"""19/10/2026 (revue complète) : « ça expulse des gens qui n'ont rien fait ». Chaque phrase normale de
joueur qu'un filtre automatique punissait devient un test : elle ne doit plus jamais l'être. Les vrais
cas, eux, doivent toujours être pris."""
from __future__ import annotations

import ast
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ARBRE = ast.parse((RACINE / "bot.py").read_text(encoding="utf-8"))


def _extraire(*noms, ns=None):
    ns = dict(ns or {}, re=re)
    voulus = set(noms)
    for n in ARBRE.body:
        nom = n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else (
            getattr(n.targets[0], "id", None) if isinstance(n, ast.Assign) else None)
        if nom in voulus:
            exec(ast.unparse(n), ns)  # noqa: S102 — code du dépôt
    return ns


def _fonctions():
    return {n.name: ast.unparse(n) for n in ast.walk(ARBRE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _filtres_liens():
    ns = _extraire("DOMAINES_OFFICIELS", "_URL_COMPLETE", "_hote", "domaine_officiel", "sans_liens_officiels",
                   "PHISHING_DOMAINS", "PHISHING_URL_PATTERNS", "advanced_phishing_check", "_SCAM_SANS_LIEN",
                   "SCAM_KEYWORDS", "_FREE_HOST_DOMAINS", "_FREE_HOST_SCAM_RE", "advanced_scam_check",
                   "COMPROMISED_PATTERNS", ns={"_normalize_for_scan": lambda t: t})
    ns["SCAM_PATTERNS"] = [re.compile(p, re.IGNORECASE) for p in ns["COMPROMISED_PATTERNS"]]
    return _extraire("check_phishing", "check_scam", ns=ns)


def test_F1_liens_officiels_et_phrases_de_jeu_jamais_pris_pour_du_phishing():
    ns = _filtres_liens()
    innocents = [
        "regarde https://cdn.discordapp.com/attachments/1/2/image.png",
        "https://media.discordapp.net/attachments/1/2/clip.gif",
        "https://discordapp.com/channels/1/2/3",
        "voilà ton cadeau https://discord.gift/AbCdEf123",
        "https://steamcommunity.com/tradeoffer/new/?partner=123&token=abc",
        "https://support.discord.com/hc/fr/articles/How-to-Verify-Age-Group",
        "gg félicitations tu as gagné la partie !",
        "congratulations you won the game gg",
        "OMG regardez https://www.roblox.com/games/123/jeu",
        "venez tester mon game https://www.roblox.com/games/456",
        "check this https://youtu.be/abc",
        "wonderful https://www.youtube.com/watch?v=x",
        "viens vite tester mon jeu",
    ]
    for texte in innocents:
        assert not ns["check_phishing"](texte)[0], texte
        assert not ns["check_scam"](texte)[0], texte


def test_F2_les_vrais_liens_piege_sont_toujours_pris():
    ns = _filtres_liens()
    assert ns["check_phishing"]("free nitro https://discord-nitro.gift/claim")[0]
    assert ns["check_phishing"]("claim ton cadeau https://disc0rd-gift.ru/nitro")[0]
    assert ns["check_phishing"]("@everyone free nitro https://discordnitro.com/x")[0]
    assert ns["check_scam"]("free nitro gift https://nitro-drop.xyz/claim now")[0]
    assert ns["check_scam"]("send your seed phrase and wallet address to receive double your crypto")[0]


def test_F3_mots_rouges_en_mot_entier():
    ns = _extraire("_RED_KEYWORDS", "_mot_entier", "_RED_KEYWORDS_RE", "_scan_red_keywords",
                   ns={"_normalize_for_scan": lambda t: t})
    scan = ns["_scan_red_keywords"]
    assert scan("ce mineur nul a encore raté son saut") == ""
    assert scan("le mineur nucléaire du jeu") == ""
    assert scan("annulé", ["nul"]) == "", "la liste du propriétaire aussi, en mot entier"
    assert scan("il partage du child porn") == "child porn"
    assert scan("photo mineur nu") == "mineur nu"


def test_F4_aucun_ban_ni_renvoi_automatique_d_un_membre():
    """Seuls bannissent : le fondateur (sanction), le site (direction), et les boutons de décision."""
    appels = {"ban": set(), "kick": set()}

    def parcourir(noeud, pile):
        for ch in ast.iter_child_nodes(noeud):
            p = pile + [ch.name] if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else pile
            if isinstance(ch, ast.Call) and isinstance(ch.func, ast.Attribute) and ch.func.attr in appels:
                appels[ch.func.attr].add(".".join(pile))
            parcourir(ch, p)
    parcourir(ARBRE, [])
    assert appels["ban"] <= {"RadieDecisionButton.callback", "sanction", "_action_moderer",
                             "_dossier_agir"}, appels["ban"]
    assert appels["kick"] <= {"sanction", "_action_moderer", "_dossier_agir",
                              "_kick_young_account", "_handle_rogue_bot"}, appels["kick"]
    f = _fonctions()
    assert "timeout(timedelta(hours=heures)" in f["_isoler_par_securite"]


def test_F5_rafale_une_heure_d_exclusion_qui_peut_revenir():
    f = _fonctions()
    assert "timeout(timedelta(hours=1)" in f["_burst_timeout"]
    assert "> 3600" in f["_offense_tick"] and "_burst_autoban" not in f


def test_F6_tete_et_staff_jamais_sanctionnes_par_un_automatisme():
    f = _fonctions()
    assert "TETE_IDS" in f["is_fully_immune"] and "_staff_ou_plus(" in f["is_fully_immune"]
    assert "TETE_IDS" in f["_compromised_riposte"]
    assert "_compromised_riposte" not in f["_ocr_scam_check"]
    assert "_compromised_riposte(msg, 'scam')" not in f["on_message"]


def test_F7_grooming_retire_et_alerte_et_garde_la_preuve_en_ticket():
    src = (RACINE / "bot.py").read_text(encoding="utf-8")
    assert "grooming_detector" not in src and not (RACINE / "grooming_detector.py").exists()
    assert "'grooming_action': 'alerte'" in src
    corps = _fonctions()["on_message"]
    i = corps.index("pmineurs.analyser(")
    assert "if not is_ticket:" in corps[i:i + 400]


def test_F8_un_raid_n_isole_que_les_comptes_recents():
    corps = _fonctions()["_handle_antiraid_join"]
    i = corps.index("recent_members.append(m)")
    assert ".days < min_age_days" in corps[i - 400:i]


def test_F9_ping_de_role_exclusion_seulement_avec_un_lien_d_arnaque():
    corps = _fonctions()["on_message"]
    i = corps.index("'Mention de rôle / @everyone (interdite)'")
    bloc = corps[i:i + 900]
    assert "check_phishing(ct)[0] or check_scam(ct)[0] or check_shortener(ct)[0]" in bloc
    assert "_isoler_par_securite" in bloc and "_offense_tick" in bloc


def _msg(contenu="", reponse=False):
    return type("M", (), {"content": contenu, "reference": object() if reponse else None})()


def test_F10_une_insulte_ne_vise_que_si_elle_s_adresse_a_quelqu_un():
    vise = _extraire("_INSULT_TARGET_RE", "_MENTION_ECRITE_RE", "_insulte_visee")["_insulte_visee"]
    assert not vise(_msg("c'est bâtard ce jeu", reponse=True), "c'est bâtard ce jeu")
    assert vise(_msg("bâtard", reponse=True), "bâtard"), "une réponse réduite à l'insulte"
    assert vise(_msg("t'es un bâtard"), "t'es un bâtard")
    assert vise(_msg("<@123> bâtard"), "bâtard")


def test_F11_rapporter_ce_qu_on_a_subi_n_est_pas_insulter():
    rx = _extraire("_DISCOURS_RAPPORTE_RE")["_DISCOURS_RAPPORTE_RE"]
    for t in ("il m'a dit d'aller me pendre", "on m'a traité de sale noir", "m'a traité de pd",
              "he told me to kys", "ils m'ont écrit des horreurs"):
        assert rx.search(t), t
    assert not rx.search("va te pendre")


def test_F12_menaces_dures_seulement_adresse_ville_ip_dox():
    import insult_filter as I
    for t in ("je viens chez toi ce soir", "je vais te retrouver dans la map", "i'm coming for you",
              "je sais qui tu es vraiment, t'es le tueur", "je vais te planter là"):
        assert not I.threat_hit(t), t
    assert I.threat_hit("je sais où tu habites") and I.threat_hit("j'ai ton ip")
    assert I.threat_soft_hit("je vais te poignarder") and not I.threat_hit("je vais te poignarder")


def test_F13_prenoms_et_mots_courants_hors_du_lexique():
    import insult_filter as I
    for t in ("Jude Bellingham a encore marqué", "le film avec Johnny Depp", "Niki Lauda en F1",
              "mon père est portos", "un vrai rital", "jestem Polak"):
        assert I.scan(t)[0] == 0, t


def test_F14_liens_masques_par_nom_de_domaine():
    ns = _extraire("TRUSTED_DOMAINS_FOR_MASKING", "check_masked_links", "_domaine_de_confiance", ns=_filtres_liens())
    lien_masque = ns["check_masked_links"]
    assert not lien_masque("[youtube.com](https://youtu.be/abc)")[0]
    assert not lien_masque("[roblox.com](https://www.roblox.com/games/1)")[0]
    assert lien_masque("[discord.com](https://discord.com.evil.ru/nitro)")[0]
    assert lien_masque("[roblox.com](https://rblx-login.ru/x)")[0]


def test_F15_qr_seulement_quand_on_parle_de_qr():
    qr = _extraire("check_qr_code_scam")["check_qr_code_scam"]
    for t in ("scanner le code promo du jeu", "le token de mon bot discord ne marche plus", "qr"):
        assert not qr(t)[0], t
    assert qr("scan this qr code to claim your nitro")[0]
    assert qr("connexion par qr code obligatoire, scanne-le")[0]


def test_F16_un_message_court_dans_trois_salons_n_est_pas_du_spam():
    import behavior_guard as BG
    BG._xchan.clear()
    assert not any(BG.track_xchannel(1, 7, s, "salut") for s in (1, 2, 3))
    BG._xchan.clear()
    assert [BG.track_xchannel(1, 7, s, "achetez mes robux pas chers ici") for s in (1, 2, 3)][-1]
    corps = _fonctions()["on_message"]
    i = corps.index("behavior_guard.track_xchannel(")
    assert "if _xs <= 1:" in corps[i:i + 900], "la première fois, un rappel"


def test_F17_du_code_banal_n_est_pas_un_vol_de_jeton():
    import token_grabber as T
    assert T.scan_message("j'utilise requests.post( et webhook.send pour mon bot")["severity"] == "low"
    assert T.scan_message("os.getenv('LOCALAPPDATA') puis leveldb et CryptUnprotectData")["severity"] == "high"
    src = (RACINE / "token_grabber.py").read_text(encoding="utf-8")
    assert "THEN 1" in src, "le compteur de récidive repart de zéro après 24 h"
    assert "exclure = (sanctionner" in src


def test_F18_toute_reponse_coupe_un_monologue_et_une_galerie_compte_pour_un():
    import time as _t
    serie = _extraire("_MONOLOGUE_PAUSE", "_compter_serie", ns={"_monologue_tracker": {}, "time": _t})["_compter_serie"]
    salon = type("S", (), {"id": 5})()

    def m(uid):
        return type("M", (), {"channel": salon, "author": type("A", (), {"id": uid})()})()
    assert [serie(m(1)) for _ in range(3)] == [1, 2, 3]
    serie(m(2))
    assert serie(m(1)) == 1, "la réponse d'un autre (staff, bot…) coupe la série"
    corps = _fonctions()["on_message"]
    assert "_buf.append(_now_f)" in corps and "fresh_escalate=_inconnu" in corps


def test_F19_les_lexiques_se_chargent_a_l_import():
    """Le nettoyage du 19/10 au matin avait retiré `_load()` : filtre d'insultes et hors-sujet muets."""
    import subprocess
    import sys
    code = ("import insult_filter as I, offtopic_filter as O; "
            "assert I.scan('espece de fils de pute')[0] >= 2; assert I.threat_hit('je sais où tu habites'); "
            "assert O._RE is not None")
    r = subprocess.run([sys.executable, "-c", code], cwd=RACINE, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_F20_bd_chemin_et_adresses_de_service_ne_sont_pas_des_coordonnees():
    ns = _extraire("_PII_EMAIL_RE", "_VOIE_SURE", "_VOIE_AMBIGUE", "_PII_ADDR_RE", "_EMAIL_DE_SERVICE",
                   "_email_perso")
    adresse, mail = ns["_PII_ADDR_RE"].search, ns["_email_perso"]
    for phrase in ("j'ai lu 3 bd de one piece", "j'ai 10 bd manga", "il reste 2 chemin pour finir l'obby",
                   "prends le 2 av le boss", "4 BD manga", "3 cours demain", "4 place de libre"):
        assert not adresse(phrase), phrase
    for phrase in ("écris à support@roblox.com", "contact@studio.fr pour les partenariats",
                   "appeals+fr@roblox.com"):
        assert not mail(phrase), phrase
    for phrase in ("j'habite au 12 rue victor hugo", "12 bd Haussmann", "5 chemin des vignes",
                   "3 av. de la république", "12 bis rue de la paix", "8 allée des roses"):
        assert adresse(phrase), phrase
    assert mail("mon mail c'est lucas.martin2012@gmail.com")
    assert mail("support@roblox.com ou moi : lea.d@hotmail.fr"), "une adresse perso parmi d'autres"
