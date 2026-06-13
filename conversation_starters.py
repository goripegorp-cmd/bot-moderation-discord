"""conversation_starters.py — Anti-silence du hub (extrait de bot.py, Phase 234).

PREMIÈRE brique de modularisation du monolithe bot.py (~80k lignes). Choisie
parce qu'elle est 100 % AUTONOME : une seule tâche de fond, AUCUNE commande slash,
AUCUNE vue persistante, AUCUN état global partagé, fail-open. Si elle hoquette, au
pire il n'y a pas de relance de discussion — rien de critique.

Comportement : si le hub est muet depuis > 3 h pendant la plage active, le bot
poste une question pour relancer la discussion (max 1 / 6 h). Le contenu vient
déjà du module `ambient53`.

Toutes les dépendances de bot.py sont INJECTÉES via setup() (même pattern que
mob_hunts / daily_bosses / world_invasion) — le module ne connaît rien de
l'intérieur de bot.py. La tâche est ressuscitée par le task_supervisor de bot.py
via le tuple ("conversation_starters_module", "conv_starter_task").
"""

import discord
from discord.ext import tasks
from datetime import datetime, timezone, timedelta

import ambient53 as amb  # contenu des questions (déjà un module séparé)

# ─── Dépendances injectées par bot.py (toutes via setup()) ───────────────────
_bot = None
_get_db = None                 # async context manager → connexion DB
_cfg = None                    # async (guild_id) -> dict de config
_is_event_active_hour = None   # async (guild_id) -> bool (plage horaire active)
_is_chatty_channel = None      # async (channel) -> bool (salon de discussion ?)
_register_for_cleanup = None   # async (message, delay, reason) -> auto-delete fiable


def setup(bot_instance, get_db_fn, cfg_fn, is_event_active_hour_fn,
          is_chatty_channel_fn, register_for_cleanup_fn):
    """Injecte les dépendances de bot.py. Appelé une fois au boot (on_ready)."""
    global _bot, _get_db, _cfg, _is_event_active_hour
    global _is_chatty_channel, _register_for_cleanup
    _bot = bot_instance
    _get_db = get_db_fn
    _cfg = cfg_fn
    _is_event_active_hour = is_event_active_hour_fn
    _is_chatty_channel = is_chatty_channel_fn
    _register_for_cleanup = register_for_cleanup_fn


@tasks.loop(hours=1)
async def conv_starter_task():
    """Si le hub est mort depuis > 3 h pendant la plage active, poste une question."""
    if _bot is None or _get_db is None or _cfg is None:
        return
    try:
        for guild in _bot.guilds:
            try:
                c = await _cfg(guild.id)
                if not c.get('event_enabled', False):
                    continue
                if _is_event_active_hour is not None and not await _is_event_active_hour(guild.id):
                    continue
                hub_id = int(c.get('hub_channel', 0) or 0)
                if not hub_id:
                    continue
                hub_ch = guild.get_channel(hub_id)
                if not hub_ch:
                    continue
                if _is_chatty_channel is not None and not await _is_chatty_channel(hub_ch):
                    continue
                # Activité récente dans le hub ? (si oui, pas besoin de relancer)
                cutoff_3h = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT 1 FROM member_activity_daily WHERE guild_id=? AND channel_id=? "
                        "AND last_ts>? LIMIT 1",
                        (guild.id, hub_ch.id, cutoff_3h),
                    ) as cur:
                        if await cur.fetchone():
                            continue
                # Déjà posté un starter dans les 6 h ? (anti-spam)
                cutoff_6h = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
                async with _get_db() as db:
                    async with db.execute(
                        "SELECT 1 FROM conv_starter_log WHERE guild_id=? AND posted_at>? LIMIT 1",
                        (guild.id, cutoff_6h),
                    ) as cur:
                        if await cur.fetchone():
                            continue
                starter = amb.pick_random_starter()
                LIFETIME = 6 * 3600
                e = discord.Embed(
                    title="💬 On se motive ?",
                    description=starter,
                    color=0x9B59B6,
                )
                e.set_footer(text="Une question pour relancer la discussion")
                try:
                    msg = await hub_ch.send(
                        embed=e,
                        allowed_mentions=discord.AllowedMentions.none(),
                        delete_after=LIFETIME,
                    )
                    if _register_for_cleanup is not None:
                        await _register_for_cleanup(msg, LIFETIME, 'conv_starter')
                    async with _get_db() as db:
                        await db.execute(
                            "INSERT INTO conv_starter_log(guild_id, content) VALUES(?,?)",
                            (guild.id, starter[:200]),
                        )
                        await db.commit()
                    print(f"[conv_starter] guild={guild.id} posted")
                except Exception as ex:
                    print(f"[conv_starter send] {ex}")
            except Exception as ex:
                print(f"[conv_starter guild={guild.id}] {ex}")
    except Exception as ex:
        print(f"[conv_starter_task] {ex}")


@conv_starter_task.before_loop
async def _conv_starter_wait():
    if _bot is not None:
        try:
            await _bot.wait_until_ready()
        except Exception:
            pass
