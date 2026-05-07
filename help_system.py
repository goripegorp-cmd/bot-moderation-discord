"""
help_system.py - Systeme d'aide multi-niveaux (Phase 0 du redesign 2026).

Trois publics cibles :
- Newcomer : nouveau sur le serveur, besoin d'orientation simple et progressive
- Oldcomer : utilisateur regulier, veut aller vite (raccourcis, fonctions avancees)
- Host    : staff/owner, manuel complet (commandes admin, troubleshooting, runbooks)

API:
    - HelpEntry        : entree d'aide (titre, description, audience, exemple)
    - HelpRegistry     : registre central des entrees
    - register_help()  : enregistre une entree
    - help_registry    : instance singleton
    - get_for_audience(audience) : filtre par public

Chaque module du bot enregistre ses propres entrees au demarrage. La commande
/help interroge ce registre et adapte le rendu selon qui pose la question.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# =============================================================================
# AUDIENCES
# =============================================================================

class Audience(Enum):
    """Publics cibles du systeme d'aide."""

    NEWCOMER = "newcomer"   # Nouveau sur le serveur
    OLDCOMER = "oldcomer"   # Utilisateur regulier
    HOST = "host"           # Staff/owner
    ALL = "all"             # Tous publics


AUDIENCE_LABELS: dict[Audience, str] = {
    Audience.NEWCOMER: "🌱 Nouveau membre",
    Audience.OLDCOMER: "💬 Membre regulier",
    Audience.HOST: "🛠️ Staff & Owner",
    Audience.ALL: "Tous",
}


# =============================================================================
# MODELE
# =============================================================================

@dataclass
class HelpEntry:
    """Entree d'aide unique."""

    key: str                                  # identifiant unique
    title: str                                # titre court affichable
    description: str                          # corps de texte (markdown OK)
    audiences: list[Audience]                 # publics cibles
    category: str = "general"                 # categorie pour le tri
    example: Optional[str] = None             # exemple concret (optionnel)
    related: list[str] = field(default_factory=list)  # cles d'entrees liees
    icon: str = "📖"                          # emoji prefixe
    order: int = 100                          # ordre de tri (plus petit = plus haut)


# =============================================================================
# REGISTRE
# =============================================================================

class HelpRegistry:
    """Registre central des entrees d'aide."""

    def __init__(self):
        self._entries: dict[str, HelpEntry] = {}

    def register(self, entry: HelpEntry) -> None:
        """Enregistre une entree (remplace si la cle existe)."""
        self._entries[entry.key] = entry

    def get(self, key: str) -> Optional[HelpEntry]:
        return self._entries.get(key)

    def all(self) -> list[HelpEntry]:
        return list(self._entries.values())

    def for_audience(self, audience: Audience) -> list[HelpEntry]:
        """Renvoie les entrees pour un public donne (triees par ordre puis titre)."""
        entries = [
            e for e in self._entries.values()
            if Audience.ALL in e.audiences or audience in e.audiences
        ]
        return sorted(entries, key=lambda e: (e.order, e.title))

    def by_category(self, category: str) -> list[HelpEntry]:
        return sorted(
            (e for e in self._entries.values() if e.category == category),
            key=lambda e: (e.order, e.title),
        )

    def categories(self) -> list[str]:
        cats = sorted({e.category for e in self._entries.values()})
        return cats

    def search(self, query: str) -> list[HelpEntry]:
        """Recherche simple (substring case-insensitive sur titre et description)."""
        q = query.lower().strip()
        if not q:
            return []
        return [
            e for e in self._entries.values()
            if q in e.title.lower() or q in e.description.lower()
        ]


help_registry = HelpRegistry()


def register_help(**kwargs) -> None:
    """Helper pour enregistrer une entree avec syntaxe kwarg."""
    help_registry.register(HelpEntry(**kwargs))


# =============================================================================
# ENTREES PRE-DEFINIES (foundationals)
# =============================================================================
# Les modules enregistrent leurs propres entrees lors du chargement. On pose
# ici les bases que tout serveur aura par defaut.

# --- Newcomer ---
register_help(
    key="welcome",
    title="Bienvenue sur le serveur",
    description=(
        "Voici les bases pour bien demarrer :\n"
        "- Lis les **regles** dans le salon dedie\n"
        "- Presente-toi dans **#presentations**\n"
        "- Choisis tes roles dans **#choix-roles**\n"
        "- Pose toutes tes questions dans **#aide**\n\n"
        "Tu peux toujours rouvrir ce guide avec `/help`."
    ),
    audiences=[Audience.NEWCOMER],
    category="onboarding",
    icon="👋",
    order=1,
)

register_help(
    key="commands_basic",
    title="Commandes de base",
    description=(
        "Les commandes utiles au quotidien :\n"
        "- `/help` - affiche cette aide\n"
        "- `/level` - voir ton niveau et tes XP\n"
        "- `/ticket` - ouvrir un ticket si tu as un souci\n"
        "- `/afk` - signaler que tu t'absentes\n"
        "- `/suggest` - proposer une idee au staff"
    ),
    audiences=[Audience.NEWCOMER, Audience.OLDCOMER],
    category="commands",
    icon="⌨️",
    order=10,
    example="/level",
)

register_help(
    key="how_to_progress",
    title="Comment progresser ?",
    description=(
        "Tu gagnes des **XP** en participant : chaque message rapporte un peu, "
        "et passer du temps en vocal aussi.\n\n"
        "Ton niveau augmente avec les XP. Atteindre certains niveaux debloque "
        "des **roles**, des **emojis** speciaux, ou des fonctionnalites."
    ),
    audiences=[Audience.NEWCOMER, Audience.OLDCOMER],
    category="leveling",
    icon="📈",
    order=20,
)

# --- Oldcomer ---
register_help(
    key="advanced_shortcuts",
    title="Raccourcis avances",
    description=(
        "Quand tu connais le bot :\n"
        "- `/shop` - boutique d'objets et de cosmetiques\n"
        "- `/leaderboard` - classement du serveur\n"
        "- `/trade` - echanger avec un autre membre\n"
        "- `/tempvoice` - creer un salon vocal temporaire personnel"
    ),
    audiences=[Audience.OLDCOMER],
    category="commands",
    icon="⚡",
    order=30,
)

# --- Host ---
register_help(
    key="moderation_intro",
    title="Outils de moderation",
    description=(
        "Le bot fournit ces outils staff :\n"
        "- `/warn` - avertir un membre (cumule un strike)\n"
        "- `/mute` `/tempmute` - reduire au silence (timeout Discord)\n"
        "- `/kick` `/ban` - sanctions lourdes\n"
        "- `/purge <nb>` - supprimer N messages\n"
        "- Tableau de bord complet : `/config moderation`"
    ),
    audiences=[Audience.HOST],
    category="moderation",
    icon="🛡️",
    order=10,
)

register_help(
    key="permissions_intro",
    title="Configurer les permissions",
    description=(
        "Tu peux definir qui a acces a quoi de facon **granulaire** :\n"
        "- Par commande : autoriser/refuser un role specifique\n"
        "- Par categorie : modifier toute une famille en un clic\n"
        "- Roles non sanctionnables : immuniser certains roles aux sanctions\n"
        "- Bypass : exempter un role d'un systeme (anti-raid, automod...)\n\n"
        "Ouvre la config avec `/config permissions`."
    ),
    audiences=[Audience.HOST],
    category="configuration",
    icon="🔐",
    order=20,
    example="/config permissions",
)

register_help(
    key="backup_intro",
    title="Sauvegarde & restauration",
    description=(
        "Avant tout changement majeur, fais une sauvegarde :\n"
        "- `/backup create` - exporte la config en JSON\n"
        "- `/backup list` - voir les sauvegardes\n"
        "- `/backup restore <id>` - restaure une sauvegarde\n\n"
        "Les sauvegardes sont stockees pendant 30 jours."
    ),
    audiences=[Audience.HOST],
    category="configuration",
    icon="💾",
    order=30,
)


# =============================================================================
# RENDU UI (helpers pour Components V2)
# =============================================================================

def format_entry_short(entry: HelpEntry) -> str:
    """Format compact pour une liste (icone + titre)."""
    return f"{entry.icon} **{entry.title}**"


def format_entry_full(entry: HelpEntry) -> str:
    """Format complet pour affichage individuel."""
    parts = [f"{entry.icon} **{entry.title}**", "", entry.description]
    if entry.example:
        parts.append("")
        parts.append(f"**Exemple :** `{entry.example}`")
    if entry.related:
        parts.append("")
        parts.append("**Voir aussi :** " + ", ".join(f"`{k}`" for k in entry.related))
    return "\n".join(parts)


__all__ = [
    "Audience",
    "AUDIENCE_LABELS",
    "HelpEntry",
    "HelpRegistry",
    "help_registry",
    "register_help",
    "format_entry_short",
    "format_entry_full",
]
