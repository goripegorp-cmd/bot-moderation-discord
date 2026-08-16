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
from discord.ui import Button, ChannelSelect, RoleSelect

from ui_v2 import (
    LayoutView, Palette, body as v2_body, container as v2_container,
    divider as v2_divider, subtitle as v2_subtitle, title as v2_title,
)

_cfg = None
_db_set = None
_log = print

#  La clé qui portait le réglage manquant. Les trois autres existaient déjà et
#  sont écrites par les vues de questionnaire — on les affiche, on ne les
#  invente pas.
CLE_ROLES_AUTORISES = "rellseas_roles_autorises"
CLE_ROLE_CIBLE = "rellseas_role"
CLE_SALON_LOG = "rellseas_log_channel"

#  Discord refuse au-delà de 25 valeurs sur un select. On borne à 10 : au-delà,
#  « quels rôles ont le droit » n'est plus un réglage, c'est une passoire.
MAX_ROLES = 10


def setup(*, cfg, db_set, log=None):
    global _cfg, _db_set, _log
    _cfg, _db_set = cfg, db_set
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
                placeholder=f"Rôles autorisés à utiliser /rellseas ({MAX_ROLES} max)…",
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
