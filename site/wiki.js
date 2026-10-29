// wiki.js — le Grimoire de RELL Seas, le wiki public du clan (29/10/2026). Données : GET /wiki/donnees. FR · EN.
// Sept rubriques en onglets (#accueil, #jeu, #monde, #lore, #fiches, #actus, #liens) : sur téléphone, on ne défile plus
// dans le vide. Seul le VÉRIFIÉ est montré (le serveur trie) ; chaque affirmation renvoie à sa source officielle.
// Les freins à la copie ralentissent la copie facile ; ils ne rendent rien invisible à qui le veut vraiment.

const ICONES = { metier: "⚒", race: "🧬", faction: "⚑", mer: "🌊", trait: "✦", classe: "⚔", fruit: "🍈", haki: "🌀",
  carte_haki: "🂠", poster: "📜", style: "🥋", arme: "🗡", equipement: "🧭", navire: "⛵", piece_navire: "💣", monture: "🐾",
  monnaie: "🪙", boss: "☠", lieu: "🏝", systeme: "⚙" };
const ONGLETS = [["accueil", "⚓"], ["jeu", "🎮"], ["monde", "🗺"], ["lore", "📖"], ["fiches", "📜"], ["actus", "🎬"], ["liens", "🔗"]];
const T = {
  fr: { onglets: { accueil: "Accueil", jeu: "Le jeu", monde: "Le monde", lore: "Lore", fiches: "Fiches", actus: "Actus & vidéos", liens: "Liens officiels" },
    sous: "Le wiki vérifié du clan", titre1: "Le grimoire de", accroche: "Tout ce que RELL a vraiment montré de RELL Seas — fruits, races, Haki, navires, boss, lore — vérifié une fiche à la fois, source officielle à l'appui.",
    explorer: "Ouvrir le grimoire", rejoindre: "Rejoindre le clan", fiches: "fiches vérifiées", favoris: "favoris sur Roblox", groupe: "membres du groupe officiel", discord: "sur le Discord officiel",
    commencer: "Par où commencer", resumes: { jeu: "Le studio, l'état du jeu, son histoire depuis RELL Piece.", monde: "Mers, factions, races, lieux et boss.", lore: "Les personnages et les histoires racontés par RELL.", fiches: "Toutes les fiches vérifiées, par pancarte.", actus: "Les 52 vidéos officielles et Movie 3 minute par minute.", liens: "Les chaînes, Discord et groupes officiels." },
    derniere: "Dernière vidéo officielle", vues: "vues", technique: "Fiche technique", dev: "Développeur", proprio: "Propriétaires", plateforme: "Plateforme", statutJeu: "Statut", pasPublic: "Pas encore public",
    favorisR: "Favoris (Roblox)", groupeR: "Groupe RELL Seas", studioR: "Groupe RELL GAMES", discordR: "Discord RELL Seas", enLigne: "en ligne", aSavoir: "À savoir", histoire: "L'histoire du projet", systemes: "Les systèmes du jeu",
    createurs: "Les créateurs", mers: "Les mers", factions: "Les factions", races: "Les races", lieux: "Lieux", boss: "Les boss", ilesNote: "Le nombre exact de mers et d'îles n'a pas encore été annoncé officiellement : seules les mers nommées par RELL sont listées.",
    loreIntro: "Ce que RELL raconte lui-même : chaque ligne vient d'une vidéo officielle, citée.", source: "Source", regarder: "Regarder",
    categories: "Les pancartes du port", tout: "Toutes", chercher: "Chercher une fiche (nom français ou anglais)…", sans: "Aucune fiche ne correspond.", choisir: "Choisis une pancarte, ou cherche une fiche.", retour: "← Toutes les pancartes",
    preuve: "Vu dans", m3: "Movie 3", verifie: "Vérifié", fermer: "Fermer", actusTitre: "Les vidéos officielles", m3Titre: "Movie 3, minute par minute",
    m3Note: "Les termes du jeu prononcés dans RELL Seas: The Movie 3 (sous-titres de la vidéo) : un clic, et la vidéo s'ouvre à la bonne minute.", toutes: "Toutes", plus: "Voir toutes les vidéos", liensIntro: "Seulement les comptes tenus par RELL. Méfie-toi de tout autre lien qui promet le jeu.",
    chiffresNote: (d) => `Chiffres publics relevés le ${d}.`, fondateur: "Fondateur", direction: "Direction",
    regle: "Ici, jamais de rumeur ni de « comment l'obtenir » : le jeu n'est pas encore sorti, et personne ne le sait vraiment.",
    droits: (c) => `Wiki non officiel réalisé par le clan ${c} : textes, tri et mise en page © ${c}, reproduction interdite sans accord. RELL Seas, ses noms et ses images (illustrations des vidéos officielles) appartiennent à RELL Games.` },
  en: { onglets: { accueil: "Home", jeu: "The game", monde: "The world", lore: "Lore", fiches: "Entries", actus: "News & videos", liens: "Official links" },
    sous: "The clan's verified wiki", titre1: "The grimoire of", accroche: "Everything RELL has really shown of RELL Seas — fruits, races, Haki, ships, bosses, lore — verified one entry at a time, with an official source.",
    explorer: "Open the grimoire", rejoindre: "Join the clan", fiches: "verified entries", favoris: "favourites on Roblox", groupe: "official group members", discord: "on the official Discord",
    commencer: "Where to start", resumes: { jeu: "The studio, the game's status, its story since RELL Piece.", monde: "Seas, factions, races, places and bosses.", lore: "The characters and stories told by RELL.", fiches: "Every verified entry, by sign.", actus: "The 52 official videos and Movie 3 minute by minute.", liens: "The official channels, Discords and groups." },
    derniere: "Latest official video", vues: "views", technique: "Key facts", dev: "Developer", proprio: "Owners", plateforme: "Platform", statutJeu: "Status", pasPublic: "Not public yet",
    favorisR: "Favourites (Roblox)", groupeR: "RELL Seas group", studioR: "RELL GAMES group", discordR: "RELL Seas Discord", enLigne: "online", aSavoir: "Good to know", histoire: "The project's story", systemes: "Game systems",
    createurs: "The creators", mers: "The seas", factions: "Factions", races: "Races", lieux: "Places", boss: "Bosses", ilesNote: "The exact number of seas and islands hasn't been officially announced yet: only the seas named by RELL are listed.",
    loreIntro: "What RELL tells itself: every line comes from an official video, quoted.", source: "Source", regarder: "Watch",
    categories: "The harbour signs", tout: "All", chercher: "Search an entry (French or English name)…", sans: "No entry matches.", choisir: "Pick a sign, or search an entry.", retour: "← All signs",
    preuve: "Shown in", m3: "Movie 3", verifie: "Verified", fermer: "Close", actusTitre: "Official videos", m3Titre: "Movie 3, minute by minute",
    m3Note: "Game terms spoken in RELL Seas: The Movie 3 (video subtitles): one click opens the video at the right minute.", toutes: "All", plus: "See all videos", liensIntro: "Only accounts run by RELL. Beware of any other link promising the game.",
    chiffresNote: (d) => `Public figures as of ${d}.`, fondateur: "Founder", direction: "Leadership",
    regle: "Never rumours nor “how to get it” here: the game isn't out yet, and nobody really knows.",
    droits: (c) => `Unofficial wiki made by the ${c} clan: texts, sorting and layout © ${c}, no reproduction without permission. RELL Seas, its names and images (official video artwork) belong to RELL Games.` } };

let toutesVideos = false;
let D = null, langue = (navigator.language || "fr").toLowerCase().startsWith("fr") ? "fr" : "en", filtre = "", q = "", minuteur = 0, chaine = "";
try { const l = localStorage.getItem("wiki-langue"); if (l === "fr" || l === "en") langue = l; } catch (_e) { /* navigation privée */ }

function el(tag, attrs, ...enfants) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "classe") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? "" : v);
  }
  for (const e of enfants.flat()) if (e != null && e !== false) n.append(e.nodeType ? e : document.createTextNode(String(e)));
  return n;
}
const t = () => T[langue];
const plier = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
const src = (chemin) => "/tableau/espace/" + String(chemin || "").replace(/["\\]/g, "");
const fondDe = (chemin, petit) => (chemin ? `url("${src(chemin)}${petit ? "_p" : ""}.webp")` : "");
const nom = (e) => (langue === "fr" ? e.nom : e.nom_en);
const nombre = (n) => (n == null ? "—" : Number(n).toLocaleString(langue === "fr" ? "fr-FR" : "en-US"));
const lien = (url, ...enfants) => el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, ...enfants);
const ongletActif = () => { const h = (location.hash || "").slice(1); return ONGLETS.some(([k]) => k === h) ? h : "accueil"; };
const titreSection = (txt) => el("h2", { classe: "w-section revele" }, txt);
function fond(elm, chemin, petit) { if (chemin) elm.style.backgroundImage = fondDe(chemin, petit); return elm; }

function image(e) {
  const b = el("span", { classe: "w-image" + (e.image ? "" : " vide"), "aria-hidden": "true" });
  if (e.image) b.style.backgroundImage = `url("${src(e.image)}")`;   // en fond : pas d'« enregistrer l'image »
  else b.textContent = ICONES[e.type] || "✦";
  return b;
}

function carte(e, grande) {
  return el("button", { type: "button", classe: "w-carte revele" + (grande ? " grande" : ""), onclick: () => fiche(e) }, image(e),
    el("span", { classe: "w-carte-texte" },
      el("span", { classe: "w-nom" }, nom(e)),
      langue === "fr" && e.nom !== e.nom_en ? el("span", { classe: "w-nom-en" }, e.nom_en) : null,
      el("span", { classe: "w-resume" }, e[langue]),
      el("span", { classe: "w-badges" }, el("span", { classe: "w-badge" }, "✓ " + t().verifie), e.m3 ? el("span", { classe: "w-badge m3" }, t().m3) : null)));
}

function fiche(e) {
  const ty = D.types.find((x) => x.cle === e.type) || {};
  const voile = el("div", { classe: "w-fond", role: "dialog", "aria-modal": "true", "aria-label": nom(e), onclick: (ev) => { if (ev.target === voile) fermer(); } });
  const bandeau = fond(el("div", { classe: "w-fiche-bandeau" }), (e.preuves && e.preuves[0] && e.preuves[0].fond) || ty.fond);
  const btn = el("button", { type: "button", classe: "w-fermer", "aria-label": t().fermer, onclick: () => fermer() }, "×");
  voile.append(el("div", { classe: "w-fiche" }, bandeau, btn,
    el("div", { classe: "w-fiche-corps" },
      el("div", { classe: "w-fiche-tete" }, image(e),
        el("div", {}, el("h2", {}, nom(e)),
          el("div", { classe: "w-nom-en" }, [ty[langue], e.groupe, langue === "fr" && e.nom !== e.nom_en ? e.nom_en : ""].filter(Boolean).join(" · ")))),
      el("p", { classe: "w-fiche-texte" }, e[langue]),
      ...(e.preuves || []).map((p) => el("div", { classe: "w-preuve" },
        el("span", {}, el("span", { classe: "w-sceau", "aria-hidden": "true" }), `${t().preuve} « ${p.titre} » · ${p.minute}`),
        el("a", { classe: "w-lien", href: p.url, target: "_blank", rel: "noopener noreferrer" }, "▶ " + t().regarder))))));
  document.body.append(voile);
  document.body.classList.add("w-bloque");
  btn.focus();
  const echap = (ev) => { if (ev.key === "Escape") fermer(); };
  document.addEventListener("keydown", echap);
  function fermer() { voile.remove(); document.body.classList.remove("w-bloque"); document.removeEventListener("keydown", echap); }
}

// ── Accueil ──
function vueAccueil() {
  const c = D.credits || {}, ch = D.chiffres || {};
  const fonds = el("div", { classe: "w-heros-fonds", "aria-hidden": "true" },
    (D.heros || []).map((h, i) => fond(el("span", { classe: "w-heros-fond" + (i === 0 ? " actif" : "") }), h.fond)));
  const pancarte = (val, lib) => el("div", { classe: "w-pancarte" }, el("span", { classe: "w-clou" }), el("strong", {}, val), el("span", {}, lib));
  const derniere = (D.actus || [])[0];
  return [
    el("section", { classe: "w-heros" }, fonds, el("div", { classe: "w-vagues", "aria-hidden": "true" }),
      el("div", { classe: "w-heros-contenu" },
        el("div", { classe: "w-affiche" },
          el("span", { classe: "w-ruban" }, t().sous + " " + (c.clan || "GoRP SEA")),
          el("span", { classe: "w-affiche-haut" }, t().titre1),
          el("h1", { classe: "w-affiche-titre" }, "RELL Seas"),
          el("p", { classe: "w-accroche" }, t().accroche),
          el("div", { classe: "w-actions" },
            el("a", { classe: "w-bouton laiton", href: "#fiches" }, "📖 " + t().explorer),
            c.discord ? el("a", { classe: "w-bouton bois", href: c.discord, target: "_blank", rel: "noopener noreferrer" }, "⚓ " + t().rejoindre) : null)),
        el("div", { classe: "w-pancartes" }, pancarte(nombre(D.entrees.length), t().fiches), pancarte(nombre(ch.favoris), t().favoris),
          pancarte(nombre(ch.groupe), t().groupe), pancarte(nombre(ch.discord), t().discord)))),
    el("div", { classe: "w-feuille" },
      titreSection(t().commencer),
      el("div", { classe: "w-portes" }, ONGLETS.filter(([k]) => k !== "accueil").map(([k, ic], i) =>
        fond(el("a", { classe: "w-porte revele", href: "#" + k },
          el("span", { classe: "w-porte-icone" }, ic), el("strong", {}, t().onglets[k]), el("span", {}, t().resumes[k])),
        (D.heros || [])[i % Math.max(1, (D.heros || []).length)]?.fond, true))),
      derniere ? [titreSection("🎬 " + t().derniere), videoGrande(derniere)] : null)];
}

function videoGrande(v) {
  return lien(v.url, fond(el("span", { classe: "w-video-une-image" }, el("span", { classe: "w-lecture grand" }, "▶")), v.fond),
    el("span", { classe: "w-video-une-texte" }, el("strong", {}, v.titre),
      el("span", { classe: "w-nom-en" }, [v.date, v.chaine, v.duree, nombre(v.vues) + " " + t().vues].filter(Boolean).join(" · ")),
      v.extrait ? el("span", {}, v.extrait) : null));
}

// ── Le jeu ──
function vueJeu() {
  const P = (D.pages || {}).jeu || {}, ch = D.chiffres || {};
  const ligne = (k, v) => el("div", { classe: "w-tech-ligne" }, el("span", {}, k), el("strong", {}, v));
  const sys = D.entrees.filter((e) => e.type === "systeme");
  return el("div", { classe: "w-feuille" },
    titreSection("🎮 " + t().onglets.jeu),
    el("div", { classe: "w-deux" },
      el("div", {}, el("p", { classe: "w-chapeau revele" }, (P.intro || {})[langue] || ""),
        P.statut ? el("div", { classe: "w-avis revele" }, el("strong", {}, "⚠ " + t().statutJeu + " : " + t().pasPublic), el("p", {}, P.statut[langue]),
          lien(P.statut.source, t().source + " : " + P.statut.source_titre)) : null),
      el("div", { classe: "w-tech revele" }, el("h3", {}, t().technique),
        ligne(t().dev, "RELL Games"), ligne(t().proprio, "RELLbad & RELLsin"), ligne(t().plateforme, "Roblox"), ligne(t().statutJeu, t().pasPublic),
        ligne(t().favorisR, nombre(ch.favoris)), ligne(t().groupeR, nombre(ch.groupe)), ligne(t().studioR, nombre(ch.studio)),
        ligne(t().discordR, nombre(ch.discord) + (ch.discord_en_ligne ? ` (${nombre(ch.discord_en_ligne)} ${t().enLigne})` : "")),
        el("p", { classe: "w-note" }, t().chiffresNote(ch.releve || "")))),
    titreSection(t().aSavoir),
    el("ul", { classe: "w-points" }, (P.points || []).map((x) => el("li", { classe: "revele" }, lien(x.url, x[langue])))),
    titreSection(t().histoire),
    el("ol", { classe: "w-frise" }, (P.histoire || []).map((x) => el("li", { classe: "revele" }, el("span", { classe: "w-frise-date" }, x.date.slice(0, 7)),
      lien(x.url, x[langue])))),
    sys.length ? [titreSection(t().systemes), el("div", { classe: "w-grille" }, sys.map((e) => carte(e)))] : null);
}

// ── Le monde ──
function vueMonde() {
  const bloc = (titre, type) => { const l = D.entrees.filter((e) => e.type === type); return l.length ? [titreSection(titre), el("div", { classe: "w-grille" }, l.map((e) => carte(e)))] : null; };
  return el("div", { classe: "w-feuille" }, titreSection("🗺 " + t().onglets.monde),
    el("p", { classe: "w-note revele" }, t().ilesNote),
    bloc(t().mers, "mer"), bloc(t().factions, "faction"), bloc(t().races, "race"), bloc(t().lieux, "lieu"), bloc(t().boss, "boss"));
}

// ── Lore ──
function vueLore() {
  const P = D.pages || {};
  return el("div", { classe: "w-feuille" }, titreSection("📖 " + t().onglets.lore), el("p", { classe: "w-chapeau revele" }, t().loreIntro),
    el("div", { classe: "w-lore" }, (P.lore || []).map((x) => fond(el("article", { classe: "w-recit revele" },
      el("div", { classe: "w-recit-texte" }, el("h3", {}, x.nom), el("p", {}, x[langue]), lien(x.url, "▶ " + t().regarder))), x.fond, true))),
    titreSection(t().createurs),
    el("div", { classe: "w-createurs" }, (P.createurs || []).map((x) => el("div", { classe: "w-createur revele" }, el("strong", {}, x.nom), el("span", {}, x[langue])))));
}

// ── Fiches ──
function vueFiches() {
  const zone = el("div", { classe: "w-feuille" });
  const dessinerF = () => {
    const recherche = el("input", { classe: "w-recherche", type: "search", placeholder: t().chercher, value: q, "aria-label": t().chercher,
      oninput: (ev) => { q = ev.target.value; liste(); } });
    const corps = el("div", {});
    zone.replaceChildren(titreSection("📜 " + t().categories), recherche, corps);
    function liste() {
      const sel = D.entrees.filter((e) => (!filtre || e.type === filtre) && (!q || plier([e.nom, e.nom_en, e.fr, e.en].join(" ")).includes(plier(q))));
      if (!filtre && !q) { corps.replaceChildren(enseignes()); return; }
      const ty = D.types.find((x) => x.cle === filtre);
      const entete = filtre ? fond(el("div", { classe: "w-rubrique" }, el("span", {}, ty ? ty[langue] : ""), el("span", { classe: "w-rubrique-nb" }, String(sel.length))), ty && ty.fond, true) : null;
      corps.replaceChildren(el("button", { type: "button", classe: "w-retour", onclick: () => { filtre = ""; q = ""; dessinerF(); } }, t().retour), entete || "",
        sel.length ? el("div", { classe: "w-grille" }, sel.map((e) => carte(e))) : el("p", { classe: "w-attente" }, t().sans));
      animer(corps);
    }
    function enseignes() {
      return el("div", { classe: "w-enseignes" }, D.types.map((ty) => {
        const nb = D.entrees.filter((e) => e.type === ty.cle).length;
        const img = el("span", { classe: "w-enseigne-image" + (ty.icone ? "" : " vide"), "aria-hidden": "true" }, ty.icone ? "" : (ICONES[ty.cle] || "✦"));
        if (ty.icone) img.style.backgroundImage = `url("${src(ty.icone)}")`;
        const pl = el("span", { classe: "w-planchette" }, img, el("span", { classe: "w-enseigne-nom" }, ty[langue]), el("span", { classe: "w-enseigne-nb" }, String(nb)));
        if (ty.fond) pl.style.setProperty("--fond", fondDe(ty.fond, true));
        return el("button", { type: "button", classe: "w-enseigne revele", onclick: () => { filtre = ty.cle; q = ""; dessinerF(); window.scrollTo({ top: 0, behavior: "smooth" }); } },
          el("span", { classe: "w-corde", "aria-hidden": "true" }), pl);
      }));
    }
    liste();
    if (q) { recherche.focus(); recherche.setSelectionRange(q.length, q.length); }
  };
  dessinerF();
  return zone;
}

// ── Actus & vidéos ──
function vueActus() {
  const zone = el("div", { classe: "w-feuille" });
  const dessinerA = () => {
    const tout = (D.actus || []).filter((v) => !chaine || v.chaine === chaine);
    const l = toutesVideos ? tout : tout.slice(0, 12);
    const puce = (k, lib) => el("button", { type: "button", classe: "w-puce", "aria-pressed": String(chaine === k), onclick: () => { chaine = k; dessinerA(); } }, lib);
    zone.replaceChildren(
      titreSection("🎞 " + t().m3Titre), el("p", { classe: "w-note" }, t().m3Note),
      el("div", { classe: "w-m3" }, (D.movie3 || []).map((b) => el("div", { classe: "w-m3-bloc revele" }, el("span", { classe: "w-m3-temps" }, b.de),
        el("div", { classe: "w-m3-termes" }, b.termes.map((x) => lien(x.url, x.nom + " · " + x.minute)))))),
      titreSection("🎬 " + t().actusTitre),
      el("div", { classe: "w-puces" }, puce("", t().toutes), puce("RELLGames", "RELLGames"), puce("CaribBros", "CaribBros")),
      el("div", { classe: "w-videos" }, l.map((v) => lien(v.url,
        fond(el("span", { classe: "w-video-image" }, el("span", { classe: "w-lecture" }, "▶"), v.duree ? el("span", { classe: "w-duree" }, v.duree) : null), v.fond, true),
        el("span", { classe: "w-video-titre" }, v.titre),
        el("span", { classe: "w-nom-en" }, [v.date, v.chaine, nombre(v.vues) + " " + t().vues].join(" · "))))),
      tout.length > l.length ? el("button", { type: "button", classe: "w-bouton laiton w-plus", onclick: () => { toutesVideos = true; dessinerA(); } },
        `${t().plus} (${tout.length})`) : null);
    zone.querySelectorAll(".w-videos > a").forEach((a) => a.classList.add("w-video", "revele"));
    animer(zone);
  };
  dessinerA();
  return zone;
}

// ── Liens officiels ──
function vueLiens() {
  const P = D.pages || {};
  return el("div", { classe: "w-feuille" }, titreSection("🔗 " + t().onglets.liens), el("p", { classe: "w-chapeau revele" }, t().liensIntro),
    el("div", { classe: "w-liens" }, (P.liens || []).map((x) => lien(x.url, el("strong", {}, x.nom), el("span", {}, x[langue]), el("span", { classe: "w-url" }, x.url.replace("https://", ""))))));
}

const VUES = { accueil: vueAccueil, jeu: vueJeu, monde: vueMonde, lore: vueLore, fiches: vueFiches, actus: vueActus, liens: vueLiens };

function nav() {
  const actif = ongletActif();
  document.getElementById("w-nav").replaceChildren(...ONGLETS.map(([k, ic]) =>
    el("a", { href: "#" + k, classe: "w-onglet", "aria-current": k === actif ? "page" : null }, el("span", { "aria-hidden": "true" }, ic), t().onglets[k])));
  const a = document.querySelector(".w-onglet[aria-current]"); if (a) a.scrollIntoView({ block: "nearest", inline: "center" });
}

function pied() {
  const c = D.credits || {};
  return [el("div", { classe: "w-credits" },
    el("div", { classe: "w-signature" }, el("span", { classe: "w-sceau grand", "aria-hidden": "true" }),
      el("div", {}, el("div", {}, el("strong", {}, t().fondateur + " : "), c.fondateur || ""),
        (c.direction || []).length ? el("div", {}, el("strong", {}, t().direction + " : "), c.direction.join(", ")) : null,
        el("div", { classe: "w-note" }, t().regle))),
    c.discord ? el("a", { classe: "w-bouton laiton", href: c.discord, target: "_blank", rel: "noopener noreferrer" }, "⚓ " + t().rejoindre) : null),
  el("p", { classe: "w-note" }, t().droits(c.clan || "GoRP SEA"))];
}

let observateur = null;
function animer(racine) {
  if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) { racine.querySelectorAll(".revele").forEach((n) => n.classList.add("vu")); return; }
  observateur = observateur || new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("vu"); observateur.unobserve(e.target); } }), { rootMargin: "0px 0px -6% 0px" });
  racine.querySelectorAll(".revele:not(.vu)").forEach((n, i) => { n.style.transitionDelay = Math.min(i % 8, 7) * 45 + "ms"; observateur.observe(n); });
}

function dessiner() {
  const zone = document.getElementById("w-contenu"), actif = ongletActif();
  document.documentElement.lang = langue;
  document.title = (actif === "accueil" ? "" : t().onglets[actif] + " · ") + "Wiki RELL Seas";
  document.getElementById("w-sous").textContent = t().sous + " " + ((D.credits || {}).clan || "GoRP SEA");
  document.getElementById("w-langue").textContent = langue === "fr" ? "EN" : "FR";
  nav();
  const vue = VUES[actif]();
  zone.replaceChildren(...[].concat(vue).flat().filter(Boolean));
  zone.classList.remove("w-entre"); void zone.offsetWidth; zone.classList.add("w-entre");
  document.getElementById("w-pied").replaceChildren(...pied());
  animer(zone);
  clearInterval(minuteur);
  const fonds = [...document.querySelectorAll(".w-heros-fond")];
  if (fonds.length > 1 && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    let i = 0;
    minuteur = setInterval(() => { fonds[i].classList.remove("actif"); i = (i + 1) % fonds.length; fonds[i].classList.add("actif"); }, 7000);
  }
}

window.addEventListener("hashchange", () => { if (D) { dessiner(); window.scrollTo({ top: 0 }); } });

// ── Les freins à la copie ──
const bloquer = (ev) => { if (!(ev.target && ev.target.closest && ev.target.closest("input"))) ev.preventDefault(); };
["contextmenu", "dragstart", "copy", "cut", "selectstart"].forEach((n) => document.addEventListener(n, bloquer));
document.addEventListener("keydown", (ev) => {
  const k = (ev.key || "").toLowerCase(), ctrl = ev.ctrlKey || ev.metaKey;
  if (k === "f12" || (ctrl && ev.shiftKey && ["i", "j", "c", "k"].includes(k)) || (ctrl && ["u", "s", "p"].includes(k))) ev.preventDefault();
});

document.getElementById("w-langue").addEventListener("click", () => {
  langue = langue === "fr" ? "en" : "fr";
  try { localStorage.setItem("wiki-langue", langue); } catch (_e) { /* rien */ }
  if (D) dessiner();
});

fetch("/wiki/donnees", { headers: { Accept: "application/json" } }).then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
  .then((d) => { D = d; dessiner(); })
  .catch(() => { const a = document.getElementById("w-attente"); if (a) a.textContent = "Le wiki est indisponible pour le moment. · The wiki is unavailable right now."; });
