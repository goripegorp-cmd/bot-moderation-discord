# 🎨 CHARTE UI — condition permanente du propriétaire

> Posée le **11/08/2026**, valable pour **tout** ce qui est créé à partir de maintenant :
> menus, boutons, panneaux, formulaires, logs.
>
> **« Je veux que tous les menus soient ultra propres. Les nouvelles technologies Discord,
> les webhooks, des boutons vraiment très très bien. Retape chaque chose pour que tout soit
> impeccable. Et je veux que ton travail soit bien rangé et bien classé, ultra optimisé
> et protégé. »**

Aucune UI ne part en production sans avoir passé **les 6 sections** ci-dessous.
Il n'y a pas de « je repasserai après » : il n'y a pas de second passage.

---

## 1. INTERDIT — le vieux Discord

| ❌ Jamais | ✅ À la place |
|---|---|
| Menus par réactions emoji (cliquer 🇦/🇧/✅ sous un message) | `discord.ui.Select` ou boutons |
| Cases à cocher simulées avec des emojis dans du texte | Un bouton dont le `label` et le `style` portent l'état |
| Commandes préfixées (`!config`) | `app_commands` (slash), descriptions en français |
| Mur de texte dans un embed en guise de formulaire | `Modal` + `TextInput` |
| « Colle l'ID du salon » | `ChannelSelect` / `RoleSelect` / `UserSelect` |
| Un `Embed` pour une nouvelle interface | `LayoutView` + `Container` (Components V2) |

---

## 2. OBLIGATOIRE — les composants modernes

**Components V2** via les helpers du projet (`ui_v2.py`, importés en `v2_*` dans `bot.py`) :

| Helper | Rôle |
|---|---|
| `v2_container(*items, color=Palette.X)` | Le bloc racine, équivalent moderne de l'embed |
| `v2_section(*textes, accessory=…)` | Bloc texte **avec** vignette ou bouton (accessoire **obligatoire**) |
| `v2_title(txt, level=1..3)` · `v2_subtitle` · `v2_body` | Hiérarchie de texte |
| `v2_divider()` | Séparateur |
| `v2_thumb(url)` | Vignette (accessoire de section) |
| `v2_kv` · `v2_bullets` · `v2_stats` | Blocs clé/valeur, listes, grilles de stats |

**Selects natifs typés — jamais de saisie d'ID à la main :**
`ChannelSelect`, `RoleSelect`, `UserSelect`, `MentionableSelect`.

**Webhooks** partout où une identité d'expéditeur par catégorie améliore la lecture
(déjà implémenté côté logs : `unified_logger.get/set_webhook_mode`).

**Vues persistantes** (`timeout=None` + `custom_id` stable, ré-enregistrées au boot par
`bot.add_view` / `bot.add_dynamic_items`) pour tout bouton devant survivre à un redémarrage.
Identifiants dynamiques → `DynamicItem`.

### Contraintes dures (dépassement = erreur 400 côté Discord)

- Avec `LayoutView`, le paramètre **`content=` est INTERDIT**.
- **40 composants** maximum par message.
- Une vue **sans aucun composant** est invalide.
- Select : **25 options** max · `label` ≤ 100 · `description` ≤ 100 · `placeholder` ≤ 150.
- `custom_id` ≤ 100 caractères, et **unique** dans le message.

---

## 3. BOUTONS — le détail qui fait le professionnel

- `label` **explicite** et en français. Jamais un bouton qui n'est qu'un emoji.
- `emoji=` est de la **décoration**, jamais le mécanisme de clic.
- `style` cohérent, toujours le même sens dans tout le bot :

| Style | Sens |
|---|---|
| `primary` | action principale / navigation vers une sous-section |
| `success` | valider, activer, créer |
| `danger` | supprimer, désactiver, fermer |
| `secondary` | retour, actualiser, action neutre |

- **Toggle** = un bouton dont le `label` ET le `style` reflètent l'état
  (`🟢 Activé` en `success` / `⚪ Désactivé` en `secondary`), jamais une réaction.
- Un bouton sans effet possible est `disabled=True`, pas absent : l'utilisateur doit
  comprendre pourquoi il ne peut pas cliquer.

---

## 4. NAVIGATION — on ne perd jamais l'utilisateur

- Chaque panneau non racine a un bouton **`◀️ Retour`** en `secondary`.
- Le retour **passe par `render_to()`**, jamais par un `edit_message(view=…)` brut :
  sinon l'état affiché n'est pas rechargé et le panneau ment.
- Fil d'Ariane clair : le titre dit **où on est**, le sous-titre dit **ce qu'on y règle**.
- Un panneau racine n'a pas de « Retour » mais a **`✖️ Fermer`** et **`🔄 Actualiser`**.

---

## 5. OPTIMISÉ

- **`defer` d'abord** sur toute interaction qui va travailler (anti-429, limite des 3 s).
- **Une seule requête** quand une seule suffit : regrouper les `COUNT` en sous-requêtes
  d'un même `SELECT` plutôt que d'enchaîner les allers-retours.
- **Jamais de f-string dans du SQL** — paramètres liés (`?`) uniquement. Le dépôt a un
  workflow CI « SQL Injection Audit » qui le refuse, et c'est une bonne raison.
- Lecture de config par `await cfg(gid)` (cache 30 s), écriture par `await db_set(gid, k, v)`
  (verrou par guilde, invalide le cache). Ne pas court-circuiter.
- Pas de requête dans `__init__` : `__init__` construit une vue **valide et synchrone**,
  tout ce qui touche la base va dans `render_to()` / `refresh()`.

---

## 6. PROTÉGÉ

- **`interaction_check`** sur chaque vue : seul celui qui a ouvert le panneau peut cliquer.
- Panneaux de configuration : **propriétaire du serveur ou super-owner uniquement**
  (`SUPER_OWNER_ID = 781205382923288593`).
- **Réponses éphémères** par défaut pour toute configuration et toute modération.
- **Anonymat du modérateur** : une réponse de slash publique trahit qui a sanctionné
  (Discord affiche « X a utilisé /mod warn ») → réponse éphémère + `channel.send` séparé.
- **Fail-open sur la disponibilité** : une erreur de base ne doit jamais empêcher un panneau
  de s'ouvrir. Chaque bloc de lecture est isolé dans son `try`, avec une valeur de repli.
- **Fail-closed sur la sécurité** : dans le doute, on protège.
- Tout `except` avale l'erreur mais **la journalise** (`print(f"[Classe méthode] {ex}")`) :
  jamais d'échec silencieux.

---

## 7. RANGÉ ET CLASSÉ

- Un panneau = une classe `…PanelV2`, avec toujours la même ossature :
  `__init__(self, u, g)` → `interaction_check` → `_build()` → `render_to()` → callbacks `_cb_*`.
- Les callbacks sont préfixés `_cb_`, groupés en fin de classe sous un commentaire de section.
- Chaque classe porte une **docstring** qui dit à quoi elle sert et qui l'ouvre.
- Les pièges non évidents sont commentés **sur place**, avec la raison (« ⚠️ PIÈGE À NE PAS
  DÉFAIRE — … ») : un correctif sans explication se fait défaire au refactor suivant.
- Les scripts d'analyse et de migration vivent dans **`outils/`**, jamais à la racine,
  avec preview par défaut et `--apply` pour écrire.

---

## Contrôle avant livraison

```bash
bash outils/verif_socle.sh
```

Puis, pour un panneau donné, vérifier ses signatures et ses appelants :

```bash
PYTHONIOENCODING=utf-8 python3 outils/sonde_panneaux.py MonPanelV2
```

Un lot n'est terminé que si **la CI est verte** (voir `HANDOFF.md` §3).
