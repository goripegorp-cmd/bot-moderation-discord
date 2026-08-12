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
