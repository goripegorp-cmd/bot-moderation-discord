#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refonte de `/configure` (HANDOFF.md §2 point 1 + §8).

Trois opérations, dans un seul passage :
  1. Remplace `MainPanelV2` — le select passe de 13 sections (dont 10 condamnées)
     aux 8 sections du périmètre gardé, aux standards UI du §8.
  2. Supprime `SecurityPanelV2`, devenu inatteignable : ses 5 enfants sont
     désormais exposés directement à la racine (aplatissement demandé au §8).
  3. Recâble les 5 boutons « ◀️ Retour » qui pointaient vers `SecurityPanelV2`.

Méthode imposée (HANDOFF.md §4) : preview par défaut, `--apply` pour écrire,
`ast.parse()` AVANT toute écriture, et vérification d'un jeton attendu dans
chaque plage avant de la couper (anti-décalage de numéros de ligne).

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/refonte_configure.py            # preview
    PYTHONIOENCODING=utf-8 python3 outils/refonte_configure.py --apply    # écrit
"""
from __future__ import annotations

import ast
import sys

FICHIER = "bot.py"

# ── Jetons attendus : si l'un manque, les numéros de ligne ont bougé → abandon ──
JETONS = {
    "MainPanelV2": [
        "class MainPanelV2(LayoutView):",
        "custom_id=\"mpv2_module\"",
        "'security':     lambda: SecurityPanelV2(self.u, self.g),",
    ],
    "SecurityPanelV2": [
        "class SecurityPanelV2(LayoutView):",
        "custom_id=\"secv2_mod\"",
        "[SecurityPanelV2 _cb_back]",
    ],
}

# Commentaire d'en-tête à retirer avec SecurityPanelV2 (il ne décrit que lui).
ENTETE_SECURITY = "#  🛡️ SÉCURITÉ — Panel V2 unifié (Phase 4.1)"

RETOUR_AVANT = "        v = SecurityPanelV2(self.u, self.g)"
RETOUR_APRES = "        v = MainPanelV2(self.u, self.g)"
RETOURS_ATTENDUS = 5

# Commentaires qui décrivaient l'ancien saut par le hub Sécurité : ils
# deviendraient mensongers, on les remet à jour dans le même passage.
COMMENTAIRE_APRES = "        # Refonte 2026-08 : retour direct à la racine /configure (MainPanelV2)."
COMMENTAIRES_AVANT = [
    "        # Phase 4 : retour vers SecurityPanelV2 (le hub Sécurité unifié)",
    "        # Phase 4 : retour vers SecurityPanelV2",
    "        # Phase 4.6 : retour vers SecurityPanelV2 (le hub)",
]
COMMENTAIRES_ATTENDUS = 4

# ── Le nouveau panneau racine ────────────────────────────────────────────────
NOUVEAU = '''# ═══════════════════════════════════════════════════════════════════════════════
#  ⚙️ /configure — PANNEAU RACINE (refonte 2026-08 : périmètre SÉCURITÉ)
#
#  Le serveur a été recentré sur la sécurité. Ce panneau n'expose plus QUE le
#  périmètre gardé : protections, sanctions, immunités, anti-raid, tickets,
#  logs, AFK, RGPD. Les 10 sections retirées du select (réseaux sociaux, jeux,
#  délégations, animations, progression, permissions, événements, entraide,
#  contrôles serveur) n'ont AUCUNE autre porte d'entrée — les retirer d'ici les
#  rend inatteignables. C'était la dernière racine qui maintenait en vie
#  ~11 600 lignes de panneaux de configuration.
#
#  ⚠️ PIÈGE À NE PAS DÉFAIRE — `_build()` doit rester SYNCHRONE et suffisante.
#     13 appelants font `MainPanelV2(u, g)` puis `edit_message(view=...)` sans
#     jamais passer par `render_to()`. Une LayoutView sans composant = erreur
#     400 côté Discord. Tout ce qui demande la base de données va donc dans
#     `render_to()`, jamais dans `__init__`.
# ═══════════════════════════════════════════════════════════════════════════════

#  Sections du select, dans l'ordre d'affichage.
#  Les classes de panneaux sont définies PLUS BAS dans bot.py : impossible de
#  les référencer ici, la résolution est donc paresseuse (`_module_select`).
#  Format : (valeur, emoji, libellé, description)
_CONFIG_SECTIONS = [
    ("protections", "🛡️", "Protections",       "Insultes · spam · liens · phishing · scam · images · QR"),
    ("sanctions",   "⚖️", "Sanctions",         "Salon de logs de modération · rôles autorisés"),
    ("immunites",   "👮", "Staff & immunités", "Qui n'est jamais sanctionné automatiquement"),
    ("antiraid",    "⚔️", "Anti-Raid",         "Vague d'arrivées · âge de compte minimum · riposte"),
    ("tickets",     "🎫", "Tickets",           "Panneaux d'ouverture · rôle staff · logs · blacklist"),
    ("logs",        "📋", "Logs & Audit",      "Un salon · toutes les catégories d'événements"),
    ("afk",         "💤", "Rôle AFK",          "Rôle automatique pour les membres inactifs"),
    ("rgpd",        "🔒", "Données & RGPD",    "Droit à l'effacement (art. 17) · rétention"),
]


class MainPanelV2(LayoutView):
    """Panneau racine de `/configure` — périmètre sécurité uniquement.

    Un select de sections (§8 : plus de menus par réactions, plus de murs de
    texte) + un résumé d'état lisible d'un coup d'œil. Chaque section ouvre son
    propre panneau, qui revient ici par son bouton « ◀️ Retour ».
    """

    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self._build()

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    # ─────────────────────────────────────────────────────────────────────────
    #  Construction — SYNCHRONE (voir l'avertissement en tête de section)
    # ─────────────────────────────────────────────────────────────────────────
    def _build(self, etat: dict | None = None):
        self.clear_items()
        items: list = []

        sous_titre = f"**{self.g.name}** · 👑 {self.u.display_name}"
        if self.g.icon:
            items.append(v2_section(
                v2_title("⚙️ Configuration"),
                v2_subtitle(sous_titre),
                accessory=v2_thumb(self.g.icon.url),
            ))
        else:
            items.append(v2_title("⚙️ Configuration"))
            items.append(v2_subtitle(sous_titre))

        items.append(v2_divider())

        # Résumé d'état — présent uniquement par le chemin async (`render_to`).
        if etat is not None:
            items.append(v2_body(
                f"🛡️ **Protections** · `{etat['prot_on']}/{etat['prot_total']}` actives\\n"
                f"⚖️ **Sanctions** · `{etat['infractions']}` au casier · logs {etat['mod_log']}\\n"
                f"👮 **Immunités** · `{etat['immune_roles']}` rôles · `{etat['immune_users']}` membres\\n"
                f"⚔️ **Anti-Raid** · {etat['antiraid']}\\n"
                f"🎫 **Tickets** · {etat['tickets']}\\n"
                f"📋 **Logs** · {etat['logs']}"
            ))
            items.append(v2_divider())

        sel = Select(
            placeholder="Choisis une section à configurer…",
            options=[
                discord.SelectOption(label=libelle, value=valeur, emoji=emoji, description=description)
                for valeur, emoji, libelle, description in _CONFIG_SECTIONS
            ],
            custom_id="cfgv2_section",
        )
        sel.callback = self._module_select

        b_refresh = Button(
            label="Actualiser", emoji="🔄",
            style=discord.ButtonStyle.secondary, custom_id="cfgv2_refresh",
        )
        b_refresh.callback = self._cb_refresh

        b_close = Button(
            label="Fermer", emoji="✖️",
            style=discord.ButtonStyle.danger, custom_id="cfgv2_close",
        )
        b_close.callback = self._close

        items.append(discord.ui.ActionRow(sel))
        items.append(discord.ui.ActionRow(b_refresh, b_close))

        self.add_item(v2_container(*items, color=Palette.PRIMARY))

    # ─────────────────────────────────────────────────────────────────────────
    #  Lecture d'état — chaque bloc est isolé : une panne de base ne doit
    #  JAMAIS empêcher le panneau de s'ouvrir (doctrine : dispo = fail-open).
    # ─────────────────────────────────────────────────────────────────────────
    async def _collect_etat(self) -> dict:
        try:
            c = await cfg(self.g.id)
        except Exception as ex:
            print(f"[MainPanelV2 _collect_etat cfg] {ex}")
            c = {}

        etat = {
            'prot_total': len(PROTS),
            'prot_on': sum(1 for k, _, _ in PROTS if c.get(k)),
            'infractions': 0,
            'immune_roles': 0,
            'immune_users': 0,
        }

        try:
            async with get_db() as db:
                for cle, table in (
                    ('infractions', 'infractions'),
                    ('immune_roles', 'immune_roles'),
                    ('immune_users', 'immune_users'),
                ):
                    async with db.execute(
                        f'SELECT COUNT(*) FROM {table} WHERE guild_id=?', (self.g.id,)
                    ) as cur:
                        row = await cur.fetchone()
                        etat[cle] = row[0] if row else 0
        except Exception as ex:
            print(f"[MainPanelV2 _collect_etat db] {ex}")

        mod_log = self.g.get_channel(c.get('mod_log_channel', 0))
        etat['mod_log'] = mod_log.mention if mod_log else "⚪ _non défini_"

        etat['antiraid'] = "🟢 actif" if c.get('antiraid_enabled') else "⚪ désactivé"

        staff = self.g.get_role(c.get('ticket_staff', 0))
        nb_panels = len(c.get('ticket_panels', {}) or {})
        if staff:
            etat['tickets'] = f"`{nb_panels}` panneau(x) · staff {staff.mention}"
        elif nb_panels:
            etat['tickets'] = f"`{nb_panels}` panneau(x) · ⚪ _rôle staff non défini_"
        else:
            etat['tickets'] = "⚪ _non configuré_"

        try:
            log_id = await ulogger2026.get_log_channel(self.g.id)
            log_ch = self.g.get_channel(log_id) if log_id else None
            etat['logs'] = log_ch.mention if log_ch else "⚪ _non défini_"
        except Exception as ex:
            print(f"[MainPanelV2 _collect_etat logs] {ex}")
            etat['logs'] = "⚪ _indisponible_"

        return etat

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        self._build(await self._collect_etat())
        if edit:
            await interaction.response.edit_message(content=None, view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)

    # ─────────────────────────────────────────────────────────────────────────
    #  Callbacks
    # ─────────────────────────────────────────────────────────────────────────
    async def _module_select(self, i):
        valeur = i.data['values'][0]
        # Résolution paresseuse : ces classes sont définies plus bas dans bot.py.
        panneaux = {
            'protections': lambda: ProtPanelV2(self.u, self.g),
            'sanctions':   lambda: ModerationPanelV2(self.u, self.g),
            'immunites':   lambda: ImmunePanelV2(self.u, self.g),
            'antiraid':    lambda: AntiRaidPanelV2(self.u, self.g),
            'tickets':     lambda: TicketMainPanelV2(self.u, self.g),
            'logs':        lambda: LogsPanelV2(self.u, self.g),
            'afk':         lambda: AfkRolePanelV2(self.u, self.g),
            'rgpd':        lambda: RgpdPanelV2(self.u, self.g),
        }
        fabrique = panneaux.get(valeur)
        if fabrique is None:
            # Valeur inattendue : on acquitte au minimum pour ne pas laisser
            # l'interaction en échec côté client.
            try:
                await i.response.defer()
            except Exception:
                pass
            return
        try:
            await fabrique().render_to(i, edit=True)
        except Exception as ex:
            print(f"[MainPanelV2 _module_select {valeur}] {ex}")
            import traceback
            traceback.print_exc()
            try:
                msg = f"❌ Section indisponible : `{type(ex).__name__}: {ex}`"
                if not i.response.is_done():
                    await i.response.send_message(msg, ephemeral=True)
                else:
                    await i.followup.send(msg, ephemeral=True)
            except Exception:
                pass

    async def _cb_refresh(self, i):
        try:
            await self.render_to(i, edit=True)
        except Exception as ex:
            print(f"[MainPanelV2 _cb_refresh] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.defer()
            except Exception:
                pass

    async def _close(self, i):
        # Phase 3.9 : `i.message.delete()` échoue silencieusement sur un message
        # éphémère et provoque « Échec de l'interaction ». Pattern éprouvé :
        try:
            await i.response.edit_message(
                content="✅ Configuration fermée. Tu peux fermer ce message via *Dismiss*.",
                embed=None, embeds=[], view=None, attachments=[],
            )
        except discord.InteractionResponded:
            try:
                await i.edit_original_response(content="✅ Fermé", embed=None, view=None)
            except Exception:
                pass
        except Exception as ex:
            print(f"[MainPanelV2 _close] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.defer()
            except Exception:
                pass
'''


def bornes_classe(arbre: ast.Module, nom: str) -> tuple[int, int]:
    for n in arbre.body:
        if isinstance(n, ast.ClassDef) and n.name == nom:
            return n.lineno, n.end_lineno
    raise SystemExit(f"ABANDON : classe {nom} introuvable au niveau module.")


def main() -> int:
    apply_ = "--apply" in sys.argv

    src = open(FICHIER, encoding="utf-8").read()
    lignes = src.splitlines(keepends=True)
    arbre = ast.parse(src)

    main_deb, main_fin = bornes_classe(arbre, "MainPanelV2")
    sec_deb, sec_fin = bornes_classe(arbre, "SecurityPanelV2")

    if not (main_fin < sec_deb):
        raise SystemExit("ABANDON : MainPanelV2 n'est plus avant SecurityPanelV2.")

    # ── Anti-décalage : le jeton attendu est-il bien dans la plage ? ──────────
    for nom, (deb, fin) in (("MainPanelV2", (main_deb, main_fin)),
                            ("SecurityPanelV2", (sec_deb, sec_fin))):
        bloc = "".join(lignes[deb - 1:fin])
        for jeton in JETONS[nom]:
            if jeton not in bloc:
                raise SystemExit(
                    f"ABANDON : jeton absent de {nom} (l.{deb}-{fin}) → "
                    f"les numéros ont bougé.\n  attendu : {jeton!r}"
                )

    # ── Remonter l'en-tête de commentaire de SecurityPanelV2 ─────────────────
    sec_entete = sec_deb
    i = sec_deb - 2  # index 0-based de la ligne au-dessus de `class ...`
    while i >= 0 and (lignes[i].startswith("#") or not lignes[i].strip()):
        if lignes[i].startswith("#"):
            sec_entete = i + 1
        i -= 1
    bloc_entete = "".join(lignes[sec_entete - 1:sec_deb - 1])
    if ENTETE_SECURITY not in bloc_entete:
        raise SystemExit(
            f"ABANDON : l'en-tête attendu de SecurityPanelV2 est introuvable "
            f"(l.{sec_entete}-{sec_deb - 1}).\n  attendu : {ENTETE_SECURITY!r}"
        )

    # ── Recomposition (de la fin vers le début : les index restent valides) ───
    nouvelles = list(lignes)
    del nouvelles[sec_entete - 1:sec_fin]                     # 2. supprime SecurityPanelV2
    nouvelles[main_deb - 1:main_fin] = [NOUVEAU]              # 1. remplace MainPanelV2
    resultat = "".join(nouvelles)

    # ── 3. Recâblage des boutons « Retour » ──────────────────────────────────
    nb_retours = resultat.count(RETOUR_AVANT)
    if nb_retours != RETOURS_ATTENDUS:
        raise SystemExit(
            f"ABANDON : {nb_retours} bouton(s) « Retour » vers SecurityPanelV2, "
            f"{RETOURS_ATTENDUS} attendus."
        )
    resultat = resultat.replace(RETOUR_AVANT, RETOUR_APRES)

    # ── 3b. Commentaires devenus mensongers ──────────────────────────────────
    #  Les variantes les plus longues d'abord, sinon la courte les tronque.
    nb_comm = 0
    for avant_c in sorted(COMMENTAIRES_AVANT, key=len, reverse=True):
        n = resultat.count(avant_c + "\n")
        if n:
            resultat = resultat.replace(avant_c + "\n", COMMENTAIRE_APRES + "\n")
            nb_comm += n
    if nb_comm != COMMENTAIRES_ATTENDUS:
        raise SystemExit(
            f"ABANDON : {nb_comm} commentaire(s) « retour vers SecurityPanelV2 » "
            f"recâblé(s), {COMMENTAIRES_ATTENDUS} attendus."
        )

    # ── Garde-fou : plus AUCUNE référence à SecurityPanelV2 ──────────────────
    restant = [
        f"  l.{n}: {l.strip()}"
        for n, l in enumerate(resultat.splitlines(), 1)
        if "SecurityPanelV2" in l
    ]
    if restant:
        raise SystemExit(
            "ABANDON : références résiduelles à SecurityPanelV2 :\n" + "\n".join(restant)
        )

    # ── Garde-fou : ast.parse AVANT d'écrire (HANDOFF §4.2) ──────────────────
    try:
        ast.parse(resultat)
    except SyntaxError as ex:
        raise SystemExit(f"ABANDON : le résultat ne se parse pas — {ex}")

    avant, apres = len(lignes), len(resultat.splitlines())
    print("── Refonte de /configure ───────────────────────────────────────")
    print(f"  MainPanelV2      l.{main_deb}-{main_fin}  ({main_fin - main_deb + 1} l.) → remplacé")
    print(f"  SecurityPanelV2  l.{sec_entete}-{sec_fin}  ({sec_fin - sec_entete + 1} l.) → supprimé")
    print(f"  Boutons Retour   {nb_retours} recâblés vers MainPanelV2")
    print(f"  Commentaires     {nb_comm} remis à jour")
    print(f"  Sections select  13 → {len(_sections_du_nouveau())}")
    print(f"  bot.py           {avant} → {apres} lignes ({apres - avant:+d})")
    print("  ast.parse        OK")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    open(FICHIER, "w", encoding="utf-8", newline="").write(resultat)
    print("\n  ÉCRIT.")
    return 0


def _sections_du_nouveau() -> list:
    """Compte les sections déclarées dans le bloc `_CONFIG_SECTIONS` généré."""
    arbre = ast.parse(NOUVEAU)
    for n in arbre.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "_CONFIG_SECTIONS":
            return n.value.elts
    return []


if __name__ == "__main__":
    raise SystemExit(main())
