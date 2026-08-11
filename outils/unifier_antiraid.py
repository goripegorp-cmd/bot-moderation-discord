#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unification des deux anti-raid concurrents.

LE PROBLÈME MESURÉ. Deux systèmes tournaient en parallèle sur `on_member_join` :
  A — clé `anti_raid` + dict `raid_config` : agit sur le SEUL déclencheur, l'expulse
      (irréversible), et son « lockdown » n'est qu'un booléen en RAM sans effet.
  B — clés `antiraid_*` (`_handle_antiraid_join`) : agit sur les N derniers arrivants,
      les ISOLE (réversible, preuves conservées), et verrouille RÉELLEMENT le serveur.

Le défaut n'était pas la double sanction : c'était un FAIL-OPEN. Le `return` de A
sortait de toute la coroutine et sautait l'appel à B. Avec les défauts de A
(auto_mode=True, min_account_age=7), tout compte de moins de 7 jours était expulsé
puis `return` → le compteur de B ne se remplissait jamais → le seul verrouillage réel
du serveur ne se déclenchait JAMAIS. A ne s'ajoutait pas à B : il le neutralisait.
Le même `return` existe dans `anti_newaccount`, donc la faille avait deux chemins.

CE QUE FAIT CE SCRIPT :
  1. Supprime le système A du flux `on_member_join`.
  2. Remonte l'appel de B tout en haut de `on_member_join`, AVANT tout `return`
     possible, pour que le compteur voie chaque arrivée. B compte avant d'agir.
  3. `_handle_antiraid_join` renvoie True quand il a agi sur le membre déclencheur ;
     `on_member_join` s'arrête alors, pour ne pas expulser un compte que B vient
     d'isoler (l'isolement conserve les preuves, le kick les détruit).
  4. Porte la seule capacité utile de A dans B : `send_log('anti_raid', …)`, qui
     alimente le journal unifié et le casier — B ne postait que dans son propre salon.
  5. Migration paresseuse et NON DESTRUCTIVE : un serveur qui avait configuré A voit
     ses réglages repris dans B, en gardant la valeur la PLUS PROTECTRICE des deux.
     Sans elle, supprimer A désactiverait silencieusement leur anti-raid.

La capacité propre de A (expulser les comptes trop jeunes) n'est PAS perdue : elle est
déjà couverte par la protection `anti_newaccount`, distincte et proprement gardée.

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/unifier_antiraid.py            # preview
    PYTHONIOENCODING=utf-8 python3 outils/unifier_antiraid.py --apply    # écrit
"""
from __future__ import annotations

import ast
import re
import sys

FICHIER = "bot.py"

DEB_A = "        # ═══════════════ ANTI-RAID SYSTÈME ═══════════════"
FIN_A = "                return  # Ne pas continuer le traitement"

# ── 2+3. L'appel de B, remonté en tête de on_member_join ─────────────────────
ANCRE_TOP = """    try:
        c = await cfg(m.guild.id)
        guild_id = m.guild.id
"""
NOUVEAU_TOP = """    # ⚠️ ANTI-RAID EN PREMIER — NE PAS REDESCENDRE CET APPEL.
    # Il était placé en fin de fonction, après plusieurs `return` (anti-raid legacy,
    # anti_newaccount). Résultat : tout membre traité par l'un de ces chemins était
    # invisible pour le compteur de raid, qui n'atteignait donc jamais son seuil —
    # le verrouillage du serveur ne se déclenchait jamais. Le compteur doit voir
    # CHAQUE arrivée, avant tout traitement susceptible de sortir de la fonction.
    try:
        if await _handle_antiraid_join(m):
            # Le membre vient d'être isolé par l'anti-raid : on s'arrête là plutôt
            # que de l'expulser derrière (l'isolement conserve les preuves).
            return
    except Exception as ex:
        print(f"[antiraid_join] {ex}")

    try:
        c = await cfg(m.guild.id)
        guild_id = m.guild.id
"""

# L'ancien appel, en fin de fonction, disparaît.
ANCIEN_APPEL = """    # ═══ Phase 28.2 : Anti-Raid (nouveau système configurable) ═══
    try:
        await _handle_antiraid_join(m)
    except Exception as ex:
        print(f"[antiraid_join] {ex}")

"""

# ── 5. Migration paresseuse + 4. journal unifié ──────────────────────────────
ANCRE_B = """async def _handle_antiraid_join(member):
    \"\"\"Phase 28.2 — détecte les raids et applique l'action configurée.\"\"\"
    c = await cfg(member.guild.id)
    if not c.get('antiraid_enabled', False):
        return
"""
NOUVEAU_B = """async def _handle_antiraid_join(member):
    \"\"\"Détecte les vagues d'arrivées et isole les comptes concernés.

    SEUL système anti-raid depuis 08/2026 : le précédent (clé `anti_raid` +
    `raid_config`) le neutralisait au lieu de le compléter — voir le commentaire
    en tête de `on_member_join`.

    Renvoie True si une action a été appliquée AU MEMBRE DÉCLENCHEUR, pour que
    l'appelant s'arrête et ne le sanctionne pas une seconde fois.

    Le compteur d'arrivées est incrémenté À CHAQUE APPEL, même hors raid : c'est
    lui qui permet de détecter la vague. Ne jamais sortir avant.
    \"\"\"
    c = await cfg(member.guild.id)

    # ── Reprise de l'ancien système, une fois par serveur ────────────────────
    # Un serveur qui avait configuré l'anti-raid legacy verrait sinon sa protection
    # tomber en silence. On reprend ses réglages en gardant, pour chaque valeur, la
    # PLUS PROTECTRICE des deux (seuil le plus bas, fenêtre la plus large, âge de
    # compte le plus exigeant). On ne peut donc que renforcer, jamais affaiblir.
    if c.get('anti_raid') and not c.get('antiraid_enabled', False):
        legacy = c.get('raid_config', {}) or {}
        try:
            await db_set(member.guild.id, 'antiraid_join_threshold', min(
                int(c.get('antiraid_join_threshold', 5) or 5),
                int(legacy.get('join_threshold', 10) or 10)))
            await db_set(member.guild.id, 'antiraid_join_window_sec', max(
                int(c.get('antiraid_join_window_sec', 10) or 10),
                int(legacy.get('join_interval', 10) or 10)))
            await db_set(member.guild.id, 'antiraid_min_account_age_days', max(
                int(c.get('antiraid_min_account_age_days', 7) or 7),
                int(legacy.get('min_account_age', 7) or 7)))
            if not int(c.get('antiraid_log_channel', 0) or 0):
                await db_set(member.guild.id, 'antiraid_log_channel',
                             int(c.get('log_anti_raid', 0) or 0))
            await db_set(member.guild.id, 'antiraid_enabled', True)
            await db_set(member.guild.id, 'anti_raid', 0)
            print(f"[ANTIRAID] guild={member.guild.id} réglages legacy repris")
            c = await cfg(member.guild.id)
        except Exception as ex:
            print(f"[ANTIRAID migration] {ex}")

    if not c.get('antiraid_enabled', False):
        return False
"""

# Les `return` internes de B doivent renvoyer False (pas d'action sur le membre).
B_RETURN_PAS_RAID = """    if len(joins) < threshold:
        return  # Pas encore raid
"""
B_RETURN_PAS_RAID_NEW = """    if len(joins) < threshold:
        return False  # Pas encore raid : le join est compté, rien à appliquer
"""

# 4. Journal unifié + casier, porté depuis l'ancien système.
ANCRE_LOG = """    # Log dans le salon dédié
    log_ch_id = int(c.get('antiraid_log_channel', 0) or 0)"""
NOUVEAU_LOG = """    # Journal unifié + casier. L'ancien système alimentait send_log('anti_raid'),
    # pas celui-ci : les raids n'apparaissaient donc ni dans le journal unifié ni
    # dans l'historique des membres. Capacité reprise ici.
    try:
        await send_log(
            member.guild, 'anti_raid', member, None,
            f"Raid détecté : {len(joins)} arrivées en {window}s",
            f"Action: {action.upper()} · {applied}/{len(recent_members)} membre(s)",
        )
    except Exception as ex:
        print(f"[ANTIRAID send_log] {ex}")

    # Log dans le salon dédié
    log_ch_id = int(c.get('antiraid_log_channel', 0) or 0)"""


def main() -> int:
    apply_ = "--apply" in sys.argv
    src = open(FICHIER, encoding="utf-8").read()
    lignes = src.splitlines(keepends=True)
    avant = len(lignes)

    # ── 1. Découpe du système A, par jetons (anti-décalage) ──────────────────
    try:
        i_deb = next(n for n, l in enumerate(lignes) if l.rstrip("\n") == DEB_A)
        i_fin = next(n for n, l in enumerate(lignes) if l.rstrip("\n") == FIN_A and n > i_deb)
    except StopIteration:
        raise SystemExit("ABANDON : bornes du système A introuvables (jetons absents).")

    bloc = "".join(lignes[i_deb:i_fin + 1])
    for jeton in ("if c.get('anti_raid'):", "raid_tracker[guild_id]", "_kick_young_account(m, reason)"):
        if jeton not in bloc:
            raise SystemExit(f"ABANDON : jeton absent du bloc A → décalage. Attendu : {jeton!r}")
    nb_a = i_fin - i_deb + 1

    del lignes[i_deb:i_fin + 1]
    src = "".join(lignes)

    # ── 2+3. Remontée de l'appel ────────────────────────────────────────────
    for etiquette, avant_s, apres_s in (
        ("appel B en tête", ANCRE_TOP, NOUVEAU_TOP),
        ("ancien appel B en fin", ANCIEN_APPEL, ""),
        ("en-tête de B", ANCRE_B, NOUVEAU_B),
        ("return hors-raid", B_RETURN_PAS_RAID, B_RETURN_PAS_RAID_NEW),
        ("journal unifié", ANCRE_LOG, NOUVEAU_LOG),
    ):
        n = src.count(avant_s)
        if n != 1:
            raise SystemExit(f"ABANDON : {etiquette} — {n} occurrence(s), 1 attendue.")
        src = src.replace(avant_s, apres_s)

    # ── Garde-fous ──────────────────────────────────────────────────────────
    ast.parse(src)

    restants = [f"  l.{n} {l.strip()[:90]}"
                for n, l in enumerate(src.splitlines(), 1)
                if re.search(r"\braid_tracker\b|c\.get\('anti_raid'\)", l)
                and "migration" not in l and "legacy" not in l]
    apres = len(src.splitlines())

    print("── Unification anti-raid ───────────────────────────────────────")
    print(f"  Système A supprimé du flux : {nb_a} lignes")
    print("  Appel de B remonté AVANT tout return (fin du fail-open)")
    print("  B renvoie True quand il agit sur le déclencheur")
    print("  send_log('anti_raid') porté dans B (journal unifié + casier)")
    print("  Migration paresseuse des réglages legacy (valeur la plus protectrice)")
    print(f"  bot.py {avant} → {apres} lignes ({apres - avant:+d})")
    print("  ast.parse OK")
    if restants:
        print(f"\n  ⚠️  {len(restants)} référence(s) restante(s) à l'ancien système :")
        for x in restants[:15]:
            print(x)

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    open(FICHIER, "w", encoding="utf-8", newline="").write(src)
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
