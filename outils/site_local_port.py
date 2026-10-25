"""outils/site_local_port.py — « Le Port » et « L'Équipage » sur le VRAI site local (`outils/site_local.py`), 25/10/2026.

Ce qu'il manquait au site local pour éprouver ces rubriques comme sur le serveur :
  · les ACTIONS du tableau (`POST /tableau/espace/action`) — les vraies : `_ACTIONS_TABLEAU` de `bot.py` et ses
    aides, lues dans sa source (jamais importé : le bot démarrerait) et exécutées sur le faux serveur. Seuls les
    gestes vers Discord sont simulés (message privé, salon des logs, fermeture d'un salon de ticket) ;
  · la mesure d'activité du clan (actifs, peu présents, inactifs, jamais vus), comme `activite.presences` ;
  · la conversation d'un ticket dans la forme du bot (`_conversation_ticket` : en direct, transcript, absent, suivi) ;
  · de quoi voir chaque rubrique remplie : un membre du staff (hors direction : l'équipe, les modérateurs), une
    alerte, des rappels d'inactivité (prévenu, délai écoulé, revenu), l'entraide et le trade, les motifs de
    fermeture des tickets, des questions répondues, un nettoyage du casier à défaire.
Rien ne part chez Discord. Branché par `site_local.construire` ; à n'importer nulle part ailleurs.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord

try:
    from zoneinfo import ZoneInfo
except ImportError:  # sans base de fuseaux : l'heure UTC (comme bot.py)
    ZoneInfo = None

BOT = Path(__file__).resolve().parent.parent / "bot.py"
#  Ce que bot.py définit et que les actions appellent, exécuté ici dans cet ordre (`_ACTIONS_TABLEAU` en dernier :
#  il nomme les fonctions). Un nom disparu de bot.py fait échouer le démarrage du site local, et le dit.
NOMS_DU_BOT = (
    "_TICKET_TZ", "_TACHES_FERMETURE", "_direction_ou_plus", "_au_journal", "_journal_rellseas", "_heure_courte",
    "_format_warn_id", "_fermer_en_fond", "_cible_site", "_retirer_du_clan", "_escalade_warns",
    "_action_ticket_fermer", "_action_candidature", "_action_clan_ajouter", "_action_clan_prevenir",
    "_action_clan_rappel_annuler", "_action_clan_retirer", "_action_clan_retirer_lot", "_SANCTIONS_SITE",
    "_DUREES_MUTE", "_inscrire_sanction", "_action_moderer", "_action_question", "_action_alerte_geree",
    "_action_fiche_retirer", "_apres_casier", "_action_sanction_retirer", "_action_casier_effacer",
    "_action_casier_serveur", "_action_casier_restaurer", "_action_debannir", "_action_suggestion_repondre",
    "_action_suggestion_retirer", "_action_sondage_retirer", "_ACTIONS_TABLEAU",
)
STAFF_ID = 1010            # Hector : rôle « Staff », hors direction (l'équipe, les modérateurs)
BOT_ID = 999
JOUR = 86400
LIBELLES_MOD = {"warn": "Avertissement", "mute": "Mute", "unmute": "Fin du mute", "kick": "Expulsion",
                "ban": "Bannissement", "unban": "Bannissement levé"}


def _sources(noms) -> list[str]:
    arbre = ast.parse(BOT.read_text(encoding="utf-8"))
    trouves = {}
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            trouves[n.name] = n
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if isinstance(t, ast.Name) and t.id in noms:
                    trouves[t.id] = n
    manquants = [x for x in noms if x not in trouves]
    if manquants:
        raise RuntimeError("bot.py ne définit plus : " + ", ".join(manquants))
    return [ast.unparse(trouves[x]) for x in noms]


def _sqlite(t: float) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le faux serveur, complété pour les actions (rangs comparables, messages privés, sanctions)
# ═══════════════════════════════════════════════════════════════════════════════

def completer_faux_serveur(g, X) -> dict:
    """Ce que les actions demandent à Discord, simulé : comparer deux rôles (hiérarchie), écrire en privé,
    muter, expulser, bannir et débannir. Rend le carnet des gestes (messages privés, bannis)."""
    carnet = {"mp": [], "bannis": {}}

    def rang(r):
        return getattr(r, "position", 0)
    X.Role.__lt__ = lambda a, b: rang(a) < rang(b)
    X.Role.__le__ = lambda a, b: rang(a) <= rang(b)
    X.Role.__gt__ = lambda a, b: rang(a) > rang(b)
    X.Role.__ge__ = lambda a, b: rang(a) >= rang(b)

    async def envoyer(self, content=None, **kw):
        carnet["mp"].append((self.id, content, kw))
        return X.Obj(id=g.nouvel_id(), channel=X.Obj(id=0))

    async def muter(self, duree, reason=None):
        self.timed_out_until = None if duree is None else datetime.now(timezone.utc) + duree

    def sortir(m):
        g.membres.pop(m.id, None)
        if m in g.members:
            g.members.remove(m)
        for r in list(m.roles):
            if m in getattr(r, "members", []):
                r.members.remove(m)

    async def expulser(self, reason=None):
        sortir(self)
    X.Membre.send, X.Membre.timeout, X.Membre.kick = envoyer, muter, expulser

    async def bannir(m, reason=None, delete_message_seconds=None):
        carnet["bannis"][int(m.id)] = (m.display_name, reason or "")
        sortir(m)

    async def debannir(objet, reason=None):
        if carnet["bannis"].pop(int(objet.id), None) is None:
            raise discord.NotFound(X.Obj(status=404, reason="x"), "absent")

    async def lire_ban(objet):
        b = carnet["bannis"].get(int(objet.id))
        if b is None:
            raise discord.NotFound(X.Obj(status=404, reason="x"), "absent")
        return X.Obj(user=X.Obj(id=int(objet.id), name=b[0]), reason=b[1])
    g.ban, g.unban, g.fetch_ban = bannir, debannir, lire_ban
    #  Le bot du site local peut tout ce que le vrai a sur GoRP (sinon « Il me manque la permission… »).
    g.me.guild_permissions = discord.Permissions(manage_roles=True, manage_channels=True, ban_members=True,
                                                 kick_members=True, moderate_members=True, mention_everyone=True,
                                                 manage_messages=True)
    return carnet


# ═══════════════════════════════════════════════════════════════════════════════
#  Les actions du tableau : celles de bot.py
# ═══════════════════════════════════════════════════════════════════════════════

def actions_du_bot(*, g, X, get_db, cfg, tete, fondateur, carnet, log=print) -> dict:
    """`_ACTIONS_TABLEAU` de bot.py, exécuté sur le faux serveur : {nom: async (g, auteur, corps) → (ok, message)}."""
    import casier
    import clan
    import questions
    import recrutements
    import registre
    import rellseas_panneau
    import sondages
    import suggestions
    import tableau
    import vigilance
    from ui_v2 import LayoutView, Palette

    async def rien(*_a, **_k):
        return None

    async def ticket_ouvert(gg, tid):
        async with get_db() as db:
            async with db.execute("SELECT channel_id, user_id, claimed_by, panel_id FROM tickets WHERE id=? AND"
                                  " guild_id=? AND status='open'", (int(tid), gg.id)) as cur:
                r = await cur.fetchone()
        if r is None:
            return None, None
        return X.Obj(id=int(r[0] or 0), name=f"ticket-{int(tid)}"), {"id": int(tid), "user": int(r[1] or 0),
                                                                      "claimed": int(r[2] or 0), "panel_id": r[3] or ""}

    async def fermer_ticket(gg, ch, tk, closer, reason, inactif_jours=0, **_options):
        """Ce que la fermeture du bot écrit (`_fermer_ticket_corps`) : statut, suivi « close », audit (le motif)."""
        t = time.time()
        async with get_db() as db:
            await db.execute("UPDATE tickets SET status='closed' WHERE id=? AND guild_id=?", (tk["id"], gg.id))
            await db.execute("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, detail, created_unix)"
                             " VALUES (?,?,?,?,?,?)", (gg.id, tk["id"], "close", closer.id, str(reason)[:200], int(t)))
            await db.execute("INSERT INTO ticket_audit (guild_id, channel_id, action, actor_id, at, detail)"
                             " VALUES (?,?,?,?,?,?)", (gg.id, ch.id, "close", closer.id, _sqlite(t), str(reason)[:200]))
            await db.commit()
        await registre.noter(gg.id, "Tickets", "ticket.close", f"Ticket #{tk['id']} fermé par {closer.display_name}",
                             membre_id=tk["user"], auteur_id=closer.id, detail=str(reason)[:200])
        return True

    async def decision_recrutement(gg, tid, auteur, accepte, motif=""):
        async with get_db() as db:
            await db.execute("UPDATE tickets SET status='closed' WHERE id=? AND guild_id=?", (int(tid), gg.id))
            await db.commit()
        return True, "Candidature refusée : ticket fermé."

    async def journal_moderation(guild, action, mod, target, reason=None, duration=None, extra=None):
        """`send_mod_log` : sur le site, la sanction arrive au journal (le salon des logs n'existe plus)."""
        lib = LIBELLES_MOD.get(action, action)
        await registre.noter(guild.id, "Modération", f"mod.{action}",
                             f"{lib} : {getattr(target, 'display_name', target)}" + (f" ({duration})" if duration else ""),
                             membre_id=getattr(target, "id", 0) or 0, auteur_id=getattr(mod, "id", 0) or 0,
                             detail=str(reason or ""))

    async def message_prive(member, guild, action_label, reason, duration_text=None):
        carnet["mp"].append((member.id, action_label, {"raison": reason, "duree": duration_text}))

    async def infraction_auto(guild_id, user_id, typ, reason, duration=""):
        async with get_db() as db:
            await db.execute("INSERT INTO infractions (guild_id, user_id, mod_id, type, reason, duration, created_at)"
                             " VALUES (?,?,?,?,?,?,?)", (int(guild_id), int(user_id), BOT_ID, str(typ)[:30],
                                                         str(reason)[:300], str(duration)[:30], _sqlite(time.time())))
            await db.commit()

    def erreur(nom, ex, guild_id=0):
        log("[SITE LOCAL][ACTION] erreur dans une action du bot")
        log(f"[SITE LOCAL][ACTION:DETAIL] {nom} {type(ex).__name__} {ex}")

    ns = {
        "__name__": "bot_site_local", "discord": discord, "asyncio": asyncio, "time": time, "aiosqlite": aiosqlite,
        "datetime": datetime, "timedelta": timedelta, "timezone": timezone, "ZoneInfo": ZoneInfo,
        "now": lambda: datetime.now(timezone.utc), "cfg": cfg, "get_db": get_db, "bot": X.Obj(user=X.Obj(id=BOT_ID)),
        "registre": registre, "questions": questions, "vigilance": vigilance, "recrutements": recrutements,
        "casier": casier, "clan": clan, "suggestions": suggestions, "sondages": sondages, "tableau": tableau,
        "rellseas_ui": rellseas_panneau, "LayoutView": LayoutView, "Palette": Palette, "TETE_IDS": frozenset(tete),
        "owner_ids_module": X.Obj(is_super_owner=lambda uid: int(uid or 0) == fondateur),
        "recidivism_module": X.Obj(recompute=rien), "is_fully_immune": lambda m: _faux_async(False),
        "log_staff_action": rien, "_dm_sanction": message_prive, "send_mod_log": journal_moderation,
        "ulogger2026": X.Obj(log_member_escalation=rien), "_ticket_ouvert": ticket_ouvert,
        "_fermer_ticket": fermer_ticket, "_decision_recrutement": decision_recrutement, "_logerr": erreur,
        "_ensure_quarantine_role": rien, "_noter_isolement": rien, "_record_infraction": infraction_auto,
    }
    for source in _sources(NOMS_DU_BOT):
        exec(compile(source, str(BOT), "exec"), ns)  # noqa: S102 — le code du dépôt (bot.py), pas des données
    return dict(ns["_ACTIONS_TABLEAU"])


async def _faux_async(valeur):
    return valeur


# ═══════════════════════════════════════════════════════════════════════════════
#  L'activité du clan (comme `activite.presences`)
# ═══════════════════════════════════════════════════════════════════════════════

#  membre → (jours sans aucun geste, jours présents sur 7) ; None : jamais vu ; « recent » : arrivé il y a peu.
ACTIVITE = {1000: (0, 6), 1001: (1, 5), 1003: (12, 0), 1004: (2, 3), 1006: (0, 7), 1007: (45, 0), 1009: (60, 0),
            1010: (0, 7), 1012: (33, 0), 1013: (20, 0), 1015: (3, 2), 1016: None, 1018: "recent", 1019: (1, 4),
            1021: (9, 0), 1022: (90, 0)}


def mesurer_groupe():
    import activite_calendrier as cal

    async def mesurer(_guild_id, membres):
        out = {}
        for m in membres:
            a = ACTIVITE.get(int(m.id))
            if int(m.id) not in ACTIVITE:  # ajouté au clan depuis le site : un peu d'activité, stable
                n = int(hashlib.blake2b(str(m.id).encode(), digest_size=2).hexdigest(), 16)
                a = (n % 5, 1 + n % 6)
            if a is None:
                continue
            if a == "recent":
                out[m.id] = {"jugeable": False}
                continue
            silence, presents = a
            out[m.id] = {"jugeable": True, "silence": silence, "presents": presents, "fenetre": 7,
                         "dernier": cal.jour(datetime.now(timezone.utc) - timedelta(days=silence))}
        return out
    return mesurer


# ═══════════════════════════════════════════════════════════════════════════════
#  La conversation d'un ticket (comme `_conversation_ticket` de bot.py)
# ═══════════════════════════════════════════════════════════════════════════════

def conversation(*, g, get_db):
    async def lire(gg, ticket):
        async with get_db() as db:
            async with db.execute("SELECT user_id, status, created_at FROM tickets WHERE id=? AND guild_id=?",
                                  (int(ticket), gg.id)) as cur:
                tk = await cur.fetchone()
            async with db.execute("SELECT url FROM ticket_transcripts WHERE guild_id=? AND ticket_id=?",
                                  (gg.id, int(ticket))) as cur:
                tr = await cur.fetchone()
            async with db.execute("SELECT kind, actor_id, detail, created_unix FROM ticket_log_events WHERE guild_id=?"
                                  " AND ticket_id=? ORDER BY id", (gg.id, int(ticket))) as cur:
                evts = await cur.fetchall()
        if tk is None:
            return {"ticket": int(ticket), "messages": [], "absent": "Ticket introuvable."}

        def nom(uid):
            m = gg.get_member(int(uid or 0))
            return m.display_name if m is not None else ("membre parti" if uid else "")
        import recrutements
        debut = recrutements._unix(tk[2]) or int(time.time()) - 3600
        auteur = gg.get_member(int(tk[0] or 0))
        qui = auteur.display_name if auteur is not None else "Membre parti"
        avatar = str(auteur.display_avatar.url) if auteur is not None else ""
        chef = gg.get_member(int(next((a for k, a, _d, _t in evts if k == "claim"), 0) or 0))
        messages = [
            {"auteur": "GoRP Bot", "bot": True, "avatar": "", "quand": debut, "texte": "", "images": [], "videos": [],
             "fichiers": [], "embeds": [{"titre": f"Ticket #{int(ticket)}", "texte": "Merci d'avoir ouvert un ticket :"
                                         " un membre du staff arrive.", "champs": [["Membre", qui]], "pied": ""}]},
            {"auteur": qui, "bot": False, "avatar": avatar, "quand": debut + 120,
             "texte": "Bonjour, je voudrais rejoindre l'équipage.", "images": [], "videos": [], "fichiers": [],
             "embeds": []}]
        if chef is not None:
            messages.append({"auteur": chef.display_name, "bot": False, "avatar": str(chef.display_avatar.url),
                             "quand": debut + 1800, "texte": "Bienvenue ! Ton pseudo Roblox ?", "images": [],
                             "videos": [], "fichiers": [], "embeds": []})
        suivi = [{"quoi": str(k or ""), "qui": nom(a), "quand": int(t or 0), "detail": str(d or "")[:300]}
                 for k, a, d, t in evts[-40:]]
        lien = (tr[0] if tr else "") or ""
        if tk[1] == "open":
            res = {"ticket": int(ticket), "source": "discord", "messages": messages}
        elif lien:
            res = {"ticket": int(ticket), "source": "transcript", "messages": messages, "lien": lien}
        else:
            res = {"ticket": int(ticket), "messages": [], "lien": "", "absent": "Aucun transcript enregistré pour ce ticket."}
        res["suivi"] = suivi
        return res
    return lire


# ═══════════════════════════════════════════════════════════════════════════════
#  Les données de démonstration du Port et de l'Équipage
# ═══════════════════════════════════════════════════════════════════════════════

MOTIFS = ("Résolu", "Problème réglé en vocal", "Sans réponse du membre", "Doublon", "Signalement traité : sanction",
          "Rôle remis")


async def remplir(*, get_db, g, salon, tete, fondateur, direction) -> None:
    """Après `site_local._remplir` : ce qu'il faut pour voir le Port et l'Équipage comme sur le serveur."""
    import casier
    import clan
    t = time.time()
    staff = next(r for r in g.roles if r.name == "Staff")
    hector = g.get_member(STAFF_ID)
    if staff not in hector.roles:
        hector.roles.append(staff)
        staff.members.append(hector)
    async with get_db() as db:
        #  Les tables que bot.py crée et que les actions touchent (compteurs du filtre, toxicité).
        await db.execute("CREATE TABLE IF NOT EXISTS badword_strikes (guild_id INTEGER, user_id INTEGER, strikes INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS user_toxicity_scores (guild_id INTEGER, user_id INTEGER, score REAL)")
        #  Les motifs de fermeture (le bot les écrit à l'audit), et un transcript pour deux tickets fermés sur trois.
        async with db.execute("SELECT id, channel_id FROM tickets WHERE guild_id=? AND status='closed'", (g.id,)) as cur:
            fermes = await cur.fetchall()
        for k, (tid, salon_id) in enumerate(fermes):
            async with db.execute("SELECT created_unix, actor_id FROM ticket_log_events WHERE guild_id=? AND ticket_id=?"
                                  " AND kind='close'", (g.id, tid)) as cur:
                fin = await cur.fetchone()
            quand = int(fin[0]) if fin else int(t)
            motif = MOTIFS[k % len(MOTIFS)]   # le même motif au suivi du ticket et à l'audit, comme à la fermeture
            await db.execute("UPDATE ticket_log_events SET detail=? WHERE guild_id=? AND ticket_id=? AND kind='close'",
                             (motif, g.id, tid))
            await db.execute("INSERT INTO ticket_audit (guild_id, channel_id, action, actor_id, at, detail)"
                             " VALUES (?,?,?,?,?,?)", (g.id, salon_id, "close", int(fin[1]) if fin else direction,
                                                      _sqlite(quand), motif))
            if k % 3:
                await db.execute("INSERT INTO ticket_transcripts (guild_id, ticket_id, url, user_name, closed_at)"
                                 " VALUES (?,?,?,?,?)", (g.id, tid, f"https://exemple.invalid/transcript/{tid}", "",
                                                         _sqlite(quand)))
        #  Le staff (hors direction) : des tickets pris et fermés, des sanctions décidées — l'équipe, les modérateurs.
        membres = [m for m in g.members if m.id not in tete and m.id != STAFF_ID]
        for k in range(6):
            tid, m = 45 + k, membres[(5 * k + 3) % len(membres)]
            ouvert = t - (2 + 3 * k) * JOUR
            await db.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)",
                             (tid, g.id, 5000 + tid, m.id, "p2" if k % 2 else "p3", STAFF_ID, "closed" if k else "open",
                              "{}", _sqlite(ouvert)))
            await db.execute("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, created_unix)"
                             " VALUES (?,?,?,?,?)", (g.id, tid, "claim", STAFF_ID, int(ouvert + 900)))
            if k:
                await db.execute("INSERT INTO ticket_log_events (guild_id, ticket_id, kind, actor_id, detail, created_unix)"
                                 " VALUES (?,?,?,?,?,?)", (g.id, tid, "close", STAFF_ID, "Résolu", int(ouvert + 7200)))
                await db.execute("INSERT INTO ticket_audit (guild_id, channel_id, action, actor_id, at, detail)"
                                 " VALUES (?,?,?,?,?,?)", (g.id, 5000 + tid, "close", STAFF_ID, _sqlite(ouvert + 7200),
                                                          "Résolu"))
        for k in range(5):
            m = membres[(7 * k + 2) % len(membres)]
            await db.execute("INSERT INTO infractions (guild_id, user_id, mod_id, type, reason, duration, created_at)"
                             " VALUES (?,?,?,?,?,?,?)", (g.id, m.id, STAFF_ID, "warn" if k != 2 else "mute",
                                                         ("Spam", "Insultes", "Flood", "Pub", "Hors sujet")[k],
                                                         "1 heure" if k == 2 else "", _sqlite(t - (1 + 4 * k) * JOUR)))
        #  Des questions répondues par le staff (le délai de réponse se mesure), une traitée, une qui n'en était pas.
        for k, (texte, statut, delai) in enumerate((("Le trade est ouvert à quelle heure ?", "repondue", 1500),
                                                    ("On peut changer de faction ?", "resolue", 5400),
                                                    ("Quelqu'un pour le boss du volcan ?", "ignoree", 0),
                                                    ("Comment on monte de grade ?", "traitee", 9000))):
            quand = int(t - (k + 1) * 7200 - 86400)
            await db.execute("INSERT INTO questions (guild_id, salon_id, message_id, auteur_id, texte, quand, statut,"
                             " repondu_par, repondu_le, par_staff, lien) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (g.id, salon.id, 7100 + k, membres[k + 4].id, texte, quand, statut,
                              STAFF_ID if delai else 0, quand + delai if delai else 0, 1 if delai else 0,
                              f"https://discord.com/channels/{g.id}/{salon.id}/{7200 + k}" if delai else ""))
        #  Un sondage terminé, deux idées décidées.
        await db.execute("INSERT INTO sondages (message_id, guild_id, channel_id, auteur_id, question, choix, comptes,"
                         " total, cree_le, fin_le, termine) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (8002, g.id, salon.id, membres[3].id, "Le meilleur style de combat ?",
                          json.dumps(["Sabre", "Mains nues", "Tir"]), json.dumps([7, 3, 5]), 15,
                          _sqlite(t - 6 * JOUR), _sqlite(t - 3 * JOUR), 1))
        for k, (titre, statut, note) in enumerate((("Des tournois de pêche le dimanche", "etude", ""),
                                                   ("Un rôle pour les vétérans", "acceptee", "Bonne idée : on s'en occupe."))):
            await db.execute("INSERT INTO suggestions_v2 (guild_id, channel_id, message_id, auteur_id, titre, details,"
                             " statut, note, decide_par, cree_le, decide_le) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (g.id, salon.id, 8110 + k, membres[6 + k].id, titre, "Pour motiver l'équipage.", statut, note,
                              direction, _sqlite(t - (8 + k) * JOUR), _sqlite(t - (2 + k) * JOUR)))
        #  L'entraide et le trade : en cours, prises, certifiées, closes.
        demandes = (("aide", "Bloqué à la quête du phare", "ouverte", 3, [], 0, 0),
                    ("boss", "Léviathan ce soir", "prise", 9, [1, 2], 0, 0),
                    ("trade", "Fruit de la Flamme contre un galion", "terminee", 30, [3], 1, 4),
                    ("farm", "Farm de berrys à l'île du Levant", "expiree", 50, [], 0, 0),
                    ("cl_trade", "Sabre courbe à vendre", "ouverte", 6, [5], 0, 0),
                    ("chill", "Balade en mer, tout le monde est bienvenu", "fermee", 70, [], 0, 0))
        for k, (zone, titre, statut, heures, aidants, certifie, partenaire) in enumerate(demandes):
            cree = int(t - heures * 3600)
            ferme = 0 if statut in ("ouverte", "prise") else cree + 7200
            await db.execute("INSERT INTO entraide_demandes (guild_id, zone, auteur_id, titre, champs, statut, salon_id,"
                             " fil_id, aidants, cree, maj, ferme, ferme_par, certifie_par, partenaire_id, mode)"
                             " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (g.id, zone, membres[k + 1].id, titre,
                              json.dumps([["Pseudo Roblox", f"{membres[k + 1].display_name.split()[0]}_RS"],
                                          ["Niveau · Level", str(40 + 25 * k)]]),
                              statut, salon.id, 9100 + k, json.dumps([membres[(k + 1 + a) % len(membres)].id for a in aidants]),
                              cree, cree, ferme, membres[k + 1].id if ferme and not certifie else 0,
                              STAFF_ID if certifie else 0, membres[partenaire].id if partenaire else 0, "carte"))
        #  Une alerte : trois faits graves en quelques heures (la carte du salon des logs est simulée).
        suspect = g.get_member(1006)
        for k, (type_, texte, gravite) in enumerate((("sec.scam", "Lien d'arnaque supprimé", 3),
                                                      ("sec.mention", "Mentions de masse bloquées", 2),
                                                      ("sec.badword", "Insulte détectée par le filtre", 2))):
            await db.execute("INSERT INTO registre (guild_id, quand, categorie, type, membre_id, auteur_id, salon_id, texte,"
                             " detail, gravite) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (g.id, int(t - (5 - k) * 1800), "Sécurité", type_, suspect.id, 0, salon.id,
                              f"{texte} : {suspect.display_name}", "", gravite))
        await db.execute("INSERT OR REPLACE INTO vigilance (guild_id, membre_id, message_id, salon_id, ouverte_le, maj_le,"
                         " base_le) VALUES (?,?,?,?,?,?,?)", (g.id, suspect.id, 9900, salon.id, int(t - 3600), int(t - 900), 0))
        await db.commit()
    #  Les rappels d'inactivité du clan : un délai écoulé, un prévenu, un revenu (fermé tout seul par `clan.rappels`).
    await clan.prevenir(g.id, [1007], direction, "mp", 0, {1007: True}, maintenant=t - 8 * JOUR)
    await clan.prevenir(g.id, [1009], fondateur, "salon", salon.id, {}, maintenant=t - 2 * JOUR)
    await clan.prevenir(g.id, [1015], fondateur, "mp", 0, {1015: False}, maintenant=t - 9 * JOUR)
    #  Des nettoyages du casier, à défaire depuis « Sanctions » : une zone (les détections automatiques de plus de 90
    #  jours) et le casier d'une personne (ses avertissements).
    await casier.nettoyer(g.id, "auto", 90, fondateur, BOT_ID)
    async with get_db() as db:
        async with db.execute("SELECT user_id FROM infractions WHERE guild_id=? AND type='warn' GROUP BY user_id"
                              " ORDER BY COUNT(*) DESC, user_id LIMIT 1", (g.id,)) as cur:
            averti = await cur.fetchone()
    if averti:
        await casier.effacer_membre(g.id, int(averti[0]), "warns", direction)
