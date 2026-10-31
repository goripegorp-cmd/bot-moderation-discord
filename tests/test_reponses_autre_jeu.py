"""31/10/2026, le fondateur : « il a demandé de l'aide pour un jeu qui s'appelle Ultimatum… tu lui as répondu qu'il peut
demander de l'aide sur RELL Seas, Clover ou créer un ticket. Ça répond pas à sa question »."""
from pathlib import Path

import faq
import reponses_auto as R

SRC = (Path(__file__).resolve().parent.parent / "reponses_auto.py").read_text(encoding="utf-8")


def test_J1_un_autre_jeu_est_reconnu():
    assert R.autre_jeu("j'ai commencé Ultimatum sur Roblox, quelqu'un peut m'aider ?") == "Ultimatum"
    assert R.autre_jeu("je joue a Blox Fruits sur roblox aidez moi") == "Blox Fruits"
    assert R.autre_jeu("j'ai commencé Ultimatum, comment on fait ?") == "Ultimatum"


def test_J2_jamais_nos_jeux_ni_une_phrase_ordinaire():
    for t in ("aidez moi sur rell seas", "j'ai commencé rell seas sur roblox, de l'aide ?", "je joue à Clover RPG aide",
              "j'ai commencé hier, aide moi", "aide moi svp", "je joue a rien aide", "je joue au jeu sur roblox aide"):
        assert R.autre_jeu(t) == "", t


def test_J3_la_reponse_ne_propose_ni_nos_jeux_ni_un_ticket():
    assert 'genre, sujet = "autre", "autre_jeu"' in SRC
    i = SRC.index('elif genre == "autre":')
    bloc = SRC[i:i + 900]
    assert "reponses.autre_jeu.texte" in bloc and "ticket" not in bloc and "_jeux_aide" not in bloc
    assert "not lieu and not faq.jeux_nommes(" in SRC        # jamais dans le salon d'un de nos jeux
    v = faq.vue_reponse("T", "corps", [])                      # sans salon Discussion : pas de rangée de boutons vide
    assert len(v.children) == 1
