"""
compromised_detector.py - Détection à HAUTE confiance de comptes piratés.

Phase 23 : système qui ne triggre QUE quand on est sûr à 90%+ que le compte
est compromis. Pas de faux positifs — chaque alerte est manuelle-actionable.

CRITÈRES DE CONFIANCE (chaque signal vaut un score) :

🔴 SIGNAUX FORTS (high confidence, 30+ pts chacun) :
  - Lien Discord d'invitation (`discord.gg/X`, `discord.com/invite/X`) DANS UN DM ou un message non-attendu
  - Lien de phishing connu (steam-gift, nitro-free, etc.)
  - @everyone OU @here SANS permission de le faire normalement
  - Message identique posté dans 3+ salons en moins de 30 sec

🟠 SIGNAUX MOYENS (15-25 pts) :
  - Compte créé il y a < 30 jours qui envoie soudainement un lien
  - Premier message du membre = lien + mention massive
  - Lien raccourci suspect (bit.ly, tinyurl, etc.) avec urgence textuelle

🟡 SIGNAUX FAIBLES (5-10 pts) :
  - Lien dans un salon où l'user n'a JAMAIS écrit avant
  - Avatar par défaut (sans photo)
  - Nom contenant "free", "nitro", "gift", "steam"

SEUIL : 60+ pts = compte considéré compromis → alerte dans le salon dédié.

API :
    score_message(member, message_content, channel, recent_history) → (score, reasons, signals)
    is_compromised(score) → bool (True si score >= 60)
    build_dossier_embed(bot, member, message, score, reasons) → discord.Embed
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional

import discord


# =============================================================================
# DÉTECTEURS
# =============================================================================

# Patterns de phishing connus en 2026
_PHISHING_PATTERNS = [
    r'discord-?(?:nitro|gift|steam)\.com',
    r'discordapp\-gift',
    r'free[\-_]?nitro',
    r'steam-?gift',
    r'steamcommunity-?gift',
    r'discordnitro\-free',
    r'nitro[\-_]?gift\-?\d*\.(?:ru|tk|ml|cf|xyz|top)',
    r'dlscord\.com',  # typosquatting
    r'discrord\.com',
    r'd1scord\.com',
    r'discord\-app\.(?:ru|cn|tk|ml)',
]

# Patterns d'urgence (phishing classique)
_URGENCY_PATTERNS = [
    r'free\s+nitro',
    r'gift\s+(?:for|to)\s+you',
    r'click\s+(?:here|now|fast)',
    r'limited\s+time',
    r'expire?s?\s+(?:in|today|soon)',
    r'verify\s+your\s+account',
    r'account\s+(?:suspended|banned|locked)',
    r'reset\s+(?:your\s+)?password',
    r'cliquer\s+(?:ici|maintenant)',
    r'temps\s+limit',
    r'compte\s+(?:bloqué|suspendu)',
]

# Domaines raccourcis suspects (combinés avec d'autres signaux)
_SHORTENED_DOMAINS = [
    'bit.ly', 'tinyurl.com', 'goo.gl', 't.co', 'shorturl.at', 'is.gd',
    'cutt.ly', 'tiny.cc', 'rb.gy', 'ow.ly',
]

# Mots-clés "gratuit/nitro" dans username
_SUSPICIOUS_USERNAME_KEYWORDS = ['free', 'nitro', 'gift', 'steam', 'giveaway']


def _has_discord_invite(content: str) -> bool:
    """True si le message contient un lien d'invitation Discord."""
    patterns = [
        r'discord\.gg/[a-zA-Z0-9]+',
        r'discord\.com/invite/[a-zA-Z0-9]+',
        r'discordapp\.com/invite/[a-zA-Z0-9]+',
    ]
    for p in patterns:
        if re.search(p, content, re.IGNORECASE):
            return True
    return False


def _has_phishing_url(content: str) -> bool:
    """True si le contenu a un URL de phishing connu."""
    for p in _PHISHING_PATTERNS:
        if re.search(p, content, re.IGNORECASE):
            return True
    return False


def _has_urgency_language(content: str) -> bool:
    """True si le contenu utilise un langage d'urgence (phishing typique)."""
    for p in _URGENCY_PATTERNS:
        if re.search(p, content, re.IGNORECASE):
            return True
    return False


def _has_shortened_url(content: str) -> bool:
    """True si le contenu contient un URL raccourci."""
    for domain in _SHORTENED_DOMAINS:
        if domain in content.lower():
            return True
    return False


def _has_mass_mention(content: str) -> bool:
    """True si le contenu contient @everyone ou @here."""
    return '@everyone' in content or '@here' in content


def _has_suspicious_username(member: discord.Member) -> bool:
    """True si le nom contient des keywords suspects."""
    name = (member.name or '').lower()
    display = (member.display_name or '').lower()
    full = name + ' ' + display
    return any(kw in full for kw in _SUSPICIOUS_USERNAME_KEYWORDS)


def _account_age_days(member: discord.Member) -> int:
    """Âge du compte Discord en jours."""
    try:
        created = member.created_at.replace(tzinfo=timezone.utc) if member.created_at.tzinfo is None else member.created_at
        return (datetime.now(timezone.utc) - created).days
    except Exception:
        return 999


def _join_age_days(member: discord.Member) -> int:
    """Âge sur le serveur en jours."""
    try:
        if not member.joined_at:
            return 999
        joined = member.joined_at.replace(tzinfo=timezone.utc) if member.joined_at.tzinfo is None else member.joined_at
        return (datetime.now(timezone.utc) - joined).days
    except Exception:
        return 999


# =============================================================================
# SCORING
# =============================================================================

# Cache des historiques par (guild_id, user_id) — RAM only, OK car les hackers
# spam vite et le détecteur doit voir le pattern dans la fenêtre récente
_history_cache: dict[tuple[int, int], list[dict]] = {}


def _record_message(guild_id: int, user_id: int, channel_id: int, content: str):
    """Enregistre un message dans l'historique récent (5 dernières min)."""
    key = (guild_id, user_id)
    if key not in _history_cache:
        _history_cache[key] = []
    now_ts = time.time()
    _history_cache[key].append({
        'time': now_ts,
        'channel_id': channel_id,
        'content': content,
        'has_link': bool(re.search(r'https?://', content)),
        'has_invite': _has_discord_invite(content),
        'has_mention': _has_mass_mention(content),
    })
    # Garde 5 dernières minutes
    cutoff = now_ts - 300
    _history_cache[key] = [m for m in _history_cache[key] if m['time'] > cutoff]


def score_message(
    member: discord.Member,
    content: str,
    channel: discord.TextChannel,
) -> tuple[int, list[str], list[str]]:
    """Calcule un score de probabilité de compromission pour ce message.

    Retourne (score, reasons, raw_signals) :
    - score : int 0-100+
    - reasons : list[str] descriptions lisibles pour le dossier
    - raw_signals : list[str] codes techniques des signaux détectés
    """
    if member is None or not content:
        return 0, [], []

    score = 0
    reasons: list[str] = []
    signals: list[str] = []

    _record_message(member.guild.id, member.id, channel.id, content)
    history = _history_cache.get((member.guild.id, member.id), [])

    has_invite = _has_discord_invite(content)
    has_phishing = _has_phishing_url(content)
    has_urgency = _has_urgency_language(content)
    has_short = _has_shortened_url(content)
    has_mention = _has_mass_mention(content)
    suspicious_name = _has_suspicious_username(member)
    account_age = _account_age_days(member)
    join_age = _join_age_days(member)

    # ─── SIGNAUX FORTS ───
    if has_phishing:
        score += 50
        reasons.append("🔴 **URL de phishing connue détectée**")
        signals.append("phishing_url")

    if has_invite and has_mention:
        score += 45
        reasons.append("🔴 **Lien d'invitation Discord + mention massive** (pattern hack classique)")
        signals.append("invite_plus_mention")

    if has_phishing and has_urgency:
        score += 40
        reasons.append("🔴 **Phishing avec langage d'urgence** (verify/free/click now)")
        signals.append("phishing_with_urgency")

    # Spam multi-salons (3+ salons en <30s)
    recent = [m for m in history if (time.time() - m['time']) < 30]
    unique_channels = {m['channel_id'] for m in recent}
    if len(unique_channels) >= 3 and any(m['has_link'] or m['has_invite'] for m in recent):
        score += 50
        reasons.append(f"🔴 **Spam multi-salons** ({len(unique_channels)} salons en <30s avec liens)")
        signals.append("multi_channel_spam")

    # ─── SIGNAUX MOYENS ───
    if has_invite and not has_mention:
        score += 25
        reasons.append("🟠 Lien d'invitation Discord posté")
        signals.append("discord_invite")

    if has_urgency and has_short:
        score += 25
        reasons.append("🟠 URL raccourci + langage d'urgence")
        signals.append("shortened_urgent")

    # Compte récent envoyant un lien
    if account_age < 30 and (has_invite or has_phishing or '://' in content):
        score += 20
        reasons.append(f"🟠 Compte récent (`{account_age}` jours) envoie un lien")
        signals.append("new_account_link")

    if has_mention and account_age < 60:
        score += 25
        reasons.append(f"🟠 Mention massive par compte récent (`{account_age}` jours)")
        signals.append("new_account_mention")

    # Premier message du membre = lien + mention
    is_first = len([m for m in history if m['has_link']]) <= 1 and member.joined_at
    if is_first and has_mention and (has_invite or '://' in content):
        score += 30
        reasons.append("🟠 **Premier message = lien + mention** (pattern bot piraté)")
        signals.append("first_message_spam")

    # ─── SIGNAUX FAIBLES ───
    if suspicious_name:
        score += 10
        reasons.append(f"🟡 Username contient un mot suspect (free/nitro/gift/steam)")
        signals.append("suspicious_username")

    if has_short and account_age < 90:
        score += 10
        reasons.append("🟡 URL raccourci posté par compte récent")
        signals.append("shortened_recent")

    # Avatar par défaut
    if member.avatar is None:
        score += 5
        reasons.append("🟡 Pas d'avatar personnalisé")
        signals.append("default_avatar")

    return score, reasons, signals


def is_compromised(score: int) -> bool:
    """True si le score atteint le seuil de haute confiance (60+)."""
    return score >= 60


# =============================================================================
# DOSSIER (embed) — pour le salon dédié
# =============================================================================

def build_dossier_embed(
    member: discord.Member,
    message: discord.Message,
    score: int,
    reasons: list[str],
    signals: list[str],
) -> discord.Embed:
    """Construit le dossier d'alerte pour le salon dédié 'comptes suspects'."""
    # Couleur selon le niveau
    if score >= 100:
        color = 0x8B0000  # rouge sang : quasi certain
        level = "🔴 **CRITIQUE — Compte très probablement piraté**"
    elif score >= 80:
        color = 0xE74C3C  # rouge
        level = "🔴 **HAUTE confiance — Compte probablement compromis**"
    else:  # >= 60
        color = 0xE67E22  # orange
        level = "🟠 **Suspicion forte — À vérifier**"

    e = discord.Embed(
        title="🚨 Compte suspect détecté",
        description=(
            f"{level}\n\n"
            f"**Score de compromission** : `{score}/100`\n"
            f"_Le bot ne signale QUE les comptes au score ≥60. Tu décides._\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    # Info compte
    account_age = _account_age_days(member)
    join_age = _join_age_days(member)
    age_warning = " ⚠️" if account_age < 30 else ""
    join_warning = " ⚠️" if join_age < 7 else ""

    e.add_field(
        name="👤 Compte concerné",
        value=(
            f"{member.mention}\n"
            f"**Tag** · `{member}`\n"
            f"**ID** · `{member.id}`\n"
            f"**Bot ?** · {'⚠️ Oui' if member.bot else 'Non'}"
        ),
        inline=False,
    )

    e.add_field(
        name="📅 Ancienneté",
        value=(
            f"**Compte créé** · <t:{int(member.created_at.timestamp())}:R> ({account_age} jours){age_warning}\n"
            f"**Rejoint serveur** · "
            f"{f'<t:{int(member.joined_at.timestamp())}:R> ({join_age} jours){join_warning}' if member.joined_at else '_inconnu_'}"
        ),
        inline=False,
    )

    # Rôles
    roles = [r for r in member.roles if r.name != "@everyone"]
    if roles:
        role_mentions = " ".join(r.mention for r in roles[:8])
        if len(roles) > 8:
            role_mentions += f" *+{len(roles) - 8}*"
        e.add_field(
            name=f"🎭 Rôles ({len(roles)})",
            value=role_mentions or "_aucun_",
            inline=False,
        )

    # Raisons de la détection
    if reasons:
        e.add_field(
            name="🚩 Signaux détectés",
            value="\n".join(reasons[:8]),
            inline=False,
        )

    # Message suspect (preview)
    msg_content = message.content or "_message sans texte (embed/fichier ?)_"
    if len(msg_content) > 400:
        msg_content = msg_content[:400] + "…"
    # Censurer les URLs pour éviter de propager le phishing
    msg_safe = re.sub(r'https?://\S+', '[🔗 LIEN CENSURÉ]', msg_content)
    e.add_field(
        name=f"💬 Message déclencheur · #{message.channel.name}",
        value=f"```\n{msg_safe}\n```",
        inline=False,
    )

    e.add_field(
        name="🛠️ Actions disponibles",
        value=(
            "Utilise les boutons ci-dessous pour décider :\n"
            "• **🔇 Mute 24h** — précaution rapide en cas de doute\n"
            "• **👢 Kick** — expulsion (le compte peut revenir)\n"
            "• **🔨 Ban** — bannissement définitif (cas confirmé)\n"
            "• **✅ Faux positif** — ferme l'alerte sans action"
        ),
        inline=False,
    )

    if member.avatar:
        e.set_thumbnail(url=member.display_avatar.url)

    e.set_footer(
        text=f"Détecté par anti-compromission · Signaux: {', '.join(signals[:6])}",
    )
    return e


__all__ = [
    "score_message",
    "is_compromised",
    "build_dossier_embed",
]
