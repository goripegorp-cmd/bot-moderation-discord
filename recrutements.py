"""recrutements.py — le suivi des candidatures Rell Seas (19/10/2026).

« Un export mensuel de tous les dossiers de recrutement, qu'on ait un aperçu, avec un vrai
système de nettoyage : qu'on ait que le filtre, pas un surplus de données qui sert à rien. »
Puis : « les fiches de toutes celles et ceux qui ont candidaté, acceptés et refusés » — et
plutôt qu'un fichier, « un vrai site interactif » : le tableau de bord (`tableau.py`).

Une ligne par ticket Rell Seas clôturé : qui, quand, par qui, ses réponses, le motif — jamais
la conversation (elle reste dans le transcript). Les tickets fermés avant ce suivi sont
rattrapés une fois depuis l'historique des tickets.

« Garder uniquement les personnes qui ont été acceptées ou refusées » : une fiche n'existe que
pour une décision claire — décision prise avec les boutons du ticket ou du tableau de bord,
enregistrée telle quelle (colonne `decision`, 24/10/2026 : le texte libre « Non admis » ou
« Recrutements fermés » passait pour un « Accepté ») ; pour les anciens tickets, le rôle du clan
(accepté) ou une lecture prudente du motif de fermeture (« accepté », « refusé », négations
comprises). Un ticket encore ouvert → En cours. Le reste (sans suite, vide, doublon) est
écarté et seulement compté. Un candidat parti du serveur garde sa décision, marquée « parti ».

Nettoyage : un candidat = une fiche (avec ses candidatures précédentes) ; réponses bornées ;
lignes de plus d'un an effacées par la rétention RGPD (`gdpr.RETENTION`).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

import activite_calendrier as cal
import visuels

MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre")
STATUTS = {"acceptes": "Accepté", "refuses": "Refusé", "en_cours": "En cours"}
REPONSES_MAX, QUESTION_MAX, REPONSE_MAX = 10, 120, 600
APERCU_MAX = 10
CLE_EXPORT = "recrutements_export"
CLE_RATTRAPAGE = "recrutements_rattrapage_v1"
CLE_RECAP = "recrutements_recap_v1"
#  La lecture prudente des anciens motifs (sans décision enregistrée) : une négation devant « accepté »,
#  « admis », « retenu » ou « recruté » est un refus ; « recrutement(s) » n'est pas une décision.
ACCEPTE = re.compile(r"\baccept(?:é|ée|és|ées|e|er|ed)?\b|\badmise?s?\b|bienvenue dans|\brecrut(?:é|ée|és|ées)\b",
                     re.I)
REFUS = re.compile(r"refus|\brejet|\b(?:pas|non|plus|jamais)\s+(?:\S+\s+){0,2}?(?:retenu|accept|admis|recrut)",
                   re.I)
DOUBLON = re.compile(r"doublon", re.I)
DECISIONS = ("acceptes", "refuses")

_get_db = _cfg = _db_set = _salon = _role = _panneaux = _lien = _decider = _autorise = None
_bot = None
_log = print


def setup(*, get_db, cfg, db_set, salon, role, panneaux, lien=None, decider=None, autorise=None,
          log=None):
    """`salon(g, c)` → salon des transcripts Rell Seas ; `role(g, c)` → rôle du clan ;
    `panneaux(c)` → panneaux de tickets Rell Seas ; `lien(i)` → (lien du tableau de bord, refus) ;
    `decider(g, ticket, auteur, accepte, motif)` → (ok, message) ; `autorise(i)` → peut décider."""
    global _get_db, _cfg, _db_set, _salon, _role, _panneaux, _lien, _decider, _autorise, _log
    _get_db, _cfg, _db_set, _salon, _role = get_db, cfg, db_set, salon, role
    _panneaux, _lien, _decider, _autorise = panneaux, lien, decider, autorise
    _log = log or print


async def init_db():
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS recrutements ("
            " guild_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL, candidat_id INTEGER NOT NULL,"
            " candidat_nom TEXT, ouvert_le INTEGER, ferme_le INTEGER NOT NULL, ferme_par INTEGER,"
            " pris_par INTEGER, reponses TEXT, msg_candidat INTEGER DEFAULT 0,"
            " msg_staff INTEGER DEFAULT 0, transcript TEXT, raison TEXT DEFAULT '',"
            " decision TEXT DEFAULT '', PRIMARY KEY (guild_id, ticket_id))")
        async with db.execute("PRAGMA table_info(recrutements)") as cur:
            colonnes = [r[1] for r in await cur.fetchall()]
        if "raison" not in colonnes:
            await db.execute("ALTER TABLE recrutements ADD COLUMN raison TEXT DEFAULT ''")
        if "decision" not in colonnes:  # 24/10/2026 : la décision des boutons, telle quelle
            await db.execute("ALTER TABLE recrutements ADD COLUMN decision TEXT DEFAULT ''")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_recrutements_mois"
                         " ON recrutements(guild_id, ferme_le)")
        await db.commit()


# ─── Le mois ────────────────────────────────────────────────────────────────

def cle_mois(d: datetime) -> str:
    return cal.mois(d)


def mois_precedent(d: datetime) -> str:
    return cal.mois(cal.debut_de_mois(d) - timedelta(days=1))


def bornes(mois: str) -> tuple[int, int]:
    if mois == "tout":
        return 0, 2 ** 40
    a, m = (int(x) for x in mois.split("-"))
    debut = datetime(a, m, 1, tzinfo=cal.FUSEAU)
    return int(debut.timestamp()), int(cal.fin_de_mois(debut).timestamp())


def libelle(mois: str) -> str:
    if mois == "tout":
        return "depuis le début"
    a, m = mois.split("-")
    return f"{MOIS[int(m) - 1]} {a}"


# ─── L'enregistrement ───────────────────────────────────────────────────────

def garder(reponses) -> dict:
    """Les réponses du formulaire : espaces écrasés, longueurs bornées, vides retirés."""
    out = {}
    for q, r in list((reponses or {}).items()):
        q = re.sub(r"\s+", " ", str(q)).strip()[:QUESTION_MAX]
        r = re.sub(r"[ \t]+", " ", str(r)).strip()
        if q and r:
            out[q] = r if len(r) <= REPONSE_MAX else r[:REPONSE_MAX - 1] + "…"
        if len(out) >= REPONSES_MAX:
            break
    return out


async def enregistrer(guild_id: int, ticket_id: int, candidat_id: int, candidat_nom: str,
                      events, reponses, participants, url, decision: str = "") -> None:
    """À la clôture : une ligne par ticket, jamais la conversation. `decision` : celle des boutons
    (« acceptes », « refuses »), sinon vide — le statut se lit alors prudemment dans le motif.
    `participants` None : la conversation n'a pas pu être relue (compteurs inconnus, pas « vide »)."""
    ouvert = next((int(t) for k, _a, _d, t in events if k == "create" and t), None)
    fin = next(((int(t), int(a or 0), str(d or "")) for k, a, d, t in reversed(events)
                if k == "close" and t), None)
    ferme_le, ferme_par, raison = fin or (int(datetime.now(timezone.utc).timestamp()), 0, "")
    pris_par = next((int(a or 0) for k, a, _d, _t in reversed(events) if k == "claim"), 0)
    if participants is None:
        cand = staff = None
    else:
        cand = sum(p["n"] for p in participants if p["id"] == candidat_id)
        staff = sum(p["n"] for p in participants if p["id"] != candidat_id and not p["bot"])
    async with _get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO recrutements (guild_id, ticket_id, candidat_id, candidat_nom,"
            " ouvert_le, ferme_le, ferme_par, pris_par, reponses, msg_candidat, msg_staff,"
            " transcript, raison, decision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (guild_id, ticket_id, candidat_id, str(candidat_nom or "")[:100], ouvert, ferme_le,
             ferme_par, pris_par, json.dumps(garder(reponses), ensure_ascii=False), cand,
             staff, url or "", raison[:200], decision if decision in DECISIONS else ""))
        await db.commit()


def _unix(texte) -> int | None:
    """« 2026-10-19 14:05:00 » (UTC, SQLite) → horodatage ; la date bouche-trou de 2020 → None."""
    try:
        d = datetime.strptime(str(texte)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return None if d.year <= 2020 else int(d.timestamp())


async def _lignes(db, sql: str, args: tuple) -> list:
    try:
        async with db.execute(sql, args) as cur:
            return await cur.fetchall()
    except sqlite3.OperationalError as ex:
        if "no such table" not in str(ex):
            raise  # base occupée, verrou… : l'appelant affiche « données indisponibles », pas « 0 »
        _log(f"[RECRUTEMENTS:DETAIL] lecture : table absente {ex}")  # base ancienne : rien d'elle
        return []


async def rattraper(g) -> int:
    """Une fois : les tickets Rell Seas fermés avant ce suivi entrent dans le registre, depuis
    l'historique des tickets (réponses, staff, motif, dates, transcript)."""
    c = await _cfg(g.id)
    if c.get(CLE_RATTRAPAGE):
        return 0
    pids = sorted(_panneaux(c)) if _panneaux else []
    n = 0
    if pids:
        marques = ",".join("?" * len(pids))
        async with _get_db() as db:
            tickets = await _lignes(
                db, f"SELECT id, user_id, claimed_by, answers, created_at, channel_id FROM tickets"
                    f" WHERE guild_id=? AND status='closed' AND panel_id IN ({marques})", (g.id, *pids))
            for tid, uid, pris, reponses, cree, salon in tickets:
                evts = await _lignes(db, "SELECT kind, actor_id, detail, created_unix FROM"
                                         " ticket_log_events WHERE guild_id=? AND ticket_id=?"
                                         " ORDER BY id", (g.id, tid))
                audit = await _lignes(db, "SELECT action, actor_id, detail, at FROM ticket_audit"
                                          " WHERE guild_id=? AND channel_id=? ORDER BY id",
                                      (g.id, salon))
                tr = await _lignes(db, "SELECT url, user_name FROM ticket_transcripts"
                                       " WHERE guild_id=? AND ticket_id=?", (g.id, tid))
                fermeture = next(((int(t), int(a or 0)) for k, a, _d, t in reversed(evts)
                                  if k == "close" and t), None)
                fa = next(((_unix(t), int(a or 0), str(d or "")) for k, a, d, t in reversed(audit)
                           if k == "close"), None)
                ouvert = next((int(t) for k, _a, _d, t in evts if k == "create" and t), None) \
                    or _unix(cree)
                ferme_le, ferme_par = fermeture or ((fa[0], fa[1]) if fa and fa[0] else (ouvert, 0))
                if not ferme_le:
                    continue
                pris_par = int(pris or 0) or next(
                    (int(a or 0) for k, a, _d, _t in reversed(evts) if k == "claim"), 0)
                try:
                    rep = json.loads(reponses or "{}")
                except ValueError:
                    rep = {}
                m = g.get_member(int(uid or 0))
                nom = m.display_name if m else (tr[0][1] if tr else "")
                await db.execute(
                    "INSERT OR IGNORE INTO recrutements (guild_id, ticket_id, candidat_id,"
                    " candidat_nom, ouvert_le, ferme_le, ferme_par, pris_par, reponses,"
                    " msg_candidat, msg_staff, transcript, raison)"
                    " VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)",
                    (g.id, int(tid), int(uid or 0), str(nom or "")[:100], ouvert, ferme_le,
                     ferme_par, pris_par, json.dumps(garder(rep if isinstance(rep, dict) else {}),
                                                     ensure_ascii=False),
                     tr[0][0] if tr else "", (fa[2] if fa else "")[:200]))
                n += 1
            await db.commit()
    await _db_set(g.id, CLE_RATTRAPAGE, datetime.now(timezone.utc).isoformat())
    if n:
        _log(f"[RECRUTEMENTS] {n} candidature(s) rattrapée(s)")
    return n


# ─── Les fiches ─────────────────────────────────────────────────────────────

async def lire(guild_id: int, mois: str = "tout") -> list[dict]:
    debut, fin = bornes(mois)
    async with _get_db() as db:
        async with db.execute(
                "SELECT ticket_id, candidat_id, candidat_nom, ouvert_le, ferme_le, ferme_par,"
                " pris_par, reponses, msg_candidat, transcript, raison, decision FROM recrutements"
                " WHERE guild_id=? AND ferme_le >= ? AND ferme_le < ? ORDER BY ferme_le",
                (guild_id, debut, fin)) as cur:
            rows = await cur.fetchall()
    cles = ("ticket", "candidat_id", "nom", "ouvert", "ferme", "ferme_par", "pris_par",
            "reponses", "msg_candidat", "transcript", "raison", "decision")
    out = []
    for r in rows:
        d = dict(zip(cles, r))
        try:
            d["reponses"] = json.loads(d["reponses"] or "{}")
        except ValueError:
            d["reponses"] = {}
        d["raison"] = d["raison"] or ""
        d["decision"] = d["decision"] or ""
        out.append(d)
    return out


async def du_candidat(guild_id: int, candidat_id: int) -> list[dict]:
    """Toutes les candidatures fermées d'une personne, de la plus récente à la plus ancienne."""
    async with _get_db() as db:
        rows = await _lignes(db, "SELECT ticket_id, ouvert_le, ferme_le, raison, reponses, transcript, decision"
                                 " FROM recrutements WHERE guild_id=? AND candidat_id=? ORDER BY ferme_le DESC",
                             (int(guild_id), int(candidat_id)))
    out = []
    for tid, ouvert, ferme, raison, reponses, transcript, prise in rows:
        try:
            rep = json.loads(reponses or "{}")
        except ValueError:
            rep = {}
        out.append({"ticket": tid, "ouvert": ouvert, "ferme": ferme, "raison": raison or "",
                    "statut": decision(False, raison or "", prise or "") or "", "reponses": rep,
                    "transcript": transcript or ""})
    return out


def decision(a_le_role: bool, raison: str, prise: str = "") -> str | None:
    """La décision prise, ou None quand rien ne l'établit (ticket sans suite). `prise` : la décision
    enregistrée par les boutons — elle fait foi. Sans elle (anciens tickets), une lecture prudente : un
    refus ou une négation (« Non admis », « pas acceptée ») l'emporte ; puis le rôle du clan ou un
    « accepté » explicite ; « Recrutements fermés » n'est pas une décision."""
    if prise in DECISIONS:
        return prise
    if REFUS.search(raison or ""):
        return "refuses"
    if a_le_role or ACCEPTE.search(raison or ""):
        return "acceptes"
    return None


def nettoyer(lignes: list[dict], statut_de) -> tuple[list[dict], int, int]:
    """Une fiche par candidat (son dernier ticket décidé, la liste de ses candidatures). Écartés,
    seulement comptés : ticket vide, doublon, et ticket fermé sans décision établie."""
    vides = doublons = sans_suite = 0
    par_candidat: dict = {}
    for d in lignes:
        if d["msg_candidat"] == 0:
            vides += 1
            continue
        if DOUBLON.search(d.get("raison") or ""):
            doublons += 1
            continue
        d = dict(d, statut=d["decision"] if d.get("decision") in DECISIONS
                 else statut_de(d["candidat_id"], d.get("raison") or ""))
        if d["statut"] is None:
            sans_suite += 1
            continue
        prec = par_candidat.get(d["candidat_id"])
        dates = (prec["dates"] if prec else []) + [d["ferme"]]
        if prec is None or d["ferme"] >= prec["ferme"]:
            par_candidat[d["candidat_id"]] = dict(d, dates=dates)
        else:
            prec["dates"] = dates
    fiches = sorted(par_candidat.values(), key=lambda d: -d["ferme"])
    for d in fiches:
        d["dates"] = sorted(d["dates"])
    return fiches, vides + sans_suite, doublons


async def en_cours(g, c=None) -> list[dict]:
    """Les candidatures dont le ticket est encore ouvert."""
    c = c or await _cfg(g.id)
    pids = sorted(_panneaux(c)) if _panneaux else []
    if not pids:
        return []
    marques = ",".join("?" * len(pids))
    async with _get_db() as db:
        rows = await _lignes(db, f"SELECT id, user_id, claimed_by, answers, created_at, channel_id"
                                 f" FROM tickets WHERE guild_id=? AND status='open'"
                                 f" AND panel_id IN ({marques}) ORDER BY id", (g.id, *pids))
    out = []
    for tid, uid, pris, reponses, cree, salon in rows:
        try:
            rep = json.loads(reponses or "{}")
        except ValueError:
            rep = {}
        out.append({"ticket": tid, "candidat_id": int(uid or 0), "pris_par": int(pris or 0),
                    "reponses": garder(rep if isinstance(rep, dict) else {}), "ouvert": _unix(cree),
                    "salon": int(salon or 0), "statut": "en_cours"})
    return out


async def candidatures(g, mois: str = "tout") -> dict:
    """Tout ce que le tableau de bord et les bilans montrent : fiches nettoyées + en cours."""
    c = await _cfg(g.id)
    role = _role(g, c) if _role else None

    def statut_de(uid, raison):
        m = g.get_member(int(uid))
        return decision(role is not None and m is not None and role in m.roles, raison)
    fiches, vides, doublons = nettoyer(await lire(g.id, mois), statut_de)
    for d in fiches:
        d["parti"] = g.get_member(int(d["candidat_id"])) is None
    return {"fiches": fiches, "vides": vides, "doublons": doublons,
            "en_cours": await en_cours(g, c) if mois == "tout" else []}


async def retirer_fiche(guild_id: int, candidat_id: int) -> int:
    """« Enlever des fiches » : toutes les lignes de ce candidat. Rend le nombre retiré."""
    async with _get_db() as db:
        cur = await db.execute("DELETE FROM recrutements WHERE guild_id=? AND candidat_id=?",
                               (guild_id, candidat_id))
        await db.commit()
        return int(cur.rowcount or 0)


def compter(fiches: list[dict], ouverts: list[dict]) -> dict:
    n = {k: 0 for k in STATUTS}
    for d in fiches:
        n[d["statut"]] += 1
    n["en_cours"] = len(ouverts)
    return n


def resume(fiches: list[dict], ouverts: list[dict], vides: int = 0, doublons: int = 0) -> str:
    n = compter(fiches, ouverts)
    total = len(fiches) + len(ouverts)
    parts = [f"{total} candidature{'s' if total > 1 else ''}"]
    parts += [f"{STATUTS[k]}{'s' if n[k] > 1 and k != 'en_cours' else ''} {n[k]}"
              for k in STATUTS if n[k]]
    ecartes = vides + doublons
    if ecartes:
        parts.append(f"{ecartes} écarté{'s' if ecartes > 1 else ''} (sans décision, vides ou doublons)")
    return " · ".join(parts)


def _quand(t, fmt: str) -> str:
    return datetime.fromtimestamp(int(t), timezone.utc).astimezone(cal.FUSEAU).strftime(fmt) if t else "—"


# ─── Les cartes Discord : un résumé et le tableau de bord ───────────────────

class BoutonTableau(discord.ui.DynamicItem[discord.ui.Button], template=r"recr:web"):
    """Sous chaque bilan : le lien personnel du tableau de bord, envoyé à soi seul."""

    def __init__(self):
        super().__init__(discord.ui.Button(label="Ouvrir le tableau de bord", custom_id="recr:web",
                                           style=discord.ButtonStyle.primary,
                                           emoji=visuels.icone("stats")))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, i: discord.Interaction):
        await envoyer_lien(i)


async def envoyer_lien(i: discord.Interaction) -> None:
    """Le lien personnel du tableau de bord, à soi seul — ou la raison du refus."""
    url, refus = await _lien(i) if _lien else (None, "Le tableau de bord n'est pas branché.")
    if not url:
        return await i.response.send_message(refus, ephemeral=True)
    v = discord.ui.View()
    v.add_item(discord.ui.Button(label="Ouvrir le tableau de bord", url=url, emoji=visuels.icone("lien")))
    await i.response.send_message("Ton lien personnel : il ne s'ouvre qu'une fois, valable 24 h. "
                                  "Ne le partage pas.", view=v, ephemeral=True)


class BoutonDecision(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"recr:dec:(?P<d>[ar]):(?P<tid>\d+)"):
    """« Les nouveaux tickets avec les nouvelles mécaniques » : la décision se prend dans le
    ticket. Accepter donne le rôle du clan et ferme ; refuser ferme avec le motif."""

    def __init__(self, decision: str, ticket: int):
        self.decision, self.ticket = decision, int(ticket)
        accepte = decision == "a"
        super().__init__(discord.ui.Button(
            label="Accepter" if accepte else "Refuser", custom_id=f"recr:dec:{decision}:{self.ticket}",
            style=discord.ButtonStyle.success if accepte else discord.ButtonStyle.danger,
            emoji=visuels.icone("valider" if accepte else "interdit")))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["d"], int(match["tid"]))

    async def callback(self, i: discord.Interaction):
        if _autorise is None or not await _autorise(i):
            return await i.response.send_message("Réservé à l'équipe de recrutement Rell Seas.", ephemeral=True)
        if self.decision == "r":
            return await i.response.send_modal(MotifRefus(self.ticket))
        await i.response.defer(ephemeral=True)
        ok, message = await _decider(i.guild, self.ticket, i.user, True, "")
        await i.followup.send(message, ephemeral=True)


class MotifRefus(discord.ui.Modal, title="Refuser la candidature"):
    motif = discord.ui.TextInput(label="Motif (le candidat ne le voit pas)", required=False,
                                 max_length=150, placeholder="Niveau insuffisant, trop jeune…")

    def __init__(self, ticket: int):
        super().__init__()
        self.ticket = ticket

    async def on_submit(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        ok, message = await _decider(i.guild, self.ticket, i.user, False, str(self.motif.value or "").strip())
        await i.followup.send(message, ephemeral=True)


def carte_decision(ticket: int) -> discord.ui.LayoutView:
    v = discord.ui.LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        discord.ui.TextDisplay("### Décision de recrutement\n-# Réservé à l'équipe Rell Seas. Accepter donne "
                               "le rôle du clan et ferme le ticket ; refuser ferme le ticket — le candidat lit "
                               "« Candidature refusée », le motif reste à l'équipe."),
        discord.ui.ActionRow(BoutonDecision("a", ticket), BoutonDecision("r", ticket)),
        accent_color=0x0EA5E9))
    return v


def carte(g, titre: str, donnees: dict) -> discord.ui.LayoutView:
    fiches, ouverts = donnees["fiches"], donnees["en_cours"]
    apercu = [f"{_quand(d['ferme'], '%d/%m')} · **{_nom(g, d['candidat_id'], d['nom'])}** · "
              f"{STATUTS[d['statut']]}" for d in fiches[:APERCU_MAX]]
    if len(fiches) > APERCU_MAX:
        apercu.append(f"-# … et {len(fiches) - APERCU_MAX} autre(s) dans le tableau de bord")
    v = discord.ui.LayoutView(timeout=None)
    v.add_item(discord.ui.Container(
        visuels.bandeau("recrutement", "Recrutements Rell Seas"),
        discord.ui.TextDisplay(f"### {titre}\n"
                               f"{resume(fiches, ouverts, donnees['vides'], donnees['doublons'])}"),
        discord.ui.Separator(),
        discord.ui.TextDisplay("\n".join(apercu) or "Aucune candidature."),
        discord.ui.ActionRow(BoutonTableau()),
        accent_color=0x0EA5E9))
    return v


def _nom(g, uid, defaut="") -> str:
    m = g.get_member(int(uid)) if uid else None
    return m.display_name if m else (defaut or str(uid))


async def publier_recap(g) -> bool:
    """Une fois, après le rattrapage : le récapitulatif de toutes les candidatures."""
    c = await _cfg(g.id)
    if c.get(CLE_RECAP):
        return False
    donnees = await candidatures(g)
    if not donnees["fiches"] and not donnees["en_cours"]:
        return False
    salon = await _salon(g, c)
    if salon is None:
        return False
    await salon.send(view=carte(g, "Toutes les candidatures", donnees),
                     allowed_mentions=discord.AllowedMentions.none())
    await _db_set(g.id, CLE_RECAP, datetime.now(timezone.utc).isoformat())
    return True


async def exporter(g, maintenant: datetime | None = None) -> bool:
    """Le 1er du mois : le bilan du mois écoulé, une seule fois, jamais pour un mois vide."""
    precedent = mois_precedent(maintenant or datetime.now(timezone.utc))
    c = await _cfg(g.id)
    if c.get(CLE_EXPORT) == precedent:
        return False
    donnees = await candidatures(g, precedent)
    if not donnees["fiches"]:
        await _db_set(g.id, CLE_EXPORT, precedent)
        return False
    salon = await _salon(g, c)
    if salon is None:
        return False
    await salon.send(view=carte(g, f"Bilan · {libelle(precedent)}", donnees),
                     allowed_mentions=discord.AllowedMentions.none())
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
