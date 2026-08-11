"""activite_panneau.py — Le panneau de configuration du système d'activité.

Components V2 de bout en bout, conformément à `UI.md` : aucun embed, aucune
réaction, aucune commande à taper. Selects natifs typés (`RoleSelect`,
`ChannelSelect`) — jamais « colle l'identifiant du salon ». Toggles portés par le
label ET le style du bouton. Réponses éphémères. Bouton « Retour » partout.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURE
═══════════════════════════════════════════════════════════════════════════════
  ActivitePanelV2            racine : interrupteur, état, accès aux sections
   ├── ActiviteCiblesPanelV2   qui est surveillé (rôles, ou tout le monde)
   │    └── ActiviteRoleSeuilsPanelV2   seuils PROPRES à un rôle
   ├── ActiviteSalonsPanelV2   annonce · retour · staff
   ├── ActiviteRecompensesPanelV2  niveaux et VIP
   └── ActiviteApercuPanelV2   aperçu à blanc + validation des expulsions

Chaque panneau lit son état à l'ouverture (`render_to`) et n'écrit qu'au clic.
Le module ne connaît pas `bot.py` : tout ce dont il a besoin lui est injecté par
`setup()`, ce qui le rend testable et évite l'import circulaire.
"""
from __future__ import annotations

import discord
from discord.ui import Button, ChannelSelect, RoleSelect, Select, UserSelect

import activite
import activite_escalade as esc
import activite_passage as passage
import activite_recompenses as rec
from ui_v2 import (
    LayoutView, Palette, body as v2_body, container as v2_container,
    divider as v2_divider, subtitle as v2_subtitle, title as v2_title,
)

_db_set = None
_log = print

JOURS_SEMAINE = ["Lundi", "Mardi", "Mercredi", "Jeudi",
                 "Vendredi", "Samedi", "Dimanche"]


def setup(*, db_set, log=None):
    global _db_set, _log
    _db_set = db_set
    if log is not None:
        _log = log


def _pastille(actif: bool) -> str:
    return "🟢" if actif else "⚪"


def _bouton_retour(callback, cid: str) -> Button:
    b = Button(label="Retour", emoji="◀️",
               style=discord.ButtonStyle.secondary, custom_id=cid)
    b.callback = callback
    return b


class _Base(LayoutView):
    """Ossature commune : propriétaire du panneau, garde d'interaction, secours."""

    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def _secours(self, i, ex, ou: str):
        _log(f"[activite_panneau {ou}] {ex}")
        try:
            msg = f"❌ Erreur : `{type(ex).__name__}`"
            if not i.response.is_done():
                await i.response.send_message(msg, ephemeral=True)
            else:
                await i.followup.send(msg, ephemeral=True)
        except Exception:
            pass

    async def _envoyer(self, i, items, couleur, edit: bool):
        self.clear_items()
        self.add_item(v2_container(*items, color=couleur))
        if edit:
            await i.response.edit_message(content=None, view=self,
                                          embed=None, attachments=[])
        else:
            await i.response.send_message(view=self, ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  RACINE
# ═══════════════════════════════════════════════════════════════════════════════

class ActivitePanelV2(_Base):
    """Racine du système d'activité. Ouvert depuis /configure."""

    async def render_to(self, i, *, edit: bool = True):
        try:
            c = await activite.config(self.g.id)
            cr = await rec.config(self.g.id)
            en_marche = await activite.actif(self.g.id)

            roles = await activite.roles_surveilles(self.g, c)
            nb_disp = (len(c.get("activite_roles_immunises") or [])
                       + len(c.get("activite_membres_immunises") or []))
            if c["activite_tout_le_monde"]:
                cible = "**tout le serveur**"
                if roles:
                    cible += f" · `{len(roles)}` rôle(s) avec des réglages à part"
            elif roles:
                cible = ", ".join(r.mention for r in roles[:5])
            else:
                cible = "⚠️ _aucune cible_"
            an = self.g.get_channel(int(c["activite_salon_annonce"] or 0))
            ret = self.g.get_channel(int(c["activite_salon_retour"] or 0))
            st = self.g.get_channel(int(c["activite_salon_staff"] or 0))
            vip = self.g.get_role(int(cr["activite_vip_role"] or 0))

            items = [
                v2_title("📊 Système d'activité"),
                v2_subtitle("Un message · un passage en vocal · une réaction — "
                            "une seule suffit pour la journée"),
                v2_divider(),
                v2_body(
                    f"{_pastille(c['activite_enabled'])} **Système** · "
                    f"{'allumé' if c['activite_enabled'] else 'éteint'}"
                    f"{'' if en_marche or not c['activite_enabled'] else '  ⚠️ _sans cible, rien ne tourne_'}\n"
                    f"🎯 **Surveillé** · {cible}\n"
                    f"📅 **Rappel** · {JOURS_SEMAINE[int(c['activite_jour_rappel'] or 0) % 7]}"
                ),
                v2_body(
                    f"📢 **Annonce** · {an.mention if an else '⚪ _non défini_'}\n"
                    f"🔙 **Retour** · {ret.mention if ret else '⚪ _non défini_'}\n"
                    f"🛡️ **Staff** · {st.mention if st else '⚪ _non défini_'}"
                ),
                v2_body(
                    f"{_pastille(cr['activite_recompenses_enabled'])} **Récompenses** · "
                    f"niveaux {'actifs' if cr['activite_recompenses_enabled'] else 'éteints'}"
                    f" · VIP {vip.mention if vip else '⚪ _aucun rôle_'}"
                ),
                v2_divider(),
                v2_body(
                    "**Ce qui se passe, par rôle et selon vos seuils :**\n"
                    "1️⃣ rappel public — le membre garde tout\n"
                    "2️⃣ rappel + **retrait du rôle**, rendu automatiquement au retour\n"
                    "3️⃣ **proposé à l'expulsion** — jamais automatique, vous validez"
                ),
                v2_divider(),
            ]

            b_on = Button(
                label="Allumé" if c["activite_enabled"] else "Éteint",
                emoji="🟢" if c["activite_enabled"] else "⚪",
                style=(discord.ButtonStyle.success if c["activite_enabled"]
                       else discord.ButtonStyle.secondary),
                custom_id="act_toggle")
            b_on.callback = self._cb_toggle

            b_cibles = Button(label="Qui est surveillé", emoji="🎯",
                              style=discord.ButtonStyle.primary, custom_id="act_cibles")
            b_cibles.callback = self._cb_cibles
            b_salons = Button(label="Salons", emoji="📢",
                              style=discord.ButtonStyle.primary, custom_id="act_salons")
            b_salons.callback = self._cb_salons
            b_rec = Button(label="Récompenses", emoji="🏅",
                           style=discord.ButtonStyle.primary, custom_id="act_rec")
            b_rec.callback = self._cb_rec
            b_ap = Button(label="Aperçu & expulsions", emoji="🔎",
                          style=discord.ButtonStyle.secondary, custom_id="act_apercu")
            b_ap.callback = self._cb_apercu
            b_disp = Button(label="Dispenses", emoji="🛡️",
                            style=discord.ButtonStyle.secondary, custom_id="act_disp")
            b_disp.callback = self._cb_dispenses

            items.append(discord.ui.ActionRow(b_on, b_cibles, b_salons, b_rec))
            items.append(discord.ui.ActionRow(
                b_ap, b_disp, _bouton_retour(self._cb_retour, "act_back")))
            await self._envoyer(i, items, Palette.INFO, edit)
        except Exception as ex:
            await self._secours(i, ex, "racine")

    async def _cb_toggle(self, i):
        try:
            c = await activite.config(self.g.id)
            await _db_set(self.g.id, "activite_enabled", not c["activite_enabled"])
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "toggle")

    async def _cb_cibles(self, i):
        await ActiviteCiblesPanelV2(self.u, self.g).render_to(i, edit=True)

    async def _cb_salons(self, i):
        await ActiviteSalonsPanelV2(self.u, self.g).render_to(i, edit=True)

    async def _cb_rec(self, i):
        await ActiviteRecompensesPanelV2(self.u, self.g).render_to(i, edit=True)

    async def _cb_apercu(self, i):
        await ActiviteApercuPanelV2(self.u, self.g).render_to(i, edit=True)

    async def _cb_dispenses(self, i):
        await ActiviteDispensesPanelV2(self.u, self.g).render_to(i, edit=True)

    async def _cb_retour(self, i):
        #  Injecté par bot.py pour éviter l'import circulaire avec MainPanelV2.
        if _retour_configure is not None:
            await _retour_configure(self.u, self.g, i)
        else:
            await i.response.defer()


#  Rempli par bot.py au câblage : `async fn(u, g, interaction)`.
_retour_configure = None


def set_retour(fn):
    global _retour_configure
    _retour_configure = fn


# ═══════════════════════════════════════════════════════════════════════════════
#  CIBLES — qui est surveillé
# ═══════════════════════════════════════════════════════════════════════════════

class ActiviteCiblesPanelV2(_Base):
    """Rôles surveillés, ou tout le serveur. Chaque rôle a ses propres seuils."""

    async def render_to(self, i, *, edit: bool = True):
        try:
            c = await activite.config(self.g.id)
            roles = await activite.roles_surveilles(self.g, c)
            tout = bool(c["activite_tout_le_monde"])

            if tout:
                detail = ("**Tout le serveur est surveillé.** Les seuils par défaut "
                          f"s'appliquent : rappel à `{activite.SEUIL_RAPPEL_DEFAUT}` j, "
                          f"retrait à `{activite.SEUIL_RETRAIT_DEFAUT}` j, "
                          f"expulsion proposée à `{activite.SEUIL_EXPULSION_DEFAUT}` j.")
            elif roles:
                lignes = []
                for r in roles:
                    cf = activite.config_du_role(c, r.id)
                    salon = self.g.get_channel(cf["salon_annonce"])
                    etat = "" if cf["actif"] else "  ⏸️ _suspendu_"
                    lignes.append(
                        f"{_pastille(cf['actif'])} {r.mention} — "
                        f"`{cf['rappel']}`/`{cf['retrait']}`/`{cf['expulsion']}` j · "
                        f"{JOURS_SEMAINE[cf['jour_rappel'] % 7][:3]} · "
                        f"{salon.mention if salon else '⚪'}{etat}")
                detail = "\n".join(lignes)
            else:
                detail = ("⚠️ **Aucune cible.** Le système ne surveillera personne, "
                          "même allumé. Choisissez un rôle ci-dessous, ou activez "
                          "« tout le serveur ».")

            items = [
                v2_title("🎯 Qui est surveillé"),
                v2_subtitle("Les trois nombres sont : rappel / retrait du rôle / expulsion"),
                v2_divider(),
                v2_body(detail),
                v2_divider(),
                v2_body("-# Choisir un rôle déjà surveillé le RETIRE de la liste."),
            ]

            sel = RoleSelect(placeholder="Ajouter ou retirer un rôle surveillé…",
                             min_values=1, max_values=1, custom_id="act_role_sel")
            sel.callback = self._cb_role

            b_tout = Button(
                label="Tout le serveur",
                emoji="🟢" if tout else "⚪",
                style=discord.ButtonStyle.success if tout else discord.ButtonStyle.secondary,
                custom_id="act_tout")
            b_tout.callback = self._cb_tout

            items.append(discord.ui.ActionRow(sel))

            #  ⚠️ Un SELECT, pas des boutons. Discord plafonne à 5 boutons par
            #  ligne : le panneau ne pouvait donc proposer que 3 rôles, et les
            #  suivants devenaient inconfigurables. Un menu en accepte 25, et
            #  chaque entrée ouvre la configuration COMPLÈTE du rôle.
            entrees = []
            if tout:
                entrees.append(discord.SelectOption(
                    label="Tout le serveur", value=activite.ROLE_TOUS, emoji="🌍",
                    description="Les membres sans rôle surveillé"))
            for r in roles[:24]:
                cf = activite.config_du_role(c, r.id)
                entrees.append(discord.SelectOption(
                    label=r.name[:90], value=str(r.id),
                    emoji="🟢" if cf["actif"] else "⚪",
                    description=(f"{cf['rappel']}/{cf['retrait']}/{cf['expulsion']} j"
                                 f" · {JOURS_SEMAINE[cf['jour_rappel'] % 7]}")[:100]))
            if entrees:
                sel_conf = Select(placeholder="Configurer un rôle en détail…",
                                  options=entrees, custom_id="act_role_conf")
                sel_conf.callback = self._cb_configurer
                items.append(discord.ui.ActionRow(sel_conf))
            if len(roles) > 24:
                items.append(v2_body(
                    f"-# ⚠️ {len(roles) - 24} rôle(s) au-delà du 25e ne peuvent pas "
                    f"être listés : Discord plafonne les menus à 25 entrées."))

            items.append(discord.ui.ActionRow(b_tout))
            items.append(discord.ui.ActionRow(_bouton_retour(self._cb_retour, "act_cib_back")))
            await self._envoyer(i, items, Palette.INFO, edit)
        except Exception as ex:
            await self._secours(i, ex, "cibles")

    async def _cb_role(self, i):
        try:
            rid = str(int(i.data["values"][0]))
            c = await activite.config(self.g.id)
            roles = dict(c["activite_roles"] or {})
            if rid in roles:
                roles.pop(rid)
            else:
                roles[rid] = {}          # seuils par défaut jusqu'à réglage
            await _db_set(self.g.id, "activite_roles", roles)
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "cibles role")

    async def _cb_tout(self, i):
        try:
            c = await activite.config(self.g.id)
            await _db_set(self.g.id, "activite_tout_le_monde",
                          not c["activite_tout_le_monde"])
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "cibles tout")

    async def _cb_configurer(self, i):
        await ActiviteRoleSeuilsPanelV2(
            self.u, self.g, i.data["values"][0]).render_to(i, edit=True)

    async def _cb_retour(self, i):
        await ActivitePanelV2(self.u, self.g).render_to(i, edit=True)


class _SeuilsModal(discord.ui.Modal):
    """Les trois seuils d'un rôle, en jours."""

    def __init__(self, parent, rid: int, s: dict):
        super().__init__(title="Seuils d'inactivité (en jours)")
        self.parent = parent
        self.rid = rid
        self.rappel = discord.ui.TextInput(
            label="Rappel public", default=str(s["rappel"]),
            placeholder="7", max_length=4)
        self.retrait = discord.ui.TextInput(
            label="Retrait du rôle", default=str(s["retrait"]),
            placeholder="14", max_length=4)
        self.expulsion = discord.ui.TextInput(
            label="Proposition d'expulsion", default=str(s["expulsion"]),
            placeholder="21", max_length=4)
        for x in (self.rappel, self.retrait, self.expulsion):
            self.add_item(x)

    async def on_submit(self, i):
        try:
            vals = []
            for champ in (self.rappel, self.retrait, self.expulsion):
                n = int(str(champ.value).strip())
                if not 1 <= n <= 365:
                    return await i.response.send_message(
                        "❌ Chaque seuil doit être entre 1 et 365 jours.", ephemeral=True)
                vals.append(n)
            #  Un ordre incohérent rendrait des paliers inatteignables. On refuse
            #  plutôt que de « corriger » en silence un réglage voulu.
            if not vals[0] < vals[1] < vals[2]:
                return await i.response.send_message(
                    "❌ Les seuils doivent être croissants : rappel < retrait < expulsion.",
                    ephemeral=True)

            await activite.ecrire_config_role(
                self.parent.g.id, self.rid,
                rappel=vals[0], retrait=vals[1], expulsion=vals[2])
            await ActiviteRoleSeuilsPanelV2(
                self.parent.u, self.parent.g, self.rid).render_to(i, edit=True)
        except ValueError:
            await i.response.send_message("❌ Entrez des nombres entiers.", ephemeral=True)
        except Exception as ex:
            _log(f"[activite_panneau seuils] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.send_message("❌ Erreur d'enregistrement.", ephemeral=True)
            except Exception:
                pass


class ActiviteRoleSeuilsPanelV2(_Base):
    """La configuration COMPLÈTE d'un rôle — son suivi à lui, indépendant des autres.

    Chaque rôle a ses seuils, son salon d'annonce, son salon de retour et son
    jour de rappel. Un champ laissé vide retombe sur le réglage du serveur :
    on ne force pas à tout ressaisir pour changer un seul seuil, et l'écran dit
    clairement ce qui est « propre au rôle » et ce qui est « hérité ».
    """

    def __init__(self, u, g, rid):
        super().__init__(u, g)
        self.rid = str(rid)

    def _nom(self):
        if self.rid == activite.ROLE_TOUS:
            return "tout le serveur"
        r = self.g.get_role(int(self.rid))
        return r.name if r else f"rôle {self.rid}"

    async def render_to(self, i, *, edit: bool = True):
        try:
            c = await activite.config(self.g.id)
            conf = activite.config_du_role(c, self.rid)
            propres = conf["_propres"]

            def _marque(cle):
                return "" if cle in propres else "  -# _(serveur)_"

            role = (None if self.rid == activite.ROLE_TOUS
                    else self.g.get_role(int(self.rid)))
            cible = ("**tout le serveur**" if role is None
                     else (role.mention if role else f"`{self.rid}` _(rôle supprimé)_"))
            an = self.g.get_channel(conf["salon_annonce"])
            ret = self.g.get_channel(conf["salon_retour"])

            items = [
                v2_title(f"⚙️ Suivi · {self._nom()}"),
                v2_subtitle("Cette configuration n'appartient qu'à ce rôle"),
                v2_divider(),
                v2_body(
                    f"🎭 **Cible** · {cible}\n"
                    f"{_pastille(conf['actif'])} **Suivi** · "
                    + ("actif" if conf["actif"] else "suspendu pour ce rôle seulement")
                ),
                v2_divider(),
                v2_body(
                    f"1️⃣ **Rappel** · `{conf['rappel']}` j{_marque('rappel')}\n"
                    f"2️⃣ **Retrait du rôle** · `{conf['retrait']}` j{_marque('retrait')}\n"
                    f"3️⃣ **Expulsion proposée** · `{conf['expulsion']}` j{_marque('expulsion')}"
                ),
                v2_body(
                    f"📢 **Annonce** · {an.mention if an else '⚪ _aucun_'}"
                    f"{_marque('salon_annonce')}\n"
                    f"🔙 **Retour** · {ret.mention if ret else '⚪ _aucun_'}"
                    f"{_marque('salon_retour')}\n"
                    f"📅 **Jour** · {JOURS_SEMAINE[conf['jour_rappel'] % 7]}"
                    f"{_marque('jour_rappel')}"
                ),
                v2_divider(),
                v2_body(
                    f"{_pastille(conf['retirer_role'])} **Retirer le rôle au palier 2** · "
                    + ("oui" if conf["retirer_role"] else "non — le membre le garde")
                ),
                v2_body(
                    f"{_pastille(conf['restitution_auto'])} **Retour du rôle** · "
                    + ("automatique dès la première activité"
                       if conf["restitution_auto"]
                       else "**validé par le staff** — pour un rôle qui a de la valeur")
                ),
                v2_body("-# « serveur » = valeur héritée des réglages généraux. "
                        "Définissez-la ici pour rendre ce rôle indépendant."),
            ]

            sel_an = ChannelSelect(
                channel_types=[discord.ChannelType.text],
                placeholder="Salon d'annonce PROPRE à ce rôle…",
                min_values=1, max_values=1, custom_id=f"actr_an_{self.rid}")
            sel_an.callback = self._faire_salon("salon_annonce")
            sel_ret = ChannelSelect(
                channel_types=[discord.ChannelType.text],
                placeholder="Salon de retour PROPRE à ce rôle…",
                min_values=1, max_values=1, custom_id=f"actr_ret_{self.rid}")
            sel_ret.callback = self._faire_salon("salon_retour")

            b_seuils = Button(label="Seuils", emoji="✏️",
                              style=discord.ButtonStyle.primary,
                              custom_id=f"actr_ed_{self.rid}")
            b_seuils.callback = self._cb_seuils
            b_jour = Button(label=JOURS_SEMAINE[conf["jour_rappel"] % 7], emoji="📅",
                            style=discord.ButtonStyle.secondary,
                            custom_id=f"actr_j_{self.rid}")
            b_jour.callback = self._cb_jour
            b_actif = Button(
                label="Suivi actif" if conf["actif"] else "Suivi suspendu",
                emoji="🟢" if conf["actif"] else "⚪",
                style=(discord.ButtonStyle.success if conf["actif"]
                       else discord.ButtonStyle.secondary),
                custom_id=f"actr_a_{self.rid}")
            b_actif.callback = self._cb_actif
            b_retr = Button(
                label="Retire le rôle" if conf["retirer_role"] else "Ne retire pas",
                emoji="🟢" if conf["retirer_role"] else "⚪",
                style=(discord.ButtonStyle.success if conf["retirer_role"]
                       else discord.ButtonStyle.secondary),
                custom_id=f"actr_r_{self.rid}")
            b_retr.callback = self._cb_retrait
            b_rest = Button(
                label="Retour auto" if conf["restitution_auto"] else "Retour validé",
                emoji="🟢" if conf["restitution_auto"] else "🛡️",
                style=(discord.ButtonStyle.success if conf["restitution_auto"]
                       else discord.ButtonStyle.primary),
                custom_id=f"actr_rest_{self.rid}")
            b_rest.callback = self._cb_restitution
            b_reset = Button(label="Tout hériter du serveur", emoji="↩️",
                             style=discord.ButtonStyle.secondary,
                             custom_id=f"actr_z_{self.rid}")
            b_reset.callback = self._cb_reset

            items.append(discord.ui.ActionRow(sel_an))
            items.append(discord.ui.ActionRow(sel_ret))
            items.append(discord.ui.ActionRow(b_seuils, b_jour, b_actif, b_retr, b_rest))
            items.append(discord.ui.ActionRow(
                b_reset, _bouton_retour(self._cb_retour, f"actr_b_{self.rid}")))
            await self._envoyer(i, items, Palette.INFO, edit)
        except Exception as ex:
            await self._secours(i, ex, "role")

    def _faire_salon(self, cle):
        async def _cb(i):
            try:
                await activite.ecrire_config_role(
                    self.g.id, self.rid, **{cle: int(i.data["values"][0])})
                await self.render_to(i, edit=True)
            except Exception as ex:
                await self._secours(i, ex, f"role {cle}")
        return _cb

    async def _cb_seuils(self, i):
        c = await activite.config(self.g.id)
        await i.response.send_modal(
            _SeuilsModal(self, self.rid, activite.config_du_role(c, self.rid)))

    async def _cb_jour(self, i):
        try:
            c = await activite.config(self.g.id)
            conf = activite.config_du_role(c, self.rid)
            await activite.ecrire_config_role(
                self.g.id, self.rid, jour_rappel=(conf["jour_rappel"] + 1) % 7)
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "role jour")

    async def _cb_actif(self, i):
        try:
            c = await activite.config(self.g.id)
            conf = activite.config_du_role(c, self.rid)
            await activite.ecrire_config_role(
                self.g.id, self.rid, actif=not conf["actif"])
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "role actif")

    async def _cb_retrait(self, i):
        try:
            c = await activite.config(self.g.id)
            conf = activite.config_du_role(c, self.rid)
            await activite.ecrire_config_role(
                self.g.id, self.rid, retirer_role=not conf["retirer_role"])
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "role retrait")

    async def _cb_restitution(self, i):
        """Bascule : le rôle revient tout seul, ou le staff valide.

        Pour un rôle de clan ou de faction, la validation est le bon réglage :
        un rôle qu'on récupère en postant un emoji ne veut plus rien dire.
        """
        try:
            c = await activite.config(self.g.id)
            conf = activite.config_du_role(c, self.rid)
            await activite.ecrire_config_role(
                self.g.id, self.rid, restitution_auto=not conf["restitution_auto"])
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "role restitution")

    async def _cb_reset(self, i):
        """Efface les réglages propres au rôle : il repasse sur ceux du serveur.

        On garde `actif` et le marqueur de semaine : remettre à zéro une
        configuration ne doit pas relancer un rappel déjà envoyé.
        """
        try:
            c = await activite.config(self.g.id)
            conf = activite.config_du_role(c, self.rid)
            await activite.ecrire_config_role(
                self.g.id, self.rid,
                rappel=None, retrait=None, expulsion=None,
                salon_annonce=0, salon_retour=0, jour_rappel=None,
                actif=conf["actif"], restitution_auto=conf["restitution_auto"],
                derniere_semaine=conf["derniere_semaine"])
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "role reset")

    async def _cb_retour(self, i):
        await ActiviteCiblesPanelV2(self.u, self.g).render_to(i, edit=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  SALONS
# ═══════════════════════════════════════════════════════════════════════════════

class ActiviteSalonsPanelV2(_Base):
    """Les trois salons du système, chacun avec un rôle distinct."""

    CHAMPS = [
        ("activite_salon_annonce", "📢 Annonce",
         "Où le rappel hebdomadaire est publié. Les inactifs y sont mentionnés."),
        ("activite_salon_retour", "🔙 Retour",
         "Où un membre écrit pour récupérer son rôle mis en veille."),
        ("activite_salon_staff", "🛡️ Staff",
         "Où le bot vous rend compte et propose les expulsions. Réservé au staff."),
    ]

    async def render_to(self, i, *, edit: bool = True):
        try:
            c = await activite.config(self.g.id)
            lignes = []
            for cle, nom, aide in self.CHAMPS:
                ch = self.g.get_channel(int(c.get(cle, 0) or 0))
                lignes.append(f"**{nom}** · {ch.mention if ch else '⚪ _non défini_'}\n"
                              f"-# {aide}")

            jour = int(c["activite_jour_rappel"] or 0) % 7
            items = [
                v2_title("📢 Salons"),
                v2_subtitle("Chaque salon a un rôle précis — ne les mélangez pas"),
                v2_divider(),
                v2_body("\n\n".join(lignes)),
                v2_divider(),
                v2_body(f"📅 **Jour du rappel** · {JOURS_SEMAINE[jour]}\n"
                        "-# Le rappel n'est envoyé qu'une fois par semaine, ce jour-là."),
            ]

            for cle, nom, _ in self.CHAMPS:
                sel = ChannelSelect(
                    channel_types=[discord.ChannelType.text],
                    placeholder=f"Définir le salon {nom.split(' ', 1)[1].lower()}…",
                    min_values=1, max_values=1, custom_id=f"act_ch_{cle}")
                sel.callback = self._faire_salon(cle)
                items.append(discord.ui.ActionRow(sel))

            b_jour = Button(label=f"Jour : {JOURS_SEMAINE[jour]}", emoji="📅",
                            style=discord.ButtonStyle.secondary, custom_id="act_jour")
            b_jour.callback = self._cb_jour
            items.append(discord.ui.ActionRow(
                b_jour, _bouton_retour(self._cb_retour, "act_sal_back")))
            await self._envoyer(i, items, Palette.INFO, edit)
        except Exception as ex:
            await self._secours(i, ex, "salons")

    def _faire_salon(self, cle: str):
        async def _cb(i):
            try:
                await _db_set(self.g.id, cle, int(i.data["values"][0]))
                await self.render_to(i, edit=True)
            except Exception as ex:
                await self._secours(i, ex, f"salon {cle}")
        return _cb

    async def _cb_jour(self, i):
        try:
            c = await activite.config(self.g.id)
            await _db_set(self.g.id, "activite_jour_rappel",
                          (int(c["activite_jour_rappel"] or 0) + 1) % 7)
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "jour")

    async def _cb_retour(self, i):
        await ActivitePanelV2(self.u, self.g).render_to(i, edit=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  RÉCOMPENSES
# ═══════════════════════════════════════════════════════════════════════════════

class ActiviteRecompensesPanelV2(_Base):
    """Niveaux et VIP. Tout dérive des jours actifs cumulés."""

    async def render_to(self, i, *, edit: bool = True):
        try:
            cr = await rec.config(self.g.id)
            on = bool(cr["activite_recompenses_enabled"])
            vip = self.g.get_role(int(cr["activite_vip_role"] or 0))
            niv = int(cr["activite_vip_niveau"] or 6)
            jours_vip = rec.jours_pour_niveau(niv)

            echelle = " · ".join(
                f"n{n}={rec.jours_pour_niveau(n)}j" for n in (1, 3, 6, 9, 12, 15))

            items = [
                v2_title("🏅 Récompenses"),
                v2_subtitle("Une seule mesure : les jours de présence réelle"),
                v2_divider(),
                v2_body(
                    f"{_pastille(on)} **Niveaux** · {'actifs' if on else 'éteints'}\n"
                    f"👑 **Rôle VIP** · {vip.mention if vip else '⚪ _aucun_'}\n"
                    f"🎯 **VIP à partir du** niveau `{niv}` — soit `{jours_vip}` jours actifs"
                ),
                v2_divider(),
                v2_body(
                    "**Pourquoi des jours et pas de l'XP par message :**\n"
                    "-# Compter les messages récompense le spam. Compter les jours "
                    "récompense la présence — 200 messages en une soirée valent une "
                    "journée, comme un seul message.\n\n"
                    f"**Échelle** · {echelle}"
                ),
                v2_divider(),
                v2_body("-# Le VIP n'est retiré que si le membre atteint le palier de "
                        "retrait d'inactivité, pas au premier jour d'absence."),
            ]

            sel = RoleSelect(placeholder="Choisir le rôle VIP…",
                             min_values=1, max_values=1, custom_id="act_vip_role")
            sel.callback = self._cb_vip_role

            b_on = Button(label="Niveaux actifs" if on else "Niveaux éteints",
                          emoji="🟢" if on else "⚪",
                          style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary,
                          custom_id="act_rec_toggle")
            b_on.callback = self._cb_toggle
            b_niv = Button(label=f"VIP au niveau {niv}", emoji="🎯",
                           style=discord.ButtonStyle.primary, custom_id="act_rec_niv")
            b_niv.callback = self._cb_niveau

            items.append(discord.ui.ActionRow(sel))
            items.append(discord.ui.ActionRow(
                b_on, b_niv, _bouton_retour(self._cb_retour, "act_rec_back")))
            await self._envoyer(i, items, Palette.PREMIUM, edit)
        except Exception as ex:
            await self._secours(i, ex, "recompenses")

    async def _cb_toggle(self, i):
        try:
            cr = await rec.config(self.g.id)
            await _db_set(self.g.id, "activite_recompenses_enabled",
                          not cr["activite_recompenses_enabled"])
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "rec toggle")

    async def _cb_vip_role(self, i):
        try:
            await _db_set(self.g.id, "activite_vip_role", int(i.data["values"][0]))
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "rec vip")

    async def _cb_niveau(self, i):
        """Fait tourner le niveau requis parmi les paliers utiles."""
        try:
            cr = await rec.config(self.g.id)
            choix = [3, 6, 9, 12, 15]
            actuel = int(cr["activite_vip_niveau"] or 6)
            suivant = choix[(choix.index(actuel) + 1) % len(choix)] if actuel in choix else 6
            await _db_set(self.g.id, "activite_vip_niveau", suivant)
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "rec niveau")

    async def _cb_retour(self, i):
        await ActivitePanelV2(self.u, self.g).render_to(i, edit=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  APERÇU + EXPULSIONS
# ═══════════════════════════════════════════════════════════════════════════════

class ActiviteApercuPanelV2(_Base):
    """Aperçu à blanc, et le SEUL endroit où une expulsion peut être déclenchée.

    L'aperçu appelle exactement la même fonction que le passage quotidien, en
    `dry_run` : ce qui est affiché est ce qui arrivera, sans approximation.
    """

    async def render_to(self, i, *, edit: bool = True):
        try:
            if not i.response.is_done():
                await i.response.defer()          # le calcul peut prendre du temps
            rap = await passage.passage(self.g, dry_run=True)
            cl = rap.get("fiches") or {}
            expulsables = cl.get("expulsion") or []
            diag = await activite.diagnostic(self.g.id)

            items = [
                v2_title("🔎 Aperçu"),
                v2_subtitle("Calculé à blanc — rien n'est appliqué ici"),
                v2_divider(),
                # Le diagnostic AVANT le classement : avant de regarder qui est
                # inactif, il faut savoir si le suivi capte quelque chose. Un
                # classement calculé sur un suivi muet accuse tout le monde.
                v2_body(activite.diagnostic_texte(diag)),
                v2_divider(),
                v2_body(passage.resume_texte(rap)),
            ]

            if expulsables:
                lignes = [f"• {f['member'].mention} — `{f['jours']}` j"
                          for f in expulsables[:15]]
                if len(expulsables) > 15:
                    lignes.append(f"-# … et {len(expulsables) - 15} autre(s)")
                items.append(v2_divider())
                items.append(v2_title("🚪 Proposés à l'expulsion", level=3))
                items.append(v2_body("\n".join(lignes)))
                items.append(v2_body(
                    "-# ⚠️ Action irréversible. Le bot ne l'exécutera JAMAIS seul : "
                    "ce bouton est le seul chemin."))

            b_maj = Button(label="Recalculer", emoji="🔄",
                           style=discord.ButtonStyle.secondary, custom_id="act_ap_maj")
            b_maj.callback = self._cb_recalculer
            ligne = [b_maj]
            if expulsables:
                b_kick = Button(
                    label=f"Expulser les {len(expulsables)}", emoji="🚪",
                    style=discord.ButtonStyle.danger, custom_id="act_ap_kick")
                b_kick.callback = self._cb_expulser
                ligne.append(b_kick)
            ligne.append(_bouton_retour(self._cb_retour, "act_ap_back"))

            items.append(discord.ui.ActionRow(*ligne))
            self.clear_items()
            self.add_item(v2_container(*items, color=Palette.WARNING))
            await i.edit_original_response(content=None, view=self, embed=None)
        except Exception as ex:
            await self._secours(i, ex, "apercu")

    async def _cb_recalculer(self, i):
        await self.render_to(i, edit=True)

    async def _cb_expulser(self, i):
        """Expulse les membres proposés. SEUL chemin d'expulsion du système."""
        try:
            if not i.response.is_done():
                await i.response.defer()
            #  Recalcul JUSTE AVANT d'agir : la liste affichée peut dater de
            #  plusieurs minutes, et quelqu'un a pu revenir entre-temps.
            rap = await passage.passage(self.g, dry_run=True)
            if rap.get("plafond_declenche"):
                return await i.followup.send(
                    f"🛑 Garde-fou : {rap['raison']}", ephemeral=True)

            faits, echecs, epargnes = 0, 0, 0
            cfg_act = await activite.config(self.g.id)
            for f in (rap.get("fiches") or {}).get("expulsion", []):
                m = f["member"]
                #  Dernière vérification d'immunité avant l'irréversible.
                if not await activite.membre_concerne(m, cfg_act):
                    epargnes += 1
                    continue
                try:
                    await m.kick(reason=f"Inactif depuis {f['jours']} jours")
                    faits += 1
                except Exception as ex:
                    _log(f"[activite expulsion {m.id}] {ex}")
                    echecs += 1

            await i.followup.send(
                f"🚪 **{faits}** expulsé(s) · ❌ {echecs} échec(s) · "
                f"🛡️ {epargnes} épargné(s) (devenus intouchables)", ephemeral=True)
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "expulsion")

    async def _cb_retour(self, i):
        await ActivitePanelV2(self.u, self.g).render_to(i, edit=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPENSES — qui n'est pas soumis à l'obligation de présence
# ═══════════════════════════════════════════════════════════════════════════════

class ActiviteDispensesPanelV2(_Base):
    """Rôles et membres dispensés d'activité.

    À ne pas confondre avec les immunités de modération : dispenser quelqu'un de
    PRÉSENCE n'a rien à voir avec le dispenser des filtres anti-spam. Un ancien,
    un ami du serveur ou un bot partenaire n'ont pas à être surveillés, sans pour
    autant devenir intouchables face aux insultes.
    """

    async def render_to(self, i, *, edit: bool = True):
        try:
            c = await activite.config(self.g.id)
            rids = [int(x) for x in (c.get("activite_roles_immunises") or [])]
            mids = [int(x) for x in (c.get("activite_membres_immunises") or [])]

            roles = [self.g.get_role(r) for r in rids]
            roles = [r for r in roles if r is not None]
            membres = [self.g.get_member(m) for m in mids]
            membres = [m for m in membres if m is not None]

            bloc_roles = (", ".join(r.mention for r in roles[:15]) if roles
                          else "⚪ _aucun_")
            bloc_membres = (", ".join(m.mention for m in membres[:15]) if membres
                            else "⚪ _aucun_")
            perdus = (len(rids) - len(roles)) + (len(mids) - len(membres))

            items = [
                v2_title("🛡️ Dispenses d'activité"),
                v2_subtitle("Qui n'a pas d'obligation de présence"),
                v2_divider(),
                v2_body(f"🎭 **Rôles dispensés**\n{bloc_roles}"),
                v2_body(f"👤 **Membres dispensés**\n{bloc_membres}"),
                v2_divider(),
                v2_body(
                    "**Toujours dispensés, sans rien régler :**\n"
                    "-# le propriétaire du serveur · le super-owner · tout "
                    "administrateur · les membres immunisés en modération · les bots"
                ),
                v2_body(
                    "-# Ces listes ne concernent QUE l'activité. Un membre dispensé "
                    "ici reste soumis aux filtres anti-spam, anti-scam et aux "
                    "sanctions — ce sont deux choses différentes."
                ),
            ]
            if perdus:
                items.append(v2_body(
                    f"-# ⚠️ {perdus} entrée(s) pointent vers un rôle ou un membre "
                    f"qui n'existe plus. Elles sont ignorées ; re-choisissez-les "
                    f"pour nettoyer."))

            sel_r = RoleSelect(placeholder="Ajouter ou retirer un rôle dispensé…",
                               min_values=1, max_values=1, custom_id="actd_role")
            sel_r.callback = self._faire_bascule("activite_roles_immunises")
            sel_m = UserSelect(placeholder="Ajouter ou retirer un membre dispensé…",
                               min_values=1, max_values=1, custom_id="actd_membre")
            sel_m.callback = self._faire_bascule("activite_membres_immunises")

            items.append(discord.ui.ActionRow(sel_r))
            items.append(discord.ui.ActionRow(sel_m))
            items.append(discord.ui.ActionRow(
                _bouton_retour(self._cb_retour, "actd_back")))
            await self._envoyer(i, items, Palette.SUCCESS, edit)
        except Exception as ex:
            await self._secours(i, ex, "dispenses")

    def _faire_bascule(self, cle: str):
        """Choisir une entrée déjà présente la RETIRE — un seul geste pour les deux."""
        async def _cb(i):
            try:
                choisi = int(i.data["values"][0])
                c = await activite.config(self.g.id)
                liste = [int(x) for x in (c.get(cle) or [])]
                if choisi in liste:
                    liste.remove(choisi)
                else:
                    liste.append(choisi)
                await _db_set(self.g.id, cle, liste)
                await self.render_to(i, edit=True)
            except Exception as ex:
                await self._secours(i, ex, f"dispense {cle}")
        return _cb

    async def _cb_retour(self, i):
        await ActivitePanelV2(self.u, self.g).render_to(i, edit=True)
