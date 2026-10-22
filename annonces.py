"""annonces.py — les annonces en un clic (22/10/2026).

Demandé par le fondateur : « des annonces ultra bien faites, custom, avec une magnifique image…
juste à mettre un texte… un système de coche verte pour que les gens aient vu l'annonce… ranger par
fil », et pour le clan : « un salon des annonces du clan… automatisé, propre. Nous, quand on fait des
annonces… cliquer sur un bouton, remplir le texte… de belles annonces magnifiques ».

Le fondateur et la direction : « Nouvelle annonce » dans 📋logs → le salon (Information, Sneak Peek,
annonces du clan…), un formulaire (titre, texte, liens, image), l'aperçu exact, Publier. L'annonce :
le bandeau du salon (ou l'image envoyée), le titre, le texte, les liens en boutons, « ✅ Vu · Seen » et
son compteur ; un fil à son nom pour la suite. Qui a vu quoi reste en base (pour le site). Une
arrivée dans le clan s'annonce d'elle-même dans les annonces du clan.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import time
from dataclasses import dataclass, field

import discord
from discord.ui import Button, Select

import config_salons
import visuels
from ui_v2 import LayoutView, Palette

#  Le bandeau de chaque salon, selon les mots de son nom : (mots, bandeau, titre du bandeau, couleur)
STYLES = (
    (("target",), "an_target", "Target Roblox", 0x22C55E),
    (("ambre",), "an_ambrebois", "Ambrebois", 0xF97316),
    (("fix",), "an_sneakfix", "Correctifs · Fixes", 0x3B82F6),
    (("goripe",), "an_goripe", "GoRipe", 0xA855F7),
    (("rellseas", "rell"), "an_rellseas", "Rell Seas", 0x06B6D4),
    (("annonce",), "an_annonce", "Annonce", 0xF59E0B),
)
STYLE_CLAN = ("an_clan", "Annonce du clan", 0x14B8A6)
STYLE_DEFAUT = ("an_annonce", "Annonce", 0xF59E0B)
#  Les actus Roblox (sneak-news-roblox) arrivent seules : « faut pas trop y toucher ».
EXCLUS = ("news",)
TYPES_IMAGE = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
IMAGE_MAX = 8 * 1024 * 1024
LIENS_MAX = 5
TITRE_MAX, TEXTE_MAX = 100, 3000    # Discord : 4 000 caractères pour tout le message
MAJ_VUES_S = 10.0          # le compteur « Vu » se réécrit au plus toutes les 10 s
ARRIVEES_S = 60.0          # les arrivées d'une minute dans le clan : une seule carte
URL = re.compile(r"^https?://\S+$", re.I)

TEXTES = {
    "vu_ok": {"fr": "✅ C'est noté, merci d'avoir lu.", "en": "✅ Noted, thanks for reading."},
    "vu_deja": {"fr": "Déjà noté ✅", "en": "Already noted ✅"},
    "introuvable": {"fr": "Cette annonce n'existe plus.", "en": "This announcement no longer exists."},
}


def tr(cle: str, langue: str = "fr") -> str:
    e = TEXTES.get(cle) or {}
    return e.get(langue) or e.get("fr") or cle


_get_db = _cfg = _db_set = _est_tete = _journal = _langue = _role_clan = None
_log = print
_maj_prevues: dict = {}
_arrivees: dict = {}


def setup(*, get_db, cfg, db_set, est_tete, journal, role_clan=None, langue=None, log=None):
    """`est_tete(g, membre)` → bool : le fondateur ou la direction ; `journal(g, type_, texte, **kw)`
    (async) ; `role_clan(g, c)` → le rôle du clan ou None ; `langue(i)` (async) → « fr » ou « en »."""
    global _get_db, _cfg, _db_set, _est_tete, _journal, _role_clan, _langue, _log
    _get_db, _cfg, _db_set, _est_tete, _journal = get_db, cfg, db_set, est_tete, journal
    _role_clan, _langue = role_clan, langue
    _log = log or print


async def langue_de(i) -> str:
    try:
        if _langue is not None:
            return "en" if await _langue(i) == "en" else "fr"
        loc = str(getattr(getattr(i, "locale", None), "value", getattr(i, "locale", "")) or "")
        return "fr" if loc.lower().startswith("fr") else "en"
    except Exception as ex:
        _log(f"[ANNONCES:DETAIL] langue {type(ex).__name__} {ex}")
        return "fr"


# ═══════════════════════════════════════════════════════════════════════════════
#  Données
# ═══════════════════════════════════════════════════════════════════════════════

_COLONNES = ("id", "guild_id", "salon_id", "message_id", "fil_id", "auteur_id", "titre", "texte", "liens",
             "image", "mention", "cree")
_SQL_UNE = ("SELECT id, guild_id, salon_id, message_id, fil_id, auteur_id, titre, texte, liens, image, mention,"
            " cree FROM annonces WHERE id=?")
_SQL_RECENTES = ("SELECT id, guild_id, salon_id, message_id, fil_id, auteur_id, titre, texte, liens, image,"
                 " mention, cree FROM annonces WHERE guild_id=? AND message_id>0 ORDER BY id DESC LIMIT ?")


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS annonces (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
            " salon_id INTEGER NOT NULL, message_id INTEGER NOT NULL DEFAULT 0, fil_id INTEGER NOT NULL DEFAULT 0,"
            " auteur_id INTEGER NOT NULL, titre TEXT NOT NULL, texte TEXT NOT NULL, liens TEXT NOT NULL DEFAULT '[]',"
            " image TEXT NOT NULL DEFAULT '', mention TEXT NOT NULL DEFAULT '', cree INTEGER NOT NULL)")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS annonces_vues (annonce_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
            " quand INTEGER NOT NULL, PRIMARY KEY (annonce_id, membre_id))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_annonces_guild ON annonces(guild_id, id)")
        await db.commit()


def _ligne(r) -> dict:
    a = dict(zip(_COLONNES, r))
    try:
        a["liens"] = [tuple(x) for x in json.loads(a["liens"] or "[]")]
    except (TypeError, ValueError):
        a["liens"] = []
    return a


async def charger(aid: int):
    async with _get_db() as db:
        async with db.execute(_SQL_UNE, (int(aid),)) as cur:
            r = await cur.fetchone()
    return _ligne(r) if r else None


async def recentes(guild_id: int, limite: int = 100) -> list:
    """Les dernières annonces publiées — pour le site."""
    async with _get_db() as db:
        async with db.execute(_SQL_RECENTES, (int(guild_id), int(limite))) as cur:
            return [_ligne(r) for r in await cur.fetchall()]


async def compter_vues(aid: int) -> int:
    async with _get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM annonces_vues WHERE annonce_id=?", (int(aid),)) as cur:
            return int((await cur.fetchone())[0])


async def qui_a_vu(aid: int) -> list:
    async with _get_db() as db:
        async with db.execute("SELECT membre_id, quand FROM annonces_vues WHERE annonce_id=? ORDER BY quand",
                              (int(aid),)) as cur:
            return [(int(m), int(q)) for m, q in await cur.fetchall()]


async def _ecrire(sql: str, args: tuple) -> int:
    async with _get_db() as db:
        cur = await db.execute(sql, args)
        await db.commit()
        return cur.lastrowid


# ═══════════════════════════════════════════════════════════════════════════════
#  Salons et rendu
# ═══════════════════════════════════════════════════════════════════════════════

def _mots(nom: str) -> list:
    return config_salons.normaliser(nom).split()


def destinations(g, c: dict) -> list:
    """Les salons où l'on annonce, dans l'ordre du serveur : Information, Sneak Peek (sauf les actus
    Roblox automatiques), les annonces du clan, et tout salon dont le nom dit « annonce »."""
    clan = int(c.get("clan_annonces", 0) or 0)
    out = []
    for ch in getattr(g, "text_channels", []) or []:
        cat = getattr(ch, "category", None)
        nc, mots = config_salons.normaliser(cat.name) if cat else "", _mots(ch.name)
        if any(m in mots for m in EXCLUS):
            continue
        if ch.id == clan or "information" in nc or "sneak" in nc or any(m.startswith("annonce") for m in mots):
            out.append(ch)
    out.sort(key=lambda s: (getattr(getattr(s, "category", None), "position", -1), s.position))
    return out[:25]


def style_de(salon, c: dict) -> tuple:
    cat = getattr(salon, "category", None)
    if salon.id == int(c.get("clan_annonces", 0) or 0) or (cat is not None and config_salons.est_clan(cat.name)):
        return STYLE_CLAN
    mots = " ".join(_mots(salon.name))
    for cles, *style in STYLES:
        if any(k in mots for k in cles):
            return tuple(style)
    return STYLE_DEFAUT


def lire_liens(texte: str) -> tuple:
    """« Nom | https://… » ou une adresse seule, une par ligne → ([(nom, url)], [erreurs])."""
    liens, erreurs = [], []
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        nom, _sep, url = ligne.rpartition("|") if "|" in ligne else ("", "", ligne)
        nom, url = nom.strip(), url.strip()
        if not URL.match(url) or len(url) > 512:
            erreurs.append(f"Lien ignoré (adresse invalide) : {ligne[:60]}")
            continue
        if not nom:
            nom = re.sub(r"^https?://(www\.)?", "", url, flags=re.I).split("/")[0][:80] or "Lien"
        liens.append((nom[:80], url))
    if len(liens) > LIENS_MAX:
        erreurs.append(f"Cinq liens au plus : les {len(liens) - LIENS_MAX} derniers sont ignorés.")
        liens = liens[:LIENS_MAX]
    return liens, erreurs


class BoutonVu(discord.ui.DynamicItem[Button], template=r"an:v:(?P<aid>\d+)"):
    """« Un système de coche verte pour que les gens aient vu l'annonce. »"""

    def __init__(self, aid: int, vues: int = 0):
        self.aid = int(aid)
        super().__init__(Button(label="Vu · Seen" + (f" · {vues}" if vues else ""), emoji="✅",
                                style=discord.ButtonStyle.success, custom_id=f"an:v:{int(aid)}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["aid"]))

    async def callback(self, i: discord.Interaction):
        await marquer_vu(i, self.aid)


def composants(a: dict, style: tuple, *, serveur: str = "", vues: int = 0, apercu: bool = False) -> list:
    """L'annonce : la mention (au-dessus, comme un message), puis la carte — l'image ou le bandeau,
    le titre, le texte, les liens, la signature et « ✅ Vu »."""
    cle, titre_bandeau, couleur = style
    items = []
    if a.get("image"):
        items.append(discord.ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{a['image']}")))
    else:
        items.append(visuels.bandeau(cle, titre_bandeau))
    items.append(discord.ui.TextDisplay(f"## {a['titre']}"))
    items.append(discord.ui.TextDisplay(a["texte"]))
    if a.get("liens"):
        items.append(discord.ui.ActionRow(*[Button(label=nom, url=url) for nom, url in a["liens"][:LIENS_MAX]]))
    items.append(discord.ui.Separator())
    pied = f"-# 📣 {serveur} · <t:{int(a['cree'])}:D>" if serveur else f"-# 📣 <t:{int(a['cree'])}:D>"
    vu = (Button(label="Vu · Seen", emoji="✅", style=discord.ButtonStyle.success, disabled=True) if apercu
          else BoutonVu(a["id"], vues))
    items.append(discord.ui.TextDisplay(pied))
    items.append(discord.ui.ActionRow(vu))
    out = [discord.ui.TextDisplay(a["mention"])] if a.get("mention") else []
    return out + [discord.ui.Container(*items, accent_color=discord.Color(couleur))]


def vue_annonce(a: dict, style: tuple, **kw) -> LayoutView:
    v = LayoutView(timeout=None)
    for x in composants(a, style, **kw):
        v.add_item(x)
    return v


# ═══════════════════════════════════════════════════════════════════════════════
#  « ✅ Vu »
# ═══════════════════════════════════════════════════════════════════════════════

async def marquer_vu(i, aid: int) -> None:
    langue = await langue_de(i)
    a = await charger(aid)
    if a is None or i.guild is None or a["guild_id"] != i.guild.id:
        return await i.response.send_message(tr("introuvable", langue), ephemeral=True)
    async with _get_db() as db:
        cur = await db.execute("INSERT OR IGNORE INTO annonces_vues(annonce_id, membre_id, quand) VALUES(?,?,?)",
                               (int(aid), i.user.id, int(time.time())))
        nouveau = (cur.rowcount or 0) > 0
        await db.commit()
    await i.response.send_message(tr("vu_ok" if nouveau else "vu_deja", langue), ephemeral=True)
    if nouveau:
        planifier_maj(i.guild, aid)


def planifier_maj(g, aid: int) -> None:
    """Le compteur se réécrit une fois pour toute une rafale de clics."""
    if aid not in _maj_prevues:
        _maj_prevues[aid] = asyncio.create_task(_maj_apres(g, aid))


async def _maj_apres(g, aid: int) -> None:
    try:
        await asyncio.sleep(MAJ_VUES_S)
    finally:
        _maj_prevues.pop(aid, None)
    await maj_annonce(g, aid)


async def maj_annonce(g, aid: int) -> bool:
    a = await charger(aid)
    salon = g.get_channel(int(a["salon_id"])) if a else None
    if a is None or salon is None or not a["message_id"]:
        return False
    vue = vue_annonce(a, style_de(salon, await _cfg(g.id)), serveur=g.name, vues=await compter_vues(aid))
    try:
        await salon.get_partial_message(int(a["message_id"])).edit(view=vue,
                                                                  allowed_mentions=discord.AllowedMentions.none())
        return True
    except discord.NotFound:
        return False
    except discord.HTTPException as ex:
        _log("[ANNONCES][E2] compteur non mis à jour")
        _log(f"[ANNONCES][E2:DETAIL] annonce={aid} {type(ex).__name__} {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Composer, aperçu, publier
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Brouillon:
    salon_id: int = 0
    titre: str = ""
    texte: str = ""
    liens: list = field(default_factory=list)
    image: bytes = b""
    image_ext: str = ""
    mention: str = ""          # "" · "everyone" · "clan"
    fil: bool = True

    @property
    def image_nom(self) -> str:
        return f"annonce.{self.image_ext}" if self.image else ""

    def fichier(self):
        return discord.File(io.BytesIO(self.image), filename=self.image_nom) if self.image else None


def _vue_message(texte: str, couleur=Palette.NEUTRAL) -> LayoutView:
    v = LayoutView(timeout=60)
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(texte), accent_color=couleur))
    return v


async def ouvrir(i) -> None:
    """Le bouton « Nouvelle annonce » (📋logs) : le fondateur et la direction seulement."""
    g, m = i.guild, i.user
    if g is None or not _est_tete(g, m):
        return await i.response.send_message("Réservé au fondateur et à la direction.", ephemeral=True)
    salons = destinations(g, await _cfg(g.id))
    if not salons:
        return await i.response.send_message("Aucun salon d'annonces trouvé (Information, Sneak Peek, annonces du "
                                             "clan).", ephemeral=True)
    await i.response.send_message(view=VueComposer(m, g, salons), ephemeral=True)


class VueComposer(LayoutView):
    def __init__(self, auteur, g, salons: list, b: Brouillon | None = None):
        super().__init__(timeout=1800)
        self.auteur, self.g, self.b = auteur, g, b or Brouillon()
        choix = Select(placeholder="Dans quel salon ?", options=[
            discord.SelectOption(label=f"#{ch.name}"[:100], value=str(ch.id),
                                 description=(getattr(getattr(ch, "category", None), "name", "") or None))
            for ch in salons])
        choix.callback = self._cb_salon
        self.add_item(discord.ui.Container(
            visuels.bandeau("an_annonce", "Annonce"),
            discord.ui.TextDisplay("### 📣 Nouvelle annonce\nChoisis le salon : un formulaire s'ouvre (titre, texte, "
                                   "liens, image). Tu verras l'aperçu exact avant de publier."),
            discord.ui.ActionRow(choix), accent_color=discord.Color(STYLE_DEFAUT[2])))

    async def interaction_check(self, i):
        return i.user.id == self.auteur.id

    async def _cb_salon(self, i):
        self.b.salon_id = int(i.data["values"][0])
        await i.response.send_modal(FormulaireAnnonce(self))


class FormulaireAnnonce(discord.ui.Modal):
    def __init__(self, porteur):
        super().__init__(title="📣 Annonce", timeout=1800)
        self.porteur, b = porteur, porteur.b
        self.titre = discord.ui.TextInput(max_length=TITRE_MAX, default=b.titre or None,
                                          placeholder="Ex. La mise à jour 2.4 est là")
        self.texte = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=TEXTE_MAX,
                                          default=b.texte or None, placeholder="Le texte de l'annonce…")
        self.liens = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=800, required=False,
                                          default="\n".join(f"{n} | {u}" for n, u in b.liens) or None,
                                          placeholder="Un lien par ligne : Twitch | https://twitch.tv/…")
        self.image = discord.ui.FileUpload(required=False, max_values=1)
        self.add_item(discord.ui.Label(text="Titre", component=self.titre))
        self.add_item(discord.ui.Label(text="Texte", component=self.texte,
                                       description="Gras, listes, liens : comme dans un message Discord."))
        self.add_item(discord.ui.Label(text="Liens (facultatif)", component=self.liens,
                                       description="Cinq boutons au plus sous l'annonce."))
        self.add_item(discord.ui.Label(text="Image (facultatif)", component=self.image,
                                       description="Garde l'image actuelle si tu n'en mets pas." if b.image else
                                       "Sinon, le bandeau du salon."))

    async def on_submit(self, i: discord.Interaction):
        await soumettre(i, self)


async def soumettre(i, f: FormulaireAnnonce) -> None:
    """Le formulaire envoyé : on lit tout, puis le message du composer devient l'aperçu."""
    await i.response.defer()
    p = f.porteur
    b = p.b
    b.titre = " ".join(str(f.titre.value or "").split())[:TITRE_MAX]
    b.texte = str(f.texte.value or "").strip()[:TEXTE_MAX]
    b.liens, erreurs = lire_liens(f.liens.value or "")
    pieces = list(getattr(f.image, "values", None) or [])
    if pieces:
        piece = pieces[0]
        ext = TYPES_IMAGE.get(str(piece.content_type or "").split(";")[0].strip().lower())
        if ext is None:
            erreurs.append("L'image doit être un PNG, un JPG, un GIF ou un WebP.")
        elif int(piece.size or 0) > IMAGE_MAX:
            erreurs.append("L'image dépasse 8 Mo.")
        else:
            try:
                b.image, b.image_ext = await piece.read(), ext
            except discord.HTTPException as ex:
                _log(f"[ANNONCES:DETAIL] image illisible {type(ex).__name__} {ex}")
                erreurs.append("Impossible de lire l'image : renvoie-la.")
    vue = VueApercu(p.auteur, p.g, b, erreurs, await _cfg(p.g.id))
    piece_jointe = b.fichier()
    await i.edit_original_response(view=vue, attachments=[piece_jointe] if piece_jointe else [])


def _mention(g, salon, c: dict, b: Brouillon) -> tuple:
    """(le texte affiché, les mentions permises, un avertissement)."""
    if b.mention == "everyone":
        peut = salon.permissions_for(g.me).mention_everyone
        return ("@everyone", discord.AllowedMentions(everyone=True, users=False, roles=False),
                "" if peut else "⚠️ Je n'ai pas le droit de mentionner @everyone ici : personne ne sera notifié.")
    if b.mention == "clan":
        role = _role_clan(g, c) if _role_clan else None
        if role is not None:
            return role.mention, discord.AllowedMentions(everyone=False, users=False, roles=[role]), ""
    return "", discord.AllowedMentions.none(), ""


class VueApercu(LayoutView):
    """L'aperçu exact (seul l'auteur le voit), puis : Publier · Modifier · Annuler, la mention, le fil."""

    def __init__(self, auteur, g, b: Brouillon, erreurs=(), c: dict | None = None):
        super().__init__(timeout=1800)
        self.auteur, self.g, self.b = auteur, g, b
        salon = g.get_channel(b.salon_id)
        c = c or {}
        texte_mention, _m, avertissement = _mention(g, salon, c, b) if salon is not None else ("", None, "")
        a = {"id": 0, "titre": b.titre or "(sans titre)", "texte": b.texte or "(sans texte)", "liens": b.liens,
             "image": b.image_nom, "mention": texte_mention, "cree": int(time.time())}
        if salon is not None:
            for x in composants(a, style_de(salon, c), serveur=g.name, apercu=True):
                self.add_item(x)
        notes = [f"-# Aperçu : toi seul le vois · salon {salon.mention if salon else 'introuvable'}"]
        notes += [f"⚠️ {e}" if not e.startswith("⚠️") else e for e in list(erreurs) + ([avertissement]
                                                                                         if avertissement else [])]
        publier_b = Button(label="Publier", style=discord.ButtonStyle.success, emoji=visuels.icone("valider"),
                           disabled=salon is None or not (b.titre and b.texte))
        publier_b.callback = self._cb_publier
        modifier = Button(label="Modifier", style=discord.ButtonStyle.secondary, emoji=visuels.icone("modifier"))
        modifier.callback = self._cb_modifier
        annuler = Button(label="Annuler", style=discord.ButtonStyle.secondary, emoji=visuels.icone("annuler"))
        annuler.callback = self._cb_annuler
        options_mention = ["", "everyone"] + (["clan"] if salon is not None and style_de(salon, c) == STYLE_CLAN
                                              and _role_clan and _role_clan(g, c) is not None else [])
        self.options_mention = options_mention
        libelle = {"": "Mention : personne", "everyone": "Mention : @everyone", "clan": "Mention : le clan"}
        mention = Button(label=libelle.get(b.mention, "Mention : personne"), style=discord.ButtonStyle.secondary,
                         emoji=visuels.icone("cloche" if b.mention else "cloche_off"))
        mention.callback = self._cb_mention
        fil = Button(label="Fil de suite : " + ("oui" if b.fil else "non"), style=discord.ButtonStyle.secondary,
                     emoji="🧵")
        fil.callback = self._cb_fil
        self.add_item(discord.ui.Container(discord.ui.TextDisplay("\n".join(notes)),
                                           discord.ui.ActionRow(publier_b, modifier, annuler),
                                           discord.ui.ActionRow(mention, fil), accent_color=Palette.NEUTRAL))

    async def interaction_check(self, i):
        return i.user.id == self.auteur.id

    async def _reafficher(self, i):
        await i.response.edit_message(view=VueApercu(self.auteur, self.g, self.b, (), await _cfg(self.g.id)))

    async def _cb_mention(self, i):
        opts = self.options_mention
        self.b.mention = opts[(opts.index(self.b.mention) + 1) % len(opts)] if self.b.mention in opts else ""
        await self._reafficher(i)

    async def _cb_fil(self, i):
        self.b.fil = not self.b.fil
        await self._reafficher(i)

    async def _cb_modifier(self, i):
        await i.response.send_modal(FormulaireAnnonce(self))

    async def _cb_annuler(self, i):
        await i.response.edit_message(view=_vue_message("Annonce abandonnée : rien n'a été publié."), attachments=[])

    async def _cb_publier(self, i):
        await i.response.defer()
        lien, erreur = await publier(self.g, self.auteur, self.b)
        if erreur:
            return await i.edit_original_response(view=_vue_message(erreur, Palette.WARNING), attachments=[])
        await i.edit_original_response(view=_vue_message(f"✅ Annonce publiée : {lien}", Palette.SUCCESS),
                                       attachments=[])


async def publier(g, auteur, b: Brouillon) -> tuple:
    """Publie l'annonce (et son fil). Rend (lien, "") ou ("", raison)."""
    salon = g.get_channel(int(b.salon_id or 0))
    if not isinstance(salon, discord.TextChannel):
        return "", "Ce salon n'existe plus."
    if not (b.titre and b.texte):
        return "", "Il faut un titre et un texte."
    droits = salon.permissions_for(g.me)
    if not (droits.send_messages and droits.embed_links and (droits.attach_files or not b.image)):
        return "", f"Je ne peux pas publier dans {salon.mention} (droits du salon)."
    c = await _cfg(g.id)
    texte_mention, mentions, _avert = _mention(g, salon, c, b)
    t = int(time.time())
    aid = await _ecrire("INSERT INTO annonces(guild_id, salon_id, auteur_id, titre, texte, liens, image, mention, cree)"
                        " VALUES(?,?,?,?,?,?,?,?,?)", (g.id, salon.id, auteur.id, b.titre, b.texte,
                                                       json.dumps(b.liens, ensure_ascii=False), b.image_nom,
                                                       texte_mention, t))
    a = {"id": aid, "titre": b.titre, "texte": b.texte, "liens": b.liens, "image": b.image_nom,
         "mention": texte_mention, "cree": t}
    envoi = {"view": vue_annonce(a, style_de(salon, c), serveur=g.name), "allowed_mentions": mentions}
    if b.image:
        envoi["file"] = b.fichier()
    try:
        msg = await salon.send(**envoi)
    except discord.HTTPException as ex:
        _log("[ANNONCES][E1] annonce non publiée")
        _log(f"[ANNONCES][E1:DETAIL] salon={salon.id} {type(ex).__name__} {ex}")
        await _ecrire("DELETE FROM annonces WHERE id=?", (aid,))
        return "", "Discord a refusé la publication : réessaie dans un instant."
    fil_id = 0
    if b.fil:
        try:
            fil = await msg.create_thread(name=f"📌 {b.titre}"[:100], auto_archive_duration=10080,
                                          reason="Annonce : la suite dans son fil")
            fil_id = fil.id
        except discord.HTTPException as ex:
            _log(f"[ANNONCES:DETAIL] fil non créé annonce={aid} {type(ex).__name__} {ex}")
    await _ecrire("UPDATE annonces SET message_id=?, fil_id=? WHERE id=?", (msg.id, fil_id, aid))
    await _journal(g, "annonce.publiee", f"{auteur.mention} a publié une annonce dans {salon.mention} : {b.titre}",
                   auteur_id=auteur.id)
    return msg.jump_url, ""


class BoutonComposer(discord.ui.DynamicItem[Button], template=r"an:new"):
    """Dans le menu de 📋logs : « Nouvelle annonce »."""

    def __init__(self):
        super().__init__(Button(label="Nouvelle annonce", custom_id="an:new", style=discord.ButtonStyle.primary,
                                emoji="📣"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        await ouvrir(i)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le clan : une arrivée s'annonce d'elle-même
# ═══════════════════════════════════════════════════════════════════════════════

async def sur_maj_membre(before, after) -> None:
    """Le rôle du clan vient d'être donné : la bienvenue dans les annonces du clan (les arrivées
    d'une même minute partagent une carte)."""
    g = getattr(after, "guild", None)
    if g is None or getattr(after, "bot", False) or _role_clan is None:
        return
    c = await _cfg(g.id)
    role = _role_clan(g, c)
    if role is None or role in before.roles or role not in after.roles:
        return
    if g.get_channel(int(c.get("clan_annonces", 0) or 0)) is None:
        return
    file = _arrivees.setdefault(g.id, [])
    if after.id not in file:
        file.append(after.id)
    if len(file) == 1:
        asyncio.create_task(_annoncer_arrivees(g))


async def _annoncer_arrivees(g) -> None:
    await asyncio.sleep(ARRIVEES_S)
    ids = _arrivees.pop(g.id, [])
    c = await _cfg(g.id)
    salon = g.get_channel(int(c.get("clan_annonces", 0) or 0))
    membres = [m for m in (g.get_member(x) for x in ids) if m is not None]
    if salon is None or not membres:
        return
    noms = ", ".join(m.mention for m in membres)
    items = []
    if len(membres) == 1 and getattr(membres[0], "display_avatar", None) is not None:
        items.append(discord.ui.Section(
            discord.ui.TextDisplay("### 🎉 Bienvenue dans l'équipage · Welcome aboard"),
            discord.ui.TextDisplay(f"{noms} rejoint le clan GoRP · joins the GoRP clan."),
            accessory=discord.ui.Thumbnail(membres[0].display_avatar.url)))
    else:
        items += [discord.ui.TextDisplay("### 🎉 Bienvenue dans l'équipage · Welcome aboard"),
                  discord.ui.TextDisplay(f"{noms} rejoignent le clan GoRP · join the GoRP clan.")]
    items.append(discord.ui.TextDisplay("-# Présentez-vous dans le chat du clan · Say hi in the clan chat"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=discord.Color(STYLE_CLAN[2])))
    try:
        await salon.send(view=v, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False,
                                                                          users=membres))
    except discord.HTTPException as ex:
        _log("[ANNONCES][E3] bienvenue du clan non publiée")
        _log(f"[ANNONCES][E3:DETAIL] {type(ex).__name__} {ex}")
