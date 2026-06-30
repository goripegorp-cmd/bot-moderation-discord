"""
social_zones.py — Phase 280 : ZONES SOCIALES 100% BOUTONS (groupes d'entraide + trades privés).

POURQUOI (demande owner 2026-06-30) : « Les commandes, ils ne savent pas faire. »
  - Un message de COORDINATION (« aidez moi à kill la dragonfly », « qui veut faire le raid »)
    → le bot propose un bouton **« Créer un groupe »** sous le message. L'auteur clique → une ZONE
    privée (salon texte) est créée rien que pour lui ; les autres voient un bouton **« Rejoindre »**
    et entrent dans la zone. Si personne ne rejoint, il reste seul dans sa zone (comme demandé).
  - Un message de TRADE (« je trade X contre Y », « wts/wtb/wtt », « j'échange … contre … »)
    → bouton **« Ouvrir un trade »**. L'auteur clique → salon privé à 2 (lui + la personne
    mentionnée, ou + le 1er qui rejoint). Les 2 sont MENTIONNÉS dans LEUR salon. Le bot **modère**
    déjà tous les salons (anti-arnaque/insultes via on_message) → modération GRATUITE, rien à câbler.
    Le salon **se ferme tout seul à l'inactivité**. **1 seul trade par CRÉATEUR** (anti-abus), mais
    on PEUT rejoindre les trades des autres.

GARANTIES (modelées sur solo_instances.py, éprouvé en prod) :
  - Création ATOMIQUE anti-double-salon : index UNIQUE partiel (guild_id, creator_id, kind) WHERE
    status='active' → 2 clics simultanés = 1 seule zone (le 2e INSERT échoue proprement).
  - Nettoyage TRIPLE COUCHE : (a) fermeture explicite (bouton 🔒, claim atomique exactly-once),
    (b) watchdog d'INACTIVITÉ (ferme toute zone sans message depuis le TTL — basé sur last_activity,
    pas sur la création), (c) boot_cleanup (ferme les zones orphelines au démarrage). Zéro fantôme.
  - Cap de sécurité par guilde (limite salons Discord). Anti-429 : cooldown par clic + edit in-place.
  - JAMAIS de MP, JAMAIS de ping @everyone/rôle dans les nudges. Les 2 users du trade sont mentionnés
    UNIQUEMENT dans leur propre salon privé (exactement ce que l'owner a demandé).

Le module est AUTONOME : AUCUNE commande slash (entrée 100% par boutons de détection en chat).
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import discord
from discord.ext import tasks

# ─── Dépendances injectées (setup) ─────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_add_log = None          # async (guild, message, level, category=...) -> None   (optionnel)
_is_staff = None         # (member) -> bool                                       (optionnel)

# ─── Réglages ──────────────────────────────────────────────────────────────────
_KINDS = ("group", "trade")
_CATEGORY = {"group": "👥 Groupes", "trade": "🤝 Échanges"}
_PREFIX = {"group": "👥-groupe", "trade": "🤝-trade"}
_MAX_MEMBERS = {"group": 6, "trade": 2}        # trade = créateur + 1 partenaire
_TTL_SEC = {"group": 1800, "trade": 1500}      # inactivité avant fermeture auto (30 / 25 min)
_MAX_ACTIVE_ZONES = 30                          # plafond de salons sociaux par guilde
_CLICK_CD = 1.5                                 # anti-spam par utilisateur (s)
_ACTIVITY_THROTTLE_SEC = 45                     # n'écrit last_activity au + qu'1×/45 s/salon
_CLOSE_LINGER_SEC = 4                           # le message « fermé » reste visible avant delete

_LABEL = {"group": "groupe", "trade": "trade"}
_COLOR = {"group": 0x5865F2, "trade": 0x2ECC71}

# ─── État mémoire (reconstruit au boot) ────────────────────────────────────────
_zone_channels: set = set()    # {channel_id} des salons sociaux ACTIFS (lookup O(1) on_message)
_last_click: dict = {}         # {uid: epoch} anti-429
_activity_writes: dict = {}    # {channel_id: epoch} throttle des écritures last_activity
_pending_closes: set = set()   # réf. aux tâches de fermeture différée (anti-GC)


def setup(bot_instance, get_db_fn, db_get_fn, add_log_fn=None, is_staff_fn=None):
    global _bot, _get_db, _db_get, _add_log, _is_staff
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _add_log = add_log_fn
    _is_staff = is_staff_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS social_zones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    creator_id INTEGER NOT NULL,
                    channel_id INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',
                    topic TEXT DEFAULT '',
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_social_active "
                "ON social_zones(guild_id, status)")
            # Anti-double-salon ATOMIQUE : 1 seule zone active par (guilde, créateur, type).
            # Un 2e INSERT (double-clic) lève IntegrityError → géré proprement.
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_social_one_active "
                "ON social_zones(guild_id, creator_id, kind) WHERE status='active'")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS social_zone_members (
                    zone_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (zone_id, user_id)
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[social_zones init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers interaction (autonomes — pas de dépendance bot.py)
# ═══════════════════════════════════════════════════════════════════════════════
async def _safe_defer(i: discord.Interaction, ephemeral: bool = True) -> bool:
    try:
        await i.response.defer(ephemeral=ephemeral)
        return True
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        return True
    except Exception:
        return False


async def _safe_followup(i: discord.Interaction, **kwargs):
    kwargs.setdefault("ephemeral", True)
    try:
        return await i.followup.send(**kwargs)
    except Exception:
        return None


def is_zone_channel(channel_id) -> bool:
    """True si ce salon est une zone sociale ACTIVE (lookup O(1) mémoire). Utilisé par
    on_message/les hooks pour ne JAMAIS nudger à l'intérieur d'une zone."""
    try:
        return int(channel_id or 0) in _zone_channels
    except Exception:
        return False


def _click_too_soon(uid: int) -> bool:
    try:
        now = datetime.now(timezone.utc).timestamp()
        if now - _last_click.get(uid, 0.0) < _CLICK_CD:
            return True
        _last_click[uid] = now
        if len(_last_click) > 5000:
            _last_click.clear()
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Requêtes DB
# ═══════════════════════════════════════════════════════════════════════════════
async def _active_zone_count(guild_id: int) -> int:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM social_zones WHERE guild_id=? AND status='active'",
                (guild_id,)) as cur:
                r = await cur.fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


async def _get_zone(zone_id: int):
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, kind, creator_id, channel_id, status, topic "
                "FROM social_zones WHERE id=?", (zone_id,)) as cur:
                r = await cur.fetchone()
        if not r:
            return None
        return {"id": r[0], "guild_id": r[1], "kind": r[2], "creator_id": r[3],
                "channel_id": r[4], "status": r[5], "topic": r[6] or ""}
    except Exception:
        return None


async def _member_count(zone_id: int) -> int:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM social_zone_members WHERE zone_id=?", (zone_id,)) as cur:
                r = await cur.fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


async def _is_member(zone_id: int, user_id: int) -> bool:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM social_zone_members WHERE zone_id=? AND user_id=? LIMIT 1",
                (zone_id, user_id)) as cur:
                r = await cur.fetchone()
        return r is not None
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Salon privé : catégorie + création + overwrites
# ═══════════════════════════════════════════════════════════════════════════════
async def _get_category(guild: discord.Guild, kind: str):
    name = _CATEGORY.get(kind, "👥 Zones")
    for c in guild.categories:
        if c.name == name:
            return c
    me = guild.me
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                        manage_channels=True, manage_permissions=True),
    }
    try:
        return await guild.create_category(name=name, overwrites=ow, reason="Zones sociales")
    except Exception as ex:
        print(f"[social_zones category] {ex}")
        return None


def _member_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True, send_messages=True, read_message_history=True,
        attach_files=True, embed_links=True, add_reactions=True)


async def _create_zone_channel(guild: discord.Guild, kind: str,
                               members: list, slug_name: str):
    """Crée le salon texte privé (membres + bot). Retourne le salon ou None."""
    cat = await _get_category(guild, kind)
    me = guild.me
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                        manage_channels=True, manage_permissions=True,
                                        read_message_history=True),
    }
    for m in members:
        if m is not None:
            ow[m] = _member_overwrite()
    name = f"{_PREFIX.get(kind, 'zone')}-{slug_name}"[:95]
    try:
        return await guild.create_text_channel(
            name=name, category=cat, overwrites=ow,
            reason=f"Zone sociale ({_LABEL.get(kind, kind)})")
    except Exception as ex:
        print(f"[social_zones create channel] {ex}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Fermeture (claim atomique exactly-once + delete idempotent)
# ═══════════════════════════════════════════════════════════════════════════════
async def _claim_close(zone_id: int) -> bool:
    """UPDATE status='ended' WHERE status='active' → True SSI ce call a gagné."""
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE social_zones SET status='ended' WHERE id=? AND status='active'",
                (zone_id,))
            await db.commit()
            return getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[social_zones _claim_close] {ex}")
        return False


async def _delete_zone_channel(zone_id: int):
    """Supprime le salon (idempotent) + channel_id=0 + retire du set mémoire."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, channel_id FROM social_zones WHERE id=?", (zone_id,)) as c:
                row = await c.fetchone()
            if not row:
                return
            gid, ch_id = int(row[0]), int(row[1] or 0)
            if ch_id:
                await db.execute("UPDATE social_zones SET channel_id=0 WHERE id=?", (zone_id,))
                await db.commit()
        _zone_channels.discard(ch_id)
        _activity_writes.pop(ch_id, None)
        if ch_id == 0:
            return
        g = _bot.get_guild(gid) if _bot else None
        if g:
            ch = g.get_channel(ch_id)
            if ch is not None:
                try:
                    await ch.delete(reason="Zone sociale fermée")
                except Exception:
                    pass
    except Exception as ex:
        print(f"[social_zones _delete_zone_channel] {ex}")


async def _delayed_delete(zone_id: int):
    try:
        await asyncio.sleep(_CLOSE_LINGER_SEC)
    except Exception:
        pass
    await _delete_zone_channel(zone_id)


async def close_zone(zone_id: int, linger: bool = False) -> bool:
    """Ferme une zone (claim atomique). linger=True laisse le message visible quelques
    secondes (fermeture manuelle) ; False = suppression immédiate (watchdog/boot)."""
    won = await _claim_close(zone_id)
    if linger:
        try:
            t = asyncio.create_task(_delayed_delete(zone_id))
            _pending_closes.add(t)
            t.add_done_callback(_pending_closes.discard)
        except Exception:
            await _delete_zone_channel(zone_id)
    else:
        await _delete_zone_channel(zone_id)
    return won


async def boot_cleanup():
    """Au boot : ferme toutes les zones 'active' (salons orphelins après reboot Railway)
    + balaie les 'ended' dont le salon traîne encore. Le set mémoire repart vide."""
    if _get_db is None:
        return
    _zone_channels.clear()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM social_zones WHERE status='active'") as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
            async with db.execute(
                "SELECT id FROM social_zones WHERE status='ended' AND channel_id != 0") as cur:
                stale = [int(r[0]) for r in await cur.fetchall()]
        for zid in ids:
            await close_zone(zid, linger=False)
        for zid in stale:
            await _delete_zone_channel(zid)
        if ids or stale:
            print(f"[social_zones boot_cleanup] {len(ids)} active(s) + "
                  f"{len(stale)} salon(s) résiduel(s) nettoyé(s)")
    except Exception as ex:
        print(f"[social_zones boot_cleanup] {ex}")


@tasks.loop(minutes=5)
async def zone_watchdog():
    """Ferme toute zone sans activité depuis son TTL (INACTIVITÉ, basé sur last_activity)
    + filet : supprime les salons des zones 'ended' qui traînent."""
    if _get_db is None:
        return
    try:
        stale_ids = []
        async with _get_db() as db:
            for kind in _KINDS:
                ttl = _TTL_SEC.get(kind, 1800)
                async with db.execute(
                    "SELECT id FROM social_zones WHERE status='active' AND kind=? AND "
                    "datetime(last_activity) < datetime('now', ?)",
                    (kind, f'-{ttl} seconds')) as cur:
                    stale_ids += [int(r[0]) for r in await cur.fetchall()]
            async with db.execute(
                "SELECT id FROM social_zones WHERE status='ended' AND channel_id != 0 AND "
                "datetime(started_at) < datetime('now', '-60 seconds')") as cur:
                ended = [int(r[0]) for r in await cur.fetchall()]
        for zid in stale_ids:
            # message d'adieu best-effort puis fermeture
            await _farewell(zid)
            await close_zone(zid, linger=False)
        for zid in ended:
            await _delete_zone_channel(zid)
    except Exception as ex:
        print(f"[social_zones zone_watchdog] {ex}")


@zone_watchdog.before_loop
async def _zw_wait():
    if _bot is not None:
        await _bot.wait_until_ready()


async def _farewell(zone_id: int):
    """Petit message d'adieu (best-effort) avant fermeture pour inactivité."""
    try:
        z = await _get_zone(zone_id)
        if not z or not z.get("channel_id"):
            return
        g = _bot.get_guild(int(z["guild_id"])) if _bot else None
        ch = g.get_channel(int(z["channel_id"])) if g else None
        if ch is not None:
            try:
                await ch.send("💤 Zone fermée automatiquement (inactivité). À bientôt !")
            except Exception:
                pass
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  ACTIVITÉ : maintient la zone vivante tant qu'on y parle (anti-fermeture prématurée)
# ═══════════════════════════════════════════════════════════════════════════════
async def note_message(msg):
    """Appelé (backgroundé) depuis on_message. Si le message est dans un salon de zone
    ACTIF, rafraîchit last_activity (throttlé 1×/45 s/salon). Lookup O(1) mémoire d'abord
    → coût quasi nul pour les 99% de messages hors-zone. FAIL-SAFE total."""
    try:
        ch = getattr(msg, "channel", None)
        author = getattr(msg, "author", None)
        if ch is None or author is None or getattr(author, "bot", False):
            return
        ch_id = int(getattr(ch, "id", 0) or 0)
        if ch_id not in _zone_channels:
            return
        now = datetime.now(timezone.utc).timestamp()
        if now - _activity_writes.get(ch_id, 0.0) < _ACTIVITY_THROTTLE_SEC:
            return
        _activity_writes[ch_id] = now
        if len(_activity_writes) > 5000:
            # purge bornée (garde les plus récents implicitement via re-remplissage)
            _activity_writes.clear()
            _activity_writes[ch_id] = now
        async with _get_db() as db:
            await db.execute(
                "UPDATE social_zones SET last_activity=CURRENT_TIMESTAMP "
                "WHERE channel_id=? AND status='active'", (ch_id,))
            await db.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  CRÉATION DE ZONE (bouton « Créer un groupe » / « Ouvrir un trade »)
# ═══════════════════════════════════════════════════════════════════════════════
def _zone_intro_embed(kind: str, creator: discord.Member, members: list) -> discord.Embed:
    if kind == "trade":
        title = "🤝 Salon d'échange privé"
        desc = (
            f"Bienvenue {creator.mention} ! Voici **votre salon d'échange privé**.\n\n"
            "• Discutez de votre échange ici, à l'abri des regards.\n"
            "• ⚠️ Le bot **surveille** ce salon contre les arnaques — méfiez-vous quand même "
            "des liens et des offres trop belles.\n"
            "• Cliquez sur **🔒 Fermer le trade** une fois l'échange terminé.\n"
            "• Le salon se **ferme tout seul** après un moment sans message.")
    else:
        title = "👥 Zone de groupe"
        desc = (
            f"Zone créée par {creator.mention} ! Réunissez-vous ici pour vous coordonner.\n\n"
            "• Organisez votre boss / raid / donjon dans ce salon dédié.\n"
            "• D'autres joueurs peuvent **rejoindre** via le bouton sous le message d'origine.\n"
            "• Cliquez sur **🔒 Fermer** quand c'est terminé.\n"
            "• La zone se **ferme toute seule** après un moment sans activité.")
    e = discord.Embed(title=title, description=desc, color=_COLOR.get(kind, 0x5865F2))
    if len(members) > 1:
        e.add_field(name="Participants",
                    value=", ".join(m.mention for m in members if m is not None) or "—",
                    inline=False)
    return e


def _panel_view(zone_id: int, kind: str):
    """Vue persistante du panneau dans le salon : bouton 🔒 Fermer (DynamicItem)."""
    v = discord.ui.View(timeout=None)
    label = "🔒 Fermer le trade" if kind == "trade" else "🔒 Fermer la zone"
    v.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.danger,
                                 custom_id=f"szone_close:{int(zone_id)}"))
    return v


async def create_zone(i: discord.Interaction, kind: str, author_id: int, partner_id: int = 0):
    """Crée la zone privée. Réservé à l'AUTEUR du message d'origine (nominatif).
    Pour le trade, ajoute le partenaire mentionné s'il y en a un. Retourne après avoir
    édité le nudge d'origine (ajoute le bouton « Rejoindre » si pertinent)."""
    if kind not in _KINDS:
        return
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        # Nominatif : seul l'auteur détecté peut ouvrir SA zone.
        if i.user.id != int(author_id):
            return await _safe_followup(
                i, content=f"ℹ️ Ce bouton est pour <@{int(author_id)}>. Si tu veux aussi "
                           f"{'échanger' if kind == 'trade' else 'monter un groupe'}, écris-le "
                           "dans le chat et le bot te le proposera. 🙂")
        guild = i.guild
        creator = i.user if isinstance(i.user, discord.Member) else guild.get_member(i.user.id)
        if creator is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        if not guild.me.guild_permissions.manage_channels:
            return await _safe_followup(
                i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")
        if await _active_zone_count(guild.id) >= _MAX_ACTIVE_ZONES:
            return await _safe_followup(
                i, content="⏳ Trop de zones ouvertes en ce moment — réessaie dans un instant.")

        partner = None
        if kind == "trade" and partner_id:
            partner = guild.get_member(int(partner_id))
            if partner is not None and (partner.bot or partner.id == creator.id):
                partner = None

        # 1) Claim ATOMIQUE : réserve la ligne. Double-clic / déjà-une-zone → IntegrityError.
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO social_zones(guild_id, kind, creator_id, channel_id, status) "
                    "VALUES(?,?,?,0,'active')",
                    (guild.id, kind, creator.id))
                zone_id = cur.lastrowid
                await db.commit()
        except sqlite3.IntegrityError:
            verb = "trade" if kind == "trade" else "groupe"
            return await _safe_followup(
                i, content=f"⚠️ Tu as déjà un {verb} en cours — ferme-le d'abord "
                           "(bouton 🔒 dans ton salon) avant d'en ouvrir un autre.")
        except Exception as ex:
            print(f"[social_zones create INSERT] {ex}")
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")

        # 2) Crée le salon. Échec → rollback de la ligne réservée (sinon zone fantôme bloquante).
        members = [creator] + ([partner] if partner is not None else [])
        ch = await _create_zone_channel(guild, kind, members, creator.display_name)
        if ch is None:
            try:
                async with _get_db() as db:
                    await db.execute("DELETE FROM social_zones WHERE id=?", (zone_id,))
                    await db.commit()
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Impossible de créer le salon, réessaie.")

        # 3) Persiste channel_id + membres + marque le salon comme actif (set mémoire).
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE social_zones SET channel_id=?, last_activity=CURRENT_TIMESTAMP "
                    "WHERE id=?", (ch.id, zone_id))
                await db.execute(
                    "INSERT OR IGNORE INTO social_zone_members(zone_id, user_id) VALUES(?,?)",
                    (zone_id, creator.id))
                if partner is not None:
                    await db.execute(
                        "INSERT OR IGNORE INTO social_zone_members(zone_id, user_id) VALUES(?,?)",
                        (zone_id, partner.id))
                await db.commit()
        except Exception as ex:
            print(f"[social_zones create persist] {ex}")
        _zone_channels.add(int(ch.id))

        # 4) Poste le panneau dans le salon (mentionne les participants — c'est LEUR salon privé).
        try:
            mention_txt = " ".join(m.mention for m in members if m is not None)
            await ch.send(
                content=mention_txt,
                embed=_zone_intro_embed(kind, creator, members),
                view=_panel_view(zone_id, kind),
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False,
                    users=[m for m in members if m is not None]))
        except Exception as ex:
            print(f"[social_zones create panel] {ex}")

        # 5) Édite le nudge d'origine : remplace « Créer/Ouvrir » par « Rejoindre » (sauf trade
        #    déjà complet à 2). Best-effort.
        try:
            full = (await _member_count(zone_id)) >= _MAX_MEMBERS.get(kind, 2)
            await _edit_nudge_after_create(i, kind, zone_id, ch, creator, full)
        except Exception:
            pass

        # 6) Log discret (optionnel).
        if _add_log is not None:
            try:
                await _add_log(
                    guild,
                    f"🧩 Zone {_LABEL.get(kind, kind)} ouverte par {creator.mention} → {ch.mention}",
                    "info", category="social_zones")
            except Exception:
                pass

        await _safe_followup(i, content=f"✅ Ton salon est prêt : {ch.mention}")
    except Exception as ex:
        print(f"[social_zones create_zone] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


async def _edit_nudge_after_create(i, kind, zone_id, channel, creator, full):
    """Transforme le nudge d'origine en invitation à REJOINDRE (ou en simple info si complet)."""
    msg = getattr(i, "message", None)
    if msg is None:
        return
    if kind == "trade":
        head = f"🤝 Trade ouvert par {creator.display_name} → {channel.mention}"
        join_label = "🤝 Rejoindre le trade"
    else:
        head = f"👥 Groupe ouvert par {creator.display_name} → {channel.mention}"
        join_label = "➕ Rejoindre le groupe"
    v = discord.ui.View(timeout=None)
    if not full:
        v.add_item(discord.ui.Button(
            label=join_label, style=discord.ButtonStyle.success,
            custom_id=f"szone_join:{int(zone_id)}"))
    try:
        await msg.edit(
            content=head + ("" if not full else "  ·  _complet_"),
            embed=None, view=(v if not full else None),
            allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  REJOINDRE UNE ZONE (bouton « Rejoindre »)
# ═══════════════════════════════════════════════════════════════════════════════
async def join_zone(i: discord.Interaction, zone_id: int):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        z = await _get_zone(zone_id)
        if not z or z["status"] != "active" or not z["channel_id"]:
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
        guild = i.guild
        member = i.user if isinstance(i.user, discord.Member) else guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        ch = guild.get_channel(int(z["channel_id"]))
        if ch is None:
            # Salon disparu → ferme la ligne pour cohérence.
            await close_zone(zone_id, linger=False)
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
        if await _is_member(zone_id, member.id):
            return await _safe_followup(i, content=f"✅ Tu es déjà dans : {ch.mention}")
        if (await _member_count(zone_id)) >= _MAX_MEMBERS.get(z["kind"], 2):
            return await _safe_followup(
                i, content="🚪 Cette zone est **complète**.")
        # Ajoute l'accès au salon + enregistre le membre.
        try:
            await ch.set_permissions(member, overwrite=_member_overwrite(),
                                     reason="Rejoint la zone sociale")
        except Exception as ex:
            print(f"[social_zones join set_permissions] {ex}")
            return await _safe_followup(i, content="❌ Impossible de t'ajouter, réessaie.")
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT OR IGNORE INTO social_zone_members(zone_id, user_id) VALUES(?,?)",
                    (zone_id, member.id))
                await db.execute(
                    "UPDATE social_zones SET last_activity=CURRENT_TIMESTAMP WHERE id=?",
                    (zone_id,))
                await db.commit()
        except Exception:
            pass
        try:
            await ch.send(f"👋 {member.mention} a rejoint la zone !",
                          allowed_mentions=discord.AllowedMentions(
                              everyone=False, roles=False, users=[member]))
        except Exception:
            pass
        # Si la zone est désormais complète, retire le bouton « Rejoindre » du nudge.
        try:
            if (await _member_count(zone_id)) >= _MAX_MEMBERS.get(z["kind"], 2):
                msg = getattr(i, "message", None)
                if msg is not None:
                    base = (msg.content or "").split("  ·  ")[0]
                    await msg.edit(content=base + "  ·  _complet_", view=None,
                                   allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            pass
        await _safe_followup(i, content=f"✅ Tu as rejoint : {ch.mention}")
    except Exception as ex:
        print(f"[social_zones join_zone] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


# ═══════════════════════════════════════════════════════════════════════════════
#  FERMER UNE ZONE (bouton 🔒 dans le salon)
# ═══════════════════════════════════════════════════════════════════════════════
async def close_zone_click(i: discord.Interaction, zone_id: int):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return
    try:
        z = await _get_zone(zone_id)
        if not z or z["status"] != "active":
            return await _safe_followup(i, content="✅ Déjà fermée.")
        member = i.user if isinstance(i.user, discord.Member) else (
            i.guild.get_member(i.user.id) if i.guild else None)
        # Autorisé : créateur, membre de la zone, ou staff.
        allowed = (i.user.id == int(z["creator_id"])) or await _is_member(zone_id, i.user.id)
        if not allowed and _is_staff is not None and member is not None:
            try:
                allowed = bool(_is_staff(member))
            except Exception:
                allowed = False
        if not allowed:
            return await _safe_followup(
                i, content="🔒 Seuls les participants (ou le staff) peuvent fermer cette zone.")
        # Message d'adieu best-effort dans le salon puis fermeture différée (linger).
        try:
            ch = i.channel
            if ch is not None:
                await ch.send(f"🔒 Zone fermée par {i.user.mention}. Le salon va disparaître…",
                              allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            pass
        await close_zone(zone_id, linger=True)
        await _safe_followup(i, content="✅ Zone fermée.")
    except Exception as ex:
        print(f"[social_zones close_zone_click] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


# ═══════════════════════════════════════════════════════════════════════════════
#  DynamicItems persistants (re-enregistrés au boot)
# ═══════════════════════════════════════════════════════════════════════════════
class ZoneCreateButton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r"szone_create:(?P<kind>[a-z]+):(?P<uid>\d+):(?P<pid>\d+)"):
    def __init__(self, kind: str, uid: int, pid: int = 0):
        label = "🤝 Ouvrir un trade" if kind == "trade" else "👥 Créer un groupe"
        super().__init__(discord.ui.Button(
            label=label, style=discord.ButtonStyle.primary,
            custom_id=f"szone_create:{kind}:{int(uid)}:{int(pid)}"))
        self.kind = kind
        self.uid = int(uid)
        self.pid = int(pid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["kind"], int(match["uid"]), int(match["pid"]))

    async def callback(self, i: discord.Interaction):
        await create_zone(i, self.kind, self.uid, self.pid)


class ZoneJoinButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"szone_join:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="➕ Rejoindre", style=discord.ButtonStyle.success,
            custom_id=f"szone_join:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await join_zone(i, self.zid)


class ZoneCloseButton(discord.ui.DynamicItem[discord.ui.Button],
                      template=r"szone_close:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="🔒 Fermer", style=discord.ButtonStyle.danger,
            custom_id=f"szone_close:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await close_zone_click(i, self.zid)


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(ZoneCreateButton, ZoneJoinButton, ZoneCloseButton)
    except Exception as ex:
        print(f"[social_zones register] {ex}")
