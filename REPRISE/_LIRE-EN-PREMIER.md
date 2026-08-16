# 🚀 REPRISE — bot-moderation-discord

> Écrit le 15/08/2026 en fin de session. **Lis ce fichier en entier avant
> d'ouvrir un seul autre fichier.** Il te fait gagner deux heures et t'évite de
> refaire cinq erreurs qui ont chacune coûté un correctif.

---

## 1. EN TROIS PHRASES

Bot Discord FR de modération, `bot.py` ≈ 48 700 lignes + 90 modules, déployé sur
**Railway** depuis `main`. Refonte « on jette tout sauf la sécurité », puis
réintroduction demandée d'un système de **veille Roblox**. Tout est poussé, CI
verte sur les trois workflows.

**Ordre de lecture : ce fichier → `HANDOFF.md` §14 et §15 → `ROBLOX.md` → `UI.md`.**

---

## 2. LA LEÇON DE LA SESSION — elle vaut pour tout le reste

**Sept fois en une session, du code parfaitement présent ne s'exécutait jamais.**

| Ce qui était cassé | Comment ça se voyait |
|---|---|
| `on_member_join` sans `@bot.event` | l'anti-raid comptait 0 arrivée depuis des MOIS |
| Réaction 🌐 dont le handler ne contenait qu'un `pass` | elle se posait sur chaque annonce, sans rien faire |
| Boutons dont la classe n'était plus enregistrée au boot | « L'interaction a échoué », en public |
| `weekly_security_report` sans `.start()` | jamais parti une seule fois |
| Détection de compte compromis, clé sans interface | dormante sur 100 % des serveurs |
| `roblox_veille` câblé avec `session=None` | sortait avant tout appel réseau |
| `webhook_send(username=...)` — paramètre inexistant | le webhook n'aurait jamais servi |

**Aucun n'était attrapé par `ast.parse`, par `import bot`, ni par les 213 tests.**

### La règle qui en découle, à appliquer sans exception

> **Ne jamais écrire « c'est fait » sans avoir suivi la chaîne jusqu'à un effet
> RÉEL** — un envoi Discord, une écriture en base, une réponse HTTP 200.
> Une fonction non appelée, une `@tasks.loop` sans `.start()`, une vue non
> réenregistrée = **NON opérationnel**, quelle que soit la qualité du code.

### Les contrôles à lancer, dans cet ordre

```bash
python -m pytest tests/ -q
python outils/verif_noms.py bot.py
python outils/verif_evenements.py bot.py
DISCORD_TOKEN=x python -c "import bot"
```

Le dernier est le seul qui exécute le code de module. **C'est lui qui compte.**
`outils/verif_evenements.py` a été écrit pour le cas `on_member_join` ; il
**reste à écrire l'équivalent pour les boucles sans `.start()` et pour les
`DynamicItem` non réenregistrés** — les deux mêmes trous, deux fois payés.

---

## 3. INSTALLER DE QUOI VÉRIFIER EN LOCAL

Les trois CI rouges de la session venaient toutes de l'impossibilité de tester.

```bash
pip install "discord.py>=2.7,<3" aiosqlite aiohttp python-dotenv matplotlib pytest pytest-asyncio
```

---

## 4. CE QUI RESTE À FAIRE — le détail est en §15 du HANDOFF

| # | Chantier | État |
|---|---|---|
| 1 | Effacer les marques de publication Roblox | ✅ **LIVRÉ** — bouton ♻️ |
| 2 | Onglet « Réseaux sociaux » dans `/configure` | ✅ **LIVRÉ** le 16/08 |
| 3 | Purger cadeaux, boss, salons d'événements | ✅ **LIVRÉ** le 16/08 — périmètre nommé |
| 4 | Remettre `/rellseas`, configurable | ✅ **LIVRÉ** le 16/08 |

### ⚠️ CE QUI A ÉTÉ TROUVÉ EN CHEMIN LE 16/08 — à ne pas réapprendre

**1. L'envoi Roblox annonçait des publications fantômes.** `publier()` appelait
`webhook_send()` puis rendait `True` sans regarder le retour. Or `webhook_send`
n'a aucun chemin qui lève : elle avale tout et rend `None`. Le bouton annonçait
« 3 fiches publiées » sur un salon qui n'avait rien reçu — **et `marquer_publie`
écrivait la marque, donc l'article était perdu pour toujours.** C'était bien le
maillon que ce fichier déclarait non observé. Corrigé, 16 tests l'enferment.

**2. `outils/purge_modules.py` allait détruire ce qu'il fallait garder.** Sa
liste `GARDER` datait d'avant la réintroduction de Roblox, du social et de
l'activité : l'aperçu proposait de supprimer `roblox_veille`, `roblox_panneau`,
`roblox_news`, `social_media`, `admin_panels_v2` et les neuf `activite_*`.
**Liste corrigée**, mais relire l'aperçu avant tout `--apply` reste la règle.

**3. Le panneau social existait déjà.** Pas dans `bot.py` — dans
`admin_panels_v2.py`, complet et branché sur le vrai manager. Il était devenu
inatteignable au retrait de `/admin`. Rebranché, pas réécrit.

**4. Le piège n°2 est plus large qu'écrit.** `_iter_supervised_loops` a un
BALAYAGE AUTO qui ramasse tout `tasks.Loop` déjà démarré, même absent de
`_SUPERVISED_LOOP_NAMES`. **Retirer le nom de la liste ne débranche rien** : il
faut supprimer la boucle. `outils/couper_symboles.py` le fait proprement.

### Ce qui reste, et qui demande un arbitrage

La purge a retiré le périmètre **nommé** par le propriétaire (cadeaux, boss,
salons d'événements) : 7 modules et ~2 200 lignes de `bot.py`, 17 boucles.
Restent **16 boucles d'animation communautaire** et 14 modules du même
registre — énigme du jour, héraut hebdomadaire, vitrine, rituel du soir,
anniversaire, camouflage de salon, projecteur vocal, PNJ, missions, heure
dorée, UGC, jalons. Ce n'est plus « cadeaux, boss, événements » : c'est la zone
grise. `PYTHONIOENCODING=utf-8 python outils/inventaire_evenements.py` en donne
la carte à jour.

### Sur le n°2 — ne pas se tromper de travail

Le système social **FONCTIONNE**. Le log de démarrage le prouve :

```
[social] YouTube : RSS auto ✅ · Twitter/X · TikTok · Instagram : via RSSHub ✅
```

`/social add|list|remove|toggle|poll_now` existent (vérifié dans les 55 commandes
enregistrées). **Il manque UNIQUEMENT un panneau** — il n'y a aucune classe de
panneau social dans `bot.py`, donc c'est à écrire, pas à rebrancher.

Modèle à suivre : `roblox_panneau.py`, le plus récent. Puis une entrée dans
`_CONFIG_SECTIONS` et sa résolution dans `_module_select`.

### Sur le n°4 — la moitié existe déjà

`realsy_tracking`, `update_realsy_activity`, `rellseas_quizzes` et les vues de
questionnaire sont **INTACTS**. Seules manquent la commande et son réglage de
permission.

⚠️ La vérification d'activité doit **réutiliser `activite.presence()`** sur une
fenêtre d'une semaine. Ne PAS écrire un second compteur : c'est ce qui avait
produit le doublon retiré le 12/08, dont le message privé annonçait un retrait de
rôle que le bot ne faisait jamais.

---

## 5. LES PIÈGES DE CE DÉPÔT — chacun a déjà coûté

1. **Ne jamais borner une coupe sur « la prochaine ligne `async def` ».** Deux
   sur-coupes le 12/08 : 500 lignes emportées une fois, le décorateur
   `@tasks.loop` de la fonction suivante l'autre — ce qui empêchait le bot de
   démarrer. Utiliser des ancres textuelles exactes, et **diffing des symboles de
   premier niveau** après chaque coupe.
2. **Le superviseur relance les boucles par leur NOM en chaîne.** Retirer un
   `.start()` ne suffit pas : il faut aussi retirer l'entrée de
   `_SUPERVISED_LOOP_NAMES`.
3. **Les heredocs bash mangent les `\n`.** Six fois dans la session. Écrire le
   script de patch avec l'outil `Write`, puis l'exécuter — jamais de `<<'PY'`
   contenant des `\n` dans des chaînes.
4. **`git commit -m` avec des accents graves** déclenche une substitution shell.
   Toujours `-F fichier`.
5. **Deux comptes `gh`** : `gh auth switch --user goripegorp-cmd` avant tout push.
6. **Un faux objet de test doit porter TOUT ce que le vrai porte.** `_Guild` sans
   `get_channel` a rendu la CI rouge un jour sur sept — le rappel hebdomadaire
   n'appelle cette méthode que le jour choisi.

---

## 6. RÈGLES PERMANENTES DU PROPRIÉTAIRE

- **Un seul projet par conversation.** S'il parle d'OPSIDRAX (Roblox) ou de MTO,
  c'est qu'il s'est trompé de fenêtre : **le lui dire et couper**, ne rien
  modifier avant confirmation.
- **Réponses courtes.** Pas de pavés. Questions en tirets, une par ligne.
- **Aucun menu ni bouton qui ment** — voir `UI.md`. Components V2 partout.
- **Pousser sur `main` par défaut.** Il attend le déploiement, pas une branche.
- **CI verte obligatoire** avant de dire qu'un lot est terminé.

---

## 7. ÉTAT DU SYSTÈME ROBLOX — ce qui tourne vraiment

Éprouvé en direct, pas déduit :

- relevé du catalogue → **HTTP 200**, 110 articles du compte officiel
- noms **français officiels** (26/28) via l'en-tête de langue — Roblox traduit,
  pas nous
- liens **reconstruits** et testés : 6/6 valides, Bundles compris (`/bundles/`
  et non `/catalog/`, sinon 404 sur ~42 % des articles)
- images en bannière, demandées **en lot**
- 5 sources d'actualité, toutes **HTTP 200** avec du contenu du jour
- boucle toutes les 30 min, **déclarée + démarrée + supervisée** (vérifié à
  l'exécution)
- plafond de **12 publications par passage**, 2 s entre chaque envoi

**Jamais vérifié** : qu'un message atterrisse réellement dans un salon Discord.
Le chemin d'appel est éprouvé contre la vraie signature ; l'envoi lui-même ne
l'est pas, faute de serveur de test. **C'est le seul maillon à confirmer.**

### Ce que le système REFUSE de faire, et pourquoi

Il ne prédit pas. Mesuré sur **964 articles** : `offSaleDeadline` renseigné
**0 fois**, `itemStatus` vide 962 fois. Aucun signal déclaratif n'annonce un
passage en collectionnable. Le système publie un **indice** qui affiche ses
facteurs, et **se tait sous 60/100** — un chiffre faible est une absence de
signal, pas un verdict.

**Rolimons est interdit** : ses conditions proscrivent verbatim l'accès
automatisé. Aucune URL rolimons dans le code. Et **aucun modèle entraîné** : les
conditions de Roblox l'interdisent sur leur contenu virtuel.

---

## 8. LES RAPPORTS À NE PAS PERDRE

`rapports/` contient les relevés bruts des audits, avec pour chaque constat son
`fichier:ligne`, sa preuve et l'effort estimé :

| Fichier | Contenu |
|---|---|
| `audit-operationnel-12aout.json` | 61 constats vérifiés (passe 1) |
| `audit-operationnel-12aout-passe2.json` | 63 constats (passe 2) |
| `roblox-veille-items-plan.json` | 86 constats, API catalogue |
| `roblox-veille-actualites-plan.json` | 71 sources ouvertes et lues |
| `roblox-modele-avance-plan.json` | le modèle par la vitesse, non implémenté |

Le dernier porte l'idée qui reste à bâtir : **personne ne publie la dérivée**.
Tout le monde donne une photographie ; la vitesse des favoris et l'écoulement du
stock ne demandent pas d'archives — juste de commencer à mesurer.
