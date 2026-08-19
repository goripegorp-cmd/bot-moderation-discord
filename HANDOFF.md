# 🔁 PASSATION — Refonte du bot (à lire EN ENTIER avant toute action)

> **Tu reprends un chantier en cours.** Ce fichier contient tout : l'objectif, l'état exact,
> la méthode, les pièges vérifiés et les règles de l'owner. **Ne recommence pas l'analyse
> depuis zéro — elle a déjà coûté 16 agents et 451 lectures de code.**

---

## 1. LE PROJET EN UNE PHRASE

Bot Discord FR de modération + MMORPG (`bot.py` ≈ **104 000 lignes** + ~145 modules), déployé
sur **Railway**. L'owner a décidé (2026-08) : **le serveur est mort, on jette tout sauf la
sécurité, et on reconstruit proprement.**

### Ce qu'on GARDE (décision owner, validée)
1. **Sécurité** : insultes, spam, liens phishing/scam, anti-raid, images (OCR anti-scam + NSFW),
   comptes piratés, fuite de token/webhook, usurpation, honeypot, récidive.
2. **Sanctions + casier** : `/mod warn / unwarn / mute / infractions / clear / note / history`.
3. **Salon de logs de modération**.
4. **`/configure` — partie sécurité uniquement**.
5. **Tickets**.
6. **Infra** : base de données, permissions/immunités, diag, santé, backup.

### Ce qu'on SUPPRIME (tout le reste, sans exception)
MMORPG (quêtes/boss/donjons/pets/économie), **niveaux/XP**, **activité**, **VIP**, **clan Realsy**,
**réseaux sociaux + patch notes**, events, engagement, Roblox, animation (anniversaires, question
du jour, entraide, zones sociales, hub communautaire…).

---

## 2. ÉTAT EXACT AU MOMENT DE LA PASSATION

| Élément | Valeur |
|---|---|
| Branche | `main` |
| `bot.py` | **52 555 lignes** (départ : 108 519 — **-52 %**) |
| Modules | **80** à la racine |
| Commandes slash | **40** (départ : 148) |
| Point de restauration | tag git **`avant-purge-mmorpg`** (poussé sur GitHub) |
| CI | **verte** sur tous les commits livrés |

**Déjà fait** (10 commits, chacun CI verte) :
- MMORPG **débranché** (câblage `on_ready` + 30 boucles retirées du superviseur).
- Code RPG mort supprimé (−2 696 l.), dont `_do_prestige` qui **remettait les niveaux à 0**.
- 16 modules RPG supprimés (+ leurs imports + `tests/test_imports.py` + tests RPG).
- **`on_ready` est désormais 100 % sécurité / tickets / logs / infra.**
- **`/configure` réécrit** : 13 sections → 8, périmètre sécurité seul. `SecurityPanelV2`
  (étage intermédiaire) supprimé, ses 5 enfants remontés à la racine. **L'ancre est levée.**
- **Sélecteurs retapés** : `ChannelSelect` natif partout, fin des paginations manuelles
  (23/page) et des deux fuites qui ressuscitaient des panneaux V1 en Embed.
- **Purge des panneaux morts** : 226 classes / 12 552 lignes, prouvées inatteignables par
  fermeture transitive inverse (`outils/purge_morts.py`).

- **Boutons rebranchés** : les 3 contrôles qui n'agissaient sur rien, + la détection de
  comptes piratés qui était **dormante sur tous les serveurs**.
- **Anti-raid unifié** : l'ancien système neutralisait le nouveau (fail-open) — un seul reste.
- **Commandes** : 148 → 40, par identifiants QUALIFIÉS (le piège §5.2 est évité par
  construction, l'outil refuse un nom nu).
- **Runtimes purgés** : fermeture inverse étendue aux FONCTIONS (`outils/purge_runtimes.py`).
- **Plus aucun nom inconnu dans `bot.py`** (`outils/verif_noms.py` passe au vert).

**LA REFONTE EST TERMINÉE.** Les 7 lots sont livrés, chacun CI verte. Ce qui reste
n'est plus du démontage mais de la construction : le périmètre gardé est propre,
honnête et opérationnel.

**Deux points à connaître avant de bâtir dessus :**
1. `gdpr.py` garde volontairement des entrées pour des tables condamnées. Sur les
   serveurs déjà déployés ces tables EXISTENT ENCORE avec des données de membres :
   les retirer du registre ferait manquer ces données au droit à l'effacement.
   Elles sont inoffensives (le registre est fail-safe) et légalement utiles.
2. Les tables mortes ne sont pas DROP en production. Détruire des données live est
   une décision du propriétaire, pas la conséquence d'un nettoyage de code. Elles
   ont simplement cessé d'être recréées.

**⚠️ TROIS CI ROUGES ONT ÉTÉ PAYÉES POUR CES LEÇONS — ne pas les réapprendre :**
- `ast.parse` valide la SYNTAXE, pas les NOMS. Lancer `outils/verif_noms.py` avant chaque push.
- Un module condamné mais **pas encore supprimé** est toujours importé par `bot.py` : son
  propre import cassé tue le boot. Ne pas ne bloquer que sur les modules gardés.
- Un `try: import x` avec repli est conçu pour l'absence du module : il ne bloque PAS.
  Distinguer import DUR (niveau module) et import PARESSEUX.
- Les tests aussi importent les modules supprimés (§5.8) — vérifier `tests/` en entier,
  pas seulement `tests/test_imports.py`.

---

## 3. GIT / GITHUB — PROCÉDURE EXACTE (⚠️ 2 comptes configurés)

Le dépôt est **`goripegorp-cmd/bot-moderation-discord`**. Il y a **deux comptes `gh`** ;
`projectwebgorp` n'a **pas** les droits de push. **Avant chaque push :**

```bash
gh auth switch --user goripegorp-cmd
```

Cycle complet :

```bash
cd /c/Users/GoRipe/Desktop/bot-moderation-discord
gh auth switch --user goripegorp-cmd
git add -A
git commit -m "message clair en français"
git pull --rebase origin main
git push origin main
```

**Ne jamais** utiliser `[skip ci]` ni `--no-verify`.

### CI — la seule preuve qui compte
3 workflows GitHub Actions tournent à chaque push :
- **Python Compile Check** → fait un **vrai `import bot`** (détecte ImportError / NameError au niveau module).
- **Pytest Smoke Tests** → ~337 tests.
- **SQL Injection Audit**.

Vérifier après push :
```bash
rid=$(gh run list --limit 1 --workflow "Python Compile Check" --json databaseId -q '.[0].databaseId')
gh run watch "$rid" --exit-status --compact
```
**Règle absolue : un lot n'est terminé que si la CI est verte.**

### Déploiement
Railway déploie automatiquement sur push `main`, **via le `Dockerfile`** (pas nixpacks).
- Python **3.13** (obligatoire : `audioop-lts` l'exige).
- Le Dockerfile installe `tesseract-ocr`, `tesseract-ocr-eng` (OCR anti-scam), `libzbar0` (QR),
  et les libs d'`onnxruntime`/`opencv` pour NSFW. **Ne pas y toucher sans raison.**

---

## 4. MÉTHODE OBLIGATOIRE (elle a évité 5 catastrophes)

1. **Jamais d'édition à l'aveugle dans `bot.py`.** Écrire un script Python d'analyse, le lancer en
   **preview**, relire la sortie, puis `--apply`.
2. **Toujours `ast.parse()` avant d'écrire.** Ce garde-fou a bloqué 3 écritures qui cassaient le bot
   (parent laissé vide, décorateur multi-lignes orphelin).
3. **Vérification anti-décalage** : avant de couper une plage de lignes, vérifier qu'un **jeton
   attendu** s'y trouve (sinon les numéros ont bougé → abandonner).
4. **Liste blanche, pas liste noire**, pour tout ce qui touche à la sécurité.
5. **Relire à la main** toute liste générée automatiquement avant de supprimer.
6. **Après chaque lot** : vérifier que les fonctions critiques existent toujours
   (`grep -c "def <nom>" bot.py`) — voir §6.
7. Python est dispo en ligne de commande via **`python3`** dans Git Bash (avec
   `PYTHONIOENCODING=utf-8`, sinon plantage d'encodage sur les accents).

---

## 5. PIÈGES VÉRIFIÉS (chacun a failli casser la prod)

1. **Les points d'entrée n'ont PAS d'appelant.** Une analyse « personne ne l'appelle donc c'est mort »
   a voulu supprimer **`on_member_join` (411 lignes = anti-raid + accueil)**. Toujours maintenir une
   liste `NEVER_DELETE` : `on_member_join`, `on_ready`, `on_message`, `help_cmd`, `notify_cmd`, `hub_cmd`.
2. **`KEEP_CMD_NAMES` avec des noms génériques** (`set`, `add`, `remove`, `list`, `reply`, `close`,
   `claim`) matche les commandes de **tous** les groupes → la fermeture garde 219 graines au lieu de
   ~40. **À corriger : n'utiliser que des noms spécifiques, ou filtrer par groupe parent.**
3. **Module CÂBLÉ ≠ module passé en ARGUMENT.** `owner_digest.setup(webhook_tracker_module=…)`
   faisait croire que webhook_tracker était câblé là. Tester `^\s*(await )?<module>\.`.
4. **Helpers vitaux enfouis dans des blocs RPG** : `_safe_defer`, `_schedule_msg_delete`,
   `_register_for_cleanup`, et surtout **`task_supervisor`** — ne pas les emporter.
5. **Le superviseur redémarre les boucles.** Retirer un `.start()` ne suffit pas : il faut aussi
   retirer l'entrée de `_SUPERVISED_MODULE_LOOPS` / `_SUPERVISED_LOOP_NAMES`, sinon la boucle repart.
6. **`check_expired_restrictions` est VITALE** : sans elle, une sanction temporaire ne se lève **jamais**.
7. **Pièges de vocabulaire** : `raid_detector`/`raid_shield` = **anti-raid sécurité (garder)** ≠ boss raid.
   `alliance` RPG ≠ clan Realsy. `trade` RPG ≠ zones sociales.
8. **`tests/test_imports.py`** contient une liste de modules en dur → **mettre à jour dans le même
   commit** que toute suppression de fichier, sinon CI rouge.
9. **Le hub V2 résout ses handlers par NOM de méthode** → supprimer une fonction ne casse rien à
   l'import mais **casse le bouton en prod, silencieusement**. Le hub doit être **réécrit**, pas amputé.
10. **`gdpr.py`** est le registre autoritaire (~290 tables) : après suppression de tables, l'élaguer
    sinon le droit à l'effacement plante.
11. ⚠️ **`conversation_starters.py` importe `ambient53` EN DUR** (hors `try`) : supprimer `ambient53`
    sans traiter `conversation_starters` = **ImportError au boot = bot mort**.
12. **NE PAS réécrire le pipeline de sécurité de zéro.** `on_message` contient des années de règles
    anti-faux-positifs **testées** (limites de mots, `_strip_media_urls` pour ne pas bloquer les GIF,
    immunités, exemptions tickets, escalade du spam, OCR mode sombre). **Le réutiliser verbatim.**

---

## 6. VÉRIFICATION APRÈS CHAQUE LOT (à copier-coller)

```bash
cd /c/Users/GoRipe/Desktop/bot-moderation-discord
for f in on_member_join on_message on_ready is_immune sanction _record_infraction \
         create_ticket check_badwords _ocr_scam_check task_supervisor \
         check_expired_restrictions; do
  c=$(grep -c "def $f" bot.py); echo "$([ "$c" -gt 0 ] && echo OK || echo MANQUANT) $f"
done
```

---

## 7. RÈGLES DE L'OWNER — NON NÉGOCIABLES

- **Super-owner = `781205382923288593` UNIQUEMENT.**
- **Owner / admins / immunisés ne sont JAMAIS sanctionnés automatiquement.**
- **Anonymat du modérateur** : le membre sanctionné ne voit **jamais** qui l'a sanctionné (seuls les
  staffs le voient dans le salon de logs). Une réponse de slash **publique** trahit le modérateur
  (Discord affiche « X a utilisé /mod warn ») → **réponse éphémère + `channel.send` séparé**.
- **MP de sanction = récap COMPLET** de toutes les infractions (« il dira toujours j'ai rien fait »).
- **Le bot ne ferme ni ne ping JAMAIS un ticket** — gestion 100 % manuelle.
- **Médias autorisés dans les tickets** (preuves) : images, vidéos, GIF, liens. Les tickets restent
  surveillés **uniquement** par anti-phishing + anti-scam.
- **Aucun ping automatique** de membres (le ping n'a lieu que si un staff lance la commande).
- **Le bot ne retire jamais un rôle** de lui-même — il avertit, le staff retire à la main.
- **Rôles pingables** : toujours `mentionable=False`.
- **Règle n°1 anti-faux-positif** : ne jamais sanctionner un innocent. Toute nouvelle règle de
  détection doit être **testée** (script Node/Python avec cas positifs ET cas légitimes) avant déploiement.
- **Sécurité = fail-closed** (dans le doute, on protège) / **disponibilité = fail-open** (une erreur
  ne doit jamais bloquer le bot).
- **Anti-429** : toujours `defer` d'abord sur les interactions.

---

## 8. 🎨 UI — EXIGENCE OWNER : DU MODERNE, PAS DU VIEUX DISCORD

> 📌 **La charte complète est dans [`UI.md`](UI.md)** — 7 sections, à passer avant toute livraison
> d'interface. Condition permanente posée le 11/08/2026 : *« tous les menus ultra propres, les
> dernières technologies Discord, des boutons vraiment très bien, du travail bien rangé, ultra
> optimisé et protégé. »* Ce qui suit en est le résumé.

> **« Les dernières technologies de Discord, pas des vieux emojis pour cocher les cases.
> Des vrais labels, des vrais menus, du professionnel. »**

### Interdit
- ❌ Menus par **réactions emoji** (cliquer 🇦/🇧/✅ sous un message) — obsolète.
- ❌ Cases à cocher simulées avec des emojis dans du texte.
- ❌ Commandes préfixées (`!config`) — tout passe par des **slash commands**.
- ❌ Murs de texte dans un embed en guise de formulaire.

### Obligatoire
- ✅ **Slash commands** (`app_commands`) avec descriptions claires, en français.
- ✅ **Composants v2 / `LayoutView`** (déjà utilisés dans le projet via `ui_v2.py` :
  `v2_title`, `v2_subtitle`, `v2_body`, `v2_divider`, `v2_container`).
  ⚠️ Avec `LayoutView`, le paramètre **`content=` est INTERDIT** (erreur 400) — tout passe par les
  composants. Maximum **40 composants** par message.
- ✅ **Boutons** avec `label` explicite + `style` cohérent (`success` = valider, `danger` = supprimer,
  `primary` = action principale, `secondary` = retour) + `emoji=` en décoration, jamais comme
  mécanisme de clic.
- ✅ **Select menus** pour les choix : `discord.ui.Select` avec `SelectOption(label=…, description=…)`,
  et surtout les **selects natifs typés** : `ChannelSelect`, `RoleSelect`, `UserSelect`,
  `MentionableSelect` — plus jamais de « colle l'ID du salon ».
- ✅ **Modals** (`discord.ui.Modal` + `TextInput`) pour la saisie de texte, avec `placeholder` et
  `max_length`.
- ✅ **Toggles** = un bouton dont le label et le style reflètent l'état (« 🟢 Activé » / « ⚪ Désactivé »),
  pas une réaction.
- ✅ **Vues persistantes** (`timeout=None` + `custom_id` stable, ré-enregistrées au boot) pour que les
  boutons survivent aux redémarrages. Pour les identifiants dynamiques : `DynamicItem`.
- ✅ **Réponses éphémères** par défaut pour tout ce qui est configuration/modération.
- ✅ Navigation : chaque panneau a un bouton **◀️ Retour** et un fil d'Ariane clair.

### Le `/configure` à écrire (cible)
Un panneau d'accueil V2 avec un **select menu** de sections, et pour chaque section un sous-panneau
à boutons/selects :
- 🛡️ **Protections** — toggles par protection (insultes, spam, liens, scam, images, raid…) + seuils via modal.
- ⚖️ **Sanctions** — durées, escalade, salon de logs (`ChannelSelect`).
- 👮 **Staff & immunités** — `RoleSelect` / `UserSelect`.
- 🎫 **Tickets** — catégorie, rôle staff, panneau d'ouverture.
- 📋 **Logs** — salon (`ChannelSelect`) + activation par catégorie d'événement.

---

## 9. OUTILS D'ANALYSE (à recréer si besoin — ils sont décrits ici)

Ils vivaient dans le scratchpad de session (temporaire). Chacun : **preview par défaut, `--apply`
pour écrire, `ast.parse` avant écriture**.

| Script | Rôle |
|---|---|
| `purge_refs.py` | Compte les usages/imports de chaque module condamné dans `bot.py` et ailleurs. |
| `unwire2.py` | Dans `on_ready`, retire le câblage des modules **hors liste blanche**. Refuse les blocs mixtes. |
| `clean_supervisor.py` | Retire les boucles supprimées de `_SUPERVISED_MODULE_LOOPS`. |
| `deadcode.py` | **Joignabilité AST** : supprime une def/class seulement si rien du socle ne l'appelle. **Exige `NEVER_DELETE`.** |
| `keepclosure.py` | **Fermeture transitive inverse** : garde les points d'entrée sécurité **+ tout ce dont ils dépendent**, supprime le reste. ← *l'outil principal pour finir* |
| `drop_modules.py` | Supprime un lot de modules : import + fichier + entrée dans `tests/test_imports.py` + tests associés. |

### Déjà recréés et versionnés dans `outils/`

| Script | Rôle |
|---|---|
| `verif_socle.sh` | Le contrôle §6 en un script : fonctions critiques + `NEVER_DELETE` + `ast.parse` + compteurs. Sort en code non nul si régression. |
| `sonde_panneaux.py` | Pour une classe de panneau : signatures `__init__`/`render_to`, boutons « Retour », et **tous ses appelants** (par AST). |
| `purge_morts.py` | **Fermeture transitive inverse à point fixe.** Trouve les classes que plus rien de vivant n'atteint. Épargne automatiquement tout nom cité dans une chaîne (le hub V2 résout par nom) et tout nom utilisé hors `bot.py`. Bloque sur une référence en **code**, signale seulement celles en commentaire. |
| `verif_noms.py` | **Détecteur de NameError avant le boot.** Fait en 5 s ce que la CI met 3 min à trouver : liste les noms utilisés mais jamais définis. À lancer avant CHAQUE push. |
| `verif_portees.py` | **Ce que `verif_noms` ne peut PAS voir.** `verif_noms` aplatit toutes les portées dans un seul ensemble : un nom assigné n'importe où passe pour connu partout. Celui-ci fait une portée à la fois, comme Python. Il a trouvé `name 'ok' is not defined`, qui tournait une dizaine de fois par jour dans les logs Railway pendant que `verif_noms` restait vert. **Les deux, pas l'un ou l'autre.** |
| `verif_boutons_persistants.py` | Tout `custom_id` posé sur une `View(timeout=None)` doit être capté par un `bot.add_view` ou un `add_dynamic_items`. Sinon le bouton s'affiche, se clique, et Discord répond « n'a pas répondu à temps » — en public. |
| `verif_boucles.py` | `.start()` sur une fonction qui a perdu son `@tasks.loop` (piège n°1), et boucles condamnées par la deny-list. |
| `sonde_pourquoi_zero.py` | Appelle les VRAIES sources Roblox (réseau réel) et compte à chaque étage : sources joignables, billets publiables, pointeurs écartés, articles dans la fenêtre. Répond à « pourquoi 0 publication » sans deviner. |
| `purge_runtimes.py` | Fermeture inverse étendue aux **fonctions** de niveau module. Protège d'office les `on_*`, les fonctions décorées, les noms cités en chaîne, les noms utilisés hors `bot.py`. |
| `purge_commandes.py` | Purge des slash commands par identifiant **qualifié** (`/mod warn`, jamais `warn`). Refuse un nom nu. Gère les commandes imbriquées dans un `try` et les `add_command` enveloppés. |
| `purge_modules.py` | Suppression atomique d'un module : fichier + import + entrée de test. Distingue import DUR et import PARESSEUX, refuse de casser un importeur encore présent. |
| `unifier_antiraid.py` · `refonte_configure.py` · `retape_selecteurs.py` | Les migrations déjà appliquées, gardées comme modèles : preview par défaut, jeton attendu vérifié, `ast.parse` avant écriture. |

---

## 11. BOUTONS QUI MENTENT ET BUGS RESTANTS (mesurés, pas supposés)

À traiter en priorité — un contrôle sans effet est pire qu'un contrôle absent :

1. **`anti_compromised`** — le toggle ON/OFF ne branche **rien** : aucun `c.get('anti_compromised')`
   nulle part. La vraie détection de compte piraté vit dans `compromised_detector.py`, pilotée par
   la clé indépendante `compromised_alerts_channel`. `compromised_action` n'est jamais appliqué.
2. **`badwords_action`** — `_PROT_ACTION_KEYS` mappe `anti_badwords` → `badwords_action`, clé qui
   n'apparaît **qu'à cette ligne** dans tout le fichier. La sanction réellement appliquée utilise
   `badwords_sanction_action`. Le bouton « Sanction » d'Anti-Insultes écrit donc dans le vide.
3. **`anti_newaccount`** — aucune clé `newaccount_action` : le kick est **codé en dur** dans
   `_kick_young_account`. Le bouton « Sanction » n'a aucun effet sur cette protection.
4. **`AfkDaysModal` — arguments inversés.** L'appel V2 passe `(self.g, self.u)` au lieu de
   `(self.u, self.g)` : `cfg()` est lu avec un identifiant d'UTILISATEUR, et le seuil AFK s'écrit
   sous un `guild_id` qui est en réalité un `user_id`. Le réglage « Jours » ne se sauvegarde pas
   là où il est lu.
5. **Deux classes AFK définies deux fois** (`AfkListViewV2`, `AfkActionsViewV2`) : seule la seconde
   existe à l'exécution. Vérifier par diff que la version morte ne contient pas un correctif absent
   de la vivante **avant** de supprimer.
6. **Deux systèmes anti-raid en parallèle**, tous deux vivants sur `on_member_join`, avec des seuils
   et des actions différents et **aucune coordination** : clé `anti_raid` + dict `raid_config` d'un
   côté, `antiraid_enabled` + `antiraid_*` de l'autre. **Décision propriétaire requise** avant de
   fusionner — c'est un changement de comportement de sécurité.
7. **L'AFK dépend d'un module condamné** : `get_afk_members` lit la table `activity_tracking`,
   alimentée par le module « activité ». Le jour où il part, l'AFK ne détecte plus personne.
   **Décision propriétaire requise** : garder les seules écritures `last_message`/`last_vocal`
   comme infra de modération, réécrire sur une source propre, ou supprimer l'AFK.

---

## 10. PREMIÈRE ACTION RECOMMANDÉE DANS LA NOUVELLE SESSION

1. Lire ce fichier en entier + `git log --oneline -10` pour voir les derniers lots.
2. `gh auth switch --user goripegorp-cmd` puis vérifier que la CI est verte sur `main`.
3. **Attaquer `/configure`** (§2 point 1) en le **réécrivant** aux standards du §8 — c'est l'ancre
   qui bloque la suppression de ~80 000 lignes.
4. Puis corriger `KEEP_CMD_NAMES` (§5 piège 2), relancer la fermeture, et livrer par lots CI-verts.

**Toujours** : un lot = une amélioration vérifiable + CI verte + un message de commit qui explique
le *pourquoi*, pas seulement le *quoi*.

---

## 12. SYSTÈME D'ACTIVITÉ — REFONTE « RÔLES AFK » (12/08/2026)

Le système de présence a été **entièrement recalculé** sur demande du propriétaire. Ne pas le
retoucher sans avoir lu ce paragraphe : la règle est contre-intuitive et elle est volontaire.

### Deux mesures, pas une — c'est toute l'astuce

Compter « depuis quand il n'a rien fait » se contourne en une soirée : il suffit de poster un
message la veille du rappel pour disparaître des listes toute l'année. Le propriétaire a décrit
lui-même le contournement (« le ping est le vendredi, alors je poste tous les vendredis »).
On mesure donc **deux choses indépendantes** :

| mesure | ce qu'elle compte | ce qu'elle déclenche |
|---|---|---|
| **silence** | jours consécutifs sans rien, **aujourd'hui compris** | les paliers (rôle AFK → retrait → départ) |
| **présence** | jours vus sur les 7 derniers jours **complets** | le rappel doux |

La journée en cours est **exclue** de la présence : à 9 h personne n'a encore parlé, et la compter
ferait dépendre le verdict de l'heure du passage. Elle est **incluse** dans le silence, pour qu'un
retour soit pris en compte à la seconde.

Le posteur du vendredi a un silence minuscule mais une présence de 1/7 : il est nommé chaque
semaine. Et comme un rappel doux sans suite devient une habitude, **les rappels doux consécutifs
s'accumulent** : au bout de `doux_max` (défaut 3), il bascule au premier palier. C'est **la seule**
chose qui l'attrape — le compteur de jours d'absence, lui, ne le voit jamais.

⚠️ La fenêtre est **bornée par l'ancienneté** (arrivée du membre ET âge du suivi). Sans ça, tout
nouveau venu est « 1 jour sur 7 » dès son inscription.

### Les paliers

| palier | déclencheur | effet |
|---|---|---|
| doux | présence < seuil | message léger, **rien de retiré** |
| 1️⃣ | silence ≥ 7 j | **rôle AFK** → le serveur entier se masque |
| 2️⃣ | silence ≥ 14 j | 2e rôle AFK + **retrait de TOUS ses rôles**, mémorisés |
| 3️⃣ | silence ≥ 21 j | **proposé** au staff. Jamais automatique. |

Retour : **immédiat**. `on_message` → `activite_niveaux.porte_une_etiquette` (comparaison
d'entiers en mémoire, aucun await) → `activite_passage.retour_immediat`. Attendre le passage
suivant laisserait quelqu'un masqué jusqu'à 6 h après avoir écrit.

### Le masquage — l'action la plus destructrice du bot

`activite_niveaux.appliquer_masquage` pose `view_channel=False` sur **tous** les salons, y compris
ceux créés plus tard (`on_guild_channel_create`). Restent visibles : le salon d'annonce (en lecture
seule) et le salon de retour (le seul où l'absent peut écrire).

- **Idempotent** : compare avant d'écrire, un 2e passage ne fait aucun appel réseau.
- **Annulable** : bouton « Tout rouvrir ». Un masquage qu'on ne peut pas défaire ne s'allume pas.
- ⚠️ **Piège Discord** : une autorisation *explicite* `view_channel=True` sur un autre rôle du
  membre **écrase** notre refus. Au palier 2 il n'a plus ces rôles, donc aucun problème ; au
  palier 1 si. On ne le corrige pas en douce — `niv.conflits()` liste les salons et le panneau
  les affiche. Le propriétaire tranche.

### Textes membres — courts et bilingues

`activite_textes.py` centralise TOUT ce que les membres lisent, en FR + EN. Deux règles tenues
**mécaniquement**, pas par bonne volonté :
- `verifier_longueurs()` échoue si une ligne dépasse 90 caractères (un test la lance) ;
- un test refuse le jargon (`palier`, `seuil`, `escalade`, `restitution`…) dans les textes membres.

Consigne d'origine : « les gens détestent lire ». Un pavé n'est pas lu, donc n'informe personne.

### Fichiers

| fichier | rôle |
|---|---|
| `activite.py` | les deux mesures + `verdict()` (**fonction pure**, testée seule) |
| `activite_niveaux.py` | rôles AFK, masquage, retrait/restitution de tous les rôles |
| `activite_textes.py` | FR/EN, garde-fou de longueur |
| `activite_escalade.py` | classement par rôle, application des paliers, retours |
| `activite_passage.py` | l'ordre du passage + retour immédiat + accueil des revenants |
| `activite_message.py` | les 3 messages + règles épinglables + MP de re-bienvenue |
| `activite_panneau.py` | `ActiviteRolesAfkPanelV2` = rôles, masquage, conflits |

Tests : `tests/test_activite_verdict.py` (les scénarios **du propriétaire**, cités mot pour mot)
et `tests/test_activite_niveaux.py` (ce que le retrait ne doit **jamais** toucher).

### Vérifier en local — installez les dépendances

Les 3 CI rouges du lot précédent venaient toutes de l'impossibilité de tester en local :

```
pip install "discord.py>=2.7,<3" aiosqlite aiohttp python-dotenv matplotlib pytest pytest-asyncio
python -m pytest tests/ -q && DISCORD_TOKEN=x python -c "import bot"
```

L'`import bot` est le contrôle qui compte : il exécute le code de module et attrape les
`NameError` que `ast.parse` ne voit pas.

---

## 13. INCIDENT DU 12/08/2026 — « 941 actions demandées » (corrigé)

**Symptôme.** Quelques heures après l'activation, le bot postait dans le salon staff, toutes les
6 h : `941 actions demandées, plafond à 25 — RIEN n'a été appliqué.`

**Cause.** `activite.jours_inactif()` retombe sur `member.joined_at` quand un membre n'a aucune
ligne d'activité. Sur un serveur existant, allumer le système donnait donc à ~941 membres un
« silence » égal à leur **ancienneté** (des mois) → tous classés en expulsion dès le premier
passage. Le garde-fou bloquait — mais **il ne pouvait plus jamais retomber** : ces anciennetés ne
décroissent pas. Interblocage définitif, et le `return` anticipé sautait aussi les retours de
membres, le masquage et le rappel hebdomadaire. Le garde-fou bloquait sa propre réparation.

**Correction — trois volets. Ne pas les défaire séparément, ils se tiennent.**

**1. L'ancre d'observation (`activite.observation_jours`).** Nouvelle clé
`activite_observe_depuis`, posée au premier allumage, **jamais réécrite** (sinon un OFF/ON
repousserait l'escalade à l'infini). `presence()` plafonne : `silence = min(silence_brut,
observation)`. `silence_brut` reste exposé pour l'affichage staff.

⚠️ **Propriété structurelle qui remplace le pansement** : `silence ≤ observation` rend le seuil
d'expulsion **inatteignable** avant autant de jours d'observation réelle. Un test le vérifie sur
toute la plage 0→20.

**2. Le quota remplace l'avortement (`activite_passage.passage`).**

- On ne compte plus l'**expulsion** : c'est une *proposition*, elle n'applique rien. La compter
  gonflait le total de non-actions — c'est littéralement d'où venait le « 941 ».
- On compte `rappel + retrait`, on **tronque** à 25, retrait d'abord, les plus anciens d'abord.
- ⚠️ **Après troncature, filtrer `cl["groupes"]`** : le rappel hebdo se construit dessus, pas sur
  les listes globales. Sans ce filtre, un membre *reporté* serait annoncé publiquement comme ayant
  perdu ses rôles alors qu'on n'y a pas touché.
- Seul cas de blocage total restant : `suivi_muet` — journal **vide** alors qu'on observe depuis
  plus de 3 jours. Sur un serveur vivant c'est impossible : les sondes sont cassées.

**3. Les messages d'ÉTAT ne se répètent plus (`bot.py`, `activite_passage_task`).** Un *événement*
(rôles retirés, rappel parti) est neuf → toujours posté. Un *état* (quota, suivi muet, expulsions
en attente) est identique à chaque passage → **une fois par jour** (`activite_jour_alerte`).
C'est ce qui avait transformé le garde-fou en bruit de fond.

**Aussi corrigé au passage :**

- `presence()` — **fail-open** : `anciennete_du_suivi() is None` veut dire « journal vide », pas
  « borne inconnue, passe ». La borne était *sautée*, donc tout le monde était jugé sur des
  journées sans aucune trace. Désormais `bornes.append(suivi_jours if not None else 0)`.
- Panneau aperçu — il imprimait « 🚪 Proposés à l'expulsion » **et** un bouton rouge trois lignes
  sous la bannière du garde-fou, dans le **même message**. Le staff cliquait et se faisait refuser.
  Bloc entier conditionné, et expulsion **par lots de 25** : un clic ne doit pas vider 900 membres.
- Bouton **« Réarmer l'observation »** (écran Aperçu) : réécrit l'ancre à aujourd'hui. Seul geste
  du système qui va vers la clémence — il ne peut que retarder, donc pas de confirmation.

### ⚠️ Ce qu'il ne faut SURTOUT PAS faire

| tentation | pourquoi c'est faux |
|---|---|
| Remonter `PLAFOND_ACTIONS_PAR_PASSAGE` | ne corrige rien et transforme le bug en catastrophe : 941 `add_roles` + dépouillement complet d'un coup |
| Supprimer le repli sur `joined_at` | `jours_inactif` rendrait `None` → `classer` exclurait **définitivement** tout membre jamais vu |
| Mettre le plafonnement dans `verdict()` | `verdict` est **pure et juste** — c'est son *entrée* qui mentait. Ça casserait `test_un_silence_prolonge_compte_meme_chez_un_nouveau` |
| Borner avec `anciennete_du_suivi()` seule | `MIN(jour)` remonte au déploiement du module, pas à l'activation : n'achète rien |
| Réécrire l'ancre à chaque ON | un OFF/ON deviendrait un moyen de ne jamais être sanctionné |

### Déroulé attendu sur un serveur de 941 fantômes

| | suivis | à étiqueter | à dépouiller | proposés | reporté |
|---|---|---|---|---|---|
| J+0 → J+6 | 941 | 0 | 0 | 0 | 0 |
| J+7 | 941 | 941 | 0 | 0 | 916 |
| J+14 | 941 | 0 | 941 | 0 | 916 |
| J+21 | 941 | 0 | 0 | 941 | 0 |

25 par passage × 4 passages/jour = **100/jour**. Le rattrapage de 941 membres prend donc ~10 jours,
volontairement. Tests : `tests/test_activite_observation.py` (13 tests, dont le cas de production
verrouillé à l'identique).

---

## 14. AUDIT OPÉRATIONNEL DU 12/08 — CE QUI RESTE À RÉPARER

Audit adverse de 73 agents sur les 5 faces du périmètre gardé : **61 constats retenus
sur 67**, 6 écartés par la contre-expertise. Le propriétaire a donné mandat général :
« tous les trucs classés comme morts, les systèmes que tu peux réparer, fais-le ».

### Déjà corrigé et poussé le 12/08

| Commit | Ce qui est réparé |
|---|---|
| `560ef21` | Activité : dépouillement sans retour possible (config par défaut) · retour indétectable sans étiquette · `int("*")` qui tuait le classement en silence |
| `af708f2` | `weekly_security_report` n'avait aucun `.start()` — jamais tourné · `/mod active` lisait des minutes comme des secondes |

### ⛔ RESTE À FAIRE — par ordre décidé avec le propriétaire

**1. Le panneau « Gérer le casier » est mort** — *demi-journée*
- `bot.py:31321` — le menu « retirer une infraction ciblée » est construit en mémoire mais
  jamais ajouté à la vue, alors que le texte affiche « choisis un élément à retirer ci-dessous »
- `bot.py:31349` — le bouton rouge « Effacer TOUT le casier » a un corps vide → le staff
  reçoit « L'interaction a échoué »
- Tracer qui efface quoi dans le journal staff : même `/mod unwarn` ne laisse aucune trace
- **Enjeu** : une sanction automatique abusive reste inscrite à vie et continue d'aggraver
  les escalades futures du membre

**2. Deux sanctions n'arrivent jamais au casier** — *2 heures*
- `bot.py:30884` — `/mod direction` (tous les rôles retirés + timeout 28 j, la sanction la
  plus lourde) n'écrit rien au casier et n'envoie aucun MP. La fiche affiche « Casier vierge »
- `bot.py:30476` et `bot.py:7460` (même défaut dupliqué) — l'escalade automatique des warns
  inscrit un mute et annonce publiquement « mute appliqué » **même quand Discord a refusé**

**3. Trois commandes de sécurité qui ne commandent rien** — *demi-journée à une journée*
- `/permissions sanctionable` — la valeur écrite n'est relue nulle part, le rôle reste sanctionné
- `/protection mode « Soft (log uniquement) »` ne débranche aucune sanction ; `/protection
  trust_user` ne protège personne
- `/setup` affiche « Configuration appliquée — erreurs : aucune » alors que ses trois
  destinations d'écriture sont mortes : 6 écrans, zéro réglage appliqué
- ⚠️ **Décision du propriétaire attendue** : brancher, ou supprimer ?

**4. « Kick » et « Ban » décrivent une action qui n'arrive jamais** — *demi-journée*
- `bot.py:10929` (anti-raid), `bot.py:17516` (~10 panneaux de protection), `bot.py:5948`
  (message public du filtre d'insultes) : les deux options font le même isolement, et le
  journal écrit « Action : BAN »
- **Enjeu** : on croit le phisheur parti, il est encore membre

**5. Les journaux : un serveur non réglé ne reçoit rien, en silence** — *demi-journée*
- `bot.py:7611` — le transcript d'un ticket est perdu pour toujours sans salon de logs :
  le salon est supprimé 5 s après la fermeture
- Ajouter une étape « salon de journaux » à `/setup`, prévenir une fois le fondateur

**6. Sanctions incomplètes** — *demi-journée*
- `bot.py:30774` — `/mod unmute` ne retire que le timeout : au 6e warn le membre garde le
  rôle de quarantaine et reste muet ; passé 28 jours la commande refuse d'agir
- `bot.py:31137` — un kick/ban cliqué par un staff devient un isolement, non écrit au casier
  ni au journal, et le MP annonce « Expulsion » à quelqu'un toujours présent
- `bot.py:30844` — le rôle « Restricted » ne bloque que les salons existants au moment de sa
  création ; créé à la main, il ne bloque rien

**7. Le droit à l'effacement est incomplet**
- Ajouter au registre RGPD les 3 tables créées les 11-12/08 : `activite_jours`,
  `activite_etat`, `activite_expulses`

### ⚠️ Le détail complet des 61 constats

`C:\Users\GoRipe\AppData\Local\Temp\claude\...\tasks\wctfvcim9.output` (JSON, clé `detail`)
— chaque constat porte son fichier:ligne, sa preuve, la nuance du réfuteur et l'effort estimé.
Le fichier est dans un dossier temporaire : **le recopier ailleurs avant de s'y fier**.

### La leçon de la journée, à ne pas réapprendre

Cinq fois en une session, du code parfaitement présent ne s'exécutait jamais :
`on_member_join` sans décorateur, une réaction dont le handler ne contenait qu'un `pass`,
des boutons dont la classe n'était plus enregistrée au boot, `weekly_security_report` sans
`.start()`, et une protection dormante faute de clé réglable.

**Aucun de ces cas n'est attrapé par `ast.parse`, par `import bot`, ni par les tests.**

**Les trois trous sont désormais fermés** (19/08/2026) — chaque détecteur a été
PROUVÉ sur une copie du dépôt où l'on réintroduit le vrai défaut, et refuse de
sortir en vert :

| Détecteur | Le défaut qu'il voit | Preuve |
|---|---|---|
| `verif_evenements.py` | `on_*` sans décorateur, handler vide | déjà en place |
| `verif_boutons_persistants.py` | custom_id posé sur une `View(timeout=None)` que plus aucun `add_view`/`add_dynamic_items` ne capte | remet le `pass` du 19/08 → ressort `onb_lang, l.24543` |
| `verif_boucles.py` | `.start()` sur une fonction qui a perdu son `@tasks.loop` ; boucle sans `.start()` ET exclue du balayage | recolle le décorateur au helper → ressort `veille_roblox_task` |
| `verif_portees.py` | nom utilisé hors de sa portée — le NameError que `verif_noms` ne peut pas voir | a trouvé les 5 résidus de purge, dont `ok` en production |

⚠️ `verif_boucles.py` ne crie PAS sur une boucle sans `.start()` explicite :
`_iter_supervised_loops` balaie automatiquement tous les objets `tasks.Loop`
des globals et relance ce qui ne tourne pas. Ce serait un faux positif — et
c'est précisément le filet posé après l'affaire `weekly_security_report`. Il
n'est fatal que si la boucle est aussi dans `_SUPERVISOR_DENY`, qui exclut de
toutes les sources, balayage compris.

---

## 15. CE QUI RESTE, COMMANDÉ LE 15/08 — SPÉCIFIÉ, PAS ENCORE FAIT

Quatre chantiers demandés. **Le premier est livré**, les trois autres sont
spécifiés ici mot pour mot pour qu'ils ne se perdent pas.

### ✅ 1. Effacer les marques de publication Roblox — FAIT

Bouton rouge **♻️ Tout republier** dans `/configure` → 🎮 Veille Roblox.

⚠️ **Pourquoi il a fallu ce bouton** : la première amorce marquait TOUT le
catalogue comme déjà publié à l'allumage. Le correctif a rendu l'amorce
raisonnable, mais **un correctif de code ne répare pas des données déjà
écrites**. Sur le serveur du propriétaire, 15 articles de moins de 30 jours
restaient invisibles pour toujours. Mesuré, pas supposé.

### ⛔ 2. Remettre l'onglet « Réseaux sociaux » dans /configure

**Le système FONCTIONNE déjà** — le log de démarrage le prouve :

```
[social] YouTube : RSS auto ✅ (vidéos + lives, sans clé)
         Twitter/X · TikTok · Instagram : via RSSHub ✅
         RSSHUB_BASE_URL = https://rsshub-production-7128.up.railway.app
```

Ce n'est donc **pas** à reconstruire : seul l'**onglet** a été retiré pendant la
purge. Les commandes `/social add|list|remove|toggle|poll_now` existent toujours
(vérifié dans les 55 commandes enregistrées).

À faire : une entrée dans `_CONFIG_SECTIONS` + la résolution dans
`_module_select`, sur le modèle de l'entrée `roblox`. Chercher un panneau social
existant avant d'en écrire un.

### ⛔ 3. Purger cadeaux, boss et salons d'événements

> « Les gens peuvent gagner des cadeaux, y a des salons qui apparaissent avec des
> événements comme gagner des cadeaux, combattre des boss. Je veux que tu
> m'assures que tu m'enlèves bien tout ça. On s'en fout, t'enlèves absolument
> tout. »

Pistes relevées en chemin : `auction_settler_task` (déjà retirée),
`_is_sweepable_event_channel`, les salons `🆘`, restes de quêtes et de boss.
⚠️ Passer par `outils/purge_modules.py` et `outils/detacher_module.py`, qui
connaissent le piège des imports durs et la liste `PROTEGES`.

### ⛔ 4. Remettre `/rellseas`, configurable

> « Je veux que tu me la remettes. Et que moi, dans le slash configure, je peux
> configurer cette commande pour savoir qui va l'utiliser. Celui qui utilisera
> cette commande pourra donner un rôle ou retirer un rôle, ou vérifier
> l'activité de la personne. Le même système d'activité dans le serveur, sauf
> que ce sera sur une semaine au propre. »

**Ce qui SUBSISTE et ne doit pas être réécrit :**

| Élément | État |
|---|---|
| `realsy_tracking` (table) | intacte, les données sont là |
| `update_realsy_activity` | appelée à chaque message |
| `RellseasQuizAnswerView` / `RellseasExamineResponseView` | existent, rechargées au boot |
| `rellseas_quizzes` (table) | intacte |
| La commande `/rellseas` | **absente** — purgée avant le 12/08 |
| `check_realsy_inactivity` | **retirée le 12/08** (doublon + son MP mentait) |

**Ce qu'il faut écrire :**

1. Une commande `/rellseas` avec trois actions : **donner** un rôle, **retirer**
   un rôle, **vérifier** l'activité d'un membre.
2. Un réglage dans `/configure` : **quels rôles ont le droit de l'utiliser**.
   ⚠️ Contrôler la permission dans la commande elle-même, pas seulement à
   l'affichage — un panneau n'est pas une garde.
3. La vérification d'activité **réutilise `activite.presence()`**, avec une
   fenêtre d'**une semaine**. Ne PAS réécrire un second compteur : le système
   d'activité gère déjà des seuils propres à chaque rôle (`CLES_ROLE`), c'est
   exactement le cas d'usage prévu le 11/08 pour les clans.

⚠️ **Ne pas rebrancher l'ancienne escalade Realsy.** Elle faisait doublon avec
le système d'activité et son message privé annonçait un retrait de rôle que le
bot ne faisait jamais. Le nouveau système couvre le besoin, avec le réglage
« retour validé par le staff » fait pour les rôles qui ont de la valeur.
