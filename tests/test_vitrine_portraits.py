"""28/10/2026 — le fondateur : « quand on regarde dans l'équipage… ça affiche pas les images des Discord sur le lien. Il
y a des trucs qui sont cachés ». Une affiche sans portrait Roblox montre l'avatar Discord de son membre (copié et servi
par le serveur, jamais chargé de Discord par la page) ; les portraits Roblox manquants se prennent tout seuls ; les
métiers de la vitrine restent ouverts jusqu'à trente affiches."""
from __future__ import annotations

import asyncio
from pathlib import Path

import affiches
import site_vitrine as V
import tableau

RACINE = Path(__file__).resolve().parent.parent


def test_V1_l_avatar_discord_garde_est_une_image_du_site(tmp_path, monkeypatch):
    monkeypatch.setattr(tableau, "RACINE_DONNEES", tmp_path)
    assert tableau._chemin_media("discord/123456789012345678") == (None, None)
    d = tableau.dossier_site("avatars_discord")
    (d / "123456789012345678.webp").write_bytes(b"RIFF0000WEBP")
    chemin, typ = tableau._chemin_media("discord/123456789012345678")
    assert chemin is not None and typ == "image/webp"
    assert V._avatar_discord_age(123456789012345678) is not None
    for faux in ("discord/abc", "discord/../x", "discord/12"):
        assert tableau._chemin_media(faux) == (None, None), faux


class _Asset:
    def replace(self, **_k):
        return self

    async def read(self):
        raise RuntimeError("Discord injoignable")


def test_V2_un_avatar_illisible_ne_casse_rien(tmp_path, monkeypatch):
    monkeypatch.setattr(tableau, "RACINE_DONNEES", tmp_path)
    membre = type("M", (), {"display_avatar": _Asset()})()
    g = type("G", (), {"id": 1, "get_member": lambda self, uid: membre})()
    V._AVATARS_EN_COURS.add((1, 42))
    asyncio.run(V._copier_avatars(g, [42]))
    assert (1, 42) not in V._AVATARS_EN_COURS, "le membre redevient candidat à la prochaine construction"


def test_V3_le_portrait_roblox_sans_pseudo_valide_n_appelle_pas_roblox(monkeypatch):
    appels = []

    async def route(*a, **k):
        appels.append(a)
        return 200, {"roblox_id": "1", "avatar": "x"}
    monkeypatch.setattr(affiches, "_route_avatar", route)
    assert asyncio.run(affiches.completer_portrait(1, {"id": "a", "roblox_nom": "pas valide !", "roblox_id": 0})) is False
    assert not appels


def test_V4_les_metiers_de_la_vitrine_restent_ouverts():
    mur = (RACINE / "site" / "equipage_mur.js").read_text(encoding="utf-8")
    assert "ouvertes + n <= 30" in mur
    src = (RACINE / "site_vitrine.py").read_text(encoding="utf-8")
    assert 'image(f"discord/{uid}")' in src and "_prendre_portraits(g, lot_r)" in src
