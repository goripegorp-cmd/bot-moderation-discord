"""nettoyage.py — un serveur propre (19/10/2026).

« Dès qu'elles sont vieilles d'un mois, tu les enlèves » ; « qu'on évite d'avoir des salons avec
des millions de messages, qu'on regroupe l'essentiel et que ça se nettoie automatiquement ».

  · Journal en fils : chaque salon de logs reçoit un fil « 📋 JJ/MM/AAAA » par jour ; un fil de
    plus de RETENTION_JOURS est supprimé d'un seul appel (la journée entière part avec lui).
  · Salons de flux (actualités Roblox, sneak peeks) et racines des salons de logs : les messages
    du bot et de ses webhooks de plus de RETENTION_JOURS sont retirés, un par un — Discord
    n'efface en groupe que les messages de moins de 14 jours.
  · Remise à neuf : un salon de logs qui n'a JAMAIS connu que le bot et porte des messages de
    plus de RETENTION_JOURS est recréé à l'identique (une seule fois) — des millions de
    messages ne s'effacent pas un par un.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import discord

RETENTION_JOURS = 30
PREFIXE_FIL = "📋 "
MAX_SUPPRESSIONS = 200
_fils: dict = {}
_verrous: dict = {}


def _limite(jours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=jours)


def nom_du_jour(quand: datetime | None = None) -> str:
    return f"{PREFIXE_FIL}{(quand or datetime.now(timezone.utc)):%d/%m/%Y}"


async def fil_du_jour(salon):
    """Le fil du jour d'un salon de logs, créé au premier log de la journée. Sans les droits,
    le salon lui-même (rien ne se perd)."""
    if not isinstance(salon, discord.TextChannel):
        return salon
    nom = nom_du_jour()
    cle = (salon.id, nom)
    if cle in _fils:
        return _fils[cle]
    async with _verrous.setdefault(salon.id, asyncio.Lock()):
        if cle in _fils:
            return _fils[cle]
        fil = next((t for t in salon.threads if t.name == nom), None)
        if fil is None:
            p = salon.permissions_for(salon.guild.me)
            if not (p.create_public_threads and p.send_messages_in_threads):
                return salon
            fil = await salon.create_thread(name=nom, type=discord.ChannelType.public_thread,
                                            auto_archive_duration=1440, reason="Journal du jour")
        if len(_fils) > 500:
            _fils.clear()
        _fils[cle] = fil
        return fil


async def supprimer_vieux_fils(salon, jours: int = RETENTION_JOURS) -> int:
    limite = _limite(jours)
    fils = [t for t in salon.threads]
    try:
        async for t in salon.archived_threads(limit=200):
            fils.append(t)
    except discord.HTTPException as ex:
        print(f"[nettoyage] fils archivés illisibles ({salon.id}) : {ex}")
    n = 0
    for t in fils:
        if t.name.startswith(PREFIXE_FIL) and t.created_at and t.created_at < limite:
            try:
                await t.delete()
                n += 1
                await asyncio.sleep(1)
            except discord.HTTPException as ex:
                print(f"[nettoyage] fil {t.id} non supprimé : {ex}")
    return n


def _du_bot(m, bot_id: int, webhooks_du_bot=frozenset()) -> bool:
    """Le bot lui-même, ou un de SES webhooks. 19/10/2026 (audit) : n'importe quel webhook comptait,
    et les messages d'autres services (salons suivis, Discohook) partaient avec la purge."""
    return m.author.id == bot_id or (m.webhook_id is not None and m.webhook_id in webhooks_du_bot)


async def webhooks_du_bot(salon, bot_id: int) -> frozenset:
    """Les webhooks créés par le bot dans ce salon (celui du fil, pour un fil)."""
    cible = salon.parent if isinstance(salon, discord.Thread) else salon
    lire = getattr(cible, "webhooks", None)
    if lire is None:
        return frozenset()
    try:
        return frozenset(wh.id for wh in await lire() if getattr(wh.user, "id", 0) == bot_id)
    except discord.HTTPException as ex:
        print("[nettoyage] webhooks illisibles : seuls les messages du bot lui-même partent")
        print(f"[nettoyage:DETAIL] salon={salon.id} {ex}")
        return frozenset()


async def purger_salon(salon, bot_id: int, jours: int = RETENTION_JOURS,
                       maximum: int = MAX_SUPPRESSIONS) -> int:
    """Les messages du bot (et de ses webhooks) de plus de `jours`, du plus ancien au plus
    récent, `maximum` par passage. Les messages des membres ne sont jamais touchés, les messages
    épinglés non plus (le menu du salon des logs)."""
    ids = await webhooks_du_bot(salon, bot_id)
    n = 0
    async for m in salon.history(limit=maximum * 5, before=_limite(jours), oldest_first=True):
        if not _du_bot(m, bot_id, ids) or getattr(m, "pinned", False):
            continue
        try:
            await m.delete()
            n += 1
        except discord.NotFound:
            pass
        except discord.Forbidden:
            # Sans le droit de gérer les messages : on s'arrête là pour ce salon, sans casser la passe.
            print("[nettoyage] suppression refusée : droit « Gérer les messages » manquant")
            print(f"[nettoyage:DETAIL] salon={salon.id}")
            break
        except discord.HTTPException as ex:
            print(f"[nettoyage] message {m.id} non supprimé : {ex}")
        if n >= maximum:
            break
        await asyncio.sleep(1.2)
    return n


async def a_remettre_a_neuf(salon, bot_id: int, jours: int = RETENTION_JOURS) -> bool:
    """Seulement un salon de logs PUR : ses 50 derniers messages viennent tous du bot, et le
    plus ancien a plus de `jours`."""
    recents = [m async for m in salon.history(limit=50)]
    if not recents or not all(_du_bot(m, bot_id) for m in recents):
        return False
    async for m in salon.history(limit=1, oldest_first=True):
        return m.created_at < _limite(jours)
    return False


async def remettre_a_neuf(salon, raison: str = "Journal remis à neuf (plus de 30 jours)"):
    """Recrée le salon à l'identique (nom, sujet, catégorie, permissions, position), puis
    supprime l'ancien. Rend le nouveau salon."""
    nouveau = await salon.clone(reason=raison)
    try:
        await nouveau.edit(position=salon.position)
    except discord.HTTPException as ex:
        print(f"[nettoyage] position non reprise ({salon.id}) : {ex}")
    await salon.delete(reason=raison)
    return nouveau


def remplacer_id(valeur, ancien: int, nouveau: int):
    """La même structure, l'identifiant `ancien` remplacé partout (int ou texte)."""
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, int):
        return nouveau if valeur == ancien else valeur
    if isinstance(valeur, str):
        return str(nouveau) if valeur == str(ancien) else valeur
    if isinstance(valeur, list):
        return [remplacer_id(v, ancien, nouveau) for v in valeur]
    if isinstance(valeur, dict):
        return {k: remplacer_id(v, ancien, nouveau) for k, v in valeur.items()}
    return valeur
