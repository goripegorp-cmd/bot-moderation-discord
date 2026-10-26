// outils/parcours_equipage.mjs — le site de l'équipage, joué pour de vrai, contre le vrai serveur local (26/10/2026).
//
// Deux personnes, chacune dans SON contexte de navigateur (son propre cookie) : un MEMBRE du clan (Kolax, portée
// « equipage ») et la DIRECTION (portée « tout », sur la même page, en mode édition). Elles cliquent comme une personne ;
// après chaque geste, l'état est RELU par l'API (un bouton qui « marche » à l'écran sans rien changer est un échec).
//   · le membre voit l'accueil, l'équipage, sa fiche — et ne trouve AUCUN bouton d'action ;
//   · chacune de ses tentatives vers la direction ou vers une écriture échoue en 403, par la page ET par l'API directe ;
//   · la direction modifie un bloc, publie une actualité avec son image, réordonne, masque — le membre voit le résultat ;
//   · le rôle du clan retiré : l'accès du membre tombe tout de suite ; rendu, il faut un lien neuf.
//
//   node outils/parcours_equipage.mjs [--url http://localhost:8790] [--sortie <dossier>] [--navigateur <exe>]
// La base du site local change à chaque parcours : relancer `python outils/site_local.py` avant de rejouer.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const BASE = String(opt("url", "http://localhost:8790")).replace(/\/+$/, "");
const PAGE = BASE + "/tableau/equipage/";
const SORTIE = opt("sortie", join(tmpdir(), "equipage-parcours"));
const IMAGE = resolve(dirname(fileURLToPath(import.meta.url)), "..", "tests", "donnees", "banniere_1600x640.png");   // une vraie bannière PNG du dépôt (1600 × 640 : bannieres.py)
const KOLAX = "1000";
const PORT = 9939 + Math.floor(Math.random() * 50);
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);
//  Ce qu'un membre ne doit JAMAIS trouver : un geste d'écriture.
const GESTES = /modifier|publier|ajouter|supprimer|retirer|masquer|montrer ce bloc|monter|descendre|enregistrer|corbeille|épingler|choisir une image/i;

// ─── Le protocole DevTools ──────────────────────────────────────────────────
let ws, prochainId = 1;
const attente = new Map();
const ecouteurs = [];
const pause = (ms) => new Promise((ok) => setTimeout(ok, ms));
function envoyer(methode, params = {}, sessionId) {
  const id = prochainId++;
  ws.send(JSON.stringify({ id, method: methode, params, sessionId }));
  return new Promise((ok, ko) => attente.set(id, { ok, ko, methode }));
}
async function lancerNavigateur() {
  const exe = NAVIGATEURS.find((p) => existsSync(p));
  if (!exe) throw new Error("Aucun Chrome ni Edge trouvé (option --navigateur <exe>).");
  const profil = mkdtempSync(join(tmpdir(), "equipage-parcours-"));
  const proc = spawn(exe, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profil}`, "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-sync", "--lang=fr-FR", "about:blank"], { stdio: "ignore" });
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
const erreursPage = [];
/** Une personne : son contexte de navigateur (ses cookies à elle), son onglet. */
async function personne(nom, entree) {
  const { browserContextId } = await envoyer("Target.createBrowserContext", {});
  const { targetId } = await envoyer("Target.createTarget", { url: "about:blank", browserContextId });
  const { sessionId } = await envoyer("Target.attachToTarget", { targetId, flatten: true });
  const o = { nom, sessionId, s: (m, p) => envoyer(m, p, sessionId) };
  await o.s("Page.enable");
  await o.s("Runtime.enable");
  await o.s("DOM.enable");
  ecouteurs.push((d) => {
    if (d.sessionId !== sessionId) return;
    if (d.method === "Runtime.exceptionThrown") erreursPage.push(nom + " · exception : " + ((d.params.exceptionDetails.exception || {}).description || d.params.exceptionDetails.text));
    if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") erreursPage.push(nom + " · console : " + d.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
  });
  await o.s("Emulation.setDeviceMetricsOverride", { width: 1366, height: 900, deviceScaleFactor: 1, mobile: false });
  await o.s("Page.navigate", { url: BASE + entree });
  await pause(1500);
  return o;
}
async function evaluer(o, expression, geste = false) {
  //  `geste` : comme un vrai clic (activation utilisateur) — sans lui, le navigateur n'ouvre pas un choix de fichier.
  const r = await o.s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true, userGesture: geste });
  if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text);
  return r.result.value;
}

// ─── Les gestes, comme une personne ─────────────────────────────────────────
const ZONE = "([...document.querySelectorAll('dialog[open]')].pop() || document)";
const visible = "(x) => x.getClientRects().length && getComputedStyle(x).visibility !== 'hidden'";
/** Cliquer l'élément visible (et actif) dont le texte (ou le libellé accessible) contient `texte`. */
function cliquer(o, selecteur, texte, { dans = "", geste = false } = {}) {
  return evaluer(o, `(() => { const z = ${dans ? `document.querySelector(${JSON.stringify(dans)})` : ZONE}; if (!z) return false; const vis = ${visible};
    const el = [...z.querySelectorAll(${JSON.stringify(selecteur)})].find((x) => vis(x) && !x.disabled && ((x.textContent || "") + " " + (x.getAttribute("aria-label") || "")).replace(/\\s+/g, " ").includes(${JSON.stringify(texte)}));
    if (!el) return false; el.scrollIntoView({ block: "center" }); el.click(); return true; })()`, geste);
}
function ecrire(o, selecteur, valeur) {
  return evaluer(o, `(() => { const el = [...${ZONE}.querySelectorAll(${JSON.stringify(selecteur)})].pop();
    if (!el) return false; el.focus(); el.value = ${JSON.stringify(valeur)}; el.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
}
async function attendre(fn, ms = 12000, pas = 300) {
  const t0 = Date.now();
  let v = null;
  while (Date.now() - t0 < ms) {
    try { v = await fn(); } catch (e) { v = null; }
    if (v) return v;
    await pause(pas);
  }
  return v;
}
/** Lire une lecture du site de l'équipage, comme la page (même cookie). */
const lireEq = (o, nom) => evaluer(o, `fetch("/tableau/equipage/api/${nom}", { credentials: "same-origin" }).then(async (r) => ({ st: r.status, d: await r.json() }))`);
/** Une requête depuis la page (son cookie, l'en-tête de la page pour les écritures) : le statut. */
const essayer = (o, methode, chemin, corps) => evaluer(o, `fetch(${JSON.stringify(chemin)}, { method: ${JSON.stringify(methode)}, credentials: "same-origin",
  headers: ${methode === "POST" ? `{ "Content-Type": "application/json", "X-Tableau": "1" }` : "{}"}, body: ${methode === "POST" ? JSON.stringify(JSON.stringify(corps || {})) : "undefined"} })
  .then((r) => r.status).catch(() => 0)`);
async function aller(o, ancre) {
  await evaluer(o, "(() => { for (const d of [...document.querySelectorAll('dialog[open]')].reverse()) d.close(); return true; })()").catch(() => null);
  await o.s("Page.navigate", { url: PAGE + "?vu=" + Date.now() + ancre });   // toujours une page fraîche (jamais le même document)
  const pret = await attendre(() => evaluer(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 15000, 200);
  await pause(700);
  return pret;
}
const texte = (o) => evaluer(o, `${ZONE} === document ? document.body.innerText : ${ZONE}.innerText`);
/** Les boutons et liens visibles : leur texte et leur libellé accessible. */
const gestesVisibles = (o) => evaluer(o, `(() => { const vis = ${visible}; return [...document.querySelectorAll("button, a[href], [role=button], input, textarea, select")]
  .filter(vis).map((x) => ((x.textContent || "") + " " + (x.getAttribute("aria-label") || "") + " " + (x.getAttribute("title") || "")).replace(/\\s+/g, " ").trim()); })()`);

// ─── Le rapport ─────────────────────────────────────────────────────────────
const resultats = [];
let numero = 0;
async function etape(o, nom, fn) {
  numero += 1;
  const debut = erreursPage.length;
  let ok = false, detail = "";
  try {
    const r = await fn();
    ok = r === true || (r && r.ok === true);
    detail = r && r !== true ? ("detail" in r ? String(r.detail || "") : JSON.stringify(r).slice(0, 300)) : "";
  } catch (e) {
    detail = "exception : " + e.message;
  }
  const erreurs = erreursPage.slice(debut);
  if (erreurs.length) { ok = false; detail += (detail ? " · " : "") + erreurs.slice(0, 3).join(" | "); }
  const fichier = join(SORTIE, String(numero).padStart(2, "0") + "-" + nom.replace(/[^a-z0-9]+/gi, "-").toLowerCase() + ".png");
  try { const c = await o.s("Page.captureScreenshot", { format: "png" }); writeFileSync(fichier, Buffer.from(c.data, "base64")); } catch (e) { /* capture impossible */ }
  resultats.push({ nom, ok, detail, capture: fichier });
  console.log(`${ok ? "ok    " : "ÉCHEC "} ${nom}${detail ? "\n        · " + detail : ""}`);
  return ok;
}

// ═══ LE MEMBRE DU CLAN ═════════════════════════════════════════════════════
async function parcoursMembre(m) {
  await etape(m, "Membre : l'accueil s'ouvre, en lecture seule", async () => {
    if (!await aller(m, "#accueil")) return { ok: false, detail: "l'accueil ne s'affiche pas" };
    const t = await texte(m);
    const manque = ["Le code de l'équipage", "Le journal de bord", "Prochaines sorties en mer", "Équipiers à l'honneur", "L'équipage en chiffres"].filter((x) => !t.includes(x));
    const edition = await evaluer(m, "!!document.querySelector('.barre-edition, .barre-bloc, .en-edition')");
    const { d } = await lireEq(m, "accueil");
    return { ok: !manque.length && !edition && d.edition === false, detail: manque.length ? "absent : " + manque.join(", ") : edition ? "une barre d'édition est là" : d.blocs.length + " blocs" };
  });

  await etape(m, "Membre : aucun bouton d'action, sur les trois onglets et dans une affiche", async () => {
    const trouves = [];
    for (const ancre of ["#accueil", "#equipage", "#fiche"]) {
      await aller(m, ancre);
      trouves.push(...(await gestesVisibles(m)).filter((x) => GESTES.test(x)).map((x) => ancre + " : " + x));
    }
    await aller(m, "#equipage");
    if (!await cliquer(m, "button.affiche", "")) return { ok: false, detail: "aucune affiche à ouvrir" };
    await attendre(() => evaluer(m, "!!document.querySelector('dialog[open] .affiche-grand')"), 5000);
    const pied = await evaluer(m, "[...document.querySelectorAll('dialog[open] .pancarte-pied button')].map((b) => b.textContent.trim())");
    trouves.push(...(await gestesVisibles(m)).filter((x) => GESTES.test(x)).map((x) => "affiche : " + x));
    return { ok: !trouves.length && pied.length === 1 && pied[0] === "Fermer", detail: trouves.length ? trouves.slice(0, 4).join(" | ") : "pied de l'affiche : " + pied.join(", ") };
  });

  await etape(m, "Membre : l'équipage par métier, la recherche, le filtre", async () => {
    const { d } = await lireEq(m, "equipage");
    const metiers = new Set(d.affiches.flatMap((a) => (a.attributs.metier || [])));
    await aller(m, "#equipage");
    //  27/10/2026 : l'onglet s'ouvre sur les équipes du clan ; le mur par métier est sous « Toutes les affiches ».
    if (!await cliquer(m, ".segment button", "Toutes les affiches")) return { ok: false, detail: "« Toutes les affiches » absent" };
    await pause(500);
    const groupes = await evaluer(m, "document.querySelectorAll('#contenu details.groupe').length");
    if (groupes !== metiers.size + (d.affiches.some((a) => !(a.attributs.metier || []).length) ? 1 : 0)) return { ok: false, detail: `groupes ${groupes} ≠ métiers ${metiers.size}` };
    await ecrire(m, ".recherche input", "mira");
    await pause(600);
    const apresRecherche = await evaluer(m, "[...document.querySelectorAll('#contenu button.affiche')].map((b) => b.getAttribute('aria-label'))");
    await ecrire(m, ".recherche input", "");
    await pause(500);
    if (!await cliquer(m, ".liste-bouton", "Tous les métiers")) return { ok: false, detail: "liste des métiers absente" };
    await pause(400);
    const navigation = d.catalogue.elements.find((e) => e.type === "metier" && e.cle === "navigation");
    if (!navigation || !await cliquer(m, ".menu-pop .option", navigation.nom)) return { ok: false, detail: "option du métier absente" };
    await pause(600);
    const filtre = await evaluer(m, "[...document.querySelectorAll('#contenu details.groupe summary')].map((s) => s.textContent.trim())");
    const ok = apresRecherche.length >= 1 && apresRecherche.every((x) => /mira/i.test(x)) && filtre.length === 1 && filtre[0].includes(navigation.nom);
    await cliquer(m, ".liste-bouton", navigation.nom); await pause(300); await cliquer(m, ".menu-pop .option", "Tous les métiers");
    return { ok, detail: `recherche « mira » : ${apresRecherche.length} affiche(s) · filtre : ${filtre.join(" / ")}` };
  });

  await etape(m, "Membre : sa fiche", async () => {
    const { d } = await lireEq(m, "equipage");
    await aller(m, "#fiche");
    const t = await texte(m);
    return { ok: d.moi === "demo-kolax-01" && /KOLAX_RS/i.test(t) && t.includes("Le Requin") && t.includes("Prime"), detail: "affiche " + d.moi };
  });

  await etape(m, "Membre : chaque tentative vers la direction ou vers une écriture → 403", async () => {
    await aller(m, "#accueil");
    const essais = [["GET", "/tableau/espace/donnees"], ["GET", "/tableau/espace/membre?id=" + KOLAX], ["GET", "/tableau/espace/api/rell/affiches"],
      ["GET", "/tableau/espace/api/rell/affiche?id=demo-kolax-01"], ["GET", "/tableau/espace/api/clan/evenements"], ["GET", "/tableau/espace/api/nettoyage"],
      ["GET", "/tableau/espace/export?quoi=journal"], ["GET", "/tableau/espace/recherche?q=a"], ["GET", "/tableau/espace/api/direct/etat?onglet=onglet-membre-1"],
      ["POST", "/tableau/espace/api/equipage/bloc", { type: "texte", contenu: { texte: "Piraté" } }],
      ["POST", "/tableau/espace/api/equipage/actualite", { titre: "Piraté" }], ["POST", "/tableau/espace/api/rell/affiche", { id: "demo-kolax-01", surnom: "Piraté" }],
      ["POST", "/tableau/espace/api/media", { nom: "x.png", base64: "iVBORw0KGgo=" }], ["POST", "/tableau/espace/action", { action: "clan_ajouter", membre: "1002" }],
      ["POST", "/tableau/espace/sync", { ops: [{ op_id: "op-membre-001", api: "rell/affiche", corps: { id: "demo-kolax-01", surnom: "Piraté" } }] }],
      ["POST", "/tableau/equipage/api/accueil", {}]];
    const non = [];
    for (const [methode, chemin, corps] of essais) {
      const st = await essayer(m, methode, chemin, corps);
      if (st !== 403) non.push(methode + " " + chemin + " → " + st);
    }
    //  La WebSocket du direct : refusée, jamais ouverte.
    const socket = await evaluer(m, `new Promise((fin) => { const w = new WebSocket("ws://" + location.host + "/tableau/espace/direct");
      w.onopen = () => { w.close(); fin("ouverte"); }; w.onerror = () => fin("refusee"); setTimeout(() => fin("sans réponse"), 5000); })`);
    //  La page de la direction elle-même.
    await m.s("Page.navigate", { url: BASE + "/tableau/espace/" });
    await pause(1200);
    const page = await evaluer(m, "document.body.innerText");
    const { d } = await lireEq(m, "accueil");
    const pirate = JSON.stringify(d).includes("Piraté");
    return { ok: !non.length && socket === "refusee" && page.includes("Réservé à la direction") && !pirate,
      detail: (non.length ? non.join(" | ") : essais.length + " tentatives refusées") + " · direct : " + socket + (pirate ? " · une écriture est passée !" : "") };
  });
}

// ═══ LA DIRECTION ══════════════════════════════════════════════════════════
const accueilDe = async (o) => (await lireEq(o, "accueil")).d;
async function parcoursDirection(d, m) {
  await etape(d, "Direction : le mode édition, un bloc modifié — le membre le lit", async () => {
    if (!await aller(d, "#accueil")) return { ok: false, detail: "l'accueil ne s'affiche pas" };
    if (!(await accueilDe(d)).edition) return { ok: false, detail: "la tête n'a pas le mode édition" };
    if (!await cliquer(d, "button", "Modifier l'accueil")) return { ok: false, detail: "« Modifier l'accueil » absent" };
    await pause(500);
    if (!await cliquer(d, "button", "Modifier", { dans: ".bloc-texte .barre-bloc" })) return { ok: false, detail: "« Modifier » du bloc texte absent" };
    await attendre(() => evaluer(d, "!!document.querySelector('dialog[open] textarea')"), 5000);
    await ecrire(d, "textarea", "Cap à l'ouest, **matelots** !\nLe vent tourne, l'équipage aussi.");
    if (!await cliquer(d, ".pancarte-pied button", "Enregistrer")) return { ok: false, detail: "« Enregistrer » absent" };
    const fait = await attendre(async () => (await accueilDe(d)).blocs.find((b) => b.type === "texte" && b.contenu.texte.startsWith("Cap à l'ouest")));
    const vu = await attendre(async () => (await accueilDe(m)).blocs.find((b) => b.type === "texte" && b.contenu.texte.startsWith("Cap à l'ouest")));
    await aller(m, "#accueil");
    const page = await texte(m);
    return { ok: !!fait && !!vu && page.includes("Cap à l'ouest, matelots !"), detail: fait ? "version " + fait.version : "le serveur n'a pas la modification" };
  });

  await etape(d, "Direction : une actualité avec son image, épinglée — le membre la lit et voit l'image", async () => {
    await aller(d, "#accueil");
    if (!await cliquer(d, ".barre-edition button", "Publier une actualité")) return { ok: false, detail: "« Publier une actualité » absent" };
    await attendre(() => evaluer(d, "!!document.querySelector('dialog[open] input.saisie')"), 5000);
    await ecrire(d, "input.saisie", "Abordage à l'aube");
    await ecrire(d, "textarea", "Tout l'équipage au port à **6 h**.");
    await d.s("Page.setInterceptFileChooserDialog", { enabled: true });
    const choix = new Promise((ok) => ecouteurs.push((e) => { if (e.sessionId === d.sessionId && e.method === "Page.fileChooserOpened") ok(e.params); }));
    if (!await cliquer(d, "dialog[open] button", "Choisir une image", { geste: true })) return { ok: false, detail: "« Choisir une image » absent" };
    const fc = await Promise.race([choix, pause(5000).then(() => null)]);
    if (!fc) return { ok: false, detail: "le choix de fichier ne s'est pas ouvert" };
    await d.s("DOM.setFileInputFiles", { files: [IMAGE], backendNodeId: fc.backendNodeId });
    const apercu = await attendre(() => evaluer(d, "!!document.querySelector('dialog[open] .image-choix img')"), 10000);
    await d.s("Page.setInterceptFileChooserDialog", { enabled: false });
    if (!apercu) return { ok: false, detail: "l'image n'a pas été envoyée" };
    await evaluer(d, "(() => { const l = [...document.querySelectorAll('dialog[open] .interrupteur')].find((x) => x.textContent.includes('Épingler')); l.querySelector('input').click(); return true; })()");
    if (!await cliquer(d, ".pancarte-pied button", "Publier")) return { ok: false, detail: "« Publier » absent" };
    const a = await attendre(async () => ((await accueilDe(d)).donnees.actualites.direction || []).find((x) => x.titre === "Abordage à l'aube"));
    if (!a || !a.image || !a.epingle) return { ok: false, detail: "le serveur n'a pas l'actualité complète : " + JSON.stringify(a) };
    const vue = ((await accueilDe(m)).donnees.actualites.direction || []).find((x) => x.titre === "Abordage à l'aube");
    const image = await essayer(m, "GET", "/tableau/espace/" + a.image);
    await aller(m, "#accueil");
    const page = await texte(m);
    return { ok: !!vue && image === 200 && page.includes("Abordage à l'aube"), detail: "image " + a.image + " → " + image + " pour le membre" };
  });

  await etape(d, "Direction : réordonner l'accueil — le membre voit le nouvel ordre", async () => {
    await aller(d, "#accueil");
    await cliquer(d, "button", "Modifier l'accueil");
    await pause(400);
    const avant = (await accueilDe(m)).blocs.map((b) => b.type);
    if (!await cliquer(d, "button", "Monter ce bloc", { dans: ".bloc-actualites .barre-bloc" })) return { ok: false, detail: "« Monter ce bloc » absent" };
    const apres = await attendre(async () => { const l = (await accueilDe(m)).blocs.map((b) => b.type); return l.indexOf("actualites") === avant.indexOf("actualites") - 1 ? l : null; });
    return { ok: !!apres, detail: (apres || avant).join(" › ") };
  });

  await etape(d, "Direction : masquer un bloc, puis le montrer", async () => {
    await aller(d, "#accueil");
    await cliquer(d, "button", "Modifier l'accueil");
    await pause(400);
    if (!await cliquer(d, "button", "Masquer ce bloc", { dans: ".bloc-honneur .barre-bloc" })) return { ok: false, detail: "« Masquer » absent" };
    const cache = await attendre(async () => !(await accueilDe(m)).blocs.some((b) => b.type === "honneur"));
    const garde = (await accueilDe(d)).blocs.find((b) => b.type === "honneur");
    await pause(500);
    if (!await cliquer(d, "button", "Montrer ce bloc", { dans: ".bloc-honneur .barre-bloc" })) return { ok: false, detail: "« Montrer » absent" };
    const revu = await attendre(async () => (await accueilDe(m)).blocs.some((b) => b.type === "honneur"));
    return { ok: !!cache && garde && garde.visible === false && !!revu, detail: "masqué pour l'équipage, visible pour la tête, puis montré" };
  });

  await etape(m, "Le rôle du clan retiré : l'accès du membre tombe tout de suite ; rendu, un lien neuf", async () => {
    const retire = await evaluer(d, `fetch("/tableau/espace/action", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Tableau": "1" },
      body: JSON.stringify({ action: "clan_retirer", membre: "${KOLAX}" }) }).then((r) => r.json())`);
    if (!retire.ok) return { ok: false, detail: "retrait refusé : " + retire.message };
    const lecture = (await lireEq(m, "accueil")).st;
    await m.s("Page.navigate", { url: PAGE + "?apres-retrait=1#accueil" });   // une autre adresse : la page est redemandée
    await pause(1200);
    const page = await evaluer(m, "document.body.innerText");
    const rendu = await evaluer(d, `fetch("/tableau/espace/action", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Tableau": "1" },
      body: JSON.stringify({ action: "clan_ajouter", membre: "${KOLAX}" }) }).then((r) => r.json())`);
    const encore = (await lireEq(m, "accueil")).st;
    await m.s("Page.navigate", { url: BASE + "/tableau/demo?qui=equipage" });
    await pause(1500);
    const neuf = (await lireEq(m, "accueil")).st;
    return { ok: lecture === 403 && page.includes("n'est plus valable") && rendu.ok && encore === 403 && neuf === 200,
      detail: `retiré : ${lecture} · page : ${page.includes("n'est plus valable") ? "refusée" : "ouverte !"} · rôle rendu, ancienne session : ${encore} · lien neuf : ${neuf}` };
  });
}

// ─── Le tout ────────────────────────────────────────────────────────────────
async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  const nav = await lancerNavigateur();
  console.log("Navigateur : " + nav.exe + "\nCaptures : " + SORTIE);
  try {
    await connecter(nav.wsUrl);
    const membre = await personne("membre", "/tableau/demo?qui=equipage");
    const direction = await personne("direction", "/tableau/demo?qui=direction&vers=equipage");
    await parcoursMembre(membre);
    await parcoursDirection(direction, membre);
  } finally {
    try { await envoyer("Browser.close"); } catch (e) { /* déjà fermé */ }
    await pause(400);
    try { nav.proc.kill(); } catch (e) { /* rien */ }
    try { rmSync(nav.profil, { recursive: true, force: true }); } catch (e) { /* le profil temporaire reste */ }
  }
  const echecs = resultats.filter((r) => !r.ok);
  writeFileSync(join(SORTIE, "parcours.json"), JSON.stringify({ quand: new Date().toISOString(), base: BASE, resultats }, null, 1));
  console.log(`\n${resultats.length} étape(s), ${echecs.length} en échec.`);
  if (echecs.length) process.exitCode = 1;
}
principal().catch((e) => { console.error("Parcours interrompu : " + e.message); process.exitCode = 2; });
