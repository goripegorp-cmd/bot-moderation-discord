"""
ux_polish.py — Theme switcher + tutorial + accent personnel (Phase 141).

Trois améliorations UX finales :

1. **THEME SWITCHER PERSONNEL** — chaque user peut choisir une teinte
   d'accent pour les panels V2 ephemeral qui le concernent
   • Catalogue : default / dark / neon / warm / ocean / forest
   • Stocké dans user_theme_pref (guild_id, user_id, theme_key)
   • Helper get_user_accent(guild_id, user_id) → int hex
   • Override les couleurs de container par défaut

2. **TUTORIAL INTERACTIF** — panel V2 multi-étapes pour découvrir le bot
   • 6 sections : Hub / Économie / Combat / Alliance / Voix / Tickets
   • Navigation via boutons « Suivant » / « Précédent » / « Fermer »
   • Persistent timeout=None pour rester actif

3. **CLOSE BUTTONS** — helper rapide pour ajouter "❌ Fermer" sur n'importe
   quel panel V2 ephemeral (déjà disponible via panels_helpers, ici on
   centralise le wording + l'API).

DB tables (créées à la volée) :
- user_theme_pref (guild_id, user_id, theme_key) PK composite

API publique :
- setup(get_db_fn, v2_helpers)
- THEMES catalog
- get_user_accent(guild_id, user_id, default=...) -> int hex
- set_user_theme(guild_id, user_id, theme_key) -> bool
- build_themes_panel(current_theme) — picker V2
- build_tutorial_step(step_idx, guild_name) — wizard V2

⚠️ Conforme RULES.md : zéro relationnel. Pure UX personnalisation.
"""
from __future__ import annotations

from typing import Optional

import discord


# ─── Catalogue des thèmes ────────────────────────────────────────────────
# Chaque thème = couleur d'accent pour les panels V2 ephemeral
THEMES = {
    "default": {"emoji": "🌌", "label": "Standard",  "color": 0x5865F2},
    "dark":    {"emoji": "🌑", "label": "Sombre",    "color": 0x2C2F33},
    "neon":    {"emoji": "🔮", "label": "Néon",      "color": 0xE91E63},
    "warm":    {"emoji": "🔥", "label": "Chaleureux","color": 0xE67E22},
    "ocean":   {"emoji": "🌊", "label": "Océan",     "color": 0x1ABC9C},
    "forest":  {"emoji": "🌲", "label": "Forêt",     "color": 0x27AE60},
}

DEFAULT_THEME_KEY = "default"

# Tutorial — 6 étapes pédagogiques
TUTORIAL_STEPS = [
    {
        "title": "🏠  LE HUB CENTRAL",
        "body": (
            "Tout passe par le **hub d'engagement** — c'est ton tableau de bord.\n\n"
            "🎯 **Dans le hub tu trouves :**\n"
            "• Tes événements en cours\n"
            "• Tes quêtes quotidiennes\n"
            "• Boutons rapides vers Économie / PvP / Outils\n\n"
            "💡 Le hub est épinglé dans un salon dédié — clique sur ses boutons "
            "pour ouvrir des panels personnels (ephemeral)."
        ),
    },
    {
        "title": "💰  ÉCONOMIE & PROGRESSION",
        "body": (
            "Le serveur a une économie complète :\n\n"
            "• 🪙 **Coins** gagnés via messages, vocaux, events, daily reward\n"
            "• 🏦 **Banque** (`/bank`) pour stocker + gagner des intérêts\n"
            "• 🎁 **Daily** (`/daily`) — récompense quotidienne avec streak\n"
            "• 🎰 **Wheel** (`/wheel`) — spin pour des récompenses random\n"
            "• 🛒 **Marketplace** entre joueurs (trade / auction)\n"
            "• 🏅 **Milestones** (`/milestones`) — paliers streak/vétéran/prestige\n"
            "• ✨ **Bonus** (`/bonus`) — cycle hebdo de bonus économiques"
        ),
    },
    {
        "title": "⚔️  COMBAT & EVENTS",
        "body": (
            "Le combat est au cœur du serveur :\n\n"
            "• 🐲 **Boss Raids** — événements collectifs, attaque pour des coins\n"
            "• 🌍 **World Boss hebdo** (samedi 21h FR) — gros loot collectif\n"
            "• ⚔️ **Duels** (`/duel @user`) — combat 1v1 avec mise\n"
            "• 🎒 **Inventory** (`/inventory`) — gear, enchants, durabilité\n"
            "• 🔨 **Crafting** — recettes pour combiner items\n"
            "• 💎 **Achievements** (`/achievements`) — succès cumulatifs"
        ),
    },
    {
        "title": "🏰  ALLIANCES & GUILDES",
        "body": (
            "Rejoins ou crée une alliance pour jouer en équipe :\n\n"
            "• 🤝 **Alliance** — équipe permanente avec salon + rôle dédiés\n"
            "• 💰 **Coffre partagé** (`/vault`) — trésor + items déposés\n"
            "• 📜 **Audit log** — historique de toutes les actions\n"
            "• 🏆 **Top contributeurs** — leaderboard interne\n"
            "• 👑 **Faction wars** — compétitions inter-alliances\n\n"
            "_Le chef expulse de l'alliance, **jamais** du serveur Discord._"
        ),
    },
    {
        "title": "🎙️  VOIX & SOCIAL",
        "body": (
            "Discord c'est aussi du vocal :\n\n"
            "• 🎙️ **VC créables** — un trigger pour ton vocal personnel\n"
            "• 🎧 **Paliers vocaux** (`/voice levels`) — récompenses cumulées\n"
            "• 🎁 **Wheel / Daily** — gains réguliers\n"
            "• 🎮 **Game Night** vocal hebdo — mini-jeux interactifs\n"
            "• ⚔️ **Rival** déclaré — bonus en duel\n\n"
            "_Pas de feature relationnelle / câlin / etc. sur ce serveur._"
        ),
    },
    {
        "title": "🎫  STAFF & SUPPORT",
        "body": (
            "Pour les questions / problèmes :\n\n"
            "• 🎫 **Tickets** — ouvre un panel ticket depuis le hub\n"
            "• 📋 **Wiki** (`/community wiki <slug>`) — FAQ persistente\n"
            "• 💡 **Suggest** (`/community suggest`) — propose une idée\n"
            "• 🗺️ **Roadmap** (`/community roadmap`) — vote sur les suggestions\n"
            "• 🛡️ **Modération** — sanctions visibles via `/mod`\n\n"
            "_Le staff est là pour aider — pas pour bannir au hasard._"
        ),
    },
]


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
# DB
# ═══════════════════════════════════════════════════════════════════════════════

async def _ensure_tables():
    global _tables_initialized
    if _tables_initialized or _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS user_theme_pref (
                guild_id INTEGER,
                user_id INTEGER,
                theme_key TEXT DEFAULT 'default',
                set_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, user_id)
            )''')
            await db.commit()
        _tables_initialized = True
    except Exception as ex:
        print(f"[ux_polish _ensure_tables] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# THEME API
# ═══════════════════════════════════════════════════════════════════════════════

async def get_user_theme_key(guild_id: int, user_id: int) -> str:
    """Retourne la clé de thème du user (ou 'default')."""
    if _get_db is None:
        return DEFAULT_THEME_KEY
    await _ensure_tables()
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT theme_key FROM user_theme_pref "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        if row and row[0] and row[0] in THEMES:
            return row[0]
    except Exception:
        pass
    return DEFAULT_THEME_KEY


async def get_user_accent(
    guild_id: int, user_id: int, default: int = 0x5865F2
) -> int:
    """Retourne la couleur d'accent du user (hex int)."""
    key = await get_user_theme_key(guild_id, user_id)
    theme = THEMES.get(key, THEMES[DEFAULT_THEME_KEY])
    return int(theme.get("color", default))


async def set_user_theme(
    guild_id: int, user_id: int, theme_key: str
) -> bool:
    """Set le thème du user. Retourne False si clé invalide."""
    if theme_key not in THEMES or _get_db is None:
        return False
    await _ensure_tables()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO user_theme_pref"
                "(guild_id, user_id, theme_key, set_at) "
                "VALUES(?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "theme_key=excluded.theme_key, set_at=CURRENT_TIMESTAMP",
                (guild_id, user_id, theme_key),
            )
            await db.commit()
        return True
    except Exception as ex:
        print(f"[ux_polish set_user_theme] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# PANELS V2
# ═══════════════════════════════════════════════════════════════════════════════

def build_themes_panel(current_theme_key: str = DEFAULT_THEME_KEY):
    """Panel V2 — picker de thème."""
    if _v2_helpers is None:
        return None
    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    cur_theme = THEMES.get(current_theme_key, THEMES[DEFAULT_THEME_KEY])

    class _ThemesPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title("🎨 Thème personnel"))
            items.append(v2_subtitle(
                f"_Couleur d'accent de tes panels ephemeral_"
            ))
            items.append(v2_divider())

            items.append(v2_body(
                f"🎨 **Thème actuel :** {cur_theme['emoji']} "
                f"**{cur_theme['label']}** _(`{current_theme_key}`)_"
            ))
            items.append(v2_divider())

            items.append(v2_body("### 🎨 THÈMES DISPONIBLES"))
            lines = []
            for key, theme in THEMES.items():
                marker = " ← _actuel_" if key == current_theme_key else ""
                lines.append(
                    f"{theme['emoji']} **{theme['label']}** "
                    f"_(`/theme set {key}`)_{marker}"
                )
            items.append(v2_body("\n".join(lines)))

            items.append(v2_divider())
            items.append(v2_body(
                "_💡 `/theme set <clé>` pour changer. "
                "Le thème s'applique aux nouveaux panels ouverts._"
            ))

            self.add_item(v2_container(*items, color=cur_theme["color"]))

    return _ThemesPanel()


class TutorialView:
    """Wrapper qui produit un LayoutView par étape avec boutons navigation."""

    @staticmethod
    def build(step_idx: int, guild_name: str, accent_color: int):
        if _v2_helpers is None:
            return None
        LayoutView = _v2_helpers['LayoutView']
        v2_title = _v2_helpers['v2_title']
        v2_subtitle = _v2_helpers['v2_subtitle']
        v2_body = _v2_helpers['v2_body']
        v2_divider = _v2_helpers['v2_divider']
        v2_container = _v2_helpers['v2_container']

        idx = max(0, min(len(TUTORIAL_STEPS) - 1, step_idx))
        step = TUTORIAL_STEPS[idx]
        total = len(TUTORIAL_STEPS)

        class _TutorialStepPanel(LayoutView):
            def __init__(self):
                super().__init__(timeout=600)
                items = []
                items.append(v2_title(step["title"]))
                items.append(v2_subtitle(
                    f"_Étape {idx + 1}/{total} — Tour du serveur {guild_name}_"
                ))
                items.append(v2_divider())
                items.append(v2_body(step["body"]))
                items.append(v2_divider())

                # Progress bar visuel
                bar_len = 12
                filled = round((idx + 1) / total * bar_len)
                bar = "█" * filled + "░" * (bar_len - filled)
                items.append(v2_body(
                    f"📊 Progression : `{bar}` {idx + 1}/{total}"
                ))

                items.append(v2_divider())
                hint = []
                if idx > 0:
                    hint.append(f"`/tutorial step:{idx}` ← précédent")
                if idx < total - 1:
                    hint.append(f"`/tutorial step:{idx + 2}` → suivant")
                if not hint:
                    hint.append("✅ Tutorial terminé ! Tu as tout vu.")
                items.append(v2_body("_💡 " + " · ".join(hint) + "_"))

                self.add_item(v2_container(*items, color=accent_color))

        return _TutorialStepPanel()


__all__ = [
    "setup",
    "THEMES", "DEFAULT_THEME_KEY", "TUTORIAL_STEPS",
    "get_user_theme_key", "get_user_accent", "set_user_theme",
    "build_themes_panel", "TutorialView",
]
