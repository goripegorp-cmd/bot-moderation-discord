"""
Phase 57 — LORE VIVANT
─────────────────────────────────────────────────────────
Transforme le lore Phase 49 (chapitres + NPCs + missions) en un récit
VRAIMENT vivant où :

• Les choix narratifs collectifs orientent le chapitre suivant
• Les NPCs se citent entre eux (relations entre personnages)
• Les members peuvent choisir une CLASSE RP (5 classes)
• Les conséquences importantes restent dans la mémoire du serveur

Toutes les données sont pures (pas de side-effect).
"""
from __future__ import annotations
import random
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  NARRATIVE CHOICES — Décisions qui orientent le chapitre suivant
# ═══════════════════════════════════════════════════════════════════════════════
#
# Format : un choix se déclenche après la victoire d'un World Boss (50% proba),
# ou manuellement par owner via /narrative_force. Vote 48h. Le résultat est
# stocké et le chapitre suivant adapte son tone.

NARRATIVE_CHOICES = [
    {
        "id": "mage_prisoner",
        "chapter_link": "chapter_02_mage",
        "trigger_after": "world_boss_victory",
        "title": "🔮 Le marché du Mage prisonnier",
        "context": (
            "Le mage que vous avez capturé propose un marché : il libère un de "
            "ses revenants pour vous aider contre les colosses, en échange de "
            "sa liberté. Que décide la guilde ?"
        ),
        "options": [
            {
                "id": "accept_pact",
                "label": "🤝 Accepter le pacte",
                "consequence": (
                    "_Le revenant rejoint la guilde. Le mage disparaît dans la nuit. "
                    "Les anciens vous regardent autrement maintenant._"
                ),
            },
            {
                "id": "refuse_execute",
                "label": "⚔️ Refuser et l'exécuter",
                "consequence": (
                    "_Le mage tombe. Ses revenants sont libérés mais désordonnés. "
                    "La guilde a tenu sa promesse à l'ancienne loi._"
                ),
            },
        ],
    },
    {
        "id": "betrayer_fate",
        "chapter_link": "chapter_03_traitre",
        "trigger_after": "world_boss_victory",
        "title": "🗡️ Le sort du traître démasqué",
        "context": (
            "Vous avez identifié le traître. C'est un membre respecté de la guilde "
            "depuis longtemps. Que faire de lui ?"
        ),
        "options": [
            {
                "id": "exile",
                "label": "🌫️ L'exiler",
                "consequence": (
                    "_Banni à jamais des terres de la guilde. Il jure vengeance "
                    "depuis l'exil. On entend parfois sa voix dans le vent._"
                ),
            },
            {
                "id": "redeem",
                "label": "📜 Le racheter par épreuve",
                "consequence": (
                    "_Il accepte une quête impossible pour se racheter. Personne ne "
                    "sait s'il survivra. Sa loyauté reste à prouver._"
                ),
            },
        ],
    },
    {
        "id": "revenant_command",
        "chapter_link": "chapter_04_resurrection",
        "trigger_after": "world_boss_victory",
        "title": "💀 Maîtriser les revenants",
        "context": (
            "Les revenants se relèvent partout. La guilde peut tenter de les "
            "asservir pour combattre à ses côtés — ou les détruire un par un."
        ),
        "options": [
            {
                "id": "command_them",
                "label": "👑 Les commander",
                "consequence": (
                    "_Vous formez une armée morte. Puissante mais maudite. Le sang "
                    "des ennemis qu'elle tue rejaillit sur vos mains._"
                ),
            },
            {
                "id": "destroy_them",
                "label": "🔥 Tous les détruire",
                "consequence": (
                    "_Une à une, les âmes sont libérées. Le travail est long. "
                    "Mais la guilde reste pure._"
                ),
            },
        ],
    },
    {
        "id": "shadow_lord_offer",
        "chapter_link": "chapter_05_seigneur",
        "trigger_after": "world_boss_victory",
        "title": "👑 L'offre du Seigneur des Ombres",
        "context": (
            "Avant le combat final, le Seigneur des Ombres propose : il quittera "
            "ces terres si la guilde lui livre **un seul** de ses membres en "
            "sacrifice. Sinon, c'est l'extermination totale."
        ),
        "options": [
            {
                "id": "accept_sacrifice",
                "label": "🩸 Accepter le sacrifice",
                "consequence": (
                    "_Un nom est tiré au sort. La guilde survit, mais brisée. Personne "
                    "ne mentionne plus le nom de celui qui est tombé. Sa chaise reste vide._"
                ),
            },
            {
                "id": "refuse_fight",
                "label": "⚔️ Refuser et combattre",
                "consequence": (
                    "_Le combat final est lancé. La victoire ou l'anéantissement. "
                    "Aucun retour en arrière possible._"
                ),
            },
        ],
    },
    {
        "id": "next_cycle",
        "chapter_link": "chapter_06_renaissance",
        "trigger_after": "world_boss_victory",
        "title": "🌅 Le cycle recommence",
        "context": (
            "La paix est revenue. Mais des signes anciens apparaissent. La guilde "
            "peut soit s'endormir et attendre, soit chercher activement la prochaine menace."
        ),
        "options": [
            {
                "id": "rest_vigilant",
                "label": "🛌 Reposer en gardant l'œil ouvert",
                "consequence": (
                    "_La guilde se repose. Mais quelques sentinelles veillent. "
                    "Si quelque chose arrive, vous serez prévenus._"
                ),
            },
            {
                "id": "hunt_actively",
                "label": "🏹 Chercher activement",
                "consequence": (
                    "_Des expéditions sont lancées. La guilde refuse l'oubli. "
                    "Quelque chose va être trouvé, peut-être plus tôt que prévu._"
                ),
            },
        ],
    },
    {
        "id": "founding_member",
        "chapter_link": None,  # Indépendant de chapitre — peut se déclencher anytime
        "trigger_after": "manual",
        "title": "🏛️ Le destin du Membre Fondateur",
        "context": (
            "Un ancien parchemin évoque un membre fondateur disparu il y a longtemps. "
            "Sa réapparition transformerait l'histoire. Faut-il le chercher ?"
        ),
        "options": [
            {
                "id": "search_him",
                "label": "🔍 Lancer la quête",
                "consequence": (
                    "_La quête commence. Elle prendra plusieurs missions. Si elle "
                    "réussit, l'histoire change drastiquement._"
                ),
            },
            {
                "id": "let_legend",
                "label": "📖 Le laisser à la légende",
                "consequence": (
                    "_Certaines choses doivent rester mystérieuses. Le membre reste "
                    "dans les chansons et c'est très bien comme ça._"
                ),
            },
        ],
    },
]


def get_narrative_choice(choice_id: str) -> Optional[dict]:
    for c in NARRATIVE_CHOICES:
        if c["id"] == choice_id:
            return c
    return None


def pick_narrative_choice_for_chapter(chapter_id: Optional[str]) -> Optional[dict]:
    """Pick une narrative choice liée au chapitre actuel."""
    if not chapter_id:
        return None
    candidates = [c for c in NARRATIVE_CHOICES if c.get("chapter_link") == chapter_id]
    if not candidates:
        return None
    return random.choice(candidates)


# ═══════════════════════════════════════════════════════════════════════════════
#  CLASSES RP — 5 classes que les members peuvent adopter
# ═══════════════════════════════════════════════════════════════════════════════

PLAYER_CLASSES = [
    {
        "id": "warrior",
        "emoji": "⚔️",
        "name": "Guerrier",
        "title_long": "Guerrier de la Guilde",
        "description": (
            "Frappe fort, encaisse fort. Charge en première ligne pendant les "
            "events. Inspire respect et loyauté."
        ),
        "passive": "Boss raid : +5% dégâts.",
        "color": 0xE74C3C,
    },
    {
        "id": "mage",
        "emoji": "🔮",
        "name": "Mage",
        "title_long": "Mage des Arcanes",
        "description": (
            "Manipule les mystères du serveur. Réussit mieux aux énigmes, voit "
            "les patterns que les autres manquent."
        ),
        "passive": "Daily Riddle : +50% reward si premier.",
        "color": 0x9B59B6,
    },
    {
        "id": "rogue",
        "emoji": "🗡️",
        "name": "Voleur",
        "title_long": "Voleur de l'Ombre",
        "description": (
            "Rapide, opportuniste. Saisit les chances avant les autres. "
            "Excellent en flash treasure et events soudains."
        ),
        "passive": "Flash Treasure : +20% reward si premier.",
        "color": 0x2C2C2C,
    },
    {
        "id": "healer",
        "emoji": "✨",
        "name": "Soigneur",
        "title_long": "Soigneur Béni",
        "description": (
            "Vit pour le collectif. Bonus de coins quand son alliance ou sa "
            "faction gagne. Apprécié de tous."
        ),
        "passive": "Bonus mentor : +50% si tu es mentor ou apprenti.",
        "color": 0x57F287,
    },
    {
        "id": "ranger",
        "emoji": "🏹",
        "name": "Rôdeur",
        "title_long": "Rôdeur des Frontières",
        "description": (
            "Indépendant, perfectionniste. Excellent en speedrun et défis solo. "
            "N'aime pas la dépendance."
        ),
        "passive": "Speedrun approved : +30% coins (au lieu de 500 → 650).",
        "color": 0x16A085,
    },
]


def get_player_class(class_id: str) -> Optional[dict]:
    for c in PLAYER_CLASSES:
        if c["id"] == class_id:
            return c
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  CROSSOVER LINES — Les NPCs se citent entre eux
# ═══════════════════════════════════════════════════════════════════════════════
#
# Quand un NPC X est posté ET qu'un autre NPC Y a parlé dans les dernières 24h,
# il y a une chance que X cite Y dans sa ligne. Crée l'illusion de personnages
# qui interagissent.

NPC_CROSSOVER_LINES = {
    # Borek → Lyra
    ("forgeron", "sage"): [
        "_Lyra m'a montré un parchemin ce matin. Je n'ai rien compris. Mais ça parlait de fer ancien._",
        "_J'ai vu Lyra hier soir. Elle ne dormait pas. Elle dort jamais quand quelque chose se prépare._",
        "_Lyra dit que les anciens textes annoncent ce qui arrive. Moi je préfère préparer les armes._",
    ],
    # Borek → Tarik
    ("forgeron", "gardien"): [
        "_Tarik m'a demandé trois épées supplémentaires hier. Il sait quelque chose qu'il n'a pas dit._",
        "_J'ai croisé Tarik aux remparts cette nuit. Il scrutait l'horizon. Il fait toujours ça avant un danger._",
        "_Tarik est le gars le plus loyal que j'aie connu. Si lui s'inquiète, je m'inquiète._",
    ],
    # Lyra → Borek
    ("sage", "forgeron"): [
        "_Borek prépare ses armes. C'est son langage à lui pour dire qu'il sent quelque chose. Écoutez son silence._",
        "_J'ai vu Borek lire un livre. Borek. Lire. Imaginez à quel point c'est sérieux._",
        "_Borek m'a apporté un fer étrange ce matin. Il pensait que je saurais le lire. Je sais._",
    ],
    # Lyra → Tarik
    ("sage", "gardien"): [
        "_Tarik a doublé les gardes cette nuit. Il a senti ce que je sens depuis trois jours._",
        "_J'ai partagé un thé avec Tarik. Sa loyauté est sa plus grande force. Et sa plus grande limite._",
        "_Les parchemins disent que les sentinelles voient avant les sages. Tarik le prouve._",
    ],
    # Tarik → Borek
    ("gardien", "forgeron"): [
        "_Borek a fini les armes que je lui avais demandées. Comme toujours, à l'heure. Bon homme._",
        "_J'ai vu Borek tester une lame trois fois avant de la livrer. C'est pour ça qu'on est encore vivants._",
        "_Borek râle souvent. Mais quand il faut combattre, il est le premier debout._",
    ],
    # Tarik → Lyra
    ("gardien", "sage"): [
        "_Lyra m'a prévenu. Elle sait toujours avant nous tous. C'est rassurant et terrifiant._",
        "_J'ai vu Lyra fixer le ciel cette nuit. Elle ne fixe le ciel que quand quelque chose s'y prépare._",
        "_Lyra dit qu'elle ne dort plus. Moi non plus. La guilde est en alerte._",
    ],
}


def pick_crossover_line(speaker_id: str, recent_speakers: list) -> Optional[str]:
    """Si possible, pick une ligne où speaker_id cite un des recent_speakers."""
    candidates = []
    for other in recent_speakers:
        if other == speaker_id:
            continue
        lines = NPC_CROSSOVER_LINES.get((speaker_id, other))
        if lines:
            candidates.extend(lines)
    if not candidates:
        return None
    return random.choice(candidates)


# ═══════════════════════════════════════════════════════════════════════════════
#  LORE MEMORIES — Événements importants que le serveur retient
# ═══════════════════════════════════════════════════════════════════════════════
#
# Types :
#  - "boss_defeat" : la guilde a échoué un boss
#  - "narrative_choice_result" : résultat d'un vote narratif
#  - "first_kill" : premier exploit individuel
#  - "season_ended" : fin d'une saison avec un titre
#
# Ces mémoires sont citées par les NPCs périodiquement pour donner du poids
# aux conséquences.

MEMORY_FLAVOR_LINES = {
    "boss_defeat": [
        "_Borek se tait en regardant la cicatrice sur son bras. 'On a perdu {detail} lors de ce combat. Je ne l'oublie pas.'_",
        "_Lyra murmure : 'Le {detail} reste un cauchemar pour la guilde. On n'a jamais récupéré ce qu'on a perdu cette nuit-là.'_",
        "_Tarik dit, avec une pause : 'Je porte encore le poids de {detail}. Ça ne disparaît pas. Mais on continue.'_",
    ],
    "narrative_choice_result": [
        "_Lyra sourit : 'On se souvient de quand vous avez choisi {detail}. C'était la bonne décision.'_",
        "_Borek hoche la tête : 'Le jour où vous avez décidé {detail}, j'ai compris que cette guilde était différente.'_",
        "_Tarik dit lentement : 'L'histoire retiendra {detail}. Pour le meilleur ou le pire.'_",
    ],
    "first_kill": [
        "_Borek frappe son enclume : 'Le premier à abattre {detail} restera dans les livres. C'est ça, faire l'histoire.'_",
        "_Lyra écrit dans son grimoire : 'Le nom de celui qui a fait tomber {detail} en premier — gravé pour toujours.'_",
    ],
    "season_ended": [
        "_Lyra ferme un livre : 'La saison de {detail} est terminée. Une nouvelle commence. L'histoire ne s'arrête pas.'_",
    ],
}


def pick_memory_flavor(memory_kind: str, detail: str) -> Optional[str]:
    lines = MEMORY_FLAVOR_LINES.get(memory_kind, [])
    if not lines:
        return None
    return random.choice(lines).replace("{detail}", detail)


__all__ = [
    "NARRATIVE_CHOICES", "PLAYER_CLASSES", "NPC_CROSSOVER_LINES",
    "MEMORY_FLAVOR_LINES",
    "get_narrative_choice", "pick_narrative_choice_for_chapter",
    "get_player_class", "pick_crossover_line", "pick_memory_flavor",
]
