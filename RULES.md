# 📜 Règles permanentes du projet

Ce fichier liste les **contraintes strictes et permanentes** qui doivent être
respectées dans toute évolution du code. À lire avant d'ajouter une feature.

---

## 🚫 Contenu interdit

### ❌ Aucun système romantique / couple / mariage
**STRICTEMENT INTERDIT** sur ce serveur :

- ❌ Système de mariage entre membres (`/marry`, `/divorce`, etc.)
- ❌ Système de couple / duo romantique
- ❌ Bagues, partenaire, conjoint, fiancé(e)
- ❌ "Dating" ou matchmaking romantique
- ❌ Emoji ❤️ comme cœur principal d'un event/mécanique
- ❌ Vocabulaire « amour » dans les messages auto du bot

> Si une feature ressemble à un lien romantique entre membres, **ne pas la coder**.
> Préférer rivalité (`/bond rival`), amitié (`/bond friend`), highfive ou hug.

### ❌ Aucun staff ne doit avoir les commandes Kick ou Ban
- Les sanctions disponibles aux modérateurs sont uniquement :
  warn / mute / direction / unwarn / unmute
- Le bannissement reste accessible aux owners du serveur via Discord nativement,
  pas via slash command modé

### ❌ Pas d'événements dans les salons tickets / annonces / lecture-seule
Les events ne doivent jamais spawn dans :
- Salons tickets
- Salons announcements (annonces, news, updates)
- Salons read-only (lecture-seule pour membres)

Utiliser le helper `_is_chatty_channel` pour filtrer.

### ❌ Pas de mass-mention
Limite Discord TOS : **max 3 mentions** dans un seul message bot.

### ❌ Pas de Kick ni Ban depuis les alliances
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
  romantique / mariage / couple. Cleanup des features `propose_marry`,
  `divorce`, `get_spouse`, achievement `marriage`, event `Vague d'amour`,
  emoji ❤️ comme target d'un event de sync.
