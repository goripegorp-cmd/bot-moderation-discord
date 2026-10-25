"""Les boutons persistants (DynamicItem) ne disparaissent plus quand une vue temporaire expire.

25/10/2026 — constaté dans discord.py 2.7.1 (`discord/ui/view.py`) : `ViewStore.add_view` inscrit au registre
global le gabarit de chaque DynamicItem que contient une vue, et `ViewStore.remove_view` — appelé quand cette vue
expire (timeout) ou s'arrête (`stop()`) — RETIRE ces gabarits du registre global. Une seule vue temporaire qui
contenait, par exemple, le bouton « Participer » d'un cadeau ou la cloche des notifications suffisait donc à rendre
TOUS les boutons de ce type muets sur le serveur (« L'interaction a échoué », sans la moindre erreur au journal :
l'interaction n'est même plus aiguillée) jusqu'au redémarrage suivant.

`garder()` (appelé une fois, avant la création du bot) retient chaque bouton inscrit par `add_dynamic_items` — ceux
du démarrage — et les remet aussitôt après chaque `add_view`/`remove_view`. Un retrait volontaire
(`remove_dynamic_items`) reste possible.
"""
from __future__ import annotations

import discord.ui.view as _vue

PERSISTANTS: dict = {}          # gabarit compilé → classe DynamicItem inscrite au démarrage
_GARDE = "_persistants_gardes"


def _remettre(store) -> None:
    registre = getattr(store, "_dynamic_items", None)
    if registre is None:
        return
    for motif, classe in PERSISTANTS.items():
        registre.setdefault(motif, classe)


def garder() -> bool:
    """Installe la garde (une seule fois). Rend True si elle vient d'être installée."""
    store = _vue.ViewStore
    if getattr(store, _GARDE, False):
        return False
    ajouter, retirer = store.add_dynamic_items, store.remove_dynamic_items
    ajouter_vue, retirer_vue = store.add_view, store.remove_view

    def add_dynamic_items(self, *items):
        for item in items:
            PERSISTANTS[item.__discord_ui_compiled_template__] = item
        return ajouter(self, *items)

    def remove_dynamic_items(self, *items):
        for item in items:
            PERSISTANTS.pop(item.__discord_ui_compiled_template__, None)
        return retirer(self, *items)

    def add_view(self, view, message_id=None):
        try:
            return ajouter_vue(self, view, message_id)
        finally:
            _remettre(self)

    def remove_view(self, view):
        try:
            return retirer_vue(self, view)
        finally:
            _remettre(self)

    store.add_dynamic_items = add_dynamic_items
    store.remove_dynamic_items = remove_dynamic_items
    store.add_view = add_view
    store.remove_view = remove_view
    setattr(store, _GARDE, True)
    return True
