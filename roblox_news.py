"""roblox_news.py — Veille d'actualité Roblox : Studio, UGC, développeurs, événements.

Voir `ROBLOX.md` (cahier des charges) et `rapports/roblox-veille-actualites-plan.json`
(97 agents, 71 sources réellement ouvertes, 9 écartées comme mortes).

═══════════════════════════════════════════════════════════════════════════════
CE QUI EST COUVERT, ET CE QUI NE PEUT PAS L'ÊTRE
═══════════════════════════════════════════════════════════════════════════════
Le propriétaire veut « absolument tout ». Honnêtement :

COUVERT — Studio (bêtas, pilotes, outils), moteur et API, UGC et Marketplace,
développeurs, politique et CGU, événements officiels, état de la plateforme.

PAS COUVERT — « tous les artistes » n'existe PAS comme flux chez Roblox. Mesuré :
la catégorie `clothing` donne 0 billet officiel sur 15 (que des petites annonces
« [FOR HIRE] designer 2D »), et le tag `ugc` ne renvoie aucun sujet. Il n'y a
aucune catégorie dédiée aux créateurs 2D, vêtements et accessoires. Le domaine
« artistes » sera donc un sous-ensemble du reste, moins fourni — ce n'est pas un
défaut du bot, c'est l'absence de la source.

═══════════════════════════════════════════════════════════════════════════════
LA CONTRAINTE QUI COMMANDE TOUTE L'ARCHITECTURE
═══════════════════════════════════════════════════════════════════════════════
Mesuré : c'est la CONCURRENCE qui déclenche le pare-feu d'AWS, pas le volume.
60 requêtes en parallèle passent ; 200 en salves rendent des réponses vides et
bloquent l'IP 21 à 41 secondes.

D'où la règle : **une source à la fois, jamais de rafale parallèle**. Chaque
source porte sa propre échéance ; un passage n'en interroge qu'une poignée.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

#  ⚠️ DOMAINES EN DUR — même règle que roblox_veille : un lien publié par ce bot
#  est RECONSTRUIT, jamais recopié d'une réponse. Voir ROBLOX.md §1.
DOMAINE_FORUM = "https://devforum.roblox.com"

#  Sources vérifiées le 12/08/2026 par appel réel. Le champ `domaine` sert au
#  classement et au routage ; `cle` identifie la source dans le registre de santé.
#
#  ⚠️ Les identifiants de catégorie sont ceux du forum Discourse de Roblox,
#  relevés dans les réponses. Ne pas les « corriger » de mémoire.
SOURCES = [
    {"cle": "annonces", "domaine": "Annonces",
     "url": f"{DOMAINE_FORUM}/c/updates/announcements/36.json?order=created",
     "minutes": 30},
    {"cle": "notes", "domaine": "Studio & moteur",
     "url": f"{DOMAINE_FORUM}/c/updates/release-notes/62.json?order=created",
     "minutes": 30},
    {"cle": "alertes", "domaine": "Politique & sécurité",
     "url": f"{DOMAINE_FORUM}/c/updates/news-alerts/193.json?order=created",
     "minutes": 60},
    {"cle": "communaute", "domaine": "Événements",
     "url": f"{DOMAINE_FORUM}/c/updates/community/90.json?order=created",
     "minutes": 60},
    {"cle": "ressources", "domaine": "Développeurs",
     "url": f"{DOMAINE_FORUM}/c/resources/roblox-staff/278.json?order=created",
     "minutes": 120},
]

MAX_BILLETS_PAR_PASSAGE = 5
MAX_PUBLIES_GARDES = 4000

#  ⚠️ FRAÎCHEUR MAXIMALE — NE PAS RETIRER CE GARDE-FOU.
#
#  Mesuré le 12/08/2026 sur les vraies réponses : les catégories lentes portent
#  en haut de liste des billets de 73, 137, 277 et jusqu'à 337 JOURS. Elles
#  publient peu, donc leur « dernier billet » peut être très ancien.
#
#  La déduplication seule ne suffit PAS à s'en protéger : elle repose sur la
#  base. Une base neuve, un serveur qui active le système pour la première fois,
#  une restauration de sauvegarde — et le salon reçoit d'un coup une alerte
#  vieille d'un an annoncée comme une nouvelle.
#
#  Le propriétaire l'a dit mot pour mot : « faut pas que les news soient
#  dépassées depuis un moment ». Ce plafond est indépendant de la base : un
#  billet trop vieux n'est JAMAIS publié, quel que soit l'état du reste.
#
#  30 jours : mesuré, ça laisse passer le billet le plus récent de CHAQUE
#  catégorie (le plus lent est à 17 jours) et bloque tous les autres.
FRAICHEUR_MAX_JOURS = 30

_get_db = None
_cfg = None
_db_set = None
_log = print


def setup(*, get_db, cfg, db_set, log=None):
    global _get_db, _cfg, _db_set, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    if log is not None:
        _log = log


CLES_DEFAUT = {
    "roblox_news_enabled": False,
    "roblox_news_salon": 0,
    "roblox_news_amorcee": "",
}


async def config(guild_id: int) -> dict:
    try:
        c = await _cfg(guild_id)
    except Exception as ex:
        _log(f"[roblox_news config] {ex}")
        c = {}
    out = dict(CLES_DEFAUT)
    for k in out:
        if k in c:
            out[k] = c[k]
    return out


async def actif(guild_id: int) -> bool:
    c = await config(guild_id)
    #  `.get` : une config partielle ne doit jamais faire tomber la garde,
    #  elle doit rendre « éteint » — fail-closed sur le doute.
    return bool(c.get("roblox_news_enabled")
                and int(c.get("roblox_news_salon") or 0))


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_news_publies("
            " guild_id INTEGER NOT NULL,"
            " topic_id INTEGER NOT NULL,"
            " publie_le TEXT NOT NULL,"
            " PRIMARY KEY(guild_id, topic_id))")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS roblox_news_sante("
            " cle TEXT PRIMARY KEY,"
            " dernier_essai TEXT, dernier_succes TEXT,"
            " dernier_code INTEGER, echecs INTEGER NOT NULL DEFAULT 0)")
        await db.commit()


def lien_billet(topic_id, slug: str | None = None) -> str | None:
    """L'URL d'un billet, RECONSTRUITE à partir d'un identifiant entier.

    Jamais recopiée d'une réponse. Le `slug` n'est qu'un confort de lecture :
    Discourse résout un billet sur son seul identifiant, donc un slug douteux
    n'est pas repris.
    """
    try:
        n = int(topic_id)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return f"{DOMAINE_FORUM}/t/{n}"


def _ouvrir():
    """Session HTTP dédiée, avec un User-Agent nommé.

    ⚠️ Ce module n'exige AUCUNE session injectée — la première version de
    `roblox_veille` le faisait, le câblage passait None, et le système sortait
    avant tout appel réseau. On n'y revient pas.
    """
    import aiohttp
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20),
        headers={"User-Agent": "BotModerationDiscord/1.0 (veille Roblox)",
                 "Accept": "application/json"})


async def _noter_sante(cle: str, code: int | None) -> int:
    maintenant = datetime.now(timezone.utc).isoformat()
    ok = code is not None and 200 <= code < 300
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT echecs FROM roblox_news_sante WHERE cle=?", (cle,)) as cur:
                row = await cur.fetchone()
            echecs = 0 if ok else (int(row[0]) if row else 0) + 1
            await db.execute(
                "INSERT INTO roblox_news_sante(cle, dernier_essai, dernier_succes,"
                " dernier_code, echecs) VALUES(?,?,?,?,?)"
                " ON CONFLICT(cle) DO UPDATE SET dernier_essai=?,"
                "  dernier_succes=COALESCE(?, dernier_succes), dernier_code=?, echecs=?",
                (cle, maintenant, maintenant if ok else None, code, echecs,
                 maintenant, maintenant if ok else None, code, echecs))
            await db.commit()
        return echecs
    except Exception as ex:
        _log(f"[roblox_news _noter_sante] {ex}")
        return 0


async def relever(source: dict) -> dict:
    """Lit une source Discourse. Rend {"billets": [...], "code": int|None}.

    Ne lève jamais : une panne de veille ne doit pas gêner la modération.
    """
    out = {"billets": [], "code": None, "domaine": source["domaine"]}
    try:
        async with _ouvrir() as sess:
            async with sess.get(source["url"]) as r:
                out["code"] = r.status
                if r.status == 200:
                    data = await r.json()
                    out["billets"] = _normaliser(data, source["domaine"])
                else:
                    _log(f"[roblox_news {source['cle']}] HTTP {r.status}")
    except Exception as ex:
        _log(f"[roblox_news {source['cle']}] {type(ex).__name__}: {ex}")
    await _noter_sante(source["cle"], out["code"])
    return out


def _trop_vieux(quand, jours: int = FRAICHEUR_MAX_JOURS) -> bool:
    """Ce billet est-il trop ancien pour être annoncé comme une nouvelle ?

    Une date ILLISIBLE est traitée comme trop vieille — fail-closed. C'est
    l'inverse du choix fait pour les articles du catalogue, et c'est délibéré :
    ici le risque n'est pas de rater une nouveauté, c'est d'annoncer une alerte
    de sécurité vieille d'un an. Dans le doute, on se tait.
    """
    try:
        d = datetime.fromisoformat(str(quand).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).days > int(jours)
    except Exception:
        return True


def _normaliser(data: dict, domaine: str) -> list[dict]:
    """Réduit une réponse Discourse aux champs qu'on sait afficher.

    Les billets ÉPINGLÉS sont écartés : ils remontent en tête indéfiniment et
    seraient republiés comme des nouveautés à chaque changement de catégorie.
    """
    out = []
    try:
        sujets = ((data.get("topic_list") or {}).get("topics") or [])
    except Exception:
        return out
    for t in sujets:
        try:
            if t.get("pinned") or t.get("pinned_globally"):
                continue
            tid = int(t.get("id") or 0)
            if tid <= 0:
                continue
            #  ⚠️ Filtre de fraîcheur appliqué DÈS LA NORMALISATION, donc avant
            #  la déduplication et avant l'amorce. Un billet trop vieux n'entre
            #  même pas dans le circuit : c'est la seule garantie qui tienne si
            #  la base est neuve ou restaurée. Voir FRAICHEUR_MAX_JOURS.
            if _trop_vieux(t.get("created_at")):
                continue
            out.append({
                "topic_id": tid,
                "titre": str(t.get("title") or "")[:200],
                "domaine": domaine,
                "cree_le": t.get("created_at"),
                "extrait": (str(t.get("excerpt") or "")[:300] or None),
                "tags": [str(x) for x in (t.get("tags") or [])][:5],
            })
        except Exception:
            continue
    out.sort(key=lambda b: str(b.get("cree_le") or ""), reverse=True)
    return out


async def deja_publie(guild_id: int, topic_id: int) -> bool:
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM roblox_news_publies WHERE guild_id=? AND topic_id=?",
                (guild_id, topic_id)) as cur:
                return bool(await cur.fetchone())
    except Exception:
        #  Fail-CLOSED : dans le doute on considère que c'est sorti. Mieux vaut
        #  rater un billet que noyer le salon de doublons.
        return True


async def marquer_publie(guild_id: int, topic_id: int) -> None:
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO roblox_news_publies(guild_id, topic_id,"
                " publie_le) VALUES(?,?,?)",
                (guild_id, topic_id, datetime.now(timezone.utc).isoformat()))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_news marquer_publie] {ex}")


#  ⚠️ CE QUE L'AMORCE LAISSE PASSER, ET POURQUOI.
#  La première version absorbait TOUT ce que la fenêtre de 30 jours laissait
#  entrer : le propriétaire allumait, et devait attendre le PROCHAIN billet du
#  forum pour voir une seule fiche — c'est exactement le défaut qui avait été
#  corrigé côté articles le 15/08 (« 30 articles lus, 0 fiche publiée »).
#  Demande du 16/08 : « je veux les dernières news partout ». La dernière
#  semaine sort donc au premier passage, bornée par le plafond de publications ;
#  ce qui est plus vieux est absorbé sans bruit. Sept jours = « les dernières »
#  sans déverser un mois d'archives — c'est le §« premier allumage » de
#  ROBLOX.md : une borne, jamais un mur.
AMORCE_GARDE_JOURS = 7


async def amorcer(guild_id: int) -> int:
    """Pose la borne du premier allumage. Rend le nombre de billets ABSORBÉS.

    Absorbe (marque comme déjà sortis) les billets plus vieux que
    `AMORCE_GARDE_JOURS` ; laisse les autres sortir au premier passage.
    Sans amorce du tout, le premier passage déverserait un mois d'archives.
    """
    n = 0
    for src in SOURCES:
        rel = await relever(src)
        for b in rel["billets"]:
            if _trop_vieux(b.get("cree_le"), AMORCE_GARDE_JOURS):
                await marquer_publie(guild_id, b["topic_id"])
                n += 1
        #  Une source à la fois, jamais de rafale — voir l'en-tête du module.
        await asyncio.sleep(1.5)
    try:
        await _db_set(guild_id, "roblox_news_amorcee",
                      datetime.now(timezone.utc).isoformat())
    except Exception as ex:
        _log(f"[roblox_news amorcer] {ex}")
    return n


async def oublier_publies(guild_id: int) -> int:
    """Efface les marques « déjà publié » des actualités d'une guilde.

    Le pendant du bouton ♻️ des articles : un correctif de code ne répare pas
    des données déjà écrites. Rend le nombre de marques effacées.
    """
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM roblox_news_publies WHERE guild_id=?",
                (guild_id,)) as cur:
                n = int((await cur.fetchone())[0])
            await db.execute(
                "DELETE FROM roblox_news_publies WHERE guild_id=?", (guild_id,))
            await db.commit()
        return n
    except Exception as ex:
        _log(f"[roblox_news oublier_publies] {ex}")
        return 0


async def purger() -> None:
    try:
        async with _get_db() as db:
            await db.execute(
                "DELETE FROM roblox_news_publies WHERE publie_le < ?",
                ((datetime.now(timezone.utc) - timedelta(days=365)).isoformat(),))
            await db.commit()
    except Exception as ex:
        _log(f"[roblox_news purger] {ex}")


async def diagnostic() -> list[dict]:
    """L'état de chaque source. Une source muette doit se voir."""
    out = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT cle, dernier_succes, dernier_code, echecs"
                " FROM roblox_news_sante") as cur:
                for cle, succes, code, echecs in await cur.fetchall():
                    out.append({"cle": cle, "dernier_succes": succes,
                                "code": code, "echecs": int(echecs or 0)})
    except Exception as ex:
        _log(f"[roblox_news diagnostic] {ex}")
    return out
