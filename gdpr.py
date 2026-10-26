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
    "sondages": ["auteur_id"],
    "suggestions_v2": ["auteur_id"],
    "suggestions_votes": ["user_id"],
    # bot.py — cœur joueur / modération-sujet / social
    "immune_users": ["user_id"],
    "account_freeze": ["user_id"],
    "security_logs": ["user_id"],
    "infractions": ["user_id"],
    "infractions_archive": ["user_id"],
    "realsy_tracking": ["user_id"],
    # 27/10/2026 — les équipes du clan : sa place dans une équipe part avec lui
    "equipes_membres": ["membre_id"],
    "shop_purchases": ["user_id"],
    "user_toxicity_scores": ["user_id"],
    "user_fingerprints": ["user_id"],
    "badword_strikes": ["user_id"],
    "member_birthdays": ["user_id"],
    "behavior_profile": ["user_id"],
    "behavior_alerts": ["user_id"],
    "dm_digest_queue": ["user_id"],
    "member_risk_scores": ["user_id"],
    "token_leaks": ["user_id"],
    "honeypot_hits": ["user_id"],
    "daily_join_log": ["user_id"],
    "raid_join_log": ["user_id"],
    "phishing_log": ["user_id"],
    "phishing_offender": ["user_id"],
    "webhook_leak_log": ["user_id"],
    "activite_jours": ["user_id"],
    "activite_etat": ["user_id"],
    "ticket_transcripts": ["user_id"],
    # 25/10/2026 — site v2 : les réponses d'un candidat au questionnaire, son journal d'opérations hors ligne
    "recrutement_reponses": ["candidat_id"],
    "tableau_ops": ["user_id"],
    # 26/10/2026 — le questionnaire en ligne du candidat : ses brouillons, la liaison de ses sessions, sa page
    "candidature_brouillons": ["candidat_id"],
    "candidature_sessions": ["candidat_id"],
    "candidature_etat": ["candidat_id"],
    # colonnes sujet ≠ "user_id"
    "temp_voice_rooms": ["owner_id"],
    # relations symétriques (le membre est sujet des deux côtés) → delete par OR
    "alt_accounts": ["main_account_id", "alt_account_id"],
    "alt_detection_log": ["new_user_id", "similar_to_user_id"],
    # NB : roblox_account_links / roblox_link_pending (PII Discord↔Roblox) sont plus haut.
    # roblox_game_library est une donnée GUILDE (PK guild_id/universe_id) → voir ANONYMIZE.
}

# Tables SANS guild_id (préférences globales) : purge par user_id seul, toutes guildes.
GLOBAL_NO_GUILD = {
    "user_language": ["user_id"],
    # 25/10/2026 — les réponses aux événements du clan (la table n'a pas de guild_id)
    "clan_evenements_reponses": ["membre_id"],
    "dm_digest_prefs": ["user_id"],
}

# ─────────────────────────────────────────────────────────────────────────────
# 2) DELETE_SUBJECT + ANONYMIZE_ACTOR sur la MÊME table : on supprime les lignes où le membre
#    est le SUJET, et on neutralise (→0) la colonne "acteur" sur les lignes d'AUTRUI qu'il a touchées.
#    {table: {"subject": [cols à delete], "actor": [cols à mettre à 0]}}
# ─────────────────────────────────────────────────────────────────────────────
DELETE_SUBJECT_KEEP_ACTOR = {
    "tickets": {"subject": ["user_id"], "actor": ["claimed_by"]},
    "recrutements": {"subject": ["candidat_id"], "actor": ["ferme_par", "pris_par"]},
    "registre": {"subject": ["membre_id"], "actor": ["auteur_id"]},
    "questions": {"subject": ["auteur_id"], "actor": ["repondu_par"]},
    "vigilance": {"subject": ["membre_id"], "actor": ["gere_par"]},
    "tableau_sessions": {"subject": ["user_id"], "actor": []},
    "tableau_blocages": {"subject": ["user_id"], "actor": []},
    "mod_notes": {"subject": ["user_id"], "actor": ["mod_id"]},
    "restricted_members": {"subject": ["user_id"], "actor": ["restricted_by"]},
    "clan_rappels": {"subject": ["membre_id"], "actor": ["par", "resolu_par"]},
    # 25/10/2026 — site v2 : recrutement en deux étapes, affiches des membres du clan
    "recrutement_suivi": {"subject": ["candidat_id"], "actor": ["fermeture_par", "decide_par"]},
    "recrutement_envois": {"subject": ["candidat_id"], "actor": ["envoye_par"]},
    "rell_affiches": {"subject": ["membre_id"], "actor": ["cree_par", "maj_par", "retire_par"]},
    # 26/10/2026 — recrutement configurable : liste noire, éliminations d'office, chefs d'équipe
    "recrutement_liste_noire": {"subject": ["membre_id"], "actor": ["par", "leve_par"]},
    "recrutement_eliminations": {"subject": ["membre_id"], "actor": []},
    "recrutement_chef_candidatures": {"subject": ["membre_id"], "actor": ["decide_par"]},
    "recrutement_chefs": {"subject": ["membre_id"], "actor": ["accepte_par"]},
}

# ─────────────────────────────────────────────────────────────────────────────
# 3) ANONYMIZE — on GARDE la ligne (audit / sécurité / finance / provenance / agrégat) mais on
#    neutralise les ID (→0) et on caviarde (→ NULL) les champs texte personnels.
#    {table: {"ids": [cols ID], "redact": [cols texte]}}
# ─────────────────────────────────────────────────────────────────────────────
ANONYMIZE = {
    "staff_audit_log": {"ids": ["actor_id", "target_id"], "redact": []},
    "ban_history": {"ids": ["user_id"], "redact": ["username", "avatar_hash"]},
    "staff_sanction_log": {"ids": ["target_user_id", "decided_by"], "redact": ["reason", "evidence"]},
    "impersonation_alerts": {"ids": ["suspect_user_id", "target_staff_id"], "redact": []},
    "ticket_response_templates": {"ids": ["added_by"], "redact": []},
    "webhook_registry": {"ids": ["owner_id"], "redact": []},
    "ticket_audit": {"ids": ["actor_id"], "redact": []},
    "ticket_log_events": {"ids": ["actor_id"], "redact": []},
    # 25/10/2026 — site v2 : qui a corrigé, modifié, publié (la ligne reste, l'auteur est neutralisé)
    "recrutement_historique": {"ids": ["par"], "redact": []},
    "rell_affiches_historique": {"ids": ["par"], "redact": []},
    "clan_evenements": {"ids": ["cree_par", "maj_par", "publie_par"], "redact": []},
    "tableau_medias": {"ids": ["auteur_id"], "redact": []},
    # 26/10/2026 — le site de l'équipage : l'accueil et les actualités écrits par la direction (la ligne reste)
    "equipage_blocs": {"ids": ["cree_par", "maj_par"], "redact": []},
    "equipage_actualites": {"ids": ["cree_par", "maj_par"], "redact": []},
    # 27/10/2026 — la vitrine publique : qui a retiré une affiche de la vitrine (le réglage reste)
    "equipage_vitrine": {"ids": ["maj_par"], "redact": []},
    # 27/10/2026 — les équipes du clan : chef effacé (l'équipe reste, sans chef), auteur neutralisé
    "equipes": {"ids": ["chef_id", "maj_par"], "redact": []},
    # 26/10/2026 — Textes & noms : qui a réécrit un texte (le texte reste, l'auteur est neutralisé)
    "site_textes": {"ids": ["maj_par"], "redact": []},
    # 26/10/2026 — recrutement configurable : qui a réglé un parcours, une question ou un rôle de chef
    "recrutement_parcours": {"ids": ["maj_par"], "redact": []},
    "recrutement_chef_questions": {"ids": ["cree_par", "maj_par"], "redact": []},
    "recrutement_chef_gabarits": {"ids": ["maj_par"], "redact": []},
    "recrutement_chef_roles": {"ids": ["maj_par"], "redact": []},
}

# Colonnes HMAC (pas un user_id brut) : agies seulement si l'appelant fournit hmac_user.
# {table: {"hmac_cols": [...], "redact": [...]}}
HMAC_ANONYMIZE = {
}

# ─────────────────────────────────────────────────────────────────────────────
# 4) JSON blobs — l'ID est dans un blob. On parse / filtre / re-sérialise sur TOUTES les lignes
#    de la guilde (l'ID peut apparaître dans une ligne appartenant à autrui / à la guilde).
#    kind: "list" (tableau d'ID) | "dict_key" (dict {str(uid): ...}) | "list_dict" (liste de dicts
#    contenant une clé user_id).
# ─────────────────────────────────────────────────────────────────────────────
JSON_BLOBS = [
    {"table": "raid_alerts", "col": "members_jsonb", "kind": "list_dict"},
]
# blobs "scan libre" (structure variable) traités au mieux : on remplace l'uid s'il apparaît
# comme entier/clé, sinon on journalise pour revue.
JSON_BLOBS_SCAN = [
    {"table": "error_log", "col": "context_jsonb"},
]

# Pour les tables qui ont AUSSI une colonne directe à traiter avant le filtrage de blob.
JSON_BLOB_PRECOLUMN = {}

# ─────────────────────────────────────────────────────────────────────────────
# 5) RÉTENTION — purge auto des données sensibles datées (minimisation). {table: (col_ts, jours)}.
#    col_ts peut être un timestamp epoch (REAL/INT) ou un ISO8601 (TEXT) : on gère les deux.
#    Tout est validé contre le schéma réel à l'exécution (colonne absente → skip).
# ─────────────────────────────────────────────────────────────────────────────
RETENTION = {
    "raid_join_log": ("joined_at", 30),
    #  120 j : l'amnistie des 3 mois lit `left_day`. Les départs sans date d'arrivée (record_leave)
    #  sont datés par leur départ.
    "daily_join_log": (("joined_day", "left_day"), 120),
    "honeypot_hits": ("detected_at", 90),
    "phishing_log": ("detected_at", 90),
    "phishing_offender": ("last_hit_at", 90),
    "security_logs": ("created_at", 180),
    "alt_detection_log": ("detected_at", 90),
    "error_log": ("occurred_at", 30),
    "recrutements": ("ferme_le", 365),
    "registre": ("quand", 90),
    "questions": ("quand", 30),
    # 26/10/2026 — un brouillon du questionnaire en ligne que personne n'a touché depuis 30 jours (l'envoi le retire avant)
    "candidature_brouillons": ("maj_le", 30),
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
# Caractères autorisés dans un identifiant SQL (table/colonne). Durcissement owner
# 2026-06-18 : les noms interpolés ici viennent TOUS de dicts INTERNES (jamais d'un
# membre) → non exploitable, mais on refuse par PRINCIPE tout identifiant non conforme
# (défense en profondeur). Comme CHAQUE ouvrière (purge_user, run_retention, _filter_blob)
# appelle `_columns(db, table)` en premier et abandonne si le set est vide, valider ICI
# couvre TOUT le module en un seul point, fail-safe (table malformée → sautée partout).
_IDENT_OK = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _safe_ident(name) -> bool:
    """True si `name` est un identifiant SQL sûr (ASCII lettres/chiffres/_, pas de chiffre
    en tête). Tout le reste → False (la table sera sautée)."""
    return (isinstance(name, str) and bool(name) and name[0] not in "0123456789"
            and all(c in _IDENT_OK for c in name))


async def _columns(db, table):
    """Colonnes réelles d'une table (set), ou set() si la table n'existe pas / nom non
    conforme. Ne lève jamais."""
    if not _safe_ident(table):
        return set()  # garde-fou défense-en-profondeur (cf. _safe_ident) → table sautée
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
    for t, (col, _jours) in RETENTION.items():
        checks.setdefault(t, set()).update(col if isinstance(col, tuple) else (col,))

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
        noms = col if isinstance(col, tuple) else (col,)
        if not cols:
            continue
        if any(c not in cols for c in noms):
            #  Plus jamais en silence : une colonne qui manque, c'est une table jamais purgée.
            print("[GDPR][E1] colonne de rétention absente : table jamais purgée")
            print(f"[GDPR][E1:DETAIL] {table}.{noms}")
            continue
        expr = noms[0] if len(noms) == 1 else "COALESCE(%s)" % ", ".join(noms)
        cutoff_epoch = now_ts - days * 86400
        cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(cutoff_epoch))
        try:
            # epoch numérique : col < cutoff_epoch ; ISO texte : col < cutoff_iso.
            # On tente les deux formes via un OR typé tolérant (CAST échoue silencieusement → 0).
            cur = await db.execute(
                "DELETE FROM %s WHERE (typeof(%s) IN ('integer','real') AND %s < ?) "
                "OR (typeof(%s)='text' AND %s < ?)" % (table, expr, expr, expr, expr),
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
