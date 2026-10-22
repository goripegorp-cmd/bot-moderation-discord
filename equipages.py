"""equipages.py — les équipages de Rell Seas (22/10/2026).

« Les gens peuvent publier leur équipage, que ce soit la marine ou les pirateries… un vrai système,
un fil dédié… ultra complet. » Puis : « deux fils seulement… plutôt que des milliers de fils ». Le post
⚓ Crews du forum Rell Seas : une carte par équipage (l'ancienne installation, un forum ⚓crews, ouvrait
un post par équipage, étiquettes Pirates / Marine et Recrute / Complet). Le post épinglé : « Pirates » ou « Marine », un
formulaire dans la langue du membre, une carte en français · anglais. Le capitaine modifie son
équipage, ouvre ou ferme le recrutement, le retire ; un joueur demande à rejoindre d'un clic (le
capitaine est prévenu dans le fil). Un équipage par capitaine ; il part avec son capitaine.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import discord
from discord.ui import Button

import visuels
from ui_v2 import LayoutView, Palette

NOM_FORUM = "⚓crews"
FACTIONS = {"pirate": ("🏴‍☠️", "Pirates", 0x111827), "marine": ("⚓", "Marine", 0x2563EB)}
TAGS = (("Pirates", "🏴‍☠️"), ("Marine", "⚓"), ("Recrute · Recruiting", "📣"), ("Complet · Full", "🔒"))
ATTENTE_REJOINDRE_S = 600
MOT_H = 24          # le mot « veut rejoindre » sous une carte : effacé après 24 h (le capitaine a été prévenu)
NOM_PANNEAU = "📌 Publier ton équipage · Post your crew"

TEXTES = {
    "titre": {"fr": "{emoji} Équipage {faction}", "en": "{emoji} {faction} crew"},
    "facultatif": {"fr": "Facultatif", "en": "Optional"},
    "zone_fermee": {"fr": "Les équipages sont fermés pour le moment.", "en": "Crews are closed for now."},
    "exclu": {"fr": "Pas de publication pendant une exclusion temporaire.", "en": "No posting while timed out."},
    "deja": {"fr": "Tu as déjà un équipage : {lien}. Modifie-le depuis sa carte.",
             "en": "You already have a crew: {lien}. Edit it from its card."},
    "obligatoire": {"fr": "« {champ} » est obligatoire.", "en": "“{champ}” is required."},
    "publie": {"fr": "Équipage publié : {lien}", "en": "Crew posted: {lien}"},
    "impossible": {"fr": "Impossible de publier ton équipage pour le moment.", "en": "Can't post your crew right now."},
    "introuvable": {"fr": "Équipage introuvable.", "en": "Crew not found."},
    "capitaine": {"fr": "Réservé au capitaine de l'équipage.", "en": "Only the crew's captain can do that."},
    "toi": {"fr": "C'est ton équipage.", "en": "It's your crew."},
    "complet": {"fr": "Cet équipage ne recrute pas pour le moment.", "en": "This crew isn't recruiting right now."},
    "deja_demande": {"fr": "Tu as déjà demandé il y a peu : le capitaine est prévenu.",
                     "en": "You asked a moment ago: the captain has been notified."},
    "demande_ok": {"fr": "Le capitaine est prévenu, rendez-vous dans le fil.{lien}",
                   "en": "The captain has been notified, see you in the thread.{lien}"},
    "recrute_on": {"fr": "Recrutement ouvert.", "en": "Recruiting open."},
    "recrute_off": {"fr": "Recrutement fermé.", "en": "Recruiting closed."},
    "modifie": {"fr": "Équipage mis à jour.", "en": "Crew updated."},
    "retirer_q": {"fr": "Retirer cet équipage ? Son post disparaît.", "en": "Remove this crew? Its post disappears."},
    "retirer_oui": {"fr": "Oui, retirer", "en": "Yes, remove"},
    "annuler": {"fr": "Annuler", "en": "Cancel"},
    "retire": {"fr": "Équipage retiré.", "en": "Crew removed."},
    "rien": {"fr": "Rien n'a changé.", "en": "Nothing changed."},
}


def tr(cle: str, langue: str = "fr", **kw) -> str:
    e = TEXTES.get(cle) or {}
    texte = e.get(langue) or e.get("fr") or cle
    try:
        return texte.format(**kw) if kw else texte
    except (KeyError, IndexError, ValueError):
        return texte


@dataclass(frozen=True)
class Champ:
    cle: str
    fr: str
    en: str
    aide_fr: str = ""
    aide_en: str = ""
    carte: str = ""
    long: bool = False
    max: int = 100
    requis: bool = True


CHAMPS = (
    Champ("nom", "Nom de l'équipage", "Crew name", "Ex. Les Requins Rouges", "E.g. The Red Sharks", "", max=60),
    Champ("pseudo", "Ton pseudo Roblox (capitaine)", "Your Roblox username (captain)", "Pour qu'on te trouve en jeu",
          "So players can find you in game", "Capitaine · Captain", max=40),
    Champ("membres", "Membres", "Members", "Ex. 6 / 10", "E.g. 6 / 10", "Membres · Members", max=20, requis=False),
    Champ("niveau", "Niveau minimum", "Minimum level", "Ex. 500", "E.g. 500", "Niveau min · Min level", max=20,
          requis=False),
    Champ("presentation", "Présentation", "About your crew", "Votre style, vos objectifs, vos horaires…",
          "Your style, goals, play times…", "", long=True, max=600),
)

_get_db = _cfg = _db_set = _texte_refuse = _controle = _est_staff = _journal = _langue = None
_log = print
_verrous: dict = {}
_demandes: dict = {}


def setup(*, get_db, cfg, db_set, texte_refuse, controle, est_staff, journal, langue=None, log=None):
    global _get_db, _cfg, _db_set, _texte_refuse, _controle, _est_staff, _journal, _langue, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    _texte_refuse, _controle, _est_staff, _journal, _langue = texte_refuse, controle, est_staff, journal, langue
    _log = log or print


def _verrou(cle):
    return _verrous.setdefault(cle, asyncio.Lock())


async def langue_de(i) -> str:
    try:
        if _langue is not None:
            return "en" if await _langue(i) == "en" else "fr"
        loc = str(getattr(getattr(i, "locale", None), "value", getattr(i, "locale", "")) or "")
        return "fr" if loc.lower().startswith("fr") else "en"
    except Exception as ex:
        _log(f"[EQUIPAGES:DETAIL] langue {type(ex).__name__} {ex}")
        return "fr"


# ═══════════════════════════════════════════════════════════════════════════════
#  Données
# ═══════════════════════════════════════════════════════════════════════════════

_COLONNES = ("id", "guild_id", "capitaine_id", "faction", "nom", "champs", "recrute", "fil_id", "cree", "maj",
             "supprime", "mode")
#  `mode` « carte » : l'équipage est une carte dans le post ⚓ Crews (`fil_id` = la carte, `salon` = le
#  post réglé) ; vide : l'ancienne installation, un post de forum par équipage (`fil_id` = ce post).
_SQL_UN = ("SELECT id, guild_id, capitaine_id, faction, nom, champs, recrute, fil_id, cree, maj, supprime, mode"
           " FROM equipages WHERE id=?")
_SQL_DU_CAPITAINE = ("SELECT id, guild_id, capitaine_id, faction, nom, champs, recrute, fil_id, cree, maj, supprime,"
                     " mode FROM equipages WHERE guild_id=? AND capitaine_id=? AND supprime=0 AND fil_id>0")
_SQL_ACTIFS = ("SELECT id, guild_id, capitaine_id, faction, nom, champs, recrute, fil_id, cree, maj, supprime, mode"
               " FROM equipages WHERE guild_id=? AND supprime=0 AND fil_id>0 ORDER BY id LIMIT 500")


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS equipages (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
            " capitaine_id INTEGER NOT NULL, faction TEXT NOT NULL, nom TEXT NOT NULL, champs TEXT NOT NULL"
            " DEFAULT '{}', recrute INTEGER NOT NULL DEFAULT 1, fil_id INTEGER NOT NULL DEFAULT 0,"
            " cree INTEGER NOT NULL, maj INTEGER NOT NULL, supprime INTEGER NOT NULL DEFAULT 0)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_equipages_capitaine ON equipages(guild_id, capitaine_id)")
        async with db.execute("PRAGMA table_info(equipages)") as cur:
            if "mode" not in {r[1] for r in await cur.fetchall()}:
                await db.execute("ALTER TABLE equipages ADD COLUMN mode TEXT NOT NULL DEFAULT ''")
        await db.execute("CREATE TABLE IF NOT EXISTS equipages_notes (equipage_id INTEGER NOT NULL,"
                         " salon_id INTEGER NOT NULL, message_id INTEGER NOT NULL, expire INTEGER NOT NULL)")
        await db.commit()


def _ligne(r) -> dict:
    d = dict(zip(_COLONNES, r))
    try:
        d["champs"] = json.loads(d["champs"] or "{}")
    except (TypeError, ValueError):
        d["champs"] = {}
    d["mode"] = d.get("mode") or ""
    return d


async def charger(eid: int):
    async with _get_db() as db:
        async with db.execute(_SQL_UN, (int(eid),)) as cur:
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


async def conf(g) -> dict:
    c = await _cfg(g.id)
    return {"forum": int(c.get("eq_forum", 0) or 0), "panneau": int(c.get("eq_panneau", 0) or 0),
            "ouverture": int(c.get("eq_ouverture", 0) or 0)}


def forum_de(g, cf: dict):
    """Le post ⚓ Crews (ou l'ancien forum), s'il est en mémoire — un post endormi n'y est pas."""
    return g.get_channel_or_thread(cf["forum"])


async def _resoudre(g, cid):
    """Un salon ou un post, même endormi ; None s'il n'existe plus. Une panne lève."""
    cid = int(cid or 0)
    if not cid:
        return None
    ch = g.get_channel_or_thread(cid)
    if ch is not None:
        return ch
    try:
        return await g.fetch_channel(cid)
    except discord.NotFound:
        return None


async def conteneur(g, cf: dict):
    """Là où vivent les cartes des équipages — le post, réveillé s'il dormait — ou None."""
    try:
        ch = await _resoudre(g, cf["forum"])
    except discord.HTTPException as ex:
        _log(f"[EQUIPAGES:DETAIL] lecture du salon {type(ex).__name__} {ex}")
        return None
    if isinstance(ch, discord.Thread) and ch.archived:
        try:
            await ch.edit(archived=False)
        except discord.HTTPException as ex:
            _log(f"[EQUIPAGES:DETAIL] réveil du post {ex}")
    return ch


def en_cartes(ch) -> bool:
    """Un équipage est une carte dans son post (ou son salon) ; seul l'ancien forum ouvrait un post."""
    return ch is not None and not isinstance(ch, discord.ForumChannel)


async def lien(g, e: dict) -> str:
    if e.get("mode") == "carte":
        return f"https://discord.com/channels/{g.id}/{(await conf(g))['forum']}/{int(e['fil_id'])}"
    return f"https://discord.com/channels/{g.id}/{int(e['fil_id'])}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Cartes
# ═══════════════════════════════════════════════════════════════════════════════

def _echapper(t) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(t or "")))


def _une_ligne(t) -> str:
    return " ".join(str(t or "").split())


def nom_du_fil(e: dict, capitaine) -> str:
    emoji = FACTIONS.get(e["faction"], FACTIONS["pirate"])[0]
    return _une_ligne(f"{emoji} {e['nom']} · {getattr(capitaine, 'display_name', '') or 'capitaine'}")[:100]


def vue_carte(e: dict, *, avatar: str = "") -> LayoutView:
    emoji, faction, couleur = FACTIONS.get(e["faction"], FACTIONS["pirate"])
    ch = e["champs"]
    entete = [discord.ui.TextDisplay(f"## {emoji} {_echapper(e['nom'])}"),
              discord.ui.TextDisplay(f"-# {faction} · <@{int(e['capitaine_id'])}> · <t:{int(e['cree'])}:R>")]
    items = [discord.ui.Section(*entete, accessory=discord.ui.Thumbnail(avatar))] if avatar else list(entete)
    lignes = [f"**{c.carte}** · {_echapper(ch.get(c.cle))}" for c in CHAMPS
              if c.carte and str(ch.get(c.cle) or "").strip()]
    if lignes:
        items.append(discord.ui.TextDisplay("\n".join(lignes)))
    if str(ch.get("presentation") or "").strip():
        items.append(discord.ui.TextDisplay(_echapper(ch["presentation"])))
    items.append(discord.ui.Separator())
    items.append(discord.ui.TextDisplay("📣 **Recrute · Recruiting**" if e["recrute"] else "🔒 **Complet · Full**"))
    boutons = ([BoutonRejoindre(e["id"])] if e["recrute"] else []) + [
        BoutonRecrutement(e["id"]), BoutonModifier(e["id"]), BoutonRetirer(e["id"])]
    items.append(discord.ui.ActionRow(*boutons))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(couleur)))
    return v


def vue_panneau() -> LayoutView:
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        visuels.bandeau("rs_crews", "Équipages · Crews"),
        discord.ui.TextDisplay("🇫🇷 Pirates ou Marine : publie ton équipage, recrute, trouve le tien.\n"
                               "🇬🇧 Pirates or Marine: post your crew, recruit, find yours."),
        discord.ui.ActionRow(BoutonPublier("pirate"), BoutonPublier("marine")),
        discord.ui.TextDisplay("-# Un équipage par capitaine · One crew per captain · le capitaine le modifie, "
                               "le ferme ou le retire · the captain edits, closes or removes it"),
        accent_color=discord.Color(0x0EA5E9)))
    return v


def _tags(forum, e: dict) -> list:
    dispo = {t.name: t for t in getattr(forum, "available_tags", []) or []}
    noms = [FACTIONS.get(e["faction"], FACTIONS["pirate"])[1], "Recrute · Recruiting" if e["recrute"] else "Complet · Full"]
    return [dispo[n] for n in noms if n in dispo]


async def _fil(g, e: dict):
    """Le post d'un équipage, ou None s'il n'existe plus. Une panne réseau n'est pas une disparition :
    elle lève (l'entretien ne retire pas un équipage parce que Discord a hoqueté)."""
    fid = int(e.get("fil_id") or 0)
    if not fid:
        return None
    fil = g.get_channel_or_thread(fid)
    if fil is not None:
        return fil
    try:
        return await g.fetch_channel(fid)
    except discord.NotFound:
        return None


async def _fil_ou_rien(g, e: dict):
    """Pour les interactions : une panne réseau ne doit pas laisser le membre sans réponse."""
    try:
        return await _fil(g, e)
    except discord.HTTPException as ex:
        _log(f"[EQUIPAGES:DETAIL] lecture du fil equipage={e['id']} {type(ex).__name__} {ex}")
        return None


def _porteur(fil):
    """Le salon qui porte la carte : le post lui-même (forum), ou le salon sous lequel pend le fil."""
    parent = getattr(fil, "parent", None)
    return fil if isinstance(parent, discord.ForumChannel) or parent is None else parent


async def _maj(g, e: dict, renommer: bool = False) -> None:
    """La carte suit l'équipage (et, ancienne installation, les étiquettes et le nom de son post)."""
    capitaine = g.get_member(int(e["capitaine_id"]))
    if e.get("mode") == "carte":
        porteur = await conteneur(g, await conf(g))
        if porteur is None:
            return
        try:
            await porteur.get_partial_message(int(e["fil_id"])).edit(
                view=vue_carte(e, avatar=capitaine.display_avatar.url if capitaine else ""),
                allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            pass
        except discord.HTTPException as ex:
            _log("[EQUIPAGES][E2] carte non mise à jour")
            _log(f"[EQUIPAGES][E2:DETAIL] equipage={e['id']} {type(ex).__name__} {ex}")
        return
    fil = await _fil_ou_rien(g, e)
    if fil is None:
        return
    try:
        if fil.archived:
            await fil.edit(archived=False)
        await _porteur(fil).get_partial_message(fil.id).edit(
            view=vue_carte(e, avatar=capitaine.display_avatar.url if capitaine else ""),
            allowed_mentions=discord.AllowedMentions.none())
        reglage = {}
        if isinstance(fil.parent, discord.ForumChannel):
            reglage["applied_tags"] = _tags(fil.parent, e)
        if renommer:
            reglage["name"] = nom_du_fil(e, capitaine)
        if reglage:
            await fil.edit(**reglage)
    except discord.HTTPException as ex:
        _log("[EQUIPAGES][E2] carte non mise à jour")
        _log(f"[EQUIPAGES][E2:DETAIL] equipage={e['id']} {type(ex).__name__} {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Publier, modifier
# ═══════════════════════════════════════════════════════════════════════════════

class Formulaire(discord.ui.Modal):
    def __init__(self, faction: str, langue: str = "fr", valeurs: dict | None = None, eid: int = 0):
        emoji, nom, _c = FACTIONS[faction]
        super().__init__(title=tr("titre", langue, emoji=emoji, faction=nom)[:45], timeout=900)
        self.faction, self.langue, self.eid, self.entrees = faction, langue, eid, {}
        valeurs = valeurs or {}
        for c in CHAMPS:
            t = discord.ui.TextInput(style=discord.TextStyle.paragraph if c.long else discord.TextStyle.short,
                                     max_length=c.max, required=c.requis,
                                     placeholder=(c.aide_en if langue == "en" else c.aide_fr)[:100] or None,
                                     default=valeurs.get(c.cle) or None)
            self.entrees[c.cle] = t
            self.add_item(discord.ui.Label(text=(c.en if langue == "en" else c.fr)[:45], component=t,
                                           description=None if c.requis else tr("facultatif", langue)))

    async def on_submit(self, i: discord.Interaction):
        valeurs = {k: (t.value or "").strip() if CHAMPS_PAR_CLE[k].long else _une_ligne(t.value)
                   for k, t in self.entrees.items()}
        if self.eid:
            await modifier(i, self.eid, valeurs, self.langue)
        else:
            await publier(i, self.faction, valeurs, self.langue)


CHAMPS_PAR_CLE = {c.cle: c for c in CHAMPS}


async def _refus(i, langue: str) -> str:
    g, m = i.guild, i.user
    if g is None or getattr(m, "guild_permissions", None) is None or not (await conf(g))["forum"]:
        return tr("zone_fermee", langue)
    if m.is_timed_out():
        return tr("exclu", langue)
    return await _controle(m, await _cfg(g.id)) or ""


async def publier(i, faction: str, valeurs: dict, langue: str = "fr"):
    g, m = i.guild, i.user
    manque = next((c for c in CHAMPS if c.requis and not valeurs.get(c.cle)), None)
    erreur = (tr("obligatoire", langue, champ=manque.en if langue == "en" else manque.fr) if manque else
              await _texte_refuse(g, "\n".join(v for v in valeurs.values() if v)))
    if erreur:
        return await i.response.send_message(erreur, ephemeral=True)
    refus = await _refus(i, langue)
    if refus:
        return await i.response.send_message(refus, ephemeral=True)
    await i.response.defer(ephemeral=True, thinking=True)
    async with _verrou(("publier", g.id)):
        deja = await _lignes(_SQL_DU_CAPITAINE, (g.id, m.id))
        if deja:
            return await i.followup.send(tr("deja", langue, lien=await lien(g, deja[0])), ephemeral=True)
        t = int(time.time())
        async with _get_db() as db:
            cur = await db.execute("INSERT INTO equipages(guild_id, capitaine_id, faction, nom, champs, cree, maj)"
                                   " VALUES(?,?,?,?,?,?,?)", (g.id, m.id, faction, valeurs["nom"],
                                                              json.dumps(valeurs, ensure_ascii=False), t, t))
            eid = cur.lastrowid
            await db.commit()
    e = await charger(eid)
    forum = await conteneur(g, await conf(g))
    mode, fil = ("carte" if en_cartes(forum) else ""), None
    try:
        if forum is None:
            raise discord.ClientException("équipages sans salon")
        if mode == "carte":
            carte_id = (await forum.send(view=vue_carte(e, avatar=m.display_avatar.url),
                                         allowed_mentions=discord.AllowedMentions.none())).id
        else:
            fil = (await forum.create_thread(name=nom_du_fil(e, m), view=vue_carte(e, avatar=m.display_avatar.url),
                                             applied_tags=_tags(forum, e),
                                             allowed_mentions=discord.AllowedMentions.none(),
                                             reason=f"Équipage n°{eid}")).thread
            carte_id = fil.id
    except (discord.HTTPException, discord.ClientException) as ex:
        _log("[EQUIPAGES][E1] équipage non publié")
        _log(f"[EQUIPAGES][E1:DETAIL] {type(ex).__name__} {ex}")
        await _ecrire("DELETE FROM equipages WHERE id=?", (eid,))
        return await i.followup.send(tr("impossible", langue), ephemeral=True)
    await _ecrire("UPDATE equipages SET fil_id=?, mode=? WHERE id=?", (carte_id, mode, eid))
    e.update(fil_id=carte_id, mode=mode)
    if fil is not None:
        try:
            await fil.add_user(m)
        except discord.HTTPException as ex:
            _log(f"[EQUIPAGES:DETAIL] capitaine non ajouté equipage={eid} {ex}")
    await i.followup.send(tr("publie", langue, lien=await lien(g, e)), ephemeral=True)
    if mode == "carte":
        asyncio.create_task(reposer_panneau(g))
    await _journal(g, "equipage.publie", f"{m.mention} a publié son équipage {FACTIONS[faction][1]} : {e['nom']}",
                   membre_id=m.id)


async def modifier(i, eid: int, valeurs: dict, langue: str = "fr"):
    g = i.guild
    manque = next((c for c in CHAMPS if c.requis and not valeurs.get(c.cle)), None)
    erreur = (tr("obligatoire", langue, champ=manque.en if langue == "en" else manque.fr) if manque else
              await _texte_refuse(g, "\n".join(v for v in valeurs.values() if v)))
    if erreur:
        return await i.response.send_message(erreur, ephemeral=True)
    await i.response.defer(ephemeral=True)
    async with _verrou(("equipage", eid)):
        e = await charger(eid)
        if e is None or e["supprime"]:
            return await i.followup.send(tr("introuvable", langue), ephemeral=True)
        e.update(nom=valeurs["nom"], champs=valeurs, maj=int(time.time()))
        await _ecrire("UPDATE equipages SET nom=?, champs=?, maj=? WHERE id=?",
                      (e["nom"], json.dumps(valeurs, ensure_ascii=False), e["maj"], eid))
    await _maj(g, e, renommer=True)
    await i.followup.send(tr("modifie", langue), ephemeral=True)


async def _capitaine(i, eid: int, langue: str, staff_ok: bool = False):
    """L'équipage si c'est son capitaine (ou le staff quand `staff_ok`), sinon un refus déjà envoyé."""
    e = await charger(eid)
    if e is None or e["supprime"] or i.guild is None or e["guild_id"] != i.guild.id:
        await i.response.send_message(tr("introuvable", langue), ephemeral=True)
        return None
    if i.user.id != e["capitaine_id"] and not (staff_ok and await _est_staff(i.guild, i.user)):
        await i.response.send_message(tr("capitaine", langue), ephemeral=True)
        return None
    return e


class BoutonPublier(discord.ui.DynamicItem[Button], template=r"eq:p:(?P<faction>pirate|marine)"):
    def __init__(self, faction: str):
        self.faction = faction
        emoji, nom, _c = FACTIONS[faction]
        super().__init__(Button(label=nom, emoji=emoji, style=discord.ButtonStyle.primary,
                                custom_id=f"eq:p:{faction}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["faction"])

    async def callback(self, i: discord.Interaction):
        langue = await langue_de(i)
        refus = await _refus(i, langue)
        if refus:
            return await i.response.send_message(refus, ephemeral=True)
        deja = await _lignes(_SQL_DU_CAPITAINE, (i.guild.id, i.user.id))
        if deja:
            return await i.response.send_message(tr("deja", langue, lien=await lien(i.guild, deja[0])),
                                                 ephemeral=True)
        await i.response.send_modal(Formulaire(self.faction, langue))


class BoutonRejoindre(discord.ui.DynamicItem[Button], template=r"eq:j:(?P<eid>\d+)"):
    def __init__(self, eid: int):
        self.eid = int(eid)
        super().__init__(Button(label="Rejoindre · Join", style=discord.ButtonStyle.success,
                                emoji=visuels.icone("accueil"), custom_id=f"eq:j:{int(eid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]))

    async def callback(self, i: discord.Interaction):
        langue = await langue_de(i)
        await i.response.defer(ephemeral=True)
        e = await charger(self.eid)
        if e is None or e["supprime"] or i.guild is None or e["guild_id"] != i.guild.id:
            return await i.followup.send(tr("introuvable", langue), ephemeral=True)
        if i.user.id == e["capitaine_id"]:
            return await i.followup.send(tr("toi", langue), ephemeral=True)
        if not e["recrute"]:
            return await i.followup.send(tr("complet", langue), ephemeral=True)
        cle, t = (e["id"], i.user.id), time.monotonic()
        if t - _demandes.get(cle, -1e9) < ATTENTE_REJOINDRE_S:
            return await i.followup.send(tr("deja_demande", langue), ephemeral=True)
        _demandes[cle] = t
        texte = (f"🙋 {i.user.mention} veut rejoindre l'équipage · wants to join — <@{int(e['capitaine_id'])}>")
        mentions = discord.AllowedMentions(users=[discord.Object(e["capitaine_id"])])
        if e["mode"] == "carte":
            await _mot_sous_la_carte(i.guild, e, texte, mentions)
        else:
            fil = await _fil_ou_rien(i.guild, e)
            if fil is not None:
                try:
                    if fil.archived:
                        await fil.edit(archived=False)
                    await fil.add_user(i.user)
                    await fil.send(texte, allowed_mentions=mentions)
                except discord.HTTPException as ex:
                    _log(f"[EQUIPAGES:DETAIL] demande equipage={e['id']} {ex}")
        await i.followup.send(tr("demande_ok", langue, lien=f" {await lien(i.guild, e)}"), ephemeral=True)


class BoutonRecrutement(discord.ui.DynamicItem[Button], template=r"eq:r:(?P<eid>\d+)"):
    def __init__(self, eid: int):
        self.eid = int(eid)
        super().__init__(Button(label="Recrutement · Recruiting", style=discord.ButtonStyle.secondary,
                                emoji=visuels.icone("cloche"), custom_id=f"eq:r:{int(eid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]))

    async def callback(self, i: discord.Interaction):
        langue = await langue_de(i)
        e = await _capitaine(i, self.eid, langue)
        if e is None:
            return
        await i.response.defer(ephemeral=True)
        e["recrute"], e["maj"] = 0 if e["recrute"] else 1, int(time.time())
        await _ecrire("UPDATE equipages SET recrute=?, maj=? WHERE id=?", (e["recrute"], e["maj"], e["id"]))
        await _maj(i.guild, e)
        await i.followup.send(tr("recrute_on" if e["recrute"] else "recrute_off", langue), ephemeral=True)


class BoutonModifier(discord.ui.DynamicItem[Button], template=r"eq:m:(?P<eid>\d+)"):
    def __init__(self, eid: int):
        self.eid = int(eid)
        super().__init__(Button(label="Modifier · Edit", style=discord.ButtonStyle.secondary,
                                emoji=visuels.icone("modifier"), custom_id=f"eq:m:{int(eid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]))

    async def callback(self, i: discord.Interaction):
        langue = await langue_de(i)
        e = await _capitaine(i, self.eid, langue)
        if e is None:
            return
        await i.response.send_modal(Formulaire(e["faction"], langue, e["champs"], eid=e["id"]))


class BoutonRetirer(discord.ui.DynamicItem[Button], template=r"eq:x:(?P<eid>\d+)"):
    def __init__(self, eid: int):
        self.eid = int(eid)
        super().__init__(Button(label="Retirer · Remove", style=discord.ButtonStyle.secondary,
                                emoji=visuels.icone("supprimer"), custom_id=f"eq:x:{int(eid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["eid"]))

    async def callback(self, i: discord.Interaction):
        langue = await langue_de(i)
        e = await _capitaine(i, self.eid, langue, staff_ok=True)
        if e is None:
            return
        v = LayoutView(timeout=300)
        oui = Button(label=tr("retirer_oui", langue), style=discord.ButtonStyle.danger, emoji=visuels.icone("supprimer"))
        non = Button(label=tr("annuler", langue), style=discord.ButtonStyle.secondary, emoji=visuels.icone("annuler"))
        auteur = i.user.id

        async def _oui(j):
            if j.user.id != auteur:
                return await j.response.defer()
            await j.response.defer()
            await retirer(j.guild, e["id"], j.user.id)
            await j.edit_original_response(view=_vue_message(tr("retire", langue)))

        async def _non(j):
            if j.user.id != auteur:
                return await j.response.defer()
            await j.response.edit_message(view=_vue_message(tr("rien", langue)))
        oui.callback, non.callback = _oui, _non
        v.add_item(discord.ui.Container(discord.ui.TextDisplay(tr("retirer_q", langue)), discord.ui.ActionRow(oui, non),
                                        accent_color=Palette.WARNING))
        await i.response.send_message(view=v, ephemeral=True)


async def _mot_sous_la_carte(g, e: dict, texte: str, mentions) -> bool:
    """Le mot du bot en réponse à la carte (le capitaine est prévenu) ; effacé après un jour."""
    try:
        porteur = await conteneur(g, await conf(g))
        if porteur is None:
            return False
        msg = await porteur.send(texte, reference=porteur.get_partial_message(int(e["fil_id"])),
                                 allowed_mentions=mentions, mention_author=False)
    except discord.HTTPException as ex:
        _log(f"[EQUIPAGES:DETAIL] mot sous la carte equipage={e['id']} {type(ex).__name__} {ex}")
        return False
    await _ecrire("INSERT INTO equipages_notes(equipage_id, salon_id, message_id, expire) VALUES(?,?,?,?)",
                  (int(e["id"]), porteur.id, msg.id, int(time.time()) + MOT_H * 3600))
    return True


async def _effacer_mots(g, eid: int = 0, maintenant: float | None = None) -> int:
    """Les mots « veut rejoindre » d'un équipage (tous), ou ceux dont le jour est passé."""
    if eid:
        sql, args = "SELECT salon_id, message_id FROM equipages_notes WHERE equipage_id=?", (int(eid),)
    else:
        sql, args = "SELECT salon_id, message_id FROM equipages_notes WHERE expire<=?", (int(maintenant or time.time()),)
    async with _get_db() as db:
        async with db.execute(sql, args) as cur:
            mots = [(int(a), int(b)) for a, b in await cur.fetchall()]
    n = 0
    for salon_id, mid in mots:
        try:
            porteur = await _resoudre(g, salon_id)
            if porteur is not None:
                await porteur.get_partial_message(mid).delete()
                n += 1
        except discord.NotFound:
            pass
        except discord.HTTPException as ex:
            _log(f"[EQUIPAGES:DETAIL] mot non effacé {type(ex).__name__} {ex}")
            continue
        await _ecrire("DELETE FROM equipages_notes WHERE message_id=?", (mid,))
    return n


def _vue_message(texte: str) -> LayoutView:
    v = LayoutView(timeout=60)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), accent_color=Palette.NEUTRAL))
    return v


async def retirer(g, eid: int, par_id: int = 0) -> bool:
    async with _verrou(("equipage", eid)):
        e = await charger(eid)
        if e is None or e["supprime"]:
            return False
        try:
            if e["mode"] == "carte":
                porteur = await _resoudre(g, (await conf(g))["forum"])
                if porteur is not None:
                    try:
                        await porteur.get_partial_message(int(e["fil_id"])).delete()
                    except discord.NotFound:
                        pass
                fil = None
            else:
                fil = await _fil(g, e)
            if fil is not None:
                parent = fil.parent
                try:
                    await fil.delete()
                except discord.NotFound:
                    pass
                if parent is not None and not isinstance(parent, discord.ForumChannel):
                    try:
                        await parent.get_partial_message(fil.id).delete()
                    except discord.NotFound:
                        pass
        except discord.HTTPException as ex:
            _log("[EQUIPAGES][E3] post non retiré")
            _log(f"[EQUIPAGES][E3:DETAIL] equipage={eid} {type(ex).__name__} {ex}")
            return False
        await _ecrire("UPDATE equipages SET supprime=1, maj=? WHERE id=?", (int(time.time()), eid))
    await _effacer_mots(g, eid)
    if par_id and par_id != e["capitaine_id"]:
        await _journal(g, "equipage.retire", f"<@{par_id}> a retiré l'équipage {e['nom']} de <@{e['capitaine_id']}>",
                       membre_id=e["capitaine_id"], auteur_id=par_id)
    return True


async def tout_retirer(guild_id: int) -> int:
    """22/10/2026 : « le crew équipage… une mauvaise idée » — tous les équipages sortent de la liste."""
    async with _get_db() as db:
        cur = await db.execute("UPDATE equipages SET supprime=1 WHERE guild_id=? AND supprime=0", (int(guild_id),))
        n = cur.rowcount or 0
        await db.commit()
    return n


async def lister(guild_id: int) -> list:
    """Pour le site : les équipages en place."""
    return await _lignes(_SQL_ACTIFS, (int(guild_id),))


async def demenager(g) -> int:
    """22/10/2026, « deux fils seulement » : les équipages de l'ancien forum deviennent des cartes du
    post ⚓ Crews — rien n'est perdu (nom, faction, champs, recrutement, capitaine)."""
    porteur = await conteneur(g, await conf(g))
    if not en_cartes(porteur):
        return 0
    n = 0
    for e in await _lignes(_SQL_ACTIFS, (g.id,)):
        if e["mode"] == "carte":
            continue
        capitaine = g.get_member(int(e["capitaine_id"]))
        try:
            carte = await porteur.send(view=vue_carte(e, avatar=capitaine.display_avatar.url if capitaine else ""),
                                       allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as ex:
            _log(f"[EQUIPAGES:DETAIL] équipage non déménagé equipage={e['id']} {type(ex).__name__} {ex}")
            continue
        await _ecrire("UPDATE equipages SET fil_id=?, mode='carte' WHERE id=?", (carte.id, e["id"]))
        n += 1
    if n:
        await reposer_panneau(g)
    return n


async def sur_depart(member) -> int:
    """Un capitaine quitte le serveur : son équipage part avec lui."""
    n = 0
    for e in await _lignes(_SQL_DU_CAPITAINE, (member.guild.id, member.id)):
        if await retirer(member.guild, e["id"]):
            n += 1
    return n


# ═══════════════════════════════════════════════════════════════════════════════
#  Installation, entretien
# ═══════════════════════════════════════════════════════════════════════════════

def droits(g) -> dict:
    """On publie par le bouton ; on parle dans les fils."""
    return {g.default_role: discord.PermissionOverwrite(
                send_messages=False, create_public_threads=False, create_private_threads=False,
                send_messages_in_threads=True, read_message_history=True, attach_files=True, embed_links=True,
                add_reactions=True),
            g.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, send_messages_in_threads=True, create_public_threads=True,
                manage_threads=True, manage_messages=True, read_message_history=True, embed_links=True,
                attach_files=True)}


async def installer(g, categorie=None, *, forum: bool | None = None, creer: bool = True) -> list:
    """Seul (sans les zones) : le forum ⚓crews et son post épinglé. Les zones donnent elles-mêmes le
    post ⚓ Crews (`creer=False`). Rien n'est supprimé."""
    forum = ("COMMUNITY" in g.features) if forum is None else forum
    faits = []
    async with _verrou(("installer", g.id)):
        cf = await conf(g)
        ch = await _resoudre(g, cf["forum"])
        if ch is None and creer:
            sujet = ("🇫🇷 Publie ton équipage avec le post épinglé ; on parle dans le fil de chaque équipage.\n"
                     "🇬🇧 Post your crew with the pinned post; talk in each crew's thread.")
            if forum:
                ch = await g.create_forum(
                    NOM_FORUM, category=categorie, topic=sujet, overwrites=droits(g),
                    default_auto_archive_duration=10080, default_layout=discord.ForumLayoutType.list_view,
                    default_sort_order=discord.ForumOrderType.latest_activity,
                    available_tags=[discord.ForumTag(name=n, emoji=e, moderated=True) for n, e in TAGS],
                    reason="Équipages Rell Seas")
            else:
                ch = await g.create_text_channel(NOM_FORUM, category=categorie, topic=sujet, overwrites=droits(g),
                                                 reason="Équipages Rell Seas")
            await _db_set(g.id, "eq_forum", ch.id)
            faits.append(f"salon {ch.name}")
        elif (isinstance(ch, discord.ForumChannel) and categorie is not None
              and getattr(ch, "category_id", None) != categorie.id):
            await ch.edit(category=categorie, sync_permissions=False, reason="Rangé dans la zone Rell Seas")
    await assurer_panneau(g)
    return faits


async def assurer_panneau(g, forcer: bool = False) -> None:
    """Le post épinglé (ancien forum) — ou, dans un post, son message d'ouverture et le panneau qui
    redescend sous la dernière carte."""
    cf = await conf(g)
    ch = await conteneur(g, cf)
    if ch is None:
        return
    try:
        if isinstance(ch, discord.ForumChannel):
            fil = await _resoudre(g, cf["panneau"]) if cf["panneau"] else None
            if fil is None:
                fil = (await ch.create_thread(name=NOM_PANNEAU, view=vue_panneau(),
                                              allowed_mentions=discord.AllowedMentions.none(),
                                              reason="Équipages : post épinglé")).thread
                await _db_set(g.id, "eq_panneau", fil.id)
                await fil.edit(pinned=True, locked=True)
            elif fil.archived or not fil.locked or not fil.flags.pinned:
                await fil.edit(archived=False, locked=True, pinned=True)
            return
        if forcer and cf["ouverture"]:
            try:
                await ch.get_partial_message(cf["ouverture"]).edit(view=vue_panneau(),
                                                                    allowed_mentions=discord.AllowedMentions.none())
            except discord.NotFound:
                pass
        if cf["panneau"]:
            if cf["panneau"] == cf["ouverture"]:
                return
            try:
                await ch.fetch_message(cf["panneau"])
                return
            except discord.NotFound:
                pass
        msg = await ch.send(view=vue_panneau(), allowed_mentions=discord.AllowedMentions.none())
        await _db_set(g.id, "eq_panneau", msg.id)
    except discord.HTTPException as ex:
        _log("[EQUIPAGES][E4] post épinglé non posé")
        _log(f"[EQUIPAGES][E4:DETAIL] {type(ex).__name__} {ex}")


async def reposer_panneau(g) -> None:
    """Après une nouvelle carte, le panneau redescend dessous (le message d'ouverture reste)."""
    async with _verrou(("panneau", g.id)):
        cf = await conf(g)
        ch = await conteneur(g, cf)
        if not en_cartes(ch):
            return
        try:
            if cf["panneau"] and cf["panneau"] != cf["ouverture"]:
                try:
                    await ch.get_partial_message(cf["panneau"]).delete()
                except discord.NotFound:
                    pass
            msg = await ch.send(view=vue_panneau(), allowed_mentions=discord.AllowedMentions.none())
            await _db_set(g.id, "eq_panneau", msg.id)
        except discord.HTTPException as ex:
            _log("[EQUIPAGES][E4] post épinglé non posé")
            _log(f"[EQUIPAGES][E4:DETAIL] reposer {type(ex).__name__} {ex}")


async def entretenir(g) -> int:
    """Les équipages restent visibles (Discord archive un post resté calme 7 jours : on le réveille) ;
    un équipage dont le post a disparu sort de la liste — pas sur une panne réseau."""
    n = 0
    await _effacer_mots(g)
    for e in await _lignes(_SQL_ACTIFS, (g.id,)):
        try:
            if e["mode"] == "carte":
                porteur = await _resoudre(g, (await conf(g))["forum"])
                try:
                    fil = await porteur.fetch_message(int(e["fil_id"])) if porteur is not None else None
                except discord.NotFound:
                    fil = None
            else:
                fil = await _fil(g, e)
        except discord.HTTPException as ex:
            _log(f"[EQUIPAGES:DETAIL] lecture du fil equipage={e['id']} {type(ex).__name__} {ex}")
            continue
        if fil is None:
            await _ecrire("UPDATE equipages SET supprime=1 WHERE id=?", (e["id"],))
            continue
        if getattr(fil, "archived", False):
            try:
                await fil.edit(archived=False)
                n += 1
            except discord.HTTPException as ex:
                _log(f"[EQUIPAGES:DETAIL] réveil equipage={e['id']} {ex}")
    await assurer_panneau(g)
    return n
