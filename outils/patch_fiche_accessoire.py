"""Réécrit la fiche d'ACCESSOIRE : légère, et elle dit ce qui vient d'arriver.

Consignes du propriétaire (18/08), mot pour mot :
  « uniquement les accessoires qui deviennent limited ou limited U, pas ceux
    qui le sont déjà devenus, et les nouveaux accessoires créés par Roblox.
    Ce sera tout pour les accessoires. Un post comme les annonces, au propre,
    avec l'image de l'accessoire, qu'on peut aller voir le modèle, une légère
    description, le prix d'origine, tout parfait. »
  « tu dis bien qu'il VIENT de passer Limited »

Ce qui change :
  · l'en-tête nomme l'événement : « VIENT DE PASSER LIMITED » (ou LIMITED U),
    « NOUVEL ACCESSOIRE ROBLOX » — plus de « passés collectionnables » vague ;
  · une courte description (celle de Roblox, en français quand elle existe) ;
  · prix d'origine ; pour un Limited : revente la plus basse, stock émis, et le
    rapport revente / prix — le chiffre qui évite de se faire avoir ;
  · le bloc « indice » disparaît : le flux « à surveiller » ne publie plus ;
  · les annonces liées (forum, newsroom) en bouton « 📰 Annonce » ;
  · image en vignette (le propriétaire l'a demandée « pas trop grande »).

Écrit dans un fichier — piège n°3. `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "roblox_panneau.py"

DEBUT = "def construire_fiche(article: dict, flux: str, image: str | None = None,"
FIN = "async def _envoyer(salon, profil: str, vue: LayoutView, etiquette: str) -> bool:"

NOUVEAU = '''def construire_fiche(article: dict, flux: str, image: str | None = None,
                     lies: list | None = None) -> LayoutView:
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
        etiquette = ("VIENT DE PASSER LIMITED U" if limited_u
                     else "VIENT DE PASSER LIMITED")
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
    titre = f"{nom_fr}\\n-# {nom_en}" if nom_fr else nom_en

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
    items.append(v2_body("\\n".join(lignes)))

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
    if boutons:
        items.append(discord.ui.ActionRow(*boutons[:5]))
    elif not lien:
        #  Identifiant illisible : on publie SANS lien plutôt qu'avec un lien
        #  approximatif. Voir ROBLOX.md §1 — c'est une règle de sécurité.
        items.append(v2_body("-# Lien indisponible (identifiant illisible)."))

    v = LayoutView(timeout=None)
    v.add_item(v2_container(*items, color=couleur))
    return v


'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    i, j = src.find(DEBUT), src.find(FIN)
    if i == -1 or j == -1 or j <= i:
        print("❌ ancres introuvables — abandon.")
        return 1
    neuf = src[:i] + NOUVEAU + src[j:]
    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    noms = {getattr(n, "name", None) for n in arbre.body}
    for attendu in ("construire_fiche", "construire_actu", "publier", "publier_actu",
                    "RobloxPanelV2", "_horodatage", "_tronquer_propre"):
        if attendu not in noms:
            print(f"❌ {attendu} absent — abandon.")
            return 1
    print(f"  roblox_panneau.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
