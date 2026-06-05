"""activity_system.py — Phase 235.25 : Système d'ACTIVITÉ (clé d'accès aux events).

Cahier des charges owner : pour PARTICIPER à un événement, il faut être VRAIMENT
actif sur le serveur. Le palier monte avec la rareté de l'event :

  🟢 Base          (Trésor Flash, Boîte mystère, Mob, Quiz)   = 3 points
  🟡 Intermédiaire (Boss du jour, Boss Raid)                  = 10 points
  🔴 Grandiose     (World Boss, Climax, Invasion)             = 25 points

Score = somme GLISSANTE sur 14 jours. 1 message = 1 point · 1 minute de vocal =
1 point, crédité en TEMPS RÉEL (le vocal COMPENSE l'écrit — soit l'un SEUL, soit
l'autre SEUL suffit). Ce gate s'ajoute AU-DESSUS du gate de niveau.

Principes :
- La barre n'est JAMAIS nulle mais TRIVIALE pour le base (3 messages ≈ rien,
  exclut juste les AFK total).
- HAUTE pour le grandiose (impossible à donner à quelqu'un de quasi-AFK).
- Messages de blocage ENCOURAGEANTS, jamais punitifs.
- Peu de notifs, tout est expliqué clairement dans le message de blocage.

Module AUTONOME : dépendances injectées via setup() (même patron que
mob_hunts / hero_journey). La CI ne voit pas les NameError runtime → on garde
tout défensif (FAIL-OPEN sur le gate : un bug n'empêche JAMAIS de jouer).
"""

from datetime import datetime, timezone, timedelta

# ─── Dépendances injectées ───
_get_db = None

# ─── Paliers d'activité (points) ───
TIER_BASE = 3
# Phase 235.32 : paliers ABAISSÉS (20→10, 60→25). Des membres clairement actifs
# étaient bloqués juste au bord du seuil. Combiné à la fenêtre 14 j + au crédit
# vocal en TEMPS RÉEL, « soit l'écrit SEUL, soit le vocal SEUL » suffit largement.
TIER_INTER = 10
TIER_GRAND = 25

TIER_LABELS = {
    TIER_BASE: "🟢 Base",
    TIER_INTER: "🟡 Intermédiaire",
    TIER_GRAND: "🔴 Grandiose",
}

# event_type (minuscules) -> palier requis
EVENT_TIERS = {
    # 🟢 Base — accessible avec un minimum d'activité (≈ 3 messages)
    "treasure": TIER_BASE,
    "flash_treasure": TIER_BASE,
    "mystery": TIER_BASE,
    "mystery_box": TIER_BASE,
    "mob": TIER_BASE,
    "quiz": TIER_BASE,
    "minigame": TIER_BASE,
    "riddle": TIER_BASE,
    # 🟡 Intermédiaire — demande une présence régulière
    "daily_boss": TIER_INTER,
    "boss": TIER_INTER,
    "boss_raid": TIER_INTER,
    "rift": TIER_INTER,  # Phase 256 Lot 3 : event collaboratif « Faille Convergente »
    # 🔴 Grandiose — réservé aux vrais actifs de la semaine
    "world_boss": TIER_GRAND,
    "climax": TIER_GRAND,
    "invasion": TIER_GRAND,
}

ROLLING_DAYS = 14         # Phase 235.32 : 7→14 j — l'activité s'ACCUMULE plus
                          # longtemps (plus besoin d'être actif TOUS les jours).
_CLEANUP_AFTER_DAYS = 62  # purge des buckets plus vieux que ça (> ROLLING_DAYS ;
                          # 62 j (≈2 mois) garantit que TOUT le mois précédent reste
                          # dispo pour le snapshot LAZY des titres saisonniers, même
                          # si le 1er /profile du mois arrive tard — cf. seasonal_titles.py)

# Phase 235.25b : anti double-comptage UNIQUEMENT. Avant, un debounce de 4 s
# « avalait » les messages rapprochés → « j'écris 3 messages mais il n'en compte
# que 2 » (bug signalé owner). Mis à 0 : CHAQUE message ≥ 2 caractères compte
# (le owner veut que « 3 messages = 3 points » soit fiable, même envoyés vite).
# L'anti-spam du serveur gère les abus ; farmer 60 pts = 60 messages = vraie
# activité de toute façon.
_MSG_DEBOUNCE_SECONDS = 0
_last_msg_ts: dict = {}   # (guild_id, user_id) -> datetime du dernier message compté

# Grâce de démarrage : tant qu'un serveur n'a pas ROLLING_DAYS jours de recul,
# on n'applique PAS les paliers élevés (🟡/🔴) — sinon, juste après l'activation,
# plus personne ne pourrait toucher un boss le temps que les scores grimpent.
# Le palier 🟢 (3) reste TOUJOURS appliqué (trivial, exclut juste les AFK total).
# Cache mémoire : une fois la fenêtre pleine, ça le reste.
_window_full_cache: dict = {}  # guild_id -> True


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _window_start() -> str:
    """Premier jour (inclus) de la fenêtre glissante, format 'YYYY-MM-DD'."""
    d = datetime.now(timezone.utc) - timedelta(days=ROLLING_DAYS - 1)
    return d.strftime("%Y-%m-%d")


def setup(get_db_fn):
    """Injecte le context manager DB (le même que bot.py : `async with get_db()`)."""
    global _get_db
    _get_db = get_db_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS activity_score ("
                "guild_id INTEGER, user_id INTEGER, day TEXT, "
                "points INTEGER DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id, day))"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_score_lookup "
                "ON activity_score(guild_id, user_id, day)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[activity init_db] {ex}")


async def _add_points(guild_id, user_id, points, *, day=None):
    if _get_db is None or points <= 0:
        return
    day = day or _today()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO activity_score (guild_id, user_id, day, points) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, day) "
                "DO UPDATE SET points = points + ?",
                (int(guild_id), int(user_id), day, int(points), int(points)),
            )
            await db.commit()
    except Exception as ex:
        print(f"[activity _add_points] {ex}")


async def get_score(guild_id, user_id) -> int:
    """Score d'activité glissant sur les 7 derniers jours."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(points), 0) FROM activity_score "
                "WHERE guild_id=? AND user_id=? AND day >= ?",
                (int(guild_id), int(user_id), _window_start()),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception as ex:
        print(f"[activity get_score] {ex}")
        return 0


async def top_scores(guild_id, limit=10):
    """Top N joueurs par score d'activité glissant (14 j) → [(user_id, points), …].

    Sert au classement « 🔥 Activité » (rend le gate d'accès aux events
    compétitif et visible). FAIL-OPEN : [] sur erreur."""
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, COALESCE(SUM(points), 0) AS pts FROM activity_score "
                "WHERE guild_id=? AND day >= ? GROUP BY user_id "
                "HAVING pts > 0 ORDER BY pts DESC LIMIT ?",
                (int(guild_id), _window_start(), int(limit)),
            ) as cur:
                return [(int(r[0]), int(r[1] or 0)) for r in await cur.fetchall()]
    except Exception as ex:
        print(f"[activity top_scores] {ex}")
        return []


def required_points(event_type) -> int:
    return EVENT_TIERS.get((event_type or "").lower(), TIER_BASE)


def tier_label(event_type) -> str:
    return TIER_LABELS.get(required_points(event_type), "🟢 Base")


async def _window_is_full(guild_id) -> bool:
    """True si le serveur a ≥ ROLLING_DAYS jours d'historique d'activité.

    Grâce de démarrage (cf. _window_full_cache) : tant que c'est faux, on ne
    bloque pas les paliers 🟡/🔴. Le palier 🟢 reste appliqué. FAIL-OPEN."""
    if _window_full_cache.get(guild_id):
        return True
    if _get_db is None:
        return True
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT MIN(day) FROM activity_score WHERE guild_id=?",
                (int(guild_id),),
            ) as cur:
                row = await cur.fetchone()
        if not row or not row[0]:
            return False
        first = datetime.strptime(row[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        full = (datetime.now(timezone.utc) - first).days >= (ROLLING_DAYS - 1)
        if full:
            _window_full_cache[guild_id] = True
        return full
    except Exception:
        return True


async def check_gate(guild_id, user_id, event_type):
    """Retourne (ok: bool, score: int, needed: int).

    FAIL-OPEN : toute erreur → (True, 0, 0). On ne bloque JAMAIS le combat sur un
    bug d'activité (sinon plus personne ne peut jouer → catastrophe). La pire
    conséquence d'un bug ici est juste "le gate ne filtre pas", pas "tout cassé".
    """
    try:
        needed = required_points(event_type)
        score = await get_score(guild_id, user_id)
        # Grâce de démarrage : paliers élevés non bloquants tant que la fenêtre
        # 7 j manque de recul (le palier 🟢 base, lui, est toujours appliqué).
        if needed > TIER_BASE and not await _window_is_full(guild_id):
            return (True, score, needed)
        return (score >= needed, score, needed)
    except Exception as ex:
        print(f"[activity check_gate] {ex}")
        return (True, 0, 0)


def block_message(event_type, score, needed) -> str:
    """Message ENCOURAGEANT (jamais punitif) affiché quand le palier manque."""
    missing = max(0, int(needed) - int(score))
    tier = TIER_LABELS.get(int(needed), "")
    base = (
        f"🌱 **Presque !** Cet événement {tier} demande "
        f"**{needed} points d'activité** sur 14 jours — tu en as **{score}**.\n"
    )
    if needed <= TIER_BASE:
        tip = (
            f"Il te manque **{missing}** tout petit point : écris 2-3 messages "
            f"et l'accès s'ouvre tout seul. 💬"
        )
    else:
        tip = (
            f"Il te manque **{missing}** : participe à la vie du serveur "
            f"(💬 1 message = 1 pt · 🔊 1 min vocal = 1 pt) et reviens — "
            f"l'accès s'ouvre automatiquement, sans rien à taper. 💪"
        )
    return base + tip


# ─── PRÉSENTATION (panneau « Mon activité » / profil / récap hebdo) ───
def render_bar(score, *, target=TIER_GRAND, segments=12) -> str:
    """Barre de progression visuelle vers le palier max (🔴 Grandiose = 60)."""
    try:
        t = max(1, int(target))
        frac = max(0.0, min(1.0, float(score) / t))
        filled = max(0, min(segments, int(round(frac * segments))))
        return "▰" * filled + "▱" * (segments - filled)
    except Exception:
        return "▱" * segments


async def profile_summary_text(guild_id, user_id, *, is_self=True) -> str:
    """Bloc texte « Mon activité (14 j) » : score + barre + paliers ouverts +
    prochain objectif clair (« +X messages pour débloquer 🟡 »).

    Réutilisable (profil, panneau dédié, récap hebdo). FAIL-OPEN : renvoie ''
    si quoi que ce soit échoue → le profil s'affiche quand même."""
    try:
        score = await get_score(guild_id, user_id)
        window_full = await _window_is_full(guild_id)
        bar = render_bar(score)

        base_ok = score >= TIER_BASE
        inter_ok = (not window_full) or score >= TIER_INTER
        grand_ok = (not window_full) or score >= TIER_GRAND

        def _mark(ok, need):
            return "✅ ouvert" if ok else f"🔒 {need} pts"

        lines = [
            f"**Score :** `{score}` pts  ·  _1 message = 1 pt · 1 min vocal = 1 pt_",
            bar,
            "",
            f"🟢 **Base** _(mob · trésor · quiz)_ — {_mark(base_ok, TIER_BASE)}",
            f"🟡 **Boss** _(boss du jour · raid)_ — {_mark(inter_ok, TIER_INTER)}",
            f"🔴 **Grandiose** _(world boss · climax · invasion)_ — {_mark(grand_ok, TIER_GRAND)}",
        ]

        if is_self:
            if not base_ok:
                miss = TIER_BASE - score
                lines.append(f"\n💬 **+{miss} message(s)** et les events 🟢 s'ouvrent !")
            elif window_full and not inter_ok:
                miss = TIER_INTER - score
                lines.append(f"\n💬 **+{miss} pts** pour débloquer les **Boss 🟡** "
                             f"(1 message OU 1 min vocal = 1 pt).")
            elif window_full and not grand_ok:
                miss = TIER_GRAND - score
                lines.append(f"\n💬 **+{miss} pts** pour débloquer le **Grandiose 🔴**.")
            elif not window_full:
                lines.append("\n🎁 _Grâce de démarrage : 🟡/🔴 ouverts en attendant "
                             "14 j d'historique d'activité._")
            else:
                lines.append("\n🌟 **Tous les events te sont ouverts — continue comme ça !**")

        return "\n".join(lines)
    except Exception as ex:
        print(f"[activity profile_summary_text] {ex}")
        return ""


# ─── HOOKS DE COLLECTE ───
async def on_message_activity(message):
    """Listener ADDITIF sur on_message : +1 point / message (debounce anti-spam).

    À enregistrer via bot.add_listener(on_message_activity, "on_message") — JAMAIS
    en @bot.event (écraserait le handler principal, cf. règle mémoire)."""
    try:
        if _get_db is None:
            return
        if getattr(message, "guild", None) is None:
            return
        author = getattr(message, "author", None)
        if author is None or getattr(author, "bot", False):
            return
        content = (getattr(message, "content", "") or "").strip()
        if len(content) < 2:
            return
        key = (message.guild.id, author.id)
        now = datetime.now(timezone.utc)
        last = _last_msg_ts.get(key)
        if last is not None and (now - last).total_seconds() < _MSG_DEBOUNCE_SECONDS:
            return
        _last_msg_ts[key] = now
        await _add_points(message.guild.id, author.id, 1)
    except Exception as ex:
        print(f"[activity on_message] {ex}")


async def add_voice_minutes(guild_id, user_id, minutes):
    """Appelé par le tracker vocal existant (déjà anti-AFK) : +1 point / minute."""
    try:
        m = int(minutes or 0)
        if m > 0:
            await _add_points(guild_id, user_id, m)
    except Exception as ex:
        print(f"[activity add_voice_minutes] {ex}")


async def cleanup_old():
    """Purge des buckets de plus de _CLEANUP_AFTER_DAYS jours (table reste minuscule)."""
    if _get_db is None:
        return
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=_CLEANUP_AFTER_DAYS)).strftime("%Y-%m-%d")
        async with _get_db() as db:
            await db.execute("DELETE FROM activity_score WHERE day < ?", (cutoff,))
            await db.commit()
    except Exception as ex:
        print(f"[activity cleanup_old] {ex}")
