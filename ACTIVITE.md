# 📊 Système d'activité — RETIRÉ le 03/10/2026

> « Le système d'activité, quand les gens sont AFK, quand ils ne parlent pas et
> tout, enlève-moi complètement ce système et ce calcul inutile. […] Tu
> t'assures juste que tout le monde voit bien tous les salons. Toutes les
> catégories aussi. » — le propriétaire, 03/10/2026

## Ce qui a disparu

Paliers, rôles AFK (« 💤 AFK », « 💤 AFK · rôles retirés », « 👀 Peu actif »,
« 🚪 Compte abandonné »), masquage des salons, retrait des rôles, rappels, porte
de retour, salon AFK, récompenses par l'activité, onglet **📊 Activité** de
`/configure`, boucle `activite_passage_task`.

## Ce qui a été défait sur Discord — `activite_demontage.py`

Au démarrage, une fois par serveur (marque `activite_demonte_le`) :

1. **rôles rendus** aux membres que le palier 2 avait dépouillés
   (`activite_etat.roles_retires`) ; un membre parti les retrouve à son retour ;
2. **rôles du système supprimés** — et avec eux leurs refus « voir le salon »
   sur tous les salons et catégories ; un rôle du serveur seulement *désigné*
   est gardé, sans refus ni porteurs ;
3. **salons du système supprimés** (porte de retour, salon AFK) — jamais un
   salon qui sert ailleurs dans la config, ni un salon au nom général.

Le compte rendu part une fois dans le salon de logs.

## Ce qui reste

Le **comptage** des jours d'activité (`activite.py`), pour le seul bouton
« Activité » de `/rellseas` — choix du propriétaire le 03/10. Aucun rôle, aucun
masquage, aucun message.

## Nouveaux arrivants — `visibilite_serveur.py`

À chaque démarrage, une ligne `[visibilite]` : ce qu'un nouvel arrivant
(@everyone + rôle d'arrivée) voit, catégories et salons invisibles (souvent
voulus : staff, journaux). Si l'onboarding Discord est actif, tous les salons
publics deviennent « par défaut » — sinon un nouveau ne les voit pas d'office.
