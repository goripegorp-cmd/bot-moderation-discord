// outils/controle_site.mjs — le contrôle visuel et technique du site v2 (« La Capitainerie »), sur la maquette locale.
//
// Pilote un Chrome ou un Edge SANS FENÊTRE (profil temporaire, rien n'est touché sur l'ordinateur) par le protocole
// DevTools, sans aucune dépendance (Node 22+). Pour chaque scène (rubriques, fiches, fenêtres) et chaque taille
// (375×812, 768×1024, 1366×768, 1920×1080) :
//   · ÉCHOUE si la page défile en largeur (scrollWidth > innerWidth) ou si un élément sort de l'écran ou de son
//     conteneur, si un texte déborde de sa boîte, si une cible tactile fait moins de 44 px (tailles téléphone et
//     tablette), si une image ne charge pas, s'il y a une erreur dans la console ou une violation de la CSP ;
//   · prend une capture (PNG) de la vue.
// Avec --hors-ligne : le scénario complet du service worker — la page s'ouvre en panne, une affiche est modifiée
// sans réseau, la modification attend dans la file, le serveur revient, elle part, le serveur l'a.
//
// Lancer (maquette démarrée : python outils/site_maquette.py) :
//   node outils/controle_site.mjs [--url http://localhost:8791/tableau/espace/] [--sortie <dossier>] [--scenes a,b]
//                                 [--tailles 375x812,1366x768] [--hors-ligne] [--seulement-hors-ligne] [--navigateur <exe>]
//   Le VRAI site local (python outils/site_local.py) : ajouter --url http://localhost:8790/tableau/espace/
//                                 --entree http://localhost:8790/tableau/demo   (pose la session d'abord)

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const URL_SITE = opt("url", "http://localhost:8791/tableau/espace/");
const ORIGINE = new URL(URL_SITE).origin;
const SORTIE = opt("sortie", join(tmpdir(), "capitainerie-captures"));
const TAILLES = String(opt("tailles", "375x812,768x1024,1366x768,1920x1080")).split(",").map((t) => t.split("x").map(Number));
const PORT = 9339 + Math.floor(Math.random() * 400);
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);

// Ouvrir le brouillon « Sortie en mer » (le vrai site local et la maquette en ont un) dans le composeur.
const OUVRIR_BROUILLON = "[...document.querySelectorAll('article.evt-carte')].find(a => a.textContent.includes('Sortie en mer')).querySelector('.feuillet-pied button').click()";
// La présence en direct : la carte de l'affiche tenue par l'autre personne, bien en vue ; puis son éditeur (lecture
// seule). Exécutées DANS la page (elles ne capturent rien du script).
async function voirCarteDirect() {
  for (const g of document.querySelectorAll("details.groupe")) g.open = true;
  await new Promise((r) => setTimeout(r, 500));
  const b = document.querySelector('[data-direct-objet="affiche:demo-kolax-01"]');
  if (b && b.parentElement) b.parentElement.scrollIntoView({ block: "center" });
}
async function ouvrirEditeurDirect() {
  document.querySelector('[data-direct-objet="affiche:demo-kolax-01"]').closest("button.affiche").click();
  await new Promise((r) => setTimeout(r, 1000));
  [...document.querySelectorAll("dialog[open] button")].find((x) => x.textContent.includes("Modifier")).click();
}
// ─── Le site de l'équipage ──────────────────────────────────────────────────
const EQ = { page: "/tableau/equipage/", entree: "/tableau/demo?qui=equipage" };
const EQ_TETE = { page: "/tableau/equipage/", entree: "/tableau/demo?vers=equipage" };
// Ce qu'un membre de l'équipage ne doit JAMAIS voir (aucun geste d'écriture sur son site).
const GESTES_DIRECTION = ["Modifier l'accueil", "Publier une actualité", "Ajouter un bloc", "Mettre à la corbeille", "Enregistrer", "Retirer"];
const cliquerTexte = (selecteur, texte) => "(async () => { const b = [...document.querySelectorAll(" + JSON.stringify(selecteur) + ")].find((x) => x.textContent.includes("
  + JSON.stringify(texte) + ")); if (!b) throw new Error('introuvable : ' + " + JSON.stringify(texte) + "); b.scrollIntoView({ block: 'center' }); b.click(); await new Promise((r) => setTimeout(r, 600)); })()";
const MODE_EDITION = cliquerTexte("button", "Modifier l'accueil");
const SCENES_EQUIPAGE = [
  { nom: "site-equipage-accueil", ...EQ, ancre: "#accueil", interdits: GESTES_DIRECTION },
  { nom: "site-equipage-analyses", ...EQ, ancre: "#accueil", interdits: GESTES_DIRECTION,
    geste: "(async () => { for (const g of document.querySelectorAll('.groupes-analyses details.groupe')) g.open = true; await new Promise((r) => setTimeout(r, 500)); document.querySelector('.groupes-analyses').scrollIntoView({ block: 'start' }); })()" },
  { nom: "site-equipage-actualites", ...EQ, ancre: "#accueil", interdits: GESTES_DIRECTION, geste: cliquerTexte("button", "Toutes les actualités") },
  { nom: "site-equipage-lire-actu", ...EQ, ancre: "#accueil", interdits: GESTES_DIRECTION, geste: cliquerTexte("button.lien-titre", "Grande chasse") },
  { nom: "site-equipage-equipage", ...EQ, ancre: "#equipage", interdits: GESTES_DIRECTION },
  { nom: "site-equipage-affiche", ...EQ, ancre: "#equipage", interdits: GESTES_DIRECTION, geste: "document.querySelector('button.affiche').click()" },
  { nom: "site-equipage-filtre", ...EQ, ancre: "#equipage", interdits: GESTES_DIRECTION, geste: "document.querySelector('.liste-bouton').click()" },
  { nom: "site-equipage-fiche", ...EQ, ancre: "#fiche", interdits: GESTES_DIRECTION },
  { nom: "site-equipage-sans-fiche", page: EQ.page, entree: "/tableau/demo?qui=equipage&id=1003", ancre: "#fiche", interdits: GESTES_DIRECTION },
  { nom: "site-equipage-edition", ...EQ_TETE, ancre: "#accueil", geste: MODE_EDITION },
  { nom: "site-equipage-ajouter-bloc", ...EQ_TETE, ancre: "#accueil", geste: MODE_EDITION, geste2: cliquerTexte(".barre-edition button", "Ajouter un bloc") },
  { nom: "site-equipage-editeur-bloc", ...EQ_TETE, ancre: "#accueil", geste: MODE_EDITION, geste2: cliquerTexte(".bloc-texte .barre-bloc button", "Modifier") },
  { nom: "site-equipage-editeur-honneur", ...EQ_TETE, ancre: "#accueil", geste: MODE_EDITION, geste2: cliquerTexte(".bloc-honneur .barre-bloc button", "Modifier") },
  { nom: "site-equipage-editeur-actualite", ...EQ_TETE, ancre: "#accueil", geste: cliquerTexte(".barre-edition button", "Publier une actualité") },
];

// Ouvrir la première affiche (les groupes par métier sont repliés au départ).
const OUVRIR_AFFICHE ="(async () => { const g = document.querySelector('details.groupe'); if (g && !g.open) g.open = true; await new Promise(r => setTimeout(r, 500)); document.querySelector('button.affiche').click(); })()";
// Textes & noms : ouvrir le n-ième groupe (Recrutement, Métiers, Le guide du clan, Annonces & événements, Le site).
const OUVRIR_GROUPE_TEXTES = (n) => `(async () => { const g = document.querySelectorAll('details.groupe')[${n}]; if (g && !g.open) g.open = true; await new Promise(r => setTimeout(r, 600)); return 1; })()`;

// Les scènes : une rubrique (ancre) et, au besoin, des gestes (code exécuté dans la page) avant le contrôle.
// Les icônes officielles et les logos viennent d'une autre branche (et du wiki, plus tard) : leur 404 est attendu,
// la page montre alors la pastille gravée. Ce n'est pas une faute de la page, seulement une image pas encore livrée.
const ATTENDUS_404 = /\/tableau\/espace\/s\/(icones\/rell|logos)\//;
const SCENES = [
  { nom: "port-apercu", ancre: "#port/apercu" },
  { nom: "port-journal", ancre: "#port/journal" },
  { nom: "port-sanctions", ancre: "#port/sanctions" },
  { nom: "port-tickets", ancre: "#port/tickets" },
  { nom: "port-repertoire", ancre: "#port/repertoire" },
  { nom: "port-salons-questions", ancre: "#port/salons/questions" },
  { nom: "port-salons-idees", ancre: "#port/salons/idees" },
  { nom: "port-salons-droits", ancre: "#port/salons/droits" },
  { nom: "port-nettoyage", ancre: "#port/nettoyage" },
  { nom: "equipage-membres", ancre: "#equipage/membres" },
  { nom: "equipage-fiches", ancre: "#equipage/fiches" },
  { nom: "equipage-candidatures", ancre: "#equipage/candidatures" },
  { nom: "equipage-questionnaire", ancre: "#equipage/candidatures/questionnaire" },
  { nom: "equipage-tickets", ancre: "#equipage/tickets" },
  { nom: "equipage-annonces", ancre: "#equipage/annonces" },
  { nom: "equipage-annonces-avenir", ancre: "#equipage/annonces/a-venir" },
  { nom: "equipage-annonces-brouillons", ancre: "#equipage/annonces/brouillons" },
  { nom: "equipage-annonces-passes", ancre: "#equipage/annonces/passes" },
  // Un brouillon rouvert : le formulaire rempli et l'aperçu rendu par le serveur ; puis la confirmation de publication.
  { nom: "equipage-annonces-ouvert", ancre: "#equipage/annonces/brouillons", geste: OUVRIR_BROUILLON },
  { nom: "fenetre-publier", ancre: "#equipage/annonces/brouillons", geste: OUVRIR_BROUILLON,
    geste2: "[...document.querySelectorAll('.composeur-actions button')].find(b => b.textContent.includes('Publier')).click()" },
  { nom: "capitainerie-affiches", ancre: "#capitainerie/affiches" },
  { nom: "capitainerie-catalogue", ancre: "#capitainerie/catalogue" },
  { nom: "capitainerie-roles", ancre: "#capitainerie/roles" },
  // Les fenêtres (pancartes)
  { nom: "fenetre-fiche", ancre: "#port/sanctions", geste: "document.querySelector('.feuillet.lien').click()" },
  { nom: "fenetre-conversation", ancre: "#port/tickets", geste: "[...document.querySelectorAll('button')].find(b => b.textContent.includes('Conversation')).click()" },
  // « Membre parti » pour l'auteur d'une affiche de démonstration (créée par la tête) : la page ne sait pas lire la
  // personne envoyée par le serveur (25/10 : `cree_par` est un objet { id, nom }, P() attendait un identifiant).
  { nom: "fenetre-affiche", ancre: "#capitainerie/affiches", geste: OUVRIR_AFFICHE, interdits: ["Membre parti", "[object Object]"] },
  { nom: "fenetre-editeur-affiche", ancre: "#capitainerie/affiches", geste: "[...document.querySelectorAll('button')].find(b => b.textContent.includes('Nouvelle affiche')).click()" },
  { nom: "fenetre-dossier-etape1", ancre: "#equipage/candidatures", geste: "[...document.querySelectorAll('.feuillet.lien')].find(x => x.textContent.includes('Étape 1')).click()" },
  { nom: "fenetre-dossier-correction", ancre: "#equipage/candidatures", geste: "[...document.querySelectorAll('.feuillet.lien')].find(x => x.textContent.includes('à corriger')).click()" },
  { nom: "fenetre-choix-questions", ancre: "#equipage/candidatures", geste: "[...document.querySelectorAll('.feuillet.lien')].find(x => x.textContent.includes('Étape 1')).click()",
    geste2: "[...document.querySelectorAll('dialog button')].find(b => b.textContent.includes('Passer à l')).click()" },
  { nom: "fenetre-file", ancre: "#port/apercu", geste: "document.querySelector('#plaque-etat').click()" },
  { nom: "fenetre-element-catalogue", ancre: "#capitainerie/catalogue", geste: "(async () => { const g = document.querySelector('details.groupe'); if (g && !g.open) g.open = true; await new Promise(r => setTimeout(r, 500)); document.querySelector('button.element-carte').click(); })()" },
  // Textes & noms (26/10/2026) : la liste, un groupe ouvert, l'éditeur d'un texte de Discord et celui d'un nom du site ;
  // les annonces « Publiées » ; les textes d'une carte depuis son aperçu ; renommer un rôle.
  { nom: "capitainerie-textes", ancre: "#capitainerie/textes" },
  { nom: "capitainerie-textes-groupe", ancre: "#capitainerie/textes", geste: OUVRIR_GROUPE_TEXTES(0) },
  { nom: "fenetre-editeur-texte", ancre: "#capitainerie/textes", geste: OUVRIR_GROUPE_TEXTES(0),
    geste2: "document.querySelector('details.groupe[open] .texte-ligne .bouton').click()" },
  { nom: "fenetre-editeur-texte-site", ancre: "#capitainerie/textes", geste: OUVRIR_GROUPE_TEXTES(4),
    geste2: "document.querySelector('details.groupe[open] .texte-ligne .bouton').click()" },
  { nom: "equipage-annonces-publiees", ancre: "#equipage/annonces/publiees" },
  { nom: "fenetre-textes-carte", ancre: "#equipage/annonces/brouillons", geste: OUVRIR_BROUILLON,
    geste2: "[...document.querySelectorAll('.apercu-cadre button')].find(b => b.textContent.includes('Modifier les textes')).click()" },
  { nom: "fenetre-renommer-role", ancre: "#capitainerie/roles", geste: "[...document.querySelectorAll('#contenu .rubrique-corps button')].find(b => b.textContent.includes('Renommer…')).click()" },
  // « Même ce qui existe déjà » : « Renommer » dans l'en-tête d'une rubrique (son nom, sa phrase, ses sous-onglets) ;
  // les textes de la carte de l'équipe (Candidatures → Questionnaire) ; ceux du guide du clan (Rôles & métiers).
  { nom: "fenetre-renommer-rubrique", ancre: "#equipage/annonces/composer", geste: "document.querySelector('#contenu .titre-rubrique .renommer-rubrique').click()" },
  { nom: "fenetre-textes-equipe", ancre: "#equipage/candidatures/questionnaire", geste: "[...document.querySelectorAll('#contenu button')].find(b => b.textContent.includes(\"La carte de l'équipe\")).click()" },
  { nom: "fenetre-textes-guide", ancre: "#capitainerie/roles", geste: "[...document.querySelectorAll('#contenu button')].find(b => b.textContent.includes('Les textes du guide du clan')).click()" },
  // La présence en direct : une SECONDE personne (la direction, son propre cookie) tient l'affiche de Kolax en
  // modification. La liste « À bord » ouverte, la carte sous cadenas, l'éditeur en lecture seule (vrai site local).
  { nom: "direct-liste", ancre: "#capitainerie/affiches", autre: true, geste: "document.querySelector('.direct-bord').click()" },
  { nom: "direct-carte-verrouillee", ancre: "#capitainerie/affiches", autre: true, geste: "(" + voirCarteDirect + ")()" },
  { nom: "direct-lecture-seule", ancre: "#capitainerie/affiches", autre: true, geste: "(" + voirCarteDirect + ")()",
    geste2: "(" + ouvrirEditeurDirect + ")()" },
  // Le site de l'équipage (`/tableau/equipage/`) : un MEMBRE du clan (Kolax, portée « equipage ») en lecture seule —
  // aucun bouton d'action —, puis la tête en mode édition. Chaque scène porte sa page et son entrée (sa session).
  ...SCENES_EQUIPAGE,
];

// ─── Le protocole DevTools ──────────────────────────────────────────────────
let ws, prochainId = 1;
const attente = new Map();
const ecouteurs = [];
function envoyer(methode, params = {}, sessionId) {
  const id = prochainId++;
  ws.send(JSON.stringify({ id, method: methode, params, sessionId }));
  return new Promise((ok, ko) => attente.set(id, { ok, ko, methode }));
}
function surEvenement(fn) { ecouteurs.push(fn); }
const pause = (ms) => new Promise((ok) => setTimeout(ok, ms));

async function lancerNavigateur() {
  const exe = NAVIGATEURS.find((p) => existsSync(p));
  if (!exe) throw new Error("Aucun Chrome ni Edge trouvé (option --navigateur <exe>).");
  const profil = mkdtempSync(join(tmpdir(), "capitainerie-profil-"));
  const proc = spawn(exe, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profil}`, "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-sync", "--disable-features=Translate,MediaRouter,OptimizationHints", "--lang=fr-FR", "about:blank"], { stdio: "ignore" });
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return { proc, profil, exe, wsUrl: (await r.json()).webSocketDebuggerUrl };
    } catch (e) { /* pas encore */ }
    await pause(250);
  }
  throw new Error("Le navigateur ne répond pas sur le port " + PORT);
}

async function connecter(wsUrl) {
  ws = new WebSocket(wsUrl);
  await new Promise((ok, ko) => { ws.onopen = ok; ws.onerror = ko; });
  ws.onmessage = (m) => {
    const d = JSON.parse(typeof m.data === "string" ? m.data : m.data.toString());
    if (d.id && attente.has(d.id)) {
      const a = attente.get(d.id);
      attente.delete(d.id);
      if (d.error) a.ko(new Error(a.methode + " : " + d.error.message)); else a.ok(d.result);
    } else if (d.method) for (const f of ecouteurs) f(d);
  };
}

async function nouvelOnglet() {
  const { targetId } = await envoyer("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await envoyer("Target.attachToTarget", { targetId, flatten: true });
  const s = (m, p) => envoyer(m, p, sessionId);
  await s("Page.enable");
  await s("Runtime.enable");
  await s("Log.enable");
  return { s, sessionId, targetId };
}

// ─── Les contrôles exécutés dans la page ────────────────────────────────────
const CONTROLE = `(() => {
  const vw = document.documentElement.clientWidth;
  const res = { pageDeborde: document.documentElement.scrollWidth > innerWidth + 0.5, scrollWidth: document.documentElement.scrollWidth, innerWidth,
    sortants: [], conteneurs: [], textes: [], petits: [], images: [] };
  const decrire = (el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + (typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\\s+/).slice(0, 3).join(".") : "")
    + (el.textContent ? " « " + el.textContent.trim().replace(/\\s+/g, " ").slice(0, 40) + " »" : "");
  const coupe = (el, jusqua) => { for (let p = el.parentElement; p && p !== jusqua && p !== document.documentElement; p = p.parentElement) { const cs = getComputedStyle(p); if (/(auto|scroll|hidden|clip)/.test(cs.overflowX) || cs.position === "fixed") return p; } return null; };
  const racines = [...document.querySelectorAll("dialog[open]")];
  const zone = racines.length ? racines[racines.length - 1] : document.body;
  for (const el of zone.querySelectorAll("*")) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || cs.display === "contents") continue;
    if (el.closest("svg") && el.tagName.toLowerCase() !== "svg") continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const abs = cs.position === "absolute" || cs.position === "fixed";
    if ((r.right > vw + 1 || r.left < -1) && !coupe(el) && !abs) res.sortants.push({ el: decrire(el), gauche: Math.round(r.left), droite: Math.round(r.right) });
    const p = el.parentElement;
    if (p && !abs && cs.position !== "sticky") {
      const pcs = getComputedStyle(p);
      const pr = p.getBoundingClientRect();
      if (pcs.display !== "contents" && pcs.display !== "inline" && /visible/.test(pcs.overflowX) && (r.right > pr.right + 1.5 || r.left < pr.left - 1.5) && !coupe(el, p.parentElement))
        res.conteneurs.push({ el: decrire(el), parent: decrire(p).slice(0, 80), depasse: Math.round(Math.max(r.right - pr.right, pr.left - r.left)) });
    }
    if (el.children.length === 0 && el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0 && /visible/.test(cs.overflowX) && cs.display !== "inline")
      res.textes.push({ el: decrire(el), contenu: el.scrollWidth, boite: el.clientWidth });
  }
  if (matchMedia("(pointer: coarse)").matches) {
    for (const el of zone.querySelectorAll("button, a[href], input, select, textarea, summary, [role=button], [role=tab]")) {
      if (el.closest(".md, .texte, p, .conv-texte") && el.matches("a")) continue;
      if (el.matches(".lien-nom")) continue;
      let cible = el;
      if (el.matches("input[type=checkbox], input[type=radio]")) cible = el.closest("label") || el;
      const cs = getComputedStyle(cible);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      const r = cible.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (r.height < 43.5 || r.width < 43.5) res.petits.push({ el: decrire(cible).slice(0, 90), l: Math.round(r.width), h: Math.round(r.height) });
    }
  }
  for (const img of document.images) if (img.complete && img.naturalWidth === 0 && img.getBoundingClientRect().width) res.images.push(img.getAttribute("src"));
  // Un « null », « undefined », « NaN » ou « [object Object] » affiché tel quel : une valeur absente passée au DOM.
  res.suspects = [];
  const marcheur = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = marcheur.nextNode(); n; n = marcheur.nextNode()) {
    const t = n.nodeValue.trim();
    const mots = t.split(/[^A-Za-z]+/);
    if (["null", "undefined", "NaN", "[object Object]"].includes(t) || mots.includes("undefined") || mots.includes("NaN") || t.includes("[object Object]")) {
      const el = n.parentElement;
      if (el && !el.closest("script, style, noscript, template") && el.getClientRects().length) res.suspects.push(decrire(el).slice(0, 90) + " « " + t.slice(0, 40) + " »");
    }
  }
  // Une pastille ronde (pastille gravée, avatar, rond à 50 %) étirée en ovale : une règle de mise en page l'a
  // tirée (25/10 : « li > span { flex: 1 } » étirait la pastille d'une race sur toute la ligne).
  res.deformes = [];
  for (const el of zone.querySelectorAll("*")) {
    if (el.closest("svg")) continue;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") continue;
    if (!el.matches(".monogramme") && cs.borderTopLeftRadius !== "50%") continue;
    const r = el.getBoundingClientRect();
    if (r.width < 6 || r.height < 6) continue;
    if (Math.abs(r.width - r.height) > 2) res.deformes.push({ el: decrire(el).slice(0, 90), l: Math.round(r.width), h: Math.round(r.height) });
  }
  const diag = window.__capitainerie || {};
  res.violations = diag.violations || [];
  res.icones = [...(diag.icones || [])];
  res.dedoublonne = true;
  return res;
})()`;

const rapport = { debut: new Date().toISOString(), url: URL_SITE, scenes: [], horsLigne: null, erreursConsole: [] };
let erreursCourantes = [];
function brancherConsole() {
  surEvenement((d) => {
    if (d.method === "Runtime.exceptionThrown") erreursCourantes.push("exception : " + (d.params.exceptionDetails.exception && d.params.exceptionDetails.exception.description || d.params.exceptionDetails.text));
    else if (d.method === "Runtime.consoleAPICalled" && (d.params.type === "error" || d.params.type === "assert")) erreursCourantes.push("console : " + d.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
    else if (d.method === "Log.entryAdded" && d.params.entry.level === "error") {
      const e = d.params.entry;
      if (/status of 404/.test(e.text || "") && ATTENDUS_404.test(e.url || "")) { rapport.attendus404 = (rapport.attendus404 || 0) + 1; return; }
      erreursCourantes.push("journal : " + e.text + (e.url ? " (" + e.url + ")" : ""));
    }
  });
}

async function evaluer(o, expression) {
  const r = await o.s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error("évaluation : " + (r.exceptionDetails.exception && r.exceptionDetails.exception.description || r.exceptionDetails.text));
  return r.result.value;
}
async function attendrePret(o, max = 9000) {
  const t0 = Date.now();
  while (Date.now() - t0 < max) {
    const pret = await evaluer(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette, dialog .squelette')").catch(() => false);
    if (pret) { await pause(500); return true; }
    await pause(150);
  }
  return false;
}
async function taille(o, l, hh) {
  const mobile = l < 720;
  await o.s("Emulation.setDeviceMetricsOverride", { width: l, height: hh, deviceScaleFactor: 1, mobile });
  await o.s("Emulation.setTouchEmulationEnabled", { enabled: l < 1100, maxTouchPoints: l < 1100 ? 5 : 1 });
}
async function capture(o, chemin) {
  const r = await o.s("Page.captureScreenshot", { format: "png" });
  writeFileSync(chemin, Buffer.from(r.data, "base64"));
}

// La seconde personne des scènes « direct-* » : la direction, dans un autre contexte du navigateur (son propre cookie),
// ouvre l'affiche de Kolax en modification et la garde. Seulement avec --entree (le vrai site local a deux personnes).
let autre = null;
async function preparerAutre() {
  if (autre !== null) return autre;
  autre = false;
  const entree = String(opt("entree", "") || "");
  if (!entree) return false;
  try {
    const { browserContextId } = await envoyer("Target.createBrowserContext", {});
    const { targetId } = await envoyer("Target.createTarget", { url: "about:blank", browserContextId });
    const { sessionId } = await envoyer("Target.attachToTarget", { targetId, flatten: true });
    const o = { s: (m, p) => envoyer(m, p, sessionId), sessionId, targetId };
    await o.s("Page.enable");
    await o.s("Runtime.enable");
    await o.s("Emulation.setDeviceMetricsOverride", { width: 1366, height: 768, deviceScaleFactor: 1, mobile: false });
    await o.s("Page.navigate", { url: entree + (entree.includes("?") ? "&" : "?") + "qui=direction" });
    await pause(1500);
    await o.s("Page.navigate", { url: URL_SITE + "#capitainerie/affiches" });
    await attendrePret(o, 12000);
    await evaluer(o, "(" + voirCarteDirect + ")()");
    await evaluer(o, "(" + ouvrirEditeurDirect + ")()");
    await pause(1200);
    autre = o;
  } catch (e) {
    console.log("        · seconde personne impossible : " + e.message);
  }
  return autre;
}

// La session de la page : l'entrée donnée (`--entree`, ou celle d'une scène) n'est rouverte que si elle change.
let entreeCourante = "";
async function entrer(o, entree) {
  if (!entree || entree === entreeCourante) return;
  await o.s("Page.navigate", { url: entree });
  await pause(1500);
  entreeCourante = entree;
}

async function controlerScene(o, scene, [l, hh]) {
  if (scene.autre && !(await preparerAutre())) { console.log(`passée ${scene.nom.padEnd(30)} (une seconde personne : vrai site local, --entree)`); return; }
  if (scene.page && !opt("entree", "")) { console.log(`passée ${scene.nom.padEnd(30)} (le site de l'équipage : vrai site local, --entree)`); return; }
  await entrer(o, scene.entree ? ORIGINE + scene.entree : String(opt("entree", "") || ""));
  erreursCourantes = [];
  await taille(o, l, hh);
  await o.s("Page.navigate", { url: (scene.page ? ORIGINE + scene.page : URL_SITE) + "?scene=" + scene.nom + "-" + l + scene.ancre });
  await pause(300);
  const pret = await attendrePret(o);
  if (scene.geste) { try { await evaluer(o, scene.geste); } catch (e) { erreursCourantes.push("geste impossible : " + e.message); } await pause(900); }
  if (scene.geste2) { try { await evaluer(o, scene.geste2); } catch (e) { erreursCourantes.push("geste impossible : " + e.message); } await pause(900); }
  const res = await evaluer(o, CONTROLE);
  const texteVu = scene.interdits ? await evaluer(o, "(document.querySelector('dialog[open]') || document.body).innerText") : "";
  const fichier = join(SORTIE, `${scene.nom}-${l}x${hh}.png`);
  await capture(o, fichier);
  const fautes = [];
  if (!pret) fautes.push("la rubrique ne s'est pas affichée");
  if (res.pageDeborde) fautes.push(`la page défile en largeur (${res.scrollWidth} > ${res.innerWidth})`);
  for (const x of res.sortants.slice(0, 6)) fautes.push(`sort de l'écran : ${x.el} [${x.gauche} → ${x.droite}]`);
  for (const x of res.conteneurs.slice(0, 6)) fautes.push(`sort de son conteneur (${x.depasse} px) : ${x.el} dans ${x.parent}`);
  for (const x of res.textes.slice(0, 6)) fautes.push(`texte qui déborde (${x.contenu} > ${x.boite}) : ${x.el}`);
  for (const x of res.petits.slice(0, 8)) fautes.push(`cible tactile trop petite (${x.l}×${x.h}) : ${x.el}`);
  for (const x of res.images.slice(0, 4)) fautes.push(`image cassée : ${x}`);
  for (const x of (res.deformes || []).slice(0, 4)) fautes.push(`rond étiré en ovale (${x.l}×${x.h}) : ${x.el}`);
  for (const x of (res.suspects || []).slice(0, 4)) fautes.push(`valeur absente affichée : ${x}`);
  for (const x of res.violations.slice(0, 4)) fautes.push(`violation CSP : ${x.directive} (${x.source}:${x.ligne})`);
  for (const x of [...new Set(erreursCourantes)].slice(0, 6)) fautes.push(x);
  for (const x of scene.interdits || []) if (texteVu.includes(x)) fautes.push(`texte interdit affiché : « ${x} »`);
  const nb = { sortants: res.sortants.length, conteneurs: res.conteneurs.length, textes: res.textes.length, petits: res.petits.length };
  rapport.scenes.push({ scene: scene.nom, taille: `${l}x${hh}`, capture: fichier, fautes, nb, icones: res.icones });
  console.log(`${fautes.length ? "ÉCHEC " : "ok    "} ${scene.nom.padEnd(30)} ${String(l + "x" + hh).padEnd(10)} ${fautes.length ? fautes.length + " faute(s)" : ""}`);
  for (const f of fautes) console.log("        · " + f);
}

// ─── Le hors-ligne, de bout en bout ─────────────────────────────────────────
// Ouvrir la première affiche, « Modifier », changer le surnom, « Enregistrer ».
const MODIFIER_SURNOM = (texte) => "(async () => { const g = document.querySelector('details.groupe'); if (g && !g.open) g.open = true; await new Promise(r => setTimeout(r, 500));"
  + " document.querySelector('button.affiche').click(); await new Promise(r => setTimeout(r, 900));"
  + " [...document.querySelectorAll('dialog[open] button')].find(b => b.textContent.includes('Modifier')).click(); await new Promise(r => setTimeout(r, 900));"
  + " const champ = [...document.querySelectorAll('dialog[open] input')].find(i => i.placeholder === \"l'Ombre des Mers\"); champ.value = " + JSON.stringify(texte) + ";"
  + " champ.dispatchEvent(new Event('input', {bubbles: true})); await new Promise(r => setTimeout(r, 300));"
  + " [...document.querySelectorAll('dialog[open] button')].find(b => b.textContent.includes('Enregistrer')).click(); await new Promise(r => setTimeout(r, 1200)); return 1; })()";
async function scenarioHorsLigne(o) {
  const etapes = [];
  const note = (ok, texte) => { etapes.push({ ok, texte }); console.log(`${ok ? "ok    " : "ÉCHEC "} hors ligne : ${texte}`); };
  const bascule = (quoi, q) => fetch(`${ORIGINE}/maquette/${quoi}?${q}`).then((r) => r.json());
  await bascule("reinitialiser", "");
  await taille(o, 1366, 768);
  await o.s("Page.navigate", { url: URL_SITE + "#capitainerie/affiches" });
  await attendrePret(o, 12000);
  // le service worker doit contrôler la page : un rechargement après l'installation
  for (let i = 0; i < 30; i++) { if (await evaluer(o, "navigator.serviceWorker && navigator.serviceWorker.controller ? 1 : 0")) break; await pause(300); if (i === 10) { await o.s("Page.reload"); await attendrePret(o, 12000); } }
  const controle = await evaluer(o, "!!(navigator.serviceWorker && navigator.serviceWorker.controller)");
  note(controle, "le service worker contrôle la page");
  await evaluer(o, "Promise.all([fetch('/tableau/espace/api/rell/catalogue').then(r=>r.ok), fetch('/tableau/espace/api/rell/affiches').then(r=>r.ok), fetch('/tableau/espace/donnees').then(r=>r.ok)])");
  await pause(1500);
  await bascule("panne", "etat=1");
  await o.s("Page.reload");
  const ouverte = await attendrePret(o, 15000);
  note(ouverte, "la page s'ouvre alors que le serveur est en panne (coquille et données gardées)");
  const plaque = await evaluer(o, "document.querySelector('#plaque-etat') ? document.querySelector('#plaque-etat').textContent : ''");
  note(/Hors ligne/i.test(plaque), "la plaque dit « " + plaque + " »");
  const polices = await evaluer(o, "(async () => { await document.fonts.ready; return [...new Set([...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/[\"']/g, '')))]; })()");
  note(["Pirata One", "Alegreya"].every((p) => polices.includes(p)), "les polices sont là hors ligne : " + polices.join(", "));
  const papier = await evaluer(o, "(async () => { const r = await fetch('/tableau/espace/s/textures/parchemin.webp'); return r.ok; })()");
  note(papier, "les textures sont servies hors ligne par le service worker");
  await capture(o, join(SORTIE, "hors-ligne-1-ouvert-en-panne.png"));
  // Modifier une affiche sans réseau
  await evaluer(o, MODIFIER_SURNOM("Contrôle hors ligne")).catch((e) => { note(false, "geste de modification : " + e.message); return 0; });
  const plaque2 = await evaluer(o, "document.querySelector('#plaque-etat').textContent");
  note(/1 modification/.test(plaque2), "la plaque dit « " + plaque2 + " »");
  const enAttente = await evaluer(o, "(async () => { const db = await new Promise((ok, ko) => { const r = indexedDB.open('capitainerie'); r.onsuccess = () => ok(r.result); r.onerror = ko; }); const t = db.transaction('file_ops'); const l = await new Promise(ok => { const r = t.objectStore('file_ops').getAll(); r.onsuccess = () => ok(r.result); }); return l.map(o => o.api + ' ' + JSON.stringify(o.corps).slice(0, 80)); })()");
  note(enAttente.length === 1 && /rell\/affiche/.test(enAttente[0]), "IndexedDB garde l'opération : " + enAttente.join(" | "));
  const optimiste = await evaluer(o, "document.body.textContent.includes('Contrôle hors ligne') && document.body.textContent.includes(\"En attente d'envoi\")");
  note(optimiste, "l'affiche modifiée s'affiche tout de suite, marquée « En attente d'envoi »");
  await capture(o, join(SORTIE, "hors-ligne-2-modification-en-attente.png"));
  // Le serveur revient
  await bascule("panne", "etat=0");
  await evaluer(o, "window.dispatchEvent(new Event('online')); 1");
  let partie = false;
  for (let i = 0; i < 40 && !partie; i++) { await pause(400); partie = await evaluer(o, "/En ligne/.test(document.querySelector('#plaque-etat').textContent)"); }
  note(partie, "au retour, l'envoi part et la plaque revient à « En ligne · à jour »");
  const serveur = await fetch(`${ORIGINE}/tableau/espace/api/rell/affiches`).then((r) => r.json());
  const recu = serveur.affiches.some((a) => a.surnom === "Contrôle hors ligne");
  note(recu, "le serveur a bien enregistré la modification (une seule fois)");
  await capture(o, join(SORTIE, "hors-ligne-3-envoye.png"));
  // Conflit : la même affiche est modifiée ailleurs pendant qu'on la modifie hors ligne.
  const aff = (serveur.affiches || []).find((a) => a.surnom === "Contrôle hors ligne");
  if (aff) {
    await bascule("ailleurs", `quoi=affiche&id=${aff.id}`);
    await bascule("panne", "etat=1");
    await evaluer(o, "window.dispatchEvent(new Event('offline')); 1");
    await evaluer(o, MODIFIER_SURNOM("Seconde modification")).catch((e) => note(false, "seconde modification : " + e.message));
    await bascule("panne", "etat=0");
    await evaluer(o, "window.dispatchEvent(new Event('online')); 1");
    let conflit = false;
    for (let i = 0; i < 40 && !conflit; i++) { await pause(400); conflit = await evaluer(o, "/conflit/i.test(document.querySelector('#plaque-etat').textContent)"); }
    note(conflit, "la modification faite ailleurs donne un conflit, annoncé par la plaque");
    await evaluer(o, "(async () => { document.querySelector('#plaque-etat').click(); await new Promise(r => setTimeout(r, 900)); [...document.querySelectorAll('dialog[open] button')].find(b => b.textContent.includes('Régler le conflit')).click(); await new Promise(r => setTimeout(r, 900)); return 1; })()").catch((e) => note(false, "ouvrir le conflit : " + e.message));
    const deuxVersions = await evaluer(o, "(() => { const d = [...document.querySelectorAll('dialog[open]')].pop(); return !!d && d.textContent.includes('Ma version') && d.textContent.includes('Version enregistrée') && d.textContent.includes('Surnom') && !d.textContent.includes('Nom Roblox'); })()");
    note(deuxVersions, "la fenêtre montre les deux versions, champ par champ");
    await capture(o, join(SORTIE, "hors-ligne-4-conflit.png"));
    await evaluer(o, "(async () => { const d = [...document.querySelectorAll('dialog[open]')].pop(); [...d.querySelectorAll('button')].find(b => b.textContent.includes('Envoyer ce choix')).click(); return 1; })()").catch((e) => note(false, "envoyer le choix : " + e.message));
    let regle = false;
    for (let i = 0; i < 40 && !regle; i++) { await pause(400); regle = await evaluer(o, "/En ligne/.test(document.querySelector('#plaque-etat').textContent)"); }
    const final = await fetch(`${ORIGINE}/tableau/espace/api/rell/affiche?id=${aff.id}`).then((r) => r.json());
    note(regle && final.surnom === "Seconde modification", "après le choix, ma version part et le serveur l'a (version " + final.version + ")");
  }
  rapport.horsLigne = etapes;
  await bascule("panne", "etat=0");
  return etapes.every((e) => e.ok);
}

// ─── Le tout ────────────────────────────────────────────────────────────────
async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  const nav = await lancerNavigateur();
  console.log("Navigateur : " + nav.exe);
  console.log("Captures : " + SORTIE);
  let ok = true;
  try {
    await connecter(nav.wsUrl);
    brancherConsole();
    const o = await nouvelOnglet();
    // --entree : une adresse ouverte d'abord (le vrai site local : /tableau/demo pose la session), puis les scènes.
    if (opt("entree", "")) await entrer(o, String(opt("entree")));
    if (!opt("seulement-hors-ligne", false)) {
      const filtre = opt("scenes", "") ? String(opt("scenes")).split(",") : null;
      for (const scene of SCENES.filter((s) => !filtre || filtre.some((f) => s.nom.includes(f)))) {
        for (const t of TAILLES) await controlerScene(o, scene, t);
      }
    }
    if (opt("hors-ligne", false) || opt("seulement-hors-ligne", false)) {
      const o2 = await nouvelOnglet();
      ok = (await scenarioHorsLigne(o2)) && ok;
    }
  } finally {
    try { await envoyer("Browser.close"); } catch (e) { /* déjà fermé */ }
    await pause(400);
    try { nav.proc.kill(); } catch (e) { /* rien */ }
    try { rmSync(nav.profil, { recursive: true, force: true }); } catch (e) { /* le profil temporaire reste */ }
  }
  const echecs = rapport.scenes.filter((s) => s.fautes.length);
  const manquantes = [...new Set(rapport.scenes.flatMap((s) => s.icones || []))];
  rapport.fin = new Date().toISOString();
  rapport.resume = { scenes: rapport.scenes.length, echecs: echecs.length, iconesProvisoires: manquantes };
  writeFileSync(join(SORTIE, "rapport.json"), JSON.stringify(rapport, null, 1));
  console.log(`\n${rapport.scenes.length} contrôle(s), ${echecs.length} en échec.` + (manquantes.length ? " Icônes encore provisoires : " + manquantes.join(", ") : "")
    + (rapport.attendus404 ? ` ${rapport.attendus404} image(s) officielle(s) pas encore livrée(s) (404 attendus, pastille gravée à la place).` : ""));
  if (echecs.length || !ok) process.exitCode = 1;
}
principal().catch((e) => { console.error("Contrôle interrompu : " + e.message); process.exitCode = 2; });
