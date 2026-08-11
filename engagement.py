"""
engagement.py - Primitives d'engagement communautaire (Phase 0 du redesign 2026).

Objectif : rendre le serveur vivant SANS spammer de pings.

Strategie :
- Notifications subtiles (reactions, citations, threads ambiants)
- Evenements automatiques bases sur l'activite reelle (pas sur des horaires fixes)
- Recompenses passives (XP, badges, roles temporaires)
- Conversation starters (questions du jour ciblees par centres d'interet)
- Budget d'attention (le bot s'auto-regule pour ne pas saouler les membres)

API:
    - EngagementChannel : enum des canaux d'attention (du moins au plus intrusif)
    - ConversationStarter : declencheur de conversation
    - EngagementEvent : evenement d'ambiance
    - AttentionBudget : limite par jour/semaine
    - can_use_channel(guild_id, channel) : verifie le budget
    - record_attention(guild_id, channel) : enregistre une utilisation
    - pick_starter(category, exclude) : choisit un starter sans repetition
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# =============================================================================
# CANAUX D'ATTENTION (du moins au plus intrusif)
# =============================================================================

class EngagementChannel(Enum):
    """Canaux d'attention disponibles, classes par intrusivite croissante."""

    REACTION = "reaction"           # Bot reagit avec emoji (zero ping, zero notif)
    SUBTLE_REPLY = "subtle_reply"   # Reponse courte sans mention
    THREAD = "thread"               # Cree un thread (les membres y opt-in)
    PINNED = "pinned"               # Epinglage d'un message marquant
    DM = "dm"                       # Message prive (rare, important seulement)
    CHANNEL_PING = "channel_ping"   # Ping d'un role (events majeurs uniquement)


CHANNEL_LABELS: dict[EngagementChannel, str] = {
    EngagementChannel.REACTION:     "Reaction (zero notification)",
    EngagementChannel.SUBTLE_REPLY: "Reponse discrete",
    EngagementChannel.THREAD:       "Thread (opt-in)",
    EngagementChannel.PINNED:       "Epinglage",
    EngagementChannel.DM:           "Message prive",
    EngagementChannel.CHANNEL_PING: "Ping de role (rare)",
}


# =============================================================================
# MODELES
# =============================================================================

@dataclass
class ConversationStarter:
    """Question/declencheur de conversation."""

    text: str
    category: str = "general"           # general, gaming, lifestyle, tech, music, ...
    audience_min_messages: int = 0      # cible : membres avec >= N messages
    cooldown_hours: int = 24            # ne pas repeter avant N heures


@dataclass
class EngagementEvent:
    """Evenement d'engagement declenche par l'activite."""

    name: str
    trigger: str                        # ex: "10_messages_in_5min"
    channel: EngagementChannel
    description: str
    cooldown_minutes: int = 60


@dataclass
class AttentionBudget:
    """Budget d'attention pour s'auto-reguler.

    Le bot tient un compteur par serveur : combien d'interventions ces
    dernieres 24h/7j ? Au-dela, il bascule vers des canaux moins intrusifs
    (REACTION uniquement).
    """

    max_subtle_replies_per_day: int = 5
    max_threads_per_day: int = 2
    max_pinned_per_week: int = 1
    max_dms_per_week: int = 0          # off par defaut
    max_channel_pings_per_week: int = 1


DEFAULT_BUDGET = AttentionBudget()


# =============================================================================
# CONVERSATION STARTERS (pre-definis, extensibles par owner)
# =============================================================================

CONVERSATION_STARTERS: list[ConversationStarter] = [
    # General
    ConversationStarter("Quel est le dernier truc qui t'a fait sourire aujourd'hui ?", category="general"),
    ConversationStarter("Si tu pouvais maitriser une nouvelle competence en 1 mois, ce serait quoi ?", category="general"),
    ConversationStarter("Le meilleur conseil que tu aies recu ?", category="general"),

    # Lifestyle
    ConversationStarter("Ton rituel matinal indispensable ?", category="lifestyle"),
    ConversationStarter("Une habitude qui t'a change la vie ?", category="lifestyle"),

    # Gaming
    ConversationStarter("Recommande un jeu sous-cote qui merite plus d'attention.", category="gaming"),
    ConversationStarter("Le boss/level qui t'a marque a vie ?", category="gaming"),

    # Music
    ConversationStarter("Le morceau qui passe en boucle chez toi en ce moment ?", category="music"),
    ConversationStarter("Un artiste decouvert recemment ?", category="music"),

    # Tech
    ConversationStarter("Le projet sur lequel tu bosses en ce moment ?", category="tech"),
    ConversationStarter("Un outil/framework dont tu ne peux plus te passer ?", category="tech"),

    # Culture
    ConversationStarter("Une decouverte recente (livre, film, serie) ?", category="culture"),
    ConversationStarter("Un classique sous-estime selon toi ?", category="culture"),
]


# =============================================================================
# EVENEMENTS AMBIANTS (declenches par l'activite reelle)
# =============================================================================

AMBIENT_EVENTS: list[EngagementEvent] = [
    EngagementEvent(
        name="hot_topic",
        trigger="10_messages_in_5min",
        channel=EngagementChannel.REACTION,
        description="Le bot ajoute un 🔥 sur le 10eme message d'un echange dynamique.",
        cooldown_minutes=30,
    ),
    EngagementEvent(
        name="welcome_back",
        trigger="member_returning_after_7d",
        channel=EngagementChannel.SUBTLE_REPLY,
        description="Salutation discrete pour un membre absent depuis plus d'une semaine.",
        cooldown_minutes=10080,  # 7j
    ),
    EngagementEvent(
        name="thread_burst",
        trigger="20_messages_in_10min",
        channel=EngagementChannel.THREAD,
        description="Cree un thread pour archiver une discussion intense.",
        cooldown_minutes=120,
    ),
    EngagementEvent(
        name="quiet_nudge",
        trigger="channel_silent_24h",
        channel=EngagementChannel.SUBTLE_REPLY,
        description="Pose une question d'ouverture (conversation starter) si un salon est silencieux 24h.",
        cooldown_minutes=1440,  # 1j
    ),
    EngagementEvent(
        name="milestone_celebrate",
        trigger="member_count_round_number",
        channel=EngagementChannel.PINNED,
        description="Celebre un cap de membres atteint (100, 500, 1000...).",
        cooldown_minutes=43200,  # 30j
    ),
]


# =============================================================================
# TRACKER (en memoire pour l'instant - persistence dans Phase 1)
# =============================================================================

_attention_log: dict[int, list[tuple[datetime, EngagementChannel]]] = {}
_starter_history: dict[int, list[tuple[datetime, str]]] = {}


def can_use_channel(
    guild_id: int,
    channel_type: EngagementChannel,
    budget: AttentionBudget = DEFAULT_BUDGET,
) -> bool:
    """Verifie si le bot peut utiliser ce canal sans depasser le budget."""
    now = datetime.now(timezone.utc)
    log = _attention_log.setdefault(guild_id, [])

    # Nettoyage : on garde 7j max
    log[:] = [(t, c) for t, c in log if (now - t).total_seconds() < 7 * 86400]

    if channel_type == EngagementChannel.REACTION:
        return True  # toujours autorise (zero pollution)

    def count_within(seconds: int, ch: EngagementChannel) -> int:
        return sum(1 for t, c in log if c == ch and (now - t).total_seconds() < seconds)

    if channel_type == EngagementChannel.SUBTLE_REPLY:
        return count_within(86400, channel_type) < budget.max_subtle_replies_per_day
    if channel_type == EngagementChannel.THREAD:
        return count_within(86400, channel_type) < budget.max_threads_per_day
    if channel_type == EngagementChannel.PINNED:
        return count_within(7 * 86400, channel_type) < budget.max_pinned_per_week
    if channel_type == EngagementChannel.DM:
        return count_within(7 * 86400, channel_type) < budget.max_dms_per_week
    if channel_type == EngagementChannel.CHANNEL_PING:
        return count_within(7 * 86400, channel_type) < budget.max_channel_pings_per_week

    return True


def record_attention(guild_id: int, channel_type: EngagementChannel) -> None:
    """Enregistre une utilisation d'un canal d'attention."""
    now = datetime.now(timezone.utc)
    _attention_log.setdefault(guild_id, []).append((now, channel_type))


def attention_usage(guild_id: int) -> dict[EngagementChannel, int]:
    """Retourne les utilisations sur les 7 derniers jours, par canal."""
    now = datetime.now(timezone.utc)
    log = _attention_log.get(guild_id, [])
    out: dict[EngagementChannel, int] = {}
    for t, c in log:
        if (now - t).total_seconds() < 7 * 86400:
            out[c] = out.get(c, 0) + 1
    return out


# =============================================================================
# CONVERSATION STARTERS
# =============================================================================

def pick_starter(
    guild_id: int,
    category: Optional[str] = None,
    exclude_recent_hours: int = 48,
) -> Optional[ConversationStarter]:
    """Choisit un starter en evitant la repetition recente.

    - `category` filtre la categorie (None = toutes)
    - `exclude_recent_hours` exclut les starters utilises dans les N dernieres heures
    """
    now = datetime.now(timezone.utc)
    history = _starter_history.setdefault(guild_id, [])

    # Nettoyage : on garde une semaine max
    history[:] = [
        (t, txt) for t, txt in history
        if (now - t).total_seconds() < 7 * 86400
    ]

    # Filtre les starters utilises recemment
    cutoff = exclude_recent_hours * 3600
    recent_texts = {
        txt for t, txt in history if (now - t).total_seconds() < cutoff
    }

    candidates = [
        s for s in CONVERSATION_STARTERS
        if (category is None or s.category == category)
        and s.text not in recent_texts
    ]

    if not candidates:
        return None

    chosen = random.choice(candidates)
    history.append((now, chosen.text))
    return chosen


__all__ = [
    "EngagementChannel",
    "CHANNEL_LABELS",
    "ConversationStarter",
    "EngagementEvent",
    "AttentionBudget",
    "DEFAULT_BUDGET",
    "CONVERSATION_STARTERS",
    "AMBIENT_EVENTS",
    "can_use_channel",
    "record_attention",
    "attention_usage",
    "pick_starter",
]
