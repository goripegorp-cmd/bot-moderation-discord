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




# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le bouton « Relever maintenant » relève AUSSI les actualités
# ═══════════════════════════════════════════════════════════════════════════════



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






# ═══════════════════════════════════════════════════════════════════════════════
#  4. La santé des actualités est AFFICHÉE
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_sante_des_actualites_est_affichee_dans_le_panneau():
    """`news.diagnostic()` était calculé et affiché nulle part. Une source
    muette ressemblait à une source calme — défaut n°4 de ROBLOX.md."""
    assert "await news.diagnostic()" in SRC_PAN
    assert "**Sources**" in SRC_PAN


# ═══════════════════════════════════════════════════════════════════════════════
#  5. La boucle n'est plus muette
# ═══════════════════════════════════════════════════════════════════════════════

def _fn(nom: str) -> str:
    """La source d'une fonction de bot.py — boucle OU fonction partagée.

    Depuis le 14/09/2026, l'envoi vit dans trois fonctions extraites de la
    boucle (`_publier_file_accessoires`, `_enfiler_billets`,
    `_publier_file_actualites`), partagées avec l'éclaireur. Les propriétés
    d'ORDRE se vérifient dans la fonction qui porte les deux bornes.
    """
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return ast.unparse(n)
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _boucle():
    for n in ast.walk(ast.parse(SRC_BOT)):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "veille_roblox_task":
            return ast.unparse(n)
    raise AssertionError("veille_roblox_task introuvable")








