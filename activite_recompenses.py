"""activite_recompenses.py — Niveaux et VIP, gagnés par la présence réelle.

DÉSACTIVÉ PAR DÉFAUT, indépendamment du suivi : on peut suivre l'activité sans
distribuer de récompense, et inversement le suivi doit tourner pour récompenser.

═══════════════════════════════════════════════════════════════════════════════
LE CHOIX DE CONCEPTION : UNE SEULE MESURE
═══════════════════════════════════════════════════════════════════════════════
Tout dérive du NOMBRE DE JOURS ACTIFS CUMULÉS — la donnée que le système mesure
déjà. Pas d'XP par message à côté, et c'est délibéré :

  · un compteur d'XP par message récompense le SPAM ; un compteur de jours
    récompense la PRÉSENCE. 200 messages en une soirée valent une journée, comme
    un seul message. C'est exactement ce qu'on veut encourager.
  · une seule source de vérité = pas de désynchronisation possible entre deux
    compteurs qui racontent des histoires différentes.
  · le nombre de jours actifs se RECALCULE depuis `activite_jours` : même si la
    table des niveaux est perdue, rien n'est perdu.

Le niveau n'est donc jamais stocké comme une vérité : il est DÉRIVÉ. La colonne
`niveau` ne sert qu'à détecter le franchissement pour annoncer la montée.

═══════════════════════════════════════════════════════════════════════════════
LE VIP
═══════════════════════════════════════════════════════════════════════════════
Un rôle, donné à partir d'un niveau réglable. Retiré quand le membre tombe au
palier de retrait d'inactivité — pas avant : perdre son VIP après trois jours de
vacances serait absurde et ferait fuir les gens qu'on veut garder.
"""
from __future__ import annotations

import activite

#  Paliers de niveaux, en JOURS ACTIFS CUMULÉS. Le niveau est l'index du dernier
#  palier franchi (+1). Courbe volontairement généreuse au début — on veut qu'un
#  nouveau venu voie sa progression dès la première semaine — puis de plus en plus
#  exigeante, pour que les hauts niveaux veuillent dire quelque chose.
PALIERS = [1, 3, 7, 14, 21, 30, 45, 60, 90, 120, 150, 180, 240, 300, 365]

#  Au-delà du dernier palier, un niveau de plus tous les N jours actifs.
JOURS_PAR_NIVEAU_AU_DELA = 90

#  Nom affiché des niveaux. Purement décoratif, mais ça donne un cap à viser.
TITRES = {
    1: "Nouveau", 3: "Habitué", 6: "Régulier", 9: "Pilier",
    12: "Vétéran", 15: "Légende",
}

CLES_DEFAUT = {
    "activite_recompenses_enabled": False,   # OFF par défaut
    "activite_vip_role": 0,                  # rôle VIP (0 = aucun)
    "activite_vip_niveau": 6,                # niveau requis (6 = 30 jours actifs)
    "activite_salon_annonces": 0,            # où annoncer les montées de niveau
    "activite_annoncer_niveaux": True,
}

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


async def init_db():
    """Colonnes de récompense, ajoutées de façon idempotente.

    `ALTER TABLE ADD COLUMN` échoue si la colonne existe : c'est le comportement
    attendu, on l'avale. SQLite n'a pas d'`IF NOT EXISTS` sur les colonnes.
    """
    async with activite._get_db() as db:
        for sql in (
            "ALTER TABLE activite_etat ADD COLUMN niveau INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE activite_etat ADD COLUMN vip INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                await db.execute(sql)
            except Exception:
                pass          # colonne déjà présente
        await db.commit()


async def config(guild_id: int) -> dict:
    try:
        c = await activite._cfg(guild_id)
    except Exception as ex:
        _log(f"[recompenses config] {ex}")
        c = {}
    out = dict(CLES_DEFAUT)
    for k in out:
        if k in c:
            out[k] = c[k]
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Le calcul
# ═══════════════════════════════════════════════════════════════════════════════

def niveau_pour(jours_actifs: int) -> int:
    """Niveau correspondant à un nombre de jours actifs cumulés.

    0 si le membre n'a jamais été actif — il n'a pas « le niveau 1 par défaut »,
    il n'est simplement pas encore entré dans le système.
    """
    if jours_actifs <= 0:
        return 0
    n = 0
    for seuil in PALIERS:
        if jours_actifs >= seuil:
            n += 1
        else:
            break
    if jours_actifs > PALIERS[-1]:
        n += (jours_actifs - PALIERS[-1]) // JOURS_PAR_NIVEAU_AU_DELA
    return n


def jours_pour_niveau(niveau: int) -> int:
    """Jours actifs nécessaires pour atteindre ce niveau. Réciproque de `niveau_pour`."""
    if niveau <= 0:
        return 0
    if niveau <= len(PALIERS):
        return PALIERS[niveau - 1]
    return PALIERS[-1] + (niveau - len(PALIERS)) * JOURS_PAR_NIVEAU_AU_DELA


def titre_du_niveau(niveau: int) -> str:
    """Titre du palier atteint (le plus haut atteint, pas le prochain)."""
    atteints = [n for n in TITRES if n <= niveau]
    return TITRES[max(atteints)] if atteints else "—"


def progression(jours_actifs: int) -> dict:
    """De quoi dessiner une barre de progression sans refaire les calculs."""
    n = niveau_pour(jours_actifs)
    debut = jours_pour_niveau(n)
    suivant = jours_pour_niveau(n + 1)
    reste = max(0, suivant - jours_actifs)
    largeur = max(1, suivant - debut)
    return {
        "niveau": n,
        "titre": titre_du_niveau(n),
        "jours": jours_actifs,
        "prochain_a": suivant,
        "reste": reste,
        "pourcent": min(100, int(100 * (jours_actifs - debut) / largeur)),
    }


async def jours_actifs(guild_id: int, user_id: int) -> int:
    """Nombre de jours DISTINCTS où le membre a été actif. Source de vérité."""
    try:
        async with activite._get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM activite_jours WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0
    except Exception as ex:
        _log(f"[recompenses jours_actifs] {ex}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Application
# ═══════════════════════════════════════════════════════════════════════════════

async def mettre_a_jour(guild, member) -> dict:
    """Recalcule niveau et VIP d'un membre. Retourne ce qui a CHANGÉ.

    Appelée une fois par jour et par membre (pas à chaque message : le niveau ne
    peut bouger qu'au franchissement d'une journée). Retourne
    {"monte": bool, "niveau": n, "vip_donne": bool, "vip_retire": bool}.
    """
    res = {"monte": False, "niveau": 0, "vip_donne": False, "vip_retire": False}
    try:
        c = await config(guild.id)
        if not c["activite_recompenses_enabled"]:
            return res

        jours = await jours_actifs(guild.id, member.id)
        niveau = niveau_pour(jours)
        res["niveau"] = niveau

        async with activite._get_db() as db:
            async with db.execute(
                "SELECT niveau, vip FROM activite_etat WHERE guild_id=? AND user_id=?",
                (guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
        ancien_niveau = int(row[0]) if row and row[0] is not None else 0
        etait_vip = bool(row[1]) if row and row[1] is not None else False

        res["monte"] = niveau > ancien_niveau

        # ── VIP ──
        vip_role = guild.get_role(int(c["activite_vip_role"] or 0))
        doit_etre_vip = bool(vip_role) and niveau >= int(c["activite_vip_niveau"] or 6)

        if vip_role is not None and vip_role < guild.me.top_role:
            if doit_etre_vip and vip_role not in member.roles:
                await member.add_roles(vip_role, reason=f"Activité : niveau {niveau}")
                res["vip_donne"] = True
            #  On ne retire le VIP QUE si le membre est descendu au palier de
            #  retrait d'inactivité. Le lui enlever après trois jours d'absence
            #  ferait fuir exactement les gens qu'on veut garder.
            elif etait_vip and not doit_etre_vip and vip_role in member.roles:
                await member.remove_roles(vip_role, reason="Activité : niveau perdu")
                res["vip_retire"] = True

        async with activite._get_db() as db:
            await db.execute(
                "INSERT INTO activite_etat(guild_id, user_id, niveau, vip)"
                " VALUES(?,?,?,?)"
                " ON CONFLICT(guild_id, user_id) DO UPDATE SET niveau=?, vip=?",
                (guild.id, member.id, niveau, int(doit_etre_vip),
                 niveau, int(doit_etre_vip)),
            )
            await db.commit()
    except Exception as ex:
        _log(f"[recompenses mettre_a_jour {getattr(member, 'id', '?')}] {ex}")
    return res


async def classement(guild_id: int, limite: int = 10) -> list:
    """Les membres les plus présents : (user_id, jours_actifs, niveau)."""
    try:
        async with activite._get_db() as db:
            async with db.execute(
                "SELECT user_id, COUNT(*) AS n FROM activite_jours"
                " WHERE guild_id=? GROUP BY user_id ORDER BY n DESC LIMIT ?",
                (guild_id, int(limite)),
            ) as cur:
                rows = await cur.fetchall()
        return [(int(u), int(n), niveau_pour(int(n))) for u, n in rows]
    except Exception as ex:
        _log(f"[recompenses classement] {ex}")
        return []
