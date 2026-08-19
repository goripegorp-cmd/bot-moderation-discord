"""Pourquoi la boucle annonce « 0 publication » — on suit la chaîne, pour de vrai.

LE SYMPTÔME, LOGS RAILWAY DU PROPRIÉTAIRE (19/08/2026)
    [veille_roblox_task] passage terminé — … · 0 publication(s) réelle(s)
répété toutes les 30 minutes pendant onze heures. Et son constat :
    « il y a énormément d'actualités de tous types US français et tout. On a
      toutes les infos mais rien n'est posté »

⚠️ CE QUE CETTE SONDE NE FAIT PAS : conclure depuis le code. « 0 publication »
a au moins six causes, et cinq se ressemblent dans les logs :
    a. les sources ne rendent rien (HTTP ≠ 200, pare-feu, format changé) ;
    b. elles rendent des billets, tous déjà publiés (base) ;
    c. elles rendent des billets, tous jugés « pointeurs » et écartés ;
    d. la cadence par source les saute toutes au même passage ;
    e. le flux est allumé mais sans salon ;
    f. il n'y a réellement RIEN de neuf.
Seule (f) est une bonne nouvelle. On appelle donc les VRAIES sources, sur le
vrai réseau, et on compte à chaque étage.

⚠️ CE QUE LA SONDE NE PEUT PAS VOIR DEPUIS CE POSTE : l'état de la base Railway
(étage b) et la configuration des serveurs (étage e). Ils sont signalés comme
hors de portée — jamais devinés. C'est précisément pour eux que le bilan de la
boucle a été détaillé.

Usage :
    PYTHONIOENCODING=utf-8 python outils/sonde_pourquoi_zero.py
"""
from __future__ import annotations

import asyncio
import os
import sys

#  Python met le dossier DU SCRIPT sur le chemin, pas le dossier courant :
#  sans cette ligne, `import roblox_news` échoue depuis outils/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import roblox_news as news        # noqa: E402
import roblox_veille as veille    # noqa: E402

LARGEUR = 78


def titre(t: str):
    print("\n" + "═" * LARGEUR)
    print(f"  {t}")
    print("═" * LARGEUR)


async def sonder_actualites():
    titre("ACTUALITÉS — ce que chaque source rend MAINTENANT")
    total_billets = total_pointeurs = 0
    joignables = 0
    for src in news.SOURCES:
        nom = src["domaine"]
        try:
            #  `forcer=True` : on veut savoir ce que la source CONTIENT, pas si
            #  son tour est venu. La cadence (étage d) est un autre sujet.
            rel = await news.relever(src, forcer=True)
        except Exception as ex:
            print(f"  ❌ {nom:<24} exception : {type(ex).__name__}: {ex}")
            continue
        code = rel.get("code")
        billets = rel.get("billets") or []
        pointeurs = int(rel.get("pointeurs") or 0)
        if code != 200:
            print(f"  ❌ {nom:<24} HTTP {code} — injoignable")
            continue
        joignables += 1
        total_billets += len(billets)
        total_pointeurs += pointeurs
        print(f"  ✅ {nom:<24} {len(billets):>3} publiable(s) · "
              f"{pointeurs:>2} pointeur(s) écarté(s) · cadence {src['minutes']} min")
        for b in billets[:2]:
            print(f"        · {(b.get('titre') or '')[:58]}")
    print(f"\n  TOTAL : {joignables}/{len(news.SOURCES)} source(s) joignable(s) · "
          f"{total_billets} billet(s) publiable(s) · {total_pointeurs} pointeur(s) écarté(s)")
    return joignables, total_billets, total_pointeurs


async def sonder_accessoires():
    titre("ACCESSOIRES — ce que le catalogue rend MAINTENANT")
    rel = await veille.relever_nouveautes(limite=120)
    arts = rel.get("articles") or []
    print(f"  nouveautés       : HTTP {rel['code']} · {len(arts)} article(s)")
    if rel["code"] == 200:
        #  ⚠️ LA RÈGLE DU PROPRIÉTAIRE (18/08) : « tu mets que les nouveaux qui
        #  sont créés à partir de maintenant ». Un article ne sort que si sa
        #  création date de moins de FENETRE_DIRECTE_HEURES.
        frais = [a for a in arts if veille.age_publiable(a, "nouveautes")]
        print(f"      créés depuis moins de {veille.FENETRE_DIRECTE_HEURES} h : {len(frais)}")
        for a in frais[:3]:
            print(f"        · {(a.get('nom') or '')[:56]}")
        if not frais:
            #  Montrer le plus récent PROUVE que la fenêtre est la cause, et
            #  non un relevé vide — deux situations très différentes.
            ages = sorted(
                (h, a.get("nom") or "")
                for a in arts
                for h in [veille._heures_depuis(a.get("cree_le"))] if h is not None)
            if ages:
                print(f"      le plus récent du catalogue a {ages[0][0]:.1f} h "
                      f"— « {ages[0][1][:42]} »")
            else:
                print("      ⚠️ aucune date exploitable — à regarder de près")

    await asyncio.sleep(veille.PAUSE_ENTRE_RELEVES)
    relc = await veille.relever_collectionnables(limite=120)
    print(f"  collectionnables : HTTP {relc['code']} · "
          f"{len(relc.get('articles') or [])} article(s)")
    print("\n  ⚠️ Les BASCULES ne peuvent PAS se voir ici : une bascule est une")
    print("     DIFFÉRENCE entre deux relevés, enregistrée en base. Base vide sur")
    print("     ce poste → premier relevé → aucune différence. Normal, et ça ne")
    print("     dit rien de Railway.")
    return rel["code"], relc["code"]


async def main():
    print("Sonde « pourquoi 0 publication » — appels réseau RÉELS.")
    joignables, billets, pointeurs = await sonder_actualites()
    await sonder_accessoires()

    titre("CE QUE ÇA TRANCHE — ET CE QUE ÇA NE TRANCHE PAS")
    if joignables == 0:
        print("  ❌ AUCUNE source joignable → la cause est EN AMONT (réseau,")
        print("     format, pare-feu). Inutile de chercher côté publication.")
    elif billets == 0 and pointeurs > 0:
        print(f"  ❌ {pointeurs} billet(s) lus, TOUS écartés comme « pointeurs ».")
        print("     → le filtre est trop strict, ou tout est renvoi de lien.")
    elif billets == 0:
        print("  ⚠️ Sources joignables mais VIDES. À confirmer sur une autre")
        print("     fenêtre : c'est peut-être réellement le calme (cause f).")
    else:
        print(f"  ✅ {billets} billet(s) publiable(s) existent, sources joignables.")
        print("     → si Railway publie 0, la cause est EN AVAL du relevé :")
        print("       « déjà publié » en base, flux éteint, ou salon absent.")
        print("       Ces trois-là ne se voient QUE dans les logs Railway ;")
        print("       c'est exactement ce que le bilan détaillé de la boucle")
        print("       imprime désormais, passage par passage.")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
