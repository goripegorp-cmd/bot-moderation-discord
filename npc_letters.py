"""
npc_letters.py — Lettres NPC hebdomadaires en DM (Phase 170.7).

🎯 OBJECTIF : ramener les joueurs INACTIFS vers le serveur via une
narration personnelle. Chaque dimanche 18h FR, UN NPC écrit une lettre
qui est envoyée en DM aux membres opt-in. Le contenu dépend du mood
INDIVIDUEL de chaque destinataire avec ce NPC.

PHILOSOPHIE :
- Opt-in strict (RGPD-friendly). Aucun DM sans consentement explicite.
- 1 lettre/semaine max par destinataire (anti-spam TOS Discord).
- Contenu personnalisé : un user qui méprise Korr reçoit une lettre froide.
  Un user fidèle à Aria reçoit une lettre intime.
- Aucun appel à l'action explicite. Juste de la narration.
- Si DM bloqué → log silencieux, pas de retry agressif.

MÉCANIQUE :
- Sélection du NPC de la semaine : rotation hebdomadaire dans l'ordre
  des 6 NPCs (Aria → Korr → Lyra → Drazek → Sienna → Voyageur → Aria…).
- Pour chaque user opt-in actif (≥1 action dans les 30j) :
  • Lit son mood avec le NPC choisi
  • Sélectionne une lettre parmi les templates qui matchent (mood + Acte)
  • Envoie en DM
- Si l'user n'a aucune activité dans 30j → skip (pas d'effort sur fantômes)

OPT-IN/OUT :
- Bouton dans le Codex : "✉️ Abonnement aux lettres"
- Toggle on/off via panel V2 dédié

API publique :
- setup(bot, get_db, db_get, v2, story_module, npc_module)
- init_db()
- LETTER_CATALOG, get_letter_def, list_letter_ids
- is_subscribed(guild_id, user_id) → bool
- subscribe(guild_id, user_id), unsubscribe(guild_id, user_id)
- toggle_subscription(guild_id, user_id) → new state
- get_letters_history(guild_id, user_id, limit=10) → list
- weekly_letter_task (loop hourly, fires dimanche 18h FR)
- generate_and_send_letters_for_guild(guild_id) → int (count sent)
- build_letters_panel(guild_id, user_id) → LayoutView
- open_letters_from_codex(interaction) → None
- LetterToggleButton (DynamicItem persistent)
- register_persistent_views(bot)

DB :
- npc_letter_subscriptions (guild_id, user_id, subscribed_at)
                            PRIMARY KEY (guild_id, user_id)
- npc_letters_sent (id PK, guild_id, user_id, npc_id, week_key,
                    letter_id, sent_at, delivered)
"""
from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord.ext import tasks
from discord.ui import Button

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_story = None
_npc = None

LETTER_WEEKDAY = 6   # dimanche
LETTER_HOUR = 18     # 18h FR
ACTIVE_WINDOW_DAYS = 30  # un user doit avoir bougé dans les 30j

# Rotation des NPCs (ordre déterministe par semaine)
NPC_ROTATION = ["aria", "korr", "lyra", "drazek", "sienna", "voyageur"]


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE LETTRES — 3 par NPC × 6 NPCs = 18 lettres
# ═══════════════════════════════════════════════════════════════════════════
# Structure :
# - id : unique
# - npc_id : référence NPC
# - mood_min, mood_max : plage de mood acceptée
# - subject : ligne d'objet (titre du DM)
# - body : corps de la lettre (markdown, multilignes)

LETTER_CATALOG = [
    # ─── ARIA ───
    {
        "id": "aria_low",
        "npc_id": "aria",
        "mood_min": 0, "mood_max": 39,
        "subject": "Un mot, malgré tout",
        "body": (
            "Je t'écris cette lettre sans certitude que tu la lises.\n\n"
            "Nos chemins se sont peu croisés. C'est dans l'ordre. La Veille "
            "n'attire pas tous les voyageurs, et je ne te juge pas pour ton "
            "éloignement.\n\n"
            "Sache simplement ceci : si un jour la cendre devient trop "
            "lourde, la Tour reste ouverte. Sans question. Sans dette.\n\n"
            "Veille bien sur toi.\n\n"
            "_— Aria, la Veilleuse_"
        ),
    },
    {
        "id": "aria_mid",
        "npc_id": "aria",
        "mood_min": 40, "mood_max": 69,
        "subject": "Pensées d'une semaine étrange",
        "body": (
            "Voyageur,\n\n"
            "La semaine fut tissée de présages. J'ai vu trois oiseaux noirs "
            "tourner au-dessus du Sanctuaire à l'aube. Quelque chose se "
            "prépare, mais je n'ose encore nommer quoi.\n\n"
            "Le serveur avance. Vous avancez. C'est l'essentiel.\n\n"
            "J'aimerais te revoir bientôt. Une heure, sans hâte. Pour parler "
            "de ce qui ne se dit pas en pleine lumière.\n\n"
            "Si tu acceptes, viens. Sinon, sache que je ne t'en voudrai pas.\n\n"
            "_— Aria_"
        ),
    },
    {
        "id": "aria_high",
        "npc_id": "aria",
        "mood_min": 70, "mood_max": 100,
        "subject": "À toi qui écoutes",
        "body": (
            "Mon cher voyageur,\n\n"
            "La nuit dernière, j'ai rêvé encore. Les cendres dansaient mais "
            "cette fois, elles formaient des mots. Tes mots, à toi qui "
            "m'écoutes depuis si longtemps.\n\n"
            "Tu sais voir ce que peu voient. Et tu sais te taire quand le "
            "silence est juste. Ces qualités-là sont rares.\n\n"
            "Le serveur a fait des choix qui me surprennent — certains que "
            "je n'aurais pas faits seule. Mais c'est cela, peut-être, le "
            "sens de la Veille : laisser les autres tracer leur route.\n\n"
            "J'aurai besoin de toi bientôt. Pas maintenant. Mais bientôt. "
            "Sache que je te ferai signe.\n\n"
            "_— Aria, qui veille avec toi_"
        ),
    },

    # ─── KORR ───
    {
        "id": "korr_low",
        "npc_id": "korr",
        "mood_min": 0, "mood_max": 39,
        "subject": "Sans détour",
        "body": (
            "Tu sais ce que je pense. Pas de détour.\n\n"
            "Tu n'es pas venu à la forge depuis longtemps. C'est ton droit. "
            "Mais quand tu reviendras — si tu reviens — sache que je "
            "t'attends. Pas avec amitié, mais avec respect du chemin qui "
            "sépare nos voies.\n\n"
            "La porte reste ouverte.\n\n"
            "_— Korr_"
        ),
    },
    {
        "id": "korr_mid",
        "npc_id": "korr",
        "mood_min": 40, "mood_max": 69,
        "subject": "Au sujet de la forge",
        "body": (
            "Voyageur,\n\n"
            "La forge tourne. Le minerai entre, l'acier sort. Cette semaine, "
            "j'ai fini une hache pour un voyageur du Nord. Belle pièce. "
            "Solide.\n\n"
            "Toi aussi tu mérites une bonne lame, je crois. Passe quand tu "
            "veux. On verra ensemble ce qui te convient.\n\n"
            "J'ai aussi de l'hydromel. Pas le pire.\n\n"
            "_— Korr, le forgeron_"
        ),
    },
    {
        "id": "korr_high",
        "npc_id": "korr",
        "mood_min": 70, "mood_max": 100,
        "subject": "Mon ami",
        "body": (
            "Voyageur,\n\n"
            "Je ne suis pas un homme de longs mots. Tu le sais.\n\n"
            "Cette semaine j'ai pensé à toi. Tu m'as aidé quand j'en avais "
            "besoin, et je n'oublie pas ces choses-là. Quand un homme tient "
            "parole, on garde sa parole en mémoire.\n\n"
            "J'ai forgé un anneau de fer ce matin. Un anneau simple, rien "
            "de magique. Mais je l'ai forgé en pensant à toi. Quand tu "
            "passes, il est à toi.\n\n"
            "Bonne semaine, voyageur. Et que ta hache reste affûtée.\n\n"
            "_— Korr, ton ami_"
        ),
    },

    # ─── LYRA ───
    {
        "id": "lyra_low",
        "npc_id": "lyra",
        "mood_min": 0, "mood_max": 39,
        "subject": "Note académique",
        "body": (
            "Voyageur,\n\n"
            "Je vous écris formellement car nous n'avons pas développé une "
            "relation propice à plus d'intimité.\n\n"
            "Mes recherches avancent. La Bibliothèque Sous-Vide révèle des "
            "secrets que je consigne pour les âges futurs. Vous n'êtes pas "
            "obligé de vous y intéresser.\n\n"
            "Bonne continuation dans vos affaires.\n\n"
            "_— Lyra, érudite_"
        ),
    },
    {
        "id": "lyra_mid",
        "npc_id": "lyra",
        "mood_min": 40, "mood_max": 69,
        "subject": "Une découverte récente",
        "body": (
            "Voyageur,\n\n"
            "Je viens de finir la traduction d'un fragment de tablette "
            "trouvée dans les Profondes. Le texte parle d'un sceau qui se "
            "nourrit de mémoire. Étrange concept.\n\n"
            "J'aimerais en discuter avec quelqu'un qui sache poser les "
            "bonnes questions. Toi, peut-être ? Tu as cette qualité d'écouter "
            "sans interrompre — c'est rare.\n\n"
            "Réfléchis-y.\n\n"
            "_— Lyra_"
        ),
    },
    {
        "id": "lyra_high",
        "npc_id": "lyra",
        "mood_min": 70, "mood_max": 100,
        "subject": "À mon complice intellectuel",
        "body": (
            "Cher voyageur,\n\n"
            "J'ai franchi un seuil cette semaine. Le grimoire interdit a "
            "parlé pour la première fois. Je n'écrirai pas ce qu'il a dit "
            "dans cette lettre — c'est trop dangereux pour le papier.\n\n"
            "Mais à toi, je le confierai. Bientôt. Quand nous serons seuls. "
            "Tu es le seul ici à qui je peux dire ces choses sans craindre "
            "le jugement.\n\n"
            "Le monde change plus vite que les autres ne le voient. Toi "
            "et moi, nous voyons les fissures.\n\n"
            "À très bientôt, mon complice.\n\n"
            "_— Lyra, qui sait qui tu es_"
        ),
    },

    # ─── DRAZEK ───
    {
        "id": "drazek_low",
        "npc_id": "drazek",
        "mood_min": 0, "mood_max": 39,
        "subject": "Sans façon",
        "body": (
            "Voyageur.\n\n"
            "Je n'écris pas pour pleurer. J'écris pour qu'on soit clair.\n\n"
            "Tu n'as pas fait tes preuves devant moi. Pas grave. Tu n'es "
            "pas obligé. Mais ne t'attends pas à ma confiance.\n\n"
            "Si un jour tu veux la gagner, tu sais où me trouver. Le Pic "
            "Rouge n'est pas loin.\n\n"
            "_— Drazek_"
        ),
    },
    {
        "id": "drazek_mid",
        "npc_id": "drazek",
        "mood_min": 40, "mood_max": 69,
        "subject": "Au sujet de l'entraînement",
        "body": (
            "Voyageur,\n\n"
            "L'épée pèse plus lourd que la semaine dernière. Ou peut-être "
            "que je vieillis. Sans doute les deux.\n\n"
            "Si tu cherches à t'entraîner, monte au Pic Rouge. Je suis là, "
            "à l'aube et au crépuscule. Je ne pose pas de questions. Je "
            "frappe.\n\n"
            "Tu pourrais apprendre des choses utiles.\n\n"
            "_— Drazek, le guerrier_"
        ),
    },
    {
        "id": "drazek_high",
        "npc_id": "drazek",
        "mood_min": 70, "mood_max": 100,
        "subject": "Frère d'armes",
        "body": (
            "Mon frère d'armes,\n\n"
            "La cicatrice neuve me fait moins mal cette semaine. C'est bon "
            "signe. Ou alors j'apprends juste à la porter.\n\n"
            "Tu as été là quand peu l'auraient été. Je n'oublie pas. Un "
            "guerrier reconnaît son égal. Et toi, tu en es un — même si tu "
            "ne brandis jamais d'arme.\n\n"
            "Quand viendra le moment, je serai à tes côtés. Pas pour la "
            "gloire. Pour la dette.\n\n"
            "À la vie, à la mort.\n\n"
            "_— Drazek, ton frère_"
        ),
    },

    # ─── SIENNA ───
    {
        "id": "sienna_low",
        "npc_id": "sienna",
        "mood_min": 0, "mood_max": 39,
        "subject": "Bonjour, client",
        "body": (
            "Cher client,\n\n"
            "Vous n'êtes pas devenu un partenaire commercial régulier. Je "
            "le note sans amertume — chaque âme suit son cours.\n\n"
            "Mes prix sont les mêmes pour tous. Si vous changez d'avis, je "
            "suis là. Je n'oublie rien, ni les insultes, ni les dettes.\n\n"
            "Bonne semaine.\n\n"
            "_— Sienna, marchande_"
        ),
    },
    {
        "id": "sienna_mid",
        "npc_id": "sienna",
        "mood_min": 40, "mood_max": 69,
        "subject": "Offre de la semaine",
        "body": (
            "Voyageur,\n\n"
            "Cette semaine, j'ai en stock un parchemin venu d'au-delà de la "
            "mer. Curieux objet. Je ne sais pas ce qu'il dit, mais il vaut "
            "son prix.\n\n"
            "Vous m'avez toujours traitée avec respect. Pour vous, je peux "
            "négocier — un peu. Pas trop. Une marchande reste une marchande.\n\n"
            "Passez à la caravane si l'envie vous prend.\n\n"
            "_— Sienna_"
        ),
    },
    {
        "id": "sienna_high",
        "npc_id": "sienna",
        "mood_min": 70, "mood_max": 100,
        "subject": "Une lettre que je ne facture pas",
        "body": (
            "Mon ami voyageur,\n\n"
            "Je n'écris pas souvent des lettres gratuites. Celle-ci est "
            "pour toi.\n\n"
            "Tu m'as aidée quand le marché brûlait. Tu m'as donné quand "
            "je n'attendais rien. Ces choses-là changent une marchande. "
            "Elles changent aussi une amie.\n\n"
            "J'ai mis de côté pour toi un objet qui ne sera pas mis en "
            "vitrine. Il est à toi quand tu passes. Pas un caprice, un don.\n\n"
            "La caravane t'attend.\n\n"
            "_— Sienna, qui te garde dans son coeur de marchande_"
        ),
    },

    # ─── LE VOYAGEUR ───
    {
        "id": "voyageur_low",
        "npc_id": "voyageur",
        "mood_min": 0, "mood_max": 39,
        "subject": "_",
        "body": (
            "_Une enveloppe sans expéditeur. À l'intérieur, une simple ligne :_\n\n"
            "« Je te vois. »\n\n"
            "_— Aucune signature_"
        ),
    },
    {
        "id": "voyageur_mid",
        "npc_id": "voyageur",
        "mood_min": 40, "mood_max": 69,
        "subject": "Lettre sans nom",
        "body": (
            "Voyageur,\n\n"
            "Tu commences à comprendre. Peut-être pas tout. Mais tu vois "
            "les fissures. C'est rare. La plupart des gens regardent le mur "
            "sans voir les fissures.\n\n"
            "Continue. Mais sois prudent. La porte que tu cherches s'ouvre "
            "dans les deux sens.\n\n"
            "On se reverra.\n\n"
            "_— L'autre toi_"
        ),
    },
    {
        "id": "voyageur_high",
        "npc_id": "voyageur",
        "mood_min": 70, "mood_max": 100,
        "subject": "Toi, plus tard",
        "body": (
            "Voyageur,\n\n"
            "Tu as fait le bon choix. La semaine dernière, l'autre fois. Tu "
            "ne le sais pas encore, mais je le sais — je l'ai déjà vécu.\n\n"
            "Cette boucle-ci sera différente grâce à toi. Pas parce que tu "
            "es héroïque — mais parce que tu écoutes. C'est plus rare que "
            "le héroïsme.\n\n"
            "Je serai là à la fin. Pas pour te sauver. Pour te dire que "
            "tu as réussi.\n\n"
            "À très bientôt, mon vieux moi.\n\n"
            "_— Le Voyageur_"
        ),
    },
]


def get_letter_def(letter_id: str) -> Optional[dict]:
    for ltr in LETTER_CATALOG:
        if ltr["id"] == letter_id:
            return ltr
    return None


def list_letter_ids() -> list[str]:
    return [ltr["id"] for ltr in LETTER_CATALOG]


def get_letters_for_npc(npc_id: str) -> list[dict]:
    return [ltr for ltr in LETTER_CATALOG if ltr["npc_id"] == npc_id]


# ═══════════════════════════════════════════════════════════════════════════
#  Setup + DB
# ═══════════════════════════════════════════════════════════════════════════

def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    story_module=None, npc_module=None,
):
    global _bot, _get_db, _db_get, _v2, _story, _npc
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _story = story_module
    _npc = npc_module


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS npc_letter_subscriptions (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS npc_letters_sent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    npc_id TEXT NOT NULL,
                    week_key TEXT NOT NULL,
                    letter_id TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    delivered INTEGER DEFAULT 1
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_letters_recent "
                "ON npc_letters_sent(guild_id, user_id, sent_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_letters_week "
                "ON npc_letters_sent(guild_id, week_key)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[npc_letters init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Subscription API
# ═══════════════════════════════════════════════════════════════════════════

async def is_subscribed(guild_id: int, user_id: int) -> bool:
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM npc_letter_subscriptions "
                "WHERE guild_id=? AND user_id=? LIMIT 1",
                (guild_id, user_id),
            ) as cur:
                return await cur.fetchone() is not None
    except Exception:
        return False


async def subscribe(guild_id: int, user_id: int) -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO npc_letter_subscriptions "
                "(guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            await db.commit()
    except Exception:
        pass


async def unsubscribe(guild_id: int, user_id: int) -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "DELETE FROM npc_letter_subscriptions "
                "WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            await db.commit()
    except Exception:
        pass


async def toggle_subscription(guild_id: int, user_id: int) -> bool:
    """Toggle on/off. Retourne le nouvel état."""
    if await is_subscribed(guild_id, user_id):
        await unsubscribe(guild_id, user_id)
        return False
    await subscribe(guild_id, user_id)
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  History
# ═══════════════════════════════════════════════════════════════════════════

async def get_letters_history(
    guild_id: int, user_id: int, limit: int = 10,
) -> list[dict]:
    if _get_db is None:
        return []
    out = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT npc_id, week_key, letter_id, sent_at, delivered "
                "FROM npc_letters_sent "
                "WHERE guild_id=? AND user_id=? "
                "ORDER BY id DESC LIMIT ?",
                (guild_id, user_id, int(limit)),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            out.append({
                "npc_id": r[0],
                "week_key": r[1],
                "letter_id": r[2],
                "sent_at": r[3],
                "delivered": bool(r[4]),
            })
    except Exception:
        pass
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Send letters logic
# ═══════════════════════════════════════════════════════════════════════════

def _paris_now() -> datetime:
    if _PARIS_TZ:
        return datetime.now(_PARIS_TZ)
    return datetime.now(timezone.utc) + timedelta(hours=2)


def _current_week_key() -> str:
    """ISO week key (YYYY-Www) basé sur Paris."""
    now = _paris_now()
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _is_send_window() -> bool:
    """True si on est dimanche 18h FR."""
    now = _paris_now()
    return now.weekday() == LETTER_WEEKDAY and now.hour == LETTER_HOUR


def _pick_npc_for_week() -> str:
    """Sélectionne le NPC de la semaine via rotation déterministe."""
    now = _paris_now()
    iso = now.isocalendar()
    week_num = iso[1]
    return NPC_ROTATION[week_num % len(NPC_ROTATION)]


async def _pick_letter_for_mood(npc_id: str, mood: int) -> Optional[dict]:
    """Sélectionne une lettre dont la plage mood correspond."""
    candidates = [
        ltr for ltr in LETTER_CATALOG
        if ltr["npc_id"] == npc_id
        and ltr["mood_min"] <= mood <= ltr["mood_max"]
    ]
    if not candidates:
        # Fallback : tout NPC, mood mid
        candidates = [
            ltr for ltr in LETTER_CATALOG
            if ltr["npc_id"] == npc_id and ltr["mood_min"] <= 50 <= ltr["mood_max"]
        ]
    if not candidates:
        return None
    return random.choice(candidates)


async def _user_was_active(guild_id: int, user_id: int) -> bool:
    """True si l'user a fait au moins 1 action dans les ACTIVE_WINDOW_DAYS derniers j.

    Utilise daily_encounters_log + chronicle_contributors comme proxies.
    """
    if _get_db is None:
        return True  # fail-open : si on ne peut pas vérifier, on envoie quand même
    try:
        threshold = (
            datetime.now(timezone.utc) - timedelta(days=ACTIVE_WINDOW_DAYS)
        ).isoformat()
        async with _get_db() as db:
            # Check encounters
            async with db.execute(
                "SELECT 1 FROM daily_encounters_log "
                "WHERE guild_id=? AND user_id=? AND played_at > ? LIMIT 1",
                (guild_id, user_id, threshold),
            ) as cur:
                if await cur.fetchone():
                    return True
            # Check contributors
            async with db.execute(
                "SELECT 1 FROM chronicle_contributors "
                "WHERE guild_id=? AND user_id=? AND last_action_at > ? LIMIT 1",
                (guild_id, user_id, threshold),
            ) as cur:
                if await cur.fetchone():
                    return True
        return False
    except Exception:
        return True  # fail-open


async def _already_received_this_week(
    guild_id: int, user_id: int, week_key: str,
) -> bool:
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM npc_letters_sent "
                "WHERE guild_id=? AND user_id=? AND week_key=? LIMIT 1",
                (guild_id, user_id, week_key),
            ) as cur:
                return await cur.fetchone() is not None
    except Exception:
        return False


async def _send_letter_to_user(
    guild: discord.Guild, user_id: int, letter: dict, npc_id: str,
) -> bool:
    """Envoie le DM. Retourne True si livré."""
    member = guild.get_member(user_id)
    if not member or member.bot:
        return False
    npc_def = {}
    if _npc is not None:
        npc_def = _npc.get_npc_def(npc_id) or {}

    embed = discord.Embed(
        title=f"{npc_def.get('emoji', '✉️')} {letter['subject']}",
        description=letter["body"],
        color=0x6D4C41,
    )
    embed.set_footer(
        text=f"Lettre de {npc_def.get('name', '?')} · "
             f"{npc_def.get('title', '')}\n"
             "💡 Tu peux te désabonner via 📖 Chronique → ✉️ Lettres."
    )
    try:
        await member.send(embed=embed)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False
    except Exception as ex:
        print(f"[npc_letters send_letter to {user_id}] {ex}")
        return False


async def generate_and_send_letters_for_guild(guild_id: int) -> int:
    """Envoie les lettres de la semaine aux abonnés actifs. Retourne le count."""
    # Phase 257 : LETTRES PNJ EN MP DÉSACTIVÉES (directive owner — zéro MP membre).
    return 0
    if _bot is None or _get_db is None:
        return 0
    guild = _bot.get_guild(guild_id)
    if not guild:
        return 0

    npc_id = _pick_npc_for_week()
    week_key = _current_week_key()
    sent_count = 0
    # FIX audit : THROTTLE + CAP anti mass-DM (ToS Discord). Sans espacement, on
    # balançait les DM des abonnés en rafale → risque de rate-limit / flag « envoi
    # massif ». On espace chaque DM (~1.2 s) et on borne le nombre par passage ;
    # le surplus éventuel attend la semaine suivante (cadence hebdo, opt-in strict).
    _MAX_LETTERS_PER_RUN = 40
    _DM_THROTTLE_SECONDS = 1.2
    attempts = 0

    # Lire les abonnés
    subscribers: list[int] = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id FROM npc_letter_subscriptions WHERE guild_id=?",
                (guild_id,),
            ) as cur:
                subscribers = [int(r[0]) for r in await cur.fetchall()]
    except Exception:
        return 0

    for uid in subscribers:
        try:
            # Anti-doublon : déjà reçu cette semaine ?
            if await _already_received_this_week(guild_id, uid, week_key):
                continue
            # Vérifie activité récente
            if not await _user_was_active(guild_id, uid):
                continue
            # Mood
            mood = 50
            if _npc is not None:
                try:
                    mood = await _npc.get_mood(guild_id, uid, npc_id)
                except Exception:
                    pass
            # Pick letter
            letter = await _pick_letter_for_mood(npc_id, mood)
            if not letter:
                continue
            # Cap par passage : ne jamais balancer des centaines de DM d'un coup.
            if attempts >= _MAX_LETTERS_PER_RUN:
                print(f"[npc_letters] cap {_MAX_LETTERS_PER_RUN} DM atteint "
                      f"guild={guild_id} — reste reporté à la semaine prochaine")
                break
            # Send
            delivered = await _send_letter_to_user(guild, uid, letter, npc_id)
            attempts += 1
            # Log
            try:
                async with _get_db() as db:
                    await db.execute(
                        "INSERT INTO npc_letters_sent "
                        "(guild_id, user_id, npc_id, week_key, letter_id, "
                        "delivered) VALUES (?, ?, ?, ?, ?, ?)",
                        (guild_id, uid, npc_id, week_key, letter["id"],
                         1 if delivered else 0),
                    )
                    await db.commit()
            except Exception:
                pass
            if delivered:
                sent_count += 1
            # Throttle : espacer les DM (anti rate-limit / anti-flag mass-DM Discord).
            await asyncio.sleep(_DM_THROTTLE_SECONDS)
        except Exception as ex:
            print(f"[generate_and_send g={guild_id} u={uid}] {ex}")
            continue

    # Log dans le Codex
    if _story is not None and sent_count > 0:
        try:
            await _story.log_chronicle_event(
                guild_id, "letters_sent",
                {"npc_id": npc_id, "week_key": week_key, "count": sent_count},
            )
        except Exception:
            pass

    print(
        f"[npc_letters] sent guild={guild_id} npc={npc_id} "
        f"week={week_key} count={sent_count}/{len(subscribers)}"
    )
    return sent_count


# ═══════════════════════════════════════════════════════════════════════════
#  V2 panel
# ═══════════════════════════════════════════════════════════════════════════

async def build_letters_panel(
    guild_id: int, user_id: int,
) -> Optional[discord.ui.LayoutView]:
    if _v2 is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    subscribed = await is_subscribed(guild_id, user_id)
    history = await get_letters_history(guild_id, user_id, limit=8)

    items = [v2_title("✉️ Lettres des NPCs")]
    items.append(v2_subtitle(
        f"_Chaque dimanche 18h FR, un NPC t'écrit en DM (contenu selon ton mood)._"
    ))
    items.append(v2_divider())

    if subscribed:
        items.append(v2_body(
            "🟢 **Tu es abonné aux lettres.**\n\n"
            "_Tu recevras 1 lettre/semaine, sauf si tu n'as fait aucune "
            "action dans les 30 derniers jours._\n\n"
            "_Si Discord refuse le DM (paramètres serveur ou tes DMs "
            "fermés), aucune lettre n'arrivera — sans erreur ni notification._"
        ))
    else:
        items.append(v2_body(
            "🔴 **Tu n'es pas abonné aux lettres.**\n\n"
            "_Abonne-toi pour recevoir les lettres en DM (désabonnable à tout moment)._\n\n"
            "_RGPD : opt-in strict, aucun DM sans consentement._"
        ))

    items.append(v2_divider())

    # NPC de la semaine
    npc_id_week = _pick_npc_for_week()
    if _npc is not None:
        npc_def = _npc.get_npc_def(npc_id_week) or {}
        items.append(v2_body(
            f"📅 **NPC de la semaine** : {npc_def.get('emoji', '?')} "
            f"**{npc_def.get('name', '?')}** ({npc_def.get('title', '')})\n"
            f"_Rotation déterministe — Aria → Korr → Lyra → Drazek → "
            f"Sienna → Voyageur._"
        ))
        items.append(v2_divider())

    # Historique
    items.append(v2_body("**📜 Tes lettres récentes**"))
    if not history:
        items.append(v2_body(
            "_Tu n'as encore reçu aucune lettre. Abonne-toi et patiente "
            "jusqu'à dimanche 18h FR._"
        ))
    else:
        for h in history:
            ltr = get_letter_def(h["letter_id"]) if h["letter_id"] else None
            npc_def = (_npc.get_npc_def(h["npc_id"]) if _npc else {}) or {}
            delivered_tag = "" if h["delivered"] else " ⚠️ _non livré_"
            subject = (ltr["subject"] if ltr else "(supprimé)")
            items.append(v2_body(
                f"{npc_def.get('emoji', '?')} **{npc_def.get('name', '?')}** "
                f"· *{subject}* · `{h['week_key']}`{delivered_tag}"
            ))

    class _LettersLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0x6D4C41))

    layout = _LettersLayout()
    # Phase 208 FIX : bouton dans un ActionRow (type 1). Un Button/DynamicItem
    # brut au top-level d'un LayoutView V2 = 400 "Invalid Form Body". On crée un
    # Button BRUT avec le MÊME label/style/custom_id que LetterToggleButton
    # (DynamicItem) ; le clic reste capté par le DynamicItem enregistré.
    btn = Button(
        label=("🔴 Se désabonner" if subscribed else "🟢 S'abonner"),
        style=(discord.ButtonStyle.danger if subscribed
               else discord.ButtonStyle.success),
        custom_id=f"letter_toggle:{user_id}",
    )
    layout.add_item(discord.ui.ActionRow(btn))
    return layout


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent button
# ═══════════════════════════════════════════════════════════════════════════

class LetterToggleButton(
    discord.ui.DynamicItem[Button],
    template=r"letter_toggle:(?P<user_id>\d+)",
):
    """Toggle subscription (persistent)."""

    def __init__(self, user_id: int, currently_subscribed: bool = False):
        label = "🔴 Se désabonner" if currently_subscribed else "🟢 S'abonner"
        style = (discord.ButtonStyle.danger if currently_subscribed
                 else discord.ButtonStyle.success)
        super().__init__(
            Button(
                label=label,
                style=style,
                custom_id=f"letter_toggle:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre tes propres lettres depuis le Codex.",
                    ephemeral=True,
                )
            except Exception:
                return

        try:
            await btn_i.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
            pass

        if btn_i.guild is None:
            try:
                await btn_i.followup.send("❌ Serveur uniquement.", ephemeral=True)
            except Exception:
                pass
            return

        try:
            new_state = await toggle_subscription(btn_i.guild.id, btn_i.user.id)
            view = await build_letters_panel(btn_i.guild.id, btn_i.user.id)
            confirm = (
                "🟢 **Abonnement activé.** Tu recevras la prochaine lettre "
                "dimanche 18h FR."
                if new_state else
                "🔴 **Abonnement coupé.** Tu ne recevras plus de DM."
            )
            if view:
                try:
                    await btn_i.edit_original_response(
                        view=view, content=None, attachments=[],
                    )
                except Exception:
                    pass
            try:
                await btn_i.followup.send(confirm, ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            print(f"[letter_toggle callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(LetterToggleButton)
    except Exception as ex:
        print(f"[npc_letters register_persistent_views] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Task loop
# ═══════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=20)
async def weekly_letter_task():
    """Toutes les 20 min : si dimanche 18h FR, envoie les lettres."""
    if _bot is None:
        return
    try:
        if not _is_send_window():
            return
        for guild in _bot.guilds:
            try:
                await generate_and_send_letters_for_guild(guild.id)
            except Exception as ex:
                print(f"[weekly_letter_task g={guild.id}] {ex}")
    except Exception as ex:
        print(f"[weekly_letter_task] {ex}")


@weekly_letter_task.before_loop
async def _letters_wait_ready():
    if _bot is not None:
        await _bot.wait_until_ready()


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point depuis le Codex
# ═══════════════════════════════════════════════════════════════════════════

async def open_letters_from_codex(interaction: discord.Interaction) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        pass
    except Exception as ex:
        print(f"[open_letters_from_codex defer] {ex}")

    if interaction.guild is None:
        try:
            await interaction.followup.send("❌ Serveur uniquement.", ephemeral=True)
        except Exception:
            pass
        return

    try:
        view = await build_letters_panel(interaction.guild.id, interaction.user.id)
        if view is None:
            await interaction.followup.send(
                "❌ Lettres indisponibles.", ephemeral=True
            )
            return
        await interaction.followup.send(view=view, ephemeral=True)
    except Exception as ex:
        print(f"[open_letters_from_codex] {ex}")
        try:
            await interaction.followup.send(
                f"❌ Erreur : `{ex}`", ephemeral=True,
            )
        except Exception:
            pass


__all__ = [
    "LETTER_CATALOG",
    "LETTER_WEEKDAY",
    "LETTER_HOUR",
    "ACTIVE_WINDOW_DAYS",
    "NPC_ROTATION",
    "setup",
    "init_db",
    "get_letter_def",
    "list_letter_ids",
    "get_letters_for_npc",
    "is_subscribed",
    "subscribe",
    "unsubscribe",
    "toggle_subscription",
    "get_letters_history",
    "generate_and_send_letters_for_guild",
    "build_letters_panel",
    "open_letters_from_codex",
    "LetterToggleButton",
    "weekly_letter_task",
    "register_persistent_views",
]
