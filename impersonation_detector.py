"""
impersonation_detector.py — Détection d'impersonation staff (Phase 147).

🎯 OBJECTIF : alerter quand un utilisateur change son nick/avatar pour
ressembler à un staff existant. PAS de sanction automatique (RULES.md
+ user request) — juste warning au owner.

Scénarios détectés :
1. **Nick swap** : user change son nom vers `Adm1n`, `0wner`, `Mod_GoRipe`
2. **Variations Unicode** : `Аdmin` (А cyrillique), espaces zero-width
3. **Avatar swap** : user prend exact même avatar qu'un staff (hash match)
4. **Returning attacker** : user kické revient avec nouvel avatar/nick mais
   user_id connu dans la blacklist

Algo :
- Hook on_member_update (nick) + on_user_update (username, avatar)
- Maintient un index `staff_signatures` rafraîchi périodiquement
- Pour chaque change, calcule similarity avec chaque staff
- Si score > seuil → DM owner avec détails

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers)
- refresh_staff_index(guild) — appeler 1×/heure ou au boot
- on_member_update_hook(before, after)
- on_user_update_hook(before, after)

DB tables :
- staff_signatures (guild_id, user_id, display_name, avatar_hash, last_seen)
- impersonation_alerts (id PK, guild_id, suspect_user_id, target_staff_id,
                        match_type, score, created_at, status)

⚠️ RULES.md : aucun auto-rollback, aucune sanction. Juste alerte.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None

# Mots-clés "rôle staff" qui rendent un pseudo suspect
STAFF_KEYWORDS = (
    "admin", "owner", "mod", "modo", "moderator",
    "staff", "support", "official", "system", "bot",
    "founder", "creator", "boss", "chief", "director",
)

# Variations Unicode courantes (homoglyphes)
HOMOGLYPHS = {
    "a": ["а", "ɑ", "α", "@", "4"],
    "e": ["е", "ε", "3"],
    "i": ["і", "І", "l", "1", "|", "!"],
    "o": ["о", "О", "0", "ο"],
    "c": ["с", "С"],
    "p": ["р", "Р"],
    "h": ["һ"],
    "x": ["х"],
    "y": ["у", "У"],
    "k": ["κ", "к"],
    "b": ["в"],
    "n": ["п"],
    "u": ["υ"],
    "s": ["ѕ", "5", "$"],
    "t": ["т", "7"],
    "g": ["9"],
    "l": ["1", "|", "I"],
}

SIMILARITY_THRESHOLD = 0.7  # ratio Levenshtein normalisé


def setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict):
    global _bot, _get_db, _db_get, _v2
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS staff_signatures (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    display_name TEXT,
                    username TEXT,
                    avatar_hash TEXT,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS impersonation_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    suspect_user_id INTEGER NOT NULL,
                    target_staff_id INTEGER,
                    match_type TEXT,
                    suspect_value TEXT,
                    target_value TEXT,
                    score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending'
                )
            """)
            await db.commit()
    except Exception as ex:
        print(f"[impersonation_detector init_db] {ex}")


# ─── Helpers ────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Normalise un nom : lowercase + NFKD + collapse homoglyphs."""
    if not s:
        return ""
    # NFKD : décompose accents/variantes
    s = unicodedata.normalize("NFKD", s)
    # Vire les zero-width et caractères de contrôle
    s = "".join(c for c in s if unicodedata.category(c)[0] != "C")
    s = s.lower()
    # Vire les non-alphanum (sauf espaces)
    s = re.sub(r"[^a-z0-9_\-\s]", "", s)
    return s.strip()


def _collapse_homoglyphs(s: str) -> str:
    """Remplace les homoglyphes par le caractère 'canonique'."""
    if not s:
        return ""
    s = s.lower()
    for canonical, variants in HOMOGLYPHS.items():
        for v in variants:
            s = s.replace(v, canonical)
    return s


def _levenshtein(a: str, b: str) -> int:
    """Distance d'édition (implémentation O(n*m) simple)."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for i, cb in enumerate(b, 1):
        curr = [i] + [0] * len(a)
        for j, ca in enumerate(a, 1):
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            )
        prev = curr
    return prev[-1]


def _similarity(a: str, b: str) -> float:
    """Ratio de similarité (0..1) basé sur Levenshtein."""
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - (_levenshtein(a, b) / max_len)


def _is_staff_member(member: discord.Member) -> bool:
    """True si le membre a des permissions staff."""
    try:
        if member.id == member.guild.owner_id:
            return True
        perms = member.guild_permissions
        return (
            perms.administrator or perms.manage_guild or
            perms.manage_messages or perms.kick_members or
            perms.ban_members
        )
    except Exception:
        return False


# ─── Refresh staff index ────────────────────────────────────────────────────

async def refresh_staff_index(guild: discord.Guild):
    """Rafraîchit la table staff_signatures pour ce guild."""
    if _get_db is None or guild is None:
        return 0
    try:
        staff_members = [m for m in guild.members if _is_staff_member(m)]
        async with _get_db() as db:
            await db.execute(
                "DELETE FROM staff_signatures WHERE guild_id=?", (guild.id,)
            )
            for m in staff_members:
                avatar_hash = ""
                try:
                    if m.avatar:
                        avatar_hash = str(m.avatar.key)
                except Exception:
                    pass
                await db.execute(
                    "INSERT INTO staff_signatures "
                    "(guild_id, user_id, display_name, username, avatar_hash) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        guild.id, m.id, m.display_name, m.name, avatar_hash,
                    ),
                )
            await db.commit()
        return len(staff_members)
    except Exception as ex:
        print(f"[impersonation_detector refresh] {ex}")
        return 0


async def _load_staff_index(guild_id: int) -> list[dict]:
    out = []
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, display_name, username, avatar_hash "
                "FROM staff_signatures WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            out.append({
                "user_id": int(r[0]),
                "display_name": r[1] or "",
                "username": r[2] or "",
                "avatar_hash": r[3] or "",
            })
    except Exception:
        pass
    return out


# ─── Detection logic ────────────────────────────────────────────────────────

async def _check_name(member: discord.Member, new_name: str) -> Optional[dict]:
    """Vérifie si new_name impersonate un staff. Renvoie alert dict ou None.
    """
    if _is_staff_member(member):
        return None  # Un staff lui-même n'impersonate pas
    staff_idx = await _load_staff_index(member.guild.id)
    if not staff_idx:
        return None

    cand_norm = _normalize(new_name)
    cand_collapsed = _collapse_homoglyphs(cand_norm)

    # 1) Mots-clés staff dans le nom (faible)
    lower = (new_name or "").lower()
    keyword_match = None
    for kw in STAFF_KEYWORDS:
        if kw in lower:
            keyword_match = kw
            break

    # 2) Similarity check vs chaque staff
    best = None
    for staff in staff_idx:
        if staff["user_id"] == member.id:
            continue
        for field, val in (
            ("display_name", staff["display_name"]),
            ("username", staff["username"]),
        ):
            if not val:
                continue
            staff_norm = _normalize(val)
            staff_collapsed = _collapse_homoglyphs(staff_norm)
            sim = _similarity(cand_collapsed, staff_collapsed)
            if sim >= SIMILARITY_THRESHOLD and sim < 1.0:
                # Pas la même string, mais très proche
                if best is None or sim > best["score"]:
                    best = {
                        "match_type": "name_similarity",
                        "target_staff_id": staff["user_id"],
                        "target_value": val,
                        "suspect_value": new_name,
                        "score": sim,
                        "field": field,
                    }

    if best is not None:
        return best

    if keyword_match:
        return {
            "match_type": "staff_keyword",
            "target_staff_id": 0,
            "target_value": keyword_match,
            "suspect_value": new_name,
            "score": 0.6,
            "field": "keyword",
        }

    return None


async def _check_avatar(member: discord.Member, new_hash: str) -> Optional[dict]:
    """Vérifie si new_hash matche un staff existant."""
    if _is_staff_member(member) or not new_hash:
        return None
    staff_idx = await _load_staff_index(member.guild.id)
    for staff in staff_idx:
        if staff["user_id"] == member.id:
            continue
        if staff["avatar_hash"] and staff["avatar_hash"] == new_hash:
            return {
                "match_type": "avatar_exact",
                "target_staff_id": staff["user_id"],
                "target_value": new_hash,
                "suspect_value": new_hash,
                "score": 1.0,
                "field": "avatar",
            }
    return None


async def _log_and_alert(member: discord.Member, alert: dict):
    """Enregistre l'alerte + DM owner."""
    if _get_db is None or alert is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO impersonation_alerts "
                "(guild_id, suspect_user_id, target_staff_id, match_type, "
                "suspect_value, target_value, score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    member.guild.id, member.id,
                    alert.get("target_staff_id", 0),
                    alert["match_type"],
                    str(alert.get("suspect_value", ""))[:200],
                    str(alert.get("target_value", ""))[:200],
                    float(alert.get("score", 0.0)),
                ),
            )
            await db.commit()

        # DM owner
        guild = member.guild
        owner = guild.owner or await guild.fetch_member(guild.owner_id)
        if owner:
            target_id = alert.get("target_staff_id", 0)
            target_member = guild.get_member(target_id) if target_id else None
            target_str = (
                f"{target_member.mention} (`{target_member.name}`)"
                if target_member else
                f"keyword `{alert.get('target_value')}`"
            )
            msg = (
                f"🎭 **Tentative d'impersonation détectée — {guild.name}**\n\n"
                f"**Suspect :** {member.mention} (`{member.name}` · "
                f"ID `{member.id}`)\n"
                f"**Type :** `{alert['match_type']}`\n"
                f"**Champ :** `{alert.get('field', '?')}`\n"
                f"**Valeur suspecte :** `{alert.get('suspect_value', '')}`\n"
                f"**Imite :** {target_str}\n"
                f"**Score similarité :** `{alert.get('score', 0):.2f}`\n\n"
                f"_Aucune sanction auto. Va voir le profil ou ouvre le "
                f"salon staff sanctions pour décider._"
            )
            try:
                await owner.send(msg)
            except Exception:
                pass
    except Exception as ex:
        print(f"[impersonation_detector _log_and_alert] {ex}")


# ─── Hooks publics ──────────────────────────────────────────────────────────

async def on_member_update_hook(
    before: discord.Member, after: discord.Member
):
    """Hook pour on_member_update (changements de nick)."""
    if before.bot or after.bot:
        return
    if before.display_name == after.display_name:
        return
    try:
        alert = await _check_name(after, after.display_name)
        if alert:
            await _log_and_alert(after, alert)
    except Exception as ex:
        print(f"[impersonation_detector on_member_update] {ex}")


async def on_user_update_hook(
    before: discord.User, after: discord.User
):
    """Hook pour on_user_update (changements username + avatar global)."""
    if before.bot or after.bot:
        return
    try:
        # Check chaque guild où on partage
        guilds_shared = []
        if _bot:
            for g in _bot.guilds:
                m = g.get_member(after.id)
                if m:
                    guilds_shared.append(m)

        for member in guilds_shared:
            # Username change
            if before.name != after.name:
                alert = await _check_name(member, after.name)
                if alert:
                    await _log_and_alert(member, alert)

            # Avatar change
            before_hash = ""
            after_hash = ""
            try:
                if before.avatar:
                    before_hash = str(before.avatar.key)
                if after.avatar:
                    after_hash = str(after.avatar.key)
            except Exception:
                pass
            if before_hash != after_hash and after_hash:
                alert = await _check_avatar(member, after_hash)
                if alert:
                    await _log_and_alert(member, alert)
    except Exception as ex:
        print(f"[impersonation_detector on_user_update] {ex}")


__all__ = [
    "setup",
    "init_db",
    "refresh_staff_index",
    "on_member_update_hook",
    "on_user_update_hook",
]
