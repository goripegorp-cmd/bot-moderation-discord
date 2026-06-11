"""
codex_chronicle.py — Le Codex visible par tous (Phase 170.1).

🎯 OBJECTIF : panel V2 navigable qui affiche l'état de la Chronique :
- Page 1 : Chapitre en cours (titre, prologue, progression, contributeurs top)
- Page 2 : Histoire (chapitres terminés avec leurs épilogues)
- Page 3 : Mémoires (log chronologique des événements majeurs)
- Page 4 : Les Actes (vue d'ensemble des 3 Actes et leur état)

Lecture libre par tous les membres (panel ephemeral). Le Codex est la
"mémoire collective" du serveur — fierté permanente.

API publique :
- setup(bot_instance, get_db_fn, db_get_fn, v2_helpers, story_module)
- build_codex_panel(guild_id, user_id, page='current') -> LayoutView
- CodexPageButton (DynamicItem) — navigation entre pages
- register_persistent_views(bot)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import discord
from discord.ui import Button

# ─── Config ────────────────────────────────────────────────────────────────
_bot = None
_get_db = None
_db_get = None
_v2 = None
_story = None  # référence vers story_engine module
_council = None  # référence vers weekly_council module (Phase 170.4)
_regional = None  # référence vers regional_state module (Phase 170.5)
_mystery = None  # référence vers mystery_investigation module (Phase 170.6)
_letters = None  # référence vers npc_letters module (Phase 170.7)
_climax = None  # référence vers monthly_climax module (Phase 170.8)

VALID_PAGES = ("current", "history", "memoirs", "acts", "welcome")


def setup(
    bot_instance, get_db_fn, db_get_fn, v2_helpers: dict, story_module,
    council_module=None, regional_module=None, mystery_module=None,
    letters_module=None, climax_module=None,
):
    global _bot, _get_db, _db_get, _v2, _story, _council, _regional, _mystery
    global _letters, _climax
    _bot = bot_instance
    _get_db = get_db_fn
    _db_get = db_get_fn
    _v2 = v2_helpers
    _story = story_module
    _council = council_module
    _regional = regional_module
    _mystery = mystery_module
    _letters = letters_module
    _climax = climax_module


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers de mise en forme
# ═══════════════════════════════════════════════════════════════════════════

def _progress_bar(pct: int, width: int = 20) -> str:
    pct = max(0, min(100, int(pct)))
    fill = int(width * pct / 100)
    return "█" * fill + "░" * (width - fill)


def _fmt_dt(raw) -> str:
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.strftime("%d/%m %Hh%M")
    except Exception:
        return str(raw)[:16]


def _humanize_kind(kind: str) -> str:
    return {
        "mob_kills": "Monstres vaincus",
        "quest_completes": "Quêtes complétées",
        "boss_damage": "Dégâts boss",
        "encounters": "Rencontres NPC",
        "council_votes": "Votes au Conseil",
        "regional_defenses": "Défenses régionales",
        "mystery_combines": "Indices combinés",
    }.get(kind, kind)


def _humanize_event(kind: str, payload: dict) -> str:
    """Transforme un event_kind+payload en ligne lisible pour Mémoires."""
    title = payload.get("title", "—")
    if kind == "chronicle_started":
        return f"🌅 La Chronique a commencé — *{title}*"
    if kind == "chapter_started":
        return f"📖 Nouveau chapitre — *{title}*"
    if kind == "chapter_completed":
        if payload.get("status") == "completed":
            return f"🎉 Chapitre terminé — *{title}*"
        return f"⏳ Chapitre expiré — *{title}*"
    if kind == "chapter_milestone":
        pct = payload.get("pct", "?")
        return f"📊 Milestone {pct}% atteint"
    if kind == "chronicle_completed":
        return "🌟 **La Chronique entière est terminée**"
    if kind == "council_decided":
        opt = payload.get("decided_option", "—")
        return f"🗳️ Conseil tranché — voie *{opt}*"
    if kind == "boss_defeated":
        return f"⚔️ Boss vaincu — *{title}*"
    if kind == "region_fallen":
        rg = payload.get("region", "?")
        return f"🚨 Région tombée — *{rg}*"
    if kind == "region_reclaimed":
        rg = payload.get("region", "?")
        return f"🛡️ Région reconquise — *{rg}*"
    if kind == "mystery_combined":
        return f"🔮 Indices combinés — un nouveau fragment révélé"
    return f"📜 {kind} — {title}"


# ═══════════════════════════════════════════════════════════════════════════
#  Build des pages
# ═══════════════════════════════════════════════════════════════════════════

async def _build_page_current(guild_id: int) -> list:
    """Page 1 : Chapitre en cours."""
    if _story is None or _v2 is None:
        return []
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']

    state = await _story.get_state(guild_id)
    items = [v2_title("📖 La Chronique d'Abylumis")]
    if not state:
        items.append(v2_body("_La Chronique n'a pas encore commencé._"))
        return items

    items.append(v2_subtitle(
        f"**Acte {state['act']} — {state['act_title']}**\n"
        f"_{state['act_subtitle']}_"
    ))
    items.append(v2_divider())
    items.append(v2_body(
        f"**Chapitre {state['chapter_id']} — *{state['chapter_title']}***\n\n"
        f"_{state['chapter_prologue']}_"
    ))
    items.append(v2_divider())

    bar = _progress_bar(state['progress_pct'])
    items.append(v2_body(
        f"🎯 **{_humanize_kind(state['kind'])}**\n"
        f"`{bar}` `{state['current']:,} / {state['target']:,}`  "
        f"({state['progress_pct']} %)"
    ))

    # Top contributeurs (anonymisés top 3)
    try:
        top = await _story.get_top_contributors(
            guild_id, state['act'], state['chapter_idx'], limit=3,
        )
    except Exception:
        top = []
    if top:
        items.append(v2_divider())
        lines = ["**🏅 Top 3 contributeurs (anonyme)**"]
        for i, (_, count) in enumerate(top):
            medal = ["🥇", "🥈", "🥉"][i]
            lines.append(f"{medal} `{count:,}` actions")
        items.append(v2_body("\n".join(lines)))

    items.append(v2_divider())
    reward_parts = []
    if state.get("reward_coins"):
        reward_parts.append(f"💰 `{state['reward_coins']}` 🪙 par contributeur")
    if state.get("reward_title"):
        reward_parts.append(f"🏅 Titre : **{state['reward_title']}**")
    if reward_parts:
        items.append(v2_body(
            "**🎁 Récompenses du chapitre :**\n" + "\n".join(reward_parts)
        ))

    items.append(v2_body(
        f"_⏱️ Chapitre démarré le {_fmt_dt(state['chapter_started'])}._\n"
        f"_Si pas complété en 60 jours, l'histoire continue quand même._"
    ))

    # Phase 170.4 : si un conseil hebdo est actif, on l'affiche
    if _council is not None:
        try:
            active = await _council.get_active_council(guild_id)
            if active:
                council_def = _council.get_council_def(active["council_id"])
                if council_def:
                    items.append(v2_divider())
                    items.append(v2_body(
                        f"🗳️ **Conseil actif — *{council_def['title']}***\n"
                        f"_{council_def['question']}_\n"
                        f"`{active['total_votes']}` voix · ferme `{active['closes_at']}`"
                    ))
        except Exception:
            pass

    # Phase 170.8 : si un Boss Climax est actif, gros warning
    if _climax is not None:
        try:
            active_climax = await _climax.get_active_climax(guild_id)
            if active_climax:
                boss = _climax.get_climax_boss_by_id(active_climax["boss_id"]) or {}
                pct = int(active_climax["hp_current"] * 100
                          / max(1, active_climax["hp_max"]))
                items.append(v2_divider())
                items.append(v2_body(
                    f"⚔️ **Boss climax actif**\n"
                    f"{boss.get('emoji', '?')} **{boss.get('name', '?')}**\n"
                    f"HP `{active_climax['hp_current']:,}/{active_climax['hp_max']:,}` "
                    f"({pct}%)"
                ))
        except Exception:
            pass

    # Phase 170.5 : si une patrouille est active, alerte
    if _regional is not None:
        try:
            patrol = await _regional.get_active_patrol(guild_id)
            if patrol:
                region = _regional.get_region_def(patrol["region_id"]) or {}
                reclaim = " (reconquête)" if patrol["is_reclaim"] else ""
                pct = int(patrol["defense_total"] * 100 / max(1, patrol["target"]))
                items.append(v2_divider())
                items.append(v2_body(
                    f"🚨 **Patrouille active{reclaim}**\n"
                    f"{region.get('emoji', '?')} **{region.get('name', '?')}** est menacée.\n"
                    f"Défense `{patrol['defense_total']}/{patrol['target']}` ({pct}%)"
                ))

            # Debuff serveur
            debuff = await _regional.get_server_debuff(guild_id)
            if debuff["fallen_count"] > 0:
                items.append(v2_body(
                    f"⚠️ **{debuff['fallen_count']} région(s) tombée(s)** "
                    f"— Debuff serveur : {debuff['loot_penalty_pct']:+d}% loot."
                ))
        except Exception:
            pass

    return items


async def _build_page_history(guild_id: int) -> list:
    """Page 2 : Histoire — tous les chapitres déjà terminés."""
    if _story is None or _v2 is None or _get_db is None:
        return []
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    items = [v2_title("📚 Histoire")]

    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT act, chapter, current, target, status, completed_at "
                "FROM chronicle_chapter_progress "
                "WHERE guild_id=? AND status!='in_progress' "
                "ORDER BY id ASC",
                (guild_id,),
            ) as cur:
                rows = await cur.fetchall()
    except Exception:
        rows = []

    if not rows:
        items.append(v2_body("_Aucun chapitre n'est encore terminé._"))
        return items

    for row in rows:
        act, chap_idx, current, target, status, completed_at = row
        chap_def = _story.get_chapter_def(int(act), int(chap_idx))
        if not chap_def:
            continue
        icon = "🎉" if status == "completed" else "⏳"
        items.append(v2_body(
            f"{icon} **{chap_def['id']} — {chap_def['title']}**\n"
            f"_{chap_def['epilogue']}_\n"
            f"`{int(current):,}/{int(target):,}` · Fini le {_fmt_dt(completed_at)}"
        ))
        items.append(v2_divider())
    return items


async def _build_page_memoirs(guild_id: int) -> list:
    """Page 3 : Mémoires — log chronologique récent."""
    if _story is None or _v2 is None:
        return []
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']

    items = [v2_title("📜 Mémoires des Cendres")]
    items.append(v2_body(
        "_Les 30 dernières pages de l'histoire du serveur._"
    ))
    items.append(v2_divider())

    try:
        events = await _story.get_recent_events(guild_id, limit=30)
    except Exception:
        events = []

    if not events:
        items.append(v2_body("_Aucun événement enregistré._"))
        return items

    lines = []
    for ev in events:
        line = _humanize_event(ev["kind"], ev["payload"])
        ts = _fmt_dt(ev["timestamp"])
        lines.append(f"`{ts}` · {line}")
    items.append(v2_body("\n".join(lines)))
    return items


async def _build_page_welcome(guild_id: int) -> list:
    """Page 5 (Phase 171) : Bienvenue — résumé pour nouveaux membres.

    Conçue pour quelqu'un qui rejoint le serveur mid-Chronicle et qui ne
    sait pas ce qui s'est passé. Donne un résumé concis du voyage.
    """
    if _story is None or _v2 is None:
        return []
    v2_title = _v2['v2_title']
    v2_subtitle = _v2['v2_subtitle']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']

    items = [
        v2_title("🌟 Bienvenue dans la Chronique"),
        v2_subtitle(
            "_Tout ce qu'il faut savoir en 1 minute._"
        ),
        v2_divider(),
    ]

    state = await _story.get_state(guild_id)
    current_act = state["act"] if state else 1
    current_chap_id = state["chapter_id"] if state else "1.1"

    items.append(v2_body(
        "**📖 C'est quoi, la Chronique d'Abylumis ?**\n\n"
        "_Une histoire collective qui se déroule sur **9 mois**. Le serveur "
        "entier collabore pour avancer dans 3 Actes de 3 chapitres chacun. "
        "Aucune action n'est obligatoire : tes actions habituelles (combat, "
        "quêtes, rencontres) alimentent automatiquement l'histoire._"
    ))
    items.append(v2_divider())

    items.append(v2_body(
        "**🎭 Où en est le serveur ?**\n\n"
        f"Actuellement : **Acte {current_act}**, chapitre **{current_chap_id}**."
    ))
    items.append(v2_divider())

    # Mini-récap des chapitres terminés
    completed = []
    if _get_db is not None:
        try:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT act, chapter, status FROM chronicle_chapter_progress "
                    "WHERE guild_id=? AND status='completed' "
                    "ORDER BY id ASC",
                    (guild_id,),
                ) as cur:
                    for r in await cur.fetchall():
                        chap_def = _story.get_chapter_def(int(r[0]), int(r[1]))
                        if chap_def:
                            completed.append(chap_def["title"])
        except Exception:
            pass

    if completed:
        items.append(v2_body(
            f"**📚 Ce que le serveur a déjà accompli ({len(completed)} chapitres) :**\n\n"
            + "\n".join(f"✅ {t}" for t in completed)
        ))
        items.append(v2_divider())

    items.append(v2_body(
        "**🎯 Comment participer ?**\n\n"
        "• 🌟 **Chaque jour** : clique « Rencontre du jour » dans le hub "
        "(5 min de narration avec un NPC)\n"
        "• 🗳️ **Chaque lundi 20h** : vote au Conseil des Anciens\n"
        "• 🚨 **Chaque mercredi 19h** : défends une région en patrouille\n"
        "• ⚔️ **1er samedi du mois 21h** : Boss Climax — récompense titre permanent\n"
        "• ✉️ **Optionnel** : abonne-toi aux lettres NPC en DM"
    ))
    items.append(v2_divider())

    items.append(v2_body(
        "**🤝 Les 6 personnages que tu vas croiser :**\n\n"
        "🌙 **Aria** la Veilleuse — sage, prudente\n"
        "🔨 **Korr** le Forgeron — loyal, simple\n"
        "📚 **Lyra** l'Érudite — curieuse, ambiguë\n"
        "⚔️ **Drazek** le Guerrier — impulsif, courageux\n"
        "💰 **Sienna** la Marchande — neutre, calculatrice\n"
        "🌫️ **Le Voyageur** — mystérieux"
    ))
    items.append(v2_divider())

    items.append(v2_body(
        "_💡 La Chronique est conçue pour durer 9 mois. Aucune urgence : "
        "même 5 minutes par jour suffisent pour vivre l'histoire pleinement._"
    ))

    return items


async def _build_page_acts(guild_id: int) -> list:
    """Page 4 : Les 3 Actes — vue d'ensemble."""
    if _story is None or _v2 is None:
        return []
    v2_title = _v2['v2_title']
    v2_body = _v2['v2_body']
    v2_divider = _v2['v2_divider']
    v2_subtitle = _v2['v2_subtitle']

    items = [v2_title("🎭 Les trois Actes")]
    items.append(v2_subtitle(
        "_9 chapitres sur 9 mois. Chaque Acte change le monde._"
    ))
    items.append(v2_divider())

    state = await _story.get_state(guild_id)
    current_act = state["act"] if state else 1
    current_chap = state["chapter_idx"] if state else 0

    for act in _story.ACTS:
        lines = [f"**Acte {act['id']} — {act['title']}**"]
        lines.append(f"_{act['subtitle']}_\n")
        for i, chap in enumerate(act["chapters"]):
            if act["id"] < current_act:
                status_icon = "✅"
            elif act["id"] == current_act:
                if i < current_chap:
                    status_icon = "✅"
                elif i == current_chap:
                    status_icon = "📖"
                else:
                    status_icon = "🔒"
            else:
                status_icon = "🔒"
            lines.append(f"  {status_icon} **{chap['id']}** {chap['title']}")
        items.append(v2_body("\n".join(lines)))
        items.append(v2_divider())
    return items


# ═══════════════════════════════════════════════════════════════════════════
#  LayoutView du Codex
# ═══════════════════════════════════════════════════════════════════════════

async def build_codex_panel(
    guild_id: int, user_id: int, page: str = "current",
) -> Optional[discord.ui.LayoutView]:
    """Construit le panel Codex pour la page demandée."""
    if _v2 is None:
        return None
    if page not in VALID_PAGES:
        page = "current"

    LayoutView = _v2['LayoutView']
    v2_container = _v2['v2_container']
    v2_divider = _v2['v2_divider']
    v2_body = _v2['v2_body']

    if page == "current":
        items = await _build_page_current(guild_id)
    elif page == "history":
        items = await _build_page_history(guild_id)
    elif page == "memoirs":
        items = await _build_page_memoirs(guild_id)
    elif page == "welcome":
        items = await _build_page_welcome(guild_id)
    else:  # acts
        items = await _build_page_acts(guild_id)

    if not items:
        items = [v2_body("_Codex indisponible._")]

    class _CodexLayout(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x8B4513))

    layout = _CodexLayout()

    # Phase 208 FIX : tous les boutons doivent vivre dans des ActionRow (type 1).
    # Un Button/DynamicItem brut au top-level d'un LayoutView V2 = 400 "Invalid
    # Form Body". On collecte des Button BRUTS (un DynamicItem ne peut pas aller
    # dans un ActionRow) avec le MÊME custom_id que chaque DynamicItem ; le clic
    # reste capté par le DynamicItem enregistré (match du custom_id).
    nav_buttons: list[Button] = []

    # 5 boutons de navigation (Phase 171 : ajout Welcome pour nouveaux membres)
    btn_defs = [
        ("welcome", "🌟 Bienvenue", discord.ButtonStyle.success),
        ("current", "📖 Chapitre", discord.ButtonStyle.primary),
        ("history", "📚 Histoire", discord.ButtonStyle.secondary),
        ("memoirs", "📜 Mémoires", discord.ButtonStyle.secondary),
        ("acts", "🎭 Actes", discord.ButtonStyle.secondary),
    ]
    for pkey, label, style in btn_defs:
        if pkey == page:
            # Bouton de la page active : désactivé visuellement
            btn = Button(
                label=label,
                style=discord.ButtonStyle.success,
                custom_id=f"codex_nav:{pkey}:{user_id}",
                disabled=True,
            )
        else:
            # Équivalent brut de CodexPageButton (même label/style/custom_id).
            btn = Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"codex_nav:{pkey}:{user_id}",
            )
        nav_buttons.append(btn)

    # Phase 170.4 : 5e bouton "🗳️ Conseil" si un conseil est actif
    if _council is not None:
        try:
            active = await _council.get_active_council(guild_id)
            if active:
                nav_buttons.append(Button(
                    label="🗳️ Conseil",
                    style=discord.ButtonStyle.danger,
                    custom_id=f"codex_council:{user_id}",
                ))
        except Exception:
            pass

    # Phase 170.5 : bouton "🌍 Régions" (toujours accessible)
    if _regional is not None:
        try:
            nav_buttons.append(Button(
                label="🌍 Régions",
                style=discord.ButtonStyle.success,
                custom_id=f"codex_regions:{user_id}",
            ))
        except Exception:
            pass

    # Phase 170.6 : bouton "🔮 Mystères" (toujours accessible)
    if _mystery is not None:
        try:
            nav_buttons.append(Button(
                label="🔮 Mystères",
                style=discord.ButtonStyle.primary,
                custom_id=f"codex_mystery:{user_id}",
            ))
        except Exception:
            pass

    # Phase 170.7 : bouton "✉️ Lettres NPCs" (opt-in DM)
    if _letters is not None:
        try:
            nav_buttons.append(Button(
                label="✉️ Lettres",
                style=discord.ButtonStyle.secondary,
                custom_id=f"codex_letters:{user_id}",
            ))
        except Exception:
            pass

    # Phase 170.8 : bouton "⚔️ Boss" (toujours visible, affiche titres si pas de boss)
    if _climax is not None:
        try:
            nav_buttons.append(Button(
                label="⚔️ Boss",
                style=discord.ButtonStyle.danger,
                custom_id=f"codex_climax:{user_id}",
            ))
        except Exception:
            pass

    # Phase 208 FIX : regrouper en ActionRows de 5 boutons max (Discord cap).
    for i in range(0, len(nav_buttons), 5):
        layout.add_item(discord.ui.ActionRow(*nav_buttons[i:i + 5]))

    return layout


# ═══════════════════════════════════════════════════════════════════════════
#  Persistent navigation button
# ═══════════════════════════════════════════════════════════════════════════

class CodexPageButton(
    discord.ui.DynamicItem[Button],
    template=r"codex_nav:(?P<page>\w+):(?P<user_id>\d+)",
):
    """Bouton de navigation entre pages du Codex (persistent)."""

    def __init__(self, page: str, user_id: int):
        super().__init__(
            Button(
                label={
                    "welcome": "🌟 Bienvenue",
                    "current": "📖 Chapitre",
                    "history": "📚 Histoire",
                    "memoirs": "📜 Mémoires",
                    "acts": "🎭 Actes",
                }.get(page, page),
                style=discord.ButtonStyle.secondary,
                custom_id=f"codex_nav:{page}:{user_id}",
            )
        )
        self.page = page
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["page"], int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        # Garde-fou : seul le user qui a ouvert le Codex peut naviguer
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Codex depuis le hub.", ephemeral=True
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
            view = await build_codex_panel(
                btn_i.guild.id, self.user_id, page=self.page,
            )
            if view is None:
                await btn_i.followup.send("❌ Codex indisponible.", ephemeral=True)
                return
            try:
                await btn_i.edit_original_response(view=view, content=None, attachments=[])
            except Exception:
                await btn_i.followup.send(view=view, ephemeral=True)
        except Exception as ex:
            print(f"[codex_nav callback] {ex}")
            try:
                await btn_i.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
            except Exception:
                pass


class CodexCouncilButton(
    discord.ui.DynamicItem[Button],
    template=r"codex_council:(?P<user_id>\d+)",
):
    """Bouton qui ouvre le Conseil actif (Phase 170.4)."""

    def __init__(self, user_id: int):
        super().__init__(
            Button(
                label="🗳️ Conseil",
                style=discord.ButtonStyle.danger,
                custom_id=f"codex_council:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Codex depuis le hub.", ephemeral=True
                )
            except Exception:
                return
        if _council is None:
            try:
                return await btn_i.response.send_message(
                    "❌ Conseil indisponible.", ephemeral=True
                )
            except Exception:
                return
        try:
            await _council.open_council_from_codex(btn_i)
        except Exception as ex:
            print(f"[codex_council callback] {ex}")
            try:
                if not btn_i.response.is_done():
                    await btn_i.response.send_message(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
                else:
                    await btn_i.followup.send(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
            except Exception:
                pass


class CodexRegionsButton(
    discord.ui.DynamicItem[Button],
    template=r"codex_regions:(?P<user_id>\d+)",
):
    """Bouton qui ouvre le panel des Régions (Phase 170.5)."""

    def __init__(self, user_id: int):
        super().__init__(
            Button(
                label="🌍 Régions",
                style=discord.ButtonStyle.success,
                custom_id=f"codex_regions:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Codex depuis le hub.", ephemeral=True
                )
            except Exception:
                return
        if _regional is None:
            try:
                return await btn_i.response.send_message(
                    "❌ Régions indisponibles.", ephemeral=True
                )
            except Exception:
                return
        try:
            await _regional.open_regions_from_codex(btn_i)
        except Exception as ex:
            print(f"[codex_regions callback] {ex}")
            try:
                if not btn_i.response.is_done():
                    await btn_i.response.send_message(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
                else:
                    await btn_i.followup.send(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
            except Exception:
                pass


class CodexMysteryButton(
    discord.ui.DynamicItem[Button],
    template=r"codex_mystery:(?P<user_id>\d+)",
):
    """Bouton qui ouvre le panel des Mystères (Phase 170.6)."""

    def __init__(self, user_id: int):
        super().__init__(
            Button(
                label="🔮 Mystères",
                style=discord.ButtonStyle.primary,
                custom_id=f"codex_mystery:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Codex depuis le hub.", ephemeral=True
                )
            except Exception:
                return
        if _mystery is None:
            try:
                return await btn_i.response.send_message(
                    "❌ Mystères indisponibles.", ephemeral=True
                )
            except Exception:
                return
        try:
            await _mystery.open_mysteries_from_codex(btn_i)
        except Exception as ex:
            print(f"[codex_mystery callback] {ex}")
            try:
                if not btn_i.response.is_done():
                    await btn_i.response.send_message(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
                else:
                    await btn_i.followup.send(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
            except Exception:
                pass


class CodexLettersButton(
    discord.ui.DynamicItem[Button],
    template=r"codex_letters:(?P<user_id>\d+)",
):
    """Bouton qui ouvre le panel Lettres (Phase 170.7)."""

    def __init__(self, user_id: int):
        super().__init__(
            Button(
                label="✉️ Lettres",
                style=discord.ButtonStyle.secondary,
                custom_id=f"codex_letters:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Codex depuis le hub.", ephemeral=True
                )
            except Exception:
                return
        if _letters is None:
            try:
                return await btn_i.response.send_message(
                    "❌ Lettres indisponibles.", ephemeral=True
                )
            except Exception:
                return
        try:
            await _letters.open_letters_from_codex(btn_i)
        except Exception as ex:
            print(f"[codex_letters callback] {ex}")
            try:
                if not btn_i.response.is_done():
                    await btn_i.response.send_message(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
                else:
                    await btn_i.followup.send(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
            except Exception:
                pass


class CodexClimaxButton(
    discord.ui.DynamicItem[Button],
    template=r"codex_climax:(?P<user_id>\d+)",
):
    """Bouton qui ouvre le panel Boss Climax (Phase 170.8)."""

    def __init__(self, user_id: int):
        super().__init__(
            Button(
                label="⚔️ Boss",
                style=discord.ButtonStyle.danger,
                custom_id=f"codex_climax:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["user_id"]))

    async def callback(self, btn_i: discord.Interaction):
        if btn_i.user.id != self.user_id:
            try:
                return await btn_i.response.send_message(
                    "🔒 Ouvre ton propre Codex depuis le hub.", ephemeral=True
                )
            except Exception:
                return
        if _climax is None:
            try:
                return await btn_i.response.send_message(
                    "❌ Boss indisponible.", ephemeral=True
                )
            except Exception:
                return
        try:
            await _climax.open_climax_from_codex(btn_i)
        except Exception as ex:
            print(f"[codex_climax callback] {ex}")
            try:
                if not btn_i.response.is_done():
                    await btn_i.response.send_message(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
                else:
                    await btn_i.followup.send(
                        f"❌ Erreur : `{ex}`", ephemeral=True
                    )
            except Exception:
                pass


def register_persistent_views(bot_instance):
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(CodexPageButton)
        bot_instance.add_dynamic_items(CodexCouncilButton)
        bot_instance.add_dynamic_items(CodexRegionsButton)
        bot_instance.add_dynamic_items(CodexMysteryButton)
        bot_instance.add_dynamic_items(CodexLettersButton)
        bot_instance.add_dynamic_items(CodexClimaxButton)
    except Exception as ex:
        print(f"[codex_chronicle register_persistent_views] {ex}")


# ═══════════════════════════════════════════════════════════════════════════
#  Entry point depuis le hub
# ═══════════════════════════════════════════════════════════════════════════

async def open_codex_from_hub(interaction: discord.Interaction) -> None:
    """Appelé depuis le bouton 📖 Codex du hub. Defer + build + send."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except (discord.NotFound, discord.HTTPException, discord.InteractionResponded):
        pass
    except Exception as ex:
        print(f"[open_codex_from_hub defer] {ex}")

    if interaction.guild is None:
        try:
            await interaction.followup.send("❌ Serveur uniquement.", ephemeral=True)
        except Exception:
            pass
        return

    try:
        view = await build_codex_panel(
            interaction.guild.id, interaction.user.id, page="current",
        )
        if view is None:
            await interaction.followup.send("❌ Codex indisponible.", ephemeral=True)
            return
        await interaction.followup.send(view=view, ephemeral=True)
    except Exception as ex:
        print(f"[open_codex_from_hub] {ex}")
        try:
            await interaction.followup.send(f"❌ Erreur : `{ex}`", ephemeral=True)
        except Exception:
            pass


__all__ = [
    "setup",
    "build_codex_panel",
    "open_codex_from_hub",
    "CodexPageButton",
    "register_persistent_views",
    "VALID_PAGES",
]
