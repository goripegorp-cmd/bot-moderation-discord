"""
roblox_link.py — Vérification de compte Roblox + game library (Phase 136).

Système de verification sans OAuth, via code à coller dans la **description
publique** (bio) du profil Roblox. Utilise uniquement les API publiques
de Roblox (pas de clé requise) :

- POST https://users.roblox.com/v1/usernames/users    → username → userId
- GET  https://users.roblox.com/v1/users/{userId}     → description (bio)
- GET  https://games.roblox.com/v1/games?universeIds  → infos jeu

Workflow link verify :

1. User : `/roblox link <username>` →
     - Bot fetch userId via users.roblox.com
     - Bot génère code aléatoire (10 chars alphanum)
     - Bot stocke (user_id, roblox_user_id, code, expires_at) dans pending
     - Bot répond : "Mets `ABC123XYZ0` dans ta bio Roblox + tape /roblox verify"

2. User colle le code dans sa bio Roblox (https://www.roblox.com/my/account)

3. User : `/roblox verify` →
     - Bot fetch bio via users.roblox.com
     - Si code présent → insert dans roblox_account_links + delete pending
     - Si pas présent → "Code introuvable, retry"

4. User : `/roblox unlink` → supprime le link

API publique :
- setup(get_db_fn, v2_helpers)
- fetch_roblox_userid(username) -> int | None
- fetch_roblox_bio(roblox_user_id) -> str | None
- start_link(guild_id, user_id, username) -> (status, msg, code?)
- verify_link(guild_id, user_id) -> (ok, msg, roblox_username?)
- unlink(guild_id, user_id) -> bool
- get_link(guild_id, user_id) -> dict | None
- build_profile_panel(guild, member, roblox_info) — LayoutView V2

⚠️ Conforme à RULES.md : aucun système relationnel.
Pur outil fonctionnel pour lier comptes Discord ↔ Roblox.
"""
from __future__ import annotations

import asyncio
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

try:
    import aiohttp
    _AIOHTTP_OK = True
except ImportError:
    _AIOHTTP_OK = False


# ─── Configuration ───────────────────────────────────────────────────────
LINK_CODE_LENGTH = 10
LINK_CODE_TTL_MINUTES = 15
LINK_CODE_PREFIX = "AB-"        # Préfixe pour repérage facile dans la bio
ROBLOX_API_TIMEOUT_SEC = 10
USER_AGENT = "Discord-Bot-RobloxLink/1.0"


# Références injectées
_get_db = None
_v2_helpers = None
_tables_initialized = False


def setup(get_db_fn, v2_helpers: dict):
    """Configure le module."""
    global _get_db, _v2_helpers
    _get_db = get_db_fn
    _v2_helpers = v2_helpers


# ═══════════════════════════════════════════════════════════════════════════════
# DB — Tables
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_tables():
    global _tables_initialized
    if _tables_initialized or _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS roblox_account_links (
                guild_id INTEGER,
                user_id INTEGER,
                roblox_user_id INTEGER,
                roblox_username TEXT,
                roblox_display_name TEXT,
                verified_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_roblox_links_roblox_id "
                "ON roblox_account_links(roblox_user_id)"
            )
            await db.execute('''CREATE TABLE IF NOT EXISTS roblox_link_pending (
                guild_id INTEGER,
                user_id INTEGER,
                roblox_user_id INTEGER,
                roblox_username TEXT,
                code TEXT,
                requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME,
                PRIMARY KEY (guild_id, user_id)
            )''')
            await db.execute('''CREATE TABLE IF NOT EXISTS roblox_game_library (
                guild_id INTEGER,
                universe_id INTEGER,
                name TEXT,
                last_updated_iso TEXT,
                place_id INTEGER,
                added_by INTEGER,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, universe_id)
            )''')
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[roblox_link _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# API ROBLOX — fetch user + bio
# ═══════════════════════════════════════════════════════════════════════════════

def _gen_code() -> str:
    """Génère un code de verification : AB-XXXXXXXXXX."""
    chars = string.ascii_uppercase + string.digits
    body = "".join(random.choice(chars) for _ in range(LINK_CODE_LENGTH))
    return f"{LINK_CODE_PREFIX}{body}"


async def fetch_roblox_userinfo(username: str) -> Optional[dict]:
    """Fetch userId + displayName via POST users.roblox.com.

    Retourne {'id', 'name', 'displayName'} ou None.
    """
    if not _AIOHTTP_OK or not username:
        return None
    username = username.strip()
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": True}
    try:
        timeout = aiohttp.ClientTimeout(total=ROBLOX_API_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url, json=payload,
                headers={"User-Agent": USER_AGENT,
                         "Content-Type": "application/json"},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                arr = data.get("data") or []
                if not arr:
                    return None
                u = arr[0]
                return {
                    "id": int(u.get("id", 0) or 0),
                    "name": u.get("name", ""),
                    "displayName": u.get("displayName", ""),
                }
    except Exception as ex:
        print(f"[roblox_link fetch_roblox_userinfo] {ex}")
        return None


async def fetch_roblox_bio(roblox_user_id: int) -> Optional[str]:
    """Fetch la description (bio) publique d'un compte Roblox."""
    if not _AIOHTTP_OK or not roblox_user_id:
        return None
    url = f"https://users.roblox.com/v1/users/{int(roblox_user_id)}"
    try:
        timeout = aiohttp.ClientTimeout(total=ROBLOX_API_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url, headers={"User-Agent": USER_AGENT}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return str(data.get("description") or "")
    except Exception as ex:
        print(f"[roblox_link fetch_roblox_bio] {ex}")
        return None


async def fetch_game_info(universe_id: int) -> Optional[dict]:
    """Fetch infos d'un jeu via games.roblox.com.

    Retourne {'id', 'name', 'lastUpdated', 'rootPlaceId', 'playing', 'visits'} ou None.
    """
    if not _AIOHTTP_OK or not universe_id:
        return None
    url = f"https://games.roblox.com/v1/games?universeIds={int(universe_id)}"
    try:
        timeout = aiohttp.ClientTimeout(total=ROBLOX_API_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url, headers={"User-Agent": USER_AGENT}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                arr = data.get("data") or []
                if not arr:
                    return None
                g = arr[0]
                return {
                    "id": int(g.get("id", 0) or 0),
                    "name": g.get("name", ""),
                    "lastUpdated": g.get("updated", ""),
                    "rootPlaceId": int(g.get("rootPlaceId", 0) or 0),
                    "playing": int(g.get("playing", 0) or 0),
                    "visits": int(g.get("visits", 0) or 0),
                }
    except Exception as ex:
        print(f"[roblox_link fetch_game_info] {ex}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# LINK FLOW — start / verify / unlink / get
# ═══════════════════════════════════════════════════════════════════════════════

async def get_link(guild_id: int, user_id: int) -> Optional[dict]:
    """Retourne le link Roblox actif (ou None)."""
    if _get_db is None:
        return None
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT roblox_user_id, roblox_username, roblox_display_name, verified_at "
                "FROM roblox_account_links WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "roblox_user_id": int(row[0] or 0),
            "roblox_username": row[1] or "",
            "roblox_display_name": row[2] or "",
            "verified_at": row[3],
        }
    except Exception as ex:
        print(f"[roblox_link get_link] {ex}")
        return None


async def start_link(
    guild_id: int, user_id: int, username: str
) -> tuple[str, str, Optional[str]]:
    """Démarre une procédure de link.

    Returns: (status, message, code_ou_None)
        status in {"started", "already_linked", "user_not_found", "error"}
    """
    if not _AIOHTTP_OK:
        return "error", "Module HTTP indisponible.", None
    if _get_db is None:
        return "error", "Module non initialisé.", None

    # Déjà lié ?
    existing = await get_link(guild_id, user_id)
    if existing:
        return (
            "already_linked",
            f"Tu es déjà lié à **{existing['roblox_username']}**. "
            f"Fais `/roblox unlink` d'abord pour changer.",
            None,
        )

    # Fetch user info Roblox
    info = await fetch_roblox_userinfo(username)
    if not info or not info.get("id"):
        return (
            "user_not_found",
            f"Compte Roblox `{username}` introuvable.",
            None,
        )

    await _ensure_tables()
    code = _gen_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=LINK_CODE_TTL_MINUTES)
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO roblox_link_pending "
                "(guild_id, user_id, roblox_user_id, roblox_username, code, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "roblox_user_id=excluded.roblox_user_id, "
                "roblox_username=excluded.roblox_username, "
                "code=excluded.code, expires_at=excluded.expires_at, "
                "requested_at=CURRENT_TIMESTAMP",
                (guild_id, user_id, info["id"], info["name"],
                 code, expires.isoformat()),
            )
            await db.commit()
        return "started", info["name"], code
    except Exception as ex:
        print(f"[roblox_link start_link] {ex}")
        return "error", f"Erreur DB : `{ex}`", None


async def verify_link(
    guild_id: int, user_id: int
) -> tuple[bool, str, Optional[dict]]:
    """Vérifie si le code est dans la bio du compte Roblox pending.

    Returns: (ok, message, link_dict_ou_None)
    """
    if not _AIOHTTP_OK:
        return False, "Module HTTP indisponible.", None
    if _get_db is None:
        return False, "Module non initialisé.", None

    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT roblox_user_id, roblox_username, code, expires_at "
                "FROM roblox_link_pending WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return (
                False,
                "Aucune demande en cours. Lance `/roblox link <username>` d'abord.",
                None,
            )
        rblx_uid, rblx_user, code, expires_at = (
            int(row[0] or 0), row[1], row[2], row[3]
        )

        # Expiration
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_dt:
                async with _get_db() as db:
                    await db.execute(
                        "DELETE FROM roblox_link_pending "
                        "WHERE guild_id=? AND user_id=?",
                        (guild_id, user_id),
                    )
                    await db.commit()
                return (
                    False,
                    "Le code a expiré. Relance `/roblox link <username>`.",
                    None,
                )
        except Exception:
            pass

        # Fetch bio + vérif présence du code
        bio = await fetch_roblox_bio(rblx_uid)
        if bio is None:
            return False, "Impossible de lire ton profil Roblox (API down ?).", None
        if code not in bio:
            return (
                False,
                f"Le code `{code}` n'est pas dans ta bio Roblox.\n"
                f"_Va sur https://www.roblox.com/my/account → onglet "
                f"« About » et colle le code, puis retape `/roblox verify`._",
                None,
            )

        # Fetch display name pour avoir la donnée complète
        display = ""
        try:
            full_info = await fetch_roblox_userinfo(rblx_user)
            if full_info:
                display = full_info.get("displayName", "")
        except Exception:
            pass

        # Insert link + cleanup pending
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO roblox_account_links "
                "(guild_id, user_id, roblox_user_id, roblox_username, roblox_display_name) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "roblox_user_id=excluded.roblox_user_id, "
                "roblox_username=excluded.roblox_username, "
                "roblox_display_name=excluded.roblox_display_name, "
                "verified_at=CURRENT_TIMESTAMP",
                (guild_id, user_id, rblx_uid, rblx_user, display),
            )
            await db.execute(
                "DELETE FROM roblox_link_pending WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            await db.commit()

        return (
            True,
            f"Compte Roblox **{rblx_user}** lié avec succès !",
            {
                "roblox_user_id": rblx_uid,
                "roblox_username": rblx_user,
                "roblox_display_name": display,
            },
        )
    except Exception as ex:
        print(f"[roblox_link verify_link] {ex}")
        return False, f"Erreur DB : `{ex}`", None


async def unlink(guild_id: int, user_id: int) -> bool:
    """Supprime le link. Retourne True si trouvé + supprimé."""
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "DELETE FROM roblox_account_links WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            await db.execute(
                "DELETE FROM roblox_link_pending WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception as ex:
        print(f"[roblox_link unlink] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# GAME LIBRARY — tracking auto-fetch
# ═══════════════════════════════════════════════════════════════════════════════

async def add_game(
    guild_id: int, universe_id: int, added_by: int
) -> tuple[bool, str]:
    """Ajoute un universe au tracking (fetch les infos via API)."""
    if _get_db is None:
        return False, "Module non initialisé."
    if not _AIOHTTP_OK:
        return False, "Module HTTP indisponible."

    await _ensure_tables()
    info = await fetch_game_info(universe_id)
    if not info:
        return False, f"Universe ID `{universe_id}` introuvable."

    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO roblox_game_library "
                "(guild_id, universe_id, name, last_updated_iso, place_id, added_by) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, universe_id) DO UPDATE SET "
                "name=excluded.name, last_updated_iso=excluded.last_updated_iso, "
                "place_id=excluded.place_id",
                (guild_id, universe_id, info["name"], info["lastUpdated"],
                 info["rootPlaceId"], added_by),
            )
            await db.commit()
        return True, f"Jeu **{info['name']}** ajouté au tracking."
    except Exception as ex:
        print(f"[roblox_link add_game] {ex}")
        return False, f"Erreur DB : `{ex}`"


async def remove_game(guild_id: int, universe_id: int) -> bool:
    """Retire un universe du tracking."""
    if _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "DELETE FROM roblox_game_library "
                "WHERE guild_id=? AND universe_id=?",
                (guild_id, universe_id),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0
    except Exception as ex:
        print(f"[roblox_link remove_game] {ex}")
        return False


async def list_games(guild_id: int) -> list[dict]:
    """Liste les jeux trackés."""
    if _get_db is None:
        return []
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT universe_id, name, last_updated_iso, place_id, added_at "
                "FROM roblox_game_library WHERE guild_id=? "
                "ORDER BY added_at DESC",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "universe_id": int(r[0]),
                "name": r[1] or "?",
                "last_updated": r[2] or "",
                "place_id": int(r[3] or 0),
                "added_at": r[4],
            }
            for r in rows
        ]
    except Exception as ex:
        print(f"[roblox_link list_games] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERING — Panels V2
# ═══════════════════════════════════════════════════════════════════════════════

def build_link_instructions_panel(
    roblox_username: str, code: str, member_name: str = ""
):
    """Panel V2 affichant les instructions de link (ephemeral)."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _LinkInstructions(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("🔗  VÉRIFICATION ROBLOX"))
            items.append(v2_subtitle(
                f"_Procédure pour lier ton Discord à **{roblox_username}**_"
            ))
            items.append(v2_divider())

            items.append(v2_body("**╔═══ 📝  ÉTAPE 1 — TON CODE  ═══╗**"))
            items.append(v2_body(
                f"Voici ton code de vérification (valable {LINK_CODE_TTL_MINUTES} min) :\n\n"
                f"# `{code}`\n\n"
                f"_Garde-le précieusement — il est unique à toi._"
            ))

            items.append(v2_divider())
            items.append(v2_body("**╔═══ 🌐  ÉTAPE 2 — COLLE-LE  ═══╗**"))
            items.append(v2_body(
                f"1. Va sur ton **profil Roblox** :\n"
                f"   https://www.roblox.com/users/profile\n"
                f"2. Clique sur le **crayon** à côté de ta description\n"
                f"3. **Colle le code** quelque part dans ta bio (n'importe où)\n"
                f"4. Sauvegarde"
            ))

            items.append(v2_divider())
            items.append(v2_body("**╔═══ ✅  ÉTAPE 3 — VALIDE  ═══╗**"))
            items.append(v2_body(
                f"De retour ici, tape :\n\n"
                f"# `/roblox verify`\n\n"
                f"_Le bot lira ta bio et confirmera le lien. "
                f"Une fois lié, tu peux retirer le code de ta bio._"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 Sécurité : ce code prouve que tu contrôles bien le "
                "compte Roblox. Personne d'autre ne peut le mettre dans "
                "sa bio sans avoir accès à ton compte._"
            ))

            self.add_item(v2_container(*items, color=0x00A2FF))

    return _LinkInstructions()


def build_profile_panel(
    member: discord.Member, link_info: dict
):
    """Panel V2 montrant le profil Roblox lié d'un membre."""
    if _v2_helpers is None or not link_info:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    rblx_id = int(link_info["roblox_user_id"])
    rblx_user = link_info.get("roblox_username", "")
    rblx_disp = link_info.get("roblox_display_name", "") or rblx_user

    class _ProfilePanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(f"🎮  PROFIL ROBLOX DE {member.display_name.upper()}"))
            items.append(v2_subtitle(
                f"_Compte vérifié via code dans la bio_"
            ))
            items.append(v2_divider())

            items.append(v2_body(
                f"👤 **Username :** [`{rblx_user}`](https://www.roblox.com/users/{rblx_id}/profile)\n"
                f"✨ **Display name :** `{rblx_disp}`\n"
                f"🆔 **User ID :** `{rblx_id}`\n"
                f"📅 **Lié depuis :** {link_info.get('verified_at', '?')}"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                f"🔗 **Lien public :**\n"
                f"https://www.roblox.com/users/{rblx_id}/profile"
            ))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/roblox unlink` pour retirer le lien."
                " `/roblox link <username>` pour le changer._"
            ))

            self.add_item(v2_container(*items, color=0x00A2FF))

    return _ProfilePanel()


def build_games_panel(games: list[dict], guild_name: str = ""):
    """Panel V2 listant les jeux trackés."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    class _GamesPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("🎮  GAME LIBRARY ROBLOX"))
            items.append(v2_subtitle(
                f"_Les jeux suivis pour ce serveur ({len(games)})_"
            ))
            items.append(v2_divider())

            if not games:
                items.append(v2_body(
                    "_Aucun jeu tracké. Staff peut ajouter avec "
                    "`/roblox add_game <universe_id>`._"
                ))
            else:
                lines = []
                for g in games[:15]:
                    place = g.get("place_id", 0)
                    last_upd = g.get("last_updated", "")
                    short_upd = last_upd.split("T")[0] if last_upd else "?"
                    if place:
                        lines.append(
                            f"🎯 [`{g['name']}`](https://www.roblox.com/games/{place}) "
                            f"_(universe `{g['universe_id']}`, MAJ `{short_upd}`)_"
                        )
                    else:
                        lines.append(
                            f"🎯 `{g['name']}` "
                            f"_(universe `{g['universe_id']}`, MAJ `{short_upd}`)_"
                        )
                if len(games) > 15:
                    lines.append(f"_… et {len(games) - 15} autre(s)_")
                items.append(v2_body("\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 L'universe ID se trouve dans l'URL du studio "
                "(Game Settings → Basic Info → place ID + Universe)._"
            ))

            self.add_item(v2_container(*items, color=0x00A2FF))

    return _GamesPanel()


__all__ = [
    "setup",
    # Link API
    "fetch_roblox_userinfo", "fetch_roblox_bio",
    "start_link", "verify_link", "unlink", "get_link",
    # Games API
    "fetch_game_info", "add_game", "remove_game", "list_games",
    # Panels
    "build_link_instructions_panel", "build_profile_panel", "build_games_panel",
    # Constants
    "LINK_CODE_TTL_MINUTES",
]
