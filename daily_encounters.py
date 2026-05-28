"""
daily_encounters.py — Rencontres quotidiennes avec les NPCs (Phase 170.3).

🎯 OBJECTIF : ancrer la Chronique dans le quotidien. Chaque joueur peut
vivre 1 rencontre par jour avec un NPC random. Chaque rencontre = micro
situation narrative + 3 choix moraux légers. Chaque choix :
- Modifie la relation avec le NPC (±10 à ±20 mood)
- Donne une petite récompense (10-50 coins)
- Compte comme 1 "encounter" dans la progression de la Chronique
- Loggue dans le Codex anonyme

PHILOSOPHIE :
- Engagement de 5-10 min/jour (rien d'obligatoire).
- Pas de "bonne" ou "mauvaise" réponse — chaque choix sert une voie.
- Les choix accumulent une orientation collective qui influence l'Acte 1.3.
- Reset minuit FR (Europe/Paris).
- Pas de FOMO : un joueur peut sauter des jours sans pénalité.

DB :
- daily_encounters_log (id PK, guild_id, user_id, date_key,
                        encounter_id, choice_idx, mood_delta_applied,
                        coin_reward, played_at)

API :
- setup(bot, get_db, db_get, v2, npc_module, story_module, add_coins_fn)
- init_db()
- ENCOUNTER_CATALOG, get_encounter_def(encounter_id)
- has_done_today(guild_id, user_id) -> bool
- pick_encounter_for_user(guild_id, user_id) -> dict | None
- record_choice(guild_id, user_id, encounter_id, choice_idx) -> dict result
- build_encounter_panel(guild_id, user_id, encounter, view_user_id) -> LayoutView
- open_encounter_from_hub(interaction) -> appel depuis le hub
- EncounterChoiceButton (DynamicItem persistent)
- register_persistent_views(bot)
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ui import Button

try:
    from zoneinfo import ZoneInfo
    _PARIS_TZ = ZoneInfo("Europe/Paris")
except Exception:
    _PARIS_TZ = None

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_npc = None
_story = None
_add_coins = None


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE ENCOUNTERS
# ═══════════════════════════════════════════════════════════════════════════
# Structure :
# - id : "aria_1", "korr_3"… unique
# - npc_id : référence au NPC (cf npc_personalities)
# - title : court titre de la situation
# - narrative : 2-3 phrases décrivant la situation
# - choices : liste de 3 dicts (toujours 3 choix)
#   - label : court (button label, ≤ 40 chars)
#   - reply : courte réponse du NPC après le choix (2-3 phrases)
#   - mood_delta : impact ±10/±20 sur le mood du user
#   - coin_reward : 10-50 coins
#
# 5 encounters par NPC × 6 NPCs = 30 encounters total.

ENCOUNTER_CATALOG = [
    # ─── ARIA — sage, prudente ───
    {
        "id": "aria_1",
        "npc_id": "aria",
        "title": "Une cendre étrange",
        "narrative": (
            "Aria observe une cendre noire qui flotte au-dessus de sa main. "
            "« Cette nuance n'existait pas hier », murmure-t-elle. Que lui conseilles-tu ?"
        ),
        "choices": [
            {
                "label": "🔬 L'étudier en silence",
                "reply": "Aria hoche la tête. « La prudence parle en toi. Bien. »",
                "mood_delta": 15,
                "coin_reward": 30,
            },
            {
                "label": "🔥 La brûler par sécurité",
                "reply": "Aria fronce les sourcils. « Détruire avant comprendre… risqué. »",
                "mood_delta": -10,
                "coin_reward": 20,
            },
            {
                "label": "📜 Consulter le Codex",
                "reply": "Aria sourit. « Tu apprendras vite, je le sens. »",
                "mood_delta": 10,
                "coin_reward": 25,
            },
        ],
    },
    {
        "id": "aria_2",
        "npc_id": "aria",
        "title": "Le livre vieux",
        "narrative": (
            "Aria te tend un livre relié de cuir noir. « Ce livre n'a pas de fin. "
            "Chaque page lue en révèle une nouvelle. Veux-tu commencer ? »"
        ),
        "choices": [
            {
                "label": "📖 L'ouvrir avec respect",
                "reply": "Aria sourit doucement. « Tu honores le savoir. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "🤔 Demander qui l'a écrit",
                "reply": "Aria hésite. « Une question juste. Mais sans réponse pour l'instant. »",
                "mood_delta": 8,
                "coin_reward": 25,
            },
            {
                "label": "❌ Refuser, méfiant",
                "reply": "Aria range le livre, déçue. « La méfiance protège, mais isole aussi. »",
                "mood_delta": -8,
                "coin_reward": 15,
            },
        ],
    },
    {
        "id": "aria_3",
        "npc_id": "aria",
        "title": "Le disciple inquiet",
        "narrative": (
            "Un jeune disciple t'aborde, fébrile. « Aria est malade. Elle refuse "
            "qu'on la voie. Toi, elle t'écoute parfois. Iras-tu ? »"
        ),
        "choices": [
            {
                "label": "🌿 Aller la voir avec une plante",
                "reply": "Aria t'accueille faiblement. « Tu connais la juste mesure. »",
                "mood_delta": 18,
                "coin_reward": 40,
            },
            {
                "label": "🚶 Respecter son isolement",
                "reply": "Plus tard, Aria te remercie d'avoir respecté son besoin.",
                "mood_delta": 5,
                "coin_reward": 20,
            },
            {
                "label": "📜 Lui écrire un mot",
                "reply": "Aria sourit en lisant. « Les mots justes valent mille gestes. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
        ],
    },
    {
        "id": "aria_4",
        "npc_id": "aria",
        "title": "Aria sous la pluie",
        "narrative": (
            "Tu trouves Aria seule sous une pluie battante, au sommet de la Tour. "
            "Elle semble loin de tout. Que fais-tu ?"
        ),
        "choices": [
            {
                "label": "☂️ Tendre un parapluie",
                "reply": "Aria sursaute, puis sourit. « Tu te soucies. C'est rare. »",
                "mood_delta": 15,
                "coin_reward": 35,
            },
            {
                "label": "🤐 Partir sans rien dire",
                "reply": "Plus tard, Aria mentionne ton tact. « Tu sais quand parler — et quand non. »",
                "mood_delta": 10,
                "coin_reward": 25,
            },
            {
                "label": "🗣️ Lui demander si ça va",
                "reply": "Aria t'observe longuement. « La sollicitude est un don. »",
                "mood_delta": 8,
                "coin_reward": 25,
            },
        ],
    },
    {
        "id": "aria_5",
        "npc_id": "aria",
        "title": "Le rêve de la cendre",
        "narrative": (
            "Aria te confie : « J'ai rêvé d'une porte qui s'ouvre sous le monde. "
            "Une voix appelait. Penses-tu que ce rêve dit vrai ? »"
        ),
        "choices": [
            {
                "label": "🌙 « Les rêves sont des avertissements »",
                "reply": "Aria approuve gravement. « Tu écoutes les profondeurs. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "😅 « Sans doute juste la fatigue »",
                "reply": "Aria se détourne. « Peut-être. Peut-être pas. »",
                "mood_delta": -5,
                "coin_reward": 20,
            },
            {
                "label": "📚 « Il faut consulter les anciens textes »",
                "reply": "Aria hoche la tête. « Le savoir guidera. Allons-y. »",
                "mood_delta": 10,
                "coin_reward": 30,
            },
        ],
    },

    # ─── KORR — loyal, forgeron ───
    {
        "id": "korr_1",
        "npc_id": "korr",
        "title": "La forge en flammes",
        "narrative": (
            "Korr martèle une épée incandescente, sueur au front. Il te lance un "
            "regard. « Tu veux essayer ? La technique se transmet en faisant. »"
        ),
        "choices": [
            {
                "label": "🔨 Prendre le marteau",
                "reply": "Korr rit, satisfait. « Voilà un acte. Pas des paroles. »",
                "mood_delta": 18,
                "coin_reward": 40,
            },
            {
                "label": "👀 Observer attentivement",
                "reply": "Korr accepte. « Apprendre par le regard, c'est valable aussi. »",
                "mood_delta": 8,
                "coin_reward": 25,
            },
            {
                "label": "😬 Refuser poliment",
                "reply": "Korr grommelle. « Bah. Reviens quand tu seras prêt. »",
                "mood_delta": -10,
                "coin_reward": 15,
            },
        ],
    },
    {
        "id": "korr_2",
        "npc_id": "korr",
        "title": "L'invitation à boire",
        "narrative": (
            "Korr ouvre une bouteille d'hydromel artisanal. « Bois avec moi. "
            "La forge se ferme à la nuit, et la solitude est lourde. »"
        ),
        "choices": [
            {
                "label": "🍺 Accepter avec joie",
                "reply": "Korr trinque. « Un vrai compagnon, toi. »",
                "mood_delta": 15,
                "coin_reward": 30,
            },
            {
                "label": "🥛 Préférer de l'eau",
                "reply": "Korr hausse les épaules. « Chacun son poison. Bois quand même. »",
                "mood_delta": 5,
                "coin_reward": 20,
            },
            {
                "label": "🏃 Décliner, trop d'autres tâches",
                "reply": "Korr fronce le sourcil. « Le travail attend toujours. Mais pas l'amitié. »",
                "mood_delta": -12,
                "coin_reward": 10,
            },
        ],
    },
    {
        "id": "korr_3",
        "npc_id": "korr",
        "title": "Le voleur près de la forge",
        "narrative": (
            "Tu vois une silhouette voler un outil de Korr dans la nuit. Korr "
            "est à l'intérieur, dos tourné. Le voleur s'enfuit."
        ),
        "choices": [
            {
                "label": "🚨 Alerter Korr immédiatement",
                "reply": "Korr fonce. Il revient peu après, l'outil retrouvé. « Tu es droit. Merci. »",
                "mood_delta": 18,
                "coin_reward": 45,
            },
            {
                "label": "🏃 Poursuivre seul le voleur",
                "reply": "Tu rattrapes le voleur. Korr est impressionné. « Du courage et de l'action. »",
                "mood_delta": 15,
                "coin_reward": 40,
            },
            {
                "label": "🙈 Ne pas s'en mêler",
                "reply": "Korr découvre le vol plus tard. Il te regarde longuement. Aucun mot.",
                "mood_delta": -18,
                "coin_reward": 5,
            },
        ],
    },
    {
        "id": "korr_4",
        "npc_id": "korr",
        "title": "L'outil tombé",
        "narrative": (
            "Korr a fait tomber son marteau dans une crevasse étroite. Il "
            "soupire. « Vieux. Trop gros pour entrer. Cet outil… mon père me l'a légué. »"
        ),
        "choices": [
            {
                "label": "🤲 Le récupérer pour lui",
                "reply": "Tu y arrives. Korr serre l'outil contre lui, ému. « Tu touches ma mémoire. »",
                "mood_delta": 20,
                "coin_reward": 50,
            },
            {
                "label": "🛠️ Proposer de fabriquer un nouveau",
                "reply": "Korr secoue la tête. « Tu ne comprends pas la valeur des choses. »",
                "mood_delta": -10,
                "coin_reward": 15,
            },
            {
                "label": "💰 Lui proposer des coins de consolation",
                "reply": "Korr refuse fermement. « L'argent ne remplace pas ce qui est cassé. »",
                "mood_delta": -15,
                "coin_reward": 10,
            },
        ],
    },
    {
        "id": "korr_5",
        "npc_id": "korr",
        "title": "Le minerai introuvable",
        "narrative": (
            "Korr cherche un minerai rare pour une commande importante. « Si "
            "tu m'aides à le trouver, je te dois un service. Vraiment. »"
        ),
        "choices": [
            {
                "label": "⛏️ L'accompagner",
                "reply": "La quête réussit. Korr te serre la main. « Un acte vaut mille promesses. »",
                "mood_delta": 18,
                "coin_reward": 45,
            },
            {
                "label": "🗺️ Lui donner une carte",
                "reply": "Korr trouve seul. « Pratique, ton idée. Reviens me voir. »",
                "mood_delta": 10,
                "coin_reward": 30,
            },
            {
                "label": "🙅 Refuser, occupé",
                "reply": "Korr s'éloigne. « Bon. La prochaine fois, peut-être. »",
                "mood_delta": -10,
                "coin_reward": 15,
            },
        ],
    },

    # ─── LYRA — érudite, ambiguë ───
    {
        "id": "lyra_1",
        "npc_id": "lyra",
        "title": "Le parchemin interdit",
        "narrative": (
            "Lyra étudie un parchemin que l'Ordre a banni. « Ce texte parle des "
            "cendres. Veux-tu m'aider à le déchiffrer ? Discrètement. »"
        ),
        "choices": [
            {
                "label": "📜 L'aider sans poser de question",
                "reply": "Lyra sourit. « Tu es de mon côté. Bien. »",
                "mood_delta": 18,
                "coin_reward": 45,
            },
            {
                "label": "❓ Demander pourquoi c'est interdit",
                "reply": "Lyra hésite. « Bonne question. Mais pas le bon moment. »",
                "mood_delta": 5,
                "coin_reward": 25,
            },
            {
                "label": "⚠️ Refuser, c'est dangereux",
                "reply": "Lyra te toise. « La prudence des autres. Inutile à mes yeux. »",
                "mood_delta": -12,
                "coin_reward": 10,
            },
        ],
    },
    {
        "id": "lyra_2",
        "npc_id": "lyra",
        "title": "Le secret confié",
        "narrative": (
            "Lyra t'attrape par le bras. « J'ai vu quelque chose dans le sous-sol. "
            "Je te le dis à toi seul. Mais ne le répète pas. »"
        ),
        "choices": [
            {
                "label": "🤐 Promettre le silence",
                "reply": "Lyra acquiesce gravement. « Tu honores la confidence. »",
                "mood_delta": 15,
                "coin_reward": 35,
            },
            {
                "label": "👂 Écouter avec prudence",
                "reply": "Lyra raconte. Tu écoutes sans jurer. « Tu décideras toi-même. »",
                "mood_delta": 8,
                "coin_reward": 25,
            },
            {
                "label": "🚫 Refuser d'entendre",
                "reply": "Lyra se ferme. « Je m'étais trompée sur toi. »",
                "mood_delta": -12,
                "coin_reward": 10,
            },
        ],
    },
    {
        "id": "lyra_3",
        "npc_id": "lyra",
        "title": "La tour vide",
        "narrative": (
            "Lyra a disparu de la Bibliothèque. Sa robe est restée. Une note "
            "dit : « Si quelqu'un cherche : ne cherchez pas. »"
        ),
        "choices": [
            {
                "label": "🔍 La chercher quand même",
                "reply": "Tu la trouves dans une crypte. Elle soupire. « Têtu. Mais touché. »",
                "mood_delta": 15,
                "coin_reward": 40,
            },
            {
                "label": "📝 Respecter sa note",
                "reply": "Lyra revient seule, deux jours plus tard. « Tu m'as respectée. Rare. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "👥 Alerter les autres NPCs",
                "reply": "Lyra apprend la rumeur, furieuse. « Tu n'as rien compris. »",
                "mood_delta": -15,
                "coin_reward": 10,
            },
        ],
    },
    {
        "id": "lyra_4",
        "npc_id": "lyra",
        "title": "La théorie controversée",
        "narrative": (
            "Lyra te présente sa nouvelle théorie : « Les cendres ne tombent "
            "pas. Elles MONTENT. Du sol vers le ciel. Qu'en penses-tu ? »"
        ),
        "choices": [
            {
                "label": "🌀 « Fascinant, continue »",
                "reply": "Lyra rayonne. « Enfin quelqu'un d'ouvert. »",
                "mood_delta": 15,
                "coin_reward": 35,
            },
            {
                "label": "🤨 « Prouve-le »",
                "reply": "Lyra accepte le défi. « Bonne discipline. Tu me forces à mieux. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "😐 « C'est absurde »",
                "reply": "Lyra se ferme. « La fermeture d'esprit est une maladie. »",
                "mood_delta": -15,
                "coin_reward": 5,
            },
        ],
    },
    {
        "id": "lyra_5",
        "npc_id": "lyra",
        "title": "Le livre devant elle",
        "narrative": (
            "Lyra hésite devant un livre noir. « Ce livre m'appelle. Mais le "
            "lire, c'est… engager quelque chose. Je devrais ? »"
        ),
        "choices": [
            {
                "label": "📖 « Lis-le »",
                "reply": "Lyra hoche la tête. « Tu pousses au savoir. Bien. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "🚫 « Ne le lis pas »",
                "reply": "Lyra range le livre. « Tu me protèges de moi-même. Touchant. »",
                "mood_delta": 10,
                "coin_reward": 25,
            },
            {
                "label": "🤝 « Lisons-le ensemble »",
                "reply": "Lyra sourit, surprise. « Une alliance dans le savoir. Étrange. »",
                "mood_delta": 15,
                "coin_reward": 35,
            },
        ],
    },

    # ─── DRAZEK — guerrier, impulsif ───
    {
        "id": "drazek_1",
        "npc_id": "drazek",
        "title": "L'entraînement au combat",
        "narrative": (
            "Drazek t'invite à croiser le fer en duel d'entraînement. « Pas pour "
            "te blesser. Pour te tester. Tu en es ? »"
        ),
        "choices": [
            {
                "label": "⚔️ Accepter le duel",
                "reply": "Drazek attaque, vous échangez des coups. À la fin : « Tu as du cran. »",
                "mood_delta": 18,
                "coin_reward": 45,
            },
            {
                "label": "🛡️ Accepter mais en défense seule",
                "reply": "Drazek apprécie la prudence. « Un esprit stratégique. Respect. »",
                "mood_delta": 10,
                "coin_reward": 30,
            },
            {
                "label": "🚫 Refuser, pas envie",
                "reply": "Drazek rit froidement. « Bah. Je m'en doutais. »",
                "mood_delta": -15,
                "coin_reward": 5,
            },
        ],
    },
    {
        "id": "drazek_2",
        "npc_id": "drazek",
        "title": "Le défi public",
        "narrative": (
            "Drazek défie publiquement un voyageur arrogant à un duel. Le voyageur "
            "blêmit. Drazek te regarde, attendant ton avis."
        ),
        "choices": [
            {
                "label": "🔥 « Vas-y, montre-lui »",
                "reply": "Drazek hurle de joie. « Voilà du soutien franc ! »",
                "mood_delta": 15,
                "coin_reward": 35,
            },
            {
                "label": "🕊️ « Laisse-le partir »",
                "reply": "Drazek hésite, recule. Plus tard : « Tu m'as évité une honte. Merci. »",
                "mood_delta": 18,
                "coin_reward": 40,
            },
            {
                "label": "😬 Détourner le regard",
                "reply": "Drazek s'en va, blessé. « La neutralité est lâche. »",
                "mood_delta": -12,
                "coin_reward": 10,
            },
        ],
    },
    {
        "id": "drazek_3",
        "npc_id": "drazek",
        "title": "La cicatrice nouvelle",
        "narrative": (
            "Drazek a une grande cicatrice fraîche sur le front. Il évite le sujet. "
            "Tu remarques."
        ),
        "choices": [
            {
                "label": "💬 Lui demander, sincère",
                "reply": "Drazek hésite, puis raconte. « Tu me donnes le droit d'être faible. »",
                "mood_delta": 18,
                "coin_reward": 40,
            },
            {
                "label": "🤐 Ne pas en parler",
                "reply": "Drazek apprécie. « Tu sais respecter. »",
                "mood_delta": 8,
                "coin_reward": 25,
            },
            {
                "label": "😅 « T'as morflé ! »",
                "reply": "Drazek se ferme. « La moquerie. Vraiment. »",
                "mood_delta": -15,
                "coin_reward": 5,
            },
        ],
    },
    {
        "id": "drazek_4",
        "npc_id": "drazek",
        "title": "Le vantard",
        "narrative": (
            "Drazek raconte un exploit guerrier qui semble exagéré. Les autres "
            "rient bas. Il te regarde, attendant."
        ),
        "choices": [
            {
                "label": "👏 Applaudir avec enthousiasme",
                "reply": "Drazek rayonne. « Un vrai ami sait reconnaître. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "🤔 Demander des détails",
                "reply": "Drazek hésite, puis admet quelques exagérations. « Tu m'as appris quelque chose. »",
                "mood_delta": 10,
                "coin_reward": 25,
            },
            {
                "label": "🙄 Ricaner doucement",
                "reply": "Drazek le voit. Il se tait. La conversation meurt.",
                "mood_delta": -12,
                "coin_reward": 5,
            },
        ],
    },
    {
        "id": "drazek_5",
        "npc_id": "drazek",
        "title": "Le guerrier qui pleure",
        "narrative": (
            "Tu surprends Drazek pleurant seul derrière une stèle. Il ne t'a pas "
            "vu. Tu peux partir, ou rester."
        ),
        "choices": [
            {
                "label": "🤚 S'éloigner discrètement",
                "reply": "Plus tard, Drazek mentionne avoir été 'observé'. Tu nies. Il sourit. « Merci. »",
                "mood_delta": 18,
                "coin_reward": 40,
            },
            {
                "label": "🪑 S'asseoir près de lui en silence",
                "reply": "Drazek pleure plus fort, puis se calme. « Personne ne fait ça pour moi. »",
                "mood_delta": 20,
                "coin_reward": 45,
            },
            {
                "label": "📢 Le mentionner à un autre NPC",
                "reply": "Drazek apprend la rumeur. Il ne te parle plus pendant des jours.",
                "mood_delta": -20,
                "coin_reward": 0,
            },
        ],
    },

    # ─── SIENNA — marchande, neutre ───
    {
        "id": "sienna_1",
        "npc_id": "sienna",
        "title": "Le marché louche",
        "narrative": (
            "Sienna te propose discrètement : « Un objet rare. Pas vraiment légal. "
            "Mais utile. 500 coins. Tu en es ? »"
        ),
        "choices": [
            {
                "label": "💰 Accepter le deal",
                "reply": "Sienna sourit. « Un partenaire. Je m'en souviendrai. »",
                "mood_delta": 12,
                "coin_reward": 35,
            },
            {
                "label": "🤝 Refuser poliment",
                "reply": "Sienna hausse les épaules. « Pas de jugement. Reviens quand tu veux. »",
                "mood_delta": 5,
                "coin_reward": 20,
            },
            {
                "label": "🚨 Menacer de la dénoncer",
                "reply": "Sienna se ferme. « Tu viens de fermer une porte importante. »",
                "mood_delta": -18,
                "coin_reward": 5,
            },
        ],
    },
    {
        "id": "sienna_2",
        "npc_id": "sienna",
        "title": "Le vol au marché",
        "narrative": (
            "Sienna se fait subtiliser une bourse par un gamin. Elle te voit, "
            "supplie du regard. Le gamin court vite."
        ),
        "choices": [
            {
                "label": "🏃 Le rattraper et récupérer",
                "reply": "Sienna serre la bourse. « Je te dois un. Je n'oublierai pas. »",
                "mood_delta": 18,
                "coin_reward": 40,
            },
            {
                "label": "💰 Lui offrir des coins en compensation",
                "reply": "Sienna accepte mais reste sur sa faim. « C'est gentil. Pas pareil. »",
                "mood_delta": 5,
                "coin_reward": 15,
            },
            {
                "label": "🤷 Ne pas s'en mêler",
                "reply": "Sienna te regarde froidement. « Note prise. »",
                "mood_delta": -12,
                "coin_reward": 5,
            },
        ],
    },
    {
        "id": "sienna_3",
        "npc_id": "sienna",
        "title": "Le cadeau étrange",
        "narrative": (
            "Sienna te tend un objet sans rien dire. « Un cadeau. Sans contrepartie. "
            "Pour une fois. » Tu hésites."
        ),
        "choices": [
            {
                "label": "🎁 Accepter et remercier",
                "reply": "Sienna sourit, surprise par ta confiance. « Garde-le bien. »",
                "mood_delta": 15,
                "coin_reward": 30,
            },
            {
                "label": "🤔 Demander ce qu'elle veut en échange",
                "reply": "Sienna soupire. « Rien. Vraiment. Mais je comprends ta méfiance. »",
                "mood_delta": 5,
                "coin_reward": 20,
            },
            {
                "label": "❌ Refuser, méfiance",
                "reply": "Sienna range l'objet. « Bon. Tant pis pour toi. »",
                "mood_delta": -10,
                "coin_reward": 10,
            },
        ],
    },
    {
        "id": "sienna_4",
        "npc_id": "sienna",
        "title": "La boutique fermée tôt",
        "narrative": (
            "Sienna ferme sa caravane bien plus tôt que d'habitude. Elle paraît "
            "inquiète. Tu peux lui demander, ou passer ton chemin."
        ),
        "choices": [
            {
                "label": "💬 Lui demander si tout va bien",
                "reply": "Sienna hésite, puis confie : « Quelqu'un me suit. Tes mots me touchent. »",
                "mood_delta": 18,
                "coin_reward": 40,
            },
            {
                "label": "🛡️ Proposer de la raccompagner",
                "reply": "Sienna accepte. Trois jours plus tard, un cadeau apparaît chez toi.",
                "mood_delta": 20,
                "coin_reward": 45,
            },
            {
                "label": "🚶 Passer son chemin",
                "reply": "Sienna comprend. Mais elle se souvient.",
                "mood_delta": -8,
                "coin_reward": 10,
            },
        ],
    },
    {
        "id": "sienna_5",
        "npc_id": "sienna",
        "title": "Le voyageur dont elle parle",
        "narrative": (
            "Sienna mentionne un voyageur mystérieux passé hier. « Il a payé en "
            "pièces que je ne reconnais pas. Il a parlé de toi. »"
        ),
        "choices": [
            {
                "label": "👁️ « Décris-le-moi »",
                "reply": "Sienna donne tous les détails, intriguée. « Tu sembles l'attendre. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "🤐 « Ne dis rien d'autre »",
                "reply": "Sienna respecte. « Bon. Le mystère me plaît. »",
                "mood_delta": 8,
                "coin_reward": 25,
            },
            {
                "label": "😅 « Ça ne me concerne pas »",
                "reply": "Sienna soupire. « Quelque chose te concerne. Quelque chose te cherche. »",
                "mood_delta": 0,
                "coin_reward": 15,
            },
        ],
    },

    # ─── LE VOYAGEUR — mystérieux ───
    {
        "id": "voyageur_1",
        "npc_id": "voyageur",
        "title": "Le rêve",
        "narrative": (
            "Le Voyageur apparaît dans ton rêve, encapuchonné. « Tu cherches. "
            "Tu le sais. Mais cherches-tu la bonne chose ? »"
        ),
        "choices": [
            {
                "label": "🤔 « Que dois-je chercher ? »",
                "reply": "Le Voyageur sourit. « Bonne question. Garde-la éveillé. »",
                "mood_delta": 15,
                "coin_reward": 35,
            },
            {
                "label": "💭 « Qui es-tu vraiment ? »",
                "reply": "Le Voyageur se dissout. « Trop tôt. »",
                "mood_delta": 5,
                "coin_reward": 20,
            },
            {
                "label": "😴 Se réveiller, ignorer",
                "reply": "Tu te souviens à peine. Mais l'image reste, gravée.",
                "mood_delta": -5,
                "coin_reward": 15,
            },
        ],
    },
    {
        "id": "voyageur_2",
        "npc_id": "voyageur",
        "title": "Le message cryptique",
        "narrative": (
            "Tu trouves un parchemin scellé à ta porte : « Quand la cendre "
            "tombe, l'autre face du monde respire. » Aucune signature."
        ),
        "choices": [
            {
                "label": "📜 Le garder précieusement",
                "reply": "Le Voyageur, lors d'une autre apparition : « Tu as gardé. Bien. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "🔥 Le brûler par méfiance",
                "reply": "Tu sens un froid dans la pièce. « La méfiance ferme des portes. »",
                "mood_delta": -12,
                "coin_reward": 5,
            },
            {
                "label": "🤔 Le partager avec un NPC",
                "reply": "Le Voyageur, plus tard : « Tu as fait confiance. À voir. »",
                "mood_delta": 8,
                "coin_reward": 25,
            },
        ],
    },
    {
        "id": "voyageur_3",
        "npc_id": "voyageur",
        "title": "Le nom prononcé",
        "narrative": (
            "Le Voyageur t'aborde dans un couloir. Il prononce ton nom complet, "
            "ton vrai nom. Tu n'as jamais dit ce nom à personne ici."
        ),
        "choices": [
            {
                "label": "😯 « Comment connais-tu ce nom ? »",
                "reply": "Le Voyageur sourit. « Les noms parlent à ceux qui écoutent. »",
                "mood_delta": 15,
                "coin_reward": 35,
            },
            {
                "label": "😨 Fuir aussitôt",
                "reply": "Le Voyageur ne te poursuit pas. Mais tu sentiras son regard.",
                "mood_delta": -10,
                "coin_reward": 5,
            },
            {
                "label": "🤝 « Alors je peux te faire confiance »",
                "reply": "Le Voyageur hoche la tête lentement. « Une logique étrange. Mais valide. »",
                "mood_delta": 18,
                "coin_reward": 40,
            },
        ],
    },
    {
        "id": "voyageur_4",
        "npc_id": "voyageur",
        "title": "L'apparition fugace",
        "narrative": (
            "Tu aperçois le Voyageur au loin, qui te fait signe. Quand tu y "
            "arrives, il a disparu. Une plume noire est posée au sol."
        ),
        "choices": [
            {
                "label": "🪶 Ramasser la plume",
                "reply": "Tu la sens vibrer. Un fragment d'indice s'imprime dans ton esprit.",
                "mood_delta": 15,
                "coin_reward": 35,
            },
            {
                "label": "🚶 Continuer ton chemin",
                "reply": "Tu sens un soupir derrière toi. La plume disparaît.",
                "mood_delta": -8,
                "coin_reward": 10,
            },
            {
                "label": "🤲 Attendre son retour",
                "reply": "Il ne revient pas. Mais tu as appris la patience.",
                "mood_delta": 10,
                "coin_reward": 25,
            },
        ],
    },
    {
        "id": "voyageur_5",
        "npc_id": "voyageur",
        "title": "Le regard lointain",
        "narrative": (
            "Lors d'un boss raid, tu aperçois le Voyageur observant depuis "
            "une colline. Il ne combat pas. Il regarde, prend des notes."
        ),
        "choices": [
            {
                "label": "🙋 Lui faire signe",
                "reply": "Il te répond d'un geste. « Tu m'as vu. C'est rare. »",
                "mood_delta": 12,
                "coin_reward": 30,
            },
            {
                "label": "🤐 Continuer à combattre",
                "reply": "Le Voyageur note quelque chose dans son carnet. « Action sans distraction. Bien. »",
                "mood_delta": 15,
                "coin_reward": 35,
            },
            {
                "label": "🗣️ Le pointer aux autres",
                "reply": "Le Voyageur disparaît. Plus tard : « Tu ne sais pas garder un secret. »",
                "mood_delta": -15,
                "coin_reward": 5,
            },
        ],
    },
]


def get_encounter_def(encounter_id: str) -> Optional[dict]:
    """Retourne la def d'un encounter par id."""
    for e in ENCOUNTER_CATALOG:
        if e["id"] == encounter_id:
            return e
    return None


def list_encounter_ids() -> list[str]:
    return [e["id"] for e in ENCOUNTER_CATALOG]


# ═══════════════════════════════════════════════════════════════════════════
#  Setup + DB
# ═══════════════════════════════════════════════════════════════════════════

def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict,
    npc_module=None, story_module=None, add_coins_fn=None,
):
    global _bot, _get_db, _db_get, _v2, _npc, _story, _add_coins
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _npc = npc_module
    _story = story_module
    _add_coins = add_coins_fn


async def init_db():
    """Crée la table daily_encounters_log. Idempotent."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_encounters_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    date_key TEXT NOT NULL,
                    encounter_id TEXT NOT NULL,
                    choice_idx INTEGER NOT NULL,
                    mood_delta_applied INTEGER DEFAULT 0,
                    coin_reward INTEGER DEFAULT 0,
                    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_daily_enc_today "
                "ON daily_encounters_log(guild_id, user_id, date_key)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[daily_encounters init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Daily flow
# ═══════════════════════════════════════════════════════════════════════════

def _today_key() -> str:
    """Retourne YYYY-MM-DD en heure Paris."""
    if _PARIS_TZ:
        now = datetime.now(_PARIS_TZ)
    else:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


async def has_done_today(guild_id: int, user_id: int) -> bool:
    """True si le user a déjà fait un encounter aujourd'hui."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT 1 FROM daily_encounters_log "
                "WHERE guild_id=? AND user_id=? AND date_key=? LIMIT 1",
                (guild_id, user_id, _today_key()),
            ) as cur:
                return await cur.fetchone() is not None
    except Exception:
        return False


async def pick_encounter_for_user(
    guild_id: int, user_id: int,
) -> Optional[dict]:
    """Sélectionne un encounter aléatoire pour ce user, en évitant ceux faits
    dans les 7 derniers jours (variété)."""
    if _get_db is None:
        return random.choice(ENCOUNTER_CATALOG)
    try:
        # Récupère les encounter_ids faits par ce user dans les 7 derniers jours
        async with _get_db() as db:
            async with db.execute(
                "SELECT DISTINCT encounter_id FROM daily_encounters_log "
                "WHERE guild_id=? AND user_id=? "
                "AND played_at > datetime('now', '-7 days')",
                (guild_id, user_id),
            ) as cur:
                recent = {r[0] for r in await cur.fetchall()}
        pool = [e for e in ENCOUNTER_CATALOG if e["id"] not in recent]
        if not pool:
            pool = ENCOUNTER_CATALOG[:]
        return random.choice(pool)
    except Exception:
        return random.choice(ENCOUNTER_CATALOG)


async def record_choice(
    guild_id: int, user_id: int, encounter_id: str, choice_idx: int,
) -> Optional[dict]:
    """Enregistre le choix, applique le mood, distribue les coins, alimente la
    Chronique. Retourne dict avec la réponse + récompense, ou None si erreur."""
    encounter = get_encounter_def(encounter_id)
    if not encounter:
        return None
    if not (0 <= choice_idx < len(encounter["choices"])):
        return None
    if await has_done_today(guild_id, user_id):
        return {"already_done": True}

    choice = encounter["choices"][choice_idx]
    npc_id = encounter["npc_id"]
    mood_delta = int(choice.get("mood_delta", 0))
    coin_reward = int(choice.get("coin_reward", 0))

    # Apply mood
    new_mood = 50
    if _npc is not None:
        try:
            new_mood = await _npc.change_mood(
                guild_id, user_id, npc_id, mood_delta,
            )
        except Exception:
            pass

    # Apply coins
    if _add_coins is not None and coin_reward > 0:
        try:
            await _add_coins(guild_id, user_id, coin_reward)
        except Exception:
            pass

    # Log in daily_encounters_log
    if _get_db is not None:
        try:
            async with _get_db() as db:
                await db.execute(
                    "INSERT INTO daily_encounters_log "
                    "(guild_id, user_id, date_key, encounter_id, choice_idx, "
                    "mood_delta_applied, coin_reward) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        guild_id, user_id, _today_key(),
                        encounter_id, int(choice_idx),
                        mood_delta, coin_reward,
                    ),
                )
                await db.commit()
        except Exception:
            pass

    # Feed Chronicle progression
    if _story is not None:
        try:
            await _story.on_encounter_completed(guild_id, user_id)
        except Exception:
            pass

    # Phase 170.6 : 5% chance d'obtenir un fragment d'indice
    granted_clue = None
    try:
        import mystery_investigation as _myst
        granted_clue = await _myst.try_grant_clue(
            guild_id, user_id, source="encounter",
        )
    except Exception:
        pass

    return {
        "reply": choice.get("reply", "…"),
        "mood_delta": mood_delta,
        "coin_reward": coin_reward,
        "new_mood": new_mood,
        "npc_id": npc_id,
        "granted_clue": granted_clue,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Build panel V2
# ═══════════════════════════════════════════════════════════════════════════

async def build_encounter_panel(
    guild_id: int, user_id: int,
    encounter: Optional[dict] = None,
    view_user_id: Optional[int] = None,
) -> Optional[discord.ui.LayoutView]:
    """Construit le panel V2 d'un encounter.

    Si encounter=None, on en pick un. view_user_id = la personne qui a cliqué.
    """
    if _v2 is None or _npc is None:
        return None
    if encounter is None:
        encounter = await pick_encounter_for_user(guild_id, user_id)
    if encounter is None:
        return None

    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    npc = _npc.get_npc_def(encounter["npc_id"]) or {}
    mood = await _npc.get_mood(guild_id, user_id, encounter["npc_id"])

    items = [
        v2_title(f"{npc.get('emoji', '✨')}  {npc.get('name', '?')}"),
        v2_subtitle(
            f"_{npc.get('title', '')}_\n"
            f"Relation : {_npc.mood_icon(mood)} {_npc.mood_label(mood)} ({mood}/100)"
        ),
        v2_divider(),
        v2_body(f"**{encounter['title']}**\n\n_{encounter['narrative']}_"),
        v2_divider(),
        v2_body("_Que choisis-tu ?_"),
    ]

    target_uid = view_user_id if view_user_id else user_id

    class _EncLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            self.add_item(v2_container(*items, color=0x6B46C1))

    layout = _EncLayout()
    # 3 boutons de choix
    for idx, choice in enumerate(encounter["choices"][:3]):
        btn = EncounterChoiceButton(encounter["id"], idx, target_uid)
        # Personnalise le label
        btn.item.label = (choice.get("label", f"Choix {idx + 1}"))[:80]
        layout.add_item(btn)

    return layout


async def _build_result_panel(
    guild_id: int, user_id: int, result: dict, encounter: dict,
) -> Optional[discord.ui.LayoutView]:
    """Construit le panel après un choix."""
    if _v2 is None or _npc is None:
        return None
    LayoutView = _v2['LayoutView']
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_container = _v2['v2_container']

    npc = _npc.get_npc_def(result["npc_id"]) or {}
    new_mood = result["new_mood"]

    items = [
        v2_title(f"{npc.get('emoji', '✨')}  {npc.get('name', '?')} répond"),
        v2_subtitle(
            f"_{npc.get('title', '')}_\n"
            f"Relation : {_npc.mood_icon(new_mood)} {_npc.mood_label(new_mood)} ({new_mood}/100)"
        ),
        v2_divider(),
        v2_body(f"_{result['reply']}_"),
        v2_divider(),
    ]
    delta = int(result["mood_delta"])
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    items.append(v2_body(
        f"📊 Mood : `{delta_str}`\n"
        f"💰 `+{result['coin_reward']}` 🪙\n"
        f"📖 +1 progression Chronique"
    ))

    # Phase 170.6 : si un indice a été obtenu, le révéler en bonus
    clue = result.get("granted_clue")
    if clue:
        items.append(v2_divider())
        items.append(v2_body(
            f"🔮 **TU AS REÇU UN FRAGMENT D'INDICE !**\n\n"
            f"_Mystère : **{clue['mystery_title']}** "
            f"(fragment {clue['clue_idx'] + 1}/{clue['total_fragments']})_\n\n"
            f"{clue['clue_text']}\n\n"
            f"_📖 Va dans 🔮 Mystères du Codex pour le partager publiquement "
            f"et inviter les autres à compléter._"
        ))

    items.append(v2_body(
        "_Reviens demain pour une nouvelle rencontre._"
    ))

    class _ResultLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=180)
            self.add_item(v2_container(*items, color=0x4CAF50))

    return _ResultLayout()


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent choice button
# ═══════════════════════════════════════════════════════════════════════════

class EncounterChoiceButton(
    discord.ui.DynamicItem[Button],
    template=r"enc_choice:(?P<encounter_id>[\w]+):(?P<choice_idx>\d+):(?P<user_id>\d+)",
):
    """Bouton de choix dans un encounter (persistent)."""

    def __init__(self, encounter_id: str, choice_idx: int, user_id: int):
        super().__init__(
            Button(
                label="…",
                style=discord.ButtonStyle.primary,
                custom_id=f"enc_choice:{encounter_id}:{choice_idx}:{user_id}",
            )
        )
        self.encounter_id = encounter_id
        self.choice_idx = choice_idx
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(
            match["encounter_id"], int(match["choice_idx"]), int(match["user_id"]),
        )

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ta propre rencontre depuis le hub.", ephemeral=True
                )
            except Exception:
                return

        try:
            await btn_i.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
            pass

        if btn_i.guild is None:
            try:
                await btn_i.followup.send("❌ Serveur uniquement.", ephemeral=True)
            except Exception:
                pass
            return

        try:
            encounter = get_encounter_def(self.encounter_id)
            if not encounter:
                await btn_i.followup.send("❌ Rencontre introuvable.", ephemeral=True)
                return

            result = await record_choice(
                btn_i.guild.id, btn_i.user.id, self.encounter_id, self.choice_idx,
            )

            if not result:
                await btn_i.followup.send(
                    "❌ Erreur lors de l'enregistrement.", ephemeral=True
                )
                return
            if result.get("already_done"):
                await btn_i.followup.send(
                    "⏳ Tu as déjà fait ta rencontre aujourd'hui. Reviens demain.",
                    ephemeral=True,
                )
                return

            view = await _build_result_panel(
                btn_i.guild.id, btn_i.user.id, result, encounter,
            )
            if view is None:
                await btn_i.followup.send(
                    f"_{result.get('reply', '…')}_\n\n"
                    f"💰 +{result['coin_reward']} 🪙",
                    ephemeral=True,
                )
                return
            try:
                await btn_i.edit_original_response(
                    view=view, content=None, attachments=[],
                )
            except Exception:
                await btn_i.followup.send(view=view, ephemeral=True)
        except Exception as ex:
            print(f"[enc_choice callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(EncounterChoiceButton)
    except Exception as ex:
        print(f"[daily_encounters register_persistent_views] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point from hub
# ═══════════════════════════════════════════════════════════════════════════

async def open_encounter_from_hub(interaction: discord.Interaction) -> None:
    """Appelé depuis le bouton 🌟 Rencontre du jour. Vérifie cooldown +
    pick encounter + send panel V2."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        pass
    except Exception as ex:
        print(f"[open_encounter_from_hub defer] {ex}")

    if interaction.guild is None:
        try:
            await interaction.followup.send("❌ Serveur uniquement.", ephemeral=True)
        except Exception:
            pass
        return

    try:
        if await has_done_today(interaction.guild.id, interaction.user.id):
            await interaction.followup.send(
                "⏳ Tu as déjà rencontré quelqu'un aujourd'hui. "
                "_Reviens demain — un autre personnage t'attend._",
                ephemeral=True,
            )
            return

        view = await build_encounter_panel(
            interaction.guild.id, interaction.user.id,
            view_user_id=interaction.user.id,
        )
        if view is None:
            await interaction.followup.send(
                "❌ Pas de rencontre disponible.", ephemeral=True
            )
            return
        await interaction.followup.send(view=view, ephemeral=True)
    except Exception as ex:
        print(f"[open_encounter_from_hub] {ex}")
        try:
            await interaction.followup.send(
                f"❌ Erreur : `{ex}`", ephemeral=True
            )
        except Exception:
            pass


__all__ = [
    "ENCOUNTER_CATALOG",
    "setup",
    "init_db",
    "get_encounter_def",
    "list_encounter_ids",
    "has_done_today",
    "pick_encounter_for_user",
    "record_choice",
    "build_encounter_panel",
    "open_encounter_from_hub",
    "EncounterChoiceButton",
    "register_persistent_views",
]
