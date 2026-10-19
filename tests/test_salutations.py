"""19/10/2026 : « quand quelqu'un dit bonjour, un emoji qui apparaît en dessous de lui avec une main…
dans les salons où l'everyone peut écrire, sauf les salons d'annonces ou autres »."""
from __future__ import annotations

import asyncio

import discord

import salutations as S
from conftest_discord import Obj


def test_A1_ce_qui_est_une_salutation():
    for texte in ("Bonjour", "bonjour tout le monde !", "Salut <@1234567890123>", "slt", "Coucouuu", "HELLO !!",
                  "Bonsoir à tous", "re", "cc les gens", "saluuuut la team", "Hey", "bjr", "yo",
                  "Bonne nuit", "bonne nuit tout le monde", "BNN", "bnn tlm", "bn", "Bonne soirée !", "bns",
                  "Bonne journée à vous", "bnj", "à plus", "A+", "@+ les gars", "a demain", "à toute", "bye",
                  "bye bye", "ciao", "tchao", "good night", "gn", "bonne nuittt", "Bon aprem !"):
        assert S.est_salutation(texte), texte
    for texte in ("je voulais dire salut", "c'est bon", "regarde ça", "re-regarde la vidéo stp maintenant les gars",
                  "Bonjour " + "x" * 90, "", "!!!", "Salutations distinguées", "bn et toi ?", "bonne idée",
                  "à mon avis non", "bon ça marche", "a faire demain"):
        assert not S.est_salutation(texte), texte


class Salon:
    def __init__(self, ecrire=True, reagir=True):
        self.id, self._ecrire, self._reagir = 5, ecrire, reagir

    def permissions_for(self, cible):
        if getattr(cible, "id", 0) == 1:
            return Obj(view_channel=True, send_messages=self._ecrire)
        return Obj(add_reactions=self._reagir)


class Message:
    def __init__(self, texte, salon, auteur=7, bot=False):
        self.content, self.channel, self.webhook_id, self.reactions = texte, salon, None, []
        self.author = Obj(id=auteur, bot=bot)
        self.guild = Obj(id=1, default_role=Obj(id=1), me=Obj(id=999))

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


def test_A2_un_main_qui_salue_seulement_ou_tout_le_monde_ecrit():
    S._derniers.clear()
    ouvert = Salon()
    m = Message("Bonjour à tous !", ouvert)
    assert asyncio.run(S.sur_message(m)) and m.reactions == ["👋"]
    encore = Message("re bonjour", ouvert)
    assert not asyncio.run(S.sur_message(encore)) and not encore.reactions, "une fois toutes les 10 minutes par membre"
    autre = Message("salut", ouvert, auteur=8)
    assert asyncio.run(S.sur_message(autre)), "chacun son 👋"
    annonce = Message("Bonjour", Salon(ecrire=False), auteur=9)
    assert not asyncio.run(S.sur_message(annonce)) and not annonce.reactions, "pas dans les annonces"
    sans_droit = Message("Bonjour", Salon(reagir=False), auteur=10)
    assert not asyncio.run(S.sur_message(sans_droit))
    robot = Message("Bonjour", ouvert, auteur=11, bot=True)
    assert not asyncio.run(S.sur_message(robot))


def test_A3_message_retire_entre_temps():
    S._derniers.clear()
    m = Message("coucou", Salon())

    async def retire(_e):
        raise discord.NotFound(Obj(status=404, reason="x"), "parti")
    m.add_reaction = retire
    assert asyncio.run(S.sur_message(m)) is False
