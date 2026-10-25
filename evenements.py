"""evenements.py — les annonces et les événements du clan GoRP, composés sur le site (25/10/2026).

Le fondateur : « créer un onglet spécifique… dans Clan GoRP, avec le salon Info, qui nous permet, en tant
que fondateur et pour la direction, de faire des annonces et déclencher des événements pour dire « Est-ce
que vous êtes disponibles à telle heure ? » avec de vrais systèmes de timer sur le Discord… vraiment bien
customisable… annoncer officiellement les métiers des gens… envoyer le listing complet du clan… qu'il custom
tout comme il le souhaite, mais que tu l'aides énormément. » Et : « pas d'emojis, des trucs moches ».

LE SITE (fondateur et direction — le site le vérifie, ce module le revérifie)
  · Un brouillon par publication, gardé en base et versionné : deux onglets ou deux personnes ne s'écrasent
    jamais (409 et les deux versions). `clan/brouillon` marche hors ligne (rejoué au retour, idempotent par
    `cle_client`) et ne touche JAMAIS Discord. `clan/apercu` rend la carte telle que Discord l'affichera
    (blocs, lignes, icônes, boutons, compteurs, découpage, composants et caractères comptés).
  · Publier (`clan/publier`), modifier une publication (`clan/modifier`) et annuler (`clan/annuler`)
    exigent la connexion : jamais rejoués hors ligne. Un double clic sur « Publier » ne publie qu'une fois
    (verrou, puis passage atomique brouillon → envoi en base) ; une erreur d'envoi relit le post avant de
    dire « rien n'est parti ».
DISCORD (Components V2, français · anglais, AUCUN émoji Unicode : les icônes maison des émojis
d'application — `visuels/icones/<nom>.png` — et rien quand l'une manque)
  · L'événement : date en clair (`<t:X:F>`), minuteur vivant (`<t:X:R>`, Discord le fait défiler chez
    chacun), durée, lieu, places ; « Disponible · Peut-être · Pas disponible » (boutons persistants), les
    compteurs et les disponibles (mentions sans ping) ; à venir → en cours → terminé, ou annulé. Un clic
    reçoit un mot pour lui seul, qui s'efface ; la carte se réécrit une fois par rafale de clics.
  · Les rappels (boucle supervisée de bot.py, une minute, et un minuteur exact à l'approche) : aux minutes
    choisies, un court message dans le post qui mentionne les « Disponible » — eux seuls, ils l'ont choisi —
    ou personne. Chaque rappel est noté en base AVANT l'envoi : après un redémarrage, rien ne repart deux
    fois (un rappel raté vaut mieux qu'un double ping).
  · En option, l'évènement programmé natif de Discord (lieu « RELL Seas · <lieu> »), créé, modifié,
    démarré, terminé ou annulé avec le nôtre ; sans la permission, le site le dit.
  · L'annonce : image (ou le bandeau du clan, comme `annonces.py`), titre, texte, « Vu · Seen » et son
    compteur.
  · L'annonce officielle des métiers et le listing complet du clan : les membres du rôle du clan regroupés
    par métier, grade ou race (les fiches des affiches du site, injectées), découpés en plusieurs cartes
    au-delà de 40 composants ou 4 000 caractères ; mentions sans ping.
"""
from __future__ import annotations

import asyncio
import inspect
import io
import json
import re
import sqlite3
import time
from datetime import datetime, timezone

import discord
from discord.ui import Button

import annonces
import diag
import paths
import visuels
import zones
from ui_v2 import LayoutView, Palette

# ═══════════════════════════════════════════════════════════════════════════════
#  Réglages
# ═══════════════════════════════════════════════════════════════════════════════

TYPES = ("evenement", "annonce", "metiers", "listing")
NOMS_TYPES = {"evenement": "Événement", "annonce": "Annonce", "metiers": "Annonce des métiers",
              "listing": "Listing du clan"}
STATUTS = ("brouillon", "envoi", "publie", "annule", "retire", "incertain")
MENTIONS = ("aucune", "clan", "inscrits")
GROUPEMENTS = ("metier", "grade", "race")
CHAMPS_LISTE = ("metiers", "grade", "race")
NOM_CLAN = "Clan GoRP"
TITRE_MAX = 100
TEXTE_MAX = {"evenement": 2000, "annonce": 3500, "metiers": 1500, "listing": 1500}
LIEU_MAX = 100
DUREE_MAX = 10080              # minutes : une semaine
RAPPEL_MAX = 20160             # minutes : deux semaines avant
RAPPELS_MAX = 5
PLACES_MAX = 500
HORIZON_S = 366 * 86400        # un événement se prévoit un an à l'avance au plus
AVANCE_S = 60                  # publié au moins une minute avant son début
FIN_SANS_DUREE_S = 2 * 3600    # sans durée : les réponses se ferment deux heures après le début
RETARD_RAPPEL_ZERO_S = 600     # « c'est l'heure » ne part plus dix minutes après le début
ENVOI_BLOQUE_S = 300           # une publication « en cours » depuis 5 min : interrompue (redémarrage)
MAJ_CARTE_S = 5.0              # la carte se réécrit au plus toutes les 5 s (une rafale = une réécriture)
AVIS_S = 120.0                 # un mot pour soi s'efface au bout de 2 minutes
DEMARRE_S = 30.0
MINUTEUR_S = 65.0              # à moins de 65 s d'un rappel ou d'un changement d'état : un minuteur exact
LOT_MENTIONS = 50              # mentions par message de rappel (Discord en refuse plus de 100)
COMPOSANTS_MAX, CARACTERES_MAX = 40, 4000   # Discord, par message Components V2
COMPOSANTS_CIBLE, CARACTERES_CIBLE = 38, 3800
ICONE_LONGUEUR = 40            # « <:minuteur_v1:123…> » : la place qu'on garde pour une icône
LIGNES_GROUPE_MAX = 1500       # caractères d'un bloc de groupe (métiers, listing) avant « suite »
MARQUE = 1_500_000_000         # l'identifiant du conteneur d'une carte : MARQUE + numéro (retrouver un envoi)
GARDE_JOURS = 60               # le nettoyage du site : les événements passés partent après 60 jours
GARDE_SECOURS_JOURS = 400      # filet du module si le nettoyage du site ne passe pas
PASSES_MAX, LIGNES_MAX = 100, 600
TAILLE_CORPS = 32 * 1024
COULEURS = {"evenement": 0xA8823F, "annonce": annonces.STYLE_CLAN[2], "metiers": 0x8E2A24, "listing": 0x1F4E5A}
#  En tête de carte quand il n'y a pas d'image : le bandeau du clan d'`annonces.py`, la liste du clan.
BANDEAUX = {"annonce": annonces.STYLE_CLAN[:2], "listing": ("clan", "Liste du clan")}
ICONES = ("minuteur", "lieu", "membres", "valider", "annuler", "peut_etre", "cloche", "ancre", "boussole",
          "drapeau", "prime", "navire", "calendrier", "horloge")
CHOIX = {"d": ("Disponible", "Available"), "p": ("Peut-être", "Maybe"), "n": ("Pas disponible", "Unavailable")}
CHOIX_ICONE = {"d": "valider", "p": "peut_etre", "n": "annuler"}
GROUPES_NOMS = {"metier": ("métier", "trade"), "grade": ("grade", "rank"), "race": ("race", "race")}
SANS_GROUPE = {"metier": "Sans métier · No trade", "grade": "Sans grade · No rank",
               "race": "Race non renseignée · Race not set"}
PURGES = [
    ("événements passés du clan", "DELETE FROM clan_evenements WHERE archive_le > 0 AND archive_le < ?",
     GARDE_JOURS, "unix"),
    ("réponses aux événements du clan", "DELETE FROM clan_evenements_reponses WHERE evenement_id NOT IN "
                                        "(SELECT id FROM clan_evenements)", None, None),
]

TEXTES = {
    "introuvable": {"fr": "Cet événement n'existe plus.", "en": "This event no longer exists."},
    "annonce_introuvable": {"fr": "Cette annonce n'existe plus.", "en": "This announcement no longer exists."},
    "annule": {"fr": "Cet événement est annulé.", "en": "This event was cancelled."},
    "fini": {"fr": "Cet événement est terminé : les réponses sont closes.",
             "en": "This event has ended: answers are closed."},
    "reserve": {"fr": "Cet événement est réservé aux membres du clan.", "en": "This event is for clan members only."},
    "complet": {"fr": "Complet : les {n} places sont déjà prises.", "en": "Full: all {n} spots are already taken."},
    "deja": {"fr": "Tu as déjà répondu **{choix}**.", "en": "You already answered **{choix}**."},
    "ok": {"fr": "C'est noté : **{choix}**.", "en": "Noted: **{choix}**."},
    "debut": {"fr": "Début <t:{q}:R>.", "en": "Starts <t:{q}:R>."},
    "rappel_toi": {"fr": "Les rappels te mentionneront.", "en": "Reminders will ping you."},
    "vu_ok": {"fr": "C'est noté, merci d'avoir lu.", "en": "Noted, thanks for reading."},
    "vu_deja": {"fr": "Déjà noté.", "en": "Already noted."},
    "demarre": {"fr": "Le bot démarre : réessaie dans quelques secondes.",
                "en": "The bot is starting: try again in a few seconds."},
    "souci": {"fr": "Un souci est survenu : réessaie dans quelques secondes.",
              "en": "Something went wrong: try again in a few seconds."},
}

_get_db = _cfg = _journal = _role_clan = _langue = _est_tete = None
_fiches = _catalogue = _media = None
_log = print
_mur = time.time                 # l'horloge, remplaçable dans les tests
_verrous: dict = {}
_maj_prevues: dict = {}
_minuteurs: dict = {}
_taches: set = set()
_fils_connus: dict = {}
_purge = [0.0]
_releve = {"boucles": 0, "derniere_boucle": 0, "rappels": 0, "cartes": 0, "publications": 0, "erreurs": 0,
           "a_venir": 0}


def tr(cle: str, langue: str = "fr", **kw) -> str:
    e = TEXTES.get(cle) or {}
    texte = e.get(langue) or e.get("fr") or cle
    return texte.format(**kw) if kw else texte


def setup(*, get_db, cfg, journal=None, role_clan=None, langue=None, est_tete=None, fiches=None,
          catalogue=None, media=None, log=None):
    """`journal(g, type_, texte, **kw)` (async) : le journal du site ; `role_clan(g, c)` → le rôle du clan ;
    `langue(i)` (async) → « fr » | « en » ; `est_tete(g, membre)` → le fondateur ou la direction (TETE_IDS) ;
    `fiches(g)` → [{membre_id, nom, metiers: [clés], grade, race}] et `catalogue(g)` → {type: {clé: {nom,
    icone_emoji?}}} (les affiches du site, sync ou async) ; `media(id)` → (octets, extension) | None (sinon :
    `<données>/site/medias/<id>.<ext>`)."""
    global _get_db, _cfg, _journal, _role_clan, _langue, _est_tete, _log
    _get_db, _cfg, _journal, _role_clan, _langue, _est_tete = get_db, cfg, journal, role_clan, langue, est_tete
    _log = log or print
    brancher(fiches=fiches, catalogue=catalogue, media=media)


def brancher(*, fiches=None, catalogue=None, media=None):
    """Les affiches du site (un autre module, qui peut démarrer après celui-ci) : les fiches des membres, le
    catalogue du jeu, les médias. Un `None` laisse ce qui est déjà branché."""
    global _fiches, _catalogue, _media
    _fiches = fiches if fiches is not None else _fiches
    _catalogue = catalogue if catalogue is not None else _catalogue
    _media = media if media is not None else _media


def pret() -> bool:
    return _get_db is not None


def releve() -> dict:
    """Pour /stats : des nombres, aucun nom."""
    return {"pret": pret(), **_releve}


def _verrou(eid: int) -> asyncio.Lock:
    return _verrous.setdefault(int(eid), asyncio.Lock())


def _signaler(code: str, message: str, ex=None, detail: str = "") -> None:
    """Un message STABLE (le tableau des erreurs ne sature pas), le détail sur une ligne à part."""
    _releve["erreurs"] += 1
    _log(f"[EVENEMENTS][{code}] {message}")
    _log(f"[EVENEMENTS][{code}:DETAIL] {detail} {type(ex).__name__ + ' ' + str(ex) if ex is not None else ''}".rstrip())
    diag.compter("evenements", code, ex)


async def _appeler(fn, *args):
    r = fn(*args)
    return await r if inspect.isawaitable(r) else r


async def _noter(g, type_: str, texte: str, **kw) -> None:
    """Le journal du site : une ligne lisible. Son échec ne casse jamais le geste."""
    if _journal is None:
        return
    try:
        await _journal(g, type_, texte, **kw)
    except Exception as ex:
        _signaler("E9", "journal du site non écrit", ex, type_)


async def langue_de(i) -> str:
    try:
        if _langue is not None:
            return "en" if await _langue(i) == "en" else "fr"
        loc = str(getattr(getattr(i, "locale", None), "value", getattr(i, "locale", "")) or "")
        return "fr" if loc.lower().startswith("fr") else "en"
    except Exception as ex:
        _log(f"[EVENEMENTS:DETAIL] langue {type(ex).__name__} {ex}")
        return "fr"


# ═══════════════════════════════════════════════════════════════════════════════
#  Données
# ═══════════════════════════════════════════════════════════════════════════════

_COLONNES = ("id", "guild_id", "type", "statut", "phase", "donnees", "version", "cle_client", "cree", "cree_par",
             "maj", "maj_par", "publie", "publie_par", "salon_id", "messages", "discord_event_id", "rappels_faits",
             "quand", "fin", "note", "envoi_le", "archive_le")
_SELECT = "SELECT " + ", ".join(_COLONNES) + " FROM clan_evenements"


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS clan_evenements (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " guild_id INTEGER NOT NULL, type TEXT NOT NULL, statut TEXT NOT NULL DEFAULT 'brouillon',"
            " phase TEXT NOT NULL DEFAULT '', donnees TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,"
            " cle_client TEXT, cree INTEGER NOT NULL, cree_par INTEGER NOT NULL DEFAULT 0, maj INTEGER NOT NULL,"
            " maj_par INTEGER NOT NULL DEFAULT 0, publie INTEGER NOT NULL DEFAULT 0,"
            " publie_par INTEGER NOT NULL DEFAULT 0, salon_id INTEGER NOT NULL DEFAULT 0,"
            " messages TEXT NOT NULL DEFAULT '[]', discord_event_id INTEGER NOT NULL DEFAULT 0,"
            " rappels_faits TEXT NOT NULL DEFAULT '[]', quand INTEGER NOT NULL DEFAULT 0,"
            " fin INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', envoi_le INTEGER NOT NULL DEFAULT 0,"
            " archive_le INTEGER NOT NULL DEFAULT 0)")
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clan_ev_cle ON clan_evenements(guild_id, cle_client)"
                         " WHERE cle_client IS NOT NULL")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_clan_ev_statut ON clan_evenements(guild_id, statut, quand)")
        #  Une réponse par membre et par publication : d · p · n (événement), v (« Vu » d'une annonce).
        await db.execute(
            "CREATE TABLE IF NOT EXISTS clan_evenements_reponses (evenement_id INTEGER NOT NULL,"
            " membre_id INTEGER NOT NULL, choix TEXT NOT NULL, quand INTEGER NOT NULL,"
            " PRIMARY KEY (evenement_id, membre_id))")
        await db.commit()


def _defauts(type_: str) -> dict:
    """Les valeurs d'un brouillon neuf : de quoi publier tout de suite, en changeant ce qu'on veut."""
    v = {"titre": "", "texte": "", "image": "", "couleur": COULEURS[type_], "destination": "", "mention": "aucune"}
    if type_ == "evenement":
        v.update(quand=None, duree_min=60, lieu="", rappels=[60], mention="inscrits", reponses=True, places=0,
                 discord_event=False, reserve_clan=True)
    elif type_ == "metiers":
        v.update(titre="Les métiers de l'équipage", groupement="metier", champs=["grade"])
    elif type_ == "listing":
        v.update(titre="Le clan au complet", groupement="grade", champs=["metiers", "race"])
    return v


CHAMPS_TYPE = {t: frozenset(_defauts(t)) for t in TYPES}
CHAMPS = frozenset().union(*CHAMPS_TYPE.values())
CLES_CONTROLE = frozenset({"id", "version", "cle_client", "type"})


def _json(brut, defaut):
    try:
        x = json.loads(brut) if brut else defaut
    except (TypeError, ValueError):
        return defaut
    return x if isinstance(x, type(defaut)) else defaut


def _ligne(r) -> dict:
    e = dict(zip(_COLONNES, r))
    #  `image_ext` : l'extension de la pièce jointe posée à la publication (jamais envoyée par le site).
    e["valeurs"] = {**_defauts(e["type"]), **{k: v for k, v in _json(e.pop("donnees"), {}).items()
                                               if k in CHAMPS_TYPE[e["type"]] or k == "image_ext"}}
    e["messages"] = [int(x) for x in _json(e["messages"], []) if str(x).isdigit()]
    e["rappels_faits"] = [int(x) for x in _json(e["rappels_faits"], []) if isinstance(x, int)]
    return e


async def charger(eid: int):
    async with _get_db() as db:
        async with db.execute(_SELECT + " WHERE id=?", (int(eid),)) as cur:
            r = await cur.fetchone()
    return _ligne(r) if r else None


async def _par_cle(guild_id: int, cle: str):
    async with _get_db() as db:
        async with db.execute(_SELECT + " WHERE guild_id=? AND cle_client=?", (int(guild_id), cle)) as cur:
            r = await cur.fetchone()
    return _ligne(r) if r else None


async def _tous(guild_id: int) -> list:
    async with _get_db() as db:
        async with db.execute(_SELECT + " WHERE guild_id=? ORDER BY id DESC LIMIT ?", (int(guild_id), LIGNES_MAX)) as cur:
            return [_ligne(r) for r in await cur.fetchall()]


async def _ecrire(sql: str, args: tuple) -> tuple:
    """(lastrowid, rowcount)."""
    async with _get_db() as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return cur.lastrowid, cur.rowcount


async def _reponses(eid: int) -> dict:
    """{"d": [membres…], "p": […], "n": […], "v": […]}, dans l'ordre des réponses."""
    out = {"d": [], "p": [], "n": [], "v": []}
    async with _get_db() as db:
        async with db.execute("SELECT membre_id, choix FROM clan_evenements_reponses WHERE evenement_id=?"
                              " ORDER BY quand, membre_id", (int(eid),)) as cur:
            for uid, choix in await cur.fetchall():
                out.setdefault(str(choix), []).append(int(uid))
    return out


async def _comptes(ids: list) -> dict:
    """{publication: {choix: nombre}} pour toute une liste, en une requête."""
    if not ids:
        return {}
    out: dict = {}
    marques = ",".join("?" * len(ids))
    async with _get_db() as db:
        async with db.execute(f"SELECT evenement_id, choix, COUNT(*) FROM clan_evenements_reponses"
                              f" WHERE evenement_id IN ({marques}) GROUP BY evenement_id, choix", tuple(ids)) as cur:
            for eid, choix, n in await cur.fetchall():
                out.setdefault(int(eid), {})[str(choix)] = int(n)
    return out


async def medias_utilises() -> set:
    """Les médias du site que les brouillons et les publications citent : le nettoyage des « médias inutilisés »
    du site ne doit jamais les retirer (un brouillon perdrait son image)."""
    out = set()
    async with _get_db() as db:
        async with db.execute("SELECT donnees FROM clan_evenements") as cur:
            for (brut,) in await cur.fetchall():
                media = _json(brut, {}).get("image")
                if isinstance(media, str) and media:
                    out.add(media)
    return out


async def purger(jours: int = GARDE_JOURS) -> int:
    """Les événements terminés ou annulés et les annonces retirées depuis plus de `jours` jours, et leurs
    réponses. Les brouillons et les annonces publiées restent (leur « Vu » doit répondre)."""
    borne = int(_mur()) - int(jours) * 86400
    async with _get_db() as db:
        cur = await db.execute("DELETE FROM clan_evenements WHERE archive_le > 0 AND archive_le < ?", (borne,))
        n = int(cur.rowcount or 0)
        await db.execute("DELETE FROM clan_evenements_reponses WHERE evenement_id NOT IN"
                         " (SELECT id FROM clan_evenements)")
        await db.commit()
    return n


# ═══════════════════════════════════════════════════════════════════════════════
#  Les destinations : les posts du forum du clan (📢 Infos d'abord)
# ═══════════════════════════════════════════════════════════════════════════════

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿️‍"
                    "\U000E0020-\U000E007F]")


def sans_emoji(texte: str) -> str:
    """Un nom pour le site (« aucun émoji nulle part ») : « 📢 Infos · Info » → « Infos · Info »."""
    return " ".join(_EMOJI.sub("", str(texte or "")).split())


def destinations(g, c: dict) -> list:
    """Les posts du forum du clan où l'on publie, 📢 Infos par défaut (le guide n'en est pas un)."""
    posts = c.get("clan_posts") or {}
    out = []
    for cle, titre, _verrouille, _texte in zones.CLAN_POSTS:
        pid = int((posts.get(cle) or {}).get("id", 0) or 0) if isinstance(posts.get(cle), dict) else 0
        if cle != "guide" and pid:
            out.append({"id": str(pid), "cle": cle, "nom": sans_emoji(titre), "defaut": cle == "infos"})
    ancien = int(c.get("clan_annonces", 0) or 0)
    if ancien and all(d["id"] != str(ancien) for d in out):
        out.append({"id": str(ancien), "cle": "annonces", "nom": "Annonces du clan", "defaut": False})
    if out and not any(d["defaut"] for d in out):
        out[0]["defaut"] = True
    return out


def _destination(dests: list, v: dict) -> dict | None:
    voulu = str(v.get("destination") or "")
    return next((d for d in dests if d["id"] == voulu), None) if voulu else next(
        (d for d in dests if d["defaut"]), None)


async def _salon(g, sid):
    """Un post, même endormi (hors mémoire) ; None s'il n'existe plus."""
    sid = int(sid or 0)
    if not sid:
        return None
    ch = g.get_channel_or_thread(sid) or _fils_connus.get(sid)
    if ch is not None:
        return ch
    try:
        ch = await g.fetch_channel(sid)
    except discord.NotFound:
        return None
    except discord.HTTPException as ex:
        _log(f"[EVENEMENTS:DETAIL] post {sid} {type(ex).__name__} {ex}")
        return None
    if isinstance(ch, discord.Thread):
        _fils_connus[ch.id] = ch
    return ch


async def _reveiller(salon) -> bool:
    if not (isinstance(salon, discord.Thread) and getattr(salon, "archived", False)):
        return True
    try:
        await salon.edit(archived=False)
        return True
    except discord.HTTPException as ex:
        _log(f"[EVENEMENTS:DETAIL] post {salon.id} non rouvert {type(ex).__name__} {ex}")
        return False


def _droits(g, salon, image: bool) -> str:
    """"" si le bot peut publier ici, sinon la raison (en clair, pour le site)."""
    d = salon.permissions_for(g.me)
    fil = isinstance(salon, discord.Thread)
    if not (d.send_messages_in_threads if fil else d.send_messages):
        return "Je n'ai pas le droit d'écrire dans ce post."
    if fil and getattr(salon, "locked", False) and not d.manage_threads:
        return "Ce post est verrouillé et je n'ai pas « Gérer les fils » : je ne peux pas y écrire."
    if image and not d.attach_files:
        return "Je n'ai pas le droit de joindre l'image dans ce post."
    return ""


def _lien(g, salon_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{g.id}/{int(salon_id)}/{int(message_id)}" if message_id else ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Les médias du site (images) et les fiches des affiches
# ═══════════════════════════════════════════════════════════════════════════════

_ID_MEDIA = re.compile(r"[A-Za-z0-9_-]{1,80}")
_EXT_IMAGES = ("webp", "png", "jpg", "jpeg", "gif")


def _media_defaut(media_id: str):
    if not _ID_MEDIA.fullmatch(str(media_id or "")):
        return None
    dossier = paths.base_data_dir() / "site" / "medias"
    for ext in _EXT_IMAGES:
        f = dossier / f"{media_id}.{ext}"
        if f.is_file():
            return f.read_bytes(), ext
    return None


async def _image(media_id: str):
    """(octets, extension) d'un média du site, ou None."""
    if not media_id or not _ID_MEDIA.fullmatch(str(media_id)):
        return None
    try:
        r = await _appeler(_media, media_id) if _media is not None else await asyncio.to_thread(_media_defaut,
                                                                                                media_id)
    except Exception as ex:
        _signaler("E10", "média du site illisible", ex, str(media_id))
        return None
    if isinstance(r, (bytes, bytearray)):
        r = (bytes(r), "webp")
    if not (isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], (bytes, bytearray)) and r[0]):
        return None
    ext = str(r[1] or "webp").lower().lstrip(".")
    return bytes(r[0]), (ext if ext in _EXT_IMAGES else "webp")


def _cat(catalogue: dict, type_: str) -> dict:
    x = (catalogue or {}).get(type_) or (catalogue or {}).get(type_ + "s") or {}
    return x if isinstance(x, dict) else {}


def _nom_cat(entrees: dict, cle: str, *, md: bool = True, bilingue: bool = False) -> str:
    """Le nom d'un élément du catalogue (sa clé s'il n'y est plus) ; pour Discord (`md`), échappé — et, pour un titre
    de groupe (`bilingue`), « nom · name » quand le catalogue a le nom anglais (les cartes parlent les deux)."""
    e = entrees.get(cle) if isinstance(entrees.get(cle), dict) else {}
    nom = " ".join(str(e.get("nom") or "").split()) or str(cle)
    if not md:
        return nom[:80]
    en = " ".join(str(e.get("nom_en") or "").split()) if bilingue else ""
    return discord.utils.escape_markdown((f"{nom} · {en}" if en and en.casefold() != nom.casefold() else nom)[:80])


_EMOJI_APP = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:\d{15,22}>")


def _emoji_jeu(catalogue: dict, type_: str, cle: str) -> str:
    """L'icône officielle d'un élément du jeu, si c'est un émoji d'application (jamais un émoji Unicode)."""
    e = _cat(catalogue, type_).get(cle)
    brut = str((e or {}).get("icone_emoji") or "") if isinstance(e, dict) else ""
    return f"{brut} " if _EMOJI_APP.fullmatch(brut) else ""


async def _equipage(g) -> dict:
    """Le clan tel qu'il est : les membres du rôle (sans les bots), leurs fiches, le catalogue du jeu."""
    c = await _cfg(g.id)
    role = _role_clan(g, c) if _role_clan else None
    membres = [m for m in (getattr(role, "members", None) or []) if not getattr(m, "bot", False)]
    fiches, catalogue = {}, {}
    if _fiches is not None:
        try:
            for f in await _appeler(_fiches, g) or []:
                if isinstance(f, dict) and str(f.get("membre_id", "")).isdigit():
                    fiches[int(f["membre_id"])] = f
        except Exception as ex:
            _signaler("E11", "fiches des affiches illisibles", ex)
    if _catalogue is not None:
        try:
            catalogue = await _appeler(_catalogue, g) or {}
        except Exception as ex:
            _signaler("E11", "catalogue du jeu illisible", ex)
    return {"role": role, "membres": membres, "fiches": fiches,
            "catalogue": catalogue if isinstance(catalogue, dict) else {}, "branche": _fiches is not None}


# ═══════════════════════════════════════════════════════════════════════════════
#  Validation (stricte, champ par champ)
# ═══════════════════════════════════════════════════════════════════════════════

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _entier(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, str) and re.fullmatch(r"-?\d{1,15}", x.strip()):
        return int(x.strip())
    return None


def _couleur(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x if 0 <= x <= 0xFFFFFF else None
    if isinstance(x, str):
        m = re.fullmatch(r"#?([0-9a-fA-F]{6})", x.strip())
        return int(m.group(1), 16) if m else None
    return None


def _une_ligne(x) -> str:
    return " ".join(_CTRL.sub(" ", str(x)).split())


def _paragraphes(x) -> str:
    t = str(x).replace("\r\n", "\n").replace("\r", "\n")
    return _CTRL.sub("", t).strip()


async def _valider(g, corps: dict, type_: str, avant: dict) -> tuple:
    """Les champs envoyés, vérifiés un par un → (valeurs propres, {champ: erreur}). `avant` : les valeurs
    actuelles (une image déjà en place n'est pas relue à chaque sauvegarde)."""
    propres, erreurs = {}, {}
    maintenant = _mur()
    dests = None
    for cle, brut in corps.items():
        if cle in CLES_CONTROLE:
            continue
        if cle not in CHAMPS:
            erreurs[cle] = "Champ inconnu."
            continue
        if cle in ("titre", "lieu"):
            if not isinstance(brut, str):
                erreurs[cle] = "Un texte est attendu."
                continue
            v = _une_ligne(brut)
            limite = TITRE_MAX if cle == "titre" else LIEU_MAX
            if len(v) > limite:
                erreurs[cle] = f"{limite} caractères au plus."
                continue
            propres[cle] = v
        elif cle == "texte":
            if not isinstance(brut, str):
                erreurs[cle] = "Un texte est attendu."
                continue
            v = _paragraphes(brut)
            if len(v) > TEXTE_MAX[type_]:
                erreurs[cle] = f"{TEXTE_MAX[type_]} caractères au plus pour ce type de publication."
                continue
            propres[cle] = v
        elif cle == "quand":
            if brut in (None, "", 0):
                propres[cle] = None
                continue
            v = _entier(brut)
            if v is None or v < 1_600_000_000:
                erreurs[cle] = "Une date (horodatage Unix, en secondes) est attendue."
            elif v > maintenant + HORIZON_S:
                erreurs[cle] = "Un an à l'avance au plus."
            else:
                propres[cle] = v
        elif cle in ("duree_min", "places"):
            v = _entier(brut)
            borne = DUREE_MAX if cle == "duree_min" else PLACES_MAX
            if v is None or not 0 <= v <= borne:
                erreurs[cle] = f"Un nombre entier de 0 à {borne} est attendu."
            else:
                propres[cle] = v
        elif cle == "image":
            if brut in (None, ""):
                propres[cle] = ""
                continue
            if not isinstance(brut, str) or not _ID_MEDIA.fullmatch(brut):
                erreurs[cle] = "Identifiant de média invalide."
            elif brut != (avant or {}).get("image") and await _image(brut) is None:
                erreurs[cle] = "Image introuvable : renvoie-la."
            else:
                propres[cle] = brut
        elif cle == "couleur":
            v = _couleur(brut)
            if v is None:
                erreurs[cle] = "Une couleur « #RRGGBB » est attendue."
            else:
                propres[cle] = v
        elif cle == "rappels":
            if brut is None:
                propres[cle] = []
                continue
            vals = [_entier(x) for x in brut] if isinstance(brut, list) else None
            if vals is None or any(x is None or not 0 <= x <= RAPPEL_MAX for x in vals):
                erreurs[cle] = f"Une liste de minutes avant le début (0 à {RAPPEL_MAX}) est attendue."
            elif len(set(vals)) > RAPPELS_MAX:
                erreurs[cle] = f"{RAPPELS_MAX} rappels au plus."
            else:
                propres[cle] = sorted(set(vals), reverse=True)
        elif cle == "mention":
            if brut not in MENTIONS:
                erreurs[cle] = "aucune, clan ou inscrits."
            elif brut == "inscrits" and type_ != "evenement":
                erreurs[cle] = "« inscrits » ne vaut que pour un événement."
            else:
                propres[cle] = brut
        elif cle == "destination":
            if brut in (None, ""):
                propres[cle] = ""
                continue
            v = str(brut).strip() if isinstance(brut, (str, int)) and not isinstance(brut, bool) else ""
            if dests is None:
                dests = destinations(g, await _cfg(g.id))
            if not v.isdigit() or all(d["id"] != v for d in dests):
                erreurs[cle] = "Ce post n'est pas une destination du forum du clan."
            else:
                propres[cle] = v
        elif cle in ("reponses", "discord_event", "reserve_clan"):
            if not isinstance(brut, bool):
                erreurs[cle] = "Vrai ou faux est attendu."
            else:
                propres[cle] = brut
        elif cle == "groupement":
            if brut not in GROUPEMENTS:
                erreurs[cle] = "metier, grade ou race."
            elif type_ == "metiers" and brut != "metier":
                erreurs[cle] = "L'annonce des métiers se range par métier."
            else:
                propres[cle] = brut
        elif cle == "champs":
            if not isinstance(brut, list) or any(x not in CHAMPS_LISTE for x in brut):
                erreurs[cle] = "Une liste parmi metiers, grade, race est attendue."
            else:
                propres[cle] = list(dict.fromkeys(brut))
    #  Un champ qui ne concerne pas ce type (des réponses sur une annonce) : vérifié, puis laissé de côté.
    return {k: v for k, v in propres.items() if k in CHAMPS_TYPE[type_]}, erreurs


def _normaliser(type_: str, v: dict) -> dict:
    """Un brouillon qui change de type garde ce qui est commun et redevient cohérent (« inscrits » n'existe que
    pour un événement, l'annonce des métiers se range par métier)."""
    v = dict(v)
    if type_ != "evenement" and v.get("mention") == "inscrits":
        v["mention"] = "aucune"
    if type_ == "metiers":
        v["groupement"] = "metier"
    return v


def _croiser(type_: str, v: dict) -> dict:
    """Ce qui ne tient qu'ensemble."""
    erreurs = {}
    if type_ == "evenement" and v.get("places") and not v.get("reponses"):
        erreurs["places"] = "Des places limitées demandent les boutons de réponse."
    if len(v.get("texte") or "") > TEXTE_MAX[type_]:
        erreurs["texte"] = f"{TEXTE_MAX[type_]} caractères au plus pour ce type de publication."
    return erreurs


def _controle(e: dict, maintenant: float, dests: list, eq: dict | None) -> list:
    """Ce qui empêche la publication, en clair (vide : prête)."""
    v, t = e["valeurs"], e["type"]
    out = []
    if not v["titre"]:
        out.append("Il faut un titre.")
    if t == "annonce" and not v["texte"]:
        out.append("Il faut un texte.")
    if _destination(dests, v) is None:
        out.append("Le forum du clan n'a pas ce post (ou il n'est pas installé).")
    if t == "evenement":
        if not v["quand"]:
            out.append("Il faut une date de début.")
        elif v["quand"] < maintenant + AVANCE_S:
            out.append("Le début doit être dans le futur (une minute au moins).")
        elif v["quand"] > maintenant + HORIZON_S:
            out.append("Un an à l'avance au plus.")
        if v["places"] and not v["reponses"]:
            out.append("Des places limitées demandent les boutons de réponse.")
    if t in ("metiers", "listing") and eq is not None:
        if eq["role"] is None:
            out.append("Le rôle du clan n'est pas réglé.")
        elif not eq["membres"]:
            out.append("Le rôle du clan n'a aucun membre.")
        elif t == "metiers" and not any((eq["fiches"].get(m.id) or {}).get("metiers") for m in eq["membres"]):
            out.append("Aucun membre du clan n'a de métier sur son affiche.")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Les cartes : un modèle (pour le site, l'aperçu fidèle) rendu en Components V2 (pour Discord)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  Une carte = un message : {"haut": mention au-dessus, "couleur", "blocs": [...]}. Un bloc : image (média du
#  site), bandeau, texte (des lignes : md, icône maison ou icône du jeu, niveau de titre), séparateur,
#  boutons. Le site dessine ses propres icônes (même nom) ; Discord reçoit les émojis d'application.

_PREFIXES = {0: "", 1: "# ", 2: "## ", 3: "### ", "petit": "-# "}
_STYLES = {"succes": discord.ButtonStyle.success, "secondaire": discord.ButtonStyle.secondary,
           "danger": discord.ButtonStyle.danger, "primaire": discord.ButtonStyle.primary}


def _l(md: str, icone: str | None = None, niveau=0, jeu=None) -> dict:
    d = {"md": md}
    if icone:
        d["icone"] = icone
    if niveau:
        d["niveau"] = niveau
    if jeu:
        d["jeu"] = list(jeu)
    return d


def _texte(*lignes) -> dict:
    return {"type": "texte", "lignes": [x for x in lignes if x]}


def _sep() -> dict:
    return {"type": "separateur"}


def _emoji_app(nom):
    """L'icône maison si l'émoji d'application est installé — jamais le repli Unicode de `visuels`."""
    pe = visuels.icone(nom) if nom else None
    return pe if pe is not None and getattr(pe, "id", None) else None


def _rendu(ligne: dict, catalogue: dict | None = None) -> str:
    ic = ""
    if ligne.get("icone"):
        pe = _emoji_app(ligne["icone"])
        ic = f"{pe} " if pe is not None else ""
    elif ligne.get("jeu"):
        ic = _emoji_jeu(catalogue or {}, *ligne["jeu"])
    return _PREFIXES.get(ligne.get("niveau", 0), "") + ic + ligne["md"]


def _longueur(ligne: dict) -> int:
    """Au pire (l'icône installée) : ce que la ligne pèsera chez Discord."""
    return (len(_PREFIXES.get(ligne.get("niveau", 0), "")) + len(ligne["md"])
            + (ICONE_LONGUEUR if ligne.get("icone") or ligne.get("jeu") else 0))


def _poids(b: dict) -> tuple:
    """(composants, caractères) d'un bloc."""
    t = b["type"]
    if t == "texte":
        return 1, sum(_longueur(x) for x in b["lignes"]) + max(0, len(b["lignes"]) - 1)
    if t == "boutons":
        return 1 + len(b["boutons"]), sum(len(x["label"]) for x in b["boutons"])
    if t == "bandeau":
        return 1, len(b["titre"])
    return 1, 0


def mesurer(carte: dict) -> tuple:
    """(composants, caractères) d'une carte, au pire : le conteneur, la mention au-dessus, chaque bloc."""
    n, c = 1 + (1 if carte.get("haut") else 0), len(carte.get("haut") or "")
    for b in carte["blocs"]:
        bn, bc = _poids(b)
        n, c = n + bn, c + bc
    return n, c


def _tient(blocs: list, haut: str = "") -> bool:
    n, c = mesurer({"haut": haut, "blocs": blocs})
    return n <= COMPOSANTS_CIBLE and c <= CARACTERES_CIBLE


def _bouton_discord(eid: int, x: dict):
    emoji = _emoji_app(x.get("icone"))
    style = _STYLES.get(x.get("style"), discord.ButtonStyle.secondary)
    if x.get("url"):
        return Button(label=x["label"], url=x["url"], emoji=emoji)
    action = x.get("action") or ""
    if eid and action and not x.get("desactive"):
        if action.startswith("r:"):
            return BoutonReponse(eid, action[2:], label=x["label"], style=style, emoji=emoji)
        if action == "vu":
            return BoutonVu(eid, label=x["label"], emoji=emoji)
    return Button(label=x["label"], style=style, emoji=emoji, disabled=True)


def vue(carte: dict, eid: int, *, image_nom: str = "", catalogue: dict | None = None,
        marque: bool = True) -> LayoutView:
    """Une carte du modèle, en Components V2 (persistante : ses boutons sont des DynamicItem). `marque` : le
    conteneur porte MARQUE + numéro — les cartes d'une publication se retrouvent dans le post (pas les rappels)."""
    v = LayoutView(timeout=None)
    if carte.get("haut"):
        v.add_item(discord.ui.TextDisplay(carte["haut"]))
    items = []
    for b in carte["blocs"]:
        t = b["type"]
        if t == "image":
            if image_nom:
                items.append(discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{image_nom}")))
        elif t == "bandeau":
            u = visuels.url(b["cle"])
            if u:
                items.append(discord.ui.MediaGallery(discord.MediaGalleryItem(u, description=b["titre"])))
        elif t == "texte":
            items.append(discord.ui.TextDisplay("\n".join(_rendu(x, catalogue) for x in b["lignes"])))
        elif t == "separateur":
            items.append(discord.ui.Separator())
        elif t == "boutons":
            items.append(discord.ui.ActionRow(*[_bouton_discord(eid, x) for x in b["boutons"]]))
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(int(carte["couleur"])),
                                    **({"id": MARQUE + int(eid)} if marque and eid else {})))
    return v


def _duree_txt(minutes: int) -> str:
    j, reste = divmod(int(minutes), 1440)
    h, m = divmod(reste, 60)
    morceaux = ([f"{j} j"] if j else []) + ([f"{h} h" + (f" {m:02d}" if m and not j else "")] if h else []) + \
        ([f"{m} min"] if m and (j or not h) else [])
    return " ".join(morceaux) or "0 min"


def _fin(v: dict) -> int:
    q = int(v.get("quand") or 0)
    return q + (int(v["duree_min"]) * 60 if v.get("duree_min") else FIN_SANS_DUREE_S) if q else 0


def phase_de(e: dict, maintenant: float) -> str:
    """À venir, en cours ou terminé : l'heure le dit (l'état affiché est noté à part, `phase`)."""
    v = e["valeurs"]
    q = int(v.get("quand") or 0)
    if not q or maintenant < q:
        return "a_venir"
    return "en_cours" if maintenant < _fin(v) else "termine"


def _mention_publication(g, c: dict, v: dict, salon) -> tuple:
    """(le texte au-dessus de la carte, les mentions permises, un avertissement)."""
    if v.get("mention") != "clan":
        return "", discord.AllowedMentions.none(), ""
    role = _role_clan(g, c) if _role_clan else None
    if role is None:
        return "", discord.AllowedMentions.none(), "Le rôle du clan n'est pas réglé : personne ne sera mentionné."
    peut = bool(getattr(role, "mentionable", False)) or (salon is not None and salon.permissions_for(g.me).mention_everyone)
    return (role.mention, discord.AllowedMentions(everyone=False, users=False, roles=[role]),
            "" if peut else "Le rôle du clan n'est pas mentionnable et je n'ai pas « Mentionner @everyone » : "
                            "personne ne sera notifié.")


def _boutons_reponse(n_d: int, places: int, actif: bool) -> dict:
    complet = bool(places) and n_d >= places
    out = []
    for choix in ("d", "p", "n"):
        fr, en = CHOIX[choix]
        label = "Complet · Full" if choix == "d" and complet else f"{fr} · {en}"
        out.append({"label": label, "style": "succes" if choix == "d" else "secondaire", "icone": CHOIX_ICONE[choix],
                    "action": f"r:{choix}", "desactive": not actif or (choix == "d" and complet)})
    return {"type": "boutons", "boutons": out}


def _lignes_quand(v: dict, phase: str, statut: str) -> list:
    q, fin = int(v.get("quand") or 0), _fin(v)
    lignes = []
    if not q:
        lignes.append(_l("**Début · Starts** à choisir · to be set", "calendrier"))
    elif statut == "annule":
        lignes += [_l("Annulé · Cancelled", "annuler", 3), _l(f"Prévu le · Was planned for <t:{q}:F>", niveau="petit")]
    elif phase == "a_venir":
        lignes += [_l(f"**Début · Starts** <t:{q}:F>", "calendrier"), _l(f"<t:{q}:R>", "minuteur", 3)]
    elif phase == "en_cours":
        lignes.append(_l("En cours · Live now", "minuteur", 3))
        lignes.append(_l(f"Fin · Ends <t:{fin}:R>" if v.get("duree_min") else f"Commencé · Started <t:{q}:R>",
                         niveau="petit"))
    else:
        lignes.append(_l("Terminé · Ended" if v.get("duree_min") else "A eu lieu · Took place", niveau=3))
        lignes.append(_l(f"<t:{q}:F>" + (f" → <t:{fin}:t>" if v.get("duree_min") else ""), niveau="petit"))
    if statut != "annule":
        if v.get("duree_min"):
            lignes.append(_l(f"**Durée · Duration** {_duree_txt(v['duree_min'])}", "horloge"))
        if v.get("lieu"):
            lignes.append(_l(f"**Lieu · Location** RELL Seas · {discord.utils.escape_markdown(v['lieu'])}", "lieu"))
    return lignes


def _liste_noms(ids: list, budget: int) -> str:
    """Les mentions qui tiennent dans `budget` caractères, puis « +N autres · others »."""
    morceaux, taille = [], 0
    for k, uid in enumerate(ids):
        m = f"<@{uid}>"
        reste = len(ids) - k - 1
        suffixe = len(f" +{reste} autres · others") if reste else 0
        if taille + len(m) + 2 + suffixe > budget:
            return ", ".join(morceaux) + f" +{len(ids) - k} autres · others"
        morceaux.append(m)
        taille += len(m) + 2
    return ", ".join(morceaux)


def _pied(e: dict) -> dict:
    """Le bas de la carte : le clan (et la date, ou « réservé au clan ») ; pour un événement à venir, les rappels
    qui partiront encore et qui ils mentionnent — la carte ne promet que ce qui arrivera."""
    v = e["valeurs"]
    lignes = [_l(NOM_CLAN + (" · Réservé au clan · Clan only" if e["type"] == "evenement" and v.get("reserve_clan")
                             else f" · <t:{int(e['publie'])}:D>" if e["type"] != "evenement" and e.get("publie")
                             else ""), "ancre", "petit")]
    restants = [m for m in v.get("rappels") or [] if m not in (e.get("rappels_faits") or [])]
    if e["type"] == "evenement" and restants and e["statut"] in ("brouillon", "publie") \
            and (e.get("phase") or "a_venir") == "a_venir":
        quand = ([", ".join(_duree_txt(m) for m in restants if m > 0) + " avant · before"]
                 if any(m > 0 for m in restants) else []) + (["au début · at start"] if 0 in restants else [])
        lignes.append(_l("Rappels · Reminders : " + " · ".join(quand), "cloche", "petit"))
        if v.get("mention") != "aucune" and v.get("reponses"):
            lignes.append(_l("Les rappels mentionnent les disponibles · Reminders ping available members",
                             niveau="petit"))
    return _texte(*lignes)


def _cartes_evenement(g, e: dict, rep: dict, maintenant: float, haut: str) -> list:
    v, statut = e["valeurs"], e["statut"]
    if statut == "brouillon":   # l'aperçu : les rappels déjà passés ne partiront pas, la carte ne les promet pas
        e = {**e, "rappels_faits": sorted(_rappels_dus(e, maintenant)[1])}
    phase = phase_de(e, maintenant) if statut in ("publie", "brouillon", "envoi", "incertain") else "termine"
    actif = statut in ("publie", "brouillon") and phase in ("a_venir", "en_cours") and statut != "annule"
    blocs = []
    if v.get("image"):
        blocs.append({"type": "image", "media": v["image"]})
    titre = v["titre"] or "(sans titre)"
    blocs.append(_texte(_l(titre, niveau=2), _l("Événement du clan · Clan event", "drapeau", "petit")))
    if v.get("texte"):
        blocs.append(_texte(_l(v["texte"])))
    blocs.append(_sep())
    blocs.append(_texte(*_lignes_quand(v, phase, statut)))
    #  Ceux qui ont quitté le serveur ne comptent plus (ni dans la liste, ni dans les places : `repondre` aussi).
    presents = [u for u in rep.get("d") or [] if g is None or g.get_member(u) is not None]
    pied = _pied(e)
    if v.get("reponses"):
        n_d, n_p, n_n = len(presents), len(rep.get("p") or []), len(rep.get("n") or [])
        titre_d = ("Disponibles · Available" if phase != "termine" else "Étaient disponibles · Were available")
        places = int(v.get("places") or 0)
        tete = _l(f"**{titre_d} — {n_d}" + (f" / {places} places · spots" if places else "") + "**"
                  + (" · **Complet · Full**" if places and n_d >= places and actif else ""), "valider")
        autres = [_l(f"**Peut-être · Maybe — {n_p}**", "peut_etre"),
                  _l(f"**Pas disponibles · Unavailable — {n_n}**", "annuler")]
        boutons = _boutons_reponse(n_d, int(v.get("places") or 0), actif) if actif else None
        base = blocs + [_sep(), _texte(tete, _l("x"), *autres)] + ([boutons] if boutons else []) + [pied]
        budget = CARACTERES_CIBLE - mesurer({"haut": haut, "blocs": base})[1] + 1
        noms = (_l(_liste_noms(presents, max(0, budget))) if presents
                else _l("Personne pour l'instant · Nobody yet" if actif else "Personne · Nobody", niveau="petit"))
        blocs += [_sep(), _texte(tete, noms, *autres)] + ([boutons] if boutons else [])
    blocs.append(pied)
    return [{"haut": haut, "couleur": int(v.get("couleur") or COULEURS["evenement"]), "blocs": blocs}]


def _cartes_annonce(e: dict, rep: dict, haut: str) -> list:
    v = e["valeurs"]
    blocs = []
    if v.get("image"):
        blocs.append({"type": "image", "media": v["image"]})
    else:
        cle, titre = BANDEAUX["annonce"]
        blocs.append({"type": "bandeau", "cle": cle, "titre": titre})
    blocs.append(_texte(_l(v["titre"] or "(sans titre)", niveau=2)))
    if v.get("texte"):
        blocs.append(_texte(_l(v["texte"])))
    blocs += [_sep(), _pied(e)]
    if e["statut"] in ("publie", "brouillon", "envoi", "incertain"):
        n = len(rep.get("v") or [])
        blocs.append({"type": "boutons", "boutons": [
            {"label": "Vu · Seen" + (f" · {n}" if n else ""), "style": "succes", "icone": "valider", "action": "vu",
             "desactive": e["statut"] not in ("publie", "brouillon")}]})
    return [{"haut": haut, "couleur": int(v.get("couleur") or COULEURS["annonce"]), "blocs": blocs}]


def _groupes(eq: dict, groupement: str, *, avec_sans: bool) -> list:
    """[(tête, [membres])] : chaque métier (un membre à plusieurs métiers est dans chacun), grade ou race,
    dans l'ordre du catalogue ; ceux sans fiche à la fin (le listing seulement)."""
    entrees = _cat(eq["catalogue"], groupement)
    groupes: dict = {}
    sans = []
    for m in eq["membres"]:
        f = eq["fiches"].get(m.id) or {}
        if groupement == "metier":
            cles = [str(k) for k in (f.get("metiers") or []) if str(k or "").strip()]
        else:
            cles = [str(f.get(groupement))] if str(f.get(groupement) or "").strip() else []
        if not cles:
            sans.append(m)
        for k in dict.fromkeys(cles):
            groupes.setdefault(k, []).append(m)
    ordre = [k for k in entrees if k in groupes] + sorted((k for k in groupes if k not in entrees), key=str.casefold)

    def nom(m):
        return (getattr(m, "display_name", "") or "").casefold()
    out = [({"cle": k, "nom": _nom_cat(entrees, k, bilingue=True), "jeu": (groupement, k) if k in entrees else None},
            sorted(groupes[k], key=nom)) for k in ordre]
    if avec_sans and sans:
        out.append(({"cle": "", "nom": SANS_GROUPE[groupement], "jeu": None}, sorted(sans, key=nom)))
    return out


def _ligne_membre(m, f: dict, champs: list, groupement: str, catalogue: dict) -> str:
    morceaux = [f"<@{m.id}>"]
    for ch in champs:
        if ch == "grade" and groupement != "grade" and str(f.get("grade") or "").strip():
            morceaux.append(_nom_cat(_cat(catalogue, "grade"), str(f["grade"])))
        elif ch == "race" and groupement != "race" and str(f.get("race") or "").strip():
            morceaux.append(_nom_cat(_cat(catalogue, "race"), str(f["race"])))
        elif ch == "metiers" and groupement != "metier" and f.get("metiers"):
            morceaux.append(", ".join(_nom_cat(_cat(catalogue, "metier"), str(k)) for k in f["metiers"]))
    return " · ".join(morceaux)


def _blocs_groupe(tete: dict, lignes: list) -> list:
    """Un groupe = un bloc (un composant) ; trop long, il continue dans un autre (« suite »)."""
    jeu = tete["jeu"]
    entete = _l(f"{tete['nom']} — {len(lignes)}", niveau=3, jeu=jeu)
    blocs, cur = [], [entete]
    taille = _longueur(entete)
    for ln in lignes:
        if taille + len(ln) + 1 > LIGNES_GROUPE_MAX and len(cur) > 1:
            blocs.append(_texte(*cur))
            cur = [_l(f"{tete['nom']} (suite · cont.)", niveau=3, jeu=jeu)]
            taille = _longueur(cur[0])
        cur.append(_l(ln))
        taille += len(ln) + 1
    blocs.append(_texte(*cur))
    return blocs


def _empaqueter(premiere: list, corps: list, pied: dict, titre: str, couleur: int, haut: str = "") -> list:
    """Les blocs répartis en cartes de 38 composants et 3 800 caractères au plus (marge sous les limites de
    Discord) ; chaque carte suivante dit « suite (2/3) »."""
    gabarit = _texte(_l(f"{titre} · suite · continued (99/99)", niveau="petit"))
    pages, cur = [], list(premiere)
    for b in corps:
        if _tient(cur + [b], "" if pages else haut):
            cur.append(b)
            continue
        pages.append(cur)
        cur = [gabarit, b]
    if not _tient(cur + [pied], "" if pages else haut):
        pages.append(cur)
        cur = [gabarit]
    pages.append(cur + [pied])
    n = len(pages)
    cartes = []
    for k, blocs in enumerate(pages):
        blocs = [(_texte(_l(f"{titre} · suite · continued ({k + 1}/{n})", niveau="petit")) if b is gabarit else b)
                 for b in blocs]
        cartes.append({"haut": haut if k == 0 else "", "couleur": couleur, "blocs": blocs})
    return cartes


def _cartes_liste(e: dict, eq: dict, haut: str) -> list:
    v, t = e["valeurs"], e["type"]
    groupement = "metier" if t == "metiers" else v.get("groupement") or "grade"
    groupes = _groupes(eq, groupement, avec_sans=(t == "listing"))
    premiere = []
    if v.get("image"):
        premiere.append({"type": "image", "media": v["image"]})
    elif t in BANDEAUX:
        cle, titre_b = BANDEAUX[t]
        premiere.append({"type": "bandeau", "cle": cle, "titre": titre_b})
    titre = v["titre"] or NOMS_TYPES[t]
    if t == "metiers":
        dans = {m.id for _t, ms in groupes for m in ms}
        resume = f"**{len(dans)} membres · members** · **{len(groupes)} métiers · trades**"
    else:
        fr, en = GROUPES_NOMS[groupement]
        resume = f"**{len(eq['membres'])} membres · members** · par {fr} · by {en}"
    premiere.append(_texte(_l(titre, niveau=2), _l(resume, "membres")))
    if v.get("texte"):
        premiere.append(_texte(_l(v["texte"])))
    premiere.append(_sep())
    corps = []
    for tete, membres in groupes:
        lignes = [_ligne_membre(m, eq["fiches"].get(m.id) or {}, v.get("champs") or [], groupement, eq["catalogue"])
                  for m in membres]
        corps += _blocs_groupe(tete, lignes)
    if not corps:
        corps.append(_texte(_l("Personne à afficher pour l'instant · Nobody to show yet", niveau="petit")))
    pied = _pied(e)
    return _empaqueter(premiere, corps, pied, titre, int(v.get("couleur") or COULEURS[t]), haut)


async def cartes(g, e: dict, *, maintenant: float | None = None, rep: dict | None = None, salon=None,
                 eq: dict | None = None) -> tuple:
    """Les cartes d'une publication (le modèle), et le contexte du rendu : {"catalogue", "avertissements",
    "mentions" (celles permises à la publication), "equipage"}."""
    maintenant = _mur() if maintenant is None else maintenant
    c = await _cfg(g.id)
    rep = rep if rep is not None else await _reponses(e["id"])
    v = e["valeurs"]
    if salon is None and v.get("mention") == "clan":
        dest = _destination(destinations(g, c), v)
        sid = e["salon_id"] or (int(dest["id"]) if dest else 0)
        salon = g.get_channel_or_thread(sid) if sid else None
    haut, mentions, avert = _mention_publication(g, c, v, salon)
    contexte = {"catalogue": {}, "avertissements": [avert] if avert else [], "mentions": mentions, "equipage": None}
    if e["type"] == "evenement":
        return _cartes_evenement(g, e, rep, maintenant, haut), contexte
    if e["type"] == "annonce":
        return _cartes_annonce(e, rep, haut), contexte
    eq = eq if eq is not None else await _equipage(g)
    contexte["catalogue"] = eq["catalogue"]
    contexte["equipage"] = eq
    if not eq["branche"]:
        contexte["avertissements"].append("Les fiches des affiches ne sont pas encore branchées : personne n'a de "
                                          "métier, de grade ni de race.")
    return _cartes_liste(e, eq, haut), contexte


# ═══════════════════════════════════════════════════════════════════════════════
#  Les boutons persistants (ils répondent après un redémarrage)
# ═══════════════════════════════════════════════════════════════════════════════

class BoutonReponse(discord.ui.DynamicItem[Button], template=r"ev:r:(?P<eid>\d+):(?P<choix>[dpn])"):
    """« Disponible · Peut-être · Pas disponible » : une réponse par membre, qu'il peut changer."""

    def __init__(self, eid: int, choix: str, *, label: str | None = None, style=None, emoji=None):
        self.eid, self.choix = int(eid), choix
        fr, en = CHOIX.get(choix, CHOIX["d"])
        super().__init__(Button(label=label or f"{fr} · {en}", style=style or discord.ButtonStyle.secondary,
                                emoji=emoji, custom_id=f"ev:r:{int(eid)}:{choix}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]), match["choix"])

    async def callback(self, i: discord.Interaction):
        await _sans_echec(i, repondre(i, self.eid, self.choix))


class BoutonVu(discord.ui.DynamicItem[Button], template=r"ev:vu:(?P<eid>\d+)"):
    """« Vu · Seen » sous une annonce du clan venue du site (le même geste que `annonces.BoutonVu`)."""

    def __init__(self, eid: int, *, label: str = "Vu · Seen", emoji=None):
        self.eid = int(eid)
        super().__init__(Button(label=label, style=discord.ButtonStyle.success, emoji=emoji,
                                custom_id=f"ev:vu:{int(eid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]))

    async def callback(self, i: discord.Interaction):
        await _sans_echec(i, marquer_vu(i, self.eid))


def _vue_avis(texte: str, couleur=Palette.NEUTRAL) -> LayoutView:
    v = LayoutView(timeout=60)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), accent_color=couleur))
    return v


def _effacer_plus_tard(i, delai: float | None = None) -> None:
    """« Un avis est pour la personne seule » : il s'efface tout seul."""
    supprimer = getattr(i, "delete_original_response", None)
    if supprimer is None:
        return

    async def _plus_tard():
        await asyncio.sleep(AVIS_S if delai is None else delai)
        try:
            await supprimer()
        except discord.HTTPException:
            pass  # déjà fermé par le membre, ou le jeton de l'interaction a expiré : rien à faire
    t = asyncio.create_task(_plus_tard())
    _taches.add(t)
    t.add_done_callback(_taches.discard)


async def _avis(i, texte: str, couleur=Palette.NEUTRAL, delai: float | None = None) -> None:
    vue_ = _vue_avis(texte, couleur)
    if i.response.is_done():
        await i.followup.send(view=vue_, ephemeral=True)
    else:
        await i.response.send_message(view=vue_, ephemeral=True)
    _effacer_plus_tard(i, delai)


async def _sans_echec(i, travail) -> None:
    """Le filet des boutons persistants : une erreur répond quand même, pour soi, puis remonte (discord.py la
    journalise, /stats la compte)."""
    try:
        await travail
    except Exception as ex:
        _signaler("E19", "bouton en échec", ex)
        try:
            await _avis(i, tr("souci", await langue_de(i)), Palette.WARNING)
        except discord.HTTPException as ex2:
            _log(f"[EVENEMENTS][E19:DETAIL] réponse impossible {type(ex2).__name__} {ex2}")
        raise


async def _du_clan(g, membre) -> bool:
    c = await _cfg(g.id)
    role = _role_clan(g, c) if _role_clan else None
    if role is None:
        return True   # pas de rôle du clan réglé : personne n'est exclu par erreur
    return role in (getattr(membre, "roles", None) or []) or bool(_est_tete and _est_tete(g, membre))


async def repondre(i, eid: int, choix: str) -> None:
    if not pret():
        return await _avis(i, tr("demarre", await langue_de(i)), Palette.WARNING, DEMARRE_S)
    await i.response.defer(ephemeral=True, thinking=True)   # répondre d'abord : la base peut faire attendre
    langue = await langue_de(i)
    e = await charger(eid)
    if e is None or i.guild is None or e["guild_id"] != i.guild.id or e["type"] != "evenement" \
            or not e["valeurs"].get("reponses"):
        return await _avis(i, tr("introuvable", langue))
    v = e["valeurs"]
    if e["statut"] == "annule":
        return await _avis(i, tr("annule", langue))
    phase = phase_de(e, _mur())
    if e["statut"] != "publie" or phase == "termine":
        return await _avis(i, tr("fini", langue))
    if v.get("reserve_clan") and not await _du_clan(i.guild, i.user):
        return await _avis(i, tr("reserve", langue), Palette.WARNING)
    uid = i.user.id
    async with _verrou(eid):   # la place comptée et prise d'un seul tenant : jamais 21 inscrits pour 20 places
        async with _get_db() as db:
            async with db.execute("SELECT choix FROM clan_evenements_reponses WHERE evenement_id=? AND membre_id=?",
                                  (int(eid), uid)) as cur:
                r = await cur.fetchone()
            avant = str(r[0]) if r else ""
            resultat = "ok"
            if avant == choix:
                resultat = "deja"
            elif choix == "d" and v.get("places"):
                async with db.execute("SELECT membre_id FROM clan_evenements_reponses WHERE evenement_id=? AND"
                                      " choix='d'", (int(eid),)) as cur:
                    pris = [int(r[0]) for r in await cur.fetchall()]
                #  Une place tenue par quelqu'un qui a quitté le serveur est libre (la carte ne le compte plus).
                if sum(1 for u in pris if i.guild.get_member(u) is not None) >= int(v["places"]):
                    resultat = "complet"
            if resultat == "ok":
                await db.execute("INSERT INTO clan_evenements_reponses(evenement_id, membre_id, choix, quand)"
                                 " VALUES(?,?,?,?) ON CONFLICT(evenement_id, membre_id) DO UPDATE SET"
                                 " choix=excluded.choix, quand=excluded.quand", (int(eid), uid, choix, int(_mur())))
                await db.commit()
    nom = CHOIX[choix][1 if langue == "en" else 0]
    if resultat == "complet":
        return await _avis(i, tr("complet", langue, n=v["places"]), Palette.WARNING)
    texte = tr("deja" if resultat == "deja" else "ok", langue, choix=nom)
    if phase == "a_venir" and v.get("quand"):
        texte += " " + tr("debut", langue, q=int(v["quand"]))
    restants = [m for m in v.get("rappels") or [] if m not in e["rappels_faits"]]
    if choix == "d" and v.get("mention") != "aucune" and restants and phase == "a_venir":
        texte += "\n-# " + tr("rappel_toi", langue)
    await _avis(i, texte, Palette.SUCCESS if resultat == "ok" else Palette.NEUTRAL)
    if resultat == "ok":
        planifier_maj(i.guild, eid)


async def marquer_vu(i, eid: int) -> None:
    if not pret():
        return await _avis(i, tr("demarre", await langue_de(i)), Palette.WARNING, DEMARRE_S)
    await i.response.defer(ephemeral=True, thinking=True)
    langue = await langue_de(i)
    e = await charger(eid)
    if e is None or i.guild is None or e["guild_id"] != i.guild.id or e["type"] != "annonce" \
            or e["statut"] != "publie":
        return await _avis(i, tr("annonce_introuvable", langue))
    async with _get_db() as db:
        cur = await db.execute("INSERT OR IGNORE INTO clan_evenements_reponses(evenement_id, membre_id, choix, quand)"
                               " VALUES(?,?,?,?)", (int(eid), i.user.id, "v", int(_mur())))
        nouveau = (cur.rowcount or 0) > 0
        await db.commit()
    await _avis(i, tr("vu_ok" if nouveau else "vu_deja", langue), Palette.SUCCESS if nouveau else Palette.NEUTRAL)
    if nouveau:
        planifier_maj(i.guild, eid)


def planifier_maj(g, eid: int) -> None:
    """La carte se réécrit une fois pour toute une rafale de clics."""
    if int(eid) not in _maj_prevues:
        _maj_prevues[int(eid)] = asyncio.create_task(_maj_apres(g, int(eid)))


async def _maj_apres(g, eid: int) -> None:
    try:
        await asyncio.sleep(MAJ_CARTE_S)
    finally:
        _maj_prevues.pop(eid, None)
    try:
        await maj_carte(g, eid)
    except Exception as ex:
        _signaler("E3", "carte non mise à jour", ex, f"evenement={eid}")


async def maj_carte(g, eid: int) -> bool:
    """La carte d'un événement ou d'une annonce, réécrite d'après la base (compteurs, état, noms)."""
    async with _verrou(eid):
        e = await charger(eid)
        if e is None or e["type"] not in ("evenement", "annonce") or e["statut"] not in ("publie", "annule") \
                or not e["messages"]:
            return False
        salon = await _salon(g, e["salon_id"])
        if salon is None or not await _reveiller(salon):
            return False
        carte, contexte = await cartes(g, e)
        nom = _nom_image(e)
        try:
            await salon.get_partial_message(e["messages"][0]).edit(
                view=vue(carte[0], eid, image_nom=nom, catalogue=contexte["catalogue"]),
                allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            await _ecrire("UPDATE clan_evenements SET note=? WHERE id=?",
                          ("Le message de la carte a été supprimé sur Discord.", int(eid)))
            return False
        except discord.HTTPException as ex:
            _signaler("E3", "carte non mise à jour", ex, f"evenement={eid}")
            return False
    _releve["cartes"] += 1
    return True


def _nom_image(e: dict) -> str:
    """Le nom de la pièce jointe d'une carte (posée à la publication, gardée à chaque réécriture)."""
    return f"clan_{e['id']}.{e['valeurs'].get('image_ext') or 'webp'}" if e["valeurs"].get("image") else ""


# ═══════════════════════════════════════════════════════════════════════════════
#  L'évènement programmé natif de Discord
# ═══════════════════════════════════════════════════════════════════════════════

def peut_evenements(g) -> bool:
    p = getattr(getattr(g, "me", None), "guild_permissions", None)
    return bool(getattr(p, "create_events", False) or getattr(p, "manage_events", False))


SANS_PERMISSION = ("L'évènement Discord n'a pas été créé : il me manque la permission « Créer des évènements » "
                   "(Paramètres du serveur → Rôles). La carte, elle, est publiée.")


def _champs_natifs(e: dict, lien: str) -> dict:
    v = e["valeurs"]
    debut = datetime.fromtimestamp(int(v["quand"]), timezone.utc)
    fin = datetime.fromtimestamp(_fin(v), timezone.utc)
    description = (v.get("texte") or "")[:800]
    if lien:
        description = (description + "\n\n" if description else "") + f"Réponds dans le forum du clan : {lien}"
    lieu = f"RELL Seas · {v['lieu']}" if v.get("lieu") else "RELL Seas"
    return {"name": (v.get("titre") or "Événement du clan")[:100], "start_time": debut, "end_time": fin,
            "description": description[:1000], "location": lieu[:100]}


async def _natif(g, ident: int):
    if not ident:
        return None
    ev = g.get_scheduled_event(int(ident)) if hasattr(g, "get_scheduled_event") else None
    if ev is not None:
        return ev
    try:
        return await g.fetch_scheduled_event(int(ident))
    except discord.NotFound:
        return None


async def _creer_natif(g, e: dict, lien: str) -> tuple:
    """(identifiant, avertissement) de l'évènement programmé natif. Ne lève jamais : la carte est déjà partie."""
    if not peut_evenements(g):
        return 0, SANS_PERMISSION
    try:
        champs = _champs_natifs(e, lien)
        image = await _image(e["valeurs"].get("image") or "")
        for avec_image in ((True, False) if image else (False,)):
            try:
                ev = await g.create_scheduled_event(entity_type=discord.EntityType.external,
                                                    privacy_level=discord.PrivacyLevel.guild_only,
                                                    reason="Événement du clan (site)",
                                                    **({"image": image[0]} if avec_image else {}), **champs)
                return int(ev.id), ("" if avec_image or not image else
                                    "Discord a refusé l'image pour l'évènement programmé : il est créé sans image.")
            except discord.Forbidden:
                return 0, SANS_PERMISSION
            except discord.HTTPException:
                if not avec_image:
                    raise
    except Exception as ex:
        _signaler("E6", "évènement Discord non créé", ex, f"evenement={e['id']}")
    return 0, "Discord a refusé l'évènement programmé : la carte, elle, est publiée."


async def _modifier_natif(g, e: dict, lien: str, *, debut_change: bool) -> str:
    """L'évènement natif reprend le titre, le texte, l'horaire et le lieu. Ne lève jamais (la carte est à jour)."""
    try:
        ev = await _natif(g, e["discord_event_id"])
        if ev is None:
            return ""
        champs = _champs_natifs(e, lien)
        if not debut_change or phase_de(e, _mur()) != "a_venir":
            champs.pop("start_time", None)
        await ev.edit(**champs, reason="Événement du clan modifié (site)")
        return ""
    except Exception as ex:
        _signaler("E6", "évènement Discord non modifié", ex, f"evenement={e['id']}")
        return "L'évènement Discord n'a pas pu être mis à jour : vérifie-le dans la liste des évènements."


async def _suivre_natif(g, e: dict, phase: str = "", *, annuler: bool = False) -> None:
    """L'évènement natif suit le nôtre : démarré au début, terminé à la fin, annulé avec lui."""
    try:
        ev = await _natif(g, e["discord_event_id"])
        if ev is None:
            return
        statut = getattr(ev, "status", None)
        if annuler:
            if statut == discord.EventStatus.scheduled:
                await ev.cancel(reason="Événement du clan annulé")
            elif statut == discord.EventStatus.active:
                await ev.end(reason="Événement du clan annulé")
        elif phase == "en_cours" and statut == discord.EventStatus.scheduled:
            await ev.start(reason="Début de l'événement du clan")
        elif phase == "termine":
            if statut == discord.EventStatus.scheduled:
                await ev.start(reason="Événement du clan")
                statut = discord.EventStatus.active
            if statut == discord.EventStatus.active:
                await ev.end(reason="Fin de l'événement du clan")
    except discord.HTTPException as ex:   # Discord a pu le faire de lui-même : on ne s'acharne pas
        _log(f"[EVENEMENTS:DETAIL] évènement natif {e['id']} {type(ex).__name__} {ex}")
    except Exception as ex:
        _signaler("E6", "évènement Discord non suivi", ex, f"evenement={e['id']}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Publier, modifier, annuler (en ligne seulement)
# ═══════════════════════════════════════════════════════════════════════════════

def _marque(msg) -> set:
    """Les identifiants des conteneurs d'un message (Components V2 lus depuis Discord)."""
    out = set()
    for comp in getattr(msg, "components", None) or []:
        ident = comp.get("id") if isinstance(comp, dict) else getattr(comp, "id", None)
        if isinstance(ident, int):
            out.add(ident)
    return out


_ILLISIBLE = object()


async def _retrouver(g, salon, eid: int):
    """Après une erreur d'envoi (ou un redémarrage pendant l'envoi) : les messages de cette publication déjà
    arrivés (une erreur 5xx ne prouve pas que Discord ne les a pas reçus). [ids] du plus ancien au plus
    récent, [] s'il n'y en a pas, `_ILLISIBLE` si le post ne se relit pas."""
    moi, cherche = getattr(getattr(g, "me", None), "id", None), MARQUE + int(eid)
    trouves = []
    try:
        async for m in salon.history(limit=50):
            if getattr(getattr(m, "author", None), "id", moi) == moi and cherche in _marque(m):
                trouves.append(int(m.id))
    except Exception as ex:
        _signaler("E7", "post non relu après une erreur d'envoi", ex, f"evenement={eid}")
        return _ILLISIBLE
    return sorted(trouves)


async def _envoyer_cartes(g, salon, e: dict, cartes_: list, contexte: dict, image) -> tuple:
    """Envoie les cartes une à une (l'image et la mention sur la première). Rend (ids des messages, "" |
    "refus" | "incertain")."""
    nom = _nom_image(e) if image is not None else ""
    ids = []
    for k, carte in enumerate(cartes_):
        envoi = {"view": vue(carte, e["id"], image_nom=nom if k == 0 else "", catalogue=contexte["catalogue"]),
                 "allowed_mentions": contexte["mentions"] if k == 0 else discord.AllowedMentions.none()}
        if k == 0 and image is not None:
            envoi["file"] = discord.File(io.BytesIO(image[0]), filename=nom)
        try:
            msg = await salon.send(**envoi)
        except Exception as ex:
            _signaler("E1", "carte non publiée", ex, f"evenement={e['id']} carte={k + 1}/{len(cartes_)}")
            deja = await _retrouver(g, salon, e["id"])
            if deja is _ILLISIBLE:
                return ids, "incertain"
            if len(deja) > len(ids):        # elle est arrivée malgré l'erreur
                ids = list(deja)
                continue
            return ids, "refus"
        ids.append(int(msg.id))
    return ids, ""


async def publier(g, auteur, eid: int, *, version=None, forcer: bool = False) -> tuple:
    """La publication sur Discord, une seule fois. Rend (status, corps)."""
    async with _verrou(eid):
        e = await charger(eid)
        if e is None or e["guild_id"] != g.id:
            return 404, {"erreur": "Publication introuvable."}
        if e["statut"] == "envoi":
            return 409, {"erreur": "La publication est déjà en cours.", "actuelle": await _vers_site(g, e)}
        if e["statut"] not in ("brouillon",) and not (forcer and e["statut"] == "incertain"):
            lien = _lien(g, e["salon_id"], e["messages"][0]) if e["messages"] else ""
            return 409, {"erreur": "Déjà publiée." if e["statut"] == "publie" else "Ce n'est plus un brouillon.",
                         "lien": lien, "actuelle": await _vers_site(g, e)}
        if version is not None and int(version) != e["version"]:
            return 409, {"conflit": True, "actuelle": await _vers_site(g, e)}
        c = await _cfg(g.id)
        maintenant = _mur()
        dests = destinations(g, c)
        eq = await _equipage(g) if e["type"] in ("metiers", "listing") else None
        erreurs = _controle(e, maintenant, dests, eq)
        image = await _image(e["valeurs"].get("image") or "")
        if e["valeurs"].get("image") and image is None:
            erreurs.append("L'image n'est plus sur le site : renvoie-la.")
        if erreurs:
            return 400, {"erreur": erreurs[0], "erreurs": erreurs}
        dest = _destination(dests, e["valeurs"])
        salon = await _salon(g, int(dest["id"]))
        if salon is None:
            return 400, {"erreur": "Ce post du forum du clan n'existe plus."}
        if not await _reveiller(salon):
            return 400, {"erreur": "Ce post est archivé et je ne peux pas le rouvrir."}
        refus = _droits(g, salon, bool(e["valeurs"].get("image")))
        if refus:
            return 400, {"erreur": refus}
        #  Le verrou tient ce processus ; la base tient tout le reste (un second processus, un redémarrage).
        _id, n = await _ecrire("UPDATE clan_evenements SET statut='envoi', envoi_le=?, version=version+1, maj=?,"
                               " maj_par=? WHERE id=? AND version=? AND statut IN ('brouillon', 'incertain')",
                               (int(maintenant), int(maintenant), auteur.id, int(eid), e["version"]))
        if not n:
            e = await charger(eid)
            return 409, {"erreur": "Cette publication vient de changer : relis-la.", "actuelle": await _vers_site(g, e)}
        #  Rendue telle qu'elle sera une fois partie : publiée, à venir, sans réponse encore. Les rappels déjà
        #  passés au moment de publier ne partent pas (la publication en tient lieu).
        _envoyer, faits = _rappels_dus(e, maintenant)
        e.update(statut="publie", publie=int(maintenant), phase="a_venir" if e["type"] == "evenement" else "",
                 salon_id=salon.id, rappels_faits=sorted(faits))
        if image is not None:
            e["valeurs"]["image_ext"] = image[1]
        try:
            cartes_, contexte = await cartes(g, e, maintenant=maintenant, rep={"d": [], "p": [], "n": [], "v": []},
                                             salon=salon, eq=eq)
        except Exception:   # rien n'est parti : le brouillon redevient publiable
            await _ecrire("UPDATE clan_evenements SET statut='brouillon', version=version+1 WHERE id=?", (int(eid),))
            raise
        ids, echec = await _envoyer_cartes(g, salon, e, cartes_, contexte, image)
        if not ids:
            if echec == "incertain":
                await _ecrire("UPDATE clan_evenements SET statut='incertain', note=?, version=version+1 WHERE id=?",
                              ("Discord n'a pas confirmé l'envoi et le post ne se relit pas : regarde le post avant "
                               "de republier.", int(eid)))
                return 502, {"erreur": "Discord n'a pas confirmé la publication et je n'ai pas pu relire le post : "
                                       "regarde-le avant de republier.", "incertain": True}
            await _ecrire("UPDATE clan_evenements SET statut='brouillon', note=?, version=version+1 WHERE id=?",
                          ("Discord a refusé la publication : rien n'est parti.", int(eid)))
            return 502, {"erreur": "Discord a refusé la publication : rien n'est parti, réessaie dans un instant."}
        avertissements = [a for a in contexte["avertissements"] if a]
        if len(ids) < len(cartes_):
            avertissements.append(f"Seules {len(ids)} cartes sur {len(cartes_)} sont parties : « Actualiser » "
                                  "(modifier sans rien changer) enverra le reste.")
        lien = _lien(g, salon.id, ids[0])
        natif = 0
        if e["type"] == "evenement" and e["valeurs"].get("discord_event"):
            natif, a = await _creer_natif(g, e, lien)
            if a:
                avertissements.append(a)
        await _ecrire("UPDATE clan_evenements SET statut='publie', publie=?, publie_par=?, salon_id=?, messages=?,"
                      " phase=?, rappels_faits=?, discord_event_id=?, note=?, donnees=?, version=version+1"
                      " WHERE id=?",
                      (int(maintenant), auteur.id, salon.id, json.dumps(ids), e["phase"], json.dumps(sorted(faits)),
                       int(natif), " ".join(avertissements)[:500], json.dumps(e["valeurs"], ensure_ascii=False),
                       int(eid)))
    _releve["publications"] += 1
    await _noter(g, f"clan.{e['type']}.publie", f"{auteur.mention} a publié « {e['valeurs']['titre']} » "
                 f"({NOMS_TYPES[e['type']].lower()}) dans « {dest['nom']} »", auteur_id=auteur.id, salon_id=salon.id)
    e = await charger(eid)
    return 200, {"ok": True, "lien": lien, "element": await _vers_site(g, e), "avertissements": avertissements}


async def _notice(g, e: dict, titre: str, md: str, icone: str, *, seulement_si_cibles: bool = False) -> int:
    """Un court message dans le post (rappel, nouvel horaire, annulation) : il mentionne les « Disponible »
    (ils l'ont choisi), sauf « mention : aucune ». `seulement_si_cibles` : rien à dire à personne, rien
    d'envoyé (une annulation que personne n'attendait n'encombre pas le post). Rend le nombre de messages."""
    v = e["valeurs"]
    cibles = []
    if v.get("mention") != "aucune" and v.get("reponses"):
        cibles = [u for u in (await _reponses(e["id"])).get("d") or [] if g.get_member(u) is not None]
    if seulement_si_cibles and not cibles:
        return 0
    salon = await _salon(g, e["salon_id"])
    if salon is None or not await _reveiller(salon):
        return 0
    lots = [cibles[k:k + LOT_MENTIONS] for k in range(0, len(cibles), LOT_MENTIONS)] or [[]]
    lien = _lien(g, e["salon_id"], e["messages"][0]) if e["messages"] else ""
    q = int(v.get("quand") or 0)
    lignes = [_l(titre, icone, 3), _l(md)]
    if q:
        lignes.append(_l(f"<t:{q}:F>" + (f" · RELL Seas · {discord.utils.escape_markdown(v['lieu'])}"
                                         if v.get("lieu") else ""), niveau="petit"))
    blocs = [_texte(*lignes)]
    if lien:
        blocs.append({"type": "boutons", "boutons": [{"label": "Voir l'événement · View event", "url": lien}]})
    envoyes = 0
    for k, lot in enumerate(lots):
        haut = " ".join(f"<@{u}>" for u in lot)
        if k == 0:
            vue_ = vue({"haut": haut, "couleur": int(v.get("couleur") or COULEURS["evenement"]), "blocs": blocs},
                       e["id"], marque=False)
        else:
            vue_ = LayoutView(timeout=None)
            vue_.add_item(discord.ui.TextDisplay(haut))
        try:
            await salon.send(view=vue_, allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=[discord.Object(u) for u in lot]))
            envoyes += 1
        except discord.HTTPException as ex:
            _signaler("E4", "message du post non envoyé", ex, f"evenement={e['id']}")
            break
    return envoyes


def _rappels_dus(e: dict, maintenant: float) -> tuple:
    """(le rappel à envoyer maintenant ou None, les rappels désormais faits). Un bot arrêté pendant plusieurs
    rappels n'envoie que le plus proche du début ; un rappel d'avant le début ne part plus une fois
    l'événement commencé ; « au début » (0) ne part plus dix minutes après."""
    v = e["valeurs"]
    q = int(v.get("quand") or 0)
    faits = set(e["rappels_faits"])
    if not q:
        return None, faits
    dus = []
    for m in v.get("rappels") or []:
        if m in faits or maintenant < q - m * 60:
            continue
        faits.add(m)
        if (m > 0 and maintenant >= q) or (m == 0 and maintenant > q + RETARD_RAPPEL_ZERO_S):
            continue
        dus.append(m)
    return (min(dus) if dus else None), faits


async def traiter(g, eid: int) -> None:
    """Un événement publié : ses rappels (notés en base AVANT l'envoi) et son état (la carte suit)."""
    rappel, nouvelle = None, ""
    async with _verrou(eid):
        e = await charger(eid)
        if e is None or e["type"] != "evenement" or e["statut"] != "publie" or e["phase"] == "termine":
            return
        maintenant = _mur()
        rappel, faits = _rappels_dus(e, maintenant)
        if faits != set(e["rappels_faits"]):
            await _ecrire("UPDATE clan_evenements SET rappels_faits=? WHERE id=?", (json.dumps(sorted(faits)), int(eid)))
        phase = phase_de(e, maintenant)
        if phase != (e["phase"] or "a_venir"):
            nouvelle = phase
            await _ecrire("UPDATE clan_evenements SET phase=?, archive_le=? WHERE id=?",
                          (phase, int(maintenant) if phase == "termine" else 0, int(eid)))
    if nouvelle:
        await maj_carte(g, eid)
        if e["discord_event_id"]:
            await _suivre_natif(g, e, nouvelle)
    if rappel is not None:
        titre = discord.utils.escape_markdown(e["valeurs"]["titre"])
        q = int(e["valeurs"]["quand"])
        if rappel > 0:
            n = await _notice(g, e, "Rappel · Reminder", f"**{titre}** — <t:{q}:R>", "cloche")
        else:
            n = await _notice(g, e, "C'est l'heure · It's time", f"**{titre}** commence · starts", "cloche")
        _releve["rappels"] += 1 if n else 0


async def modifier(g, auteur, corps: dict) -> tuple:
    """Une publication déjà sur Discord, modifiée (ou réécrite telle quelle : « Actualiser »)."""
    eid = _id(corps.get("id"))
    if eid is None:
        return 400, {"erreur": "Identifiant manquant.", "champs": {"id": "Identifiant manquant."}}
    version = _entier(corps.get("version"))
    async with _verrou(eid):
        e = await charger(eid)
        if e is None or e["guild_id"] != g.id:
            return 404, {"erreur": "Publication introuvable."}
        if e["statut"] != "publie" or (e["type"] == "evenement" and "termine" in (e["phase"], phase_de(e, _mur()))):
            return 409, {"erreur": "Seule une publication en ligne (événement pas encore terminé) se modifie.",
                         "actuelle": await _vers_site(g, e)}
        if version is None:
            return 400, {"erreur": "La version est demandée.", "champs": {"version": "La version est demandée."}}
        if version != e["version"]:
            return 409, {"conflit": True, "actuelle": await _vers_site(g, e)}
        if "type" in corps and corps["type"] != e["type"]:
            return 400, {"erreur": "Le type d'une publication ne change pas.", "champs": {"type": "Immuable."}}
        if "destination" in corps and str(corps["destination"] or "") not in ("", str(e["salon_id"])):
            return 400, {"erreur": "Une publication ne change pas de post : annule-la et republie.",
                         "champs": {"destination": "Immuable."}}
        corps = {k: x for k, x in corps.items() if k != "destination"}
        propres, erreurs = await _valider(g, corps, e["type"], e["valeurs"])
        avant = dict(e["valeurs"])
        valeurs = {**avant, **propres}
        erreurs.update(_croiser(e["type"], valeurs))
        maintenant = _mur()
        q_change = e["type"] == "evenement" and valeurs.get("quand") != avant.get("quand")
        if q_change and (not valeurs.get("quand") or valeurs["quand"] < maintenant + AVANCE_S):
            erreurs["quand"] = "Le nouveau début doit être dans le futur (une minute au moins)."
        if erreurs:
            return 400, {"erreur": next(iter(erreurs.values())), "champs": erreurs}
        salon = await _salon(g, e["salon_id"])
        if salon is None or not e["messages"]:
            return 409, {"erreur": "Le post ou le message de cette publication n'existe plus : republie-la."}
        if not await _reveiller(salon):
            return 400, {"erreur": "Ce post est archivé et je ne peux pas le rouvrir."}
        e["valeurs"] = valeurs
        avertissements = []
        if e["type"] == "evenement":
            #  Un nouvel horaire : les rappels repartent de zéro, l'état aussi. Un rappel ajouté dont l'heure est
            #  déjà passée ne part pas (comme à la publication) : jamais un « rappel » surprise.
            q = int(valeurs.get("quand") or 0)
            faits = set() if q_change else set(e["rappels_faits"])
            faits |= {m for m in valeurs.get("rappels") or [] if q and q - m * 60 <= maintenant}
            e["rappels_faits"] = sorted(faits)
            if q_change:
                e["phase"] = "a_venir"
        image_change = valeurs.get("image") != avant.get("image")
        image = await _image(valeurs.get("image") or "") if image_change and valeurs.get("image") else None
        if image_change and valeurs.get("image") and image is None:
            return 400, {"erreur": "Image introuvable : renvoie-la.", "champs": {"image": "Image introuvable."}}
        if image is not None:
            valeurs["image_ext"] = image[1]
        cartes_, contexte = await cartes(g, e, maintenant=maintenant, salon=salon)
        avertissements += contexte["avertissements"]
        nom = _nom_image(e)
        ids = list(e["messages"])
        try:
            for k, carte in enumerate(cartes_):
                vue_ = vue(carte, eid, image_nom=nom if k == 0 else "", catalogue=contexte["catalogue"])
                if k < len(ids):
                    envoi = {"view": vue_, "allowed_mentions": discord.AllowedMentions.none()}
                    if k == 0 and image_change:
                        envoi["attachments"] = [discord.File(io.BytesIO(image[0]), filename=nom)] if image else []
                    await salon.get_partial_message(ids[k]).edit(**envoi)
                else:
                    ids.append(int((await salon.send(view=vue_, allowed_mentions=discord.AllowedMentions.none())).id))
            for mid in ids[len(cartes_):]:
                try:
                    await salon.get_partial_message(mid).delete()
                except discord.NotFound:
                    pass
            ids = ids[:len(cartes_)]
        except discord.NotFound:
            return 409, {"erreur": "Le message de cette publication a été supprimé sur Discord : republie-la."}
        except discord.HTTPException as ex:
            _signaler("E5", "publication non modifiée", ex, f"evenement={eid}")
            return 502, {"erreur": "Discord a refusé la modification : réessaie dans un instant."}
        natif = e["discord_event_id"]
        lien = _lien(g, salon.id, ids[0])
        if e["type"] == "evenement":
            if valeurs.get("discord_event") and not natif:
                natif, a = await _creer_natif(g, e, lien)
                avertissements += [a] if a else []
            elif natif and not valeurs.get("discord_event"):
                await _suivre_natif(g, e, annuler=True)
                natif = 0
            elif natif:
                a = await _modifier_natif(g, e, lien, debut_change=q_change)
                avertissements += [a] if a else []
        await _ecrire("UPDATE clan_evenements SET donnees=?, messages=?, rappels_faits=?, phase=?, quand=?, fin=?,"
                      " discord_event_id=?, note=?, version=version+1, maj=?, maj_par=? WHERE id=?",
                      (json.dumps(valeurs, ensure_ascii=False), json.dumps(ids), json.dumps(e["rappels_faits"]),
                       e["phase"], int(valeurs.get("quand") or 0), _fin(valeurs), int(natif or 0),
                       " ".join(a for a in avertissements if a)[:500], int(maintenant), auteur.id, int(eid)))
    if q_change:
        titre = discord.utils.escape_markdown(valeurs["titre"])
        await _notice(g, e, "Nouvel horaire · New time", f"**{titre}** — <t:{int(valeurs['quand'])}:R>. Toujours "
                      "disponible ? Mets ta réponse à jour · Still available? Update your answer.", "calendrier",
                      seulement_si_cibles=True)
    await _noter(g, f"clan.{e['type']}.modifie", f"{auteur.mention} a modifié « {valeurs['titre']} » "
                 f"({NOMS_TYPES[e['type']].lower()})", auteur_id=auteur.id, salon_id=salon.id)
    e = await charger(eid)
    return 200, {"ok": True, "lien": lien, "element": await _vers_site(g, e),
                 "avertissements": [a for a in avertissements if a]}


async def annuler(g, auteur, eid: int, *, prevenir: bool = True) -> tuple:
    """Un événement annulé (la carte le dit, l'évènement natif suit, les disponibles sont prévenus) ; une
    annonce, des métiers ou un listing retirés (leurs messages supprimés)."""
    async with _verrou(eid):
        e = await charger(eid)
        if e is None or e["guild_id"] != g.id:
            return 404, {"erreur": "Publication introuvable."}
        if e["statut"] in ("annule", "retire"):
            return 200, {"ok": True, "deja": True, "element": await _vers_site(g, e)}
        if e["statut"] == "brouillon":
            return 409, {"erreur": "Un brouillon ne s'annule pas : supprime-le."}
        if e["statut"] == "envoi":
            return 409, {"erreur": "La publication est en cours : attends quelques secondes."}
        if e["type"] == "evenement" and e["statut"] == "publie" and "termine" in (e["phase"], phase_de(e, _mur())):
            return 409, {"erreur": "Cet événement est déjà terminé."}
        maintenant = int(_mur())
        salon = await _salon(g, e["salon_id"])
        if e["type"] == "evenement" and e["statut"] == "publie":
            await _ecrire("UPDATE clan_evenements SET statut='annule', archive_le=?, version=version+1, maj=?,"
                          " maj_par=? WHERE id=?", (maintenant, maintenant, auteur.id, int(eid)))
            statut = "annule"
        else:
            ids = list(e["messages"])
            if salon is not None and e["statut"] == "incertain":
                trouves = await _retrouver(g, salon, eid)
                ids = trouves if isinstance(trouves, list) else ids
            for mid in ids:
                if salon is None:
                    break
                try:
                    await salon.get_partial_message(mid).delete()
                except discord.NotFound:
                    pass
                except discord.HTTPException as ex:
                    _signaler("E8", "message de la publication non supprimé", ex, f"evenement={eid}")
                    return 502, {"erreur": "Discord a refusé la suppression : réessaie dans un instant."}
            await _ecrire("UPDATE clan_evenements SET statut='retire', archive_le=?, version=version+1, maj=?,"
                          " maj_par=? WHERE id=?", (maintenant, maintenant, auteur.id, int(eid)))
            statut = "retire"
    if statut == "annule":
        await maj_carte(g, eid)
        if e["discord_event_id"]:
            await _suivre_natif(g, e, annuler=True)
        if prevenir:
            titre = discord.utils.escape_markdown(e["valeurs"]["titre"])
            await _notice(g, e, "Annulé · Cancelled", f"**{titre}** n'aura pas lieu · will not take place.", "annuler",
                          seulement_si_cibles=True)
    await _noter(g, f"clan.{e['type']}.{statut}", f"{auteur.mention} a {'annulé' if statut == 'annule' else 'retiré'}"
                 f" « {e['valeurs']['titre']} » ({NOMS_TYPES[e['type']].lower()})", auteur_id=auteur.id)
    return 200, {"ok": True, "element": await _vers_site(g, await charger(eid))}


# ═══════════════════════════════════════════════════════════════════════════════
#  La boucle (bot.py : `evenements_task`, une minute, supervisée)
# ═══════════════════════════════════════════════════════════════════════════════

async def tic(guilds) -> None:
    if not pret():
        return
    _releve["boucles"] += 1
    _releve["derniere_boucle"] = int(_mur())
    a_venir = 0
    for g in guilds:
        try:
            a_venir += await _tic_serveur(g)
        except Exception as ex:
            _signaler("E20", "passage de la boucle en échec", ex, f"serveur={getattr(g, 'id', 0)}")
    _releve["a_venir"] = a_venir
    if _mur() - _purge[0] > 86400:
        _purge[0] = _mur()
        try:
            n = await purger(GARDE_SECOURS_JOURS)
            if n:
                _log("[EVENEMENTS] filet de nettoyage passé")
                _log(f"[EVENEMENTS:DETAIL] lignes={n}")
        except Exception as ex:
            _signaler("E21", "nettoyage de secours en échec", ex)


async def _tic_serveur(g) -> int:
    maintenant = _mur()
    async with _get_db() as db:
        async with db.execute(_SELECT + " WHERE guild_id=? AND ((type='evenement' AND statut='publie' AND"
                              " phase!='termine') OR (statut='envoi' AND envoi_le<?))",
                              (g.id, int(maintenant) - ENVOI_BLOQUE_S)) as cur:
            lignes = [_ligne(r) for r in await cur.fetchall()]
    n = 0
    for e in lignes:
        if e["statut"] == "envoi":
            await _reprendre_envoi(g, e["id"])
            continue
        n += 1
        await traiter(g, e["id"])
        prochain = _prochaine_echeance(e, maintenant)
        if MINUTEUR_S and prochain and 0 < prochain - maintenant <= MINUTEUR_S and e["id"] not in _minuteurs:
            _minuteurs[e["id"]] = asyncio.create_task(_minuteur(g, e["id"], prochain))
    return n


def _prochaine_echeance(e: dict, maintenant: float):
    v = e["valeurs"]
    q = int(v.get("quand") or 0)
    if not q:
        return None
    dates = [q - m * 60 for m in v.get("rappels") or [] if m not in e["rappels_faits"] and q - m * 60 > maintenant]
    dates += [t for t in (q, _fin(v)) if t > maintenant]
    return min(dates) if dates else None


async def _minuteur(g, eid: int, quand: float) -> None:
    """« De vrais timers » : à la seconde près, pas au passage suivant de la boucle."""
    try:
        await asyncio.sleep(max(0.0, quand - _mur()) + 0.5)
        await traiter(g, eid)
    except asyncio.CancelledError:
        raise
    except Exception as ex:
        _signaler("E22", "minuteur en échec", ex, f"evenement={eid}")
    finally:
        _minuteurs.pop(eid, None)


async def _reprendre_envoi(g, eid: int) -> None:
    """Une publication restée « en cours » (le bot a redémarré pendant l'envoi) : partie (on la garde), pas
    partie (retour au brouillon), ou le post ne se relit pas (« incertaine », le site le dit)."""
    if _verrou(eid).locked():
        return
    async with _verrou(eid):
        e = await charger(eid)
        if e is None or e["statut"] != "envoi":
            return
        dest = _destination(destinations(g, await _cfg(g.id)), e["valeurs"])
        salon = await _salon(g, int(dest["id"])) if dest else None
        trouves = await _retrouver(g, salon, eid) if salon is not None else []
        if trouves is _ILLISIBLE:
            await _ecrire("UPDATE clan_evenements SET statut='incertain', note=?, version=version+1 WHERE id=?",
                          ("La publication a été interrompue et le post ne se relit pas : regarde-le.", int(eid)))
            return
        if not trouves:
            await _ecrire("UPDATE clan_evenements SET statut='brouillon', note=?, version=version+1 WHERE id=?",
                          ("La publication a été interrompue (redémarrage) : rien n'est parti.", int(eid)))
            return
        maintenant = _mur()
        _r, faits = _rappels_dus(e, maintenant)
        image = await _image(e["valeurs"].get("image") or "")
        if image is not None:   # la pièce jointe déjà partie porte cette extension : les réécritures la gardent
            e["valeurs"]["image_ext"] = image[1]
        note = "Publication reprise après un redémarrage." + (
            " L'évènement Discord n'a pas été créé : « Modifier » le crée." if e["valeurs"].get("discord_event")
            and e["type"] == "evenement" else "")
        if e["type"] == "evenement":   # sans évènement natif : « Modifier » (case cochée) le créera
            e["valeurs"]["discord_event"] = False
        await _ecrire("UPDATE clan_evenements SET statut='publie', publie=?, publie_par=maj_par, salon_id=?,"
                      " messages=?, phase=?, rappels_faits=?, note=?, donnees=?, version=version+1 WHERE id=?",
                      (int(e["envoi_le"] or maintenant), salon.id, json.dumps(trouves),
                       "a_venir" if e["type"] == "evenement" else "", json.dumps(sorted(faits)), note,
                       json.dumps(e["valeurs"], ensure_ascii=False), int(eid)))
    _log("[EVENEMENTS] publication interrompue retrouvée")
    await maj_carte(g, eid)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le site : les routes (`tableau.monter(ROUTES_SITE)`)
# ═══════════════════════════════════════════════════════════════════════════════

def _id(x):
    s = str(x if x is not None else "").strip()
    return int(s) if s.isdigit() and len(s) <= 12 and int(s) > 0 else None


def _qui(g, uid) -> dict | None:
    if not uid:
        return None
    m = g.get_member(int(uid))
    return {"id": str(uid), "nom": m.display_name if m is not None else "Membre parti"}


def _valeurs_site(v: dict) -> dict:
    out = {k: x for k, x in v.items() if k != "image_ext"}
    out["couleur"] = f"#{int(v.get('couleur') or 0):06x}"
    return out


async def _vers_site(g, e: dict, comptes: dict | None = None, dests: list | None = None) -> dict:
    """Une publication telle que le site la lit (identifiants Discord en texte : 64 bits)."""
    if e is None:
        return {}
    dests = dests if dests is not None else destinations(g, await _cfg(g.id))
    dest = (next((d for d in dests if d["id"] == str(e["salon_id"])), None) if e["salon_id"]
            else _destination(dests, e["valeurs"]))
    comptes = comptes if comptes is not None else (await _comptes([e["id"]])).get(e["id"], {})
    salon_id = e["salon_id"] or (int(dest["id"]) if dest else 0)
    return {
        "id": e["id"], "type": e["type"], "statut": e["statut"],
        #  L'heure fait foi (la carte suit à la minute près) : à venir, en cours, terminé.
        "phase": phase_de(e, _mur()) if e["type"] == "evenement" else "",
        "version": e["version"], "cle_client": e["cle_client"] or "",
        "titre": e["valeurs"]["titre"], "quand": e["valeurs"].get("quand") or None,
        "fin": _fin(e["valeurs"]) if e["type"] == "evenement" and e["valeurs"].get("quand") else None,
        "valeurs": _valeurs_site(e["valeurs"]),
        "destination": ({"id": dest["id"], "nom": dest["nom"]} if dest else None),
        "cree": e["cree"], "cree_par": _qui(g, e["cree_par"]), "maj": e["maj"], "maj_par": _qui(g, e["maj_par"]),
        "publie": e["publie"] or None, "publie_par": _qui(g, e["publie_par"]),
        "lien": _lien(g, salon_id, e["messages"][0]) if e["messages"] else "",
        "cartes": len(e["messages"]),
        "reponses": {"disponibles": comptes.get("d", 0), "peut_etre": comptes.get("p", 0),
                     "pas_disponibles": comptes.get("n", 0), "vus": comptes.get("v", 0)},
        "discord_event": ({"id": str(e["discord_event_id"]),
                           "lien": f"https://discord.com/events/{g.id}/{e['discord_event_id']}"}
                          if e["discord_event_id"] else None),
        "rappels_faits": e["rappels_faits"], "note": e["note"],
    }


def _refus(g, auteur):
    if not pret():
        return 503, {"erreur": "Le module des événements démarre : réessaie dans un instant."}
    if g is None or auteur is None or (_est_tete is not None and not _est_tete(g, auteur)):
        return 403, {"erreur": "Réservé au fondateur et à la direction."}
    return None


MODELES = [
    {"cle": "dispo", "nom": "Êtes-vous disponibles ?", "type": "evenement",
     "description": "Une heure, trois boutons : on s'organise selon les disponibles.",
     "valeurs": {"titre": "Qui est disponible ?", "texte": "Réponds avec les boutons : on s'organise selon les "
                                                         "disponibles.\n-# Answer with the buttons: we plan around "
                                                         "who's available.",
                 "duree_min": 60, "rappels": [60, 0], "mention": "inscrits", "reponses": True, "places": 0,
                 "discord_event": False, "reserve_clan": True}},
    {"cle": "sortie", "nom": "Sortie en mer", "type": "evenement",
     "description": "Raid, chasse ou boss : lieu, durée, rappels la veille et une heure avant.",
     "valeurs": {"titre": "Sortie en mer", "texte": "", "duree_min": 120, "rappels": [1440, 60, 10],
                 "mention": "inscrits", "reponses": True, "places": 0, "discord_event": True,
                 "reserve_clan": True}},
    {"cle": "reunion", "nom": "Réunion du clan", "type": "evenement",
     "description": "Tout le clan mentionné à la publication, rappels la veille et 30 min avant.",
     "valeurs": {"titre": "Réunion du clan", "texte": "", "duree_min": 45, "rappels": [1440, 30],
                 "mention": "clan", "reponses": True, "places": 0, "discord_event": True, "reserve_clan": True}},
    {"cle": "entrainement", "nom": "Entraînement", "type": "evenement",
     "description": "Places limitées : les premiers disponibles sont retenus.",
     "valeurs": {"titre": "Entraînement", "texte": "", "duree_min": 90, "rappels": [60, 10],
                 "mention": "inscrits", "reponses": True, "places": 10, "discord_event": False,
                 "reserve_clan": True}},
    {"cle": "annonce", "nom": "Annonce officielle", "type": "annonce",
     "description": "Titre, texte, image : « Vu » pour savoir qui l'a lue.",
     "valeurs": {"titre": "", "texte": "", "mention": "clan"}},
    {"cle": "metiers", "nom": "Annonce officielle des métiers", "type": "metiers",
     "description": "Chaque métier et qui l'exerce, d'après les affiches.",
     "valeurs": {"titre": "Les métiers de l'équipage", "groupement": "metier", "champs": ["grade"]}},
    {"cle": "listing", "nom": "Listing complet du clan", "type": "listing",
     "description": "Tout le clan, par grade (ou par métier, ou par race).",
     "valeurs": {"titre": "Le clan au complet", "groupement": "grade", "champs": ["metiers", "race"]}},
]
RAPPELS_SUGGERES = [[10080, "1 semaine avant"], [1440, "1 jour avant"], [180, "3 h avant"], [60, "1 h avant"],
                    [30, "30 min avant"], [15, "15 min avant"], [10, "10 min avant"], [0, "Au début"]]
COULEURS_SUGGEREES = [["Laiton", "#a8823f"], ["Clan", f"#{COULEURS['annonce']:06x}"], ["Cire", "#8e2a24"],
                      ["Mer", "#1f4e5a"], ["Vert", "#3f6b3a"], ["Ambre", "#a8641c"], ["Encre", "#2b1d12"]]


async def route_evenements(g, auteur, requete, corps):
    """GET clan/evenements : tout ce qu'il faut à l'onglet (destinations, brouillons, à venir, passés,
    modèles, lieux du jeu, limites, droits du bot)."""
    refus = _refus(g, auteur)
    if refus:
        return refus
    c = await _cfg(g.id)
    dests = destinations(g, c)
    lignes = await _tous(g.id)
    comptes = await _comptes([e["id"] for e in lignes])
    brouillons, a_venir, passes = [], [], []
    maintenant = _mur()
    for e in lignes:
        item = await _vers_site(g, e, comptes.get(e["id"], {}), dests)
        if e["statut"] == "brouillon":
            brouillons.append(item)
        elif e["statut"] in ("envoi", "incertain") or (e["type"] == "evenement" and e["statut"] == "publie"
                                                        and phase_de(e, maintenant) != "termine"):
            a_venir.append(item)
        else:
            passes.append(item)
    a_venir.sort(key=lambda x: (x["quand"] or 0, x["id"]))
    brouillons.sort(key=lambda x: -(x["maj"] or 0))
    passes.sort(key=lambda x: -max(x["quand"] or 0, x["publie"] or 0))
    lieux = []
    if _catalogue is not None:
        try:
            cat = await _appeler(_catalogue, g) or {}
            for type_ in ("ile", "zone", "lieu"):
                lieux += [{"type": type_, "cle": k, "nom": sans_emoji(_nom_cat(_cat(cat, type_), k, md=False))}
                          for k in _cat(cat, type_)]
        except Exception as ex:
            _signaler("E11", "catalogue du jeu illisible", ex)
    role = _role_clan(g, c) if _role_clan else None
    return 200, {
        "destinations": [{"id": d["id"], "nom": d["nom"], "defaut": d["defaut"]} for d in dests],
        "brouillons": brouillons, "a_venir": a_venir, "passes": passes[:PASSES_MAX], "passes_total": len(passes),
        "modeles": MODELES, "lieux": lieux, "rappels_suggeres": RAPPELS_SUGGERES, "couleurs": COULEURS_SUGGEREES,
        "defauts": {t: _valeurs_site(_defauts(t)) for t in TYPES},
        "limites": {"titre": TITRE_MAX, "texte": TEXTE_MAX, "lieu": LIEU_MAX, "duree_min": DUREE_MAX,
                    "rappel_min": RAPPEL_MAX, "rappels": RAPPELS_MAX, "places": PLACES_MAX,
                    "composants": COMPOSANTS_MAX, "caracteres": CARACTERES_MAX},
        "droits": {"discord_event": peut_evenements(g), "role_clan": role is not None,
                   "role_clan_nom": getattr(role, "name", "") or "", "fiches": _fiches is not None},
        "maintenant": int(maintenant),
    }


async def route_brouillon(g, auteur, requete, corps):
    """POST clan/brouillon (hors ligne) : crée ou modifie un brouillon. Ne touche jamais Discord."""
    refus = _refus(g, auteur)
    if refus:
        return refus
    if not isinstance(corps, dict):
        return 400, {"erreur": "Corps JSON attendu."}
    cle = corps.get("cle_client")
    if cle is not None and (not isinstance(cle, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", cle)):
        return 400, {"erreur": "cle_client invalide.", "champs": {"cle_client": "8 à 64 caractères A-Z, 0-9, - ou _."}}
    e = None
    if corps.get("id") is not None:
        eid = _id(corps["id"])
        if eid is None:
            return 400, {"erreur": "Identifiant invalide.", "champs": {"id": "Identifiant invalide."}}
        e = await charger(eid)
        if e is None or e["guild_id"] != g.id:
            return 404, {"erreur": "Brouillon introuvable."}
        if _entier(corps.get("version")) is None:
            return 400, {"erreur": "La version est demandée.", "champs": {"version": "La version est demandée."}}
    elif cle:
        e = await _par_cle(g.id, cle)
    if e is not None and e["statut"] != "brouillon":
        return 409, {"erreur": "Déjà publiée : modifie-la en ligne (clan/modifier).", "publie": True,
                     "actuelle": await _vers_site(g, e)}
    if e is not None and corps.get("version") is not None and _entier(corps["version"]) != e["version"]:
        return 409, {"conflit": True, "actuelle": await _vers_site(g, e)}
    type_ = corps.get("type", e["type"] if e else None)
    if type_ not in TYPES:
        return 400, {"erreur": "Type inconnu.", "champs": {"type": "evenement, annonce, metiers ou listing."}}
    avant = e["valeurs"] if e else {}
    propres, erreurs = await _valider(g, corps, type_, avant)
    base = _defauts(type_)
    if e is not None:   # un brouillon qui change de type garde ce qui est commun (titre, texte, image…)
        base.update(e["valeurs"] if type_ == e["type"] else
                    _normaliser(type_, {k: x for k, x in e["valeurs"].items() if k in CHAMPS_TYPE[type_]}))
    valeurs = {**base, **propres}
    erreurs.update(_croiser(type_, valeurs))
    if erreurs:
        return 400, {"erreur": next(iter(erreurs.values())), "champs": erreurs}
    maintenant = int(_mur())
    donnees = json.dumps(valeurs, ensure_ascii=False)
    q, fin = int(valeurs.get("quand") or 0), _fin(valeurs)
    if e is None:
        try:
            eid, _n = await _ecrire("INSERT INTO clan_evenements(guild_id, type, donnees, cle_client, cree, cree_par,"
                                    " maj, maj_par, quand, fin) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                    (g.id, type_, donnees, cle, maintenant, auteur.id, maintenant, auteur.id, q, fin))
        except sqlite3.IntegrityError:   # la même création, rejouée en même temps : la première gagne
            e = await _par_cle(g.id, cle)
            return 200, {"ok": True, "element": await _vers_site(g, e), "deja": True}
        await _noter(g, f"clan.{type_}.brouillon", f"{auteur.mention} a commencé un brouillon "
                     f"({NOMS_TYPES[type_].lower()}) : « {valeurs['titre'] or 'sans titre'} »", auteur_id=auteur.id)
        return 200, {"ok": True, "element": await _vers_site(g, await charger(eid))}
    _id_, n = await _ecrire("UPDATE clan_evenements SET type=?, donnees=?, quand=?, fin=?, version=version+1, maj=?,"
                            " maj_par=?, note='' WHERE id=? AND version=? AND statut='brouillon'",
                            (type_, donnees, q, fin, maintenant, auteur.id, e["id"], e["version"]))
    if not n:
        e2 = await charger(e["id"])
        return 409, ({"conflit": True, "actuelle": await _vers_site(g, e2)} if e2 is not None
                     else {"erreur": "Brouillon supprimé entre-temps."})
    return 200, {"ok": True, "element": await _vers_site(g, await charger(e["id"]))}


async def route_supprimer_brouillon(g, auteur, requete, corps):
    """POST clan/supprimer_brouillon (hors ligne) : idempotent — déjà parti, c'est « fait »."""
    refus = _refus(g, auteur)
    if refus:
        return refus
    if not isinstance(corps, dict):
        return 400, {"erreur": "Corps JSON attendu."}
    if corps.get("id") is not None:
        eid = _id(corps["id"])
        if eid is None:
            return 400, {"erreur": "Identifiant invalide."}
        e = await charger(eid)
    elif isinstance(corps.get("cle_client"), str):
        e = await _par_cle(g.id, corps["cle_client"])
    else:
        return 400, {"erreur": "Identifiant manquant."}
    if e is None:
        return 200, {"ok": True, "deja": True}
    if e["guild_id"] != g.id:
        return 404, {"erreur": "Brouillon introuvable."}
    if e["statut"] != "brouillon":
        return 409, {"erreur": "Seul un brouillon se supprime : annule la publication.",
                     "actuelle": await _vers_site(g, e)}
    version = _entier(corps.get("version"))
    if version is not None and version != e["version"]:
        return 409, {"conflit": True, "actuelle": await _vers_site(g, e)}
    _x, n = await _ecrire("DELETE FROM clan_evenements WHERE id=? AND statut='brouillon' AND version=?",
                          (e["id"], e["version"]))
    if not n:
        e2 = await charger(e["id"])
        return (200, {"ok": True, "deja": True}) if e2 is None else (409, {"conflit": True,
                                                                           "actuelle": await _vers_site(g, e2)})
    await _ecrire("DELETE FROM clan_evenements_reponses WHERE evenement_id=?", (e["id"],))
    await _noter(g, f"clan.{e['type']}.brouillon_supprime", f"{auteur.mention} a supprimé le brouillon "
                 f"« {e['valeurs']['titre'] or 'sans titre'} »", auteur_id=auteur.id)
    return 200, {"ok": True}


def _carte_site(carte: dict) -> dict:
    blocs = []
    for b in carte["blocs"]:
        t = b["type"]
        if t == "image":
            blocs.append({"type": "image", "media": b["media"], "url": f"media/{b['media']}"})
        elif t == "bandeau":
            fichier = visuels.fichier(f"{b['cle']}.gif")
            blocs.append({"type": "bandeau", "cle": b["cle"], "titre": b["titre"],
                          "url": f"/v/{b['cle']}.gif?v={visuels.VERSION}" if fichier else ""})
        elif t == "texte":
            blocs.append({"type": "texte", "lignes": [
                {"md": x["md"], "icone": x.get("icone") or "", "niveau": x.get("niveau", 0),
                 "jeu": ({"type": x["jeu"][0], "cle": x["jeu"][1]} if x.get("jeu") else None)}
                for x in b["lignes"]]})
        elif t == "boutons":
            blocs.append({"type": "boutons", "boutons": [
                {"label": x["label"], "style": "lien" if x.get("url") else x.get("style", "secondaire"),
                 "icone": x.get("icone") or "", "desactive": bool(x.get("desactive")), "url": x.get("url") or ""}
                for x in b["boutons"]]})
        else:
            blocs.append({"type": "separateur"})
    n, c = mesurer(carte)
    return {"haut": carte.get("haut") or "", "couleur": f"#{int(carte['couleur']):06x}", "blocs": blocs,
            "composants": n, "caracteres": c}


async def route_apercu(g, auteur, requete, corps):
    """GET clan/apercu?id= : les cartes telles que Discord les affichera, et ce qui bloque ou prévient."""
    refus = _refus(g, auteur)
    if refus:
        return refus
    eid = _id((requete or {}).get("id"))
    if eid is None:
        return 400, {"erreur": "Identifiant invalide.", "champs": {"id": "Identifiant invalide."}}
    e = await charger(eid)
    if e is None or e["guild_id"] != g.id:
        return 404, {"erreur": "Publication introuvable."}
    c = await _cfg(g.id)
    maintenant = _mur()
    rep = await _reponses(eid)
    cartes_, contexte = await cartes(g, e, maintenant=maintenant, rep=rep)
    dests = destinations(g, c)
    erreurs = _controle(e, maintenant, dests, contexte.get("equipage")) if e["statut"] == "brouillon" else []
    if e["statut"] == "brouillon" and e["valeurs"].get("image") and await _image(e["valeurs"]["image"]) is None:
        erreurs.append("L'image n'est plus sur le site : renvoie-la.")
    avertissements = list(contexte["avertissements"])
    v = e["valeurs"]
    rappels = []
    if e["type"] == "evenement":
        q = int(v.get("quand") or 0)
        for m in v.get("rappels") or []:
            rappels.append({"minutes": m, "quand": q - m * 60 if q else None, "fait": m in e["rappels_faits"],
                            "passe": bool(q) and q - m * 60 <= maintenant})
        if e["statut"] == "brouillon" and q:
            passes = [r["minutes"] for r in rappels if r["passe"]]
            if passes:
                avertissements.append("Rappel(s) déjà passé(s), qui ne partiront pas : "
                                      + ", ".join("au début" if m == 0 else f"{_duree_txt(m)} avant" for m in passes)
                                      + ".")
        if v.get("rappels") and v.get("mention") != "aucune" and not v.get("reponses"):
            avertissements.append("Sans boutons de réponse, les rappels ne mentionnent personne.")
        if v.get("discord_event") and not peut_evenements(g):
            avertissements.append(SANS_PERMISSION)
        if v.get("discord_event") and not v.get("duree_min"):
            avertissements.append("Durée non précisée : l'évènement Discord affichera une fin deux heures après le "
                                  "début.")
    trop = [k + 1 for k, x in enumerate(cartes_) if mesurer(x)[0] > COMPOSANTS_MAX or mesurer(x)[1] > CARACTERES_MAX]
    if trop:
        erreurs.append("Une carte dépasse les limites de Discord : raccourcis le texte.")
    personnes, roles = {}, {}
    for x in cartes_:
        for b in x["blocs"]:
            for ln in b.get("lignes") or []:
                for uid in re.findall(r"<@!?(\d+)>", ln["md"]):
                    m = g.get_member(int(uid))
                    personnes[uid] = m.display_name if m is not None else "Membre parti"
        for rid in re.findall(r"<@&(\d+)>", x.get("haut") or ""):
            r = g.get_role(int(rid))
            roles[rid] = getattr(r, "name", "") or "rôle supprimé"
    for uid in re.findall(r"<@!?(\d+)>", " ".join(x.get("haut") or "" for x in cartes_)):
        m = g.get_member(int(uid))
        personnes[uid] = m.display_name if m is not None else "Membre parti"
    dest = _destination(dests, v)
    return 200, {
        "id": e["id"], "type": e["type"], "statut": e["statut"], "version": e["version"],
        "phase": phase_de(e, maintenant) if e["type"] == "evenement" else "",
        "destination": ({"id": dest["id"], "nom": dest["nom"]} if dest else None),
        "cartes": [_carte_site(x) for x in cartes_],
        "limites": {"composants": COMPOSANTS_MAX, "caracteres": CARACTERES_MAX},
        "personnes": personnes, "roles": roles,
        "publiable": e["statut"] == "brouillon" and not erreurs, "erreurs": erreurs,
        "avertissements": [a for a in avertissements if a],
        "rappels": rappels,
        "discord_event": {"demande": bool(v.get("discord_event")), "permission": peut_evenements(g),
                          "id": str(e["discord_event_id"] or ""),
                          "lien": (f"https://discord.com/events/{g.id}/{e['discord_event_id']}"
                                   if e["discord_event_id"] else "")},
        "maintenant": int(maintenant),
    }


async def route_publier(g, auteur, requete, corps):
    """POST clan/publier {"id", "version"?, "forcer"?} — en ligne seulement, jamais rejoué hors ligne."""
    refus = _refus(g, auteur)
    if refus:
        return refus
    if not isinstance(corps, dict):
        return 400, {"erreur": "Corps JSON attendu."}
    eid = _id(corps.get("id"))
    if eid is None and isinstance(corps.get("cle_client"), str):
        e = await _par_cle(g.id, corps["cle_client"])
        eid = e["id"] if e else None
    if eid is None:
        return 400, {"erreur": "Identifiant manquant.", "champs": {"id": "Identifiant manquant."}}
    version = corps.get("version")
    if version is not None and _entier(version) is None:
        return 400, {"erreur": "Version invalide.", "champs": {"version": "Un entier est attendu."}}
    return await publier(g, auteur, eid, version=_entier(version) if version is not None else None,
                         forcer=corps.get("forcer") is True)


async def route_modifier(g, auteur, requete, corps):
    """POST clan/modifier {"id", "version", …champs} — une publication en ligne (événement à venir ou en
    cours, annonce, métiers, listing) ; sans champ : « Actualiser » (réécrite d'après les données du jour)."""
    refus = _refus(g, auteur)
    if refus:
        return refus
    if not isinstance(corps, dict):
        return 400, {"erreur": "Corps JSON attendu."}
    inconnus = [k for k in corps if k not in CHAMPS and k not in CLES_CONTROLE]
    if inconnus:
        return 400, {"erreur": f"Champ inconnu : {inconnus[0]}.", "champs": {k: "Champ inconnu." for k in inconnus}}
    return await modifier(g, auteur, corps)


async def route_annuler(g, auteur, requete, corps):
    """POST clan/annuler {"id", "prevenir"?} — un événement annulé, une annonce retirée."""
    refus = _refus(g, auteur)
    if refus:
        return refus
    if not isinstance(corps, dict):
        return 400, {"erreur": "Corps JSON attendu."}
    eid = _id(corps.get("id"))
    if eid is None:
        return 400, {"erreur": "Identifiant manquant.", "champs": {"id": "Identifiant manquant."}}
    prevenir = corps.get("prevenir", True)
    if not isinstance(prevenir, bool):
        return 400, {"erreur": "« prevenir » : vrai ou faux.", "champs": {"prevenir": "Vrai ou faux est attendu."}}
    return await annuler(g, auteur, eid, prevenir=prevenir)


#  Le contrat avec le registre d'API du site (`tableau.monter`) : `fn(g, auteur, requete, corps) → (status,
#  corps)`. Hors ligne : seulement ce qui ne touche pas Discord (les brouillons).
ROUTES_SITE = {
    "clan/evenements": {"methode": "GET", "fn": route_evenements, "ecriture": False, "hors_ligne": False,
                        "corps_max": 0, "grave": None},
    "clan/apercu": {"methode": "GET", "fn": route_apercu, "ecriture": False, "hors_ligne": False,
                    "corps_max": 0, "grave": None},
    "clan/brouillon": {"methode": "POST", "fn": route_brouillon, "ecriture": True, "hors_ligne": True,
                       "corps_max": TAILLE_CORPS, "grave": None},
    "clan/supprimer_brouillon": {"methode": "POST", "fn": route_supprimer_brouillon, "ecriture": True,
                                 "hors_ligne": True, "corps_max": 1024, "grave": None},
    "clan/publier": {"methode": "POST", "fn": route_publier, "ecriture": True, "hors_ligne": False,
                     "corps_max": 1024, "grave": None},
    "clan/modifier": {"methode": "POST", "fn": route_modifier, "ecriture": True, "hors_ligne": False,
                      "corps_max": TAILLE_CORPS, "grave": None},
    "clan/annuler": {"methode": "POST", "fn": route_annuler, "ecriture": True, "hors_ligne": False,
                     "corps_max": 1024, "grave": None},
}
