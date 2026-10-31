"""31/10/2026, le fondateur : « certains arrivent encore à envoyer des gifs avec des insultes… regarde comment est
formulé le lien (klipy.com/gifs/pd-kumpel-pd-1)… sois beaucoup plus attentif »."""
from pathlib import Path

import insult_filter as F

RACINE = Path(__file__).resolve().parent.parent


def test_A1_pd_et_ses_deguisements_sont_de_la_haine():
    for t in ("pd kumpel pd 1", "sale pd", "t'es un pd", "p.d", "p-d", "p d", "p*d", "pds", "pd1", "pede",
              "sale pedale", "sale tapette", "sale gay", "negro"):
        assert F.scan(t, lg="fr")[0] == 3, t
    assert F.scan("pedo", lg="fr")[0] == 2


def test_A2_jamais_les_mots_innocents():
    for t in ("speed run", "updated", "le gps", "pdf du guide", "top départ", "group d", "ipd", "stop dabbing",
              "je fais du vélo, la pédale est cassée", "une tapette à mouches", "je suis gay et fier", "mon pote est gay"):
        assert F.scan(t, lg="fr")[0] == 0, t


def test_A3_le_lien_d_un_gif_insultant_compte_comme_une_infraction():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "await sanction(msg.author, 'delete', 0, f\"GIF ou lien insultant — « {_sterm} »\", msg.guild)" in src
