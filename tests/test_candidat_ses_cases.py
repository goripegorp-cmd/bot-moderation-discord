"""Le contrôle de sécurité du fondateur sur la page du candidat (27/10/2026) : « un candidat ou un futur chef ne touche
QUE ses propres cases, et rien d'autre du site ».

Sur le VRAI site local (le serveur du bot, ses modules, un faux Discord : le socle de tests/test_candidature_site.py),
un test par cas demandé. Chaque refus est vérifié EN BASE : rien d'écrit ailleurs que dans SES cases.

K1  un autre envoi, un autre ticket : jamais atteints (paramètres, champs du corps, liens forgés) — sa session reste
    liée à SON envoi ; celle d'un futur chef (du clan) n'ouvre pas le site de l'équipage.
K2  un numéro d'étape forgé : refusé à l'envoi, sans effet ailleurs (le repère de la page) — jamais une erreur 500.
K3  une étape non ouverte, ou déjà envoyée : refusée, rien de réécrit.
K4  un double envoi — l'un après l'autre, ET en même temps (deux onglets, un double clic) : un seul passe, rien de
    réécrit par le second.
K5  des champs inconnus ou modifiés à la main : ignorés ou refusés (400 / 409) avec un message stable — jamais 500.
K6  un corps trop gros, un JSON illisible : 413 / 400, rien d'écrit.
K7  une réponse en HTML ou en script : gardée telle quelle (du texte), servie en JSON, affichée en texte partout — le
    dossier de la direction, le direct, sa page — et jamais envoyée à Discord.
K8  un lien réutilisé, expiré, abîmé, d'une autre portée, d'un envoi remplacé ; une session expirée : refusés.
K9  une session après la fermeture du ticket : plus rien à lire, plus rien à écrire.
K10 un futur chef qui perd le rôle du clan : plus rien, tout de suite.
K11 `api/direct/candidat` et la WebSocket du direct, interrogés par « equipage » ou « candidat » : 403.
(Ses écritures d'une autre origine : tests/test_acces_site.py, A6 ; chaque adresse du serveur : A2 et C1.)
"""
from __future__ import annotations

import asyncio
import json
import re
import time

import aiohttp
import pytest

import test_candidature_site as _socle
from test_candidature_site import FONDATEUR, ORIGINE, RACINE, _empreinte_base, _envoi_chef, _texte

local = _socle.local              # le même site local que tests/test_candidature_site.py (une instance pour ce fichier)
sans_cadence = _socle.sans_cadence

#  Les messages d'erreur que la page du candidat peut lire (stables : jamais le texte d'une exception Python).
MESSAGES = {"Cette question n'est pas ouverte.", "Cette étape n'est pas ouverte.", "Présence invalide.",
            "« reponses » : un objet {rang: texte}.", "Une réponse vise une question qui n'est pas ouverte.",
            "Chaque réponse est un texte.", "Ce questionnaire s'envoie étape par étape.", "Ce questionnaire s'envoie en une fois.",
            "Tes réponses sont déjà envoyées.", "Cette étape est déjà envoyée : la direction la regarde.",
            "Ce questionnaire a été remplacé.", "Ta candidature est terminée.", "Ce questionnaire n'existe plus.",
            "Corps illisible.", "Trop volumineux.", "Requête refusée.", "Adresse inconnue."}
#  Des réponses piégées : du HTML, du script, des mentions — elles doivent rester du TEXTE partout.
PIEGES = ("<script>window.__piege=1</script>", "<img src=x onerror=window.__piege=2>", "\"><svg onload=window.__piege=3>",
          "javascript:window.__piege=4", "</textarea><b>gras ?</b>", "{{constructor.constructor('window.__piege=5')()}}",
          "@everyone @here <@&1> <@781205382923288593>")


@pytest.fixture(autouse=True)
def _memoire_propre():
    """Les mémoires du module (contextes, liaisons, direct, cadences) sont indexées par numéro d'envoi : un autre fichier
    de tests (une autre base) a pu laisser les siennes sous les mêmes numéros."""
    import candidature_site
    import tableau
    for d in (candidature_site._contextes, candidature_site._liaisons, candidature_site._direct, candidature_site._seaux):
        d.clear()
    tableau._essais.clear()
    yield
    tableau._essais.clear()


def _lignes(local, sql, *args) -> list:
    return [tuple(x) for x in local.sql(sql, args)]


def _etat_envoi(local, eid) -> tuple:
    """Les portes et le statut d'un envoi, ses réponses gardées et ses brouillons : tout ce qu'un refus ne doit pas toucher."""
    return (_lignes(local, "SELECT statut, etape_ouverte, etape_envoyee, repondu_le FROM recrutement_envois WHERE id=?", eid),
            _lignes(local, "SELECT rang, texte FROM recrutement_reponses WHERE envoi_id=? ORDER BY rang", eid),
            _lignes(local, "SELECT rang, texte FROM candidature_brouillons WHERE envoi_id=? ORDER BY rang", eid))


def _rangs(d) -> list:
    return [q["rang"] for x in d["etapes"] for q in x["questions"]]


def _empreinte_calme(local) -> dict:
    """L'empreinte de la base (`_empreinte_base`), prise une fois les tâches de fond des tests d'avant finies."""
    avant = _empreinte_base(local)
    for _ in range(10):
        local.faire(asyncio.sleep(0.3))
        maintenant = _empreinte_base(local)
        if maintenant == avant:
            break
        avant = maintenant
    return avant


def _post_brut(local, h, nom, data, entetes=None):
    async def f():
        r = await local.client.post(f"/tableau/candidature/api/{nom}", data=data,
                                    headers=dict(h, **ORIGINE, **{"Content-Type": "application/json"}, **(entetes or {})))
        return r.status, await r.read()
    return local.faire(f())


def _stable(st, rep) -> None:
    """Jamais 500, et un refus parle avec un message de la page (jamais le texte d'une exception)."""
    assert st != 500, f"erreur 500 : {rep}"
    if st >= 400 and isinstance(rep, dict):
        assert rep.get("erreur") in MESSAGES or rep.get("manquent"), f"message instable : {rep.get('erreur')!r}"


# ═══════════════════════════════════════════════════════════════════════════════
#  K1 — un autre envoi, un autre ticket
# ═══════════════════════════════════════════════════════════════════════════════

def test_K1_jamais_l_envoi_ni_le_ticket_d_un_autre(local, sans_cadence):
    import tableau
    ta, ea = local.ticket(1005)
    tb, eb = local.ticket(1008)
    ha, hb = local.candidat(f"ticket={ta}"), local.candidat(f"ticket={tb}")
    st, db_ = local.lire("questionnaire", hb)
    rang = db_["etapes"][0]["questions"][0]["rang"]
    assert local.ecrire("brouillon", {"reponses": {str(rang): "à B"}}, hb)[0] == 200
    avant_b = _etat_envoi(local, eb)
    #  A vise B par tous les moyens : les paramètres de sa lecture, les champs de ses écritures.
    autres = {"envoi": eb, "envoi_id": eb, "ticket": tb, "ticket_id": tb, "candidat": 1008, "candidat_id": 1008,
              "guild": 2, "guild_id": 2, "id": eb, "membre": 1008}
    st, da = local.lire("questionnaire", ha, params={k: str(v) for k, v in autres.items()})
    assert st == 200 and da["envoi"] == ea and rang in _rangs(da), "les mêmes rangs : seule la liaison décide"
    for nom, corps in (("saisie", {"rang": rang, "texte": "vers B ?", "etape": 1}),
                       ("brouillon", {"reponses": {str(rang): "vers B ?"}}), ("presence", {"vue": "ouverte"})):
        st, rep = local.ecrire(nom, dict(corps, **autres), ha)
        assert st == 200, (nom, st, rep)
    tous = {str(r): f"A {r}" for r in _rangs(da)}
    st, rep = local.ecrire("envoyer", {"reponses": tous, **autres}, ha)
    assert st == 200 and rep["etat"] == "envoye", rep
    local.annonces()
    #  B : rien n'a bougé — ni son envoi, ni ses brouillons, ni ses réponses, ni son direct.
    assert _etat_envoi(local, eb) == avant_b
    assert local.lire("questionnaire", hb)[1]["reponses"] == {str(rang): "à B"}
    st, dd = local.api("direct/candidat", local.tete, {"envoi": str(eb)})
    assert st == 200 and dd["reponses"] == {str(rang): "à B"}, dd["reponses"]
    #  A : tout est chez lui, à son nom.
    assert _lignes(local, "SELECT DISTINCT envoi_id, candidat_id FROM recrutement_reponses WHERE envoi_id IN (?, ?)", ea, eb)         == [(ea, 1005)]
    assert not _lignes(local, "SELECT 1 FROM candidature_brouillons WHERE texte='vers B ?'"), "les brouillons envoyés partent"
    #  Un lien bien signé à SON nom mais portant l'envoi de B, ou au nom de B avec son envoi à lui : refusés à l'entrée.
    for jeton in (tableau.jeton(1, 1005, "candidat", nonce=f"e{eb}x" + "Z" * 12),
                  tableau.jeton(1, 1008, "candidat", nonce=f"e{ea}x" + "Y" * 12)):
        h_, (st, page) = local.entrer("/tableau/candidature/" + jeton)
        assert h_ is None and st == 403 and "Rackham" not in page
    #  Un futur chef (du clan) : sa session « candidat » n'ouvre ni le site de l'équipage, ni ses lectures, ni la
    #  Capitainerie — avec son cookie, ou recopié dans celui de la direction.
    eid = _envoi_chef(local, 1006)
    hc, _a = local.entrer("/tableau/candidature/" + tableau.jeton(1, 1006, "candidat", nonce=f"e{eid}x" + "C" * 12))
    assert hc is not None and local.lire("questionnaire", hc)[1]["nature"] == "chef"
    sid = hc["Cookie"].split("=", 1)[1]
    for h in (hc, {"Cookie": f"{tableau.COOKIE}={sid}"}):
        for chemin in ("/tableau/equipage/", "/tableau/equipage/api/equipage", "/tableau/equipage/api/accueil",
                       "/tableau/espace/", "/tableau/espace/donnees", "/tableau/espace/api/equipage/equipes"):
            assert local.requete("GET", chemin, h)[0] == 403, chemin


# ═══════════════════════════════════════════════════════════════════════════════
#  K2 — un numéro d'étape forgé
# ═══════════════════════════════════════════════════════════════════════════════

FORGES = (2, 3, 0, -1, 99, 10 ** 12, "2", "²", "①", "١", "１", " 1", "1 ", "+1", "1.0", 1.0, "deux", True, False, None,
          [1], {"numero": 1}, "")


def test_K2_un_numero_d_etape_force(local, sans_cadence):
    tid, eid = local.ticket(1011, etapes=3, ouverte=1, fiche=1)
    h = local.candidat(f"ticket={tid}")
    st, d = local.lire("questionnaire", h)
    r1 = _rangs(d)
    assert d["portes"]["courante"] == 1 and r1
    avant = _etat_envoi(local, eid)
    #  L'envoi d'une étape : seul le numéro de l'étape ouverte, en nombre ; tout autre → refusé, sans rien écrire.
    for etape in FORGES:
        st, rep = local.ecrire("envoyer_etape", {"etape": etape, "reponses": {str(r): "x" for r in r1}}, h)
        _stable(st, rep)
        assert st == 409 and rep["erreur"] == "Cette étape n'est pas ouverte.", (etape, st, rep)
    assert _etat_envoi(local, eid) == avant
    #  Le repère de la page (son étape, sa question, pour le direct) : un faux numéro ne casse rien et n'ouvre rien.
    for etape in FORGES:
        for nom, corps in (("saisie", {"rang": r1[0], "texte": "repère", "etape": etape, "rang_vu": etape}),
                           ("presence", {"vue": "ouverte", "etape": etape, "rang": etape}),
                           ("brouillon", {"reponses": {str(r1[0]): "repère"}, "etape": etape, "rang": etape})):
            st, rep = local.ecrire(nom, corps, h)
            _stable(st, rep)
            assert st == 200, (nom, etape, st, rep)
    apres = _etat_envoi(local, eid)
    assert apres[:2] == avant[:2], "les portes et les réponses n'ont pas bougé"
    assert apres[2] == [(r1[0], "repère")], "seul SON brouillon, sur une question ouverte"
    st, dd = local.api("direct/candidat", local.tete, {"envoi": str(eid)})
    assert st == 200 and 0 <= dd["etape"] <= 1000 and 0 <= dd["rang"] <= 1000


# ═══════════════════════════════════════════════════════════════════════════════
#  K3 — une étape non ouverte, ou déjà envoyée
# ═══════════════════════════════════════════════════════════════════════════════

def test_K3_une_etape_non_ouverte_ou_deja_envoyee(local, sans_cadence):
    import questionnaire
    tid, eid = local.ticket(1014, etapes=2, ouverte=1)
    h = local.candidat(f"ticket={tid}")
    st, d = local.lire("questionnaire", h)
    r1 = _rangs(d)
    tous = [int(q["rang"]) for q in local.faire(questionnaire._envoi(eid))["questions"]]
    r2 = [r for r in tous if r not in r1]
    assert r1 and r2
    avant = _etat_envoi(local, eid)
    #  L'étape 2, pas encore ouverte : ni frappe, ni brouillon, ni envoi ; ni le tout-en-un.
    for nom, corps, attendu in (("saisie", {"rang": r2[0], "texte": "en avance"}, 400),
                                ("brouillon", {"reponses": {str(r2[0]): "en avance"}}, 400),
                                ("brouillon", {"reponses": {**{str(r): "x" for r in r1}, str(r2[0]): "en avance"}}, 400),
                                ("envoyer_etape", {"etape": 2, "reponses": {str(r): "x" for r in r2}}, 409),
                                ("envoyer_etape", {"etape": 1, "reponses": {str(r): "x" for r in tous}}, 400),
                                ("envoyer", {"reponses": {str(r): "x" for r in tous}}, 409)):
        st, rep = local.ecrire(nom, corps, h)
        _stable(st, rep)
        assert st == attendu, (nom, corps, st, rep)
    assert _etat_envoi(local, eid) == avant, "une étape fermée n'a rien laissé"
    #  L'étape 1 envoyée : elle est figée — en attente de la direction, puis l'étape 2 ouverte.
    st, rep = local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(r): f"Une {r}" for r in r1}}, h)
    assert st == 200 and rep["etat"] == "attente", rep
    fige = _etat_envoi(local, eid)
    for nom, corps in (("saisie", {"rang": r1[0], "texte": "réécrire"}), ("brouillon", {"reponses": {str(r1[0]): "réécrire"}}),
                       ("envoyer_etape", {"etape": 1, "reponses": {str(r): "réécrire" for r in r1}})):
        st, rep = local.ecrire(nom, corps, h)
        _stable(st, rep)
        assert st == 409 and rep["etat"] == "attente", (nom, st, rep)
    local.ouvrir_etape(eid)
    assert local.lire("questionnaire", h)[1]["portes"]["courante"] == 2
    for nom, corps, attendu in (("saisie", {"rang": r1[0], "texte": "réécrire"}, 400),
                                ("brouillon", {"reponses": {str(r1[0]): "réécrire"}}, 400),
                                ("envoyer_etape", {"etape": 1, "reponses": {str(r): "réécrire" for r in r1}}, 409)):
        st, rep = local.ecrire(nom, corps, h)
        _stable(st, rep)
        assert st == attendu, (nom, st, rep)
    assert _etat_envoi(local, eid)[1:] == fige[1:], "l'étape envoyée n'a pas été réécrite"
    assert {t for _r, t in _etat_envoi(local, eid)[1]} == {f"Une {r}" for r in r1}


# ═══════════════════════════════════════════════════════════════════════════════
#  K4 — un double envoi, l'un après l'autre et EN MÊME TEMPS
# ═══════════════════════════════════════════════════════════════════════════════

def _en_meme_temps(local, h, nom, corps_par_onglet: dict) -> dict:
    """Les envois partent ensemble (deux onglets, un double clic) : {onglet : (statut, réponse)}."""
    async def un(onglet, corps):
        r = await local.client.post(f"/tableau/candidature/api/{nom}", json=corps, headers=dict(h, **ORIGINE))
        return onglet, (r.status, await r.json())

    async def tous():
        return dict(await asyncio.gather(*(un(o, c) for o, c in corps_par_onglet.items())))
    return local.faire(tous())


@pytest.fixture
def au_pire_moment(monkeypatch):
    """Le pire moment, rendu certain : les envois arrivés ensemble s'attendent (au plus 1 s) juste avant d'écrire, et la
    fin de l'envoi (`clore_envoi`) arrive un peu après l'écriture des réponses (un serveur occupé) — la fenêtre où un
    second envoi passait. Rend `armer(n)` : n envois attendus ensemble."""
    import questionnaire
    etat = {"evt": None, "attendus": 0, "arrives": 0}

    def ensemble(vraie):
        async def f(*a, **k):
            if etat["evt"] is not None:
                etat["arrives"] += 1
                if etat["arrives"] >= etat["attendus"]:
                    etat["evt"].set()
                try:
                    await asyncio.wait_for(etat["evt"].wait(), 1.0)
                except (asyncio.TimeoutError, TimeoutError):
                    pass   # seul (les autres attendent leur tour ailleurs) : il continue
            return await vraie(*a, **k)
        return f

    vraie_cloture = questionnaire.clore_envoi

    async def cloture_lente(e, t):
        await asyncio.sleep(0.3)
        return await vraie_cloture(e, t)
    for nom in ("envoyer_tout", "envoyer_etape"):
        monkeypatch.setattr(questionnaire, nom, ensemble(getattr(questionnaire, nom)))
    monkeypatch.setattr(questionnaire, "clore_envoi", cloture_lente)

    def armer(n):
        etat.update(evt=asyncio.Event(), attendus=n, arrives=0)
    return armer


def test_K4_un_double_envoi_ne_reecrit_rien(local, sans_cadence, au_pire_moment):
    #  A — un questionnaire d'avant (tout en une fois) : trois envois EN MÊME TEMPS.
    tid, eid = local.ticket(1017)
    h = local.candidat(f"ticket={tid}")
    rangs = _rangs(local.lire("questionnaire", h)[1])
    au_pire_moment(3)
    res = _en_meme_temps(local, h, "envoyer", {o: {"reponses": {str(r): f"{o} {r}" for r in rangs}}
                                               for o in ("Premier", "Second", "Troisième")})
    local.annonces()
    for st, rep in res.values():
        _stable(st, rep)
    gagnants = [o for o, (st, _r) in res.items() if st == 200]
    assert len(gagnants) == 1 and sorted(st for st, _r in res.values()) == [200, 409, 409], res
    gardees = {t for _r, t in _etat_envoi(local, eid)[1]}
    assert gardees == {f"{gagnants[0]} {r}" for r in rangs}, f"un envoi refusé a réécrit les réponses : {sorted(gardees)[:3]}"
    assert _lignes(local, "SELECT COUNT(*) FROM recrutement_historique WHERE ticket_id=? AND quoi='reponses'", tid) == [(1,)]
    #  Puis l'un après l'autre : refusé, rien de réécrit.
    st, rep = local.ecrire("envoyer", {"reponses": {str(r): "encore" for r in rangs}}, h)
    assert st == 409 and rep["etat"] == "envoye"
    assert {t for _r, t in _etat_envoi(local, eid)[1]} == gardees
    #  B — le passage d'étape : la même étape envoyée deux fois en même temps, puis une troisième.
    tid2, eid2 = local.ticket(1020, etapes=2, ouverte=1)
    h2 = local.candidat(f"ticket={tid2}")
    r1 = _rangs(local.lire("questionnaire", h2)[1])
    au_pire_moment(2)
    res = _en_meme_temps(local, h2, "envoyer_etape", {o: {"etape": 1, "reponses": {str(r): f"{o} {r}" for r in r1}}
                                                      for o in ("Premier", "Second")})
    local.annonces()
    gagnants = [o for o, (st, _r) in res.items() if st == 200]
    assert len(gagnants) == 1 and sorted(st for st, _r in res.values()) == [200, 409], res
    assert {t for _r, t in _etat_envoi(local, eid2)[1]} == {f"{gagnants[0]} {r}" for r in r1}
    assert _etat_envoi(local, eid2)[0][0][2] == 1, "une seule étape envoyée"
    assert local.ecrire("envoyer_etape", {"etape": 1, "reponses": {str(r): "encore" for r in r1}}, h2)[0] == 409
    assert _lignes(local, "SELECT COUNT(*) FROM recrutement_historique WHERE ticket_id=? AND quoi='etape_recue'", tid2) == [(1,)]


# ═══════════════════════════════════════════════════════════════════════════════
#  K5 — des champs inconnus ou modifiés à la main
# ═══════════════════════════════════════════════════════════════════════════════

def test_K5_des_champs_inconnus_ou_modifies_a_la_main(local, sans_cadence):
    import questionnaire
    tid, eid = local.ticket(1023)
    h = local.candidat(f"ticket={tid}")
    rangs = _rangs(local.lire("questionnaire", h)[1])
    r = rangs[0]
    avant = _etat_envoi(local, eid)
    questions_avant = local.faire(questionnaire._envoi(eid))["questions"]
    faux_rangs = ("²", "①", "١", "-1", "1e3", "0x1", "1.0", " 1", "", "99999999", "abc", "1;DROP TABLE x")
    faux_textes = (5, None, True, ["x"], {"x": 1}, 1.5)
    essais = []
    for x in faux_rangs:
        essais += [("saisie", {"rang": x, "texte": "x"}), ("brouillon", {"reponses": {x: "x"}}),
                   ("envoyer", {"reponses": {**{str(k): "x" for k in rangs}, x: "x"}})]
    for x in (True, False, None, 1.0, -1, 10 ** 30, [r], {"r": r}):
        essais.append(("saisie", {"rang": x, "texte": "x"}))
    for t in faux_textes:
        essais += [("saisie", {"rang": r, "texte": t}), ("brouillon", {"reponses": {str(r): t}}),
                   ("envoyer", {"reponses": {**{str(k): "x" for k in rangs}, str(r): t}})]
    for rep_ in ([], "x", None, 5, [[str(r), "x"]], {str(k): "x" for k in range(1, questionnaire.PAR_ENVOI + 2)}):
        essais += [("brouillon", {"reponses": rep_}), ("envoyer", {"reponses": rep_}),
                   ("envoyer_etape", {"etape": 1, "reponses": rep_})]
    for vue in ("partout", None, ["ouverte"], {"v": 1}, 1, "OUVERTE"):
        essais.append(("presence", {"vue": vue}))
    for nom, corps in essais:
        st, rep = local.ecrire(nom, corps, h)
        _stable(st, rep)
        assert st in (400, 409), (nom, corps, st, rep)
    assert _etat_envoi(local, eid) == avant, "un champ modifié à la main a laissé une trace"
    #  La prévention : un numéro venu de la page passe par `_entier` (chiffres ASCII) — jamais `str.isdigit()`, qui
    #  accepte « ² » (et `int("²")` lève : l'erreur 500 corrigée le 27/10).
    import ast
    import candidature_site
    arbre = ast.parse((RACINE / "candidature_site.py").read_text(encoding="utf-8"))
    appels = [n.lineno for n in ast.walk(arbre) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("isdigit", "isnumeric", "isdecimal")]
    assert not appels, f"candidature_site.py, ligne(s) {appels} : passer par `_entier` (chiffres ASCII)"
    assert [candidature_site._entier(x) for x in ("²", "①", "١", "１", "12", 7, True, "1234567")] == \
        [None, None, None, None, 12, 7, None, None]
    #  Des champs INCONNUS (ou ceux de la base) glissés dans un corps valable : ignorés — il n'écrit que ses réponses.
    inconnus = {"statut": "repondu", "etape_ouverte": 9, "etape_envoyee": 9, "candidat_id": FONDATEUR, "guild_id": 2,
                "envoi": 1, "ticket": 1, "nature": "chef", "metier": "x", "questions": [{"rang": 1, "reponse": "x"}],
                "__proto__": {"admin": True}, "constructor": {"prototype": {"admin": True}}}
    assert local.ecrire("saisie", {"rang": r, "texte": "frappe", **inconnus}, h)[0] == 200
    assert local.ecrire("brouillon", {"reponses": {str(r): "brouillon"}, **inconnus}, h)[0] == 200
    assert local.ecrire("presence", {"vue": "cachee", **inconnus}, h)[0] == 200
    apres = _etat_envoi(local, eid)
    assert apres[0] == avant[0] and apres[1] == avant[1] and apres[2] == [(r, "brouillon")]
    st, rep = local.ecrire("envoyer", {"reponses": {str(k): f"Réponse {k}" for k in rangs}, **inconnus}, h)
    assert st == 200 and rep["etat"] == "envoye", rep
    local.annonces()
    e = local.faire(questionnaire._envoi(eid))
    assert (e["candidat_id"], e["guild_id"], e["ticket_id"], e["etape_ouverte"]) == (1023, 1, tid, 0)
    assert e["questions"] == questions_avant and e["nature"] != "chef", "l'envoi lui-même, intact"
    assert _lignes(local, "SELECT DISTINCT candidat_id FROM recrutement_reponses WHERE envoi_id=?", eid) == [(1023,)]


# ═══════════════════════════════════════════════════════════════════════════════
#  K6 — un corps trop gros, un JSON illisible
# ═══════════════════════════════════════════════════════════════════════════════

def test_K6_un_corps_trop_gros_ou_illisible(local):
    import candidature_site
    tid, eid = local.ticket(1019)
    h = local.candidat(f"ticket={tid}")
    rangs = _rangs(local.lire("questionnaire", h)[1])
    avant, base = _etat_envoi(local, eid), _empreinte_calme(local)
    for nom, route in sorted(candidature_site.ECRITURES.items()):
        maxi = route["corps_max"]
        #  Juste au-dessus de sa borne (une réponse énorme comprise) : 413, sans lire plus loin.
        trop = json.dumps({"reponses": {str(rangs[0]): "a" * maxi}, "rang": rangs[0], "texte": "a" * maxi,
                           "vue": "ouverte"}).encode()
        st, rep = _post_brut(local, h, nom, trop)
        assert st == 413 and json.loads(rep)["erreur"] == "Trop volumineux.", (nom, len(trop), maxi, st)
        #  Par morceaux, sans longueur annoncée : borné pareil.
        blocs = maxi // 1024 + 8

        async def morceaux():
            for _ in range(blocs):
                yield b"a" * 1024
        assert _post_brut(local, h, nom, morceaux())[0] == 413, nom
        #  Illisible ou piégé : 400 « Corps illisible. ».
        profondeur = max(1, min(3000, (maxi - 2) // 2))
        for brut in (b"{pas du json", b"[1, 2]", b'"texte"', b"\xff\xfe\x00{", b"{" * 10, b"[" * profondeur + b"]" * profondeur,
                     b'{"a": ' * 2000 + b"1" + b"}" * 2000, b'{"rang": 1' + b"0" * 5000 + b"}"):
            if len(brut) > maxi:
                continue
            st, rep = _post_brut(local, h, nom, brut)
            assert st == 400 and json.loads(rep)["erreur"] == "Corps illisible.", (nom, brut[:16], st, rep[:120])
    assert _etat_envoi(local, eid) == avant
    apres = _empreinte_calme(local)
    assert sorted(t for t in apres if apres[t] != base.get(t)) == [], "un corps refusé a laissé une trace en base"


# ═══════════════════════════════════════════════════════════════════════════════
#  K7 — une réponse en HTML ou en script : du texte, partout
# ═══════════════════════════════════════════════════════════════════════════════

def _chaines(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _chaines(v)
    elif isinstance(x, list):
        for v in x:
            yield from _chaines(v)
    elif isinstance(x, str):
        yield x


#  Les seuls endroits du code du site qui fabriquent du HTML à partir d'une chaîne : AUCUN, sauf le sprite d'icônes
#  (un fichier SVG du site, jamais une donnée).
PUITS_HTML = re.compile(r"\binnerHTML\b|\bouterHTML\b|insertAdjacentHTML|document\.write|createContextualFragment|"
                        r"\bsrcdoc\b|new\s+Function\b|\beval\s*\(|setAttribute\(\s*[\"']on|\.html\s*\(|DOMParser")


def test_K7_une_reponse_en_html_ou_en_script_reste_du_texte_partout(local, sans_cadence):
    tid, eid = local.ticket(1004)
    h = local.candidat(f"ticket={tid}")
    rangs = _rangs(local.lire("questionnaire", h)[1])
    assert len(rangs) >= 3
    pieges = {str(r): PIEGES[k % len(PIEGES)] for k, r in enumerate(rangs)}
    ecrits = set(pieges.values())
    #  Tapé (le direct), gardé en brouillon, puis envoyé : chaque fois, exactement le texte écrit.
    assert local.ecrire("saisie", {"rang": rangs[0], "texte": PIEGES[0], "etape": 1}, h)[0] == 200
    st, dd = local.api("direct/candidat", local.tete, {"ticket": str(tid)})
    assert st == 200 and dd["reponses"][str(rangs[0])] == PIEGES[0]
    assert local.ecrire("brouillon", {"reponses": pieges}, h)[0] == 200
    st, d = local.lire("questionnaire", h)
    assert d["reponses"] == pieges, "sa page relit exactement ce qu'il a écrit"
    st, rep = local.ecrire("envoyer", {"reponses": pieges}, h)
    assert st == 200 and rep["etat"] == "envoye", rep
    local.annonces()
    assert {(str(r), t) for r, t in _etat_envoi(local, eid)[1]} == set(pieges.items()), "gardé tel quel, sans réécriture"
    #  Servi en JSON (jamais en HTML), à la direction comme à lui : le dossier, le direct, sa lecture.
    for qui, chemin, params in (("tete", "/tableau/espace/api/recrutement/dossier", {"ticket": str(tid)}),
                                ("tete", "/tableau/espace/api/direct/candidat", {"ticket": str(tid)}),
                                ("candidat", "/tableau/candidature/api/questionnaire", None)):
        st, corps, en = local.requete("GET", chemin, local.tete if qui == "tete" else h, params=params)
        assert st == 200 and en["Content-Type"].startswith("application/json"), (chemin, st)
        assert en["X-Content-Type-Options"] == "nosniff" and en["Cache-Control"] == "no-store"
        assert ecrits <= set(_chaines(json.loads(corps))), f"{chemin} : un piège manque ou a été transformé"
    #  Les pages HTML ne l'emploient jamais (le dossier et le direct sont construits dans le navigateur, nœud par nœud).
    for chemin, hh in (("/tableau/espace/", local.tete), ("/tableau/candidature/", h)):
        page = _texte(local.requete("GET", chemin, hh)[1])
        assert not any(p in page for p in PIEGES), chemin
    #  Le code du site : aucun endroit ne fabrique de HTML depuis une chaîne — la réponse est un nœud de texte partout
    #  (`dom.js` : `h()` et `ajouter()` posent des nœuds de texte). Seule exception : le sprite d'icônes, un fichier SVG
    #  du site lu par `DOMParser` en « image/svg+xml » (jamais une donnée).
    for f in sorted((RACINE / "site").glob("*.js")):
        code = re.sub(r"(?m)^\s*//.*$", "", f.read_text(encoding="utf-8"))   # les lignes de commentaire seulement
        for m in PUITS_HTML.finditer(code):
            ligne = code.count("\n", 0, m.start()) + 1
            assert (f.name, m.group(0)) == ("dom.js", "DOMParser"), f"{f.name}:{ligne} : {m.group(0)}"
    dom = (RACINE / "site" / "dom.js").read_text(encoding="utf-8")
    assert dom.count("DOMParser") == 1 and 'parseFromString(texte, "image/svg+xml")' in dom, "seul le sprite SVG du site"
    assert "e.append(c instanceof Node ? c : document.createTextNode(String(c)))" in dom, "une chaîne devient un nœud de texte"
    #  Jamais envoyé à Discord : ni dans le ticket, ni au journal.
    messages = json.loads(_texte(local.requete("GET", f"/tableau/demo/discord?ticket={tid}")[1]))["messages"]
    tout = json.dumps(messages, ensure_ascii=False)
    assert messages and not any(p in tout for p in PIEGES) and "__piege" not in tout
    assert not [t for (t,) in local.sql("SELECT texte || ' ' || COALESCE(detail, '') FROM registre WHERE membre_id=? OR"
                                        " auteur_id=?", (1004, 1004)) if "__piege" in t or "<script" in t]


# ═══════════════════════════════════════════════════════════════════════════════
#  K8 — un lien réutilisé, expiré, abîmé, d'une autre portée ; une session expirée
# ═══════════════════════════════════════════════════════════════════════════════

def test_K8_un_lien_reutilise_ou_expire(local, sans_cadence):
    import candidature_site
    import questionnaire
    import tableau
    from conftest_discord import Obj
    tid, eid = local.ticket(1009)
    url, refus = local.faire(candidature_site.lien_ticket(Obj(guild=local.g, user=local.g.get_member(1009)), tid))
    assert url and refus == ""
    jeton = url.rsplit("/", 1)[1]

    def entree(j, h=None):
        st, corps, en = local.requete("GET", "/tableau/candidature/" + j, h)
        return st, _texte(corps), en
    h, arrivee = local.entrer("/tableau/candidature/" + jeton)
    assert arrivee == "/tableau/candidature/"
    #  Réutilisé : ailleurs (sans cookie, avec la session d'un autre candidat) → « déjà servi », aucun cookie.
    t2, _e2 = local.ticket(1012)
    autre = local.candidat(f"ticket={t2}")
    for hh in (None, autre, local.tete):
        st, page, en = entree(jeton, hh)
        assert st == 403 and "Set-Cookie" not in en and "déjà servi" in page, (hh, st)
    #  Expiré, abîmé, coupé, d'une autre portée, ou un lien de candidat à l'entrée de la direction → refusés.
    vieux = tableau.jeton(1, 1009, "candidat", maintenant=time.time() - 2 * tableau.DUREE, nonce=f"e{eid}x" + "V" * 12)
    abime = jeton[:-1] + ("A" if jeton[-1] != "A" else "B")
    for j in (vieux, abime, jeton[:-6], jeton + "x", tableau.jeton(1, 1009, "tout"), tableau.jeton(1, 1009, "equipage"),
              tableau.jeton(1, 1009, "candidat"), tableau.jeton(1, 1009, "candidat", nonce="e" + str(eid))):
        st, page, en = entree(j)
        assert st == 403 and "Set-Cookie" not in en, (j[-12:], st)
    st, _p, en = local.requete("GET", "/tableau/" + jeton)
    assert st == 403 and "Set-Cookie" not in en, "un lien de candidat n'ouvre jamais la Capitainerie"
    #  Un lien pas encore servi d'un envoi REMPLACÉ : refusé (« remplacé »).
    t3, e3 = local.ticket(1015)
    url3, _r = local.faire(candidature_site.lien_ticket(Obj(guild=local.g, user=local.g.get_member(1015)), t3))
    st, rep = local.faire(questionnaire.envoyer(local.g, t3, local.g.get_member(FONDATEUR), {}, depuis="renvoi"))
    assert st == 200
    st, page, en = entree(url3.rsplit("/", 1)[1])
    assert st == 403 and "Set-Cookie" not in en
    #  Sa session, une fois expirée : plus rien (la page, ses lectures, ses écritures).
    sid = h["Cookie"].split("=", 1)[1]
    emp = tableau._empreinte(sid)
    local.sql("UPDATE tableau_sessions SET expire_le=? WHERE empreinte=?", (int(time.time()) - 5, emp))
    local.sql("UPDATE candidature_sessions SET expire_le=? WHERE empreinte=?", (int(time.time()) - 5, emp))
    tableau._sessions.pop(emp, None)
    candidature_site._liaisons.pop(emp, None)
    avant = _etat_envoi(local, eid)
    assert local.requete("GET", "/tableau/candidature/", h)[0] == 403
    st, d = local.lire("questionnaire", h)
    assert st == 403 and d.get("etat") == "expire" and "etapes" not in d
    st, _r = local.ecrire("brouillon", {"reponses": {"1": "après la fin"}}, h)
    assert st == 403 and _etat_envoi(local, eid) == avant


# ═══════════════════════════════════════════════════════════════════════════════
#  K9 — une session après la fermeture du ticket
# ═══════════════════════════════════════════════════════════════════════════════

def test_K9_une_session_apres_la_fermeture_du_ticket(local, sans_cadence):
    import candidature_site
    tid, eid = local.ticket(1016)
    h = local.candidat(f"ticket={tid}")
    st, d = local.lire("questionnaire", h)
    rangs = _rangs(d)
    assert local.ecrire("brouillon", {"reponses": {str(rangs[0]): "avant la fermeture"}}, h)[0] == 200
    local.sql("UPDATE tickets SET status='closed' WHERE id=?", (tid,))
    candidature_site._contextes.pop(eid, None)   # sans attendre les 4 s du cache des frappes (rien n'y est écrit en base)
    avant = _etat_envoi(local, eid)
    st, d = local.lire("questionnaire", h)
    assert st == 200 and d["etat"] == "ferme"
    assert not {"etapes", "reponses", "envoi", "liens", "portes"} & set(d), sorted(d)
    assert "avant la fermeture" not in json.dumps(d, ensure_ascii=False)
    for nom, corps in (("saisie", {"rang": rangs[0], "texte": "après"}), ("brouillon", {"reponses": {str(rangs[0]): "après"}}),
                       ("envoyer", {"reponses": {str(r): "après" for r in rangs}}),
                       ("envoyer_etape", {"etape": 1, "reponses": {str(r): "après" for r in rangs}})):
        st, rep = local.ecrire(nom, corps, h)
        _stable(st, rep)
        assert st == 409 and rep["etat"] == "ferme", (nom, st, rep)
    st, rep = local.ecrire("presence", {"vue": "ouverte"}, h)
    assert st == 200 and rep["etat"] == "ferme", "le battement de la page lui dit seulement que c'est fini"
    assert _etat_envoi(local, eid) == avant, "rien d'écrit après la fermeture"
    st, dd = local.api("direct/candidat", local.tete, {"envoi": str(eid)})
    assert dd["etat"] == "ferme" and "après" not in json.dumps(dd, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════════
#  K10 — un futur chef qui perd le rôle du clan
# ═══════════════════════════════════════════════════════════════════════════════

def test_K10_un_futur_chef_qui_perd_le_role_du_clan(local, sans_cadence):
    import tableau
    eid = _envoi_chef(local, 1007)
    m = local.g.get_member(1007)
    clan = next(r for r in local.g.roles if r.name == "Rell Seas")
    assert clan in m.roles
    hc, _a = local.entrer("/tableau/candidature/" + tableau.jeton(1, 1007, "candidat", nonce=f"e{eid}x" + "K" * 12))
    st, d = local.lire("questionnaire", hc)
    assert st == 200 and d["etat"] == "ouvert" and d["nature"] == "chef"
    r1 = _rangs(d)
    assert local.ecrire("saisie", {"rang": r1[0], "texte": "avant"}, hc)[0] == 200
    assert local.ecrire("brouillon", {"reponses": {str(r1[0]): "avant"}}, hc)[0] == 200
    local.faire(m.remove_roles(clan))
    try:
        avant = _etat_envoi(local, eid)
        #  Tout de suite — même la frappe, servie par le cache de 4 s : le rôle du clan est relu à CHAQUE requête.
        for nom, corps in (("saisie", {"rang": r1[0], "texte": "après"}), ("brouillon", {"reponses": {str(r1[0]): "après"}}),
                           ("envoyer_etape", {"etape": 1, "reponses": {str(r): "après" for r in r1}}),
                           ("envoyer", {"reponses": {str(r): "après" for r in r1}})):
            st, rep = local.ecrire(nom, corps, hc)
            _stable(st, rep)
            assert st == 409 and rep["etat"] == "ferme", (nom, st, rep)
        st, d = local.lire("questionnaire", hc)
        assert d["etat"] == "ferme" and not {"etapes", "reponses", "envoi"} & set(d)
        st, rep = local.ecrire("presence", {"vue": "ouverte"}, hc)
        assert st == 200 and rep["etat"] == "ferme"
        assert _etat_envoi(local, eid) == avant, "rien d'écrit sans le rôle du clan"
        #  Un nouveau lien, une nouvelle entrée : refusés.
        h_, (st, _p) = local.entrer("/tableau/candidature/" + tableau.jeton(1, 1007, "candidat", nonce=f"e{eid}x" + "L" * 12))
        assert h_ is None and st == 403
    finally:
        local.faire(m.add_roles(clan))


# ═══════════════════════════════════════════════════════════════════════════════
#  K11 — le direct de la direction : ni « equipage », ni « candidat »
# ═══════════════════════════════════════════════════════════════════════════════

def test_K11_le_direct_de_la_direction_refuse_equipage_et_candidat(local):
    import tableau
    tid, eid = local.ticket(1021)
    h = local.candidat(f"ticket={tid}")
    sid = h["Cookie"].split("=", 1)[1]
    sessions = {"candidat": h, "candidat_recopie": {"Cookie": f"{tableau.COOKIE}={sid}"}, "equipage": local.kolax_equipage}
    for qui, hh in sessions.items():
        for params in ({"ticket": str(tid)}, {"envoi": str(eid)}):
            st, corps, _en = local.requete("GET", "/tableau/espace/api/direct/candidat", hh, params=params)
            assert st == 403 and "reponses" not in _texte(corps) and len(corps) < 200, (qui, params, st)
        assert local.requete("GET", "/tableau/espace/api/direct/etat", hh, params={"onglet": "onglet-k11-xyz"})[0] == 403

        async def socket():
            try:
                ws = await local.client.ws_connect("/tableau/espace/direct", headers=dict(hh, Origin="http://localhost:8790"))
            except aiohttp.WSServerHandshakeError as ex:
                return ex.status
            await ws.close()
            return 101
        assert local.faire(socket()) == 403, qui
    assert local.api("direct/candidat", local.tete, {"ticket": str(tid)})[0] == 200
    #  La tête elle-même : un numéro écrit avec d'autres chiffres que 0-9 est refusé proprement (jamais une erreur 500).
    for params in ({"ticket": "²"}, {"envoi": "①"}, {"ticket": "١"}, {"envoi": "１２"}, {"ticket": "", "envoi": ""}):
        assert local.api("direct/candidat", local.tete, params)[0] == 400, params
