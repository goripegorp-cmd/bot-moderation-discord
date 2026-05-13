"""
server_architect.py - Refonte automatique de l'architecture du serveur (Phase 3.1).

Le bot analyse les salons existants, propose une architecture propre groupee par
themes (Bienvenue / Annonces / Discussion / Streams / Trade / Support / Staff),
et peut l'appliquer avec backup automatique pour rollback.

Composants :
    - ChannelAnalyzer : classifie chaque salon par theme (rules-based sur le nom)
    - Blueprint : structure cible (categories + ordre + perms suggerees)
    - apply_blueprint() : applique le blueprint (deplace, renomme, configure)
    - backup_state() / restore_state() : snapshot/restore complet

Categories proposees par defaut :
    📌 Bienvenue (rules, roles, welcome)
    📣 Annonces & Lives (news, twitch-alerts, youtube-alerts, tiktok)
    💬 Discussion (general, off-topic, blagues)
    🎮 Gaming (par jeu)
    🛒 Marketplace (trade, vente, recherche)
    🎫 Support & Aide (help, tickets)
    🎤 Vocaux (lobby, vocaux libres)
    🔧 Staff (mod-only, admin-only)
    📋 Logs (audit, mod-logs, join-leave)

Securite :
    - Aucun salon supprime sans confirmation explicite
    - Toutes les modifs sont reversibles via le backup auto avant apply
    - Owner only (l'integrateur bot.py doit gater la commande)
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import discord

from paths import module_dir


DATA_DIR = module_dir("architecture")


# =============================================================================
# CATEGORIES & CLASSIFICATION
# =============================================================================

class Theme(str, Enum):
    WELCOME = "welcome"
    ANNOUNCEMENTS = "announcements"
    LIVES = "lives"
    SOCIAL = "social"
    DEVELOPMENT = "development"     # Phase 3.2 : devlog, playtest, builds
    STUDIOS = "studios"             # Phase 3.2 : studios suivis, leurs actus
    LORE = "lore"                   # Phase 3.2 : worldbuilding, design
    EVENTS = "events"               # Phase 3.2 : evenements, contests
    DISCUSSION = "discussion"
    GAMING = "gaming"
    MARKETPLACE = "marketplace"
    SUPPORT = "support"
    VOICE = "voice"
    STAFF = "staff"
    LOGS = "logs"
    OTHER = "other"


THEME_META: dict[Theme, dict] = {
    Theme.WELCOME:       {"icon": "📌", "name": "Bienvenue",       "order": 0,
                          "desc": "Règles, choix de rôles, présentations"},
    Theme.ANNOUNCEMENTS: {"icon": "📣", "name": "Annonces",        "order": 1,
                          "desc": "Annonces officielles, news, info"},
    Theme.DEVELOPMENT:   {"icon": "🛠️", "name": "Développement",   "order": 2,
                          "desc": "Devlog, playtests, builds, design game"},
    Theme.STUDIOS:       {"icon": "🏢", "name": "Studios suivis",  "order": 3,
                          "desc": "Actus des studios que vous suivez"},
    Theme.LIVES:         {"icon": "🎬", "name": "Lives & Vidéos",  "order": 4,
                          "desc": "Notifications Twitch, YouTube, TikTok"},
    Theme.SOCIAL:        {"icon": "📡", "name": "Réseaux sociaux", "order": 5,
                          "desc": "Twitter, Instagram, Reddit, etc."},
    Theme.EVENTS:        {"icon": "🎉", "name": "Évènements",      "order": 6,
                          "desc": "Évènements, contests, giveaways"},
    Theme.LORE:          {"icon": "📖", "name": "Lore & Univers",  "order": 7,
                          "desc": "Histoire, worldbuilding, concept art"},
    Theme.DISCUSSION:    {"icon": "💬", "name": "Discussion",      "order": 8,
                          "desc": "Général, off-topic, mèmes"},
    Theme.GAMING:        {"icon": "🎮", "name": "Gaming",          "order": 9,
                          "desc": "Salons par jeu"},
    Theme.MARKETPLACE:   {"icon": "🛒", "name": "Marketplace",     "order": 10,
                          "desc": "Trade, vente, recherche"},
    Theme.SUPPORT:       {"icon": "🎫", "name": "Support & Aide",  "order": 11,
                          "desc": "Tickets, aide, FAQ"},
    Theme.VOICE:         {"icon": "🎤", "name": "Vocaux",          "order": 12,
                          "desc": "Salons vocaux libres et lobbies"},
    Theme.STAFF:         {"icon": "🔧", "name": "Staff",           "order": 13,
                          "desc": "Salons mods/admins uniquement"},
    Theme.LOGS:          {"icon": "📋", "name": "Logs",            "order": 14,
                          "desc": "Audit, modération, join-leave"},
    Theme.OTHER:         {"icon": "📦", "name": "Autres",          "order": 15,
                          "desc": "Salons non classifiés"},
}


# Patterns de classification (lower-case match dans le nom du salon)
# Premier match gagne. Phase 3.2 : etendu avec game dev, studios, lore, events.
CLASSIFICATION_RULES: list[tuple[Theme, list[str]]] = [
    (Theme.WELCOME, [
        "regle", "rule", "rules", "welcome", "bienvenue", "presentation",
        "choix-role", "choix-roles", "choix-rôle", "roles-mention", "self-role",
        "lis-moi", "lisez-moi", "info-server", "info-serveur",
        "abylumis", "abylum",  # phase 3.2 : utilisateur specifique
    ]),
    (Theme.ANNOUNCEMENTS, [
        "annonce", "announce", "announcement", "news", "actu", "info-bot",
        "changelog", "update", "patch", "communique", "communiqué",
        "mise-a-jour", "mise-à-jour",
    ]),
    (Theme.DEVELOPMENT, [  # Phase 3.2 : devlog game dev
        "devlog", "dev-log", "dev-blog", "development", "developpement",
        "developement", "build", "builds", "playtest", "play-test",
        "alpha", "beta", "testing", "test-server", "qa",
        "feedback-dev", "bug-report", "feature-request",
        "concept", "wip", "work-in-progress", "showcase",
    ]),
    (Theme.STUDIOS, [  # Phase 3.2 : studios suivis
        "studio", "studios", "studios-suivis", "developer-news",
        "indie-news", "studio-news", "studio-actu", "follows",
        "creators-news",
    ]),
    (Theme.LIVES, [
        "live", "lives", "stream", "streams", "twitch", "youtube",
        "tiktok", "kick", "vod", "video", "videos", "yt-",
        "broadcast", "diffusion", "en-direct",
    ]),
    (Theme.SOCIAL, [
        "twitter", "x-post", "instagram", "reddit", "rosocial", "social",
        "tweet", "post-x", "facebook", "linkedin",
    ]),
    (Theme.EVENTS, [  # Phase 3.2 : events / contests
        "event", "events", "evenement", "evenements", "évènement", "évènements",
        "contest", "concours", "tournoi", "tournament",
        "giveaway", "tirage", "calendar", "calendrier",
        "halloween", "noel", "noël", "paques", "pâques",
    ]),
    (Theme.LORE, [  # Phase 3.2 : lore / worldbuilding
        "lore", "univers", "world", "worldbuilding", "background",
        "histoire", "history", "story", "stories",
        "concept-art", "art", "fanart", "design-doc",
        "personnage", "character", "characters", "factions",
    ]),
    (Theme.MARKETPLACE, [
        "trade", "echange", "achat", "vente", "marketplace", "ventes",
        "vend", "buy", "sell", "deals", "promo", "promotion",
        "shop", "boutique", "soldes",
    ]),
    (Theme.SUPPORT, [
        "ticket", "support", "aide", "help", "faq", "demande",
        "candidature", "report", "signalement", "contact-staff",
        "question", "questions",
    ]),
    (Theme.STAFF, [
        "staff", "mod-only", "admin-only", "modo", "moderateur",
        "salon-staff", "discussion-staff", "moderation", "modération",
        "dev-only", "team",
    ]),
    (Theme.LOGS, [
        "log", "logs", "audit", "mod-log", "ban-log", "join-leave",
        "boost-log", "voice-log", "delete-log", "member-log",
        "message-log", "server-log",
    ]),
    (Theme.GAMING, [
        "jeu", "game", "gaming", "roblox", "minecraft", "valorant",
        "fortnite", "cs", "csgo", "cs2", "lol", "league",
        "wow", "warcraft", "apex", "overwatch", "fifa", "ea-",
        "rocket-league", "rl-", "destiny", "dota",
    ]),
    (Theme.DISCUSSION, [
        "general", "général", "tchat", "chat", "off-topic", "blague", "discord",
        "meme", "memes", "random", "discussion", "papote", "media",
        "images", "photos", "art-share", "musique", "music",
    ]),
]


# Phase 3.2 : keywords supplementaires a matcher dans le TOPIC du salon
TOPIC_RULES: list[tuple[Theme, list[str]]] = [
    (Theme.DEVELOPMENT, [
        "devlog", "playtest", "build", "feedback développement",
        "feedback dev", "alpha", "bêta",
    ]),
    (Theme.STUDIOS, [
        "studios suivis", "actualités des studios", "studio news",
    ]),
    (Theme.LIVES, ["live", "stream", "diffusion"]),
    (Theme.MARKETPLACE, ["trade", "marketplace", "vente"]),
    (Theme.LORE, ["lore", "histoire", "worldbuilding", "univers"]),
]


def classify_channel(channel: discord.abc.GuildChannel) -> Theme:
    """Determine le theme d'un salon par son nom, topic et categorie actuelle.

    Phase 3.2 : utilise plusieurs signaux avec priorite :
    1. Topic du salon (le plus precis si configure)
    2. Nom de la categorie parente (preserve l'organisation existante)
    3. Nom du salon (fallback)
    """
    # Vocal -> Voice (sauf si nom contient un keyword Logs/Staff/etc.)
    if isinstance(channel, discord.VoiceChannel):
        name_lower = channel.name.lower()
        for theme, keywords in CLASSIFICATION_RULES:
            if theme in (Theme.STAFF, Theme.LOGS):
                if any(kw in name_lower for kw in keywords):
                    return theme
        return Theme.VOICE

    if isinstance(channel, discord.ForumChannel):
        name_lower = channel.name.lower()
        if any(kw in name_lower for kw in ("support", "aide", "help", "question")):
            return Theme.SUPPORT
        if any(kw in name_lower for kw in ("trade", "vente", "achat")):
            return Theme.MARKETPLACE
        if any(kw in name_lower for kw in ("devlog", "playtest", "build")):
            return Theme.DEVELOPMENT
        return Theme.DISCUSSION

    # 1. Topic du salon
    topic = (getattr(channel, "topic", None) or "").lower()
    if topic:
        for theme, keywords in TOPIC_RULES:
            if any(kw in topic for kw in keywords):
                return theme

    # 2. Nom de la categorie parente (preserve l'organisation user)
    if channel.category:
        cat_name_lower = channel.category.name.lower()
        for theme, keywords in CLASSIFICATION_RULES:
            if any(kw in cat_name_lower for kw in keywords):
                return theme

    # 3. Nom du salon (fallback)
    name_lower = channel.name.lower()
    for theme, keywords in CLASSIFICATION_RULES:
        if any(kw in name_lower for kw in keywords):
            return theme
    return Theme.OTHER


# =============================================================================
# MODELES
# =============================================================================

@dataclass
class ChannelSnapshot:
    """Snapshot d'un salon pour backup/diff."""

    channel_id: int
    name: str
    type: str
    category_id: Optional[int]
    position: int
    topic: Optional[str] = None
    slowmode: int = 0
    nsfw: bool = False
    user_limit: int = 0  # vocaux
    overwrites: dict = field(default_factory=dict)  # role_id/user_id -> {allow, deny}


@dataclass
class CategorySnapshot:
    """Snapshot d'une categorie."""

    category_id: int
    name: str
    position: int
    overwrites: dict = field(default_factory=dict)


@dataclass
class ServerSnapshot:
    """Snapshot complet du serveur."""

    guild_id: int
    captured_at: float
    categories: list[CategorySnapshot] = field(default_factory=list)
    channels: list[ChannelSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "guild_id": self.guild_id,
            "captured_at": self.captured_at,
            "categories": [asdict(c) for c in self.categories],
            "channels": [asdict(c) for c in self.channels],
        }


@dataclass
class ChannelProposal:
    """Une proposition pour un salon (changements suggérés)."""

    channel_id: int
    current_name: str
    current_category_id: Optional[int]
    suggested_theme: Theme
    suggested_category_name: str   # ex: "📣 Annonces"
    notes: list[str] = field(default_factory=list)


@dataclass
class Blueprint:
    """Plan complet de refonte du serveur."""

    guild_id: int
    generated_at: float
    proposals: list[ChannelProposal] = field(default_factory=list)
    # Categories cibles dans l'ordre theme (icon + name)
    target_categories: list[tuple[Theme, str]] = field(default_factory=list)

    def by_theme(self) -> dict[Theme, list[ChannelProposal]]:
        out: dict[Theme, list[ChannelProposal]] = {t: [] for t in Theme}
        for p in self.proposals:
            out[p.suggested_theme].append(p)
        return out


# =============================================================================
# ANALYZER
# =============================================================================

def analyze_guild(guild: discord.Guild) -> Blueprint:
    """Genere un blueprint pour le serveur, sans toucher a rien."""
    blueprint = Blueprint(guild_id=guild.id, generated_at=time.time())

    # Pour chaque salon, on classifie
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel):
            continue
        theme = classify_channel(ch)
        meta = THEME_META[theme]
        target_cat_name = f"{meta['icon']} {meta['name']}"

        notes = []
        cat_name = ch.category.name if ch.category else None
        if cat_name != target_cat_name:
            notes.append(f"Déplacer de '{cat_name or '— aucune —'}' vers '{target_cat_name}'")
        else:
            notes.append("Déjà dans la bonne catégorie")

        blueprint.proposals.append(ChannelProposal(
            channel_id=ch.id,
            current_name=ch.name,
            current_category_id=ch.category.id if ch.category else None,
            suggested_theme=theme,
            suggested_category_name=target_cat_name,
            notes=notes,
        ))

    # Liste des categories cibles dans l'ordre
    used_themes = sorted(
        {p.suggested_theme for p in blueprint.proposals},
        key=lambda t: THEME_META[t]["order"],
    )
    blueprint.target_categories = [
        (t, f"{THEME_META[t]['icon']} {THEME_META[t]['name']}")
        for t in used_themes
    ]

    return blueprint


# =============================================================================
# BACKUP
# =============================================================================

def _backup_path(guild_id: int, backup_id: str) -> Path:
    return DATA_DIR / f"{guild_id}_{backup_id}.json"


async def backup_state(guild: discord.Guild, label: str = "") -> str:
    """Snapshot complet du serveur. Retourne l'ID du backup."""
    snap = ServerSnapshot(guild_id=guild.id, captured_at=time.time())

    for cat in guild.categories:
        ow = {
            str(target.id): {
                "allow": pair.pair()[0].value,
                "deny": pair.pair()[1].value,
                "type": "role" if isinstance(target, discord.Role) else "member",
            }
            for target, pair in cat.overwrites.items()
        }
        snap.categories.append(CategorySnapshot(
            category_id=cat.id,
            name=cat.name,
            position=cat.position,
            overwrites=ow,
        ))

    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel):
            continue
        ow = {
            str(target.id): {
                "allow": pair.pair()[0].value,
                "deny": pair.pair()[1].value,
                "type": "role" if isinstance(target, discord.Role) else "member",
            }
            for target, pair in ch.overwrites.items()
        }
        snap.channels.append(ChannelSnapshot(
            channel_id=ch.id,
            name=ch.name,
            type=str(ch.type),
            category_id=ch.category.id if ch.category else None,
            position=ch.position,
            topic=getattr(ch, "topic", None),
            slowmode=getattr(ch, "slowmode_delay", 0) or 0,
            nsfw=getattr(ch, "nsfw", False) or False,
            user_limit=getattr(ch, "user_limit", 0) or 0,
            overwrites=ow,
        ))

    backup_id = f"{int(time.time())}"
    if label:
        backup_id += "_" + re.sub(r"[^a-z0-9_-]", "", label.lower())[:30]
    path = _backup_path(guild.id, backup_id)
    payload = {
        "label": label,
        "snapshot": snap.to_dict(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return backup_id


async def list_backups(guild_id: int) -> list[dict]:
    out = []
    for p in DATA_DIR.glob(f"{guild_id}_*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            snap = data.get("snapshot", {})
            out.append({
                "backup_id": p.stem.split("_", 1)[1],
                "label": data.get("label", ""),
                "captured_at": snap.get("captured_at", 0),
                "channel_count": len(snap.get("channels", [])),
                "category_count": len(snap.get("categories", [])),
                "size_kb": p.stat().st_size / 1024,
            })
        except (json.JSONDecodeError, OSError):
            continue
    out.sort(key=lambda x: x["captured_at"], reverse=True)
    return out


async def load_backup(guild_id: int, backup_id: str) -> Optional[dict]:
    path = _backup_path(guild_id, backup_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# =============================================================================
# APPLY BLUEPRINT
# =============================================================================

@dataclass
class ApplyReport:
    """Rapport d'application d'un blueprint."""

    backup_id: Optional[str] = None
    categories_created: list[str] = field(default_factory=list)
    channels_moved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def apply_blueprint(
    guild: discord.Guild,
    blueprint: Blueprint,
    *,
    create_backup: bool = True,
    dry_run: bool = False,
) -> ApplyReport:
    """Applique le blueprint sur le serveur.

    - create_backup : snapshot avant pour rollback
    - dry_run : simule sans rien faire (logging only)
    """
    report = ApplyReport()

    if create_backup and not dry_run:
        try:
            report.backup_id = await backup_state(guild, label="before-architecture-apply")
        except Exception as ex:
            report.errors.append(f"backup_state failed: {ex}")

    # 1. Creer les categories manquantes
    existing_cats = {cat.name: cat for cat in guild.categories}
    target_cats: dict[str, discord.CategoryChannel] = {}

    for theme, cat_name in blueprint.target_categories:
        if cat_name in existing_cats:
            target_cats[cat_name] = existing_cats[cat_name]
            continue
        if dry_run:
            report.categories_created.append(f"[dry-run] créer '{cat_name}'")
            continue
        try:
            new_cat = await guild.create_category(
                name=cat_name,
                reason="Refonte architecture - server_architect.py",
            )
            target_cats[cat_name] = new_cat
            report.categories_created.append(cat_name)
        except discord.Forbidden:
            report.errors.append(f"Permissions manquantes pour créer '{cat_name}'")
        except Exception as ex:
            report.errors.append(f"create_category('{cat_name}') : {ex}")

    # 2. Reorganiser l'ordre des categories selon l'ordre theme
    if not dry_run:
        try:
            ordered_cats = [target_cats[name] for _, name in blueprint.target_categories if name in target_cats]
            for idx, cat in enumerate(ordered_cats):
                try:
                    await cat.edit(position=idx, reason="Refonte architecture")
                except Exception as ex:
                    report.errors.append(f"position '{cat.name}' : {ex}")
                await asyncio.sleep(0.3)
        except Exception as ex:
            report.errors.append(f"reorder categories : {ex}")

    # 3. Deplacer chaque salon dans la categorie cible
    for proposal in blueprint.proposals:
        try:
            ch = guild.get_channel(proposal.channel_id)
            if ch is None:
                continue
            target_cat = target_cats.get(proposal.suggested_category_name)
            if target_cat is None:
                continue
            if ch.category and ch.category.id == target_cat.id:
                continue  # deja dedans
            if dry_run:
                report.channels_moved.append(
                    f"[dry-run] #{ch.name} -> '{proposal.suggested_category_name}'"
                )
                continue
            try:
                await ch.edit(category=target_cat, reason="Refonte architecture")
                report.channels_moved.append(
                    f"#{ch.name} -> '{proposal.suggested_category_name}'"
                )
            except discord.Forbidden:
                report.errors.append(f"Permissions manquantes pour déplacer #{ch.name}")
            except Exception as ex:
                report.errors.append(f"move #{ch.name} : {ex}")
            await asyncio.sleep(0.3)  # rate limit gentil
        except Exception as ex:
            report.errors.append(f"proposal {proposal.channel_id} : {ex}")

    return report


# =============================================================================
# RESTORE
# =============================================================================

async def restore_state(
    guild: discord.Guild, backup_id: str, *, dry_run: bool = False
) -> ApplyReport:
    """Restaure l'etat du serveur depuis un backup.

    Restaure : positions, categories des salons, overwrites principaux.
    Ne supprime PAS les nouvelles categories/salons crees apres le backup
    (pour eviter perte de donnees).
    """
    report = ApplyReport(backup_id=backup_id)
    data = await load_backup(guild.id, backup_id)
    if not data:
        report.errors.append(f"Backup '{backup_id}' introuvable")
        return report

    snap = data.get("snapshot", {})

    # Remap categories par ID (les nouvelles categories crees apres backup n'existaient pas)
    cat_id_to_obj = {cat.id: cat for cat in guild.categories}

    for ch_snap in snap.get("channels", []):
        try:
            ch = guild.get_channel(ch_snap["channel_id"])
            if ch is None:
                continue  # supprime entre temps
            target_cat = cat_id_to_obj.get(ch_snap["category_id"])

            changes = {}
            if target_cat is not None and (not ch.category or ch.category.id != target_cat.id):
                changes["category"] = target_cat
            # On garde position relative
            if ch.position != ch_snap["position"]:
                changes["position"] = ch_snap["position"]
            if changes and not dry_run:
                try:
                    await ch.edit(**changes, reason=f"Restore backup {backup_id}")
                    report.channels_moved.append(f"#{ch.name} restauré")
                except Exception as ex:
                    report.errors.append(f"restore #{ch.name} : {ex}")
                await asyncio.sleep(0.3)
            elif changes:
                report.channels_moved.append(f"[dry-run] #{ch.name}")
        except Exception as ex:
            report.errors.append(f"restore {ch_snap.get('channel_id')} : {ex}")

    return report


# =============================================================================
# SUGGESTIONS DE ROLES DE MENTION (Phase 3.2)
# =============================================================================
# Apres avoir analyse l'architecture, on propose des roles de mention adaptes
# au type de serveur detecte. L'owner peut creer un roles_panel pour que les
# membres s'abonnent eux-memes a ces mentions (evite les @everyone abusifs).

@dataclass
class SuggestedRole:
    """Un role de mention suggere pour le serveur."""

    label: str                # ex: "🎬 Stream Alerts"
    description: str          # ex: "Notifie quand quelqu'un est en live"
    emoji: str = ""           # emoji optionnel
    color: int = 0x5865F2     # couleur de role suggeree


# Suggestions par theme detecte sur le serveur
ROLE_SUGGESTIONS_BY_THEME: dict[Theme, list[SuggestedRole]] = {
    Theme.LIVES: [
        SuggestedRole("Stream Alerts", "Mentionne quand un créateur est en live", "🎬", 0x9146FF),
        SuggestedRole("Nouvelles Vidéos", "Mentionne pour les nouvelles vidéos YouTube", "🔴", 0xFF0000),
    ],
    Theme.DEVELOPMENT: [
        SuggestedRole("Devlog", "Mises à jour développement du jeu", "🛠️", 0x3498DB),
        SuggestedRole("Playtest", "Sessions de test ouvertes aux membres", "🎮", 0xE67E22),
        SuggestedRole("Builds", "Nouvelles versions à tester", "📦", 0x95A5A6),
    ],
    Theme.STUDIOS: [
        SuggestedRole("Studios News", "Actus des studios suivis", "🏢", 0x2ECC71),
    ],
    Theme.MARKETPLACE: [
        SuggestedRole("Trade", "Annonces de trades et ventes", "💰", 0xF1C40F),
        SuggestedRole("Deals Gaming", "Promotions Steam/Epic/etc.", "🎯", 0xFF6B35),
    ],
    Theme.EVENTS: [
        SuggestedRole("Évènements", "Notifie pour les events serveur", "🎉", 0xEB459E),
        SuggestedRole("Giveaways", "Mentionne pour les tirages au sort", "🎁", 0xE74C3C),
    ],
    Theme.LORE: [
        SuggestedRole("Lore Updates", "Mises à jour de l'univers", "📖", 0x9B59B6),
    ],
    Theme.ANNOUNCEMENTS: [
        SuggestedRole("Annonces Importantes", "Annonces officielles du serveur", "📣", 0xE67E22),
    ],
    Theme.SOCIAL: [
        SuggestedRole("Posts Réseaux", "Notifie pour les nouveaux posts X/Twitter/etc.", "📡", 0x1DA1F2),
    ],
}


def suggest_roles_for_guild(blueprint: Blueprint) -> list[SuggestedRole]:
    """Genere une liste de roles de mention adaptes au serveur detecte.

    Base sur les themes presents dans le blueprint (i.e. les categories qu'on
    va creer). On suggere des roles UNIQUEMENT pour les themes qui ont des
    salons.
    """
    out: list[SuggestedRole] = []
    by_theme = blueprint.by_theme()
    for theme in Theme:
        if not by_theme.get(theme):
            continue
        suggestions = ROLE_SUGGESTIONS_BY_THEME.get(theme, [])
        for s in suggestions:
            out.append(s)
    return out


# =============================================================================
# TEMPLATES SERVEUR (Phase 3.2)
# =============================================================================

class ServerTemplate(str, Enum):
    """Template de configuration adapte au type de serveur."""
    GAMEDEV = "gamedev"        # Studio / dev de jeu
    STREAMER = "streamer"      # Communaute de createur
    GAMING = "gaming"          # Communaute jeu video
    COMMUNITY = "community"    # Communaute generique


TEMPLATE_META: dict[ServerTemplate, dict] = {
    ServerTemplate.GAMEDEV: {
        "name": "Game Development",
        "desc": "Pour un studio ou un projet de jeu en cours",
        "themes": [Theme.WELCOME, Theme.ANNOUNCEMENTS, Theme.DEVELOPMENT, Theme.STUDIOS,
                   Theme.LORE, Theme.EVENTS, Theme.LIVES, Theme.SOCIAL,
                   Theme.DISCUSSION, Theme.VOICE, Theme.SUPPORT, Theme.STAFF, Theme.LOGS],
    },
    ServerTemplate.STREAMER: {
        "name": "Communauté de Créateur",
        "desc": "Pour un streamer / créateur de contenu",
        "themes": [Theme.WELCOME, Theme.ANNOUNCEMENTS, Theme.LIVES, Theme.SOCIAL,
                   Theme.EVENTS, Theme.DISCUSSION, Theme.GAMING, Theme.VOICE,
                   Theme.SUPPORT, Theme.STAFF, Theme.LOGS],
    },
    ServerTemplate.GAMING: {
        "name": "Communauté Gaming",
        "desc": "Pour une communauté autour de jeux vidéo",
        "themes": [Theme.WELCOME, Theme.ANNOUNCEMENTS, Theme.GAMING, Theme.MARKETPLACE,
                   Theme.LIVES, Theme.EVENTS, Theme.DISCUSSION, Theme.VOICE,
                   Theme.SUPPORT, Theme.STAFF, Theme.LOGS],
    },
    ServerTemplate.COMMUNITY: {
        "name": "Communauté Généraliste",
        "desc": "Communauté large, multi-sujets",
        "themes": [Theme.WELCOME, Theme.ANNOUNCEMENTS, Theme.DISCUSSION,
                   Theme.EVENTS, Theme.SOCIAL, Theme.VOICE,
                   Theme.SUPPORT, Theme.STAFF, Theme.LOGS],
    },
}


def detect_template(blueprint: Blueprint) -> ServerTemplate:
    """Devine le type de serveur en fonction des themes presents."""
    by_theme = blueprint.by_theme()
    has_dev = bool(by_theme.get(Theme.DEVELOPMENT)) or bool(by_theme.get(Theme.LORE))
    has_streams = bool(by_theme.get(Theme.LIVES))
    has_gaming = bool(by_theme.get(Theme.GAMING))

    if has_dev:
        return ServerTemplate.GAMEDEV
    if has_streams and not has_gaming:
        return ServerTemplate.STREAMER
    if has_gaming or has_streams:
        return ServerTemplate.GAMING
    return ServerTemplate.COMMUNITY


__all__ = [
    "Theme",
    "THEME_META",
    "CLASSIFICATION_RULES",
    "TOPIC_RULES",
    "classify_channel",
    "ChannelSnapshot",
    "CategorySnapshot",
    "ServerSnapshot",
    "ChannelProposal",
    "Blueprint",
    "ApplyReport",
    "analyze_guild",
    "backup_state",
    "list_backups",
    "load_backup",
    "apply_blueprint",
    "restore_state",
    "SuggestedRole",
    "ROLE_SUGGESTIONS_BY_THEME",
    "suggest_roles_for_guild",
    "ServerTemplate",
    "TEMPLATE_META",
    "detect_template",
]
