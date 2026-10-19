"""suggestions.py — de vraies suggestions (19/10/2026).

Un salon « 💡suggestions » créé une fois par le bot, puis à son propriétaire. Le panneau du
bas ouvre un formulaire (titre, détails). Chaque idée devient une fiche : vote Pour/Contre
(un par membre, modifiable), un fil pour en discuter, et le staff qui tranche — à l'étude,
acceptée, refusée, réalisée — avec sa réponse, annoncée à l'auteur dans le fil.
Chaque idée a sa fiche dans « 💡logs-suggestions », tenue à jour jusqu'à la décision.
Rôle « 🔔 Suggestions » pris d'un clic ; personne n'est prévenu au départ.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ui import Button, ChannelSelect

import notifs
import visuels
from ui_v2 import LayoutView, Palette

NOM_SALON = "💡suggestions"
NOM_LOGS = "💡logs-suggestions"
MAX_TITRE, MAX_DETAILS = 100, 1500
PAR_JOUR = 3
_FORMAT = "%Y-%m-%d %H:%M:%S"
STATUTS = {
    "attente": ("En attente", "🟡", Palette.WARNING),
    "etude": ("À l'étude", "🔵", Palette.INFO),
    "acceptee": ("Acceptée", "🟢", Palette.SUCCESS),
    "refusee": ("Refusée", "🔴", Palette.DANGER),
    "realisee": ("Réalisée", "✅", Palette.SUCCESS),
}
FINAUX = {"acceptee", "refusee", "realisee"}

_get_db = _cfg = _db_set = None
_texte_refuse = _controle = _salon_logs = _retour = None
_log = print
_verrous: dict = {}
_rappels: dict = {}
_a_rafraichir: dict = {}


def setup(*, get_db, cfg, db_set, texte_refuse, controle, salon_logs, log=None):
    global _get_db, _cfg, _db_set, _texte_refuse, _controle, _salon_logs, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    _texte_refuse, _controle, _salon_logs = texte_refuse, controle, salon_logs
    _log = log or print


def set_retour(fn):
    global _retour
    _retour = fn


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS suggestions_v2 ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,"
            " channel_id INTEGER NOT NULL, message_id INTEGER, thread_id INTEGER,"
            " auteur_id INTEGER NOT NULL, titre TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',"
            " statut TEXT NOT NULL DEFAULT 'attente', note TEXT NOT NULL DEFAULT '',"
            " decide_par INTEGER, cree_le TEXT NOT NULL, decide_le TEXT, log_message_id INTEGER)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_v2_auteur "
                         "ON suggestions_v2(guild_id, auteur_id, cree_le)")
        await db.execute("CREATE TABLE IF NOT EXISTS suggestions_votes ("
                         " suggestion_id INTEGER NOT NULL, user_id INTEGER NOT NULL,"
                         " vote INTEGER NOT NULL, PRIMARY KEY(suggestion_id, user_id))")
        await db.commit()


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def est_staff(membre) -> bool:
    p = getattr(membre, "guild_permissions", None)
    return bool(p and (p.administrator or p.manage_messages))


def barre(part: float, largeur: int = 16) -> str:
    plein = round(max(0.0, min(1.0, part)) * largeur)
    return "▰" * plein + "▱" * (largeur - plein)


def verifier(titre: str, details: str) -> str:
    if not (titre or "").strip():
        return "Donne un titre à ton idée."
    if len(titre) > MAX_TITRE or len(details or "") > MAX_DETAILS:
        return "Ton idée est trop longue."
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Salon et panneau
# ═══════════════════════════════════════════════════════════════════════════════

async def salon_de(g):
    c = await _cfg(g.id)
    salon = g.get_channel(int(c.get("suggestions_salon", 0) or 0))
    return salon if isinstance(salon, discord.TextChannel) else None


async def ouvertes(g) -> bool:
    return bool((await _cfg(g.id)).get("suggestions_actives", 1))


def vue_panneau(ouvert: bool = True) -> LayoutView:
    v = LayoutView(timeout=None)
    proposer = BoutonProposer()
    proposer.item.disabled = not ouvert
    proposer.item.emoji = visuels.icone("idee")
    v.add_item(discord.ui.Container(
        visuels.bandeau("suggestions", "Suggestions"),
        discord.ui.TextDisplay("Une idée pour le serveur ? Propose-la, la communauté vote."
                               if ouvert else "Les suggestions sont fermées pour le moment."),
        discord.ui.ActionRow(proposer,
                             notifs.BoutonNotif("suggestions", emoji=visuels.icone("cloche"))),
        accent_color=Palette.WARNING))
    return v


def _verrou(gid):
    return _verrous.setdefault(gid, asyncio.Lock())


async def reposer_panneau(g, salon=None) -> None:
    async with _verrou(g.id):
        try:
            salon = salon or await salon_de(g)
            if salon is None:
                return
            c = await _cfg(g.id)
            ancien = int(c.get("suggestions_panneau", 0) or 0)
            if ancien:
                try:
                    await salon.get_partial_message(ancien).delete()
                except discord.NotFound:
                    pass
            msg = await salon.send(view=vue_panneau(bool(c.get("suggestions_actives", 1))))
            await _db_set(g.id, "suggestions_panneau", msg.id)
        except discord.HTTPException as ex:
            _log(f"[SUGGESTIONS] panneau : {type(ex).__name__} {ex}")


async def assurer_panneau(g) -> None:
    salon = await salon_de(g)
    if salon is None:
        return
    pid = int((await _cfg(g.id)).get("suggestions_panneau", 0) or 0)
    if pid:
        try:
            await salon.fetch_message(pid)
            return
        except discord.NotFound:
            pass
        except discord.HTTPException as ex:
            _log(f"[SUGGESTIONS] lecture du panneau : {ex}")
            return
    await reposer_panneau(g, salon)


async def creer_salon(g):
    """Les membres n'écrivent pas dans le salon, mais discutent dans le fil de chaque idée."""
    me = g.me
    salon = await g.create_text_channel(
        NOM_SALON, reason="Suggestions : salon dédié",
        topic="Les idées de la communauté — bouton tout en bas.",
        overwrites={
            g.default_role: discord.PermissionOverwrite(
                send_messages=False, add_reactions=False, send_messages_in_threads=True,
                create_public_threads=False, create_private_threads=False),
            me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_messages=True,
                create_public_threads=True, manage_threads=True, read_message_history=True,
                send_messages_in_threads=True),
        })
    await _db_set(g.id, "suggestions_salon", salon.id)
    await _db_set(g.id, "suggestions_panneau", 0)
    await reposer_panneau(g, salon)
    return salon


async def installer(g) -> None:
    try:
        c = await _cfg(g.id)
        if not c.get("suggestions_installees"):
            me = g.me
            if me and me.guild_permissions.manage_channels and not c.get("suggestions_salon"):
                await creer_salon(g)
            await _db_set(g.id, "suggestions_installees", 1)
        await assurer_panneau(g)
    except discord.HTTPException as ex:
        _log(f"[SUGGESTIONS] installation : {type(ex).__name__} {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Données
# ═══════════════════════════════════════════════════════════════════════════════

_COLONNES = ("id", "guild_id", "channel_id", "message_id", "thread_id", "auteur_id", "titre",
             "details", "statut", "note", "decide_par", "cree_le", "decide_le", "log_message_id")


async def charger(sid: int):
    async with _get_db() as db:
        async with db.execute(f"SELECT {', '.join(_COLONNES)} FROM suggestions_v2 WHERE id=?",
                              (sid,)) as cur:
            r = await cur.fetchone()
        if r is None:
            return None, 0, 0
        async with db.execute("SELECT SUM(vote=1), SUM(vote=-1) FROM suggestions_votes "
                              "WHERE suggestion_id=?", (sid,)) as cur:
            pour, contre = await cur.fetchone()
    return dict(zip(_COLONNES, r)), int(pour or 0), int(contre or 0)


# ═══════════════════════════════════════════════════════════════════════════════
#  La fiche publique
# ═══════════════════════════════════════════════════════════════════════════════

def vue_carte(s: dict, pour: int, contre: int, *, ping: str = "") -> LayoutView:
    libelle, pastille, couleur = STATUTS.get(s["statut"], STATUTS["attente"])
    total = pour + contre
    v = LayoutView(timeout=None)
    tete = f"{ping}\n" if ping else ""
    items = [discord.ui.TextDisplay(f"{tete}### {s['titre']}\n-# Idée n°{s['id']} de "
                                    f"<@{s['auteur_id']}> · {pastille} {libelle}")]
    if s["details"]:
        items.append(discord.ui.TextDisplay(s["details"]))
    items += [discord.ui.Separator(),
              discord.ui.TextDisplay(f"`{barre(pour / total if total else 0.5)}`\n"
                                     f"Pour **{pour}** · Contre **{contre}**")]
    if s["note"]:
        items.append(discord.ui.TextDisplay(f"**Réponse du staff** — {s['note']}"))
    boutons = []
    if s["statut"] not in FINAUX:
        p, c = BoutonPour(s["id"]), BoutonContre(s["id"])
        p.item.label, c.item.label = f"Pour · {pour}", f"Contre · {contre}"
        p.item.emoji, c.item.emoji = visuels.icone("pour"), visuels.icone("contre")
        boutons += [p, c]
    g = BoutonGerer(s["id"])
    g.item.emoji = visuels.icone("reglages")
    boutons.append(g)
    items.append(discord.ui.ActionRow(*boutons))
    v.add_item(discord.ui.Container(*items, accent_color=couleur))
    return v


async def _rafraichir(salon, sid: int, attendre: float = 3):
    await asyncio.sleep(attendre)
    _a_rafraichir.pop(sid, None)
    s, pour, contre = await charger(sid)
    if s is None or not s["message_id"]:
        return
    try:
        await salon.get_partial_message(s["message_id"]).edit(view=vue_carte(s, pour, contre))
    except discord.HTTPException as ex:
        _log(f"[SUGGESTIONS] rafraîchir : {ex}")


def rafraichir_plus_tard(salon, sid: int) -> None:
    if sid not in _a_rafraichir:
        _a_rafraichir[sid] = asyncio.create_task(_rafraichir(salon, sid))


# ═══════════════════════════════════════════════════════════════════════════════
#  Proposer
# ═══════════════════════════════════════════════════════════════════════════════

async def _limite(g, membre) -> str:
    if est_staff(membre):
        return ""
    depuis = (_maintenant() - timedelta(days=1)).strftime(_FORMAT)
    async with _get_db() as db:
        async with db.execute("SELECT cree_le FROM suggestions_v2 WHERE guild_id=? AND auteur_id=? "
                              "AND cree_le>? ORDER BY cree_le", (g.id, membre.id, depuis)) as cur:
            du_jour = [r[0] for r in await cur.fetchall()]
    if len(du_jour) >= PAR_JOUR:
        libre = int(datetime.strptime(du_jour[0], _FORMAT).replace(tzinfo=timezone.utc).timestamp()) + 86400
        return f"{PAR_JOUR} idées par jour au maximum — la prochaine <t:{libre}:R>."
    return ""


async def peut_proposer(i) -> str:
    g, m = i.guild, i.user
    if g is None or getattr(m, "guild_permissions", None) is None:
        return "Les suggestions se font sur le serveur."
    if not await ouvertes(g) or await salon_de(g) is None:
        return "Les suggestions sont fermées pour le moment."
    if m.is_timed_out():
        return "Pas de suggestion pendant une exclusion temporaire."
    raison = await _controle(m, await _cfg(g.id))
    return raison or await _limite(g, m)


class Formulaire(discord.ui.Modal, title="Nouvelle idée"):
    def __init__(self, titre="", details=""):
        super().__init__(timeout=900)
        self.t = discord.ui.TextInput(max_length=MAX_TITRE, default=titre or None,
                                      placeholder="En une phrase")
        self.d = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=MAX_DETAILS,
                                      required=False, default=details or None,
                                      placeholder="Pourquoi, comment…")
        self.add_item(discord.ui.Label(text="Ton idée", component=self.t))
        self.add_item(discord.ui.Label(text="Détails", description="Facultatif", component=self.d))

    async def on_submit(self, i: discord.Interaction):
        await publier(i, self.t.value, self.d.value)


def vue_corriger(auteur_id, erreur, titre, details) -> LayoutView:
    v = LayoutView(timeout=900)
    b = Button(label="Corriger", style=discord.ButtonStyle.primary, emoji=visuels.icone("modifier"))

    async def _cb(i: discord.Interaction):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.send_modal(Formulaire(titre, details))
    b.callback = _cb
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(erreur), discord.ui.ActionRow(b),
                                    accent_color=Palette.WARNING))
    return v


async def publier(i, titre, details):
    g, m = i.guild, i.user
    titre, details = " ".join((titre or "").split()), (details or "").strip()
    erreur = verifier(titre, details) or await _texte_refuse(g, f"{titre}\n{details}")
    if erreur:
        return await i.response.send_message(view=vue_corriger(m.id, erreur, titre, details),
                                             ephemeral=True)
    refus = await peut_proposer(i)
    if refus:
        return await i.response.send_message(refus, ephemeral=True)
    await i.response.defer(ephemeral=True, thinking=True)
    salon = await salon_de(g)
    role = await notifs.role(g, "suggestions")
    async with _get_db() as db:
        cur = await db.execute(
            "INSERT INTO suggestions_v2(guild_id, channel_id, auteur_id, titre, details, cree_le) "
            "VALUES(?,?,?,?,?,?)", (g.id, salon.id, m.id, titre, details,
                                    _maintenant().strftime(_FORMAT)))
        sid = cur.lastrowid
        await db.commit()
    s, _, _ = await charger(sid)
    try:
        msg = await salon.send(view=vue_carte(s, 0, 0, ping=notifs.ping(role)),
                               allowed_mentions=notifs.mentions(role))
    except discord.HTTPException as ex:
        _log(f"[SUGGESTIONS] envoi : {type(ex).__name__} {ex}")
        async with _get_db() as db:
            await db.execute("DELETE FROM suggestions_v2 WHERE id=?", (sid,))
            await db.commit()
        return await i.followup.send("Impossible de publier ton idée pour le moment.", ephemeral=True)
    fil = None
    try:
        fil = await msg.create_thread(name=f"Idée n°{sid} · {titre}"[:100], auto_archive_duration=10080)
    except discord.HTTPException as ex:
        _log(f"[SUGGESTIONS] fil : {ex}")
    async with _get_db() as db:
        await db.execute("UPDATE suggestions_v2 SET message_id=?, thread_id=? WHERE id=?",
                         (msg.id, getattr(fil, "id", None), sid))
        await db.commit()
    await i.followup.send(f"Idée publiée : {msg.jump_url}", ephemeral=True)
    asyncio.create_task(reposer_panneau(g, salon))
    asyncio.create_task(journaliser(g, sid, m))


class BoutonProposer(discord.ui.DynamicItem[Button], template=r"sug:proposer"):
    def __init__(self):
        super().__init__(Button(label="Proposer une idée", style=discord.ButtonStyle.primary,
                                custom_id="sug:proposer"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        refus = await peut_proposer(i)
        if refus:
            return await i.response.send_message(refus, ephemeral=True)
        await i.response.send_modal(Formulaire())


# ═══════════════════════════════════════════════════════════════════════════════
#  Voter
# ═══════════════════════════════════════════════════════════════════════════════

async def voter(i, sid: int, sens: int):
    s, _, _ = await charger(sid)
    if s is None or s["statut"] in FINAUX:
        return await i.response.send_message("Les votes sur cette idée sont clos.", ephemeral=True)
    async with _get_db() as db:
        async with db.execute("SELECT vote FROM suggestions_votes WHERE suggestion_id=? AND user_id=?",
                              (sid, i.user.id)) as cur:
            r = await cur.fetchone()
        if r and r[0] == sens:
            await db.execute("DELETE FROM suggestions_votes WHERE suggestion_id=? AND user_id=?",
                             (sid, i.user.id))
            texte = "Vote retiré."
        else:
            await db.execute("INSERT INTO suggestions_votes(suggestion_id, user_id, vote) "
                             "VALUES(?,?,?) ON CONFLICT(suggestion_id, user_id) DO UPDATE SET "
                             "vote=excluded.vote", (sid, i.user.id, sens))
            texte = "Tu es pour." if sens > 0 else "Tu es contre."
        await db.commit()
    await i.response.send_message(texte, ephemeral=True)
    rafraichir_plus_tard(i.channel, sid)


class BoutonPour(discord.ui.DynamicItem[Button], template=r"sug:p:(?P<sid>\d+)"):
    def __init__(self, sid: int):
        self.sid = int(sid)
        super().__init__(Button(label="Pour", style=discord.ButtonStyle.success,
                                custom_id=f"sug:p:{self.sid}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["sid"]))

    async def callback(self, i):
        await voter(i, self.sid, 1)


class BoutonContre(discord.ui.DynamicItem[Button], template=r"sug:c:(?P<sid>\d+)"):
    def __init__(self, sid: int):
        self.sid = int(sid)
        super().__init__(Button(label="Contre", style=discord.ButtonStyle.danger,
                                custom_id=f"sug:c:{self.sid}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["sid"]))

    async def callback(self, i):
        await voter(i, self.sid, -1)


# ═══════════════════════════════════════════════════════════════════════════════
#  Décider (staff)
# ═══════════════════════════════════════════════════════════════════════════════

class FormulaireDecision(discord.ui.Modal, title="Décision du staff"):
    def __init__(self, sid: int, statut: str, note: str = ""):
        super().__init__(timeout=900)
        self.sid, self.statut = sid, statut
        self.n = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=800,
                                      required=False, default=note or None,
                                      placeholder="Visible par tous sous l'idée")
        self.add_item(discord.ui.Label(text=f"Réponse — {STATUTS[statut][0]}",
                                       description="Facultatif", component=self.n))

    async def on_submit(self, i: discord.Interaction):
        await decider(i, self.sid, self.statut, self.n.value.strip())


class MenuDecision(LayoutView):
    def __init__(self, staff_id: int, s: dict):
        super().__init__(timeout=600)
        self.staff_id, self.s = staff_id, s
        sel = discord.ui.Select(placeholder="Nouveau statut", options=[
            discord.SelectOption(label=l, value=k, emoji=p, default=k == s["statut"])
            for k, (l, p, _) in STATUTS.items()])
        sel.callback = self._statut
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(f"### Idée n°{s['id']}\n{s['titre']}"),
            discord.ui.ActionRow(sel), accent_color=Palette.INFO))

    async def interaction_check(self, i):
        return i.user.id == self.staff_id

    async def _statut(self, i):
        await i.response.send_modal(FormulaireDecision(self.s["id"], i.data["values"][0], self.s["note"]))


async def decider(i, sid: int, statut: str, note: str):
    if not est_staff(i.user):
        return await i.response.send_message("Réservé au staff.", ephemeral=True)
    await i.response.defer(ephemeral=True)
    async with _get_db() as db:
        await db.execute("UPDATE suggestions_v2 SET statut=?, note=?, decide_par=?, decide_le=? "
                         "WHERE id=?", (statut, note, i.user.id, _maintenant().strftime(_FORMAT), sid))
        await db.commit()
    s, pour, contre = await charger(sid)
    g = i.guild
    salon = g.get_channel(s["channel_id"]) if g else None
    if salon is not None:
        await _rafraichir(salon, sid, attendre=0)
        fil = g.get_thread(s["thread_id"]) if s["thread_id"] else None
        if fil is None and s["thread_id"]:
            try:
                fil = await g.fetch_channel(s["thread_id"])
            except discord.HTTPException:
                fil = None
        if fil is not None:
            libelle, pastille, _ = STATUTS[statut]
            texte = f"<@{s['auteur_id']}> Ton idée est maintenant **{libelle}** {pastille}"
            if note:
                texte += f"\n> {note}"
            try:
                await fil.send(texte, allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException as ex:
                _log(f"[SUGGESTIONS] fil : {ex}")
    await journaliser(g, sid)
    await i.followup.send(f"Idée n°{sid} : {STATUTS[statut][0]}.", ephemeral=True)


class BoutonGerer(discord.ui.DynamicItem[Button], template=r"sug:g:(?P<sid>\d+)"):
    def __init__(self, sid: int):
        self.sid = int(sid)
        super().__init__(Button(label="Gérer", style=discord.ButtonStyle.secondary,
                                custom_id=f"sug:g:{self.sid}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["sid"]))

    async def callback(self, i):
        if not est_staff(i.user):
            return await i.response.send_message("Réservé au staff.", ephemeral=True)
        s, _, _ = await charger(self.sid)
        if s is None:
            return await i.response.send_message("Idée introuvable.", ephemeral=True)
        await i.response.send_message(view=MenuDecision(i.user.id, s), ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Logs : une fiche par idée, tenue à jour
# ═══════════════════════════════════════════════════════════════════════════════

def vue_journal(g_id: int, s: dict, pour: int, contre: int, nom_auteur: str = "") -> LayoutView:
    libelle, pastille, couleur = STATUTS.get(s["statut"], STATUTS["attente"])
    lien = (f"https://discord.com/channels/{g_id}/{s['channel_id']}/{s['message_id']}"
            if s["message_id"] else "")
    lignes = [f"### Idée n°{s['id']} · {pastille} {libelle}",
              f"**{s['titre']}**",
              f"Auteur : <@{s['auteur_id']}> · `{s['auteur_id']}`" + (f" · {nom_auteur}" if nom_auteur else ""),
              f"Proposée le {s['cree_le']} UTC · Pour {pour} · Contre {contre}"]
    if s["decide_par"]:
        lignes.append(f"Décision : <@{s['decide_par']}> le {s['decide_le']} UTC")
    if lien:
        lignes.append(f"[Voir l'idée]({lien})")
    items = [discord.ui.TextDisplay("\n".join(lignes))]
    if s["details"]:
        items += [discord.ui.Separator(), discord.ui.TextDisplay(s["details"][:1500])]
    if s["note"]:
        items.append(discord.ui.TextDisplay(f"**Réponse du staff** — {s['note']}"))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(*items, accent_color=couleur))
    return v


async def journaliser(g, sid: int, auteur=None) -> None:
    try:
        if g is None:
            return
        salon = await _salon_logs(g, "suggestions", NOM_LOGS)
        if salon is None:
            return
        s, pour, contre = await charger(sid)
        vue = vue_journal(g.id, s, pour, contre, getattr(auteur, "display_name", ""))
        mentions = discord.AllowedMentions.none()
        if s["log_message_id"]:
            try:
                await salon.get_partial_message(s["log_message_id"]).edit(view=vue,
                                                                          allowed_mentions=mentions)
                return
            except discord.NotFound:
                pass
        msg = await salon.send(view=vue, allowed_mentions=mentions)
        async with _get_db() as db:
            await db.execute("UPDATE suggestions_v2 SET log_message_id=? WHERE id=?", (msg.id, sid))
            await db.commit()
    except discord.HTTPException as ex:
        _log(f"[SUGGESTIONS] logs : {type(ex).__name__} {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Écouteurs
# ═══════════════════════════════════════════════════════════════════════════════

async def sur_message(msg: discord.Message) -> None:
    """Un message posé à la main dans le salon (pas dans un fil) est retiré."""
    g = msg.guild
    if g is None or _cfg is None or msg.author.bot or msg.webhook_id:
        return
    try:
        salon = await salon_de(g)
        if salon is None or msg.channel.id != salon.id or est_staff(msg.author):
            return
        try:
            await msg.delete()
        except discord.HTTPException:
            return
        cle = (g.id, msg.author.id)
        if time.monotonic() - _rappels.get(cle, -1e9) > 600:
            _rappels[cle] = time.monotonic()
            await salon.send(f"{msg.author.mention} Propose ton idée avec le bouton en bas ; "
                             "on en discute dans son fil.", delete_after=10,
                             allowed_mentions=discord.AllowedMentions(users=True))
    except Exception as ex:
        _log(f"[SUGGESTIONS] message : {type(ex).__name__} {ex}")


async def sur_salon_supprime(channel) -> None:
    g = getattr(channel, "guild", None)
    if g is None or _cfg is None:
        return
    c = await _cfg(g.id)
    if int(c.get("suggestions_salon", 0) or 0) == channel.id:
        await _db_set(g.id, "suggestions_salon", 0)
        await _db_set(g.id, "suggestions_panneau", 0)


# ═══════════════════════════════════════════════════════════════════════════════
#  /configure → Suggestions
# ═══════════════════════════════════════════════════════════════════════════════

class SuggestionsPanelV2(LayoutView):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g, self._note = u, g, ""

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def render_to(self, i, *, edit: bool = True):
        try:
            salon = await salon_de(self.g)
            actives = await ouvertes(self.g)
            etat = ("🟢 Ouvertes" if actives else "⚪ Fermées") + " · " + (
                salon.mention if salon else "aucun salon")
            items = [visuels.bandeau("suggestions", "Suggestions"), discord.ui.TextDisplay(etat)]
            if self._note:
                items.append(discord.ui.TextDisplay(self._note))
            sel = ChannelSelect(channel_types=[discord.ChannelType.text],
                                placeholder="Salon des suggestions", min_values=1, max_values=1)
            sel.callback = self._cb_salon
            b_on = Button(label="Fermer" if actives else "Ouvrir",
                          style=discord.ButtonStyle.secondary if actives else discord.ButtonStyle.success,
                          emoji=visuels.icone("pause" if actives else "activer"))
            b_on.callback = self._cb_basculer
            boutons = [b_on]
            if salon is None:
                b = Button(label="Créer le salon", style=discord.ButtonStyle.primary,
                           emoji=visuels.icone("ajouter"))
                b.callback = self._cb_creer
            else:
                b = Button(label="Reposer le bouton", style=discord.ButtonStyle.secondary,
                           emoji=visuels.icone("actualiser"))
                b.callback = self._cb_reposer
            r = Button(label="Retour", style=discord.ButtonStyle.secondary, emoji=visuels.icone("retour"))
            r.callback = self._cb_retour
            boutons += [b, r]
            items += [discord.ui.ActionRow(sel), discord.ui.ActionRow(*boutons)]
            self.clear_items()
            self.add_item(discord.ui.Container(*items, accent_color=Palette.WARNING))
            if not edit:
                return await i.response.send_message(view=self, ephemeral=True)
            if i.response.is_done():
                await i.edit_original_response(content=None, view=self, embed=None, attachments=[])
            else:
                await i.response.edit_message(content=None, view=self, embed=None, attachments=[])
        except Exception as ex:
            _log(f"[SUGGESTIONS] panneau de configuration : {type(ex).__name__} {ex}")

    async def _cb_salon(self, i):
        await i.response.defer()
        nouveau_id = int(i.data["values"][0])
        ancien = await salon_de(self.g)
        if ancien is not None and ancien.id != nouveau_id:
            pid = int((await _cfg(self.g.id)).get("suggestions_panneau", 0) or 0)
            if pid:
                try:
                    await ancien.get_partial_message(pid).delete()
                except discord.HTTPException:
                    pass
        await _db_set(self.g.id, "suggestions_salon", nouveau_id)
        await _db_set(self.g.id, "suggestions_panneau", 0)
        await reposer_panneau(self.g)
        self._note = ""
        await self.render_to(i)

    async def _cb_basculer(self, i):
        await i.response.defer()
        await _db_set(self.g.id, "suggestions_actives", 0 if await ouvertes(self.g) else 1)
        await reposer_panneau(self.g)
        await self.render_to(i)

    async def _cb_creer(self, i):
        await i.response.defer()
        try:
            salon = await creer_salon(self.g)
            self._note = f"{salon.mention} créé — déplace-le où tu veux."
        except discord.HTTPException as ex:
            _log(f"[SUGGESTIONS] création du salon : {ex}")
            self._note = "Il me manque le droit de gérer les salons."
        await self.render_to(i)

    async def _cb_reposer(self, i):
        await i.response.defer()
        await reposer_panneau(self.g)
        self._note = "Bouton reposé en bas du salon."
        await self.render_to(i)

    async def _cb_retour(self, i):
        if _retour is not None:
            await _retour(self.u, self.g, i)
        else:
            await i.response.defer()
