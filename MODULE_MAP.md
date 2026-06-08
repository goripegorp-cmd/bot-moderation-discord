# MODULE_MAP.md — orientation for navigating this repo

> Hand-curated map: *which file owns what*, the boot contract, the DB layer, and the
> hard rules that keep edits from breaking the bot. For the exhaustive symbol → `file:line`
> lookup, see **INDEX.md** (auto-generated). For runtime conventions and history, see
> the memory docs under `.claude/.../memory/`.

---

## 1. The shape of the codebase

- **`bot.py`** (~84k lines) is the hub: the aiosqlite **DB pool**, the `discord.Client`/
  `CommandTree`, **every slash command**, the engagement Hub views, the **boss-raid &
  world-boss** combat handlers, the `_QuietStdout` log filter, `task_supervisor`, and the
  `on_ready` wiring that injects dependencies into every sibling module.
- **~90 sibling modules** each own one subsystem. They never `import bot` (no cycle);
  instead `bot.py` calls each module's `setup(...)` at boot and passes the shared helpers in.
- **One-off scripts** (`_audit_*.py`, `_migrate_*.py`, `_patch_*.py`, `_fix_*.py`) are NOT
  part of the boot path — manual maintenance tools. Don't wire them into runtime.

## 2. The boot / dependency-injection contract

Every subsystem module follows the same shape. Wiring happens in `bot.py` `on_ready`:

```
import xxx as xxx_module
...
xxx_module.setup(bot, get_db, db_get, V2_HELPERS, add_coins_fn=add_coins, ...)  # inject deps
await xxx_module.init_db()              # CREATE TABLE IF NOT EXISTS (idempotent)
xxx_module.register_persistent_views(bot)  # re-attach DynamicItem / View on reboot
await xxx_module.boot_cleanup()         # heal orphaned channels/rows from a hard restart
```

**The standard `setup` signature** (grep `^def setup(` to confirm per module):
`setup(bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, add_coins_fn=None, ...)`.
Modules store these in module-level globals and use them everywhere. **A module must
never reach back into `bot` directly** — if it needs something new, add a parameter to its
`setup` and pass it from `on_ready`.

- `get_db_fn()` → async context manager yielding a pooled aiosqlite connection.
- `db_get_fn(guild_id, key, default)` → read a per-guild config value.
- `v2_helpers` → dict of Components-V2 builders. **Keys are prefixed `v2_`**:
  `v2_title, v2_subtitle, v2_body, v2_divider, v2_container` + the `LayoutView` class
  (unprefixed). Always destructure with the `v2_` prefix (see `solo_instances._v2get`).
- `add_coins_fn` / bank helpers come from **`coin_economy.py`** and are already atomic.

**Background loops** must be registered in `task_supervisor`'s `_SUPERVISED_LOOP_NAMES`
(in `bot.py`) AND started in `on_ready`. A loop missing from the supervisor list silently
stops forever if it ever raises — that is a recurring class of bug.

## 3. DB layer — the rules that matter

- Pool: **20 connections, WAL, autocommit-off, `busy_timeout=5s`, NO row locks / no
  `BEGIN IMMEDIATE`.** Therefore *any* read-modify-write split across two statements is
  **racy** under double-click or concurrent tasks.
- **Economy = FAIL-CLOSED + atomic.** Mutate with a single conditional UPDATE and check
  `cursor.rowcount` before paying out:
  `UPDATE ... SET coins = MAX(0, coins + ?) WHERE ...` (already done in `coin_economy.add_coins`/`add_bank`),
  and for one-shot claims `UPDATE ... SET status='ended' WHERE status='active'` then bail if `rowcount != 1`.
- **Combat = FAIL-OPEN.** A bug in gating/pets/recall must never block an attack — wrap in
  try/except and proceed.
- Idempotent schema: `CREATE TABLE IF NOT EXISTS`, `INSERT OR IGNORE` / `ON CONFLICT`.
- SQLite `CURRENT_TIMESTAMP` is **naive UTC** — normalize (`tzinfo=timezone.utc`) before
  arithmetic, or compare with `julianday(...)`, never mix naive/aware datetimes.

## 4. Domain → module index ("where do I edit for X")

| Concern | Primary file(s) |
| --- | --- |
| **DB pool, slash cmds, Hub, log filter, task_supervisor, on_ready** | `bot.py` |
| **Coins / bank (atomic helpers)** | `coin_economy.py` |
| **Boss raid + World boss combat** | `bot.py` (`_handle_boss_attack`, `WorldBossAttackView`) |
| **Shared combat actions ⚡/📣/🛡️** | `combat_actions.py` |
| **Re-ping past participants** | `combat_recall.py` |
| **Daily boss / Monthly climax / Mob hunts / Invasion** | `daily_bosses.py` · `monthly_climax.py` · `mob_hunts.py` · `world_invasion.py` |
| **Instanced dungeons (group) / Solo per-player events** | `dungeon_instances.py` · `solo_instances.py` |
| **Light/world events** | `economy_events.py` · `rift_events.py` · `chain_events.py` · `caravan_events.py` · `wandering_merchant.py` · `community_goals.py` · `alliance_war.py` |
| **Combat recap (consolidated journal)** | `raid_recap.py` |
| **Activity gate (14-day score → event access)** | `activity_system.py` |
| **Activity VIP roles / heatmap** | `activity_rewards.py` · `activity_heatmap.py` |
| **Pets: eggs / hatching / evolution** | `pet_eggs.py` · `pet_evolution.py` (catalogue: `engagement47.PETS`) |
| **Weapons / armor catalogue, drops** | `events_engine` (WEAPONS/ARMOR) referenced from `bot.py` |
| **Seasons / titles / prestige** | `seasonal_engine.py` · `seasonal_titles.py` |
| **Cosmetics / La Cité currency / housing** | `cosmetics.py` · `citadelle.py` |
| **Narrative: story, NPCs, council, regions, mystery** | `story_engine.py` · `npc_personalities.py` · `npc_letters.py` · `weekly_council.py` · `regional_state.py` · `mystery_investigation.py` · `daily_encounters.py` · `codex_chronicle.py` |
| **Onboarding / hero journey** | `onboarding_journey.py` · `hero_journey.py` |
| **Alliances (vault, war)** | `alliance_vault.py` · `alliance_war.py` |
| **Voice lounges / autoclean** | `voice_lounges.py` · `voice_autoclean.py` |
| **Security / anti-raid / scam / token leaks** | `protection_guards.py` · `antiscam.py` · `raid_detector.py` · `compromised_detector.py` · `impersonation_detector.py` · `token_grabber.py` · `anti_token_leak.py` · `webhook_leak.py` · `honeypot.py` · `behavior_anomaly.py` · `member_risk.py` · `twofa_vault.py` |
| **Moderation UI / sanctions** | `mod_dashboard.py` · `staff_sanction.py` · `permissions.py` |
| **Social publishing / Roblox / streams** | `social_media.py` · `social_gallery.py` · `social_liveness.py` · `tracking_layer.py` · `publish_metrics.py` · `game_updates.py` · `spotlight_quality.py` · `stream_schedule.py` · `stream_watch_party.py` · `roblox_link.py` · `roblox_game_stats.py` · `roblox_raffle.py` |
| **Tickets** | `tickets_enhance.py` |
| **Notifications / digests / DMs** | `event_notif_role.py` · `dm_notify.py` · `dm_digest.py` · `owner_digest.py` · `npc_letters.py` |
| **Components-V2 helpers / admin panels / setup** | `panels_helpers.py` · `admin_panels_v2.py` · `setup_wizard.py` · `help_system.py` · `help_faq.py` · `roles_panel.py` · `ux_polish.py` · `event_followup.py` |
| **Owner observability / health / logging** | `observability.py` · `health_server.py` · `health_check.py` · `error_logger.py` · `unified_logger.py` · `weekly_stats.py` |
| **Backups / cleanup / rate limit** | `backup_lite.py` · `db_backup.py` · `data_cleanup.py` · `rate_limiter.py` |

## 5. Events architecture (read before touching combat)

- **One major combat event at a time** — global lock `_has_any_major_event_running`.
  **Solo events (`solo_instances.py`) run in parallel and NEVER touch that lock.**
- Combat is **100% TEXT — zero voice channels created.** (Vocal presence only grants a
  random combat boost.) The live fight lives in an **ephemeral `⚔️-combat` channel** that is
  deleted when no event runs; the consolidated recap goes to permanent `📜-chroniques-combat`.
- **NEVER mask `@everyone` channels during an event** (a past masking loop made the whole
  server invisible). Channels stay visible; the fight is contained to its own channel.
- **Event access is gated by ACTIVITY only** (`activity_system`, 3/10/25 pts over 14 days,
  voice credited in real time), never by level. Level gates only *equipping* gear.
- **Solo events** create a **private per-player channel** (`@everyone` view=False), run-local
  HP, and a **3-layer cleanup**: end-of-run lingering close (`_RESULT_LINGER_SEC`), a 30-min
  watchdog TTL, and boot cleanup. Atomic `_claim_run` prevents double close.

## 6. Hard rules (violating any of these breaks the bot)

1. **NO new slash commands** — the tree is near Discord's ~100 cap. Add features as buttons
   on existing panels / sub-hubs, never a new `@tree.command`. The CI import-check fails
   loudly on `CommandLimitReached`.
2. **Components V2 limits:** LayoutView ≤ 40 components; ActionRow ≤ 5 buttons; Select ≤ 25
   options. A LayoutView **cannot** carry `content=` (400 50035). Bare buttons / DynamicItems
   must be wrapped in `discord.ui.ActionRow(...)`.
3. **Never two `@bot.event` for the same event** — discord.py keeps only the last. Use
   `bot.add_listener(fn, "on_x")` for additive handlers.
4. **DM guard:** any command using `i.guild.id` must `if i.guild is None: return ...`.
5. **Anti-429:** ACK with `defer()` first; per-player cooldown checked **before any network
   call**; a click rejected by cooldown sends **zero** followup; refresh live panels via
   `ch.get_partial_message(id).edit(...)` (no GET) + throttle (~1×/4s).
6. **P2P trade forbidden** — vendor/auction only.
7. **Deploy = commit + push to `main`** (Railway). **No local Python here** — rely on CI
   (`compile-check.yml` import-check is authoritative for boot). Always wait for CI green.
8. Rewards modest, rarities hard (retention is the #1 value).

## 7. CI workflows (`.github/workflows/`)

| file | job | authority |
| --- | --- | --- |
| `compile-check.yml` | py_compile every file **+ `import bot`** (executes module-level code) | **authoritative for boot** — catches `CommandLimitReached`, `NameError`, `ImportError` |
| `pytest.yml` | pytest smoke (`tests/`) | regression guard |
| `sql-audit.yml` | SQL-injection audit | security guard |
| `index.yml` | regenerate **INDEX.md** + ruff lint (non-blocking) | navigation aid; auto-commits INDEX.md back (`[skip ci]`, loop-safe) |
