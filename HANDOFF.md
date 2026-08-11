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
