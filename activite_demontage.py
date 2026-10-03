"""activite_demontage.py — Le système d'activité est RETIRÉ (03/10/2026).

DEMANDE DU PROPRIÉTAIRE (03/10/2026)
    « Le système d'activité, quand les gens sont AFK, quand ils ne parlent pas
      et tout, enlève-moi complètement ce système et ce calcul inutile. […]
      Quelqu'un qui est AFK, c'est juste qu'il ne parle pas, il reparlera à
      l'avenir. Donc, tu t'assures juste que tout le monde voit bien tous les
      salons. Toutes les catégories aussi […] »
    Puis, à ses deux questions : salons du système → « Les supprimer » ;
    bouton « Activité » de /rellseas → « Garder pour /rellseas » (seul le
    comptage des jours reste, dans `activite.py` — aucun rôle, aucun masquage,
    aucun message).

═══════════════════════════════════════════════════════════════════════════════
CE QUE LE SYSTÈME AVAIT POSÉ SUR DISCORD — ET QUE CE MODULE DÉFAIT
═══════════════════════════════════════════════════════════════════════════════
  1. Des membres DÉPOUILLÉS de tous leurs rôles (palier 2). La liste est en
     base, `activite_etat.roles_retires` : on la leur REND, en un appel par
     membre. Un membre parti entre-temps la retrouve à son retour
     (`rendre_au_retour`, branché sur l'arrivée).
  2. Ses étiquettes — « 💤 AFK », « 💤 AFK · rôles retirés », « 👀 Peu actif »,
     « 🚪 Compte abandonné » — et, portés par elles, un refus « voir le salon »
     sur CHAQUE salon et CHAQUE catégorie. C'est ce masquage qui faisait dire
     « ils ont du mal à voir les catégories ». On SUPPRIME ces rôles : Discord
     retire avec eux leurs surcharges sur tous les salons, en un appel par rôle.
     Un rôle du serveur que le propriétaire avait seulement DÉSIGNÉ (pas créé
     par le bot) n'est pas supprimé : on lui retire ses refus et ses porteurs.
  3. Ses salons (porte de retour, salon AFK) : supprimés — SAUF s'ils servent
     aussi à autre chose (référencés ailleurs dans la configuration) ou si leur
     nom ne dit pas ce qu'ils sont. On ne supprime jamais un salon général que
     quelqu'un aurait choisi comme porte : l'historique d'un salon supprimé ne
     revient pas.

RELANÇABLE ET SOBRE : tourne au démarrage tant qu'il reste quelque chose à
défaire, ne fait d'appel réseau que pour ce qui reste. Quand tout est fait,
une marque en base (`activite_demonte_le`) le fait taire.
"""
from __future__ import annotations

import asyncio
import json
import unicodedata
from datetime import datetime, timezone

import discord

#  Entre deux écritures Discord : une tâche de démarrage ne doit jamais manger le
#  quota dont la modération a besoin.
PAUSE = 0.6

#  Les noms que le bot donnait lui-même à ses étiquettes (`creer_role`).
NOMS_ETIQUETTES = frozenset({"💤 AFK", "💤 AFK · rôles retirés", "👀 Peu actif",
                             "🚪 Compte abandonné"})
CLES_ROLES = ("activite_role_doux", "activite_role_niveau1",
              "activite_role_niveau2", "activite_role_abandon")
CLES_SALONS = ("activite_salon_retour", "activite_salon_afk")
#  Ce que le nom d'un salon doit dire pour qu'on le supprime (sans accents, en
#  minuscules). Un « #général » choisi comme porte n'y répond pas : il reste.
MOTS_SALON_SYSTEME = ("afk", "retour", "absen", "inacti", "revenir", "reviens",
                      "porte", "return", "comeback", "come-back")
MARQUE = "activite_demonte_le"

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


# ═══════════════════════════════════════════════════════════════════════════════
#  Ce qui appartient au système
# ═══════════════════════════════════════════════════════════════════════════════

def _entier(x) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def _json(x, defaut):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return defaut
    return x if x is not None else defaut


def ids_roles_systeme(cfg: dict) -> set[int]:
    """Toutes les étiquettes jamais configurées : actuelles ET anciennes."""
    ids = {_entier(cfg.get(k)) for k in CLES_ROLES}
    hist = _json(cfg.get("activite_etiquettes_historique"), {})
    if isinstance(hist, dict):
        for v in hist.values():
            for x in (v or []):
                ids.add(_entier(x))
    return ids - {0}


def ids_salons_systeme(cfg: dict) -> set[int]:
    """La porte de retour, le salon AFK, et la porte propre à un rôle suivi."""
    ids = {_entier(cfg.get(k)) for k in CLES_SALONS}
    roles = _json(cfg.get("activite_roles"), {})
    if isinstance(roles, dict):
        for conf in roles.values():
            if isinstance(conf, dict):
                ids.add(_entier(conf.get("salon_retour")))
    return ids - {0}


def _normaliser(nom: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(nom or ""))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def nom_de_salon_systeme(nom: str) -> bool:
    n = _normaliser(nom)
    return any(m in n for m in MOTS_SALON_SYSTEME)


def _designe(valeur, cible: int) -> bool:
    """Cette valeur de configuration désigne-t-elle `cible` ? (entier, texte,
    JSON, liste, dictionnaire — clés comprises : `auto_help_channels` range ses
    salons en clés)."""
    if isinstance(valeur, bool):
        return False
    if isinstance(valeur, int):
        return valeur == cible
    if isinstance(valeur, str):
        s = valeur.strip()
        if s.isdigit():
            return int(s) == cible
        if s[:1] in "[{":
            try:
                return _designe(json.loads(s), cible)
            except Exception:
                return False
        return False
    if isinstance(valeur, (list, tuple, set)):
        return any(_designe(v, cible) for v in valeur)
    if isinstance(valeur, dict):
        return any(_designe(k, cible) or _designe(v, cible)
                   for k, v in valeur.items())
    return False


def utilise_ailleurs(cfg: dict, salon_id: int) -> list[str]:
    """Les réglages, HORS système d'activité, qui désignent ce salon."""
    return [str(k) for k, v in cfg.items()
            if not str(k).startswith("activite_") and _designe(v, salon_id)]


def role_cree_par_le_systeme(role) -> bool:
    """À NOTRE nom et sans AUCUNE permission : c'est `creer_role` qui l'a fait.
    Un rôle du serveur qui porterait le même nom par hasard a, lui, des droits."""
    try:
        return (str(role.name) in NOMS_ETIQUETTES
                and int(role.permissions.value) == 0
                and not role.managed)
    except Exception:
        return False


def _manipulable(guild, role) -> bool:
    try:
        me = guild.me
        return (me is not None and me.guild_permissions.manage_roles
                and role < me.top_role and not role.managed)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Rendre les rôles
# ═══════════════════════════════════════════════════════════════════════════════

async def roles_a_rendre(get_db, guild_id: int, user_id: int | None = None) -> dict:
    """{user_id: [role_id, …]} — ce que le palier 2 avait pris et pas rendu."""
    sql = ("SELECT user_id, roles_retires FROM activite_etat WHERE guild_id=?"
           " AND roles_retires IS NOT NULL AND roles_retires NOT IN ('', '[]')")
    params = [guild_id]
    if user_id is not None:
        sql += " AND user_id=?"
        params.append(user_id)
    try:
        async with get_db() as db:
            async with db.execute(sql, tuple(params)) as cur:
                rows = await cur.fetchall()
    except Exception as ex:
        if "no such table" in str(ex):
            return {}
        raise
    out = {}
    for uid, brut in rows:
        ids = [_entier(x) for x in (_json(brut, []) or [])]
        ids = [i for i in ids if i]
        if ids:
            out[int(uid)] = ids
    return out


async def _noter_restants(get_db, guild_id: int, user_id: int, restants) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE activite_etat SET roles_retires=?, palier=0"
            " WHERE guild_id=? AND user_id=?",
            (json.dumps(list(restants)), guild_id, user_id))
        await db.commit()


async def rendre(guild, member, ids, get_db) -> dict:
    """Rend à `member` les rôles `ids`. Un rôle supprimé depuis n'est plus à
    rendre ; un rôle passé au-dessus du bot RESTE noté (rendu plus tard)."""
    res = {"rendus": [], "impossibles": [], "disparus": 0}
    a_rendre, restants = [], []
    for rid in ids:
        r = guild.get_role(int(rid))
        if r is None:
            res["disparus"] += 1
            continue
        if not _manipulable(guild, r):
            restants.append(int(rid))
            res["impossibles"].append(str(r.name))
            continue
        if r not in member.roles:
            a_rendre.append(r)
    if a_rendre:
        #  `atomic=False` : UN seul appel pour tous les rôles, comme le retrait.
        await member.add_roles(*a_rendre, atomic=False,
                               reason="Système d'activité retiré : rôles rendus")
        res["rendus"] = [str(r.name) for r in a_rendre]
    await _noter_restants(get_db, guild.id, member.id, restants)
    return res


async def rendre_au_retour(guild, member, *, get_db):
    """Un membre dépouillé par l'ancien système revient sur le serveur : il
    récupère ses rôles dès l'arrivée. `None` s'il n'y avait rien à rendre."""
    ids = (await roles_a_rendre(get_db, guild.id, member.id)).get(member.id)
    if not ids:
        return None
    return await rendre(guild, member, ids, get_db)


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Les étiquettes — et le masquage qu'elles portaient
# ═══════════════════════════════════════════════════════════════════════════════

async def retirer_etiquettes(guild, cfg: dict) -> dict:
    res = {"supprimes": [], "nettoyes": [], "bloques": []}
    ids = ids_roles_systeme(cfg)
    cibles = [r for r in guild.roles
              if not r.is_default()
              and (r.id in ids or role_cree_par_le_systeme(r))]
    for r in cibles:
        if not _manipulable(guild, r):
            res["bloques"].append(str(r.name))
            continue
        if role_cree_par_le_systeme(r):
            #  Supprimer le rôle retire aussi ses refus sur TOUS les salons et
            #  catégories, et le retire à tous ses porteurs : un appel.
            await r.delete(reason="Système d'activité retiré")
            res["supprimes"].append(str(r.name))
        else:
            #  Un rôle du serveur seulement DÉSIGNÉ comme étiquette : il reste,
            #  sans les refus que le système avait posés, et sans porteurs.
            for salon in list(guild.channels):
                if not salon.overwrites_for(r).is_empty():
                    await salon.set_permissions(
                        r, overwrite=None, reason="Système d'activité retiré")
                    await asyncio.sleep(PAUSE)
            for m in list(r.members):
                await m.remove_roles(r, reason="Système d'activité retiré")
                await asyncio.sleep(PAUSE)
            res["nettoyes"].append(str(r.name))
        await asyncio.sleep(PAUSE)
    return res


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Les salons du système
# ═══════════════════════════════════════════════════════════════════════════════

async def supprimer_salons(guild, cfg: dict) -> dict:
    res = {"supprimes": [], "gardes": []}
    for sid in sorted(ids_salons_systeme(cfg)):
        salon = guild.get_channel(sid)
        if salon is None:
            continue
        nom = str(getattr(salon, "name", sid))
        if getattr(salon, "type", None) == discord.ChannelType.category:
            res["gardes"].append((nom, "c'est une catégorie"))
            continue
        ailleurs = utilise_ailleurs(cfg, sid)
        if ailleurs:
            res["gardes"].append((nom, "sert aussi à " + ", ".join(ailleurs[:3])))
            continue
        if not nom_de_salon_systeme(nom):
            res["gardes"].append((nom, "nom général — à supprimer à la main "
                                       "si c'était bien le sien"))
            continue
        try:
            await salon.delete(reason="Système d'activité retiré (salon du système)")
            res["supprimes"].append(nom)
        except discord.Forbidden:
            res["gardes"].append((nom, "le bot n'a pas le droit de le supprimer"))
        await asyncio.sleep(PAUSE)
    return res


# ═══════════════════════════════════════════════════════════════════════════════
#  Tout ensemble
# ═══════════════════════════════════════════════════════════════════════════════

async def demonter(guild, *, cfg: dict, get_db, db_set) -> dict:
    """Défait, sur ce serveur, tout ce que le système d'activité avait posé.

    `cfg` : la configuration BRUTE du serveur. Rend un bilan ; `fait` est vrai
    quand il ne reste plus rien que le bot puisse défaire (les membres absents
    récupèrent leurs rôles à leur retour ; un rôle au-dessus du bot, lui,
    attend que le propriétaire le redescende — le démontage reprendra)."""
    res = {"membres": 0, "rendus": 0, "absents": 0, "impossibles": [],
           "etiquettes": {"supprimes": [], "nettoyes": [], "bloques": []},
           "salons": {"supprimes": [], "gardes": []}, "fait": False,
           "deja": bool(cfg.get(MARQUE))}
    if res["deja"]:
        return res
    for uid, ids in (await roles_a_rendre(get_db, guild.id)).items():
        m = guild.get_member(uid)
        if m is None and not getattr(guild, "chunked", True):
            try:
                m = await guild.fetch_member(uid)
            except Exception:
                m = None
        if m is None:
            res["absents"] += 1
            continue
        try:
            r = await rendre(guild, m, ids, get_db)
        except Exception as ex:
            _log("[activite_demontage][E301] roles non rendus")
            _log(f"[activite_demontage][E301:DETAIL] membre={uid} {type(ex).__name__}: {ex}")
            res["impossibles"].append(str(uid))
            continue
        if r["rendus"]:
            res["membres"] += 1
            res["rendus"] += len(r["rendus"])
        res["impossibles"] += r["impossibles"]
        await asyncio.sleep(PAUSE)
    res["etiquettes"] = await retirer_etiquettes(guild, cfg)
    res["salons"] = await supprimer_salons(guild, cfg)
    if cfg.get("activite_enabled"):
        await db_set(guild.id, "activite_enabled", False)
    res["fait"] = not (res["impossibles"] or res["etiquettes"]["bloques"])
    if res["fait"]:
        await db_set(guild.id, MARQUE, datetime.now(timezone.utc).isoformat())
    return res


def a_agi(res: dict) -> bool:
    return bool(res["rendus"] or res["etiquettes"]["supprimes"]
                or res["etiquettes"]["nettoyes"] or res["salons"]["supprimes"])


def bilan_texte(res: dict) -> str:
    """Une ligne de journal ; le compte rendu staff en reprend le contenu."""
    e, s = res["etiquettes"], res["salons"]
    morceaux = [f"{res['membres']} membre(s) ont récupéré {res['rendus']} rôle(s)"]
    if e["supprimes"] or e["nettoyes"]:
        morceaux.append(
            f"{len(e['supprimes']) + len(e['nettoyes'])} rôle(s) du système retiré(s) "
            f"({', '.join(e['supprimes'] + e['nettoyes'])}) — masquage levé sur "
            f"tous les salons et catégories")
    if s["supprimes"]:
        morceaux.append(f"salon(s) supprimé(s) : {', '.join('#' + n for n in s['supprimes'])}")
    for nom, pourquoi in s["gardes"]:
        morceaux.append(f"#{nom} gardé ({pourquoi})")
    if res["absents"]:
        morceaux.append(f"{res['absents']} membre(s) parti(s) les récupéreront à leur retour")
    if e["bloques"]:
        morceaux.append(f"⚠️ au-dessus du bot, à supprimer à la main : "
                        f"{', '.join(e['bloques'])}")
    if res["impossibles"]:
        morceaux.append(f"⚠️ {len(res['impossibles'])} rôle(s) au-dessus du bot "
                        f"pas encore rendu(s)")
    return " · ".join(morceaux)
