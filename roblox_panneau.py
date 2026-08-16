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

import asyncio

import discord
from discord.ui import Button, ChannelSelect

import roblox_news as news
import roblox_veille as veille
from ui_v2 import (
    LayoutView, Palette, body as v2_body, container as v2_container,
    divider as v2_divider, subtitle as v2_subtitle, title as v2_title,
)

_db_set = None
_webhook_send = None
_log = print

#  Le nom affiché par le webhook, par flux. C'est ce qui rend le salon lisible
#  quand trois flux tombent au même endroit.
#  La CLE de profil webhook, par flux. Doit correspondre a WEBHOOK_PROFILES
#  dans bot.py — sans correspondance, tout sort sous « Notifications ».
PLATEFORME = {
    "nouveautes": "roblox_nouveautes",
    "bascules": "roblox_bascules",
    "surveiller": "roblox_surveiller",
}

NOMS_FLUX = {
    "nouveautes": "🆕 Nouveautés Roblox",
    "bascules": "💎 Passés collectionnables",
    "surveiller": "👀 À surveiller",
}


def setup(*, db_set, webhook_send=None, log=None):
    global _db_set, _webhook_send, _log
    _db_set = db_set
    _webhook_send = webhook_send
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


def construire_fiche(article: dict, flux: str, image: str | None = None) -> LayoutView:
    """La fiche d'un article, en quadrillage fixe.

    L'ordre ne change jamais : type et nom, puis créateur et date, puis les
    chiffres, puis l'indice et ce qui le justifie, puis le lien.
    """
    ind = veille.indice(article)
    lien = veille.lien_article(article.get("asset_id"),
                                article.get("item_type"))

    couleur = {"bascules": Palette.PREMIUM, "surveiller": Palette.WARNING}.get(
        flux, Palette.INFO)

    #  LE NOM, EN DEUX LANGUES quand Roblox en fournit une traduction. Le
    #  français d'abord — c'est la langue du serveur — l'anglais en dessous,
    #  parce que c'est celui qu'on retrouve dans le catalogue et sur les sites
    #  d'échange. Sans traduction officielle, une seule ligne : on ne traduit
    #  jamais nous-mêmes, et on n'affiche pas deux fois la même chose.
    nom_en = _ou_tiret(article.get("nom"))
    nom_fr = article.get("nom_fr")
    titre = f"{nom_fr}\n-# {nom_en}" if nom_fr else nom_en

    items = [
        v2_title(NOMS_FLUX.get(flux, "Roblox")),
        v2_subtitle(f"{_ou_tiret(article.get('type_article'))}"),
        v2_body(f"## {titre}"),
    ]

    #  L'IMAGE EN BANNIÈRE, tout en haut — un accessoire se juge d'abord à l'œil.
    #  `MediaGallery` est le composant V2 fait pour ça ; s'il n'est pas
    #  disponible dans cette version de discord.py, on n'affiche rien plutôt que
    #  de tordre la fiche.
    if image:
        try:
            galerie = discord.ui.MediaGallery()
            galerie.add_item(media=image)
            items.append(galerie)
        except Exception as ex:
            _log(f"[roblox fiche image] {ex}")

    items += [
        v2_divider(),
        v2_body(
            f"**Créateur** · Roblox\n"
            f"**Créé le** · {_ou_tiret((article.get('cree_le') or '')[:10])}\n"
            f"**Prix** · {_ou_tiret(article.get('prix'))}\n"
            f"**Favoris** · {_ou_tiret(article.get('favoris'))}\n"
            f"**Statut** · "
            + ("collectionnable" if article.get("collectionnable")
               else ("retiré de la vente" if article.get("hors_vente") else "en vente"))
        ),
        v2_divider(),
    ]

    #  ⚠️ « INDICE », JAMAIS « PRÉDICTION ». Mesuré sur 339 articles : aucun
    #  signal déclaratif n'annonce un passage en collectionnable.
    #
    #  ET SURTOUT : on ne l'affiche QUE s'il dit quelque chose. Demande du
    #  propriétaire le 12/08 — « quasiment du 100 % ou du 80 %, pas du 20 % ; tu
    #  dis pas et tu mets pas ce qui sert à rien ». Un « 30/100 » se lit comme un
    #  verdict faible alors que ce n'est qu'une ABSENCE de signal. Se taire est
    #  plus honnête que d'afficher un chiffre qui n'apprend rien.
    if ind["note"] >= veille.SEUIL_INDICE_AFFICHE and ind["facteurs"]:
        detail = " · ".join(f"{lib} +{pts}" for lib, pts in ind["facteurs"])
        items.append(v2_body(
            f"**Indice** · `{ind['note']}/100`\n"
            f"-# {detail}\n"
            f"-# Un indice, pas une prédiction : Roblox n'annonce jamais à "
            f"l'avance qu'un article passera collectionnable."))

    if flux == "bascules":
        #  Aucun champ ne donne la date de bascule. On dit donc « détecté »,
        #  et c'est la seule formulation honnête.
        items.append(v2_body("-# Détecté par comparaison de deux relevés — "
                             "Roblox ne publie pas la date de bascule."))

    if lien:
        items.append(v2_divider())
        b = Button(label="Voir l'article", emoji="🔗",
                   style=discord.ButtonStyle.link, url=lien)
        items.append(discord.ui.ActionRow(b))
    else:
        #  Identifiant illisible : on publie SANS lien plutôt qu'avec un lien
        #  approximatif. Voir ROBLOX.md §1 — c'est une règle de sécurité.
        items.append(v2_body("-# Lien indisponible (identifiant illisible)."))

    v = LayoutView(timeout=None)
    v.add_item(v2_container(*items, color=couleur))
    return v


async def _envoyer(salon, profil: str, vue: LayoutView, etiquette: str) -> bool:
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
            res = await _webhook_send(salon, profil, view=vue)
            if res is None:
                _log(f"[roblox {etiquette}] webhook_send a rendu None — RIEN "
                     f"n'est parti dans #{getattr(salon, 'name', '?')} "
                     f"({getattr(salon, 'id', '?')}). Cause journalisée par "
                     f"[webhook_send] juste au-dessus.")
                return False
            return True
        await salon.send(view=vue)
        return True
    except Exception as ex:
        #  Repli : un défaut de webhook ne doit pas faire taire le flux.
        _log(f"[roblox {etiquette} webhook] {ex}")
        try:
            await salon.send(view=vue)
            return True
        except Exception as ex2:
            _log(f"[roblox {etiquette}] {ex2}")
            return False


async def publier(guild, salon, article: dict, flux: str,
                  image: str | None = None) -> bool:
    """Publie une fiche, par webhook si possible. Fail-safe.

    Rend `True` seulement si le message est REELLEMENT parti — l'appelant
    s'appuie dessus pour écrire la marque « déjà publié », qui est définitive.

    `image` est passée par l'appelant, qui a demandé les vignettes EN LOT :
    une requête pour cent articles au lieu de cent requêtes. Aller la chercher
    ici, article par article, ferait exactement ce que le pare-feu punit.
    """
    if salon is None:
        return False
    vue = construire_fiche(article, flux, image=image)
    return await _envoyer(salon, PLATEFORME.get(flux, "roblox_nouveautes"),
                          vue, "publier")


def construire_actu(billet: dict) -> LayoutView:
    """La fiche d'un billet d'actualité — même quadrillage que les articles.

    Le DOMAINE est en titre, pas le titre du billet : dans un salon où tombent
    Studio, UGC, politique et événements, c'est la première chose qu'on cherche.
    """
    lien = news.lien_billet(billet.get("topic_id"))
    items = [
        v2_title(f"📢 {_ou_tiret(billet.get('domaine'))}"),
        v2_subtitle(_ou_tiret(billet.get("titre"))),
        v2_divider(),
        v2_body(
            f"**Publié le** · {_ou_tiret((billet.get('cree_le') or '')[:10])}\n"
            f"**Sujets** · {_ou_tiret(', '.join(billet.get('tags') or []))}"),
    ]
    if billet.get("extrait"):
        items.append(v2_body(f"-# {billet['extrait']}"))
    if lien:
        items.append(v2_divider())
        items.append(discord.ui.ActionRow(Button(
            label="Lire l'annonce", emoji="🔗",
            style=discord.ButtonStyle.link, url=lien)))
    else:
        items.append(v2_body("-# Lien indisponible (identifiant illisible)."))
    v = LayoutView(timeout=None)
    v.add_item(v2_container(*items, color=Palette.PRIMARY))
    return v


async def publier_actu(guild, salon, billet: dict) -> bool:
    """Publie un billet, par webhook si possible. Fail-safe.

    Même contrat que `publier` : `True` seulement si le message est parti.
    """
    if salon is None:
        return False
    #  Meme raison que ci-dessus : le nom vient du profil, pas d'un kwarg.
    return await _envoyer(salon, "roblox_actu", construire_actu(billet),
                          "publier_actu")


# ═══════════════════════════════════════════════════════════════════════════════
#  Le panneau
# ═══════════════════════════════════════════════════════════════════════════════

_retour_configure = None


def set_retour(fn):
    global _retour_configure
    _retour_configure = fn


class RobloxPanelV2(LayoutView):
    """L'onglet Roblox. Réglages, état des relevés, et un relevé à la demande."""

    CHAMPS = [
        ("roblox_salon_nouveautes", "🆕 Nouveautés",
         "Les articles que Roblox vient de créer."),
        ("roblox_salon_bascules", "💎 Passés collectionnables",
         "Détectés en comparant deux relevés."),
        ("roblox_salon_surveiller", "👀 À surveiller",
         "Retirés de la vente, ou fortement demandés."),
        ("roblox_news_salon", "📢 Actualité Roblox",
         "Studio · UGC · développeurs · événements · politique."),
    ]

    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self._dernier = ""

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def render_to(self, i, *, edit: bool = True):
        try:
            #  ⚠️ DEUX MODULES, DEUX CONFIGURATIONS — LES FUSIONNER ICI.
            #
            #  `roblox_news_salon` appartient à `roblox_news`, pas à `roblox_veille`.
            #  L'écran le lisait dans la config des articles, qui ne contient pas
            #  cette clé : le salon était bien ENREGISTRÉ par le select, mais
            #  l'écran affichait « non défini » pour toujours. Défaut signalé par
            #  le propriétaire — « il détecte bien le salon, mais il veut pas
            #  l'afficher », et c'était exactement ça.
            c = dict(await veille.config(self.g.id))
            c.update(await news.config(self.g.id))
            diag = await veille.diagnostic()
            en_marche = await veille.actif(self.g.id)

            lignes = []
            for cle, nom, aide in self.CHAMPS:
                ch = self.g.get_channel(int(c.get(cle, 0) or 0))
                lignes.append(f"**{nom}** · {ch.mention if ch else '⚪ _non défini_'}\n"
                              f"-# {aide}")

            #  ⚠️ La santé se lit sur le CODE HTTP, jamais sur « on a trouvé
            #  quelque chose » : le dernier collectionnable créé par Roblox date
            #  d'octobre 2025. Un salon calme est normal ; une source muette ne
            #  l'est pas, et seule cette ligne fait la différence.
            if diag["sources"]:
                sante = []
                for s in diag["sources"]:
                    icone = "🟢" if s["echecs"] == 0 else "🔴"
                    sante.append(f"{icone} `{s['source']}` · code "
                                 f"`{_ou_tiret(s['code'])}`"
                                 + (f" · {s['echecs']} échec(s) d'affilée"
                                    if s["echecs"] else ""))
                sante_txt = "\n".join(sante)
            else:
                sante_txt = "⚪ aucun relevé effectué pour l'instant"

            items = [
                v2_title("🎮 Veille Roblox"),
                v2_subtitle("Nouveaux accessoires de Roblox · passages en "
                            "collectionnable · indices"),
                v2_divider(),
                v2_body(
                    f"{'🟢' if c['roblox_veille_enabled'] else '⚪'} **Système** · "
                    + ("allumé" if c["roblox_veille_enabled"] else "éteint")
                    + ("" if en_marche or not c["roblox_veille_enabled"]
                       else "  ⚠️ _aucun salon défini, rien ne sortira_")),
                v2_divider(),
                v2_body("\n\n".join(lignes)),
                v2_divider(),
                v2_body(f"**État des relevés**\n{sante_txt}\n"
                        f"-# `{diag['articles_connus']}` article(s) connu(s)"),
            ]

            if self._dernier:
                items.append(v2_body(self._dernier))

            items.append(v2_divider())
            items.append(v2_body(
                "-# ⚠️ Roblox n'annonce **jamais** à l'avance qu'un article "
                "passera collectionnable — vérifié sur 339 articles. Ce que le "
                "bot publie est un **indice** adossé à des faits observables "
                "(retrait de la vente, demande, prix), jamais une prédiction.\n"
                "-# Le dernier collectionnable créé par Roblox date d'octobre "
                "2025 : un salon calme est **normal**."))

            for cle, nom, _ in self.CHAMPS:
                sel = ChannelSelect(
                    channel_types=[discord.ChannelType.text],
                    placeholder=f"Salon · {nom.split(' ', 1)[1]}…",
                    min_values=1, max_values=1, custom_id=f"rblx_ch_{cle}")
                sel.callback = self._faire_salon(cle)
                items.append(discord.ui.ActionRow(sel))

            b_on = Button(
                label="Allumé" if c["roblox_veille_enabled"] else "Éteint",
                emoji="🟢" if c["roblox_veille_enabled"] else "⚪",
                style=(discord.ButtonStyle.success if c["roblox_veille_enabled"]
                       else discord.ButtonStyle.secondary),
                custom_id="rblx_toggle")
            b_on.callback = self._cb_toggle

            b_test = Button(label="Relever maintenant", emoji="🔄",
                            style=discord.ButtonStyle.primary,
                            custom_id="rblx_test")
            b_test.callback = self._cb_relever

            #  Efface la mémoire des publications. Rouge : il peut faire
            #  ressortir des articles déjà vus — c'est justement à ça qu'il sert,
            #  mais on ne le déclenche pas par mégarde.
            b_reset = Button(label="Tout republier", emoji="♻️",
                             style=discord.ButtonStyle.danger,
                             custom_id="rblx_reset")
            b_reset.callback = self._cb_oublier

            b_back = Button(label="Retour", emoji="◀️",
                            style=discord.ButtonStyle.secondary,
                            custom_id="rblx_back")
            b_back.callback = self._cb_retour

            items.append(discord.ui.ActionRow(b_on, b_test, b_reset, b_back))

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
            _log(f"[RobloxPanelV2] {ex}")
            try:
                msg = f"❌ Erreur : `{type(ex).__name__}`"
                if not i.response.is_done():
                    await i.response.send_message(msg, ephemeral=True)
                else:
                    await i.followup.send(msg, ephemeral=True)
            except Exception:
                pass

    def _faire_salon(self, cle: str):
        async def _cb(i):
            try:
                await _db_set(self.g.id, cle, int(i.data["values"][0]))
                self._dernier = ""
                await self.render_to(i, edit=True)
            except Exception as ex:
                _log(f"[roblox salon {cle}] {ex}")
        return _cb

    async def _cb_toggle(self, i):
        """Allume ou éteint. À l'allumage, pose la borne du premier relevé.

        Sans cette amorce, le premier passage déverserait tout le catalogue
        connu dans le salon — voir `veille.amorcer`.
        """
        try:
            await i.response.defer()
            c = await veille.config(self.g.id)
            allume = not c["roblox_veille_enabled"]
            await _db_set(self.g.id, "roblox_veille_enabled", allume)
            if allume and not c.get("roblox_veille_amorcee"):
                n = await veille.amorcer(self.g.id)
                self._dernier = (
                    f"✅ Allumé. `{n}` article(s) hors fenêtre d'âge ont été "
                    f"absorbés sans être publiés.\n"
                    f"-# Les articles récents, eux, sortiront au prochain "
                    f"relevé — cliquez « Relever maintenant » pour ne pas "
                    f"attendre.")
            else:
                self._dernier = "✅ Allumé." if allume else "⚪ Éteint."
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox toggle] {ex}")

    async def _cb_relever(self, i):
        """Un relevé immédiat, pour vérifier que la chaîne fonctionne.

        Le bouton dit ce qu'il a VU, y compris quand il n'a rien trouvé : c'est
        la seule façon de distinguer « rien de neuf » de « ça ne marche pas ».

        ⚠️ PIÈGE À NE PAS DÉFAIRE — « 0 PUBLIÉE » A CINQ CAUSES.
        Salon non réglé · salon introuvable · article hors fenêtre d'âge ·
        indice sous le seuil · déjà sorti · envoi refusé par Discord. Toutes
        donnaient le même texte : « Rien de neuf : c'est normal, Roblox publie
        peu. » Un compte-rendu qui range une panne de permission sous « c'est
        normal » est un bouton qui ment — on compte donc chaque cause, et on
        nomme celle qui a réellement bloqué.
        """
        try:
            await i.response.defer()
            rel = await veille.relever_nouveautes(limite=30)
            if rel["code"] != 200:
                self._dernier = (
                    f"🔴 Relevé en échec — code `{_ou_tiret(rel['code'])}`, "
                    f"`{rel['echecs']}` échec(s) d'affilée. Rien n'a été publié.")
                return await self.render_to(i, edit=True)

            evts = await veille.comparer_et_enregistrer(rel["articles"])

            #  ⚠️ LE SECOND RELEVÉ — celui qui voit les Limiteds.
            #  Le relevé ci-dessus trie par date de CRÉATION : il ne contient
            #  que des articles récents, et JAMAIS les accessoires passés
            #  collectionnables (mesuré le 16/08 : 0 sur 10, contre 10 sur 10
            #  avec `SalesTypeFilter=2`). Sans lui, ce bouton cherchait au seul
            #  endroit où les Limiteds ne sont pas.
            await asyncio.sleep(veille.PAUSE_ENTRE_APPELS)
            relc = await veille.relever_collectionnables(limite=30)
            if relc["code"] == 200:
                await veille.comparer_et_enregistrer(relc["articles"])
                vus = {x["asset_id"] for x in (evts.get("bascules") or [])}
                for x in relc["articles"]:
                    if x.get("collectionnable") and x["asset_id"] not in vus:
                        evts.setdefault("bascules", []).append(x)
                        vus.add(x["asset_id"])
            else:
                _log(f"[roblox relever collectionnables] code {relc['code']}")

            c = await veille.config(self.g.id)
            envoyes = 0
            #  Le décompte des refus, par cause. C'est lui qui rend le
            #  compte-rendu honnête.
            motifs = {"sans_salon": 0, "salon_introuvable": 0, "age": 0,
                      "seuil": 0, "deja": 0, "envoi": 0}
            salons_absents = []
            #  Les images en UN SEUL appel pour tout le passage.
            a_publier = [x for k in ("nouveaux", "bascules", "retires")
                         for x in (evts.get(k) or [])[:5]]
            imgs = await veille.vignettes([x["asset_id"] for x in a_publier])
            for flux, cle in (("nouveautes", "nouveaux"),
                              ("bascules", "bascules"),
                              ("surveiller", "retires")):
                #  « bascules » regarde plus loin : c'est ce flux qui rattrape
                #  les Limiteds jamais sortis. Le plafond de publications reste
                #  le vrai garde-fou — la tranche ne décide que du REGARD.
                candidats = (evts.get(cle) or [])[:30 if cle == "bascules" else 5]
                #  ⚠️ L'identifiant AVANT le salon : `get_channel(0)` et
                #  `get_channel(1234)` rendent tous les deux `None`, mais l'un
                #  veut dire « case vide » et l'autre « salon supprimé ou
                #  invisible au bot ». Deux pannes différentes, deux corrections
                #  différentes — les confondre coûterait une heure de recherche.
                salon_id = veille.salon_du_flux(c, flux)
                salon = self.g.get_channel(salon_id) if salon_id else None
                if candidats and salon is None:
                    if salon_id:
                        motifs["salon_introuvable"] += len(candidats)
                        salons_absents.append(str(salon_id))
                    else:
                        motifs["sans_salon"] += len(candidats)
                    continue
                for a in candidats:
                    #  Meme plafond que la boucle : le bouton ne doit pas etre
                    #  un moyen de contourner la protection de debit.
                    if envoyes >= veille.MAX_PUBLICATIONS_PAR_PASSAGE:
                        break
                    #  Trop vieux = plus une nouvelle. L'article reste en base
                    #  pour la détection des bascules, mais on ne le publie pas.
                    if not veille.age_publiable(a, flux):
                        motifs["age"] += 1
                        continue
                    #  « À surveiller » ne publie que du solide : ce flux doit
                    #  être rare et sûr, pas un fourre-tout.
                    if flux == "surveiller" and \
                            veille.indice(a)["note"] < veille.SEUIL_SURVEILLER:
                        motifs["seuil"] += 1
                        continue
                    if await veille.deja_publie(self.g.id, a["asset_id"], flux):
                        motifs["deja"] += 1
                        continue
                    if await publier(self.g, salon, a, flux,
                                     image=imgs.get(a["asset_id"])):
                        #  La marque est DÉFINITIVE : on ne l'écrit que sur un
                        #  envoi réellement abouti (voir `_envoyer`).
                        await veille.marquer_publie(self.g.id, a["asset_id"], flux)
                        envoyes += 1
                    else:
                        motifs["envoi"] += 1
            await veille.purger()
            self._dernier = self._compte_rendu(len(rel["articles"]), envoyes,
                                               motifs, salons_absents)
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox relever] {ex}")
            self._dernier = f"❌ Erreur : `{type(ex).__name__}` — {ex}"
            try:
                await self.render_to(i, edit=True)
            except Exception:
                pass

    @staticmethod
    def _compte_rendu(lus: int, envoyes: int, motifs: dict,
                      salons_absents: list) -> str:
        """Le texte du relevé — il nomme la cause, il ne la range pas.

        Séparé de `_cb_relever` pour être testable sans Discord : c'est ce
        texte, et lui seul, qui dit au propriétaire si la chaîne marche.
        """
        detail = []
        if motifs["sans_salon"]:
            detail.append(f"`{motifs['sans_salon']}` bloquée(s) : **aucun salon "
                          f"réglé** pour ce flux — réglez-le ci-dessus")
        if motifs["salon_introuvable"]:
            detail.append(
                f"`{motifs['salon_introuvable']}` bloquée(s) : **salon "
                f"introuvable** (`{'`, `'.join(salons_absents)}`) — supprimé, "
                f"ou le bot n'y a pas accès")
        if motifs["envoi"]:
            detail.append(f"`{motifs['envoi']}` **refusée(s) par Discord** — "
                          f"permissions du salon (voir les journaux). Ces "
                          f"articles ressortiront au prochain relevé")
        if motifs["deja"]:
            detail.append(f"`{motifs['deja']}` déjà publié(e)(s) — « ♻️ Tout "
                          f"republier » les libère")
        if motifs["age"]:
            detail.append(f"`{motifs['age']}` hors fenêtre d'âge")
        if motifs["seuil"]:
            detail.append(f"`{motifs['seuil']}` sous le seuil d'indice "
                          f"(`{veille.SEUIL_SURVEILLER}`)")

        #  Une panne se voit au premier coup d'œil : icône rouge, pas verte.
        panne = bool(motifs["sans_salon"] or motifs["salon_introuvable"]
                     or motifs["envoi"])
        icone = "🔴" if panne else ("🟢" if envoyes else "⚪")
        txt = (f"{icone} Relevé — `{lus}` article(s) lus, `{envoyes}` "
               f"fiche(s) **réellement publiée(s)**.")
        if detail:
            txt += "\n" + "\n".join(f"-# • {d}." for d in detail)
        elif not envoyes:
            txt += ("\n-# • Aucun article nouveau dans ce relevé : rien à "
                    "publier, et c'est normal — Roblox publie peu.")
        return txt

    async def _cb_oublier(self, i):
        """Efface la mémoire des publications de cette guilde.

        Nécessaire parce qu'un correctif de code ne répare pas des données déjà
        écrites : la première amorce avait marqué tout le catalogue comme sorti,
        et ces marques survivaient au correctif.
        """
        try:
            await i.response.defer()
            n = await veille.oublier_publies(self.g.id)
            self._dernier = (
                f"♻️ `{n}` marque(s) effacée(s). Les articles déjà connus "
                f"peuvent de nouveau sortir.\n"
                f"-# Cliquez « Relever maintenant » — ils sortiront par paquets "
                f"de `{veille.MAX_PUBLICATIONS_PAR_PASSAGE}`, jamais d'un bloc.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox oublier] {ex}")

    async def _cb_retour(self, i):
        if _retour_configure is not None:
            await _retour_configure(self.u, self.g, i)
        else:
            await i.response.defer()
