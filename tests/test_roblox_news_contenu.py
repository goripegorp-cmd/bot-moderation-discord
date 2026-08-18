"""Le CONTENU d'une actualité — essentiel, médias, traduction, fiche.

DEMANDE DU PROPRIÉTAIRE (18/08), et l'ancienne fiche qu'il montre en modèle :
    « Les posts sont très moches, aucune information, les textes sont coupés.
    Il y a des images, des vidéos, des choses à ne pas rater. Un post qui dit
    "allez voir ce lien" sert à rien. Comme si tu reprenais le post, mais en
    français. C'est comme ça que tu les transformes, voire même en mieux. »

CE QUE CES TESTS TIENNENT, sans réseau, sur des extraits HTML RÉELS :
1. l'essentiel = la section « Key Takeaways » écrite par Roblox, sinon les
   premiers paragraphes — coupés proprement, jamais en pleine phrase ;
2. les posts « allez voir ce lien » sont écartés — pas les annonces brèves ;
3. les images sont filtrées sur les domaines officiels, en pleine taille,
   dédoublonnées ; les vidéos YouTube sont reconstruites depuis leur id ;
4. la fiche est bilingue FR puis EN, illustrée, datée nativement, sous les
   4 000 caractères — et elle DIT quand elle est traduite à la machine.
"""
from __future__ import annotations

import pytest

import roblox_news_contenu as c
import roblox_panneau as rp


@pytest.fixture(autouse=True)
def _silence():
    c.setup(log=lambda *a: None)
    rp.setup(db_set=None, webhook_send=None, log=lambda *a: None)


#  Forme réelle d'un billet d'annonce du forum (18/08), réduite.
COOKED = '''
<h2>Key Takeaways</h2>
<ul>
<li>Collections are now available in Studio Beta to help you manage groups of game objects.</li>
<li>This feature automatically connects your code to instances matching a query pattern.</li>
</ul>
<h2>Enabling the Studio Beta</h2>
<p>Hi Creators! Go to File &gt; Beta Features and enable &ldquo;Collections&rdquo;.</p>
<div class="lightbox-wrapper"><a class="lightbox" href="//devforum-uploads.s3.dualstack.us-east-2.amazonaws.com/uploads/original/5X/8/8/9/2/88921accbff16de03a9c0274acbf4d1c326ece0d.jpeg"><img src="//devforum-uploads.s3.dualstack.us-east-2.amazonaws.com/uploads/optimized/5X/8/8/9/2/88921accbff16de03a9c0274acbf4d1c326ece0d_2_690x388.jpeg"></a></div>
<img src="https://doy2mn9upadnk.cloudfront.net/images/emoji/twitter/star2.png?v=14">
<img src="https://evil.example/pixel.png">
<p>Watch: <a href="https://www.youtube.com/watch?v=Fg-Ksoa7b-s">demo</a> and <a href="https://youtu.be/_k1ea0OIKaU">more</a></p>
<video><source src="//devforum-uploads.s3.dualstack.us-east-2.amazonaws.com/uploads/original/5X/a/b/c/clip.mp4"></video>
'''

POINTEUR = '<p>Hi all, release notes for 734 is here! Have a great rest of your week. '\
           '<a href="https://create.roblox.com/docs/release-notes/734">Release Notes</a></p>'


# ═══════════════════════════════════════════════════════════════════════════════
#  1. L'essentiel
# ═══════════════════════════════════════════════════════════════════════════════

def test_lessentiel_est_la_section_key_takeaways():
    t = c.extraire_essentiel(COOKED)
    assert t.startswith("• Collections are now available")
    assert "query pattern" in t
    assert "Enabling the Studio Beta" not in t, (
        "la section s'arrête au titre suivant : c'est l'auteur qui a résumé")


def test_sans_section_dessentiel_on_prend_le_debut():
    html = "<p>Premier paragraphe utile et complet.</p><p>Second paragraphe.</p>"
    t = c.extraire_essentiel(html)
    assert t == "Premier paragraphe utile et complet.\n\nSecond paragraphe."


def test_le_budget_coupe_a_une_frontiere_de_bloc_jamais_en_pleine_phrase():
    html = "".join(f"<p>Paragraphe numéro {i} avec un peu de texte dedans.</p>"
                   for i in range(60))
    t = c.extraire_essentiel(html, budget=300)
    assert len(t) <= 300 + 2
    assert t.endswith("…")
    assert "dedans.\n\n…" in t, "la coupe tombe entre deux paragraphes"


def test_les_entites_html_sont_decodees():
    """L'ancienne fiche affichait « &hellip; » — mesuré sur la capture."""
    t = c.extraire_essentiel("<p>Today we&rsquo;re shipping&hellip; go to File &gt; Beta</p>")
    assert "&hellip;" not in t and "&rsquo;" not in t and "&gt;" not in t
    assert "we’re shipping…" in t and "File > Beta" in t


def test_len_tete_darticle_est_nettoye():
    """Salle de presse : « Partager », le titre répété, « Par … », « Publié … »
    précédaient le premier vrai paragraphe."""
    html = ("<p>Partager</p><h1>Au-delà du selfie</h1><p>Un sous-titre utile</p>"
            "<p>Par Xixi Wang</p><p>Publié 4 août 2026</p><p>Le vrai premier paragraphe.</p>")
    t = c.extraire_essentiel(html, titre="Au-delà du selfie")
    assert "Partager" not in t and "Par Xixi Wang" not in t and "Publié 4 août" not in t
    assert "Au-delà du selfie" not in t, "le titre est déjà affiché à part"
    assert t.startswith("Un sous-titre utile"), "le sous-titre, lui, est du contenu"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Les posts « allez voir ce lien »
# ═══════════════════════════════════════════════════════════════════════════════

def test_un_post_court_qui_renvoie_ailleurs_est_un_pointeur():
    assert c.est_pointeur(c.extraire_essentiel(POINTEUR), POINTEUR) is True


def test_une_annonce_breve_SANS_lien_nest_pas_un_pointeur():
    html = "<p>Studio est indisponible ce soir de 20 h à 21 h pour maintenance.</p>"
    assert c.est_pointeur(c.extraire_essentiel(html), html) is False


def test_un_post_de_fond_avec_liens_nest_pas_un_pointeur():
    assert c.est_pointeur(c.extraire_essentiel(COOKED), COOKED) is False


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Les médias
# ═══════════════════════════════════════════════════════════════════════════════

def test_les_images_sont_filtrees_dedoublonnees_et_pleine_taille():
    imgs = c.extraire_images(COOKED)
    assert imgs == [
        "https://devforum-uploads.s3.dualstack.us-east-2.amazonaws.com/uploads/original/5X/8/8/9/2/88921accbff16de03a9c0274acbf4d1c326ece0d.jpeg"
    ], ("une seule image : la pleine taille du lightbox ; la miniature "
        "_2_690x388 est la même ; l'emoji et le domaine étranger sont écartés")


def test_les_urls_relatives_au_protocole_sont_prefixees():
    assert c._absolue("//devforum-uploads.s3.dualstack.us-east-2.amazonaws.com/x.png") \
        == "https://devforum-uploads.s3.dualstack.us-east-2.amazonaws.com/x.png"


@pytest.mark.parametrize("url", [
    "https://evil.example/a.png",
    "https://cms-media.roblox.com.evil.example/a.png",
    "https://roblox.com.evil.example/a.png",
    "ftp://cms-media.roblox.com/a.png",
])
def test_un_domaine_hors_liste_est_refuse(url):
    assert c._domaine_autorise(url) is False


def test_les_videos_youtube_sont_reconstruites_depuis_lidentifiant():
    assert c.extraire_videos(COOKED) == [
        "https://www.youtube.com/watch?v=Fg-Ksoa7b-s",
        "https://www.youtube.com/watch?v=_k1ea0OIKaU",
    ]


def test_les_videos_hebergees_par_le_forum_sont_gardees_pour_la_galerie():
    assert c.extraire_videos_fichiers(COOKED) == [
        "https://devforum-uploads.s3.dualstack.us-east-2.amazonaws.com/uploads/original/5X/a/b/c/clip.mp4"
    ]


# ═══════════════════════════════════════════════════════════════════════════════
#  4. La traduction — chaîne de repli, jamais bloquante
# ═══════════════════════════════════════════════════════════════════════════════

def test_lordre_des_fournisseurs_depend_de_la_cle_deepl(monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    monkeypatch.delenv("TRADUCTION_FOURNISSEUR", raising=False)
    assert c.fournisseurs_disponibles() == ["google", "mymemory"]
    monkeypatch.setenv("DEEPL_API_KEY", "abc:fx")
    assert c.fournisseurs_disponibles()[0] == "deepl"
    monkeypatch.setenv("TRADUCTION_FOURNISSEUR", "aucun")
    assert c.fournisseurs_disponibles() == []


@pytest.mark.asyncio
async def test_traduire_retombe_sur_le_fournisseur_suivant(monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    monkeypatch.delenv("TRADUCTION_FOURNISSEUR", raising=False)

    async def _google_ko(sess, t):
        raise RuntimeError("bloqué")

    async def _mymemory_ok(sess, t):
        return "Bonjour"

    monkeypatch.setattr(c, "_google", _google_ko)
    monkeypatch.setattr(c, "_mymemory", _mymemory_ok)
    fr, par = await c.traduire("Hello")
    assert (fr, par) == ("Bonjour", "MyMemory")


@pytest.mark.asyncio
async def test_traduire_ne_leve_jamais_quand_tout_echoue(monkeypatch):
    monkeypatch.setenv("TRADUCTION_FOURNISSEUR", "google")

    async def _google_ko(sess, t):
        raise RuntimeError("bloqué")

    monkeypatch.setattr(c, "_google", _google_ko)
    assert await c.traduire("Hello") == (None, None)


@pytest.mark.asyncio
async def test_enrichir_billet_pose_tout_et_ne_traduit_pas_le_francais(monkeypatch):
    appels = []

    async def _traduire(t):
        appels.append(t)
        return "Titre FR\n\n• Point un\n\n• Point deux", "Google"

    monkeypatch.setattr(c, "traduire", _traduire)

    b = await c.enrichir_billet({"titre": "Title EN"}, COOKED, "en")
    assert b["corps"].startswith("• Collections")
    assert b["titre_fr"] == "Titre FR" and b["corps_fr"].startswith("• Point un")
    assert b["traduit_par"] == "Google" and b["langue"] == "en"
    assert len(b["images"]) == 1 and len(b["videos"]) == 2
    assert b["pointeur"] is False

    appels.clear()
    b_fr = await c.enrichir_billet({"titre": "Titre"}, "<p>Texte en français.</p>", "fr")
    assert appels == [], "un texte français n'est JAMAIS traduit — on cite"
    assert b_fr["corps_fr"] == "Texte en français." and b_fr["traduit_par"] is None


@pytest.mark.asyncio
async def test_un_pointeur_nest_pas_traduit(monkeypatch):
    """On ne dépense pas une requête pour un billet qu'on écarte."""
    appels = []

    async def _traduire(t):
        appels.append(t)
        return "x", "Google"

    monkeypatch.setattr(c, "traduire", _traduire)
    b = await c.enrichir_billet({"titre": "Release Notes for 734"}, POINTEUR, "en")
    assert b["pointeur"] is True and appels == []


# ═══════════════════════════════════════════════════════════════════════════════
#  5. La fiche — bilingue, illustrée, datée, sous les limites
# ═══════════════════════════════════════════════════════════════════════════════

def _compter(p):
    n = 0
    for x in p:
        n += 1
        n += _compter(x.get("components", []) or [])
    return n


def _texte(p):
    n = 0
    for x in p:
        if x.get("type") == 10:
            n += len(x.get("content", ""))
        n += _texte(x.get("components", []) or [])
    return n


def _types(p, s=None):
    s = s if s is not None else set()
    for x in p:
        s.add(x.get("type"))
        _types(x.get("components", []) or [], s)
    return s


BILLET_EN = {
    "topic_id": 4779420, "titre": "[Studio Beta] No-code Hotkey Hints",
    "domaine": "Annonces", "cree_le": "2026-08-04T18:11:00Z", "langue": "en",
    "corps": "• InputActionLabel is a new UI instance.\n\nHi Creators!",
    "corps_fr": "• InputActionLabel est une nouvelle instance d'interface.\n\nSalut les créateurs !",
    "titre_fr": "[Studio Beta] Astuces de raccourcis sans code", "traduit_par": "Google",
    "images": ["https://devforum-uploads.s3.dualstack.us-east-2.amazonaws.com/uploads/original/5X/a.jpeg"],
    "videos": ["https://www.youtube.com/watch?v=Fg-Ksoa7b-s"], "videos_fichiers": [],
    "lien": None,
}

BILLET_FR = {
    "topic_id": "newsroom:2026/08/x", "titre": "Au-delà du selfie", "domaine": "Salle de presse (FR)",
    "cree_le": "2026-08-04T12:00:00Z", "langue": "fr", "corps": "Le texte français.",
    "corps_fr": "Le texte français.", "titre_fr": "Au-delà du selfie", "traduit_par": None,
    "images": ["https://cms-media.roblox.com/assets/x.png"], "videos": [], "videos_fichiers": [],
    "lien": "https://about.roblox.com/fr/newsroom/2026/08/x",
}


def test_la_fiche_traduite_est_bilingue_francais_dabord():
    p = rp.construire_actu(BILLET_EN).to_components()
    brut = str(p)
    i_fr, i_en = brut.find("Salut les créateurs"), brut.find("Hi Creators")
    assert 0 < i_fr < i_en, "français d'abord, l'original ensuite"
    assert "🇬🇧 Original (English)" in brut
    assert "Traduction automatique (Google)" in brut, "la fiche DIT qu'elle traduit"
    assert "[Studio Beta] Astuces" in brut


def test_la_fiche_francaise_ne_montre_pas_de_bloc_anglais_ni_de_mention_de_traduction():
    brut = str(rp.construire_actu(BILLET_FR).to_components())
    assert "Original (English)" not in brut
    assert "Rédigé en français par Roblox" in brut


def test_la_fiche_porte_la_galerie_les_boutons_et_la_date_native():
    p = rp.construire_actu(BILLET_EN).to_components()
    brut = str(p)
    assert 12 in _types(p), "MediaGallery (type 12) pour l'image pleine largeur"
    from datetime import datetime, timezone
    attendu = int(datetime(2026, 8, 4, 18, 11, tzinfo=timezone.utc).timestamp())
    assert f"<t:{attendu}:f>" in brut, "horodatage natif Discord — fuseau du lecteur"
    assert "youtube.com/watch?v=Fg-Ksoa7b-s" in brut, "la vidéo YouTube part en bouton"


def test_le_titre_na_plus_le_suffixe_du_site():
    p = {"date": "2026-08-04T12:00:00.000Z", "titre": None}
    import roblox_news as n
    page = n._lire_page_article('<meta property="og:title" content="Titre | Roblox" />')
    assert page["titre"] == "Titre"


@pytest.mark.parametrize("billet", [BILLET_EN, BILLET_FR])
def test_la_fiche_reste_sous_les_limites_de_lapi(billet):
    vue = rp.construire_actu(billet)
    p = vue.to_components()
    assert p and _compter(p) <= 40 and _texte(p) <= 4000
    assert vue.has_components_v2()


def test_un_tres_long_corps_est_coupe_proprement_sous_4000():
    long_fr = "\n\n".join(f"Paragraphe {i}. Une phrase entière ici." for i in range(200))
    long_en = "\n\n".join(f"Paragraph {i}. A full sentence here." for i in range(200))
    b = dict(BILLET_EN, corps=long_en, corps_fr=long_fr)
    p = rp.construire_actu(b).to_components()
    assert _texte(p) <= 4000
    brut = str(p)
    assert " …" in brut, "la coupe est signalée"
    assert "Paragraphe 1." in brut and "A full sentence here" in brut, (
        "les deux langues sont présentes, chacune dans son budget")


def test_sans_traduction_la_fiche_le_dit_et_publie_quand_meme():
    b = dict(BILLET_EN, corps_fr=None, titre_fr=None, traduit_par=None)
    brut = str(rp.construire_actu(b).to_components())
    assert "traduction indisponible" in brut
    assert "Hi Creators" in brut, "l'original tient lieu de corps"
    assert "Original (English)" not in brut, "pas de doublon quand rien n'est traduit"


def test_tronquer_propre_ne_coupe_jamais_un_mot():
    t = rp._tronquer_propre("Un texte assez long pour être coupé quelque part au milieu", 30)
    assert t.endswith("…") and " au" not in t.rstrip(" …")[-3:] or t.count(" ") >= 2
    assert not t.rstrip(" …").endswith(("qu", "coup", "milie"))
