"""La sécurité du site (26/10/2026) — « protège le site contre tout type d'attaque possible ».

S1 le code ne sort plus : chaque fichier de `site/` à ses seuls lecteurs (tête, équipage, public), refusé comme absent.
S2 les en-têtes de base sur TOUTE réponse (même les 404 d'aiohttp), sans nom ni version du serveur.
S3 /stats publique : des nombres, des oui/non et des dates — jamais un nom, un identifiant, un contenu de cadeau.
S4 les surfaces publiques : transcripts jamais en cache, visuels sans chemin, JSON piégé sans erreur 500.
S5 la trace de chaque écriture du site vers Discord, à la porte (réussie, refusée, en échec), avec l'appareil.
S6 la rubrique « Sécurité » : sessions (appareil, adresse approximative, dernière activité), refus comptés, permissions.
S7 le bouton d'urgence « Fermer toutes les autres sessions » : la sienne reste ouverte.
S8 aucune fausse alerte : la tête n'est jamais alertée ; un signal fort (hors de la tête) l'est, regroupé.
S9 le journal d'audit : une permission dangereuse donnée hors de la tête est un signal fort ; rien n'est retiré.
"""
from __future__ import annotations

import asyncio
import json
import time

import discord
import pytest

import health_server
import rellseas_panneau
import securite_site
import tableau
from conftest_discord import Obj
from test_site_v2_serveur import DIRECTION, FONDATEUR, ORIGINE, TETE, Role, Site, _json, _site_v2


@pytest.fixture
def site(tmp_path, monkeypatch):
    s = Site(tmp_path, monkeypatch)
    securite_site.remettre_a_zero()
    yield s
    securite_site.remettre_a_zero()
    securite_site.setup(envoyer=None)


def _equipage(site, uid=7):
    """Une session du site de l'équipage (le rôle du clan réglé et porté)."""
    clan = site.g.role(50, "Rell Seas", 4)
    site.conf[rellseas_panneau.CLE_ROLE_CIBLE] = clan.id
    site.g.membres[uid].roles.append(clan)
    sid = asyncio.run(tableau._ouvrir_session(1, uid, int(time.time()) + 3600, portee="equipage"))
    return {"Cookie": f"{tableau.COOKIE}={sid}"}


# ═══════════════════════════════════════════════════════════════════════════════
#  S1 — le code ne sort plus
# ═══════════════════════════════════════════════════════════════════════════════

def test_S1_chaque_fichier_a_ses_seuls_lecteurs(site):
    dossier = site.tmp / "site"
    _site_v2(dossier)
    for rel, texte in (("equipage.js", "export const E = 1;"), ("dom.js", "export const d = 1;"),
                       ("securite.js", "export const s = 1;"), ("polices/polices.css", "@font-face{}"),
                       ("textures/bois.webp", "RIFF0000WEBP"), ("nouveau-module.js", "export const n = 1;"),
                       ("vitrine.js", "export const v = 1;"), ("direct.css", ".d{}"), ("textes.css", ".t{}")):
        (dossier / rel).parent.mkdir(parents=True, exist_ok=True)
        (dossier / rel).write_text(texte, encoding="utf-8")
    tete, eq = site.biscuit(origine=False), _equipage(site)

    async def scenario(c):
        out = {}
        for rel in ("app.js", "textes.css", "equipage.js", "direct.css", "style.css", "dom.js", "vitrine.js",
                    "securite.js", "nouveau-module.js", "polices/polices.css", "textures/bois.webp", "icones/ui.svg",
                    "manifest.webmanifest"):
            for qui, h in (("anonyme", {}), ("equipage", eq), ("tete", tete)):
                r = await c.get(f"/tableau/espace/s/{rel}?v=1", headers=h)
                out[(rel, qui)] = (r.status, r.headers.get("Cache-Control"), await r.text())
        for qui, h in (("anonyme", {}), ("equipage", eq), ("tete", tete)):
            out[("sw.js", qui)] = ((await c.get("/tableau/espace/sw.js", headers=h)).status,)
        out["absent"] = (await c.get("/tableau/espace/s/rien.js?v=1")).status
        return out
    out = site.http(scenario)
    for rel in ("app.js", "textes.css", "securite.js", "nouveau-module.js"):
        assert out[(rel, "anonyme")][0] == out[(rel, "equipage")][0] == 404, f"{rel} : la tête seule"
        assert out[(rel, "tete")][:2] == (200, "private, max-age=31536000, immutable")
    assert out[("nouveau-module.js", "anonyme")][2] == "Introuvable.", "un fichier inconnu : la tête seule, par défaut"
    for rel in ("equipage.js", "direct.css"):
        assert out[(rel, "anonyme")][0] == 404 and out[(rel, "equipage")][0] == out[(rel, "tete")][0] == 200, \
            f"{rel} : la page de l'équipage et la tête"
        assert out[(rel, "equipage")][1].startswith("private"), "jamais gardé par un cache partagé"
    #  27/10/2026 : la vitrine publique (`/equipage`) charge le socle commun — public, comme l'image.
    for rel in ("style.css", "dom.js", "vitrine.js", "polices/polices.css", "textures/bois.webp", "icones/ui.svg",
                "manifest.webmanifest"):
        assert out[(rel, "anonyme")][0] == 200 and out[(rel, "anonyme")][1].startswith("public"), f"{rel} : public"
    assert out[("sw.js", "anonyme")] == out[("sw.js", "equipage")] == (404,) and out[("sw.js", "tete")] == (200,)
    assert out["absent"] == 404
    #  Les lecteurs : la liste explicite, le reste à la tête.
    assert tableau.lecteurs_statique("polices/alegreya.woff2") is None and tableau.lecteurs_statique("ui.js") is None
    assert tableau.lecteurs_statique("equipage.js") == frozenset({"tout", "equipage"})
    assert tableau.lecteurs_statique("app.js") == tableau.lecteurs_statique("inconnu.css") == frozenset({"tout"})
    #  Un membre de l'équipage qui demande le code de la direction : noté (une ligne, jamais une alerte).
    lignes = [x for x in site.journal() if x["type"] == "site.hors_portee"]
    assert len(lignes) == 1 and lignes[0]["gravite"] == 1 and not lignes[0]["membre_id"]
    assert securite_site._compteurs.get("fichier", 0) >= 4 and site.alertes == []


def _charge_par(page: str) -> set:
    """Ce que la page `site/<page>` charge : ses scripts et leur graphe d'imports statiques, ses feuilles de style."""
    import re
    racine = tableau.SITE
    texte = (racine / page).read_text(encoding="utf-8")

    def deps(f):
        t = (racine / f).read_text(encoding="utf-8")
        return set(re.findall(r'from\s+"\./([^"]+)"', t)) | set(re.findall(r'import\s+"\./([^"]+)"', t))
    vus, pile = set(), list(re.findall(r'<script[^>]+src="/tableau/espace/s/([A-Za-z0-9_.-]+\.js)', texte))
    while pile:
        f = pile.pop()
        if f not in vus:
            vus.add(f)
            pile.extend(deps(f))
    return vus | set(re.findall(r'/tableau/espace/s/([A-Za-z0-9_-]+\.css)', texte))


def test_S1b_les_fichiers_de_chaque_page_sont_ceux_qu_elle_charge():
    """Les listes suivent EXACTEMENT ce que chaque page charge : la vitrine publique (`site/vitrine.html`) → « public » ;
    le site de l'équipage (`site/equipage.html`) → « equipage » pour ce qu'il charge en plus. Rien de plus (le code de
    la Capitainerie ne sort pas), rien de moins (les pages marchent). `direct.js`, chargé seulement en mode édition (la
    tête), n'en fait pas partie. Un import ajouté sans y penser fait échouer ce test : le décider ici (tableau.py)."""
    publics = {m for m in tableau.ACCES_STATIQUES["public"] if "*" not in m and m.endswith((".js", ".css"))}
    vitrine = _charge_par("vitrine.html") | _charge_par("candidature.html")   # les deux pages SANS session de la direction
    assert publics == vitrine, (f"vitrine.html et candidature.html chargent {sorted(vitrine - publics)} (à rendre publics) ; "
                                f"publics sans raison : {sorted(publics - vitrine)}")
    equipage = _charge_par("equipage.html") - vitrine
    assert set(tableau.ACCES_STATIQUES["equipage"]) == equipage, sorted(equipage)
    capitainerie = _charge_par("index.html") - vitrine - equipage
    for propre in ("app.js", "securite.js", "discord.js", "clan.js", "recrutement.js", "fiche.js", "textes.js",
                   "equipes_admin.js", "direct.js"):
        assert propre in capitainerie and tableau.lecteurs_statique(propre) == frozenset({"tout"}), propre


# ═══════════════════════════════════════════════════════════════════════════════
#  S2 — les en-têtes de base sur toute réponse
# ═══════════════════════════════════════════════════════════════════════════════

def test_S2_entetes_de_base_partout_meme_sur_les_erreurs(site):
    async def scenario(c):
        out = {}
        for nom, chemin in (("inconnue", "/rien/du/tout"), ("health", "/health"), ("racine", "/"),
                            ("transcript", "/t/aaaaaaaaaaaaaaaaaaaaaa"), ("visuel", "/v/rien.png"),
                            ("page", "/tableau/espace/")):
            r = await c.get(chemin)
            out[nom] = dict(r.headers)
        r = await c.request("TRACE", "/health")
        out["methode"] = dict(r.headers, statut=r.status)
        return out
    out = site.http(scenario)
    for nom, h in out.items():
        for k, v in health_server.ENTETES_BASE.items():
            if k in ("Cross-Origin-Resource-Policy",):
                continue
            assert h.get(k), f"{nom} : {k} absent"
        assert h.get("Server") == "capitainerie" and "aiohttp" not in json.dumps(h), f"{nom} : ni nom ni version"
        #  Les politiques de document : sur les pages HTML seulement (sur un fichier, elles ne protègent rien et pèsent).
        est_page = "text/html" in h.get("Content-Type", "")
        for k in health_server.ENTETES_DOCUMENT:
            assert bool(h.get(k)) == est_page or (est_page and h.get(k)), f"{nom} : {k}"
    assert out["page"]["Cross-Origin-Opener-Policy"] == "same-origin" and out["page"]["Permissions-Policy"]
    assert "Permissions-Policy" not in out["health"], "un JSON public ne porte pas les politiques d'une page"
    assert out["inconnue"]["Cache-Control"] == "no-store" and "noindex" in out["inconnue"]["X-Robots-Tag"]
    assert out["methode"]["statut"] == 405
    #  Le cookie de session : __Host-, Secure, HttpOnly, SameSite=Lax (le lien du bouton Discord est une navigation
    #  depuis un autre site : Strict ne passerait pas la redirection), Path=/.
    assert tableau.COOKIE.startswith("__Host-")


def test_S2b_le_lien_du_bouton_discord_ouvre_toujours_la_session(site):
    j = tableau.jeton(1, FONDATEUR, "tout")

    async def scenario(c):
        r = await c.get(f"/tableau/{j}", allow_redirects=False,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Edg/141.0",
                                 "X-Forwarded-For": "86.245.12.34, 10.0.0.1"})
        return r.status, r.headers.get("Location"), r.headers.getall("Set-Cookie", [])
    st, ou, biscuits = site.http(scenario)
    assert st == 303 and ou == "/tableau/espace/"
    b = biscuits[0]
    for attendu in ("__Host-tableau=", "HttpOnly", "Secure", "SameSite=Lax", "Path=/"):
        assert attendu in b, attendu
    assert "Domain" not in b
    lignes = site.sql("SELECT appareil, adresse, vu_le FROM tableau_sessions")
    assert lignes == [("Windows · Edge", "86.245.12.x", lignes[0][2])] and lignes[0][2] > 0, \
        "l'appareil et l'adresse APPROXIMATIVE (jamais entière) de la session"


# ═══════════════════════════════════════════════════════════════════════════════
#  S3 — /stats publique
# ═══════════════════════════════════════════════════════════════════════════════

def test_S3_stats_publique_sans_nom_ni_identifiant(site, monkeypatch):
    monkeypatch.setattr(health_server, "ETAT_PUBLIC", {
        "logs_direction": True, "commu_salons": 3, "demarrage": {"etapes_ratees": ["tableau"]},
        "erreurs_ui": {"site/api.rell/affiche:ValueError": [2, 1793000000]}, "erreurs_bot": {"bot/x:KeyError": [1, 1793000001]},
        "catalogue_depart": {"types": 9, "elements": 120, "refuses": 0, "quand": 1793000000},
        "evenements": {"pret": True, "publications": 4, "erreurs": 0},
        "cadeaux_en_cours": 1, "cadeaux_detail": [{"msg_min": 10, "inscrits": 12}],
        "accueil": {"quand": 1793000000, "lignes": 2, "membres": 812, "mention": True},
        "tickets_vus": {"dernier": {"ticket": 412, "quand": 1, "erreurs": 0, "detail": ["ajout fondateur : 403 Forbidden"]}},
        "sante_salons": {"verifies": 12, "problemes": ["mod_log_channel (TextChannel) : écrire"]},
        "vocaux_hubs": ["rell", "clover"], "faq_trouve": {"ticket": True, "jeux": {"rell": {"trade": False}}},
        "roles_zones_manquants": {"rell": 0}, "x": FONDATEUR, "par_membre": {str(DIRECTION): 3},
        "cadeaux_elagage": {"le": "2026-10-19T14:05:00+00:00", "retires": 4}})

    async def scenario(c):
        return await _json(await c.get("/stats"))
    st, d = site.http(scenario)
    texte = json.dumps(d, ensure_ascii=False)
    t = d["travaux"]
    assert st == 200
    for interdit in (str(FONDATEUR), str(DIRECTION), "Forbidden", "mod_log_channel", "cadeaux_detail", "clover",
                     "écrire"):
        assert interdit not in texte, f"/stats ne montre jamais : {interdit}"
    assert t["demarrage"] == {"etapes_ratees": ["tableau"]} and t["erreurs_ui"] == {"site/api.rell/affiche:ValueError": [2, 1793000000]}
    assert t["erreurs_bot"] == {"bot/x:KeyError": [1, 1793000001]} and t["catalogue_depart"]["elements"] == 120
    assert t["evenements"] == {"pret": True, "publications": 4, "erreurs": 0} and t["logs_direction"] is True
    assert t["commu_salons"] == 3 and t["sante_salons"] == {"verifies": 12, "problemes": 1} and t["vocaux_hubs"] == 2
    assert t["faq_trouve"] == {"ticket": True, "jeux": {"rell": {"trade": False}}}
    assert t["cadeaux_elagage"] == {"le": "2026-10-19T14:05:00+00:00", "retires": 4}
    assert t["tickets_vus"] == {"dernier": {"quand": 1, "erreurs": 0, "detail": 1}} and t["par_membre"] == {}
    assert "membres" not in t["accueil"] and t["accueil"]["lignes"] == 2, "la taille du serveur ne sort pas"


# ═══════════════════════════════════════════════════════════════════════════════
#  S4 — les surfaces publiques
# ═══════════════════════════════════════════════════════════════════════════════

def test_S4_transcripts_visuels_et_json_piege(site, monkeypatch):
    import transcript_store
    import visuels
    jeton = transcript_store.new_token()
    transcript_store.save_html(jeton, "<!doctype html><p>conversation</p>")
    (site.tmp / "visuels").mkdir()
    (site.tmp / "visuels" / "bandeau.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    monkeypatch.setattr(visuels, "DOSSIER", site.tmp / "visuels")
    appels = []

    async def moderer(g, auteur, corps):
        appels.append(corps)
        return True, "Fait."
    monkeypatch.setattr(tableau, "_actions", {"moderer": moderer})
    avec = site.biscuit()

    async def scenario(c):
        out = {}
        r = await c.get(f"/t/{jeton}")
        out["t"] = (r.status, r.headers.get("Cache-Control"), r.headers.get("X-Robots-Tag"), r.headers.get("X-Frame-Options"))
        r = await c.get("/v/bandeau.png")
        out["v"] = (r.status, r.headers.get("Cross-Origin-Resource-Policy"))
        out["v_refus"] = [(await c.get(f"/v/{n}")).status for n in ("..%2Fbot.py", "C:bandeau.png", "bandeau.png%00.png",
                                                                       ".bandeau.png", "bandeau.gif.py")]
        piege = "[" * 2000 + "]" * 2000
        r = await c.post("/tableau/espace/action", data=piege, headers=dict(avec, **{"Content-Type": "application/json"}))
        out["piege"] = r.status
        return out
    out = site.http(scenario)
    assert out["t"] == (200, "no-store", "noindex, nofollow, noarchive", "DENY"), "un transcript : jamais en cache"
    assert len(jeton) >= 22, "128 bits : un jeton ne se devine pas"
    assert out["v"] == (200, "cross-origin"), "un visuel public, lu par Discord"
    assert all(s == 404 for s in out["v_refus"]), out["v_refus"]
    assert out["piege"] == 400 and appels == [], "un JSON imbriqué 2 000 fois : refusé proprement (avant : 500)"


# ═══════════════════════════════════════════════════════════════════════════════
#  S5 — la trace de chaque écriture du site
# ═══════════════════════════════════════════════════════════════════════════════

def test_S5_chaque_ecriture_du_site_est_tracee_a_la_porte(site, monkeypatch):
    async def moderer(g, auteur, corps):
        if corps.get("membre") == 0:
            raise RuntimeError("Discord refuse")
        return corps.get("membre") != 9, "Membre averti." if corps.get("membre") != 9 else "Protégé."

    async def note(g, auteur, requete, corps):
        return 200, {"ok": True, "_journal": None}   # une adresse qui ne note rien elle-même : la trace, si

    async def casse(g, auteur, requete, corps):
        raise RuntimeError("moitié fait")
    monkeypatch.setattr(tableau, "_actions", {"moderer": moderer})
    tableau.monter({"t/note": {"methode": "POST", "fn": note}, "t/casse": {"methode": "POST", "fn": casse}})
    ua = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Mobile/15E148 Safari/604.1"}
    avec = dict(site.biscuit(DIRECTION), **ua)

    async def scenario(c):
        for membre in (7, 9, 0):
            await c.post("/tableau/espace/action", json={"action": "moderer", "sanction": "warn", "membre": membre},
                         headers=avec)
        await c.post("/tableau/espace/api/t/note", json={}, headers=avec)
        await c.post("/tableau/espace/api/t/casse", json={}, headers=avec)
        await c.post("/tableau/espace/sync", json={"ops": []}, headers=avec)
    site.http(scenario)
    lignes = site.sql("SELECT user_id, quoi, statut, texte, appareil FROM tableau_actions ORDER BY id")
    assert lignes == [(DIRECTION, "action/moderer", 200, "Membre averti.", "iPhone · Safari"),
                      (DIRECTION, "action/moderer", 409, "Protégé.", "iPhone · Safari"),
                      (DIRECTION, "action/moderer", 500, "L'action n'a pas pu être faite.", "iPhone · Safari"),
                      (DIRECTION, "t/note", 200, "t › note", "iPhone · Safari"),
                      (DIRECTION, "t/casse", 500, "en échec", "iPhone · Safari")], lignes


# ═══════════════════════════════════════════════════════════════════════════════
#  S6 + S7 — la rubrique « Sécurité » et le bouton d'urgence
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_S7_la_rubrique_securite_et_fermer_les_autres_sessions(site):
    site.g._roles[3] = Role(3, "Modération", 5, permissions=discord.Permissions(ban_members=True, kick_members=True))
    site.g.membres[7].roles.append(site.g._roles[3])
    site.g._roles[3].members.append(site.g.membres[7])
    site.g.me = Obj(id=999, top_role=Role(2, "GoRP Bot", 50),
                    guild_permissions=discord.Permissions(manage_roles=True, view_audit_log=True))
    pc = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36"}
    tel = {"User-Agent": "Mozilla/5.0 (Linux; Android 15) Chrome/141.0 Mobile Safari/537.36"}
    eq = _equipage(site)

    async def ouvrir(c, uid, ua):
        """Le lien du bouton, comme dans Discord : la session naît avec son appareil."""
        r = await c.get(f"/tableau/{tableau.jeton(1, uid, 'tout')}", allow_redirects=False, headers=ua)
        sid = r.cookies[tableau.COOKIE].value
        return dict({"Cookie": f"{tableau.COOKIE}={sid}"}, **ORIGINE, **ua)

    async def scenario(c):
        out = {}
        fondateur_pc, fondateur_tel = await ouvrir(c, FONDATEUR, pc), await ouvrir(c, FONDATEUR, tel)
        direction, direction_2 = await ouvrir(c, DIRECTION, pc), await ouvrir(c, DIRECTION, tel)
        for h in (fondateur_pc, fondateur_tel, direction, direction_2):
            await c.get("/tableau/espace/api/securite", headers=h)
        out["fondateur"] = await _json(await c.get("/tableau/espace/api/securite", headers=fondateur_pc))
        out["direction"] = await _json(await c.get("/tableau/espace/api/securite", headers=direction))
        out["equipage"] = (await c.get("/tableau/espace/api/securite", headers=eq)).status
        out["sans_origine"] = (await c.post("/tableau/espace/api/securite/fermer_autres", json={},
                                            headers={"Cookie": direction["Cookie"]})).status
        out["fermer_direction"] = await _json(await c.post("/tableau/espace/api/securite/fermer_autres", json={},
                                                           headers=direction))
        out["apres_direction"] = [(await c.get("/tableau/espace/api/securite", headers=h)).status
                                  for h in (fondateur_pc, fondateur_tel, direction, direction_2)]
        out["fermer_fondateur"] = await _json(await c.post("/tableau/espace/api/securite/fermer_autres", json={},
                                                           headers=fondateur_pc))
        out["apres_fondateur"] = [(await c.get("/tableau/espace/api/securite", headers=h)).status
                                  for h in (fondateur_pc, fondateur_tel, direction)]
        out["equipage_apres"] = (await c.get("/tableau/equipage/api/rien", headers=eq)).status
        return out
    out = site.http(scenario)
    st, d = out["fondateur"]
    assert st == 200 and d["fondateur"] is True and d["equipage"] == 1
    sessions = {(s["qui"], s["appareil"]): s for s in d["sessions"]}
    assert set(sessions) == {(str(FONDATEUR), "Windows · Chrome"), (str(FONDATEUR), "Android · Chrome"),
                             (str(DIRECTION), "Windows · Chrome"), (str(DIRECTION), "Android · Chrome")}
    assert all(s["adresse"] == "127.0.0.x" for s in d["sessions"]), "le fondateur voit l'adresse approximative de tous"
    assert sum(s["moi"] for s in d["sessions"]) == 1 and sessions[(str(FONDATEUR), "Windows · Chrome")]["moi"]
    assert all(s["vue"] >= s["ouverte"] > 0 for s in d["sessions"])
    roles = {r["nom"]: r for r in d["permissions"]["roles"]}
    assert roles["Modération"]["permissions"] == ["Bannir", "Expulser"] and roles["Modération"]["membres"] == ["7"]
    assert d["permissions"]["audit"] is True and d["personnes"]["7"]["nom"] == "Kolax"
    assert [r["cle"] for r in d["refus"]] == list(securite_site.REFUS)
    _st, dd = out["direction"]
    assert all(s["adresse"] == "" for s in dd["sessions"] if s["qui"] == str(FONDATEUR)), \
        "la direction ne voit pas l'adresse du fondateur"
    assert all(s["adresse"] for s in dd["sessions"] if s["qui"] == str(DIRECTION))
    assert out["equipage"] == 403 and out["sans_origine"] == 400
    assert out["fermer_direction"] == (200, {"ok": True, "fermees": 1}), "la direction ferme SES autres sessions"
    assert out["apres_direction"] == [200, 200, 200, 403]
    assert out["fermer_fondateur"] == (200, {"ok": True, "fermees": 2}), "le fondateur ferme toutes les autres"
    assert out["apres_fondateur"] == [200, 403, 403], "la sienne reste ouverte"
    assert out["equipage_apres"] in (404, 200), "le site de l'équipage n'est pas touché"
    traces = site.sql("SELECT quoi, statut FROM tableau_actions ORDER BY id")
    assert traces == [("securite/fermer_autres", 200), ("securite/fermer_autres", 200)]


# ═══════════════════════════════════════════════════════════════════════════════
#  S8 — aucune fausse alerte ; un signal fort, regroupé
# ═══════════════════════════════════════════════════════════════════════════════

def test_S8_la_tete_jamais_alertee_un_signal_fort_regroupe(tmp_path, monkeypatch):
    """Décision du fondateur : une alerte SEULEMENT pour une action privilégiée qui ABOUTIT hors de la tête. Une lecture
    hors de la tête : un fait visible (Sécurité), jamais une alerte ; une action refusée ou en échec : rien ; la tête,
    quoi qu'elle fasse : rien."""
    site = Site(tmp_path, monkeypatch, peut_agir={9})   # une porte trop large : quelqu'un hors de la tête y entre
    securite_site.remettre_a_zero()
    cartes = []

    async def envoyer(g, titre, texte):
        cartes.append((titre, texte))
        return True
    securite_site.setup(envoyer=envoyer)

    async def note(g, auteur, requete, corps):
        if corps.get("refus"):
            return 409, {"erreur": "Refusé."}
        if corps.get("casse"):
            raise RuntimeError("en panne")
        return 200, {"ok": True, "_journal": {"texte": "Note posée"}}

    async def moderer(g, auteur, corps):
        return corps.get("membre") != 8, "Fait." if corps.get("membre") != 8 else "Protégé."
    tableau.monter({"t/note": {"methode": "POST", "fn": note}})
    monkeypatch.setattr(tableau, "_actions", {"moderer": moderer})
    try:
        tete, intrus = site.biscuit(FONDATEUR), site.biscuit(9)

        async def scenario(c, h, n_ok):
            for _ in range(3):
                await c.get("/tableau/espace/api/securite", headers=h)
            await c.post("/tableau/espace/api/t/note", json={"refus": True}, headers=h)
            await c.post("/tableau/espace/api/t/note", json={"casse": True}, headers=h)
            await c.post("/tableau/espace/action", json={"action": "moderer", "sanction": "warn", "membre": 8}, headers=h)
            for _ in range(n_ok):
                await c.post("/tableau/espace/api/t/note", json={}, headers=h)
            await c.post("/tableau/espace/action", json={"action": "moderer", "sanction": "warn", "membre": 7}, headers=h)
        site.http(lambda c: scenario(c, tete, 3))
        assert cartes == [] and not securite_site._alertes, "la tête : jamais une alerte, quoi qu'elle fasse"
        assert not [x for x in site.journal() if x["categorie"] == "Sécurité"], "ni un fait"
        #  Hors de la tête : des lectures, des refus, un échec — aucune carte.
        site.http(lambda c: _sans_reussite(c, intrus))
        assert cartes == [], "une lecture, un refus, un échec hors de la tête : jamais une alerte"
        faits = [x for x in site.journal() if x["type"] == "site.hors_tete"]
        assert len(faits) == 1 and faits[0]["auteur_id"] == 9 and faits[0]["gravite"] == 1, \
            "la lecture : un fait VISIBLE dans la rubrique, une ligne par session et par 10 minutes"
        #  Puis des actions qui ABOUTISSENT : la première alerte part tout de suite, les suivantes attendent, regroupées.
        site.http(lambda c: scenario(c, intrus, 3))
        assert len(cartes) == 1 and "hors de la tête" in cartes[0][0] and "Intrus (9)" in cartes[0][1], \
            "la première tout de suite, les suivantes regroupées (jamais de rafale)"
        e = securite_site._alertes[(1, "hors_tete")]
        assert e["n"] == 3 and e["tache"] is not None, "trois actions de plus attendent la carte regroupée"
        lignes = [x for x in site.journal() if x["categorie"] == "Sécurité" and x["type"].startswith("securite.")]
        assert [x["type"] for x in lignes] == ["securite.hors_tete"] and lignes[0]["auteur_id"] == 9
        assert not [x for x in site.journal() if x["auteur_id"] == FONDATEUR and x["categorie"] == "Sécurité"]
        #  La carte regroupée part à la fin du délai, en une fois.
        monkeypatch.setattr(securite_site, "ALERTE_DELAI", 0)

        async def regroupee():
            await securite_site._plus_tard(site.g, "hors_tete", "Une action du site a abouti hors de la tête", 0)
        asyncio.run(regroupee())
        assert len(cartes) == 2 and cartes[1][1].count("·") == 3
    finally:
        securite_site.remettre_a_zero()
        securite_site.setup(envoyer=None)


async def _sans_reussite(c, h):
    """Des lectures, une écriture refusée, une écriture en échec, une action refusée : rien n'aboutit."""
    for _ in range(3):
        await c.get("/tableau/espace/api/securite", headers=h)
    await c.post("/tableau/espace/api/t/note", json={"refus": True}, headers=h)
    await c.post("/tableau/espace/api/t/note", json={"casse": True}, headers=h)
    await c.post("/tableau/espace/action", json={"action": "moderer", "sanction": "warn", "membre": 8}, headers=h)


# ═══════════════════════════════════════════════════════════════════════════════
#  S9 — le journal d'audit : une permission dangereuse donnée hors de la tête
# ═══════════════════════════════════════════════════════════════════════════════

def _entree(action, user_id, avant=None, apres=None, cible=None, extra=None, g=None):
    return Obj(action=action, user_id=user_id, user=None, guild=g, target=cible, extra=extra,
               changes=Obj(before=Obj(**(avant or {})), after=Obj(**(apres or {}))))


def test_S9_journal_d_audit_permission_dangereuse_hors_de_la_tete(tmp_path, monkeypatch):
    site = Site(tmp_path, monkeypatch)
    securite_site.remettre_a_zero()
    cartes = []

    async def envoyer(g, titre, texte):
        cartes.append((titre, texte))
        return True
    securite_site.setup(envoyer=envoyer)
    A = discord.AuditLogAction
    g = site.g
    g.me = Obj(id=999)
    admin = Role(60, "Admin", 9, permissions=discord.Permissions(administrator=True))
    g._roles[60] = admin
    mod = Role(61, "Modo", 3)
    g._roles[61] = mod
    P = discord.Permissions
    try:
        cas = {
            "role_update_intrus": _entree(A.role_update, 9, {"permissions": P(manage_messages=True)},
                                          {"permissions": P(manage_messages=True, ban_members=True)}, cible=mod, g=g),
            "role_update_tete": _entree(A.role_update, DIRECTION, {"permissions": P.none()},
                                        {"permissions": P(administrator=True)}, cible=mod, g=g),
            "role_update_bot": _entree(A.role_update, 999, {"permissions": P.none()},
                                       {"permissions": P(administrator=True)}, cible=mod, g=g),
            "role_update_anodin": _entree(A.role_update, 9, {"permissions": P.none()},
                                          {"permissions": P(manage_messages=True)}, cible=mod, g=g),
            "role_create": _entree(A.role_create, 9, {}, {"permissions": P(manage_webhooks=True)}, cible=mod, g=g),
            "membre": _entree(A.member_role_update, 9, {"roles": []}, {"roles": [Obj(id=60)]},
                              cible=g.membres[7], g=g),
            "salon": _entree(A.overwrite_update, 9, {"allow": P(send_messages=True)},
                             {"allow": P(send_messages=True, manage_webhooks=True)}, cible=Obj(name="annonces"),
                             extra=g.membres[8], g=g),
        }
        phrases = {k: securite_site.examiner_entree(e, TETE, 999) for k, e in cas.items()}
        assert phrases["role_update_tete"] is None and phrases["role_update_bot"] is None, "ni la tête, ni le bot"
        assert phrases["role_update_anodin"] is None, "une permission ordinaire n'est pas un signal"
        assert "« Bannir » au rôle Modo" in phrases["role_update_intrus"] and "Intrus (9)" in phrases["role_update_intrus"]
        assert "Gérer les webhooks" in phrases["role_create"]
        assert "le rôle Admin (Administrateur) à Kolax" in phrases["membre"]
        assert "« Gérer les webhooks » dans #annonces à Mira" in phrases["salon"]

        async def scenario():
            for k in ("role_update_tete", "role_update_intrus", "membre"):
                await securite_site.sur_entree_audit(cas[k], TETE)
        asyncio.run(scenario())
        assert len(cartes) == 1 and "permission dangereuse" in cartes[0][0], "une carte, la suivante regroupée"
        assert securite_site._alertes[(1, "permission")]["n"] == 1
    finally:
        securite_site.remettre_a_zero()
        securite_site.setup(envoyer=None)


def test_S9b_bot_py_branche_l_audit_et_l_alerte_forte():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "bot.py").read_text(encoding="utf-8")
    assert "await securite_site.sur_entree_audit(entry, TETE_IDS)" in src
    assert "securite_site.setup(envoyer=_alerte_forte_site)" in src
    debut = src.index("async def _alerte_forte_site(")
    corps = src[debut:src.index("\nclass BoutonGere", debut)]
    code = corps.split(chr(34) * 3, 2)[2]   # sans la docstring
    assert "users=[discord.Object(id=SUPER_OWNER_ID)]" in code and "content=" not in code
    assert "remove_roles" not in code and "edit(" not in code, "jamais rien de retiré"
