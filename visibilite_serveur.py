"""visibilite_serveur.py — Ce qu'un NOUVEL ARRIVANT voit du serveur (03/10/2026).

DEMANDE DU PROPRIÉTAIRE (03/10/2026)
    « Tu t'assures que tout s'affiche bien pour les nouveaux arrivants. Que
      tout le monde voit bien le serveur et qu'il n'y ait pas de problème
      là-dessus. »

À chaque démarrage, pour chaque serveur :
  · LE RÔLE D'ARRIVÉE (`welcome_autorole`, posé par le bot à chaque arrivée) :
    existe-t-il, le bot peut-il le poser ? Sans lui, un nouveau ne reçoit pas
    les salons que ce rôle ouvre.
  · CE QU'IL VOIT : catégories et salons visibles pour @everyone + ce rôle, et
    la liste de ce qui reste invisible — souvent voulu (staff, journaux), à
    vérifier d'un coup d'œil. Calculé dans le cache, sans appel réseau.
    ⚠️ Discord affiche une catégorie dès qu'UN de ses salons est visible, même
    si la catégorie elle-même ne l'est pas (vérifié le 03/10) : une catégorie
    n'est « invisible » que si aucun de ses salons ne l'est.
  · L'ONBOARDING DISCORD : quand il est actif, un nouveau ne voit d'office QUE
    les salons « par défaut » — le reste n'apparaît qu'en allant le chercher.
    C'est LA cause classique du « ils ont du mal à voir les catégories ». On y
    ajoute tous les salons que @everyone peut voir (Discord n'accepte que
    ceux-là) ; les questions d'accueil ne sont pas touchées : seul le champ
    des salons par défaut est envoyé, tous les champs étant facultatifs
    (documentation Discord, « Modify Guild Onboarding »).
    C'est la SEULE correction automatique : un salon invisible peut être voulu
    (staff), un salon public absent des salons par défaut ne l'est jamais.
"""
from __future__ import annotations

import discord

#  Les types de salon qu'un onboarding accepte comme « par défaut ».
TYPES_PAR_DEFAUT = (discord.ChannelType.text, discord.ChannelType.news,
                    discord.ChannelType.forum, discord.ChannelType.voice,
                    discord.ChannelType.stage_voice)
#  Combien de noms on écrit dans le journal, au plus.
MAX_NOMS = 12

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


def role_d_arrivee(guild, cfg: dict):
    try:
        rid = int(cfg.get("welcome_autorole", 0) or 0)
    except (TypeError, ValueError):
        rid = 0
    return guild.get_role(rid) if rid else None


def voit(salon, role) -> bool:
    try:
        return bool(salon.permissions_for(role).view_channel)
    except Exception:
        return False


def _est_categorie(salon) -> bool:
    return getattr(salon, "type", None) == discord.ChannelType.category


def releve(guild, cfg: dict) -> dict:
    """Ce que voit un nouvel arrivant. Aucun appel réseau."""
    role = role_d_arrivee(guild, cfg)
    pose = False
    if role is not None:
        try:
            me = guild.me
            pose = bool(me and me.guild_permissions.manage_roles
                        and role < me.top_role and not role.managed)
        except Exception:
            pose = False
    qui = role if (role is not None and pose) else guild.default_role
    categories = [c for c in guild.channels if _est_categorie(c)]
    salons = [s for s in guild.channels if not _est_categorie(s)]
    vus = {s.id for s in salons if voit(s, qui)}
    cachees, ids_cachees, vues = [], set(), 0
    for c in categories:
        enfants = [s for s in salons if getattr(s, "category_id", None) == c.id]
        if voit(c, qui) or any(s.id in vus for s in enfants):
            vues += 1
        else:
            cachees.append((str(c.name), len(enfants)))
            ids_cachees.add(c.id)
    #  Les salons invisibles HORS d'une catégorie déjà entièrement invisible :
    #  ceux-là se cachent au milieu de ce que le nouveau voit.
    isoles = [str(s.name) for s in salons
              if s.id not in vus and getattr(s, "category_id", None) not in ids_cachees]
    return {
        "role": str(role.name) if role is not None else None,
        "role_pose": pose,
        "role_configure": bool(int(cfg.get("welcome_autorole", 0) or 0)),
        "categories": (vues, len(categories)),
        "salons": (len(vus), len(salons)),
        "categories_cachees": cachees,
        "salons_caches": isoles,
    }


async def ouvrir_onboarding(guild, *, corriger: bool = True) -> dict:
    """L'onboarding Discord : s'il est actif, chaque salon public devient un
    salon « par défaut ». Rend {actif, defaut, manquants, ajoutes, raison}."""
    res = {"actif": None, "defaut": 0, "manquants": 0, "ajoutes": 0, "raison": ""}
    try:
        ob = await guild.onboarding()
    except discord.Forbidden:
        res["raison"] = "lecture refusée par Discord"
        return res
    except Exception as ex:
        res["raison"] = f"lecture impossible ({type(ex).__name__})"
        return res
    res["actif"] = bool(getattr(ob, "enabled", False))
    deja = set(getattr(ob, "default_channel_ids", None) or ())
    res["defaut"] = len(deja)
    if not res["actif"]:
        return res
    manquants = [s for s in guild.channels
                 if getattr(s, "type", None) in TYPES_PAR_DEFAUT
                 and s.id not in deja and voit(s, guild.default_role)]
    res["manquants"] = len(manquants)
    if not manquants or not corriger:
        return res
    try:
        await guild.edit_onboarding(
            default_channels=[discord.Object(id=i) for i in sorted(deja)] + manquants,
            reason="Les nouveaux arrivants voient tous les salons publics")
        res["ajoutes"] = len(manquants)
    except discord.Forbidden:
        res["raison"] = "droits « Gérer le serveur » et « Gérer les rôles » requis"
    except discord.HTTPException as ex:
        res["raison"] = f"Discord a refusé ({getattr(ex, 'status', '?')})"
    return res


def bilan_texte(guild_nom: str, r: dict, ob: dict) -> str:
    qui = (f"@everyone + « {r['role']} »" if r["role"] and r["role_pose"]
           else "@everyone seul")
    morceaux = [f"un nouvel arrivant ({qui}) voit {r['categories'][0]}/"
                f"{r['categories'][1]} catégorie(s) et {r['salons'][0]}/"
                f"{r['salons'][1]} salon(s)"]
    if r["role_configure"] and not r["role_pose"]:
        morceaux.append("⚠️ rôle d'arrivée introuvable ou au-dessus du bot : "
                        "les nouveaux ne le reçoivent pas")
    if r["categories_cachees"]:
        noms = ", ".join(f"{n} ({k})" for n, k in r["categories_cachees"][:MAX_NOMS])
        morceaux.append(f"catégories invisibles : {noms}")
    if r["salons_caches"]:
        noms = ", ".join("#" + n for n in r["salons_caches"][:MAX_NOMS])
        plus = len(r["salons_caches"]) - MAX_NOMS
        morceaux.append(f"salons invisibles : {noms}" + (f" … +{plus}" if plus > 0 else ""))
    if ob.get("actif") is None:
        morceaux.append(f"onboarding Discord : {ob.get('raison') or 'illisible'}")
    elif not ob["actif"]:
        morceaux.append("onboarding Discord : inactif (tout salon visible s'affiche)")
    elif ob["ajoutes"]:
        morceaux.append(f"onboarding Discord : {ob['ajoutes']} salon(s) public(s) "
                        f"ajouté(s) aux salons par défaut ({ob['defaut']} → "
                        f"{ob['defaut'] + ob['ajoutes']})")
    elif ob["manquants"]:
        morceaux.append(f"⚠️ onboarding Discord : {ob['manquants']} salon(s) public(s) "
                        f"hors des salons par défaut — {ob['raison']}")
    else:
        morceaux.append(f"onboarding Discord : actif, les {ob['defaut']} salons "
                        f"publics sont tous par défaut")
    return f"{guild_nom} : " + " · ".join(morceaux)
