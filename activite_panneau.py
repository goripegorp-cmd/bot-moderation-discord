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
   ├── ActiviteRolesAfkPanelV2 les deux rôles d'absence + masquage des salons
   ├── ActiviteSalonsPanelV2   annonce · retour · staff
   ├── ActiviteRecompensesPanelV2  niveaux et VIP
   ├── ActiviteApercuPanelV2   aperçu à blanc + validation des expulsions
   └── ActiviteDispensesPanelV2  qui est dispensé de présence

Chaque panneau lit son état à l'ouverture (`render_to`) et n'écrit qu'au clic.
Le module ne connaît pas `bot.py` : tout ce dont il a besoin lui est injecté par
`setup()`, ce qui le rend testable et évite l'import circulaire.
"""
from __future__ import annotations

import discord
from discord.ui import Button, ChannelSelect, RoleSelect, Select, UserSelect

import activite
import activite_calendrier as cal
import activite_escalade as esc
import activite_niveaux as niv
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
            #  Un panneau qui a dû répondre avant de travailler (masquage de deux
            #  cents salons : bien au-delà des 3 secondes accordées) arrive ici
            #  avec l'interaction déjà consommée. Sans ce cas, son résultat ne
            #  s'affiche jamais et le bouton paraît sans effet.
            if i.response.is_done():
                await i.edit_original_response(content=None, view=self,
                                               embed=None, attachments=[])
            else:
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
            afk1 = self.g.get_role(int(c["activite_role_niveau1"] or 0))
            afk2 = self.g.get_role(int(c["activite_role_niveau2"] or 0))

            #  ⚠️ Ne PAS appeler `observation_jours` ici : elle POSE l'ancre si
            #  elle manque. Ouvrir l'écran de configuration ne doit rien
            #  démarrer — sinon un simple coup d'œil lancerait le compte à
            #  rebours d'un système que le propriétaire n'a pas encore allumé.
            ancre = str(c.get("activite_observe_depuis") or "")
            obs = cal.jours_entre(ancre) if ancre else None
            seuil_max = activite.config_du_role(c, activite.ROLE_TOUS)["expulsion"]
            if not ancre:
                obs_texte = ("🕐 **Observation** · _pas encore commencée_\n"
                             "-# Elle démarre à l'allumage. Aucune absence "
                             "antérieure ne sera reprochée à qui que ce soit.")
            elif obs is not None and obs < seuil_max:
                obs_texte = (
                    f"🕐 **Observation** · `{obs}` jour(s) depuis le `{ancre}`\n"
                    f"-# Le silence de chacun est plafonné à `{obs}` j : "
                    f"personne ne peut être proposé à l'expulsion avant "
                    f"`{seuil_max - obs}` jour(s) de plus. C'est voulu — on ne "
                    f"reproche pas des journées qu'on n'a pas observées.")
            else:
                obs_texte = (f"🕐 **Observation** · `{obs}` jour(s) depuis le "
                             f"`{ancre}` — tous les paliers sont atteignables.")

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
                v2_body(
                    f"{_pastille(bool(afk1 and afk2))} **Rôles AFK** · "
                    f"{afk1.mention if afk1 else '⚪ _niveau 1 manquant_'} → "
                    f"{afk2.mention if afk2 else '⚪ _niveau 2 manquant_'}\n"
                    f"{_pastille(c['activite_masquer_salons'])} **Masquage** · "
                    f"{'les absents ne voient plus que 2 salons' if c['activite_masquer_salons'] else 'désactivé'}"
                ),
                v2_divider(),
                #  L'observation : la seule ligne qui explique pourquoi rien ne
                #  se passe encore. Sans elle, un propriétaire qui vient
                #  d'allumer croit le système cassé — ou pire, ne comprend pas
                #  pourquoi il agirait un jour.
                v2_body(obs_texte),
                v2_divider(),
                #  La règle telle qu'un membre la vit, pas telle que le code la
                #  calcule. Les seuils affichés sont ceux du serveur ; un rôle
                #  qui a les siens le montre dans son propre écran.
                v2_body(
                    f"**La règle : être vu au moins "
                    f"`{c['activite_seuil_presence']}` jour(s) sur "
                    f"`{c['activite_fenetre']}`.**\n"
                    f"👀 vu trop rarement → simple rappel, rien de retiré "
                    f"(`{c['activite_doux_max']}` fois de suite → passe en 1️⃣)\n"
                    "1️⃣ silence prolongé → **rôle AFK**, le serveur se masque\n"
                    "2️⃣ **tous ses rôles retirés** — rendus dès son retour\n"
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

            b_afk = Button(label="Rôles AFK & masquage", emoji="💤",
                           style=discord.ButtonStyle.primary, custom_id="act_afk")
            b_afk.callback = self._cb_afk

            items.append(discord.ui.ActionRow(b_on, b_cibles, b_salons, b_afk))
            items.append(discord.ui.ActionRow(
                b_rec, b_ap, b_disp, _bouton_retour(self._cb_retour, "act_back")))
            await self._envoyer(i, items, Palette.INFO, edit)
        except Exception as ex:
            await self._secours(i, ex, "racine")

    async def _cb_toggle(self, i):
        try:
            c = await activite.config(self.g.id)
            allume = not c["activite_enabled"]
            await _db_set(self.g.id, "activite_enabled", allume)
            #  Poser l'ancre d'observation au PREMIER allumage, jamais ensuite.
            #  Sans elle, le système reprocherait aux membres des mois qu'il n'a
            #  pas observés (voir `activite.observation_jours`). La réécrire à
            #  chaque ON ferait d'un OFF/ON un moyen de repousser l'escalade
            #  indéfiniment : c'est pour ça que le bouton de réarmement est
            #  séparé, explicite, et dans un autre écran.
            if allume and not c.get("activite_observe_depuis"):
                await activite.observation_jours(self.g.id)
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

    async def _cb_afk(self, i):
        await ActiviteRolesAfkPanelV2(self.u, self.g).render_to(i, edit=True)

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
    """Les seuils d'un rôle : trois durées de silence, plus l'exigence de présence.

    Cinq champs — le maximum d'un formulaire Discord, et c'est exactement ce
    qu'il faut : les trois paliers de silence, le nombre de jours où il faut
    s'être montré, et le nombre de rappels doux tolérés d'affilée.
    """

    def __init__(self, parent, rid: int, s: dict):
        super().__init__(title="Seuils d'activité")
        self.parent = parent
        self.rid = rid
        self.rappel = discord.ui.TextInput(
            label="Silence avant le rôle AFK (jours)", default=str(s["rappel"]),
            placeholder="7", max_length=4)
        self.retrait = discord.ui.TextInput(
            label="Silence avant le retrait des rôles (jours)",
            default=str(s["retrait"]), placeholder="14", max_length=4)
        self.expulsion = discord.ui.TextInput(
            label="Silence avant proposition d'expulsion (jours)",
            default=str(s["expulsion"]), placeholder="21", max_length=4)
        self.presence = discord.ui.TextInput(
            label="Jours de présence exigés sur la fenêtre",
            default=str(s["presence"]), placeholder="3", max_length=3)
        self.doux = discord.ui.TextInput(
            label="Rappels doux d'affilée avant le rôle AFK",
            default=str(s["doux_max"]), placeholder="3", max_length=3)
        for x in (self.rappel, self.retrait, self.expulsion,
                  self.presence, self.doux):
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

            c = await activite.config(self.parent.g.id)
            fenetre = int(c.get("activite_fenetre") or activite.FENETRE_PRESENCE_DEFAUT)
            presence = int(str(self.presence.value).strip())
            #  Exiger plus de jours que la fenêtre n'en contient rendrait TOUT LE
            #  MONDE fautif en permanence, y compris les membres présents chaque
            #  jour. C'est le réglage qui transforme le système en machine à
            #  expulser : on le refuse net.
            if not 1 <= presence <= fenetre:
                return await i.response.send_message(
                    f"❌ La présence exigée doit être entre 1 et {fenetre} — "
                    f"la fenêtre ne compte que {fenetre} jour(s).", ephemeral=True)

            doux = int(str(self.doux.value).strip())
            if not 1 <= doux <= 52:
                return await i.response.send_message(
                    "❌ Les rappels doux tolérés doivent être entre 1 et 52.",
                    ephemeral=True)

            await activite.ecrire_config_role(
                self.parent.g.id, self.rid,
                rappel=vals[0], retrait=vals[1], expulsion=vals[2],
                presence=presence, doux_max=doux)
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
                    f"👀 **Présence exigée** · `{conf['presence']}` jour(s) vu(s) "
                    f"sur `{c['activite_fenetre']}`{_marque('presence')}\n"
                    f"-# En dessous : rappel doux, rien de retiré. "
                    f"`{conf['doux_max']}` fois d'affilée{_marque('doux_max')} "
                    f"et il passe en 1️⃣."
                ),
                v2_body(
                    f"1️⃣ **Rôle AFK** · `{conf['rappel']}` j de silence{_marque('rappel')}\n"
                    f"2️⃣ **Tous ses rôles retirés** · `{conf['retrait']}` j{_marque('retrait')}\n"
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
                    f"{_pastille(conf['retirer_role'])} **Retirer tous ses rôles au 2️⃣** · "
                    + ("oui" if conf["retirer_role"] else "non — il garde tout")
                ),
                v2_body(
                    f"{_pastille(conf['restitution_auto'])} **Retour des rôles** · "
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
#  RÔLES AFK ET MASQUAGE
# ═══════════════════════════════════════════════════════════════════════════════

class ActiviteRolesAfkPanelV2(_Base):
    """Les deux rôles d'inactivité, et le masquage du serveur qu'ils portent.

    L'écran le plus délicat du système : c'est ici qu'on décide que des membres
    ne verront plus rien du serveur. Il affiche donc TROIS choses avant tout
    bouton — quels rôles, si le bot peut réellement les manipuler, et quels
    salons resteraient visibles malgré le masquage.
    """

    def __init__(self, u, g):
        super().__init__(u, g)
        #  Résultat de la dernière action, affiché en haut. Sans ce retour, un
        #  bouton qui travaille 90 secondes semble n'avoir rien fait.
        self._dernier = ""

    async def render_to(self, i, *, edit: bool = True):
        try:
            c = await activite.config(self.g.id)
            r0 = self.g.get_role(int(c["activite_role_doux"] or 0))
            r1 = self.g.get_role(int(c["activite_role_niveau1"] or 0))
            r2 = self.g.get_role(int(c["activite_role_niveau2"] or 0))
            ouverts = niv.salons_ouverts(self.g, c)
            confl = niv.conflits(self.g, c) if (r1 or r2) else []

            def _nom_palier(niveau: int) -> str:
                #  Le palier 0 n'est pas un « niveau » de sanction : l'appeler
                #  ainsi laisserait croire à une punition graduée alors qu'il
                #  ne retire rien et ne masque rien.
                return "Peu actif" if niveau == 0 else f"Niveau {niveau}"

            def _etat(r, niveau: int) -> str:
                if r is None:
                    return f"⚪ **{_nom_palier(niveau)}** · _aucun rôle_"
                if not niv.utilisable(self.g, r):
                    return (f"🔴 **{_nom_palier(niveau)}** · {r.mention}\n"
                            f"-# ⚠️ Le bot ne peut pas le poser : remontez son "
                            f"propre rôle au-dessus de celui-ci dans les "
                            f"paramètres du serveur.")
                return (f"🟢 **{_nom_palier(niveau)}** · {r.mention} · "
                        f"`{len(r.members)}` membre(s)")

            items = [
                v2_title("💤 Rôles AFK & masquage"),
                v2_subtitle("Le rôle rend l'absence visible — et masque le serveur"),
                v2_divider(),
                #  ⚠️ LA PERMISSION DE MENTIONNER EST AFFICHÉE ICI, EN CLAIR.
                #  Sans « Mentionner tous les rôles », la mention du rôle
                #  s'affiche et ne notifie PERSONNE — exactement le symptôme
                #  que ce rôle doit corriger, mais en silencieux.
                v2_body(
                    f"{_etat(r0, 0)}\n"
                    f"-# Posé dès qu'un membre se montre trop peu. **Aucune "
                    f"sanction, aucun masquage** : il ne sert qu'à être "
                    f"mentionné, pour ne pas citer des centaines de pseudos.\n"
                    + ("-# 🟢 Le bot peut mentionner les rôles."
                       if self.g.me.guild_permissions.mention_everyone
                       else "-# 🔴 **Il manque « Mentionner tous les rôles » "
                            "au bot** : la mention s'affichera sans notifier "
                            "personne.")),
                v2_body(f"{_etat(r1, 1)}\n-# Posé au 1er seuil. Le membre garde "
                        f"tous ses autres rôles."),
                v2_body(f"{_etat(r2, 2)}\n-# Posé au 2e seuil, en même temps que "
                        f"le retrait de tous ses rôles."),
                v2_divider(),
            ]

            if self._dernier:
                items.append(v2_body(self._dernier))
                items.append(v2_divider())

            #  Ce que le masquage laisse ouvert. Affiché AVANT le bouton, parce
            #  que c'est la seule information qui permet de juger si l'on va
            #  enfermer les absents ou leur laisser une porte.
            if ouverts:
                noms = []
                for sid in sorted(ouverts):
                    ch = self.g.get_channel(sid)
                    noms.append(ch.mention if ch else f"`{sid}` _(introuvable)_")
                reste = "  ·  ".join(noms)
            else:
                reste = "⚠️ **aucun** — les absents seraient enfermés sans issue"

            items.append(v2_body(
                f"{_pastille(c['activite_masquer_salons'])} **Masquage des salons**\n"
                f"-# Tous les salons deviennent invisibles aux porteurs de ces "
                f"rôles, y compris ceux créés plus tard.\n"
                f"👁️ **Resteraient visibles** · {reste}"))

            #  Le piège des permissions Discord, rendu concret. Voir l'en-tête de
            #  `activite_niveaux.py` : une autorisation explicite sur un autre
            #  rôle écrase notre refus, et seul le 2e niveau y échappe.
            if confl:
                apercu = ", ".join(f"#{x['salon']}" for x in confl[:5])
                if len(confl) > 5:
                    apercu += f" … (+{len(confl) - 5})"
                items.append(v2_body(
                    f"⚠️ **`{len(confl)}` salon(s) resteront visibles au niveau 1**\n"
                    f"-# {apercu}\n"
                    f"-# Un autre rôle du membre y autorise explicitement la "
                    f"lecture, ce qui écrase le masquage. Au niveau 2 il n'a "
                    f"plus ces rôles, donc il ne les verra plus."))

            items.append(v2_divider())

            #  ⚠️ LE PALIER 0 EST DANS LA MÊME BOUCLE, exprès. Le rôle qui
            #  touche le plus de monde (des centaines) doit se régler au même
            #  endroit que les deux autres, sinon il reste introuvable.
            for niveau, cle in ((0, "activite_role_doux"),
                                (1, "activite_role_niveau1"),
                                (2, "activite_role_niveau2")):
                sel = RoleSelect(
                    placeholder=("Rôle « peu actif » (aucune sanction)…"
                                 if niveau == 0
                                 else f"Rôle du niveau {niveau}…"),
                    min_values=1, max_values=1, custom_id=f"act_afk_{niveau}")
                sel.callback = self._faire_role(cle)
                items.append(discord.ui.ActionRow(sel))

            b_creer = Button(
                label="Créer les rôles manquants", emoji="✨",
                style=discord.ButtonStyle.success, custom_id="act_afk_creer",
                disabled=bool(r0 and r1 and r2))
            b_creer.callback = self._cb_creer

            b_masq = Button(
                label="Masquage activé" if c["activite_masquer_salons"]
                else "Masquage désactivé",
                emoji="🙈" if c["activite_masquer_salons"] else "👁️",
                style=(discord.ButtonStyle.success if c["activite_masquer_salons"]
                       else discord.ButtonStyle.secondary),
                custom_id="act_afk_masq")
            b_masq.callback = self._cb_masquage

            b_app = Button(
                label="Appliquer maintenant", emoji="🔒",
                style=discord.ButtonStyle.primary, custom_id="act_afk_app",
                disabled=not (r1 or r2) or not c["activite_masquer_salons"])
            b_app.callback = self._cb_appliquer

            b_def = Button(
                label="Tout rouvrir", emoji="↩️",
                style=discord.ButtonStyle.danger, custom_id="act_afk_def",
                disabled=not (r1 or r2))
            b_def.callback = self._cb_rouvrir

            items.append(discord.ui.ActionRow(b_creer, b_masq, b_app, b_def))
            items.append(discord.ui.ActionRow(
                _bouton_retour(self._cb_retour, "act_afk_back")))
            await self._envoyer(i, items, Palette.INFO, edit)
        except Exception as ex:
            await self._secours(i, ex, "rôles afk")

    def _faire_role(self, cle: str):
        async def _cb(i):
            try:
                await _db_set(self.g.id, cle, int(i.data["values"][0]))
                #  Le cache du retour immédiat doit connaître ce rôle TOUT DE
                #  SUITE : sans ça, un membre étiqueté qui écrit ne serait
                #  débloqué qu'au passage suivant, jusqu'à six heures plus tard.
                niv.memoriser_ids(await activite.config(self.g.id))
                self._dernier = ""
                await self.render_to(i, edit=True)
            except Exception as ex:
                await self._secours(i, ex, f"rôle afk {cle}")
        return _cb

    async def _cb_creer(self, i):
        """Crée les rôles absents. Ne touche jamais à ceux déjà désignés."""
        try:
            await i.response.defer()
            c = await activite.config(self.g.id)
            crees = []
            for niveau, cle in ((0, "activite_role_doux"),
                                (1, "activite_role_niveau1"),
                                (2, "activite_role_niveau2")):
                if self.g.get_role(int(c.get(cle) or 0)) is not None:
                    continue
                r = await niv.creer_role(self.g, niveau)
                if r is not None:
                    await _db_set(self.g.id, cle, r.id)
                    crees.append(r.name)
            if crees:
                niv.memoriser_ids(await activite.config(self.g.id))
            self._dernier = (f"✅ Créé : {', '.join(crees)}" if crees
                             else "⚠️ Rien à créer, ou permission « Gérer les "
                                  "rôles » manquante.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "création rôles afk")

    async def _cb_masquage(self, i):
        try:
            c = await activite.config(self.g.id)
            await _db_set(self.g.id, "activite_masquer_salons",
                          not c["activite_masquer_salons"])
            self._dernier = ""
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "bascule masquage")

    async def _cb_appliquer(self, i):
        """Pose le masquage sur tous les salons, tout de suite.

        Le passage quotidien le fait déjà, mais l'attendre pour vérifier que la
        configuration est bonne serait absurde : on veut voir le résultat au
        moment où on règle, pas le lendemain.
        """
        try:
            await i.response.defer()
            c = await activite.config(self.g.id)
            res = await niv.appliquer_masquage(self.g, c)
            if res.get("raison"):
                self._dernier = f"⚠️ {res['raison']}"
            else:
                self._dernier = (
                    f"🔒 `{res['modifies']}` salon(s) masqué(s) · "
                    f"`{res['deja_bons']}` déjà en règle"
                    + (f" · ⚠️ `{res['ignores']}` hors de portée du bot"
                       if res["ignores"] else "")
                    + (f" · ❌ `{res['echecs']}` échec(s)" if res["echecs"] else ""))
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "application masquage")

    async def _cb_rouvrir(self, i):
        """Retire toutes les surcharges posées par le système. Le retour arrière.

        Bouton rouge et volontairement présent : un système de masquage qu'on ne
        peut pas défaire d'un clic ne devrait jamais être allumé.
        """
        try:
            await i.response.defer()
            c = await activite.config(self.g.id)
            res = await niv.retirer_masquage(self.g, c)
            self._dernier = (f"↩️ `{res['nettoyes']}` salon(s) rouvert(s)"
                             + (f" · ❌ `{res['echecs']}` échec(s)"
                                if res["echecs"] else ""))
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "réouverture")

    async def _cb_retour(self, i):
        await ActivitePanelV2(self.u, self.g).render_to(i, edit=True)


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
            niveau_vip = int(cr["activite_vip_niveau"] or 6)
            jours_vip = rec.jours_pour_niveau(niveau_vip)

            echelle = " · ".join(
                f"n{n}={rec.jours_pour_niveau(n)}j" for n in (1, 3, 6, 9, 12, 15))

            items = [
                v2_title("🏅 Récompenses"),
                v2_subtitle("Une seule mesure : les jours de présence réelle"),
                v2_divider(),
                v2_body(
                    f"{_pastille(on)} **Niveaux** · {'actifs' if on else 'éteints'}\n"
                    f"👑 **Rôle VIP** · {vip.mention if vip else '⚪ _aucun_'}\n"
                    f"🎯 **VIP à partir du** niveau `{niveau_vip}` — soit `{jours_vip}` jours actifs"
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
            b_niv = Button(label=f"VIP au niveau {niveau_vip}", emoji="🎯",
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

            #  ⚠️ Ne JAMAIS proposer une action que le passage refuse d'exécuter.
            #  Avant le 12/08/2026, ce bloc et son bouton rouge s'affichaient
            #  trois lignes sous la bannière du garde-fou, dans le MÊME message :
            #  le staff lisait « rien n'a été appliqué », voyait « Expulser les
            #  941 », cliquait, et se faisait refuser. Un panneau qui se
            #  contredit finit par ne plus être lu du tout.
            gele = bool(rap.get("suivi_muet"))
            if gele:
                items.append(v2_divider())
                items.append(v2_body(
                    "🛑 **Aucune action possible tant que le suivi ne capte rien.**\n"
                    "-# Écrivez un message, passez en vocal, mettez une réaction, "
                    "puis rouvrez cet écran : les compteurs ci-dessus doivent bouger."))
            elif expulsables:
                lignes = [f"• {f['member'].mention} — `{f['jours']}` j"
                          for f in expulsables[:15]]
                if len(expulsables) > 15:
                    lignes.append(f"-# … et {len(expulsables) - 15} autre(s)")
                items.append(v2_divider())
                items.append(v2_title("🚪 Proposés à l'expulsion", level=3))
                items.append(v2_body("\n".join(lignes)))
                items.append(v2_body(
                    f"-# ⚠️ Action irréversible. Le bot ne l'exécutera JAMAIS seul : "
                    f"ce bouton est le seul chemin, et il n'en traite que "
                    f"`{activite.PLAFOND_ACTIONS_PAR_PASSAGE}` par clic."))

            b_maj = Button(label="Recalculer", emoji="🔄",
                           style=discord.ButtonStyle.secondary, custom_id="act_ap_maj")
            b_maj.callback = self._cb_recalculer
            b_rearm = Button(label="Réarmer l'observation", emoji="🕐",
                             style=discord.ButtonStyle.secondary,
                             custom_id="act_ap_rearm")
            b_rearm.callback = self._cb_rearmer
            ligne = [b_maj, b_rearm]
            if expulsables and not gele:
                lot = min(len(expulsables), activite.PLAFOND_ACTIONS_PAR_PASSAGE)
                b_kick = Button(
                    label=(f"Expulser {lot}" if lot == len(expulsables)
                           else f"Expulser {lot} sur {len(expulsables)}"),
                    emoji="🚪",
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

    async def _cb_rearmer(self, i):
        """Repart de zéro sur l'observation : plus personne n'est en retard.

        Le seul geste du système qui va dans le sens de la CLÉMENCE — il ne
        peut que retarder une sanction, jamais l'avancer. C'est pour ça qu'il
        n'exige pas de confirmation, contrairement à l'expulsion.

        Utile après un changement de seuils, une migration de base, ou une
        longue coupure du bot : dans tous ces cas le compteur ne reflète plus
        ce qui a réellement été observé.
        """
        try:
            if not i.response.is_done():
                await i.response.defer()
            jour = cal.jour()
            await _db_set(self.g.id, "activite_observe_depuis", jour)
            await i.followup.send(
                f"🕐 Observation réarmée au `{jour}`. Le silence de chacun "
                f"repart de 0 : aucune absence antérieure ne sera reprochée.",
                ephemeral=True)
            await self.render_to(i, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "réarmement")

    async def _cb_expulser(self, i):
        """Expulse les membres proposés. SEUL chemin d'expulsion du système."""
        try:
            if not i.response.is_done():
                await i.response.defer()
            #  Recalcul JUSTE AVANT d'agir : la liste affichée peut dater de
            #  plusieurs minutes, et quelqu'un a pu revenir entre-temps.
            rap = await passage.passage(self.g, dry_run=True)
            if rap.get("suivi_muet"):
                return await i.followup.send(
                    f"🛑 {rap['raison']}", ephemeral=True)

            faits, echecs, epargnes = 0, 0, 0
            cfg_act = await activite.config(self.g.id)
            #  PAR LOTS. Un clic ne doit pas pouvoir vider neuf cents membres :
            #  même validée par un humain, une action irréversible de cette
            #  taille se déclenche par erreur bien plus souvent qu'à dessein.
            tous = (rap.get("fiches") or {}).get("expulsion", [])
            lot = tous[:activite.PLAFOND_ACTIONS_PAR_PASSAGE]
            restants = len(tous) - len(lot)
            for f in lot:
                m = f["member"]
                #  Dernière vérification d'immunité avant l'irréversible.
                if not await activite.membre_concerne(m, cfg_act):
                    epargnes += 1
                    continue
                try:
                    #  La trace est écrite AVANT l'expulsion. Après, le membre
                    #  n'est plus dans la guilde et le moindre échec ferait
                    #  perdre la raison de son départ — donc l'accueil différent
                    #  qu'on lui doit s'il revient un jour.
                    await activite.noter_expulsion(self.g.id, m.id, f["jours"])
                    await m.kick(reason=f"Inactif depuis {f['jours']} jours")
                    faits += 1
                except Exception as ex:
                    _log(f"[activite expulsion {m.id}] {ex}")
                    echecs += 1

            await i.followup.send(
                f"🚪 **{faits}** expulsé(s) · ❌ {echecs} échec(s) · "
                f"🛡️ {epargnes} épargné(s) (devenus intouchables)"
                + (f"\n⏳ `{restants}` restant(s) — recliquez pour le lot suivant."
                   if restants else ""), ephemeral=True)
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
