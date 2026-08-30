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
import roblox_pings as pings
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


def _fmt_nombre(v) -> str:
    """Un grand nombre se lit par milliers séparés : `107 687`, pas `107687`.

    Un stock est le chiffre que l'œil compare le plus souvent d'une fiche à
    l'autre — collé, il se lit de travers.
    """
    if v is None or v == "":
        return "—"
    try:
        return f"{int(v):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def _fmt_robux(v) -> str:
    """Un prix, avec son unité. `0` veut dire GRATUIT, pas « inconnu ».

    La distinction compte : un article offert et un article au prix inconnu ne
    se traitent pas pareil quand on décide d'acheter.
    """
    if v is None or v == "":
        return "—"
    try:
        n = int(v)
    except (TypeError, ValueError):
        return str(v)
    return "gratuit" if n == 0 else f"{n:,}".replace(",", " ") + " R$"


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


def construire_fiche(article: dict, flux: str, image: str | None = None,
                     lies: list | None = None, ping_cle: str | None = None,
                     ping_role=None) -> LayoutView:
    """La fiche d'un accessoire — légère, et elle dit ce qui VIENT d'arriver.

    Ordre fixe (on la lit en diagonale) :
      EN-TÊTE      « VIENT DE PASSER LIMITED » · « NOUVEL ACCESSOIRE ROBLOX »
      NOM          français (Roblox) puis anglais · vignette à droite
      DESCRIPTION  courte, celle de Roblox
      CHIFFRES     prix d'origine · pour un Limited : revente, stock, rapport
      DATE         création (ou détection de la bascule) — horodatage natif
      BOUTONS      voir l'accessoire · 📰 annonce liée

    `lies` : les billets d'actualité qui parlent de cet accessoire (voir
    `roblox_news.billets_lies`). Un bouton, pas un pavé.
    """
    lien = veille.lien_article(article.get("asset_id"),
                                article.get("item_type"))
    limited_u = bool(article.get("limited_u"))
    if flux == "bascules":
        #  ⚠️ TROIS CLASSES, PAS DEUX — exigence de la spécification du 30/08 :
        #  « Limited / LimitedUnique / Collectible ; le système doit distinguer
        #  ces trois catégories ». Un `Collectible` est un UGC Limited : dire
        #  « VIENT DE PASSER LIMITED » d'un UGC serait faux, et ce sont deux
        #  marchés différents pour qui échange.
        #  Repli sur `limited_u` pour les fiches mises en file AVANT ce
        #  correctif : leur charge JSON n'a pas de champ `classe`.
        _classe = article.get("classe") or (
            veille.CLASSE_LIMITED_U if limited_u else veille.CLASSE_LIMITED)
        etiquette = f"VIENT DE PASSER {veille.libelle_classe(_classe)}"
        pastille, couleur = "🔷", Palette.PREMIUM
    else:
        etiquette, pastille, couleur = "NOUVEL ACCESSOIRE ROBLOX", "🆕", Palette.INFO

    #  LE NOM, EN DEUX LANGUES quand Roblox en fournit une traduction. Le
    #  français d'abord — c'est la langue du serveur — l'anglais en dessous,
    #  parce que c'est celui qu'on retrouve dans le catalogue et sur les sites
    #  d'échange. Sans traduction officielle, une seule ligne : on ne traduit
    #  jamais nous-mêmes, et on n'affiche pas deux fois la même chose.
    nom_en = _ou_tiret(article.get("nom"))
    nom_fr = article.get("nom_fr")
    titre = f"{nom_fr}\n-# {nom_en}" if nom_fr else nom_en

    items = [v2_title(f"{etiquette} · {_ou_tiret(article.get('type_article'))}", level=3)]

    #  ⚠️ L'IMAGE EN VIGNETTE, PAS EN BANNIÈRE — « l'image pas trop grande »,
    #  demandé le 16/08 pour les accessoires. `Section` + `Thumbnail` la met à
    #  droite du nom. Repli sur le nom seul si l'accessoire est refusé.
    if image:
        try:
            items.append(discord.ui.Section(
                v2_body(f"## {pastille} {titre}"),
                accessory=discord.ui.Thumbnail(media=image)))
        except Exception as ex:
            _log(f"[roblox fiche image] {ex}")
            items.append(v2_body(f"## {pastille} {titre}"))
    else:
        items.append(v2_body(f"## {pastille} {titre}"))

    #  La « légère description » : celle de Roblox, en français si elle existe.
    desc = (article.get("description_fr") or article.get("description") or "").strip()
    if desc:
        items.append(v2_body(_tronquer_propre(desc, 280)))

    # ── Les chiffres, sans pavé ─────────────────────────────────────────────
    stock = article.get("stock") or article.get("quantite")
    #  Les BUNDLES n'ont pas de fiche économie : leurs chiffres viennent du
    #  catalogue (`prix_revente`).
    revente = article.get("revente") or article.get("prix_revente")
    mult = article.get("multiplicateur")
    lignes = [f"**Prix d'origine** · {_fmt_robux(article.get('prix'))}"]
    if flux == "bascules" or article.get("collectionnable"):
        lignes.append(f"**Revente la plus basse** · {_fmt_robux(revente)}")
        lignes.append(f"**Stock émis** · {_fmt_nombre(stock)}")
        #  ⚠️ LE RAPPORT EST AFFICHÉ MÊME QUAND IL EST MAUVAIS — c'est ce qui
        #  évite de se faire avoir. Mesuré : Specter Time Fedora ×0,6.
        if mult is not None:
            if mult >= 2:
                lignes.append(f"**Revente / prix** · 🟢 ×{mult}")
            elif mult >= 1:
                lignes.append(f"**Revente / prix** · 🟠 ×{mult}")
            else:
                lignes.append(f"**Revente / prix** · 🔴 ×{mult} — sous le prix d'origine")
    items.append(v2_divider())
    items.append(v2_body("\n".join(lignes)))

    #  La date : création pour une nouveauté ; pour une bascule, on la DIT
    #  détectée — Roblox ne publie pas la date de passage en Limited.
    if flux == "bascules":
        pied = "-# 🔷 Passage en Limited **détecté à l'instant** par comparaison de deux relevés"
    else:
        pied = f"-# 📅 Créé {_horodatage(article.get('cree_le'))} · Roblox"
    items.append(v2_body(pied))

    # ── Les boutons ────────────────────────────────────────────────────────
    boutons = []
    if lien:
        boutons.append(Button(label="Voir l'accessoire", emoji="🔗",
                              style=discord.ButtonStyle.link, url=lien))
    for k, l_ in enumerate((lies or [])[:2], 1):
        if l_.get("lien"):
            boutons.append(Button(label="Annonce" if k == 1 else f"Annonce {k}",
                                  emoji="📰", style=discord.ButtonStyle.link,
                                  url=l_["lien"]))
    #  ⚠️ LE BOUTON DE NOTIFICATION N'EST JAMAIS SACRIFIÉ AU PLAFOND DE 5.
    #  On tronque les liens à 4 pour lui garder sa place : une annonce liée en
    #  moins se remplace par un clic sur le forum, un bouton d'abonnement
    #  manquant ne se remplace par rien.
    b_ping = _bouton_ping(ping_cle)
    if b_ping is not None:
        boutons = boutons[:4] + [b_ping]
        ligne = _ligne_mention(ping_role)
        if ligne:
            items.append(v2_body(ligne))
    if boutons:
        items.append(discord.ui.ActionRow(*boutons[:5]))
    elif not lien:
        #  Identifiant illisible : on publie SANS lien plutôt qu'avec un lien
        #  approximatif. Voir ROBLOX.md §1 — c'est une règle de sécurité.
        items.append(v2_body("-# Lien indisponible (identifiant illisible)."))

    v = LayoutView(timeout=None)
    v.add_item(v2_container(*items, color=couleur))
    return v


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
            await salon.send(view=vue)
            return True
        except Exception as ex2:
            _log(f"[roblox {etiquette}] {ex2}")
            return False


async def publier(guild, salon, article: dict, flux: str,
                  image: str | None = None, lies: list | None = None,
                  trace: dict | None = None) -> bool:
    """Publie une fiche, par webhook si possible. Fail-safe.

    Rend `True` seulement si le message est REELLEMENT parti — l'appelant
    s'appuie dessus pour écrire la marque « déjà publié », qui est définitive.

    `image` est passée par l'appelant, qui a demandé les vignettes EN LOT :
    une requête pour cent articles au lieu de cent requêtes. Aller la chercher
    ici, article par article, ferait exactement ce que le pare-feu punit.
    `lies` : les annonces d'actualité qui parlent de l'accessoire.
    """
    if salon is None:
        return False
    #  Le rôle de notification de ce flux — créé à la première annonce du
    #  genre, jamais au démarrage (un serveur qui n'active rien ne voit pas
    #  huit rôles apparaître).
    cle = pings.cle_du_flux(flux)
    role = await pings.role_de(guild, cle) if cle else None
    vue = construire_fiche(article, flux, image=image, lies=lies,
                           ping_cle=cle, ping_role=role)
    return await _envoyer(salon, PLATEFORME.get(flux, "roblox_nouveautes"),
                          vue, "publier", ping_role=role, trace=trace)


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


def _horodatage(iso) -> str:
    """`<t:UNIX:f>` — Discord l'affiche dans le fuseau du LECTEUR.

    L'ancienne fiche écrivait « 04/08/2026 18:11 » en dur : juste pour un
    lecteur, faux pour tous les autres. Une date illisible rend « — ».
    """
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return f"<t:{int(d.timestamp())}:f>"
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


class RobloxPanelV2(LayoutView):
    """L'onglet Roblox. Réglages, état des relevés, et un relevé à la demande."""

    #  ⚠️ Deux flux d'accessoires, et c'est tout — tranché le 18/08 : « ce sera
    #  tout pour les accessoires ». Le salon « à surveiller » a été retiré du
    #  panneau : proposer un réglage pour un flux qui ne publie plus serait un
    #  menu qui ment (UI.md).
    CHAMPS = [
        ("roblox_salon_nouveautes", "🆕 Nouveaux accessoires",
         "Créés par Roblox à partir de maintenant."),
        ("roblox_salon_bascules", "🔷 Vient de passer Limited",
         "Limited ou Limited U — détecté en direct entre deux relevés."),
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
            #  ⚠️ La santé des ACTUALITÉS était calculée (`news.diagnostic`)
            #  mais affichée NULLE PART. Une source muette ressemble à une
            #  source calme — c'est le défaut n°4 de ROBLOX.md, et il était là.
            try:
                diag_news = await news.diagnostic()
            except Exception as ex:
                _log(f"[RobloxPanelV2 diag news] {ex}")
                diag_news = []
            try:
                news_en_marche = await news.actif(self.g.id)
            except Exception as ex:
                _log(f"[RobloxPanelV2 news.actif] {ex}")
                news_en_marche = False

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

            if diag_news:
                sante_news = []
                for s_ in diag_news:
                    icone = "🟢" if s_["echecs"] == 0 else "🔴"
                    sante_news.append(f"{icone} `{s_['cle']}` · code "
                                      f"`{_ou_tiret(s_['code'])}`"
                                      + (f" · {s_['echecs']} échec(s) d'affilée"
                                         if s_["echecs"] else ""))
                sante_news_txt = "\n".join(sante_news)
            else:
                sante_news_txt = "⚪ aucun relevé d'actualité pour l'instant"

            #  La file d'envoi de CE serveur. C'est le seul chiffre qui
            #  distingue « rien à publier » de « tout est bloqué à l'envoi ».
            _file = await veille.etat_file(self.g.id)

            items = [
                v2_title("🎮 Veille Roblox"),
                v2_subtitle("Nouveaux accessoires de Roblox · passages en "
                            "collectionnable · indices"),
                v2_divider(),
                v2_body(
                    f"{'🟢' if c['roblox_veille_enabled'] else '⚪'} **Accessoires** · "
                    + ("allumés" if c["roblox_veille_enabled"] else "éteints")
                    + ("" if en_marche or not c["roblox_veille_enabled"]
                       else "  ⚠️ _aucun salon défini, rien ne sortira_")
                    + "\n"
                    #  ⚠️ CET INTERRUPTEUR N'EXISTAIT PAS. `roblox_news_enabled`
                    #  n'était écrit nulle part — ni bouton, ni commande — donc
                    #  `actif()` rendait toujours faux et le bloc actualité de
                    #  la boucle ne s'exécutait JAMAIS. Le salon se réglait, la
                    #  santé se calculait, et rien ne sortait. Constaté par le
                    #  propriétaire le 16/08 : « 0 fond sur les actus ».
                    + f"{'🟢' if c.get('roblox_news_enabled') else '⚪'} **Actualités** · "
                    + ("allumées" if c.get("roblox_news_enabled") else "éteintes")
                    + ("" if news_en_marche or not c.get("roblox_news_enabled")
                       else "  ⚠️ _aucun salon d'actualité défini, rien ne sortira_")
                    #  ⚠️ UN MODE QUI RETIENT LES ENVOIS DOIT SE VOIR AU
                    #  PREMIER COUP D'ŒIL. Oublié allumé, il ressemblerait
                    #  trait pour trait à une panne — et c'est exactement le
                    #  genre de confusion qui coûte des heures.
                    + ("\n🧪 **Simulation ACTIVE** · rien ne part dans un "
                       "salon, les fiches attendent en file"
                       if c.get("roblox_veille_simulation") else "")),
                v2_divider(),
                v2_body("\n\n".join(lignes)),
                v2_divider(),
                v2_body(f"**État des relevés — accessoires**\n{sante_txt}\n"
                        f"-# `{diag['articles_connus']}` article(s) connu(s)"
                        f" · file d'envoi : `{_file.get('attente', 0)}` en "
                        f"attente, `{_file.get('envoyees', 0)}` envoyée(s)"
                        + (f", ⚠️ `{_file['abandonnees']}` abandonnée(s) après "
                           f"`{veille.MAX_ESSAIS_ENVOI}` essais"
                           if _file.get("abandonnees") else "")),
                v2_body(f"**État des relevés — actualités**\n{sante_news_txt}"),
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

            b_news = Button(
                label="Actus allumées" if c.get("roblox_news_enabled") else "Actus éteintes",
                emoji="🟢" if c.get("roblox_news_enabled") else "⚪",
                style=(discord.ButtonStyle.success if c.get("roblox_news_enabled")
                       else discord.ButtonStyle.secondary),
                custom_id="rblx_toggle_news")
            b_news.callback = self._cb_toggle_news

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

            #  ⚠️ LE MODE SIMULATION A BESOIN D'UN BOUTON, SINON IL N'EXISTE
            #  PAS. Une clé de configuration que personne ne peut basculer est
            #  du code mort : « une fonction non appelée n'est pas
            #  opérationnelle, même parfaite ».
            _simu = bool(c.get("roblox_veille_simulation"))
            b_simu = Button(
                label="Simulation" if _simu else "Simulation",
                emoji="🧪" if _simu else "⚪",
                style=(discord.ButtonStyle.danger if _simu
                       else discord.ButtonStyle.secondary),
                custom_id="rblx_toggle_simu")
            b_simu.callback = self._cb_toggle_simulation

            #  ⚠️ LE RATTRAPAGE — demandé le 30/08 : « assure-toi que les
            #  derniers accessoires soient bien publiés sur le serveur ».
            #  Mesuré ce jour-là : les huit derniers articles créés par Roblox
            #  ont 38,4 jours, pour une fenêtre de six heures. Ils ne PEUVENT
            #  pas sortir tout seuls. Ce bouton est le seul chemin honnête :
            #  borné, volontaire, et il ne change pas la règle.
            b_rattrap = Button(label="Publier les derniers", emoji="📦",
                               style=discord.ButtonStyle.primary,
                               custom_id="rblx_rattraper")
            b_rattrap.callback = self._cb_rattraper

            b_back = Button(label="Retour", emoji="◀️",
                            style=discord.ButtonStyle.secondary,
                            custom_id="rblx_back")
            b_back.callback = self._cb_retour

            #  Deux rangées : Discord refuse plus de 5 boutons par ligne, et
            #  regrouper les trois interrupteurs ensemble se lit mieux.
            items.append(discord.ui.ActionRow(b_on, b_news, b_simu))
            items.append(discord.ui.ActionRow(b_test, b_rattrap, b_reset,
                                              b_back))

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

    async def _cb_rattraper(self, i):
        """Remet en file les derniers accessoires jamais annoncés.

        ⚠️ IL DIT L'ÂGE DE CE QU'IL VA PUBLIER. Le propriétaire a interdit de
        présenter comme « nouveau » ce qui a des semaines : si le bouton
        publiait 38 jours d'archives en silence, il romprait sa propre règle.
        On annonce donc le chiffre avant que les fiches ne sortent.
        """
        try:
            await i.response.defer()
            r = await veille.rattraper_nouveautes(self.g.id, combien=12)
            if not r["candidats"]:
                self._dernier = (
                    "⚪ Rien à rattraper — tous les accessoires récents sont "
                    "déjà sortis, ou aucun n'a moins de "
                    f"`{veille.AGE_MAX_JOURS}` jours.")
            else:
                self._dernier = (
                    f"📦 `{r['enfiles']}` accessoire(s) remis en file sur "
                    f"`{r['candidats']}` retenu(s).\n"
                    + (f"-# ⚠️ Le plus ancien du lot a `{r['plus_vieux_j']}` "
                       f"jours : ce sont les DERNIÈRES créations de Roblox, "
                       f"pas des nouveautés du jour. Roblox n'a rien créé "
                       f"depuis.\n" if r.get("plus_vieux_j") else "")
                    + f"-# Ils partiront par paquets de "
                      f"`{veille.MAX_PUBLICATIONS_PAR_PASSAGE}`, du plus "
                      f"ancien au plus récent. Cliquez « Relever maintenant » "
                      f"pour ne pas attendre.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox rattraper] {ex}")
            self._dernier = f"❌ Erreur : `{type(ex).__name__}` — {ex}"
            try:
                await self.render_to(i, edit=True)
            except Exception:
                pass

    async def _cb_toggle_simulation(self, i):
        """Allume ou éteint le mode simulation.

        ⚠️ CE QU'IL FAIT, EXACTEMENT — et il faut le dire au staff, sinon le
        bouton devient un piège. Tout tourne : relevés, détection, mise en
        file. Seul l'ENVOI est retenu. Les fiches restent en file et ne sont
        pas marquées envoyées : éteindre l'interrupteur les fait partir pour de
        bon, dans l'ordre où elles sont entrées. C'est ce qui permet d'éprouver
        la chaîne complète sur un vrai serveur sans mentir à ses membres.
        """
        try:
            await i.response.defer()
            c = await veille.config(self.g.id)
            allume = not bool(c.get("roblox_veille_simulation"))
            await _db_set(self.g.id, "roblox_veille_simulation", allume)
            file = await veille.etat_file(self.g.id)
            if allume:
                self._dernier = (
                    "🧪 **Simulation allumée.** Le bot relève, détecte et met "
                    "en file — mais **rien ne partira dans un salon**.\n"
                    f"-# `{file.get('attente', 0)}` fiche(s) attendent déjà. "
                    f"Elles sortiront, dans l'ordre, dès que vous éteindrez.")
            else:
                self._dernier = (
                    "✅ **Simulation éteinte.** Les publications reprennent.\n"
                    f"-# `{file.get('attente', 0)}` fiche(s) en file vont "
                    f"sortir au rythme de "
                    f"`{veille.MAX_PUBLICATIONS_PAR_PASSAGE}` par passage.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox toggle simulation] {ex}")

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

    async def _cb_toggle_news(self, i):
        """Allume ou éteint les ACTUALITÉS. Amorce raisonnable au premier
        allumage : la semaine écoulée sort, le reste est absorbé.

        Voir `news.amorcer` — la première version de l'amorce absorbait TOUT et
        le propriétaire devait attendre le prochain billet du forum.
        """
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
                    f"-# Ceux de la semaine écoulée sortiront au prochain "
                    f"relevé — cliquez « Relever maintenant » pour ne pas attendre.")
            else:
                self._dernier = ("✅ Actualités allumées." if allume
                                 else "⚪ Actualités éteintes.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox toggle news] {ex}")

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
            rel = await veille.relever_nouveautes(limite=120)
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
            await asyncio.sleep(veille.PAUSE_ENTRE_RELEVES)
            relc = await veille.relever_collectionnables(limite=120)
            if relc["code"] == 200:
                #  Ce relevé DÉTECTE, il ne publie plus par lui-même (18/08) :
                #  seules les bascules vues en direct sortent.
                evts_c = await veille.comparer_et_enregistrer(relc["articles"])
                vus = {x["asset_id"] for x in (evts.get("bascules") or [])}
                for x in (evts_c.get("bascules") or []):
                    if x["asset_id"] not in vus:
                        evts.setdefault("bascules", []).append(x)
                        vus.add(x["asset_id"])
            else:
                _log(f"[roblox relever collectionnables] code {relc['code']}")

            c = await veille.config(self.g.id)
            envoyes = 0
            #  Le décompte des refus, par cause. C'est lui qui rend le
            #  compte-rendu honnête.
            motifs = {"sans_salon": 0, "salon_introuvable": 0, "age": 0,
                      "seuil": 0, "deja": 0, "envoi": 0, "simulation": 0}
            salons_absents = []
            #  ⚠️ MÊME MISE EN FILE QUE LA BOUCLE — CORRECTIF DU 30/08.
            #  Ce bouton avait EXACTEMENT la même famine : il tronquait à 10 et
            #  5 alors que `comparer_et_enregistrer`, deux lignes plus haut,
            #  venait d'écrire les articles en base. Ce que la tranche laissait
            #  dehors n'était plus « jamais vu » et ne pouvait plus JAMAIS
            #  revenir — ni par ce bouton, ni par la boucle.
            #  On enfile donc TOUT ce qui passe les filtres, et on ne tire
            #  ensuite que ce que le plafond permet. Les deux chemins partagent
            #  la même file : cliquer ici ne double plus rien.
            for flux_e, cle_e in (("bascules", "bascules"),
                                  ("nouveautes", "nouveaux")):
                brut_e = evts.get(cle_e) or []
                for a_e in veille.ordonner_publication(brut_e, len(brut_e)):
                    if not veille.age_publiable(a_e, flux_e):
                        motifs["age"] += 1
                        continue
                    if not await veille.publiable_dans(
                            self.g.id, a_e["asset_id"], flux_e):
                        motifs["deja"] += 1
                        continue
                    await veille.enfiler(self.g.id, a_e, flux_e)

            #  Les images en UN SEUL appel pour tout le passage.
            #  Même sélection que la publication, sinon une fiche sort sans son
            #  image (ou on demande des vignettes pour rien).
            attente = await veille.a_envoyer(
                self.g.id, limite=veille.MAX_PUBLICATIONS_PAR_PASSAGE)
            a_publier = [e["article"] for e in attente]
            #  Mêmes chiffres de trading que la boucle : stock et revente
            #  viennent d'un point d'API distinct, un appel par article.
            lot = a_publier
            #  Même respiration que la boucle : sans elle, les chiffres et
            #  les images manquent après les deux relevés paginés.
            if lot:
                await asyncio.sleep(veille.PAUSE_AVANT_FICHES)
            await veille.enrichir(lot)
            #  Le nom français officiel, en un appel pour tout le lot.
            await veille.traduire(lot)
            #  Les ARTICLES, pas les identifiants : voir `vignettes`.
            imgs = await veille.vignettes(a_publier)
            #  Même ordre de priorité que la boucle : bascules d'abord, pour
            #  qu'un article ne « grille » pas sa propre bascule dans un flux
            #  plus faible au même passage.
            #  Deux flux, et c'est tout (18/08) : « ce sera tout pour les
            #  accessoires ». Le flux « à surveiller » ne publie plus.
            #  ⚠️ ON VIDE LA FILE, dans l'ordre où elle s'est remplie — donc du
            #  plus ancien au plus récent (`a_envoyer` trie sur `detecte_le`),
            #  pour que le salon se lise de haut en bas en scrollant.
            simulation = bool(c.get("roblox_veille_simulation"))
            for entree in attente:
                a, flux = entree["article"], entree["flux"]
                #  ⚠️ L'identifiant AVANT le salon : `get_channel(0)` et
                #  `get_channel(1234)` rendent tous les deux `None`, mais l'un
                #  veut dire « case vide » et l'autre « salon supprimé ou
                #  invisible au bot ». Deux pannes différentes, deux corrections
                #  différentes — les confondre coûterait une heure de recherche.
                salon_id = veille.salon_du_flux(c, flux)
                salon = self.g.get_channel(salon_id) if salon_id else None
                if salon is None:
                    if salon_id:
                        motifs["salon_introuvable"] += 1
                        if str(salon_id) not in salons_absents:
                            salons_absents.append(str(salon_id))
                    else:
                        motifs["sans_salon"] += 1
                    #  ⚠️ COMPTER L'ÉCHEC, SINON LA FILE SE FIGE. Sans cette
                    #  ligne, `essais` ne bougeait jamais et `a_envoyer` —
                    #  qui trie par date — re-tirait éternellement les mêmes
                    #  douze fiches bloquées : plus rien d'autre ne sortait,
                    #  jamais. Un salon supprimé gelait la file entière.
                    #  La boucle, elle, le faisait déjà : les deux chemins
                    #  divergeaient. Trouvé en réfutation le 30/08.
                    await veille.noter_echec_envoi(
                        entree["id"],
                        f"salon introuvable ({salon_id})" if salon_id
                        else "aucun salon réglé pour ce flux")
                    continue
                #  Mode simulation : on va jusqu'ici et pas plus loin. La fiche
                #  reste en file et partira le jour où l'interrupteur retombe.
                if simulation:
                    motifs["simulation"] += 1
                    continue
                #  ⚠️ RÉSERVER AVANT D'ENVOYER — voir `veille.reserver`. Sans
                #  ce verrou, ce bouton et la boucle pouvaient tirer les MÊMES
                #  lignes pendant les ~2 min où la boucle enrichit et publie,
                #  et le salon recevait tout en double. Rejoué en réfutation :
                #  6 messages pour une file de 3.
                if not await veille.reserver(entree["id"], entree["essais"]):
                    continue
                lies = news.billets_lies(a.get("nom") or "")
                trace = {}
                if await publier(self.g, salon, a, flux,
                                 image=imgs.get(a["asset_id"]), lies=lies,
                                 trace=trace):
                    #  La marque est DÉFINITIVE : on ne l'écrit que sur un
                    #  envoi réellement abouti (voir `_envoyer`). Et on sort de
                    #  la file APRÈS l'envoi, jamais avant.
                    await veille.marquer_envoye(entree["id"],
                                                trace.get("message_id"))
                    await veille.marquer_publie(self.g.id, a["asset_id"], flux)
                    envoyes += 1
                else:
                    await veille.noter_echec_envoi(entree["id"],
                                                   "bouton : publier a rendu False")
                    motifs["envoi"] += 1
            await veille.purger()
            compte_rendu = self._compte_rendu(len(rel["articles"]), envoyes,
                                              motifs, salons_absents)

            #  ── LES ACTUALITÉS, dans le même geste ───────────────────────
            #  ⚠️ Sans ce bloc, le bouton ne prouvait RIEN sur ce flux : il
            #  relevait le catalogue et les Limiteds, jamais le forum. Le
            #  propriétaire lisait « relevé réussi » et les actualités
            #  restaient muettes, sans qu'une ligne ne le dise.
            compte_rendu += "\n" + await self._relever_actualites()
            self._dernier = compte_rendu
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox relever] {ex}")
            self._dernier = f"❌ Erreur : `{type(ex).__name__}` — {ex}"
            try:
                await self.render_to(i, edit=True)
            except Exception:
                pass

    async def _relever_actualites(self) -> str:
        """Relève les 5 sources d'actualité et publie ce qui doit sortir.

        Rend un compte-rendu qui NOMME la cause quand rien ne sort. Une source
        à la fois, avec pause — c'est la concurrence que le pare-feu punit.
        """
        try:
            c = await news.config(self.g.id)
            if not c.get("roblox_news_enabled"):
                return ("📢 Actualités — ⚪ **éteintes**, rien n'a été relevé. "
                        "Allumez-les avec le bouton « Actus ».")
            salon = self.g.get_channel(int(c.get("roblox_news_salon", 0) or 0))
            if salon is None:
                return ("📢 Actualités — 🔴 **aucun salon réglé**, rien ne peut "
                        "sortir. Réglez « 📢 Actualité Roblox » ci-dessus.")

            lus, envoyes, deja, refuses, en_panne, pointeurs = 0, 0, 0, 0, [], 0
            absorbes = 0
            simules = 0
            #  La simulation est un réglage de la VEILLE, pas des actualités :
            #  un seul interrupteur pour les deux flux, comme le panneau
            #  l'annonce (« rien ne partira dans un salon »).
            _simu_actu = bool((await veille.config(self.g.id))
                              .get("roblox_veille_simulation"))
            for src in news.SOURCES:
                #  ⚠️ `forcer=True` : un bouton de vérification qui respecterait
                #  la cadence dirait « 0 lu » sur une source relevée dix minutes
                #  plus tôt, et on la croirait morte.
                rel = await news.relever(src, forcer=True)
                if rel["code"] != 200:
                    en_panne.append(f"`{src['cle']}` ({_ou_tiret(rel['code'])})")
                    await asyncio.sleep(1.5)
                    continue
                lus += len(rel["billets"])
                pointeurs += int(rel.get("pointeurs") or 0)
                #  ⚠️ MÊME ORDRE QUE LA BOUCLE, ET C'EST OBLIGATOIRE :
                #  dédupliquer, absorber les trop vieux, PUIS tronquer. La
                #  version précédente tronquait en premier — un billet déjà
                #  sorti gardait une des cinq places à chaque relevé, et le
                #  rang 6 n'y remontait jamais (voir `news.absorber_vieux`).
                #  Deux chemins de publication qui divergent, c'est un défaut
                #  corrigé d'un côté et vivant de l'autre.
                _neufs = []
                for b in (rel.get("billets") or []):
                    if await news.deja_publie(self.g.id, b["topic_id"]):
                        deja += 1
                    else:
                        _neufs.append(b)
                _frais_b, _abs = await news.absorber_vieux(self.g.id, _neufs)
                absorbes += _abs
                #  Du plus ancien au plus récent, et le même plafond par source.
                for b in veille.ordonner_publication(
                        _frais_b, news.MAX_BILLETS_PAR_PASSAGE):
                    if envoyes >= veille.MAX_PUBLICATIONS_PAR_PASSAGE:
                        break
                    #  ⚠️ LA SIMULATION COUVRE AUSSI LES ACTUALITÉS. Elle ne
                    #  gardait que les accessoires, pendant que ce panneau
                    #  affirmait « rien ne partira dans un salon » : un clic
                    #  sur « Relever maintenant », simulation allumée, et les
                    #  billets partaient quand même. On ne les marque pas
                    #  publiés : ils ressortiront à l'extinction.
                    if _simu_actu:
                        simules += 1
                        continue
                    if await publier_actu(self.g, salon, b):
                        await news.marquer_publie(self.g.id, b["topic_id"])
                        envoyes += 1
                    else:
                        refuses += 1
                await asyncio.sleep(1.5)
            await news.purger()

            detail = []
            if simules:
                detail.append(f"`{simules}` retenue(s) : **mode simulation "
                              f"actif** — rien n'est parti, elles ressortiront "
                              f"quand vous l'éteindrez")
            if en_panne:
                detail.append(f"source(s) en panne : {', '.join(en_panne)}")
            if refuses:
                detail.append(f"`{refuses}` **refusée(s) par Discord** — permissions "
                              f"du salon (voir les journaux)")
            if deja:
                detail.append(f"`{deja}` déjà publiée(s) — « ♻️ Tout republier » "
                              f"les libère")
            if absorbes:
                #  ⚠️ LE DIRE PLUTÔT QUE DE LE TAIRE. Ces billets ne sortiront
                #  jamais : ils sont marqués sortis sans avoir été envoyés,
                #  parce qu'au-delà de la garde ce n'est plus une nouvelle.
                #  Un compteur muet ferait croire qu'ils vont venir.
                detail.append(f"`{absorbes}` trop vieux (> {news.AMORCE_GARDE_JOURS} j) — "
                              f"absorbé(s) sans envoi, ils ne reviendront pas")
            if pointeurs:
                detail.append(f"`{pointeurs}` billet(s) « allez voir ce lien » "
                              f"écarté(s) — sans contenu propre, ils n'apprennent rien")
            panne = bool(en_panne or refuses)
            icone = "🔴" if panne else ("🟢" if envoyes else "⚪")
            txt = (f"📢 Actualités — {icone} `{lus}` billet(s) frais lus, "
                   f"`{envoyes}` **réellement publié(s)**.")
            if detail:
                txt += "\n" + "\n".join(f"-# • {d}." for d in detail)
            elif not envoyes:
                txt += ("\n-# • Rien de neuf depuis le dernier passage : "
                        "c'est normal, le forum publie environ un billet par jour.")
            return txt
        except Exception as ex:
            _log(f"[roblox relever actualites] {ex}")
            return f"📢 Actualités — ❌ erreur : `{type(ex).__name__}`"

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
        if motifs.get("simulation"):
            detail.append(f"`{motifs['simulation']}` retenue(s) : **mode "
                          f"simulation actif** — rien n'est parti, les fiches "
                          f"attendent en file et sortiront quand vous "
                          f"l'éteindrez")
        if motifs["envoi"]:
            #  ⚠️ « ressortiront au prochain relevé » N'ÉTAIT PAS VRAI avant la
            #  file d'attente : l'article était déjà en base, la tranche
            #  l'écartait, et il ne revenait jamais. Depuis le 30/08 la ligne
            #  reste en file et l'affirmation est exacte — bornée par
            #  `MAX_ESSAIS_ENVOI`, sinon un salon supprimé la ferait grossir
            #  sans fin.
            detail.append(f"`{motifs['envoi']}` **refusée(s) par Discord** — "
                          f"permissions du salon (voir les journaux). Ces "
                          f"fiches restent en file et seront réessayées "
                          f"(`{veille.MAX_ESSAIS_ENVOI}` essais au plus)")
        if motifs["deja"]:
            detail.append(f"`{motifs['deja']}` déjà publié(e)(s) — « ♻️ Tout "
                          f"republier » les libère")
        if motifs["age"]:
            detail.append(f"`{motifs['age']}` pas assez récent(s) — seuls ce qui "
                          f"est créé ou passe Limited depuis moins de "
                          f"`{veille.FENETRE_DIRECTE_HEURES}` h est publié")
        if motifs.get("seuil"):
            detail.append(f"`{motifs['seuil']}` sous le seuil d'indice")

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
            #  Les actualités ont leur propre table de marques : sans cette
            #  ligne, le bouton disait « tout republier » et n'effaçait que
            #  la moitié.
            n_news = await news.oublier_publies(self.g.id)
            #  ⚠️ ET LES FICHES ABANDONNÉES, QUE CE BOUTON NE TOUCHAIT PAS.
            #  Une fiche ayant échoué `MAX_ESSAIS_ENVOI` fois — salon supprimé,
            #  permission retirée — sortait de la file pour toujours :
            #  `enfiler` refuse de la réinsérer (contrainte d'unicité) et
            #  `oublier_publies` n'efface que `roblox_publies`. Le staff
            #  réparait la permission et rien ne revenait. C'est ici que le
            #  chemin de retour a sa place : c'est LE bouton « débloque tout ».
            n_file = await veille.relancer_abandonnees(self.g.id)
            self._dernier = (
                f"♻️ `{n}` marque(s) d'article et `{n_news}` marque(s) "
                f"d'actualité effacée(s). Ce qui est déjà connu peut de nouveau "
                f"sortir.\n"
                + (f"-# `{n_file}` fiche(s) abandonnée(s) après "
                   f"`{veille.MAX_ESSAIS_ENVOI}` échecs d'envoi ont été "
                   f"remises en file.\n" if n_file else "")
                + f"-# Cliquez « Relever maintenant » — ils sortiront par "
                  f"paquets de `{veille.MAX_PUBLICATIONS_PAR_PASSAGE}`, jamais "
                  f"d'un bloc.")
            await self.render_to(i, edit=True)
        except Exception as ex:
            _log(f"[roblox oublier] {ex}")

    async def _cb_retour(self, i):
        if _retour_configure is not None:
            await _retour_configure(self.u, self.g, i)
        else:
            await i.response.defer()
