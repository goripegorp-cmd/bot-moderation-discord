"""annonces_modifiables.py — modifier une annonce ou un événement DÉJÀ PUBLIÉ, depuis le site de l'équipage (26/10/2026).

Le fondateur : « dans le tableau de bord que tout le monde a accès avec le fameux accueil, l'équipage et ma fiche, fais
en sorte que uniquement nous […] la direction, la fondation, on puisse modifier les annonces qu'on a déjà postées, que
ça se modifie bien, que ça riposte pas une annonce, mais que ça fasse un truc au propre. Que l'affichage soit nickel,
qu'on peut même mettre une bannière au propre avec des dimensions exactes […] Sur le site. »

QUI : la tête seule (fondateur, direction). Les adresses sont sous `/tableau/espace/api/` : une session de portée
« equipage » n'y entre jamais (`tableau._verifier`, 403) ; une écriture exige la tête (`tableau._executer`) et ce module
le revérifie (`evenements._refus` : `_a_la_tete`).

QUOI : le titre, le texte, la bannière (`bannieres.py` : 1600 × 640, 5:2) et les liens d'une annonce ou d'un événement
publié — rien d'autre ici (la date, les rappels, le post se règlent dans l'administration). Le code est CELUI de
l'administration (`evenements.modifier`, `evenements.apercu_modification`) : mêmes règles, mêmes limites.

COMMENT : le message Discord est MODIFIÉ EN PLACE (mêmes identifiants) — jamais republié, jamais un message de plus (un
texte qui en demanderait un de plus est refusé, la raison dite) ; un message supprimé sur Discord est dit tel quel, rien
ne se republie tout seul. Version vérifiée (deux personnes ne s'écrasent jamais : 409). Le verrou de présence est celui
de l'administration (`evenement:<id>`) : l'administration et le site de l'équipage ne modifient jamais la même
publication en même temps (423). Chaque modification va au journal ; la réponse porte l'accueil relu.
"""
from __future__ import annotations

import bannieres
import evenements
import site_equipage

#  Ce que l'éditeur du site de l'équipage peut changer d'une publication (le reste : dans l'administration).
CHAMPS_EDITEUR = ("titre", "texte", "image", "liens")
CLES = frozenset({"id", "version", *CHAMPS_EDITEUR})


def _objet(corps) -> str | None:
    """La clé du verrou de présence : celle de l'administration (`tableau.VERROUS_ROUTES["clan/modifier"]`)."""
    eid = evenements._id(corps.get("id")) if isinstance(corps, dict) else None
    return f"evenement:{eid}" if eid else None


def _filtrer(corps) -> tuple:
    """(corps limité aux champs de l'éditeur, refus | None)."""
    if not isinstance(corps, dict):
        return None, (400, {"erreur": "Corps JSON attendu."})
    autres = sorted(k for k in corps if k not in CLES)
    if autres:
        return None, (400, {"erreur": f"Ce champ ne se modifie pas ici : {autres[0]}.",
                            "champs": {k: "Non modifiable ici." for k in autres}})
    return dict(corps), None


def _limites(type_: str) -> dict:
    return {"titre": evenements.TITRE_MAX, "texte": evenements.TEXTE_MAX[type_], "liens": evenements.LIENS_MAX,
            "lien_nom": evenements.LIEN_NOM_MAX, "lien_url": evenements.LIEN_URL_MAX,
            "composants": evenements.COMPOSANTS_MAX, "caracteres": evenements.CARACTERES_MAX}


async def route_lire(g, auteur, requete, corps):
    """`GET equipage/publication?id=` : la publication telle que l'éditeur la reprend (son texte Discord brut, sa
    bannière, ses liens, sa version), et si elle se modifie encore."""
    refus = evenements._refus(g, auteur)
    if refus:
        return refus
    eid = evenements._id((requete or {}).get("id"))
    if eid is None:
        return 400, {"erreur": "Identifiant invalide.", "champ": "id"}
    e = await evenements.charger(eid)
    if e is None or e["guild_id"] != g.id or e["statut"] in ("brouillon", "envoi"):
        return 404, {"erreur": "Cette publication n'existe plus."}
    v = e["valeurs"]
    site = await evenements._vers_site(g, e)
    return 200, {"publication": {
        "id": e["id"], "type": e["type"], "nom_type": evenements.NOMS_TYPES[e["type"]], "statut": e["statut"],
        "phase": site["phase"], "version": e["version"], "titre": v.get("titre") or "", "texte": v.get("texte") or "",
        "image": v.get("image") or "", "liens": list(v.get("liens") or []), "quand": site["quand"],
        "publie": site["publie"], "lien": site["lien"], "messages": len(e["messages"]),
        "destination": site["destination"], "modifiable": evenements._en_ligne(e),
        "note": e["note"] or ""},
        "limites": _limites(e["type"]), "banniere": bannieres.spec()}


async def route_modifier(g, auteur, requete, corps):
    """`POST equipage/publication` `{id, version, titre?, texte?, image?, liens?}` : la publication modifiée EN PLACE
    sur Discord (`evenements.modifier`), puis l'accueil relu."""
    refus = evenements._refus(g, auteur)
    if refus:
        return refus
    corps, refus = _filtrer(corps)
    if refus:
        return refus
    statut, rep = await evenements.route_modifier(g, auteur, requete, corps)
    if statut != 200:
        return statut, rep
    site_equipage._apres_ecriture(g)   # une bannière changée : l'équipage la voit tout de suite
    el = rep.get("element") or {}
    quoi = "événement" if el.get("type") == "evenement" else "annonce" if el.get("type") == "annonce" else "publication"
    return 200, {**rep, "accueil": await site_equipage._accueil_direction(g),
                 "_journal": f"Site de l'équipage : {quoi} « {el.get('titre') or 'sans titre'} » modifié"
                             f"{'e' if quoi != 'événement' else ''} sur Discord (même message, rien de republié)"}


async def route_apercu(g, auteur, requete, corps):
    """`POST equipage/publication/apercu` (une lecture : rien n'est écrit) : les cartes Discord telles qu'elles seraient
    avec ces changements, et ce qui empêcherait de les enregistrer."""
    refus = evenements._refus(g, auteur)
    if refus:
        return refus
    corps, refus = _filtrer(corps)
    if refus:
        return refus
    statut, rep = await evenements.apercu_modification(g, auteur, corps)
    if statut == 200:   # l'actualité telle que l'équipage la lira sur l'accueil (le texte nettoyé comme le site le fait)
        v = rep.get("valeurs") or {}
        image = v.get("image") if isinstance(v.get("image"), str) else ""
        rep["site"] = {"titre": site_equipage.sans_emoji(v.get("titre")) or evenements.NOMS_TYPES[rep["type"]],
                       "texte": site_equipage.texte_discord(v.get("texte"), g),
                       "image": f"media/{image}" if site_equipage.FORMAT_MEDIA.fullmatch(image or "") else "",
                       "liens": list(v.get("liens") or [])}
    return statut, rep


async def route_retirer(g, auteur, requete, corps):
    """`POST equipage/publication/retirer` `{id}` (28/10/2026, le fondateur : « on peut aussi supprimer les anciens posts
    annonces ») : une annonce retirée — ses messages Discord supprimés — ou un événement annulé, sans prévenir personne
    (le code de l'administration : `evenements.annuler`) ; puis l'accueil relu."""
    refus = evenements._refus(g, auteur)
    if refus:
        return refus
    eid = evenements._id(corps.get("id")) if isinstance(corps, dict) else None
    if eid is None:
        return 400, {"erreur": "Identifiant manquant.", "champ": "id"}
    statut, rep = await evenements.annuler(g, auteur, eid, prevenir=False)
    if statut != 200:
        return statut, rep
    site_equipage._apres_ecriture(g)
    el = rep.get("element") or {}
    quoi = "événement annulé" if el.get("type") == "evenement" else "annonce retirée de Discord"
    return 200, {**rep, "accueil": await site_equipage._accueil_direction(g),
                 "_journal": None if rep.get("deja") else f"Site de l'équipage : {quoi} « {el.get('titre') or 'sans titre'} »"}


ROUTES_SITE = {
    "equipage/publication/retirer": {"methode": "POST", "fn": route_retirer, "ecriture": True, "corps_max": 256,
                                     "verrou": _objet},
    "equipage/publication": [
        {"methode": "GET", "fn": route_lire, "corps_max": 0},
        {"methode": "POST", "fn": route_modifier, "ecriture": True, "corps_max": evenements.TAILLE_CORPS,
         "verrou": _objet},
    ],
    "equipage/publication/apercu": {"methode": "POST", "fn": route_apercu, "ecriture": False,
                                    "corps_max": evenements.TAILLE_CORPS},
}

__all__ = ["ROUTES_SITE", "CHAMPS_EDITEUR", "route_lire", "route_modifier", "route_apercu", "route_retirer"]
