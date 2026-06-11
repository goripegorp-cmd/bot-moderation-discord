# Contrat de style — Menus & panneaux (Abylumis bot)

> Objectif owner : tous les menus **plus compacts, plus épurés, plus beaux**, qui
> **prennent moins de place** dans le chat. Ce document est la référence unique
> pour toute refonte visuelle/textuelle des menus. Appliquer SANS jamais toucher
> à la logique.

## Principes (le « beau » = sobre + dense + cohérent)

1. **Titre = 1 ligne.** `#` H1, **un seul** emoji en tête, pas de titre à rallonge.
2. **Sous-titre = 1 ligne `-#` max**, discret, pour le contexte. **Supprimer** les
   phrases d'instruction (« Clique sur le bouton ci-dessous pour… ») : le bouton
   se suffit.
3. **Densité.** Regrouper les stats en lignes compactes `emoji **Label** · valeur`
   (séparateur `·`), au lieu d'une ligne (ou d'un field) par valeur. Viser
   **≤ 6–8 lignes** de texte avant un séparateur.
4. **Séparateurs.** Un `divider()` (ou `ui.Separator`) entre sections logiques —
   **jamais deux d'affilée**, jamais en tête ni en fin de container.
5. **Boutons.** Label **court** (1–2 mots), **un** emoji en tête, verbe d'action
   (`Équiper`, `Forger`, `Fermer`). ≤ 5 boutons par ActionRow.
6. **Couleurs (Palette ui_v2).** PRIMARY par défaut ; SUCCESS / DANGER / WARNING
   selon le contexte ; **PREMIUM (or)** pour loot/rareté/récompense.
7. **Pas de footer volumineux** : un `-#` discret au plus.
8. **Emojis.** **Un** par élément au maximum, cohérents — pas de salves d'emojis
   décoratives.
9. **Chiffres.** Formatage compact (`format_coins(n, short=True)` → `1.2k`),
   barres HP courtes (`format_hp_bar`, length ≤ 12).
10. **Embeds legacy.** Trimmer la description (≤ ~3 lignes), **fusionner** les
    champs redondants, retirer les `field` inline décoratifs inutiles.

## Règles ABSOLUES (sécurité — ne JAMAIS enfreindre)

- **Ne change QUE le texte affiché** (titres, descriptions, labels de boutons,
  placeholders, séparateurs, emojis, choix de couleur). **JAMAIS** :
  `custom_id`, nom de callback, nombre/structure de composants dont dépend la
  logique, ni les `{variables}` / format specs d'une f-string.
- **Limites Components V2** : ≤ 40 composants/message, ≤ 5 boutons/ActionRow,
  `content=` **interdit** avec une LayoutView (texte → TextDisplay interne).
- **Combat = fail-open** : aucune modif de texte ne doit pouvoir casser un
  chemin de combat (rester dans les `try/except` existants).
- Chaque lot doit **compiler** (CI `compile-check` = vrai `import bot`) avant
  d'être considéré comme fait.

## Helpers à privilégier (déjà en place)

- `ui_v2` : `title/subtitle/body/kv_block/bullets/stat_line/stats_grid/divider/`
  `section/container/header/info_card/recap_view`, `Palette`, `BasePanel`,
  `StaticPanel`.
- `panels_helpers` : `rarity_badge/rarity_color/format_coins/format_duration/`
  `format_item_line/format_hp_bar/section_header/make_close_button/`
  `make_refresh_button/make_nav_button`.
