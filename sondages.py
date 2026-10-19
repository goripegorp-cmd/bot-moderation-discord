"""sondages.py — de vrais sondages Discord, créés par les membres en un bouton (19/10/2026).

Un salon dédié, créé une fois par le bot puis déplaçable n'importe où : il est suivi par
son identifiant. Personne n'y écrit ; le panneau tout en bas ouvre un formulaire (question,
réponses, durée, choix multiple) et le bot publie un sondage NATIF — Discord gère les votes,
les résultats et la clôture : aucune base de votes, aucun bouton de vote à maintenir.
Garde-fous : filtres du serveur sur le texte, pas de lien ni de mention, un sondage en cours
et trois par jour par membre (le staff n'a pas de limite).
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ui import Button, ChannelSelect

from ui_v2 import (
    LayoutView, Palette, body as v2_body, container as v2_container,
    divider as v2_divider, section as v2_section, title as v2_title,
)

NOM_SALON = "📊・sondages"
DUREES = (("1 heure", 1), ("4 heures", 4), ("12 heures", 12),
          ("1 jour", 24), ("3 jours", 72), ("7 jours", 168))
DUREE_DEFAUT = 24
MAX_QUESTION = 300          # limites de Discord
MAX_REPONSE = 55
MIN_REPONSES, MAX_REPONSES = 2, 10
EN_COURS_PAR_MEMBRE = 1
PAR_JOUR = 3
_FORMAT = "%Y-%m-%d %H:%M:%S"   # comme CURRENT_TIMESTAMP : comparable par SQLite

_get_db = _cfg = _db_set = None
_texte_refuse = _controle = _retour = None
_log = print
_verrous: dict = {}
_rappels: dict = {}


def setup(*, get_db, cfg, db_set, texte_refuse, controle, log=None):
    """`texte_refuse(guild, texte) -> str` (raison, ou "") ; `controle(membre, cfg) -> str`."""
    global _get_db, _cfg, _db_set, _texte_refuse, _controle, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    _texte_refuse, _controle = texte_refuse, controle
    _log = log or print


def set_retour(fn):
    global _retour
    _retour = fn


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS sondages ("
            " message_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,"
            " channel_id INTEGER NOT NULL, auteur_id INTEGER NOT NULL,"
            " question TEXT NOT NULL, cree_le TEXT NOT NULL, fin_le TEXT NOT NULL,"
            " termine INTEGER NOT NULL DEFAULT 0)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sondages_auteur "
                         "ON sondages(guild_id, auteur_id, cree_le)")
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Règles pures
# ═══════════════════════════════════════════════════════════════════════════════

def lire_reponses(texte: str) -> list:
    """Une réponse par ligne ; puces et numéros retirés, doublons ignorés."""
    vues, out = set(), []
    for ligne in (texte or "").splitlines():
        r = re.sub(r"^\s*(?:[-•*·]|\d{1,2}[.)])\s*", "", ligne)
        r = re.sub(r"\s+", " ", r).strip()
        if r and r.casefold() not in vues:
            vues.add(r.casefold())
            out.append(r)
    return out


def verifier(question: str, reponses: list) -> str:
    """Raison du refus, ou ""."""
    q = (question or "").strip()
    if not q:
        return "Écris une question."
    if len(q) > MAX_QUESTION:
        return f"La question dépasse {MAX_QUESTION} caractères."
    if len(reponses) < MIN_REPONSES:
        return "Il faut au moins 2 réponses, une par ligne."
    if len(reponses) > MAX_REPONSES:
        return "10 réponses au maximum."
    trop = next((r for r in reponses if len(r) > MAX_REPONSE), None)
    if trop:
        return f"« {trop[:40]}… » dépasse {MAX_REPONSE} caractères."
    return ""


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def est_staff(membre) -> bool:
    p = getattr(membre, "guild_permissions", None)
    return bool(p and (p.administrator or p.manage_messages))


# ═══════════════════════════════════════════════════════════════════════════════
#  Salon et panneau
# ═══════════════════════════════════════════════════════════════════════════════

async def salon_de(g):
    c = await _cfg(g.id)
    salon = g.get_channel(int(c.get("sondages_salon", 0) or 0))
    return salon if isinstance(salon, discord.TextChannel) else None


async def ouverts(g) -> bool:
    return bool((await _cfg(g.id)).get("sondages_actifs", 1))


def vue_panneau(ouvert: bool = True) -> LayoutView:
    v = LayoutView(timeout=None)
    b = BoutonCreer()
    b.item.disabled = not ouvert
    v.add_item(v2_container(
        v2_section(v2_title("📊 Sondages"),
                   v2_body("Pose ta question, la communauté vote." if ouvert
                           else "Fermés pour le moment."),
                   accessory=b),
        color=Palette.PRIMARY))
    return v


def _verrou(gid):
    return _verrous.setdefault(gid, asyncio.Lock())


async def reposer_panneau(g, salon=None) -> None:
    """Le bouton reste le dernier message du salon : l'ancien part, un neuf arrive."""
    async with _verrou(g.id):
        try:
            salon = salon or await salon_de(g)
            if salon is None:
                return
            c = await _cfg(g.id)
            ancien = int(c.get("sondages_panneau", 0) or 0)
            if ancien:
                try:
                    await salon.get_partial_message(ancien).delete()
                except discord.NotFound:
                    pass
            msg = await salon.send(view=vue_panneau(bool(c.get("sondages_actifs", 1))))
            await _db_set(g.id, "sondages_panneau", msg.id)
        except discord.HTTPException as ex:
            _log(f"[SONDAGES] panneau : {type(ex).__name__} {ex}")


async def assurer_panneau(g) -> None:
    """Pose le panneau s'il a disparu (salon purgé, message supprimé)."""
    salon = await salon_de(g)
    if salon is None:
        return
    pid = int((await _cfg(g.id)).get("sondages_panneau", 0) or 0)
    if pid:
        try:
            await salon.fetch_message(pid)
            return
        except discord.NotFound:
            pass
        except discord.HTTPException as ex:
            _log(f"[SONDAGES] lecture du panneau : {ex}")
            return
    await reposer_panneau(g, salon)


async def creer_salon(g):
    """Salon en lecture seule pour les membres : ils votent, le bot publie."""
    me = g.me
    salon = await g.create_text_channel(
        NOM_SALON, reason="Sondages : salon dédié",
        topic="Les sondages de la communauté — bouton tout en bas.",
        overwrites={
            g.default_role: discord.PermissionOverwrite(
                send_messages=False, send_polls=False, add_reactions=False,
                create_public_threads=False, create_private_threads=False),
            me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, send_polls=True,
                manage_messages=True, read_message_history=True, embed_links=True),
        })
    await _db_set(g.id, "sondages_salon", salon.id)
    await _db_set(g.id, "sondages_panneau", 0)
    await reposer_panneau(g, salon)
    return salon


async def installer(g) -> None:
    """Au démarrage : le salon est créé UNE fois (ensuite il appartient au propriétaire,
    qui le déplace ou le supprime), puis le panneau est assuré."""
    try:
        c = await _cfg(g.id)
        if not c.get("sondages_installes"):
            me = g.me
            if me and me.guild_permissions.manage_channels and not c.get("sondages_salon"):
                await creer_salon(g)
            await _db_set(g.id, "sondages_installes", 1)
        await assurer_panneau(g)
    except discord.HTTPException as ex:
        _log(f"[SONDAGES] installation : {type(ex).__name__} {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Création
# ═══════════════════════════════════════════════════════════════════════════════

async def _limite(g, membre) -> str:
    if est_staff(membre):
        return ""
    maintenant = _maintenant()
    async with _get_db() as db:
        async with db.execute(
                "SELECT message_id, channel_id FROM sondages WHERE guild_id=? AND auteur_id=? "
                "AND termine=0 AND fin_le>? ORDER BY cree_le DESC",
                (g.id, membre.id, maintenant.strftime(_FORMAT))) as cur:
            en_cours = await cur.fetchall()
        async with db.execute(
                "SELECT cree_le FROM sondages WHERE guild_id=? AND auteur_id=? AND cree_le>? "
                "ORDER BY cree_le", (g.id, membre.id,
                                    (maintenant - timedelta(days=1)).strftime(_FORMAT))) as cur:
            du_jour = [r[0] for r in await cur.fetchall()]
    if len(en_cours) >= EN_COURS_PAR_MEMBRE:
        mid, cid = en_cours[0]
        return (f"Tu as déjà un sondage en cours : "
                f"https://discord.com/channels/{g.id}/{cid}/{mid}")
    if len(du_jour) >= PAR_JOUR:
        libre = datetime.strptime(du_jour[0], _FORMAT).replace(tzinfo=timezone.utc) + timedelta(days=1)
        return f"{PAR_JOUR} sondages par jour au maximum — le prochain <t:{int(libre.timestamp())}:R>."
    return ""


async def peut_creer(i) -> str:
    g, m = i.guild, i.user
    if g is None or getattr(m, "guild_permissions", None) is None:
        return "Les sondages se créent sur le serveur."
    if not await ouverts(g) or await salon_de(g) is None:
        return "Les sondages sont fermés pour le moment."
    if m.is_timed_out():
        return "Tu ne peux pas créer de sondage pendant une exclusion temporaire."
    raison = await _controle(m, await _cfg(g.id))
    return raison or await _limite(g, m)


class Formulaire(discord.ui.Modal, title="Nouveau sondage"):
    def __init__(self, question="", reponses="", heures=DUREE_DEFAUT, multiple=False):
        super().__init__(timeout=900)
        self.q = discord.ui.TextInput(max_length=MAX_QUESTION, default=question or None,
                                      placeholder="Ta question")
        self.r = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=700,
                                      default=reponses or None,
                                      placeholder="Oui\nNon\nPeut-être")
        self.d = discord.ui.Select(options=[
            discord.SelectOption(label=libelle, value=str(h), default=h == heures)
            for libelle, h in DUREES])
        self.m = discord.ui.Select(options=[
            discord.SelectOption(label="Un seul choix", value="0", default=not multiple),
            discord.SelectOption(label="Plusieurs choix", value="1", default=multiple)])
        self.add_item(discord.ui.Label(text="Question", component=self.q))
        self.add_item(discord.ui.Label(text="Réponses", description="Une par ligne, de 2 à 10",
                                       component=self.r))
        self.add_item(discord.ui.Label(text="Durée", component=self.d))
        self.add_item(discord.ui.Label(text="Votes", component=self.m))

    async def on_submit(self, i: discord.Interaction):
        heures = int(self.d.values[0]) if self.d.values else DUREE_DEFAUT
        multiple = bool(self.m.values) and self.m.values[0] == "1"
        await publier(i, self.q.value, self.r.value, heures, multiple)


def vue_corriger(auteur_id, erreur, *valeurs) -> LayoutView:
    """L'erreur, et « Corriger » qui rouvre le formulaire avec ce qui avait été écrit."""
    v = LayoutView(timeout=900)
    b = Button(label="Corriger", emoji="✏️", style=discord.ButtonStyle.primary)

    async def _cb(i: discord.Interaction):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.send_modal(Formulaire(*valeurs))
    b.callback = _cb
    v.add_item(v2_container(v2_body(f"⚠️ {erreur}"), discord.ui.ActionRow(b),
                            color=Palette.WARNING))
    return v


async def publier(i, question, reponses_txt, heures, multiple):
    g, m = i.guild, i.user
    reponses = lire_reponses(reponses_txt)
    erreur = verifier(question, reponses) or await _texte_refuse(
        g, "\n".join([question] + reponses))
    if erreur:
        return await i.response.send_message(
            view=vue_corriger(m.id, erreur, question, reponses_txt, heures, multiple),
            ephemeral=True)
    refus = await peut_creer(i)
    if refus:
        return await i.response.send_message(f"⚠️ {refus}", ephemeral=True)
    await i.response.defer(ephemeral=True, thinking=True)
    salon = await salon_de(g)
    sondage = discord.Poll(question=question.strip(), duration=timedelta(hours=heures),
                           multiple=multiple)
    for r in reponses:
        sondage.add_answer(text=r)
    vue = discord.ui.View(timeout=None)
    vue.add_item(BoutonTerminer(m.id))
    mentions = discord.AllowedMentions.none()
    try:
        try:
            msg = await salon.send(f"Sondage de {m.mention}", poll=sondage, view=vue,
                                   allowed_mentions=mentions)
        except discord.HTTPException as ex:
            if isinstance(ex, discord.Forbidden):
                raise
            _log(f"[SONDAGES] envoi avec bouton refusé : {ex}")
            msg = await salon.send(f"Sondage de {m.mention}", poll=sondage,
                                   allowed_mentions=mentions)
    except discord.Forbidden:
        return await i.followup.send(f"⚠️ Je n'ai pas le droit de publier dans {salon.mention}.",
                                     ephemeral=True)
    except discord.HTTPException as ex:
        _log(f"[SONDAGES] envoi refusé : {ex}")
        return await i.followup.send("⚠️ Discord a refusé ce sondage. Réessaie.", ephemeral=True)
    maintenant = _maintenant()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO sondages(message_id, guild_id, channel_id, auteur_id, "
                "question, cree_le, fin_le, termine) VALUES(?,?,?,?,?,?,?,0)",
                (msg.id, g.id, salon.id, m.id, question.strip()[:MAX_QUESTION],
                 maintenant.strftime(_FORMAT),
                 (maintenant + timedelta(hours=heures)).strftime(_FORMAT)))
            await db.commit()
    except Exception as ex:
        _log(f"[SONDAGES] enregistrement : {ex}")
    await i.followup.send(f"✅ Sondage publié : {msg.jump_url}", ephemeral=True)
    asyncio.create_task(reposer_panneau(g, salon))


class BoutonCreer(discord.ui.DynamicItem[Button], template=r"sdg:creer"):
    def __init__(self):
        super().__init__(Button(label="Créer un sondage", emoji="📊",
                                style=discord.ButtonStyle.primary, custom_id="sdg:creer"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        refus = await peut_creer(i)
        if refus:
            return await i.response.send_message(f"⚠️ {refus}", ephemeral=True)
        await i.response.send_modal(Formulaire())


class BoutonTerminer(discord.ui.DynamicItem[Button], template=r"sdg:fin:(?P<auteur>\d+)"):
    def __init__(self, auteur: int):
        self.auteur = int(auteur)
        super().__init__(Button(label="Terminer", emoji="⏹️",
                                style=discord.ButtonStyle.secondary,
                                custom_id=f"sdg:fin:{self.auteur}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["auteur"]))

    async def callback(self, i: discord.Interaction):
        msg = i.message
        if i.user.id != self.auteur and not est_staff(i.user):
            return await i.response.send_message(
                "Seul l'auteur ou le staff peut terminer ce sondage.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        try:
            await msg.end_poll()
        except discord.HTTPException as ex:
            if ex.status != 400:                      # 400 : déjà terminé
                _log(f"[SONDAGES] fin : {ex}")
                return await i.followup.send("⚠️ Impossible de terminer ce sondage.",
                                             ephemeral=True)
        try:
            await msg.edit(view=None)
        except discord.HTTPException:
            pass
        await marquer_termine(msg.id)
        await i.followup.send("⏹️ Sondage terminé.", ephemeral=True)


async def marquer_termine(message_id) -> None:
    try:
        async with _get_db() as db:
            await db.execute("UPDATE sondages SET termine=1 WHERE message_id=?", (int(message_id),))
            await db.commit()
    except Exception as ex:
        _log(f"[SONDAGES] marquer terminé : {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Écouteurs (branchés par bot.py)
# ═══════════════════════════════════════════════════════════════════════════════

async def sur_message(msg: discord.Message) -> None:
    """Fin d'un sondage : le bouton « Terminer » part et le panneau revient en bas.
    Un message posé à la main (droits resynchronisés par une catégorie) est retiré."""
    g = msg.guild
    if g is None or _cfg is None:
        return
    try:
        salon = await salon_de(g)
        if salon is None or msg.channel.id != salon.id:
            return
        if msg.type == discord.MessageType.poll_result:
            ref = msg.reference.message_id if msg.reference else None
            if ref:
                await marquer_termine(ref)
                try:
                    await salon.get_partial_message(ref).edit(view=None)
                except discord.HTTPException:
                    pass
            await reposer_panneau(g, salon)
            return
        if msg.author.bot or msg.webhook_id or est_staff(msg.author):
            return
        try:
            await msg.delete()
        except discord.HTTPException:
            return
        cle = (g.id, msg.author.id)
        if time.monotonic() - _rappels.get(cle, -1e9) > 600:
            _rappels[cle] = time.monotonic()
            await salon.send(f"{msg.author.mention} 📊 Ici, on crée un sondage avec le bouton en bas.",
                             delete_after=10, allowed_mentions=discord.AllowedMentions(users=True))
    except Exception as ex:
        _log(f"[SONDAGES] message : {type(ex).__name__} {ex}")


async def sur_suppression(payload) -> None:
    if _get_db is not None and payload.guild_id:
        await marquer_termine(payload.message_id)


async def sur_salon_supprime(channel) -> None:
    g = getattr(channel, "guild", None)
    if g is None or _cfg is None:
        return
    c = await _cfg(g.id)
    if int(c.get("sondages_salon", 0) or 0) == channel.id:
        await _db_set(g.id, "sondages_salon", 0)
        await _db_set(g.id, "sondages_panneau", 0)


# ═══════════════════════════════════════════════════════════════════════════════
#  /configure → Sondages
# ═══════════════════════════════════════════════════════════════════════════════

class SondagesPanelV2(LayoutView):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g, self._note = u, g, ""

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def render_to(self, i, *, edit: bool = True):
        try:
            salon = await salon_de(self.g)
            actifs = await ouverts(self.g)
            etat = ("🟢 **Ouverts**" if actifs else "⚪ **Fermés**") + " · " + (
                salon.mention if salon else "⚪ _aucun salon_")
            items = [v2_title("📊 Sondages"), v2_body(etat)]
            if self._note:
                items += [v2_divider(), v2_body(self._note)]
            sel = ChannelSelect(channel_types=[discord.ChannelType.text],
                                placeholder="Salon des sondages…", min_values=1, max_values=1)
            sel.callback = self._cb_salon
            b_on = Button(label="Ouverts" if actifs else "Fermés",
                          emoji="🟢" if actifs else "⚪",
                          style=discord.ButtonStyle.success if actifs else discord.ButtonStyle.secondary)
            b_on.callback = self._cb_basculer
            boutons = [b_on]
            if salon is None:
                b_creer = Button(label="Créer le salon", emoji="➕", style=discord.ButtonStyle.primary)
                b_creer.callback = self._cb_creer
                boutons.append(b_creer)
            else:
                b_repos = Button(label="Reposer le bouton", emoji="🔄",
                                 style=discord.ButtonStyle.secondary)
                b_repos.callback = self._cb_reposer
                boutons.append(b_repos)
            b_retour = Button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary)
            b_retour.callback = self._cb_retour
            boutons.append(b_retour)
            items += [discord.ui.ActionRow(sel), discord.ui.ActionRow(*boutons)]
            self.clear_items()
            self.add_item(v2_container(*items, color=Palette.PRIMARY))
            if not edit:
                return await i.response.send_message(view=self, ephemeral=True)
            if i.response.is_done():
                await i.edit_original_response(content=None, view=self, embed=None, attachments=[])
            else:
                await i.response.edit_message(content=None, view=self, embed=None, attachments=[])
        except Exception as ex:
            _log(f"[SONDAGES] panneau de configuration : {type(ex).__name__} {ex}")

    async def _cb_salon(self, i):
        await i.response.defer()
        nouveau = self.g.get_channel(int(i.data["values"][0]))
        ancien = await salon_de(self.g)
        if ancien is not None and nouveau is not None and ancien.id != nouveau.id:
            pid = int((await _cfg(self.g.id)).get("sondages_panneau", 0) or 0)
            if pid:
                try:
                    await ancien.get_partial_message(pid).delete()
                except discord.HTTPException:
                    pass
        await _db_set(self.g.id, "sondages_salon", int(i.data["values"][0]))
        await _db_set(self.g.id, "sondages_panneau", 0)
        await reposer_panneau(self.g)
        self._note = ""
        await self.render_to(i)

    async def _cb_basculer(self, i):
        await i.response.defer()
        await _db_set(self.g.id, "sondages_actifs", 0 if await ouverts(self.g) else 1)
        await reposer_panneau(self.g)
        await self.render_to(i)

    async def _cb_creer(self, i):
        await i.response.defer()
        try:
            salon = await creer_salon(self.g)
            self._note = f"✅ {salon.mention} créé — déplace-le où tu veux."
        except discord.HTTPException as ex:
            _log(f"[SONDAGES] création du salon : {ex}")
            self._note = "⚠️ Il me manque le droit de gérer les salons."
        await self.render_to(i)

    async def _cb_reposer(self, i):
        await i.response.defer()
        await reposer_panneau(self.g)
        self._note = "✅ Bouton reposé en bas du salon."
        await self.render_to(i)

    async def _cb_retour(self, i):
        if _retour is not None:
            await _retour(self.u, self.g, i)
        else:
            await i.response.defer()
