"""Fait passer les QUATRE panneaux sociaux par `_rendre()`.

Pourquoi un script et pas quatre remplacements à la main : le bloc d'affichage
`if edit: ... else: ...` apparaît 14 fois dans `admin_panels_v2.py`, à
l'identique. Un remplacement global toucherait dix panneaux hors périmètre
(permissions, protection, communauté), qui ne sont plus atteignables depuis le
retrait de `/admin` et qu'on ne réveille pas aujourd'hui.

⚠️ PIÈGE DU DÉPÔT N°1 — la coupe n'est PAS bornée sur « la prochaine ligne
`class` » au jugé : on borne sur deux ancres textuelles exactes, et le script
refuse de travailler si l'une manque ou si le compte de remplacements n'est pas
celui attendu. Deux sur-coupes ont déjà coûté 500 lignes et un `@tasks.loop`.

Aperçu par défaut ; `--apply` pour écrire.
"""
from __future__ import annotations

import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "admin_panels_v2.py"

#  Les bornes de la zone sociale. Exactes, et vérifiées avant toute écriture.
DEBUT = "class SocialMediaPanelV2(_OwnerView):"
FIN = "# =============================================================================\n# PROTECTION PANEL"

ANCIEN = """        if edit:
            await interaction.response.edit_message(view=self, embed=None, attachments=[])
        else:
            await interaction.response.send_message(view=self, ephemeral=True)"""

NOUVEAU = """        await _rendre(self, interaction, edit)"""

ATTENDU = 4  # SocialMediaPanelV2 · SocialAddPanel · SocialManagePanel · SocialEditPanel


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")

    i = src.find(DEBUT)
    j = src.find(FIN)
    if i == -1 or j == -1 or j <= i:
        print("❌ Ancres introuvables ou inversées — aucune écriture.")
        return 1

    tete, zone, queue = src[:i], src[i:j], src[j:]
    n = zone.count(ANCIEN)
    if n != ATTENDU:
        print(f"❌ {n} bloc(s) trouvé(s) dans la zone sociale, {ATTENDU} attendu(s).")
        print("   Le fichier a changé : relire avant de patcher.")
        return 1

    nouveau = tete + zone.replace(ANCIEN, NOUVEAU) + queue

    #  Garde-fou : hors de la zone, PAS UN OCTET ne doit bouger.
    if nouveau[:i] != tete or nouveau[len(nouveau) - len(queue):] != queue:
        print("❌ Le patch déborde de la zone sociale — abandon.")
        return 1

    print(f"✅ {n} bloc(s) d'affichage à faire passer par `_rendre()`.")
    print(f"   Zone : octets {i} → {j} ({zone.count(chr(10))} lignes).")
    if "--apply" not in sys.argv:
        print("   (aperçu — relancer avec --apply pour écrire)")
        return 0

    CIBLE.write_text(nouveau, encoding="utf-8")
    print("   Écrit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
