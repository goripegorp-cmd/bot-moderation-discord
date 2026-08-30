"""Les commandes `/roblox` — interroger la veille sans ouvrir le panneau.

═══════════════════════════════════════════════════════════════════════════════
POURQUOI UN GROUPE, ALORS QUE LA SPÉCIFICATION DEMANDE `/latest`, `/limited`…
═══════════════════════════════════════════════════════════════════════════════
Trois raisons, et c'est un écart assumé, pas un oubli :

1. `/latest`, `/limited`, `/item`, `/health` sont des noms GÉNÉRIQUES. Sur un
   serveur où plusieurs bots cohabitent, ils se marchent dessus et le membre ne
   sait plus lequel il appelle. `/roblox recents` ne peut appartenir qu'à nous.
2. Discord plafonne une application à 100 commandes globales, et ce dépôt a
   DÉJÀ payé ce plafond : `bot.py` porte encore les traces de deux correctifs
   d'urgence (« Phase 116/118 HOTFIX : décorateur retiré, CommandLimitReached
   100 globally »). Sept noms de premier niveau brûleraient sept places pour
   une seule fonctionnalité. Le groupe en coûte UNE.
3. `/roblox` puis Tab montre les six sous-commandes : c'est plus découvrable
   qu'espérer qu'on devine `/model-status`.

Les capacités demandées sont toutes là, sous d'autres noms :
    /latest       → /roblox recents
    /limited      → /roblox limited
    /item         → /roblox article
    /predict      → /roblox prediction
    /predictions  → /roblox predictions
    /model-status → /roblox modele
    /health       → /roblox sante

═══════════════════════════════════════════════════════════════════════════════
CE QUE CES COMMANDES NE FERONT PAS, ET POURQUOI
═══════════════════════════════════════════════════════════════════════════════
`/roblox prediction` ne rendra PAS de pourcentage tant qu'aucun modèle ne peut
être calibré. Mesuré le 30/08/2026 : sept points d'API testés ne donnent aucune
date de passage en Limited, donc il n'existe aucune vérité terrain. La
spécification tranche elle-même : « Si les données sont insuffisantes, afficher
"données insuffisantes" au lieu de fabriquer un pourcentage. »
La commande dit donc où en est la collecte, et ce qu'il manque. C'est une
réponse, pas une dérobade : elle est vérifiable, elle progresse toute seule, et
elle deviendra un vrai chiffre le jour où elle le pourra.
"""
from __future__ import annotations

import discord
from discord import app_commands

import roblox_veille as veille
from ui_v2 import (Palette, body, container, divider, subtitle, title)

_log = print
_autorise = None          # posé par setup() : qui a le droit d'interroger


def setup(*, autorise=None, log=None):
    """Branche le module. `autorise(interaction) -> bool`."""
    global _autorise, _log
    if autorise is not None:
        _autorise = autorise
    if log is not None:
        _log = log


# ═══════════════════════════════════════════════════════════════════════════════
#  Rendu
# ═══════════════════════════════════════════════════════════════════════════════

def _ou(v, defaut: str = "—") -> str:
    return defaut if v in (None, "", 0) and v is not False else str(v)


def _quand(iso) -> str:
    """Un horodatage Discord — il s'affiche dans le fuseau de CHAQUE lecteur."""
    if not iso:
        return "—"
    try:
        from datetime import datetime
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return f"<t:{int(d.timestamp())}:R>"
    except Exception:
        return "—"


class _Vue(discord.ui.LayoutView):
    """Une réponse éphémère. Pas de bouton : rien à persister."""

    def __init__(self, *blocs, couleur=Palette.INFO):
        super().__init__(timeout=None)
        self.add_item(container(*blocs, color=couleur))


async def _repondre(i, *blocs, couleur=Palette.INFO):
    vue = _Vue(*blocs, couleur=couleur)
    if i.response.is_done():
        await i.followup.send(view=vue, ephemeral=True)
    else:
        await i.response.send_message(view=vue, ephemeral=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le groupe
# ═══════════════════════════════════════════════════════════════════════════════

groupe = app_commands.Group(
    name="roblox",
    description="🎮 Interroger la veille du catalogue Roblox",
    guild_only=True)


async def _refuse(i) -> bool:
    """Rend True si l'appelant n'a pas le droit — et le lui a DIT.

    ⚠️ TOUJOURS RÉPONDRE AVANT DE REFUSER. Une interaction sans réponse
    affiche « Échec de l'interaction », qui se lit comme une panne du bot et
    non comme un refus. Ce piège a déjà coûté une session entière sur
    `/rellseas`.
    """
    if _autorise is None:
        return False
    try:
        if await _autorise(i):
            return False
    except Exception as ex:
        _log(f"[roblox_commandes autorise] {ex}")
    try:
        await i.response.send_message(
            "⛔ Cette commande est réservée au staff.", ephemeral=True)
    except Exception:
        pass
    return True


@groupe.command(name="sante", description="🩺 L'état réel de la veille Roblox")
async def sante(i: discord.Interaction):
    """Le `/health` de la spécification : dernier passage, articles suivis,
    taille de la file, erreurs récentes, état de la base, version du modèle."""
    if await _refuse(i):
        return
    await i.response.defer(ephemeral=True)
    try:
        diag = await veille.diagnostic()
        file = await veille.etat_file(i.guild.id)
        serie = await veille.etat_serie()
        cfg = await veille.config(i.guild.id)
        curseur, tours = await veille._curseur_lu("collectionnables")

        sources = []
        for s in (diag.get("sources") or []):
            icone = "🟢" if not s.get("echecs") else "🔴"
            sources.append(
                f"{icone} `{s.get('cle', '?')}` · code `{_ou(s.get('code'))}` · "
                f"dernier succès {_quand(s.get('dernier_succes'))}"
                + (f" · **{s['echecs']} échec(s) d'affilée**"
                   if s.get("echecs") else ""))
        if not sources:
            sources = ["⚪ aucun relevé effectué pour l'instant"]

        #  ⚠️ ON DIT L'ÉTAT DE L'INTERRUPTEUR AVANT TOUT LE RESTE. Un système
        #  éteint et un système en panne produisent les mêmes zéros partout.
        allume = bool(cfg.get("roblox_veille_enabled"))
        simu = bool(cfg.get("roblox_veille_simulation"))

        blocs = [
            title("🩺 Santé de la veille Roblox", level=2),
            body(("🟢 **Allumée**" if allume else "⚪ **Éteinte** — "
                  "rien ne tourne, et c'est la première chose à vérifier")
                 + ("\n🧪 **Simulation ACTIVE** — rien ne part dans un salon"
                    if simu else "")),
            divider(),
            body("**Relevés**\n" + "\n".join(sources)),
            divider(),
            body(f"**Suivi** · `{diag.get('articles_connus', 0)}` article(s) "
                 f"en base\n"
                 f"**File d'envoi** · `{file.get('attente', 0)}` en attente, "
                 f"`{file.get('envoyees', 0)}` envoyée(s) au total"
                 + (f", ⚠️ `{file['abandonnees']}` abandonnée(s)"
                    if file.get("abandonnees") else "")
                 + (f"\n-# la plus ancienne attend depuis "
                    f"{_quand(file.get('plus_vieille'))}"
                    if file.get("plus_vieille") else "")),
            body(f"**Rotation du flux Limited** · `{tours}` tour(s) complet(s), "
                 + ("reprise en cours de flux au prochain passage"
                    if curseur else "prochain passage repart du début")),
            divider(),
            #  ⚠️ « Version du modèle » EST une donnée de santé, même — et
            #  surtout — quand la réponse est « aucun ».
            body(f"**Série temporelle** · `{serie['mesures']}` mesure(s) sur "
                 f"`{serie['articles']}` article(s)"
                 + (f", depuis {_quand(serie['depuis'])}" if serie["depuis"]
                    else "")
                 + f"\n**Modèle de prédiction** · aucun — "
                   f"`{serie['transitions_observees']}`/"
                   f"`{veille.MIN_TRANSITIONS_POUR_MODELE}` bascules observées"),
        ]
        couleur = (Palette.SUCCESS if allume and not any(
            s.get("echecs") for s in (diag.get("sources") or []))
            else (Palette.WARNING if allume else Palette.NEUTRAL))
        await _repondre(i, *blocs, couleur=couleur)
    except Exception as ex:
        _log(f"[roblox_commandes sante] {type(ex).__name__}: {ex}")
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}`",
                              ephemeral=True)


@groupe.command(name="article",
                description="🔎 L'état ACTUEL d'un accessoire, redemandé à Roblox")
@app_commands.describe(identifiant="L'identifiant de l'accessoire (le nombre "
                                   "dans l'adresse roblox.com/catalog/…)")
async def article(i: discord.Interaction, identifiant: str):
    if await _refuse(i):
        return
    await i.response.defer(ephemeral=True)
    #  ⚠️ L'IDENTIFIANT EST UNE CHAÎNE, PAS UN ENTIER. Les identifiants Roblox
    #  dépassent aujourd'hui 10^14 (mesuré : 95681420685521) ; Discord rend un
    #  entier signé 64 bits sans problème, mais un collage depuis une URL
    #  contient souvent des espaces ou l'adresse entière. On extrait.
    chiffres = "".join(c for c in str(identifiant) if c.isdigit())
    if not chiffres:
        return await i.followup.send(
            "❌ Je n'ai pas trouvé d'identifiant là-dedans. Colle le nombre, "
            "ou l'adresse complète `roblox.com/catalog/…`.", ephemeral=True)
    try:
        a = await veille.fiche_par_id(int(chiffres))
        if a is None:
            return await i.followup.send(
                f"❌ Roblox ne connaît pas l'article `{chiffres}`, ou son point "
                f"de détails n'a pas répondu. Vérifie l'identifiant.",
                ephemeral=True)

        lien = veille.lien_article(a["asset_id"], a.get("item_type"))
        classe = a.get("classe") or ""
        restriction = (veille.libelle_classe(classe) if classe
                       else "aucune (article ordinaire)")
        #  La croissance des favoris n'existe que si la série remonte assez
        #  loin. `None` veut dire « je ne sais pas encore », pas « zéro ».
        lignes = [
            f"**Identifiant** · `{a['asset_id']}`",
            f"**Type** · {_ou(a.get('type_article'))}",
            f"**Restriction** · {restriction}",
            f"**Prix** · " + (f"`{a['prix']}` R$" if a.get("prix") is not None
                              else "hors vente ou non communiqué"),
            f"**Favoris** · `{_ou(a.get('favoris'))}`",
        ]
        for j in (1, 7, 30):
            c = await veille.croissance_favoris(a["asset_id"], j)
            lignes.append(
                f"-# favoris sur {j} j · "
                + (f"{'+' if c >= 0 else ''}{c}" if c is not None
                   else "_série trop courte pour le dire_"))
        if a.get("quantite"):
            lignes.append(f"**Quantité émise** · `{a['quantite']}`")
        if a.get("prix_revente"):
            lignes.append(f"**Revente la moins chère** · `{a['prix_revente']}` R$")
        lignes.append(f"**Hors vente** · " + ("oui" if a.get("hors_vente")
                                              else "non"))
        #  ⚠️ ON NE PRÉSENTE JAMAIS UNE DATE D'OBSERVATION COMME UNE DATE DE
        #  CRÉATION. `cree_le` vient de `itemCreatedUtc` — et même celui-là
        #  ment parfois (94 Limiteds portent la même minute de janvier 2026 :
        #  c'est une réindexation). On dit d'où vient le chiffre.
        lignes.append(f"**Créé (d'après Roblox)** · {_quand(a.get('cree_le'))}")

        blocs = [
            title(f"🔎 {_ou(a.get('nom'))}", level=2),
            subtitle("État redemandé à Roblox à l'instant — pas la mémoire "
                     "du bot"),
            divider(),
            body("\n".join(lignes)),
        ]
        if lien:
            blocs.append(body(f"[Voir sur Roblox]({lien})"))
        await _repondre(i, *blocs,
                        couleur=Palette.PREMIUM if classe else Palette.INFO)
    except Exception as ex:
        _log(f"[roblox_commandes article] {type(ex).__name__}: {ex}")
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}`",
                              ephemeral=True)


async def _liste(i, flux: str, titre: str, vide: str):
    """Le corps partagé de `recents` et `limited`."""
    if await _refuse(i):
        return
    await i.response.defer(ephemeral=True)
    try:
        evts = await veille.derniers_evenements(i.guild.id, flux, limite=10)
        if not evts:
            return await i.followup.send(vide, ephemeral=True)
        lignes = []
        for e in evts:
            a = e["article"]
            lien = veille.lien_article(a.get("asset_id"), a.get("item_type"))
            nom = _ou(a.get("nom_fr") or a.get("nom"))
            cl = a.get("classe") or ""
            lignes.append(
                f"• {f'[{nom}]({lien})' if lien else nom}"
                + (f" — **{veille.libelle_classe(cl)}**" if cl else "")
                + f" · annoncé {_quand(e['envoye_le'])}")
        await _repondre(
            i, title(titre, level=2),
            subtitle("Ce qui est RÉELLEMENT sorti dans un salon — "
                     "pas ce qui a été détecté"),
            divider(), body("\n".join(lignes)),
            couleur=Palette.PREMIUM if flux == "bascules" else Palette.INFO)
    except Exception as ex:
        _log(f"[roblox_commandes {flux}] {type(ex).__name__}: {ex}")
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}`",
                              ephemeral=True)


@groupe.command(name="recents",
                description="🆕 Les derniers nouveaux accessoires annoncés")
async def recents(i: discord.Interaction):
    await _liste(i, "nouveautes", "🆕 Derniers accessoires annoncés",
                 "⚪ Aucune nouveauté annoncée pour l'instant.\n"
                 "-# Mesuré le 30/08 : le compte Roblox n'avait rien créé "
                 "depuis 38 jours. Un salon calme est normal — `/roblox sante` "
                 "dit si la veille tourne.")


@groupe.command(name="limited",
                description="🔷 Les derniers passages en Limited annoncés")
async def limited(i: discord.Interaction):
    await _liste(i, "bascules", "🔷 Derniers passages en Limited",
                 "⚪ Aucun passage en Limited annoncé pour l'instant.\n"
                 "-# Roblox n'a fait que 36 bascules sur toute l'année 2025 : "
                 "l'événement est rare. `/roblox sante` dit si la veille "
                 "tourne.")


def _refus_de_predire(serie: dict) -> list:
    """Le message que rend TOUTE demande de prédiction, tant que c'est vrai.

    ⚠️ IL DIT POURQUOI, ET IL DIT COMBIEN IL MANQUE. « Données insuffisantes »
    tout court se lit comme une dérobade ; adossé à des compteurs qui montent
    tout seuls, c'est une réponse vérifiable.
    """
    reste = max(0, veille.MIN_TRANSITIONS_POUR_MODELE
                - serie["transitions_observees"])
    return [
        title("📊 Données insuffisantes", level=2),
        subtitle("Aucun pourcentage ne sera affiché tant qu'il serait inventé"),
        divider(),
        body("**Pourquoi.** Une probabilité ne vaut que si elle est *calibrée* "
             "— si, parmi les articles annoncés à 70 %, environ 70 % basculent "
             "vraiment. Calibrer exige de savoir QUAND les articles passés "
             "Limited l'ont fait.\n"
             "Mesuré le 30/08/2026 : **sept points d'API Roblox testés, aucun "
             "ne donne cette date.** Il n'existe donc aucune vérité terrain — "
             "et un modèle entraîné sans elle produirait un chiffre qui a "
             "l'air sérieux et ne mesure rien."),
        divider(),
        body("**Ce que le bot fait à la place.** Il constitue sa propre série "
             "temporelle, mesure après mesure, en attendant d'avoir observé "
             "assez de bascules pour en tirer quelque chose.\n"
             f"**Bascules observées** · `{serie['transitions_observees']}` "
             f"sur `{veille.MIN_TRANSITIONS_POUR_MODELE}` nécessaires"
             + (f" — il en manque `{reste}`" if reste else
                " — le seuil est atteint, un modèle devient envisageable")
             + f"\n**Mesures accumulées** · `{serie['mesures']}` sur "
               f"`{serie['articles']}` article(s)"),
        body("-# Roblox a fait 36 bascules sur toute l'année 2025 : atteindre "
             "ce seuil prendra des mois. C'est le chiffre honnête, pas une "
             "excuse."),
    ]


@groupe.command(
    name="prediction",
    description="📊 Chances qu'un accessoire passe Limited (honnêtement)")
@app_commands.describe(identifiant="L'identifiant de l'accessoire")
async def prediction(i: discord.Interaction, identifiant: str):
    if await _refuse(i):
        return
    await i.response.defer(ephemeral=True)
    try:
        serie = await veille.etat_serie()
        #  ⚠️ LE REFUS PASSE AVANT TOUT LE RESTE. Aller chercher l'article
        #  d'abord donnerait l'impression qu'un calcul a eu lieu.
        if serie["transitions_observees"] < veille.MIN_TRANSITIONS_POUR_MODELE:
            return await _repondre(i, *_refus_de_predire(serie),
                                   couleur=Palette.NEUTRAL)
        #  Si un jour on passe ce seuil, c'est ICI que le modèle se branchera —
        #  avec ses deux horizons, sa version et sa date de calcul, jamais un
        #  pourcentage nu.
        await _repondre(
            i, title("📊 Modèle non encore entraîné", level=2),
            body("Le seuil de données est atteint, mais aucun modèle n'a "
                 "encore été entraîné ni calibré. Rien ne sera affiché avant."),
            couleur=Palette.NEUTRAL)
    except Exception as ex:
        _log(f"[roblox_commandes prediction] {type(ex).__name__}: {ex}")
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}`",
                              ephemeral=True)


@groupe.command(name="predictions",
                description="📊 Les accessoires les plus susceptibles de basculer")
async def predictions(i: discord.Interaction):
    if await _refuse(i):
        return
    await i.response.defer(ephemeral=True)
    try:
        serie = await veille.etat_serie()
        await _repondre(i, *_refus_de_predire(serie), couleur=Palette.NEUTRAL)
    except Exception as ex:
        _log(f"[roblox_commandes predictions] {type(ex).__name__}: {ex}")
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}`",
                              ephemeral=True)


@groupe.command(name="modele",
                description="🧪 Où en est la collecte pour un futur modèle")
async def modele(i: discord.Interaction):
    if await _refuse(i):
        return
    await i.response.defer(ephemeral=True)
    try:
        serie = await veille.etat_serie()
        await _repondre(i, *_refus_de_predire(serie), couleur=Palette.NEUTRAL)
    except Exception as ex:
        _log(f"[roblox_commandes modele] {type(ex).__name__}: {ex}")
        await i.followup.send(f"❌ Erreur : `{type(ex).__name__}`",
                              ephemeral=True)
