"""tickets_interdits.py — interdire des tickets à une personne, depuis sa fiche sur le site (27/10/2026).

Le fondateur, mot pour mot : « J'aimerais qu'on ait aussi la possibilité sur l'affiche de chacune des personnes avec les
sanctions en haut, qu'on puisse le blacklist des tickets et qu'on décide de quel type de ticket il n'a pas le droit de
créer. Est-ce que c'est des tickets serveurs ou des tickets du clan ? Comme ça, c'est plus simple pour nous de pouvoir
blacklist les gens plutôt que d'utiliser une commande sur le serveur Discord. » Puis : « ils ne doivent pas recevoir de
messages en privé ou quoi que ce soit… Ils l'apprennent quand ils veulent recréer un ticket. Mais ils ne savent pas de
qui, de quoi, comment. »

UNE SEULE VÉRITÉ
  · Ce que lit le contrôle d'ouverture du bot (`_ticket_ouvrir`, `_create_ticket_corps`) : la liste `blacklist` de
    chaque panneau (`cfg['ticket_panels']`). Le site, `/mod ticketblacklist`, le bouton « Blacklist » d'un ticket,
    /configure et la liste noire du recrutement écrivent tous là.
  · Deux familles, celles du site (Tickets : « Clan · RELL Seas » et « Tickets normaux ») : CLAN = les panneaux du clan
    (`rellseas_panneau.panneaux_tickets` : le choix de /configure, sinon un nom qui parle de Rell Seas — le recrutement),
    SERVEUR = tout le reste. Un nouveau panneau se range de lui-même.
  · La famille CLAN entière passe par la liste noire du recrutement (`questionnaire.mettre_sur_liste_noire`,
    `lever_liste_noire`) : la liste « Liste noire » de Demande de recrutement › Réglages et la fiche disent la même
    chose, et une levée là-bas se lit ici. Un panneau du clan seul (le réglage fin) : sa liste seulement.
  · Qui, depuis quand, pourquoi : l'entrée de la liste noire du recrutement (le clan entier), sinon la table
    `tickets_interdictions` (une ligne par personne et par panneau). Un décor seulement : une ligne dont la personne
    n'est plus dans la liste du panneau ne compte pas, et s'efface à la lecture suivante.

LE SILENCE
  · Rien n'est envoyé à la personne, ni quand on l'interdit, ni quand on lève l'interdiction : aucun message privé, aucune
    mention, aucun avis. Elle l'apprend en touchant un panneau interdit — un avis pour elle seule, GÉNÉRIQUE
    (`tickets.interdit.refus`, sans aucune variable : même réécrit, il ne dit ni qui, ni pourquoi, ni depuis quand).

LE SITE (la fiche d'une personne, `site/tickets_interdits.js`) — la tête seule
  · GET tickets/interdictions?membre=<id> · POST tickets/interdire {membre, version, familles | panneaux, motif?}
    · POST tickets/lever {membre, version, familles | panneaux}. La version lue ne correspond plus : 409 et l'état du
    moment. Le fondateur, la direction, un administrateur, un robot (le bot compris) : jamais interdits (403).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time

import diag
import rellseas_panneau
import textes as textes_du_site

FAMILLES = ("serveur", "clan")
MOTIF_MAX = 150                    # comme la liste noire du recrutement (questionnaire.MOTIF_MAX)
PANNEAUX_MAX = 50                  # un corps ne nomme jamais plus de panneaux
CHIFFRES = re.compile(r"[0-9]{1,20}")
FORMAT_VERSION = re.compile(r"[0-9a-f]{12}")
FORMAT_PANNEAU = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
SOURCES = ("site", "commande", "ticket", "configure", "recrutement")
NOMS = {"serveur": "les tickets du serveur", "clan": "les tickets du clan"}

#  Les textes (Capitainerie → Réglages → Textes & noms). Le refus n'a AUCUNE variable : le code ne lui passe jamais ni
#  qui, ni pourquoi, ni depuis quand — même un texte réécrit sur le site ne peut pas les dire.
GROUPE = "tickets"
CLE_REFUS = "tickets.interdit.refus"
textes_du_site.nommer_groupe(GROUPE, "Les tickets", 35)
REFUS = textes_du_site.declarer(
    CLE_REFUS, "Tu ne peux pas ouvrir ce type de ticket pour le moment.\n-# You can't open this type of ticket right now.",
    groupe=GROUPE, partie="Un panneau interdit", ordre=1, max_=600, titre="Le refus (pour la personne seule)",
    aide="Une personne interdite touche un panneau du serveur : cet avis, pour elle seule. Aucune variable : jamais "
         "qui, pourquoi, ni depuis quand. Les panneaux du clan disent « Refus à l'ouverture » (Recrutement).")
#  Les noms du bloc « Tickets » de la fiche (`site/tickets_interdits.js` les lit par `libelle`).
SITE = (("titre", "Tickets", "Le titre du bloc, sous les sanctions de la fiche."),
        ("serveur", "Tickets du serveur", "La ligne des panneaux du serveur (tout sauf le clan)."),
        ("clan", "Tickets du clan", "La ligne des panneaux du clan (RELL Seas, le recrutement)."),
        ("interdire", "Interdire", "Le bouton d'une ligne autorisée."),
        ("lever", "Lever l'interdiction", "Le bouton d'une ligne interdite."),
        ("deux", "Interdire les deux", "Le bouton du haut : le serveur et le clan d'un coup."),
        ("panneaux", "Panneau par panneau", "Le réglage fin : chaque panneau de tickets, un par un."))
for _k, (_cle, _defaut, _aide) in enumerate(SITE):
    textes_du_site.declarer(f"site.fiche.tickets.{_cle}", _defaut, groupe="site", partie="La fiche d'une personne",
                            ordre=460 + _k, titre=f"Tickets · « {_defaut} »", aide=_aide, max_=40, lignes=False)

_get_db = _cfg = _db_set = _exempte = _robot = None
_tete: frozenset = frozenset()
_verrous: dict = {}                # boucle → (boucle, verrou) : un verrou né dans une autre boucle y lèverait une erreur
_log = print


class _Invalide(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def setup(*, get_db, cfg, db_set, tete=(), exempte=None, robot=None, log=None) -> None:
    """`cfg(guild_id)` / `db_set(guild_id, cle, valeur)` : la configuration du bot ; `tete` : TETE_IDS ;
    `exempte(g, membre, c)` → vrai si les tickets n'ont aucune limite pour ce membre (bot.py `_ticket_sans_limite` :
    une interdiction ne s'appliquerait pas) ; `robot()` → l'identifiant du bot."""
    global _get_db, _cfg, _db_set, _tete, _exempte, _robot, _log
    _get_db, _cfg, _db_set, _exempte, _robot = get_db, cfg, db_set, exempte, robot
    _tete = frozenset(int(x) for x in tete or ())
    _log = log or print
    _verrous.clear()


def pret() -> bool:
    return _get_db is not None and _cfg is not None


async def init_db() -> None:
    async with _get_db() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS tickets_interdictions (guild_id INTEGER NOT NULL,"
                         " membre_id INTEGER NOT NULL, panneau TEXT NOT NULL, depuis INTEGER NOT NULL DEFAULT 0,"
                         " par INTEGER NOT NULL DEFAULT 0, motif TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',"
                         " PRIMARY KEY (guild_id, membre_id, panneau))")
        await db.commit()


def _signaler(code: str, message: str, detail: str = "", ex=None) -> None:
    """Un message STABLE (le tableau des erreurs ne sature pas), le détail sur une ligne à part."""
    _log(f"[TICKETS][{code}] {message}")
    _log(f"[TICKETS][{code}:DETAIL] {detail} {type(ex).__name__ + ' ' + str(ex) if ex is not None else ''}".rstrip())
    if ex is not None:
        diag.compter("tickets_interdits", code, ex)


def _verrou() -> asyncio.Lock:
    boucle = asyncio.get_running_loop()
    v = _verrous.get(id(boucle))
    if v is None or v[0] is not boucle:
        v = _verrous[id(boucle)] = (boucle, asyncio.Lock())
    return v[1]


def _questionnaire():
    """Le recrutement (la liste noire du clan), s'il est branché — sinon None : les listes des panneaux seules."""
    try:
        import questionnaire
    except Exception as ex:  # le module manque : la famille du clan s'écrit dans les listes, et le journal le dit
        _signaler("E1", "recrutement absent : listes des panneaux seules", "", ex)
        return None
    return questionnaire if questionnaire.pret() else None


# ═══════════════════════════════════════════════════════════════════════════════
#  Les panneaux et leurs familles
# ═══════════════════════════════════════════════════════════════════════════════

def famille(c: dict, pid) -> str:
    """« clan » ou « serveur » : la classification du site (Tickets › Clan · RELL Seas), un nouveau panneau compris."""
    return "clan" if str(pid) in rellseas_panneau.panneaux_tickets(c or {}) else "serveur"


def panneaux(c: dict) -> list:
    """Les panneaux de tickets, dans l'ordre de la configuration : {id, nom, famille, ferme}."""
    clan = rellseas_panneau.panneaux_tickets(c or {})
    out = []
    for pid, p in ((c or {}).get("ticket_panels") or {}).items():
        if isinstance(p, dict):
            out.append({"id": str(pid), "nom": str(p.get("name") or pid)[:80],
                        "famille": "clan" if str(pid) in clan else "serveur", "ferme": bool(p.get("disabled"))})
    return out


def _liste(pnl) -> list:
    """La liste noire d'un panneau, en identifiants (des chiffres 0-9 seulement)."""
    brut = pnl.get("blacklist") if isinstance(pnl, dict) else None
    return [int(str(x)) for x in (brut if isinstance(brut, list) else []) if CHIFFRES.fullmatch(str(x))]


def _membre(v) -> int | None:
    """Un identifiant venu du client : des chiffres 0-9 (« ² » ou « ５ » refusés), jamais 0."""
    if isinstance(v, bool):
        return None
    s = str(v) if isinstance(v, (int, str)) else ""
    return int(s) if CHIFFRES.fullmatch(s) and int(s) > 0 else None


# ═══════════════════════════════════════════════════════════════════════════════
#  Lire : l'état d'une personne
# ═══════════════════════════════════════════════════════════════════════════════

def _qui(g, uid) -> dict | None:
    if not uid:
        return None
    m = g.get_member(int(uid)) if g is not None else None
    return {"id": str(uid), "nom": getattr(m, "display_name", "") or "Membre parti"}


async def protection(g, uid: int, c: dict | None = None) -> str:
    """La raison pour laquelle cette personne n'est JAMAIS interdite de tickets — sinon « ». Des refus stables."""
    if int(uid) in _tete:
        return "Le fondateur et la direction ne sont jamais interdits de tickets."
    robot = 0
    try:
        robot = int(_robot() or 0) if _robot is not None else 0
    except Exception as ex:  # l'identifiant du bot illisible : les robots restent protégés par `bot`
        _signaler("E2", "identifiant du bot illisible", "", ex)
    m = g.get_member(int(uid)) if g is not None else None
    if int(uid) == robot or getattr(m, "bot", False):
        return "Un robot n'ouvre pas de ticket : rien à interdire."
    if m is None:
        return ""
    if int(uid) == int(getattr(g, "owner_id", 0) or 0) or getattr(getattr(m, "guild_permissions", None),
                                                                 "administrator", False):
        return "Un administrateur n'est jamais interdit de tickets."
    if _exempte is not None:
        try:
            if _exempte(g, m, c if c is not None else await _cfg(g.id)):
                return "La direction ouvre ses tickets sans aucune limite : rien à interdire."
        except Exception as ex:  # la règle du bot illisible : on n'invente pas d'exemption
            _signaler("E3", "exemption de tickets illisible", "", ex)
    return ""


async def _recrutement(g, uid: int) -> dict | None:
    """Son entrée ACTIVE de la liste noire du recrutement (le clan entier) — ou None."""
    q = _questionnaire()
    if q is None:
        return None
    return await q.entree_liste_noire(g.id, int(uid))


async def _metas(guild_id: int, uid: int) -> dict:
    async with _get_db() as db:
        async with db.execute("SELECT panneau, depuis, par, motif, source FROM tickets_interdictions WHERE guild_id=? AND"
                              " membre_id=?", (int(guild_id), int(uid))) as cur:
            rows = await cur.fetchall()
    return {str(p): {"depuis": int(d or 0), "par": int(par or 0), "motif": str(m or ""), "source": str(s or "")}
            for p, d, par, m, s in rows}


async def _oublier(guild_id: int, uid: int, pids) -> None:
    pids = [str(p) for p in pids]
    if not pids:
        return
    async with _get_db() as db:
        await db.execute(f"DELETE FROM tickets_interdictions WHERE guild_id=? AND membre_id=? AND panneau IN"
                         f" ({','.join('?' * len(pids))})", (int(guild_id), int(uid), *pids))
        await db.commit()


async def _retenir(guild_id: int, uid: int, pids, *, depuis: int, par: int, motif: str, source: str) -> None:
    pids = [str(p) for p in pids]
    if not pids:
        return
    async with _get_db() as db:
        await db.executemany("INSERT OR REPLACE INTO tickets_interdictions (guild_id, membre_id, panneau, depuis, par,"
                             " motif, source) VALUES (?,?,?,?,?,?,?)",
                             [(int(guild_id), int(uid), p, int(depuis), int(par or 0), str(motif or "")[:MOTIF_MAX],
                               source if source in SOURCES else "") for p in pids])
        await db.commit()


def _decor(g, meta: dict | None) -> dict:
    """Depuis quand, par qui, pourquoi — pour la page (la tête seule)."""
    if not meta:
        return {"depuis": 0, "par": None, "motif": "", "source": ""}
    return {"depuis": int(meta.get("depuis") or 0), "par": _qui(g, meta.get("par")), "motif": str(meta.get("motif") or ""),
            "source": str(meta.get("source") or "")}


def _version(lignes: list, rec: dict | None) -> str:
    """L'empreinte de ce qui lui est interdit : une écriture qui l'a lue autrement est refusée (409)."""
    brut = json.dumps([sorted(x["id"] for x in lignes if x["interdit"]), int((rec or {}).get("id") or 0)])
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:12]


async def _lire_etat(g, uid: int, c: dict) -> tuple:
    """(lignes des panneaux, entrée du recrutement) — ce qui est interdit, panneau par panneau, avec son décor."""
    ps = panneaux(c)
    listes = {pid: _liste(p) for pid, p in ((c.get("ticket_panels") or {}).items()) if isinstance(p, dict)}
    rec = await _recrutement(g, uid)
    metas = await _metas(g.id, uid)
    lignes = []
    for p in ps:
        par_rec = p["famille"] == "clan" and rec is not None
        interdit = par_rec or int(uid) in listes.get(p["id"], [])
        meta = None
        if par_rec:
            meta = {"depuis": rec["depuis"], "par": rec["par"], "motif": rec["motif"], "source": "recrutement"}
        elif interdit:
            meta = metas.get(p["id"])
        lignes.append(dict(p, interdit=bool(interdit), **_decor(g, meta)))
    perimees = [pid for pid in metas if not any(x["id"] == pid and x["interdit"] for x in lignes)]
    if perimees:   # la personne n'est plus dans la liste du panneau (levée ailleurs) : le décor part
        await _oublier(g.id, uid, perimees)
    return lignes, rec


def _resume(lignes: list) -> dict:
    """Une famille : « aucun » (pas de panneau), « autorise », « interdit », ou « partiel » ; le décor le plus récent."""
    n, interdits = len(lignes), [x for x in lignes if x["interdit"]]
    etat = "aucun" if not n else "autorise" if not interdits else "interdit" if len(interdits) == n else "partiel"
    dernier = max(interdits, key=lambda x: x["depuis"], default=None)
    decor = {k: dernier[k] for k in ("depuis", "par", "motif", "source")} if dernier else _decor(None, None)
    return dict(decor, etat=etat, panneaux=n, interdits=len(interdits),
                noms=[x["nom"] for x in interdits][:10])


async def etat(g, uid: int) -> dict:
    """Ce qui lui est interdit : les deux familles (résumé), chaque panneau, la protection, la version."""
    c = await _cfg(g.id)
    lignes, rec = await _lire_etat(g, int(uid), c)
    return {"membre": str(int(uid)), "protege": await protection(g, int(uid), c),
            "familles": {f: _resume([x for x in lignes if x["famille"] == f]) for f in FAMILLES},
            "panneaux": lignes, "version": _version(lignes, rec)}


# ═══════════════════════════════════════════════════════════════════════════════
#  Écrire : l'état voulu, appliqué aux listes que lit le bot
# ═══════════════════════════════════════════════════════════════════════════════

async def _ecrire_listes(g, uid: int, voulu: set) -> bool:
    """Chaque liste des panneaux : la personne dedans si son panneau est dans `voulu`, dehors sinon. Une seule écriture
    de la configuration ; False si elle a échoué (le bot dit son échec par un faux)."""
    c = await _cfg(g.id)
    panels = c.get("ticket_panels") or {}
    change = False
    for pid, pnl in panels.items():
        if not isinstance(pnl, dict):
            continue
        avant = _liste(pnl)
        dedans = int(uid) in avant
        if str(pid) in voulu and not dedans:
            pnl["blacklist"] = avant + [int(uid)]
            change = True
        elif str(pid) not in voulu and dedans:
            pnl["blacklist"] = [x for x in avant if x != int(uid)]
            change = True
    if not change:
        return True
    return (await _db_set(g.id, "ticket_panels", panels)) is not False


async def _appliquer(g, auteur, uid: int, voulu: set, *, motif: str = "", source: str = "site") -> bool:
    """L'état voulu (`voulu` : les panneaux interdits, tous) appliqué. Le clan ENTIER : la liste noire du recrutement
    (qui écrit aussi les listes de ses panneaux) ; une partie du clan seulement : ses listes, l'entrée du recrutement
    levée d'abord. Le serveur : ses listes. Le décor suit (nouveaux interdits : maintenant, par l'auteur, le motif).
    Rien n'est envoyé à la personne. Rend False si une écriture a échoué."""
    c = await _cfg(g.id)
    ps = panneaux(c)
    tous = {p["id"] for p in ps}
    clan = {p["id"] for p in ps if p["famille"] == "clan"}
    voulu = {str(p) for p in voulu} & tous
    avant_lignes, rec = await _lire_etat(g, uid, c)
    avant = {x["id"] for x in avant_lignes if x["interdit"]}
    q = _questionnaire()
    par = int(getattr(auteur, "id", 0) or 0)
    t = int(time.time())
    ok = True
    garder_rec = None
    if clan and q is not None:
        if clan <= voulu and rec is None:
            await q.mettre_sur_liste_noire(g, int(uid), motif=motif, par=par)
        elif not clan <= voulu and rec is not None:
            #  Une partie du clan seulement : l'entrée du recrutement est levée (elle interdit tout le clan), les panneaux
            #  du clan qui restent interdits gardent son décor.
            garder_rec = rec
            st, _rep = await q.lever_liste_noire(g, auteur, {"membre": str(int(uid))})
            ok = ok and st == 200
    ok = await _ecrire_listes(g, uid, voulu) and ok
    #  Le décor : les panneaux nouvellement interdits (le clan entier, lui, est décrit par le recrutement).
    entier = bool(clan) and clan <= voulu and q is not None
    nouveaux = {p for p in voulu - avant if not (entier and p in clan)}
    leves = (avant - voulu) | ({p for p in clan} if entier else set())
    await _oublier(g.id, uid, leves)
    await _retenir(g.id, uid, nouveaux, depuis=t, par=par, motif=motif, source=source)
    if garder_rec is not None:
        await _retenir(g.id, uid, (clan & voulu) - nouveaux, depuis=garder_rec["depuis"], par=garder_rec["par"],
                       motif=garder_rec["motif"], source="recrutement")
    if not ok:
        _signaler("E4", "interdiction de tickets écrite à moitié", f"serveur={g.id} membre={uid}")
    return ok


def _cibles(c: dict, familles=(), pids=()) -> set:
    """Les panneaux visés : ceux des familles nommées, et les panneaux nommés."""
    out = {p["id"] for p in panneaux(c) if p["famille"] in set(familles)}
    connus = {p["id"] for p in panneaux(c)}
    return out | {str(p) for p in pids if str(p) in connus}


async def _modifier(g, auteur, uid: int, cibles: set, *, ajouter: bool, motif: str = "", source: str = "site") -> bool:
    """Les panneaux `cibles` interdits (`ajouter`) ou rouverts ; les autres interdictions restent. L'appelant tient le
    verrou."""
    c = await _cfg(g.id)
    lignes, _rec = await _lire_etat(g, uid, c)
    actuel = {x["id"] for x in lignes if x["interdit"]}
    voulu = (actuel | cibles) if ajouter else (actuel - cibles)
    return await _appliquer(g, auteur, uid, voulu, motif=motif, source=source)


async def interdire(g, auteur, uid: int, *, familles=(), panneaux_=(), motif: str = "", source: str = "site") -> dict:
    """Interdire des familles ou des panneaux (les autres interdictions restent). Rend l'état d'après (+ « ok »)."""
    async with _verrou():
        cibles = _cibles(await _cfg(g.id), familles, panneaux_)
        ok = await _modifier(g, auteur, int(uid), cibles, ajouter=True, motif=_net(motif)[:MOTIF_MAX], source=source)
    return dict(await etat(g, uid), ok=ok)


async def lever(g, auteur, uid: int, *, familles=(), panneaux_=(), source: str = "site") -> dict:
    """Lever l'interdiction de familles ou de panneaux (les autres restent). Rend l'état d'après (+ « ok »)."""
    async with _verrou():
        cibles = _cibles(await _cfg(g.id), familles, panneaux_)
        ok = await _modifier(g, auteur, int(uid), cibles, ajouter=False, source=source)
    return dict(await etat(g, uid), ok=ok)


# ═══════════════════════════════════════════════════════════════════════════════
#  Les autres portes (bot.py) : `/mod ticketblacklist`, le bouton « Blacklist » d'un ticket
# ═══════════════════════════════════════════════════════════════════════════════
#  Elles écrivent la liste du panneau elles-mêmes, puis appellent ici : le décor (qui, depuis quand) ; et, pour une
#  levée sur un panneau du clan, l'entrée du recrutement (elle interdit tout le clan, sinon la levée ne servirait à rien).
#  Ne lèvent jamais : la commande est faite, son journal aussi.

async def noter(g, uid: int, pids, *, par: int = 0, motif: str = "", source: str = "") -> bool:
    """Une interdiction posée ailleurs (la liste déjà écrite) : son décor."""
    if not pret():
        return False
    try:
        await _retenir(g.id, int(uid), pids, depuis=int(time.time()), par=par, motif=_net(motif)[:MOTIF_MAX],
                       source=source)
        return True
    except Exception as ex:  # le décor manque (la fiche dira « sans date ») ; l'interdiction, elle, est faite
        _signaler("E5", "décor d'une interdiction non écrit", f"serveur={getattr(g, 'id', 0)}", ex)
        return False


async def apres_levee(g, auteur, uid: int, pids, source: str = "commande") -> bool:
    """Une interdiction levée ailleurs (la liste déjà écrite) : le décor part ; sur un panneau du clan, l'entrée du
    recrutement aussi (les autres panneaux du clan restent interdits)."""
    if not pret():
        return False
    try:
        await lever(g, auteur, int(uid), panneaux_=[str(p) for p in pids], source=source)
        return True
    except Exception as ex:  # la levée est faite sur ce panneau ; le reste est dit au journal du bot
        _signaler("E6", "levée d'une interdiction non suivie", f"serveur={getattr(g, 'id', 0)}", ex)
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Les adresses du site (`tableau.monter(tickets_interdits)`) — la tête seule
# ═══════════════════════════════════════════════════════════════════════════════

def _net(texte) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(texte or ""))).strip()


def _corps(corps, *, motif: bool) -> tuple:
    """(membre, familles, panneaux, motif, version) d'un corps d'écriture — ou _Invalide."""
    if not isinstance(corps, dict):
        raise _Invalide("Corps attendu : un objet JSON.")
    uid = _membre(corps.get("membre"))
    if uid is None:
        raise _Invalide("« membre » : un identifiant (des chiffres) est attendu.")
    familles, pids = corps.get("familles", []), corps.get("panneaux", [])
    if not isinstance(familles, list) or any(f not in FAMILLES for f in familles):
        raise _Invalide("« familles » : « serveur », « clan », ou les deux.")
    if not isinstance(pids, list) or len(pids) > PANNEAUX_MAX \
            or any(not isinstance(p, str) or not FORMAT_PANNEAU.fullmatch(p) for p in pids):
        raise _Invalide("« panneaux » : une liste de panneaux de tickets.")
    if not familles and not pids:
        raise _Invalide("Choisis les tickets : du serveur, du clan, ou un panneau.")
    texte = corps.get("motif", "")
    if not isinstance(texte, str):
        raise _Invalide("« motif » : un texte est attendu.")
    texte = _net(texte) if motif else ""
    if len(texte) > MOTIF_MAX:
        raise _Invalide(f"Motif : {MOTIF_MAX} caractères au plus.")
    version = corps.get("version")
    if not isinstance(version, str) or not FORMAT_VERSION.fullmatch(version):
        raise _Invalide("« version » : la version lue est demandée.")
    return uid, list(dict.fromkeys(familles)), list(dict.fromkeys(pids)), texte, version


def _quoi(c: dict, familles: list, pids: list) -> str:
    """« tickets du serveur », « tickets du serveur et du clan », « tickets « Support » »…"""
    if familles:
        return "tickets du serveur et du clan" if len(familles) == 2 else NOMS[familles[0]].replace("les ", "", 1)
    noms = {p["id"]: p["nom"] for p in panneaux(c)}
    return "tickets " + ", ".join(f"« {noms[p]} »" for p in pids[:5] if p in noms)


async def _ecrire(g, auteur, corps, *, interdire_: bool) -> tuple:
    """Une écriture du site : la tête seule, un corps vérifié, jamais le fondateur ni la direction, et la version lue —
    vérifiée sous le verrou, avec l'écriture."""
    if not pret():
        return 503, {"erreur": "Les interdictions démarrent : réessaie dans un instant."}
    if auteur is None or int(getattr(auteur, "id", 0) or 0) not in _tete:
        return 403, {"erreur": "Réservé au fondateur et à la direction."}
    try:
        uid, familles, pids, motif, version = _corps(corps, motif=interdire_)
    except _Invalide as ex:
        return ex.status, {"erreur": ex.message}
    c = await _cfg(g.id)
    if any(p not in {x["id"] for x in panneaux(c)} for p in pids):
        return 404, {"erreur": "Ce panneau de tickets n'existe plus."}
    raison = await protection(g, uid, c)
    if raison:
        return 403, {"erreur": raison}
    cibles = _cibles(c, familles, pids)
    if not cibles:
        return 404, {"erreur": "Aucun panneau de tickets ici."}
    nom = (_qui(g, uid) or {}).get("nom", "Membre parti")
    quoi = _quoi(c, familles, pids)
    async with _verrou():
        lu = await etat(g, uid)
        if version != lu["version"]:
            return 409, {"conflit": True, "erreur": "Ses tickets ont changé entre-temps : la fiche est relue.", "etat": lu}
        interdits = {x["id"] for x in lu["panneaux"] if x["interdit"]}
        if (cibles <= interdits) if interdire_ else not (cibles & interdits):
            return 200, {"ok": True, "deja": True, "etat": lu, "_journal": None,
                         "message": "Déjà interdit." if interdire_ else "Déjà autorisé."}
        ok = await _modifier(g, auteur, uid, cibles, ajouter=interdire_, motif=motif)
    apres = await etat(g, uid)
    if interdire_:
        message = f"{nom} ne peut plus ouvrir de {quoi}. Il n'est pas prévenu."
        journal = f"{quoi[0].upper()}{quoi[1:]} interdits à {nom}" + (f" — {motif}" if motif else "")
    else:
        message = f"{nom} peut de nouveau ouvrir des {quoi}."
        journal = f"{quoi[0].upper()}{quoi[1:]} de nouveau ouverts à {nom}"
    if not ok:
        message += " Une partie n'a pas pu être enregistrée : relis sa fiche."
    return 200, {"ok": ok, "message": message, "etat": apres,
                 "_journal": {"texte": journal, "membre_id": uid, "detail": motif}}


async def _r_etat(g, auteur, requete, corps):
    if not pret():
        return 503, {"erreur": "Les interdictions démarrent : réessaie dans un instant."}
    uid = _membre((requete or {}).get("membre"))
    if uid is None:
        return 400, {"erreur": "« membre » : un identifiant (des chiffres) est attendu."}
    return 200, await etat(g, uid)


async def _r_interdire(g, auteur, requete, corps):
    return await _ecrire(g, auteur, corps, interdire_=True)


async def _r_lever(g, auteur, requete, corps):
    return await _ecrire(g, auteur, corps, interdire_=False)


def _verrou_membre(corps) -> str | None:
    """Présence en direct : les interdictions d'une personne, une écriture à la fois."""
    uid = _membre((corps or {}).get("membre"))
    return f"interdictions:{uid}" if uid is not None else None


ROUTES_SITE = {
    "tickets/interdictions": {"methode": "GET", "fn": _r_etat, "corps_max": 0},
    #  Une interdiction change tout de suite ce que le bot laisse ouvrir : jamais rejouée hors ligne.
    "tickets/interdire": {"methode": "POST", "fn": _r_interdire, "ecriture": True, "corps_max": 4096,
                          "verrou": _verrou_membre},
    "tickets/lever": {"methode": "POST", "fn": _r_lever, "ecriture": True, "corps_max": 4096,
                      "verrou": _verrou_membre},
}
