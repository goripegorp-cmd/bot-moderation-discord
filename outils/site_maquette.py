"""outils/site_maquette.py — la maquette locale du site v2, « La Capitainerie » (25/10/2026).

Sert le dossier `site/` EXACTEMENT comme le vrai serveur (mêmes chemins `/tableau/espace/...`, `{{V}}` remplacé par
l'empreinte du dossier, mêmes en-têtes, même CSP que la spécification §2.2) et simule TOUTE l'API — les routes
existantes (`donnees`, `membre`, `conversation`, `recherche`, `export`, `action`, `sortir`) et les nouvelles
(`api/rell/...`, `api/clan/...`, `api/nettoyage...`, `api/recrutement/...`, `api/media`, `sync`) — avec des données
fictives réalistes, en français, nombreuses (pour éprouver les regroupements). Les écritures modifient l'état en
mémoire ; une version périmée donne un vrai conflit 409 ; la synchronisation est idempotente (`op_id`).
Les formes suivent le VRAI serveur (`tests/test_site_v2_port.py` les compare) ; les actions (`action`) lisent les mêmes
champs et répondent comme celles de bot.py : un corps mal formé est refusé ici aussi.

Rien n'appelle Discord ni Roblox : avatars, portraits et icônes de démonstration sont dessinés ici (Pillow).
Les annonces et événements du clan (`api/clan/...`) suivent `evenements.py` à la lettre : mêmes réponses, mêmes refus,
et les cartes de l'aperçu rendues par le module lui-même (ses défauts, ses modèles et ses limites viennent de lui).

Lancer :
    python outils/site_maquette.py            → http://localhost:8791/tableau/espace/
    python outils/site_maquette.py --panne    → démarre « en panne » (toutes les adresses du site répondent 503)

Bascules (hors de la portée du service worker, donc jamais mises en cache) :
    /maquette/panne?etat=1|0       le serveur tombe / revient
    /maquette/session?etat=0|1     la session expire / revient (403 « Session expirée. »)
    /maquette/lent?ms=6000         chaque réponse attend (éprouve le délai de 4 s du service worker)
    /maquette/ailleurs?quoi=affiche&id=12   une modification « faite ailleurs » : la prochaine écriture → 409
                                    (quoi=brouillon&id=3 : un brouillon d'annonce ou d'événement)
    /maquette/incertain?etat=1      la prochaine publication du clan part sans confirmation de Discord (502 « incertaine »)
    /maquette/etat                  l'état des bascules
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import hashlib
import io
import json
import random
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web, WSMsgType

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # sans base de fuseaux : l'heure UTC
    PARIS = timezone.utc

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # sans Pillow : pas d'images de démonstration (les pages restent utilisables)
    Image = ImageDraw = ImageFont = None

RACINE = Path(__file__).resolve().parent.parent / "site"
#  Les posts du forum du clan où les annonces et les événements se publient (zones.CLAN_POSTS, sans le guide).
POSTS_CLAN = (("infos", "Infos · Info"), ("annonces", "Annonces · Announcements"), ("chat", "Chat"), ("economie", "Économie · Economy"),
              ("trade", "Trade du clan · Clan trade"), ("taverne", "Taverne · Tavern"))
_EV: list = []


def _ev():
    """Le module des événements du bot (`evenements.py`) : ses défauts, ses modèles, ses limites et le rendu de ses cartes.
    La maquette répond ainsi avec les MÊMES formes que le serveur (25/10 : la page écrite contre une maquette qui
    inventait les siennes lisait des champs que le serveur n'envoie pas). Chargé une fois ; None s'il ne se charge pas
    (ses routes répondent alors 503, comme le serveur quand le module démarre)."""
    if not _EV:
        try:
            import sys
            racine = str(Path(__file__).resolve().parent.parent)
            if racine not in sys.path:
                sys.path.insert(0, racine)
            import evenements
            _EV.append(evenements)
        except Exception as ex:  # la maquette reste utilisable : les annonces disent « indisponible »
            print("[MAQUETTE][E1] module des événements illisible")
            print(f"[MAQUETTE][E1:DETAIL] {type(ex).__name__} {ex}")
            _EV.append(None)
    return _EV[0]
#  D'autres dossiers « site/ » qui complètent le nôtre (--extra), comme après la fusion des branches : icônes
#  officielles et logos d'un autre agent. Un fichier absent partout reste un 404 (le repli gravé de la page s'affiche).
EXTRA: list[Path] = []
ESPACE = "/tableau/espace"
MAINTENANT = time.time()
JOUR = 86400

# ─── En-têtes : les mêmes que le vrai serveur ───────────────────────────────
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data: blob: "
       "https://cdn.discordapp.com https://*.discordapp.net; media-src 'self' https://cdn.discordapp.com "
       "https://*.discordapp.net; connect-src 'self'; worker-src 'self'; manifest-src 'self'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")
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
}
ENTETES_PAGE = dict(ENTETES, **{"Content-Security-Policy": CSP})
TYPES_MIME = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8", "woff2": "font/woff2",
              "webp": "image/webp", "png": "image/png", "svg": "image/svg+xml", "json": "application/json",
              "webmanifest": "application/manifest+json", "ico": "image/x-icon"}

BASCULES = {"panne": False, "session": True, "lent": 0}


def empreinte_site() -> str:
    """L'empreinte du dossier `site/` (chemins, tailles, dates) : elle change à chaque modification."""
    h = hashlib.sha256()
    for f in sorted(RACINE.rglob("*")):
        if f.is_file():
            st = f.stat()
            h.update(f"{f.relative_to(RACINE).as_posix()}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()[:12]


def _json(corps, status: int = 200, etag: str | None = None) -> web.Response:
    entetes = dict(ENTETES, **({"ETag": etag} if etag else {}))
    r = web.Response(body=json.dumps(corps, ensure_ascii=False, separators=(",", ":"), default=str).encode(),
                     status=status, content_type="application/json", headers=entetes)
    r.enable_compression()
    return r


def _refus(message: str, status: int = 400) -> web.Response:
    return _json({"ok": False, "erreur": message, "message": message}, status)


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40] or "element"


def _quand(t) -> str:
    return datetime.fromtimestamp(int(t), PARIS).strftime("%d/%m/%Y %H:%M") if t else ""


def _mois(t) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m")


def _jour(t) -> str:
    return datetime.fromtimestamp(int(t), PARIS).strftime("%Y-%m-%d")


# ─── Images de démonstration (Pillow) ───────────────────────────────────────
_IMAGES: dict = {}
TEINTES = ["#1f4e5a", "#8e2a24", "#3f6b3a", "#a8641c", "#5e3a4e", "#4a5560", "#7a4b2a", "#2f5f6b", "#6b4527",
           "#5a6b2e", "#7c3a52", "#335c4a"]


def _police(taille: int):
    for nom in ("C:/Windows/Fonts/georgiab.ttf", "C:/Windows/Fonts/georgia.ttf", "DejaVuSerif-Bold.ttf"):
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=taille)
    except TypeError:
        return ImageFont.load_default()


def _png(img) -> bytes:
    f = io.BytesIO()
    img.save(f, "PNG", optimize=True)
    return f.getvalue()


def image_avatar(uid: str, nom: str) -> bytes:
    cle = ("av", uid)
    if cle not in _IMAGES:
        r = random.Random(uid)
        img = Image.new("RGB", (128, 128), TEINTES[r.randrange(len(TEINTES))])
        d = ImageDraw.Draw(img)
        init = "".join(m[0] for m in re.findall(r"[A-Za-zÀ-ÿ]+", nom)[:2]).upper() or "?"
        f = _police(52)
        b = d.textbbox((0, 0), init, font=f)
        d.text(((128 - (b[2] - b[0])) / 2 - b[0], (128 - (b[3] - b[1])) / 2 - b[1]), init, fill="#f4ead2", font=f)
        _IMAGES[cle] = _png(img)
    return _IMAGES[cle]


def image_icone(type_: str, cle_: str, nom: str) -> bytes:
    """Une icône de démonstration : un emblème à l'encre (la vraie viendra du jeu)."""
    cle = ("ic", type_, cle_)
    if cle not in _IMAGES:
        r = random.Random(type_ + cle_)
        img = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        teinte = TEINTES[r.randrange(len(TEINTES))]
        if type_ in ("metier", "style"):
            d.polygon([(48, 6), (88, 20), (82, 62), (48, 90), (14, 62), (8, 20)], fill=teinte, outline="#2b1d12")
        elif type_ in ("grade",):
            pts = []
            import math
            for i in range(10):
                a = math.pi / 2 + i * math.pi / 5
                rr = 44 if i % 2 == 0 else 19
                pts.append((48 + rr * math.cos(a), 50 - rr * math.sin(a)))
            d.polygon(pts, fill=teinte, outline="#2b1d12")
        elif type_ in ("faction", "navire"):
            d.rectangle([14, 8, 82, 70], fill=teinte, outline="#2b1d12", width=2)
            d.polygon([(14, 70), (48, 92), (82, 70)], fill=teinte, outline="#2b1d12")
        else:
            d.ellipse([6, 6, 90, 90], fill=teinte, outline="#2b1d12", width=3)
        init = "".join(m[0] for m in re.findall(r"[A-Za-zÀ-ÿ]+", nom)[:2]).upper() or "?"
        f = _police(34)
        b = d.textbbox((0, 0), init, font=f)
        d.text(((96 - (b[2] - b[0])) / 2 - b[0], (96 - (b[3] - b[1])) / 2 - b[1] - 2), init, fill="#f4ead2", font=f)
        _IMAGES[cle] = _png(img)
    return _IMAGES[cle]


def image_roblox(rid: str) -> bytes:
    """Un portrait façon Roblox (blocs), pour l'affiche."""
    cle = ("rb", rid)
    if cle not in _IMAGES:
        r = random.Random(rid)
        img = Image.new("RGB", (300, 300), "#d9d2c3")
        d = ImageDraw.Draw(img)
        peau = r.choice(["#f2c9a0", "#d9a274", "#a8724a", "#7a4f32", "#f5d6b8"])
        haut = r.choice(TEINTES)
        d.rectangle([0, 230, 300, 300], fill="#c9bfa9")
        d.rectangle([95, 150, 205, 300], fill=haut)  # torse
        d.rectangle([55, 155, 95, 280], fill=peau)  # bras
        d.rectangle([205, 155, 245, 280], fill=peau)
        d.rounded_rectangle([105, 40, 195, 140], radius=18, fill=peau)  # tête
        d.rectangle([125, 78, 137, 92], fill="#2b1d12")
        d.rectangle([163, 78, 175, 92], fill="#2b1d12")
        d.arc([128, 95, 172, 122], 20, 160, fill="#2b1d12", width=4)
        if r.random() < .6:  # chapeau
            d.polygon([(80, 52), (220, 52), (190, 20), (110, 20)], fill="#2f1d10")
        _IMAGES[cle] = _png(img)
    return _IMAGES[cle]


# ─── Le monde fictif ────────────────────────────────────────────────────────
PRENOMS = ["Akira", "Alix", "Ambre", "Anaïs", "Arthur", "Axel", "Baptiste", "Bastien", "Blanche", "Capucine",
           "Céleste", "Clément", "Corentin", "Dorian", "Eliott", "Elouan", "Emma", "Enzo", "Erwan", "Esteban",
           "Fanny", "Gabin", "Gaspard", "Hugo", "Inès", "Isaac", "Jade", "Jules", "Kylian", "Léa", "Léon", "Lina",
           "Louis", "Lucas", "Maël", "Malo", "Manon", "Marius", "Mathis", "Maya", "Nathan", "Nina", "Noah",
           "Nolan", "Océane", "Paul", "Pierre", "Quentin", "Raphaël", "Romane", "Rose", "Ruben", "Sacha",
           "Salomé", "Samuel", "Simon", "Théo", "Tom", "Ulysse", "Valentin", "Victor", "Wassim", "Yanis",
           "Yanna", "Zoé", "Margaux", "Titouan", "Loïc", "Héloïse", "Basile"]
SUFFIXES = ["", "", "", "", "_RS", "Sea", "77", "duNord", "Kaizoku", " le Rouge", "_FR", "Marin", "Tide", "Storm",
            "_GoRP", "Ancre", "Vague", " des Brumes", "Corsaire", "Écume"]
SURNOMS = ["l'Ombre des Mers", "Main de Fer", "le Cartographe", "Œil de Faucon", "la Tempête", "Cœur de Corail",
           "le Silencieux", "Lame d'Écume", "le Rieur", "Vent du Large", "la Sirène", "le Brise-Coque",
           "Gueule de Loup", "l'Insaisissable", "Barbe-Grise", "la Boussole", "Poing de Pierre", "le Fantôme"]
RAISONS = ["Insultes répétées dans #général", "Spam de liens", "Publicité non autorisée", "Propos haineux",
           "Harcèlement d'un membre", "Contournement d'un mute", "Pseudo inapproprié", "Flood en vocal",
           "Partage de contenu choquant", "Arnaque au trade", "Usurpation d'identité", "Provocation"]
SALONS_TEXTE = ["général", "trade", "aide", "rell-seas", "annonces", "médias", "taverne", "recrutement", "règles",
                "suggestions", "sondages", "clan-gorp"]


class Monde:
    def __init__(self, graine: int, catalogue: dict | None = None, questionnaire: dict | None = None):
        self.graine, self.catalogue_fourni, self.questionnaire_fourni = graine, catalogue, questionnaire
        self.r = r = random.Random(graine)
        self.personnes: dict[str, dict] = {}
        self.ops: dict[str, dict] = {}
        self.medias: dict[str, tuple[bytes, str]] = {}
        self.ailleurs: set = set()
        self.compteur = 1000
        #  Ce que les actions du tableau changent (comme bot.py) : alertes gérées, membres partis ou bannis.
        self.alertes_gerees: set = set()
        self.partis: set = set()
        self.bannis: set = set()
        self.archives: dict = {}   # nettoyage du casier → ses entrées (pour le défaire)
        self.fondateur = self._personne("781205382923288593", "Capitaine Corbeau", "corbeau")
        self.direction = self._personne("827633340797681714", "Second Marée", "maree.seconde")
        self.moi = self.fondateur["id"]
        self.serveur = [self._personne() for _ in range(1600)]
        # quelques cas limites : émoji dans le nom (nettoyé à l'affichage), nom très long, sans avatar
        self.serveur[3]["nom"] = "⚓ Ancre Noire"
        self.serveur[7]["nom"] = "Maximilien-Alexandre de la Grande Mer du Ponant"
        self.serveur[9]["avatar"] = ""
        self.staff = self.serveur[10:18]
        self.clan_ids = [p["id"] for p in self.serveur[20:162]]
        self.radies = [p["id"] for p in self.serveur[1500:1503]]
        self._clan()
        self._journal()
        self._casier()
        self._tickets()
        self._candidatures()
        self._questions()
        self._salons()
        self._sondages_idees()
        self._entraide_annonces()
        self._catalogue(catalogue)
        self._affiches()
        self._roles()
        self._evenements()
        self._nettoyage()
        self._recrutement(questionnaire)

    # ── personnes ──
    def _personne(self, uid: str | None = None, nom: str | None = None, pseudo: str | None = None) -> dict:
        r = self.r
        uid = uid or str(700000000000000000 + r.randrange(10 ** 17))
        if nom is None:
            nom = r.choice(PRENOMS) + r.choice(SUFFIXES)
        pseudo = pseudo or (_slug(nom).replace("_", ".") + (str(r.randrange(10, 999)) if r.random() < .5 else ""))
        p = {"id": uid, "nom": nom, "pseudo": pseudo, "avatar": f"{ESPACE}/media/demo/av/{uid}.png",
             "arrivee": int(MAINTENANT - r.uniform(2, 900) * JOUR), "cree": int(MAINTENANT - r.uniform(200, 3000) * JOUR)}
        self.personnes[uid] = p
        return p

    def ident(self, uid) -> dict:
        p = self.personnes.get(str(uid))
        if p is None:
            return {"id": str(uid or ""), "nom": "Membre parti", "pseudo": "", "avatar": ""}
        return {"id": p["id"], "nom": p["nom"], "pseudo": p["pseudo"], "avatar": p["avatar"]}

    def nom(self, uid) -> str:
        return self.ident(uid)["nom"] if uid else ""

    def t(self, jours_max: float, jours_min: float = 0) -> int:
        return int(MAINTENANT - self.r.uniform(jours_min, jours_max) * JOUR)

    # ── clan ──
    def _clan(self):
        r = self.r
        self.clan: dict[str, dict] = {}
        for i, uid in enumerate(self.clan_ids):
            rang = r.choices([0, 1, 2, 3, 4], [52, 22, 16, 6, 4])[0]
            presents = {0: r.randint(3, 7), 1: r.randint(1, 2), 2: 0}.get(rang, 0)
            derniere = {0: r.choice(["aujourd'hui", "hier", "il y a 2 j"]), 1: f"il y a {r.randint(8, 25)} j",
                        2: f"il y a {r.randint(31, 90)} j", 3: "jamais vu", 4: "aujourd'hui"}[rang]
            rappel = None
            if rang == 2 and r.random() < .55:
                envoye = self.t(12, 1)
                statut = "echu" if MAINTENANT - envoye > 7 * JOUR else "en_attente"
                rappel = {"envoye_le": envoye, "echeance": envoye + 7 * JOUR, "par": self.fondateur["nom"],
                          "mode": r.choice(["mp", "salon"]), "salon": "clan-gorp", "remis": r.random() < .8,
                          "statut": statut, "resolu_le": None, "resolu_par": None}
            elif rang == 0 and r.random() < .08:
                envoye = self.t(20, 8)
                rappel = {"envoye_le": envoye, "echeance": envoye + 7 * JOUR, "par": self.direction["nom"],
                          "mode": "mp", "salon": "", "remis": True, "statut": "revenu", "resolu_le": self.t(6),
                          "resolu_par": None}
            self.clan[uid] = {"rang": rang, "jours": f"{presents}/7" if rang in (0, 1, 2) else "—",
                              "derniere": derniere, "rappel": rappel}

    def clan_donnees(self) -> dict:
        statuts = ["Actif", "Peu présent", "Inactif", "Jamais vu", "Trop récent"]
        membres = []
        for uid, c in self.clan.items():
            p = self.personnes[uid]
            membres.append(dict(self.ident(uid), statut=statuts[c["rang"]], rang=c["rang"], jours=c["jours"],
                                derniere=c["derniere"], arrivee=datetime.fromtimestamp(p["arrivee"], PARIS).strftime("%d/%m/%Y"),
                                rappel=c["rappel"]))
        membres.sort(key=lambda x: (x["rang"], x["nom"].casefold(), x["id"]))
        return {"role": "Clan GoRP", "role_id": "900000000000000001", "membres": membres,
                "direction": [self.ident(self.fondateur["id"]), self.ident(self.direction["id"])],
                "salons": [{"id": str(800000000000000000 + i), "nom": n, "cat": c} for i, (n, c) in enumerate(
                    [("clan-gorp", "Clan GoRP"), ("chat-du-clan", "Clan GoRP"), ("général", "Communauté"),
                     ("rell-seas", "Jeux")])]}

    # ── journal ──
    def _journal(self):
        r = self.r
        cats = [("Modération", 14), ("Sécurité", 8), ("Membres", 22), ("Messages", 20), ("Vocal", 12), ("Tickets", 10),
                ("Clan", 6), ("Questions", 5), ("Sondages", 2), ("Suggestions", 2), ("Accès", 3), ("Serveur", 3),
                ("Config", 1), ("Entraide", 3), ("Site", 2)]
        noms, poids = zip(*cats)
        self.journal = []
        for i in range(700):
            cat = r.choices(noms, poids)[0]
            m = r.choice(self.serveur)["id"]
            a = r.choice(self.staff)["id"] if r.random() < .5 else ""
            salon = "#" + r.choice(SALONS_TEXTE)
            grav = 0
            if cat == "Modération":
                typ, texte = r.choice([("mod.warn", f"Avertissement pour {self.nom(m)}"), ("mod.mute", f"Mute d'une heure pour {self.nom(m)}"),
                                       ("mod.kick", f"Expulsion de {self.nom(m)}"), ("mod.ban", f"Bannissement de {self.nom(m)}")])
                grav = 2 if typ in ("mod.kick", "mod.ban") else 1
                detail = r.choice(RAISONS)
            elif cat == "Sécurité":
                typ, texte = r.choice([("sec.lien", "Lien suspect supprimé"), ("sec.insulte", "Insulte détectée par le filtre"),
                                       ("sec.raid", "Arrivées en rafale : vigilance renforcée"), ("sec.mention", "Mentions de masse bloquées")])
                grav = r.choice([1, 2, 2])
                detail = r.choice(["Message retiré automatiquement", "Le membre a été prévenu en privé", ""])
            elif cat == "Membres":
                typ, texte = r.choice([("membre.arrivee", f"{self.nom(m)} a rejoint le serveur"), ("membre.depart", f"{self.nom(m)} a quitté le serveur"),
                                       ("membre.pseudo", f"{self.nom(m)} a changé de pseudo")])
                detail, a = "", ""
            elif cat == "Messages":
                typ, texte = r.choice([("msg.suppr", f"Message supprimé dans {salon}"), ("msg.modif", f"Message modifié dans {salon}")])
                detail = r.choice(["« on se retrouve sur le bateau ce soir ? »", "« quelqu'un pour le boss ? »",
                                   "« vends sabre courbe contre fruit »", "« merci pour l'aide ! »"])
            elif cat == "Vocal":
                typ, texte = r.choice([("vocal.rejoint", f"{self.nom(m)} a rejoint le vocal Taverne"), ("vocal.quitte", f"{self.nom(m)} a quitté le vocal")])
                detail, a = "", ""
            elif cat == "Tickets":
                n = r.randint(1200, 1700)
                typ, texte = r.choice([("ticket.ouvert", f"Ticket #{n} ouvert"), ("ticket.ferme", f"Ticket #{n} fermé")])
                detail = r.choice(["Support", "Signalement", "Recrutement Rell Seas", ""])
            elif cat == "Clan":
                typ, texte = r.choice([("clan.role", f"{self.nom(m)} a reçu le rôle du clan"), ("clan.rappel", f"Rappel d'inactivité envoyé à {self.nom(m)}")])
                detail = ""
            elif cat == "Accès":
                typ, texte, m = "site.ouvert", f"Site ouvert par {self.fondateur['nom']}", ""
                detail, a = "", self.fondateur["id"]
            elif cat == "Site":
                typ, texte, m = "site.ecriture", "Affiche modifiée depuis le site", ""
                detail, a = "", self.direction["id"]
            else:
                typ, texte, detail = cat.casefold() + ".evt", f"{cat} : activité de {self.nom(m)}", ""
            quand = int(MAINTENANT - (i / 700) ** 1.6 * 32 * JOUR - r.uniform(0, 1800))
            self.journal.append({"id": 50000 - i, "quand": quand, "cat": cat, "type": typ, "texte": texte,
                                 "detail": detail, "membre": m, "auteur": a, "salon": salon if cat in ("Messages", "Sécurité") else "",
                                 "gravite": grav})
        self.journal.sort(key=lambda e: -e["quand"])

    # ── casier ──
    def _casier(self):
        r = self.r
        self.infractions = []
        robot = "1"
        types = [("warn", 50), ("mute", 18), ("kick", 5), ("ban", 4), ("insulte", 14), ("menace", 3), ("harcelement", 3),
                 ("protection", 6)]
        tn, tp = zip(*types)
        cibles = r.sample(self.serveur[30:1400], 260)
        iid = 9000
        for cible in cibles:
            for _ in range(r.choices([1, 2, 3, 4, 6, 9, 14], [40, 22, 14, 10, 7, 4, 3])[0]):
                typ = r.choices(tn, tp)[0]
                auto = typ not in ("warn", "mute", "kick", "ban") or r.random() < .25
                iid += 1
                self.infractions.append({"sanction": iid, "uid": cible["id"], "type": typ, "raison": r.choice(RAISONS),
                                         "duree": r.choice(["10 min", "1 h", "6 h", "1 j"]) if typ == "mute" else "",
                                         "date": self.t(400), "auto": auto, "mod": robot if auto else r.choice(self.staff)["id"]})
        self.infractions.sort(key=lambda x: -x["date"])
        self.lots = [{"lot": "zone-a1", "quand": self.t(9, 4), "par": self.fondateur["id"], "quoi": "Avertissements, plus de 90 jours",
                      "n": 42, "personnes": 31, "restaure_le": None, "restaure_par": ""},
                     {"lot": "amnistie-b2", "quand": self.t(20, 15), "par": "", "quoi": "Amnistie : 3 mois sans infraction",
                      "n": 17, "personnes": 9, "restaure_le": self.t(14, 10), "restaure_par": self.direction["id"]},
                     #  Le casier d'une personne (comme `tableau._casier` : la personne à part, jamais son identifiant).
                     {"lot": "membre-c3", "quand": self.t(3, 1), "par": self.direction["id"], "quoi": "Avertissements",
                      "membre": cibles[0]["id"], "n": 3, "personnes": 1, "restaure_le": None, "restaure_par": ""}]
        self.restreints = [{"uid": self.serveur[1400]["id"], "depuis": self.t(3), "raison": "Comportement à surveiller", "par": self.direction["id"]}]
        self.mutes = {self.serveur[1401]["id"]: int(MAINTENANT + 3 * 3600), self.serveur[1402]["id"]: int(MAINTENANT + 86400)}

    LIB = {"warn": "Avertissement", "mute": "Mute", "kick": "Expulsion", "ban": "Bannissement", "insulte": "Insulte",
           "menace": "Menace", "discrimination": "Discrimination", "haine": "Haine", "incitation": "Incitation",
           "harcelement": "Harcèlement", "grooming": "Protection des mineurs", "protection": "Filtre automatique"}
    GROUPES = {"warn": "Avertissements", "mute": "Mutes", "kick": "Expulsions et bans", "ban": "Expulsions et bans"}

    def entree(self, x: dict) -> dict:
        return {"sanction": x["sanction"], "type": x["type"], "libelle": self.LIB.get(x["type"], x["type"]),
                "groupe": self.GROUPES.get(x["type"], "Détections"), "raison": x["raison"], "duree": x["duree"],
                "date": x["date"], "auto": x["auto"], "par": "Automatique" if x["auto"] else self.nom(x["mod"])}

    def sanctions_donnees(self) -> dict:
        par_type, mois, staff, staff30, membres = {}, {}, {}, {}, {}
        auto = manuel = r30 = 0
        apart = {self.fondateur["id"], self.direction["id"]}
        for x in self.infractions:
            par_type[x["type"]] = par_type.get(x["type"], 0) + 1
            auto, manuel = auto + x["auto"], manuel + (not x["auto"])
            age = MAINTENANT - x["date"]
            r30 += age <= 30 * JOUR
            if age <= 365 * JOUR:
                mois.setdefault(_mois(x["date"]), {"Avertissements": 0, "Mutes": 0, "Expulsions et bans": 0, "Détections": 0})[
                    self.GROUPES.get(x["type"], "Détections")] += 1
            if not x["auto"] and x["mod"] not in apart:
                st = staff.setdefault(x["mod"], {"total": 0, "types": {}, "dernieres": []})
                st["total"] += 1
                st["types"][x["type"]] = st["types"].get(x["type"], 0) + 1
                if age <= 30 * JOUR:
                    staff30[x["mod"]] = staff30.get(x["mod"], 0) + 1
                if len(st["dernieres"]) < 15:
                    st["dernieres"].append(dict(self.entree(x), id=x["uid"]))
            f = membres.setdefault(x["uid"], {"id": x["uid"], "total": 0, "n30": 0, "n90": 0, "types": {}, "derniere": 0, "liste": []})
            f["total"] += 1
            f["n30"] += age <= 30 * JOUR
            f["n90"] += age <= 90 * JOUR
            f["types"][x["type"]] = f["types"].get(x["type"], 0) + 1
            f["derniere"] = max(f["derniere"], x["date"])
            if len(f["liste"]) < 12:
                f["liste"].append(self.entree(x))
        self._staff30_sanctions = staff30
        return {"total": len(self.infractions), "trente_jours": r30, "auto": auto, "manuel": manuel,
                "libelles": {k: self.LIB.get(k, k) for k in par_type},
                "types": sorted(({"type": k, "libelle": self.LIB.get(k, k), "n": v, "detection": k not in self.GROUPES}
                                 for k, v in par_type.items()), key=lambda t: -t["n"]),
                "mois": dict(sorted(mois.items())[-12:]),
                "staff": sorted(({"nom": self.nom(k), "id": k, **v} for k, v in staff.items()), key=lambda x: -x["total"])[:15],
                "membres": sorted(membres.values(), key=lambda f: -f["derniere"])[:250],
                "actives": {"mutes": [dict(self.ident(u), jusqu=j) for u, j in self.mutes.items()],
                            "radies": [self.ident(u) for u in self.radies],
                            "restreints": [dict(self.ident(x["uid"]), depuis=x["depuis"], raison=x["raison"], par=self.nom(x["par"]))
                                           for x in self.restreints]}}

    # ── tickets ──
    PANNEAUX = {"p1": ("Support", False), "p2": ("Signalement", False), "p3": ("Partenariat", False),
                "p4": ("Recrutement Rell Seas", True), "p5": ("Aide Rell Seas", True)}

    def _tickets(self):
        r = self.r
        self.tickets = []
        n = 1200
        for i in range(340):
            n += 1
            pid = r.choices(list(self.PANNEAUX), [30, 18, 4, 0, 14])[0]
            ouvert = self.t(170)
            ferme = i >= 24
            pris = r.choice(self.staff)["id"] if r.random() < .85 else ""
            fin = min(MAINTENANT - 60, ouvert + r.uniform(.05, 4) * JOUR) if ferme else None
            self.tickets.append({"ticket": n, "uid": r.choice(self.serveur[20:1500])["id"], "panel": pid,
                                 "statut": "closed" if ferme else "open", "ouvert": ouvert if ferme else self.t(5),
                                 "prise": (ouvert + r.uniform(300, 30000), pris) if pris else None,
                                 "fin": (int(fin), r.choice(self.staff)["id"]) if ferme else None, "pris_par": pris,
                                 "motif": r.choice(["Résolu", "Problème réglé en vocal", "Sans réponse du membre",
                                                    "Doublon", "Signalement traité : sanction appliquée", ""]) if ferme else "",
                                 "transcript": f"https://exemple.invalid/t/{n}" if ferme else ""})

    def tickets_donnees(self) -> dict:
        types, ouverts, staff, staff30, mois, fermes = {}, [], {}, {}, {}, []
        for x in self.tickets:
            nom, rell = self.PANNEAUX[x["panel"]]
            t = types.setdefault(nom, {"nom": nom, "rellseas": rell, "total": 0, "ouverts": 0, "fermes": 0, "sans_prise": 0,
                                       "_p": [], "_f": []})
            t["total"] += 1
            if x["pris_par"]:
                staff.setdefault(x["pris_par"], {"pris": 0, "fermes": 0})["pris"] += 1
                staff30.setdefault(x["pris_par"], {"pris": 0, "fermes": 0})["pris"] += 1
            if x["statut"] == "open":
                t["ouverts"] += 1
                ouverts.append(dict(self.ident(x["uid"]), ticket=x["ticket"], type=nom, rellseas=rell, ouvert=x["ouvert"],
                                    pris_par=self.nom(x["pris_par"]), salon=f"https://discord.com/channels/1/{x['ticket']}"))
            else:
                t["fermes"] += 1
                t["sans_prise"] += not x["pris_par"]
                staff.setdefault(x["fin"][1], {"pris": 0, "fermes": 0})["fermes"] += 1
                t["_f"].append(x["fin"][0] - x["ouvert"])
                fermes.append(x)
            if x["prise"]:
                t["_p"].append(x["prise"][0] - x["ouvert"])
            mois.setdefault(_mois(x["ouvert"]), {"Rell Seas": 0, "Tickets normaux": 0})["Rell Seas" if rell else "Tickets normaux"] += 1
        for t in types.values():
            p, f = sorted(t.pop("_p")), sorted(t.pop("_f"))
            t["prise_mediane"] = int(p[len(p) // 2]) if p else 0
            t["fermeture_mediane"] = int(f[len(f) // 2]) if f else 0
        fermes.sort(key=lambda x: -x["fin"][0])
        self._staff30_tickets = staff30
        jours = next((r["garde_jours"] for r in self.regles if r["cle"] == "tickets_archives"), 30)  # la règle « Nettoyage »
        return {"archives_jours": jours, "types": sorted(types.values(), key=lambda t: (not t["rellseas"], -t["total"], t["nom"])),
                "ouverts": sorted(ouverts, key=lambda o: (not o["rellseas"], o["type"], o["ouvert"])),
                "staff": sorted(({"nom": self.nom(k), **v} for k, v in staff.items()), key=lambda x: -(x["pris"] + x["fermes"]))[:15],
                "mois": dict(sorted(mois.items())[-12:]),
                "fermes": [{"id": x["uid"], "ticket": x["ticket"], "type": self.PANNEAUX[x["panel"]][0],
                            "rellseas": self.PANNEAUX[x["panel"]][1], "ouvert": x["ouvert"], "ferme": x["fin"][0],
                            "ferme_par": self.nom(x["fin"][1]), "motif": x["motif"], "transcript": x["transcript"]}
                           for x in fermes[:300]]}

    # ── candidatures (et recrutement en deux étapes) ──
    QUESTIONS_ETAPE1 = ["Ton pseudo Roblox ?", "Ton âge ?", "Depuis quand joues-tu à RELL Seas ?", "Ton niveau en jeu ?",
                        "Pourquoi veux-tu rejoindre le clan GoRP ?", "Tes disponibilités dans la semaine ?"]

    def _reponses_etape1(self, nom: str) -> list:
        r = self.r
        return [[self.QUESTIONS_ETAPE1[0], _slug(nom).replace("_", "") + str(r.randint(1, 99))],
                [self.QUESTIONS_ETAPE1[1], str(r.randint(13, 24)) + " ans"],
                [self.QUESTIONS_ETAPE1[2], r.choice(["Depuis la sortie du jeu", "Six mois", "Trois semaines", "Un an environ"])],
                [self.QUESTIONS_ETAPE1[3], str(r.randint(20, 400))],
                [self.QUESTIONS_ETAPE1[4], r.choice([
                    "Je cherche un équipage sérieux pour faire les boss et les évènements, et j'aime l'ambiance du serveur.",
                    "Des amis sont déjà dans le clan et je veux progresser avec eux. Je suis actif tous les soirs.",
                    "Pour participer aux guerres de factions et partager mes connaissances du jeu avec les nouveaux.",
                    "parce que"])],
                [self.QUESTIONS_ETAPE1[5], r.choice(["Le soir après 18 h", "Week-end surtout", "Tous les jours", "Mercredi et samedi"])]]

    def _candidatures(self):
        r = self.r
        self.candidats, self.en_cours = [], []
        for i, p in enumerate(self.serveur[200:290]):
            ouvert = self.t(240, 2)
            statut = r.choices(["acceptes", "refuses"], [55, 45])[0]
            ferme = int(ouvert + r.uniform(.2, 5) * JOUR)
            self.candidats.append(dict(self.ident(p["id"]), statut=statut, ticket=1000 + i, ouvert=ouvert, ferme=ferme,
                                       pris_par=self.nom(r.choice(self.staff)["id"]), ferme_par=self.nom(r.choice([self.fondateur, self.direction])["id"]),
                                       motif="Bienvenue dans l'équipage" if statut == "acceptes" else r.choice(
                                           ["Réponses insuffisantes à l'étape 1", "Étape 2 : 7/10 justes", "Trop jeune", "Inactif pendant le test"]),
                                       parti=r.random() < .1, reponses=self._reponses_etape1(p["nom"]),
                                       transcript=f"https://exemple.invalid/t/c{1000 + i}", candidatures=[ouvert]))
        etats = ["etape1"] * 5 + ["etape2_attente"] * 4 + ["etape2_reponses"] * 3 + ["etape2_partiel"]
        for i, (p, etat) in enumerate(zip(self.serveur[300:313], etats)):
            self.en_cours.append(dict(self.ident(p["id"]), statut="en_cours", ticket=1600 + i, ouvert=self.t(9, .1),
                                      pris_par=self.nom(r.choice(self.staff)["id"]) if r.random() < .7 else "",
                                      reponses=self._reponses_etape1(p["nom"]), salon=f"https://discord.com/channels/1/{1600 + i}",
                                      etape=1 if etat == "etape1" else 2, recrutement=etat))
            #  Comme sur le serveur : une candidature en cours est aussi un ticket ouvert « Recrutement Rell Seas ».
            c = self.en_cours[-1]
            pris = next((x["id"] for x in self.staff if x["nom"] == c["pris_par"]), "")
            self.tickets.append({"ticket": c["ticket"], "uid": p["id"], "panel": "p4", "statut": "open", "ouvert": c["ouvert"],
                                 "prise": (c["ouvert"] + 1800, pris) if pris else None, "fin": None, "pris_par": pris,
                                 "motif": "", "transcript": ""})

    # ── questions ──
    def _questions(self):
        r = self.r
        textes = ["Comment on rejoint le clan ?", "Quelqu'un sait où trouver le boss des abysses ?", "C'est quand le prochain évènement ?",
                  "On peut échanger un fruit contre un navire ?", "Pourquoi je n'ai plus accès au salon trade ?",
                  "Comment on monte de grade dans le clan ?", "Le serveur organise des tournois ?", "Il faut quel niveau pour le Movie 3 ?",
                  "Comment signaler un arnaqueur ?", "Où sont les règles du trade ?"]
        self.questions = []
        for i in range(70):
            quand = self.t(30)
            statut = r.choices(["ouverte", "repondue", "resolue", "traitee", "ignoree"], [18, 40, 22, 12, 8])[0]
            par = r.choice(self.staff)["id"] if statut in ("repondue", "resolue", "traitee") else ""
            self.questions.append({"question": 300 + i, "id": r.choice(self.serveur[20:1500])["id"], "texte": r.choice(textes),
                                   "quand": quand, "statut": statut, "par_id": par, "par_staff": bool(par),
                                   "repondu_le": quand + int(r.uniform(120, 30000)) if par else None,
                                   "salon": "#" + r.choice(["❓・aide", "💬・général", "🌊rell-seas", "trade"]),  # comme Discord : émoji et séparateur
                                   "message": f"https://discord.com/channels/1/2/{300 + i}", "reponse": ""})
        self.questions.sort(key=lambda q: -q["quand"])

    def questions_donnees(self) -> dict:
        lib = {"ouverte": "Sans réponse", "repondue": "Répondue", "resolue": "Résolue", "traitee": "Traitée", "ignoree": "Pas une question"}
        liste = [dict(q, libelle=lib[q["statut"]], par=self.nom(q["par_id"])) for q in self.questions]
        delais = sorted(q["repondu_le"] - q["quand"] for q in self.questions if q["repondu_le"])
        salons: dict = {}
        for q in self.questions:
            salons[q["salon"]] = salons.get(q["salon"], 0) + 1
        return {"liste": liste, "stats": {"ouvertes": sum(q["statut"] == "ouverte" for q in liste),
                                          "repondues_7": sum(1 for q in self.questions if q["repondu_le"] and MAINTENANT - q["repondu_le"] < 7 * JOUR),
                                          "delai_median": delais[len(delais) // 2] if delais else 0,
                                          "salons": [{"salon": s, "n": n} for s, n in sorted(salons.items(), key=lambda kv: -kv[1])[:6]]}}

    # ── salons et droits ──
    def _salons(self):
        self.salons = [
            {"categorie": "📌 Accueil", "salons": [("règles", False, "lecture"), ("annonces", False, "lecture"), ("bienvenue", False, "lecture"), ("rôles", False, "ouvert")]},
            {"categorie": "Communauté", "salons": [("général", False, "ouvert"), ("médias", False, "ouvert"), ("taverne", True, "ouvert"), ("trade", False, "ouvert"), ("aide", False, "ouvert")]},
            {"categorie": "Jeux", "salons": [("rell-seas", False, "ouvert"), ("live", True, "vitrine"), ("vidéo", True, "vitrine")]},
            {"categorie": "🦜▷・Clan GoRP", "salons": [("clan-gorp", False, "clan"), ("chat-du-clan", False, "clan"), ("vocal du clan", True, "clan")]},
            {"categorie": "Staff", "salons": [("📋logs", False, "cache"), ("staff", False, "cache"), ("réunion", True, "cache")]},
        ]

    def salons_donnees(self) -> list:
        out = []
        for i, c in enumerate(self.salons):
            lignes = []
            for j, (nom, vocal, profil) in enumerate(c["salons"]):
                voir = profil in ("ouvert", "lecture", "vitrine")
                lignes.append({"id": str(810000000000000000 + i * 100 + j), "nom": nom, "vocal": vocal, "profil": profil,
                               "voir": voir, "ecrire": profil == "ouvert" and not vocal, "reagir": voir and not vocal,
                               "rejoindre": profil == "ouvert" and vocal, "images": profil == "ouvert" and not vocal})
            out.append({"categorie": c["categorie"], "salons": lignes})
        return out

    # ── sondages, idées ──
    def _sondages_idees(self):
        r = self.r
        self.sondages = []
        for i in range(16):
            choix = r.choice([["Oui", "Non"], ["Samedi", "Dimanche", "Peu importe"], ["Boss", "Exploration", "Guerre de factions", "Trade"],
                              ["Le Movie 3 est excellent", "Moyen", "Décevant"]])
            comptes = [r.randint(0, 40) for _ in choix]
            cree = self.t(60)
            statut = "en_cours" if i < 4 else ("retire" if i % 7 == 0 else "termine")
            self.sondages.append({"id": 70 + i, "salon_id": "2", "lien": f"https://discord.com/channels/1/2/{70 + i}", "auteur": r.choice(self.serveur[20:900])["id"],
                                  "question": r.choice(["On fait une sortie en mer ce week-end ?", "Quel jour pour l'évènement du clan ?",
                                                        "Votre activité préférée en jeu ?", "Votre avis sur le Movie 3 ?"]),
                                  "choix": choix, "comptes": comptes, "total": sum(comptes), "multiple": r.random() < .3, "cree": cree,
                                  "fin": cree + 3 * JOUR if statut != "en_cours" else int(MAINTENANT + r.uniform(.2, 3) * JOUR), "statut": statut,
                                  "retire_le": cree + JOUR if statut == "retire" else None, "retire_par": self.direction["id"] if statut == "retire" else "",
                                  "salon": "#📊・sondages"})
        lib = {"attente": "En attente", "etude": "À l'étude", "acceptee": "Acceptée", "refusee": "Refusée", "realisee": "Réalisée"}
        self.idees = []
        for i in range(34):
            statut = r.choices(list(lib), [30, 15, 25, 15, 15])[0]
            self.idees.append({"id": 400 + i, "salon_id": "3", "lien": f"https://discord.com/channels/1/3/{400 + i}", "auteur": r.choice(self.serveur[20:900])["id"],
                               "titre": r.choice(["Un salon pour les captures d'écran", "Des tournois mensuels", "Un rôle pour les vétérans",
                                                  "Une carte des îles épinglée", "Un bot de rappel pour les boss", "Des évènements le dimanche"]),
                               "details": "Ce serait pratique pour tout le monde, et ça motiverait les nouveaux à participer davantage.",
                               "statut": statut, "libelle": lib[statut], "note": "Bonne idée, on s'en occupe." if statut in ("acceptee", "realisee") else "",
                               "decide_par": self.direction["id"] if statut not in ("attente",) else "", "cree": self.t(90),
                               "decide_le": self.t(30) if statut != "attente" else None, "retire_le": self.t(10) if i % 11 == 5 else None,
                               "pour": r.randint(0, 30), "contre": r.randint(0, 12), "salon": "#💡suggestions"})

    # ── entraide, annonces ──
    def _entraide_annonces(self):
        r = self.r
        self.entraide = []
        #  Comme `tableau._entraide` : les zones d'entraide.ZONES (Rell Seas, et Clover RPG en « cl_… »), leur libellé,
        #  le statut et son libellé bilingue.
        lib = {"ouverte": "Ouverte · Open", "prise": "En cours · Ongoing", "terminee": "Terminée · Done", "fermee": "Fermée · Closed",
               "expiree": "Fermée · Closed", "retiree": "Retirée · Removed"}
        zones = {"aide": "Aide · Help", "boss": "Boss", "farm": "Farm", "chill": "Chill", "trade": "Trade",
                 "cl_aide": "Aide · Help · Clover RPG", "cl_trade": "Trade · Clover RPG"}
        for i in range(44):
            zone = r.choice(["aide", "aide", "boss", "farm", "chill", "trade", "trade", "cl_aide", "cl_trade"])
            statut = r.choice(["ouverte", "prise", "terminee", "fermee", "expiree", "retiree"])
            echange = zone.endswith("trade")
            self.entraide.append({"id": 600 + i, "zone": zone, "type": zones[zone], "emoji": "",
                                  "auteur": r.choice(self.serveur[20:900])["id"],
                                  "titre": r.choice(["Vends sabre courbe", "Échange fruit rare contre navire"] if echange else
                                                    ["Besoin d'aide pour le boss des abysses", "Quelqu'un pour farmer ce soir ?",
                                                     "Bloqué à la quête du phare"]),
                                  "champs": [["Pseudo Roblox", _slug(r.choice(PRENOMS)) + "_RS"], ["Niveau · Level", str(r.randint(20, 300))]],
                                  "statut": statut, "libelle": lib[statut], "aidants": [p["id"] for p in r.sample(self.serveur[20:900], r.randint(0, 3))],
                                  "credites": [], "certifie_par": r.choice(self.staff)["id"] if statut == "terminee" else "",
                                  "partenaire": r.choice(self.serveur[20:900])["id"] if echange and statut == "terminee" else "",
                                  "ferme_par": r.choice(self.staff)["id"] if statut in ("fermee", "retiree") else "",
                                  "cree": self.t(40), "ferme": self.t(5) if statut not in ("ouverte", "prise") else None,
                                  "lien": "https://discord.com/channels/1/4/5" if statut != "retiree" else "",
                                  "transcript": f"https://exemple.invalid/e/{600 + i}" if statut in ("terminee", "fermee") else ""})
        self.annonces = []
        for i in range(10):
            vus = [p["id"] for p in r.sample(self.serveur[20:400], r.randint(3, 60))]
            self.annonces.append({"id": 90 + i, "titre": r.choice(["Nouvelle saison du clan", "Évènement de ce week-end", "Rappel des règles du trade",
                                                                   "Le Movie 3 est sorti !"]),
                                  "texte": "**Bonjour à tous !**\nUne nouvelle annonce importante pour l'équipage. Lisez bien jusqu'au bout.",
                                  "salon": "#📢・annonces", "auteur": r.choice([self.fondateur, self.direction])["id"], "cree": self.t(45),
                                  "vues": len(vus), "vus": vus[:40], "mention": r.choice(["", "le clan", "@everyone"]),
                                  "lien": "https://discord.com/channels/1/5/6"})

    # ── catalogue RELL Seas (démonstration) ──
    def _catalogue(self, fourni: dict | None):
        if fourni:
            self.cat_types = [dict(t, version=t.get("version", 1)) for t in fourni.get("types", [])]
            self.cat_elements = [dict(e, version=e.get("version", 1)) for e in fourni.get("elements", [])]
            self.cat_maj = MAINTENANT
            return
        T = [("metier", "Métiers", "Jobs", True), ("race", "Races", "Races", False), ("faction", "Factions", "Factions", False),
             ("grade", "Grades du clan", "Clan ranks", False), ("style", "Styles de combat", "Fighting styles", True),
             ("fruit", "Fruits", "Fruits", False), ("arme", "Armes", "Weapons", True), ("navire", "Navires", "Ships", False)]
        self.cat_types = [{"cle": c, "nom": n, "nom_en": e, "champ": c, "multiple": m, "ordre": i + 1, "version": 1}
                          for i, (c, n, e, m) in enumerate(T)]
        E = {
            "metier": [("navigateur", "Navigateur", "Navigator"), ("cuisinier", "Cuisinier", "Cook"), ("medecin", "Médecin", "Doctor"),
                       ("charpentier", "Charpentier", "Shipwright"), ("canonnier", "Canonnier", "Gunner"), ("archeologue", "Archéologue", "Archaeologist"),
                       ("musicien", "Musicien", "Musician"), ("timonier", "Timonier", "Helmsman"), ("forgeron", "Forgeron", "Blacksmith"),
                       ("pecheur", "Pêcheur", "Fisher"), ("chasseur", "Chasseur de primes", "Bounty hunter"), ("marchand", "Marchand", "Merchant"),
                       ("cartographe", "Cartographe", "Cartographer"), ("plongeur", "Plongeur des abysses", "Abyss diver")],
            "race": [("humain", "Humain", "Human"), ("homme_poisson", "Homme-poisson", "Fishman"), ("mink", "Mink", "Mink"),
                     ("celeste", "Céleste", "Skypiean"), ("cyborg", "Cyborg", "Cyborg")],
            "faction": [("pirates", "Pirates", "Pirates"), ("marine", "Marine", "Marines"), ("revolution", "Révolutionnaires", "Revolutionaries"),
                        ("chasseurs", "Chasseurs", "Hunters")],
            "grade": [("capitaine", "Capitaine", "Captain"), ("second", "Second", "First mate"), ("officier", "Officier", "Officer"),
                      ("quartier_maitre", "Quartier-maître", "Quartermaster"), ("matelot", "Matelot", "Sailor"), ("mousse", "Mousse", "Cabin boy")],
            "style": [("mains_nues", "Combat à mains nues", "Brawling"), ("sabre", "Sabre", "Sword"), ("tir", "Tir", "Marksman"),
                      ("jambes", "Jeu de jambes", "Leg style")],
            "fruit": [("flamme", "Fruit de la Flamme", "Flame Fruit"), ("glace", "Fruit de la Glace", "Ice Fruit"), ("sable", "Fruit du Sable", "Sand Fruit"),
                      ("foudre", "Fruit de la Foudre", "Lightning Fruit"), ("ombre", "Fruit de l'Ombre", "Shadow Fruit")],
            "arme": [("sabre_courbe", "Sabre courbe", "Cutlass"), ("mousquet", "Mousquet", "Musket"), ("trident", "Trident", "Trident"),
                     ("hache", "Hache d'abordage", "Boarding axe")],
            "navire": [("sloop", "Sloop", "Sloop"), ("brigantin", "Brigantin", "Brigantine"), ("galion", "Galion", "Galleon"),
                       ("caravelle", "Caravelle", "Caravel")],
        }
        r = self.r
        self.cat_elements = []
        for typ, liste in E.items():
            for i, (cle, nom, nom_en) in enumerate(liste):
                nouveau = cle in ("cartographe", "plongeur", "ombre", "cyborg")
                self.cat_elements.append({
                    "type": typ, "cle": cle, "nom": nom, "nom_en": nom_en,
                    "description": f"{nom} — fiche de démonstration de la maquette. La vraie description viendra du catalogue du jeu.",
                    "categorie": r.choice(["Équipage", "Combat", "Exploration", "Commerce"]) if typ == "metier" else "",
                    "rarete": r.choice(["Commun", "Rare", "Épique", "Légendaire"]) if typ in ("fruit", "arme") else "",
                    # Comme le vrai catalogue : la plupart des icônes officielles manquent encore (champ vide) ;
                    # deux pointent vers un fichier pas encore livré (404 → pastille gravée).
                    "icone": (f"icones/rell/{typ}/{cle}.webp" if cle in ("flamme", "galion")
                              else f"media/demo/ic/{typ}/{cle}" if (typ in ("metier", "grade") or r.random() < .3) else ""),
                    "statut": "a_verifier" if (nouveau or r.random() < .2) else "confirme",
                    "source": "Wiki RELL Seas (démo)" if r.random() < .7 else "", "ordre": i + 1, "actif": cle != "hache",
                    "nouveau_movie3": nouveau, "version": 1})
        self.cat_maj = MAINTENANT

    def element(self, typ, cle):
        return next((e for e in self.cat_elements if e["type"] == typ and e["cle"] == cle), None)

    # ── affiches ──
    def _affiches(self):
        r = self.r
        self.affiches: dict[str, dict] = {}
        self.historiques: dict[str, list] = {}
        n = 0
        metiers = [e["cle"] for e in self.cat_elements if e["type"] == "metier"] or ["navigateur"]
        cles = lambda t, defaut: [e["cle"] for e in self.cat_elements if e["type"] == t and e.get("actif", True)] or defaut  # noqa: E731
        races, factions = cles("race", ["humain"]), cles("faction", ["pirates"])
        styles, fruits = cles("style", ["mains_nues"]), cles("fruit", ["flamme"])
        grades = cles("grade", ["capitaine", "second", "officier", "quartier_maitre", "matelot", "mousse"])
        for uid in self.clan_ids:
            if r.random() > .68:
                continue
            n += 1
            p = self.personnes[uid]
            rid = str(100000000 + r.randrange(10 ** 8))
            attributs = {"metier": r.sample(metiers, min(len(metiers), r.choice([1, 1, 1, 2]))),
                         "race": [r.choice(races)], "faction": [r.choice(factions)]}
            if r.random() < .5:
                attributs["style"] = [r.choice(styles)]
            if r.random() < .35:
                attributs["fruit"] = [r.choice(fruits)]
            cree = self.t(50, 2)
            a = {"id": str(n), "membre": self.ident(uid), "roblox": {"nom": _slug(p["nom"]).replace("_", "") + "_" + str(r.randint(1, 99)),
                                                                "id": rid, "avatar": f"media/avatar/{rid}"},
                 "surnom": r.choice(SURNOMS), "prime": r.choice([5, 12, 30, 50, 80, 120, 250, 500, 900, 1500, 3000]) * 100000,
                 "niveau": r.randint(10, 400), "grade": r.choices(grades, ([1, 2, 8, 10, 50, 29] + [10] * len(grades))[:len(grades)])[0],
                 "statut": r.choices(["actif", "en_mer", "absent"], [70, 20, 10])[0], "attributs": attributs,
                 "notes": r.choice(["", "Très bon navigateur, toujours présent aux sorties.", "À surveiller pour une promotion."]),
                 "cree_le": cree, "cree_par": self.fondateur["id"], "maj_le": cree + int(r.uniform(0, 20) * JOUR) if r.random() < .5 else cree,
                 "maj_par": self.direction["id"], "version": r.randint(1, 4), "retire_le": None}
            a["maj_le"] = min(a["maj_le"], int(MAINTENANT))
            self.affiches[a["id"]] = a
            self.historiques[a["id"]] = [{"quand": cree, "qui": self.fondateur["id"], "quoi": "Affiche créée", "changements": []}]
            if a["maj_le"] != cree:
                self.historiques[a["id"]].append({"quand": a["maj_le"], "qui": self.direction["id"], "quoi": "Prime modifiée",
                                                  "changements": [{"champ": "prime", "avant": 50000, "apres": a["prime"]}]})
        # deux affiches dans la corbeille
        for k in list(self.affiches)[:2]:
            self.affiches[k]["retire_le"] = self.t(6, 1)
        self.prochaine_affiche = n + 1

    def affiche_pub(self, a: dict) -> dict:
        return dict(a)

    # ── rôles ──
    def _roles(self):
        couleurs = ["#1f4e5a", "#a8641c", "#3f6b3a", "#8e2a24", "#5e3a4e", "#7a4b2a", "#4a5560", "#a8823f"]
        noms = ["Navigateur", "Cuisinier", "Médecin", "Charpentier", "Canonnier", "Archéologue", "Musicien", "Timonier",
                "Clan GoRP", "Modérateur", "Vétéran", "Membre", "Nouveau", "Pirate", "Marine", "Annonces", "🎉 Évènements"]
        self.roles = [{"id": str(950000000000000000 + i), "nom": n, "couleur": couleurs[i % len(couleurs)] if i < 10 else "",
                       "position": 40 - i} for i, n in enumerate(noms)]
        self.metiers_reglages = {"auto": True, "max_metiers": 2, "rattaches": [self.roles[8]["id"], self.roles[10]["id"]], "icones_roles": False}
        self.liens_roles = [{"type": "metier", "cle": "navigateur", "role_id": self.roles[0]["id"], "role_nom": "Navigateur", "couleur": self.roles[0]["couleur"], "auto": True},
                            {"type": "metier", "cle": "cuisinier", "role_id": self.roles[1]["id"], "role_nom": "Cuisinier", "couleur": self.roles[1]["couleur"], "auto": False},
                            {"type": "metier", "cle": "medecin", "role_id": self.roles[2]["id"], "role_nom": "Médecin", "couleur": self.roles[2]["couleur"], "auto": True},
                            {"type": "faction", "cle": "pirates", "role_id": self.roles[13]["id"], "role_nom": "Pirate", "couleur": "", "auto": False}]

    # ── annonces et événements du clan : le contrat d'evenements.py (mêmes routes, mêmes formes, mêmes refus) ──
    #  Les éléments sont gardés comme le serveur les garde (valeurs, couleur en entier, statut, phase, messages…) ;
    #  ses défauts, ses modèles et le rendu de ses cartes viennent du module lui-même (`_ev()`).
    def _evenements(self):
        self.destinations = [{"id": str(9111 + i), "cle": cle, "nom": nom, "defaut": cle == "infos"} for i, (cle, nom) in enumerate(POSTS_CLAN)]
        self.role_clan = ("900000000000000001", "Clan GoRP")
        self.evts: dict[int, dict] = {}
        self.reponses_evt: dict[int, dict] = {}
        self.prochain_evt = 1
        self.prochain_message = 7_000_000
        self.prochaine_incertaine = False
        self.lieux_evt = [{"type": "ile", "cle": "port_central", "nom": "Port de l'île centrale"}, {"type": "ile", "cle": "forteresse", "nom": "Forteresse du centre"},
                          {"type": "zone", "cle": "abysses", "nom": "Fosse des abysses"}, {"type": "lieu", "cle": "taverne", "nom": "Taverne du clan"}]
        E = _ev()
        if E is None:
            return
        self._nouvel_evt("evenement", {"titre": "Sortie en mer : le boss des abysses", "quand": int(MAINTENANT + 2 * JOUR + 3600),
                                       "texte": "Rendez-vous au port **15 minutes avant**.\nPrévoyez des vivres et vos meilleures armes.\n\n> Les absents non excusés passent leur tour.",
                                       "lieu": "Port de l'île centrale", "places": 12, "rappels": [1440, 60], "discord_event": True}, age=self.t(3))
        self._nouvel_evt("annonce", {"titre": "Nouvelles règles du clan", "texte": "Merci de lire les **nouvelles règles** épinglées dans le post Infos.",
                                     "mention": "clan"}, age=self.t(3))
        self._nouvel_evt("metiers", {"texte": "Voici les métiers officiels de chacun, à jour du Movie 3."}, age=self.t(3))
        for k, (titre, dt, rep) in enumerate([("Entraînement de combat", 1.2, (9, 3, 2)), ("Chasse au trésor", 5, (4, 6, 1)), ("Guerre de factions", -3, (14, 2, 5)),
                                              ("Réunion de l'équipage", -9, (11, 0, 3)), ("Course de navires", -16, (7, 4, 4)), ("Soirée taverne", -25, (18, 3, 1))]):
            quand = int(MAINTENANT + dt * JOUR)
            e = self._nouvel_evt("evenement", {"titre": titre, "quand": quand, "texte": "Tout l'équipage est attendu.", "places": 15 if k % 2 else 0,
                                               "mention": "clan" if k % 3 == 0 else "inscrits", "discord_event": k % 2 == 0, "lieu": "Taverne du clan" if k == 3 else ""},
                                 age=int(min(MAINTENANT, quand) - 3 * JOUR))
            self._publier_evt(e, int(min(MAINTENANT, quand) - 3 * JOUR))
            ids = self.clan_ids
            self.reponses_evt[e["id"]] = {"d": ids[:rep[0]], "p": ids[rep[0]:rep[0] + rep[1]], "n": ids[rep[0] + rep[1]:sum(rep)], "v": []}
            if k == 4:
                e.update(statut="annule", archive_le=int(quand - 5 * JOUR), version=e["version"] + 1)
            self._suivre_evt(e)
        a = self._nouvel_evt("annonce", {"titre": "Le Movie 3 est sorti !", "texte": "**Le Movie 3 est là.** Toutes les nouveautés dans le salon dédié.",
                                         "mention": "clan"}, age=self.t(1))
        self._publier_evt(a, a["cree"])
        self.reponses_evt[a["id"]]["v"] = self.clan_ids[:41]

    def _nouvel_evt(self, type_, valeurs, age=None, cle_client=None, auteur=None):
        E = _ev()
        i = self.prochain_evt
        self.prochain_evt += 1
        t = int(age or time.time())
        v = {**E._defauts(type_), **valeurs}
        qui = int(auteur or self.fondateur["id"])
        e = {"id": i, "guild_id": 1, "type": type_, "statut": "brouillon", "phase": "", "valeurs": v, "version": 1, "cle_client": cle_client,
             "cree": t, "cree_par": qui, "maj": t, "maj_par": qui, "publie": 0, "publie_par": 0, "salon_id": 0, "messages": [],
             "discord_event_id": 0, "rappels_faits": [], "quand": int(v.get("quand") or 0), "fin": E._fin(v), "note": "", "envoi_le": 0, "archive_le": 0}
        self.evts[i] = e
        self.reponses_evt[i] = {"d": [], "p": [], "n": [], "v": []}
        return e

    def _publier_evt(self, e, t, auteur=None, n_cartes=1):
        """Ce que `evenements.publier` laisse en base une fois les cartes parties."""
        E = _ev()
        dest = E._destination(self.destinations, e["valeurs"]) or self.destinations[0]
        _r, faits = E._rappels_dus(e, t)
        ids = list(range(self.prochain_message, self.prochain_message + n_cartes))
        self.prochain_message += n_cartes
        natif = 0
        if e["type"] == "evenement" and e["valeurs"].get("discord_event"):
            natif, self.prochain_message = self.prochain_message, self.prochain_message + 1
        e.update(statut="publie", publie=int(t), publie_par=int(auteur or self.direction["id"]), salon_id=int(dest["id"]), messages=ids,
                 phase="a_venir" if e["type"] == "evenement" else "", rappels_faits=sorted(faits), discord_event_id=natif, version=e["version"] + 2)

    def _suivre_evt(self, e):
        """Ce que la boucle du bot fait passer le temps venu : rappels faits, phase, archivage d'un événement fini."""
        E = _ev()
        if e["type"] != "evenement" or e["statut"] != "publie":
            return
        maintenant = time.time()
        _r, faits = E._rappels_dus(e, maintenant)
        e["rappels_faits"] = sorted(faits)
        phase = E.phase_de(e, maintenant)
        if phase != (e["phase"] or "a_venir"):
            e["phase"] = phase
            e["archive_le"] = int(maintenant) if phase == "termine" else 0

    def evt_site(self, e) -> dict:
        """Un élément tel que le site le lit (`evenements._vers_site`)."""
        E = _ev()
        dests = self.destinations
        dest = next((d for d in dests if d["id"] == str(e["salon_id"])), None) if e["salon_id"] else E._destination(dests, e["valeurs"])
        rep = self.reponses_evt.get(e["id"], {})
        salon_id = e["salon_id"] or (int(dest["id"]) if dest else 0)

        def qui(uid):
            return {"id": str(uid), "nom": self.ident(str(uid))["nom"]} if uid else None
        return {
            "id": e["id"], "type": e["type"], "statut": e["statut"], "phase": E.phase_de(e, time.time()) if e["type"] == "evenement" else "",
            "version": e["version"], "cle_client": e["cle_client"] or "", "titre": e["valeurs"]["titre"], "quand": e["valeurs"].get("quand") or None,
            "fin": E._fin(e["valeurs"]) if e["type"] == "evenement" and e["valeurs"].get("quand") else None,
            "valeurs": E._valeurs_site(e["valeurs"]), "destination": ({"id": dest["id"], "nom": dest["nom"]} if dest else None),
            "cree": e["cree"], "cree_par": qui(e["cree_par"]), "maj": e["maj"], "maj_par": qui(e["maj_par"]),
            "publie": e["publie"] or None, "publie_par": qui(e["publie_par"]),
            "lien": f"https://discord.com/channels/1/{salon_id}/{e['messages'][0]}" if e["messages"] else "", "cartes": len(e["messages"]),
            "reponses": {"disponibles": len(rep.get("d") or []), "peut_etre": len(rep.get("p") or []), "pas_disponibles": len(rep.get("n") or []),
                         "vus": len(rep.get("v") or [])},
            "discord_event": ({"id": str(e["discord_event_id"]), "lien": f"https://discord.com/events/1/{e['discord_event_id']}"} if e["discord_event_id"] else None),
            "rappels_faits": e["rappels_faits"], "note": e["note"],
        }

    def evt_equipage(self) -> dict:
        """Le clan tel que `evenements._equipage` le lit : les membres du rôle, leurs fiches (les affiches), le catalogue."""
        from types import SimpleNamespace
        membres = [SimpleNamespace(id=int(uid), display_name=self.nom(uid), bot=False) for uid in self.clan_ids]
        fiches = {}
        for a in self.affiches.values():
            if a["retire_le"] or not a["membre"].get("id"):
                continue
            at = a.get("attributs") or {}
            fiches[int(a["membre"]["id"])] = {"membre_id": a["membre"]["id"], "nom": a["membre"]["nom"], "metiers": list(at.get("metier") or []),
                                              "race": (at.get("race") or [""])[0], "grade": a.get("grade") or ""}
        catalogue: dict = {}
        for el in self.cat_elements:
            catalogue.setdefault(el["type"], {})[el["cle"]] = {"nom": el["nom"], "nom_en": el.get("nom_en", ""), "icone": el.get("icone", ""),
                                                               "icone_emoji": "", "actif": el.get("actif", True)}
        return {"role": self.role_clan, "membres": membres, "fiches": fiches, "catalogue": catalogue, "branche": True}

    # ── nettoyage ──
    def _nettoyage(self):
        """Comme `tableau.etat_nettoyage` : les règles du serveur (celles de tableau.py et des modules branchés), ce que
        chacune GARDE aujourd'hui (`compteurs` ; une règle sans compte n'y est pas), le dernier passage (`bilan` : règle
        → éléments retirés), qui l'a lancé (`par` : vide pour la boucle du jour) et les 10 derniers bilans."""
        R = [("journal_messages", "Journal : messages et vocal", "Messages supprimés ou modifiés, allées et venues en vocal : effacés du journal après ce délai.", 30, 30, 30, True),
             ("journal", "Journal : tout le reste", "Sanctions, tickets, arrivées, sécurité, site… : effacés du journal après ce délai.", 90, 90, 90, True),
             ("tickets_archives", "Tickets fermés : archives", "Un ticket fermé depuis plus longtemps passe dans les archives de la liste (il reste consultable).", 30, 7, 90, False),
             ("transcripts", "Conversations des tickets fermés", "Les pages des conversations (transcripts) : effacées après ce délai.", 120, 120, 120, True),
             ("candidatures_refusees", "Candidatures refusées", "Les fiches des candidatures refusées : effacées après ce délai (les acceptées restent).", 180, 30, 365, True),
             ("questionnaires", "Questionnaires de recrutement", "Les questions posées, les réponses et les corrections des candidatures fermées : effacées après ce délai.", 365, 30, 365, True),
             ("evenements_passes", "Événements passés", "Annonces et événements du clan terminés, annulés ou retirés : effacés après ce délai (les brouillons et les annonces publiées restent).", 60, 14, 365, True),
             ("affiches_corbeille", "Affiches en corbeille", "Une affiche retirée reste restaurable pendant ce délai, puis elle est effacée pour de bon.", 30, 7, 90, True),
             ("affiches_historique", "Historique des affiches", "Qui a changé quoi sur chaque affiche : effacé après ce délai.", 180, 30, 365, True),
             ("medias", "Images inutilisées", "Une image envoyée sur le site, utilisée nulle part et pas vue depuis ce délai : effacée.", 30, 7, 180, True),
             ("ops", "Modifications hors ligne", "La trace des modifications envoyées au retour du réseau (pour ne jamais les appliquer deux fois).", 30, 7, 90, True),
             ("sessions", "Sessions et liens du site", "Les sessions et les liens expirés : effacés dès leur fin.", 0, 0, 0, True)]
        self.regles = [{"cle": c, "nom": n, "quoi": q, "garde_jours": g, "defaut": g, "min": mi, "max": ma, "reglable": mi < ma, "auto": a}
                       for c, n, q, g, mi, ma, a in R]
        self.nettoyage_dernier = int(MAINTENANT - 9 * 3600)
        self.nettoyage_par = ""                      # le dernier passage : la boucle du jour
        self.nettoyage_lance = 0.0                   # « Lancer maintenant » : une fois toutes les 5 minutes au plus
        #  Ce que chaque règle garde aujourd'hui (« Événements passés » n'a pas de compte, comme sur le serveur).
        self.nettoyage_compteurs = {"journal_messages": 214, "journal": 1630, "tickets_archives": 58, "transcripts": 212,
                                    "candidatures_refusees": 4, "questionnaires": 31, "affiches_corbeille": 2,
                                    "affiches_historique": 96, "medias": 18, "ops": 31, "sessions": 3}
        #  Ce qu'un passage retirerait (ce qui a dépassé sa durée).
        self.nettoyage_excedents = {"journal_messages": 12, "journal": 4, "candidatures_refusees": 1, "medias": 2, "ops": 6, "sessions": 1}
        self.nettoyage_bilan = {r["cle"]: 0 for r in self.regles if r["auto"]}
        self.nettoyage_bilan.update(journal_messages=380, medias=12, ops=20)
        self.nettoyage_bilans = [{"quand": int(MAINTENANT - 9 * 3600), "total": 412, "par": "",
                                  "detail": "Journal : messages et vocal 380 · Images inutilisées 12 · Modifications hors ligne 20"},
                                 {"quand": int(MAINTENANT - 33 * 3600), "total": 377, "par": self.fondateur["id"],
                                  "detail": "Journal : messages et vocal 351 · Candidatures refusées 26"}]

    def etat_nettoyage(self) -> dict:
        qui = {x: self.ident(x) for x in [self.nettoyage_par, *(b["par"] for b in self.nettoyage_bilans)] if x}
        return {"regles": [dict(r) for r in self.regles], "compteurs": dict(self.nettoyage_compteurs),
                "dernier": self.nettoyage_dernier, "bilan": dict(self.nettoyage_bilan), "par": self.nettoyage_par,
                "bilans": [dict(b) for b in self.nettoyage_bilans[:10]], "personnes": qui}

    # ── recrutement en deux étapes : la banque, les dossiers ──
    THEMES = [("studio", "Studio RELL Games"), ("jeu", "Le jeu RELL Seas"), ("races", "Races"), ("factions", "Factions"),
              ("fruits", "Fruits"), ("combat", "Combat"), ("navires", "Navires"), ("monde", "Le monde"), ("evenements", "Évènements"),
              ("boss", "Boss"), ("personnages", "Personnages"), ("actualites", "Actualités · Movie 3")]

    def _recrutement(self, fourni: dict | None):
        r = self.r
        Q = [("studio", "Quel studio développe RELL Seas ?", "RELL Games", ["Rell Games", "RELL"]),
             ("studio", "Sur quelle plateforme se joue RELL Seas ?", "Roblox", []),
             ("studio", "Où le studio publie-t-il ses annonces officielles ? (démo)", "Sur son serveur Discord", ["Discord"]),
             ("jeu", "Quelle monnaie sert à payer les primes ?", "Le Berry", ["Berry", "Berries", "฿"]),
             ("jeu", "Que faut-il faire pour obtenir un navire ? (démo)", "L'acheter au port", ["acheter au port", "au chantier naval"]),
             ("jeu", "Combien de joueurs au plus dans un équipage ? (démo)", "8", ["huit", "8 joueurs"]),
             ("races", "Citez une race jouable. (démo)", "Homme-poisson", ["Humain", "Mink", "Céleste", "Cyborg"]),
             ("races", "Quelle race respire sous l'eau ? (démo)", "L'homme-poisson", ["homme poisson", "fishman"]),
             ("factions", "Quelle faction poursuit les pirates ? (démo)", "La Marine", ["Marine", "les marines"]),
             ("factions", "Comment rejoint-on les Révolutionnaires ? (démo)", "Par la quête de l'île cachée", ["quête de l'île cachée"]),
             ("fruits", "Que se passe-t-il si un utilisateur de fruit tombe à l'eau ? (démo)", "Il coule", ["il ne peut pas nager", "coule"]),
             ("fruits", "Quel fruit permet de voler ? (démo)", "Le fruit de la Flamme", ["fruit flamme", "flamme"]),
             ("fruits", "Combien de fruits peut-on manger à la fois ? (démo)", "Un seul", ["1", "un"]),
             ("combat", "Quels sont les trois styles de combat de base ? (démo)", "Mains nues, sabre et tir", ["poings, épée, armes à feu"]),
             ("combat", "Quelle touche sert à esquiver ? (démo)", "Q", ["la touche Q"]),
             ("navires", "Quel est le plus grand navire ? (démo)", "Le Galion", ["galion"]),
             ("navires", "Où répare-t-on son navire ? (démo)", "Au chantier naval", ["chantier"]),
             ("monde", "Comment s'appelle l'île de départ ? (démo)", "L'île du Levant", ["île du levant", "levant"]),
             ("monde", "Combien de mers compte le monde ? (démo)", "Quatre", ["4", "quatre mers"]),
             ("monde", "Que trouve-t-on au centre de la carte ? (démo)", "La forteresse de la Marine", ["forteresse"]),
             ("evenements", "À quelle fréquence a lieu l'évènement de la marée noire ? (démo)", "Toutes les deux heures", ["2 h", "deux heures"]),
             ("evenements", "Que gagne-t-on à la chasse au trésor ? (démo)", "Un coffre rare", ["coffre", "un coffre"]),
             ("boss", "Quel boss garde les abysses ? (démo)", "Le Léviathan", ["leviathan"]),
             ("boss", "Combien de phases a le boss du volcan ? (démo)", "Trois", ["3"]),
             ("boss", "Quelle arme est conseillée contre le Kraken ? (démo)", "Le harpon", ["harpon"]),
             ("personnages", "Qui vend les cartes au port ? (démo)", "La cartographe Elsa", ["Elsa", "la cartographe"]),
             ("personnages", "Qui entraîne au sabre ? (démo)", "Maître Kenji", ["Kenji"]),
             ("actualites", "Quelle mise à jour est sortie le 25 octobre 2026 ?", "Le Movie 3", ["Movie 3", "movie three", "film 3"]),
             ("actualites", "Quel nouveau métier arrive avec le Movie 3 ? (démo)", "Cartographe", ["le cartographe"]),
             ("actualites", "Quelle nouvelle zone ouvre le Movie 3 ? (démo)", "Les abysses", ["abysses", "la fosse"]),
             ("actualites", "Combien de nouveaux boss avec le Movie 3 ? (démo)", "Deux", ["2"]),
             ("studio", "Comment s'appelle le clan qui recrute ici ?", "GoRP", ["Go RP", "gorp"])]
        if fourni:
            self.banque = {q["id"]: dict(q, version=q.get("version", 1)) for q in fourni.get("questions", [])}
        else:
            self.banque = {}
            for i, (theme, question, rep, variantes) in enumerate(Q, 1):
                qid = f"q{i}"
                self.banque[qid] = {"id": qid, "theme": theme, "question": question, "reponse": rep, "variantes": variantes,
                                    "source": {"titre": r.choice(["Vidéo du Movie 3", "Wiki RELL Seas", "Guide du clan"]),
                                               "url": "https://exemple.invalid/source/" + qid,
                                               "minutage": r.choice(["", "02:14", "11:40", "27:05"])},
                                    "section": r.choice(["", "Présentation", "Mises à jour", "Progression"]),
                                    "extrait": "« … » (extrait de démonstration)" if r.random() < .4 else "",
                                    "difficulte": r.choice([1, 1, 2, 2, 3]), "statut": "confirme" if "(démo)" not in question else "a_verifier",
                                    "active": i != 6, "version": 1}
        self.liens_info = [{"id": "l1", "titre": "Vidéo officielle du Movie 3", "url": "https://exemple.invalid/movie3", "description": "Toutes les nouveautés du 25/10."},
                           {"id": "l2", "titre": "Wiki RELL Seas", "url": "https://exemple.invalid/wiki", "description": "Races, fruits, boss, îles."},
                           {"id": "l3", "titre": "Guide du clan GoRP", "url": "https://exemple.invalid/guide", "description": "Règles et grades de l'équipage."}]
        ids = list(self.banque)
        self.reglages = {"nombre_defaut": 10, "selection_defaut": ids[:3] + ids[7:10] + ids[-5:-1]}
        self.modeles_q = {"mq1": {"id": "mq1", "nom": "Débutant", "questions": ids[:6], "par_defaut": False, "version": 1},
                          "mq2": {"id": "mq2", "nom": "Spécial Movie 3", "questions": [q for q in ids if self.banque[q]["theme"] == "actualites"] + ids[:2],
                                  "par_defaut": False, "version": 1},
                          "mq3": {"id": "mq3", "nom": "Complet (12 thèmes)", "questions": self.reglages["selection_defaut"] + ids[12:14],
                                  "par_defaut": True, "version": 2}}
        self.derniere_selection = {"questions": ids[2:13], "envoye_le": self.t(2, 1), "candidat": self.nom(self.serveur[305]["id"]), "envoi_id": "e5"}
        self.dossiers: dict[int, dict] = {}
        self.prochain_envoi = 20
        for c in self.en_cours:
            d = {"ticket": c["ticket"], "candidat": self.ident(c["id"]), "etape": c["etape"], "statut": c["recrutement"],
                 "ouvert": c["ouvert"], "etape1": {"reponses": c["reponses"], "quand": c["ouvert"] + 600}, "envois": []}
            if c["etape"] == 2:
                choix = r.sample(ids, 10)
                envoi = {"id": f"e{self.prochain_envoi}", "envoye_le": c["ouvert"] + int(.6 * JOUR), "par": self.fondateur["nom"],
                         "statut": "attente" if c["recrutement"] == "etape2_attente" else "repondu", "repondu_le": None, "questions": []}
                self.prochain_envoi += 1
                for qid in choix:
                    q = self.banque[qid]
                    item = {"id": qid, "question": q["question"], "reponse_attendue": q["reponse"], "variantes": q["variantes"],
                            "theme": q["theme"], "reponse": None, "juste": None}
                    if envoi["statut"] == "repondu":
                        mode = r.choice(["exact", "exact", "variante", "faute", "faux", "vide"])
                        item["reponse"] = {"exact": q["reponse"], "variante": (q["variantes"] or [q["reponse"]])[0],
                                           "faute": q["reponse"][:-1] + "e" if len(q["reponse"]) > 3 else q["reponse"].lower(),
                                           "faux": r.choice(["Je ne sais pas", "Le Kraken", "Trois", "La Marine"]), "vide": ""}[mode]
                        if c["recrutement"] == "etape2_partiel":
                            item["juste"] = r.choice([True, True, None])
                    envoi["questions"].append(item)
                if envoi["statut"] == "repondu":
                    envoi["repondu_le"] = envoi["envoye_le"] + int(.3 * JOUR)
                d["envois"].append(envoi)
            self.dossiers[c["ticket"]] = d

    # ── calculs ──
    def equipe(self) -> list:
        eq: dict = {}
        for uid, v in self._staff30_tickets.items():
            eq.setdefault(uid, {"tickets": 0, "sanctions": 0, "questions": 0})["tickets"] += v["pris"] + v["fermes"]
        for uid, n in self._staff30_sanctions.items():
            eq.setdefault(uid, {"tickets": 0, "sanctions": 0, "questions": 0})["sanctions"] += n
        for q in self.questions:
            if q["par_staff"] and q["par_id"]:
                eq.setdefault(q["par_id"], {"tickets": 0, "sanctions": 0, "questions": 0})["questions"] += 1
        return sorted(({"id": uid, **v} for uid, v in eq.items()), key=lambda x: -(x["tickets"] + x["sanctions"] + x["questions"]))[:12]

    def alertes(self) -> list:
        out = []
        for p in self.serveur[1410:1413]:
            if p["id"] in self.alertes_gerees:
                continue
            evts = [{"quand": self.t(1), "texte": t, "gravite": g} for t, g in
                    [("Insulte détectée par le filtre", 2), ("Mentions de masse bloquées", 2), ("Lien suspect supprimé", 1)]]
            out.append({"id": p["id"], "ouverte_le": self.t(1), "maj_le": self.t(.2), "incidents": 3, "points": 7, "evenements": evts})
        return out

    def compte_casier(self) -> dict:
        """Comme `casier.comptes` : ce que chaque zone effacerait, selon l'âge (les bannissements jamais)."""
        out = {}
        for portee in ("warns", "auto", "tout"):
            out[portee] = {}
            for jours in (0, 30, 90):
                borne = time.time() - jours * JOUR
                out[portee][str(jours)] = sum(
                    1 for x in self.infractions if x["type"] not in ("ban", "tempban", "softban") and (not jours or x["date"] < borne)
                    and (x["type"] == "warn" if portee == "warns" else x["auto"] if portee == "auto" else True))
        return out

    def par_jour(self) -> dict:
        out: dict = {}
        for e in self.journal:
            if MAINTENANT - e["quand"] <= 30 * JOUR:
                j = out.setdefault(_jour(e["quand"]), {})
                j[e["cat"]] = j.get(e["cat"], 0) + 1
        return out

    def donnees(self, version: str) -> dict:
        sanctions = self.sanctions_donnees()
        tickets = self.tickets_donnees()
        cites = set()
        for e in self.journal[:400]:
            cites.update(x for x in (e["membre"], e["auteur"]) if x)
        for m in sanctions["membres"]:
            cites.add(m["id"])
        for s in sanctions["staff"]:
            cites.add(s["id"])
        for t in tickets["fermes"]:
            cites.add(t["id"])
        for q in self.questions:
            cites.add(q["id"])
        for x in self.sondages + self.idees:
            cites.add(x["auteur"])
            if x.get("retire_par"):
                cites.add(x["retire_par"])
            if x.get("decide_par"):
                cites.add(x["decide_par"])
        for x in self.entraide:
            cites.update(y for y in [x["auteur"], x["certifie_par"], x["partenaire"], *x["aidants"]] if y)
        for x in self.annonces:
            cites.update([x["auteur"], *x["vus"]])
        for l in self.lots:
            cites.update(y for y in (l["par"], l["restaure_par"]) if y)
        for a in self.alertes():
            cites.add(a["id"])
        eq = self.equipe()
        cites.update(x["id"] for x in eq)
        cites.update([self.fondateur["id"], self.direction["id"]])
        return {
            "version": version, "serveur": {"nom": "GoRP · Rell Seas FR", "icone": f"{ESPACE}/media/demo/serveur.png"},
            "genere": datetime.now(timezone.utc).isoformat(), "portee": "tout",
            "a_part": [self.fondateur["id"], self.direction["id"]],
            "candidats": self.candidats, "en_cours": self.en_cours, "ecartes": 7,
            "tickets": tickets, "clan": self.clan_donnees(), "sanctions": sanctions, "equipe": eq,
            "journal": {"evenements": self.journal[:400], "par_jour": self.par_jour()},
            "questions": self.questions_donnees(), "alertes": self.alertes(),
            "sondages": {"liste": self.sondages, "stats": {"en_cours": sum(s["statut"] == "en_cours" for s in self.sondages), "mois": 9, "votes_mois": 312}},
            "casier": {"lots": self.lots, "compte": self.compte_casier()},
            "suggestions": {"liste": self.idees, "stats": {"ouvertes": sum(1 for i in self.idees if i["statut"] in ("attente", "etude") and not i["retire_le"]),
                                                           "total": len(self.idees), "votes": sum(i["pour"] + i["contre"] for i in self.idees)}},
            "entraide": {"liste": self.entraide, "stats": {"ouvertes": sum(1 for x in self.entraide if x["statut"] in ("ouverte", "prise")),
                                                           "total": len(self.entraide), "certifiees": sum(1 for x in self.entraide if x["certifie_par"])}},
            "annonces": {"liste": self.annonces, "stats": {"total": len(self.annonces), "vues": sum(a["vues"] for a in self.annonces)}},
            "salons": self.salons_donnees(),
            "personnes": {uid: self.ident(uid) for uid in cites},
            "expire": int(MAINTENANT + 20 * 3600), "droits": {"actions": True, "staff": True, "moi": self.moi},
        }

    def fiche(self, uid: str) -> dict:
        p = self.personnes.get(uid)
        present = p is not None and uid not in [x["id"] for x in self.serveur[1580:1590]] and uid not in self.partis | self.bannis
        a_part = uid in (self.fondateur["id"], self.direction["id"])
        sanctions = [self.entree(x) for x in self.infractions if x["uid"] == uid]
        par_lui = [dict(self.entree(x), id=x["uid"]) for x in self.infractions if x["mod"] == uid][:100]
        tickets = [{"ticket": x["ticket"], "type": self.PANNEAUX[x["panel"]][0], "statut": "ouvert" if x["statut"] == "open" else "fermé",
                    "ouvert": x["ouvert"], "ferme": x["fin"][0] if x["fin"] else None, "pris_par": self.nom(x["pris_par"]),
                    "ferme_par": self.nom(x["fin"][1]) if x["fin"] else "", "motif": x["motif"], "transcript": x["transcript"],
                    "salon": f"https://discord.com/channels/1/{x['ticket']}" if x["statut"] == "open" else ""}
                   for x in reversed(self.tickets) if x["uid"] == uid]
        cands = [{"ticket": c["ticket"], "ouvert": c["ouvert"], "ferme": c["ferme"], "raison": c["motif"], "statut": c["statut"],
                  "reponses": c["reponses"], "transcript": c["transcript"]} for c in self.candidats if c["id"] == uid]
        qd = self.questions_donnees()["liste"]
        roles = [{"nom": "Clan GoRP", "couleur": "#3f6b3a"}] if uid in self.clan else []
        roles += [{"nom": "Membre", "couleur": ""}, {"nom": "🎉 Évènements", "couleur": ""}]
        if a_part:
            roles.insert(0, {"nom": "Fondateur" if uid == self.fondateur["id"] else "Direction", "couleur": "#8e2a24"})
        al = next((a for a in self.alertes() if a["id"] == uid), None)
        qui = {x: self.ident(x) for x in {uid, *[s["id"] for s in par_lui], *[e["auteur"] for e in self.journal if e["membre"] == uid and e["auteur"]]}}
        r = next((x for x in self.restreints if x["uid"] == uid), None)   # comme `tableau.fiche` : restreint par la direction
        if r:
            qui[r["par"]] = self.ident(r["par"])
        membre = dict(self.ident(uid), present=present, a_part=a_part, protege=a_part, bot=False, roles=roles if present else [],
                      arrivee=p["arrivee"] if p else None, cree=p["cree"] if p else None, mute_jusqu=self.mutes.get(uid),
                      clan=uid in self.clan,
                      restreint={"depuis": r["depuis"], "duree": 0, "raison": r["raison"], "par": r["par"]} if r else None)
        if not present:
            membre["banni"] = uid in [x["id"] for x in self.serveur[1580:1584]] or uid in self.bannis
        return {"membre": membre, "agir": not a_part, "sanctions": sanctions, "donnees": par_lui, "tickets": tickets,
                "candidatures": cands, "journal": [e for e in self.journal if e["membre"] == uid][:300],
                "questions": [q for q in qd if q["id"] == uid], "sondages": [s for s in self.sondages if s["auteur"] == uid],
                "idees": [i for i in self.idees if i["auteur"] == uid], "alerte": al, "personnes": qui}

    def conversation(self, ticket: int) -> dict:
        r = random.Random(ticket)
        x = next((t for t in self.tickets if t["ticket"] == ticket), None)
        uid = x["uid"] if x else (next((c["id"] for c in self.en_cours + self.candidats if c["ticket"] == ticket), None))
        if uid is None:
            return {"ticket": ticket, "messages": [], "absent": "Ticket introuvable."}
        staff = r.choice(self.staff)
        t0 = x["ouvert"] if x else self.t(5)
        msgs = [{"auteur": "GoRP", "bot": True, "avatar": "", "quand": t0, "texte": "", "images": [], "videos": [], "fichiers": [],
                 "embeds": [{"titre": "Ticket ouvert", "texte": "Merci d'avoir ouvert un ticket. Un membre du staff arrive.",
                             "champs": [["Type", "Support"], ["Membre", self.nom(uid)]], "pied": "Ticket #" + str(ticket)}]}]
        lignes = ["Bonjour, j'ai un problème avec mon rôle du clan.", "Bonjour ! Qu'est-ce qui se passe exactement ?",
                  "Je ne vois plus le salon du clan depuis hier.", "Je regarde ça tout de suite.", "C'est bon, le rôle est remis.",
                  "Merci beaucoup !", "Avec plaisir. Je ferme le ticket ?", "Oui, merci."]
        for i, l in enumerate(lignes[:r.randint(4, 8)]):
            qui = uid if i % 2 == 0 else staff["id"]
            msgs.append({"auteur": self.nom(qui), "bot": False, "avatar": self.ident(qui)["avatar"], "quand": t0 + 300 * (i + 1),
                         "texte": l, "images": [], "videos": [], "fichiers": [], "embeds": []})
        if r.random() < .5:
            msgs[2]["images"] = [f"{ESPACE}/media/demo/av/{uid}.png"]
        suivi = [{"quoi": "create", "qui": self.nom(uid), "quand": t0, "detail": ""},
                 {"quoi": "claim", "qui": staff["nom"], "quand": t0 + 900, "detail": ""}]
        if x and x["fin"]:
            suivi.append({"quoi": "close", "qui": self.nom(x["fin"][1]), "quand": x["fin"][0], "detail": x["motif"]})
        return {"ticket": ticket, "source": "transcript" if x and x["statut"] == "closed" else "discord", "messages": msgs,
                "lien": x["transcript"] if x else "", "suivi": suivi}

    def nouvel_id(self) -> int:
        self.compteur += 1
        return self.compteur


MONDE: Monde | None = None


# ─── Routes : la page, les fichiers statiques, le service worker ───────────
async def page(request):
    if not BASCULES["session"]:
        return web.Response(text="<!doctype html><title>Ce lien n'est plus valable</title><p>Ce lien n'est plus valable.",
                            status=403, content_type="text/html", headers=ENTETES)
    v = empreinte_site()
    texte = (RACINE / "index.html").read_text(encoding="utf-8").replace("{{V}}", v)
    r = web.Response(text=texte, content_type="text/html", headers=ENTETES_PAGE)
    r.enable_compression()
    return r


async def statique(request):
    chemin = request.match_info.get("chemin", "")
    if "\\" in chemin or chemin.startswith("/") or any(p in ("", ".", "..") for p in chemin.split("/")):
        raise web.HTTPNotFound()
    ext = chemin.rsplit(".", 1)[-1].lower() if "." in chemin else ""
    if ext not in TYPES_MIME:
        raise web.HTTPNotFound()
    f = None
    for racine in [RACINE, *EXTRA]:
        x = (racine / chemin).resolve()
        if x.is_file() and x.is_relative_to(racine.resolve()):
            f = x
            break
    if f is None:
        raise web.HTTPNotFound()
    entetes = {"Content-Type": TYPES_MIME[ext], "X-Content-Type-Options": "nosniff",
               "Cross-Origin-Resource-Policy": "same-origin",
               "Cache-Control": "public, max-age=31536000, immutable" if "v" in request.query else "no-cache"}
    return web.FileResponse(f, headers=entetes)


async def service_worker(request):
    f = RACINE / "sw.js"
    if not f.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={"Content-Type": TYPES_MIME["js"], "Cache-Control": "no-cache", "Service-Worker-Allowed": ESPACE + "/",
                                        "X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin"})


async def media(request):
    chemin = request.match_info.get("chemin", "")
    m = MONDE
    entetes = dict(ENTETES)
    if chemin.startswith("demo/av/"):
        uid = chemin[8:].removesuffix(".png")
        p = m.personnes.get(uid)
        if p is None or Image is None:
            raise web.HTTPNotFound()
        return web.Response(body=image_avatar(uid, p["nom"]), content_type="image/png", headers=entetes)
    if chemin == "demo/serveur.png" and Image is not None:
        return web.Response(body=image_icone("faction", "gorp", "Go RP"), content_type="image/png", headers=entetes)
    if chemin.startswith("demo/ic/") and Image is not None:
        morceaux = chemin.split("/")
        if len(morceaux) == 4:
            e = m.element(morceaux[2], morceaux[3])
            return web.Response(body=image_icone(morceaux[2], morceaux[3], e["nom"] if e else morceaux[3]),
                                content_type="image/png", headers=entetes)
    if chemin.startswith("avatar/") and Image is not None:
        rid = chemin[7:]
        if rid.isdigit():
            return web.Response(body=image_roblox(rid), content_type="image/png", headers=entetes)
    if chemin in m.medias:
        octets, mime = m.medias[chemin]
        return web.Response(body=octets, content_type=mime, headers=entetes)
    raise web.HTTPNotFound()


# ─── Les routes existantes ──────────────────────────────────────────────────
def _session_ok():
    return BASCULES["session"]


async def donnees(request):
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    corps = MONDE.donnees(empreinte_site())
    emp = dict(corps)
    emp.pop("genere", None)
    etag = '"' + hashlib.sha256(json.dumps(emp, sort_keys=True, default=str).encode()).hexdigest()[:20] + '"'
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=dict(ENTETES, ETag=etag))
    return _json(corps, etag=etag)


async def membre(request):
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    uid = request.query.get("id", "")
    if not uid.isdigit() or len(uid) > 20:
        return _json({"erreur": "membre invalide"}, 400)
    return _json(MONDE.fiche(uid))


async def conversation(request):
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    t = request.query.get("ticket", "")
    if not t.isdigit() or len(t) > 12:
        return _json({"erreur": "ticket invalide"}, 400)
    return _json(MONDE.conversation(int(t)))


async def recherche(request):
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    m = MONDE
    q = _slug(request.query.get("q", "")[:64]).replace("_", "")
    statuts = ["Actif", "Peu présent", "Inactif", "Jamais vu", "Trop récent"]
    if q:
        trouves = [p for p in m.serveur + [m.fondateur, m.direction]
                   if q in _slug(p["nom"]).replace("_", "") or q in p["pseudo"].replace(".", "") or q in p["id"]][:25]
    else:
        trouves = sorted(m.serveur, key=lambda p: -p["arrivee"])[:12]
    return _json({"role": "Clan GoRP", "membres": [
        dict(m.ident(p["id"]), clan=p["id"] in m.clan, a_part=p["id"] in (m.fondateur["id"], m.direction["id"]),
             statut=statuts[m.clan[p["id"]]["rang"]] if p["id"] in m.clan else None,
             rang=m.clan[p["id"]]["rang"] if p["id"] in m.clan else None, arrivee=p["arrivee"]) for p in trouves]})


async def export(request):
    """Comme `tableau.export` / `tableau.exporter` : mêmes colonnes, mêmes noms de fichier, mêmes refus."""
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    m, q = MONDE, request.query
    quoi, fmt = q.get("quoi", ""), "json" if q.get("format") == "json" else "csv"
    membre_, jours_ = q.get("membre", ""), q.get("jours", "30")
    if (membre_ and (not membre_.isdigit() or len(membre_) > 20)) or not jours_.isdigit() or len(jours_) > 3:
        return _json({"erreur": "demande invalide"}, 400)
    jours = max(1, min(int(jours_ or 30), 365))
    nom_id = lambda uid: f"{m.nom(uid)} ({uid})" if uid else ""  # noqa: E731
    if quoi == "journal":
        rows = [e for e in m.journal if MAINTENANT - e["quand"] <= jours * JOUR and (not membre_ or membre_ in (e["membre"], e["auteur"]))]
        entetes = ["Date", "Catégorie", "Type", "Gravité", "Membre", "Auteur", "Salon", "Texte", "Détail"]
        lignes = [[_quand(e["quand"]), e["cat"], e["type"], e["gravite"], nom_id(e["membre"]), nom_id(e["auteur"]), e["salon"],
                   e["texte"], e["detail"]] for e in rows]
        brut = [dict(e, date=_quand(e["quand"])) for e in rows]
    elif quoi == "membre" and membre_:
        f = m.fiche(membre_)
        entetes = ["Rubrique", "Date", "Quoi", "Par", "Détail", "Lien"]
        lignes = ([["Sanction", _quand(s["date"]), s["libelle"], s["par"], s["raison"], ""] for s in f["sanctions"]]
                  + [["Ticket", _quand(t["ouvert"]), f"#{t['ticket']} {t['type']} ({t['statut']})", t["ferme_par"], t["motif"],
                      t["transcript"]] for t in f["tickets"]]
                  + [["Journal", _quand(e["quand"]), e["cat"], nom_id(e["auteur"]), e["texte"] + (f" — {e['detail']}" if e["detail"] else ""), ""]
                     for e in f["journal"]]
                  + [["Question", _quand(x["quand"]), x["libelle"], x["par"], x["texte"], x["message"]] for x in f["questions"]])
        brut = f
    elif quoi == "sanctions":
        entetes = ["N°", "Date", "Membre", "Type", "Durée", "Par", "Raison"]
        lignes = [[x["sanction"], _quand(x["date"]), nom_id(x["uid"]), m.LIB.get(x["type"], x["type"]), x["duree"],
                   nom_id(x["mod"]), x["raison"]] for x in m.infractions]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    elif quoi == "questions":
        d = m.questions_donnees()
        entetes = ["Date", "Membre", "Salon", "Statut", "Répondu par", "Question", "Lien"]
        lignes = [[_quand(x["quand"]), nom_id(x["id"]), x["salon"], x["libelle"], x["par"], x["texte"], x["message"]] for x in d["liste"]]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    elif quoi == "erreurs":
        entetes = ["Date (UTC)", "Source", "Type", "Message", "Trace"]
        lignes = [["2026-10-25 10:00:00", "tableau", "TimeoutError", "démonstration", ""]]
        brut = [dict(zip(entetes, lg)) for lg in lignes]
    else:
        return _json({"erreur": "export inconnu ou réservé"}, 404)
    nom = f"{quoi}-{_slug('GoRP · Rell Seas FR').replace('_', '-')}-{datetime.now(PARIS):%Y-%m-%d}"
    if fmt == "json":
        corps, type_, nom = json.dumps(brut, ensure_ascii=False, indent=1, default=str).encode(), "application/json", nom + ".json"
    else:
        f = io.StringIO()
        w = csv.writer(f, delimiter=";", lineterminator="\r\n")
        w.writerow(entetes)
        for ligne in lignes:  # comme `tableau._csv` : une cellule qui commencerait une formule est neutralisée
            cellules = ["" if v is None else str(v).replace("\r", " ").replace("\n", " ") for v in ligne]
            w.writerow(["'" + c if c[:1] in ("=", "+", "-", "@", "\t") else c for c in cellules])
        corps, type_, nom = ("\ufeff" + f.getvalue()).encode(), "text/csv", nom + ".csv"
    return web.Response(body=corps, content_type=type_, charset="utf-8",
                        headers=dict(ENTETES, **{"Content-Disposition": f'attachment; filename="{nom}"'}))


def _origine_ok(request) -> bool:
    h = request.headers
    if h.get("X-Tableau") != "1" or h.get("Sec-Fetch-Site", "same-origin") != "same-origin":
        return False
    o = h.get("Origin")
    return o is None or o == f"{request.scheme}://{request.host}"


async def _corps(request, maximum: int = 65536):
    if request.content_length and request.content_length > maximum:
        return None
    try:
        c = await request.json()
    except (ValueError, UnicodeDecodeError):
        return None
    return c if isinstance(c, dict) else None


#  Les actions du tableau, comme `_ACTIONS_TABLEAU` de bot.py : mêmes noms, mêmes champs lus, mêmes refus et mêmes
#  messages (un corps mal formé est refusé ici aussi : le contrôle sur la maquette dit vrai). → (ok, message)
_DUREES_MUTE = {10: "10 minutes", 60: "1 heure", 360: "6 heures", 1440: "1 jour", 10080: "7 jours"}
_PROTEGE = "Le fondateur et la direction sont protégés : aucune action possible depuis le site."
_PORTEES = ("warns", "auto", "tout")
_BANS = ("ban", "tempban", "softban")


def _entier(d, k) -> int:
    try:
        return int(d.get(k) or 0)
    except (TypeError, ValueError):
        return 0


def _cible(m, uid):
    """(personne, None) ou (None, le refus) — comme `_cible_site` : présent, ni fondateur ni direction."""
    p = m.personnes.get(str(uid))
    if p is None or str(uid) in m.partis | m.bannis:
        return None, "Ce membre n'est plus sur le serveur."
    if str(uid) in (m.fondateur["id"], m.direction["id"]):
        return None, _PROTEGE
    return p, None


def _lot_casier(m, entrees, quoi):
    if not entrees:
        return None
    lot = f"zone-{int(time.time())}-{m.nouvel_id()}"
    m.archives[lot] = entrees
    m.lots.insert(0, {"lot": lot, "quand": int(time.time()), "par": m.moi, "quoi": quoi, "n": len(entrees),
                      "personnes": len({x["uid"] for x in entrees}), "restaure_le": None, "restaure_par": ""})
    return lot


def a_ticket_fermer(m, d):
    t = next((x for x in m.tickets if x["ticket"] == _entier(d, "ticket") and x["statut"] == "open"), None)
    if t is None:
        return False, "Ce ticket n'est plus ouvert."
    t["statut"], t["fin"] = "closed", (int(time.time()), m.moi)
    t["motif"] = str(d.get("motif") or "").strip()[:150] or "Fermé depuis le tableau de bord"
    return True, "Ticket fermé : transcript et journal comme d'habitude."


def a_candidature(m, d):
    if d.get("decision") == "accepter":
        return False, ("Cette action ne donne aucun rôle : accepter passe par l'étape 2 — corrige ses réponses dans la "
                       "rubrique Candidatures du site, puis accepte (rôle du clan, fermeture).")
    return True, "Candidature refusée : ticket fermé."


def a_clan_retirer(m, d, uid=None):
    uid = str(uid if uid is not None else d.get("membre") or "")
    p, refus = _cible(m, uid)
    if p is None:
        return False, refus
    if uid not in m.clan:
        return False, f"{p['nom']} n'a pas (ou plus) le rôle du clan."
    m.clan.pop(uid)
    return True, f"{p['nom']} n'a plus le rôle du clan."


def a_clan_retirer_lot(m, d):
    ids = [str(x) for x in (d.get("membres") or []) if str(x).isdigit()][:25]
    if not ids:
        return False, "Rien à retirer."
    faits, refus = 0, []
    for uid in ids:
        ok, message = a_clan_retirer(m, d, uid)
        faits += ok
        if not ok:
            refus.append(message)
    return faits > 0, f"{faits} membre(s) retiré(s) du clan." + (f" {len(refus)} refus : {refus[0]}" if refus else "")


def a_clan_ajouter(m, d):
    uid = str(d.get("membre") or "")
    p, refus = _cible(m, uid)
    if p is None:
        return False, refus
    if uid in m.clan:
        return False, f"{p['nom']} est déjà dans le clan."
    m.clan[uid] = {"rang": 4, "jours": "—", "derniere": "jamais vu", "rappel": None}
    return True, f"{p['nom']} a rejoint le clan."


def a_clan_prevenir(m, d):
    mode = str(d.get("mode") or "")
    ids = list(dict.fromkeys(str(x) for x in (d.get("membres") or []) if str(x).isdigit()))[:25]
    if mode not in ("mp", "salon") or not ids:
        return False, "Demande invalide."
    salon = None
    if mode == "salon":
        salon = next((s for s in m.clan_donnees()["salons"] if s["id"] == str(d.get("salon") or "")), None)
        if salon is None:
            return False, "Je ne peux pas écrire dans ce salon."
    cibles = [u for u in ids if u in m.clan and u not in (m.fondateur["id"], m.direction["id"])]
    if not cibles:
        return False, "Personne à prévenir : ils ne sont plus dans le clan, ou sont de la direction."
    t = int(time.time())
    for u in cibles:
        m.clan[u]["rappel"] = {"envoye_le": t, "echeance": t + 7 * JOUR, "par": m.nom(m.moi), "mode": mode,
                               "salon": salon["nom"] if salon else "", "remis": True, "statut": "en_attente",
                               "resolu_le": None, "resolu_par": 0}
    return True, (f"{len(cibles)} membre(s) prévenu(s) : retrait proposé le "
                  f"{datetime.fromtimestamp(t + 7 * JOUR, PARIS).strftime('%d/%m')} s'ils ne reviennent pas.")


def a_clan_rappel_annuler(m, d):
    c = m.clan.get(str(d.get("membre") or ""))
    if not c or not c["rappel"] or c["rappel"]["statut"] not in ("en_attente", "echu"):
        return False, "Aucun rappel en cours pour ce membre."
    c["rappel"] = None
    return True, "Rappel annulé."


def a_moderer(m, d):
    sanction = str(d.get("sanction") or "")
    if sanction not in ("warn", "mute", "unmute", "kick", "ban"):
        return False, "Sanction inconnue."
    raison = str(d.get("motif") or "").strip()[:300]
    if sanction != "unmute" and len(raison) < 3:
        return False, "Indique un motif (3 caractères au moins)."
    uid = str(d.get("membre") or "")
    p, refus = _cible(m, uid)
    if p is None:
        return False, refus

    def inscrire(typ, duree=""):
        m.infractions.insert(0, {"sanction": m.nouvel_id(), "uid": uid, "type": typ, "raison": raison, "duree": duree,
                                 "date": int(time.time()), "auto": False, "mod": m.moi})
    if sanction == "warn":
        inscrire("warn")
        total = sum(1 for x in m.infractions if x["uid"] == uid and x["type"] == "warn")
        return True, f"Avertissement enregistré ({total} au total)."
    if sanction == "mute":
        minutes = _entier(d, "duree") or 60
        if minutes not in _DUREES_MUTE:
            return False, "Durée invalide."
        inscrire("mute", _DUREES_MUTE[minutes])
        m.mutes[uid] = int(time.time()) + minutes * 60
        return True, f"{p['nom']} est muté {_DUREES_MUTE[minutes]}."
    if sanction == "unmute":
        if m.mutes.pop(uid, None) is None:
            return False, "Ce membre n'est pas muté."
        return True, f"Le mute de {p['nom']} est levé."
    inscrire(sanction)
    m.clan.pop(uid, None)
    (m.bannis if sanction == "ban" else m.partis).add(uid)
    return True, f"{p['nom']} est {'banni' if sanction == 'ban' else 'expulsé'}."


def a_question(m, d):
    statut = str(d.get("statut") or "")
    if statut not in ("traitee", "ignoree", "ouverte"):
        return False, "Statut inconnu."
    q = next((x for x in m.questions if x["question"] == _entier(d, "question")), None)
    if q is None:
        return False, "Question introuvable."
    q["statut"] = statut
    if statut == "ouverte":
        q.update(par_id="", par_staff=False, repondu_le=None)
    else:
        q.update(par_id=m.moi, repondu_le=int(time.time()))
    return True, {"traitee": "Question marquée traitée.", "ignoree": "Retirée : ce n'était pas une question.",
                  "ouverte": "Question rouverte."}[statut]


def a_alerte_geree(m, d):
    uid = str(d.get("membre") or "")
    if not uid.isdigit():
        return False, "Alerte inconnue."
    m.alertes_gerees.add(uid)
    return True, "Alerte gérée : elle disparaît du salon des logs."


def a_fiche_retirer(m, d):
    cid = str(d.get("candidat") or "")
    avant = len(m.candidats)
    m.candidats = [c for c in m.candidats if c["id"] != cid]
    return (True, "Fiche retirée.") if len(m.candidats) < avant else (False, "Fiche déjà retirée.")


def a_sanction_retirer(m, d):
    sid = _entier(d, "sanction")
    if not any(x["sanction"] == sid for x in m.infractions):
        return False, "Sanction déjà retirée."
    m.infractions = [x for x in m.infractions if x["sanction"] != sid]
    return True, "Sanction retirée du casier."


def a_casier_effacer(m, d):
    quoi, uid = str(d.get("quoi") or ""), str(d.get("membre") or "")
    if quoi not in ("warns", "tout") or not uid.isdigit():
        return False, "Demande invalide."
    if uid == m.fondateur["id"]:
        return False, "Le fondateur n'a pas de casier à effacer."
    entrees = [x for x in m.infractions if x["uid"] == uid and (quoi == "tout" or x["type"] == "warn")]
    if not entrees:
        return False, "Rien à effacer."
    m.infractions = [x for x in m.infractions if x not in entrees]
    _lot_casier(m, entrees, "Avertissements" if quoi == "warns" else "Casier entier")
    m.lots[0]["membre"] = uid
    quoi_txt = "avertissement(s)" if quoi == "warns" else "entrée(s) du casier"
    if quoi == "tout":
        m.mutes.pop(uid, None)
    return True, f"{len(entrees)} {quoi_txt} effacé(s). Annulable pendant 30 jours."


def a_casier_serveur(m, d):
    portee = str(d.get("portee") or "")
    jours = _entier(d, "jours") if str(d.get("jours", "0")).lstrip("-").isdigit() else -1
    if portee not in _PORTEES or jours not in (0, 30, 90):
        return False, "Demande invalide."
    if str(d.get("confirmation") or "").strip().upper() != "EFFACER":
        return False, "Écris EFFACER pour confirmer."
    borne = time.time() - jours * JOUR

    def dans(x):
        if x["type"] in _BANS or (jours and x["date"] >= borne):
            return False
        return x["type"] == "warn" if portee == "warns" else x["auto"] if portee == "auto" else True
    entrees = [x for x in m.infractions if dans(x)]
    if not entrees:
        return False, "Rien à effacer dans cette zone."
    m.infractions = [x for x in m.infractions if not dans(x)]
    quoi = {"warns": "Avertissements", "auto": "Détections automatiques", "tout": "Tout le casier (sauf bannissements)"}[portee]
    _lot_casier(m, entrees, quoi + (f", plus de {jours} jours" if jours else ""))
    return True, (f"{len(entrees)} entrée(s) effacée(s) pour {len({x['uid'] for x in entrees})} personne(s). "
                  "Annulable pendant 30 jours.")


def a_casier_restaurer(m, d):
    lot = next((x for x in m.lots if x["lot"] == str(d.get("lot") or "")[:80]), None)
    if lot is None or lot["restaure_le"]:
        return False, "Ce nettoyage est déjà annulé, ou trop ancien."
    entrees = m.archives.pop(lot["lot"], [])
    m.infractions = sorted(m.infractions + entrees, key=lambda x: -x["date"])
    lot.update(restaure_le=int(time.time()), restaure_par=m.moi)
    return True, f"{len(entrees) or lot['n']} entrée(s) remise(s) au casier."


def a_debannir(m, d):
    uid = str(d.get("membre") or "")
    banni = uid in m.bannis or uid in [x["id"] for x in m.serveur[1580:1584]]
    if not uid.isdigit() or not banni:
        return False, "Ce membre n'est pas banni."
    m.bannis.discard(uid)
    return True, "Bannissement levé : il peut revenir sur le serveur."


_STATUTS_IDEES = {"attente": "En attente", "etude": "À l'étude", "acceptee": "Acceptée", "refusee": "Refusée",
                  "realisee": "Réalisée"}


def a_suggestion_repondre(m, d):
    statut = str(d.get("statut") or "")
    if statut not in _STATUTS_IDEES:
        return False, "Statut inconnu."
    i = next((x for x in m.idees if x["id"] == _entier(d, "suggestion")), None)
    if i is None:
        return False, "Idée introuvable."
    i.update(statut=statut, libelle=_STATUTS_IDEES[statut], note=str(d.get("motif") or "").strip()[:800],
             decide_par=m.moi, decide_le=int(time.time()))
    return True, f"Idée : {_STATUTS_IDEES[statut]}. L'auteur est prévenu."


def a_suggestion_retirer(m, d):
    i = next((x for x in m.idees if x["id"] == _entier(d, "suggestion")), None)
    if i is None:
        return False, "Idée introuvable."
    if i["retire_le"]:
        return False, "Cette idée est déjà retirée du salon."
    i["retire_le"] = int(time.time())
    return True, "Idée retirée du salon."


def a_sondage_retirer(m, d):
    s = next((x for x in m.sondages if x["id"] == _entier(d, "sondage")), None)
    if s is None:
        return False, "Sondage introuvable."
    if s["retire_le"]:
        return False, "Ce sondage est déjà retiré du salon."
    s.update(statut="retire", retire_le=int(time.time()), retire_par=m.moi)
    return True, "Sondage retiré du salon."


ACTIONS = {"ticket_fermer": a_ticket_fermer, "candidature": a_candidature, "clan_retirer": a_clan_retirer,
           "clan_retirer_lot": a_clan_retirer_lot, "fiche_retirer": a_fiche_retirer, "sanction_retirer": a_sanction_retirer,
           "moderer": a_moderer, "question": a_question, "alerte_geree": a_alerte_geree,
           "sondage_retirer": a_sondage_retirer, "casier_effacer": a_casier_effacer, "casier_serveur": a_casier_serveur,
           "casier_restaurer": a_casier_restaurer, "debannir": a_debannir, "clan_ajouter": a_clan_ajouter,
           "clan_prevenir": a_clan_prevenir, "clan_rappel_annuler": a_clan_rappel_annuler,
           "suggestion_repondre": a_suggestion_repondre, "suggestion_retirer": a_suggestion_retirer}


async def action(request):
    if not _session_ok():
        return _json({"ok": False, "message": "Session expirée."}, 403)
    if not _origine_ok(request):
        return _json({"ok": False, "message": "Requête refusée."}, 400)
    c = await _corps(request, 4096) or {}
    fn = ACTIONS.get(str(c.get("action") or ""))
    if fn is None:
        return _json({"ok": False, "message": "Action inconnue."}, 400)
    ok, message = fn(MONDE, c)
    return _json({"ok": bool(ok), "message": str(message)})


async def sortir(request):
    if not _origine_ok(request):
        return _json({"ok": False, "message": "Requête refusée."}, 400)
    if request.query.get("partout") == "1":
        return _json({"ok": True, "message": "Toutes tes sessions sont fermées."})
    return web.Response(status=204, headers=ENTETES)


# ─── Les nouvelles routes (préfixe api/) ────────────────────────────────────
def _version_ok(objet: dict, corps: dict, genre: str) -> bool:
    cle = (genre, str(objet.get("id") or objet.get("cle")))
    if cle in MONDE.ailleurs:  # une modification « faite ailleurs » entre-temps
        MONDE.ailleurs.discard(cle)
        objet["version"] = int(objet.get("version") or 1) + 1
        objet["maj_le"], objet["maj_par"] = int(time.time()), MONDE.direction["id"]
        if genre == "affiche":
            objet["surnom"] = (objet.get("surnom") or "") + " (modifié ailleurs)"
    v = corps.get("version")
    return v is None or int(v) == int(objet.get("version") or 1)


def r_catalogue(m, q, c):
    return 200, {"types": m.cat_types, "elements": m.cat_elements, "maj": int(m.cat_maj)}


def r_catalogue_element(m, q, c):
    typ = str(c.get("type") or "")
    if not any(t["cle"] == typ for t in m.cat_types):
        return 400, {"ok": False, "erreur": "Type inconnu."}
    nom = str(c.get("nom") or "").strip()
    if not 1 <= len(nom) <= 80:
        return 400, {"ok": False, "erreur": "Le nom est obligatoire (80 caractères au plus)."}
    cle = str(c.get("cle") or "") or _slug(nom)
    e = m.element(typ, cle)
    if e is not None and c.get("cle"):
        if not _version_ok(e, c, "element"):
            return 409, {"conflit": True, "actuelle": e}
    elif e is not None:
        return 400, {"ok": False, "erreur": "Cet élément existe déjà."}
    else:
        e = {"type": typ, "cle": cle, "version": 0, "ordre": 99}
        m.cat_elements.append(e)
    for k in ("nom", "nom_en", "description", "categorie", "rarete", "icone", "source"):
        if k in c:
            e[k] = str(c.get(k) or "")[:1000]
    for k in ("actif", "nouveau_movie3"):
        if k in c:
            e[k] = bool(c[k])
    if c.get("statut") in ("confirme", "a_verifier"):
        e["statut"] = c["statut"]
    e.setdefault("statut", "a_verifier")
    e.setdefault("actif", True)
    e.setdefault("nouveau_movie3", False)
    if "ordre" in c:
        e["ordre"] = int(c.get("ordre") or 0)
    e["version"] = int(e.get("version") or 0) + 1
    m.cat_maj = time.time()
    return 200, {"ok": True, "element": e}


def r_catalogue_retirer(m, q, c):
    e = m.element(str(c.get("type") or ""), str(c.get("cle") or ""))
    if e is None:
        return 404, {"ok": False, "erreur": "Élément introuvable."}
    e["actif"] = False
    e["version"] = int(e["version"]) + 1
    return 200, {"ok": True, "element": e}


def r_catalogue_type(m, q, c):
    nom = str(c.get("nom") or "").strip()
    if not nom:
        return 400, {"ok": False, "erreur": "Le nom du type est obligatoire."}
    cle = str(c.get("cle") or "") or _slug(nom)
    t = next((x for x in m.cat_types if x["cle"] == cle), None)
    if t is None:
        t = {"cle": cle, "champ": cle, "ordre": len(m.cat_types) + 1, "version": 0}
        m.cat_types.append(t)
    elif not _version_ok(t, c, "type"):
        return 409, {"conflit": True, "actuelle": t}
    t.update({"nom": nom, "nom_en": str(c.get("nom_en") or ""), "multiple": bool(c.get("multiple"))})
    if "ordre" in c:
        t["ordre"] = int(c.get("ordre") or 0)
    t["version"] = int(t.get("version") or 0) + 1
    return 200, {"ok": True, "type": t}


def _stats_affiches(m):
    actives = [a for a in m.affiches.values() if not a["retire_le"]]
    return {"total": len(actives), "corbeille": len(m.affiches) - len(actives), "prime_totale": sum(a["prime"] for a in actives)}


def r_affiches(m, q, c):
    return 200, {"affiches": [a for a in m.affiches.values() if not a["retire_le"]], "corbeille": [a for a in m.affiches.values() if a["retire_le"]],
                 "stats": _stats_affiches(m)}


def r_affiche_get(m, q, c):
    a = m.affiches.get(str(q.get("id", "")))
    if a is None:
        return 404, {"erreur": "Affiche introuvable."}
    return 200, dict(a, historique=list(reversed(m.historiques.get(a["id"], [])))[:20])


def r_affiche(m, q, c):
    attributs = c.get("attributs") or {}
    if not isinstance(attributs, dict):
        return 400, {"ok": False, "erreur": "Attributs invalides."}
    for typ, cles in attributs.items():
        t = next((x for x in m.cat_types if x["cle"] == typ), None)
        if t is None or not isinstance(cles, list) or (not t["multiple"] and len(cles) > 1):
            return 400, {"ok": False, "erreur": f"Choix invalide pour « {typ} »."}
        for k in cles:
            if m.element(typ, k) is None:
                return 400, {"ok": False, "erreur": "Un choix n'existe pas dans le catalogue."}
    surnom = str(c.get("surnom") or "")
    if len(surnom) > 60:
        return 400, {"ok": False, "erreur": "Le surnom fait 60 caractères au plus."}
    aid = str(c.get("id") or "")
    if aid and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", aid):
        return 400, {"ok": False, "erreur": "Identifiant invalide.", "champ": "id"}
    maintenant = int(time.time())
    mid = str(c.get("membre_id") or "")
    a = m.affiches.get(aid) if aid else None
    if mid:
        autre = next((x for x in m.affiches.values() if not x["retire_le"] and x["membre"].get("id") == mid and x["id"] != aid), None)
        if autre is not None:
            return 409, {"conflit": True, "doublon": {"id": autre["id"], "nom": autre["roblox"]["nom"] or autre["membre"]["nom"]},
                         "erreur": "Ce membre a déjà une affiche."}
    if a is not None:
        if a["retire_le"]:
            return 409, {"conflit": True, "retiree": {"id": a["id"]}, "erreur": "Cette affiche est dans la corbeille."}
        if not _version_ok(a, c, "affiche"):
            return 409, {"conflit": True, "actuelle": a}
        avant = dict(a)
    else:
        a = {"id": aid or str(m.prochaine_affiche), "cree_le": maintenant, "cree_par": m.moi, "version": 0, "retire_le": None}
        m.prochaine_affiche += 1
        m.affiches[a["id"]] = a
        avant = None
    mid = mid or str((avant or {}).get("membre", {}).get("id") or "")
    a["membre"] = m.ident(mid) if mid else {"id": "", "nom": "", "avatar": ""}
    rb = c.get("roblox") or {}
    a["roblox"] = {"nom": str(rb.get("nom") or "")[:40], "id": str(rb.get("id") or ""),
                   "avatar": f"media/avatar/{rb['id']}" if str(rb.get("id") or "").isdigit() else ""}
    a["surnom"] = surnom
    a["prime"] = max(0, min(int(c.get("prime") or 0), 10 ** 12))
    a["niveau"] = max(0, min(int(c.get("niveau") or 0), 10000))
    a["grade"] = str(c.get("grade") or "")[:40]
    a["statut"] = str(c.get("statut") or "actif")[:20]
    a["attributs"] = {k: v for k, v in attributs.items() if v}
    a["notes"] = str(c.get("notes") or "")[:1000]
    a["maj_le"], a["maj_par"] = maintenant, m.moi
    a["version"] = int(a["version"]) + 1
    changements = [] if avant is None else [{"champ": k, "avant": avant.get(k), "apres": a.get(k)}
                                            for k in ("surnom", "prime", "niveau", "grade", "statut", "attributs", "notes") if avant.get(k) != a.get(k)]
    m.historiques.setdefault(a["id"], []).append({"quand": maintenant, "qui": m.moi, "quoi": "Affiche créée" if avant is None else "Affiche modifiée",
                                                  "changements": changements})
    return 200, {"ok": True, "affiche": a}


def r_affiche_retirer(m, q, c):
    a = m.affiches.get(str(c.get("id") or ""))
    if a is None:
        return 404, {"ok": False, "erreur": "Affiche introuvable."}
    if c.get("restaurer") and a["membre"].get("id"):
        autre = next((x for x in m.affiches.values() if not x["retire_le"] and x["membre"].get("id") == a["membre"]["id"] and x["id"] != a["id"]), None)
        if autre is not None:
            return 409, {"conflit": True, "doublon": {"id": autre["id"]}, "erreur": "Ce membre a déjà une autre affiche."}
    a["retire_le"] = None if c.get("restaurer") else int(time.time())
    a["version"] = int(a["version"]) + 1
    m.historiques.setdefault(a["id"], []).append({"quand": int(time.time()), "qui": m.moi,
                                                  "quoi": "Sortie de la corbeille" if c.get("restaurer") else "Mise à la corbeille", "changements": []})
    return 200, {"ok": True, "affiche": a}


def r_affiche_restaurer(m, q, c):
    return r_affiche_retirer(m, q, dict(c, restaurer=True))


def r_avatar(m, q, c):
    nom = str(c.get("roblox_nom") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", nom):
        return 400, {"ok": False, "erreur": "Nom Roblox invalide (3 à 20 lettres, chiffres ou _)."}
    rid = str(int(hashlib.sha256(nom.casefold().encode()).hexdigest()[:8], 16) % 10 ** 9 + 10 ** 8)
    return 200, {"ok": True, "roblox_id": rid, "avatar": f"media/avatar/{rid}", "nom": nom}


def r_roles(m, q, c):
    return 200, {"liens": m.liens_roles, "roles": m.roles}


def r_role(m, q, c):
    typ, cle = str(c.get("type") or ""), str(c.get("cle") or "")
    if m.element(typ, cle) is None:
        return 400, {"ok": False, "erreur": "Élément du catalogue inconnu."}
    m.liens_roles = [l for l in m.liens_roles if not (l["type"] == typ and l["cle"] == cle)]
    if c.get("retirer"):
        return 200, {"ok": True, "message": "Lien retiré."}
    if c.get("creer"):
        n = c["creer"]
        role = {"id": str(960000000000000000 + len(m.roles)), "nom": str(n.get("nom") or "")[:100], "couleur": str(n.get("couleur") or ""), "position": 1}
        m.roles.append(role)
    else:
        role = next((x for x in m.roles if x["id"] == str(c.get("role_id"))), None)
        if role is None:
            return 400, {"ok": False, "erreur": "Rôle introuvable."}
    lien = {"type": typ, "cle": cle, "role_id": role["id"], "role_nom": role["nom"], "couleur": role["couleur"], "auto": bool(c.get("auto"))}
    m.liens_roles.append(lien)
    return 200, {"ok": True, "lien": lien, "message": "Rôle lié."}


def r_roles_appliquer(m, q, c):
    a = m.affiches.get(str(c.get("affiche_id") or ""))
    if a is None:
        return 404, {"ok": False, "erreur": "Affiche introuvable."}
    donnes = [l["role_nom"] for l in m.liens_roles if l["cle"] in sum(a["attributs"].values(), [])]
    return 200, {"ok": True, "donnes": donnes, "retires": [], "message": f"{len(donnes)} rôle(s) donné(s), 0 retiré."}


def r_metiers_reglages(m, q, c):
    if c:  # POST
        if "max_metiers" in c and not 1 <= int(c.get("max_metiers") or 0) <= 5:
            return 400, {"erreur": "Entre 1 et 5 métiers.", "champ": "max_metiers"}
        if "auto" in c:
            m.metiers_reglages["auto"] = bool(c["auto"])
        if "max_metiers" in c:
            m.metiers_reglages["max_metiers"] = int(c["max_metiers"])
        if isinstance(c.get("rattaches"), list):
            connus = {r["id"] for r in m.roles}
            m.metiers_reglages["rattaches"] = [str(x) for x in c["rattaches"] if str(x) in connus]
        return 200, {"ok": True, "reglages": m.metiers_reglages}
    return 200, dict(m.metiers_reglages, roles_disponibles=m.roles)


def r_metiers_installer(m, q, c):
    crees = []
    for e in [x for x in m.cat_elements if x["type"] == "metier" and x.get("actif", True)]:
        if any(l["type"] == "metier" and l["cle"] == e["cle"] for l in m.liens_roles):
            continue
        role = {"id": str(970000000000000000 + len(m.roles)), "nom": e["nom"], "couleur": "#a8823f", "position": 2}
        m.roles.append(role)
        m.liens_roles.append({"type": "metier", "cle": e["cle"], "role_id": role["id"], "role_nom": role["nom"], "couleur": role["couleur"], "auto": True})
        crees.append(role["nom"])
    return 200, {"ok": True, "message": f"{len(crees)} rôle(s) créé(s).", "bilan": {"crees": crees, "donnes": 3 * len(crees)}}


def r_metiers_reconcilier(m, q, c):
    return 200, {"ok": True, "message": "Vérification faite.", "bilan": {"membres": len(m.clan), "rendus": 2, "retires": 1}}


def _evt_refus():
    if _ev() is None:
        return 503, {"erreur": "Le module des événements démarre : réessaie dans un instant."}
    return None


def _evt_valider(m, corps: dict, type_: str, avant: dict) -> tuple:
    """`evenements._valider`, champ par champ, mêmes messages (la maquette n'a pas de fichiers d'images : ses médias)."""
    E = _ev()
    propres, erreurs = {}, {}
    maintenant = time.time()
    for cle, brut in corps.items():
        if cle in E.CLES_CONTROLE:
            continue
        if cle not in E.CHAMPS:
            erreurs[cle] = "Champ inconnu."
            continue
        if cle in ("titre", "lieu"):
            if not isinstance(brut, str):
                erreurs[cle] = "Un texte est attendu."
                continue
            v = E._une_ligne(brut)
            limite = E.TITRE_MAX if cle == "titre" else E.LIEU_MAX
            if len(v) > limite:
                erreurs[cle] = f"{limite} caractères au plus."
                continue
            propres[cle] = v
        elif cle == "texte":
            if not isinstance(brut, str):
                erreurs[cle] = "Un texte est attendu."
                continue
            v = E._paragraphes(brut)
            if len(v) > E.TEXTE_MAX[type_]:
                erreurs[cle] = f"{E.TEXTE_MAX[type_]} caractères au plus pour ce type de publication."
                continue
            propres[cle] = v
        elif cle == "quand":
            if brut in (None, "", 0):
                propres[cle] = None
                continue
            v = E._entier(brut)
            if v is None or v < 1_600_000_000:
                erreurs[cle] = "Une date (horodatage Unix, en secondes) est attendue."
            elif v > maintenant + E.HORIZON_S:
                erreurs[cle] = "Un an à l'avance au plus."
            else:
                propres[cle] = v
        elif cle in ("duree_min", "places"):
            v = E._entier(brut)
            borne = E.DUREE_MAX if cle == "duree_min" else E.PLACES_MAX
            if v is None or not 0 <= v <= borne:
                erreurs[cle] = f"Un nombre entier de 0 à {borne} est attendu."
            else:
                propres[cle] = v
        elif cle == "image":
            if brut in (None, ""):
                propres[cle] = ""
            elif not isinstance(brut, str) or not E._ID_MEDIA.fullmatch(brut):
                erreurs[cle] = "Identifiant de média invalide."
            elif brut != (avant or {}).get("image") and brut not in m.medias:
                erreurs[cle] = "Image introuvable : renvoie-la."
            else:
                propres[cle] = brut
        elif cle == "couleur":
            v = E._couleur(brut)
            if v is None:
                erreurs[cle] = "Une couleur « #RRGGBB » est attendue."
            else:
                propres[cle] = v
        elif cle == "rappels":
            if brut is None:
                propres[cle] = []
                continue
            vals = [E._entier(x) for x in brut] if isinstance(brut, list) else None
            if vals is None or any(x is None or not 0 <= x <= E.RAPPEL_MAX for x in vals):
                erreurs[cle] = f"Une liste de minutes avant le début (0 à {E.RAPPEL_MAX}) est attendue."
            elif len(set(vals)) > E.RAPPELS_MAX:
                erreurs[cle] = f"{E.RAPPELS_MAX} rappels au plus."
            else:
                propres[cle] = sorted(set(vals), reverse=True)
        elif cle == "mention":
            if brut not in E.MENTIONS:
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
            if not v.isdigit() or all(d["id"] != v for d in m.destinations):
                erreurs[cle] = "Ce post n'est pas une destination du forum du clan."
            else:
                propres[cle] = v
        elif cle in ("reponses", "discord_event", "reserve_clan"):
            if not isinstance(brut, bool):
                erreurs[cle] = "Vrai ou faux est attendu."
            else:
                propres[cle] = brut
        elif cle == "groupement":
            if brut not in E.GROUPEMENTS:
                erreurs[cle] = "metier, grade ou race."
            elif type_ == "metiers" and brut != "metier":
                erreurs[cle] = "L'annonce des métiers se range par métier."
            else:
                propres[cle] = brut
        elif cle == "champs":
            if not isinstance(brut, list) or any(x not in E.CHAMPS_LISTE for x in brut):
                erreurs[cle] = "Une liste parmi metiers, grade, race est attendue."
            else:
                propres[cle] = list(dict.fromkeys(brut))
        elif cle == "liens":   # 26/10/2026 : les liens d'une publication (des boutons sous son texte)
            liens, faute = E._liens(brut)
            if faute:
                erreurs[cle] = faute
            else:
                propres[cle] = liens
    return {k: v for k, v in propres.items() if k in E.CHAMPS_TYPE[type_]}, erreurs


def _evt_cartes(m, e) -> tuple:
    """(cartes du modèle, avertissements, équipage) : le rendu d'`evenements.cartes`, sans Discord."""
    E = _ev()
    v = e["valeurs"]
    haut, avert = ("", [])
    if v.get("mention") == "clan":
        haut = f"<@&{m.role_clan[0]}>"
    rep = m.reponses_evt.get(e["id"]) or {"d": [], "p": [], "n": [], "v": []}
    rep = {k: [int(x) for x in rep.get(k, [])] for k in ("d", "p", "n", "v")}
    if e["type"] == "evenement":
        return E._cartes_evenement(None, e, rep, time.time(), haut), avert, None
    if e["type"] == "annonce":
        return E._cartes_annonce(e, rep, haut), avert, None
    eq = m.evt_equipage()
    return E._cartes_liste(e, eq, haut), avert, eq


def _evt_trouver(m, c):
    E = _ev()
    eid = E._id(c.get("id")) if isinstance(c, dict) else None
    if eid is not None:
        return eid, m.evts.get(eid)
    cle = c.get("cle_client") if isinstance(c, dict) else None
    if isinstance(cle, str):
        e = next((x for x in m.evts.values() if x.get("cle_client") == cle), None)
        return (e["id"] if e else None), e
    return None, None


def r_evenements(m, q, c):
    refus = _evt_refus()
    if refus:
        return refus
    E = _ev()
    maintenant = time.time()
    brouillons, a_venir, publiees, passes = [], [], [], []
    for e in sorted(m.evts.values(), key=lambda x: -x["id"])[:E.LIGNES_MAX]:
        m._suivre_evt(e)
        item = m.evt_site(e)
        if e["statut"] == "brouillon":
            brouillons.append(item)
        elif e["statut"] in ("envoi", "incertain") or (e["type"] == "evenement" and e["statut"] == "publie" and E.phase_de(e, maintenant) != "termine"):
            a_venir.append(item)
        elif e["type"] != "evenement" and e["statut"] == "publie":   # 26/10/2026 : « Publiées », comme le serveur
            publiees.append(item)
        else:
            passes.append(item)
    a_venir.sort(key=lambda x: (x["quand"] or 0, x["id"]))
    brouillons.sort(key=lambda x: -(x["maj"] or 0))
    publiees.sort(key=lambda x: (-(x["publie"] or 0), -x["id"]))
    passes.sort(key=lambda x: -max(x["quand"] or 0, x["publie"] or 0))
    return 200, {
        "destinations": [{"id": d["id"], "nom": d["nom"], "defaut": d["defaut"]} for d in m.destinations],
        "brouillons": brouillons, "a_venir": a_venir, "publiees": publiees[:E.PASSES_MAX], "publiees_total": len(publiees),
        "passes": passes[:E.PASSES_MAX], "passes_total": len(passes), "libelles": E.libelles_carte(0),
        "modeles": E.MODELES, "lieux": m.lieux_evt, "rappels_suggeres": E.RAPPELS_SUGGERES, "couleurs": E.COULEURS_SUGGEREES,
        "defauts": {t: E._valeurs_site(E._defauts(t)) for t in E.TYPES},
        "limites": {"titre": E.TITRE_MAX, "texte": E.TEXTE_MAX, "lieu": E.LIEU_MAX, "duree_min": E.DUREE_MAX, "rappel_min": E.RAPPEL_MAX,
                    "rappels": E.RAPPELS_MAX, "places": E.PLACES_MAX, "composants": E.COMPOSANTS_MAX, "caracteres": E.CARACTERES_MAX},
        "droits": {"discord_event": True, "role_clan": True, "role_clan_nom": m.role_clan[1], "fiches": True},
        "maintenant": int(maintenant),
    }


def r_brouillon(m, q, c):
    """`evenements.route_brouillon` : crée ou modifie un brouillon (rejoué hors ligne, idempotent par cle_client)."""
    refus = _evt_refus()
    if refus:
        return refus
    E = _ev()
    cle = c.get("cle_client")
    if cle is not None and (not isinstance(cle, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", cle)):
        return 400, {"erreur": "cle_client invalide.", "champs": {"cle_client": "8 à 64 caractères A-Z, 0-9, - ou _."}}
    e = None
    if c.get("id") is not None:
        eid = E._id(c["id"])
        if eid is None:
            return 400, {"erreur": "Identifiant invalide.", "champs": {"id": "Identifiant invalide."}}
        e = m.evts.get(eid)
        if e is None:
            return 404, {"erreur": "Brouillon introuvable."}
        if E._entier(c.get("version")) is None:
            return 400, {"erreur": "La version est demandée.", "champs": {"version": "La version est demandée."}}
    elif cle:
        e = next((x for x in m.evts.values() if x.get("cle_client") == cle), None)
    if e is not None and ("brouillon", str(e["id"])) in m.ailleurs:   # bascule : modifié ailleurs entre-temps
        m.ailleurs.discard(("brouillon", str(e["id"])))
        e["valeurs"]["titre"] = (e["valeurs"]["titre"] + " (modifié ailleurs)")[:E.TITRE_MAX]
        e["version"] += 1
    if e is not None and e["statut"] != "brouillon":
        return 409, {"erreur": "Déjà publiée : modifie-la en ligne (clan/modifier).", "publie": True, "actuelle": m.evt_site(e)}
    if e is not None and c.get("version") is not None and E._entier(c["version"]) != e["version"]:
        return 409, {"conflit": True, "actuelle": m.evt_site(e)}
    type_ = c.get("type", e["type"] if e else None)
    if type_ not in E.TYPES:
        return 400, {"erreur": "Type inconnu.", "champs": {"type": "evenement, annonce, metiers ou listing."}}
    avant = e["valeurs"] if e else {}
    propres, erreurs = _evt_valider(m, c, type_, avant)
    base = E._defauts(type_)
    if e is not None:
        base.update(e["valeurs"] if type_ == e["type"] else E._normaliser(type_, {k: x for k, x in e["valeurs"].items() if k in E.CHAMPS_TYPE[type_]}))
    valeurs = {**base, **propres}
    erreurs.update(E._croiser(type_, valeurs))
    if erreurs:
        return 400, {"erreur": next(iter(erreurs.values())), "champs": erreurs}
    t = int(time.time())
    if e is None:
        e = m._nouvel_evt(type_, valeurs, age=t, cle_client=cle, auteur=m.moi)
        return 200, {"ok": True, "element": m.evt_site(e)}
    e.update(type=type_, valeurs=valeurs, quand=int(valeurs.get("quand") or 0), fin=E._fin(valeurs), version=e["version"] + 1, maj=t,
             maj_par=int(m.moi), note="")
    return 200, {"ok": True, "element": m.evt_site(e)}


def r_supprimer_brouillon(m, q, c):
    refus = _evt_refus()
    if refus:
        return refus
    E = _ev()
    if c.get("id") is not None:
        eid = E._id(c["id"])
        if eid is None:
            return 400, {"erreur": "Identifiant invalide."}
        e = m.evts.get(eid)
    elif isinstance(c.get("cle_client"), str):
        e = next((x for x in m.evts.values() if x.get("cle_client") == c["cle_client"]), None)
    else:
        return 400, {"erreur": "Identifiant manquant."}
    if e is None:
        return 200, {"ok": True, "deja": True}
    if e["statut"] != "brouillon":
        return 409, {"erreur": "Seul un brouillon se supprime : annule la publication.", "actuelle": m.evt_site(e)}
    version = E._entier(c.get("version"))
    if version is not None and version != e["version"]:
        return 409, {"conflit": True, "actuelle": m.evt_site(e)}
    m.evts.pop(e["id"], None)
    m.reponses_evt.pop(e["id"], None)
    return 200, {"ok": True}


def r_apercu(m, q, c):
    """`evenements.route_apercu` : les cartes telles que Discord les affichera (le rendu même du module)."""
    refus = _evt_refus()
    if refus:
        return refus
    E = _ev()
    eid = E._id((q or {}).get("id"))
    if eid is None:
        return 400, {"erreur": "Identifiant invalide.", "champs": {"id": "Identifiant invalide."}}
    e = m.evts.get(eid)
    if e is None:
        return 404, {"erreur": "Publication introuvable."}
    maintenant = time.time()
    cartes_, avertissements, eq = _evt_cartes(m, e)
    erreurs = E._controle(e, maintenant, m.destinations, eq) if e["statut"] == "brouillon" else []
    if e["statut"] == "brouillon" and e["valeurs"].get("image") and e["valeurs"]["image"] not in m.medias:
        erreurs.append("L'image n'est plus sur le site : renvoie-la.")
    v = e["valeurs"]
    rappels = []
    if e["type"] == "evenement":
        qd = int(v.get("quand") or 0)
        for mi in v.get("rappels") or []:
            rappels.append({"minutes": mi, "quand": qd - mi * 60 if qd else None, "fait": mi in e["rappels_faits"], "passe": bool(qd) and qd - mi * 60 <= maintenant})
        if e["statut"] == "brouillon" and qd:
            passes = [r["minutes"] for r in rappels if r["passe"]]
            if passes:
                avertissements.append("Rappel(s) déjà passé(s), qui ne partiront pas : "
                                      + ", ".join("au début" if mi == 0 else f"{E._duree_txt(mi)} avant" for mi in passes) + ".")
        if v.get("rappels") and v.get("mention") != "aucune" and not v.get("reponses"):
            avertissements.append("Sans boutons de réponse, les rappels ne mentionnent personne.")
        if v.get("discord_event") and not v.get("duree_min"):
            avertissements.append("Durée non précisée : l'évènement Discord affichera une fin deux heures après le début.")
    if any(E.mesurer(x)[0] > E.COMPOSANTS_MAX or E.mesurer(x)[1] > E.CARACTERES_MAX for x in cartes_):
        erreurs.append("Une carte dépasse les limites de Discord : raccourcis le texte.")
    personnes, roles = {}, {}
    for x in cartes_:
        for b in x["blocs"]:
            for ln in b.get("lignes") or []:
                for uid in re.findall(r"<@!?(\d+)>", ln["md"]):
                    personnes[uid] = m.ident(uid)["nom"]
        for rid in re.findall(r"<@&(\d+)>", x.get("haut") or ""):
            roles[rid] = m.role_clan[1] if rid == m.role_clan[0] else "rôle supprimé"
    dest = E._destination(m.destinations, v)
    return 200, {
        "id": e["id"], "type": e["type"], "statut": e["statut"], "version": e["version"],
        "phase": E.phase_de(e, maintenant) if e["type"] == "evenement" else "",
        "destination": ({"id": dest["id"], "nom": dest["nom"]} if dest else None),
        "cartes": [E._carte_site(x) for x in cartes_], "limites": {"composants": E.COMPOSANTS_MAX, "caracteres": E.CARACTERES_MAX},
        "personnes": personnes, "roles": roles, "publiable": e["statut"] == "brouillon" and not erreurs, "erreurs": erreurs,
        "avertissements": [a for a in avertissements if a], "rappels": rappels,
        "discord_event": {"demande": bool(v.get("discord_event")), "permission": True, "id": str(e["discord_event_id"] or ""),
                          "lien": f"https://discord.com/events/1/{e['discord_event_id']}" if e["discord_event_id"] else ""},
        "maintenant": int(maintenant),
    }


def r_publier(m, q, c):
    """`evenements.route_publier` + `publier` : une fois ; incertaine si la bascule /maquette/incertain l'a demandé."""
    refus = _evt_refus()
    if refus:
        return refus
    E = _ev()
    eid, e = _evt_trouver(m, c)
    if eid is None:
        return 400, {"erreur": "Identifiant manquant.", "champs": {"id": "Identifiant manquant."}}
    version = c.get("version")
    if version is not None and E._entier(version) is None:
        return 400, {"erreur": "Version invalide.", "champs": {"version": "Un entier est attendu."}}
    forcer = c.get("forcer") is True
    if e is None:
        return 404, {"erreur": "Publication introuvable."}
    if e["statut"] == "envoi":
        return 409, {"erreur": "La publication est déjà en cours.", "actuelle": m.evt_site(e)}
    if e["statut"] != "brouillon" and not (forcer and e["statut"] == "incertain"):
        site = m.evt_site(e)
        return 409, {"erreur": "Déjà publiée." if e["statut"] == "publie" else "Ce n'est plus un brouillon.", "lien": site["lien"], "actuelle": site}
    if version is not None and int(version) != e["version"]:
        return 409, {"conflit": True, "actuelle": m.evt_site(e)}
    maintenant = time.time()
    cartes_, avertissements, eq = _evt_cartes(m, e)
    erreurs = E._controle(e, maintenant, m.destinations, eq)
    if e["valeurs"].get("image") and e["valeurs"]["image"] not in m.medias:
        erreurs.append("L'image n'est plus sur le site : renvoie-la.")
    if erreurs:
        return 400, {"erreur": erreurs[0], "erreurs": erreurs}
    if m.prochaine_incertaine and not forcer:
        m.prochaine_incertaine = False
        e.update(statut="incertain", envoi_le=int(maintenant), version=e["version"] + 2,
                 note="Discord n'a pas confirmé l'envoi et le post ne se relit pas : regarde le post avant de republier.")
        return 502, {"erreur": "Discord n'a pas confirmé la publication et je n'ai pas pu relire le post : regarde-le avant de republier.", "incertain": True}
    m._publier_evt(e, maintenant, auteur=m.moi, n_cartes=len(cartes_))
    e.update(note="", maj=int(maintenant), maj_par=int(m.moi))
    site = m.evt_site(e)
    return 200, {"ok": True, "lien": site["lien"], "element": site, "avertissements": [a for a in avertissements if a]}


def r_modifier(m, q, c):
    """`evenements.route_modifier` + `modifier` : une publication en ligne ; sans champ, « Actualiser »."""
    refus = _evt_refus()
    if refus:
        return refus
    E = _ev()
    inconnus = [k for k in c if k not in E.CHAMPS and k not in E.CLES_CONTROLE]
    if inconnus:
        return 400, {"erreur": f"Champ inconnu : {inconnus[0]}.", "champs": {k: "Champ inconnu." for k in inconnus}}
    eid = E._id(c.get("id"))
    if eid is None:
        return 400, {"erreur": "Identifiant manquant.", "champs": {"id": "Identifiant manquant."}}
    version = E._entier(c.get("version"))
    e = m.evts.get(eid)
    if e is None:
        return 404, {"erreur": "Publication introuvable."}
    maintenant = time.time()
    if e["statut"] != "publie" or (e["type"] == "evenement" and "termine" in (e["phase"], E.phase_de(e, maintenant))):
        return 409, {"erreur": "Seule une publication en ligne (événement pas encore terminé) se modifie.", "actuelle": m.evt_site(e)}
    if version is None:
        return 400, {"erreur": "La version est demandée.", "champs": {"version": "La version est demandée."}}
    if version != e["version"]:
        return 409, {"conflit": True, "actuelle": m.evt_site(e)}
    if "type" in c and c["type"] != e["type"]:
        return 400, {"erreur": "Le type d'une publication ne change pas.", "champs": {"type": "Immuable."}}
    if "destination" in c and str(c["destination"] or "") not in ("", str(e["salon_id"])):
        return 400, {"erreur": "Une publication ne change pas de post : annule-la et republie.", "champs": {"destination": "Immuable."}}
    corps = {k: x for k, x in c.items() if k != "destination"}
    propres, erreurs = _evt_valider(m, corps, e["type"], e["valeurs"])
    avant = dict(e["valeurs"])
    valeurs = {**avant, **propres}
    erreurs.update(E._croiser(e["type"], valeurs))
    q_change = e["type"] == "evenement" and valeurs.get("quand") != avant.get("quand")
    if q_change and (not valeurs.get("quand") or valeurs["quand"] < maintenant + E.AVANCE_S):
        erreurs["quand"] = "Le nouveau début doit être dans le futur (une minute au moins)."
    if erreurs:
        return 400, {"erreur": next(iter(erreurs.values())), "champs": erreurs}
    #  La publication telle qu'elle serait (une copie : un refus ne laisse rien derrière lui, comme le serveur).
    f = dict(e, valeurs=valeurs, rappels_faits=list(e["rappels_faits"]))
    if f["type"] == "evenement":
        qd = int(valeurs.get("quand") or 0)
        faits = set() if q_change else set(f["rappels_faits"])
        faits |= {mi for mi in valeurs.get("rappels") or [] if qd and qd - mi * 60 <= maintenant}
        f["rappels_faits"] = sorted(faits)
        if q_change:
            f["phase"] = "a_venir"
    cartes_, avertissements, _eq = _evt_cartes(m, f)
    n = len(cartes_)
    #  26/10/2026 : les messages sont réécrits EN PLACE, jamais un de plus (`evenements._hors_limites`).
    hors = E._hors_limites(cartes_, len(e["messages"]), e["type"])
    if hors:
        return 400, {"erreur": hors, "champs": {"texte": hors}, "messages": {"publies": len(e["messages"]), "demandes": n}}
    if f["type"] == "evenement":
        if valeurs.get("discord_event") and not f["discord_event_id"]:
            f["discord_event_id"], m.prochain_message = m.prochain_message, m.prochain_message + 1
        elif f["discord_event_id"] and not valeurs.get("discord_event"):
            f["discord_event_id"] = 0
    e.update(f)
    e.update(messages=e["messages"][:n], quand=int(valeurs.get("quand") or 0), fin=E._fin(valeurs), version=e["version"] + 1,
             maj=int(maintenant), maj_par=int(m.moi), note="")
    site = m.evt_site(e)
    return 200, {"ok": True, "lien": site["lien"], "element": site, "avertissements": [a for a in avertissements if a]}


def r_annuler(m, q, c):
    """`evenements.route_annuler` + `annuler` : un événement annulé, une annonce (métiers, listing) retirée."""
    refus = _evt_refus()
    if refus:
        return refus
    E = _ev()
    eid = E._id(c.get("id"))
    if eid is None:
        return 400, {"erreur": "Identifiant manquant.", "champs": {"id": "Identifiant manquant."}}
    prevenir = c.get("prevenir", True)
    if not isinstance(prevenir, bool):
        return 400, {"erreur": "« prevenir » : vrai ou faux.", "champs": {"prevenir": "Vrai ou faux est attendu."}}
    e = m.evts.get(eid)
    if e is None:
        return 404, {"erreur": "Publication introuvable."}
    if e["statut"] in ("annule", "retire"):
        return 200, {"ok": True, "deja": True, "element": m.evt_site(e)}
    if e["statut"] == "brouillon":
        return 409, {"erreur": "Un brouillon ne s'annule pas : supprime-le."}
    if e["statut"] == "envoi":
        return 409, {"erreur": "La publication est en cours : attends quelques secondes."}
    maintenant = int(time.time())
    if e["type"] == "evenement" and e["statut"] == "publie" and "termine" in (e["phase"], E.phase_de(e, maintenant)):
        return 409, {"erreur": "Cet événement est déjà terminé."}
    statut = "annule" if e["type"] == "evenement" and e["statut"] == "publie" else "retire"
    e.update(statut=statut, archive_le=maintenant, version=e["version"] + 1, maj=maintenant, maj_par=int(m.moi))
    return 200, {"ok": True, "element": m.evt_site(e)}


def r_nettoyage(m, q, c):
    return 200, m.etat_nettoyage()


def r_nettoyage_regle(m, q, c):
    """Comme `tableau._route_nettoyage_regle` : mêmes refus (règle inconnue, durée fixe, hors bornes), même réponse."""
    rg = next((x for x in m.regles if x["cle"] == c.get("cle")), None) if isinstance(c.get("cle"), str) else None
    if rg is None:
        return 404, {"erreur": "Règle inconnue.", "champ": "cle"}
    if rg["min"] == rg["max"]:
        return 400, {"erreur": "Cette durée est fixe.", "champ": "cle"}
    j = c.get("garde_jours")
    if isinstance(j, bool) or not isinstance(j, int) or not rg["min"] <= j <= rg["max"]:
        return 400, {"erreur": f"Entre {rg['min']} et {rg['max']} jours.", "champ": "garde_jours"}
    rg["garde_jours"] = j
    rep = m.etat_nettoyage()
    rep.update(ok=True, regle=dict(rg))
    return 200, rep


def r_nettoyage_lancer(m, q, c):
    """Comme `tableau._route_nettoyage_lancer` : chaque règle qui efface retire ce qui a dépassé sa durée ; le bilan
    est gardé ; une fois toutes les 5 minutes au plus (429)."""
    if time.time() - m.nettoyage_lance < 300:
        return 429, {"erreur": "Déjà lancé il y a moins de 5 minutes."}
    m.nettoyage_lance = time.time()
    noms = {r["cle"]: r["nom"] for r in m.regles}
    bilan = {r["cle"]: 0 for r in m.regles if r["auto"]}
    for k, n in m.nettoyage_excedents.items():
        bilan[k] = n
        m.nettoyage_compteurs[k] = max(0, m.nettoyage_compteurs.get(k, 0) - n)
    m.nettoyage_excedents = {}
    retires = {k: n for k, n in bilan.items() if n > 0}
    m.nettoyage_dernier, m.nettoyage_par, m.nettoyage_bilan = int(time.time()), m.moi, bilan
    m.nettoyage_bilans.insert(0, {"quand": int(time.time()), "total": sum(retires.values()), "par": m.moi,
                                  "detail": " · ".join(f"{noms[k]} {n}" for k, n in retires.items())})
    rep = m.etat_nettoyage()
    rep.update(ok=True)
    return 200, rep


def r_media(m, q, c):
    """`tableau._route_media` : mêmes refus (400, 413, 415), même réponse {id, url, largeur, hauteur, octets, type}."""
    brut = c.get("base64")
    if not isinstance(brut, str) or not brut:
        return 400, {"erreur": "Image absente.", "champ": "base64"}
    if brut.startswith("data:"):
        brut = brut.split(",", 1)[1] if "," in brut else ""
    try:
        octets = base64.b64decode("".join(brut.split()), validate=True)
    except ValueError:
        return 400, {"erreur": "Image illisible.", "champ": "base64"}
    if len(octets) > 8 * 1024 * 1024:
        return 413, {"erreur": "Image trop lourde : 8 Mo au plus."}
    magiques = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8")
    if not (octets.startswith(magiques) or (octets[:4] == b"RIFF" and octets[8:12] == b"WEBP")):
        return 415, {"erreur": "Format refusé : PNG, JPEG, WebP ou GIF seulement."}
    if c.get("format") not in (None, "", "banniere"):
        return 400, {"erreur": "Format demandé inconnu.", "champ": "format"}
    mid = "m" + hashlib.sha256(octets).hexdigest()[:16]
    largeur = hauteur = 0
    if c.get("format") == "banniere":   # 26/10/2026 : la bannière refaite à sa taille exacte, par le code du bot
        import bannieres
        try:
            r = bannieres.recadrer(octets)
        except bannieres.Refus as ex:
            return ex.statut, ex.corps()
        m.medias[mid] = (r["octets"], r["type"])
        return 200, {"ok": True, "id": mid, "url": f"media/{mid}", "largeur": r["largeur"], "hauteur": r["hauteur"],
                     "octets": len(r["octets"]), "type": r["type"],
                     "banniere": {"source": r["source"], "coupe": r["coupe"], "recadree": r["recadree"]}}
    if Image is not None:
        try:
            img = Image.open(io.BytesIO(octets))
            img.thumbnail((2048, 2048))
            f = io.BytesIO()
            img.convert("RGBA").save(f, "WEBP", quality=86)
            octets, (largeur, hauteur) = f.getvalue(), img.size
        except Exception:  # comme le serveur : une image qui ne se lit pas est refusée
            return 415, {"erreur": "Image illisible, ou trop grande à décoder."}
    m.medias[mid] = (octets, "image/webp")
    return 200, {"ok": True, "id": mid, "url": f"media/{mid}", "largeur": largeur, "hauteur": hauteur, "octets": len(octets),
                 "type": "image/webp"}


def _banque(m):
    return {"themes": [{"cle": k, "nom": n} for k, n in m.THEMES], "questions": list(m.banque.values()), "liens": m.liens_info,
            "reglages": m.reglages, "modeles": list(m.modeles_q.values()), "derniere_selection": m.derniere_selection}


def r_banque(m, q, c):
    return 200, _banque(m)


def r_question(m, q, c):
    texte, rep = str(c.get("question") or "").strip(), str(c.get("reponse") or "").strip()
    if not texte or not rep:
        return 400, {"ok": False, "erreur": "La question et la réponse attendue sont obligatoires."}
    if c.get("theme") not in dict(m.THEMES):
        return 400, {"ok": False, "erreur": "Thème inconnu."}
    qid = c.get("id")
    if qid:
        x = m.banque.get(str(qid))
        if x is None:
            return 404, {"ok": False, "erreur": "Question introuvable."}
        if not _version_ok(x, c, "question"):
            return 409, {"conflit": True, "actuelle": x}
    else:
        x = {"id": f"q{len(m.banque) + 100}", "version": 0}
        m.banque[x["id"]] = x
    for k in ("theme", "question", "reponse", "section", "extrait"):
        x[k] = str(c.get(k) or "")[:1000]
    x["variantes"] = [str(v)[:200] for v in (c.get("variantes") or [])][:20]
    src = c.get("source") or {}
    x["source"] = {"titre": str(src.get("titre") or "")[:120], "url": str(src.get("url") or "")[:500], "minutage": str(src.get("minutage") or "")[:12]}
    x["difficulte"] = int(c.get("difficulte") or 1)
    x["statut"] = "confirme" if c.get("statut") == "confirme" else "a_verifier"
    x["active"] = bool(c.get("active", True))
    x["version"] = int(x["version"]) + 1
    return 200, {"ok": True, "question": x}


def r_question_retirer(m, q, c):
    x = m.banque.pop(str(c.get("id") or ""), None)
    return (200, {"ok": True}) if x else (404, {"ok": False, "erreur": "Question introuvable."})


def r_liens(m, q, c):
    liens = c.get("liens")
    if not isinstance(liens, list) or len(liens) > 20:
        return 400, {"ok": False, "erreur": "Liste de liens invalide."}
    m.liens_info = [{"id": str(l.get("id") or f"l{i}"), "titre": str(l.get("titre") or "")[:120], "url": str(l.get("url") or "")[:500],
                     "description": str(l.get("description") or "")[:300]} for i, l in enumerate(liens, 1)]
    return 200, {"ok": True, "liens": m.liens_info}


def r_reglages(m, q, c):
    n = int(c.get("nombre_defaut") or m.reglages["nombre_defaut"])
    if not 1 <= n <= 40:
        return 400, {"ok": False, "erreur": "Entre 1 et 40 questions."}
    m.reglages["nombre_defaut"] = n
    if isinstance(c.get("selection_defaut"), list):
        m.reglages["selection_defaut"] = [str(x) for x in c["selection_defaut"] if str(x) in m.banque]
    return 200, {"ok": True, "reglages": m.reglages}


def r_modele(m, q, c):
    nom = str(c.get("nom") or "").strip()
    qs = [str(x) for x in (c.get("questions") or []) if str(x) in m.banque]
    if not nom or not qs:
        return 400, {"ok": False, "erreur": "Un nom et au moins une question."}
    mid = c.get("id")
    if mid:
        x = m.modeles_q.get(str(mid))
        if x is None:
            return 404, {"ok": False, "erreur": "Modèle introuvable."}
        if not _version_ok(x, c, "modele"):
            return 409, {"conflit": True, "actuelle": x}
    else:
        x = {"id": f"mq{len(m.modeles_q) + 10}", "version": 0, "par_defaut": False}
        m.modeles_q[x["id"]] = x
    x.update({"nom": nom[:60], "questions": qs})
    if c.get("par_defaut"):
        for y in m.modeles_q.values():
            y["par_defaut"] = False
        x["par_defaut"] = True
    x["version"] = int(x["version"]) + 1
    return 200, {"ok": True, "modele": x}


def r_modele_retirer(m, q, c):
    x = m.modeles_q.pop(str(c.get("id") or ""), None)
    return (200, {"ok": True}) if x else (404, {"ok": False, "erreur": "Modèle introuvable."})


def r_dossier(m, q, c):
    try:
        d = m.dossiers[int(q.get("ticket", "0"))]
    except (KeyError, ValueError):
        return 404, {"erreur": "Dossier introuvable."}
    return 200, dict(d, liens=m.liens_info, message_refus_etape1=(
        "Tes réponses ne correspondent pas à ce que nous attendons : ce ticket va être clôturé. Merci d'avoir créé un ticket.\n"
        "Your answers do not match what we expect: this ticket will be closed. Thank you for opening a ticket."),
        message_refus=("Merci pour ta candidature. Elle n'est pas retenue cette fois-ci : ce ticket va être clôturé.\n"
                       "Thank you for applying. Your application was not accepted this time: this ticket will be closed."))


def r_suivi(m, q, c):
    """Comme `questionnaire.suivi` (`GET recrutement/suivi`) : chaque candidature ouverte et son ÉTAPE — « etape1 »,
    « etape2 » (questionnaire envoyé, pas de réponse), « reponses » (à corriger) — avec le résumé du dernier envoi.
    `donnees` ne porte pas l'étape : l'aperçu et les compteurs du site la lisent ici."""
    ouverts = []
    for c_ in m.en_cours:
        etat = str(c_.get("recrutement") or "etape1")
        etape = "etape1" if etat == "etape1" else "etape2" if etat == "etape2_attente" else "reponses"
        envois = (m.dossiers.get(c_["ticket"]) or {}).get("envois") or []
        resume = None
        if envois:
            e = envois[-1]
            qs = e.get("questions") or []
            repondues = sum(1 for x in qs if str(x.get("reponse") or "").strip())
            corrigees = [x for x in qs if x.get("juste") is not None]
            justes = sum(1 for x in corrigees if x["juste"])
            resume = {"id": e["id"], "nb": len(qs), "statut": "envoye" if e["statut"] == "attente" else "repondu",
                      "envoye_le": e["envoye_le"], "repondu_le": e["repondu_le"],
                      #  26/10/2026 (questionnaire.suivi) : les étapes du questionnaire, une à la fois (« porte »).
                      "etapes": 1, "etape_ouverte": 2, "etape_envoyee": 2 if e["statut"] != "attente" else 0, "total": 2,
                      "porte": True,
                      "bilan": {"total": len(qs), "repondues": repondues, "corrigees": len(corrigees), "justes": justes,
                                "fausses": len(corrigees) - justes, "complet": bool(qs) and len(corrigees) == len(qs),
                                "reussite": bool(qs) and justes == len(qs), "taux": round(100 * justes / len(qs)) if qs else 0,
                                "exigence": 100}}
        #  26/10/2026 : le mode du panneau, la prise en charge et la PROCHAINE action (analyser · attendre · corriger).
        action = "analyser" if etape == "etape1" else "corriger" if etape == "reponses" else "attendre"
        ouverts.append({"ticket": c_["ticket"], "candidat": dict(m.ident(c_["id"]), present=c_["id"] not in m.partis | m.bannis),
                        "ouvert": c_["ouvert"], "etape": etape,
                        "annonce": 0, "mode": "approbation", "affiche": True, "panneau": "rellseas", "pris_par": None,
                        "fermeture_prevue": False, "salon": c_.get("salon", ""), "action": action, "envoi": resume})
    return 200, {"ouverts": ouverts, "recents": [], "elimines": [], "exigence": 100}


def _selection(m, c) -> tuple[list, list]:
    if c.get("derniere"):
        voulues = list(m.derniere_selection["questions"])
    elif c.get("modele"):
        mo = m.modeles_q.get(str(c["modele"]))
        voulues = list(mo["questions"]) if mo else []
    else:
        voulues = [str(x) for x in (c.get("questions") or [])]
    return [x for x in voulues if x in m.banque], [x for x in voulues if x not in m.banque]


def _envoyer(m, d, qs, cand_nom):
    envoi = {"id": f"e{m.prochain_envoi}", "envoye_le": int(time.time()), "par": m.nom(m.moi), "statut": "attente", "repondu_le": None,
             "questions": [{"id": x, "question": m.banque[x]["question"], "reponse_attendue": m.banque[x]["reponse"],
                            "variantes": m.banque[x]["variantes"], "theme": m.banque[x]["theme"], "reponse": None, "juste": None} for x in qs]}
    m.prochain_envoi += 1
    d["envois"].append(envoi)
    d["etape"], d["statut"] = 2, "etape2_attente"
    m.derniere_selection = {"questions": qs, "envoye_le": envoi["envoye_le"], "candidat": cand_nom, "envoi_id": envoi["id"]}
    return envoi


def _cand(m, ticket):
    return next((c for c in m.en_cours if c["ticket"] == ticket), None)


def r_etape1(m, q, c):
    d = m.dossiers.get(int(c.get("ticket") or 0))
    if d is None:
        return 404, {"ok": False, "erreur": "Dossier introuvable."}
    if c.get("decision") == "refuser":
        m.en_cours = [x for x in m.en_cours if x["ticket"] != d["ticket"]]
        d["statut"] = "refuse"
        return 200, {"ok": True, "message": "Refus envoyé dans le ticket ; il se ferme dans un instant."}
    if c.get("decision") != "etape2":
        return 400, {"ok": False, "erreur": "Décision inconnue."}
    qs, ignorees = _selection(m, c)
    if not qs:
        return 400, {"ok": False, "erreur": "Aucune question choisie."}
    envoi = _envoyer(m, d, qs, d["candidat"]["nom"])
    cand = _cand(m, d["ticket"])
    if cand:
        cand["etape"], cand["recrutement"] = 2, "etape2_attente"
    return 200, {"ok": True, "envoi": envoi, "ignorees": ignorees, "message": f"Étape 2 envoyée : {len(qs)} questions."}


def r_corriger(m, q, c):
    for d in m.dossiers.values():
        for e in d["envois"]:
            if e["id"] == c.get("envoi"):
                for x in e["questions"]:
                    if x["id"] == c.get("question"):
                        if c.get("juste") not in (True, False, None):
                            return 400, {"ok": False, "erreur": "Valeur invalide."}
                        x["juste"] = c.get("juste")
                        return 200, {"ok": True, "correction": {"envoi": e["id"], "question": x["id"], "juste": x["juste"]}}
    return 404, {"ok": False, "erreur": "Réponse introuvable."}


def r_decision(m, q, c):
    d = m.dossiers.get(int(c.get("ticket") or 0))
    if d is None:
        return 404, {"ok": False, "erreur": "Dossier introuvable."}
    dec = c.get("decision")
    if dec in ("accepter", "refuser"):
        m.en_cours = [x for x in m.en_cours if x["ticket"] != d["ticket"]]
        d["statut"] = "accepte" if dec == "accepter" else "refuse"
        return 200, {"ok": True, "message": "Candidat accepté : rôle du clan donné, ticket fermé." if dec == "accepter"
                     else "Refus envoyé ; le ticket se ferme."}
    if dec == "renvoyer":
        qs, ignorees = _selection(m, c)
        if not qs:
            return 400, {"ok": False, "erreur": "Aucune question choisie."}
        envoi = _envoyer(m, d, qs, d["candidat"]["nom"])
        cand = _cand(m, d["ticket"])
        if cand:
            cand["recrutement"] = "etape2_attente"
        return 200, {"ok": True, "envoi": envoi, "ignorees": ignorees, "message": f"{len(qs)} nouvelles questions envoyées."}
    return 400, {"ok": False, "erreur": "Décision inconnue."}


# ─── Textes & noms (textes.py) ──────────────────────────────────────────────
_TX: list = []


def _tx():
    """Le registre des textes du bot (`textes.py`) et les modules qui y déclarent les leurs : « Textes & noms » répond avec
    les VRAIS textes ; ce qu'on y change reste en mémoire (la maquette n'a pas de base). None s'il ne se charge pas (ses
    routes répondent alors 503, comme le serveur quand le registre démarre)."""
    if not _TX:
        try:
            _ev()                     # le chemin du bot, et les textes des annonces & événements
            import textes
            import metiers            # noqa: F401 — leurs textes se déclarent au chargement
            import questionnaire      # noqa: F401
            import zones              # noqa: F401
            _TX.append(textes)
        except Exception as ex:  # la maquette reste utilisable : l'onglet dit « indisponible »
            print("[MAQUETTE][E2] registre des textes illisible")
            print(f"[MAQUETTE][E2:DETAIL] {type(ex).__name__} {ex}")
            _TX.append(None)
    return _TX[0]


class _ServeurTextes:
    """Le serveur vu par le registre (identifiant 0) : personne n'y est connu (« modifié » sans auteur)."""
    id = 0

    @staticmethod
    def get_member(_uid):
        return None


_TX_INDISPONIBLE = (503, {"erreur": "Les textes démarrent : réessaie dans un instant."})


def r_textes(m, q, c):
    T = _tx()
    return (200, {"groupes": T.groupes(_ServeurTextes)}) if T is not None else _TX_INDISPONIBLE


def r_textes_site(m, q, c):
    T = _tx()
    return (200, {"valeurs": T.valeurs_site(0)}) if T is not None else _TX_INDISPONIBLE


def _ecrire_texte(c, origine: bool):
    """Comme `textes.ecrire` / `textes.remettre`, en mémoire : mêmes contrôles (`textes.propre`), même conflit (409)."""
    T = _tx()
    if T is None:
        return _TX_INDISPONIBLE
    cle = c.get("cle")
    if not isinstance(cle, str) or not T.declare(cle):
        return 404, {"erreur": "Ce texte n'existe pas (ou plus)."}
    d = T._DECLARES[cle]
    lignes = T._cache.setdefault(0, {})
    ligne = lignes.get(cle)
    actuelle = ligne[1] if ligne else 0
    version = c.get("version")
    if origine:
        if ligne is None or ligne[0] is None:
            return 200, {"ok": True, "deja": True, "texte": T.item(_ServeurTextes, cle)}
        valeur = d["defaut"]
        conflit = version is not None and version != actuelle
    else:
        try:
            valeur = T.propre(c.get("valeur"), d)
        except T._Invalide as ex:
            return ex.status, {"erreur": ex.message}
        conflit = version != actuelle
    if conflit:
        return 409, {"conflit": True, "erreur": "Ce texte a changé entre-temps.", "actuelle": T.item(_ServeurTextes, cle)}
    lignes[cle] = (None if valeur == d["defaut"] else valeur, actuelle + 1, int(time.time()), 0)
    return 200, {"ok": True, "texte": T.item(_ServeurTextes, cle), "avertissements": [] if origine else T.avertissements(valeur, d)}


def r_texte(m, q, c):
    return _ecrire_texte(c, False)


def r_texte_defaut(m, q, c):
    return _ecrire_texte(c, True)


def r_role_renommer(m, q, c):
    """Renommer un rôle lié (Rôles & métiers) : le nom suit dans les liens."""
    role = next((x for x in m.roles if x["id"] == str(c.get("role_id"))), None)
    if role is None:
        return 404, {"erreur": "Ce rôle n'existe plus sur le serveur."}
    nom = " ".join(str(c.get("nom") or "").split())[:100]
    if not nom:
        return 400, {"erreur": "Le nom du rôle ne peut pas être vide."}
    if nom == role["nom"]:
        return 200, {"ok": True, "deja": True, "role": role, "message": "Le rôle porte déjà ce nom."}
    role["nom"] = nom
    metiers_lies = []
    for lien in m.liens_roles:
        if lien["role_id"] == role["id"]:
            lien["role_nom"] = nom
            if lien["type"] == "metier":
                metiers_lies.append(lien["cle"])
    return 200, {"ok": True, "role": {"id": role["id"], "nom": nom, "couleur": role["couleur"]}, "metiers": metiers_lies,
                 "message": f"Rôle renommé « {nom} »."}


ROUTES = {
    "textes": ("GET", r_textes, False), "textes/site": ("GET", r_textes_site, False), "texte": ("POST", r_texte, True),
    "texte/defaut": ("POST", r_texte_defaut, True), "rell/role/renommer": ("POST", r_role_renommer, False),
    "rell/catalogue": ("GET", r_catalogue, False), "rell/catalogue/element": ("POST", r_catalogue_element, True),
    "rell/catalogue/retirer": ("POST", r_catalogue_retirer, True), "rell/catalogue/type": ("POST", r_catalogue_type, True),
    "rell/affiches": ("GET", r_affiches, False), "rell/affiche": ("GETPOST", None, True),
    "rell/affiche/retirer": ("POST", r_affiche_retirer, True), "rell/affiche/restaurer": ("POST", r_affiche_restaurer, True),
    "rell/avatar": ("POST", r_avatar, False),
    "rell/roles": ("GET", r_roles, False), "rell/role": ("POST", r_role, False), "rell/roles/appliquer": ("POST", r_roles_appliquer, False),
    "rell/metiers/reglages": ("GETPOST", r_metiers_reglages, False), "rell/metiers/installer": ("POST", r_metiers_installer, False),
    "rell/metiers/reconcilier": ("POST", r_metiers_reconcilier, False),
    "clan/evenements": ("GET", r_evenements, False), "clan/brouillon": ("POST", r_brouillon, True), "clan/apercu": ("GET", r_apercu, False),
    "clan/publier": ("POST", r_publier, False), "clan/annuler": ("POST", r_annuler, False),
    "clan/supprimer_brouillon": ("POST", r_supprimer_brouillon, True), "clan/modifier": ("POST", r_modifier, False),
    "nettoyage": ("GET", r_nettoyage, False), "nettoyage/regle": ("POST", r_nettoyage_regle, False),
    "nettoyage/lancer": ("POST", r_nettoyage_lancer, False), "media": ("POST", r_media, False),
    "recrutement/banque": ("GET", r_banque, False), "recrutement/question": ("POST", r_question, True),
    "recrutement/question/retirer": ("POST", r_question_retirer, True), "recrutement/liens": ("POST", r_liens, True),
    "recrutement/reglages": ("POST", r_reglages, True), "recrutement/modele": ("POST", r_modele, True),
    "recrutement/modele/retirer": ("POST", r_modele_retirer, True), "recrutement/dossier": ("GET", r_dossier, False),
    "recrutement/suivi": ("GET", r_suivi, False),
    "recrutement/etape1": ("POST", r_etape1, False), "recrutement/corriger": ("POST", r_corriger, True),
    "recrutement/decision": ("POST", r_decision, False),
}


async def api(request):
    nom = request.match_info.get("nom", "")
    route = ROUTES.get(nom)
    if route is None:
        return _json({"erreur": "Route inconnue."}, 404)
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    methode, fn, _hl = route
    if nom == "rell/affiche":
        fn = r_affiche_get if request.method == "GET" else r_affiche
    elif methode == "GETPOST":
        pass
    elif request.method != methode:
        return _json({"erreur": "Méthode refusée."}, 405)
    corps = None
    if request.method == "POST":
        if not _origine_ok(request):
            return _json({"ok": False, "erreur": "Requête refusée."}, 400)
        corps = await _corps(request, 12 * 1024 * 1024 if nom == "media" else 65536)
        if corps is None:
            return _json({"ok": False, "erreur": "Corps invalide ou trop gros."}, 400)
    status, rep = fn(MONDE, request.query, corps or {})
    return _json(rep, status)


async def sync(request):
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    if not _origine_ok(request):
        return _json({"ok": False, "erreur": "Requête refusée."}, 400)
    c = await _corps(request, 1024 * 1024)
    ops = (c or {}).get("ops")
    if not isinstance(ops, list) or len(ops) > 50:
        return _json({"erreur": "50 opérations au plus."}, 400)
    m, resultats = MONDE, []
    for op in ops:
        oid, nom = str(op.get("op_id") or ""), str(op.get("api") or "")
        if not re.fullmatch(r"[0-9a-f-]{36}", oid):
            resultats.append({"op_id": oid, "status": 400, "corps": {"erreur": "op_id invalide"}})
            continue
        if oid in m.ops:
            resultats.append(m.ops[oid])
            continue
        route = ROUTES.get(nom)
        if route is None or not route[2]:
            res = {"op_id": oid, "status": 400, "corps": {"erreur": "Cette modification ne peut pas attendre hors ligne."}}
        else:
            fn = r_affiche if nom == "rell/affiche" else route[1]
            st, corps = fn(m, {}, op.get("corps") if isinstance(op.get("corps"), dict) else {})
            res = {"op_id": oid, "status": st, "corps": corps}
        m.ops[oid] = res
        resultats.append(res)
    return _json({"resultats": resultats})


# ─── La présence en direct (site/direct.js) ─────────────────────────────────
async def direct(request):
    """La WebSocket du direct, réduite à une personne (la maquette n'en a qu'une) : chaque verrou lui est accordé.
    Le vrai serveur (tableau.py, plusieurs personnes, verrous refusés, 423) : outils/site_local.py."""
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=1024)
    await ws.prepare(request)
    moi = MONDE.fondateur
    async for msg in ws:
        if msg.type != WSMsgType.TEXT:
            break
        try:
            m = json.loads(msg.data)
        except ValueError:
            break
        t, maintenant = m.get("t"), int(time.time())
        if t == "bonjour":
            await ws.send_json({"t": "etat", "moi": moi["id"], "o": "maquette", "s": maintenant, "v": [],
                                "p": [{"id": moi["id"], "nom": moi["nom"], "av": moi["avatar"], "n": 1, "d": maintenant,
                                       "pages": [[str(m.get("page") or ""), maintenant]]}],
                                "cfg": {"bat": 20, "bail": 60, "inactif": 300, "tour": 10}})
        elif t == "prendre":
            await ws.send_json({"t": "pris", "o": m.get("o"), "n": 0, "ch": False,
                                "v": {"o": m.get("o"), "ti": str(m.get("ti") or ""), "id": moi["id"], "d": maintenant, "nb": 1}})
        elif t == "lacher":
            await ws.send_json({"t": "libre", "o": m.get("o"), "s": maintenant})
    return ws


# ─── Les bascules de la maquette ────────────────────────────────────────────
async def bascule(request):
    global MONDE
    quoi = request.match_info["quoi"]
    q = request.query
    if quoi == "panne":
        BASCULES["panne"] = q.get("etat", "1") == "1"
    elif quoi == "session":
        BASCULES["session"] = q.get("etat", "1") == "1"
    elif quoi == "lent":
        BASCULES["lent"] = max(0, min(int(q.get("ms", "0") or 0), 30000))
    elif quoi == "reinitialiser":
        MONDE = Monde(MONDE.graine, MONDE.catalogue_fourni, MONDE.questionnaire_fourni)
        BASCULES.update({"panne": False, "session": True, "lent": 0})
    elif quoi == "incertain":
        MONDE.prochaine_incertaine = q.get("etat", "1") == "1"
    elif quoi == "ailleurs":
        genre, ident = q.get("quoi", "affiche"), q.get("id", "")
        MONDE.ailleurs.add((genre, ident))
    elif quoi != "etat":
        raise web.HTTPNotFound()
    return web.json_response(dict(BASCULES, ailleurs=sorted(map(list, MONDE.ailleurs))),
                             headers={"Cache-Control": "no-store"})


@web.middleware
async def intermediaire(request, handler):
    if request.path.startswith("/tableau/"):
        if BASCULES["lent"]:
            await asyncio.sleep(BASCULES["lent"] / 1000)
        if BASCULES["panne"]:
            return web.Response(status=503, text="Service indisponible (maquette en panne)", headers={"Cache-Control": "no-store"})
    return await handler(request)


async def accueil(request):
    raise web.HTTPFound(ESPACE + "/")


async def visuel(request):
    """Comme le vrai serveur (`health_server`) : GET /v/<nom> → un bandeau ou une icône de `visuels/` (images publiques).
    L'aperçu d'une annonce ou d'un listing sans image montre le bandeau du clan servi ici."""
    nom = request.match_info.get("nom", "")
    f = RACINE.parent / "visuels" / nom
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}\.(gif|png)", nom) or not f.is_file():
        return web.Response(status=404, text="404")
    return web.FileResponse(f, headers={"Cache-Control": "public, max-age=604800", "X-Content-Type-Options": "nosniff"})


async def vers_espace(request):
    """Comme le vrai serveur : la page vit à /tableau/espace/ (la portée du service worker)."""
    raise web.HTTPSeeOther(ESPACE + "/")


def application() -> web.Application:
    app = web.Application(middlewares=[intermediaire], client_max_size=13 * 1024 * 1024)
    r = app.router
    r.add_get("/", accueil)
    r.add_get(ESPACE, vers_espace)
    r.add_get(ESPACE + "/", page)
    r.add_get(ESPACE + "/sw.js", service_worker)
    r.add_get(ESPACE + "/s/{chemin:.+}", statique)
    r.add_get(ESPACE + "/media/{chemin:.+}", media)
    r.add_get(ESPACE + "/donnees", donnees)
    r.add_get(ESPACE + "/membre", membre)
    r.add_get(ESPACE + "/conversation", conversation)
    r.add_get(ESPACE + "/recherche", recherche)
    r.add_get(ESPACE + "/export", export)
    r.add_post(ESPACE + "/action", action)
    r.add_post(ESPACE + "/sortir", sortir)
    r.add_post(ESPACE + "/sync", sync)
    r.add_get(ESPACE + "/direct", direct)
    r.add_route("*", ESPACE + "/api/{nom:.+}", api)
    r.add_get("/maquette/{quoi}", bascule)
    r.add_get("/v/{nom}", visuel)
    return app


def dessiner_icones_app() -> None:
    """Les icônes de l'application installée (manifeste) : un sceau de cire et une ancre de laiton sur bois sombre.
    Pleine surface (« maskable ») : le dessin tient dans le cercle central de 80 %."""
    import math
    t = 1024
    img = Image.new("RGB", (t, t), "#2f1d10")
    d = ImageDraw.Draw(img)
    r = random.Random(3)
    for y in range(0, t, 6):  # le veinage du bois, très discret
        teinte = 40 + int(8 * math.sin(y / 37.0) + r.random() * 5)
        d.line([(0, y), (t, y + r.randint(-6, 6))], fill=(teinte + 7, teinte - 10, teinte - 26), width=3)
    c = t // 2
    for k in range(18):  # le bord irrégulier de la cire
        a = k / 18 * 2 * math.pi
        rr = 330 + r.randint(-14, 16)
        x, y = c + rr * math.cos(a), c + rr * math.sin(a)
        d.ellipse([x - 70, y - 70, x + 70, y + 70], fill="#7a221d")
    for i in range(60):  # le relief de la cire
        rayon = 360 - i * 5
        f = i / 60
        couleur = (int(106 + 62 * f), int(28 + 30 * f), int(23 + 24 * f))
        d.ellipse([c - rayon, c - rayon, c + rayon, c + rayon], fill=couleur)
    d.ellipse([c - 250, c - 250, c + 250, c + 250], outline="#6a1c17", width=10)
    laiton, ombre = "#d4ae63", "#5e1612"
    for dx, coul in ((8, ombre), (0, laiton)):  # l'ancre (ombre portée puis laiton)
        o = dx
        d.ellipse([c - 52 + o, c - 250 + o, c + 52 + o, c - 146 + o], outline=coul, width=26)
        d.rectangle([c - 18 + o, c - 160 + o, c + 18 + o, c + 200 + o], fill=coul)
        d.rectangle([c - 130 + o, c - 105 + o, c + 130 + o, c - 69 + o], fill=coul)
        d.arc([c - 210 + o, c - 40 + o, c + 210 + o, c + 260 + o], 20, 160, fill=coul, width=36)
        for sens in (-1, 1):
            x0 = c + sens * 200 + o
            d.polygon([(x0, c + 60 + o), (x0 - sens * 70, c + 115 + o), (x0 + sens * 26, c + 150 + o)], fill=coul)
    for taille, nom in ((512, "app-512.png"), (192, "app-192.png")):
        img.resize((taille, taille), Image.LANCZOS).save(RACINE / nom, "PNG", optimize=True)
        print("écrit", RACINE / nom)


def main():
    global MONDE
    if "--icones-app" in __import__("sys").argv:
        dessiner_icones_app()
        return
    p = argparse.ArgumentParser(description="Maquette locale du site v2 (La Capitainerie).")
    p.add_argument("--port", type=int, default=8791)
    p.add_argument("--hote", default="127.0.0.1")
    p.add_argument("--graine", type=int, default=7)
    p.add_argument("--panne", action="store_true", help="démarrer en panne (503 partout)")
    p.add_argument("--catalogue", help="un vrai catalogue (même forme que GET rell/catalogue)")
    p.add_argument("--questionnaire", help="une vraie banque de questions ({\"questions\": [...]})")
    p.add_argument("--extra", action="append", default=[], help="un autre dossier site/ qui complète le nôtre (icônes, logos)")
    a = p.parse_args()
    EXTRA.extend(Path(x).resolve() for x in a.extra if Path(x).is_dir())
    lire = lambda f: json.loads(Path(f).read_text(encoding="utf-8")) if f else None  # noqa: E731
    MONDE = Monde(a.graine, lire(a.catalogue), lire(a.questionnaire))
    BASCULES["panne"] = a.panne
    print(f"Maquette : http://localhost:{a.port}{ESPACE}/  (site/ : {RACINE})")
    web.run_app(application(), host=a.hote, port=a.port, print=None)


if __name__ == "__main__":
    main()
