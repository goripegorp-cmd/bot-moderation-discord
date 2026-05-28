"""
token_grabber.py — Scanner anti-token-grabber 2026 (Phase 147).

🎯 OBJECTIF : intercepter les URLs de phishing AVANT que les utilisateurs
ne cliquent. Les attaques 2026 les plus courantes :

1. **Typosquatting Discord** : di5cord.com, discrod.gg, discordhq.com,
   dlscord-app.net, dlscord.com, discord-nitro.gift, dlscord-gift.com,
   etc. → page fake "claim ton nitro" qui demande le login.

2. **GitHub Gist / Pastebin avec code Python** : "lance ce script pour
   débloquer un cheat", exfiltre les tokens depuis %LOCALAPPDATA%.

3. **URLs raccourcies** (bit.ly, tinyurl, cutt.ly) qui pointent vers du
   phishing → on bloque celles combinées à un keyword urgent.

4. **Fake "free nitro / gift / claim"** sur domains non-officiels.

Stratégie :
- Hook `on_message` ULTRA-précoce (avant tout autre traitement).
- Scan le content + les embeds (pour les copy-paste de tweets/messages).
- Si match → delete + DM author + send au salon staff sanction.
- Multi-récidive (2× en 24h) → auto-mute 1h + alerte staff.

DB tables :
- phishing_log (id PK, guild_id, user_id, content_excerpt, url_matched,
                detected_at, action_taken)
- phishing_offender (guild_id, user_id PK, hits_24h, last_hit_at)

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, staff_sanction=None)
- scan_message(message) -> dict avec {matched_urls, reason, severity}
- on_message_hook(message) -> bool (True si action a été prise)

⚠️ RULES.md : pas de ban auto. Auto-mute max 1h + alerte staff via
le module staff_sanction.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_staff_sanction = None  # module staff_sanction (Phase 147)


# ─── Catalogue des patterns (mis à jour Phase 147 — mai 2026) ──────────────

# Domains imitateurs de Discord (typosquatting)
PHISHING_DOMAINS = {
    # Typosquatting Discord
    "di5cord.com", "discrod.gg", "discrod.com", "discordhq.com",
    "discordd.com", "discrord.com", "dlscord.com", "dlscord-app.net",
    "dlscord-gift.com", "discord-app.com", "discord-nitro.com",
    "discord-nitro.gift", "discord-nitros.com", "dicord.com",
    "discord-gift.com", "discordgift.io", "discordgift.ru",
    "steamcommunlty.com", "stearmcommunity.com",  # crypto-related
    "discordapp.io", "discordapp.ru", "discord-gifts.com",
    "discord-nitro-gift.com", "discordgive.com", "steamcommumity.com",
    "discordsapp.com", "dlscordapp.com", "dlscord-app.com",
}

# Phrases / mots-clés à scorer
PHISHING_KEYWORDS = [
    # FR
    "nitro gratuit", "nitro offert", "claim ton cadeau",
    "vérifie ton compte", "ton compte va etre supprime",
    "récompense exclusive", "100 nitros gratuits",
    "abonnement nitro gratuit", "récupère ton nitro",
    # EN (utilisé par scammers FR aussi)
    "free nitro", "claim your gift", "claim your nitro",
    "verify your account", "free discord", "free skin",
    "free robux", "1 year nitro", "3 months nitro",
    # Urgence
    "dans 24h sinon", "dépêche-toi", "limited time", "expires soon",
    "act fast", "click before",
]

# Phrases courantes des token grabbers Python
GRABBER_CODE_PATTERNS = [
    r"requests\.post\s*\(",
    r"webhook\.send",
    r"os\.environ.*?(?:DISCORD|TOKEN)",
    r"%LOCALAPPDATA%[\\/]Discord",
    r"leveldb",
    r"discord_desktop_core",
    r"Local Storage[\\/]leveldb",
    r"import\s+win32crypt",
    r"CryptUnprotectData",
    # Patterns plus génériques de RAT
    r"socket\.connect\s*\(",
    r"subprocess\.(?:Popen|run|call)\s*\(",
    r"base64\.b64decode\s*\(",
    r"exec\s*\(\s*(?:base64|bytes|requests)",
]
_RX_GRABBER_CODE = re.compile(
    "|".join(GRABBER_CODE_PATTERNS), re.IGNORECASE | re.MULTILINE
)

# Détection URLs raccourcies (bit.ly etc) — combinées avec keywords = suspect
SHORTENER_DOMAINS = {
    "bit.ly", "tinyurl.com", "cutt.ly", "t.co", "is.gd", "v.gd",
    "shorturl.at", "rebrand.ly", "ow.ly", "buff.ly", "rb.gy",
    "tiny.cc", "soo.gd", "lnkd.in", "linktr.ee",
}

# Code-hosts à scruter (pastebin/gist)
CODE_HOSTS = {
    "pastebin.com", "paste.ee", "rentry.co", "rentry.org",
    "justpaste.it", "ghostbin.com", "hastebin.com",
    "gist.github.com", "controlc.com", "txt.fyi", "0bin.net",
    "privatebin.net",
}

# Domains FR connus pour scams crypto / phishing
SCAM_TLDS_KEYWORDS = re.compile(
    r"https?://[^/\s]*?(?:nitro|gift|claim|free|reward|prize|win|airdrop)"
    r"[^/\s]*?\.(?:ru|xyz|tk|ml|ga|cf|click|top|gq|info|live|site|online|space)",
    re.IGNORECASE,
)

# Pattern URL générique
_RX_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"\)`]+",
    re.IGNORECASE,
)


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    staff_sanction_module=None,
):
    """Configure le module."""
    global _bot, _get_db, _db_get, _v2, _staff_sanction
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _staff_sanction = staff_sanction_module


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS phishing_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    content_excerpt TEXT,
                    url_matched TEXT,
                    reason TEXT,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    action_taken TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS phishing_offender (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    hits_24h INTEGER DEFAULT 0,
                    last_hit_at TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_phishing_log_user "
                "ON phishing_log(guild_id, user_id, detected_at)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[token_grabber init_db] {ex}")


# ─── Scan engine ────────────────────────────────────────────────────────────

def _extract_urls(text: str) -> list[str]:
    """Liste les URLs du texte."""
    if not text:
        return []
    out = []
    for m in _RX_URL.finditer(text):
        url = m.group(0).rstrip(".,;:!?)>]")
        out.append(url)
    return out


def _domain_of(url: str) -> str:
    """Extrait le domain d'une URL (lowercase)."""
    try:
        u = url.lower()
        if u.startswith("http://"):
            u = u[7:]
        elif u.startswith("https://"):
            u = u[8:]
        if u.startswith("www."):
            u = u[4:]
        # Coupe au premier /, ?, #
        for c in ("/", "?", "#"):
            i = u.find(c)
            if i != -1:
                u = u[:i]
        return u
    except Exception:
        return ""


def scan_message(content: str, attachments: list = None) -> dict:
    """Analyse un message. Renvoie dict avec :
    - matched_urls: liste d'URLs suspectes
    - reason: str raison principale
    - severity: 'low' / 'medium' / 'high'
    - has_grabber_code: bool
    """
    out = {
        "matched_urls": [],
        "reason": "",
        "severity": "low",
        "has_grabber_code": False,
    }
    if not content:
        return out
    text = content.lower()

    # 1) Domains de phishing connus
    urls = _extract_urls(content)
    for url in urls:
        d = _domain_of(url)
        if d in PHISHING_DOMAINS:
            out["matched_urls"].append(url)
            out["reason"] = f"Domain typosquatting Discord détecté : `{d}`"
            out["severity"] = "high"
            return out

    # 2) Scam TLDs + keyword
    if SCAM_TLDS_KEYWORDS.search(content):
        m = SCAM_TLDS_KEYWORDS.search(content)
        out["matched_urls"].append(m.group(0))
        out["reason"] = "URL avec TLD scam-friendly + keyword phishing"
        out["severity"] = "high"
        return out

    # 3) Code grabber Python
    if _RX_GRABBER_CODE.search(content):
        out["has_grabber_code"] = True
        out["reason"] = "Code Python suspect (token grabber / RAT pattern)"
        out["severity"] = "high"
        return out

    # 4) Code-host + keyword phishing
    for url in urls:
        d = _domain_of(url)
        if d in CODE_HOSTS:
            # Code-host seul = pas suffisant, mais + keyword = suspect
            for kw in PHISHING_KEYWORDS:
                if kw.lower() in text:
                    out["matched_urls"].append(url)
                    out["reason"] = (
                        f"Code-host `{d}` + keyword phishing `{kw}`"
                    )
                    out["severity"] = "high"
                    return out

    # 5) URL shortener + keyword phishing
    for url in urls:
        d = _domain_of(url)
        if d in SHORTENER_DOMAINS:
            for kw in PHISHING_KEYWORDS:
                if kw.lower() in text:
                    out["matched_urls"].append(url)
                    out["reason"] = (
                        f"URL raccourcie `{d}` + keyword phishing `{kw}`"
                    )
                    out["severity"] = "medium"
                    return out

    # 6) Keywords seuls (suspicion légère, log mais pas d'action)
    kw_hits = sum(1 for kw in PHISHING_KEYWORDS if kw.lower() in text)
    if kw_hits >= 2:
        out["reason"] = f"Combinaison suspecte de {kw_hits} keywords phishing"
        out["severity"] = "low"

    return out


# ─── Action handler ─────────────────────────────────────────────────────────

async def on_message_hook(message: discord.Message) -> bool:
    """Hook depuis bot.py on_message. Retourne True si action a été prise."""
    if not message.guild or message.author.bot:
        return False
    if _get_db is None:
        return False
    try:
        result = scan_message(message.content or "")
        if result["severity"] not in ("high", "medium"):
            return False

        # Action : delete message
        deleted = False
        try:
            await message.delete()
            deleted = True
        except Exception:
            pass

        # Log DB
        url_str = ",".join(result["matched_urls"][:3])
        excerpt = (message.content or "")[:280]
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO phishing_log "
                "(guild_id, user_id, content_excerpt, url_matched, "
                "reason, action_taken) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message.guild.id, message.author.id,
                    excerpt, url_str, result["reason"],
                    "deleted" if deleted else "detected_only",
                ),
            )

            # Update offender count
            await db.execute(
                "INSERT INTO phishing_offender (guild_id, user_id, hits_24h, "
                "last_hit_at) VALUES (?, ?, 1, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "hits_24h = hits_24h + 1, last_hit_at = CURRENT_TIMESTAMP",
                (message.guild.id, message.author.id),
            )
            await db.commit()

            # Check récidive
            async with db.execute(
                "SELECT hits_24h FROM phishing_offender "
                "WHERE guild_id=? AND user_id=? "
                "AND last_hit_at >= datetime('now', '-1 day')",
                (message.guild.id, message.author.id),
            ) as cur:
                row = await cur.fetchone()
            hits = int(row[0] if row else 1)

        # DM author (peut-être compte piraté qui ne sait pas)
        try:
            dm_text = (
                f"⚠️ **{message.guild.name}** — Ton message a été supprimé.\n\n"
                f"**Raison détectée :** {result['reason']}\n\n"
                f"Si **tu n'as pas envoyé** ce message, ton compte est "
                f"peut-être compromis :\n"
                f"1. Change immédiatement ton mot de passe Discord\n"
                f"2. Active la 2FA (Settings → My Account → Two-Factor)\n"
                f"3. Déconnecte les sessions inconnues "
                f"(Settings → Devices)\n\n"
                f"_Aucune sanction automatique appliquée. Le staff va review._"
            )
            await message.author.send(dm_text)
        except Exception:
            pass

        # Notifier staff via staff_sanction module
        if _staff_sanction is not None:
            try:
                auto_mute_duration = 0
                if hits >= 2:
                    # Récidive → mute auto 1h
                    auto_mute_duration = 60
                    try:
                        from datetime import timedelta as _td
                        until = (datetime.now(timezone.utc)
                                 + _td(minutes=60))
                        await message.author.timeout(
                            until, reason="Phishing récidive auto-mute"
                        )
                    except Exception as ex:
                        print(f"[token_grabber auto-mute] {ex}")

                await _staff_sanction.create_sanction_panel(
                    guild=message.guild,
                    target=message.author,
                    reason=result["reason"],
                    evidence_text=excerpt,
                    evidence_channel_id=message.channel.id,
                    auto_action_taken=(
                        f"Message supprimé + mute 60min (récidive {hits}×)"
                        if auto_mute_duration > 0 else
                        "Message supprimé"
                    ),
                    source="token_grabber",
                )
            except Exception as ex:
                print(f"[token_grabber notify staff] {ex}")

        return True
    except Exception as ex:
        print(f"[token_grabber on_message_hook] {ex}")
        return False


__all__ = [
    "setup",
    "init_db",
    "scan_message",
    "on_message_hook",
    "PHISHING_DOMAINS",
    "PHISHING_KEYWORDS",
]
