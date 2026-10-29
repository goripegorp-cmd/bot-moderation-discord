#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Icônes officielles, logos et catalogue de RELL Seas pour le site du clan (25/10/2026).

Le fondateur a autorisé le téléchargement des icônes officielles du jeu (wiki Fandom de RELL Seas)
et des logos officiels. Ce script refait TOUT, et se rejoue à l'identique :

1. Téléchargement poli (une image à la fois, une pause entre deux requêtes) des SEULES images
   listées par le dossier de recherche du 25/10 (wiki Fandom en PNG d'origine via
   `&format=original`, API thumbnails de Roblox, icône du Discord RELL Seas). Les images des
   montures : seulement celles dont l'API du wiki donne l'adresse exacte. Chaque fichier reçu est
   vérifié (octets magiques, taille, ouverture complète par Pillow) ; sinon rien n'en est gardé et
   l'échec est noté. Les originaux restent dans un cache HORS du dépôt (`--cache`).
2. Conversion (Pillow) :
   - site : `site/icones/rell/<type>/<cle>.webp` (carré 256 px, recadré au contenu, transparence
     gardée) ; races : portrait carré (visage, haut du corps) + `<cle>_entier.webp` ;
     `site/logos/<nom>.webp` ;
   - Discord : `visuels/icones/rell_<type>_<cle>.png` (128 × 128, transparent), émojis
     d'application installés par `visuels.installer_icones` — métiers, races, factions, fruits,
     traits, classes et Haki seulement. Aucun fichier existant d'un autre nom n'est touché.
3. `donnees_jeu/rell_catalogue.json` : la forme exacte de la spécification (§2.4).
4. `site/icones/rell/SOURCES.md` (provenance de chaque image) et `site/icones/rell/planche.html`
   (planche de contrôle : chaque icône à 32, 64 et 128 px sur parchemin et sur bois sombre).
5. Vérification (`--verifier`, aussi lancée à la fin) : forme du catalogue, fichiers, tailles, noms.

Règle des noms : `nom_en` = le nom exact du jeu, toujours. `nom` = le nom français du dossier de
recherche ; à défaut, la traduction d'un mot courant ; un nom propre ou un terme forgé du jeu
(carte de Haki, poster, style, arme ou navire nommé, mer, monnaie) reste tel quel en anglais.
Renommages du 25/10 : le NOUVEAU nom est affiché, l'ancien va dans la description (« Anciennement … »).

Défi anti-robot : le CDN des images du wiki (static.wikia.nocookie.net, Cloudflare) peut répondre
aux outils par un défi (`Cf-Mitigated: challenge`). On ne le contourne JAMAIS : ni faux navigateur,
ni boucle de reprises. Au premier défi, l'hôte est mis de côté pour la séance ; les images refusées
ne sont redemandées qu'avec `--reessayer` (une requête, puis arrêt au premier défi). Pour les obtenir :
  1. le script écrit une page d'aide `<cache>/a_enregistrer/rell_seas_images.html` ;
  2. une personne l'ouvre dans son navigateur (Chrome, Edge, Firefox), attend que toutes les images
     s'affichent, puis Ctrl+S, type « Page Web, complète », dans le même dossier ;
  3. `--depuis <la page enregistrée>` importe chaque image (mêmes vérifications que le
     téléchargement). `--depuis <dossier>` accepte aussi des fichiers nommés `<type>__<cle>.png` ou
     du nom du fichier du wiki (`Cookingicon.png`).
Les icônes déjà livrées restent valables sans le cache : le catalogue suit les fichiers présents,
et leur provenance est gardée à la fin de SOURCES.md.

Usage :
  python -I outils/icones_rellseas.py --cache DOSSIER               tout (télécharge ce qui manque)
  python -I outils/icones_rellseas.py --cache DOSSIER --hors-ligne  tout refaire depuis le cache
  python -I outils/icones_rellseas.py --cache DOSSIER --depuis PAGE_OU_DOSSIER
  python -I outils/icones_rellseas.py --verifier                    vérifier seulement
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import html.parser
import io
import json
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageFilter

RACINE = Path(__file__).resolve().parent.parent
SITE = RACINE / "site"
DOSSIER_ICONES = SITE / "icones" / "rell"
DOSSIER_LOGOS = SITE / "logos"
DOSSIER_DISCORD = RACINE / "visuels" / "icones"
CATALOGUE = RACINE / "donnees_jeu" / "rell_catalogue.json"
SOURCES_MD = DOSSIER_ICONES / "SOURCES.md"
PLANCHE = DOSSIER_ICONES / "planche.html"

VIDEO_M3 = "https://www.youtube.com/watch?v=q09y0z5Vyxw"
WIKI = "https://rellseas.fandom.com/wiki/"
API_WIKI = "https://rellseas.fandom.com/api.php"
UA = "GoRP-Capitainerie/1.0 (site prive du clan GoRP ; releve ponctuel des icones officielles)"
PAUSE = 1.2                    # secondes entre deux requêtes : poli avec le wiki et Roblox
OCTETS_MIN, OCTETS_MAX = 100, 8 * 1024 * 1024
COTE_MAX = 4096
Image.MAX_IMAGE_PIXELS = COTE_MAX * COTE_MAX
HOTES = ("static.wikia.nocookie.net", "rellseas.fandom.com", "thumbnails.roblox.com",
         "cdn.discordapp.com")
COTE_SITE, COTE_DISCORD = 256, 128
TYPES_DISCORD = ("metier", "race", "faction", "fruit", "trait", "classe", "haki")
NOM_DISCORD_MAX = 26

# ─────────────────────────────── Types du catalogue ───────────────────────────────
#  cle, nom, nom_en, champ (étiquette sur l'affiche), multiple
TYPES = [
    ("metier", "Métiers", "Talents", "Métiers", True),
    ("race", "Races", "Races", "Race", False),
    ("faction", "Factions", "Factions", "Faction", False),
    ("mer", "Mers", "Seas", "Mer de départ", False),
    ("trait", "Traits principaux", "Main Traits", "Trait principal", False),
    ("classe", "Classes principales", "Main Classes", "Classe principale", False),
    ("fruit", "Fruits", "God Fruits", "Fruit", False),
    ("haki", "Haki", "Haki", "Haki", True),
    ("carte_haki", "Cartes de Haki", "Haki Cards", "Cartes de Haki", True),
    ("poster", "Posters", "Posters", "Posters", True),
    ("style", "Styles de combat", "Fighting Styles", "Styles de combat", True),
    ("arme", "Armes", "Weapons", "Armes", True),
    ("equipement", "Équipement", "Equipment", "Équipement", True),
    ("enchantement", "Enchantements", "Enchants", "Enchantements", True),
    ("navire", "Navires", "Ships", "Navires", True),
    ("piece_navire", "Pièces de navire", "Ship Parts", "Pièces de navire", True),
    ("monture", "Montures", "Mounts", "Montures", True),
    ("monnaie", "Monnaies", "Currencies", "Monnaies", True),
]

ELEMENTS: list[dict] = []


def el(type_, cle, nom, nom_en, description, *, categorie="", statut="confirme", nouveau=False,
       source="", image=None, rarete="", actif=True):
    """Un élément du catalogue. `image` : l'adresse donnée par le dossier de recherche (wiki),
    ou « api:<Fichier.png> » (adresse demandée à l'API du wiki), ou None (aucune icône officielle)."""
    ELEMENTS.append({
        "type": type_, "cle": cle, "nom": nom, "nom_en": nom_en, "description": description,
        "categorie": categorie, "rarete": rarete, "statut": statut, "source": source or VIDEO_M3,
        "nouveau_movie3": nouveau, "image": image, "actif": actif,
    })


# ── Métiers (talents) — ordre de la liste lue à l'écran dans Movie 3, puis Shipwright ──
el("metier", "cooking", "Cuisine", "Cooking",
   "Feu de camp puis cuisine complète en mini-jeux (découpe, poêle, four, mixeur) ; nutrition, "
   "recettes. Movie 3 : mini-jeux, maîtrise.",
   categorie="Production · soutien", source=WIKI + "Cooking",
   image="https://static.wikia.nocookie.net/rell-seasw/images/b/bb/Cookingicon.png/revision/latest?cb=20260622234132")
el("metier", "thieving", "Vol", "Thieving",
   "Crochetage, exécution furtive, pickpocket, interrogatoire ; déclenche les Marines. "
   "Movie 3 : interrogatoire, exécutions.",
   categorie="Illégal · furtivité", source=WIKI + "Thieving",
   image="https://static.wikia.nocookie.net/rell-seasw/images/2/21/Thievingtalenticon.png/revision/latest?cb=20260622235241")
el("metier", "navigation", "Navigation", "Navigation",
   "Longue-vue (apparitions rares), boussole améliorable, trésors et sites découverts. "
   "Movie 3 : amélioration annoncée.",
   categorie="Exploration", source=WIKI + "Talents",
   image="https://static.wikia.nocookie.net/rell-seasw/images/9/99/Navigationtalenticon.png/revision/latest?cb=20260622235102")
el("metier", "fishing", "Pêche", "Fishing",
   "Nouveau système de pêche ; canne à Léviathan ; journal des poissons. Movie 3 : système refait.",
   categorie="Récolte", source=WIKI + "Fishing",
   image="https://static.wikia.nocookie.net/rell-seasw/images/0/03/Fishingtalenticon.png/revision/latest?cb=20260622233608")
el("metier", "crafting", "Artisanat", "Crafting",
   "Forge (fondre, couler, refroidir, affûter), plans d'armes et d'armures, mode auto-play. "
   "Movie 3 : forge en mini-jeux.",
   categorie="Production", source=WIKI + "Crafting",
   image="https://static.wikia.nocookie.net/rell-seasw/images/f/f8/Craftingtalenticon.png/revision/latest?cb=20260622234856")
el("metier", "woodcutting", "Bûcheronnage", "Woodcutting",
   "Abattage réaliste ; le bois sert au feu et à l'artisanat.",
   categorie="Récolte", source=WIKI + "Woodcutting",
   image="https://static.wikia.nocookie.net/rell-seasw/images/6/6f/Woodcuttingicon.png/revision/latest?cb=20260622233928")
el("metier", "doctor", "Médecin", "Doctor",
   "Soigne les maladies (rhume, grippe, peste), potions ; progresse par la connaissance (livres). "
   "Aucune icône officielle pour l'instant.",
   categorie="Soutien · santé", nouveau=True, source=VIDEO_M3)
el("metier", "mining", "Minage", "Mining",
   "Roche et minerais (cuivre, étain) ; évolutions annoncées dans Movie 3.",
   categorie="Récolte", source=WIKI + "Mining",
   image="https://static.wikia.nocookie.net/rell-seasw/images/5/55/Miningtalenticon.png/revision/latest?cb=20260622234434")
el("metier", "shipwright", "Charpentier naval", "Shipwright",
   "N'existe pas dans le jeu (confirmé par le fondateur le 26/10/2026) : la construction des navires est un "
   "système, pas un métier. Retiré du catalogue.",
   categorie="Navire", statut="confirme", source=WIKI + "Shipwright", actif=False,
   image="https://static.wikia.nocookie.net/rell-seasw/images/6/6b/Shipwrighttalenticon.png/revision/latest?cb=20260622234652")

# ── Races (Movie 3 : races et sous-espèces ; noms du wiki renommés le 25/10) ──
el("race", "human", "Humain", "Human", "Race de base, la plus commune.", source=WIKI + "Human",
   image="https://static.wikia.nocookie.net/rell-seasw/images/6/6e/Human.png/revision/latest?cb=20261025160144")
el("race", "beastman", "Homme-bête", "Beastman",
   "Anciennement Mink. Sous-espèces animales (loup, lion, bison, girafe, cerf, mouton).",
   source=WIKI + "Beastman",
   image="https://static.wikia.nocookie.net/rell-seasw/images/5/5f/BeastMan_Race.png/revision/latest?cb=20261025150735")
el("race", "marinian", "Marinien", "Marinian",
   "Anciennement Fishman. 3 types (dont Sharkman, Octopus) ; Lowborn, Highborn, Royalty ; "
   "Swimmer ou Breather.",
   source=WIKI + "Marinian",
   image="https://static.wikia.nocookie.net/rell-seasw/images/7/77/Marinian_Race.png/revision/latest?cb=20261025152400")
el("race", "avalonian", "Avalonien", "Avalonian", "Anciennement Skypiean. Ailes blanches.",
   source=WIKI + "Avalonian",
   image="https://static.wikia.nocookie.net/rell-seasw/images/1/17/Avalonian_Race.png/revision/latest?cb=20261025154306")
el("race", "cyborg", "Cyborg", "Cyborg", "Parties robotiques.", source=WIKI + "Cyborg",
   image="https://static.wikia.nocookie.net/rell-seasw/images/f/f9/Cyborg_Race.png/revision/latest?cb=20261025145700")
el("race", "giant", "Géant", "Giant", "Nouvelle race : grande taille, barbes exclusives.",
   nouveau=True, source=WIKI + "Giant",
   image="https://static.wikia.nocookie.net/rell-seasw/images/8/8c/GaintRace.png/revision/latest?cb=20261025183132")
el("race", "dwarf", "Nain", "Dwarf", "Nouvelle race : barbes exclusives.",
   nouveau=True, source=WIKI + "Races",
   image="https://static.wikia.nocookie.net/rell-seasw/images/7/7f/DwarfRace.png/revision/latest?cb=20261025183131")
el("race", "three_eyes", "Trois-Yeux", "Three Eyes",
   "Nouvelle race. Sous-espèces : Fishman, ogre, orc, elfe, dragon, nain.",
   nouveau=True, source=WIKI + "Three_Eyes",
   image="https://static.wikia.nocookie.net/rell-seasw/images/6/66/ThreeEyesRace.png/revision/latest?cb=20261025182351")
el("race", "lunars", "Lunars", "Lunars",
   "Anciennement Lunarian (nom changé le 25/10, « confirmé par Movie 3 » selon le wiki). "
   "Ailes noires, flamme dans le dos.",
   statut="a_verifier", nouveau=True, source=WIKI + "Lunars",
   image="https://static.wikia.nocookie.net/rell-seasw/images/f/f0/LunarianRace.png.png/revision/latest?cb=20261025183544")
el("race", "oni", "Oni", "Oni", "Anciennement Antique Giant. Cornes, grande taille ; Oni King et Oni Queen.",
   statut="a_verifier", nouveau=True, source=WIKI + "Oni",
   image="https://static.wikia.nocookie.net/rell-seasw/images/5/56/OniRace.png/revision/latest?cb=20261025183133")

# ── Factions (les 4 factions principales) ──
el("faction", "pirates", "Pirates", "Pirates",
   "Anciennement Council of Piracy. Plus de 40 factions pirates selon les RELL Bros (Movie 2).",
   categorie="Faction principale", source=WIKI + "Factions/Pirates",
   image="https://static.wikia.nocookie.net/rell-seasw/images/8/84/PirateCouncil.png/revision/latest?cb=20241227094259")
el("faction", "marines", "Marine", "World Seas Marine Corps",
   "Anciennement Marines (WSMC). Force armée du gouvernement : ordre, justice, chasse aux pirates ; "
   "21 rangs, de Recruit à Fleet Admiral.",
   categorie="Faction principale", source=WIKI + "Factions/World_Seas_Marine_Corps",
   image="https://static.wikia.nocookie.net/rell-seasw/images/f/f3/MarineCorps.png/revision/latest?cb=20241227094300")
el("faction", "revolution", "Révolutionnaires", "Arms of Revolution",
   "Anciennement Revolutionary Army. Faction secrète qui veut renverser l'ordre mondial. "
   "Nom exact à vérifier.",
   categorie="Faction principale", source=WIKI + "Factions/Arms_of_Revolution",
   image="https://static.wikia.nocookie.net/rell-seasw/images/f/f5/ArmsOfRevolution.png/revision/latest?cb=20260326125443")
el("faction", "gouvernement", "Gouvernement mondial", "World Seas Government",
   "Anciennement World Government. Dirige le monde et supervise le Marine Corps ; ennemis : "
   "Pirates et Révolutionnaires.",
   categorie="Faction principale", source=WIKI + "Factions/World_Seas_Government",
   image="https://static.wikia.nocookie.net/rell-seasw/images/f/fe/WorldSeasGovernment.png/revision/latest?cb=20241227094300")

# ── Mers (journal C1–C7 : seuls les noms confirmés) ──
el("mer", "desolate", "Desolate", "Desolate", "Mer 4.", nouveau=True)
el("mer", "sunken", "Sunken", "Sunken", "Mer 5.", nouveau=True)
el("mer", "molten", "Molten", "Molten", "Numéro de mer non confirmé.", nouveau=True)
el("mer", "uncharted", "Uncharted", "Uncharted", "Numéro de mer non confirmé.", nouveau=True)

# ── Trait principal (1 parmi 6, figé) — effets : page Traits du 25/10, à vérifier ──
_TRAIT = "Trait principal (1 parmi 6, figé). Effet (à vérifier) : "
el("trait", "health", "Santé", "Health", _TRAIT + "×1,5 points de vie.", source=WIKI + "Traits",
   image="https://static.wikia.nocookie.net/rell-seasw/images/d/de/HealthTraitIcon.png/revision/latest?cb=20261025192901")
el("trait", "endurance", "Endurance", "Endurance",
   _TRAIT + "×2 stamina. Icône nommée « Stamina » sur le wiki : nom exact à vérifier.",
   source=WIKI + "Traits",
   image="https://static.wikia.nocookie.net/rell-seasw/images/0/0c/StaminaTraitIcon.png/revision/latest?cb=20261025192901")
el("trait", "defense", "Défense", "Defense", _TRAIT + "×1,2 blocage.", source=WIKI + "Traits",
   image="https://static.wikia.nocookie.net/rell-seasw/images/b/b5/DefenseTraitIcon.png/revision/latest?cb=20261025192900")
el("trait", "willpower", "Volonté", "Willpower", _TRAIT + "×1,2 dégâts du style de combat.",
   source=WIKI + "Traits",
   image="https://static.wikia.nocookie.net/rell-seasw/images/2/20/WillPowerTraitIcon.png/revision/latest?cb=20261025192901")
el("trait", "spiritual", "Spirituel", "Spiritual", _TRAIT + "×1,2 dégâts et résistance.",
   source=WIKI + "Traits",
   image="https://static.wikia.nocookie.net/rell-seasw/images/d/db/SpiritualTraitIcon.png/revision/latest?cb=20261025192901")
el("trait", "luck", "Chance", "Luck", _TRAIT + "×2 butin.", source=WIKI + "Traits",
   image="https://static.wikia.nocookie.net/rell-seasw/images/3/3b/LuckTraitIcon.png/revision/latest?cb=20261025192901")

# ── Classe principale (1 parmi 4, figée) ──
_CLASSE = "Classe principale (1 parmi 4, figée)."
el("classe", "light", "Léger", "Light", _CLASSE,
   image="https://static.wikia.nocookie.net/rell-seasw/images/0/0b/LightMainClass.png/revision/latest?cb=20261025192901")
el("classe", "medium", "Moyen", "Medium", _CLASSE, statut="a_verifier",
   image="https://static.wikia.nocookie.net/rell-seasw/images/6/69/MediumMainClass.png/revision/latest?cb=20261025192901")
el("classe", "heavy", "Lourd", "Heavy", _CLASSE, statut="a_verifier",
   image="https://static.wikia.nocookie.net/rell-seasw/images/7/7f/HeavyMainClass.png/revision/latest?cb=20261025192901")
el("classe", "gunman", "Tireur", "Gunman", "Anciennement Ranged. " + _CLASSE, statut="a_verifier",
   image="https://static.wikia.nocookie.net/rell-seasw/images/b/be/GunmanMainClass.png/revision/latest?cb=20261025192901")

# ── God Fruits : 32, liste d'avant Movie 3 (2 wikis concordants) ──
_FRUITS = [
    #  cle, nom, nom_en, classe, page du wiki, description, image
    ("rubber", "Caoutchouc", "Rubber", "Paramecia", "Rubber", "Corps en caoutchouc (Rubber Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/8/8d/RubberGodFruit.png/revision/latest?cb=20250703005433"),
    ("quake", "Séisme", "Quake", "Paramecia", "Quake", "Séismes et secousses (Tremor/Quake Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/d/d6/QuakeGodFruit.png/revision/latest?cb=20241229092739"),
    ("dough", "Pâte", "Dough", "Paramecia", "Dough", "Créer, contrôler et devenir de la pâte (mochi).",
     "https://static.wikia.nocookie.net/rell-seasw/images/3/37/DoughGodFruit.png/revision/latest?cb=20250703005434"),
    ("operation", "Opération", "Operation", "Paramecia", "Operation",
     "Domaine sphérique (Free Modification Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/b/bc/OperationGodFruit.png/revision/latest?cb=20241229092844"),
    ("venom", "Venin", "Venom", "Paramecia", "Venom",
     "Poison (Poison Human) ; immunité à tous les poisons ; ce n'est pas un Logia.",
     "https://static.wikia.nocookie.net/rell-seasw/images/9/91/VenomGodFruit.png/revision/latest?cb=20241229092844"),
    ("soul", "Âme", "Soul", "Paramecia", "Soul", "Manipuler les âmes.",
     "https://static.wikia.nocookie.net/rell-seasw/images/0/01/SoulGodFruit.png/revision/latest?cb=20241229092739"),
    ("paw", "Patte", "Paw", "Paramecia", "Paw", "Coups de pression et répulsion (Paw Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/5/55/PawGodFruit.png/revision/latest?cb=20241229092739"),
    ("gravity", "Gravité", "Gravity", "Paramecia", "Gravity",
     "Contrôle de la gravité ; ultime : Meteor Shower.",
     "https://static.wikia.nocookie.net/rell-seasw/images/6/64/GravityGodFruit.png/revision/latest?cb=20241229092739"),
    ("string", "Fil", "String", "Paramecia", "String", "Fils (String Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/b/b2/StringGodFruit.png/revision/latest?cb=20241229092739"),
    ("barrier", "Barrière", "Barrier", "Paramecia", "Barrier", "Barrières (Barrier Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/c/c9/BarrierGodFruit.png/revision/latest?cb=20241229092738"),
    ("love", "Amour", "Love", "Paramecia", "Love",
     "Amour et désir : projectiles d'amour, explosion de cœurs.",
     "https://static.wikia.nocookie.net/rell-seasw/images/2/24/LoveGodFruit.png/revision/latest?cb=20241229092739"),
    ("revive", "Résurrection", "Revive", "Paramecia", "Revive",
     "Ressuscite après la première mort (Reviving Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/d/dc/ReviveGodFruit.png/revision/latest?cb=20241229092739"),
    ("bomb", "Bombe", "Bomb", "Paramecia", "Bomb", "Fait exploser n'importe quelle partie du corps.",
     "https://static.wikia.nocookie.net/rell-seasw/images/2/2b/BombGodFruit.png/revision/latest?cb=20241229092738"),
    ("chop", "Découpe", "Chop", "Paramecia", "Chop",
     "Se découper en morceaux ; immunité aux attaques tranchantes.",
     "https://static.wikia.nocookie.net/rell-seasw/images/d/d9/ChopGodFruit.png/revision/latest?cb=20241229092738"),
    ("flame", "Flamme", "Flame", "Logia", "Flame", "Logia du feu : brûlure.",
     "https://static.wikia.nocookie.net/rell-seasw/images/7/78/FlameGodFruit.png/revision/latest?cb=20241229090314"),
    ("ice", "Glace", "Ice", "Logia", "Ice", "Logia de la glace (Freezing Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/6/61/IceGodFruit.png/revision/latest?cb=20241229092739"),
    ("sand", "Sable", "Sand", "Logia", "Sand", "Logia du sable (Sand Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/c/c4/SandGodFruit.png/revision/latest?cb=20241229092844"),
    ("smoke", "Fumée", "Smoke", "Logia", "Smoke_Devil_Fruit", "Logia de la fumée (Smoke Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/3/36/SmokeGodFruit.png/revision/latest?cb=20241229092740"),
    ("light", "Lumière", "Light", "Logia", "Light", "Logia de la lumière.",
     "https://static.wikia.nocookie.net/rell-seasw/images/f/f2/LightGodFruit.png/revision/latest?cb=20241229092739"),
    ("dark", "Ténèbres", "Dark", "Logia", "Dark", "Logia des ténèbres (Darkness Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/a/a4/DarkGodFruit.png/revision/latest?cb=20241229092738"),
    ("rumble", "Foudre", "Rumble", "Logia", "Rumble", "Anciennement Lightning (Goro). Logia de la foudre.",
     "https://static.wikia.nocookie.net/rell-seasw/images/2/28/RumbleGodFruit.png/revision/latest?cb=20241229092844"),
    ("magma", "Magma", "Magma", "Logia", "Magma", "Logia du magma (Magma Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/9/9e/MagmaGodFruit.png/revision/latest?cb=20241229092844"),
    ("dragon", "Dragon", "Dragon", "Zoan", "Dragon",
     "Zoan mythique (Mythical Zoan) : dragon azur, forme hybride ou complète.",
     "https://static.wikia.nocookie.net/rell-seasw/images/6/69/DragonGodFruit.png/revision/latest?cb=20241229092738"),
    ("phoenix", "Phénix", "Phoenix", "Zoan", "Phoenix", "Zoan mythique (Mythical Zoan) : phénix ou hybride.",
     "https://static.wikia.nocookie.net/rell-seasw/images/0/09/PhoenixGodFruit.png/revision/latest?cb=20241229092844"),
    ("buddha", "Bouddha", "Buddha", "Zoan", "Buddha", "Zoan mythique (Mythical Zoan) : bouddha géant doré.",
     "https://static.wikia.nocookie.net/rell-seasw/images/4/4d/BuddhaGodFruit.png/revision/latest?cb=20241229092843"),
    ("mythical_wolf", "Loup mythique", "Mythical Wolf", "Zoan", "Mythical_Wolf",
     "Anciennement Yamato Kitsune / Mythical Fox. Zoan mythique (Mythical Zoan) : divinité loup "
     "ancienne ; pas au lancement, prévu dans une mise à jour.",
     "https://static.wikia.nocookie.net/rell-seasw/images/4/48/MythicalWolfGodFruit.png/revision/latest?cb=20241229092844"),
    ("allosaurus", "Allosaure", "Allosaurus", "Zoan", "Allosaurus", "Zoan antique (Ancient Zoan) : allosaure.",
     "https://static.wikia.nocookie.net/rell-seasw/images/c/c8/AllosaurusGodFruit.png/revision/latest?cb=20241229092737"),
    ("leopard", "Léopard", "Leopard", "Zoan", "Leopard", "Zoan : léopard (Leopard Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/7/76/LeopardGodFruit.png/revision/latest?cb=20241229092844"),
    ("wolf", "Loup", "Wolf", "Zoan", "Wolf", "Zoan : hybride proche du loup-garou.",
     "https://static.wikia.nocookie.net/rell-seasw/images/1/12/WolfGodFruit.png/revision/latest?cb=20241229092844"),
    ("giraffe", "Girafe", "Giraffe", "Zoan", "Giraffe", "Zoan : girafe (Giraffe Human).",
     "https://static.wikia.nocookie.net/rell-seasw/images/7/77/GiraffeGodFruit.png/revision/latest?cb=20241229092739"),
    ("falcon", "Faucon", "Falcon", "Zoan", "Falcon", "Zoan : se transforme en faucon brun.",
     "https://static.wikia.nocookie.net/rell-seasw/images/4/48/FalconGodFruit.png/revision/latest?cb=20241229092739"),
    ("bison", "Bison", "Bison", "Zoan", "Bison", "Zoan : bison complet ou hybride.",
     "https://static.wikia.nocookie.net/rell-seasw/images/0/04/BisonGodFruit.png/revision/latest?cb=20241229092738"),
]
for _c, _n, _ne, _cat, _page, _d, _img in _FRUITS:
    el("fruit", _c, _n, _ne, _d, categorie=_cat, source=WIKI + _page, image=_img)

# ── Haki (3 types ; cartes de Movie 2) ──
el("haki", "armament", "Armement", "Armament",
   "Armure invisible d'énergie spirituelle ; touche les Logia. Touche R.", source=WIKI + "Armament_Haki",
   image="https://static.wikia.nocookie.net/rell-seasw/images/0/07/ArmamentHakiImage.png/revision/latest?cb=20241231151444")
el("haki", "observation", "Observation", "Observation",
   "Sixième sens : présence, puissance, précognition limitée. Touche T.", source=WIKI + "Observation_Haki",
   image="https://static.wikia.nocookie.net/rell-seasw/images/5/51/ObservationHakiImage.png/revision/latest?cb=20241231153834")
el("haki", "conqueror", "Conquérant", "Conqueror",
   "Impose sa volonté : étourdit, assomme les plus faibles. Touche G.", source=WIKI + "Conquerors_Haki",
   image="https://static.wikia.nocookie.net/rell-seasw/images/d/d1/ConquerorsHakiImage.png/revision/latest?cb=20241231153256")

_SANS_DETAIL = "Effet non détaillé sur le wiki."
_CARTES = [
    #  cle, nom (= nom du jeu), forme, page du wiki (ou None), description, image
    ("bri_o_tarth", "Bri O. Tarth", "Armament", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/5/51/HCA_Bri.png/revision/latest?cb=20241228075430"),
    ("sir_galahad", "Sir Galahad", "Armament", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/7/71/HCA_Galahad.png/revision/latest?cb=20241228075432"),
    ("sir_gawain", "Sir Gawain", "Armament", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/1/19/HCA_Gawain.png/revision/latest?cb=20241228075432"),
    ("sir_lancelot", "Sir Lancelot", "Armament", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/1/14/HCA_Lancelot.png/revision/latest?cb=20241228075432"),
    ("sie_g_fried", "Sie G. Fried", "Armament", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/4/4e/HCA_Sie.png/revision/latest?cb=20241228075432"),
    ("sir_lannister", "Sir Lannister", "Armament", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/c/cd/Sir_Lannister.png/revision/latest?cb=20250824232403"),
    ("opp_e_heimer", "Opp E. Heimer", "Observation", "Opp_E._Heimer",
     "Future Sight : esquive 8 attaques ; recharge 15 s.",
     "https://static.wikia.nocookie.net/rell-seasw/images/a/a7/OHC_Opp.png/revision/latest?cb=20241228073051"),
    ("new_d_ton", "New D. Ton", "Observation", "New_D._Ton", "Indicateur avant la dernière M1.",
     "https://static.wikia.nocookie.net/rell-seasw/images/b/b7/HCO_New.png/revision/latest?cb=20241228075435"),
    ("ein_s_tein", "Ein S. Tein", "Observation", "Ein_S._Tein", "Sentir la force des adversaires.",
     "https://static.wikia.nocookie.net/rell-seasw/images/1/1b/HCO_Ein.png/revision/latest?cb=20241228075434"),
    ("dar_d_win", "Dar D. Win", "Observation", "Dar_D._Win", "Sentir la présence des adversaires.",
     "https://static.wikia.nocookie.net/rell-seasw/images/0/05/HCO_Dar.png/revision/latest?cb=20241228075434"),
    ("sigma_freud", "Sigma Freud", "Observation", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/d/da/HCO_Sigma.png/revision/latest?cb=20241228075435"),
    ("tom_e_dison", "Tom E. Dison", "Observation", "Tom_E._Dison",
     "L'Evade devient une contre-attaque par saisie.",
     "https://static.wikia.nocookie.net/rell-seasw/images/3/3c/HCO_Tom.png/revision/latest?cb=20241228075435"),
    ("xanda_d_goat", "Xanda D. Goat", "Conqueror", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/8/8c/HCC_Xanda.png/revision/latest?cb=20241228075434"),
    ("julius_c_zar", "Julius C. Zar", "Conqueror", "Julius_C._Zar",
     "Immobilise les ennemis proches et réduit leurs défenses de 15 %.",
     "https://static.wikia.nocookie.net/rell-seasw/images/7/71/HCC_Julius.png/revision/latest?cb=20241228075434"),
    ("geng_d_khan", "Geng D. Khan", "Conqueror", "Geng_D._Khan",
     "Quand le joueur est mis à terre : explosion de Haki qui neutralise les attaquants 10 s.",
     "https://static.wikia.nocookie.net/rell-seasw/images/3/3b/HCC_Geng.png/revision/latest?cb=20241228075432"),
    ("nap_o_leon", "Nap O. Leon", "Conqueror", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/e/ea/HCC_Nap.png/revision/latest?cb=20241228075434"),
    ("go_d_zilla", "Go D. Zilla", "Conqueror", "Go_D._Zilla",
     "Étourdit tout le monde, coupe les transformations, met les touches de tous en recharge.",
     "https://static.wikia.nocookie.net/rell-seasw/images/a/a7/HCC_Go.png/revision/latest?cb=20241228075434"),
]
for _c, _n, _forme, _page, _d, _img in _CARTES:
    el("carte_haki", _c, _n, _n, _d, categorie=_forme, source=WIKI + (_page or "Haki"), image=_img)

# ── Posters (passifs « Potential ») : liste des modèles du wiki, à vérifier ──
_POSTERS = [
    #  cle, nom (= nom du jeu), catégorie, page du wiki (ou None), description, image
    ("alpha_clasher", "Alpha Clasher", "Fierce", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/9/9c/AlphaClasherMASK.png/revision/latest?cb=20250722100507"),
    ("m1_god", "M1 God", "Fierce", "M1_God",
     "Prolonge le combo de M1 : écrase, rebondit, téléporte près de l'adversaire sur la dernière M1.",
     "https://static.wikia.nocookie.net/rell-seasw/images/d/df/M1GodMASK.png/revision/latest?cb=20250722100508"),
    ("full_stack", "Full Stack", "Fierce", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/1/1a/FullStackMASK.png/revision/latest?cb=20250722100508"),
    ("faster_punch", "Faster Punch", "Fierce", "Faster_Punch",
     "Strong Punch plus rapide et de plus longue portée.",
     "https://static.wikia.nocookie.net/rell-seasw/images/8/86/FasterPunchMASK.png/revision/latest?cb=20250722100508"),
    ("strong_puncher", "Strong Puncher", "Fierce", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/b/bf/StrongPunchMASK.png/revision/latest?cb=20250722100508"),
    ("down_god", "Down God", "Fierce", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/7/79/DownGodMASK.png/revision/latest?cb=20250811060232"),
    ("flash_dash", "Flash Dash", "Agile", "Flash_Dash",
     "Dash invisible, images rémanentes et traînée noire.",
     "https://static.wikia.nocookie.net/rell-seasw/images/9/9a/Poster_FlashDash.png/revision/latest?cb=20250607061101"),
    ("geppo_master", "Geppo Master", "Agile", "Geppo_Master", "Deux sauts Geppo de plus.",
     "https://static.wikia.nocookie.net/rell-seasw/images/b/ba/GeppoMasterMASK.png/revision/latest?cb=20250722095707"),
    ("wall_bouncer", "Wall Bouncer", "Agile", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/a/af/WallBouncerMASK.png/revision/latest?cb=20260115043428"),
    ("ronaldo_trip", "Ronaldo Trip", "Agile", "Ronaldo_Trip",
     "La glissade fait trébucher l'adversaire (3 dégâts).",
     "https://static.wikia.nocookie.net/rell-seasw/images/2/2f/RonaldoTripMASK.png/revision/latest?cb=20250722100508"),
    ("jumper", "Jumper", "Agile", "Jumper", "Double saut plus haut.",
     "https://static.wikia.nocookie.net/rell-seasw/images/4/45/JumperMASK.png/revision/latest?cb=20250722101459"),
    ("mr_widestep", "Mr Widestep", "Agile", "Mr_Widestep", "Portée du dash augmentée.",
     "https://static.wikia.nocookie.net/rell-seasw/images/2/29/MrWidestepMASK.png/revision/latest?cb=20250722095707"),
    ("sir_pitcher", "Sir Pitcher", "Agile", "Sir_Pitcher",
     "Après une projection : 3 Geppo Dash puis un écrasement.",
     "https://static.wikia.nocookie.net/rell-seasw/images/6/6d/SirPtcherMASK.png/revision/latest?cb=20250722095708"),
    ("strong_tilt", "Strong Tilt", "Agile", "Strong_Tilt",
     "Down Tilt : combo de M1 complet sans briser la garde.",
     "https://static.wikia.nocookie.net/rell-seasw/images/a/a9/StrongTiltMASK.png/revision/latest?cb=20250722095708"),
    ("auto_parry", "Auto Parry", "Tactic", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/6/67/AutoParryMASK.png/revision/latest?cb=20250722101101"),
    ("parry_god", "Parry God", "Tactic", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/2/2f/ParryGodMASK.png/revision/latest?cb=20250722101103"),
    ("quick_parry", "Quick Parry", "Tactic", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/c/cf/QuickParryMASK.png/revision/latest?cb=20250722101103"),
    ("evade_god", "Evade God", "Tactic", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/c/c1/EvadeGodMASK.png/revision/latest?cb=20250722101103"),
    ("parryingan", "Parryingan", "Tactic", None, _SANS_DETAIL,
     "https://static.wikia.nocookie.net/rell-seasw/images/8/82/ParryinganMASK.png/revision/latest?cb=20250722101103"),
]
for _c, _n, _cat, _page, _d, _img in _POSTERS:
    el("poster", _c, _n, _n, _d, categorie=_cat, statut="a_verifier", source=WIKI + (_page or "Posters"),
       image=_img)

# ── Styles de combat (wiki : « not completely verified ») ──
_STYLE = "Un des 4 styles connus (liste du wiki, non vérifiée)."
el("style", "black_leg", "Black Leg", "Black Leg", _STYLE, statut="a_verifier", source=WIKI + "Fighting_Styles")
el("style", "electro", "Electro", "Electro",
   _STYLE + " Le wiki le lie aux Beastman (anciennement Mink).", statut="a_verifier",
   source=WIKI + "Fighting_Styles")
el("style", "rokushiki", "Rokushiki", "Rokushiki", _STYLE, statut="a_verifier", source=WIKI + "Fighting_Styles")
el("style", "dragon_claw", "Dragon Claw", "Dragon Claw", _STYLE, statut="a_verifier",
   source=WIKI + "Fighting_Styles")

# ── Armes : nommées dans Movie 3 (jamais les noms provisoires du wiki) + les 4 classes d'armes ──
el("arme", "katana", "Katana", "Katana", "Arme montrée dans Movie 3.", categorie="Arme", nouveau=True)
el("arme", "dagger", "Dague", "Dagger", "Arme aperçue dans Movie 3 ; nom exact à vérifier.",
   categorie="Arme", statut="a_verifier", nouveau=True)
el("arme", "yahu_great_sword", "Yahu Great Sword", "Yahu Great Sword",
   "Grande épée montrée dans Movie 3 (Yahu : boss Léviathan volcanique).", categorie="Arme", nouveau=True)
el("arme", "light", "Armes légères", "Light",
   "Classe d'arme : rapides et petites ; Q Spec de moindre portée.",
   categorie="Classe d'arme", statut="a_verifier", source=WIKI + "Weapons",
   image="https://static.wikia.nocookie.net/rell-seasw/images/b/bc/LightWeaponsIcon.png/revision/latest?cb=20250709043922")
el("arme", "medium", "Armes moyennes", "Medium",
   "Classe d'arme : équilibre entre vitesse, portée et dégâts.",
   categorie="Classe d'arme", statut="a_verifier", source=WIKI + "Weapons",
   image="https://static.wikia.nocookie.net/rell-seasw/images/b/bb/MediumWeaponsIcon.png/revision/latest?cb=20250709043852")
el("arme", "heavy", "Armes lourdes", "Heavy",
   "Classe d'arme : lentes et grosses ; Q Spec de plus longue portée.",
   categorie="Classe d'arme", statut="a_verifier", source=WIKI + "Weapons",
   image="https://static.wikia.nocookie.net/rell-seasw/images/a/a1/HeavyWeaponsIcon.png/revision/latest?cb=20250709043351")
el("arme", "ranged", "Armes à distance", "Ranged",
   "Classe d'arme : à distance, munitions limitées. La classe principale correspondante s'appelle "
   "désormais Gunman.",
   categorie="Classe d'arme", statut="a_verifier", source=WIKI + "Weapons",
   image="https://static.wikia.nocookie.net/rell-seasw/images/9/92/RangedWeaponsIcon.png/revision/latest?cb=20250709043906")

# ── Équipement ──
el("equipement", "spyglass", "Longue-vue", "Spyglass",
   "Observer au loin ; avec le talent Navigation, repère les apparitions rares. Appelée Telescope "
   "sur le wiki.", source=WIKI + "Equipment",
   image="https://static.wikia.nocookie.net/rell-seasw/images/6/6c/Telescope.png/revision/latest?cb=20250621131530")
el("equipement", "snail_phone", "Escargot-téléphone", "Snail Phone",
   "Appeler ou écrire aux joueurs du même serveur. Appelé Den Den Mushi sur le wiki.",
   source=WIKI + "Den_Den_Mushi",
   image="https://static.wikia.nocookie.net/rell-seasw/images/9/95/DenDenMushi.png/revision/latest?cb=20250621131113")
el("equipement", "ship_in_a_bottle", "Navire en bouteille", "Ship in a bottle",
   "Fait apparaître son navire ou son sous-marin ; ouvre le constructeur du navire.",
   source=WIKI + "Ship_in_a_bottle",
   image="https://static.wikia.nocookie.net/rell-seasw/images/a/a6/ShipInABottle1%28AI_upcalled%29.png/revision/latest?cb=20250708142838")
el("equipement", "lock_pick", "Crochet de serrure", "Lock Pick",
   "Ouvre coffres et portes par un mini-jeu ; un échec casse le crochet.", source=WIKI + "Lock_Pick",
   image="https://static.wikia.nocookie.net/rell-seasw/images/e/ea/PickLock.png/revision/latest?cb=20250621130856")
el("equipement", "shovel", "Pelle", "Shovel", "Chasse au trésor : déterre des coffres.",
   source=WIKI + "Shovel",
   image="https://static.wikia.nocookie.net/rell-seasw/images/e/ee/Shovel1.png/revision/latest?cb=20250719030541")
el("equipement", "paraglider", "Parapente", "Paraglider",
   "Planer depuis un point haut, sans dégâts de chute.", source=WIKI + "Paraglider",
   image="https://static.wikia.nocookie.net/rell-seasw/images/9/9a/Paraglider.png/revision/latest?cb=20250621131234")
el("equipement", "compass", "Boussole", "Compass",
   "Se repérer et trouver son île ; améliorable avec le talent Navigation.", source=WIKI + "Equipment",
   image="https://static.wikia.nocookie.net/rell-seasw/images/9/92/Compass.png/revision/latest?cb=20250708182551")
el("equipement", "fishing_rod", "Canne à pêche", "Fishing rod",
   "Pêche en mini-jeu ; Movie 3 montre la canne à Léviathan. Aucune icône officielle.",
   source=WIKI + "Fishing_rod")
el("equipement", "grappling_hook", "Grappin", "Grappling hook",
   "S'accroche aux murs et aux tyroliennes. Aucune icône officielle.", source=WIKI + "Grappling_hook")
el("equipement", "traders_bag", "Sac de marchand", "Traders bag",
   "Un sac posé au sol avec une étiquette de prix, pour échanger.", statut="a_verifier",
   source=WIKI + "Traders_bag",
   image="https://static.wikia.nocookie.net/rell-seasw/images/1/1a/TradersBag.png/revision/latest?cb=20250808081915")

# ── Enchantements (obtenus par l'artisanat ; à vérifier) ──
_ENCH = "Enchantement d'arme : les M1 déclenchent un effet élémentaire. "
el("enchantement", "fire", "Feu", "Fire", _ENCH + "Brûlure.", statut="a_verifier", source=WIKI + "Enchants")
el("enchantement", "ice", "Glace", "Ice", _ENCH + "Détail inconnu.", statut="a_verifier", source=WIKI + "Enchants")
el("enchantement", "poison", "Poison", "Poison", _ENCH + "Détail inconnu.", statut="a_verifier",
   source=WIKI + "Enchants")
el("enchantement", "lightning", "Foudre", "Lightning", _ENCH + "Détail inconnu.", statut="a_verifier",
   source=WIKI + "Enchants")
el("enchantement", "sea_prism", "Sea Prism", "Sea Prism",
   _ENCH + "Agit sur les utilisateurs de God Fruits : fort contre eux.", statut="a_verifier",
   source=WIKI + "Enchants")

# ── Navires (Movie 3) ──
_STATS = " Stats d'un navire (à vérifier) : Speed, Armour, Cannons, Turn Speed, Ram Strength, Health."
el("navire", "sloop", "Sloop", "Sloop", "Navire montré dans Movie 3." + _STATS, categorie="Navire",
   source=WIKI + "Sailing")
el("navire", "caravel", "Caravelle", "Caravel", "Navire cité par le wiki." + _STATS, categorie="Navire",
   statut="a_verifier", source=WIKI + "Sailing")
el("navire", "galleon", "Galion", "Galleon", "Navire cité par le wiki." + _STATS, categorie="Navire",
   statut="a_verifier", source=WIKI + "Sailing")
el("navire", "sovereign", "Sovereign", "Sovereign",
   "Navire préconstruit de Movie 3 ; le second mot de son nom est inaudible." + _STATS,
   categorie="Préconstruit", nouveau=True)
el("navire", "submarine", "Sous-marin", "Submarine",
   "Explore les 7 couches de profondeur ; invoqué sous l'eau par la bouteille.",
   categorie="Sous-marin", source=WIKI + "Submarines")

# ── Pièces de navire (emplacements du constructeur) et canons — à vérifier ──
el("piece_navire", "sails", "Voiles", "Sails",
   "Emplacement des voiles (pièce de base : Basic Sail) ; voiles à l'emblème de l'équipage.",
   categorie="Emplacement", statut="a_verifier", source=WIKI + "Ship_Customisation",
   image="https://static.wikia.nocookie.net/rell-seasw/images/7/79/Sailsicon.png/revision/latest?cb=20260624153312")
el("piece_navire", "cannons", "Canons", "Cannons",
   "Emplacement des canons (Basic, Heavy, Burst, Mortar).",
   categorie="Emplacement", statut="a_verifier", source=WIKI + "Ship_Customisation",
   image="https://static.wikia.nocookie.net/rell-seasw/images/b/bf/Canonicon.png/revision/latest?cb=20260624152721")
el("piece_navire", "steering_wheel", "Roue de gouvernail", "Steering Wheel",
   "Commande principale du navire, en mer et dans le ciel.",
   categorie="Emplacement", statut="a_verifier", source=WIKI + "Steering_Wheel",
   image="https://static.wikia.nocookie.net/rell-seasw/images/a/a4/SteeringWheelicon.png/revision/latest?cb=20260624153832")
el("piece_navire", "material", "Matériau", "Material",
   "Matériau de la coque (pièce de base : Wood Plank).",
   categorie="Emplacement", statut="a_verifier", source=WIKI + "Ship_Customisation",
   image="https://static.wikia.nocookie.net/rell-seasw/images/9/9a/Materialshipicon.png/revision/latest?cb=20260624154055")
el("piece_navire", "bow", "Proue", "Bow (Front)",
   "Avant du navire : figure de proue (Figurehead).",
   categorie="Emplacement", statut="a_verifier", source=WIKI + "Ship_Customisation",
   image="https://static.wikia.nocookie.net/rell-seasw/images/1/18/Bowfrontshipicon.png/revision/latest?cb=20260624154410")
el("piece_navire", "midship", "Milieu", "Midship (Middle)",
   "Milieu du navire : grand mât (Main Mast).",
   categorie="Emplacement", statut="a_verifier", source=WIKI + "Ship_Customisation",
   image="https://static.wikia.nocookie.net/rell-seasw/images/b/bf/Middleshipicon.png/revision/latest?cb=20260624154803")
el("piece_navire", "stern", "Poupe", "Stern (Back)",
   "Arrière du navire : gouvernail (Rudder).",
   categorie="Emplacement", statut="a_verifier", source=WIKI + "Ship_Customisation",
   image="https://static.wikia.nocookie.net/rell-seasw/images/c/c2/Sternbackicon.png/revision/latest?cb=20260624155108")
el("piece_navire", "basic_cannon", "Canon de base", "Basic Cannon",
   "Tire 1 boulet, portée moyenne (supposée).",
   categorie="Canon", statut="a_verifier", source=WIKI + "Cannon",
   image="https://static.wikia.nocookie.net/rell-seasw/images/1/10/ShipCanonIcon1.png/revision/latest?cb=20260625152648")
el("piece_navire", "heavy_cannon", "Canon lourd", "Heavy Cannon",
   "Tire 1 boulet, gros dégâts, courte portée (supposée).",
   categorie="Canon", statut="a_verifier", source=WIKI + "Cannon",
   image="https://static.wikia.nocookie.net/rell-seasw/images/3/30/ShipHeavyCanonIcon2.png/revision/latest?cb=20260625153151")
el("piece_navire", "burst_cannon", "Canon à rafale", "Burst Cannon",
   "Tire 3 boulets à la fois, longue portée (supposée). Aucune icône officielle.",
   categorie="Canon", statut="a_verifier", source=WIKI + "Cannon")
el("piece_navire", "mortar_cannon", "Mortier", "Mortar Cannon",
   "Tir en cloche ; on peut y grimper pour être projeté sur un navire ennemi. Aucune icône officielle.",
   categorie="Canon", statut="a_verifier", source=WIKI + "Cannon")

# ── Montures : les 3 classes, puis la liste du wiki (à vérifier) et l'abeille de Movie 3 ──
_CLASSES_MONTURE = {"Terrestrial": "Terrestre", "Aquatic": "Aquatique", "Aerial": "Aérienne"}
el("monture", "terrestrial", "Terrestre", "Terrestrial", "Classe de monture : se déplace sur terre.",
   categorie="Classe", statut="a_verifier", source=WIKI + "Mounts",
   image="https://static.wikia.nocookie.net/rell-seasw/images/c/c7/TerrestrialMountIcon.png/revision/latest?cb=20250718134100")
el("monture", "aquatic", "Aquatique", "Aquatic", "Classe de monture : se déplace dans l'eau.",
   categorie="Classe", statut="a_verifier", source=WIKI + "Mounts",
   image="https://static.wikia.nocookie.net/rell-seasw/images/4/48/AquaticMountIcon.png/revision/latest?cb=20250718134100")
el("monture", "aerial", "Aérienne", "Aerial", "Classe de monture : se déplace dans le ciel.",
   categorie="Classe", statut="a_verifier", source=WIKI + "Mounts",
   image="https://static.wikia.nocookie.net/rell-seasw/images/6/6f/AerialMountIcon.png/revision/latest?cb=20250718134059")
_MONTURES = [
    #  cle, nom, nom_en (= fichier <nom_en sans espace>MountDisplay.png), classes du wiki, précision
    ("blu", "Blu", "Blu", "Terrestrial/Aerial", ""),
    ("cat", "Chat", "Cat", "Terrestrial", ""),
    ("crab", "Crabe", "Crab", "Aquatic", ""),
    ("deer", "Cerf", "Deer", "Terrestrial", ""),
    ("dragon", "Dragon", "Dragon", "Terrestrial/Aerial", ""),
    ("flying_fish", "Poisson volant", "Flying Fish", "Aquatic/Aerial", ""),
    ("fox", "Renard", "Fox", "Terrestrial", ""),
    ("frog", "Grenouille", "Frog", "Terrestrial/Aquatic", ""),
    ("mammoth", "Mammouth", "Mammoth", "Terrestrial", ""),
    ("octopus", "Pieuvre", "Octopus", "Aquatic", ""),
    ("owl", "Hibou", "Owl", "Terrestrial/Aerial", " Une place."),
    ("rooster", "Coq", "Rooster", "Terrestrial", ""),
    ("shark", "Requin", "Shark", "Aquatic", ""),
    ("spider", "Araignée", "Spider", "Terrestrial", ""),
    ("thragg", "Thragg", "Thragg", "Terrestrial", ""),
    ("whale", "Baleine", "Whale", "Aquatic",
     " Deux places ; obtenue avec l'abonnement Gold/Silver Supporter du Discord RELL Games "
     "(abonnements arrêtés le 30/11/2025)."),
]
for _c, _n, _ne, _cl, _plus in _MONTURES:
    _fr = [_CLASSES_MONTURE[x] for x in _cl.split("/")]
    _desc = "Monture " + " et ".join(x.lower() for x in _fr) + " (liste du wiki)." + _plus
    el("monture", _c, _n, _ne, _desc, categorie=" · ".join(_fr), statut="a_verifier", source=WIKI + "Mounts",
       image="api:" + _ne.replace(" ", "") + "MountDisplay.png")
el("monture", "bee", "Abeille", "Bee", "Monture montrée dans Movie 3. Aucune image officielle.", nouveau=True)

# ── Monnaies (Movie 3) ──
el("monnaie", "relli", "Relli", "Relli", "Monnaie principale. Anciennement RELL Coins.",
   source=WIKI + "Currencies",
   image="https://static.wikia.nocookie.net/rell-seasw/images/0/03/RELLCoin.png/revision/latest?cb=20241229144543")
el("monnaie", "tickets", "Tickets", "Tickets", "Monnaie rare (Fruit Tournament).", nouveau=True)
el("monnaie", "randomize", "Randomize", "Randomize", "Tirages (« spins »).", nouveau=True)

# ── Logos officiels (site/logos/<cle>.webp) ──
LOGOS = [
    #  cle, titre, adresse (API thumbnails de Roblox : JSON → imageUrl ; sinon l'image), page d'origine
    ("rellseas_jeu", "Icône du jeu RELL Seas (Roblox)",
     "https://thumbnails.roblox.com/v1/games/icons?universeIds=2738929784&size=512x512&format=Png&isCircular=false",
     "https://www.roblox.com/communities/11020595/RELL-Seas"),
    ("rellseas_groupe", "Groupe Roblox « RELL Seas » (11020595)",
     "https://thumbnails.roblox.com/v1/groups/icons?groupIds=11020595&size=420x420&format=Png&isCircular=false",
     "https://www.roblox.com/communities/11020595/RELL-Seas"),
    ("rellgames_groupe", "Groupe studio « RELL GAMES » (4939446)",
     "https://thumbnails.roblox.com/v1/groups/icons?groupIds=4939446&size=420x420&format=Png&isCircular=false",
     "https://www.roblox.com/communities/4939446"),
    ("rellseas_discord", "Icône du serveur Discord RELL Seas",
     "https://cdn.discordapp.com/icons/1159565695294636233/097bc6b1f30ec16415317fe383ba19ef.png?size=512",
     "https://discord.gg/RELLSEAS"),
]


# ─────────────────────────────── 1. Téléchargement ───────────────────────────────
SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "PNG", "png"),
    (b"\xff\xd8\xff", "JPEG", "jpg"),
    (b"GIF87a", "GIF", "gif"),
    (b"GIF89a", "GIF", "gif"),
)


class Refus(Exception):
    """Un fichier ou une réponse refusés : rien n'en est gardé, la raison est notée."""


#  Le CDN des images du wiki peut répondre aux outils par un défi anti-robot (Cloudflare,
#  `Cf-Mitigated: challenge`). On ne le contourne JAMAIS (ni faux navigateur, ni boucle de
#  reprises) : l'hôte est mis de côté pour la séance et les images passent par `--depuis`.
DEFI = "défi anti-robot du CDN du wiki (Cloudflare) : non contourné"


def _maintenant() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hote_permis(url: str) -> bool:
    morceaux = urllib.parse.urlsplit(url)
    hote = (morceaux.hostname or "").lower()
    return morceaux.scheme == "https" and (hote in HOTES or hote.endswith(".rbxcdn.com"))


def type_reel(octets: bytes):
    """Le format d'après les octets magiques (jamais d'après l'extension ni l'en-tête HTTP)."""
    for signature, fmt, ext in SIGNATURES:
        if octets.startswith(signature):
            return fmt, ext
    if len(octets) >= 12 and octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "WEBP", "webp"
    return None


def verifier_image(octets: bytes) -> dict:
    """Octets magiques, taille, ouverture complète par Pillow, dimensions raisonnables."""
    if not OCTETS_MIN <= len(octets) <= OCTETS_MAX:
        raise Refus(f"taille anormale ({len(octets)} octets)")
    reel = type_reel(octets)
    if reel is None:
        raise Refus("pas une image (octets magiques inconnus)")
    fmt, ext = reel
    try:
        with Image.open(io.BytesIO(octets)) as im:
            im.verify()
        with Image.open(io.BytesIO(octets)) as im:
            im.load()
            largeur, hauteur, format_lu, mode = im.width, im.height, im.format, im.mode
    except Exception as ex:  # Pillow lève des types variés sur un fichier abîmé : tous refusés
        raise Refus(f"Pillow ne l'ouvre pas ({type(ex).__name__})") from ex
    if format_lu != fmt:
        raise Refus(f"format incohérent ({fmt} selon les octets, {format_lu} selon Pillow)")
    if not (16 <= largeur <= COTE_MAX and 16 <= hauteur <= COTE_MAX):
        raise Refus(f"dimensions anormales ({largeur}×{hauteur})")
    return {"format": fmt, "ext": ext, "largeur": largeur, "hauteur": hauteur, "mode": mode,
            "octets": len(octets), "sha256": hashlib.sha256(octets).hexdigest()}


class Reseau:
    """Une requête à la fois, une pause entre deux, quelques reprises sur 429/5xx."""

    def __init__(self, hors_ligne: bool):
        self.hors_ligne = hors_ligne
        self._derniere = 0.0
        self.requetes = 0
        self.bloques: set[str] = set()

    def get(self, url: str, accept: str) -> tuple[bytes, str, str]:
        if self.hors_ligne:
            raise Refus("hors ligne demandé (--hors-ligne)")
        if not _hote_permis(url):
            raise Refus("hôte non autorisé")
        hote = urllib.parse.urlsplit(url).hostname
        if hote in self.bloques:
            raise Refus(DEFI)
        derniere_erreur = "inconnue"
        for essai in range(3):
            attente = PAUSE - (time.monotonic() - self._derniere)
            if attente > 0:
                time.sleep(attente)
            self._derniere = time.monotonic()
            self.requetes += 1
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            try:
                with urllib.request.urlopen(req, timeout=30) as rep:
                    finale = rep.geturl()
                    if not _hote_permis(finale):
                        raise Refus("redirection vers un hôte non autorisé")
                    octets = rep.read(OCTETS_MAX + 1)
                    return octets, finale, rep.headers.get("Content-Type", "")
            except urllib.error.HTTPError as ex:
                if (ex.headers.get("Cf-Mitigated") or "").lower() == "challenge":
                    self.bloques.add(hote)
                    raise Refus(DEFI) from None
                derniere_erreur = f"HTTP {ex.code}"
                if ex.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as ex:
                derniere_erreur = type(ex).__name__
            time.sleep(3 * (essai + 1))
        raise Refus(f"téléchargement impossible ({derniere_erreur})")


def nom_fichier_wiki(url: str) -> str:
    """`…/images/b/bb/Cookingicon.png/revision/latest?cb=…` → `Cookingicon.png`."""
    morceaux = urllib.parse.urlsplit(url).path.split("/")
    i = morceaux.index("revision") if "revision" in morceaux else len(morceaux)
    return urllib.parse.unquote(morceaux[i - 1])


def page_fichier_wiki(nom: str) -> str:
    return WIKI + "File:" + urllib.parse.quote(nom.replace(" ", "_"), safe="()_.,-")


def adresses_montures(reseau: Reseau, fichiers: list[str]) -> dict:
    """L'adresse EXACTE de chaque image de monture, donnée par l'API du wiki (aucune devinée)."""
    params = {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url",
              "titles": "|".join("File:" + f for f in fichiers)}
    octets, _, _ = reseau.get(API_WIKI + "?" + urllib.parse.urlencode(params), "application/json")
    try:
        requete = json.loads(octets.decode("utf-8")).get("query", {})
    except (ValueError, AttributeError) as ex:
        raise Refus("réponse de l'API du wiki illisible") from ex
    trouves = {}
    for page in requete.get("pages", {}).values():
        url = ((page.get("imageinfo") or [{}])[0]).get("url") or ""
        if url and "missing" not in page and urllib.parse.urlsplit(url).hostname == "static.wikia.nocookie.net":
            trouves[page.get("title", "").removeprefix("File:").replace("_", " ")] = url
    return {f: trouves.get(f.replace("_", " ")) for f in fichiers}


def adresse_png_wiki(url: str) -> str:
    """Le wiki sert du WebP aux navigateurs ; `format=original` rend le PNG d'origine."""
    return url + ("&" if "?" in url else "?") + "format=original"


def _image_roblox(reseau: Reseau, api: str) -> str:
    """Les API thumbnails de Roblox répondent `{"data": [{"state", "imageUrl"}]}` : on suit `imageUrl`."""
    for _ in range(4):
        octets, _, _ = reseau.get(api, "application/json")
        try:
            donnee = (json.loads(octets.decode("utf-8")).get("data") or [None])[0] or {}
        except (ValueError, AttributeError) as ex:
            raise Refus("réponse de l'API Roblox illisible") from ex
        if donnee.get("state") == "Completed" and donnee.get("imageUrl"):
            if not _hote_permis(donnee["imageUrl"]):
                raise Refus("imageUrl hors des domaines de Roblox")
            return donnee["imageUrl"]
        if donnee.get("state") not in ("Pending", None):
            raise Refus(f"vignette Roblox indisponible ({donnee.get('state')})")
        time.sleep(3)
    raise Refus("vignette Roblox toujours en attente")


def sources_a_telecharger() -> list[dict]:
    """Toutes les images à obtenir : celles des éléments du catalogue, puis les logos."""
    sources = [{"type": e["type"], "cle": e["cle"], "image": e["image"]} for e in ELEMENTS if e["image"]]
    sources += [{"type": "logo", "cle": c, "image": u, "titre": t, "page": p} for c, t, u, p in LOGOS]
    return sources


def telecharger(cache: Path, hors_ligne: bool, reessayer: bool = False) -> dict:
    """Remplit le cache (un dossier par type) et rend le manifeste {"type/cle": {...}}.
    Un fichier déjà reçu et intact (même source, même empreinte) n'est pas redemandé ; une image
    refusée par le défi anti-robot ne l'est qu'avec `--reessayer` (une requête, puis on s'arrête)."""
    cache.mkdir(parents=True, exist_ok=True)
    chemin_manifeste = cache / "manifeste.json"
    try:
        ancien = json.loads(chemin_manifeste.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ancien = {}
    reseau = Reseau(hors_ligne)
    sources = sources_a_telecharger()
    montures = [s["image"].removeprefix("api:") for s in sources if s["image"].startswith("api:")]
    api_montures = dict(ancien.get("_api_montures") or {})
    if any(not api_montures.get(m) for m in montures):
        try:
            api_montures.update({f: u for f, u in adresses_montures(reseau, montures).items() if u})
        except Refus as ex:
            print(f"[ICONES] API du wiki (montures) : {ex}")
    manifeste = {"_api_montures": api_montures}
    for s in sources:
        cle = f"{s['type']}/{s['cle']}"
        image = s["image"]
        entree = {"type": s["type"], "cle": s["cle"], "url_source": image}
        if image.startswith("api:"):
            entree["fichier_api"] = image.removeprefix("api:")
            image = api_montures.get(entree["fichier_api"]) or ""
            entree["url_source"] = image
            if not image:
                entree["erreur"] = "l'API du wiki ne donne aucune adresse exacte"
                manifeste[cle] = entree
                print(f"[ICONES] écarté {cle} : {entree['erreur']}")
                continue
        avant = ancien.get(cle) or {}
        if avant.get("erreur") == DEFI and avant.get("url_source") == image and not reessayer:
            manifeste[cle] = avant
            continue
        fichier = cache / s["type"] / f"{s['cle']}.{avant.get('ext', 'png')}"
        if avant.get("url_source") == image and not avant.get("erreur") and fichier.is_file():
            try:
                if verifier_image(fichier.read_bytes())["sha256"] == avant.get("sha256"):
                    manifeste[cle] = avant
                    continue
            except Refus:
                pass
        if s["type"] == "logo":
            entree["titre"], entree["page"] = s["titre"], s["page"]
        try:
            if urllib.parse.urlsplit(image).hostname == "thumbnails.roblox.com":
                adresse = _image_roblox(reseau, image)
            elif urllib.parse.urlsplit(image).hostname == "static.wikia.nocookie.net":
                adresse = adresse_png_wiki(image)
                entree["fichier_wiki"] = nom_fichier_wiki(image)
                entree["page_fichier"] = page_fichier_wiki(entree["fichier_wiki"])
            else:
                adresse = image
            octets, finale, ctype = reseau.get(adresse, "image/png,image/*;q=0.8")
            infos = verifier_image(octets)
            if ctype and not ctype.lower().startswith("image/"):
                raise Refus(f"en-tête Content-Type inattendu ({ctype})")
            dossier = cache / s["type"]
            dossier.mkdir(parents=True, exist_ok=True)
            for vieux in dossier.glob(f"{s['cle']}.*"):
                vieux.unlink()
            (dossier / f"{s['cle']}.{infos['ext']}").write_bytes(octets)
            entree.update(infos, url_telechargee=adresse, url_finale=finale, content_type=ctype,
                          date=_maintenant())
            print(f"[ICONES] reçu {cle} ({infos['largeur']}×{infos['hauteur']}, {infos['octets']} o)")
        except Refus as ex:
            entree["erreur"] = str(ex)
            print(f"[ICONES] écarté {cle} : {ex}")
        manifeste[cle] = entree
    chemin_manifeste.write_text(json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ICONES] {reseau.requetes} requête(s) ; manifeste : {chemin_manifeste}")
    return manifeste


# ─────────────────────────── 1 bis. Import d'images enregistrées à la main ───────────────────────────
PAGE_MANUELLE = "rell_seas_images.html"


class _Images(html.parser.HTMLParser):
    """Relève les `<img data-cle="type/cle" src="…">` d'une page enregistrée par un navigateur."""

    def __init__(self):
        super().__init__()
        self.images: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img" and a.get("data-cle") and a.get("src"):
            self.images[a["data-cle"]] = a["src"]


def _attendues() -> dict:
    """type/cle → adresse attendue (dossier de recherche, ou adresse exacte donnée par l'API du wiki)."""
    return {f"{s['type']}/{s['cle']}": s["image"] for s in sources_a_telecharger()}


def importer(depuis: Path, cache: Path, manifeste: dict) -> dict:
    """Images enregistrées par le navigateur du fondateur : soit la page d'aide enregistrée en
    « Page Web complète » (Ctrl+S), soit un dossier de fichiers nommés `<type>__<cle>.png` ou du nom
    du fichier du wiki (`Cookingicon.png`). Chaque fichier passe les mêmes vérifications."""
    attendues = _attendues()
    trouves: dict[str, Path] = {}
    if depuis.is_file():
        lecteur = _Images()
        lecteur.feed(depuis.read_text(encoding="utf-8", errors="replace"))
        base = depuis.parent.resolve()
        for cle, src in lecteur.images.items():
            if cle not in attendues or re.match(r"^[a-z][a-z0-9+.-]*:", src, re.I):
                continue                       # encore une adresse web : image non enregistrée
            chemin = (base / urllib.parse.unquote(src).replace("\\", "/")).resolve()
            if base in chemin.parents and chemin.is_file():
                trouves[cle] = chemin
    elif depuis.is_dir():
        par_nom = {}
        for cle, url in attendues.items():
            par_nom[cle.replace("/", "__").lower()] = cle
            if url and not url.startswith("api:") and "static.wikia.nocookie.net" in url:
                par_nom[nom_fichier_wiki(url).lower()] = cle
            elif url.startswith("api:"):
                par_nom[url.removeprefix("api:").lower()] = cle
        for f in sorted(depuis.iterdir()):
            cle = par_nom.get(f.name.lower()) or par_nom.get(f.stem.lower())
            if f.is_file() and cle:
                trouves[cle] = f
    else:
        raise SystemExit(f"[ICONES] --depuis : introuvable ({depuis})")
    for cle, chemin in sorted(trouves.items()):
        type_, cle_el = cle.split("/", 1)
        entree = {"type": type_, "cle": cle_el, "url_source": (manifeste.get(cle) or {}).get("url_source")
                  or attendues[cle]}
        try:
            octets = chemin.read_bytes()
            infos = verifier_image(octets)
        except (OSError, Refus) as ex:
            print(f"[ICONES] import refusé {cle} : {ex}")
            continue
        dossier = cache / type_
        dossier.mkdir(parents=True, exist_ok=True)
        for vieux in dossier.glob(f"{cle_el}.*"):
            vieux.unlink()
        (dossier / f"{cle_el}.{infos['ext']}").write_bytes(octets)
        if entree["url_source"] and "static.wikia.nocookie.net" in entree["url_source"]:
            entree["fichier_wiki"] = nom_fichier_wiki(entree["url_source"])
            entree["page_fichier"] = page_fichier_wiki(entree["fichier_wiki"])
            entree["url_telechargee"] = adresse_png_wiki(entree["url_source"])
        entree.update(infos, obtention="enregistrée à la main dans le navigateur du fondateur",
                      date=_maintenant())
        manifeste[cle] = entree
        print(f"[ICONES] importé {cle} ({infos['largeur']}×{infos['hauteur']})")
    (cache / "manifeste.json").write_text(json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifeste


def ecrire_page_manuelle(cache: Path, manifeste: dict) -> Path | None:
    """Page d'aide (hors du dépôt) : les images encore manquantes, chargées par le NAVIGATEUR du
    fondateur ; Ctrl+S « Page Web complète » les enregistre toutes, puis `--depuis` les importe."""
    manquantes = []
    livrees = sorties_presentes()
    for cle, url in _attendues().items():
        entree = manifeste.get(cle) or {}
        url = entree.get("url_source") or url
        if (cle not in livrees and entree.get("erreur") and url
                and urllib.parse.urlsplit(url).hostname == "static.wikia.nocookie.net"):
            manquantes.append((cle, adresse_png_wiki(url)))
    if not manquantes:
        return None
    dossier = cache / "a_enregistrer"
    dossier.mkdir(parents=True, exist_ok=True)
    page = dossier / PAGE_MANUELLE
    cartes = "\n".join(
        f'<figure><img data-cle="{html.escape(c)}" src="{html.escape(u)}" alt="{html.escape(c)}" '
        f'referrerpolicy="no-referrer" loading="eager"><figcaption>{html.escape(c)}</figcaption></figure>'
        for c, u in manquantes)
    page.write_text(f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>RELL Seas — images à enregistrer</title>
<style>body{{font:16px/1.5 Georgia,serif;background:#efe2c4;color:#2b1d12;margin:24px}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
figure{{margin:0;padding:8px;background:#fff8e8;border:1px solid #b99a6b;text-align:center}}
img{{max-width:128px;max-height:128px}}figcaption{{font-size:12px;word-break:break-all}}</style></head>
<body><h1>RELL Seas — {len(manquantes)} images officielles à enregistrer</h1>
<ol><li>Attends que toutes les images soient affichées (aucune case vide).</li>
<li>Ctrl+S, type « Page Web, complète », enregistre dans ce dossier :<br><code>{html.escape(str(dossier))}</code></li>
<li>Puis : <code>python -I outils/icones_rellseas.py --cache "{html.escape(str(cache))}" --depuis "{html.escape(str(page))}"</code></li></ol>
<main>
{cartes}
</main></body></html>
""", encoding="utf-8")
    return page


# ─────────────────────────────── 2. Conversion ───────────────────────────────
SEUIL_ALPHA = 10        # en dessous : pixel vide (ombre presque invisible, bruit de bord)
MARGE_SITE = 0.05       # marge autour du sujet, sur chaque bord, pour les icônes du site
MARGE_DISCORD = 0.02    # au plus près pour Discord : l'émoji s'affiche à 22 px
ENTIER_MAX = 640        # plus grand côté du rendu entier d'une race
LOGO_MAX = 512
PORTRAIT_COTE = 0.38    # côté du portrait d'une race, en fraction de la hauteur du personnage
PORTRAIT_HAUT = -0.03   # marge au-dessus de la tête (cheveux, cornes), en fraction de la hauteur
# Réglages par race après contrôle de la planche : cle -> (centre x, haut, côté) en fractions de la
# boîte du personnage (largeur pour x ; hauteur pour haut et côté). Sans réglage : calcul automatique.
PORTRAITS: dict[str, tuple[float, float, float]] = {}


def ouvrir_rgba(chemin: Path) -> Image.Image:
    with Image.open(chemin) as im:
        im.load()
        return im.convert("RGBA")


def boite_utile(im: Image.Image):
    return im.getchannel("A").point(lambda v: 255 if v > SEUIL_ALPHA else 0).getbbox()


def opaque(im: Image.Image) -> bool:
    return im.getchannel("A").getextrema()[0] == 255


def rogner(im: Image.Image) -> Image.Image:
    boite = boite_utile(im)
    return im.crop(boite) if boite else im


def au_carre(sujet: Image.Image, marge: float) -> Image.Image:
    cote = round(max(sujet.size) * (1 + 2 * marge))
    toile = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
    toile.alpha_composite(sujet, ((cote - sujet.width) // 2, (cote - sujet.height) // 2))
    return toile


def redimensionner(im: Image.Image, taille: tuple[int, int]) -> Image.Image:
    """Lanczos ; Pillow travaille en alpha prémultiplié pour le RGBA : pas de liseré sombre."""
    return im if im.size == taille else im.resize(taille, Image.Resampling.LANCZOS)


def renforcer(im: Image.Image) -> Image.Image:
    """Un léger masque flou après une forte réduction (lisibilité en petit), alpha intact."""
    rgb = im.convert("RGB").filter(ImageFilter.UnsharpMask(radius=0.8, percent=45, threshold=2))
    rgb.putalpha(im.getchannel("A"))
    return rgb


def icone_carree(im: Image.Image, cote: int, marge: float) -> Image.Image:
    carre = au_carre(rogner(im), marge)
    petit = redimensionner(carre, (cote, cote))
    return renforcer(petit) if carre.width >= cote * 2 else petit


def _profil_colonnes(alpha: Image.Image, y0: int, y1: int) -> list[int]:
    """Opacité moyenne de chaque colonne entre les lignes y0 et y1."""
    bande = alpha.crop((0, y0, alpha.width, max(y0 + 1, y1)))
    return list(bande.resize((alpha.width, 1), Image.Resampling.BOX).getdata())


def _centre(profil: list[int], x0: int = 0, x1: int | None = None) -> float:
    x1 = len(profil) if x1 is None else x1
    morceau = profil[x0:x1]
    total = sum(morceau)
    return x0 + sum(i * v for i, v in enumerate(morceau)) / total if total else (x0 + x1) / 2


def portrait(im: Image.Image, cle: str) -> Image.Image:
    """Le haut du corps et le visage d'un rendu de personnage, en carré."""
    sujet = rogner(im)
    w, h = sujet.size
    if h < 1.4 * w and cle not in PORTRAITS:
        return icone_carree(im, COTE_SITE, MARGE_SITE)        # déjà un buste : rien à couper
    if cle in PORTRAITS:
        fx, fy, fc = PORTRAITS[cle]
        cx, haut, cote = fx * w, fy * h, fc * h
    else:
        # Le haut de la tête : première ligne opaque sur l'AXE du corps (des ailes ou des cornes
        # plus hautes, sur les côtés, ne trompent pas), puis le centre de la tête autour de cet axe.
        alpha = sujet.getchannel("A")
        axe = round(_centre(_profil_colonnes(alpha, 0, h)))
        demi = max(2, round(w * 0.05))
        lignes = list(alpha.crop((max(0, axe - demi), 0, min(w, axe + demi), h))
                      .resize((1, h), Image.Resampling.BOX).getdata())
        tete = next((y for y, v in enumerate(lignes) if v > 40), 0)
        fenetre = round(w * 0.18)
        cx = _centre(_profil_colonnes(alpha, tete, tete + round(h * 0.08)),
                     max(0, axe - fenetre), min(w, axe + fenetre))
        haut, cote = tete + PORTRAIT_HAUT * h, PORTRAIT_COTE * h
    g, t = round(cx - cote / 2), round(haut)
    recadre = sujet.crop((g, t, g + round(cote), t + round(cote)))   # hors du cadre : transparent
    return icone_carree_sans_rognage(recadre, COTE_SITE)


def icone_carree_sans_rognage(im: Image.Image, cote: int) -> Image.Image:
    petit = redimensionner(im, (cote, cote))
    return renforcer(petit) if im.width >= cote * 2 else petit


def rendu_entier(im: Image.Image) -> Image.Image:
    sujet = rogner(im)
    marge = round(max(sujet.size) * 0.02)
    toile = Image.new("RGBA", (sujet.width + 2 * marge, sujet.height + 2 * marge), (0, 0, 0, 0))
    toile.alpha_composite(sujet, (marge, marge))
    if max(toile.size) > ENTIER_MAX:
        k = ENTIER_MAX / max(toile.size)
        toile = redimensionner(toile, (max(1, round(toile.width * k)), max(1, round(toile.height * k))))
    return toile


def _ecrire(chemin: Path, octets: bytes) -> None:
    """N'écrit que si le contenu change : rejouer le script ne salit pas le dépôt."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if not (chemin.is_file() and chemin.read_bytes() == octets):
        chemin.write_bytes(octets)


def ecrire_webp(im: Image.Image, chemin: Path, qualite: int = 90) -> None:
    tampon = io.BytesIO()
    if opaque(im):
        im.convert("RGB").save(tampon, "WEBP", quality=qualite, method=6)
    else:
        im.save(tampon, "WEBP", quality=qualite, alpha_quality=100, method=6)
    _ecrire(chemin, tampon.getvalue())


def ecrire_png(im: Image.Image, chemin: Path) -> None:
    tampon = io.BytesIO()
    im.save(tampon, "PNG", optimize=True)
    _ecrire(chemin, tampon.getvalue())


def nom_discord(type_: str, cle: str) -> str:
    return f"rell_{type_}_{cle}"


def construire(cache: Path, manifeste: dict) -> dict:
    """Toutes les images du site et de Discord, depuis les originaux vérifiés du cache."""
    produits: dict[str, dict] = {}
    for type_, cle_el in _cles_avec_image():
        e = {"type": type_, "cle": cle_el}
        cle = f"{type_}/{cle_el}"
        entree = manifeste.get(cle) or {}
        if not entree.get("sha256") or entree.get("erreur"):
            continue
        original = cache / e["type"] / f"{e['cle']}.{entree['ext']}"
        try:
            octets = original.read_bytes()
            if verifier_image(octets)["sha256"] != entree["sha256"]:
                raise Refus("l'original du cache a changé")
        except (OSError, Refus) as ex:
            print(f"[ICONES] original inutilisable {cle} : {ex}")
            continue
        im = ouvrir_rgba(original)
        sortie: dict[str, Path] = {}
        if e["type"] == "logo":
            logo = im if max(im.size) <= LOGO_MAX else redimensionner(
                im, (round(im.width * LOGO_MAX / max(im.size)), round(im.height * LOGO_MAX / max(im.size))))
            sortie["site"] = DOSSIER_LOGOS / f"{e['cle']}.webp"
            ecrire_webp(logo, sortie["site"], qualite=92)
        else:
            sortie["site"] = DOSSIER_ICONES / e["type"] / f"{e['cle']}.webp"
            if e["type"] == "race":
                ecrire_webp(portrait(im, e["cle"]), sortie["site"])
                sortie["entier"] = DOSSIER_ICONES / e["type"] / f"{e['cle']}_entier.webp"
                ecrire_webp(rendu_entier(im), sortie["entier"])
            else:
                ecrire_webp(icone_carree(im, COTE_SITE, MARGE_SITE), sortie["site"])
            if e["type"] in TYPES_DISCORD:
                nom = nom_discord(e["type"], e["cle"])
                assert len(nom) <= NOM_DISCORD_MAX and nom.startswith("rell_"), nom
                sortie["discord"] = DOSSIER_DISCORD / f"{nom}.png"
                source_discord = portrait(im, e["cle"]) if e["type"] == "race" else im
                ecrire_png(icone_carree(source_discord, COTE_DISCORD, MARGE_DISCORD), sortie["discord"])
        produits[cle] = sortie
    return produits


def sorties_prevues(type_: str, cle: str) -> dict[str, Path]:
    """Les fichiers que ce script fabrique pour un élément (ou un logo)."""
    if type_ == "logo":
        return {"site": DOSSIER_LOGOS / f"{cle}.webp"}
    s = {"site": DOSSIER_ICONES / type_ / f"{cle}.webp"}
    if type_ == "race":
        s["entier"] = DOSSIER_ICONES / type_ / f"{cle}_entier.webp"
    if type_ in TYPES_DISCORD:
        s["discord"] = DOSSIER_DISCORD / f"{nom_discord(type_, cle)}.png"
    return s


def _cles_avec_image() -> list[tuple[str, str]]:
    return [(e["type"], e["cle"]) for e in ELEMENTS if e["image"]] + [("logo", c) for c, *_ in LOGOS]


def sorties_presentes() -> dict[str, dict[str, Path]]:
    """Ce qui existe VRAIMENT sur le disque : le catalogue, les sources et la planche s'y fient
    (une icône déjà livrée reste valable même si l'original n'est plus dans le cache)."""
    presentes = {}
    for type_, cle in _cles_avec_image():
        s = {k: p for k, p in sorties_prevues(type_, cle).items() if p.is_file()}
        if "site" in s:
            presentes[f"{type_}/{cle}"] = s
    return presentes


def nettoyer_obsoletes() -> None:
    """Retire seulement ce qui ne correspond plus à aucun élément illustré (élément supprimé,
    image retirée, clé renommée). Jamais un fichier d'un autre nom : `rell_*.png` et les WebP de
    `site/icones/rell/` uniquement ; les logos ne sont jamais retirés."""
    prevues = {p.resolve() for t, c in _cles_avec_image() for p in sorties_prevues(t, c).values()}
    for f in [*DOSSIER_DISCORD.glob("rell_*.png"), *DOSSIER_ICONES.glob("*/*.webp")]:
        if f.is_file() and f.resolve() not in prevues:
            f.unlink()
            print(f"[ICONES] retiré (obsolète) : {f.relative_to(RACINE).as_posix()}")


# ─────────────────────────────── 3. Catalogue ───────────────────────────────
CLES_TYPE = ("cle", "nom", "nom_en", "champ", "multiple", "ordre")
CLES_ELEMENT = ("type", "cle", "nom", "nom_en", "description", "categorie", "rarete", "icone", "statut",
                "source", "ordre", "actif", "nouveau_movie3", "version")


#  29/10/2026 : un élément « à vérifier » dont le nom EXACT est dit dans une vidéo officielle de RELL (chaîne RELLGames,
#  relevé de `outils/videos_rellseas.py`) passe « confirmé », avec la vidéo et la minute dans sa description. Les mots
#  courants (un « dagger », du « poison », « lightning »…) peuvent être dits dans un autre sens : ils restent à vérifier.
VIDEOS = RACINE / "donnees_jeu" / "rell_videos.json"
AMBIGUS = {"Dagger", "Mammoth", "Poison", "Lightning", "Fire", "Ice", "Sails", "Cannons", "Material", "Light", "Medium",
           "Heavy", "Ranged", "Electro", "Jumper", "Galleon", "Dragon", "Shark", "Whale", "Cat", "Crab", "Fox", "Owl"}


def preuve_video(e: dict) -> dict:
    """L'élément, confirmé par une vidéo officielle si son nom exact y est dit (sinon inchangé)."""
    if e.get("statut") != "a_verifier" or e["nom_en"] in AMBIGUS or not VIDEOS.exists():
        return e
    d = json.loads(VIDEOS.read_text(encoding="utf-8"))
    vus = d["termes"].get(e["nom_en"]) or d["termes"].get(e["nom_en"] + "s")
    if not vus:
        return e
    vid, t = vus[0]
    titre = next((v["titre"] for v in d["videos"] if v["id"] == vid), "vidéo officielle")
    e = dict(e, statut="confirme")
    minute = f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"
    e["description"] = (e["description"] + f" Dit dans « {titre} » ({minute}, "
                        f"youtu.be/{vid}?t={t}).").strip()
    return e


def catalogue(produits: dict) -> dict:
    types = [dict(zip(CLES_TYPE, (c, n, ne, ch, m, i))) for i, (c, n, ne, ch, m) in enumerate(TYPES, 1)]
    rangs: dict[str, int] = {}
    elements = []
    for e in map(preuve_video, ELEMENTS):
        rangs[e["type"]] = rangs.get(e["type"], 0) + 1
        a_icone = "site" in produits.get(f"{e['type']}/{e['cle']}", {})
        elements.append({
            "type": e["type"], "cle": e["cle"], "nom": e["nom"], "nom_en": e["nom_en"],
            "description": e["description"], "categorie": e["categorie"], "rarete": e["rarete"],
            "icone": f"s/icones/rell/{e['type']}/{e['cle']}.webp" if a_icone else "",
            "statut": e["statut"], "source": e["source"], "ordre": rangs[e["type"]], "actif": e.get("actif", True),
            "nouveau_movie3": e["nouveau_movie3"], "version": 1,
        })
    return {"types": types, "elements": elements}


def ecrire_catalogue(donnees: dict) -> None:
    """Un objet par ligne : lisible, et un changement d'élément = une ligne dans le diff."""
    def bloc(nom, liste, fin):
        lignes = [f' "{nom}": [']
        lignes += ["  " + json.dumps(x, ensure_ascii=False) + ("," if i < len(liste) - 1 else "")
                   for i, x in enumerate(liste)]
        return lignes + [" ]" + fin]
    texte = "\n".join(["{", *bloc("types", donnees["types"], ","), *bloc("elements", donnees["elements"], ""),
                       "}"]) + "\n"
    json.loads(texte)
    _ecrire(CATALOGUE, texte.encode("utf-8"))


# ─────────────────────────────── 4. Sources et planche ───────────────────────────────
def _date(iso: str) -> str:
    try:
        return dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%d/%m/%Y %H:%M UTC")
    except (TypeError, ValueError):
        return "—"


def _md(texte: str) -> str:
    return str(texte).replace("|", "\\|")


PROVENANCE_DEBUT = "<!-- provenance-json"
PROVENANCE_FIN = "-->"
CHAMPS_PROVENANCE = ("url_source", "fichier_wiki", "page_fichier", "url_telechargee", "url_finale", "obtention",
                     "titre", "page", "date", "format", "largeur", "hauteur", "octets", "sha256")


def lire_provenance() -> dict:
    """La provenance des images déjà livrées, gardée à la fin de SOURCES.md : si le cache des
    originaux est perdu, les icônes du dépôt restent documentées."""
    try:
        texte = SOURCES_MD.read_text(encoding="utf-8")
        debut = texte.index(PROVENANCE_DEBUT) + len(PROVENANCE_DEBUT)
        return json.loads(texte[debut:texte.index(PROVENANCE_FIN, debut)])
    except (OSError, ValueError):
        return {}


def fusion_provenance(manifeste: dict, presentes: dict) -> dict:
    """Pour chaque image livrée : l'entrée du cache si l'original y est, sinon l'ancienne provenance."""
    ancienne = lire_provenance()
    fusion = {}
    for cle in presentes:
        entree = manifeste.get(cle) or {}
        if not entree.get("sha256") or entree.get("erreur"):
            entree = ancienne.get(cle) or {}
        fusion[cle] = {k: entree[k] for k in CHAMPS_PROVENANCE if entree.get(k) not in (None, "")}
    return fusion


def ecrire_sources(provenance: dict, presentes: dict, manifeste: dict) -> None:
    noms = {f"{e['type']}/{e['cle']}": e for e in ELEMENTS}

    def chemin(p: Path) -> str:
        return p.relative_to(SITE).as_posix() if SITE in p.parents else p.relative_to(RACINE).as_posix()

    def original(m: dict) -> str:
        if not m.get("sha256"):
            return "provenance inconnue | —"
        return f"{m['largeur']}×{m['hauteur']} {m['format']}, {m['octets']} o | `{m['sha256'][:16]}`"

    l = [
        "# Sources des images officielles de RELL Seas",
        "",
        "Visuels du jeu **RELL Seas**, du studio **RELL Games** : icônes et rendus hébergés par le wiki",
        "communautaire RELL Seas (Fandom, https://rellseas.fandom.com), logos servis par Roblox et Discord.",
        "Ils restent la propriété de RELL Games. Ils sont utilisés tels quels (recadrés, mis à l'échelle,",
        "convertis en WebP/PNG) sur le **site privé du clan GoRP**, réservé à son fondateur et à sa",
        "direction, avec l'accord du fondateur (25/10/2026) ; ils ne sont pas redistribués ailleurs.",
        "Les descriptions du catalogue sont des résumés en français ; la page source de chaque élément est",
        "dans `donnees_jeu/rell_catalogue.json` (champ `source`).",
        "",
        "Tout est fabriqué par `outils/icones_rellseas.py`. Chaque original a été vérifié avant toute",
        "conversion : octets magiques, taille, ouverture complète par Pillow, dimensions. L'empreinte",
        "SHA-256 est celle de l'original reçu.",
        "",
        "## Logos (`site/logos/`)",
        "",
        "| Fichier | Logo | Demandé à | Image reçue | Téléchargé le | Original | SHA-256 |",
        "|---|---|---|---|---|---|---|",
    ]
    for c, titre, url, page in LOGOS:
        cle = f"logo/{c}"
        if cle not in presentes:
            raison = (manifeste.get(cle) or {}).get("erreur", "non reçu")
            l.append(f"| — | {_md(titre)} | {url} | non reçu : {_md(raison)} | — | — | — |")
            continue
        m = provenance.get(cle, {})
        l.append(f"| `{chemin(presentes[cle]['site'])}` | {_md(titre)} ({page}) | {url} | "
                 f"{m.get('url_finale', '—')} | {_date(m.get('date'))} | {original(m)} |")
    l += ["", "## Icônes et rendus du catalogue (`site/icones/rell/`, `visuels/icones/rell_*.png`)", "",
          "| Fichier(s) | Élément | Fichier du wiki | Téléchargé le | Original | SHA-256 |",
          "|---|---|---|---|---|---|"]
    attente, sans = [], []
    for cle, e in noms.items():
        if not e["image"]:
            sans.append(e)
            continue
        if cle not in presentes:
            attente.append((e, manifeste.get(cle) or {}))
            continue
        m = provenance.get(cle, {})
        fichiers = "<br>".join(f"`{chemin(p)}`" for p in presentes[cle].values())
        wiki = (f"[{_md(m.get('fichier_wiki'))}]({m.get('page_fichier')}) — {m.get('url_telechargee')}"
                if m.get("fichier_wiki") else m.get("url_telechargee", "—"))
        if m.get("obtention"):
            wiki += f" ({m['obtention']})"
        l.append(f"| {fichiers} | {_md(e['nom'])} ({_md(e['nom_en'])}) | {wiki} | {_date(m.get('date'))} | "
                 f"{original(m)} |")
    l += ["", f"## En attente ({len(attente)})", ""]
    if attente:
        l += ["Listées par le dossier de recherche mais pas encore obtenues. Le CDN des images du wiki",
              "(static.wikia.nocookie.net) répond aux outils automatiques par un défi anti-robot",
              "(Cloudflare) : il n'a pas été contourné. Elles s'importent avec `--depuis` une fois",
              "enregistrées par un navigateur (procédure en tête de `outils/icones_rellseas.py`).", "",
              "| Élément | Adresse (dossier de recherche ou API du wiki) | Raison |", "|---|---|---|"]
        for e, m in attente:
            url = m.get("url_source") or e["image"]
            l.append(f"| {e['type']}/{e['cle']} — {_md(e['nom'])} | {url} | "
                     f"{_md(m.get('erreur', 'non téléchargée'))} |")
    else:
        l.append("Aucune.")
    l += ["", f"## Sans icône ({len(sans)})", "",
          "Le dossier de recherche ne donne aucune icône officielle pour ces éléments : le site affiche",
          "le nom seul. (La page Enchants du wiki montre des images d'enchantements, non retenues par le",
          "dossier : elles n'ont pas été téléchargées.)", ""]
    l += [f"- {e['type']}/{e['cle']} — {e['nom']} ({e['nom_en']})" for e in sans]
    l += ["", PROVENANCE_DEBUT, json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=1),
          PROVENANCE_FIN]
    _ecrire(SOURCES_MD, ("\n".join(l) + "\n").encode("utf-8"))


def ecrire_planche(manifeste: dict, produits: dict) -> None:
    """Planche de contrôle (fichier local, jamais servi) : chaque icône à 32, 64 et 128 px sur
    parchemin et sur bois sombre ; les émojis Discord à 22 et 48 px sur les deux thèmes de Discord."""
    esc = html.escape
    statut_txt = {"confirme": "confirmé", "a_verifier": "à vérifier"}

    def rangee(src, fond, tailles=(32, 64, 128)):
        return (f'<div class="rangee {fond}">' + "".join(
            f'<img src="{esc(src)}" width="{t}" height="{t}" alt="">' for t in tailles) + "</div>")

    blocs = []
    nb = {"icones": 0, "attente": 0, "sans": 0}
    logos = []
    for c, titre, *_ in LOGOS:
        p = produits.get(f"logo/{c}", {}).get("site")
        if p:
            src = "../../logos/" + p.name
            logos.append(f'<article class="carte"><h3>{esc(titre)}</h3>{rangee(src, "parchemin", (48, 96, 192))}'
                         f'{rangee(src, "bois", (48, 96, 192))}</article>')
        else:
            logos.append(f'<article class="carte manque"><h3>{esc(titre)}</h3><p>non reçu</p></article>')
    blocs.append(f'<section><h2>Logos officiels</h2><div class="grille">{"".join(logos)}</div></section>')
    for t_cle, t_nom, t_nom_en, champ, multiple in TYPES:
        cartes = []
        for e in [x for x in ELEMENTS if x["type"] == t_cle]:
            cle = f"{e['type']}/{e['cle']}"
            prod = produits.get(cle, {})
            entete = (f'<h3>{esc(e["nom"])} <small>{esc(e["nom_en"])}</small></h3>'
                      f'<p class="meta"><span class="statut {e["statut"]}">{statut_txt[e["statut"]]}</span>'
                      + (' <span class="m3">nouveau Movie 3</span>' if e["nouveau_movie3"] else "")
                      + (f' · {esc(e["categorie"])}' if e["categorie"] else "") + "</p>")
            if "site" in prod:
                nb["icones"] += 1
                src = f'{e["type"]}/{prod["site"].name}'
                corps = rangee(src, "parchemin") + rangee(src, "bois")
                if "entier" in prod:
                    ent = f'{e["type"]}/{prod["entier"].name}'
                    corps += (f'<div class="rangee parchemin"><img class="entier" src="{esc(ent)}" alt=""></div>'
                              f'<div class="rangee bois"><img class="entier" src="{esc(ent)}" alt=""></div>')
                if "discord" in prod:
                    dsrc = "../../../visuels/icones/" + prod["discord"].name
                    corps += (f'<p class="meta">Discord : <code>{esc(prod["discord"].stem)}</code></p>'
                              + rangee(dsrc, "discord_sombre", (22, 48)) + rangee(dsrc, "discord_clair", (22, 48)))
                cartes.append(f'<article class="carte">{entete}{corps}</article>')
            elif e["image"]:
                nb["attente"] += 1
                raison = (manifeste.get(cle) or {}).get("erreur", "non téléchargée")
                cartes.append(f'<article class="carte manque">{entete}<p>En attente : {esc(raison)}</p></article>')
            else:
                nb["sans"] += 1
                cartes.append(f'<article class="carte manque">{entete}<p>Aucune icône dans le dossier de recherche.</p></article>')
        blocs.append(f'<section><h2>{esc(t_nom)} <small>{esc(t_nom_en)} · champ « {esc(champ)} »'
                     f'{" · plusieurs" if multiple else ""}</small></h2><div class="grille">{"".join(cartes)}</div>'
                     "</section>")
    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Planche RELL Seas</title>
<style>
:root{{--parchemin:#efe2c4;--encre:#2b1d12;--bois:#2f1d10;--laiton:#a8823f;--cire:#8e2a24;--vert:#3f6b3a}}
body{{margin:0;padding:16px;background:#e4d2a6;color:var(--encre);font:15px/1.45 Georgia,serif}}
h1{{margin:0 0 4px}}h2{{margin:28px 0 8px;border-bottom:2px solid var(--laiton)}}h2 small,h3 small{{font-weight:normal;opacity:.7}}
.grille{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}}
.carte{{background:#fff8e8;border:1px solid #b99a6b;padding:8px;min-width:0;overflow:hidden}}.carte h3{{margin:0;font-size:16px}}
.carte.manque{{border-style:dashed;opacity:.75}}.meta{{margin:2px 0 6px;font-size:13px}}
.statut{{padding:0 5px;border-radius:3px;color:#fff;background:var(--vert)}}.statut.a_verifier{{background:#a8641c}}
.m3{{padding:0 5px;border-radius:3px;color:#fff;background:var(--cire)}}
.rangee{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:6px}}.parchemin{{background:var(--parchemin)}}
.bois{{background:var(--bois)}}.discord_sombre{{background:#313338}}.discord_clair{{background:#fff}}
.entier{{height:180px;width:auto}}code{{font-size:12px}}
</style></head><body>
<h1>Planche de contrôle — RELL Seas</h1>
<p>{nb["icones"]} élément(s) avec icône · {nb["attente"]} en attente · {nb["sans"]} sans icône dans le dossier de recherche.
Chaque icône à 32, 64 et 128 px sur parchemin (#efe2c4) puis sur bois sombre (#2f1d10) ; les émojis Discord à 22 et 48 px.</p>
{"".join(blocs)}
</body></html>
"""
    _ecrire(PLANCHE, page.encode("utf-8"))


# ─────────────────────────────── 5. Vérification ───────────────────────────────
def verifier_tout() -> list[str]:
    """Forme exacte du catalogue, fichiers présents et conformes, noms des émojis, rien d'orphelin."""
    err: list[str] = []
    try:
        donnees = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        return [f"catalogue illisible : {ex}"]
    if set(donnees) != {"types", "elements"}:
        err.append(f"clés du catalogue : {sorted(donnees)}")
    types = donnees.get("types", [])
    cles_types = [t.get("cle") for t in types]
    if len(set(cles_types)) != len(cles_types):
        err.append("types en double")
    for t in types:
        if tuple(t) != CLES_TYPE:
            err.append(f"type {t.get('cle')} : clés {tuple(t)}")
        if not (isinstance(t.get("multiple"), bool) and isinstance(t.get("ordre"), int) and t.get("nom")
                and t.get("champ") and t.get("nom_en")):
            err.append(f"type {t.get('cle')} : valeurs invalides")
    for obligatoire in ("metier", "race", "faction", "fruit", "trait", "classe", "haki", "carte_haki", "poster",
                        "style", "arme", "navire", "monture", "mer", "equipement", "enchantement", "piece_navire"):
        if obligatoire not in cles_types:
            err.append(f"type manquant : {obligatoire}")
    vus, ordres = set(), {}
    icones_attendues = set()
    for e in donnees.get("elements", []):
        nom = f"{e.get('type')}/{e.get('cle')}"
        if tuple(e) != CLES_ELEMENT:
            err.append(f"{nom} : clés {tuple(e)}")
            continue
        if nom in vus:
            err.append(f"{nom} : en double")
        vus.add(nom)
        if e["type"] not in cles_types:
            err.append(f"{nom} : type inconnu")
        if not re.fullmatch(r"[a-z0-9_]{1,40}", e["cle"]):
            err.append(f"{nom} : clé invalide")
        if e["statut"] not in ("confirme", "a_verifier"):
            err.append(f"{nom} : statut {e['statut']!r}")
        if not (isinstance(e["actif"], bool) and isinstance(e["nouveau_movie3"], bool) and e["version"] == 1):
            err.append(f"{nom} : actif/nouveau_movie3/version invalides")
        if not (e["nom"] and e["nom_en"] and e["description"]) or len(e["description"]) > 300:
            err.append(f"{nom} : nom ou description invalide")
        if not e["source"].startswith(("https://rellseas.fandom.com/wiki/", VIDEO_M3)):
            err.append(f"{nom} : source inattendue")
        if any("\U0001F000" <= ch <= "\U0001FAFF" or "☀" <= ch <= "➿" for ch in
               e["nom"] + e["description"] + e["categorie"]):
            err.append(f"{nom} : émoji interdit")
        ordres.setdefault(e["type"], []).append(e["ordre"])
        if e["icone"]:
            attendu = f"s/icones/rell/{e['type']}/{e['cle']}.webp"   # la forme de la spécification §2.4
            if e["icone"] != attendu:
                err.append(f"{nom} : icone {e['icone']!r} (attendu {attendu!r})")
            fichier = SITE / e["icone"].removeprefix("s/")
            icones_attendues.add(fichier.resolve())
            try:
                with Image.open(fichier) as im:
                    if im.format != "WEBP" or im.size != (COTE_SITE, COTE_SITE):
                        err.append(f"{nom} : icône {im.format} {im.size}")
            except OSError:
                err.append(f"{nom} : icône absente ({e['icone']})")
            if fichier.is_file() and fichier.stat().st_size > 120_000:
                err.append(f"{nom} : icône trop lourde")
            if e["type"] == "race":
                icones_attendues.add((fichier.parent / f"{e['cle']}_entier.webp").resolve())
            if e["type"] in TYPES_DISCORD:
                png = DOSSIER_DISCORD / f"{nom_discord(e['type'], e['cle'])}.png"
                try:
                    with Image.open(png) as im:
                        if im.format != "PNG" or im.size != (COTE_DISCORD, COTE_DISCORD) or im.mode != "RGBA":
                            err.append(f"{nom} : émoji Discord {im.format} {im.size} {im.mode}")
                except OSError:
                    err.append(f"{nom} : émoji Discord absent ({png.name})")
    for type_, liste in ordres.items():
        if sorted(liste) != list(range(1, len(liste) + 1)):
            err.append(f"{type_} : ordres {liste}")
    for f in DOSSIER_ICONES.glob("*/*.webp"):
        if f.resolve() not in icones_attendues:
            err.append(f"orphelin : {f.relative_to(RACINE).as_posix()}")
    for f in DOSSIER_DISCORD.glob("rell_*.png"):
        if len(f.stem) > NOM_DISCORD_MAX or not re.fullmatch(r"rell_[a-z0-9_]+", f.stem):
            err.append(f"nom d'émoji invalide : {f.name}")
        if f.stat().st_size > 256_000:
            err.append(f"émoji trop lourd : {f.name}")
        type_cle = f.stem.removeprefix("rell_")
        if not any(type_cle == f"{e['type']}_{e['cle']}" and e["icone"] for e in donnees.get("elements", [])):
            err.append(f"émoji sans élément : {f.name}")
    for c, *_ in LOGOS:
        if not (DOSSIER_LOGOS / f"{c}.webp").is_file():
            err.append(f"logo absent : {c}")
    for f in (SOURCES_MD, PLANCHE):
        if not f.is_file():
            err.append(f"absent : {f.relative_to(RACINE).as_posix()}")
    provenance = lire_provenance()
    for cle in sorties_presentes():
        if not (provenance.get(cle) or {}).get("sha256"):
            err.append(f"{cle} : provenance absente de SOURCES.md")
    return err


# ─────────────────────────────── Programme ───────────────────────────────
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Icônes officielles et catalogue de RELL Seas")
    p.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "rellseas_icones_brut",
                   help="dossier des originaux téléchargés (hors du dépôt)")
    p.add_argument("--hors-ligne", action="store_true", help="aucune requête : le cache seulement")
    p.add_argument("--reessayer", action="store_true",
                   help="redemander une fois les images refusées par le défi anti-robot du wiki")
    p.add_argument("--depuis", type=Path,
                   help="page d'aide enregistrée en « Page Web complète », ou dossier d'images enregistrées")
    p.add_argument("--verifier", action="store_true", help="vérifier seulement (rien n'est écrit)")
    args = p.parse_args()
    if not args.verifier:
        cache = args.cache.resolve()
        if RACINE in cache.parents or cache == RACINE:
            raise SystemExit("[ICONES] le cache des originaux doit être HORS du dépôt")
        manifeste = telecharger(cache, args.hors_ligne or bool(args.depuis), args.reessayer)
        if args.depuis:
            manifeste = importer(args.depuis.resolve(), cache, manifeste)
        construire(cache, manifeste)
        nettoyer_obsoletes()
        presentes = sorties_presentes()
        ecrire_catalogue(catalogue(presentes))
        ecrire_sources(fusion_provenance(manifeste, presentes), presentes, manifeste)
        ecrire_planche(manifeste, presentes)
        page = ecrire_page_manuelle(cache, manifeste)
        if page:
            print(f"[ICONES] images manquantes : page d'aide à ouvrir dans un navigateur : {page}")
    erreurs = verifier_tout()
    for e in erreurs:
        print(f"[ICONES][VERIF] {e}")
    print("[ICONES] vérification : " + ("ÉCHEC" if erreurs else "VERT"))
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
