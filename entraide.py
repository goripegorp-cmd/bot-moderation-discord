"""entraide.py — Système d'ENTRAIDE multi-gaming (SOCLE — Tâche 1).

🎯 OBJECTIF (demande owner) : RELIER intelligemment les joueurs qui ont besoin
d'aide sur un jeu à ceux qui peuvent aider, les pousser à se connecter EN VOCAL,
et créer des ZONES dédiées. Beaucoup de demandes d'aide restent sans réponse :
ce module est le SOCLE de données + cycle de vie qui rend le matching possible.

Choix de conception VALIDÉS par l'owner :
  1. CATALOGUE de jeux configurable par l'owner (boutons) — table entraide_games.
  2. Salon VOCAL TEMPORAIRE auto (créé à la demande, auto-supprimé quand VIDE) —
     le module porte juste la donnée voice_channel_id ; la création/suppression
     réelle du vocal se fait côté bot.py (perms + garde « jamais toucher un vocal
     occupé par d'autres », incident connu).
  3. Rôle AIDANT {jeu} OPT-IN pingé DANS LE SALON (jamais @everyone, jamais en MP,
     avec cap anti-spam) — le module expose helper_role_id + is_helper_role() ;
     la prise/retrait du rôle réel et le ping se font côté bot.py.

CONTRAINTES (rappel) : zéro MP proactif, aucune slash command (tout en boutons),
@everyone jamais touché. Tout est FAIL-SAFE : si la feature n'est pas configurée
(salon demandes / catégorie vocale absents côté bot.py), elle est simplement OFF.

Module AUTONOME : dépendances injectées via setup() (MÊME patron que
activity_system / referrals / presence_chain). La CI ne voit pas les NameError
runtime → tout reste défensif (FAIL-OPEN / FAIL-SAFE partout).

DB :
- entraide_games        (catalogue de jeux configurable par l'owner)
- entraide_requests     (cycle de vie des demandes d'aide)
- entraide_helper_stats (réputation des aidants — compteur d'aides)
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from discord.ext import tasks

# ─── Dépendances injectées (même contrat que les autres modules autonomes) ───
_get_db = None                 # context manager DB (`async with get_db()`)
_cfg = None                    # async (guild_id) -> dict de config (blob JSON par guilde)
_db_set = None                 # async (guild_id, key, val) -> None
_v2 = None                     # helpers Components V2 (v2_title/v2_body/… — fournis, non requis ici)
_add_coins = None              # async (guild_id, user_id, amount) -> None  (optionnel, MODESTE)
_register_cleanup = None       # (channel_id, …) -> None  (salons éphémères — optionnel)
_chatty = None                 # async (guild) -> TextChannel|None  (optionnel)
_bot = None                    # instance bot (tâche périodique d'expiration)


# ─── Constantes (réglages, ajustables) ───────────────────────────────────────
# Une demande « ouverte » sans réponse expire au bout de ce délai (en minutes) :
# on la marque expirée pour ne pas polluer la file et libérer l'anti-spam.
EXPIRE_OPEN_MIN = 180

# C2 — RELANCE : une demande OUVERTE et NON prise (aucun aidant) depuis ce délai
# (minutes) est re-pingée UNE SEULE FOIS au rôle aidant du jeu (puis flag relanced=1).
# Choisi entre l'arrivée (ping initial) et l'expiration (EXPIRE_OPEN_MIN) pour réveiller
# une demande qui dort sans noyer le salon. Respecte le cooldown anti-spam du ping.
RELANCE_AFTER_MIN = 35

# Anti-spam du PING du rôle aidant (par jeu, par guilde) : on ne re-ping pas le
# rôle aidant d'un même jeu plus d'une fois par fenêtre. Géré côté bot.py via
# can_ping_helpers()/mark_helper_ping() ci-dessous (état mémoire, fail-open).
HELPER_PING_COOLDOWN_SEC = 600

# Plafond de salons vocaux temporaires d'entraide vivants simultanément par guilde
# (garde-fou anti-abus ; la création réelle se fait côté bot.py qui consulte ce cap).
MAX_TEMP_VOICE_PER_GUILD = 10

# Récompense MODESTE (pièces, jamais Éclats) de l'aidant quand une demande est
# résolue. Optionnelle : créditée côté bot.py via add_coins (atomique) seulement
# si _add_coins est injecté. Volontairement petite (rétention #1, anti-inflation).
HELP_REWARD_COINS = 50

# COOLDOWN ENTRE DEUX DEMANDES d'un même utilisateur (anti-abus, anti-génération
# multiple de salons). Même APRÈS avoir résolu/expiré sa demande, un user ne peut
# pas en re-créer une avant ce délai (minutes). Empêche le spam de demandes qui
# génère plein de vocaux. Vérifié DB-backed dans create_request (survit au reboot).
REQUEST_COOLDOWN_MIN = 10

# Plafond DUR du nombre de demandes OUVERTES simultanées par GUILDE (garde-fou
# anti-flood global ; complète le « 1 demande open / user »). 0 = pas de cap.
MAX_OPEN_REQUESTS_PER_GUILD = 30

# Codes de retour de create_request (anti-spam) — l'appelant (bot.py) les traduit
# en messages publics dans le salon (jamais en MP).
CREATE_OK = "ok"
CREATE_DUPLICATE = "duplicate"     # l'utilisateur a déjà une demande ouverte
CREATE_UNKNOWN_GAME = "unknown_game"
CREATE_DISABLED = "disabled"       # module non configuré / DB absente
CREATE_COOLDOWN = "cooldown"       # l'utilisateur a créé une demande trop récemment
CREATE_GUILD_FULL = "guild_full"   # trop de demandes ouvertes sur la guilde


# ─── Cache mémoire du cooldown de ping (fail-open, non persisté) ───
# { (guild_id, game_key): datetime du dernier ping } — re-prime vide au boot,
# ce qui au pire autorise UN ping juste après un reboot : acceptable.
_last_helper_ping: dict = {}


def setup(bot, get_db_fn, cfg_fn, db_set_fn, v2_helpers,
          add_coins_fn=None, register_cleanup_fn=None, chatty_fn=None):
    """Injecte les dépendances (même contrat que activity_system / referrals).

    - bot                : instance bot (itère les guilds pour la tâche d'expiration).
    - get_db_fn          : context manager DB (`async with get_db()`).
    - cfg_fn             : async (guild_id) -> dict (config blob JSON par guilde).
    - db_set_fn          : async (guild_id, key, val) -> None (écriture config).
    - v2_helpers         : namespace des helpers Components V2 (réutilisés côté UI bot.py).
    - add_coins_fn       : async (guild_id, user_id, amount) -> None — récompense MODESTE
                           optionnelle (si None, l'entraide reste purement réputationnelle).
    - register_cleanup_fn: enregistre un salon éphémère pour nettoyage (optionnel).
    - chatty_fn          : async (guild) -> TextChannel|None — salon d'accroche (optionnel).
    """
    global _bot, _get_db, _cfg, _db_set, _v2
    global _add_coins, _register_cleanup, _chatty
    _bot = bot
    _get_db = get_db_fn
    _cfg = cfg_fn
    _db_set = db_set_fn
    _v2 = v2_helpers
    _add_coins = add_coins_fn
    _register_cleanup = register_cleanup_fn
    _chatty = chatty_fn


async def init_db():
    """CREATE TABLE IF NOT EXISTS (+ index + ALTER best-effort). FAIL-OPEN."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            # Catalogue de jeux configurable par l'owner.
            await db.execute(
                "CREATE TABLE IF NOT EXISTS entraide_games ("
                "guild_id INTEGER NOT NULL, "
                "game_key TEXT NOT NULL, "
                "label TEXT NOT NULL, "
                "emoji TEXT DEFAULT '', "
                "helper_role_id INTEGER DEFAULT 0, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY (guild_id, game_key))"
            )
            # Cycle de vie des demandes d'aide.
            await db.execute(
                "CREATE TABLE IF NOT EXISTS entraide_requests ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "guild_id INTEGER NOT NULL, "
                "requester_id INTEGER NOT NULL, "
                "game_key TEXT NOT NULL, "
                "description TEXT DEFAULT '', "
                "status TEXT DEFAULT 'open', "
                "request_channel_id INTEGER DEFAULT 0, "
                "message_id INTEGER DEFAULT 0, "
                "voice_channel_id INTEGER DEFAULT 0, "
                "helper_id INTEGER DEFAULT 0, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "resolved_at TIMESTAMP)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_entraide_requests_status "
                "ON entraide_requests(guild_id, status)"
            )
            # Réputation aidant : compteur d'aides apportées.
            await db.execute(
                "CREATE TABLE IF NOT EXISTS entraide_helper_stats ("
                "guild_id INTEGER NOT NULL, "
                "user_id INTEGER NOT NULL, "
                "helped_count INTEGER DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id))"
            )
            await db.commit()
        # ALTER best-effort (migrations douces si une vieille table existe déjà).
        for stmt in (
            "ALTER TABLE entraide_games ADD COLUMN helper_role_id INTEGER DEFAULT 0",
            "ALTER TABLE entraide_games ADD COLUMN emoji TEXT DEFAULT ''",
            "ALTER TABLE entraide_requests ADD COLUMN voice_channel_id INTEGER DEFAULT 0",
            "ALTER TABLE entraide_requests ADD COLUMN message_id INTEGER DEFAULT 0",
            "ALTER TABLE entraide_requests ADD COLUMN request_channel_id INTEGER DEFAULT 0",
            "ALTER TABLE entraide_requests ADD COLUMN helper_id INTEGER DEFAULT 0",
            "ALTER TABLE entraide_requests ADD COLUMN resolved_at TIMESTAMP",
            # C2 : flag « demande relancée UNE fois » (re-ping du rôle aidant si une
            # demande dort sans réponse). 0 = jamais relancée, 1 = déjà relancée.
            "ALTER TABLE entraide_requests ADD COLUMN relanced INTEGER DEFAULT 0",
        ):
            try:
                async with _get_db() as db:
                    await db.execute(stmt)
                    await db.commit()
            except Exception:
                pass  # colonne déjà présente : normal, best-effort
    except Exception as ex:
        print(f"[entraide init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE DE JEUX (configurable par l'owner)
# ═══════════════════════════════════════════════════════════════════════════

def _slugify(text: str) -> str:
    """Titre de jeu -> game_key url-friendly (≤ 40 car.). Calque delegations.py.
    FAIL-OPEN : renvoie 'jeu' si le titre ne donne aucun caractère exploitable."""
    try:
        import re
        s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower())
        s = s.strip("_")
        return s[:40] or "jeu"
    except Exception:
        return "jeu"


async def list_games(guild_id) -> list:
    """Catalogue de la guilde -> [{game_key, label, emoji, helper_role_id}].
    FAIL-OPEN : [] sur erreur / module non prêt."""
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT game_key, label, emoji, helper_role_id "
                "FROM entraide_games WHERE guild_id=? "
                "ORDER BY created_at ASC, label ASC",
                (int(guild_id),),
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for gk, label, emoji, role_id in rows:
            out.append({
                "game_key": gk,
                "label": label or gk,
                "emoji": emoji or "",
                "helper_role_id": int(role_id or 0),
            })
        return out
    except Exception as ex:
        print(f"[entraide list_games] {ex}")
        return []


async def get_game(guild_id, game_key) -> Optional[dict]:
    """Un jeu du catalogue -> {game_key, label, emoji, helper_role_id} ou None.
    FAIL-OPEN : None sur erreur."""
    if _get_db is None or not game_key:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT game_key, label, emoji, helper_role_id "
                "FROM entraide_games WHERE guild_id=? AND game_key=?",
                (int(guild_id), str(game_key)),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "game_key": row[0],
            "label": row[1] or row[0],
            "emoji": row[2] or "",
            "helper_role_id": int(row[3] or 0),
        }
    except Exception as ex:
        print(f"[entraide get_game] {ex}")
        return None


async def add_game(guild_id, label, emoji="", helper_role_id=0) -> Optional[str]:
    """Ajoute (ou met à jour) un jeu au catalogue. Renvoie le game_key (slugifié)
    ou None sur échec. game_key dérivé du label ; si collision, suffixe numérique.
    FAIL-OPEN : None sur erreur."""
    if _get_db is None or not (label or "").strip():
        return None
    try:
        base = _slugify(label)
        existing = {g["game_key"] for g in await list_games(guild_id)}
        game_key = base
        n = 2
        while game_key in existing:
            suffix = f"_{n}"
            game_key = (base[: 40 - len(suffix)]) + suffix
            n += 1
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO entraide_games "
                "(guild_id, game_key, label, emoji, helper_role_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(guild_id, game_key) DO UPDATE SET "
                "label=excluded.label, emoji=excluded.emoji, "
                "helper_role_id=excluded.helper_role_id",
                (int(guild_id), game_key, label.strip(),
                 (emoji or "").strip(), int(helper_role_id or 0)),
            )
            await db.commit()
        return game_key
    except Exception as ex:
        print(f"[entraide add_game] {ex}")
        return None


async def set_game_helper_role(guild_id, game_key, helper_role_id) -> bool:
    """Associe un rôle AIDANT à un jeu (opt-in). FAIL-OPEN : False sur erreur."""
    if _get_db is None or not game_key:
        return False
    try:
        async with _get_db() as db:
            dc = await db.execute(
                "UPDATE entraide_games SET helper_role_id=? "
                "WHERE guild_id=? AND game_key=?",
                (int(helper_role_id or 0), int(guild_id), str(game_key)),
            )
            await db.commit()
        return getattr(dc, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[entraide set_game_helper_role] {ex}")
        return False


async def remove_game(guild_id, game_key) -> bool:
    """Retire un jeu du catalogue. FAIL-OPEN : False sur erreur.
    Les demandes existantes restent (historique) mais ne pourront plus matcher."""
    if _get_db is None or not game_key:
        return False
    try:
        async with _get_db() as db:
            dc = await db.execute(
                "DELETE FROM entraide_games WHERE guild_id=? AND game_key=?",
                (int(guild_id), str(game_key)),
            )
            await db.commit()
        return getattr(dc, "rowcount", 0) >= 1
    except Exception as ex:
        print(f"[entraide remove_game] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  RÔLE AIDANT (opt-in) — le module porte la donnée, bot.py applique les perms
# ═══════════════════════════════════════════════════════════════════════════

async def is_helper_role(guild_id, role_id) -> bool:
    """True si `role_id` est un rôle AIDANT déclaré (pour un jeu quelconque) de la
    guilde. Sert à bot.py (toggle du rôle réel via perms). FAIL-OPEN : False."""
    if _get_db is None or not role_id:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM entraide_games "
                "WHERE guild_id=? AND helper_role_id=? LIMIT 1",
                (int(guild_id), int(role_id)),
            ) as cur:
                row = await cur.fetchone()
        return row is not None
    except Exception as ex:
        print(f"[entraide is_helper_role] {ex}")
        return False


def can_ping_helpers(guild_id, game_key) -> bool:
    """Anti-spam du ping rôle aidant (mémoire, fail-open). True si la fenêtre de
    cooldown HELPER_PING_COOLDOWN_SEC est passée pour ce (jeu, guilde). bot.py
    appelle mark_helper_ping() juste après avoir réellement pingé."""
    try:
        key = (int(guild_id), str(game_key))
        last = _last_helper_ping.get(key)
        if last is None:
            return True
        return (datetime.now(timezone.utc) - last).total_seconds() >= HELPER_PING_COOLDOWN_SEC
    except Exception:
        return True  # fail-open : au pire on autorise le ping (cap géré côté bot)


def mark_helper_ping(guild_id, game_key) -> None:
    """Mémorise l'instant d'un ping rôle aidant (anti-spam). FAIL-OPEN."""
    try:
        _last_helper_ping[(int(guild_id), str(game_key))] = datetime.now(timezone.utc)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  CYCLE DE VIE DES DEMANDES (tout FAIL-SAFE)
# ═══════════════════════════════════════════════════════════════════════════

async def request_cooldown_remaining_sec(guild_id, requester_id) -> int:
    """Secondes restantes avant que `requester_id` puisse re-créer une demande
    (anti-abus, DB-backed → survit au reboot). 0 si pas de cooldown actif / OFF.
    Base : created_at de SA demande la plus récente (tout statut confondu).
    FAIL-OPEN : 0 (au pire on autorise la création, le cap guilde reste un filet)."""
    if _get_db is None or REQUEST_COOLDOWN_MIN <= 0:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT created_at FROM entraide_requests "
                "WHERE guild_id=? AND requester_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (int(guild_id), int(requester_id)),
            ) as cur:
                row = await cur.fetchone()
        if not row or not row[0]:
            return 0
        # created_at est stocké en UTC (CURRENT_TIMESTAMP SQLite) sans tz → on parse
        # défensivement et on traite comme UTC.
        try:
            last = datetime.fromisoformat(str(row[0]).replace("Z", "").strip())
        except Exception:
            try:
                last = datetime.strptime(str(row[0])[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                return 0
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        remaining = int(REQUEST_COOLDOWN_MIN * 60 - elapsed)
        return remaining if remaining > 0 else 0
    except Exception as ex:
        print(f"[entraide request_cooldown_remaining_sec] {ex}")
        return 0


async def count_requests_since(guild_id, requester_id, hours: int = 24) -> int:
    """#6 (quota/jour) : nombre de demandes créées par `requester_id` sur les `hours`
    dernières heures (tout statut). FAIL-OPEN → 0 (au pire on autorise)."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM entraide_requests "
                "WHERE guild_id=? AND requester_id=? "
                "AND created_at > datetime('now', ?)",
                (int(guild_id), int(requester_id), f"-{int(hours)} hours"),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as ex:
        print(f"[entraide count_requests_since] {ex}")
        return 0


async def create_request(guild_id, requester_id, game_key, description) -> tuple:
    """Crée une demande d'aide OUVERTE. Renvoie (code, request_id|None).

    - code == CREATE_OK            : demande créée, request_id renseigné.
    - code == CREATE_DUPLICATE     : l'utilisateur a DÉJÀ une demande open (anti-spam).
    - code == CREATE_COOLDOWN      : l'utilisateur a créé une demande trop récemment
                                     (request_id porte les secondes restantes).
    - code == CREATE_GUILD_FULL    : trop de demandes ouvertes sur la guilde (cap dur).
    - code == CREATE_UNKNOWN_GAME  : game_key absent du catalogue.
    - code == CREATE_DISABLED      : module non prêt / erreur DB.
    FAIL-SAFE : ne lève jamais."""
    if _get_db is None:
        return (CREATE_DISABLED, None)
    try:
        # Le jeu doit exister au catalogue (sinon pas de matching possible).
        game = await get_game(guild_id, game_key)
        if game is None:
            return (CREATE_UNKNOWN_GAME, None)
        # Anti-abus 1 : COOLDOWN entre demandes (même après résolution/expiration).
        # Empêche le spam de demandes qui génère plein de salons vocaux.
        try:
            remaining = await request_cooldown_remaining_sec(guild_id, requester_id)
        except Exception:
            remaining = 0
        if remaining > 0:
            return (CREATE_COOLDOWN, int(remaining))
        # Anti-abus 2 : une seule demande OUVERTE par utilisateur à la fois.
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM entraide_requests "
                "WHERE guild_id=? AND requester_id=? AND status='open' LIMIT 1",
                (int(guild_id), int(requester_id)),
            ) as cur:
                dup = await cur.fetchone()
            if dup is not None:
                return (CREATE_DUPLICATE, int(dup[0]))
            # Anti-abus 3 : cap DUR de demandes ouvertes par guilde (filet anti-flood).
            if MAX_OPEN_REQUESTS_PER_GUILD > 0:
                async with db.execute(
                    "SELECT COUNT(*) FROM entraide_requests "
                    "WHERE guild_id=? AND status='open'",
                    (int(guild_id),),
                ) as cur:
                    crow = await cur.fetchone()
                if crow and int(crow[0] or 0) >= MAX_OPEN_REQUESTS_PER_GUILD:
                    return (CREATE_GUILD_FULL, None)
            cur2 = await db.execute(
                "INSERT INTO entraide_requests "
                "(guild_id, requester_id, game_key, description, status, created_at) "
                "VALUES (?, ?, ?, ?, 'open', CURRENT_TIMESTAMP)",
                (int(guild_id), int(requester_id), str(game_key),
                 (description or "").strip()[:500]),
            )
            await db.commit()
            new_id = getattr(cur2, "lastrowid", None)
        return (CREATE_OK, int(new_id) if new_id else None)
    except Exception as ex:
        print(f"[entraide create_request] {ex}")
        return (CREATE_DISABLED, None)


async def get_request(request_id) -> Optional[dict]:
    """Lecture d'une demande -> dict complet ou None. FAIL-OPEN : None."""
    if _get_db is None or not request_id:
        return None
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, requester_id, game_key, description, status, "
                "request_channel_id, message_id, voice_channel_id, helper_id, "
                "created_at, resolved_at "
                "FROM entraide_requests WHERE id=?",
                (int(request_id),),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]), "guild_id": int(row[1]),
            "requester_id": int(row[2]), "game_key": row[3],
            "description": row[4] or "", "status": row[5] or "open",
            "request_channel_id": int(row[6] or 0), "message_id": int(row[7] or 0),
            # Le sentinelle -1 (réservation de slot vocal en cours) ne doit JAMAIS
            # être vu comme un vrai salon par l'UI → clamp à 0.
            "voice_channel_id": max(0, int(row[8] or 0)), "helper_id": int(row[9] or 0),
            "created_at": row[10], "resolved_at": row[11],
        }
    except Exception as ex:
        print(f"[entraide get_request] {ex}")
        return None


async def list_open_requests(guild_id, limit=20) -> list:
    """Demandes OUVERTES de la guilde (les plus anciennes d'abord — file d'attente).
    -> [dict, …]. FAIL-OPEN : []."""
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, requester_id, game_key, description, status, "
                "request_channel_id, message_id, voice_channel_id, helper_id, "
                "created_at, resolved_at "
                "FROM entraide_requests WHERE guild_id=? AND status='open' "
                "ORDER BY created_at ASC LIMIT ?",
                (int(guild_id), int(limit)),
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for row in rows:
            out.append({
                "id": int(row[0]), "guild_id": int(row[1]),
                "requester_id": int(row[2]), "game_key": row[3],
                "description": row[4] or "", "status": row[5] or "open",
                "request_channel_id": int(row[6] or 0), "message_id": int(row[7] or 0),
                "voice_channel_id": max(0, int(row[8] or 0)), "helper_id": int(row[9] or 0),
                "created_at": row[10], "resolved_at": row[11],
            })
        return out
    except Exception as ex:
        print(f"[entraide list_open_requests] {ex}")
        return []


async def list_open_requests_for_game(guild_id, game_key, within_hours=6,
                                      limit=10, exclude_request_id=0) -> list:
    """Demandes OUVERTES du MÊME jeu (même game_key) sur les `within_hours` dernières
    heures — sert au REGROUPEMENT « même besoin » (mentionner ceux qui cherchent de
    l'aide sur le même jeu pour qu'ils s'entraident au même endroit / même vocal).
    Les plus récentes d'abord (les voisins immédiats du demandeur). On peut exclure
    une demande (ex. celle qu'on vient de créer) via `exclude_request_id`.
    -> [dict, …]. FAIL-OPEN : []."""
    if _get_db is None or not game_key:
        return []
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=int(within_hours))).strftime("%Y-%m-%d %H:%M:%S")
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, requester_id, game_key, description, status, "
                "request_channel_id, message_id, voice_channel_id, helper_id, "
                "created_at, resolved_at "
                "FROM entraide_requests "
                "WHERE guild_id=? AND game_key=? AND status='open' "
                "AND created_at >= ? AND id != ? "
                "ORDER BY created_at DESC LIMIT ?",
                (int(guild_id), str(game_key), cutoff,
                 int(exclude_request_id or 0), int(limit)),
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for row in rows:
            out.append({
                "id": int(row[0]), "guild_id": int(row[1]),
                "requester_id": int(row[2]), "game_key": row[3],
                "description": row[4] or "", "status": row[5] or "open",
                "request_channel_id": int(row[6] or 0), "message_id": int(row[7] or 0),
                "voice_channel_id": max(0, int(row[8] or 0)), "helper_id": int(row[9] or 0),
                "created_at": row[10], "resolved_at": row[11],
            })
        return out
    except Exception as ex:
        print(f"[entraide list_open_requests_for_game] {ex}")
        return []


async def claim_request(request_id, helper_id) -> Optional[dict]:
    """Un aidant PREND une demande. ATOMIQUE : UPDATE … WHERE status='open' →
    rowcount==1 garantit qu'UN SEUL premier aidant gagne le claim (anti-course).
    Crédite +1 helped_count atomique. Renvoie le dict de la demande matchée, ou
    None si déjà prise / introuvable / auto-claim refusé. FAIL-OPEN : None.

    NB : on refuse que le demandeur se « réponde » lui-même (auto-claim)."""
    if _get_db is None or not request_id or not helper_id:
        return None
    try:
        # On lit d'abord pour bloquer l'auto-claim (le demandeur ≠ aidant).
        req = await get_request(request_id)
        if req is None or req.get("status") != "open":
            return None
        if int(req.get("requester_id", 0)) == int(helper_id):
            return None  # pas d'auto-entraide
        async with _get_db() as db:
            dc = await db.execute(
                "UPDATE entraide_requests SET helper_id=?, status='matched' "
                "WHERE id=? AND status='open'",
                (int(helper_id), int(request_id)),
            )
            await db.commit()
        if getattr(dc, "rowcount", 0) != 1:
            return None  # course perdue : un autre aidant a claim avant
        # Réputation : +1 helped_count atomique (APRÈS le claim gagné → jamais
        # de double-comptage même si la fonction est rejouée).
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT INTO entraide_helper_stats (guild_id, user_id, helped_count) "
                    "VALUES (?, ?, 1) "
                    "ON CONFLICT(guild_id, user_id) "
                    "DO UPDATE SET helped_count = helped_count + 1",
                    (int(req["guild_id"]), int(helper_id)),
                )
                await db.commit()
        except Exception:
            pass  # la réputation est un bonus ; le claim reste valide
        return await get_request(request_id)
    except Exception as ex:
        print(f"[entraide claim_request] {ex}")
        return None


async def resolve_request(request_id, by_user_id) -> Optional[dict]:
    """Marque une demande RÉSOLUE (status->'resolved', resolved_at). Renvoie le dict
    final, ou None si introuvable / déjà résolue. Idempotent (WHERE status != 'resolved').

    Récompense MODESTE de l'aidant (pièces, atomique) si add_coins injecté ET qu'un
    aidant distinct du demandeur est associé. FAIL-OPEN : None sur erreur."""
    if _get_db is None or not request_id:
        return None
    try:
        async with _get_db() as db:
            dc = await db.execute(
                "UPDATE entraide_requests SET status='resolved', "
                "resolved_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND status != 'resolved'",
                (int(request_id),),
            )
            await db.commit()
        if getattr(dc, "rowcount", 0) != 1:
            return None  # déjà résolue / introuvable → pas de double-récompense
        req = await get_request(request_id)
        if req is None:
            return None
        # Récompense MODESTE de l'aidant (pièces, jamais Éclats). Conditions :
        # aidant connu, distinct du demandeur, et add_coins disponible.
        helper = int(req.get("helper_id", 0) or 0)
        requester = int(req.get("requester_id", 0) or 0)
        if (_add_coins is not None and HELP_REWARD_COINS > 0
                and helper and helper != requester):
            try:
                await _add_coins(int(req["guild_id"]), helper, int(HELP_REWARD_COINS))
            except Exception:
                pass  # la résolution reste actée même si le crédit échoue
        return req
    except Exception as ex:
        print(f"[entraide resolve_request] {ex}")
        return None


async def set_request_voice(request_id, vc_id) -> bool:
    """Associe le salon vocal temporaire à une demande. FAIL-OPEN : False."""
    if _get_db is None or not request_id:
        return False
    try:
        async with _get_db() as db:
            dc = await db.execute(
                "UPDATE entraide_requests SET voice_channel_id=? WHERE id=?",
                (int(vc_id or 0), int(request_id)),
            )
            await db.commit()
        return getattr(dc, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[entraide set_request_voice] {ex}")
        return False


async def claim_request_voice_slot(request_id) -> bool:
    """RÉSERVE ATOMIQUE du droit de créer LE vocal d'une demande (anti double-salon).
    Pose un sentinelle voice_channel_id=-1 UNIQUEMENT si la demande n'a pas déjà un
    vocal (voice_channel_id <= 0). rowcount==1 => CET appel gagne la course et doit
    créer le vocal ; 0 => un autre clic l'a déjà réservé/créé → ne PAS recréer.
    L'appelant DOIT ensuite poser le vrai id via set_request_voice(), ou remettre 0
    via release_request_voice_slot() si la création échoue. FAIL-SAFE : False (au pire
    on ne crée pas → pas de salon en trop, jamais 2)."""
    if _get_db is None or not request_id:
        return False
    try:
        async with _get_db() as db:
            dc = await db.execute(
                "UPDATE entraide_requests SET voice_channel_id=-1 "
                "WHERE id=? AND (voice_channel_id IS NULL OR voice_channel_id<=0)",
                (int(request_id),),
            )
            await db.commit()
        return getattr(dc, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[entraide claim_request_voice_slot] {ex}")
        return False


async def release_request_voice_slot(request_id) -> bool:
    """Libère le sentinelle posé par claim_request_voice_slot (remet voice_channel_id
    à 0) SI la création du vocal a échoué — uniquement si encore à -1 (ne pas écraser
    un vrai id posé entre-temps). FAIL-SAFE : False."""
    if _get_db is None or not request_id:
        return False
    try:
        async with _get_db() as db:
            dc = await db.execute(
                "UPDATE entraide_requests SET voice_channel_id=0 "
                "WHERE id=? AND voice_channel_id=-1",
                (int(request_id),),
            )
            await db.commit()
        return getattr(dc, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[entraide release_request_voice_slot] {ex}")
        return False


async def list_dangling_requests(guild_id, limit=200) -> list:
    """SURVIE REBOOT : demandes NON ouvertes (resolved/expired) qui portent ENCORE un
    artefact à nettoyer — un message_id (post non supprimé) OU un voice_channel_id
    valide (> 0, vocal temp non supprimé). Sert au balayage d'orphelins du cleanup
    (un reboot en plein milieu ne doit RIEN laisser). -> [dict, …]. FAIL-OPEN : []."""
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, requester_id, game_key, description, status, "
                "request_channel_id, message_id, voice_channel_id, helper_id, "
                "created_at, resolved_at "
                "FROM entraide_requests "
                "WHERE guild_id=? AND status NOT IN ('open') "
                "AND (message_id > 0 OR voice_channel_id > 0) "
                "ORDER BY resolved_at DESC LIMIT ?",
                (int(guild_id), int(limit)),
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for row in rows:
            out.append({
                "id": int(row[0]), "guild_id": int(row[1]),
                "requester_id": int(row[2]), "game_key": row[3],
                "description": row[4] or "", "status": row[5] or "",
                "request_channel_id": int(row[6] or 0), "message_id": int(row[7] or 0),
                "voice_channel_id": max(0, int(row[8] or 0)), "helper_id": int(row[9] or 0),
                "created_at": row[10], "resolved_at": row[11],
            })
        return out
    except Exception as ex:
        print(f"[entraide list_dangling_requests] {ex}")
        return []


async def clear_request_artifacts(request_id, *, clear_message=False,
                                   clear_voice=False) -> bool:
    """Marque le(s) artefact(s) d'une demande comme NETTOYÉ(s) (message_id et/ou
    voice_channel_id remis à 0) une fois la suppression réelle effectuée côté bot.py.
    Évite que le balayage d'orphelins retente indéfiniment. FAIL-SAFE : False."""
    if _get_db is None or not request_id:
        return False
    if not clear_message and not clear_voice:
        return False
    try:
        sets = []
        if clear_message:
            sets.append("message_id=0")
        if clear_voice:
            sets.append("voice_channel_id=0")
        async with _get_db() as db:
            dc = await db.execute(
                f"UPDATE entraide_requests SET {', '.join(sets)} WHERE id=?",
                (int(request_id),),
            )
            await db.commit()
        return getattr(dc, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[entraide clear_request_artifacts] {ex}")
        return False


async def set_request_message(request_id, ch_id, msg_id) -> bool:
    """Mémorise le salon + message du post de demande (pour édition/maj ultérieure).
    FAIL-OPEN : False."""
    if _get_db is None or not request_id:
        return False
    try:
        async with _get_db() as db:
            dc = await db.execute(
                "UPDATE entraide_requests SET request_channel_id=?, message_id=? "
                "WHERE id=?",
                (int(ch_id or 0), int(msg_id or 0), int(request_id)),
            )
            await db.commit()
        return getattr(dc, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[entraide set_request_message] {ex}")
        return False


async def list_stale_unclaimed_requests(guild_id, older_than_min=RELANCE_AFTER_MIN,
                                        limit=20) -> list:
    """C2 — Demandes OUVERTES qui DORMENT : status='open', AUCUN aidant (helper_id<=0),
    JAMAIS relancées (relanced=0 / NULL) et plus vieilles que `older_than_min` minutes.
    Sert à re-pinger UNE fois le rôle aidant du jeu (réveil). Les plus anciennes d'abord.
    -> [dict, …]. FAIL-OPEN : []."""
    if _get_db is None:
        return []
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(minutes=int(older_than_min))).strftime("%Y-%m-%d %H:%M:%S")
        async with _get_db() as db:
            async with db.execute(
                "SELECT id, guild_id, requester_id, game_key, description, status, "
                "request_channel_id, message_id, voice_channel_id, helper_id, "
                "created_at, resolved_at "
                "FROM entraide_requests "
                "WHERE guild_id=? AND status='open' "
                "AND (helper_id IS NULL OR helper_id<=0) "
                "AND (relanced IS NULL OR relanced=0) "
                "AND created_at < ? "
                "ORDER BY created_at ASC LIMIT ?",
                (int(guild_id), cutoff, int(limit)),
            ) as cur:
                rows = await cur.fetchall()
        out = []
        for row in rows:
            out.append({
                "id": int(row[0]), "guild_id": int(row[1]),
                "requester_id": int(row[2]), "game_key": row[3],
                "description": row[4] or "", "status": row[5] or "open",
                "request_channel_id": int(row[6] or 0), "message_id": int(row[7] or 0),
                "voice_channel_id": max(0, int(row[8] or 0)), "helper_id": int(row[9] or 0),
                "created_at": row[10], "resolved_at": row[11],
            })
        return out
    except Exception as ex:
        print(f"[entraide list_stale_unclaimed_requests] {ex}")
        return []


async def mark_request_relanced(request_id) -> bool:
    """C2 — Pose ATOMIQUEMENT le flag relanced=1 sur une demande ENCORE ouverte et non
    relancée. rowcount==1 => CET appel gagne le droit de re-pinger (anti double-relance
    même en cas de relance concurrente / reboot en plein milieu). FAIL-SAFE : False."""
    if _get_db is None or not request_id:
        return False
    try:
        async with _get_db() as db:
            dc = await db.execute(
                "UPDATE entraide_requests SET relanced=1 "
                "WHERE id=? AND status='open' AND (relanced IS NULL OR relanced=0)",
                (int(request_id),),
            )
            await db.commit()
        return getattr(dc, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[entraide mark_request_relanced] {ex}")
        return False


async def expire_open_requests(guild_id, older_than_min=EXPIRE_OPEN_MIN) -> list:
    """Marque EXPIRÉES les demandes OUVERTES plus vieilles que `older_than_min`
    minutes (libère l'anti-spam, dégorge la file). Renvoie la liste des dicts
    expirés (pour que bot.py nettoie les éventuels posts/vocaux). FAIL-OPEN : []."""
    if _get_db is None:
        return []
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(minutes=int(older_than_min))).strftime("%Y-%m-%d %H:%M:%S")
        # On capture d'abord les lignes concernées (pour le nettoyage côté bot).
        async with _get_db() as db:
            async with db.execute(
                "SELECT id FROM entraide_requests "
                "WHERE guild_id=? AND status='open' AND created_at < ?",
                (int(guild_id), cutoff),
            ) as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
        expired = []
        for rid in ids:
            try:
                async with _get_db() as db:
                    dc = await db.execute(
                        "UPDATE entraide_requests SET status='expired', "
                        "resolved_at=CURRENT_TIMESTAMP "
                        "WHERE id=? AND status='open'",
                        (rid,),
                    )
                    await db.commit()
                if getattr(dc, "rowcount", 0) == 1:
                    r = await get_request(rid)
                    if r is not None:
                        expired.append(r)
            except Exception:
                continue
        return expired
    except Exception as ex:
        print(f"[entraide expire_open_requests] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
#  RÉPUTATION AIDANT
# ═══════════════════════════════════════════════════════════════════════════

async def get_helper_count(guild_id, user_id) -> int:
    """Nombre d'aides apportées par un membre (réputation). FAIL-OPEN : 0."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT helped_count FROM entraide_helper_stats "
                "WHERE guild_id=? AND user_id=?",
                (int(guild_id), int(user_id)),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception as ex:
        print(f"[entraide get_helper_count] {ex}")
        return 0


async def top_helpers(guild_id, limit=10) -> list:
    """Classement des aidants -> [(user_id, helped_count), …]. FAIL-OPEN : []."""
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, helped_count FROM entraide_helper_stats "
                "WHERE guild_id=? AND helped_count > 0 "
                "ORDER BY helped_count DESC LIMIT ?",
                (int(guild_id), int(limit)),
            ) as cur:
                return [(int(r[0]), int(r[1] or 0)) for r in await cur.fetchall()]
    except Exception as ex:
        print(f"[entraide top_helpers] {ex}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
#  TÂCHE PÉRIODIQUE (supervisée par bot.py — _SUPERVISED_MODULE_LOOPS)
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=30)
async def entraide_expiry_task():
    """Expire les demandes ouvertes trop vieilles de chaque serveur (dégorge la
    file + libère l'anti-spam). FAIL-OPEN : un bug ne tue pas la boucle (le
    superviseur la ressuscite). 30 min = réactif sans marteler la DB.

    Le nettoyage des posts/vocaux associés aux demandes expirées est laissé à
    bot.py (qui a les perms) : ici on se contente de changer le statut."""
    try:
        if _bot is None:
            return
        for guild in list(_bot.guilds):
            try:
                await expire_open_requests(guild.id, EXPIRE_OPEN_MIN)
            except Exception as ex:
                print(f"[entraide entraide_expiry_task guild] {ex}")
    except Exception as ex:
        print(f"[entraide entraide_expiry_task] {ex}")


__all__ = [
    "setup",
    "init_db",
    # catalogue
    "list_games",
    "get_game",
    "add_game",
    "set_game_helper_role",
    "remove_game",
    # rôle aidant
    "is_helper_role",
    "can_ping_helpers",
    "mark_helper_ping",
    # cycle de vie
    "create_request",
    "request_cooldown_remaining_sec",
    "get_request",
    "list_open_requests",
    "list_open_requests_for_game",
    "list_dangling_requests",
    "claim_request",
    "resolve_request",
    "list_stale_unclaimed_requests",
    "mark_request_relanced",
    "set_request_voice",
    "claim_request_voice_slot",
    "release_request_voice_slot",
    "clear_request_artifacts",
    "set_request_message",
    "expire_open_requests",
    # réputation
    "get_helper_count",
    "top_helpers",
    # tâche
    "entraide_expiry_task",
    # constantes
    "EXPIRE_OPEN_MIN",
    "RELANCE_AFTER_MIN",
    "HELPER_PING_COOLDOWN_SEC",
    "MAX_TEMP_VOICE_PER_GUILD",
    "HELP_REWARD_COINS",
    "REQUEST_COOLDOWN_MIN",
    "MAX_OPEN_REQUESTS_PER_GUILD",
    "CREATE_OK",
    "CREATE_DUPLICATE",
    "CREATE_UNKNOWN_GAME",
    "CREATE_DISABLED",
    "CREATE_COOLDOWN",
    "CREATE_GUILD_FULL",
]
