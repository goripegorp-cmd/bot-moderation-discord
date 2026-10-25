"""outils/site_maquette.py — la maquette locale du site v2, « La Capitainerie » (25/10/2026).

Sert le dossier `site/` EXACTEMENT comme le vrai serveur (mêmes chemins `/tableau/espace/...`, `{{V}}` remplacé par
l'empreinte du dossier, mêmes en-têtes, même CSP que la spécification §2.2) et simule TOUTE l'API — les routes
existantes (`donnees`, `membre`, `conversation`, `recherche`, `export`, `action`, `sortir`) et les nouvelles
(`api/rell/...`, `api/clan/...`, `api/nettoyage...`, `api/recrutement/...`, `api/media`, `sync`) — avec des données
fictives réalistes, en français, nombreuses (pour éprouver les regroupements). Les écritures modifient l'état en
mémoire ; une version périmée donne un vrai conflit 409 ; la synchronisation est idempotente (`op_id`).

Rien n'appelle Discord ni Roblox : avatars, portraits et icônes de démonstration sont dessinés ici (Pillow).

Lancer :
    python outils/site_maquette.py            → http://localhost:8791/tableau/espace/
    python outils/site_maquette.py --panne    → démarre « en panne » (toutes les adresses du site répondent 503)

Bascules (hors de la portée du service worker, donc jamais mises en cache) :
    /maquette/panne?etat=1|0       le serveur tombe / revient
    /maquette/session?etat=0|1     la session expire / revient (403 « Session expirée. »)
    /maquette/lent?ms=6000         chaque réponse attend (éprouve le délai de 4 s du service worker)
    /maquette/ailleurs?quoi=affiche&id=12   une modification « faite ailleurs » : la prochaine écriture → 409
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

from aiohttp import web

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
                      "n": 17, "personnes": 9, "restaure_le": self.t(14, 10), "restaure_par": self.direction["id"]}]
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
        return {"archives_jours": 30, "types": sorted(types.values(), key=lambda t: (not t["rellseas"], -t["total"], t["nom"])),
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
                                   "salon": "#" + r.choice(["aide", "général", "rell-seas", "trade"]),
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
                                  "salon": "#sondages"})
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
                               "pour": r.randint(0, 30), "contre": r.randint(0, 12), "salon": "#suggestions"})

    # ── entraide, annonces ──
    def _entraide_annonces(self):
        r = self.r
        self.entraide = []
        lib = {"ouverte": "Ouverte", "prise": "En cours", "terminee": "Terminée", "fermee": "Fermée", "expiree": "Fermée sans activité"}
        for i in range(44):
            zone = r.choice(["help", "help", "trade"])
            statut = r.choice(list(lib))
            self.entraide.append({"id": 600 + i, "zone": zone, "type": "Trade" if zone == "trade" else "Help", "emoji": "",
                                  "auteur": r.choice(self.serveur[20:900])["id"],
                                  "titre": r.choice(["Besoin d'aide pour le boss des abysses", "Échange fruit rare contre navire",
                                                     "Quelqu'un pour farmer ce soir ?", "Vends sabre courbe"]),
                                  "champs": [["Niveau", str(r.randint(20, 300))], ["Serveur", r.choice(["EU", "NA"])]],
                                  "statut": statut, "libelle": lib[statut], "aidants": [p["id"] for p in r.sample(self.serveur[20:900], r.randint(0, 3))],
                                  "credites": [], "certifie_par": r.choice(self.staff)["id"] if statut == "terminee" else "",
                                  "partenaire": r.choice(self.serveur[20:900])["id"] if zone == "trade" and statut == "terminee" else "",
                                  "ferme_par": "", "cree": self.t(40), "ferme": self.t(5) if statut not in ("ouverte", "prise") else None,
                                  "lien": "https://discord.com/channels/1/4/5" if statut in ("ouverte", "prise") else "", "transcript": ""})
        self.annonces = []
        for i in range(10):
            vus = [p["id"] for p in r.sample(self.serveur[20:400], r.randint(3, 60))]
            self.annonces.append({"id": 90 + i, "titre": r.choice(["Nouvelle saison du clan", "Évènement de ce week-end", "Rappel des règles du trade",
                                                                   "Le Movie 3 est sorti !"]),
                                  "texte": "**Bonjour à tous !**\nUne nouvelle annonce importante pour l'équipage. Lisez bien jusqu'au bout.",
                                  "salon": "#annonces", "auteur": r.choice([self.fondateur, self.direction])["id"], "cree": self.t(45),
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

    # ── annonces et événements du clan (contrat d'evenements.py) ──
    def _evenements(self):
        self.destinations = [{"id": "111", "nom": "📢 Infos", "defaut": True}, {"id": "112", "nom": "📣 Annonces", "defaut": False},
                             {"id": "113", "nom": "Évènements du clan", "defaut": False}, {"id": "114", "nom": "Discussions", "defaut": False}]
        self.evts: dict[int, dict] = {}
        self.prochain_evt = 1
        brouillons = [
            ("evenement", "Sortie en mer : le boss des abysses", int(MAINTENANT + 2 * JOUR + 3600),
             {"texte": "Rendez-vous au port **15 minutes avant**.\nPrévoyez des vivres et vos meilleures armes.\n\n> Les absents non excusés passent leur tour.",
              "lieu": "Port de l'île centrale", "places": 12}),
            ("annonce", "Nouvelles règles du clan", None, {"texte": "Merci de lire les **nouvelles règles** épinglées dans le salon.", "mention": "clan"}),
            ("metiers", "Les métiers de l'équipage", None, {"texte": "Voici les métiers officiels de chacun, à jour du Movie 3.", "groupement": "metier"}),
        ]
        for type_, titre, quand, val in brouillons:
            self._nouvel_evt(type_, titre, quand, val, statut="brouillon", age=self.t(3))
        for k, (titre, dt, rep) in enumerate([("Entraînement de combat", 1.2, (9, 3, 2)), ("Chasse au trésor", 5, (4, 6, 1)), ("Guerre de factions", -3, (14, 2, 5)),
                                              ("Réunion de l'équipage", -9, (11, 0, 3)), ("Course de navires", -16, (7, 4, 4)), ("Soirée taverne", -25, (18, 3, 1))]):
            e = self._nouvel_evt("evenement", titre, int(MAINTENANT + dt * JOUR), {"texte": "Tout l'équipage est attendu.", "places": 15 if k % 2 else 0},
                                 statut="annule" if k == 4 else "publie", age=int(MAINTENANT + min(dt, 0) * JOUR - 3 * JOUR))
            e["reponses"] = {"disponibles": rep[0], "peut_etre": rep[1], "pas_disponibles": rep[2], "vus": rep[0] + rep[1] + rep[2] + 6}
            e["discord_event"] = {"id": "77" + str(e["id"]), "lien": "https://discord.com/events/1/77" + str(e["id"])} if k % 2 == 0 else None
            e["rappels_faits"] = [1440] if dt < 1 else []
        a = self._nouvel_evt("annonce", "Le Movie 3 est sorti !", None, {"texte": "**Le Movie 3 est là.** Toutes les nouveautés dans le salon dédié."}, statut="publie", age=self.t(1))
        a["reponses"] = {"disponibles": 0, "peut_etre": 0, "pas_disponibles": 0, "vus": 41}
        self.modeles = [{"id": "m1", "nom": "Sortie en mer", "type": "evenement", "titre": "Sortie en mer",
                         "valeurs": {"texte": "Rendez-vous au port.", "duree_min": 90, "rappels": [1440, 60, 15], "reponses": True, "discord_event": True, "couleur": "#1f4e5a"}},
                        {"id": "m2", "nom": "Annonce officielle", "type": "annonce", "titre": "Annonce", "valeurs": {"couleur": "#8e2a24"}},
                        {"id": "m3", "nom": "Listing du dimanche", "type": "listing", "titre": "L'équipage au complet", "valeurs": {"groupement": "grade"}}]
        self.prochaine_incertaine = False

    VALEURS_DEFAUT = {"texte": "", "duree_min": 60, "lieu": "", "image": "", "couleur": "#a8823f", "rappels": [60, 15], "mention": "clan",
                      "reponses": True, "places": 0, "discord_event": True, "reserve_clan": False, "groupement": "metier", "champs": ["metiers", "grade"]}

    def _nouvel_evt(self, type_, titre, quand, valeurs, statut="brouillon", age=None, cle_client=None):
        i = self.prochain_evt
        self.prochain_evt += 1
        t = int(age or time.time())
        val = dict(self.VALEURS_DEFAUT, **valeurs)
        if type_ != "evenement":
            val.update({"reponses": False, "discord_event": False})
        e = {"id": i, "type": type_, "statut": statut, "version": 1, "cle_client": cle_client, "titre": titre, "quand": quand, "fin": None,
             "valeurs": val, "destination": "111", "cree": t, "cree_par": self.fondateur["id"], "maj": t, "maj_par": self.fondateur["id"],
             "publie": t if statut != "brouillon" else None, "publie_par": self.direction["id"] if statut != "brouillon" else None,
             "lien": f"https://discord.com/channels/1/111/{9000 + i}" if statut != "brouillon" else "", "cartes": [],
             "reponses": {"disponibles": 0, "peut_etre": 0, "pas_disponibles": 0, "vus": 0}, "discord_event": None, "rappels_faits": [], "note": ""}
        self.evts[i] = e
        self._phase(e)
        return e

    def _phase(self, e):
        q = e.get("quand")
        e["fin"] = int(q + 60 * int(e["valeurs"].get("duree_min") or 0)) if q else None
        maintenant = time.time()
        if e["type"] != "evenement":
            e["phase"] = "a_venir" if (e.get("publie") or maintenant) > maintenant - 7 * JOUR else "termine"
        elif not q or maintenant < q:
            e["phase"] = "a_venir"
        elif maintenant < (e["fin"] or q):
            e["phase"] = "en_cours"
        else:
            e["phase"] = "termine"

    # ── nettoyage ──
    def _nettoyage(self):
        self.regles = [
            {"cle": "journal_messages", "nom": "Journal · messages et vocal", "quoi": "Messages supprimés ou modifiés, entrées et sorties des vocaux.", "garde_jours": 30, "min": 7, "max": 90},
            {"cle": "journal", "nom": "Journal · le reste", "quoi": "Modération, sécurité, membres, tickets, clan…", "garde_jours": 90, "min": 30, "max": 365},
            {"cle": "tickets_archives", "nom": "Tickets fermés → archives", "quoi": "Rangés dans les archives de la liste après ce délai.", "garde_jours": 30, "min": 7, "max": 120},
            {"cle": "transcripts", "nom": "Transcripts des tickets", "quoi": "Les conversations enregistrées à la fermeture.", "garde_jours": 120, "min": 30, "max": 365},
            {"cle": "candidatures_refusees", "nom": "Candidatures refusées", "quoi": "Les dossiers des candidats refusés.", "garde_jours": 180, "min": 30, "max": 730},
            {"cle": "affiches_corbeille", "nom": "Affiches dans la corbeille", "quoi": "Effacées pour de bon après ce délai.", "garde_jours": 30, "min": 7, "max": 90},
            {"cle": "affiches_historique", "nom": "Historique des affiches", "quoi": "Qui a changé quoi sur chaque affiche.", "garde_jours": 180, "min": 30, "max": 730},
            {"cle": "evenements_passes", "nom": "Événements passés", "quoi": "Annonces et événements terminés du salon Info.", "garde_jours": 60, "min": 14, "max": 365},
            {"cle": "medias", "nom": "Images inutilisées", "quoi": "Images envoyées sur le site et plus utilisées nulle part.", "garde_jours": 30, "min": 7, "max": 180},
            {"cle": "ops", "nom": "Envois hors ligne", "quoi": "La trace des modifications envoyées au retour de la connexion.", "garde_jours": 30, "min": 7, "max": 90},
        ]
        self.nettoyage_dernier = int(MAINTENANT - 9 * 3600)
        self.nettoyage_compteurs = {"journal_messages": 214, "journal": 37, "tickets_archives": 58, "transcripts": 12, "candidatures_refusees": 4,
                                    "affiches_corbeille": 0, "affiches_historique": 0, "evenements_passes": 2, "medias": 6, "ops": 31}
        self.nettoyage_bilans = [{"quand": int(MAINTENANT - 9 * 3600), "total": 412, "detail": "journal 380 · médias 12 · envois 20"},
                                 {"quand": int(MAINTENANT - 33 * 3600), "total": 377, "detail": "journal 351 · tickets archivés 26"}]

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
            evts = [{"quand": self.t(1), "texte": t, "gravite": g} for t, g in
                    [("Insulte détectée par le filtre", 2), ("Mentions de masse bloquées", 2), ("Lien suspect supprimé", 1)]]
            out.append({"id": p["id"], "ouverte_le": self.t(1), "maj_le": self.t(.2), "incidents": 3, "points": 7, "evenements": evts})
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
            "casier": {"lots": self.lots, "compte": {"warns": {"0": 312, "30": 260, "90": 171}, "auto": {"0": 205, "30": 180, "90": 133},
                                                     "tout": {"0": 690, "30": 588, "90": 402}}},
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
        present = p is not None and uid not in [x["id"] for x in self.serveur[1580:1590]]
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
        membre = dict(self.ident(uid), present=present, a_part=a_part, protege=a_part, bot=False, roles=roles if present else [],
                      arrivee=p["arrivee"] if p else None, cree=p["cree"] if p else None, mute_jusqu=self.mutes.get(uid),
                      clan=uid in self.clan)
        if not present:
            membre["banni"] = uid in [x["id"] for x in self.serveur[1580:1584]]
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
    if not _session_ok():
        return _json({"erreur": "Session expirée."}, 403)
    m, q = MONDE, request.query
    quoi, fmt = q.get("quoi", ""), q.get("format", "csv")
    if quoi == "journal":
        jours = int(q.get("jours", "30") or 30)
        rows = [e for e in m.journal if MAINTENANT - e["quand"] <= jours * JOUR]
        entetes = ["Date", "Catégorie", "Type", "Gravité", "Membre", "Auteur", "Salon", "Texte", "Détail"]
        lignes = [[_quand(e["quand"]), e["cat"], e["type"], e["gravite"], m.nom(e["membre"]), m.nom(e["auteur"]), e["salon"], e["texte"], e["detail"]] for e in rows]
    elif quoi == "sanctions":
        entetes = ["N°", "Date", "Membre", "Type", "Durée", "Par", "Raison"]
        lignes = [[x["sanction"], _quand(x["date"]), m.nom(x["uid"]), m.LIB.get(x["type"], x["type"]), x["duree"],
                   "Automatique" if x["auto"] else m.nom(x["mod"]), x["raison"]] for x in m.infractions]
    elif quoi == "questions":
        entetes = ["Date", "Membre", "Salon", "Statut", "Question"]
        lignes = [[_quand(x["quand"]), m.nom(x["id"]), x["salon"], x["statut"], x["texte"]] for x in m.questions]
    elif quoi == "membre" and q.get("membre", "").isdigit():
        f = m.fiche(q["membre"])
        entetes = ["Rubrique", "Date", "Quoi", "Par", "Détail"]
        lignes = [["Sanction", _quand(s["date"]), s["libelle"], s["par"], s["raison"]] for s in f["sanctions"]]
    elif quoi == "erreurs":
        entetes = ["Date (UTC)", "Source", "Type", "Message"]
        lignes = [["2026-10-25 10:00:00", "tableau", "TimeoutError", "démonstration"]]
    else:
        return _json({"erreur": "export inconnu ou réservé"}, 404)
    nom = f"{quoi}-maquette-{datetime.now(PARIS):%Y-%m-%d}"
    if fmt == "json":
        corps, type_, nom = json.dumps([dict(zip(entetes, l)) for l in lignes], ensure_ascii=False, indent=1).encode(), "application/json", nom + ".json"
    else:
        f = io.StringIO()
        w = csv.writer(f, delimiter=";", lineterminator="\r\n")
        w.writerow(entetes)
        w.writerows(lignes)
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


async def action(request):
    if not _session_ok():
        return _json({"ok": False, "message": "Session expirée."}, 403)
    if not _origine_ok(request):
        return _json({"ok": False, "message": "Requête refusée."}, 400)
    c = await _corps(request, 4096) or {}
    m, nom = MONDE, str(c.get("action") or "")
    uid = str(c.get("membre") or "")
    if nom == "moderer":
        s = c.get("sanction")
        if s in ("warn", "mute", "kick", "ban"):
            m.infractions.insert(0, {"sanction": m.nouvel_id(), "uid": uid, "type": s, "raison": c.get("motif") or "",
                                     "duree": f"{c.get('duree')} min" if s == "mute" else "", "date": int(time.time()),
                                     "auto": False, "mod": m.moi})
        if s == "unmute":
            m.mutes.pop(uid, None)
        return _json({"ok": True, "message": {"warn": "Avertissement envoyé.", "mute": "Membre muté.", "unmute": "Mute levé.",
                                              "kick": "Membre expulsé.", "ban": "Membre banni."}.get(s, "C'est fait.")})
    if nom == "clan_retirer":
        m.clan.pop(uid, None)
        return _json({"ok": True, "message": "Rôle du clan retiré."})
    if nom == "clan_retirer_lot":
        for x in c.get("membres") or []:
            m.clan.pop(str(x), None)
        return _json({"ok": True, "message": f"{len(c.get('membres') or [])} membre(s) retiré(s) du clan."})
    if nom == "clan_ajouter":
        m.clan[uid] = {"rang": 4, "jours": "—", "derniere": "aujourd'hui", "rappel": None}
        return _json({"ok": True, "message": "Ajouté au clan."})
    if nom == "clan_prevenir":
        for x in c.get("membres") or []:
            if str(x) in m.clan:
                m.clan[str(x)]["rappel"] = {"envoye_le": int(time.time()), "echeance": int(time.time() + 7 * JOUR), "par": m.nom(m.moi),
                                            "mode": c.get("mode", "mp"), "salon": "clan-gorp", "remis": True, "statut": "en_attente",
                                            "resolu_le": None, "resolu_par": None}
        return _json({"ok": True, "message": "Membres prévenus."})
    if nom == "clan_rappel_annuler":
        if uid in m.clan:
            m.clan[uid]["rappel"] = None
        return _json({"ok": True, "message": "Rappel annulé : il reste au clan."})
    if nom == "question":
        for q in m.questions:
            if q["question"] == c.get("question"):
                q["statut"] = c.get("statut", q["statut"])
        return _json({"ok": True, "message": "Question mise à jour."})
    if nom == "ticket_fermer":
        for t in m.tickets:
            if t["ticket"] == c.get("ticket") and t["statut"] == "open":
                t["statut"], t["fin"], t["motif"] = "closed", (int(time.time()), m.moi), c.get("motif") or "Fermé depuis le site"
        return _json({"ok": True, "message": "Ticket fermé."})
    if nom == "sanction_retirer":
        m.infractions = [x for x in m.infractions if x["sanction"] != c.get("sanction")]
        return _json({"ok": True, "message": "Sanction retirée du casier."})
    if nom in ("casier_effacer", "casier_serveur", "casier_restaurer", "debannir", "alerte_geree", "fiche_retirer",
               "candidature", "sondage_retirer", "suggestion_repondre", "suggestion_retirer"):
        return _json({"ok": True, "message": "C'est fait."})
    return _json({"ok": False, "message": "Action inconnue."}, 400)


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


def _evt_listes(m):
    for e in m.evts.values():
        m._phase(e)
    brouillons = sorted([e for e in m.evts.values() if e["statut"] == "brouillon"], key=lambda e: -e["maj"])
    a_venir = sorted([e for e in m.evts.values() if e["statut"] in ("publie", "incertain", "envoi") and e["phase"] != "termine"],
                     key=lambda e: e.get("quand") or e.get("publie") or 0)
    passes = sorted([e for e in m.evts.values() if e["statut"] in ("annule", "retire") or (e["statut"] == "publie" and e["phase"] == "termine")],
                    key=lambda e: -(e.get("quand") or e.get("publie") or 0))
    return brouillons, a_venir, passes


LIMITES_TEXTE = {"evenement": 2000, "annonce": 3500, "metiers": 1500, "listing": 1500}
CHAMPS_EVT = {"id", "version", "cle_client", "type", "titre", "texte", "quand", "duree_min", "lieu", "image", "couleur", "rappels", "mention",
              "destination", "reponses", "discord_event", "reserve_clan", "places", "groupement", "champs"}


def r_evenements(m, q, c):
    brouillons, a_venir, passes = _evt_listes(m)
    return 200, {"destinations": m.destinations, "brouillons": brouillons, "a_venir": a_venir, "passes": passes[:20], "passes_total": len(passes),
                 "modeles": m.modeles, "lieux": ["Port de l'île centrale", "Taverne du clan", "Fosse des abysses", "Forteresse du centre"],
                 "rappels_suggeres": [1440, 60, 15], "couleurs": ["#a8823f", "#8e2a24", "#1f4e5a", "#3f6b3a", "#a8641c", "#5e3a4e"],
                 "defauts": dict(m.VALEURS_DEFAUT, destination="111"),
                 "limites": {"titre": 100, "texte": LIMITES_TEXTE, "lieu": 100, "rappels": 5, "rappel_max": 20160, "places": 500, "duree_max": 10080},
                 "maintenant": int(time.time()),
                 "droits": {"discord_event": True, "role_clan": "900000000000000001", "role_clan_nom": "Clan GoRP",
                            "fiches": len([a for a in m.affiches.values() if not a["retire_le"]])}}


def _verifier_champs(c, type_):
    inconnus = {k: "Champ inconnu." for k in c if k not in CHAMPS_EVT}
    if inconnus:
        return {"erreur": "Champ inconnu.", "champs": inconnus}
    err = {}
    if "titre" in c and len(str(c.get("titre") or "")) > 100:
        err["titre"] = "100 caractères au plus."
    if "texte" in c and len(str(c.get("texte") or "")) > LIMITES_TEXTE.get(type_, 2000):
        err["texte"] = f"{LIMITES_TEXTE.get(type_, 2000)} caractères au plus."
    if "duree_min" in c and not 0 <= int(c.get("duree_min") or 0) <= 10080:
        err["duree_min"] = "Entre 0 et 10 080 minutes."
    if "lieu" in c and len(str(c.get("lieu") or "")) > 100:
        err["lieu"] = "100 caractères au plus."
    if "couleur" in c and c.get("couleur") and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(c["couleur"])):
        err["couleur"] = "Couleur #RRGGBB."
    if "rappels" in c and (not isinstance(c["rappels"], list) or len(c["rappels"]) > 5 or any(not 0 <= int(x) <= 20160 for x in c["rappels"])):
        err["rappels"] = "5 rappels au plus, entre 0 et 20 160 minutes."
    if "mention" in c and c["mention"] not in ("aucune", "clan", "inscrits"):
        err["mention"] = "Mention inconnue."
    if int(c.get("places") or 0) and not c.get("reponses", True):
        err["places"] = "Les places demandent les boutons de réponse."
    if "places" in c and not 0 <= int(c.get("places") or 0) <= 500:
        err["places"] = "Entre 0 et 500."
    return {"erreur": "Champs invalides.", "champs": err} if err else None


def _trouver_evt(m, c):
    if c.get("id"):
        return m.evts.get(int(c["id"]))
    if c.get("cle_client"):
        return next((e for e in m.evts.values() if e.get("cle_client") == c["cle_client"]), None)
    return None


def _appliquer_evt(m, e, c):
    for k in ("titre", "quand", "destination"):
        if k in c:
            e[k] = c[k]
    for k, v in c.items():
        if k not in ("id", "version", "cle_client", "type", "titre", "quand", "destination"):
            e["valeurs"][k] = v
    if c.get("type") and e["statut"] == "brouillon":
        e["type"] = c["type"]
    e["maj"], e["maj_par"] = int(time.time()), m.moi
    e["version"] += 1
    m._phase(e)


def r_brouillon(m, q, c):
    e = _trouver_evt(m, c)
    type_ = c.get("type") or (e or {}).get("type") or "evenement"
    if type_ not in ("evenement", "annonce", "metiers", "listing"):
        return 400, {"erreur": "Type inconnu.", "champs": {"type": "Type inconnu."}}
    err = _verifier_champs(c, type_)
    if err:
        return 400, err
    if e is not None:
        if e["statut"] != "brouillon":
            return 409, {"erreur": "Déjà publié : modifie-le depuis « À venir ».", "publie": True}
        if c.get("id") and c.get("version") is None:
            return 400, {"erreur": "La version est obligatoire.", "champs": {"version": "Obligatoire."}}
        cle = ("brouillon", str(e["id"]))
        if cle in m.ailleurs:
            m.ailleurs.discard(cle)
            e["version"] += 1
            e["titre"] = (e.get("titre") or "") + " (modifié ailleurs)"
        if c.get("version") is not None and int(c["version"]) != e["version"]:
            return 409, {"conflit": True, "actuelle": e}
    elif c.get("id"):
        return 404, {"erreur": "Brouillon introuvable."}
    else:
        e = m._nouvel_evt(type_, "", None, {}, cle_client=c.get("cle_client"))
        e["version"] = 0
    _appliquer_evt(m, e, c)
    return 200, {"ok": True, "element": e}


def r_supprimer_brouillon(m, q, c):
    e = _trouver_evt(m, c)
    if e is None:
        return 200, {"ok": True, "deja": True}
    if e["statut"] != "brouillon":
        return 409, {"erreur": "Déjà publié.", "publie": True}
    m.evts.pop(e["id"], None)
    return 200, {"ok": True}


def _carte_evt(m, e) -> dict:
    v = e["valeurs"]
    blocs, lignes = [], []
    if e.get("titre"):
        lignes.append({"md": e["titre"], "icone": None, "niveau": 2, "jeu": None})
    for l in str(v.get("texte") or "").split("\n"):
        lignes.append({"md": l, "icone": None, "niveau": 0, "jeu": None})
    if lignes:
        blocs.append({"type": "texte", "lignes": lignes})
    if e["type"] == "evenement" and e.get("quand"):
        qd = int(e["quand"])
        l2 = [{"md": f"**Quand · When** <t:{qd}:F> (<t:{qd}:R>)", "icone": "minuteur", "niveau": 0, "jeu": None}]
        if v.get("lieu"):
            l2.append({"md": f"**Lieu · Where** {v['lieu']}", "icone": "lieu", "niveau": 0, "jeu": None})
        if v.get("duree_min"):
            l2.append({"md": f"**Durée · Duration** {v['duree_min']} min", "icone": "calendrier", "niveau": 0, "jeu": None})
        if v.get("reponses") and v.get("places"):
            l2.append({"md": f"**Places · Spots** {e['reponses']['disponibles']}/{v['places']}", "icone": "membres", "niveau": 0, "jeu": None})
        blocs += [{"type": "separateur"}, {"type": "texte", "lignes": l2}]
    if e["type"] in ("metiers", "listing"):
        grp = v.get("groupement") or "metier"
        groupes: dict = {}
        for a in m.affiches.values():
            if a["retire_le"]:
                continue
            cles = [a["grade"]] if grp == "grade" else (a["attributs"].get(grp) or ["—"])
            for k in cles:
                groupes.setdefault(k, []).append(f"<@{a['membre']['id']}>" if a["membre"].get("id") else a["roblox"]["nom"])
        l3 = []
        for k, noms in sorted(groupes.items()):
            el = m.element(grp, k)
            l3.append({"md": f"**{el['nom'] if el else k}** · {len(noms)}", "icone": None, "niveau": 3, "jeu": {"type": grp, "cle": k} if el else None})
            l3.append({"md": ", ".join(noms[:25]) + (f" et {len(noms) - 25} autres" if len(noms) > 25 else ""), "icone": None, "niveau": 0, "jeu": None})
        blocs += [{"type": "separateur"}, {"type": "texte", "lignes": l3 or [{"md": "Aucune affiche pour l'instant.", "icone": None, "niveau": "petit", "jeu": None}]}]
    if v.get("image"):
        blocs.append({"type": "image", "media": v["image"], "url": f"media/{v['image']}"})
    if e["type"] == "evenement" and v.get("reponses"):
        blocs.append({"type": "boutons", "boutons": [{"label": "Dispo · Available", "style": "success", "icone": "valider", "desactive": False, "url": None},
                                                     {"label": "Peut-être · Maybe", "style": "secondary", "icone": "peut_etre", "desactive": False, "url": None},
                                                     {"label": "Pas dispo · Unavailable", "style": "danger", "icone": "annuler", "desactive": False, "url": None}]})
    haut = "<@&900000000000000001>" if v.get("mention") == "clan" else ("Inscrits · Registered" if v.get("mention") == "inscrits" else "")
    texte = sum(len(l.get("md") or "") for b in blocs for l in b.get("lignes", []))
    return {"haut": haut, "couleur": v.get("couleur") or "#a8823f", "blocs": blocs, "composants": 3 + len(blocs), "caracteres": texte}


def r_apercu(m, q, c):
    try:
        e = m.evts.get(int(q.get("id", "0")))
    except ValueError:
        e = None
    if e is None:
        return 404, {"erreur": "Introuvable."}
    carte = _carte_evt(m, e)
    erreurs, avert = [], []
    if not e.get("titre"):
        erreurs.append("Le titre manque.")
    if e["type"] == "evenement" and not e.get("quand"):
        erreurs.append("La date manque.")
    if e["type"] == "evenement" and e.get("quand") and e["quand"] < time.time():
        avert.append("La date est déjà passée.")
    personnes = {a["membre"]["id"]: a["membre"]["nom"] for a in m.affiches.values() if a["membre"].get("id")}
    rappels = [{"minutes": mi, "quand": int(e["quand"] - mi * 60), "fait": mi in e["rappels_faits"], "passe": e["quand"] - mi * 60 < time.time()}
               for mi in (e["valeurs"].get("rappels") or [])] if e.get("quand") else []
    return 200, {"cartes": [carte], "personnes": personnes, "roles": {"900000000000000001": "Clan GoRP"}, "publiable": not erreurs, "erreurs": erreurs,
                 "avertissements": avert, "rappels": rappels,
                 "discord_event": {"demande": bool(e["valeurs"].get("discord_event")), "permission": True,
                                   "id": (e.get("discord_event") or {}).get("id"), "lien": (e.get("discord_event") or {}).get("lien")},
                 "limites": {"caracteres": 4000, "composants": 40}}


def r_publier(m, q, c):
    e = _trouver_evt(m, c)
    if e is None:
        return 404, {"erreur": "Introuvable."}
    if e["statut"] in ("publie", "envoi"):
        return 409, {"erreur": "Déjà publié."}
    if e["statut"] == "incertain" and not c.get("forcer"):
        return 409, {"erreur": "Publication incertaine : vérifie, puis force.", "incertain": True}
    if c.get("version") is not None and int(c["version"]) != e["version"]:
        return 409, {"conflit": True, "actuelle": e}
    if not e.get("titre"):
        return 400, {"erreur": "À corriger.", "erreurs": ["Le titre manque."]}
    if m.prochaine_incertaine and not c.get("forcer"):
        m.prochaine_incertaine = False
        e["statut"], e["note"] = "incertain", "Discord n'a pas confirmé l'envoi."
        return 200, {"ok": False, "incertain": True, "element": e}
    e.update({"statut": "publie", "publie": int(time.time()), "publie_par": m.moi, "lien": f"https://discord.com/channels/1/{e['destination']}/{9000 + e['id']}", "note": ""})
    if e["type"] == "evenement" and e["valeurs"].get("discord_event"):
        e["discord_event"] = {"id": "77" + str(e["id"]), "lien": "https://discord.com/events/1/77" + str(e["id"])}
    e["version"] += 1
    m._phase(e)
    return 200, {"ok": True, "lien": e["lien"], "element": e, "avertissements": []}


def r_modifier(m, q, c):
    e = m.evts.get(int(c.get("id") or 0))
    if e is None:
        return 404, {"erreur": "Introuvable."}
    if e["statut"] == "brouillon":
        return 400, {"erreur": "Encore un brouillon : utilise clan/brouillon."}
    if c.get("version") is None or int(c["version"]) != e["version"]:
        return 409, {"conflit": True, "actuelle": e}
    err = _verifier_champs(c, e["type"])
    if err:
        return 400, err
    if set(c) - {"id", "version"}:
        _appliquer_evt(m, e, c)
    else:
        e["version"] += 1
    return 200, {"ok": True, "element": e}


def r_annuler(m, q, c):
    e = m.evts.get(int(c.get("id") or 0))
    if e is None:
        return 404, {"ok": False, "erreur": "Introuvable."}
    if e["statut"] in ("annule", "retire"):
        return 200, {"ok": True, "deja": True}
    e["statut"] = "annule" if e["type"] == "evenement" else "retire"
    e["version"] += 1
    return 200, {"ok": True, "element": e}


def r_nettoyage(m, q, c):
    regles = [dict(r, defaut=r.get("defaut", r["garde_jours"]), reglable=r["cle"] not in ("ops",), auto=True) for r in m.regles]
    return 200, {"regles": regles, "dernier": m.nettoyage_dernier, "compteurs": m.nettoyage_compteurs, "bilan": m.nettoyage_bilans[0] if m.nettoyage_bilans else None,
                 "par": None, "bilans": m.nettoyage_bilans}


def r_nettoyage_regle(m, q, c):
    rg = next((x for x in m.regles if x["cle"] == c.get("cle")), None)
    if rg is None:
        return 404, {"ok": False, "erreur": "Règle inconnue."}
    j = int(c.get("garde_jours") or 0)
    if not rg["min"] <= j <= rg["max"]:
        return 400, {"ok": False, "erreur": f"Entre {rg['min']} et {rg['max']} jours."}
    rg["garde_jours"] = j
    return 200, {"ok": True, "regle": rg}


def r_nettoyage_lancer(m, q, c):
    if time.time() - m.nettoyage_dernier < 300:
        return 429, {"erreur": "Un nettoyage vient d'être fait : attends cinq minutes."}
    total = sum(m.nettoyage_compteurs.values())
    m.nettoyage_bilans.insert(0, {"quand": int(time.time()), "total": total, "detail": " · ".join(
        f"{k} {v}" for k, v in m.nettoyage_compteurs.items() if v)})
    m.nettoyage_compteurs = {k: 0 for k in m.nettoyage_compteurs}
    m.nettoyage_dernier = int(time.time())
    return 200, {"ok": True, "total": total, "message": f"{total} élément(s) nettoyé(s)."}


def r_media(m, q, c):
    try:
        octets = base64.b64decode(str(c.get("base64") or ""), validate=True)
    except ValueError:
        return 400, {"ok": False, "erreur": "Image illisible."}
    if len(octets) > 8 * 1024 * 1024:
        return 400, {"ok": False, "erreur": "8 Mo au plus."}
    magiques = (b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8")
    if not octets.startswith(magiques):
        return 400, {"ok": False, "erreur": "Formats acceptés : PNG, JPEG, WebP, GIF."}
    mid = "m" + hashlib.sha256(octets).hexdigest()[:16]
    if Image is not None:
        img = Image.open(io.BytesIO(octets))
        img.thumbnail((2048, 2048))
        f = io.BytesIO()
        img.convert("RGBA").save(f, "WEBP", quality=86)
        octets = f.getvalue()
    m.medias[mid] = (octets, "image/webp")
    return 200, {"ok": True, "id": mid, "url": f"media/{mid}"}


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


ROUTES = {
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
    r.add_route("*", ESPACE + "/api/{nom:.+}", api)
    r.add_get("/maquette/{quoi}", bascule)
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
