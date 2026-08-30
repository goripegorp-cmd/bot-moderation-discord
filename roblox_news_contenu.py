"""roblox_news_contenu.py — Le CONTENU d'une actualité : l'essentiel, les
images, les vidéos, et la traduction en français.

Demande du propriétaire (18/08/2026), mot pour mot :

    « Je veux que tu t'assures d'afficher vraiment les news correctes et que tu
    fasses une traduction en français. Il y a des images, des fois des vidéos,
    des choses importantes à ne pas rater. L'essentiel des informations du
    post. S'il y a un post qui nous dit "allez voir ce lien pour tel update",
    il sert à rien : il faut une news complète qui explique quelque chose de
    concret. S'il y a une image, l'image au propre, comme si tu reprenais le
    post — mais en traduisant en français. »

═══════════════════════════════════════════════════════════════════════════════
LA RÈGLE DE ROBLOX.MD, ET COMMENT ELLE EST TENUE
═══════════════════════════════════════════════════════════════════════════════
« Les traduire à la machine SANS LE DIRE serait un mensonge de plus. »
C'est le « sans le dire » qui faisait le mensonge. Chaque fiche traduite porte
donc la mention du fournisseur (« Traduction automatique (Google) — original en
anglais ») et le lien vers l'original. La salle de presse FR, écrite en français
par Roblox, n'est jamais traduite : on cite.

═══════════════════════════════════════════════════════════════════════════════
« L'ESSENTIEL » — COMMENT ON LE TROUVE SANS INVENTER
═══════════════════════════════════════════════════════════════════════════════
Mesuré sur les annonces réelles du 18/08 : Roblox ouvre CHAQUE billet par une
section « Key Takeaways » (parfois « TL;DR »), puis détaille. C'est l'essentiel
écrit par l'auteur lui-même — on le prend tel quel, jusqu'au titre suivant.
Sans cette section, on prend les premiers paragraphes, coupés proprement à une
frontière de paragraphe, jamais au milieu d'une phrase, dans la limite de
`BUDGET_CORPS`. On ne résume pas à la machine : on ne dispose d'aucun modèle
pour ça et on ne fabriquerait pas un texte que Roblox n'a pas écrit.

═══════════════════════════════════════════════════════════════════════════════
LES POSTS « POINTEURS » — CEUX QUI NE SERVENT À RIEN
═══════════════════════════════════════════════════════════════════════════════
« Hi all, release notes for 734 is here! Have a great rest of your week. » +
un lien. Mesuré : 70 caractères. Un billet dont le corps est court ET qui ne
fait que renvoyer ailleurs n'apprend rien : il est ÉCARTÉ, et compté à part
dans le compte-rendu pour qu'on sache qu'il a existé.

═══════════════════════════════════════════════════════════════════════════════
LES IMAGES — DOMAINES OFFICIELS SEULEMENT
═══════════════════════════════════════════════════════════════════════════════
Une URL d'image n'est pas reconstructible (empreinte). Elle est donc FILTRÉE
sur une liste blanche de domaines relevés dans les réponses réelles : uploads
du forum (S3), CDN Discourse hors émojis, CMS du newsroom, CDN Roblox. Le forum
sert ses images en URL relative au protocole (`//devforum-uploads…`) : on les
préfixe. Une image hors liste est ignorée — jamais affichée.
"""
from __future__ import annotations

import asyncio
import html as _html
import os
import re

_log = print


def setup(*, log=None):
    global _log
    if log is not None:
        _log = log


#  ── Bornes ────────────────────────────────────────────────────────────────
#  Components V2 : 4 000 caractères de texte au total par message. Le corps
#  prend la part du lion ; titre, méta et mention se partagent le reste.
BUDGET_CORPS = 2400
BUDGET_TITRE = 200
#  MediaGallery accepte 10. Six : le billet 4779420 (mesuré) porte cinq
#  captures et UN GIF animé de démonstration en cinquième position — à quatre,
#  le média le plus parlant sautait. Au-delà de six, la grille ne se lit plus.
MAX_IMAGES = 6
MAX_VIDEOS = 2
#  Un billet dont le texte utile tient sous ce seuil ET qui renvoie ailleurs
#  est un « pointeur ». 300 caractères : « Release notes for 734 is here! »
#  en fait 70 ; le plus court billet de fond mesuré en fait 900+.
SEUIL_POINTEUR = 300

#  ── Domaines d'images autorisés ────────────────────────────────────────────
DOMAINES_IMAGES = (
    "devforum-uploads.s3.dualstack.us-east-2.amazonaws.com",
    "devforum.roblox.com",
    "doy2mn9upadnk.cloudfront.net",
    "global.discourse-cdn.com",
    "cms-media.roblox.com",
    "tr.rbxcdn.com",
    "images.rbxcdn.com",
)

_MOTIF_ESSENTIEL = re.compile(
    r"key\s*takeaways?|tl;?\s*dr|summary|in\s+short|r[ée]sum[ée]|l['’]essentiel",
    re.I)


# ═══════════════════════════════════════════════════════════════════════════════
#  HTML → texte structuré
# ═══════════════════════════════════════════════════════════════════════════════

def _texte(html_fragment: str) -> str:
    """Retire les balises, déséchappe, normalise les blancs."""
    t = re.sub(r"<br\s*/?>", "\n", html_fragment)
    t = re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def _blocs(html: str) -> list[tuple[str, str, int]]:
    """Découpe un HTML en blocs (type, texte, niveau).

    type ∈ {"h", "p", "li", "pre"} ; `niveau` n'a de sens que pour "h".
    On garde l'ORDRE du document : c'est lui qui dit où commence et où finit
    une section. Les blocs vides sont écartés.
    """
    out = []
    for m in re.finditer(
            r"<(h[1-6])[^>]*>(.*?)</\1>"
            r"|<li[^>]*>(.*?)</li>"
            r"|<pre[^>]*>(.*?)</pre>"
            r"|<p[^>]*>(.*?)</p>",
            html, re.S | re.I):
        if m.group(1):
            t = _texte(m.group(2))
            if t:
                out.append(("h", t, int(m.group(1)[1])))
        elif m.group(3) is not None:
            t = _texte(m.group(3))
            if t:
                out.append(("li", t, 0))
        elif m.group(4) is not None:
            t = _texte(m.group(4))
            if t:
                out.append(("pre", t, 0))
        elif m.group(5) is not None:
            t = _texte(m.group(5))
            if t:
                out.append(("p", t, 0))
    return out


def _rendre(blocs: list[tuple[str, str, int]], budget: int) -> str:
    """Assemble des blocs en texte Discord, sans dépasser `budget`.

    Coupe à une frontière de BLOC, jamais au milieu d'une phrase : une fiche
    tronquée en pleine phrase se lit comme un défaut, pas comme un résumé.
    """
    lignes, total = [], 0
    for genre, t, niveau in blocs:
        if genre == "h":
            ligne = f"**{t}**"
        elif genre == "li":
            ligne = f"• {t}"
        elif genre == "pre":
            ligne = f"`{t[:200]}`"
        else:
            ligne = t
        #  +2 pour le saut de ligne double entre blocs.
        if total + len(ligne) + 2 > budget:
            if lignes:
                lignes.append("…")
            else:
                #  Un seul bloc plus long que tout le budget : on le coupe à la
                #  dernière phrase complète qui tient.
                coupe = ligne[:budget]
                fin = max(coupe.rfind(". "), coupe.rfind("! "), coupe.rfind("? "))
                lignes.append((coupe[:fin + 1] if fin > budget // 2 else coupe.rstrip()) + " …")
            break
        lignes.append(ligne)
        total += len(ligne) + 2
    return "\n\n".join(lignes)


_MOTIF_EN_TETE = re.compile(
    r"^(?:partager|share|par\s+.{1,60}|by\s+.{1,60}|publi[ée]e?\s+.{1,40}|published\s+.{1,40}"
    r"|updated\s+.{1,40}|mis\s+à\s+jour\s+.{1,40})$", re.I)


def _nettoyer_en_tete(blocs: list, titre: str | None) -> list:
    """Retire le bruit d'en-tête d'une page article : « Partager », le titre
    répété, « Par Untel », « Publié le … ». Mesuré sur la salle de presse le
    18/08 : ces cinq lignes précédaient le premier vrai paragraphe et se
    retrouvaient en tête de fiche, sous le titre déjà affiché.
    On ne retire QUE des blocs de tête, jamais un bloc au milieu du texte."""
    t_norm = re.sub(r"\s+", " ", (titre or "")).strip().lower()
    out = []
    for k, (genre, t, niveau) in enumerate(blocs):
        tn = re.sub(r"\s+", " ", t).strip().lower()
        #  Le bruit d'en-tête vit dans les tout premiers blocs ; au-delà, un
        #  « Par … » est peut-être une citation qu'on garde.
        if k < 6 and ((_MOTIF_EN_TETE.match(tn) and len(t) < 90)
                      or (t_norm and tn == t_norm)
                      or (genre == "h" and t_norm and tn in t_norm)):
            continue
        out.append((genre, t, niveau))
    return out


def extraire_essentiel(html: str, budget: int = BUDGET_CORPS,
                       titre: str | None = None) -> str:
    """L'essentiel d'un billet, écrit par son auteur.

    1. S'il existe une section « Key Takeaways » / « TL;DR » / « Summary » :
       son contenu, jusqu'au titre suivant de niveau égal ou supérieur.
    2. Sinon : les blocs depuis le début, dans le budget.
    Un billet vide rend « ». `titre` sert à écarter le titre répété en tête.
    """
    blocs = _nettoyer_en_tete(_blocs(html or ""), titre)
    if not blocs:
        return ""
    for i, (genre, t, niveau) in enumerate(blocs):
        if genre == "h" and _MOTIF_ESSENTIEL.search(t):
            section = []
            for genre2, t2, niveau2 in blocs[i + 1:]:
                if genre2 == "h" and niveau2 <= niveau:
                    break
                section.append((genre2, t2, niveau2))
            if section:
                return _rendre(section, budget)
            break
    #  Sans section d'essentiel : le début du billet, titres exclus quand ils
    #  ouvrent le texte (le titre du billet est déjà affiché à part).
    debut = [b for b in blocs if not (b[0] == "h" and b is blocs[0])]
    return _rendre(debut, budget)


# ═══════════════════════════════════════════════════════════════════════════════
#  Images et vidéos
# ═══════════════════════════════════════════════════════════════════════════════

def _domaine_autorise(url: str) -> bool:
    try:
        hote = re.match(r"^https?://([^/]+)/", url).group(1).lower()
    except Exception:
        return False
    return any(hote == d or hote.endswith("." + d) for d in DOMAINES_IMAGES)


def _absolue(url: str) -> str:
    """`//hote/chemin` → `https://hote/chemin`. Le forum sert ainsi ses images."""
    u = url.strip()
    if u.startswith("//"):
        return "https:" + u
    return u


def extraire_images(html: str, maximum: int = MAX_IMAGES) -> list[str]:
    """Les images du billet, PLEINE TAILLE quand elle existe, filtrées.

    Discourse enveloppe une image dans `<a class="lightbox" href="PLEINE">
    <img src="MINIATURE">` : on préfère la pleine taille et on ne compte pas la
    miniature une seconde fois. Les émojis (`/emoji/`) et les avatars sont
    écartés. Domaine hors liste blanche = ignoré.
    """
    vus, out = set(), []

    def _cle(u: str) -> str:
        #  Discourse nomme un fichier par son EMPREINTE SHA-1 (40 hex) et sa
        #  miniature `{empreinte}_{version}_{L}x{H}.ext` — parfois avec une
        #  AUTRE extension que l'original (jpeg → png). Mesuré le 18/08 : la
        #  dédup par « chemin sans dimensions » gardait l'originale ET la
        #  miniature. L'empreinte seule les confond, et c'est ce qu'on veut.
        m = re.search(r"([0-9a-f]{40})", u)
        return m.group(1) if m else u

    def _ajouter(u):
        u = _absolue(_html.unescape(u))
        if "/emoji/" in u or "/user_avatar/" in u or "/letter_avatar" in u:
            return
        if not _domaine_autorise(u):
            return
        cle = _cle(u)
        if cle in vus:
            return
        vus.add(cle)
        out.append(u)

    #  ORDRE DU DOCUMENT, en une seule passe : dans une lightbox, le `<a href>`
    #  (pleine taille) précède le `<img src>` (miniature) — la première
    #  occurrence gagne, donc l'originale. Une image hors lightbox (un GIF
    #  animé, que Discourse ne met pas en lightbox) reste à sa place.
    #  ⚠️ `\shref=` et non `href=` : la balise porte AUSSI un
    #  `data-download-href="/uploads/short-url/…"` (chemin relatif, rejeté par
    #  le filtre de domaine). Un `[^>]+href=` gourmand reculait jusqu'à ce
    #  dernier, la pleine taille était perdue, et la miniature `optimized`
    #  prenait sa place. Mesuré le 18/08 sur le billet 4779420.
    #  `<img\s[^>]*?src=` et non `<img[^>]+\ssrc=` : ce dernier exigeait un
    #  caractère AVANT l'espace, donc `<img src="…">` — src en premier
    #  attribut, la forme des GIF hors lightbox — ne matchait pas. Le GIF de
    #  démonstration du billet 4779420 sautait pour ça.
    for m in re.finditer(
            r'<a\s[^>]*?class="[^"]*lightbox[^"]*"[^>]*?\shref="([^"]+)"'
            r'|<img\s[^>]*?src="([^"]+)"',
            html or ""):
        _ajouter(m.group(1) or m.group(2))
    return out[:maximum]


_MOTIF_YOUTUBE = re.compile(
    r"https?://(?:www\.|m\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)"
    r"([A-Za-z0-9_\-]{11})")


def extraire_videos(html: str, maximum: int = MAX_VIDEOS) -> list[str]:
    """Les vidéos YouTube d'un billet, RECONSTRUITES depuis leur identifiant.

    Un identifiant YouTube fait exactement 11 caractères de [A-Za-z0-9_-] :
    on le valide, puis on reconstruit `https://www.youtube.com/watch?v=ID`.
    Jamais l'URL recopiée telle quelle (ROBLOX.md §1). Elles partent en
    boutons-liens : Discord ne lit pas YouTube dans un conteneur V2.
    """
    vus, out = set(), []
    for m in _MOTIF_YOUTUBE.finditer(html or ""):
        vid = m.group(1)
        if vid not in vus:
            vus.add(vid)
            out.append(f"https://www.youtube.com/watch?v={vid}")
    return out[:maximum]


def extraire_videos_fichiers(html: str, maximum: int = MAX_VIDEOS) -> list[str]:
    """Les vidéos HÉBERGÉES par le forum (`<video><source src="…mp4">`).

    Celles-là, Discord sait les LIRE dans une galerie V2 — c'est le « voire
    même en mieux » demandé : la vidéo se joue dans le salon, pas derrière
    un lien. Même liste blanche de domaines que les images.
    """
    vus, out = set(), []
    for m in re.finditer(r'<(?:source|video)[^>]+src="([^"]+\.(?:mp4|webm|mov))(?:\?[^"]*)?"',
                         html or "", re.I):
        u = _absolue(_html.unescape(m.group(1)))
        if _domaine_autorise(u) and u not in vus:
            vus.add(u)
            out.append(u)
    return out[:maximum]


def est_pointeur(texte: str, html: str) -> bool:
    """Le billet ne fait-il que renvoyer ailleurs ?

    Court ET porteur d'au moins un lien sortant. Un billet court SANS lien
    (une annonce brève mais complète) n'est pas un pointeur.

    ⚠️ ON JUGE SUR LE CORPS ENTIER, PAS SUR L'ESSENTIEL EXTRAIT. Un billet de
    fond dont le « Key Takeaways » tient en deux puces (180 caractères) aurait
    été écarté comme pointeur si l'on avait mesuré l'essentiel — attrapé par
    un test. `texte` ne sert plus que de repli quand `html` est vide.
    """
    complet = _texte(html) if html else (texte or "")
    if len(complet.strip()) >= SEUIL_POINTEUR:
        return False
    return bool(re.search(r'<a[^>]+href="https?://', html or ""))


# ═══════════════════════════════════════════════════════════════════════════════
#  Traduction — DeepL si clé, sinon Google, sinon MyMemory ; jamais bloquante
# ═══════════════════════════════════════════════════════════════════════════════

FOURNISSEURS = ("deepl", "google", "mymemory")


def fournisseurs_disponibles() -> list[str]:
    """L'ordre d'essai. `TRADUCTION_FOURNISSEUR` force un fournisseur unique ;
    `TRADUCTION_FOURNISSEUR=aucun` coupe la traduction (fiches en anglais,
    mention affichée)."""
    force = (os.getenv("TRADUCTION_FOURNISSEUR") or "").strip().lower()
    if force == "aucun":
        return []
    if force in FOURNISSEURS:
        return [force]
    out = []
    if os.getenv("DEEPL_API_KEY"):
        out.append("deepl")
    out += ["google", "mymemory"]
    return out


async def _deepl(sess, texte: str) -> str | None:
    cle = os.getenv("DEEPL_API_KEY", "")
    hote = "api-free.deepl.com" if cle.endswith(":fx") else "api.deepl.com"
    async with sess.post(f"https://{hote}/v2/translate",
                         data={"auth_key": cle, "text": texte,
                               "source_lang": "EN", "target_lang": "FR"}) as r:
        if r.status != 200:
            return None
        d = await r.json(content_type=None)
        return "".join(x.get("text", "") for x in d.get("translations", [])) or None


async def _google(sess, texte: str) -> str | None:
    """Point non officiel, sans clé. Fonctionne — mesuré le 18/08 — mais peut
    disparaître sans préavis : d'où la chaîne de repli."""
    async with sess.get("https://translate.googleapis.com/translate_a/single",
                        params={"client": "gtx", "sl": "en", "tl": "fr",
                                "dt": "t", "q": texte}) as r:
        if r.status != 200:
            return None
        d = await r.json(content_type=None)
        return "".join(x[0] for x in (d[0] or []) if x and x[0]) or None


async def _mymemory(sess, texte: str) -> str | None:
    """Gratuit, sans clé, mais 500 caractères par requête et un quota
    journalier : on découpe par phrases."""
    morceaux, courant = [], ""
    for phrase in re.split(r"(?<=[.!?])\s+", texte):
        if len(courant) + len(phrase) + 1 > 480 and courant:
            morceaux.append(courant)
            courant = phrase
        else:
            courant = (courant + " " + phrase).strip()
    if courant:
        morceaux.append(courant)
    out = []
    for m in morceaux[:8]:
        async with sess.get("https://api.mymemory.translated.net/get",
                            params={"q": m, "langpair": "en|fr"}) as r:
            if r.status != 200:
                return None
            d = await r.json(content_type=None)
            t = (d.get("responseData") or {}).get("translatedText")
            if not t or "MYMEMORY WARNING" in str(t).upper():
                return None
            out.append(str(t))
        await asyncio.sleep(0.5)
    return " ".join(out) or None


async def traduire(texte: str) -> tuple[str | None, str | None]:
    """→ (texte français, nom du fournisseur) ou (None, None).

    Ne lève JAMAIS : une panne de traduction ne doit pas taire une actualité.
    L'appelant publie alors l'original avec la mention « traduction
    indisponible ».

    ⚠️ UN SEUL APPEL PAR BILLET. Mesuré le 18/08 sur Google : les paragraphes,
    le gras (`**…**`) et les puces (`• `) survivent à la traduction en bloc.
    Une première version traduisait ligne à ligne — dix requêtes par billet
    pour rien, et un risque de blocage à la première rafale.
    """
    if not texte or not texte.strip():
        return None, None
    import aiohttp
    noms = {"deepl": "DeepL", "google": "Google", "mymemory": "MyMemory"}
    for nom in fournisseurs_disponibles():
        try:
            async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=25),
                    headers={"User-Agent": "BotModerationDiscord/1.0 (veille Roblox)"}
            ) as sess:
                fn = {"deepl": _deepl, "google": _google, "mymemory": _mymemory}[nom]
                fr = await fn(sess, texte)
                if fr and fr.strip():
                    return _html.unescape(fr).strip(), noms[nom]
        except Exception as ex:
            _log(f"[roblox_news_contenu traduire {nom}] {type(ex).__name__}: {ex}")
            continue
    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
#  L'assemblage — ce que reçoivent les lecteurs de source
# ═══════════════════════════════════════════════════════════════════════════════

async def enrichir_billet(billet: dict, html_corps: str, langue: str = "en") -> dict:
    """Complète un billet avec son essentiel, ses médias, sa traduction.

    Modifie ET rend `billet`. Pose :
      corps, corps_fr, titre_fr, langue, traduit_par, images, videos, pointeur
    Ne lève jamais.
    """
    try:
        corps = extraire_essentiel(html_corps, titre=billet.get("titre"))
        #  ⚠️ LES NOTES DE VERSION NE SORTAIENT JAMAIS — mesuré sur TROIS
        #  semaines consécutives le 30/08/2026, et c'est exactement ce que le
        #  propriétaire réclamait (« même des mises à jour et tout ») :
        #    · 11/08 « Release Notes for 734 » → 70 caractères  → JETÉ
        #    · 20/08 « Release Notes for 735 » → 320 caractères → fiche vide
        #    · 27/08 « Release Notes for 736 » → 424 caractères → fiche vide
        #  Le billet du forum ne contient qu'une phrase et un lien : tout le
        #  contenu vit sur `create.roblox.com/docs`. On va donc le chercher.
        #  Aucune source périodique n'est ajoutée : la requête ne part que
        #  lorsqu'un billet pointe vraiment là-bas, soit ~1 fois par semaine.
        _repris_des_docs = False
        if len((corps or "").strip()) < SEUIL_POINTEUR:
            #  ⚠️ SON PROPRE FILET, ET C'EST INDISPENSABLE. Le `try` qui
            #  englobe toute cette fonction rend le billet EN L'ÉTAT quand il
            #  attrape : une panne ici sortait donc un billet sans `corps`,
            #  sans `images` et SANS la clé `pointeur` — que l'appelant lit en
            #  `.get()`, donc le billet passait, amputé, au lieu d'être écarté.
            #  Une source annexe injoignable ne doit jamais dégrader le billet
            #  au-delà de « il n'a pas de corps enrichi ».
            try:
                _docs = await corps_documentation(
                    html_corps,
                    date_iso=billet.get("cree_le") or billet.get("date"))
            except Exception as ex:
                _log(f"[roblox_news_contenu docs] {type(ex).__name__}: {ex}")
                _docs = None
            if _docs:
                corps = _docs
                billet["source_corps"] = "documentation Roblox"
                _repris_des_docs = True
        billet["corps"] = corps
        billet["images"] = extraire_images(html_corps)
        billet["videos"] = extraire_videos(html_corps)
        billet["videos_fichiers"] = extraire_videos_fichiers(html_corps)
        billet["langue"] = langue
        #  ⚠️ SI ON EST ALLÉ CHERCHER LE CONTENU, CE N'EST PLUS UN POINTEUR.
        #  `est_pointeur` juge sur le HTML D'ORIGINE — celui du forum, resté
        #  court. Sans cette ligne, on paierait la requête vers la
        #  documentation, on obtiendrait le vrai contenu, et on jetterait le
        #  billet quand même. C'est le défaut à deux étages qui a fait
        #  disparaître trois semaines de notes de version.
        billet["pointeur"] = (False if _repris_des_docs
                              else est_pointeur(corps, html_corps))
        billet["traduit_par"] = None
        if langue == "fr":
            billet["corps_fr"] = corps
            billet["titre_fr"] = billet.get("titre")
            return billet
        if billet["pointeur"]:
            #  On ne dépense pas une traduction pour un billet qu'on écarte.
            billet["corps_fr"] = None
            billet["titre_fr"] = None
            return billet
        #  Titre et corps dans UN appel : moins de requêtes, et le titre reste
        #  cohérent avec le texte.
        bloc = f"{billet.get('titre') or ''}\n\n{corps}".strip()
        fr, par = await traduire(bloc[:BUDGET_TITRE + BUDGET_CORPS + 4])
        if fr:
            titre_fr, _, corps_fr = fr.partition("\n\n")
            billet["titre_fr"] = titre_fr.strip()[:BUDGET_TITRE] or None
            billet["corps_fr"] = corps_fr.strip() or None
            billet["traduit_par"] = par
        else:
            billet["titre_fr"] = None
            billet["corps_fr"] = None
    except Exception as ex:
        _log(f"[roblox_news_contenu enrichir_billet] {type(ex).__name__}: {ex}")
    return billet


# ═══════════════════════════════════════════════════════════════════════════════
#  Le contenu réel des notes de version — sur la documentation, pas sur le forum
# ═══════════════════════════════════════════════════════════════════════════════

#  ⚠️ DOMAINE EN DUR. Même règle que partout dans ce dépôt : une URL suivie par
#  le bot est RECONSTRUITE à partir d'une constante et d'un chemin validé,
#  jamais recopiée telle quelle depuis une réponse. Ce bot lutte contre le
#  phishing — il ne peut pas suivre un lien approximatif.
DOMAINE_DOCS = "https://create.roblox.com"

#  Les chemins de documentation qu'on accepte de suivre. Tout le reste est
#  ignoré : on ne va pas chercher une page de marketing ou un profil.
CHEMINS_DOCS = ("/docs/updates/", "/docs/release-notes/")

#  Combien de caractères on retient de la page de documentation. Aligné sur ce
#  que la fiche affiche réellement — inutile de traduire ce qu'on coupera.
MAX_CORPS_DOCS = 2400


def lien_documentation(html: str) -> str | None:
    """Le chemin de documentation cité par ce billet, ou None.

    Rend un CHEMIN (`/docs/updates/2026-08-24`), jamais une URL complète :
    c'est l'appelant qui la reconstruit à partir de `DOMAINE_DOCS`.
    """
    if not html:
        return None
    for m in re.finditer(r'href="(https?://[^"]+)"', html):
        u = m.group(1)
        if not u.startswith(DOMAINE_DOCS + "/"):
            continue
        chemin = u[len(DOMAINE_DOCS):].split("?")[0].split("#")[0]
        #  ⚠️ ON VALIDE LE CHEMIN, on ne fait pas confiance à l'URL. Un billet
        #  peut citer n'importe quoi ; on ne suit que deux familles connues.
        if any(chemin.startswith(p) for p in CHEMINS_DOCS):
            return chemin.rstrip("/")
    return None


def _chemin_du_lundi(date_iso) -> str | None:
    """Le chemin `/docs/updates/AAAA-MM-JJ` du lundi de cette date.

    ⚠️ POURQUOI CE REPLI EXISTE, ET IL N'EST PAS THÉORIQUE. Mesuré le 30/08 sur
    les trois dernières notes de version : le lien du billet mène tantôt à
    `/docs/updates/2026-08-24` (qui répond), tantôt à
    `/docs/release-notes/release-notes-735` (dont la version `.md` rend 404).
    Deux semaines sur trois, suivre le lien seul aurait échoué. Le lundi de la
    date du billet, lui, a fonctionné pour les trois.
    """
    if not date_iso:
        return None
    try:
        from datetime import datetime as _dt, timedelta as _td
        d = _dt.fromisoformat(str(date_iso).replace("Z", "+00:00"))
    except Exception:
        return None
    lundi = d - _td(days=d.weekday())
    return f"/docs/updates/{lundi.strftime('%Y-%m-%d')}"


async def corps_documentation(html: str, date_iso=None) -> str | None:
    """Le texte de la page de documentation citée par ce billet. None si rien.

    ⚠️ POURQUOI `.md` ET PAS LA PAGE HTML. Mesuré le 30/08 : ajouter `.md` au
    chemin rend le markdown source — 474 à 1 340 octets, `text/markdown`, avec
    un ETag et un HTTP 304 sur `If-None-Match`. La page HTML, elle, est une
    application JavaScript dont le texte utile n'est pas dans le document.

    ⚠️ DEUX PIÈGES MESURÉS CE JOUR-LÀ, ET ILS COÛTENT CHER :
     1. `last_updated` du front-matter est un horodatage de BUILD : les
        semaines du 10, 17 et 24 août portent toutes `2026-08-28T18:00:06Z`, à
        la seconde près. Ne JAMAIS s'en servir comme date de publication.
     2. Un 404 rend du HTML avec un code 200-like côté taille (2 599 octets ce
        jour-là, 15 792 lors d'une autre mesure). On teste donc le code ET le
        type de contenu, jamais la taille.
    """
    #  Le lien du billet d'abord ; le lundi de sa date en repli. Les doublons
    #  sont écartés pour ne pas faire deux fois la même requête.
    chemins = []
    for c in (lien_documentation(html), _chemin_du_lundi(date_iso)):
        if c and c not in chemins:
            chemins.append(c)
    if not chemins:
        return None
    #  ⚠️ ON N'ESSAIE LE REPLI QUE SI LE BILLET POINTE DÉJÀ VERS LA
    #  DOCUMENTATION. Sinon toute annonce courte du forum déclencherait une
    #  requête inutile chaque semaine — exactement le « spam d'une recherche
    #  qui sert à rien » que le propriétaire a interdit.
    if lien_documentation(html) is None:
        return None
    try:
        async with _ouvrir_contenu() as sess:
            for chemin in chemins:
                url = f"{DOMAINE_DOCS}{chemin}.md"
                async with sess.get(url) as r:
                    if r.status != 200:
                        _log(f"[roblox_news_contenu docs] HTTP {r.status} sur "
                             f"{chemin}.md")
                        continue
                    type_contenu = str(r.headers.get("Content-Type") or "").lower()
                    if not type_contenu.startswith("text/markdown"):
                        #  La page d'erreur déguisée : elle rend 200, en HTML.
                        _log(f"[roblox_news_contenu docs] {chemin}.md répond "
                             f"en « {type_contenu} » et non en markdown")
                        continue
                    brut = await r.text()
                texte = _markdown_en_texte(brut)
                if texte:
                    return texte
    except Exception as ex:
        _log(f"[roblox_news_contenu docs] {type(ex).__name__}: {ex}")
    return None


def _markdown_en_texte(brut: str) -> str | None:
    """Réduit le markdown de la documentation à ce que la fiche sait afficher.

    On garde les titres de section et les puces — c'est la structure même des
    notes de version (« ## Improvements », « ## Fixes ») — et on jette le
    front-matter YAML, qui ne contient que des métadonnées de build.
    """
    if not brut:
        return None
    texte = brut.strip()
    #  Front-matter YAML : `---\n…\n---` en tête. Il porte `last_updated`, qui
    #  est un horodatage de build — le publier ferait dater toutes les notes du
    #  même jour.
    if texte.startswith("---"):
        fin = texte.find("\n---", 3)
        if fin != -1:
            texte = texte[fin + 4:].lstrip()
    lignes = []
    for ligne in texte.splitlines():
        l = ligne.strip()
        if not l:
            continue
        if l.startswith("#"):
            lignes.append(f"**{l.lstrip('#').strip()}**")
        elif l.startswith(("- ", "* ")):
            lignes.append(f"• {l[2:].strip()}")
        else:
            lignes.append(l)
    out = "\n".join(lignes).strip()
    return out[:MAX_CORPS_DOCS] if out else None


def _ouvrir_contenu():
    """Une session HTTP pour aller lire la documentation. Voir `corps_documentation`."""
    import aiohttp
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20),
        headers={"User-Agent": "GoRp-Discord-Bot/1.0 (veille actualités)",
                 "Accept": "text/markdown, text/plain"})
