"""sondages.py — les sondages Discord, faits comme Discord les fait (19/10/2026, soir).

« Refais-le avec le système de sondage par défaut de Discord, qui était bien mieux. Pas le nouveau
système… ça envoie trop de messages débiles… Et qui s'affiche au propre, même sur le panel. Comme
ça, on peut décider si on l'enlève du salon ou non. »

Les membres créent leurs sondages eux-mêmes, avec le bouton « Sondage » de Discord, dans
« 📊sondages » (et partout où Discord le leur permet). Le bot n'écrit plus rien dans le salon : ni
panneau, ni annonce, ni bouton. Il veille seulement :
· un sondage qui enfreint les filtres du serveur (lien, mention, mot interdit, insulte, politique)
  ou les limites (un en cours et trois par jour par membre ; staff libre) est retiré, la raison
  dite à l'auteur dans un message qui s'efface ;
· dans « 📊sondages », un message qui n'est pas un sondage est retiré (rappel rare, qui s'efface) ;
· chaque sondage est suivi — question, choix, votes en direct, fin — et s'affiche sur le site, où
  le fondateur et la direction peuvent le retirer du salon.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks
from discord.ui import Button, ChannelSelect

import registre
import visuels
from ui_v2 import LayoutView, Palette, carte_texte

NOM_SALON = "📊sondages"
ANCIENS_NOMS = ("📊・sondages",)
EN_COURS_PAR_MEMBRE = 1
PAR_JOUR = 3
RAPPEL = 3600
ATTENTE_VOTES = 5
_FORMAT = "%Y-%m-%d %H:%M:%S"   # comme CURRENT_TIMESTAMP : comparable par SQLite

_get_db = _cfg = _db_set = None
_texte_refuse = _controle = _retour = None
_log = print
_bot = None
_rappels: dict = {}
_a_rafraichir: dict = {}


def setup(*, get_db, cfg, db_set, texte_refuse, controle, log=None):
    """`texte_refuse(g, texte) -> str` · `controle(membre, cfg) -> str` (âge du compte…)."""
    global _get_db, _cfg, _db_set, _texte_refuse, _controle, _log
    _get_db, _cfg, _db_set = get_db, cfg, db_set
    _texte_refuse, _controle = texte_refuse, controle
    _log = log or print


def set_retour(fn):
    global _retour
    _retour = fn


_COLONNES = {"comptes": "TEXT NOT NULL DEFAULT '[]'", "total": "INTEGER NOT NULL DEFAULT 0",
             "multiple": "INTEGER NOT NULL DEFAULT 0", "retire_le": "INTEGER NOT NULL DEFAULT 0",
             "retire_par": "INTEGER NOT NULL DEFAULT 0", "maj_le": "INTEGER NOT NULL DEFAULT 0"}


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
        async with db.execute("PRAGMA table_info(sondages)") as cur:
            colonnes = {r[1] for r in await cur.fetchall()}
        for nom, type_ in _COLONNES.items():
            if nom not in colonnes:
                ajout = f"ALTER TABLE sondages ADD COLUMN {nom} {type_}"
                await db.execute(ajout)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sondages_auteur ON sondages(guild_id, auteur_id, cree_le)")
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sondages_votes'") as cur:
            anciens_votes = await cur.fetchone() is not None
        if anciens_votes:
            #  Les anciens sondages anonymes : leurs résultats passent dans `comptes`, les empreintes partent.
            async with db.execute("SELECT id, choix FROM sondages WHERE anonyme=1") as cur:
                anonymes = await cur.fetchall()
            for sid, choix in anonymes:
                comptes = [0] * len(json.loads(choix or "[]"))
                async with db.execute("SELECT choix, COUNT(*) FROM sondages_votes WHERE sondage_id=? GROUP BY choix",
                                      (sid,)) as cur:
                    for k, n in await cur.fetchall():
                        if 0 <= k < len(comptes):
                            comptes[k] = n
                await db.execute("UPDATE sondages SET comptes=?, total=? WHERE id=?",
                                 (json.dumps(comptes), sum(comptes), sid))
            await db.execute("DROP TABLE sondages_votes")
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Règles pures
# ═══════════════════════════════════════════════════════════════════════════════

def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _ts(texte: str) -> int:
    return int(datetime.strptime(texte, _FORMAT).replace(tzinfo=timezone.utc).timestamp())


def est_staff(membre) -> bool:
    p = getattr(membre, "guild_permissions", None)
    return bool(p and (p.administrator or p.manage_messages))


def libelle(reponse) -> str:
    """Le texte d'un choix tel que Discord l'affiche (émoji compris)."""
    emoji, texte = getattr(reponse, "emoji", None), (getattr(reponse, "text", None) or "").strip()
    return " ".join(x for x in (str(emoji) if emoji else "", texte) if x) or "—"


def gagnants(choix: list, comptes: list) -> str:
    if not sum(comptes):
        return "Aucun vote."
    meilleur = max(comptes)
    tete = [choix[k] for k, n in enumerate(comptes) if n == meilleur and k < len(choix)]
    return ("Égalité : " + " · ".join(tete)) if len(tete) > 1 else f"Gagnant : {tete[0]}"


def lire_sondage(msg) -> dict:
    """Ce que le site montre d'un sondage Discord : question, choix, votes, fin."""
    p = msg.poll
    reponses = list(p.answers)
    fin = getattr(p, "expires_at", None) or (msg.created_at + (p.duration or timedelta(hours=24)))
    return {"question": str(getattr(p.question, "text", p.question) or "")[:300],
            "choix": [libelle(a) for a in reponses], "comptes": [int(a.vote_count or 0) for a in reponses],
            "multiple": bool(getattr(p, "multiple", False)), "fin": fin,
            "termine": bool(p.is_finalized()) if hasattr(p, "is_finalized") else False}


# ═══════════════════════════════════════════════════════════════════════════════
#  Le salon
# ═══════════════════════════════════════════════════════════════════════════════

async def salon_de(g):
    c = await _cfg(g.id)
    salon = g.get_channel(int(c.get("sondages_salon", 0) or 0))
    return salon if isinstance(salon, discord.TextChannel) else None


async def ouverts(g) -> bool:
    return bool((await _cfg(g.id)).get("sondages_actifs", 1))


def droits_membres(ouvert: bool) -> discord.PermissionOverwrite:
    """Créer un sondage demande « Envoyer des messages » ET « Créer des sondages » : les messages
    qui ne sont pas des sondages sont retirés par le bot. Ni réaction, ni fil, ni fichier."""
    return discord.PermissionOverwrite(send_messages=ouvert, send_polls=ouvert, add_reactions=False,
                                       attach_files=False, embed_links=False, create_public_threads=False,
                                       create_private_threads=False)


async def regler_salon(g, salon, ouvert: bool) -> bool:
    """Seuls les droits des sondages changent ; la vue du salon et le reste restent tels quels."""
    tous = salon.overwrites_for(g.default_role)
    voulu = {k: v for k, v in droits_membres(ouvert) if v is not None}
    if all(getattr(tous, k) == v for k, v in voulu.items()):
        return False
    tous.update(**voulu)
    await salon.set_permissions(g.default_role, overwrite=tous, reason="Sondages Discord : droits du salon")
    return True


async def creer_salon(g):
    me = g.me
    salon = await g.create_text_channel(
        NOM_SALON, reason="Sondages : salon dédié",
        topic="Crée ton sondage avec le bouton ➕ puis « Sondage ». Un en cours, trois par jour.",
        overwrites={g.default_role: droits_membres(await ouverts(g)),
                    me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True,
                                                    read_message_history=True)})
    await _db_set(g.id, "sondages_salon", salon.id)
    return salon


async def installer(g) -> None:
    """Le salon est créé UNE fois ; ensuite il appartient au propriétaire. Une fois aussi : passage
    aux sondages Discord (panneau, boutons et rôle de notification de l'ancien système retirés)."""
    try:
        c = await _cfg(g.id)
        me = g.me
        if not c.get("sondages_installes"):
            if me and me.guild_permissions.manage_channels and not c.get("sondages_salon"):
                await creer_salon(g)
            await _db_set(g.id, "sondages_installes", 1)
        salon = await salon_de(g)
        if salon is not None and salon.name in ANCIENS_NOMS:
            await salon.edit(name=NOM_SALON, reason="Sondages : nom du salon")
        if not c.get("sondages_natifs_v2"):
            await _passer_aux_sondages_discord(g, c, salon)
    except discord.HTTPException as ex:
        _log("[SONDAGES][E1] installation impossible")
        _log(f"[SONDAGES][E1:DETAIL] {g.id} {type(ex).__name__} {ex}")


async def _passer_aux_sondages_discord(g, c, salon) -> None:
    if salon is not None:
        pid = int(c.get("sondages_panneau", 0) or 0)
        if pid:
            try:
                await salon.get_partial_message(pid).delete()
            except discord.NotFound:
                pass
        if g.me and g.me.guild_permissions.manage_roles:
            await regler_salon(g, salon, bool(c.get("sondages_actifs", 1)))
    async with _get_db() as db:
        async with db.execute("SELECT id, channel_id, message_id, anonyme, question, choix, comptes FROM sondages"
                              " WHERE guild_id=? AND termine=0", (g.id,)) as cur:
            anciens = await cur.fetchall()
    for sid, cid, mid, anonyme, question, choix, comptes in anciens:
        ch = g.get_channel(int(cid or 0))
        vue = _vue_figee(question, json.loads(choix or "[]"), json.loads(comptes or "[]")) if anonyme else None
        if ch is not None and mid:
            try:
                await ch.get_partial_message(int(mid)).edit(view=vue)
            except discord.HTTPException as ex:
                _log(f"[SONDAGES] ancien sondage : {ex}")
        if anonyme:
            await _marquer(sid, termine=1)
    role = g.get_role(int(c.get("notif_role_sondages", 0) or 0))
    if role is not None and g.me and g.me.guild_permissions.manage_roles and not role.managed:
        try:
            await role.delete(reason="Sondages : plus de rôle de notification")
        except discord.HTTPException as ex:
            _log(f"[SONDAGES] rôle de notification : {ex}")
    await _db_set(g.id, "notif_role_sondages", 0)
    await _db_set(g.id, "sondages_panneau", 0)
    await _db_set(g.id, "sondages_natifs_v2", int(time.time()))
    _log(f"[SONDAGES] passage aux sondages Discord : {g.id}")


def _vue_figee(question: str, choix: list, comptes: list):
    """Un ancien sondage anonyme (bouton du bot) : ses boutons partent, son résultat reste."""
    total = sum(comptes) or 1
    lignes = "\n".join(f"**{c}** · {round(100 * n / total)} % · {n}" for c, n in zip(choix, comptes))
    v = LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.TextDisplay(f"### {question}\n{lignes or 'Aucun vote.'}\n-# Sondage terminé · "
                               f"{gagnants(choix, comptes)}"), accent_color=Palette.PRIMARY))
    return v


# ═══════════════════════════════════════════════════════════════════════════════
#  Un nouveau sondage : vérifié, puis suivi
# ═══════════════════════════════════════════════════════════════════════════════

async def _limite(g, membre) -> str:
    if est_staff(membre):
        return ""
    maintenant = _maintenant()
    async with _get_db() as db:
        async with db.execute(
                "SELECT COUNT(*) FROM sondages WHERE guild_id=? AND auteur_id=? AND termine=0 AND retire_le=0 "
                "AND fin_le>?", (g.id, membre.id, maintenant.strftime(_FORMAT))) as cur:
            en_cours = (await cur.fetchone())[0]
        async with db.execute(
                "SELECT cree_le FROM sondages WHERE guild_id=? AND auteur_id=? AND cree_le>? ORDER BY cree_le",
                (g.id, membre.id, (maintenant - timedelta(days=1)).strftime(_FORMAT))) as cur:
            du_jour = [r[0] for r in await cur.fetchall()]
    if en_cours >= EN_COURS_PAR_MEMBRE:
        return "tu as déjà un sondage en cours."
    if len(du_jour) >= PAR_JOUR:
        return f"{PAR_JOUR} sondages par jour au maximum (le prochain <t:{_ts(du_jour[0]) + 86400}:R>)."
    return ""


async def raison_du_refus(msg, s: dict) -> str:
    g, m = msg.guild, msg.author
    if getattr(m, "guild_permissions", None) is None:
        return ""
    if est_staff(m):
        return ""
    salon = await salon_de(g)
    if salon is not None and msg.channel.id == salon.id and not await ouverts(g):
        return "les sondages sont fermés pour le moment."
    raison = await _texte_refuse(g, "\n".join([s["question"]] + s["choix"]))
    if raison:
        return raison[0].lower() + raison[1:]
    raison = await _controle(m, await _cfg(g.id))
    return (raison[0].lower() + raison[1:]) if raison else await _limite(g, m)


async def _dire(salon, texte: str, membre, secondes: int = 12) -> None:
    """Un avis au membre, qui s'efface. 24/10/2026 (revue) : une carte V2, plus du texte brut ; seul le
    membre est mentionné."""
    try:
        await salon.send(view=carte_texte(texte, couleur=Palette.WARNING), delete_after=secondes,
                         allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[membre]))
    except discord.HTTPException as ex:
        _log(f"[SONDAGES] message : {ex}")


async def nouveau(msg) -> bool:
    """Un sondage vient d'être posté : retiré s'il enfreint une règle, suivi sinon."""
    g = msg.guild
    s = lire_sondage(msg)
    raison = await raison_du_refus(msg, s)
    if raison:
        try:
            await msg.delete()
        except discord.HTTPException as ex:
            _log(f"[SONDAGES] retrait impossible : {ex}")
            return False
        await _dire(msg.channel, f"{msg.author.mention} Sondage retiré : {raison}", msg.author)
        await registre.noter(g.id, "Sondages", "sondage.refuse", f"Sondage refusé : {s['question'][:120]} — {raison}",
                             membre_id=msg.author.id, salon_id=msg.channel.id)
        return False
    cree = msg.created_at.astimezone(timezone.utc)
    async with _get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO sondages(message_id, guild_id, channel_id, auteur_id, question, choix, comptes,"
            " total, multiple, heures, cree_le, fin_le, maj_le) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (msg.id, g.id, msg.channel.id, msg.author.id, s["question"], json.dumps(s["choix"], ensure_ascii=False),
             json.dumps(s["comptes"]), sum(s["comptes"]), int(s["multiple"]),
             max(1, round((s["fin"] - cree).total_seconds() / 3600)), cree.strftime(_FORMAT),
             s["fin"].astimezone(timezone.utc).strftime(_FORMAT), int(time.time())))
        await db.commit()
    await registre.noter(g.id, "Sondages", "sondage.publie",
                         f"Sondage publié par {getattr(msg.author, 'display_name', 'un membre')} : {s['question']}",
                         membre_id=msg.author.id, salon_id=msg.channel.id)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  Votes, fin, retrait
# ═══════════════════════════════════════════════════════════════════════════════

async def _ligne(message_id=None, sid=None):
    requete = ("SELECT id, guild_id, channel_id, message_id, auteur_id, question, choix, comptes, total, termine,"
               " retire_le FROM sondages WHERE " + ("message_id=?" if message_id else "id=?"))
    async with _get_db() as db:
        async with db.execute(requete, (int(message_id or sid),)) as cur:
            r = await cur.fetchone()
    if r is None:
        return None
    return {"id": r[0], "guild_id": r[1], "channel_id": r[2], "message_id": r[3], "auteur_id": r[4],
            "question": r[5], "choix": json.loads(r[6] or "[]"), "comptes": json.loads(r[7] or "[]"),
            "total": r[8], "termine": bool(r[9]), "retire_le": r[10]}


_CHAMPS = ("termine", "retire_le", "retire_par", "comptes", "total", "choix", "maj_le")


async def _marquer(sid: int, **champs) -> None:
    if not champs:
        return
    requete = "UPDATE sondages SET " + ", ".join(k + "=?" for k in champs if k in _CHAMPS) + " WHERE id=?"
    async with _get_db() as db:
        await db.execute(requete, (*(v for k, v in champs.items() if k in _CHAMPS), sid))
        await db.commit()


ECHECS_MAX = 6
_echecs: dict = {}  # sondage -> lectures ratées d'affilée


async def rafraichir(g, s: dict) -> None:
    """Les votes du sondage, lus chez Discord ; à la fin, le résultat part au journal."""
    salon = g.get_channel(int(s["channel_id"])) or (g.get_thread(int(s["channel_id"])) if hasattr(g, "get_thread") else None)
    if salon is None:  # salon disparu : plus rien à relire
        await _marquer(s["id"], termine=1)
        return
    try:
        msg = await salon.fetch_message(int(s["message_id"]))
    except discord.NotFound:
        if not s["retire_le"]:
            await _marquer(s["id"], termine=1, retire_le=int(time.time()))
        return
    except discord.HTTPException as ex:
        _log(f"[SONDAGES] lecture : {ex}")
        _echecs[s["id"]] = _echecs.get(s["id"], 0) + 1
        if _echecs[s["id"]] >= ECHECS_MAX:  # une heure d'échecs : on arrête de le relire
            _echecs.pop(s["id"], None)
            await _marquer(s["id"], termine=1)
        return
    _echecs.pop(s["id"], None)
    if msg.poll is None:  # plus un sondage
        await _marquer(s["id"], termine=1)
        return
    lu = lire_sondage(msg)
    fini = lu["termine"] or lu["fin"] <= _maintenant()
    await _marquer(s["id"], comptes=json.dumps(lu["comptes"]), total=sum(lu["comptes"]), choix=json.dumps(
        lu["choix"], ensure_ascii=False), termine=int(fini), maj_le=int(time.time()))
    if fini and not s["termine"]:
        await registre.noter(g.id, "Sondages", "sondage.fin",
                             f"Sondage terminé : {s['question']} · {sum(lu['comptes'])} vote(s) · "
                             + gagnants(lu["choix"], lu["comptes"]),
                             membre_id=int(s["auteur_id"]), salon_id=int(s["channel_id"]))


async def _plus_tard(g, message_id) -> None:
    await asyncio.sleep(ATTENTE_VOTES)
    _a_rafraichir.pop(message_id, None)
    s = await _ligne(message_id=message_id)
    if s is not None:
        await rafraichir(g, s)


async def sur_vote(payload) -> None:
    """Un vote ajouté ou retiré : le site suit, au plus une lecture toutes les 5 s par sondage."""
    try:
        if _get_db is None or _bot is None or not getattr(payload, "guild_id", None):
            return
        mid = payload.message_id
        if mid in _a_rafraichir:
            return
        g = _bot.get_guild(payload.guild_id)
        if g is not None:
            _a_rafraichir[mid] = asyncio.get_running_loop().create_task(_plus_tard(g, mid))
    except Exception as ex:  # un vote ne casse jamais rien ; le relevé périodique rattrape
        _log("[SONDAGES][E2] vote non suivi")
        _log(f"[SONDAGES][E2:DETAIL] {type(ex).__name__} {ex}")


async def retirer(g, sid: int, auteur) -> tuple[bool, str]:
    """Le site : retirer un sondage du salon (fondateur et direction).

    24/10/2026 (revue) : un post archivé n'est pas en mémoire — le message restait et le site disait
    « Sondage retiré ». Le salon est demandé à Discord, le post réveillé le temps du retrait puis
    rendormi ; tout échec est dit tel quel, et rien n'est marqué retiré."""
    s = await _ligne(sid=sid)
    if s is None or s["guild_id"] != g.id:
        return False, "Sondage introuvable."
    if s["retire_le"]:
        return False, "Ce sondage est déjà retiré du salon."
    cid = int(s["channel_id"])
    salon = g.get_channel(cid) or g.get_thread(cid)
    if salon is None:
        try:
            salon = await g.fetch_channel(cid)
        except discord.NotFound:
            salon = None  # le salon n'existe plus : le sondage non plus
        except discord.HTTPException as ex:
            _log("[SONDAGES][E5] salon du sondage illisible")
            _log(f"[SONDAGES][E5:DETAIL] salon={cid} {type(ex).__name__} {ex}")
            return False, "Je n'arrive pas à atteindre ce salon : rien n'a été retiré."
    if salon is not None:
        endormi = isinstance(salon, discord.Thread) and salon.archived
        if endormi:
            try:
                await salon.edit(archived=False)
            except discord.HTTPException as ex:
                _log("[SONDAGES][E6] post archivé non rouvert")
                _log(f"[SONDAGES][E6:DETAIL] salon={cid} {type(ex).__name__} {ex}")
                return False, "Ce sondage est dans un post archivé que je ne peux pas rouvrir : rien n'a été retiré."
        try:
            await salon.get_partial_message(int(s["message_id"])).delete()
        except discord.NotFound:
            pass
        except discord.Forbidden:
            return False, "Il me manque le droit de gérer les messages dans ce salon."
        except discord.HTTPException as ex:
            _log("[SONDAGES][E7] retrait refusé par Discord")
            _log(f"[SONDAGES][E7:DETAIL] salon={cid} {type(ex).__name__} {ex}")
            return False, "Discord a refusé le retrait : rien n'a été retiré, réessaie dans un instant."
        finally:
            if endormi:
                try:
                    await salon.edit(archived=True)
                except discord.HTTPException as ex:
                    _log(f"[SONDAGES:DETAIL] post {cid} non rendormi {type(ex).__name__} {ex}")
    await _marquer(sid, termine=1, retire_le=int(time.time()), retire_par=int(auteur.id))
    await registre.noter(g.id, "Sondages", "sondage.retire",
                         f"Sondage retiré du salon par {auteur.display_name} : {s['question']}",
                         membre_id=int(s["auteur_id"]), auteur_id=auteur.id, salon_id=int(s["channel_id"]))
    return True, "Sondage retiré du salon."


@tasks.loop(minutes=10)
async def cloture_task():
    """Les sondages arrivés à échéance : résultat définitif relu chez Discord."""
    if _get_db is None or _bot is None:
        return
    async with _get_db() as db:
        async with db.execute("SELECT id, guild_id FROM sondages WHERE termine=0 AND fin_le<=? ORDER BY fin_le LIMIT 30",
                              (_maintenant().strftime(_FORMAT),)) as cur:
            dus = await cur.fetchall()
    for sid, gid in dus:
        g = _bot.get_guild(int(gid))
        s = await _ligne(sid=sid)
        if g is None or s is None:
            await _marquer(sid, termine=1)
            continue
        await rafraichir(g, s)
        await asyncio.sleep(1)


def demarrer(bot) -> None:
    global _bot
    _bot = bot
    if not cloture_task.is_running():
        cloture_task.start()


async def lister(guild_id: int, limite: int = 60, auteur_id: int = 0) -> dict:
    """Pour le site : les sondages (d'un membre, si demandé), du plus récent au plus ancien, et quelques
    chiffres."""
    maintenant = _maintenant().strftime(_FORMAT)
    filtre, args = ("AND auteur_id=? ", (int(auteur_id),)) if auteur_id else ("", ())
    requete = ("SELECT id, channel_id, message_id, auteur_id, question, choix, comptes, total, multiple, cree_le,"
               " fin_le, termine, retire_le, retire_par FROM sondages WHERE guild_id=? " + filtre
               + "ORDER BY cree_le DESC LIMIT ?")
    async with _get_db() as db:
        async with db.execute(requete, (guild_id, *args, limite)) as cur:
            lignes = await cur.fetchall()
        async with db.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM sondages WHERE guild_id=? AND cree_le>?",
                              (guild_id, (_maintenant() - timedelta(days=30)).strftime(_FORMAT))) as cur:
            mois, votes = await cur.fetchone()
    liste = []
    for (sid, cid, mid, auteur, question, choix, comptes, total, multiple, cree, fin, termine, retire,
         retire_par) in lignes:
        statut = "retire" if retire else ("termine" if termine or fin <= maintenant else "en_cours")
        liste.append({"id": sid, "salon_id": str(cid), "lien": f"https://discord.com/channels/{guild_id}/{cid}/{mid}",
                      "auteur": str(auteur), "question": question, "choix": json.loads(choix or "[]"),
                      "comptes": json.loads(comptes or "[]"), "total": int(total or 0), "multiple": bool(multiple),
                      "cree": _ts(cree), "fin": _ts(fin), "statut": statut,
                      "retire_le": int(retire or 0) or None, "retire_par": str(retire_par) if retire_par else ""})
    return {"liste": liste, "stats": {"en_cours": sum(1 for x in liste if x["statut"] == "en_cours"),
                                      "mois": int(mois or 0), "votes_mois": int(votes or 0)}}


# ═══════════════════════════════════════════════════════════════════════════════
#  Écouteurs (branchés par bot.py)
# ═══════════════════════════════════════════════════════════════════════════════

async def sur_message(msg: discord.Message) -> None:
    g = msg.guild
    if g is None or _cfg is None:
        return
    try:
        if msg.type == discord.MessageType.poll_result:
            ref = msg.reference.message_id if msg.reference else None
            s = await _ligne(message_id=ref) if ref else None
            if s is not None:
                await rafraichir(g, s)
            return
        if msg.author.bot or msg.webhook_id:
            return
        if getattr(msg, "poll", None) is not None:
            await nouveau(msg)
            return
        salon = await salon_de(g)
        if salon is None or msg.channel.id != salon.id or msg.is_system() or est_staff(msg.author):
            return
        try:
            await msg.delete()
        except discord.HTTPException:
            return
        cle = (g.id, msg.author.id)
        if time.monotonic() - _rappels.get(cle, -1e9) > RAPPEL:
            _rappels[cle] = time.monotonic()
            if len(_rappels) > 500:  # 20/10/2026 : une entrée par personne, à vie
                for k in [k for k, v in _rappels.items() if time.monotonic() - v > RAPPEL]:
                    _rappels.pop(k, None)
            await _dire(salon, f"{msg.author.mention} Ici, seulement des sondages : bouton ➕ puis « Sondage ».",
                        msg.author, 10)
    except Exception as ex:  # un message ne casse jamais rien
        _log("[SONDAGES][E3] message non traité")
        _log(f"[SONDAGES][E3:DETAIL] {type(ex).__name__} {ex}")


async def sur_suppression(payload) -> None:
    if _get_db is None or not payload.guild_id:
        return
    s = await _ligne(message_id=payload.message_id)
    if s is not None and not s["retire_le"]:
        await _marquer(s["id"], termine=1, retire_le=int(time.time()))


async def sur_salon_supprime(channel) -> None:
    g = getattr(channel, "guild", None)
    if g is None or _cfg is None:
        return
    c = await _cfg(g.id)
    if int(c.get("sondages_salon", 0) or 0) == channel.id:
        await _db_set(g.id, "sondages_salon", 0)


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
            etat = ("🟢 Ouverts" if actifs else "⚪ Fermés") + " · " + (salon.mention if salon else "aucun salon")
            items = [visuels.bandeau("sondages", "Sondages"), discord.ui.TextDisplay(
                f"{etat}\n-# Les membres créent leurs sondages avec le bouton ➕ de Discord. Suivi et retrait : "
                "sur le site.")]
            if self._note:
                items.append(discord.ui.TextDisplay(self._note))
            sel = ChannelSelect(channel_types=[discord.ChannelType.text], placeholder="Salon des sondages",
                                min_values=1, max_values=1)
            sel.callback = self._cb_salon
            b_on = Button(label="Fermer" if actifs else "Ouvrir",
                          style=discord.ButtonStyle.secondary if actifs else discord.ButtonStyle.success,
                          emoji=visuels.icone("pause" if actifs else "activer"))
            b_on.callback = self._cb_basculer
            boutons = [b_on]
            if salon is None:
                b = Button(label="Créer le salon", style=discord.ButtonStyle.primary, emoji=visuels.icone("ajouter"))
                b.callback = self._cb_creer
                boutons.append(b)
            r = Button(label="Retour", style=discord.ButtonStyle.secondary, emoji=visuels.icone("retour"))
            r.callback = self._cb_retour
            boutons.append(r)
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
            _log("[SONDAGES][E4] panneau de configuration")
            _log(f"[SONDAGES][E4:DETAIL] {type(ex).__name__} {ex}")

    async def _cb_salon(self, i):
        await i.response.defer()
        await _db_set(self.g.id, "sondages_salon", int(i.data["values"][0]))
        salon = await salon_de(self.g)
        self._note = ""
        if salon is not None:
            try:
                await regler_salon(self.g, salon, await ouverts(self.g))
            except discord.HTTPException as ex:
                _log(f"[SONDAGES] droits du salon : {ex}")
                self._note = "Je n'ai pas pu régler les droits de ce salon (il me faut « Gérer les rôles »)."
        await self.render_to(i)

    async def _cb_basculer(self, i):
        await i.response.defer()
        ouvert = not await ouverts(self.g)
        await _db_set(self.g.id, "sondages_actifs", int(ouvert))
        salon = await salon_de(self.g)
        self._note = ""
        if salon is not None:
            try:
                await regler_salon(self.g, salon, ouvert)
            except discord.HTTPException as ex:
                _log(f"[SONDAGES] droits du salon : {ex}")
                self._note = "Je n'ai pas pu régler les droits du salon (il me faut « Gérer les rôles »)."
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

    async def _cb_retour(self, i):
        if _retour is not None:
            await _retour(self.u, self.g, i)
        else:
            await i.response.defer()
