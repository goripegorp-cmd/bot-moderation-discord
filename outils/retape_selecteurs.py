#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retape des sélecteurs : plus de pagination à la main, plus de fuite V2 -> V1.

Trois panneaux V2 envoyaient encore `edit_message(embed=…, view=<vue V1>)` — c'est-à-dire
un Embed *et* une vue à l'ancienne, avec pagination manuelle des salons (23 ou 24 par page)
parce qu'un `Select` classique plafonne à 25 options. Le projet a déjà le composant correct,
`V2GenericChannelPicker`, bâti sur `discord.ui.ChannelSelect` natif : pas de plafond, pas de
pagination, pas d'ID à coller. On branche celui-là et on supprime les bricolages.

  A. ProtDetailV2._cb_log            -> V2GenericChannelPicker (clé `log_<protection>`)
  B. LinkConfigPanelV2._cb_add_ch    -> V2GenericChannelPicker (+ save_fn : ajout à une LISTE)
  C. AntiRaidConfigPanelV2._cb_action-> RaidActionPanelV2 (neuf), fin de la fuite vers V1
  D. V2GenericChannelPicker : bouton « Retour » en `danger` -> `secondary` (UI.md §3)

Méthode imposée (HANDOFF.md §4) : preview par défaut, `--apply` pour écrire, `ast.parse()`
avant écriture, et jeton attendu vérifié dans chaque plage avant de la couper.

Usage :
    PYTHONIOENCODING=utf-8 python3 outils/retape_selecteurs.py            # preview
    PYTHONIOENCODING=utf-8 python3 outils/retape_selecteurs.py --apply    # écrit
"""
from __future__ import annotations

import ast
import sys

FICHIER = "bot.py"

# ── A. Le sélecteur de salon de log d'une protection ─────────────────────────
A_AVANT = '''    async def _cb_log(self, i):
        try:
            total_channels = len(list(self.g.text_channels))
            v = LogSelectView(self.u, self.g, self.key, self.prot)
            await i.response.edit_message(
                embed=discord.Embed(
                    title="📜 Choisir le salon de log",
                    description=f"Pour la protection **{self.prot[2]}**\\n\\n📊 {total_channels} salons disponibles",
                    color=0x9B59B6,
                ),
                view=v,
                attachments=[],
            )
        except Exception as ex:
            print(f"[LOG SELECT V2 ERROR] {ex}")
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
'''

A_APRES = '''    async def _cb_log(self, i):
        # UI.md §2 : ChannelSelect natif via V2GenericChannelPicker. L'ancien
        # LogSelectView paginait les salons 23 par 23 (limite des 25 options d'un
        # Select classique) et renvoyait un Embed depuis un panneau V2.
        try:
            v = V2GenericChannelPicker(
                self.u, self.g,
                config_key=f'log_{self.key}',
                return_panel_factory=lambda: ProtDetailV2(self.u, self.g, self.prot),
                title="📜 Salon de log",
                description=f"Où envoyer les alertes de **{self.prot[2]}**.",
                color=0x9B59B6,
            )
            await v.render_to(i, edit=True)
        except Exception as ex:
            print(f"[ProtDetailV2 _cb_log] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.send_message(f"❌ Erreur : {ex}", ephemeral=True)
                else:
                    await i.followup.send(f"❌ Erreur : {ex}", ephemeral=True)
            except Exception:
                pass
'''

# ── B. L'ajout d'un salon autorisé pour l'anti-liens ─────────────────────────
B_AVANT = '''    async def _cb_add_ch(self, i):
        v = PaginatedLinkChanSelectView(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Choisir un salon à autoriser",
                description=f"📊 {len(list(self.g.text_channels))} salons disponibles",
                color=0x9B59B6,
            ),
            view=v,
            attachments=[],
        )
'''

B_APRES = '''    async def _cb_add_ch(self, i):
        # UI.md §2 : ChannelSelect natif. `link_allowed_channels` est une LISTE,
        # donc on passe par save_fn plutôt que par l'écriture simple du picker.
        async def _ajouter(guild_id, channel_id):
            c = await cfg(guild_id)
            salons = list(c.get('link_allowed_channels', []) or [])
            if channel_id and channel_id not in salons:
                salons.append(channel_id)
            elif not channel_id:
                # Le bouton « Aucun (reset) » du picker envoie 0 : on vide la liste.
                salons = []
            await db_set(guild_id, 'link_allowed_channels', salons)

        try:
            v = V2GenericChannelPicker(
                self.u, self.g,
                return_panel_factory=lambda: LinkConfigPanelV2(self.u, self.g),
                title="📍 Autoriser un salon",
                description="Les liens resteront permis dans ce salon.",
                color=0x9B59B6,
                save_fn=_ajouter,
            )
            await v.render_to(i, edit=True)
        except Exception as ex:
            print(f"[LinkConfigPanelV2 _cb_add_ch] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.send_message(f"❌ Erreur : {ex}", ephemeral=True)
                else:
                    await i.followup.send(f"❌ Erreur : {ex}", ephemeral=True)
            except Exception:
                pass
'''

# ── C. Le choix de la riposte anti-raid ─────────────────────────────────────
C_AVANT = '''    async def _cb_action(self, i):
        v = RaidActionSelect(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(title="⚡ Choisir l'action anti-raid", color=0xE74C3C),
            view=v,
            attachments=[],
        )
'''

C_APRES = '''    async def _cb_action(self, i):
        # UI.md §4 : l'ancien RaidActionSelect renvoyait vers AntiRaidConfigPanel V1
        # (un Embed) — une fuite qui ressuscitait le panneau legacy à chaque clic.
        try:
            await RaidActionPanelV2(self.u, self.g).render_to(i, edit=True)
        except Exception as ex:
            print(f"[AntiRaidConfigPanelV2 _cb_action] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.send_message(f"❌ Erreur : {ex}", ephemeral=True)
                else:
                    await i.followup.send(f"❌ Erreur : {ex}", ephemeral=True)
            except Exception:
                pass
'''

# Le panneau neuf, inséré juste avant `class AntiRaidConfigPanel(View):` (le V1 mourant).
C_NOUVEAU_PANNEAU = '''class RaidActionPanelV2(LayoutView):
    """Riposte appliquée quand l'anti-raid se déclenche (clé `raid_config.action`).

    Ouvert par AntiRaidConfigPanelV2 · « ⚡ Riposte ». Remplace RaidActionSelect,
    qui retombait sur le panneau V1 en Embed (UI.md §1 et §4).
    """

    #  (valeur stockée, emoji, libellé, ce que ça fait concrètement)
    ACTIONS = [
        ("kick", "👢", "Expulser", "Le membre est expulsé, il peut revenir avec une invitation."),
        ("ban", "🔨", "Bannir", "Le membre est banni, il ne peut plus revenir."),
        ("mute", "🔇", "Rendre muet", "Le membre reste, mais ne peut plus écrire ni parler."),
    ]

    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self._build()

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    def _build(self, actuelle: str | None = None):
        self.clear_items()
        items: list = [
            v2_title("⚡ Riposte anti-raid"),
            v2_subtitle("Ce que le bot fait aux comptes d'une vague détectée"),
            v2_divider(),
        ]

        if actuelle is not None:
            libelle = next(
                (f"{e} **{lib}**" for v, e, lib, _ in self.ACTIONS if v == actuelle),
                "⚪ _aucune_",
            )
            items.append(v2_body(f"Riposte actuelle · {libelle}"))
            items.append(v2_divider())

        items.append(v2_body("\\n".join(
            f"{emoji} **{libelle}** — {aide}" for _, emoji, libelle, aide in self.ACTIONS
        )))
        items.append(v2_divider())

        # UI.md §3 : le bouton de l'action ACTIVE est en `success` et désactivé —
        # l'état se lit sur le bouton, pas dans une case cochée en texte.
        ligne = []
        for valeur, emoji, libelle, _ in self.ACTIONS:
            actif = (valeur == actuelle)
            b = Button(
                label=libelle,
                emoji=emoji,
                style=discord.ButtonStyle.success if actif else discord.ButtonStyle.secondary,
                disabled=actif,
                custom_id=f"raidact_{valeur}",
            )
            b.callback = self._faire_callback(valeur)
            ligne.append(b)

        b_back = Button(
            label="Retour", emoji="◀️",
            style=discord.ButtonStyle.secondary, custom_id="raidact_back",
        )
        b_back.callback = self._cb_back

        items.append(discord.ui.ActionRow(*ligne))
        items.append(discord.ui.ActionRow(b_back))

        self.add_item(v2_container(*items, color=Palette.DANGER))

    def _faire_callback(self, valeur: str):
        async def _cb(i):
            try:
                c = await cfg(self.g.id)
                raid_cfg = dict(c.get('raid_config', {}) or {})
                raid_cfg['action'] = valeur
                await db_set(self.g.id, 'raid_config', raid_cfg)
                await self.render_to(i, edit=True)
            except Exception as ex:
                print(f"[RaidActionPanelV2 _cb {valeur}] {ex}")
                try:
                    if not i.response.is_done():
                        await i.response.defer()
                except Exception:
                    pass
        return _cb

    async def render_to(self, interaction: discord.Interaction, *, edit: bool = True):
        # Disponibilité = fail-open : si la config est illisible, on affiche quand
        # même le panneau, simplement sans marquer la riposte active.
        try:
            c = await cfg(self.g.id)
            actuelle = (c.get('raid_config', {}) or {}).get('action')
        except Exception as ex:
            print(f"[RaidActionPanelV2 render_to cfg] {ex}")
            actuelle = None
        self._build(actuelle)
        if edit:
            await interaction.response.edit_message(content=None, view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)

    async def _cb_back(self, i):
        try:
            await AntiRaidConfigPanelV2(self.u, self.g).render_to(i, edit=True)
        except Exception as ex:
            print(f"[RaidActionPanelV2 _cb_back] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.defer()
            except Exception:
                pass


'''

# ── D. Cohérence du style des boutons « Retour » (UI.md §3) ──────────────────
D_AVANT = '''        b_back = Button(label="◀️ Retour", style=discord.ButtonStyle.danger)'''
D_APRES = '''        b_back = Button(label="◀️ Retour", style=discord.ButtonStyle.secondary)'''
# Les 4 sélecteurs génériques du fichier : V2GenericChannelPicker, V2GenericRolePicker,
# V2AdsChannelPicker, _ChanPickerV2. Un « Retour » en rouge dit « attention, destructeur »
# alors qu'il ne fait que remonter d'un cran — on uniformise sur `secondary`.
D_ATTENDUS = 4

ANCRE_NOUVEAU = "class AntiRaidConfigPanel(View):"


def remplacer_unique(src: str, avant: str, apres: str, etiquette: str) -> str:
    n = src.count(avant)
    if n != 1:
        raise SystemExit(f"ABANDON : {etiquette} — {n} occurrence(s) du bloc attendu, 1 requise.")
    return src.replace(avant, apres)


def main() -> int:
    apply_ = "--apply" in sys.argv
    src = open(FICHIER, encoding="utf-8").read()
    avant_lignes = len(src.splitlines())

    # A, B, C : remplacements de corps de callback, chacun doit être unique.
    src = remplacer_unique(src, A_AVANT, A_APRES, "A ProtDetailV2._cb_log")
    src = remplacer_unique(src, B_AVANT, B_APRES, "B LinkConfigPanelV2._cb_add_ch")
    src = remplacer_unique(src, C_AVANT, C_APRES, "C AntiRaidConfigPanelV2._cb_action")

    # C bis : insertion du panneau neuf, juste avant le V1 mourant.
    if src.count(ANCRE_NOUVEAU) != 1:
        raise SystemExit(f"ABANDON : ancre d'insertion introuvable ou multiple ({ANCRE_NOUVEAU!r}).")
    src = src.replace(ANCRE_NOUVEAU, C_NOUVEAU_PANNEAU + ANCRE_NOUVEAU)

    # D : style des boutons Retour.
    nb_d = src.count(D_AVANT)
    if nb_d != D_ATTENDUS:
        raise SystemExit(f"ABANDON : D — {nb_d} bouton(s) « Retour » en danger, {D_ATTENDUS} attendus.")
    src = src.replace(D_AVANT, D_APRES)

    # ── Garde-fou : le panneau neuf se parse-t-il, et est-il bien au niveau module ?
    arbre = ast.parse(src)
    classes = {n.name for n in arbre.body if isinstance(n, ast.ClassDef)}
    if "RaidActionPanelV2" not in classes:
        raise SystemExit("ABANDON : RaidActionPanelV2 n'est pas une classe de niveau module.")

    # ── Garde-fou : les bricolages ne sont-ils plus appelés de nulle part ? ──
    orphelins = {}
    for nom in ("LogSelectView", "PaginatedLinkChanSelectView", "RaidActionSelect"):
        bornes = next(
            ((n.lineno, n.end_lineno) for n in arbre.body
             if isinstance(n, ast.ClassDef) and n.name == nom), None
        )
        appels = [
            n.lineno for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == nom
        ]
        externes = [l for l in appels if not (bornes and bornes[0] <= l <= bornes[1])]
        orphelins[nom] = externes

    ast.parse(src)  # ceinture et bretelles avant écriture

    apres_lignes = len(src.splitlines())
    print("── Retape des sélecteurs ───────────────────────────────────────")
    print("  A  ProtDetailV2._cb_log             -> V2GenericChannelPicker")
    print("  B  LinkConfigPanelV2._cb_add_ch     -> V2GenericChannelPicker (+ save_fn)")
    print("  C  AntiRaidConfigPanelV2._cb_action -> RaidActionPanelV2 (neuf)")
    print(f"  D  boutons « Retour » danger->secondary : {nb_d}")
    print(f"  bot.py  {avant_lignes} → {apres_lignes} lignes ({apres_lignes - avant_lignes:+d})")
    print("  ast.parse OK")
    print("\n  Appelants restants des bricolages (hors eux-mêmes) :")
    for nom, lignes in orphelins.items():
        etat = "ORPHELIN (supprimable)" if not lignes else f"encore appelé l.{lignes}"
        print(f"    {nom:32} {etat}")

    if not apply_:
        print("\n  PREVIEW — rien écrit. Relancer avec --apply.")
        return 0

    open(FICHIER, "w", encoding="utf-8", newline="").write(src)
    print("\n  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
