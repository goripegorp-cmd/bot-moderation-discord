"""referrals.py — Tâche B.1 : PARRAINAGE RÉCOMPENSÉ (anti-alt, zéro DM).

🎯 OBJECTIF (croissance & hype) : récompenser MODESTEMENT un membre qui fait
venir un nouveau, SANS ouvrir la porte aux fermes d'alts. La récompense du parrain
est DIFFÉRÉE et CONDITIONNÉE à une double GATE anti-alt :

  1. L'invité doit atteindre un SEUIL D'ACTIVITÉ RÉELLE (réutilise activity_system :
     messages + vocal sur 14 j) → un alt jamais ouvert ne crédite jamais.
  2. Le compte de l'invité doit être suffisamment ÂGÉ (comme member_risk) → un alt
     créé la veille ne crédite jamais.

Tant que les deux conditions ne sont pas réunies, le parrainage reste « en attente ».
Une tâche quotidienne (fail-open, supervisée) re-vérifie les attentes et crédite
le parrain quand l'invité a fait ses preuves. Claim ATOMIQUE + anti-doublon par
invitee_id : un même invité ne crédite JAMAIS deux fois.

SUIVI DES INVITATIONS (léger, fail-safe) : on garde en mémoire le compteur d'uses
de chaque invite (cache par guilde). À chaque arrivée, on compare le cache au snapshot
live `guild.invites()` : l'invite dont le compteur a augmenté de 1 désigne le parrain.
Si l'ambiguïté est totale (plusieurs invites bougent, vanity URL, invite expirée non
vue…), on n'attribue simplement PAS de parrain (jamais de fausse attribution).

AUCUN DM : l'affichage « Mes parrainages » se fait via un bouton du hub. Toute
annonce/notification éventuelle passe par un salon (géré côté bot.py).

Module AUTONOME : dépendances injectées via setup() (même patron que
activity_system / cosmetics). FAIL-OPEN partout : un bug n'empêche jamais un join.

DB :
- referrals (guild_id, invitee_id PK avec guild_id, inviter_id, joined_at,
             rewarded INTEGER DEFAULT 0, rewarded_at TIMESTAMP)
- referral_invite_meta : (non persistée — cache mémoire suffit ; on re-prime au boot)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import tasks

# ─── Dépendances injectées ───────────────────────────────────────────────────
_get_db = None
_add_coins = None            # add_coins(guild_id, user_id, amount) -> coroutine
_activity_score = None       # async get_score(guild_id, user_id) -> int
_bot = None

# ─── Réglages (MODESTES — rétention #1, anti-inflation) ───────────────────────
# Récompense pièces du PARRAIN une fois l'invité validé. Volontairement petite :
# le parrainage est un bonus d'ambiance, pas une source de farm.
REWARD_COINS = 150

# GATE anti-alt n°1 : activité réelle de l'invité (points activity_system sur 14 j).
# 25 pts = ~25 messages OU ~25 min de vocal → exclut tout alt « ouvert puis fermé ».
MIN_INVITEE_ACTIVITY = 25

# GATE anti-alt n°2 : âge du compte Discord de l'invité (jours). Aligné sur la
# logique member_risk (compte < 30 j = suspect). Un alt fraîchement créé attend.
MIN_INVITEE_ACCOUNT_AGE_DAYS = 30

# Un parrain ne peut pas se parrainer lui-même (auto-invite). Évident, mais explicite.

# Cache mémoire des uses d'invites : { guild_id: { invite_code: uses } }.
_invite_uses_cache: dict = {}


def setup(get_db_fn, *, add_coins_fn=None, activity_score_fn=None, bot=None):
    """Injecte les dépendances (DB + crédit pièces + score d'activité + bot)."""
    global _get_db, _add_coins, _activity_score, _bot
    _get_db = get_db_fn
    _add_coins = add_coins_fn
    _activity_score = activity_score_fn
    _bot = bot


async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS referrals ("
                "guild_id INTEGER NOT NULL, "
                "invitee_id INTEGER NOT NULL, "
                "inviter_id INTEGER NOT NULL, "
                "joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "rewarded INTEGER DEFAULT 0, "
                "rewarded_at TIMESTAMP, "
                "PRIMARY KEY (guild_id, invitee_id))"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_referrals_inviter "
                "ON referrals(guild_id, inviter_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_referrals_pending "
                "ON referrals(guild_id, rewarded)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[referrals init_db] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  SUIVI DES INVITATIONS (cache léger)
# ═══════════════════════════════════════════════════════════════════════════════

async def prime_guild_cache(guild: discord.Guild) -> None:
    """Snapshot des uses d'invites de la guilde → cache mémoire. À appeler au boot
    (on_ready) ET après on_invite_create/delete. FAIL-SAFE (perms manquantes →
    cache vide pour cette guilde, l'attribution sera juste désactivée)."""
    if guild is None:
        return
    try:
        invites = await guild.invites()
    except Exception:
        # Manage Guild manquant ou indisponible : pas de tracking pour cette guilde.
        _invite_uses_cache[guild.id] = {}
        return
    try:
        snapshot = {}
        for inv in invites:
            try:
                snapshot[inv.code] = int(inv.uses or 0)
            except Exception:
                continue
        # Vanity URL (serveurs boostés) : compteur séparé, on le suit aussi si dispo.
        try:
            vanity = getattr(guild, "vanity_url_code", None)
            if vanity:
                vi = await guild.vanity_invite()
                if vi is not None:
                    snapshot[f"__vanity__{vanity}"] = int(getattr(vi, "uses", 0) or 0)
        except Exception:
            pass
        _invite_uses_cache[guild.id] = snapshot
    except Exception as ex:
        print(f"[referrals prime_guild_cache] {ex}")
        _invite_uses_cache[guild.id] = {}


async def on_invite_create(invite: discord.Invite) -> None:
    """Maj cache : nouvelle invite (uses initiaux). FAIL-SAFE."""
    try:
        g = getattr(invite, "guild", None)
        if g is None:
            return
        bucket = _invite_uses_cache.setdefault(g.id, {})
        bucket[invite.code] = int(invite.uses or 0)
    except Exception as ex:
        print(f"[referrals on_invite_create] {ex}")


async def on_invite_delete(invite: discord.Invite) -> None:
    """Maj cache : invite supprimée/expirée. FAIL-SAFE."""
    try:
        g = getattr(invite, "guild", None)
        if g is None:
            return
        bucket = _invite_uses_cache.get(g.id)
        if bucket is not None:
            bucket.pop(getattr(invite, "code", None), None)
    except Exception as ex:
        print(f"[referrals on_invite_delete] {ex}")


async def _match_inviter(guild: discord.Guild) -> Optional[int]:
    """Compare le cache au snapshot live → renvoie l'inviter_id si UNE SEULE invite
    a vu son compteur augmenter (attribution sûre), sinon None (ambiguïté → on
    n'attribue pas). Met à jour le cache au passage. FAIL-SAFE (None sur erreur)."""
    if guild is None:
        return None
    old = _invite_uses_cache.get(guild.id)
    try:
        invites = await guild.invites()
    except Exception:
        return None  # pas de perms → pas d'attribution
    try:
        new_snapshot = {}
        increased: list[tuple[str, int]] = []  # (code, inviter_id)
        for inv in invites:
            try:
                code = inv.code
                uses = int(inv.uses or 0)
            except Exception:
                continue
            new_snapshot[code] = uses
            prev = old.get(code) if old else None
            if prev is not None and uses == prev + 1:
                inviter = getattr(inv, "inviter", None)
                if inviter is not None and not getattr(inviter, "bot", False):
                    increased.append((code, int(inviter.id)))
        # Vanity URL : on rafraîchit le compteur mais on n'attribue PAS de parrain
        # (impossible de savoir QUI a partagé le vanity → jamais de fausse attribution).
        try:
            vanity = getattr(guild, "vanity_url_code", None)
            if vanity:
                vi = await guild.vanity_invite()
                if vi is not None:
                    new_snapshot[f"__vanity__{vanity}"] = int(getattr(vi, "uses", 0) or 0)
        except Exception:
            pass

        # Toujours rafraîchir le cache, même si l'attribution est ambiguë.
        _invite_uses_cache[guild.id] = new_snapshot

        # Attribution SÛRE seulement si exactement une invite humaine a +1.
        if len(increased) == 1:
            return increased[0][1]
        return None
    except Exception as ex:
        print(f"[referrals _match_inviter] {ex}")
        return None


async def on_member_join(member: discord.Member) -> Optional[int]:
    """Hook on_member_join : déduit le parrain et enregistre le parrainage EN ATTENTE.
    Le crédit est DIFFÉRÉ (cf. try_award_pending). Retourne l'inviter_id si détecté.
    FAIL-SAFE : ne lève jamais, ne bloque jamais le join."""
    if not member or not member.guild or member.bot or _get_db is None:
        # Même si on n'enregistre rien, on doit garder le cache à jour pour ne pas
        # « rater » la prochaine attribution → on resynchronise quand même.
        try:
            if member and member.guild:
                await _match_inviter(member.guild)
        except Exception:
            pass
        return None
    try:
        inviter_id = await _match_inviter(member.guild)
        if inviter_id is None or inviter_id == member.id:
            return None
        # Enregistre EN ATTENTE (idempotent via PK guild_id+invitee_id). Si l'invité
        # était déjà là (re-join), on ne réécrit pas un parrainage existant.
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO referrals "
                "(guild_id, invitee_id, inviter_id, joined_at, rewarded) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, 0)",
                (member.guild.id, member.id, inviter_id),
            )
            await db.commit()
        return inviter_id
    except Exception as ex:
        print(f"[referrals on_member_join] {ex}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  GATE ANTI-ALT + CRÉDIT DIFFÉRÉ
# ═══════════════════════════════════════════════════════════════════════════════

def _account_age_days(member: discord.Member) -> int:
    try:
        created = member.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).days
    except Exception:
        return 0


async def _invitee_passes_gate(guild: discord.Guild, invitee_id: int) -> bool:
    """True si l'invité a fait ses preuves (activité réelle + compte assez âgé).
    FAIL-CLOSED : si on ne peut pas prouver l'éligibilité, on N'attribue PAS
    (mieux vaut ne pas récompenser qu'enrichir une ferme d'alts)."""
    try:
        member = guild.get_member(invitee_id)
        if member is None:
            return False  # parti / introuvable → pas de preuve d'activité réelle
        if member.bot:
            return False
        # GATE 2 : âge du compte.
        if _account_age_days(member) < MIN_INVITEE_ACCOUNT_AGE_DAYS:
            return False
        # GATE 1 : activité réelle (messages + vocal sur 14 j).
        if _activity_score is None:
            return False  # pas de moyen de prouver l'activité → fail-closed
        score = await _activity_score(guild.id, invitee_id)
        return int(score or 0) >= MIN_INVITEE_ACTIVITY
    except Exception as ex:
        print(f"[referrals _invitee_passes_gate] {ex}")
        return False


async def try_award_pending(guild: discord.Guild) -> int:
    """Re-vérifie tous les parrainages EN ATTENTE de la guilde et crédite le parrain
    pour ceux dont l'invité a passé la gate. Claim ATOMIQUE + anti-doublon par
    invitee_id. Retourne le nombre de parrains crédités. FAIL-OPEN (0 sur erreur)."""
    if guild is None or _get_db is None:
        return 0
    awarded = 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT invitee_id, inviter_id FROM referrals "
                "WHERE guild_id=? AND rewarded=0 LIMIT 200",
                (guild.id,),
            ) as cur:
                pending = await cur.fetchall()
        for invitee_id, inviter_id in pending:
            try:
                invitee_id = int(invitee_id)
                inviter_id = int(inviter_id)
            except Exception:
                continue
            if not await _invitee_passes_gate(guild, invitee_id):
                continue
            # Claim ATOMIQUE : on passe rewarded 0→1 sous condition. rowcount==1 →
            # c'est NOUS qui avons gagné le claim → on crédite. Sinon (course / déjà
            # payé) on ne crédite pas. Le crédit vient APRÈS le claim gagné (jamais
            # de double-crédit même en cas de double exécution de la tâche).
            try:
                async with _get_db() as db:
                    dc = await db.execute(
                        "UPDATE referrals SET rewarded=1, rewarded_at=CURRENT_TIMESTAMP "
                        "WHERE guild_id=? AND invitee_id=? AND rewarded=0",
                        (guild.id, invitee_id),
                    )
                    await db.commit()
                if getattr(dc, "rowcount", 0) != 1:
                    continue  # déjà réclamé par une autre exécution
            except Exception:
                continue
            # Crédit MODESTE du parrain (pièces). Si add_coins échoue, le claim reste
            # marqué (idempotent) : on ne re-tente pas en boucle, on n'over-crédite pas.
            if _add_coins is not None:
                try:
                    await _add_coins(guild.id, inviter_id, REWARD_COINS)
                except Exception:
                    pass
            awarded += 1
        return awarded
    except Exception as ex:
        print(f"[referrals try_award_pending] {ex}")
        return awarded


# ═══════════════════════════════════════════════════════════════════════════════
#  AFFICHAGE « Mes parrainages »
# ═══════════════════════════════════════════════════════════════════════════════

async def get_my_referrals(guild_id: int, inviter_id: int) -> dict:
    """Stats de parrainage d'un membre, pour le panneau hub. FAIL-OPEN.
    Retourne {total, rewarded, pending, coins_earned, invitees:[{id,rewarded}]}."""
    out = {
        "total": 0, "rewarded": 0, "pending": 0,
        "coins_earned": 0, "invitees": [],
    }
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT invitee_id, rewarded FROM referrals "
                "WHERE guild_id=? AND inviter_id=? "
                "ORDER BY rewarded DESC, joined_at DESC LIMIT 50",
                (int(guild_id), int(inviter_id)),
            ) as cur:
                rows = await cur.fetchall()
        for inv_id, rew in rows:
            r = int(rew or 0)
            out["invitees"].append({"id": int(inv_id), "rewarded": bool(r)})
            out["total"] += 1
            if r:
                out["rewarded"] += 1
            else:
                out["pending"] += 1
        out["coins_earned"] = out["rewarded"] * REWARD_COINS
    except Exception as ex:
        print(f"[referrals get_my_referrals] {ex}")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  TÂCHE QUOTIDIENNE (supervisée par bot.py — _SUPERVISED_MODULE_LOOPS)
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(hours=6)
async def referral_reward_task():
    """Re-vérifie les parrainages en attente de chaque serveur et crédite les
    parrains éligibles. FAIL-OPEN : un bug ne tue pas la boucle (le superviseur la
    ressuscite de toute façon). 6 h = réactif sans marteler la DB."""
    try:
        if _bot is None:
            return
        for guild in list(_bot.guilds):
            try:
                await try_award_pending(guild)
            except Exception as ex:
                print(f"[referrals referral_reward_task guild] {ex}")
    except Exception as ex:
        print(f"[referrals referral_reward_task] {ex}")


__all__ = [
    "setup",
    "init_db",
    "prime_guild_cache",
    "on_invite_create",
    "on_invite_delete",
    "on_member_join",
    "try_award_pending",
    "get_my_referrals",
    "referral_reward_task",
    "REWARD_COINS",
    "MIN_INVITEE_ACTIVITY",
    "MIN_INVITEE_ACCOUNT_AGE_DAYS",
]
