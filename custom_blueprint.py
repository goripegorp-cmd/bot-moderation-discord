"""
custom_blueprint.py - Blueprint custom pour reconstruire un serveur from scratch
                      (Phase 3.4).

Probleme resolu : "wipe" detruit tout mais ne reconstruit rien. L'owner veut
configurer interactivement le serveur ideal, valider, puis le bot detruit
l'ancien et reconstruit suivant le blueprint valide.

Workflow :
    1. Owner pick un preset (GameDev/Streamer/Gaming/Community) ou part vierge
    2. Owner customise via /architecture builder (V2 panel) :
       - Catégories : nom, ordre
       - Salons : nom, type (text/voice/forum), topic, slowmode
       - Rôles : nom, couleur, permissions, mentionable
       - Permissions par salon : qui voit, qui parle
    3. Owner clique "Sauvegarder" → blueprint JSON stocke
    4. Owner clique "Apply" :
       - Snapshot avant (rollback possible)
       - WIPE (sauf preserve_ids)
       - CREATE catégories, channels, roles
       - APPLY permissions

API :
    CustomChannel / CustomCategory / CustomRole / CustomBlueprint dataclasses
    load_blueprint(guild_id) / save_blueprint(guild_id, bp)
    apply_blueprint(guild, bp, wipe_first=True) -> ApplyReport
    PRESETS = {gamedev, streamer, gaming, community}
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import discord

from paths import module_dir


DATA_DIR = module_dir("custom_blueprints")


# =============================================================================
# MODELES
# =============================================================================

class ChannelType(str, Enum):
    TEXT = "text"
    VOICE = "voice"
    FORUM = "forum"
    ANNOUNCEMENT = "announcement"
    STAGE = "stage"


@dataclass
class CustomChannel:
    """Salon a creer."""
    name: str
    ctype: str = "text"            # ChannelType valeur
    topic: str = ""
    slowmode: int = 0              # secondes
    nsfw: bool = False
    user_limit: int = 0            # vocaux uniquement
    # Permissions : role_name (str) -> {allow: list[str], deny: list[str]}
    # noms des perms : "view_channel", "send_messages", "read_message_history",
    # "manage_messages", "manage_channels", "connect", "speak", "mention_everyone"
    role_perms: dict[str, dict[str, list[str]]] = field(default_factory=dict)


@dataclass
class CustomCategory:
    """Categorie a creer + ses salons."""
    name: str
    channels: list[CustomChannel] = field(default_factory=list)
    role_perms: dict[str, dict[str, list[str]]] = field(default_factory=dict)


@dataclass
class CustomRole:
    """Role a creer."""
    name: str
    color: int = 0x99AAB5
    mentionable: bool = True
    hoist: bool = False          # affiche separe dans la liste
    # Permissions : list de noms (administrateur deconseille)
    permissions: list[str] = field(default_factory=list)


@dataclass
class CustomBlueprint:
    """Blueprint complet."""
    name: str = "Custom"
    description: str = ""
    categories: list[CustomCategory] = field(default_factory=list)
    roles: list[CustomRole] = field(default_factory=list)
    # Roles de mention pour le panneau self-service (Phase 3.1)
    mention_roles: list[str] = field(default_factory=list)  # noms de roles

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CustomBlueprint":
        cats = [
            CustomCategory(
                name=c["name"],
                channels=[CustomChannel(**ch) for ch in c.get("channels", [])],
                role_perms=c.get("role_perms", {}),
            )
            for c in data.get("categories", [])
        ]
        roles = [CustomRole(**r) for r in data.get("roles", [])]
        return cls(
            name=data.get("name", "Custom"),
            description=data.get("description", ""),
            categories=cats,
            roles=roles,
            mention_roles=data.get("mention_roles", []),
        )


# =============================================================================
# PRESETS PRO
# =============================================================================
# 4 templates clé en main. Chacun definit categories + channels + roles.
# Perms par defaut sensées : everyone voit, le @Staff modere.

def _ch(name, ctype="text", topic="", slowmode=0, role_perms=None):
    return CustomChannel(
        name=name, ctype=ctype, topic=topic, slowmode=slowmode,
        role_perms=role_perms or {},
    )


def _cat(name, channels):
    return CustomCategory(name=name, channels=channels)


def _role(name, color=0x99AAB5, mentionable=True, perms=None):
    return CustomRole(name=name, color=color, mentionable=mentionable,
                       permissions=perms or [])


PRESET_GAMEDEV = CustomBlueprint(
    name="Game Development Studio",
    description="Studio / projet de jeu en developpement. Devlog, playtest, "
                "studios suivis, communaute.",
    categories=[
        _cat("📌 Bienvenue", [
            _ch("règles", topic="Règlement du serveur — à lire avant tout."),
            _ch("choix-rôles", topic="Réagis pour recevoir les notifications qui t'intéressent."),
            _ch("présentations", topic="Présente-toi à la communauté !"),
        ]),
        _cat("📣 Annonces", [
            _ch("annonces", ctype="announcement", topic="Annonces officielles du studio."),
            _ch("communiqués", topic="Communiqués détaillés, patch notes."),
        ]),
        _cat("🛠️ Développement", [
            _ch("devlog", topic="Mises à jour du développement, screenshots, GIFs."),
            _ch("builds", topic="Nouveaux builds à télécharger pour testing."),
            _ch("playtest", topic="Sessions de playtest organisées."),
            _ch("feedback", topic="Retours détaillés sur les builds testés."),
            _ch("bug-report", topic="Signaler un bug rencontré (format : version + repro)."),
            _ch("design-doc", topic="Discussions sur le design du jeu."),
        ]),
        _cat("📖 Lore & Univers", [
            _ch("lore", topic="L'univers du jeu — histoire, factions, lieux."),
            _ch("concept-art", topic="Concept arts officiels du jeu."),
            _ch("personnages", topic="Personnages, factions, classes."),
            _ch("fanart", topic="Vos fanarts de l'univers du jeu !"),
        ]),
        _cat("🏢 Studios suivis", [
            _ch("studios-news", topic="Actualités des studios qu'on suit."),
            _ch("inspiration", topic="Jeux et créations qui inspirent."),
        ]),
        _cat("🎬 Lives & Vidéos", [
            _ch("twitch-alerts", topic="Notifications de lives Twitch."),
            _ch("youtube-alerts", topic="Nouvelles vidéos YouTube."),
            _ch("tiktok", topic="TikToks officiels et inspirations."),
            _ch("vods", topic="Replays des sessions live."),
        ]),
        _cat("📡 Réseaux sociaux", [
            _ch("twitter", topic="Posts Twitter officiels."),
            _ch("instagram", topic="Posts Instagram officiels."),
        ]),
        _cat("🎉 Évènements", [
            _ch("évènements", topic="Calendrier et annonces d'events."),
            _ch("giveaways", topic="Concours et tirages au sort."),
        ]),
        _cat("💬 Discussion", [
            _ch("général", topic="Discussion générale."),
            _ch("off-topic", topic="Hors-sujet — papote libre."),
            _ch("mèmes", topic="Mèmes uniquement, sois drôle."),
            _ch("musique", topic="Partage ce que tu écoutes."),
        ]),
        _cat("🎤 Vocaux", [
            _ch("Lobby", ctype="voice"),
            _ch("Discussion", ctype="voice"),
            _ch("Playtest", ctype="voice"),
            _ch("Music", ctype="voice"),
        ]),
        _cat("🎫 Support", [
            _ch("ouvrir-ticket", topic="Ouvre un ticket pour contacter le staff."),
            _ch("faq", topic="Réponses aux questions fréquentes."),
        ]),
        _cat("🔧 Staff", [
            _ch("staff-général",
                role_perms={"@everyone": {"deny": ["view_channel"]}}),
            _ch("staff-dev",
                role_perms={"@everyone": {"deny": ["view_channel"]}}),
            _ch("Staff Voice", ctype="voice",
                role_perms={"@everyone": {"deny": ["view_channel"]}}),
        ]),
        _cat("📋 Logs", [
            _ch("mod-logs", role_perms={"@everyone": {"deny": ["view_channel"]}}),
            _ch("join-leave", role_perms={"@everyone": {"deny": ["view_channel"]}}),
            _ch("audit", role_perms={"@everyone": {"deny": ["view_channel"]}}),
        ]),
    ],
    roles=[
        _role("Fondateur", color=0xFF6B35, hoist=True, perms=["administrator"]),
        _role("Dev Team", color=0x3498DB, hoist=True,
              perms=["manage_messages", "manage_channels", "manage_roles", "kick_members"]),
        _role("Staff", color=0x9B59B6, hoist=True,
              perms=["manage_messages", "kick_members", "manage_nicknames", "moderate_members"]),
        _role("Helper", color=0x2ECC71, mentionable=True,
              perms=["manage_messages"]),
        _role("Tester", color=0xF1C40F, mentionable=True),
        _role("VIP", color=0xEB459E, mentionable=True),
    ],
    mention_roles=[
        "Devlog Alerts",
        "Playtest Alerts",
        "Stream Alerts",
        "Studios News",
        "Évènements",
        "Giveaways",
        "Lore Updates",
    ],
)


PRESET_STREAMER = CustomBlueprint(
    name="Communauté de Créateur",
    description="Communauté autour d'un streamer / créateur de contenu.",
    categories=[
        _cat("📌 Bienvenue", [
            _ch("règles"),
            _ch("choix-rôles"),
            _ch("présentations"),
        ]),
        _cat("📣 Annonces", [
            _ch("annonces", ctype="announcement"),
            _ch("planning-stream", topic="Calendrier des prochains lives."),
        ]),
        _cat("🎬 Lives & Vidéos", [
            _ch("twitch-alerts"),
            _ch("youtube-alerts"),
            _ch("clips", topic="Tes meilleurs moments du stream."),
            _ch("vods"),
        ]),
        _cat("📡 Réseaux sociaux", [
            _ch("twitter"),
            _ch("tiktok"),
            _ch("instagram"),
        ]),
        _cat("🎉 Évènements", [
            _ch("évènements"),
            _ch("giveaways"),
            _ch("tournois"),
        ]),
        _cat("💬 Discussion", [
            _ch("général"),
            _ch("off-topic"),
            _ch("mèmes"),
            _ch("musique"),
        ]),
        _cat("🎮 Gaming", [
            _ch("lfg", topic="Look-For-Group : trouve des partenaires."),
            _ch("discussion-jeux"),
        ]),
        _cat("🎤 Vocaux", [
            _ch("Lobby", ctype="voice"),
            _ch("Gaming 1", ctype="voice"),
            _ch("Gaming 2", ctype="voice"),
            _ch("Music", ctype="voice"),
        ]),
        _cat("🎫 Support", [
            _ch("ouvrir-ticket"),
            _ch("faq"),
        ]),
        _cat("🔧 Staff", [
            _ch("staff-général", role_perms={"@everyone": {"deny": ["view_channel"]}}),
            _ch("Staff Voice", ctype="voice",
                role_perms={"@everyone": {"deny": ["view_channel"]}}),
        ]),
        _cat("📋 Logs", [
            _ch("mod-logs", role_perms={"@everyone": {"deny": ["view_channel"]}}),
            _ch("join-leave", role_perms={"@everyone": {"deny": ["view_channel"]}}),
        ]),
    ],
    roles=[
        _role("Streamer", color=0x9146FF, hoist=True, perms=["administrator"]),
        _role("Modérateur", color=0x9B59B6, hoist=True,
              perms=["manage_messages", "kick_members", "moderate_members"]),
        _role("Sub Twitch", color=0xEB459E, hoist=True),
        _role("VIP", color=0xF1C40F, hoist=True),
        _role("Membre actif", color=0x2ECC71),
    ],
    mention_roles=["Stream Alerts", "Nouvelles Vidéos", "Évènements", "Giveaways"],
)


PRESET_GAMING = CustomBlueprint(
    name="Communauté Gaming",
    description="Communauté autour de jeux vidéo, LFG, trade.",
    categories=[
        _cat("📌 Bienvenue", [
            _ch("règles"),
            _ch("choix-rôles"),
            _ch("présentations"),
        ]),
        _cat("📣 Annonces", [
            _ch("annonces", ctype="announcement"),
            _ch("patch-notes"),
        ]),
        _cat("🎮 Gaming", [
            _ch("général-gaming"),
            _ch("lfg", topic="Look-For-Group : trouve des partenaires."),
            _ch("astuces", topic="Tips & tricks."),
            _ch("captures", topic="Screenshots et clips."),
        ]),
        _cat("🛒 Marketplace", [
            _ch("trade", topic="Échanges entre membres."),
            _ch("achat-vente"),
            _ch("deals-promos", topic="Bons plans Steam/Epic/etc."),
        ]),
        _cat("🎬 Lives & Vidéos", [
            _ch("twitch-alerts"),
            _ch("youtube-alerts"),
        ]),
        _cat("🎉 Évènements", [
            _ch("tournois"),
            _ch("giveaways"),
            _ch("évènements"),
        ]),
        _cat("💬 Discussion", [
            _ch("général"),
            _ch("off-topic"),
            _ch("mèmes"),
        ]),
        _cat("🎤 Vocaux", [
            _ch("Lobby", ctype="voice"),
            _ch("Gaming 1", ctype="voice"),
            _ch("Gaming 2", ctype="voice"),
            _ch("Gaming 3", ctype="voice"),
            _ch("AFK", ctype="voice"),
        ]),
        _cat("🎫 Support", [
            _ch("ouvrir-ticket"),
            _ch("faq"),
        ]),
        _cat("🔧 Staff", [
            _ch("staff-général", role_perms={"@everyone": {"deny": ["view_channel"]}}),
        ]),
        _cat("📋 Logs", [
            _ch("mod-logs", role_perms={"@everyone": {"deny": ["view_channel"]}}),
            _ch("join-leave", role_perms={"@everyone": {"deny": ["view_channel"]}}),
        ]),
    ],
    roles=[
        _role("Owner", color=0xFF6B35, hoist=True, perms=["administrator"]),
        _role("Admin", color=0xE74C3C, hoist=True, perms=["administrator"]),
        _role("Modérateur", color=0x9B59B6, hoist=True,
              perms=["manage_messages", "kick_members", "moderate_members"]),
        _role("Trade-Verified", color=0xF1C40F),
        _role("Booster", color=0xEB459E, hoist=True),
    ],
    mention_roles=["LFG", "Trade", "Tournois", "Deals Gaming", "Évènements"],
)


PRESET_COMMUNITY = CustomBlueprint(
    name="Communauté Généraliste",
    description="Communauté multi-sujets sans focus particulier.",
    categories=[
        _cat("📌 Bienvenue", [
            _ch("règles"),
            _ch("choix-rôles"),
            _ch("présentations"),
        ]),
        _cat("📣 Annonces", [
            _ch("annonces", ctype="announcement"),
        ]),
        _cat("💬 Discussion", [
            _ch("général"),
            _ch("off-topic"),
            _ch("mèmes"),
            _ch("musique"),
            _ch("photos"),
        ]),
        _cat("🎉 Évènements", [
            _ch("évènements"),
            _ch("giveaways"),
        ]),
        _cat("📡 Réseaux sociaux", [
            _ch("twitter"),
            _ch("instagram"),
        ]),
        _cat("🎤 Vocaux", [
            _ch("Lobby", ctype="voice"),
            _ch("Discussion 1", ctype="voice"),
            _ch("Discussion 2", ctype="voice"),
            _ch("Music", ctype="voice"),
        ]),
        _cat("🎫 Support", [
            _ch("ouvrir-ticket"),
            _ch("faq"),
        ]),
        _cat("🔧 Staff", [
            _ch("staff-général", role_perms={"@everyone": {"deny": ["view_channel"]}}),
        ]),
        _cat("📋 Logs", [
            _ch("mod-logs", role_perms={"@everyone": {"deny": ["view_channel"]}}),
            _ch("join-leave", role_perms={"@everyone": {"deny": ["view_channel"]}}),
        ]),
    ],
    roles=[
        _role("Owner", color=0xFF6B35, hoist=True, perms=["administrator"]),
        _role("Modérateur", color=0x9B59B6, hoist=True,
              perms=["manage_messages", "kick_members", "moderate_members"]),
        _role("Membre actif", color=0x2ECC71),
    ],
    mention_roles=["Évènements", "Giveaways", "Annonces Importantes"],
)


PRESETS: dict[str, CustomBlueprint] = {
    "gamedev": PRESET_GAMEDEV,
    "streamer": PRESET_STREAMER,
    "gaming": PRESET_GAMING,
    "community": PRESET_COMMUNITY,
}


# =============================================================================
# STORAGE
# =============================================================================

def _bp_path(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}.json"


async def load_blueprint(guild_id: int) -> Optional[CustomBlueprint]:
    p = _bp_path(guild_id)
    if not p.exists():
        return None
    try:
        return CustomBlueprint.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


async def save_blueprint(guild_id: int, bp: CustomBlueprint) -> None:
    _bp_path(guild_id).write_text(
        json.dumps(bp.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )


# =============================================================================
# MUTATIONS (utilises par le V2 builder)
# =============================================================================

async def get_or_create_blueprint(guild_id: int) -> CustomBlueprint:
    """Charge le blueprint du serveur, ou en cree un nouveau vide."""
    bp = await load_blueprint(guild_id)
    if bp is None:
        bp = CustomBlueprint(name="Mon Serveur", description="Custom build")
    return bp


def mutate_load_preset(bp: CustomBlueprint, preset_key: str) -> bool:
    """Remplace le blueprint par un preset (in-place)."""
    preset = PRESETS.get(preset_key)
    if not preset:
        return False
    bp.name = preset.name
    bp.description = preset.description
    bp.categories = [
        CustomCategory(
            name=c.name,
            channels=[CustomChannel(**asdict(ch)) for ch in c.channels],
            role_perms=dict(c.role_perms),
        )
        for c in preset.categories
    ]
    bp.roles = [CustomRole(**asdict(r)) for r in preset.roles]
    bp.mention_roles = list(preset.mention_roles)
    return True


def mutate_add_category(bp: CustomBlueprint, name: str) -> bool:
    """Ajoute une categorie vide. Retourne False si nom deja pris."""
    if any(c.name == name for c in bp.categories):
        return False
    bp.categories.append(CustomCategory(name=name))
    return True


def mutate_rename_category(bp: CustomBlueprint, old: str, new: str) -> bool:
    for c in bp.categories:
        if c.name == old:
            c.name = new
            return True
    return False


def mutate_delete_category(bp: CustomBlueprint, name: str) -> bool:
    n = len(bp.categories)
    bp.categories = [c for c in bp.categories if c.name != name]
    return len(bp.categories) < n


def mutate_move_category(bp: CustomBlueprint, name: str, direction: int) -> bool:
    """Deplace une categorie haut (-1) ou bas (+1)."""
    for i, c in enumerate(bp.categories):
        if c.name == name:
            ni = i + direction
            if 0 <= ni < len(bp.categories):
                bp.categories[i], bp.categories[ni] = bp.categories[ni], bp.categories[i]
                return True
            return False
    return False


def mutate_add_channel(
    bp: CustomBlueprint, cat_name: str, ch_name: str,
    ctype: str = "text", topic: str = "", slowmode: int = 0,
) -> bool:
    for c in bp.categories:
        if c.name == cat_name:
            if any(ch.name == ch_name for ch in c.channels):
                return False
            c.channels.append(CustomChannel(
                name=ch_name, ctype=ctype, topic=topic, slowmode=slowmode,
            ))
            return True
    return False


def mutate_rename_channel(
    bp: CustomBlueprint, cat_name: str, old: str, new: str,
) -> bool:
    for c in bp.categories:
        if c.name == cat_name:
            for ch in c.channels:
                if ch.name == old:
                    ch.name = new
                    return True
    return False


def mutate_delete_channel(
    bp: CustomBlueprint, cat_name: str, ch_name: str,
) -> bool:
    for c in bp.categories:
        if c.name == cat_name:
            n = len(c.channels)
            c.channels = [ch for ch in c.channels if ch.name != ch_name]
            return len(c.channels) < n
    return False


def mutate_add_role(
    bp: CustomBlueprint, name: str, color: int = 0x99AAB5,
    mentionable: bool = True, hoist: bool = False,
    permissions: Optional[list[str]] = None,
) -> bool:
    if any(r.name == name for r in bp.roles):
        return False
    bp.roles.append(CustomRole(
        name=name, color=color, mentionable=mentionable, hoist=hoist,
        permissions=permissions or [],
    ))
    return True


def mutate_rename_role(bp: CustomBlueprint, old: str, new: str) -> bool:
    for r in bp.roles:
        if r.name == old:
            r.name = new
            return True
    return False


def mutate_delete_role(bp: CustomBlueprint, name: str) -> bool:
    n = len(bp.roles)
    bp.roles = [r for r in bp.roles if r.name != name]
    return len(bp.roles) < n


def mutate_set_role_color(bp: CustomBlueprint, name: str, color: int) -> bool:
    for r in bp.roles:
        if r.name == name:
            r.color = color
            return True
    return False


def mutate_clear(bp: CustomBlueprint) -> None:
    """Vide le blueprint (pour recommencer)."""
    bp.categories = []
    bp.roles = []
    bp.mention_roles = []
    bp.name = "Vide"
    bp.description = ""


# =============================================================================
# APPLY
# =============================================================================

@dataclass
class BuildReport:
    """Rapport d'une construction."""
    backup_id: Optional[str] = None
    categories_created: list[str] = field(default_factory=list)
    channels_created: list[str] = field(default_factory=list)
    roles_created: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# Permissions Discord supportees (nom Python -> attribut Permissions)
_PERM_NAMES = {
    "view_channel", "send_messages", "read_message_history",
    "manage_messages", "manage_channels", "manage_roles", "manage_nicknames",
    "manage_guild", "kick_members", "ban_members", "moderate_members",
    "connect", "speak", "stream", "use_voice_activation",
    "mention_everyone", "embed_links", "attach_files", "add_reactions",
    "use_application_commands", "create_public_threads", "create_private_threads",
    "send_messages_in_threads", "administrator",
}


def _permissions_from_names(names: list[str]) -> discord.Permissions:
    """Construit un Permissions object depuis une liste de noms."""
    p = discord.Permissions.none()
    for n in names:
        if n in _PERM_NAMES and hasattr(p, n):
            try:
                setattr(p, n, True)
            except Exception:
                pass
    return p


def _overwrite_from_perms(
    role_perms: dict[str, list[str]],
) -> discord.PermissionOverwrite:
    """Construit un PermissionOverwrite (allow/deny) depuis allow + deny."""
    ow = discord.PermissionOverwrite()
    for perm in role_perms.get("allow", []):
        if perm in _PERM_NAMES and hasattr(ow, perm):
            setattr(ow, perm, True)
    for perm in role_perms.get("deny", []):
        if perm in _PERM_NAMES and hasattr(ow, perm):
            setattr(ow, perm, False)
    return ow


async def apply_blueprint(
    guild: discord.Guild, bp: CustomBlueprint, *,
    wipe_first: bool = True,
    create_roles: bool = True,
    dry_run: bool = False,
) -> BuildReport:
    """Construit le serveur depuis le blueprint.

    - wipe_first : supprime tout l'existant (apres backup auto)
    - create_roles : cree les roles du blueprint
    - dry_run : simule sans rien faire

    Returns BuildReport.
    """
    from server_architect import backup_state, wipe_guild

    report = BuildReport()

    # 1. Backup avant (toujours)
    if not dry_run:
        try:
            report.backup_id = await backup_state(guild, label="before-build")
        except Exception as ex:
            report.errors.append(f"backup avant build : {ex}")
            return report

    # 2. Wipe si demande
    if wipe_first and not dry_run:
        try:
            wipe_report = await wipe_guild(guild, dry_run=False)
            report.errors.extend([f"[wipe] {e}" for e in wipe_report.errors])
        except Exception as ex:
            report.errors.append(f"wipe : {ex}")

    # 3. Creer les roles
    role_name_to_obj: dict[str, discord.Role] = {}
    if create_roles:
        for r in bp.roles:
            existing = discord.utils.get(guild.roles, name=r.name)
            if existing:
                role_name_to_obj[r.name] = existing
                continue
            if dry_run:
                report.roles_created.append(f"[dry-run] {r.name}")
                continue
            try:
                perms = _permissions_from_names(r.permissions)
                new_role = await guild.create_role(
                    name=r.name,
                    color=discord.Color(r.color),
                    mentionable=r.mentionable,
                    hoist=r.hoist,
                    permissions=perms,
                    reason="custom_blueprint apply",
                )
                role_name_to_obj[r.name] = new_role
                report.roles_created.append(r.name)
                await asyncio.sleep(0.3)
            except discord.Forbidden:
                report.errors.append(f"role '{r.name}' : permissions insuffisantes")
            except Exception as ex:
                report.errors.append(f"role '{r.name}' : {ex}")

    # 4. Aussi mapper @everyone
    role_name_to_obj["@everyone"] = guild.default_role

    # 5. Creer categories + channels dans l'ordre
    for cat_idx, cat in enumerate(bp.categories):
        if dry_run:
            report.categories_created.append(f"[dry-run] {cat.name}")
            continue
        try:
            # Permissions overrides pour la categorie
            overwrites = {}
            for role_name, perms in cat.role_perms.items():
                role_obj = role_name_to_obj.get(role_name)
                if role_obj:
                    overwrites[role_obj] = _overwrite_from_perms(perms)

            new_cat = await guild.create_category(
                name=cat.name,
                overwrites=overwrites,
                reason="custom_blueprint apply",
                position=cat_idx,
            )
            report.categories_created.append(cat.name)
            await asyncio.sleep(0.3)

            # Creer les salons dans cette categorie
            for ch in cat.channels:
                try:
                    ch_overwrites = {}
                    for role_name, perms in ch.role_perms.items():
                        role_obj = role_name_to_obj.get(role_name)
                        if role_obj:
                            ch_overwrites[role_obj] = _overwrite_from_perms(perms)

                    ctype = ch.ctype.lower()
                    if ctype == "voice":
                        await guild.create_voice_channel(
                            name=ch.name, category=new_cat,
                            overwrites=ch_overwrites,
                            user_limit=ch.user_limit or 0,
                            reason="custom_blueprint apply",
                        )
                    elif ctype == "forum":
                        try:
                            await guild.create_forum(
                                name=ch.name, category=new_cat,
                                overwrites=ch_overwrites,
                                topic=ch.topic[:1024] if ch.topic else None,
                                reason="custom_blueprint apply",
                            )
                        except AttributeError:
                            # Fallback si create_forum pas dispo
                            await guild.create_text_channel(
                                name=ch.name, category=new_cat,
                                overwrites=ch_overwrites,
                                topic=ch.topic[:1024] if ch.topic else None,
                                reason="custom_blueprint apply",
                            )
                    elif ctype == "announcement":
                        try:
                            new_chan = await guild.create_text_channel(
                                name=ch.name, category=new_cat,
                                overwrites=ch_overwrites,
                                topic=ch.topic[:1024] if ch.topic else None,
                                news=True,
                                reason="custom_blueprint apply",
                            )
                        except (TypeError, AttributeError):
                            await guild.create_text_channel(
                                name=ch.name, category=new_cat,
                                overwrites=ch_overwrites,
                                topic=ch.topic[:1024] if ch.topic else None,
                                reason="custom_blueprint apply",
                            )
                    else:
                        new_chan = await guild.create_text_channel(
                            name=ch.name, category=new_cat,
                            overwrites=ch_overwrites,
                            topic=ch.topic[:1024] if ch.topic else None,
                            slowmode_delay=ch.slowmode,
                            nsfw=ch.nsfw,
                            reason="custom_blueprint apply",
                        )
                    report.channels_created.append(f"#{ch.name}")
                    await asyncio.sleep(0.3)
                except discord.Forbidden:
                    report.errors.append(f"channel '{ch.name}' : permissions")
                except Exception as ex:
                    report.errors.append(f"channel '{ch.name}' : {ex}")
        except Exception as ex:
            report.errors.append(f"category '{cat.name}' : {ex}")

    return report


__all__ = [
    "ChannelType",
    "CustomChannel",
    "CustomCategory",
    "CustomRole",
    "CustomBlueprint",
    "BuildReport",
    "PRESETS",
    "PRESET_GAMEDEV",
    "PRESET_STREAMER",
    "PRESET_GAMING",
    "PRESET_COMMUNITY",
    "load_blueprint",
    "save_blueprint",
    "apply_blueprint",
]
