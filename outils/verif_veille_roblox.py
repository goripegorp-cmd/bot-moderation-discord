"""Vérification opérationnelle de bout en bout de la veille Roblox.

Le propriétaire demande : « est-ce que tout est bien opérationnel ? »
La règle du dépôt interdit d'y répondre autrement qu'en suivant la chaîne
jusqu'à un effet réel. Ce script la suit, étape par étape, et dit à chaque
maillon ce qui est PROUVÉ et ce qui ne l'est pas.

Il appelle la VRAIE API Roblox. Il n'envoie rien sur Discord : le dernier
maillon — un message qui atterrit dans un salon — ne peut se prouver qu'en
jeu, et ce script le dit au lieu de le supposer.

Usage :
    PYTHONIOENCODING=utf-8 python outils/verif_veille_roblox.py
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiosqlite  # noqa: E402

import roblox_panneau as panneau  # noqa: E402
import roblox_veille as veille  # noqa: E402
import roblox_news as news  # noqa: E402

RESULTATS: list[tuple[str, bool | None, str]] = []


def note(etape: str, ok: bool | None, detail: str = "") -> None:
    """`None` = non vérifiable ici, et c'est une réponse valable."""
    RESULTATS.append((etape, ok, detail))
    icone = "✅" if ok else ("❌" if ok is False else "⚠️ ")
    print(f"  {icone} {etape}")
    if detail:
        print(f"      {detail}")


def _compter(payload) -> int:
    n = 0
    for c in payload:
        n += 1
        n += _compter(c.get("components", []) or [])
    return n


async def main() -> int:
    chemin = os.path.join(tempfile.mkdtemp(), "verif.db")

    @contextlib.asynccontextmanager
    async def get_db():
        db = await aiosqlite.connect(chemin)
        try:
            yield db
        finally:
            await db.close()

    async def cfg(gid):
        return {}

    async def db_set(gid, k, v):
        return None

    veille.setup(get_db=get_db, cfg=cfg, db_set=db_set, session=None,
                 log=lambda *a: None)
    panneau.setup(db_set=None, webhook_send=None, log=lambda *a: None)
    news.setup(get_db=get_db, cfg=cfg, db_set=db_set, log=lambda *a: None)
    await veille.init_db()
    await news.init_db()

    # ── 1. Le catalogue complet ────────────────────────────────────────────
    print("\n═══ 1. RELEVÉ DU CATALOGUE (accessoires créés par Roblox) ═══")
    cat = await veille.relever_nouveautes(limite=120)
    note("le catalogue répond", cat["code"] == 200, f"HTTP {cat['code']}")
    note("la pagination va au bout", bool(cat["complet"]),
         f"{len(cat['articles'])} articles en {cat['pages']} page(s)")
    note("le volume correspond au catalogue réel", len(cat["articles"]) > 900,
         f"{len(cat['articles'])} articles (mesuré le 16/08 : 964)")

    await asyncio.sleep(veille.PAUSE_ENTRE_RELEVES)

    # ── 2. Le flux des collectionnables ────────────────────────────────────
    print("\n═══ 2. RELEVÉ DES LIMITEDS ═══")
    lim = await veille.relever_collectionnables(limite=120)
    note("le flux Limited répond", lim["code"] == 200, f"HTTP {lim['code']}")
    tous_coll = all(a["collectionnable"] for a in lim["articles"])
    note("tous les articles rendus sont bien collectionnables", tous_coll,
         f"{len(lim['articles'])} articles, "
         f"{sum(1 for a in lim['articles'] if a['collectionnable'])} Limited")
    ids_cat = {a["asset_id"] for a in cat["articles"]}
    invisibles = [a for a in lim["articles"] if a["asset_id"] not in ids_cat]
    note("ce flux voit ce que le catalogue ne voit pas", bool(invisibles),
         f"{len(invisibles)} Limited(s) absents du catalogue général")

    # ── 3. La règle « VIENT de passer » (18/08) ────────────────────────────
    print("\n═══ 3. RÈGLE DE PUBLICATION — « vient de passer », « créé à partir "
          "de maintenant » ═══")
    #  Un Limited vu déjà collectionnable n'est PAS une bascule : il ne sort
    #  pas, quel que soit son âge. Seul `bascule_detectee` fait sortir.
    republies = [a for a in lim["articles"] if veille.age_publiable(a, "bascules")]
    note("aucun Limited déjà collectionnable n'est republié", not republies,
         f"{len(lim['articles'])} Limited(s) relevés, {len(republies)} publiable(s) "
         f"— tous enregistrés, aucun publié : ils sont « déjà devenus »")
    if lim["articles"]:
        simule = dict(lim["articles"][0], bascule_detectee=True)
        note("une bascule vue en direct passe, elle", veille.age_publiable(simule, "bascules"),
             "marqueur `bascule_detectee` posé par comparer_et_enregistrer")
    #  Les nouveautés : créées il y a moins de FENETRE_DIRECTE_HEURES seulement.
    recentes = [a for a in cat["articles"] if veille.age_publiable(a, "nouveautes")]
    plus_recent_h = min((veille._heures_depuis(a.get("cree_le")) or 1e9
                         for a in cat["articles"]), default=None)
    note("les nouveautés ne passent que si créées à l'instant",
         all((veille._heures_depuis(a.get("cree_le")) or 1e9) <= veille.FENETRE_DIRECTE_HEURES
             for a in recentes),
         f"{len(recentes)} publiable(s) sur {len(cat['articles'])} · le plus récent du "
         f"catalogue date de {plus_recent_h:.1f} h" if plus_recent_h is not None else "—")

    # ── 4. L'ordre de publication ──────────────────────────────────────────
    print("\n═══ 4. ORDRE DE PUBLICATION ═══")
    lot = veille.ordonner_publication(lim["articles"], 12)
    dates = [str(a.get("cree_le") or "") for a in lot]
    note("l'envoi va du plus ancien au plus récent", dates == sorted(dates),
         f"{len(lot)} fiche(s) dans un paquet d'essai")

    # ── 5. Les chiffres de trading ─────────────────────────────────────────
    print("\n═══ 5. ENRICHISSEMENT (stock, revente, multiplicateur) ═══")
    echantillon = lot[:3]
    #  La même respiration que la boucle réelle : sans elle, ces appels
    #  tombent en plein 429 après les deux relevés paginés.
    print(f"      (pause de {veille.PAUSE_AVANT_FICHES:.0f} s — débit)")
    await asyncio.sleep(veille.PAUSE_AVANT_FICHES)
    await veille.enrichir(echantillon)
    #  ⚠️ ON VÉRIFIE LA DONNÉE QUI ATTERRIT SUR LA FICHE, PAS SA PROVENANCE.
    #  Les Assets tiennent leurs chiffres de l'API économie (`stock`,
    #  `revente`) ; les Bundles n'ont pas de fiche économie et tiennent les
    #  leurs du catalogue (`quantite`, `prix_revente`). Une première version
    #  de ce contrôle ne regardait que les clés « économie » et annonçait
    #  0/3 alors que les trois fiches affichaient bien leurs chiffres — un
    #  vérificateur qui ment est pire que pas de vérificateur.
    avec_stock = [a for a in echantillon
                  if a.get("stock") or a.get("quantite")]
    avec_revente = [a for a in echantillon
                    if a.get("revente") or a.get("prix_revente")]
    bundles = sum(1 for a in echantillon
                  if str(a.get("item_type") or "").lower() == "bundle")
    note("le stock émis est disponible", bool(avec_stock),
         f"{len(avec_stock)}/{len(echantillon)} ({bundles} bundle(s) — "
         f"chiffres pris au catalogue, ils n'ont pas de fiche économie)")
    note("le prix de revente est disponible", bool(avec_revente),
         f"{len(avec_revente)}/{len(echantillon)}")
    for a in echantillon:
        m = a.get("multiplicateur")
        if m is not None:
            print(f"      {a['nom'][:32]:<34} ×{m}  "
                  f"({a.get('prix')} R$ → {a.get('revente')} R$)")

    # ── 6. L'indice ────────────────────────────────────────────────────────
    print("\n═══ 6. INDICE (faits observés, PAS une prédiction) ═══")
    for a in echantillon:
        ind = veille.indice(a)
        print(f"      {a['nom'][:30]:<32} {ind['note']:>3}/100 "
              f"· confiance {ind['confiance']}")
        for lib, pts in ind["facteurs"]:
            print(f"          {pts:+3d}  {lib}")
    note("l'indice affiche toujours ses facteurs",
         all(veille.indice(a)["facteurs"] or veille.indice(a)["note"] == 0
             for a in echantillon))

    # ── 7. La fiche ────────────────────────────────────────────────────────
    print("\n═══ 7. LA FICHE ═══")
    #  On passe les ARTICLES, pas les identifiants : c'est `item_type` qui
    #  dit s'il faut le point « assets » ou le point « bundles ».
    imgs = await veille.vignettes(echantillon)
    note("les vignettes sont récupérées en lot", bool(imgs),
         f"{len(imgs)}/{len(echantillon)} images")
    ok_fiches, max_comp = True, 0
    for a in echantillon:
        vue = panneau.construire_fiche(a, "bascules",
                                       image=imgs.get(a["asset_id"]))
        p = vue.to_components()
        max_comp = max(max_comp, _compter(p))
        if not p or _compter(p) > 40 or not vue.has_components_v2():
            ok_fiches = False
    note("les fiches se sérialisent sous les limites de l'API", ok_fiches,
         f"{max_comp} composants au maximum, sur 40 autorisés")

    # ── 8. La séparation des flux ──────────────────────────────────────────
    print("\n═══ 8. SÉPARATION DES TROIS FLUX ═══")
    await veille.marquer_publie(1, 4242, "bascules")
    sep = (not await veille.publiable_dans(1, 4242, "surveiller")
           and not await veille.publiable_dans(1, 4242, "nouveautes"))
    note("une bascule bloque les flux plus faibles", sep)
    await veille.marquer_publie(1, 4243, "nouveautes")
    note("une nouveauté n'empêche pas une bascule plus tard",
         await veille.publiable_dans(1, 4243, "bascules"))

    # ── 8 bis. Les ACTUALITÉS — toutes les sources, forcées ───────────────
    print("\n═══ 8 bis. ACTUALITÉS — 8 sources officielles ═══")
    total_frais, en_panne, fr_titres = 0, [], 0
    for src in news.SOURCES:
        rel = await news.relever(src, forcer=True)
        if rel["code"] != 200:
            en_panne.append(f"{src['cle']} ({rel['code']})")
        total_frais += len(rel["billets"])
        if src["cle"] == "newsroom_fr":
            fr_titres = sum(1 for b in rel["billets"]
                            if any(ch in (b.get("titre") or "") for ch in "éèàçêù"))
        print(f"      {src['cle']:<12} {src['format']:<9} HTTP {rel['code']}  "
              f"{len(rel['billets']):>2} frais")
        await asyncio.sleep(2)
    note(f"les {len(news.SOURCES)} sources répondent", not en_panne,
         "toutes en HTTP 200" if not en_panne else "en panne : " + ", ".join(en_panne))
    note("il y a des actualités fraîches à publier", total_frais > 0,
         f"{total_frais} billet(s) de moins de {news.FRAICHEUR_MAX_JOURS} jours")
    note("la salle de presse FRANÇAISE rend des titres en français", fr_titres > 0,
         f"{fr_titres} titre(s) accentué(s) — Roblox traduit, on cite")
    #  Une fiche d'actualité se sérialise aussi sous les limites.
    src_fr = next(s_ for s_ in news.SOURCES if s_["cle"] == "newsroom_fr")
    rel_fr = await news.relever(src_fr, forcer=True)
    if rel_fr["billets"]:
        v = panneau.construire_actu(rel_fr["billets"][0])
        note("la fiche d'actualité se sérialise sous les limites",
             bool(v.to_components()) and _compter(v.to_components()) <= 40
             and v.has_components_v2(),
             f"{_compter(v.to_components())} composants · lien "
             f"{(rel_fr['billets'][0].get('lien') or '—')[:60]}")

    # ── 9. Le maillon qu'on ne peut PAS prouver ici ────────────────────────
    print("\n═══ 9. L'ENVOI DISCORD ═══")
    note("un message atterrit dans un salon", None,
         "NON VÉRIFIABLE d'ici — mais OBSERVÉ le 18/08/2026 : le propriétaire "
         "a envoyé une capture du salon avec les fiches « Salle de presse (FR) » "
         "et « Newsroom Roblox » publiées par le bot. Le maillon que le HANDOFF "
         "déclarait jamais vu l'a été. Ce script ne peut que le rappeler.")

    # ── Verdict ────────────────────────────────────────────────────────────
    print(f"\n{'═' * 68}")
    ok = sum(1 for _, s, _ in RESULTATS if s is True)
    ko = sum(1 for _, s, _ in RESULTATS if s is False)
    na = sum(1 for _, s, _ in RESULTATS if s is None)
    print(f"  {ok} vérifié(s) · {ko} en échec · {na} non vérifiable(s) ici")
    if ko:
        print("\n  ❌ EN ÉCHEC :")
        for etape, statut, detail in RESULTATS:
            if statut is False:
                print(f"      {etape} — {detail}")
    print(f"{'═' * 68}")
    return 1 if ko else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
