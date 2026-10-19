"""Phase 164.3 : tests honeypot — Phase 158 config-based.

Vérifie que Phase 158 a bien viré l'auto-create et que la lecture
de la config retourne 0 par défaut (= désactivé, comportement attendu).
"""
import asyncio
import re

import pytest

import honeypot


def test_no_naked_honeypot_name_reference():
    """Phase 163.4 : plus de référence au token HONEYPOT_NAME dans le code
    actif (le bug NameError était sur cette constante inexistante)."""
    src_path = honeypot.__file__
    with open(src_path, encoding="utf-8") as f:
        content = f.read()
    # Cherche `HONEYPOT_NAME` SEULEMENT dans des lignes de code (pas commentées)
    bad_lines = []
    for lineno, line in enumerate(content.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Ignore les chaînes/docstrings simples
        # Cherche un identifiant nu HONEYPOT_NAME (pas dans une string)
        code_part = line.split("#", 1)[0]
        if re.search(r"\bHONEYPOT_NAME\b", code_part):
            bad_lines.append(f"L{lineno}: {stripped}")
    assert not bad_lines, f"HONEYPOT_NAME encore référencé : {bad_lines}"


def test_public_api_exported():
    """L'API publique Phase 158 est en place."""
    assert hasattr(honeypot, "setup")
    assert hasattr(honeypot, "init_db")
    assert hasattr(honeypot, "get_honeypot_channel_id")
    assert hasattr(honeypot, "apply_honeypot_perms")
    assert hasattr(honeypot, "on_message_hook")


def test_get_honeypot_channel_id_default_zero():
    """Sans setup() préalable (_db_get is None), retourne 0 (= désactivé)."""
    result = asyncio.run(honeypot.get_honeypot_channel_id(123456))
    assert result == 0


def test_seuls_les_roles_qui_voient_le_salon_sont_refermes(monkeypatch):
    """20/10/2026 (audit 1 #22) : un appel par role du serveur, 0,5 s chacun, avant de repondre."""
    import asyncio

    import discord

    from conftest_discord import Obj
    poses = []

    class Role(discord.Role):
        def __init__(self, rid):
            self.id = rid

        def __hash__(self):
            return self.id

        def __eq__(self, autre):
            return getattr(autre, "id", None) == self.id
    tout_le_monde, voit, neutre = Role(1), Role(2), Role(3)
    g = Obj(default_role=tout_le_monde, me=Obj(id=9), roles=[tout_le_monde, voit, neutre] + [Role(i) for i in range(10, 60)])

    async def poser(cible, **k):
        poses.append(getattr(cible, "id", None))

    async def rien(*_a):
        return None
    salon = Obj(guild=g, set_permissions=poser, overwrites={
        voit: discord.PermissionOverwrite(view_channel=True),
        neutre: discord.PermissionOverwrite(send_messages=False)})
    monkeypatch.setattr(honeypot.asyncio, "sleep", rien)
    out = asyncio.run(honeypot.apply_honeypot_perms(salon))
    assert out["success"] and poses == [1, 9, 2], poses
