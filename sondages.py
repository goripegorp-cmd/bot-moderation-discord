"""sondages.py — sondages créés par les membres en un bouton (19/10/2026).

Un salon « 📊sondages » créé une fois par le bot, puis à son propriétaire (suivi par son
identifiant). Personne n'y écrit : le panneau tout en bas ouvre un menu (durée, votes
visibles ou anonymes) puis un formulaire (question, 2 à 4 choix, chacun son champ).
Votes visibles : un sondage natif Discord. Votes anonymes : un sondage maison, chaque vote
réduit à une empreinte HMAC — personne ne peut savoir qui a voté quoi.
Chaque sondage a sa fiche dans « 📊logs-sondages », complétée par le résultat final.
Rôle « 🔔 Sondages » pris d'un clic ; personne n'est prévenu au départ.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks
from discord.ui import Button, ChannelSelect

import notifs
import registre
import visuels
from ui_v2 import LayoutView, Palette

NOM_SALON = "📊sondages"
ANCIENS_NOMS = ("📊・sondages",)
NOM_LOGS = "📊logs-sondages"
DUREES = (("1 heure", 1), ("4 heures", 4), ("12 heures", 12),
          ("1 jour", 24), ("3 jours", 72), ("7 jours", 168))
DUREE_DEFAUT = 24
MAX_QUESTION = 300          # limites de Discord
MAX_REPONSE = 55
MIN_CHOIX, MAX_CHOIX = 2, 4
EN_COURS_PAR_MEMBRE = 1
PAR_JOUR = 3
_FORMAT = "%Y-%m-%d %H:%M:%S"   # comme CURRENT_TIMESTAMP : comparable par SQLite

_get_db = _cfg = _db_set = None
_texte_refuse = _controle = _salon_logs = _retour = None
_cle = b""
_log = print
_bot = None
_verrous: dict = {}
_rappels: dict = {}
_a_rafraichir: dict = {}


def setup(*, get_db, cfg, db_set, texte_refuse, controle, salon_logs, cle_secrete, log=None):
    """`texte_refuse(g, texte) -> str` · `controle(membre, cfg) -> str` ·
    `salon_logs(g, cle, nom) -> salon|None` · `cle_secrete` : la clé des votes anonymes."""
    global _get_db, _cfg, _db_set, _texte_refuse, _controle, _salon_logs, _cle, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    _texte_refuse, _controle, _salon_logs = texte_refuse, controle, salon_logs
    _cle = str(cle_secrete or "").encode()
    _log = log or print


def set_retour(fn):
    global _retour
    _retour = fn


async def init_db():
    async with _get_db() as db:
        async with db.execute("PRAGMA table_info(sondages)") as cur:
            colonnes = {r[1] for r in await cur.fetchall()}
        if colonnes and "id" not in colonnes:
            await db.execute("ALTER TABLE sondages RENAME TO sondages_avant")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS sondages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INTEGER UNIQUE,"
            " guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, auteur_id INTEGER NOT NULL,"
            " question TEXT NOT NULL, choix TEXT NOT NULL DEFAULT '[]', anonyme INTEGER NOT NULL DEFAULT 0,"
            " heures INTEGER NOT NULL DEFAULT 24, cree_le TEXT NOT NULL, fin_le TEXT NOT NULL,"
            " termine INTEGER NOT NULL DEFAULT 0, log_message_id INTEGER)")
        if colonnes and "id" not in colonnes:
            await db.execute(
                "INSERT INTO sondages(message_id, guild_id, channel_id, auteur_id, question, "
                "cree_le, fin_le, termine) SELECT message_id, guild_id, channel_id, auteur_id, "
                "question, cree_le, fin_le, termine FROM sondages_avant")
            await db.execute("DROP TABLE sondages_avant")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sondages_auteur "
                         "ON sondages(guild_id, auteur_id, cree_le)")
        await db.execute("CREATE TABLE IF NOT EXISTS sondages_votes ("
                         " sondage_id INTEGER NOT NULL, votant TEXT NOT NULL, choix INTEGER NOT NULL,"
                         " PRIMARY KEY(sondage_id, votant))")
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Règles pures
# ═══════════════════════════════════════════════════════════════════════════════

def nettoyer_choix(valeurs) -> list:
    """Les choix remplis, sans doublon, dans l'ordre des champs."""
    vus, out = set(), []
    for v in valeurs:
        r = " ".join(str(v or "").split())
        if r and r.casefold() not in vus:
            vus.add(r.casefold())
            out.append(r)
    return out


def verifier(question: str, choix: list) -> str:
    q = (question or "").strip()
    if not q:
        return "Écris une question."
    if len(q) > MAX_QUESTION:
        return f"La question dépasse {MAX_QUESTION} caractères."
    if len(choix) < MIN_CHOIX:
        return "Il faut au moins deux choix différents."
    if len(choix) > MAX_CHOIX:
        return f"{MAX_CHOIX} choix au maximum."
    trop = next((c for c in choix if len(c) > MAX_REPONSE), None)
    if trop:
        return f"« {trop[:40]}… » dépasse {MAX_REPONSE} caractères."
    return ""


def barre(part: float, largeur: int = 12) -> str:
    plein = round(max(0.0, min(1.0, part)) * largeur)
    return "▰" * plein + "▱" * (largeur - plein)


def libelle_duree(heures: int) -> str:
    return next((l for l, h in DUREES if h == heures), f"{heures} h")


def empreinte(sondage_id: int, user_id: int) -> str:
    return hmac.new(_cle, f"{sondage_id}:{user_id}".encode(), hashlib.sha256).hexdigest()[:32]


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _ts(texte: str) -> int:
    return int(datetime.strptime(texte, _FORMAT).replace(tzinfo=timezone.utc).timestamp())


def est_staff(membre) -> bool:
    p = getattr(membre, "guild_permissions", None)
    return bool(p and (p.administrator or p.manage_messages))


def gagnants(choix: list, comptes: list) -> str:
    total = sum(comptes)
    if not total:
        return "Aucun vote."
    meilleur = max(comptes)
    tete = [choix[k] for k, n in enumerate(comptes) if n == meilleur]
    if len(tete) > 1:
        return "Égalité : " + " · ".join(tete)
    return f"Gagnant : **{tete[0]}**"


def lignes_resultats(choix: list, comptes: list) -> str:
    total = sum(comptes) or 1
    return "\n".join(f"**{c}**\n`{barre(n / total)}` {round(100 * n / total)} % · {n}"
                     for c, n in zip(choix, comptes))


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
    creer = BoutonCreer()
    creer.item.disabled = not ouvert
    creer.item.emoji = visuels.icone("ajouter")
    v.add_item(discord.ui.Container(
        visuels.bandeau("sondages", "Sondages"),
        discord.ui.TextDisplay("Pose ta question, la communauté vote." if ouvert
                               else "Les sondages sont fermés pour le moment."),
        discord.ui.ActionRow(creer, notifs.BoutonNotif("sondages", emoji=visuels.icone("cloche"))),
        accent_color=Palette.PRIMARY))
    return v


def _verrou(gid):
    return _verrous.setdefault(gid, asyncio.Lock())


async def reposer_panneau(g, salon=None) -> None:
    """Le panneau reste le dernier message du salon : l'ancien part, un neuf arrive."""
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
    """Lecture seule pour les membres : ils votent, le bot publie."""
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
    """Le salon est créé UNE fois ; ensuite il appartient au propriétaire."""
    try:
        c = await _cfg(g.id)
        if not c.get("sondages_installes"):
            me = g.me
            if me and me.guild_permissions.manage_channels and not c.get("sondages_salon"):
                await creer_salon(g)
            await _db_set(g.id, "sondages_installes", 1)
        salon = await salon_de(g)
        if salon is not None and salon.name in ANCIENS_NOMS:
            await salon.edit(name=NOM_SALON, reason="Sondages : nom du salon")
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
        libre = _ts(du_jour[0]) + 86400
        return f"{PAR_JOUR} sondages par jour au maximum — le prochain <t:{libre}:R>."
    return ""


async def peut_creer(i) -> str:
    g, m = i.guild, i.user
    if g is None or getattr(m, "guild_permissions", None) is None:
        return "Les sondages se créent sur le serveur."
    if not await ouverts(g) or await salon_de(g) is None:
        return "Les sondages sont fermés pour le moment."
    if m.is_timed_out():
        return "Pas de sondage pendant une exclusion temporaire."
    raison = await _controle(m, await _cfg(g.id))
    return raison or await _limite(g, m)


class Formulaire(discord.ui.Modal, title="Nouveau sondage"):
    def __init__(self, heures=DUREE_DEFAUT, anonyme=False, question="", choix=()):
        super().__init__(timeout=900)
        self.heures, self.anonyme = heures, anonyme
        choix = list(choix) + [""] * MAX_CHOIX
        self.q = discord.ui.TextInput(max_length=MAX_QUESTION, default=question or None,
                                      placeholder="Ta question")
        self.champs = [discord.ui.TextInput(max_length=MAX_REPONSE, required=k < MIN_CHOIX,
                                            default=choix[k] or None,
                                            placeholder="Facultatif" if k >= MIN_CHOIX else None)
                       for k in range(MAX_CHOIX)]
        self.add_item(discord.ui.Label(text="Question", component=self.q))
        for k, champ in enumerate(self.champs):
            self.add_item(discord.ui.Label(text=f"Choix {k + 1}", component=champ))

    async def on_submit(self, i: discord.Interaction):
        await publier(i, self.q.value, [c.value for c in self.champs], self.heures, self.anonyme)


class MenuCreation(LayoutView):
    """Le menu avant le formulaire : durée et type de vote."""

    def __init__(self, auteur_id: int):
        super().__init__(timeout=600)
        self.auteur_id, self.heures, self.anonyme = auteur_id, DUREE_DEFAUT, False
        duree = discord.ui.Select(placeholder="Durée", options=[
            discord.SelectOption(label=l, value=str(h), default=h == DUREE_DEFAUT) for l, h in DUREES])
        votes = discord.ui.Select(placeholder="Votes", options=[
            discord.SelectOption(label="Votes visibles", value="0", default=True,
                                 description="Un sondage Discord classique"),
            discord.SelectOption(label="Votes anonymes", value="1",
                                 description="Personne ne voit qui a voté quoi")])
        ecrire = Button(label="Écrire le sondage", style=discord.ButtonStyle.primary,
                        emoji=visuels.icone("modifier"))
        duree.callback, votes.callback, ecrire.callback = self._duree, self._votes, self._ecrire
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay("### Nouveau sondage\n-# Durée et votes, puis la question "
                                   "et ses choix."),
            discord.ui.ActionRow(duree), discord.ui.ActionRow(votes), discord.ui.ActionRow(ecrire),
            accent_color=Palette.PRIMARY))

    async def interaction_check(self, i):
        return i.user.id == self.auteur_id

    async def _duree(self, i):
        self.heures = int(i.data["values"][0])
        await i.response.defer()

    async def _votes(self, i):
        self.anonyme = i.data["values"][0] == "1"
        await i.response.defer()

    async def _ecrire(self, i):
        await i.response.send_modal(Formulaire(self.heures, self.anonyme))


def vue_corriger(auteur_id, erreur, heures, anonyme, question, choix) -> LayoutView:
    v = LayoutView(timeout=900)
    b = Button(label="Corriger", style=discord.ButtonStyle.primary, emoji=visuels.icone("modifier"))

    async def _cb(i: discord.Interaction):
        if i.user.id != auteur_id:
            return await i.response.defer()
        await i.response.send_modal(Formulaire(heures, anonyme, question, choix))
    b.callback = _cb
    v.add_item(discord.ui.Container(discord.ui.TextDisplay(erreur), discord.ui.ActionRow(b),
                                    accent_color=Palette.WARNING))
    return v


async def publier(i, question, valeurs, heures, anonyme):
    g, m = i.guild, i.user
    choix = nettoyer_choix(valeurs)
    erreur = verifier(question, choix) or await _texte_refuse(g, "\n".join([question] + choix))
    if erreur:
        return await i.response.send_message(
            view=vue_corriger(m.id, erreur, heures, anonyme, question, list(valeurs)), ephemeral=True)
    refus = await peut_creer(i)
    if refus:
        return await i.response.send_message(refus, ephemeral=True)
    await i.response.defer(ephemeral=True, thinking=True)
    salon = await salon_de(g)
    role = await notifs.role(g, "sondages")
    maintenant = _maintenant()
    fin = maintenant + timedelta(hours=heures)
    async with _get_db() as db:
        cur = await db.execute(
            "INSERT INTO sondages(guild_id, channel_id, auteur_id, question, choix, anonyme, "
            "heures, cree_le, fin_le) VALUES(?,?,?,?,?,?,?,?,?)",
            (g.id, salon.id, m.id, question.strip(), json.dumps(choix, ensure_ascii=False),
             int(anonyme), heures, maintenant.strftime(_FORMAT), fin.strftime(_FORMAT)))
        sid = cur.lastrowid
        await db.commit()
    s = {"id": sid, "auteur_id": m.id, "question": question.strip(), "choix": choix,
         "anonyme": anonyme, "heures": heures, "fin": int(fin.timestamp()), "termine": False,
         "channel_id": salon.id}
    try:
        if anonyme:
            msg = await salon.send(view=vue_anonyme(s, [0] * len(choix), ping=notifs.ping(role)),
                                   allowed_mentions=notifs.mentions(role))
        else:
            sondage = discord.Poll(question=s["question"], duration=timedelta(hours=heures))
            for c in choix:
                sondage.add_answer(text=c)
            vue = discord.ui.View(timeout=None)
            vue.add_item(BoutonTerminer(m.id))
            msg = await salon.send(f"{notifs.ping(role)} Sondage de {m.mention}".strip(),
                                   poll=sondage, view=vue, allowed_mentions=notifs.mentions(role))
    except discord.HTTPException as ex:
        _log(f"[SONDAGES] envoi : {type(ex).__name__} {ex}")
        async with _get_db() as db:
            await db.execute("DELETE FROM sondages WHERE id=?", (sid,))
            await db.commit()
        texte = (f"Je n'ai pas le droit de publier dans {salon.mention}."
                 if isinstance(ex, discord.Forbidden) else "Discord a refusé ce sondage. Réessaie.")
        return await i.followup.send(texte, ephemeral=True)
    async with _get_db() as db:
        await db.execute("UPDATE sondages SET message_id=? WHERE id=?", (msg.id, sid))
        await db.commit()
    s["message_id"], s["lien"] = msg.id, msg.jump_url
    await i.followup.send(f"Sondage publié : {msg.jump_url}", ephemeral=True)
    asyncio.create_task(reposer_panneau(g, salon))
    asyncio.create_task(journaliser(g, s, m))


# ═══════════════════════════════════════════════════════════════════════════════
#  Sondage anonyme
# ═══════════════════════════════════════════════════════════════════════════════

def vue_anonyme(s: dict, comptes: list, *, ping: str = "") -> LayoutView:
    v = LayoutView(timeout=None)
    total = sum(comptes)
    votes = f"{total} vote{'s' if total > 1 else ''}"
    pied = (f"-# Vote anonyme · terminé · {votes}" if s["termine"]
            else f"-# Vote anonyme · fin <t:{s['fin']}:R> · {votes}")
    tete = f"{ping}\n" if ping else ""
    items = [discord.ui.TextDisplay(f"{tete}### {s['question']}\n-# Sondage de <@{s['auteur_id']}>"),
             discord.ui.Separator(),
             discord.ui.TextDisplay(lignes_resultats(s["choix"], comptes))]
    if s["termine"]:
        items += [discord.ui.TextDisplay(gagnants(s["choix"], comptes)), discord.ui.TextDisplay(pied)]
    else:
        boutons = []
        for k, c in enumerate(s["choix"]):
            b = BoutonVote(s["id"], k)
            b.item.label = c[:80]
            boutons.append(b)
        fin = BoutonFinAnonyme(s["id"])
        fin.item.emoji = visuels.icone("terminer")
        items += [discord.ui.TextDisplay(pied), discord.ui.ActionRow(*boutons), discord.ui.ActionRow(fin)]
    v.add_item(discord.ui.Container(*items, accent_color=Palette.PRIMARY))
    return v


async def charger(sid: int):
    async with _get_db() as db:
        async with db.execute(
                "SELECT id, guild_id, channel_id, message_id, auteur_id, question, choix, anonyme, "
                "heures, cree_le, fin_le, termine, log_message_id FROM sondages WHERE id=?",
                (sid,)) as cur:
            r = await cur.fetchone()
        if r is None:
            return None, []
        choix = json.loads(r[6] or "[]")
        comptes = [0] * len(choix)
        async with db.execute("SELECT choix, COUNT(*) FROM sondages_votes WHERE sondage_id=? "
                              "GROUP BY choix", (sid,)) as cur:
            for k, n in await cur.fetchall():
                if 0 <= k < len(comptes):
                    comptes[k] = n
    s = {"id": r[0], "guild_id": r[1], "channel_id": r[2], "message_id": r[3], "auteur_id": r[4],
         "question": r[5], "choix": choix, "anonyme": bool(r[7]), "heures": r[8],
         "cree": _ts(r[9]), "fin": _ts(r[10]), "termine": bool(r[11]), "log_message_id": r[12]}
    return s, comptes


async def _rafraichir(salon, sid: int):
    """Un vote → le message suit, au plus une modification toutes les 3 s par sondage."""
    await asyncio.sleep(3)
    _a_rafraichir.pop(sid, None)
    s, comptes = await charger(sid)
    if s is None or not s["message_id"] or s["termine"]:
        return
    try:
        await salon.get_partial_message(s["message_id"]).edit(view=vue_anonyme(s, comptes))
    except discord.HTTPException as ex:
        _log(f"[SONDAGES] rafraîchir : {ex}")


class BoutonVote(discord.ui.DynamicItem[Button], template=r"sdgv:(?P<sid>\d+):(?P<k>\d)"):
    def __init__(self, sid: int, k: int):
        self.sid, self.k = int(sid), int(k)
        super().__init__(Button(label=f"Choix {self.k + 1}", style=discord.ButtonStyle.secondary,
                                custom_id=f"sdgv:{self.sid}:{self.k}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["sid"]), int(match["k"]))

    async def callback(self, i: discord.Interaction):
        s, _ = await charger(self.sid)
        if s is None or s["termine"] or time.time() >= s["fin"] or self.k >= len(s["choix"]):
            return await i.response.send_message("Ce sondage est terminé.", ephemeral=True)
        async with _get_db() as db:
            await db.execute("INSERT INTO sondages_votes(sondage_id, votant, choix) VALUES(?,?,?) "
                             "ON CONFLICT(sondage_id, votant) DO UPDATE SET choix=excluded.choix",
                             (self.sid, empreinte(self.sid, i.user.id), self.k))
            await db.commit()
        await i.response.send_message(f"Vote enregistré : **{s['choix'][self.k]}**. "
                                      "Personne ne peut savoir lequel.", ephemeral=True)
        if self.sid not in _a_rafraichir:
            _a_rafraichir[self.sid] = asyncio.create_task(_rafraichir(i.channel, self.sid))


class BoutonFinAnonyme(discord.ui.DynamicItem[Button], template=r"sdgf:(?P<sid>\d+)"):
    def __init__(self, sid: int):
        self.sid = int(sid)
        super().__init__(Button(label="Terminer", style=discord.ButtonStyle.secondary,
                                custom_id=f"sdgf:{self.sid}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["sid"]))

    async def callback(self, i: discord.Interaction):
        s, _ = await charger(self.sid)
        if s is None:
            return await i.response.send_message("Sondage introuvable.", ephemeral=True)
        if i.user.id != s["auteur_id"] and not est_staff(i.user):
            return await i.response.send_message("Seul l'auteur ou le staff peut le terminer.",
                                                 ephemeral=True)
        await i.response.defer(ephemeral=True)
        await finaliser(i.client, self.sid)
        await i.followup.send("Sondage terminé.", ephemeral=True)


async def finaliser(bot, sid: int) -> None:
    """Fin d'un sondage anonyme : le résultat est figé dans le message et dans les logs."""
    async with _get_db() as db:
        cur = await db.execute("UPDATE sondages SET termine=1 WHERE id=? AND termine=0", (sid,))
        await db.commit()
        if not cur.rowcount:
            return
    s, comptes = await charger(sid)
    g = bot.get_guild(s["guild_id"])
    salon = g.get_channel(s["channel_id"]) if g else None
    if salon is not None and s["message_id"]:
        try:
            await salon.get_partial_message(s["message_id"]).edit(view=vue_anonyme(s, comptes))
        except discord.HTTPException as ex:
            _log(f"[SONDAGES] fin anonyme : {ex}")
    if g is not None:
        await journaliser(g, s, None, comptes)


@tasks.loop(minutes=1)
async def cloture_task():
    """Les sondages anonymes arrivés à échéance (les natifs, Discord les clôt)."""
    if _get_db is None or _bot is None:
        return
    async with _get_db() as db:
        async with db.execute("SELECT id FROM sondages WHERE anonyme=1 AND termine=0 AND fin_le<=?",
                              (_maintenant().strftime(_FORMAT),)) as cur:
            dus = [r[0] for r in await cur.fetchall()]
    for sid in dus:
        await finaliser(_bot, sid)


def demarrer(bot) -> None:
    global _bot
    _bot = bot
    if not cloture_task.is_running():
        cloture_task.start()


# ═══════════════════════════════════════════════════════════════════════════════
#  Sondage natif : terminer, fin naturelle
# ═══════════════════════════════════════════════════════════════════════════════

class BoutonTerminer(discord.ui.DynamicItem[Button], template=r"sdg:fin:(?P<auteur>\d+)"):
    def __init__(self, auteur: int):
        self.auteur = int(auteur)
        super().__init__(Button(label="Terminer", style=discord.ButtonStyle.secondary,
                                emoji=visuels.icone("terminer"), custom_id=f"sdg:fin:{self.auteur}"))

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
                return await i.followup.send("Impossible de terminer ce sondage.", ephemeral=True)
        try:
            await msg.edit(view=None)
        except discord.HTTPException:
            pass
        await marquer_termine(msg.id)
        await i.followup.send("Sondage terminé.", ephemeral=True)


async def marquer_termine(message_id) -> None:
    try:
        async with _get_db() as db:
            await db.execute("UPDATE sondages SET termine=1 WHERE message_id=?", (int(message_id),))
            await db.commit()
    except Exception as ex:
        _log(f"[SONDAGES] marquer terminé : {ex}")


async def _par_message(message_id):
    async with _get_db() as db:
        async with db.execute("SELECT id FROM sondages WHERE message_id=?", (int(message_id),)) as cur:
            r = await cur.fetchone()
    return (await charger(r[0])) if r else (None, [])


# ═══════════════════════════════════════════════════════════════════════════════
#  Logs : une fiche par sondage, complétée par le résultat
# ═══════════════════════════════════════════════════════════════════════════════

def vue_journal(s: dict, auteur_txt: str, comptes=None) -> LayoutView:
    v = LayoutView(timeout=None)
    etat = "terminé" if comptes is not None else "en cours"
    lignes = [f"### Sondage {etat}",
              f"**{s['question']}**",
              f"Auteur : {auteur_txt}",
              f"Votes {'anonymes' if s['anonyme'] else 'visibles'} · {libelle_duree(s['heures'])}"
              f" · fin <t:{s['fin']}:f>"]
    if s.get("lien"):
        lignes.append(f"[Voir le sondage]({s['lien']})")
    items = [discord.ui.TextDisplay("\n".join(lignes)), discord.ui.Separator()]
    if comptes is None:
        items.append(discord.ui.TextDisplay("\n".join(f"· {c}" for c in s["choix"])))
    else:
        total = sum(comptes)
        items += [discord.ui.TextDisplay(lignes_resultats(s["choix"], comptes)),
                  discord.ui.TextDisplay(f"{gagnants(s['choix'], comptes)} · {total} vote"
                                         f"{'s' if total > 1 else ''}")]
    v.add_item(discord.ui.Container(*items, accent_color=Palette.PRIMARY if comptes is None
                                    else Palette.SUCCESS))
    return v


async def journaliser(g, s: dict, auteur=None, comptes=None) -> None:
    """Crée la fiche du sondage dans les logs, ou la complète avec le résultat. Toujours au
    journal du site, même sans salon de logs."""
    fin = comptes is not None
    texte = (f"Sondage terminé : {s['question']} · {sum(comptes)} vote(s) · "
             + registre.propre(gagnants(s["choix"], comptes))) if fin else \
        (f"Sondage publié par {getattr(auteur, 'display_name', None) or 'un membre'} : {s['question']}")
    await registre.noter(g.id, "Sondages", "sondage.fin" if fin else "sondage.publie", texte,
                         membre_id=int(s.get("auteur_id") or 0), salon_id=int(s.get("channel_id") or 0))
    try:
        salon = await _salon_logs(g, "sondages", NOM_LOGS)
        if salon is None:
            return
        uid = s["auteur_id"]
        auteur_txt = f"<@{uid}> · `{uid}`" + (f" · {auteur.display_name}" if auteur else "")
        if "lien" not in s and s.get("message_id") and s.get("channel_id"):
            s["lien"] = f"https://discord.com/channels/{g.id}/{s['channel_id']}/{s['message_id']}"
        vue = vue_journal(s, auteur_txt, comptes)
        mentions = discord.AllowedMentions.none()
        lid = s.get("log_message_id")
        if lid:
            try:
                await salon.get_partial_message(lid).edit(view=vue, allowed_mentions=mentions)
                return
            except discord.NotFound:
                pass
        msg = await salon.send(view=vue, allowed_mentions=mentions)
        async with _get_db() as db:
            await db.execute("UPDATE sondages SET log_message_id=? WHERE id=?", (msg.id, s["id"]))
            await db.commit()
    except discord.HTTPException as ex:
        _log(f"[SONDAGES] logs : {type(ex).__name__} {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Écouteurs (branchés par bot.py)
# ═══════════════════════════════════════════════════════════════════════════════

async def sur_message(msg: discord.Message) -> None:
    """Fin d'un sondage natif : bouton retiré, résultat aux logs, panneau redescendu.
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
                    sondage_msg = await salon.fetch_message(ref)
                    await sondage_msg.edit(view=None)
                    s, _ = await _par_message(ref)
                    if s is not None and sondage_msg.poll is not None:
                        comptes = [a.vote_count for a in sondage_msg.poll.answers]
                        await journaliser(g, s, None, comptes)
                except discord.HTTPException as ex:
                    _log(f"[SONDAGES] fin naturelle : {ex}")
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
            await salon.send(f"{msg.author.mention} Ici, on crée un sondage avec le bouton en bas.",
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


class BoutonCreer(discord.ui.DynamicItem[Button], template=r"sdg:creer"):
    def __init__(self):
        super().__init__(Button(label="Créer un sondage", style=discord.ButtonStyle.primary,
                                custom_id="sdg:creer"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        refus = await peut_creer(i)
        if refus:
            return await i.response.send_message(refus, ephemeral=True)
        await i.response.send_message(view=MenuCreation(i.user.id), ephemeral=True)


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
            etat = ("🟢 Ouverts" if actifs else "⚪ Fermés") + " · " + (
                salon.mention if salon else "aucun salon")
            items = [visuels.bandeau("sondages", "Sondages"), discord.ui.TextDisplay(etat)]
            if self._note:
                items.append(discord.ui.TextDisplay(self._note))
            sel = ChannelSelect(channel_types=[discord.ChannelType.text],
                                placeholder="Salon des sondages", min_values=1, max_values=1)
            sel.callback = self._cb_salon
            b_on = Button(label="Fermer" if actifs else "Ouvrir",
                          style=discord.ButtonStyle.secondary if actifs else discord.ButtonStyle.success,
                          emoji=visuels.icone("pause" if actifs else "activer"))
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
            self.add_item(discord.ui.Container(*items, accent_color=Palette.PRIMARY))
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
        nouveau_id = int(i.data["values"][0])
        ancien = await salon_de(self.g)
        if ancien is not None and ancien.id != nouveau_id:
            pid = int((await _cfg(self.g.id)).get("sondages_panneau", 0) or 0)
            if pid:
                try:
                    await ancien.get_partial_message(pid).delete()
                except discord.HTTPException:
                    pass
        await _db_set(self.g.id, "sondages_salon", nouveau_id)
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
            self._note = f"{salon.mention} créé — déplace-le où tu veux."
        except discord.HTTPException as ex:
            _log(f"[SONDAGES] création du salon : {ex}")
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
