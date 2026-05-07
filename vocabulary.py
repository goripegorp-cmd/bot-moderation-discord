"""
vocabulary.py - Vocabulaire centralise du bot (Phase 0 du redesign 2026).

Tous les libelles UI (boutons, titres, descriptions standards, messages
d'erreur) sont definis ici pour :
- Coherence entre tous les modules
- Vocabulaire professionnel et comprehensible
- Preparation a l'i18n (FR/EN ulterieur)
- Modification rapide d'un terme a un seul endroit

Convention :
- Classes statiques regroupent les libelles par theme
- Pas d'emojis dans les classes "Term" (libelle pur)
- Les emojis sont dans Action / Status (UI), pas dans le vocabulaire metier
"""
from __future__ import annotations


# =============================================================================
# ACTIONS (boutons, callbacks)
# =============================================================================

class Action:
    """Libelles d'actions standards (boutons UI)."""

    SAVE = "Sauvegarder"
    SAVE_ICON = "💾 Sauvegarder"
    CANCEL = "Annuler"
    CANCEL_ICON = "✖️ Annuler"
    BACK = "Retour"
    BACK_ICON = "◀️ Retour"
    NEXT = "Suivant"
    NEXT_ICON = "▶️ Suivant"
    CONFIRM = "Confirmer"
    CONFIRM_ICON = "✅ Confirmer"
    DELETE = "Supprimer"
    DELETE_ICON = "🗑️ Supprimer"
    EDIT = "Modifier"
    EDIT_ICON = "✏️ Modifier"
    ADD = "Ajouter"
    ADD_ICON = "➕ Ajouter"
    REMOVE = "Retirer"
    REMOVE_ICON = "➖ Retirer"
    RESET = "Reinitialiser"
    RESET_ICON = "🔄 Reinitialiser"
    REFRESH = "Actualiser"
    REFRESH_ICON = "🔁 Actualiser"
    EXPORT = "Exporter"
    EXPORT_ICON = "📤 Exporter"
    IMPORT = "Importer"
    IMPORT_ICON = "📥 Importer"
    HELP = "Aide"
    HELP_ICON = "💡 Aide"
    CLOSE = "Fermer"
    CLOSE_ICON = "✖️ Fermer"
    OPEN = "Ouvrir"
    OPEN_ICON = "📂 Ouvrir"
    DETAILS = "Details"
    DETAILS_ICON = "🔍 Details"
    SEARCH = "Rechercher"
    SEARCH_ICON = "🔎 Rechercher"
    APPLY = "Appliquer"
    APPLY_ICON = "✔️ Appliquer"
    PREVIEW = "Apercu"
    PREVIEW_ICON = "👁️ Apercu"


# =============================================================================
# ETATS (statuts visuels)
# =============================================================================

class Status:
    """Libelles d'etats."""

    ENABLED = "Active"
    ENABLED_ICON = "✅ Active"
    DISABLED = "Desactive"
    DISABLED_ICON = "❌ Desactive"
    PENDING = "En attente"
    PENDING_ICON = "⏳ En attente"
    DONE = "Termine"
    DONE_ICON = "✔️ Termine"
    ERROR = "Erreur"
    ERROR_ICON = "⛔ Erreur"
    WARNING = "Attention"
    WARNING_ICON = "⚠️ Attention"
    INFO = "Information"
    INFO_ICON = "ℹ️ Information"
    LOADING = "Chargement"
    LOADING_ICON = "🔄 Chargement..."
    LOCKED = "Verrouille"
    LOCKED_ICON = "🔒 Verrouille"
    UNLOCKED = "Deverrouille"
    UNLOCKED_ICON = "🔓 Deverrouille"


# =============================================================================
# ROLES UTILISATEUR (terminologie metier)
# =============================================================================

class UserRole:
    """Roles utilisateur du bot."""

    OWNER = "Proprietaire du serveur"
    ADMIN = "Administrateur"
    MOD = "Moderateur"
    HELPER = "Helper"
    MEMBER = "Membre"
    NEWCOMER = "Nouveau membre"
    HOST = "Animateur / Staff"
    BOT = "Bot"


# =============================================================================
# MODULES (noms officiels affiches dans les menus)
# =============================================================================

class Module:
    """Noms officiels des modules du bot (affichage)."""

    PROTECTION = "Protection"
    MODERATION = "Moderation"
    IMMUNITY = "Immunites"
    COMMANDS = "Commandes personnalisees"
    CHANNELS = "Configuration des salons"
    TICKETS = "Tickets"
    ADS = "Publicite"
    STATS = "Statistiques"
    CENTER = "Centre d'animation"
    LEVELING = "Niveaux & Economie"
    TEMPVOICE = "Voix temporaires"
    AUTOHELP = "Aide automatique"
    PERMISSIONS = "Permissions"
    BACKUP = "Sauvegarde & Restauration"
    HELP = "Aide & Documentation"
    ENGAGEMENT = "Engagement communautaire"


# =============================================================================
# MESSAGES STANDARDS (errors, success, info)
# =============================================================================

class Message:
    """Messages utilisateur standards."""

    # --- Succes ---
    SAVED = "✅ Configuration enregistree."
    SAVED_DETAIL = "✅ {item} enregistre avec succes."
    DELETED = "🗑️ {item} supprime."
    UPDATED = "✏️ {item} mis a jour."
    APPLIED = "✔️ Modifications appliquees."

    # --- Annulation / Timeout ---
    CANCELLED = "✖️ Action annulee."
    TIMEOUT = "⏰ Delai expire. Relance la commande pour recommencer."

    # --- Permissions ---
    NOT_PERMITTED = "🚫 Vous n'avez pas la permission d'effectuer cette action."
    NOT_OWNER = "🚫 Seul le proprietaire du serveur peut configurer cela."
    NOT_STAFF = "🚫 Cette action est reservee au staff."
    OWNER_ONLY_PANEL = (
        "🚫 Seul l'utilisateur ayant ouvert ce panneau peut l'utiliser."
    )

    # --- Erreurs de saisie ---
    INVALID_INPUT = "⚠️ Saisie invalide. Verifie les valeurs entrees."
    INVALID_CHANNEL = "⚠️ Salon invalide ou inaccessible."
    INVALID_ROLE = "⚠️ Role invalide ou non assignable par le bot."
    INVALID_USER = "⚠️ Utilisateur introuvable."
    NOT_FOUND = "🔍 Element introuvable."

    # --- Confirmations ---
    CONFIRM_DELETE = (
        "⚠️ Es-tu sur de vouloir supprimer {item} ? Cette action est definitive."
    )
    CONFIRM_RESET = (
        "⚠️ Es-tu sur de vouloir reinitialiser {item} ? Toutes les donnees seront perdues."
    )

    # --- Onboarding ---
    WELCOME_NEW = (
        "👋 Bienvenue ! Pour bien demarrer, ouvre l'aide avec **/help**."
    )
    SETUP_INCOMPLETE = (
        "⚠️ Configuration incomplete. Ouvre **/setup** pour finir l'installation."
    )

    # --- Sanctions ---
    NOT_SANCTIONABLE = (
        "🛡️ {user} ne peut pas etre sanctionne (configuration owner)."
    )
    BYPASSED = "🛡️ {user} bypass le systeme {system}."

    # --- Generiques ---
    LOADING = "🔄 Chargement..."
    UNKNOWN_ERROR = (
        "❌ Une erreur inattendue s'est produite. Si le probleme persiste, "
        "contacte un administrateur."
    )


# =============================================================================
# TONE GUIDE (regles de redaction pour cohérence)
# =============================================================================

class Tone:
    """Regles de redaction a respecter dans tout texte UI."""

    # Tutoiement systematique (pas de vouvoiement) sauf messages d'erreur permission
    USE_TU = True
    # Phrases courtes : 1 idee = 1 phrase
    MAX_SENTENCE_WORDS = 20
    # Pas de jargon technique sans explication
    EXPLAIN_TECHNICAL = True
    # Toujours indiquer la prochaine action a faire
    ALWAYS_NEXT_STEP = True


# =============================================================================
# LABELS DE TEMPS (durations, periodes)
# =============================================================================

class Time:
    """Labels temporels."""

    NEVER = "Jamais"
    NOW = "Maintenant"
    JUST_NOW = "A l'instant"
    MINUTES = "minutes"
    HOURS = "heures"
    DAYS = "jours"
    WEEKS = "semaines"
    MONTHS = "mois"
    YEARS = "annees"
    PERMANENT = "Permanent"
    TEMPORARY = "Temporaire"


# =============================================================================
# CHIFFRES & UNITES
# =============================================================================

class Unit:
    """Unites courantes."""

    XP = "XP"
    POINTS = "points"
    LEVEL = "Niveau"
    COINS = "pieces"
    MEMBERS = "membres"
    MESSAGES = "messages"
    CHANNELS = "salons"
    ROLES = "roles"


__all__ = [
    "Action",
    "Status",
    "UserRole",
    "Module",
    "Message",
    "Tone",
    "Time",
    "Unit",
]
