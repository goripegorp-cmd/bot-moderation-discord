"""20/10/2026 (audit 2 #16) : la copie exacte du pseudo d'un membre du staff passait ; la liste du
staff n'etait construite qu'au demarrage."""
from __future__ import annotations

import asyncio

import impersonation_detector as I
from conftest_discord import Obj, base


def _perms(staff):
    return Obj(administrator=staff, manage_guild=False, manage_messages=False, kick_members=False,
               ban_members=False)


def _membre(uid, nom, staff, guilde):
    return Obj(id=uid, display_name=nom, name=nom.lower(), avatar=None, bot=False, guild=guilde,
               guild_permissions=_perms(staff), display_avatar=Obj(key=f"a{uid}"))


def test_U1_copie_exacte_et_homoglyphes_reperes_nom_court_ignore(tmp_path):
    get_db, *_ = base(tmp_path)
    I.setup(None, get_db, None, {})
    g = Obj(id=1, owner_id=0, members=[])
    g.members += [_membre(10, "GoRipe", True, g), _membre(11, "Al", True, g)]
    intrus = _membre(20, "x", False, g)

    async def scenario():
        await I.init_db()
        await I.refresh_staff_index(g)
        return [await I._check_name(intrus, nom) for nom in ("GoRipe", "G0Ripe", "Al", "promenade")]
    copie, homoglyphe, court, rien = asyncio.run(scenario())
    assert copie["match_type"] == "name_similarity" and copie["score"] == 1.0
    assert homoglyphe["target_staff_id"] == 10
    assert court is None and rien is None


def test_U2_un_nouveau_membre_du_staff_est_protege_sans_redemarrage(tmp_path):
    get_db, *_ = base(tmp_path)
    I.setup(None, get_db, None, {})
    g = Obj(id=1, owner_id=0, members=[])
    avant = _membre(30, "Moderatrice", False, g)
    apres = _membre(30, "Moderatrice", True, g)

    async def scenario():
        await I.init_db()
        g.members[:] = [avant]
        await I.refresh_staff_index(g)
        vide = await I._load_staff_index(1)
        g.members[:] = [apres]
        await I.on_member_update_hook(avant, apres)  # elle entre dans le staff
        return vide, await I._load_staff_index(1)
    vide, protege = asyncio.run(scenario())
    assert vide == [] and [s["user_id"] for s in protege] == [30]


def test_U3_l_historique_des_comptes_compromis_oublie_les_silencieux(monkeypatch):
    """Audit 2 #20 : une entree par membre ayant un jour ecrit, a vie."""
    import compromised_detector as C
    horloge = [1000.0]
    monkeypatch.setattr(C.time, "time", lambda: horloge[0])
    C._history_cache.clear()
    for uid in range(600):
        C._record_message(1, uid, 5, "salut")
    horloge[0] += 400
    C._record_message(1, 9999, 5, "encore la")
    assert list(C._history_cache) == [(1, 9999)]
