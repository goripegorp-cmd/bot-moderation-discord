"""29/10/2026 (audit des protections) : de vraies phrases de joueurs ne déclenchent rien ; l'arnaque
« giveaway crypto + lien » est prise. Fonctions réelles du bot."""
import os

os.environ.setdefault("FAUX_JETON", "1")
import bot as B  # noqa: E402

NORMAUX = [
    "gg wp les gars, on refait un raid ce soir ?", "je viens de drop un fruit légendaire trop content",
    "regarde ma vidéo https://youtu.be/dQw4w9WgXcQ", "je trade mon fruit contre 2M berry",
    "free fruit à qui veut sur le serveur", "j'ai gagné 1000 robux au concours officiel de roblox",
    "le nouveau update est sorti, nitro boost du serveur merci !", "steam est en promo ce week-end",
    "je veux trader mes crypto, quelqu'un s'y connait ?", "le giveaway du serveur finit ce soir",
    "https://www.roblox.com/games/123/Rell-Seas giveaway 1000 robux ce soir sur le jeu",
]
ARNAQUES = [
    "mrbeast giveaway 5000$ crypto withdraw now https://mr-beast.win",
    "claim your free crypto airdrop https://bonus-claim.xyz",
]


def test_AUDIT_phrases_normales_pas_arnaque():
    for t in NORMAUX:
        assert not B.check_scam(t)[0], t


def test_AUDIT_arnaque_crypto_lien_prise():
    for t in ARNAQUES:
        assert B.check_scam(t)[0], t


def test_AUDIT_approche_predatrice_alerte_protection_des_mineurs_pas_scam():
    import inspect
    import unified_logger as U
    assert U.EVENT_META[U.EventType.SEC_MINEURS]["label"] == "Protection des mineurs"
    src = inspect.getsource(B.on_message)
    i = src.index("pmineurs.analyser(")
    assert "'anti_grooming'" in src[i:i + 800] and "'anti_scam'" not in src[i:i + 800]
    assert "'anti_grooming':   ulogger2026.EventType.SEC_MINEURS" in inspect.getsource(B.send_log)
