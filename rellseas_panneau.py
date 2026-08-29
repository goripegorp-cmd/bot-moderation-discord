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
#  ⚠️ La garde ne peut plus passer par le constructeur : la vue est
#  PERSISTANTE et partagée, elle est construite au boot sans contexte.
_autorise = None       # (interaction) -> bool

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


def setup(*, cfg, db_set, get_db=None, mesurer=None, marquer_suivi=None,
          autorise=None, log=None):
    global _cfg, _db_set, _log, _mesurer, _marquer_suivi, _autorise
    _cfg, _db_set = cfg, db_set
    _mesurer = mesurer
    _marquer_suivi = marquer_suivi
    _autorise = autorise
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


#  ═══════════════════════════════════════════════════════════════════════════
#  LE PANNEAU DE GESTION — PERSISTANT
#  ═══════════════════════════════════════════════════════════════════════════
#
#  ⚠️ POURQUOI CETTE CLASSE A ÉTÉ REFAITE LE 23/08/2026.
#  Plainte du propriétaire, capture à l'appui : « quand on interagit avec les
#  boutons, ça ne marche pas. Il nous met échec de l'interaction, on peut rien
#  faire dans ce menu ».
#
#  CAUSE, PROUVÉE DANS LE CODE DE discord.py 2.7.1 :
#  la vue n'était enregistrée nulle part. Elle naissait avec `timeout=600` et
#  ne vivait que dans la mémoire du processus. `ViewStore.dispatch_view`
#  (view.py:1076) cherche l'item, ne le trouve pas, et fait `return` — AUCUN
#  accusé de réception n'est envoyé. Discord attend trois secondes et affiche
#  « Échec de l'interaction ». Aucune ligne de journal, aucune trace.
#  Deux chemins y menaient : un redéploiement (le propriétaire en fait
#  plusieurs par jour) et les 600 secondes d'inactivité.
#
#  ⚠️ `timeout=None` NE SUFFIT PAS, ET C'EST CONTRE-INTUITIF.
#  `InteractionResponse.send_message` (interactions.py) contient :
#      if ephemeral and view.timeout is None:
#          view.timeout = 15 * 60.0
#  Toute vue ÉPHÉMÈRE se voit donc imposer quinze minutes. Seul
#  `bot.add_view(...)` — qui range la vue dans le créneau `message_id=None`,
#  jamais purgé — survit à un redémarrage.
#
#  CE QUE CELA IMPOSE : une vue enregistrée est UNE SEULE instance partagée par
#  tout le staff. Rien de personnel ne peut vivre sur `self` — la sélection de
#  l'un écraserait celle de l'autre. L'état est donc sorti de l'objet, dans des
#  dictionnaires de module indexés par (serveur, utilisateur).

#  La sélection en cours, par (guild_id, user_id). En mémoire : elle est perdue
#  au redémarrage, et le panneau le DIT au lieu de faire semblant.
_SELECTIONS: dict[tuple[int, int], list[int]] = {}
_DERNIER: dict[tuple[int, int], str] = {}
#  La dernière recherche, pour réafficher ses résultats après un clic.
_RECHERCHES: dict[tuple[int, int], tuple[str, list[int]]] = {}

#  Combien de résultats on montre au plus. Limite dure d'un Select Discord.
MAX_RESULTATS = 25


def _cle(i) -> tuple[int, int]:
    return (i.guild.id if i.guild else 0, i.user.id)


def _sel(i) -> list[int]:
    return _SELECTIONS.get(_cle(i), [])


def _poser(i, ids: list[int]) -> None:
    #  Dédoublonnage en gardant l'ordre : deux passes de recherche peuvent
    #  proposer la même personne, et la compter deux fois fausserait le compte
    #  affiché sur les boutons.
    vus, propre = set(), []
    for x in ids:
        if x not in vus:
            vus.add(x)
            propre.append(x)
    _SELECTIONS[_cle(i)] = propre


def _membres_du_salon(i) -> list:
    """Les membres qui voient le salon où la commande a été tapée.

    ⚠️ POURQUOI CE RACCOURCI EXISTE. Demande du propriétaire (24/08) : « si on
    exécute la commande dans un salon où il y a uniquement les joueurs affichés
    à droite […] par exemple si un jour crée un ticket et que dans le ticket on
    est 5, ça te permettra d'afficher aussi le membre qui a créé le ticket ».
    Dans un ticket, les gens concernés sont déjà là : les retrouver à la main
    dans un serveur de mille membres n'a aucun sens.

    Les tickets de ce bot sont des SALONS TEXTE avec permissions
    (`create_text_channel(..., overwrites=ow)`), donc `channel.members` rend
    exactement les participants.

    ⚠️ TROIS TYPES, TROIS COMPORTEMENTS — et un seul rend des `Member` :
      · `TextChannel.members`  → les membres qui PEUVENT VOIR le salon ;
      · `VoiceChannel.members` → ceux actuellement CONNECTÉS dedans ;
      · `Thread.members`       → des `ThreadMember`, PAS des `Member` : pas de
        `.display_name`, pas de `.bot`. On repasse donc par
        `guild.get_member` dans tous les cas.

    Rend `[]` si le salon est public : `channel.members` y vaut presque tout le
    serveur, et proposer neuf cents personnes ne rendrait service à personne.
    C'est ce plafond qui fait que le raccourci n'apparaît QUE là où il aide.
    """
    g, salon = i.guild, getattr(i, "channel", None)
    if g is None or salon is None:
        return []
    try:
        bruts = list(getattr(salon, "members", []) or [])
    except Exception:
        return []
    if not bruts or len(bruts) > MAX_RESULTATS:
        return []
    out = []
    for x in bruts:
        m = x if hasattr(x, "display_name") else g.get_member(getattr(x, "id", 0))
        if m is not None and not getattr(m, "bot", False):
            out.append(m)
    return out


def _sans_accents(s: str) -> str:
    """Pour que « rené » se trouve en tapant « rene ». Fonction pure."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                   if not unicodedata.combining(c)).casefold()


def _extraire_id(texte: str) -> int | None:
    """Un identifiant Discord, collé sous n'importe quelle forme.

    ⚠️ AJOUTÉ LE 24/08 À LA DEMANDE DU PROPRIÉTAIRE : « fais en sorte qu'on
    puisse mettre l'ID de l'utilisateur, que ce soit plus simple comme ça ».
    Un identifiant est EXACT — il ne dépend ni du pseudo affiché, ni des
    accents, ni du cache des membres. C'est le chemin qui marche toujours,
    et c'est pour ça qu'il est essayé EN PREMIER.

    Accepte `123456789012345678`, `<@123…>` et `<@!123…>` : on colle ce qu'on a
    sous la main, on ne nettoie pas à la main.
    """
    brut = str(texte or "").strip()
    for prefixe, suffixe in (("<@!", ">"), ("<@", ">")):
        if brut.startswith(prefixe) and brut.endswith(suffixe):
            brut = brut[len(prefixe):-len(suffixe)].strip()
            break
    if brut.isdigit() and 15 <= len(brut) <= 21:
        try:
            return int(brut)
        except Exception:
            return None
    return None


class _ChercheModal(discord.ui.Modal, title="Trouver un membre"):
    """Un identifiant, ou quelques lettres. La recherche est faite PAR LE BOT.

    ⚠️ DEUX CHEMINS, ET L'IDENTIFIANT PASSE EN PREMIER.
    Le propriétaire a signalé le 24/08 que la recherche par lettres « ne marche
    pas du tout » et a demandé de pouvoir coller un identifiant. Un identifiant
    ne dépend de rien : ni du pseudo, ni des accents, ni du cache. S'il est
    fourni, on l'utilise et on ne cherche pas.

    ⚠️ ET ON VA LE CHERCHER SUR DISCORD SI BESOIN. `guild.get_member` ne lit
    que le cache : un membre absent du cache serait « introuvable » alors qu'il
    existe. On retombe donc sur `fetch_member`, un appel réseau, qui tranche
    pour de bon.

    ⚠️ POURQUOI LA RECHERCHE PAR NOM EST FAITE CÔTÉ BOT. Le menu natif de
    Discord propose une liste de membres, mais rien dans la bibliothèque ni
    dans la documentation ne garantit qu'il cherche dans TOUT le serveur : on
    ne parie pas là-dessus. On balaie `guild.members` nous-mêmes, dans le
    pseudo du serveur, le nom global et le nom de compte, sans accents ni
    casse — et on rend des noms lisibles.
    """

    lettres = discord.ui.TextInput(
        label="Identifiant, ou quelques lettres du pseudo",
        placeholder="123456789012345678  —  ou bien : rell",
        min_length=2, max_length=60, required=True)

    async def on_submit(self, i: discord.Interaction):
        saisie = str(self.lettres.value).strip()
        k = _cle(i)
        g = i.guild

        #  ── 1. Un identifiant ? C'est exact, on ne cherche pas plus loin. ──
        uid = _extraire_id(saisie)
        if uid is not None:
            m = g.get_member(uid) if g else None
            if m is None and g is not None:
                #  Hors cache : on demande à Discord. C'est la différence entre
                #  « introuvable » et « pas encore chargé ».
                try:
                    m = await g.fetch_member(uid)
                except Exception as ex:
                    _log(f"[rellseas recherche id {uid}] {type(ex).__name__}: {ex}")
                    m = None
            if m is None:
                _RECHERCHES.pop(k, None)
                _DERNIER[k] = (
                    f"🔎 Aucun membre avec l'identifiant `{uid}` sur ce serveur.\n"
                    f"-# Vérifiez l'identifiant, ou collez la mention du membre.")
            else:
                ids = list(_sel(i))
                if m.id not in ids:
                    ids.append(m.id)
                _poser(i, ids)
                _RECHERCHES.pop(k, None)
                _DERNIER[k] = (f"✅ {m.mention} ajouté à la sélection "
                               f"(`{len(ids)}` au total).")
            return await self._rendre(i)

        #  ── 2. Sinon, recherche par lettres. ──
        besoin = _sans_accents(saisie)
        trouves = []
        for m in (g.members if g else []):
            if m.bot:
                continue
            for champ in (m.display_name, getattr(m, "global_name", None), m.name):
                if champ and besoin in _sans_accents(champ):
                    trouves.append(m.id)
                    break
            if len(trouves) >= MAX_RESULTATS:
                break
        _RECHERCHES[k] = (saisie, trouves)
        #  ⚠️ ON DIT COMBIEN DE MEMBRES ONT ÉTÉ FOUILLÉS. Un serveur dont le
        #  cache est vide rendrait « aucun résultat » pour TOUT — et on
        #  chercherait la panne dans la recherche au lieu du cache.
        vus = len(g.members) if g else 0
        _log(f"[rellseas recherche] « {saisie} » → {len(trouves)} sur {vus} membres")
        if not trouves:
            _DERNIER[k] = (
                f"🔎 Aucun membre ne correspond à « {saisie} » "
                f"(`{vus}` membres fouillés).\n"
                f"-# Essayez moins de lettres, ou **collez son identifiant** — "
                f"c'est le chemin le plus sûr.")
        return await self._rendre(i)

    async def _rendre(self, i: discord.Interaction):
        """Réaffiche le panneau. ⚠️ Avec un repli : une soumission de modale
        n'a pas toujours le droit d'éditer le message d'origine, et un échec
        silencieux ici donnerait l'impression que la recherche « ne fait
        rien » — exactement la plainte du 24/08."""
        try:
            await RellseasGestionV2().render_to(i, edit=True)
        except Exception as ex:
            _log(f"[rellseas recherche rendu] {type(ex).__name__}: {ex}")
            try:
                await i.followup.send(
                    _DERNIER.get(_cle(i))
                    or "🔎 Recherche effectuée — rouvrez le panneau pour voir "
                       "le résultat.", ephemeral=True)
            except Exception:
                pass

    async def on_error(self, i: discord.Interaction, ex: Exception):
        #  Une modale a son propre filet : sans lui, une erreur ici laisse
        #  l'utilisateur devant un formulaire figé, sans un mot.
        _log(f"[rellseas recherche] {type(ex).__name__}: {ex}")
        try:
            envoi = (i.followup.send if i.response.is_done()
                     else i.response.send_message)
            await envoi(f"❌ La recherche a échoué (`{type(ex).__name__}`).\n"
                        f"-# Réessayez, ou collez directement l'identifiant du "
                        f"membre.", ephemeral=True)
        except Exception:
            pass


class RellseasGestionV2(LayoutView):
    """Donner, retirer, examiner — par lots. VUE PERSISTANTE.

    ⚠️ AUCUN ÉTAT SUR `self`. Voir l'en-tête de section : l'instance
    enregistrée au démarrage est partagée par tout le staff. Serveur et
    utilisateur se lisent dans l'interaction, la sélection dans `_SELECTIONS`.
    """

    def __init__(self):
        #  `timeout=None` + `bot.add_view` : le seul couple qui survit à un
        #  redéploiement. Voir l'en-tête.
        super().__init__(timeout=None)

    @classmethod
    def squelette(cls) -> "RellseasGestionV2":
        """L'instance enregistrée au boot, avec les custom_id FIXES.

        `bot.add_view` ne peut inscrire que les composants présents à l'instant
        de l'appel : ce squelette les porte tous, sans état ni `disabled`.
        """
        v = cls()
        sel = UserSelect(placeholder="Choisir des membres…",
                         min_values=0, max_values=MAX_MEMBRES,
                         custom_id="rellseas_membres")
        sel.callback = v._cb_membres
        res = discord.ui.Select(placeholder="Résultats…",
                                options=[discord.SelectOption(label="—", value="0")],
                                custom_id="rellseas_resultats")
        res.callback = v._cb_resultat
        #  ⚠️ SANS CETTE INSCRIPTION, LE RACCOURCI « CE SALON » EST MUET.
        #  `add_view` n'enregistre que les composants présents à cet instant :
        #  un custom_id absent du squelette ne sera jamais capté après un
        #  redéploiement — le défaut même qu'on vient de corriger.
        ici = discord.ui.Select(placeholder="Ce salon…",
                                options=[discord.SelectOption(label="—", value="0")],
                                custom_id="rellseas_salon")
        ici.callback = v._cb_salon
        boutons = []
        for cid, cb in (("rellseas_g_chercher", v._cb_chercher),
                        ("rellseas_g_donner", v._cb_donner),
                        ("rellseas_g_retirer", v._cb_retirer),
                        ("rellseas_g_activite", v._cb_activite),
                        ("rellseas_g_vider", v._cb_vider)):
            b = Button(label="—", custom_id=cid)
            b.callback = cb
            boutons.append(b)
        v.add_item(v2_container(discord.ui.ActionRow(sel),
                                discord.ui.ActionRow(ici),
                                discord.ui.ActionRow(res),
                                discord.ui.ActionRow(*boutons),
                                color=Palette.INFO))
        return v

    async def interaction_check(self, i) -> bool:
        """⚠️ ON RÉPOND TOUJOURS AVANT DE REFUSER.

        `View._scheduled_task` fait `if not allow: return` sans rien envoyer, et
        n'appelle PAS `on_error` : un refus muet produit littéralement « Échec
        de l'interaction ». C'était l'un des chemins du défaut du 23/08.

        Il n'y a plus de test d'identité : la vue est partagée, et le message
        est éphémère — seul celui qui a tapé la commande le voit.
        """
        if _autorise is None:
            return True
        try:
            if await _autorise(i):
                return True
        except Exception as ex:
            _log(f"[RellseasGestionV2 garde] {ex}")
        try:
            await i.response.send_message(
                "❌ Vous n'avez plus la permission d'utiliser ce panneau.\n"
                "-# Elle se règle dans `/configure` → 🎭 Rellseas.",
                ephemeral=True)
        except Exception:
            pass
        return False

    # ─────────────────────────────────────────────────────────────────────────
    #  Rendu
    # ─────────────────────────────────────────────────────────────────────────

    async def render_to(self, i, *, edit: bool = True):
        g, k = i.guild, _cle(i)
        c = await _cfg(g.id)
        role = g.get_role(int(c.get(CLE_ROLE_CIBLE, 0) or 0))
        ids = _SELECTIONS.get(k, [])
        choisis = [m for m in (g.get_member(x) for x in ids) if m is not None]
        n = len(choisis)

        items = [
            v2_title("🎭 Rellseas · Gestion du rôle"),
            v2_subtitle("Donner ou retirer le rôle à plusieurs membres d'un coup"),
            v2_divider(),
        ]

        if role is None:
            items.append(v2_body(
                "🔴 **Aucun rôle n'est réglé.**\n"
                "-# `/configure` → 🎭 Rellseas → « Rôle attribué ». Tant qu'il "
                "manque, donner et retirer sont impossibles."))
        else:
            items.append(v2_body(
                f"**Rôle donné par ce panneau** · {role.mention}\n"
                f"-# `{len(getattr(role, 'members', []) or [])}` membre(s) le "
                f"portent · se change dans `/configure` → 🎭 Rellseas"))

        items.append(v2_divider())

        if choisis:
            apercu = " ".join(m.mention for m in choisis[:10])
            if n > 10:
                apercu += f" -# … et {n - 10} autre(s)"
            items.append(v2_body(f"**Sélection** · `{n}` membre(s)\n{apercu}"))
            if n > MAX_MEMBRES:
                #  ⚠️ ON LE DIT. Au-delà de 25, les suivants ne sont plus dans
                #  le menu : les décocher paraîtrait sans effet.
                items.append(v2_body(
                    f"-# Les `{MAX_MEMBRES}` premiers sont dans le menu "
                    f"ci-dessous. Pour tout enlever d'un coup : 🧹."))
        else:
            items.append(v2_body(
                "**Sélection** · ⚪ _aucun membre_\n"
                "-# Ouvrez le menu ci-dessous, **ou** cliquez 🔎 et tapez "
                "quelques lettres d'un pseudo."))

        dernier = _DERNIER.get(k)
        if dernier:
            items.append(v2_divider())
            items.append(v2_body(dernier))

        items.append(v2_divider())

        sel = UserSelect(
            placeholder=f"Choisir des membres — {MAX_MEMBRES} par passe…",
            min_values=0, max_values=MAX_MEMBRES,
            custom_id="rellseas_membres",
            #  ⚠️ SANS `default_values`, LE CUMUL EST IMPOSSIBLE. Le client
            #  renvoie UNIQUEMENT ce qui est coché dans le menu : un menu
            #  rouvert vide écrasait la sélection précédente. C'est la cause
            #  exacte de « au lieu d'ajouter un par un ».
            #  ⚠️ TRONQUÉ À 25 : au-delà, Discord refuse le message entier
            #  (HTTP 400) et le panneau ne s'affiche plus du tout.
            default_values=[discord.Object(id=x) for x in ids[:MAX_MEMBRES]])
        sel.callback = self._cb_membres
        lignes = [discord.ui.ActionRow(sel)]

        #  ⚠️ LE RACCOURCI « CE SALON » — demandé le 24/08. Dans un ticket, les
        #  gens concernés sont déjà là : les retrouver à la main dans un
        #  serveur de mille membres n'a aucun sens. Il n'apparaît QUE si le
        #  salon a peu de monde (voir `_membres_du_salon`), donc jamais dans un
        #  salon public où il listerait tout le serveur.
        ici = _membres_du_salon(i)
        if ici:
            opts = [discord.SelectOption(
                label=m.display_name[:100], description=f"@{m.name}"[:100],
                value=str(m.id), emoji="✅" if m.id in ids else None)
                for m in ici[:MAX_RESULTATS]]
            s_ici = discord.ui.Select(
                placeholder=(f"👥 Les {len(opts)} membres de ce salon — "
                             f"cliquez pour ajouter ou retirer"),
                options=opts, min_values=1, max_values=1,
                custom_id="rellseas_salon")
            s_ici.callback = self._cb_salon
            lignes.append(discord.ui.ActionRow(s_ici))

        recherche = _RECHERCHES.get(k)
        if recherche and recherche[1]:
            mots, trouves = recherche
            options = []
            for uid in trouves[:MAX_RESULTATS]:
                m = g.get_member(uid)
                if m is None:
                    continue
                deja = uid in ids
                options.append(discord.SelectOption(
                    label=m.display_name[:100],
                    description=f"@{m.name}"[:100],
                    value=str(uid),
                    emoji="✅" if deja else None))
            if options:
                res = discord.ui.Select(
                    placeholder=(f"{len(options)} trouvé(s) pour « {mots} » — "
                                 f"cliquez pour ajouter ou retirer"),
                    options=options, min_values=1, max_values=1,
                    custom_id="rellseas_resultats")
                res.callback = self._cb_resultat
                lignes.append(discord.ui.ActionRow(res))

        pret = bool(choisis) and role is not None
        b_chercher = Button(label="Chercher un membre", emoji="🔎",
                            style=discord.ButtonStyle.secondary,
                            custom_id="rellseas_g_chercher")
        b_chercher.callback = self._cb_chercher
        b_donner = Button(
            label=(f"Donner le rôle à {n}" if pret else "Donner le rôle"),
            emoji="✅", style=discord.ButtonStyle.success,
            disabled=not pret, custom_id="rellseas_g_donner")
        b_donner.callback = self._cb_donner
        b_retirer = Button(
            label=(f"Retirer le rôle à {n}" if pret else "Retirer le rôle"),
            emoji="🚫", style=discord.ButtonStyle.danger,
            disabled=not pret, custom_id="rellseas_g_retirer")
        b_retirer.callback = self._cb_retirer
        b_activite = Button(
            label=(f"Activité 7 j de {n}" if choisis else "Activité 7 jours"),
            emoji="📊", style=discord.ButtonStyle.primary,
            disabled=not choisis, custom_id="rellseas_g_activite")
        b_activite.callback = self._cb_activite
        b_vider = Button(label="Tout désélectionner", emoji="🧹",
                         style=discord.ButtonStyle.secondary,
                         disabled=not choisis, custom_id="rellseas_g_vider")
        b_vider.callback = self._cb_vider
        lignes.append(discord.ui.ActionRow(
            b_chercher, b_donner, b_retirer, b_activite, b_vider))

        items += lignes
        self.clear_items()
        self.add_item(v2_container(*items, color=Palette.INFO))

        if not edit:
            return await i.response.send_message(view=self, ephemeral=True)
        if i.response.is_done():
            await i.edit_original_response(content=None, view=self,
                                           embed=None, attachments=[])
        else:
            await i.response.edit_message(content=None, view=self,
                                          embed=None, attachments=[])

    # ─────────────────────────────────────────────────────────────────────────
    #  Callbacks
    #
    #  ⚠️ AUCUN `except` MUET ICI. L'ancienne version enveloppait chaque
    #  callback dans un `try/except` qui se contentait de journaliser : elle
    #  court-circuitait le filet `on_error` d'ui_v2, qui répond « ⚠️ Un souci
    #  est survenu », et transformait chaque incident en bouton muet de plus.
    # ─────────────────────────────────────────────────────────────────────────

    async def _cb_membres(self, i):
        """⚠️ ON FUSIONNE, ON N'ÉCRASE PAS. Le client ne renvoie que ce qui est
        coché dans le menu ; les membres au-delà des 25 affichés n'y sont pas
        et seraient perdus à chaque passe."""
        choisis = [int(v) for v in (i.data.get("values") or [])]
        hors_menu = _sel(i)[MAX_MEMBRES:]
        _poser(i, choisis + [x for x in hors_menu if x not in choisis])
        _DERNIER.pop(_cle(i), None)
        await RellseasGestionV2().render_to(i, edit=True)

    async def _cb_resultat(self, i):
        """Un résultat de recherche : on l'ajoute, ou on l'enlève s'il y est."""
        await self._basculer(i, int((i.data.get("values") or ["0"])[0]))

    async def _cb_salon(self, i):
        """Un membre du salon courant : on l'ajoute, ou on l'enlève s'il y est."""
        await self._basculer(i, int((i.data.get("values") or ["0"])[0]))

    async def _basculer(self, i, uid: int):
        ids = list(_sel(i))
        if uid in ids:
            ids.remove(uid)
        else:
            ids.append(uid)
        _poser(i, ids)
        _DERNIER.pop(_cle(i), None)
        await RellseasGestionV2().render_to(i, edit=True)

    async def _cb_chercher(self, i):
        await i.response.send_modal(_ChercheModal())

    async def _cb_vider(self, i):
        _SELECTIONS.pop(_cle(i), None)
        _RECHERCHES.pop(_cle(i), None)
        _DERNIER.pop(_cle(i), None)
        await RellseasGestionV2().render_to(i, edit=True)

    async def _role_utilisable(self, g, c: dict):
        """Le rôle cible, et si le bot peut réellement le manipuler.

        Rendre `(role, raison)` : `raison` non vide = on ne tente RIEN. Vérifier
        AVANT le lot évite 25 refus identiques et un compte-rendu illisible.
        """
        role = g.get_role(int(c.get(CLE_ROLE_CIBLE, 0) or 0))
        if role is None:
            return None, ("Aucun rôle Rellseas réglé — `/configure` → "
                          "🎭 Rellseas.")
        moi = g.me
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
        g, u, k = i.guild, i.user, _cle(i)
        c = await _cfg(g.id)
        role, raison = await self._role_utilisable(g, c)
        if raison:
            _DERNIER[k] = f"🔴 **Rien n'a été fait.** {raison}"
            return await RellseasGestionV2().render_to(i, edit=True)

        faits, echecs = [], []
        for uid in _SELECTIONS.get(k, []):
            m = g.get_member(uid)
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
                await geste(role, reason=f"/rellseas par {u} ({u.id})")
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
                    await _marquer_suivi(g.id, m.id)
                except Exception as ex:
                    _log(f"[rellseas suivi {uid}] {ex}")

        verbe = "donné" if donner else "retiré"
        _DERNIER[k] = _bilan(f"**Rôle {verbe}** · {role.mention}", faits, echecs)
        await self._journal(
            g, f"🎭 **Rôle {verbe}** · `{len(faits)}` membre(s) "
               f"par {u.mention}" + (f" — {' '.join(faits)}" if faits else ""))
        #  La sélection est conservée : enchaîner « donner » puis « vérifier »
        #  sur le même lot est le geste courant.
        await RellseasGestionV2().render_to(i, edit=True)

    async def _cb_donner(self, i):
        await self._agir(i, donner=True)

    async def _cb_retirer(self, i):
        await self._agir(i, donner=False)

    async def _cb_activite(self, i):
        """L'activité de tout le lot, mesurée par le système d'activité.

        ⚠️ AUCUN COMPTEUR ICI. `_mesurer` appelle `activite.presence()` sur une
        fenêtre d'une semaine. Un second compteur avait déjà été écrit puis
        retiré le 12/08 : il faisait doublon et mentait.
        """
        await i.response.defer()
        g, k = i.guild, _cle(i)
        if _mesurer is None:
            _DERNIER[k] = "🔴 La mesure d'activité n'est pas branchée."
            return await RellseasGestionV2().render_to(i, edit=True)

        lignes = []
        for uid in _SELECTIONS.get(k, []):
            m = g.get_member(uid)
            if m is None:
                lignes.append(f"❔ `{uid}` — membre introuvable")
                continue
            try:
                mes = await _mesurer(g.id, m)
            except Exception as ex:
                _log(f"[rellseas activite {uid}] {ex}")
                lignes.append(f"❔ {m.mention} — mesure impossible")
                continue
            lignes.append(f"{_etiquette_activite(mes)} {m.mention}")

        _DERNIER[k] = (
            "**Activité sur les 7 derniers jours** · lecture seule, personne "
            "n'est prévenu\n" + "\n".join(lignes)
            + "\n-# 🟢 actif · 🟠 peu présent · 🔴 absent · ⚪ pas assez de "
              "recul pour juger\n"
              "-# Mesuré par le système d'activité du serveur — aucun "
              "compteur séparé.")
        await RellseasGestionV2().render_to(i, edit=True)

    async def _journal(self, g, texte: str) -> None:
        """Trace nominative. Fail-open : jamais bloquant."""
        try:
            c = await _cfg(g.id)
            salon = g.get_channel(int(c.get(CLE_SALON_LOG, 0) or 0))
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
