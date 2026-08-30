"""Les ACTUALITÉS Roblox — le flux qui ne pouvait pas démarrer.

LE CONSTAT DU PROPRIÉTAIRE (16/08)
    « Aucun de tes systèmes concernant les news ne sont annoncés dans le
    serveur. Rien n'est annoncé, absolument rien. »

LA CAUSE, ET ELLE ÉTAIT STRUCTURELLE
`roblox_news_enabled` n'était écrit NULLE PART — ni bouton, ni commande.
`roblox_news.actif()` rendait donc toujours faux, `guildes_news` restait vide,
et le bloc actualité de la boucle ne s'exécutait JAMAIS. Le salon se réglait,
la santé se calculait, et rien ne sortait.

Vérifié le jour du constat : 5 sources sur 5 en HTTP 200, 29 billets frais.
Le contenu était là. L'interrupteur n'existait pas.

C'est le 5ᵉ des sept cas du briefing : « clé de config sans interface donc
toujours à 0 ». Ces tests l'enferment, lui et ce qui l'entourait :
la santé jamais affichée, le bouton « Relever » qui ignorait ce flux, le
bouton ♻️ qui n'effaçait que la moitié des marques, la boucle muette.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import roblox_news as news
import roblox_panneau as panneau

RACINE = Path(__file__).resolve().parent.parent
SRC_BOT = (RACINE / "bot.py").read_text(encoding="utf-8")
SRC_PAN = (RACINE / "roblox_panneau.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. L'interrupteur existe, et quelqu'un l'écrit
# ═══════════════════════════════════════════════════════════════════════════════

def test_quelquun_ecrit_enfin_roblox_news_enabled():
    """LE défaut. Une clé que personne n'écrit vaut toujours sa valeur par
    défaut — ici False — et tout ce qui en dépend est mort."""
    assert '"roblox_news_enabled", allume' in SRC_PAN, (
        "aucun bouton n'écrit roblox_news_enabled : les actualités ne "
        "peuvent jamais s'allumer")


def test_le_bouton_des_actualites_est_bien_dans_le_panneau():
    assert "rblx_toggle_news" in SRC_PAN
    assert "_cb_toggle_news" in SRC_PAN


@pytest.mark.asyncio
async def test_actif_exige_interrupteur_ET_salon(monkeypatch):
    async def _cfg_on(gid):
        return {"roblox_news_enabled": True, "roblox_news_salon": 42}

    async def _cfg_sans_salon(gid):
        return {"roblox_news_enabled": True, "roblox_news_salon": 0}

    async def _cfg_eteint(gid):
        return {"roblox_news_enabled": False, "roblox_news_salon": 42}

    news.setup(get_db=None, cfg=_cfg_on, db_set=None, log=lambda *a: None)
    assert await news.actif(1) is True
    news.setup(get_db=None, cfg=_cfg_sans_salon, db_set=None, log=lambda *a: None)
    assert await news.actif(1) is False
    news.setup(get_db=None, cfg=_cfg_eteint, db_set=None, log=lambda *a: None)
    assert await news.actif(1) is False


@pytest.mark.asyncio
async def test_actif_ne_tombe_pas_sur_une_config_partielle():
    """Fail-closed sur le doute : une clé absente = éteint, pas une exception.
    Ce KeyError faisait tomber tout le panneau /configure → Veille Roblox."""
    async def _cfg(gid):
        return {"roblox_news_salon": 42}   # sans roblox_news_enabled

    news.setup(get_db=None, cfg=_cfg, db_set=None, log=lambda *a: None)
    assert await news.actif(1) is False


# ═══════════════════════════════════════════════════════════════════════════════
#  2. L'amorce laisse passer la semaine écoulée
# ═══════════════════════════════════════════════════════════════════════════════

def _billet(tid: int, jours: int) -> dict:
    from datetime import datetime, timedelta, timezone
    quand = datetime.now(timezone.utc) - timedelta(days=jours)
    return {"topic_id": tid, "titre": f"billet {tid}", "domaine": "Annonces",
            "cree_le": quand.isoformat(), "extrait": None, "tags": []}


@pytest.mark.asyncio
async def test_lamorce_absorbe_le_vieux_et_laisse_sortir_la_semaine(monkeypatch):
    """La première version absorbait TOUT : le propriétaire allumait et
    attendait le prochain billet du forum pour voir une seule fiche."""
    marques = []

    async def _relever(src, forcer=False):   # même signature que le vrai
        return {"billets": [_billet(1, 2), _billet(2, 6), _billet(3, 12),
                            _billet(4, 25)], "code": 200}

    async def _marquer(gid, tid):
        marques.append(tid)

    async def _db_set(gid, k, v):
        return None

    async def _dodo(_):
        return None

    monkeypatch.setattr(news, "relever", _relever)
    monkeypatch.setattr(news, "marquer_publie", _marquer)
    monkeypatch.setattr(news, "_db_set", _db_set)
    monkeypatch.setattr(news.asyncio, "sleep", _dodo)

    n = await news.amorcer(1)

    #  5 sources × 2 billets vieux (12 j et 25 j) = 10 absorbés ;
    #  les billets de 2 et 6 jours restent libres.
    assert n == 2 * len(news.SOURCES)
    assert set(marques) == {3, 4}, "seuls les billets > 7 jours sont absorbés"
    assert news.AMORCE_GARDE_JOURS == 7


@pytest.mark.asyncio
async def test_oublier_publies_existe_pour_les_actualites(monkeypatch):
    """Le bouton ♻️ disait « tout republier » et n'effaçait que les articles."""
    import contextlib

    class _Cur:
        """⚠️ aiosqlite `execute()` rend un objet qui est À LA FOIS awaitable
        (`await db.execute(...)`) ET gestionnaire de contexte (`async with
        db.execute(...) as cur`). Une doublure qui n'a que la moitié fait
        échouer le DELETE, avalé par le try — et le test accuse le code.
        Piège n°6 du dépôt : un faux objet porte TOUT ce que le vrai porte."""

        async def fetchone(self):
            return (3,)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __await__(self):
            async def _rien():
                return self
            return _rien().__await__()

    class _DB:
        def __init__(self):
            self.requetes = []

        def execute(self, q, p=()):
            self.requetes.append(q)
            return _Cur()

        async def commit(self):
            return None

    db = _DB()

    @contextlib.asynccontextmanager
    async def _get_db():
        yield db

    news.setup(get_db=_get_db, cfg=None, db_set=None, log=lambda *a: None)
    n = await news.oublier_publies(1)

    assert n == 3
    assert any("DELETE FROM roblox_news_publies" in q for q in db.requetes)


def test_le_bouton_republier_efface_aussi_les_actualites():
    assert "news.oublier_publies(self.g.id)" in SRC_PAN


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le bouton « Relever maintenant » relève AUSSI les actualités
# ═══════════════════════════════════════════════════════════════════════════════

def test_relever_maintenant_passe_par_les_actualites():
    """Sans ça, le bouton disait « relevé réussi » et le forum restait muet."""
    assert "await self._relever_actualites()" in SRC_PAN
    assert "async def _relever_actualites" in SRC_PAN


class _FauxSalon:
    def __init__(self, cid=14):
        self.id = cid
        self.name = "actus"
        self.mention = f"<#{cid}>"


class _FauxGuild:
    id = 1
    name = "S"
    icon = None

    def __init__(self, salon=None):
        self._salon = salon

    def get_channel(self, cid):
        return self._salon if (self._salon and cid) else None


class _FauxUser:
    id = 1
    display_name = "p"


@pytest.mark.asyncio
async def test_relever_actualites_dit_quand_elles_sont_eteintes():
    async def _cfg(gid):
        return {"roblox_news_enabled": False, "roblox_news_salon": 14}

    news.setup(get_db=None, cfg=_cfg, db_set=None, log=lambda *a: None)
    panneau.setup(db_set=None, webhook_send=None, log=lambda *a: None)

    vue = panneau.RobloxPanelV2(_FauxUser(), _FauxGuild(_FauxSalon()))
    txt = await vue._relever_actualites()

    assert "éteintes" in txt
    assert "rien n'a été relevé" in txt.lower()


@pytest.mark.asyncio
async def test_relever_actualites_dit_quand_le_salon_manque():
    async def _cfg(gid):
        return {"roblox_news_enabled": True, "roblox_news_salon": 0}

    news.setup(get_db=None, cfg=_cfg, db_set=None, log=lambda *a: None)
    panneau.setup(db_set=None, webhook_send=None, log=lambda *a: None)

    vue = panneau.RobloxPanelV2(_FauxUser(), _FauxGuild(None))
    txt = await vue._relever_actualites()

    assert "aucun salon" in txt.lower()



def _file_en_memoire(monkeypatch, news):
    """Une file d'attente en memoire, avec TOUTES les protections de la vraie.

    ⚠️ ELLE DOIT PORTER CE QUE PORTE LA VRAIE : unicite sur (guild, topic),
    reservation par jeton d'essais, marquage apres envoi, comptage des echecs.
    Une doublure plus permissive que l'original ferait passer un test sur du
    code casse — c'est exactement ce qui a laisse passer la regression des
    identifiants textuels.
    """
    lignes = {}
    suivant = {"id": 0}

    async def _enfiler(gid, billet):
        tid = str(billet.get("topic_id") or "").strip()
        if not tid or (gid, tid) in lignes:
            return False
        suivant["id"] += 1
        lignes[(gid, tid)] = {"id": suivant["id"], "billet": billet,
                              "essais": 0, "envoye": False}
        return True

    async def _a_envoyer(gid, limite=5):
        out = [dict(v) for k, v in sorted(lignes.items(), key=lambda x: x[1]["id"])
               if k[0] == gid and not v["envoye"] and v["essais"] < 5]
        return out[:limite]

    async def _reserver(lid, essais_vus):
        for v in lignes.values():
            if v["id"] == lid and not v["envoye"] and v["essais"] == essais_vus:
                v["essais"] = essais_vus + 1
                return True
        return False

    async def _marquer_envoyee(lid, message_id=None):
        for v in lignes.values():
            if v["id"] == lid:
                v["envoye"] = True
                return True
        return False

    async def _noter_echec(lid, motif):
        for v in lignes.values():
            if v["id"] == lid:
                v["essais"] += 1

    async def _purger_file():
        return 0

    monkeypatch.setattr(news, "enfiler_actu", _enfiler)
    monkeypatch.setattr(news, "actus_a_envoyer", _a_envoyer)
    monkeypatch.setattr(news, "reserver_actu", _reserver)
    monkeypatch.setattr(news, "marquer_actu_envoyee", _marquer_envoyee)
    monkeypatch.setattr(news, "noter_echec_actu", _noter_echec)
    monkeypatch.setattr(news, "purger_file_actu", _purger_file)
    return lignes


@pytest.mark.asyncio
async def test_relever_actualites_publie_et_compte(monkeypatch):
    """La chaîne complète, sur des doublures : relever → dédup → publier →
    marquer → compte-rendu honnête."""
    async def _cfg(gid):
        return {"roblox_news_enabled": True, "roblox_news_salon": 14}

    async def _relever(src, forcer=False):   # même signature que le vrai
        return {"billets": [_billet(10, 1), _billet(11, 2)], "code": 200}

    deja = {11}
    marques = []
    envois = []

    async def _deja(gid, tid):
        return tid in deja

    async def _marquer(gid, tid):
        marques.append(tid)

    async def _publier_actu(g, salon, b):
        envois.append(b["topic_id"])
        return True

    async def _purger():
        return None

    async def _dodo(_):
        return None

    news.setup(get_db=None, cfg=_cfg, db_set=None, log=lambda *a: None)
    panneau.setup(db_set=None, webhook_send=None, log=lambda *a: None)
    monkeypatch.setattr(news, "relever", _relever)
    monkeypatch.setattr(news, "deja_publie", _deja)
    monkeypatch.setattr(news, "marquer_publie", _marquer)
    monkeypatch.setattr(news, "purger", _purger)
    monkeypatch.setattr(panneau, "publier_actu", _publier_actu)
    monkeypatch.setattr(panneau.asyncio, "sleep", _dodo)
    _file_en_memoire(monkeypatch, news)

    vue = panneau.RobloxPanelV2(_FauxUser(), _FauxGuild(_FauxSalon()))
    txt = await vue._relever_actualites()

    #  ⚠️ UN SEUL ENVOI, ET C'EST LA CORRECTION DU 30/08.
    #  L'ancienne attente etait `[10] * len(SOURCES)` : le meme billet publie
    #  SEPT fois, une par source. Elle ne tenait que parce que la doublure
    #  `_marquer` n'alimentait pas `deja` — en production, la deuxieme source
    #  l'aurait deduplique. Avec la file, un topic_id n'entre qu'une fois et ne
    #  part qu'une fois, quel que soit le nombre de sources qui le remontent.
    assert envois == [10], "le billet non publie part UNE fois, pas une par source"
    assert marques == [10], "et il est marque UNIQUEMENT apres l'envoi"
    assert "**réellement publié(s)**" in txt
    assert "déjà publiée(s)" in txt


@pytest.mark.asyncio
async def test_relever_actualites_ne_marque_pas_un_envoi_refuse(monkeypatch):
    """Même règle que les articles : la marque est définitive, on ne l'écrit
    que sur un envoi qui a RÉELLEMENT abouti."""
    async def _cfg(gid):
        return {"roblox_news_enabled": True, "roblox_news_salon": 14}

    async def _relever(src, forcer=False):   # même signature que le vrai
        return {"billets": [_billet(10, 1)], "code": 200}

    marques = []

    async def _deja(gid, tid):
        return False

    async def _marquer(gid, tid):
        marques.append(tid)

    async def _publier_refuse(g, salon, b):
        return False

    async def _purger():
        return None

    async def _dodo(_):
        return None

    news.setup(get_db=None, cfg=_cfg, db_set=None, log=lambda *a: None)
    panneau.setup(db_set=None, webhook_send=None, log=lambda *a: None)
    monkeypatch.setattr(news, "relever", _relever)
    monkeypatch.setattr(news, "deja_publie", _deja)
    monkeypatch.setattr(news, "marquer_publie", _marquer)
    monkeypatch.setattr(news, "purger", _purger)
    monkeypatch.setattr(panneau, "publier_actu", _publier_refuse)
    monkeypatch.setattr(panneau.asyncio, "sleep", _dodo)
    _file_en_memoire(monkeypatch, news)

    vue = panneau.RobloxPanelV2(_FauxUser(), _FauxGuild(_FauxSalon()))
    txt = await vue._relever_actualites()

    assert marques == [], "un refus de Discord ne doit JAMAIS poser la marque"
    assert "refusée(s) par Discord" in txt
    assert txt.startswith("📢 Actualités — 🔴")


# ═══════════════════════════════════════════════════════════════════════════════
#  4. La santé des actualités est AFFICHÉE
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_sante_des_actualites_est_affichee_dans_le_panneau():
    """`news.diagnostic()` était calculé et affiché nulle part. Une source
    muette ressemblait à une source calme — défaut n°4 de ROBLOX.md."""
    assert "await news.diagnostic()" in SRC_PAN
    assert "État des relevés — actualités" in SRC_PAN


# ═══════════════════════════════════════════════════════════════════════════════
#  5. La boucle n'est plus muette
# ═══════════════════════════════════════════════════════════════════════════════

def _boucle():
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            return ast.unparse(n)
    raise AssertionError("veille_roblox_task introuvable")


def test_la_boucle_dit_quand_elle_na_rien_a_faire():
    corps = _boucle()
    assert "passage sans travail" in corps, (
        "un return muet ne distingue pas « personne n'a allumé » de « la "
        "boucle est morte » — depuis Railway, c'est la même chose")


def test_la_boucle_fait_un_bilan_a_chaque_passage():
    corps = _boucle()
    assert "passage terminé" in corps
    #  ⚠️ DEUX COMPTEURS DEPUIS LE 30/08, ET C'EST PLUS STRICT, PAS MOINS.
    #  Un compteur commun laissait un billet d'actualite eteindre le
    #  diagnostic par serveur des accessoires — le cas qui a coute onze heures
    #  au proprietaire. On exige donc que CHAQUE flux tienne le sien.
    assert corps.count("_publies_a += 1") == 1, (
        "les accessoires doivent tenir leur propre compteur")
    assert corps.count("_publies_n += 1") == 1, (
        "les actualites doivent tenir leur propre compteur")
    assert "_publies +=" not in corps, (
        "le compteur commun est revenu : voir le defaut G5 du 30/08")
    assert "_publies_a" in corps and "_publies_n" in corps, (
        "le bilan doit citer les deux, sinon on ne sait pas lequel est a zero")


# ═══════════════════════════════════════════════════════════════════════════════
#  6. Le lien entre un ACCESSOIRE et l'annonce qui en parle (18/08)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def registre_vide():
    news._recents.clear()
    yield
    news._recents.clear()


def test_un_accessoire_est_relie_a_lannonce_qui_le_nomme(registre_vide):
    news._memoriser_recent({"topic_id": 4800001, "titre": "New Limited: The Requiem drops today",
                            "cree_le": "2026-08-18T10:00:00Z", "domaine": "Annonces"})
    news._memoriser_recent({"topic_id": 4800002, "titre": "Release Notes for 735",
                            "cree_le": "2026-08-18T11:00:00Z", "domaine": "Studio & moteur"})
    lies = news.billets_lies("The Requiem")
    assert len(lies) == 1
    assert lies[0]["lien"] == "https://devforum.roblox.com/t/4800001"


def test_un_nom_dun_seul_mot_ne_relie_rien(registre_vide):
    """« Hat » collerait a toute annonce qui contient « hat » : on prefere se
    taire qu'annoncer un rapport qui n'existe pas."""
    news._memoriser_recent({"topic_id": 1, "titre": "A new hat for everyone",
                            "cree_le": "2026-08-18T10:00:00Z", "domaine": "Annonces"})
    assert news.billets_lies("Hat") == []


def test_tous_les_mots_significatifs_doivent_apparaitre(registre_vide):
    news._memoriser_recent({"topic_id": 1, "titre": "Specter items are back",
                            "cree_le": "2026-08-18T10:00:00Z", "domaine": "Annonces"})
    assert news.billets_lies("Specter Time Fedora") == [], (
        "« time » et « fedora » manquent : pas de lien")


def test_le_corps_du_billet_compte_aussi(registre_vide):
    news._memoriser_recent({"topic_id": 1, "titre": "Weekly Recap",
                            "corps": "This week the Tricolor Ladoo Hat went live for India Day.",
                            "cree_le": "2026-08-18T10:00:00Z", "domaine": "Annonces"})
    assert len(news.billets_lies("Tricolor Ladoo Hat")) == 1


def test_le_registre_est_borne(registre_vide):
    for i in range(news.MAX_RECENTS + 50):
        news._memoriser_recent({"topic_id": i + 1, "titre": f"billet {i}",
                                "cree_le": "2026-08-18T10:00:00Z", "domaine": "x"})
    assert len(news._recents) <= news.MAX_RECENTS


def test_la_boucle_et_le_bouton_relient_les_accessoires_aux_annonces():
    assert "billets_lies(a.get(\"nom\")" in SRC_BOT
    assert "billets_lies(a.get(\"nom\")" in SRC_PAN
