# 📊 Système d'activité

> **Éteint par défaut.** Rien ne tourne tant que vous ne l'avez pas allumé
> **et** désigné une cible. Tout se règle dans `/configure` → **📊 Activité**.

---

## 1. Qu'est-ce qu'être « actif » ?

Un membre est actif **sur une journée** s'il fait **au moins une** de ces trois choses :

| | Ce qui compte | Ce qui ne compte pas |
|---|---|---|
| 💬 **Message** | Écrire dans n'importe quel salon | Un message supprimé compte quand même — il a été écrit |
| 🎤 **Vocal** | **Entrer** dans un salon vocal | Couper son micro, se mettre en sourdine, changer de salon |
| 👍 **Réaction** | Réagir à un message, même ancien | Retirer une réaction |

Une seule suffit. 200 messages dans la soirée valent exactement une journée,
comme un seul message : le système mesure la **présence**, pas le volume.

La journée est comptée en **UTC**.

---

## 2. Ce qui arrive à un membre inactif

Trois paliers, avec des seuils que **vous** réglez, **rôle par rôle**.

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

## 3. Qui n'est JAMAIS touché

À aucun palier, jamais, même en cas de bug :

- le **propriétaire** du serveur
- le **super-owner**
- tout **administrateur**
- tout membre **immunisé** (section 👮 Staff & immunités)
- les **bots**

La vérification est **fail-closed** : si le bot n'arrive pas à établir qu'un
membre est touchable, il le laisse tranquille. Et elle est **refaite juste avant
chaque action**, pas seulement au moment du calcul — quelqu'un a pu devenir
administrateur entre les deux.

---

## 4. Le garde-fou qui peut tout arrêter

Si un passage veut agir sur **plus de 25 membres d'un coup**, il n'agit sur
**personne** et vous alerte.

Ce n'est pas une limite de débit, c'est un **détecteur de panne**. Si des dizaines
de membres basculent simultanément, la cause la plus probable n'est pas que le
serveur s'est vidé cette nuit : c'est que le suivi est cassé — base réinitialisée,
horloge décalée, ou système activé sur un serveur sans historique.

Dans ce cas, agir ferait des dégâts irréversibles. **Ne relevez pas ce plafond
pour « débloquer » la situation** : cherchez d'abord pourquoi il s'est déclenché.

---

## 5. Récompenses : niveaux et VIP

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

## 6. Les trois salons

| Salon | À quoi il sert | Qui doit le voir |
|---|---|---|
| 📢 **Annonce** | Le rappel hebdomadaire, avec les mentions | Tout le monde |
| 🔙 **Retour** | Où un membre écrit pour récupérer son rôle | Tout le monde |
| 🛡️ **Staff** | Rapports et propositions d'expulsion | Staff uniquement |

⚠️ **Ne les mélangez pas.** Mettre le salon staff en public exposerait la liste
des membres proposés à l'expulsion.

Le rappel n'est envoyé **qu'une fois par semaine**, le jour que vous choisissez.

---

## 7. Comment le mettre en route

1. `/configure` → **📊 Activité**
2. **🎯 Qui est surveillé** → choisissez un rôle, ou « tout le serveur »
3. **⚙️ Seuils** → réglez les trois paliers pour ce rôle
4. **📢 Salons** → les trois salons + le jour du rappel
5. **🔎 Aperçu** → vérifiez qui serait concerné, **sans rien appliquer**
6. Seulement ensuite : allumez l'interrupteur

> **Laissez tourner une semaine avant d'allumer les paliers.** Le système ne
> connaît que ce qu'il a vu : au premier jour, tout le monde paraît inactif.
> L'aperçu vous le montrera, et le garde-fou vous bloquerait de toute façon.

---

## 8. Où est quoi

| Fichier | Rôle |
|---|---|
| `activite.py` | Suivi des 3 sources, config, calcul des jours |
| `activite_escalade.py` | Classement par palier, retrait et restitution des rôles |
| `activite_passage.py` | Le passage quotidien — un seul point d'entrée |
| `activite_recompenses.py` | Niveaux et VIP |
| `activite_panneau.py` | Le panneau de configuration (Components V2) |
| `tests/test_activite.py` | 25 tests sur la logique de décision |

**Tables** : `activite_jours` (une ligne par membre et par jour) et
`activite_etat` (palier, rôles retirés, niveau, VIP).

Le nombre de jours actifs se **recalcule** depuis `activite_jours` : même si la
table d'état est perdue, les niveaux se reconstituent.
