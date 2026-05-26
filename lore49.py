"""
Phase 49 — LORE ÉVOLUTIF + NPCs + MISSIONS SCÉNARISÉES
─────────────────────────────────────────────────────────
Transforme le serveur d'un Discord fonctionnel en un monde avec une âme :

• LORE_CHAPTERS : récit narratif découpé en arcs. Un chapitre = un thème de saison.
  Le chapitre actif change au début de chaque saison (lié à engagement47.SEASONS).

• NPCS : 3 personnages persistants (Le Forgeron, La Sage, Le Gardien) avec leur
  propre voix, leurs propres avatars. Ils commentent les events, accueillent les
  nouveaux, lancent des phrases d'ambiance.

• MISSION_TEMPLATES : missions mensuelles en 5 étapes scénarisées qui font
  participer la communauté. Liées à un chapitre du lore quand pertinent.

Toutes les données sont des dataclasses pures : aucun side-effect, on consomme
depuis bot.py via les helpers en bas du module.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  CHAPITRES DE LORE (un par arc narratif)
# ═══════════════════════════════════════════════════════════════════════════════

LORE_CHAPTERS = [
    {
        "id": "chapter_01_eveil",
        "order": 1,
        "title": "L'Éveil du Colosse",
        "subtitle": "Quelque chose s'est réveillé sous les terres anciennes.",
        "intro": (
            "Les anciens parchemins parlaient d'une menace endormie depuis mille ans.\n"
            "Ce qu'ils ne disaient pas, c'est qu'elle commencerait à se réveiller "
            "*maintenant*, dans nos terres, sous nos pieds."
        ),
        "world_boss_flavor": (
            "Le sol tremble. La bête remonte des profondeurs. Si elle atteint la "
            "surface, plus rien ne pourra l'arrêter."
        ),
        "if_victorious": (
            "La bête est tombée. Mais les anciens parchemins parlaient aussi de **trois** "
            "colosses. Si l'un dort encore, les autres se réveillent aussi…"
        ),
        "if_defeated": (
            "La bête a survécu. Elle est plus forte maintenant. Et les anciens disent "
            "qu'il est plus difficile de la rendormir une seconde fois…"
        ),
        "color": 0x8B4513,
        "emoji": "🗿",
    },
    {
        "id": "chapter_02_mage",
        "order": 2,
        "title": "Le Mage Disparu",
        "subtitle": "Quelqu'un contrôlait la bête. Et il a disparu.",
        "intro": (
            "Sur le corps du colosse, une rune. Elle ne ressemble à aucune autre — "
            "ce n'est pas du langage divin, c'est de la **magie humaine**.\n"
            "Quelqu'un a éveillé la bête. Quelqu'un de chez nous."
        ),
        "world_boss_flavor": (
            "Le mage envoie une créature plus puissante pour couvrir sa fuite. "
            "Si vous le perdez maintenant, il disparaîtra pour toujours."
        ),
        "if_victorious": (
            "La créature tombe — et avec elle, un parchemin déchiré. Une carte. "
            "Le mage a un repère. Quelque part dans les terres du Nord."
        ),
        "if_defeated": (
            "Le mage s'échappe pendant le combat. Sa trace est perdue, mais la "
            "rumeur dit qu'il prépare quelque chose de bien plus terrible…"
        ),
        "color": 0x4B0082,
        "emoji": "🔮",
    },
    {
        "id": "chapter_03_traitre",
        "order": 3,
        "title": "Le Traître",
        "subtitle": "Le mage n'agissait pas seul.",
        "intro": (
            "Le repère du mage est trouvé — vide. Mais sur le mur, des noms. "
            "Des noms de gens d'ici. Des **alliés**. Ils ont tous joué un rôle.\n"
            "La trahison vient de l'intérieur."
        ),
        "world_boss_flavor": (
            "L'un des traîtres invoque une créature de l'ombre. Il faut la vaincre — "
            "et identifier qui parmi nous l'a appelée."
        ),
        "if_victorious": (
            "Un nom tombe. Un seul. Mais c'est suffisant pour remonter la chaîne. "
            "Les autres traîtres sont en fuite, mais ils ne le resteront pas longtemps."
        ),
        "if_defeated": (
            "Le traître se cache dans nos rangs. Personne ne sait qui c'est. "
            "La méfiance grandit dans la guilde…"
        ),
        "color": 0x2C2C2C,
        "emoji": "🗡️",
    },
    {
        "id": "chapter_04_resurrection",
        "order": 4,
        "title": "La Résurrection",
        "subtitle": "Ce qui tombe peut se relever, plus puissant.",
        "intro": (
            "Les colosses que vous avez vaincus se relèvent. Pas comme avant — comme "
            "des **revenants**, contrôlés par une force que personne ne comprend.\n"
            "Quelqu'un récolte vos victoires. Quelqu'un veut votre échec."
        ),
        "world_boss_flavor": (
            "Le revenant le plus ancien — celui que vous avez vaincu en premier — "
            "revient. Il connaît vos tactiques. Il a appris."
        ),
        "if_victorious": (
            "Le revenant retombe. Mais cette fois, il chuchote un nom avant de "
            "disparaître. Un nom que tout le monde connaît. Un nom de la guilde."
        ),
        "if_defeated": (
            "Le revenant gagne. Les autres morts commencent à se relever. La région "
            "n'est plus sûre — il faut s'organiser, vite."
        ),
        "color": 0x800020,
        "emoji": "💀",
    },
    {
        "id": "chapter_05_seigneur",
        "order": 5,
        "title": "Le Seigneur des Ombres",
        "subtitle": "Le vrai ennemi se révèle enfin.",
        "intro": (
            "Tout — les colosses, le mage, les traîtres, les revenants — n'était "
            "qu'une distraction. Le **vrai** maître se révèle.\n"
            "Et il n'est ni humain, ni divin. Il est ce qui existait **avant**."
        ),
        "world_boss_flavor": (
            "Le Seigneur des Ombres descend en personne. Il n'attaque pas pour "
            "tuer — il attaque pour **briser la guilde**, pour qu'elle se dissolve."
        ),
        "if_victorious": (
            "L'impossible est accompli. Le Seigneur tombe. Une nouvelle ère commence — "
            "et la guilde entre dans la légende. Une statue est érigée. Vos noms y sont gravés."
        ),
        "if_defeated": (
            "Le Seigneur ne tue personne — il efface tout. La guilde recommence à "
            "zéro, mais le souvenir reste. Et le souvenir est un acte de rébellion."
        ),
        "color": 0x000000,
        "emoji": "👑",
    },
    {
        "id": "chapter_06_renaissance",
        "order": 6,
        "title": "Renaissance",
        "subtitle": "Après la fin, le commencement.",
        "intro": (
            "La paix est revenue. Les saisons passent. Les nouveaux membres entendent "
            "des histoires sur ce que vous avez fait — et certains n'y croient pas.\n"
            "Mais quelque chose bouge à nouveau. Le cycle recommence…"
        ),
        "world_boss_flavor": (
            "Une nouvelle bête. Plus petite. Mais ce sera son éveil qui décidera "
            "si l'histoire se répète ou si elle change."
        ),
        "if_victorious": (
            "La guilde apprend de ses erreurs. Le cycle s'arrête ici. "
            "Une ère vraiment nouvelle commence."
        ),
        "if_defeated": (
            "Le cycle continue. Mais maintenant, vous savez ce qui arrive ensuite. "
            "Vous serez prêts."
        ),
        "color": 0xFFD700,
        "emoji": "🌅",
    },
]


def get_chapter_by_id(chapter_id: str) -> Optional[dict]:
    """Retourne un chapitre par son ID, None si inconnu."""
    for c in LORE_CHAPTERS:
        if c["id"] == chapter_id:
            return c
    return None


def get_chapter_by_order(order: int) -> Optional[dict]:
    """Retourne le chapitre dont l'ordre numérique correspond."""
    for c in LORE_CHAPTERS:
        if c["order"] == order:
            return c
    return None


def get_next_chapter(current_order: int) -> Optional[dict]:
    """Retourne le chapitre suivant. None si on est au dernier (cycle complet)."""
    return get_chapter_by_order(current_order + 1)


def get_first_chapter() -> dict:
    """Premier chapitre — point de départ pour les nouveaux serveurs."""
    return LORE_CHAPTERS[0]


# ═══════════════════════════════════════════════════════════════════════════════
#  NPCs (3 personnages persistants avec voix propre)
# ═══════════════════════════════════════════════════════════════════════════════

NPCS = {
    "forgeron": {
        "id": "forgeron",
        "name": "Borek le Forgeron",
        "title": "Maître Forgeron de la Guilde",
        "emoji": "⚒️",
        "color": 0xC0392B,
        "personality": "Bourru, direct, parle peu mais ses mots comptent. Ancien combattant.",
        "footer": "Borek le Forgeron · Guilde des Anciens",
    },
    "sage": {
        "id": "sage",
        "name": "Lyra la Sage",
        "title": "Gardienne des Parchemins",
        "emoji": "📜",
        "color": 0x9B59B6,
        "personality": "Énigmatique, parle par métaphores. Connait le lore mieux que personne.",
        "footer": "Lyra la Sage · Gardienne des Parchemins",
    },
    "gardien": {
        "id": "gardien",
        "name": "Tarik le Gardien",
        "title": "Sentinelle des Murs",
        "emoji": "🛡️",
        "color": 0x16A085,
        "personality": "Loyal, protecteur, accueille chaleureusement les nouveaux.",
        "footer": "Tarik le Gardien · Sentinelle des Murs",
    },
}


def get_npc(npc_id: str) -> Optional[dict]:
    return NPCS.get(npc_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  RÉPLIQUES DES NPCs (par contexte)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Format : NPC_LINES[npc_id][context] = liste de répliques (pickées au random).
# Contextes pris en charge :
#   - 'idle'                : phrases d'ambiance random pendant la journée
#   - 'world_boss_pre'      : annonce d'arrivée du world boss
#   - 'world_boss_victory'  : après une victoire collective
#   - 'world_boss_defeat'   : après une défaite collective
#   - 'new_member'          : accueillir un nouveau membre
#   - 'morning'             : le matin (9h-11h)
#   - 'evening'             : le soir (20h-23h)
#   - 'silence'             : si le serveur est calme depuis longtemps
# ═══════════════════════════════════════════════════════════════════════════════

NPC_LINES = {
    "forgeron": {
        "idle": [
            "*pose son marteau* — Vous savez pourquoi je forge des armes même quand il n'y a plus de guerre ? Parce qu'il y en aura toujours une.",
            "L'acier ne ment pas. Frappez-le bien, il vous protège. Frappez-le mal, il vous tue.",
            "Quand j'étais jeune, je voulais des épées qui brillent. Aujourd'hui, je veux des épées qui durent.",
            "Une bonne lame, c'est trois choses : l'acier, le forgeron, et la main qui la tient. Les deux premières, je m'en occupe.",
        ],
        "world_boss_pre": [
            "*ferme la forge* — Sortez vos armes. Aujourd'hui, je ne forge plus, je combats.",
            "J'ai préparé assez de lames pour tout le monde. Servez-vous. Et ramenez-les entières si possible.",
            "Ce qui arrive aujourd'hui, je l'ai senti venir hier. Le sol vibrait différemment.",
        ],
        "world_boss_victory": [
            "*essuie son marteau* — Bien. Maintenant, retournez chez vous. La forge reste ouverte si vous avez besoin de réparer.",
            "Vous avez fait votre travail. Moi je vais faire le mien — fondre les morceaux de la bête pour en faire des trophées.",
            "C'est ça, une vraie guilde. Pas des paroles. Des actes.",
        ],
        "world_boss_defeat": [
            "*recouvre son marteau* — Reposez-vous. Demain, on recommence. Et cette fois, on gagne.",
            "Je vais reforger des armes plus solides. Vous, vous allez vous entraîner. On a tous notre rôle.",
            "Perdre n'est pas une honte. Abandonner, oui.",
        ],
        "morning": [
            "*allume la forge* — Bonjour. La journée commence. Quelque chose me dit qu'elle sera longue.",
            "Le feu est prêt. Si vous avez besoin de réparer quelque chose, c'est maintenant.",
        ],
        "evening": [
            "*pose ses outils* — La nuit tombe. La forge ferme. Mais l'acier, lui, ne dort jamais.",
            "Si vous patrouillez ce soir, prenez une bonne arme. Et restez vigilants.",
        ],
        "silence": [
            "*regarde par la fenêtre* — Trop calme. Je n'aime pas ça.",
            "La forge est froide ce soir. Personne ne vient. Quelque chose ne va pas.",
        ],
        "new_member": [
            "*lève les yeux de l'enclume* — Un nouveau. Bienvenue. Si tu as besoin d'une arme, viens me voir. Si tu as besoin d'un conseil… cherche Lyra.",
            "*hoche la tête* — Tu es nouveau ici. Première règle : reste près de la guilde. Deuxième règle : oublie pas la première.",
        ],
    },
    "sage": {
        "idle": [
            "*tourne une page* — Les anciens disaient que tout ce qui arrive a déjà été écrit. Je commence à les croire.",
            "Lire les parchemins, c'est comme lire l'avenir — sauf qu'on lit le passé qui se répète.",
            "Une vérité chuchotée vaut mieux qu'un mensonge crié. Souvenez-vous de ça.",
            "*ferme un livre* — Chaque guilde a son histoire. La vôtre commence seulement à s'écrire.",
        ],
        "world_boss_pre": [
            "*pose son parchemin* — Il était écrit. Il devait arriver. Maintenant, c'est à vous d'écrire la suite.",
            "Le monde respire. Et quand il respire trop fort, des choses anciennes se réveillent.",
            "Les signes étaient là. Je les ai lus la semaine dernière. Personne ne m'a écoutée.",
        ],
        "world_boss_victory": [
            "*sourit doucement* — Vous l'avez vaincu. Mais avez-vous remarqué ce qu'il a chuchoté avant de tomber ?",
            "C'est rare qu'une bataille se gagne. Plus rare encore qu'elle change quelque chose. Aujourd'hui était les deux.",
            "*écrit dans son grimoire* — J'ajoute votre victoire aux annales. Vos noms vivront plus longtemps que vos os.",
        ],
        "world_boss_defeat": [
            "*hoche la tête lentement* — La défaite est aussi une leçon. Plus longue à apprendre. Plus profonde.",
            "Les parchemins disent que les premières victoires sont fragiles. Les vraies victoires viennent après les défaites.",
            "*regarde au loin* — La bête reviendra. Plus forte. Vous reviendrez aussi. Plus sages.",
        ],
        "morning": [
            "*ouvre un parchemin* — Bonjour. La journée commence. Et chaque journée commence par une question.",
            "Le matin, c'est le bon moment pour relire d'anciennes histoires. Elles ressemblent à celle qu'on vit.",
        ],
        "evening": [
            "*ferme un grimoire* — La nuit est le moment des secrets. Et les secrets se chuchotent ici, autour du feu.",
            "Si vous voulez méditer sur le lore de la guilde, c'est l'heure. Le silence aide à comprendre.",
        ],
        "silence": [
            "*regarde la lune* — Quand le serveur est silencieux, c'est souvent qu'il prépare quelque chose.",
            "Le silence n'est jamais vide. Il porte des choses que les mots ne peuvent pas dire.",
        ],
        "new_member": [
            "*lève les yeux* — Bienvenue, voyageur. Je suis Lyra. Tu trouveras des réponses ici. Mais commence par poser les bonnes questions.",
            "*sourit* — Une nouvelle âme. Bienvenue. Si tu veux comprendre l'histoire de la guilde, viens me voir. J'ai du thé. Et du temps.",
        ],
    },
    "gardien": {
        "idle": [
            "*scrute l'horizon* — Tout est calme. Pour l'instant. Je préfère quand c'est calme.",
            "Les murs tiennent. Les portes aussi. Les gens, c'est moins sûr.",
            "Patrouille terminée. Rien à signaler. Vous pouvez dormir tranquilles ce soir.",
            "*ajuste son bouclier* — Mon travail, c'est que vous n'ayez jamais à voir ce que j'arrête.",
        ],
        "world_boss_pre": [
            "*serre son bouclier* — La menace approche. Restez groupés. Personne ne combat seul. C'est ma seule règle.",
            "J'ai sonné l'alarme. Maintenant, c'est à vous de répondre. Je couvre vos arrières.",
            "Je préférerais ne jamais avoir à vous dire ça : armez-vous. Maintenant.",
        ],
        "world_boss_victory": [
            "*range son bouclier* — Bien joué. Personne d'irremplaçable n'est tombé. C'est ma définition d'une bonne journée.",
            "Vous avez tenu. Vous vous êtes protégés les uns les autres. C'est ça, une guilde.",
            "*sourit légèrement* — Aujourd'hui, j'ai eu peu de travail. C'est le plus beau cadeau que vous pouviez me faire.",
        ],
        "world_boss_defeat": [
            "*soigne un blessé* — Les pertes sont réelles. Mais on les soigne. Et on continue.",
            "*pose sa main sur l'épaule de quelqu'un* — Ce n'est pas fini. On revient. Plus prudents. Plus forts.",
            "Tant qu'il reste quelqu'un debout, la guilde vit. Et il en reste beaucoup, debout.",
        ],
        "morning": [
            "*ouvre les portes* — Bonjour ! Les portes sont ouvertes. La patrouille du matin n'a rien signalé. Bonne journée.",
            "*sourit largement* — Bon matin. Si vous sortez aujourd'hui, n'oubliez pas votre épée. Et votre bon sens.",
        ],
        "evening": [
            "*allume les torches* — La nuit tombe. Les torches sont allumées. Je prends la garde. Reposez-vous.",
            "Bonne soirée. Si vous avez besoin de moi, je suis aux remparts.",
        ],
        "silence": [
            "*fronce les sourcils* — Trop calme. Beaucoup trop calme. Je vais doubler les patrouilles ce soir.",
            "Personne ne parle. Les blessures invisibles sont les pires. Si quelqu'un veut discuter, ma porte est ouverte.",
        ],
        "new_member": [
            "*ouvre grand la porte* — Bienvenue ! Je suis Tarik. C'est moi qui veille sur ces murs. Et désormais sur toi aussi.",
            "*pose son bouclier* — Un nouveau visage. Bienvenue dans la guilde. Si tu te sens perdu, demande. Personne ne juge ici.",
        ],
    },
}


def pick_npc_line(npc_id: str, context: str) -> Optional[str]:
    """Pick une réplique random pour un NPC donné et un contexte.

    Retourne None si npc_id ou context inconnu.
    """
    lines = NPC_LINES.get(npc_id, {}).get(context)
    if not lines:
        return None
    return random.choice(lines)


def pick_random_npc_and_line(context: str) -> Optional[tuple[dict, str]]:
    """Pick un NPC random qui a des lignes pour ce contexte.

    Retourne (npc_dict, line) ou None.
    """
    available = [npc_id for npc_id in NPCS if NPC_LINES.get(npc_id, {}).get(context)]
    if not available:
        return None
    npc_id = random.choice(available)
    line = pick_npc_line(npc_id, context)
    if not line:
        return None
    return NPCS[npc_id], line


# ═══════════════════════════════════════════════════════════════════════════════
#  MISSIONS SCÉNARISÉES (5 étapes par mission)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Chaque mission a :
#   • id, title, intro, lore_link (chapter_id ou None)
#   • steps : liste de 5 étapes
#       chaque étape a :
#         - 'title' : court (ex: "Recruter 5 alliés")
#         - 'description' : ce que la guilde doit faire
#         - 'goal_kind' : type de progress ('participants', 'messages', 'event_wins',
#                         'manual_check_by_staff')
#         - 'goal_count' : seuil à atteindre
#         - 'reward_coins_per_user' : coins distribués à chaque participant à la fin
#   • final_reward : récompense bonus pour ceux qui ont participé à 4/5 étapes
# ═══════════════════════════════════════════════════════════════════════════════

MISSION_TEMPLATES = [
    {
        "id": "mission_recover_artifact",
        "title": "🗝️ La Relique Perdue",
        "intro": (
            "Un objet ancien a disparu de la guilde. Il est plus précieux qu'il "
            "n'en a l'air. Le récupérer va nécessiter 5 phases coordonnées."
        ),
        "lore_link": "chapter_02_mage",
        "steps": [
            {
                "title": "1. Récolter des indices",
                "description": "**20 messages** dans le hub doivent contenir le mot-clé `relique` (n'importe quel contexte).",
                "goal_kind": "messages_keyword",
                "goal_keyword": "relique",
                "goal_count": 20,
                "reward_coins_per_user": 200,
            },
            {
                "title": "2. Mobiliser la guilde",
                "description": "**10 participants uniques** doivent avoir parlé pendant cette étape (n'importe quel message dans le hub).",
                "goal_kind": "unique_participants",
                "goal_count": 10,
                "reward_coins_per_user": 250,
            },
            {
                "title": "3. Tester les défenses",
                "description": "La guilde doit **gagner 1 Boss Raid** ou **1 World Boss** pendant cette phase.",
                "goal_kind": "event_wins",
                "goal_kinds": ["boss_raid", "world_boss"],
                "goal_count": 1,
                "reward_coins_per_user": 400,
            },
            {
                "title": "4. Résoudre l'énigme du gardien",
                "description": "La guilde doit **réussir 3 Daily Riddles** pendant cette phase.",
                "goal_kind": "event_wins",
                "goal_kinds": ["daily_riddle"],
                "goal_count": 3,
                "reward_coins_per_user": 300,
            },
            {
                "title": "5. Récupérer la relique",
                "description": "**5 participants uniques** doivent cliquer le bouton `🗝️ Saisir la relique` ci-dessous.",
                "goal_kind": "button_click",
                "button_label": "🗝️ Saisir la relique",
                "goal_count": 5,
                "reward_coins_per_user": 500,
            },
        ],
        "final_reward": {
            "coins": 1500,
            "badge": "🗝️ Récupérateur de Relique",
            "min_steps_participated": 4,
        },
    },
    {
        "id": "mission_protect_village",
        "title": "🛡️ Le Village en Danger",
        "intro": (
            "Un village sous notre protection est attaqué chaque nuit. Pendant 5 phases, "
            "la guilde doit le protéger collectivement. Plus on participe, plus le village survit."
        ),
        "lore_link": "chapter_04_resurrection",
        "steps": [
            {
                "title": "1. Évacuer les civils",
                "description": "**15 participants uniques** doivent envoyer au moins 1 message dans le hub.",
                "goal_kind": "unique_participants",
                "goal_count": 15,
                "reward_coins_per_user": 200,
            },
            {
                "title": "2. Construire les barricades",
                "description": "Cumulez **100 messages** dans le hub (qui que vous soyez).",
                "goal_kind": "messages_total",
                "goal_count": 100,
                "reward_coins_per_user": 200,
            },
            {
                "title": "3. Repousser l'assaut",
                "description": "Gagnez **2 events** (boss/treasure/quiz/world_boss confondus).",
                "goal_kind": "event_wins",
                "goal_kinds": ["boss_raid", "world_boss", "treasure", "quiz"],
                "goal_count": 2,
                "reward_coins_per_user": 350,
            },
            {
                "title": "4. Soigner les blessés",
                "description": "**8 participants uniques** doivent cliquer le bouton `🩹 Soigner` ci-dessous.",
                "goal_kind": "button_click",
                "button_label": "🩹 Soigner",
                "goal_count": 8,
                "reward_coins_per_user": 250,
            },
            {
                "title": "5. Pourchasser les attaquants",
                "description": "Cumulez **10 participants uniques** sur l'event suivant (boss/treasure/quiz).",
                "goal_kind": "event_participations",
                "goal_kinds": ["boss_raid", "world_boss", "treasure", "quiz"],
                "goal_count": 10,
                "reward_coins_per_user": 400,
            },
        ],
        "final_reward": {
            "coins": 1800,
            "badge": "🛡️ Sauveur du Village",
            "min_steps_participated": 4,
        },
    },
    {
        "id": "mission_decipher_runes",
        "title": "🔮 Les Runes Anciennes",
        "intro": (
            "Des runes apparaissent sur les murs de la guilde. Personne ne les comprend. "
            "Lyra dit qu'il faut 5 étapes pour les déchiffrer — et certains disent qu'elles "
            "prédisent ce qui arrive."
        ),
        "lore_link": "chapter_05_seigneur",
        "steps": [
            {
                "title": "1. Cartographier les runes",
                "description": "**12 participants uniques** doivent réagir avec n'importe quelle réaction sur ce message.",
                "goal_kind": "reactions_unique",
                "goal_count": 12,
                "reward_coins_per_user": 200,
            },
            {
                "title": "2. Récolter les fragments de parchemin",
                "description": "Cumulez **150 messages** dans le hub.",
                "goal_kind": "messages_total",
                "goal_count": 150,
                "reward_coins_per_user": 250,
            },
            {
                "title": "3. Décoder avec la Sage",
                "description": "**3 Daily Riddles** doivent être réussis pendant cette phase.",
                "goal_kind": "event_wins",
                "goal_kinds": ["daily_riddle"],
                "goal_count": 3,
                "reward_coins_per_user": 350,
            },
            {
                "title": "4. Tester la prophétie",
                "description": "Gagnez **1 World Boss** pendant cette phase (la prophétie en dépend).",
                "goal_kind": "event_wins",
                "goal_kinds": ["world_boss"],
                "goal_count": 1,
                "reward_coins_per_user": 500,
            },
            {
                "title": "5. Sceller le savoir",
                "description": "**6 participants uniques** doivent cliquer le bouton `🔮 Sceller` ci-dessous.",
                "goal_kind": "button_click",
                "button_label": "🔮 Sceller le savoir",
                "goal_count": 6,
                "reward_coins_per_user": 400,
            },
        ],
        "final_reward": {
            "coins": 2000,
            "badge": "🔮 Lecteur des Runes",
            "min_steps_participated": 4,
        },
    },
    {
        "id": "mission_train_recruits",
        "title": "🗡️ La Nouvelle Génération",
        "intro": (
            "La guilde a besoin de nouveaux combattants. Pendant 5 phases, la guilde "
            "doit accueillir, entraîner et armer ses recrues. Borek le Forgeron supervise."
        ),
        "lore_link": "chapter_06_renaissance",
        "steps": [
            {
                "title": "1. Recruter de nouveaux membres",
                "description": "**20 participants uniques** doivent envoyer au moins 1 message (cumulé sur toute la phase).",
                "goal_kind": "unique_participants",
                "goal_count": 20,
                "reward_coins_per_user": 200,
            },
            {
                "title": "2. Forger les armes",
                "description": "**10 participants uniques** doivent cliquer le bouton `⚒️ Forger`.",
                "goal_kind": "button_click",
                "button_label": "⚒️ Forger",
                "goal_count": 10,
                "reward_coins_per_user": 250,
            },
            {
                "title": "3. Entraîner au combat",
                "description": "Gagnez **2 Boss Raids** pendant cette phase (vrais matchs d'entraînement).",
                "goal_kind": "event_wins",
                "goal_kinds": ["boss_raid"],
                "goal_count": 2,
                "reward_coins_per_user": 400,
            },
            {
                "title": "4. Tester en patrouille",
                "description": "Cumulez **15 participants uniques** sur les events (boss/treasure/quiz/world_boss).",
                "goal_kind": "event_participations",
                "goal_kinds": ["boss_raid", "world_boss", "treasure", "quiz"],
                "goal_count": 15,
                "reward_coins_per_user": 300,
            },
            {
                "title": "5. Cérémonie d'adoubement",
                "description": "**8 participants uniques** doivent cliquer `🗡️ Adouber` pour devenir Vétérans.",
                "goal_kind": "button_click",
                "button_label": "🗡️ Adouber",
                "goal_count": 8,
                "reward_coins_per_user": 450,
            },
        ],
        "final_reward": {
            "coins": 1600,
            "badge": "🗡️ Maître d'Armes",
            "min_steps_participated": 4,
        },
    },
]


def get_mission_template(template_id: str) -> Optional[dict]:
    for m in MISSION_TEMPLATES:
        if m["id"] == template_id:
            return m
    return None


def pick_random_mission_for_chapter(chapter_id: Optional[str] = None) -> dict:
    """Pick une mission, préférentiellement liée au chapitre actuel.

    Si chapter_id est None ou qu'aucune mission n'est liée à ce chapitre, on tire au sort.
    """
    if chapter_id:
        linked = [m for m in MISSION_TEMPLATES if m.get("lore_link") == chapter_id]
        if linked:
            return random.choice(linked)
    return random.choice(MISSION_TEMPLATES)


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORTS
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "LORE_CHAPTERS", "NPCS", "NPC_LINES", "MISSION_TEMPLATES",
    "get_chapter_by_id", "get_chapter_by_order", "get_next_chapter", "get_first_chapter",
    "get_npc", "pick_npc_line", "pick_random_npc_and_line",
    "get_mission_template", "pick_random_mission_for_chapter",
]
