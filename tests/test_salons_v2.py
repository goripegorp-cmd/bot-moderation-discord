"""19/10/2026 : le récapitulatif des salons du fondateur — Information et Sneak Peek en lecture
seule, chat ouvert, suggestions au bouton, aide refait, Join pour tous (le staff déplace), Live /
Vidéo / 3 frères / GoRPC / Taverne visibles mais fermés, GoRp_SEA au clan et au staff."""
from __future__ import annotations

import ast
from pathlib import Path

import discord

import config_salons as C
from conftest_discord import Obj

ARBRE = ast.parse((Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8"))
T, V, K = discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.category


class Cible:
    def __init__(self, cid, nom, position=0):
        self.id, self.name, self.position = cid, nom, position

    def __hash__(self):
        return self.id

    def __eq__(self, autre):
        return getattr(autre, "id", None) == self.id


class Salon:
    def __init__(self, sid, nom, type_, categorie=None, ows=None):
        self.id, self.name, self.type, self.category = sid, nom, type_, categorie
        self.overwrites = dict(ows or {})

    def overwrites_for(self, cible):
        o = self.overwrites.get(cible)
        return discord.PermissionOverwrite(**dict(o)) if o is not None else discord.PermissionOverwrite()


def _serveur(bot_admin=False):
    tous, clan, staff, direction = Cible(1, "@everyone"), Cible(50, "Rell Seas", 3), Cible(10, "Staff", 5), Cible(11, "Direction", 8)
    me = Obj(id=999, roles=[], guild_permissions=Obj(administrator=bot_admin))
    info, sneak = Salon(100, "📌 Information", K), Salon(200, "👀 Sneak Peek", K)
    commu, vocaux, gorp = Salon(300, "Communauté", K), Salon(400, "🔊 Vocaux", K), Salon(500, "🏴‍☠️ GoRp_SEA", K)
    salons = [info, sneak, commu, vocaux, gorp,
              Salon(101, "📢・annonce", T, info), Salon(102, "target-roblox", T, info), Salon(103, "ticket", T, info),
              Salon(104, "📊sondages", T, info),
              Salon(201, "sneak-news-roblox", T, sneak),
              Salon(301, "💬・chat", T, commu, {tous: discord.PermissionOverwrite(attach_files=False)}),
              Salon(302, "💡suggestions", T, commu), Salon(303, "❓・aide", T, commu), Salon(304, "🆘・entraide", T, commu),
              Salon(305, "📋logs", T, commu), Salon(306, "général-staff", T, commu),
              Salon(401, "➕ Join", V, vocaux), Salon(402, "🔴 Live", V, vocaux), Salon(403, "3 frères", V, vocaux),
              Salon(404, "Discussion", V, vocaux),
              Salon(501, "info-gorp", T, gorp), Salon(502, "chat-gorpsea", T, gorp), Salon(503, "➕ Join", V, gorp)]
    g = Obj(default_role=tous, me=me, channels=salons)
    return g, tous, clan, staff, direction, {s.id: s for s in salons}


def _droits(actions):
    return {(s.id, getattr(c, "name", "bot")): n for s, c, n, _r in actions}


def test_V1_lecture_seule_parole_et_bouton():
    g, tous, clan, staff, direction, s = _serveur()
    a = _droits(C.plan_v2(g, clan, [staff, direction], {401, 503}, True, {104, 305}))
    for sid in (101, 102, 201, 302, 303):
        o = a[(sid, "@everyone")]
        assert o.view_channel and o.read_message_history and o.send_messages is False and o.add_reactions is False, sid
        assert a[(sid, "Staff")].send_messages, "le staff et au-dessus écrivent toujours"
        assert a[(sid, "bot")].send_messages, "le bot y publie"
    assert (103, "@everyone") not in a, "un salon de ticket n'est jamais touché ici"
    assert not any(k[0] in (104, 305, 306, 304) for k in a), "sondages, logs, staff, entraide : jamais touchés"
    chat = a[(301, "@everyone")]
    assert chat.send_messages and chat.attach_files and chat.embed_links, "le chat : messages, images, liens"


def test_V2_vocaux_join_et_vitrines():
    g, tous, clan, staff, direction, s = _serveur()
    a = _droits(C.plan_v2(g, clan, [staff, direction], {401, 503}, True, set()))
    assert a[(401, "@everyone")].connect and a[(401, "Staff")].move_members, "Join : tout le monde, le staff déplace"
    for sid in (402, 403):
        assert a[(sid, "@everyone")].view_channel and a[(sid, "@everyone")].connect is False, "visible, on n'y entre pas"
    assert (404, "@everyone") not in a, "un vocal ordinaire n'est pas touché"
    sans = _droits(C.plan_v2(g, clan, [staff], {401}, False, set()))
    assert sans[(401, "Staff")].move_members is None, "jamais un droit que le bot n'a pas"


def test_V3_gorp_sea_au_clan_et_au_staff():
    g, tous, clan, staff, direction, s = _serveur()
    a = _droits(C.plan_v2(g, clan, [staff, direction], {401, 503}, True, set()))
    for sid in (500, 501, 502, 503):
        assert a[(sid, "@everyone")].view_channel is False, sid
        assert a[(sid, "Staff")].view_channel, "le staff et au-dessus voient le clan"
    assert a[(501, "Rell Seas")].send_messages is False and a[(501, "Rell Seas")].view_channel, "info-gorp : lecture"
    assert a[(502, "Rell Seas")].send_messages and a[(502, "Rell Seas")].attach_files, "chat-gorpsea : messages, images"
    assert a[(503, "Rell Seas")].connect and a[(503, "Staff")].move_members, "Join du clan"
    assert a[(502, "bot")].view_channel and a[(503, "bot")].move_members, "le bot voit le clan et y déplace"
    sans_clan = _droits(C.plan_v2(g, None, [staff], set(), True, set()))
    assert not any(sid in (500, 501, 502, 503) for sid, _n in sans_clan), "sans rôle de clan réglé, rien ne se cache"


def test_V4_le_bot_garde_ses_droits_sauf_s_il_est_administrateur():
    g, tous, clan, staff, direction, s = _serveur()
    actions = C.plan_v2(g, clan, [staff], {503}, True, set())
    cibles = {(sa.id, getattr(c, "id", None)) for sa, c, _n, _r in actions}
    assert (101, 999) in cibles and (502, 999) in cibles and (503, 999) in cibles, "le bot voit et écrit où il publie"
    g2 = _serveur(bot_admin=True)[0]
    assert not any(getattr(c, "id", None) == 999 for _s, c, _n, _r in C.plan_v2(g2, clan, [staff], {503}, True, set()))


def test_V5_une_seconde_fois_rien_ne_change():
    g, tous, clan, staff, direction, s = _serveur()
    for salon, cible, neuf, _r in C.plan_v2(g, clan, [staff], {401, 503}, True, {104, 305}):
        salon.overwrites[cible] = neuf
    assert C.plan_v2(g, clan, [staff], {401, 503}, True, {104, 305}) == [], "idempotent"


def test_V6_branchements():
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    assert "await _configurer_salons_v2(g)" in src and "await _salon_aide(g)" in src
    fn = next(ast.unparse(n) for n in ARBRE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_configurer_salons_v2")
    assert "'anti_invite', 1" in fn and "required_role=clan_role.id" in fn and "config_salons_historique" in fn
    aide = next(ast.unparse(n) for n in ARBRE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_vue_aide")
    assert "url=salon.jump_url" in aide and "if salon is not None" in aide, "chaque ligne mène à un vrai salon"
