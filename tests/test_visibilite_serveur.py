"""Ce qu'un NOUVEL ARRIVANT voit du serveur (03/10/2026).

« Tu t'assures que tout s'affiche bien pour les nouveaux arrivants. Que tout le
monde voit bien le serveur. » Relevé sans appel réseau ; seule correction :
l'onboarding Discord, dont les salons « par défaut » sont tout ce qu'un nouveau
voit d'office. Ces tests n'appellent jamais Discord.
"""
from __future__ import annotations

import asyncio

import discord
import pytest

import visibilite_serveur as vis

T, CAT = discord.ChannelType.text, discord.ChannelType.category


class _Role:
    def __init__(self, rid, nom, rang, managed=False):
        self.id, self.name, self.rang, self.managed = rid, nom, rang, managed

    def __lt__(self, autre):
        return self.rang < autre.rang


class _Salon:
    def __init__(self, sid, nom, type_=T, categorie=None, voient=()):
        self.id, self.name, self.type = sid, nom, type_
        self.category_id = categorie
        self.voient = set(voient)          # identifiants des rôles qui voient

    def permissions_for(self, role):
        return type("P", (), {"view_channel": role.id in self.voient})()


class _Onboarding:
    def __init__(self, actif, defaut):
        self.enabled, self.default_channel_ids = actif, set(defaut)


class _Guild:
    def __init__(self, salons, onboarding=None, bot_rang=50, refus=None):
        self.id = 1
        self.default_role = _Role(1, "@everyone", 0)
        self.membre = _Role(10, "Membre", 5)
        self.roles = [self.default_role, self.membre]
        self.channels = salons
        self._ob, self._refus = onboarding, refus
        self.editions = []
        self.me = type("Me", (), {
            "top_role": _Role(999, "bot", bot_rang),
            "guild_permissions": type("P", (), {"manage_roles": True})()})()

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    async def onboarding(self):
        if self._ob is None:
            raise discord.Forbidden(type("R", (), {"status": 403, "reason": "x"})(), "x")
        return self._ob

    async def edit_onboarding(self, *, default_channels, reason=None):
        if self._refus:
            raise self._refus
        self.editions.append(sorted(c.id for c in default_channels))


def _serveur(**kw):
    #  @everyone voit l'accueil ; « Membre » voit la communauté ; personne ne
    #  voit le staff ; un salon caché traîne dans la communauté.
    salons = [
        _Salon(1, "ACCUEIL", CAT, voient={1, 10}),
        _Salon(2, "règles", categorie=1, voient={1, 10}),
        _Salon(3, "bienvenue", categorie=1, voient={1, 10}),
        _Salon(4, "COMMUNAUTÉ", CAT, voient=()),          # catégorie fermée…
        _Salon(5, "général", categorie=4, voient={10}),   # …mais un salon visible
        _Salon(6, "brouillon", categorie=4, voient=()),
        _Salon(7, "STAFF", CAT, voient=()),
        _Salon(8, "modération", categorie=7, voient=()),
        _Salon(9, "logs", categorie=7, voient=()),
    ]
    return _Guild(salons, **kw)


def test_V1_ce_que_voit_un_nouveau_avec_son_role_d_arrivee():
    r = vis.releve(_serveur(), {"welcome_autorole": 10})
    assert r["role"] == "Membre" and r["role_pose"] is True
    assert r["categories"] == (2, 3), \
        "COMMUNAUTÉ s'affiche : Discord montre une catégorie dès qu'un de ses salons l'est"
    assert r["salons"] == (3, 6)
    assert r["categories_cachees"] == [("STAFF", 2)]
    assert r["salons_caches"] == ["brouillon"], \
        "les salons d'une catégorie entièrement cachée ne sont pas répétés"


def test_V1bis_sans_role_d_arrivee_on_juge_avec_everyone_seul():
    r = vis.releve(_serveur(), {})
    assert r["role"] is None and r["salons"] == (2, 6)
    assert ("COMMUNAUTÉ", 2) in r["categories_cachees"]


def test_V1ter_un_role_d_arrivee_au_dessus_du_bot_est_signale():
    g = _serveur(bot_rang=3)
    r = vis.releve(g, {"welcome_autorole": 10})
    assert r["role_pose"] is False and r["salons"] == (2, 6), \
        "le bot ne peut pas le poser : le nouveau n'a que @everyone"
    t = vis.bilan_texte("GoRP", r, {"actif": False})
    assert "rôle d'arrivée introuvable ou au-dessus du bot" in t


def test_V2_onboarding_actif_tous_les_salons_publics_deviennent_par_defaut():
    g = _serveur(onboarding=_Onboarding(True, {2}))
    ob = asyncio.run(vis.ouvrir_onboarding(g))
    assert g.editions == [[2, 3]], \
        "les défauts existants gardés, le salon public manquant ajouté — pas les catégories"
    assert ob == {"actif": True, "defaut": 1, "manquants": 1, "ajoutes": 1, "raison": ""}


def test_V2bis_un_salon_que_everyone_ne_voit_pas_n_est_jamais_propose():
    """Discord refuserait, et ce serait l'ouvrir de fait : le salon « général »
    réservé au rôle Membre n'est pas ajouté."""
    g = _serveur(onboarding=_Onboarding(True, {2, 3}))
    ob = asyncio.run(vis.ouvrir_onboarding(g))
    assert g.editions == [] and ob["manquants"] == 0


@pytest.mark.parametrize("onboarding,attendu", [
    (_Onboarding(False, set()), {"actif": False}),
    (None, {"actif": None}),
])
def test_V3_onboarding_inactif_ou_illisible_rien_n_est_ecrit(onboarding, attendu):
    g = _serveur(onboarding=onboarding)
    ob = asyncio.run(vis.ouvrir_onboarding(g))
    assert g.editions == []
    assert all(ob[k] == v for k, v in attendu.items())


def test_V4_un_refus_de_discord_est_dit_pas_avale():
    refus = discord.Forbidden(type("R", (), {"status": 403, "reason": "x"})(), "x")
    g = _serveur(onboarding=_Onboarding(True, {2}), refus=refus)
    ob = asyncio.run(vis.ouvrir_onboarding(g))
    assert ob["ajoutes"] == 0 and "Gérer le serveur" in ob["raison"]
    t = vis.bilan_texte("GoRP", vis.releve(g, {"welcome_autorole": 10}), ob)
    assert "hors des salons par défaut" in t and "Gérer le serveur" in t


def test_V5_le_bilan_se_lit_d_un_coup_d_oeil():
    g = _serveur(onboarding=_Onboarding(True, {2}))
    ob = asyncio.run(vis.ouvrir_onboarding(g))
    t = vis.bilan_texte("GoRP SEA (1)", vis.releve(g, {"welcome_autorole": 10}), ob)
    assert t.startswith("GoRP SEA (1) : un nouvel arrivant (@everyone + « Membre ») "
                        "voit 2/3 catégorie(s) et 3/6 salon(s)")
    assert "catégories invisibles : STAFF (2)" in t
    assert "salons invisibles : #brouillon" in t
    assert "1 salon(s) public(s) ajouté(s) aux salons par défaut (1 → 2)" in t
