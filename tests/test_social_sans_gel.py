"""Le stockage des réseaux sociaux ne gèle plus le bot (29/09/2026).

MESURÉ — journal Railway du 29/09, 09:37 UTC :
    [STALL] ⚠️ boucle asyncio bloquée depuis 44.5s
    discord.gateway: heartbeat blocked for more than 50 seconds
Pile : `_cleanup_loop → cleanup_all → cleanup_announcement → _save_anns →
_write_json → path.write_text → io.open`. Une fonction `async` qui écrivait sur
le disque SUR la boucle : quand le volume a calé, tout le bot a calé — la
modération comprise.

Ces tests n'appellent jamais le réseau.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

import social_media as sm


def _avec_horloge(fabrique):
    """Lance `fabrique()` en comptant les tours d'une horloge à 10 ms : une
    boucle gelée ne compte plus."""
    async def main():
        tours = 0
        fini = asyncio.Event()

        async def horloge():
            nonlocal tours
            while not fini.is_set():
                await asyncio.sleep(0.01)
                tours += 1

        h = asyncio.create_task(horloge())
        res = await fabrique()
        fini.set()
        await h
        return tours, res
    return asyncio.run(main())


def test_W1_une_ecriture_lente_ne_gele_plus_la_boucle(tmp_path, monkeypatch):
    vrai = sm._ecrire_json_bloquant

    def disque_lent(path, texte):
        time.sleep(0.4)
        vrai(path, texte)

    monkeypatch.setattr(sm, "_ecrire_json_bloquant", disque_lent)
    p = tmp_path / "1_anns.json"
    tours, _ = _avec_horloge(lambda: sm._write_json(p, [{"titre": "Été"}]))
    assert tours >= 10, f"la boucle a calé pendant l'écriture ({tours} tours)"
    assert json.loads(p.read_text(encoding="utf-8")) == [{"titre": "Été"}]


def test_W2_une_lecture_lente_non_plus(tmp_path, monkeypatch):
    p = tmp_path / "1_subs.json"
    p.write_text('[{"x": "é"}]', encoding="utf-8")
    vrai = sm._lire_json_bloquant

    def disque_lent(path):
        time.sleep(0.4)
        return vrai(path)

    monkeypatch.setattr(sm, "_lire_json_bloquant", disque_lent)
    tours, res = _avec_horloge(lambda: sm._read_json(p))
    assert tours >= 10 and res == [{"x": "é"}]
    assert asyncio.run(sm._read_json(tmp_path / "absent.json")) is None


def test_W3_un_arret_en_pleine_ecriture_ne_perd_pas_les_annonces(tmp_path, monkeypatch):
    """Chaque déploiement arrête un conteneur. Arrêté au milieu d'un
    `write_text`, l'ancien code laissait un JSON tronqué, lu comme « rien » :
    toutes les annonces du serveur oubliées."""
    p = tmp_path / "1_anns.json"
    asyncio.run(sm._write_json(p, [{"ancien": True}]))

    def coupure(*_a, **_k):
        raise OSError("conteneur arrêté")

    monkeypatch.setattr(sm.os, "replace", coupure)
    with pytest.raises(OSError):
        asyncio.run(sm._write_json(p, [{"neuf": True}]))
    monkeypatch.undo()
    assert asyncio.run(sm._read_json(p)) == [{"ancien": True}]


class _Adaptateur(sm.PlatformAdapter):
    platform = sm.Platform.YOUTUBE

    def __init__(self, actifs):
        self.actifs = set(actifs)

    async def fetch_posts(self, handle):
        return []

    async def is_post_active(self, post):
        return post.post_id in self.actifs


def _annonce(gid, pid):
    return sm.Announcement(
        sub_id="s", post_id=pid, platform=sm.Platform.YOUTUBE, handle="h",
        guild_id=gid, discord_channel_id=1, discord_message_id=2, post_url="u",
        post_title="t", post_type=sm.PostType.VIDEO,
        posted_at="2026-09-29T00:00:00+00:00", last_checked_at="")


@pytest.fixture
def ecritures(tmp_path, monkeypatch):
    monkeypatch.setattr(sm, "DATA_DIR", tmp_path)
    vues = []
    vrai = sm._ecrire_json_bloquant

    def compte(path, texte):
        vues.append(path.name)
        vrai(path, texte)

    monkeypatch.setattr(sm, "_ecrire_json_bloquant", compte)
    return vues


def _gestionnaire(actifs, n=5):
    async def supprimer(_ann):
        return True

    m = sm.SocialMediaManager(delete_callback=supprimer)
    m.register_adapter(_Adaptateur(actifs))
    m._anns = {1: {a.unique_key: a for a in (_annonce(1, f"p{i}")
                                             for i in range(1, n + 1))}}
    return m


def test_W4_un_tour_de_nettoyage_ecrit_une_fois_par_serveur(ecritures, tmp_path):
    """Avant : une réécriture complète du fichier PAR annonce vérifiée — c'est
    dans l'une d'elles que le bot a calé 50 s."""
    m = _gestionnaire(actifs={"p1", "p2", "p3", "p4", "p5"})
    assert asyncio.run(m.cleanup_all()) == {1: 0}
    assert ecritures == ["1_anns.json"]
    sauve = json.loads((tmp_path / "1_anns.json").read_text(encoding="utf-8"))
    assert len(sauve) == 5 and all(a["last_checked_at"] for a in sauve), \
        "les dates de vérification sont bien gardées"


def test_W5_une_suppression_se_note_tout_de_suite(ecritures, tmp_path):
    """Une annonce supprimée de Discord est notée sans attendre la fin du tour :
    un redémarrage au milieu ne doit pas la faire supprimer deux fois."""
    m = _gestionnaire(actifs={"p1", "p2", "p3", "p4"})
    assert asyncio.run(m.cleanup_all()) == {1: 1}
    assert ecritures == ["1_anns.json", "1_anns.json"]
    sauve = json.loads((tmp_path / "1_anns.json").read_text(encoding="utf-8"))
    assert [a["deleted"] for a in sauve] == [False, False, False, False, True]


def test_W6_cleanup_announcement_seul_sauve_toujours(ecritures):
    """Appelée seule, elle garde son comportement : elle sauvegarde."""
    m = _gestionnaire(actifs={"p1"}, n=1)
    (ann,) = m._anns[1].values()
    asyncio.run(m.cleanup_announcement(ann))
    assert ecritures == ["1_anns.json"]


def test_W7_un_tour_de_nettoyage_qui_plante_se_dit(monkeypatch):
    """`except: pass` rendait un tour planté invisible (même règle que
    `_poll_loop`, 18/07)."""
    import diag
    vus = []
    monkeypatch.setattr(diag, "error", lambda *a, **k: vus.append(a))
    m = sm.SocialMediaManager()

    async def boum():
        m._stop_event.set()
        raise RuntimeError("disque")

    m.cleanup_all = boum
    asyncio.run(m._cleanup_loop())
    assert vus and vus[0][:2] == ("social", "cleanup_loop")
