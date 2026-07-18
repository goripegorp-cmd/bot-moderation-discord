"""
social_media.py - Tracker des reseaux sociaux (Phase 1.2 du redesign 2026).

Permet a l'owner de tracker des comptes externes (Twitch lives, YouTube videos,
TikTok, Twitter/X, Instagram, Kick) et d'annoncer les nouvelles publications
dans des salons Discord designes.

Garanties (specs owner) :
- AUCUN doublon : chaque post a un ID unique, on n'annonce qu'une seule fois
- AUTO-CLEANUP : si un post disparait de la source, l'annonce Discord est supprimee
- OPTIMISE : polling intelligent, cache, sessions HTTP partagees, batch API
- EXTERNE-FRIENDLY : pas de dependance OS, JSON-only persistence, env vars

Architecture :
- Platform                : enum des plateformes
- SocialPost              : un post recupere depuis une plateforme
- Subscription            : "ce serveur veut tracker tel compte dans tel salon"
- Announcement            : trace d'une annonce postee (couple sub_id+post_id)
- PlatformAdapter (ABC)   : interface adapter
- TwitchAdapter / YouTubeAdapter / ManualAdapter : implementations
- SocialMediaManager      : orchestration (subs, anns, polling, cleanup)

Hooks Discord (a fournir par bot.py au demarrage) :
- post_callback(subscription, post) -> Optional[int]  # retourne le message_id
- delete_callback(announcement) -> bool               # retourne True si OK

Variables d'environnement :
- TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET (optionnel)
- YOUTUBE_API_KEY                          (optionnel)

Sans ces variables, les plateformes correspondantes acceptent uniquement le
mode manuel (l'owner publie a la main, le bot tracke et auto-clean).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


# =============================================================================
# ENUMS & METADATA
# =============================================================================

class Platform(str, Enum):
    TWITCH = "twitch"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    KICK = "kick"


class PostType(str, Enum):
    LIVE = "live"
    VIDEO = "video"
    SHORT = "short"
    POST = "post"


PLATFORM_LABELS: dict[Platform, str] = {
    Platform.TWITCH:    "Twitch",
    Platform.YOUTUBE:   "YouTube",
    Platform.TIKTOK:    "TikTok",
    Platform.TWITTER:   "Twitter / X",
    Platform.INSTAGRAM: "Instagram",
    Platform.KICK:      "Kick",
}

PLATFORM_COLORS: dict[Platform, int] = {
    Platform.TWITCH:    0x9146FF,
    Platform.YOUTUBE:   0xFF0000,
    Platform.TIKTOK:    0x000000,
    Platform.TWITTER:   0x1DA1F2,
    Platform.INSTAGRAM: 0xE4405F,
    Platform.KICK:      0x53FC18,
}

PLATFORM_ICONS: dict[Platform, str] = {
    Platform.TWITCH:    "🟣",
    Platform.YOUTUBE:   "🔴",
    Platform.TIKTOK:    "⚫",
    Platform.TWITTER:   "🐦",
    Platform.INSTAGRAM: "📸",
    Platform.KICK:      "🟢",
}


# =============================================================================
# MODELS
# =============================================================================

@dataclass
class SocialPost:
    """Post recupere depuis une plateforme."""

    platform: Platform
    handle: str
    post_id: str
    post_type: PostType
    title: str
    url: str
    thumbnail_url: Optional[str] = None
    posted_at: Optional[str] = None      # ISO 8601 UTC
    is_live: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def unique_key(self) -> str:
        return f"{self.platform.value}:{self.handle.lower()}:{self.post_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        d["post_type"] = self.post_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SocialPost":
        return cls(
            platform=Platform(data["platform"]),
            handle=data["handle"],
            post_id=data["post_id"],
            post_type=PostType(data["post_type"]),
            title=data["title"],
            url=data["url"],
            thumbnail_url=data.get("thumbnail_url"),
            posted_at=data.get("posted_at"),
            is_live=data.get("is_live", False),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Subscription:
    """Souscription : tel serveur tracke tel compte dans tel salon."""

    sub_id: str
    guild_id: int
    platform: Platform
    handle: str
    display_name: str
    target_channel_id: int
    role_to_ping: Optional[int] = None
    track_lives: bool = True
    track_videos: bool = True
    track_shorts: bool = False
    track_posts: bool = False
    template: Optional[str] = None       # ex: "{display_name} est en live ! {url}"
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def matches(self, post: SocialPost) -> bool:
        if not self.enabled:
            return False
        if post.platform != self.platform:
            return False
        if post.handle.lower() != self.handle.lower():
            return False
        if post.post_type == PostType.LIVE:
            return self.track_lives
        if post.post_type == PostType.VIDEO:
            return self.track_videos
        if post.post_type == PostType.SHORT:
            return self.track_shorts
        if post.post_type == PostType.POST:
            # Twitter/TikTok/Instagram sont des plateformes « post » : leur SEUL contenu, ce
            # sont des posts → on les tracke d'office (sinon une souscription créée avec le
            # défaut track_posts=False ne ferait jamais rien). owner 2026-06-27.
            if self.platform in (Platform.TWITTER, Platform.TIKTOK, Platform.INSTAGRAM):
                return True
            # 🐛 BUG CORRIGÉ (owner 2026-07-18) : le chemin RSS YouTube (YouTubeRSSAdapter, câblé
            # par défaut SANS clé) émet des SocialPost typés PostType.POST — jamais VIDEO (VIDEO
            # n'existe que dans l'adapter API, inactif sans YOUTUBE_API_KEY). Résultat : chaque
            # vidéo tombait ici sur `return self.track_posts` = False par défaut → JETÉE en
            # silence. Une vidéo YouTube = une vidéo → on respecte track_videos (défaut True).
            if self.platform == Platform.YOUTUBE:
                return self.track_videos
            return self.track_posts
        return False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Subscription":
        return cls(
            sub_id=data["sub_id"],
            guild_id=data["guild_id"],
            platform=Platform(data["platform"]),
            handle=data["handle"],
            display_name=data.get("display_name", data["handle"]),
            target_channel_id=data["target_channel_id"],
            role_to_ping=data.get("role_to_ping"),
            track_lives=data.get("track_lives", True),
            track_videos=data.get("track_videos", True),
            track_shorts=data.get("track_shorts", False),
            track_posts=data.get("track_posts", False),
            template=data.get("template"),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class Announcement:
    """Trace d'une annonce postee."""

    sub_id: str
    post_id: str
    platform: Platform
    handle: str
    guild_id: int
    discord_channel_id: int
    discord_message_id: int
    post_url: str
    post_title: str
    post_type: PostType
    posted_at: str
    last_checked_at: str
    is_currently_live: bool = False
    deleted: bool = False                 # True si on a supprime l'annonce Discord

    @property
    def unique_key(self) -> str:
        return f"{self.platform.value}:{self.handle.lower()}:{self.post_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        d["post_type"] = self.post_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Announcement":
        return cls(
            sub_id=data["sub_id"],
            post_id=data["post_id"],
            platform=Platform(data["platform"]),
            handle=data["handle"],
            guild_id=data["guild_id"],
            discord_channel_id=data["discord_channel_id"],
            discord_message_id=data["discord_message_id"],
            post_url=data.get("post_url", ""),
            post_title=data.get("post_title", ""),
            post_type=PostType(data.get("post_type", "live")),
            posted_at=data["posted_at"],
            last_checked_at=data["last_checked_at"],
            is_currently_live=data.get("is_currently_live", False),
            deleted=data.get("deleted", False),
        )


# =============================================================================
# PLATFORM ADAPTER (ABC)
# =============================================================================

class PlatformAdapter(ABC):
    """Interface pour adapter une plateforme."""

    platform: Platform

    @property
    def configured(self) -> bool:
        """True si l'adapter peut faire des requetes API reelles."""
        return False

    async def setup(self, session: Optional[aiohttp_ClientSession_T] = None) -> None:
        """Setup optionnel (auth, token, etc.). Default no-op."""
        pass

    async def teardown(self) -> None:
        """Cleanup optionnel."""
        pass

    @abstractmethod
    async def fetch_posts(self, handle: str) -> list[SocialPost]:
        """Recupere les posts en cours / recents d'un compte."""
        ...

    async def is_post_active(self, post: SocialPost) -> bool:
        """Verifie si un post est toujours actif sur la plateforme.

        Implementation par defaut : refetch tous les posts du handle, et regarde
        si l'ID est present. Adapter peut override pour quelque chose de plus
        efficace.
        """
        try:
            current = await self.fetch_posts(post.handle)
        except Exception:
            return True  # en cas d'erreur API, on garde l'annonce
        return any(p.post_id == post.post_id for p in current)


# Type alias for forward refs (aiohttp may not be imported in some test contexts)
aiohttp_ClientSession_T = Any


# =============================================================================
# MANUAL ADAPTER (toujours disponible, l'owner publie a la main)
# =============================================================================

class ManualAdapter(PlatformAdapter):
    """Adapter manuel : pas d'API, l'owner declare les posts a la main.

    Utile pour les plateformes sans API publique fiable (TikTok, Instagram,
    Twitter sans cle, etc.). Le bot ne dedup que sur les declarations explicites.
    """

    def __init__(self, platform: Platform):
        self.platform = platform
        self._manual_posts: dict[str, list[SocialPost]] = {}  # handle -> posts

    @property
    def configured(self) -> bool:
        return True

    def declare_post(self, post: SocialPost) -> None:
        """L'owner declare manuellement un post a tracker."""
        if post.platform != self.platform:
            raise ValueError(f"post platform {post.platform} != adapter {self.platform}")
        key = post.handle.lower()
        self._manual_posts.setdefault(key, []).append(post)

    def remove_post(self, handle: str, post_id: str) -> None:
        """L'owner declare qu'un post manuel n'est plus actif."""
        key = handle.lower()
        if key in self._manual_posts:
            self._manual_posts[key] = [
                p for p in self._manual_posts[key] if p.post_id != post_id
            ]

    async def fetch_posts(self, handle: str) -> list[SocialPost]:
        return list(self._manual_posts.get(handle.lower(), []))


# =============================================================================
# TWITCH ADAPTER (lives uniquement - les videos / clips peuvent etre ajoutes)
# =============================================================================

class TwitchAdapter(PlatformAdapter):
    """Adapter Twitch via l'API Helix (OAuth client credentials).

    Detecte les streams en live. Gere automatiquement le token.
    """

    platform = Platform.TWITCH

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("TWITCH_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("TWITCH_CLIENT_SECRET")
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._session = None  # type: Any

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def setup(self, session=None) -> None:
        if session is not None:
            self._session = session
        else:
            import aiohttp
            self._session = aiohttp.ClientSession()

    async def teardown(self) -> None:
        # Ne ferme PAS la session si elle nous a ete fournie
        pass

    async def _ensure_token(self) -> Optional[str]:
        if not self.configured:
            return None
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        try:
            async with self._session.post(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            self._token = data.get("access_token")
            self._token_expires_at = now + data.get("expires_in", 3600)
            return self._token
        except Exception:
            return None

    async def fetch_posts(self, handle: str) -> list[SocialPost]:
        """Recupere le live en cours d'un user (vide si pas en live)."""
        if not self.configured or not self._session:
            return []
        token = await self._ensure_token()
        if not token:
            return []
        url = "https://api.twitch.tv/helix/streams"
        headers = {
            "Client-Id": self.client_id,
            "Authorization": f"Bearer {token}",
        }
        params = {"user_login": handle}
        try:
            async with self._session.get(
                url, headers=headers, params=params, timeout=10
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception:
            return []

        posts: list[SocialPost] = []
        for entry in data.get("data", []):
            stream_id = str(entry.get("id"))
            user_login = entry.get("user_login", handle)
            user_name = entry.get("user_name", handle)
            title = entry.get("title", "")
            game_name = entry.get("game_name", "")
            started_at = entry.get("started_at")
            thumb = entry.get("thumbnail_url", "").replace("{width}", "1280").replace("{height}", "720")

            posts.append(SocialPost(
                platform=Platform.TWITCH,
                handle=user_login,
                post_id=stream_id,
                post_type=PostType.LIVE,
                title=title or f"{user_name} est en live",
                url=f"https://www.twitch.tv/{user_login}",
                thumbnail_url=thumb or None,
                posted_at=started_at,
                is_live=True,
                metadata={
                    "game_name": game_name,
                    "user_name": user_name,
                    "viewer_count": entry.get("viewer_count", 0),
                },
            ))
        return posts


# =============================================================================
# YOUTUBE ADAPTER (videos + lives via API v3 / cle)
# =============================================================================

class YouTubeAdapter(PlatformAdapter):
    """Adapter YouTube via l'API Data v3 (cle simple).

    Recupere les videos et lives recents d'une chaine. Le `handle` peut etre :
    - un channel_id (UC...)
    - un handle @username (resolu via search)
    """

    platform = Platform.YOUTUBE

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("YOUTUBE_API_KEY")
        self._session = None  # type: Any
        self._channel_id_cache: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def setup(self, session=None) -> None:
        if session is not None:
            self._session = session
        else:
            import aiohttp
            self._session = aiohttp.ClientSession()

    async def _resolve_channel_id(self, handle: str) -> Optional[str]:
        if handle.startswith("UC") and len(handle) > 20:
            return handle
        if handle in self._channel_id_cache:
            return self._channel_id_cache[handle]
        if not self._session:
            return None
        h = handle.lstrip("@").strip()
        _chan = "https://www.googleapis.com/youtube/v3/channels"
        _srch = "https://www.googleapis.com/youtube/v3/search"
        # Ordre de resolution (du plus PRECIS + moins cher au plus large) :
        #  1) forHandle=@pseudo  → resout PILE la bonne chaine, 1 unite de quota.
        #  2) forUsername=pseudo → ancien pseudo « legacy » (chaines historiques).
        #  3) search q=nom       → nom libre, 100 unites de quota → dernier recours.
        # C'est ce qui fait « juste marcher » aussi bien le @pseudo que le NOM officiel.
        attempts = [
            (_chan, {"part": "id", "forHandle": "@" + h}),
            (_chan, {"part": "id", "forUsername": h}),
            (_srch, {"part": "snippet", "type": "channel", "q": h, "maxResults": 1}),
        ]
        for url, params in attempts:
            q = {**params, "key": self.api_key}
            try:
                async with self._session.get(url, params=q, timeout=10) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
            except Exception:
                continue
            items = data.get("items", [])
            if not items:
                continue
            _id = items[0].get("id")
            channel_id = (_id if isinstance(_id, str) else None) \
                or items[0].get("snippet", {}).get("channelId") \
                or (items[0].get("id", {}) or {}).get("channelId")
            if channel_id and str(channel_id).startswith("UC"):
                self._channel_id_cache[handle] = channel_id
                try:
                    import diag
                    diag.event("social", "youtube_api_resolve", f"@{h} → {channel_id}")
                except Exception:
                    pass
                return channel_id
        try:
            import diag
            diag.warn("social", "youtube_api_resolve",
                      f"@{h} introuvable via l'API (clé posée mais 0 résultat sur forHandle/forUsername/search)")
        except Exception:
            pass
        return None

    async def fetch_posts(self, handle: str) -> list[SocialPost]:
        if not self.configured or not self._session:
            return []
        channel_id = await self._resolve_channel_id(handle)
        if not channel_id:
            return []
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": 5,
            "key": self.api_key,
        }
        try:
            async with self._session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception:
            return []

        posts: list[SocialPost] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue
            live_state = snippet.get("liveBroadcastContent", "none")
            is_live_now = (live_state == "live")
            ptype = PostType.LIVE if is_live_now else PostType.VIDEO

            thumbs = snippet.get("thumbnails", {})
            thumb_url = (
                thumbs.get("maxres", {}).get("url")
                or thumbs.get("high", {}).get("url")
                or thumbs.get("default", {}).get("url")
            )

            posts.append(SocialPost(
                platform=Platform.YOUTUBE,
                handle=handle,
                post_id=video_id,
                post_type=ptype,
                title=snippet.get("title", ""),
                url=f"https://www.youtube.com/watch?v={video_id}",
                thumbnail_url=thumb_url,
                posted_at=snippet.get("publishedAt"),
                is_live=is_live_now,
                metadata={
                    "channel_id": channel_id,
                    "channel_title": snippet.get("channelTitle"),
                },
            ))
        return posts

    async def is_post_active(self, post: SocialPost) -> bool:
        """Pour YouTube, on verifie que la video est toujours publiee."""
        if not self.configured or not self._session:
            return True
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "status,snippet",
            "id": post.post_id,
            "key": self.api_key,
        }
        try:
            async with self._session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return True
                data = await resp.json()
        except Exception:
            return True
        items = data.get("items", [])
        if not items:
            return False  # plus dispo => annonce a supprimer
        status = items[0].get("status", {})
        privacy = status.get("privacyStatus")
        return privacy in ("public", "unlisted")


# =============================================================================
# RSSHUB ADAPTER (Twitter/X, TikTok, Instagram... via flux RSS - owner 2026-06-27)
# =============================================================================
# Les API officielles de X/TikTok/Instagram sont fermees/payantes et le scraping
# direct est bloque (Cloudflare/login). La methode qui MARCHE = un convertisseur
# RSS (RSSHub, open-source/gratuit/auto-hebergeable). Cet adapter prend le @pseudo
# tape par l'owner et le TRANSFORME tout seul en URL de flux RSSHub, puis recupere
# les derniers posts. L'owner ne touche JAMAIS a un lien. 100% FAIL-SAFE.

# Routes RSSHub par plateforme (le :user est remplace par le pseudo nettoye).
RSSHUB_ROUTES: dict[Platform, str] = {
    Platform.TWITTER:   "twitter/user/{user}",
    Platform.TIKTOK:    "tiktok/user/@{user}",
    # Instagram : on utilise la route web-api "/instagram/2/user/" (par COOKIE IG_COOKIE)
    # et PAS "/instagram/user/" (private-api login/mdp) qui est cassee en 2026.
    Platform.INSTAGRAM: "instagram/2/user/{user}",
}
# Instance RSSHub par defaut (publique). Surcharge conseillee : variable d'env
# RSSHUB_BASE_URL pointant vers TA propre instance (1 clic sur Railway) = fiable+illimitee.
DEFAULT_RSSHUB_BASE = "https://rsshub.app"


def _clean_handle(handle: str) -> str:
    """@CaribBros / https://x.com/CaribBros / 'caribbros ' -> 'caribbros'.

    GENERIQUE (Twitter/TikTok/Instagram). YouTube a le sien : `_clean_yt_handle` — ses URL ont
    des ONGLETS (/videos, /featured…) qu'il faut retirer, alors qu'ici un compte peut
    legitimement s'appeler « videos ».
    """
    h = (handle or "").strip()
    h = h.split("?")[0].split("#")[0]  # query/fragment : « x.com/Nom?s=20 » collé du navigateur
    if "/" in h:                       # si on a colle une URL, on prend le dernier segment
        h = h.rstrip("/").split("/")[-1]
    h = h.lstrip("@").strip()
    return h


# Onglets de chaine YouTube : ce sont des SUFFIXES d'URL, jamais le nom de la chaine.
_YT_TABS = {"videos", "featured", "streams", "shorts", "about", "playlists",
            "community", "live", "podcasts", "releases", "channels", "store"}


def _clean_yt_handle(handle: str) -> str:
    """Extrait l'identifiant d'une chaine YouTube (channel_id UC..., @pseudo ou nom legacy).

    Corrige un bug reel (revue 2026-07-17) : l'ancien nettoyage generique gardait le DERNIER
    segment de l'URL, or l'URL qu'on copie depuis son navigateur finit par un ONGLET —
    « youtube.com/@RellGames/videos » donnait « videos », et on tentait de resoudre la chaine
    « @videos ». Pire, le message d'aide conseillait lui-meme de coller
    « youtube.com/channel/UC... » : avec /videos au bout, ce chemin echouait AUSSI. Le pire cas
    n'est pas le silence — si une chaine homonyme existe, on publie les videos de QUELQU'UN D'AUTRE.
    """
    h = (handle or "").strip()
    h = h.split("?")[0].split("#")[0]
    if "/" not in h:
        return h.lstrip("@").strip()
    import re as _re
    # 1) un channel_id explicite. On EXIGE le segment « /channel/ » : chercher « UC[\w-]{20,} »
    # n'importe ou prendrait un pseudo legitime tel que « @UCsomethingverylongname » pour un
    # channel_id, et on irait poller le flux de personne.
    m = _re.search(r"/channel/(UC[\w-]{20,})", h)
    if m:
        return m.group(1)
    segs = [s for s in h.rstrip("/").split("/") if s]
    for s in reversed(segs):                       # 2) un @pseudo, ou qu'il soit
        if s.startswith("@"):
            return s.lstrip("@").strip()
    segs = [s for s in segs if s.lower() not in _YT_TABS]   # 3) sinon : nom legacy (/c/, /user/)
    return (segs[-1] if segs else "").lstrip("@").strip()


class RSSHubAdapter(PlatformAdapter):
    """Recupere les posts d'un compte (Twitter/TikTok/Insta) via un flux RSSHub.

    Le `handle` est un simple @pseudo ; l'adapter construit lui-meme l'URL du flux.
    Anti-flood : au TOUT PREMIER passage pour un pseudo, on prend l'etat courant comme
    REFERENCE (zero dump d'historique) et on n'annonce QUE les posts suivants.
    """

    _UA = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    MAX_NEW_PER_POLL = 3               # anti-flood : au plus N nouveaux posts par passage

    def __init__(self, platform: Platform, base_url: Optional[str] = None):
        self.platform = platform
        # owner 2026-07-12 : base_url est une PROPRIETE lue A CHAUD (env RSSHUB_BASE_URL, posable
        # via /social depuis Discord sans toucher a Railway) → une MAJ s'applique SANS redemarrage.
        self._base_override = ((base_url or "").strip().rstrip("/")) or None
        self.route = RSSHUB_ROUTES.get(platform, "")
        self._session = None  # type: Any
        self._seen: dict[str, set] = {}      # handle -> set des guid deja vus (baseline en memoire)

    @property
    def base_url(self) -> str:
        """Lu DYNAMIQUEMENT → changer RSSHUB_BASE_URL (env OU /social) prend effet TOUT DE SUITE,
        sans reconstruire les adapters ni redemarrer le bot."""
        if self._base_override:
            return self._base_override
        return (os.environ.get("RSSHUB_BASE_URL") or DEFAULT_RSSHUB_BASE).rstrip("/")

    @property
    def configured(self) -> bool:
        # "configured" = capable de requetes reelles (≠ manuel) → True si on a une route + une base.
        return bool(self.route and self.base_url)

    async def setup(self, session=None) -> None:
        if session is not None:
            self._session = session
        else:
            import aiohttp
            self._session = aiohttp.ClientSession()

    def feed_url(self, handle: str) -> str:
        return f"{self.base_url}/{self.route.format(user=_clean_handle(handle))}"

    async def _fetch_items(self, handle: str) -> list[SocialPost]:
        """Telecharge + parse le flux RSS/Atom -> liste de SocialPost (du + recent au + ancien)."""
        import xml.etree.ElementTree as ET
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()
        url = self.feed_url(handle)
        try:
            async with self._session.get(url, headers=self._UA, timeout=15) as resp:
                if resp.status != 200:
                    # owner 2026-07-18 : ne plus avaler en silence. rsshub.app public = 302/403,
                    # instance perso = 403/5xx si cookie mort → désormais VISIBLE dans [DIAG].
                    try:
                        import diag
                        diag.warn("social", "rss_fetch",
                                  f"{getattr(self.platform, 'value', '?')} @{handle} : "
                                  f"flux HTTP {resp.status} ({url})")
                    except Exception:
                        pass
                    return []
                text = await resp.text()
            root = ET.fromstring(text)
        except Exception as _ex:
            try:
                import diag
                diag.warn("social", "rss_fetch",
                          f"{getattr(self.platform, 'value', '?')} @{handle} : "
                          f"échec réseau/parse ({type(_ex).__name__}) — {url}")
            except Exception:
                pass
            return []
        out: list[SocialPost] = []
        try:
            nodes = root.findall(".//item")
            if nodes:
                for it in nodes[:10]:
                    link = (it.findtext("link") or "").strip()
                    guid = (it.findtext("guid") or link or "").strip()
                    title = (it.findtext("title") or "").strip()
                    desc = it.findtext("description") or ""
                    img = ""
                    enc = it.find("enclosure")
                    if enc is not None and enc.get("url"):
                        img = enc.get("url")
                    if not img and desc:
                        import re as _re
                        m = _re.search(r'<img[^>]+src=["\']([^"\']+)', desc)
                        if m:
                            img = m.group(1)
                    pid = guid or title
                    if not pid:
                        continue
                    out.append(SocialPost(
                        platform=self.platform, handle=handle, post_id=pid,
                        post_type=PostType.POST, title=title[:280] or "Nouveau post",
                        url=link or url, thumbnail_url=img or None,
                        posted_at=(it.findtext("pubDate") or None),
                    ))
            else:                          # Atom (fallback)
                ns = {"a": "http://www.w3.org/2005/Atom"}
                for e in root.findall(".//a:entry", ns)[:10]:
                    le = e.find("a:link", ns)
                    link = le.get("href") if le is not None else ""
                    guid = (e.findtext("a:id", namespaces=ns) or link or "").strip()
                    title = (e.findtext("a:title", namespaces=ns) or "").strip()
                    pid = guid or title
                    if not pid:
                        continue
                    out.append(SocialPost(
                        platform=self.platform, handle=handle, post_id=pid,
                        post_type=PostType.POST, title=title[:280] or "Nouveau post",
                        url=link or url))
        except Exception as _ex:
            # owner 2026-07-18 : renvoyer ce qui a DÉJÀ été parsé (avant : `return []` jetait
            # tous les items déjà lus si une SEULE entrée était malformée) + trace visible.
            try:
                import diag
                diag.warn("social", "rss_parse",
                          f"{getattr(self.platform, 'value', '?')} @{handle} : "
                          f"parse partiel ({type(_ex).__name__}), {len(out)} item(s) gardé(s)")
            except Exception:
                pass
            return out
        return out

    async def fetch_posts(self, handle: str) -> list[SocialPost]:
        if not self.configured:
            return []
        items = await self._fetch_items(handle)
        if not items:
            return []
        key = _clean_handle(handle).lower()
        seen = self._seen.get(key)
        ids = [p.post_id for p in items]
        if seen is None:
            # 🎯 BUG CORRIGE (owner 2026-07-17) : la baseline EN MEMOIRE (self._seen) se
            # reinitialisait a CHAQUE redemarrage Railway → au 1er passage on renvoyait [] et les
            # DERNIERES videos/tweets etaient avales, JAMAIS postes (« aucune se poste »). Or le
            # vrai dedup est PERSISTANT cote manager (has_announcement / _anns sur /data, survit au
            # reboot). On renvoie donc les N DERNIERS posts (le manager filtre ceux deja annonces
            # → aucun re-post) au lieu de []. Au 1er ajout d'une chaine = on poste les N derniers
            # (borne a MAX_NEW_PER_POLL, voulu : « poster les dernieres videos »), pas 15.
            self._seen[key] = set(ids)
            return list(reversed(items[:self.MAX_NEW_PER_POLL]))
        fresh = [p for p in items if p.post_id not in seen]
        for pid in ids:
            seen.add(pid)
        if len(seen) > 200:                 # borne memoire
            self._seen[key] = set(ids)
        # du + ancien au + recent, plafonne (anti-flood)
        return list(reversed(fresh[:self.MAX_NEW_PER_POLL]))

    async def is_post_active(self, post: SocialPost) -> bool:
        # Un post/tweet ne "disparait" pas comme un live qui se termine : on NE supprime
        # jamais l'annonce juste parce que le post a defile hors du flux. → toujours actif.
        return True


# =============================================================================
# YOUTUBE via RSS OFFICIEL — SANS CLE (owner 2026-07-12)
# =============================================================================
# 🎯 BUG CORRIGE : le panneau « Reseaux sociaux » enregistrait bien les pseudos YouTube, mais
# bot.py ne branchait `YouTubeAdapter` QUE si `YOUTUBE_API_KEY` existait (sa propriete
# `configured` = bool(api_key)). Sans cle → YOUTUBE tombait sur `ManualAdapter`, qui renvoie
# une liste VIDE A VIE → **aucune video n'a JAMAIS ete publiee** depuis ce panneau. Pire : le
# statut au boot affichait « YouTube : RSS auto ✅ (sans cle) » — vrai du POLLER LEGACY, faux de
# ce chemin-la → la panne etait masquee.
# SOLUTION : YouTube expose un flux RSS **officiel, gratuit, sans cle** :
#   https://www.youtube.com/feeds/videos.xml?channel_id=UC...
# C'est de l'**Atom**, que `RSSHubAdapter._fetch_items` sait DEJA parser (branche Atom) — et son
# anti-flood (1er passage = reference, plafond par passage) est deja eprouve. On herite donc de
# lui et on ne surcharge que l'URL + la resolution du pseudo → un minimum de code neuf.

class YouTubeRSSAdapter(RSSHubAdapter):
    """YouTube via son flux RSS OFFICIEL (Atom). Aucune cle, aucun quota, aucun hebergement.

    Accepte un `channel_id` (UC...), un @pseudo, une URL de chaine, ou un nom legacy :
    le channel_id est resolu UNE fois (puis cache) en lisant la page publique de la chaine.
    """

    platform = Platform.YOUTUBE

    _CID_FAIL_TTL = 3600.0                       # 1 h avant de retenter un pseudo irresolvable

    def __init__(self):
        super().__init__(Platform.YOUTUBE)
        # `configured` du parent exige une route non vide ; ici l'URL est fixe → marqueur.
        self.route = "_youtube_rss_"
        self._cid: dict[str, str] = {}          # pseudo nettoye -> channel_id (UC...)
        self._cid_fail: dict[str, float] = {}   # pseudo nettoye -> instant du dernier echec

    @property
    def configured(self) -> bool:
        return True                              # RSS officiel : toujours disponible, sans cle

    def feed_url(self, handle: str) -> str:
        h = _clean_yt_handle(handle)
        return ("https://www.youtube.com/feeds/videos.xml?channel_id="
                + self._cid.get(h.lower(), h))

    # ⚠️ COOKIE DE CONSENTEMENT (owner 2026-07-12) — sinon RIEN ne marche depuis l'Europe.
    # Verifie en direct : https://www.youtube.com/@RellGames renvoie un **302 vers
    # consent.youtube.com** (mur cookies UE, impose par l'IP du serveur — Railway est en UE ;
    # forcer ?hl=en&gl=US NE change RIEN, la redirection persiste avec gl=FR). Sans cookie, on
    # recupere la page de CONSENTEMENT au lieu de la chaine → aucun channelId → **zero video**.
    # Ces cookies sont exactement ce que la page de consentement poserait ; c'est la parade
    # standard (utilisee par yt-dlp & co). NB : le FLUX RSS lui-meme n'est PAS soumis au mur —
    # seule la resolution @pseudo -> channel_id l'etait.
    _CONSENT = {"Cookie": "SOCS=CAI; CONSENT=YES+cb.20210328-17-p0.en+FX+123",
                "Accept-Language": "en-US,en;q=0.9"}

    async def _resolve_channel_id(self, handle: str) -> Optional[str]:
        """@pseudo / nom / URL -> channel_id UC... (lu sur la page publique, puis cache)."""
        h = _clean_yt_handle(handle)
        if h.startswith("UC") and len(h) > 20:   # deja un channel_id
            return h
        hit = self._cid.get(h.lower())
        if hit:
            return hit
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()
        import re as _re
        _hdr = {**self._UA, **self._CONSENT}
        for _u in (f"https://www.youtube.com/@{h}",
                   f"https://www.youtube.com/c/{h}",
                   f"https://www.youtube.com/user/{h}"):
            try:
                async with self._session.get(_u, headers=_hdr, timeout=15,
                                             allow_redirects=True) as r:
                    if r.status != 200:
                        continue
                    html = await r.text()
            except Exception:
                continue
            if "consent.youtube.com" in html[:5000] and "channelId" not in html[:20000]:
                continue                          # mur de consentement → tentative suivante
            m = (_re.search(r'"channelId"\s*:\s*"(UC[\w-]{20,})"', html)
                 or _re.search(r'/channel/(UC[\w-]{20,})', html)
                 or _re.search(r'"externalId"\s*:\s*"(UC[\w-]{20,})"', html))
            if m:
                self._cid[h.lower()] = m.group(1)
                if len(self._cid) > 500:         # borne memoire
                    self._cid.clear()
                    self._cid[h.lower()] = m.group(1)
                try:
                    import diag
                    diag.event("social", "youtube_resolve", f"@{h} → {m.group(1)} (via {_u})")
                except Exception:
                    pass
                return m.group(1)
        # Échec de résolution — visible dans [DIAG] (le mur de consentement UE bloque le @pseudo ;
        # la voie SÛRE = l'URL youtube.com/channel/UC... ou une clé YOUTUBE_API_KEY).
        try:
            import diag
            diag.warn("social", "youtube_resolve",
                      f"@{h} NON résolu (mur de consentement UE) → colle l'URL "
                      f"youtube.com/channel/UC... ou pose YOUTUBE_API_KEY")
        except Exception:
            pass
        return None

    async def _fetch_items(self, handle: str) -> list:
        # CACHE NEGATIF (revue 2026-07-17). Un pseudo irresolvable l'est DURABLEMENT (faute de
        # frappe, chaine renommee, mur de consentement) : c'est le cas NOMINAL, pas un cas rare.
        # Sans ce garde, on relancait 3 GET vers youtube.com + un pave de warning A CHAQUE
        # passage — soit ~864 requetes/jour pour UN seul pseudo casse (poll = 300 s par defaut),
        # avec un risque de rate-limit sur le chemin qui souffre deja du mur de consentement.
        import time as _t
        _h = _clean_yt_handle(handle).lower()
        # ⚠️ Tester l'APPARTENANCE au dict AVANT l'arithmetique (corrige un bug d'audit
        # 2026-07-17) : le sentinel `.get(_h, 0.0)` confondait « jamais tombe en echec » et
        # « echoue a l'instant 0.0 ». Or `time.monotonic()` part du boot systeme ; pendant la 1re
        # heure d'uptime, `monotonic() - 0.0 < 3600` est VRAI → un pseudo JAMAIS resolu retournait
        # [] sans meme essayer. On ne saute QUE les pseudos reellement enregistres en echec.
        _last_fail = self._cid_fail.get(_h)
        if _last_fail is not None and _t.monotonic() - _last_fail < self._CID_FAIL_TTL:
            return []                            # echec recent : ni requete, ni log
        # Resout le channel_id AVANT que le parent ne construise l'URL (feed_url lit le cache).
        cid = await self._resolve_channel_id(handle)
        if not cid:
            if len(self._cid_fail) > 500:        # borne memoire (idem `_cid`)
                self._cid_fail.clear()
            self._cid_fail[_h] = _t.monotonic()  # → le warning ci-dessous sort 1×/h, pas 1×/5 min
            # DIAG : « pourquoi cette chaine YouTube ne poste rien ? » → visible sur Railway.
            try:
                import diag
                diag.warn("social", "youtube_resolve",
                          f"@{handle} irresolvable (mur consentement UE ou pseudo inexact) → "
                          f"mets l'ID de chaine UC... ou l'URL youtube.com/channel/UC... "
                          f"Nouvel essai dans 1 h max.")
            except Exception:
                pass
            return []
        return await super()._fetch_items(handle)


# =============================================================================
# TWITTER / X ADAPTER DIRECT (syndication - owner 2026-06-27)
# =============================================================================
# LA solution Twitter qui marche GRATUITEMENT en 2026, SANS API, SANS instance a heberger,
# SANS jeton : le point d'entree "syndication" de Twitter (celui qui sert a afficher les
# tweets embarques sur les sites web) renvoie les derniers tweets d'un compte en JSON, sans
# authentification. L'owner met juste le @pseudo dans le panneau -> le bot va chercher les
# tweets tout seul et les poste. 100% FAIL-SAFE. (Endpoint non officiel : si X le coupe un
# jour, on bascule sur RSSHub ; le code reste, il suffit de rebrancher l'adapter.)

class TwitterSyndicationAdapter(PlatformAdapter):
    """Recupere les derniers tweets d'un compte via syndication.twitter.com (sans cle)."""

    platform = Platform.TWITTER
    _URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{user}"
    _UA = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    MAX_NEW_PER_POLL = 3

    def __init__(self):
        self.platform = Platform.TWITTER
        self._session = None  # type: Any
        self._seen: dict[str, set] = {}

    @property
    def configured(self) -> bool:
        return True

    async def setup(self, session=None) -> None:
        if session is not None:
            self._session = session
        else:
            import aiohttp
            self._session = aiohttp.ClientSession()

    async def _fetch_tweets(self, handle: str) -> list[SocialPost]:
        import re as _re
        h = _clean_handle(handle)
        if not h:
            return []
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()
        try:
            async with self._session.get(self._URL.format(user=h), headers=self._UA,
                                         timeout=20) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
        except Exception:
            return []
        m = _re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, _re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(1))
            entries = ((((data.get("props") or {}).get("pageProps") or {})
                        .get("timeline") or {}).get("entries") or [])
        except Exception:
            return []
        tweets = []
        for e in entries:
            t = (e.get("content") or {}).get("tweet") if isinstance(e, dict) else None
            if isinstance(t, dict) and t.get("id_str"):
                tweets.append(t)
        # Tri par ID (snowflake = ordre chronologique) decroissant : le + recent d'abord.
        def _idnum(t):
            try:
                return int(t.get("id_str") or 0)
            except Exception:
                return 0
        tweets.sort(key=_idnum, reverse=True)
        out: list[SocialPost] = []
        for t in tweets[:15]:
            sn = ((t.get("user") or {}).get("screen_name")) or h
            tid = t["id_str"]
            txt = (t.get("full_text") or t.get("text") or "").strip()
            img = ""
            media = (t.get("entities") or {}).get("media") or []
            if isinstance(media, list) and media:
                img = media[0].get("media_url_https") or ""
            out.append(SocialPost(
                platform=Platform.TWITTER, handle=handle, post_id=str(tid),
                post_type=PostType.POST, title=(txt[:280] or "Nouveau tweet"),
                url=f"https://twitter.com/{sn}/status/{tid}",
                thumbnail_url=img or None, posted_at=t.get("created_at")))
        return out

    async def fetch_posts(self, handle: str) -> list[SocialPost]:
        items = await self._fetch_tweets(handle)        # plus recent d'abord
        if not items:
            return []
        key = _clean_handle(handle).lower()
        seen = self._seen.get(key)
        ids = [p.post_id for p in items]
        if seen is None:
            # Idem RSSHubAdapter (bug corrige 2026-07-17) : la baseline memoire se reinitialisait a
            # chaque reboot → derniers tweets avales. Dedup persistant cote manager → on renvoie les
            # N derniers au lieu de [].
            self._seen[key] = set(ids)
            return list(reversed(items[:self.MAX_NEW_PER_POLL]))
        fresh = [p for p in items if p.post_id not in seen]
        for pid in ids:
            seen.add(pid)
        if len(seen) > 300:
            self._seen[key] = set(ids)
        return list(reversed(fresh[:self.MAX_NEW_PER_POLL]))   # du + ancien au + recent

    async def is_post_active(self, post: SocialPost) -> bool:
        return True


# =============================================================================
# PERSISTANCE
# =============================================================================

from paths import module_dir
DATA_DIR = module_dir("social")


def _subs_path(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}_subs.json"


def _anns_path(guild_id: int) -> Path:
    return DATA_DIR / f"{guild_id}_anns.json"


_io_lock = asyncio.Lock()


async def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


async def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# =============================================================================
# MANAGER
# =============================================================================

PostCallback = Callable[[Subscription, SocialPost], Awaitable[Optional[int]]]
DeleteCallback = Callable[[Announcement], Awaitable[bool]]


class SocialMediaManager:
    """Orchestrateur central : adapters + subs + anns + polling + cleanup."""

    def __init__(
        self,
        post_callback: Optional[PostCallback] = None,
        delete_callback: Optional[DeleteCallback] = None,
        poll_interval_seconds: int = 300,
        cleanup_interval_seconds: int = 1800,
    ):
        self._adapters: dict[Platform, PlatformAdapter] = {}
        self._subs: dict[int, dict[str, Subscription]] = {}     # guild_id -> sub_id -> Sub
        self._anns: dict[int, dict[str, Announcement]] = {}     # guild_id -> unique_key -> Ann
        self._post_callback = post_callback
        self._delete_callback = delete_callback
        self.poll_interval_seconds = max(60, poll_interval_seconds)
        self.cleanup_interval_seconds = max(120, cleanup_interval_seconds)
        self._poll_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._loaded_guilds: set[int] = set()

    # ---- adapters ---------------------------------------------------------

    def register_adapter(self, adapter: PlatformAdapter) -> None:
        self._adapters[adapter.platform] = adapter

    def get_adapter(self, platform: Platform) -> Optional[PlatformAdapter]:
        return self._adapters.get(platform)

    def configured_platforms(self) -> list[Platform]:
        return [p for p, a in self._adapters.items() if a.configured]

    async def setup_all(self, session=None) -> None:
        for adapter in self._adapters.values():
            try:
                await adapter.setup(session=session)
            except Exception:
                pass

    async def teardown_all(self) -> None:
        for adapter in self._adapters.values():
            try:
                await adapter.teardown()
            except Exception:
                pass

    # ---- callbacks --------------------------------------------------------

    def set_post_callback(self, cb: PostCallback) -> None:
        self._post_callback = cb

    def set_delete_callback(self, cb: DeleteCallback) -> None:
        self._delete_callback = cb

    # ---- persistence ------------------------------------------------------

    async def load_guild(self, guild_id: int) -> None:
        async with _io_lock:
            subs_data = await _read_json(_subs_path(guild_id)) or []
            anns_data = await _read_json(_anns_path(guild_id)) or []

        self._subs[guild_id] = {}
        for d in subs_data:
            try:
                sub = Subscription.from_dict(d)
                self._subs[guild_id][sub.sub_id] = sub
            except (KeyError, ValueError):
                continue

        self._anns[guild_id] = {}
        for d in anns_data:
            try:
                ann = Announcement.from_dict(d)
                self._anns[guild_id][ann.unique_key] = ann
            except (KeyError, ValueError):
                continue

        self._loaded_guilds.add(guild_id)

    async def _save_subs(self, guild_id: int) -> None:
        async with _io_lock:
            payload = [s.to_dict() for s in self._subs.get(guild_id, {}).values()]
            await _write_json(_subs_path(guild_id), payload)

    async def _save_anns(self, guild_id: int) -> None:
        async with _io_lock:
            payload = [a.to_dict() for a in self._anns.get(guild_id, {}).values()]
            await _write_json(_anns_path(guild_id), payload)

    async def _ensure_loaded(self, guild_id: int) -> None:
        if guild_id not in self._loaded_guilds:
            await self.load_guild(guild_id)

    # ---- subscriptions API ------------------------------------------------

    async def add_subscription(
        self,
        guild_id: int,
        platform: Platform,
        handle: str,
        target_channel_id: int,
        display_name: Optional[str] = None,
        role_to_ping: Optional[int] = None,
        track_lives: bool = True,
        track_videos: bool = True,
        track_shorts: bool = False,
        track_posts: bool = False,
        template: Optional[str] = None,
    ) -> Subscription:
        await self._ensure_loaded(guild_id)
        # Detect doublon (meme platform+handle+channel)
        existing = self._find_subscription(guild_id, platform, handle, target_channel_id)
        if existing:
            return existing

        sub = Subscription(
            sub_id=uuid.uuid4().hex[:12],
            guild_id=guild_id,
            platform=platform,
            handle=handle,
            display_name=display_name or handle,
            target_channel_id=target_channel_id,
            role_to_ping=role_to_ping,
            track_lives=track_lives,
            track_videos=track_videos,
            track_shorts=track_shorts,
            track_posts=track_posts,
            template=template,
        )
        self._subs.setdefault(guild_id, {})[sub.sub_id] = sub
        await self._save_subs(guild_id)
        return sub

    async def remove_subscription(self, guild_id: int, sub_id: str) -> bool:
        await self._ensure_loaded(guild_id)
        if sub_id not in self._subs.get(guild_id, {}):
            return False
        del self._subs[guild_id][sub_id]
        await self._save_subs(guild_id)
        return True

    async def update_subscription(
        self, guild_id: int, sub_id: str, **changes
    ) -> Optional[Subscription]:
        await self._ensure_loaded(guild_id)
        sub = self._subs.get(guild_id, {}).get(sub_id)
        if not sub:
            return None
        for k, v in changes.items():
            if hasattr(sub, k):
                setattr(sub, k, v)
        await self._save_subs(guild_id)
        return sub

    async def list_subscriptions(self, guild_id: int) -> list[Subscription]:
        await self._ensure_loaded(guild_id)
        return list(self._subs.get(guild_id, {}).values())

    def _find_subscription(
        self, guild_id: int, platform: Platform, handle: str, channel_id: int
    ) -> Optional[Subscription]:
        for sub in self._subs.get(guild_id, {}).values():
            if (
                sub.platform == platform
                and sub.handle.lower() == handle.lower()
                and sub.target_channel_id == channel_id
            ):
                return sub
        return None

    # ---- announcements API ------------------------------------------------

    async def list_announcements(self, guild_id: int) -> list[Announcement]:
        await self._ensure_loaded(guild_id)
        return list(self._anns.get(guild_id, {}).values())

    async def has_announcement(
        self, guild_id: int, platform: Platform, handle: str, post_id: str
    ) -> bool:
        await self._ensure_loaded(guild_id)
        key = f"{platform.value}:{handle.lower()}:{post_id}"
        return key in self._anns.get(guild_id, {})

    async def _record_announcement(
        self,
        sub: Subscription,
        post: SocialPost,
        discord_message_id: int,
    ) -> Announcement:
        now = datetime.now(timezone.utc).isoformat()
        ann = Announcement(
            sub_id=sub.sub_id,
            post_id=post.post_id,
            platform=post.platform,
            handle=post.handle,
            guild_id=sub.guild_id,
            discord_channel_id=sub.target_channel_id,
            discord_message_id=discord_message_id,
            post_url=post.url,
            post_title=post.title,
            post_type=post.post_type,
            posted_at=now,
            last_checked_at=now,
            is_currently_live=post.is_live,
        )
        self._anns.setdefault(sub.guild_id, {})[ann.unique_key] = ann
        await self._save_anns(sub.guild_id)
        return ann

    # ---- polling loop -----------------------------------------------------

    async def poll_subscription(self, sub: Subscription) -> int:
        """Poll une souscription. Retourne le nombre d'annonces creees."""
        adapter = self._adapters.get(sub.platform)
        if not adapter:
            try:
                import diag
                diag.warn("social", "poll", f"aucun adapter pour {getattr(sub.platform, 'value', '?')}")
            except Exception:
                pass
            return 0
        try:
            posts = await adapter.fetch_posts(sub.handle)
        except Exception as _ex:
            # 🎯 Avant : erreur avalee → « pourquoi rien ne remonte de cette chaine ? » invisible.
            try:
                import diag
                diag.error("social", f"{getattr(sub.platform, 'value', '?')}_fetch",
                           f"@{getattr(sub, 'handle', '?')} : echec de recuperation", exc=_ex)
            except Exception:
                pass
            return 0

        created = 0
        for post in posts:
            if not sub.matches(post):
                continue
            # Dedup strict
            already = await self.has_announcement(
                sub.guild_id, post.platform, post.handle, post.post_id
            )
            if already:
                continue
            # Post via callback
            if self._post_callback is None:
                continue
            try:
                msg_id = await self._post_callback(sub, post)
            except Exception as _ex:
                # owner 2026-07-18 : un échec d'envoi Discord (perms, 429, salon supprimé)
                # faisait disparaître le post SANS trace → désormais visible dans [DIAG].
                try:
                    import diag
                    diag.error("social", "post_callback",
                               f"{getattr(sub.platform, 'value', '?')} @{getattr(sub, 'handle', '?')}"
                               f" → salon {getattr(sub, 'target_channel_id', '?')} : échec d'envoi",
                               exc=_ex)
                except Exception:
                    pass
                continue
            if msg_id is None:
                continue
            await self._record_announcement(sub, post, msg_id)
            created += 1
        return created

    async def poll_all(self) -> dict[int, int]:
        """Poll toutes les souscriptions de tous les guilds charges."""
        results: dict[int, int] = {}
        _total_subs = 0
        for guild_id, subs in list(self._subs.items()):
            count = 0
            for sub in subs.values():
                _total_subs += 1
                count += await self.poll_subscription(sub)
            results[guild_id] = count
        # owner 2026-07-18 : battement de cycle (visible dans [DIAG]) — PROUVE que le poller du
        # manager tourne. En usage « panneau seul » ce total reste 0 (le manager ne sert que
        # /social add) → confirme empiriquement quel système gère les pseudos de l'owner.
        try:
            import diag
            _posted = sum(results.values())
            diag.trace("social", "manager_cycle",
                       f"{_total_subs} souscription(s) /social add · {_posted} publiée(s)")
        except Exception:
            pass
        return results

    # ---- cleanup loop -----------------------------------------------------

    async def cleanup_announcement(self, ann: Announcement) -> bool:
        """Verifie qu'une annonce est toujours valide. Supprime sinon."""
        if ann.deleted:
            return False
        adapter = self._adapters.get(ann.platform)
        if not adapter:
            return False
        # Reconstruit un SocialPost minimal pour is_post_active
        fake_post = SocialPost(
            platform=ann.platform,
            handle=ann.handle,
            post_id=ann.post_id,
            post_type=ann.post_type,
            title=ann.post_title,
            url=ann.post_url,
        )
        still_active = True
        try:
            still_active = await adapter.is_post_active(fake_post)
        except Exception:
            still_active = True
        ann.last_checked_at = datetime.now(timezone.utc).isoformat()
        if not still_active and self._delete_callback is not None:
            try:
                ok = await self._delete_callback(ann)
                if ok:
                    ann.deleted = True
            except Exception:
                pass
        await self._save_anns(ann.guild_id)
        return ann.deleted

    async def cleanup_all(self) -> dict[int, int]:
        """Cleanup pour toutes les annonces des guilds charges."""
        results: dict[int, int] = {}
        for guild_id, anns in list(self._anns.items()):
            removed = 0
            for ann in list(anns.values()):
                if ann.deleted:
                    continue
                if await self.cleanup_announcement(ann):
                    removed += 1
            results[guild_id] = removed
        return results

    # ---- background tasks -------------------------------------------------

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.poll_all()
            except Exception as _ex:
                # owner 2026-07-18 : avant `except: pass` → un cycle qui plante était INVISIBLE.
                try:
                    import diag
                    diag.error("social", "poll_loop", "cycle de poll en échec", exc=_ex)
                except Exception:
                    pass
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.poll_interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def _cleanup_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.cleanup_all()
            except Exception:
                pass
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.cleanup_interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    def start_background_tasks(self) -> None:
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_background_tasks(self) -> None:
        self._stop_event.set()
        for t in (self._poll_task, self._cleanup_task):
            if t is not None:
                try:
                    await asyncio.wait_for(t, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
        self._poll_task = None
        self._cleanup_task = None
        self._stop_event = asyncio.Event()


# =============================================================================
# UTILITAIRES UI
# =============================================================================

def default_template(platform: Platform, post_type: PostType) -> str:
    """Template par defaut pour une plateforme + type de post."""
    icon = PLATFORM_ICONS.get(platform, "")
    if post_type == PostType.LIVE:
        return f"{icon} **{{display_name}}** est en live sur {PLATFORM_LABELS[platform]} !\n{{title}}\n{{url}}"
    if post_type == PostType.VIDEO:
        return f"{icon} Nouvelle video de **{{display_name}}** sur {PLATFORM_LABELS[platform]} !\n{{title}}\n{{url}}"
    if post_type == PostType.SHORT:
        return f"{icon} **{{display_name}}** a publie un Short !\n{{url}}"
    return f"{icon} Nouveau post de **{{display_name}}** !\n{{url}}"


def render_template(sub: Subscription, post: SocialPost) -> str:
    """Rend le template d'une subscription avec les variables du post."""
    template = sub.template or default_template(post.platform, post.post_type)
    return (
        template
        .replace("{display_name}", sub.display_name)
        .replace("{handle}", post.handle)
        .replace("{title}", post.title)
        .replace("{url}", post.url)
        .replace("{platform}", PLATFORM_LABELS.get(post.platform, post.platform.value))
    )


__all__ = [
    "Platform",
    "PostType",
    "PLATFORM_LABELS",
    "PLATFORM_COLORS",
    "PLATFORM_ICONS",
    "SocialPost",
    "Subscription",
    "Announcement",
    "PlatformAdapter",
    "ManualAdapter",
    "TwitchAdapter",
    "YouTubeAdapter",
    "RSSHubAdapter",
    "TwitterSyndicationAdapter",
    "SocialMediaManager",
    "default_template",
    "render_template",
]
