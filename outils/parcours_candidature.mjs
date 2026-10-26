// outils/parcours_candidature.mjs — le questionnaire en ligne joué À DEUX, dans deux navigateurs sans fenêtre (profils
// séparés : deux cookies, deux personnes) contre le VRAI serveur local.
//
//   C = le candidat du ticket #60 (Tobias), sur TÉLÉPHONE (375 × 812, tactile) : /tableau/demo?qui=candidat&ticket=60
//       — son lien personnel, une session « candidat » ; trois étapes, la première ouverte (la fiche est son étape 1).
//   D = la direction, sur PC (1366 × 768) : /tableau/demo?qui=direction, le dossier du ticket #60, bloc « En direct ».
//
//   C tape → D voit le texte s'écrire (délai mesuré, « En train d'écrire ») ; la connexion de C coupée : il écrit quand
//   même, ferme la page, revient → rien de perdu ; C envoie l'étape → D le voit ; la direction ouvre l'étape suivante →
//   la page de C la montre ; … la dernière → « Merci » chez C, « Réponses reçues » et la correction chez D ; C ne peut
//   rien ouvrir d'autre (pages et API de la direction, le direct, l'équipage, un autre ticket) ; enfin un questionnaire
//   d'avant (#61, tout en une fois) sur le même téléphone. Une capture par navigateur et par étape.
//
//   node outils/parcours_candidature.mjs [--url http://localhost:8807] [--sortie <dossier>] [--navigateur <exe>]
//
// La base du site local change à chaque parcours : relancer le site local avant de rejouer.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const BASE = String(opt("url", "http://localhost:8807")).replace(/\/+$/, "");
const SITE = BASE + "/tableau/espace/";
const PAGE_CANDIDAT = BASE + "/tableau/candidature/";
const SORTIE = opt("sortie", join(tmpdir(), "capitainerie-candidature"));
const TICKET = 60;
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);
const pause = (ms) => new Promise((ok) => setTimeout(ok, ms));

// ─── Un navigateur sans fenêtre, son profil, son protocole DevTools ─────────
class Navigateur {
  constructor(nom) { this.nom = nom; this.attente = new Map(); this.prochain = 1; this.ecouteurs = []; this.erreurs = []; this.trames = []; this.sockets = []; this.requetes = []; }
  /** Les requêtes du questionnaire depuis `t0` : « +1,2 s brouillon 200 ». */
  journal(t0, filtre = /./) {
    return this.requetes.filter((x) => x.t >= t0 && filtre.test(x.nom)).map((x) => "+" + ((x.t - t0) / 1000).toFixed(1) + " s " + x.nom.split("?")[0] + " " + x.statut).join(", ");
  }
  async lancer(port) {
    const exe = NAVIGATEURS.find((p) => existsSync(p));
    if (!exe) throw new Error("Aucun Edge ni Chrome trouvé (option --navigateur <exe>).");
    this.exe = exe;
    this.profil = mkdtempSync(join(tmpdir(), "capitainerie-candidature-" + this.nom + "-"));
    this.proc = spawn(exe, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${this.profil}`, "--no-first-run", "--no-default-browser-check",
      "--disable-extensions", "--disable-sync", "--disable-features=Translate,MediaRouter,OptimizationHints", "--lang=fr-FR", "about:blank"], { stdio: "ignore" });
    for (let i = 0; i < 80; i++) {
      try {
        const r = await fetch(`http://127.0.0.1:${port}/json/version`);
        if (r.ok) { await this.connecter((await r.json()).webSocketDebuggerUrl); return; }
      } catch (e) { /* pas encore */ }
      await pause(250);
    }
    throw new Error(this.nom + " : le navigateur ne répond pas sur le port " + port);
  }
  async connecter(url) {
    this.ws = new WebSocket(url);
    await new Promise((ok, ko) => { this.ws.onopen = ok; this.ws.onerror = ko; });
    this.ws.onmessage = (m) => {
      const d = JSON.parse(typeof m.data === "string" ? m.data : m.data.toString());
      if (d.id && this.attente.has(d.id)) {
        const a = this.attente.get(d.id);
        this.attente.delete(d.id);
        if (d.error) a.ko(new Error(a.methode + " : " + d.error.message)); else a.ok(d.result);
      } else if (d.method) for (const f of this.ecouteurs) f(d);
    };
  }
  envoyer(methode, params = {}, sessionId) {
    const id = this.prochain++;
    this.ws.send(JSON.stringify({ id, method: methode, params, sessionId }));
    return new Promise((ok, ko) => this.attente.set(id, { ok, ko, methode }));
  }
  async onglet(largeur, hauteur, telephone) {
    const { targetId } = await this.envoyer("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await this.envoyer("Target.attachToTarget", { targetId, flatten: true });
    this.s = (m, p) => this.envoyer(m, p, sessionId);
    for (const m of ["Page.enable", "Runtime.enable", "Log.enable", "Network.enable"]) await this.s(m);
    this.ecouteurs.push((d) => {
      if (d.sessionId !== sessionId) return;
      const p = d.params || {};
      if (d.method === "Runtime.exceptionThrown") this.erreurs.push("exception : " + ((p.exceptionDetails.exception || {}).description || p.exceptionDetails.text));
      if (d.method === "Runtime.consoleAPICalled" && p.type === "error") this.erreurs.push("console : " + p.args.map((a) => a.value ?? a.description ?? "").join(" "));
      if (d.method === "Log.entryAdded" && p.entry.level === "error" && !/favicon|\/s\/(icones\/rell|logos)\//.test(p.entry.url || "")) this.erreurs.push("journal : " + p.entry.text + (p.entry.url ? " (" + p.entry.url + ")" : ""));
      if (d.method === "Network.requestWillBeSent" && /\/tableau\/candidature\/api\//.test(p.request.url)) this.requetes.push({ id: p.requestId, t: Date.now(), nom: p.request.url.split("/api/")[1], statut: 0 });
      if (d.method === "Network.responseReceived" || d.method === "Network.loadingFailed") {
        const q = this.requetes.find((x) => x.id === p.requestId);
        if (q) q.statut = d.method === "Network.loadingFailed" ? "échec" : p.response.status;
      }
      if (d.method === "Network.webSocketCreated") this.sockets.push({ url: p.url, id: p.requestId });
      if (d.method === "Network.webSocketHandshakeResponseReceived") { const s = this.sockets.find((x) => x.id === p.requestId); if (s) s.statut = p.response.status; }
      if (d.method === "Network.webSocketFrameReceived") {
        const r = p.response || {};
        if (r.opcode === 1) { let t = "?"; try { t = JSON.parse(r.payloadData).t; } catch (e) { /* pas du JSON */ } this.trames.push({ t: Date.now(), genre: t, taille: Buffer.byteLength(r.payloadData || "") }); }
      }
    });
    await this.s("Emulation.setDeviceMetricsOverride", { width: largeur, height: hauteur, deviceScaleFactor: telephone ? 2 : 1, mobile: !!telephone });
    if (telephone) await this.s("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  }
  async evaluer(expression) {
    const r = await this.s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(this.nom + " : " + ((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text));
    return r.result.value;
  }
  async capture(fichier) {
    try { const c = await this.s("Page.captureScreenshot", { format: "png" }); writeFileSync(fichier, Buffer.from(c.data, "base64")); } catch (e) { /* capture impossible */ }
  }
  api(chemin) { return this.evaluer(`fetch(${JSON.stringify(SITE + "api/" + chemin)}, { credentials: "same-origin", headers: { "X-Tableau": "1" } }).then((r) => r.json())`); }
  async fermer() {
    try { await this.envoyer("Browser.close"); } catch (e) { /* déjà fermé */ }
    await pause(400);
    try { this.proc.kill(); } catch (e) { /* rien */ }
    try { rmSync(this.profil, { recursive: true, force: true }); } catch (e) { /* le profil temporaire reste */ }
  }
}
async function attendre(fn, ms = 15000, pas = 250) {
  const t0 = Date.now();
  let v = null;
  while (Date.now() - t0 < ms) {
    try { v = await fn(); } catch (e) { v = null; }
    if (v) return v;
    await pause(pas);
  }
  return v;
}

// ─── Les gestes ─────────────────────────────────────────────────────────────
const VISIBLE = "(x) => x.getClientRects().length && getComputedStyle(x).visibility !== 'hidden' && !x.closest('[inert]')";
//  « dialog[open] … » : dans la DERNIÈRE fenêtre ouverte (une confirmation par-dessus un dossier).
const cliquer = (n, selecteur, texte) => n.evaluer(`(() => { const vis = ${VISIBLE}; const sel = ${JSON.stringify(selecteur)};
  const racine = sel.startsWith("dialog[open] ") ? [...document.querySelectorAll("dialog[open]")].pop() : document;
  if (!racine) return false;
  const el = [...racine.querySelectorAll(sel.startsWith("dialog[open] ") ? sel.slice(13) : sel)].find((x) => vis(x) && !x.disabled && (x.textContent || x.getAttribute("aria-label") || "").replace(/\\s+/g, " ").includes(${JSON.stringify(texte)}));
  if (!el) return false; el.scrollIntoView({ block: "center" }); el.click(); return true; })()`);
/** La page du candidat : sa vue, le titre de l'étape, le petit mot « Enregistré », ses champs, un débordement. */
const pageC = (C) => C.evaluer(`(() => { const t = document.querySelector('#etape-titre, #attente-titre, #merci-titre, #message-titre, #relire-titre');
  const e = window.__candidature ? window.__candidature.etat() : {};
  return { vue: e.vue || "", horsLigne: !!e.horsLigne, sales: e.sales || [], titre: t ? t.innerText.replace(/\\s+/g, " ").trim() : "",
    enr: ((document.querySelector('#etat-enr') || {}).className || "").replace("cand-etat-enr", "").trim(),
    enrTexte: ((document.querySelector('#etat-enr') || {}).innerText || "").trim(),
    zones: Object.fromEntries([...document.querySelectorAll('textarea.cand-reponse')].map((z) => [z.id.slice(2), z.value])),
    compte: ((document.querySelector('.cand-compte') || {}).innerText || "").trim(),
    debord: document.documentElement.scrollWidth > innerWidth + 1 }; })()`);
/** Taper comme au clavier (une lettre à la fois, au rythme d'un pouce rapide). */
async function taper(C, rang, texte, pasMs = 70) {
  const ok = await C.evaluer(`(() => { const z = document.querySelector('#q-${rang}'); if (!z) return false; z.scrollIntoView({ block: 'center' }); z.focus();
    z.setSelectionRange(z.value.length, z.value.length); return true; })()`);
  if (!ok) throw new Error("champ de la question " + rang + " introuvable");
  for (const ch of texte) { await C.s("Input.insertText", { text: ch }); await pause(pasMs); }
}
/** Remplir les questions vides de l'étape à l'écran. */
const remplir = (C, prefixe) => C.evaluer(`(async () => { let n = 0; for (const z of document.querySelectorAll('textarea.cand-reponse')) { if (!z.value.trim()) {
  z.focus(); z.value = ${JSON.stringify(prefixe)} + ' (question ' + z.id.slice(2) + ')'; z.dispatchEvent(new Event('input', { bubbles: true })); n++; } }
  await new Promise((r) => setTimeout(r, 1800)); return n; })()`);
/** « Envoyer cette étape » (ou « Envoyer mes réponses »), puis la confirmation. */
async function envoyer(C, libelle) {
  if (!await cliquer(C, "button.cand-envoyer", libelle)) return "bouton « " + libelle + " » absent";
  if (!await attendre(() => C.evaluer("!!document.querySelector('dialog[open]')"), 5000)) return "pas de confirmation";
  await pause(300);
  if (!await cliquer(C, "dialog[open] button", libelle)) return "confirmation sans « " + libelle + " »";
  return (await attendre(() => C.evaluer("!!document.querySelector('.cand-attente, .cand-merci')"), 15000)) ? "" : "ni attente ni merci après l'envoi";
}
/** La page revient au premier plan (le candidat revient de Discord) : elle relit son questionnaire. */
async function revenir(C) {
  await pause(4300);   // la relecture légère : pas plus d'une toutes les 4 s
  await C.evaluer("(() => { dispatchEvent(new Event('focus')); return true; })()");
}
const ouvrirEtapeSuivante = () => fetch(BASE + "/tableau/demo/etape_suivante?ticket=" + TICKET).then((r) => r.json());
/** Une adresse de démonstration du site local (le faux Discord, le vrai chemin du bot) : sa réponse JSON. */
const demo = (chemin) => fetch(BASE + "/tableau/demo/" + chemin, { cache: "no-store" }).then((r) => r.json());
/** Les messages du bot dans le fil d'un ticket, tels qu'ils sont maintenant (le faux Discord). */
const messagesTicket = async (tid) => ((await demo("discord?ticket=" + tid)).messages || []);
/** Une écriture du site de la direction, par la session de D (la même route que ses boutons). */
const posterD = (D, nom, corps) => D.evaluer(`fetch(${JSON.stringify(SITE + "api/")} + ${JSON.stringify(nom)}, { method: "POST", credentials: "same-origin",
  headers: { "X-Tableau": "1", "Content-Type": "application/json" }, body: ${JSON.stringify(JSON.stringify(corps))} }).then(async (r) => ({ status: r.status, corps: await r.json() }))`);
const fermerFenetres = (D) => D.evaluer("(() => { for (const d of [...document.querySelectorAll('dialog[open]')].reverse()) d.close(); return true; })()");
/** Une page du site de la direction, relue (on passe par une autre : la même adresse ne redessinerait rien). */
async function allerD(D, ancre) {
  await fermerFenetres(D).catch(() => null);
  await D.s("Page.navigate", { url: SITE + "#accueil/attente" });
  await pause(300);
  await D.s("Page.navigate", { url: SITE + ancre });
  const pret = await attendre(() => D.evaluer("!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 15000);
  await pause(500);
  return pret;
}
/** Ouvre la ligne `selecteur` d'une liste (ses groupes dépliés), puis attend la fenêtre. */
async function ouvrirLigne(D, selecteur, attendu) {
  const ok = await attendre(() => D.evaluer(`(() => { for (const g of document.querySelectorAll('#contenu details.groupe')) g.open = true;
    const li = document.querySelector(${JSON.stringify(selecteur)}); const b = li && li.querySelector('.lc-ouvrir');
    if (!b) return false; b.scrollIntoView({ block: 'center' }); b.click(); return true; })()`), 10000);
  return ok && attendre(() => D.evaluer(`!!document.querySelector(${JSON.stringify("dialog[open] " + attendu)})`), 15000);
}
/** Le dossier d'un ticket (la zone « Demande de recrutement ») ; `direct` : attendre le bloc « En direct ». */
async function ouvrirDossier(D, ticket, direct = true) {
  if (!await allerD(D, "#capitainerie/recrutement")) return false;
  if (!await ouvrirLigne(D, `#contenu li.lc[data-ticket="${ticket}"]`, ".dossier-tete")) return false;
  if (!direct) return true;
  return attendre(() => D.evaluer("(() => { const d = document.querySelector('dialog[open] .en-direct'); if (!d || !d.querySelector('.en-direct-etape')) return false; d.scrollIntoView({ block: 'start' }); return true; })()"), 15000);
}
/** La candidature d'un chef d'équipe (Capitainerie › Demande de recrutement › Chefs), son bloc « En direct ». */
async function ouvrirCandidatureChef(D, envoi, direct = true) {
  if (!await allerD(D, "#capitainerie/recrutement/chefs")) return false;
  if (!await ouvrirLigne(D, `#contenu li.lc[data-envoi="${envoi}"]`, ".correction-barre")) return false;
  if (!direct) return true;
  return attendre(() => D.evaluer("(() => { const d = document.querySelector('dialog[open] .en-direct'); if (!d || !d.querySelector('.en-direct-etape')) return false; d.scrollIntoView({ block: 'start' }); return true; })()"), 15000);
}
/** Coche « Juste » sur chaque réponse de la fenêtre ouverte (une à une : la page se redessine après chacune). */
async function toutJuste(D) {
  let n = 0;
  for (let k = 0; k < 30; k++) {
    const fait = await D.evaluer(`(() => { const b = [...document.querySelectorAll('dialog[open] .bouton-juste')].find((x) => x.getAttribute('aria-pressed') !== 'true' && !x.disabled);
      if (!b) return false; b.scrollIntoView({ block: 'center' }); b.click(); return true; })()`);
    if (!fait) break;
    n += 1;
    await pause(450);
  }
  return n;
}
const etatDirect = (D) => D.evaluer("(() => { const e = document.querySelector('dialog[open] .en-direct .en-direct-etat'); return e ? e.innerText.trim() : null; })()");
const reponseDirect = (D, rang) => D.evaluer(`(() => { const li = [...document.querySelectorAll('dialog[open] .en-direct .en-direct-q')].find((x) => ((x.querySelector('.en-direct-num') || {}).textContent || '') === '${rang}');
  if (!li) return null; const r = li.querySelector('.en-direct-reponse'); li.scrollIntoView({ block: 'center' });
  return { texte: r && !r.querySelector('.aide') ? r.innerText.trim() : '', actif: li.classList.contains('actif'), ecrit: ((li.querySelector('.en-direct-ecrit') || {}).innerText || '').trim() }; })()`);
const toasts = (D) => D.evaluer("[...document.querySelectorAll('#toasts > *')].map((t) => t.innerText.replace(/\\s+/g, ' ').trim())");

/** Le délai entre la frappe du candidat et le texte chez la direction : le premier caractère vu, puis le mot entier. */
async function mesurer(C, D, rang, mot) {
  const avant = ((await reponseDirect(D, rang)) || {}).texte || "";
  const debut = Date.now();
  let premier = 0, enTrain = false;
  const veille = (async () => {
    while (Date.now() - debut < 20000) {
      const r = await reponseDirect(D, rang);
      if (r && r.texte && r.texte !== avant && !premier) premier = Date.now();
      if (r && (r.actif || /en train d'écrire/i.test(r.ecrit))) enTrain = true;
      if (r && r.texte.endsWith(mot.trim())) return Date.now();
      await pause(40);
    }
    return 0;
  })();
  await taper(C, rang, mot);
  const finFrappe = Date.now();
  const vu = await veille;
  return { premierCaractereMs: premier ? premier - debut : null, motEntierMs: vu ? vu - finFrappe : null, frappeMs: finFrappe - debut, enTrain };
}

// ─── Le rapport ─────────────────────────────────────────────────────────────
const resultats = [];
let numero = 0;
async function etape(nom, navs, fn, o = {}) {
  numero += 1;
  const debut = navs.map((n) => n.erreurs.length);
  let ok = false, detail = "";
  try {
    const r = await fn();
    ok = r === true || (r && r.ok === true);
    detail = r && r !== true ? ("detail" in r ? String(r.detail || "") : JSON.stringify(r).slice(0, 500)) : "";
  } catch (e) { detail = "exception : " + e.message; }
  const erreurs = navs.flatMap((n, i) => n.erreurs.slice(debut[i]).filter((x) => !(o.attendus && o.attendus.test(x))).map((x) => n.nom + " " + x));
  if (erreurs.length) { ok = false; detail += (detail ? " · " : "") + erreurs.slice(0, 3).join(" | "); }
  const captures = [];
  for (const n of navs) {
    const f = join(SORTIE, String(numero).padStart(2, "0") + "-" + n.nom + "-" + nom.replace(/[^a-z0-9]+/gi, "-").toLowerCase().slice(0, 60) + ".png");
    await n.capture(f);
    captures.push(f);
  }
  resultats.push({ nom, ok, detail, captures });
  console.log(`${ok ? "ok    " : "ÉCHEC "} ${nom}${detail ? "\n        · " + detail : ""}`);
  return ok;
}

// ═══ LE PARCOURS ════════════════════════════════════════════════════════════
async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  const C = new Navigateur("C-candidat"), D = new Navigateur("D-direction");
  const port = 9960 + Math.floor(Math.random() * 300);
  await Promise.all([C.lancer(port), D.lancer(port + 1)]);
  console.log("Navigateurs : " + C.exe + " (deux profils séparés)\nCaptures : " + SORTIE);
  const mesures = { delais: [] };
  let envoi = 0;
  //  « À chaque instant, au plus deux messages du bot dans le ticket » : un relevé CONTINU (toutes les 120 ms) du fil du
  //  vrai ticket, de la demande à la décision — pas seulement entre deux étapes.
  const releve = { tid: 0, actif: true, n: 0, max: 0, pire: [] };
  const releveur = (async () => {
    while (releve.actif) {
      if (releve.tid) {
        const m = await messagesTicket(releve.tid).catch(() => null);
        if (m) {
          releve.n++;
          if (m.length > releve.max) { releve.max = m.length; releve.pire = m.map((y) => (y.texte || "").slice(0, 60)); }
        }
      }
      await pause(120);
    }
  })();
  try {
    await C.onglet(375, 812, true);
    await D.onglet(1366, 768, false);
    await D.s("Page.navigate", { url: BASE + "/tableau/demo?qui=direction" });

    await etape("C ouvre son lien sur son téléphone : « Étape 2 sur 4 » (la fiche est l'étape 1), ses brouillons, rien qui déborde", [C], async () => {
      await C.s("Page.navigate", { url: BASE + "/tableau/demo?qui=candidat&ticket=" + TICKET });
      const p = await attendre(async () => { const x = await pageC(C); return x.vue === "etape" && Object.keys(x.zones).length ? x : null; }, 15000);
      if (!p) return { ok: false, detail: "la page du candidat ne s'ouvre pas : " + JSON.stringify(await pageC(C).catch(() => null)) };
      envoi = (await C.evaluer("window.__candidature.etat().envoi")) || 0;
      const brouillons = Object.values(p.zones).filter((v) => v.trim()).length;
      return { ok: /^Étape 2 sur 4/.test(p.titre) && brouillons === 2 && !p.debord && C.sockets.length === 0,
        detail: `« ${p.titre} » · ${Object.keys(p.zones).length} questions, ${brouillons} brouillons repris · ${p.compte} · débordement ${p.debord ? "OUI" : "non"} · WebSocket chez le candidat : ${C.sockets.length}` };
    });

    await etape("D ouvre le dossier du ticket #60 : le bloc « En direct » (WebSocket 101) dit la page ouverte", [D], async () => {
      if (!await ouvrirDossier(D, TICKET)) return { ok: false, detail: "dossier ou bloc « En direct » introuvable" };
      const etat = await attendre(async () => { const e = await etatDirect(D); return e && /Page ouverte|En train d'écrire/.test(e) ? e : null; }, 10000);
      const r1 = await reponseDirect(D, 1);
      const ws = D.sockets.filter((s) => s.url.includes("/tableau/espace/direct"));
      return { ok: !!etat && !!r1 && /studio/.test(r1.texte) && ws.some((s) => s.statut === 101),
        detail: `« ${etat || await etatDirect(D)} » · question 1 : « ${(r1 || {}).texte || ""} » · WebSocket ${ws.map((s) => s.statut).join("/") || "aucune"}` };
    });

    await etape("C tape : D voit le texte s'écrire en direct (délai mesuré, « En train d'écrire »)", [C, D], async () => {
      const essais = [];
      for (const [rang, mot] of [[3, "Le capitaine du Vent Noir"], [3, " et son second"], [1, " (je confirme)"]]) {
        essais.push(Object.assign({ rang }, await mesurer(C, D, rang, mot)));
        await pause(600);
      }
      mesures.delais = essais;
      const etat = await etatDirect(D);
      const finaux = essais.map((x) => x.motEntierMs);
      const ok = finaux.every((x) => x !== null && x < 2500) && essais.every((x) => x.premierCaractereMs !== null && x.premierCaractereMs < 2500) && essais.some((x) => x.enTrain);
      return { ok, detail: essais.map((x) => `q${x.rang} : 1er caractère ${x.premierCaractereMs} ms après le début, mot entier ${x.motEntierMs} ms après la dernière touche (frappe ${x.frappeMs} ms)${x.enTrain ? ", « en train d'écrire »" : ""}`).join(" · ") + ` · état : « ${etat} »` };
    });

    await etape("Le débit du direct reste borné pendant la frappe (au plus 4 messages « candidat » par seconde)", [D], async () => {
      const t0 = Date.now();
      await taper(C, 3, " — vu au large", 35);   // une frappe rapide : une lettre toutes les 35 ms
      await pause(900);
      const recus = D.trames.filter((x) => x.genre === "candidat" && x.t >= t0);
      const duree = (Date.now() - t0) / 1000;
      const max = Math.ceil(duree / 0.25) + 2;
      mesures.debit = { secondes: Math.round(duree * 10) / 10, messages: recus.length, plusGros: Math.max(0, ...recus.map((x) => x.taille)) };
      return { ok: recus.length > 0 && recus.length <= max, detail: `${recus.length} message(s) « candidat » en ${mesures.debit.secondes} s (borne ${max}), le plus gros ${mesures.debit.plusGros} octets` };
    });

    const HORS_LIGNE = "Écrit sans connexion, gardé quand même";
    let tCoupure = 0;
    await etape("La connexion de C coupée : il écrit quand même, « Pas de connexion », le texte reste sur son téléphone", [C], async () => {
      tCoupure = Date.now();
      await C.s("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
      await taper(C, 4, HORS_LIGNE, 40);
      const p = await attendre(async () => { const x = await pageC(C); return x.enr === "hors-ligne" ? x : null; }, 10000);
      const local = await C.evaluer(`(() => { try { return JSON.parse(localStorage.getItem('candidature.${envoi}') || 'null'); } catch (e) { return null; } })()`);
      const garde = !!local && (local.reponses || {})["4"] === HORS_LIGNE && (local.sales || []).includes("4");
      return { ok: !!p && garde, detail: `petit mot : « ${(p || {}).enrTexte || ""} » · gardé sur l'appareil : ${garde ? "oui" : "NON"}` };
    }, { attendus: /ERR_INTERNET_DISCONNECTED|Failed to fetch|net::ERR/ });

    await etape("C ferme la page sans connexion, la connexion revient, il rouvre : rien n'est perdu (et la direction le voit)", [C, D], async () => {
      await C.s("Page.navigate", { url: "about:blank" });
      await pause(600);
      await C.s("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
      await C.s("Page.navigate", { url: PAGE_CANDIDAT });
      const p = await attendre(async () => { const x = await pageC(C); return x.vue === "etape" && x.zones["4"] === HORS_LIGNE && x.enr === "ok" ? x : null; }, 20000);
      const serveur = await attendre(async () => { const d = await D.api("direct/candidat?ticket=" + TICKET); return d.reponses && d.reponses["4"] === HORS_LIGNE ? d : null; }, 10000);
      const chezD = await attendre(async () => { const r = await reponseDirect(D, 4); return r && r.texte === HORS_LIGNE ? r : null; }, 10000);
      return { ok: !!p && !!serveur && !!chezD, detail: `champ 4 : « ${(p || {}).zones ? p.zones["4"] : "?"} » · petit mot « ${(p || {}).enrTexte || ""} » · serveur : ${serveur ? "gardé" : "absent"} · direct de D : ${chezD ? "affiché" : "absent"}`
        + ` · requêtes depuis la coupure : ${C.journal(tCoupure, /brouillon|presence/)}` };
    }, { attendus: /ERR_INTERNET_DISCONNECTED|Failed to fetch|net::ERR/ });

    await etape("C envoie l'étape (confirmation) : « Réponses envoyées » chez lui, « il attend ta décision » chez D", [C, D], async () => {
      const vides = await remplir(C, "Réponse du téléphone");
      const err = await envoyer(C, "Envoyer cette étape");
      if (err) return { ok: false, detail: err };
      const p = await pageC(C);
      const etat = await attendre(async () => { const e = await etatDirect(D); return e && /envoyée · il attend ta décision/.test(e) ? e : null; }, 10000);
      const t = await attendre(async () => { const x = await toasts(D); return x.some((y) => /étape du questionnaire est arrivée/.test(y)) ? x : null; }, 6000);
      const serveur = await D.api("direct/candidat?ticket=" + TICKET);
      return { ok: p.vue === "attente" && /Réponses envoyées/.test(p.titre) && !!etat && serveur.portes.envoyee === 1 && serveur.etat === "attente",
        detail: `${vides} champ(s) remplis · C : « ${p.titre} » · D : « ${etat || await etatDirect(D)} » · avis D : ${t ? "« " + t.join(" | ") + " »" : "aucun"}` };
    });

    async function etapeSuivante(numero, total) {
      return etape(`La direction ouvre l'étape ${numero} : la page de C la montre quand il revient`, [C, D], async () => {
        const o = await ouvrirEtapeSuivante();
        if (!o.ok) return { ok: false, detail: "étape non ouverte : " + JSON.stringify(o) };
        const t0 = Date.now();
        await revenir(C);
        const p = await attendre(async () => { const x = await pageC(C); return x.vue === "etape" && x.titre.startsWith(`Étape ${numero} sur ${total}`) ? x : null; }, 30000);
        const etat = await attendre(async () => { const e = await etatDirect(D); return e && !/attend ta décision/.test(e) ? e : null; }, 10000);
        return { ok: !!p && Object.values(p.zones).every((v) => !v.trim()), detail: `C : « ${(p || {}).titre || (await pageC(C)).titre} » ${Math.round((Date.now() - t0) / 100) / 10} s après l'ouverture · D : « ${etat || await etatDirect(D)} »` };
      });
    }
    await etapeSuivante(3, 4);
    await etape("C remplit et envoie l'étape 3", [C, D], async () => {
      await remplir(C, "Réponse de l'étape 3");
      const err = await envoyer(C, "Envoyer cette étape");
      const p = await pageC(C);
      return { ok: !err && p.vue === "attente", detail: err || `C : « ${p.titre} »` };
    });
    await etapeSuivante(4, 4);

    await etape("C envoie la dernière étape : « Merci » chez lui ; « Réponses reçues » et la correction chez D", [C, D], async () => {
      await remplir(C, "Réponse de la dernière étape");
      const err = await envoyer(C, "Envoyer cette étape");
      if (err) return { ok: false, detail: err };
      const p = await attendre(async () => { const x = await pageC(C); return x.vue === "merci" ? x : null; }, 10000);
      const t = await attendre(async () => { const x = await toasts(D); return x.some((y) => /Réponses reçues/.test(y)) ? x : null; }, 15000);
      const correction = await attendre(() => D.evaluer("(() => { const b = document.querySelectorAll('dialog[open] .correction-liste .bouton-juste'); if (!b.length) return 0; b[0].closest('.correction').scrollIntoView({ block: 'center' }); return b.length; })()"), 15000);
      const dossier = await D.api("recrutement/dossier?ticket=" + TICKET);
      const e = (dossier.envois || []).find((x) => x.id === envoi) || {};
      return { ok: !!p && !!t && correction === 10 && e.statut === "repondu" && (e.bilan || {}).repondues === 10,
        detail: `C : « ${(p || {}).titre || ""} » · avis D : ${t ? "« " + t.filter((y) => /Réponses reçues/.test(y)).join("") + " »" : "aucun"} · ${correction} réponses à corriger · envoi ${e.statut}, ${(e.bilan || {}).repondues}/10` };
    });

    await etape("D corrige une réponse venue du site (« Juste »)", [D], async () => {
      if (!await cliquer(D, "dialog[open] .bouton-juste", "Juste")) return { ok: false, detail: "« Juste » introuvable" };
      const x = await attendre(async () => { const d = await D.api("recrutement/dossier?ticket=" + TICKET); const e = (d.envois || []).find((y) => y.id === envoi);
        return e && e.bilan.justes === 1 ? e : null; }, 10000);
      return { ok: !!x, detail: x ? `bilan : ${x.bilan.justes} juste(s), ${x.bilan.corrigees} corrigée(s)` : "correction non enregistrée" };
    });

    await etape("C ne peut rien ouvrir d'autre : pages et API de la direction, le direct, l'équipage, un autre ticket", [C], async () => {
      const r = await C.evaluer(`(async () => { const out = {};
        for (const [nom, url] of [["page de la direction", "/tableau/espace/"], ["dossier (API)", "/tableau/espace/api/recrutement/dossier?ticket=${TICKET}"],
          ["direct (API)", "/tableau/espace/api/direct/candidat?ticket=${TICKET}"], ["présence (WebSocket, en HTTP)", "/tableau/espace/direct"],
          ["site de l'équipage", "/tableau/equipage/"], ["API de l'équipage", "/tableau/equipage/api/accueil"]]) {
          const x = await fetch(url, { credentials: "include", headers: { "X-Tableau": "1" } }); out[nom] = x.status; }
        const q = await fetch("/tableau/candidature/api/questionnaire?ticket=63&envoi=1", { credentials: "include" }).then((x) => x.json());
        out["un autre ticket (paramètres ignorés)"] = q.envoi;
        return out; })()`);
      await C.s("Page.navigate", { url: SITE });
      await attendre(() => C.evaluer("document.readyState === 'complete' && !!document.querySelector('h1')"), 8000);
      const texte = await C.evaluer("document.body.innerText.replace(/\\s+/g, ' ').slice(0, 160)");
      const refus = Object.entries(r).filter(([k]) => !k.startsWith("un autre")).every(([, v]) => v === 403);
      return { ok: refus && r["un autre ticket (paramètres ignorés)"] === envoi && !/Capitainerie|Tableau de bord/.test(texte) && C.sockets.length === 0,
        detail: Object.entries(r).map(([k, v]) => k + " → " + v).join(" · ") + ` (son envoi : ${envoi}) · /tableau/espace/ affiche « ${texte} »` };
    }, { attendus: /status of 403/ });

    await etape("Un questionnaire d'avant (#61) sur le même téléphone : tout ouvert, « Relire et envoyer », un seul envoi", [C], async () => {
      await C.s("Page.navigate", { url: BASE + "/tableau/demo?qui=candidat&ticket=61" });
      const p = await attendre(async () => { const x = await pageC(C); return x.vue === "etape" && Object.keys(x.zones).length ? x : null; }, 15000);
      if (!p) return { ok: false, detail: "la page du #61 ne s'ouvre pas" };
      await remplir(C, "Réponse d'un questionnaire d'avant");
      if (!await cliquer(C, "button.cand-suivant", "Relire et envoyer")) return { ok: false, detail: "« Relire et envoyer » absent" };
      if (!await attendre(async () => (await pageC(C)).vue === "relire", 5000)) return { ok: false, detail: "pas de relecture" };
      const err = await envoyer(C, "Envoyer mes réponses");
      const f = await pageC(C);
      return { ok: !err && f.vue === "merci" && !f.debord, detail: err || `« ${p.titre} » (${Object.keys(p.zones).length} questions) → « ${f.titre} »` };
    });

    // ═══ LE VRAI CHEMIN D'UN TICKET : la demande, la fiche, l'approbation, la page, l'étape suivante, la décision ═══
    //  Barbe-Grise (hors du clan, aucun ticket) ; à chaque instant, au plus deux messages du bot dans le ticket.
    const CAND = 1002;
    let tid = 0, eidT = 0, msgEtape = "";
    const deuxAuPlus = async () => { const m = await messagesTicket(tid); return { m, ok: m.length <= 2 }; };
    await etape("Le parcours du panneau : la fiche (étape 1), puis deux étapes de questions", [D], async () => {
      const p = ((await D.api("recrutement/parcours")).panneaux || []).find((x) => x.panneau === "p1");
      if (!p) return { ok: false, detail: "le panneau p1 n'a pas de parcours" };
      const r = await posterD(D, "recrutement/parcours", { panneau: "p1", version: p.version || 0, mode: "approbation",
        fiche: [{ titre: "Pseudo Roblox", type: "court", aide: "Ton pseudo exact" }],
        gabarit: [{ titre: "Le jeu", consigne: "Quelques mots suffisent.", source: "tirage", nombre: 3 },
          { titre: "Le clan", consigne: "Relis-toi avant d'envoyer.", source: "tirage", nombre: 2 }],
        exigence: 100, delai: 20, liste_noire: true, metier: true });
      return { ok: r.status === 200, detail: r.status === 200 ? "version " + r.corps.parcours.version + " · étapes : Le jeu (3), Le clan (2)" : JSON.stringify(r.corps).slice(0, 200) };
    });

    await etape("La demande : « Es-tu sûr ? », la fiche, puis l'affiche seule dans le ticket (le vrai chemin du bot)", [D], async () => {
      const r = await demo(`recrutement/ouvrir?membre=${CAND}&pseudo=Parcours_Web`);
      tid = Number(r.ticket || 0);
      if (!tid) return { ok: false, detail: "pas de ticket : " + JSON.stringify(r).slice(0, 240) };
      releve.tid = tid;
      const m = await messagesTicket(tid);
      return { ok: m.length === 1 && /Es-tu sûr/.test(r.confirmation || ""), detail: `ticket #${tid} · ${m.length} message(s) du bot · « ${((m[0] || {}).texte || "").slice(0, 90)}… »` };
    });

    await etape("L'approbation sur le site : l'étape 2 part dans le ticket (deux messages du bot, les questions sur SA page)", [D], async () => {
      if (!await ouvrirDossier(D, tid, false)) return { ok: false, detail: "dossier du ticket #" + tid + " introuvable" };
      if (!await cliquer(D, "dialog[open] button", "Approuver la demande")) return { ok: false, detail: "« Approuver la demande » absent" };
      const d = await attendre(async () => { const x = await D.api("recrutement/dossier?ticket=" + tid); return x.etape === "etape2" && (x.envois || []).length ? x : null; }, 15000);
      if (!d) return { ok: false, detail: "le serveur n'a pas l'envoi" };
      const e = d.envois[d.envois.length - 1];
      eidT = Number(e.id);
      const m = await messagesTicket(tid);
      msgEtape = ((m[1] || {}).id) || "";
      const texte = (m[1] || {}).texte || "";
      const ok = m.length === 2 && /Étape 2 sur 3/.test(texte) && !e.questions.some((q) => texte.includes(q.question)) && e.etape_ouverte === 1 && e.etape_fiche === 1;
      return { ok, detail: `envoi ${eidT} · ${e.questions.length} questions en ${(e.etapes || []).length} étapes · ticket : ${m.length} messages · « ${texte.slice(0, 90)}… »` };
    });

    await etape("« Répondre au questionnaire » (le vrai bouton du ticket) : son lien, sa page sur son téléphone — aucun formulaire", [C], async () => {
      const l = await demo("recrutement/lien?ticket=" + tid);
      if (!l.url || l.formulaire) return { ok: false, detail: "pas de lien : " + JSON.stringify(l).slice(0, 240) };
      await C.s("Page.navigate", { url: l.url });
      const p = await attendre(async () => { const x = await pageC(C); return x.vue === "etape" && Object.keys(x.zones).length ? x : null; }, 15000);
      return { ok: !!p && /^Étape 2 sur 3/.test(p.titre) && Object.keys(p.zones).length === 3 && !p.debord,
        detail: p ? `lu pour lui seul : « ${(l.lu || "").slice(0, 70)}… » · « ${p.titre} » · ${Object.keys(p.zones).length} questions` : "la page ne s'ouvre pas" };
    });

    await etape("Le direct : la direction voit sa page ouverte et chaque frappe dans le dossier", [C, D], async () => {
      if (!await ouvrirDossier(D, tid)) return { ok: false, detail: "le bloc « En direct » n'apparaît pas dans le dossier" };
      const rangs = Object.keys(await pageC(C).then((x) => x.zones)).map(Number).sort((a, b) => a - b);
      const x = await mesurer(C, D, rangs[0], "Les Rell Bros, sur le wiki");
      mesures.delais_ticket = x;
      const etat = await etatDirect(D);
      return { ok: x.motEntierMs !== null && x.motEntierMs < 2500 && x.enTrain, detail: `mot entier ${x.motEntierMs} ms après la dernière touche · 1er caractère ${x.premierCaractereMs} ms · « ${etat} »` };
    });

    await etape("Il envoie l'étape 2 : « réponses reçues » dans le ticket (le même message, réécrit) ; la direction est prévenue", [C, D], async () => {
      await remplir(C, "Ma réponse depuis la page");
      const err = await envoyer(C, "Envoyer cette étape");
      if (err) return { ok: false, detail: err };
      const m = await attendre(async () => { const y = await messagesTicket(tid); return y.length === 2 && /reçues/i.test((y[1] || {}).texte || "") ? y : null; }, 10000);
      const t = await attendre(async () => { const y = await toasts(D); return y.some((z) => /étape du questionnaire est arrivée/.test(z)) ? y : null; }, 10000);
      const bouton = await attendre(() => D.evaluer("[...document.querySelectorAll('dialog[open] button')].some((b) => b.textContent.includes(\"Ouvrir l'étape 3\"))"), 10000);
      return { ok: !!m && m[1].id === msgEtape && !!t && !!bouton,
        detail: m ? `ticket : ${m.length} messages, « ${m[1].texte.slice(0, 80)}… » (le même) · avis : ${t ? "oui" : "non"} · « Ouvrir l'étape 3 » : ${bouton ? "oui" : "non"}` : "le message d'étape n'est pas réécrit" };
    });

    await etape("La direction ouvre l'étape 3 : l'ancien message s'efface, le nouveau le prévient (deux messages au plus)", [D], async () => {
      if (!await cliquer(D, "dialog[open] button", "Ouvrir l'étape 3")) return { ok: false, detail: "« Ouvrir l'étape 3 » absent" };
      const m = await attendre(async () => { const y = await messagesTicket(tid); return y.length === 2 && y[1].id !== msgEtape && /Étape 3 sur 3/.test(y[1].texte) ? y : null; }, 10000);
      if (m) msgEtape = m[1].id;
      return { ok: !!m, detail: m ? `ticket : ${m.length} messages · « ${m[1].texte.slice(0, 90)}… »` : JSON.stringify((await messagesTicket(tid)).map((y) => y.texte.slice(0, 60))) };
    });

    await etape("Il revient sur sa page : l'étape 3, puis l'envoi — « Merci » ; « Réponses envoyées » dans le ticket", [C, D], async () => {
      await revenir(C);
      const p = await attendre(async () => { const x = await pageC(C); return x.vue === "etape" && /^Étape 3 sur 3/.test(x.titre) ? x : null; }, 30000);
      if (!p) return { ok: false, detail: "l'étape 3 n'apparaît pas : " + JSON.stringify(await pageC(C)).slice(0, 200) };
      await remplir(C, "Ma réponse de la dernière étape");
      const err = await envoyer(C, "Envoyer cette étape");
      const f = await pageC(C);
      const v = await deuxAuPlus();
      const t = await attendre(async () => { const y = await toasts(D); return y.some((z) => /Réponses reçues/.test(z)) ? y : null; }, 15000);
      return { ok: !err && f.vue === "merci" && v.ok && v.m.some((y) => /envoyées/i.test(y.texte)) && !!t,
        detail: err || `C : « ${f.titre} » · ticket : ${v.m.length} messages · avis D : ${t ? "« Réponses reçues »" : "aucun"}` };
    });

    await etape("La décision : chaque réponse cochée « Juste », « Accepter » — le rôle du clan, le ticket fermé, deux messages au plus", [D], async () => {
      if (!await ouvrirDossier(D, tid, false)) return { ok: false, detail: "dossier introuvable" };
      const n = await toutJuste(D);
      const corrige = await attendre(async () => { const x = await D.api("recrutement/dossier?ticket=" + tid); const b = x.envois[x.envois.length - 1].bilan; return b.justes === b.total ? b : null; }, 15000);
      if (!corrige) return { ok: false, detail: n + " « Juste » cochés, le serveur n'a pas tout" };
      if (!await ouvrirDossier(D, tid, false)) return { ok: false, detail: "le dossier ne se rouvre pas" };   // relu : 100 %
      if (!await attendre(() => cliquer(D, "dialog[open] button", "Accepter · " + corrige.total + "/" + corrige.total), 8000)) return { ok: false, detail: "« Accepter » absent" };
      if (!await attendre(() => D.evaluer("document.querySelectorAll('dialog[open]').length > 1"), 6000)) return { ok: false, detail: "confirmation absente" };
      if (!await cliquer(D, "dialog[open] button", "Accepter")) return { ok: false, detail: "« Accepter » absent de la confirmation" };
      const d = await attendre(async () => { const x = await D.api("recrutement/dossier?ticket=" + tid); return x.etape === "accepte" ? x : null; }, 15000);
      const v = await deuxAuPlus();
      const mp = ((await demo("discord?mp=" + CAND)).mp || []).map((x) => x.texte).join(" | ");
      releve.actif = false;
      await releveur;
      mesures.releve_ticket = { releves: releve.n, max: releve.max, pire: releve.pire };
      return { ok: !!d && v.ok && /accepté/i.test(mp) && releve.n > 50 && releve.max <= 2,
        detail: `${n} réponses justes · ${d ? "accepté" : "pas accepté"} · ticket : ${v.m.length} messages · relevé continu : ${releve.n} relevés, ${releve.max} message(s) du bot au plus · MP : « ${mp.slice(-70)} »` };
    });

    // ═══ LE VRAI CHEMIN D'UN CHEF D'ÉQUIPE : la proposition, le message privé, la page, 100 %, le rôle, le badge ═══
    let chef = null, eidC = 0;
    await etape("Proposer d'être chef (la route du bouton) : le rôle des chefs du métier, son message privé et son bouton persistant", [D], async () => {
      const C0 = await D.api("recrutement/chefs");
      const occupes = new Set([...(C0.candidatures || []).filter((x) => /en_cours|corriger|attente/.test(x.etat)).map((x) => String(x.membre.id)),
        ...(C0.chefs || []).map((x) => String(x.membre.id))]);
      chef = (C0.membres || []).filter((m) => !m.chef && !occupes.has(String(m.id))).sort((a, b) => a.nom.localeCompare(b.nom, "fr"))[0];
      const qs = (C0.questions || []).filter((q) => (q.metiers || []).includes("navigation") && q.actif !== false && !q.retiree).slice(0, 4);
      if (!chef || qs.length < 4) return { ok: false, detail: "membre ou questions de chef manquants : " + JSON.stringify({ chef, qs: qs.length }) };
      const role = await posterD(D, "recrutement/chefs/role", { metier: "navigation", creer: true });
      const r = await posterD(D, "recrutement/chefs/proposer", { membre: String(chef.id), metier: "navigation", etapes: [
        { titre: "Le cap", consigne: "Chaque réponse doit être juste.", questions: qs.slice(0, 2).map((q) => q.id) },
        { titre: "L'équipage", consigne: "Pense à ceux que tu guideras.", questions: qs.slice(2).map((q) => q.id) }] });
      if (r.status !== 200) return { ok: false, detail: "proposition refusée : " + JSON.stringify(r.corps).slice(0, 200) };
      eidC = Number(r.corps.envoi);
      const mp = ((await demo("mp?membre=" + chef.id)).messages || []).pop() || {};
      return { ok: role.status === 200 && r.corps.invite === true && (mp.custom_ids || []).includes("cq:rep:" + eidC) && /Chef d'équipe · Navigation/.test(mp.texte || ""),
        detail: `${chef.nom} · rôle des chefs : ${role.status} · envoi ${eidC} · MP : « ${(mp.texte || "").slice(0, 80)}… » · bouton ${JSON.stringify(mp.custom_ids)}` };
    });

    let attendues = {};
    await etape("Le bouton de son message privé : sa page de chef (le titre, la règle), la direction le voit écrire", [C, D], async () => {
      const l = await demo(`mp/cliquer?membre=${chef.id}&custom_id=cq:rep:${eidC}`);
      if (!l.url) return { ok: false, detail: "pas de lien : " + JSON.stringify(l).slice(0, 200) };
      await C.s("Page.navigate", { url: l.url });
      const p = await attendre(async () => { const x = await pageC(C); return x.vue === "etape" && Object.keys(x.zones).length ? x : null; }, 15000);
      if (!p) return { ok: false, detail: "la page du chef ne s'ouvre pas" };
      const entete = await C.evaluer("document.querySelector('#nom-page').textContent + ' | ' + document.querySelector('.titre-rubrique h1').textContent");
      const dossier = await D.api("recrutement/chefs/dossier?envoi=" + eidC);
      attendues = Object.fromEntries(((dossier.questionnaire || {}).questions || []).map((q) => [String(q.rang), q.attendue || ""]));
      if (!await ouvrirCandidatureChef(D, eidC)) return { ok: false, detail: "le direct n'apparaît pas dans sa candidature" };
      const rangs = Object.keys(p.zones).map(Number).sort((a, b) => a - b);
      const x = await mesurer(C, D, rangs[0], attendues[String(rangs[0])]);
      mesures.delais_chef = x;
      return { ok: /Questionnaire de chef d'équipe · Navigation/.test(entete) && /^Étape 1 sur 2/.test(p.titre) && x.motEntierMs !== null && x.motEntierMs < 2500,
        detail: `« ${entete} » · « ${p.titre} » · direct : mot entier ${x.motEntierMs} ms après la dernière touche` };
    });

    await etape("Ses réponses justes : l'étape 1 envoyée ; la direction ouvre l'étape 2 — un nouveau message privé, sa page la montre", [C, D], async () => {
      await C.evaluer(`(async () => { const a = ${JSON.stringify(attendues)}; for (const z of document.querySelectorAll('textarea.cand-reponse')) { const r = z.id.slice(2);
        if (!z.value.trim() || z.value !== a[r]) { z.focus(); z.value = a[r]; z.dispatchEvent(new Event('input', { bubbles: true })); } } await new Promise((r) => setTimeout(r, 1800)); return 1; })()`);
      const err = await envoyer(C, "Envoyer cette étape");
      if (err) return { ok: false, detail: err };
      const avant = ((await demo("mp?membre=" + chef.id)).messages || []).length;
      const bouton = await attendre(() => cliquer(D, "dialog[open] button", "Ouvrir l'étape suivante"), 15000);
      if (!bouton) return { ok: false, detail: "« Ouvrir l'étape suivante » absent" };
      const mp = await attendre(async () => { const x = (await demo("mp?membre=" + chef.id)).messages || []; return x.length > avant ? x[x.length - 1] : null; }, 10000);
      await revenir(C);
      const p = await attendre(async () => { const x = await pageC(C); return x.vue === "etape" && /^Étape 2 sur 2/.test(x.titre) ? x : null; }, 30000);
      return { ok: !!mp && /L'étape 2 de ton questionnaire est ouverte/.test(mp.texte) && !!p,
        detail: `MP : « ${((mp || {}).texte || "").slice(0, 90)}… » · page : « ${(p || {}).titre || ""} »` };
    });

    await etape("Sa dernière étape envoyée : « Merci » ; la direction coche 100 %, « Nommer chef » — son rôle, son badge dans l'éditeur des équipes", [C, D], async () => {
      await C.evaluer(`(async () => { const a = ${JSON.stringify(attendues)}; for (const z of document.querySelectorAll('textarea.cand-reponse')) { const r = z.id.slice(2);
        z.focus(); z.value = a[r]; z.dispatchEvent(new Event('input', { bubbles: true })); } await new Promise((r) => setTimeout(r, 1800)); return 1; })()`);
      const err = await envoyer(C, "Envoyer cette étape");
      const f = await pageC(C);
      if (err || f.vue !== "merci") return { ok: false, detail: err || "pas de « Merci » : " + f.titre };
      if (!await ouvrirCandidatureChef(D, eidC, false)) return { ok: false, detail: "sa candidature ne s'ouvre pas" };
      const marquer = await attendre(() => cliquer(D, "dialog[open] button", "Marquer justes les"), 8000);
      const n = marquer ? 0 : await toutJuste(D);
      const b = await attendre(async () => { const x = await D.api("recrutement/chefs/dossier?envoi=" + eidC); const y = (x.questionnaire || {}).bilan || {}; return y.total && y.justes === y.total ? y : null; }, 15000);
      if (!b) return { ok: false, detail: "corrections incomplètes" };
      //  Les corrections partent par la file du site : la candidature relue, « Nommer chef » (100 %) s'ouvre.
      if (!await ouvrirCandidatureChef(D, eidC, false)) return { ok: false, detail: "sa candidature ne se rouvre pas" };
      if (!await attendre(() => cliquer(D, "dialog[open] button", "Nommer chef"), 8000)) return { ok: false, detail: "« Nommer chef » absent (" + b.justes + "/" + b.total + ")" };
      if (!await attendre(() => D.evaluer("document.querySelectorAll('dialog[open]').length > 1"), 6000)) return { ok: false, detail: "confirmation absente" };
      if (!await cliquer(D, "dialog[open] button", "Nommer chef")) return { ok: false, detail: "« Nommer chef » absent de la confirmation" };
      const nomme = await attendre(async () => ((await D.api("recrutement/chefs")).chefs || []).find((x) => String(x.membre.id) === String(chef.id)), 15000);
      const badge = ((await D.api("equipage/equipes")).badges || {})[String(chef.id)] || "";
      if (!nomme || !badge.startsWith("Chef validé · ")) return { ok: false, detail: "pas nommé ou pas de badge : « " + badge + " »" };
      //  27/10/2026 (la navigation regroupée) : l'ancien « Par équipe » est la vue « Équipes » d'Équipage (…/equipes).
      await allerD(D, "#equipage/membres/equipes");
      await D.s("Page.reload", {});
      await attendre(() => D.evaluer("!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 12000);
      await pause(600);
      if (!await attendre(() => cliquer(D, "#contenu button", "Nouvelle équipe"), 8000)) return { ok: false, detail: "« Nouvelle équipe » absent de la vue « Équipes »" };
      const premier = await attendre(() => D.evaluer(`(() => { const d = [...document.querySelectorAll("dialog[open]")].pop();
        const li = d && d.querySelector('ol.choix-equipe[role="radiogroup"] > li'); if (!li) return null;
        const r = li.querySelector('input[type="radio"]'); return { id: r ? r.value : "", texte: li.innerText.replace(/\\s+/g, " ").trim() }; })()`), 8000);
      return { ok: !!premier && premier.id === String(chef.id) && premier.texte.includes(badge),
        detail: `${marquer ? "« Marquer justes »" : n + " « Juste »"} · ${b.justes}/${b.total} · « ${badge} » · en tête du choix du chef : « ${(premier || {}).texte || "rien"} »` };
    });
  } finally {
    releve.actif = false;
    await releveur;
    await C.fermer(); await D.fermer();
  }
  const echecs = resultats.filter((r) => !r.ok);
  writeFileSync(join(SORTIE, "parcours_candidature.json"), JSON.stringify({ quand: new Date().toISOString(), base: BASE, resultats, mesures }, null, 1));
  console.log(`\nDélais (frappe du candidat → texte chez la direction) : ${JSON.stringify(mesures.delais)}\nDébit : ${JSON.stringify(mesures.debit || {})}`);
  console.log(`\n${resultats.length} étape(s), ${echecs.length} en échec.`);
  if (echecs.length) process.exitCode = 1;
}
principal().catch((e) => { console.error("Parcours interrompu : " + e.message); process.exitCode = 2; });
