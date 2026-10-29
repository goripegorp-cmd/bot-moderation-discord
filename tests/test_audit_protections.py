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
