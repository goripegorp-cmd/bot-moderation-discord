"""ui_usage.py — Mesure d'usage RÉELLE : quels menus/boutons/commandes servent (owner 2026-07-17).

POURQUOI CE MODULE EXISTE. L'owner demande de « désactiver les menus qui ne servent plus ».
Réponse honnête au moment de la demande : **c'était INMESURABLE** — aucune table n'enregistrait
l'ouverture d'un panneau ni le clic d'un bouton (`activity_tracking` = messages/vocal,
`nudge_stats` = les nudges SEULEMENT). Supprimer un menu aurait été de la spéculation, ce qui
viole la règle n°1 (ne jamais casser ce qui sert à quelqu'un sur une intuition).
→ Ce module INSTRUMENTE. Les faits arrivent après ~30 jours d'usage réel ; les EVENTS, eux, sont
  mesurables IMMÉDIATEMENT (tables déjà alimentées) — cf. `events_report()`.

COMMENT C'EST BRANCHÉ (choix important). Le point de mesure est l'événement **`on_interaction`**
de discord.py — API PUBLIQUE, listener SÉPARÉ :
  • un plantage ici NE PEUT PAS casser un bouton (le listener est indépendant du callback) ;
  • il capte TOUT (boutons, selects, commandes) sans dépendre de l'héritage.
Les deux autres pistes ont été ÉCARTÉES pour de vraies raisons :
  • `interaction_check` → **129 classes de bot.py définissent la leur** → le MRO écraserait le
    hook et on ne compterait qu'une partie des panneaux (mesure faussée = pire que rien) ;
  • `_scheduled_task` → API PRIVÉE de discord.py ; une signature qui change casserait TOUS les
    boutons d'un coup. Inacceptable pour de la simple télémétrie.

COÛT : **zéro I/O sur le chemin chaud**. On incrémente un compteur en RAM ; une boucle écrit en
base toutes les 60 s (`flush_task`). Buffer borné.
VIE PRIVÉE : on ne stocke **aucun ID de membre**, aucun contenu — seulement « ce bouton a été
cliqué N fois le jour J ». Purge automatique au-delà de `_RETENTION_DAYS`.

Module PUR : aucune dépendance à bot.py. `get_db` injecté par setup().
"""
from __future__ import annotations

import re
import sys as _sys

import discord as _discord

import ui_v2 as _v2

_get_db = None

_RETENTION_DAYS = 120          # au-delà, la donnée n'aide plus à décider → purge
_MAX_BUFFER = 20000            # borne mémoire (garde-fou : ~1 clé par bouton/jour, jamais atteint)


def setup(get_db_fn) -> None:
    """Injecte l'accès DB (appelé depuis bot.py au boot)."""
    global _get_db
    _get_db = get_db_fn


# ═══════════════════════════════════════════════════════════════════════════════
#  📥 COLLECTE — RAM uniquement, zéro I/O sur le chemin chaud
# ═══════════════════════════════════════════════════════════════════════════════

# (guild_id, surface, action, day) -> nb de clics pas encore écrits
_buffer: dict = {}


def _norm(cid: str) -> str:
    """`sanction_ban_123456789` → `sanction_ban` ; `vctl:lock:998877` → `vctl_lock`.

    Les custom_id embarquent des IDs volatils (snowflakes, id d'event…). Sans ce nettoyage,
    CHAQUE clic créerait sa propre ligne et on ne pourrait rien regrouper : le tableau dirait
    « 8000 boutons cliqués 1 fois » au lieu de « ce bouton-là : 8000 clics ».
    """
    try:
        parts = [p for p in re.split(r'[:_\-]', str(cid or '')) if p and not p.isdigit()]
        return ('_'.join(parts) or str(cid or '?'))[:80]
    except Exception:
        return '?'


def record(guild_id: int, surface: str, action: str, day: str) -> None:
    """Incrémente en MÉMOIRE. FAIL-SAFE absolu : la télémétrie ne casse jamais une interaction."""
    try:
        if not guild_id:
            return
        k = (int(guild_id), str(surface)[:40], str(action)[:80], str(day)[:10])
        _buffer[k] = _buffer.get(k, 0) + 1
        if len(_buffer) > _MAX_BUFFER:      # garde-fou : on jette plutôt que de gonfler la RAM
            _buffer.clear()
    except Exception:
        pass


def observe(interaction, day: str) -> None:
    """Traduit une interaction Discord en (surface, action). Appelé par le listener bot.py."""
    try:
        it = getattr(interaction, 'type', None)
        gid = getattr(getattr(interaction, 'guild', None), 'id', 0)
        if not gid:
            return                                   # MP → hors sujet (on mesure les menus du serveur)
        if it == _discord.InteractionType.component:
            cid = (getattr(interaction, 'data', None) or {}).get('custom_id') or '?'
            act = _norm(cid)
            record(gid, act.split('_')[0][:40] or 'bouton', act, day)
        elif it == _discord.InteractionType.application_command:
            name = (getattr(interaction, 'command', None) and interaction.command.qualified_name) \
                   or (getattr(interaction, 'data', None) or {}).get('name') or '?'
            record(gid, 'commande', str(name)[:80], day)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  💾 PERSISTANCE
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db() -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ui_usage (
                    guild_id INTEGER NOT NULL,
                    surface  TEXT    NOT NULL,
                    action   TEXT    NOT NULL,
                    day      TEXT    NOT NULL,
                    count    INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, surface, action, day)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ui_usage_day ON ui_usage(guild_id, day)")
            await db.commit()
    except Exception as ex:
        print(f"[ui_usage init_db] {ex}", file=_sys.stderr, flush=True)


async def flush() -> int:
    """Vide le buffer en base. Renvoie le nb de lignes écrites. FAIL-SAFE."""
    if _get_db is None or not _buffer:
        return 0
    # On DÉTACHE le buffer d'abord : les clics qui arrivent pendant l'écriture (il y a des `await`
    # plus bas) atterrissent dans le dict vidé et ne sont pas perdus — et on n'itère pas un dict
    # qu'on mute en même temps.
    pending = dict(_buffer)
    _buffer.clear()
    try:
        async with _get_db() as db:
            for (gid, surface, action, day), n in pending.items():
                await db.execute(
                    "INSERT INTO ui_usage(guild_id, surface, action, day, count) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(guild_id, surface, action, day) DO UPDATE SET "
                    "count = count + excluded.count",
                    (gid, surface, action, day, int(n)),
                )
            await db.commit()
        return len(pending)
    except Exception as ex:
        print(f"[ui_usage flush] {ex}", file=_sys.stderr, flush=True)
        return 0


async def purge_old() -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                f"DELETE FROM ui_usage WHERE day < date('now','-{int(_RETENTION_DAYS)} day')")
            await db.commit()
    except Exception as ex:
        print(f"[ui_usage purge_old] {ex}", file=_sys.stderr, flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  📊 LECTURE — les faits qui autorisent (ou non) une suppression
# ═══════════════════════════════════════════════════════════════════════════════

async def ui_report(guild_id: int, days: int = 30) -> dict:
    """{'rows': [(surface, action, clics, jours_actifs, dernier)], 'depuis': 'YYYY-MM-DD'}"""
    out = {'rows': [], 'depuis': None}
    if _get_db is None:
        return out
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT surface, action, SUM(count), COUNT(DISTINCT day), MAX(day) "
                "FROM ui_usage WHERE guild_id=? AND day >= date('now', ?) "
                "GROUP BY surface, action ORDER BY SUM(count) ASC",
                (int(guild_id), f"-{int(days)} day"),
            ) as cur:
                out['rows'] = list(await cur.fetchall())
            async with db.execute(
                "SELECT MIN(day) FROM ui_usage WHERE guild_id=?", (int(guild_id),)
            ) as cur:
                r = await cur.fetchone()
            out['depuis'] = r[0] if r and r[0] else None
    except Exception as ex:
        print(f"[ui_usage ui_report] {ex}", file=_sys.stderr, flush=True)
    return out


async def events_report(guild_id: int, days: int = 30) -> dict:
    """Mesure des EVENTS — répondable TOUT DE SUITE (tables déjà alimentées).

    ⚠️ `COUNT(DISTINCT …)` partout : les LEFT JOIN sur les participants DUPLIQUENT la ligne
    d'event (1 ligne par attaquant). Un `SUM(e.victory)` ou `SUM(CASE WHEN status='killed')` nu
    compterait donc les victoires ×  le nombre de joueurs — chiffre faux, et faux vers le HAUT.
    """
    out = {'par_type': [], 'zero_joueur': [], 'cumul': [], 'boss': [], 'actifs': 0}
    if _get_db is None:
        return out
    _since = f"-{int(days)} day"
    try:
        async with _get_db() as db:
            # A) Quel type d'event mobilise vraiment ?
            try:
                async with db.execute(
                    "SELECT e.event_type, COUNT(DISTINCT e.id), COUNT(DISTINCT p.user_id), "
                    "       COALESCE(SUM(p.attacks_count),0), "
                    "       COUNT(DISTINCT CASE WHEN e.victory=1 THEN e.id END) "
                    "FROM events e LEFT JOIN event_participants p ON p.event_id = e.id "
                    "WHERE e.guild_id=? AND e.started_at >= datetime('now', ?) "
                    "GROUP BY e.event_type ORDER BY COUNT(DISTINCT p.user_id) ASC",
                    (int(guild_id), _since),
                ) as cur:
                    out['par_type'] = list(await cur.fetchall())
            except Exception:
                pass
            # B) Events lancés que PERSONNE n'a touché (le signal le plus dur)
            try:
                async with db.execute(
                    "SELECT e.event_type, COUNT(*) FROM events e "
                    "WHERE e.guild_id=? AND e.started_at >= datetime('now', ?) "
                    "  AND NOT EXISTS (SELECT 1 FROM event_participants p WHERE p.event_id = e.id) "
                    "GROUP BY e.event_type ORDER BY COUNT(*) DESC",
                    (int(guild_id), _since),
                ) as cur:
                    out['zero_joueur'] = list(await cur.fetchall())
            except Exception:
                pass
            # C) Compteur maison CUMULATIF (⚠️ depuis toujours, PAS 30 j — ne pas mélanger avec A)
            try:
                async with db.execute(
                    "SELECT event_kind, count_started, count_participations, count_completions, "
                    "       last_run_at FROM event_engagement WHERE guild_id=? "
                    "ORDER BY count_participations ASC",
                    (int(guild_id),),
                ) as cur:
                    out['cumul'] = list(await cur.fetchall())
            except Exception:
                pass
            # D) Boss du jour (module séparé)
            try:
                async with db.execute(
                    "SELECT b.boss_id, COUNT(DISTINCT b.id), COUNT(DISTINCT a.user_id), "
                    "       COALESCE(SUM(a.attack_count),0), "
                    "       COUNT(DISTINCT CASE WHEN b.status='killed' THEN b.id END) "
                    "FROM daily_boss_events b "
                    "LEFT JOIN daily_boss_attackers a ON a.event_id = b.id "
                    "WHERE b.guild_id=? AND b.started_at >= datetime('now', ?) "
                    "GROUP BY b.boss_id ORDER BY COUNT(DISTINCT a.user_id) ASC",
                    (int(guild_id), _since),
                ) as cur:
                    out['boss'] = list(await cur.fetchall())
            except Exception:
                pass
            # F) Dénominateur OBLIGATOIRE — sans lui, « 12 joueurs » ne veut rien dire
            try:
                async with db.execute(
                    "SELECT COUNT(*) FROM activity_tracking "
                    "WHERE guild_id=? AND last_message >= datetime('now', ?)",
                    (int(guild_id), _since),
                ) as cur:
                    r = await cur.fetchone()
                out['actifs'] = int(r[0]) if r else 0
            except Exception:
                pass
    except Exception as ex:
        print(f"[ui_usage events_report] {ex}", file=_sys.stderr, flush=True)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  🖥️ PANNEAU — Components V2, 3 onglets. Aucun chiffre sans son dénominateur.
# ═══════════════════════════════════════════════════════════════════════════════

def _pct(n: int, total: int) -> str:
    try:
        return f"{round(100.0 * int(n) / int(total))} %" if total else "—"
    except Exception:
        return "—"


async def _events_items(guild, days: int):
    v2 = _v2
    r = await events_report(guild.id, days)
    items = [v2.title(f"📊 Usage réel — events · {days} derniers jours"),
             v2.subtitle(f"Membres actifs sur la période : **{r['actifs']}** — "
                         f"c'est le dénominateur : « 12 joueurs » ne veut rien dire sans lui."),
             v2.divider()]
    if r['par_type']:
        rows = []
        for et, lances, joueurs, clics, victoires in r['par_type'][:12]:
            rows.append((f"`{et}`",
                         f"{joueurs} joueurs ({_pct(joueurs, r['actifs'])} des actifs) · "
                         f"{lances} lancés · {clics} clics · {victoires} victoires"))
        items += [v2.title("Par type d'event — du MOINS joué au plus", level=2),
                  v2.kv_block(rows)]
    else:
        items.append(v2.body("_Aucun event lancé sur la période._"))
    if r['zero_joueur']:
        items += [v2.divider(), v2.title("⚠️ Lancés que PERSONNE n'a touché", level=2),
                  v2.kv_block([(f"`{et}`", f"{n} fois à 0 joueur") for et, n in r['zero_joueur'][:8]])]
    if r['boss']:
        rows = []
        for bid, appar, joueurs, atk, tues in r['boss'][:8]:
            rows.append((f"`{bid}`", f"{joueurs} joueurs · {appar} apparitions · "
                                     f"{atk} attaques · {tues} tués"))
        items += [v2.divider(), v2.title("Boss du jour — du plus IGNORÉ au plus joué", level=2),
                  v2.kv_block(rows)]
    items += [v2.divider(),
              v2.body("⚠️ **Ne supprime rien sur ce seul tableau.** Un event à 0 joueur peut "
                      "n'avoir jamais été **configuré** ou jamais **tourné** — « pas utilisé » et "
                      "« pas branché » se ressemblent en base et se corrigent très différemment. "
                      "Croise avec l'onglet cumul (`last_run_at`) avant de trancher.")]
    return items


async def _ui_items(guild, days: int, *, kind: str):
    """kind='menus' (boutons/selects) ou 'commandes'."""
    v2 = _v2
    r = await ui_report(guild.id, days)
    label = "menus & boutons" if kind == 'menus' else "commandes"
    # `observe()` range les slash commands sous la surface 'commande' ; tout le reste est un
    # composant (bouton/select), rangé sous la 1re partie de son custom_id.
    rows_all = [x for x in r['rows']
                if (x[0] == 'commande') is (kind == 'commandes')]
    items = [v2.title(f"📊 Usage réel — {label} · {days} derniers jours")]
    if not r['depuis']:
        items += [v2.subtitle("⏳ **La mesure vient de démarrer.**"),
                  v2.divider(),
                  v2.body("Avant aujourd'hui, **rien n'enregistrait les clics** : ni l'ouverture "
                          "d'un panneau, ni l'appui sur un bouton. Je ne pouvais donc pas te dire "
                          "quels menus servent — et te répondre au feeling aurait risqué de "
                          "supprimer un menu utilisé.\n\n"
                          "Le compteur tourne maintenant. **Reviens dans ~30 jours** : tu auras la "
                          "liste triée du moins cliqué au plus cliqué, et là on pourra couper sur "
                          "des faits.\n\n"
                          "-# Aucun ID de membre n'est enregistré — seulement « ce bouton, N clics, "
                          "tel jour ».")]
        return items
    items.append(v2.subtitle(f"Mesuré depuis le **{r['depuis']}** · "
                             f"{len(rows_all)} {label} distincts vus"))
    items.append(v2.divider())
    if not rows_all:
        items.append(v2.body(f"_Aucune donnée pour les {label} sur la période._"))
        return items
    items.append(v2.title("🔻 Les MOINS utilisés — candidats à la désactivation", level=2))
    items.append(v2.kv_block([(f"`{a}`", f"{c} clics · {j} jours actifs · vu le {d}")
                              for _s, a, c, j, d in rows_all[:12]]))
    if len(rows_all) > 12:
        items.append(v2.divider())
        items.append(v2.title("🔺 Les PLUS utilisés — à ne surtout pas toucher", level=2))
        items.append(v2.kv_block([(f"`{a}`", f"{c} clics · {j} jours actifs")
                                  for _s, a, c, j, _d in rows_all[-6:][::-1]]))
    items.append(v2.divider())
    items.append(v2.body("💡 Un bouton **absent de cette liste** n'a **jamais** été cliqué depuis "
                         f"le {r['depuis']} — c'est le vrai code mort, et le signal le plus sûr "
                         "pour désactiver."))
    return items


class UsagePanel(_v2.BasePanel):
    """Panneau `/mod usage` — 3 onglets. Non persistant (éphémère, timeout 10 min) : inutile de
    le réenregistrer au boot. `BasePanel` restreint déjà l'usage à celui qui l'a ouvert."""

    def __init__(self, owner, guild, days: int = 30, tab: str = 'events'):
        super().__init__(owner)
        self.guild = guild
        self.days = days
        self.tab = tab

    async def build(self):
        if self.tab == 'events':
            items = await _events_items(self.guild, self.days)
            color = _v2.Palette.PRIMARY
        elif self.tab == 'commandes':
            items = await _ui_items(self.guild, self.days, kind='commandes')
            color = _v2.Palette.INFO
        else:
            items = await _ui_items(self.guild, self.days, kind='menus')
            color = _v2.Palette.ACCENT
        self.add_item(_v2.container(*items, color=color))
        row = _discord.ui.ActionRow()
        for _key, _lbl, _emo in (('events', "Events", "🎮"),
                                 ('menus', "Menus & boutons", "🖱️"),
                                 ('commandes', "Commandes", "⌨️")):
            b = _discord.ui.Button(
                label=_lbl, emoji=_emo,
                style=(_discord.ButtonStyle.primary if _key == self.tab
                       else _discord.ButtonStyle.secondary),
                disabled=(_key == self.tab))
            b.callback = self._make_cb(_key)
            row.add_item(b)
        self.add_item(row)
        return self

    def _make_cb(self, key: str):
        async def _cb(i: _discord.Interaction):
            # DEFER-FIRST : les requêtes ci-dessous peuvent prendre > 3 s sur une grosse base.
            try:
                if not i.response.is_done():
                    await i.response.defer()
            except Exception:
                pass
            try:
                v = await UsagePanel(self.owner, self.guild, self.days, key).build()
                await i.edit_original_response(view=v)
            except Exception as ex:
                print(f"[ui_usage tab {key}] {ex}", file=_sys.stderr, flush=True)
        return _cb


async def build_panel(owner, guild, days: int = 30):
    return await UsagePanel(owner, guild, days, 'events').build()
