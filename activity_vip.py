"""
activity_vip.py — VIP CONTINU par SEUIL, avec décroissance + rappels (owner 2026-07-02).

POURQUOI (demande owner) : « Remercie À TOUT PRIX toutes les personnes actives, peu importe
qui. Dès qu'ils dépassent un seuil d'activité → rôle VIP (VIP+ pour les hyper-actifs). Ils
doivent être TOUS récompensés (merci + boost). LE PLUS IMPORTANT : rappelle-leur que l'activité
doit être régulière (chaque jour / chaque semaine) — sinon ils perdent le rôle ET les accès. »

DIFFÉRENCE avec activity_rewards.py (ancien) : celui-ci était une COMPÉTITION hebdo (seuls les
5 plus actifs gagnaient). Ici c'est un STATUT CONTINU par SEUIL ABSOLU : TOUT LE MONDE qui reste
actif l'obtient, sans plafond, sans classement — et le PERD s'il décroche (après un avertissement).
Réconciliation (owner a choisi « Option A ») : ce module est le SEUL propriétaire des rôles
🌟 VIP / 💎 VIP+ ; l'ancien hebdo devient une simple vitrine « Top actifs » (aucun rôle) dès que
`vip_enabled` est activé.

SOURCE D'ACTIVITÉ (lecture seule) : table `activity_score(guild_id, user_id, day 'YYYY-MM-DD' UTC,
points)` d'activity_system.py — 1 message = 1 pt, 1 min vocal = 1 pt, déjà ce que /profile affiche.
On calcule sur une fenêtre glissante : (a) le SCORE (SUM points) et (b) la RÉGULARITÉ (nb de jours
DISTINCTS actifs) — c'est la régularité qui encode « actif tous les jours / toutes les semaines ».

GARANTIES :
- FAIL-CLOSED sur les récompenses : à la moindre erreur DB → on n'accorde RIEN et on ne retire RIEN
  ce tour-ci (jamais « tout le monde devient VIP » ni « tout le monde perd VIP » sur un bug).
- Décroissance DOUCE : chute sous le seuil → AVERTISSEMENT dans le salon (jamais en MP) + délai de
  grâce → retrait seulement si toujours en dessous ; retour immédiat du rôle dès qu'il remonte.
- Grâce de démarrage : tant que la fenêtre n'a pas assez d'historique, on n'AVERTIT ni ne RETIRE
  (on accorde seulement) → pas de fausse alerte de masse juste après l'activation.
- Un SEUL écrivain des rôles (ce module). Anti-429 : 0,5 s entre deux éditions de rôle réelles,
  et on n'édite QUE si le rôle change vraiment (jamais de re-add inutile). Boucle supervisée.
- « Perdre les accès » = pur effet Discord : l'owner attache la visibilité des salons aux rôles
  VIP/VIP+ ; retirer le rôle retire l'accès automatiquement (zéro gestion de permissions côté bot).

API : setup(bot, get_db, db_get, v2) · init_db() · vip_eval_task (loop 30 min, supervisée) ·
evaluate_now(guild) (éval immédiate, ex. quand l'owner active) · holders_count(guild) · settings(gid).

Config (guild_config, réglable sans redéploiement, défauts ci-dessous) :
  vip_enabled(false) · vip_warn_enabled(true) · vip_window_days(7) ·
  vip_score_min(120) · vip_active_days_min(3) · vip_plus_score_min(600) ·
  vip_plus_active_days_min(5) · vip_grace_days(3) · vip_announce_channel_id(0)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks

# owner 2026-07-12 : privation VIP des fauteurs de trouble. Import SOUPLE — si le module manque,
# _vip_exclusion=None et le VIP fonctionne exactement comme avant (aucune privation). Fail-open.
try:
    import vip_exclusion as _vip_exclusion
except Exception:
    _vip_exclusion = None

# ─── Dépendances injectées ───────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None          # async (guild_id) -> dict de config brute
_v2 = None

# ─── Rôles (PARTAGÉS avec activity_rewards — mêmes noms/couleurs → mêmes rôles) ──
VIP_ROLE_NAME = "🌟 VIP"
VIP_PLUS_ROLE_NAME = "💎 VIP+"
VIP_COLOR = 0x3498DB
VIP_PLUS_COLOR = 0x9B59B6

# ─── Défauts de configuration (tous surchargeables via guild_config) ─────────
_DEFAULTS = {
    "vip_enabled": False,
    "vip_warn_enabled": True,
    "vip_window_days": 7,
    "vip_score_min": 120,
    "vip_active_days_min": 3,
    "vip_plus_score_min": 600,
    "vip_plus_active_days_min": 5,
    "vip_grace_days": 3,
}
# Bornes de sécurité (anti-config absurde saisie au modal).
_CLAMP = {
    "vip_window_days": (2, 30),
    "vip_score_min": (1, 100000),
    "vip_active_days_min": (1, 30),
    "vip_plus_score_min": (1, 1000000),
    "vip_plus_active_days_min": (1, 30),
    "vip_grace_days": (1, 30),
}

_RANK = {"none": 0, "vip": 1, "vip_plus": 2}
_evaluating: set = set()         # guildes en cours d'éval (anti-concurrence loop × evaluate_now)
_ROLE_EDIT_SLEEP = 0.5           # anti-429 entre 2 éditions de rôle réelles
_ANNOUNCE_GRANT_CAP = 20         # membres nommés max dans l'annonce de grant
_WARN_INDIVIDUAL_CAP = 15        # au-delà, on résume au lieu de pinguer 1 par 1


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers=None):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers or {}


# ═══════════════════════════════════════════════════════════════════════════════
#  DB
# ═══════════════════════════════════════════════════════════════════════════════
async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            # Table de rôles PARTAGÉE avec activity_rewards (CREATE IF NOT EXISTS idempotent).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS activity_vip_roles (
                    guild_id INTEGER PRIMARY KEY,
                    vip_role_id INTEGER DEFAULT 0,
                    vip_plus_role_id INTEGER DEFAULT 0
                )
            """)
            # Machine à états du VIP continu (1 ligne / membre).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS vip_status (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'none',
                    status TEXT NOT NULL DEFAULT 'active',
                    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_qualified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    warned_at TIMESTAMP,
                    last_score INTEGER DEFAULT 0,
                    last_active_days INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vip_status_guild "
                "ON vip_status(guild_id, status)")
            # Journal d'audit (transparence + debug des changements).
            await db.execute("""
                CREATE TABLE IF NOT EXISTS vip_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    tier TEXT,
                    score INTEGER,
                    active_days INTEGER,
                    at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vip_audit_lookup "
                "ON vip_audit(guild_id, user_id, at)")
            await db.commit()
    except Exception as ex:
        print(f"[activity_vip init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════════════════════
async def settings(guild_id: int) -> dict:
    """Config effective (défauts + surcharges guild_config, bornée). FAIL-SAFE défauts."""
    s = dict(_DEFAULTS)
    if _db_get is None:
        return s
    try:
        c = await _db_get(guild_id) or {}
        for k, dv in _DEFAULTS.items():
            v = c.get(k, dv)
            if isinstance(dv, bool):
                s[k] = bool(v)
            else:
                try:
                    v = int(v)
                except Exception:
                    v = dv
                lo, hi = _CLAMP.get(k, (None, None))
                if lo is not None:
                    v = max(lo, min(hi, v))
                s[k] = v
        # Cohérence : VIP+ doit être ≥ VIP (sinon classification incohérente).
        if s["vip_plus_score_min"] < s["vip_score_min"]:
            s["vip_plus_score_min"] = s["vip_score_min"]
        if s["vip_plus_active_days_min"] < s["vip_active_days_min"]:
            s["vip_plus_active_days_min"] = s["vip_active_days_min"]
    except Exception as ex:
        print(f"[activity_vip settings] {ex}")
    return s


# ═══════════════════════════════════════════════════════════════════════════════
#  Fenêtre d'activité (lecture seule de activity_score, en UTC comme la table)
# ═══════════════════════════════════════════════════════════════════════════════
def _window_start_str(days: int) -> str:
    d = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)) - 1)
    return d.strftime("%Y-%m-%d")


async def _aggregate_activity(guild_id: int, window_days: int):
    """{user_id: (score, active_days)} sur la fenêtre. Retourne None SI ERREUR (→ fail-closed :
    l'appelant saute la guilde ce tour). Un dict vide = pas d'activité (valide, pas une erreur)."""
    if _get_db is None:
        return None
    start = _window_start_str(window_days)
    try:
        out = {}
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, COALESCE(SUM(points),0) AS score, "
                "COUNT(DISTINCT CASE WHEN points>0 THEN day END) AS active_days "
                "FROM activity_score WHERE guild_id=? AND day >= ? GROUP BY user_id",
                (int(guild_id), start),
            ) as cur:
                for r in await cur.fetchall():
                    out[int(r[0])] = (int(r[1] or 0), int(r[2] or 0))
        return out
    except Exception as ex:
        print(f"[activity_vip _aggregate_activity] {ex}")
        return None


async def _history_window_full(guild_id: int, window_days: int) -> bool:
    """True si le serveur a ≥ window_days jours d'historique d'activité. Sert de GRÂCE DE
    DÉMARRAGE : False → on n'avertit ni ne retire (grant seulement). FAIL-SAFE **False** : au
    moindre doute (erreur DB), on SUPPRIME les retraits ce tour-ci (jamais retirer sur un bug ;
    ça ne fait que différer un éventuel retrait de 30 min). Cohérent avec le fail-closed global."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT MIN(day) FROM activity_score WHERE guild_id=?", (int(guild_id),)) as cur:
                row = await cur.fetchone()
        if not row or not row[0]:
            return False
        first = datetime.strptime(row[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - first).days >= (max(1, int(window_days)) - 1)
    except Exception:
        return False


def _classify(score: int, days: int, s: dict) -> str:
    """Palier VISÉ selon score ET régularité (les DEUX doivent tenir → un burst d'un seul jour
    ne suffit pas ; il faut être actif plusieurs jours = régularité)."""
    if score >= s["vip_plus_score_min"] and days >= s["vip_plus_active_days_min"]:
        return "vip_plus"
    if score >= s["vip_score_min"] and days >= s["vip_active_days_min"]:
        return "vip"
    return "none"


# ═══════════════════════════════════════════════════════════════════════════════
#  Rôles (mêmes que activity_rewards : on résout par id persisté, sinon par nom, sinon crée)
# ═══════════════════════════════════════════════════════════════════════════════
async def _get_role_ids(guild_id: int):
    if _get_db is None:
        return (0, 0)
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT vip_role_id, vip_plus_role_id FROM activity_vip_roles WHERE guild_id=?",
                (guild_id,)) as cur:
                row = await cur.fetchone()
        if row:
            return (int(row[0] or 0), int(row[1] or 0))
    except Exception:
        pass
    return (0, 0)


async def _save_role_ids(guild_id: int, vip_id: int, vip_plus_id: int):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO activity_vip_roles (guild_id, vip_role_id, vip_plus_role_id) "
                "VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET "
                "vip_role_id=excluded.vip_role_id, vip_plus_role_id=excluded.vip_plus_role_id",
                (guild_id, vip_id, vip_plus_id))
            await db.commit()
    except Exception:
        pass


async def _ensure_roles(guild: discord.Guild):
    """(vip_role, vip_plus_role) — auto-crée si absents ET si manage_roles. Fail-soft None."""
    vip_id, vip_plus_id = await _get_role_ids(guild.id)
    vip_role = guild.get_role(vip_id) if vip_id else None
    vip_plus_role = guild.get_role(vip_plus_id) if vip_plus_id else None
    try:
        can_manage = bool(guild.me and guild.me.guild_permissions.manage_roles)
    except Exception:
        can_manage = False

    if vip_role is None:
        vip_role = discord.utils.get(guild.roles, name=VIP_ROLE_NAME)
        if vip_role is None and can_manage:
            try:
                vip_role = await guild.create_role(
                    name=VIP_ROLE_NAME, colour=discord.Colour(VIP_COLOR),
                    hoist=True, mentionable=False, reason="VIP continu (activité régulière)")
            except Exception as ex:
                print(f"[activity_vip create VIP] {ex}")
    if vip_plus_role is None:
        vip_plus_role = discord.utils.get(guild.roles, name=VIP_PLUS_ROLE_NAME)
        if vip_plus_role is None and can_manage:
            try:
                vip_plus_role = await guild.create_role(
                    name=VIP_PLUS_ROLE_NAME, colour=discord.Colour(VIP_PLUS_COLOR),
                    hoist=True, mentionable=False, reason="VIP+ continu (activité régulière)")
            except Exception as ex:
                print(f"[activity_vip create VIP+] {ex}")

    await _save_role_ids(guild.id, vip_role.id if vip_role else 0,
                         vip_plus_role.id if vip_plus_role else 0)
    return vip_role, vip_plus_role


def _role_for(tier: str, vip_role, vip_plus_role):
    return vip_plus_role if tier == "vip_plus" else (vip_role if tier == "vip" else None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Salon d'annonce (même priorité que activity_rewards) + audit
# ═══════════════════════════════════════════════════════════════════════════════
async def _announce_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    if _db_get is None:
        return None
    try:
        cfg = await _db_get(guild.id) or {}
        for key in ("vip_announce_channel_id", "hub_channel", "welcome_channel", "general_channel"):
            ch_id = int(cfg.get(key, 0) or 0)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if ch is not None:
                    return ch
    except Exception:
        pass
    avoid = ("ticket", "log", "audit", "annonce", "announce", "règl", "regl", "rule", "staff",
             "admin", "mod", "welcome", "bienvenue", "info", "chronique", "combat", "arène",
             "arene", "vente", "shop", "boutique")
    try:
        me = guild.me
        for ch in guild.text_channels:
            n = (ch.name or "").lower()
            if any(a in n for a in avoid):
                continue
            if me and ch.permissions_for(me).send_messages:
                return ch
    except Exception:
        pass
    return None


async def _audit(guild_id: int, user_id: int, event: str, tier: str, score: int, days: int):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO vip_audit (guild_id, user_id, event, tier, score, active_days) "
                "VALUES (?,?,?,?,?,?)", (guild_id, user_id, event, tier, int(score), int(days)))
            await db.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  État (vip_status)
# ═══════════════════════════════════════════════════════════════════════════════
async def _load_status(guild_id: int) -> dict:
    """{user_id: {tier,status,warned_at(datetime|None),granted_at}}. Vide sur erreur."""
    out = {}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, tier, status, warned_at, granted_at FROM vip_status "
                "WHERE guild_id=?", (guild_id,)) as cur:
                for r in await cur.fetchall():
                    out[int(r[0])] = {
                        "tier": r[1] or "none", "status": r[2] or "active",
                        "warned_at": _parse_ts(r[3]), "granted_at": r[4]}
    except Exception as ex:
        print(f"[activity_vip _load_status] {ex}")
    return out


def _parse_ts(v):
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def _upsert_status(guild_id, user_id, *, tier, status, warned_at, score, days,
                         set_granted=False):
    if _get_db is None:
        return
    wt = warned_at.isoformat() if isinstance(warned_at, datetime) else None
    try:
        async with _get_db() as db:
            if set_granted:
                await db.execute(
                    "INSERT INTO vip_status "
                    "(guild_id,user_id,tier,status,granted_at,last_qualified_at,warned_at,"
                    " last_score,last_active_days) "
                    "VALUES (?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,?,?,?) "
                    "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
                    "tier=excluded.tier, status=excluded.status, "
                    "granted_at=CURRENT_TIMESTAMP, last_qualified_at=CURRENT_TIMESTAMP, "
                    "warned_at=excluded.warned_at, last_score=excluded.last_score, "
                    "last_active_days=excluded.last_active_days",
                    (guild_id, user_id, tier, status, wt, int(score), int(days)))
            else:
                await db.execute(
                    "INSERT INTO vip_status "
                    "(guild_id,user_id,tier,status,last_qualified_at,warned_at,"
                    " last_score,last_active_days) "
                    "VALUES (?,?,?,?,CURRENT_TIMESTAMP,?,?,?) "
                    "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
                    "tier=excluded.tier, status=excluded.status, "
                    "last_qualified_at=CURRENT_TIMESTAMP, warned_at=excluded.warned_at, "
                    "last_score=excluded.last_score, last_active_days=excluded.last_active_days",
                    (guild_id, user_id, tier, status, wt, int(score), int(days)))
            await db.commit()
    except Exception as ex:
        print(f"[activity_vip _upsert_status] {ex}")


async def _delete_status(guild_id, user_id):
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("DELETE FROM vip_status WHERE guild_id=? AND user_id=?",
                             (guild_id, user_id))
            await db.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Évaluation d'une guilde (cœur : grant / keep / warn / grâce / retrait / retour)
# ═══════════════════════════════════════════════════════════════════════════════
async def evaluate_guild(guild: discord.Guild) -> dict:
    res = {"granted": [], "promoted": [], "recovered": [], "warned": [], "removed": [],
           "demoted": [], "skipped": False}
    if guild is None or _get_db is None:
        res["skipped"] = True
        return res
    s = await settings(guild.id)
    if not s["vip_enabled"]:
        res["skipped"] = True
        return res
    # Anti-concurrence : la boucle 30 min et un evaluate_now() (toggle) ne doivent pas évaluer la
    # MÊME guilde en même temps (sinon double-grant / double-annonce). Le 2e appel saute.
    if guild.id in _evaluating:
        res["skipped"] = True
        return res
    _evaluating.add(guild.id)
    try:
        return await _evaluate_guild_locked(guild, s, res)
    finally:
        _evaluating.discard(guild.id)


async def _evaluate_guild_locked(guild: discord.Guild, s: dict, res: dict) -> dict:
    vip_role, vip_plus_role = await _ensure_roles(guild)
    if vip_role is None and vip_plus_role is None:
        # Pas de rôles (pas de manage_roles / au-dessus du bot) → rien à faire, fail-soft.
        res["skipped"] = True
        return res

    agg = await _aggregate_activity(guild.id, s["vip_window_days"])
    if agg is None:
        # FAIL-CLOSED : erreur de lecture → on n'accorde ni ne retire RIEN ce tour-ci.
        res["skipped"] = True
        return res

    window_full = await _history_window_full(guild.id, s["vip_window_days"])
    status_rows = await _load_status(guild.id)

    # Univers à réconcilier : membres actifs (agg) ∪ lignes d'état ∪ porteurs actuels du rôle.
    holders = set()
    try:
        for m in guild.members:
            if getattr(m, "bot", False):
                continue
            r = getattr(m, "roles", []) or []
            if (vip_role and vip_role in r) or (vip_plus_role and vip_plus_role in r):
                holders.add(int(m.id))
    except Exception:
        holders = set()
    universe = set(agg.keys()) | set(status_rows.keys()) | holders

    now = datetime.now(timezone.utc)
    grace = timedelta(days=s["vip_grace_days"])

    # ── PRIVATION VIP (owner 2026-07-12) ──────────────────────────────────────────────────
    # Un membre sanctionné (mute/kick/ban auto, ou warn d'un staff) est privé des récompenses
    # gagnées par son ACTIVITÉ : 1 mois, puis 2, 4, 8, jusqu'à 1 an s'il recommence. Objectif
    # owner : spammer pour farmer le VIP ne doit plus rien rapporter.
    # On charge la liste une SEULE fois par passage (pas par membre) puis on force la cible à
    # « none » → le reste de la boucle retire le rôle par le chemin NORMAL (aucune duplication).
    # FAIL-OPEN : erreur de lecture → ensemble vide, on ne prive personne à tort (règle n°1).
    _excluded = set()
    try:
        if _vip_exclusion is not None:
            _excluded = await _vip_exclusion.excluded_ids(guild.id)
    except Exception as ex:
        print(f"[activity_vip exclusions] {ex}")
        _excluded = set()

    async def _add_role(member, role) -> bool:
        """True si le membre POSSÈDE le rôle au retour (ajouté OU déjà présent). False sur échec."""
        if role is None:
            return False
        try:
            if role in member.roles:
                return True
            await member.add_roles(role, reason="VIP continu (activité régulière)")
            await asyncio.sleep(_ROLE_EDIT_SLEEP)
            return True
        except Exception as ex:
            print(f"[activity_vip add_role] {ex}")
            return False

    async def _rm_role(member, role) -> bool:
        """True si le membre N'A PLUS le rôle au retour (retiré OU déjà absent). False sur échec."""
        if role is None:
            return True
        try:
            if role not in member.roles:
                return True
            await member.remove_roles(role, reason="VIP retiré (activité en baisse)")
            await asyncio.sleep(_ROLE_EDIT_SLEEP)
            return True
        except Exception as ex:
            print(f"[activity_vip rm_role] {ex}")
            return False

    for uid in universe:
        try:
            member = guild.get_member(uid)
            score, days = agg.get(uid, (0, 0))
            target = _classify(score, days, s)
            # Privé de récompenses d'activité → AUCUN rôle, quelle que soit son activité.
            if uid in _excluded:
                target = "none"
            st = status_rows.get(uid)

            if member is None:
                # Membre parti/hors cache : on ne peut pas éditer ses rôles. On nettoie l'état si
                # plus rien à suivre, sinon on laisse (il pourrait revenir).
                if st and target == "none":
                    await _delete_status(guild.id, uid)
                continue

            # Palier RÉELLEMENT porté (les rôles Discord font foi).
            r = member.roles
            if vip_plus_role and vip_plus_role in r:
                held = "vip_plus"
            elif vip_role and vip_role in r:
                held = "vip"
            else:
                held = "none"
            held_rank, target_rank = _RANK[held], _RANK[target]
            cur_status = (st or {}).get("status", "active")
            warned_at = (st or {}).get("warned_at")

            # ── MONTÉE / NOUVEAU (target strictement au-dessus du rôle porté) ──
            if target_rank > held_rank:
                new_role = _role_for(target, vip_role, vip_plus_role)
                if new_role is None:
                    continue  # ce palier n'a pas de rôle dispo → skip
                if not await _add_role(member, new_role):
                    continue  # l'ajout a échoué → on n'enregistre ni annonce (pas de grant fantôme)
                # Promotion VIP→VIP+ : retire l'ancien rôle VIP (évite double-hoist).
                if target == "vip_plus" and held == "vip" and vip_role is not None:
                    await _rm_role(member, vip_role)
                is_new = (held == "none")
                await _upsert_status(guild.id, uid, tier=target, status="active",
                                     warned_at=None, score=score, days=days, set_granted=is_new)
                await _audit(guild.id, uid, "grant" if is_new else "promote", target, score, days)
                (res["granted"] if is_new else res["promoted"]).append((uid, target, score, days))
                continue

            # ── MAINTIEN (target == rôle porté, et > none) ──
            if target_rank == held_rank and held_rank > 0:
                recovered = (cur_status == "warned")
                await _upsert_status(guild.id, uid, tier=held, status="active",
                                     warned_at=None, score=score, days=days)
                if recovered:
                    await _audit(guild.id, uid, "recover", held, score, days)
                    res["recovered"].append((uid, held, score, days))
                continue

            # ── SOUS LE SEUIL du rôle porté (target < held) → décroissance douce ──
            if target_rank < held_rank and held_rank > 0:
                # Grâce de démarrage : fenêtre trop courte → on n'avertit ni ne retire.
                if not window_full:
                    continue
                if s["vip_warn_enabled"] and cur_status != "warned":
                    # 1er passage sous le seuil → AVERTISSEMENT (on GARDE le rôle). Le message dépend
                    # de ce qui l'attend : perte TOTALE (target none) vs simple rétrogradation VIP+→VIP.
                    await _upsert_status(guild.id, uid, tier=held, status="warned",
                                         warned_at=now, score=score, days=days)
                    await _audit(guild.id, uid, "warn", held, score, days)
                    res["warned"].append((uid, held, target, score, days,
                                          _needed_text(held, score, days, s)))
                    continue
                # Déjà averti (ou avertissements désactivés) : la grâce a-t-elle expiré ?
                grace_over = (not s["vip_warn_enabled"]) or (
                    warned_at is not None and (now - warned_at) >= grace)
                if not grace_over:
                    continue  # encore dans le délai de grâce → on garde le rôle, silence
                # Grâce expirée et toujours en dessous → on descend au palier visé.
                if target == "none":
                    await _rm_role(member, vip_plus_role)
                    await _rm_role(member, vip_role)
                    await _upsert_status(guild.id, uid, tier="none", status="removed",
                                         warned_at=None, score=score, days=days)
                    await _audit(guild.id, uid, "remove", held, score, days)
                    res["removed"].append((uid, held, score, days))
                else:
                    # Rétrograde VIP+ → VIP (garde une base VIP, plus doux). SÉCURITÉ (miroir de la
                    # montée) : on ne retire l'ancien rôle QUE si le nouveau a bien été appliqué —
                    # sinon on garderait le membre SANS aucun rôle tout en le croyant VIP (fantôme).
                    new_role = _role_for(target, vip_role, vip_plus_role)
                    if new_role is None or not await _add_role(member, new_role):
                        continue  # rôle cible indisponible/échec → on GARDE VIP+, on réessaiera
                    if vip_plus_role is not None:
                        await _rm_role(member, vip_plus_role)
                    await _upsert_status(guild.id, uid, tier=target, status="active",
                                         warned_at=None, score=score, days=days)
                    await _audit(guild.id, uid, "demote", target, score, days)
                    res["demoted"].append((uid, target, score, days))
                continue

            # ── Ni porteur ni éligible : nettoie une ligne d'état résiduelle ──
            if held == "none" and target == "none" and st is not None:
                await _delete_status(guild.id, uid)
        except Exception as ex:
            print(f"[activity_vip evaluate member {uid}] {ex}")
            continue

    await _announce(guild, res)
    return res


def _needed_text(tier: str, score: int, days: int, s: dict) -> str:
    """Ce qu'il manque pour GARDER son palier (affiché dans l'avertissement)."""
    if tier == "vip_plus":
        need_s, need_d = s["vip_plus_score_min"], s["vip_plus_active_days_min"]
    else:
        need_s, need_d = s["vip_score_min"], s["vip_active_days_min"]
    parts = []
    if score < need_s:
        parts.append(f"**{need_s - score} pts** (tu es à {score}/{need_s})")
    if days < need_d:
        parts.append(f"**{need_d - days} jour(s) actif(s)** (tu es à {days}/{need_d} cette semaine)")
    return " et ".join(parts) if parts else "un petit peu d'activité"


# ═══════════════════════════════════════════════════════════════════════════════
#  Annonces (dans le salon VIP, JAMAIS en MP). Merci + RAPPEL de régularité.
# ═══════════════════════════════════════════════════════════════════════════════
def _label(tier: str) -> str:
    return VIP_PLUS_ROLE_NAME if tier == "vip_plus" else VIP_ROLE_NAME


async def _announce(guild: discord.Guild, res: dict):
    try:
        ch = await _announce_channel(guild)
        if ch is None:
            return
        me = guild.me

        def _nm(uid):
            m = guild.get_member(uid)
            return m.mention if m else f"<@{uid}>"

        # ── Nouveaux VIP / promotions / retours : 1 carte de remerciement (avec RAPPEL) ──
        joins = (res.get("granted") or []) + (res.get("promoted") or []) + (res.get("recovered") or [])
        if joins:
            vplus = [u for (u, t, *_ ) in joins if t == "vip_plus"]
            vbase = [u for (u, t, *_ ) in joins if t == "vip"]
            lines = ["🎉 **Merci d'animer le serveur — récompense d'activité !**", ""]
            if vplus:
                lines.append("💎 **VIP+** _(hyper-actifs)_ : " + _join_names(vplus, _nm))
            if vbase:
                lines.append("🌟 **VIP** _(membres actifs)_ : " + _join_names(vbase, _nm))
            lines.append("")
            lines.append("Vos rôles vous ouvrent des **salons spéciaux**. ⚠️ **Restez actifs "
                         "régulièrement** (au moins quelques jours par semaine) : sinon, après un "
                         "avertissement, le rôle **et les accès** sont retirés. À très vite ! 💪")
            # Pings réels plafonnés à 3 (ToS/RULES) ; les autres noms s'affichent sans notifier.
            ping_ids = (vplus + vbase)[:3]
            allowed = discord.AllowedMentions(
                users=[discord.Object(id=u) for u in ping_ids], roles=False, everyone=False)
            await _safe_send(ch, "\n".join(lines)[:1900], allowed)

        # ── Avertissements : 1 message PERSONNEL pinguant chaque membre (le rappel clé) ──
        warned = res.get("warned") or []
        if warned:
            if len(warned) <= _WARN_INDIVIDUAL_CAP:
                for (uid, held, target, score, days, need) in warned:
                    m = guild.get_member(uid)
                    if m is None:
                        continue
                    if target == "none":
                        risk = (f"tu risques de **perdre** ton rôle {_label(held)} "
                                "(et les accès aux salons)")
                    else:
                        # VIP+ qui redescend : il garde une base VIP → on ne dit PAS « perte totale ».
                        risk = (f"tu risques de **repasser {_label(target)}** "
                                f"(tu perdrais les salons réservés {_label(held)})")
                    txt = (f"⏳ {m.mention}, ton activité a **baissé** — {risk}. Il te manque {need} "
                           f"cette semaine. Reviens participer et tu **gardes tout automatiquement** ! 💪")
                    allowed = discord.AllowedMentions(users=[m], roles=False, everyone=False)
                    if not await _safe_send(ch, txt, allowed):
                        break
                    await asyncio.sleep(_ROLE_EDIT_SLEEP)
            else:
                # Rare (grosse vague) : on résume au lieu de pinguer des dizaines de membres.
                sample = ", ".join(_nm(u) for (u, *_r) in warned[:10])
                await _safe_send(
                    ch, f"⏳ **{len(warned)} membres** voient leur activité baisser et risquent de "
                        f"perdre leur rôle VIP — un petit effort pour le garder ! {sample}"
                        + (" …" if len(warned) > 10 else ""),
                    discord.AllowedMentions.none())

        # ── Retraits / rétrogradations : message doux (jamais culpabilisant) ──
        removed = res.get("removed") or []
        demoted = res.get("demoted") or []
        if removed or demoted:
            parts = []
            if removed:
                parts.append("👋 Rôle VIP mis en **pause** (inactivité) : "
                             + _join_names([u for (u, *_r) in removed], _nm)
                             + " — reviens quand tu veux, tu le retrouveras vite !")
            if demoted:
                parts.append("🔄 Passage 💎→🌟 : "
                             + _join_names([u for (u, *_r) in demoted], _nm)
                             + " — encore un effort pour remonter en VIP+ !")
            await _safe_send(ch, "\n".join(parts)[:1900], discord.AllowedMentions.none())
    except Exception as ex:
        print(f"[activity_vip _announce] {ex}")


def _join_names(ids, namer, cap=_ANNOUNCE_GRANT_CAP):
    names = [namer(u) for u in ids[:cap]]
    extra = len(ids) - len(names)
    txt = ", ".join(names) if names else "—"
    if extra > 0:
        txt += f" _+{extra} autre(s)_"
    return txt


async def _safe_send(ch, content, allowed) -> bool:
    try:
        me = ch.guild.me if ch.guild else None
        if me is not None and not ch.permissions_for(me).send_messages:
            return False
        await ch.send(content, allowed_mentions=allowed)
        return True
    except Exception as ex:
        print(f"[activity_vip send] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  API publique diverse
# ═══════════════════════════════════════════════════════════════════════════════
async def holders_count(guild: discord.Guild):
    """(nb_vip, nb_vip_plus) porteurs actuels des rôles — pour le panneau de config."""
    try:
        vip_id, vip_plus_id = await _get_role_ids(guild.id)
        vr = guild.get_role(vip_id) if vip_id else None
        vpr = guild.get_role(vip_plus_id) if vip_plus_id else None
        nv = len(vr.members) if vr else 0
        nvp = len(vpr.members) if vpr else 0
        return (nv, nvp)
    except Exception:
        return (0, 0)


async def evaluate_now(guild: discord.Guild):
    """Éval immédiate d'une guilde (ex. quand l'owner vient d'activer / de régler les seuils)."""
    try:
        return await evaluate_guild(guild)
    except Exception as ex:
        print(f"[activity_vip evaluate_now] {ex}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Boucle supervisée (30 min)
# ═══════════════════════════════════════════════════════════════════════════════
@tasks.loop(minutes=30)
async def vip_eval_task():
    if _bot is None or _get_db is None:
        return
    try:
        for guild in list(_bot.guilds):
            try:
                await evaluate_guild(guild)
                await asyncio.sleep(0.5)  # espace les guildes (anti-429)
            except Exception as ex:
                print(f"[vip_eval_task g={getattr(guild,'id',0)}] {ex}")
    except Exception as ex:
        print(f"[vip_eval_task] {ex}")


@vip_eval_task.before_loop
async def _vip_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


__all__ = [
    "VIP_ROLE_NAME", "VIP_PLUS_ROLE_NAME",
    "setup", "init_db", "settings", "evaluate_guild", "evaluate_now",
    "holders_count", "vip_eval_task",
]
