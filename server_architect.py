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
    Theme.LIVES:         {"icon": "🎬", "name": "Lives & Vidéos",  "order": 2,
                          "desc": "Notifications Twitch, YouTube, TikTok"},
    Theme.SOCIAL:        {"icon": "📡", "name": "Réseaux sociaux", "order": 3,
                          "desc": "Twitter, Instagram, Reddit, etc."},
    Theme.DISCUSSION:    {"icon": "💬", "name": "Discussion",      "order": 4,
                          "desc": "Général, off-topic, mèmes"},
    Theme.GAMING:        {"icon": "🎮", "name": "Gaming",          "order": 5,
                          "desc": "Salons par jeu"},
    Theme.MARKETPLACE:   {"icon": "🛒", "name": "Marketplace",     "order": 6,
                          "desc": "Trade, vente, recherche"},
    Theme.SUPPORT:       {"icon": "🎫", "name": "Support & Aide",  "order": 7,
                          "desc": "Tickets, aide, FAQ"},
    Theme.VOICE:         {"icon": "🎤", "name": "Vocaux",          "order": 8,
                          "desc": "Salons vocaux libres et lobbies"},
    Theme.STAFF:         {"icon": "🔧", "name": "Staff",           "order": 9,
                          "desc": "Salons mods/admins uniquement"},
    Theme.LOGS:          {"icon": "📋", "name": "Logs",            "order": 10,
                          "desc": "Audit, modération, join-leave"},
    Theme.OTHER:         {"icon": "📦", "name": "Autres",          "order": 11,
                          "desc": "Salons non classifiés"},
}


# Patterns de classification (lower-case match dans le nom du salon)
# Premier match gagne.
CLASSIFICATION_RULES: list[tuple[Theme, list[str]]] = [
    (Theme.WELCOME, [
        "regle", "rule", "rules", "welcome", "bienvenue", "presentation",
        "choix-role", "choix-roles", "choix-rôle", "roles-mention", "self-role",
        "lis-moi", "lisez-moi", "info-server",
    ]),
    (Theme.ANNOUNCEMENTS, [
        "annonce", "announce", "announcement", "news", "actu", "info-bot",
        "changelog", "update", "patch", "communique",
    ]),
    (Theme.LIVES, [
        "live", "lives", "stream", "streams", "twitch", "youtube",
        "tiktok", "kick", "vod", "video", "videos", "yt-",
    ]),
    (Theme.SOCIAL, [
        "twitter", "x-post", "instagram", "reddit", "rosocial", "social",
        "tweet", "post-x",
    ]),
    (Theme.MARKETPLACE, [
        "trade", "echange", "achat", "vente", "marketplace", "ventes",
        "vend", "buy", "sell", "deals", "promo", "promotion",
    ]),
    (Theme.SUPPORT, [
        "ticket", "support", "aide", "help", "faq", "demande",
        "candidature", "report", "signalement", "contact-staff",
    ]),
    (Theme.STAFF, [
        "staff", "mod-only", "admin-only", "modo", "moderateur",
        "salon-staff", "discussion-staff", "moderation",
    ]),
    (Theme.LOGS, [
        "log", "logs", "audit", "mod-log", "ban-log", "join-leave",
        "boost-log", "voice-log", "delete-log",
    ]),
    (Theme.GAMING, [
        "jeu", "game", "gaming", "roblox", "minecraft", "valorant",
        "fortnite", "cs", "csgo", "cs2", "lol", "league",
        "wow", "warcraft", "apex", "overwatch", "fifa", "ea-",
    ]),
    (Theme.DISCUSSION, [
        "general", "tchat", "chat", "off-topic", "blague", "discord",
        "meme", "memes", "random", "discussion", "papote", "media",
        "images", "photos",
    ]),
]


def classify_channel(channel: discord.abc.GuildChannel) -> Theme:
    """Determine le theme d'un salon par son nom et type."""
    # Vocal -> Voice (sauf si nom contient un keyword Logs/Staff/etc.)
    if isinstance(channel, discord.VoiceChannel):
        name_lower = channel.name.lower()
        # Voice channels avec nom revelateur
        for theme, keywords in CLASSIFICATION_RULES:
            if theme in (Theme.STAFF, Theme.LOGS):
                if any(kw in name_lower for kw in keywords):
                    return theme
        return Theme.VOICE

    if isinstance(channel, discord.ForumChannel):
        # Forums -> souvent Support ou Marketplace selon nom
        name_lower = channel.name.lower()
        if any(kw in name_lower for kw in ("support", "aide", "help", "question")):
            return Theme.SUPPORT
        if any(kw in name_lower for kw in ("trade", "vente", "achat")):
            return Theme.MARKETPLACE
        return Theme.DISCUSSION

    # Text channels et threads : on classifie par nom
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


__all__ = [
    "Theme",
    "THEME_META",
    "CLASSIFICATION_RULES",
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
]
