"""entraide.py — l'entraide Rell Seas (22/10/2026).

Demandé par le fondateur : « un salon ultra bien optimisé ou une catégorie qui regroupe plusieurs
sous-salons… demander de l'aide, faire du trading (s'échanger des fruits), des demandes de farm, de
boss, de chill, une zone discussion pour le jeu… ultra compact pour éviter des milliers de salons…
un vrai salon tout en haut, de redirection : ils cliquent sur trade, ça les amène dans la zone
trade… des joueurs qualifiés avec des rôles, plusieurs sous-rôles en fonction des zones : ils
pourront certifier que l'aide a bien été faite et clôturer la demande… un nettoyage automatique. »

Une catégorie, sept salons, quel que soit le nombre de demandes :
  🧭 orientation — une ligne par zone, un bouton qui y mène ;
  💬 discussion  — le chat du jeu ;
  🆘 aide · ⚔️ boss · 🌾 farm · 🤝 trade · 🌴 chill — une zone par besoin.
Une demande = UN fil (post de forum si le serveur est communautaire, sinon fil sous une carte),
jamais un salon. « ➕ Publier une demande » ouvre le formulaire de la zone ; la carte montre
l'auteur, sa demande, qui vient aider. Un guide de la zone (son rôle) certifie l'aide et clôt —
le middleman pour un échange ; l'auteur peut fermer ; le staff peut tout. Nettoyage : une demande
sans activité se ferme, une demande close disparaît après un délai ; la base garde la trace.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import discord
from discord.ui import Button, RoleSelect, Select, UserSelect

import visuels
from ui_v2 import LayoutView, Palette


# ═══════════════════════════════════════════════════════════════════════════════
#  Zones
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Champ:
    cle: str
    libelle: str          # ≤ 45 caractères (titre du champ)
    aide: str = ""        # ≤ 100 caractères (texte d'exemple)
    long: bool = False
    max: int = 100
    requis: bool = True


@dataclass(frozen=True)
class Zone:
    cle: str
    nom: str
    emoji: str
    salon: str
    phrase: str           # la ligne de l'orientation
    consigne: str         # le panneau de la zone
    couleur: int
    expire_h: int         # fermée après autant d'heures sans activité
    champs: tuple
    titre: str            # le nom du fil, à partir des champs
    certif: str = ""      # « guide », « middleman » ou rien
    role: str = ""        # le rôle créé à l'installation
    rejoindre: str = "Je viens aider"
    icone_rejoindre: str = "accueil"
    annonce: str = "🙋 {qui} vient t'aider, {auteur} !"


PSEUDO = Champ("pseudo", "Ton pseudo Roblox", "Pour qu'on te trouve en jeu", max=40)
NIVEAU = Champ("niveau", "Ton niveau", "Ex. 1 250", max=20, requis=False)

ZONES = {z.cle: z for z in (
    Zone("aide", "Aide", "🆘", "🆘・aide", "Une question, un blocage",
         "Bloqué ou perdu ? Publie ta demande : un joueur vient t'aider, un guide certifie l'aide.",
         0x22C55E, 24,
         (Champ("titre", "Ton problème", "En une phrase", max=90),
          Champ("details", "Explique", "Où tu es, ce que tu as déjà essayé…", long=True, max=800, requis=False),
          PSEUDO, NIVEAU),
         "{titre}", certif="guide", role="🆘 Guide Aide"),
    Zone("boss", "Boss", "⚔️", "⚔️・boss", "Du renfort contre un boss",
         "Un boss te résiste ? Dis lequel : des joueurs viennent t'épauler, un guide certifie.",
         0xEF4444, 6,
         (Champ("titre", "Quel boss ?", "Son nom", max=60), PSEUDO, NIVEAU,
          Champ("joueurs", "Joueurs voulus", "Combien en plus de toi ? Ex. 2", max=10, requis=False),
          Champ("details", "Précisions", "Île, heure, conditions…", long=True, max=500, requis=False)),
         "Boss {titre}", certif="guide", role="⚔️ Guide Boss"),
    Zone("farm", "Farm", "🌾", "🌾・farm", "Farmer à plusieurs",
         "Niveaux, argent, objets : trouve des joueurs pour farmer avec toi.",
         0x84CC16, 12,
         (Champ("titre", "Quoi farmer ?", "Niveaux, argent, un objet…", max=80), PSEUDO, NIVEAU,
          Champ("duree", "Combien de temps ?", "Ex. 1 h", max=30, requis=False),
          Champ("details", "Précisions", "Où, comment…", long=True, max=500, requis=False)),
         "Farm {titre}", certif="guide", role="🌾 Guide Farm"),
    Zone("trade", "Trade", "🤝", "🤝・trade", "Échanger fruits et objets",
         "Propose un échange. Avec un inconnu, ne donne jamais en premier : appelle un middleman.",
         0xF59E0B, 48,
         (Champ("donne", "Je donne", "Fruits, objets…", max=120),
          Champ("cherche", "Je cherche", "Ce que tu veux en échange", max=120), PSEUDO,
          Champ("details", "Précisions", "Valeur, conditions…", long=True, max=400, requis=False)),
         "{donne} ⇄ {cherche}", certif="middleman", role="🛡️ Middleman",
         rejoindre="Intéressé", icone_rejoindre="pour", annonce="💬 {qui} est intéressé par ton échange, {auteur} !"),
    Zone("chill", "Chill", "🌴", "🌴・chill", "Jouer tranquille ensemble",
         "Envie de naviguer, discuter, explorer ? Trouve des joueurs pour jouer tranquille.",
         0x38BDF8, 6,
         (Champ("titre", "Ce que tu veux faire", "Naviguer, discuter, explorer…", max=90), PSEUDO,
          Champ("quand", "Quand ?", "Maintenant, ce soir 21 h…", max=40, requis=False),
          Champ("details", "Précisions", "Ce que tu aimes, ton style…", long=True, max=400, requis=False)),
         "{titre}", rejoindre="Je viens", annonce="🌴 {qui} te rejoint, {auteur} !"),
)}
CATEGORIE = "🏴‍☠️ RELL SEAS"
ORIENTATION = "🧭・orientation"
DISCUSSION = "💬・discussion"

STATUTS = {
    "ouverte": ("Ouverte", "🟢"),
    "prise": ("En cours", "🟡"),
    "terminee": ("Terminée", "✅"),
    "fermee": ("Fermée", "🔒"),
    "expiree": ("Expirée", "⌛"),
    "retiree": ("Retirée", "🗑️"),
}
OUVERTS = ("ouverte", "prise")
#  Étiquettes des forums : réservées au bot et au staff (« modérées »).
TAGS = (("Ouverte", "🟢"), ("En cours", "🟡"), ("Terminée", "✅"), ("Fermée", "🔒"))
ETIQUETTE = {"ouverte": "Ouverte", "prise": "En cours", "terminee": "Terminée"}

MAX_OUVERTES = 3          # par membre, toutes zones
ATTENTE_S = 120           # entre deux demandes d'un même membre
MAX_AIDANTS = 10
GARDER_H = 24             # une demande close disparaît après ce délai
APPEL_MM_S = 900          # un appel au middleman par quart d'heure et par échange
ARCHIVE_MIN = 10080       # Discord n'archive jamais avant nous
DELAIS = (2, 6, 12, 24, 48, 72)
PAR_PASSAGE = 15          # fermetures ou suppressions par passage de la boucle

_get_db = _cfg = _db_set = None
_texte_refuse = _controle = _est_staff = _journal = _salon_ticket = _retour = None
_log = print
_verrous: dict = {}
_creations: dict = {}
_verifies: dict = {}


def setup(*, get_db, cfg, db_set, texte_refuse, controle, est_staff, journal, salon_ticket=None, log=None):
    """`texte_refuse(g, texte)` → raison ou "" ; `controle(membre, cfg)` → raison ou "" ;
    `est_staff(g, membre)` (async) ; `journal(g, type_, texte, membre_id=, auteur_id=)` ;
    `salon_ticket(g)` → le salon où s'ouvrent les tickets, ou None."""
    global _get_db, _cfg, _db_set, _texte_refuse, _controle, _est_staff, _journal, _salon_ticket, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    _texte_refuse, _controle, _est_staff, _journal = texte_refuse, controle, est_staff, journal
    _salon_ticket = salon_ticket
    _log = log or print


def set_retour(fn):
    global _retour
    _retour = fn


def _verrou(cle):
    return _verrous.setdefault(cle, asyncio.Lock())


# ═══════════════════════════════════════════════════════════════════════════════
#  Données
# ═══════════════════════════════════════════════════════════════════════════════

_COLONNES = ("id", "guild_id", "zone", "auteur_id", "titre", "champs", "statut", "salon_id", "fil_id",
             "aidants", "cree", "maj", "ferme", "ferme_par", "certifie_par", "credites", "partenaire_id",
             "appel_mm", "supprime")
_SQL_UNE = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants, cree,"
            " maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime"
            " FROM entraide_demandes WHERE id=?")
_SQL_OUVERTES = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants,"
                 " cree, maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime"
                 " FROM entraide_demandes WHERE guild_id=? AND statut IN ('ouverte', 'prise')"
                 " AND fil_id>0 ORDER BY id LIMIT 300")
_SQL_DE_L_AUTEUR = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants,"
                    " cree, maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime"
                    " FROM entraide_demandes WHERE guild_id=? AND auteur_id=? AND statut IN ('ouverte', 'prise')"
                    " AND fil_id>0")
_SQL_A_EFFACER = ("SELECT id, guild_id, zone, auteur_id, titre, champs, statut, salon_id, fil_id, aidants,"
                  " cree, maj, ferme, ferme_par, certifie_par, credites, partenaire_id, appel_mm, supprime"
                  " FROM entraide_demandes WHERE guild_id=? AND statut NOT IN ('ouverte', 'prise')"
                  " AND supprime=0 AND ferme>0 AND ferme<? ORDER BY ferme LIMIT ?")


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS entraide_demandes ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, zone TEXT NOT NULL,"
            " auteur_id INTEGER NOT NULL, titre TEXT NOT NULL, champs TEXT NOT NULL DEFAULT '[]',"
            " statut TEXT NOT NULL DEFAULT 'ouverte', salon_id INTEGER NOT NULL DEFAULT 0,"
            " fil_id INTEGER NOT NULL DEFAULT 0, aidants TEXT NOT NULL DEFAULT '[]',"
            " cree INTEGER NOT NULL, maj INTEGER NOT NULL, ferme INTEGER NOT NULL DEFAULT 0,"
            " ferme_par INTEGER NOT NULL DEFAULT 0, certifie_par INTEGER NOT NULL DEFAULT 0,"
            " credites TEXT NOT NULL DEFAULT '[]', partenaire_id INTEGER NOT NULL DEFAULT 0,"
            " appel_mm INTEGER NOT NULL DEFAULT 0, supprime INTEGER NOT NULL DEFAULT 0)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entraide_statut ON entraide_demandes(guild_id, statut)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entraide_auteur ON entraide_demandes(guild_id, auteur_id, statut)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entraide_fil ON entraide_demandes(fil_id)")
        await db.commit()


def _ligne(r) -> dict:
    d = dict(zip(_COLONNES, r))
    for k in ("champs", "aidants", "credites"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except (TypeError, ValueError):
            d[k] = []
    return d


async def charger(did: int):
    async with _get_db() as db:
        async with db.execute(_SQL_UNE, (int(did),)) as cur:
            r = await cur.fetchone()
    return _ligne(r) if r else None


async def _lignes(sql: str, args: tuple) -> list:
    async with _get_db() as db:
        async with db.execute(sql, args) as cur:
            return [_ligne(r) for r in await cur.fetchall()]


async def _ecrire(sql: str, args: tuple) -> None:
    async with _get_db() as db:
        await db.execute(sql, args)
        await db.commit()


async def reputation(guild_id: int, membre_id: int) -> int:
    """Échanges certifiés par un middleman, comme vendeur ou comme acheteur."""
    async with _get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM entraide_demandes WHERE guild_id=? AND zone='trade'"
                              " AND statut='terminee' AND (auteur_id=? OR partenaire_id=?)",
                              (int(guild_id), int(membre_id), int(membre_id))) as cur:
            return int((await cur.fetchone())[0])


async def compter_ouvertes(guild_id: int) -> dict:
    async with _get_db() as db:
        async with db.execute("SELECT zone, COUNT(*) FROM entraide_demandes WHERE guild_id=?"
                              " AND statut IN ('ouverte', 'prise') AND fil_id>0 GROUP BY zone",
                              (int(guild_id),)) as cur:
            return {z: int(n) for z, n in await cur.fetchall()}


# ═══════════════════════════════════════════════════════════════════════════════
#  Réglages
# ═══════════════════════════════════════════════════════════════════════════════

async def conf(g) -> dict:
    c = await _cfg(g.id)
    return {"actif": bool(c.get("rs_actif")), "categorie": int(c.get("rs_categorie", 0) or 0),
            "salons": dict(c.get("rs_salons") or {}), "roles": dict(c.get("rs_roles") or {}),
            "panneaux": dict(c.get("rs_panneaux") or {}), "orientation": int(c.get("rs_orientation", 0) or 0),
            "orientation_v": str(c.get("rs_orientation_v", "") or ""), "reglages": dict(c.get("rs_reglages") or {})}


def ids_salons(c: dict) -> set:
    """Les salons de l'entraide, pour qu'aucun réglage de masse ne touche à leurs droits."""
    ids = {int(v) for v in (c.get("rs_salons") or {}).values() if str(v).isdigit()}
    return ids | ({int(c["rs_categorie"])} if str(c.get("rs_categorie", "")).isdigit() else set())


def salon(g, cf: dict, cle: str):
    return g.get_channel(int(cf["salons"].get(cle, 0) or 0))


def role_zone(g, cf: dict, cle: str):
    return g.get_role(int(cf["roles"].get(cle, 0) or 0))


def expire_h(cf: dict, z: Zone) -> int:
    v = (cf["reglages"].get("expire") or {}).get(z.cle)
    return int(v) if str(v).isdigit() and int(v) > 0 else z.expire_h


def garder_h(cf: dict) -> int:
    v = cf["reglages"].get("garder_h")
    return int(v) if str(v).isdigit() and int(v) > 0 else GARDER_H


def prevenir(cf: dict, z: Zone) -> bool:
    return z.certif == "guide" and bool((cf["reglages"].get("ping") or {}).get(z.cle, True))


async def _regler(g, cle: str, valeur) -> None:
    cf = await conf(g)
    reglages = cf["reglages"]
    reglages[cle] = valeur
    await _db_set(g.id, "rs_reglages", reglages)


# ═══════════════════════════════════════════════════════════════════════════════
#  Textes et cartes
# ═══════════════════════════════════════════════════════════════════════════════

def _echapper(t) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(t or "")))


def _mention(uid) -> str:
    return f"<@{int(uid)}>"


def _une_ligne(t: str) -> str:
    return " ".join(str(t or "").split())


def titre_de(z: Zone, valeurs: dict) -> str:
    return _une_ligne(z.titre.format(**{c.cle: valeurs.get(c.cle, "") for c in z.champs}))[:90]


def nom_du_fil(auteur, titre: str) -> str:
    return _une_ligne(f"{titre} · {getattr(auteur, 'display_name', '') or 'membre'}")[:100]


def verifier(z: Zone, valeurs: dict) -> str:
    for c in z.champs:
        v = valeurs.get(c.cle, "")
        if c.requis and not v.strip():
            return f"« {c.libelle} » est obligatoire."
        if len(v) > c.max:
            return f"« {c.libelle} » est trop long."
    return ""


def _ligne_statut(d: dict, z: Zone, garder: int = GARDER_H) -> str:
    lib, pastille = STATUTS.get(d["statut"], (d["statut"], "•"))
    if d["statut"] in OUVERTS:
        if not d["aidants"]:
            return f"{pastille} **{lib}** · personne pour l'instant"
        mot = "intéressé(s)" if z.cle == "trade" else "en route"
        return f"{pastille} **{lib}** · {mot} : " + ", ".join(_mention(a) for a in d["aidants"][:MAX_AIDANTS])
    fin = f"\n-# Ce fil disparaît <t:{d['ferme'] + garder * 3600}:R>." if d["ferme"] and not d["supprime"] else ""
    if d["statut"] == "terminee":
        quoi = "Échange certifié" if z.cle == "trade" else "Aide certifiée"
        s = f"✅ **{quoi}** par {_mention(d['certifie_par'])} · <t:{d['ferme']}:R>"
        if z.cle == "trade" and d["partenaire_id"]:
            s += f"\n-# Échange avec {_mention(d['partenaire_id'])}"
        elif d["credites"]:
            s += "\n-# Ont aidé : " + ", ".join(_mention(x) for x in d["credites"])
        return s + fin
    if d["statut"] == "expiree":
        return "⌛ **Fermée** · plus d'activité" + fin
    if d["statut"] == "retiree":
        return "🗑️ **Retirée** par le staff" + fin
    par = f" par {_mention(d['ferme_par'])}" if d["ferme_par"] and d["ferme_par"] != d["auteur_id"] else ""
    return f"🔒 **Fermée**{par} · <t:{d['ferme']}:R>" + fin


def vue_carte(d: dict, z: Zone, *, avatar: str = "", ping: str = "", rep: int | None = None,
              garder: int = GARDER_H) -> LayoutView:
    ouvert = d["statut"] in OUVERTS
    entete = [discord.ui.TextDisplay(f"### {z.emoji} {z.nom} · n°{d['id']}"),
              discord.ui.TextDisplay(f"{_mention(d['auteur_id'])} · <t:{d['cree']}:R>")]
    items = [discord.ui.Section(*entete, accessory=discord.ui.Thumbnail(avatar))] if avatar else list(entete)
    lignes = [f"**{lib}** · {_echapper(v)}" for lib, v in d["champs"] if str(v or "").strip()]
    if lignes:
        items.append(discord.ui.TextDisplay("\n".join(lignes)))
    if z.cle == "trade" and ouvert:
        confiance = "premier échange certifié à venir" if not rep else f"{rep} échange(s) certifié(s)"
        items.append(discord.ui.TextDisplay(f"-# 🛡️ {confiance} · avec un inconnu, ne donne jamais en "
                                            "premier : appelle un middleman"))
    items.append(discord.ui.Separator())
    items.append(discord.ui.TextDisplay(_ligne_statut(d, z, garder)))
    if ouvert:
        boutons = [BoutonRejoindre(d["id"], z)]
        if z.cle == "trade":
            boutons.append(BoutonMiddleman(d["id"]))
        if z.certif:
            boutons.append(BoutonCertifier(d["id"], z))
        boutons.append(BoutonFermer(d["id"]))
        items.append(discord.ui.ActionRow(*boutons))
        if ping:
            items.append(discord.ui.TextDisplay(f"-# Guides prévenus : {ping}"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(z.couleur) if ouvert else Palette.NEUTRAL))
    return v


def vue_panneau(z: Zone, cf: dict, g=None) -> LayoutView:
    r = role_zone(g, cf, z.cle) if g is not None and z.role else None
    pied = ["une demande à la fois", f"fermée après {expire_h(cf, z)} h sans activité"]
    if r is not None:
        pied.append(f"{'middlemen' if z.certif == 'middleman' else 'guides'} : {r.mention}")
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        visuels.bandeau(f"rs_{z.cle}", f"{z.emoji} {z.nom}"),
        discord.ui.TextDisplay(z.consigne),
        discord.ui.TextDisplay("-# " + " · ".join(pied)),
        discord.ui.ActionRow(BoutonNouvelle(z.cle)),
        accent_color=discord.Color(z.couleur)))
    return v


def vue_orientation(g, cf: dict, ouvertes: dict | None = None):
    """Une ligne par zone et un bouton qui y mène — une ligne n'apparaît que si son salon existe."""
    ouvertes = ouvertes or {}
    lignes = [(salon(g, cf, "discussion"), "💬", "Discussion", "Parler du jeu", None)]
    lignes += [(salon(g, cf, z.cle), z.emoji, z.nom, z.phrase, ouvertes.get(z.cle, 0)) for z in ZONES.values()]
    ticket = _salon_ticket(g) if _salon_ticket else None
    lignes.append((ticket, "🎫", "Un souci avec un joueur ?", "Ouvre un ticket : le staff répond en privé", None))
    items = [visuels.bandeau("rs_port", "Entraide Rell Seas"),
             discord.ui.TextDisplay("Choisis ta zone : le bouton t'y emmène.")]
    for ch, emoji, nom, phrase, n in lignes:
        if ch is None:
            continue
        compte = "" if n is None else (" · aucune demande en cours" if not n else f" · {n} demande(s) en cours")
        items.append(discord.ui.Section(discord.ui.TextDisplay(f"{emoji} **{nom}**\n-# {phrase}{compte}"),
                                        accessory=Button(label="Y aller", url=ch.jump_url)))
    items.append(discord.ui.TextDisplay("-# Respect · une demande à la fois par zone · les guides certifient "
                                        "l'aide · jamais d'échange sans middleman avec un inconnu"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(0x0EA5E9)))
    signature = "1|" + "|".join(f"{getattr(ch, 'id', 0)}:{n}" for ch, _e, _no, _p, n in lignes)
    return v, signature


# ═══════════════════════════════════════════════════════════════════════════════
#  Fils
# ═══════════════════════════════════════════════════════════════════════════════

def _horodatage(snowflake) -> float:
    return discord.utils.snowflake_time(int(snowflake)).timestamp() if snowflake else 0.0


async def _fil(g, d: dict):
    """Le fil d'une demande (archivé compris), ou None s'il n'existe plus. Une panne réseau n'est
    pas une disparition : elle lève."""
    fid = int(d.get("fil_id") or 0)
    if not fid:
        return None
    fil = g.get_channel_or_thread(fid)
    if fil is not None:
        return fil
    try:
        return await g.fetch_channel(fid)
    except discord.NotFound:
        return None


async def _fil_ou_rien(g, d: dict):
    """Pour les interactions : une panne réseau ne doit pas laisser le membre sans réponse."""
    try:
        return await _fil(g, d)
    except discord.HTTPException as ex:
        _log(f"[ENTRAIDE:DETAIL] lecture du fil demande={d['id']} {type(ex).__name__} {ex}")
        return None


def _porteur(fil):
    """Le salon qui porte la carte : le post lui-même (forum) ou le salon sous lequel pend le fil."""
    parent = getattr(fil, "parent", None)
    return fil if isinstance(parent, discord.ForumChannel) or parent is None else parent


def _tags(forum, statut: str) -> list:
    nom = ETIQUETTE.get(statut, "Fermée")
    t = discord.utils.get(getattr(forum, "available_tags", []) or [], name=nom)
    return [t] if t is not None else []


async def _maj_carte(g, d: dict, fil=None) -> None:
    z = ZONES.get(d["zone"])
    fil = fil or await _fil_ou_rien(g, d)
    if z is None or fil is None:
        return
    cf = await conf(g)
    auteur = g.get_member(int(d["auteur_id"]))
    rep = await reputation(g.id, d["auteur_id"]) if z.cle == "trade" else None
    vue = vue_carte(d, z, avatar=auteur.display_avatar.url if auteur else "", rep=rep, garder=garder_h(cf))
    try:
        await _porteur(fil).get_partial_message(fil.id).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
    except discord.NotFound:
        pass
    except discord.HTTPException as ex:
        _log("[ENTRAIDE][E2] carte non mise à jour")
        _log(f"[ENTRAIDE][E2:DETAIL] demande={d['id']} {type(ex).__name__} {ex}")


async def _clore_sur_discord(g, d: dict, note: str = "") -> None:
    """La carte d'abord (un message d'un fil archivé ne s'édite plus), puis le mot de fin, puis le
    fil verrouillé et archivé — étiquette comprise, en un seul appel."""
    fil = await _fil_ou_rien(g, d)
    if fil is None:
        return
    await _maj_carte(g, d, fil)
    if note:
        try:
            await fil.send(note, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] mot de fin demande={d['id']} {ex}")
    reglage = {"locked": True, "archived": True}
    if isinstance(fil.parent, discord.ForumChannel):
        reglage["applied_tags"] = _tags(fil.parent, d["statut"])
    try:
        await fil.edit(**reglage)
    except discord.HTTPException as ex:
        _log("[ENTRAIDE][E3] fil non archivé")
        _log(f"[ENTRAIDE][E3:DETAIL] demande={d['id']} {type(ex).__name__} {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Publier
# ═══════════════════════════════════════════════════════════════════════════════

async def peut_publier(i, z: Zone) -> str:
    g, m = i.guild, i.user
    if g is None or getattr(m, "guild_permissions", None) is None:
        return "L'entraide se fait sur le serveur."
    cf = await conf(g)
    if not cf["actif"] or salon(g, cf, z.cle) is None:
        return "Cette zone est fermée pour le moment."
    if m.is_timed_out():
        return "Pas de demande pendant une exclusion temporaire."
    return await _controle(m, await _cfg(g.id)) or await limite(g, m, z)


async def limite(g, m, z: Zone) -> str:
    if await _est_staff(g, m):
        return ""
    t0 = _creations.get((g.id, m.id))
    if t0 is not None and time.monotonic() - t0 < ATTENTE_S:
        return "Attends deux minutes entre deux demandes."
    ouvertes = await _lignes(_SQL_DE_L_AUTEUR, (g.id, m.id))
    ici = next((d for d in ouvertes if d["zone"] == z.cle), None)
    if ici is not None:
        fil = g.get_channel_or_thread(int(ici["fil_id"] or 0))
        lien = f" : {fil.jump_url}" if fil is not None else ""
        return f"Tu as déjà une demande ouverte ici{lien}. Ferme-la avant d'en publier une autre."
    if len(ouvertes) >= MAX_OUVERTES:
        return f"Tu as déjà {MAX_OUVERTES} demandes ouvertes. Ferme-en une d'abord."
    return ""


class Formulaire(discord.ui.Modal):
    def __init__(self, z: Zone, valeurs: dict | None = None):
        super().__init__(title=f"{z.emoji} {z.nom} · nouvelle demande"[:45], timeout=900)
        self.zone, self.entrees = z, {}
        valeurs = valeurs or {}
        for c in z.champs[:5]:
            t = discord.ui.TextInput(style=discord.TextStyle.paragraph if c.long else discord.TextStyle.short,
                                     max_length=c.max, required=c.requis, placeholder=c.aide[:100] or None,
                                     default=valeurs.get(c.cle) or None)
            self.entrees[c.cle] = t
            self.add_item(discord.ui.Label(text=c.libelle[:45], component=t,
                                           description=None if c.requis else "Facultatif"))

    async def on_submit(self, i: discord.Interaction):
        await publier(i, self.zone, {k: (t.value or "").strip() for k, t in self.entrees.items()})


def vue_corriger(auteur_id: int, z: Zone, erreur: str, valeurs: dict) -> LayoutView:
    v = LayoutView(timeout=900)
    b = Button(label="Corriger", style=discord.ButtonStyle.primary, emoji=visuels.icone("modifier"))

    async def _cb(i: discord.Interaction):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.send_modal(Formulaire(z, valeurs))
    b.callback = _cb
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(erreur), discord.ui.ActionRow(b),
                                    accent_color=Palette.WARNING))
    return v


async def publier(i, z: Zone, valeurs: dict):
    g, m = i.guild, i.user
    valeurs = {c.cle: (valeurs.get(c.cle, "") if c.long else _une_ligne(valeurs.get(c.cle, ""))) for c in z.champs}
    erreur = verifier(z, valeurs) or await _texte_refuse(g, "\n".join(v for v in valeurs.values() if v))
    if erreur:
        return await i.response.send_message(view=vue_corriger(m.id, z, erreur, valeurs), ephemeral=True)
    refus = await peut_publier(i, z)
    if refus:
        return await i.response.send_message(refus, ephemeral=True)
    await i.response.defer(ephemeral=True, thinking=True)
    titre = titre_de(z, valeurs)
    async with _verrou(("publier", g.id)):
        refus = await limite(g, m, z)
        if refus:
            return await i.followup.send(refus, ephemeral=True)
        t = int(time.time())
        champs = [[c.libelle, valeurs.get(c.cle, "")] for c in z.champs]
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT INTO entraide_demandes(guild_id, zone, auteur_id, titre, champs, cree, maj)"
                " VALUES(?,?,?,?,?,?,?)", (g.id, z.cle, m.id, titre, json.dumps(champs, ensure_ascii=False), t, t))
            did = cur.lastrowid
            await db.commit()
        _creations[(g.id, m.id)] = time.monotonic()
    cf = await conf(g)
    ch = salon(g, cf, z.cle)
    d = await charger(did)
    role = role_zone(g, cf, z.cle) if prevenir(cf, z) else None
    if role is not None and not (role.mentionable or g.me.guild_permissions.mention_everyone):
        role = None
    rep = await reputation(g.id, m.id) if z.cle == "trade" else None
    vue = vue_carte(d, z, avatar=m.display_avatar.url, ping=role.mention if role else "", rep=rep,
                    garder=garder_h(cf))
    mentions = discord.AllowedMentions(everyone=False, users=False, roles=[role] if role else False)
    try:
        if isinstance(ch, discord.ForumChannel):
            fil = (await ch.create_thread(name=nom_du_fil(m, titre), view=vue, allowed_mentions=mentions,
                                          applied_tags=_tags(ch, "ouverte"),
                                          reason=f"Entraide : demande n°{did}")).thread
        elif isinstance(ch, discord.TextChannel):
            carte = await ch.send(view=vue, allowed_mentions=mentions)
            fil = await carte.create_thread(name=nom_du_fil(m, titre), auto_archive_duration=ARCHIVE_MIN,
                                            reason=f"Entraide : demande n°{did}")
        else:
            raise discord.ClientException("zone sans salon")
    except (discord.HTTPException, discord.ClientException) as ex:
        _log("[ENTRAIDE][E1] demande non publiée")
        _log(f"[ENTRAIDE][E1:DETAIL] zone={z.cle} {type(ex).__name__} {ex}")
        await _ecrire("DELETE FROM entraide_demandes WHERE id=?", (did,))
        _creations.pop((g.id, m.id), None)
        return await i.followup.send("Impossible de publier ta demande pour le moment.", ephemeral=True)
    await _ecrire("UPDATE entraide_demandes SET salon_id=?, fil_id=? WHERE id=?", (ch.id, fil.id, did))
    try:
        await fil.add_user(m)  # l'auteur suit son fil : il est prévenu de chaque réponse
    except discord.HTTPException as ex:
        _log(f"[ENTRAIDE:DETAIL] auteur non ajouté au fil demande={did} {ex}")
    await i.followup.send(f"Demande publiée : {fil.jump_url}", ephemeral=True)
    if isinstance(ch, discord.TextChannel):
        asyncio.create_task(reposer_panneau_texte(g, z))
    await _journal(g, "entraide.demande", f"{m.mention} a publié une demande · {z.nom} : {titre}",
                   membre_id=m.id)


class BoutonNouvelle(discord.ui.DynamicItem[Button], template=r"rs:n:(?P<zone>[a-z]+)"):
    def __init__(self, zone: str):
        self.zone = zone
        super().__init__(Button(label="Publier une demande", style=discord.ButtonStyle.primary,
                                emoji=visuels.icone("ajouter"), custom_id=f"rs:n:{zone}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["zone"])

    async def callback(self, i: discord.Interaction):
        z = ZONES.get(self.zone)
        if z is None:
            return await i.response.send_message("Cette zone n'existe plus.", ephemeral=True)
        refus = await peut_publier(i, z)
        if refus:
            return await i.response.send_message(refus, ephemeral=True)
        await i.response.send_modal(Formulaire(z))


# ═══════════════════════════════════════════════════════════════════════════════
#  Rejoindre, appeler un middleman
# ═══════════════════════════════════════════════════════════════════════════════

async def _demande_ouverte(i, did: int):
    d = await charger(did)
    if d is None or i.guild is None or d["guild_id"] != i.guild.id:
        await i.followup.send("Demande introuvable.", ephemeral=True)
        return None
    if d["statut"] not in OUVERTS:
        await i.followup.send("Cette demande est close.", ephemeral=True)
        return None
    return d


async def rejoindre(i, did: int):
    await i.response.defer(ephemeral=True)
    g, m = i.guild, i.user
    async with _verrou(("demande", did)):
        d = await _demande_ouverte(i, did)
        if d is None:
            return
        z = ZONES[d["zone"]]
        if m.id == d["auteur_id"]:
            return await i.followup.send("C'est ta demande : attends qu'un joueur se manifeste.", ephemeral=True)
        fil = g.get_channel_or_thread(int(d["fil_id"]))
        lien = f" {fil.jump_url}" if fil is not None else ""
        if m.id in d["aidants"]:
            return await i.followup.send(f"Tu es déjà dessus.{lien}", ephemeral=True)
        if len(d["aidants"]) >= MAX_AIDANTS:
            return await i.followup.send("Il y a déjà assez de monde sur cette demande.", ephemeral=True)
        d["aidants"].append(m.id)
        d["statut"], d["maj"] = "prise", int(time.time())
        await _ecrire("UPDATE entraide_demandes SET aidants=?, statut=?, maj=? WHERE id=?",
                      (json.dumps(d["aidants"]), d["statut"], d["maj"], did))
    fil = await _fil_ou_rien(g, d)
    if fil is not None:
        await _maj_carte(g, d, fil)
        try:
            if isinstance(fil.parent, discord.ForumChannel):
                await fil.edit(applied_tags=_tags(fil.parent, "prise"))
            await fil.add_user(m)
            await fil.send(z.annonce.format(qui=m.mention, auteur=_mention(d["auteur_id"])),
                           allowed_mentions=discord.AllowedMentions(users=[discord.Object(d["auteur_id"])]))
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] annonce demande={did} {ex}")
    await i.followup.send(f"C'est noté, rendez-vous dans le fil.{lien}", ephemeral=True)


class BoutonRejoindre(discord.ui.DynamicItem[Button], template=r"rs:j:(?P<did>\d+)"):
    def __init__(self, did: int, z: Zone | None = None):
        self.did = int(did)
        z = z or ZONES["aide"]
        super().__init__(Button(label=z.rejoindre, style=discord.ButtonStyle.success,
                                emoji=visuels.icone(z.icone_rejoindre), custom_id=f"rs:j:{int(did)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["did"]))

    async def callback(self, i: discord.Interaction):
        await rejoindre(i, self.did)


async def appeler_middleman(i, did: int):
    await i.response.defer(ephemeral=True)
    g, m = i.guild, i.user
    async with _verrou(("demande", did)):
        d = await _demande_ouverte(i, did)
        if d is None:
            return
        if m.id != d["auteur_id"] and m.id not in d["aidants"]:
            return await i.followup.send("Seuls l'auteur et les intéressés appellent un middleman.", ephemeral=True)
        t = int(time.time())
        if t - int(d["appel_mm"] or 0) < APPEL_MM_S:
            return await i.followup.send("Un middleman a déjà été appelé il y a peu.", ephemeral=True)
        cf = await conf(g)
        role = role_zone(g, cf, "trade")
        if role is None or not role.members:
            return await i.followup.send("Aucun middleman n'est désigné pour le moment.", ephemeral=True)
        fil = await _fil_ou_rien(g, d)
        if fil is None:
            return await i.followup.send("Le fil de cet échange est introuvable pour le moment.", ephemeral=True)
        try:
            await fil.send(f"🛡️ {role.mention} — {m.mention} demande un middleman pour cet échange.",
                           allowed_mentions=discord.AllowedMentions(roles=[role]))
        except discord.HTTPException as ex:
            _log("[ENTRAIDE][E4] middleman non appelé")
            _log(f"[ENTRAIDE][E4:DETAIL] demande={did} {ex}")
            return await i.followup.send("Impossible de prévenir les middlemen pour le moment.", ephemeral=True)
        await _ecrire("UPDATE entraide_demandes SET appel_mm=? WHERE id=?", (t, did))
    await i.followup.send("Middlemen prévenus : attends-en un avant d'échanger.", ephemeral=True)


class BoutonMiddleman(discord.ui.DynamicItem[Button], template=r"rs:m:(?P<did>\d+)"):
    def __init__(self, did: int):
        self.did = int(did)
        super().__init__(Button(label="Middleman", style=discord.ButtonStyle.secondary,
                                emoji=visuels.icone("bouclier"), custom_id=f"rs:m:{int(did)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["did"]))

    async def callback(self, i: discord.Interaction):
        await appeler_middleman(i, self.did)


# ═══════════════════════════════════════════════════════════════════════════════
#  Certifier, fermer
# ═══════════════════════════════════════════════════════════════════════════════

async def peut_certifier(g, m, d: dict) -> str:
    z = ZONES.get(d["zone"])
    if z is None or not z.certif:
        return "Cette zone ne se certifie pas : l'auteur ferme sa demande."
    staff = await _est_staff(g, m)
    role = role_zone(g, await conf(g), z.cle)
    if not staff and (role is None or role not in getattr(m, "roles", [])):
        qui = "middlemen" if z.certif == "middleman" else f"guides de la zone {z.nom}"
        return f"Réservé aux {qui}" + (f" ({role.mention})." if role else ".")
    if m.id == d["auteur_id"] and not staff:
        return "Tu ne peux pas certifier ta propre demande."
    return ""


async def certifier(g, did: int, par, credites: list, partenaire: int = 0) -> str:
    async with _verrou(("demande", did)):
        d = await charger(did)
        if d is None or d["statut"] not in OUVERTS:
            return "Cette demande est déjà close."
        t = int(time.time())
        credites = [int(x) for x in dict.fromkeys(credites) if int(x) != d["auteur_id"]][:MAX_AIDANTS]
        d.update(statut="terminee", ferme=t, ferme_par=par.id, certifie_par=par.id, credites=credites,
                 partenaire_id=int(partenaire or 0), maj=t)
        await _ecrire("UPDATE entraide_demandes SET statut=?, ferme=?, ferme_par=?, certifie_par=?, credites=?,"
                      " partenaire_id=?, maj=? WHERE id=?",
                      (d["statut"], t, par.id, par.id, json.dumps(credites), d["partenaire_id"], t, did))
    z = ZONES[d["zone"]]
    if z.cle == "trade":
        note = f"✅ Échange certifié par {par.mention}" + (
            f" — avec {_mention(d['partenaire_id'])}." if d["partenaire_id"] else ".")
    else:
        note = f"✅ Aide certifiée par {par.mention}" + (
            " — merci à " + ", ".join(_mention(x) for x in credites) + " !" if credites else ".")
    await _clore_sur_discord(g, d, note)
    aides = (" — aidé par " + ", ".join(_mention(x) for x in credites)) if credites and z.cle != "trade" else ""
    await _journal(g, "entraide.certifiee", f"{par.mention} a certifié la demande de {_mention(d['auteur_id'])}"
                                            f" · {z.nom} : {d['titre']}{aides}",
                   membre_id=d["auteur_id"], auteur_id=par.id)
    return ""


async def fermer(g, did: int, par_id: int, statut: str = "fermee", note: str = "",
                 maintenant: float | None = None) -> bool:
    async with _verrou(("demande", did)):
        d = await charger(did)
        if d is None or d["statut"] not in OUVERTS:
            return False
        t = int(maintenant or time.time())
        d.update(statut=statut, ferme=t, ferme_par=int(par_id or 0), maj=t)
        await _ecrire("UPDATE entraide_demandes SET statut=?, ferme=?, ferme_par=?, maj=? WHERE id=?",
                      (statut, t, d["ferme_par"], t, did))
    await _clore_sur_discord(g, d, note)
    if par_id and par_id != d["auteur_id"]:
        await _journal(g, "entraide.fermee", f"{_mention(par_id)} a fermé la demande de "
                                             f"{_mention(d['auteur_id'])} · {ZONES[d['zone']].nom} : {d['titre']}",
                       membre_id=d["auteur_id"], auteur_id=par_id)
    return True


class VueCertifier(LayoutView):
    """Qui a aidé (ou avec qui l'échange s'est fait) — la liste est déjà cochée, on corrige au besoin."""

    def __init__(self, d: dict, z: Zone, par):
        super().__init__(timeout=300)
        self.d, self.z, self.par, self.choisis = d, z, par, None
        echange = z.cle == "trade"
        defauts = [discord.Object(id=int(x)) for x in d["aidants"][:1 if echange else MAX_AIDANTS]]
        self.qui = UserSelect(placeholder="Avec qui l'échange s'est fait ?" if echange else "Qui a aidé ?",
                              min_values=0, max_values=1 if echange else MAX_AIDANTS, default_values=defauts)
        self.qui.callback = self._cb_qui
        ok = Button(label="Certifier l'échange" if echange else "Certifier l'aide",
                    style=discord.ButtonStyle.success, emoji=visuels.icone("valider"))
        ok.callback = self._cb_ok
        non = Button(label="Annuler", style=discord.ButtonStyle.secondary, emoji=visuels.icone("annuler"))
        non.callback = self._cb_non
        texte = ("Certifier cet échange ? La demande se ferme et compte dans la confiance des deux joueurs."
                 if echange else "Certifier que l'aide a été faite ? La demande se ferme ; les joueurs cochés "
                                 "sont remerciés.")
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"### {z.emoji} Certifier · n°{d['id']}\n{texte}"),
            discord.ui.ActionRow(self.qui), discord.ui.ActionRow(ok, non), accent_color=Palette.SUCCESS))

    async def interaction_check(self, i):
        return i.user.id == self.par.id

    async def _cb_qui(self, i):
        self.choisis = [u.id for u in self.qui.values]
        await i.response.defer()

    async def _cb_ok(self, i):
        await i.response.defer()
        choisis = self.choisis if self.choisis is not None else [int(x) for x in self.d["aidants"]]
        if self.z.cle == "trade":
            erreur = await certifier(i.guild, self.d["id"], i.user, [], partenaire=(choisis or [0])[0])
        else:
            erreur = await certifier(i.guild, self.d["id"], i.user, choisis)
        await i.edit_original_response(view=_vue_message(erreur or "Certifié ✅", Palette.WARNING if erreur
                                                         else Palette.SUCCESS))

    async def _cb_non(self, i):
        await i.response.edit_message(view=_vue_message("Rien n'a changé.", Palette.NEUTRAL))


def _vue_message(texte: str, couleur) -> LayoutView:
    v = LayoutView(timeout=60)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), accent_color=couleur))
    return v


def vue_confirmer(texte: str, libelle: str, action, auteur_id: int, *, icone: str = "verrou",
                  style=discord.ButtonStyle.danger) -> LayoutView:
    """OUI / NON, tout en bas : jamais une action finale sur un mauvais clic."""
    v = LayoutView(timeout=300)
    oui = Button(label=libelle, style=style, emoji=visuels.icone(icone))
    non = Button(label="Annuler", style=discord.ButtonStyle.secondary, emoji=visuels.icone("annuler"))

    async def _oui(i):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.defer()
        texte_fin = await action(i)
        await i.edit_original_response(view=_vue_message(texte_fin, Palette.NEUTRAL))

    async def _non(i):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.edit_message(view=_vue_message("Rien n'a changé.", Palette.NEUTRAL))
    oui.callback, non.callback = _oui, _non
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), discord.ui.ActionRow(oui, non),
                                    accent_color=Palette.WARNING))
    return v


class BoutonCertifier(discord.ui.DynamicItem[Button], template=r"rs:c:(?P<did>\d+)"):
    def __init__(self, did: int, z: Zone | None = None):
        self.did = int(did)
        qui = "middleman" if z is not None and z.certif == "middleman" else "guide"
        super().__init__(Button(label=f"Certifier · {qui}", style=discord.ButtonStyle.primary,
                                emoji=visuels.icone("valider"), custom_id=f"rs:c:{int(did)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["did"]))

    async def callback(self, i: discord.Interaction):
        d = await charger(self.did)
        if d is None or i.guild is None or d["guild_id"] != i.guild.id:
            return await i.response.send_message("Demande introuvable.", ephemeral=True)
        if d["statut"] not in OUVERTS:
            return await i.response.send_message("Cette demande est close.", ephemeral=True)
        refus = await peut_certifier(i.guild, i.user, d)
        if refus:
            return await i.response.send_message(refus, ephemeral=True,
                                                 allowed_mentions=discord.AllowedMentions.none())
        await i.response.send_message(view=VueCertifier(d, ZONES[d["zone"]], i.user), ephemeral=True)


class BoutonFermer(discord.ui.DynamicItem[Button], template=r"rs:f:(?P<did>\d+)"):
    def __init__(self, did: int):
        self.did = int(did)
        super().__init__(Button(label="Fermer", style=discord.ButtonStyle.secondary,
                                emoji=visuels.icone("verrou"), custom_id=f"rs:f:{int(did)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["did"]))

    async def callback(self, i: discord.Interaction):
        g, m = i.guild, i.user
        d = await charger(self.did)
        if d is None or g is None or d["guild_id"] != g.id:
            return await i.response.send_message("Demande introuvable.", ephemeral=True)
        if d["statut"] not in OUVERTS:
            return await i.response.send_message("Cette demande est déjà close.", ephemeral=True)
        z = ZONES[d["zone"]]
        role = role_zone(g, await conf(g), z.cle)
        autorise = m.id == d["auteur_id"] or await _est_staff(g, m) or (role is not None and role in m.roles)
        if not autorise:
            return await i.response.send_message("Seuls l'auteur, les guides de la zone et le staff ferment "
                                                 "une demande.", ephemeral=True)
        sienne = m.id == d["auteur_id"]
        did = self.did

        async def _action(_i):
            note = "🔒 Demande fermée par son auteur." if sienne else f"🔒 Demande fermée par {m.mention}."
            ok = await fermer(g, did, m.id, "fermee", note)
            return "Demande fermée." if ok else "Cette demande était déjà close."
        texte = ("Fermer ta demande ? Le fil se verrouille puis disparaît." if sienne
                 else "Fermer cette demande sans certifier l'aide ? Le fil se verrouille puis disparaît.")
        await i.response.send_message(view=vue_confirmer(texte, "Oui, fermer", _action, m.id), ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Entretien : expiration, suppression, panneaux
# ═══════════════════════════════════════════════════════════════════════════════

async def _effacer(g, d: dict) -> None:
    """Le fil (et, hors forum, la carte qui le porte). Une erreur passagère : on réessaiera."""
    try:
        fil = await _fil(g, d)
        if fil is not None:
            parent = fil.parent
            await fil.delete()
            if parent is not None and not isinstance(parent, discord.ForumChannel):
                try:
                    await parent.get_partial_message(int(d["fil_id"])).delete()
                except discord.NotFound:
                    pass
    except discord.Forbidden as ex:
        _log("[ENTRAIDE][E5] fil non supprimé (droits)")
        _log(f"[ENTRAIDE][E5:DETAIL] demande={d['id']} {ex}")
    except discord.HTTPException as ex:
        _log(f"[ENTRAIDE:DETAIL] suppression reportée demande={d['id']} {type(ex).__name__} {ex}")
        return
    await _ecrire("UPDATE entraide_demandes SET supprime=1 WHERE id=?", (d["id"],))


async def entretenir(g, maintenant: float | None = None) -> dict:
    """Toutes les 5 minutes : les demandes sans activité se ferment, les demandes closes disparaissent
    après le délai, l'orientation suit les compteurs, les panneaux restent en place (toutes les 30 min)."""
    cf = await conf(g)
    bilan = {"expirees": 0, "retirees": 0, "effacees": 0}
    if not cf["actif"]:
        return bilan
    t = maintenant or time.time()
    actions = 0
    for d in await _lignes(_SQL_OUVERTES, (g.id,)):
        if actions >= PAR_PASSAGE:
            break
        z = ZONES.get(d["zone"])
        if z is None:
            continue
        try:
            fil = await _fil(g, d)
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] lecture du fil demande={d['id']} {ex}")
            continue
        if fil is None:
            await _ecrire("UPDATE entraide_demandes SET statut='retiree', ferme=?, maj=?, supprime=1 WHERE id=?",
                          (int(t), int(t), d["id"]))
            bilan["retirees"] += 1
            actions += 1
            continue
        derniere = max(float(d["maj"]), _horodatage(getattr(fil, "last_message_id", None)))
        delai = expire_h(cf, z)
        if t - derniere > delai * 3600:
            if await fermer(g, d["id"], 0, "expiree", f"⌛ Fermée faute d'activité depuis {delai} h. "
                                                      "Republie-la si tu as encore besoin.", maintenant=t):
                bilan["expirees"] += 1
                actions += 1
    limite_t = int(t - garder_h(cf) * 3600)
    for d in await _lignes(_SQL_A_EFFACER, (g.id, limite_t, PAR_PASSAGE)):
        await _effacer(g, d)
        bilan["effacees"] += 1
    #  Une publication interrompue (redémarrage entre l'écriture et le fil) ne bloque personne.
    await _ecrire("DELETE FROM entraide_demandes WHERE guild_id=? AND fil_id=0 AND cree<?", (g.id, int(t) - 600))
    await rafraichir_orientation(g)
    if t - _verifies.get(g.id, 0) > 1800:
        _verifies[g.id] = t
        await assurer_panneaux(g)
    return bilan


async def sur_depart(member) -> int:
    """Un membre quitte le serveur : ses demandes ouvertes se ferment."""
    g = member.guild
    n = 0
    for d in await _lignes(_SQL_DE_L_AUTEUR, (g.id, member.id)):
        if await fermer(g, d["id"], 0, "fermee", "🔒 Fermée : son auteur a quitté le serveur."):
            n += 1
    return n


async def rafraichir_orientation(g, forcer: bool = False, verifier_present: bool = False) -> None:
    """Le panneau d'orientation : posé s'il manque, réécrit quand un salon ou un compteur change.
    Ses clés sont à part (`rs_orientation`) : il ne se dispute jamais `rs_panneaux` avec les zones."""
    async with _verrou(("orientation", g.id)):
        cf = await conf(g)
        ch = salon(g, cf, "orientation")
        if not isinstance(ch, discord.TextChannel):
            return
        vue, signature = vue_orientation(g, cf, await compter_ouvertes(g.id))
        mid = cf["orientation"]
        try:
            if mid and not forcer and cf["orientation_v"] == signature:
                if not verifier_present:
                    return
                try:
                    await ch.fetch_message(mid)
                    return
                except discord.NotFound:
                    mid = 0
            if mid:
                try:
                    await ch.get_partial_message(mid).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())
                except discord.NotFound:
                    mid = 0
            if not mid:
                mid = (await ch.send(view=vue, allowed_mentions=discord.AllowedMentions.none())).id
        except discord.HTTPException as ex:
            _log("[ENTRAIDE][E6] orientation non posée")
            _log(f"[ENTRAIDE][E6:DETAIL] {type(ex).__name__} {ex}")
            return
        await _db_set(g.id, "rs_orientation", mid)
        await _db_set(g.id, "rs_orientation_v", signature)


async def _panneau_forum(g, cf: dict, z: Zone, forum, forcer: bool) -> None:
    """Le post épinglé, en tête du forum, avec son bouton « Publier une demande »."""
    tid = int(cf["panneaux"].get(z.cle, 0) or 0)
    fil = None
    if tid:
        fil = g.get_channel_or_thread(tid)
        if fil is None:
            try:
                fil = await g.fetch_channel(tid)
            except discord.NotFound:
                fil = None
    vue = vue_panneau(z, cf, g)
    if fil is None:
        fil = (await forum.create_thread(name=f"📌 Publier une demande · {z.nom}", view=vue,
                                         allowed_mentions=discord.AllowedMentions.none(),
                                         reason="Entraide : panneau de la zone")).thread
        cf["panneaux"][z.cle] = fil.id
        try:
            await fil.edit(pinned=True, locked=True)
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] panneau non épinglé zone={z.cle} {ex}")
        return
    if fil.archived or not fil.locked or not fil.flags.pinned:
        try:
            await fil.edit(archived=False, locked=True, pinned=True)
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] panneau non rétabli zone={z.cle} {ex}")
    if forcer:
        await fil.get_partial_message(fil.id).edit(view=vue, allowed_mentions=discord.AllowedMentions.none())


async def _panneau_texte(g, cf: dict, z: Zone, ch, forcer: bool, reposer: bool = False) -> None:
    """Hors forum : le panneau reste en bas du salon, sous les cartes."""
    mid = int(cf["panneaux"].get(z.cle, 0) or 0)
    if mid and reposer:
        try:
            await ch.get_partial_message(mid).delete()
        except discord.NotFound:
            pass
        mid = 0
    if mid:
        try:
            if forcer:
                await ch.get_partial_message(mid).edit(view=vue_panneau(z, cf, g),
                                                       allowed_mentions=discord.AllowedMentions.none())
            else:
                await ch.fetch_message(mid)
            return
        except discord.NotFound:
            pass
    cf["panneaux"][z.cle] = (await ch.send(view=vue_panneau(z, cf, g),
                                           allowed_mentions=discord.AllowedMentions.none())).id


async def reposer_panneau_texte(g, z: Zone) -> None:
    async with _verrou(("panneaux", g.id)):
        try:
            cf = await conf(g)
            ch = salon(g, cf, z.cle)
            if isinstance(ch, discord.TextChannel):
                await _panneau_texte(g, cf, z, ch, False, reposer=True)
                await _db_set(g.id, "rs_panneaux", cf["panneaux"])
        except discord.HTTPException as ex:
            _log(f"[ENTRAIDE:DETAIL] panneau non reposé zone={z.cle} {ex}")


async def assurer_panneaux(g, forcer: bool = False) -> None:
    async with _verrou(("panneaux", g.id)):
        cf = await conf(g)
        for z in ZONES.values():
            ch = salon(g, cf, z.cle)
            try:
                if isinstance(ch, discord.ForumChannel):
                    await _panneau_forum(g, cf, z, ch, forcer)
                elif isinstance(ch, discord.TextChannel):
                    await _panneau_texte(g, cf, z, ch, forcer)
            except discord.HTTPException as ex:
                _log("[ENTRAIDE][E7] panneau de zone non posé")
                _log(f"[ENTRAIDE][E7:DETAIL] zone={z.cle} {type(ex).__name__} {ex}")
        await _db_set(g.id, "rs_panneaux", cf["panneaux"])
    await rafraichir_orientation(g, forcer=forcer, verifier_present=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Installation
# ═══════════════════════════════════════════════════════════════════════════════

def droits_orientation(g) -> dict:
    return {g.default_role: discord.PermissionOverwrite(
                send_messages=False, add_reactions=False, create_public_threads=False,
                create_private_threads=False, send_messages_in_threads=False),
            g.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, embed_links=True, attach_files=True,
                read_message_history=True, manage_messages=True)}


def droits_zone(g) -> dict:
    """On ne publie que par le bouton ; on parle dans les fils (preuves et captures comprises)."""
    return {g.default_role: discord.PermissionOverwrite(
                send_messages=False, create_public_threads=False, create_private_threads=False,
                send_messages_in_threads=True),
            g.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, send_messages_in_threads=True,
                create_public_threads=True, manage_threads=True, manage_messages=True,
                read_message_history=True, embed_links=True, attach_files=True)}


def sujet(z: Zone, cf: dict) -> str:
    return (f"{z.emoji} {z.phrase}. Publie avec le bouton « Publier une demande » ; on répond dans le fil. "
            f"Une demande à la fois, fermée après {expire_h(cf, z)} h sans activité.")


async def installer(g, *, forum: bool | None = None) -> list:
    """Crée ce qui manque — catégorie, salons, rôles, panneaux — et ne supprime jamais rien.
    Relancer répare : un salon effacé à la main revient. Rend la liste de ce qui a été créé."""
    me = g.me
    p = getattr(me, "guild_permissions", None)
    if not (p and p.manage_channels and p.manage_roles):
        raise PermissionError("Il me faut « Gérer les salons » et « Gérer les rôles ».")
    forum = ("COMMUNITY" in g.features) if forum is None else forum
    faits = []
    async with _verrou(("installer", g.id)):
        cf = await conf(g)
        cat = g.get_channel(cf["categorie"])
        if not isinstance(cat, discord.CategoryChannel):
            cat = await g.create_category(CATEGORIE, reason="Entraide Rell Seas")
            await _db_set(g.id, "rs_categorie", cat.id)
            faits.append(f"catégorie {cat.name}")
        roles = cf["roles"]
        for z in ZONES.values():
            if z.role and role_zone(g, cf, z.cle) is None:
                r = await g.create_role(name=z.role, colour=discord.Colour(z.couleur), mentionable=False,
                                        hoist=False, reason="Entraide Rell Seas : guides de la zone")
                roles[z.cle] = r.id
                await _db_set(g.id, "rs_roles", roles)
                faits.append(f"rôle {r.name}")
        salons = cf["salons"]

        async def _garder(cle, ch):
            salons[cle] = ch.id
            await _db_set(g.id, "rs_salons", salons)
            faits.append(f"salon {ch.name}")
        if salon(g, cf, "orientation") is None:
            await _garder("orientation", await g.create_text_channel(
                ORIENTATION, category=cat, overwrites=droits_orientation(g), reason="Entraide Rell Seas",
                topic="Choisis ta zone : un bouton t'y emmène."))
        if salon(g, cf, "discussion") is None:
            await _garder("discussion", await g.create_text_channel(
                DISCUSSION, category=cat, slowmode_delay=2, reason="Entraide Rell Seas",
                topic="Parler de Rell Seas : îles, fruits, mises à jour, astuces."))
        for z in ZONES.values():
            if salon(g, cf, z.cle) is not None:
                continue
            if forum:
                ch = await g.create_forum(
                    z.salon, category=cat, topic=sujet(z, cf), overwrites=droits_zone(g),
                    default_auto_archive_duration=ARCHIVE_MIN, default_layout=discord.ForumLayoutType.list_view,
                    default_sort_order=discord.ForumOrderType.latest_activity,
                    available_tags=[discord.ForumTag(name=n, emoji=e, moderated=True) for n, e in TAGS],
                    reason="Entraide Rell Seas")
            else:
                ch = await g.create_text_channel(z.salon, category=cat, topic=sujet(z, cf),
                                                 overwrites=droits_zone(g), reason="Entraide Rell Seas")
            await _garder(z.cle, ch)
        await _db_set(g.id, "rs_actif", 1)
    await assurer_panneaux(g, forcer=True)
    return faits


# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration (/configure → Entraide Rell Seas)
# ═══════════════════════════════════════════════════════════════════════════════

class EntraidePanelV2(LayoutView):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g, self._note, self.zone = u, g, "", None

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def render_to(self, i, *, edit: bool = True):
        try:
            cf = await conf(self.g)
            items = [visuels.bandeau("rs_port", "Entraide Rell Seas")]
            installe = cf["actif"] and salon(self.g, cf, "orientation") is not None
            if not installe:
                items.append(discord.ui.TextDisplay(
                    "Pas encore installée.\n-# Une catégorie, sept salons (orientation, discussion, aide, boss, "
                    "farm, trade, chill) et quatre rôles de guide."))
            else:
                ouvertes = await compter_ouvertes(self.g.id)
                forum = isinstance(salon(self.g, cf, "aide"), discord.ForumChannel)
                lignes = [f"🟢 Installée · {'forums' if forum else 'salons et fils'} · "
                          f"{sum(ouvertes.values())} demande(s) en cours"]
                for z in ZONES.values():
                    r = role_zone(self.g, cf, z.cle)
                    qui = f" · {r.mention} ({len(r.members)})" if r else (" · rôle manquant" if z.role else "")
                    ping = " · 🔔" if prevenir(cf, z) else ""
                    lignes.append(f"{z.emoji} **{z.nom}** · {expire_h(cf, z)} h{qui}{ping}")
                lignes.append(f"-# Les demandes closes disparaissent après {garder_h(cf)} h.")
                items.append(discord.ui.TextDisplay("\n".join(lignes)))
            if self._note:
                items.append(discord.ui.TextDisplay(self._note))
            if installe:
                choix = Select(placeholder="Régler une zone…", options=[
                    discord.SelectOption(label=z.nom, value=z.cle, emoji=z.emoji, default=self.zone == z.cle)
                    for z in ZONES.values()])
                choix.callback = self._cb_zone
                items.append(discord.ui.ActionRow(choix))
                z = ZONES.get(self.zone)
                if z is not None:
                    if z.role:
                        rs = RoleSelect(placeholder=f"Rôle des {'middlemen' if z.certif == 'middleman' else 'guides'}"
                                                    f" · {z.nom}", min_values=1, max_values=1)
                        rs.callback = self._cb_role
                        items.append(discord.ui.ActionRow(rs))
                    delai = Select(placeholder=f"Fermée après… · {z.nom}", options=[
                        discord.SelectOption(label=f"{h} h sans activité", value=str(h),
                                             default=h == expire_h(cf, z)) for h in DELAIS])
                    delai.callback = self._cb_delai
                    items.append(discord.ui.ActionRow(delai))
                    if z.certif == "guide":
                        b = Button(label="Prévenir les guides : " + ("oui" if prevenir(cf, z) else "non"),
                                   style=discord.ButtonStyle.secondary,
                                   emoji=visuels.icone("cloche" if prevenir(cf, z) else "cloche_off"))
                        b.callback = self._cb_ping
                        items.append(discord.ui.ActionRow(b))
                garder = Select(placeholder="Les demandes closes disparaissent après…", options=[
                    discord.SelectOption(label=f"{h} h", value=str(h), default=h == garder_h(cf))
                    for h in (6, 24, 72)])
                garder.callback = self._cb_garder
                items.append(discord.ui.ActionRow(garder))
            b_inst = Button(label="Réparer" if installe else "Installer", style=discord.ButtonStyle.primary,
                            emoji=visuels.icone("actualiser" if installe else "ajouter"))
            b_inst.callback = self._cb_installer
            boutons = [b_inst]
            if installe:
                b_rep = Button(label="Reposer les panneaux", style=discord.ButtonStyle.secondary,
                               emoji=visuels.icone("epingle"))
                b_rep.callback = self._cb_panneaux
                boutons.append(b_rep)
            r = Button(label="Retour", style=discord.ButtonStyle.secondary, emoji=visuels.icone("retour"))
            r.callback = self._cb_retour
            boutons.append(r)
            items.append(discord.ui.ActionRow(*boutons))
            self.clear_items()
            self.add_item(discord.ui.Container(*items, accent_color=discord.Color(0x0EA5E9)))
            if not edit:
                return await i.response.send_message(view=self, ephemeral=True)
            if i.response.is_done():
                await i.edit_original_response(content=None, view=self, embed=None, attachments=[])
            else:
                await i.response.edit_message(content=None, view=self, embed=None, attachments=[])
        except Exception as ex:
            _log("[ENTRAIDE][E8] panneau de configuration")
            _log(f"[ENTRAIDE][E8:DETAIL] {type(ex).__name__} {ex}")

    async def _cb_zone(self, i):
        await i.response.defer()
        self.zone, self._note = i.data["values"][0], ""
        await self.render_to(i)

    async def _cb_role(self, i):
        await i.response.defer()
        z, rid = ZONES[self.zone], int(i.data["values"][0])
        r = self.g.get_role(rid)
        if r is None or r.managed or r.is_default():
            self._note = "Ce rôle ne peut pas servir (rôle d'une application ou @everyone)."
            return await self.render_to(i)
        cf = await conf(self.g)
        cf["roles"][z.cle] = rid
        await _db_set(self.g.id, "rs_roles", cf["roles"])
        self._note = f"{z.emoji} {z.nom} : {r.mention} certifie désormais."
        await assurer_panneaux(self.g, forcer=True)
        await self.render_to(i)

    async def _cb_delai(self, i):
        await i.response.defer()
        cf = await conf(self.g)
        expire = dict(cf["reglages"].get("expire") or {})
        expire[self.zone] = int(i.data["values"][0])
        await _regler(self.g, "expire", expire)
        self._note = ""
        await assurer_panneaux(self.g, forcer=True)
        await self.render_to(i)

    async def _cb_ping(self, i):
        await i.response.defer()
        cf = await conf(self.g)
        ping = dict(cf["reglages"].get("ping") or {})
        ping[self.zone] = not prevenir(cf, ZONES[self.zone])
        await _regler(self.g, "ping", ping)
        await self.render_to(i)

    async def _cb_garder(self, i):
        await i.response.defer()
        await _regler(self.g, "garder_h", int(i.data["values"][0]))
        await self.render_to(i)

    async def _cb_installer(self, i):
        cf = await conf(self.g)
        repare = cf["actif"]
        texte = ("Réparer l'entraide ? Ce qui manque est recréé (salons, rôles, panneaux) ; rien n'est supprimé."
                 if repare else "Installer l'entraide ? Une catégorie, sept salons et quatre rôles de guide "
                                "sont créés ; rien n'est supprimé.")
        panneau = self

        async def _action(_i):
            try:
                faits = await installer(panneau.g)
            except PermissionError as ex:
                return str(ex)
            except discord.HTTPException as ex:
                _log("[ENTRAIDE][E9] installation incomplète")
                _log(f"[ENTRAIDE][E9:DETAIL] {type(ex).__name__} {ex}")
                return "Installation incomplète : relance « Réparer » dans un instant."
            await _journal(panneau.g, "entraide.installation",
                           "Entraide Rell Seas " + ("réparée" if repare else "installée") +
                           (" : " + ", ".join(faits) if faits else " : rien ne manquait."), auteur_id=panneau.u.id)
            return ("Créé : " + ", ".join(faits) + ".") if faits else "Rien ne manquait : panneaux reposés."
        await i.response.send_message(view=vue_confirmer(texte, "Oui, " + ("réparer" if repare else "installer"),
                                                         _action, self.u.id, icone="valider",
                                                         style=discord.ButtonStyle.success), ephemeral=True)

    async def _cb_panneaux(self, i):
        await i.response.defer()
        await assurer_panneaux(self.g, forcer=True)
        self._note = "Panneaux reposés."
        await self.render_to(i)

    async def _cb_retour(self, i):
        if _retour is not None:
            await _retour(self.u, self.g, i)
        else:
            await i.response.defer()
