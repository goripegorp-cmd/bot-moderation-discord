"""roblox_panneau.py — L'onglet Roblox de /configure, et la publication des fiches.

Components V2 de bout en bout (voir `UI.md`) : aucun embed, selects natifs typés,
toggles dont le libellé ET le style reflètent l'ÉTAT, bouton Retour partout.

═══════════════════════════════════════════════════════════════════════════════
LA FICHE EST UN QUADRILLAGE, PAS UN PAVÉ
═══════════════════════════════════════════════════════════════════════════════
Exigence du propriétaire. Chaque publication suit le MÊME ordre, et un champ
inconnu s'affiche `—` au lieu de disparaître : une fiche à géométrie variable ne
se lit plus en diagonale, et c'est tout l'intérêt du quadrillage.

═══════════════════════════════════════════════════════════════════════════════
PUBLICATION PAR WEBHOOK
═══════════════════════════════════════════════════════════════════════════════
Demandé explicitement. Le webhook porte un nom et un avatar propres au flux :
on voit d'où vient la fiche sans lire une ligne. Repli sur un envoi normal si le
bot n'a pas la permission de gérer les webhooks — un flux ne doit pas se taire
pour un défaut de droits.
"""
from __future__ import annotations


import discord
from discord.ui import Button, ChannelSelect

import roblox_news as news
import roblox_pings as pings
from ui_v2 import (
    LayoutView, Palette, body as v2_body, container as v2_container,
    divider as v2_divider, subtitle as v2_subtitle, title as v2_title,
)

_db_set = None
_webhook_send = None
#  Pour COMPLÉTER une fiche déjà publiée (cartes cadeaux) au lieu d'en poster
#  une nouvelle. Même profil de webhook que l'envoi : un message se modifie
#  par le webhook qui l'a posté.
_webhook_edit = None
_log = print


def setup(*, db_set, webhook_send=None, webhook_edit=None, log=None):
    global _db_set, _webhook_send, _webhook_edit, _log
    _db_set = db_set
    _webhook_send = webhook_send
    _webhook_edit = webhook_edit
    if log is not None:
        _log = log


# ═══════════════════════════════════════════════════════════════════════════════
#  La fiche
# ═══════════════════════════════════════════════════════════════════════════════

def _ou_tiret(v) -> str:
    """Un champ inconnu s'affiche `—`. Il ne disparaît JAMAIS de la fiche."""
    if v is None or v == "":
        return "—"
    return str(v)


def _bouton_ping(cle: str | None):
    """Le bouton d'abonnement aux notifications de cette catégorie.

    ⚠️ SON LIBELLÉ EST NEUTRE, ET C'EST VOULU. Un message est le MÊME pour tout
    le monde : la moitié du salon a déjà le rôle, l'autre non. Un bouton
    « S'abonner » mentirait à ceux qui sont déjà abonnés, et « Se désabonner »
    aux autres. On dit donc ce que fait le clic — il bascule — et la réponse
    ÉPHÉMÈRE annonce l'état réel de celui qui a cliqué. C'est la règle
    « aucun bouton qui ment » (UI.md), appliquée à un cas où l'état n'est pas
    partagé.

    ⚠️ LE BOUTON EST POSÉ MÊME SANS RÔLE EXISTANT : si le bot manque de la
    permission « Gérer les rôles », le clic le DIT au membre. Cacher le bouton
    laisserait croire que la fonction n'existe pas.
    """
    if not cle or cle not in pings.CATEGORIES:
        return None
    return Button(label="Me prévenir · arrêter", emoji="🔔",
                  style=discord.ButtonStyle.secondary,
                  custom_id=pings.custom_id(cle))


def _ligne_mention(ping_role) -> str | None:
    """La ligne discrète qui porte le vrai ping. `None` s'il n'y a pas de rôle
    — on n'écrit JAMAIS un faux « @rôle » en texte : ça ne notifie personne et
    ça donne l'illusion du contraire."""
    m = pings.mention(ping_role)
    return f"-# 🔔 {m}" if m else None


def _autorisation_mention(ping_role):
    """⚠️ SANS CECI, LE PING NE PART PAS. Les rôles de notification sont créés
    `mentionable=False` — un membre ne doit pas pouvoir s'en servir pour
    réveiller tout le serveur. La contrepartie est que le bot doit autoriser
    EXPLICITEMENT ce rôle-là à chaque envoi : `everyone` et `users` restent
    fermés, seul le rôle concerné passe.

    Écrire `<@&id>` sans cette autorisation afficherait une jolie pastille de
    rôle qui ne notifierait personne — le genre d'échec qu'on ne voit pas."""
    try:
        import discord as _d
        if ping_role is None:
            return _d.AllowedMentions.none()
        return _d.AllowedMentions(everyone=False, users=False, roles=[ping_role])
    except Exception:
        return None


async def _envoyer(salon, profil: str, vue: LayoutView, etiquette: str,
                   ping_role=None, trace: dict | None = None) -> bool:
    """L'envoi réel. Rend `True` UNIQUEMENT si un message est parti.

    ⚠️ PIÈGE À NE PAS DÉFAIRE — LE RETOUR DE `webhook_send` COMPTE.
    `webhook_send` (bot.py) n'a AUCUN chemin qui lève : elle attrape Forbidden,
    HTTPException et tout le reste, journalise, tente son propre repli
    `channel.send`, et rend `None` quand plus rien n'est possible. La version
    précédente appelait donc `await _webhook_send(...)` puis rendait `True` sans
    regarder — ce qui produisait DEUX mensonges :

      · le bouton « Relever maintenant » annonçait « 3 fiches publiées » alors
        que le salon n'avait rien reçu (permission manquante, par exemple) ;
      · pire, l'appelant enchaînait sur `marquer_publie()`, et l'article était
        marqué SORTI POUR TOUJOURS sans jamais avoir été vu.

    `None` ⇔ rien n'est parti : avec `wait=True` un webhook rend un
    `WebhookMessage`, et le repli `channel.send` rend un `Message`.
    Pas de nouvelle tentative ici quand elle rend `None` : `webhook_send` a
    déjà essayé `channel.send` de son côté, la refaire échouerait pareil.
    """
    try:
        if _webhook_send is not None:
            #  ⚠️ `webhook_send` n'accepte PAS de `username` — sa signature est
            #  (channel, platform, embed, content, file, files, embeds, view).
            #  La premiere version le lui passait : chaque publication levait un
            #  TypeError, tombait dans le repli, et le webhook n'etait JAMAIS
            #  utilise alors que c'etait la demande. Le nom vient donc du profil
            #  declare dans WEBHOOK_PROFILES, choisi par la CLE de plateforme.
            res = await _webhook_send(salon, profil, view=vue,
                                      allowed_mentions=_autorisation_mention(ping_role))
            if res is None:
                _log(f"[roblox {etiquette}] webhook_send a rendu None — RIEN "
                     f"n'est parti dans #{getattr(salon, 'name', '?')} "
                     f"({getattr(salon, 'id', '?')}). Cause journalisée par "
                     f"[webhook_send] juste au-dessus.")
                return False
            #  ⚠️ LE TYPE DE RETOUR NE CHANGE PAS. Deux tests exigent
            #  `is False` sur les chemins d'échec, et tous les appelants font
            #  `if await publier(...)`. L'identifiant du message — que la
            #  spécification du 30/08 demande d'enregistrer pour la file
            #  d'attente — voyage donc par ce dictionnaire, pas par le retour.
            if trace is not None:
                trace["message_id"] = getattr(res, "id", None)
            return True
        _msg = await salon.send(
            view=vue, allowed_mentions=_autorisation_mention(ping_role))
        if trace is not None:
            trace["message_id"] = getattr(_msg, "id", None)
        return True
    except Exception as ex:
        #  Repli : un défaut de webhook ne doit pas faire taire le flux.
        _log(f"[roblox {etiquette} webhook] {ex}")
        try:
            _m2 = await salon.send(view=vue)
            if trace is not None:
                trace["message_id"] = getattr(_m2, "id", None)
            return True
        except Exception as ex2:
            _log(f"[roblox {etiquette}] {ex2}")
            return False


#  ⚠️ LIMITE DURE : 4 000 caractères de texte au total dans un message V2
#  (somme de tous les TextDisplay). Dépasser = HTTP 400, la fiche ne part pas.
#  On calcule, on ne coupe pas au hasard.
BUDGET_TEXTE_ACTU = 3900
#  Part réservée aux méta (titre, en-tête, mention, date). Le reste va aux
#  corps, français d'abord.
RESERVE_META = 500

#  ⚠️ L'ESSENTIEL, PAS LE BILLET. Retour du propriétaire (18/08) sur la
#  première version : « tu mets énormément d'informations, ça fait des très
#  très gros pavés ». Elle affichait jusqu'à 2 300 caractères de français et
#  900 d'anglais — 3 250 au total, mesuré. Une fiche se lit en dix secondes ;
#  le bouton « Lire l'article complet » mène au forum pour tout le reste, et
#  c'est ce que le propriétaire veut : « quand l'utilisateur clique dessus, il
#  va sur devforum, il aura toutes les informations ».
#  Les « Key Takeaways » de Roblox font 250 à 400 caractères : 800 laisse la
#  place aux points clés ET à une phrase d'intro. 400 d'original suffisent à
#  vérifier la traduction, pas à relire.
BUDGET_FR_AFFICHE = 800
BUDGET_ORIGINAL = 400

#  Une couleur et une pastille par domaine : on reconnaît le genre de nouvelle
#  avant de lire — c'était la force de l'ancienne fiche (« 🟢 »).
STYLE_DOMAINE = {
    "Annonces":               ("🟢", Palette.SUCCESS,  "MISE À JOUR"),
    "Studio & moteur":        ("🔵", Palette.INFO,     "STUDIO & MOTEUR"),
    "Politique & sécurité":   ("🔴", Palette.DANGER,   "POLITIQUE & SÉCURITÉ"),
    "Événements":             ("🟣", Palette.ACCENT,   "ÉVÉNEMENT"),
    "Développeurs":           ("🟠", Palette.WARNING,  "DÉVELOPPEURS"),
    "Communiqués officiels":  ("⚪", Palette.NEUTRAL,  "COMMUNIQUÉ OFFICIEL"),
    "Newsroom Roblox":        ("🟡", Palette.PREMIUM,  "NEWSROOM"),
    "Salle de presse (FR)":   ("🟡", Palette.PREMIUM,  "SALLE DE PRESSE"),
}


def _horodatage(iso, style: str = "f") -> str:
    """`<t:UNIX:f>` — Discord l'affiche dans le fuseau du LECTEUR.

    L'ancienne fiche écrivait « 04/08/2026 18:11 » en dur : juste pour un
    lecteur, faux pour tous les autres. Une date illisible rend « — ».
    `style="R"` : « il y a 12 minutes », qui se met à jour tout seul.
    """
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return f"<t:{int(d.timestamp())}:{style}>"
    except Exception:
        return "—"


def _tronquer_propre(texte: str, budget: int) -> str:
    """Coupe à une frontière de paragraphe, sinon de phrase — jamais au milieu
    d'un mot. Une fiche tronquée en pleine phrase se lit comme un défaut."""
    t = (texte or "").strip()
    if len(t) <= budget:
        return t
    coupe = t[:budget]
    for sep in ("\n\n", ". ", "! ", "? ", "\n"):
        i = coupe.rfind(sep)
        if i > budget // 2:
            return coupe[:i + (1 if sep.strip() else 0)].rstrip() + " …"
    return coupe.rsplit(" ", 1)[0].rstrip() + " …"


def construire_actu(billet: dict, ping_cle: str | None = None,
                    ping_role=None) -> LayoutView:
    """La fiche d'une actualité : français d'abord, l'original ensuite, les
    médias, la date, le lien. Complète, ou elle ne part pas.

    Structure (ordre fixe, on la lit en diagonale) :
      EN-TÊTE       MISE À JOUR · domaine
      TITRE         🟢 titre en français
      CORPS FR      l'essentiel, traduit — ou écrit en français par Roblox
      ORIGINAL      🇬🇧 titre + début du texte anglais (si traduit)
      MÉDIAS        galerie (images pleine taille, vidéos du forum) · boutons YouTube
      PIED          mention de traduction · date native · lien complet
    """
    lien = billet.get("lien") or news.lien_billet(billet.get("topic_id"))
    domaine = _ou_tiret(billet.get("domaine"))
    pastille, couleur, etiquette = STYLE_DOMAINE.get(
        domaine, ("📢", Palette.PRIMARY, "ACTUALITÉ"))

    langue = billet.get("langue") or "en"
    traduit_par = billet.get("traduit_par")
    titre_orig = _ou_tiret(billet.get("titre"))
    corps_orig = (billet.get("corps") or billet.get("extrait") or "").strip()

    if langue == "fr":
        titre_fr, corps_fr, montrer_original = titre_orig, corps_orig, False
    elif traduit_par and billet.get("corps_fr"):
        titre_fr = billet.get("titre_fr") or titre_orig
        corps_fr = billet["corps_fr"]
        montrer_original = True
    else:
        #  Traduction indisponible : l'original tient lieu de corps, et la
        #  mention le DIT. On ne tait pas une actualité pour ça.
        titre_fr, corps_fr, montrer_original = titre_orig, corps_orig, False

    # ── Le budget de texte, calculé ────────────────────────────────────────
    disponible = BUDGET_TEXTE_ACTU - RESERVE_META - len(titre_fr) - len(titre_orig)
    #  Le plafond dur (4 000) reste une garde ; la lisibilité impose des budgets
    #  bien plus bas — voir BUDGET_FR_AFFICHE / BUDGET_ORIGINAL.
    budget_fr = min(BUDGET_FR_AFFICHE, max(300, disponible))
    budget_orig = min(BUDGET_ORIGINAL, max(200, disponible - budget_fr)) if montrer_original else 0
    corps_fr = _tronquer_propre(corps_fr, budget_fr)
    corps_orig_court = _tronquer_propre(corps_orig, budget_orig) if montrer_original else ""

    items = [
        v2_title(f"{etiquette} · {domaine}", level=3),
        v2_body(f"## {pastille} {titre_fr}"),
    ]
    if corps_fr:
        items.append(v2_body(corps_fr))
    else:
        items.append(v2_body("-# _Le corps de ce billet n'a pas pu être lu — "
                             "voir l'article complet._"))

    if montrer_original and corps_orig_court:
        items.append(v2_divider())
        items.append(v2_body(f"**🇬🇧 Original (English)**\n**{titre_orig}**\n"
                             f"{corps_orig_court}"))

    # ── Les médias : galerie pleine largeur, comme le billet d'origine ────
    medias = list(billet.get("images") or []) + list(billet.get("videos_fichiers") or [])
    if medias:
        try:
            galerie = discord.ui.MediaGallery()
            for u in medias[:10]:
                galerie.add_item(media=u)
            items.append(v2_divider())
            items.append(galerie)
        except Exception as ex:
            _log(f"[roblox fiche actu galerie] {ex}")

    # ── Le pied : mention, date, source ────────────────────────────────────
    if langue == "fr":
        mention = "🇫🇷 Rédigé en français par Roblox"
    elif traduit_par:
        mention = f"🇫🇷 Traduction automatique ({traduit_par}) — original anglais ci-dessus"
    else:
        mention = "🇬🇧 Texte original — traduction indisponible pour ce passage"
    items.append(v2_divider())
    items.append(v2_body(
        f"-# {mention}\n"
        f"-# 📅 Publié {_horodatage(billet.get('cree_le'))} · "
        f"{'DevForum' if isinstance(billet.get('topic_id'), int) else 'Roblox'}"))

    # ── Les boutons : article complet, vidéos YouTube ──────────────────────
    boutons = []
    if lien:
        boutons.append(Button(label="Lire l'article complet", emoji="🔗",
                              style=discord.ButtonStyle.link, url=lien))
    for k, v in enumerate((billet.get("videos") or [])[:2], 1):
        boutons.append(Button(label=f"Vidéo {k}" if k > 1 or len(billet.get("videos") or []) > 1
                              else "Vidéo", emoji="▶️",
                              style=discord.ButtonStyle.link, url=v))
    #  Même règle que sur la fiche d'accessoire : le bouton d'abonnement garde
    #  sa place, quitte à laisser tomber une vidéo (elle reste dans l'article).
    b_ping = _bouton_ping(ping_cle)
    if b_ping is not None:
        boutons = boutons[:4] + [b_ping]
        ligne = _ligne_mention(ping_role)
        if ligne:
            items.append(v2_body(ligne))
    if boutons:
        items.append(discord.ui.ActionRow(*boutons[:5]))
    elif not lien:
        items.append(v2_body("-# Lien indisponible (identifiant illisible)."))

    v = LayoutView(timeout=None)
    v.add_item(v2_container(*items, color=couleur))
    return v


async def publier_actu(guild, salon, billet: dict) -> bool:
    """Publie un billet, par webhook si possible. Fail-safe.

    Même contrat que `publier` : `True` seulement si le message est parti.
    """
    if salon is None:
        return False
    #  La catégorie vient du DOMAINE du billet — « Studio & moteur » n'a pas le
    #  même public que « Événements ». Domaine inconnu = pas de ping plutôt
    #  qu'un ping au mauvais rôle.
    cle = pings.cle_du_billet(billet)
    role = await pings.role_de(guild, cle) if cle else None
    #  Meme raison que ci-dessus : le nom vient du profil, pas d'un kwarg.
    return await _envoyer(salon, "roblox_actu",
                          construire_actu(billet, ping_cle=cle, ping_role=role),
                          "publier_actu", ping_role=role)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le panneau
# ═══════════════════════════════════════════════════════════════════════════════

_retour_configure = None


def set_retour(fn):
    global _retour_configure
    _retour_configure = fn


_relever = None


def set_relever(fn):
    """Le passage d'actualité à la demande, fourni par bot.py : `await fn()` -> compteurs."""
    global _relever
    _relever = fn


class RobloxPanelV2(LayoutView):
    """L'onglet Roblox : l'actualité (blog, forum, notes de version). Les accessoires sont
    retirés le 19/10/2026 — « tu ne me gardes que les news »."""

    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g, self._dernier = u, g, ""

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def render_to(self, i, *, edit: bool = True):
        try:
            c = await news.config(self.g.id)
            allume = bool(c.get("roblox_news_enabled"))
            salon = self.g.get_channel(int(c.get("roblox_news_salon", 0) or 0))
            try:
                diag = await news.diagnostic()
            except Exception as ex:
                _log(f"[RobloxPanelV2 diag news] {ex}")
                diag = []
            sante = "\n".join(
                f"{'🟢' if s['echecs'] == 0 else '🔴'} `{s['cle']}` · code `{_ou_tiret(s['code'])}`"
                + (f" · {s['echecs']} échec(s) d'affilée" if s["echecs"] else "")
                for s in diag) or "⚪ aucun relevé pour l'instant"
            f = await news.etat_file_actu(self.g.id)
            items = [
                v2_title("📢 Actualité Roblox"),
                v2_subtitle("Studio · UGC · développeurs · événements · politique"),
                v2_divider(),
                v2_body(("🟢 **Allumée**" if allume else "⚪ **Éteinte**")
                        + f" · salon {salon.mention if salon else '⚪ _non défini_'}"
                        + ("  ⚠️ _aucun salon : rien ne sortira_" if allume and not salon else "")),
                v2_divider(),
                v2_body(f"**Sources**\n{sante}\n-# file d'envoi : `{f.get('attente', 0)}` en "
                        f"attente · `{f.get('envoyees', 0)}` envoyée(s)"),
            ]
            if self._dernier:
                items.append(v2_body(self._dernier))
            sel = ChannelSelect(channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                                placeholder="Salon des actualités…", min_values=1, max_values=1,
                                custom_id="rblx_ch_roblox_news_salon")
            sel.callback = self._cb_salon
            items.append(discord.ui.ActionRow(sel))
            b_on = Button(label="Allumée" if allume else "Éteinte", emoji="🟢" if allume else "⚪",
                          style=(discord.ButtonStyle.success if allume
                                 else discord.ButtonStyle.secondary),
                          custom_id="rblx_toggle_news")
            b_on.callback = self._cb_toggle_news
            b_test = Button(label="Relever maintenant", emoji="🔄",
                            style=discord.ButtonStyle.primary, custom_id="rblx_test",
                            disabled=_relever is None)
            b_test.callback = self._cb_relever
            b_back = Button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary,
                            custom_id="rblx_back")
            b_back.callback = self._cb_retour
            items.append(discord.ui.ActionRow(b_on, b_test, b_back))
            self.clear_items()
            self.add_item(v2_container(*items, color=Palette.INFO))
            if edit:
                if i.response.is_done():
                    await i.edit_original_response(content=None, view=self, embed=None,
                                                   attachments=[])
                else:
                    await i.response.edit_message(content=None, view=self, embed=None,
                                                  attachments=[])
            else:
                await i.response.send_message(view=self, ephemeral=True)
        except Exception as ex:
            _log(f"[RobloxPanelV2] {ex}")
            try:
                msg = f"❌ Erreur : `{type(ex).__name__}`"
                if not i.response.is_done():
                    await i.response.send_message(msg, ephemeral=True)
                else:
                    await i.followup.send(msg, ephemeral=True)
            except discord.HTTPException:
                pass

    async def _cb_salon(self, i):
        try:
            await _db_set(self.g.id, "roblox_news_salon", int(i.data["values"][0]))
            self._dernier = ""
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox salon actu] {ex}")

    async def _cb_toggle_news(self, i):
        """Au premier allumage, la semaine écoulée sort et le reste est absorbé
        (`news.amorcer`)."""
        try:
            await i.response.defer()
            c = await news.config(self.g.id)
            allume = not c.get("roblox_news_enabled")
            await _db_set(self.g.id, "roblox_news_enabled", allume)
            if allume and not c.get("roblox_news_amorcee"):
                n = await news.amorcer(self.g.id)
                self._dernier = (
                    f"✅ Actualités allumées. `{n}` billet(s) de plus de "
                    f"`{news.AMORCE_GARDE_JOURS}` jours absorbé(s) sans être publiés.\n"
                    f"-# Ceux de la semaine écoulée sortiront au prochain relevé.")
            else:
                self._dernier = "✅ Actualités allumées." if allume else "⚪ Actualités éteintes."
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox toggle news] {ex}")

    async def _cb_relever(self, i):
        try:
            await i.response.defer()
            self._dernier = "🔄 Relevé en cours…"
            await self.render_to(i, edit=True)
            #  Un billet abandonné après MAX_ESSAIS_ACTU échecs (salon interdit, supprimé)
            #  ne revient jamais seul : `enfiler_actu` refuse de le réinsérer. Ce bouton
            #  est le chemin de retour, une fois la panne réparée.
            relances = await news.relancer_actus_abandonnees(self.g.id)
            res = await _relever()
            self._dernier = (f"✅ `{res.get('lus', 0)}` billet(s) lu(s) · "
                             f"`{res.get('enfiles', 0)}` nouveau(x) · "
                             f"`{res.get('publies', 0)}` publié(s)"
                             + (f" · ♻️ `{relances}` billet(s) bloqué(s) remis en file"
                                if relances else "")
                             + (f" · ⚠️ `{res['pannes']}` source(s) en panne"
                                if res.get("pannes") else ""))
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox relever] {ex}")

    async def _cb_retour(self, i):
        if _retour_configure is not None:
            await _retour_configure(self.u, self.g, i)
        else:
            await i.response.defer()
