"""
community_features.py - Features pour faire vivre la communaute (Phase 1.4).

Toutes les features sont conformes a `engagement.py` :
    - elles respectent le budget d'attention (max N pings/jour, etc.)
    - elles preferent le canal le moins intrusif possible
    - elles sont opt-in par l'owner (toutes off par defaut sauf welcome)

Features fournies :
    1. DailyConversation       - une question/jour dans un salon
    2. MemberSpotlight         - mise en avant hebdo d'un membre actif
    3. WelcomeQuickstart       - message d'accueil personnalise + liens utiles
    4. ActivityRecognition     - le bot reagit 🔥 sur les threads dynamiques
    5. InactivityNudge         - relance subtile sur un salon silencieux
    6. ThemeDays               - jour theme (#music-monday, #tech-thursday)
    7. WeeklyDigest            - resume hebdo des stats (membres, messages, top contributeurs)

Chaque feature est une fonction pure : elle prend un contexte (guild_id,
config, donnees) et retourne soit None (rien a faire) soit un FeaturePayload
decrivant l'action a executer (que bot.py applique reellement).

Cela rend les features 100% testables sans Discord.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from engagement import (
    EngagementChannel, AttentionBudget, DEFAULT_BUDGET,
    can_use_channel, record_attention, pick_starter, CONVERSATION_STARTERS,
)


# =============================================================================
# CONFIG
# =============================================================================

@dataclass
class CommunityConfig:
    """Config par-guild des features communautaires."""

    # ---- Daily conversation ----
    daily_conversation_enabled: bool = False
    daily_conversation_channel_id: Optional[int] = None
    daily_conversation_hour_utc: int = 18         # 18h UTC = ~19h Paris hiver
    daily_conversation_categories: list[str] = field(
        default_factory=lambda: ["general", "lifestyle", "culture"]
    )

    # ---- Member spotlight ----
    member_spotlight_enabled: bool = False
    member_spotlight_channel_id: Optional[int] = None
    member_spotlight_day_of_week: int = 0         # 0=lundi, 6=dimanche
    member_spotlight_hour_utc: int = 12

    # ---- Welcome ----
    welcome_quickstart_enabled: bool = True
    welcome_quickstart_channel_id: Optional[int] = None
    welcome_quickstart_rules_channel_id: Optional[int] = None
    welcome_quickstart_help_channel_id: Optional[int] = None

    # ---- Activity recognition ----
    activity_recognition_enabled: bool = True
    activity_recognition_burst_threshold: int = 10   # nb messages en X minutes
    activity_recognition_window_minutes: int = 5
    activity_recognition_emoji: str = "🔥"

    # ---- Inactivity nudge ----
    inactivity_nudge_enabled: bool = False
    inactivity_nudge_channel_ids: list[int] = field(default_factory=list)
    inactivity_nudge_threshold_hours: int = 48

    # ---- Theme days ----
    theme_days_enabled: bool = False
    theme_days: dict[int, str] = field(default_factory=dict)
    # Format: {day_of_week (0-6): "theme name"}, ex: {0: "Music Monday", 4: "Free Friday"}
    theme_days_channel_id: Optional[int] = None

    # ---- Weekly digest ----
    weekly_digest_enabled: bool = False
    weekly_digest_channel_id: Optional[int] = None
    weekly_digest_day_of_week: int = 6            # dimanche
    weekly_digest_hour_utc: int = 20

    @classmethod
    def from_dict(cls, data: dict) -> "CommunityConfig":
        # Theme days keys come as strings from JSON
        theme = data.get("theme_days", {})
        theme = {int(k): v for k, v in theme.items()}
        out = cls(**{**data, "theme_days": theme})
        return out


# =============================================================================
# PERSISTANCE
# =============================================================================

from paths import module_dir
DATA_DIR = module_dir("community")


def _config_path(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}_config.json"


def _state_path(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}_state.json"


_config_cache: dict[int, CommunityConfig] = {}


async def load_config(guild_id: int) -> CommunityConfig:
    if guild_id in _config_cache:
        return _config_cache[guild_id]
    path = _config_path(guild_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cfg = CommunityConfig.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            cfg = CommunityConfig()
    else:
        cfg = CommunityConfig()
    _config_cache[guild_id] = cfg
    return cfg


async def save_config(guild_id: int, cfg: CommunityConfig) -> None:
    _config_cache[guild_id] = cfg
    path = _config_path(guild_id)
    path.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")


async def reload_config(guild_id: int) -> CommunityConfig:
    _config_cache.pop(guild_id, None)
    return await load_config(guild_id)


# State (persistance des derniers triggers, pour eviter les doublons)
def _load_state(guild_id: int) -> dict:
    path = _state_path(guild_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(guild_id: int, state: dict) -> None:
    _state_path(guild_id).write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# =============================================================================
# PAYLOADS RETOURNES PAR LES FEATURES
# =============================================================================

class FeatureActionType(str, Enum):
    POST_MESSAGE = "post_message"
    ADD_REACTION = "add_reaction"
    PIN_MESSAGE = "pin_message"
    CREATE_THREAD = "create_thread"
    SEND_DM = "send_dm"


@dataclass
class FeaturePayload:
    """Decrit ce que bot.py doit faire pour appliquer la feature."""

    action_type: FeatureActionType
    target_channel_id: Optional[int] = None
    target_message_id: Optional[int] = None
    target_user_id: Optional[int] = None
    content: Optional[str] = None
    emoji: Optional[str] = None
    thread_name: Optional[str] = None
    metadata: dict = field(default_factory=dict)


# =============================================================================
# FEATURE 1 : DAILY CONVERSATION
# =============================================================================

async def should_post_daily_conversation(
    guild_id: int,
    now: Optional[datetime] = None,
) -> Optional[FeaturePayload]:
    """Verifie si on doit poster la question du jour."""
    cfg = await load_config(guild_id)
    if not cfg.daily_conversation_enabled or not cfg.daily_conversation_channel_id:
        return None

    now = now or datetime.now(timezone.utc)
    state = _load_state(guild_id)

    # Si on a deja poste aujourd'hui, on skip
    today_str = now.strftime("%Y-%m-%d")
    if state.get("last_daily_conversation_date") == today_str:
        return None

    # On poste a partir de l'heure configuree
    if now.hour < cfg.daily_conversation_hour_utc:
        return None

    # Budget d'attention (la question est un SUBTLE_REPLY)
    if not can_use_channel(guild_id, EngagementChannel.SUBTLE_REPLY):
        return None

    # Choisit une categorie au hasard parmi celles configurees
    if cfg.daily_conversation_categories:
        category = random.choice(cfg.daily_conversation_categories)
    else:
        category = None

    starter = pick_starter(guild_id, category=category)
    if not starter:
        return None

    record_attention(guild_id, EngagementChannel.SUBTLE_REPLY)
    state["last_daily_conversation_date"] = today_str
    _save_state(guild_id, state)

    content = (
        f"💬 **Question du jour**\n\n"
        f"{starter.text}\n\n"
        f"-# Reagis librement, partage ton avis !"
    )
    return FeaturePayload(
        action_type=FeatureActionType.POST_MESSAGE,
        target_channel_id=cfg.daily_conversation_channel_id,
        content=content,
        metadata={"category": starter.category, "starter_text": starter.text},
    )


# =============================================================================
# FEATURE 2 : MEMBER SPOTLIGHT
# =============================================================================

@dataclass
class MemberActivity:
    """Donnees d'activite d'un membre sur la fenetre consideree."""

    user_id: int
    user_name: str
    message_count: int
    voice_minutes: int = 0
    helpful_reactions: int = 0   # nb fois quelqu'un a reagi avec 👍❤️🤝 sur ses msgs


def _spotlight_score(activity: MemberActivity) -> float:
    """Score combine : messages + voix + utilite. Pondere pour ne pas favoriser le spam."""
    msg_score = min(activity.message_count, 200) * 0.4   # plafond 200
    voice_score = min(activity.voice_minutes / 60, 30) * 0.3  # plafond 30h
    helpful_score = activity.helpful_reactions * 1.0     # tres valorise
    return msg_score + voice_score + helpful_score


async def select_member_spotlight(
    guild_id: int,
    activity_data: list[MemberActivity],
    now: Optional[datetime] = None,
) -> Optional[FeaturePayload]:
    """Choisit un membre a mettre en avant cette semaine."""
    cfg = await load_config(guild_id)
    if not cfg.member_spotlight_enabled or not cfg.member_spotlight_channel_id:
        return None

    now = now or datetime.now(timezone.utc)
    state = _load_state(guild_id)

    # Le bon jour de la semaine ?
    if now.weekday() != cfg.member_spotlight_day_of_week:
        return None
    if now.hour < cfg.member_spotlight_hour_utc:
        return None

    week_str = now.strftime("%Y-W%U")
    if state.get("last_spotlight_week") == week_str:
        return None

    if not activity_data:
        return None

    # Eviter de re-elire le meme que la semaine derniere
    last_winner = state.get("last_spotlight_user_id")
    eligible = [a for a in activity_data if a.user_id != last_winner] or activity_data

    eligible.sort(key=_spotlight_score, reverse=True)
    winner = eligible[0]

    if _spotlight_score(winner) < 5:
        # Activite trop faible pour un spotlight, on skip
        return None

    if not can_use_channel(guild_id, EngagementChannel.PINNED):
        # On retombe sur SUBTLE_REPLY si epinglage indispo
        if not can_use_channel(guild_id, EngagementChannel.SUBTLE_REPLY):
            return None
        record_attention(guild_id, EngagementChannel.SUBTLE_REPLY)
    else:
        record_attention(guild_id, EngagementChannel.PINNED)

    state["last_spotlight_week"] = week_str
    state["last_spotlight_user_id"] = winner.user_id
    _save_state(guild_id, state)

    content = (
        f"⭐ **Membre de la semaine** ⭐\n\n"
        f"Bravo a <@{winner.user_id}> !\n"
        f"-# {winner.message_count} messages • "
        f"{winner.voice_minutes // 60}h de vocal • "
        f"{winner.helpful_reactions} reactions de remerciement"
    )
    return FeaturePayload(
        action_type=FeatureActionType.POST_MESSAGE,
        target_channel_id=cfg.member_spotlight_channel_id,
        target_user_id=winner.user_id,
        content=content,
        metadata={
            "week": week_str,
            "score": _spotlight_score(winner),
            "user_name": winner.user_name,
        },
    )


# =============================================================================
# FEATURE 3 : WELCOME QUICKSTART
# =============================================================================

async def build_welcome_message(
    guild_id: int,
    member_id: int,
    member_name: str,
    server_name: str,
) -> Optional[FeaturePayload]:
    """Construit un message de bienvenue personnalise (envoyable au membre ou en salon)."""
    cfg = await load_config(guild_id)
    if not cfg.welcome_quickstart_enabled:
        return None

    parts: list[str] = [
        f"👋 Bienvenue sur **{server_name}**, <@{member_id}> !",
        "",
        "Pour bien demarrer :",
    ]
    if cfg.welcome_quickstart_rules_channel_id:
        parts.append(f"📜 Lis les regles dans <#{cfg.welcome_quickstart_rules_channel_id}>")
    parts.append("⌨️ Tape `/help` pour voir les commandes")
    if cfg.welcome_quickstart_help_channel_id:
        parts.append(f"💬 Pose tes questions dans <#{cfg.welcome_quickstart_help_channel_id}>")
    parts.append("")
    parts.append("-# Bonne aventure parmi nous !")

    content = "\n".join(parts)

    target_channel = cfg.welcome_quickstart_channel_id
    if target_channel is None:
        # On retombe sur DM si pas de salon configure
        return FeaturePayload(
            action_type=FeatureActionType.SEND_DM,
            target_user_id=member_id,
            content=content,
            metadata={"member_name": member_name},
        )

    return FeaturePayload(
        action_type=FeatureActionType.POST_MESSAGE,
        target_channel_id=target_channel,
        target_user_id=member_id,
        content=content,
        metadata={"member_name": member_name},
    )


# =============================================================================
# FEATURE 4 : ACTIVITY RECOGNITION (gentle 🔥 reaction)
# =============================================================================

async def should_add_activity_reaction(
    guild_id: int,
    channel_id: int,
    target_message_id: int,
    recent_message_count: int,
    window_minutes: int,
) -> Optional[FeaturePayload]:
    """Si un salon connait un burst d'activite, on reagit subtilement."""
    cfg = await load_config(guild_id)
    if not cfg.activity_recognition_enabled:
        return None

    if recent_message_count < cfg.activity_recognition_burst_threshold:
        return None
    if window_minutes > cfg.activity_recognition_window_minutes:
        return None  # window trop large, pas vraiment un burst

    # Cooldown : eviter de reagir 2x dans le meme burst
    state = _load_state(guild_id)
    last_reaction_at = state.get("last_activity_reaction_at_per_channel", {}).get(str(channel_id))
    if last_reaction_at:
        last_dt = datetime.fromisoformat(last_reaction_at)
        if (datetime.now(timezone.utc) - last_dt).total_seconds() < 1800:  # 30 min
            return None

    # Toujours OK pour les reactions (zero notif)
    if not can_use_channel(guild_id, EngagementChannel.REACTION):
        return None
    record_attention(guild_id, EngagementChannel.REACTION)

    per_channel = state.setdefault("last_activity_reaction_at_per_channel", {})
    per_channel[str(channel_id)] = datetime.now(timezone.utc).isoformat()
    _save_state(guild_id, state)

    return FeaturePayload(
        action_type=FeatureActionType.ADD_REACTION,
        target_channel_id=channel_id,
        target_message_id=target_message_id,
        emoji=cfg.activity_recognition_emoji,
    )


# =============================================================================
# FEATURE 5 : INACTIVITY NUDGE
# =============================================================================

async def should_nudge_inactive_channel(
    guild_id: int,
    channel_id: int,
    last_message_at: datetime,
    now: Optional[datetime] = None,
) -> Optional[FeaturePayload]:
    """Si un salon est silencieux depuis trop longtemps, propose un starter."""
    cfg = await load_config(guild_id)
    if not cfg.inactivity_nudge_enabled:
        return None
    if cfg.inactivity_nudge_channel_ids and channel_id not in cfg.inactivity_nudge_channel_ids:
        return None

    now = now or datetime.now(timezone.utc)
    silent_hours = (now - last_message_at).total_seconds() / 3600
    if silent_hours < cfg.inactivity_nudge_threshold_hours:
        return None

    # Cooldown : pas de nudge dans les 24h precedant
    state = _load_state(guild_id)
    last_nudge = state.get("last_nudge_per_channel", {}).get(str(channel_id))
    if last_nudge:
        last_dt = datetime.fromisoformat(last_nudge)
        if (now - last_dt).total_seconds() < 86400:
            return None

    if not can_use_channel(guild_id, EngagementChannel.SUBTLE_REPLY):
        return None

    starter = pick_starter(guild_id)
    if not starter:
        return None

    record_attention(guild_id, EngagementChannel.SUBTLE_REPLY)
    per_channel = state.setdefault("last_nudge_per_channel", {})
    per_channel[str(channel_id)] = now.isoformat()
    _save_state(guild_id, state)

    content = (
        f"💭 Ce salon dort depuis un moment.\n\n"
        f"{starter.text}\n\n"
        f"-# Premier qui repond a tout mon respect"
    )
    return FeaturePayload(
        action_type=FeatureActionType.POST_MESSAGE,
        target_channel_id=channel_id,
        content=content,
        metadata={"silent_hours": silent_hours},
    )


# =============================================================================
# FEATURE 6 : THEME DAYS
# =============================================================================

async def get_theme_for_today(
    guild_id: int,
    now: Optional[datetime] = None,
) -> Optional[FeaturePayload]:
    """Si le jour du jour a un theme configure, on le rappelle subtilement."""
    cfg = await load_config(guild_id)
    if not cfg.theme_days_enabled or not cfg.theme_days_channel_id:
        return None

    now = now or datetime.now(timezone.utc)
    weekday = now.weekday()
    theme = cfg.theme_days.get(weekday)
    if not theme:
        return None

    # Une fois par jour max
    state = _load_state(guild_id)
    today_str = now.strftime("%Y-%m-%d")
    if state.get("last_theme_day_date") == today_str:
        return None

    if not can_use_channel(guild_id, EngagementChannel.SUBTLE_REPLY):
        return None

    record_attention(guild_id, EngagementChannel.SUBTLE_REPLY)
    state["last_theme_day_date"] = today_str
    _save_state(guild_id, state)

    content = (
        f"🎯 **{theme}**\n\n"
        f"-# C'est le moment de partager sur ce theme dans ce salon !"
    )
    return FeaturePayload(
        action_type=FeatureActionType.POST_MESSAGE,
        target_channel_id=cfg.theme_days_channel_id,
        content=content,
        metadata={"theme": theme, "weekday": weekday},
    )


# =============================================================================
# FEATURE 7 : WEEKLY DIGEST
# =============================================================================

@dataclass
class WeeklyStats:
    """Stats hebdomadaires fournies par bot.py."""

    new_members: int = 0
    total_messages: int = 0
    voice_hours: int = 0
    most_active_channel: Optional[tuple[int, int]] = None  # (channel_id, message_count)
    top_contributors: list[tuple[int, int]] = field(default_factory=list)  # [(user_id, message_count), ...]


async def build_weekly_digest(
    guild_id: int,
    stats: WeeklyStats,
    now: Optional[datetime] = None,
) -> Optional[FeaturePayload]:
    """Genere le resume hebdo si on est le bon jour/heure."""
    cfg = await load_config(guild_id)
    if not cfg.weekly_digest_enabled or not cfg.weekly_digest_channel_id:
        return None

    now = now or datetime.now(timezone.utc)
    if now.weekday() != cfg.weekly_digest_day_of_week:
        return None
    if now.hour < cfg.weekly_digest_hour_utc:
        return None

    state = _load_state(guild_id)
    week_str = now.strftime("%Y-W%U")
    if state.get("last_digest_week") == week_str:
        return None

    if not can_use_channel(guild_id, EngagementChannel.PINNED):
        if not can_use_channel(guild_id, EngagementChannel.SUBTLE_REPLY):
            return None
        record_attention(guild_id, EngagementChannel.SUBTLE_REPLY)
    else:
        record_attention(guild_id, EngagementChannel.PINNED)

    state["last_digest_week"] = week_str
    _save_state(guild_id, state)

    parts = [
        "📊 **Bilan hebdomadaire**",
        "",
        f"👥 **{stats.new_members}** nouveaux membres cette semaine",
        f"💬 **{stats.total_messages}** messages echanges",
        f"🎤 **{stats.voice_hours}h** en vocal",
    ]
    if stats.most_active_channel:
        ch_id, count = stats.most_active_channel
        parts.append(f"🔥 Salon le plus actif : <#{ch_id}> ({count} messages)")
    if stats.top_contributors:
        top_lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, c) in enumerate(stats.top_contributors[:3]):
            medal = medals[i] if i < 3 else "🏅"
            top_lines.append(f"{medal} <@{uid}> — {c} messages")
        parts.append("")
        parts.append("**Top contributeurs**")
        parts.extend(top_lines)
    parts.append("")
    parts.append("-# Bonne semaine a tous !")

    return FeaturePayload(
        action_type=FeatureActionType.POST_MESSAGE,
        target_channel_id=cfg.weekly_digest_channel_id,
        content="\n".join(parts),
        metadata={"week": week_str},
    )


__all__ = [
    "CommunityConfig",
    "FeatureActionType",
    "FeaturePayload",
    "MemberActivity",
    "WeeklyStats",
    "load_config",
    "save_config",
    "reload_config",
    "should_post_daily_conversation",
    "select_member_spotlight",
    "build_welcome_message",
    "should_add_activity_reaction",
    "should_nudge_inactive_channel",
    "get_theme_for_today",
    "build_weekly_digest",
]
