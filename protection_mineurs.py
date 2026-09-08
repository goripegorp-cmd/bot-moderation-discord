"""Détection des approches prédatrices — « grooming » — sur un serveur de jeu.

═══════════════════════════════════════════════════════════════════════════════
DEMANDE DU PROPRIÉTAIRE (06/09/2026)
═══════════════════════════════════════════════════════════════════════════════
    « des gens qui ramènent les autres, les voir en privé pour des photos […]
     ça peut être une rencontre comme une amitié, mais ça peut être une
     rencontre comme quelqu'un qui veut tenter des trucs bizarres […] faut
     vraiment bien cibler le problème »

C'est une communauté Roblox : le public est en grande partie mineur. Le risque
n'est pas théorique.

═══════════════════════════════════════════════════════════════════════════════
POURQUOI CE N'EST PAS UNE LISTE DE MOTS INTERDITS
═══════════════════════════════════════════════════════════════════════════════
⚠️ LE PIÈGE, ET IL EST FATAL. « photo », « mp », « rencontre », « quel âge » —
pris isolément, ces mots sont le quotidien d'un serveur de jeu. Une liste de
mots interdits produirait des dizaines d'alertes par jour, toutes fausses. Au
bout d'une semaine le staff coupe le filtre, et le jour où un vrai prédateur
écrit, plus personne ne regarde. **Un filtre bruyant protège moins qu'un
filtre absent**, parce qu'il détruit l'attention.

On raisonne donc en SIGNAUX COMBINÉS, comme `check_image_scam` déjà présent
dans ce dépôt :

  · TROIS familles suffisent SEULES, parce qu'elles n'ont aucun usage innocent
    dans un serveur de jeu :
        SEXUEL   — sollicitation d'images intimes ;
        SITE     — sites de rencontre ou pour adultes ;
        SECRET   — l'isolement : « le dis à personne », « c'est notre secret »,
                   « supprime ce message ». C'est LA signature du grooming, et
                   c'est celle qu'un enfant ne sait pas reconnaître.

  · QUATRE familles ne comptent qu'À DEUX, parce que chacune est banale seule :
        PRIVE    — « viens en mp », « ajoute mon snap » ;
        IMAGE    — « une photo de toi », « tu ressembles à quoi » ;
        AFFECT   — « tu me plais », « on sort ensemble » ;
        AGE      — « t'as quel âge », « t'es seul chez toi ».

    « mp moi » seul = un échange normal. « mp moi » + « envoie une photo de
    toi » = le motif qu'on cherche.

⚠️ CE MODULE NE SANCTIONNE PAS TOUT SEUL AU-DELÀ DU PALIER FORT. Accuser à
tort quelqu'un d'approche prédatrice est une accusation grave, publique et
difficile à défaire. Le module rend un verdict et un MOTIF LISIBLE ; c'est
l'appelant qui décide, et le staff qui tranche.
"""
from __future__ import annotations

import re
import unicodedata

# ═══════════════════════════════════════════════════════════════════════════════
#  Normalisation — l'obfuscation est la première parade d'un prédateur
# ═══════════════════════════════════════════════════════════════════════════════

_ZERO_WIDTH = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD], None)

#  ⚠️ PAS DE « l » → « i ». Ça casserait « fille », « belle », « appelle » et
#  transformerait des mots ordinaires en faux positifs. Le leet retenu est
#  celui qu'on observe réellement : chiffres et symboles évidents.
_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
    "@": "a", "$": "s", "€": "e", "!": "i", "+": "t",
})


def normaliser(texte: str) -> str:
    """Minuscule, accents retirés, invisibles supprimés, leet réduit, séparateurs
    écrasés — pour que « p h o t o » et « ph0to » soient vus comme « photo ».

    ⚠️ ON GARDE LES ESPACES SIMPLES. Tout coller (« photodetoi ») ferait
    apparaître des mots à cheval sur deux mots voisins, et chaque frontière
    deviendrait une source de faux positifs.
    """
    try:
        t = (texte or "").lower()
        t = t.translate(_ZERO_WIDTH)
        t = unicodedata.normalize("NFKD", t)
        t = "".join(c for c in t if not unicodedata.combining(c))
        t = t.translate(_LEET)
        #  « p.h.o.t.o », « p-h-o-t-o », « p h o t o » → « photo »
        t = re.sub(r"(?<=\b\w)[\s.\-_*]+(?=\w\b)", "", t)
        #  ⚠️ L'APOSTROPHE DISPARAÎT, ELLE N'EST PAS REMPLACÉE PAR UN
        #  ESPACE. « t'as » doit devenir « tas » : c'est la forme que
        #  visent les motifs. La remplacer par un espace donnerait
        #  « t as », que rien ne reconnaît — quatre cas réels manqués au
        #  calibrage à cause de ça.
        t = t.replace("'", "").replace("\u2019", "")
        t = re.sub(r"[^\w\s]+", " ", t)
        t = re.sub(r"(\w)\1{2,}", r"\1\1", t)      # « phooooto » → « phooto »
        t = re.sub(r"\s+", " ", t).strip()
        return t
    except Exception:
        return (texte or "").lower()


def _rx(motifs) -> re.Pattern:
    return re.compile(r"(?:" + "|".join(motifs) + r")", re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════════
#  LES TROIS FAMILLES QUI SUFFISENT SEULES
# ═══════════════════════════════════════════════════════════════════════════════

#  Sollicitation d'images intimes. ⚠️ CHAQUE ENTRÉE PORTE SA QUALIFICATION :
#  « photo » nu ne figure NULLE PART ici, sinon toute capture d'écran de jeu
#  déclencherait l'alerte.
_SEXUEL = [
    r"\bnudes?\b", r"\bnude\b", r"\bnudz\b",
    r"\bdick\s*pics?\b", r"\bdickpics?\b",
    r"\bphotos?\s+(?:de\s+)?(?:toi\s+)?(?:tout(?:e)?\s+)?nu(?:e|es|s)?\b",
    r"\bphotos?\s+(?:coquine|hot|sexy|intime|denudee)s?\b",
    r"\btu\s+m['e]\s*envoie[sz]?\s+(?:une\s+)?photo\s+(?:coquine|hot|sexy|nue)",
    r"\bmontre\s+(?:moi\s+)?(?:ton|ta|tes)\s+(?:corps|poitrine|sein|fesse|"
    r"cul|zizi|bite|chatte|intimite)",
    r"\benvoie\s+(?:moi\s+)?(?:une\s+)?photo\s+(?:sans|en)\s+(?:vetement|"
    r"sous.?vetement|culotte|slip)",
    r"\bsend\s+nudes?\b", r"\bsexcam\b", r"\bsexting\b",
    r"\bphoto\s+de\s+(?:tes?\s+)?(?:pieds|fesses|seins)\b",
    r"\bt(?:u\s+es|es)\s+en\s+(?:culotte|slip|sous.?vetement)",
    r"\bon\s+se\s+fait\s+un\s+(?:sexe|plan\s+cul)\b",
    r"\bplan\s+cul\b", r"\bsnap\s+(?:hot|coquin)\b",
]

#  Sites de rencontre / adultes. Aucun usage légitime dans une communauté de
#  jeu majoritairement mineure : le simple fait d'y renvoyer est le problème.
_SITE = [
    r"\bonlyfans?\b", r"\bonly\s*fans\b", r"\bo\s*f\s+(?:link|lien)\b",
    r"\bmym\.fans\b", r"\bfansly\b", r"\bchaturbate\b", r"\bstripchat\b",
    r"\bpornhub\b", r"\bxvideos\b", r"\bxhamster\b", r"\bredtube\b",
    r"\btinder\b", r"\bbadoo\b", r"\bgrindr\b", r"\bbumble\b",
    r"\badopteunmec\b", r"\bmeetic\b", r"\bcoco\.(?:gg|fr)\b",
    r"\bomegle\b", r"\bchatroulette\b",
    r"\bsites?\s+de\s+rencontres?\b",
    r"\brencontres?\s+(?:coquine|sexe|adulte|sans\s+lendemain)s?\b",
    r"\bwebcam\s+(?:hot|coquine|sexe)\b",
]

#  L'OFFRE DE RENCONTRE TARIFÉE — cas réel du 06/09/2026, supprimé à la main
#  par le propriétaire parce que le bot ne l'avait pas vu :
#      « Je suis disponible pour des rencontres coquine payant sans prise de
#        tête écrit moi si tu es intéressé »
#  Aucun usage innocent sur un serveur de jeu pour mineurs.
_TARIF = [
    r"\bescorte?\b", r"\bescort\s*girl\b",
    r"\bsugar\s*(?:daddy|baby|mamma|momma)\b",
    r"\brencontres?\s+(?:payante|tarifee|remuneree)s?\b",
    r"\brencontres?\s+\w{0,12}\s*payant",
    r"\b(?:je\s+suis\s+)?disponible\s+pour\s+(?:des\s+)?rencontres?\b",
    r"\bdispo\s+pour\s+(?:des\s+)?rencontres?\b",
    r"\bmoments?\s+(?:coquin|intime|chaud)s?\s+(?:payant|contre)",
    r"\bje\s+vends\s+(?:mes\s+)?(?:photos|videos|contenus?)\b",
    r"\bcontenus?\s+(?:prive|exclusif)s?\s+payants?\b",
    r"\btarifs?\s+(?:sur\s+demande|en\s+mp|en\s+dm)\b",
    r"\bpaid\s+(?:meet|meetup|content)\b",
]

#  L'ISOLEMENT — la signature du grooming, et celle qu'un enfant ne sait pas
#  reconnaître. ⚠️ « c'est un secret » seul est exclu : un serveur de jeu est
#  plein de surprises et de cadeaux. On exige la consigne de SILENCE ou
#  d'EFFACEMENT, qui n'a pas d'usage innocent entre un adulte et un enfant.
_SECRET = [
    r"\bne?\s*(?:le\s+)?dis\s+(?:surtout\s+)?(?:rien\s+)?(?:a\s+)?"
    r"(?:personne|tes\s+parents|ta\s+mere|ton\s+pere|tes\s+potes)",
    r"\bdis\s+le\s+a\s+personne\b",
    r"\bgarde\s+(?:ca|le|cela)\s+(?:pour\s+toi|secret|entre\s+nous)\b",
    r"\bc'?est\s+(?:notre|un)\s+secret\s+(?:a\s+nous|entre\s+nous)\b",
    r"\breste\s+entre\s+nous\b", r"\bque\s+ca\s+reste\s+entre\s+nous\b",
    #  ⚠️ QUALIFIÉ, PAS NU. « supprime ce message » tout court est écrit tous
    #  les jours par un modérateur qui range un doublon — mesuré en faux
    #  positif au calibrage. Seule la consigne d'effacement APRÈS LECTURE, ou
    #  visant la conversation entière, n'a pas d'usage innocent.
    r"\bsupprime\s+(?:ce\s+)?message\s+(?:apres|des\s+que|quand\s+tu)",
    r"\bsupprime\s+(?:nos\s+messages|la\s+conversation|notre\s+conversation)",
    r"\befface\s+(?:nos\s+messages|la\s+conversation|notre\s+conversation)",
    r"\bne\s+screen\s+pas\b", r"\bne\s+montre\s+(?:ca\s+)?a\s+personne\b",
    r"\bdont\s+tell\s+(?:anyone|your\s+parents)\b",
    r"\bour\s+little\s+secret\b", r"\bdelete\s+our\s+(?:message|chat)\b",
]

#  L'ISOLEMENT PHYSIQUE — famille SÉPARÉE du sondage d'âge, et c'est délibéré.
#  ⚠️ « how old are you ? are you alone » n'avait qu'UNE famille et passait
#  entre les mailles au calibrage. Or demander à un enfant s'il est SEUL CHEZ
#  LUI est le marqueur le plus caractéristique du grooming : mélangé au
#  sondage d'âge, il n'ajoutait rien ; séparé, il fait basculer.
_ISOLEMENT = [
    r"\bt(?:u\s+es|es)\s+(?:tout\s+)?seul(?:e)?\s*(?:chez\s+toi|a\s+la\s+maison|"
    r"dans\s+ta\s+chambre)?\b",
    r"\btes\s+parents\s+(?:sont\s+la|dorment|travaillent|sont\s+pas\s+la|"
    r"sont\s+absents)\b",
    r"\bpersonne\s+(?:ne\s+)?(?:te\s+)?(?:regarde|voit|ecoute)\b",
    r"\byaa?\s+personne\s+(?:avec\s+toi|chez\s+toi)\b",
    r"\bare\s+(?:you|u)\s+alone\b", r"\bis\s+anyone\s+(?:with|near)\s+you\b",
]

# ═══════════════════════════════════════════════════════════════════════════════
#  LES QUATRE FAMILLES QUI NE COMPTENT QU'À DEUX
# ═══════════════════════════════════════════════════════════════════════════════

#  Passage au privé / hors plateforme. Banal seul : on s'ajoute pour jouer.
_PRIVE = [
    r"\b(?:viens?|passe|parle|discute|rejoins?)\s+(?:moi\s+)?en\s+"
    r"(?:mp|dm|prive|priver)\b",
    r"\bmp\s*(?:moi|-?moi)\b", r"\bdm\s*me\b", r"\bdm\s*moi\b",
    r"\bajoute\s+(?:moi\s+)?(?:sur\s+)?(?:snap|insta|instagram|tel|telegram|"
    r"whats?app|discord|tiktok)\b",
    r"\b(?:mon|ton)\s+(?:snap|snapchat|insta|instagram|telegram|whats?app)\b",
    r"\bon\s+(?:se\s+)?parle\s+(?:ailleurs|autre\s+part|en\s+prive)\b",
    r"\bvocal\s+(?:prive|a\s+deux|en\s+tete\s+a\s+tete)\b",
    r"\brejoins?\s+moi\s+(?:en\s+)?vocal\b",
    r"\bhit\s+me\s+up\s+(?:on|in)\s+dm\b",
]

#  Demande d'image PERSONNELLE. ⚠️ « photo » nu est volontairement absent :
#  dans un serveur Roblox, une photo est neuf fois sur dix une capture d'écran.
#  On exige le rattachement à la PERSONNE.
_IMAGE = [
    r"\bphotos?\s+de\s+(?:toi|ta\s+(?:tete|gueule|face)|ton\s+visage)\b",
    r"\b(?:ta|ton|une)\s+photo\s+(?:irl|en\s+vrai|reelle)\b",
    r"\benvoie\s+(?:moi\s+)?(?:une\s+)?(?:photo|selfie|pic)\s+de\s+toi\b",
    r"\bmontre\s+(?:moi\s+)?(?:ton\s+visage|ta\s+tete|a\s+quoi\s+tu\s+ressemble)",
    r"\btu\s+ressemble[sz]?\s+a\s+quoi\b", r"\bt(?:u\s+es|es)\s+comment\s+irl\b",
    r"\bselfies?\b", r"\bphoto\s+irl\b",
    r"\ballume\s+(?:ta\s+)?(?:cam|camera|webcam)\b",
    r"\bon\s+fait\s+(?:une\s+)?(?:cam|video)\s+(?:a\s+deux|prive)\b",
    r"\bpics?\s+of\s+(?:you|u)\b", r"\bshow\s+(?:me\s+)?your\s+face\b",
]

#  Registre affectif / romantique adressé. Banal entre amis du même âge ;
#  significatif combiné à autre chose.
_AFFECT = [
    r"\btu\s+me\s+(?:plai[sz]|kiff|fait\s+craquer)\b",
    r"\bje\s+(?:te\s+)?(?:kiff|t'?aime|suis\s+amoureux|craque\s+pour\s+toi)\b",
    r"\bon\s+sort\s+ensemble\b", r"\btu\s+veux\s+sortir\s+avec\s+moi\b",
    r"\bveux\s+tu\s+etre\s+ma\s+(?:copine|petite\s+amie|meuf)\b",
    r"\bt(?:u\s+es|es)\s+(?:trop\s+)?(?:belle|beau|mignonne?|sexy|bonne)\b",
    r"\bmon\s+(?:bebe|coeur|amour|chaton)\b",
    r"\bje\s+t'?attends\s+(?:mon|ma)\s+(?:cheri|cherie)\b",
    r"\bbe\s+my\s+girlfriend\b", r"\byou'?re\s+(?:so\s+)?(?:cute|hot|sexy)\b",
]

#  Sondage d'âge et de surveillance. Très banal entre enfants ; c'est la
#  COMBINAISON avec le reste qui parle.
_AGE = [
    r"\bt(?:u\s+as|as|es)\s+quel\s+age\b", r"\bquel\s+age\s+(?:tu\s+as|as\s+tu)\b",
    r"\bt(?:u\s+es|es)\s+(?:en\s+)?(?:cm2|6eme|5eme|4eme|3eme|college|primaire)\b",
    r"\btu\s+(?:habites?|vis)\s+ou\b", r"\btu\s+es\s+de\s+quelle\s+ville\b",
    r"\bhow\s+old\s+are\s+(?:you|u)\b",
]

#  Les tournures d'annonce. ⚠️ TOUTES BANALES SEULES — « écris-moi si tu es
#  intéressé » se dit pour vendre un accessoire Roblox. C'est leur cumul avec
#  une autre famille qui parle.
_ANNONCE = [
    r"\bsans\s+prise\s+de\s+tete\b",
    r"\becri[st]\s+moi\s+si\s+(?:tu\s+es|t\s*es)\s+interesse",
    r"\becrive[sz]\s+moi\s+en\s+(?:prive|mp|dm)\b",
    r"\bpas\s+serieux\s+s\s*abstenir\b",
    r"\bhomme\s+ou\s+femme\s+peu\s+importe\b",
    r"\bje\s+suis\s+dispo\b",
]

#  L'effacement NU : banal seul (un doublon qu'on range), significatif combiné.
_EFFACEMENT = [
    r"\bsupprime\s+(?:ce\s+)?message\b",
    r"\befface\s+(?:ce\s+)?message\b",
    r"\bdelete\s+(?:this|that)\s+message\b",
]

_RE = {
    "sollicitation sexuelle": _rx(_SEXUEL),
    "site de rencontre / adulte": _rx(_SITE),
    "consigne de silence (isolement)": _rx(_SECRET),
    "passage en privé": _rx(_PRIVE),
    "demande de photo personnelle": _rx(_IMAGE),
    "avances affectives": _rx(_AFFECT),
    "sondage d'âge": _rx(_AGE),
    "sondage d'isolement (seul chez toi ?)": _rx(_ISOLEMENT),
    "demande d'effacement": _rx(_EFFACEMENT),
    "offre de rencontre tarifée": _rx(_TARIF),
    "tournure d'annonce": _rx(_ANNONCE),
}

#  Les trois qui déclenchent SEULES.
FAMILLES_FORTES = frozenset({
    "sollicitation sexuelle",
    "site de rencontre / adulte",
    "consigne de silence (isolement)",
    "offre de rencontre tarifée",
})

#  Nombre de familles faibles requis pour déclencher.
SEUIL_COMBINE = 2


def analyser(texte: str, deja_normalise: str | None = None) -> dict:
    """Rend `{"touche", "gravite", "familles", "motif", "extraits"}`.

    `gravite` : "forte" (une famille sans usage innocent), "combinee" (au moins
    deux familles banales ensemble), ou "" si rien.

    ⚠️ FAIL-OPEN. Une erreur ici ne doit RIEN bloquer : un défaut de filtre ne
    doit pas supprimer les messages d'un serveur entier.
    """
    out = {"touche": False, "gravite": "", "familles": [], "motif": "",
           "extraits": []}
    try:
        brut = texte or ""
        norm = deja_normalise if deja_normalise is not None else normaliser(brut)
        if not norm:
            return out

        for nom, rx in _RE.items():
            m = rx.search(norm) or rx.search(brut.lower())
            if m:
                out["familles"].append(nom)
                out["extraits"].append(m.group(0)[:60])

        fortes = [f for f in out["familles"] if f in FAMILLES_FORTES]
        faibles = [f for f in out["familles"] if f not in FAMILLES_FORTES]

        if fortes:
            out["touche"] = True
            out["gravite"] = "forte"
        elif len(faibles) >= SEUIL_COMBINE:
            out["touche"] = True
            out["gravite"] = "combinee"

        if out["touche"]:
            out["motif"] = " + ".join(out["familles"])
        return out
    except Exception as ex:
        print(f"[protection_mineurs] {ex}")
        return {"touche": False, "gravite": "", "familles": [], "motif": "",
                "extraits": []}


def resume(res: dict) -> str:
    """Une ligne pour le journal staff. Cite les EXTRAITS, pas seulement les
    familles : sans le texte exact, le staff ne peut pas juger."""
    if not res.get("touche"):
        return ""
    tete = ("🚨 **Approche prédatrice — signal FORT**" if res["gravite"] == "forte"
            else "⚠️ **Approche prédatrice — signaux combinés**")
    ext = " · ".join(f"« {e} »" for e in res.get("extraits", [])[:4])
    return f"{tete}\nFamilles : {res['motif']}\nRelevé : {ext}"
