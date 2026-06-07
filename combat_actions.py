"""combat_actions.py — Actions de combat UNIVERSELLES (Phase 269+).

Helper partagé, réutilisable par TOUS les events de combat (boss du jour, boss
raid, world boss, mobs, climax) pour enrichir l'immersion sans surcharger ni
risquer les tempêtes 429.

Actions livrées (les deux n'affectent QUE les dégâts SORTANTS — aucun couplage
au chemin de riposte, donc intégration minimale et sûre) :
  ⚡ Charger (custom_id `cba_charge:<scope>`) — ta PROCHAINE attaque inflige +X %
     (état PAR JOUEUR, fenêtre courte, cooldown par joueur).
  📣 Crier  (custom_id `cba_shout:<scope>`)  — buff d'ÉQUIPE : +Y % de dégâts pour
     TOUS les attaquants pendant Z s (état PAR EVENT, cooldown partagé par event).

`<scope>` dans le custom_id = l'event_id (utilisé par 📣 Crier qui est partagé par
event ; ⚡ Charger est par joueur et n'utilise pas le scope pour sa logique).

ARCHITECTURE ANTI-429 (règles owner) :
  - Les boutons NE rafraîchissent PAS le panneau de combat (zéro edit/GET serveur)
    → ils se contentent d'un `defer(ephemeral=True)` + un followup éphémère.
  - Cooldown PAR JOUEUR / PAR EVENT vérifié AVANT tout réseau.
  - L'écho public de 📣 Crier est fail-soft, sans ping, auto-supprimé.

État 100 % EN MÉMOIRE (le combat est éphémère ; un reboot remet tout à zéro =
acceptable). FAIL-OPEN partout : la moindre erreur ⇒ multiplicateur neutre 1.0,
jamais de blocage du combat.

Intégration côté module de combat (UNE ligne, après calcul des dégâts) :
    import combat_actions as _ca
    damage = int(damage * _ca.consume_charge_mult(gid, uid) * _ca.shout_mult(gid, event_id))
"""
import time
import discord

# ─── Réglages (volontairement modestes — l'enjeu est tactique, pas inflationniste) ─
_CHARGE_MULT = 1.6        # ×1.6 sur la PROCHAINE attaque chargée
_CHARGE_TTL = 10.0        # s : fenêtre pour placer l'attaque chargée
_CHARGE_CD = 12.0         # s : cooldown PAR JOUEUR
_SHOUT_MULT = 1.10        # ×1.10 dégâts d'équipe
_SHOUT_TTL = 12.0         # s : durée du buff collectif
_SHOUT_CD = 25.0          # s : cooldown PAR EVENT (partagé par tout le serveur)

# ─── État en mémoire ───────────────────────────────────────────────────────────
_charge = {}       # (gid, uid)   -> expire_ts (attaque chargée en attente)
_shout = {}        # (gid, scope) -> expire_ts (buff d'équipe actif)
_charge_cd = {}    # (gid, uid)   -> last_ts
_shout_cd = {}     # (gid, scope) -> last_ts


def _now() -> float:
    return time.time()


def setup(*_args, **_kwargs):
    """Présent pour cohérence avec les autres modules. Aucune dépendance externe :
    l'état est pur en mémoire et les échos publics passent par l'interaction."""
    return


# ─── Lecture des multiplicateurs (appelée DANS le calcul de dégâts d'un module) ──
def consume_charge_mult(guild_id, user_id) -> float:
    """Retourne le multiplicateur de charge et le CONSOMME (une seule attaque)."""
    try:
        k = (int(guild_id), int(user_id))
        exp = _charge.get(k, 0.0)
        if exp and _now() < exp:
            _charge.pop(k, None)
            return _CHARGE_MULT
        if exp:
            _charge.pop(k, None)  # expiré → nettoie
    except Exception:
        pass
    return 1.0


def shout_mult(guild_id, scope_id) -> float:
    """Retourne le multiplicateur du buff d'équipe (ne le consomme pas : il dure
    _SHOUT_TTL s et profite à tous)."""
    try:
        k = (int(guild_id), int(scope_id))
        exp = _shout.get(k, 0.0)
        if exp and _now() < exp:
            return _SHOUT_MULT
        if exp:
            _shout.pop(k, None)
    except Exception:
        pass
    return 1.0


# ─── Armement (appelé par les boutons) ───────────────────────────────────────────
def _arm_charge(guild_id, user_id):
    """(ok, wait_s). Pose une attaque chargée si le cooldown joueur le permet."""
    k = (int(guild_id), int(user_id))
    now = _now()
    last = _charge_cd.get(k, 0.0)
    if now - last < _CHARGE_CD:
        return (False, int(_CHARGE_CD - (now - last)) + 1)
    _charge_cd[k] = now
    _charge[k] = now + _CHARGE_TTL
    return (True, 0)


def _arm_shout(guild_id, scope_id):
    """(ok, wait_s). Active le buff d'équipe si le cooldown PAR EVENT le permet."""
    k = (int(guild_id), int(scope_id))
    now = _now()
    last = _shout_cd.get(k, 0.0)
    if now - last < _SHOUT_CD:
        return (False, int(_SHOUT_CD - (now - last)) + 1)
    _shout_cd[k] = now
    _shout[k] = now + _SHOUT_TTL
    return (True, 0)


def _parse_scope(i: discord.Interaction) -> int:
    try:
        return int((i.data or {}).get("custom_id", "").split(":")[1])
    except Exception:
        return 0


# ─── Boutons persistants (DynamicItem — match du custom_id, survit au reboot) ────
class CombatChargeButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"cba_charge:(?P<scope>\d+)",
):
    def __init__(self, scope: int = 0):
        super().__init__(
            discord.ui.Button(label="⚡ Charger", style=discord.ButtonStyle.primary,
                              custom_id=f"cba_charge:{scope}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        try:
            return cls(int(match["scope"]))
        except Exception:
            return cls(0)

    async def callback(self, i: discord.Interaction):
        try:
            try:
                await i.response.defer(ephemeral=True)
            except Exception:
                pass
            if i.guild is None:
                return
            ok, wait = _arm_charge(i.guild.id, i.user.id)
            if not ok:
                # Revue 269 / règle anti-429 251.24 : un clic rejeté par cooldown
                # ne fait JAMAIS de followup (discord.py réessaie les followups sur
                # 429 → amplification). Le defer a déjà acquitté l'interaction.
                return
            try:
                await i.followup.send(
                    f"⚡ **Chargé !** Ta **prochaine attaque** infligera "
                    f"**+{int((_CHARGE_MULT - 1) * 100)} %** de dégâts "
                    f"(dans les {int(_CHARGE_TTL)} s — frappe vite !).",
                    ephemeral=True)
            except Exception:
                pass
        except Exception as ex:
            print(f"[cba_charge] {ex}")


class CombatShoutButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"cba_shout:(?P<scope>\d+)",
):
    def __init__(self, scope: int = 0):
        super().__init__(
            discord.ui.Button(label="📣 Crier", style=discord.ButtonStyle.secondary,
                              custom_id=f"cba_shout:{scope}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        try:
            return cls(int(match["scope"]))
        except Exception:
            return cls(0)

    async def callback(self, i: discord.Interaction):
        try:
            try:
                await i.response.defer(ephemeral=True)
            except Exception:
                pass
            if i.guild is None:
                return
            scope = _parse_scope(i)
            ok, wait = _arm_shout(i.guild.id, scope)
            if not ok:
                # Revue 269 / règle anti-429 251.24 : clic rejeté par cooldown =
                # ZÉRO followup. Le buff d'équipe est de toute façon déjà actif.
                return
            try:
                await i.followup.send(
                    f"📣 **Tu galvanises l'équipe !** +{int((_SHOUT_MULT - 1) * 100)} % de "
                    f"dégâts pour **tous** pendant {int(_SHOUT_TTL)} s.", ephemeral=True)
            except Exception:
                pass
            # Écho public fail-soft, SANS ping, auto-supprimé (1 max / _SHOUT_CD s par event).
            try:
                nm = discord.utils.escape_markdown(getattr(i.user, "display_name", "Un héros"))
                if i.channel is not None:
                    await i.channel.send(
                        f"📣 **{nm}** galvanise les troupes — **+{int((_SHOUT_MULT - 1) * 100)} % "
                        f"de dégâts pour tous** pendant {int(_SHOUT_TTL)} s ! 🔥",
                        allowed_mentions=discord.AllowedMentions.none(),
                        delete_after=_SHOUT_TTL)
            except Exception:
                pass
        except Exception as ex:
            print(f"[cba_shout] {ex}")


def register_persistent_views(bot_instance):
    """Enregistre les boutons d'action de combat (match du custom_id au clic)."""
    if bot_instance is None:
        return
    try:
        bot_instance.add_dynamic_items(CombatChargeButton, CombatShoutButton)
    except Exception as ex:
        print(f"[combat_actions register] {ex}")


__all__ = [
    "setup", "register_persistent_views", "consume_charge_mult", "shout_mult",
    "CombatChargeButton", "CombatShoutButton",
]
