"""29/10/2026 — « ils vont dire bonjour à tous les messages… juste mettre plein de gifs… c'est pas construit » : un
message compte s'il est construit (qualite.py) ; les cadeaux s'en servent, et le disent dans « Mes stats »."""
from __future__ import annotations

import qualite as Q


def test_Q1_ce_qui_ne_compte_pas():
    j = Q.Juge()
    assert j.juger(1, "https://tenor.com/view/drole-gif-1", 0) == ("vide", 0), "un GIF seul"
    assert j.juger(1, "😂😂 <:pirate:123>", 5) == ("vide", 0), "des émojis seuls"
    assert j.juger(1, "Bonjour !", 10) == ("", 1), "le premier bonjour de la journée compte"
    for x in ("salut tout le monde", "cc", "bonjourrrr", "yo les gars", "gm"):
        assert j.juger(1, x, 20)[0] == "salut", x
    assert j.juger(1, "Bonjour", 10 + Q.SALUT_S) == ("", 1), "le lendemain : de nouveau"
    assert j.juger(1, "gg bien joué pour le boss", 30) == ("", 1)
    assert j.juger(1, "GG bien joué pour le boss !!", 40) == ("doublon", 0), "le même, à la ponctuation près"
    assert j.juger(1, "gg bien joué pour le boss", 40 + Q.DOUBLON_S) == ("", 1), "2 heures plus tard : il compte"


def test_Q2_ce_qui_compte_et_la_discussion_compte_double():
    j = Q.Juge()
    assert j.juger(1, "je cherche un équipage pour le raid de ce soir", 0) == ("", 1)
    assert j.juger(1, "merci", 10) == ("", 1), "un mot normal compte"
    assert j.juger(1, "oui je suis d'accord avec toi pour demain", 20, reponse=True) == ("", 2)
    assert j.juger(1, "ok", 30, reponse=True) == ("", 1), "une réponse d'un mot ne compte pas double"
    assert j.juger(2, "je cherche un équipage pour le raid de ce soir", 40) == ("", 1), "chacun sa mémoire"


def test_Q3_le_plafond_de_l_heure():
    j = Q.Juge()
    for k in range(Q.PLAFOND_HEURE):
        assert j.juger(1, f"message utile numéro {k} pour la discussion", k) == ("", 1)
    assert j.juger(1, "encore un message utile", 100)[0] == "plafond"
    assert j.juger(1, "une heure plus tard ça repart", 3700) == ("", 1)


def test_Q4_branche_dans_les_cadeaux():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "cadeaux.py").read_text(encoding="utf-8")
    assert "raison, poids = _juge.juger(cle, texte, t, reponse=reponse," in src and "réveillé pour le cadeau" in src
    assert 'tr("ecartes", langue, n=ecartes)' in src and "non comptés" in src


def test_QUALITE_ping_pong_a_deux_courts_ne_comptent_plus_vraies_phrases_si():
    j = Q.Juge()
    t = 0.0
    for i in range(14):
        r, _p = j.juger((1, 1 + i % 2), f"mdr {i}", t, salon=9, cible=2 - i % 2, reponse=True)
        t += 4
    assert r == "duo"
    r, p = j.juger((1, 1), "je pense qu'on devrait refaire le donjon demain soir avec toute la team", t, salon=9,
                   cible=2, reponse=True)
    assert r == "" and p == 1      # compte, mais pas double dans un duo fermé


def test_QUALITE_discussion_a_plusieurs_courts_comptent():
    j = Q.Juge()
    for i in range(15):
        assert j.juger((1, 1 + i % 3), f"ouais {i}", i * 4.0, salon=9)[0] == ""


def test_QUALITE_bonus_double_plafonne_vers_la_meme_personne():
    j = Q.Juge()
    poids = [j.juger((1, 1), f"réponse numéro {i} avec une vraie phrase", i * 60.0, reponse=True, cible=2)[1]
             for i in range(12)]
    assert poids[:10] == [2] * 10 and poids[10:] == [1, 1]
