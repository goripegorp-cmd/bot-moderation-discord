"""
promo_tools.py — Outils de promotion EXTERNE du serveur (owner 2026-06-29).

ZÉRO bot ajouté : tout passe par NOTRE bot. Trois capacités, 100% dans les règles
Discord (pas de spam, pas d'achat de membres, PAS d'auto-bump selfbot) :

1. SUIVI PAR-ANNUAIRE — un lien d'invitation UNIQUE par annuaire (Disboard, DiscordL,
   serveur-prive.net…). On lit le compteur `.uses` de chaque lien → on sait QUEL annuaire
   amène le plus d'arrivées. (Le bump lui-même reste MANUEL : Discord le verrouille à un
   humain dans le serveur ; cf. bump_reminder côté bot.py. Aucune API de bump n'existe.)
2. KIT DE FICHE — texte de présentation + tags SEO longue-traîne prêts à coller.
3. CHECKLIST — quels annuaires sont faits / à faire (flag `listed`).

API : setup(get_db_fn, bot=None) · init_db() · PROMO_DIRECTORIES · directory_meta ·
      register_source · set_listed · list_sources · get_stats(guild) · build_listing_kit().
"""
from __future__ import annotations

from typing import Optional

import discord

_get_db = None
_bot = None

# ─── Catalogue des annuaires recommandés (recherche vérifiée 2026-06-29) ───────
# needs_bot=True UNIQUEMENT pour Disboard : sa fiche exige SON bot in-server pour le
# bump /2h. TOUS les autres = fiche WEB, ZÉRO bot ajouté. (Pas d'API de bump nulle part :
# les « auto-bump » = selfbots = ban. Le bump humain de Disboard est rappelé par notre bot.)
PROMO_DIRECTORIES = [
    {"key": "disboard",          "label": "Disboard",           "url": "https://disboard.org/",             "needs_bot": True,  "note": "n°1 trafic · bump /2h · nécessite le bot Disboard"},
    {"key": "discordl_fr",       "label": "DiscordL 🇫🇷",        "url": "https://www.discordl.org/",         "needs_bot": False, "note": "n°1 annuaire FR · fiche web · 0 bot"},
    {"key": "serveurprive_fr",   "label": "Serveur-Privé 🇫🇷",   "url": "https://serveur-prive.net/discord", "needs_bot": False, "note": "catégorie Jeux · fiche web · 0 bot"},
    {"key": "discordtop_fr",     "label": "DiscordTop 🇫🇷",      "url": "https://discordtop.net/",           "needs_bot": False, "note": "classement FR par votes · fiche web · 0 bot"},
    {"key": "serveurdiscord_fr", "label": "Serveur-Discord 🇫🇷", "url": "https://serveur-discord.com/",      "needs_bot": False, "note": "annuaire FR par catégories · fiche web · 0 bot"},
    {"key": "discordme",         "label": "Discord.me",         "url": "https://discord.me/",               "needs_bot": False, "note": "SFW-friendly · fiche web · 0 bot"},
    {"key": "topgg",             "label": "Top.gg",             "url": "https://top.gg/",                   "needs_bot": False, "note": "gros trafic · fiche web + votes · 0 bot"},
    {"key": "discordservers",    "label": "DiscordServers.io",  "url": "https://discordservers.io/",        "needs_bot": False, "note": "fiche web · 0 bot (ex-Disforge, redirige ici)"},
]

_DIR_BY_KEY = {d["key"]: d for d in PROMO_DIRECTORIES}


def directory_meta(key: str) -> Optional[dict]:
    return _DIR_BY_KEY.get(key)


def setup(get_db_fn, *, bot=None):
    global _get_db, _bot
    _get_db = get_db_fn
    _bot = bot


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS promo_sources ("
                "guild_id INTEGER NOT NULL, "
                "source_key TEXT NOT NULL, "
                "label TEXT, "
                "code TEXT, "
                "listed INTEGER DEFAULT 0, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY (guild_id, source_key))"
            )
            await db.commit()
        print("[promo_tools] OK (suivi par-annuaire + kit + checklist)")
    except Exception as ex:
        print(f"[promo_tools init_db] {ex}")


async def register_source(guild_id: int, source_key: str, label: str, code: str) -> bool:
    """Enregistre/MAJ le lien d'invitation dédié d'un annuaire (préserve `listed`). FAIL-SAFE."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO promo_sources (guild_id, source_key, label, code) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, source_key) DO UPDATE SET label=excluded.label, code=excluded.code",
                (int(guild_id), source_key, label, code),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[promo_tools register_source] {ex}")
        return False


async def set_listed(guild_id: int, source_key: str, listed: bool, label: str = "") -> bool:
    """Bascule le flag « fiche créée sur le site » (checklist). FAIL-SAFE."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO promo_sources (guild_id, source_key, label, listed) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, source_key) DO UPDATE SET listed=excluded.listed",
                (int(guild_id), source_key, label, 1 if listed else 0),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[promo_tools set_listed] {ex}")
        return False


async def list_sources(guild_id: int) -> dict:
    """Renvoie {source_key: {label, code, listed}} pour la guilde. FAIL-SAFE."""
    out: dict = {}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT source_key, label, code, listed FROM promo_sources WHERE guild_id=?",
                (int(guild_id),),
            ) as cur:
                async for row in cur:
                    out[row[0]] = {"label": row[1] or "", "code": row[2] or "", "listed": bool(row[3])}
    except Exception as ex:
        print(f"[promo_tools list_sources] {ex}")
    return out


async def get_stats(guild: discord.Guild) -> list[dict]:
    """Pour chaque annuaire ayant un lien dédié, lit `.uses` (= arrivées cumulées via ce
    lien) et trie par arrivées décroissantes. FAIL-SAFE.
    Renvoie [{source_key, label, code, uses, alive}]."""
    rows = await list_sources(guild.id)
    if not rows:
        return []
    uses_by_code: Optional[dict] = {}
    try:
        for inv in await guild.invites():
            try:
                uses_by_code[inv.code] = int(inv.uses or 0)
            except Exception:
                continue
    except Exception:
        uses_by_code = None  # pas la perm « Gérer le serveur » → uses illisibles
    out = []
    for key, info in rows.items():
        code = info.get("code") or ""
        if not code:
            continue
        alive = uses_by_code is not None and code in uses_by_code
        out.append({
            "source_key": key,
            "label": info.get("label") or _DIR_BY_KEY.get(key, {}).get("label", key),
            "code": code,
            "uses": uses_by_code.get(code, 0) if uses_by_code else 0,
            "alive": alive,
            "unknown": uses_by_code is None,
        })
    out.sort(key=lambda r: r["uses"], reverse=True)
    return out


# ─── Kit de fiche : tags SEO longue-traîne (la recherche montre qu'ils convertissent
#     bien mieux que des tags génériques type « gaming »). ────────────────────────────
_KIT_TAGS = [
    "mmorpg", "mmorpg-fr", "rpg", "rpg-fr", "jeu-de-role", "roleplay",
    "gaming-fr", "communaute-fr", "francophone", "open-world", "aventure",
]


def build_listing_kit(guild_name: str, invite_url: str, pitch: str = "") -> dict:
    """Génère un texte de fiche + des tags prêts à coller. Pur (aucune I/O)."""
    name = (guild_name or "Notre serveur").strip()
    default_pitch = (
        f"**{name}** — un MMORPG open-world francophone : quêtes, classes & ressources, "
        f"donjons, boss de monde et événements communautaires, dans une vraie ambiance "
        f"d'aventure. Communauté active et bienveillante, débutants bienvenus. Rejoins-nous !"
    )
    body = pitch.strip() or default_pitch
    short = f"{name} · MMORPG open-world FR — quêtes, donjons, events. Communauté active 🎮"
    return {
        "short": short[:120],
        "body": body,
        "tags": list(_KIT_TAGS),
        "invite": invite_url or "",
    }


__all__ = [
    "setup", "init_db", "PROMO_DIRECTORIES", "directory_meta",
    "register_source", "set_listed", "list_sources", "get_stats",
    "build_listing_kit",
]
