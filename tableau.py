"""tableau.py — le site du staff, servi par le bot (19/10/2026).

« Pas des .txt : un vrai site interactif, ultra bien fait » ; « plus de logs sur Discord, tout
sur le site, traduit par personne » ; « des zones par personne… qu'on évite de scroller
indéfiniment » ; « direction et fondateur : mis à part, pas pris pour les stats » ; « renforce
l'infrastructure du site, qu'il soit impeccable : quelqu'un qui n'a pas les accès ne l'a pas du
tout ».

L'ACCÈS
  · Les deux comptes « à la tête » (TETE_IDS : le fondateur et la direction), par identifiant, et
    personne d'autre — 24/10/2026 : le propriétaire d'un autre serveur où se trouve le bot y entrait.
  · Le bouton du salon « 📋logs » donne un lien PERSONNEL, signé, valable 24 h et À USAGE UNIQUE.
    Ouvert une fois, il devient une session (cookie HttpOnly, Secure, SameSite) et disparaît de la
    barre d'adresse : copié, photographié ou retrouvé dans l'historique, il ne sert plus à rien.
  · Chaque requête revérifie : session valide (relue en base au moins chaque minute : fermée
    ailleurs, elle est coupée), personne toujours sur le serveur et à la tête, pas suspendue.
    « Fermer toutes mes sessions » (pied de page) déconnecte tous ses navigateurs d'un coup.
  · Agir : les mêmes, revérifiés à chaque action. Trop d'actions graves en peu de temps — le signe
    d'un compte volé — est signalé au fondateur dans « 📋logs » (la tête n'est jamais suspendue ;
    tout autre compte le serait une heure).
  · 26/10/2026, le site de l'équipage : une session a une PORTÉE. « tout » : le fondateur et la direction ;
    « equipage » : un membre du rôle du clan, qui ne voit QUE `/tableau/equipage/` (lecture seule). `_verifier`
    refuse une portée qu'on ne lui demande pas : toute adresse, présente ou future, est fermée à l'équipage par
    défaut. Le rôle du clan est revérifié à chaque requête ; perdu, la session est fermée.
  · Défenses : CSP à nonce (aucun script injecté ne s'exécute), en-têtes stricts, origine vérifiée
    sur les écritures (déconnexion comprise), cadence limitée par session et par adresse (faux liens
    et faux cookies : un cookie mal formé ne touche jamais la base), rien en cache, rien d'indexé.

LES DONNÉES
  Lues en direct dans la base du bot. Chaque réponse porte une empreinte (ETag) : la page qui se
  rafraîchit ne retélécharge rien quand rien n'a changé ; la version de la page fait recharger
  celle qui est périmée.

LE SITE V2, « LA CAPITAINERIE » (25/10/2026)
  · La page vient du dossier `site/` (index.html, scripts et styles SANS rien en ligne) ; `{{V}}` y
    devient l'empreinte du dossier : un fichier changé = de nouvelles adresses, jamais un vieux
    script gardé en cache. Sans `site/index.html`, l'ancienne page reste servie.
  · Les fichiers de `site/` (`/tableau/espace/s/…`) : extensions choisies, jamais un pas hors du dossier.
    26/10/2026 (sécurité) : chacun à ses SEULS lecteurs (`ACCES_STATIQUES`) — le code et le style de la
    Capitainerie à la tête, ceux du site de l'équipage à ses sessions, seule l'image (polices, icônes,
    textures…) à tous. Le service worker (`/tableau/espace/sw.js`, tête seule) garde la coquille pour
    travailler hors ligne.
  · 26/10/2026 (sécurité) : chaque écriture du site est tracée à la porte (`securite_site`), les sessions
    gardent leur appareil et leur adresse approximative ; la rubrique « Sécurité » les montre. Aucune
    alerte sur ce que fait la tête ; une alerte regroupée seulement pour un signal fort.
  · Les modules branchent leurs adresses (`monter`) sous `/tableau/espace/api/…` : session, tête,
    origine pour toute écriture, taille du corps, cadence, limites graves, journal du site ; une
    erreur reste ici (« indisponible » côté page, le détail au journal du bot).
  · Hors ligne, la page garde ses modifications et les rejoue (`/tableau/espace/sync`) : chaque
    opération a son identifiant, appliquée une seule fois même renvoyée dix fois.
  · Les images envoyées sont refaites (Pillow) : jamais le fichier reçu tel quel.
  · Le nettoyage : des règles bornées, réglables sur le site, appliquées chaque jour, bilan au journal.
  · La présence en direct (26/10/2026, `/tableau/espace/direct`) : qui est à bord, sur quelle page, ce qu'il modifie ;
    un objet en cours de modification est verrouillé pour les autres, et le serveur refuse leurs écritures (423).
"""
from __future__ import annotations

import asyncio
import base64
import csv
import fnmatch
import hashlib
import hmac
import inspect
import io
import json
import os
import re
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # sans base de fuseaux : l'heure UTC
    PARIS = timezone.utc

import discord

import annonces
import casier
import clan
import diag
import entraide
import owner_ids
import paths
import questions
import questionnaire
import recrutements
import registre
import rellseas_panneau
import securite_site
import sondages
import suggestions
import transcript_store
import vigilance

DUREE = 24 * 3600
#  25/10/2026 : la barre finale compte. La page est à `/tableau/espace/` : ses adresses relatives
#  (`s/app.js`, `api/…`) restent dans l'espace, et le service worker (portée `/tableau/espace/`) la
#  contrôle — sans la barre, ni l'un ni l'autre. `/tableau/espace` y renvoie.
ESPACE = "/tableau/espace/"
#  26/10/2026 : le site de l'équipage (une page à part). Les portées d'une session : « tout » (fondateur, direction) et
#  « equipage » (le rôle du clan, lecture seule) — une autre, ou une vieille, est refusée partout.
EQUIPAGE = "/tableau/equipage/"
PORTEES = ("tout", "equipage")
OUVERTURE_JOURNAL_S = 1800     # « Site de l'équipage ouvert par … » : une ligne par personne et par demi-heure
TENTATIVE_JOURNAL_S = 600      # une session de l'équipage qui demande une page de la direction : une ligne / 10 min
COOKIE = "__Host-tableau"
LIMITE_REQUETES = 240          # par minute et par session
LIMITE_ESSAIS = 30             # liens ou cookies invalides par adresse et par 10 minutes
RELIRE = 60                    # s : une session gardée en mémoire est relue en base au-delà
FORMAT_SESSION = re.compile(r"[A-Za-z0-9_-]{43}")  # ce que donne secrets.token_urlsafe(32)
LIMITES_GRAVES = {"exclusion": 5, "roles": 25, "casier": 10, "rappels": 50}  # par 10 minutes et par personne
BLOCAGE = 3600
#  L'ancienne page (avant `site/`) : facultative — retirée un jour, l'import ne casse pas pour autant.
try:
    PAGE_BRUTE = (Path(__file__).resolve().parent / "tableau_page.html").read_text(encoding="utf-8")
except OSError:
    PAGE_BRUTE = ""
VERSION = hashlib.sha256(PAGE_BRUTE.encode()).hexdigest()[:12]
PAGE = PAGE_BRUTE.replace("__VERSION__", VERSION)


def _message(titre: str, texte: str) -> str:
    return ("<!doctype html><html lang='fr'><meta charset='utf-8'><meta name='viewport' "
            "content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            f"<title>{titre}</title><body style='margin:0;min-height:100vh;display:grid;place-items:center;"
            "background:#05070d;color:#e8eef8;font-family:system-ui,Segoe UI,sans-serif;text-align:center;"
            f"padding:24px'><div><h1 style='font-size:22px'>{titre}</h1><p style='color:#a7b4c8;max-width:460px'>"
            f"{texte}</p></div></body></html>")


EXPIRE = _message("Ce lien n'est plus valable",
                  "Demande un nouveau lien dans Discord : salon <b>📋logs</b> → <b>Ouvrir le tableau de bord</b>.")
DEJA = _message("Ce lien a déjà servi",
                "Chaque lien ne s'ouvre qu'une fois. Demande-en un nouveau dans Discord : salon <b>📋logs</b> → "
                "<b>Ouvrir le tableau de bord</b>.")
TROP = _message("Trop d'essais", "Réessaie dans quelques minutes.")
EXPIRE_EQUIPAGE = _message("Ce lien n'est plus valable",
                           "Demande un nouveau lien dans Discord : forum du clan → <b>Guide du clan</b> → "
                           "<b>Le site de l'équipage</b>.")
DEJA_EQUIPAGE = _message("Ce lien a déjà servi",
                         "Chaque lien ne s'ouvre qu'une fois. Demande-en un nouveau dans Discord : forum du clan → "
                         "<b>Guide du clan</b> → <b>Le site de l'équipage</b>.")
RESERVE = _message("Réservé à la direction",
                   "Cette page est celle du fondateur et de la direction. Ton espace : "
                   "<a href='/tableau/equipage/' style='color:#e8c98a'>le site de l'équipage</a>.")
ENTETES = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    #  24/10/2026 (revue) : `*.discordapp.net` couvre media.discordapp.net ET le relais images-ext-* — les images
    #  d'encadré des tickets passent désormais par lui (l'IP du lecteur ne part plus chez l'hébergeur d'origine).
    "Content-Security-Policy": ("default-src 'none'; img-src 'self' https://cdn.discordapp.com "
                                "https://*.discordapp.net data:; media-src 'self' https://cdn.discordapp.com "
                                "https://*.discordapp.net; style-src 'unsafe-inline'; "
                                "script-src 'none'; connect-src 'self'; base-uri 'none'; "
                                "form-action 'none'; frame-ancestors 'none'"),
}
#  La page v2 : rien en ligne (ni script, ni style, ni attribut style=) — tout vient de `site/`.
CSP_SITE = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
            "img-src 'self' data: blob: https://cdn.discordapp.com https://*.discordapp.net; "
            "media-src 'self' https://cdn.discordapp.com https://*.discordapp.net; connect-src 'self'; "
            "worker-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
#  Un fichier de `site/` ouvert seul (un SVG surtout) : aucun script, rien de chargé d'ailleurs.
CSP_STATIQUE = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:"
#  Le service worker a SA politique (celle de la page ne le suit pas) : ses requêtes restent chez nous
#  et chez Discord (avatars), comme celles de la page.
CSP_SW = "default-src 'none'; script-src 'self'; connect-src 'self' https://cdn.discordapp.com https://*.discordapp.net"
CSP_MEDIA = "default-src 'none'; sandbox"
SITE = Path(__file__).resolve().parent / "site"
TYPES_STATIQUES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8", "woff2": "font/woff2",
                   "webp": "image/webp", "png": "image/png", "svg": "image/svg+xml",
                   "json": "application/json; charset=utf-8",
                   "webmanifest": "application/manifest+json; charset=utf-8", "ico": "image/x-icon"}
COMPRESSIBLES = {"js", "css", "svg", "json", "webmanifest"}
#  26/10/2026 (sécurité) : « le fameux F12 qui leur permet de voir le code source entier du site ». Un navigateur voit
#  toujours ce qu'il reçoit : la vraie protection est que PERSONNE d'autre que la tête ne reçoive le code. Chaque fichier
#  de `site/` a ses lecteurs (motifs `fnmatch`, chemin relatif à `site/`) :
#    · "public" : ce qui n'est que de l'image (polices, icônes, textures, ornements, logos, l'icône de l'application et
#      son manifeste, que le navigateur lit SANS cookie) — sans session ;
#    · une portée de session ("equipage", demain "candidat"…) : les fichiers que SA page charge ;
#    · tout le reste — le code et le style de la Capitainerie, et tout fichier inconnu ou ajouté demain sans y penser :
#      la tête seule (portée « tout »). Un fichier refusé répond 404, comme un fichier absent.
#  La vitrine publique et la page du candidat AJOUTENT ici leurs fichiers (et rien d'autre ne devient lisible).
ACCES_STATIQUES = {
    "public": ("polices/*", "icones/*", "textures/*", "ornements/*", "logos/*", "app-192.png", "app-512.png",
               "manifest.webmanifest"),
    #  Le site de l'équipage (site/equipage.html) : ses modules (import statiques ; `direct.js` n'est chargé qu'en mode
    #  édition, par la tête) et ses feuilles de style.
    "equipage": ("equipage.js", "equipage_accueil.js", "equipage_commun.js", "dom.js", "noyau.js", "api.js", "ui.js",
                 "affiche.js", "donnees.js", "hors_ligne.js", "style.css", "composants.css", "pieces.css", "ateliers.css",
                 "direct.css", "equipage.css"),
}
STATIQUE_MAX = 6 * 1024 * 1024          # un fichier de `site/` (au-delà : refusé, jamais tout en mémoire)
STATIQUES_CACHE = 48 * 1024 * 1024      # ce que la mémoire garde des fichiers de `site/`
SEGMENT_STATIQUE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
ENTETES_STATIQUES = {
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000",
    "Content-Security-Policy": CSP_STATIQUE,
}
#  Le registre des adresses du site (`monter`).
FORMAT_ROUTE = re.compile(r"[a-z0-9_]{1,40}(?:/[a-z0-9_]{1,40}){0,4}")
CORPS_DEFAUT = 64 * 1024
CORPS_PLAFOND = 12 * 1024 * 1024
LIMITE_ECRITURES = 120     # écritures du site (adresses + synchronisation) par minute et par personne
LIMITE_MEDIAS = 1500       # images servies par minute et par session (une galerie entière, pas plus)
LIMITE_STATIQUES = 3000    # fichiers de `site/` servis avec la session, par minute (des pages rechargées en rafale)
PARAMETRES_MAX = 20
#  La synchronisation hors ligne.
SYNC_OPS_MAX = 50
SYNC_CORPS_MAX = 4 * 1024 * 1024
FORMAT_OP = re.compile(r"[A-Za-z0-9_-]{8,64}")
OP_GARDEE_MAX = 256 * 1024             # le résultat gardé d'une opération (au-delà : son seul statut)
OPS_RECENTES = 600                     # s : les résultats tout frais restent aussi en mémoire
#  Les images envoyées depuis le site.
MEDIA_MAX = 8 * 1024 * 1024            # octets décodés
MEDIA_COTE = 2048
MEDIA_PIXELS = 24_000_000              # au-delà, l'image demanderait trop de mémoire à décoder
MEDIAS_DOSSIER_MAX = 512 * 1024 * 1024
MEDIAS_LIBRE_MIN = 300 * 1024 * 1024   # place libre minimale du volume pour accepter une image
FORMAT_MEDIA = re.compile(r"[A-Za-z0-9_-]{16}")
FORMAT_AVATAR = re.compile(r"avatar/([0-9]{1,20})")
MAGIQUES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"),
            (b"GIF89a", "image/gif"))
#  Le nettoyage du site.
NETTOYAGE_INTERVALLE = 23 * 3600       # la boucle horaire n'applique les règles qu'une fois par jour
NETTOYAGE_MANUEL = 300                 # « Lancer maintenant » : une fois toutes les 5 minutes au plus
NETTOYAGE_BILANS = 30                  # passages gardés par serveur (la rubrique en montre les 10 derniers)

_cle = b""
_base = ""
_bot = None
_radie = "🚫 Radié"
_cfg = _get_db = _mesurer_groupe = _autorise_membre = _direction = _alerte_securite = _mis_a_part = None
_tete: frozenset = frozenset()
_alertes_tete: dict = {}
_actions: dict = {}
_cadence: dict = {}
_sessions: dict = {}
_requetes: dict = {}
_requetes_medias: dict = {}
_requetes_statiques: dict = {}   # 26/10/2026 : les fichiers de `site/` lus avec la session (leur propre cadence)
_essais: dict = {}
_graves: dict = {}
_blocages: dict = {}
_ops_en_cours: dict = {}     # op_id → Future : la même opération renvoyée pendant qu'elle s'applique
_ops_recentes: dict = {}     # op_id → (heure, utilisateur, statut, corps)
_nettoyages: dict = {}       # serveur → heure du dernier « Lancer maintenant »
_medias_vus: dict = {}       # image → dernière heure notée en base (une écriture par heure au plus)
_statiques: dict = {}        # chemin → (taille, date, octets, etag) — les fichiers de `site/` en mémoire
_page_site: dict = {}        # index.html et sw.js lus une fois par version du fichier
_cache_empreinte: dict = {"signature": None, "v": "", "vu": 0.0}
#  Ce que les modules branchent (pas de l'état de session : `setup` ne les efface pas).
ROUTES: dict = {}            # nom → {méthode : définition normalisée} (modules)
_INTERNES: dict = {}         # nom → {méthode : définition normalisée} (ce fichier : médias, nettoyage)
REGLES: dict = {}            # clé → règle de nettoyage
_SOURCES_MEDIAS: list = []   # async (guild_id) → set des images utilisées
RACINE_DONNEES: Path | None = None   # tests : le dossier des images ; sinon `base_data_dir()/site`
_verrous: dict = {}          # nom → (boucle, verrou) : un verrou né dans une autre boucle y lèverait une erreur
#  Le site de l'équipage (26/10/2026) : ses lectures (`monter_equipage`) et les images qu'il peut voir.
ROUTES_EQUIPAGE: dict = {}   # nom → async (g, membre, session, requete) → (statut, corps) — GET seulement
MEDIAS_EQUIPAGE = None       # async (g) → l'ensemble des images (`media/…`) permises à une session « equipage »
_ouvertures: dict = {}       # (serveur, membre) → heure de la dernière ligne « site de l'équipage ouvert »
_tentatives: dict = {}       # empreinte de session → heure de la dernière ligne « page de la direction refusée »

#  Le casier mélange les sanctions décidées (staff ou escalade) et les détections du bot.
SANCTIONS = {"warn": "Avertissement", "mute": "Mute", "kick": "Expulsion", "ban": "Bannissement"}
DETECTIONS = {"insulte": "Insulte", "menace": "Menace", "discrimination": "Discrimination",
              "haine": "Haine", "incitation": "Incitation", "harcelement": "Harcèlement",
              "grooming": "Protection des mineurs", "protection": "Filtre automatique"}
GROUPES = {"warn": "Avertissements", "mute": "Mutes", "kick": "Expulsions et bans",
           "ban": "Expulsions et bans"}
MEMBRES_CASIER = 250   # cartes « par membre » envoyées à la page (les plus récents)
LISTE_PAR_MEMBRE = 12  # entrées par carte ; la fiche complète vient de /membre
EXPORT_MAX = 20000
PURGES = [("sessions du site", "DELETE FROM tableau_sessions WHERE expire_le < ?", 1, "unix"),
          ("liens du site", "DELETE FROM tableau_jetons WHERE expire_le < ?", 1, "unix"),
          ("suspensions du site", "DELETE FROM tableau_blocages WHERE jusqu < ?", 1, "unix")]
_cache: dict = {}
_log = print


def setup(*, bot, cle: str, base_url, cfg, get_db, mesurer_groupe, autorise_membre, radie=None,
          direction=None, mis_a_part=None, tete=(), actions=None, alerte_securite=None, conversation=None,
          log=None):
    """`autorise_membre(g, membre, c)` → qui entre sur le site ; `direction(g, membre, c)` → qui agit ;
    `mis_a_part(g, membre, c)` → hors statistiques et intouchable (par défaut : `direction`) ; `tete` :
    les identifiants « à la tête » (« c'est ceux-là et uniquement eux »), jamais suspendus ;
    `actions` : {nom: async (g, auteur, données) → (ok, message)} ; `alerte_securite(g, membre,
    texte, suspendu=True)` : prévient dans « 📋logs » ; `conversation(g, ticket)` → toute la conversation
    d'un ticket (ouvert : en direct ; fermé : le transcript enregistré)."""
    global _bot, _cle, _base, _cfg, _get_db, _mesurer_groupe, _autorise_membre, _log, _radie
    global _direction, _actions, _alerte_securite, _mis_a_part, _tete, _conversation
    _conversation = conversation
    _direction, _actions = direction, dict(actions or {})
    _mis_a_part, _tete = mis_a_part or direction, frozenset(int(x) for x in tete)
    _bot, _cle, _base = bot, cle.encode(), (base_url or "").rstrip("/")
    _radie = radie or _radie
    _cfg, _get_db, _mesurer_groupe, _autorise_membre = cfg, get_db, mesurer_groupe, autorise_membre
    _alerte_securite = alerte_securite
    _log = log or print
    securite_site.setup(get_db=get_db, log=_log)   # 26/10/2026 : la trace des écritures, les sessions et leurs appareils
    for d in (_sessions, _requetes, _requetes_medias, _requetes_statiques, _essais, _graves, _blocages, _cadence, _cache,
              _ops_recentes, _nettoyages, _medias_vus, _alertes_tete, _ouvertures, _tentatives, _direct_salles,
              _direct_ecrits):
        d.clear()


async def init_db():
    async with _get_db() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_sessions (empreinte TEXT PRIMARY KEY, guild_id INTEGER,"
                         " user_id INTEGER, cree_le INTEGER, expire_le INTEGER)")
        #  26/10/2026 : la portée de chaque session (« tout » : la tête ; « equipage » : le site de l'équipage). Les
        #  sessions d'avant sont toutes celles de la tête : « tout ».
        async with db.execute("PRAGMA table_info(tableau_sessions)") as cur:
            colonnes = [r[1] for r in await cur.fetchall()]
        if "portee" not in colonnes:
            await db.execute("ALTER TABLE tableau_sessions ADD COLUMN portee TEXT NOT NULL DEFAULT 'tout'")
        #  26/10/2026 (sécurité) : l'appareil, l'adresse approximative et la dernière activité de chaque session (rubrique
        #  « Sécurité » du site).
        for col, sql in (("appareil", "TEXT NOT NULL DEFAULT ''"), ("adresse", "TEXT NOT NULL DEFAULT ''"),
                         ("vu_le", "INTEGER NOT NULL DEFAULT 0")):
            if col not in colonnes:
                await db.execute(f"ALTER TABLE tableau_sessions ADD COLUMN {col} {sql}")
        await securite_site.creer_tables(db)
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_jetons (nonce TEXT PRIMARY KEY, expire_le INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_blocages (guild_id INTEGER, user_id INTEGER, jusqu INTEGER,"
                         " raison TEXT, PRIMARY KEY (guild_id, user_id))")
        #  25/10/2026 (site v2) : les opérations rejouées au retour du réseau, les images, le nettoyage.
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_ops (op_id TEXT PRIMARY KEY, guild_id INTEGER NOT NULL,"
                         " user_id INTEGER NOT NULL, api TEXT NOT NULL, status INTEGER NOT NULL, corps TEXT NOT NULL,"
                         " quand INTEGER NOT NULL)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tableau_ops_quand ON tableau_ops(guild_id, quand)")
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_medias (id TEXT PRIMARY KEY, guild_id INTEGER NOT NULL,"
                         " auteur_id INTEGER NOT NULL, nom TEXT NOT NULL DEFAULT '', type TEXT NOT NULL,"
                         " octets INTEGER NOT NULL, largeur INTEGER NOT NULL, hauteur INTEGER NOT NULL,"
                         " cree_le INTEGER NOT NULL, vu_le INTEGER NOT NULL DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_nettoyage (guild_id INTEGER NOT NULL, cle TEXT NOT NULL,"
                         " jours INTEGER NOT NULL, maj_le INTEGER NOT NULL DEFAULT 0, maj_par INTEGER NOT NULL DEFAULT 0,"
                         " PRIMARY KEY (guild_id, cle))")
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_nettoyage_etat (guild_id INTEGER PRIMARY KEY,"
                         " dernier INTEGER NOT NULL DEFAULT 0, bilan TEXT NOT NULL DEFAULT '{}',"
                         " par INTEGER NOT NULL DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS tableau_nettoyage_bilans (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                         " guild_id INTEGER NOT NULL, quand INTEGER NOT NULL, total INTEGER NOT NULL,"
                         " detail TEXT NOT NULL DEFAULT '', par INTEGER NOT NULL DEFAULT 0)")
        for uid in _tete:
            await db.execute("DELETE FROM tableau_blocages WHERE user_id=?", (uid,))
        await db.commit()


def a_la_tete(g, user_id: int) -> bool:
    """Le fondateur et la direction, par identifiant — eux seuls. 24/10/2026 : le propriétaire du
    serveur en faisait aussi partie ; celui d'un autre serveur où se trouve le bot n'est pas à la
    tête. `g` reste dans la signature pour les appelants."""
    return int(user_id) in _tete


def autorise_equipage(g, membre, c) -> bool:
    """Le site de l'équipage (26/10/2026) : le RÔLE DU CLAN (réglages Rell Seas, `rellseas_panneau.CLE_ROLE_CIBLE`),
    et rien d'autre — jamais un bot. Lu à chaque requête (en mémoire : un rôle retiré coupe tout de suite)."""
    if g is None or membre is None or getattr(membre, "bot", False):
        return False
    rid = int((c or {}).get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0)
    return rid > 0 and any(int(getattr(r, "id", 0) or 0) == rid for r in (getattr(membre, "roles", None) or []))


# ─── Le lien personnel, à usage unique ──────────────────────────────────────

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jeton(guild_id: int, user_id: int, portee: str, maintenant: float | None = None, nonce: str | None = None) -> str:
    n = nonce or _b64(secrets.token_bytes(9))
    charge = f"{int(guild_id)}.{int(user_id)}.{portee}.{int((maintenant or time.time()) + DUREE)}.{n}"
    sig = hmac.new(_cle, charge.encode(), hashlib.sha256).digest()[:18]
    return f"{_b64(charge.encode())}.{_b64(sig)}"


def lire_jeton(j: str, maintenant: float | None = None) -> dict | None:
    try:
        a, b = str(j).split(".", 1)
        charge, sig = _unb64(a), _unb64(b)
        g, u, p, e, n = charge.decode().split(".")
        g, u, e = int(g), int(u), int(e)
    except (ValueError, UnicodeDecodeError):
        return None
    if not _cle or not hmac.compare_digest(sig, hmac.new(_cle, charge, hashlib.sha256).digest()[:18]):
        return None
    #  26/10/2026 : une portée inconnue (dont l'ancienne « rs », jamais donnée) est refusée.
    if e < (maintenant or time.time()) or p not in PORTEES or not n:
        return None
    return {"g": g, "u": u, "p": p, "e": e, "n": n}


async def suspendu(guild_id: int, user_id: int, maintenant: float | None = None) -> int:
    """L'heure de fin de suspension, ou 0. Jamais pour ceux qui sont à la tête."""
    t = maintenant or time.time()
    if a_la_tete(None, user_id):
        return 0
    jusqu = _blocages.get((guild_id, user_id))
    if jusqu is None and _get_db is not None:
        async with _get_db() as db:
            async with db.execute("SELECT jusqu FROM tableau_blocages WHERE guild_id=? AND user_id=?",
                                  (guild_id, user_id)) as cur:
                r = await cur.fetchone()
        jusqu = int(r[0]) if r else 0
        _blocages[(guild_id, user_id)] = jusqu
    return jusqu if jusqu and jusqu > t else 0


async def lien_pour(i, membre_id: int = 0) -> tuple[str | None, str]:
    """(lien personnel, "") — ou (None, la raison du refus, dite telle quelle à la personne).
    `membre_id` : le lien ouvre directement la fiche de ce membre."""
    if not _base or not _cle or i.guild is None:
        return None, "Le tableau de bord n'est pas joignable pour le moment."
    if _autorise_membre is None or not _autorise_membre(i.guild, i.user, await _cfg(i.guild.id)):
        return None, "Réservé au fondateur et à la direction."
    fin = await suspendu(i.guild.id, i.user.id)
    if fin:
        return None, (f"Ton accès au site est suspendu jusqu'à {_quand(fin)[-5:]} : trop d'actions graves "
                      "en peu de temps. Le fondateur est prévenu.")
    ancre = f"#membre={int(membre_id)}" if membre_id else ""
    return f"{_base}/tableau/{jeton(i.guild.id, i.user.id, 'tout')}{ancre}", ""


# ─── Les sessions ───────────────────────────────────────────────────────────

def _empreinte(sid: str) -> str:
    return hashlib.sha256(sid.encode()).hexdigest()


async def _ouvrir_session(guild_id: int, user_id: int, expire: int, maintenant: float | None = None,
                         portee: str = "tout", appareil: str = "", adresse: str = "") -> str:
    if portee not in PORTEES:
        raise ValueError("portée de session inconnue")
    sid = secrets.token_urlsafe(32)
    emp = _empreinte(sid)
    t = int(maintenant or time.time())
    async with _get_db() as db:
        await db.execute("INSERT INTO tableau_sessions (empreinte, guild_id, user_id, cree_le, expire_le, portee, appareil,"
                         " adresse, vu_le) VALUES (?,?,?,?,?,?,?,?,?)",
                         (emp, guild_id, user_id, t, int(expire), portee, appareil[:80], adresse[:60], t))
        if appareil:   # 26/10/2026 : « nouvel appareil » se lit dans la rubrique Sécurité (jamais alerté)
            await securite_site.noter_appareil(db, guild_id, user_id, appareil, adresse, t)
        await db.commit()
    _sessions[emp] = (guild_id, user_id, int(expire), float(maintenant or time.time()), portee)
    return sid


async def _session(request, maintenant: float | None = None, portees=("tout",)):
    """(empreinte, (serveur, membre, fin)) d'une session de l'une des `portees` (None : n'importe laquelle) — ou None.
    26/10/2026 : par défaut « tout » seulement — une session du site de l'équipage n'est jamais rendue à qui ne la
    demande pas (une adresse écrite demain sans y penser lui reste fermée)."""
    ses = await _lire_session(request, maintenant)
    if ses is None or (portees is not None and ses[2] not in portees):
        return None
    return ses[0], ses[1]


async def _lire_session(request, maintenant: float | None = None):
    """(empreinte, (serveur, membre, fin), portée) — ou None.

    24/10/2026 : n'importe quel cookie occupait une connexion de la base, sans limite par adresse,
    et une session effacée de la base restait ouverte jusqu'au redémarrage (cache en mémoire). Un
    cookie mal formé ne touche plus la base ; un cookie inconnu compte comme un faux lien (même
    limite par adresse, et au-delà plus aucune lecture) ; une session en mémoire est relue en base
    au-delà de RELIRE secondes (sa portée avec elle)."""
    t = maintenant or time.time()
    sid = request.cookies.get(COOKIE, "") if hasattr(request, "cookies") else ""
    if not sid:
        return None
    if not FORMAT_SESSION.fullmatch(sid):
        _trop_essais(request, compter=True, maintenant=t)
        securite_site.compter("cookie")
        return None
    emp = _empreinte(sid)
    s = _sessions.get(emp)
    #  Une session gardée en mémoire SANS sa portée (écrite par un code d'avant la colonne) est relue en base : la portée
    #  vient toujours de la base, jamais devinée.
    if s is None or t - s[3] > RELIRE or len(s) < 5:
        if s is None and _trop_essais(request, maintenant=t):
            return None
        async with _get_db() as db:
            async with db.execute("SELECT guild_id, user_id, expire_le, portee, appareil FROM tableau_sessions"
                                  " WHERE empreinte=?", (emp,)) as cur:
                r = await cur.fetchone()
            if r is not None:
                await _noter_vue(db, request, emp, r, t)
        if r is None:
            if s is None:
                _trop_essais(request, compter=True, maintenant=t)
                securite_site.compter("cookie")
            _sessions.pop(emp, None)
            return None
        s = _sessions[emp] = (int(r[0]), int(r[1]), int(r[2]), t, str(r[3] or ""))
    if s[2] < t:
        return None
    return emp, s[:3], (s[4] if len(s) > 4 else "")  # une portée absente : refusée partout


def _appareil(request) -> str:
    return securite_site.appareil(request.headers.get("User-Agent", "") if hasattr(request, "headers") else "")


async def _noter_vue(db, request, emp: str, r, t: float) -> None:
    """26/10/2026 (rubrique Sécurité) : la dernière activité d'une session, à la minute près (sa ligne n'est relue qu'une
    fois par minute) ; une session ouverte sans appareil connu (l'entrée de démonstration) prend celui de la requête."""
    try:
        if str(r[4] or ""):
            await db.execute("UPDATE tableau_sessions SET vu_le=? WHERE empreinte=?", (int(t), emp))
        else:
            app, adr = _appareil(request), securite_site.adresse_approx(_ip(request))
            await db.execute("UPDATE tableau_sessions SET vu_le=?, appareil=?, adresse=? WHERE empreinte=?",
                             (int(t), app, adr, emp))
            await securite_site.noter_appareil(db, int(r[0]), int(r[1]), app, adr, t)
        await db.commit()
    except Exception as ex:  # la date de dernière activité manque ; la session, elle, tient
        _log("[TABLEAU][E23] dernière activité d'une session non notée")
        _log(f"[TABLEAU][E23:DETAIL] {type(ex).__name__} {ex}")


async def fermer_sessions(guild_id: int | None, user_id: int) -> int:
    """Ferme les sessions d'une personne sur ce serveur — sur tous si `guild_id` est None —, en base
    ET en mémoire : coupées à la requête suivante. Rend leur nombre."""
    async with _get_db() as db:
        if guild_id is None:
            cur = await db.execute("DELETE FROM tableau_sessions WHERE user_id=?", (int(user_id),))
        else:
            cur = await db.execute("DELETE FROM tableau_sessions WHERE guild_id=? AND user_id=?",
                                   (int(guild_id), int(user_id)))
        n = max(cur.rowcount or 0, 0)
        await db.commit()
    for emp in [e for e, s in _sessions.items()
                if s[1] == int(user_id) and (guild_id is None or s[0] == int(guild_id))]:
        _sessions.pop(emp, None)
    return n


async def suspendre(g, membre, raison: str, maintenant: float | None = None) -> None:
    """Le signe d'un compte volé : plus d'accès au site pendant une heure, et on prévient."""
    t = int(maintenant or time.time())
    async with _get_db() as db:
        await db.execute("INSERT OR REPLACE INTO tableau_blocages (guild_id, user_id, jusqu, raison) VALUES (?,?,?,?)",
                         (g.id, membre.id, t + BLOCAGE, raison[:200]))
        await db.commit()
    _blocages[(g.id, membre.id)] = t + BLOCAGE
    await fermer_sessions(g.id, membre.id)
    await registre.noter(g.id, "Sécurité", "site.suspendu", f"Accès au site suspendu une heure : {membre.display_name}"
                         f" — {raison}", membre_id=membre.id, gravite=2)
    if _alerte_securite is not None:
        try:
            await _alerte_securite(g, membre, raison)
        except Exception as ex:  # l'alerte ne doit pas empêcher la suspension
            _log("[TABLEAU][E6] alerte de sécurité impossible")
            _log(f"[TABLEAU][E6:DETAIL] {type(ex).__name__} {ex}")


class _Refus(Exception):
    def __init__(self, status: int, message: str, portee: str = ""):
        super().__init__(message)
        self.status, self.message = status, message
        self.portee = portee  # refus de portée : celle de la session refusée (la page de la direction le dit)


def _ip(request) -> str:
    """Le client : la PREMIÈRE adresse de X-Forwarded-For. Vérifié le 20/10/2026 : le proxy de Railway
    retire l'en-tête envoyé par le client, et la DERNIÈRE adresse est celle du CDN — partagée par
    beaucoup de visiteurs (la prendre aurait mis tout le monde dans un seul compteur d'essais)."""
    fwd = request.headers.get("X-Forwarded-For", "") if hasattr(request, "headers") else ""
    return (fwd.split(",")[0].strip() or getattr(request, "remote", "") or "?")[:64]


def _trop_essais(request, compter: bool = False, maintenant: float | None = None) -> bool:
    t = maintenant or time.time()
    ip = _ip(request)
    recents = [x for x in _essais.get(ip, []) if t - x < 600]
    if compter:
        recents.append(t)
    if recents:
        _essais[ip] = recents
    else:
        _essais.pop(ip, None)
    if len(_essais) > 5000:  # les plus anciennes d'abord — tout vider remettait l'attaquant à zéro
        for k in sorted(_essais, key=lambda k: _essais[k][-1])[:1000]:
            _essais.pop(k, None)
    return len(recents) > LIMITE_ESSAIS


async def _verifier(request, maintenant: float | None = None, medias: bool = False, portees=("tout",),
                    statiques: bool = False):
    """Session valide et de l'une des `portees` (par défaut « tout » seulement : une session du site de l'équipage est
    refusée PARTOUT où on ne la demande pas), personne toujours autorisée — « tout » : le fondateur ou la direction ;
    « equipage » : le rôle du clan, sinon sa session est fermée —, pas suspendue, cadence raisonnable.
    `medias` : une image de la page (sa propre cadence : une galerie ne vide pas celle des données) ; `statiques` : un
    fichier de `site/` (la sienne aussi). 26/10/2026 : la session admise devient celle de la requête en cours
    (`securite_site.SESSION` : la trace des écritures dit de quel appareil elles viennent)."""
    t = maintenant or time.time()
    ses = await _lire_session(request, t)
    if ses is None:
        if _trop_essais(request, maintenant=t):
            raise _Refus(429, "Trop d'essais.")
        raise _Refus(403, "Session expirée.")
    emp, (gid, uid, expire), portee = ses
    if portee not in portees:
        securite_site.compter("hors_portee")
        await _tentative_hors_portee(request, emp, gid, uid, portee, t)
        raise _Refus(403, "Réservé au fondateur et à la direction.", portee=portee or "?")
    g = _bot.get_guild(gid) if _bot else None
    m = g.get_member(uid) if g else None
    if m is None:
        raise _Refus(403, "Accès retiré.")
    c = await _cfg(g.id)
    if portee == "equipage":
        if not autorise_equipage(g, m, c):
            await _fermer_session_equipage(emp, g, m)
            raise _Refus(403, "Accès retiré.")
    elif _autorise_membre is None or not _autorise_membre(g, m, c):
        raise _Refus(403, "Accès retiré.")
    if await suspendu(gid, uid, t):
        raise _Refus(403, "Accès suspendu.")
    seau, limite = ((_requetes_medias, LIMITE_MEDIAS) if medias else (_requetes_statiques, LIMITE_STATIQUES) if statiques
                    else (_requetes, LIMITE_REQUETES))
    recents = [x for x in seau.get(emp, []) if t - x < 60]
    if len(recents) >= limite:
        securite_site.compter("cadence")
        raise _Refus(429, "Trop de requêtes.")
    seau[emp] = recents + [t]
    securite_site.SESSION.set({"emp": emp, "u": uid, "appareil": _appareil(request)})
    if portee == "tout" and _tete and uid not in _tete:
        #  La porte de la direction a laissé passer quelqu'un hors de la tête (avec `autorise_membre` = la tête, par
        #  identifiant, cela n'arrive jamais). Une lecture : un fait VISIBLE dans la rubrique Sécurité, une ligne par session
        #  et par 10 minutes — jamais une alerte (décision du fondateur : l'alerte est pour une action qui ABOUTIT,
        #  `_action_hors_tete`). Rien n'est bloqué ici.
        await securite_site.lecture_hors_tete(g, m, emp, str(getattr(request, "path", "") or ""), t)
    return {"g": gid, "u": uid, "e": expire, "p": portee, "emp": emp}, g


async def _action_hors_tete(g, auteur, quoi: str) -> None:
    """Le signal fort a. (décision du fondateur) : une action privilégiée du site qui ABOUTIT pour quelqu'un hors de la
    tête — appelé seulement après la réussite (une tentative refusée ou en échec n'alerte jamais). Avec le bot tel qu'il
    est, cela n'arrive jamais : si oui, la porte a un trou. Une alerte regroupée dans « 📋logs » ; rien n'est bloqué."""
    uid = int(getattr(auteur, "id", 0) or 0)
    if _tete and uid not in _tete:
        await securite_site.signal_fort(g, "hors_tete", "Une action du site a abouti hors de la tête",
                                        f"{getattr(auteur, 'display_name', None) or uid} ({uid}) : {str(quoi)[:120]}",
                                        auteur_id=uid)


async def _tentative_hors_portee(request, emp: str, gid: int, uid: int, portee: str, t: float) -> None:
    """Une session de l'équipage demande une page de la direction : refusé, et noté au journal (Sécurité) — une ligne
    par session et par 10 minutes au plus (un membre curieux ne remplit pas le journal)."""
    if portee != "equipage" or t - _tentatives.get(emp, 0) < TENTATIVE_JOURNAL_S:
        return
    _tentatives[emp] = t
    if len(_tentatives) > 5000:
        for k in sorted(_tentatives, key=_tentatives.get)[:1000]:
            _tentatives.pop(k, None)
    g = _bot.get_guild(gid) if _bot else None
    m = g.get_member(uid) if g else None
    await registre.noter(gid, "Sécurité", "site.hors_portee",
                         f"Site de l'équipage : {getattr(m, 'display_name', None) or 'un membre'} a demandé une page de "
                         "la direction (refusé)", auteur_id=uid, detail=str(getattr(request, "path", "") or "")[:120],
                         gravite=1)


async def _fermer_session_equipage(emp: str, g, m) -> None:
    """Le rôle du clan est perdu : la session est fermée (en base et en mémoire) — y revenir demandera un lien neuf."""
    async with _get_db() as db:
        await db.execute("DELETE FROM tableau_sessions WHERE empreinte=?", (emp,))
        await db.commit()
    _sessions.pop(emp, None)
    await registre.noter(g.id, "Accès", "site.equipage_ferme",
                         f"Site de l'équipage fermé à {m.display_name} : il n'a plus le rôle du clan", auteur_id=m.id)


# ─── Les personnes ──────────────────────────────────────────────────────────

def _ident(g, uid, defaut="") -> dict:
    m = g.get_member(int(uid)) if uid else None
    return {"id": str(uid or ""), "nom": m.display_name if m else (defaut or "Membre parti"),
            "pseudo": m.name if m else "",
            "avatar": str(m.display_avatar.with_size(64).url) if m else ""}


def _nom(g, uid) -> str:
    if not uid:
        return ""
    m = g.get_member(int(uid))
    return m.display_name if m else "Membre parti"


class _Personnes(dict):
    """Une fiche (nom, avatar) par personne citée, envoyée une seule fois ; les listes ne portent
    que l'identifiant."""

    def __init__(self, g):
        super().__init__()
        self.g = g

    def __call__(self, uid, defaut="") -> str:
        if not uid:
            return ""
        k = str(int(uid))
        if k not in self:
            self[k] = _ident(self.g, int(uid), defaut)
        return k


def a_part(g, c) -> set:
    """« Direction et fondateur : mis à part, pas pris pour les stats. »"""
    out = {m.id for m in getattr(g, "members", []) or [] if _mis_a_part is not None and _mis_a_part(g, m, c)}
    return out | ({g.owner_id} if getattr(g, "owner_id", 0) else set())


def _quand(t) -> str:
    return datetime.fromtimestamp(int(t), PARIS).strftime("%d/%m/%Y %H:%M") if t else ""


def _instant(valeur) -> int | None:
    """Une date de la base en horodatage : « 2026-10-19 14:05:00 » (SQLite, UTC) comme l'ISO complet que `/mod direction`
    écrit dans `restricted_members` (« 2026-10-19T14:05:00.123+00:00 ») ; la date bouche-trou d'avant 2021 → None."""
    if not valeur:
        return None
    try:
        d = datetime.fromisoformat(str(valeur).strip())
    except ValueError:
        return recrutements._unix(valeur)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return None if d.year <= 2020 else int(d.timestamp())


# ─── Les données ────────────────────────────────────────────────────────────

async def _clan(g, c, apart: set) -> dict:
    role = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    if role is None:
        return {"role": "", "membres": [], "direction": []}
    tous = [m for m in role.members if not m.bot]
    membres = [m for m in tous if m.id not in apart]
    mesures = await _mesurer_groupe(g.id, membres) if _mesurer_groupe and membres else {}
    avatars = {m.id: str(m.display_avatar.with_size(64).url) for m in tous}
    try:
        rappels = await clan.rappels(g.id, {uid: (mes or {}).get("dernier") for uid, mes in mesures.items()},
                                     {m.id for m in tous})
    except Exception as ex:  # sans les rappels, la liste du clan reste lisible ; le détail part au journal
        _log("[TABLEAU][E8] rappels du clan illisibles")
        _log(f"[TABLEAU][E8:DETAIL] {type(ex).__name__} {ex}")
        rappels = {}
    for r in rappels.values():
        r["par"] = _nom(g, r["par"])
        r["salon"] = getattr(g.get_channel(int(r["salon"] or 0)), "name", "") if r["salon"] else ""
    return {"role": role.name, "role_id": str(role.id),
            "membres": [{"id": str(x["id"]), "nom": x["nom"], "pseudo": x["pseudo"], "avatar": avatars.get(x["id"], ""),
                         "statut": x["statut"], "rang": x["rang"], "jours": x["jours"], "derniere": x["derniere"],
                         "arrivee": x["arrivee"], "rappel": rappels.get(x["id"])}
                        for x in rellseas_panneau.lignes_clan(membres, mesures)],
            "direction": [_ident(g, m.id) for m in tous if m.id in apart], "salons": _salons_du_clan(g, role)}


def _salons_du_clan(g, role) -> list:
    """Où pinger les inactifs : les salons texte que le clan voit et où le bot peut écrire."""
    me, out = getattr(g, "me", None), []
    for s in getattr(g, "text_channels", None) or []:
        if me is not None and s.permissions_for(role).view_channel and s.permissions_for(me).send_messages:
            out.append({"id": str(s.id), "nom": s.name, "cat": s.category.name if s.category else ""})
    return out[:60]


async def recherche(request):
    """« Filtrer tout le serveur ou rechercher une personne en particulier » pour l'ajouter au clan."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    c = await _cfg(g.id)
    role = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    dans = {m.id for m in role.members} if role is not None else set()
    apart = a_part(g, c)
    trouves = clan.chercher(getattr(g, "members", None) or [], request.query.get("q", "")[:64], dans)
    # L'activité n'est suivie QUE pour le clan : hors du clan, un badge dirait « Jamais vu » à tort
    # (20/10/2026) — on ne mesure, et n'affiche, que les membres du clan.
    du_clan = [m for m in trouves if m.id in dans]
    try:
        mesures = await _mesurer_groupe(g.id, du_clan) if _mesurer_groupe and du_clan else {}
    except Exception as ex:  # sans mesure, la recherche reste utile ; le détail part au journal
        _log("[TABLEAU][E7] activité illisible")
        _log(f"[TABLEAU][E7:DETAIL] {type(ex).__name__} {ex}")
        mesures = {}
    lignes = {x["id"]: x for x in rellseas_panneau.lignes_clan(du_clan, mesures)}
    return _json({"role": role.name if role is not None else "", "membres": [
        dict(_ident(g, m.id), clan=m.id in dans, a_part=m.id in apart, statut=lignes.get(m.id, {}).get("statut"),
             rang=lignes.get(m.id, {}).get("rang"),
             arrivee=int(m.joined_at.timestamp()) if getattr(m, "joined_at", None) else None) for m in trouves]})


def _mediane(valeurs) -> int:
    v = sorted(x for x in valeurs if x is not None and x >= 0)
    return int(v[len(v) // 2]) if v else 0


async def _lignes_tickets(g, filtre: str = "", args: tuple = ()) -> list[dict]:
    async with _get_db() as db:
        tickets = await recrutements._lignes(
            db, "SELECT id, user_id, panel_id, claimed_by, status, created_at, channel_id FROM tickets"
                " WHERE guild_id=?" + filtre + " ORDER BY id", (g.id, *args))
        evts = await recrutements._lignes(
            db, "SELECT ticket_id, kind, actor_id, created_unix FROM ticket_log_events"
                " WHERE guild_id=? AND kind IN ('claim', 'close') ORDER BY id", (g.id,))
        audit = await recrutements._lignes(
            db, "SELECT channel_id, action, actor_id, at, detail FROM ticket_audit"
                " WHERE guild_id=? AND action IN ('claim', 'close') ORDER BY id", (g.id,))
        transcripts = dict(await recrutements._lignes(
            db, "SELECT ticket_id, url FROM ticket_transcripts WHERE guild_id=? AND url != ''", (g.id,)))
    prises, fins = {}, {}
    for tid, kind, actor, t in evts:
        (prises if kind == "claim" else fins).setdefault(tid, (int(t or 0), int(actor or 0)))
    prises_salon, fins_salon, motifs = {}, {}, {}
    for salon, action, actor, at, detail in audit:
        (prises_salon if action == "claim" else fins_salon).setdefault(
            salon, (recrutements._unix(at), int(actor or 0)))
        if action == "close" and detail:
            motifs[salon] = str(detail)[:200]
    out = []
    for tid, uid, pid, pris, statut, cree, salon in tickets:
        prise = prises.get(tid) or prises_salon.get(salon)
        fin_t = fins.get(tid) or fins_salon.get(salon)
        out.append({"ticket": tid, "uid": int(uid or 0), "panel": pid, "statut": statut, "salon": salon,
                    "ouvert": recrutements._unix(cree), "prise": prise, "fin": fin_t,
                    "pris_par": int(pris or 0) or (prise[1] if prise else 0), "motif": motifs.get(salon, ""),
                    "transcript": transcripts.get(tid, "")})
    return out


async def _tickets(g, c, apart: set, qui) -> dict:
    """Tous les tickets, triés par type : ouverts, fermés, délais réels, staff, mois."""
    panneaux = c.get("ticket_panels") or {}
    rell = rellseas_panneau.panneaux_tickets(c)
    types, ouverts, staff, staff30, mois, fermes = {}, [], {}, {}, {}, []
    maintenant = time.time()
    debut_mois = maintenant - 365 * 86400
    for x in await _lignes_tickets(g):
        nom = str((panneaux.get(x["panel"]) or {}).get("name") or "Sans type")
        est_rell = str(x["panel"] or "") in rell
        t = types.setdefault(nom, {"nom": nom, "rellseas": est_rell, "total": 0, "ouverts": 0,
                                   "fermes": 0, "sans_prise": 0, "_prise": [], "_fin": []})
        t["rellseas"] = t["rellseas"] or est_rell
        t["total"] += 1
        ouvert, prise, fin_t, pris_par = x["ouvert"], x["prise"], x["fin"], x["pris_par"]
        if pris_par and pris_par not in apart:
            staff.setdefault(pris_par, {"pris": 0, "fermes": 0})["pris"] += 1
            if prise and prise[0] and maintenant - prise[0] <= 30 * 86400:
                staff30.setdefault(pris_par, {"pris": 0, "fermes": 0})["pris"] += 1
        if x["statut"] == "open":
            t["ouverts"] += 1
            ouverts.append(dict(_ident(g, x["uid"]), ticket=x["ticket"], type=nom, rellseas=est_rell, ouvert=ouvert,
                                pris_par=_nom(g, pris_par),
                                salon=f"https://discord.com/channels/{g.id}/{x['salon']}" if x["salon"] else ""))
        else:
            t["fermes"] += 1
            if not pris_par:
                t["sans_prise"] += 1
            if fin_t and fin_t[1] and fin_t[1] not in apart:
                staff.setdefault(fin_t[1], {"pris": 0, "fermes": 0})["fermes"] += 1
                if fin_t[0] and maintenant - fin_t[0] <= 30 * 86400:
                    staff30.setdefault(fin_t[1], {"pris": 0, "fermes": 0})["fermes"] += 1
            if ouvert and fin_t and fin_t[0]:
                t["_fin"].append(fin_t[0] - ouvert)
            fermes.append((fin_t[0] if fin_t and fin_t[0] else (ouvert or 0), x, nom, est_rell))
        if ouvert and prise and prise[0]:
            t["_prise"].append(prise[0] - ouvert)
        if ouvert and ouvert >= debut_mois:
            cle_m = recrutements.cle_mois(datetime.fromtimestamp(ouvert, timezone.utc))
            groupe = "Rell Seas" if est_rell else "Tickets normaux"
            mois.setdefault(cle_m, {"Rell Seas": 0, "Tickets normaux": 0})[groupe] += 1
    for t in types.values():
        t["prise_mediane"] = _mediane(t.pop("_prise"))
        t["fermeture_mediane"] = _mediane(t.pop("_fin"))
    fermes.sort(key=lambda f: f[0], reverse=True)
    return {
        "types": sorted(types.values(), key=lambda t: (not t["rellseas"], -t["total"], t["nom"])),
        "ouverts": sorted(ouverts, key=lambda o: (not o["rellseas"], o["type"], o["ouvert"] or 0)),
        "staff": sorted(({"nom": _nom(g, k), **v} for k, v in staff.items()),
                        key=lambda x: -(x["pris"] + x["fermes"]))[:15],
        "staff30": staff30,
        "mois": dict(sorted(mois.items())[-12:]),
        "fermes": [{"id": qui(x["uid"]), "ticket": x["ticket"], "type": nom, "rellseas": est_rell,
                    "ouvert": x["ouvert"], "ferme": ferme or None,
                    "ferme_par": _nom(g, x["fin"][1] if x["fin"] else 0), "motif": x["motif"],
                    "transcript": x["transcript"]}
                   for ferme, x, nom, est_rell in fermes[:300]],
    }


def _libelle(typ: str) -> str:
    return SANCTIONS.get(typ) or DETECTIONS.get(typ) or (typ or "Autre").capitalize()


def _entree_casier(g, iid, typ, raison, duree, quand, est_auto, mod) -> dict:
    return {"sanction": iid, "type": typ, "libelle": _libelle(typ), "groupe": GROUPES.get(typ, "Détections"),
            "raison": str(raison or "")[:300], "duree": str(duree or ""), "date": quand, "auto": est_auto,
            "par": "Automatique" if est_auto else _nom(g, mod)}


async def _sanctions(g, apart: set, qui) -> dict:
    """Le casier, en chiffres et PAR MEMBRE : « quelqu'un qui a fait plusieurs avertissements, une
    case pour lui avec tous ses avertissements », et ce qui est en cours sur le serveur."""
    robot = getattr(getattr(_bot, "user", None), "id", 0) or 0
    async with _get_db() as db:
        rows = await recrutements._lignes(
            db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                " WHERE guild_id=? ORDER BY id DESC LIMIT 5000", (g.id,))
        restreints = await recrutements._lignes(
            db, "SELECT user_id, restricted_at, duration, reason, restricted_by FROM restricted_members"
                " WHERE guild_id=?", (g.id,))
    maintenant = time.time()
    par_type, mois, staff, staff30, membres = {}, {}, {}, {}, {}
    auto = manuel = recents_30 = 0
    for iid, uid, mod, typ, raison, duree, cree in rows:
        typ = str(typ or "autre").lower()
        quand = recrutements._unix(cree)
        est_auto = not mod or int(mod) == robot
        par_type[typ] = par_type.get(typ, 0) + 1
        auto, manuel = auto + est_auto, manuel + (not est_auto)
        age = maintenant - quand if quand else 10 ** 9
        recents_30 += age <= 30 * 86400
        if age <= 365 * 86400:
            cle_m = recrutements.cle_mois(datetime.fromtimestamp(quand, timezone.utc))
            mois.setdefault(cle_m, {"Avertissements": 0, "Mutes": 0, "Expulsions et bans": 0,
                                    "Détections": 0})[GROUPES.get(typ, "Détections")] += 1
        if not est_auto and int(mod) not in apart:
            st = staff.setdefault(int(mod), {"total": 0, "types": {}, "dernieres": []})
            st["total"] += 1
            st["types"][typ] = st["types"].get(typ, 0) + 1
            if age <= 30 * 86400:
                staff30[int(mod)] = staff30.get(int(mod), 0) + 1
            if len(st["dernieres"]) < 15:
                st["dernieres"].append(dict(_entree_casier(g, iid, typ, raison, duree, quand, est_auto, mod),
                                            id=qui(uid)))
        if not uid or int(uid) in apart:
            continue
        f = membres.setdefault(int(uid), {"id": qui(uid), "total": 0, "n30": 0, "n90": 0, "types": {},
                                          "derniere": 0, "liste": []})
        f["total"] += 1
        f["n30"] += age <= 30 * 86400
        f["n90"] += age <= 90 * 86400
        f["types"][typ] = f["types"].get(typ, 0) + 1
        f["derniere"] = max(f["derniere"], quand or 0)
        if len(f["liste"]) < LISTE_PAR_MEMBRE:
            f["liste"].append(_entree_casier(g, iid, typ, raison, duree, quand, est_auto, mod))
    radie = next((r for r in getattr(g, "roles", []) if r.name == _radie), None)
    mutes = [m for m in getattr(g, "members", []) if getattr(m, "is_timed_out", lambda: False)()]
    return {
        "total": len(rows), "trente_jours": recents_30, "auto": auto, "manuel": manuel,
        "libelles": {k: _libelle(k) for k in par_type},
        "types": sorted(({"type": k, "libelle": _libelle(k), "n": v, "detection": k not in SANCTIONS}
                         for k, v in par_type.items()), key=lambda t: -t["n"]),
        "mois": dict(sorted(mois.items())[-12:]),
        "staff": sorted(({"nom": _nom(g, k), "id": qui(k), **v} for k, v in staff.items()),
                        key=lambda x: -x["total"])[:15],
        "staff30": staff30,
        "membres": sorted(membres.values(), key=lambda f: -f["derniere"])[:MEMBRES_CASIER],
        "actives": {
            "mutes": [dict(_ident(g, m.id), jusqu=int(m.timed_out_until.timestamp()) if m.timed_out_until else None)
                      for m in mutes if m.id not in apart],
            "radies": [_ident(g, m.id) for m in (radie.members if radie else [])],
            "restreints": [dict(_ident(g, uid), depuis=_instant(depuis), raison=str(raison or "")[:200],
                                par=_nom(g, par)) for uid, depuis, _d, raison, par in restreints],
        },
    }


def _evenement(g, r: dict, qui) -> dict:
    lieu = None
    if r["salon_id"]:
        lieu = g.get_channel(int(r["salon_id"])) or g.get_thread(int(r["salon_id"]))
    return {"id": r["id"], "quand": r["quand"], "cat": r["categorie"] or "Autre", "type": r["type"] or "",
            "texte": r["texte"] or "", "detail": r["detail"] or "", "membre": qui(r["membre_id"]),
            "auteur": qui(r["auteur_id"]), "salon": f"#{lieu.name}" if lieu else "",
            "gravite": int(r["gravite"] or 0)}


async def _journal(g, qui, membre_id: int | None = None, limite: int = 400) -> dict:
    """« Il n'y aura plus de logs sur Discord : tout sur le site, traduit par personne. »"""
    out = {"evenements": [_evenement(g, r, qui) for r in await registre.lire(g.id, limite, membre_id)]}
    if membre_id is None:
        #  Le fuseau, pas le décalage du jour : au changement d'heure (25/10/2026), le décalage
        #  d'aujourd'hui appliqué à 30 jours d'historique faisait glisser une heure par jour sur la veille.
        out["par_jour"] = await registre.par_jour(g.id, 30, PARIS)
    return out


def _question(g, q: dict, qui) -> dict:
    salon = g.get_channel(int(q["salon_id"] or 0)) or g.get_thread(int(q["salon_id"] or 0))
    return {"question": q["id"], "id": qui(q["auteur_id"]), "texte": q["texte"], "quand": q["quand"],
            "statut": q["statut"], "libelle": questions.STATUTS.get(q["statut"], q["statut"]),
            "par": _nom(g, q["repondu_par"]), "par_id": str(q["repondu_par"] or ""),
            "par_staff": bool(q["par_staff"]), "repondu_le": q["repondu_le"],
            "salon": f"#{salon.name}" if salon else "#salon", "message": q["message"], "reponse": q["lien"] or ""}


async def _questions(g, qui) -> dict:
    d = await questions.lister(g.id)
    return {"liste": [_question(g, q, qui) for q in d["liste"]],
            "stats": dict(d["stats"], salons=[{"salon": f"#{getattr(g.get_channel(int(s or 0)), 'name', 'salon')}",
                                               "n": n} for s, n in d["stats"]["salons"]])}


async def _alertes(g, qui) -> list:
    out = []
    maintenant = time.time()
    for a in await vigilance.ouvertes(g.id):
        evts = await registre.graves(g.id, a["membre_id"], int(maintenant - vigilance.FENETRE))
        n, points = vigilance.mesure(evts)
        out.append({"id": qui(a["membre_id"]), "ouverte_le": a["ouverte_le"], "maj_le": a["maj_le"],
                    "incidents": n, "points": points,
                    "evenements": [{"quand": e["quand"], "texte": e["texte"], "gravite": e["gravite"]}
                                   for e in evts[-8:]]})
    return out


async def _casier(g, qui) -> dict:
    """Ce que chaque zone du casier effacerait, et les nettoyages des 30 derniers jours (à défaire)."""
    lots = await casier.lots(g.id)
    for x in lots:
        x["par"] = qui(int(x["par"])) if x["par"] else ""
        x["restaure_par"] = qui(int(x["restaure_par"])) if x["restaure_par"] else ""
        #  « Avertissements de 1234… » (`casier.effacer_membre`) : la personne à part, nommée par la page (25/10/2026 :
        #  le site affichait l'identifiant brut).
        cible = re.search(r" de (\d+)$", str(x["quoi"] or ""))
        if cible:
            x["membre"] = qui(int(cible.group(1)))
            x["quoi"] = str(x["quoi"])[:cible.start()]
    return {"lots": lots, "compte": await casier.comptes(g.id, getattr(getattr(_bot, "user", None), "id", 0) or 0)}


async def _suggestions(g, qui) -> dict:
    d = await suggestions.lister(g.id)
    for s in d["liste"]:
        s["auteur"] = qui(int(s["auteur"]))
        if s["decide_par"]:
            s["decide_par"] = qui(int(s["decide_par"]))
        ch = g.get_channel(int(s["salon_id"]))
        s["salon"] = f"#{ch.name}" if ch is not None else "#salon supprimé"
    return d


async def _entraide(g, qui) -> dict:
    """« Nous, on a toutes les informations des salons trade et entraide au propre » : chaque demande,
    ouverte ou close — qui, quoi, qui est venu, qui l'a certifiée, avec qui l'échange s'est fait."""
    liste = []
    for d in await entraide.recentes(g.id, 300):
        z = entraide.ZONES.get(d["zone"])
        liste.append({"id": d["id"], "zone": d["zone"], "type": z.libelle if z else d["zone"], "emoji": z.emoji if z else "",
                      "auteur": qui(d["auteur_id"]), "titre": d["titre"],
                      "champs": [[str(lib), str(v)] for lib, v in d["champs"] if str(v or "").strip()],
                      "statut": d["statut"], "libelle": entraide.STATUTS.get(d["statut"], (d["statut"], ""))[0],
                      "aidants": [qui(x) for x in d["aidants"]], "credites": [qui(x) for x in d["credites"]],
                      "certifie_par": qui(d["certifie_par"]), "partenaire": qui(d["partenaire_id"]),
                      "ferme_par": qui(d["ferme_par"]), "cree": d["cree"], "ferme": d["ferme"] or None,
                      "lien": "" if d["supprime"] else entraide.lien(g, d),
                      "transcript": transcript_store.transcript_url(d["jeton"]) if d["jeton"] else ""})
    return {"liste": liste, "stats": {"ouvertes": sum(1 for x in liste if x["statut"] in entraide.OUVERTS),
                                      "total": len(liste), "certifiees": sum(1 for x in liste if x["certifie_par"])}}


async def _annonces(g, qui) -> dict:
    """Les annonces publiées depuis 📋logs et qui a cliqué « ✅ Vu »."""
    liste = []
    for a in await annonces.recentes(g.id, 60):
        ch = g.get_channel(int(a["salon_id"])) or g.get_thread(int(a["salon_id"]))
        vus = await annonces.qui_a_vu(a["id"])
        liste.append({"id": a["id"], "titre": a["titre"], "texte": a["texte"][:1500],
                      "salon": f"#{ch.name}" if ch is not None else "#salon supprimé", "auteur": qui(a["auteur_id"]),
                      "cree": a["cree"], "vues": len(vus), "vus": [qui(m) for m, _q in vus[:40]],
                      "mention": "@everyone" if a["mention"] == "@everyone" else ("le clan" if a["mention"] else ""),
                      "lien": f"https://discord.com/channels/{g.id}/{a['salon_id']}/{a['message_id']}"})
    return {"liste": liste, "stats": {"total": len(liste), "vues": sum(x["vues"] for x in liste)}}


async def _droits_salons(g, c) -> list:
    """« Des vrais trucs bien propres par salon, qu'on comprenne bien » : chaque catégorie, chaque
    salon, ce que @everyone (et le clan) peut y faire. Lecture seule : rien ne se règle d'ici."""
    tous = g.default_role
    clan = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    sortie = []
    for categorie, salons in g.by_category():
        lignes = []
        for s in salons:
            if isinstance(s, discord.CategoryChannel):
                continue
            p = s.permissions_for(tous)
            vocal = isinstance(s, (discord.VoiceChannel, discord.StageChannel))
            pc = s.permissions_for(clan) if clan is not None else None
            if p.view_channel:
                profil = ("ouvert" if p.connect else "vitrine") if vocal else ("ouvert" if p.send_messages else "lecture")
            elif pc is not None and pc.view_channel:
                profil = "clan"
            else:
                profil = "cache"
            lignes.append({"id": str(s.id), "nom": s.name, "vocal": vocal, "profil": profil,
                           "voir": bool(p.view_channel), "ecrire": bool(p.send_messages) and not vocal,
                           "reagir": bool(p.add_reactions) and not vocal, "rejoindre": bool(p.connect) and vocal,
                           "images": bool(p.attach_files) and not vocal})
        if lignes:
            sortie.append({"categorie": categorie.name if categorie is not None else "Sans catégorie", "salons": lignes})
    return sortie


async def _sondages(g, qui) -> dict:
    """« Et qui s'affiche au propre, même sur le panel. »"""
    d = await sondages.lister(g.id)
    for s in d["liste"]:
        s["auteur"] = qui(int(s["auteur"]))
        if s["retire_par"]:
            s["retire_par"] = qui(int(s["retire_par"]))
        ch = g.get_channel(int(s["salon_id"])) or g.get_thread(int(s["salon_id"]))
        s["salon"] = f"#{ch.name}" if ch is not None else "#salon supprimé"
    return d


_ETAPE1 = {"etape": 1, "recrutement": "etape1", "fermeture_prevue": False}
_DECIDEES = frozenset({"accepte", "refuse", "refus_etape1", "ferme"})


async def _etapes_recrutement(g) -> dict:
    """ticket → {etape (1 | 2), recrutement (etape1 · etape2_attente · etape2_reponses · etape2_partiel · …),
    fermeture_prevue} : l'étape tenue par le recrutement en deux étapes (questionnaire.py), s'il est branché. La page
    range ainsi les candidatures en cours : « à décider », « questions envoyées », « à corriger »."""
    if not questionnaire.pret():
        return {}
    try:
        s = await questionnaire.suivi(g)
    except Exception as ex:  # la liste reste lisible : chaque candidature retombe à l'étape 1
        _log("[TABLEAU][E19] étapes du recrutement illisibles")
        _log(f"[TABLEAU][E19:DETAIL] {type(ex).__name__} {ex}")
        return {}
    out = {}
    for o in s.get("ouverts") or []:
        etape = str(o.get("etape") or "etape1")
        b = (o.get("envoi") or {}).get("bilan") or {}
        rec = {"etape2": "etape2_attente",
               "reponses": "etape2_partiel" if b.get("corrigees") else "etape2_reponses"}.get(etape, etape)
        out[int(o["ticket"])] = {"etape": 1 if etape in ("etape1", "refus_etape1") else 2, "recrutement": rec,
                                 "fermeture_prevue": bool(o.get("fermeture_prevue"))}
    return out


def candidatures_en_cours(en_cours: list, etapes: dict) -> list:
    """Chaque candidature en cours avec son étape ; une candidature décidée (son ticket se ferme) n'y est plus."""
    out = []
    for o in en_cours:
        e = etapes.get(int(o["ticket"]), _ETAPE1)
        if e["recrutement"] not in _DECIDEES:   # (« fermeture_prevue » ne vaut que pour une décidée : pas ici)
            out.append(dict(o, etape=e["etape"], recrutement=e["recrutement"]))
    return out


async def donnees(g, portee: str = "tout") -> dict:
    cle = (g.id, portee)
    deja = _cache.get(cle)
    if deja and time.time() - deja[0] < 15:
        return deja[1]
    c = await _cfg(g.id)
    apart = a_part(g, c)
    qui = _Personnes(g)
    parties = {}
    for nom, fn in (("journal", lambda: _journal(g, qui)), ("questions", lambda: _questions(g, qui)),
                    ("alertes", lambda: _alertes(g, qui)), ("sondages", lambda: _sondages(g, qui)),
                    ("casier", lambda: _casier(g, qui)), ("suggestions", lambda: _suggestions(g, qui)),
                    ("entraide", lambda: _entraide(g, qui)),
                    ("annonces", lambda: _annonces(g, qui)), ("salons", lambda: _droits_salons(g, c))):
        try:
            parties[nom] = await fn()
        except Exception as ex:  # une partie illisible n'emporte pas le reste du tableau
            _log("[TABLEAU][E4] partie illisible")
            _log(f"[TABLEAU][E4:DETAIL] {nom} {type(ex).__name__} {ex}")
            parties[nom] = [] if nom == "alertes" else {"erreur": True}
    cand = await recrutements.candidatures(g)
    candidats = [dict(_ident(g, d["candidat_id"], d["nom"]), statut=d["statut"], ticket=d["ticket"],
                      ouvert=d["ouvert"], ferme=d["ferme"], pris_par=_nom(g, d["pris_par"]),
                      ferme_par=_nom(g, d["ferme_par"]), motif=d["raison"], parti=d.get("parti", False),
                      reponses=list(d["reponses"].items()), transcript=d["transcript"] or "",
                      candidatures=d["dates"])
                 for d in cand["fiches"]]
    en_cours = [dict(_ident(g, o["candidat_id"]), statut="en_cours", ticket=o["ticket"],
                     ouvert=o["ouvert"], pris_par=_nom(g, o["pris_par"]),
                     reponses=list(o["reponses"].items()),
                     salon=f"https://discord.com/channels/{g.id}/{o['salon']}" if o["salon"] else "")
                for o in cand["en_cours"]]
    etapes = await _etapes_recrutement(g)
    #  Décidée (acceptée, refusée) : son ticket se ferme dans quelques secondes — elle n'est plus « en cours »
    #  (sinon la liste la rangeait parmi les questions envoyées, et l'aperçu la comptait « à décider »).
    en_cours = candidatures_en_cours(en_cours, etapes)
    tickets = await _tickets(g, c, apart, qui)
    #  Site v2 : les tickets fermés depuis plus de N jours passent aux archives de la liste (règle « Nettoyage »).
    tickets["archives_jours"] = await jours_regle(g.id, "tickets_archives")
    sanctions = await _sanctions(g, apart, qui)
    equipe: dict = {}
    for uid, v in tickets.pop("staff30").items():
        equipe.setdefault(uid, {"tickets": 0, "sanctions": 0, "questions": 0})["tickets"] += v["pris"] + v["fermes"]
    for uid, n in sanctions.pop("staff30").items():
        equipe.setdefault(uid, {"tickets": 0, "sanctions": 0, "questions": 0})["sanctions"] += n
    for q in parties["questions"].get("liste") or []:
        if q["par_staff"] and q["par_id"] and q["repondu_le"] and time.time() - q["repondu_le"] <= 30 * 86400:
            equipe.setdefault(int(q["par_id"]), {"tickets": 0, "sanctions": 0, "questions": 0})["questions"] += 1
    out = {
        "version": version_page(),
        "serveur": {"nom": g.name, "icone": str(g.icon.with_size(128).url) if g.icon else ""},
        "genere": datetime.now(timezone.utc).isoformat(),
        "portee": portee,
        "a_part": sorted(str(x) for x in apart),
        "candidats": candidats,
        "en_cours": en_cours,
        "ecartes": cand["vides"] + cand["doublons"],
        "tickets": tickets,
        "clan": await _clan(g, c, apart),
        "sanctions": sanctions,
        "equipe": sorted(({"id": qui(uid), **v} for uid, v in equipe.items() if uid not in apart),
                         key=lambda x: -(x["tickets"] + x["sanctions"] + x["questions"]))[:12],
        **parties,
        "personnes": qui,
    }
    _cache[cle] = (time.time(), out)
    return out


# ─── La fiche d'un membre : tout ce qui le concerne ─────────────────────────

async def fiche(g, uid: int, auteur) -> dict:
    """« Une case par personne… sur ce qu'il a fait tel jour et quand. » Rôles en lecture seule :
    le site ne donne aucun rôle ; seul le rôle Rell Seas peut y être retiré (direction, fondateur)."""
    c = await _cfg(g.id)
    qui = _Personnes(g)
    qui(uid)
    m = g.get_member(int(uid))
    protege = m is not None and (int(uid) == getattr(g, "owner_id", 0) or bool(_mis_a_part and _mis_a_part(g, m, c)))
    agir = (bool(_direction and auteur is not None and _direction(g, auteur, c))
            and not await suspendu(g.id, getattr(auteur, "id", 0)))
    clan = g.get_role(int(c.get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0))
    infos = {"present": m is not None, "a_part": bool(m is not None and (int(uid) == getattr(g, "owner_id", 0)
                                                                         or (_mis_a_part and _mis_a_part(g, m, c)))),
             "protege": protege, "bot": bool(getattr(m, "bot", False)), "roles": [], "arrivee": None, "cree": None,
             "mute_jusqu": None, "clan": bool(m is not None and clan is not None and clan in m.roles)}
    if m is not None:
        infos["roles"] = [{"nom": r.name, "couleur": f"#{r.colour.value:06x}" if getattr(r, "colour", None)
                           and r.colour.value else ""} for r in sorted(m.roles, key=lambda r: -r.position)
                          if r != getattr(g, "default_role", None)][:20]
        infos["arrivee"] = int(m.joined_at.timestamp()) if getattr(m, "joined_at", None) else None
        infos["cree"] = int(m.created_at.timestamp()) if getattr(m, "created_at", None) else None
        if getattr(m, "timed_out_until", None) and getattr(m, "is_timed_out", lambda: False)():
            infos["mute_jusqu"] = int(m.timed_out_until.timestamp())
    elif getattr(g, "fetch_ban", None) is not None:
        import discord
        try:
            await g.fetch_ban(discord.Object(id=int(uid)))
            infos["banni"] = True
        except discord.NotFound:
            infos["banni"] = False
        except discord.HTTPException as ex:
            _log("[TABLEAU][E6] bannissement illisible")
            _log(f"[TABLEAU][E6:DETAIL] {uid} {type(ex).__name__} {ex}")
    robot = getattr(getattr(_bot, "user", None), "id", 0) or 0
    async with _get_db() as db:
        rows = await recrutements._lignes(
            db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                " WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 500", (g.id, int(uid)))
        par_lui = await recrutements._lignes(
            db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                " WHERE guild_id=? AND mod_id=? ORDER BY id DESC LIMIT 100", (g.id, int(uid)))
        restriction = await recrutements._lignes(
            db, "SELECT restricted_at, duration, reason, restricted_by FROM restricted_members"
                " WHERE guild_id=? AND user_id=?", (g.id, int(uid)))
    #  Restreint par la direction (/direction) : depuis quand, pour combien de minutes (0 : sans fin), pourquoi, par qui.
    infos["restreint"] = ({"depuis": _instant(restriction[0][0]), "duree": int(restriction[0][1] or 0),
                           "raison": str(restriction[0][2] or "")[:300], "par": qui(restriction[0][3]) if restriction[0][3] else ""}
                          if restriction else None)
    sanctions = [_entree_casier(g, iid, str(typ or "autre").lower(), raison, duree, recrutements._unix(cree),
                                not mod or int(mod) == robot, mod)
                 for iid, _u, mod, typ, raison, duree, cree in rows]
    donnees_par_lui = [dict(_entree_casier(g, iid, str(typ or "autre").lower(), raison, duree,
                                           recrutements._unix(cree), False, mod), id=qui(u))
                       for iid, u, mod, typ, raison, duree, cree in par_lui] if int(uid) != robot else []
    panneaux = c.get("ticket_panels") or {}
    tickets = [{"ticket": x["ticket"], "type": str((panneaux.get(x["panel"]) or {}).get("name") or "Sans type"),
                "statut": "ouvert" if x["statut"] == "open" else "fermé", "ouvert": x["ouvert"],
                "ferme": x["fin"][0] if x["fin"] else None, "pris_par": _nom(g, x["pris_par"]),
                "ferme_par": _nom(g, x["fin"][1] if x["fin"] else 0), "motif": x["motif"],
                "transcript": x["transcript"],
                "salon": f"https://discord.com/channels/{g.id}/{x['salon']}" if x["statut"] == "open" and x["salon"] else ""}
               for x in reversed(await _lignes_tickets(g, " AND user_id=?", (int(uid),)))]
    candidatures = [dict(r, reponses=list(r["reponses"].items())[:20])
                    for r in await recrutements.du_candidat(g.id, int(uid))]
    journal = await _journal(g, qui, int(uid), 300)
    qs = [_question(g, q, qui) for q in await questions.du_membre(g.id, int(uid))]
    alerte = next((a for a in await _alertes(g, qui) if a["id"] == str(int(uid))), None)
    ses_sondages, ses_idees = [], []
    for nom, module in (("sondages", sondages), ("idees", suggestions)):
        try:
            liste = (await module.lister(g.id, 30, int(uid)))["liste"]
        except Exception as ex:  # l'une illisible n'emporte pas l'autre ; le détail part au journal
            _log("[TABLEAU][E9] sondages ou idées du membre illisibles")
            _log(f"[TABLEAU][E9:DETAIL] {nom} {type(ex).__name__} {ex}")
            continue
        for x in liste:
            ch = g.get_channel(int(x["salon_id"])) or g.get_thread(int(x["salon_id"]))
            x["salon"] = f"#{ch.name}" if ch is not None else "#salon supprimé"
        (ses_sondages if nom == "sondages" else ses_idees).extend(liste)
    return {"membre": dict(qui[str(int(uid))], **infos), "agir": agir and not protege, "sanctions": sanctions,
            "donnees": donnees_par_lui, "tickets": tickets, "candidatures": candidatures,
            "journal": journal["evenements"], "questions": qs, "sondages": ses_sondages, "idees": ses_idees,
            "alerte": alerte, "personnes": qui}


# ─── L'export : un fichier propre, à garder ou à m'envoyer ──────────────────

def _csv(entetes: list, lignes: list) -> bytes:
    """Point-virgule et BOM : s'ouvre proprement dans Excel en français. Une cellule qui
    commencerait par = + - @ est neutralisée (pas de formule exécutée à l'ouverture)."""
    f = io.StringIO()
    w = csv.writer(f, delimiter=";", lineterminator="\r\n")
    w.writerow(entetes)
    for ligne in lignes:
        cellules = []
        for v in ligne:
            s = "" if v is None else str(v).replace("\r", " ").replace("\n", " ")
            cellules.append("'" + s if s[:1] in ("=", "+", "-", "@", "\t") else s)
        w.writerow(cellules)
    return ("﻿" + f.getvalue()).encode("utf-8")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).casefold()).strip("-")[:40] or "serveur"


async def exporter(g, quoi: str, auteur, jours: int = 30, membre: int = 0, categorie: str = "",
                   format_: str = "csv") -> tuple[bytes, str, str] | None:
    """(contenu, type, nom de fichier) — ou None si l'export n'existe pas ou n'est pas permis."""
    c = await _cfg(g.id)
    jours = max(1, min(int(jours or 30), 365))
    depuis = int(time.time() - jours * 86400)
    qui = _Personnes(g)

    def nom_id(uid) -> str:
        return f"{qui[qui(uid)]['nom']} ({uid})" if uid else ""
    if quoi == "journal":
        rows = await registre.lire(g.id, EXPORT_MAX, membre or None, depuis, categorie or None)
        entetes = ["Date", "Catégorie", "Type", "Gravité", "Membre", "Auteur", "Salon", "Texte", "Détail"]
        lignes = [[_quand(r["quand"]), r["categorie"], r["type"], r["gravite"], nom_id(r["membre_id"]),
                   nom_id(r["auteur_id"]), _evenement(g, r, qui)["salon"], r["texte"], r["detail"]] for r in rows]
        brut = [dict(r, date=_quand(r["quand"])) for r in rows]
    elif quoi == "membre" and membre:
        f = await fiche(g, int(membre), auteur)
        entetes = ["Rubrique", "Date", "Quoi", "Par", "Détail", "Lien"]
        lignes = ([["Sanction", _quand(s["date"]), s["libelle"], s["par"], s["raison"], ""] for s in f["sanctions"]]
                  + [["Ticket", _quand(t["ouvert"]), f"#{t['ticket']} {t['type']} ({t['statut']})", t["ferme_par"],
                      t["motif"], t["transcript"]] for t in f["tickets"]]
                  + [["Journal", _quand(e["quand"]), e["cat"], nom_id(int(e["auteur"])) if e["auteur"] else "",
                      e["texte"] + (f" — {e['detail']}" if e["detail"] else ""), ""] for e in f["journal"]]
                  + [["Question", _quand(q["quand"]), q["libelle"], q["par"], q["texte"], q["message"]]
                     for q in f["questions"]])
        brut = f
    elif quoi == "sanctions":
        async with _get_db() as db:
            rows = await recrutements._lignes(
                db, "SELECT id, user_id, mod_id, type, reason, duration, created_at FROM infractions"
                    " WHERE guild_id=? ORDER BY id DESC LIMIT ?", (g.id, EXPORT_MAX))
        entetes = ["N°", "Date", "Membre", "Type", "Durée", "Par", "Raison"]
        lignes = [[iid, _quand(recrutements._unix(cree)), nom_id(uid), _libelle(str(typ or "").lower()), duree,
                   nom_id(mod), raison] for iid, uid, mod, typ, raison, duree, cree in rows]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    elif quoi == "questions":
        d = await questions.lister(g.id)
        entetes = ["Date", "Membre", "Salon", "Statut", "Répondu par", "Question", "Lien"]
        lignes = [[_quand(q["quand"]), nom_id(q["auteur_id"]), _question(g, q, qui)["salon"],
                   questions.STATUTS.get(q["statut"], q["statut"]), _nom(g, q["repondu_par"]), q["texte"],
                   q["message"]] for q in d["liste"]]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    elif quoi == "erreurs" and _direction and auteur is not None and _direction(g, auteur, c):
        #  Les erreurs de CE serveur. Celles du bot entier (sans serveur : guild_id 0) : le fondateur
        #  seul — 24/10/2026 : elles partaient vers quiconque ouvrait le site (tous serveurs confondus).
        globales = owner_ids.is_super_owner(getattr(auteur, "id", 0))
        async with _get_db() as db:
            rows = await recrutements._lignes(
                db, "SELECT occurred_at, source, error_type, message, traceback FROM error_log"
                    + (" WHERE guild_id IN (?, 0)" if globales else " WHERE guild_id=?")
                    + " ORDER BY id DESC LIMIT 2000", (g.id,))
        entetes = ["Date (UTC)", "Source", "Type", "Message", "Trace"]
        lignes = [[str(a), s, t, str(msg or "")[:1000], str(tb or "")[:4000]] for a, s, t, msg, tb in rows]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    else:
        return None
    nom = f"{quoi}-{_slug(g.name)}-{datetime.now(PARIS):%Y-%m-%d}"
    if format_ == "json":
        return (json.dumps(brut, ensure_ascii=False, indent=1, default=str).encode("utf-8"),
                "application/json", f"{nom}.json")
    return _csv(entetes, lignes), "text/csv", f"{nom}.csv"


# ─── Les routes (servies par health_server) ─────────────────────────────────

#  Un refus de cadence (429) dit QUAND réessayer : les cadences du site comptent sur une minute glissante, la page
#  (et sa file hors ligne) attend ce délai au lieu de marteler le serveur.
REESSAYER_S = 60


def _json(corps, status: int = 200, etag: str | None = None):
    from aiohttp import web
    entetes = dict(ENTETES, **({"ETag": etag} if etag else {}))
    if status == 429:
        entetes["Retry-After"] = str(REESSAYER_S)
    r = web.Response(body=json.dumps(corps, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"),
                     status=status, content_type="application/json", headers=entetes)
    r.enable_compression()
    return r


def _html(texte: str, status: int = 200, nonce: str | None = None):
    from aiohttp import web
    entetes = dict(ENTETES)
    if status == 429:
        entetes["Retry-After"] = str(REESSAYER_S)
    if nonce:
        entetes["Content-Security-Policy"] = ENTETES["Content-Security-Policy"].replace(
            "script-src 'none'", f"script-src 'nonce-{nonce}'")
    r = web.Response(text=texte, status=status, content_type="text/html", headers=entetes)
    r.enable_compression()
    return r


async def entree(request):
    """Le lien du bouton : vérifié, consommé, changé en session DE SA PORTÉE — puis l'adresse propre. 26/10/2026 : un
    lien « equipage » (le rôle du clan exigé) ouvre `/tableau/equipage/` ; un lien « tout » avec `?vers=equipage` (le
    bouton du guide du clan, pour la tête) ouvre la même page, avec le mode édition."""
    from aiohttp import web
    if _trop_essais(request):
        return _html(TROP, 429)
    j = lire_jeton(request.match_info.get("jeton", ""))
    g = _bot.get_guild(j["g"]) if j and _bot else None
    m = g.get_member(j["u"]) if g else None
    equipage = bool(j) and j["p"] == "equipage"
    if m is None:
        permis = False
    else:
        c = await _cfg(g.id)
        permis = autorise_equipage(g, m, c) if equipage else (_autorise_membre is not None and _autorise_membre(g, m, c))
    if not permis or await suspendu(g.id, m.id):
        _trop_essais(request, compter=True)
        securite_site.compter("lien")
        return _html(EXPIRE_EQUIPAGE if equipage else EXPIRE, 403)
    vers = EQUIPAGE if equipage or (getattr(request, "query", None) or {}).get("vers") == "equipage" else ESPACE
    async with _get_db() as db:
        cur = await db.execute("INSERT OR IGNORE INTO tableau_jetons (nonce, expire_le) VALUES (?,?)", (j["n"], j["e"]))
        await db.commit()
        neuf = bool(cur.rowcount)
    if not neuf:
        ses = await _lire_session(request)
        if ses is not None and ses[1][:2] == (j["g"], j["u"]) and ses[2] == j["p"]:
            return web.Response(status=303, headers=dict(ENTETES, Location=vers))
        _trop_essais(request, compter=True)
        securite_site.compter("lien")
        return _html(DEJA_EQUIPAGE if equipage else DEJA, 403)
    sid = await _ouvrir_session(j["g"], j["u"], j["e"], portee=j["p"], appareil=_appareil(request),
                                adresse=securite_site.adresse_approx(_ip(request)))
    r = web.Response(status=303, headers=dict(ENTETES, Location=vers))
    r.set_cookie(COOKIE, sid, max_age=max(60, j["e"] - int(time.time())), path="/", secure=True, httponly=True,
                 samesite="Lax")
    if equipage:
        await _noter_ouverture_equipage(g, m)
    else:
        await registre.noter(g.id, "Accès", "site.ouvert", f"Site ouvert par {m.display_name}", auteur_id=m.id)
    return r


async def _noter_ouverture_equipage(g, m, maintenant: float | None = None) -> None:
    """« Site de l'équipage ouvert par … » : une ligne par personne et par demi-heure (le journal reste lisible)."""
    t = maintenant or time.time()
    cle = (g.id, m.id)
    if t - _ouvertures.get(cle, 0) < OUVERTURE_JOURNAL_S:
        return
    _ouvertures[cle] = t
    if len(_ouvertures) > 5000:
        for k in sorted(_ouvertures, key=_ouvertures.get)[:1000]:
            _ouvertures.pop(k, None)
    await registre.noter(g.id, "Accès", "site.equipage", f"Site de l'équipage ouvert par {m.display_name}",
                         auteur_id=m.id)


async def page(request):
    """La page : celle de `site/` (v2) dès qu'elle existe — sinon l'ancienne, avec son nonce."""
    from aiohttp import web
    try:
        await _verifier(request)
    except _Refus as r:
        if r.portee == "equipage":  # 26/10/2026 : un membre du clan ici — refusé, et on lui montre SON espace
            return _html(RESERVE, 403)
        return _html(EXPIRE if r.status != 429 else TROP, r.status)
    neuve = _lire_page_site("index.html")
    if neuve is None and not PAGE:
        return _html(_message("Site en maintenance", "Réessaie dans quelques minutes."), 503)
    if neuve is not None:
        r = web.Response(text=neuve, content_type="text/html",
                         headers=dict(ENTETES, **{"Content-Security-Policy": CSP_SITE}))
        r.enable_compression()
        return r
    nonce = _b64(secrets.token_bytes(16))
    return _html(PAGE.replace("__NONCE__", nonce), nonce=nonce)


async def vers_espace(request):
    """`/tableau/espace` sans la barre : la page est à `/tableau/espace/` (adresses relatives, service worker)."""
    from aiohttp import web
    return web.Response(status=303, headers=dict(ENTETES, Location=ESPACE))


async def api(request):
    from aiohttp import web
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    c = await _cfg(g.id)
    moi = g.get_member(j["u"])
    droits = {"actions": bool(_direction and _direction(g, moi, c)), "staff": True, "moi": str(j["u"])}
    try:
        d = await donnees(g, j["p"])
    except Exception as ex:  # la page affiche l'erreur ; le détail part au journal
        _log("[TABLEAU][E1] données indisponibles")
        _log(f"[TABLEAU][E1:DETAIL] {type(ex).__name__} {ex}")
        return _json({"erreur": "données indisponibles"}, 500)
    corps = dict(d, expire=j["e"], droits=droits)
    empreinte = dict(corps)
    empreinte.pop("genere", None)
    etag = '"' + hashlib.sha256(json.dumps(empreinte, sort_keys=True, default=str).encode()).hexdigest()[:20] + '"'
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=dict(ENTETES, ETag=etag))
    return _json(corps, etag=etag)


async def membre(request):
    """La fiche d'une personne : sanctions, tickets, candidatures, journal, questions, rôles."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    uid = request.query.get("id", "")
    if not uid.isdigit() or len(uid) > 20:
        return _json({"erreur": "membre invalide"}, 400)
    try:
        return _json(await fiche(g, int(uid), g.get_member(j["u"])))
    except Exception as ex:  # la page le dit ; le détail part au journal du bot
        _log("[TABLEAU][E3] fiche indisponible")
        _log(f"[TABLEAU][E3:DETAIL] {type(ex).__name__} {ex}")
        return _json({"erreur": "fiche indisponible"}, 500)


_conversation = None


async def conversation(request):
    """Toute la conversation d'un ticket (20/10/2026 : « on n'a que le questionnaire »)."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    ticket = request.query.get("ticket", "")
    if not ticket.isdigit() or len(ticket) > 12 or _conversation is None:
        return _json({"erreur": "ticket invalide"}, 400)
    try:
        return _json(await _conversation(g, int(ticket)))
    except Exception as ex:  # la page le dit ; le détail part au journal du bot
        _log("[TABLEAU][E10] conversation indisponible")
        _log(f"[TABLEAU][E10:DETAIL] {ticket} {type(ex).__name__} {ex}")
        return _json({"erreur": "conversation indisponible"}, 500)


async def export(request):
    from aiohttp import web
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    q = request.query
    membre_ = q.get("membre", "")
    jours = q.get("jours", "30")
    if (membre_ and (not membre_.isdigit() or len(membre_) > 20)) or not jours.isdigit() or len(jours) > 3:
        return _json({"erreur": "demande invalide"}, 400)
    try:
        res = await exporter(g, q.get("quoi", ""), g.get_member(j["u"]), int(jours), int(membre_ or 0),
                             q.get("cat", "")[:40], "json" if q.get("format") == "json" else "csv")
    except Exception as ex:
        _log("[TABLEAU][E5] export impossible")
        _log(f"[TABLEAU][E5:DETAIL] {type(ex).__name__} {ex}")
        return _json({"erreur": "export impossible"}, 500)
    if res is None:
        return _json({"erreur": "export inconnu ou réservé"}, 404)
    contenu, type_, nom = res
    r = web.Response(body=contenu, content_type=type_, charset="utf-8",
                     headers=dict(ENTETES, **{"Content-Disposition": f'attachment; filename="{nom}"'}))
    r.enable_compression()
    return r


def _origine_ok(request) -> bool:
    """Une écriture vient de la page elle-même : en-tête maison, même origine, même site. Un refus est compté (rubrique
    Sécurité), jamais alerté."""
    h = request.headers
    origine = h.get("Origin")
    attendue = _base.split("/", 3)[:3] if _base else None
    attendue = "/".join(attendue) if attendue else f"{getattr(request, 'scheme', 'https')}://{getattr(request, 'host', '')}"
    ok = (h.get("X-Tableau") == "1" and h.get("Sec-Fetch-Site", "same-origin") == "same-origin"
          and (origine is None or origine == attendue))
    if not ok:
        securite_site.compter("origine")
    return ok


async def limite_grave(g, auteur, genre: str, n: int = 1, maintenant: float | None = None) -> str | None:
    """Compte `n` actions graves de ce genre. None : elles peuvent se faire. Sinon le refus à montrer
    (accès au site suspendu une heure, le fondateur prévenu) — jamais pour la tête : la rafale est seulement
    notée (rubrique Sécurité), une fois par 10 minutes. Partagé par les actions et les adresses du site (`grave`)."""
    t = maintenant or time.time()
    cle = (g.id, auteur.id, genre)
    faits = [x for x in _graves.get(cle, []) if t - x < 600]
    if len(faits) + n > LIMITES_GRAVES[genre]:
        raison = f"{len(faits) + n} actions graves ({genre}) en moins de 10 minutes"
        if not a_la_tete(g, auteur.id):
            await suspendre(g, auteur, raison)
            return "Trop d'actions graves en peu de temps : accès au site suspendu une heure, le fondateur est prévenu."
        #  « Si tu es suspendu alors que je suis le fondateur, il y a un petit problème » : jamais de
        #  suspension pour la tête. 26/10/2026, décision du fondateur (« faut pas que tu fasses non plus une fausse
        #  alerte ») : plus d'alerte non plus — le fait reste VISIBLE dans la rubrique Sécurité (une ligne du journal par
        #  10 minutes au plus).
        if t - _alertes_tete.get(cle, 0) > 600:
            _alertes_tete[cle] = t
            await registre.noter(g.id, "Sécurité", "site.rafale",
                                 f"{raison} : {getattr(auteur, 'display_name', None) or auteur.id}", auteur_id=auteur.id)
    _graves[cle] = faits + [t] * n
    return None


def _genre_grave(nom: str, corps: dict) -> tuple[str, int] | None:
    if nom == "moderer" and corps.get("sanction") in ("kick", "ban"):
        return "exclusion", 1
    if nom in ("clan_retirer", "clan_ajouter"):
        return "roles", 1
    if nom == "clan_prevenir":
        return "rappels", len(corps.get("membres") or [])
    if nom == "clan_retirer_lot":
        return "roles", len(corps.get("membres") or [])
    if nom in ("casier_effacer", "casier_restaurer"):
        return "casier", 1
    if nom == "casier_serveur":
        return "casier", 5
    if nom == "debannir":
        return "exclusion", 1
    return None


async def action(request):
    """« Seulement le fondateur et le rôle direction » : chaque action est revérifiée ici, inscrite
    au journal, et refusée si elle ne vient pas de la page elle-même. Trop d'actions graves : accès
    suspendu."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"ok": False, "message": r.message}, r.status)
    if not _origine_ok(request):
        return _json({"ok": False, "message": "Requête refusée."}, 400)
    try:
        corps = await request.json() if request.content_length and request.content_length <= 4096 else {}
    except (ValueError, RecursionError):   # 26/10/2026 : un JSON imbriqué 2 000 fois levait RecursionError (500)
        corps = {}
    if not isinstance(corps, dict):
        corps = {}
    nom = str(corps.get("action") or "")
    fn = _actions.get(nom)
    if fn is None:
        return _json({"ok": False, "message": "Action inconnue."}, 400)
    auteur = g.get_member(j["u"])
    if _direction is None or not _direction(g, auteur, await _cfg(g.id)):
        return _json({"ok": False, "message": "Réservé au fondateur et à la direction."}, 403)
    refus = refus_verrou(g.id, await _objets_ecriture(nom, VERROUS_ACTIONS.get(nom), corps), auteur.id)
    if refus is not None:   # présence en direct : le dossier est en cours de modification par quelqu'un d'autre
        return _json({"ok": False, "message": refus["erreur"]}, 423)
    maintenant = time.time()
    recents = [t for t in _cadence.get(auteur.id, []) if maintenant - t < 60]
    if len(recents) >= 20:
        return _json({"ok": False, "message": "Trop d'actions d'un coup, attends une minute."}, 429)
    _cadence[auteur.id] = recents + [maintenant]
    grave = _genre_grave(nom, corps)
    if grave is not None:
        refus = await limite_grave(g, auteur, grave[0], grave[1], maintenant)
        if refus is not None:
            return _json({"ok": False, "message": refus}, 403)
    statut = 200
    try:
        ok, message = await fn(g, auteur, corps)
        statut = 200 if ok else 409
    except Exception as ex:  # l'action échoue : la page le dit, le détail part au journal
        _log("[TABLEAU][E2] action impossible")
        _log(f"[TABLEAU][E2:DETAIL] {nom} {type(ex).__name__} {ex}")
        ok, message, statut = False, "L'action n'a pas pu être faite.", 500
    for cle in [k for k in _cache if k[0] == g.id]:
        _cache.pop(cle, None)
    #  26/10/2026 : la trace de chaque action du site vers Discord, à la porte même (réussie, refusée ou en échec).
    await securite_site.noter_action(g, auteur, f"action/{nom}", statut, str(message))
    if ok:
        await _action_hors_tete(g, auteur, f"action/{nom} — {message}")
    return _json({"ok": bool(ok), "message": str(message)})


async def sortir(request):
    """Se déconnecter : la session de ce navigateur est effacée — avec `?partout=1`, TOUTES les
    sessions de la personne (« Fermer toutes mes sessions » : une session volée est coupée).

    Une écriture comme les autres : elle doit venir de la page elle-même, sinon rien n'est touché,
    pas même le cookie (24/10/2026 : un autre site pouvait déconnecter de force)."""
    from aiohttp import web
    if not _origine_ok(request):
        return _json({"ok": False, "message": "Requête refusée."}, 400)
    ses = await _session(request, portees=None)  # se déconnecter : toute portée (le site de l'équipage aussi)
    if getattr(request, "query", {}).get("partout") == "1":
        if ses is None:
            return _json({"ok": False, "message": "Session expirée."}, 403)
        _emp, (gid, uid, _fin) = ses
        n = await fermer_sessions(None, uid)
        g = _bot.get_guild(gid) if _bot is not None else None
        m = g.get_member(uid) if g is not None else None
        await registre.noter(gid, "Accès", "site.sessions_fermees",
                             f"Toutes les sessions du site fermées par {getattr(m, 'display_name', None) or uid}",
                             auteur_id=uid, detail=f"{n} session(s) fermée(s)")
        r = _json({"ok": True, "message": "Toutes tes sessions sont fermées."})
    else:
        if ses is not None:
            async with _get_db() as db:
                await db.execute("DELETE FROM tableau_sessions WHERE empreinte=?", (ses[0],))
                await db.commit()
            _sessions.pop(ses[0], None)
        r = web.Response(status=204, headers=ENTETES)
    r.del_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="Lax")  # __Host- exige Secure
    return r

# ═══════════════════════════════════════════════════════════════════════════════
#  Site v2 — la page de `site/`, ses fichiers, le service worker
# ═══════════════════════════════════════════════════════════════════════════════

def _fichiers_site() -> list:
    """(chemin relatif, chemin, taille, date) de chaque fichier de `site/`, triés ; sans les cachés."""
    racine, out, pile = SITE, [], [SITE]
    while pile:
        dossier = pile.pop()
        try:
            entrees = list(os.scandir(dossier))
        except OSError:
            continue
        for e in entrees:
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    pile.append(Path(e.path))
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    out.append((Path(e.path).relative_to(racine).as_posix(), Path(e.path), st.st_size, st.st_mtime_ns))
            except OSError:
                continue
    return sorted(out)


def empreinte_site(maintenant: float | None = None) -> str:
    """L'empreinte du dossier `site/` (12 caractères), `{{V}}` de la page : le contenu de chaque fichier.
    Un fichier changé, ajouté ou retiré = une autre empreinte = d'autres adresses (`?v=`), jamais un vieux
    fichier gardé par le navigateur. Recalculée seulement quand un fichier change (taille, date)."""
    t = maintenant or time.time()
    racine = str(SITE)
    deja = _cache_empreinte
    if deja["signature"] is not None and deja.get("racine") == racine and t - deja["vu"] < 2:
        return deja["v"]  # relue au plus toutes les 2 s : la page, les données et le service worker la demandent
    fichiers = _fichiers_site()
    signature = (racine, tuple((r, s, m) for r, _p, s, m in fichiers))
    if signature != _cache_empreinte["signature"]:
        h = hashlib.sha256()
        for rel, p, _s, _m in fichiers:
            h.update(rel.encode("utf-8") + b"\x00")
            try:
                h.update(p.read_bytes())
            except OSError:
                continue
        _cache_empreinte.update(signature=signature, v=h.hexdigest()[:12] if fichiers else "")
    _cache_empreinte.update(vu=t, racine=racine)
    return _cache_empreinte["v"]


def version_page() -> str:
    """La version de la page servie : la page se recharge d'elle-même quand elle change."""
    return empreinte_site() if (SITE / "index.html").is_file() else VERSION


def _lire_page_site(nom: str) -> str | None:
    """`site/index.html` ou `site/sw.js`, `{{V}}` remplacé — None s'il n'existe pas (ou illisible)."""
    p = SITE / nom
    try:
        st = p.stat()
    except OSError:
        return None
    cle = (str(p), st.st_size, st.st_mtime_ns)
    deja = _page_site.get(nom)
    if deja is None or deja[0] != cle:
        try:
            texte = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as ex:
            _log("[TABLEAU][E13] page du site illisible")
            _log(f"[TABLEAU][E13:DETAIL] {nom} {type(ex).__name__} {ex}")
            return None
        _page_site[nom] = deja = (cle, texte)
    return deja[1].replace("{{V}}", empreinte_site())


def _chemin_statique(brut) -> tuple[str, str] | None:
    """(chemin relatif, extension) d'un fichier de `site/` demandé — None au moindre doute : segment
    vide, `.` ou `..`, caché, caractère hors liste, extension non permise."""
    brut = str(brut or "")
    if not brut or len(brut) > 300:
        return None
    segments = brut.split("/")
    if len(segments) > 8 or any(not SEGMENT_STATIQUE.fullmatch(s) or ".." in s for s in segments):
        return None
    nom = segments[-1]
    ext = nom.rsplit(".", 1)[1].lower() if "." in nom else ""
    if ext not in TYPES_STATIQUES:
        return None
    return "/".join(segments), ext


def lecteurs_statique(rel: str):
    """Qui peut lire ce fichier de `site/` : None (public), sinon l'ensemble des portées de session permises — « tout »
    toujours ; un fichier qu'aucune liste ne cite : la tête seule (`ACCES_STATIQUES`)."""
    rel = str(rel or "")
    if any(fnmatch.fnmatchcase(rel, m) for m in ACCES_STATIQUES.get("public", ())):
        return None
    return frozenset({"tout"} | {p for p, motifs in ACCES_STATIQUES.items()
                                 if p != "public" and any(fnmatch.fnmatchcase(rel, m) for m in motifs)})


def _lire_statique(rel: str):
    """(octets, etag) d'un fichier de `site/`, gardés en mémoire tant qu'il ne change pas — ou None.
    Le chemin résolu (liens suivis) doit rester DANS `site/`."""
    try:
        racine = SITE.resolve()
        p = (SITE / rel).resolve()
        if not p.is_relative_to(racine) or not p.is_file():
            return None
        st = p.stat()
    except (OSError, ValueError, RuntimeError):
        return None
    if st.st_size > STATIQUE_MAX:
        return None
    deja = _statiques.get(str(p))
    if deja is not None and deja[0] == st.st_size and deja[1] == st.st_mtime_ns:
        return deja[2], deja[3]
    try:
        data = p.read_bytes()
    except OSError:
        return None
    etag = '"' + hashlib.sha256(data).hexdigest()[:20] + '"'
    _statiques.pop(str(p), None)
    if sum(len(x[2]) for x in _statiques.values()) + len(data) <= STATIQUES_CACHE:
        _statiques[str(p)] = (st.st_size, st.st_mtime_ns, data, etag)
    return data, etag


def _meme_etag(request, etag: str) -> bool:
    vus = request.headers.get("If-None-Match", "") if hasattr(request, "headers") else ""
    return bool(vus) and any(x.strip().removeprefix("W/") == etag for x in vus.split(","))


def _introuvable(cache: str = "no-store"):
    from aiohttp import web
    return web.Response(status=404, text="Introuvable.", headers=dict(ENTETES_STATIQUES, **{"Cache-Control": cache}))


async def statique(request):
    """`/tableau/espace/s/{chemin}` : un fichier de `site/`, jamais hors du dossier, type exact. 26/10/2026 (sécurité) :
    servi à ses SEULS lecteurs (`ACCES_STATIQUES`) — le code et le style de la Capitainerie à la tête, ceux du site de
    l'équipage à ses sessions, l'image à tous ; un refus répond comme un fichier absent (404). Gardé un an par le
    navigateur quand l'adresse porte `?v=` (l'empreinte change avec le fichier), revalidé sinon — « private » dès qu'il
    faut une session : aucun cache partagé (proxy, CDN) ne le garde pour le servir à un autre."""
    from aiohttp import web
    demande = _chemin_statique(request.match_info.get("chemin", ""))
    if demande is None:
        return _introuvable()
    lecteurs = lecteurs_statique(demande[0])
    if lecteurs is not None:
        try:
            await _verifier(request, portees=lecteurs, statiques=True)
        except _Refus as r:
            if r.status == 429:
                return web.Response(status=429, text="Trop de requêtes.",
                                    headers=dict(ENTETES_STATIQUES, **{"Cache-Control": "no-store",
                                                                       "Retry-After": str(REESSAYER_S)}))
            securite_site.compter("fichier")
            return _introuvable()
    lu = _lire_statique(demande[0])
    if lu is None:
        return _introuvable()
    data, etag = lu
    entetes = dict(ENTETES_STATIQUES, ETag=etag, **{
        "Cache-Control": ("public, " if lecteurs is None else "private, ")
        + ("max-age=31536000, immutable" if "v" in request.query else "no-cache")})
    if _meme_etag(request, etag):
        return web.Response(status=304, headers=entetes)
    entetes["Content-Type"] = TYPES_STATIQUES[demande[1]]
    if demande[1] == "js":  # lancé en Web Worker, un script garde la politique du service worker
        entetes["Content-Security-Policy"] = CSP_SW
    r = web.Response(body=data, headers=entetes)
    if demande[1] in COMPRESSIBLES:
        r.enable_compression()
    return r


async def service_worker(request):
    """`/tableau/espace/sw.js` : le service worker (portée `/tableau/espace/`), `{{V}}` remplacé pour qu'il
    se renouvelle avec le site. Toujours revalidé ; sa propre politique de sécurité. 26/10/2026 : le code de la
    Capitainerie, donc à la tête seule (le navigateur le demande avec le cookie ; sans session, sa mise à jour échoue
    et l'ancien reste en place : le hors ligne ne se perd pas)."""
    from aiohttp import web
    try:
        await _verifier(request, statiques=True)
    except _Refus:
        securite_site.compter("fichier")
        return _introuvable()
    texte = _lire_page_site("sw.js")
    if texte is None:
        return _introuvable()
    entetes = dict(ENTETES_STATIQUES, **{"Cache-Control": "private, no-cache", "Content-Type": "text/javascript; charset=utf-8",
                                         "Content-Security-Policy": CSP_SW, "Service-Worker-Allowed": "/tableau/espace/"})
    r = web.Response(body=texte.encode("utf-8"), headers=entetes)
    r.enable_compression()
    return r


# ═══════════════════════════════════════════════════════════════════════════════
#  Site v2 — le registre des adresses (`/tableau/espace/api/…`)
# ═══════════════════════════════════════════════════════════════════════════════

_ABSENT = object()
_REGLES_INTERNES: set = set()


def _normaliser_route(nom, d) -> dict:
    """Une adresse de `ROUTES_SITE`, vérifiée : une erreur ici est une erreur de câblage (au démarrage)."""
    if not isinstance(nom, str) or not FORMAT_ROUTE.fullmatch(nom):
        raise ValueError(f"route du site : nom invalide {nom!r}")
    if not isinstance(d, dict):
        raise ValueError(f"route du site : définition invalide ({nom})")
    methode = str(d.get("methode", "GET")).upper()
    fn = d.get("fn")
    ecriture = d.get("ecriture", methode == "POST")
    hors_ligne = d.get("hors_ligne", False)
    corps_max = d.get("corps_max", CORPS_DEFAUT)
    grave = d.get("grave")
    if methode not in ("GET", "POST") or not callable(fn):
        raise ValueError(f"route du site : méthode ou fonction invalide ({nom})")
    if not isinstance(ecriture, bool) or not isinstance(hors_ligne, bool):
        raise ValueError(f"route du site : « ecriture » et « hors_ligne » sont des booléens ({nom})")
    if methode == "GET" and (ecriture or hors_ligne):
        raise ValueError(f"route du site : une lecture (GET) n'écrit pas et ne se rejoue pas ({nom})")
    if hors_ligne and not ecriture:
        raise ValueError(f"route du site : seule une écriture se rejoue hors ligne ({nom})")
    if isinstance(corps_max, bool) or not isinstance(corps_max, int) or not 0 <= corps_max <= CORPS_PLAFOND:
        raise ValueError(f"route du site : corps_max hors bornes ({nom})")  # 0 : aucun corps (une lecture)
    if grave is not None and grave not in LIMITES_GRAVES:
        raise ValueError(f"route du site : genre grave inconnu ({nom})")
    verrou = d.get("verrou")   # présence en direct : fonction(corps) → objet(s) que l'écriture touche
    if verrou is not None and (not callable(verrou) or not ecriture):
        raise ValueError(f"route du site : « verrou » est la fonction d'une écriture ({nom})")
    return {"nom": nom, "methode": methode, "fn": fn, "ecriture": ecriture, "hors_ligne": hors_ligne,
            "corps_max": corps_max, "grave": grave, "verrou": verrou}


def _normaliser_regle(r) -> dict:
    """Une règle de nettoyage : bornes cohérentes, fonctions appelables."""
    if not isinstance(r, dict) or not isinstance(r.get("cle"), str) or not FORMAT_ROUTE.fullmatch(r["cle"]) \
            or "/" in r["cle"]:
        raise ValueError("règle de nettoyage : clé invalide")
    cle = r["cle"]
    nombres = [r.get(k) for k in ("garde_jours", "min", "max")]
    if any(isinstance(x, bool) or not isinstance(x, int) for x in nombres):
        raise ValueError(f"règle de nettoyage : durées entières attendues ({cle})")
    garde, mini, maxi = nombres
    if not 0 <= mini <= garde <= maxi <= 3650:
        raise ValueError(f"règle de nettoyage : bornes incohérentes ({cle})")
    fn, compter = r.get("fn"), r.get("compter")
    if (fn is not None and not callable(fn)) or (compter is not None and not callable(compter)):
        raise ValueError(f"règle de nettoyage : fonction invalide ({cle})")
    return {"cle": cle, "nom": str(r.get("nom") or cle)[:60], "quoi": str(r.get("quoi") or "")[:300],
            "garde_jours": garde, "min": mini, "max": maxi, "fn": fn, "compter": compter,
            "ordre": int(r.get("ordre") or 0)}


def _definitions(nom, d) -> list:
    """Une adresse = une définition, ou une LISTE (une par méthode : `GET rell/affiche` et `POST rell/affiche`)."""
    liste = [_normaliser_route(nom, x) for x in (d if isinstance(d, list) else [d])]
    if not liste or len({x["methode"] for x in liste}) != len(liste):
        raise ValueError(f"route du site : une définition par méthode ({nom})")
    return liste


def monter(*sources) -> int:
    """Branche les adresses d'un ou plusieurs modules : `monter(affiches, evenements)`, ou une table seule
    (`monter(module.ROUTES_SITE)`). Une adresse peut avoir une définition par méthode (une liste). Un module
    peut aussi donner `REGLES_NETTOYAGE` (rubrique « Nettoyage ») et `medias_utilises(guild_id)` (ses
    images ne partent jamais au nettoyage). Tout est vérifié AVANT d'enregistrer : une erreur (adresse en
    double, définition invalide) n'en branche aucune. Rebrancher les mêmes fonctions ne change rien. Rend
    le nombre de définitions de ces sources."""
    routes, regles, sources_medias = {}, [], []
    for s in sources:
        table = s if isinstance(s, dict) else getattr(s, "ROUTES_SITE", None)
        if not isinstance(table, dict):
            raise ValueError("monter : un module avec ROUTES_SITE, ou une table d'adresses")
        for nom, d in table.items():
            for r in _definitions(nom, d):
                deja = (_INTERNES.get(nom, {}).get(r["methode"]) or ROUTES.get(nom, {}).get(r["methode"])
                        or routes.get(nom, {}).get(r["methode"]))
                if deja is not None and deja["fn"] is not r["fn"]:
                    raise ValueError(f"route du site en double : {r['methode']} {nom}")
                routes.setdefault(nom, {})[r["methode"]] = r
        if not isinstance(s, dict):
            for x in getattr(s, "REGLES_NETTOYAGE", None) or []:
                regle = _normaliser_regle(x)
                if regle["cle"] in _REGLES_INTERNES or any(y["cle"] == regle["cle"] for y in regles):
                    raise ValueError(f"règle de nettoyage en double : {regle['cle']}")
                regles.append(regle)
            f = getattr(s, "medias_utilises", None)
            if callable(f):
                sources_medias.append(f)
    for nom, par_methode in routes.items():
        ROUTES.setdefault(nom, {}).update(par_methode)
    for regle in regles:
        REGLES[regle["cle"]] = regle
    for f in sources_medias:
        if f not in _SOURCES_MEDIAS:
            _SOURCES_MEDIAS.append(f)
    return sum(len(x) for x in routes.values())


def _routes_de(nom) -> dict:
    """{méthode : définition} d'une adresse — vide si elle n'existe pas."""
    if not isinstance(nom, str) or not FORMAT_ROUTE.fullmatch(nom):
        return {}
    return dict(ROUTES.get(nom, {}), **_INTERNES.get(nom, {}))


def _route(nom, methode: str = "POST") -> dict | None:
    return _routes_de(nom).get(methode)


async def _lire_corps(request, maximum: int) -> bytes:
    """Le corps de la requête, jamais plus de `maximum` octets lus (au-delà : 413, avant même de tout lire)."""
    longueur = getattr(request, "content_length", None)
    if longueur is not None and longueur > maximum:
        raise _Refus(413, "Trop volumineux.")
    flux = getattr(request, "content", None)
    if flux is not None and hasattr(flux, "read"):
        morceaux, total = [], 0
        while True:
            bloc = await flux.read(65536)
            if not bloc:
                break
            total += len(bloc)
            if total > maximum:
                raise _Refus(413, "Trop volumineux.")
            morceaux.append(bloc)
        return b"".join(morceaux)
    if hasattr(request, "read"):
        data = await request.read()
    else:  # requêtes simulées des tests : le corps déjà décodé
        data = json.dumps(await request.json()).encode("utf-8") if hasattr(request, "json") else b""
    if len(data) > maximum:
        raise _Refus(413, "Trop volumineux.")
    return data


async def _lire_json(request, maximum: int) -> dict:
    brut = await _lire_corps(request, maximum)
    if not brut.strip():
        return {}
    try:
        corps = json.loads(brut.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise _Refus(400, "Corps illisible.") from None
    if not isinstance(corps, dict):
        raise _Refus(400, "Corps illisible.")
    return corps


def _parametres(request) -> dict:
    """Les paramètres d'adresse, bornés : 20 au plus, nom ≤ 40, valeur ≤ 512 caractères."""
    q = getattr(request, "query", None) or {}
    out = {}
    for k in list(q.keys())[:PARAMETRES_MAX]:
        if isinstance(k, str) and 0 < len(k) <= 40:
            out[k] = str(q.get(k, ""))[:512]
    return out


async def _noter_ecriture(g, auteur, nom: str, journal) -> None:
    """Le journal du site (catégorie « Site ») : la phrase donnée par l'adresse, ou une phrase par défaut."""
    membre_id, detail = 0, ""
    if isinstance(journal, dict):
        texte = str(journal.get("texte") or "")
        membre_id = int(journal.get("membre_id") or 0)
        detail = str(journal.get("detail") or "")
    elif isinstance(journal, str):
        texte = journal
    else:
        texte = f"Site : {nom.replace('/', ' › ')}"
    qui = getattr(auteur, "display_name", None) or str(getattr(auteur, "id", "?"))
    await registre.noter(g.id, "Site", f"site.{nom.replace('/', '.')}"[:40], f"{texte or nom} (par {qui})",
                         auteur_id=getattr(auteur, "id", 0) or 0, membre_id=membre_id, detail=detail)


async def _executer(nom: str, route: dict, g, auteur, requete: dict, corps, maintenant: float | None = None):
    """Une adresse du site appliquée : (statut, corps). Écriture : réservée à la tête (`direction`),
    cadence par personne, limites graves, journal du site et données relues. Une exception reste ici
    (« indisponible » pour la page, le détail au journal du bot). Les clés « _… » de la réponse ne sortent
    jamais (`_journal` : la phrase du journal ; None : rien à noter)."""
    t = maintenant or time.time()
    objets: list = []
    if route["ecriture"]:
        if auteur is None or _direction is None or not _direction(g, auteur, await _cfg(g.id)):
            return 403, {"erreur": "Réservé au fondateur et à la direction."}
        #  26/10/2026 (présence en direct) : un objet en cours de modification par quelqu'un d'autre n'est pas écrit.
        objets = await _objets_ecriture(nom, route.get("verrou") or VERROUS_ROUTES.get(nom), corps)
        refus = refus_verrou(g.id, objets, auteur.id)
        if refus is not None:
            return 423, refus
        cle = ("site", auteur.id)
        recents = [x for x in _cadence.get(cle, []) if t - x < 60]
        if len(recents) >= LIMITE_ECRITURES:
            return 429, {"erreur": "Trop de modifications d'un coup : attends une minute."}
        _cadence[cle] = recents + [t]
        if route["grave"]:
            refus = await limite_grave(g, auteur, route["grave"], 1, t)
            if refus is not None:
                return 403, {"erreur": refus}
    try:
        res = route["fn"](g, auteur, requete, corps)
        if inspect.isawaitable(res):
            res = await res
        status, rep = res
        if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status <= 599 \
                or not isinstance(rep, dict):
            raise TypeError("réponse mal formée")
    except Exception as ex:  # l'adresse échoue : la page lit « indisponible », le détail part au journal
        _log("[TABLEAU][E11] adresse du site en échec")
        _log(f"[TABLEAU][E11:DETAIL] {nom} {type(ex).__name__} {ex}")
        diag.compter("site", f"api.{nom}", ex)
        if route["ecriture"]:   # 26/10/2026 : une écriture en échec reste tracée (Discord a pu être touché à moitié)
            await securite_site.noter_action(g, auteur, nom, 500, "en échec")
        return 500, {"erreur": "Indisponible pour le moment."}
    journal = rep.get("_journal", _ABSENT)
    rep = {k: v for k, v in rep.items() if not str(k).startswith("_")}
    if route["ecriture"]:
        #  26/10/2026 : la trace de chaque écriture du site, à la porte même — réussie ou non (rubrique Sécurité).
        await securite_site.noter_action(g, auteur, nom, status, securite_site.texte_journal(
            journal, str(rep.get("erreur") or rep.get("message") or nom.replace("/", " › "))))
    if route["ecriture"] and status < 400:
        for k in [k for k in _cache if k[0] == g.id]:
            _cache.pop(k, None)
        if journal is not None:
            await _noter_ecriture(g, auteur, nom, None if journal is _ABSENT else journal)
        direct_ecrit(g.id, objets, auteur.id)
        await _action_hors_tete(g, auteur, nom)
    return status, rep


async def api_site(request):
    """`/tableau/espace/api/{nom}` (GET et POST) : les adresses branchées par les modules (`monter`) et
    celles de ce fichier (images, nettoyage). Même porte que le reste : session, tête, origine de la page
    pour toute écriture, taille du corps."""
    from aiohttp import web
    nom = str(request.match_info.get("nom", ""))
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    par_methode = _routes_de(nom)
    if not par_methode:
        return _json({"erreur": "Adresse inconnue."}, 404)
    if nom.startswith("direct/") and j.get("p") != PORTEE_DIRECT:   # le direct : les sessions de portée « tout » seules
        return _json({"erreur": "Réservé au fondateur et à la direction."}, 403)
    methode = "GET" if request.method == "HEAD" else request.method
    route = par_methode.get(methode)
    if route is None:
        r = _json({"erreur": "Méthode refusée."}, 405)
        r.headers["Allow"] = ", ".join(sorted(par_methode))
        return r
    if (route["ecriture"] or methode == "POST") and not _origine_ok(request):
        return _json({"erreur": "Requête refusée."}, 400)
    corps = None
    if methode == "POST":
        try:
            corps = await _lire_json(request, route["corps_max"])
        except _Refus as r:
            return _json({"erreur": r.message}, r.status)
    status, rep = await _executer(nom, route, g, g.get_member(j["u"]), _parametres(request), corps)
    if methode == "GET" and status == 200:
        etag = '"' + hashlib.sha256(json.dumps(rep, sort_keys=True, ensure_ascii=False, default=str)
                                    .encode("utf-8")).hexdigest()[:20] + '"'
        if _meme_etag(request, etag):
            return web.Response(status=304, headers=dict(ENTETES, ETag=etag))
        return _json(rep, 200, etag=etag)
    return _json(rep, status)


api_site_post = api_site  # le même, pour la route POST (aiohttp : un nom par route)


# ═══════════════════════════════════════════════════════════════════════════════
#  Site v2 — hors ligne : les opérations rejouées (`/tableau/espace/sync`)
# ═══════════════════════════════════════════════════════════════════════════════

def _resultat_garde(status: int) -> bool:
    """Un résultat qui ne changera pas si on rejoue (fait, refusé, en conflit) — pas une panne, ni une
    cadence, ni une session tombée, ni un objet en cours de modification ailleurs (423) : ceux-là se retentent."""
    return status < 500 and status not in (401, 403, 423, 429)


async def _op_connue(op_id: str):
    async with _get_db() as db:
        async with db.execute("SELECT user_id, status, corps FROM tableau_ops WHERE op_id=?", (op_id,)) as cur:
            r = await cur.fetchone()
    if r is None:
        return None
    try:
        corps = json.loads(r[2] or "{}")
    except ValueError:
        corps = {}
    return int(r[0]), int(r[1]), corps if isinstance(corps, dict) else {}


async def _garder_op(guild_id: int, uid: int, op_id: str, api: str, status: int, corps: dict, t: float) -> None:
    texte = json.dumps(corps, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(texte) > OP_GARDEE_MAX:
        texte = json.dumps({"ok": status < 400, "trop_long": True})
    async with _get_db() as db:
        await db.execute("INSERT OR IGNORE INTO tableau_ops (op_id, guild_id, user_id, api, status, corps, quand)"
                         " VALUES (?,?,?,?,?,?,?)", (op_id, int(guild_id), int(uid), api[:120], int(status), texte, int(t)))
        await db.commit()


async def _appliquer_op(g, auteur, uid: int, op_id: str, op: dict, maintenant: float | None = None):
    """Une opération : appliquée UNE fois. Déjà faite (même renvoyée dix fois, ou en même temps) : le même
    résultat, rien de refait. Seules les adresses `hors_ligne` se rejouent."""
    t = maintenant or time.time()
    for k in [k for k, v in _ops_recentes.items() if t - v[0] > OPS_RECENTES]:
        _ops_recentes.pop(k, None)
    deja = _ops_recentes.get(op_id)
    if deja is not None:
        return (deja[2], deja[3]) if deja[1] == uid else (409, {"erreur": "Identifiant d'opération déjà utilisé."})
    if op_id in _ops_en_cours:
        status, corps, auteur_op = await asyncio.shield(_ops_en_cours[op_id])
        return (status, corps) if auteur_op == uid else (409, {"erreur": "Identifiant d'opération déjà utilisé."})
    attente = asyncio.get_running_loop().create_future()
    _ops_en_cours[op_id] = attente
    res = (500, {"erreur": "Indisponible pour le moment."})
    try:
        connue = await _op_connue(op_id)
        if connue is not None:
            res = (connue[1], connue[2]) if connue[0] == uid else (409, {"erreur": "Identifiant d'opération déjà utilisé."})
        else:
            api = op.get("api")
            route = _route(api)
            corps = op.get("corps")
            corps = {} if corps is None else corps
            if route is None or not route["hors_ligne"]:
                res = (400, {"erreur": "Cette opération ne se rejoue pas hors ligne."})
            elif not isinstance(corps, dict):
                res = (400, {"erreur": "Opération invalide."})
            elif len(json.dumps(corps, ensure_ascii=False, default=str).encode("utf-8")) > route["corps_max"]:
                res = (413, {"erreur": "Trop volumineux."})
            else:
                res = await _executer(api, route, g, auteur, {}, corps, t)
            if _resultat_garde(res[0]):
                #  D'abord en mémoire : appliquée, l'opération ne doit jamais l'être une seconde fois, même si sa
                #  trace en base échoue (la page renverrait alors la même dans les minutes qui suivent).
                _ops_recentes[op_id] = (t, uid, res[0], res[1])
                try:
                    await _garder_op(g.id, uid, op_id, str(api), res[0], res[1], t)
                except Exception as ex:  # la trace manque en base ; la réponse, elle, reste la vraie
                    _log("[TABLEAU][E18] trace d'une opération hors ligne non gardée")
                    _log(f"[TABLEAU][E18:DETAIL] {type(ex).__name__} {ex}")
                    diag.compter("site", "sync.trace", ex)
    except Exception as ex:  # la base refuse : l'opération reste dans la file de la page, réessayée plus tard
        _log("[TABLEAU][E12] opération hors ligne non appliquée")
        _log(f"[TABLEAU][E12:DETAIL] {type(ex).__name__} {ex}")
        diag.compter("site", "sync", ex)
        res = (500, {"erreur": "Indisponible pour le moment."})
    finally:
        _ops_en_cours.pop(op_id, None)
        if not attente.done():
            attente.set_result((res[0], res[1], uid))
    return res


async def sync(request):
    """`POST /tableau/espace/sync` `{"ops": [{"op_id", "api", "corps"}]}` (50 au plus) : les modifications
    faites hors ligne, dans l'ordre. → `{"resultats": [{"op_id", "status", "corps"}]}`. Après une cadence
    dépassée (429), les suivantes ne sont pas tentées : la page les garde et réessaie, dans le même ordre."""
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    if not _origine_ok(request):
        return _json({"erreur": "Requête refusée."}, 400)
    try:
        corps = await _lire_json(request, SYNC_CORPS_MAX)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    ops = corps.get("ops")
    if not isinstance(ops, list) or len(ops) > SYNC_OPS_MAX:
        return _json({"erreur": f"Demande invalide ({SYNC_OPS_MAX} opérations au plus)."}, 400)
    auteur = g.get_member(j["u"])
    resultats, arret = [], False
    for op in ops:
        op_id = op.get("op_id") if isinstance(op, dict) else None
        if not isinstance(op_id, str) or not FORMAT_OP.fullmatch(op_id):
            resultats.append({"op_id": op_id if isinstance(op_id, str) else "", "status": 400,
                              "corps": {"erreur": "Opération invalide."}})
            continue
        if arret:
            resultats.append({"op_id": op_id, "status": 429, "corps": {"erreur": "Plus tard : trop d'un coup."}})
            continue
        status, rep = await _appliquer_op(g, auteur, j["u"], op_id, op)
        resultats.append({"op_id": op_id, "status": status, "corps": rep})
        arret = status == 429
    return _json({"resultats": resultats})


# ═══════════════════════════════════════════════════════════════════════════════
#  Site v2 — les images envoyées depuis le site (`api/media`, `/tableau/espace/media/…`)
# ═══════════════════════════════════════════════════════════════════════════════

def dossier_site(sous: str) -> Path:
    """`base_data_dir()/site/<sous>` (créé au besoin) : `medias`, `avatars`."""
    racine = RACINE_DONNEES if RACINE_DONNEES is not None else paths.base_data_dir() / "site"
    d = Path(racine) / sous
    d.mkdir(parents=True, exist_ok=True)
    return d


def type_image(data: bytes) -> str | None:
    """Le type réel d'une image, par ses premiers octets (jamais le nom ni le type annoncé)."""
    for magique, typ in MAGIQUES:
        if data.startswith(magique):
            return typ
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def reencoder_image(data: bytes, cote: int = MEDIA_COTE) -> tuple[bytes, int, int, str]:
    """L'image REFAITE : premier cadre, orientation appliquée, toutes les métadonnées retirées (une image
    neuve, pixel par pixel), `cote` px au plus, en WebP (PNG si Pillow n'a pas WebP). → (octets, largeur,
    hauteur, type). ValueError si elle ne se lit pas, ou demanderait trop de mémoire."""
    try:
        from PIL import Image, ImageOps, features
    except ImportError as ex:
        raise ValueError("Pillow absent") from ex
    try:
        #  26/10/2026 : `formats` — seuls ces quatre décodeurs de Pillow sont essayés (aucun format exotique ouvert).
        with Image.open(io.BytesIO(data), formats=("PNG", "JPEG", "WEBP", "GIF")) as im:
            if im.format not in ("PNG", "JPEG", "WEBP", "GIF"):
                raise ValueError("format")
            largeur, hauteur = im.size
            if largeur < 1 or hauteur < 1 or largeur * hauteur > MEDIA_PIXELS:
                raise ValueError("dimensions")
            if im.format == "JPEG":
                im.draft("RGB", (cote, cote))
            im.seek(0)
            cadre = ImageOps.exif_transpose(im)
            alpha = cadre.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in cadre.info
            cadre = cadre.convert("RGBA" if alpha else "RGB")
            cadre.thumbnail((cote, cote), Image.Resampling.LANCZOS)
            neuve = Image.new(cadre.mode, cadre.size)
            neuve.paste(cadre)
            sortie = io.BytesIO()
            if features.check("webp"):
                neuve.save(sortie, "WEBP", quality=88, method=4)
                typ = "image/webp"
            else:
                neuve.save(sortie, "PNG", optimize=True)
                typ = "image/png"
            return sortie.getvalue(), neuve.width, neuve.height, typ
    except ValueError:
        raise
    except Exception as ex:  # fichier tronqué, bombe de décompression, format trompeur…
        raise ValueError("illisible") from ex


def _ecrire_atomique(chemin: Path, data: bytes) -> None:
    tmp = chemin.with_name(f"{chemin.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, chemin)
    finally:
        if tmp.exists():
            tmp.unlink()


def _nom_fichier(nom: str) -> str:
    nom = re.sub(r"[\x00-\x1f\x7f/\\]+", " ", nom)
    return re.sub(r"\s+", " ", nom).strip()[:120]


async def _place_medias(dossier: Path) -> bool:
    """Assez de place : le dossier des images sous sa limite, et le volume pas plein."""
    async with _get_db() as db:
        async with db.execute("SELECT COALESCE(SUM(octets), 0) FROM tableau_medias") as cur:
            occupe = int((await cur.fetchone())[0] or 0)
    if occupe >= MEDIAS_DOSSIER_MAX:
        return False
    try:
        return shutil.disk_usage(dossier).free >= MEDIAS_LIBRE_MIN
    except OSError:
        return True


async def _route_media(g, auteur, requete, corps):
    """`POST api/media` `{"nom", "type", "base64"}` → `{"id", "url", "largeur", "hauteur", "octets", "type"}`.
    PNG, JPEG, WebP ou GIF (reconnus à leurs octets), 8 Mo au plus, refaits en WebP ≤ 2048 px."""
    nom, brut = corps.get("nom", ""), corps.get("base64")
    if nom is None:
        nom = ""
    if not isinstance(nom, str) or len(nom) > 200:
        return 400, {"erreur": "Nom de fichier invalide.", "champ": "nom"}
    if corps.get("type") is not None and not isinstance(corps.get("type"), str):
        return 400, {"erreur": "Type invalide.", "champ": "type"}
    if not isinstance(brut, str) or not brut:
        return 400, {"erreur": "Image absente.", "champ": "base64"}
    if brut.startswith("data:"):
        brut = brut.split(",", 1)[1] if "," in brut else ""
    brut = "".join(brut.split())
    if len(brut) > (MEDIA_MAX + 2) // 3 * 4:
        return 413, {"erreur": "Image trop lourde : 8 Mo au plus."}
    try:
        data = base64.b64decode(brut, validate=True)
    except ValueError:  # binascii.Error en hérite
        return 400, {"erreur": "Image illisible.", "champ": "base64"}
    if not data:
        return 400, {"erreur": "Image absente.", "champ": "base64"}
    if len(data) > MEDIA_MAX:
        return 413, {"erreur": "Image trop lourde : 8 Mo au plus."}
    if type_image(data) is None:
        return 415, {"erreur": "Format refusé : PNG, JPEG, WebP ou GIF seulement."}
    dossier = dossier_site("medias")
    if not await _place_medias(dossier):
        return 507, {"erreur": "Plus de place pour les images : le nettoyage en libère."}
    async with _verrou("media", lambda: asyncio.Semaphore(1)):  # une image refaite à la fois : la mémoire tenue
        try:
            sortie, largeur, hauteur, typ = await asyncio.to_thread(reencoder_image, data)
        except ValueError:
            return 415, {"erreur": "Image illisible, ou trop grande à décoder."}
    ident = secrets.token_urlsafe(12)
    await asyncio.to_thread(_ecrire_atomique, dossier / f"{ident}.{'webp' if typ == 'image/webp' else 'png'}", sortie)
    t = int(time.time())
    nom = _nom_fichier(nom)
    async with _get_db() as db:
        await db.execute("INSERT INTO tableau_medias (id, guild_id, auteur_id, nom, type, octets, largeur, hauteur,"
                         " cree_le, vu_le) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (ident, g.id, auteur.id, nom, typ, len(sortie), largeur, hauteur, t, t))
        await db.commit()
    return 200, {"ok": True, "id": ident, "url": f"media/{ident}", "largeur": largeur, "hauteur": hauteur,
                 "octets": len(sortie), "type": typ, "_journal": f"Image ajoutée au site : {nom or ident}"}


async def lire_media(ident):
    """(octets, extension) d'une image envoyée sur le site, ou None — pour le module des événements (une image
    d'annonce part avec la carte Discord)."""
    chemin, _typ = _chemin_media(str(ident or ""))
    if chemin is None:
        return None
    try:
        return await asyncio.to_thread(chemin.read_bytes), chemin.suffix.lstrip(".")
    except OSError:
        return None


def _chemin_media(ident: str):
    """(chemin, type) d'une image du site : `media/<id>` (envoyée) ou `media/avatar/<id Roblox>`."""
    ident = str(ident or "")
    m = FORMAT_AVATAR.fullmatch(ident)
    if m:
        sous, nom = "avatars", m.group(1)
    elif FORMAT_MEDIA.fullmatch(ident):
        sous, nom = "medias", ident
    else:
        return None, None
    try:
        dossier = dossier_site(sous)
    except OSError:
        return None, None
    for ext, typ in (("webp", "image/webp"), ("png", "image/png")):
        p = dossier / f"{nom}.{ext}"
        if p.is_file():
            return p, typ
    return None, None


async def media(request):
    """`GET /tableau/espace/media/{id}` : une image du site — session exigée, rien gardé en cache."""
    from aiohttp import web
    try:
        j, g = await _verifier(request, medias=True, portees=PORTEES)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    ident = str(request.match_info.get("media", ""))
    #  26/10/2026 : une session du site de l'équipage ne voit QUE les images que ses lectures citent (portraits des
    #  affiches, icônes du catalogue, images de l'accueil) — jamais une autre image envoyée sur le site.
    if j["p"] != "tout" and not await _media_permis_equipage(g, ident):
        return _json({"erreur": "Réservé au fondateur et à la direction."}, 403)
    chemin, typ = _chemin_media(ident)
    if chemin is None:
        return _json({"erreur": "Image introuvable."}, 404)
    try:
        data = await asyncio.to_thread(chemin.read_bytes)
    except OSError:
        return _json({"erreur": "Image introuvable."}, 404)
    t = time.time()
    if FORMAT_MEDIA.fullmatch(ident) and t - _medias_vus.get(ident, 0) > 3600:
        _medias_vus[ident] = t
        try:
            async with _get_db() as db:
                await db.execute("UPDATE tableau_medias SET vu_le=? WHERE id=?", (int(t), ident))
                await db.commit()
        except Exception as ex:  # seulement la date de dernière vue (pour le nettoyage) : l'image part quand même
            _log("[TABLEAU][E16] date de vue d'une image non notée")
            _log(f"[TABLEAU][E16:DETAIL] {type(ex).__name__} {ex}")
    return web.Response(body=data, headers=dict(ENTETES, **{"Content-Type": typ, "Content-Security-Policy": CSP_MEDIA,
                                                           "Content-Disposition": "inline"}))


# ═══════════════════════════════════════════════════════════════════════════════
#  Site v2 — le nettoyage (rubrique « Nettoyage » et boucle quotidienne)
# ═══════════════════════════════════════════════════════════════════════════════

def _verrou(nom: str, fabrique):
    """Le verrou `nom` de la boucle d'évènements en cours (créé au besoin)."""
    boucle = asyncio.get_running_loop()
    deja = _verrous.get(nom)
    if deja is None or deja[0] is not boucle:
        deja = _verrous[nom] = (boucle, fabrique())
    return deja[1]


async def _compter(sql: str, args: tuple) -> int:
    async with _get_db() as db:
        rows = await recrutements._lignes(db, sql, args)  # une table absente (base ancienne) : 0
    return int(rows[0][0] or 0) if rows else 0


async def _supprimer(sql: str, args: tuple) -> int:
    async with _get_db() as db:
        try:
            cur = await db.execute(sql, args)
        except Exception as ex:
            if "no such table" in str(ex):
                return 0
            raise
        n = max(cur.rowcount or 0, 0)
        await db.commit()
    return n


def _sqlite_date(t: float) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def jours_regle(guild_id: int, cle: str) -> int:
    """La durée de garde d'une règle pour ce serveur (réglée sur le site, sinon celle par défaut), bornée."""
    r = REGLES.get(cle)
    if r is None:
        return 0
    if r["min"] == r["max"] or _get_db is None:
        return r["garde_jours"]
    try:
        async with _get_db() as db:
            async with db.execute("SELECT jours FROM tableau_nettoyage WHERE guild_id=? AND cle=?",
                                  (int(guild_id), cle)) as cur:
                row = await cur.fetchone()
    except Exception as ex:  # réglage illisible : la durée par défaut (la plus prudente), et on le dit
        _log("[TABLEAU][E14] réglage de nettoyage illisible")
        _log(f"[TABLEAU][E14:DETAIL] {cle} {type(ex).__name__} {ex}")
        return r["garde_jours"]
    return max(r["min"], min(r["max"], int(row[0]))) if row else r["garde_jours"]


async def etat_nettoyage(guild_id: int, maintenant: float | None = None) -> dict:
    """Ce que la rubrique « Nettoyage » montre : les règles (durée, bornes), ce que chacune garde
    aujourd'hui, le dernier passage et son bilan."""
    t = maintenant or time.time()
    regles, compteurs = [], {}
    for r in sorted(REGLES.values(), key=lambda x: (x["ordre"], x["cle"])):
        jours = await jours_regle(guild_id, r["cle"])
        regles.append({"cle": r["cle"], "nom": r["nom"], "quoi": r["quoi"], "garde_jours": jours,
                       "defaut": r["garde_jours"], "min": r["min"], "max": r["max"],
                       "reglable": r["min"] < r["max"], "auto": r["fn"] is not None})
        if r["compter"] is not None:
            try:
                n = r["compter"](int(guild_id), jours, t)
                compteurs[r["cle"]] = int(((await n) if inspect.isawaitable(n) else n) or 0)
            except Exception as ex:  # un compteur illisible n'empêche pas les autres
                _log("[TABLEAU][E15] compteur de nettoyage illisible")
                _log(f"[TABLEAU][E15:DETAIL] {r['cle']} {type(ex).__name__} {ex}")
                compteurs[r["cle"]] = None
    async with _get_db() as db:
        async with db.execute("SELECT dernier, bilan, par FROM tableau_nettoyage_etat WHERE guild_id=?",
                              (int(guild_id),)) as cur:
            row = await cur.fetchone()
        async with db.execute("SELECT quand, total, detail, par FROM tableau_nettoyage_bilans WHERE guild_id=?"
                              " ORDER BY id DESC LIMIT 10", (int(guild_id),)) as cur:
            bilans = [{"quand": int(q), "total": int(n), "detail": str(dt or ""), "par": str(par) if par else ""}
                      for q, n, dt, par in await cur.fetchall()]
    try:
        bilan = json.loads(row[1]) if row else {}
    except ValueError:
        bilan = {}
    return {"regles": regles, "compteurs": compteurs, "dernier": int(row[0]) if row and row[0] else None,
            "bilan": bilan if isinstance(bilan, dict) else {}, "par": str(row[2]) if row and row[2] else "",
            "bilans": bilans}


async def nettoyer(g, auteur=None, maintenant: float | None = None) -> dict:
    """Applique chaque règle à ce serveur ; le bilan (clé → éléments retirés, -1 : en échec) est gardé et
    noté au journal du site. `auteur` None : la boucle quotidienne."""
    t = maintenant or time.time()
    bilan: dict = {}
    async with _verrou("nettoyage", asyncio.Lock):
        for r in sorted(REGLES.values(), key=lambda x: (x["ordre"], x["cle"])):
            if r["fn"] is None:
                continue
            jours = await jours_regle(g.id, r["cle"])
            try:
                n = r["fn"](int(g.id), jours, t)
                bilan[r["cle"]] = max(int(((await n) if inspect.isawaitable(n) else n) or 0), 0)
            except Exception as ex:  # une règle en échec n'arrête pas les autres ; elle est dite dans le bilan
                _log("[TABLEAU][E17] règle de nettoyage en échec")
                _log(f"[TABLEAU][E17:DETAIL] {r['cle']} {type(ex).__name__} {ex}")
                diag.compter("site", f"nettoyage.{r['cle']}", ex)
                bilan[r["cle"]] = -1
        async with _get_db() as db:
            await db.execute("INSERT OR REPLACE INTO tableau_nettoyage_etat (guild_id, dernier, bilan, par)"
                             " VALUES (?,?,?,?)", (int(g.id), int(t), json.dumps(bilan), int(getattr(auteur, "id", 0) or 0)))
            await db.commit()
    retires = {k: n for k, n in bilan.items() if n > 0}
    echecs = [REGLES[k]["nom"] for k, n in bilan.items() if n < 0 and k in REGLES]
    total = sum(retires.values())
    resume = " · ".join(f"{REGLES[k]['nom']} {n}" for k, n in retires.items() if k in REGLES)
    async with _get_db() as db:
        await db.execute("INSERT INTO tableau_nettoyage_bilans (guild_id, quand, total, detail, par) VALUES (?,?,?,?,?)",
                         (int(g.id), int(t), total, (resume + (" · en échec : " + ", ".join(echecs) if echecs else ""))[:600],
                          int(getattr(auteur, "id", 0) or 0)))
        await db.execute("DELETE FROM tableau_nettoyage_bilans WHERE guild_id=? AND id NOT IN (SELECT id FROM"
                         " tableau_nettoyage_bilans WHERE guild_id=? ORDER BY id DESC LIMIT ?)",
                         (int(g.id), int(g.id), NETTOYAGE_BILANS))
        await db.commit()
    texte = ("Nettoyage du site" + (" (automatique)" if auteur is None else f" lancé par {auteur.display_name}")
             + (f" : {total} élément(s) retiré(s)" if total else " : rien à retirer"))
    detail = " · ".join([f"{REGLES[k]['nom']} : {n}" for k, n in retires.items() if k in REGLES]
                        + ([f"en échec : {', '.join(echecs)}"] if echecs else []))
    await registre.noter(g.id, "Site", "site.nettoyage", texte, auteur_id=int(getattr(auteur, "id", 0) or 0),
                         detail=detail, gravite=1 if echecs else 0)
    return bilan


async def nettoyer_si_du(g, maintenant: float | None = None) -> dict | None:
    """La boucle (horaire) : les règles une fois par jour et par serveur, même après un redémarrage."""
    t = maintenant or time.time()
    async with _get_db() as db:
        async with db.execute("SELECT dernier FROM tableau_nettoyage_etat WHERE guild_id=?", (int(g.id),)) as cur:
            row = await cur.fetchone()
    if row is not None and t - int(row[0] or 0) < NETTOYAGE_INTERVALLE:
        return None
    return await nettoyer(g, None, t)


def _noms_nettoyage(g, etat: dict) -> dict:
    """Qui a lancé les nettoyages (`par`, et celui de chaque bilan), avec son nom : la page ne connaît que les personnes
    citées dans ses données (25/10/2026 : le fondateur, absent des 400 derniers évènements, s'y lisait « Membre parti »)."""
    qui = _Personnes(g)
    for uid in [etat.get("par"), *(b.get("par") for b in etat.get("bilans") or [])]:
        if str(uid or "").isdigit():
            qui(int(uid))
    return dict(qui)


async def _route_nettoyage(g, auteur, requete, corps):
    """`GET api/nettoyage` → `{"regles", "compteurs", "dernier", "bilan", "par", "bilans", "personnes"}`."""
    rep = await etat_nettoyage(g.id)
    rep["personnes"] = _noms_nettoyage(g, rep)
    return 200, rep


async def _route_nettoyage_regle(g, auteur, requete, corps):
    """`POST api/nettoyage/regle` `{"cle", "garde_jours"}` : une durée, dans les bornes de la règle."""
    cle, jours = corps.get("cle"), corps.get("garde_jours")
    r = REGLES.get(cle) if isinstance(cle, str) else None
    if r is None:
        return 404, {"erreur": "Règle inconnue.", "champ": "cle"}
    if r["min"] == r["max"]:
        return 400, {"erreur": "Cette durée est fixe.", "champ": "cle"}
    if isinstance(jours, bool) or not isinstance(jours, int) or not r["min"] <= jours <= r["max"]:
        return 400, {"erreur": f"Entre {r['min']} et {r['max']} jours.", "champ": "garde_jours"}
    avant = await jours_regle(g.id, cle)
    async with _get_db() as db:
        await db.execute("INSERT OR REPLACE INTO tableau_nettoyage (guild_id, cle, jours, maj_le, maj_par)"
                         " VALUES (?,?,?,?,?)", (int(g.id), cle, jours, int(time.time()), int(auteur.id)))
        await db.commit()
    rep = await etat_nettoyage(g.id)
    rep.update(ok=True, regle=next(x for x in rep["regles"] if x["cle"] == cle), personnes=_noms_nettoyage(g, rep),
               _journal=f"Règle de nettoyage « {r['nom']} » : {jours} jours (avant : {avant})" if avant != jours else None)
    return 200, rep


async def _route_nettoyage_lancer(g, auteur, requete, corps):
    """`POST api/nettoyage/lancer` : toutes les règles maintenant (une fois toutes les 5 minutes au plus)."""
    t = time.time()
    if t - _nettoyages.get(g.id, 0) < NETTOYAGE_MANUEL:
        return 429, {"erreur": "Déjà lancé il y a moins de 5 minutes."}
    _nettoyages[g.id] = t
    await nettoyer(g, auteur, t)
    rep = await etat_nettoyage(g.id)
    rep.update(ok=True, personnes=_noms_nettoyage(g, rep), _journal=None)  # `nettoyer` a déjà noté son bilan
    return 200, rep


#  Les règles de ce fichier (les modules ajoutent les leurs par `monter`).

class _Serveur:
    """Un serveur réduit à son identifiant (les lectures de tickets ne demandent que lui)."""

    def __init__(self, gid: int):
        self.id = int(gid)


async def _purger_journal_messages(gid, jours, t):
    return await _supprimer("DELETE FROM registre WHERE guild_id=? AND categorie IN ('Messages', 'Vocal') AND quand < ?",
                            (gid, int(t - jours * 86400)))


async def _compter_journal_messages(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM registre WHERE guild_id=? AND categorie IN ('Messages', 'Vocal')", (gid,))


async def _purger_journal(gid, jours, t):
    return await _supprimer("DELETE FROM registre WHERE guild_id=? AND quand < ?", (gid, int(t - jours * 86400)))


async def _compter_journal(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM registre WHERE guild_id=? AND categorie NOT IN ('Messages', 'Vocal')",
                          (gid,))


async def _compter_archives(gid, jours, t):
    """Les tickets fermés depuis plus de `jours` : rangés dans les archives de la liste (la page les replie)."""
    borne = t - jours * 86400
    return sum(1 for x in await _lignes_tickets(_Serveur(gid)) if x["statut"] != "open"
               and ((x["fin"][0] if x["fin"] and x["fin"][0] else x["ouvert"]) or 0) < borne)


async def _purger_transcripts(gid, jours, t):
    return await asyncio.to_thread(transcript_store.purge_old)


async def _compter_transcripts(gid, jours, t):
    def compter():
        try:
            return sum(1 for n in os.listdir(transcript_store._BASE_DIR) if n.endswith(".html"))
        except OSError:
            return 0
    return await asyncio.to_thread(compter)


async def _candidatures_refusees(gid, jours, t) -> list:
    async with _get_db() as db:
        rows = await recrutements._lignes(db, "SELECT ticket_id, raison, decision FROM recrutements"
                                              " WHERE guild_id=? AND ferme_le < ?", (gid, int(t - jours * 86400)))
    return [int(tid) for tid, raison, prise in rows if recrutements.decision(False, raison or "", prise or "") == "refuses"]


async def _purger_candidatures(gid, jours, t):
    n = 0
    for tid in await _candidatures_refusees(gid, jours, t):
        n += await _supprimer("DELETE FROM recrutements WHERE guild_id=? AND ticket_id=?", (gid, tid))
    return n


async def _compter_candidatures(gid, jours, t):
    return len(await _candidatures_refusees(gid, jours, t))


def _avec_serveur(f) -> bool:
    """`medias_utilises(guild_id)` ou `medias_utilises()` : les deux formes sont acceptées."""
    try:
        params = inspect.signature(f).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL) for p in params)


async def _medias_utilises(gid) -> set:
    utilises: set = set()
    for f in list(_SOURCES_MEDIAS):
        res = f(gid) if _avec_serveur(f) else f()
        utilises |= {str(x) for x in ((await res) if inspect.isawaitable(res) else res) or ()}
    return utilises


async def _purger_medias(gid, jours, t):
    """Une image envoyée, plus utilisée nulle part (les modules le disent), ni vue depuis `jours` jours."""
    borne = int(t - jours * 86400)
    utilises = await _medias_utilises(gid)  # une source en échec : on ne retire RIEN (exception remontée)
    async with _get_db() as db:
        async with db.execute("SELECT id FROM tableau_medias WHERE guild_id=? AND cree_le < ? AND vu_le < ?",
                              (gid, borne, borne)) as cur:
            candidats = [str(r[0]) for r in await cur.fetchall()]
    n = 0
    for ident in candidats:
        if ident in utilises or not FORMAT_MEDIA.fullmatch(ident):
            continue
        for ext in ("webp", "png"):
            p = dossier_site("medias") / f"{ident}.{ext}"
            if p.exists():
                await asyncio.to_thread(p.unlink)
        n += await _supprimer("DELETE FROM tableau_medias WHERE id=?", (ident,))
    return n


async def _compter_medias(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM tableau_medias WHERE guild_id=?", (gid,))


async def _purger_ops(gid, jours, t):
    return await _supprimer("DELETE FROM tableau_ops WHERE guild_id=? AND quand < ?", (gid, int(t - jours * 86400)))


async def _compter_ops(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM tableau_ops WHERE guild_id=?", (gid,))


async def _purger_sessions(gid, jours, t):
    n = 0
    for _nom, sql, _j, _f in PURGES:
        n += await _supprimer(sql, (int(t),))
    return n


async def _compter_sessions(gid, jours, t):
    return await _compter("SELECT COUNT(*) FROM tableau_sessions WHERE guild_id=? AND expire_le >= ?", (gid, int(t)))


def _regle_interne(**r) -> None:
    regle = _normaliser_regle(r)
    REGLES[regle["cle"]] = regle
    _REGLES_INTERNES.add(regle["cle"])


def purges_en_regle(purges):
    """Une règle de nettoyage tirée d'une liste `PURGES` (nom, requête, jours, format — celle du grand nettoyage) :
    la durée réglée sur le site remplace celle de la liste ; une requête sans durée (orphelins) passe telle quelle."""
    async def fn(_gid, jours, t):
        n = 0
        for _nom, sql, j, fmt in purges:
            if j:
                borne = t - jours * 86400
                n += await _supprimer(sql, (int(borne) if fmt == "unix" else _sqlite_date(borne),))
            else:
                n += await _supprimer(sql, ())
        return n
    return fn


def ajouter_regle(**r) -> None:
    """Une règle de nettoyage donnée par un module (même forme que `REGLES_NETTOYAGE`) ; jamais une règle de
    ce fichier remplacée. La même clé, redonnée : remplacée (un module rebranché)."""
    regle = _normaliser_regle(r)
    if regle["cle"] in _REGLES_INTERNES:
        raise ValueError(f"règle de nettoyage en double : {regle['cle']}")
    REGLES[regle["cle"]] = regle


_regle_interne(cle="journal_messages", nom="Journal : messages et vocal",
               quoi="Messages supprimés ou modifiés, allées et venues en vocal : effacés du journal après ce délai.",
               garde_jours=registre.JOURS_COURTS, min=registre.JOURS_COURTS, max=registre.JOURS_COURTS, ordre=10,
               fn=_purger_journal_messages, compter=_compter_journal_messages)
_regle_interne(cle="journal", nom="Journal : tout le reste",
               quoi="Sanctions, tickets, arrivées, sécurité, site… : effacés du journal après ce délai.",
               garde_jours=registre.JOURS, min=registre.JOURS, max=registre.JOURS, ordre=11,
               fn=_purger_journal, compter=_compter_journal)
_regle_interne(cle="tickets_archives", nom="Tickets fermés : archives",
               quoi="Un ticket fermé depuis plus longtemps passe dans les archives de la liste (il reste consultable).",
               garde_jours=30, min=7, max=90, ordre=20, compter=_compter_archives)
_regle_interne(cle="transcripts", nom="Conversations des tickets fermés",
               quoi="Les pages des conversations (transcripts) : effacées après ce délai.",
               garde_jours=transcript_store._RETENTION_DAYS, min=transcript_store._RETENTION_DAYS,
               max=transcript_store._RETENTION_DAYS, ordre=21, fn=_purger_transcripts, compter=_compter_transcripts)
_regle_interne(cle="candidatures_refusees", nom="Candidatures refusées",
               quoi="Les fiches des candidatures refusées : effacées après ce délai (les acceptées restent).",
               garde_jours=180, min=30, max=365, ordre=30, fn=_purger_candidatures, compter=_compter_candidatures)
_regle_interne(cle="medias", nom="Images inutilisées",
               quoi="Une image envoyée sur le site, utilisée nulle part et pas vue depuis ce délai : effacée.",
               garde_jours=30, min=7, max=180, ordre=80, fn=_purger_medias, compter=_compter_medias)
_regle_interne(cle="ops", nom="Modifications hors ligne",
               quoi="La trace des modifications envoyées au retour du réseau (pour ne jamais les appliquer deux fois).",
               garde_jours=30, min=7, max=90, ordre=90, fn=_purger_ops, compter=_compter_ops)
_regle_interne(cle="sessions", nom="Sessions et liens du site",
               quoi="Les sessions et les liens expirés : effacés dès leur fin.",
               garde_jours=0, min=0, max=0, ordre=95, fn=_purger_sessions, compter=_compter_sessions)

#  Les adresses de ce fichier, sous `/tableau/espace/api/`.
_INTERNES.update({nom: {d["methode"]: _normaliser_route(nom, d)} for nom, d in {
    "media": {"methode": "POST", "fn": _route_media, "ecriture": True, "corps_max": (MEDIA_MAX + 2) // 3 * 4 + 64 * 1024},
    "nettoyage": {"methode": "GET", "fn": _route_nettoyage},
    "nettoyage/regle": {"methode": "POST", "fn": _route_nettoyage_regle, "ecriture": True},
    "nettoyage/lancer": {"methode": "POST", "fn": _route_nettoyage_lancer, "ecriture": True},
}.items()})


# ═══════════════════════════════════════════════════════════════════════════════
#  Le site de l'équipage (26/10/2026) — `/tableau/equipage/`
#  Une page à part, en LECTURE SEULE pour les membres du rôle du clan (portée « equipage ») ; le fondateur et la
#  direction (« tout ») y ont le mode édition, dont les écritures passent par `/tableau/espace/api/equipage/…`
#  (registre `monter` : origine, tête, cadence, journal). Les données viennent de `site_equipage.py`.
# ═══════════════════════════════════════════════════════════════════════════════

def monter_equipage(lectures: dict, medias=None) -> int:
    """Branche les lectures du site de l'équipage — `{nom : async (g, membre, session, requete) → (statut, corps)}`,
    servies en GET seulement sous `/tableau/equipage/api/<nom>` — et `medias(g)` → les images qu'une session
    « equipage » peut voir (sans elle : aucune). Tout est vérifié avant de brancher ; rebrancher les mêmes ne change
    rien. Rend le nombre de lectures."""
    if not isinstance(lectures, dict):
        raise ValueError("monter_equipage : une table de lectures")
    for nom, fn in lectures.items():
        if not isinstance(nom, str) or not FORMAT_ROUTE.fullmatch(nom) or not callable(fn):
            raise ValueError(f"lecture de l'équipage invalide : {nom!r}")
        deja = ROUTES_EQUIPAGE.get(nom)
        if deja is not None and deja is not fn:
            raise ValueError(f"lecture de l'équipage en double : {nom}")
    if medias is not None and not callable(medias):
        raise ValueError("monter_equipage : `medias` doit être une fonction")
    ROUTES_EQUIPAGE.update(lectures)
    if medias is not None:
        global MEDIAS_EQUIPAGE
        MEDIAS_EQUIPAGE = medias
    return len(lectures)


async def _media_permis_equipage(g, ident: str) -> bool:
    """L'image fait partie de celles que le site de l'équipage cite. Sans source, ou en échec : non (fermé)."""
    if MEDIAS_EQUIPAGE is None or g is None:
        return False
    try:
        permis = MEDIAS_EQUIPAGE(g)
        permis = (await permis) if inspect.isawaitable(permis) else permis
    except Exception as ex:  # en doute, on refuse ; le détail part au journal du bot
        _log("[TABLEAU][E41] images du site de l'équipage illisibles")
        _log(f"[TABLEAU][E41:DETAIL] {type(ex).__name__} {ex}")
        diag.compter("site", "equipage.medias", ex)
        return False
    return str(ident) in (permis or ())


async def vers_equipage(request):
    """`/tableau/equipage` sans la barre : la page est à `/tableau/equipage/`."""
    from aiohttp import web
    return web.Response(status=303, headers=dict(ENTETES, Location=EQUIPAGE))


async def page_equipage(request):
    """La page du site de l'équipage (`site/equipage.html`) : une session « equipage » ou « tout »."""
    from aiohttp import web
    try:
        await _verifier(request, portees=PORTEES)
    except _Refus as r:
        return _html(EXPIRE_EQUIPAGE if r.status != 429 else TROP, r.status)
    texte = _lire_page_site("equipage.html")
    if texte is None:
        return _html(_message("Site en maintenance", "Réessaie dans quelques minutes."), 503)
    r = web.Response(text=texte, content_type="text/html", headers=dict(ENTETES, **{"Content-Security-Policy": CSP_SITE}))
    r.enable_compression()
    return r


async def api_equipage(request):
    """`GET /tableau/equipage/api/{nom}` : une lecture du site de l'équipage (`monter_equipage`). Même porte que le reste
    (session, rôle du clan revérifié, cadence) ; une erreur reste ici (« indisponible », le détail au journal)."""
    from aiohttp import web
    nom = str(request.match_info.get("nom", ""))
    try:
        j, g = await _verifier(request, portees=PORTEES)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    fn = ROUTES_EQUIPAGE.get(nom) if FORMAT_ROUTE.fullmatch(nom) else None
    if fn is None:
        return _json({"erreur": "Adresse inconnue."}, 404)
    try:
        res = fn(g, g.get_member(j["u"]), {"portee": j["p"], "expire": j["e"]}, _parametres(request))
        status, rep = (await res) if inspect.isawaitable(res) else res
        if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status <= 599 or not isinstance(rep, dict):
            raise TypeError("réponse mal formée")
    except Exception as ex:  # la page lit « indisponible », le détail part au journal
        _log("[TABLEAU][E40] lecture du site de l'équipage en échec")
        _log(f"[TABLEAU][E40:DETAIL] {nom} {type(ex).__name__} {ex}")
        diag.compter("site", f"equipage.{nom}", ex)
        return _json({"erreur": "Indisponible pour le moment."}, 500)
    rep = {k: v for k, v in rep.items() if not str(k).startswith("_")}
    if status == 200:
        etag = '"' + hashlib.sha256(json.dumps(rep, sort_keys=True, ensure_ascii=False, default=str)
                                    .encode("utf-8")).hexdigest()[:20] + '"'
        if _meme_etag(request, etag):
            return web.Response(status=304, headers=dict(ENTETES, ETag=etag))
        return _json(rep, 200, etag=etag)
    return _json(rep, status)


async def api_equipage_refus(request):
    """`POST /tableau/equipage/api/…` : le site de l'équipage ne reçoit AUCUNE écriture (les modifications de la
    direction passent par `/tableau/espace/api/equipage/…`, avec toutes leurs vérifications)."""
    return _json({"erreur": "Lecture seule."}, 403)


# ═══════════════════════════════════════════════════════════════════════════════
#  Site v2 — la présence en direct et les verrous d'édition (`/tableau/espace/direct`)
# ═══════════════════════════════════════════════════════════════════════════════
#  26/10/2026 — « quand la direction ou quelqu'un est sur le site et l'utilise, affiche les personnes qui utilisent le
#  site en temps réel et ce qu'ils modifient (…) qu'ils aient vraiment une zone comme quoi on ne peut pas toucher parce
#  que c'est en cours de modification. »
#
#  · Une WebSocket par onglet (`GET /tableau/espace/direct`) : la même porte que le reste — session du cookie (relue
#    chaque minute et à chaque prise de verrou), personne toujours à la tête, pas suspendue, origine de la page —, une
#    « salle » par serveur Discord. Sans WebSocket (un proxy qui la bloque), la page interroge `GET api/direct/etat` et
#    envoie par `POST api/direct/envoi` toutes les 10 s : le même protocole, en plus lent.
#  · Tout vit en MÉMOIRE (un seul processus) : qui est là, ses onglets et leur page, les verrous. Aucune lecture de la
#    base pour la présence (seule la revérification d'une session relit sa ligne).
#  · Un verrou est un bail par onglet (60 s), renouvelé par le battement de la page (20 s) ; onglet caché : pas de
#    battement, un bail de 5 min 30 (sans saisie depuis 5 min, la page rend la main d'elle-même). Il tombe à
#    « lacher », à l'expiration, à la fermeture de la socket après une grâce de 10 s (un rechargement ne le perd pas).
#    La même personne dans deux onglets : le verrou est à elle (réentrant).
#  · Le serveur fait respecter les verrous : une écriture dont la route déclare un « verrou » (`ROUTES_SITE` :
#    `"verrou": fonction(corps) → objet(s) | None`, sinon la table `VERROUS_ROUTES` ci-dessous) est refusée (423,
#    « En cours de modification par X. ») si l'objet est tenu par QUELQU'UN D'AUTRE. Rejouée par la file hors ligne,
#    elle n'est jamais gardée comme refusée : elle attend dans la page et repart quand l'objet se libère.
#  · Les messages (JSON compacts, 1 Ko au plus ; `o` : la clé de l'objet). Page → serveur : bonjour {page, onglet?},
#    page {page}, prendre {o, ti, n?}, lacher {o}, vivant {cache?}, demande {o}. Serveur → page : etat (à l'arrivée),
#    puis seulement des deltas — present, absent, page, verrou, libre, ecrit — et les réponses : pris {o, n, ch, v},
#    refuse {o, par, nom}, demandee {o}, demande {o, par, nom} (au détenteur seulement). Sans WebSocket, le même
#    message part dans `POST api/direct/envoi` avec l'identifiant de l'onglet (`onglet`).

DIRECT_BAIL = 60                 # s : le verrou d'un onglet qui ne bat plus tombe
DIRECT_BAIL_CACHE = 330          # s : onglet caché (aucun battement) — l'inactivité (5 min) rend la main avant
DIRECT_BATTEMENT = 20            # s : le battement d'une page qui tient un verrou
DIRECT_GRACE = 10                # s : une socket fermée garde sa présence et ses verrous (un rechargement)
DIRECT_VERIFIER = 60             # s : la session de chaque socket est revérifiée
DIRECT_PING = 25                 # s : battement WebSocket (aiohttp) : une connexion morte est coupée
DIRECT_RONDE = 5                 # s : la ronde d'une salle (baux, grâces, sessions)
DIRECT_BONJOUR = 10              # s : le premier message attendu d'une socket
DIRECT_INACTIF = 300             # s : (page) sans saisie depuis, l'éditeur rend la main
DIRECT_TOUR = 10                 # s : (page, sans WebSocket) l'interrogation
DIRECT_HTTP_VIE = 35             # s : un onglet qui interroge et ne donne plus de nouvelles est parti
DIRECT_MSG_MAX = 1024            # octets par message
DIRECT_CADENCE = 40              # messages par 10 s et par onglet (au-delà : ignorés ; trois fois plus : coupé)
DIRECT_ONGLETS = 8               # onglets branchés par personne
DIRECT_PRISES = 64               # onglets branchés par salle
DIRECT_VERROUS = 24              # verrous par personne
DIRECT_FILE = 200                # messages en attente d'écriture sur une socket (au-delà : trop lente, coupée)
DIRECT_BOITE = 20                # messages gardés pour un onglet qui interroge
DIRECT_DEMANDE = 20              # s entre deux « Demander la main » du même objet, par onglet
DIRECT_ECRITS = 4096             # objets dont le compteur d'écritures est gardé
DIRECT_TITRE = 120
FORMAT_OBJET = re.compile(r"[a-z][a-z0-9_-]{0,29}:[A-Za-z0-9_.:@~-]{1,270}")
FORMAT_PAGE = re.compile(r"[a-z0-9_-]{1,30}(?:/[a-z0-9_-]{1,60}){0,3}")
FORMAT_ONGLET = re.compile(r"[A-Za-z0-9_-]{8,40}")
_INVISIBLES_DIRECT = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁠-⁤⁦-⁩﻿]")
#  Les codes de fermeture (la page les lit) : session finie ou accès retiré → « session terminée », sans reconnexion ;
#  une session d'une autre portée que « tout » (l'équipage, en lecture seule) → le direct ne la concerne pas.
CODE_SESSION, CODE_ACCES, CODE_MESSAGE, CODE_TROP, CODE_LENT, CODE_PORTEE = 4401, 4403, 4400, 4429, 4408, 4406
PORTEE_DIRECT = "tout"           # seules les sessions du fondateur et de la direction entrent dans le direct
_direct_salles: dict = {}        # serveur → _Salle
_direct_ecrits: dict = {}        # (serveur, objet) → {"n": compteur, "h": [(n, auteur)…] (les 8 dernières écritures)}


def _fnv(texte: str) -> str:
    """FNV-1a sur 32 bits (la page fait le même calcul) : l'empreinte d'une clé d'objet trop longue."""
    h = 0x811C9DC5
    for octet in texte.encode("utf-8"):
        h = ((h ^ octet) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def objet_direct(o) -> str | None:
    """La clé d'un objet (`type:identifiant`) telle que le direct la garde : 100 caractères au plus (au-delà, raccourcie
    par son empreinte, comme le fait la page) — None si elle est invalide."""
    if not isinstance(o, str) or len(o) > 300 or not FORMAT_OBJET.fullmatch(o):
        return None
    return o if len(o) <= 100 else o[:91] + "~" + _fnv(o)


def _titre_direct(t) -> str:
    return re.sub(r"\s+", " ", _INVISIBLES_DIRECT.sub("", str(t or ""))).strip()[:DIRECT_TITRE]


def _page_direct(p) -> str:
    p = str(p or "")[:200]
    return p if FORMAT_PAGE.fullmatch(p) else ""


class _Verrou:
    """Un objet en cours de modification : par qui, et le bail de chacun de ses onglets."""
    __slots__ = ("objet", "titre", "uid", "prises", "depuis")

    def __init__(self, objet: str, titre: str, uid: int, t: float):
        self.objet, self.titre, self.uid, self.depuis = objet, titre, uid, t
        self.prises: dict = {}       # onglet → fin de son bail


class _Prise:
    """Un onglet branché : une WebSocket (`ws`), ou une page qui interroge (`ws` None : ses messages passent par
    `api/direct/…`, et ce qui lui est adressé attend dans `boite`)."""
    __slots__ = ("id", "gid", "uid", "emp", "ws", "page", "page_t", "depuis", "vu", "verifie", "cache", "ferme_le",
                 "bonjour", "file", "ecrivain", "seau", "demandes", "boite", "fin", "code")

    def __init__(self, ident: str, gid: int, uid: int, emp: str, ws, t: float):
        self.id, self.gid, self.uid, self.emp, self.ws = ident, gid, uid, emp, ws
        self.page, self.page_t, self.depuis, self.vu, self.verifie = "", t, t, t, t
        self.cache, self.ferme_le, self.bonjour, self.fin, self.code = False, 0.0, False, "", 0
        self.file = asyncio.Queue() if ws is not None else None
        self.ecrivain = None
        self.seau: list = []
        self.demandes: dict = {}
        self.boite: list = []

    def envoyer(self, texte: str) -> None:
        if self.ferme_le or self.file is None or self.fin:
            return
        if self.file.qsize() >= DIRECT_FILE:   # elle ne lit plus : coupée, elle se reconnectera
            _couper(self, CODE_LENT, "lent")
            return
        self.file.put_nowait(texte)


class _Salle:
    """Un serveur Discord : ses onglets branchés, ses verrous, l'arrivée de chacun (gardée tant qu'il est là), et ce
    que les pages savent des pages de chacun (le dernier delta « page » envoyé)."""
    __slots__ = ("gid", "prises", "verrous", "arrivees", "vues", "ronde")

    def __init__(self, gid: int):
        self.gid = gid
        self.prises: dict = {}
        self.verrous: dict = {}
        self.arrivees: dict = {}
        self.vues: dict = {}
        self.ronde = None


def _salle_direct(gid: int) -> _Salle:
    s = _direct_salles.get(gid)
    if s is None:
        s = _direct_salles[gid] = _Salle(gid)
    return s


def _texte_direct(m: dict) -> str:
    return json.dumps(m, ensure_ascii=False, separators=(",", ":"))


def _envoyer_a(prise: _Prise, m: dict) -> None:
    """Un message pour cet onglet seul (une réponse, une demande de la main)."""
    if prise.ferme_le:
        return
    if prise.ws is None:
        if len(prise.boite) < DIRECT_BOITE:
            prise.boite.append(m)
        return
    prise.envoyer(_texte_direct(m))


def _diffuser(salle: _Salle, m: dict, sauf: _Prise | None = None) -> None:
    """Un delta à tous les onglets branchés (ceux qui interrogent relisent l'état complet à leur tour)."""
    texte = None
    for p in list(salle.prises.values()):
        if p is sauf or p.ferme_le or not p.bonjour or p.ws is None:
            continue
        texte = texte or _texte_direct(m)
        p.envoyer(texte)


def _couper(prise: _Prise, code: int, raison: str) -> None:
    """Ferme la socket d'un onglet (session finie, trop de messages, trop lente) : sa boucle de réception s'arrête."""
    if not prise.fin:
        prise.fin, prise.code = raison, code
    ws = prise.ws
    if ws is not None and not ws.closed:
        asyncio.get_running_loop().create_task(ws.close(code=prise.code, message=prise.fin.encode()))


def _qui_direct(gid: int, uid: int) -> dict:
    g = _bot.get_guild(gid) if _bot is not None else None
    i = _ident(g, uid) if g is not None else {"id": str(uid), "nom": "Membre parti", "avatar": ""}
    return {"id": i["id"], "nom": i["nom"], "av": i["avatar"]}


def _personne_direct(salle: _Salle, uid: int) -> dict | None:
    """Une personne à bord : nom, avatar, les pages de ses onglets ouverts (la plus récente d'abord ; pendant un
    rechargement, celles d'avant), combien d'onglets, son arrivée. None si elle n'a plus d'onglet."""
    prises = [p for p in salle.prises.values() if p.uid == uid and p.bonjour]
    if not prises:
        return None
    pages: dict = {}
    for p in sorted([p for p in prises if not p.ferme_le] or prises, key=lambda x: x.page_t):
        if p.page:
            pages[p.page] = int(p.page_t)
    rec = _qui_direct(salle.gid, uid)
    rec.update(pages=sorted(([k, t] for k, t in pages.items()), key=lambda x: -x[1])[:4],
               n=sum(1 for p in prises if not p.ferme_le) or 1,
               d=int(salle.arrivees.get(uid, min(p.depuis for p in prises))))
    return rec


def _verrou_rec(salle: _Salle, v: _Verrou) -> dict:
    vivants = sum(1 for i in v.prises if (p := salle.prises.get(i)) is not None and not p.ferme_le)
    return {"o": v.objet, "ti": v.titre, "id": str(v.uid), "d": int(v.depuis), "nb": vivants}


def _etat_direct(salle: _Salle, prise: _Prise, t: float) -> dict:
    uids: list = []
    for p in salle.prises.values():
        if p.bonjour and p.uid not in uids:
            uids.append(p.uid)
    return {"t": "etat", "moi": str(prise.uid), "o": prise.id, "s": int(t),
            "p": [r for r in (_personne_direct(salle, u) for u in uids) if r],
            "v": [_verrou_rec(salle, v) for v in salle.verrous.values()],
            "cfg": {"bat": DIRECT_BATTEMENT, "bail": DIRECT_BAIL, "inactif": DIRECT_INACTIF, "tour": DIRECT_TOUR}}


def _place_direct(salle: _Salle, uid: int) -> bool:
    vivantes = [p for p in salle.prises.values() if not p.ferme_le]
    return len(vivantes) < DIRECT_PRISES and sum(1 for p in vivantes if p.uid == uid) < DIRECT_ONGLETS


def _brancher(salle: _Salle, prise: _Prise) -> None:
    """L'onglet entre dans la salle (muet jusqu'à son « bonjour ») ; la ronde de la salle tourne tant qu'il y a du monde."""
    salle.prises[prise.id] = prise
    boucle = asyncio.get_running_loop()
    if salle.ronde is None or salle.ronde.done() or salle.ronde.get_loop() is not boucle:
        salle.ronde = boucle.create_task(_ronde(salle))


def _vue_pages(rec) -> tuple:
    return (tuple(p for p, _t in rec["pages"]), rec["n"]) if rec else ()


def _delta_page(salle: _Salle, uid: int) -> None:
    """Les onglets d'une personne ont bougé : un delta « page » — seulement si ce qu'en montrent les pages change
    (comparé au dernier envoyé : un rechargement, une socket fantôme qui s'en va ne disent rien)."""
    rec = _personne_direct(salle, uid)
    if rec is None:
        return
    vue = _vue_pages(rec)
    if salle.vues.get(uid) != vue:
        salle.vues[uid] = vue
        _diffuser(salle, {"t": "page", "id": rec["id"], "pages": rec["pages"], "n": rec["n"]})


def _bonjour(salle: _Salle, prise: _Prise, page: str, t: float, onglet=None) -> list:
    nouveau = prise.uid not in salle.arrivees
    prise.page, prise.page_t, prise.bonjour = page, t, True
    if nouveau:
        salle.arrivees[prise.uid] = t
    #  Une socket qui remplace l'interrogation du même onglet (la WebSocket revient) : ses verrous passent à la
    #  socket, l'onglet qui interrogeait part tout de suite (il les aurait gardés jusqu'à son extinction).
    ancienne = (salle.prises.get("h-" + onglet) if prise.ws is not None and isinstance(onglet, str)
                and FORMAT_ONGLET.fullmatch(onglet) else None)
    if ancienne is not None and ancienne.uid == prise.uid:
        for v in salle.verrous.values():
            if ancienne.id in v.prises:
                v.prises[prise.id] = max(v.prises.pop(ancienne.id), _bail(prise, t))
        _retirer(salle, ancienne, t)
    elif nouveau:
        rec = _personne_direct(salle, prise.uid)
        salle.vues[prise.uid] = _vue_pages(rec)
        _diffuser(salle, {"t": "present", "p": rec}, sauf=prise)
    else:
        _delta_page(salle, prise.uid)
    return [_etat_direct(salle, prise, t)]


def _changer_page(salle: _Salle, prise: _Prise, page: str, t: float) -> None:
    if page and page != prise.page:
        prise.page, prise.page_t = page, t
        _delta_page(salle, prise.uid)


def _liberer(salle: _Salle, v: _Verrou, t: float) -> None:
    if salle.verrous.get(v.objet) is v:
        del salle.verrous[v.objet]
    _diffuser(salle, {"t": "libre", "o": v.objet, "s": int(t)})


def _retirer_du_verrou(salle: _Salle, v: _Verrou, onglets, t: float) -> None:
    for i in onglets:
        v.prises.pop(i, None)
    if not v.prises:
        _liberer(salle, v, t)
    else:
        _diffuser(salle, {"t": "verrou", "v": _verrou_rec(salle, v)})


def _bail(prise: _Prise, t: float) -> float:
    return t + (DIRECT_BAIL_CACHE if prise.cache else DIRECT_BAIL)


def _ecrits_n(gid: int, o: str) -> int:
    e = _direct_ecrits.get((gid, o))
    return e["n"] if e else 0


def _ecrit_depuis(gid: int, o: str, n, uid: int) -> bool:
    """Quelqu'un d'AUTRE a-t-il écrit cet objet depuis le compteur `n` que la page connaît ? Sans `n` : non. Une
    histoire perdue (compteur effacé, serveur redémarré) : oui, par prudence — la page relira."""
    if n is None:
        return False
    e = _direct_ecrits.get((gid, o))
    if e is None:
        return n > 0
    if e["n"] <= n:
        return False
    h = e["h"]
    if not h or h[0][0] > n + 1:
        return True
    return any(k > n and u != uid for k, u in h)


async def _session_direct(prise: _Prise, t: float, forcer: bool = False) -> str:
    """« » si la session de cet onglet tient toujours ; sinon « session » (finie, fermée ailleurs) ou « acces »
    (retiré, suspendu). La ligne de la session est relue en base au-delà de RELIRE secondes, ou si `forcer`."""
    s = _sessions.get(prise.emp)
    if s is None or forcer or t - s[3] > RELIRE or len(s) < 5:
        async with _get_db() as db:
            async with db.execute("SELECT guild_id, user_id, expire_le, portee FROM tableau_sessions WHERE empreinte=?",
                                  (prise.emp,)) as cur:
                r = await cur.fetchone()
        if r is None:
            _sessions.pop(prise.emp, None)
            return "session"
        #  La portée reste dans la mémoire des sessions (la porte `_verifier` la lit) : « tout » seule entre ici.
        s = _sessions[prise.emp] = (int(r[0]), int(r[1]), int(r[2]), t, str(r[3] or ""))
    if s[2] < t or (s[0], s[1]) != (prise.gid, prise.uid):
        return "session"
    if s[4] != PORTEE_DIRECT:
        return "acces"
    g = _bot.get_guild(prise.gid) if _bot is not None else None
    m = g.get_member(prise.uid) if g is not None else None
    if m is None or _autorise_membre is None or not _autorise_membre(g, m, await _cfg(g.id)):
        return "acces"
    if await suspendu(prise.gid, prise.uid, t):
        return "acces"
    return ""


def _retirer(salle: _Salle, prise: _Prise, t: float) -> None:
    """L'onglet quitte la salle pour de bon : ses verrous tombent, sa personne part si c'était son dernier onglet."""
    if salle.prises.get(prise.id) is not prise:
        return
    del salle.prises[prise.id]
    prise.ferme_le = prise.ferme_le or t
    for v in list(salle.verrous.values()):
        if prise.id in v.prises:
            _retirer_du_verrou(salle, v, [prise.id], t)
    if not prise.bonjour:
        return
    if _personne_direct(salle, prise.uid) is None:
        salle.arrivees.pop(prise.uid, None)
        salle.vues.pop(prise.uid, None)
        _diffuser(salle, {"t": "absent", "id": str(prise.uid)})
    else:
        _delta_page(salle, prise.uid)


def _finir(salle: _Salle, prise: _Prise, raison: str, t: float) -> None:
    """Session finie ou accès retiré : la socket est fermée avec son code, sans grâce (ses verrous tombent tout de suite)."""
    _couper(prise, CODE_SESSION if raison == "session" else CODE_ACCES, raison)
    _retirer(salle, prise, t)


def _debrancher(salle: _Salle, prise: _Prise, t: float) -> None:
    """La socket est fermée : présence et verrous gardés DIRECT_GRACE secondes (un rechargement les retrouve)."""
    if salle.prises.get(prise.id) is not prise:
        return
    if prise.fin in ("session", "acces") or not prise.bonjour:
        _retirer(salle, prise, t)
    else:
        prise.ferme_le = prise.ferme_le or t


async def _ronde(salle: _Salle) -> None:
    """Toutes les DIRECT_RONDE secondes, tant que la salle a du monde : grâces finies, baux échus, sessions relues."""
    while salle.prises or salle.verrous:
        await asyncio.sleep(DIRECT_RONDE)
        try:
            await _balayer(salle, time.time())
        except Exception as ex:  # une ronde ratée n'arrête pas les suivantes ; le détail part au journal
            _log("[TABLEAU][E21] ronde du direct en échec")
            _log(f"[TABLEAU][E21:DETAIL] {type(ex).__name__} {ex}")
            diag.compter("site", "direct.ronde", ex)


async def _balayer(salle: _Salle, t: float) -> None:
    for p in list(salle.prises.values()):
        if p.ws is None and not p.ferme_le and t - p.vu > (DIRECT_BAIL_CACHE if p.cache else DIRECT_HTTP_VIE):
            p.ferme_le = t       # un onglet qui interrogeait et ne donne plus de nouvelles
        if p.ferme_le and t - p.ferme_le >= DIRECT_GRACE:
            _retirer(salle, p, t)
    for v in list(salle.verrous.values()):
        echus = [i for i, fin in v.prises.items() if fin <= t]
        if echus:
            _retirer_du_verrou(salle, v, echus, t)
    for p in list(salle.prises.values()):
        if (p.ws is not None and p.emp and p.bonjour and not p.ferme_le and not p.fin
                and (p.emp not in _sessions or t - p.verifie >= DIRECT_VERIFIER)):
            p.verifie = t
            raison = await _session_direct(p, t)
            if raison:
                _finir(salle, p, raison, t)


def _cadence_direct(prise: _Prise, t: float) -> str:
    """« ok » ; « ignore » (trop d'un coup : le message est laissé) ; « coupe » (bien trop : l'onglet est coupé)."""
    prise.seau = [x for x in prise.seau if t - x < 10]
    prise.seau.append(t)
    n = len(prise.seau)
    return "coupe" if n > DIRECT_CADENCE * 3 else "ignore" if n > DIRECT_CADENCE else "ok"


async def _prendre(salle: _Salle, prise: _Prise, m: dict, t: float) -> list:
    o = objet_direct(m.get("o"))
    if o is None:
        return [{"t": "refuse", "o": str(m.get("o") or "")[:100], "err": "objet"}]
    if prise.emp:   # « à chaque prise de verrou » : la session relue en base
        prise.verifie = t
        raison = await _session_direct(prise, t, forcer=True)
        if raison:
            _finir(salle, prise, raison, t)
            return []
    titre = _titre_direct(m.get("ti")) or o.split(":", 1)[0]
    v = salle.verrous.get(o)
    if v is not None:
        echus = [i for i, fin in v.prises.items() if fin <= t]
        if echus:   # un bail échu que la ronde n'a pas encore vu
            _retirer_du_verrou(salle, v, echus, t)
            v = salle.verrous.get(o)
    if v is not None and v.uid != prise.uid:
        return [{"t": "refuse", "o": o, "par": str(v.uid), "nom": _qui_direct(salle.gid, v.uid)["nom"]}]
    if v is None:
        if sum(1 for x in salle.verrous.values() if x.uid == prise.uid) >= DIRECT_VERROUS:
            return [{"t": "refuse", "o": o, "err": "trop"}]
        v = salle.verrous[o] = _Verrou(o, titre, prise.uid, t)
    avant = (_verrou_rec(salle, v)["nb"], v.titre) if v.prises else None
    v.prises[prise.id] = _bail(prise, t)
    v.titre = titre
    rec = _verrou_rec(salle, v)
    if avant != (rec["nb"], v.titre):
        _diffuser(salle, {"t": "verrou", "v": rec}, sauf=prise)
    n = m.get("n")
    n = n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None
    return [{"t": "pris", "o": o, "n": _ecrits_n(salle.gid, o), "ch": _ecrit_depuis(salle.gid, o, n, prise.uid),
             "v": rec}]


def _lacher(salle: _Salle, prise: _Prise, o, t: float) -> None:
    o = objet_direct(o)
    v = salle.verrous.get(o) if o else None
    if v is not None and prise.id in v.prises:
        _retirer_du_verrou(salle, v, [prise.id], t)


def _vivant(salle: _Salle, prise: _Prise, cache: bool, t: float) -> None:
    """Le battement : les baux de cet onglet repartent (longs s'il est caché)."""
    prise.cache = bool(cache)
    for v in salle.verrous.values():
        if prise.id in v.prises:
            v.prises[prise.id] = _bail(prise, t)


def _demande(salle: _Salle, prise: _Prise, o, t: float) -> list:
    """« Demander la main » : la personne qui tient l'objet est prévenue (ses onglets qui le tiennent)."""
    o = objet_direct(o)
    v = salle.verrous.get(o) if o else None
    if v is None:
        return [{"t": "libre", "o": o or "", "s": int(t)}]
    if v.uid == prise.uid:
        return []
    if t - prise.demandes.get(o, 0) < DIRECT_DEMANDE:
        return [{"t": "demandee", "o": o, "deja": 1}]
    if len(prise.demandes) > 50:
        prise.demandes = {k: x for k, x in prise.demandes.items() if t - x < DIRECT_DEMANDE}
    prise.demandes[o] = t
    qui = _qui_direct(salle.gid, prise.uid)
    for i in v.prises:
        p = salle.prises.get(i)
        if p is not None:
            _envoyer_a(p, {"t": "demande", "o": o, "par": qui["id"], "nom": qui["nom"]})
    return [{"t": "demandee", "o": o}]


async def _traiter_direct(salle: _Salle, prise: _Prise, m, t: float) -> list:
    """Un message d'un onglet → ses réponses (les deltas partent d'eux-mêmes aux autres)."""
    if not isinstance(m, dict):
        return []
    genre = m.get("t")
    prise.vu = t
    if genre == "bonjour":
        return _bonjour(salle, prise, _page_direct(m.get("page")), t, m.get("onglet"))
    if not prise.bonjour:
        return []
    if genre == "page":
        _changer_page(salle, prise, _page_direct(m.get("page")), t)
    elif genre == "prendre":
        return await _prendre(salle, prise, m, t)
    elif genre == "lacher":
        _lacher(salle, prise, m.get("o"), t)
    elif genre == "vivant":
        _vivant(salle, prise, m.get("cache") is True, t)
    elif genre == "demande":
        return _demande(salle, prise, m.get("o"), t)
    return []


def _origine_direct_ok(request) -> bool:
    """La WebSocket vient de la page elle-même : même origine (un navigateur l'envoie toujours), même site."""
    h = request.headers
    if h.get("Sec-Fetch-Site", "same-origin") != "same-origin":
        return False
    attendue = _base.split("/", 3)[:3] if _base else None
    attendue = "/".join(attendue) if attendue else f"{getattr(request, 'scheme', 'https')}://{getattr(request, 'host', '')}"
    return h.get("Origin", "") == attendue


async def _ecrire_direct(prise: _Prise) -> None:
    """L'écrivain d'une socket : ses messages dans l'ordre, une socket lente n'en retarde aucune autre."""
    ws = prise.ws
    while True:
        texte = await prise.file.get()
        if texte is None or ws.closed:
            return
        try:
            await asyncio.wait_for(ws.send_str(texte), 10)
        except (asyncio.TimeoutError, ConnectionError, RuntimeError) as ex:
            if not ws.closed:   # trop lente : coupée, elle se reconnectera
                _log("[TABLEAU][E22] message du direct non envoyé")
                _log(f"[TABLEAU][E22:DETAIL] {type(ex).__name__} {ex}")
                _couper(prise, CODE_LENT, "lent")
            return


async def direct(request):
    """`GET /tableau/espace/direct` : la WebSocket du direct, une par onglet."""
    from aiohttp import web, WSMsgType
    try:
        j, g = await _verifier(request)
    except _Refus as r:
        return _json({"erreur": r.message}, r.status)
    if not _origine_direct_ok(request):
        securite_site.compter("websocket")
        return _json({"erreur": "Requête refusée."}, 400)
    ws = web.WebSocketResponse(heartbeat=DIRECT_PING, max_msg_size=DIRECT_MSG_MAX, compress=False)
    if not ws.can_prepare(request).ok:
        return _json({"erreur": "WebSocket attendue."}, 400)
    if j.get("p") != PORTEE_DIRECT:   # une autre portée (l'équipage, en lecture seule) : refusée proprement, sans retour
        await ws.prepare(request)
        await ws.close(code=CODE_PORTEE, message=b"portee")
        return ws
    salle = _salle_direct(j["g"])
    prise = _Prise(secrets.token_urlsafe(6), j["g"], j["u"], j["emp"], ws, time.time())
    place = _place_direct(salle, j["u"])
    if place:
        _brancher(salle, prise)     # avant tout `await` : la ronde voit l'onglet dès son arrivée
    await ws.prepare(request)
    if not place:
        await ws.close(code=CODE_TROP, message=b"trop")
        return ws
    prise.ecrivain = asyncio.get_running_loop().create_task(_ecrire_direct(prise))
    try:
        while not prise.fin:
            try:
                msg = await ws.receive(timeout=None if prise.bonjour else DIRECT_BONJOUR)
            except asyncio.TimeoutError:
                prise.fin = "bonjour"
                await ws.close(code=CODE_MESSAGE, message=b"bonjour")
                break
            if msg.type == WSMsgType.TEXT:
                t = time.time()
                verdict = _cadence_direct(prise, t)
                if verdict == "coupe":
                    prise.fin = "trop"
                    await ws.close(code=CODE_TROP, message=b"trop")
                    break
                if verdict == "ignore":
                    continue
                try:
                    m = json.loads(msg.data)
                except ValueError:
                    prise.fin = "message"
                    await ws.close(code=CODE_MESSAGE, message=b"message")
                    break
                for r in await _traiter_direct(salle, prise, m, t):
                    _envoyer_a(prise, r)
                if prise.fin:   # session finie à la prise d'un verrou : fermée ici, avec son code
                    await ws.close(code=prise.code or CODE_MESSAGE, message=prise.fin.encode())
                    break
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
            else:   # du binaire : rien de tel dans le protocole
                prise.fin = "message"
                await ws.close(code=CODE_MESSAGE, message=b"message")
                break
    finally:
        _debrancher(salle, prise, time.time())
        prise.file.put_nowait(None)
    return ws


async def _route_direct_etat(g, auteur, requete, corps):
    """`GET api/direct/etat?onglet=<id>&page=…&cache=0|1` (sans WebSocket, toutes les 10 s) : l'onglet donne de ses
    nouvelles (c'est aussi son battement) et lit l'état complet, avec ce qui lui est adressé (`msgs`)."""
    o = str(requete.get("onglet", ""))
    if not FORMAT_ONGLET.fullmatch(o) or auteur is None:
        return 400, {"erreur": "Onglet invalide."}
    t = time.time()
    salle = _salle_direct(g.id)
    prise = salle.prises.get("h-" + o)
    if prise is not None and prise.uid != auteur.id:
        return 409, {"erreur": "Onglet invalide."}
    if prise is None:
        if not _place_direct(salle, auteur.id):
            return 429, {"erreur": "Trop d'onglets ouverts sur le site."}
        prise = _Prise("h-" + o, g.id, auteur.id, "", None, t)
        _brancher(salle, prise)
    prise.ferme_le, prise.vu = 0.0, t     # revenu dans sa grâce : il retrouve tout
    _vivant(salle, prise, requete.get("cache") == "1", t)
    page = _page_direct(requete.get("page"))
    if not prise.bonjour:
        _bonjour(salle, prise, page, t)
    else:
        _changer_page(salle, prise, page, t)
    boite, prise.boite = prise.boite, []
    return 200, dict(_etat_direct(salle, prise, t), msgs=boite)


async def _route_direct_envoi(g, auteur, requete, corps):
    """`POST api/direct/envoi` `{"onglet": <id>, "t": …, …}` : un message de l'onglet qui interroge → `{"r": [réponses]}`."""
    o = str(corps.get("onglet", ""))
    salle = _direct_salles.get(g.id)
    prise = salle.prises.get("h-" + o) if salle is not None and FORMAT_ONGLET.fullmatch(o) else None
    if prise is None or auteur is None or prise.uid != auteur.id or prise.ferme_le:
        return 409, {"erreur": "Onglet inconnu : l'état doit être relu."}
    t = time.time()
    if _cadence_direct(prise, t) != "ok":
        return 429, {"erreur": "Trop de messages d'un coup."}
    return 200, {"r": await _traiter_direct(salle, prise, corps, t)}


def direct_ecrit(gid: int, objets, uid: int) -> None:
    """Une écriture faite (le registre l'appelle) : les compteurs, et « ecrit » à la salle (les autres pages relisent)."""
    objets = list(objets or [])
    if not objets:
        return
    for o in objets:
        e = _direct_ecrits.pop((gid, o), None) or {"n": 0, "h": []}
        e["n"] += 1
        e["h"] = (e["h"] + [(e["n"], int(uid))])[-8:]
        _direct_ecrits[(gid, o)] = e
    while len(_direct_ecrits) > DIRECT_ECRITS:
        _direct_ecrits.pop(next(iter(_direct_ecrits)))
    salle = _direct_salles.get(gid)
    if salle is not None:
        _diffuser(salle, {"t": "ecrit", "o": objets[:10], "id": str(uid)})


def refus_verrou(gid: int, objets, uid: int, maintenant: float | None = None) -> dict | None:
    """Le corps du refus (423) d'une écriture sur un objet tenu par QUELQU'UN D'AUTRE — ou None : elle peut se faire."""
    salle = _direct_salles.get(gid)
    if salle is None or not objets:
        return None
    t = maintenant or time.time()
    for o in objets:
        v = salle.verrous.get(o)
        if v is not None and v.uid != uid and any(fin > t for fin in v.prises.values()):
            nom = _qui_direct(gid, v.uid)["nom"]
            return {"erreur": f"En cours de modification par {nom}.", "verrou": {"objet": o, "par": str(v.uid), "nom": nom}}
    return None


#  Les objets que touche chaque écriture du site (la page prend les mêmes clés : `site/direct.js`). Une route peut
#  aussi déclarer le sien dans `ROUTES_SITE` (`"verrou": fonction(corps)`), qui passe avant cette table.
def _champ_id(c: dict, k: str = "id") -> str:
    v = c.get(k)
    return "" if v is None or isinstance(v, (bool, dict, list)) else str(v).strip()[:120]


def _objet_si(genre: str, *valeurs) -> str | None:
    return genre + ":" + ":".join(valeurs) if valeurs and all(valeurs) else None


def _v_affiche(c: dict) -> list:
    out = [_objet_si("affiche", _champ_id(c))]
    if not c.get("version"):   # une création : l'affiche de ce membre est peut-être en train d'être créée ailleurs
        out.append(_objet_si("affiche-membre", _champ_id(c, "membre_id")))
    return [o for o in out if o]


async def _v_correction(c: dict):
    """`recrutement/corriger` porte l'envoi, pas le ticket : le dossier se retrouve par l'envoi."""
    eid = _champ_id(c, "envoi")
    if not eid.isdigit():
        return None
    e = await questionnaire._envoi(int(eid))
    return f"dossier:{int(e['ticket_id'])}" if e else None


def _v_par_id(genre: str):
    return lambda c: _objet_si(genre, _champ_id(c))


VERROUS_ROUTES = {
    "rell/affiche": _v_affiche,
    "rell/affiche/retirer": _v_par_id("affiche"),
    "rell/affiche/restaurer": _v_par_id("affiche"),
    "rell/catalogue/element": lambda c: _objet_si("element", _champ_id(c, "type"), _champ_id(c, "cle")),
    "rell/catalogue/retirer": lambda c: _objet_si("element", _champ_id(c, "type"), _champ_id(c, "cle")),
    "rell/catalogue/type": lambda c: "catalogue:types",
    "rell/role": lambda c: _objet_si("role", _champ_id(c, "type"), _champ_id(c, "cle")),
    "rell/metiers/reglages": lambda c: "metiers:reglages",
    "recrutement/question": _v_par_id("question"),
    "recrutement/question/retirer": _v_par_id("question"),
    "recrutement/modele": _v_par_id("modele"),
    "recrutement/modele/retirer": _v_par_id("modele"),
    "recrutement/liens": lambda c: "questionnaire:liens",
    "recrutement/reglages": lambda c: "questionnaire:reglages",
    "recrutement/corriger": _v_correction,
    "recrutement/etape1": lambda c: _objet_si("dossier", _champ_id(c, "ticket")),
    "recrutement/decision": lambda c: _objet_si("dossier", _champ_id(c, "ticket")),
    "clan/brouillon": _v_par_id("brouillon"),
    "clan/supprimer_brouillon": _v_par_id("brouillon"),
    #  Publier : le brouillon, ou la publication incertaine qu'on force (ouverte dans le composeur sous ce nom-là).
    "clan/publier": lambda c: [o for o in (_objet_si("brouillon", _champ_id(c)), _objet_si("evenement", _champ_id(c))) if o],
    "clan/modifier": _v_par_id("evenement"),
    "clan/annuler": _v_par_id("evenement"),
    "nettoyage/regle": lambda c: _objet_si("nettoyage", _champ_id(c, "cle")),
}
#  Les actions historiques (`/tableau/espace/action`) qui touchent un objet du site.
VERROUS_ACTIONS = {"ticket_fermer": lambda c: _objet_si("dossier", _champ_id(c, "ticket")),
                   "candidature": lambda c: _objet_si("dossier", _champ_id(c, "ticket"))}


async def _objets_ecriture(nom: str, fn, corps) -> list:
    """Les objets (clés valides) que touche une écriture. Une fonction en échec : aucun (l'écriture garde ses propres
    contrôles), et le détail part au journal."""
    if fn is None or not isinstance(corps, dict):
        return []
    try:
        r = fn(corps)
        if inspect.isawaitable(r):
            r = await r
    except Exception as ex:
        _log("[TABLEAU][E20] objet d'un verrou illisible")
        _log(f"[TABLEAU][E20:DETAIL] {nom} {type(ex).__name__} {ex}")
        return []
    return [o for o in (objet_direct(x) for x in ([r] if isinstance(r, str) else list(r or []))) if o]


_INTERNES.update({nom: {d["methode"]: _normaliser_route(nom, d)} for nom, d in {
    "direct/etat": {"methode": "GET", "fn": _route_direct_etat},
    "direct/envoi": {"methode": "POST", "fn": _route_direct_envoi, "ecriture": False, "corps_max": DIRECT_MSG_MAX},
}.items()})
#  26/10/2026 : la rubrique « Sécurité » (securite_site.py) — sessions et appareils, dernières écritures du site, refus
#  comptés, alertes, qui détient une permission dangereuse ; et le bouton d'urgence « Fermer toutes les autres sessions ».
_INTERNES.update({nom: {d["methode"]: _normaliser_route(nom, d)} for nom, d in securite_site.ROUTES_INTERNES.items()})
