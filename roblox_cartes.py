"""roblox_cartes.py — Les articles offerts avec les cartes cadeaux Roblox.

DEMANDE DU PROPRIÉTAIRE (29/09/2026)
    « il y a eu des nouveaux accessoires obtenibles par les cartes cadeaux […]
      On achète des cartes cadeaux à chaque fois, ça change les items.
      J'aimerais aussi que tu affiches les items disponibles dans les cartes
      cadeaux. Que ce soit optimisé. »

═══════════════════════════════════════════════════════════════════════════════
LA SOURCE — LA PAGE OFFICIELLE, ET RIEN D'AUTRE (mesuré le 29/09)
═══════════════════════════════════════════════════════════════════════════════
  · https://www.roblox.com/giftcards-fr est une coquille : la liste vit dans son
    script `https://js.rbxcdn.com/<empreinte>-GiftCards.js`, en dur, pays par
    pays : `{countries:[…,"fr",…],config:{bonus_items:z,cashstar_items:N,
    items:y}}`, et plus haut `y=[0x7f0a82b787c3,…]` — des identifiants
    d'articles écrits en hexadécimal. Les noms de variables changent à chaque
    version du script : on suit la configuration, jamais un nom.
  · Pour la France ce jour-là : Icarus Wings (carte en magasin, septembre
    2026 ; aussi en carte numérique), Cap of Hermes, Helm of Ares, Minotaur Head
    (codes numériques Amazon), Medusa Snakes (code bonus des cartes achetées sur
    roblox.com/giftcards).
  · Les articles du mois suivant sont DÉJÀ au catalogue (Sparkling Robux
    Shades : « … from select retailers in October 2026 »), hors vente, mais pas
    encore sur la page : seule la page dit ce qu'une carte donne AUJOURD'HUI.
    C'est aussi pourquoi le flux « nouveautés » ne les publie pas à leur
    création (règle d'or : hors vente et pas Limited) — ils sortent ICI, le
    jour où une carte les donne.

═══════════════════════════════════════════════════════════════════════════════
OPTIMISÉ
═══════════════════════════════════════════════════════════════════════════════
La page (~60 Ko) au plus toutes les HEURES_ENTRE_LECTURES ; le script (~170 Ko)
seulement quand son empreinte change ; une fiche Discord seulement quand la
liste change — une par mois, en pratique. Pages publiques, identité du bot
affichée telle quelle ; un refus (pare-feu, 403, 429) attend la lecture
suivante, sans rien contourner.

═══════════════════════════════════════════════════════════════════════════════
LE MOIS SUIVANT — SEULEMENT CE QUI EST SÛR (demande du 29/09, après-midi)
═══════════════════════════════════════════════════════════════════════════════
    « On peut mettre les prochains, mais il faut que tu sois sûr de toi. »
La page officielle ne contient QUE le mois en cours (vérifié le 29/09 : aucun
article d'octobre dans son script). La seule preuve écrite du mois suivant est
la description de l'article « carte en magasin » : « Get this item when you
redeem a Roblox Gift Card from select retailers in October 2026 ». Mesuré sur
714 créations de Roblox : un article par mois, d'août 2025 à octobre 2026,
créé un à quatre mois à l'avance. Les codes Amazon et le code bonus n'écrivent
pas leur mois : ils ne sont JAMAIS annoncés d'avance — on ne devine pas.
Ces annonces sont relevées dans les listes que le relevé de 30 min lit déjà :
zéro requête de plus, mémorisées en base jusqu'à leur mois.

═══════════════════════════════════════════════════════════════════════════════
UNE FICHE COURTE, COMPLÉTÉE SUR PLACE (29/09, après-midi)
═══════════════════════════════════════════════════════════════════════════════
    « Tu regroupes, oui, mais tu t'assures que ça ne prenne pas trop de place
      non plus. Que ce soit compréhensible. »
Une ligne par carte à acheter, les noms en liens, une seule image (voir
`roblox_panneau.construire_cartes`). Une NOUVELLE liste fait une fiche neuve,
avec ping ; le mois suivant annoncé ou une nouvelle présentation
(`VERSION_FICHE`) font MODIFIER la fiche déjà publiée — pas un message de plus.
"""
from __future__ import annotations

import asyncio
import re

import roblox_veille as veille

PAGE = "https://www.roblox.com/giftcards-fr"
#  La page où l'on échange une carte, pour le bouton de la fiche.
PAGE_ECHANGE = "https://www.roblox.com/redeem"
PAYS = "fr"
HEURES_ENTRE_LECTURES = 3.0
#  Aucune liste n'a jamais été aussi longue ; au-delà, la fiche le DIT
#  (« … et N autre(s) ») au lieu de s'allonger.
MAX_ARTICLES = 10
#  Les articles du mois suivant, sur la ligne 🔜. Roblox en annonce UN par mois
#  (mesuré d'août 2025 à octobre 2026) ; la borne garde la fiche courte si
#  cela changeait.
MAX_PROCHAINS = 4
#  La PRÉSENTATION de la fiche. En changer fait MODIFIER les fiches déjà
#  publiées, sans en poster de nouvelles (voir `signature_suite`) :
#    1 — un bloc illustré par article (29/09 au matin) ;
#    2 — la fiche courte : une ligne par carte, les noms en liens.
VERSION_FICHE = 2
#  Un article dont Roblox n'a rendu AUCUN nom (ni anglais, ni français) : la
#  fiche attend la lecture suivante plutôt que d'afficher « Article 1396… »,
#  au plus ESSAIS_NOMS lectures — ensuite elle part, l'article avec son lien.
ESSAIS_NOMS = 3

MOTIF_SCRIPT = re.compile(r"https://js\.rbxcdn\.com/[0-9a-f]{16,}-GiftCards\.js")
MOTIF_GROUPE = re.compile(r"\{countries:\[([^\]]*)\],config:\{([^{}]*)\}\}")
MOTIF_ENTREE = re.compile(r"([a-z_]+):(\[[^\]]*\]|[A-Za-z_$][\w$]*)")
MOTIF_NOMBRE = re.compile(r"0x[0-9a-fA-F]+|\d+")
CLES = ("items", "bonus_items", "cashstar_items")

_MOIS = {"january": "janvier", "february": "février", "march": "mars",
         "april": "avril", "may": "mai", "june": "juin", "july": "juillet",
         "august": "août", "september": "septembre", "october": "octobre",
         "november": "novembre", "december": "décembre"}
_MOIS_FR = tuple(_MOIS.values())


def _nombres(texte: str) -> list[int]:
    out = []
    for x in MOTIF_NOMBRE.findall(texte or ""):
        v = int(x, 16) if x.lower().startswith("0x") else int(x)
        if v > 0:
            out.append(v)
    return out


def offre_du_script(js: str, pays: str = PAYS) -> dict | None:
    """{items, bonus_items, cashstar_items} pour `pays`, lus dans le script.

    `None` si la structure n'est plus celle qu'on a mesurée — on ne devine
    jamais : une liste inventée afficherait des articles qu'aucune carte ne
    donne.
    """
    for m in MOTIF_GROUPE.finditer(js or ""):
        if pays not in re.findall(r"[\"']([a-z]{2})[\"']", m.group(1)):
            continue
        conf = dict(MOTIF_ENTREE.findall(m.group(2)))
        #  Les variables sont déclarées juste avant la configuration.
        avant = js[max(0, m.start() - 6000): m.start()]
        out = {}
        for cle in CLES:
            valeur = conf.get(cle)
            if valeur is None:
                out[cle] = []
            elif valeur.startswith("["):
                out[cle] = _nombres(valeur)
            else:
                defs = list(re.finditer(
                    r"(?<![\w$.])" + re.escape(valeur) + r"=\[([^\]]*)\]", avant))
                if not defs:
                    return None
                out[cle] = _nombres(defs[-1].group(1))
        if not (out["items"] or out["bonus_items"]):
            return None
        return out
    return None


def ids_de(offre: dict) -> list[int]:
    """Les articles de l'offre, sans doublon, dans l'ordre de la page."""
    vus, out = set(), []
    for cle in ("items", "cashstar_items", "bonus_items"):
        for i in (offre or {}).get(cle) or []:
            if i not in vus:
                vus.add(i)
                out.append(i)
    return out[:MAX_ARTICLES]


def signature(offre: dict) -> str:
    """Ce qui, en changeant, mérite une nouvelle fiche. L'ordre n'y entre pas."""
    return ",".join(str(i) for i in sorted(ids_de(offre)))


def source_de(article: dict, offre: dict) -> str:
    """Quelle carte donne cet article — d'après la page, puis sa description.
    Court : c'est l'étiquette d'une ligne de la fiche, qui regroupe.

    ⚠️ SANS DESCRIPTION (l'économie n'a pas répondu), RIEN N'EST DÉDUIT : un
    article vendu en magasin ET en carte numérique se serait affiché
    « numérique » seul — faux. Il reste « Carte cadeau », qui est vrai.
    """
    aid = article.get("asset_id")
    offre = offre or {}
    texte = " ".join(str(article.get(k) or "") for k in
                     ("description", "description_fr")).lower()
    if aid in (offre.get("bonus_items") or []):
        return "🎟️ **Bonus des cartes achetées sur roblox.com**"
    if "amazon" in texte:
        return "🟠 **Code Amazon**"
    numerique = aid in (offre.get("cashstar_items") or [])
    if "retailer" in texte or "détaillant" in texte:
        return ("🛒 **Carte en magasin" + (" ou numérique**" if numerique else "**"))
    if numerique and aid not in (offre.get("items") or []):
        return "💳 **Carte numérique roblox.com**"
    return "🎁 **Carte cadeau**"


_MOTIF_MOIS_EN = re.compile(r"\bin (" + "|".join(_MOIS) + r")\s+(\d{4})\b", re.I)
_MOTIF_MOIS_FR = re.compile(r"\ben (" + "|".join(_MOIS_FR) + r")\s+(\d{4})\b", re.I)


def mois_annonce(article: dict) -> tuple[int, int] | None:
    """(2026, 10) si la description de Roblox écrit le mois en toutes lettres."""
    m = _MOTIF_MOIS_EN.search(str(article.get("description") or ""))
    if m:
        return int(m.group(2)), list(_MOIS).index(m.group(1).lower()) + 1
    m = _MOTIF_MOIS_FR.search(str(article.get("description_fr") or ""))
    if m:
        return int(m.group(2)), _MOIS_FR.index(m.group(1).lower()) + 1
    return None


def nom_du_mois(annee: int, mois: int) -> str:
    return f"{_MOIS_FR[int(mois) - 1]} {int(annee)}"


def mois_de(articles: list[dict]) -> str | None:
    """« septembre 2026 », lu dans la description de l'article du mois."""
    for a in articles:
        am = mois_annonce(a)
        if am:
            return nom_du_mois(*am)
    return None


def mois_suivant(annee: int, mois: int) -> tuple[int, int]:
    return (annee + 1, 1) if mois == 12 else (annee, mois + 1)


def mois_seul(annee: int, mois: int) -> str:
    """« octobre » — pour la ligne 🔜, sous un titre qui porte déjà l'année."""
    return _MOIS_FR[int(mois) - 1]


#  Ce qui casserait la ligne : un « [ » ferme le lien masqué trop tôt, un « * »
#  ou un « _ » mettrait la suite en gras ou en italique.
_MOTIF_NOM_INTERDIT = re.compile(r"[\[\]<>\\*_~`|]")


def nom_affiche(article: dict, largeur: int = 48) -> str:
    """Le nom montré sur la fiche : le français officiel de Roblox s'il existe,
    sinon l'anglais — un seul, la ligne reste courte."""
    nom = str(article.get("nom_fr") or article.get("nom") or "")
    nom = " ".join(_MOTIF_NOM_INTERDIT.sub("", nom).split())
    if not nom:
        return f"Article {article.get('asset_id')}"
    return nom if len(nom) <= largeur else nom[:largeur - 1].rstrip() + "…"


def groupes(articles, offre) -> list[tuple[str, list[dict]]]:
    """Les articles rangés par carte à acheter, dans l'ordre de la page : UNE
    ligne par carte sur la fiche, pas un bloc par article."""
    out: dict[str, list[dict]] = {}
    for a in articles or []:
        out.setdefault(source_de(a, offre), []).append(a)
    return list(out.items())


def annonces_dans(articles) -> list[dict]:
    """Les articles « carte cadeau » dont Roblox ÉCRIT le mois : les seuls qu'on
    annonce d'avance. Une carte cadeau ET un mois, dans la même description."""
    out = []
    for a in articles or []:
        en = str(a.get("description") or "")
        fr = str(a.get("description_fr") or "")
        if "gift card" not in en.lower() and "carte cadeau" not in fr.lower():
            continue
        am = mois_annonce(a)
        if am and int(a.get("asset_id") or 0) > 0:
            out.append({"asset_id": int(a["asset_id"]), "annee": am[0],
                        "mois": am[1], "nom": str(a.get("nom") or "")[:120],
                        "description": en[:400]})
    return out


async def noter_annonces(articles) -> int:
    """Mémorise les annonces trouvées dans ce que le relevé vient de lire —
    sans une requête. Rend combien. Ne lève jamais."""
    trouves = annonces_dans(articles)
    if not trouves:
        return 0
    try:
        maint = veille.datetime.now(veille.timezone.utc).isoformat()
        async with veille._get_db() as db:
            for a in trouves:
                await db.execute(
                    "INSERT INTO roblox_cartes_annonces(asset_id, annee, mois, nom,"
                    " description, vu_le) VALUES(?,?,?,?,?,?) ON CONFLICT(asset_id)"
                    " DO UPDATE SET annee=?, mois=?, nom=?, description=?, vu_le=?",
                    (a["asset_id"], a["annee"], a["mois"], a["nom"], a["description"],
                     maint, a["annee"], a["mois"], a["nom"], a["description"], maint))
            await db.commit()
    except Exception as ex:
        veille._log(f"[roblox_cartes noter_annonces] {ex}")
        return 0
    return len(trouves)


async def annonces_du_mois(annee: int, mois: int) -> list[dict]:
    """Les articles annoncés pour ce mois-là, tels que mémorisés."""
    try:
        async with veille._get_db() as db:
            async with db.execute(
                "SELECT asset_id, nom, description FROM roblox_cartes_annonces"
                " WHERE annee=? AND mois=? ORDER BY asset_id",
                (int(annee), int(mois))) as cur:
                return [{"asset_id": int(r[0]), "nom": r[1] or "",
                         "description": r[2] or "", "item_type": "Asset"}
                        for r in await cur.fetchall()]
    except Exception as ex:
        veille._log(f"[roblox_cartes annonces_du_mois] {ex}")
        return []


async def mois_de_l_offre(offre: dict) -> tuple[int, int] | None:
    """Le mois de l'offre en cours, d'après les annonces mémorisées — sans
    requête. `None` si aucun de ses articles n'écrit son mois. Page déjà passée
    au mois suivant (articles des deux mois) : le plus récent gagne.

    La table compte une ligne par article annoncé — une par mois : on la lit
    en entier plutôt que d'assembler une clause `IN (?, ?, …)`. Une requête
    SQL fabriquée par concaténation, même de `?`, est ce que l'audit SQL du
    dépôt signale ; aucune raison de lui en donner une de plus."""
    ids = set(ids_de(offre))
    if not ids:
        return None
    try:
        async with veille._get_db() as db:
            async with db.execute(
                    "SELECT asset_id, annee, mois FROM roblox_cartes_annonces") as cur:
                lignes = await cur.fetchall()
    except Exception as ex:
        veille._log(f"[roblox_cartes mois_de_l_offre] {ex}")
        return None
    mois = [(int(a), int(m)) for aid, a, m in lignes if int(aid) in ids]
    return max(mois) if mois else None


async def lire_offre(etat: dict) -> dict:
    """La page, puis le script s'il a changé. Rend {"offre", "code", "motif",
    "script_relu"}. `etat` garde le dernier script lu et son offre : tant que
    l'empreinte ne bouge pas, on ne retélécharge rien."""
    out = {"offre": None, "code": None, "motif": None, "script_relu": False}
    try:
        async with veille._ouvrir() as sess:
            async with sess.get(PAGE, headers={"Accept": "text/html"}) as r:
                out["code"] = r.status
                if r.status != 200:
                    out["motif"] = f"HTTP {r.status}"
                    return out
                page = await r.text()
            m = MOTIF_SCRIPT.search(page or "")
            if not m:
                out["motif"] = "script introuvable dans la page"
                return out
            if m.group(0) == etat.get("script") and etat.get("offre"):
                out["offre"] = etat["offre"]
                return out
            async with sess.get(m.group(0), headers={"Accept": "*/*"}) as r:
                if r.status != 200:
                    out["code"] = r.status
                    out["motif"] = f"script HTTP {r.status}"
                    return out
                js = await r.text()
            out["script_relu"] = True
            offre = offre_du_script(js)
            if offre is None:
                out["motif"] = "liste introuvable dans le script (format changé)"
                return out
            etat["script"], etat["offre"] = m.group(0), offre
            out["offre"] = offre
    except Exception as ex:
        out["motif"] = f"{type(ex).__name__}: {ex}"
    return out


async def _economie(sess, aid: int, langue: str | None = None) -> dict | None:
    entetes = {"Accept-Language": langue} if langue else None
    async with sess.get(veille.API_ECONOMIE_DETAILS.format(int(aid)),
                        headers=entetes) as r:
        if r.status != 200:
            return None
        d = await r.json(content_type=None)
    return d if isinstance(d, dict) else None


async def fiches(offre: dict, en_plus=()) -> list[dict]:
    """Les articles de l'offre, puis ceux de `en_plus` (les annonces du mois
    suivant, telles que mémorisées) : nom et description en anglais PUIS en
    français, tous deux de Roblox.

    ⚠️ PAR L'ÉCONOMIE, PAS PAR LA REQUÊTE GROUPÉE DES FICHES. Mesuré le 29/09 :
    `economy/v2/assets/{id}/details` rend le français officiel avec l'en-tête
    `Accept-Language: fr-fr`, et son quota tient sur l'IP de Railway (2/s),
    quand la requête groupée y est à 1 par minute, déjà prise par l'éclaireur.
    Deux requêtes par article ; un article sans réponse garde ce qu'on
    savait de lui (le nom relevé pour une annonce, sinon son identifiant), et
    `nom_lu` dit si Roblox a rendu un nom — sans lui, l'appelant réessaie
    plutôt que d'afficher un identifiant.

    ⚠️ UNE REQUÊTE PAR SECONDE AU PLUS (`PAUSE_ECONOMIE_MIN × 4`). L'éclaireur
    date ses articles sur ce même point d'API : douze appels en douze
    secondes, une ou deux fois par mois, ne lui prennent rien.
    """
    articles = []
    connus = {}
    for p in en_plus or ():
        try:
            connus[int(p["asset_id"])] = p
        except (KeyError, TypeError, ValueError):
            continue
    ids = ids_de(offre)
    ids = ids + [i for i in connus if i not in ids]
    try:
        async with veille._ouvrir() as sess:
            for i, aid in enumerate(ids):
                if i:
                    await asyncio.sleep(veille.PAUSE_ECONOMIE_MIN * 4)
                en = await _economie(sess, aid)
                await asyncio.sleep(veille.PAUSE_ECONOMIE_MIN * 4)
                fr = await _economie(sess, aid, "fr-fr")
                base = connus.get(aid) or {}
                a = {"asset_id": aid, "item_type": "Asset",
                     "nom": str((en or {}).get("Name") or base.get("nom")
                                or f"Article {aid}")[:120],
                     "description": str((en or {}).get("Description")
                                        or base.get("description") or "")[:400],
                     "nom_lu": bool((en or {}).get("Name") or (fr or {}).get("Name")
                                    or base.get("nom"))}
                if fr and fr.get("Name") and fr.get("Name") != a["nom"]:
                    a["nom_fr"] = str(fr["Name"])[:120]
                if fr and fr.get("Description") and fr.get("Description") != a["description"]:
                    a["description_fr"] = str(fr["Description"])[:400]
                articles.append(a)
    except Exception as ex:
        veille._log(f"[roblox_cartes fiches] {type(ex).__name__}: {ex}")
    return articles


def signature_suite(prochains) -> str:
    """Ce qui, en changeant, fait MODIFIER la fiche déjà publiée (sans en
    poster une) : sa présentation (`VERSION_FICHE`) et le mois suivant. La
    fiche du 29/09 au matin n'a pas de suite notée (« ») : la première lecture
    après ce changement la remet au format court, sur place."""
    return f"v{VERSION_FICHE}:" + ",".join(str(i) for i in sorted(
        int(p["asset_id"]) for p in prochains or []))


async def etat_affiche(guild_id: int) -> dict:
    """Ce que ce serveur montre déjà : la liste, la suite, le message."""
    c = await veille.config(guild_id)
    try:
        message = int(c.get("roblox_cartes_message") or 0)
    except (TypeError, ValueError):
        message = 0
    return {"signature": c.get("roblox_cartes_signature") or "",
            "suite": c.get("roblox_cartes_suite") or "", "message": message}


async def deja_affichee(guild_id: int, sig: str) -> bool:
    return (await etat_affiche(guild_id))["signature"] == sig


async def noter_affichee(guild_id: int, sig: str, suite: str | None = None,
                         message_id: int | None = None) -> None:
    """Note ce que ce serveur montre. `message_id` 0 EFFACE l'identifiant
    noté : une fiche neuve partie sans identifiant connu ne doit pas laisser
    croire que celle du mois d'avant est la bonne à modifier."""
    await veille._db_set(guild_id, "roblox_cartes_signature", sig)
    if suite is not None:
        await veille._db_set(guild_id, "roblox_cartes_suite", suite)
    if message_id is not None:
        await veille._db_set(guild_id, "roblox_cartes_message", int(message_id or 0))
