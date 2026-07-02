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

# owner 2026-07-02 — CONFIANCE des échanges : rôle médiateur (0 = repli sur le staff), seuil de
# signalements avant le rôle « ⚠️ Prudence », nom du rôle Prudence (auto-créé). Surchargeables env.
try:
    _TRADE_MEDIATOR_ROLE_ID = int(os.environ.get("TRADE_MEDIATOR_ROLE_ID", "0") or 0)
except Exception:
    _TRADE_MEDIATOR_ROLE_ID = 0
try:
    _TRADE_SCAM_THRESHOLD = max(2, int(os.environ.get("TRADE_SCAM_THRESHOLD", "3") or 3))
except Exception:
    _TRADE_SCAM_THRESHOLD = 3
_PRUDENCE_ROLE_NAME = "⚠️ Prudence"
# Anti-farm alt : une même PAIRE de traders ne crédite la confiance qu'une fois par fenêtre (72 h).
_TRADE_PAIR_WINDOW_SEC = 72 * 3600

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
_PENDING_TTL_SEC = 900                          # invitation/consentement en attente : purge à 15 min
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
            # Anti-double-salon ATOMIQUE : 1 seule zone active OU EN ATTENTE par (guilde, créateur,
            # type). Un 2e INSERT (double-clic, ou 2e demande alors qu'une 1re est pending) lève
            # IntegrityError → géré proprement. owner 2026-07-02 : couvre désormais 'pending'
            # (groupe/trade en attente d'un 2e participant, salon pas encore créé) → DROP+CREATE
            # pour appliquer la nouvelle condition WHERE même si l'index existait déjà.
            try:
                await db.execute("DROP INDEX IF EXISTS idx_social_one_active")
            except Exception:
                pass
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_social_one_active "
                "ON social_zones(guild_id, creator_id, kind) "
                "WHERE status IN ('active','pending','materializing')")
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
            # owner 2026-07-02 — CONFIANCE des échanges (anti-arnaque) :
            # trade_reputation : compteur « échanges réussis » (badge) + signalements reçus.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trade_reputation (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    successful INTEGER DEFAULT 0,
                    reported INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            # trade_confirm : qui a cliqué « ✅ Échange réussi » (les 2 requis → +1 confiance chacun).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trade_confirm (
                    zone_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (zone_id, user_id)
                )
            """)
            # trade_scam_report : 1 signalement / rapporteur / échange (anti-spam).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trade_scam_report (
                    zone_id INTEGER NOT NULL,
                    reporter_id INTEGER NOT NULL,
                    PRIMARY KEY (zone_id, reporter_id)
                )
            """)
            # trade_log : historique (staff : enquêter sur un signalement — qui/quoi/issue).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trade_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    zone_id INTEGER,
                    a_id INTEGER, b_id INTEGER,
                    item TEXT DEFAULT '',
                    outcome TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_trade_log_guild ON trade_log(guild_id, created_at)")
            # trade_pair_credit : anti-farm alt — 1 crédit de confiance par PAIRE / fenêtre (a<b).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trade_pair_credit (
                    guild_id INTEGER NOT NULL,
                    a INTEGER NOT NULL,
                    b INTEGER NOT NULL,
                    last_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, a, b)
                )
            """)
            # owner 2026-07-02 : vocal dédié optionnel d'une zone de groupe (créé par le créateur,
            # supprimé avec la zone). ALTER best-effort (colonne peut déjà exister).
            try:
                await db.execute("ALTER TABLE social_zones ADD COLUMN voice_channel_id INTEGER DEFAULT 0")
            except Exception:
                pass
            # owner 2026-07-02 : partenaire d'un TRADE en attente de consentement mutuel + id du
            # message d'invitation/consentement (pour l'éditer en « expiré »/« créé »). ALTER best-effort.
            try:
                await db.execute("ALTER TABLE social_zones ADD COLUMN partner_id INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE social_zones ADD COLUMN nudge_channel_id INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE social_zones ADD COLUMN nudge_message_id INTEGER DEFAULT 0")
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
                "SELECT id, guild_id, kind, creator_id, channel_id, status, topic, partner_id "
                "FROM social_zones WHERE id=?", (zone_id,)) as cur:
                r = await cur.fetchone()
        if not r:
            return None
        return {"id": r[0], "guild_id": r[1], "kind": r[2], "creator_id": r[3],
                "channel_id": r[4], "status": r[5], "topic": r[6] or "",
                "partner_id": int((r[7] if len(r) > 7 else 0) or 0)}
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
            # PENDING/MATERIALIZING d'avant le reboot = invitations mortes (le nudge RAM a disparu) :
            # on purge les lignes (pas de salon à supprimer, channel_id=0). Le nudge Discord traînant
            # sera balayé par son delete_after natif ou restera inerte (bouton → « plus disponible »).
            async with db.execute(
                "SELECT id FROM social_zones WHERE status IN ('pending','materializing')") as cur:
                pend = [int(r[0]) for r in await cur.fetchall()]
        for zid in ids:
            await close_zone(zid, linger=False)
        for zid in stale:
            await _delete_zone_channel(zid)
        for zid in pend:
            # Un 'materializing' crashé peut avoir CRÉÉ un salon (channel_id persisté en phase 1) :
            # on le supprime via _delete_zone_channel (no-op si channel_id=0) AVANT de purger la ligne.
            await _delete_zone_channel(zid)
        if pend:
            try:
                async with _get_db() as db:
                    await db.execute("DELETE FROM social_zones WHERE status IN ('pending','materializing')")
                    for zid in pend:
                        await db.execute("DELETE FROM social_zone_members WHERE zone_id=?", (zid,))
                    await db.commit()
            except Exception:
                pass
        if ids or stale or pend:
            print(f"[social_zones boot_cleanup] {len(ids)} active(s) + "
                  f"{len(stale)} salon(s) résiduel(s) + {len(pend)} en attente nettoyé(s)")
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
                # Filet DÉFENSE-EN-PROFONDEUR (owner 2026-07-02) : un crash entre la création du
                # salon et la persistance de channel_id, AVEC une catégorie indisponible, laisse un
                # salon à la RACINE (sans catégorie) que la boucle par-catégorie ci-dessus ne voit
                # pas. On balaie donc aussi les salons racine portant notre préfixe, non référencés.
                try:
                    for ch in list(getattr(g, "text_channels", []) or []):
                        if getattr(ch, "category", None) is not None:
                            continue
                        nm = getattr(ch, "name", "") or ""
                        cid = int(getattr(ch, "id", 0))
                        if cid in active_ids:
                            continue
                        if any(nm.startswith(p + "-") for p in prefixes):
                            try:
                                await ch.delete(reason="Zone sociale orpheline racine (reboot)")
                                removed += 1
                            except Exception:
                                pass
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
            # owner 2026-07-02 : PENDING périmé (groupe sans 2e joueur / trade non accepté) →
            # rien ne s'est créé, on purge la ligne + on éteint le nudge (« expiré »). Couvre aussi
            # un 'materializing' resté coincé (crash en pleine création). Basé sur started_at.
            async with db.execute(
                "SELECT id FROM social_zones WHERE status IN ('pending','materializing') AND "
                "datetime(started_at) < datetime('now', ?)",
                (f'-{_PENDING_TTL_SEC} seconds',)) as cur:
                pend = [int(r[0]) for r in await cur.fetchall()]
        for zid in pend:
            await _mark_nudge_dead(zid, "⌛ Invitation expirée — personne n'a rejoint/accepté.")
            # 'materializing' resté coincé (crash) peut avoir un salon → on le supprime d'abord.
            await _delete_zone_channel(zid)
            try:
                async with _get_db() as db:
                    await db.execute(
                        "DELETE FROM social_zones WHERE id=? AND status IN ('pending','materializing')",
                        (zid,))
                    await db.execute("DELETE FROM social_zone_members WHERE zone_id=?", (zid,))
                    await db.commit()
            except Exception:
                pass
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
def _zone_intro_embed(kind: str, creator: discord.Member, members: list,
                      topic: str = "", rep_lines: str = "") -> discord.Embed:
    if kind == "trade":
        title = "🤝 Salon d'échange privé"
        desc = (
            "Voici **votre salon d'échange privé**, rien que pour vous deux.\n\n"
            "• Mettez-vous d'accord ici, à l'abri des regards.\n"
            "• **✅ Échange réussi** (les 2) → +1 **confiance** 🛡️ chacun (badge public).\n"
            "• **🚨 Signaler une arnaque** prévient le staff · **⚖️ Médiateur** pour les gros trades.\n"
            "• Cliquez sur **🔒 Fermer le trade** une fois terminé (fermeture auto sinon).")
    else:
        title = "👥 Zone de groupe"
        desc = (
            f"Groupe de {creator.mention if creator else 'joueur'} — réunissez-vous ici !\n\n"
            "• Organisez votre boss / raid / donjon dans ce salon dédié.\n"
            "• **➕ Ajouter un membre** · **🔊 Créer un vocal** · **👢 Expulser** (créateur/staff).\n"
            "• Cliquez sur **🔒 Fermer** quand c'est terminé.\n"
            "• La zone se **ferme toute seule** après un moment sans activité.")
    e = discord.Embed(title=title, description=desc, color=_COLOR.get(kind, 0x5865F2))
    if kind == "trade":
        t = (topic or "").strip()
        if t:
            e.add_field(name="📦 Échange proposé", value=f"_{t[:400]}_", inline=False)
        if rep_lines:
            e.add_field(name="🛡️ Confiance des traders", value=rep_lines[:1024], inline=False)
        # AVERTISSEMENT ANTI-ARNAQUE (owner 2026-07-02) : très visible, à chaque salon d'échange.
        e.add_field(
            name="⚠️ Méfiance — anti-arnaque",
            value=("• **Jamais** de « cross-trade » ou de paiement/échange **en premier** sur "
                   "confiance : faites l'échange **en même temps**.\n"
                   "• Méfiez-vous des offres **trop belles**, des liens, et de quelqu'un qui "
                   "**presse**.\n"
                   "• Un **screenshot** ne prouve rien. En cas de doute → **staff** + bouton 🔒.\n"
                   "• Le bot surveille ce salon, mais **restez prudents** : une arnaque validée "
                   "par vous n'est **pas** remboursable."),
            inline=False)
    if len(members) > 1:
        e.add_field(name="Participants",
                    value=", ".join(m.mention for m in members if m is not None) or "—",
                    inline=False)
    return e


def _panel_view(zone_id: int, kind: str):
    """Panneau de GESTION persistant, posté dans le salon de la zone (owner 2026-07-02).
    GROUPE : ➕ Ajouter · 🔊 Vocal · 👢 Expulser · 🔒 Fermer.
    TRADE : ✅ Échange réussi · 🚨 Signaler · ⚖️ Médiateur · 🔒 Fermer (confiance/anti-arnaque).
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
        v.add_item(discord.ui.Button(
            label="🔒 Fermer la zone", style=discord.ButtonStyle.danger,
            custom_id=f"szone_close:{zid}"))
    else:  # trade — boutons de CONFIANCE (anti-arnaque)
        v.add_item(discord.ui.Button(
            label="✅ Échange réussi", style=discord.ButtonStyle.success,
            custom_id=f"szone_trade_done:{zid}"))
        v.add_item(discord.ui.Button(
            label="🚨 Signaler une arnaque", style=discord.ButtonStyle.danger,
            custom_id=f"szone_trade_scam:{zid}"))
        v.add_item(discord.ui.Button(
            label="⚖️ Médiateur", style=discord.ButtonStyle.secondary,
            custom_id=f"szone_trade_med:{zid}"))
        v.add_item(discord.ui.Button(
            label="🔒 Fermer le trade", style=discord.ButtonStyle.secondary,
            custom_id=f"szone_close:{zid}"))
    return v


# Mémoire courte : résumé d'échange capturé AU MOMENT du nudge (le custom_id d'un bouton ne peut
# pas transporter de texte). Clé = id du message nudge ; lu par create_zone. Borné (anti-fuite).
_zone_topic_mem: dict = {}


def remember_zone_topic(msg_id: int, text: str):
    """Appelé par bot.py quand il poste le nudge d'un échange : mémorise le résumé (« je vends X
    contre Y ») pour le réafficher dans le salon d'échange. FAIL-SAFE."""
    try:
        if not text:
            return
        _zone_topic_mem[int(msg_id)] = str(text).strip()[:300]
        if len(_zone_topic_mem) > 500:
            for k in list(_zone_topic_mem.keys())[:250]:
                _zone_topic_mem.pop(k, None)
    except Exception:
        pass


async def create_zone(i: discord.Interaction, kind: str, author_id: int, partner_id: int = 0):
    """owner 2026-07-02 — LANCEMENT en 2 temps (plus de salon créé « à vide ») :
    • GROUPE : on ne crée PAS le salon tout de suite. On poste une INVITATION dans le chat ;
      le salon naît au 1er « Rejoindre » (si personne, rien n'est créé — le watchdog purge).
    • TRADE : consentement MUTUEL. On envoie une demande au partenaire (ou une proposition
      ouverte) ; le salon d'échange naît quand l'autre ACCEPTE (résumé + avertissement anti-arnaque).
    Réservé à l'AUTEUR détecté (nominatif)."""
    if kind not in _KINDS:
        return
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
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

        # Résumé d'échange capturé au nudge (trade uniquement).
        topic = ""
        nudge = getattr(i, "message", None)
        try:
            if nudge is not None:
                topic = _zone_topic_mem.pop(int(nudge.id), "") or ""
        except Exception:
            topic = ""
        n_ch_id = int(getattr(getattr(nudge, "channel", None), "id", 0) or 0)
        n_msg_id = int(getattr(nudge, "id", 0) or 0)

        partner = None
        if kind == "trade" and partner_id:
            partner = guild.get_member(int(partner_id))
            if partner is not None and (partner.bot or partner.id == creator.id):
                partner = None

        # Claim ATOMIQUE d'une ligne PENDING (statut 'pending' : PAS de salon encore). L'index
        # unique (active|pending) empêche 2 demandes simultanées du même créateur/type.
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT INTO social_zones(guild_id, kind, creator_id, channel_id, status, "
                    "topic, partner_id, nudge_channel_id, nudge_message_id) "
                    "VALUES(?,?,?,0,'pending',?,?,?,?)",
                    (guild.id, kind, creator.id, topic, (partner.id if partner else 0),
                     n_ch_id, n_msg_id))
                zone_id = cur.lastrowid
                # Le créateur est déjà « membre » de la zone en attente.
                await db.execute(
                    "INSERT OR IGNORE INTO social_zone_members(zone_id, user_id) VALUES(?,?)",
                    (zone_id, creator.id))
                await db.commit()
        except sqlite3.IntegrityError:
            verb = "trade" if kind == "trade" else "groupe"
            return await _safe_followup(
                i, content=f"⚠️ Tu as déjà un {verb} en cours — termine-le d'abord avant d'en "
                           "relancer un autre.")
        except Exception as ex:
            print(f"[social_zones create INSERT] {ex}")
            return await _safe_followup(i, content="❌ Erreur au lancement, réessaie.")

        if kind == "group":
            await _post_group_invite(i, zone_id, creator)
            return await _safe_followup(
                i, content="✅ Invitation lancée dans le chat ! Le salon du groupe se **créera dès "
                           "qu'un joueur rejoint**. S'il n'y a personne, rien n'est créé. 👍")
        # ── TRADE : consentement mutuel ──
        if partner is not None:
            await _post_trade_consent(i, zone_id, creator, partner, topic)
            return await _safe_followup(
                i, content=f"✅ Demande d'échange envoyée à **{partner.display_name}**. Le salon "
                           "s'ouvrira **s'il/elle accepte**.")
        await _post_trade_open(i, zone_id, creator, topic)
        return await _safe_followup(
            i, content="✅ Ta proposition d'échange est postée. Le salon s'ouvrira **dès que "
                       "quelqu'un accepte** l'échange.")
    except Exception as ex:
        print(f"[social_zones create_zone] {ex}")
        await _safe_followup(i, content=f"❌ Erreur : `{ex}`")


def _topic_line(topic: str) -> str:
    t = (topic or "").strip()
    return f"\n> 💬 _« {t[:200]} »_" if t else ""


async def _post_group_invite(i, zone_id: int, creator):
    """Édite le nudge d'origine en INVITATION à rejoindre le futur groupe (salon pas encore créé)."""
    msg = getattr(i, "message", None)
    if msg is None:
        return
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(
        label="➕ Rejoindre le groupe", style=discord.ButtonStyle.success,
        custom_id=f"szone_join:{int(zone_id)}"))
    try:
        await msg.edit(
            content=f"👥 **{creator.display_name}** cherche des joueurs — clique pour **rejoindre** ! "
                    "Le salon privé s'ouvre au 1er qui rejoint.",
            embed=None, view=v, allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


async def _post_trade_consent(i, zone_id: int, creator, partner, topic: str):
    """Édite le nudge en DEMANDE DE CONSENTEMENT au partenaire mentionné (mentionne les 2)."""
    msg = getattr(i, "message", None)
    if msg is None:
        return
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(
        label="✅ Accepter l'échange", style=discord.ButtonStyle.success,
        custom_id=f"szone_trade_ok:{int(zone_id)}"))
    v.add_item(discord.ui.Button(
        label="❌ Refuser", style=discord.ButtonStyle.secondary,
        custom_id=f"szone_trade_no:{int(zone_id)}"))
    try:
        badge = await _trade_badge(i.guild.id, creator.id) if i.guild else ""
    except Exception:
        badge = ""
    try:
        await msg.edit(
            content=(f"🤝 {creator.mention} propose un **échange** à {partner.mention}."
                     f"{_topic_line(topic)}\n{badge}\n{partner.mention}, tu acceptes ? "
                     "_(le salon privé s'ouvrira seulement si tu acceptes)_"),
            embed=None, view=v,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=[creator, partner]))
    except Exception:
        pass


async def _post_trade_open(i, zone_id: int, creator, topic: str):
    """Édite le nudge en PROPOSITION OUVERTE (pas de partenaire nommé) : le 1er qui accepte ouvre
    le salon d'échange avec le créateur."""
    msg = getattr(i, "message", None)
    if msg is None:
        return
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(
        label="🤝 Faire l'échange", style=discord.ButtonStyle.success,
        custom_id=f"szone_trade_ok:{int(zone_id)}"))
    try:
        badge = await _trade_badge(i.guild.id, creator.id) if i.guild else ""
    except Exception:
        badge = ""
    try:
        await msg.edit(
            content=(f"🤝 **{creator.display_name}** cherche à **échanger**.{_topic_line(topic)}\n"
                     f"{badge}\nClique **Faire l'échange** pour ouvrir un salon privé avec lui/elle."),
            embed=None, view=v, allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


async def _mark_nudge_dead(zone_id: int, text: str):
    """Édite le nudge d'une zone PENDING annulée/expirée (best-effort, retire les boutons)."""
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT nudge_channel_id, nudge_message_id FROM social_zones WHERE id=?",
                (zone_id,)) as cur:
                r = await cur.fetchone()
        if not r:
            return
        ch = _bot.get_channel(int(r[0] or 0)) if (_bot and r[0]) else None
        if ch is None or not r[1]:
            return
        try:
            msg = await ch.fetch_message(int(r[1]))
        except Exception:
            return
        await msg.edit(content=text, embed=None, view=None,
                       allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


async def _materialize_zone(zone_id: int, joiner) -> "tuple":
    """Crée RÉELLEMENT le salon d'une zone 'pending' (au 1er join d'un groupe / à l'acceptation
    d'un trade) et la passe 'active'. Claim ATOMIQUE pending→active (rowcount==1) → un seul
    matérialise (anti-double-salon sur clics concurrents). Retourne (channel|None, error_str|None)."""
    z = await _get_zone(zone_id)
    if not z:
        return None, "gone"
    if z["status"] == "active" and z["channel_id"] and _bot:
        # déjà matérialisée (course gagnée par un autre) → renvoie le salon existant
        g = _bot.get_guild(int(z["guild_id"]))
        return (g.get_channel(int(z["channel_id"])) if g else None), None
    if z["status"] == "materializing":
        return None, "race"   # matérialisation en cours par un autre clic → réessaie
    if z["status"] != "pending":
        return None, "gone"
    guild = _bot.get_guild(int(z["guild_id"])) if _bot else None
    if guild is None:
        return None, "gone"
    creator = guild.get_member(int(z["creator_id"]))
    kind = z["kind"]
    # Réserve la matérialisation : pending→'materializing' (un seul gagne).
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE social_zones SET status='materializing' WHERE id=? AND status='pending'",
                (zone_id,))
            won = getattr(cur, "rowcount", 0) == 1
            await db.commit()
    except Exception as ex:
        print(f"[social_zones materialize claim] {ex}")
        return None, "error"
    if not won:
        # quelqu'un d'autre matérialise → renvoie le salon dès qu'il existe (best-effort)
        z2 = await _get_zone(zone_id)
        if z2 and z2["channel_id"] and guild:
            return guild.get_channel(int(z2["channel_id"])), None
        return None, "race"
    members = [m for m in (creator, joiner) if m is not None]
    ch = await _create_zone_channel(guild, kind, members, (creator.display_name if creator else "zone"))
    if ch is None:
        # échec création → on REND la ligne à 'pending' (réessayable), gardé sur 'materializing'.
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE social_zones SET status='pending' WHERE id=? AND status='materializing'",
                    (zone_id,))
                await db.commit()
        except Exception:
            pass
        return None, "channel"
    # PHASE 1 — persiste channel_id AVANT le flip 'active', gardé sur status='materializing'. Ainsi,
    # un crash APRÈS cette écriture laisse channel_id != 0 → boot_cleanup route le nettoyage par
    # _delete_zone_channel (plus de salon fantôme). rowcount==0 → la ligne a disparu (refus
    # concurrent) → on supprime le salon fraîchement créé (anti-fantôme) au lieu de le garder.
    persisted = False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE social_zones SET channel_id=?, last_activity=CURRENT_TIMESTAMP "
                "WHERE id=? AND status='materializing'", (ch.id, zone_id))
            persisted = getattr(cur, "rowcount", 0) == 1
            if persisted:
                for m in members:
                    await db.execute(
                        "INSERT OR IGNORE INTO social_zone_members(zone_id, user_id) VALUES(?,?)",
                        (zone_id, m.id))
            await db.commit()
    except Exception as ex:
        print(f"[social_zones materialize persist1] {ex}")
        persisted = False
    if not persisted:
        # Course perdue / erreur DB → on ne laisse PAS de salon orphelin.
        try:
            await ch.delete(reason="zone annulée/perdue pendant la création")
        except Exception:
            pass
        # Si la ligne existe encore en 'materializing' (cas erreur DB, pas refus), on la rend.
        try:
            async with _get_db() as db:
                await db.execute(
                    "UPDATE social_zones SET status='pending', channel_id=0 "
                    "WHERE id=? AND status='materializing'", (zone_id,))
                await db.commit()
        except Exception:
            pass
        return None, "gone"
    # PHASE 2 — flip 'active' (channel_id déjà écrit → aucune fenêtre de fantôme).
    try:
        async with _get_db() as db:
            await db.execute(
                "UPDATE social_zones SET status='active' WHERE id=? AND status='materializing'",
                (zone_id,))
            await db.commit()
    except Exception:
        pass
    _zone_channels.add(int(ch.id))
    # ÉCHANGE : journal (staff/enquête) + badges de confiance des 2 traders dans l'intro.
    rep_lines = ""
    if kind == "trade":
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT INTO trade_log(guild_id, zone_id, a_id, b_id, item, outcome) "
                    "VALUES(?,?,?,?,?, 'open')",
                    (guild.id, zone_id,
                     (creator.id if creator else 0), (joiner.id if joiner else 0),
                     (z.get("topic") or "")[:300]))
                await db.commit()
        except Exception as ex:
            print(f"[social_zones trade_log insert] {ex}")   # non bloquant : le crédit n'en dépend plus
        try:
            _bl = []
            for m in members:
                _bl.append(f"• {m.mention} — {await _trade_badge(guild.id, m.id)}")
            rep_lines = "\n".join(_bl)
        except Exception:
            rep_lines = ""
    # Panneau + intro dans le salon (mentionne les participants — c'est LEUR salon privé).
    try:
        await ch.send(
            content=" ".join(m.mention for m in members),
            embed=_zone_intro_embed(kind, creator, members, topic=z.get("topic", ""),
                                    rep_lines=rep_lines),
            view=_panel_view(zone_id, kind),
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=members))
    except Exception as ex:
        print(f"[social_zones materialize panel] {ex}")
    if _add_log is not None:
        try:
            await _add_log(guild, f"🧩 Zone {_LABEL.get(kind, kind)} créée ({creator.mention if creator else '?'} "
                                  f"+ {joiner.mention if joiner else '?'}) → {ch.mention}", "info",
                           category="social_zones")
        except Exception:
            pass
    return ch, None


async def _edit_group_nudge_live(i, zone_id: int, ch, full: bool):
    """Après matérialisation d'un groupe : édite l'invitation cliquée → pointe vers le salon (garde
    le bouton « Rejoindre » tant qu'il reste de la place)."""
    msg = getattr(i, "message", None)
    if msg is None:
        return
    v = discord.ui.View(timeout=None)
    if not full:
        v.add_item(discord.ui.Button(
            label="➕ Rejoindre le groupe", style=discord.ButtonStyle.success,
            custom_id=f"szone_join:{int(zone_id)}"))
    head = (f"👥 Groupe en cours → {ch.mention}"
            + ("  ·  _complet_" if full else " — clique pour rejoindre !"))
    try:
        await msg.edit(content=head, embed=None, view=(v if not full else None),
                       allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  TRADE : consentement mutuel (✅ Accepter / ❌ Refuser) → matérialise le salon
# ═══════════════════════════════════════════════════════════════════════════════
async def trade_consent_click(i: discord.Interaction, zone_id: int, accept: bool):
    if not await _safe_defer(i):
        return
    if _click_too_soon(i.user.id):
        return await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
    try:
        if i.guild is None:
            return await _safe_followup(i, content="❌ Serveur uniquement.")
        z = await _get_zone(zone_id)
        if not z or z["kind"] != "trade":
            return await _safe_followup(i, content="⌛ Cette demande n'est plus disponible.")
        if z["status"] not in ("pending", "materializing"):
            if z["status"] == "active" and z["channel_id"]:
                _c = i.guild.get_channel(int(z["channel_id"]))
                if _c is not None:
                    return await _safe_followup(
                        i, content=f"✅ L'échange a déjà son salon : {_c.mention}")
            return await _safe_followup(i, content="⌛ Cette demande n'est plus disponible.")
        creator_id = int(z["creator_id"])
        partner_id = int(z.get("partner_id") or 0)
        clicker = i.user
        if clicker.id == creator_id:
            return await _safe_followup(
                i, content="⏳ C'est ta demande — c'est à **l'autre** d'accepter l'échange. 🙂")
        if partner_id and clicker.id != partner_id:
            return await _safe_followup(
                i, content=f"ℹ️ Cette demande d'échange est adressée à <@{partner_id}>.")
        if await _is_zone_banned(zone_id, clicker.id):
            return await _safe_followup(i, content="🚫 Tu ne peux pas rejoindre cette zone.")
        if not accept:
            # REFUS : claim ATOMIQUE 'pending'→'refused'. On ne touche JAMAIS 'materializing' (état
            # possédé par une acceptation EN COURS → sinon on supprimerait la ligne sous un salon en
            # création = fantôme). Si on ne gagne pas, c'est que l'autre a déjà accepté/est en cours.
            try:
                async with _get_db() as db:
                    cur = await db.execute(
                        "UPDATE social_zones SET status='refused' WHERE id=? AND status='pending'",
                        (zone_id,))
                    refused = getattr(cur, "rowcount", 0) == 1
                    await db.commit()
            except Exception:
                refused = False
            if not refused:
                z2 = await _get_zone(zone_id)
                if z2 and z2["status"] in ("materializing", "active"):
                    return await _safe_followup(
                        i, content="⏳ Trop tard — l'échange est en train de s'ouvrir.")
                return await _safe_followup(i, content="⌛ Cette demande n'est plus disponible.")
            await _mark_nudge_dead(zone_id, "❌ Échange refusé.")
            try:
                async with _get_db() as db:
                    await db.execute(
                        "DELETE FROM social_zones WHERE id=? AND status='refused'", (zone_id,))
                    await db.execute("DELETE FROM social_zone_members WHERE zone_id=?", (zone_id,))
                    await db.commit()
            except Exception:
                pass
            return await _safe_followup(i, content="👍 Échange refusé — la demande est annulée.")
        # ACCEPTE → matérialise le salon d'échange (créateur + partenaire).
        member = clicker if isinstance(clicker, discord.Member) else i.guild.get_member(clicker.id)
        ch2, err = await _materialize_zone(zone_id, member)
        if ch2 is None:
            if err == "race":
                return await _safe_followup(
                    i, content="⏳ Le salon se crée à l'instant… réessaie dans 2 s.")
            return await _safe_followup(i, content="⌛ Cette demande n'est plus disponible.")
        await _mark_nudge_dead(zone_id, "✅ Échange accepté — salon privé ouvert.")
        return await _safe_followup(i, content=f"✅ Échange accepté — votre salon : {ch2.mention}")
    except Exception as ex:
        print(f"[social_zones trade_consent_click] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIANCE DES ÉCHANGES (owner 2026-07-02) — anti-arnaque : compteur d'échanges
#  réussis (badge), signalement au staff, médiateur, rôle « ⚠️ Prudence » sur récidive.
# ═══════════════════════════════════════════════════════════════════════════════
async def get_trade_rep(guild_id: int, user_id: int):
    """(successful, reported) pour ce membre. (0,0) si aucune ligne / erreur."""
    if _get_db is None:
        return (0, 0)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT successful, reported FROM trade_reputation WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)) as cur:
                r = await cur.fetchone()
        if r:
            return (int(r[0] or 0), int(r[1] or 0))
    except Exception:
        pass
    return (0, 0)


async def _trade_badge(guild_id: int, user_id: int) -> str:
    """Badge de confiance affiché à côté d'un trader (nudge). Neuf = averti gentiment."""
    s, rep = await get_trade_rep(guild_id, user_id)
    if s <= 0 and rep <= 0:
        return "🆕 _(nouveau trader — 0 échange vérifié, prudence)_"
    txt = f"🛡️ **{s}** échange(s) réussi(s)"
    if rep > 0:
        txt += f" · ⚠️ **{rep}** signalement(s)"
    return txt


async def _bump_rep(guild_id: int, user_id: int, field: str, delta: int = 1) -> int:
    """Incrémente successful/reported ; retourne la nouvelle valeur (ou 0)."""
    if _get_db is None or field not in ("successful", "reported"):
        return 0
    try:
        async with _get_db() as db:
            await db.execute(
                f"INSERT INTO trade_reputation(guild_id, user_id, {field}, updated_at) "
                f"VALUES(?,?,?,CURRENT_TIMESTAMP) "
                f"ON CONFLICT(guild_id, user_id) DO UPDATE SET {field}={field}+?, "
                f"updated_at=CURRENT_TIMESTAMP",
                (guild_id, user_id, delta, delta))
            await db.commit()
            async with db.execute(
                f"SELECT {field} FROM trade_reputation WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)) as cur:
                r = await cur.fetchone()
        return int(r[0] or 0) if r else 0
    except Exception as ex:
        print(f"[social_zones _bump_rep] {ex}")
        return 0


def _mediator_role(guild):
    """Rôle médiateur configuré (env), sinon repli sur le rôle staff."""
    try:
        if _TRADE_MEDIATOR_ROLE_ID:
            r = guild.get_role(_TRADE_MEDIATOR_ROLE_ID)
            if r is not None:
                return r
    except Exception:
        pass
    return _staff_role(guild)


async def _ensure_prudence_role(guild):
    """Rôle « ⚠️ Prudence » (auto-créé, non-mentionnable, non-hoisté) — simple marqueur visible
    d'un trader signalé plusieurs fois. Fail-soft None si pas manage_roles."""
    try:
        r = discord.utils.get(guild.roles, name=_PRUDENCE_ROLE_NAME)
        if r is not None:
            return r
        if not (guild.me and guild.me.guild_permissions.manage_roles):
            return None
        return await guild.create_role(
            name=_PRUDENCE_ROLE_NAME, colour=discord.Colour(0xE67E22),
            hoist=False, mentionable=False, reason="Trader signalé plusieurs fois (anti-arnaque)")
    except Exception as ex:
        print(f"[social_zones _ensure_prudence_role] {ex}")
        return None


async def _trade_participants(zone_id: int):
    """IDs des participants de l'échange (membres de la zone)."""
    return await _zone_member_ids(zone_id)


async def _log_trade_outcome(zone_id: int, outcome: str):
    try:
        async with _get_db() as db:
            await db.execute("UPDATE trade_log SET outcome=? WHERE zone_id=?", (outcome, zone_id))
            await db.commit()
    except Exception:
        pass


async def _trade_guard(i, zone_id):
    """Garde commune aux boutons de confiance : defer + cooldown + zone trade active + clicker
    participant. Retourne (zone|None, channel|None, member|None) ; None-tuple si refusé (déjà répondu)."""
    if not await _safe_defer(i):
        return None, None, None
    if _click_too_soon(i.user.id):
        await _safe_followup(i, content="⏳ Un instant… réessaie dans une seconde.")
        return None, None, None
    if i.guild is None:
        await _safe_followup(i, content="❌ Serveur uniquement.")
        return None, None, None
    z = await _get_zone(zone_id)
    if not z or z["kind"] != "trade" or z["status"] != "active" or not z["channel_id"]:
        await _safe_followup(i, content="⌛ Cet échange n'est plus disponible.")
        return None, None, None
    if not await _is_member(zone_id, i.user.id):
        await _safe_followup(i, content="ℹ️ Seuls les **2 participants** de l'échange peuvent agir ici.")
        return None, None, None
    ch = i.guild.get_channel(int(z["channel_id"]))
    member = i.user if isinstance(i.user, discord.Member) else i.guild.get_member(i.user.id)
    return z, ch, member


async def trade_done_click(i: discord.Interaction, zone_id: int):
    z, ch, member = await _trade_guard(i, zone_id)
    if z is None:
        return
    try:
        gid = int(z["guild_id"])
        # Enregistre la confirmation du clicker.
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT OR IGNORE INTO trade_confirm(zone_id, user_id) VALUES(?,?)",
                    (zone_id, i.user.id))
                await db.commit()
                async with db.execute(
                    "SELECT COUNT(*) FROM trade_confirm WHERE zone_id=?", (zone_id,)) as cur:
                    n = int((await cur.fetchone())[0] or 0)
        except Exception:
            n = 0
        parts = await _trade_participants(zone_id)
        if n < 2:
            return await _safe_followup(
                i, content="✅ Ta confirmation est prise. En attente de **l'autre participant**…")
        # Les 2 ont confirmé. RÈGLEMENT EXACTLY-ONCE via un claim sur la ligne social_zones (TOUJOURS
        # présente, contrairement à trade_log) : UPDATE status='ended' WHERE status='active' → un seul
        # gagne, crédite, ferme. (Le crédit lui-même est DÉ-DUPLIQUÉ par paire → anti-farm alt.)
        settled = False
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "UPDATE social_zones SET status='ended' WHERE id=? AND status='active'", (zone_id,))
                settled = getattr(cur, "rowcount", 0) == 1
                await db.commit()
        except Exception:
            settled = False
        if not settled:
            return await _safe_followup(i, content="✅ Échange déjà confirmé — merci !")
        await _log_trade_outcome(zone_id, "success")
        # Crédit +1 confiance à chacun, SAUF si cette paire a déjà été créditée récemment (anti-alt).
        credited = await _credit_pair_if_fresh(gid, parts)
        if ch is not None:
            try:
                tail = ("+1 **confiance** 🛡️ pour chacun. Merci d'être des traders réglos !"
                        if credited else
                        "_(confiance déjà créditée récemment pour cette paire — anti-abus.)_")
                await ch.send(f"🎉 **Échange confirmé par les deux !** {tail} Le salon va se fermer.",
                              allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                pass
        # Suppression du salon (le status est déjà 'ended' → close_zone programme juste le delete).
        await close_zone(zone_id, linger=True)
        await _safe_followup(i, content="✅ Échange confirmé — merci !")
    except Exception as ex:
        print(f"[social_zones trade_done_click] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


async def _credit_pair_if_fresh(gid: int, parts) -> bool:
    """+1 confiance à chaque participant SAUF si cette PAIRE a déjà été créditée dans la fenêtre
    (_TRADE_PAIR_WINDOW_SEC) → un main+alt ne peut pas farmer en boucle. Retourne True si crédité."""
    ids = sorted({int(u) for u in parts})
    if len(ids) < 2:
        return False
    a, b = ids[0], ids[1]
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM trade_pair_credit WHERE guild_id=? AND a=? AND b=? "
                "AND datetime(last_at) > datetime('now', ?)",
                (gid, a, b, f'-{_TRADE_PAIR_WINDOW_SEC} seconds')) as cur:
                if await cur.fetchone():
                    return False   # paire créditée trop récemment → pas de nouveau crédit
            await db.execute(
                "INSERT INTO trade_pair_credit(guild_id, a, b, last_at) "
                "VALUES(?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, a, b) DO UPDATE SET last_at=CURRENT_TIMESTAMP",
                (gid, a, b))
            await db.commit()
    except Exception:
        return False
    for uid in (a, b):
        await _bump_rep(gid, uid, "successful", 1)
    return True


async def trade_scam_click(i: discord.Interaction, zone_id: int):
    z, ch, member = await _trade_guard(i, zone_id)
    if z is None:
        return
    try:
        gid = int(z["guild_id"])
        # 1 signalement / rapporteur / échange.
        try:
            async with _get_db() as db:
                cur = await db.execute(
                    "INSERT OR IGNORE INTO trade_scam_report(zone_id, reporter_id) VALUES(?,?)",
                    (zone_id, i.user.id))
                first = getattr(cur, "rowcount", 0) == 1
                await db.commit()
        except Exception:
            first = True
        if not first:
            return await _safe_followup(i, content="✅ Tu as déjà signalé cet échange. Le staff est prévenu.")
        # Incrémente `reported` pour l'AUTRE participant (jamais soi-même).
        others = [uid for uid in await _trade_participants(zone_id) if uid != i.user.id]
        flagged = []
        for uid in others:
            newv = await _bump_rep(gid, uid, "reported", 1)
            if newv >= _TRADE_SCAM_THRESHOLD:
                flagged.append(uid)
        await _log_trade_outcome(zone_id, "reported")
        # Rôle « ⚠️ Prudence » sur récidive (marqueur visible).
        if flagged and i.guild is not None:
            role = await _ensure_prudence_role(i.guild)
            if role is not None:
                for uid in flagged:
                    m = i.guild.get_member(uid)
                    if m is not None and role not in m.roles:
                        try:
                            await m.add_roles(role, reason="Trader signalé plusieurs fois (anti-arnaque)")
                        except Exception:
                            pass
        # Alerte STAFF DANS le salon (le staff y a accès via l'overwrite anti-triche).
        if ch is not None:
            st = _staff_role(i.guild)
            names = " ".join(f"<@{uid}>" for uid in await _trade_participants(zone_id))
            topic = (z.get("topic") or "").strip()
            head = st.mention if st is not None else "**@staff**"
            try:
                await ch.send(
                    f"🚨 {head} — {i.user.mention} **signale une arnaque** dans cet échange.\n"
                    f"Participants : {names}" + (f"\n📦 Échange annoncé : _{topic[:200]}_" if topic else "")
                    + "\n_Merci de vérifier l'historique ci-dessus._",
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, users=False,
                        roles=[st] if st is not None else False))
            except Exception:
                pass
        await _safe_followup(
            i, content="🚨 Signalement envoyé au **staff**. Reste prudent : ne donne jamais ton "
                       "objet en premier « sur confiance ».")
    except Exception as ex:
        print(f"[social_zones trade_scam_click] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


async def trade_mediator_click(i: discord.Interaction, zone_id: int):
    z, ch, member = await _trade_guard(i, zone_id)
    if z is None:
        return
    try:
        if ch is None:
            return await _safe_followup(i, content="❌ Salon introuvable.")
        role = _mediator_role(i.guild)
        if role is None:
            return await _safe_followup(
                i, content="ℹ️ Aucun rôle médiateur configuré. Préviens le staff directement.")
        try:
            await ch.send(
                f"⚖️ {role.mention} — {i.user.mention} demande un **médiateur** pour sécuriser cet "
                "échange. Merci de superviser la transaction. 🛡️",
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=[role]))
        except Exception:
            pass
        await _safe_followup(i, content="⚖️ Un médiateur a été appelé — attends sa supervision.")
    except Exception as ex:
        print(f"[social_zones trade_mediator_click] {ex}")
        await _safe_followup(i, content="❌ Erreur, réessaie.")


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
        if not z:
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
        guild = i.guild
        member = i.user if isinstance(i.user, discord.Member) else guild.get_member(i.user.id)
        if member is None:
            return await _safe_followup(i, content="❌ Membre introuvable.")
        # ── GROUPE EN ATTENTE (lazy) : le 1er « Rejoindre » d'un AUTRE joueur CRÉE le salon ──
        if z["status"] in ("pending", "materializing") and z["kind"] == "group":
            if member.id == int(z["creator_id"]):
                return await _safe_followup(
                    i, content="⏳ C'est ton invitation — le salon se créera quand **un autre "
                               "joueur** rejoint. 🙂")
            if await _is_zone_banned(zone_id, member.id):
                return await _safe_followup(
                    i, content="🚫 Un gestionnaire t'a retiré de cette zone.")
            ch2, err = await _materialize_zone(zone_id, member)
            if ch2 is None:
                if err == "race":
                    return await _safe_followup(
                        i, content="⏳ Le salon se crée à l'instant… réessaie dans 2 s.")
                return await _safe_followup(i, content="⌛ Cette invitation n'est plus disponible.")
            try:
                full = (await _member_count(zone_id)) >= _MAX_MEMBERS.get("group", 6)
                await _edit_group_nudge_live(i, zone_id, ch2, full)
            except Exception:
                pass
            return await _safe_followup(i, content=f"✅ Groupe créé — tu as rejoint : {ch2.mention}")
        if z["status"] != "active" or not z["channel_id"]:
            return await _safe_followup(i, content="⌛ Cette zone n'est plus disponible.")
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


class ZoneTradeOkButton(discord.ui.DynamicItem[discord.ui.Button],
                        template=r"szone_trade_ok:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="✅ Accepter l'échange", style=discord.ButtonStyle.success,
            custom_id=f"szone_trade_ok:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await trade_consent_click(i, self.zid, accept=True)


class ZoneTradeNoButton(discord.ui.DynamicItem[discord.ui.Button],
                        template=r"szone_trade_no:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="❌ Refuser", style=discord.ButtonStyle.secondary,
            custom_id=f"szone_trade_no:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await trade_consent_click(i, self.zid, accept=False)


class ZoneTradeDoneButton(discord.ui.DynamicItem[discord.ui.Button],
                          template=r"szone_trade_done:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="✅ Échange réussi", style=discord.ButtonStyle.success,
            custom_id=f"szone_trade_done:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await trade_done_click(i, self.zid)


class ZoneTradeScamButton(discord.ui.DynamicItem[discord.ui.Button],
                          template=r"szone_trade_scam:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="🚨 Signaler une arnaque", style=discord.ButtonStyle.danger,
            custom_id=f"szone_trade_scam:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await trade_scam_click(i, self.zid)


class ZoneTradeMediatorButton(discord.ui.DynamicItem[discord.ui.Button],
                              template=r"szone_trade_med:(?P<zid>\d+)"):
    def __init__(self, zid: int):
        super().__init__(discord.ui.Button(
            label="⚖️ Médiateur", style=discord.ButtonStyle.secondary,
            custom_id=f"szone_trade_med:{int(zid)}"))
        self.zid = int(zid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["zid"]))

    async def callback(self, i: discord.Interaction):
        await trade_mediator_click(i, self.zid)


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(
            ZoneCreateButton, ZoneJoinButton, ZoneCloseButton,
            ZoneAddButton, ZoneVoiceButton, ZoneExpelButton,
            ZoneTradeOkButton, ZoneTradeNoButton,
            ZoneTradeDoneButton, ZoneTradeScamButton, ZoneTradeMediatorButton)
    except Exception as ex:
        print(f"[social_zones register] {ex}")
