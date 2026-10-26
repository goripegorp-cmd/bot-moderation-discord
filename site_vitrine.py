"""site_vitrine.py — la VITRINE PUBLIQUE de l'équipage (27/10/2026) : `/equipage`.

Le fondateur : « mettre dans le site un endroit où on peut copier le lien […] le lien officiel de l'équipage […] Les
autres qui souhaiteront cliquer dessus ils pourront aussi voir […] c'est un peu l'affiche même de ce à quoi notre
équipage ressemble. Il faut que ce soit vraiment beau. Et bien fait. »

UNE PAGE SANS SESSION, SUR INTERNET : elle ne montre que ce que la direction a rendu public.
  · Les blocs de l'accueil marqués « publics » (réglage par bloc ; au départ, le bandeau et le code de l'équipage) et
    visibles. Une actualité : celles de la direction seulement (jamais les automatiques, qui citent des noms Discord).
    Les annonces et événements : leurs mentions deviennent « @membre ».
  · Le mur des affiches « visibles sur la vitrine » (réglage par affiche, oui par défaut), en champs publics SEULEMENT :
    pseudo Roblox, surnom, prime, niveau, grade, statut, insignes, portrait Roblox. Jamais le nom ni l'avatar Discord,
    aucun identifiant (une affiche, une image : des jetons opaques signés), aucune note.
  · Les analyses : seulement les parties d'un bloc « Analyses » public, calculées sur les affiches de la vitrine.

LES ADRESSES (`health_server` les branche ; RIEN d'autre, aucune écriture) :
  GET /equipage                → la page (balises Open Graph : l'aperçu du lien collé dans Discord)
  GET /equipage/donnees        → ce que la page montre (JSON)
  GET /equipage/banniere.png   → l'image de l'aperçu (1200 × 630), dessinée ici avec les textures et polices du site
  GET /equipage/image/<jeton>  → une image citée par les données (portrait, insigne, image d'un bloc public)

LES DÉFENSES : réponses gardées côté serveur (`FRAIS`, renouvelées aussitôt après une écriture de la direction :
`site_equipage.generation`), cadence par adresse IP (la PREMIÈRE de X-Forwarded-For : `tableau._ip`), `X-Robots-Tag:
noindex` (partageable, jamais référencé), CSP stricte (aucune image d'ailleurs : ni Discord, ni Roblox en direct),
aucun cookie lu ni posé — une session ouverte ne change RIEN à ce que la vitrine montre.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import io
import json
import re
import time
from collections import OrderedDict

import affiches
import diag
import site_equipage
import tableau

ADRESSE = site_equipage.ADRESSE_VITRINE          # « /equipage »
FRAIS = 60.0                     # s : une réponse publique gardée (une écriture de la direction la renouvelle aussitôt)
BANNIERE_PAUSE = 30.0            # s : au plus une bannière redessinée par demi-minute (la précédente sert entre-temps)
LIMITES = {"page": 120, "donnees": 120, "image": 1500, "banniere": 60}   # requêtes par minute et par adresse IP
PASSAGES_MAX = 20000             # adresses suivies (les plus anciennes partent d'abord)
LARGEUR, HAUTEUR = 1200, 630     # l'image de l'aperçu (Open Graph)
AFFICHES_BANNIERE = 3
FORMAT_JETON = re.compile(r"[A-Za-z0-9_-]{22}")
FORMAT_STATIQUE = re.compile(r"s/(?:icones|logos)/[a-z0-9_-]{1,64}(?:/[a-z0-9_-]{1,64}){0,3}\.(?:webp|png|svg)")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; manifest-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
CSP_IMAGE = "default-src 'none'; sandbox"
ENTETES = {
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}
#  Les textes que la page lit (en plus des noms d'affiche renommés).
CLES_PAGE = tuple(site_equipage.PAGE)

_cache: dict = {}                # serveur → l'entrée publique (données, jetons des images, aperçu)
_bannieres: dict = {}            # serveur → (signature, octets, heure)
_passages: OrderedDict = OrderedDict()   # (adresse, genre) → (début de la minute, nombre)
_verrous: dict = {}              # serveur → (boucle, verrou) : un seul calcul à la fois
_choix = {"t": 0.0, "id": 0}     # le serveur de la vitrine (gardé 5 minutes)
_dernier_avis = {"cadence": 0.0, "police": 0.0}


def _signaler(code: str, message: str, ex=None, detail: str = "") -> None:
    """Un message STABLE (le tableau des erreurs ne sature pas), le détail sur une ligne à part."""
    log = getattr(site_equipage, "_log", print) or print
    log(f"[VITRINE][{code}] {message}")
    log(f"[VITRINE][{code}:DETAIL] {detail} {type(ex).__name__ + ' ' + str(ex) if ex is not None else ''}".rstrip())
    if ex is not None:
        diag.compter("vitrine", code, ex)


def pret() -> bool:
    return site_equipage.pret() and tableau._bot is not None and bool(tableau._cle)


def oublier(guild_id: int | None = None) -> None:
    """Les réponses gardées (un test, un changement de réglages) : recalculées à la prochaine visite."""
    if guild_id is None:
        _cache.clear()
        _bannieres.clear()
        _choix.update(t=0.0, id=0)
    else:
        _cache.pop(int(guild_id), None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Le serveur, les jetons, la cadence
# ═══════════════════════════════════════════════════════════════════════════════

async def _guilde():
    """Le serveur dont la vitrine montre l'équipage : celui qui a un rôle du clan réglé (le plus grand s'il y en a
    plusieurs). Gardé 5 minutes."""
    bot = tableau._bot
    t = time.monotonic()
    if _choix["id"] and t - _choix["t"] < 300:
        g = bot.get_guild(_choix["id"]) if bot is not None else None
        if g is not None:
            return g
    candidats = []
    for g in list(getattr(bot, "guilds", None) or []):
        if await site_equipage._role_clan(g) is not None:
            candidats.append(g)
    if not candidats:
        return None
    g = max(candidats, key=lambda x: (int(getattr(x, "member_count", 0) or 0), -int(getattr(x, "id", 0) or 0)))
    _choix.update(t=t, id=g.id)
    return g


def _jeton(genre: str, valeur: str) -> str:
    """Un nom opaque et stable (signé par la clé du site) : une affiche, une image — jamais leur identifiant."""
    cle = tableau._cle if isinstance(tableau._cle, (bytes, bytearray)) else str(tableau._cle or "").encode("utf-8")
    brut = hmac.new(bytes(cle), f"vitrine\x1f{genre}\x1f{valeur}".encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(brut).decode("ascii").rstrip("=")[:22]


def _trop(request, genre: str) -> bool:
    """Cadence par adresse IP (la première de X-Forwarded-For) : `LIMITES[genre]` par minute."""
    t = time.monotonic()
    cle = (tableau._ip(request), genre)
    debut, n = _passages.pop(cle, (t, 0))
    if t - debut >= 60:
        debut, n = t, 0
    n += 1
    _passages[cle] = (debut, n)
    while len(_passages) > PASSAGES_MAX:
        _passages.popitem(last=False)
    if n > LIMITES[genre]:
        if t - _dernier_avis["cadence"] > 60:
            _dernier_avis["cadence"] = t
            _signaler("E2", "cadence dépassée sur la vitrine", detail=f"genre={genre}")
        return True
    return False


def _verrou(guild_id: int) -> asyncio.Lock:
    boucle = asyncio.get_running_loop()
    deja = _verrous.get(guild_id)
    if deja is None or deja[0] is not boucle:
        deja = _verrous[guild_id] = (boucle, asyncio.Lock())
    return deja[1]


# ═══════════════════════════════════════════════════════════════════════════════
#  Ce que la vitrine montre (et rien d'autre)
# ═══════════════════════════════════════════════════════════════════════════════

def _propre(texte, maximum: int = 600) -> str:
    """Un texte public : mentions en « @membre » / « #salon », sans mise en forme Discord, borné."""
    return site_equipage.texte_discord(texte, None, maximum)


def _nom_public(a: dict) -> str:
    """Le nom d'une affiche sur la vitrine : le pseudo Roblox, sinon le surnom — JAMAIS le nom Discord."""
    return site_equipage.sans_emoji(a["roblox_nom"])[:40] or site_equipage.sans_emoji(a["surnom"])[:40] or "Matelot"


async def _construire(g) -> dict:
    """{donnees (envoyées), images (jeton → image du site), apercu (balises et bannière)}."""
    t = time.time()
    await site_equipage._assurer_depart(g)
    types, elements = await affiches._catalogue()
    masquees = await site_equipage.vitrine_masquees(g.id)
    lignes = [a for a in await site_equipage._affiches_actives(g) if a["id"] not in masquees]
    lignes.sort(key=lambda a: (_nom_public(a).casefold(), _jeton("affiche", a["id"])))
    images: dict = {}

    def image(chemin) -> str:
        chemin = str(chemin or "")
        if not chemin or tableau._chemin_media(chemin)[0] is None:
            return ""
        j = _jeton("image", chemin)
        images[j] = chemin
        return f"{ADRESSE}/image/{j}"

    def icone(brute) -> str:
        s = affiches._icone_servie(brute or "")
        m = affiches.FORMAT_ICONE_MEDIA.fullmatch(s)
        if m:
            return image(m.group(1))
        return s if FORMAT_STATIQUE.fullmatch(s) else ""

    ids = {a["id"]: _jeton("affiche", a["id"])[:12] for a in lignes}
    mur, portraits = [], {}
    for a in lignes:
        attributs = {ty: [k for k in (cles or []) if (ty, k) in elements] for ty, cles in (a["attributs"] or {}).items()}
        avatar = image(f"avatar/{int(a['roblox_id'])}") if a["roblox_id"] else ""
        if avatar:
            portraits[a["id"]] = tableau._chemin_media(f"avatar/{int(a['roblox_id'])}")[0]
        mur.append({"id": ids[a["id"]], "roblox": {"nom": site_equipage.sans_emoji(a["roblox_nom"])[:40], "avatar": avatar},
                    "surnom": site_equipage.sans_emoji(a["surnom"])[:60], "prime": int(a["prime"] or 0),
                    "niveau": int(a["niveau"] or 0), "grade": str(a["grade"] or "")[:64],
                    "statut": str(a["statut"] or "actif")[:20], "attributs": {ty: ks for ty, ks in attributs.items() if ks}})
    cites = {(ty, k) for x in mur for ty, ks in x["attributs"].items() for k in ks}
    grade_t = site_equipage._type_par(types, "grade", r"\bgrades?\b")
    if grade_t:
        cites |= {(grade_t, x["grade"]) for x in mur if x["grade"]}
    catalogue = {
        "types": [{"cle": ty["cle"], "nom": ty["nom"], "ordre": int(ty["ordre"]), "multiple": bool(ty["multiple"]),
                   "champ": ty["champ"]} for ty in sorted(types.values(), key=lambda x: (x["ordre"], x["nom"].casefold()))],
        "elements": [{"type": e["type"], "cle": e["cle"], "nom": e["nom"], "icone": icone(e["icone"]),
                      "actif": bool(e["actif"]), "ordre": int(e["ordre"])}
                     for (ty, k), e in sorted(elements.items(), key=lambda x: (x[1]["ordre"], x[1]["nom"].casefold()))
                     if (ty, k) in cites]}

    #  Les blocs PUBLICS et visibles, dans l'ordre de l'accueil, sous des noms neutres (b1, b2…).
    blocs = [b for b in await site_equipage._blocs(g.id) if b["visible"] and b["public"]]
    types_vus = {b["type"] for b in blocs}
    sorties, donnees_blocs = [], {}
    publications = await site_equipage._publications(g, t, public=True) if types_vus & {"evenements", "analyses"} else []
    for n, b in enumerate(blocs, start=1):
        c = dict(b["contenu"])
        for champ, maximum in (("titre", 80), ("sous_titre", 200), ("legende", 200), ("texte", 2500)):
            if isinstance(c.get(champ), str):
                c[champ] = _propre(c[champ], maximum)
        if "image" in c:
            c["image"] = image(c.get("image"))
        if b["type"] == "actualites":
            c["automatiques"] = False      # les actualités automatiques citent des noms Discord : jamais ici
        if b["type"] == "honneur":
            choisies = [ids[x] for x in c.get("affiches") or [] if x in ids]
            auto = [ids[a["id"]] for a in sorted((a for a in lignes if int(a["prime"] or 0) > 0),
                                                 key=lambda a: (-int(a["prime"]), _nom_public(a).casefold()))[:3]]
            c["affiches"] = choisies
            donnees_blocs.setdefault("honneur", {})[f"b{n}"] = choisies or auto
        sorties.append({"id": f"b{n}", "type": b["type"], "contenu": c})
    if "actualites" in types_vus:
        actus = await site_equipage._actualites_direction(g.id)
        donnees_blocs["actualites"] = {"direction": [
            {"id": f"a{k}", "genre": "direction", "titre": _propre(a["titre"], 100), "texte": _propre(a["texte"], 2000),
             "image": image(a["image"]), "epingle": bool(a["epingle"]), "quand": int(a["cree_le"])}
            for k, a in enumerate(actus, start=1)], "auto": []}
    if "evenements" in types_vus:
        a_venir = sorted((p for p in publications if p["type"] == "evenement" and p["statut"] == "publie"
                          and p["phase"] in ("a_venir", "en_cours")), key=lambda p: p["quand"] or 0)
        donnees_blocs["evenements"] = [
            {"id": f"e{k}", "titre": _propre(p["titre"], 120), "texte": p["texte"], "quand": p["quand"], "fin": p["fin"],
             "lieu": _propre(p["lieu"], 100), "duree_min": p["duree_min"], "places": p["places"], "phase": p["phase"],
             "reponses": p["reponses"], "image": image(p["image"])}
            for k, p in enumerate(a_venir[:site_equipage.EVENEMENTS_LUS], start=1)]
    if "analyses" in types_vus:
        parties = {p for b in blocs if b["type"] == "analyses"
                   for p in (b["contenu"].get("parties") or site_equipage.PARTIES_ANALYSES)}
        brut = await site_equipage.analyses(g, t, lignes, publications, await site_equipage._recrues(g))
        for cle in ("metiers", "races", "factions"):
            brut[cle] = [dict(r, icone=icone_servie_publique(r.get("icone"), image)) for r in brut[cle]]
        top = sorted((a for a in lignes if int(a["prime"] or 0) > 0),
                     key=lambda a: (-int(a["prime"]), _nom_public(a).casefold()))[:5]
        brut["primes"]["top"] = [{"affiche": ids[a["id"]], "nom": _nom_public(a), "prime": int(a["prime"])} for a in top]
        if brut["evenements"].get("prochain"):
            brut["evenements"]["prochain"]["titre"] = _propre(brut["evenements"]["prochain"]["titre"], 120)
        donnees_blocs["analyses"] = {k: v for k, v in brut.items() if k in parties}

    #  Les équipes : chacune par les affiches déjà montrées ici (le chef, puis ses membres par la hiérarchie existante) —
    #  aucune donnée de plus que le mur ; une équipe sans affiche montrée n'y paraît pas.
    equipes = []
    for e in (await site_equipage.equipes_lues(g, lignes, publiques=ids))["equipes"]:
        te = e["type"]
        equipes.append(dict(e, nom=_propre(e["nom"], 60), type=None if te is None else {
            "genre": te["genre"], "nom": _propre(te["nom"], 60), "icone": icone_servie_publique(te.get("icone"), image)}))

    role = await site_equipage._role_clan(g)
    clan = site_equipage.sans_emoji(getattr(role, "name", "")) if role is not None else ""
    serveur = site_equipage.sans_emoji(getattr(g, "name", ""))
    libelles = site_equipage.libelles_page(g)
    donnees = {
        "serveur": {"nom": serveur}, "clan": clan,
        "textes": {cle: site_equipage._t(g, cle) for cle in CLES_PAGE}, "libelles": libelles,
        "affiches": mur, "catalogue": catalogue, "accueil": {"blocs": sorties, "donnees": donnees_blocs}, "equipes": equipes,
        "maintenant": int(t), "version": tableau.version_page(),
    }

    #  L'aperçu du lien (Discord, autres messageries) : le titre, la phrase, et ce que la bannière dessine.
    titre = site_equipage._t(g, f"{site_equipage.GROUPE}.titre")
    nom_clan = f"Clan {clan}" if clan else serveur
    primes = sum(int(a["prime"] or 0) for a in lignes)
    bandeau = next((b for b in sorties if b["type"] == "bandeau"), None)
    noms_grades = {e["cle"]: e["nom"] for e in catalogue["elements"] if grade_t and e["type"] == grade_t}
    top3 = sorted(lignes, key=lambda a: (-int(a["prime"] or 0), _nom_public(a).casefold()))[:AFFICHES_BANNIERE]
    apercu = {
        "titre": site_equipage._t(g, f"{site_equipage.GROUPE}.vitrine.og.titre", titre=titre, clan=nom_clan),
        "description": site_equipage._t(g, f"{site_equipage.GROUPE}.vitrine.og.description", pirates=len(lignes)),
        "site": titre,
        "banniere": {
            "titre": titre, "haut": " · ".join(x for x in (nom_clan, serveur if clan else "") if x),
            "ligne": site_equipage._t(g, f"{site_equipage.GROUPE}.vitrine.banniere", pirates=len(lignes),
                                      primes=_nombre(primes)),
            "phrase": (bandeau["contenu"].get("sous_titre") if bandeau else "") or
                      site_equipage._t(g, f"{site_equipage.GROUPE}.vitrine.phrase"),
            "mention": clan or titre,
            "affiches": [{"nom": _nom_public(a), "surnom": site_equipage.sans_emoji(a["surnom"])[:40],
                          "prime": int(a["prime"] or 0),
                          "grade": noms_grades.get(a["grade"], site_equipage.sans_emoji(a["grade"]).capitalize())[:24],
                          "portrait": str(portraits.get(a["id"]) or "")} for a in top3],
        },
    }
    apercu["signature"] = hashlib.sha256(json.dumps(apercu["banniere"], sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {"donnees": donnees, "images": images, "apercu": apercu}


def icone_servie_publique(s, image) -> str:
    """Une icône d'une analyse (« media/… » ou « s/icones/… ») telle que la vitrine la sert."""
    s = str(s or "")
    m = affiches.FORMAT_ICONE_MEDIA.fullmatch(s)
    if m:
        return image(m.group(1))
    return s if FORMAT_STATIQUE.fullmatch(s) else ""


def _nombre(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


async def _entree(g) -> dict:
    """L'entrée publique de ce serveur : gardée `FRAIS` secondes, renouvelée après une écriture de la direction."""
    gen = site_equipage.generation(g.id)
    e = _cache.get(g.id)
    if e is not None and e["gen"] == gen and time.monotonic() - e["t"] < FRAIS:
        return e
    async with _verrou(g.id):
        e = _cache.get(g.id)
        if e is not None and e["gen"] == gen and time.monotonic() - e["t"] < FRAIS:
            return e
        x = await _construire(g)
        corps = json.dumps(x["donnees"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        e = {"t": time.monotonic(), "gen": gen, "corps": corps,
             "etag": '"' + hashlib.sha256(corps).hexdigest()[:24] + '"', "images": x["images"], "apercu": x["apercu"],
             "pages": {}}
        _cache[g.id] = e
        return e


# ═══════════════════════════════════════════════════════════════════════════════
#  Les adresses (`health_server`)
# ═══════════════════════════════════════════════════════════════════════════════

def _reponse(status: int, texte: str, **entetes):
    from aiohttp import web
    return web.Response(status=status, text=texte, content_type="text/plain",
                        headers=dict(ENTETES, **{"Content-Security-Policy": CSP_IMAGE, "Cache-Control": "no-store"},
                                     **entetes))


def _refus_cadence():
    return _reponse(429, "Trop de demandes : réessaie dans une minute.", **{"Retry-After": "60"})


def _origine(request) -> str:
    """L'adresse publique du site (réglée au démarrage), sinon celle de la requête."""
    if tableau._base:
        return str(tableau._base).rstrip("/")
    proto = (request.headers.get("X-Forwarded-Proto", "") or request.scheme or "https").split(",")[0].strip()
    return f"{proto if proto in ('http', 'https') else 'https'}://{request.host}"


async def _ouvrir(request, genre: str):
    """(serveur, entrée) — ou la réponse de refus (cadence, vitrine fermée)."""
    if _trop(request, genre):
        return None, _refus_cadence()
    if not pret():
        return None, _reponse(503, "La vitrine de l'équipage n'est pas ouverte pour le moment.")
    g = await _guilde()
    if g is None:
        return None, _reponse(503, "La vitrine de l'équipage n'est pas ouverte pour le moment.")
    return (g, await _entree(g)), None


async def vers_vitrine(request):
    """`/equipage/` : la vitrine est à `/equipage` (une seule adresse à partager)."""
    from aiohttp import web
    raise web.HTTPMovedPermanently(ADRESSE, headers=ENTETES)


async def page(request):
    """`GET /equipage` : la page publique, ses balises Open Graph remplies (titre, phrase, image, adresse)."""
    from aiohttp import web
    try:
        ouvert, refus = await _ouvrir(request, "page")
        if refus is not None:
            return refus
        _g, e = ouvert
        base = _origine(request)
        texte = e["pages"].get(base)
        if texte is None:
            modele = tableau._lire_page_site("vitrine.html")
            if modele is None:
                return _reponse(404, "Introuvable.")
            ap = e["apercu"]
            valeurs = {"OG_TITRE": ap["titre"], "OG_DESCRIPTION": ap["description"], "OG_SITE": ap["site"],
                       "OG_URL": base + ADRESSE, "OG_IMAGE": f"{base}{ADRESSE}/banniere.png?v={ap['signature']}",
                       "OG_ALT": ap["banniere"]["titre"] + " · " + ap["banniere"]["haut"],
                       "TITRE": ap["banniere"]["titre"], "SOUS_TITRE": ap["banniere"]["haut"]}
            texte = re.sub(r"\{\{([A-Z_]{2,20})\}\}", lambda m: html.escape(str(valeurs.get(m.group(1), "")), quote=True),
                           modele)
            e["pages"] = {base: texte}
        etag = '"' + hashlib.sha256(texte.encode("utf-8")).hexdigest()[:24] + '"'
        entetes = dict(ENTETES, **{"Content-Security-Policy": CSP, "Cache-Control": "no-cache", "ETag": etag})
        if etag in request.headers.get("If-None-Match", ""):
            return web.Response(status=304, headers=entetes)
        r = web.Response(text=texte, content_type="text/html", headers=entetes)
        r.enable_compression()
        return r
    except Exception as ex:   # une adresse PUBLIQUE : rien du détail ne sort, il part au journal
        _signaler("E1", "page de la vitrine en échec", ex)
        return _reponse(500, "La vitrine est indisponible pour le moment.")


async def donnees(request):
    """`GET /equipage/donnees` : ce que la page montre (JSON). Revalidé à chaque visite (ETag) : une affiche retirée
    par la direction disparaît au rechargement."""
    from aiohttp import web
    try:
        ouvert, refus = await _ouvrir(request, "donnees")
        if refus is not None:
            return refus
        _g, e = ouvert
        entetes = dict(ENTETES, **{"Content-Security-Policy": CSP_IMAGE, "Cache-Control": "no-cache", "ETag": e["etag"]})
        if e["etag"] in request.headers.get("If-None-Match", ""):
            return web.Response(status=304, headers=entetes)
        r = web.Response(body=e["corps"], content_type="application/json", charset="utf-8", headers=entetes)
        r.enable_compression()
        return r
    except Exception as ex:
        _signaler("E3", "données de la vitrine en échec", ex)
        return _reponse(500, "La vitrine est indisponible pour le moment.")


async def image(request):
    """`GET /equipage/image/<jeton>` : une image que les données publiques citent — aucune autre (404)."""
    from aiohttp import web
    try:
        jeton = str(request.match_info.get("jeton", ""))
        if not FORMAT_JETON.fullmatch(jeton):
            return _reponse(404, "Introuvable.")
        ouvert, refus = await _ouvrir(request, "image")
        if refus is not None:
            return refus
        _g, e = ouvert
        chemin = e["images"].get(jeton)
        p, typ = tableau._chemin_media(chemin) if chemin else (None, None)
        if p is None:
            return _reponse(404, "Introuvable.")
        etag = f'"{jeton}"'
        entetes = dict(ENTETES, **{"Content-Security-Policy": CSP_IMAGE, "Cache-Control": "public, max-age=3600",
                                   "ETag": etag, "Content-Type": typ, "Content-Disposition": "inline"})
        if etag in request.headers.get("If-None-Match", ""):
            return web.Response(status=304, headers=entetes)
        return web.Response(body=await asyncio.to_thread(p.read_bytes), headers=entetes)
    except OSError:
        return _reponse(404, "Introuvable.")
    except Exception as ex:
        _signaler("E4", "image de la vitrine en échec", ex)
        return _reponse(500, "Indisponible.")


async def banniere(request):
    """`GET /equipage/banniere.png` : l'image de l'aperçu du lien (1200 × 630). Redessinée quand ce qu'elle montre
    change (au plus une fois par `BANNIERE_PAUSE`) ; servie à tous (les messageries la chargent de leurs serveurs)."""
    from aiohttp import web
    try:
        ouvert, refus = await _ouvrir(request, "banniere")
        if refus is not None:
            return refus
        g, e = ouvert
        sig = e["apercu"]["signature"]
        deja = _bannieres.get(g.id)
        if deja is None or (deja[0] != sig and time.monotonic() - deja[2] >= BANNIERE_PAUSE):
            octets = await asyncio.to_thread(dessiner_banniere, e["apercu"]["banniere"])
            deja = _bannieres[g.id] = (sig, octets, time.monotonic())
        etag = f'"{deja[0]}"'
        entetes = dict(ENTETES, **{"Content-Security-Policy": CSP_IMAGE, "Cache-Control": "public, max-age=600",
                                   "ETag": etag, "Content-Type": "image/png", "Content-Disposition": "inline",
                                   "Cross-Origin-Resource-Policy": "cross-origin"})
        if etag in request.headers.get("If-None-Match", ""):
            return web.Response(status=304, headers=entetes)
        return web.Response(body=deja[1], headers=entetes)
    except Exception as ex:
        _signaler("E5", "bannière de la vitrine en échec", ex)
        return _reponse(500, "Indisponible.")


# ═══════════════════════════════════════════════════════════════════════════════
#  La bannière (Pillow) : une carte marine dans un cadre de bois, le nom de l'équipage, trois avis de recherche
# ═══════════════════════════════════════════════════════════════════════════════

ENCRE = (43, 29, 18)
SIENNE = (122, 75, 42)
LAITON = (168, 130, 63)
POLICES = {"titre": "pirata-one-latin.woff2", "affiche": "rye-latin.woff2", "texte": "alegreya-latin.woff2",
           "italique": "alegreya-italique-latin.woff2", "capitales": "alegreya-sc-700-latin.woff2"}
_polices: dict = {}
_textures: dict = {}


def _police(nom: str, taille: int):
    from PIL import ImageFont
    cle = (nom, int(taille))
    f = _polices.get(cle)
    if f is None:
        try:
            f = ImageFont.truetype(str(tableau.SITE / "polices" / POLICES[nom]), int(taille))
        except OSError as ex:   # FreeType sans WOFF2 : la police par défaut, dite au journal (une fois par heure)
            if time.monotonic() - _dernier_avis["police"] > 3600:
                _dernier_avis["police"] = time.monotonic()
                _signaler("E6", "polices de la bannière illisibles", ex, detail=nom)
            try:
                f = ImageFont.load_default(int(taille))   # Pillow ≥ 10.1 : une vraie police, à la taille voulue
            except TypeError:
                f = ImageFont.load_default()
        _polices[cle] = f
    return f


def _texture(nom: str):
    from PIL import Image
    im = _textures.get(nom)
    if im is None:
        with Image.open(tableau.SITE / "textures" / f"{nom}.webp") as brut:
            im = _textures[nom] = brut.convert("RGBA")
    return im


def _couvrir(im, taille):
    """`im` recadrée pour couvrir `taille` (comme object-fit: cover)."""
    from PIL import Image
    l, h = taille
    k = max(l / im.width, h / im.height)
    r = im.resize((max(l, round(im.width * k)), max(h, round(im.height * k))), Image.Resampling.LANCZOS)
    x, y = (r.width - l) // 2, (r.height - h) // 2
    return r.crop((x, y, x + l, y + h))


def _ajuster(d, texte: str, nom: str, taille: int, largeur: float, minimum: int = 9):
    """(police, texte) : la plus grande taille ≤ `taille` où `texte` tient dans `largeur` ; sinon raccourci « … »."""
    t = int(taille)
    while t > minimum and d.textlength(texte, font=_police(nom, t)) > largeur:
        t = max(minimum, int(t * 0.92))
    f = _police(nom, t)
    while len(texte) > 1 and d.textlength(texte, font=f) > largeur:
        texte = texte[:-2].rstrip() + "…"
    return f, texte


def _espace(d, centre, texte: str, f, couleur, espace: float) -> None:
    """Un texte centré en `centre`, lettres espacées de `espace` pixels (Pillow n'espace pas les lettres)."""
    largeurs = [d.textlength(ch, font=f) for ch in texte]
    total = sum(largeurs) + espace * (len(texte) - 1)
    x = centre[0] - total / 2
    for ch, l in zip(texte, largeurs):
        d.text((x, centre[1]), ch, font=f, fill=couleur, anchor="lm")
        x += l + espace


def _berry(d, x: float, y: float, taille: int, couleur) -> float:
    """Le ฿ dessiné (aucune police du site n'a ce signe) : un B barré, posé à gauche de (x, y) ; rend sa largeur."""
    f = _police("affiche", max(8, round(taille * 0.8)))
    x0, y0, x1, y1 = d.textbbox((x, y), "B", font=f, anchor="lm")
    d.text((x, y), "B", font=f, fill=couleur, anchor="lm")
    milieu, depasse = (x0 + x1) / 2 + (x1 - x0) * 0.04, (y1 - y0) * 0.16
    d.line([(milieu, y0 - depasse), (milieu, y1 + depasse)], fill=couleur, width=max(2, round(taille * 0.07)))
    return x1 - x


def _silhouette(l: int, h: int):
    """Le portrait absent : une silhouette d'encre sur le papier (comme la page)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (l, h), (236, 222, 190, 255))
    d = ImageDraw.Draw(im)
    teinte = (160, 128, 84, 255)
    r = l * 0.2
    d.ellipse([l / 2 - r, h * 0.36 - r, l / 2 + r, h * 0.36 + r], fill=teinte)
    d.rounded_rectangle([l * 0.27, h * 0.66, l * 0.73, h * 1.08], radius=l * 0.08, fill=teinte)
    return im


def _avis(a: dict, l: int, mention: str):
    """Un avis de recherche (gabarit de `site/ornements/affiche.json`, 600 × 840) de `l` pixels de large."""
    from PIL import Image, ImageDraw, ImageEnhance
    h = round(l * 7 / 5)
    k = l / 600
    im = Image.new("RGBA", (l, h), (0, 0, 0, 0))
    im.alpha_composite(_texture("papier_affiche").resize((l, h), Image.Resampling.LANCZOS))
    d = ImageDraw.Draw(im)
    encre = ENCRE + (255,)
    for marge, epais, opacite in ((34, 5, 210), (46, 1.6, 150)):   # le double filet imprimé
        m = round(marge * k)
        d.rectangle([m, m, l - m, h - m], outline=ENCRE + (opacite,), width=max(1, round(epais * k)))
    f, t = _ajuster(d, "WANTED", "affiche", round(100 * k), 470 * k)
    d.text((l / 2, (44 + 54) * k), t, font=f, fill=encre, anchor="mm")
    f = _police("capitales", max(8, round(23 * k)))
    _espace(d, (l / 2, (162 + 17) * k), "AVIS DE L'ÉQUIPAGE", f, (74, 50, 32, 255), 2.2 * k)
    for y in (150, 205):
        d.line([(110 * k, y * k), (490 * k, y * k)], fill=ENCRE + (170,), width=max(1, round(2 * k)))
    x, y, pl, ph = (round(v * k) for v in (120, 214, 360, 316))
    portrait = _silhouette(pl, ph)
    if a.get("portrait"):
        try:
            with Image.open(a["portrait"]) as brut:
                tete = _couvrir(brut.convert("RGBA"), (pl, ph))
            fond = Image.new("RGBA", (pl, ph), (236, 222, 190, 255))
            fond.alpha_composite(tete)
            portrait = ImageEnhance.Color(fond).enhance(0.82)   # un peu passé, comme l'encre sur le papier
        except OSError:
            pass   # portrait illisible : la silhouette (la bannière ne tombe jamais pour une image)
    im.alpha_composite(portrait, (x, y))
    d.rectangle([x - 2, y - 2, x + pl + 1, y + ph + 1], outline=encre, width=max(2, round(6 * k)))
    if a.get("grade"):
        gx, gy, gl, gh = 222 * k, 518 * k, 156 * k, 30 * k
        d.rectangle([gx, gy, gx + gl, gy + gh], fill=LAITON + (255,), outline=encre, width=max(1, round(2 * k)))
        f, t = _ajuster(d, a["grade"], "capitales", round(19 * k), gl - 10 * k)
        d.text((gx + gl / 2, gy + gh / 2), t, font=f, fill=encre, anchor="mm")
    if a.get("surnom"):
        f, t = _ajuster(d, f"« {a['surnom']} »", "italique", round(26 * k), 440 * k)
        d.text((l / 2, (562 + 17) * k), t, font=f, fill=(74, 50, 32, 255), anchor="mm")
    f, t = _ajuster(d, a["nom"].upper(), "affiche", round(48 * k), 488 * k)
    d.text((l / 2, (592 + 32) * k), t, font=f, fill=encre, anchor="mm")
    nombre = _nombre(a["prime"])
    f, t = _ajuster(d, nombre, "affiche", round(44 * k), 380 * k)
    signe = d.textbbox((0, 0), "B", font=_police("affiche", max(8, round(f.size * 0.8))), anchor="lm")
    total = (signe[2] - signe[0]) + 10 * k + d.textlength(t, font=f)
    depart = l / 2 - total / 2
    largeur = _berry(d, depart, (668 + 28) * k, f.size, encre)
    d.text((depart + largeur + 10 * k, (668 + 28) * k), t, font=f, fill=encre, anchor="lm")
    d.line([(150 * k, 735 * k), (450 * k, 735 * k)], fill=ENCRE + (150,), width=max(1, round(2 * k)))
    f, t = _ajuster(d, mention, "titre", round(30 * k), 300 * k)
    d.text((l / 2, (774 + 16) * k), t, font=f, fill=encre, anchor="mm")
    return im


def _poser(fond, im, centre, angle: float) -> None:
    """Poser un avis penché en `centre`, avec son ombre portée."""
    from PIL import Image, ImageFilter
    marge = 40   # l'ombre floutée a besoin de place autour de l'avis (sinon elle s'arrête net en rectangle)
    ombre = Image.new("RGBA", (im.width + 2 * marge, im.height + 2 * marge), (24, 14, 6, 0))
    alpha = Image.new("L", ombre.size, 0)
    alpha.paste(im.getchannel("A").point(lambda v: int(v * 0.42)), (marge, marge))
    ombre.putalpha(alpha)
    for calque, decalage, flou in ((ombre, (7, 11), 14), (im, (0, 0), 0)):
        r = calque.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        if flou:
            r = r.filter(ImageFilter.GaussianBlur(flou))
        fond.alpha_composite(r, (round(centre[0] - r.width / 2 + decalage[0]), round(centre[1] - r.height / 2 + decalage[1])))


def dessiner_banniere(b: dict) -> bytes:
    """L'image de l'aperçu (PNG 1200 × 630) : la carte marine sur parchemin, un cadre de bois, le nom de l'équipage à
    gauche, ses trois plus hautes primes en avis de recherche à droite. Rien que des données publiques."""
    from PIL import Image, ImageDraw
    W, H = LARGEUR, HAUTEUR
    fond = Image.new("RGBA", (W, H), (226, 204, 158, 255))
    tuile = _texture("parchemin_fonce")
    for x in range(0, W, tuile.width):
        for y in range(0, H, tuile.height):
            fond.alpha_composite(tuile.crop((0, 0, min(tuile.width, W - x), min(tuile.height, H - y))), (x, y))
    carte = _couvrir(_texture("carte_marine"), (W, H))
    carte.putalpha(carte.getchannel("A").point(lambda v: int(v * 0.55)))
    fond.alpha_composite(carte)
    avis = b.get("affiches") or []
    voile = Image.new("RGBA", (W, H), (0, 0, 0, 0))   # là où est le texte, le papier plus clair : il s'y lit
    dv = ImageDraw.Draw(voile)
    for x in range(0, W, 4):
        part = (1 - x / 680) if avis else (1 - abs(x - W / 2) / (W / 2)) * 0.9
        if part > 0:
            dv.rectangle([x, 0, x + 4, H], fill=(246, 232, 200, int(120 * part)))
    fond.alpha_composite(voile)
    fond.alpha_composite(_texture("vignette").resize((W, H), Image.Resampling.LANCZOS))
    #  Le cadre de bois, un filet de laiton dedans.
    bois = _couvrir(_texture("bois"), (W, H))
    masque = Image.new("L", (W, H), 255)
    ImageDraw.Draw(masque).rectangle([22, 22, W - 23, H - 23], fill=0)
    fond.paste(bois, (0, 0), masque)
    d = ImageDraw.Draw(fond)
    d.rectangle([22, 22, W - 23, H - 23], outline=LAITON + (255,), width=3)
    d.rectangle([27, 27, W - 28, H - 28], outline=ENCRE + (140,), width=1)

    #  Les avis à droite (le plus haut au milieu, devant ; les noms des autres restent lisibles), puis le texte.
    places = {1: [(895, 318, 1.5, 262)], 2: [(800, 330, -4.5, 232), (1012, 318, 3.5, 240)],
              3: [(700, 340, -5.0, 196), (1062, 340, 5.0, 196), (881, 316, 1.0, 236)]}
    if avis:
        ordre = [avis[1], avis[2], avis[0]] if len(avis) == 3 else (avis[::-1] if len(avis) == 2 else avis)
        for a, (cx, cy, angle, largeur) in zip(ordre, places[len(ordre)]):
            _poser(fond, _avis(a, largeur, b.get("mention") or ""), (cx, cy), angle)
    d = ImageDraw.Draw(fond)
    gauche, droite = 72, (588 if len(avis) == 3 else 640) if avis else W - 76
    centre = (gauche + droite) / 2
    f = _police("capitales", 27)
    haut = (b.get("haut") or "").upper()
    if haut:
        f, haut = _ajuster(d, haut, "capitales", 27, droite - gauche)
        _espace(d, (centre, 150), haut, f, SIENNE + (255,), 2.5)
    f, titre = _ajuster(d, b.get("titre") or "L'Équipage", "titre", 150, droite - gauche)
    d.text((centre + 2, 258 + 3), titre, font=f, fill=(255, 244, 214, 150), anchor="mm")   # le relief du papier
    d.text((centre, 258), titre, font=f, fill=ENCRE + (255,), anchor="mm")
    y = 338   # le filet d'encre et son losange
    d.line([(centre - 190, y), (centre - 14, y)], fill=ENCRE + (200,), width=2)
    d.line([(centre + 14, y), (centre + 190, y)], fill=ENCRE + (200,), width=2)
    d.polygon([(centre, y - 8), (centre + 8, y), (centre, y + 8), (centre - 8, y)], fill=ENCRE + (230,))
    f, ligne = _ajuster(d, b.get("ligne") or "", "italique", 36, droite - gauche)
    d.text((centre, 384), ligne, font=f, fill=SIENNE + (255,), anchor="mm")
    phrase = " ".join(str(b.get("phrase") or "").split())
    if phrase:
        f = _police("texte", 26)
        lignes, courante = [], ""
        for mot in phrase.split():
            essai = f"{courante} {mot}".strip()
            if d.textlength(essai, font=f) <= droite - gauche or not courante:
                courante = essai
            else:
                lignes.append(courante)
                courante = mot
        lignes.append(courante)
        if len(lignes) > 2:
            lignes = lignes[:2]
            _f, lignes[1] = _ajuster(d, lignes[1] + "…", "texte", 26, droite - gauche)
        for n, texte in enumerate(lignes):
            d.text((centre, 444 + n * 36), texte, font=f, fill=(74, 50, 32, 255), anchor="mm")
    sortie = io.BytesIO()
    fond.convert("RGB").save(sortie, "PNG", optimize=True)
    return sortie.getvalue()


__all__ = ["ADRESSE", "page", "donnees", "image", "banniere", "vers_vitrine", "dessiner_banniere", "oublier", "pret"]
