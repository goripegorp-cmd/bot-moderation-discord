"""Rebranche le bouton « 🌍 Ma langue / My language » de l'accueil.

LE SYMPTÔME, CAPTURE DU PROPRIÉTAIRE (19/08/2026)
    Message d'accueil d'un nouveau membre → clic sur « 🌍 Ma langue / My
    language » → « GoRp n'a pas répondu à temps ».

LA CAUSE — LE CAS N°3 DU BRIEFING, MOT POUR MOT
« Boutons dont la classe n'était plus enregistrée au boot → L'interaction a
échoué, en public. »

Le bouton porte `custom_id="onb_lang"` et comptait sur `OnboardingView`,
réenregistrée au démarrage par `bot.add_view(...)`. La purge d'animation a
remplacé cet appel par `pass  # bloc vidé (module détaché)` (bot.py l.21518) —
la vue portait aussi les boutons hub / parcours / notifications — et la classe
est partie avec.

Le bouton, lui, est resté : `_welcome_quick_buttons` le repose sur CHAQUE carte
d'accueil, et son commentaire affirme encore qu'il est « matché globalement par
OnboardingView, enregistrée au boot ». C'est faux depuis la purge. Personne
n'écoute plus ce custom_id, donc Discord attend trois secondes et affiche
l'échec — devant chaque nouveau membre.

CE QUE CE PATCH POSE — ET CE QU'IL NE POSE PAS
⚠️ Il n'écrit AUCUN second système de langue. Le dépôt en a déjà un, complet et
vivant : `LangSelectButton` (DynamicItem `i18n_setlang:<lang>`, réenregistré au
boot l.22422) dont le clic passe par `_i18n_apply_lang` — defer-first,
`set_user_lang`, attribution du rôle drapeau, confirmation traduite. Le bouton
d'accueil se contente désormais d'OUVRIR ce sélecteur en éphémère.

`AccueilLangueView` : vue persistante (`timeout=None`, custom_id stable), un
seul bouton, réponse éphémère portant les six drapeaux. Le choix d'un membre ne
regarde personne d'autre → éphémère, jamais public.

⚠️ `_safe_defer` D'ABORD, avant la moindre lecture : sans acquittement immédiat
on retomberait dans les trois secondes, c'est-à-dire dans le défaut réparé.

⚠️ En-tête via la clé `lang.choose`, qui existe déjà dans les six langues du
catalogue : un sélecteur de langue affiché en français à un anglophone serait
absurde.

Écrit dans un fichier puis exécuté — piège n°3 du dépôt (les heredocs bash
écrasent les `\\n` et abîment les emoji). `--apply` pour écrire.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "bot.py"

#  ═══ 1. LA VUE, posée juste après le sélecteur qu'elle réutilise ═══
ANCRE_CLASSE = "# ─── HUB D'ENGAGEMENT (5 boutons persistants, custom_ids stables) ─────────────"

CLASSE = '''class AccueilLangueView(discord.ui.View):
    """Le bouton « 🌍 Ma langue / My language » de la carte d'accueil.

    ⚠️ VUE PERSISTANTE — `timeout=None` + custom_id stable, réenregistrée au
    boot par `bot.add_view(AccueilLangueView())`. SANS ce réenregistrement,
    personne n'écoute le custom_id `onb_lang` : Discord attend trois secondes
    puis affiche « n'a pas répondu à temps ». C'est exactement ce qui est
    arrivé quand la purge a emporté `OnboardingView` en laissant le bouton
    posé sur chaque carte d'accueil (constaté par le propriétaire le 19/08).

    ⚠️ ELLE NE DÉCIDE RIEN. Elle ouvre le sélecteur qui existe déjà —
    `LangSelectButton` → `_i18n_apply_lang` (préférence + rôle drapeau +
    confirmation traduite). Un second chemin de choix de langue divergerait du
    premier au premier correctif. Ne PAS en écrire un ici.

    Ne porte QUE la langue : les anciens boutons hub / parcours / notifications
    appartenaient à l'animation retirée, ils ne reviennent pas.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🌍 Ma langue / My language",
                       style=discord.ButtonStyle.secondary,
                       custom_id="onb_lang")
    async def _cb_langue(self, i: discord.Interaction, _b: discord.ui.Button):
        #  ⚠️ ACQUITTER AVANT TOUTE LECTURE : `lang_of` touche la base, et un
        #  démarrage à froid dépasserait les trois secondes de Discord.
        if not await _safe_defer(i, ephemeral=True):
            return
        try:
            actuelle = await i18n_module.lang_of(
                user_id=getattr(getattr(i, "user", None), "id", None),
                interaction=i,
                guild_id=(i.guild.id if getattr(i, "guild", None) else None))
        except Exception as ex:
            print(f"[AccueilLangueView lang_of] {ex}")
            actuelle = "fr"
        try:
            v = discord.ui.View(timeout=None)
            #  Les SIX langues supportées, pas seulement celles du serveur : la
            #  préférence est personnelle (elle suit le membre d'un serveur à
            #  l'autre) et le catalogue les traduit toutes.
            for _l in i18n_module.SUPPORTED_LANGS:
                v.add_item(LangSelectButton(_l))
            entete = i18n_module.t("lang.choose", actuelle)
            await _safe_followup(
                i,
                content=(f"🌍 **{entete}**\\n"
                         f"— {i18n_module.lang_choice_label(actuelle)}"),
                view=v)
        except Exception as ex:
            print(f"[AccueilLangueView] {ex}")
            await _safe_followup(
                i, content="❌ Sélecteur de langue indisponible — réessaie dans un instant.")


'''

#  ═══ 2. LE RÉENREGISTREMENT AU BOOT, là où il avait été vidé ═══
ANCIEN_BOOT = '''    # Phase 40 — views persistantes (custom_ids stables, callbacks utilisent i.user.id)
    try:
        pass  # bloc vidé (module détaché)
    except Exception as ex:
        print(f"[on_ready add_view OnboardingView] {ex}")
'''

NOUVEAU_BOOT = '''    # Phase 40 — views persistantes (custom_ids stables, callbacks utilisent i.user.id)
    #  ⚠️ SANS CETTE LIGNE, LE BOUTON LANGUE DE L'ACCUEIL NE RÉPOND PAS.
    #  La purge d'animation avait remplacé ce `bot.add_view` par un `pass` en
    #  emportant `OnboardingView` : le bouton `onb_lang` restait posé sur chaque
    #  carte d'accueil, plus personne ne l'écoutait, et Discord affichait « n'a
    #  pas répondu à temps » après trois secondes, devant chaque nouveau membre.
    #  Constaté par le propriétaire le 19/08/2026, capture à l'appui.
    try:
        bot.add_view(AccueilLangueView())
    except Exception as ex:
        print(f"[on_ready add_view AccueilLangueView] {ex}")
'''

#  ═══ 3. LE COMMENTAIRE QUI MENTAIT, sur la carte d'accueil ═══
ANCIEN_COMMENT = '''        # owner 2026-06-30 : INTERNATIONAL — bouton « 🌍 Ma langue » TOUJOURS présent à l'accueil
        # (custom_id onb_lang matché globalement par OnboardingView, enregistrée au boot). Le
        # nouveau membre choisit sa langue tout de suite. Bilingue.'''

NOUVEAU_COMMENT = '''        # owner 2026-06-30 : INTERNATIONAL — bouton « 🌍 Ma langue » TOUJOURS présent à l'accueil.
        # Le nouveau membre choisit sa langue tout de suite. Bilingue.
        #  ⚠️ custom_id `onb_lang` capté par AccueilLangueView, réenregistrée au boot
        #  (on_ready, Phase 40). Si ce `bot.add_view` disparaît, CE BOUTON MENT : il
        #  s'affiche et ne répond pas. C'est arrivé — la purge d'animation avait
        #  emporté l'ancienne OnboardingView en laissant le bouton ici (19/08/2026).'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    avant = {getattr(n, "name", None) for n in ast.parse(src).body}

    if "class AccueilLangueView" in src:
        print("❌ AccueilLangueView existe déjà — patch déjà appliqué ?")
        return 1
    ancres = (("classe", ANCRE_CLASSE), ("boot", ANCIEN_BOOT),
              ("commentaire", ANCIEN_COMMENT))
    for nom, ancre in ancres:
        if src.count(ancre) != 1:
            print(f"❌ ancre « {nom} » trouvée {src.count(ancre)} fois — abandon.")
            return 1

    neuf = src.replace(ANCRE_CLASSE, CLASSE + ANCRE_CLASSE, 1)
    neuf = neuf.replace(ANCIEN_BOOT, NOUVEAU_BOOT, 1)
    neuf = neuf.replace(ANCIEN_COMMENT, NOUVEAU_COMMENT, 1)

    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse échoue l.{ex.lineno} : {ex.msg}")
        return 1
    apres = {getattr(n, "name", None) for n in arbre.body}
    if avant - apres:
        print(f"❌ symboles perdus : {avant - apres}")
        return 1
    if "AccueilLangueView" not in apres:
        print("❌ la classe n'est pas au niveau module — abandon.")
        return 1
    #  La classe doit être définie AVANT LangSelectButton ? Non : elle ne s'en
    #  sert qu'à l'exécution du callback. Mais elle doit exister au moment du
    #  `bot.add_view`, qui tourne dans on_ready — donc après l'import complet.
    if "bot.add_view(AccueilLangueView())" not in neuf:
        print("❌ le réenregistrement au boot n'est pas là — abandon.")
        return 1

    print(f"  bot.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
