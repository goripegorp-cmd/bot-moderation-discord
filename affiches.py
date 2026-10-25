"""affiches.py — la Capitainerie du site : le catalogue RELL Seas, les affiches, les rôles des métiers (25/10/2026).

Demandé par le fondateur : « créer leurs propres affiches, qui restent, extrêmement professionnelles,
pour repérer tout concernant RELL Seas… catégories selon les métiers (gros changements avec le Movie 3)…
aider la direction avec un système de rôles… des fiches ultra techniques de tout ce que les joueurs
peuvent détenir dans le jeu, et UNIQUEMENT ce qui existe dans le jeu ». Puis (25/10) : le catalogue est
modifiable sur le site, pré-rempli avec le confirmé (« à vérifier » sinon).

LE CATALOGUE (commun à tout le bot : le jeu est le même partout)
  · Des types (race, métier, faction…) et leurs éléments : nom FR · EN, description, catégorie, rareté,
    icône (`s/icones/rell/…` : officielle, ou `media/…` : envoyée sur le site), statut « confirmé » ou
    « à vérifier », source, nouveauté du Movie 3, ordre, actif.
  · Le catalogue de départ (`donnees_jeu/rell_catalogue.json`) est lu au démarrage : ce qui manque est
    ajouté, ce qui n'a pas été touché sur le site suit le fichier, et ce qui a été modifié sur le site
    n'est JAMAIS remplacé.
  · Chaque modification porte une version : deux écrans qui modifient la même chose — le second reçoit
    un conflit (409) avec la version actuelle, rien n'est écrasé en silence.

LES AFFICHES (par serveur)
  · Une par membre : portrait Roblox, surnom, prime, niveau, grade, statut, et ses attributs — UNIQUEMENT
    des éléments du catalogue. Historique de chaque changement (qui, quand, quoi). Retirée : corbeille
    30 jours (règle « Nettoyage »), restaurable.
  · Le portrait Roblox est demandé PAR LE SERVEUR (jamais par la page : l'adresse du lecteur ne part pas
    chez Roblox), refait en WebP et gardé ici.

LES RÔLES DES MÉTIERS
  · Un rôle Discord par élément (un métier surtout) : un rôle existant, ou créé SANS aucune permission.
    Jamais un rôle de gestion ou de modération, jamais au-dessus du bot. « Appliquer » donne les rôles des
    métiers de l'affiche et retire ceux qu'elle n'a plus ; « automatique » le fait à chaque enregistrement.

Toutes les adresses passent par le registre du site (`tableau.monter`) : session, tête, origine,
cadence, journal. Chaque champ est vérifié ici (type, longueur, clé du catalogue) ; une erreur de saisie
répond 400 avec le champ en cause, jamais une exception vers la page.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import discord

import registre
import tableau

DEPART = Path(__file__).resolve().parent / "donnees_jeu" / "rell_catalogue.json"
#  Le bilan du dernier chargement du catalogue de départ (affiché dans /stats, clé « catalogue_depart ») : une entrée
#  écartée au démarrage se voit sans lire le journal (25/10 : 144 éléments écartés pour un chemin d'icône mal formé).
DERNIER_DEPART: dict = {}
STATUTS_ELEMENT = ("confirme", "a_verifier")
FORMAT_CLE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
FORMAT_AFFICHE = re.compile(r"[A-Za-z0-9_-]{1,64}")
FORMAT_ROBLOX = re.compile(r"[A-Za-z0-9_]{3,20}")
FORMAT_ICONE = re.compile(r"s/(?:icones|logos)/[a-z0-9_-]{1,64}(?:/[a-z0-9_-]{1,64}){0,3}\.(?:webp|png|svg)")
FORMAT_ICONE_MEDIA = re.compile(r"media/([A-Za-z0-9_-]{16})")
FORMAT_COULEUR = re.compile(r"#([0-9a-fA-F]{6})")
#  Caractères de contrôle, invisibles et de direction (une phrase qui s'écrit à l'envers) : retirés.
_INVISIBLES = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠-⁤⁦-⁩﻿]")
TYPES_MAX, ELEMENTS_PAR_TYPE = 30, 50
PRIME_MAX, NIVEAU_MAX = 10 ** 12, 100_000
HISTORIQUE = 20                 # changements renvoyés par la fiche d'une affiche
CHANGEMENT_MAX = 300            # caractères gardés d'une valeur dans l'historique
#  Roblox : appelé par le serveur seulement, délai court, adresses fixes, images de leur CDN seulement.
ROBLOX_UTILISATEURS = "https://users.roblox.com/v1/usernames/users"
ROBLOX_PORTRAIT = "https://thumbnails.roblox.com/v1/users/avatar-headshot"
ROBLOX_DELAI = 6
ROBLOX_PAR_MINUTE = 30          # pour tout le bot
ROBLOX_JSON_MAX = 256 * 1024
AVATAR_MAX = 3 * 1024 * 1024
AVATAR_COTE = 420
AVATAR_FRAIS = 7 * 86400        # un portrait plus récent est réutilisé sans redemander à Roblox
PORTRAIT_ATTENTE = 1.5          # s : Roblox prépare encore l'image (« Pending ») — on redemande une fois
AGENT = "GoRP-Capitainerie/1.0 (bot Discord)"
#  Un rôle donné depuis le site ne donne JAMAIS de droit de gestion ni de modération.
PERMISSIONS_INTERDITES = ("administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
                          "manage_messages", "manage_threads", "manage_nicknames", "manage_events",
                          "manage_emojis", "manage_emojis_and_stickers", "manage_expressions", "create_expressions",
                          "create_events", "kick_members", "ban_members", "moderate_members", "mention_everyone",
                          "view_audit_log", "view_guild_insights", "mute_members", "deafen_members", "move_members",
                          "priority_speaker")

_get_db = None
_log = print
_actions_staff = None
_verrou = None
_cat: dict = {"types": None, "elements": None}
_appels_roblox: list = []


def setup(*, get_db, log=None, actions_staff=None):
    """`actions_staff(guild_id, auteur_id, cible_id, action, detail, surface=)` (async, facultatif) : la trace
    des rôles donnés ou retirés dans l'historique du staff."""
    global _get_db, _log, _actions_staff
    _get_db, _log, _actions_staff = get_db, log or print, actions_staff
    _cat.update(types=None, elements=None)
    _appels_roblox.clear()


def _verrou_ecriture() -> asyncio.Lock:
    """Une écriture à la fois (lire la version, la comparer, écrire) : jamais deux modifications mêlées.
    Un verrou par boucle d'évènements (un verrou né dans une autre boucle y lèverait une erreur)."""
    global _verrou
    boucle = asyncio.get_running_loop()
    if _verrou is None or _verrou[0] is not boucle:
        _verrou = (boucle, asyncio.Lock())
    return _verrou[1]


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS rell_types (cle TEXT PRIMARY KEY, nom TEXT NOT NULL, nom_en TEXT NOT NULL DEFAULT '',"
            " champ TEXT NOT NULL DEFAULT '', multiple INTEGER NOT NULL DEFAULT 1, ordre INTEGER NOT NULL DEFAULT 0,"
            " origine TEXT NOT NULL DEFAULT 'site', modifie INTEGER NOT NULL DEFAULT 1, empreinte TEXT NOT NULL DEFAULT '',"
            " version INTEGER NOT NULL DEFAULT 1, maj_le INTEGER NOT NULL DEFAULT 0, maj_par INTEGER NOT NULL DEFAULT 0)")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS rell_elements (type TEXT NOT NULL, cle TEXT NOT NULL, nom TEXT NOT NULL,"
            " nom_en TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', categorie TEXT NOT NULL DEFAULT '',"
            " rarete TEXT NOT NULL DEFAULT '', icone TEXT NOT NULL DEFAULT '', statut TEXT NOT NULL DEFAULT 'a_verifier',"
            " source TEXT NOT NULL DEFAULT '', ordre INTEGER NOT NULL DEFAULT 0, actif INTEGER NOT NULL DEFAULT 1,"
            " nouveau_movie3 INTEGER NOT NULL DEFAULT 0, origine TEXT NOT NULL DEFAULT 'site',"
            " modifie INTEGER NOT NULL DEFAULT 1, empreinte TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,"
            " maj_le INTEGER NOT NULL DEFAULT 0, maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (type, cle))")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS rell_affiches (guild_id INTEGER NOT NULL, id TEXT NOT NULL,"
            " membre_id INTEGER NOT NULL DEFAULT 0, membre_nom TEXT NOT NULL DEFAULT '', roblox_nom TEXT NOT NULL DEFAULT '',"
            " roblox_id INTEGER NOT NULL DEFAULT 0, surnom TEXT NOT NULL DEFAULT '', prime INTEGER NOT NULL DEFAULT 0,"
            " niveau INTEGER NOT NULL DEFAULT 0, grade TEXT NOT NULL DEFAULT '', statut TEXT NOT NULL DEFAULT '',"
            " attributs TEXT NOT NULL DEFAULT '{}', notes TEXT NOT NULL DEFAULT '', cree_le INTEGER NOT NULL,"
            " cree_par INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL, maj_par INTEGER NOT NULL DEFAULT 0,"
            " version INTEGER NOT NULL DEFAULT 1, retire_le INTEGER NOT NULL DEFAULT 0, retire_par INTEGER NOT NULL DEFAULT 0,"
            " PRIMARY KEY (guild_id, id))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_rell_affiches_membre ON rell_affiches(guild_id, membre_id)")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS rell_affiches_historique (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " guild_id INTEGER NOT NULL, affiche_id TEXT NOT NULL, quand INTEGER NOT NULL, par INTEGER NOT NULL DEFAULT 0,"
            " action TEXT NOT NULL, changements TEXT NOT NULL DEFAULT '[]')")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_rell_historique ON rell_affiches_historique(guild_id, affiche_id, id)")
        await db.execute("CREATE TABLE IF NOT EXISTS rell_avatars (roblox_id INTEGER PRIMARY KEY, nom TEXT NOT NULL,"
                         " nom_cle TEXT NOT NULL, maj_le INTEGER NOT NULL)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_rell_avatars_nom ON rell_avatars(nom_cle)")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS rell_roles (guild_id INTEGER NOT NULL, type TEXT NOT NULL, cle TEXT NOT NULL,"
            " role_id INTEGER NOT NULL, auto INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL DEFAULT 0,"
            " maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, type, cle))")
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  La vérification des champs
# ═══════════════════════════════════════════════════════════════════════════════

class Invalide(Exception):
    """Une saisie refusée : le champ en cause et la raison, dits tels quels à la page (400)."""

    def __init__(self, champ: str, message: str):
        super().__init__(message)
        self.champ, self.message = champ, message

    def corps(self) -> dict:
        return {"erreur": self.message, "champ": self.champ}


def _texte(v, champ: str, maxi: int, *, requis: bool = False, lignes: bool = False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise Invalide(champ, "Texte attendu.")
    v = _INVISIBLES.sub("", unicodedata.normalize("NFC", v))
    if lignes:
        v = re.sub(r"\n{4,}", "\n\n\n", v.replace("\r\n", "\n").replace("\r", "\n"))
    else:
        v = re.sub(r"\s+", " ", v)
    v = v.strip()
    if requis and not v:
        raise Invalide(champ, "Ce champ est obligatoire.")
    if len(v) > maxi:
        raise Invalide(champ, f"Trop long : {maxi} caractères au plus.")
    return v


def _entier(v, champ: str, mini: int, maxi: int, defaut: int | None = None) -> int:
    if v is None or (isinstance(v, str) and not v.strip()):
        if defaut is not None:
            return defaut
        raise Invalide(champ, "Nombre attendu.")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    elif isinstance(v, str) and re.fullmatch(r"-?[0-9]{1,15}", v.strip()):
        v = int(v.strip())
    if isinstance(v, bool) or not isinstance(v, int):
        raise Invalide(champ, "Nombre entier attendu.")
    if not mini <= v <= maxi:
        raise Invalide(champ, f"Entre {mini} et {maxi}.")
    return v


def _booleen(v, champ: str, defaut: bool) -> bool:
    if v is None:
        return defaut
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    raise Invalide(champ, "Oui ou non attendu.")


def _cle(v, champ: str) -> str:
    if not isinstance(v, str) or not FORMAT_CLE.fullmatch(v):
        raise Invalide(champ, "Clé invalide : minuscules, chiffres, « - » et « _ » (64 au plus).")
    return v


def _cle_ou_nom(d: dict, nom: str) -> str:
    """La clé donnée ; sinon celle du nom (« Maître d'équipage » → « maitre-d-equipage »)."""
    if d.get("cle") not in (None, ""):
        return _cle(d.get("cle"), "cle")
    cle = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower())
    return _cle(cle.strip("-")[:64], "cle")


def _identifiant(v, champ: str, requis: bool = True) -> int:
    """Un identifiant Discord ou Roblox : des chiffres (en texte ou en nombre)."""
    if v in (None, "", 0) and not requis:
        return 0
    if isinstance(v, int) and not isinstance(v, bool) and v > 0:
        v = str(v)
    if not isinstance(v, str) or not re.fullmatch(r"[0-9]{1,20}", v) or int(v) <= 0:
        raise Invalide(champ, "Identifiant invalide.")
    return int(v)


def _source(v) -> str:
    """Une adresse web (http ou https) ou un texte — jamais un autre schéma (`javascript:`…)."""
    s = _texte(v, "source", 500)
    if re.match(r"[a-z][a-z0-9+.-]*:", s, re.I) and not re.match(r"https?://\S+$", s, re.I):
        raise Invalide("source", "Une adresse web (https://…) ou un texte.")
    return s


def _icone(v) -> str:
    s = _texte(v, "icone", 200)
    if s and not (FORMAT_ICONE.fullmatch(s) or FORMAT_ICONE_MEDIA.fullmatch(s)):
        raise Invalide("icone", "Icône invalide : une icône du site (s/icones/…) ou une image envoyée (media/…).")
    return s


async def _icone_existe(icone: str) -> bool:
    m = FORMAT_ICONE_MEDIA.fullmatch(icone or "")
    if not m:
        return True
    async with _get_db() as db:
        async with db.execute("SELECT 1 FROM tableau_medias WHERE id=?", (m.group(1),)) as cur:
            return await cur.fetchone() is not None


def _couleur(v) -> int:
    if v in (None, ""):
        return 0
    if not isinstance(v, str) or not FORMAT_COULEUR.fullmatch(v):
        raise Invalide("couleur", "Couleur attendue : #RRVVBB.")
    return int(v[1:], 16)


def _empreinte(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _personne(g, uid) -> dict:
    m = g.get_member(int(uid)) if uid else None
    return {"id": str(uid or ""), "nom": m.display_name if m else ("" if not uid else "Membre parti")}


# ═══════════════════════════════════════════════════════════════════════════════
#  Le catalogue RELL Seas
# ═══════════════════════════════════════════════════════════════════════════════

_COL_TYPES = ("cle", "nom", "nom_en", "champ", "multiple", "ordre", "origine", "modifie", "empreinte", "version", "maj_le",
              "maj_par")
_COL_ELEMENTS = ("type", "cle", "nom", "nom_en", "description", "categorie", "rarete", "icone", "statut", "source", "ordre",
                 "actif", "nouveau_movie3", "origine", "modifie", "empreinte", "version", "maj_le", "maj_par")
_CHAMPS_TYPE = ("nom", "nom_en", "champ", "multiple", "ordre")
_CHAMPS_ELEMENT = ("nom", "nom_en", "description", "categorie", "rarete", "icone", "statut", "source", "ordre", "actif",
                   "nouveau_movie3")


def _oublier_catalogue() -> None:
    _cat.update(types=None, elements=None)


async def _catalogue() -> tuple[dict, dict]:
    """({clé : type}, {(type, clé) : élément}) — gardé en mémoire, relu après chaque écriture."""
    if _cat["types"] is None or _cat["elements"] is None:
        async with _get_db() as db:
            async with db.execute(f"SELECT {', '.join(_COL_TYPES)} FROM rell_types") as cur:
                types = {r[0]: dict(zip(_COL_TYPES, r)) for r in await cur.fetchall()}
            async with db.execute(f"SELECT {', '.join(_COL_ELEMENTS)} FROM rell_elements") as cur:
                elements = {(r[0], r[1]): dict(zip(_COL_ELEMENTS, r)) for r in await cur.fetchall()}
        _cat.update(types=types, elements=elements)
    return _cat["types"], _cat["elements"]


def _valider_type(d) -> dict:
    if not isinstance(d, dict):
        raise Invalide("type", "Type invalide.")
    nom = _texte(d.get("nom"), "nom", 60, requis=True)
    return {"cle": _cle_ou_nom(d, nom), "nom": nom,
            "nom_en": _texte(d.get("nom_en"), "nom_en", 60), "champ": _texte(d.get("champ"), "champ", 40),
            "multiple": _booleen(d.get("multiple"), "multiple", True),
            "ordre": _entier(d.get("ordre"), "ordre", -100_000, 100_000, defaut=0)}


def _valider_element(d, types: dict) -> dict:
    if not isinstance(d, dict):
        raise Invalide("element", "Élément invalide.")
    type_ = _cle(d.get("type"), "type")
    if type_ not in types:
        raise Invalide("type", "Type inconnu du catalogue.")
    statut = d.get("statut") if d.get("statut") is not None else "a_verifier"
    if statut not in STATUTS_ELEMENT:
        raise Invalide("statut", "Statut : « confirme » ou « a_verifier ».")
    nom = _texte(d.get("nom"), "nom", 80, requis=True)
    return {"type": type_, "cle": _cle_ou_nom(d, nom), "nom": nom,
            "nom_en": _texte(d.get("nom_en"), "nom_en", 80),
            "description": _texte(d.get("description"), "description", 2000, lignes=True),
            "categorie": _texte(d.get("categorie"), "categorie", 60), "rarete": _texte(d.get("rarete"), "rarete", 40),
            "icone": _icone(d.get("icone")), "statut": statut, "source": _source(d.get("source")),
            "ordre": _entier(d.get("ordre"), "ordre", -100_000, 100_000, defaut=0),
            "actif": _booleen(d.get("actif"), "actif", True),
            "nouveau_movie3": _booleen(d.get("nouveau_movie3"), "nouveau_movie3", False)}


def _sortie_type(t: dict) -> dict:
    return {"cle": t["cle"], "nom": t["nom"], "nom_en": t["nom_en"], "champ": t["champ"], "multiple": bool(t["multiple"]),
            "ordre": int(t["ordre"]), "version": int(t["version"]), "maj_le": int(t["maj_le"] or 0) or None,
            "modifie": bool(t["modifie"])}


_PRESENTES: dict = {}  # icône du site (s/…) → le fichier existe dans site/ (lu une fois : site/ ne change qu'au déploiement)


def _icone_servie(icone: str) -> str:
    """Une icône du site (`s/…`) absente de `site/` part vide : la page montre aussitôt la pastille gravée, sans
    requête perdue (404). Le chemin a passé FORMAT_ICONE (segments [a-z0-9_-]) : il ne sort jamais de site/."""
    if not icone or not icone.startswith("s/"):
        return icone or ""
    ok = _PRESENTES.get(icone)
    if ok is None:
        ok = _PRESENTES[icone] = (tableau.SITE / icone[2:]).is_file()
    return icone if ok else ""


def _sortie_element(e: dict) -> dict:
    return {"type": e["type"], "cle": e["cle"], "nom": e["nom"], "nom_en": e["nom_en"], "description": e["description"],
            "categorie": e["categorie"], "rarete": e["rarete"], "icone": _icone_servie(e["icone"]), "statut": e["statut"],
            "source": e["source"], "ordre": int(e["ordre"]), "actif": bool(e["actif"]),
            "nouveau_movie3": bool(e["nouveau_movie3"]), "version": int(e["version"]),
            "maj_le": int(e["maj_le"] or 0) or None, "modifie": bool(e["modifie"])}


def _meme(avant: dict, apres: dict, champs) -> bool:
    return all((bool(avant[c]) if isinstance(apres[c], bool) else avant[c]) == apres[c] for c in champs)


async def catalogue() -> dict:
    """`GET rell/catalogue` : `{"types": [...], "elements": [...], "maj": horodatage}`."""
    types, elements = await _catalogue()
    ordre_type = {k: (t["ordre"], t["nom"].casefold()) for k, t in types.items()}
    return {"types": [_sortie_type(t) for t in sorted(types.values(), key=lambda t: (t["ordre"], t["nom"].casefold()))],
            "elements": [_sortie_element(e) for e in sorted(
                elements.values(), key=lambda e: (ordre_type.get(e["type"], (0, "")), e["ordre"], e["nom"].casefold()))],
            "maj": max([int(x["maj_le"] or 0) for x in list(types.values()) + list(elements.values())] or [0]) or None}


async def charger_depart(chemin=None) -> dict:
    """Le catalogue de départ (même forme que `GET rell/catalogue`) : ce qui manque est AJOUTÉ ; ce qui n'a
    jamais été touché sur le site suit le fichier ; ce qui a été modifié sur le site n'est JAMAIS remplacé.
    Une entrée invalide est écartée (et comptée), jamais à moitié écrite."""
    p = Path(chemin) if chemin else DEPART
    bilan = {"types": 0, "elements": 0, "mis_a_jour": 0, "gardes": 0, "refuses": 0}
    if not p.is_file():
        return dict(bilan, absent=True)
    try:
        brut = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as ex:
        _log("[AFFICHES][E1] catalogue de départ illisible")
        _log(f"[AFFICHES][E1:DETAIL] {type(ex).__name__} {ex}")
        return dict(bilan, illisible=True)
    types_in = brut.get("types") if isinstance(brut, dict) else None
    elements_in = brut.get("elements") if isinstance(brut, dict) else None
    if not isinstance(types_in, list) or not isinstance(elements_in, list):
        _log("[AFFICHES][E1] catalogue de départ illisible")
        _log("[AFFICHES][E1:DETAIL] « types » et « elements » doivent être des listes")
        return dict(bilan, illisible=True)
    t = int(time.time())
    async with _verrou_ecriture():
        types, elements = await _catalogue()
        connus = dict(types)
        async with _get_db() as db:
            for brut_t in types_in:
                try:
                    v = _valider_type(brut_t)
                except Invalide as ex:
                    bilan["refuses"] += 1
                    _log(f"[AFFICHES:DETAIL] type de départ écarté : {ex.champ} {ex.message}")
                    continue
                emp, deja = _empreinte(v), connus.get(v["cle"])
                if deja is None:
                    await db.execute("INSERT OR IGNORE INTO rell_types (cle, nom, nom_en, champ, multiple, ordre, origine,"
                                     " modifie, empreinte, version, maj_le, maj_par) VALUES (?,?,?,?,?,?,'depart',0,?,1,?,0)",
                                     (v["cle"], v["nom"], v["nom_en"], v["champ"], int(v["multiple"]), v["ordre"], emp, t))
                    bilan["types"] += 1
                elif deja["modifie"]:
                    bilan["gardes"] += 1
                elif deja["empreinte"] != emp:
                    await db.execute("UPDATE rell_types SET nom=?, nom_en=?, champ=?, multiple=?, ordre=?, empreinte=?,"
                                     " version=version+1, maj_le=? WHERE cle=? AND modifie=0",
                                     (v["nom"], v["nom_en"], v["champ"], int(v["multiple"]), v["ordre"], emp, t, v["cle"]))
                    bilan["mis_a_jour"] += 1
                connus[v["cle"]] = dict(v, modifie=deja["modifie"] if deja else 0)
            for brut_e in elements_in:
                try:
                    v = _valider_element(brut_e, connus)
                    if not await _icone_existe(v["icone"]):
                        raise Invalide("icone", "Image inconnue.")
                except Invalide as ex:
                    bilan["refuses"] += 1
                    _log(f"[AFFICHES:DETAIL] élément de départ écarté : {ex.champ} {ex.message}")
                    continue
                emp, deja = _empreinte(v), elements.get((v["type"], v["cle"]))
                valeurs = (v["nom"], v["nom_en"], v["description"], v["categorie"], v["rarete"], v["icone"], v["statut"],
                           v["source"], v["ordre"], int(v["actif"]), int(v["nouveau_movie3"]))
                if deja is None:
                    await db.execute("INSERT OR IGNORE INTO rell_elements (type, cle, nom, nom_en, description, categorie,"
                                     " rarete, icone, statut, source, ordre, actif, nouveau_movie3, origine, modifie,"
                                     " empreinte, version, maj_le, maj_par) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'depart',0,?,1,?,0)",
                                     (v["type"], v["cle"], *valeurs, emp, t))
                    bilan["elements"] += 1
                elif deja["modifie"]:
                    bilan["gardes"] += 1
                elif deja["empreinte"] != emp:
                    await db.execute("UPDATE rell_elements SET nom=?, nom_en=?, description=?, categorie=?, rarete=?,"
                                     " icone=?, statut=?, source=?, ordre=?, actif=?, nouveau_movie3=?, empreinte=?,"
                                     " version=version+1, maj_le=? WHERE type=? AND cle=? AND modifie=0",
                                     (*valeurs, emp, t, v["type"], v["cle"]))
                    bilan["mis_a_jour"] += 1
            await db.commit()
        _oublier_catalogue()
    DERNIER_DEPART.clear()
    DERNIER_DEPART.update(bilan, quand=int(time.time()))
    if bilan["refuses"]:
        _log("[AFFICHES][E2] catalogue de départ : entrées écartées")
    if any(bilan[k] for k in ("types", "elements", "mis_a_jour", "refuses")):
        _log(f"[AFFICHES] catalogue de départ : {bilan['types']} type(s), {bilan['elements']} élément(s) ajouté(s),"
             f" {bilan['mis_a_jour']} suivi(s), {bilan['gardes']} gardé(s) (modifiés sur le site), {bilan['refuses']} écarté(s)")
    return bilan


async def _route_catalogue(g, auteur, requete, corps):
    return 200, await catalogue()


async def _route_type(g, auteur, requete, corps):
    """`POST rell/catalogue/type` `{"cle", "nom", "nom_en", "champ", "multiple", "ordre", "version"}` :
    créer (version 0) ou modifier (la version connue)."""
    try:
        v = _valider_type(corps)
        version = _entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)
    except Invalide as ex:
        return 400, ex.corps()
    t = int(time.time())
    async with _verrou_ecriture():
        types, _e = await _catalogue()
        deja = types.get(v["cle"])
        if deja is None and version:
            return 409, {"conflit": True, "actuelle": None}
        if deja is not None and version != deja["version"]:
            return 409, {"conflit": True, "actuelle": _sortie_type(deja)}
        if deja is not None and _meme(deja, v, _CHAMPS_TYPE):
            return 200, {"ok": True, "type": _sortie_type(deja), "_journal": None}
        async with _get_db() as db:
            if deja is None:
                await db.execute("INSERT INTO rell_types (cle, nom, nom_en, champ, multiple, ordre, origine, modifie,"
                                 " empreinte, version, maj_le, maj_par) VALUES (?,?,?,?,?,?,'site',1,'',1,?,?)",
                                 (v["cle"], v["nom"], v["nom_en"], v["champ"], int(v["multiple"]), v["ordre"], t, auteur.id))
            else:
                await db.execute("UPDATE rell_types SET nom=?, nom_en=?, champ=?, multiple=?, ordre=?, modifie=1,"
                                 " version=version+1, maj_le=?, maj_par=? WHERE cle=?",
                                 (v["nom"], v["nom_en"], v["champ"], int(v["multiple"]), v["ordre"], t, auteur.id, v["cle"]))
            await db.commit()
        _oublier_catalogue()
        types, _e = await _catalogue()
    return 200, {"ok": True, "type": _sortie_type(types[v["cle"]]),
                 "_journal": f"Catalogue RELL Seas : type « {v['nom']} » {'ajouté' if deja is None else 'modifié'}"}


async def _route_element(g, auteur, requete, corps):
    """`POST rell/catalogue/element` : créer (version 0) ou modifier (la version connue) un élément."""
    try:
        version = _entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)
        async with _verrou_ecriture():
            types, elements = await _catalogue()
            v = _valider_element(corps, types)
            if not await _icone_existe(v["icone"]):
                raise Invalide("icone", "Cette image n'existe plus : envoie-la de nouveau.")
            deja = elements.get((v["type"], v["cle"]))
            if deja is None and version:
                return 409, {"conflit": True, "actuelle": None}
            if deja is not None and version != deja["version"]:
                return 409, {"conflit": True, "actuelle": _sortie_element(deja)}
            if deja is not None and _meme(deja, v, _CHAMPS_ELEMENT):
                return 200, {"ok": True, "element": _sortie_element(deja), "_journal": None}
            t = int(time.time())
            valeurs = (v["nom"], v["nom_en"], v["description"], v["categorie"], v["rarete"], v["icone"], v["statut"],
                       v["source"], v["ordre"], int(v["actif"]), int(v["nouveau_movie3"]))
            async with _get_db() as db:
                if deja is None:
                    await db.execute("INSERT INTO rell_elements (type, cle, nom, nom_en, description, categorie, rarete,"
                                     " icone, statut, source, ordre, actif, nouveau_movie3, origine, modifie, empreinte,"
                                     " version, maj_le, maj_par) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'site',1,'',1,?,?)",
                                     (v["type"], v["cle"], *valeurs, t, auteur.id))
                else:
                    await db.execute("UPDATE rell_elements SET nom=?, nom_en=?, description=?, categorie=?, rarete=?,"
                                     " icone=?, statut=?, source=?, ordre=?, actif=?, nouveau_movie3=?, modifie=1,"
                                     " version=version+1, maj_le=?, maj_par=? WHERE type=? AND cle=?",
                                     (*valeurs, t, auteur.id, v["type"], v["cle"]))
                await db.commit()
            _oublier_catalogue()
            types, elements = await _catalogue()
    except Invalide as ex:
        return 400, ex.corps()
    nom_type = types[v["type"]]["nom"]
    return 200, {"ok": True, "element": _sortie_element(elements[(v["type"], v["cle"])]),
                 "_journal": f"Catalogue RELL Seas : « {v['nom']} » ({nom_type}) {'ajouté' if deja is None else 'modifié'}"}


async def _route_retirer_element(g, auteur, requete, corps):
    """`POST rell/catalogue/retirer` `{"type", "cle", "version"}` : l'élément n'est plus proposé (gardé sur les
    affiches qui l'ont déjà) ; on le remet en l'enregistrant avec « actif »."""
    try:
        type_, cle = _cle(corps.get("type"), "type"), _cle(corps.get("cle"), "cle")
        version = _entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)  # 0 : sans contrôle
    except Invalide as ex:
        return 400, ex.corps()
    async with _verrou_ecriture():
        _t, elements = await _catalogue()
        deja = elements.get((type_, cle))
        if deja is None:
            return 404, {"erreur": "Élément introuvable."}
        if not deja["actif"]:
            return 200, {"ok": True, "element": _sortie_element(deja), "_journal": None}
        if version and version != deja["version"]:
            return 409, {"conflit": True, "actuelle": _sortie_element(deja)}
        async with _get_db() as db:
            await db.execute("UPDATE rell_elements SET actif=0, modifie=1, version=version+1, maj_le=?, maj_par=?"
                             " WHERE type=? AND cle=?", (int(time.time()), auteur.id, type_, cle))
            await db.commit()
        _oublier_catalogue()
        _t, elements = await _catalogue()
    return 200, {"ok": True, "element": _sortie_element(elements[(type_, cle)]),
                 "_journal": f"Catalogue RELL Seas : « {deja['nom']} » retiré"}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les affiches
# ═══════════════════════════════════════════════════════════════════════════════

_COL_AFFICHES = ("id", "membre_id", "membre_nom", "roblox_nom", "roblox_id", "surnom", "prime", "niveau", "grade", "statut",
                 "attributs", "notes", "cree_le", "cree_par", "maj_le", "maj_par", "version", "retire_le", "retire_par")
_CHAMPS_AFFICHE = ("membre_id", "roblox_nom", "roblox_id", "surnom", "prime", "niveau", "grade", "statut", "attributs",
                   "notes")


def _ligne_affiche(r) -> dict:
    a = dict(zip(_COL_AFFICHES, r))
    try:
        attributs = json.loads(a["attributs"] or "{}")
    except ValueError:
        attributs = {}
    a["attributs"] = attributs if isinstance(attributs, dict) else {}
    return a


async def _affiches(guild_id: int, ident: str | None = None) -> list[dict]:
    sql = f"SELECT {', '.join(_COL_AFFICHES)} FROM rell_affiches WHERE guild_id=?"
    args: tuple = (int(guild_id),)
    if ident is not None:
        sql, args = sql + " AND id=?", args + (ident,)
    async with _get_db() as db:
        async with db.execute(sql, args) as cur:
            return [_ligne_affiche(r) for r in await cur.fetchall()]


async def _affiche(guild_id: int, ident: str) -> dict | None:
    lignes = await _affiches(guild_id, ident)
    return lignes[0] if lignes else None


async def _affiche_du_membre(guild_id: int, membre_id: int, sauf: str = "") -> dict | None:
    async with _get_db() as db:
        async with db.execute(f"SELECT {', '.join(_COL_AFFICHES)} FROM rell_affiches WHERE guild_id=? AND membre_id=?"
                              " AND retire_le=0 AND id<>? LIMIT 1", (int(guild_id), int(membre_id), sauf)) as cur:
            r = await cur.fetchone()
    return _ligne_affiche(r) if r else None


def _avatar_roblox(roblox_id) -> str:
    if not roblox_id:
        return ""
    chemin, _typ = tableau._chemin_media(f"avatar/{int(roblox_id)}")
    return f"media/avatar/{int(roblox_id)}" if chemin is not None else ""


def _sortie_affiche(g, a: dict) -> dict:
    m = g.get_member(int(a["membre_id"])) if a["membre_id"] else None
    return {"id": a["id"],
            "membre": {"id": str(a["membre_id"] or ""), "nom": m.display_name if m else a["membre_nom"],
                       "avatar": str(m.display_avatar.with_size(128).url) if m else "", "present": m is not None},
            "roblox": {"nom": a["roblox_nom"], "id": str(a["roblox_id"] or ""), "avatar": _avatar_roblox(a["roblox_id"])},
            "surnom": a["surnom"], "prime": int(a["prime"]), "niveau": int(a["niveau"]), "grade": a["grade"],
            "statut": a["statut"], "attributs": a["attributs"], "notes": a["notes"], "cree_le": int(a["cree_le"]),
            "cree_par": _personne(g, a["cree_par"]), "maj_le": int(a["maj_le"]), "maj_par": _personne(g, a["maj_par"]),
            "version": int(a["version"]), "retire_le": int(a["retire_le"]) or None}


def _attributs(v, types: dict, elements: dict) -> dict:
    """`{type : [clés]}` — uniquement des éléments du catalogue (un seul pour un type à choix unique)."""
    if v is None:
        return {}
    if not isinstance(v, dict) or len(v) > TYPES_MAX:
        raise Invalide("attributs", "Attributs invalides.")
    out = {}
    for type_, cles in v.items():
        if not isinstance(type_, str) or type_ not in types:
            raise Invalide("attributs", "Type inconnu du catalogue.")
        if isinstance(cles, str):
            cles = [cles]
        if not isinstance(cles, list) or len(cles) > ELEMENTS_PAR_TYPE or not all(isinstance(c, str) for c in cles):
            raise Invalide("attributs", f"« {types[type_]['nom']} » : une liste d'éléments du catalogue.")
        vues = list(dict.fromkeys(cles))
        for cle in vues:
            if (type_, cle) not in elements:
                raise Invalide("attributs", f"« {types[type_]['nom']} » : élément inconnu du catalogue.")
        if len(vues) > 1 and not types[type_]["multiple"]:
            raise Invalide("attributs", f"« {types[type_]['nom']} » : un seul choix.")
        if vues:
            out[type_] = vues
    return out


def _valider_affiche(g, corps: dict, types: dict, elements: dict, deja: dict | None) -> dict:
    membre = corps.get("membre_id")
    if membre is None and isinstance(corps.get("membre"), dict):
        membre = corps["membre"].get("id")
    membre_id = _identifiant(membre, "membre_id", requis=False)
    m = g.get_member(membre_id) if membre_id else None
    if membre_id and m is None and (deja is None or deja["membre_id"] != membre_id):
        raise Invalide("membre_id", "Ce membre n'est pas sur le serveur.")
    roblox = corps.get("roblox") if isinstance(corps.get("roblox"), dict) else {}
    roblox_nom = _texte(corps.get("roblox_nom", roblox.get("nom")), "roblox_nom", 20)
    if roblox_nom and not FORMAT_ROBLOX.fullmatch(roblox_nom):
        raise Invalide("roblox_nom", "Pseudo Roblox : 3 à 20 lettres, chiffres ou « _ ».")
    garde_nom = deja["membre_nom"] if deja and deja["membre_id"] == membre_id else ""  # un membre parti garde son nom
    roblox_id = _identifiant(corps.get("roblox_id", roblox.get("id")), "roblox_id", requis=False)
    v = {"membre_id": membre_id, "membre_nom": m.display_name[:100] if m else garde_nom,
         "roblox_nom": roblox_nom, "roblox_id": roblox_id if roblox_nom else 0,
         "surnom": _texte(corps.get("surnom"), "surnom", 60),
         "prime": _entier(corps.get("prime"), "prime", 0, PRIME_MAX, defaut=0),
         "niveau": _entier(corps.get("niveau"), "niveau", 0, NIVEAU_MAX, defaut=0),
         "grade": _texte(corps.get("grade"), "grade", 40), "statut": _texte(corps.get("statut"), "statut", 40),
         "attributs": _attributs(corps.get("attributs"), types, elements),
         "notes": _texte(corps.get("notes"), "notes", 4000, lignes=True)}
    if not (v["membre_id"] or v["roblox_nom"] or v["surnom"]):
        raise Invalide("membre_id", "Une affiche a besoin d'un membre, d'un pseudo Roblox ou d'un surnom.")
    return v


def _court(x):
    if isinstance(x, str) and len(x) > CHANGEMENT_MAX:
        return x[:CHANGEMENT_MAX - 1] + "…"
    return x


def _changements(avant: dict | None, apres: dict) -> list:
    out = []
    for c in _CHAMPS_AFFICHE:
        a = avant[c] if avant is not None else None
        if a != apres[c] and not (avant is None and apres[c] in ("", 0, {}, None)):
            out.append({"champ": c, "avant": _court(a), "apres": _court(apres[c])})
    return out


async def _noter_historique(db, guild_id: int, ident: str, par: int, action: str, changements: list, t: int) -> None:
    await db.execute("INSERT INTO rell_affiches_historique (guild_id, affiche_id, quand, par, action, changements)"
                     " VALUES (?,?,?,?,?,?)", (int(guild_id), ident, t, int(par), action,
                                               json.dumps(changements, ensure_ascii=False)))


def _titre(a: dict) -> str:
    return a.get("surnom") or a.get("membre_nom") or a.get("roblox_nom") or a.get("id", "")


async def _route_affiches(g, auteur, requete, corps):
    """`GET rell/affiches` → `{"affiches": [...], "corbeille": [...], "stats": {...}}`."""
    toutes = await _affiches(g.id)
    actives = [a for a in toutes if not a["retire_le"]]
    corbeille = [a for a in toutes if a["retire_le"]]
    par_type: dict = {}
    for a in actives:
        for type_, cles in a["attributs"].items():
            for cle in cles:
                par_type.setdefault(type_, {})[cle] = par_type.get(type_, {}).get(cle, 0) + 1
    tri = lambda a: (_titre(a).casefold(), a["id"])  # noqa: E731
    return 200, {"affiches": [_sortie_affiche(g, a) for a in sorted(actives, key=tri)],
                 "corbeille": [_sortie_affiche(g, a) for a in sorted(corbeille, key=lambda a: -a["retire_le"])],
                 "stats": {"total": len(actives), "corbeille": len(corbeille),
                           "primes": sum(int(a["prime"]) for a in actives),
                           "prime_totale": sum(int(a["prime"]) for a in actives),
                           "sans_membre": sum(1 for a in actives if not a["membre_id"]),
                           "membres_partis": sum(1 for a in actives if a["membre_id"] and g.get_member(int(a["membre_id"])) is None),
                           "par_type": par_type}}


async def _route_affiche_lire(g, auteur, requete, corps):
    """`GET rell/affiche?id=` → `{"affiche": {...}, "historique": [20 derniers changements]}`."""
    ident = requete.get("id", "")
    if not FORMAT_AFFICHE.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'affiche invalide.", "champ": "id"}
    a = await _affiche(g.id, ident)
    if a is None:
        return 404, {"erreur": "Affiche introuvable."}
    async with _get_db() as db:
        async with db.execute("SELECT quand, par, action, changements FROM rell_affiches_historique WHERE guild_id=?"
                              " AND affiche_id=? ORDER BY id DESC LIMIT ?", (g.id, ident, HISTORIQUE)) as cur:
            rows = await cur.fetchall()
    historique = []
    for quand, par, action, changements in rows:
        try:
            ch = json.loads(changements or "[]")
        except ValueError:
            ch = []
        ch = ch if isinstance(ch, list) else []
        qui = _personne(g, par)
        historique.append({"quand": int(quand), "qui": qui["nom"], "quoi": _quoi(action, ch), "par": qui,
                           "action": action, "changements": ch})
    sortie = _sortie_affiche(g, a)
    return 200, dict(sortie, affiche=sortie, historique=historique)


_LIBELLES = {"membre_id": "Membre", "roblox_nom": "Pseudo Roblox", "roblox_id": "Compte Roblox", "surnom": "Surnom",
             "prime": "Prime", "niveau": "Niveau", "grade": "Grade", "statut": "Statut", "attributs": "Fiche du jeu",
             "notes": "Notes"}


def _quoi(action: str, changements: list) -> str:
    """Une ligne lisible d'un changement : « Prime : 100 000 → 250 000 · Grade : Second → Capitaine »."""
    if action == "creee":
        return "Affiche créée"
    if action == "retiree":
        return "Mise à la corbeille"
    if action == "restauree":
        return "Sortie de la corbeille"
    morceaux = []
    for c in changements:
        champ = c.get("champ") if isinstance(c, dict) else ""
        nom = _LIBELLES.get(champ, str(champ))
        if champ in ("prime", "niveau"):
            a, b = (f"{int(x or 0):,}".replace(",", "\u202f") for x in (c.get("avant"), c.get("apres")))
            morceaux.append(f"{nom} : {a} → {b}")
        elif champ in ("surnom", "grade", "statut", "roblox_nom"):
            morceaux.append(f"{nom} : {c.get('avant') or '—'} → {c.get('apres') or '—'}")
        else:
            morceaux.append(f"{nom} : modifié" if champ != "notes" else "Notes modifiées")
    return " · ".join(morceaux) or "Affiche modifiée"


async def _route_affiche(g, auteur, requete, corps):
    """`POST rell/affiche` : créer (sans `id` ou un `id` neuf choisi par la page, version 0) ou modifier (la
    version connue). Conflit : 409 `{"conflit": true, "actuelle": {...}}` ; un membre a déjà son affiche :
    409 `{"conflit": true, "doublon": true, "actuelle": {...}}`."""
    ident = corps.get("id")
    if ident in (None, ""):
        ident = None
    elif not isinstance(ident, str) or not FORMAT_AFFICHE.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'affiche invalide.", "champ": "id"}
    try:
        version = _entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)
        async with _verrou_ecriture():
            types, elements = await _catalogue()
            deja = await _affiche(g.id, ident) if ident else None
            v = _valider_affiche(g, corps, types, elements, deja)
            if deja is None and version:
                return 409, {"conflit": True, "actuelle": None}
            if deja is not None and deja["retire_le"]:
                return 409, {"conflit": True, "retiree": True, "actuelle": _sortie_affiche(g, deja)}
            if deja is not None and version != deja["version"]:
                return 409, {"conflit": True, "actuelle": _sortie_affiche(g, deja)}
            if v["membre_id"]:
                doublon = await _affiche_du_membre(g.id, v["membre_id"], sauf=ident or "")
                if doublon is not None:
                    return 409, {"conflit": True, "doublon": True, "actuelle": _sortie_affiche(g, doublon)}
            changements = _changements(deja, v)
            if deja is not None and not changements:
                return 200, {"ok": True, "affiche": _sortie_affiche(g, deja), "_journal": None}
            t = int(time.time())
            valeurs = (v["membre_id"], v["membre_nom"], v["roblox_nom"], v["roblox_id"], v["surnom"], v["prime"],
                       v["niveau"], v["grade"], v["statut"], json.dumps(v["attributs"], ensure_ascii=False), v["notes"])
            async with _get_db() as db:
                if deja is None:
                    ident = ident or secrets.token_urlsafe(9)
                    await db.execute("INSERT INTO rell_affiches (guild_id, id, membre_id, membre_nom, roblox_nom, roblox_id,"
                                     " surnom, prime, niveau, grade, statut, attributs, notes, cree_le, cree_par, maj_le,"
                                     " maj_par, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                                     (g.id, ident, *valeurs, t, auteur.id, t, auteur.id))
                else:
                    await db.execute("UPDATE rell_affiches SET membre_id=?, membre_nom=?, roblox_nom=?, roblox_id=?,"
                                     " surnom=?, prime=?, niveau=?, grade=?, statut=?, attributs=?, notes=?, maj_le=?,"
                                     " maj_par=?, version=version+1 WHERE guild_id=? AND id=?",
                                     (*valeurs, t, auteur.id, g.id, ident))
                await _noter_historique(db, g.id, ident, auteur.id, "creee" if deja is None else "modifiee", changements, t)
                await db.commit()
            nouvelle = await _affiche(g.id, ident)
    except Invalide as ex:
        return 400, ex.corps()
    rep = {"ok": True, "affiche": _sortie_affiche(g, nouvelle),
           "_journal": {"texte": f"Affiche « {_titre(nouvelle)} » {'créée' if deja is None else 'modifiée'}",
                        "membre_id": nouvelle["membre_id"],
                        "detail": ", ".join(c["champ"] for c in changements)[:600]}}
    roles = await _roles_automatiques(g, auteur, nouvelle)
    if roles is not None:
        rep["roles"] = roles
    return 200, rep


async def _route_affiche_retirer(g, auteur, requete, corps):
    """`POST rell/affiche/retirer` `{"id", "version"?}` : à la corbeille (effacée après 30 jours) ; avec
    `"restaurer": true`, sortie de la corbeille (comme `rell/affiche/restaurer`)."""
    ident = corps.get("id")
    if isinstance(ident, int) and not isinstance(ident, bool):
        ident = str(ident)
    if not isinstance(ident, str) or not FORMAT_AFFICHE.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'affiche invalide.", "champ": "id"}
    try:
        version = _entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)  # 0 : sans contrôle
        if _booleen(corps.get("restaurer"), "restaurer", False):
            return await _route_affiche_restaurer(g, auteur, requete, dict(corps, id=ident))
    except Invalide as ex:
        return 400, ex.corps()
    async with _verrou_ecriture():
        a = await _affiche(g.id, ident)
        if a is None:
            return 404, {"erreur": "Affiche introuvable."}
        if a["retire_le"]:
            return 200, {"ok": True, "affiche": _sortie_affiche(g, a), "_journal": None}
        if version and version != a["version"]:
            return 409, {"conflit": True, "actuelle": _sortie_affiche(g, a)}
        t = int(time.time())
        async with _get_db() as db:
            await db.execute("UPDATE rell_affiches SET retire_le=?, retire_par=?, maj_le=?, maj_par=?, version=version+1"
                             " WHERE guild_id=? AND id=?", (t, auteur.id, t, auteur.id, g.id, ident))
            await _noter_historique(db, g.id, ident, auteur.id, "retiree", [], t)
            await db.commit()
        a = await _affiche(g.id, ident)
    return 200, {"ok": True, "affiche": _sortie_affiche(g, a),
                 "_journal": {"texte": f"Affiche « {_titre(a)} » mise à la corbeille", "membre_id": a["membre_id"]}}


async def _route_affiche_restaurer(g, auteur, requete, corps):
    """`POST rell/affiche/restaurer` `{"id"}` : sortie de la corbeille (si le membre n'a pas d'autre affiche)."""
    ident = corps.get("id")
    if isinstance(ident, int) and not isinstance(ident, bool):
        ident = str(ident)
    if not isinstance(ident, str) or not FORMAT_AFFICHE.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'affiche invalide.", "champ": "id"}
    async with _verrou_ecriture():
        a = await _affiche(g.id, ident)
        if a is None:
            return 404, {"erreur": "Affiche introuvable (la corbeille se vide après 30 jours)."}
        if not a["retire_le"]:
            return 200, {"ok": True, "affiche": _sortie_affiche(g, a), "_journal": None}
        if a["membre_id"]:
            doublon = await _affiche_du_membre(g.id, a["membre_id"], sauf=ident)
            if doublon is not None:
                return 409, {"conflit": True, "doublon": True, "actuelle": _sortie_affiche(g, doublon)}
        t = int(time.time())
        async with _get_db() as db:
            await db.execute("UPDATE rell_affiches SET retire_le=0, retire_par=0, maj_le=?, maj_par=?, version=version+1"
                             " WHERE guild_id=? AND id=?", (t, auteur.id, g.id, ident))
            await _noter_historique(db, g.id, ident, auteur.id, "restauree", [], t)
            await db.commit()
        a = await _affiche(g.id, ident)
    return 200, {"ok": True, "affiche": _sortie_affiche(g, a),
                 "_journal": {"texte": f"Affiche « {_titre(a)} » restaurée", "membre_id": a["membre_id"]}}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les portraits Roblox (demandés par le serveur, jamais par la page)
# ═══════════════════════════════════════════════════════════════════════════════

async def _lire_borne(r, maximum: int) -> bytes:
    morceaux, total = [], 0
    async for bloc in r.content.iter_chunked(65536):
        total += len(bloc)
        if total > maximum:
            raise ValueError("réponse trop longue")
        morceaux.append(bloc)
    return b"".join(morceaux)


async def _http_json(methode: str, url: str, *, params=None, json_=None):
    """(statut, données) d'une API de Roblox — délai court, aucune redirection suivie."""
    import aiohttp
    delai = aiohttp.ClientTimeout(total=ROBLOX_DELAI, connect=4)
    async with aiohttp.ClientSession(timeout=delai, headers={"User-Agent": AGENT, "Accept": "application/json"}) as s:
        async with s.request(methode, url, params=params, json=json_, allow_redirects=False) as r:
            brut = await _lire_borne(r, ROBLOX_JSON_MAX)
            if r.status != 200:
                return r.status, None
    return 200, json.loads(brut.decode("utf-8"))


async def _http_octets(url: str, maximum: int):
    """(statut, octets) d'une image du CDN de Roblox — délai court, taille bornée, aucune redirection."""
    import aiohttp
    delai = aiohttp.ClientTimeout(total=ROBLOX_DELAI, connect=4)
    async with aiohttp.ClientSession(timeout=delai, headers={"User-Agent": AGENT}) as s:
        async with s.get(url, allow_redirects=False) as r:
            if r.status != 200:
                return r.status, b""
            return 200, await _lire_borne(r, maximum)


def _adresse_cdn(url) -> bool:
    """Une image de Roblox ne vient que de son CDN (https, *.rbxcdn.com) : jamais une adresse quelconque."""
    if not isinstance(url, str) or len(url) > 1000:
        return False
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return False
    hote = (u.hostname or "").lower()
    return (u.scheme == "https" and port in (None, 443) and not u.username and not u.password
            and (hote == "rbxcdn.com" or hote.endswith(".rbxcdn.com")))


async def _portrait(roblox_id: int) -> str:
    """Le portrait (tête, 420 px) téléchargé PAR LE SERVEUR, refait en WebP, gardé ; `media/avatar/<id>` ou ""."""
    for essai in range(2):
        status, data = await _http_json("GET", ROBLOX_PORTRAIT, params={"userIds": str(roblox_id), "size": "420x420",
                                                                         "format": "Png", "isCircular": "false"})
        lignes = data.get("data") if status == 200 and isinstance(data, dict) else None
        item = next((x for x in lignes or [] if isinstance(x, dict) and x.get("targetId") == roblox_id), None)
        if item is None:
            return ""
        if item.get("state") == "Completed":
            break
        if essai == 0:
            await asyncio.sleep(PORTRAIT_ATTENTE)
    else:
        return ""
    url = item.get("imageUrl")
    if not _adresse_cdn(url):
        return ""
    status, octets = await _http_octets(url, AVATAR_MAX)
    if status != 200 or tableau.type_image(octets) is None:
        return ""
    try:
        sortie, _l, _h, typ = await asyncio.to_thread(tableau.reencoder_image, octets, AVATAR_COTE)
    except ValueError:
        return ""
    dossier = tableau.dossier_site("avatars")
    ext = "webp" if typ == "image/webp" else "png"
    await asyncio.to_thread(tableau._ecrire_atomique, dossier / f"{roblox_id}.{ext}", sortie)
    autre = dossier / f"{roblox_id}.{'png' if ext == 'webp' else 'webp'}"
    if autre.exists():
        await asyncio.to_thread(autre.unlink)
    return f"media/avatar/{roblox_id}"


async def _route_avatar(g, auteur, requete, corps):
    """`POST rell/avatar` `{"roblox_nom"}` → `{"roblox_id", "nom", "avatar"}` : l'identifiant du joueur et son
    portrait, servi par `media/avatar/<id>`."""
    nom = corps.get("roblox_nom")
    nom = nom.strip() if isinstance(nom, str) else ""
    if not FORMAT_ROBLOX.fullmatch(nom):
        return 400, {"erreur": "Pseudo Roblox : 3 à 20 lettres, chiffres ou « _ ».", "champ": "roblox_nom"}
    t = time.time()
    async with _get_db() as db:
        async with db.execute("SELECT roblox_id, nom, maj_le FROM rell_avatars WHERE nom_cle=? ORDER BY maj_le DESC"
                              " LIMIT 1", (nom.casefold(),)) as cur:
            connu = await cur.fetchone()
    if connu is not None and t - int(connu[2]) < AVATAR_FRAIS and _avatar_roblox(connu[0]):
        return 200, {"ok": True, "roblox_id": str(connu[0]), "nom": connu[1], "avatar": _avatar_roblox(connu[0]),
                     "_journal": None}
    recents = [x for x in _appels_roblox if t - x < 60]
    if len(recents) >= ROBLOX_PAR_MINUTE:
        return 429, {"erreur": "Trop de recherches Roblox d'un coup : attends une minute."}
    _appels_roblox[:] = recents + [t]
    try:
        status, data = await _http_json("POST", ROBLOX_UTILISATEURS, json_={"usernames": [nom], "excludeBannedUsers": False})
    except Exception as ex:  # réseau, délai, réponse illisible : Roblox injoignable, la page le dit
        _log("[AFFICHES][E2] Roblox injoignable (nom)")
        _log(f"[AFFICHES][E2:DETAIL] {type(ex).__name__} {ex}")
        return 502, {"erreur": "Roblox ne répond pas : réessaie dans un instant."}
    if status != 200 or not isinstance(data, dict):
        _log("[AFFICHES][E2] Roblox injoignable (nom)")
        _log(f"[AFFICHES][E2:DETAIL] statut {status}")
        return 502, {"erreur": "Roblox ne répond pas : réessaie dans un instant."}
    joueur = next((u for u in data.get("data") or [] if isinstance(u, dict) and isinstance(u.get("id"), int)
                   and not isinstance(u.get("id"), bool) and u["id"] > 0), None)
    if joueur is None:
        return 404, {"erreur": "Aucun joueur Roblox à ce nom.", "champ": "roblox_nom"}
    rid = int(joueur["id"])
    vrai = str(joueur.get("name") or nom)
    vrai = vrai if FORMAT_ROBLOX.fullmatch(vrai) else nom
    try:
        avatar = await _portrait(rid) or _avatar_roblox(rid)  # sinon l'ancien portrait, s'il y en a un
    except Exception as ex:  # le portrait manque : l'identifiant reste bon, la page met un portrait vide
        _log("[AFFICHES][E3] portrait Roblox indisponible")
        _log(f"[AFFICHES][E3:DETAIL] {type(ex).__name__} {ex}")
        avatar = _avatar_roblox(rid)
    async with _get_db() as db:
        await db.execute("INSERT OR REPLACE INTO rell_avatars (roblox_id, nom, nom_cle, maj_le) VALUES (?,?,?,?)",
                         (rid, vrai, vrai.casefold(), int(t)))
        if vrai.casefold() != nom.casefold():
            await db.execute("DELETE FROM rell_avatars WHERE nom_cle=? AND roblox_id<>?", (nom.casefold(), rid))
        await db.commit()
    return 200, {"ok": True, "roblox_id": str(rid), "nom": vrai, "avatar": avatar, "_journal": None}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les rôles des métiers
# ═══════════════════════════════════════════════════════════════════════════════

def refus_role(g, role) -> str | None:
    """Pourquoi ce rôle ne peut pas être donné depuis le site — None s'il le peut."""
    if role is None:
        return "Rôle introuvable."
    if role.id == getattr(g, "id", None) or getattr(role, "is_default", lambda: False)():
        return "Le rôle @everyone ne se donne pas."
    if getattr(role, "managed", False):
        return "Rôle géré par une intégration (bot, boost…) : impossible à donner."
    haut = getattr(getattr(getattr(g, "me", None), "top_role", None), "position", 0)
    if getattr(role, "position", 0) >= haut:
        return "Ce rôle est au-dessus du mien : je ne peux pas le donner."
    droits = getattr(role, "permissions", None)
    if droits is not None and any(getattr(droits, p, False) is True for p in PERMISSIONS_INTERDITES):
        return "Ce rôle donne des droits de gestion ou de modération : jamais depuis le site."
    return None


def _peut_gerer_roles(g) -> bool:
    return bool(getattr(getattr(getattr(g, "me", None), "guild_permissions", None), "manage_roles", False))


def _couleur_role(role) -> str:
    valeur = getattr(getattr(role, "colour", None), "value", 0) or 0
    return f"#{valeur:06x}" if valeur else ""


async def _liens(guild_id: int, seulement_auto: bool = False) -> list[dict]:
    async with _get_db() as db:
        async with db.execute("SELECT type, cle, role_id, auto FROM rell_roles WHERE guild_id=?"
                              + (" AND auto=1" if seulement_auto else "") + " ORDER BY type, cle", (int(guild_id),)) as cur:
            return [{"type": r[0], "cle": r[1], "role_id": int(r[2]), "auto": bool(r[3])} for r in await cur.fetchall()]


def _sortie_lien(g, lien: dict, elements: dict) -> dict:
    role = g.get_role(lien["role_id"])
    refus = refus_role(g, role) if role is not None else "Ce rôle n'existe plus."
    e = elements.get((lien["type"], lien["cle"]))
    return {"type": lien["type"], "cle": lien["cle"], "element": e["nom"] if e else "", "role_id": str(lien["role_id"]),
            "role_nom": getattr(role, "name", ""), "couleur": _couleur_role(role) if role is not None else "",
            "auto": lien["auto"], "existe": role is not None, "attribuable": refus is None, "raison": refus or ""}


async def _route_roles(g, auteur, requete, corps):
    """`GET rell/roles` → `{"liens": [...], "roles": [rôles attribuables], "gestion": bool}`."""
    _t, elements = await _catalogue()
    roles = [{"id": str(r.id), "nom": r.name, "couleur": _couleur_role(r), "position": int(getattr(r, "position", 0))}
             for r in sorted(getattr(g, "roles", []) or [], key=lambda r: -getattr(r, "position", 0))
             if refus_role(g, r) is None]
    return 200, {"liens": [_sortie_lien(g, x, elements) for x in await _liens(g.id)], "roles": roles,
                 "gestion": _peut_gerer_roles(g)}


async def _route_role(g, auteur, requete, corps):
    """`POST rell/role` : lier un élément du catalogue à un rôle existant (`role_id`), ou en créer un (`creer`:
    {"nom", "couleur"} — aucune permission), `auto` : appliqué à chaque enregistrement d'affiche ; `retirer`:
    true défait le lien (le rôle reste sur Discord)."""
    try:
        type_, cle = _cle(corps.get("type"), "type"), _cle(corps.get("cle"), "cle")
        auto = _booleen(corps.get("auto"), "auto", False)
        retirer = _booleen(corps.get("retirer"), "retirer", False)
        creer = corps.get("creer")
        if creer is not None and not isinstance(creer, dict):
            raise Invalide("creer", "Création invalide.")
        nom = _texte(creer.get("nom"), "nom", 100, requis=True) if creer is not None else ""
        couleur = _couleur(creer.get("couleur")) if creer is not None else 0
        role_id = 0 if (creer is not None or retirer) else _identifiant(corps.get("role_id"), "role_id")
    except Invalide as ex:
        return 400, ex.corps()
    _t, elements = await _catalogue()
    e = elements.get((type_, cle))
    if e is None:
        return 404, {"erreur": "Élément introuvable dans le catalogue."}
    if retirer:
        async with _get_db() as db:
            cur = await db.execute("DELETE FROM rell_roles WHERE guild_id=? AND type=? AND cle=?", (g.id, type_, cle))
            n = cur.rowcount or 0
            await db.commit()
        return 200, {"ok": True, "liens": [_sortie_lien(g, x, elements) for x in await _liens(g.id)],
                     "_journal": f"Rôle du métier « {e['nom']} » délié" if n else None}
    cree = False
    if creer is not None:
        if not _peut_gerer_roles(g):
            return 403, {"erreur": "Il me manque la permission « Gérer les rôles »."}
        try:
            role = await g.create_role(name=nom, colour=discord.Colour(couleur), permissions=discord.Permissions.none(),
                                       hoist=False, mentionable=False,
                                       reason=f"Métier {e['nom']} — site de la direction ({auteur})")
        except discord.HTTPException as ex:
            _log("[AFFICHES][E4] rôle du métier non créé")
            _log(f"[AFFICHES][E4:DETAIL] {type(ex).__name__} {ex}")
            return 502, {"erreur": "Discord a refusé de créer le rôle."}
        cree = True
    else:
        role = g.get_role(role_id)
        refus = refus_role(g, role)
        if refus is not None:
            return 400, {"erreur": refus, "champ": "role_id"}
    async with _get_db() as db:
        await db.execute("INSERT OR REPLACE INTO rell_roles (guild_id, type, cle, role_id, auto, maj_le, maj_par)"
                         " VALUES (?,?,?,?,?,?,?)", (g.id, type_, cle, role.id, int(auto), int(time.time()), auteur.id))
        await db.commit()
    lien = {"type": type_, "cle": cle, "role_id": role.id, "auto": auto}
    return 200, {"ok": True, "lien": _sortie_lien(g, lien, elements),
                 "liens": [_sortie_lien(g, x, elements) for x in await _liens(g.id)],
                 "_journal": f"Rôle « {role.name} »{' créé et' if cree else ''} lié au métier « {e['nom']} »"
                             + (" (attribution automatique)" if auto else "")}


async def appliquer_roles(g, auteur, membre, attributs: dict, seulement_auto: bool = False) -> dict:
    """Donne à `membre` les rôles liés aux éléments de `attributs` et retire les rôles liés qu'il n'a plus — jamais
    un autre rôle. → `{"ajoutes", "retires", "ignores"}` ou `{"erreur"}`."""
    liens = await _liens(g.id, seulement_auto)
    voulus = {x["role_id"] for x in liens if x["cle"] in (attributs.get(x["type"]) or [])}
    ajouter, retirer, ignores = [], [], []
    a_deja = {r.id for r in getattr(membre, "roles", []) or []}
    for rid in sorted({x["role_id"] for x in liens}):
        role = g.get_role(rid)
        if role is None:
            continue
        if (rid in voulus) == (rid in a_deja):
            continue
        if refus_role(g, role) is not None:
            ignores.append({"id": str(rid), "nom": role.name})
        elif rid in voulus:
            ajouter.append(role)
        else:
            retirer.append(role)
    if not ajouter and not retirer:
        return {"ajoutes": [], "retires": [], "ignores": ignores}
    if not _peut_gerer_roles(g):
        return {"erreur": "Il me manque la permission « Gérer les rôles »."}
    raison = f"Rôles des métiers — site de la direction ({auteur})"
    try:
        if ajouter:
            await membre.add_roles(*ajouter, reason=raison)
        if retirer:
            await membre.remove_roles(*retirer, reason=raison)
    except discord.HTTPException as ex:
        _log("[AFFICHES][E5] rôles des métiers non appliqués")
        _log(f"[AFFICHES][E5:DETAIL] {type(ex).__name__} {ex}")
        return {"erreur": "Discord a refusé (hiérarchie ou permission)."}
    if _actions_staff is not None:
        try:
            await _actions_staff(g.id, auteur.id, membre.id, "roles_metiers",
                                 " ".join([f"+{r.name}" for r in ajouter] + [f"-{r.name}" for r in retirer])[:300],
                                 surface="tableau")
        except Exception as ex:  # l'historique du staff manque une ligne ; les rôles sont bien posés
            _log("[AFFICHES][E6] trace du staff non écrite")
            _log(f"[AFFICHES][E6:DETAIL] {type(ex).__name__} {ex}")
    return {"ajoutes": [{"id": str(r.id), "nom": r.name} for r in ajouter],
            "retires": [{"id": str(r.id), "nom": r.name} for r in retirer], "ignores": ignores}


def _phrase_roles(nom: str, res: dict) -> str:
    morceaux = [f"+{x['nom']}" for x in res.get("ajoutes", [])] + [f"−{x['nom']}" for x in res.get("retires", [])]
    return f"Rôles des métiers de {nom} : {', '.join(morceaux)}"


async def _roles_automatiques(g, auteur, affiche: dict) -> dict | None:
    """Après l'enregistrement d'une affiche : les liens « automatiques » appliqués à son membre (s'il est là)."""
    m = g.get_member(int(affiche["membre_id"])) if affiche["membre_id"] else None
    if m is None or not await _liens(g.id, True):
        return None
    refus = await tableau.limite_grave(g, auteur, "roles", 1)
    if refus is not None:
        return {"erreur": refus}
    res = await appliquer_roles(g, auteur, m, affiche["attributs"], seulement_auto=True)
    if res.get("ajoutes") or res.get("retires"):
        await registre.noter(g.id, "Site", "site.roles_metiers", f"{_phrase_roles(m.display_name, res)} (automatique)",
                             membre_id=m.id, auteur_id=auteur.id)
    return res


async def _route_appliquer(g, auteur, requete, corps):
    """`POST rell/roles/appliquer` `{"affiche_id"}` → `{"ok", "ajoutes", "retires", "ignores"}`."""
    ident = corps.get("affiche_id")
    if not isinstance(ident, str) or not FORMAT_AFFICHE.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'affiche invalide.", "champ": "affiche_id"}
    a = await _affiche(g.id, ident)
    if a is None or a["retire_le"]:
        return 404, {"erreur": "Affiche introuvable."}
    m = g.get_member(int(a["membre_id"])) if a["membre_id"] else None
    if m is None:
        return 409, {"erreur": "Cette affiche n'est liée à aucun membre présent sur le serveur."}
    res = await appliquer_roles(g, auteur, m, a["attributs"])
    if "erreur" in res:
        return 502 if "Discord" in res["erreur"] else 403, {"erreur": res["erreur"]}
    change = res["ajoutes"] or res["retires"]
    message = (f"{len(res['ajoutes'])} rôle(s) donné(s), {len(res['retires'])} retiré(s)." if change
               else "Rien à changer : ses rôles suivent déjà ses métiers.")
    return 200, dict(res, ok=True, message=message, donnes=[x["nom"] for x in res["ajoutes"]],
                     _journal={"texte": _phrase_roles(m.display_name, res), "membre_id": m.id} if change else None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le branchement sur le site (`tableau.monter(affiches)`) et le nettoyage
# ═══════════════════════════════════════════════════════════════════════════════

async def medias_utilises(guild_id: int) -> set:
    """Les images du site encore utilisées ici (icônes du catalogue) : jamais retirées par le nettoyage."""
    _t, elements = await _catalogue()
    return {m.group(1) for e in elements.values() if (m := FORMAT_ICONE_MEDIA.fullmatch(e["icone"] or ""))}


def _premier(attributs: dict, *types) -> list:
    for t in types:
        if attributs.get(t):
            return list(attributs[t])
    return []


async def fiches_clan(g) -> list[dict]:
    """Pour les annonces du clan (`evenements.brancher(fiches=…)`) : une fiche par membre qui a son affiche —
    ses métiers, sa race, sa faction (clés du catalogue), son grade, son surnom, son pseudo Roblox."""
    out = []
    for a in await _affiches(g.id):
        if a["retire_le"] or not a["membre_id"]:
            continue
        m = g.get_member(int(a["membre_id"]))
        out.append({"membre_id": str(a["membre_id"]), "nom": m.display_name if m else a["membre_nom"],
                    "metiers": _premier(a["attributs"], "metier", "metiers"),
                    "race": (_premier(a["attributs"], "race", "races") or [""])[0],
                    "faction": (_premier(a["attributs"], "faction", "factions") or [""])[0],
                    "grade": a["grade"], "surnom": a["surnom"], "roblox": a["roblox_nom"], "affiche_id": a["id"]})
    return out


def _emoji_jeu(type_: str, cle: str) -> str:
    """L'émoji d'application de l'icône officielle (`rell_<clé>` ou `rell_<type>_<clé>`), s'il est installé."""
    import visuels
    for nom in (f"rell_{type_}_{cle}", f"rell_{cle}"):
        e = visuels.icone(nom.replace("-", "_")[:32])
        if e is not None and getattr(e, "id", None):
            return str(e)
    return ""


def brancher_evenements(module) -> None:
    """Le module des événements du clan, s'il est là : il lit les fiches et le catalogue des affiches (annonce des
    métiers, listing) et les images du site (`brancher`) ; ses adresses rejoignent le site et ses images utilisées
    ne partent jamais au nettoyage (`tableau.monter` lit son `medias_utilises`) ; ses événements passés ont leur
    règle de nettoyage (« Événements passés », 60 jours, réglable) — par son `purger(jours)`, sinon ses `PURGES`."""
    if callable(getattr(module, "brancher", None)):
        module.brancher(fiches=fiches_clan, catalogue=catalogue_clan, media=tableau.lire_media)
    tableau.monter(module)
    if "evenements_passes" in tableau.REGLES:
        return
    if callable(getattr(module, "purger", None)):
        async def purger(_gid, jours, _t):
            return await module.purger(jours)
    elif getattr(module, "PURGES", None):
        purger = tableau.purges_en_regle(module.PURGES)
    else:
        return
    tableau.ajouter_regle(cle="evenements_passes", nom="Événements passés",
                          quoi="Annonces et événements du clan terminés, annulés ou retirés : effacés après ce délai "
                               "(les brouillons et les annonces publiées restent).",
                          garde_jours=max(14, min(365, int(getattr(module, "GARDE_JOURS", 60) or 60))), min=14, max=365,
                          ordre=50, fn=purger)


async def catalogue_clan(g=None) -> dict:
    """Pour les annonces du clan (`evenements.brancher(catalogue=…)`) : `{type : {clé : {nom, nom_en, icone,
    icone_emoji, actif}}}` — les noms FR · EN et l'icône officielle de chaque élément du jeu."""
    _t, elements = await _catalogue()
    out: dict = {t: {} for t in _t}
    for (type_, cle), e in sorted(elements.items(), key=lambda x: (x[1]["ordre"], x[1]["nom"].casefold())):
        out.setdefault(type_, {})[cle] = {"nom": e["nom"], "nom_en": e["nom_en"], "icone": e["icone"],
                                         "icone_emoji": _emoji_jeu(type_, cle), "actif": bool(e["actif"])}
    return out


async def _nettoyer_corbeille(gid, jours, t):
    borne = int(t - jours * 86400)
    async with _get_db() as db:
        async with db.execute("SELECT id FROM rell_affiches WHERE guild_id=? AND retire_le>0 AND retire_le<?",
                              (gid, borne)) as cur:
            ids = [r[0] for r in await cur.fetchall()]
        for ident in ids:
            await db.execute("DELETE FROM rell_affiches_historique WHERE guild_id=? AND affiche_id=?", (gid, ident))
            await db.execute("DELETE FROM rell_affiches WHERE guild_id=? AND id=?", (gid, ident))
        await db.commit()
    return len(ids)


async def _compter_corbeille(gid, jours, t):
    async with _get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM rell_affiches WHERE guild_id=? AND retire_le>0", (gid,)) as cur:
            return int((await cur.fetchone())[0])


async def _nettoyer_historique(gid, jours, t):
    async with _get_db() as db:
        cur = await db.execute("DELETE FROM rell_affiches_historique WHERE guild_id=? AND quand<?",
                               (gid, int(t - jours * 86400)))
        n = cur.rowcount or 0
        await db.commit()
    return max(n, 0)


async def _compter_historique(gid, jours, t):
    async with _get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM rell_affiches_historique WHERE guild_id=?", (gid,)) as cur:
            return int((await cur.fetchone())[0])


REGLES_NETTOYAGE = [
    {"cle": "affiches_corbeille", "nom": "Affiches en corbeille",
     "quoi": "Une affiche retirée reste restaurable pendant ce délai, puis elle est effacée pour de bon.",
     "garde_jours": 30, "min": 7, "max": 90, "ordre": 60, "fn": _nettoyer_corbeille, "compter": _compter_corbeille},
    {"cle": "affiches_historique", "nom": "Historique des affiches",
     "quoi": "Qui a changé quoi sur chaque affiche : effacé après ce délai.",
     "garde_jours": 180, "min": 30, "max": 365, "ordre": 61, "fn": _nettoyer_historique, "compter": _compter_historique},
]

ROUTES_SITE = {
    "rell/catalogue": {"methode": "GET", "fn": _route_catalogue},
    "rell/catalogue/element": {"methode": "POST", "fn": _route_element, "ecriture": True, "hors_ligne": True},
    "rell/catalogue/retirer": {"methode": "POST", "fn": _route_retirer_element, "ecriture": True, "hors_ligne": True},
    "rell/catalogue/type": {"methode": "POST", "fn": _route_type, "ecriture": True, "hors_ligne": True},
    "rell/affiches": {"methode": "GET", "fn": _route_affiches},
    "rell/affiche": [{"methode": "GET", "fn": _route_affiche_lire},
                     {"methode": "POST", "fn": _route_affiche, "ecriture": True, "hors_ligne": True}],
    "rell/affiche/retirer": {"methode": "POST", "fn": _route_affiche_retirer, "ecriture": True, "hors_ligne": True},
    "rell/affiche/restaurer": {"methode": "POST", "fn": _route_affiche_restaurer, "ecriture": True, "hors_ligne": True},
    "rell/avatar": {"methode": "POST", "fn": _route_avatar, "ecriture": True},
    "rell/roles": {"methode": "GET", "fn": _route_roles},
    "rell/role": {"methode": "POST", "fn": _route_role, "ecriture": True, "grave": "roles"},
    "rell/roles/appliquer": {"methode": "POST", "fn": _route_appliquer, "ecriture": True, "grave": "roles"},
}
