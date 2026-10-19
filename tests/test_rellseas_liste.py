"""19/10/2026 : « savoir combien il y a de personnes à l'intérieur, les lister, les copier avec
leur ID au propre… un fichier correct avec les noms bien rangés devant leur ID… et devant eux
leur activité, actifs ou pas actifs »."""
from __future__ import annotations

import asyncio
import datetime as dt

import aiosqlite
import discord

import activite
import activite_calendrier as cal
import rellseas_panneau as R
from conftest_discord import Obj


def _membre(uid, nom, pseudo, arrive_il_y_a=200):
    return Obj(id=uid, display_name=nom, name=pseudo, bot=False, mention=f"<@{uid}>",
               joined_at=cal.maintenant() - dt.timedelta(days=arrive_il_y_a))


def _il_y_a(n):
    return cal.jour(cal.maintenant() - dt.timedelta(days=n))


def test_R1_tri_par_statut_puis_nom_et_identifiants_alignes():
    ms = [_membre(98765432109876543, "🔥 Kaïto le Pirate des Mers du Sud", "kaito"),
          _membre(123456789012345678, "zoé", "zoe"), _membre(111, "Alix", "alix"),
          _membre(222, "李小龍", "bruce", 1)]
    mes = {98765432109876543: {"jugeable": True, "silence": 9, "presents": 0, "fenetre": 7},
           123456789012345678: {"jugeable": True, "silence": 0, "presents": 5, "fenetre": 7,
                                "dernier": cal.jour()},
           111: {"jugeable": True, "silence": 0, "presents": 6, "fenetre": 7, "dernier": _il_y_a(1)},
           222: {"jugeable": False, "silence": 0, "presents": 0, "fenetre": 1}}
    lignes = R.lignes_clan(ms, mes)
    assert [x["statut"] for x in lignes] == ["Actif", "Actif", "Absent", "Trop récent"]
    assert [x["nom"] for x in lignes[:2]] == ["Alix", "zoé"]
    assert lignes[0]["derniere"] == "hier" and lignes[1]["derniere"] == "aujourd'hui"
    texte = R.texte_fichier("GoRP SEA", "Rell Seas", lignes, cal.maintenant())
    corps = [l for l in texte.splitlines() if l[:1].isdigit()]
    assert len(corps) == 4
    colonnes = set()
    for l, x in zip(corps, lignes):
        avant = l[:l.index(str(x["id"]))]
        colonnes.add(R.largeur(avant))
    assert len(colonnes) == 1, "chaque identifiant commence à la même colonne, émojis compris"
    assert "4 membre(s)" in texte and "Actifs 2" in texte


def test_R2_mesure_groupee_identique_a_la_mesure_par_membre(tmp_path, monkeypatch):
    chemin = str(tmp_path / "a.db")
    conf = {"activite_observe_depuis": _il_y_a(60), "activite_fenetre": 7}

    async def cfg(_g):
        return conf

    async def db_set(_g, k, v):
        conf[k] = v
    monkeypatch.setattr(activite, "_cfg", cfg)
    monkeypatch.setattr(activite, "_db_set", db_set)
    monkeypatch.setattr(activite, "_get_db", lambda: aiosqlite.connect(chemin))
    ms = [_membre(1, "A", "a"), _membre(2, "B", "b"), _membre(3, "C", "c", 2), _membre(4, "D", "d")]

    async def scenario():
        await activite.init_db()
        async with aiosqlite.connect(chemin) as db:
            for uid, jours in ((1, (1, 2, 3, 5, 9)), (2, (8,)), (3, (1,)), (9, (1, 2))):
                for n in jours:
                    await db.execute("INSERT INTO activite_jours VALUES(1,?,?, 'm')", (uid, _il_y_a(n)))
            await db.commit()
        groupe = await activite.presences(1, ms, conf)
        seuls = {m.id: await activite.presence(1, m, conf) for m in ms}
        return groupe, seuls
    groupe, seuls = asyncio.run(scenario())
    for m in ms:
        attendu = dict(seuls[m.id])
        assert groupe[m.id] == attendu, m.id
    assert groupe[1]["presents"] == 4 and groupe[2]["presents"] == 0
    assert groupe[4]["dernier"] is None and groupe[3]["jugeable"] is False


def test_R3_le_bouton_est_enregistre_et_affiche_le_compte():
    v = R.RellseasGestionV2.squelette()
    ids = [c.custom_id for c in v.walk_children() if hasattr(c, "custom_id")]
    assert "rellseas_g_liste" in ids
    rangees = [c for c in v.walk_children() if isinstance(c, discord.ui.ActionRow)]
    assert all(len(r.children) <= 5 for r in rangees)


def test_R4_le_clic_envoie_l_apercu_et_le_fichier_complet(monkeypatch):
    role = Obj(id=5, name="Rell Seas", mention="<@&5>",
               members=[_membre(123456789012345678, "GoRipe", "goripe"), _membre(7, "Bot", "bot")])
    role.members[1].bot = True
    journal, envois = [], []
    g = Obj(id=1, name="GoRP SEA", get_role=lambda rid: role if rid == 5 else None,
            get_channel=lambda cid: Obj(send=lambda t: journal.append(t)) if cid == 9 else None)

    async def cfg(_g):
        return {R.CLE_ROLE_CIBLE: 5}

    async def mesurer_groupe(_gid, membres):
        assert [m.id for m in membres] == [123456789012345678], "les bots ne comptent pas"
        return {123456789012345678: {"jugeable": True, "silence": 0, "presents": 7, "fenetre": 7,
                                     "dernier": cal.jour()}}

    async def defer(**_k):
        return None

    async def suivi(content=None, **kw):
        envois.append(kw)

    async def rien(*a, **k):
        return None
    monkeypatch.setattr(R, "_cfg", cfg)
    monkeypatch.setattr(R, "_mesurer_groupe", mesurer_groupe)
    monkeypatch.setattr(R.RellseasGestionV2, "_journal", rien)
    i = Obj(guild=g, user=Obj(id=3, mention="<@3>"), response=Obj(defer=defer),
            followup=Obj(send=suivi))
    asyncio.run(R.RellseasGestionV2()._cb_liste(i))
    kw = envois[0]
    assert kw["ephemeral"] is True
    contenu = kw["file"].fp.getvalue().decode("utf-8")
    assert "GoRipe" in contenu and "123456789012345678" in contenu and "Actif" in contenu
    fichiers = [c for c in kw["view"].walk_children() if isinstance(c, discord.ui.File)]
    assert fichiers and fichiers[0].media.url == f"attachment://{kw['file'].filename}"
    textes = " ".join(c.content for c in kw["view"].walk_children()
                      if isinstance(c, discord.ui.TextDisplay))
    assert "1 membre(s)" in textes and "123456789012345678" in textes
