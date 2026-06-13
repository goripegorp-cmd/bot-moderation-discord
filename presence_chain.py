"""presence_chain.py — Chaîne collective de présence quotidienne (compteur SERVEUR).

Cahier des charges owner :
- Compteur SERVEUR (pas par-user). Chaque jour où AU MOINS N membres DISTINCTS
  sont actifs (réutilise le tracking d'activité existant : activity_system /
  activity_tracking — 1 message OU 1 min de vocal = actif), la chaîne fait +1.
  Un jour creux (< N membres) CASSE la chaîne (retour à 0).
- Jauge visible dans le hub + annonce de palier (7 / 30 / 100 j) dans un salon
  CHATTY, allowed_mentions=none (jamais de ping de masse).
- Table légère : (guild_id, current_streak, best_streak, last_day ISO FR,
  last_milestone). Récompense collective MODESTE et anti-doublon (1 fois / palier).
- Task quotidienne FAIL-OPEN + à inscrire au superviseur.

Module AUTONOME : dépendances injectées via setup() (même patron que
activity_system / mob_hunts). La CI ne voit pas les NameError runtime → tout
reste défensif. Aucune mutation de l'économie « pièces » ici : la récompense
collective passe par l'injection award_fn (pièces MODESTES) si fournie, sinon on
se contente de l'annonce honorifique. Anti-double-claim garanti par last_milestone.
"""

from datetime import datetime, timezone, timedelta

from discord.ext import tasks
import discord


# ─── Dépendances injectées ───
_get_db = None
_bot = None
_distinct_active_fn = None     # async (guild_id, day_iso_utc) -> int (activity_system)
_pick_chatty_fn = None         # async (guild) -> discord.TextChannel | None
_award_fn = None               # async (guild_id, user_id, coins) -> None  (optionnel)

# ─── Paramètres ───
# N membres DISTINCTS actifs dans la journée pour que la chaîne tienne. Modeste
# (un petit serveur reste capable de tenir la chaîne), exclut juste « personne ».
MIN_ACTIVE_MEMBERS = 3

# Paliers honorifiques. Récompense collective MODESTE (rétention #1) — distribuée
# 1 SEULE FOIS par palier (anti-doublon via colonne last_milestone) à chaque
# membre actif du jour, plafonnée pour ne jamais inonder l'économie.
MILESTONES = (7, 30, 100)
MILESTONE_COINS = {7: 50, 30: 150, 100: 400}   # pièces / membre actif, modeste
MILESTONE_MAX_RECIPIENTS = 40                  # plafond anti-inflation par palier


def _today_utc() -> str:
    """Jour courant 'YYYY-MM-DD' UTC — MÊME format que activity_system.activity_score
    (la chaîne lit l'activité par cette clé)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday_utc() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _now_fr_iso() -> str:
    """Horodatage lisible FR pour last_day (stocké en clair, jamais reparsé pour
    de la logique — la logique compte les jours via les clés UTC d'activity_score)."""
    return datetime.now(timezone.utc).strftime("%d/%m/%Y")


def setup(get_db_fn, *, bot=None, distinct_active_fn=None,
          pick_chatty_fn=None, award_fn=None):
    """Injecte les dépendances (même contrat que les autres modules autonomes).

    - get_db_fn        : context manager DB (`async with get_db()`).
    - bot              : l'instance bot (pour itérer les guilds + envoyer l'annonce).
    - distinct_active_fn : async (guild_id, day) -> int (activity_system).
    - pick_chatty_fn   : async (guild) -> TextChannel|None (salon chatty pour annonce).
    - award_fn         : async (guild_id, user_id, coins) -> None (récompense MODESTE,
      optionnelle — si None, le palier reste purement honorifique)."""
    global _get_db, _bot, _distinct_active_fn, _pick_chatty_fn, _award_fn
    _get_db = get_db_fn
    _bot = bot
    _distinct_active_fn = distinct_active_fn
    _pick_chatty_fn = pick_chatty_fn
    _award_fn = award_fn


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS presence_chain ("
                "guild_id INTEGER PRIMARY KEY, "
                "current_streak INTEGER DEFAULT 0, "
                "best_streak INTEGER DEFAULT 0, "
                "last_day TEXT, "          # jour UTC déjà comptabilisé (anti-double-tick)
                "last_day_fr TEXT, "       # même jour en clair FR (affichage)
                "last_milestone INTEGER DEFAULT 0)"  # plus haut palier déjà récompensé
            )
            await db.commit()
    except Exception as ex:
        print(f"[presence_chain init_db] {ex}")


async def get_state(guild_id) -> dict:
    """Lecture seule (hub). Retourne {current, best, last_day_fr, last_milestone}.
    FAIL-OPEN : tout à 0 / '' sur erreur."""
    out = {"current": 0, "best": 0, "last_day_fr": "", "last_milestone": 0}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT current_streak, best_streak, last_day_fr, last_milestone "
                "FROM presence_chain WHERE guild_id=?",
                (int(guild_id),),
            ) as cur:
                row = await cur.fetchone()
        if row:
            out["current"] = int(row[0] or 0)
            out["best"] = int(row[1] or 0)
            out["last_day_fr"] = row[2] or ""
            out["last_milestone"] = int(row[3] or 0)
    except Exception as ex:
        print(f"[presence_chain get_state] {ex}")
    return out


def _next_milestone(current: int):
    for m in MILESTONES:
        if current < m:
            return m
    return None


def render_chain_line(state: dict) -> str:
    """Ligne compacte pour le hub : chaîne actuelle + record + prochaine cible +
    barre de progression vers le prochain palier. FAIL-OPEN : '' sur erreur."""
    try:
        cur = int(state.get("current", 0) or 0)
        best = int(state.get("best", 0) or 0)
        nxt = _next_milestone(cur)
        if nxt is None:
            bar = "▰" * 12
            tail = "🏆 **Palier max (100 j) tenu — légende du serveur !**"
        else:
            prevs = [m for m in MILESTONES if m <= cur]
            base = max(prevs) if prevs else 0
            span = max(1, nxt - base)
            frac = max(0.0, min(1.0, (cur - base) / span))
            filled = max(0, min(12, int(round(frac * 12))))
            bar = "▰" * filled + "▱" * (12 - filled)
            tail = f"Prochain palier collectif : **{nxt} j** (encore `{nxt - cur} j`)"
        rec = f" · record `{best} j`" if best else ""
        return (
            f"🔗 **Chaîne de présence : `{cur}` jour(s)**{rec}\n"
            f"{bar}\n{tail}"
        )
    except Exception:
        return ""


async def _grant_milestone_reward(guild_id, day_utc, milestone) -> int:
    """Récompense collective MODESTE : crédite les membres ACTIFS du jour (plafond
    MILESTONE_MAX_RECIPIENTS) une SEULE fois par palier. Retourne le nb de membres
    crédités (0 si award_fn absent ou erreur). FAIL-OPEN : ne casse jamais le tick."""
    coins = int(MILESTONE_COINS.get(milestone, 0) or 0)
    if _award_fn is None or _get_db is None or coins <= 0:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id FROM activity_score "
                "WHERE guild_id=? AND day=? AND points > 0 "
                "ORDER BY points DESC LIMIT ?",
                (int(guild_id), day_utc, int(MILESTONE_MAX_RECIPIENTS)),
            ) as cur:
                rows = await cur.fetchall()
        granted = 0
        for (uid,) in rows:
            try:
                await _award_fn(int(guild_id), int(uid), coins)
                granted += 1
            except Exception:
                continue
        return granted
    except Exception as ex:
        print(f"[presence_chain _grant_milestone_reward] {ex}")
        return 0


async def _announce_milestone(guild, milestone, current, granted, coins):
    """Annonce de palier dans un salon CHATTY, allowed_mentions=none (jamais de ping
    de masse). FAIL-OPEN : silencieux si pas de salon dispo / erreur d'envoi."""
    if _pick_chatty_fn is None:
        return
    try:
        ch = await _pick_chatty_fn(guild)
        if ch is None:
            return
        reward_line = ""
        if granted > 0 and coins > 0:
            reward_line = (
                f"\n🎁 Récompense collective : **+{coins} 🪙** pour les "
                f"**{granted}** membres actifs aujourd'hui — merci d'avoir tenu la chaîne !"
            )
        msg = (
            f"🔗 **Chaîne de présence : {milestone} jours d'affilée !**\n"
            f"Le serveur est resté vivant **{current} jours** sans interruption. "
            f"Continuez comme ça !{reward_line}"
        )
        await ch.send(msg, allowed_mentions=discord.AllowedMentions.none())
    except Exception as ex:
        print(f"[presence_chain _announce_milestone] {ex}")


async def _tick_guild(guild):
    """Évalue la chaîne d'UN serveur pour HIER (journée complète et figée).

    Idempotent : last_day (clé UTC) empêche de re-compter le même jour si la task
    refire (reconnexion, double on_ready). FAIL-OPEN par serveur."""
    if _get_db is None or _distinct_active_fn is None:
        return
    try:
        gid = int(guild.id)
        # On évalue HIER : journée complète. Comme la task tourne 1×/jour, on
        # comptabilise le jour écoulé une seule fois (garde-fou last_day).
        eval_day = _yesterday_utc()
        # Lire la clé UTC brute (last_day) pour l'anti-doublon idempotent.
        async with _get_db() as db:
            async with db.execute(
                "SELECT current_streak, best_streak, last_day, last_milestone "
                "FROM presence_chain WHERE guild_id=?",
                (gid,),
            ) as cur:
                row = await cur.fetchone()
        cur_streak = int(row[0]) if row else 0
        best_streak = int(row[1]) if row else 0
        last_day = (row[2] if row else None) or ""
        last_milestone = int(row[3]) if row else 0
        if last_day == eval_day:
            return  # déjà comptabilisé ce jour-là

        active = await _distinct_active_fn(gid, eval_day)
        if active >= MIN_ACTIVE_MEMBERS:
            new_streak = cur_streak + 1
        else:
            new_streak = 0
        new_best = max(best_streak, new_streak)

        async with _get_db() as db:
            await db.execute(
                "INSERT INTO presence_chain "
                "(guild_id, current_streak, best_streak, last_day, last_day_fr, last_milestone) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET "
                "current_streak=excluded.current_streak, "
                "best_streak=excluded.best_streak, "
                "last_day=excluded.last_day, "
                "last_day_fr=excluded.last_day_fr",
                (gid, new_streak, new_best, eval_day, _now_fr_iso(), last_milestone),
            )
            await db.commit()

        # Palier franchi ? (anti-doublon : strictement au-dessus du dernier récompensé)
        reached = None
        for m in MILESTONES:
            if new_streak >= m > last_milestone:
                reached = m  # on garde le PLUS HAUT atteint
        if reached is not None:
            coins = int(MILESTONE_COINS.get(reached, 0) or 0)
            granted = await _grant_milestone_reward(gid, eval_day, reached)
            async with _get_db() as db:
                await db.execute(
                    "UPDATE presence_chain SET last_milestone=? WHERE guild_id=?",
                    (int(reached), gid),
                )
                await db.commit()
            await _announce_milestone(guild, reached, new_streak, granted, coins)
    except Exception as ex:
        print(f"[presence_chain _tick_guild {getattr(guild, 'id', '?')}] {ex}")


@tasks.loop(hours=24)
async def chain_daily_task():
    """Task quotidienne FAIL-OPEN : évalue la chaîne de chaque serveur pour la
    journée écoulée. Inscrite au superviseur (bot.py) → ressuscitée si elle meurt."""
    try:
        if _bot is None:
            return
        for guild in list(_bot.guilds):
            try:
                await _tick_guild(guild)
            except Exception as ex:
                print(f"[presence_chain chain_daily_task guild] {ex}")
    except Exception as ex:
        print(f"[presence_chain chain_daily_task] {ex}")
