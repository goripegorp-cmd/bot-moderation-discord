# 📜 Règles permanentes du projet

Ce fichier liste les **contraintes strictes et permanentes** qui doivent être
respectées dans toute évolution du code. À lire **avant** d'ajouter une feature.

---

## 🎯 Identité du serveur

Ce serveur est **un serveur d'événements, de gestion, de compétition et de
communauté Roblox**. Pas une plateforme de relations interpersonnelles.

Direction prise :
- ✅ **Événements** : boss raids, world bosses, mini-jeux, treasure hunt, quiz
- ✅ **Économie** : coins, bank, crafting, enchantement, forge, **vente au marchand** (item → pièces)
- ✅ **Progression** : XP, level, prestige, achievements, streaks
- ✅ **Clans / Factions / Alliances** : guildes, équipes, coffres partagés
- ✅ **Gestion** : alliance management, trésorerie, log d'activité, rôles
- ✅ **Compétition** : duels, tournois, ladder Elo, faction wars
- ✅ **Roblox-spécifique** : updates, link verify, achievements broadcasts

### 🚫 Trading joueur-à-joueur STRICTEMENT INTERDIT
Aucun item / équipement / pièce ne doit jamais **changer de joueur** :
- ❌ **Trade P2P** (échange direct d'items entre 2 joueurs) — désactivé (Phase 166)
- ❌ **Hôtel des ventes / enchères** (auction house) — désactivé (Phase 166)
- ❌ **Marketplace** joueur-à-joueur (revente d'items à d'autres joueurs) — désactivé
- ✅ Seule transformation autorisée d'un item en pièces : **la VENTE AU MARCHAND**
  (système), via le coffre `/inventory` → bouton Équipement (Phase 217).

Raison : empêcher le passage de stuff des anciens vers les nouveaux (qui tue la
progression), les arnaques, et le RMT. Le stuff se **gagne** (combat, loot,
craft), il ne se **transfère pas**.

---

## 🚫 Contenu interdit (strict)

### ❌ Aucun système relationnel / romantique / "copain-copain"
**TOTALEMENT INTERDIT** :

- ❌ **Mariage** / fiançailles / duo permanent / partenariat romantique
- ❌ **Couple** / dating / matchmaking / "âme sœur"
- ❌ **Amitié explicite** entre joueurs (système de friendship, friend list,
     amis acceptés) — l'amitié n'est PAS une feature à coder
- ❌ **Hug / câlin / highfive** / interactions tactiles 1-vers-1
- ❌ **Compliment anonyme** / "tu es génial" / gentillesse anonyme
- ❌ **Cœur** (❤️ 💕 💖 💝 💞 💗 💘 💌 🥰 😘 ❣️ 💟) comme emoji de feature
     ou de panel. Exception unique : ❤️ utilisé pour HP en combat (convention
     RPG universelle, lifepoints/santé).
- ❌ Vocabulaire « amour », « cœur de ... », « ami(e) cher(e) », etc.
     dans les messages générés par le bot

> Si une feature ressemble à "rapprocher deux joueurs personnellement",
> **ne pas la coder**. Préférer rivalité (déjà existante), faction wars,
> alliance contribution, leaderboard, mentor/apprenti (système d'aide).

### ❌ Aucun staff ne doit avoir les commandes Kick ou Ban
- Sanctions modé disponibles : **warn / mute / direction / unwarn / unmute**
- Le bannissement reste accessible aux owners du serveur via Discord nativement,
  pas via slash command modé

### ❌ Pas d'événements dans tickets / annonces / lecture-seule
Les events ne doivent jamais spawn dans :
- Salons tickets
- Salons announcements (annonces, news, updates)
- Salons read-only (lecture-seule pour membres)

Utiliser le helper `_is_chatty_channel` pour filtrer.

### ❌ Pas de mass-mention
Limite Discord TOS : **max 3 mentions** dans un seul message bot.

### ❌ Alliances : pas de pouvoir sur Discord
- Le chef d'une alliance peut expulser un membre **de l'alliance** uniquement
- Il ne peut JAMAIS kick / ban un membre du serveur Discord
- Une expulsion d'alliance retire seulement les permissions d'alliance, pas la
  présence sur le serveur

---

## ✅ Conventions code

- discord.py 2.7.1 — Components V2 (LayoutView, Container, Section) systématique
- SQLite via aiosqlite — async/await partout
- Pas de fichier Python > 80k lignes — split en modules dès que possible
- Try/except englobant sur tous les callbacks de buttons et tâches
- Limite 100 slash commands Discord — préférer `app_commands.Group`
  pour consolider

---

## 🔖 Historique des règles

- **2026-05-28** : Création du fichier. Interdiction explicite de tout système
  romantique / mariage / couple.
- **2026-05-28** : **Renforcement** — interdiction étendue à toute feature
  type "copain-copain" : friendship, hug, highfive, compliment anonyme,
  emoji cœurs (sauf ❤️ HP). Strip :
    - `social_bonds.py` (module entier supprimé)
    - `/bond` group + 7 sub-commands (friend, unfriend, rival, unrival,
       hug, highfive, list)
    - `ComplimentSelectView` + `ComplimentOpenView` +
       `_post_compliment_of_the_day` + `compliment_dispatcher`
       (dead-code restant de Phase 48 Suppression Compliment)
    - Achievement `marriage` dans engagement41.py
    - Event "Vague d'amour ❤️" dans events42.py
