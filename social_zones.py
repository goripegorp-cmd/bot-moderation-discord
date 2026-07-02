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
import os
import sqlite3
from datetime import datetime, timezone

import discord
from discord.ext import tasks

# Rôle STAFF autorisé à VOIR toutes les zones (anti-triche) + expulser/fermer (owner 2026-07-02,
# ID 1465411944205914275). Surchargable par env SOCIAL_STAFF_ROLE_ID.
try:
    _ZONE_STAFF_ROLE_ID = int(os.environ.get("SOCIAL_STAFF_ROLE_ID", "1465411944205914275") or 0)
except Exception:
    _ZONE_STAFF_ROLE_ID = 0

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
_boot_done = False             # garde anti-reconnexion : ne détruit les zones qu'au 1er boot
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


def _staff_role(guild):
    """Le rôle staff configuré (ou None)."""
    try:
        return guild.get_role(_ZONE_STAFF_ROLE_ID) if (guild and _ZONE_STAFF_ROLE_ID) else None
    except Exception:
        return None


def _is_zone_staff(member) -> bool:
    """Staff = rôle staff configuré OU is_staff_fn injecté (admin/mod). FAIL-SAFE False."""
    try:
        if member is None:
            return False
        if _ZONE_STAFF_ROLE_ID and any(
                getattr(r, "id", 0) == _ZONE_STAFF_ROLE_ID for r in getattr(member, "roles", []) or []):
            return True
        if _is_staff is not None:
            try:
                return bool(_is_staff(member))
            except Exception:
                return False
    except Exception:
        return False
    return False


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
            # owner 2026-07-02 : liste de bannissement PAR ZONE. Un membre EXPULSÉ ne peut plus
            # re-rejoindre la MÊME zone via le bouton « Rejoindre » (sinon l'expulsion ne sert à
            # rien). Un gestionnaire peut le ré-inviter explicitement (l'ajout lève le ban).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS social_zone_bans (
                    zone_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (zone_id, user_id)
                )
            """)
            # owner 2026-07-02 : vocal dédié optionnel d'une zone de groupe (créé par le créateur,
            # supprimé avec la zone). ALTER best-effort (colonne peut déjà exister).
            try:
                await db.execute("ALTER TABLE social_zones ADD COLUMN voice_channel_id INTEGER DEFAULT 0")
            except Exception:
                pass
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


async def _is_zone_banned(zone_id: int, user_id: int) -> bool:
    """True si l'utilisateur a été EXPULSÉ de cette zone (bloque le re-join self-service).
    FAIL-OPEN (au doute, on laisse rejoindre — dispo > blocage, ce n'est pas un ban sécu)."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM social_zone_bans WHERE zone_id=? AND user_id=? LIMIT 1",
                (zone_id, user_id)) as cur:
                return (await cur.fetchone()) is not None
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
    # STAFF (owner 2026-07-02) : le rôle staff VOIT toutes les zones (anti-triche) et peut y
    # intervenir/expulser/fermer. Vue + historique + écriture (pour avertir en cas de triche).
    st = _staff_role(guild)
    if st is not None:
        ow[st] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True)
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
    """Supprime le(s) salon(s) texte + vocal (idempotent), PUIS met channel_id/voice_channel_id
    à 0 — mais SEULEMENT si la/les suppression(s) Discord ont réussi. Ainsi, sur échec transitoire
    (429/5xx), la ligne garde ses ids != 0 et le watchdog (qui balaie les zones 'ended' avec
    channel_id != 0) réessaiera au tour suivant → ZÉRO salon fantôme, sans attendre un reboot."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT guild_id, channel_id, voice_channel_id FROM social_zones WHERE id=?",
                (zone_id,)) as c:
                row = await c.fetchone()
        if not row:
            return
        gid = int(row[0])
        ch_id = int(row[1] or 0)
        vc_id = int((row[2] if len(row) > 2 else 0) or 0)
        _zone_channels.discard(ch_id)
        _zone_channels.discard(vc_id)
        _activity_writes.pop(ch_id, None)
        _activity_writes.pop(vc_id, None)
        all_gone = True
        g = _bot.get_guild(gid) if _bot else None
        if g:
            for _cid in (ch_id, vc_id):   # salon texte + vocal dédié éventuel
                if _cid <= 0:             # 0 = néant, -1 = réservation vocale (pas encore de salon)
                    continue
                ch = g.get_channel(_cid)
                if ch is not None:
                    try:
                        await ch.delete(reason="Zone sociale fermée")
                    except Exception as ex:
                        # Échec transitoire → on GARDE la référence pour retry par le watchdog.
                        print(f"[social_zones delete channel {_cid}] {ex}")
                        all_gone = False
        elif ch_id > 0 or vc_id > 0:
            # Guilde indisponible (reconnexion) → on ne peut pas confirmer la suppression :
            # ne pas zéroter, laisser le watchdog/boot réessayer.
            all_gone = False
        try:
            async with _get_db() as db:
                if all_gone and (ch_id or vc_id):
                    await db.execute(
                        "UPDATE social_zones SET channel_id=0, voice_channel_id=0 WHERE id=?",
                        (zone_id,))
                # Nettoie la liste de bannissement de la zone (rowid mort après fermeture).
                await db.execute("DELETE FROM social_zone_bans WHERE zone_id=?", (zone_id,))
                await db.commit()
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
    + balaie les 'ended' dont le salon traîne encore. Le set mémoire repart vide.

    GARDE anti-reconnexion : on_ready se redéclenche à CHAQUE reconnexion gateway ; sans
    cette garde, une simple reconnexion détruirait les zones EN COURS d'utilisation. On ne
    nettoie donc qu'au TOUT PREMIER boot du process (les vrais orphelins viennent du process
    précédent ; les zones créées dans CE process restent vivantes sur reconnexion)."""
    global _boot_done
    if _get_db is None:
        return
    if _boot_done:
        return
    _boot_done = True
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
    # Filet anti-fantôme : balaie les salons orphelins (reboot en pleine création où
    # channel_id n'a pas pu être persisté → la ligne ne les référence pas).
    await _boot_reconcile_orphans()


async def _boot_reconcile_orphans():
    """Supprime tout salon résiduel sous nos catégories portant notre préfixe et NON référencé
    par une ligne active (orphelin d'un reboot mid-création). Sans danger : skippe les salons
    d'une zone active (course rare avec une création concurrente au boot)."""
    if _bot is None:
        return
    prefixes = tuple(p for p in (_PREFIX.get(k) for k in _KINDS) if p)
    cat_names = set(_CATEGORY.values())
    active_ids = set()
    active_vc_ids = set()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT channel_id FROM social_zones WHERE status='active' AND channel_id != 0") as cur:
                active_ids = {int(r[0]) for r in await cur.fetchall()}
            # Vocaux référencés par une zone active → à NE PAS supprimer.
            try:
                async with db.execute(
                    "SELECT voice_channel_id FROM social_zones "
                    "WHERE status='active' AND voice_channel_id != 0") as cur:
                    active_vc_ids = {int(r[0]) for r in await cur.fetchall()}
            except Exception:
                active_vc_ids = set()
    except Exception:
        active_ids = set()
    removed = 0
    try:
        for g in list(_bot.guilds):
            try:
                for cat in list(getattr(g, "categories", []) or []):
                    if cat.name not in cat_names:
                        continue
                    for ch in list(getattr(cat, "channels", []) or []):
                        nm = getattr(ch, "name", "") or ""
                        cid = int(getattr(ch, "id", 0))
                        is_voice = isinstance(ch, discord.VoiceChannel)
                        if is_voice:
                            # Vocal orphelin d'un reboot : sous notre catégorie, préfixe 🔊,
                            # non référencé par une zone active.
                            if cid in active_vc_ids:
                                continue
                            if nm.startswith("🔊 "):
                                try:
                                    await ch.delete(reason="Vocal de zone sociale orphelin (reboot)")
                                    removed += 1
                                except Exception:
                                    pass
                            continue
                        if cid in active_ids:
                            continue
                        if any(nm.startswith(p + "-") for p in prefixes):
                            try:
                                await ch.delete(reason="Zone sociale orpheline (reboot)")
                                removed += 1
                            except Exception:
                                pass
            except Exception:
                continue
        if removed:
            print(f"[social_zones reconcile] {removed} salon(s) orphelin(s) supprimé(s)")
    except Exception as ex:
        print(f"[social_zones reconcile] {ex}")


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
            # Ne ferme PAS un groupe dont le vocal est OCCUPÉ (des gens parlent sans taper) :
            # on rafraîchit son activité pour qu'il survive au tour suivant.
            if await _voice_is_active(zid):
                await _touch_activity(zid)
                continue
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


async def _voice_is_active(zone_id: int) -> bool:
    """True si la zone possède un vocal dédié où ≥1 membre (non-bot) est connecté.
    → empêche le watchdog de fermer un groupe pendant que des gens parlent en vocal."""
    try:
        vc_id = await _zone_voice_id(zone_id)
        if not vc_id or _bot is None:
            return False
        z = await _get_zone(zone_id)
        if not z:
            return False
        g = _bot.get_guild(int(z["guild_id"]))
        vc = g.get_channel(vc_id) if g else None
        if vc is None:
            return False
        return any(not getattr(m, "bot", False) for m in getattr(vc, "members", []) or [])
    except Exception:
        return False


async def _touch_activity(zone_id: int):
    """Rafraîchit last_activity (best-effort) — garde une zone vivante."""
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE social_zones SET last_activity=CURRENT_TIMESTAMP WHERE id=?", (zone_id,))
            await db.commit()
    except Exception:
        pass


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
            # ch_id peut être le salon TEXTE (channel_id) ou le chat du VOCAL (voice_channel_id).
            await db.execute(
                "UPDATE social_zones SET last_activity=CURRENT_TIMESTAMP "
                "WHERE status='active' AND (channel_id=? OR voice_channel_id=?)", (ch_id, ch_id))
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
            "• **➕ Ajouter un membre** : le créateur invite directement quelqu'un du serveur.\n"
            "• **🔊 Créer un vocal** : ouvre un salon vocal privé rien que pour le groupe.\n"
            "• **👢 Expulser** : le créateur (ou le staff) retire un membre.\n"
            "• Cliquez sur **🔒 Fermer** quand c'est terminé.\n"
            "• La zone se **ferme toute seule** après un moment sans activité.")
    e = discord.Embed(title=title, description=desc, color=_COLOR.get(kind, 0x5865F2))
    if len(members) > 1:
        e.add_field(name="Participants",
                    value=", ".join(m.mention for m in members if m is not None) or "—",
                    inline=False)
    return e


def _panel_view(zone_id: int, kind: str):
    """Panneau de GESTION persistant, posté dans le salon de la zone (owner 2026-07-02).
    GROUPE : ➕ Ajouter un membre · 🔊 Créer un vocal · 👢 Expulser · 🔒 Fermer.
    TRADE (2 pers., NON extensible) : 👢 Expulser (staff) · 🔒 Fermer.
    Tous les boutons sont des DynamicItems → re-câblés au boot, survivent aux redéploiements."""
    v = discord.ui.View(timeout=None)
    zid = int(zone_id)
    if kind == "group":
        v.add_item(discord.ui.Button(
            label="➕ Ajouter un membre", style=discord.ButtonStyle.success,
            custom_id=f"szone_add:{zid}"))
        v.add_item(discord.ui.Button(
            label="🔊 Créer un vocal", style=discord.ButtonStyle.primary,
            custom_id=f"szone_voice:{zid}"))
    v.add_item(discord.ui.Button(
        label="👢 Expulser", style=discord.ButtonStyle.secondary,
        custom_id=f"szone_expel:{zid}"))
    label = "🔒 Fermer le trade" if kind == "trade" else "🔒 Fermer la zone"
    v.add_item(discord.ui.Button(
        label=label, style=discord.ButtonStyle.danger,
        custom_id=f"szone_close:{zid}"))
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
        # défer déjà envoyé → résout l'éphémère (sinon spinner « thinking… » figé côté client)
        return await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
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
            # channel_id n'a pas pu être mémorisé → tout chemin de suppression raterait ce
            # salon (channel_id resté 0) = FANTÔME permanent. On nettoie immédiatement.
            try:
                await ch.delete(reason="échec persistance zone sociale")
            except Exception:
                pass
            try:
                async with _get_db() as db:
                    await db.execute("DELETE FROM social_zones WHERE id=?", (zone_id,))
                    await db.commit()
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Erreur à la création, réessaie.")
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
        # défer déjà envoyé → résout l'éphémère (sinon spinner « thinking… » figé côté client)
        return await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
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
        # Expulsé de CETTE zone → ne peut pas re-rejoindre en self-service (un gestionnaire
        # peut le ré-inviter explicitement via ➕ Ajouter, ce qui lève le ban).
        if await _is_zone_banned(zone_id, member.id):
            return await _safe_followup(
                i, content="🚫 Un gestionnaire t'a retiré de cette zone — tu ne peux pas la rejoindre.")
        # Claim ATOMIQUE du slot AVANT d'accorder l'accès (anti-dépassement de cap sur clics
        # concurrents — sinon 2 « Rejoindre » simultanés ouvrent un trade « privé à 2 » à 3).
        # INSERT … SELECT … WHERE count<cap AND NOT déjà-membre : SQLite sérialise les writers,
        # un seul gagne la dernière place (rowcount==1).
        max_m = _MAX_MEMBERS.get(z["kind"], 2)
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO social_zone_members(zone_id, user_id) "
                    "SELECT ?, ? WHERE "
                    "(SELECT COUNT(*) FROM social_zone_members WHERE zone_id=?) < ? "
                    "AND NOT EXISTS(SELECT 1 FROM social_zone_members WHERE zone_id=? AND user_id=?)",
                    (zone_id, member.id, zone_id, max_m, zone_id, member.id))
                claimed = getattr(cur, "rowcount", 0) == 1
                await db.commit()
        except Exception as ex:
            print(f"[social_zones join claim] {ex}")
            return await _safe_followup(i, content="❌ Erreur, réessaie.")
        if not claimed:
            if await _is_member(zone_id, member.id):
                return await _safe_followup(i, content=f"✅ Tu es déjà dans : {ch.mention}")
            return await _safe_followup(i, content="🚪 Cette zone est **complète**.")
        # Slot gagné → accorde l'accès. Si l'octroi échoue, on REND le slot (anti-place fantôme).
        try:
            await ch.set_permissions(member, overwrite=_member_overwrite(),
                                     reason="Rejoint la zone sociale")
            # Si un vocal de groupe existe déjà, ouvre-lui aussi l'accès (best-effort).
            _vc_id = await _zone_voice_id(zone_id)
            if _vc_id:
                _vc = guild.get_channel(_vc_id)
                if _vc is not None:
                    try:
                        await _vc.set_permissions(member, overwrite=_voice_member_overwrite(),
                                                  reason="Rejoint la zone sociale")
                    except Exception:
                        pass
        except Exception as ex:
            print(f"[social_zones join set_permissions] {ex}")
            try:
                async with _get_db() as db:
                    await db.execute(
                        "DELETE FROM social_zone_members WHERE zone_id=? AND user_id=?",
                        (zone_id, member.id))
                    await db.commit()
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Impossible de t'ajouter, réessaie.")
        try:
            async with _get_db() as db:
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
        # défer déjà envoyé → résout l'éphémère (sinon spinner « thinking… » figé côté client)
        return await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
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
#  GESTION DU SALON (owner 2026-07-02) — le CRÉATEUR a une vraie gestion + le STAFF
#  peut intervenir. Tout en boutons/menus (« les commandes, ils ne savent pas faire »).
#     ➕ Ajouter un membre (groupe)   🔊 Créer un vocal (groupe)   👢 Expulser   🔒 Fermer
# ═══════════════════════════════════════════════════════════════════════════════
def _can_manage(i: discord.Interaction, zone) -> bool:
    """Peut gérer la zone = son CRÉATEUR ou un STAFF (rôle configuré/admin). FAIL-SAFE False."""
    try:
        if not zone:
            return False
        if int(i.user.id) == int(zone["creator_id"]):
            return True
        member = i.user if isinstance(i.user, discord.Member) else (
            i.guild.get_member(i.user.id) if i.guild else None)
        return _is_zone_staff(member)
    except Exception:
        return False


def _voice_member_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True, connect=True, speak=True, stream=True, use_voice_activation=True)


async def _zone_member_ids(zone_id: int) -> list:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id FROM social_zone_members WHERE zone_id=?", (zone_id,)) as cur:
                return [int(r[0]) for r in await cur.fetchall()]
    except Exception:
        return []


async def _zone_voice_id(zone_id: int) -> int:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT voice_channel_id FROM social_zones WHERE id=?", (zone_id,)) as cur:
                r = await cur.fetchone()
        return int((r[0] if r else 0) or 0)
    except Exception:
        return 0


# ─── ➕ AJOUTER UN MEMBRE (groupe uniquement) ──────────────────────────────────
async def add_member_click(i: discord.Interaction, zone_id: int):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
    try:
        z = await _get_zone(zone_id)
        if not z or z["status"] != "active" or not z["channel_id"]:
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
        if z["kind"] != "group":
            return await _safe_followup(
                i, content="🤝 Un salon d'échange est **strictement à 2 personnes** — on n'y "
                           "ajoute pas de membre.")
        if not _can_manage(i, z):
            return await _safe_followup(
                i, content="🔒 Seuls le **créateur** du groupe ou le **staff** peuvent ajouter "
                           "des membres.")
        if (await _member_count(zone_id)) >= _MAX_MEMBERS.get("group", 6):
            return await _safe_followup(i, content="👥 Ce groupe est déjà **complet**.")
        return await _safe_followup(
            i, content="Choisis la personne à ajouter au groupe :",
            view=_AddMemberSelectView(zone_id))
    except Exception as ex:
        print(f"[social_zones add_member_click] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


class _AddMemberSelectView(discord.ui.View):
    """Menu éphémère (transitoire) : sélectionne un membre du serveur à ajouter au groupe."""
    def __init__(self, zone_id: int):
        super().__init__(timeout=120)
        self.zone_id = int(zone_id)
        sel = discord.ui.UserSelect(
            placeholder="Sélectionne un membre à ajouter…", min_values=1, max_values=1)
        sel.callback = self._on_select
        self.add_item(sel)
        self._sel = sel

    async def _on_select(self, i: discord.Interaction):
        try:
            user = self._sel.values[0] if self._sel.values else None
        except Exception:
            user = None
        await _do_add_member(i, self.zone_id, user)


async def _do_add_member(i: discord.Interaction, zone_id: int, user):
    if not await _safe_defer(i):
        return
    try:
        if user is None:
            return await _safe_followup(i, content="❌ Aucun membre sélectionné.")
        z = await _get_zone(zone_id)
        if not z or z["status"] != "active" or not z["channel_id"]:
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
        if z["kind"] != "group":
            return await _safe_followup(i, content="🤝 Un trade reste à 2 personnes.")
        if not _can_manage(i, z):
            return await _safe_followup(i, content="🔒 Réservé au créateur ou au staff.")
        guild = i.guild
        if guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        member = guild.get_member(int(getattr(user, "id", 0))) or (
            user if isinstance(user, discord.Member) else None)
        if member is None or getattr(member, "bot", False):
            return await _safe_followup(i, content="❌ Membre invalide (ou bot).")
        ch = guild.get_channel(int(z["channel_id"]))
        if ch is None:
            await close_zone(zone_id, linger=False)
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
        if await _is_member(zone_id, member.id):
            return await _safe_followup(
                i, content=f"ℹ️ {member.display_name} est déjà dans le groupe.")
        # Claim ATOMIQUE du slot (anti-dépassement de cap sur ajouts concurrents).
        max_m = _MAX_MEMBERS.get("group", 6)
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO social_zone_members(zone_id, user_id) "
                    "SELECT ?, ? WHERE "
                    "(SELECT COUNT(*) FROM social_zone_members WHERE zone_id=?) < ? "
                    "AND NOT EXISTS(SELECT 1 FROM social_zone_members WHERE zone_id=? AND user_id=?)",
                    (zone_id, member.id, zone_id, max_m, zone_id, member.id))
                claimed = getattr(cur, "rowcount", 0) == 1
                await db.commit()
        except Exception as ex:
            print(f"[social_zones add claim] {ex}")
            return await _safe_followup(i, content="❌ Erreur, réessaie.")
        if not claimed:
            return await _safe_followup(i, content="👥 Le groupe est **complet**.")
        # Accorde l'accès texte (+ vocal si présent). Échec → rollback du slot (anti-fantôme).
        try:
            await ch.set_permissions(member, overwrite=_member_overwrite(),
                                     reason="Ajouté à la zone par le créateur/staff")
            vc_id = await _zone_voice_id(zone_id)
            if vc_id:
                vc = guild.get_channel(vc_id)
                if vc is not None:
                    try:
                        await vc.set_permissions(member, overwrite=_voice_member_overwrite(),
                                                 reason="Ajouté à la zone")
                    except Exception:
                        pass
        except Exception as ex:
            print(f"[social_zones add set_permissions] {ex}")
            try:
                async with _get_db() as db:
                    await db.execute(
                        "DELETE FROM social_zone_members WHERE zone_id=? AND user_id=?",
                        (zone_id, member.id))
                    await db.commit()
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Impossible de l'ajouter, réessaie.")
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE social_zones SET last_activity=CURRENT_TIMESTAMP WHERE id=?", (zone_id,))
                # Ajout explicite par un gestionnaire → lève un éventuel ban (ré-invitation voulue).
                await db.execute(
                    "DELETE FROM social_zone_bans WHERE zone_id=? AND user_id=?",
                    (zone_id, member.id))
                await db.commit()
        except Exception:
            pass
        # Salue + MENTIONNE le nouvel arrivant DANS le salon (il reçoit une notif → il trouve la zone).
        try:
            await ch.send(
                f"👋 {member.mention}, tu as été **ajouté à ce groupe** par {i.user.mention} ! "
                "Bienvenue — c'est ici que ça se passe. 🎯",
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False, users=[member]))
        except Exception:
            pass
        await _safe_followup(i, content=f"✅ {member.display_name} a été ajouté à {ch.mention}.")
    except Exception as ex:
        print(f"[social_zones _do_add_member] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


# ─── 🔊 CRÉER UN VOCAL (groupe uniquement) ─────────────────────────────────────
async def voice_click(i: discord.Interaction, zone_id: int):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
    try:
        z = await _get_zone(zone_id)
        if not z or z["status"] != "active" or not z["channel_id"]:
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
        if z["kind"] != "group":
            return await _safe_followup(
                i, content="🔊 Le vocal n'est disponible que pour les **groupes**.")
        if not _can_manage(i, z):
            return await _safe_followup(
                i, content="🔒 Seuls le **créateur** du groupe ou le **staff** peuvent créer le vocal.")
        guild = i.guild
        if guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        # État courant du slot vocal : 0 = aucun, -1 = réservé (création en cours), >0 = existe.
        existing = await _zone_voice_id(zone_id)
        if existing == -1:
            return await _safe_followup(
                i, content="🔊 Le vocal est **en cours de création**, un petit instant…")
        if existing > 0:
            vc = guild.get_channel(existing)
            if vc is not None:
                return await _safe_followup(
                    i, content=f"🔊 Le vocal existe déjà : **{vc.name}** "
                               "(rejoins-le depuis la barre de gauche).")
            # existing > 0 mais salon disparu (supprimé à la main) → on recrée en réservant
            # DEPUIS cette valeur exacte (anti-course : un seul passe de `existing` à -1).
        if not guild.me.guild_permissions.manage_channels:
            return await _safe_followup(
                i, content="❌ Le bot n'a pas la permission « Gérer les salons ».")
        # ── RÉSERVATION ATOMIQUE (exactly-once) ────────────────────────────────────────
        # _click_too_soon ne bloque que le MÊME user : 2 gestionnaires différents (créateur +
        # staff) peuvent cliquer en même temps. Sans réservation, chacun crée un vocal → 1 devient
        # orphelin. On passe voice_channel_id de {0 | valeur stale lue} → -1 : SQLite sérialise,
        # un SEUL gagne (rowcount==1). Le perdant est renvoyé sans rien créer.
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "UPDATE social_zones SET voice_channel_id=-1 "
                    "WHERE id=? AND status='active' AND voice_channel_id=?",
                    (zone_id, int(existing)))
                reserved = getattr(cur, "rowcount", 0) == 1
                await db.commit()
        except Exception as ex:
            print(f"[social_zones voice reserve] {ex}")
            return await _safe_followup(i, content="❌ Erreur, réessaie.")
        if not reserved:
            return await _safe_followup(
                i, content="🔊 Le vocal vient d'être créé (ou est en cours) — regarde la barre de gauche.")
        ch = guild.get_channel(int(z["channel_id"]))
        cat = getattr(ch, "category", None) if ch is not None else None
        if cat is None:
            cat = await _get_category(guild, "group")
        me = guild.me
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
            me: discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True, manage_channels=True,
                manage_permissions=True, move_members=True),
        }
        st = _staff_role(guild)
        if st is not None:
            ow[st] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        members = []
        for uid in await _zone_member_ids(zone_id):
            m = guild.get_member(uid)
            if m is not None:
                ow[m] = _voice_member_overwrite()
                members.append(m)
        base = (getattr(ch, "name", "") or "groupe").replace(_PREFIX.get("group", ""), "").strip("-")
        vc_name = f"🔊 {base or 'groupe'}"[:95]
        try:
            vc = await guild.create_voice_channel(
                name=vc_name, category=cat, overwrites=ow, reason="Vocal de zone sociale")
        except Exception as ex:
            print(f"[social_zones create voice] {ex}")
            # LIBÈRE la réservation (−1 → 0) pour permettre une nouvelle tentative.
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE social_zones SET voice_channel_id=0 "
                        "WHERE id=? AND voice_channel_id=-1", (zone_id,))
                    await db.commit()
            except Exception:
                pass
            return await _safe_followup(i, content="❌ Impossible de créer le vocal, réessaie.")
        # Persiste l'id RÉEL — SEULEMENT si la réservation est toujours à -1 (sinon la zone a été
        # fermée/réinitialisée entre-temps → on supprime le vocal pour ne pas laisser de fantôme).
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "UPDATE social_zones SET voice_channel_id=?, last_activity=CURRENT_TIMESTAMP "
                    "WHERE id=? AND voice_channel_id=-1", (vc.id, zone_id))
                persisted = getattr(cur, "rowcount", 0) == 1
                await db.commit()
        except Exception as ex:
            print(f"[social_zones persist voice] {ex}")
            persisted = False
        if not persisted:
            try:
                await vc.delete(reason="zone fermée/réinitialisée pendant la création du vocal")
            except Exception:
                pass
            # Si la réservation traîne encore (cas erreur DB, pas fermeture), on la libère.
            try:
                async with _get_db() as db:
                    await db.execute(
                        "UPDATE social_zones SET voice_channel_id=0 "
                        "WHERE id=? AND voice_channel_id=-1", (zone_id,))
                    await db.commit()
            except Exception:
                pass
            return await _safe_followup(
                i, content="⌛ La zone a été fermée entre-temps — vocal annulé.")
        # Le chat texte du vocal fait partie de la zone → modéré, sans nudge, et son activité
        # garde la zone vivante (lookup O(1) mémoire, comme le salon texte).
        try:
            _zone_channels.add(int(vc.id))
        except Exception:
            pass
        # Filet : un membre qui a rejoint PENDANT la création (entre le snapshot et le persist)
        # n'a pas eu son overwrite vocal via join_zone (voice_channel_id valait -1). On re-scanne
        # et on complète les accès manquants (course rare, best-effort).
        try:
            have = {int(m.id) for m in members}
            for uid in await _zone_member_ids(zone_id):
                if uid in have:
                    continue
                m2 = guild.get_member(uid)
                if m2 is not None:
                    try:
                        await vc.set_permissions(m2, overwrite=_voice_member_overwrite(),
                                                 reason="Vocal de zone (membre tardif)")
                    except Exception:
                        pass
        except Exception:
            pass
        # Annonce DANS le salon + MENTIONNE tous les membres (qu'ils sachent que c'est pour eux).
        if ch is not None:
            try:
                await ch.send(
                    f"🔊 **Vocal du groupe créé** par {i.user.mention} → **{vc.name}**.\n"
                    "Rejoignez-le depuis la barre de gauche pour parler ensemble ! 🎧\n"
                    + (" ".join(m.mention for m in members) if members else ""),
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, roles=False, users=members))
            except Exception:
                pass
        await _safe_followup(i, content=f"✅ Vocal **{vc.name}** créé pour le groupe.")
    except Exception as ex:
        print(f"[social_zones voice_click] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


# ─── 👢 EXPULSER (créateur ou staff) ───────────────────────────────────────────
async def expel_click(i: discord.Interaction, zone_id: int):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
    try:
        z = await _get_zone(zone_id)
        if not z or z["status"] != "active" or not z["channel_id"]:
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
        if not _can_manage(i, z):
            return await _safe_followup(
                i, content="🔒 Seuls le **créateur** ou le **staff** peuvent expulser des membres.")
        guild = i.guild
        if guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        creator_id = int(z["creator_id"])
        options = []
        for uid in await _zone_member_ids(zone_id):
            if uid == creator_id:
                continue  # on ne s'expulse pas soi-même → pour fermer, bouton 🔒
            m = guild.get_member(uid)
            label = (m.display_name if m is not None else str(uid))[:80] or str(uid)
            options.append(discord.SelectOption(label=label, value=str(uid)))
        if not options:
            return await _safe_followup(
                i, content="👥 Personne à expulser (il n'y a que le créateur). "
                           "Pour fermer, utilise **🔒 Fermer**.")
        return await _safe_followup(
            i, content="Choisis le membre à expulser :",
            view=_ExpelSelectView(zone_id, options))
    except Exception as ex:
        print(f"[social_zones expel_click] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


class _ExpelSelectView(discord.ui.View):
    """Menu éphémère (transitoire) : sélectionne le membre de la zone à expulser."""
    def __init__(self, zone_id: int, options: list):
        super().__init__(timeout=120)
        self.zone_id = int(zone_id)
        sel = discord.ui.Select(
            placeholder="Sélectionne un membre à expulser…",
            min_values=1, max_values=1, options=options[:25])
        sel.callback = self._on_select
        self.add_item(sel)
        self._sel = sel

    async def _on_select(self, i: discord.Interaction):
        try:
            uid = int(self._sel.values[0]) if self._sel.values else 0
        except Exception:
            uid = 0
        await _do_expel(i, self.zone_id, uid)


async def _do_expel(i: discord.Interaction, zone_id: int, user_id: int):
    if not await _safe_defer(i):
        return
    try:
        if not user_id:
            return await _safe_followup(i, content="❌ Aucun membre sélectionné.")
        z = await _get_zone(zone_id)
        if not z or z["status"] != "active":
            return await _safe_followup(i, content="✅ Zone déjà fermée.")
        if not _can_manage(i, z):
            return await _safe_followup(i, content="🔒 Réservé au créateur ou au staff.")
        if int(user_id) == int(z["creator_id"]):
            return await _safe_followup(
                i, content="🚫 On n'expulse pas le créateur. Pour fermer la zone, utilise **🔒 Fermer**.")
        guild = i.guild
        if guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        # ORDRE FAIL-CLOSED (expulsion = action de SÉCURITÉ) : on RETIRE d'abord l'accès, et on ne
        # supprime la ligne (+ ban) QUE si la révocation a réussi. Sinon on GARDE tout et on signale
        # l'échec — jamais de « ✅ expulsé » alors que la personne garde l'accès.
        # Membre présent → set_permissions(overwrite=None). Membre PARTI du serveur (pas dans le
        # cache) → il n'a plus accès de toute façon ; on retire l'overwrite résiduel en best-effort
        # (API bas niveau) SANS bloquer l'expulsion (sinon un départ figerait la liste).
        member = guild.get_member(int(user_id))
        ch = guild.get_channel(int(z["channel_id"])) if z["channel_id"] else None
        vc_id = await _zone_voice_id(zone_id)
        vc = guild.get_channel(vc_id) if (vc_id and vc_id > 0) else None

        async def _revoke(channel) -> bool:
            """Retire l'accès du membre à ce salon. True = accès effectivement retiré (ou déjà
            absent). Pour un membre PARTI, best-effort → toujours True (pas d'accès résiduel réel)."""
            if channel is None:
                return True
            if member is not None:
                try:
                    await channel.set_permissions(member, overwrite=None, reason="Expulsé de la zone")
                    return True
                except Exception as ex:
                    print(f"[social_zones expel revoke {getattr(channel,'id',0)}] {ex}")
                    return False
            # Membre hors cache/parti : retire l'overwrite résiduel via l'API bas niveau.
            try:
                await channel._state.http.delete_channel_permissions(
                    channel.id, int(user_id), reason="Expulsé (membre parti)")
            except Exception:
                pass
            return True

        revoke_ok = await _revoke(ch)
        if not await _revoke(vc):
            revoke_ok = False
        # Déconnecte du vocal si connecté (best-effort, n'affecte pas revoke_ok).
        if vc is not None and member is not None:
            try:
                mv = getattr(member, "voice", None)
                if mv and mv.channel and int(mv.channel.id) == int(vc.id):
                    await member.move_to(None, reason="Expulsé de la zone")
            except Exception:
                pass
        if not revoke_ok:
            # On n'a PAS pu retirer l'accès → on ne touche pas la DB (le membre reste listé,
            # donc ré-essayable) et on dit la vérité au gestionnaire.
            return await _safe_followup(
                i, content="❌ Impossible de retirer les permissions (vérifie les droits du bot). "
                           "Le membre est **toujours dans la liste** — réessaie.")
        # Révocation confirmée → retire la ligne + BAN (anti re-join) de façon atomique.
        try:
            async with _get_db() as db:
                await db.execute(
                    "DELETE FROM social_zone_members WHERE zone_id=? AND user_id=?",
                    (zone_id, int(user_id)))
                await db.execute(
                    "INSERT OR IGNORE INTO social_zone_bans(zone_id, user_id) VALUES(?,?)",
                    (zone_id, int(user_id)))
                await db.commit()
        except Exception:
            pass
        name = member.display_name if member is not None else str(user_id)
        if ch is not None:
            try:
                await ch.send(f"👢 **{name}** a été retiré de la zone par {i.user.mention}.",
                              allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                pass
        await _safe_followup(i, content=f"✅ {name} a été expulsé.")
    except Exception as ex:
        print(f"[social_zones _do_expel] {ex}")
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


class ZoneAddButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"szone_add:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="➕ Ajouter un membre", style=discord.ButtonStyle.success,
            custom_id=f"szone_add:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await add_member_click(i, self.zid)


class ZoneVoiceButton(discord.ui.DynamicItem[discord.ui.Button],
                      template=r"szone_voice:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="🔊 Créer un vocal", style=discord.ButtonStyle.primary,
            custom_id=f"szone_voice:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await voice_click(i, self.zid)


class ZoneExpelButton(discord.ui.DynamicItem[discord.ui.Button],
                      template=r"szone_expel:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="👢 Expulser", style=discord.ButtonStyle.secondary,
            custom_id=f"szone_expel:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await expel_click(i, self.zid)


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(
            ZoneCreateButton, ZoneJoinButton, ZoneCloseButton,
            ZoneAddButton, ZoneVoiceButton, ZoneExpelButton)
    except Exception as ex:
        print(f"[social_zones register] {ex}")
