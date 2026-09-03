"""Un rôle de notification par TYPE d'annonce Roblox, et un bouton pour le prendre.

DEMANDE DU PROPRIÉTAIRE (19/08/2026)
    « Sous chacune des annonces Roblox, j'aimerais que tu y crées un petit rôle
      pour le ping […] les gens vont pouvoir cocher en dessous s'ils veulent
      recevoir les notifications ou non. Ils ont juste à cliquer une fois sur le
      bouton, ça leur donnera le rôle et ils se feront ping […] Ils auront juste
      à rappuyer dessus pour ne plus recevoir les notifications. […] Tu fais la
      même pour le côté accessoires […] qui deviennent limited ou alors pour les
      accessoires qui viennent juste de sortir. »

HUIT CATÉGORIES, PAS UNE DE PLUS
Elles ne sont pas inventées : elles reprennent EXACTEMENT les domaines que les
sources rendent déjà (`roblox_news.SOURCES`) et les deux flux d'accessoires.
Un membre qui ne veut que les notes de Studio ne sera pas réveillé par un
concours de build. Les deux salles de presse (FR et EN) partagent un seul rôle :
c'est le même contenu, dédupliqué en amont — deux rôles pingeraient deux fois
pour un seul article.

⚠️ RÔLES NON MENTIONNABLES. `mentionable=False` à la création : un membre ne
peut pas s'en servir pour réveiller tout le monde. Le bot, lui, ping quand même
en passant `allowed_mentions(roles=[role])` explicitement — c'est la seule
manière propre, et c'est déjà la doctrine du dépôt (voir `_ensure_ugc_roles` et
le commentaire de la Phase sur les rôles d'event).

⚠️ CRÉATION PARESSEUSE. Aucun rôle n'est créé au démarrage : un serveur qui
n'active jamais les actualités ne verra jamais apparaître huit rôles dans sa
liste. Le rôle d'une catégorie naît à sa PREMIÈRE annonce publiée, ou au
premier clic sur son bouton.

⚠️ ON NE PROMET RIEN QU'ON NE PEUT TENIR. Sans la permission « Gérer les
rôles », ou si le rôle est au-dessus du bot dans la hiérarchie, `basculer` rend
un état d'échec explicite et le bouton le DIT au membre. Un bouton qui répond
« c'est fait » sans rien faire est le défaut que ce dépôt a déjà payé trois
fois.
"""
from __future__ import annotations

#  Injectés par bot.py (même patron que les autres modules du dépôt).
_cfg = None
_db_set = None
_log = print


def setup(*, cfg, db_set, log=None):
    global _cfg, _db_set, _log
    _cfg, _db_set = cfg, db_set
    if log:
        _log = log


# ═══════════════════════════════════════════════════════════════════════════════
#  Les catégories
# ═══════════════════════════════════════════════════════════════════════════════

#  `role`   : le nom du rôle créé dans le serveur.
#  `couleur`: sa couleur, alignée sur la pastille de la fiche correspondante.
#  `quoi`   : la phrase dite au membre quand il s'abonne — elle doit décrire
#             CE QU'IL VA RECEVOIR, pas le nom du rôle. « Tu recevras les notes
#             de version » est utile ; « tu as le rôle Studio » ne l'est pas.
CATEGORIES: dict[str, dict] = {
    "annonces": {
        "role": "🟢 Annonces Roblox", "couleur": 0x43B581,
        "quoi": "les mises à jour officielles de Roblox",
    },
    "studio": {
        "role": "🔵 Roblox Studio", "couleur": 0x5865F2,
        "quoi": "les notes de version de Studio et du moteur",
    },
    "securite": {
        "role": "🔴 Sécurité Roblox", "couleur": 0xED4245,
        "quoi": "les changements de règles, de sécurité et de modération",
    },
    "evenements": {
        "role": "🟣 Événements Roblox", "couleur": 0x9B59B6,
        "quoi": "les événements, concours et annonces communautaires",
    },
    "devs": {
        "role": "🟠 Développeurs Roblox", "couleur": 0xE67E22,
        "quoi": "les ressources publiées par le staff Roblox",
    },
    "presse": {
        "role": "🟡 Presse Roblox", "couleur": 0xF1C40F,
        "quoi": "les communiqués de la salle de presse Roblox",
    },
    "limited": {
        "role": "💎 Passages Limited", "couleur": 0x1ABC9C,
        "quoi": "les accessoires qui viennent de passer Limited",
    },
    "nouveaux": {
        "role": "🆕 Nouveaux accessoires", "couleur": 0x3498DB,
        "quoi": "les accessoires que Roblox vient de créer",
    },
    #  ⚠️ SA PROPRE CATÉGORIE. Le débit et le public ne sont pas les mêmes :
    #  Roblox crée par fournées espacées de semaines, les joueurs en continu.
    #  Partager le rôle « Nouveaux accessoires » notifierait pour de l UGC des
    #  membres qui n avaient demandé que l officiel.
    "ugc": {
        "role": "🎨 Nouveautés UGC", "couleur": 0xE67E22,
        "quoi": "les accessoires créés par les autres joueurs, filtrés",
    },
}

#  ⚠️ CES CLÉS SONT LES `domaine` RÉELS DE `roblox_news.SOURCES`, pas des noms
#  choisis ici. Un domaine renommé là-bas sans l'être ici retomberait
#  silencieusement sur « aucun ping » — d'où le test qui compare les deux
#  tables (`test_roblox_pings.py`).
CLE_PAR_DOMAINE: dict[str, str] = {
    "Annonces": "annonces",
    "Studio & moteur": "studio",
    "Politique & sécurité": "securite",
    "Événements": "evenements",
    "Développeurs": "devs",
    #  Un seul rôle pour les deux salles de presse : même contenu, dédupliqué
    #  en amont (la version française est servie en premier, exprès).
    "Salle de presse (FR)": "presse",
    "Newsroom Roblox": "presse",
    "Communiqués officiels": "presse",
}

CLE_PAR_FLUX: dict[str, str] = {
    "bascules": "limited",
    "nouveautes": "nouveaux",
    #  ⚠️ SA PROPRE CLÉ, PAS CELLE DES NOUVEAUTÉS. Les deux flux n'ont ni le
    #  même débit ni le même public : partager le rôle ferait notifier pour de
    #  l'UGC les membres qui n'ont demandé que les créations officielles.
    "ugc": "ugc",
}

#  Le préfixe du `custom_id`. Partagé avec `bot.py` (le DynamicItem qui capte le
#  clic) et `roblox_panneau.py` (qui pose le bouton) : une seule vérité.
PREFIXE = "rbxping"


def custom_id(cle: str) -> str:
    return f"{PREFIXE}:{cle}"


def cle_du_billet(billet: dict) -> str | None:
    """La catégorie d'une actualité, d'après son domaine."""
    return CLE_PAR_DOMAINE.get(str((billet or {}).get("domaine") or ""))


def cle_du_flux(flux: str) -> str | None:
    """La catégorie d'un accessoire, d'après son flux de publication."""
    return CLE_PAR_FLUX.get(str(flux or ""))


def cle_config(cle: str) -> str:
    return f"roblox_ping_role_{cle}"


def mention(role) -> str:
    """`<@&id>` — ce qui ping réellement. Vide si pas de rôle : on n'écrit
    jamais un faux `@rôle` en texte brut, ça ne notifie personne et ça donne
    l'illusion du contraire."""
    return f"<@&{role.id}>" if role is not None else ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Le rôle : le trouver, le créer si besoin
# ═══════════════════════════════════════════════════════════════════════════════

async def role_de(guild, cle: str, creer: bool = True):
    """Le rôle de cette catégorie sur ce serveur. `None` si indisponible.

    ⚠️ AUCUNE EXCEPTION NE SORT. Un défaut de rôle ne doit jamais empêcher une
    annonce de partir : mieux vaut une fiche sans ping qu'aucune fiche.
    """
    if guild is None or cle not in CATEGORIES:
        return None
    try:
        c = await _cfg(guild.id)
        rid = int(c.get(cle_config(cle), 0) or 0)
        role = guild.get_role(rid) if rid else None
        if role is not None:
            return role
        if not creer:
            return None
        #  ⚠️ ON VÉRIFIE LA PERMISSION AVANT D'APPELER L'API. Sans ça, un
        #  serveur mal réglé produirait un appel HTTP raté à CHAQUE annonce.
        me = getattr(guild, "me", None)
        if not (me and me.guild_permissions.manage_roles):
            return None
        spec = CATEGORIES[cle]
        role = await guild.create_role(
            name=spec["role"],
            colour=_couleur(spec["couleur"]),
            mentionable=False, hoist=False,
            reason="Veille Roblox — rôle de notification (opt-in par bouton)")
        await _db_set(guild.id, cle_config(cle), role.id)
        _log(f"[roblox_pings] rôle « {spec['role']} » créé sur {guild.id}")
        return role
    except Exception as ex:
        _log(f"[roblox_pings role_de {cle}] {ex}")
        return None


def _couleur(valeur):
    """`discord.Colour` sans importer discord au chargement du module (il est
    importé par des tests qui n'ont pas besoin de la bibliothèque)."""
    try:
        import discord
        return discord.Colour(valeur)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Le clic : prendre ou rendre le rôle
# ═══════════════════════════════════════════════════════════════════════════════

#  Les états rendus par `basculer`. Chacun a une phrase à dire au membre, et
#  aucune ne ment : « impossible » ne se déguise jamais en « c'est fait ».
ACTIVE = "active"
RETIRE = "retire"
SANS_PERMISSION = "sans_permission"
TROP_HAUT = "trop_haut"
ERREUR = "erreur"


async def basculer(guild, membre, cle: str) -> tuple[str, object]:
    """Prend le rôle s'il ne l'a pas, le rend s'il l'a. Rend (état, rôle).

    ⚠️ LES DEUX CAS D'ÉCHEC SONT DISTINCTS ET DITS TELS QUELS :
      · `SANS_PERMISSION` — le bot n'a pas « Gérer les rôles » ;
      · `TROP_HAUT` — le rôle existe mais est au-dessus du bot dans la
        hiérarchie, donc intouchable. C'est le cas le plus vicieux : tout a
        l'air normal, le rôle est là, et l'attribution échoue en silence.
    """
    if cle not in CATEGORIES:
        return ERREUR, None
    try:
        role = await role_de(guild, cle, creer=True)
        if role is None:
            return SANS_PERMISSION, None
        me = getattr(guild, "me", None)
        if not (me and me.guild_permissions.manage_roles):
            return SANS_PERMISSION, role
        if role >= me.top_role or role.managed:
            return TROP_HAUT, role
        if role in getattr(membre, "roles", []):
            await membre.remove_roles(role, reason="Veille Roblox — désabonnement")
            return RETIRE, role
        await membre.add_roles(role, reason="Veille Roblox — abonnement")
        return ACTIVE, role
    except Exception as ex:
        _log(f"[roblox_pings basculer {cle}] {ex}")
        return ERREUR, None


def phrase(etat: str, cle: str) -> str:
    """Ce qu'on dit au membre. Une phrase, en éphémère, jamais en public."""
    spec = CATEGORIES.get(cle) or {}
    quoi = spec.get("quoi", "ces annonces")
    nom = spec.get("role", "ce rôle")
    if etat == ACTIVE:
        return (f"🔔 C'est noté — tu seras **mentionné** pour {quoi}.\n"
                f"-# Reclique sur le même bouton pour ne plus l'être.")
    if etat == RETIRE:
        return (f"🔕 C'est noté — tu ne seras **plus mentionné** pour {quoi}.\n"
                f"-# Reclique sur le même bouton pour te réabonner.")
    if etat == SANS_PERMISSION:
        return ("❌ Je n'ai pas la permission **Gérer les rôles** sur ce serveur, "
                "je ne peux donc pas te donner le rôle.\n"
                "-# Un administrateur peut me l'accorder, puis ça marchera.")
    if etat == TROP_HAUT:
        return (f"❌ Le rôle **{nom}** est placé au-dessus du mien dans la liste "
                f"des rôles : je ne peux pas y toucher.\n"
                f"-# Un administrateur doit remonter mon rôle au-dessus de lui.")
    return "❌ Impossible pour le moment — réessaie dans un instant."
