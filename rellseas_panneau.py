"""L'onglet « Rellseas » de /configure — qui a le droit de s'en servir.

Demandé mot pour mot par le propriétaire (15/08/2026) :

    « Je veux que tu me la remettes. Et que moi, dans le slash configure, je
    peux configurer cette commande pour savoir qui va l'utiliser. Celui qui
    utilisera cette commande pourra donner un rôle ou retirer un rôle, ou
    vérifier l'activité de la personne. Le même système d'activité dans le
    serveur, sauf que ce sera sur une semaine au propre. »

⚠️ CE PANNEAU N'EST PAS UNE GARDE. Il règle qui a le droit ; c'est la commande
qui doit vérifier. Un panneau qui masque un bouton n'empêche personne de taper
la commande — la permission est contrôlée dans `/rellseas` elle-même
(`bot._rellseas_autorise`), et ce panneau n'en est que le réglage.

Ce qui existait déjà et n'a pas été réécrit : la table `realsy_tracking`,
`update_realsy_activity`, la table `rellseas_quizzes` et les deux vues de
questionnaire, toutes intactes. Seuls manquaient la commande et son réglage.
"""
from __future__ import annotations

import discord
from discord.ui import Button, ChannelSelect, RoleSelect, UserSelect

from ui_v2 import (
    LayoutView, Palette, body as v2_body, container as v2_container,
    divider as v2_divider, subtitle as v2_subtitle, title as v2_title,
)

_cfg = None
_db_set = None
_log = print
#  Injectés par bot.py — le module ne connaît ni la base ni le système
#  d'activité, il ne fait que les appeler.
_mesurer = None        # (guild_id, member) -> dict, via activite.presence()
_marquer_suivi = None  # (guild_id, user_id) -> None, écrit realsy_tracking

#  La clé qui portait le réglage manquant. Les trois autres existaient déjà et
#  sont écrites par les vues de questionnaire — on les affiche, on ne les
#  invente pas.
CLE_ROLES_AUTORISES = "rellseas_roles_autorises"
CLE_ROLE_CIBLE = "rellseas_role"
CLE_SALON_LOG = "rellseas_log_channel"

#  ⚠️ PLUSIEURS RÔLES, PAS UN SEUL. Demande explicite du propriétaire :
#  « on peut être plusieurs à pouvoir utiliser cette commande ». 25 est la
#  limite dure de Discord sur un select — on prend tout ce qui est permis.
#  Le reste du bot passe par `check_mod_perm`, qui ne lit QU'UN rôle ; c'est
#  probablement de là que venait le doute. Ici, la garde lit une LISTE.
MAX_ROLES = 25

#  Limite dure de Discord sur un `UserSelect`. C'est aussi la taille d'un lot :
#  au-delà, on enchaîne les lots, on ne perd personne.
MAX_MEMBRES = 25


def setup(*, cfg, db_set, get_db=None, mesurer=None, marquer_suivi=None, log=None):
    global _cfg, _db_set, _log, _mesurer, _marquer_suivi
    _cfg, _db_set = cfg, db_set
    _mesurer = mesurer
    _marquer_suivi = marquer_suivi
    if log is not None:
        _log = log


_retour_configure = None


def set_retour(fn):
    global _retour_configure
    _retour_configure = fn


def roles_autorises(c: dict) -> list[int]:
    """Les rôles ayant droit à `/rellseas`, lus depuis la config.

    Tolère la valeur absente, une chaîne, une liste d'entiers ou de chaînes :
    la config est un JSON libre, et un réglage écrit par une version
    antérieure ne doit pas faire planter la garde. Tout ce qui n'est pas un
    identifiant lisible est ignoré — fail-closed, on n'autorise jamais par
    accident.
    """
    brut = c.get(CLE_ROLES_AUTORISES) or []
    if isinstance(brut, (str, int)):
        brut = [brut]
    out = []
    for v in brut:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(n)
    return out


class RellseasPanelV2(LayoutView):
    """Règle qui peut utiliser `/rellseas`, et sur quel rôle elle agit.

    Ouvert par le propriétaire du serveur depuis `/configure`.
    """

    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self._dernier = ""

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def render_to(self, i, *, edit: bool = True):
        try:
            #  Fail-open sur la disponibilité : une erreur de base ne doit
            #  jamais empêcher le panneau de s'ouvrir (UI.md §6).
            try:
                c = await _cfg(self.g.id)
            except Exception as ex:
                _log(f"[RellseasPanelV2 cfg] {ex}")
                c = {}

            role_cible = self.g.get_role(int(c.get(CLE_ROLE_CIBLE, 0) or 0))
            salon_log = self.g.get_channel(int(c.get(CLE_SALON_LOG, 0) or 0))
            autorises = roles_autorises(c)
            noms = []
            for rid in autorises:
                r = self.g.get_role(rid)
                #  Un rôle supprimé depuis le réglage doit se VOIR : sinon la
                #  liste paraît plus fournie qu'elle ne l'est.
                noms.append(r.mention if r else f"`{rid}` ⚠️ _rôle supprimé_")

            items = [
                v2_title("🎭 Rellseas"),
                v2_subtitle("Qui peut donner, retirer, et vérifier l'activité"),
                v2_divider(),
                v2_body(
                    f"**Rôle attribué** · "
                    f"{role_cible.mention if role_cible else '⚪ _non défini_'}\n"
                    f"-# C'est le rôle que `/rellseas donner` et "
                    f"`/rellseas retirer` posent et enlèvent."),
                v2_body(
                    f"**Salon de journal** · "
                    f"{salon_log.mention if salon_log else '⚪ _non défini_'}\n"
                    f"-# Chaque geste y laisse une trace nominative."),
                v2_divider(),
                v2_body(
                    "**Rôles autorisés à utiliser `/rellseas`**\n"
                    + (" · ".join(noms) if noms
                       else "⚪ _aucun_ — seuls les administrateurs et le "
                            "propriétaire du serveur peuvent s'en servir")),
                v2_body(
                    "-# Les administrateurs et le propriétaire y ont **toujours** "
                    "droit, réglage ou pas. Le contrôle est fait dans la commande, "
                    "pas seulement à l'affichage."),
            ]

            if self._dernier:
                items.append(v2_divider())
                items.append(v2_body(self._dernier))

            sel_roles = RoleSelect(
                placeholder=f"Rôles autorisés — plusieurs possibles ({MAX_ROLES} max)…",
                min_values=0, max_values=MAX_ROLES,
                custom_id="rellseas_roles_ok")
            sel_roles.callback = self._cb_roles

            sel_cible = RoleSelect(
                placeholder="Rôle attribué par la commande…",
                min_values=1, max_values=1, custom_id="rellseas_role_cible")
            sel_cible.callback = self._faire_cle(CLE_ROLE_CIBLE, "Rôle attribué")

            sel_log = ChannelSelect(
                channel_types=[discord.ChannelType.text],
                placeholder="Salon de journal…",
                min_values=1, max_values=1, custom_id="rellseas_log")
            sel_log.callback = self._faire_cle(CLE_SALON_LOG, "Salon de journal")

            b_back = Button(label="Retour", emoji="◀️",
                            style=discord.ButtonStyle.secondary,
                            custom_id="rellseas_back")
            b_back.callback = self._cb_retour

            items += [
                v2_divider(),
                discord.ui.ActionRow(sel_roles),
                discord.ui.ActionRow(sel_cible),
                discord.ui.ActionRow(sel_log),
                discord.ui.ActionRow(b_back),
            ]

            self.clear_items()
            self.add_item(v2_container(*items, color=Palette.INFO))

            if edit:
                if i.response.is_done():
                    await i.edit_original_response(content=None, view=self,
                                                   embed=None, attachments=[])
                else:
                    await i.response.edit_message(content=None, view=self,
                                                  embed=None, attachments=[])
            else:
                await i.response.send_message(view=self, ephemeral=True)
        except Exception as ex:
            _log(f"[RellseasPanelV2] {ex}")
            try:
                msg = f"❌ Erreur : `{type(ex).__name__}`"
                if not i.response.is_done():
                    await i.response.send_message(msg, ephemeral=True)
                else:
                    await i.followup.send(msg, ephemeral=True)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Callbacks
    # ─────────────────────────────────────────────────────────────────────────

    async def _cb_roles(self, i):
        """Enregistre la liste des rôles autorisés.

        `min_values=0` : vider la liste est un réglage légitime — il ramène la
        commande aux seuls administrateurs.
        """
        try:
            ids = [int(v) for v in (i.data.get("values") or [])]
            await _db_set(self.g.id, CLE_ROLES_AUTORISES, ids)
            self._dernier = (
                f"✅ `{len(ids)}` rôle(s) autorisé(s)." if ids
                else "✅ Liste vidée — `/rellseas` redevient réservée aux "
                     "administrateurs et au propriétaire.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[rellseas roles] {ex}")

    def _faire_cle(self, cle: str, libelle: str):
        async def _cb(i):
            try:
                await _db_set(self.g.id, cle, int(i.data["values"][0]))
                self._dernier = f"✅ {libelle} enregistré."
                await self.render_to(i, edit=True)
            except Exception as ex:
                _log(f"[rellseas {cle}] {ex}")
        return _cb

    async def _cb_retour(self, i):
        try:
            if _retour_configure is not None:
                return await _retour_configure(self.u, self.g, i)
            await i.response.defer()
        except Exception as ex:
            _log(f"[rellseas retour] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  LE PANNEAU DE GESTION — ce qu'ouvre `/rellseas`
# ═══════════════════════════════════════════════════════════════════════════════
#  Demandé le 16/08/2026, en remplacement des sous-commandes `donner` /
#  `retirer` :
#
#      « Je veux que l'utilisateur utilise la commande officielle, et qu'à
#      l'intérieur il y ait un panneau, et ce panneau lui permet de donner, de
#      retirer des rôles efficacement et rapidement. Il peut en donner à
#      plusieurs personnes d'un coup. Retirer à plusieurs personnes d'un seul
#      coup. Il a son propre panneau de gestion très professionnel et propre. »
#
#  UNE commande, UN panneau, des lots. Le choix des membres se fait par
#  `UserSelect` natif — jamais « colle les identifiants » (UI.md §1).

def _bilan(titre: str, faits: list[str], echecs: list[str]) -> str:
    """Le compte-rendu d'un lot. Il dit ce qui est FAIT et ce qui ne l'est pas.

    ⚠️ RÈGLE DE CE DÉPÔT — ON N'ANNONCE JAMAIS UN GESTE QUE DISCORD A REFUSÉ.
    C'est ce défaut précis qui avait fait retirer l'ancienne escalade Realsy :
    son message privé annonçait un retrait de rôle que le bot ne faisait pas.
    Un lot rend donc DEUX listes, et la seconde n'est jamais masquée.
    """
    lignes = [titre]
    if faits:
        lignes.append(f"✅ `{len(faits)}` — " + " ".join(faits))
    if echecs:
        lignes.append(f"❌ `{len(echecs)}` — non traité(s) :")
        lignes.extend(f"-# • {e}" for e in echecs)
    if not faits and not echecs:
        lignes.append("⚪ Rien à faire.")
    return "\n".join(lignes)


class RellseasGestionV2(LayoutView):
    """Le panneau de `/rellseas` : donner et retirer le rôle, par lots.

    Ouvert par quiconque porte un des rôles autorisés (ou par un
    administrateur). Éphémère : chacun ouvre le sien, et plusieurs personnes
    peuvent donc s'en servir en même temps sans se marcher dessus.
    """

    def __init__(self, u, g, *, autorise=None):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        #  ⚠️ LA GARDE EST REVÉRIFIÉE À CHAQUE CLIC, pas seulement à
        #  l'ouverture. Un panneau vit 10 minutes ; un droit peut être retiré
        #  entre-temps, et une vue ouverte ne doit pas devenir un laissez-passer.
        self._autorise = autorise
        self._membres: list[int] = []
        self._dernier = ""

    async def interaction_check(self, i):
        if i.user.id != self.u.id:
            return False
        if self._autorise is None:
            return True
        try:
            if await self._autorise(i):
                return True
        except Exception as ex:
            _log(f"[RellseasGestionV2 garde] {ex}")
        #  Fail-closed, et on le DIT : un bouton qui ne fait rien sans expliquer
        #  est un bouton qui ment.
        try:
            await i.response.send_message(
                "❌ Votre permission d'utiliser `/rellseas` a été retirée "
                "depuis l'ouverture de ce panneau.", ephemeral=True)
        except Exception:
            pass
        return False

    # ─────────────────────────────────────────────────────────────────────────
    #  Construction
    # ─────────────────────────────────────────────────────────────────────────

    async def render_to(self, i, *, edit: bool = True):
        try:
            try:
                c = await _cfg(self.g.id)
            except Exception as ex:
                _log(f"[RellseasGestionV2 cfg] {ex}")
                c = {}

            role = self.g.get_role(int(c.get(CLE_ROLE_CIBLE, 0) or 0))
            choisis = [self.g.get_member(m) for m in self._membres]
            choisis = [m for m in choisis if m is not None]

            items = [
                v2_title("🎭 Rellseas"),
                v2_subtitle("Donner, retirer, examiner — par lots"),
                v2_divider(),
            ]

            if role is None:
                #  Sans rôle cible, deux boutons sur trois n'ont aucun sens :
                #  on le dit franchement plutôt que de les laisser échouer.
                items.append(v2_body(
                    "🔴 **Aucun rôle Rellseas n'est réglé.**\n"
                    "-# `/configure` → 🎭 Rellseas → « Rôle attribué ». "
                    "Tant qu'il manque, donner et retirer sont impossibles."))
            else:
                porteurs = len(getattr(role, "members", []) or [])
                items.append(v2_body(
                    f"**Rôle géré** · {role.mention}\n"
                    f"-# `{porteurs}` membre(s) le portent actuellement."))

            items.append(v2_divider())

            if choisis:
                #  Qui est sélectionné, et qui a déjà le rôle : c'est ce qui
                #  rend l'action prévisible avant le clic.
                lignes = []
                for m in choisis[:MAX_MEMBRES]:
                    marque = "🟢" if (role and role in m.roles) else "⚪"
                    lignes.append(f"{marque} {m.mention}")
                items.append(v2_body(
                    f"**Sélection · `{len(choisis)}` membre(s)**\n"
                    + " ".join(lignes)
                    + "\n-# 🟢 porte déjà le rôle · ⚪ ne l'a pas"))
            else:
                items.append(v2_body(
                    "**Sélection** · ⚪ _aucun membre_\n"
                    "-# Choisissez jusqu'à "
                    f"`{MAX_MEMBRES}` membres ci-dessous, puis agissez."))

            if self._dernier:
                items.append(v2_divider())
                items.append(v2_body(self._dernier))

            sel = UserSelect(
                placeholder=f"Choisir des membres ({MAX_MEMBRES} max)…",
                min_values=0, max_values=MAX_MEMBRES,
                custom_id="rellseas_membres")
            sel.callback = self._cb_membres

            #  Un bouton sans effet possible est `disabled`, pas absent :
            #  l'utilisateur doit comprendre POURQUOI il ne peut pas cliquer
            #  (UI.md §3).
            pret = bool(choisis) and role is not None
            b_donner = Button(label="Donner le rôle", emoji="✅",
                              style=discord.ButtonStyle.success,
                              disabled=not pret, custom_id="rellseas_g_donner")
            b_donner.callback = self._cb_donner

            b_retirer = Button(label="Retirer le rôle", emoji="🚫",
                               style=discord.ButtonStyle.danger,
                               disabled=not pret, custom_id="rellseas_g_retirer")
            b_retirer.callback = self._cb_retirer

            b_activite = Button(label="Vérifier l'activité", emoji="📊",
                                style=discord.ButtonStyle.primary,
                                disabled=not choisis,
                                custom_id="rellseas_g_activite")
            b_activite.callback = self._cb_activite

            b_vider = Button(label="Vider la sélection", emoji="🧹",
                             style=discord.ButtonStyle.secondary,
                             disabled=not choisis, custom_id="rellseas_g_vider")
            b_vider.callback = self._cb_vider

            items += [
                v2_divider(),
                discord.ui.ActionRow(sel),
                discord.ui.ActionRow(b_donner, b_retirer, b_activite, b_vider),
            ]

            self.clear_items()
            self.add_item(v2_container(*items, color=Palette.INFO))

            if edit:
                if i.response.is_done():
                    await i.edit_original_response(content=None, view=self,
                                                   embed=None, attachments=[])
                else:
                    await i.response.edit_message(content=None, view=self,
                                                  embed=None, attachments=[])
            else:
                await i.response.send_message(view=self, ephemeral=True)
        except Exception as ex:
            _log(f"[RellseasGestionV2] {ex}")
            try:
                msg = f"❌ Erreur : `{type(ex).__name__}`"
                if not i.response.is_done():
                    await i.response.send_message(msg, ephemeral=True)
                else:
                    await i.followup.send(msg, ephemeral=True)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Callbacks
    # ─────────────────────────────────────────────────────────────────────────

    async def _cb_membres(self, i):
        try:
            self._membres = [int(v) for v in (i.data.get("values") or [])]
            self._dernier = ""
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[rellseas gestion membres] {ex}")

    async def _cb_vider(self, i):
        try:
            self._membres = []
            self._dernier = ""
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[rellseas gestion vider] {ex}")

    async def _role_utilisable(self, c: dict):
        """Le rôle cible, et si le bot peut réellement le manipuler.

        Rendre `(role, raison)` : `raison` non vide = on ne tente RIEN. Vérifier
        AVANT le lot évite 25 refus identiques et un compte-rendu illisible.
        """
        role = self.g.get_role(int(c.get(CLE_ROLE_CIBLE, 0) or 0))
        if role is None:
            return None, ("Aucun rôle Rellseas réglé — `/configure` → "
                          "🎭 Rellseas.")
        moi = self.g.me
        if moi is None:
            return role, "Je ne me vois pas sur ce serveur."
        if not moi.guild_permissions.manage_roles:
            return role, "Il me manque la permission « Gérer les rôles »."
        if role >= moi.top_role:
            return role, (f"{role.mention} est au-dessus de mon rôle le plus "
                          f"haut : Discord m'interdit d'y toucher.")
        return role, ""

    async def _agir(self, i, donner: bool):
        """Le lot. Une seule mécanique pour donner et pour retirer."""
        await i.response.defer()
        try:
            c = await _cfg(self.g.id)
        except Exception as ex:
            _log(f"[rellseas agir cfg] {ex}")
            c = {}

        role, raison = await self._role_utilisable(c)
        if raison:
            self._dernier = f"🔴 **Rien n'a été fait.** {raison}"
            return await self.render_to(i, edit=True)

        faits, echecs = [], []
        for uid in self._membres:
            m = self.g.get_member(uid)
            if m is None:
                echecs.append(f"`{uid}` — membre introuvable (parti ?)")
                continue
            a_le_role = role in m.roles
            if donner and a_le_role:
                echecs.append(f"{m.mention} — l'avait déjà")
                continue
            if not donner and not a_le_role:
                echecs.append(f"{m.mention} — ne l'avait pas")
                continue
            try:
                geste = m.add_roles if donner else m.remove_roles
                await geste(role, reason=f"/rellseas par {self.u} ({self.u.id})")
            except discord.Forbidden:
                echecs.append(f"{m.mention} — refusé par Discord (hiérarchie)")
                continue
            except Exception as ex:
                _log(f"[rellseas agir {uid}] {ex}")
                echecs.append(f"{m.mention} — `{type(ex).__name__}`")
                continue
            faits.append(m.mention)
            if donner and _marquer_suivi is not None:
                #  Le suivi d'activité démarre à l'attribution : sans ça,
                #  `last_activity` reste vide et le membre paraît inactif
                #  dès le lendemain.
                try:
                    await _marquer_suivi(self.g.id, m.id)
                except Exception as ex:
                    _log(f"[rellseas suivi {uid}] {ex}")

        verbe = "donné" if donner else "retiré"
        self._dernier = _bilan(f"**Rôle {verbe}** · {role.mention}", faits, echecs)
        await self._journal(
            f"🎭 **Rôle {verbe}** · `{len(faits)}` membre(s) "
            f"par {self.u.mention}"
            + (f" — {' '.join(faits)}" if faits else ""))
        #  La sélection est conservée : enchaîner « donner » puis « vérifier »
        #  sur le même lot est le geste courant.
        await self.render_to(i, edit=True)

    async def _cb_donner(self, i):
        try:
            await self._agir(i, donner=True)
        except Exception as ex:
            _log(f"[rellseas donner] {ex}")

    async def _cb_retirer(self, i):
        try:
            await self._agir(i, donner=False)
        except Exception as ex:
            _log(f"[rellseas retirer] {ex}")

    async def _cb_activite(self, i):
        """L'activité de tout le lot, mesurée par le système d'activité.

        ⚠️ AUCUN COMPTEUR ICI. `_mesurer` appelle `activite.presence()` sur une
        fenêtre d'une semaine. Un second compteur avait déjà été écrit puis
        retiré le 12/08 : il faisait doublon et mentait.
        """
        try:
            await i.response.defer()
            if _mesurer is None:
                self._dernier = "🔴 La mesure d'activité n'est pas branchée."
                return await self.render_to(i, edit=True)

            lignes = []
            for uid in self._membres:
                m = self.g.get_member(uid)
                if m is None:
                    lignes.append(f"❔ `{uid}` — membre introuvable")
                    continue
                try:
                    mes = await _mesurer(self.g.id, m)
                except Exception as ex:
                    _log(f"[rellseas activite {uid}] {ex}")
                    lignes.append(f"❔ {m.mention} — mesure impossible")
                    continue
                lignes.append(f"{_etiquette_activite(mes)} {m.mention}")

            self._dernier = (
                "**Activité sur les 7 derniers jours**\n" + "\n".join(lignes)
                + "\n-# 🟢 actif · 🟠 peu présent · 🔴 absent · ⚪ pas assez de "
                  "recul pour juger\n"
                  "-# Mesuré par le système d'activité du serveur — aucun "
                  "compteur séparé.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[rellseas activite] {ex}")

    async def _journal(self, texte: str) -> None:
        """Trace nominative. Fail-open : jamais bloquant."""
        try:
            c = await _cfg(self.g.id)
            salon = self.g.get_channel(int(c.get(CLE_SALON_LOG, 0) or 0))
            if salon is not None:
                await salon.send(texte)
        except Exception as ex:
            _log(f"[rellseas journal] {ex}")


def _etiquette_activite(mes: dict) -> str:
    """Une mesure → une pastille et son chiffre. FONCTION PURE, donc testable.

    « Pas encore jugeable » n'est PAS « absent » : reprocher une absence sur
    des journées qu'on n'a pas observées serait un verdict fabriqué.
    """
    presents = mes.get("presents", 0)
    fenetre = mes.get("fenetre", 7)
    if not mes.get("jugeable"):
        return f"⚪ `{mes.get('observables', 0)}j observés` —"
    if mes.get("silence") is None:
        return "⚪ `jamais vu` —"
    if presents == 0:
        return f"🔴 `0/{fenetre}` —"
    if presents <= 2:
        return f"🟠 `{presents}/{fenetre}` —"
    return f"🟢 `{presents}/{fenetre}` —"
