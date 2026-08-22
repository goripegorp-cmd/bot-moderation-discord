"""activite_textes.py — Tout ce que le système d'activité DIT, en français et en anglais.

═══════════════════════════════════════════════════════════════════════════════
DEUX RÈGLES, DEMANDÉES PAR LE PROPRIÉTAIRE — ET TENUES ICI, PAS AILLEURS
═══════════════════════════════════════════════════════════════════════════════
1. **COURT.** Les gens ne lisent pas. Un pavé d'explication n'est pas lu, donc
   n'informe personne, donc ne sert à rien — et pire, il donne l'impression
   d'une procédure lourde alors que la règle tient en une phrase.
   Contrainte tenue mécaniquement : `verifier_longueurs()` échoue si une ligne
   dépasse `MAX_LIGNE` caractères. Un test la lance. On ne peut donc pas
   « juste rajouter une petite précision » sans que ça casse.

2. **BILINGUE FR + EN.** Un serveur international : une annonce qu'une moitié
   des membres ne comprend pas produit exactement l'inactivité qu'on combat.
   Chaque texte est donc un couple, jamais une chaîne seule.

═══════════════════════════════════════════════════════════════════════════════
ZÉRO JARGON
═══════════════════════════════════════════════════════════════════════════════
Interdits dans les textes membres : « palier », « escalade », « seuil »,
« fenêtre glissante », « restitution ». Ce sont des mots de développeur.
Le membre lit « 7 jours sans rien → rôle AFK », pas « palier 1 atteint ».
Le vocabulaire technique reste dans le code et dans les panneaux du staff.
"""
from __future__ import annotations

#  Aucune ligne de texte membre ne doit dépasser ça. Ce n'est pas une limite
#  Discord : c'est la limite au-delà de laquelle un lecteur décroche.
MAX_LIGNE = 90

#  Les deux drapeaux servent de repère visuel instantané : on trouve sa langue
#  sans lire. Les codes sont mis en constante pour qu'un changement de style
#  (drapeau → « FR · ») se fasse en un seul endroit.
FR = "🇫🇷"
EN = "🇬🇧"


def duo(fr: str, en: str) -> str:
    """Une ligne française et son équivalent anglais, l'une sous l'autre."""
    return f"{FR} {fr}\n{EN} {en}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Les gestes qui comptent — la seule chose que le membre doit vraiment retenir
# ═══════════════════════════════════════════════════════════════════════════════

GESTES = "💬 message  ·  🎤 vocal  ·  👍 réaction"


# ═══════════════════════════════════════════════════════════════════════════════
#  Titres
# ═══════════════════════════════════════════════════════════════════════════════

T_ABSENTS = "💤 Absents · Away"
T_PRESQUE = "👀 Presque · Almost"
T_ROLES_RETIRES = "🔒 Rôles retirés · Roles removed"
T_BIENVENUE = "👋 Re-bienvenue · Welcome back"
T_REGLES = "📋 Comment rester · How to stay"


# ═══════════════════════════════════════════════════════════════════════════════
#  Corps de message
# ═══════════════════════════════════════════════════════════════════════════════

def revenir(salon_mention: str | None = None) -> str:
    """« Comment revenir » — la ligne la plus importante de tout le système.

    Elle passe AVANT toute justification : quelqu'un qui ne lit qu'une ligne doit
    tomber sur l'action à faire, pas sur la raison du message.
    """
    if salon_mention:
        return duo(f"Écris dans {salon_mention} pour tout récupérer.",
                   f"Write in {salon_mention} to get everything back.")
    return duo(f"Un geste suffit : {GESTES}", f"One is enough: {GESTES}")


def vu_trop_peu(presents: int, fenetre: int) -> str:
    """Le rappel doux : présent, mais trop rarement.

    Le ton est volontairement léger. Ce membre EST venu ; le braquer maintenant
    le ferait partir alors qu'il suffit de peu pour le ramener.
    """
    return duo(f"Vu {presents} jour sur {fenetre}. Essaie un peu plus.",
               f"Seen {presents} day out of {fenetre}. Try a bit more.")


def presence_demandee(exige: int, fenetre: int) -> str:
    """La RÈGLE, quand le message s'adresse à un rôle et non à des personnes.

    ⚠️ Ne jamais utiliser les chiffres d'UN membre ici. Le palier « doux »
    couvre aussi bien 0 jour vu que 2 : afficher « Vu 0 jour sur 3 » à des
    centaines de personnes serait faux pour la plupart, et il n'y a plus de
    ligne par membre pour rétablir la vérité. On annonce donc le seuil.
    """
    j = "jour" if exige <= 1 else "jours"
    d = "day" if exige <= 1 else "days"
    return duo(f"Il faut se montrer au moins {exige} {j} sur {fenetre}. "
               f"Un message suffit.",
               f"You need to show up at least {exige} {d} out of {fenetre}. "
               f"One message is enough.")


def apres_expulsion() -> str:
    """Message privé au membre expulsé pour inactivité qui revient.

    Il n'accuse pas et ne menace pas : il rappelle le fait, donne la règle, et
    s'arrête. Trois lignes — au-delà, il n'est plus lu.
    """
    return duo("Tu étais parti pour inactivité. Un message par jour suffit à rester.",
               "You were removed for inactivity. One message a day is enough to stay.")


def pas_une_sanction() -> str:
    """Le pied de page. Court : la nuance se dit en une ligne ou pas du tout."""
    return "-# 🇫🇷 Pas une sanction · 🇬🇧 Not a punishment"


def regles(rappel: int, retrait: int, expulsion: int) -> list[str]:
    """La procédure complète, en quatre lignes numérotées.

    Les durées viennent de la CONFIGURATION, jamais écrites en dur : un serveur
    qui règle le retrait à 30 jours doit voir « 30 » ici, sinon l'annonce ment
    aux membres — et une annonce qui ment est pire que pas d'annonce.
    """
    return [
        duo(f"Sois vu 1 fois par jour — {GESTES}",
            f"Be seen once a day — {GESTES}"),
        duo(f"{rappel} jours sans rien → rôle AFK",
            f"{rappel} days silent → AFK role"),
        duo(f"{retrait} jours → tu perds tes rôles",
            f"{retrait} days → you lose your roles"),
        duo(f"{expulsion} jours → départ du serveur",
            f"{expulsion} days → removed from the server"),
    ]


def retour_tout_revient() -> str:
    return duo("1 message et tout revient.", "1 message and everything comes back.")


def semaine_du(debut, fin) -> str:
    """Pied de page datant le rappel. Format identique dans les deux langues.

    ⚠️ SANS le préfixe `-#` : ce texte part dans `v2_subtitle`, qui l'ajoute
    déjà. Le mettre ici produisait un `-# -#` visible à l'écran.
    """
    return f"{debut.strftime('%d/%m')} → {fin.strftime('%d/%m')}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Le garde-fou de longueur
# ═══════════════════════════════════════════════════════════════════════════════

def verifier_longueurs() -> list[str]:
    """Rend la liste des lignes trop longues. Vide = tout va bien.

    Appelée par les tests. Sans ça, la règle « court » se dégrade au fil des
    retouches : personne ne compte les caractères à la main, et le pavé revient
    en trois modifications innocentes.
    """
    echantillons = [
        revenir(), revenir("#retour"), vu_trop_peu(1, 7), apres_expulsion(),
        pas_une_sanction(), retour_tout_revient(), *regles(7, 14, 21),
        #  Le texte du palier doux quand il s'adresse au RÔLE : il remplace la
        #  liste de centaines de pseudos, il doit tenir sur une ligne.
        presence_demandee(1, 7), presence_demandee(3, 7),
    ]
    trop_longues = []
    for bloc in echantillons:
        for ligne in bloc.split("\n"):
            if len(ligne) > MAX_LIGNE:
                trop_longues.append(ligne)
    return trop_longues
