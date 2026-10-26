"""Le banc d'un VRAI ticket de recrutement (26/10/2026) : les fonctions de `bot.py` (ouverture, accueil, équipe qui
entre dans le fil, décision, fermeture) lues dans sa source et exécutées sur le faux Discord, avec `questionnaire.py`
branché comme dans `_activite_boot`. Rien n'est imité à la main : un message de plus dans le code est un message de plus
ici. Sert à COMPTER les messages qu'un candidat voit dans son ticket, de l'ouverture à la fermeture."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import discord

import questionnaire as Q
import recrutements
import rellseas_panneau
import textes as textes_registre
import tickets_fils as tickets_fils_vrai
import visuels
from conftest_discord import Obj, laisser_finir
from faux_serveur import Fil, Message, Monde, Partiel, Texte
from ui_v2 import LayoutView, Palette, View

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)
FONDATEUR, DIRECTION, CANDIDAT, AUTRE, RECRUTEUR, BOT = 781205382923288593, 827633340797681714, 50, 60, 70, 999
EXEMPLE = Path(__file__).resolve().parent / "questionnaire_exemple.json"
LIENS = Path(__file__).resolve().parent / "questionnaire_liens_exemple.json"

#  Ce que bot.py définit et que le chemin d'un ticket de recrutement emploie (dans cet ordre : une classe avant ceux
#  qui la nomment). Un nom disparu de bot.py fait échouer le banc, et le dit.
NOMS_DU_BOT = (
    "TETE_IDS", "_direction_ou_plus", "_ticket_sans_limite", "_tickets_en_creation", "get_ticket", "_ticket_ouvert",
    "_CASIER_MOTS", "_BOUTONS_TICKET", "_contexte_ticket", "TicketControlView", "_vue_dossier_ticket",
    "_vue_dossier_ticket_de", "_accueil_recrutement", "_equipe_du_type", "_equipe_direction", "EQUIPE_TICKET_MAX",
    "_TICKETS_VUS", "_COMPTES_SUPPRIMES", "_TACHES_TICKETS_VUS", "_equipe_a_voir", "_carte_equipe", "_echec",
    "_SansCarte", "_faire_voir_ticket", "_faire_voir_plus_tard", "_create_ticket_corps", "create_ticket",
    "_TACHES_FERMETURE", "_fermer_en_fond", "_tickets_en_fermeture", "_garder_ticket_sans_transcript",
    "_fermer_ticket_corps", "_fermer_ticket", "_decision_recrutement", "_peut_decider", "_vue_ticket_message",
    "TicketQuestionnaireModal", "TicketConfirmCreateView", "_ticket_ouvrir",
)
#  Des noms facultatifs (ajoutés par le chantier du recrutement, 26/10/2026) : lus s'ils existent (le banc mesure aussi
#  le code d'avant).
NOMS_FACULTATIFS = ("_recrutement_extras", "_liste_noire_recrutement", "_role_clan_de", "_metiers_catalogue",
                    "_fiche_recue",
                    #  26/10/2026 (sécurité) : « Accepter » passe par la règle de /rellseas (jamais un membre sanctionné).
                    "_RADIE_ROLE_NAME", "_QUARANTINE_ROLE_NAMES", "_refus_cible_rellseas")


def _noeud(nom):
    for n in ARBRE.body:
        cible = getattr(n, "name", None)
        if cible is None and isinstance(n, ast.Assign):
            cible = next((t.id for t in n.targets if isinstance(t, ast.Name)), None)
        elif cible is None and isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            cible = n.target.id
        if cible == nom:
            return n
    return None


def source(nom) -> str:
    n = _noeud(nom)
    if n is None:
        raise AssertionError(f"bot.py ne définit plus {nom}")
    return ast.unparse(n)


class _Asyncio:
    """`asyncio` sans attente : les pauses du bot (2 s avant de relire les membres du fil, 5 s avant de supprimer
    un ticket) passent la main sans dormir."""
    def __getattr__(self, nom):
        return getattr(asyncio, nom)

    @staticmethod
    async def sleep(_delai=0, *_a, **_k):
        await asyncio.sleep(0)


class MessageFil(Message):
    """Un message du fil : réécrit (la carte se relit à sa dernière version), supprimé."""

    async def edit(self, **kw):
        if self.id in self.salon.monde.effaces:
            raise discord.NotFound(Obj(status=404, reason="x"), "absent")
        self.salon.cartes.append((self.id, kw))
        self.salon.entrer_par_mention(kw.get("allowed_mentions"))

    async def delete(self, **_kw):
        self.salon.monde.effaces.add(self.id)


class FilTicket(Fil):
    """Le fil privé d'un ticket : ses membres, et Discord qui fait entrer qui est mentionné par une modification."""

    def __init__(self, monde, tid, parent, name):
        super().__init__(monde, tid, parent, name)
        self.dedans, self.ajouts, self.supprime = set(), [], False
        self.max_visibles = 0          # le plus grand nombre de messages du bot visibles À LA FOIS

    async def send(self, content=None, **kw):
        if self.supprime:
            raise discord.NotFound(Obj(status=404, reason="x"), "fil supprimé")
        self.envois.append((content, kw))
        m = MessageFil(self, self.monde.nouvel_id())
        m.content, m.kw, m.reference = content, kw, None
        self.messages.append(m)
        self.max_visibles = max(self.max_visibles, len(self.visibles()))
        return m

    def entrer_par_mention(self, am):
        if am is None:
            return
        for u in am.users if isinstance(am.users, list) else []:
            self.dedans.add(u.id)
        for r in am.roles if isinstance(am.roles, list) else []:
            self.dedans.update(m.id for m in getattr(r, "members", []))

    async def fetch_members(self):
        return [Obj(id=x) for x in self.dedans]

    async def add_user(self, m):
        self.ajouts.append(m.id)
        self.dedans.add(m.id)

    async def delete(self, *, reason=None):
        self.supprime = True
        await super().delete(reason=reason)

    def get_partial_message(self, mid):
        fil = self

        class P(Partiel):
            async def edit(self, **kw):
                await super().edit(**kw)
                fil.entrer_par_mention(kw.get("allowed_mentions"))
        return P(self, mid)

    # ─── Ce que le candidat voit ───
    def visibles(self) -> list:
        return [m for m in self.messages if m.id not in self.monde.effaces]

    def vue(self, m):
        """La dernière version d'un message (sa vue), réécritures comprises."""
        kw = next((k for mid, k in reversed(self.cartes) if mid == m.id), m.kw)
        return kw.get("view")


class Role:
    def __init__(self, rid, name, position=1):
        self.id, self.name, self.position = rid, name, position
        self.mention, self.mentionable, self.managed, self.members = f"<@&{rid}>", False, False, []

    def is_default(self):
        return False

    def __ge__(self, autre):
        return self.position >= autre.position

    def __lt__(self, autre):
        return self.position < autre.position


class Membre:
    def __init__(self, uid, nom, *roles):
        self.id, self.mention, self.display_name, self.name = uid, f"<@{uid}>", nom, nom.lower()
        self.display_avatar = Obj(url=f"https://cdn.discordapp.com/avatars/{uid}.png")
        self.display_avatar.with_size = lambda _n: self.display_avatar
        self.roles, self.bot = list(roles), False
        self.guild_permissions = Obj(administrator=False, manage_roles=False)
        self.created_at = datetime(2024, 1, 2, tzinfo=timezone.utc)
        self.joined_at = datetime(2026, 3, 4, tzinfo=timezone.utc)
        self.mp, self.mp_ferme = [], False
        for r in roles:
            r.members.append(self)

    @property
    def top_role(self):
        return max(self.roles, key=lambda r: r.position) if self.roles else Role(0, "@everyone", 0)

    async def add_roles(self, *roles, reason=None):
        for r in roles:
            if r not in self.roles:
                self.roles.append(r)
                r.members.append(self)

    async def remove_roles(self, *roles, reason=None):
        for r in roles:
            if r in self.roles:
                self.roles.remove(r)
                r.members.remove(self)

    async def send(self, content=None, **kw):
        if self.mp_ferme:
            raise discord.Forbidden(Obj(status=403, reason="x"), {"code": 50007, "message": "Cannot send messages"})
        self.mp.append((content, kw))
        return Obj(id=len(self.mp))

    def __str__(self):
        return self.display_name


class Serveur(Monde):
    owner = None

    def __init__(self):
        super().__init__(forum=False, communautaire=False)
        self.roles_ = {}
        self.default_role = Role(1, "@everyone", 0)

    def get_role(self, rid):
        return self.roles_.get(int(rid or 0))

    def role(self, nom, position):
        r = Role(self.nouvel_id(), nom, position)
        self.roles_[r.id] = r
        return r

    async def create_role(self, *, name, reason=None, **_k):
        """« Créer le rôle » (les chefs d'équipe) : en bas de la liste, sans droits."""
        return self.role(name, 2)

    def membre(self, uid, nom, *roles):
        m = Membre(uid, nom, *roles)
        m.guild = self
        self.membres[uid] = m
        self.members.append(m)
        return m


class Inter:
    """Une interaction : la réponse (message, formulaire, acquittement), les suivis (pour soi)."""

    def __init__(self, banc, membre, salon=None):
        self.guild, self.user, self.channel = banc.g, membre, salon
        self.messages, self.modals, self.suivis, self.effaces = [], [], [], 0
        self.response = Obj(is_done=lambda: self._fait, send_message=self._repondre, send_modal=self._modal,
                            defer=self._defer, edit_message=self._editer)
        self._fait = False
        self.followup = Obj(send=self._suivre)
        self.locale = "fr"
        self.edits = []

    async def _repondre(self, content=None, **kw):
        self._fait = True
        self.messages.append(kw.get("view", content))

    async def _modal(self, modal):
        self._fait = True
        self.modals.append(modal)

    async def _defer(self, **_kw):
        self._fait = True

    async def _editer(self, **kw):
        self._fait = True
        self.edits.append(kw)

    async def _suivre(self, content=None, **kw):
        self.suivis.append(kw.get("view", content))

    async def delete_original_response(self):
        self.effaces += 1

    async def edit_original_response(self, **kw):
        self.edits.append(kw)

    def vues(self):
        return [v for v in self.messages + self.suivis if hasattr(v, "to_components")]


def espace_du_bot(*, g, get_db, cfg, db_set, porteur, categorie, journal, logs, erreurs, metiers, autorise,
                  fondateur: int = FONDATEUR) -> dict:
    """Les fonctions de bot.py du chemin d'un ticket de recrutement (NOMS_DU_BOT, NOMS_FACULTATIFS), lues dans sa source
    et exécutées avec des doublures : le salon porteur des fils, la catégorie, le webhook (un simple `send`), le journal
    (`journal`, `logs`), les erreurs (`erreurs`), le module des métiers (`metiers`). Sert au banc (les tests) et au site
    local (`outils/site_local_recrutement.py`) : un seul chemin, le vrai."""
    async def rien(*_a, **_k):
        return None

    async def vrai(*_a, **_k):
        return True

    async def heures(*_a, **_k):
        return True, ""

    async def gate(*_a, **_k):
        return ""

    async def zero(*_a, **_k):
        return 0

    async def categorie_(_g):
        return categorie

    async def parent(guild, cat, staff, parents, enregistrer, *, voient=(), groupe="", nom=""):
        return porteur

    async def ouvrir(parent_ch, membre, nom):
        fil = FilTicket(g, g.nouvel_id(), parent_ch, nom[:100])
        g.fils[fil.id] = fil
        await fil.add_user(membre)
        return fil

    async def webhook_send(ch, profil, embed=None, content=None, file=None, files=None, embeds=None, view=None,
                           allowed_mentions=None, cle=None):
        kw = {k: v for k, v in (("content", content), ("embed", embed), ("embeds", embeds), ("file", file),
                                ("files", files), ("view", view), ("allowed_mentions", allowed_mentions))
              if v is not None}
        return await ch.send(**kw)

    async def journal_clan(_g, texte, membre_id=0, auteur_id=0):
        journal.append(texte)

    async def log_staff(*a, **_k):
        logs.append(a)

    def logerr(ou, ex, **_k):
        erreurs.append((ou, f"{type(ex).__name__}: {ex}"))

    outils_fils = Obj(parent=parent, ouvrir=ouvrir, salon=tickets_fils_vrai.salon,
                      DROITS_SALON=tickets_fils_vrai.DROITS_SALON, CLE_PARENTS=tickets_fils_vrai.CLE_PARENTS,
                      ajouter=tickets_fils_vrai.ajouter)
    ns = {"discord": discord, "asyncio": _Asyncio(), "json": json, "time": time, "datetime": datetime,
          "timezone": timezone, "LayoutView": LayoutView, "Palette": Palette, "View": View, "visuels": visuels,
          "Button": discord.ui.Button, "questionnaire": Q, "recrutements": recrutements,
          "rellseas_ui": rellseas_panneau, "textes": textes_registre, "tickets_fils": outils_fils,
          "metiers": metiers, "cfg": cfg, "db_set": db_set,
          "get_db": get_db, "now": lambda: datetime.now(timezone.utc), "webhook_send": webhook_send,
          "send_ticket_log": vrai, "_ticket_hours_allows": heures, "check_rate_limit": lambda *a, **k: True,
          "_access_gate_reason": gate, "count_user_tickets": zero, "count_user_tickets_today": zero,
          "_categorie_tickets": categorie_, "SUPER_OWNER_ID": fondateur,
          "owner_ids_module": Obj(is_super_owner=lambda uid: uid == fondateur),
          "is_fully_immune": rien, "_logerr": logerr, "_journal_rellseas": journal_clan,
          "log_staff_action": log_staff, "_recent_transcript_urls": {}, "_ticket_transcript_html": rien,
          "_ticket_transcript_file": rien, "_ticket_feedback_view": lambda *a, **k: None,
          "tix_module": Obj(log_action=rien), "_au_journal": rien, "_rellseas_autorise": autorise,
          "RECOURS_MARQUE": "recours", "Modal": discord.ui.Modal, "TextInput": discord.ui.TextInput,
          "metiers_reel": None}
    for nom in NOMS_DU_BOT:
        exec(compile(source(nom), "bot.py", "exec"), ns)  # noqa: S102 — le code du dépôt (bot.py)
    for nom in NOMS_FACULTATIFS:
        if _noeud(nom) is not None:
            exec(compile(source(nom), "bot.py", "exec"), ns)  # noqa: S102
    return ns


class BancTicket:
    """Un serveur, une base, le chemin du bot pour un ticket de recrutement. `metier` : le guide du clan existe (la
    carte du choix du métier est posée à l'acceptation, comme en production)."""

    def __init__(self, tmp_path, *, metier: bool = True):
        self.chemin = tmp_path / "ticket.db"
        self.g = Serveur()
        self.direction_r = self.g.role("Direction", 60)
        self.recruteurs_r = self.g.role("Recruteurs", 40)
        self.clan_r = self.g.role("Rell Seas", 30)
        self.g.me = Obj(id=BOT, top_role=self.g.role("GoRP Bot", 80), display_name="GoRP",
                        guild_permissions=Obj(manage_roles=True, manage_channels=True, administrator=True),
                        mention=f"<@{BOT}>")
        self.fondateur = self.g.membre(FONDATEUR, "GoRipe", self.direction_r)
        self.direction = self.g.membre(DIRECTION, "Capitaine", self.direction_r)
        self.recruteur = self.g.membre(RECRUTEUR, "Vigie", self.recruteurs_r)
        self.candidat = self.g.membre(CANDIDAT, "Kolax")
        self.autre = self.g.membre(AUTRE, "Mira")
        self.porteur = self.g._salon(Texte, "🎫・tickets-rell-seas", {})
        self.categorie = self.g.categorie("🎫 TICKETS")
        self.conf = {
            "ticket_panels": {"p1": {"name": "Recrutement Rell Seas", "welcome_message": "Bienvenue à bord !",
                                     "questions": [{"title": "Pseudo Roblox", "question": "Ton pseudo exact"},
                                                   {"title": "Âge", "question": "Ta tranche d'âge"}],
                                     "max": 1},
                              "p2": {"name": "Support", "max": 1}},
            rellseas_panneau.CLE_ROLE_CIBLE: self.clan_r.id, "direction_allowed_role": self.direction_r.id,
            rellseas_panneau.CLE_ROLES_AUTORISES: [self.recruteurs_r.id], "tickets_fils": 1,
        }
        self.metier = metier
        self.erreurs, self.journal, self.logs = [], [], []
        self.ns = self._espace()

    # ─── La base ───
    @contextlib.asynccontextmanager
    async def get_db(self):
        db = await aiosqlite.connect(self.chemin)
        try:
            yield db
        finally:
            await db.close()

    async def preparer(self):
        async with self.get_db() as db:
            await db.execute("CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,"
                             " channel_id INTEGER, user_id INTEGER, panel_id TEXT, claimed_by INTEGER, status TEXT,"
                             " answers TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            await db.execute("CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id,"
                             " user_id, mod_id, type, reason)")
            #  Le suivi des recrutements tel qu'en production (recrutements.init_db).
            await db.execute("CREATE TABLE IF NOT EXISTS recrutements (guild_id INTEGER NOT NULL, ticket_id INTEGER NOT"
                             " NULL, candidat_id INTEGER NOT NULL, candidat_nom TEXT, ouvert_le INTEGER, ferme_le INTEGER"
                             " NOT NULL, ferme_par INTEGER, pris_par INTEGER, reponses TEXT, msg_candidat INTEGER DEFAULT"
                             " 0, msg_staff INTEGER DEFAULT 0, transcript TEXT, raison TEXT DEFAULT '', decision TEXT"
                             " DEFAULT '', PRIMARY KEY (guild_id, ticket_id))")
            await db.commit()
        await Q.init_db()

    async def cfg(self, _gid):
        return self.conf

    async def db_set(self, _gid, cle, valeur):
        self.conf[cle] = valeur
        return True

    # ─── Le bot, lu dans sa source ───
    def _espace(self) -> dict:
        banc = self

        async def inviter_au_choix(g, ch, membre):
            if not banc.metier or ch is None or membre is None:
                return None
            v = LayoutView(timeout=None)
            v.add_item(discord.ui.Container(discord.ui.TextDisplay(f"{membre.mention} choisis ton métier.")))
            await ch.send(view=v, allowed_mentions=discord.AllowedMentions.none())
            return "https://discord.com/channels/1/2/3"

        async def autorise(i):
            return i.user.id in (FONDATEUR, DIRECTION, RECRUTEUR)
        return espace_du_bot(g=self.g, get_db=self.get_db, cfg=self.cfg, db_set=self.db_set, porteur=self.porteur,
                             categorie=self.categorie, journal=self.journal, logs=self.logs, erreurs=self.erreurs,
                             metiers=Obj(inviter_au_choix=inviter_au_choix), autorise=autorise)

    def monter(self, **extra):
        """`questionnaire.setup` comme l'étape « questionnaire » du bot (ses branchements du 26/10/2026 compris)."""
        ns = self.ns
        kw = dict(get_db=self.get_db, cfg=self.cfg, panneaux=rellseas_panneau.panneaux_tickets,
                  ticket_ouvert=ns["_ticket_ouvert"], decider=ns["_decision_recrutement"], autorise=ns["_peut_decider"],
                  lien=self.lien, journal=self.noter, fichier_banque=EXEMPLE, fichier_liens=LIENS,
                  log=lambda *a: None)
        if "_recrutement_extras" in ns:
            async def metiers(_g):
                return [{"cle": "navigation", "nom": "Navigateur"}, {"cle": "cuisine", "nom": "Cuisinier"}]

            async def metiers_membre(_g, m):
                return ["navigation"] if getattr(m, "id", 0) == CANDIDAT else []

            async def invitation(g, membre):
                return (f"{membre.mention} choisis ton métier.", "https://discord.com/channels/1/2/3",
                        "Choisir mon métier") if self.metier else None
            kw.update(extras=ns["_recrutement_extras"], liste_noire=ns["_liste_noire_recrutement"],
                      est_tete=lambda m: getattr(m, "id", 0) in (FONDATEUR, DIRECTION), clan=ns["_role_clan_de"],
                      metiers=metiers, metiers_membre=metiers_membre, metier=invitation)
        kw.update(extra)
        Q.setup(**kw)

    async def lien(self, i):
        if i.user.id in (FONDATEUR, DIRECTION):
            return "https://bot.exemple/tableau/JETON", ""
        return None, "Réservé au fondateur et à la direction."

    async def noter(self, g, type_, texte, membre_id=0, auteur_id=0):
        self.journal.append((type_, texte))

    # ─── Les gestes ───
    async def ouvrir_ticket(self, membre=None, pid="p1", reponses=None):
        """Le chemin du bot : `create_ticket` (le formulaire d'ouverture déjà rempli), puis les tâches de fond (l'équipe
        qui entre dans le fil)."""
        membre = membre or self.candidat
        i = Inter(self, membre)
        ch, err = await self.ns["create_ticket"](i, pid, reponses if reponses is not None
                                                 else {"Pseudo Roblox": "Kolax_RS", "Âge": "16 – 17 ans"})
        assert err is None, err
        await laisser_finir()
        async with self.get_db() as db:
            async with db.execute("SELECT id FROM tickets WHERE channel_id=?", (ch.id,)) as cur:
                tid = (await cur.fetchone())[0]
        return int(tid), ch

    async def statut(self, tid):
        async with self.get_db() as db:
            async with db.execute("SELECT status FROM tickets WHERE id=?", (int(tid),)) as cur:
                return (await cur.fetchone())[0]
