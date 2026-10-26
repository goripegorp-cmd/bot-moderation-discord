// outils/parcours_direct.mjs — la présence en direct et les verrous d'édition, joués À DEUX dans deux navigateurs sans
// fenêtre (profils séparés : deux cookies, deux personnes) contre le VRAI serveur local.
//
//   A = le fondateur (/tableau/demo), B = la direction (/tableau/demo?qui=direction).
//   A ouvre une affiche en modification → B voit l'avatar de A (« À bord »), le cadenas sur la carte, et l'éditeur en
//   lecture seule ; B « demande la main » → A reçoit l'avis ; B tente d'écrire par l'API → 423 ; A enregistre et ferme →
//   B voit la libération, l'édition s'ouvre sur la version RELUE, B enregistre (rien de perdu) ; puis tout est libre.
//   Enfin une ZONE de la page (les liens du questionnaire) : prise par A à sa première saisie, fermée chez B, rendue
//   dès que A change de page — et dès qu'il ferme la page (sans attendre la grâce du serveur).
//   Chaque étape relit l'état (la page ET l'API) ; une capture par navigateur et par étape. Le réseau du navigateur
//   (protocole DevTools) dit si la WebSocket passe (101, la CSP « connect-src 'self' », le service worker) et mesure
//   la charge : messages par minute au repos, avec un verrou tenu, et leur taille.
//
//   node outils/parcours_direct.mjs [--url http://localhost:8796] [--sortie <dossier>] [--mesure 60] [--navigateur <exe>]
//
// La base du site local change à chaque parcours : relancer le site local avant de rejouer.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const BASE = String(opt("url", "http://localhost:8796")).replace(/\/+$/, "");
const SITE = BASE + "/tableau/espace/";
const SORTIE = opt("sortie", join(tmpdir(), "capitainerie-direct"));
const MESURE = Number(opt("mesure", 60)) || 0;   // secondes de mesure au repos (0 : pas de mesure)
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);
const pause = (ms) => new Promise((ok) => setTimeout(ok, ms));

// ─── Un navigateur sans fenêtre, son profil, son protocole DevTools ─────────
class Navigateur {
  constructor(nom) { this.nom = nom; this.attente = new Map(); this.prochain = 1; this.ecouteurs = []; this.erreurs = []; this.trames = []; this.sockets = []; }
  async lancer(port) {
    const exe = NAVIGATEURS.find((p) => existsSync(p));
    if (!exe) throw new Error("Aucun Edge ni Chrome trouvé (option --navigateur <exe>).");
    this.exe = exe;
    this.profil = mkdtempSync(join(tmpdir(), "capitainerie-direct-" + this.nom + "-"));
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
  async onglet() {
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
      if (d.method === "Network.webSocketCreated") this.sockets.push({ url: p.url, id: p.requestId });
      if (d.method === "Network.webSocketHandshakeResponseReceived") { const s = this.sockets.find((x) => x.id === p.requestId); if (s) s.statut = p.response.status; }
      if (d.method === "Network.webSocketFrameSent" || d.method === "Network.webSocketFrameReceived") {
        const r = p.response || {};
        if (r.opcode === 1) this.trames.push({ t: Date.now(), sens: d.method.endsWith("Sent") ? "envoi" : "recu", taille: Buffer.byteLength(r.payloadData || ""), texte: r.payloadData || "" });
      }
    });
    await this.s("Emulation.setDeviceMetricsOverride", { width: 1366, height: 900, deviceScaleFactor: 1, mobile: false });
  }
  async evaluer(expression) {
    const r = await this.s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(this.nom + " : " + ((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text));
    return r.result.value;
  }
  async capture(fichier) {
    try { const c = await this.s("Page.captureScreenshot", { format: "png" }); writeFileSync(fichier, Buffer.from(c.data, "base64")); } catch (e) { /* capture impossible */ }
  }
  async aller(ancre) {
    await this.s("Page.navigate", { url: SITE + ancre });
    return attendre(() => this.evaluer("!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 15000, 200);
  }
  api(chemin) { return this.evaluer(`fetch(${JSON.stringify(SITE + "api/" + chemin)}, { credentials: "same-origin", headers: { "X-Tableau": "1" } }).then((r) => r.json())`); }
  async fermer() {
    try { await this.envoyer("Browser.close"); } catch (e) { /* déjà fermé */ }
    await pause(400);
    try { this.proc.kill(); } catch (e) { /* rien */ }
    try { rmSync(this.profil, { recursive: true, force: true }); } catch (e) { /* le profil temporaire reste */ }
  }
}
async function attendre(fn, ms = 15000, pas = 300) {
  const t0 = Date.now();
  let v = null;
  while (Date.now() - t0 < ms) {
    try { v = await fn(); } catch (e) { v = null; }
    if (v) return v;
    await pause(pas);
  }
  return v;
}

// ─── Les gestes (dans la pancarte ouverte, sinon la page) ───────────────────
const ZONE = "([...document.querySelectorAll('dialog[open]')].pop() || document)";
// Les liens du questionnaire sont rangés dans un groupe replié (rangement.js, 26/10) : on le déplie, puis on attend
// le bouton « Enregistrer les liens ».
const PRET_LIENS = "(() => { for (const d of document.querySelectorAll('#contenu details.groupe')) if (d.querySelector('summary').textContent.includes('Les liens')) d.open = true;"
  + " return [...document.querySelectorAll('#contenu button')].some((b) => /Enregistrer les liens/.test(b.textContent)); })()";
const VISIBLE = "(x) => x.getClientRects().length && getComputedStyle(x).visibility !== 'hidden' && !x.closest('[inert]')";
const cliquer = (n, selecteur, texte) => n.evaluer(`(() => { const z = ${ZONE}; const vis = ${VISIBLE};
  const el = [...z.querySelectorAll(${JSON.stringify(selecteur)})].find((x) => vis(x) && !x.disabled && (x.textContent || x.getAttribute("aria-label") || "").replace(/\\s+/g, " ").includes(${JSON.stringify(texte)}));
  if (!el) return false; el.scrollIntoView({ block: "center" }); el.click(); return true; })()`);
/** Ouvre l'affiche (les groupes par métier dépliés) puis « Modifier ». */
async function ouvrirEditeur(n, nomCarte) {
  await n.evaluer("(() => { for (const g of document.querySelectorAll('details.groupe')) g.open = true; return true; })()");
  await pause(500);
  const ok = await n.evaluer(`(() => { const b = [...document.querySelectorAll("button.affiche")].find((x) => x.textContent.toUpperCase().includes(${JSON.stringify(nomCarte.toUpperCase())}));
    if (!b) return false; b.click(); return true; })()`);
  if (!ok) return false;
  if (!await attendre(() => cliquer(n, "dialog[open] button", "Modifier"), 8000)) return false;
  return attendre(() => n.evaluer("!!document.querySelector('dialog[open] .editeur-affiche')"), 8000);
}
const etatEditeur = (n) => n.evaluer(`(() => { const d = [...document.querySelectorAll("dialog[open]")].pop(); if (!d) return null;
  const vis = ${VISIBLE};
  const consigne = d.querySelector(".direct-consigne");
  return { lecture: d.classList.contains("direct-lecture"), consigne: consigne ? consigne.innerText.replace(/\\s+/g, " ") : "",
    avis: (d.querySelector(".direct-avis") || {}).innerText || "", cadre: (d.querySelector(".direct-cadre") || {}).innerText || "",
    figes: [...d.querySelectorAll(".pancarte-corps > *")].filter((x) => x.inert).length,
    boutons: [...d.querySelectorAll(".pancarte-pied button")].filter(vis).map((b) => b.textContent.trim()),
    surnom: ((d.querySelector('input[placeholder="l\\'Ombre des Mers"]') || {}).value) ?? null,
    prime: ((d.querySelector('input[type=number][step="1000"]') || {}).value) ?? null }; })()`);
const saisir = (n, selecteur, valeur) => n.evaluer(`(() => { const d = [...document.querySelectorAll("dialog[open]")].pop(); const i = d && d.querySelector(${JSON.stringify(selecteur)});
  if (!i) return false; i.focus(); i.value = ${JSON.stringify(String(valeur))}; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
const bord = (n) => n.evaluer(`(() => { const b = document.querySelector(".direct-bord"); return b ? { label: b.getAttribute("aria-label") || "", avatars: b.querySelectorAll(".direct-avatar").length, coupe: b.classList.contains("coupe") } : null; })()`);
/** La carte d'un objet bien en vue (les captures la montrent). */
const voirCarte = (n, objet) => n.evaluer(`(() => { for (const g of document.querySelectorAll("details.groupe")) g.open = true;
  const b = [...document.querySelectorAll('[data-direct-objet="${objet}"]')].find((x) => !x.closest("dialog"));
  if (b && b.parentElement) b.parentElement.scrollIntoView({ block: "center" }); return !!b; })()`);
const badge = (n, objet) => n.evaluer(`(() => { const b = [...document.querySelectorAll('[data-direct-objet="${objet}"]')].find((x) => !x.closest("dialog")); if (!b) return null;
  return { visible: !b.hidden, texte: b.textContent.trim(), titre: b.title, pris: b.parentElement.classList.contains("direct-sous-verrou") }; })()`);

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
    detail = r && r !== true ? ("detail" in r ? String(r.detail || "") : JSON.stringify(r).slice(0, 400)) : "";
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
function charge(n, t0, t1) {
  const l = n.trames.filter((x) => x.t >= t0 && x.t < t1);
  const min = (t1 - t0) / 60000;
  const par = (sens) => l.filter((x) => x.sens === sens);
  const r = { secondes: Math.round((t1 - t0) / 1000), envoyes: par("envoi").length, recus: par("recu").length,
    parMinute: Math.round((l.length / min) * 10) / 10, octets: l.reduce((s, x) => s + x.taille, 0), genres: [...new Set(l.map((x) => { try { return JSON.parse(x.texte).t; } catch (e) { return "?"; } }))] };
  if (l.length) r.exemples = l.slice(0, 3).map((x) => x.sens + " +" + Math.round((x.t - t0) / 1000) + " s " + x.texte.slice(0, 160));   // pour comprendre un écart
  return r;
}

// ═══ LE PARCOURS ════════════════════════════════════════════════════════════
async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  const A = new Navigateur("A-fondateur"), B = new Navigateur("B-direction");
  const port = 9640 + Math.floor(Math.random() * 300);
  await Promise.all([A.lancer(port), B.lancer(port + 1)]);
  console.log("Navigateurs : " + A.exe + " (deux profils séparés)\nCaptures : " + SORTIE);
  const mesures = {};
  try {
    await A.onglet(); await B.onglet();
    await A.s("Page.navigate", { url: BASE + "/tableau/demo" });
    await B.s("Page.navigate", { url: BASE + "/tableau/demo?qui=direction" });
    await pause(2500);
    const affs = await attendre(() => A.api("rell/affiches").then((x) => (x.affiches || []).length ? x : null), 15000);
    const cible = (affs.affiches || []).find((a) => a.id === "demo-kolax-01") || affs.affiches[0];
    const OBJET = "affiche:" + cible.id;
    const nomCarte = (cible.roblox && cible.roblox.nom) || cible.membre.nom;
    const SURNOM_A = "Le Requin des parcours", PRIME_B = 4242000;

    await etape("Les deux à bord : la WebSocket passe (101), la CSP et le service worker la laissent", [A, B], async () => {
      await Promise.all([A.aller("#capitainerie/affiches"), B.aller("#capitainerie/affiches")]);
      // Le service worker contrôle la page après un rechargement : la socket passe toujours.
      await attendre(() => A.evaluer("navigator.serviceWorker && navigator.serviceWorker.ready.then(() => true)"), 10000);
      await A.s("Page.reload"); await B.s("Page.reload");
      await attendre(() => A.evaluer("!!(navigator.serviceWorker && navigator.serviceWorker.controller) && !!document.querySelector('#contenu .titre-rubrique')"), 15000);
      await attendre(() => B.evaluer("!!document.querySelector('#contenu .titre-rubrique')"), 15000);
      const deux = await attendre(async () => { const [x, y] = [await bord(A), await bord(B)]; return x && y && x.avatars === 2 && y.avatars === 2 ? [x, y] : null; }, 15000);
      const sw = await A.evaluer("!!(navigator.serviceWorker && navigator.serviceWorker.controller)");
      const csp = [...(await A.evaluer("(window.__capitainerie || {}).violations || []")), ...(await B.evaluer("(window.__capitainerie || {}).violations || []"))];
      const sockets = [...A.sockets, ...B.sockets].filter((s) => s.url.includes("/tableau/espace/direct"));
      const ok = !!deux && sw && !csp.length && sockets.length >= 2 && sockets.every((s) => s.statut === 101)
        && /Capitaine Direction/.test(deux[0].label) && /GoRipe/.test(deux[1].label);
      return { ok, detail: deux ? `A : « ${deux[0].label} » · B : « ${deux[1].label} » · sockets ${sockets.map((s) => s.statut).join("/")} · service worker ${sw ? "actif" : "absent"} · CSP ${csp.length} violation(s)` : "les avatars n'apparaissent pas" };
    });

    if (MESURE) {
      await etape(`La charge au repos (${MESURE} s, rien d'ouvert)`, [A, B], async () => {
        const t0 = Date.now();
        await pause(MESURE * 1000);
        mesures.repos = { A: charge(A, t0, Date.now()), B: charge(B, t0, Date.now()) };
        const ok = mesures.repos.A.parMinute === 0 && mesures.repos.B.parMinute === 0;
        return { ok, detail: "A : " + JSON.stringify(mesures.repos.A) + " · B : " + JSON.stringify(mesures.repos.B) };
      });
    }

    await etape("A ouvre une affiche en modification (la main est à lui)", [A, B], async () => {
      if (!await ouvrirEditeur(A, nomCarte)) return { ok: false, detail: "éditeur de A introuvable" };
      const e = await attendre(async () => { const x = await etatEditeur(A); return x && !x.lecture && x.boutons.includes("Enregistrer l'affiche") ? x : null; }, 6000);
      return { ok: !!e && !e.consigne, detail: JSON.stringify(e) };
    });

    await etape("B voit l'avatar de A, ce qu'il modifie, et le cadenas sur la carte", [A, B], async () => {
      const bd = await attendre(async () => { const x = await badge(B, OBJET); return x && x.visible && x.pris ? x : null; }, 8000);
      await voirCarte(B, OBJET);
      await pause(300);
      const ouvert = await B.evaluer("(() => { document.querySelector('.direct-bord').click(); return true; })()");
      await pause(600);
      const liste = await B.evaluer("(document.querySelector('.direct-liste') || {}).innerText || ''");
      const ok = !!bd && /En cours de modification\s*par GoRipe/.test(bd.texte) && ouvert && /GoRipe/.test(liste) && /modifie l'affiche de/.test(liste) && /Capitainerie › Affiches/.test(liste);
      return { ok, detail: (bd ? "badge « " + bd.texte + " » (" + bd.titre + ")" : "pas de badge") + " · liste : " + liste.replace(/\s+/g, " ").slice(0, 220) };
    });

    await etape("B ouvre la même affiche : l'éditeur s'ouvre en lecture seule", [A, B], async () => {
      await B.evaluer("(() => { document.querySelector('.direct-bord').click(); return true; })()");   // referme la liste
      await pause(300);
      if (!await ouvrirEditeur(B, nomCarte)) return { ok: false, detail: "éditeur de B introuvable" };
      const e = await attendre(async () => { const x = await etatEditeur(B); return x && x.lecture && x.consigne ? x : null; }, 6000);
      const ok = !!e && /GoRipe modifie l'affiche de/.test(e.consigne) && e.figes > 0 && !e.boutons.includes("Enregistrer l'affiche") && e.boutons.includes("Fermer");
      return { ok, detail: JSON.stringify(e) };
    });

    await etape("B demande la main : A reçoit l'avis", [A, B], async () => {
      if (!await cliquer(B, "dialog[open] button", "Demander la main")) return { ok: false, detail: "bouton « Demander la main » absent" };
      const avis = await attendre(async () => { const x = await etatEditeur(A); return x && x.avis ? x.avis : null; }, 6000);
      const envoyee = await attendre(async () => { const x = await etatEditeur(B); return x && /Demande envoyée/.test(x.consigne) ? x : null; }, 4000);
      return { ok: !!avis && /Capitaine Direction voudrait modifier/.test(avis) && !!envoyee, detail: "A : « " + String(avis || "").replace(/\s+/g, " ") + " »" };
    });

    await etape("B tente d'écrire par l'API pendant que A tient le verrou → 423", [A, B], async () => {
      const r = await B.evaluer(`(async () => { const a = (await fetch(${JSON.stringify(SITE + "api/rell/affiche?id=" + encodeURIComponent(cible.id))}, { headers: { "X-Tableau": "1" } }).then((r) => r.json())).affiche;
        const corps = { id: a.id, version: a.version, membre_id: a.membre.id, roblox: { nom: a.roblox.nom, id: a.roblox.id }, surnom: "Écrit en douce", prime: a.prime, niveau: a.niveau,
          grade: a.grade, statut: a.statut, attributs: a.attributs, notes: a.notes };
        const r = await fetch(${JSON.stringify(SITE + "api/rell/affiche")}, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Tableau": "1" }, body: JSON.stringify(corps) });
        return { status: r.status, corps: await r.json() }; })()`);
      const apres = await A.api("rell/affiche?id=" + encodeURIComponent(cible.id));
      return { ok: r.status === 423 && /En cours de modification par GoRipe/.test(r.corps.erreur || "") && apres.surnom !== "Écrit en douce", detail: JSON.stringify(r) };
    }, { attendus: /status of 423/ });   // le navigateur note la réponse 423 de cet essai : c'est elle qu'on attend

    await etape("A enregistre et ferme : B voit la libération, l'édition s'ouvre sur la version relue", [A, B], async () => {
      if (!await cliquer(A, "dialog[open] button", "Garder la main")) return { ok: false, detail: "« Garder la main » absent chez A" };
      if (!await saisir(A, "input[placeholder=\"l'Ombre des Mers\"]", SURNOM_A)) return { ok: false, detail: "champ du surnom introuvable chez A" };
      await pause(300);
      if (!await cliquer(A, "dialog[open] button", "Enregistrer l'affiche")) return { ok: false, detail: "« Enregistrer l'affiche » absent chez A" };
      const serveur = await attendre(async () => { const x = await A.api("rell/affiche?id=" + encodeURIComponent(cible.id)); return x.surnom === SURNOM_A ? x : null; }, 10000);
      if (!serveur) return { ok: false, detail: "le serveur n'a pas le surnom de A" };
      const e = await attendre(async () => { const x = await etatEditeur(B); return x && !x.lecture && !x.consigne && x.surnom === SURNOM_A && x.boutons.includes("Enregistrer l'affiche") ? x : null; }, 15000);
      return { ok: !!e, detail: e ? "B a la main, surnom relu « " + e.surnom + " » (version " + serveur.version + ")" : "B : " + JSON.stringify(await etatEditeur(B)) };
    });

    await etape("A voit B à son tour : le cadenas passe chez lui", [A, B], async () => {
      const bd = await attendre(async () => { const x = await badge(A, OBJET); return x && x.visible && /par Capitaine Direction/.test(x.texte) ? x : null; }, 8000);
      await voirCarte(A, OBJET);
      await pause(400);
      return { ok: !!bd, detail: bd ? "badge chez A : « " + bd.texte + " »" : "pas de badge chez A : " + JSON.stringify(await badge(A, OBJET)) };
    });

    if (MESURE) {
      await etape(`La charge avec un verrou tenu (${Math.max(30, Math.round(MESURE / 2))} s)`, [A, B], async () => {
        const t0 = Date.now();
        await pause(Math.max(30, Math.round(MESURE / 2)) * 1000);
        mesures.verrou = { tient: charge(B, t0, Date.now()), voit: charge(A, t0, Date.now()) };
        const ok = mesures.verrou.tient.envoyes <= Math.ceil(mesures.verrou.tient.secondes / 20) + 1 && mesures.verrou.voit.recus === 0;
        return { ok, detail: "B (tient) : " + JSON.stringify(mesures.verrou.tient) + " · A : " + JSON.stringify(mesures.verrou.voit) };
      });
    }

    await etape("B enregistre sur la version relue : rien de perdu", [A, B], async () => {
      if (!await saisir(B, "input[type=number][step=\"1000\"]", PRIME_B)) return { ok: false, detail: "champ de la prime introuvable chez B" };
      await pause(300);
      if (!await cliquer(B, "dialog[open] button", "Enregistrer l'affiche")) return { ok: false, detail: "« Enregistrer l'affiche » absent chez B" };
      const x = await attendre(async () => { const y = await B.api("rell/affiche?id=" + encodeURIComponent(cible.id)); return y.prime === PRIME_B ? y : null; }, 10000);
      const conflits = await B.evaluer("document.querySelector('#plaque-etat').textContent");
      return { ok: !!x && x.surnom === SURNOM_A && !/conflit/i.test(conflits), detail: x ? `surnom « ${x.surnom} » (A) + prime ${x.prime} (B), version ${x.version} · plaque « ${conflits} »` : "prime de B non reçue" };
    });

    await etape("Tout est libre : plus de cadenas, plus personne ne modifie", [A, B], async () => {
      const libre = await attendre(async () => { const [x, y] = [await badge(A, OBJET), await badge(B, OBJET)]; return x && y && !x.visible && !y.visible && !x.pris && !y.pris ? [x, y] : null; }, 10000);
      await A.evaluer("(() => { document.querySelector('.direct-bord').click(); return true; })()");
      await pause(500);
      const liste = await A.evaluer("(document.querySelector('.direct-liste') || {}).innerText || ''");
      return { ok: !!libre && !/modifie/.test(liste), detail: "liste chez A : " + liste.replace(/\s+/g, " ").slice(0, 200) };
    });

    await etape("Une zone de la page : A touche aux liens du questionnaire, B la voit fermée ; A change de page → libre aussitôt", [A, B], async () => {
      await A.evaluer("(() => { if (document.querySelector('.direct-liste')) document.querySelector('.direct-bord').click(); return true; })()");
      const PRET = PRET_LIENS;
      await Promise.all([A.s("Page.navigate", { url: SITE + "#equipage/candidatures/questionnaire" }), B.s("Page.navigate", { url: SITE + "#equipage/candidatures/questionnaire" })]);
      if (!await attendre(() => A.evaluer(PRET), 15000) || !await attendre(() => B.evaluer(PRET), 15000)) return { ok: false, detail: "le questionnaire ne s'affiche pas" };
      // A tape dans un titre de lien (sans enregistrer) : la main est prise à la première saisie.
      const tape = await A.evaluer(`(() => { const i = document.querySelector('input[aria-label="Titre du lien"]');
        if (i) { i.scrollIntoView({ block: "center" }); i.focus(); i.value += " (essai)"; i.dispatchEvent(new Event("input", { bubbles: true })); return "saisie"; }
        const b = [...document.querySelectorAll("button")].find((x) => /Ajouter un lien/.test(x.textContent)); if (!b) return ""; b.scrollIntoView({ block: "center" }); b.click(); return "ajout"; })()`);
      if (!tape) return { ok: false, detail: "rien à modifier dans les liens chez A" };
      const ferme = await attendre(() => B.evaluer(`(() => { const c = document.querySelector(".direct-zone-lecture .direct-consigne"); if (!c) return null;
        c.scrollIntoView({ block: "start" }); window.scrollBy(0, -140); return c.innerText.replace(/\\s+/g, " "); })()`), 8000);
      if (!ferme || !/GoRipe modifie les liens du questionnaire/.test(ferme)) return { ok: false, detail: "B ne voit pas la zone fermée : " + ferme };
      await pause(300);
      await B.capture(join(SORTIE, String(numero).padStart(2, "0") + "-B-direction-zone-fermee.png"));
      const t0 = Date.now();
      await A.s("Page.navigate", { url: SITE + "#port/journal" });   // la page change (même document) : la zone quitte l'écran
      const libre = await attendre(() => B.evaluer("!document.querySelector('.direct-consigne') && !document.querySelector('.direct-zone-lecture')"), 15000, 100);
      const delai = Date.now() - t0;
      return { ok: !!libre && delai < 5000, detail: `A (${tape}) → B : « ${ferme.slice(0, 120)} » · libre ${delai} ms après le changement de page de A` };
    });

    await etape("A ferme la page en pleine modification : la main est rendue aussitôt (pas au bout de la grâce de 10 s)", [A, B], async () => {
      const PRET = PRET_LIENS;
      await A.s("Page.navigate", { url: SITE + "#equipage/candidatures/questionnaire" });
      if (!await attendre(() => A.evaluer(PRET), 15000)) return { ok: false, detail: "le questionnaire ne s'affiche pas chez A" };
      await A.evaluer(`(() => { const b = [...document.querySelectorAll("#contenu button")].find((x) => /Ajouter un lien/.test(x.textContent)); if (b) b.click(); return !!b; })()`);
      const ferme = await attendre(() => B.evaluer("!!document.querySelector('.direct-zone-lecture .direct-consigne')"), 8000);
      if (!ferme) return { ok: false, detail: "B ne voit pas la zone prise par A" };
      const t0 = Date.now();
      await A.s("Page.navigate", { url: "about:blank" });   // l'onglet quitte le site : « pagehide »
      const libre = await attendre(() => B.evaluer("!document.querySelector('.direct-consigne') && !document.querySelector('.direct-zone-lecture')"), 20000, 100);
      const delai = Date.now() - t0;
      return { ok: !!libre && delai < 5000, detail: `libre chez B ${delai} ms après la fermeture de la page de A` };
    });

    const tailles = [...A.trames, ...B.trames];
    mesures.tailles = { messages: tailles.length, plusGros: Math.max(0, ...tailles.map((x) => x.taille)), moyen: Math.round(tailles.reduce((s, x) => s + x.taille, 0) / Math.max(1, tailles.length)),
      parGenre: Object.fromEntries([...new Set(tailles.map((x) => { try { return JSON.parse(x.texte).t; } catch (e) { return "?"; } }))].map((g) => [g, Math.max(...tailles.filter((x) => { try { return JSON.parse(x.texte).t === g; } catch (e) { return false; } }).map((x) => x.taille))])) };
    console.log("\nTailles des messages : " + JSON.stringify(mesures.tailles));
  } finally {
    await A.fermer(); await B.fermer();
  }
  const echecs = resultats.filter((r) => !r.ok);
  writeFileSync(join(SORTIE, "parcours_direct.json"), JSON.stringify({ quand: new Date().toISOString(), base: BASE, resultats, mesures }, null, 1));
  console.log(`\n${resultats.length} étape(s), ${echecs.length} en échec.`);
  if (echecs.length) process.exitCode = 1;
}
principal().catch((e) => { console.error("Parcours interrompu : " + e.message); process.exitCode = 2; });
