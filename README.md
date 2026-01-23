# 🛡️ Bot Discord - Modération & Protection

Bot complet de modération pour Discord avec système de warns, protections automatiques et logs.

---

## 📋 Fonctionnalités

### Commandes de Modération
| Commande | Description |
|----------|-------------|
| `/warn @membre [raison]` | Avertir un membre |
| `/warnings @membre` | Voir les warns d'un membre |
| `/clearwarns @membre` | Supprimer tous les warns |
| `/delwarn [id]` | Supprimer un warn spécifique |
| `/mute @membre [raison]` | Mute un membre (rôle) |
| `/unmute @membre` | Unmute un membre |
| `/timeout @membre [minutes] [raison]` | Timeout (natif Discord) |
| `/untimeout @membre` | Retirer le timeout |
| `/kick @membre [raison]` | Expulser un membre |
| `/ban @membre [raison] [delete_days]` | Bannir un membre |
| `/unban [user_id]` | Débannir un utilisateur |
| `/clear [nombre]` | Supprimer des messages |
| `/modlogs @membre` | Voir l'historique des sanctions |

### Commandes de Configuration (Owner uniquement)
| Commande | Description |
|----------|-------------|
| `/config logs #salon` | Définir le salon de logs |
| `/config muterole @role` | Définir le rôle mute |
| `/config sanctions [mute] [kick] [ban]` | Configurer les sanctions auto |
| `/config protection [type] [on/off]` | Activer/désactiver une protection |
| `/config immunerole [add/remove] @role` | Gérer les rôles immunisés |
| `/config exemptchannel [add/remove] #salon` | Exempter un salon des protections |
| `/config view` | Voir la configuration actuelle |

### Protections Automatiques
- 🔗 **Anti-Liens** - Bloque tous les liens
- 🖼️ **Anti-Images** - Bloque les images/GIFs
- 🎣 **Anti-Phishing** - Détecte les liens malveillants (activé par défaut)
- 📨 **Anti-Spam** - Protection contre le spam
- 🚨 **Anti-Raid** - Détection des raids
- 🤖 **Anti-Fake Bots** - Protection contre les faux bots

### Système de Logs
- Actions de modération
- Messages supprimés/modifiés
- Arrivées/départs de membres

---

## 🚀 Installation

### Prérequis
- Python 3.10 ou supérieur
- pip (gestionnaire de paquets Python)

### Étapes

1. **Télécharger les fichiers**
   - `bot.py`
   - `requirements.txt`
   - `.env`

2. **Ouvrir un terminal** dans le dossier des fichiers

3. **Installer les dépendances**
   ```bash
   pip install -r requirements.txt
   ```

4. **Lancer le bot**
   ```bash
   python bot.py
   ```

---

## ⚙️ Configuration Initiale

Une fois le bot lancé et présent sur ton serveur :

### 1. Configurer le salon de logs
```
/config logs #logs-modération
```

### 2. Créer et configurer le rôle mute
- Créer un rôle "Muted" sur ton serveur
- Retirer les permissions d'envoyer des messages pour ce rôle dans tous les salons
- Configurer le rôle dans le bot :
```
/config muterole @Muted
```

### 3. Définir les rôles immunisés (staff)
```
/config immunerole add @Staff
/config immunerole add @Modérateur
```

### 4. Configurer les sanctions automatiques (optionnel)
```
/config sanctions warns_mute:3 warns_kick:5 warns_ban:7
```
(0 = désactivé)

### 5. Activer/désactiver les protections
```
/config protection anti_link true
/config protection anti_image false
```

### 6. Exempter des salons (optionnel)
```
/config exemptchannel add #liens-autorisés
```

### 7. Vérifier la configuration
```
/config view
```

---

## 📝 Notes Importantes

- **Owner** : Le propriétaire du serveur est TOUJOURS immunisé
- **Rôles immunisés** : Les membres avec ces rôles ne peuvent pas être sanctionnés
- **Salons exemptés** : Les protections (anti-link, etc.) ne s'appliquent pas dans ces salons
- **Sanctions auto** : Mettre 0 pour désactiver une sanction automatique

---

## 🔒 Sécurité

- Ne partage JAMAIS ton fichier `.env` contenant le token
- Régénère ton token si tu penses qu'il a été compromis
- Seul le owner du serveur peut modifier la configuration

---

## 📞 Support

En cas de problème, vérifie :
1. Que Python 3.10+ est installé : `python --version`
2. Que les dépendances sont installées : `pip install -r requirements.txt`
3. Que le token dans `.env` est correct
4. Que le bot a les permissions nécessaires sur le serveur (Administrator recommandé)
5. Que les intents sont activés sur le Discord Developer Portal

---

## 🎯 Permissions Discord Recommandées

Pour le bot :
- Administrator (ou au minimum) :
  - Gérer les rôles
  - Gérer les messages
  - Expulser des membres
  - Bannir des membres
  - Modérer les membres
  - Voir les salons
  - Envoyer des messages
  - Intégrer des liens
