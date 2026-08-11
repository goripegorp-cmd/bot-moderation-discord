# 📊 Système d'activité

> **Éteint par défaut.** Rien ne tourne tant que vous ne l'avez pas allumé
> **et** désigné une cible. Tout se règle dans `/configure` → **📊 Activité**.

---

## 1. Qu'est-ce qu'être « actif » ?

Un membre est actif **sur une journée** s'il pose **au moins un geste
volontaire** parmi ces six :

| | Ce qui compte |
|---|---|
| 💬 **Message** | Écrire dans n'importe quel salon (un message supprimé compte : il a été écrit) |
| 🎤 **Vocal** | Entrer dans un salon, en changer, **reprendre son micro**, partager son écran ou sa caméra |
| 👍 **Réaction** | Réagir à un message, même très ancien |
| 🎛️ **Commande ou bouton** | Lancer une commande, cliquer un bouton, choisir dans un menu |
| 🧵 **Fil** | Ouvrir un fil de discussion |
| 📊 **Sondage** | Voter à un sondage |

Une seule suffit. 200 messages dans la soirée valent exactement une journée,
comme un seul message : le système mesure la **présence**, pas le volume.

### ⚠️ Ce qui ne comptera jamais

**Le statut « en ligne ».** Être connecté ne prouve rien : un téléphone oublié
allumé, un client jamais fermé, un compte secondaire en veille affichent tous
« en ligne » sans qu'aucun humain soit là. C'est exactement ce que ce système
doit attraper — le compter reviendrait à récompenser la fraude.

**Rester assis dans un salon vocal.** On peut y dormir des jours. Seuls les
gestes comptent : entrer, changer de salon, reprendre son micro, se montrer.
Ces gestes se reproduisent naturellement au fil d'une vraie session, donc
quelqu'un qui participe vraiment est crédité chaque jour — même s'il ne quitte
jamais le vocal.

### Les bornes de temps

| | De | À |
|---|---|---|
| **Journée** | minuit | minuit |
| **Semaine** | **lundi 00h00** | lundi 00h00 suivant |
| **Mois** | le 1er 00h00 | le 1er du mois suivant |

Tout est en **heure de Paris**, changements d'heure compris — pas en UTC. Quand
vous dites « lundi 00h00 », c'est minuit chez vous.

Le rappel hebdomadaire part **une seule fois par semaine**, même si le bot
redémarre ou passe plusieurs fois dans la journée.

---

## 2. Chaque rôle a SON propre suivi

**Par défaut, tout le serveur est suivi.** Tous vos membres portent `@everyone`
et beaucoup n'ont aucun autre rôle : allumer le système suffit à couvrir tout le
monde. Les rôles ne servent pas à *activer* le suivi, mais à donner des
**réglages différents** à certains.

Un rôle peut définir, rien que pour lui :

| Réglage | Exemple |
|---|---|
| Ses **trois seuils** | Rappel à 3 j, retrait à 5 j, expulsion à 7 j |
| Son **salon d'annonce** | Les recrues relancées dans #recrutement |
| Son **salon de retour** | Où ce rôle-là revient se signaler |
| Son **jour de rappel** | Lundi pour l'un, vendredi pour l'autre |
| **Retirer le rôle ou non** | Certains rôles ne se retirent jamais |
| **Suspendre ce rôle seul** | Sans éteindre le reste du système |

Deux rôles peuvent donc vivre sur des rythmes qui n'ont rien à voir. Un réglage
laissé vide retombe sur celui du serveur — vous n'avez pas à tout ressaisir pour
changer un seul seuil, et l'écran marque `(serveur)` à côté de ce qui est hérité.

Le **marqueur de semaine est propre à chaque rôle** : un rôle relancé le lundi
n'empêche pas celui du vendredi de partir.

> Le menu « Configurer un rôle en détail » liste jusqu'à **25 rôles** — la limite
> de Discord pour un menu déroulant.

---

## 3. Ce qui arrive à un membre inactif

Les seuils ci-dessous sont les **défauts**, repris par tout rôle qui ne définit
pas les siens.

| Palier | Défaut | Ce qui se passe |
|---|---|---|
| 1️⃣ | 7 jours | Rappel public. Le membre est **mentionné**, garde tout. |
| 2️⃣ | 14 jours | 2ᵉ rappel + **son rôle lui est retiré**. |
| 3️⃣ | 21 jours | **Proposé à l'expulsion** — jamais automatique. |

**Le retrait de rôle est réversible.** Le rôle est mémorisé et **rendu
automatiquement** dès que le membre redevient actif. C'est une mise en veille,
pas une punition. Le membre peut aussi écrire dans le **salon de retour** pour
le récupérer tout de suite.

**L'expulsion n'est jamais automatique.** Le bot poste la liste dans le salon
staff ; vous seul cliquez. Le bouton **recalcule la liste juste avant d'agir** —
quelqu'un revenu entre-temps est épargné.

---

## 4. Qui n'est JAMAIS touché

À aucun palier, jamais, même en cas de bug :

- le **propriétaire** du serveur
- le **super-owner**
- tout **administrateur**
- tout membre **immunisé** en modération (section 👮 Staff & immunités)
- les **bots**

### Et ceux que **vous** dispensez

Écran **🛡️ Dispenses** : vous y désignez les **rôles** et les **membres** qui
n'ont aucune obligation de présence — un ancien, un ami du serveur, un bot
partenaire.

⚠️ **C'est distinct de l'immunité de modération.** Dispenser quelqu'un de
*présence* ne le dispense pas des filtres anti-spam ou anti-scam. Les deux listes
sont séparées exprès : vous pouvez laisser un ancien membre tranquille sans en
faire quelqu'un d'intouchable.

Choisir une entrée déjà dispensée la retire — un seul geste pour les deux sens.
Si la liste devient illisible, le système **dispense** plutôt que d'exposer
quelqu'un à l'expulsion.

La vérification est **fail-closed** : si le bot n'arrive pas à établir qu'un
membre est touchable, il le laisse tranquille. Et elle est **refaite juste avant
chaque action**, pas seulement au moment du calcul — quelqu'un a pu devenir
administrateur entre les deux.

---

## 5. Le garde-fou qui peut tout arrêter

Si un passage veut agir sur **plus de 25 membres d'un coup**, il n'agit sur
**personne** et vous alerte.

Ce n'est pas une limite de débit, c'est un **détecteur de panne**. Si des dizaines
de membres basculent simultanément, la cause la plus probable n'est pas que le
serveur s'est vidé cette nuit : c'est que le suivi est cassé — base réinitialisée,
horloge décalée, ou système activé sur un serveur sans historique.

Dans ce cas, agir ferait des dégâts irréversibles. **Ne relevez pas ce plafond
pour « débloquer » la situation** : cherchez d'abord pourquoi il s'est déclenché.

---

## 6. Récompenses : niveaux et VIP

Tout dérive d'**une seule mesure** : le nombre de **jours actifs cumulés**.

Pas d'XP par message, et c'est délibéré — compter les messages récompense le
spam, compter les jours récompense la présence.

| Niveau | Jours actifs | | Niveau | Jours actifs |
|---|---|---|---|---|
| 1 | 1 | | 9 | 90 |
| 3 | 7 | | 12 | 180 |
| 6 | 30 | | 15 | 365 |

Au-delà du niveau 15 : +1 niveau tous les 90 jours actifs.

Le **rôle VIP** est donné à partir d'un niveau que vous choisissez (défaut :
niveau 6, soit un mois de présence). Il n'est retiré **que** si le membre atteint
le palier de retrait d'inactivité — pas au premier jour d'absence.

---

## 7. Les salons du serveur

| Salon | À quoi il sert | Qui doit le voir |
|---|---|---|
| 📢 **Annonce** | Le rappel hebdomadaire, avec les mentions | Tout le monde |
| 🔙 **Retour** | Où un membre écrit pour récupérer son rôle | Tout le monde |
| 🛡️ **Staff** | Rapports et propositions d'expulsion | Staff uniquement |

⚠️ **Ne les mélangez pas.** Mettre le salon staff en public exposerait la liste
des membres proposés à l'expulsion.

Ce sont les salons **par défaut**. Chaque rôle peut avoir les siens.

Le rappel part **une fois par semaine par rôle**, le jour propre à ce rôle.

---

## 8. Comment le mettre en route

1. `/configure` → **📊 Activité**
2. **🎯 Qui est surveillé** → choisissez un rôle, ou « tout le serveur »
3. **Configurer un rôle en détail** → ses seuils, son salon, son jour —
   répétez pour chaque rôle, ils sont indépendants
4. **📢 Salons** → les trois salons + le jour du rappel
5. **🔎 Aperçu** → il vous dit d'abord **si le suivi capte vraiment** vos
   messages, votre vocal et vos réactions, puis qui serait concerné —
   **sans rien appliquer**
6. Seulement ensuite : allumez l'interrupteur

> **Laissez tourner une semaine avant d'allumer les paliers.** Le système ne
> connaît que ce qu'il a vu : au premier jour, tout le monde paraît inactif.
> L'aperçu vous le montrera, et le garde-fou vous bloquerait de toute façon.

---

## 9. Où est quoi

| Fichier | Rôle |
|---|---|
| `activite.py` | Suivi des 3 sources, config, calcul des jours |
| `activite_escalade.py` | Classement par palier, retrait et restitution des rôles |
| `activite_passage.py` | Le passage quotidien — un seul point d'entrée |
| `activite_recompenses.py` | Niveaux et VIP |
| `activite_calendrier.py` | Toutes les bornes de temps : jour, semaine, mois |
| `activite_panneau.py` | Le panneau de configuration (Components V2) |
| `tests/test_activite.py` | 35 tests : décision, niveaux, calendrier |

**Tables** : `activite_jours` (une ligne par membre et par jour) et
`activite_etat` (palier, rôles retirés, niveau, VIP).

Le nombre de jours actifs se **recalcule** depuis `activite_jours` : même si la
table d'état est perdue, les niveaux se reconstituent.
