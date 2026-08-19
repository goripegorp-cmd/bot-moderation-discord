# 🎯 VEILLE ROBLOX — LE CAHIER DES CHARGES

> Deux systèmes distincts, demandés le 12/08/2026. Ce fichier fixe ce qui est
> **non négociable**. Il se lit AVANT d'écrire une ligne de code, et il prime sur
> toute facilité d'implémentation.
>
> ⚠️ Le HANDOFF classe « Roblox » dans le périmètre SUPPRIMÉ par la refonte. Ces
> deux systèmes sont une **réintroduction explicitement demandée** par le
> propriétaire, pas un reste oublié. Ne pas les purger en croyant bien faire.

---

## LES DEUX SYSTÈMES

### A. Les accessoires — veille et prédiction

Demandé mot pour mot :

> « Roblox peut créer des nouveaux accessoires sur la plateforme, il met des
> nouveaux accessoires ou alors d'anciens accessoires qui remet en vente ou
> obtenable qui sont des accessoires potentiellement rares. Il y a aussi des
> prédictions qui sont justifiées, comme quoi certains limited ou certains
> accessoires deviendraient limited — **uniquement ceux qui sont créés par
> Roblox**. […] Pour qu'on puisse savoir à l'avance si l'item va se vendre cher
> ou pas. Comme un vrai système de trading. »

Quatre flux à publier :
1. les **nouveaux articles créés par Roblox** ;
2. les articles **remis en vente** ou redevenus obtenables ;
3. les articles **en prédiction** — susceptibles de passer collectionnables ;
4. les articles qui **viennent de** passer collectionnables.

### B. L'actualité — Studio, UGC, développeurs, artistes, événements

Demandé mot pour mot :

> « C'est là où je te demande de **ne pas faire d'erreur et de bien relire ce que
> tu fais**. […] toutes les mises à jour et les actualités sur Roblox qui sont
> liées à tout le domaine de Roblox Studio. Tout le domaine lié aux UGC
> créateurs, tout le domaine lié aux développeurs, à tous les artistes. […] Je
> veux que tu relèves **absolument tout**. C'est très très très important. Pareil,
> les événements à venir. »

Chaque système a son **interrupteur** et son **salon**, réglés dans `/configure`.

---

## LES NON-NÉGOCIABLES

### 1. Les liens doivent être certains

> « Que les liens soient approuvés et certifiés, qu'on peut aller sur l'item en
> question sans se poser de questions. »

C'est une exigence de **sécurité**, pas de confort. Un lien douteux publié par un
bot de modération, sur un serveur qui lutte contre le phishing, serait une faute.

- Une URL n'est JAMAIS recopiée depuis une réponse d'API, un titre, ni un texte.
  Elle est **reconstruite** à partir du domaine officiel en dur dans le code et de
  l'**identifiant numérique** de l'article.
- L'identifiant est validé comme entier avant construction. Pas d'entier, pas de lien.
- Le domaine est une **constante du module**, jamais une valeur reçue.
- Un article dont l'identifiant est absent ou illisible est publié **sans lien**,
  jamais avec un lien approximatif.

### 2. Webhooks et Components V2

> « Tu te sers vraiment des webhooks, d'une nouvelle technologie. »

- Publication par **webhook**, avec un nom et un avatar propres au flux, pour que
  la source soit lisible d'un coup d'œil dans le salon.
- Affichage en **Components V2** (`LayoutView`, `Container`, `Section`,
  `Separator`, `Thumbnail`) — jamais d'embed hérité.
- Voir `UI.md` : la règle permanente s'applique intégralement.
- Limites à respecter : 40 composants par vue, 25 options par select,
  label ≤ 100, description ≤ 100, placeholder ≤ 150. `content=` est INTERDIT
  sur une `LayoutView`.

### 3. Un quadrillage, pas un pavé

> « Que tout soit propre, que le quadrillage vraiment de toutes ces informations
> lors de la publication. »

Chaque publication est une **fiche structurée**, toujours dans le même ordre, pour
qu'on la lise en diagonale :

```
[vignette]   TYPE D'ARTICLE · NOM
             créateur · date de mise en vente
             ─────────────────────────────
             prix · quantité · statut
             note de prédiction + ce qui la justifie
             ─────────────────────────────
             [Voir l'article]
```

Un champ inconnu s'affiche `—`. Il ne disparaît pas : une fiche à géométrie
variable ne se lit plus en diagonale, et c'est tout l'intérêt du quadrillage.

### 4. Des sources tenues pour fiables

> « Que tes sources soient ultra fiables. »

- Une source n'est retenue que si elle a été **ouverte et lue**, avec un extrait
  réel à l'appui. Une URL de mémoire est une URL morte en puissance.
- Priorité absolue aux **sources officielles**. Une source communautaire est
  autorisée seulement si elle est **étiquetée comme telle** dans la publication.
- ⚠️ **Une source qui ne répond plus doit le DIRE.** Un flux mort ressemble à un
  flux calme — ce défaut précis est tombé cinq fois dans ce dépôt le 12/08. Toute
  source muette au-delà de son rythme habituel remonte une alerte au salon staff.

### 5. Temps réel et coût maîtrisé

> « Un vrai travail de qualité en temps réel […] et que ton code soit ultra
> optimisé. »

- Interrogation **par flux**, à un rythme adapté à chacun — pas une grande boucle
  qui réveille tout.
- **Aucun travail au repos** : rien n'est recalculé tant qu'aucune nouveauté n'est
  détectée.
- Dédoublonnage par identifiant, **persisté en base** : un redémarrage ne doit
  jamais republier ce qui est déjà sorti.
- Tables **bornées** : on ne garde pas l'historique complet du catalogue.
- La boucle est déclarée, **démarrée** (`.start()` dans `on_ready`) ET inscrite au
  superviseur `_SUPERVISED_LOOP_NAMES`. Deux boucles ont été livrées sans `.start()`
  dans ce dépôt : elles n'ont jamais tourné une seule fois.

### 6. Une prédiction qui ne ment pas

Le système annonce une valeur probable. Il doit donc dire **sur quoi il se fonde**
et **ce qu'il ignore**.

- La note affiche ses **facteurs** et leur poids, jamais un pourcentage nu.
- Une donnée manquante réduit la **confiance** affichée — elle n'est pas devinée.
- Aucune formulation de certitude. On décrit des indices, pas un avenir.

---

## LE PREMIER ALLUMAGE

Ne jamais déverser l'historique dans le salon. À l'activation, on pose une borne
au moment présent et on ne publie que ce qui sort ensuite. Un rattrapage explicite
peut être proposé, jamais imposé.

---

## LES NOTIFICATIONS — UN RÔLE PAR TYPE (owner 19/08/2026)

> « Sous chacune des annonces Roblox […] un petit rôle pour le ping […] ils ont
> juste à cliquer une fois sur le bouton […] Ils auront juste à rappuyer dessus
> pour ne plus recevoir les notifications. »

Huit catégories, définies dans `roblox_pings.py`. Elles ne sont pas inventées :
elles reprennent les `domaine` réels de `roblox_news.SOURCES` et les deux flux
d'accessoires. Un test compare les deux tables — un domaine renommé sans être
répercuté ici publierait **sans ping, sans erreur**.

| Bouton | Rôle créé | Ce qu'il notifie |
|---|---|---|
| `rbxping:annonces` | 🟢 Annonces Roblox | les mises à jour officielles |
| `rbxping:studio` | 🔵 Roblox Studio | les notes de version de Studio et du moteur |
| `rbxping:securite` | 🔴 Sécurité Roblox | règles, sécurité, modération |
| `rbxping:evenements` | 🟣 Événements Roblox | événements et concours |
| `rbxping:devs` | 🟠 Développeurs Roblox | ressources du staff Roblox |
| `rbxping:presse` | 🟡 Presse Roblox | la salle de presse (FR **et** EN : même contenu, un seul rôle) |
| `rbxping:limited` | 💎 Passages Limited | les accessoires qui **viennent** de passer Limited |
| `rbxping:nouveaux` | 🆕 Nouveaux accessoires | les accessoires que Roblox vient de créer |

**Les quatre règles à ne pas défaire.**

1. **Rôles non mentionnables.** Créés `mentionable=False` : un membre ne doit
   pas pouvoir réveiller le serveur avec. Le bot ping quand même, en passant
   `allowed_mentions(roles=[role])` à chaque envoi. **Sans cette autorisation,
   le `<@&id>` s'affiche en pastille et ne notifie personne** — un ping
   silencieux est indiscernable d'un ping réussi.
2. **Création paresseuse.** Aucun rôle au démarrage : un serveur qui n'active
   jamais la veille ne verra pas huit rôles apparaître. Le rôle naît à la
   première annonce de sa catégorie, ou au premier clic.
3. **Libellé neutre sur le bouton.** Un message est le même pour tout le monde :
   la moitié du salon est déjà abonnée. « S'abonner » mentirait aux uns,
   « Se désabonner » aux autres. Le bouton dit ce que fait le clic — il bascule
   — et la réponse **éphémère** annonce l'état réel de celui qui a cliqué.
4. **Les échecs ne se déguisent jamais en succès.** Permission « Gérer les
   rôles » absente et rôle placé au-dessus du bot sont deux échecs **distincts**,
   chacun avec sa phrase. Le second est le plus vicieux : le rôle existe, tout a
   l'air normal, et l'attribution échoue.

⚠️ Le bouton est un `DynamicItem` (`RobloxPingButton`) réenregistré au boot par
`bot.add_dynamic_items`. **Sans ce réenregistrement, tous les boutons déjà posés
dans l'historique du salon deviennent muets.** `outils/verif_boutons_persistants.py
bot.py roblox_panneau.py` le vérifie — les deux fichiers ensemble, le bouton
étant posé dans l'un et enregistré dans l'autre.

---

## ÉTAT LIVRÉ AU 12/08/2026, ET D'OÙ VIENNENT LES CHIFFRES

Tout est poussé sur `main`, CI verte à chaque lot. Ce qui suit n'est pas une
intention : c'est ce qui tourne.

### Les fichiers

| Fichier | Rôle |
|---|---|
| `roblox_veille.py` | relevé du catalogue, comparaison d'instantanés, indice, images, santé |
| `roblox_news.py` | 5 sources d'actualité, fraîcheur, déduplication, santé |
| `roblox_panneau.py` | l'onglet `/configure` et les deux formats de fiche |
| `bot.py` → `veille_roblox_task` | la boucle, toutes les 30 min |

### Les quatre salons

Réglables séparément dans `/configure` → 🎮 Veille Roblox. Un seul salon réglé →
tout y tombe.

1. **🆕 Nouveautés** — articles créés par Roblox (`CreatorTargetId=1`)
2. **💎 Passés collectionnables** — détectés par comparaison de deux relevés
3. **👀 À surveiller** — indice ≥ 60 uniquement
4. **📢 Actualité** — 5 sources officielles, étiquetées par domaine

### Les constantes, et leur justification MESURÉE

⚠️ Ne pas les changer sans refaire la mesure. Chacune vient d'un appel réel.

| Constante | Valeur | Pourquoi CE chiffre |
|---|---|---|
| `LIMITES_AUTORISEES` | 10, 28, 30, 60, 120 | l'API refuse tout le reste par un HTTP 400 explicite |
| `AGE_MIN_JOURS` | 10 | un article neuf n'a ni revente, ni demande installée : rien à dire |
| `AGE_MAX_JOURS` | 90 | au-delà c'est une archive, plus une nouvelle |
| `SEUIL_INDICE_AFFICHE` | 60 | en dessous, l'indice n'est pas une faiblesse mais une ABSENCE de signal — on se tait |
| `SEUIL_SURVEILLER` | 60 | ce flux doit être rare et sûr |
| `FRAICHEUR_MAX_JOURS` | 30 | mesuré : laisse passer le plus récent de chaque catégorie (la plus lente est à 17 j), bloque les billets de 73, 137, 277 et 337 jours |
| `PAUSE_ENTRE_APPELS` | 2 s | débits mesurés : catalogue 12/60 s, fiche 10/60 s |

### Trois règles de sécurité à ne pas défaire

1. **Les liens sont RECONSTRUITS**, jamais recopiés d'une réponse. Domaine en dur
   + identifiant validé comme entier. Sans entier, la fiche part **sans lien**.
   Éprouvé : une chaîne empoisonnée rend `None`.
2. **Les URL d'images font exception** — elles portent une empreinte et ne sont
   pas reconstructibles. Elles sont donc **filtrées sur le domaine officiel**.
3. **Fail-closed sur les dates de news** : une date illisible = trop vieux. Pour
   un accessoire c'est l'inverse (fail-open) — le risque n'est pas le même :
   rater une nouveauté d'un côté, annoncer une alerte périmée de l'autre.

### La traduction ne vient pas de nous

L'en-tête `Accept-Language: fr-fr` sur le même point d'API renvoie le nom
**officiel** de Roblox — « Chapeau Ladoo tricolore ». Mesuré : 26 articles
traduits sur 28. On ne traduit jamais nous-mêmes ; on demande et on cite. Sans
traduction officielle, une seule ligne — jamais deux fois la même chose.

⚠️ Les billets du FORUM, eux, n'ont pas de version française. Ils restent en
anglais. Les traduire à la machine sans le dire serait un mensonge de plus.

### Ce qui reste ouvert

- Les news tombent dans **un seul salon**, étiquetées par domaine. Un salon par
  domaine est possible — environ une demi-heure.
- Le modèle de prédiction **par la vitesse** (favoris/jour, écoulement du stock,
  apparition d'un revendeur) : recherche lancée, pas encore implémenté. C'est le
  seul terrain où l'on peut dépasser les outils existants — ils publient tous une
  photographie, personne ne publie la dérivée.
