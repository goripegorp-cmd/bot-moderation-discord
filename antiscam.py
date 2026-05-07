"""
antiscam.py - Detection unifiee anti-arnaques (Phase 1.6).

Fusionne la detection :
    - phishing (faux Discord/Steam/Roblox/PayPal/...)
    - scam (free nitro, free robux, airdrops bidons)
    - liens compromis (typosquats, raccourcisseurs suspects, IPs nues)
    - codes QR (interface preparee, implementation OCR optionnelle)

L'idee : le module retourne une **analyse** (confidence + evidence). C'est
ensuite `protection_guards.decide_action(...)` qui decide quoi en faire (en
tenant compte du trust score, des whitelists, du soft mode, etc.).

Cela elimine le risque de bans aleatoires :
    - Un giveaway legitime (`🎁 GIVEAWAY 🎁`) peut atteindre confidence=0.7,
      mais protection_guards le whiteliste sur le pattern -> LOG only.
    - Un veteran qui poste un faux nitro voit son ban downgrade a kick par
      le trust boost.

API:
    analyze_message(text) -> ScamAnalysis
    extract_urls(text)    -> list[str]
    domain_of(url)        -> str
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from protection_guards import Action, AutoEventType, DetectionEvent


# =============================================================================
# REGEXES & PATTERNS
# =============================================================================

URL_RE = re.compile(
    r"(?:https?://|www\.)[\w\-._~:/?#\[\]@!$&'()*+,;=%]+",
    re.IGNORECASE,
)

# IPv4 nu (souvent suspect)
IP_URL_RE = re.compile(r"https?://(?:\d{1,3}\.){3}\d{1,3}", re.IGNORECASE)

# Raccourcisseurs courants (souvent legit, mais peuvent masquer scam)
URL_SHORTENERS = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd",
    "buff.ly", "rebrand.ly", "shorte.st", "adf.ly", "cutt.ly",
}

# Mots-cles de scam (signaux faibles : 1 mot = pas grand chose, plusieurs = suspect)
SCAM_KEYWORDS = [
    # Free X
    "free nitro", "free discord nitro", "nitro free",
    "free robux", "free vbucks", "free skins", "free gems",
    "free csgo", "free steam", "free bitcoin", "free ethereum",
    # Claim / Airdrop
    "claim your", "claim now", "airdrop", "limited offer",
    "exclusive offer", "instant payout",
    # Verify scam
    "verify your account", "verify discord", "verify age",
    "click to verify", "captcha verification",
    # Auth-required scam
    "login to claim", "log in to receive", "authenticate to",
    # Crypto trap
    "send 0.1 eth", "double your crypto", "x2 crypto",
    "binance gift", "metamask reward",
    # Token grab
    "discord token", "steal token", "grab account",
    # Roblox specific
    "free robux generator", "robux glitch", "infinite robux",
]

# Typosquats Discord/Steam/Roblox (bot.py en a deja une liste, on la reflete ici)
PHISHING_DOMAINS_BUILTIN = {
    # Discord
    "discord-gift.com", "discord-nitro.gift", "discordgift.site",
    "discordnitro.com", "dlscord.com", "dlscord.gift",
    "discorcl.com", "discrod.com", "discordc.com",
    "discord-app.com", "discordapp.gift", "discord.gift",
    "discord-airdrop.com", "discordn.com", "discordi.com",
    "discord-claim.com", "discordnitros.com",
    "dlscord-nitro.com", "discordd.gift", "disc0rd.gift",
    "disc0rd-nitro.com", "discorid.gift", "discordl.com",
    "discord-free.com", "discordgiveaway.com",
    "discord-verify.com", "discordlogin.net", "d1scord.com",
    "discord-verify.net", "discordapp-gifts.com",
    "discordapp-nitro.com", "discordfree-nitro.com",
    "discord-login.com", "discord-login.net",
    "discord-safeguard.com", "discord-age-verify.com",
    "discord-verify-age.com", "verify-discord.com",
    "steam-discord.com", "discord-security.com",
    "discord-captcha.com",
    # Steam
    "steamcomminuty.com", "steampowored.com", "steamcommunlty.com",
    "steancommunity.com", "store-steampowered.com",
    "steamcommunity.ru.com", "steamcommunitv.com",
    "steamcommunity-login.com", "steam-guard.com",
    "steamguard-code.com", "1steam.xyz", "2-csgo.com",
    # Roblox
    "0www-roblox.com", "1-robiox.website", "1-roblox.info",
    "1robiox1.xyz", "1roblofx.com",
    # Crypto
    "free-ethereum.com", "free-bitcoin.gift", "crypto-airdrop.com",
    "nft-free.com", "opensea-drop.com", "metamask-airdrop.com",
    "eth-giveaway.com", "0x1trade.com", "1000usdc.net",
    "1000usdc.top", "2000usdt.top",
    # Token grabbers
    "18nsfw-verification.xyz", "1captcha.site",
    # Faux services
    "paypal-verify.com", "amazon-gift.com", "netflix-free.com",
    "spotify-premium.gift",
}

# TLD a forte densite scam (signaux faibles, jamais bloquant seul)
SUSPICIOUS_TLDS = {
    ".gift", ".click", ".loan", ".work", ".help", ".support",
    ".click", ".country", ".click", ".gq", ".ml", ".cf", ".tk",
}


# =============================================================================
# MODELES
# =============================================================================

@dataclass
class ScamAnalysis:
    """Resultat d'une analyse anti-arnaques."""

    is_threat: bool                   # True si confidence > seuil (defaut 0.3)
    confidence: float                 # 0.0 a 1.0
    event_type: AutoEventType
    evidence: list[str] = field(default_factory=list)
    matched_urls: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    suggested_action: Action = Action.LOG

    def to_event(self, raw_content: str) -> DetectionEvent:
        """Convertit l'analyse en DetectionEvent pour protection_guards."""
        return DetectionEvent(
            event_type=self.event_type,
            confidence=self.confidence,
            evidence=self.evidence,
            raw_content=raw_content,
        )


# =============================================================================
# UTILITAIRES URL
# =============================================================================

def extract_urls(text: str) -> list[str]:
    """Extrait toutes les URLs d'un texte (raccourcies ou pleines)."""
    if not text:
        return []
    return URL_RE.findall(text)


def domain_of(url: str) -> str:
    """Retourne le domaine (sans www) d'une URL."""
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        # On enleve un eventuel port
        if ":" in host:
            host = host.split(":", 1)[0]
        return host
    except Exception:
        return ""


def is_known_phishing_domain(domain: str, extra_list: Optional[set[str]] = None) -> bool:
    """True si le domaine est dans la liste des phishing connus."""
    if not domain:
        return False
    haystack = PHISHING_DOMAINS_BUILTIN | (extra_list or set())
    return domain in haystack or any(domain.endswith("." + d) for d in haystack)


def is_url_shortener(domain: str) -> bool:
    return domain in URL_SHORTENERS


def is_suspicious_tld(domain: str) -> bool:
    return any(domain.endswith(tld) for tld in SUSPICIOUS_TLDS)


def is_ip_url(url: str) -> bool:
    return bool(IP_URL_RE.match(url))


def has_suspicious_lookalike(domain: str) -> bool:
    """Detecte des typosquats simples (zero a la place de o, l au lieu de i)."""
    if not domain:
        return False
    suspicious = (
        ("d1scord" in domain) or
        ("dlscord" in domain) or
        ("disc0rd" in domain) or
        ("steamcomm" in domain and "steamcommunity.com" not in domain) or
        ("rob1ox" in domain) or
        ("robiox" in domain) or
        ("paypa1" in domain) or
        ("amaz0n" in domain) or
        ("g00gle" in domain) or
        ("microsft" in domain)
    )
    return suspicious


# =============================================================================
# DETECTION DE MOTS-CLES
# =============================================================================

def find_scam_keywords(text: str) -> list[str]:
    """Retourne la liste des mots-cles scam matches (en lower)."""
    if not text:
        return []
    lower = text.lower()
    return [kw for kw in SCAM_KEYWORDS if kw in lower]


# =============================================================================
# ANALYSE PRINCIPALE
# =============================================================================

THREAT_THRESHOLD = 0.3


async def analyze_message(
    text: str,
    *,
    extra_phishing_domains: Optional[set[str]] = None,
) -> ScamAnalysis:
    """Analyse un texte et retourne une evaluation du risque scam.

    Strategie de scoring :
    - Domaine phishing connu       : +0.85 confidence + flag PHISHING
    - Lookalike typosquat          : +0.6
    - URL avec IP nue              : +0.4
    - Raccourcisseur                : +0.15 (signal faible, contextuel)
    - TLD suspect                  : +0.1 (signal faible)
    - Mot-cle scam isole           : +0.15 chaque (capped a 0.6)
    - Combo (URL + keyword scam)   : +0.2 bonus

    Confidence finale : min(1.0, somme).
    """
    evidence: list[str] = []
    confidence = 0.0
    event_type = AutoEventType.SCAM
    matched_urls: list[str] = []
    matched_keywords: list[str] = []

    # 1. Extraction URLs
    urls = extract_urls(text)
    has_phishing_domain = False
    has_suspicious_url = False

    for raw_url in urls:
        domain = domain_of(raw_url)
        if not domain:
            continue
        matched_urls.append(raw_url)

        if is_known_phishing_domain(domain, extra_phishing_domains):
            confidence += 0.85
            evidence.append(f"Domaine phishing connu : {domain}")
            event_type = AutoEventType.PHISHING
            has_phishing_domain = True
        elif has_suspicious_lookalike(domain):
            confidence += 0.6
            evidence.append(f"Typosquat suspect : {domain}")
            event_type = AutoEventType.PHISHING
            has_suspicious_url = True
        elif is_ip_url(raw_url):
            confidence += 0.4
            evidence.append(f"URL avec IP nue : {raw_url}")
            has_suspicious_url = True
        else:
            if is_url_shortener(domain):
                confidence += 0.15
                evidence.append(f"Raccourcisseur d'URL : {domain}")
                has_suspicious_url = True
            if is_suspicious_tld(domain):
                confidence += 0.1
                evidence.append(f"TLD suspect : {domain}")
                has_suspicious_url = True

    # 2. Keywords scam
    keywords = find_scam_keywords(text)
    if keywords:
        matched_keywords = keywords
        kw_score = min(len(keywords) * 0.15, 0.6)
        confidence += kw_score
        evidence.append(f"Mots-cles scam : {', '.join(keywords[:3])}{'...' if len(keywords) > 3 else ''}")

    # 3. Combo URL + keywords (signal fort)
    if matched_keywords and matched_urls and not has_phishing_domain:
        confidence += 0.2
        evidence.append("Combo URL + mots-cles scam")

    # 4. Cap final
    confidence = min(1.0, max(0.0, confidence))
    is_threat = confidence >= THREAT_THRESHOLD

    # 5. Action suggeree par confidence (purement indicative,
    #    `protection_guards.decide_action` est le decideur final)
    if confidence >= 0.85:
        suggested = Action.BAN
    elif confidence >= 0.7:
        suggested = Action.KICK
    elif confidence >= 0.5:
        suggested = Action.TEMPMUTE
    elif confidence >= 0.3:
        suggested = Action.MUTE
    elif confidence > 0.0:
        suggested = Action.WARN
    else:
        suggested = Action.LOG

    return ScamAnalysis(
        is_threat=is_threat,
        confidence=confidence,
        event_type=event_type,
        evidence=evidence,
        matched_urls=matched_urls,
        matched_keywords=matched_keywords,
        suggested_action=suggested,
    )


# =============================================================================
# AIDE A LA DECISION (intégration avec protection_guards)
# =============================================================================

async def evaluate_and_decide(
    text: str,
    guild_id: int,
    member_context,
    *,
    extra_phishing_domains: Optional[set[str]] = None,
):
    """Pipeline complet : analyse + decision.

    Retourne (analysis, decision) ou (analysis, None) si pas de threat.

    Usage cote bot :
        ctx = MemberContext(...)
        analysis, decision = await evaluate_and_decide(msg.content, msg.guild.id, ctx)
        if decision and decision.final_action != Action.LOG:
            # appliquer decision.final_action
    """
    from protection_guards import decide_action

    analysis = await analyze_message(text, extra_phishing_domains=extra_phishing_domains)
    if not analysis.is_threat:
        return analysis, None

    decision = await decide_action(
        guild_id=guild_id,
        member=member_context,
        event=analysis.to_event(text),
        proposed_action=analysis.suggested_action,
    )
    return analysis, decision


__all__ = [
    "URL_RE",
    "IP_URL_RE",
    "URL_SHORTENERS",
    "SCAM_KEYWORDS",
    "PHISHING_DOMAINS_BUILTIN",
    "SUSPICIOUS_TLDS",
    "ScamAnalysis",
    "extract_urls",
    "domain_of",
    "is_known_phishing_domain",
    "is_url_shortener",
    "is_suspicious_tld",
    "is_ip_url",
    "has_suspicious_lookalike",
    "find_scam_keywords",
    "analyze_message",
    "evaluate_and_decide",
    "THREAT_THRESHOLD",
]
