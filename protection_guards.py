"""
protection_guards.py - Garde-fous anti-faux-positifs (Phase 1.3 du redesign 2026).

But : empecher les bans / kicks injustes par AutoMod et antiraid.

Contexte (retour owner) :
    "On a eu des soucis ou l'automode bannissait les gens aleatoirement
     parce qu'ils envoyaient juste de simples giveaways, des images, etc."

Approche multi-couches :
    1. Trust score utilisateur (anciennete + activite + roles)
    2. Confidence score sur chaque detection
    3. Whitelist patterns/domaines/users
    4. Gradient d'actions (NONE -> LOG -> WARN -> MUTE -> KICK -> BAN)
    5. Audit trail pour chaque action automatique
    6. Mode SOFT (dry-run global, log uniquement)
    7. Mode REVIEW (DM staff au lieu de sanctionner)

Integration cote bot :
    Au lieu d'agir directement, le code antimode appelle :

        from protection_guards import decide_action, AutoEventType

        decision = await decide_action(
            guild_id=msg.guild.id,
            member=msg.author,
            event_type=AutoEventType.SPAM,
            confidence=0.6,
            evidence=["5 messages identiques en 10s"],
            proposed_action=Action.MUTE,
        )

        if decision.final_action == Action.NONE:
            return  # downgrade total : on ne fait rien
        # ... applique decision.final_action

    Le module garantit que les utilisateurs avec trust score eleve sont
    proteges, que les patterns whitelistes (gifs, giveaways) ne declenchent
    rien, et que tout est audite.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


# =============================================================================
# ENUMS
# =============================================================================

class Action(str, Enum):
    NONE = "none"      # ne rien faire (event whiteliste ou trust trop haut)
    LOG = "log"        # juste enregistrer dans l'audit
    WARN = "warn"      # avertir le membre
    MUTE = "mute"      # timeout court (5min)
    TEMPMUTE = "tempmute"  # timeout long (1-24h)
    KICK = "kick"      # expulser
    BAN = "ban"        # bannir


class AutoEventType(str, Enum):
    SPAM = "spam"
    BADWORD = "badword"
    PHISHING = "phishing"
    SCAM = "scam"
    RAID = "raid"
    ALT_DETECTION = "alt"
    IMAGE_FLOOD = "image_flood"
    LINK = "link"
    INVITE_ADVERTISEMENT = "invite_ad"
    MASS_MENTION = "mass_mention"
    QR_CODE = "qr_code"
    NSFW = "nsfw"


ACTION_SEVERITY: dict[Action, int] = {
    Action.NONE: 0,
    Action.LOG: 1,
    Action.WARN: 2,
    Action.MUTE: 3,
    Action.TEMPMUTE: 4,
    Action.KICK: 5,
    Action.BAN: 6,
}


# =============================================================================
# WHITELISTS PAR DEFAUT (corrigent les faux-positifs connus)
# =============================================================================

DEFAULT_DOMAIN_WHITELIST: list[str] = [
    # Gifs / memes
    "tenor.com", "giphy.com", "gfycat.com",
    # Hosts d'images legitimes
    "imgur.com", "i.imgur.com",
    "cdn.discordapp.com", "media.discordapp.net",
    "media.tenor.com", "media.giphy.com",
    # Reseaux sociaux (les liens sont legit a partager)
    "youtube.com", "youtu.be",
    "twitch.tv", "kick.com",
    "twitter.com", "x.com",
    "tiktok.com", "vm.tiktok.com",
    "instagram.com",
    "reddit.com", "redd.it",
    # Gaming
    "store.steampowered.com", "steamcommunity.com",
    "epicgames.com",
    "roblox.com",
    "ea.com", "ubisoft.com",
    # Tech docs
    "github.com", "gitlab.com",
    "stackoverflow.com",
]

# Patterns regex de "giveaway legitime" (le ! doit pas declencher antiscam)
DEFAULT_GIVEAWAY_PATTERNS: list[str] = [
    r"🎁",                                        # emoji cadeau
    r"\bgiveaway\b",
    r"\bgiveways\b",
    r"\btirage\b",
    r"\bconcours\b",
    r"\bwinner\b",
    r"\bgagnant\b",
]

# Extensions images / videos legitimes
LEGIT_FILE_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".webm",
}


# =============================================================================
# MODELES
# =============================================================================

@dataclass
class TrustScore:
    """Score de confiance d'un membre (0-100)."""

    account_age_days: int = 0
    server_age_days: int = 0
    message_count: int = 0
    has_privileged_role: bool = False
    is_booster: bool = False
    has_premium_indicator: bool = False  # ex: nitro display

    @property
    def value(self) -> int:
        score = 0
        # Age compte (max 30 pts)
        if self.account_age_days >= 365:
            score += 30
        elif self.account_age_days >= 180:
            score += 20
        elif self.account_age_days >= 30:
            score += 10
        elif self.account_age_days >= 7:
            score += 5
        # Anciennete sur le serveur (max 25 pts)
        if self.server_age_days >= 180:
            score += 25
        elif self.server_age_days >= 30:
            score += 15
        elif self.server_age_days >= 7:
            score += 8
        # Activite (max 25 pts)
        if self.message_count >= 1000:
            score += 25
        elif self.message_count >= 200:
            score += 15
        elif self.message_count >= 50:
            score += 8
        elif self.message_count >= 10:
            score += 3
        # Roles (max 20 pts)
        if self.has_privileged_role:
            score += 15
        if self.is_booster:
            score += 5
        if self.has_premium_indicator:
            score += 2
        return min(score, 100)


@dataclass
class DetectionEvent:
    """Une detection rapportee par un module antimode."""

    event_type: AutoEventType
    confidence: float                  # 0.0 a 1.0
    evidence: list[str] = field(default_factory=list)
    raw_content: Optional[str] = None  # contenu detecte (sera tronque dans l'audit)


@dataclass
class ActionDecision:
    """Decision finale apres passage par les garde-fous."""

    final_action: Action
    proposed_action: Action
    reason: str
    downgraded: bool = False
    audit_log_only: bool = False
    notify_staff: bool = False
    trust_score: int = 0


@dataclass
class AuditEntry:
    """Une entree d'audit (chaque decision est auditee)."""

    timestamp: str
    guild_id: int
    user_id: int
    user_name: str
    event_type: str
    confidence: float
    proposed_action: str
    final_action: str
    reason: str
    trust_score: int
    evidence_summary: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AuditEntry":
        return cls(**data)


# =============================================================================
# POLITIQUE PAR-GUILD
# =============================================================================

@dataclass
class ProtectionPolicy:
    """Configuration des garde-fous pour un serveur."""

    # Mode global
    soft_mode: bool = False               # True = jamais de sanction reelle, tout est log
    review_mode: bool = False             # True = DM staff au lieu de sanctionner

    # Trust boost
    trust_boost_enabled: bool = True
    trust_threshold_protected: int = 70   # >= 70 : pas de ban auto
    trust_threshold_immune: int = 90      # >= 90 : seulement LOG meme sur scam

    # Seuils de confiance par event type (action -> min confidence requise)
    # Defaults conservateurs : il faut tres peu de confidence pour WARN,
    # mais quasi-certitude pour BAN.
    confidence_thresholds: dict[str, dict[str, float]] = field(default_factory=lambda: {
        AutoEventType.SPAM.value: {
            "warn": 0.3, "mute": 0.5, "tempmute": 0.7, "kick": 0.85, "ban": 0.95,
        },
        AutoEventType.BADWORD.value: {
            "warn": 0.3, "mute": 0.6, "tempmute": 0.8, "kick": 0.95, "ban": 0.99,
        },
        AutoEventType.PHISHING.value: {
            "warn": 0.2, "mute": 0.4, "tempmute": 0.6, "kick": 0.8, "ban": 0.92,
        },
        AutoEventType.SCAM.value: {
            "warn": 0.2, "mute": 0.4, "tempmute": 0.6, "kick": 0.8, "ban": 0.92,
        },
        AutoEventType.RAID.value: {
            "warn": 0.4, "mute": 0.6, "tempmute": 0.75, "kick": 0.85, "ban": 0.95,
        },
        AutoEventType.ALT_DETECTION.value: {
            "warn": 0.5, "mute": 0.7, "tempmute": 0.85, "kick": 0.92, "ban": 0.98,
        },
        AutoEventType.IMAGE_FLOOD.value: {
            "warn": 0.4, "mute": 0.7, "tempmute": 0.85, "kick": 0.95, "ban": 0.99,
        },
        AutoEventType.LINK.value: {
            "warn": 0.3, "mute": 0.6, "tempmute": 0.8, "kick": 0.95, "ban": 0.99,
        },
        AutoEventType.INVITE_ADVERTISEMENT.value: {
            "warn": 0.3, "mute": 0.5, "tempmute": 0.7, "kick": 0.85, "ban": 0.95,
        },
        AutoEventType.MASS_MENTION.value: {
            "warn": 0.4, "mute": 0.65, "tempmute": 0.8, "kick": 0.92, "ban": 0.98,
        },
        AutoEventType.QR_CODE.value: {
            "warn": 0.3, "mute": 0.5, "tempmute": 0.7, "kick": 0.85, "ban": 0.95,
        },
        AutoEventType.NSFW.value: {
            "warn": 0.3, "mute": 0.6, "tempmute": 0.8, "kick": 0.9, "ban": 0.97,
        },
    })

    # Whitelists
    domain_whitelist: list[str] = field(default_factory=lambda: list(DEFAULT_DOMAIN_WHITELIST))
    giveaway_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_GIVEAWAY_PATTERNS))
    trusted_user_ids: list[int] = field(default_factory=list)
    trusted_role_ids: list[int] = field(default_factory=list)

    # Notifications
    audit_log_channel_id: Optional[int] = None
    staff_review_channel_id: Optional[int] = None
    staff_role_id: Optional[int] = None

    # Quota anti-action-storm : si > N actions auto en M minutes, on bascule en review
    action_storm_threshold: int = 5
    action_storm_window_minutes: int = 5


# =============================================================================
# PERSISTANCE
# =============================================================================

from paths import module_dir
DATA_DIR = module_dir("protection")
AUDIT_DIR = DATA_DIR / "audit"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def _policy_path(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}_policy.json"


def _audit_path(guild_id: int) -> Path:
    return AUDIT_DIR / f"{guild_id}.jsonl"


_io_lock = asyncio.Lock()
_policy_cache: dict[int, ProtectionPolicy] = {}


async def load_policy(guild_id: int) -> ProtectionPolicy:
    """Charge la politique d'un guild (cache + disque)."""
    if guild_id in _policy_cache:
        return _policy_cache[guild_id]
    async with _io_lock:
        if guild_id in _policy_cache:
            return _policy_cache[guild_id]
        path = _policy_path(guild_id)
        if not path.exists():
            policy = ProtectionPolicy()
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                policy = ProtectionPolicy(**data)
            except (json.JSONDecodeError, TypeError):
                policy = ProtectionPolicy()
        _policy_cache[guild_id] = policy
        return policy


async def save_policy(guild_id: int, policy: ProtectionPolicy) -> None:
    async with _io_lock:
        _policy_cache[guild_id] = policy
        path = _policy_path(guild_id)
        path.write_text(
            json.dumps(asdict(policy), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


async def reload_policy(guild_id: int) -> ProtectionPolicy:
    async with _io_lock:
        _policy_cache.pop(guild_id, None)
    return await load_policy(guild_id)


# =============================================================================
# AUDIT (JSONL append-only, simple et robuste)
# =============================================================================

async def append_audit(entry: AuditEntry) -> None:
    async with _io_lock:
        path = _audit_path(entry.guild_id)
        line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


async def read_audit(guild_id: int, limit: int = 100) -> list[AuditEntry]:
    async with _io_lock:
        path = _audit_path(guild_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
    out: list[AuditEntry] = []
    for line in lines[-limit:]:
        try:
            d = json.loads(line)
            out.append(AuditEntry.from_dict(d))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


# =============================================================================
# TRACKER ANTI-ACTION-STORM
# =============================================================================

# guild_id -> deque-like list de (timestamp_seconds, action)
_action_log: dict[int, list[float]] = {}


def _record_action(guild_id: int) -> int:
    """Enregistre une action et retourne le nombre d'actions sur la fenetre."""
    now = datetime.now(timezone.utc).timestamp()
    log = _action_log.setdefault(guild_id, [])
    # Garde max 1h
    cutoff = now - 3600
    log[:] = [t for t in log if t >= cutoff]
    log.append(now)
    return len(log)


def _action_count_in_window(guild_id: int, window_minutes: int) -> int:
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - (window_minutes * 60)
    return sum(1 for t in _action_log.get(guild_id, []) if t >= cutoff)


# =============================================================================
# WHITELIST CHECKS
# =============================================================================

def _content_matches_giveaway(text: str, patterns: list[str]) -> bool:
    """True si le texte contient des indices de giveaway legitime."""
    if not text:
        return False
    matches = 0
    for pat in patterns:
        try:
            if re.search(pat, text, re.IGNORECASE):
                matches += 1
        except re.error:
            continue
    return matches >= 2  # au moins 2 signaux concordants


URL_RE = re.compile(r"https?://([^\s/?#]+)", re.IGNORECASE)


def _content_only_whitelisted_domains(text: str, whitelist: list[str]) -> bool:
    """True si toutes les URLs du texte sont sur des domaines whitelistes."""
    urls = URL_RE.findall(text or "")
    if not urls:
        return False
    wl_lower = {d.lower() for d in whitelist}
    for raw in urls:
        domain = raw.lower()
        # On considere comme match si le domaine ou un parent est dans la WL
        ok = any(domain == w or domain.endswith("." + w) for w in wl_lower)
        if not ok:
            return False
    return True


def _user_is_trusted(
    user_id: int, role_ids: list[int], policy: ProtectionPolicy
) -> bool:
    if user_id in policy.trusted_user_ids:
        return True
    return bool(set(role_ids) & set(policy.trusted_role_ids))


# =============================================================================
# CALCUL DE L'ACTION FINALE
# =============================================================================

def _action_for_confidence(
    event_type: AutoEventType, confidence: float, policy: ProtectionPolicy
) -> Action:
    """Determine l'action max permise par la politique pour cette confidence."""
    thresholds = policy.confidence_thresholds.get(event_type.value, {})
    # On parcourt les actions du plus severe au moins severe
    for action_str in ("ban", "kick", "tempmute", "mute", "warn"):
        threshold = thresholds.get(action_str)
        if threshold is None:
            continue
        if confidence >= threshold:
            return Action(action_str)
    return Action.LOG


def _downgrade_for_trust(action: Action, trust: int, policy: ProtectionPolicy) -> Action:
    """Reduit la severite si le trust est eleve."""
    if not policy.trust_boost_enabled:
        return action
    severity = ACTION_SEVERITY[action]
    if trust >= policy.trust_threshold_immune:
        # Seulement LOG, jamais de sanction reelle
        return Action.LOG if severity > ACTION_SEVERITY[Action.WARN] else action
    if trust >= policy.trust_threshold_protected:
        # Pas de ban auto
        if action == Action.BAN:
            return Action.KICK
        if action == Action.KICK:
            return Action.TEMPMUTE
        # Mute reste mute, warn reste warn
    return action


# =============================================================================
# API PUBLIQUE
# =============================================================================

@dataclass
class MemberContext:
    """Contexte d'un membre fourni par bot.py (pas de discord.Member ici pour pouvoir tester)."""

    user_id: int
    user_name: str
    role_ids: list[int]
    account_age_days: int
    server_age_days: int
    message_count: int
    has_privileged_role: bool = False
    is_booster: bool = False


async def decide_action(
    guild_id: int,
    member: MemberContext,
    event: DetectionEvent,
    proposed_action: Action,
) -> ActionDecision:
    """Decide l'action finale apres passage par les garde-fous.

    Strategie :
        1. Si l'utilisateur est trusted_user_ids ou a un trusted_role : NONE
        2. Si event_type=PHISHING/SCAM/LINK/QR_CODE et que content match
           giveaway pattern OU domaines whitelistes : downgrade a LOG
        3. Calcule l'action max permise par confidence
        4. Cap par proposed_action (ne jamais sur-sanctionner)
        5. Trust boost
        6. Si soft_mode : final = LOG (mais on log la decision originale)
        7. Si action storm detectee : final = LOG, notify_staff = True
        8. Audit append
    """
    policy = await load_policy(guild_id)
    trust = TrustScore(
        account_age_days=member.account_age_days,
        server_age_days=member.server_age_days,
        message_count=member.message_count,
        has_privileged_role=member.has_privileged_role,
        is_booster=member.is_booster,
    ).value

    # 1. User trusted
    if _user_is_trusted(member.user_id, member.role_ids, policy):
        return await _finalize(
            guild_id, member, event, proposed_action,
            final=Action.LOG, reason="user/role whitelist", trust=trust,
            policy=policy,
        )

    # 2. Whitelist contenu
    raw = event.raw_content or ""
    if event.event_type in (
        AutoEventType.PHISHING, AutoEventType.SCAM, AutoEventType.LINK,
        AutoEventType.QR_CODE, AutoEventType.INVITE_ADVERTISEMENT,
    ):
        if _content_matches_giveaway(raw, policy.giveaway_patterns):
            return await _finalize(
                guild_id, member, event, proposed_action,
                final=Action.LOG,
                reason="giveaway pattern detecte",
                trust=trust, policy=policy,
            )
        if _content_only_whitelisted_domains(raw, policy.domain_whitelist):
            return await _finalize(
                guild_id, member, event, proposed_action,
                final=Action.LOG,
                reason="domaines whitelistes uniquement",
                trust=trust, policy=policy,
            )

    # 3. Action max par confidence
    confidence_action = _action_for_confidence(event.event_type, event.confidence, policy)

    # 4. Cap par proposed (ne jamais sur-sanctionner)
    if ACTION_SEVERITY[confidence_action] > ACTION_SEVERITY[proposed_action]:
        capped = proposed_action
    else:
        capped = confidence_action

    # 5. Trust boost (downgrade)
    boosted = _downgrade_for_trust(capped, trust, policy)
    downgraded = ACTION_SEVERITY[boosted] < ACTION_SEVERITY[capped]

    # 6. Soft / review mode
    audit_only = False
    notify_staff = False
    if policy.soft_mode and ACTION_SEVERITY[boosted] > ACTION_SEVERITY[Action.LOG]:
        boosted = Action.LOG
        audit_only = True
        notify_staff = True
    if policy.review_mode and ACTION_SEVERITY[boosted] > ACTION_SEVERITY[Action.WARN]:
        boosted = Action.LOG
        audit_only = True
        notify_staff = True

    # 7. Action storm
    storm = _action_count_in_window(guild_id, policy.action_storm_window_minutes)
    if storm >= policy.action_storm_threshold and ACTION_SEVERITY[boosted] >= ACTION_SEVERITY[Action.KICK]:
        boosted = Action.LOG
        audit_only = True
        notify_staff = True

    # On enregistre l'action seulement si on aurait agi
    if not audit_only and ACTION_SEVERITY[boosted] >= ACTION_SEVERITY[Action.MUTE]:
        _record_action(guild_id)

    reason_parts = []
    if downgraded:
        reason_parts.append(f"trust={trust} downgrade")
    if audit_only:
        reason_parts.append("soft/review/storm => audit only")
    if not reason_parts:
        reason_parts.append(f"confidence={event.confidence:.2f}")
    reason = " | ".join(reason_parts)

    return await _finalize(
        guild_id, member, event, proposed_action,
        final=boosted, reason=reason, trust=trust, policy=policy,
        downgraded=downgraded, audit_only=audit_only, notify_staff=notify_staff,
    )


async def _finalize(
    guild_id: int,
    member: MemberContext,
    event: DetectionEvent,
    proposed_action: Action,
    *,
    final: Action,
    reason: str,
    trust: int,
    policy: ProtectionPolicy,
    downgraded: bool = False,
    audit_only: bool = False,
    notify_staff: bool = False,
) -> ActionDecision:
    """Finalise une decision : audit + retour."""
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        guild_id=guild_id,
        user_id=member.user_id,
        user_name=member.user_name,
        event_type=event.event_type.value,
        confidence=event.confidence,
        proposed_action=proposed_action.value,
        final_action=final.value,
        reason=reason,
        trust_score=trust,
        evidence_summary=" / ".join(event.evidence)[:300],
    )
    await append_audit(entry)
    return ActionDecision(
        final_action=final,
        proposed_action=proposed_action,
        reason=reason,
        downgraded=downgraded or ACTION_SEVERITY[final] < ACTION_SEVERITY[proposed_action],
        audit_log_only=audit_only,
        notify_staff=notify_staff,
        trust_score=trust,
    )


__all__ = [
    "Action",
    "AutoEventType",
    "ACTION_SEVERITY",
    "DEFAULT_DOMAIN_WHITELIST",
    "DEFAULT_GIVEAWAY_PATTERNS",
    "TrustScore",
    "MemberContext",
    "DetectionEvent",
    "ActionDecision",
    "AuditEntry",
    "ProtectionPolicy",
    "load_policy",
    "save_policy",
    "reload_policy",
    "append_audit",
    "read_audit",
    "decide_action",
]
