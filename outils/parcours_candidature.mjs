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
const cliquer = (n, selecteur, texte) => n.evaluer(`(() => { const vis = ${VISIBLE};
  const el = [...document.querySelectorAll(${JSON.stringify(selecteur)})].find((x) => vis(x) && !x.disabled && (x.textContent || x.getAttribute("aria-label") || "").replace(/\\s+/g, " ").includes(${JSON.stringify(texte)}));
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

/** Le dossier du ticket (la direction) : la liste, la ligne du ticket, puis le bloc « En direct ». */
async function ouvrirDossier(D, ticket) {
  await D.s("Page.navigate", { url: SITE + "#equipage/candidatures" });
  if (!await attendre(() => D.evaluer("!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 15000)) return false;
  await D.evaluer("(() => { for (const g of document.querySelectorAll('#contenu details.groupe')) g.open = true; return true; })()");
  await pause(500);
  const ok = await D.evaluer(`(() => { const l = [...document.querySelectorAll('.lc-clic, .feuillet.lien')].find((x) => x.textContent.includes('Ticket #${ticket} '));
    if (!l) return false; l.click(); return true; })()`);
  if (!ok) return false;
  return attendre(() => D.evaluer("(() => { const d = document.querySelector('dialog[open] .en-direct'); if (!d || !d.querySelector('.en-direct-etape')) return false; d.scrollIntoView({ block: 'start' }); return true; })()"), 15000);
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
  } finally {
    await C.fermer(); await D.fermer();
  }
  const echecs = resultats.filter((r) => !r.ok);
  writeFileSync(join(SORTIE, "parcours_candidature.json"), JSON.stringify({ quand: new Date().toISOString(), base: BASE, resultats, mesures }, null, 1));
  console.log(`\nDélais (frappe du candidat → texte chez la direction) : ${JSON.stringify(mesures.delais)}\nDébit : ${JSON.stringify(mesures.debit || {})}`);
  console.log(`\n${resultats.length} étape(s), ${echecs.length} en échec.`);
  if (echecs.length) process.exitCode = 1;
}
principal().catch((e) => { console.error("Parcours interrompu : " + e.message); process.exitCode = 2; });
