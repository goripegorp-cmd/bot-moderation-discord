// outils/parcours_vitrine.mjs — la VITRINE PUBLIQUE de l'équipage et les ÉQUIPES du clan, jouées pour de vrai contre
// le vrai serveur local (27/10/2026). Chaque personne dans SON contexte de navigateur (son propre cookie) :
//   · un VISITEUR sans compte : la vitrine s'ouvre ; aucune donnée privée (ni nom Discord, ni identifiant, ni note) ;
//     aucune autre adresse ne lui répond ; « Copier le lien » copie l'adresse publique ; l'aperçu (Open Graph) est là ;
//   · la DIRECTION : retire une affiche de la vitrine (elle disparaît chez le visiteur, puis revient) ; rend un bloc
//     public (il paraît) ; crée une ÉQUIPE et nomme son chef (le site de la direction, l'éditeur en panneau) ;
//   · le CHEF voit « Mon équipe » (ceux qu'il a sous sa main), un MEMBRE voit la sienne ; le tri par type et par
//     hiérarchie ; la fiche d'administration du chef porte sa ligne d'équipe ; l'équipage ne peut rien y écrire (403).
// Après chaque geste, l'état est RELU par l'API (un bouton qui « marche » à l'écran sans rien changer est un échec).
//
//   node outils/parcours_vitrine.mjs [--url http://localhost:8790] [--sortie <dossier>] [--navigateur <exe>]
// La base du site local change à chaque parcours : relancer `python outils/site_local.py` avant de rejouer.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const BASE = String(opt("url", "http://localhost:8790")).replace(/\/+$/, "");
const VITRINE = BASE + "/equipage";
const SORTIE = opt("sortie", join(tmpdir(), "vitrine-parcours"));
const PORT = 9989 + Math.floor(Math.random() * 50);
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);
//  Ce que la vitrine ne montre JAMAIS (noms Discord de la base de démonstration, identifiants, mots de la direction).
const INTERDITS = ["discordapp", "GoRipe", "Capitaine Direction", "Anne Bonny", "Ishmael", "Salazar", "demo-kolax-01", "demo-mira",
  "notes", "membre_id", "cree_par", "Avis placardé", "Nouvelle affiche", "Grande chasse au trésor", "Mot de la direction"];
const NOM_EQUIPE = "Les Écumeurs du Large";

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
  const profil = mkdtempSync(join(tmpdir(), "vitrine-parcours-"));
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
/** Une personne : son contexte de navigateur (ses cookies à elle), son onglet ; `entree` vide : aucun cookie. */
async function personne(nom, entree) {
  const { browserContextId } = await envoyer("Target.createBrowserContext", {});
  const { targetId } = await envoyer("Target.createTarget", { url: "about:blank", browserContextId });
  const { sessionId } = await envoyer("Target.attachToTarget", { targetId, flatten: true });
  const o = { nom, sessionId, browserContextId, s: (m, p) => envoyer(m, p, sessionId) };
  await o.s("Page.enable");
  await o.s("Runtime.enable");
  ecouteurs.push((d) => {
    if (d.sessionId !== sessionId) return;
    if (d.method === "Runtime.exceptionThrown") erreursPage.push(nom + " · exception : " + ((d.params.exceptionDetails.exception || {}).description || d.params.exceptionDetails.text));
    if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") erreursPage.push(nom + " · console : " + d.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
  });
  await o.s("Emulation.setDeviceMetricsOverride", { width: 1366, height: 900, deviceScaleFactor: 1, mobile: false });
  await o.s("Emulation.setFocusEmulationEnabled", { enabled: true });   // la page « a le focus » : le presse-papiers répond
  if (entree) { await o.s("Page.navigate", { url: BASE + entree }); await pause(1500); }
  return o;
}
async function evaluer(o, expression, geste = false) {
  const r = await o.s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true, userGesture: geste });
  if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text);
  return r.result.value;
}
async function attendre(fn, ms = 12000, pas = 250) {
  const t0 = Date.now();
  let v = null;
  while (Date.now() - t0 < ms) {
    try { v = await fn(); } catch (e) { v = null; }
    if (v) return v;
    await pause(pas);
  }
  return v;
}
async function ouvrir(o, url, pret) {
  //  Toujours une page fraîche : `?vu=` AVANT l'ancre (après, il ferait partie de la route de la page).
  const [chemin, ancre] = url.split("#");
  await o.s("Page.navigate", { url: chemin + (chemin.includes("?") ? "&" : "?") + "vu=" + Date.now() + (ancre !== undefined ? "#" + ancre : "") });
  const ok = await attendre(() => evaluer(o, "!!document.querySelector(" + JSON.stringify(pret) + ")"), 15000, 200);
  await pause(600);
  return ok;
}
/** Cliquer l'élément visible dont le texte contient `texte` (dans la pancarte ouverte, sinon la page). */
function cliquer(o, selecteur, texte, geste = false) {
  return evaluer(o, `(() => { const z = [...document.querySelectorAll('dialog[open]')].pop() || document;
    const el = [...z.querySelectorAll(${JSON.stringify(selecteur)})].find((x) => x.getClientRects().length && !x.disabled && ((x.textContent || "") + " " + (x.getAttribute("aria-label") || "")).replace(/\\s+/g, " ").includes(${JSON.stringify(texte)}));
    if (!el) return false; el.scrollIntoView({ block: "center" }); el.click(); return true; })()`, geste);
}
/** Une liste du site (bouton + options) : choisir l'option qui contient `texte`. */
async function choisir(o, libelleListe, texte) {
  const ouvert = await evaluer(o, `(() => { const z = [...document.querySelectorAll('dialog[open]')].pop() || document;
    const b = [...z.querySelectorAll('.liste-bouton')].find((x) => x.getClientRects().length && (x.getAttribute('aria-label') || '').includes(${JSON.stringify(libelleListe)}));
    if (!b) return false; b.click(); return true; })()`);
  if (!ouvert) return false;
  await pause(300);
  return evaluer(o, `(() => { const op = [...document.querySelectorAll('[role=option]')].find((x) => x.getClientRects().length && x.textContent.includes(${JSON.stringify(texte)}));
    if (!op) return false; op.click(); return true; })()`);
}
const texte = (o) => evaluer(o, "([...document.querySelectorAll('dialog[open]')].pop() || document.body).innerText");
const api = (o, chemin) => evaluer(o, `fetch(${JSON.stringify(chemin)}, { credentials: "same-origin", cache: "no-store" }).then(async (r) => ({ st: r.status, d: r.headers.get("content-type") && r.headers.get("content-type").includes("json") ? await r.json() : null }))`);
const ecrire = (o, chemin, corps) => evaluer(o, `fetch(${JSON.stringify(chemin)}, { method: "POST", credentials: "same-origin",
  headers: { "Content-Type": "application/json", "X-Tableau": "1" }, body: ${JSON.stringify(JSON.stringify(corps))} }).then(async (r) => ({ st: r.status, d: await r.json().catch(() => null) }))`);
const donneesVitrine = (o) => evaluer(o, `fetch("/equipage/donnees", { credentials: "omit", cache: "no-store" }).then((r) => r.json())`);

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

// ═══ LE VISITEUR SANS COMPTE ═══════════════════════════════════════════════
async function parcoursVisiteur(v) {
  await etape(v, "Visiteur sans compte : la vitrine s'ouvre (bandeau, code, équipes, mur)", async () => {
    if (!await ouvrir(v, VITRINE, "#contenu .vitrine-mur")) return { ok: false, detail: "la vitrine ne s'affiche pas" };
    const t = await texte(v);
    const manque = ["Le code de l'équipage", "Les équipes", "Toutes les affiches", "Copier le lien de l'équipage"].filter((x) => !t.includes(x));
    const d = await donneesVitrine(v);
    const cookie = await evaluer(v, "document.cookie");
    return { ok: !manque.length && d.affiches.length > 0 && !cookie, detail: manque.length ? "absent : " + manque.join(", ") : `${d.affiches.length} affiche(s) · ${d.equipes.length} équipe(s) · aucun cookie` };
  });

  await etape(v, "Visiteur : aucune donnée privée (données ET page)", async () => {
    const brut = JSON.stringify(await donneesVitrine(v));
    await cliquer(v, ".segment button", "Toutes les affiches");
    await pause(500);
    const page = await evaluer(v, "document.documentElement.outerHTML");
    const trouves = INTERDITS.filter((x) => brut.includes(x) || page.includes(x));
    const images = [...brut.matchAll(/"(\/[^"]*\/image\/[^"]*)"/g)].map((m) => m[1]);
    const mauvaises = images.filter((x) => !/^\/equipage\/image\/[A-Za-z0-9_-]{22}$/.test(x));
    await cliquer(v, ".segment button", "Les équipes");
    return { ok: !trouves.length && !mauvaises.length, detail: trouves.length ? "trouvé : " + trouves.join(", ") : mauvaises.length ? "images : " + mauvaises.slice(0, 2).join(", ") : images.length + " image(s), toutes par jeton opaque" };
  });

  await etape(v, "Visiteur : aucune autre adresse ne lui répond", async () => {
    const essais = [["GET", "/tableau/espace/"], ["GET", "/tableau/espace/donnees"], ["GET", "/tableau/espace/api/equipage/equipes"],
      ["GET", "/tableau/equipage/api/equipage"], ["GET", "/tableau/equipage/api/accueil"], ["GET", "/tableau/espace/membre?id=1000"],
      ["GET", "/tableau/espace/media/" + "A".repeat(16)], ["GET", "/equipage/image/" + "A".repeat(22)], ["GET", "/equipage/admin"],
      ["POST", "/equipage/donnees"], ["POST", "/tableau/espace/api/equipage/equipe"], ["POST", "/tableau/espace/action"],
      ["DELETE", "/equipage"]];
    const r = await evaluer(v, `Promise.all(${JSON.stringify(essais)}.map(([m, u]) => fetch(u, { method: m, credentials: "same-origin", redirect: "manual",
      headers: m === "POST" ? { "Content-Type": "application/json", "X-Tableau": "1" } : {}, body: m === "POST" ? "{}" : undefined })
      .then(async (x) => [m + " " + u, x.status, x.type === "opaqueredirect" ? "" : (await x.text()).slice(0, 200)]).catch(() => [m + " " + u, 0, ""])))`);
    //  Refusé : 401/403/404/405, ou une redirection (vers l'entrée par lien) — jamais une donnée du site.
    const passes = r.filter(([, st, corps]) => !(st === 0 || st === 401 || st === 403 || st === 404 || st === 405 || (st >= 300 && st < 400))
      || /"(membres|equipes|affiches|blocs)"\s*:/.test(corps));
    return { ok: !passes.length, detail: passes.length ? "répond : " + passes.map(([a, s]) => a + " → " + s).join(", ") : r.map(([a, s]) => s).join(" ") };
  });

  await etape(v, "Visiteur : « Copier le lien de l'équipage » copie l'adresse publique", async () => {
    await envoyer("Browser.grantPermissions", { origin: BASE, browserContextId: v.browserContextId, permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"] });
    if (!await cliquer(v, "#entete-outils .lien-equipage", "Copier le lien", true)) return { ok: false, detail: "bouton introuvable" };
    await pause(500);
    const copie = await evaluer(v, "navigator.clipboard.readText().catch(() => '')", true);
    const dit = await texte(v);
    return { ok: copie === VITRINE && dit.includes("Lien copié"), detail: `presse-papiers : « ${copie} » · ${dit.includes("Lien copié") ? "« Lien copié »" : "aucun avis"}` };
  });

  await etape(v, "L'aperçu du lien collé dans Discord : balises Open Graph et bannière 1200 × 630", async () => {
    const r = await fetch(VITRINE, { headers: { "User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)" } });
    const html = await r.text();
    const og = Object.fromEntries([...html.matchAll(/<meta property="og:([a-z:_]+)" content="([^"]*)"/g)].map((m) => [m[1], m[2]]));
    const img = await fetch(og.image.replace(/&amp;/g, "&"));
    const octets = Buffer.from(await img.arrayBuffer());
    const png = octets.subarray(1, 4).toString() === "PNG";
    const l = octets.readUInt32BE(16), h = octets.readUInt32BE(20);
    return { ok: r.status === 200 && r.headers.get("x-robots-tag") === "noindex, nofollow" && og.title && og.description && png && l === 1200 && h === 630,
      detail: `« ${og.title} » · ${og.description.slice(0, 60)}… · image ${l}×${h} (${Math.round(octets.length / 1024)} Ko)` };
  });
}

// ═══ LA DIRECTION : LA VITRINE ═════════════════════════════════════════════
async function parcoursDirectionVitrine(d, v) {
  await etape(d, "Direction : retirer une affiche de la vitrine — elle disparaît chez le visiteur, puis revient", async () => {
    if (!await ouvrir(d, BASE + "/tableau/equipage/#equipage", "#contenu .titre-rubrique")) return { ok: false, detail: "le site de l'équipage ne s'ouvre pas" };
    await cliquer(d, ".segment button", "Toutes les affiches");
    await pause(400);
    const avant = (await donneesVitrine(v)).affiches.length;
    const nom = await evaluer(d, "(() => { const b = document.querySelector('button.affiche'); const n = b.getAttribute('aria-label'); b.click(); return n; })()");
    await pause(600);
    const interrupteur = await evaluer(d, "(() => { const i = document.querySelector('dialog[open] .reglage-vitrine input[role=switch]'); if (!i) return null; i.click(); return i.checked; })()", true);
    if (interrupteur === null) return { ok: false, detail: "pas d'interrupteur « Visible sur la vitrine » dans l'affiche ouverte" };
    const masquees = await attendre(async () => { const r = await api(d, "/tableau/equipage/api/equipage"); return (r.d.vitrine.masquees || []).length ? r.d.vitrine.masquees : null; });
    await ouvrir(v, VITRINE, "#contenu .vitrine-mur");
    const pendant = (await donneesVitrine(v)).affiches.length;
    const tampon = await evaluer(d, "(async () => { document.querySelector('dialog[open] .pancarte-tete button').click(); await new Promise(r => setTimeout(r, 400)); return document.querySelectorAll('.ruban-hors-vitrine').length; })()");
    await evaluer(d, "(() => { document.querySelector('button.affiche').closest('.affiche-case').querySelector('button.affiche').click(); return 1; })()");
    await pause(600);
    await evaluer(d, "(() => { const i = document.querySelector('dialog[open] .reglage-vitrine input[role=switch]'); i.click(); return 1; })()", true);
    await attendre(async () => { const r = await api(d, "/tableau/equipage/api/equipage"); return !(r.d.vitrine.masquees || []).length; });
    await evaluer(d, "(() => { const b = document.querySelector('dialog[open] .pancarte-tete button'); if (b) b.click(); return 1; })()");
    const apres = (await donneesVitrine(v)).affiches.length;
    return { ok: !!masquees && pendant === avant - 1 && tampon >= 1 && apres === avant,
      detail: `« ${String(nom).replace("Affiche de ", "").split(",")[0]} » : ${avant} → ${pendant} → ${apres} affiche(s) sur la vitrine · tampon « Hors vitrine » : ${tampon}` };
  });

  await etape(d, "Direction : un bloc rendu public paraît sur la vitrine (« Sur la vitrine »), puis s'en retire", async () => {
    if (!await ouvrir(d, BASE + "/tableau/equipage/#accueil", "#contenu .barre-edition")) return { ok: false, detail: "pas de barre d'édition" };
    await cliquer(d, ".barre-edition button", "Modifier l'accueil");
    await pause(500);
    const ok1 = await evaluer(d, `(() => { const b = [...document.querySelectorAll('.bloc-honneur .bascule-vitrine')][0]; if (!b) return false; b.click(); return true; })()`);
    if (!ok1) return { ok: false, detail: "bouton « Sur la vitrine » introuvable" };
    await attendre(async () => (await api(d, "/tableau/equipage/api/accueil")).d.blocs.some((b) => b.type === "honneur" && b.public));
    await ouvrir(v, VITRINE, "#contenu .vitrine-mur");
    const vu = (await texte(v)).includes("Équipiers à l'honneur");
    await evaluer(d, `(() => { document.querySelector('.bloc-honneur .bascule-vitrine').click(); return 1; })()`);
    await attendre(async () => !(await api(d, "/tableau/equipage/api/accueil")).d.blocs.some((b) => b.type === "honneur" && b.public));
    await ouvrir(v, VITRINE, "#contenu .vitrine-mur");
    const parti = !(await texte(v)).includes("Équipiers à l'honneur");
    await cliquer(d, ".barre-edition button", "Terminer");
    return { ok: vu && parti, detail: `visible sur la vitrine : ${vu} · retiré : ${parti}` };
  });
}

// ═══ L'ÉQUIPAGE ACTUEL : un départ, un retour (27/10/2026) ═════════════════
async function parcoursDepart(d, v) {
  await etape(d, "Un membre quitte le clan : son affiche quitte la vitrine, l'atelier la garde (« Ancien membre »), son retour la rend", async () => {
    const affs = (await api(d, "/tableau/espace/api/rell/affiches")).d.affiches;
    const clan = new Set((await api(d, "/tableau/espace/donnees")).d.clan.membres.map((m) => String(m.id)));
    const vues = new Set((await donneesVitrine(v)).affiches.map((a) => a.roblox.nom));
    const a = affs.find((x) => !x.retire_le && x.membre && clan.has(String(x.membre.id)) && x.roblox && vues.has(x.roblox.nom));
    if (!a) return { ok: false, detail: "aucune affiche d'un membre du clan sur la vitrine" };
    const action = (nom) => ecrire(d, "/tableau/espace/action", { action: nom, membre: String(a.membre.id) });
    const r1 = await action("clan_retirer");
    if (r1.st !== 200) return { ok: false, detail: "rôle du clan non retiré : " + r1.st };
    await ouvrir(v, VITRINE, "#contenu .vitrine-mur");
    const partie = !(await donneesVitrine(v)).affiches.some((x) => x.roblox.nom === a.roblox.nom);
    //  L'atelier de la direction : l'affiche est là, avec sa mention.
    await ouvrir(d, BASE + "/tableau/espace/#capitainerie/affiches", "#contenu .titre-rubrique");
    await evaluer(d, `(() => { const i = document.querySelector('#contenu .outils input[type=search]'); i.value = ${JSON.stringify(a.roblox.nom)};
      i.dispatchEvent(new Event("input", { bubbles: true })); return 1; })()`);
    const mention = await attendre(() => evaluer(d, `(() => { const r = document.querySelector('#contenu .affiche.affiche-ancienne .ruban-ancien');
      if (!r) return null; r.closest('.affiche').scrollIntoView({ block: "center" }); return r.innerText; })()`), 8000);
    await pause(400);
    const capture = await d.s("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(SORTIE, "atelier-ancien-membre.png"), Buffer.from(capture.data, "base64"));
    const r2 = await action("clan_ajouter");
    await ouvrir(v, VITRINE, "#contenu .vitrine-mur");
    const revenue = (await donneesVitrine(v)).affiches.some((x) => x.roblox.nom === a.roblox.nom);
    const gardee = (await api(d, "/tableau/espace/api/rell/affiches")).d.affiches.some((x) => x.id === a.id && !x.retire_le);
    return { ok: partie && /Ancien membre/.test(mention || "") && r2.st === 200 && revenue && gardee,
      detail: `« ${a.roblox.nom} » : hors de la vitrine ${partie} · atelier : « ${mention} » · rôle rendu, de retour : ${revenue} · jamais supprimée : ${gardee}` };
  });
}

// ═══ LES ÉQUIPES ═══════════════════════════════════════════════════════════
async function parcoursEquipes(d) {
  let chef = null, membres = [];
  await etape(d, "Direction : créer une équipe et nommer son chef (L'Équipage › Équipage, la vue « Équipes », l'éditeur)", async () => {
    if (!await ouvrir(d, BASE + "/tableau/espace/#equipage/membres", "#contenu .titre-rubrique")) return { ok: false, detail: "rubrique absente" };
    const clan = (await api(d, "/tableau/espace/donnees")).d.clan.membres;
    const equipes = (await api(d, "/tableau/espace/api/equipage/equipes")).d.equipes;
    const places = new Set(equipes.flatMap((e) => [e.chef && e.chef.id, ...e.membres.map((m) => m.id)]).filter(Boolean));
    const libres = clan.filter((m) => !places.has(String(m.id))).sort((a, b) => a.nom.localeCompare(b.nom, "fr"));
    if (libres.length < 3) return { ok: false, detail: "pas assez de membres sans équipe" };
    [chef, ...membres] = libres.slice(0, 3);
    await cliquer(d, "#contenu .sous-onglets a", "Équipes");   // la vue « Équipes » (27/10 : un sous-onglet)
    await pause(800);
    if (!await cliquer(d, "button", "Nouvelle équipe")) return { ok: false, detail: "« Nouvelle équipe » absent" };
    await pause(600);
    await evaluer(d, `(() => { const i = document.querySelector('dialog[open] input.saisie'); i.value = ${JSON.stringify(NOM_EQUIPE)}; i.dispatchEvent(new Event("input", { bubbles: true })); return 1; })()`);
    if (!await choisir(d, "Type d'équipe", "Pêche")) return { ok: false, detail: "type « Pêche » introuvable" };
    await pause(300);
    const choixChef = await evaluer(d, `(() => { const l = [...document.querySelectorAll('dialog[open] input[name=chef-equipe]')].find((x) => x.value === ${JSON.stringify(String(chef.id))});
      if (!l) return false; l.click(); return true; })()`);
    await pause(300);
    const choixMembres = await evaluer(d, `(() => { let n = 0; for (const id of ${JSON.stringify(membres.map((m) => String(m.id)))}) {
      const c = [...document.querySelectorAll('dialog[open] input[type=checkbox]')].find((x) => x.value === id); if (c) { c.click(); n += 1; } } return n; })()`);
    if (!choixChef || choixMembres !== 2) return { ok: false, detail: `chef : ${choixChef} · membres cochés : ${choixMembres}` };
    await cliquer(d, "dialog[open] button", "Créer l'équipe");
    const e = await attendre(async () => (await api(d, "/tableau/espace/api/equipage/equipes")).d.equipes.find((x) => x.nom === NOM_EQUIPE));
    const ferme = await attendre(() => evaluer(d, "!document.querySelector('dialog[open]')"), 5000);
    const ok = e && e.chef && e.chef.id === String(chef.id) && e.membres.map((m) => m.id).sort().join() === membres.map((m) => String(m.id)).sort().join()
      && e.type && e.type.nom === "Pêche";
    return { ok: !!ok && !!ferme, detail: e ? `« ${e.nom} » · ${e.type && e.type.nom} · chef : ${e.chef && e.chef.nom} · membres : ${e.membres.map((m) => m.nom).join(", ")}` : "l'équipe n'est pas enregistrée" };
  });
  return { chef, membres };
}

async function parcoursChefEtMembre(d, chef, membre) {
  const c = await personne("chef", "/tableau/demo?qui=equipage&id=" + chef.id);
  const m = await personne("membre", "/tableau/demo?qui=equipage&id=" + membre.id);
  await etape(c, "Le chef voit « Mon équipe » : ceux qu'il a sous sa main", async () => {
    if (!await ouvrir(c, BASE + "/tableau/equipage/#fiche", ".mon-equipe")) return { ok: false, detail: "« Mon équipe » absent" };
    await evaluer(c, "(() => { document.querySelector('.mon-equipe').scrollIntoView({ block: 'start' }); return 1; })()");
    const t = await evaluer(c, "document.querySelector('.mon-equipe').innerText");
    const r = (await api(c, "/tableau/equipage/api/equipage")).d.mon_equipe;
    return { ok: t.includes(NOM_EQUIPE) && /Sous ta main/i.test(t) && t.includes(membre.nom) && r && r.role === "chef",
      detail: t.replace(/\s+/g, " ").slice(0, 160) };
  });
  await etape(m, "Un membre voit son équipe sur « Ma fiche », son chef mis en avant", async () => {
    if (!await ouvrir(m, BASE + "/tableau/equipage/#fiche", ".mon-equipe")) return { ok: false, detail: "« Mon équipe » absent" };
    await evaluer(m, "(() => { document.querySelector('.mon-equipe').scrollIntoView({ block: 'start' }); return 1; })()");
    const t = await evaluer(m, "document.querySelector('.mon-equipe').innerText");
    const chefMisEnAvant = await evaluer(m, "!!document.querySelector('.mon-equipe .equipe-chef .equipe-chef-titre')");
    const r = (await api(m, "/tableau/equipage/api/equipage")).d.mon_equipe;
    return { ok: t.includes(NOM_EQUIPE) && t.includes(chef.nom) && chefMisEnAvant && r && r.role === "membre", detail: t.replace(/\s+/g, " ").slice(0, 160) };
  });
  await etape(c, "Tri par type d'équipe, puis par hiérarchie (les chefs d'abord)", async () => {
    if (!await ouvrir(c, BASE + "/tableau/equipage/#equipage", "#contenu .titre-rubrique")) return { ok: false, detail: "onglet absent" };
    await cliquer(c, ".segment button", "Les équipes");
    if (!await choisir(c, "Trier", "Par type")) return { ok: false, detail: "tri par type introuvable" };
    await pause(400);
    const types = await evaluer(c, "[...document.querySelectorAll('.equipes-type')].map((x) => x.innerText.trim())");
    if (!await choisir(c, "Trier", "Par hiérarchie")) return { ok: false, detail: "tri par hiérarchie introuvable" };
    await pause(400);
    const lignes = await evaluer(c, "[...document.querySelectorAll('.hierarchie-ligne')].map((x) => ({ chef: x.classList.contains('chef'), t: x.innerText.replace(/\\s+/g, ' ').trim() }))");
    const nbChefs = lignes.filter((x) => x.chef).length;
    const chefsDabord = lignes.slice(0, nbChefs).every((x) => x.chef) && lignes.slice(nbChefs).every((x) => !x.chef);
    const rangs = lignes.map((x) => Number(x.t.split(" ")[0]));
    return { ok: types.length >= 2 && types.includes("Pêche") && nbChefs >= 3 && chefsDabord && rangs.every((n, i) => n === i + 1),
      detail: `types : ${types.join(" · ")} · hiérarchie : ${lignes.length} lignes, ${nbChefs} chefs en tête` };
  });
  await etape(m, "L'équipage ne peut rien écrire ni lire des équipes de la direction (403)", async () => {
    const r1 = await ecrire(m, "/tableau/espace/api/equipage/equipe", { nom: "Pirates", chef: String(membre.id), membres: [] });
    const r2 = await api(m, "/tableau/espace/api/equipage/equipes");
    const r3 = await ecrire(m, "/tableau/espace/api/equipage/equipe/supprimer", { id: "abcdefgh" });
    return { ok: r1.st === 403 && r2.st === 403 && r3.st === 403, detail: `écrire : ${r1.st} · lire : ${r2.st} · supprimer : ${r3.st}` };
  });
  await etape(d, "Direction : la fiche du chef porte sa ligne « Équipe : … · chef d'équipe »", async () => {
    if (!await ouvrir(d, BASE + "/tableau/espace/#equipage/membres", "#contenu .titre-rubrique")) return { ok: false, detail: "rubrique absente" };
    //  Comme une personne : chercher le chef dans la rubrique, puis ouvrir sa ligne.
    await evaluer(d, `(() => { const i = document.querySelector('#contenu .outils input[type=search]'); i.value = ${JSON.stringify(chef.nom)};
      i.dispatchEvent(new Event("input", { bubbles: true })); return 1; })()`);
    await pause(700);
    const ouverte = await evaluer(d, `(() => { const l = [...document.querySelectorAll('#contenu .lc-clic')].find((x) => x.getClientRects().length && x.textContent.includes(${JSON.stringify(chef.nom)}));
      if (!l) return false; l.click(); return true; })()`);
    if (!ouverte) return { ok: false, detail: "ligne du chef introuvable" };
    const ligne = await attendre(() => evaluer(d, "(() => { const x = document.querySelector('dialog[open] .fiche-equipe'); return x && /Équipe :/.test(x.innerText) && x.innerText.includes(" + JSON.stringify(NOM_EQUIPE) + ") ? x.innerText : null; })()"), 8000);
    return { ok: !!ligne && /chef d'équipe/i.test(ligne), detail: ligne ? ligne.replace(/\s+/g, " ") : "ligne absente" };
  });
}

// ─── Le tout ────────────────────────────────────────────────────────────────
async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  const nav = await lancerNavigateur();
  console.log("Navigateur : " + nav.exe + "\nCaptures : " + SORTIE);
  try {
    await connecter(nav.wsUrl);
    const visiteur = await personne("visiteur", "");
    const direction = await personne("direction", "/tableau/demo");
    await parcoursVisiteur(visiteur);
    await parcoursDirectionVitrine(direction, visiteur);
    await parcoursDepart(direction, visiteur);
    const { chef, membres } = await parcoursEquipes(direction);
    if (chef && membres.length) await parcoursChefEtMembre(direction, chef, membres[0]);
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
