"""longevite.py — le site sur plusieurs années (26/10/2026).

« Imagine-toi que le site peut aussi tourner sur plusieurs années, voire est-ce qu'il peut tenir le coup ou pas. » —
« fait en sorte qu'on puisse nettoyer tout comme on souhaite. Par exemple, qu'il n'y ait pas des milliers de tickets
logs de gens qui ont déjà fermé. »

Mesuré par `outils/banc_annees.py` (le vrai site local rempli de 1, 3 et 5 ans de serveur). Ce module apporte :

  · LA SUITE des longues listes, que la page demande quand on ouvre un groupe, cherche, ou touche « Voir plus » —
    les données (`donnees`) n'en portent que le début :
      `GET api/journal`        le journal filtré PAR LE SERVEUR (période, catégorie, gravité, recherche), 200 par page
                               (à 5 ans : 4 000 évènements par jour ; les données n'en portent que les 400 derniers) ;
      `GET api/tickets/fermes` un mois des archives, ou une recherche (les données : les 300 plus récents) ;
      `GET api/casier/membres` le reste du casier, 250 cases par page, ou une recherche (les données : 250 cases).
  · Une RÈGLE DE NETTOYAGE pour chaque famille de données qui grossissait sans fin ou qu'une purge cachée effaçait
    sans le dire — toutes visibles et réglables dans la rubrique « Nettoyage », avec l'aperçu de ce qui part et un
    « Nettoyer maintenant ». Rien ne part plus tôt qu'avant par défaut : les durées que le bot tenait cachées sont
    reprises telles quelles (et restent son filet) ; ce qui n'avait AUCUNE durée en reçoit une, prudente.
  · Les FICHIERS ORPHELINS : images et portraits sans référence, images de transcripts sans leur page, restes
    d'écriture (`.tmp`) — plus d'un jour.
  · L'ÉTAT DU STOCKAGE (base, pages libres, compactage, dossiers, copies, volume) pour la rubrique.
Branché par le bot (étape du site) et le site local : `setup(get_db=…, chemin_base=…)` puis `tableau.monter(longevite)`.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import casier
import compactage
import recrutements
import rellseas_panneau
import tableau
import transcript_store

JOUR = 86400
JOURNAL_PAGE, JOURNAL_PAGE_MAX = 200, 500
FERMES_MAX = 3000            # tickets d'un mois des archives (ou d'une recherche) au plus
CASIER_PAGE, CASIER_PAGE_MAX = 250, 500
RECHERCHE_IDS = 300          # personnes reconnues par leur nom dans une recherche du journal
LOT = 500                    # suppressions par paquet (la base n'est jamais tenue longtemps)
ORPHELIN_AGE_S = 86400       # un fichier sans référence depuis plus d'un jour est un orphelin
STOCKAGE_FRAIS = 600         # s : la taille des dossiers, relue au plus toutes les 10 minutes
FORMAT_JETON = re.compile(r"[A-Za-z0-9_-]{16,86}")

_get_db = None
_chemin_base = None
_log = print
_dossiers: dict = {"t": 0.0, "valeur": None}
_orphelins_vus: dict = {"t": 0.0, "n": None}   # l'aperçu des orphelins (un parcours des dossiers), gardé STOCKAGE_FRAIS


def setup(*, get_db, chemin_base=None, log=None) -> None:
    global _get_db, _chemin_base, _log
    _get_db, _chemin_base, _log = get_db, chemin_base, log or print
    tableau.ETAT_STOCKAGE = etat_stockage
    compactage.setup(log=_log)
    _dossiers.update(t=0.0, valeur=None)
    _orphelins_vus.update(t=0.0, n=None)


def pret() -> bool:
    return _get_db is not None


async def _lignes(sql: str, args: tuple = ()) -> list:
    """Les lignes d'une lecture — une table absente (base ancienne, module pas branché) : aucune."""
    async with _get_db() as db:
        return await recrutements._lignes(db, sql, args)


async def _compter(sql: str, args: tuple = ()) -> int:
    rows = await _lignes(sql, args)
    return int(rows[0][0] or 0) if rows else 0


async def _supprimer(sql: str, args: tuple = ()) -> int:
    """Un DELETE ; une table absente : 0."""
    async with _get_db() as db:
        try:
            cur = await db.execute(sql, args)
        except sqlite3.OperationalError as ex:
            if "no such table" in str(ex):
                return 0
            raise
        n = max(cur.rowcount or 0, 0)
        await db.commit()
    return n


def _sqlite(t: float) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _robot() -> int:
    return int(getattr(getattr(tableau._bot, "user", None), "id", 0) or 0)


def _entier(requete: dict, nom: str, defaut: int = 0, mini: int = 0, maxi: int = 2 ** 62) -> int:
    brut = str(requete.get(nom, "") or "")
    if not brut:
        return defaut
    if not brut.isdigit() or len(brut) > 18:
        raise ValueError(nom)
    return max(mini, min(maxi, int(brut)))


def _recherche(requete: dict) -> str:
    return re.sub(r"\s+", " ", str(requete.get("q", "") or "")).strip()[:64]


def _ids_nommes(g, q: str) -> list:
    """Les membres dont le nom, le pseudo ou l'identifiant contient `q` (RECHERCHE_IDS au plus)."""
    if q.isdigit():
        return [int(q)] if len(q) <= 20 else []
    cle, out = q.casefold(), []
    for m in getattr(g, "members", None) or []:
        if cle in str(getattr(m, "display_name", "")).casefold() or cle in str(getattr(m, "name", "")).casefold():
            out.append(int(m.id))
            if len(out) >= RECHERCHE_IDS:
                break
    return out


def _motif_like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ═══════════════════════════════════════════════════════════════════════════════
#  La suite des longues listes
# ═══════════════════════════════════════════════════════════════════════════════

async def _route_journal(g, auteur, requete, corps):
    """`GET api/journal?depuis=&jusqua=&cat=&gravite=&q=&avant=&n=` → `{"evenements", "suite", "total", "personnes"}` :
    le journal filtré par le serveur, du plus récent au plus ancien, `n` par page (200 ; 500 au plus). `avant` : la
    `suite` rendue par la page précédente (« quand:id »). `total` : combien en tout pour ce filtre.
    `comptes=1` : en plus, `par_categorie` (le même filtre sans la catégorie : les puces de la page) et `par_jour`
    (combien chaque jour, à l'heure de Paris : « 300 sur 3 610 » dans le groupe d'un jour).
    `resume=1` : en plus, `graves` et `personnes_n` (les tuiles du journal)."""
    try:
        depuis = _entier(requete, "depuis")
        jusqua = _entier(requete, "jusqua")
        n = _entier(requete, "n", JOURNAL_PAGE, 1, JOURNAL_PAGE_MAX)
        gravite = _entier(requete, "gravite", 0, 0, 3)
    except ValueError as ex:
        return 400, {"erreur": "Demande invalide.", "champ": str(ex)}
    avant = str(requete.get("avant", "") or "")
    curseur = None
    if avant:
        morceaux = avant.split(":")
        if len(morceaux) != 2 or not all(x.isdigit() and len(x) <= 18 for x in morceaux):
            return 400, {"erreur": "Demande invalide.", "champ": "avant"}
        curseur = (int(morceaux[0]), int(morceaux[1]))
    cat = str(requete.get("cat", "") or "")[:40]
    q = _recherche(requete)
    #  `du` / `au` : des jours entiers, à l'heure de Paris (le groupe d'un jour, d'une semaine, d'un mois de la page).
    for nom in ("du", "au"):
        brut = str(requete.get(nom, "") or "")
        if not brut:
            continue
        try:
            jour = datetime.strptime(brut, "%Y-%m-%d").date()
        except ValueError:
            return 400, {"erreur": "Jour invalide.", "champ": nom}
        if nom == "au":   # jusqu'au lendemain à minuit (la vraie minuit de Paris, changement d'heure compris)
            jour += timedelta(days=1)
        borne = int(datetime(jour.year, jour.month, jour.day, tzinfo=tableau.PARIS).timestamp())
        if nom == "au":
            jusqua = min(jusqua, borne) if jusqua else borne
        else:
            depuis = max(depuis, borne)
    filtres = []   # (clause, valeurs, c'est la catégorie)
    if depuis:
        filtres.append(("quand>=?", [depuis], False))
    if jusqua:
        filtres.append(("quand<?", [jusqua], False))
    if cat and cat != "tous":
        filtres.append(("categorie=?", [cat], True))
    if gravite:
        filtres.append(("gravite>=?", [gravite], False))
    if q:
        ou, a = ["texte LIKE ? ESCAPE '\\'", "detail LIKE ? ESCAPE '\\'", "categorie LIKE ? ESCAPE '\\'"], [_motif_like(q)] * 3
        ids = _ids_nommes(g, q)
        if ids:
            marques = ",".join("?" * len(ids))
            ou += [f"membre_id IN ({marques})", f"auteur_id IN ({marques})"]
            a += ids + ids
        filtres.append(("(" + " OR ".join(ou) + ")", a, False))

    def filtre(avec_categorie: bool = True) -> tuple:
        garde = [f for f in filtres if avec_categorie or not f[2]]
        return " AND ".join(["guild_id=?"] + [c for c, _v, _k in garde]), [g.id] + [x for _c, v, _k in garde for x in v]
    where, args = filtre()
    extra = {}
    if requete.get("resume") == "1":   # les chiffres d'une période (tuiles du journal) : combien, dont graves, qui
        r = await _lignes("SELECT COUNT(*), COALESCE(SUM(gravite >= 2), 0), COUNT(DISTINCT CASE WHEN membre_id > 0 THEN"
                          f" membre_id END) FROM registre WHERE {where}", tuple(args))
        total, graves, personnes = (int(x or 0) for x in r[0]) if r else (0, 0, 0)
        extra = {"graves": graves, "personnes_n": personnes}
    else:
        total = await _compter(f"SELECT COUNT(*) FROM registre WHERE {where}", tuple(args))
    if requete.get("comptes") == "1":
        w2, a2 = filtre(False)
        extra["par_categorie"] = {str(c or "Autre"): int(k) for c, k in await _lignes(
            f"SELECT categorie, COUNT(*) FROM registre WHERE {w2} GROUP BY categorie", tuple(a2))}
        jours: dict = {}
        for h, k in await _lignes(f"SELECT quand / 3600, COUNT(*) FROM registre WHERE {where} GROUP BY 1", tuple(args)):
            jour = datetime.fromtimestamp(int(h) * 3600, tableau.PARIS).strftime("%Y-%m-%d")
            jours[jour] = jours.get(jour, 0) + int(k)
        extra["par_jour"] = jours
    if curseur is not None:
        where += " AND (quand<? OR (quand=? AND id<?))"
        args += [curseur[0], curseur[0], curseur[1]]
    import registre
    rows = await _lignes(f"SELECT {', '.join(registre.COLONNES)} FROM registre WHERE {where}"
                         " ORDER BY quand DESC, id DESC LIMIT ?", (*args, n + 1))
    rangs = [dict(zip(registre.COLONNES, r)) for r in rows]
    qui = tableau._Personnes(g)
    suite = f"{rangs[n - 1]['quand']}:{rangs[n - 1]['id']}" if len(rangs) > n else None
    return 200, {"evenements": [tableau._evenement(g, r, qui) for r in rangs[:n]], "suite": suite, "total": total,
                 "personnes": dict(qui), **extra}


async def _route_tickets_fermes(g, auteur, requete, corps):
    """`GET api/tickets/fermes?mois=AAAA-MM` (un mois des archives, en entier), `?depuis=` (fermés depuis cette date) ou
    `?q=` (une recherche dans tous les tickets fermés : membre, numéro, motif, type) → `{"fermes", "total",
    "personnes"}`, du plus récent au plus ancien."""
    mois = str(requete.get("mois", "") or "")
    q = _recherche(requete)
    try:
        depuis = _entier(requete, "depuis")
    except ValueError:
        return 400, {"erreur": "Demande invalide.", "champ": "depuis"}
    if mois and not re.fullmatch(r"\d{4}-\d{2}", mois):
        return 400, {"erreur": "Mois invalide.", "champ": "mois"}
    if not mois and not q and not depuis:
        return 400, {"erreur": "Un mois, une date ou une recherche.", "champ": "mois"}
    c = await tableau._cfg(g.id)
    panneaux = c.get("ticket_panels") or {}
    rell = rellseas_panneau.panneaux_tickets(c)
    cle = q.casefold().lstrip("#")
    out = []
    for x in await tableau._lignes_tickets(g):
        if x["statut"] == "open":
            continue
        fin = x["fin"]
        ferme = fin[0] if fin and fin[0] else (x["ouvert"] or 0)
        if mois and (not ferme or tableau._mois_paris(ferme) != mois):
            continue
        if depuis and ferme < depuis:
            continue
        nom = str((panneaux.get(x["panel"]) or {}).get("name") or "Sans type")
        if q:
            m = g.get_member(int(x["uid"] or 0))
            botte = " ".join(str(v) for v in (x["uid"], x["ticket"], x["motif"], nom, getattr(m, "display_name", ""),
                                               getattr(m, "name", ""))).casefold()
            if cle not in botte:
                continue
        out.append((ferme, x, nom, str(x["panel"] or "") in rell))
    out.sort(key=lambda f: f[0], reverse=True)
    qui = tableau._Personnes(g)
    return 200, {"fermes": [tableau.ticket_ferme(g, qui, *f) for f in out[:FERMES_MAX]], "total": len(out),
                 "personnes": dict(qui)}


async def _route_casier_membres(g, auteur, requete, corps):
    """`GET api/casier/membres?apres=&n=&q=` → `{"membres", "total", "suite", "personnes"}` : les cases du casier au-delà
    des 250 des données (rangées par date de leur dernière entrée), ou celles qu'une recherche trouve (nom, identifiant,
    motif, modérateur)."""
    try:
        apres = _entier(requete, "apres", 0, 0, 10 ** 7)
        n = _entier(requete, "n", CASIER_PAGE, 1, CASIER_PAGE_MAX)
    except ValueError as ex:
        return 400, {"erreur": "Demande invalide.", "champ": str(ex)}
    q = _recherche(requete).casefold()
    c = await tableau._cfg(g.id)
    apart = tableau.a_part(g, c)
    rows = await _lignes("SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                         " WHERE guild_id=? ORDER BY id DESC", (g.id,))
    cartes = sorted(tableau.cartes_casier(g, rows, apart, _robot(), time.time()).values(), key=lambda f: -f["derniere"])
    if q:
        def trouve(f):
            m = g.get_member(int(f["id"]))
            botte = " ".join([f["id"], getattr(m, "display_name", "") or "", getattr(m, "name", "") or ""]
                             + [f"{x['raison']} {x['par']}" for x in f["liste"]]).casefold()
            return q in botte
        cartes = [f for f in cartes if trouve(f)]
    page = cartes[apres:apres + n]
    qui = tableau._Personnes(g)
    for f in page:
        qui(int(f["id"]))
    return 200, {"membres": page, "total": len(cartes), "suite": apres + n if apres + n < len(cartes) else None,
                 "personnes": dict(qui)}


ROUTES_SITE = {
    "journal": {"methode": "GET", "fn": _route_journal, "corps_max": 0},
    "tickets/fermes": {"methode": "GET", "fn": _route_tickets_fermes, "corps_max": 0},
    "casier/membres": {"methode": "GET", "fn": _route_casier_membres, "corps_max": 0},
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les règles de nettoyage (rubrique « Nettoyage » du site)
# ═══════════════════════════════════════════════════════════════════════════════

#  ─── Les tickets fermés : la ligne, son suivi, son audit, ses extras, sa conversation ─────────────────────────────
_FERMES_AVANT = ("SELECT t.id, t.channel_id FROM tickets t WHERE t.guild_id=? AND t.status!='open' AND COALESCE("
                 "(SELECT MAX(e.created_unix) FROM ticket_log_events e WHERE e.guild_id=t.guild_id AND e.ticket_id=t.id"
                 " AND e.kind='close'), CAST(strftime('%s', t.created_at) AS INTEGER), 0) < ?")


async def _tickets_fermes_avant(gid: int, borne: int, limite: int | None = None) -> list:
    return await _lignes(_FERMES_AVANT + (f" LIMIT {int(limite)}" if limite else ""), (gid, borne))


async def _jetons_gardes() -> set:
    """Les conversations qu'une fiche de candidature cite encore : elles suivent leur propre règle."""
    out = set()
    for (url,) in await _lignes("SELECT transcript FROM recrutements WHERE transcript != ''"):
        j = transcript_store.jeton_de(url)
        if j:
            out.add(j)
    return out


def _effacer_transcript(jeton: str) -> int:
    if not jeton or not FORMAT_JETON.fullmatch(jeton):
        return 0
    n = 0
    p = transcript_store.transcript_path(jeton)
    if p and os.path.isfile(p):
        os.remove(p)
        n += 1
    d = os.path.join(transcript_store._BASE_DIR, "a_" + jeton)
    if os.path.isdir(d):   # ses images : un reste éventuel (fichier verrouillé) repart avec les orphelins
        shutil.rmtree(d, ignore_errors=True)
    return n


async def _purger_tickets(gid, jours, t):
    borne, n = int(t - jours * JOUR), 0
    gardes = await _jetons_gardes()
    while True:
        rows = await _tickets_fermes_avant(gid, borne, LOT)
        if not rows:
            break
        ids = [int(r[0]) for r in rows]
        salons = [int(r[1]) for r in rows if r[1]]
        m_ids, m_salons = ",".join("?" * len(ids)), ",".join("?" * len(salons)) or "0"
        jetons = [str(r[0]) for r in await _lignes(f"SELECT jeton FROM ticket_transcripts WHERE guild_id=? AND ticket_id IN"
                                                  f" ({m_ids}) AND jeton IS NOT NULL AND jeton != ''", (gid, *ids))]
        for sql, cles in ((f"DELETE FROM ticket_log_events WHERE guild_id=? AND ticket_id IN ({m_ids})", ids),
                          (f"DELETE FROM ticket_transcripts WHERE guild_id=? AND ticket_id IN ({m_ids})", ids),
                          (f"DELETE FROM ticket_log_msgs WHERE guild_id=? AND ticket_id IN ({m_ids})", ids),
                          (f"DELETE FROM ticket_audit WHERE guild_id=? AND channel_id IN ({m_salons})", salons),
                          (f"DELETE FROM ticket_tags WHERE guild_id=? AND channel_id IN ({m_salons})", salons)):
            await _supprimer(sql, (gid, *cles))
        await _supprimer(f"DELETE FROM ticket_extras WHERE channel_id IN ({m_salons})", tuple(salons))
        partis = await _supprimer(f"DELETE FROM tickets WHERE guild_id=? AND id IN ({m_ids})", (gid, *ids))
        n += partis
        await asyncio.to_thread(lambda: [_effacer_transcript(j) for j in jetons if j not in gardes])
        if len(rows) < LOT or not partis:
            break
    return n


async def _apercu_tickets(gid, jours, t):
    return len(await _tickets_fermes_avant(gid, int(t - jours * JOUR)))


async def _compter_tickets(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status!='open'", (gid,))


#  ─── Le casier : par `casier.nettoyer` — chaque passage est un nettoyage annulable 30 jours (« Nettoyer le casier ») ──
def _casier(portee: str):
    async def fn(gid, jours, t):
        return int((await casier.nettoyer(gid, portee, int(jours), 0, _robot()))["n"])

    async def apercu(gid, jours, t):
        sql, args = casier.filtre(portee, int(jours), _robot())
        return await _compter(f"SELECT COUNT(*) FROM infractions WHERE guild_id=? AND ({sql})", (gid, *args))

    async def compter(gid, jours, t):
        sql, args = casier.filtre(portee, 0, _robot())
        return await _compter(f"SELECT COUNT(*) FROM infractions WHERE guild_id=? AND ({sql})", (gid, *args))
    return fn, apercu, compter


_detections, _apercu_detections, _compter_detections = _casier("auto")
_sanctions, _apercu_sanctions, _compter_sanctions = _casier("tout")


#  ─── Les salons : questions, sondages, idées, entraide ───────────────────────────────────────────────────────────
async def _purger_questions(gid, jours, t):
    return await _supprimer("DELETE FROM questions WHERE guild_id=? AND quand < ?", (gid, int(t - jours * JOUR)))


async def _apercu_questions(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM questions WHERE guild_id=? AND quand < ?", (gid, int(t - jours * JOUR)))


async def _purger_sondages(gid, jours, t):
    return await _supprimer("DELETE FROM sondages WHERE guild_id=? AND cree_le < ?", (gid, _sqlite(t - jours * JOUR)))


async def _apercu_sondages(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM sondages WHERE guild_id=? AND cree_le < ?", (gid, _sqlite(t - jours * JOUR)))


_IDEES_FINIES = ("SELECT id FROM suggestions_v2 WHERE guild_id=? AND ((retire_le > 0 AND retire_le < ?)"
                 " OR (statut IN ('acceptee', 'refusee', 'realisee') AND decide_le IS NOT NULL AND decide_le < ?))")


async def _purger_idees(gid, jours, t):
    borne, n = t - jours * JOUR, 0
    while True:
        ids = [int(r[0]) for r in await _lignes(_IDEES_FINIES + f" LIMIT {LOT}", (gid, int(borne), _sqlite(borne)))]
        if not ids:
            break
        marques = ",".join("?" * len(ids))
        await _supprimer(f"DELETE FROM suggestions_votes WHERE suggestion_id IN ({marques})", tuple(ids))
        partis = await _supprimer(f"DELETE FROM suggestions_v2 WHERE guild_id=? AND id IN ({marques})", (gid, *ids))
        n += partis
        if len(ids) < LOT or not partis:
            break
    return n


async def _apercu_idees(gid, jours, t):
    borne = t - jours * JOUR
    return len(await _lignes(_IDEES_FINIES, (gid, int(borne), _sqlite(borne))))


#  Une demande close (son fil déjà retiré de Discord) ; jamais un échange CERTIFIÉ (il fait la réputation du membre).
_ENTRAIDE_CLOSES = ("SELECT id FROM entraide_demandes WHERE guild_id=? AND statut NOT IN ('ouverte', 'prise')"
                    " AND (supprime=1 OR fil_id=0) AND ferme > 0 AND ferme < ? AND NOT (statut='terminee' AND certifie_par!=0)")


async def _purger_entraide(gid, jours, t):
    borne, n = int(t - jours * JOUR), 0
    while True:
        ids = [int(r[0]) for r in await _lignes(_ENTRAIDE_CLOSES + f" LIMIT {LOT}", (gid, borne))]
        if not ids:
            break
        marques = ",".join("?" * len(ids))
        await _supprimer(f"DELETE FROM entraide_notes WHERE demande_id IN ({marques})", tuple(ids))
        partis = await _supprimer(f"DELETE FROM entraide_demandes WHERE guild_id=? AND id IN ({marques})", (gid, *ids))
        n += partis
        if len(ids) < LOT or not partis:
            break
    return n


async def _apercu_entraide(gid, jours, t):
    return len(await _lignes(_ENTRAIDE_CLOSES, (gid, int(t - jours * JOUR))))


async def _compter_entraide(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM entraide_demandes WHERE guild_id=?", (gid,))


#  ─── Le clan : les actualités de l'équipage (jamais les épinglées) ───────────────────────────────────────────────
async def _purger_actualites(gid, jours, t):
    return await _supprimer("DELETE FROM equipage_actualites WHERE guild_id=? AND epingle=0 AND cree_le < ?",
                            (gid, int(t - jours * JOUR)))


async def _apercu_actualites(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM equipage_actualites WHERE guild_id=? AND epingle=0 AND cree_le < ?",
                          (gid, int(t - jours * JOUR)))


#  ─── Les portraits Roblox : ceux qu'aucune affiche ne cite (une recherche sans suite, une affiche effacée) ─────────
_PORTRAITS_SEULS = ("SELECT roblox_id FROM rell_avatars WHERE maj_le < ? AND roblox_id NOT IN"
                    " (SELECT roblox_id FROM rell_affiches WHERE roblox_id > 0)")


def _effacer_portrait(rid: int) -> None:
    dossier = tableau.dossier_site("avatars")
    for ext in ("webp", "png"):
        p = dossier / f"{int(rid)}.{ext}"
        if p.is_file():
            p.unlink()


async def _purger_portraits(gid, jours, t):
    ids = [int(r[0]) for r in await _lignes(_PORTRAITS_SEULS, (int(t - jours * JOUR),))]
    n = 0
    for k in range(0, len(ids), LOT):
        lot = ids[k:k + LOT]
        await asyncio.to_thread(lambda: [_effacer_portrait(r) for r in lot])
        n += await _supprimer(f"DELETE FROM rell_avatars WHERE roblox_id IN ({','.join('?' * len(lot))})", tuple(lot))
    return n


async def _apercu_portraits(gid, jours, t):
    return len(await _lignes(_PORTRAITS_SEULS, (int(t - jours * JOUR),)))


async def _compter_portraits(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM rell_avatars")


#  ─── Les membres partis : empreintes de compte, invitations ; l'audit du staff ───────────────────────────────────
async def _empreintes_parties(gid: int, jours: int, t: float) -> list:
    """Les empreintes (détection des doubles comptes) de ceux qui ne sont plus sur le serveur depuis `jours` : la
    détection ne compare qu'aux membres PRÉSENTS — elles ne servent plus. Liste des membres incomplète : aucune."""
    g = tableau._bot.get_guild(int(gid)) if tableau._bot is not None else None
    if g is None or not getattr(g, "chunked", False):
        return []
    presents = {int(m.id) for m in getattr(g, "members", None) or []}
    borne = datetime.fromtimestamp(int(t - jours * JOUR), timezone.utc).strftime("%Y-%m-%d")
    rows = await _lignes("SELECT user_id FROM user_fingerprints WHERE guild_id=? AND substr(COALESCE(updated_at, ''), 1, 10) < ?",
                         (gid, borne))
    return [int(r[0]) for r in rows if int(r[0]) not in presents]


async def _purger_empreintes(gid, jours, t):
    ids, n = await _empreintes_parties(gid, jours, t), 0
    for k in range(0, len(ids), LOT):
        lot = ids[k:k + LOT]
        n += await _supprimer(f"DELETE FROM user_fingerprints WHERE guild_id=? AND user_id IN ({','.join('?' * len(lot))})",
                              (gid, *lot))
    return n


async def _apercu_empreintes(gid, jours, t):
    return len(await _empreintes_parties(gid, jours, t))


async def _compter_empreintes(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM user_fingerprints WHERE guild_id=?", (gid,))


async def _purger_invitations(gid, jours, t):
    return await _supprimer("DELETE FROM invitations_arrivees WHERE guild_id=? AND parti > 0 AND parti < ?",
                            (gid, int(t - jours * JOUR)))


async def _apercu_invitations(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM invitations_arrivees WHERE guild_id=? AND parti > 0 AND parti < ?",
                          (gid, int(t - jours * JOUR)))


async def _purger_audit(gid, jours, t):
    return await _supprimer("DELETE FROM staff_audit_log WHERE guild_id=? AND created_at < ?", (gid, _sqlite(t - jours * JOUR)))


async def _apercu_audit(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM staff_audit_log WHERE guild_id=? AND created_at < ?",
                          (gid, _sqlite(t - jours * JOUR)))


#  ─── Les équipes du clan (27/10/2026) : un membre parti du serveur sort de son équipe ───────────────────────────
#  `equipes` (une ligne par équipe, son chef) et `equipes_membres` (une place par membre, la clé est le membre) : leur
#  taille est bornée (EQUIPES_MAX équipes, une place par membre du clan) — sauf les places de ceux qui partent. Le bot
#  appelle `membre_parti` à chaque départ ; la règle « Équipes : membres partis » rattrape chaque jour ceux partis
#  pendant qu'il était éteint, et les places d'une équipe qui n'existe plus.
async def membre_parti(guild_id: int, membre_id: int, maintenant: float | None = None) -> int:
    """Un membre a quitté le serveur : il sort de son équipe ; s'il en était le chef, l'équipe reste, sans chef (comme
    l'effacement RGPD). Rend le nombre de places libérées (0 ou 1). Avant le branchement du site : rien (le rattrapage
    du jour s'en charge)."""
    if _get_db is None:
        return 0
    return await _liberer(int(guild_id), [int(membre_id)], maintenant or time.time())


async def _liberer(gid: int, ids: list, t: float) -> int:
    """Les places de `ids` libérées ; chaque équipe touchée change de version (une saisie ouverte sur le site le voit)."""
    n = 0
    for k in range(0, len(ids), LOT):
        lot = ids[k:k + LOT]
        marques = ",".join("?" * len(lot))
        touchees = {str(r[0]) for r in await _lignes(
            f"SELECT equipe_id FROM equipes_membres WHERE guild_id=? AND membre_id IN ({marques})"
            f" UNION SELECT id FROM equipes WHERE guild_id=? AND chef_id IN ({marques})", (gid, *lot, gid, *lot))}
        if not touchees:
            continue
        async with _get_db() as db:
            cur = await db.execute(f"DELETE FROM equipes_membres WHERE guild_id=? AND membre_id IN ({marques})", (gid, *lot))
            n += max(cur.rowcount or 0, 0)
            cur = await db.execute(f"UPDATE equipes SET chef_id=0 WHERE guild_id=? AND chef_id IN ({marques})", (gid, *lot))
            n += max(cur.rowcount or 0, 0)
            for eid in sorted(touchees):
                await db.execute("UPDATE equipes SET version=version+1, maj_le=?, maj_par=0 WHERE guild_id=? AND id=?",
                                 (int(t), gid, eid))
            await db.commit()
    return n


async def _equipes_a_liberer(gid: int) -> tuple:
    """(places à retirer — (équipe, membre) : un membre parti, ou une équipe qui n'existe plus —, équipes dont le chef est
    parti). Liste des membres du serveur incomplète : seules les places orphelines (on ne retire jamais quelqu'un qu'on
    n'a pas vu partir)."""
    equipes = {str(i): int(c or 0) for i, c in await _lignes("SELECT id, chef_id FROM equipes WHERE guild_id=?", (gid,))}
    places = [(str(e), int(m)) for e, m in await _lignes("SELECT equipe_id, membre_id FROM equipes_membres WHERE guild_id=?",
                                                          (gid,))]
    g = tableau._bot.get_guild(int(gid)) if tableau._bot is not None else None
    complet = g is not None and bool(getattr(g, "chunked", False))
    presents = {int(m.id) for m in getattr(g, "members", None) or []} if complet else set()

    def parti(uid: int) -> bool:
        return complet and uid not in presents
    return ([(e, m) for e, m in places if e not in equipes or parti(m)],
            sorted(e for e, chef in equipes.items() if chef and parti(chef)))


async def _purger_equipes(gid, jours, t):
    retirer, sans_chef = await _equipes_a_liberer(gid)
    if not retirer and not sans_chef:
        return 0
    n = 0
    async with _get_db() as db:
        for e, m in retirer:
            cur = await db.execute("DELETE FROM equipes_membres WHERE guild_id=? AND equipe_id=? AND membre_id=?", (gid, e, m))
            n += max(cur.rowcount or 0, 0)
        for e in sans_chef:
            cur = await db.execute("UPDATE equipes SET chef_id=0 WHERE guild_id=? AND id=?", (gid, e))
            n += max(cur.rowcount or 0, 0)
        for e in sorted({e for e, _m in retirer} | set(sans_chef)):   # une équipe effacée n'a plus de ligne : rien
            await db.execute("UPDATE equipes SET version=version+1, maj_le=?, maj_par=0 WHERE guild_id=? AND id=?",
                             (int(t), gid, e))
        await db.commit()
    return n


async def _apercu_equipes(gid, jours, t):
    retirer, sans_chef = await _equipes_a_liberer(gid)
    return len(retirer) + len(sans_chef)


async def _compter_equipes(gid, jours, t):
    return (await _compter("SELECT COUNT(*) FROM equipes_membres WHERE guild_id=?", (gid,))
            + await _compter("SELECT COUNT(*) FROM equipes WHERE guild_id=? AND chef_id != 0", (gid,)))


#  ─── Les fichiers orphelins ──────────────────────────────────────────────────────────────────────────────────────
async def _references() -> tuple:
    medias = {str(r[0]) for r in await _lignes("SELECT id FROM tableau_medias")}
    portraits = {int(r[0]) for r in await _lignes("SELECT roblox_id FROM rell_avatars")}
    portraits |= {int(r[0]) for r in await _lignes("SELECT roblox_id FROM rell_affiches WHERE roblox_id > 0")}
    return medias, portraits


def _balayer(medias: set, portraits: set, t: float, effacer: bool) -> dict:
    """Les fichiers sans référence de plus d'ORPHELIN_AGE_S : images du site, portraits, images de transcripts sans leur
    page, restes d'écriture (`.tmp`). Rend {sorte : nombre} — effacés si `effacer`."""
    vieux, out = t - ORPHELIN_AGE_S, {"images": 0, "portraits": 0, "transcripts": 0, "restes": 0}

    def ancien(e) -> bool:
        try:
            return e.stat(follow_symlinks=False).st_mtime < vieux
        except OSError:   # effacé entre la liste et sa lecture : rien à faire
            return False

    def retirer(e, sorte):
        out[sorte] += 1
        if effacer:
            try:
                if e.is_dir(follow_symlinks=False):
                    shutil.rmtree(e.path, ignore_errors=True)
                else:
                    os.remove(e.path)
            except OSError as ex:
                out[sorte] -= 1
                _log("[LONGEVITE][E3] fichier orphelin non effacé")
                _log(f"[LONGEVITE][E3:DETAIL] {e.path} {type(ex).__name__} {ex}")
    for sous, sorte, connus in (("medias", "images", medias), ("avatars", "portraits", portraits)):
        try:
            entrees = list(os.scandir(tableau.dossier_site(sous)))
        except OSError:
            continue
        for e in entrees:
            if not e.is_file(follow_symlinks=False) or not ancien(e):
                continue
            racine, _, ext = e.name.rpartition(".")
            if e.name.endswith(".tmp"):
                retirer(e, "restes")
            elif ext in ("webp", "png") and (int(racine) if sorte == "portraits" and racine.isdigit() else racine) not in connus:
                retirer(e, sorte)
    try:
        entrees = list(os.scandir(transcript_store._BASE_DIR))
    except OSError:
        entrees = []
    for e in entrees:
        if e.name.endswith(".tmp") and ancien(e):
            retirer(e, "restes")
        elif e.name.startswith("a_") and e.is_dir(follow_symlinks=False) and ancien(e) \
                and not os.path.isfile(os.path.join(transcript_store._BASE_DIR, e.name[2:] + ".html")):
            retirer(e, "transcripts")
    return out


async def _orphelins(t: float, effacer: bool) -> int:
    medias, portraits = await _references()
    n = sum((await asyncio.to_thread(_balayer, medias, portraits, t, effacer)).values())
    #  Une image du site dont le fichier a disparu : sa ligne ne compte plus pour rien.
    dossier = tableau.dossier_site("medias")
    perdues = [i for i in medias if tableau.FORMAT_MEDIA.fullmatch(i)
               and not any((dossier / f"{i}.{ext}").is_file() for ext in ("webp", "png"))]
    vieilles = {str(r[0]) for r in await _lignes("SELECT id FROM tableau_medias WHERE cree_le < ?", (int(t - ORPHELIN_AGE_S),))}
    perdues = [i for i in perdues if i in vieilles]
    if effacer:
        for k in range(0, len(perdues), LOT):
            lot = perdues[k:k + LOT]
            await _supprimer(f"DELETE FROM tableau_medias WHERE id IN ({','.join('?' * len(lot))})", tuple(lot))
    #  27/10/2026 : une affiche retirée de la vitrine puis effacée pour de bon laissait son réglage (`equipage_vitrine`).
    sans_affiche = (" FROM equipage_vitrine WHERE NOT EXISTS (SELECT 1 FROM rell_affiches a"
                    " WHERE a.guild_id=equipage_vitrine.guild_id AND a.id=equipage_vitrine.affiche_id)")
    reglages = await (_supprimer("DELETE" + sans_affiche) if effacer else _compter("SELECT COUNT(*)" + sans_affiche))
    return n + len(perdues) + reglages


async def _purger_orphelins(gid, jours, t):
    _orphelins_vus.update(t=0.0, n=None)
    return await _orphelins(t, True)


async def _apercu_orphelins(gid, jours, t):
    """Combien d'orphelins partiraient — le parcours des dossiers (80 ms à 5 ans, des milliers de fichiers) est gardé
    STOCKAGE_FRAIS secondes : la rubrique le redemande à chaque visite ; un nettoyage l'oublie."""
    if _orphelins_vus["n"] is None or abs(t - _orphelins_vus["t"]) > STOCKAGE_FRAIS:
        _orphelins_vus.update(t=t, n=await _orphelins(t, False))
    return _orphelins_vus["n"]


REGLES_NETTOYAGE = [
    {"cle": "tickets_fermes", "nom": "Tickets fermés",
     "quoi": "Un ticket fermé depuis plus longtemps est effacé pour de bon : sa ligne, son suivi, son audit et sa "
             "conversation (celle d'une candidature reste avec sa fiche).",
     "garde_jours": 365, "min": 30, "max": 365, "ordre": 22,
     "fn": _purger_tickets, "apercu": _apercu_tickets, "compter": _compter_tickets},
    {"cle": "questions", "nom": "Questions relevées",
     "quoi": "Les questions relevées dans les salons : effacées après ce délai.",
     "garde_jours": 30, "min": 7, "max": 30, "ordre": 73, "fn": _purger_questions, "apercu": _apercu_questions},
    {"cle": "casier_detections", "nom": "Casier : détections automatiques",
     "quoi": "Insultes, filtre, protection : effacées du casier après ce délai (annulable 30 jours, dans Sanctions). "
             "L'amnistie de 3 mois passe aussi, chaque jour.",
     "garde_jours": 365, "min": 90, "max": 365, "ordre": 40,
     "fn": _detections, "apercu": _apercu_detections, "compter": _compter_detections},
    {"cle": "casier_sanctions", "nom": "Casier : sanctions du staff",
     "quoi": "Avertissements, mutes, expulsions : effacés du casier après ce délai (annulable 30 jours). Les "
             "bannissements restent deux ans.",
     "garde_jours": 730, "min": 365, "max": 730, "ordre": 41,
     "fn": _sanctions, "apercu": _apercu_sanctions, "compter": _compter_sanctions},
    {"cle": "actualites", "nom": "Actualités de l'équipage",
     "quoi": "Les actualités publiées sur le site de l'équipage : effacées après ce délai (jamais les épinglées).",
     "garde_jours": 365, "min": 30, "max": 3650, "ordre": 52, "fn": _purger_actualites, "apercu": _apercu_actualites},
    {"cle": "equipes_partis", "nom": "Équipes : membres partis",
     "quoi": "Un membre parti du serveur sort de son équipe ; un chef parti la laisse sans chef. Fait à son départ, "
             "rattrapé chaque jour.",
     "garde_jours": 0, "min": 0, "max": 0, "ordre": 54, "duree": "tant qu'il est sur le serveur",
     "fn": _purger_equipes, "apercu": _apercu_equipes, "compter": _compter_equipes},
    {"cle": "portraits", "nom": "Portraits Roblox inutilisés",
     "quoi": "Un portrait qu'aucune affiche ne montre (recherche sans suite, affiche effacée) : effacé après ce délai.",
     "garde_jours": 90, "min": 14, "max": 365, "ordre": 62,
     "fn": _purger_portraits, "apercu": _apercu_portraits, "compter": _compter_portraits},
    {"cle": "sondages", "nom": "Sondages",
     "quoi": "Les sondages des membres et leurs résultats : effacés après ce délai.",
     "garde_jours": 90, "min": 30, "max": 90, "ordre": 75, "fn": _purger_sondages, "apercu": _apercu_sondages},
    {"cle": "idees", "nom": "Idées décidées ou retirées",
     "quoi": "Une idée décidée (acceptée, refusée, réalisée) ou retirée du salon, et ses votes : effacée après ce délai.",
     "garde_jours": 365, "min": 60, "max": 730, "ordre": 76, "fn": _purger_idees, "apercu": _apercu_idees},
    {"cle": "entraide", "nom": "Entraide et trade : demandes closes",
     "quoi": "Une demande close est effacée de l'historique après ce délai. Les échanges certifiés restent : ils font "
             "la réputation de chacun.",
     "garde_jours": 365, "min": 30, "max": 730, "ordre": 77,
     "fn": _purger_entraide, "apercu": _apercu_entraide, "compter": _compter_entraide},
    {"cle": "empreintes", "nom": "Comptes partis : empreintes",
     "quoi": "Ce que la détection des doubles comptes garde de ceux qui ont quitté le serveur : effacé après ce délai "
             "(elle ne compare qu'aux membres présents).",
     "garde_jours": 90, "min": 30, "max": 365, "ordre": 70,
     "fn": _purger_empreintes, "apercu": _apercu_empreintes, "compter": _compter_empreintes},
    {"cle": "invitations", "nom": "Invitations des membres partis",
     "quoi": "Qui a invité un membre parti depuis ce délai : effacé (il ne compte plus dans les invitations).",
     "garde_jours": 180, "min": 30, "max": 730, "ordre": 71, "fn": _purger_invitations, "apercu": _apercu_invitations},
    {"cle": "audit_staff", "nom": "Audit des actions du staff",
     "quoi": "Qui a fait quoi, sur qui (sanctions, isolements, notes) : effacé après ce délai.",
     "garde_jours": 365, "min": 90, "max": 730, "ordre": 72, "fn": _purger_audit, "apercu": _apercu_audit},
    {"cle": "orphelins", "nom": "Fichiers orphelins",
     "quoi": "Images, portraits et pièces de conversations que plus rien ne cite, restes d'écriture, réglages de "
             "vitrine d'une affiche effacée : effacés après un jour.",
     "garde_jours": 1, "min": 1, "max": 1, "ordre": 96, "fn": _purger_orphelins, "apercu": _apercu_orphelins},
]


# ═══════════════════════════════════════════════════════════════════════════════
#  L'état du stockage (rubrique « Nettoyage »)
# ═══════════════════════════════════════════════════════════════════════════════

def _taille(chemin) -> tuple:
    n = octets = 0
    for racine, _d, fichiers in os.walk(chemin):
        for f in fichiers:
            try:
                octets += os.path.getsize(os.path.join(racine, f))
                n += 1
            except OSError:   # effacé pendant le parcours (un nettoyage, une écriture) : il ne compte plus
                continue
    return n, octets


def _dossiers_lus() -> dict:
    import db_backup
    out = {}
    for nom, chemin in (("transcripts", transcript_store._BASE_DIR), ("images", tableau.dossier_site("medias")),
                        ("portraits", tableau.dossier_site("avatars"))):
        n, octets = _taille(chemin)
        out[nom] = {"fichiers": n, "octets": octets}
    try:
        copies = [p for p in db_backup._resolve_backup_dir().glob("bot.db.*.bak") if p.is_file()]
        out["copies"] = {"fichiers": len(copies), "octets": sum(p.stat().st_size for p in copies)}
    except OSError as ex:
        _log("[LONGEVITE][E2] dossier des copies illisible")
        _log(f"[LONGEVITE][E2:DETAIL] {type(ex).__name__} {ex}")
        out["copies"] = {"fichiers": 0, "octets": 0}
    return out


async def etat_stockage(guild_id: int) -> dict:
    """La place prise : la base (et ses pages libres, son compactage), les dossiers, les copies, le volume."""
    t = time.time()
    if _dossiers["valeur"] is None or t - _dossiers["t"] > STOCKAGE_FRAIS:
        _dossiers.update(t=t, valeur=await asyncio.to_thread(_dossiers_lus))
    base = await compactage.etat(_get_db)
    total = libre = None
    if _chemin_base:
        try:
            u = shutil.disk_usage(os.path.dirname(os.path.abspath(_chemin_base)) or ".")
            total, libre = int(u.total), int(u.free)
        except OSError as ex:
            _log("[LONGEVITE][E1] volume illisible")
            _log(f"[LONGEVITE][E1:DETAIL] {type(ex).__name__} {ex}")
    return {"base": base["octets"], "libres": base["libres"], "incremental": base["mode"] == compactage.INCREMENTAL,
            "compacte_le": base["dernier"] or base["conversion"] or None, "dossiers": dict(_dossiers["valeur"]),
            "volume": {"total": total, "libre": libre}}
