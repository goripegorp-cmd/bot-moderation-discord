"""activite_escalade.py — Les paliers : rappel, retrait de rôle, proposition d'expulsion.

Séparé de `activite.py` volontairement : le suivi doit rester minuscule et rapide
(il tourne sur CHAQUE message), l'escalade est un traitement lourd qui passe une
fois par jour. Mélanger les deux ferait payer à chaque message le coût du calcul.

═══════════════════════════════════════════════════════════════════════════════
CE QUI SE PASSE, ET DANS QUEL ORDRE
═══════════════════════════════════════════════════════════════════════════════
Un passage quotidien :
  1. Refuse de tourner si le système est éteint ou sans cible.
  2. Calcule, pour chaque membre concerné, ses jours d'inactivité.
  3. Range chacun dans son palier selon les seuils de SON rôle.
  4. ⚠️ PLAFOND : si le nombre d'actions dépasse `PLAFOND_ACTIONS_PAR_PASSAGE`,
     on n'agit sur PERSONNE et on alerte le staff. Un pic pareil veut dire que le
     suivi est cassé (base vidée, horloge décalée), pas que le serveur dort.
  5. Applique : rappel hebdomadaire (le jour choisi), retrait de rôle, et pour
     l'expulsion → une simple PROPOSITION au staff. Jamais d'expulsion automatique.

RÉVERSIBILITÉ. Les rôles retirés sont mémorisés dans `activite_etat.roles_retires`.
Dès que le membre redevient actif, ils lui sont RENDUS automatiquement. Le retrait
n'est donc pas une punition définitive, c'est une mise en veille.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import activite

PLAFOND_ACTIONS_PAR_PASSAGE = activite.PLAFOND_ACTIONS_PAR_PASSAGE

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


# ═══════════════════════════════════════════════════════════════════════════════
#  Classement
# ═══════════════════════════════════════════════════════════════════════════════

async def classer(guild) -> dict:
    """Range les membres concernés par palier. NE MODIFIE RIEN.

    C'est la fonction que le panneau appelle pour l'aperçu, et celle que le
    passage quotidien appelle avant d'agir : même calcul, donc ce que le staff
    voit est exactement ce qui sera appliqué.

    Retourne {"rappel": [...], "retrait": [...], "expulsion": [...],
              "actifs": n, "suivis": n}
    """
    cfg_act = await activite.config(guild.id)
    out = {"rappel": [], "retrait": [], "expulsion": [], "actifs": 0, "suivis": 0}
    if not await activite.actif(guild.id):
        return out

    for member in guild.members:
        try:
            if not await activite.membre_concerne(member, cfg_act):
                continue
            out["suivis"] += 1

            jours = await activite.jours_inactif(guild.id, member)
            if jours is None:
                #  Ni activité connue ni date d'arrivée : on ne devine pas.
                continue

            role = activite.role_surveille_du_membre(member, cfg_act)
            seuils = (activite.seuils_du_role(cfg_act, role.id) if role
                      else {"rappel": activite.SEUIL_RAPPEL_DEFAUT,
                            "retrait": activite.SEUIL_RETRAIT_DEFAUT,
                            "expulsion": activite.SEUIL_EXPULSION_DEFAUT,
                            "retirer_role": True})

            fiche = {"member": member, "jours": jours, "role": role, "seuils": seuils}
            #  Du plus grave au moins grave : un membre n'apparaît qu'une fois.
            if jours >= seuils["expulsion"]:
                out["expulsion"].append(fiche)
            elif jours >= seuils["retrait"]:
                out["retrait"].append(fiche)
            elif jours >= seuils["rappel"]:
                out["rappel"].append(fiche)
            else:
                out["actifs"] += 1
        except Exception as ex:
            _log(f"[activite classer {getattr(member, 'id', '?')}] {ex}")
    for k in ("rappel", "retrait", "expulsion"):
        out[k].sort(key=lambda f: -f["jours"])
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Restitution — le pendant du retrait
# ═══════════════════════════════════════════════════════════════════════════════

async def rendre_roles(guild, member) -> list:
    """Rend les rôles retirés à un membre redevenu actif. Retourne les rôles rendus.

    Appelée dès qu'un membre est marqué actif. Sans elle, le retrait de rôle
    serait définitif et le système deviendrait une punition, pas une mise en veille.
    """
    rendus = []
    try:
        async with activite._get_db() as db:
            async with db.execute(
                "SELECT roles_retires FROM activite_etat WHERE guild_id=? AND user_id=?",
                (guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
        if not row or not row[0]:
            return rendus
        ids = json.loads(row[0]) or []
        if not ids:
            return rendus

        for rid in ids:
            r = guild.get_role(int(rid))
            #  Ne jamais tenter un rôle au-dessus du bot : l'API refuserait et on
            #  perdrait la mémoire du rôle en le retirant de la liste.
            if r is not None and r not in member.roles and r < guild.me.top_role:
                try:
                    await member.add_roles(r, reason="Activité : retour du membre")
                    rendus.append(r)
                except Exception as ex:
                    _log(f"[activite rendre_roles {r.id}] {ex}")

        if rendus:
            restants = [int(x) for x in ids if guild.get_role(int(x)) not in rendus]
            async with activite._get_db() as db:
                await db.execute(
                    "UPDATE activite_etat SET roles_retires=?, palier=0"
                    " WHERE guild_id=? AND user_id=?",
                    (json.dumps(restants), guild.id, member.id),
                )
                await db.commit()
    except Exception as ex:
        _log(f"[activite rendre_roles] {ex}")
    return rendus


# ═══════════════════════════════════════════════════════════════════════════════
#  Application des paliers
# ═══════════════════════════════════════════════════════════════════════════════

async def appliquer_retraits(guild, fiches: list) -> dict:
    """Retire le rôle surveillé aux membres du palier 2. Mémorise pour restitution."""
    res = {"faits": 0, "echecs": 0, "ignores": 0}
    for f in fiches:
        member, role, seuils = f["member"], f["role"], f["seuils"]
        if role is None or not seuils.get("retirer_role", True):
            res["ignores"] += 1
            continue
        #  Re-vérification de l'immunité JUSTE AVANT d'agir : le classement peut
        #  dater de quelques secondes, un membre a pu devenir admin entre-temps.
        cfg_act = await activite.config(guild.id)
        if not await activite.membre_concerne(member, cfg_act):
            res["ignores"] += 1
            continue
        if role >= guild.me.top_role:
            _log(f"[activite retrait] rôle {role.id} au-dessus du bot — ignoré")
            res["echecs"] += 1
            continue
        try:
            await member.remove_roles(role, reason=f"Inactif depuis {f['jours']} jours")
            async with activite._get_db() as db:
                async with db.execute(
                    "SELECT roles_retires FROM activite_etat WHERE guild_id=? AND user_id=?",
                    (guild.id, member.id),
                ) as cur:
                    row = await cur.fetchone()
                deja = json.loads(row[0]) if row and row[0] else []
                if role.id not in deja:
                    deja.append(role.id)
                await db.execute(
                    "INSERT INTO activite_etat(guild_id, user_id, palier, roles_retires)"
                    " VALUES(?,?,2,?)"
                    " ON CONFLICT(guild_id, user_id) DO UPDATE SET palier=2, roles_retires=?",
                    (guild.id, member.id, json.dumps(deja), json.dumps(deja)),
                )
                await db.commit()
            res["faits"] += 1
        except Exception as ex:
            _log(f"[activite retrait {member.id}] {ex}")
            res["echecs"] += 1
    return res


def texte_rappel(fiches: list, salon_retour=None, avec_retrait: bool = False) -> str:
    """Le message public. MENTIONNE les membres — choix explicite du propriétaire.

    Volontairement court et sans reproche : le but est de faire revenir quelqu'un,
    pas de l'humilier devant le serveur.
    """
    if not fiches:
        return ""
    lignes = []
    for f in fiches[:40]:
        lignes.append(f"• {f['member'].mention} — `{f['jours']}` jour(s)")
    if len(fiches) > 40:
        lignes.append(f"-# … et {len(fiches) - 40} autre(s)")

    if avec_retrait:
        tete = ("## ⚠️ Rôle retiré pour inactivité\n"
                "Votre rôle vous a été **mis en veille**. Il vous sera rendu "
                "automatiquement dès votre retour.")
        pied = (f"\n👉 Pour le récupérer tout de suite : écrivez un message dans "
                f"{salon_retour.mention}." if salon_retour else
                "\n👉 Il suffit de redevenir actif pour le récupérer.")
    else:
        tete = ("## 👋 On ne vous a pas vu depuis un moment\n"
                "Rien de grave — un simple signe suffit à repartir de zéro.")
        pied = ("\n👉 **Une seule** de ces trois choses suffit : écrire un message, "
                "passer en vocal, ou réagir à un message.")

    return f"{tete}\n\n" + "\n".join(lignes) + "\n" + pied
