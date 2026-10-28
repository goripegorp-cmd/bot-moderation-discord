"""site_equipage.py — le site de l'équipage (26/10/2026).

Le fondateur : « les personnels qui ont le rôle du clan [doivent] avoir accès au site pour regarder justement cette
zone-là. Eux, ils n'auront que ça […] Ils pourront voir leur fiche personnelle et la fiche de tout l'équipage, mais
ils ne pourront rien modifier […] Fais en sorte que la direction et le fondateur puissent modifier même ce qui existe
déjà à sa sauce […] une page d'accueil dédiée à la piraterie. Avec un vrai système d'analyse, d'actualité. »

L'ACCÈS (le portier reste `tableau.py` : `_verifier(…, portees=…)` refuse une session « equipage » PAR DÉFAUT)
  · Le bouton « Le site de l'équipage » du guide du clan (`section_guide`, persistant) donne un lien personnel,
    signé, à usage unique, de portée « equipage » — aux SEULS membres du rôle du clan (réglages Rell Seas). Le
    fondateur et la direction reçoivent leur lien habituel (« tout ») : la même page, avec le mode édition.
  · Une session « equipage » n'atteint que `/tableau/equipage/`, les lectures de `LECTURES`
    (`/tableau/equipage/api/…`), les images que ces lectures citent (`medias_permis`), les fichiers publics de
    `site/` et la déconnexion. Tout le reste répond 403. Le rôle du clan perdu : sa session est fermée.
  · Les lectures NETTOIENT : d'une affiche, seulement ce qu'elle montre (nom, surnom, prime, niveau, grade, statut,
    insignes, portrait) — jamais les notes de la direction, l'historique, qui a modifié quoi, un identifiant.

L'ACCUEIL (composé par la direction : `ROUTES_SITE`, écritures de la tête seule, chacune au journal du site)
  · Des blocs rangés : bandeau (titre, image), texte, image, actualités, événements à venir, équipiers à l'honneur,
    analyses. Chacun se modifie, se déplace, se masque, se supprime. Un contenu de départ est posé UNE fois (jamais
    reposé s'il a été effacé) ; chaque bloc porte une version (deux écrans ne s'écrasent jamais : 409).
  · Les actualités : celles de la direction (titre, texte, image, épinglée) et les automatiques — annonces et
    événements publiés du clan, recrues acceptées, nouvelles affiches.
  · Les analyses : calculées ici, depuis les affiches, le rôle du clan, le recrutement et les événements.

Les textes (la page, les actualités automatiques, le lien sur Discord, la ligne du guide du clan) sont DÉCLARÉS dans
le registre `textes.py` : la direction les réécrit dans Capitainerie → Textes & noms (famille « Le site de
l'équipage », et « Le guide du clan » pour sa ligne). La page reçoit les siens par `depart` (sa propre lecture : la
portée « equipage » n'entre jamais dans `textes/site`).
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import re
import secrets
import time
from collections import Counter
from datetime import datetime

import discord
from discord.ui import Button

import affiches
import diag
import hierarchie
import recrutements
import rellseas_panneau
import tableau
import textes
from ui_v2 import LayoutView, Palette

# ═══════════════════════════════════════════════════════════════════════════════
#  Réglages
# ═══════════════════════════════════════════════════════════════════════════════

TYPES_BLOC = ("bandeau", "texte", "image", "actualites", "evenements", "honneur", "analyses")
PARTIES_ANALYSES = ("membres", "metiers", "races", "factions", "grades", "statuts", "primes", "niveaux", "recrues",
                    "evenements")
FORMAT_ID = re.compile(r"[A-Za-z0-9_-]{6,32}")
FORMAT_MEDIA = re.compile(r"(?:media/)?([A-Za-z0-9_-]{16})")
BLOCS_MAX = 24
ACTUALITES_MAX = 500            # gardées en base (au-delà : retirer les anciennes d'abord)
ACTUALITES_LUES = 40            # envoyées à la page : les épinglées, puis les plus récentes
AUTO_JOURS = 90                 # la fenêtre des actualités automatiques (annonces, événements, recrues)
AFFICHES_NEUVES_JOURS = 45      # « Nouvelle affiche » : créée depuis moins de 45 jours
HONNEUR_MAX = 6
EVENEMENTS_LUS = 8
TEXTE_AUTO_MAX = 600            # caractères d'une annonce reprise en actualité
PERMIS_FRAIS = 20               # s : la liste des images permises à l'équipage, gardée en mémoire
AVIS_S = 180.0                  # le lien personnel (message pour soi) s'efface au bout de 3 minutes
STATUTS_AFFICHE = {"actif": "En service", "en_mer": "En mer", "absent": "Absent", "ancien": "Ancien de l'équipage"}

_get_db = None
_cfg = None
_log = print
_verrou = None
_permis: dict = {}              # serveur → (heure, ensemble des images permises)
_taches: set = set()
_generations: dict = {}         # serveur → compteur des écritures (la vitrine publique renouvelle ses réponses)
PUBLICS_DEPART = ("bandeau", "texte")   # au départ, sur la vitrine : le bandeau et le code de l'équipage


def _t(g, cle: str, **valeurs) -> str:
    """Un texte du site de l'équipage (registre `textes.py`) : celui de ce serveur, sinon celui d'origine."""
    return textes.texte_cache(getattr(g, "id", g) or 0, cle, **valeurs)


#  Les textes déclarés au registre : (clé, texte d'origine, titre dans l'onglet, aide, longueur, sur une ligne, partie,
#  variables). La famille « equipage_site » ; la ligne du guide du clan dans la famille du guide (« guide. » : le guide
#  se réécrit quand elle change).
GROUPE = "equipage_site"
textes.nommer_groupe(GROUPE, "Le site de l'équipage", 50)
_ONGLETS, _PAGES, _FIN, _AUTO, _LIEN, _VITRINE = ("Les trois onglets", "Les pages", "Le pied de page et les adieux",
                                                  "Les actualités automatiques", "Le lien sur Discord",
                                                  "La vitrine publique")
TEXTES = (
    ("titre", "L'Équipage", "Le nom du site", "En haut de la page, à côté du médaillon.", 40, True, _ONGLETS, ()),
    ("onglet.accueil", "Accueil", "L'onglet « Accueil »", "Sur sa pancarte.", 30, True, _ONGLETS, ()),
    ("onglet.accueil.sous", "Le pont du navire", "L'onglet « Accueil » · le sous-titre", "La petite ligne de la pancarte.",
     40, True, _ONGLETS, ()),
    ("onglet.equipage", "L'équipage", "L'onglet « L'équipage »", "Sur sa pancarte.", 30, True, _ONGLETS, ()),
    ("onglet.equipage.sous", "Toutes les affiches", "L'onglet « L'équipage » · le sous-titre",
     "La petite ligne de la pancarte.", 40, True, _ONGLETS, ()),
    ("onglet.fiche", "Ma fiche", "L'onglet « Ma fiche »", "Sur sa pancarte.", 30, True, _ONGLETS, ()),
    ("onglet.fiche.sous", "Mon avis de recherche", "L'onglet « Ma fiche » · le sous-titre",
     "La petite ligne de la pancarte.", 40, True, _ONGLETS, ()),
    ("accueil.phrase", "Les nouvelles du bord, les sorties en mer et l'équipage en chiffres.", "L'accueil · la phrase",
     "Sous le titre de l'accueil, quand aucun bandeau ne l'ouvre.", 160, True, _PAGES, ()),
    ("equipage.phrase", "Les équipes du clan, leur chef en tête, et l'avis de recherche de chaque pirate.", "L'équipage · la phrase",
     "Sous le titre de la page des affiches.", 160, True, _PAGES, ()),
    ("fiche.phrase", "Ton avis de recherche, tel que tout l'équipage le voit.", "Ma fiche · la phrase",
     "Sous le titre de la page « Ma fiche ».", 160, True, _PAGES, ()),
    ("fiche.vide.titre", "Pas encore d'affiche", "Ma fiche · sans affiche, le titre",
     "Ce que lit un membre qui n'a pas encore son affiche.", 60, True, _PAGES, ()),
    ("fiche.vide.texte", "Demande à la direction : elle crée ton avis de recherche.", "Ma fiche · sans affiche, la phrase",
     "Sous le titre précédent.", 200, True, _PAGES, ()),
    ("pied.lecture", "Lecture seule : rien ne se modifie ici.", "Le pied de page · l'équipage",
     "En bas de chaque page, pour les membres du clan.", 160, True, _FIN, ()),
    ("pied.edition", "Tu peux composer l'accueil : bouton « Modifier l'accueil ».", "Le pied de page · la direction",
     "En bas de chaque page, pour le fondateur et la direction.", 160, True, _FIN, ()),
    ("adieu.titre", "Bon vent, matelot", "La déconnexion · le titre", "Après « Se déconnecter ».", 60, True, _FIN, ()),
    ("adieu.texte", "Tu es déconnecté. Pour revenir : le guide du clan sur Discord, « Le site de l'équipage ».",
     "La déconnexion · la phrase", "Sous le titre précédent.", 300, True, _FIN, ()),
    ("retire.titre", "Accès retiré", "L'accès retiré · le titre",
     "Quand la session finit (rôle du clan retiré, lien expiré…).", 60, True, _FIN, ()),
    ("retire.texte", "Ce site est réservé à l'équipage. Pour revenir : le guide du clan sur Discord.",
     "L'accès retiré · la phrase", "Sous le titre précédent.", 300, True, _FIN, ()),
    ("auto.recrue", "{nom} rejoint l'équipage", "Une recrue acceptée", "Une actualité automatique.", 120, True, _AUTO,
     (("nom", "le nom de la recrue"),)),
    ("auto.affiche", "Nouvelle affiche : {nom}", "Une nouvelle affiche", "Une actualité automatique.", 120, True, _AUTO,
     (("nom", "le nom sur l'affiche"),)),
    ("auto.annule", "Annulé : {titre}", "Un événement annulé", "Une actualité automatique.", 140, True, _AUTO,
     (("titre", "le titre de l'événement"),)),
    ("lien.texte", "**Ton lien personnel** : il ne s'ouvre qu'une fois. Ne le partage pas.\n-# Your personal link: it "
                   "opens once. Don't share it.", "Le lien personnel", "Le message pour soi, après le bouton du guide.",
     600, False, _LIEN, ()),
    ("lien.bouton", "Ouvrir le site de l'équipage", "Le lien personnel · le bouton", "Il ouvre le site.", 80, True, _LIEN,
     ()),
    ("lien.reserve", "Réservé aux membres de l'équipage : il faut le rôle du clan.", "Le refus",
     "Pour quelqu'un qui n'a pas le rôle du clan.", 300, True, _LIEN, ()),
    #  27/10/2026 : la vitrine publique (`site_vitrine.py`, `/equipage`) et l'aperçu de son lien dans Discord.
    ("vitrine.phrase", "Les avis de recherche de tout l'équipage, rangés par métier.", "La vitrine · la phrase du mur",
     "Sous le titre du mur des affiches, sur la vitrine publique.", 160, True, _VITRINE, ()),
    ("vitrine.vide", "Les avis de recherche arrivent bientôt.", "La vitrine · sans affiche",
     "Quand aucune affiche n'est montrée sur la vitrine.", 160, True, _VITRINE, ()),
    ("vitrine.pied", "La vitrine de l'équipage : ce que la direction choisit de montrer.", "La vitrine · le pied de page",
     "En bas de la vitrine publique.", 200, True, _VITRINE, ()),
    ("vitrine.membre", "Membre du clan ? Ton accès personnel : le guide du clan sur Discord.",
     "La vitrine · pour les membres", "Sous le pied de page de la vitrine.", 200, True, _VITRINE, ()),
    ("vitrine.og.titre", "{titre} · {clan}", "L'aperçu du lien · le titre",
     "Le titre de la carte quand le lien de la vitrine est collé dans Discord.", 100, True, _VITRINE,
     (("titre", "le nom du site"), ("clan", "« Clan » et le nom du clan"))),
    ("vitrine.og.description", "{pirates} pirates, leurs avis de recherche et le code de l'équipage. Viens voir à quoi "
                               "ressemble notre équipage.", "L'aperçu du lien · la phrase",
     "Sous le titre de la carte, dans Discord.", 300, True, _VITRINE, (("pirates", "le nombre d'affiches montrées"),)),
    ("vitrine.banniere", "{pirates} pirates · {primes} berrys de primes", "L'aperçu du lien · la ligne de l'image",
     "Sur l'image de la carte, sous le nom du clan.", 100, True, _VITRINE,
     (("pirates", "le nombre d'affiches montrées"), ("primes", "le total de leurs primes"))),
)
for _k, (_cle, _defaut, _titre, _aide, _max, _ligne, _partie, _vars) in enumerate(TEXTES):
    textes.declarer(f"{GROUPE}.{_cle}", _defaut, groupe=GROUPE, titre=_titre, aide=_aide, max_=_max, lignes=not _ligne,
                    partie=_partie, variables=_vars, ordre=10 + _k)
#  Le bouton « Copier le lien de l'équipage » est AUSSI sur le site de la direction : des clés « site. » (servies à la
#  page de la direction par `textes/site`), rangées dans cette famille.
LIEN_PUBLIC = (("site.equipage.lien", "Copier le lien de l'équipage", "Le bouton « Copier le lien de l'équipage »",
                "En haut à droite des deux sites et de la vitrine : il copie l'adresse publique de la vitrine.", 60),
               ("site.equipage.lien.copie", "Lien copié", "Le bouton « Copier le lien » · l'avis",
                "Ce que le site dit une fois le lien copié.", 60),
               ("site.equipage.lien.repli", "Copie ce lien pour le partager :", "Le bouton « Copier le lien » · sans "
                "presse-papiers", "Quand le navigateur refuse la copie : le lien est montré, prêt à copier.", 100),
               ("site.equipage.ancien", "Ancien membre · masquée de la vitrine", "L'affiche d'un ancien membre",
                "Dans l'atelier des affiches : son membre n'a plus le rôle du clan (ou a quitté le serveur). Elle reste là, "
                "et revient sur la vitrine s'il revient au clan.", 60))
for _k, (_cle, _defaut, _titre, _aide, _max) in enumerate(LIEN_PUBLIC):
    textes.declarer(_cle, _defaut, groupe=GROUPE, titre=_titre, aide=_aide, max_=_max, lignes=False, partie=_VITRINE,
                    ordre=200 + _k)
#  Les équipes du clan (27/10/2026) : leurs noms se lisent sur les trois pages (la direction, l'équipage, la vitrine) —
#  des clés « site. », rangées dans cette famille.
NOMS_EQUIPES = (("site.equipes.titre", "Les équipes", "Les équipes · le titre", "Sur le site de l'équipage et la vitrine.", 40),
                ("site.equipes.phrase", "Chaque équipe, son chef d'équipe et les matelots qu'il a sous sa main.",
                 "Les équipes · la phrase", "Sous le titre des équipes.", 160),
                ("site.equipes.chef", "Chef d'équipe", "Le chef d'équipe · son titre",
                 "Sur l'insigne du chef, partout où il paraît.", 40),
                ("site.equipes.sans", "Sans équipe", "Les membres sans équipe · le titre", "Le dernier groupe.", 40),
                ("site.equipes.mon", "Mon équipe", "« Mon équipe » · le titre", "Sur « Ma fiche », pour chaque membre d'une "
                 "équipe.", 40),
                ("site.equipes.sous_main", "Sous ta main", "« Mon équipe » · pour le chef",
                 "Ce que lit le chef au-dessus des membres de son équipe.", 60),
                ("site.equipes.aucune", "Pas encore d'équipe : la direction forme les équipes.", "Sans équipe · « Ma fiche »",
                 "Ce que lit un membre qui n'est dans aucune équipe.", 160))
for _k, (_cle, _defaut, _titre, _aide, _max) in enumerate(NOMS_EQUIPES):
    textes.declarer(_cle, _defaut, groupe=GROUPE, titre=_titre, aide=_aide, max_=_max, lignes=False,
                    partie="Les équipes", ordre=300 + _k)
textes.declarer("guide.site.texte", "### Le site de l'équipage · Crew website\nTon avis de recherche, tout l'équipage, les "
                "nouvelles et les chiffres du clan, en lecture seule. La vitrine, elle, est publique : partage-la.\n-# "
                "Your WANTED poster, the whole crew, clan news and stats, read-only. The showcase is public: share it.",
                groupe="guide", titre="Le site de l'équipage", partie="Le bas du guide", ordre=35, max_=800,
                aide="Sa ligne dans le guide (pour les membres du rôle du clan) : un lien personnel au site, et le lien "
                     "public de la vitrine.")
textes.declarer("guide.site.bouton", "Ouvrir · Open", groupe="guide", titre="Le site de l'équipage · le bouton",
                partie="Le bas du guide", ordre=36, max_=80, lignes=False, aide="Il donne le lien personnel, pour soi.")
textes.declarer("guide.vitrine.bouton", "La vitrine · Showcase", groupe="guide",
                titre="Le site de l'équipage · le bouton de la vitrine", partie="Le bas du guide", ordre=37, max_=80,
                lignes=False, aide="À côté du précédent : il ouvre la vitrine publique de l'équipage (le lien à partager).")
#  Les clés que la page lit (`depart`) : la famille, sauf ce qui ne sert qu'au bot (le lien, les actualités, l'aperçu
#  du lien dans Discord), et les libellés du bouton « Copier le lien ».
PAGE = tuple(f"{GROUPE}.{cle}" for cle, *_r in TEXTES
             if not cle.startswith(("lien.", "auto.", "vitrine.og.", "vitrine.banniere"))) + tuple(c for c, *_r in LIEN_PUBLIC) \
    + tuple(c for c, *_r in NOMS_EQUIPES)
#  Les noms « site. » que les pages de l'équipage et la vitrine lisent par `libelle` (seulement ceux-là).
PREFIXES_LIBELLES = ("site.affiche.", "site.equipage.", "site.equipes.", "site.hierarchie.")


def libelles_page(g) -> dict:
    """Les noms « site. » de ces pages, tels que ce serveur les a (réécrits, sinon d'origine)."""
    renommes = textes.valeurs_site(getattr(g, "id", g) or 0)
    return {k: v for k, v in renommes.items() if k.startswith(PREFIXES_LIBELLES)}


def textes_page(g) -> dict:
    """Les libellés de la page, tels que ce serveur les a (réécrits, sinon d'origine) : servis par `depart`."""
    return {cle: _t(g, cle) for cle in PAGE}


def setup(*, get_db, cfg, log=None):
    """`cfg(guild_id)` (async) : les réglages du serveur (le rôle du clan : `rellseas_panneau.CLE_ROLE_CIBLE`)."""
    global _get_db, _cfg, _log
    _get_db, _cfg, _log = get_db, cfg, log or print
    _permis.clear()


def _signaler(code: str, message: str, ex=None, detail: str = "") -> None:
    """Un message STABLE (le tableau des erreurs ne sature pas), le détail sur une ligne à part."""
    _log(f"[EQUIPAGE][{code}] {message}")
    _log(f"[EQUIPAGE][{code}:DETAIL] {detail} {type(ex).__name__ + ' ' + str(ex) if ex is not None else ''}".rstrip())
    if ex is not None:
        diag.compter("equipage", code, ex)


def _verrou_ecriture() -> asyncio.Lock:
    """Une écriture à la fois (lire la version, la comparer, écrire). Un verrou par boucle d'évènements."""
    global _verrou
    boucle = asyncio.get_running_loop()
    if _verrou is None or _verrou[0] is not boucle:
        _verrou = (boucle, asyncio.Lock())
    return _verrou[1]


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS equipage_blocs (guild_id INTEGER NOT NULL, id TEXT NOT NULL, type TEXT NOT NULL,"
            " ordre INTEGER NOT NULL DEFAULT 0, visible INTEGER NOT NULL DEFAULT 1, contenu TEXT NOT NULL DEFAULT '{}',"
            " version INTEGER NOT NULL DEFAULT 1, cree_le INTEGER NOT NULL, cree_par INTEGER NOT NULL DEFAULT 0,"
            " maj_le INTEGER NOT NULL, maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, id))")
        #  27/10/2026 : la vitrine publique — un bloc « public » s'y montre. Une base d'avant (sans la colonne) : le
        #  bandeau et le premier texte (le code de l'équipage, au départ) deviennent publics, le reste reste privé.
        async with db.execute("PRAGMA table_info(equipage_blocs)") as cur:
            colonnes = {r[1] for r in await cur.fetchall()}
        if "public" not in colonnes:
            await db.execute("ALTER TABLE equipage_blocs ADD COLUMN public INTEGER NOT NULL DEFAULT 0")
            async with db.execute("SELECT guild_id, id, type FROM equipage_blocs ORDER BY guild_id, ordre, cree_le, id") as cur:
                lignes = await cur.fetchall()
            premiers_textes = set()
            for gid, ident, type_ in lignes:
                if type_ == "bandeau" or (type_ == "texte" and gid not in premiers_textes):
                    await db.execute("UPDATE equipage_blocs SET public=1 WHERE guild_id=? AND id=?", (gid, ident))
                if type_ == "texte":
                    premiers_textes.add(gid)
        #  Les affiches retirées de la vitrine par la direction (une ligne = masquée ; aucune ligne = visible).
        await db.execute("CREATE TABLE IF NOT EXISTS equipage_vitrine (guild_id INTEGER NOT NULL, affiche_id TEXT NOT NULL,"
                         " maj_le INTEGER NOT NULL, maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, affiche_id))")
        #  Les équipes du clan : un nom, un type (« metier:<clé> » ou « libre:<libellé> »), un chef, l'ordre de la direction.
        #  Un membre est dans UNE équipe à la fois (la clé de `equipes_membres` est le membre) ; le chef n'y est pas listé.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS equipes (guild_id INTEGER NOT NULL, id TEXT NOT NULL, nom TEXT NOT NULL,"
            " type TEXT NOT NULL DEFAULT '', chef_id INTEGER NOT NULL DEFAULT 0, ordre INTEGER NOT NULL DEFAULT 0,"
            " version INTEGER NOT NULL DEFAULT 1, cree_le INTEGER NOT NULL, maj_le INTEGER NOT NULL,"
            " maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, id))")
        await db.execute("CREATE TABLE IF NOT EXISTS equipes_membres (guild_id INTEGER NOT NULL, equipe_id TEXT NOT NULL,"
                         " membre_id INTEGER NOT NULL, PRIMARY KEY (guild_id, membre_id))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_equipes_membres ON equipes_membres(guild_id, equipe_id)")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS equipage_actualites (guild_id INTEGER NOT NULL, id TEXT NOT NULL,"
            " titre TEXT NOT NULL, texte TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '',"
            " epingle INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, cree_le INTEGER NOT NULL,"
            " cree_par INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL, maj_par INTEGER NOT NULL DEFAULT 0,"
            " PRIMARY KEY (guild_id, id))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_equipage_actualites ON equipage_actualites(guild_id, cree_le)")
        #  Le contenu de départ est posé une seule fois par serveur : effacé par la direction, il ne revient pas.
        await db.execute("CREATE TABLE IF NOT EXISTS equipage_etat (guild_id INTEGER PRIMARY KEY,"
                         " depart_pose INTEGER NOT NULL DEFAULT 0)")
        await db.commit()


def pret() -> bool:
    return _get_db is not None and _cfg is not None


# ═══════════════════════════════════════════════════════════════════════════════
#  Les petits outils
# ═══════════════════════════════════════════════════════════════════════════════

async def _role_clan(g, c=None):
    c = c if c is not None else await _cfg(g.id)
    return g.get_role(int((c or {}).get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0)) if g is not None else None


def _membres_clan(role) -> list:
    return [m for m in (getattr(role, "members", None) or []) if not getattr(m, "bot", False)]


def _mois(t) -> str:
    return datetime.fromtimestamp(int(t), tableau.PARIS).strftime("%Y-%m")


def _douze_mois(maintenant: float) -> list:
    """Les douze derniers mois (« AAAA-MM »), du plus ancien au mois en cours (heure de Paris)."""
    d = datetime.fromtimestamp(int(maintenant), tableau.PARIS)
    a, m = d.year, d.month
    out = []
    for _ in range(12):
        out.append(f"{a:04d}-{m:02d}")
        a, m = (a, m - 1) if m > 1 else (a - 1, 12)
    return out[::-1]


def _media_sortie(ident: str) -> str:
    return f"media/{ident}" if ident else ""


_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿️‍"
                    "\U000E0020-\U000E007F⃣]")


def sans_emoji(texte) -> str:
    """« Aucun émoji nulle part » : retirés, espaces propres, sur une ligne."""
    return " ".join(_EMOJI.sub("", str(texte or "")).split())


def texte_discord(texte, g=None, maximum: int = TEXTE_AUTO_MAX) -> str:
    """Un texte écrit pour Discord, lisible sur le site : mentions en noms, dates en clair, sans émoji ni mise en forme
    Discord (seul le **gras** reste, la page le rend), les lignes gardées, `maximum` caractères au plus."""
    t = str(texte or "")

    def membre(m):
        x = g.get_member(int(m.group(1))) if g is not None else None
        return f"@{x.display_name}" if x is not None else "@membre"

    def salon(m):
        x = g.get_channel(int(m.group(1))) if g is not None else None
        return f"#{x.name}" if x is not None else "#salon"

    def heure(m):
        return datetime.fromtimestamp(int(m.group(1)), tableau.PARIS).strftime("%d/%m à %H:%M")
    t = re.sub(r"<@!?(\d{5,22})>", membre, t)
    t = re.sub(r"<#(\d{5,22})>", salon, t)
    t = re.sub(r"<@&\d{5,22}>", "@rôle", t)
    t = re.sub(r"<a?:\w+:\d+>", "", t)
    t = re.sub(r"<t:(\d{1,12})(?::[a-zA-Z])?>", heure, t)
    t = re.sub(r"\[([^\]\n]{1,200})\]\((?:https?://)[^)\s]{1,400}\)", r"\1", t)
    t = re.sub(r"__|~~|`|\|\|", "", t)
    lignes = []
    for ligne in t.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        ligne = re.sub(r"^\s*(?:-#|>{1,3}|#{1,3})\s*", "", ligne)
        lignes.append(" ".join(_EMOJI.sub("", ligne).split()))
    t = re.sub(r"\n{3,}", "\n\n", "\n".join(lignes)).strip()
    return t if len(t) <= maximum else t[:maximum - 1].rstrip() + "…"


# ═══════════════════════════════════════════════════════════════════════════════
#  Les affiches, nettoyées (ce qu'une affiche montre, rien d'autre)
# ═══════════════════════════════════════════════════════════════════════════════

def _type_par(types: dict, cle: str, motif: str):
    """La clé du type (« metier », « race », « faction »…) : par sa clé, sinon par son nom."""
    if cle in types:
        return cle
    for k, t in sorted(types.items(), key=lambda x: (x[1]["ordre"], x[0])):
        if re.search(motif, f"{t['champ']} {t['nom']}", re.I):
            return k
    return None


def _affiche_publique(g, a: dict, elements: dict) -> dict:
    """Une affiche telle que l'équipage la lit : jamais les notes, l'historique, qui l'a faite, un identifiant
    Discord ou Roblox (le portrait seul, par son adresse)."""
    m = g.get_member(int(a["membre_id"])) if a["membre_id"] else None
    attributs = {t: [k for k in (cles or []) if (t, k) in elements] for t, cles in (a["attributs"] or {}).items()}
    sortie = {"id": a["id"],
              "membre": {"nom": m.display_name if m is not None else (a["membre_nom"] or ""),
                         "avatar": str(m.display_avatar.with_size(128).url) if m is not None else ""},
              "roblox": {"nom": a["roblox_nom"] or "", "avatar": affiches._avatar_roblox(a["roblox_id"])},
              "surnom": a["surnom"] or "", "prime": int(a["prime"] or 0), "niveau": int(a["niveau"] or 0),
              #  27/10/2026 : le grade montré vient du rang du membre lié (hierarchie.py) ; sans membre lié, le grade écrit.
              "grade": hierarchie.grade_affiche(g, a), "statut": a["statut"] or "actif",
              "attributs": {t: ks for t, ks in attributs.items() if ks}}
    if hierarchie.connu(g):
        sortie["rang"] = hierarchie.rang_affiche(g, a)
    return sortie


def _nom_affiche(g, a: dict) -> str:
    """Le nom affiché (comme la page : le pseudo Roblox, sinon le membre, sinon le surnom)."""
    if a["roblox_nom"]:
        return a["roblox_nom"]
    m = g.get_member(int(a["membre_id"])) if a["membre_id"] else None
    return sans_emoji(m.display_name if m is not None else a["membre_nom"]) or a["surnom"] or "Inconnu"


async def _affiches_actives(g) -> list:
    return [a for a in await affiches._affiches(g.id) if not a["retire_le"]]


def _cle_tri(g, a: dict):
    return (_nom_affiche(g, a).casefold(), a["id"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Les blocs de l'accueil
# ═══════════════════════════════════════════════════════════════════════════════

_COL_BLOCS = ("id", "type", "ordre", "visible", "contenu", "version", "cree_le", "cree_par", "maj_le", "maj_par", "public")


def _ligne_bloc(r) -> dict:
    b = dict(zip(_COL_BLOCS, r))
    try:
        contenu = json.loads(b["contenu"] or "{}")
    except ValueError:
        contenu = {}
    b["contenu"] = contenu if isinstance(contenu, dict) else {}
    b["visible"] = bool(b["visible"])
    b["public"] = bool(b["public"])
    return b


async def _blocs(guild_id: int) -> list:
    async with _get_db() as db:
        async with db.execute(f"SELECT {', '.join(_COL_BLOCS)} FROM equipage_blocs WHERE guild_id=?"
                              " ORDER BY ordre, cree_le, id", (int(guild_id),)) as cur:
            return [_ligne_bloc(r) for r in await cur.fetchall()]


async def _bloc(guild_id: int, ident: str):
    async with _get_db() as db:
        async with db.execute(f"SELECT {', '.join(_COL_BLOCS)} FROM equipage_blocs WHERE guild_id=? AND id=?",
                              (int(guild_id), ident)) as cur:
            r = await cur.fetchone()
    return _ligne_bloc(r) if r else None


def depart() -> list:
    """Le contenu de départ, pirate et sobre — entièrement modifiable : (type, contenu)."""
    return [
        ("bandeau", {"titre": "L'équipage",
                     "sous_titre": "Le pavillon est hissé. Bienvenue à bord, matelot.", "image": ""}),
        ("texte", {"titre": "Le code de l'équipage",
                   "texte": "On ne laisse jamais un équipier à la mer.\n"
                            "Le butin se partage, les tempêtes aussi.\n"
                            "La parole d'un pirate vaut de l'or : on la tient.\n"
                            "Le capitaine écoute, l'équipage décide."}),
        ("actualites", {"titre": "Le journal de bord", "nombre": 5,
                        "automatiques": True}),
        ("evenements", {"titre": "Prochaines sorties en mer", "nombre": 4}),
        ("honneur", {"titre": "Équipiers à l'honneur",
                     "texte": "Les plus hautes primes de l'équipage.",
                     "affiches": []}),
        ("analyses", {"titre": "L'équipage en chiffres",
                      "parties": list(PARTIES_ANALYSES)}),
    ]


async def _assurer_depart(g) -> None:
    """Le contenu de départ, posé une fois par serveur (sous le verrou des écritures)."""
    async with _get_db() as db:
        async with db.execute("SELECT depart_pose FROM equipage_etat WHERE guild_id=?", (g.id,)) as cur:
            r = await cur.fetchone()
    if r is not None and int(r[0] or 0):
        return
    async with _verrou_ecriture():
        async with _get_db() as db:
            async with db.execute("SELECT depart_pose FROM equipage_etat WHERE guild_id=?", (g.id,)) as cur:
                r = await cur.fetchone()
            if r is not None and int(r[0] or 0):
                return
            async with db.execute("SELECT COUNT(*) FROM equipage_blocs WHERE guild_id=?", (g.id,)) as cur:
                deja = int((await cur.fetchone())[0] or 0)
            if not deja:
                t = int(time.time())
                for n, (type_, contenu) in enumerate(depart(), start=1):
                    await db.execute("INSERT INTO equipage_blocs (guild_id, id, type, ordre, visible, contenu, version,"
                                     " cree_le, cree_par, maj_le, maj_par, public) VALUES (?,?,?,?,1,?,1,?,0,?,0,?)",
                                     (g.id, secrets.token_urlsafe(8), type_, n, json.dumps(contenu, ensure_ascii=False),
                                      t, t, int(type_ in PUBLICS_DEPART)))
            await db.execute("INSERT OR REPLACE INTO equipage_etat (guild_id, depart_pose) VALUES (?, 1)", (g.id,))
            await db.commit()
    _permis.pop(g.id, None)


def _sortie_bloc(b: dict, edition: bool) -> dict:
    """Un bloc pour la page : ses images en adresse du site ; la version et l'état visible pour la direction."""
    c = dict(b["contenu"])
    if "image" in c:
        c["image"] = _media_sortie(c.get("image") or "")
    out = {"id": b["id"], "type": b["type"], "contenu": c}
    if edition:
        out.update(visible=b["visible"], version=int(b["version"]), public=b["public"])
    return out


# ─── La vérification d'un bloc ──────────────────────────────────────────────

async def _media_valide(g, v, champ: str, requis: bool = False) -> str:
    """Une image envoyée sur le site (`media/<id>` ou `<id>`) de CE serveur — ou rien."""
    if v in (None, ""):
        if requis:
            raise affiches.Invalide(champ, "Une image est attendue.")
        return ""
    m = FORMAT_MEDIA.fullmatch(str(v)) if isinstance(v, str) else None
    if m is None:
        raise affiches.Invalide(champ, "Image invalide : envoie-la d'abord.")
    async with _get_db() as db:
        async with db.execute("SELECT 1 FROM tableau_medias WHERE id=? AND guild_id=?", (m.group(1), g.id)) as cur:
            if await cur.fetchone() is None:
                raise affiches.Invalide(champ, "Image introuvable : envoie-la à nouveau.")
    return m.group(1)


async def _valider_contenu(g, type_: str, d) -> dict:
    T, E, B = affiches._texte, affiches._entier, affiches._booleen
    if not isinstance(d, dict):
        raise affiches.Invalide("contenu", "Contenu invalide.")
    if type_ == "bandeau":
        return {"titre": T(d.get("titre"), "titre", 80, requis=True), "sous_titre": T(d.get("sous_titre"), "sous_titre", 200),
                "image": await _media_valide(g, d.get("image"), "image")}
    if type_ == "texte":
        return {"titre": T(d.get("titre"), "titre", 80), "texte": T(d.get("texte"), "texte", 2500, requis=True, lignes=True)}
    if type_ == "image":
        return {"image": await _media_valide(g, d.get("image"), "image", requis=True),
                "legende": T(d.get("legende"), "legende", 200)}
    if type_ == "actualites":
        return {"titre": T(d.get("titre"), "titre", 80), "nombre": E(d.get("nombre"), "nombre", 1, 12, defaut=5),
                "automatiques": B(d.get("automatiques"), "automatiques", True)}
    if type_ == "evenements":
        return {"titre": T(d.get("titre"), "titre", 80), "nombre": E(d.get("nombre"), "nombre", 1, EVENEMENTS_LUS, defaut=4)}
    if type_ == "honneur":
        ids = d.get("affiches") or []
        if not isinstance(ids, list) or len(ids) > HONNEUR_MAX or not all(
                isinstance(x, str) and affiches.FORMAT_AFFICHE.fullmatch(x) for x in ids):
            raise affiches.Invalide("affiches", f"{HONNEUR_MAX} affiches au plus.")
        actives = {a["id"] for a in await _affiches_actives(g)}
        if any(x not in actives for x in ids):
            raise affiches.Invalide("affiches", "Une de ces affiches n'existe plus.")
        return {"titre": T(d.get("titre"), "titre", 80), "texte": T(d.get("texte"), "texte", 200),
                "affiches": list(dict.fromkeys(ids))}
    if type_ == "analyses":
        parties = d.get("parties")
        if parties is None:
            parties = list(PARTIES_ANALYSES)
        if not isinstance(parties, list) or not all(isinstance(p, str) and p in PARTIES_ANALYSES for p in parties):
            raise affiches.Invalide("parties", "Parties inconnues.")
        return {"titre": T(d.get("titre"), "titre", 80),
                "parties": [p for p in PARTIES_ANALYSES if p in parties] or list(PARTIES_ANALYSES)}
    raise affiches.Invalide("type", "Type de bloc inconnu.")


def _titre_bloc(type_: str, contenu: dict) -> str:
    noms = {"bandeau": "Bandeau", "texte": "Texte", "image": "Image", "actualites": "Actualités",
            "evenements": "Événements à venir", "honneur": "Équipiers à l'honneur", "analyses": "Analyses"}
    return str(contenu.get("titre") or contenu.get("legende") or noms.get(type_, type_))[:80]


# ═══════════════════════════════════════════════════════════════════════════════
#  Les actualités : celles de la direction, et les automatiques
# ═══════════════════════════════════════════════════════════════════════════════

_COL_ACTU = ("id", "titre", "texte", "image", "epingle", "version", "cree_le", "maj_le")


async def _actualites_direction(guild_id: int, limite: int = ACTUALITES_LUES) -> list:
    async with _get_db() as db:
        async with db.execute(f"SELECT {', '.join(_COL_ACTU)} FROM equipage_actualites WHERE guild_id=?"
                              " ORDER BY epingle DESC, cree_le DESC, id LIMIT ?", (int(guild_id), int(limite))) as cur:
            rows = await cur.fetchall()
    return [dict(zip(_COL_ACTU, r)) for r in rows]


def _sortie_actu(a: dict, edition: bool) -> dict:
    out = {"id": a["id"], "genre": "direction", "titre": a["titre"], "texte": a["texte"],
           "image": _media_sortie(a["image"]), "epingle": bool(a["epingle"]), "quand": int(a["cree_le"])}
    if edition:
        out["version"] = int(a["version"])
        out["maj"] = int(a["maj_le"])
    return out


async def _publications(g, maintenant: float, public: bool = False) -> list:
    """Les annonces et événements PUBLIÉS du clan (module des événements, s'il est là) — jamais un brouillon, ni qui
    les a écrits, ni où ils sont postés : titre, texte, image, date, lieu, réponses (des nombres). `public` (la
    vitrine) : les mentions deviennent « @membre » et « #salon » — aucun nom de Discord ne sort."""
    try:
        import evenements
    except ModuleNotFoundError:
        return []
    if not evenements.pret():
        return []
    lignes = [e for e in await evenements._tous(g.id) if e["statut"] in ("publie", "annule")]
    comptes = await evenements._comptes([e["id"] for e in lignes])
    out = []
    for e in lignes:
        v = e["valeurs"]
        image = v.get("image") if isinstance(v.get("image"), str) else ""
        n = comptes.get(e["id"], {})
        evenement = e["type"] == "evenement"
        quand = int(v.get("quand") or 0) if evenement else 0
        out.append({"id": int(e["id"]), "type": e["type"], "statut": e["statut"],
                    "titre": sans_emoji(v.get("titre")) or ("Événement" if evenement else "Annonce"),
                    "texte": texte_discord(v.get("texte"), None if public else g),
                    "image": image if FORMAT_MEDIA.fullmatch(image or "") else "",
                    "quand": quand or None, "fin": evenements._fin(v) if evenement and quand else None,
                    "lieu": sans_emoji(v.get("lieu")) if evenement else "",
                    "duree_min": int(v.get("duree_min") or 0) if evenement else 0,
                    "places": int(v.get("places") or 0) if evenement else 0,
                    "phase": ("annule" if e["statut"] == "annule" else evenements.phase_de(e, maintenant)) if evenement else "",
                    "publie": int(e["publie"] or 0) or None,
                    #  Les liens de la publication (des boutons sur Discord ; des adresses https vérifiées à l'écriture).
                    "liens": [{"nom": sans_emoji(x.get("nom")), "url": x["url"]} for x in v.get("liens") or []
                              if isinstance(x, dict) and isinstance(x.get("url"), str) and x["url"].startswith("https://")],
                    "reponses": {"d": int(n.get("d", 0)), "p": int(n.get("p", 0)), "n": int(n.get("n", 0)),
                                 "v": int(n.get("v", 0))}})
    return out


async def _recrues(g) -> list:
    """Les candidatures ACCEPTÉES (le recrutement du clan) : le nom et la date, rien d'autre."""
    try:
        cand = await recrutements.candidatures(g)
    except Exception as ex:  # sans recrutement lisible, le reste du site vit ; le détail part au journal
        _signaler("E3", "recrutement illisible", ex)
        return []
    out = []
    for d in cand.get("fiches") or []:
        if d.get("statut") != "acceptes" or not d.get("ferme"):
            continue
        m = g.get_member(int(d.get("candidat_id") or 0))
        out.append({"nom": sans_emoji(m.display_name if m is not None else d.get("nom")) or "Une recrue",
                    "quand": int(d["ferme"])})
    return out


async def actualites_auto(g, maintenant: float, publications=None, recrues=None, lignes=None) -> list:
    """Les actualités automatiques des `AUTO_JOURS` derniers jours : annonces et événements publiés, recrues
    acceptées, nouvelles affiches — la plus récente d'abord."""
    borne = maintenant - AUTO_JOURS * 86400
    publications = publications if publications is not None else await _publications(g, maintenant)
    recrues = recrues if recrues is not None else await _recrues(g)
    lignes = lignes if lignes is not None else await _affiches_actives(g)
    out = []
    for p in publications:
        quand = p["publie"] or p["quand"] or 0
        if quand < borne:
            continue
        evenement = p["type"] == "evenement"
        genre = "evenement" if evenement else "annonce"
        titre = p["titre"]
        if p["phase"] == "annule":
            titre = _t(g, f"{GROUPE}.auto.annule", titre=titre)
        out.append({"id": f"auto-pub-{p['id']}", "genre": genre, "titre": titre, "texte": p["texte"],
                    "image": _media_sortie(p["image"]), "quand": int(quand), "evenement": {
                        "quand": p["quand"], "lieu": p["lieu"], "phase": p["phase"]} if evenement else None,
                    "liens": p.get("liens") or []})
    for r in recrues:
        if r["quand"] >= borne:
            out.append({"id": f"auto-recrue-{r['quand']}-{hashlib.sha256(r['nom'].encode()).hexdigest()[:6]}",
                        "genre": "recrue", "titre": _t(g, f"{GROUPE}.auto.recrue", nom=r["nom"]), "texte": "", "image": "",
                        "quand": r["quand"]})
    for a in lignes:
        if int(a["cree_le"] or 0) >= maintenant - AFFICHES_NEUVES_JOURS * 86400:
            out.append({"id": f"auto-affiche-{a['id']}", "genre": "affiche", "titre": _t(g, f"{GROUPE}.auto.affiche", nom=_nom_affiche(g, a)),
                        "texte": f"« {a['surnom']} »" if a["surnom"] else "", "image": "", "quand": int(a["cree_le"]),
                        "affiche": a["id"]})
    out.sort(key=lambda x: -x["quand"])
    return out[:ACTUALITES_LUES]


# ═══════════════════════════════════════════════════════════════════════════════
#  Les analyses (« un vrai système d'analyse »)
# ═══════════════════════════════════════════════════════════════════════════════

def _repartition(lignes: list, type_cle, elements: dict) -> list:
    if not type_cle:
        return []
    n = Counter(k for a in lignes for k in dict.fromkeys((a["attributs"] or {}).get(type_cle) or []))
    out = []
    for k, x in n.items():
        e = elements.get((type_cle, k))
        if e is None:
            continue
        out.append({"cle": k, "nom": e["nom"], "icone": affiches._icone_servie(e["icone"]), "type": type_cle, "n": x})
    out.sort(key=lambda r: (-r["n"], r["nom"].casefold()))
    return out


def _pas_rond(maximum: int) -> int:
    for pas in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000):
        if math.ceil(maximum / pas) <= 6:
            return pas
    return 50000


def _tranches(niveaux: list) -> list:
    if not niveaux:
        return []
    pas = _pas_rond(max(niveaux))
    n = Counter((x - 1) // pas for x in niveaux)
    return [{"de": k * pas + 1, "a": (k + 1) * pas, "n": n.get(k, 0)} for k in range(max(n) + 1)]


def _mediane(valeurs: list) -> int:
    v = sorted(valeurs)
    if not v:
        return 0
    k = len(v) // 2
    return int(v[k]) if len(v) % 2 else int((v[k - 1] + v[k]) // 2)


async def analyses(g, maintenant: float | None = None, lignes=None, publications=None, recrues=None) -> dict:
    """Tout ce que le bloc « Analyses » montre — calculé ici, en nombres (aucun identifiant)."""
    t = maintenant or time.time()
    c = await _cfg(g.id)
    role = await _role_clan(g, c)
    clan = _membres_clan(role)
    lignes = lignes if lignes is not None else await _affiches_actives(g)
    types, elements = await affiches._catalogue()
    ids_clan = {m.id for m in clan}
    avec = {int(a["membre_id"]) for a in lignes if a["membre_id"]}
    primes = [int(a["prime"] or 0) for a in lignes]
    niveaux = [int(a["niveau"]) for a in lignes if int(a["niveau"] or 0) > 0]
    top = sorted((a for a in lignes if int(a["prime"] or 0) > 0), key=lambda a: (-int(a["prime"]), _cle_tri(g, a)))[:5]
    grade_t = _type_par(types, "grade", r"\bgrades?\b")
    #  27/10/2026 : le grade montré (le rang du membre lié — hierarchie.py), rangé dans l'ordre de la hiérarchie.
    st = await hierarchie.assurer(g)
    place = {r["nom"]: n for n, r in enumerate(st["rangs"])} if st else {}
    montres = [hierarchie.grade_affiche(g, a).strip() for a in lignes]
    grades = Counter(x for x in montres if x)

    def nom_grade(k):
        if k in place:
            return k
        e = elements.get((grade_t, k)) if grade_t else None
        return e["nom"] if e else sans_emoji(k.replace("_", " ")).capitalize()
    statuts = Counter((a["statut"] or "actif") for a in lignes)
    publications = publications if publications is not None else await _publications(g, t)
    recrues = recrues if recrues is not None else await _recrues(g)
    mois = _douze_mois(t)
    par_mois = Counter(_mois(r["quand"]) for r in recrues)
    evts = [p for p in publications if p["type"] == "evenement"]
    a_venir = sorted((p for p in evts if p["statut"] == "publie" and p["phase"] in ("a_venir", "en_cours")),
                     key=lambda p: p["quand"] or 0)
    passes = sorted((p for p in evts if p["statut"] == "publie" and p["phase"] == "termine"),
                    key=lambda p: -(p["quand"] or 0))[:10]
    effectif = len(clan)

    def taux(p):
        r = p["reponses"]
        return min(100, round(100 * (r["d"] + r["p"] + r["n"]) / effectif)) if effectif else None
    taux_passes = [x for x in (taux(p) for p in passes) if x is not None]
    annonces_ = [p for p in publications if p["type"] != "evenement" and p["statut"] == "publie"
                 and (p["publie"] or 0) >= t - AUTO_JOURS * 86400]
    vus = [min(100, round(100 * p["reponses"]["v"] / effectif)) for p in annonces_ if effectif]
    return {
        "membres": {"clan": effectif, "affiches": len(lignes), "sans_affiche": len(ids_clan - avec),
                    "hors_clan": len([a for a in lignes if a["membre_id"] and int(a["membre_id"]) not in ids_clan])},
        "metiers": _repartition(lignes, _type_par(types, "metier", r"m[ée]tier"), elements),
        "races": _repartition(lignes, _type_par(types, "race", r"\braces?\b"), elements),
        "factions": _repartition(lignes, _type_par(types, "faction", r"\bfactions?\b"), elements),
        "grades": sorted(({"cle": k, "nom": nom_grade(k), "n": n} for k, n in grades.items()),
                         key=lambda r: (place.get(r["cle"], len(place)), -r["n"], r["nom"].casefold())),
        "statuts": sorted(({"cle": k, "nom": STATUTS_AFFICHE.get(k, sans_emoji(k).capitalize() or "En service"), "n": n}
                           for k, n in statuts.items()), key=lambda r: (-r["n"], r["nom"].casefold())),
        "primes": {"total": sum(primes), "moyenne": round(sum(primes) / len(primes)) if primes else 0,
                   "mediane": _mediane(primes), "max": max(primes) if primes else 0,
                   "top": [{"affiche": a["id"], "nom": _nom_affiche(g, a), "prime": int(a["prime"])} for a in top]},
        "niveaux": {"moyen": round(sum(niveaux) / len(niveaux)) if niveaux else 0, "max": max(niveaux) if niveaux else 0,
                    "renseignes": len(niveaux), "tranches": _tranches(niveaux)},
        "recrues": {"mois": mois, "par_mois": {k: par_mois.get(k, 0) for k in mois},
                    "total_12": sum(par_mois.get(k, 0) for k in mois),
                    "trente_jours": sum(1 for r in recrues if r["quand"] >= t - 30 * 86400)},
        "evenements": {"a_venir": len(a_venir),
                       "prochain": {"titre": a_venir[0]["titre"], "quand": a_venir[0]["quand"]} if a_venir else None,
                       "passes": len(passes), "taux_reponse": round(sum(taux_passes) / len(taux_passes)) if taux_passes else None,
                       "annonces": len(annonces_), "taux_vu": round(sum(vus) / len(vus)) if vus else None},
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Les équipes du clan (27/10/2026) : un nom, un type (un métier, ou un libellé), un chef, ses membres
# ═══════════════════════════════════════════════════════════════════════════════
#  Le fondateur : « le chef d'équipe, on peut aussi lui attribuer une équipe sur le site que lui-même, il verra dans
#  l'équipage […] ceux qui ouvriront la liste des équipages, ils verront le chef d'équipe […] trier par type d'équipe.
#  Et en fonction de la hiérarchie. » La hiérarchie est celle qui EXISTE : le chef d'abord, puis l'ordre des grades du
#  catalogue (un type « grade », s'il y en a un), puis le rang de prime, puis le nom. Rien d'inventé.

EQUIPES_MAX = 60
EQUIPE_MEMBRES_MAX = 250
_badges_chef = None   # (guild_id) → {membre_id: libellé} (ou sa coroutine) — rien par défaut


def brancher_badges_chef(fn) -> None:
    """Le fournisseur des badges du sélecteur de chef (les chefs validés par le recrutement : « Chef validé · métier »),
    proposés en premier. `fn(guild_id)` rend `{membre_id: libellé}` (ou une coroutine qui le rend)."""
    global _badges_chef
    _badges_chef = fn


async def badges_chef(guild_id: int) -> dict:
    """{identifiant (texte): libellé} — vide sans fournisseur, ou s'il échoue (le détail part au journal)."""
    if _badges_chef is None:
        return {}
    try:
        r = _badges_chef(int(guild_id))
        if inspect.isawaitable(r):
            r = await r
    except Exception as ex:   # le sélecteur reste utilisable, sans badges
        _signaler("E21", "badges des chefs illisibles", ex)
        return {}
    if not isinstance(r, dict):
        return {}
    return {str(k): sans_emoji(v)[:60] for k, v in r.items() if str(k).isdigit() and isinstance(v, str) and v.strip()}


_COL_EQUIPES = ("id", "nom", "type", "chef_id", "ordre", "version", "cree_le", "maj_le", "maj_par")


async def _equipes(guild_id: int) -> list:
    """Les équipes (l'ordre de la direction), chacune avec ses membres (identifiants, le chef à part)."""
    async with _get_db() as db:
        async with db.execute(f"SELECT {', '.join(_COL_EQUIPES)} FROM equipes WHERE guild_id=? ORDER BY ordre, cree_le, id",
                              (int(guild_id),)) as cur:
            equipes = [dict(zip(_COL_EQUIPES, r)) for r in await cur.fetchall()]
        async with db.execute("SELECT equipe_id, membre_id FROM equipes_membres WHERE guild_id=?", (int(guild_id),)) as cur:
            liens = await cur.fetchall()
    par_equipe: dict = {}
    for eid, mid in liens:
        par_equipe.setdefault(eid, []).append(int(mid))
    for e in equipes:
        e["chef_id"] = int(e["chef_id"] or 0)
        e["membres"] = [m for m in par_equipe.get(e["id"], []) if m != e["chef_id"]]
    return equipes


def _type_metier(types: dict):
    return _type_par(types, "metier", r"m[ée]tier")


def type_equipe(brut: str, elements: dict, tm) -> dict | None:
    """Le type d'une équipe tel que les pages le montrent : {genre, cle?, nom, icone?} — ou None."""
    brut = str(brut or "")
    if brut.startswith("metier:"):
        cle = brut[7:]
        e = elements.get((tm, cle)) if tm else None
        return {"genre": "metier", "cle": cle, "nom": e["nom"] if e else sans_emoji(cle.replace("_", " ")).capitalize(),
                "icone": affiches._icone_servie(e["icone"]) if e else ""}
    if brut.startswith("libre:") and brut[6:].strip():
        return {"genre": "libre", "nom": brut[6:]}
    return None


def rangs_grades(types: dict, elements: dict) -> dict:
    """{clé de grade: rang} — l'ordre des grades du catalogue (un type « grade »), s'il y en a un ; sinon vide."""
    gt = _type_par(types, "grade", r"\bgrades?\b")
    if not gt:
        return {}
    els = sorted((e for (t, _k), e in elements.items() if t == gt), key=lambda e: (int(e["ordre"]), e["nom"].casefold()))
    return {e["cle"]: n for n, e in enumerate(els)}


def cle_hierarchie(a, nom: str, rangs: dict) -> tuple:
    """La hiérarchie EXISTANTE d'un membre : son grade (ordre du catalogue), puis sa prime (rang de prime), puis son nom.
    Sans affiche : après tous ceux qui en ont une."""
    if a is None:
        return (2, 0, 0, nom.casefold())
    rang = rangs.get(a["grade"]) if a["grade"] else None
    return (0 if rang is not None else 1, rang if rang is not None else 0, -int(a["prime"] or 0), nom.casefold())


async def _valider_equipe(g, corps) -> dict:
    """Une équipe saisie par la direction : nom, type (un métier du catalogue ou un libellé), chef et membres (du clan)."""
    T = affiches._texte
    nom = T(corps.get("nom"), "nom", 60, requis=True)
    t = corps.get("type")
    if t in (None, "", {}):
        type_ = ""
    elif isinstance(t, dict) and t.get("genre") == "metier":
        types, elements = await affiches._catalogue()
        tm, cle = _type_metier(types), t.get("cle")
        if not tm or not isinstance(cle, str) or (tm, cle) not in elements:
            raise affiches.Invalide("type", "Ce métier n'est pas au catalogue.")
        type_ = f"metier:{cle}"
    elif isinstance(t, dict) and t.get("genre") == "libre":
        type_ = "libre:" + T(t.get("texte"), "type", 40, requis=True)
    else:
        raise affiches.Invalide("type", "Type d'équipe invalide : un métier, ou un libellé.")
    clan = {m.id for m in _membres_clan(await _role_clan(g))}
    chef = corps.get("chef")
    chef_id = 0
    if chef not in (None, "", 0, "0"):
        chef_id = int(chef) if isinstance(chef, (str, int)) and str(chef).isdigit() else -1
        if chef_id not in clan:
            raise affiches.Invalide("chef", "Le chef d'équipe doit être un membre du clan.")
    brut = corps.get("membres") or []
    if not isinstance(brut, list) or len(brut) > EQUIPE_MEMBRES_MAX:
        raise affiches.Invalide("membres", f"{EQUIPE_MEMBRES_MAX} membres au plus.")
    membres = []
    for x in brut:
        if not isinstance(x, (str, int)) or isinstance(x, bool) or not str(x).isdigit():
            raise affiches.Invalide("membres", "Membre invalide.")
        if int(x) not in clan:
            raise affiches.Invalide("membres", "Un de ces membres n'est plus au clan.")
        if int(x) != chef_id and int(x) not in membres:
            membres.append(int(x))
    return {"nom": nom, "type": type_, "chef_id": chef_id, "membres": membres}


def _nom_membre(g, mid: int) -> str:
    m = g.get_member(int(mid)) if mid else None
    return sans_emoji(m.display_name) if m is not None else "Membre parti"


async def equipes_direction(g) -> dict:
    """Pour le site de la direction (`GET equipage/equipes`) : les équipes, les métiers proposés comme type, et les badges
    du sélecteur de chef."""
    types, elements = await affiches._catalogue()
    tm = _type_metier(types)

    def personne(mid):
        return {"id": str(mid), "nom": _nom_membre(g, mid), "present": g.get_member(int(mid)) is not None}
    sortie = []
    for e in await _equipes(g.id):
        t = type_equipe(e["type"], elements, tm)
        saisie = ({"genre": "metier", "cle": t["cle"]} if t and t["genre"] == "metier"
                  else {"genre": "libre", "texte": t["nom"]} if t else None)
        sortie.append({"id": e["id"], "nom": e["nom"], "type": t, "saisie_type": saisie,
                       "chef": personne(e["chef_id"]) if e["chef_id"] else None,
                       "membres": [personne(m) for m in e["membres"]], "ordre": int(e["ordre"]),
                       "version": int(e["version"]), "maj_le": int(e["maj_le"])})
    metiers = sorted(((k, e) for (t, k), e in elements.items() if tm and t == tm and e["actif"]),
                     key=lambda x: (int(x[1]["ordre"]), x[1]["nom"].casefold()))
    return {"equipes": sortie, "badges": await badges_chef(g.id),
            "metiers": [{"cle": k, "nom": e["nom"], "icone": affiches._icone_servie(e["icone"])} for k, e in metiers]}


async def equipes_lues(g, lignes: list, *, publiques=None) -> dict:
    """Les équipes telles que l'équipage (ou la vitrine) les lit, chacun rangé par la hiérarchie existante.
    `lignes` : les affiches montrées. `publiques` (la vitrine) : {id d'affiche: jeton} — une personne n'y paraît QUE par
    son affiche montrée (aucun nom Discord, aucun avatar) ; sinon (l'équipage) : son nom et son avatar Discord aussi.
    Rend {"equipes": [...], "sans_equipe": [...] (l'équipage seulement), "chefs": {membre: équipe}, "places": {membre: équipe}}."""
    types, elements = await affiches._catalogue()
    tm, rangs = _type_metier(types), rangs_grades(types, elements)
    equipes = await _equipes(g.id)
    affiche_de = {int(a["membre_id"]): a for a in lignes if a["membre_id"]}
    clan = _membres_clan(await _role_clan(g))
    tous = {m.id: m for m in clan}
    #  27/10/2026 : « le tri par hiérarchie suit l'ordre des rangs partout » — le rang (hierarchie.py) d'abord, puis la
    #  hiérarchie d'avant (le grade du catalogue, la prime, le nom). Sans hiérarchie lue : comme avant.
    avec_rangs = await hierarchie.assurer(g) is not None
    pour_tous = sorted({e["chef_id"] for e in equipes if e["chef_id"]} | {m for e in equipes for m in e["membres"]}
                       | (set(tous) if publiques is None else set()),
                       key=lambda mid: (hierarchie.ordre_de(g, mid),
                                        *cle_hierarchie(affiche_de.get(mid), _nom_membre(g, mid), rangs)))
    rang_de = {mid: n for n, mid in enumerate(pour_tous)}

    def personne(mid):
        a = affiche_de.get(mid)
        if publiques is not None:
            return {"affiche": publiques[a["id"]], "h": rang_de.get(mid, 0)} if a is not None and a["id"] in publiques else None
        m = tous.get(mid) or g.get_member(int(mid))
        p = {"nom": sans_emoji(m.display_name) if m is not None else "Membre parti",
             "avatar": str(m.display_avatar.with_size(64).url) if m is not None else "",
             "affiche": a["id"] if a is not None else None, "h": rang_de.get(mid, 0)}
        if avec_rangs:   # son rang (l'identifiant d'un rang de `hierarchie`), aussi pour qui n'a pas d'affiche
            r = hierarchie.rang_de(g, mid)
            p["rang"] = r["id"] if r else ""
        return p
    sortie, places, chefs = [], {}, {}
    for n, e in enumerate(equipes, start=1):
        membres = [p for p in (personne(m) for m in sorted(e["membres"], key=lambda mid: rang_de.get(mid, 0))) if p]
        chef = personne(e["chef_id"]) if e["chef_id"] else None
        if publiques is not None and chef is None and not membres:
            continue   # la vitrine ne montre une équipe que par des affiches montrées
        t = type_equipe(e["type"], elements, tm)
        sortie.append({"id": e["id"] if publiques is None else f"q{n}", "nom": e["nom"], "type": t, "chef": chef,
                       "membres": membres})
        if e["chef_id"]:
            chefs[e["chef_id"]] = e["id"]
            places[e["chef_id"]] = e["id"]
        for m in e["membres"]:
            places[m] = e["id"]
    out = {"equipes": sortie, "chefs": chefs, "places": places}
    if publiques is None:
        out["sans_equipe"] = [personne(mid) for mid in pour_tous if mid in tous and mid not in places]
    return out


# ─── Les écritures de la direction (tête seule : `tableau._executer`) ──────────

def _sortie_equipe_conflit(e: dict, g) -> dict:
    return {"id": e["id"], "nom": e["nom"], "version": int(e["version"]),
            "chef": {"id": str(e["chef_id"]), "nom": _nom_membre(g, e["chef_id"])} if e["chef_id"] else None,
            "membres": [str(m) for m in e["membres"]]}


async def _route_equipes(g, auteur, requete, corps):
    """`GET equipage/equipes` : les équipes (site de la direction)."""
    return 200, await equipes_direction(g)


async def _route_equipe(g, auteur, requete, corps):
    """`POST equipage/equipe` `{id?, nom, type, chef, membres, version?}` : créer ou modifier une équipe. Un membre ajouté
    quitte son ancienne équipe ; le chef n'est le chef que d'UNE équipe, et jamais membre d'une autre."""
    ident = corps.get("id")
    try:
        version = affiches._entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)
        v = await _valider_equipe(g, corps)
        async with _verrou_ecriture():
            equipes = await _equipes(g.id)
            deja = None
            if ident not in (None, ""):
                if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
                    return 400, {"erreur": "Identifiant d'équipe invalide.", "champ": "id"}
                deja = next((e for e in equipes if e["id"] == ident), None)
                if deja is None:
                    return 404, {"erreur": "Cette équipe n'existe plus."}
                if version != int(deja["version"]):
                    return 409, {"conflit": True, "actuelle": _sortie_equipe_conflit(deja, g)}
            elif len(equipes) >= EQUIPES_MAX:
                return 400, {"erreur": f"{EQUIPES_MAX} équipes au plus : supprime d'abord une équipe."}
            autres = [e for e in equipes if deja is None or e["id"] != deja["id"]]
            if any(e["nom"].casefold() == v["nom"].casefold() for e in autres):
                raise affiches.Invalide("nom", "Une autre équipe porte déjà ce nom.")
            chefs = {e["chef_id"]: e for e in autres if e["chef_id"]}
            if v["chef_id"] in chefs:
                raise affiches.Invalide("chef", f"{_nom_membre(g, v['chef_id'])} est déjà chef de « {chefs[v['chef_id']]['nom']} ».")
            for m in v["membres"]:
                if m in chefs:
                    raise affiches.Invalide("membres", f"{_nom_membre(g, m)} est chef de « {chefs[m]['nom']} » : nomme d'abord "
                                                       "un autre chef là-bas.")
            personnes = set(v["membres"]) | ({v["chef_id"]} if v["chef_id"] else set())
            quittees = {e["id"] for e in autres if personnes & set(e["membres"])}
            t = int(time.time())
            async with _get_db() as db:
                if deja is None:
                    ident = secrets.token_urlsafe(8)
                    await db.execute("INSERT INTO equipes (guild_id, id, nom, type, chef_id, ordre, version, cree_le, maj_le,"
                                     " maj_par) VALUES (?,?,?,?,?,?,1,?,?,?)",
                                     (g.id, ident, v["nom"], v["type"], v["chef_id"],
                                      max([int(e["ordre"]) for e in equipes], default=0) + 1, t, t, auteur.id))
                else:
                    await db.execute("UPDATE equipes SET nom=?, type=?, chef_id=?, version=version+1, maj_le=?, maj_par=?"
                                     " WHERE guild_id=? AND id=?", (v["nom"], v["type"], v["chef_id"], t, auteur.id, g.id, ident))
                    await db.execute("DELETE FROM equipes_membres WHERE guild_id=? AND equipe_id=?", (g.id, ident))
                for m in personnes:   # une seule équipe à la fois : ils quittent l'ancienne
                    await db.execute("DELETE FROM equipes_membres WHERE guild_id=? AND membre_id=?", (g.id, m))
                for m in v["membres"]:
                    await db.execute("INSERT INTO equipes_membres (guild_id, equipe_id, membre_id) VALUES (?,?,?)", (g.id, ident, m))
                for eid in quittees:   # une équipe qui perd un membre change aussi (son éditeur ouvert le saura : 409)
                    await db.execute("UPDATE equipes SET version=version+1, maj_le=?, maj_par=? WHERE guild_id=? AND id=?",
                                     (t, auteur.id, g.id, eid))
                await db.commit()
    except affiches.Invalide as ex:
        return 400, ex.corps()
    _apres_ecriture(g)
    morceaux = [f"chef : {_nom_membre(g, v['chef_id'])}" if v["chef_id"] else "sans chef",
                f"{len(v['membres'])} membre{'s' if len(v['membres']) > 1 else ''}"]
    return 200, {"ok": True, "id": ident, **(await equipes_direction(g)),
                 "_journal": f"Équipes : « {v['nom']} » {'créée' if deja is None else 'modifiée'} ({', '.join(morceaux)})"}


async def _route_equipe_supprimer(g, auteur, requete, corps):
    """`POST equipage/equipe/supprimer` `{id}` : l'équipe part ; ses membres et son chef deviennent « sans équipe »."""
    ident = corps.get("id")
    if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'équipe invalide.", "champ": "id"}
    async with _verrou_ecriture():
        e = next((x for x in await _equipes(g.id) if x["id"] == ident), None)
        if e is not None:
            async with _get_db() as db:
                await db.execute("DELETE FROM equipes_membres WHERE guild_id=? AND equipe_id=?", (g.id, ident))
                await db.execute("DELETE FROM equipes WHERE guild_id=? AND id=?", (g.id, ident))
                await db.commit()
    _apres_ecriture(g)
    return 200, {"ok": True, **(await equipes_direction(g)),
                 "_journal": f"Équipes : « {e['nom']} » supprimée" if e is not None else None}


async def _route_equipe_deplacer(g, auteur, requete, corps):
    """`POST equipage/equipe/deplacer` `{id, sens: "haut" | "bas"}` : l'ordre des équipes (sur les trois pages)."""
    ident, sens = corps.get("id"), corps.get("sens")
    if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'équipe invalide.", "champ": "id"}
    if sens not in ("haut", "bas"):
        return 400, {"erreur": "Sens : « haut » ou « bas ».", "champ": "sens"}
    async with _verrou_ecriture():
        equipes = await _equipes(g.id)
        i = next((k for k, e in enumerate(equipes) if e["id"] == ident), None)
        if i is None:
            return 404, {"erreur": "Cette équipe n'existe plus."}
        j = i - 1 if sens == "haut" else i + 1
        bouge = 0 <= j < len(equipes)
        if bouge:
            equipes[i], equipes[j] = equipes[j], equipes[i]
            async with _get_db() as db:
                for n, e in enumerate(equipes, start=1):
                    await db.execute("UPDATE equipes SET ordre=? WHERE guild_id=? AND id=?", (n, g.id, e["id"]))
                await db.commit()
    if bouge:
        _apres_ecriture(g)
    e = equipes[j] if bouge else equipes[i]
    return 200, {"ok": True, **(await equipes_direction(g)),
                 "_journal": f"Équipes : « {e['nom']} » déplacée vers le {sens}" if bouge else None}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les lectures (`/tableau/equipage/api/<nom>`) — session « equipage » ou « tout »
# ═══════════════════════════════════════════════════════════════════════════════

async def lecture_depart(g, membre, session: dict, requete: dict):
    """`GET depart` : qui je suis (nom, portrait), le serveur, le clan, la fin de la session, le mode édition."""
    role = await _role_clan(g)
    edition = session.get("portee") == "tout"
    return 200, {
        "moi": {"nom": membre.display_name if membre is not None else "",
                "avatar": str(membre.display_avatar.with_size(64).url) if membre is not None else ""},
        "edition": edition, "expire": int(session.get("expire") or 0),
        "serveur": {"nom": getattr(g, "name", "") or "", "icone": str(g.icon.with_size(128).url) if getattr(g, "icon", None) else ""},
        "clan": sans_emoji(getattr(role, "name", "")) if role is not None else "",
        "version": tableau.version_page(), "textes": textes_page(g),
        #  Les noms des statuts et des tampons d'affiche renommés par la direction (`site/affiche.js` les lit par
        #  `libelle`) : seulement ceux-là — l'équipage n'entre pas dans `textes/site`.
        "libelles": libelles_page(g),
        "modules": {"direct": edition and (tableau.SITE / "direct.js").is_file()},
    }


async def lecture_equipage(g, membre, session: dict, requete: dict):
    """`GET equipage` : toutes les affiches (nettoyées), le catalogue qu'elles citent, et la mienne."""
    types, elements = await affiches._catalogue()
    await hierarchie.assurer(g)   # 27/10/2026 : le rang de chacun, lu avant les affiches (leur grade montré en vient)
    lignes = sorted(await _affiches_actives(g), key=lambda a: _cle_tri(g, a))
    publiques = [_affiche_publique(g, a, elements) for a in lignes]
    cites = {(t, k) for a in publiques for t, ks in a["attributs"].items() for k in ks}
    grade_t = _type_par(types, "grade", r"\bgrades?\b")
    if grade_t:
        cites |= {(grade_t, a["grade"]) for a in publiques if a["grade"]}
    moi = next((a["id"] for a in lignes if membre is not None and int(a["membre_id"] or 0) == membre.id), None)
    #  La direction (mode édition) voit aussi quelles affiches sont retirées de la vitrine publique.
    vitrine = None
    if session.get("portee") == "tout":
        #  Et celles des ANCIENS membres (plus le rôle du clan, ou partis du serveur) : jamais sur la vitrine, tant qu'ils
        #  ne reviennent pas au clan (27/10/2026).
        clan_ids = {m.id for m in _membres_clan(await _role_clan(g))}
        vitrine = {"masquees": sorted(await vitrine_masquees(g.id) & {a["id"] for a in lignes}),
                   "anciennes": sorted(a["id"] for a in lignes if a["membre_id"] and int(a["membre_id"]) not in clan_ids)}
    #  Les équipes (27/10/2026) : chacune, son chef mis en avant, ses membres par la hiérarchie existante ; la mienne.
    eq = await equipes_lues(g, lignes)
    mien = int(getattr(membre, "id", 0) or 0)
    mon = {"id": eq["places"][mien], "role": "chef" if mien in eq["chefs"] else "membre"} if mien in eq["places"] else None
    #  La hiérarchie (27/10/2026) : chaque rang, dans l'ordre, et ses membres (lecture seule) ; le mien.
    rangs = await hierarchie.vue_equipage(g, lignes)
    if rangs is not None:
        r = hierarchie.rang_de(g, mien) if mien else None
        rangs["mon_rang"] = r["id"] if r else ""
    return 200, {
        "affiches": publiques, "moi": moi, **({"vitrine": vitrine} if vitrine is not None else {}),
        **({"hierarchie": rangs} if rangs is not None else {}),
        "equipes": eq["equipes"], "sans_equipe": eq["sans_equipe"], "mon_equipe": mon,
        "catalogue": {
            "types": [{"cle": t["cle"], "nom": t["nom"], "ordre": int(t["ordre"]), "multiple": bool(t["multiple"]),
                       "champ": t["champ"]} for t in sorted(types.values(), key=lambda t: (t["ordre"], t["nom"].casefold()))],
            "elements": [{"type": e["type"], "cle": e["cle"], "nom": e["nom"], "icone": affiches._icone_servie(e["icone"]),
                          "actif": bool(e["actif"]), "ordre": int(e["ordre"])}
                         for (ty, k), e in sorted(elements.items(), key=lambda x: (x[1]["ordre"], x[1]["nom"].casefold()))
                         if (ty, k) in cites]},
    }


async def lecture_accueil(g, membre, session: dict, requete: dict):
    """`GET accueil` : les blocs (la direction voit aussi les masqués, avec leur version) et les données de ceux qui en
    demandent : actualités, événements à venir, équipiers à l'honneur, analyses."""
    edition = session.get("portee") == "tout"
    maintenant = time.time()
    await _assurer_depart(g)
    blocs = [b for b in await _blocs(g.id) if edition or b["visible"]]
    types_vus = {b["type"] for b in blocs}
    donnees: dict = {}
    lignes = await _affiches_actives(g) if types_vus & {"actualites", "honneur", "analyses"} else []
    publications = await _publications(g, maintenant) if types_vus & {"actualites", "evenements", "analyses"} else []
    recrues = await _recrues(g) if types_vus & {"actualites", "analyses"} else []
    if "actualites" in types_vus:
        donnees["actualites"] = {
            "direction": [_sortie_actu(a, edition) for a in await _actualites_direction(g.id)],
            "auto": await actualites_auto(g, maintenant, publications, recrues, lignes)}
    if "evenements" in types_vus:
        a_venir = sorted((p for p in publications if p["type"] == "evenement" and p["statut"] == "publie"
                          and p["phase"] in ("a_venir", "en_cours")), key=lambda p: p["quand"] or 0)
        donnees["evenements"] = [{k: p[k] for k in ("titre", "texte", "quand", "fin", "lieu", "duree_min", "places",
                                                    "phase", "reponses")} | {"image": _media_sortie(p["image"]),
                                                                              "id": f"ev-{p['id']}"}
                                 for p in a_venir[:EVENEMENTS_LUS]]
    if "honneur" in types_vus:
        actives = {a["id"] for a in lignes}
        auto = [a["id"] for a in sorted((a for a in lignes if int(a["prime"] or 0) > 0),
                                        key=lambda a: (-int(a["prime"]), _cle_tri(g, a)))[:3]]
        donnees["honneur"] = {b["id"]: ([x for x in b["contenu"].get("affiches") or [] if x in actives] or auto)
                              for b in blocs if b["type"] == "honneur"}
    if "analyses" in types_vus:
        donnees["analyses"] = await analyses(g, maintenant, lignes, publications, recrues)
    return 200, {"blocs": [_sortie_bloc(b, edition) for b in blocs], "donnees": donnees, "edition": edition,
                 "maintenant": int(maintenant)}


LECTURES = {"depart": lecture_depart, "equipage": lecture_equipage, "accueil": lecture_accueil}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les images que l'équipage peut voir (`tableau.media`, session « equipage »)
# ═══════════════════════════════════════════════════════════════════════════════

async def medias_permis(g) -> set:
    """Les images (`media/…`) que les lectures de l'équipage citent : portraits des affiches, icônes envoyées du
    catalogue, images des blocs VISIBLES et des actualités, images des annonces publiées. Rien d'autre."""
    t = time.time()
    deja = _permis.get(g.id)
    if deja is not None and t - deja[0] < PERMIS_FRAIS:
        return deja[1]
    lignes = await _affiches_actives(g)
    permis = {f"avatar/{int(a['roblox_id'])}" for a in lignes if a["roblox_id"]}
    permis |= await affiches.medias_utilises(g.id)
    for b in await _blocs(g.id):
        if b["visible"] and isinstance(b["contenu"].get("image"), str) and b["contenu"]["image"]:
            permis.add(b["contenu"]["image"])
    async with _get_db() as db:
        async with db.execute("SELECT image FROM equipage_actualites WHERE guild_id=? AND image != ''", (g.id,)) as cur:
            permis |= {str(r[0]) for r in await cur.fetchall()}
    permis |= {p["image"] for p in await _publications(g, t)
               if p["image"] and (p["publie"] or p["quand"] or 0) >= t - AUTO_JOURS * 86400}
    _permis[g.id] = (t, permis)
    return permis


async def medias_utilises(guild_id: int) -> set:
    """Pour le nettoyage du site : les images des blocs (même masqués) et des actualités ne partent jamais."""
    out = set()
    async with _get_db() as db:
        async with db.execute("SELECT contenu FROM equipage_blocs WHERE guild_id=?", (int(guild_id),)) as cur:
            for (brut,) in await cur.fetchall():
                try:
                    image = (json.loads(brut or "{}") or {}).get("image")
                except (ValueError, AttributeError):
                    continue
                if isinstance(image, str) and image:
                    out.add(image)
        async with db.execute("SELECT image FROM equipage_actualites WHERE guild_id=? AND image != ''",
                              (int(guild_id),)) as cur:
            out |= {str(r[0]) for r in await cur.fetchall()}
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Les écritures de la direction (`/tableau/espace/api/equipage/…`, `tableau.monter`)
# ═══════════════════════════════════════════════════════════════════════════════

async def _accueil_direction(g) -> dict:
    return (await lecture_accueil(g, None, {"portee": "tout"}, {}))[1]


def _apres_ecriture(g) -> None:
    _permis.pop(g.id, None)
    _generations[g.id] = _generations.get(g.id, 0) + 1


def generation(guild_id: int) -> int:
    """Le compteur des écritures de la direction sur ce serveur : la vitrine publique renouvelle ses réponses quand il
    change (sinon au plus tard au bout de son délai)."""
    return _generations.get(int(guild_id), 0)


async def vitrine_masquees(guild_id: int) -> set:
    """Les affiches que la direction a retirées de la vitrine publique (identifiants)."""
    async with _get_db() as db:
        async with db.execute("SELECT affiche_id FROM equipage_vitrine WHERE guild_id=?", (int(guild_id),)) as cur:
            return {str(r[0]) for r in await cur.fetchall()}


async def _route_bloc(g, auteur, requete, corps):
    """`POST equipage/bloc` `{id?, type, contenu, visible?, version?}` : ajouter (à la fin) ou modifier un bloc."""
    ident = corps.get("id")
    try:
        version = affiches._entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)
        visible = affiches._booleen(corps.get("visible"), "visible", True)
        async with _verrou_ecriture():
            deja = None
            if ident not in (None, ""):
                if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
                    return 400, {"erreur": "Identifiant de bloc invalide.", "champ": "id"}
                deja = await _bloc(g.id, ident)
                if deja is None:
                    return 404, {"erreur": "Ce bloc n'existe plus."}
            type_ = deja["type"] if deja is not None else corps.get("type")
            if type_ not in TYPES_BLOC:
                return 400, {"erreur": "Type de bloc inconnu.", "champ": "type"}
            contenu = await _valider_contenu(g, type_, corps.get("contenu"))
            if deja is not None and version != int(deja["version"]):
                return 409, {"conflit": True, "actuel": _sortie_bloc(deja, True)}
            t = int(time.time())
            async with _get_db() as db:
                if deja is None:
                    async with db.execute("SELECT COUNT(*), COALESCE(MAX(ordre), 0) FROM equipage_blocs WHERE guild_id=?",
                                          (g.id,)) as cur:
                        n, ordre = await cur.fetchone()
                    if int(n) >= BLOCS_MAX:
                        return 400, {"erreur": f"{BLOCS_MAX} blocs au plus : supprime d'abord un bloc."}
                    ident = secrets.token_urlsafe(8)
                    await db.execute("INSERT INTO equipage_blocs (guild_id, id, type, ordre, visible, contenu, version,"
                                     " cree_le, cree_par, maj_le, maj_par) VALUES (?,?,?,?,?,?,1,?,?,?,?)",
                                     (g.id, ident, type_, int(ordre) + 1, int(visible),
                                      json.dumps(contenu, ensure_ascii=False), t, auteur.id, t, auteur.id))
                else:
                    await db.execute("UPDATE equipage_blocs SET contenu=?, visible=?, version=version+1, maj_le=?,"
                                     " maj_par=? WHERE guild_id=? AND id=?",
                                     (json.dumps(contenu, ensure_ascii=False), int(visible), t, auteur.id, g.id, ident))
                await db.commit()
            bloc = await _bloc(g.id, ident)
    except affiches.Invalide as ex:
        return 400, ex.corps()
    _apres_ecriture(g)
    return 200, {"ok": True, "bloc": _sortie_bloc(bloc, True), "accueil": await _accueil_direction(g),
                 "_journal": f"Site de l'équipage : bloc « {_titre_bloc(type_, contenu)} » "
                             f"{'ajouté' if deja is None else 'modifié'}"}


async def _route_bloc_visible(g, auteur, requete, corps):
    """`POST equipage/bloc/visible` `{id, visible}` : masquer un bloc (la direction le voit encore) ou le montrer."""
    ident = corps.get("id")
    if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
        return 400, {"erreur": "Identifiant de bloc invalide.", "champ": "id"}
    try:
        visible = affiches._booleen(corps.get("visible"), "visible", True)
    except affiches.Invalide as ex:
        return 400, ex.corps()
    async with _verrou_ecriture():
        b = await _bloc(g.id, ident)
        if b is None:
            return 404, {"erreur": "Ce bloc n'existe plus."}
        if b["visible"] != visible:
            async with _get_db() as db:
                await db.execute("UPDATE equipage_blocs SET visible=?, version=version+1, maj_le=?, maj_par=?"
                                 " WHERE guild_id=? AND id=?", (int(visible), int(time.time()), auteur.id, g.id, ident))
                await db.commit()
    _apres_ecriture(g)
    return 200, {"ok": True, "accueil": await _accueil_direction(g),
                 "_journal": None if b["visible"] == visible else
                 f"Site de l'équipage : bloc « {_titre_bloc(b['type'], b['contenu'])} » {'montré' if visible else 'masqué'}"}


async def _route_bloc_public(g, auteur, requete, corps):
    """`POST equipage/bloc/public` `{id, public}` : montrer un bloc sur la vitrine publique (`/equipage`), ou l'en
    retirer. Un bloc masqué n'y paraît jamais, même public."""
    ident = corps.get("id")
    if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
        return 400, {"erreur": "Identifiant de bloc invalide.", "champ": "id"}
    try:
        public = affiches._booleen(corps.get("public"), "public", False)
    except affiches.Invalide as ex:
        return 400, ex.corps()
    async with _verrou_ecriture():
        b = await _bloc(g.id, ident)
        if b is None:
            return 404, {"erreur": "Ce bloc n'existe plus."}
        if b["public"] != public:
            async with _get_db() as db:
                await db.execute("UPDATE equipage_blocs SET public=?, version=version+1, maj_le=?, maj_par=?"
                                 " WHERE guild_id=? AND id=?", (int(public), int(time.time()), auteur.id, g.id, ident))
                await db.commit()
    _apres_ecriture(g)
    return 200, {"ok": True, "accueil": await _accueil_direction(g),
                 "_journal": None if b["public"] == public else
                 f"Site de l'équipage : bloc « {_titre_bloc(b['type'], b['contenu'])} » "
                 f"{'montré sur la vitrine publique' if public else 'retiré de la vitrine publique'}"}


async def _route_vitrine_affiche(g, auteur, requete, corps):
    """`POST equipage/vitrine/affiche` `{id, visible}` : une affiche sur la vitrine publique (par défaut), ou retirée
    (elle reste au mur du site de l'équipage)."""
    ident = corps.get("id")
    if not isinstance(ident, str) or not affiches.FORMAT_AFFICHE.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'affiche invalide.", "champ": "id"}
    try:
        visible = affiches._booleen(corps.get("visible"), "visible", True)
    except affiches.Invalide as ex:
        return 400, ex.corps()
    a = next((x for x in await _affiches_actives(g) if x["id"] == ident), None)
    if a is None:
        return 404, {"erreur": "Cette affiche n'est plus au mur."}
    async with _verrou_ecriture():
        avant = ident not in await vitrine_masquees(g.id)
        if avant != visible:
            async with _get_db() as db:
                if visible:
                    await db.execute("DELETE FROM equipage_vitrine WHERE guild_id=? AND affiche_id=?", (g.id, ident))
                else:
                    await db.execute("INSERT OR REPLACE INTO equipage_vitrine (guild_id, affiche_id, maj_le, maj_par)"
                                     " VALUES (?,?,?,?)", (g.id, ident, int(time.time()), auteur.id))
                await db.commit()
    _apres_ecriture(g)
    return 200, {"ok": True, "id": ident, "visible": visible,
                 "masquees": sorted(await vitrine_masquees(g.id)),
                 "_journal": None if avant == visible else
                 f"Site de l'équipage : affiche de {_nom_affiche(g, a)} "
                 f"{'remise sur la vitrine publique' if visible else 'retirée de la vitrine publique'}"}


async def _route_bloc_deplacer(g, auteur, requete, corps):
    """`POST equipage/bloc/deplacer` `{id, sens: "haut" | "bas"}` : échange avec son voisin (puis 1, 2, 3…)."""
    ident, sens = corps.get("id"), corps.get("sens")
    if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
        return 400, {"erreur": "Identifiant de bloc invalide.", "champ": "id"}
    if sens not in ("haut", "bas"):
        return 400, {"erreur": "Sens : « haut » ou « bas ».", "champ": "sens"}
    async with _verrou_ecriture():
        blocs = await _blocs(g.id)
        i = next((k for k, b in enumerate(blocs) if b["id"] == ident), None)
        if i is None:
            return 404, {"erreur": "Ce bloc n'existe plus."}
        j = i - 1 if sens == "haut" else i + 1
        bouge = 0 <= j < len(blocs)
        if bouge:
            blocs[i], blocs[j] = blocs[j], blocs[i]
            async with _get_db() as db:
                for n, b in enumerate(blocs, start=1):
                    await db.execute("UPDATE equipage_blocs SET ordre=? WHERE guild_id=? AND id=?", (n, g.id, b["id"]))
                await db.commit()
    if bouge:
        _apres_ecriture(g)   # l'ordre de la vitrine publique suit
    b = blocs[j] if bouge else blocs[i]
    return 200, {"ok": True, "accueil": await _accueil_direction(g),
                 "_journal": f"Site de l'équipage : bloc « {_titre_bloc(b['type'], b['contenu'])} » déplacé vers le {sens}"
                 if bouge else None}


async def _route_bloc_supprimer(g, auteur, requete, corps):
    """`POST equipage/bloc/supprimer` `{id}` : le bloc part pour de bon (la page demande confirmation)."""
    ident = corps.get("id")
    if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
        return 400, {"erreur": "Identifiant de bloc invalide.", "champ": "id"}
    async with _verrou_ecriture():
        b = await _bloc(g.id, ident)
        if b is None:
            return 200, {"ok": True, "accueil": await _accueil_direction(g), "_journal": None}
        async with _get_db() as db:
            await db.execute("DELETE FROM equipage_blocs WHERE guild_id=? AND id=?", (g.id, ident))
            await db.commit()
    _apres_ecriture(g)
    return 200, {"ok": True, "accueil": await _accueil_direction(g),
                 "_journal": f"Site de l'équipage : bloc « {_titre_bloc(b['type'], b['contenu'])} » supprimé"}


async def _route_actualite(g, auteur, requete, corps):
    """`POST equipage/actualite` `{id?, titre, texte, image?, epingle?, version?}` : publier ou modifier."""
    ident = corps.get("id")
    try:
        version = affiches._entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)
        titre = affiches._texte(corps.get("titre"), "titre", 100, requis=True)
        texte = affiches._texte(corps.get("texte"), "texte", 2000, lignes=True)
        image = await _media_valide(g, corps.get("image"), "image")
        epingle = affiches._booleen(corps.get("epingle"), "epingle", False)
        async with _verrou_ecriture():
            deja = None
            if ident not in (None, ""):
                if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
                    return 400, {"erreur": "Identifiant d'actualité invalide.", "champ": "id"}
                async with _get_db() as db:
                    async with db.execute(f"SELECT {', '.join(_COL_ACTU)} FROM equipage_actualites WHERE guild_id=?"
                                          " AND id=?", (g.id, ident)) as cur:
                        r = await cur.fetchone()
                if r is None:
                    return 404, {"erreur": "Cette actualité n'existe plus."}
                deja = dict(zip(_COL_ACTU, r))
                if version != int(deja["version"]):
                    return 409, {"conflit": True, "actuelle": _sortie_actu(deja, True)}
            t = int(time.time())
            async with _get_db() as db:
                if deja is None:
                    async with db.execute("SELECT COUNT(*) FROM equipage_actualites WHERE guild_id=?", (g.id,)) as cur:
                        if int((await cur.fetchone())[0]) >= ACTUALITES_MAX:
                            return 400, {"erreur": f"{ACTUALITES_MAX} actualités au plus : retire d'abord les anciennes."}
                    ident = secrets.token_urlsafe(8)
                    await db.execute("INSERT INTO equipage_actualites (guild_id, id, titre, texte, image, epingle, version,"
                                     " cree_le, cree_par, maj_le, maj_par) VALUES (?,?,?,?,?,?,1,?,?,?,?)",
                                     (g.id, ident, titre, texte, image, int(epingle), t, auteur.id, t, auteur.id))
                else:
                    await db.execute("UPDATE equipage_actualites SET titre=?, texte=?, image=?, epingle=?,"
                                     " version=version+1, maj_le=?, maj_par=? WHERE guild_id=? AND id=?",
                                     (titre, texte, image, int(epingle), t, auteur.id, g.id, ident))
                await db.commit()
    except affiches.Invalide as ex:
        return 400, ex.corps()
    _apres_ecriture(g)
    return 200, {"ok": True, "id": ident, "accueil": await _accueil_direction(g),
                 "_journal": f"Site de l'équipage : actualité « {titre} » {'publiée' if deja is None else 'modifiée'}"}


async def _route_actualite_retirer(g, auteur, requete, corps):
    """`POST equipage/actualite/retirer` `{id}` : l'actualité part pour de bon (la page demande confirmation)."""
    ident = corps.get("id")
    if not isinstance(ident, str) or not FORMAT_ID.fullmatch(ident):
        return 400, {"erreur": "Identifiant d'actualité invalide.", "champ": "id"}
    async with _verrou_ecriture():
        async with _get_db() as db:
            async with db.execute("SELECT titre FROM equipage_actualites WHERE guild_id=? AND id=?", (g.id, ident)) as cur:
                r = await cur.fetchone()
            if r is not None:
                await db.execute("DELETE FROM equipage_actualites WHERE guild_id=? AND id=?", (g.id, ident))
                await db.commit()
    _apres_ecriture(g)
    return 200, {"ok": True, "accueil": await _accueil_direction(g),
                 "_journal": f"Site de l'équipage : actualité « {r[0]} » retirée" if r is not None else None}


def _cle_verrou(genre: str):
    """La clé que touche une écriture (`accueil:<id>`, `actualite:<id>`) : la présence en direct (`tableau`, `site/
    direct.js`) refuse (423) d'écrire un bloc ou une actualité que quelqu'un d'autre est en train de modifier. Un ajout
    (sans identifiant) ne touche rien d'existant."""
    def objet(corps):
        ident = corps.get("id") if isinstance(corps, dict) else None
        return f"{genre}:{ident}" if isinstance(ident, str) and FORMAT_ID.fullmatch(ident) else None
    objet.__name__ = f"_cle_verrou_{genre}"
    return objet


ROUTES_SITE = {
    "equipage/bloc": {"methode": "POST", "fn": _route_bloc, "ecriture": True, "corps_max": 32 * 1024,
                      "verrou": _cle_verrou("accueil")},
    "equipage/bloc/visible": {"methode": "POST", "fn": _route_bloc_visible, "ecriture": True, "corps_max": 1024,
                              "verrou": _cle_verrou("accueil")},
    "equipage/bloc/public": {"methode": "POST", "fn": _route_bloc_public, "ecriture": True, "corps_max": 1024,
                             "verrou": _cle_verrou("accueil")},
    "equipage/vitrine/affiche": {"methode": "POST", "fn": _route_vitrine_affiche, "ecriture": True, "corps_max": 1024},
    #  Les équipes du clan (27/10/2026) : lues par la direction (et la fiche d'un membre) ; écrites par la tête seule.
    "equipage/equipes": {"methode": "GET", "fn": _route_equipes},
    "equipage/equipe": {"methode": "POST", "fn": _route_equipe, "ecriture": True, "corps_max": 16 * 1024,
                        "verrou": _cle_verrou("equipe")},
    "equipage/equipe/supprimer": {"methode": "POST", "fn": _route_equipe_supprimer, "ecriture": True, "corps_max": 1024,
                                  "verrou": _cle_verrou("equipe")},
    "equipage/equipe/deplacer": {"methode": "POST", "fn": _route_equipe_deplacer, "ecriture": True, "corps_max": 1024,
                                 "verrou": _cle_verrou("equipe")},
    "equipage/bloc/deplacer": {"methode": "POST", "fn": _route_bloc_deplacer, "ecriture": True, "corps_max": 1024,
                               "verrou": _cle_verrou("accueil")},
    "equipage/bloc/supprimer": {"methode": "POST", "fn": _route_bloc_supprimer, "ecriture": True, "corps_max": 1024,
                                "verrou": _cle_verrou("accueil")},
    "equipage/actualite": {"methode": "POST", "fn": _route_actualite, "ecriture": True, "corps_max": 16 * 1024,
                           "verrou": _cle_verrou("actualite")},
    "equipage/actualite/retirer": {"methode": "POST", "fn": _route_actualite_retirer, "ecriture": True,
                                   "corps_max": 1024, "verrou": _cle_verrou("actualite")},
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Discord : le lien personnel (guide du clan)
# ═══════════════════════════════════════════════════════════════════════════════

async def lien_equipage(i) -> tuple:
    """(lien personnel, "") — ou (None, le refus, dit tel quel à la personne). Un membre du rôle du clan : un lien de
    portée « equipage » (lecture seule). Le fondateur et la direction : leur lien habituel (« tout »), qui ouvre la même
    page avec le mode édition. Personne d'autre."""
    g, m = getattr(i, "guild", None), getattr(i, "user", None)
    if g is None or m is None or not tableau._base or not tableau._cle or not pret():
        return None, "Le site de l'équipage n'est pas joignable pour le moment."
    c = await _cfg(g.id)
    tete = tableau.a_la_tete(g, m.id) and tableau._autorise_membre is not None and tableau._autorise_membre(g, m, c)
    if not tete and not tableau.autorise_equipage(g, m, c):
        return None, _t(g, f"{GROUPE}.lien.reserve")
    if await tableau.suspendu(g.id, m.id):
        return None, "Ton accès au site est suspendu pour le moment. Réessaie plus tard."
    if tete:
        return f"{tableau._base}/tableau/{tableau.jeton(g.id, m.id, 'tout')}?vers=equipage", ""
    return f"{tableau._base}/tableau/{tableau.jeton(g.id, m.id, 'equipage')}", ""


def _vue_avis(texte: str, couleur=Palette.NEUTRAL, lien: str = "", bouton: str = "") -> LayoutView:
    v = LayoutView(timeout=AVIS_S)
    morceaux = [discord.ui.TextDisplay(texte)]
    if lien:
        morceaux.append(discord.ui.ActionRow(Button(label=(bouton or "Ouvrir")[:80], url=lien)))
    v.add_item(discord.ui.Container(*morceaux, accent_color=couleur))
    return v


def _effacer_plus_tard(i, delai: float = AVIS_S) -> None:
    """« Un avis est pour la personne seule » : il s'efface tout seul."""
    supprimer = getattr(i, "delete_original_response", None)
    if supprimer is None:
        return

    async def _plus_tard():
        await asyncio.sleep(delai)
        try:
            await supprimer()
        except discord.HTTPException:
            pass  # déjà fermé par le membre, ou le jeton de l'interaction a expiré : rien à faire
    tache = asyncio.create_task(_plus_tard())
    _taches.add(tache)
    tache.add_done_callback(_taches.discard)


async def envoyer_lien(i) -> None:
    url, refus = await lien_equipage(i)
    if url:
        g = getattr(i, "guild", None)
        vue = _vue_avis(_t(g, f"{GROUPE}.lien.texte"), discord.Color(0xA8823F), url, _t(g, f"{GROUPE}.lien.bouton"))
    else:
        vue = _vue_avis(refus, Palette.WARNING)
    if i.response.is_done():
        await i.followup.send(view=vue, ephemeral=True)
    else:
        await i.response.send_message(view=vue, ephemeral=True)
    _effacer_plus_tard(i)


class BoutonSiteEquipage(discord.ui.DynamicItem[Button], template=r"eq:site"):
    """« Le site de l'équipage » (guide du clan) : persistant, il répond après un redémarrage (`bot.add_dynamic_items`)."""

    def __init__(self, libelle: str = ""):
        #  Le libellé : celui du guide (`section_guide`, réécrit sur le site) ; recréé au clic, il ne se voit pas.
        super().__init__(Button(label=(libelle or textes.defaut("guide.site.bouton"))[:80],
                                style=discord.ButtonStyle.secondary, custom_id="eq:site"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        try:
            await envoyer_lien(i)
        except Exception as ex:
            _signaler("E9", "lien du site de l'équipage en échec", ex)
            try:
                vue = _vue_avis("Un souci est survenu : réessaie dans un instant.", Palette.WARNING)
                if i.response.is_done():
                    await i.followup.send(view=vue, ephemeral=True)
                else:
                    await i.response.send_message(view=vue, ephemeral=True)
            except discord.HTTPException as ex2:
                _signaler("E9", "réponse impossible", ex2)
            raise


ADRESSE_VITRINE = "/equipage"   # la vitrine publique (`site_vitrine.py`) : le lien officiel de l'équipage


def lien_vitrine() -> str:
    """L'adresse publique de la vitrine (à partager), ou "" quand le site n'a pas d'adresse publique."""
    return f"{tableau._base}{ADRESSE_VITRINE}" if tableau._base else ""


async def section_guide(g, c: dict) -> tuple | None:
    """Pour le guide du clan (`zones.vue_guide_clan`) : (la ligne « Le site de l'équipage », son bouton personnel et, à
    côté, le lien PUBLIC de la vitrine ; leur signature) — None quand le site n'est pas joignable ou qu'aucun rôle du
    clan n'est réglé (aucun bouton qui ment)."""
    if not pret() or not tableau._base or not tableau._cle or g is None:
        return None
    rid = int((c or {}).get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0)
    if not rid or g.get_role(rid) is None:
        return None
    texte, libelle, vitrine = _t(g, "guide.site.texte"), _t(g, "guide.site.bouton"), _t(g, "guide.vitrine.bouton")
    composants = [discord.ui.TextDisplay(texte),
                  discord.ui.ActionRow(BoutonSiteEquipage(libelle), Button(label=vitrine[:80], url=lien_vitrine()))]
    return composants, hashlib.sha256(f"{texte}\x1f{libelle}\x1f{vitrine}\x1f{lien_vitrine()}".encode("utf-8")).hexdigest()[:12]


__all__ = ["setup", "init_db", "LECTURES", "ROUTES_SITE", "medias_permis", "medias_utilises", "section_guide",
           "BoutonSiteEquipage", "lien_equipage", "analyses", "actualites_auto", "texte_discord", "lien_vitrine",
           "vitrine_masquees", "generation", "ADRESSE_VITRINE"]
