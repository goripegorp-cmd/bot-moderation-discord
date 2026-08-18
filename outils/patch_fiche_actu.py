"""Réécrit la fiche d'actualité : bilingue, illustrée, complète.

Le propriétaire (18/08) montre l'ancienne fiche qu'il aimait — « c'est comme
ça que tu les transformes, voire même en mieux » :

    MISE À JOUR · Roblox (plateforme & créateurs)
    🟢 Améliorations de l'importation d'animations
    Bonjour les créateurs, aujourd'hui nous introduisons…    ← français d'abord
    🇬🇧 Official (English)
    Animation Import Improvements
    Hi Creators, today we're introducing…                     ← l'original ensuite
    Read the full official article →
    [image pleine largeur]
    🧑‍💼 Mise à jour développeurs · 04/08/2026 18:11

C'est la cible. Et « en mieux » sur quatre points MESURÉS sur l'ancienne :
  · les entités HTML sont décodées — l'ancienne affichait « &hellip; » ;
  · l'horodatage est natif Discord (`<t:…:f>`) — il s'affiche dans le fuseau
    de CHAQUE lecteur, pas en heure serveur ;
  · les vidéos hébergées par le forum se LISENT dans la galerie ; YouTube part
    en bouton (Discord ne lit pas YouTube dans un conteneur V2) ;
  · le budget de texte est calculé, jamais coupé au hasard : Discord refuse
    au-delà de 4 000 caractères de texte par message V2, et l'ancienne
    tronquait en pleine phrase.

La salle de presse FR est en français par Roblox : pas de bloc anglais, pas de
mention de traduction — on cite.

Écrit dans un fichier — piège n°3. `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "roblox_panneau.py"

DEBUT = "def construire_actu(billet: dict) -> LayoutView:"
FIN = "async def publier_actu(guild, salon, billet: dict) -> bool:"

NOUVEAU = '''#  ⚠️ LIMITE DURE : 4 000 caractères de texte au total dans un message V2
#  (somme de tous les TextDisplay). Dépasser = HTTP 400, la fiche ne part pas.
#  On calcule, on ne coupe pas au hasard.
BUDGET_TEXTE_ACTU = 3900
#  Part réservée aux méta (titre, en-tête, mention, date). Le reste va aux
#  corps, français d'abord.
RESERVE_META = 500
#  L'original anglais, abrégé : il est là pour vérifier, pas pour tout relire.
BUDGET_ORIGINAL = 900

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
    for sep in ("\\n\\n", ". ", "! ", "? ", "\\n"):
        i = coupe.rfind(sep)
        if i > budget // 2:
            return coupe[:i + (1 if sep.strip() else 0)].rstrip() + " …"
    return coupe.rsplit(" ", 1)[0].rstrip() + " …"


def construire_actu(billet: dict) -> LayoutView:
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
    if montrer_original:
        budget_orig = min(BUDGET_ORIGINAL, max(300, disponible // 3))
        budget_fr = max(400, disponible - budget_orig)
    else:
        budget_orig, budget_fr = 0, max(400, disponible)
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
        items.append(v2_body(f"**🇬🇧 Original (English)**\\n**{titre_orig}**\\n"
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
        f"-# {mention}\\n"
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
    if boutons:
        items.append(discord.ui.ActionRow(*boutons[:5]))
    elif not lien:
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
    for attendu in ("construire_actu", "publier_actu", "construire_fiche",
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
