"""29/10/2026 : les règles du fondateur salon par salon (droits_staff.py), sur un faux serveur."""
import discord

import droits_staff as D

T, V, CAT, FORUM = discord.ChannelType.text, discord.ChannelType.voice, discord.ChannelType.category, discord.ChannelType.forum


class Role:
    def __init__(self, i, perms=0, admin=False):
        self.id, self.name, self.managed = i, f"r{i}", False
        self.permissions = discord.Permissions(perms)
        self.permissions.administrator = admin

    def is_default(self):
        return self.id == 0


TOUS = Role(0, discord.Permissions(view_channel=True, send_messages=True, connect=True,
                                   send_messages_in_threads=True).value)
STAFF = Role(1, discord.Permissions(move_members=True, send_messages=True).value)
DIR = Role(2)
ADMIN = Role(3, admin=True)


class Salon:
    def __init__(self, nom, type_, cat=None, ow=None):
        self.name, self.type, self.category, self.ow = nom, type_, cat, dict(ow or {})

    def overwrites_for(self, r):
        return discord.PermissionOverwrite(**dict(self.ow.get(r.id, discord.PermissionOverwrite())))

    def permissions_for(self, r):
        if r.permissions.administrator:
            return discord.Permissions.all()
        p = discord.Permissions(TOUS.permissions.value | r.permissions.value)
        for cible in ([TOUS] if r is TOUS else [TOUS, r]):
            a, d = self.overwrites_for(cible).pair()
            p = discord.Permissions((p.value & ~d.value) | a.value)
        return p


class Guilde:
    def __init__(self, salons):
        self.channels, self.default_role = salons, TOUS
        self.me = type("Me", (), {"roles": []})()


def _plan(*salons):
    return {(s.name, r.id): (n, why) for s, r, n, why in D.plan(Guilde(list(salons)), [STAFF, ADMIN], [DIR])}


def test_DROITS_public_le_staff_supprime_les_messages_hors_forums():
    p = _plan(Salon("chat", T), Salon("clover-rpg", FORUM))
    assert p[("chat", 1)][0].manage_messages is True and p[("chat", 2)][0].manage_messages is True
    #  29/10/2026 : dans un forum (posts verrouillés guide, infos, annonces), « les seuls qui peuvent, fondateurs et
    #  direction » — le staff n'écrit pas dans un post verrouillé, ne supprime pas, n'ouvre pas de post.
    st, di = p[("clover-rpg", 1)][0], p[("clover-rpg", 2)][0]
    assert (st.manage_threads, st.manage_messages, st.send_messages) == (None, None, False)   # n'en avait pas : refus inutile
    assert (di.manage_threads, di.manage_messages) == (True, True)
    assert not any(k[1] == 3 for k in p)                 # un administrateur a déjà tout


def test_DROITS_lecture_seule_personne_n_ecrit_sauf_le_fondateur():
    lecture = discord.PermissionOverwrite(send_messages=False, send_messages_in_threads=False)
    assert _plan(Salon("annonce", T, ow={0: lecture})) == {}     # le refus de @everyone vaut pour le staff : rien à faire
    donne = discord.PermissionOverwrite(send_messages=True, manage_messages=True)
    p = _plan(Salon("annonce", T, ow={0: lecture, 1: donne, 2: donne}))
    assert p[("annonce", 1)][0].send_messages is False and p[("annonce", 1)][0].manage_messages is False
    assert p[("annonce", 2)][0].send_messages is False                # la Direction non plus


def test_DROITS_clan_modere_mais_ne_voit_pas_sans_le_role():
    cat = Salon("GoRp SEA", CAT, ow={0: discord.PermissionOverwrite(view_channel=False),
                                     1: discord.PermissionOverwrite(view_channel=True)})
    chat = Salon("chat", T, cat=cat, ow={0: discord.PermissionOverwrite(view_channel=False),
                                         1: discord.PermissionOverwrite(view_channel=True, send_messages=True)})
    p = _plan(cat, chat)
    assert p[("GoRp SEA", 1)][0].view_channel is None
    n = p[("chat", 1)][0]
    assert n.view_channel is None and n.manage_messages is True and n.send_messages is True
    assert ("chat", 2) not in p                          # la Direction : rien ne change dans le clan


def test_DROITS_vocaux_taverne_oui_vitrines_non_direction_partout():
    vitrine = discord.PermissionOverwrite(connect=False)
    p = _plan(Salon("3 frères", V, ow={0: vitrine}), Salon("taverne", V, ow={0: vitrine}), Salon("Vocal 1", V))
    assert p[("3 frères", 1)][0].move_members is False
    assert p[("3 frères", 2)][0].move_members is True
    assert p[("taverne", 1)][0].mute_members is True
    assert p[("Vocal 1", 1)][0].mute_members is True and p[("Vocal 1", 1)][0].move_members is None  # l'a déjà


def test_DROITS_une_fois_applique_plus_rien_a_faire():
    salons = [Salon("chat", T), Salon("annonce", T, ow={0: discord.PermissionOverwrite(send_messages=False,
                                                                                         send_messages_in_threads=False)}),
              Salon("3 frères", V, ow={0: discord.PermissionOverwrite(connect=False)})]
    g = Guilde(salons)
    for s, r, n, _ in D.plan(g, [STAFF], [DIR]):
        s.ow[r.id] = n
    assert D.plan(g, [STAFF], [DIR]) == []


def test_DROITS_forum_du_clan_le_staff_ne_gere_plus_les_posts():
    cat = Salon("GoRp SEA", CAT, ow={0: discord.PermissionOverwrite(view_channel=False)})
    donne = discord.PermissionOverwrite(view_channel=True, send_messages=True, send_messages_in_threads=True,
                                        manage_threads=True, manage_messages=True)
    forum = Salon("clan-gorp", FORUM, cat=cat, ow={0: discord.PermissionOverwrite(view_channel=False), 1: donne})
    p = _plan(cat, forum)
    n = p[("clan-gorp", 1)][0]
    assert (n.manage_threads, n.manage_messages, n.send_messages, n.view_channel) == (False, False, False, None)
    assert n.send_messages_in_threads is True                       # il écrit toujours dans les posts ouverts
    d = p[("clan-gorp", 2)][0]
    assert d.manage_threads is True and d.manage_messages is True   # la Direction écrit dans les posts verrouillés


def test_DROITS_salon_automatique_personne_n_ecrit():
    panneau = Salon("ouvrir-un-ticket", T)
    panneau.id = 77
    g = Guilde([panneau])
    p = {(s.name, r.id): n for s, r, n, _ in D.plan(g, [STAFF], [DIR], automatiques={77})}
    assert p[("ouvrir-un-ticket", 1)].send_messages is False and p[("ouvrir-un-ticket", 2)].send_messages is False
    #  @everyone aussi, mais les fils (les tickets) restent ouverts
    poses = []

    async def poser(r, overwrite, reason):
        poses.append((r, overwrite))
    panneau.set_permissions = poser
    g.get_channel = lambda i: panneau if i == 77 else None
    import asyncio
    asyncio.run(D.appliquer(g, [], [], automatiques={77}))
    (r, ow), = [x for x in poses if x[0] is TOUS]
    assert ow.send_messages is False and ow.add_reactions is False and ow.send_messages_in_threads is None

