"""recrutements.py — le suivi des recrutements Rell Seas (19/10/2026).

« Un export mensuel de tous les dossiers de recrutement, qu'on ait un aperçu, avec un vrai
système de nettoyage : qu'on ait que le filtre, pas un surplus de données qui sert à rien. »

Une ligne compacte par ticket Rell Seas clôturé : qui, quand, par qui, ses réponses — la
conversation reste dans le transcript. Le 1er du mois, le bilan du mois écoulé part dans le
salon des transcripts Rell Seas, avec un filtre (acceptés, sans le rôle, partis).

Nettoyage : un ticket où le candidat n'a rien écrit est écarté (seulement compté) ; un candidat
venu plusieurs fois tient en une ligne ; les réponses sont resserrées ; les lignes de plus d'un
an sont effacées par la rétention RGPD (`gdpr.RETENTION`).
"""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

import activite_calendrier as cal
import colonnes
import visuels

MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre")
FILTRES = {"tous": "Tous", "acceptes": "Acceptés", "sans_role": "Sans le rôle",
           "partis": "Partis du serveur"}
ISSUES = {"acceptes": "Accepté", "sans_role": "Sans le rôle", "partis": "Parti"}
REPONSES_MAX, QUESTION_MAX, REPONSE_MAX = 6, 40, 80
APERCU_MAX = 12
CLE_EXPORT = "recrutements_export"
_COLONNES = (("DATE", 6), ("CANDIDAT", 24), ("IDENTIFIANT", 21), ("ISSUE", 13), ("DURÉE", 10),
             ("PRIS EN CHARGE PAR", 22), ("TRANSCRIPT", 60))

_get_db = _cfg = _db_set = _salon = _role = _autorise = None
_bot = None
_log = print


def setup(*, get_db, cfg, db_set, salon, role, autorise=None, log=None):
    """`salon(g, c)` → le salon des transcripts Rell Seas ; `role(g, c)` → le rôle du clan."""
    global _get_db, _cfg, _db_set, _salon, _role, _autorise, _log
    _get_db, _cfg, _db_set, _salon, _role, _autorise = get_db, cfg, db_set, salon, role, autorise
    _log = log or print


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS recrutements ("
            " guild_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL, candidat_id INTEGER NOT NULL,"
            " candidat_nom TEXT, ouvert_le INTEGER, ferme_le INTEGER NOT NULL, ferme_par INTEGER,"
            " pris_par INTEGER, reponses TEXT, msg_candidat INTEGER DEFAULT 0,"
            " msg_staff INTEGER DEFAULT 0, transcript TEXT, PRIMARY KEY (guild_id, ticket_id))")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_recrutements_mois"
                         " ON recrutements(guild_id, ferme_le)")
        await db.commit()


# ─── Le mois ────────────────────────────────────────────────────────────────

def cle_mois(d: datetime) -> str:
    return cal.mois(d)


def mois_precedent(d: datetime) -> str:
    return cal.mois(cal.debut_de_mois(d) - timedelta(days=1))


def bornes(mois: str) -> tuple[int, int]:
    a, m = (int(x) for x in mois.split("-"))
    debut = datetime(a, m, 1, tzinfo=cal.FUSEAU)
    return int(debut.timestamp()), int(cal.fin_de_mois(debut).timestamp())


def libelle(mois: str) -> str:
    a, m = mois.split("-")
    return f"{MOIS[int(m) - 1]} {a}"


# ─── L'enregistrement, à la clôture ─────────────────────────────────────────

def resserrer(reponses) -> dict:
    """Les réponses du formulaire, réduites à l'utile : espaces écrasés, longueurs bornées."""
    out = {}
    for q, r in list((reponses or {}).items()):
        q = re.sub(r"\s+", " ", str(q)).strip()[:QUESTION_MAX]
        r = re.sub(r"\s+", " ", str(r)).strip()
        if q and r:
            out[q] = r if len(r) <= REPONSE_MAX else r[:REPONSE_MAX - 1] + "…"
        if len(out) >= REPONSES_MAX:
            break
    return out


async def enregistrer(guild_id: int, ticket_id: int, candidat_id: int, candidat_nom: str,
                      events, reponses, participants, url) -> None:
    """Une ligne par ticket : jamais la conversation, seulement ce qui sert au bilan."""
    ouvert = next((int(t) for k, _a, _d, t in events if k == "create" and t), None)
    fin = next(((int(t), int(a or 0)) for k, a, _d, t in reversed(events) if k == "close" and t), None)
    ferme_le, ferme_par = fin or (int(datetime.now(timezone.utc).timestamp()), 0)
    pris_par = next((int(a or 0) for k, a, _d, _t in reversed(events) if k == "claim"), 0)
    cand = sum(p["n"] for p in participants if p["id"] == candidat_id)
    staff = sum(p["n"] for p in participants if p["id"] != candidat_id and not p["bot"])
    async with _get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO recrutements (guild_id, ticket_id, candidat_id, candidat_nom,"
            " ouvert_le, ferme_le, ferme_par, pris_par, reponses, msg_candidat, msg_staff,"
            " transcript) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (guild_id, ticket_id, candidat_id, str(candidat_nom or "")[:100], ouvert, ferme_le,
             ferme_par, pris_par, json.dumps(resserrer(reponses), ensure_ascii=False), cand,
             staff, url or ""))
        await db.commit()


# ─── Le bilan ───────────────────────────────────────────────────────────────

async def lire(guild_id: int, mois: str) -> list[dict]:
    debut, fin = bornes(mois)
    async with _get_db() as db:
        async with db.execute(
                "SELECT ticket_id, candidat_id, candidat_nom, ouvert_le, ferme_le, ferme_par,"
                " pris_par, reponses, msg_candidat, transcript FROM recrutements"
                " WHERE guild_id=? AND ferme_le >= ? AND ferme_le < ? ORDER BY ferme_le",
                (guild_id, debut, fin)) as cur:
            rows = await cur.fetchall()
    cles = ("ticket", "candidat_id", "nom", "ouvert", "ferme", "ferme_par", "pris_par",
            "reponses", "msg_candidat", "transcript")
    out = []
    for r in rows:
        d = dict(zip(cles, r))
        try:
            d["reponses"] = json.loads(d["reponses"] or "{}")
        except ValueError:
            d["reponses"] = {}
        out.append(d)
    return out


def nettoyer(lignes: list[dict], issue_de) -> tuple[list[dict], int]:
    """Un candidat = une ligne (son dernier dossier, avec le nombre de tickets) ; un ticket où le
    candidat n'a rien écrit est écarté et seulement compté."""
    vides = sum(1 for d in lignes if not d["msg_candidat"])
    par_candidat: dict = {}
    for d in lignes:
        if not d["msg_candidat"]:
            continue
        prec = par_candidat.get(d["candidat_id"])
        n = (prec["tickets"] if prec else 0) + 1
        if prec is None or d["ferme"] >= prec["ferme"]:
            par_candidat[d["candidat_id"]] = dict(d, tickets=n)
        else:
            prec["tickets"] = n
    dossiers = sorted(par_candidat.values(), key=lambda d: d["ferme"])
    for d in dossiers:
        d["issue"] = issue_de(d["candidat_id"])
    return dossiers, vides


def duree(d: dict) -> str:
    if not d.get("ouvert") or d["ferme"] < d["ouvert"]:
        return "—"
    mn = (d["ferme"] - d["ouvert"]) // 60
    j, reste = divmod(mn, 1440)
    h, m = divmod(reste, 60)
    return f"{j} j {h} h" if j else f"{h} h {m:02d}" if h else f"{m} min"


def resume(dossiers: list[dict], vides: int) -> str:
    n = len(dossiers)
    parts = [f"{n} dossier{'s' if n > 1 else ''}"]
    parts += [f"{ISSUES[k]}{'s' if sum(d['issue'] == k for d in dossiers) > 1 else ''} "
              f"{sum(d['issue'] == k for d in dossiers)}"
              for k in ISSUES if any(d["issue"] == k for d in dossiers)]
    if vides:
        parts.append(f"{vides} ticket{'s' if vides > 1 else ''} vide{'s' if vides > 1 else ''} écarté{'s' if vides > 1 else ''}")
    return " · ".join(parts)


def _quand(t: int, fmt: str) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).astimezone(cal.FUSEAU).strftime(fmt)


def texte_fichier(serveur: str, mois: str, garde: list[dict], tous: list[dict], vides: int,
                  filtre: str, nom_de) -> str:
    lignes = [f"RECRUTEMENTS RELL SEAS · {libelle(mois)} · {serveur}",
              resume(tous, vides),
              f"Filtre : {FILTRES[filtre]} · {len(garde)} ligne(s)",
              ""]
    lignes += colonnes.entete(_COLONNES)
    for d in garde:
        nom = nom_de(d["candidat_id"], d["nom"]) + (f" ×{d['tickets']}" if d["tickets"] > 1 else "")
        valeurs = (_quand(d["ferme"], "%d/%m"), nom, d["candidat_id"], ISSUES[d["issue"]], duree(d),
                   nom_de(d["pris_par"], "—") if d["pris_par"] else "—")
        #  Le lien reste entier, en dernière colonne : coupé, il ne mènerait nulle part.
        lignes.append("".join(colonnes.cadrer(v, w) + " " for v, (_t, w) in zip(valeurs, _COLONNES))
                      + (d["transcript"] or "—"))
        if d["reponses"]:
            lignes.append(" " * 7 + " · ".join(f"{q} : {r}" for q, r in d["reponses"].items()))
    if not garde:
        lignes.append("Aucun dossier pour ce filtre.")
    return "\n".join(lignes + [""])


def vue_bilan(mois: str, garde: list[dict], tous: list[dict], vides: int, filtre: str,
              nom_fichier: str, nom_de) -> discord.ui.LayoutView:
    apercu = [f"{_quand(d['ferme'], '%d/%m')} · **{nom_de(d['candidat_id'], d['nom'])}** · "
              f"{ISSUES[d['issue']]}" for d in garde[:APERCU_MAX]]
    if len(garde) > APERCU_MAX:
        apercu.append(f"-# … et {len(garde) - APERCU_MAX} autre(s) dans le fichier")
    titre = f"### {libelle(mois).capitalize()}" + ("" if filtre == "tous" else f" · {FILTRES[filtre]}")
    v = discord.ui.LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        visuels.bandeau("recrutement", "Recrutements Rell Seas"),
        discord.ui.TextDisplay(f"{titre}\n{resume(tous, vides)}"),
        discord.ui.Separator(),
        discord.ui.TextDisplay("\n".join(apercu) or "Aucun dossier pour ce filtre."),
        discord.ui.File(f"attachment://{nom_fichier}"),
        discord.ui.ActionRow(FiltreRecrutement(mois)),
        accent_color=0x0EA5E9))
    return v


async def bilan(g, mois: str, filtre: str = "tous"):
    """(vue, fichier) du mois — `filtre` : tous, acceptes, sans_role, partis."""
    filtre = filtre if filtre in FILTRES else "tous"
    c = await _cfg(g.id)
    role = _role(g, c) if _role else None

    def issue_de(uid):
        m = g.get_member(int(uid))
        if m is None:
            return "partis"
        return "acceptes" if role is not None and role in m.roles else "sans_role"

    def nom_de(uid, defaut):
        m = g.get_member(int(uid)) if uid else None
        return m.display_name if m else (defaut or str(uid))
    tous, vides = nettoyer(await lire(g.id, mois), issue_de)
    garde = tous if filtre == "tous" else [d for d in tous if d["issue"] == filtre]
    nom = f"recrutements-{mois}" + ("" if filtre == "tous" else f"-{filtre}") + ".txt"
    texte = texte_fichier(g.name, mois, garde, tous, vides, filtre, nom_de)
    return (vue_bilan(mois, garde, tous, vides, filtre, nom, nom_de),
            discord.File(io.BytesIO(texte.encode("utf-8")), filename=nom))


class FiltreRecrutement(discord.ui.DynamicItem[discord.ui.Select],
                        template=r"recr:f:(?P<mois>\d{4}-\d{2})"):
    """Le filtre sous chaque bilan : renvoie, à soi seul, le fichier filtré du mois."""

    def __init__(self, mois: str):
        self.mois = mois
        super().__init__(discord.ui.Select(
            placeholder="Filtrer le mois…", custom_id=f"recr:f:{mois}",
            options=[discord.SelectOption(label=v, value=k) for k, v in FILTRES.items()]))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["mois"])

    async def callback(self, i: discord.Interaction):
        if _autorise is not None and not await _autorise(i):
            return await i.response.send_message("Réservé à l'équipe Rell Seas.", ephemeral=True)
        await i.response.defer(ephemeral=True, thinking=True)
        vue, fichier = await bilan(i.guild, self.mois, (i.data.get("values") or ["tous"])[0])
        await i.followup.send(view=vue, file=fichier, ephemeral=True,
                              allowed_mentions=discord.AllowedMentions.none())


# ─── L'export du 1er du mois ────────────────────────────────────────────────

async def exporter(g, maintenant: datetime | None = None) -> bool:
    """Le bilan du mois écoulé, une seule fois, dans le salon des transcripts Rell Seas."""
    precedent = mois_precedent(maintenant or datetime.now(timezone.utc))
    c = await _cfg(g.id)
    if c.get(CLE_EXPORT) == precedent:
        return False
    if not await lire(g.id, precedent):
        await _db_set(g.id, CLE_EXPORT, precedent)
        return False
    salon = await _salon(g, c)
    if salon is None:
        return False
    vue, fichier = await bilan(g, precedent)
    await salon.send(view=vue, file=fichier, allowed_mentions=discord.AllowedMentions.none())
    await _db_set(g.id, CLE_EXPORT, precedent)
    return True


@tasks.loop(hours=1)
async def export_task():
    for g in list(getattr(_bot, "guilds", []) or []):
        try:
            if await exporter(g):
                _log("[RECRUTEMENTS] bilan mensuel publié")
        except discord.HTTPException as ex:
            _log(f"[RECRUTEMENTS][E1] bilan non publié : {ex}")


@export_task.before_loop
async def _attendre():
    if _bot is not None:
        await _bot.wait_until_ready()


def demarrer(bot) -> None:
    global _bot
    _bot = bot
    if not export_task.is_running():
        export_task.start()
