"""outils/banc_annees.py — le site après 1, 3 et 5 ans : est-ce qu'il tient le coup ? (26/10/2026)

« Imagine-toi que le site peut aussi tourner sur plusieurs années, voire est-ce qu'il peut tenir le coup ou pas. »

Le VRAI site local (`outils/site_local.py` : le serveur du bot, ses modules, ses routes, le faux Discord) sur une base
remplie de ce qu'un serveur comme GoRP produit en N années — `HYPOTHESES` ci-dessous, estimées d'après le code (qui
écrit quoi, à quel rythme, gardé combien de temps) et calées sur le serveur réel du 26/10/2026 (`/stats` du bot :
1 036 membres, ~120 tickets en quatre mois, la base à 0,9 % du volume). Puis la base est nettoyée comme le bot la
nettoie, avec SES fonctions (journal, grand nettoyage hebdomadaire, rétention RGPD, amnistie du casier, règles du
site), et on MESURE :
  · la base (taille, pages libres, lignes et poids par table) et les dossiers (transcripts, images, portraits) ;
  · chaque réponse du site (`donnees` surtout) : temps à froid (cache vidé) et à chaud, poids brut et compressé ;
  · la mémoire Python d'une construction de `donnees` (pic tracemalloc) ;
  · les boucles du bot qui parcourent ces tables (nettoyages, amnistie, purges, événements, activité du clan) ;
  · le démarrage (les `init_db` de chaque module sur la base remplie, comme au redémarrage du bot) ;
  · le compactage (VACUUM complet, ou incrémental si la base est en `auto_vacuum` incrémental).
Chaque taille tourne dans son propre processus (les modules gardent de l'état) ; le rapport (JSON + Markdown) les
réunit. `--servir PORT` garde la base servie pour le contrôle visuel et la mesure de la page (`outils/perf_page.mjs`).

Usage :
    python outils/banc_annees.py --annees 1,3,5 --sortie C:/chemin/banc        → rapport.json et rapport.md
    python outils/banc_annees.py --annees 5 --servir 8809                       → la base « 5 ans », servie
    python outils/banc_annees.py --annees 1 --sans-fichiers --rapide            → plus court (tests)
Rien ne part chez Discord ni chez Roblox. Les membres, textes et fichiers sont inventés (octets au hasard pour les
images : leur poids compte, pas leur contenu).
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
for _chemin in (RACINE, RACINE / "outils", RACINE / "tests"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

JOUR = 86400
SERVEUR_ID = 1
FONDATEUR, DIRECTION, STAFF_ID, BOT_ID = 781205382923288593, 827633340797681714, 1010, 999

# ═══════════════════════════════════════════════════════════════════════════════
#  Les hypothèses (par jour et pour 1 000 membres, sauf mention) — d'où elles viennent
# ═══════════════════════════════════════════════════════════════════════════════
HYPOTHESES = {
    "membres": 1036,          # /stats du bot, 26/10/2026 (accueil.membres)
    "croissance": 1.5,        # par an — pessimiste : un serveur qui grandit vite (×7,6 en 5 ans)
    "partis": 0.30,           # gens cités qui ont quitté le serveur (davantage dans les vieux évènements)
    "clan": 0.06,             # part des membres au clan Rell Seas (60 au moins)
    #  Le journal (`registre.noter`) : unified_logger (messages supprimés/modifiés, vocal, arrivées, rôles…),
    #  modération, sécurité, tickets, questions, entraide, clan, configuration, cadeaux, annonces.
    "journal": {"Messages": 140, "Vocal": 220, "Membres": 45, "Modération": 8, "Sécurité": 12, "Tickets": 6,
                "Questions": 10, "Entraide": 10, "Clan": 6, "Config": 2, "Annonces": 1, "Cadeaux": 2, "Suggestions": 1},
    "journal_fixe": {"Site": 25, "Accès": 4},   # par jour : la direction sur le site (sans lien avec le nombre de membres)
    "tickets": 1.5,           # ouverts — le serveur réel : ~120 tickets en quatre mois pour ~1 000 membres
    "tickets_clan": 0.30,     # part du recrutement Rell Seas (p1) ; 75 % reçoivent une décision
    "transcript_messages": (4, 60),   # messages d'un ticket (2 % : un long ticket de 150 à 400 messages)
    "transcript_images": 0.30,        # tickets avec 1 à 3 images ré-hébergées (~250 Ko chacune)
    "sanctions": 2.5,         # du staff (avertissements, mutes, expulsions, bans)
    "detections": 5.0,        # automatiques (insultes, filtre, menaces…)
    "questions": 15, "sondages": 0.3, "idees": 0.2, "entraide": 8,
    "annonces_logs": 0.15,    # par jour (annonces du salon des logs) ; « Vu » : 25 % des membres
    "evenements": 0.25, "annonces_clan": 0.15,   # par jour (le clan) ; réponses : 40 % du clan
    "affiches": 0.70,         # du clan a son affiche ; 3 modifications par jour
    "clan_depart_an": 0.35,   # part du clan qui le quitte chaque année (27/10/2026 : vitrine et équipes)
    "affiches_partis_retirees": 0.5,   # affiches de ceux qui ont quitté le clan que la direction retire (les autres restent)
    "equipe_taille": (3, 9),  # membres d'une équipe, en plus de son chef ; une équipe pour huit membres du clan
    "vitrine": "tous les blocs de l'accueil publics (le pire cas : événements, analyses, actualités)",
    "portraits": 1.0,         # recherches Roblox par jour (le portrait est gardé, même sans affiche)
    "medias": 0.5,            # images envoyées par jour (~150 Ko) ; 55 % utilisées (annonces, accueil)
    "actualites": 0.25,       # actualités de l'équipage par jour (40 % avec image)
    "activite": 0.30,         # membres actifs chaque jour (`activite_jours`)
    "arrivees": 12, "audit_staff": 6, "securite": 5,
}

PRENOMS = ("Kolax", "Mira", "Barbe", "Anne", "Calico", "Morgane", "Ishmael", "Tortuga", "Rackham", "Salazar", "Hector",
           "Jade", "Corsaire", "Nemo", "Lysandre", "Océane", "Bastien", "Elio", "Zéphyr", "Ylva", "Tobias", "Maëlle",
           "Rosalind", "Silas", "Gaspard", "Louna", "Ravel", "Iris", "Malo", "Sacha")
SURNOMS = ("le Rouge", "Main-de-Fer", "des Abysses", "la Brune", "Bois-Flotté", "l'Écumeur", "Sans-Peur", "du Levant",
           "la Vigie", "Grand-Mât", "Barbe-Sel", "le Taciturne", "Œil-de-Lynx", "la Tempête", "des Récifs")
PHRASES = ("la réunion est déplacée à demain soir, prévenez les autres", "quelqu'un pour farmer le boss des abysses ?",
           "merci pour l'aide de tout à l'heure", "je vends un fruit rare contre des berrys", "on se retrouve au port",
           "le serveur a crash pendant le raid", "qui a la carte du trésor ?", "gg à tout l'équipage pour ce soir",
           "est-ce que le Movie 3 change les factions ?", "je reviens dans dix minutes")
MOTIFS = ("Spam dans le salon", "Insulte envers un membre", "Lien interdit", "Pub pour un autre serveur", "Hors sujet répété",
          "Flood de mentions", "Contournement d'un mute", "Langage inapproprié en vocal", "Arnaque au trade", "Image interdite")


def _sqlite(t: float) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _jour(t: float) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).strftime("%Y-%m-%d")


def _n(v) -> str:
    return f"{int(v or 0):,}".replace(",", " ")


def _mo(octets) -> str:
    return f"{(octets or 0) / 1048576:.1f}".replace(".", ",") + " Mo"


# ═══════════════════════════════════════════════════════════════════════════════
#  La population : qui est là, qui est parti, au fil des années
# ═══════════════════════════════════════════════════════════════════════════════

class Monde:
    """Les membres (présents dans le faux serveur, partis hors de lui), leur nombre au fil du temps, le hasard."""

    def __init__(self, annees: float, ctx, h: dict = HYPOTHESES, graine: int = 26102026):
        self.annees, self.h, self.ctx = annees, h, ctx
        self.g = ctx.guild
        self.hasard = random.Random(graine + int(annees * 100))
        self.maintenant = time.time()
        self.jours = int(round(annees * 365))
        self.membres_fin = max(30, int(round(h["membres"] * h["croissance"] ** annees)))
        self.presents: list = []
        self.partis = [90_000_000 + k for k in range(int(self.membres_fin * h["partis"] / (1 - h["partis"])) + 1)]
        self.staff = [FONDATEUR, DIRECTION, STAFF_ID]

    def membres(self, d: float) -> float:
        """Le nombre de membres il y a `d` jours."""
        return self.h["membres"] * self.h["croissance"] ** max(0.0, self.annees - d / 365)

    def combien(self, par_mille: float, d: float, fixe: bool = False) -> int:
        """Le nombre d'évènements d'un jour : `par_mille` pour 1 000 membres (ou par jour si `fixe`), arrondi au hasard."""
        x = par_mille if fixe else par_mille * self.membres(d) / 1000
        n = int(x)
        return n + (1 if self.hasard.random() < x - n else 0)

    def qui(self, d: float = 0) -> int:
        """Une personne citée par un évènement d'il y a `d` jours : quelques-uns très souvent (loi de puissance), et
        davantage de partis dans les vieux évènements."""
        part_partis = 0.10 + 0.40 * min(1.0, d / max(1, self.jours))
        liste = self.partis if self.hasard.random() < part_partis else self.presents
        return liste[int(len(liste) * self.hasard.random() ** 2.2)]

    def quand(self, d: float) -> int:
        return int(self.maintenant - d * JOUR - self.hasard.random() * JOUR)


async def peupler(monde: Monde) -> None:
    """Les membres du faux serveur jusqu'au nombre de la dernière année (le clan : 6 %, 60 au moins), et l'équipe."""
    g, conf = monde.ctx.guild, monde.ctx.conf
    import rellseas_panneau
    clan = g.get_role(int(conf[rellseas_panneau.CLE_ROLE_CIBLE]))
    staff = next(r for r in g.roles if r.name == "Staff")
    deja = [m for m in g.members if m.id not in (FONDATEUR, DIRECTION) and not getattr(m, "bot", False)]
    a_ajouter = max(0, monde.membres_fin - len(deja))
    besoin = max(0, max(60, int(monde.membres_fin * monde.h["clan"])) - sum(1 for m in deja if clan in m.roles))
    au_clan = set(monde.hasard.sample(range(a_ajouter), min(besoin, a_ajouter)))
    for k in range(a_ajouter):
        nom = f"{PRENOMS[k % len(PRENOMS)]} {SURNOMS[(k // len(PRENOMS)) % len(SURNOMS)]}" + (f" {k // 450}" if k >= 450 else "")
        roles = [clan] if k in au_clan else []
        if k < 5:
            roles.append(staff)
        m = g.membre(10_000_000 + k, nom, *roles, arrivee_jours=monde.hasard.randint(1, max(2, monde.jours + 30)))
        if k < 5:
            monde.staff.append(m.id)
    monde.presents = [m.id for m in g.members if m.id not in (FONDATEUR, DIRECTION) and not getattr(m, "bot", False)]
    monde.hasard.shuffle(monde.presents)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le remplissage (une transaction, sqlite3 direct : des centaines de milliers de lignes en quelques secondes)
# ═══════════════════════════════════════════════════════════════════════════════

class Base:
    def __init__(self, chemin: Path):
        self.c = sqlite3.connect(chemin, timeout=60)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("PRAGMA synchronous=OFF")
        self.colonnes: dict = {}
        self.compte: dict = {}

    def cols(self, table: str) -> list:
        if table not in self.colonnes:
            self.colonnes[table] = [r[1] for r in self.c.execute(f"PRAGMA table_info({table})")]
        return self.colonnes[table]

    def ajouter(self, table: str, lignes: list, ou: str = "INSERT") -> None:
        if not lignes:
            return
        noms = list(lignes[0].keys())
        manque = [n for n in noms if n not in self.cols(table)]
        if manque:
            raise RuntimeError(f"{table} : colonnes inconnues {manque}")
        self.c.executemany(f"{ou} INTO {table} ({', '.join(noms)}) VALUES ({', '.join('?' * len(noms))})",
                           [tuple(x[n] for n in noms) for x in lignes])
        self.compte[table] = self.compte.get(table, 0) + len(lignes)

    def un(self, sql, args=()):
        return self.c.execute(sql, args).fetchone()

    def fin(self):
        self.c.commit()
        self.c.close()


def _tables_du_bot(b: Base) -> None:
    """Les tables que bot.py (ou un module que le site local ne branche pas) crée, avec leurs index — et les colonnes de
    `ticket_transcripts` que le site local n'a pas (`user_id`, `panel`, `jeton`)."""
    for sql in (
            "CREATE TABLE IF NOT EXISTS activite_jours(guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, jour TEXT NOT NULL,"
            " sources TEXT NOT NULL DEFAULT '', PRIMARY KEY(guild_id, user_id, jour))",
            "CREATE INDEX IF NOT EXISTS idx_activite_jours_guild_jour ON activite_jours(guild_id, jour)",
            "CREATE TABLE IF NOT EXISTS activite_etat(guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, dernier_actif TEXT,"
            " palier INTEGER NOT NULL DEFAULT 0, roles_retires TEXT NOT NULL DEFAULT '[]', derniere_alerte TEXT,"
            " PRIMARY KEY(guild_id, user_id))",
            "CREATE TABLE IF NOT EXISTS invitations_arrivees (guild_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
            " auteur_id INTEGER NOT NULL, code TEXT NOT NULL, arrive INTEGER NOT NULL, compte_cree INTEGER NOT NULL,"
            " parti INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, membre_id))",
            "CREATE INDEX IF NOT EXISTS idx_invitations_auteur ON invitations_arrivees(guild_id, auteur_id)",
            "CREATE TABLE IF NOT EXISTS staff_audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, actor_id INTEGER,"
            " target_id INTEGER, action TEXT, detail TEXT, surface TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "CREATE INDEX IF NOT EXISTS idx_staff_audit_guild_id ON staff_audit_log(guild_id, id DESC)",
            "CREATE TABLE IF NOT EXISTS user_fingerprints (guild_id INTEGER, user_id INTEGER, avatar_hash TEXT,"
            " username_normalized TEXT, created_at_ts INTEGER, joined_at_ts INTEGER, first_message_at DATETIME,"
            " first_message_channel INTEGER, behavior_hash TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
            " PRIMARY KEY (guild_id, user_id))",
            "CREATE TABLE IF NOT EXISTS daily_join_log (guild_id INTEGER, user_id INTEGER, joined_day TEXT, left_day TEXT,"
            " PRIMARY KEY (guild_id, user_id, joined_day))",
            "CREATE TABLE IF NOT EXISTS security_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,"
            " action TEXT, details TEXT, ip_hash TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE IF NOT EXISTS ticket_extras (channel_id INTEGER PRIMARY KEY, priority TEXT DEFAULT 'normal',"
            " last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP, closed_at DATETIME, claimed_at DATETIME)",
            "CREATE INDEX IF NOT EXISTS idx_ticket_extras_activity ON ticket_extras(last_activity_at)",
            "CREATE TABLE IF NOT EXISTS ticket_log_msgs (guild_id INTEGER, ticket_id INTEGER, message_id INTEGER,"
            " PRIMARY KEY (guild_id, ticket_id))",
            #  Les publications des réseaux (`publications.py`, que le site local ne branche pas) : le grand nettoyage
            #  les purge chaque semaine — sans elles, chaque passage écrivait une erreur de table absente.
            "CREATE TABLE IF NOT EXISTS publications (guild_id INTEGER NOT NULL, plateforme TEXT NOT NULL,"
            " post_id TEXT NOT NULL, reserve_le INTEGER NOT NULL, instance TEXT DEFAULT '', chemin TEXT DEFAULT '',"
            " message_id INTEGER DEFAULT 0, salon_id INTEGER DEFAULT 0, PRIMARY KEY (guild_id, plateforme, post_id))",
            #  Les index que bot.py pose sur les tables partagées (db_init, on_ready, tickets_enhance, error_logger).
            "CREATE INDEX IF NOT EXISTS idx_tickets_channel_status ON tickets(channel_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_tle ON ticket_log_events(guild_id, ticket_id)",
            "CREATE INDEX IF NOT EXISTS idx_ticket_audit_ch ON ticket_audit(channel_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_infractions_guild_user ON infractions(guild_id, user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_error_log_guild_recent ON error_log(guild_id, occurred_at DESC)"):
        b.c.execute(sql)
    for col, typ in (("user_id", "INTEGER"), ("panel", "TEXT"), ("jeton", "TEXT")):
        if col not in b.cols("ticket_transcripts"):
            b.c.execute(f"ALTER TABLE ticket_transcripts ADD COLUMN {col} {typ}")
            b.colonnes.pop("ticket_transcripts", None)
    b.c.execute("CREATE INDEX IF NOT EXISTS idx_ticket_transcripts_user ON ticket_transcripts(guild_id, user_id)")


def _octets_image(hasard, taille: int, webp: bool = True) -> bytes:
    """Des octets d'image (en-tête juste, contenu au hasard) : leur poids compte, pas leur contenu."""
    entete = b"RIFF" + (taille - 8).to_bytes(4, "little") + b"WEBPVP8 " if webp else b"\x89PNG\r\n\x1a\n"
    return entete + hasard.randbytes(max(0, taille - len(entete)))


def _transcript_html(monde: Monde, tid: int, auteur: str, debut: int, n: int, images: list) -> str:
    """Un transcript dans la forme de bot.py (`_render_ticket_transcript_html`) — ce que `transcript_store` relit."""
    h = monde.hasard
    lignes = []
    for k in range(n):
        qui = auteur if k % 2 else h.choice(("GoRP Bot", "Hector", "Capitaine Direction"))
        texte = " ".join(h.choice(PHRASES) for _ in range(h.randint(1, 4)))
        att = "".join(f'<img class="att" loading="lazy" src="{u}" alt="image">' for u in (images if k == 1 else []))
        lignes.append(f'<div class="msg" data-t="{debut + k * 90}"><img class="avatar" loading="lazy" '
                      f'src="https://cdn.discordapp.com/embed/avatars/{k % 6}.png" alt=""><div class="mbody"><div class="mhead">'
                      f'<span class="author">{qui}</span><span class="ts">{datetime.fromtimestamp(debut + k * 90, timezone.utc):%d/%m/%Y %H:%M}'
                      f'</span></div><div class="content">{texte}</div>{att}</div></div>')
    css = "body{background:#313338;color:#dbdee1;font-family:sans-serif}" * 40   # la feuille du bot (~5 Ko)
    return ("<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'><title>Ticket #" + str(tid) + "</title><style>"
            + css + "</style></head><body><div class='header'><h1>Ticket #" + str(tid) + "</h1><div class='sub'>" + str(n)
            + " message(s)</div></div><div class='chat'>" + "".join(lignes) + "</div></body></html>")


def remplir(monde: Monde, fichiers: bool = True) -> dict:
    """Toutes les familles de données, sur la fenêtre que leur rétention garderait (plus une marge que le premier
    nettoyage retire) — et sur TOUTES les années pour ce qui n'a pas de rétention. Rend le nombre de lignes par table."""
    import transcript_store
    import tableau
    h, hasard, now = monde.h, monde.hasard, monde.maintenant
    b = Base(monde.ctx.dossier / "site_local.db")
    _tables_du_bot(b)
    jours = monde.jours
    salons = [s.id for s in monde.g.salons.values()] or [1]

    # ─── Le journal (registre) : messages et vocal 32 jours, le reste 92 (la purge garde 30 / 90, au plus 100 000) ──
    gabarits = {
        "Messages": (("msg.delete", "Message supprimé de {n} dans #chat"), ("msg.edit", "Message modifié par {n}")),
        "Vocal": (("voice.join", "Vocal : {n} rejoint « Taverne »"), ("voice.leave", "Vocal : {n} quitte « Taverne »"),
                  ("voice.move", "Vocal : {n} passe dans « Raid »")),
        "Membres": (("member.join", "Arrivée : {n}"), ("member.leave", "Départ : {n}"), ("member.update", "Rôles de {n} modifiés")),
        "Modération": (("mod.warn", "Avertissement : {n}"), ("mod.mute", "Mute : {n} (1 h)"), ("mod.kick", "Expulsion : {n}")),
        "Sécurité": (("sec.spam", "Spam bloqué : {n}"), ("sec.link", "Lien supprimé : {n}"), ("sec.scam", "Lien d'arnaque supprimé : {n}")),
        "Tickets": (("ticket.open", "Ticket ouvert par {n}"), ("ticket.close", "Ticket de {n} fermé")),
        "Questions": (("question.ouverte", "Question relevée : {n}"),), "Entraide": (("entraide.ouverte", "Demande d'entraide de {n}"),),
        "Clan": (("clan.journal", "Rôle du clan donné à {n}"),), "Config": (("config.change", "Réglage modifié par {n}"),),
        "Annonces": (("annonce.publiee", "Annonce publiée par {n}"),), "Cadeaux": (("cadeaux.inscrit", "{n} inscrit au cadeau"),),
        "Suggestions": (("suggestion.ouverte", "Idée proposée par {n}"),),
        "Site": (("site.rell.affiche", "Affiche modifiée (par {n})"), ("site.ouvert", "Site ouvert par {n}")),
        "Accès": (("site.ouvert", "Site ouvert par {n}"),)}
    noms = {m.id: m.display_name for m in monde.g.members}
    lignes = []
    for cat in list(h["journal"]) + list(h["journal_fixe"]):
        fixe = cat in h["journal_fixe"]
        fenetre = min(jours, 32 if cat in ("Messages", "Vocal") else 92)
        for d in range(fenetre):
            for _ in range(monde.combien(h["journal_fixe"][cat] if fixe else h["journal"][cat], d, fixe)):
                typ, texte = hasard.choice(gabarits[cat])
                uid = hasard.choice(monde.staff[:2]) if fixe else monde.qui(d)
                detail = (" · ".join(hasard.choice(PHRASES) for _ in range(hasard.randint(1, 5))) if cat == "Messages"
                          else hasard.choice(("", "", "Motif : " + hasard.choice(MOTIFS))))
                lignes.append({"guild_id": SERVEUR_ID, "quand": monde.quand(d), "categorie": cat, "type": typ,
                               "membre_id": 0 if fixe else uid, "auteur_id": uid if fixe or cat == "Modération" else 0,
                               "salon_id": hasard.choice(salons), "texte": texte.format(n=noms.get(uid, "Membre parti")),
                               "detail": detail[:600], "gravite": 2 if typ in ("mod.mute", "sec.scam") else 1 if cat == "Modération" else 0})
    lignes.sort(key=lambda x: x["quand"])
    b.ajouter("registre", lignes)

    # ─── Les tickets (365 jours), leur suivi, leur audit, leurs transcripts (fichiers : 120 jours) ──
    tid, tickets, evts, audit, transcripts, extras, p1_decides = 100_000, [], [], [], [], [], []
    dossier_tr = Path(transcript_store._BASE_DIR)
    dossier_tr.mkdir(parents=True, exist_ok=True)
    octets_tr = 0
    for d in range(min(jours, 367), -1, -1):
        for _ in range(monde.combien(h["tickets"], d)):
            tid += 1
            uid = monde.qui(d)
            ouvert = monde.quand(d)
            clan = hasard.random() < h["tickets_clan"]
            panneau = "p1" if clan else hasard.choice(("p2", "p2", "p3"))
            encore = d <= 1 and hasard.random() < 0.6
            pris = hasard.choice(monde.staff) if hasard.random() < 0.9 else 0
            fin = ouvert + hasard.randint(1800, 5 * JOUR)
            if encore or fin > now:
                encore, fin = True, 0
            reponses = {"Pseudo Roblox": f"Pirate_{uid % 100000}", "Niveau": str(hasard.randint(5, 90)),
                        "Pourquoi nous ?": hasard.choice(PHRASES)} if clan else {}
            tickets.append({"id": tid, "guild_id": SERVEUR_ID, "channel_id": 7_000_000 + tid, "user_id": uid, "panel_id": panneau,
                            "claimed_by": pris, "status": "open" if encore else "closed", "answers": json.dumps(reponses),
                            "created_at": _sqlite(ouvert)})
            evts.append({"guild_id": SERVEUR_ID, "ticket_id": tid, "kind": "open", "actor_id": uid, "detail": "", "created_unix": ouvert})
            if pris:
                evts.append({"guild_id": SERVEUR_ID, "ticket_id": tid, "kind": "claim", "actor_id": pris, "detail": "",
                             "created_unix": ouvert + hasard.randint(60, 20000)})
                audit.append({"guild_id": SERVEUR_ID, "channel_id": 7_000_000 + tid, "action": "claim", "actor_id": pris,
                              "at": _sqlite(ouvert + 600), "detail": ""})
            for _ in range(hasard.randint(0, 2)):
                evts.append({"guild_id": SERVEUR_ID, "ticket_id": tid, "kind": hasard.choice(("add", "rename", "note")),
                             "actor_id": pris or uid, "detail": hasard.choice(PHRASES), "created_unix": ouvert + 900})
            extras.append({"channel_id": 7_000_000 + tid, "priority": "normal", "last_activity_at": _sqlite(fin or ouvert),
                           "closed_at": _sqlite(fin) if fin else None, "claimed_at": _sqlite(ouvert + 600) if pris else None})
            if encore:
                continue
            motif = hasard.choice(("Résolu", "Problème réglé en vocal", "Sans réponse du membre", "Doublon",
                                   "Signalement traité : sanction", "Candidature acceptée", "Candidature refusée"))
            qui_ferme = pris or hasard.choice(monde.staff)
            evts.append({"guild_id": SERVEUR_ID, "ticket_id": tid, "kind": "close", "actor_id": qui_ferme, "detail": motif, "created_unix": fin})
            audit.append({"guild_id": SERVEUR_ID, "channel_id": 7_000_000 + tid, "action": "close", "actor_id": qui_ferme,
                          "at": _sqlite(fin), "detail": motif})
            if clan and hasard.random() < 0.75:
                p1_decides.append((tid, uid, ouvert, fin, pris, qui_ferme, reponses))
            if now - fin <= 125 * JOUR:     # les transcripts : 120 jours (data_cleanup, transcript_store)
                jeton = "".join(hasard.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-") for _ in range(22))
                transcripts.append({"guild_id": SERVEUR_ID, "ticket_id": tid, "user_id": uid, "user_name": noms.get(uid, "Membre parti"),
                                    "panel": panneau, "url": f"http://localhost/t/{jeton}", "closed_at": _iso(fin), "jeton": jeton})
                if fichiers:
                    n = hasard.randint(150, 400) if hasard.random() < 0.02 else hasard.randint(*h["transcript_messages"])
                    images = []
                    if hasard.random() < h["transcript_images"]:
                        dossier_a = dossier_tr / f"a_{jeton}"
                        dossier_a.mkdir(exist_ok=True)
                        for k in range(hasard.randint(1, 3)):
                            data = _octets_image(hasard, hasard.randint(120_000, 400_000), webp=False)
                            (dossier_a / f"{k}.png").write_bytes(data)
                            octets_tr += len(data)
                            images.append(f"/ta/{jeton}/{k}")
                        os.utime(dossier_a, (fin, fin))
                    html = _transcript_html(monde, tid, noms.get(uid, "Membre parti"), fin - n * 90, n, images)
                    p = dossier_tr / f"{jeton}.html"
                    p.write_text(html, encoding="utf-8")
                    os.utime(p, (fin, fin))
                    octets_tr += len(html.encode())
    b.ajouter("tickets", tickets)
    b.ajouter("ticket_log_events", evts)
    b.ajouter("ticket_audit", audit)
    b.ajouter("ticket_transcripts", transcripts)
    b.ajouter("ticket_extras", extras, "INSERT OR REPLACE")

    # ─── Les candidatures décidées (365 jours, RGPD) et le questionnaire de l'étape 2 ──
    modele = b.un("SELECT questions FROM recrutement_envois ORDER BY id LIMIT 1")
    questions_json = modele[0] if modele else json.dumps([{"rang": k, "question": "Question ?" * 8, "reponse": "Réponse"} for k in range(10)])
    rec, envois, rep, corr, hist, suivi = [], [], [], [], [], []
    for tid_, uid, ouvert, fin, pris, ferme_par, reponses in p1_decides:
        accepte = hasard.random() < 0.55
        rec.append({"guild_id": SERVEUR_ID, "ticket_id": tid_, "candidat_id": uid, "candidat_nom": noms.get(uid, f"Candidat {uid}"),
                    "ouvert_le": ouvert, "ferme_le": fin, "ferme_par": ferme_par, "pris_par": pris,
                    "reponses": json.dumps({**reponses, **{f"Question {k}": hasard.choice(PHRASES) * hasard.randint(1, 3)
                                                           for k in range(hasard.randint(3, 7))}}, ensure_ascii=False),
                    "msg_candidat": hasard.randint(2, 30), "msg_staff": hasard.randint(1, 20), "transcript": "",
                    "raison": "" if accepte else hasard.choice(("Niveau insuffisant", "Réponses trop vagues", "N'a pas répondu")),
                    "decision": "acceptes" if accepte else "refuses"})
        if hasard.random() < 0.5:
            envoi = len(envois) + 1000
            envois.append({"id": envoi, "guild_id": SERVEUR_ID, "ticket_id": tid_, "candidat_id": uid, "questions": questions_json,
                           "statut": "repondu", "envoye_par": ferme_par, "cree_le": ouvert + 3600, "envoye_le": ouvert + 3600,
                           "repondu_le": ouvert + 7200})
            for r in range(10):
                rep.append({"envoi_id": envoi, "rang": r, "guild_id": SERVEUR_ID, "candidat_id": uid,
                            "texte": hasard.choice(PHRASES), "recu_le": ouvert + 7200})
                corr.append({"envoi_id": envoi, "rang": r, "juste": hasard.randint(0, 1), "par": ferme_par, "le": fin - 600})
            for quoi in ("etape1", "envoye", "repondu", "decide"):
                hist.append({"guild_id": SERVEUR_ID, "ticket_id": tid_, "quand": fin - 3000, "quoi": quoi, "par": ferme_par, "detail": ""})
            suivi.append({"guild_id": SERVEUR_ID, "ticket_id": tid_, "candidat_id": uid, "etape": "accepte" if accepte else "refuse",
                          "envoi_id": envoi, "decide_par": ferme_par, "decide_le": fin, "cree_le": ouvert, "maj_le": fin})
    b.ajouter("recrutements", rec, "INSERT OR REPLACE")
    b.ajouter("recrutement_envois", envois)
    b.ajouter("recrutement_reponses", rep)
    b.ajouter("recrutement_corrections", corr)
    b.ajouter("recrutement_historique", hist)
    b.ajouter("recrutement_suivi", suivi, "INSERT OR REPLACE")

    # ─── Le casier : sanctions et détections (730 jours au plus) — l'amnistie fera le tri, comme chaque jour ──
    inf = []
    for d in range(min(jours, 735), -1, -1):
        for _ in range(monde.combien(h["sanctions"], d)):
            typ = hasard.choices(("warn", "mute", "kick", "ban"), (60, 28, 8, 4))[0]
            inf.append({"guild_id": SERVEUR_ID, "user_id": monde.qui(d), "mod_id": hasard.choice(monde.staff), "type": typ,
                        "reason": hasard.choice(MOTIFS), "duration": hasard.choice(("1 heure", "6 heures", "1 jour")) if typ == "mute" else "",
                        "created_at": _sqlite(monde.quand(d))})
        for _ in range(monde.combien(h["detections"], d)):
            typ = hasard.choices(("insulte", "protection", "menace", "discrimination", "harcelement", "haine"), (50, 30, 5, 5, 5, 5))[0]
            inf.append({"guild_id": SERVEUR_ID, "user_id": monde.qui(d), "mod_id": BOT_ID, "type": typ,
                        "reason": hasard.choice(MOTIFS), "duration": "", "created_at": _sqlite(monde.quand(d))})
    b.ajouter("infractions", inf)

    # ─── Questions (30 j), sondages (90 j), idées et votes (toutes les années), entraide (toutes les années) ──
    qs = []
    for d in range(min(jours, 32)):
        for _ in range(monde.combien(h["questions"], d)):
            statut = hasard.choice(("ouverte", "repondue", "repondue", "resolue", "traitee", "ignoree"))
            q = monde.quand(d)
            qs.append({"guild_id": SERVEUR_ID, "salon_id": hasard.choice(salons), "message_id": 50_000_000 + len(qs) + d * 1000,
                       "auteur_id": monde.qui(d), "texte": hasard.choice(PHRASES).capitalize() + " ?", "quand": q, "statut": statut,
                       "repondu_par": hasard.choice(monde.staff) if statut in ("repondue", "resolue") else 0,
                       "repondu_le": q + 1800 if statut in ("repondue", "resolue") else 0, "par_staff": int(statut == "repondue"),
                       "lien": f"https://discord.com/channels/{SERVEUR_ID}/1/{50_000_000 + len(qs)}"})
    b.ajouter("questions", qs, "INSERT OR IGNORE")
    so = []
    for d in range(min(jours, 92)):
        for _ in range(monde.combien(h["sondages"], d)):
            c = monde.quand(d)
            so.append({"message_id": 60_000_000 + len(so), "guild_id": SERVEUR_ID, "channel_id": hasard.choice(salons),
                       "auteur_id": monde.qui(d), "question": "Quel soir pour le raid ?", "choix": json.dumps(["Vendredi", "Samedi", "Dimanche"]),
                       "cree_le": _sqlite(c), "fin_le": _sqlite(c + JOUR), "termine": int(d > 1),
                       "comptes": json.dumps([hasard.randint(0, 40) for _ in range(3)]), "total": hasard.randint(0, 120)})
    b.ajouter("sondages", so)
    idees, votes = [], []
    for d in range(jours, -1, -1):
        for _ in range(monde.combien(h["idees"], d)):
            sid = 70_000 + len(idees)
            idees.append({"id": sid, "guild_id": SERVEUR_ID, "channel_id": hasard.choice(salons), "message_id": 70_000_000 + sid,
                          "auteur_id": monde.qui(d), "titre": "Idée : " + hasard.choice(PHRASES), "details": hasard.choice(PHRASES) * 2,
                          "statut": hasard.choice(("attente", "etude", "acceptee", "refusee", "realisee")), "cree_le": _sqlite(monde.quand(d))})
            for u in set(monde.qui(d) for _ in range(8 + int(10 * monde.membres(d) / 1000))):
                votes.append({"suggestion_id": sid, "user_id": u, "vote": hasard.choice((1, 1, -1))})
    b.ajouter("suggestions_v2", idees)
    b.ajouter("suggestions_votes", votes, "INSERT OR IGNORE")
    ent = []
    for d in range(jours, -1, -1):
        for _ in range(monde.combien(h["entraide"], d)):
            c = monde.quand(d)
            ent.append({"guild_id": SERVEUR_ID, "zone": hasard.choice(("aide", "boss", "farm", "trade", "cl_trade", "cl_aide")),
                        "auteur_id": monde.qui(d), "titre": hasard.choice(PHRASES).capitalize(),
                        "champs": json.dumps([["Objet", hasard.choice(PHRASES)], ["Niveau", str(hasard.randint(1, 90))],
                                              ["Détails", hasard.choice(PHRASES) * 2]], ensure_ascii=False),
                        "statut": "ouverte" if d < 1 else hasard.choice(("terminee", "fermee", "expiree")), "salon_id": hasard.choice(salons),
                        "fil_id": 80_000_000 + len(ent), "aidants": json.dumps([monde.qui(d) for _ in range(hasard.randint(0, 3))]),
                        "cree": c, "maj": c + 3600, "ferme": 0 if d < 1 else c + 7200, "ferme_par": 0 if d < 1 else monde.qui(d),
                        #  close : son fil est retiré de Discord au passage suivant (`entraide.GARDER_H` = 0) ; un échange
                        #  sur cinq est certifié par un middleman (il fait la réputation).
                        "supprime": int(d >= 1), "certifie_par": monde.qui(d) if d >= 1 and hasard.random() < 0.2 else 0})
    b.ajouter("entraide_demandes", ent)

    # ─── Les annonces du salon des logs et leurs « Vu » (toutes les années : rien ne les efface) ──
    an, vues = [], []
    for d in range(jours, -1, -1):
        for _ in range(monde.combien(h["annonces_logs"], d, fixe=True)):
            aid = 90_000 + len(an)
            c = monde.quand(d)
            an.append({"id": aid, "guild_id": SERVEUR_ID, "salon_id": hasard.choice(salons), "message_id": 90_000_000 + aid, "fil_id": 0,
                       "auteur_id": FONDATEUR, "titre": "Annonce : " + hasard.choice(PHRASES), "texte": hasard.choice(PHRASES) * 4,
                       "mention": hasard.choice(("", "@everyone")), "cree": c})
            for u in set(monde.qui(d) for _ in range(int(monde.membres(d) * 0.25))):
                vues.append({"annonce_id": aid, "membre_id": u, "quand": c + hasard.randint(60, 3 * JOUR)})
    b.ajouter("annonces", an)
    b.ajouter("annonces_vues", vues, "INSERT OR IGNORE")

    # ─── Les annonces et événements du clan : copies des lignes de démonstration (le format du module) ──
    modeles = {}
    for r in b.c.execute("SELECT * FROM clan_evenements"):
        ligne = dict(zip(b.cols("clan_evenements"), r))
        modeles.setdefault((ligne["type"], ligne["statut"]), ligne)
    clan_ids = [m.id for m in monde.g.members if any(getattr(r, "name", "") == "Rell Seas" for r in m.roles)]
    evs, reps = [], []
    nid = 100_000
    for d in range(jours, -1, -1):
        for genre in ("evenement", "annonce"):
            for _ in range(monde.combien(h["evenements"] if genre == "evenement" else h["annonces_clan"], d, fixe=True)):
                if genre == "evenement" and d > 62:
                    continue          # les événements passés : la règle du site les efface après 60 jours
                m = modeles.get((genre, "publie")) or next(iter(modeles.values()), None)
                if m is None:
                    break
                nid += 1
                c = monde.quand(d)
                donnees = json.loads(m["donnees"] or "{}")
                donnees["titre"] = (donnees.get("titre") or "Titre")[:40] + f" n°{nid}"
                if genre == "evenement":
                    donnees["quand"] = c + 2 * JOUR
                fini = genre == "evenement" and c + 2 * JOUR + 7200 < now
                evs.append(dict(m, id=nid, cle_client=None, donnees=json.dumps(donnees, ensure_ascii=False), cree=c, maj=c, publie=c,
                                statut="publie", phase="termine" if fini else m["phase"], quand=donnees.get("quand", 0) or 0,
                                archive_le=(c + 2 * JOUR + 7200) if fini else 0))
                for u in hasard.sample(clan_ids, min(len(clan_ids), int(len(clan_ids) * 0.4))):
                    reps.append({"evenement_id": nid, "membre_id": u, "choix": hasard.choice("dpn") if genre == "evenement" else "v",
                                 "quand": c + 600})
    b.ajouter("clan_evenements", evs)
    b.ajouter("clan_evenements_reponses", reps, "INSERT OR IGNORE")

    # ─── Les affiches (70 % du clan), leur historique (180 j), les portraits (un par affiche + les recherches) ──
    gabarit = b.un("SELECT * FROM rell_affiches LIMIT 1")
    gab = dict(zip(b.cols("rell_affiches"), gabarit)) if gabarit else None
    aff, histo, portraits = [], [], []
    dossier_av = tableau.dossier_site("avatars")
    for k, uid in enumerate(clan_ids[:int(len(clan_ids) * h["affiches"])]):
        if gab is None:
            break
        c = monde.quand(hasard.randint(0, max(1, jours)))
        rid = 5_000_000_000 + k
        retiree = hasard.random() < 0.03
        aff.append(dict(gab, id=f"banc-{k:06d}", membre_id=uid, membre_nom=noms.get(uid, ""), roblox_nom=f"Pirate_{k}", roblox_id=rid,
                        surnom=hasard.choice(SURNOMS), prime=hasard.randint(1, 400) * 10000, niveau=hasard.randint(1, 90), cree_le=c,
                        maj_le=c, retire_le=int(now - hasard.randint(1, 25) * JOUR) if retiree else 0))
        portraits.append(rid)
    for d in range(min(jours, 182)):
        for _ in range(monde.combien(3, d, fixe=True)):
            if aff:
                histo.append({"guild_id": SERVEUR_ID, "affiche_id": hasard.choice(aff)["id"], "quand": monde.quand(d),
                              "par": hasard.choice(monde.staff[:2]), "action": "modifiee",
                              "changements": json.dumps([{"champ": "prime", "avant": 10000, "apres": 20000}])})
    for d in range(jours):
        for _ in range(monde.combien(h["portraits"], d, fixe=True)):
            portraits.append(6_000_000_000 + len(portraits))
    #  27/10/2026 — le roulement du clan : qui l'a quitté garde son affiche (« un membre parti garde son nom ») tant que la
    #  direction ne la retire pas ; la vitrine publique montre toutes les affiches actives.
    anciens = list(monde.partis)
    n_anciens = int(len(clan_ids) * h["clan_depart_an"] * monde.annees * h["affiches"]) if gab is not None else 0
    for k in range(min(n_anciens, len(anciens))):
        c = monde.quand(hasard.randint(30, max(31, jours)))
        rid = 5_500_000_000 + k
        retiree = hasard.random() < h["affiches_partis_retirees"]
        aff.append(dict(gab, id=f"banc-p{k:06d}", membre_id=anciens[k], membre_nom=f"Ancien {k}", roblox_nom=f"Ancien_{k}",
                        roblox_id=rid, surnom=hasard.choice(SURNOMS), prime=hasard.randint(1, 400) * 10000,
                        niveau=hasard.randint(1, 90), cree_le=c, maj_le=c,
                        retire_le=min(int(now - JOUR), c + hasard.randint(1, 20) * JOUR) if retiree else 0))
        portraits.append(rid)
    b.ajouter("rell_affiches", aff)
    b.ajouter("rell_affiches_historique", histo)
    #  Les équipes du clan : une pour huit membres (EQUIPES_MAX au plus), un chef chacune. Avant le premier nettoyage, la
    #  part du clan partie depuis leur création y est restée (le bot éteint ne l'a pas vue partir) : la règle « Équipes :
    #  membres partis » la retire.
    import site_equipage
    places_prises = {r[0] for r in b.c.execute("SELECT membre_id FROM equipes_membres")} | {
        r[0] for r in b.c.execute("SELECT chef_id FROM equipes")}
    libres_clan = [i for i in clan_ids if i not in places_prises]
    hasard.shuffle(libres_clan)
    equipes, places = [], []
    for k in range(min(site_equipage.EQUIPES_MAX - 2, max(1, len(clan_ids) // 8))):
        if len(libres_clan) < 2:
            break
        chef, c = libres_clan.pop(), monde.quand(hasard.randint(0, max(1, min(jours, 365))))
        eid = f"banc-eq-{k:03d}"
        equipes.append({"guild_id": SERVEUR_ID, "id": eid, "nom": f"Équipe {k + 1}", "type": "libre:Équipe", "chef_id": chef,
                        "ordre": 10 + k, "version": 1, "cree_le": c, "maj_le": c, "maj_par": FONDATEUR})
        for _ in range(min(hasard.randint(*h["equipe_taille"]), len(libres_clan))):
            places.append({"guild_id": SERVEUR_ID, "equipe_id": eid, "membre_id": libres_clan.pop()})
    partis_equipes = anciens[n_anciens:n_anciens + int(len(places) * h["clan_depart_an"] * min(1.0, monde.annees))]
    for k, uid in enumerate(partis_equipes):
        places.append({"guild_id": SERVEUR_ID, "equipe_id": hasard.choice(equipes)["id"], "membre_id": uid})
    if equipes and len(anciens) > n_anciens + len(partis_equipes):
        equipes[-1]["chef_id"] = anciens[n_anciens + len(partis_equipes)]   # un chef parti
    b.ajouter("equipes", equipes)
    b.ajouter("equipes_membres", places, "INSERT OR IGNORE")
    av = [{"roblox_id": rid, "nom": f"Pirate_{rid}", "nom_cle": f"pirate_{rid}", "maj_le": int(now - hasard.randint(0, max(1, jours)) * JOUR)}
          for rid in portraits]
    b.ajouter("rell_avatars", av, "INSERT OR REPLACE")
    if fichiers:
        for rid in portraits:
            (dossier_av / f"{rid}.webp").write_bytes(_octets_image(hasard, hasard.randint(9_000, 22_000)))

    # ─── Les images envoyées sur le site et les actualités de l'équipage ──
    medias, actus = [], []
    dossier_md = tableau.dossier_site("medias")
    utilisees = []
    for d in range(jours, -1, -1):
        for _ in range(monde.combien(h["medias"], d, fixe=True)):
            utile = hasard.random() < 0.55
            if not utile and d > 32:
                continue      # inutilisée : la règle « Images inutilisées » l'a effacée après 30 jours
            ident = "".join(hasard.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop0123456789_-") for _ in range(16))
            c = monde.quand(d)
            taille = hasard.randint(60_000, 320_000)
            medias.append({"id": ident, "guild_id": SERVEUR_ID, "auteur_id": FONDATEUR, "nom": "image.png", "type": "image/webp",
                           "octets": taille, "largeur": 1600, "hauteur": 900, "cree_le": c, "vu_le": c})
            if utile:
                utilisees.append((ident, c))
            if fichiers:
                (dossier_md / f"{ident}.webp").write_bytes(_octets_image(hasard, taille))
    b.ajouter("tableau_medias", medias)
    for d in range(jours, -1, -1):
        for _ in range(monde.combien(h["actualites"], d, fixe=True)):
            if len(actus) >= 499:
                break
            c = monde.quand(d)
            image = utilisees.pop()[0] if utilisees and hasard.random() < 0.4 else ""
            actus.append({"guild_id": SERVEUR_ID, "id": f"banc{len(actus):06d}", "titre": "Actualité : " + hasard.choice(PHRASES),
                          "texte": " ".join(hasard.choice(PHRASES) for _ in range(6)), "image": image, "epingle": 0,
                          "cree_le": c, "maj_le": c})
    b.ajouter("equipage_actualites", actus)
    #  Le reste des images utilisées : citées par des annonces du clan (comme le composeur le fait).
    for (ident, _c), ev in zip(utilisees, evs[::max(1, len(evs) // max(1, len(utilisees)))]):
        donnees = json.loads(ev["donnees"])
        donnees["image"] = ident
        b.c.execute("UPDATE clan_evenements SET donnees=? WHERE id=?", (json.dumps(donnees, ensure_ascii=False), ev["id"]))

    # ─── Le site : sessions, liens, opérations hors ligne ──
    ses, ops = [], []
    for d in range(min(jours, 2)):
        for k in range(8):
            ses.append({"empreinte": f"{d:02d}{k:02d}" + "e" * 60, "guild_id": SERVEUR_ID, "user_id": FONDATEUR, "cree_le": monde.quand(d),
                        "expire_le": int(now + JOUR - d * JOUR), "portee": "tout"})
    for d in range(min(jours, 32)):
        for k in range(10):
            ops.append({"op_id": f"banc-op-{d:04d}-{k:02d}", "guild_id": SERVEUR_ID, "user_id": FONDATEUR, "api": "rell/affiche", "status": 200,
                        "corps": json.dumps({"ok": True, "affiche": {"id": "x", "notes": "n" * 600}}), "quand": monde.quand(d)})
    b.ajouter("tableau_sessions", ses, "INSERT OR IGNORE")
    b.ajouter("tableau_ops", ops, "INSERT OR IGNORE")

    # ─── Les tables du bot qui grossissent avec les membres ──
    act, inv, aud, emp, arr, sec, err = [], [], [], [], [], [], []
    for d in range(min(jours, 92)):
        jour = _jour(now - d * JOUR)
        for uid in hasard.sample(monde.presents, min(len(monde.presents), int(monde.membres(d) * h["activite"]))):
            act.append({"guild_id": SERVEUR_ID, "user_id": uid, "jour": jour, "sources": hasard.choice(("m", "v", "mv"))})
    #  Les arrivées : beaucoup repartent (le roulement d'un serveur Discord) — une arrivée sur `presents / arrivées` est
    #  encore là ; chacune a son empreinte de compte (détection des doubles comptes), 60 % leur invitation suivie.
    arrivees = sum(monde.combien(h["arrivees"], d) for d in range(jours, -1, -1)) or 1
    part_presents = min(1.0, len(monde.presents) / arrivees)
    libres, partis_libres = list(monde.presents), list(monde.partis)
    k_arr = 0
    for d in range(jours, -1, -1):
        for _ in range(monde.combien(h["arrivees"], d)):
            k_arr += 1
            c = monde.quand(d)
            present = bool(libres) and hasard.random() < part_presents
            uid = libres.pop() if present else (partis_libres.pop() if partis_libres else 30_000_000 + k_arr)
            depart = 0 if present else min(int(now), c + hasard.randint(3600, 60 * JOUR))
            if hasard.random() < 0.6:
                inv.append({"guild_id": SERVEUR_ID, "membre_id": uid, "auteur_id": monde.qui(d), "code": f"code{k_arr % 97}",
                            "arrive": c, "compte_cree": c - hasard.randint(1, 2000) * JOUR, "parti": depart})
            emp.append({"guild_id": SERVEUR_ID, "user_id": uid, "avatar_hash": "a" * 32, "username_normalized": f"pirate{uid}",
                        "created_at_ts": c - 400 * JOUR, "joined_at_ts": c, "behavior_hash": "b" * 16, "updated_at": _sqlite(c)})
            if d <= 122:
                arr.append({"guild_id": SERVEUR_ID, "user_id": uid, "joined_day": _jour(c),
                            "left_day": _jour(depart) if depart and now - depart <= 122 * JOUR else None})
    for uid in libres:      # les membres d'avant la période : leur empreinte aussi
        c = int(now - hasard.randint(jours + 1, jours + 400) * JOUR)
        emp.append({"guild_id": SERVEUR_ID, "user_id": uid, "avatar_hash": "a" * 32, "username_normalized": f"pirate{uid}",
                    "created_at_ts": c - 400 * JOUR, "joined_at_ts": c, "behavior_hash": "b" * 16, "updated_at": _sqlite(c)})
    for d in range(jours, -1, -1):
        for _ in range(monde.combien(h["audit_staff"], d)):
            aud.append({"guild_id": SERVEUR_ID, "actor_id": hasard.choice(monde.staff), "target_id": monde.qui(d), "action": "warn",
                        "detail": hasard.choice(MOTIFS), "surface": "slash", "created_at": _sqlite(monde.quand(d))})
        if d <= 92:
            for _ in range(monde.combien(h["securite"], d)):
                sec.append({"guild_id": SERVEUR_ID, "user_id": monde.qui(d), "action": "spam", "details": hasard.choice(PHRASES),
                            "created_at": _sqlite(monde.quand(d))})
        if d <= 8:
            for _ in range(20):
                err.append({"guild_id": SERVEUR_ID, "source": "banc", "error_type": "ValueError", "message": "exemple",
                            "traceback": "Traceback (most recent call last):\n" + "  File \"bot.py\", line 1\n" * 30,
                            "occurred_at": _sqlite(monde.quand(d))})
    b.ajouter("activite_jours", act, "INSERT OR IGNORE")
    b.ajouter("invitations_arrivees", inv, "INSERT OR IGNORE")
    b.ajouter("user_fingerprints", emp, "INSERT OR IGNORE")
    b.ajouter("staff_audit_log", aud)
    b.ajouter("daily_join_log", arr, "INSERT OR IGNORE")
    b.ajouter("security_logs", sec)
    b.ajouter("error_log", err)
    #  La vitrine publique au pire : tous les blocs de l'accueil publics (événements, analyses, actualités, honneur…).
    if "public" in b.cols("equipage_blocs"):
        b.c.execute("UPDATE equipage_blocs SET public=1")
    compte = dict(b.compte)
    b.fin()
    compte["_fichiers_transcripts_octets"] = octets_tr
    return compte


# ═══════════════════════════════════════════════════════════════════════════════
#  Le nettoyage du bot, avec SES fonctions (ce qui aurait tourné chaque jour, puis chaque semaine)
# ═══════════════════════════════════════════════════════════════════════════════

async def nettoyer_comme_le_bot(monde: Monde) -> dict:
    """Le premier passage (rattrapage) : journal, grand nettoyage, RGPD, amnistie, règles du site, transcripts."""
    import casier
    import data_cleanup
    import gdpr
    import registre
    import tableau
    import transcript_store
    get_db = monde.ctx.get_db
    data_cleanup.setup(None, get_db)
    out = {}
    t = time.perf_counter()
    out["registre"] = await registre.purger()
    out["data_cleanup"] = sum((await data_cleanup.run_cleanup()).values())
    async with get_db() as db:
        out["rgpd"] = sum((await gdpr.run_retention(db)).values())
    partis = {uid: None for uid in monde.partis}
    bilan = await casier.amnistie(SERVEUR_ID, set(monde.presents), partis)
    out["amnistie"] = bilan["n"]
    #  L'amnistie passe chaque jour : son archive (30 jours) n'en garde qu'un mois — pas tout l'historique d'un coup.
    async with get_db() as db:
        await db.execute("DELETE FROM infractions_archive WHERE lot=? AND abs(random() % 1000) >= ?",
                         (bilan["lot"], int(1000 * 30 / max(30, min(monde.jours, 730)))))
        await db.commit()
    bilan_site = await tableau.nettoyer(monde.g, None)
    out["site"] = sum(max(0, n) for n in bilan_site.values())
    out["site : équipes (membres partis)"] = max(0, int(bilan_site.get("equipes_partis", 0)))
    out["transcripts"] = await asyncio.to_thread(transcript_store.purge_old)
    #  Comme `db_optimizer_task`, chaque jour : les statistiques de SQLite (le choix des index en dépend).
    async with get_db() as db:
        await db.execute("ANALYZE")
        await db.commit()
    out["duree_s"] = round(time.perf_counter() - t, 2)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Les mesures
# ═══════════════════════════════════════════════════════════════════════════════

def taille_dossier(p: Path) -> tuple:
    n, octets = 0, 0
    for racine, _d, fs in os.walk(p):
        for f in fs:
            try:
                octets += os.path.getsize(os.path.join(racine, f))
                n += 1
            except OSError:
                continue
    return n, octets


def mesurer_base(chemin: Path) -> dict:
    c = sqlite3.connect(chemin)
    pages = c.execute("PRAGMA page_count").fetchone()[0]
    taille_page = c.execute("PRAGMA page_size").fetchone()[0]
    libres = c.execute("PRAGMA freelist_count").fetchone()[0]
    mode = c.execute("PRAGMA auto_vacuum").fetchone()[0]
    tables = {}
    try:
        poids = dict(c.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name").fetchall())
    except sqlite3.Error:
        poids = {}
    index_de = {}
    for nom, tbl in c.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index'"):
        index_de.setdefault(tbl, []).append(nom)
    for (nom,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        n = c.execute(f'SELECT COUNT(*) FROM "{nom}"').fetchone()[0]
        tables[nom] = {"lignes": n, "octets": int(poids.get(nom, 0) or 0),
                       "index_octets": int(sum(poids.get(i, 0) or 0 for i in index_de.get(nom, [])))}
    c.close()
    wal = Path(str(chemin) + "-wal")
    return {"octets": pages * taille_page, "fichier": chemin.stat().st_size, "wal": wal.stat().st_size if wal.exists() else 0,
            "pages_libres": libres, "part_libre": round(libres / pages, 4) if pages else 0, "auto_vacuum": mode, "tables": tables}


async def chronometrer(fn, fois: int = 1):
    """(durée médiane en ms, dernier résultat) d'une coroutine appelée `fois` fois."""
    durees, res = [], None
    for _ in range(fois):
        t = time.perf_counter()
        res = await fn()
        durees.append((time.perf_counter() - t) * 1000)
    return round(statistics.median(durees), 1), res


class Client:
    """Un navigateur réduit à ses requêtes : la session de démonstration (`/tableau/demo`), puis GET avec gzip."""

    def __init__(self, base: str):
        self.base, self.cookie, self.session = base, "", None

    async def ouvrir(self, qui: str = ""):
        import aiohttp
        self.session = aiohttp.ClientSession(auto_decompress=False)
        async with self.session.get(self.base + "/tableau/demo" + qui, allow_redirects=False) as r:
            brut = r.headers.get("Set-Cookie", "")
            self.cookie = brut.split(";", 1)[0]
        return self

    async def fermer(self):
        await self.session.close()

    async def lire(self, chemin: str) -> dict:
        t = time.perf_counter()
        async with self.session.get(self.base + chemin, headers={"Cookie": self.cookie, "Accept-Encoding": "gzip"}) as r:
            brut = await r.read()
            statut, encodage = r.status, r.headers.get("Content-Encoding", "")
        ms = (time.perf_counter() - t) * 1000
        corps = gzip.decompress(brut) if encodage == "gzip" else brut
        return {"statut": statut, "ms": round(ms, 1), "octets": len(corps), "gzip": len(brut) if encodage == "gzip" else None,
                "corps": corps}


def _vider_caches():
    import tableau
    tableau._cache.clear()
    try:
        import site_equipage
        site_equipage._permis.clear()
    except (ImportError, AttributeError):   # un dépôt sans le site de l'équipage : rien à vider
        pass
    try:
        import site_vitrine
        site_vitrine.oublier()
    except ImportError:   # un dépôt d'avant la vitrine publique : rien à vider
        pass


async def mesurer_routes(monde: Monde, port: int) -> dict:
    """Chaque réponse du site : à froid (caches vidés), puis trois fois à chaud ; poids brut et compressé."""
    import tableau
    base = f"http://localhost:{port}"
    tete = await Client(base).ouvrir()
    equipage = await Client(base).ouvrir("?qui=equipage")
    import transcript_store
    async with monde.ctx.get_db() as db:
        async with db.execute("SELECT membre_id, COUNT(*) n FROM registre WHERE membre_id>0 GROUP BY membre_id"
                              " ORDER BY n DESC LIMIT 1") as cur:
            charge = await cur.fetchone()
        async with db.execute("SELECT ticket_id, jeton FROM ticket_transcripts WHERE jeton IS NOT NULL AND jeton != ''") as cur:
            jetons = await cur.fetchall()
    membre = int(charge[0]) if charge else 1000

    def poids(jeton):
        p = transcript_store.transcript_path(jeton)
        return os.path.getsize(p) if p and os.path.isfile(p) else -1
    ticket = max(jetons, key=lambda x: poids(x[1]), default=None)   # la plus longue conversation
    routes = [
        ("donnees", "/tableau/espace/donnees", True),
        ("membre (le plus cité)", f"/tableau/espace/membre?id={membre}", True),
        ("recherche", "/tableau/espace/recherche?q=pi", False),
        ("export journal 90 j", "/tableau/espace/export?quoi=journal&jours=90", False),
        ("export casier", "/tableau/espace/export?quoi=sanctions", False),
        ("conversation (transcript)", f"/tableau/espace/conversation?ticket={ticket[0] if ticket else 1}", False),
        ("rell/affiches", "/tableau/espace/api/rell/affiches", False),
        ("rell/catalogue", "/tableau/espace/api/rell/catalogue", False),
        ("clan/evenements", "/tableau/espace/api/clan/evenements", False),
        ("nettoyage", "/tableau/espace/api/nettoyage", False),
        ("recrutement/suivi", "/tableau/espace/api/recrutement/suivi", False),
        ("recrutement/banque", "/tableau/espace/api/recrutement/banque", False),
        ("textes", "/tableau/espace/api/textes", False),
    ]
    from urllib.parse import quote
    il_y_a_3_mois = datetime.fromtimestamp(time.time() - 95 * JOUR, timezone.utc).strftime("%Y-%m")
    for nom, chemin in (("journal (7 jours, Modération)", f"journal?depuis={int(time.time() - 7 * JOUR)}&cat={quote('Modération')}"),
                        ("journal (recherche « Mira »)", "journal?q=Mira"),
                        ("tickets fermés (un mois des archives)", f"tickets/fermes?mois={il_y_a_3_mois}"),
                        ("casier (la suite : 250 cases de plus)", "casier/membres?apres=250"),
                        ("nettoyage : aperçu d'une durée", "nettoyage/apercu?cle=journal&jours=45")):
        if chemin.split("?")[0] in tableau.ROUTES or chemin.split("?")[0] in tableau._INTERNES:   # après les corrections
            routes.append((nom, f"/tableau/espace/api/{chemin}", False))
    out = {}
    for nom, chemin, lourd in routes:
        _vider_caches()
        froid = await tete.lire(chemin)
        chauds = [await tete.lire(chemin) for _ in range(3)]
        out[nom] = {"statut": froid["statut"], "froid_ms": froid["ms"], "chaud_ms": round(statistics.median(c["ms"] for c in chauds), 1),
                    "octets": froid["octets"], "gzip": froid["gzip"]}
        if nom == "donnees" and froid["statut"] == 200:
            d = json.loads(froid["corps"])
            out[nom]["parties"] = {k: len(json.dumps(v, ensure_ascii=False).encode()) for k, v in d.items()}
            out[nom]["elements"] = {"journal": len(d.get("journal", {}).get("evenements", [])),
                                    "tickets_fermes": len(d.get("tickets", {}).get("fermes", [])),
                                    "casier_membres": len(d.get("sanctions", {}).get("membres", [])),
                                    "candidats": len(d.get("candidats", [])), "personnes": len(d.get("personnes", {})),
                                    "questions": len(d.get("questions", {}).get("liste", [])),
                                    "entraide": len(d.get("entraide", {}).get("liste", []))}
    #  27/10/2026 : la vitrine PUBLIQUE (sans session ; réponses gardées 60 s — « froid » : recalculée) et les équipes.
    if "equipage/equipes" in tableau.ROUTES:
        routes_suite = [("équipes (direction)", "/tableau/espace/api/equipage/equipes")]
    else:
        routes_suite = []
    try:
        import site_vitrine   # noqa: F401 — la vitrine existe dans ce dépôt
        routes_suite += [("vitrine : données", "/equipage/donnees"), ("vitrine : la page", "/equipage"),
                         ("vitrine : l'image de l'aperçu", "/equipage/banniere.png")]
    except ImportError:   # un dépôt d'avant la vitrine (le banc mesure aussi l'état « avant »)
        pass
    for nom, chemin in routes_suite:
        _vider_caches()
        froid = await tete.lire(chemin)
        chauds = [await tete.lire(chemin) for _ in range(3)]
        out[nom] = {"statut": froid["statut"], "froid_ms": froid["ms"], "chaud_ms": round(statistics.median(c["ms"] for c in chauds), 1),
                    "octets": froid["octets"], "gzip": froid["gzip"]}
        if nom == "vitrine : données" and froid["statut"] == 200:
            d = json.loads(froid["corps"])
            out[nom]["elements"] = {"affiches": len(d.get("affiches", [])), "equipes": len(d.get("equipes", [])),
                                    "blocs": len((d.get("accueil") or {}).get("blocs", []))}
    for nom, chemin in (("équipage : accueil", "/tableau/equipage/api/accueil"), ("équipage : équipage", "/tableau/equipage/api/equipage")):
        _vider_caches()
        froid = await equipage.lire(chemin)
        chauds = [await equipage.lire(chemin) for _ in range(3)]
        out[nom] = {"statut": froid["statut"], "froid_ms": froid["ms"], "chaud_ms": round(statistics.median(c["ms"] for c in chauds), 1),
                    "octets": froid["octets"], "gzip": froid["gzip"]}
    await tete.fermer()
    await equipage.fermer()
    return out


async def mesurer_regles(monde: Monde) -> dict:
    """La rubrique « Nettoyage », règle par règle : ce que coûtent son compte (« N gardés ») et son aperçu (« N partiront »)
    — la page les demande tous à chaque visite. {clé : {"compter_ms", "apercu_ms", "partiront"}}."""
    import inspect

    import tableau
    t, out = time.time(), {}
    for r in sorted(tableau.REGLES.values(), key=lambda x: (x["ordre"], x["cle"])):
        jours = await tableau.jours_regle(SERVEUR_ID, r["cle"])
        ligne = {}
        for nom, fn in (("compter", r["compter"]), ("apercu", r.get("apercu"))):
            if fn is None:
                continue
            d = time.perf_counter()
            n = fn(SERVEUR_ID, jours, t)
            n = (await n) if inspect.isawaitable(n) else n
            ligne[nom + "_ms"] = round((time.perf_counter() - d) * 1000, 1)
            if nom == "apercu":
                ligne["partiront"] = int(n or 0)
        out[r["cle"]] = ligne
    return out


async def mesurer_memoire(monde: Monde) -> dict:
    """Le pic de mémoire Python d'une construction de `donnees` (et de sa mise en JSON), cache vidé."""
    import tableau
    _vider_caches()
    tracemalloc.start()
    d = await tableau.donnees(monde.g)
    texte = json.dumps(d, ensure_ascii=False, separators=(",", ":"), default=str)
    _actuel, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"donnees_pic_octets": pic, "donnees_json_octets": len(texte.encode())}


async def mesurer_boucles(monde: Monde) -> dict:
    """Les boucles du bot qui parcourent ces tables, sur la base en régime établi (un jour de plus)."""
    import casier
    import data_cleanup
    import gdpr
    import registre
    import tableau
    import transcript_store
    get_db = monde.ctx.get_db
    out = {}
    out["nettoyage du site (toutes les règles)"], _ = await chronometrer(lambda: tableau.nettoyer(monde.g, None))
    out["rubrique Nettoyage (compteurs)"], _ = await chronometrer(lambda: tableau.etat_nettoyage(SERVEUR_ID))
    out["journal : purge (toutes les 2 000 écritures)"], _ = await chronometrer(registre.purger)
    out["grand nettoyage (hebdomadaire)"], _ = await chronometrer(data_cleanup.run_cleanup)

    async def rgpd():
        async with get_db() as db:
            return await gdpr.run_retention(db)
    out["rétention RGPD (quotidienne)"], _ = await chronometrer(rgpd)
    out["amnistie du casier (quotidienne)"], _ = await chronometrer(
        lambda: casier.amnistie(SERVEUR_ID, set(monde.presents), {u: None for u in monde.partis}))
    out["casier : comptes par zone"], _ = await chronometrer(lambda: casier.comptes(SERVEUR_ID, BOT_ID))
    out["transcripts : purge et plafond"], _ = await chronometrer(
        lambda: asyncio.to_thread(lambda: transcript_store.purge_old() + transcript_store.plafonner()))
    try:
        import evenements
        if evenements.pret():
            out["événements du clan (chaque minute)"], _ = await chronometrer(lambda: evenements.tic([monde.g]), 3)
    except ImportError:
        pass
    if tableau._mesurer_groupe is not None:
        import rellseas_panneau
        clan = monde.g.get_role(int(monde.ctx.conf[rellseas_panneau.CLE_ROLE_CIBLE]))
        out["activité du clan (liste du clan)"], _ = await chronometrer(
            lambda: tableau._mesurer_groupe(SERVEUR_ID, [m for m in clan.members if not m.bot]), 3)
    out["arrivée d'un membre (doubles comptes)"] = await mesurer_arrivee(monde)
    return out


def _fonctions_du_bot(noms) -> dict:
    """Des fonctions de bot.py, lues dans sa source (jamais importé : le bot démarrerait)."""
    import ast
    import re as _re
    from collections import Counter
    ns = {"re": _re, "Counter": Counter}
    for n in ast.parse((RACINE / "bot.py").read_text(encoding="utf-8")).body:
        if isinstance(n, ast.FunctionDef) and n.name in noms:
            exec(ast.unparse(n), ns)   # noqa: S102 — code du dépôt
    return ns


async def mesurer_arrivee(monde: Monde) -> float:
    """La 4ᵉ vérification de `detect_alt_account` (bot.py), à chaque arrivée : le nom du nouveau comparé aux empreintes
    de compte — telle que bot.py la fait aujourd'hui (avec ou sans le tri `_nom_peut_ressembler`). ms."""
    ns = _fonctions_du_bot({"normalize_username", "levenshtein_distance", "username_similarity", "_nom_peut_ressembler"})
    async with monde.ctx.get_db() as db:
        async with db.execute("SELECT user_id, username_normalized FROM user_fingerprints WHERE guild_id=? AND user_id != ?",
                              (SERVEUR_ID, 1)) as cur:
            empreintes = await cur.fetchall()
    nom, g = "Pirate_Nouveau77", monde.g
    filtre = ns.get("_nom_peut_ressembler")
    t = time.perf_counter()
    for uid, norme in empreintes:
        if norme:
            if filtre is not None:
                m = g.get_member(uid)
                if not m or not filtre(nom, norme):
                    continue
                ns["username_similarity"](nom, norme)
            else:
                if ns["username_similarity"](nom, norme) >= 85:
                    g.get_member(uid)
    return round((time.perf_counter() - t) * 1000, 1)


async def mesurer_demarrage(monde: Monde) -> dict:
    """Le redémarrage : les `init_db` de chaque module sur la base remplie (tables, index, colonnes ajoutées)."""
    import importlib
    out, total = {}, 0.0
    for nom in ("registre", "recrutements", "questions", "vigilance", "clan", "casier", "sondages", "suggestions", "entraide",
                "annonces", "tableau", "questionnaire", "affiches", "textes", "site_equipage", "evenements", "activite"):
        try:
            module = importlib.import_module(nom)
        except ImportError:
            continue
        if getattr(module, "_get_db", None) is None or not hasattr(module, "init_db"):
            continue
        t = time.perf_counter()
        await module.init_db()
        ms = (time.perf_counter() - t) * 1000
        out[nom] = round(ms, 1)
        total += ms
    out["total"] = round(total, 1)
    return out


async def mesurer_compactage(monde: Monde) -> dict:
    """Ce que coûte le compactage : VACUUM complet (base bloquée pendant ce temps), ou l'incrémental."""
    chemin = monde.ctx.dossier / "site_local.db"
    avant = chemin.stat().st_size
    out = {"avant": avant}
    try:
        import compactage
    except ImportError:
        compactage = None
    if compactage is not None:
        get_db = monde.ctx.get_db
        t = time.perf_counter()
        etat = await compactage.etat(get_db)
        out["etat_ms"] = round((time.perf_counter() - t) * 1000, 1)
        out["mode"], out["libres_avant"] = etat.get("mode"), etat.get("libres")
        #  La conversion, une fois (aux heures creuses) : un VACUUM complet qui passe la base en incrémental.
        t = time.perf_counter()
        out["conversion"] = await compactage.passer(get_db, chemin, forcer=True)
        out["conversion_ms"] = round((time.perf_counter() - t) * 1000, 1)
        #  Une nuit ordinaire : les pages qu'un jour de purges libère (le jour le plus ancien du journal), rendues par
        #  paquets — pauses comprises.
        c = sqlite3.connect(chemin, timeout=60)
        c.execute("DELETE FROM registre WHERE quand < (SELECT MIN(quand) + 86400 FROM registre)")
        c.commit()
        c.close()
        out["nuit_libres"] = (await compactage.etat(get_db))["libres"]
        t = time.perf_counter()
        out["passage"] = await compactage.passer(get_db, chemin, forcer=True)
        out["passage_ms"] = round((time.perf_counter() - t) * 1000, 1)
        out["apres_passage_libres"] = (await compactage.etat(get_db))["libres"]
    t = time.perf_counter()
    c = sqlite3.connect(chemin, timeout=60)
    c.execute("VACUUM")
    c.close()
    out["vacuum_ms"] = round((time.perf_counter() - t) * 1000, 1)
    out["apres_vacuum"] = chemin.stat().st_size
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Une taille : construire, remplir, nettoyer, mesurer
# ═══════════════════════════════════════════════════════════════════════════════

async def une_taille(annees: float, port: int, fichiers: bool = True, servir: bool = False, dossier: Path | None = None,
                     mesures: bool = True) -> dict:
    import site_local
    import tableau
    from aiohttp import web
    debut = time.perf_counter()
    app, ctx = await site_local.construire(dossier, port)
    #  L'activité du clan : la vraie mesure (`activite.presences`, comme `_rellseas_mesurer_groupe` de bot.py).
    import activite

    async def _cfg(_gid):
        return ctx.conf

    async def _db_set(_gid, k, v):
        ctx.conf[k] = v
    activite.setup(get_db=ctx.get_db, cfg=_cfg, db_set=_db_set, log=lambda *a: None)

    async def mesurer_groupe(guild_id, membres):
        conf = dict(await activite.config(guild_id))
        conf["activite_fenetre"] = 7
        return await activite.presences(guild_id, membres, conf)
    tableau._mesurer_groupe = mesurer_groupe
    #  La conversation d'un ticket fermé : son transcript relu, comme `_conversation_seule` de bot.py (le site local, lui,
    #  invente une conversation) ; un ticket sans transcript garde celle du site local.
    import transcript_store
    inventee = tableau._conversation

    async def conversation(gg, ticket_id):
        async with ctx.get_db() as db:
            async with db.execute("SELECT url, jeton FROM ticket_transcripts WHERE guild_id=? AND ticket_id=?",
                                  (gg.id, int(ticket_id))) as cur:
                tr = await cur.fetchone()
        jeton = tr[1] if tr and tr[1] else None
        if not jeton:
            return await inventee(gg, ticket_id)
        messages = await asyncio.to_thread(transcript_store.lire_conversation, jeton)
        if messages is None:
            return {"ticket": int(ticket_id), "messages": [], "lien": tr[0], "absent": "Le transcript a été effacé."}
        return {"ticket": int(ticket_id), "source": "transcript", "messages": messages, "lien": tr[0]}
    tableau._conversation = conversation
    monde = Monde(annees, ctx)
    await peupler(monde)
    t = time.perf_counter()
    comptes = await asyncio.to_thread(remplir, monde, fichiers)
    remplissage_s = round(time.perf_counter() - t, 1)
    await activite.init_db()
    rattrapage = await nettoyer_comme_le_bot(monde)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", port).start()
    rapport = {"annees": annees, "membres": monde.membres_fin, "clan": len([m for m in monde.g.members
                                                                             if any(r.name == "Rell Seas" for r in m.roles)]),
               "remplissage_s": remplissage_s, "inseres": comptes, "rattrapage": rattrapage}
    rapport["base"] = mesurer_base(ctx.dossier / "site_local.db")
    rapport["dossiers"] = {nom: dict(zip(("fichiers", "octets"), taille_dossier(p))) for nom, p in (
        ("transcripts", Path(__import__("transcript_store")._BASE_DIR)), ("medias", tableau.dossier_site("medias")),
        ("portraits", tableau.dossier_site("avatars")))}
    if mesures:
        rapport["routes"] = await mesurer_routes(monde, port)
        rapport["regles"] = await mesurer_regles(monde)
        rapport["memoire"] = await mesurer_memoire(monde)
        rapport["boucles"] = await mesurer_boucles(monde)
        rapport["demarrage"] = await mesurer_demarrage(monde)
        if not servir and dossier is None:
            rapport["compactage"] = await mesurer_compactage(monde)
    rapport["duree_s"] = round(time.perf_counter() - debut, 1)
    if servir:
        print(f"[BANC] base « {annees} an(s) » servie : http://localhost:{port}/tableau/demo   (dossier {ctx.dossier})", flush=True)
        print("[BANC] PRET", flush=True)
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await runner.cleanup()
    await runner.cleanup()
    if dossier is None:
        shutil.rmtree(ctx.dossier, ignore_errors=True)
    return rapport


# ═══════════════════════════════════════════════════════════════════════════════
#  Le rapport
# ═══════════════════════════════════════════════════════════════════════════════

VOLUME_RAILWAY = 5 * 1024 ** 3    # hypothèse : le volume d'un projet Railway « Hobby » (le /stats ne donne que des %)
COPIES_MAX = 11                    # db_backup : 7 quotidiennes + 4 hebdomadaires, au plus 30 % du volume


def markdown(rapports: list, titre: str = "Banc de plusieurs années") -> str:
    r = sorted(rapports, key=lambda x: x["annees"])
    col = " | ".join(f"{x['annees']:g} an{'s' if x['annees'] > 1 else ''}" for x in r)
    sep = "|".join(["---"] * (len(r) + 1))
    L = [f"# {titre}", "", f"Mesuré le {datetime.now():%d/%m/%Y %H:%M} sur le vrai site local (`outils/banc_annees.py`).", "",
         f"| | {col} |", f"|{sep}|",
         "| Membres | " + " | ".join(_n(x["membres"]) for x in r) + " |",
         "| Clan | " + " | ".join(str(x["clan"]) for x in r) + " |",
         "| Base (fichier) | " + " | ".join(_mo(x["base"]["fichier"]) for x in r) + " |",
         "| Pages libres | " + " | ".join(f"{100 * x['base']['part_libre']:.0f} %" for x in r) + " |",
         "| Transcripts | " + " | ".join(f"{_mo(x['dossiers']['transcripts']['octets'])} ({x['dossiers']['transcripts']['fichiers']})" for x in r) + " |",
         "| Images du site | " + " | ".join(f"{_mo(x['dossiers']['medias']['octets'])} ({x['dossiers']['medias']['fichiers']})" for x in r) + " |",
         "| Portraits | " + " | ".join(f"{_mo(x['dossiers']['portraits']['octets'])} ({x['dossiers']['portraits']['fichiers']})" for x in r) + " |",
         "| Copies de la base (≤ 11, ≤ 30 % du volume) | " + " | ".join(
             _mo(min(COPIES_MAX * x["base"]["fichier"], max(2 * x["base"]["fichier"], 0.30 * VOLUME_RAILWAY))) for x in r) + " |",
         "| Total sur un volume de 5 Go | " + " | ".join(
             f"{100 * (x['base']['fichier'] + min(COPIES_MAX * x['base']['fichier'], max(2 * x['base']['fichier'], 0.30 * VOLUME_RAILWAY)) + sum(d['octets'] for d in x['dossiers'].values())) / VOLUME_RAILWAY:.1f} %".replace(".", ",")
             for x in r) + " |", ""]
    L += ["## Les plus grosses tables", "", f"| Table | {col} |", f"|{sep}|"]
    grosses = sorted({t for x in r for t in x["base"]["tables"]},
                     key=lambda t: -max(x["base"]["tables"].get(t, {}).get("octets", 0) + x["base"]["tables"].get(t, {}).get("index_octets", 0) for x in r))[:18]
    for t in grosses:
        L.append(f"| {t} | " + " | ".join(
            f"{_n(x['base']['tables'].get(t, {}).get('lignes', 0))} l. · {_mo(x['base']['tables'].get(t, {}).get('octets', 0) + x['base']['tables'].get(t, {}).get('index_octets', 0))}"
            for x in r) + " |")
    L += ["", "## Les réponses du site (froid : caches vidés · chaud · poids brut / compressé)", "", f"| Réponse | {col} |", f"|{sep}|"]
    for nom in r[-1]["routes"]:
        cellules = []
        for x in r:
            v = x["routes"].get(nom)
            cellules.append("—" if not v else f"{v['froid_ms']:.0f} ms · {v['chaud_ms']:.0f} ms · {v['octets'] / 1024:.0f} Ko / "
                            f"{(v['gzip'] or v['octets']) / 1024:.0f} Ko" + ("" if v["statut"] == 200 else f" · **{v['statut']}**"))
        L.append(f"| {nom} | " + " | ".join(cellules) + " |")
    if all("vitrine : données" in x["routes"] for x in r):
        v = [x["routes"]["vitrine : données"].get("elements", {}) for x in r]
        L += ["", "### La vitrine publique (sans session, réponses gardées 60 s)", "", f"| | {col} |", f"|{sep}|",
              "| Affiches montrées (dont celles des anciens du clan, tant que la direction ne les retire pas) | "
              + " | ".join(_n(e.get("affiches", 0)) for e in v) + " |",
              "| Équipes montrées | " + " | ".join(_n(e.get("equipes", 0)) for e in v) + " |",
              "| Blocs publics | " + " | ".join(_n(e.get("blocs", 0)) for e in v) + " |"]
    L += ["", "### Ce que pèse `donnees`, partie par partie (octets JSON)", "", f"| Partie | {col} |", f"|{sep}|"]
    parties = sorted({p for x in r for p in x["routes"]["donnees"].get("parties", {})},
                     key=lambda p: -r[-1]["routes"]["donnees"].get("parties", {}).get(p, 0))
    for p in parties[:12]:
        L.append(f"| {p} | " + " | ".join(f"{x['routes']['donnees'].get('parties', {}).get(p, 0) / 1024:.0f} Ko" for x in r) + " |")
    L.append("| éléments | " + " | ".join(", ".join(f"{k} {v}" for k, v in x["routes"]["donnees"].get("elements", {}).items()) for x in r) + " |")
    L.append("| mémoire (pic Python) | " + " | ".join(_mo(x["memoire"]["donnees_pic_octets"]) for x in r) + " |")
    if all("regles" in x for x in r):
        L += ["", "### La rubrique « Nettoyage », règle par règle (compte · aperçu, ms)", "", f"| Règle | {col} |", f"|{sep}|"]
        for k in r[-1]["regles"]:
            L.append(f"| {k} | " + " | ".join(
                "—" if k not in x["regles"] else " · ".join(f"{x['regles'][k][c]:.0f}" for c in ("compter_ms", "apercu_ms")
                                                             if c in x["regles"][k]) for x in r) + " |")
    L += ["", "## Les boucles du bot (ms)", "", f"| Boucle | {col} |", f"|{sep}|"]
    for nom in r[-1]["boucles"]:
        L.append(f"| {nom} | " + " | ".join(f"{x['boucles'].get(nom, 0):.0f}" for x in r) + " |")
    L += ["", "## Le démarrage (init_db sur la base remplie, ms)", "",
          "| Total | " + " | ".join(f"{x['demarrage']['total']:.0f}" for x in r) + " |", ""]
    if all("compactage" in x for x in r):
        cp = [x["compactage"] for x in r]
        L += ["## Le compactage", "", f"| | {col} |", f"|{sep}|",
              "| Pages libres après le premier nettoyage | " + " | ".join(_mo(c.get("libres_avant", 0)) for c in cp) + " |",
              "| Conversion en incrémental (une fois, la nuit : un VACUUM) | " + " | ".join(
                  f"{c['conversion_ms']:.0f} ms" if "conversion_ms" in c else "—" for c in cp) + " |",
              "| Une nuit ordinaire (un jour de purges rendu par paquets, pauses comprises) | " + " | ".join(
                  f"{c['passage_ms']:.0f} ms · {_mo(c.get('nuit_libres', 0))} rendus · reste {_mo(c.get('apres_passage_libres', 0))}"
                  if "passage_ms" in c else "—" for c in cp) + " |",
              "| VACUUM complet (la base bloquée) | " + " | ".join(f"{c['vacuum_ms']:.0f} ms" for c in cp) + " |", ""]
    L += ["## Le premier nettoyage (rattrapage, lignes retirées)", "",
          "| | " + col + " |", f"|{sep}|"]
    for k in r[-1]["rattrapage"]:
        L.append(f"| {k} | " + " | ".join(str(x["rattrapage"].get(k, "")) for x in r) + " |")
    L += ["", "## Les hypothèses", "", "```json", json.dumps(HYPOTHESES, ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(L)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Le site après plusieurs années : volumes, temps, poids.")
    p.add_argument("--annees", default="1,3,5", help="tailles, en années (1,3,5 par défaut)")
    p.add_argument("--port", type=int, default=8809)
    p.add_argument("--sortie", default="", help="dossier du rapport (rapport.json, rapport.md)")
    p.add_argument("--servir", action="store_true", help="une seule taille, gardée servie sur --port")
    p.add_argument("--sans-fichiers", action="store_true", help="sans transcripts ni images sur le disque")
    p.add_argument("--garder", default="", help="une seule taille, construite dans ce dossier et gardée (analyses)")
    p.add_argument("--sans-mesures", action="store_true", help="construire (et servir) sans mesurer")
    p.add_argument("--titre", default="Banc de plusieurs années")
    p.add_argument("--json", default="", help="(interne) écrire le rapport d'une taille ici")
    a = p.parse_args()
    tailles = [float(x) for x in a.annees.split(",") if x.strip()]
    if a.servir or a.json or a.garder or len(tailles) == 1 and not a.sortie:
        rapport = asyncio.run(une_taille(tailles[0], a.port, not a.sans_fichiers, a.servir, Path(a.garder) if a.garder else None,
                                         not a.sans_mesures))
        if a.json:
            Path(a.json).write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            print(json.dumps(rapport, ensure_ascii=False, indent=1))
        return 0
    sortie = Path(a.sortie or tempfile.mkdtemp(prefix="banc_annees_"))
    sortie.mkdir(parents=True, exist_ok=True)
    rapports = []
    for n in tailles:
        fichier = sortie / f"taille_{n:g}.json"
        print(f"[BANC] {n:g} an(s)…", flush=True)
        cmd = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--annees", f"{n:g}", "--port", str(a.port), "--json", str(fichier)]
        if a.sans_fichiers:
            cmd.append("--sans-fichiers")
        r = subprocess.run(cmd, cwd=str(RACINE))
        if r.returncode != 0 or not fichier.exists():
            print(f"[BANC] {n:g} an(s) : échec (code {r.returncode})")
            return 1
        rapports.append(json.loads(fichier.read_text(encoding="utf-8")))
    (sortie / "rapport.json").write_text(json.dumps(rapports, ensure_ascii=False, indent=1), encoding="utf-8")
    (sortie / "rapport.md").write_text(markdown(rapports, a.titre), encoding="utf-8")
    print(f"[BANC] rapport : {sortie / 'rapport.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
