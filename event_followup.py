"""
event_followup.py — Boutons de suivi après événements (Phase 146).

🎯 OBJECTIF CENTRAL : les utilisateurs ne connaissent PAS les commandes.
Ils utilisent les boutons. Après chaque event (boss, daily, treasure, etc.),
le bot leur propose 3-4 boutons qui ouvrent les panels pertinents — zéro
commande à mémoriser.

EXEMPLE pratique :
  Boss Raid victoire → "✅ Tu as gagné 200 coins !" + panel V2 avec 3 boutons :
    [🏅 Mes paliers]  [🌸 Drops saison]  [🎯 Mes quêtes]
  L'utilisateur clique → s'ouvre en ephemeral → il découvre les features.

Architecture :
- Les modules existants enregistrent leurs handlers via register_handler()
- Quand un event finit, le bot appelle build_followup_view(owner_id, "boss_raid")
- La View attache automatiquement 3-4 boutons selon l'event_kind
- Chaque bouton ouvre une commande/panel sans que l'user le sache

API publique :
- setup() — vide, juste pour cohérence
- register_handler(event_kind, label, emoji, callback_async)
- build_followup_view(owner_id, event_kind) -> View | None
- build_followup_panel(owner_id, event_kind, summary_text) -> LayoutView

⚠️ RULES.md : zéro relationnel. Les boutons orientent vers du gameplay /
gestion uniquement.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import discord
from discord.ui import View, Button


# Type : callback async qui reçoit l'interaction
HandlerCallback = Callable[[discord.Interaction], Awaitable[None]]


# ─── Registry des handlers par event_kind ──────────────────────────────────
# Chaque event_kind a une liste de tuples (label, emoji, style, callback)
# Max 4 boutons par event (Discord ActionRow limite + UX)
_handlers: dict[str, list[tuple[str, str, discord.ButtonStyle, HandlerCallback]]] = {}
_v2_helpers = None


def setup(v2_helpers: dict):
    """Configure le module (panels V2)."""
    global _v2_helpers
    _v2_helpers = v2_helpers


def register_handler(
    event_kind: str,
    label: str,
    emoji: str,
    callback: HandlerCallback,
    style: discord.ButtonStyle = discord.ButtonStyle.primary,
):
    """Enregistre un bouton de suivi pour un type d'event.

    Args:
        event_kind : "boss_raid", "world_boss", "daily", "treasure",
                     "duel_win", "quiz_win", "wheel_spin", "generic", etc.
        label      : Texte du bouton (max ~20 chars)
        emoji      : Emoji de tête
        callback   : Coroutine qui reçoit l'interaction et ouvre le panel
        style      : Style Discord du bouton
    """
    if event_kind not in _handlers:
        _handlers[event_kind] = []
    _handlers[event_kind].append((label, emoji, style, callback))


def _get_handlers(event_kind: str) -> list:
    """Récupère les handlers pour un event_kind, fallback sur 'generic'."""
    if event_kind in _handlers:
        return _handlers[event_kind][:4]  # max 4 boutons
    return _handlers.get("generic", [])[:4]


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD VIEW — version simple (juste boutons, à attacher à n'importe quel message)
# ═══════════════════════════════════════════════════════════════════════════════

def build_followup_view(
    owner_id: int, event_kind: str
) -> Optional[View]:
    """Construit une View avec 3-4 boutons de suivi.

    Le View vérifie owner_id : seul l'utilisateur qui a gagné l'event
    peut cliquer sur ses propres boutons.

    Retourne None si aucun handler enregistré pour cet event_kind.
    """
    handlers = _get_handlers(event_kind)
    if not handlers:
        return None

    class _FollowupView(View):
        def __init__(self):
            super().__init__(timeout=300)
            for label, emoji, style, cb in handlers:
                btn = Button(label=label, emoji=emoji, style=style)
                btn.callback = self._wrap(cb)
                self.add_item(btn)

        async def interaction_check(
            self, interaction: discord.Interaction
        ) -> bool:
            return interaction.user.id == owner_id

        def _wrap(self, cb: HandlerCallback):
            async def _handler(i: discord.Interaction):
                try:
                    await cb(i)
                except Exception as ex:
                    print(f"[event_followup callback {event_kind}] {ex}")
                    try:
                        if not i.response.is_done():
                            await i.response.send_message(
                                f"❌ Erreur : `{ex}`", ephemeral=True
                            )
                    except Exception:
                        pass
            return _handler

    return _FollowupView()


# ═══════════════════════════════════════════════════════════════════════════════
# BUILD PANEL V2 — version complète avec texte + boutons (LayoutView)
# ═══════════════════════════════════════════════════════════════════════════════

def build_followup_panel(
    owner_id: int, event_kind: str, summary_text: str,
    title: str = "🎉  Bien joué !", color: int = 0xFFD700,
):
    """LayoutView V2 complet : texte de résumé + boutons cliquables.

    Args:
        owner_id      : ID du membre qui a gagné l'event
        event_kind    : type d'event (pour choisir les boutons)
        summary_text  : texte affiché (ex: "Tu as gagné 200 coins")
        title         : titre du panel
        color         : couleur d'accent
    """
    if _v2_helpers is None:
        return None

    LayoutView = _v2_helpers['LayoutView']
    v2_title = _v2_helpers['v2_title']
    v2_subtitle = _v2_helpers['v2_subtitle']
    v2_body = _v2_helpers['v2_body']
    v2_divider = _v2_helpers['v2_divider']
    v2_container = _v2_helpers['v2_container']

    handlers = _get_handlers(event_kind)

    class _FollowupPanel(LayoutView):
        def __init__(self):
            super().__init__(timeout=300)
            items = []
            items.append(v2_title(title))
            items.append(v2_body(summary_text))

            if handlers:
                items.append(v2_divider())
                items.append(v2_body(
                    "_💡 Continue ton aventure — clique sur un bouton :_"
                ))

            # Container avec le texte
            self.add_item(v2_container(*items, color=color))

            # Boutons en ActionRow séparé (LayoutView le supporte)
            if handlers:
                row = discord.ui.ActionRow()
                for label, emoji, style, cb in handlers:
                    btn = Button(label=label, emoji=emoji, style=style)
                    btn.callback = self._wrap(cb)
                    row.add_item(btn)
                try:
                    self.add_item(row)
                except Exception:
                    # Fallback : ajouter chaque bouton directement
                    for label, emoji, style, cb in handlers:
                        btn = Button(label=label, emoji=emoji, style=style)
                        btn.callback = self._wrap(cb)
                        try:
                            self.add_item(btn)
                        except Exception:
                            pass

        async def interaction_check(
            self, interaction: discord.Interaction
        ) -> bool:
            return interaction.user.id == owner_id

        def _wrap(self, cb: HandlerCallback):
            async def _handler(i: discord.Interaction):
                try:
                    await cb(i)
                except Exception as ex:
                    print(f"[event_followup panel cb {event_kind}] {ex}")
                    try:
                        if not i.response.is_done():
                            await i.response.send_message(
                                f"❌ Erreur : `{ex}`", ephemeral=True
                            )
                    except Exception:
                        pass
            return _handler

    return _FollowupPanel()


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER PRATIQUE — attach à une réponse existante après un event
# ═══════════════════════════════════════════════════════════════════════════════

async def followup_send(
    channel: discord.TextChannel,
    member: discord.Member,
    event_kind: str,
    summary_text: str,
    title: str = "🎉  Bien joué !",
    color: int = 0xFFD700,
    delete_after: Optional[int] = 180,
) -> Optional[discord.Message]:
    """Envoie un panel followup dans un salon, auto-delete après 3 min par défaut.

    À call depuis n'importe quel handler d'event après la victoire :
      await event_followup.followup_send(
          msg.channel, winner_member, "boss_raid",
          "✅ Tu as porté le coup final ! +1000 coins"
      )

    Retourne le message envoyé (ou None si échec).
    """
    if not channel or not member:
        return None
    try:
        panel = build_followup_panel(
            member.id, event_kind, summary_text,
            title=title, color=color,
        )
        if panel is None:
            # Fallback texte
            try:
                msg = await channel.send(content=summary_text)
                return msg
            except Exception:
                return None
        try:
            msg = await channel.send(view=panel)
            if delete_after and delete_after > 0:
                try:
                    await msg.delete(delay=delete_after)
                except Exception:
                    pass
            return msg
        except Exception as ex:
            print(f"[event_followup followup_send] {ex}")
            return None
    except Exception as ex:
        print(f"[event_followup followup_send outer] {ex}")
        return None


__all__ = [
    "setup",
    "register_handler",
    "build_followup_view",
    "build_followup_panel",
    "followup_send",
    "HandlerCallback",
]
