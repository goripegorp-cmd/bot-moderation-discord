"""Le bilan de la veille dit désormais POURQUOI zéro, et pas seulement zéro.

LE SYMPTÔME, LOGS RAILWAY DU PROPRIÉTAIRE (19/08/2026)
    [veille_roblox_task] passage terminé — … · 0 publication(s) réelle(s)
onze heures durant, toutes les 30 minutes. Et son constat :
    « il y a énormément d'actualités de tous types US français et tout. On a
      toutes les infos mais rien n'est posté »

CE QUE LA MESURE A DONNÉ (sonde_pourquoi_zero.py, appels réseau réels)
    7/7 sources joignables · 19 billets publiables · 3 pointeurs écartés
    catalogue : HTTP 200, 964 articles — le PLUS RÉCENT a 670 h (28 jours)

Deux enseignements, très différents l'un de l'autre :

  1. Côté ACCESSOIRES, zéro est la bonne réponse. Roblox n'a pas créé un seul
     accessoire de sa main depuis 28 jours. Avec la règle du propriétaire
     (« que les nouveaux qui sont créés à partir de maintenant »), il n'y a
     rien à publier — et il n'y aura rien avant la prochaine fournée.
  2. Côté ACTUALITÉS, dix-neuf billets publiables existaient AU MOMENT de la
     mesure. Si Railway en publie zéro, la cause est en AVAL du relevé : flux
     éteint, salon absent, ou billets déjà marqués publiés en base. Ces trois
     causes ne se distinguent QUE dans les logs — et le bilan n'en disait rien.

⚠️ LE DÉFAUT RÉEL EST LÀ. « 0 publication » recouvrait au moins six situations
dont une seule est une panne. Le propriétaire ne pouvait pas trancher, donc il
a supposé la panne — la supposition la plus coûteuse. Un compteur qui ne dit
que son total force à deviner ; un bilan qui décompose répond avant qu'on
demande.

CE QUE CE PATCH POSE
  a. `_diag_veille_serveurs()` — la ligne par serveur (allumé ? salon ?),
     extraite du cas « personne n'a rien allumé » où elle était enfermée. Elle
     sort maintenant AUSSI quand un passage se termine à zéro publication :
     c'est précisément là qu'on en a besoin.
  b. Des compteurs par étage — lus, candidats, hors fenêtre, déjà sortis,
     échecs d'envoi — pour les accessoires ET pour les actualités.
  c. Un bilan en trois lignes qui nomme l'étage où tout s'est arrêté.

CE QUE CE PATCH NE FAIT PAS, ET POURQUOI
J'avais aussi porté `FENETRE_DIRECTE_HEURES` de 6 à 24 h, pour qu'une fournée
d'accessoires tombée pendant une panne de nuit ne soit pas perdue. ABANDONNÉ :
le propriétaire avait déjà tranché contre, mot pour mot — « pas qui est passé
limited d'il y a un jour, 2 jours […] faut vraiment que ça passe là bientôt ».
Vingt-quatre heures, c'est « il y a un jour ». Le test
`test_une_nouveaute_plus_ancienne_est_absorbee_pas_publiee[24]` a refusé le
changement avant qu'il n'atteigne la production. Le compromis assumé est
désormais écrit au-dessus de la constante, dans roblox_veille.py.

Écrit dans un fichier puis exécuté (piège n°3 : les heredocs). `--apply`.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CIBLE = RACINE / "bot.py"


# ═══════════════════════════════════════════════════════════════════════════════
#  1. bot.py — le helper, les compteurs, le bilan
# ═══════════════════════════════════════════════════════════════════════════════

VIEUX_DIAG = '''        if not guildes_items and not guildes_news:
            #  ⚠️ LE DIRE. Cette boucle était muette : elle sortait sans un mot,
            #  et depuis les logs Railway rien ne distinguait « personne n'a
            #  allumé » de « la boucle est morte ». Une ligne toutes les 30 min
            #  ne coûte rien et répond à la question avant qu'on la pose.
            print(f"[veille_roblox_task] passage sans travail — aucun des "
                  f"{len(bot.guilds)} serveur(s) n'a allumé accessoires ni "
                  f"actualités (interrupteur + salon requis)")
            #  ⚠️ DIRE QUOI, PAR SERVEUR. « Aucun n'a allumé » a fait deviner
            #  le propriétaire le 18/08 : interrupteur éteint, ou salon
            #  manquant ? Une ligne par serveur tranche sans ouvrir /configure.
            for g in list(bot.guilds)[:10]:
                try:
                    _ca = await roblox_module.config(g.id)
                    _cn = await roblox_news_module.config(g.id)
                    _acc = ("OK" if _ca.get("roblox_veille_enabled")
                            and roblox_module.salon_du_flux(_ca, "nouveautes")
                            else ("éteint" if not _ca.get("roblox_veille_enabled")
                                  else "allumé mais AUCUN salon"))
                    _act = ("OK" if _cn.get("roblox_news_enabled")
                            and int(_cn.get("roblox_news_salon") or 0)
                            else ("éteintes" if not _cn.get("roblox_news_enabled")
                                  else "allumées mais AUCUN salon"))
                    print(f"[veille_roblox_task]   {g.name} ({g.id}) : "
                          f"accessoires={_acc} · actualités={_act}")
                except Exception as _dex:
                    print(f"[veille_roblox_task]   {getattr(g, 'id', '?')} : {_dex}")
            return
        _publies = 0
'''

NEUF_DIAG = '''        if not guildes_items and not guildes_news:
            #  ⚠️ LE DIRE. Cette boucle était muette : elle sortait sans un mot,
            #  et depuis les logs Railway rien ne distinguait « personne n'a
            #  allumé » de « la boucle est morte ». Une ligne toutes les 30 min
            #  ne coûte rien et répond à la question avant qu'on la pose.
            print(f"[veille_roblox_task] passage sans travail — aucun des "
                  f"{len(bot.guilds)} serveur(s) n'a allumé accessoires ni "
                  f"actualités (interrupteur + salon requis)")
            await _diag_veille_serveurs()
            return
        _publies = 0
        #  ⚠️ COMPTER À CHAQUE ÉTAGE. « 0 publication » recouvrait six
        #  situations dont une seule est une panne (mesuré le 19/08) : le
        #  propriétaire ne pouvait pas trancher, donc il supposait la panne.
        #  Ces compteurs nomment l'étage exact où le passage s'est arrêté.
        _sa = {"lus": 0, "candidats": 0, "hors_fenetre": 0, "deja": 0, "echecs": 0}
        _sn = {"lus": 0, "sautees": 0, "pannes": 0, "deja": 0, "echecs": 0}
'''

#  Le helper, posé juste avant la boucle.
#  ⚠️ L'ANCRE EST LE DÉCORATEUR, PAS LE `def`. S'ancrer sur
#  « async def veille_roblox_task(): » insère le helper ENTRE `@tasks.loop`
#  et sa fonction : le décorateur se recolle au helper et la boucle ne
#  tourne plus jamais. C'est le piège n°1 du dépôt, et je l'ai reposé le
#  19/08 — `test_la_boucle_reste_declaree_et_supervisee` l'a attrapé.
VIEUX_ANCRE_HELPER = "@tasks.loop(minutes=30)\nasync def veille_roblox_task():"

HELPER = '''async def _diag_veille_serveurs(limite: int = 10) -> None:
    """Dit, SERVEUR PAR SERVEUR, ce qui est allumé et ce qui manque.

    ⚠️ « Aucun serveur n'a allumé » a fait deviner le propriétaire le 18/08 :
    interrupteur éteint, ou salon manquant ? Une ligne par serveur tranche
    sans ouvrir /configure.

    ⚠️ Ce diagnostic était ENFERMÉ dans le cas « personne n'a rien allumé ».
    Or le cas qui fait mal est l'autre : un flux allumé, l'autre éteint, un
    passage qui se termine à zéro publication — et là, rien ne sortait. Il est
    donc appelé aussi depuis le bilan quand le passage n'a rien publié.
    """
    for g in list(bot.guilds)[:limite]:
        try:
            _ca = await roblox_module.config(g.id)
            _cn = await roblox_news_module.config(g.id)
            _acc = ("OK" if _ca.get("roblox_veille_enabled")
                    and roblox_module.salon_du_flux(_ca, "nouveautes")
                    else ("éteint" if not _ca.get("roblox_veille_enabled")
                          else "allumé mais AUCUN salon"))
            _act = ("OK" if _cn.get("roblox_news_enabled")
                    and int(_cn.get("roblox_news_salon") or 0)
                    else ("éteintes" if not _cn.get("roblox_news_enabled")
                          else "allumées mais AUCUN salon"))
            print(f"[veille_roblox_task]   {g.name} ({g.id}) : "
                  f"accessoires={_acc} · actualités={_act}")
        except Exception as _dex:
            print(f"[veille_roblox_task]   {getattr(g, 'id', '?')} : {_dex}")


'''

#  ── Compteur « lus » côté accessoires ────────────────────────────────────────
VIEUX_LUS = '''            rel = await roblox_module.relever_nouveautes(limite=120)
            if rel["code"] == 200:
                evts = await roblox_module.comparer_et_enregistrer(rel["articles"])
'''
NEUF_LUS = '''            rel = await roblox_module.relever_nouveautes(limite=120)
            _sa["lus"] = len(rel.get("articles") or [])
            if rel["code"] == 200:
                evts = await roblox_module.comparer_et_enregistrer(rel["articles"])
'''

#  ── Les trois portes de la publication d'un article ──────────────────────────
VIEUX_PORTES = '''                            if not roblox_module.age_publiable(a, flux):
                                continue
                            #  Déjà sorti ici, OU déjà sorti dans un flux plus
                            #  fort : on ne le republie pas ailleurs.
                            if not await roblox_module.publiable_dans(
                                    g.id, a["asset_id"], flux):
                                continue
                            if _budget <= 0:
                                _reporte += 1
                                continue'''
NEUF_PORTES = '''                            _sa["candidats"] += 1
                            if not roblox_module.age_publiable(a, flux):
                                _sa["hors_fenetre"] += 1
                                continue
                            #  Déjà sorti ici, OU déjà sorti dans un flux plus
                            #  fort : on ne le republie pas ailleurs.
                            if not await roblox_module.publiable_dans(
                                    g.id, a["asset_id"], flux):
                                _sa["deja"] += 1
                                continue
                            if _budget <= 0:
                                _reporte += 1
                                continue'''

VIEUX_ENVOI = '''                                await roblox_module.marquer_publie(g.id, a["asset_id"], flux)
                                _budget -= 1
                                _publies += 1
                            await asyncio.sleep(roblox_module.PAUSE_ENTRE_PUBLICATIONS)'''
NEUF_ENVOI = '''                                await roblox_module.marquer_publie(g.id, a["asset_id"], flux)
                                _budget -= 1
                                _publies += 1
                            else:
                                #  ⚠️ `publier` avale ses erreurs et rend None.
                                #  Sans ce compteur, un salon devenu interdit
                                #  ressemblerait à « rien à publier ».
                                _sa["echecs"] += 1
                            await asyncio.sleep(roblox_module.PAUSE_ENTRE_PUBLICATIONS)'''

#  ── Côté actualités ──────────────────────────────────────────────────────────
VIEUX_NEWS_SRC = '''                if rel.get("sautee"):
                    continue
                if rel["code"] != 200:
                    await asyncio.sleep(2)
                    continue'''
NEUF_NEWS_SRC = '''                if rel.get("sautee"):
                    _sn["sautees"] += 1
                    continue
                if rel["code"] != 200:
                    _sn["pannes"] += 1
                    await asyncio.sleep(2)
                    continue
                _sn["lus"] += len(rel.get("billets") or [])'''

VIEUX_NEWS_PUB = '''                        if await roblox_news_module.deja_publie(g.id, b["topic_id"]):
                            continue
                        if _budget <= 0:
                            _reporte += 1
                            continue
                        if await roblox_ui.publier_actu(g, salon, b):
                            await roblox_news_module.marquer_publie(g.id, b["topic_id"])
                            _budget -= 1
                            _publies += 1
                        await asyncio.sleep(roblox_module.PAUSE_ENTRE_PUBLICATIONS)'''
NEUF_NEWS_PUB = '''                        if await roblox_news_module.deja_publie(g.id, b["topic_id"]):
                            _sn["deja"] += 1
                            continue
                        if _budget <= 0:
                            _reporte += 1
                            continue
                        if await roblox_ui.publier_actu(g, salon, b):
                            await roblox_news_module.marquer_publie(g.id, b["topic_id"])
                            _budget -= 1
                            _publies += 1
                        else:
                            #  Un salon supprimé ou interdit se voit ICI, et
                            #  nulle part ailleurs : `publier_actu` rend None
                            #  sans lever.
                            _sn["echecs"] += 1
                        await asyncio.sleep(roblox_module.PAUSE_ENTRE_PUBLICATIONS)'''

#  ── Le bilan ────────────────────────────────────────────────────────────────
VIEUX_BILAN = '''        print(f"[veille_roblox_task] passage terminé — accessoires sur "
              f"{len(guildes_items)} serveur(s), actualités sur "
              f"{len(guildes_news)} · {_publies} publication(s) réelle(s) · "
              f"{_reporte} reportée(s)")
        if _reporte:'''
NEUF_BILAN = '''        print(f"[veille_roblox_task] passage terminé — accessoires sur "
              f"{len(guildes_items)} serveur(s), actualités sur "
              f"{len(guildes_news)} · {_publies} publication(s) réelle(s) · "
              f"{_reporte} reportée(s)")
        #  ⚠️ LE DÉTAIL, TOUJOURS. C'est lui qui répond à « pourquoi zéro ».
        if guildes_items:
            print(f"[veille_roblox_task]   accessoires : {_sa['lus']} lu(s) · "
                  f"{_sa['candidats']} candidat(s) · {_sa['hors_fenetre']} hors "
                  f"fenêtre ({roblox_module.FENETRE_DIRECTE_HEURES} h) · "
                  f"{_sa['deja']} déjà sorti(s) · {_sa['echecs']} échec(s) d'envoi")
        if guildes_news:
            print(f"[veille_roblox_task]   actualités : {_sn['lus']} billet(s) lu(s) · "
                  f"{_sn['sautees']} source(s) sautée(s) (cadence) · "
                  f"{_sn['pannes']} source(s) en panne · {_sn['deja']} déjà "
                  f"publié(s) · {_sn['echecs']} échec(s) d'envoi")
        #  ⚠️ ZÉRO PUBLICATION → ON DIT L'ÉTAT DE CHAQUE SERVEUR. Le cas qui a
        #  coûté onze heures au propriétaire : un flux allumé, l'autre éteint,
        #  et un bilan qui ne montrait que le total.
        if _publies == 0:
            await _diag_veille_serveurs()
        if _reporte:'''

REMPLACEMENTS_BOT = [
    ("helper", VIEUX_ANCRE_HELPER, HELPER + VIEUX_ANCRE_HELPER),
    ("diag", VIEUX_DIAG, NEUF_DIAG),
    ("lus", VIEUX_LUS, NEUF_LUS),
    ("portes", VIEUX_PORTES, NEUF_PORTES),
    ("envoi", VIEUX_ENVOI, NEUF_ENVOI),
    ("news_src", VIEUX_NEWS_SRC, NEUF_NEWS_SRC),
    ("news_pub", VIEUX_NEWS_PUB, NEUF_NEWS_PUB),
    ("bilan", VIEUX_BILAN, NEUF_BILAN),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  2. roblox_veille.py — la fenêtre
# ═══════════════════════════════════════════════════════════════════════════════

#  ⚠️ LE VOLET « FENÊTRE » A ÉTÉ ABANDONNÉ. J'avais porté
#  FENETRE_DIRECTE_HEURES de 6 à 24 h pour survivre à une panne de nuit. Le
#  propriétaire avait déjà tranché contre, mot pour mot : « pas qui est passé
#  limited d'il y a un jour, 2 jours […] faut vraiment que ça passe là
#  bientôt ». `test_une_nouveaute_plus_ancienne_est_absorbee_pas_publiee[24]`
#  a refusé le changement. Le compromis est désormais écrit dans
#  roblox_veille.py, au-dessus de la constante, pour qu'on ne le redécouvre
#  pas — et pour qu'on ne le « corrige » pas une troisième fois.


def _appliquer(chemin: Path, remplacements, ecrire: bool) -> bool:
    src = chemin.read_text(encoding="utf-8")
    avant = {getattr(n, "name", None) for n in ast.parse(src).body}
    neuf = src
    for nom, vieux, nouveau in remplacements:
        if neuf.count(vieux) != 1:
            print(f"❌ {chemin.name} : ancre « {nom} » trouvée "
                  f"{neuf.count(vieux)} fois — abandon.")
            return False
        neuf = neuf.replace(vieux, nouveau, 1)
    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ {chemin.name} : ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return False
    apres = {getattr(n, "name", None) for n in arbre.body}
    if avant - apres:
        print(f"❌ {chemin.name} : symboles perdus : {avant - apres}")
        return False
    print(f"  {chemin.name} {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if ecrire:
        chemin.write_text(neuf, encoding="utf-8", newline="")
    return True


def main() -> int:
    ecrire = "--apply" in sys.argv
    if "_diag_veille_serveurs" in CIBLE.read_text(encoding="utf-8"):
        print("❌ patch déjà appliqué (_diag_veille_serveurs existe).")
        return 1
    ok = _appliquer(CIBLE, REMPLACEMENTS_BOT, ecrire)
    if not ok:
        return 1
    print("  ÉCRIT." if ecrire else "  PREVIEW — rien écrit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
