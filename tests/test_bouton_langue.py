"""« Ma langue / My language » ne répondait pas — défaut signalé le 19/08.

LE SYMPTÔME, MOT POUR MOT DU PROPRIÉTAIRE
    « le ma langue my langue quand on clique dessus, ça fait que le Bot n'a pas
    répondu, ça ne marche pas »
Capture à l'appui : carte d'accueil d'un nouveau membre, clic sur le bouton,
« GoRp n'a pas répondu à temps ».

LA CAUSE
Le bouton porte `custom_id="onb_lang"` et comptait sur `OnboardingView`,
réenregistrée au boot par `bot.add_view(...)`. La purge d'animation a remplacé
cet appel par `pass  # bloc vidé (module détaché)` et emporté la classe. Le
bouton, lui, est resté : `_welcome_quick_buttons` le repose sur CHAQUE carte
d'accueil. Plus personne n'écoutant ce custom_id, Discord attend trois secondes
et affiche l'échec — en public, à chaque nouveau membre.

⚠️ AUCUN TEST NE POUVAIT LE VOIR. Le bouton est bien construit, la carte bien
envoyée, `import bot` passe, les 385 tests passent. Le défaut ne vit que dans
le RACCORD entre un custom_id émis et un enregistrement au boot. D'où ces
tests, et le détecteur `outils/verif_boutons_persistants.py` qu'ils appellent.

CE QUI EST VERROUILLÉ ICI
  1. la vue existe, porte le bon custom_id, et est réenregistrée au boot ;
  2. elle acquitte AVANT de lire la base (sinon on retombe dans les 3 s) ;
  3. elle réutilise le sélecteur existant au lieu d'en écrire un second ;
  4. plus AUCUN bouton persistant du fichier n'est orphelin ;
  5. le détecteur voit vraiment une régression (sinon son feu vert ne vaut rien).
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = (RACINE / "bot.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SRC)


def _classe(nom: str) -> ast.ClassDef:
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.ClassDef) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable dans bot.py")


def _fonction(nom: str):
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"{nom} introuvable dans bot.py")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Le raccord : le bouton émis a bien un capteur enregistré au boot
# ═══════════════════════════════════════════════════════════════════════════════

def test_la_carte_daccueil_pose_toujours_le_bouton_langue():
    """Si ce bouton disparaît, le membre international n'a plus rien. Il DOIT
    rester — c'est son capteur qui doit exister, pas lui qui doit partir."""
    corps = ast.unparse(_fonction("_welcome_quick_buttons"))
    assert "onb_lang" in corps


def test_la_vue_du_bouton_langue_existe_et_porte_le_bon_custom_id():
    corps = ast.unparse(_classe("AccueilLangueView"))
    assert "custom_id='onb_lang'" in corps.replace('"', "'"), (
        "le custom_id doit être EXACTEMENT celui posé sur la carte d'accueil")


def test_la_vue_est_persistante():
    """`timeout=None` : sans ça, la vue meurt au premier redémarrage et le
    bouton redevient muet sur toutes les cartes déjà envoyées."""
    corps = ast.unparse(_classe("AccueilLangueView"))
    assert "timeout=None" in corps


def test_la_vue_est_reenregistree_au_boot():
    """⚠️ LA LIGNE QUI MANQUAIT. C'est elle, et elle seule, qui rattache le
    custom_id après un redémarrage."""
    assert "bot.add_view(AccueilLangueView())" in SRC, (
        "sans ce add_view au boot, le bouton s'affiche et ne répond jamais")
    #  Et elle doit être dans on_ready, pas dans une fonction jamais appelée.
    on_ready = ast.unparse(_fonction("on_ready"))
    assert "AccueilLangueView()" in on_ready


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Le comportement : acquitter d'abord, ne pas dupliquer le système
# ═══════════════════════════════════════════════════════════════════════════════

def test_le_callback_acquitte_avant_de_lire_la_base():
    """`lang_of` touche la base. Lire avant d'acquitter = les 3 s de Discord
    tombent sur un démarrage à froid, et on retombe dans le défaut réparé."""
    corps = ast.unparse(_classe("AccueilLangueView"))
    avant_lecture = corps.split("lang_of")[0]
    assert "_safe_defer" in avant_lecture, (
        "le defer doit venir AVANT toute lecture, pas après")


def test_le_bouton_reutilise_le_selecteur_existant():
    """⚠️ UN SEUL CHEMIN DE CHOIX DE LANGUE. `LangSelectButton` →
    `_i18n_apply_lang` fait déjà tout : préférence, rôle drapeau, confirmation
    traduite. Un second chemin divergerait du premier au premier correctif."""
    corps = ast.unparse(_classe("AccueilLangueView"))
    assert "LangSelectButton" in corps
    assert "set_user_lang" not in corps, (
        "n'écris pas un second enregistrement de langue : passe par "
        "LangSelectButton → _i18n_apply_lang")


def test_le_selecteur_reutilise_est_bien_vivant():
    """Réutiliser une classe morte ne vaudrait pas mieux qu'en écrire une."""
    assert "bot.add_dynamic_items(LangSelectButton)" in SRC
    corps = ast.unparse(_classe("LangSelectButton"))
    assert "_i18n_apply_lang" in corps


def test_lentete_du_selecteur_est_traduite():
    """Afficher « Choisis ta langue » en français à un lusophone qui vient
    justement changer de langue serait un comble."""
    corps = ast.unparse(_classe("AccueilLangueView"))
    assert "'lang.choose'" in corps.replace('"', "'"), (
        "utilise la clé du catalogue, traduite dans les 6 langues")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Le détecteur : vert sur bot.py, ET capable de voir une régression
# ═══════════════════════════════════════════════════════════════════════════════

OUTIL = RACINE / "outils" / "verif_boutons_persistants.py"


def _lancer(*cibles: Path):
    return subprocess.run([sys.executable, str(OUTIL), *[str(c) for c in cibles]],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(RACINE))


def test_aucun_bouton_persistant_orphelin_dans_bot():
    """⚠️ LES DEUX FICHIERS ENSEMBLE. Les fiches de la veille Roblox posent
    leurs boutons dans `roblox_panneau.py`, mais c'est `bot.py` qui les
    enregistre au boot. Juger `bot.py` seul déclarerait orphelin tout ce qui
    est capté depuis l'autre."""
    r = _lancer(RACINE / "bot.py", RACINE / "roblox_panneau.py")
    assert r.returncode == 0, (
        "un bouton persistant n'a plus de capteur enregistré au boot :\n"
        + (r.stdout or "") + (r.stderr or ""))


def test_le_detecteur_voit_vraiment_une_regression(tmp_path):
    """⚠️ SANS CE TEST, le feu vert précédent ne prouverait rien : un détecteur
    qui renvoie toujours 0 passerait pour un dépôt sain. On lui soumet le
    défaut du 19/08 en miniature — un custom_id sur une vue persistante que
    rien n'enregistre — et on exige qu'il le refuse."""
    faux = tmp_path / "faux_bot.py"
    faux.write_text(
        "import discord\n"
        "class VueEnregistree(discord.ui.View):\n"
        "    @discord.ui.button(custom_id='ok_capte')\n"
        "    async def cb(self, i, b):\n"
        "        pass\n"
        "def poser():\n"
        "    v = discord.ui.View(timeout=None)\n"
        "    v.add_item(discord.ui.Button(custom_id='ok_capte'))\n"
        "    v.add_item(discord.ui.Button(custom_id='orphelin_muet'))\n"
        "    return v\n"
        "async def on_ready():\n"
        "    bot.add_view(VueEnregistree())\n",
        encoding="utf-8")
    r = _lancer(faux)
    assert r.returncode == 1, "le détecteur a laissé passer un bouton orphelin"
    assert "orphelin_muet" in r.stdout
    assert "ok_capte" not in r.stdout.split("SANS CAPTEUR")[-1], (
        "faux positif : un custom_id capté par une vue enregistrée est sain")
