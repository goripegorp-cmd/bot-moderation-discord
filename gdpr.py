"""
gdpr.py — Conformité RGPD : droit à l'effacement (art. 17) + rétention bornée.

Carte dérivée de l'audit exhaustif du 2026-06-14 (cartographie de ~290 tables, workflow
wf_24402de5-47d). C'est LE registre faisant autorité des données personnelles du bot.

Principes (décidés côté ingénierie, conformes RGPD) :
- DELETE  : données personnelles / gameplay dont l'utilisateur est le SUJET → on supprime ses lignes.
- ANONYMIZE : tables d'audit / sécurité / financières / provenance / agrégats, OU colonnes "acteur"
  (le membre agissait sur AUTRUI) → on GARDE la ligne (intégrité / preuve / stats) mais on neutralise
  l'ID (→ 0) et on caviarde les champs texte personnels. On ne supprime JAMAIS une ligne juste parce
  qu'une colonne "acteur" (mod_id, decided_by, claimed_by, restricted_by, …) correspond — sinon on
  détruirait l'historique d'AUTRUI.
- JSON blob : l'ID vit dans un blob JSON (votes, participants, contributeurs) → parse / filtre / re-sérialise.
- HMAC : colonnes anonymes hachées (confessions.user_hash, compliments_log.from_user_hash) → on ne peut
  matcher que via un HMAC recalculé fourni par l'appelant (paramètre hmac_user).
- FAIL-SAFE : chaque table est traitée dans son propre try/except ; une table/colonne absente est
  ignorée et comptée dans "skipped" (jamais de crash). Tout tourne dans une seule transaction.

Module PUR (aucun import de bot.py) : l'appelant passe une connexion aiosqlite ouverte (`db`).
"""

import json
import time

# ─────────────────────────────────────────────────────────────────────────────
# 1) DELETE — l'utilisateur est le SUJET de la ligne → suppression. {table: [colonnes_sujet]}
#    (OR entre colonnes si plusieurs). Scopé par guild_id SAUF tables globales (cf. GLOBAL_NO_GUILD).
# ─────────────────────────────────────────────────────────────────────────────
DELETE_SUBJECT = {
    # bot.py — cœur joueur / modération-sujet / social
    "immune_users": ["user_id"],
    "account_freeze": ["user_id"],
    "security_logs": ["user_id"],
    "infractions": ["user_id"],
    "realsy_tracking": ["user_id"],
    "suggestions": ["user_id"],
    "member_activity": ["user_id"],
    "combat_ping_log": ["user_id"],
    "economy": ["user_id"],
    "shop_purchases": ["user_id"],
    "event_participants": ["user_id"],
    "player_inventory": ["user_id"],
    "player_stash": ["user_id"],
    "loot_history": ["user_id"],
    "player_badges": ["user_id"],
    "player_event_stats": ["user_id"],
    "personal_events_log": ["user_id"],
    "player_classes": ["user_id"],
    "player_voice_optin": ["user_id"],
    "wakeup_log": ["user_id"],
    "comeback_dms": ["user_id"],
    "daily_quest_progress": ["user_id"],
    "user_streaks": ["user_id"],
    "user_stats41": ["user_id"],
    "achievements_unlocked": ["user_id"],
    "user_pets": ["user_id"],
    "wheel_log": ["user_id"],
    "world_boss_attackers": ["user_id"],
    "daily_riddle_answered": ["user_id"],
    "daily_quest_pushes": ["user_id"],
    "season_progress": ["user_id"],
    "user_prestige": ["user_id"],
    "faction_reputation": ["user_id"],
    "weekly_quests": ["user_id"],
    "monthly_quests": ["user_id"],
    "user_notif_prefs": ["user_id"],
    "mission_step_progress": ["user_id"],
    "matchmaking_party_members": ["user_id"],
    "bingo_cards": ["user_id"],
    "prediction_bets": ["user_id"],
    "weekly_recap_log": ["user_id"],
    "daily_greeting_log": ["user_id"],
    "narrative_vote_ballots": ["user_id"],
    "player_class_choice": ["user_id"],
    "update_vote_ballots": ["user_id"],
    "tournament_participants": ["user_id"],
    "heist_participants": ["user_id"],
    "user_bank_deposits": ["user_id"],
    "advent_calendar": ["user_id"],
    "voice_activity_log": ["user_id"],
    "easter_eggs_log": ["user_id"],
    "user_toxicity_scores": ["user_id"],
    "user_fingerprints": ["user_id"],
    "badword_strikes": ["user_id"],
    "member_birthdays": ["user_id"],
    "creator_links": ["user_id"],
    "ladder_ratings": ["user_id"],
    "alliance_members": ["user_id"],
    "voice_daily_rewards": ["user_id"],
    "activity_score": ["user_id"],
    "activity_vip_grants": ["user_id"],
    "alliance_war_participants": ["user_id"],
    "behavior_profile": ["user_id"],
    "behavior_alerts": ["user_id"],
    "combat_recall": ["user_id"],
    "user_cosmetics": ["user_id"],
    "chain_contributors": ["user_id"],
    "caravan_contributors": ["user_id"],
    "luxury_tax_log": ["user_id"],
    "roadmap_votes": ["user_id"],
    "daily_encounters_log": ["user_id"],
    "daily_boss_attackers": ["user_id"],
    "boss_ping_log": ["user_id"],
    "dm_digest_queue": ["user_id"],
    "dm_event_optin": ["user_id"],
    "dungeon_members": ["user_id"],
    "dormant_dm_log": ["user_id"],
    "dormant_comeback_pending": ["user_id"],
    "hero_journey": ["user_id"],
    "mob_attackers": ["user_id"],
    "climax_attackers": ["user_id"],
    "climax_titles": ["user_id"],
    "mystery_clues_held": ["user_id"],
    "mystery_shares": ["user_id"],
    "member_risk_scores": ["user_id"],
    "npc_letter_subscriptions": ["user_id"],
    "npc_letters_sent": ["user_id"],
    "npc_mood": ["user_id"],
    "onboarding_journey": ["user_id"],
    "pet_eggs": ["user_id"],
    "pet_evolution": ["user_id"],
    "player_styles": ["user_id"],
    "milestone_claims": ["user_id"],
    "reputation": ["user_id"],
    "reputation_history": ["user_id"],
    "patrol_contributions": ["user_id"],
    "roblox_account_links": ["user_id"],
    "roblox_link_pending": ["user_id"],
    "raffle_tickets": ["user_id"],
    "rift_contributors": ["user_id"],
    "saga_participants": ["user_id"],
    "seasonal_drops_log": ["user_id"],
    "monthly_champions": ["user_id"],
    "solo_runs": ["user_id"],
    "solo_cooldowns": ["user_id"],
    "chronicle_contributors": ["user_id"],
    "voice_milestone_claims": ["user_id"],
    "merchant_purchases": ["user_id"],
    "council_votes": ["user_id"],
    "welcomed_users": ["user_id"],
    "invasion_attackers": ["user_id"],
    "token_leaks": ["user_id"],
    "honeypot_hits": ["user_id"],
    "daily_join_log": ["user_id"],
    "raid_join_log": ["user_id"],
    "phishing_log": ["user_id"],
    "phishing_offender": ["user_id"],
    "twofa_confirmations": ["user_id"],
    "webhook_leak_log": ["user_id"],
    "citadelle_wallet": ["user_id"],
    "citadelle_materials": ["user_id"],
    "citadelle_cosmetics": ["user_id"],
    "citadelle_active": ["user_id"],
    "citadelle_passe": ["user_id"],
    "citadelle_professions": ["user_id"],
    "citadelle_garden": ["user_id"],
    "citadelle_rente": ["user_id"],
    "citadelle_mastery": ["user_id"],
    # colonnes sujet ≠ "user_id"
    "temp_voice_rooms": ["owner_id"],
    "time_capsules": ["author_id"],
    "stream_schedule": ["scheduled_by_user_id"],
    "caravan_roles": ["holder_id"],
    # relations symétriques (le membre est sujet des deux côtés) → delete par OR
    "mentorships": ["mentor_id", "apprentice_id"],
    "mentor_bonus_track": ["mentor_id", "apprenti_id"],
    "alt_accounts": ["main_account_id", "alt_account_id"],
    "alt_detection_log": ["new_user_id", "similar_to_user_id"],
    "alliance_invites": ["invited_user_id", "invited_by"],
    # cross-plateforme (PII sensible Discord↔Roblox) → suppression complète
    "roblox_game_library": ["user_id"],
}

# Tables SANS guild_id (préférences globales) : purge par user_id seul, toutes guildes.
GLOBAL_NO_GUILD = {
    "user_language": ["user_id"],
    "user_theme_pref": ["user_id"],
    "dm_digest_prefs": ["user_id"],
}

# ─────────────────────────────────────────────────────────────────────────────
# 2) DELETE_SUBJECT + ANONYMIZE_ACTOR sur la MÊME table : on supprime les lignes où le membre
#    est le SUJET, et on neutralise (→0) la colonne "acteur" sur les lignes d'AUTRUI qu'il a touchées.
#    {table: {"subject": [cols à delete], "actor": [cols à mettre à 0]}}
# ─────────────────────────────────────────────────────────────────────────────
DELETE_SUBJECT_KEEP_ACTOR = {
    "tickets": {"subject": ["user_id"], "actor": ["claimed_by"]},
    "mod_notes": {"subject": ["user_id"], "actor": ["mod_id"]},
    "rellseas_quizzes": {"subject": ["user_id"], "actor": ["examiner_id"]},
    "restricted_members": {"subject": ["user_id"], "actor": ["restricted_by"]},
    "achievement_broadcasts": {"subject": ["user_id"], "actor": ["posted_by"]},
    "user_titles": {"subject": ["user_id"], "actor": ["awarded_by"]},
    "entraide_requests": {"subject": ["requester_id"], "actor": ["helper_id"]},
    "referrals": {"subject": ["invitee_id"], "actor": ["inviter_id"]},
    "marketplace_listings": {"subject": ["seller_id"], "actor": ["buyer_id"]},
}

# ─────────────────────────────────────────────────────────────────────────────
# 3) ANONYMIZE — on GARDE la ligne (audit / sécurité / finance / provenance / agrégat) mais on
#    neutralise les ID (→0) et on caviarde (→ NULL) les champs texte personnels.
#    {table: {"ids": [cols ID], "redact": [cols texte]}}
# ─────────────────────────────────────────────────────────────────────────────
ANONYMIZE = {
    "member_activity_daily": {"ids": ["user_id"], "redact": []},
    "staff_audit_log": {"ids": ["actor_id", "target_id"], "redact": []},
    "activity_tracking": {"ids": ["user_id"], "redact": []},
    "events": {"ids": ["triggered_by"], "redact": []},
    "auctions": {"ids": ["seller_id", "top_bidder_id"], "redact": []},
    "duels": {"ids": ["challenger_id", "opponent_id", "winner_id"], "redact": []},
    "pvp_duels": {"ids": ["challenger_id", "challenged_id", "winner_id"], "redact": []},
    "daily_riddles_log": {"ids": ["first_winner_id"], "redact": []},
    "flash_treasures": {"ids": ["grabbed_by"], "redact": []},
    "compliments_log": {"ids": ["to_user_id"], "redact": []},
    "alliances": {"ids": ["leader_id"], "redact": []},
    "confession_replies": {"ids": ["replier_id"], "redact": ["content"]},
    "speedrun_submissions": {"ids": ["user_id", "reviewed_by"], "redact": ["notes", "video_url"]},
    "matchmaking_parties": {"ids": ["host_id"], "redact": []},
    "game_updates": {"ids": ["posted_by"], "redact": []},
    "predictions": {"ids": ["created_by"], "redact": []},
    "shoutouts": {"ids": ["from_user_id", "to_user_id"], "redact": ["reason"]},
    "narrative_votes": {"ids": ["created_by"], "redact": []},
    "update_votes": {"ids": ["created_by"], "redact": []},
    "tournaments": {"ids": ["winner_id", "created_by"], "redact": []},
    "thematic_voices": {"ids": ["host_id"], "redact": []},
    "unique_loots": {"ids": ["current_owner_id"], "redact": []},
    "unique_loot_history": {"ids": ["owner_id"], "redact": []},
    "ban_history": {"ids": ["user_id"], "redact": ["username", "avatar_hash"]},
    "hall_of_fame_records": {"ids": ["user_id", "added_by"], "redact": ["detail"]},
    "alliance_audit_log": {"ids": ["actor_id", "target_id"], "redact": []},
    "staff_sanction_log": {"ids": ["target_user_id", "decided_by"], "redact": ["reason", "evidence"]},
    "impersonation_alerts": {"ids": ["suspect_user_id", "target_staff_id"], "redact": []},
    "entraide_helper_stats": {"ids": ["user_id"], "redact": []},
    "alliance_vault_items": {"ids": ["deposited_by"], "redact": []},
    "wiki_entries": {"ids": ["author_id"], "redact": []},
    "roadmap_items": {"ids": ["user_id"], "redact": []},
    "spotlighted_messages": {"ids": ["author_id"], "redact": []},
    "ticket_response_templates": {"ids": ["added_by"], "redact": []},
    "webhook_registry": {"ids": ["owner_id"], "redact": []},
    # transferts P2P : on neutralise le côté du partant, le contrepartie garde son relevé
    "economy_events": {"ids": ["sender_id", "receiver_id"], "redact": []},
}

# Colonnes HMAC (pas un user_id brut) : agies seulement si l'appelant fournit hmac_user.
# {table: {"hmac_cols": [...], "redact": [...]}}
HMAC_ANONYMIZE = {
    "confessions": {"hmac_cols": ["user_hash"], "redact": ["content"]},
    "compliments_log": {"hmac_cols": ["from_user_hash"], "redact": []},
}

# ─────────────────────────────────────────────────────────────────────────────
# 4) JSON blobs — l'ID est dans un blob. On parse / filtre / re-sérialise sur TOUTES les lignes
#    de la guilde (l'ID peut apparaître dans une ligne appartenant à autrui / à la guilde).
#    kind: "list" (tableau d'ID) | "dict_key" (dict {str(uid): ...}) | "list_dict" (liste de dicts
#    contenant une clé user_id).
# ─────────────────────────────────────────────────────────────────────────────
JSON_BLOBS = [
    {"table": "giveaways", "col": "participants", "kind": "list"},
    {"table": "polls", "col": "votes_json", "kind": "dict_key"},
    {"table": "evening_rituals", "col": "participants_json", "kind": "list"},
    {"table": "tag_royale", "col": "chain_users_json", "kind": "list"},
    {"table": "community_goals", "col": "contributors_jsonb", "kind": "dict_key"},
    {"table": "daily_prompts", "col": "votes_jsonb", "kind": "dict_key"},
    {"table": "mystery_revelations", "col": "contributors_json", "kind": "list"},
    {"table": "raffle_draws", "col": "winners_jsonb", "kind": "list"},
    {"table": "saga_choices", "col": "voters_jsonb", "kind": "list_dict"},
    {"table": "raid_alerts", "col": "members_jsonb", "kind": "list_dict"},
]
# blobs "scan libre" (structure variable) traités au mieux : on remplace l'uid s'il apparaît
# comme entier/clé, sinon on journalise pour revue.
JSON_BLOBS_SCAN = [
    {"table": "chronicle_events", "col": "payload_json"},
    {"table": "error_log", "col": "context_jsonb"},
    {"table": "owner_digest_log", "col": "last_summary_jsonb"},
]

# Pour les tables qui ont AUSSI une colonne directe à traiter avant le filtrage de blob.
JSON_BLOB_PRECOLUMN = {
    "giveaways": {"delete": ["created_by"]},      # supprime les giveaways créés par le membre
    "polls": {"delete": ["author_id"]},           # supprime les sondages créés par le membre
    "tag_royale": {"anonymize": ["started_user_id"]},
}

# ─────────────────────────────────────────────────────────────────────────────
# 5) RÉTENTION — purge auto des données sensibles datées (minimisation). {table: (col_ts, jours)}.
#    col_ts peut être un timestamp epoch (REAL/INT) ou un ISO8601 (TEXT) : on gère les deux.
#    Tout est validé contre le schéma réel à l'exécution (colonne absente → skip).
# ─────────────────────────────────────────────────────────────────────────────
RETENTION = {
    "raid_join_log": ("joined_at", 30),
    "daily_join_log": ("joined_at", 30),
    "honeypot_hits": ("created_at", 90),
    "phishing_log": ("created_at", 90),
    "security_logs": ("timestamp", 180),
    "behavior_alerts": ("created_at", 90),
    "alt_detection_log": ("detected_at", 90),
    "error_log": ("created_at", 30),
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _columns(db, table):
    """Colonnes réelles d'une table (set), ou set() si la table n'existe pas. Ne lève jamais."""
    try:
        async with db.execute("PRAGMA table_info(%s)" % table) as cur:
            rows = await cur.fetchall()
        return {r[1] for r in rows}
    except Exception:
        return set()


def _has_guild(cols):
    return "guild_id" in cols


async def _exec(db, sql, params, summary, bucket, table):
    """Exécute une requête, agrège le rowcount, n'échoue jamais (compté en 'errors')."""
    try:
        cur = await db.execute(sql, params)
        n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        summary[bucket][table] = summary[bucket].get(table, 0) + n
    except Exception as ex:
        summary["errors"].append("%s/%s: %s" % (bucket, table, ex))


# ─────────────────────────────────────────────────────────────────────────────
# Purge principale
# ─────────────────────────────────────────────────────────────────────────────
async def purge_user(db, guild_id, user_id, *, hmac_user=None, commit=True):
    """
    Efface/anonymise toutes les données de `user_id` dans la guilde `guild_id`.
    - db : connexion aiosqlite ouverte.
    - hmac_user : HMAC de l'utilisateur (str) pour matcher les colonnes hachées (confessions…),
      calculé par l'appelant avec la même clé que le reste du code. None → on saute ces tables.
    - commit : commit en fin (par défaut). Tout est fail-safe par table.
    Retourne un résumé {deleted:{t:n}, anonymized:{t:n}, blobs:{t:n}, errors:[...]}.
    """
    uid = int(user_id)
    gid = int(guild_id)
    summary = {"deleted": {}, "anonymized": {}, "blobs": {}, "errors": [], "guild_id": gid, "user_id": uid}

    # 1) DELETE sujet ----------------------------------------------------------
    for table, subj_cols in DELETE_SUBJECT.items():
        cols = await _columns(db, table)
        if not cols:
            continue
        present = [c for c in subj_cols if c in cols]
        if not present:
            summary["errors"].append("delete/%s: aucune colonne sujet présente (%s)" % (table, subj_cols))
            continue
        where = " OR ".join("%s=?" % c for c in present)
        params = [uid] * len(present)
        if _has_guild(cols):
            sql = "DELETE FROM %s WHERE guild_id=? AND (%s)" % (table, where)
            params = [gid] + params
        else:
            sql = "DELETE FROM %s WHERE %s" % (table, where)
        await _exec(db, sql, params, summary, "deleted", table)

    # 1bis) tables globales (pas de guild_id) ---------------------------------
    for table, subj_cols in GLOBAL_NO_GUILD.items():
        cols = await _columns(db, table)
        present = [c for c in subj_cols if c in cols]
        if not present:
            continue
        where = " OR ".join("%s=?" % c for c in present)
        await _exec(db, "DELETE FROM %s WHERE %s" % (table, where), [uid] * len(present), summary, "deleted", table)

    # 2) DELETE sujet + ANONYMIZE acteur (même table) -------------------------
    for table, spec in DELETE_SUBJECT_KEEP_ACTOR.items():
        cols = await _columns(db, table)
        if not cols:
            continue
        g = _has_guild(cols)
        subj = [c for c in spec["subject"] if c in cols]
        if subj:
            where = " OR ".join("%s=?" % c for c in subj)
            params = [uid] * len(subj)
            if g:
                await _exec(db, "DELETE FROM %s WHERE guild_id=? AND (%s)" % (table, where), [gid] + params, summary, "deleted", table)
            else:
                await _exec(db, "DELETE FROM %s WHERE %s" % (table, where), params, summary, "deleted", table)
        for ac in [c for c in spec["actor"] if c in cols]:
            if g:
                await _exec(db, "UPDATE %s SET %s=0 WHERE guild_id=? AND %s=?" % (table, ac, ac), [gid, uid], summary, "anonymized", table)
            else:
                await _exec(db, "UPDATE %s SET %s=0 WHERE %s=?" % (table, ac, ac), [uid], summary, "anonymized", table)

    # 3) ANONYMIZE (garder la ligne, neutraliser ID + caviarder texte) --------
    for table, spec in ANONYMIZE.items():
        cols = await _columns(db, table)
        if not cols:
            continue
        g = _has_guild(cols)
        ids = [c for c in spec["ids"] if c in cols]
        redact = [c for c in spec.get("redact", []) if c in cols]
        for idc in ids:
            sets = ["%s=0" % idc] + ["%s=NULL" % r for r in redact]
            set_clause = ", ".join(sets)
            if g:
                await _exec(db, "UPDATE %s SET %s WHERE guild_id=? AND %s=?" % (table, set_clause, idc), [gid, uid], summary, "anonymized", table)
            else:
                await _exec(db, "UPDATE %s SET %s WHERE %s=?" % (table, set_clause, idc), [uid], summary, "anonymized", table)

    # 3bis) HMAC (confessions, compliments) -----------------------------------
    if hmac_user:
        for table, spec in HMAC_ANONYMIZE.items():
            cols = await _columns(db, table)
            if not cols:
                continue
            g = _has_guild(cols)
            redact = [c for c in spec.get("redact", []) if c in cols]
            for hc in [c for c in spec["hmac_cols"] if c in cols]:
                sets = ["%s=NULL" % hc] + ["%s=NULL" % r for r in redact]
                set_clause = ", ".join(sets)
                if g:
                    await _exec(db, "UPDATE %s SET %s WHERE guild_id=? AND %s=?" % (table, set_clause, hc), [gid, str(hmac_user)], summary, "anonymized", table)
                else:
                    await _exec(db, "UPDATE %s SET %s WHERE %s=?" % (table, set_clause, hc), [str(hmac_user)], summary, "anonymized", table)

    # 4) JSON blobs -----------------------------------------------------------
    # 4a) pré-colonnes (delete/anonymize une colonne directe avant le filtrage du blob)
    for table, pre in JSON_BLOB_PRECOLUMN.items():
        cols = await _columns(db, table)
        if not cols:
            continue
        g = _has_guild(cols)
        for dc in [c for c in pre.get("delete", []) if c in cols]:
            if g:
                await _exec(db, "DELETE FROM %s WHERE guild_id=? AND %s=?" % (table, dc), [gid, uid], summary, "deleted", table)
            else:
                await _exec(db, "DELETE FROM %s WHERE %s=?" % (table, dc), [uid], summary, "deleted", table)
        for ac in [c for c in pre.get("anonymize", []) if c in cols]:
            if g:
                await _exec(db, "UPDATE %s SET %s=0 WHERE guild_id=? AND %s=?" % (table, ac, ac), [gid, uid], summary, "anonymized", table)
            else:
                await _exec(db, "UPDATE %s SET %s=0 WHERE %s=?" % (table, ac, ac), [uid], summary, "anonymized", table)

    # 4b) filtrage des blobs
    for spec in JSON_BLOBS:
        await _filter_blob(db, gid, uid, spec["table"], spec["col"], spec["kind"], summary)
    for spec in JSON_BLOBS_SCAN:
        await _filter_blob(db, gid, uid, spec["table"], spec["col"], "scan", summary)

    if commit:
        try:
            await db.commit()
        except Exception as ex:
            summary["errors"].append("commit: %s" % ex)
    return summary


async def _filter_blob(db, gid, uid, table, col, kind, summary):
    """Charge chaque ligne, retire l'uid du blob, réécrit si modifié. Fail-safe."""
    cols = await _columns(db, table)
    if not cols or col not in cols:
        return
    g = _has_guild(cols)
    # clé primaire de réécriture : on prend rowid (toujours dispo sauf WITHOUT ROWID, rare ici)
    try:
        if g:
            q = "SELECT rowid, %s FROM %s WHERE guild_id=?" % (col, table)
            cur = await db.execute(q, [gid])
        else:
            q = "SELECT rowid, %s FROM %s" % (col, table)
            cur = await db.execute(q, [])
        rows = await cur.fetchall()
    except Exception as ex:
        summary["errors"].append("blob/%s: select %s" % (table, ex))
        return
    changed = 0
    for rid, raw in rows:
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        new = _strip_uid(data, uid, kind)
        if new is not None:
            try:
                await db.execute("UPDATE %s SET %s=? WHERE rowid=?" % (table, col), [json.dumps(new), rid])
                changed += 1
            except Exception as ex:
                summary["errors"].append("blob/%s: update %s" % (table, ex))
    if changed:
        summary["blobs"][table] = summary["blobs"].get(table, 0) + changed


def _strip_uid(data, uid, kind):
    """Retourne la structure modifiée (sans uid) ou None si rien n'a changé."""
    suid = str(uid)
    try:
        if kind == "list":
            if isinstance(data, list):
                filt = [x for x in data if str(x) != suid and x != uid]
                return filt if len(filt) != len(data) else None
        elif kind == "dict_key":
            if isinstance(data, dict) and (suid in data or uid in data):
                d = dict(data)
                d.pop(suid, None)
                d.pop(uid, None)
                return d
        elif kind == "list_dict":
            if isinstance(data, list):
                filt = [x for x in data if not (isinstance(x, dict) and str(x.get("user_id", x.get("id", ""))) == suid)]
                return filt if len(filt) != len(data) else None
        elif kind == "scan":
            # best-effort : retire l'uid d'éventuelles listes/dicts imbriqués
            return _deep_strip(data, suid, uid)
    except Exception:
        return None
    return None


def _deep_strip(obj, suid, uid):
    """Parcours récursif : retire l'uid des listes et des clés de dict. None si inchangé."""
    changed = False
    if isinstance(obj, list):
        out = []
        for x in obj:
            if str(x) == suid or x == uid:
                changed = True
                continue
            r = _deep_strip(x, suid, uid)
            out.append(r if r is not None else x)
            if r is not None:
                changed = True
        return out if changed else None
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k) == suid:
                changed = True
                continue
            r = _deep_strip(v, suid, uid)
            out[k] = r if r is not None else v
            if r is not None:
                changed = True
        return out if changed else None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Validation de la carte contre le schéma réel (auto-contrôle, à logger au boot)
# ─────────────────────────────────────────────────────────────────────────────
async def validate_map(db):
    """Retourne {missing_tables:[...], missing_columns:[(table,col)...]} : ce que la carte
    référence mais que le schéma réel ne contient pas → permet de repérer une dérive."""
    missing_tables, missing_columns = [], []

    def _check(table, want_cols):
        return table, want_cols

    checks = {}
    for t, c in DELETE_SUBJECT.items():
        checks.setdefault(t, set()).update(c)
    for t, c in GLOBAL_NO_GUILD.items():
        checks.setdefault(t, set()).update(c)
    for t, spec in DELETE_SUBJECT_KEEP_ACTOR.items():
        checks.setdefault(t, set()).update(spec["subject"] + spec["actor"])
    for t, spec in ANONYMIZE.items():
        checks.setdefault(t, set()).update(spec["ids"] + spec.get("redact", []))
    for t, spec in HMAC_ANONYMIZE.items():
        checks.setdefault(t, set()).update(spec["hmac_cols"] + spec.get("redact", []))
    for spec in JSON_BLOBS + JSON_BLOBS_SCAN:
        checks.setdefault(spec["table"], set()).add(spec["col"])

    for table, want in checks.items():
        cols = await _columns(db, table)
        if not cols:
            missing_tables.append(table)
            continue
        for c in want:
            if c not in cols:
                missing_columns.append((table, c))
    return {"missing_tables": missing_tables, "missing_columns": missing_columns}


# ─────────────────────────────────────────────────────────────────────────────
# Rétention bornée (minimisation des données)
# ─────────────────────────────────────────────────────────────────────────────
async def run_retention(db, *, now_ts=None, commit=True):
    """Purge les lignes plus vieilles que la rétention déclarée. Gère ts epoch ET ISO8601.
    Colonne/table absente → skip. Fail-safe. Retourne {table: rows_supprimées}."""
    if now_ts is None:
        now_ts = time.time()
    out = {}
    for table, (col, days) in RETENTION.items():
        cols = await _columns(db, table)
        if not cols or col not in cols:
            continue
        cutoff_epoch = now_ts - days * 86400
        cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(cutoff_epoch))
        try:
            # epoch numérique : col < cutoff_epoch ; ISO texte : col < cutoff_iso.
            # On tente les deux formes via un OR typé tolérant (CAST échoue silencieusement → 0).
            cur = await db.execute(
                "DELETE FROM %s WHERE (typeof(%s) IN ('integer','real') AND %s < ?) "
                "OR (typeof(%s)='text' AND %s < ?)" % (table, col, col, col, col),
                [cutoff_epoch, cutoff_iso],
            )
            out[table] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        except Exception:
            continue
    if commit:
        try:
            await db.commit()
        except Exception:
            pass
    return out
