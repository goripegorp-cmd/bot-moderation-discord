"""La HIÉRARCHIE de l'équipage (27/10/2026, hierarchie.py) — sur le VRAI site local (`outils/site_local.py`).

H1 les rangs de départ, dans l'ordre ; les trois rangs verrouillés (le Capitaine = le fondateur, le Second = la
   direction, le rang par défaut en dernier) : ni retirés, ni déplacés, ni attribués — renommables.
H2 l'attribution par la tête seule (version vérifiée, journal, verrou de présence) ; la portée « equipage » : 403 sur toute
   écriture et sur la lecture de la direction, rien n'a bougé ; le site de l'équipage et la vitrine montrent le rang.
H3 les rôles Discord : un rang lié donne SON rôle et retire les AUTRES rôles de rang, jamais un autre rôle ; un rôle à
   permission dangereuse, le rôle du clan, un rôle au-dessus du bot, un rôle géré : refusés ; le rôle du rang par défaut
   (ici le rôle du clan) n'est jamais retiré ; un rôle changé sur Discord se lit tout de suite ; la hiérarchie du bot
   vérifiée AVANT (raison claire, rien ne bouge) ; un refus de Discord ne laisse rien à moitié.
H4 la reprise des anciens grades par leur NOM : correspondance automatique, rangs réservés, « à relier », corrigée sur le
   site, « Créer ce rang » ; un rang renommé garde ses membres ; une affiche sans membre lié garde son grade écrit.
H5 le départ du clan : le rang n'est plus affiché, rien n'est effacé — il revient avec le membre.
H6 le câblage : textes au registre, adresses et verrous, étape du bot, pages sans HTML de données.
"""
from __future__ import annotations

import ast
import json

import discord
import pytest

import test_site_equipage as _socle
from conftest_discord import Obj
from test_site_equipage import ANNE, DIRECTION, FONDATEUR, KOLAX, MIRA, RACINE

local = _socle.local   # un site local à part pour ce fichier (portée « module »)
CALICO = 1004
ROUTES = (("equipage/hierarchie/rang", {"nom": "Pirate"}), ("equipage/hierarchie/rang/supprimer", {"id": "vigie"}),
          ("equipage/hierarchie/rang/deplacer", {"id": "vigie", "sens": "haut"}),
          ("equipage/hierarchie/rang/role", {"id": "vigie", "creer": True}),
          ("equipage/hierarchie/attribuer", {"membre": str(KOLAX), "rang": "vigie", "version": 0}),
          ("equipage/hierarchie/reprise", {"cle": "matelot", "rang": "vigie", "version": 1}))


def _h(local, h=None) -> dict:
    st, corps, _e = local.requete("GET", "/tableau/espace/api/equipage/hierarchie", h or local.tete)
    assert st == 200, corps
    return json.loads(corps)


def _attribuer(local, membre, rang, h=None):
    d = _h(local)
    v = (d["membres"].get(str(membre)) or {}).get("version", 0)
    return local.ecrire("equipage/hierarchie/attribuer", {"membre": str(membre), "rang": rang, "version": v}, h or local.tete)


def _rang(d, ident) -> dict:
    return next(r for r in d["rangs"] if r["id"] == ident)


def _journal(local, motif="Hiérarchie : %") -> str:
    return local.sql("SELECT texte FROM registre WHERE texte LIKE ? ORDER BY rowid DESC LIMIT 1", (motif,))[0][0]


def _action(local, action, membre):
    st, rep, _h = local.requete("POST", "/tableau/espace/action", local.tete, {"action": action, "membre": str(membre)}, ecrire=True)
    assert st == 200, rep


def _vitrine(local) -> dict:
    import site_vitrine
    site_vitrine.oublier()
    st, corps, _e = local.requete("GET", "/equipage/donnees")
    assert st == 200
    return json.loads(corps)


# ═══════════════════════════════════════════════════════════════════════════════

def test_H1_les_rangs_de_depart_et_les_trois_rangs_verrouilles(local):
    d = _h(local)
    assert [r["nom"] for r in d["rangs"]] == ["Capitaine", "Second", "Commandant", "Chef de flotte", "Vigie", "Charpentier",
                                             "Corsaire", "Moussaillon"]
    cap, sec, defaut = d["rangs"][0], d["rangs"][1], d["rangs"][-1]
    assert (cap["verrou"], sec["verrou"], defaut["verrou"]) == ("capitaine", "second", "defaut")
    #  Le Capitaine : le fondateur, lui seul ; le Second : la direction, un seul — par TETE_IDS, jamais par le site.
    assert [m["id"] for m in cap["membres"]] == [str(FONDATEUR)] and [m["id"] for m in sec["membres"]] == [str(DIRECTION)]
    assert d["membres"][str(FONDATEUR)]["source"] == d["membres"][str(DIRECTION)]["source"] == "tete"
    #  Le rang par défaut : tout membre du clan sans autre rang (la démonstration : un Charpentier, un Corsaire).
    assert _rang(d, "charpentier")["n"] == 1 and _rang(d, "corsaire")["n"] == 1
    assert d["membres"][str(KOLAX)]["rang"] == "moussaillon" and str(1002) not in d["membres"], "Barbe-Grise : hors du clan"
    #  Verrouillés : ni retirés, ni déplacés, ni attribués (à personne, ni à eux).
    for nom, corps in (("equipage/hierarchie/rang/supprimer", {"id": "capitaine"}),
                       ("equipage/hierarchie/rang/supprimer", {"id": "moussaillon"}),
                       ("equipage/hierarchie/rang/deplacer", {"id": "moussaillon", "sens": "haut"}),
                       ("equipage/hierarchie/rang/deplacer", {"id": "second", "sens": "bas"})):
        st, r = local.ecrire(nom, corps, local.tete)
        assert st == 400 and "verrouillé" in r["erreur"], (nom, st, r)
    st, r = _attribuer(local, KOLAX, "capitaine")
    assert st == 400 and r["champ"] == "rang", r
    st, r = _attribuer(local, DIRECTION, "vigie")
    assert st == 400 and r["champ"] == "membre" and "Capitaine ou Second" in r["erreur"], r
    st, r = _attribuer(local, 1002, "vigie")
    assert st == 400 and "pas dans le clan" in r["erreur"], r
    #  … mais renommables (et rendus).
    st, r = local.ecrire("equipage/hierarchie/rang", {"id": "second", "version": sec["version"], "nom": "Second maître",
                                                      "insigne": sec["insigne"], "couleur": sec["couleur"], "phrase": sec["phrase"]},
                         local.tete)
    assert st == 200 and _rang(r, "second")["nom"] == "Second maître" and _rang(r, "second")["verrou"] == "second"
    st, r = local.ecrire("equipage/hierarchie/rang", {"id": "second", "version": _rang(r, "second")["version"], "nom": "Second",
                                                      "insigne": sec["insigne"], "couleur": sec["couleur"], "phrase": sec["phrase"]},
                         local.tete)
    assert st == 200
    #  Ajouter, déplacer, retirer un rang intermédiaire : juste au-dessus du rang par défaut ; un nom pris est refusé.
    st, r = local.ecrire("equipage/hierarchie/rang", {"nom": "Quartier-maître", "insigne": "cle", "couleur": "#3d2f5e"}, local.tete)
    assert st == 200, r
    assert [x["nom"] for x in r["rangs"]][-2:] == ["Quartier-maître", "Moussaillon"]
    qm = r["id"]
    st, r2 = local.ecrire("equipage/hierarchie/rang", {"nom": "quartier maitre", "insigne": "cle", "couleur": "#3d2f5e"}, local.tete)
    assert st == 400 and r2["champ"] == "nom"
    for refus in ({"nom": "X", "insigne": "fusee", "couleur": "#3d2f5e"}, {"nom": "X", "insigne": "cle", "couleur": "rouge"}, {"nom": ""}):
        assert local.ecrire("equipage/hierarchie/rang", dict({"insigne": "cle", "couleur": "#3d2f5e"}, **refus), local.tete)[0] == 400
    st, r = local.ecrire("equipage/hierarchie/rang/deplacer", {"id": qm, "sens": "haut"}, local.tete)
    assert st == 200 and [x["nom"] for x in r["rangs"]][-3:] == ["Quartier-maître", "Corsaire", "Moussaillon"]
    st, r = local.ecrire("equipage/hierarchie/rang/supprimer", {"id": qm}, local.tete)
    assert st == 200 and "Quartier-maître" not in [x["nom"] for x in r["rangs"]]


def test_H2_la_tete_seule_attribue_version_journal_et_l_equipage_refuse(local):
    import hierarchie
    avant = _h(local)
    #  La portée « equipage » : 403 sur toute écriture, et sur la lecture de la direction ; rien n'a bougé.
    for nom, corps in ROUTES:
        assert local.ecrire(nom, corps, local.kolax)[0] == 403, nom
    assert local.requete("GET", "/tableau/espace/api/equipage/hierarchie", local.kolax)[0] == 403
    assert _h(local) == avant, "rien n'a bougé"
    #  La direction (la tête) peut, comme le fondateur.
    hd, _a = local.entrer("/tableau/demo?qui=direction")
    st, r = _attribuer(local, KOLAX, "commandant", hd)
    assert st == 200 and r["membres"][str(KOLAX)] == {"rang": "commandant", "source": "site", "version": 1}, r
    assert _journal(local).startswith("Hiérarchie : Kolax nommé Commandant (par Capitaine Direction)"), _journal(local)
    #  Une version dépassée : 409, le rang enregistré dans la réponse.
    st, r = local.ecrire("equipage/hierarchie/attribuer", {"membre": str(KOLAX), "rang": "vigie", "version": 0}, local.tete)
    assert st == 409 and r["actuel"]["rang"] == "commandant" and r["actuel"]["version"] == 1, r
    #  Le site de l'équipage et la vitrine le montrent : sur son affiche (le grade montré), dans la hiérarchie.
    st, eq = local.lire("equipage", local.kolax)
    kolax = next(a for a in eq["affiches"] if a["roblox"]["nom"] == "Kolax_RS")
    assert kolax["rang"]["nom"] == "Commandant" and kolax["grade"] == "Commandant"
    assert eq["hierarchie"]["mon_rang"] == "commandant"
    assert [m["nom"] for m in _rang(eq["hierarchie"], "commandant")["membres"]] == ["Kolax"]
    v = _vitrine(local)
    vk = next(a for a in v["affiches"] if a["roblox"]["nom"] == "Kolax_RS")
    assert vk["grade"] == "Commandant" and _rang(v["hierarchie"], "commandant")["membres"] == [{"affiche": vk["id"]}]
    assert set(_rang(v["hierarchie"], "commandant")) == {"id", "nom", "insigne", "couleur", "phrase", "verrou", "n", "membres"}
    #  Les verrous de la présence en direct : un rang, le rang d'un membre.
    assert hierarchie.ROUTES_SITE["equipage/hierarchie/attribuer"]["verrou"](
        {"affectations": [{"membre": str(KOLAX)}, {"membre": "12"}]}) == ["rang-membre:1000", "rang-membre:12"]
    assert hierarchie.ROUTES_SITE["equipage/hierarchie/rang"]["verrou"]({"id": "vigie"}) == "rang:vigie"
    assert hierarchie.ROUTES_SITE["equipage/hierarchie/rang"]["verrou"]({"nom": "neuf"}) is None
    #  Plusieurs d'un coup (25 au plus) : un seul passage, une ligne au journal.
    st, r = local.ecrire("equipage/hierarchie/attribuer", {"affectations": [
        {"membre": str(KOLAX), "rang": "moussaillon", "version": 1},
        {"membre": str(CALICO), "rang": "vigie", "version": 0}]}, local.tete)
    assert st == 200 and sorted(r["faits"]) == sorted([str(KOLAX), str(CALICO)]), r
    assert r["membres"][str(KOLAX)]["rang"] == "moussaillon" and r["membres"][str(CALICO)]["rang"] == "vigie"
    assert _journal(local).startswith("Hiérarchie : 2 membres changent de rang")
    assert local.ecrire("equipage/hierarchie/attribuer", {"affectations": [{"membre": str(KOLAX), "rang": "vigie"}] * 26},
                        local.tete)[0] == 400
    assert _attribuer(local, CALICO, "moussaillon")[0] == 200


def test_H3_roles_discord_exclusifs_refus_dangereux_et_rang_par_defaut_jamais_touche(local, monkeypatch):
    g = local.g
    par_nom = {r.name: r for r in g.roles}
    clan, staff, bot_r, geree = par_nom["Rell Seas"], par_nom["Staff"], par_nom["GoRP Bot"], par_nom["Bot musique"]
    vigie, cmd = g.role("Vigie de bord", 9), g.role("Commandant de bord", 10)
    lier = lambda rang, role: local.ecrire("equipage/hierarchie/rang/role", {"id": rang, "role_id": str(role.id)}, local.tete)  # noqa: E731
    #  Refusés, avec une raison claire : permission dangereuse, rôle du clan (pour un intermédiaire), au-dessus du bot,
    #  géré par une intégration, déjà lié ailleurs.
    for role, mot in ((staff, "permission dangereuse (Bannir, Expulser)"), (clan, "rôle du clan"), (bot_r, "au-dessus du mien"),
                      (geree, "intégration")):
        st, r = lier("vigie", role)
        assert st == 400 and mot in r["erreur"] and r["champ"] == "role_id", (role.name, st, r)
    assert lier("vigie", vigie)[0] == 200 and lier("commandant", cmd)[0] == 200
    st, r = lier("corsaire", vigie)
    assert st == 400 and "déjà celui du rang « Vigie »" in r["erreur"], r
    #  Le rang par défaut lié au rôle du clan : permis (il n'est jamais donné ni retiré).
    assert lier("moussaillon", clan)[0] == 200
    mira = g.get_member(MIRA)
    autres = {r.id for r in mira.roles}
    assert clan.id in autres
    st, r = _attribuer(local, MIRA, "vigie")
    assert st == 200 and vigie in mira.roles and cmd not in mira.roles
    st, r = _attribuer(local, MIRA, "commandant")
    assert st == 200 and cmd in mira.roles and vigie not in mira.roles, "un seul rôle de rang"
    assert {x.id for x in mira.roles} == autres | {cmd.id}, "jamais un autre rôle"
    assert "+Commandant de bord" in _journal(local) and "−Vigie de bord" in _journal(local)
    st, r = _attribuer(local, MIRA, "moussaillon")
    assert st == 200 and {x.id for x in mira.roles} == autres, "le rôle du clan (celui du rang par défaut) reste"
    #  Un rôle donné ou retiré DIRECTEMENT sur Discord : le site le reflète aussitôt.
    local.faire(mira.add_roles(vigie))
    assert _h(local)["membres"][str(MIRA)] == {"rang": "vigie", "source": "role", "version": 3}
    local.faire(mira.remove_roles(vigie))
    assert _h(local)["membres"][str(MIRA)]["rang"] == "moussaillon"
    #  Sans « Gérer les rôles » : la raison, et rien ne bouge (ni Discord, ni le rang écrit).
    perms = g.me.guild_permissions
    g.me.guild_permissions = discord.Permissions(manage_roles=False)
    try:
        st, r = _attribuer(local, MIRA, "vigie")
        assert st == 403 and "Gérer les rôles" in r["erreur"], r
    finally:
        g.me.guild_permissions = perms
    assert vigie not in mira.roles and _h(local)["membres"][str(MIRA)]["version"] == 3
    #  Discord refuse : rien à moitié, le rang écrit ne change pas.
    async def refuse(*_roles, reason=None):
        raise discord.Forbidden(Obj(status=403, reason="refus"), "hiérarchie")
    monkeypatch.setattr(mira, "add_roles", refuse)
    st, r = _attribuer(local, MIRA, "vigie")
    assert st == 502 and "rien n'a changé" in r["erreur"] and vigie not in mira.roles, r
    monkeypatch.undo()
    assert _h(local)["membres"][str(MIRA)]["rang"] == "moussaillon"
    #  Délier : ceux qui avaient le rang par leur rôle le gardent (écrit sur le site) ; le rôle reste sur Discord.
    local.faire(mira.add_roles(cmd))
    st, r = local.ecrire("equipage/hierarchie/rang/role", {"id": "commandant", "retirer": True}, local.tete)
    assert st == 200 and r["membres"][str(MIRA)]["rang"] == "commandant" and r["membres"][str(MIRA)]["source"] == "site"
    assert cmd in mira.roles and g.get_role(cmd.id) is not None
    for rang in ("vigie", "moussaillon"):
        assert local.ecrire("equipage/hierarchie/rang/role", {"id": rang, "retirer": True}, local.tete)[0] == 200
    local.faire(mira.remove_roles(cmd))
    assert _attribuer(local, MIRA, "moussaillon")[0] == 200
    #  « Créer le rôle » : sans aucune permission, au nom du rang ; renommer le rang renomme le rôle qui le suivait.
    st, r = local.ecrire("equipage/hierarchie/rang/role", {"id": "chef-de-flotte", "creer": True}, local.tete)
    assert st == 200 and _rang(r, "chef-de-flotte")["role"]["nom"] == "Chef de flotte", r
    cree = g.get_role(int(_rang(r, "chef-de-flotte")["role"]["id"]))
    assert cree.permissions == discord.Permissions.none()
    fl = _rang(r, "chef-de-flotte")
    st, r = local.ecrire("equipage/hierarchie/rang", {"id": fl["id"], "version": fl["version"], "nom": "Amiral",
                                                      "insigne": fl["insigne"], "couleur": fl["couleur"], "phrase": fl["phrase"]},
                         local.tete)
    assert st == 200 and cree.name == "Amiral", r
    fl = _rang(r, "chef-de-flotte")
    assert local.ecrire("equipage/hierarchie/rang", {"id": fl["id"], "version": fl["version"], "nom": "Chef de flotte",
                                                     "insigne": fl["insigne"], "couleur": fl["couleur"], "phrase": fl["phrase"]},
                        local.tete)[0] == 200
    assert local.ecrire("equipage/hierarchie/rang/role", {"id": "chef-de-flotte", "retirer": True}, local.tete)[0] == 200


def test_H4_la_reprise_des_anciens_grades_par_leur_nom(local):
    d = _h(local)
    rep = {x["nom"]: x for x in d["reprise"]}
    #  La démonstration : « Second » (Kolax : un rang réservé), « Matelot », « Mousse » — à relier, rien d'inventé.
    assert rep["Second"]["reserve"] and rep["Second"]["rang"] == "" and rep["Matelot"]["rang"] == rep["Mousse"]["rang"] == ""
    assert d["membres"][str(KOLAX)]["rang"] == "moussaillon", "« Second » écrit ne fait pas un Second"
    #  Un grade qui porte le nom d'un rang (casse et accents à part) : relié tout seul, par son nom.
    st, r = local.ecrire("rell/affiche", {"id": "hie-anne-0001", "membre_id": str(ANNE), "roblox_nom": "Anne_RS",
                                          "grade": "CORSAIRE", "statut": "actif"}, local.tete)
    assert st == 200, r
    try:
        d = _h(local)
        assert d["membres"][str(ANNE)] == {"rang": "corsaire", "source": "reprise", "version": 0}
        assert {x["nom"]: x for x in d["reprise"]}["CORSAIRE"]["rang"] == "corsaire"
        #  Le rang renommé garde ses membres (la correspondance tient par le rang, pas par le nom).
        cors = _rang(d, "corsaire")
        st, r = local.ecrire("equipage/hierarchie/rang", {"id": "corsaire", "version": cors["version"], "nom": "Flibustier",
                                                          "insigne": cors["insigne"], "couleur": cors["couleur"],
                                                          "phrase": cors["phrase"]}, local.tete)
        assert st == 200 and r["membres"][str(ANNE)]["rang"] == "corsaire"
        st, eq = local.lire("equipage", local.kolax)
        anne = next(a for a in eq["affiches"] if a["roblox"]["nom"] == "Anne_RS")
        assert anne["grade"] == "Flibustier" and anne["rang"]["nom"] == "Flibustier"
        assert local.sql("SELECT grade FROM rell_affiches WHERE id='hie-anne-0001'") == [("CORSAIRE",)], "le grade écrit reste"
        cors = _rang(r, "corsaire")
        assert local.ecrire("equipage/hierarchie/rang", {"id": "corsaire", "version": cors["version"], "nom": "Corsaire",
                                                         "insigne": cors["insigne"], "couleur": cors["couleur"],
                                                         "phrase": cors["phrase"]}, local.tete)[0] == 200
        #  Corrigée sur le site : « Mousse » → Vigie (Nemo, jamais nommé, la prend ; Calico, nommé en H2, garde son rang
        #  écrit : l'attribution passe avant la reprise) ; « Matelot » : « Créer ce rang ».
        st, r = local.ecrire("rell/affiche", {"id": "hie-nemo-0001", "membre_id": "1009", "roblox_nom": "Nemo_RS",
                                              "grade": "mousse", "statut": "actif"}, local.tete)
        assert st == 200, r
        mousse = {x["nom"]: x for x in _h(local)["reprise"]}["Mousse"]
        st, r = local.ecrire("equipage/hierarchie/reprise", {"cle": mousse["cle"], "rang": "vigie", "version": mousse["version"]},
                             local.tete)
        assert st == 200 and r["membres"]["1009"] == {"rang": "vigie", "source": "reprise", "version": 0}, r
        assert r["membres"][str(CALICO)]["source"] == "site"
        assert local.ecrire("equipage/hierarchie/reprise", {"cle": mousse["cle"], "rang": "second", "version": mousse["version"] + 1},
                            local.tete)[0] == 400, "aucun ancien grade ne mène au Second"
        assert local.ecrire("equipage/hierarchie/reprise", {"cle": mousse["cle"], "rang": "", "version": mousse["version"]},
                            local.tete)[0] == 409
        matelot = {x["nom"]: x for x in r["reprise"]}["Matelot"]
        st, r = local.ecrire("equipage/hierarchie/reprise", {"cle": matelot["cle"], "creer": True}, local.tete)
        assert st == 200 and "Matelot" in [x["nom"] for x in r["rangs"]], r
        cree = next(x for x in r["rangs"] if x["nom"] == "Matelot")
        if r["membres"][str(MIRA)]["source"] != "site":   # Mira a pu être nommée avant (H3) : son rang écrit passe d'abord
            assert r["membres"][str(MIRA)]["rang"] == cree["id"]
        assert local.ecrire("equipage/hierarchie/rang/supprimer", {"id": cree["id"]}, local.tete)[0] == 200
        mousse = {x["nom"]: x for x in _h(local)["reprise"]}["Mousse"]
        assert local.ecrire("equipage/hierarchie/reprise", {"cle": mousse["cle"], "rang": "", "version": mousse["version"]},
                            local.tete)[0] == 200
        #  Une affiche SANS membre lié garde son grade écrit, partout.
        st, r = local.ecrire("rell/affiche", {"id": "hie-fantome-01", "roblox_nom": "Fantome_RS", "grade": "Quartier-maître",
                                              "statut": "actif"}, local.tete)
        assert st == 200, r
        eq = local.lire("equipage", local.kolax)[1]
        f = next(a for a in eq["affiches"] if a["roblox"]["nom"] == "Fantome_RS")
        assert f["grade"] == "Quartier-maître" and f["rang"] is None
        vf = next(a for a in _vitrine(local)["affiches"] if a["roblox"]["nom"] == "Fantome_RS")
        assert vf["grade"] == "Quartier-maître" and vf["rang"] is None
        st, corps, _e = local.requete("GET", "/tableau/espace/api/rell/affiches", local.tete)
        adm = {a["id"]: a for a in json.loads(corps)["affiches"]}
        assert adm["hie-fantome-01"]["rang"] is None and adm["hie-anne-0001"]["rang"]["nom"] == "Corsaire"
        assert adm["hie-anne-0001"]["grade"] == "CORSAIRE", "l'atelier lit toujours le grade écrit"
    finally:
        for ident in ("hie-anne-0001", "hie-fantome-01", "hie-nemo-0001"):
            local.ecrire("rell/affiche/retirer", {"id": ident}, local.tete)


def test_H5_un_depart_du_clan_le_rang_n_est_plus_montre_rien_n_est_efface(local):
    assert _attribuer(local, MIRA, "charpentier")[0] == 200
    _action(local, "clan_retirer", MIRA)
    try:
        d = _h(local)
        assert str(MIRA) not in d["membres"] and d["hors"][str(MIRA)] == "charpentier", "gardé, plus montré"
        assert local.sql("SELECT rang_id FROM hierarchie_membres WHERE membre_id=?", (MIRA,)) == [("charpentier",)]
        mira = next(a for a in local.lire("equipage", local.tete)[1]["affiches"] if a["roblox"]["nom"] == "Mira_RS")
        assert mira["rang"] == {"id": "", "nom": "", "couleur": "", "insigne": ""} and mira["grade"] == ""
        assert str(MIRA) not in json.dumps(_rang(d, "charpentier")["membres"])
        st, r = _attribuer(local, MIRA, "vigie")
        assert st == 400 and "pas dans le clan" in r["erreur"]
    finally:
        _action(local, "clan_ajouter", MIRA)
    assert _h(local)["membres"][str(MIRA)]["rang"] == "charpentier", "il revient avec son rang"
    assert _attribuer(local, MIRA, "moussaillon")[0] == 200


def test_H6_le_cablage(local):
    import hierarchie
    import tableau
    import textes
    for cle, *_r in hierarchie.TEXTES_SITE:
        assert textes.declare(cle) and cle.startswith("site.hierarchie."), cle
    assert textes.declare("site.sous.equipage.membres.hierarchie")
    assert hierarchie.cle_grade("Chef-de-Flotte") == "chef de flotte" and hierarchie.cle_grade(" Écuyère ") == "ecuyere"
    assert {n for n in tableau.ROUTES if n.startswith("equipage/hierarchie")} == {
        "equipage/hierarchie", "equipage/hierarchie/rang", "equipage/hierarchie/rang/supprimer",
        "equipage/hierarchie/rang/deplacer", "equipage/hierarchie/rang/role", "equipage/hierarchie/attribuer",
        "equipage/hierarchie/reprise"}
    assert tableau.ROUTES["equipage/hierarchie/rang/role"]["POST"]["grave"] == "roles"
    assert not any(r.get("hors_ligne") for d in tableau.ROUTES.values() for r in d.values() if r["fn"].__module__ == "hierarchie")
    #  L'étape du bot : après « affiches » et « site_equipage ».
    boot = ast.unparse(next(n for n in ast.parse((RACINE / "bot.py").read_text(encoding="utf-8")).body
                            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_activite_boot"))
    etape = boot[boot.index("with _Etape('hierarchie'):"):]
    for morceau in ("hierarchie.setup(get_db=get_db, cfg=cfg", "await hierarchie.init_db()", "tableau.monter(hierarchie)"):
        assert morceau in etape, morceau
    assert boot.index("with _Etape('affiches'):") < boot.index("with _Etape('site_equipage'):") < boot.index("with _Etape('hierarchie'):")
    #  Les pages : aucune donnée en HTML ; le dessin public, l'éditeur à la tête seule.
    for f in ("hierarchie.js", "hierarchie_admin.js"):
        js = (RACINE / "site" / f).read_text(encoding="utf-8")
        assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js and ".style." not in js, f
    assert tableau.lecteurs_statique("hierarchie.js") != frozenset({"tout"})
    assert tableau.lecteurs_statique("hierarchie_admin.js") == frozenset({"tout"})
    import gdpr
    assert gdpr.DELETE_SUBJECT_KEEP_ACTOR["hierarchie_membres"] == {"subject": ["membre_id"], "actor": ["maj_par"]}

    async def valider():
        async with local.ctx.get_db() as db:
            return await gdpr.validate_map(db)
    rapport = local.faire(valider())
    assert not [t for t in rapport["missing_tables"] if t.startswith("hierarchie")], rapport
