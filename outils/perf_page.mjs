// outils/perf_page.mjs — la page elle-même, dans un navigateur sans fenêtre : combien de temps avant qu'une rubrique
// soit affichée, ce qu'elle a téléchargé, la mémoire et les nœuds qu'elle tient (26/10/2026, banc de plusieurs années).
//
// Pilote un Chrome ou un Edge SANS FENÊTRE par le protocole DevTools (Node 22+, aucune dépendance), comme
// `controle_site.mjs`. Pour chaque rubrique : un chargement à neuf de la page (cache vidé) jusqu'à la rubrique prête
// (titre affiché, plus aucun squelette, plus aucune requête en cours), puis Performance.getMetrics (tas JS, nœuds,
// mises en page, temps de script) et les octets reçus. Une capture de la page ENTIÈRE (pour la regarder).
//
//   node outils/perf_page.mjs --base http://localhost:8809 --sortie C:/chemin [--taille 1366x768] [--rubriques a,b]
//   (la base servie : `python outils/banc_annees.py --annees 5 --servir --port 8809`, ou `python outils/site_local.py`)

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const BASE = String(opt("base", "http://localhost:8809")).replace(/\/$/, "");
const SORTIE = String(opt("sortie", join(tmpdir(), "perf-page")));
const [LARGEUR, HAUTEUR] = String(opt("taille", "1366x768")).split("x").map(Number);
const PORT = 9800 + Math.floor(Math.random() * 150);
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);
const RUBRIQUES = [
  ["accueil", "#accueil/attente"], ["apercu", "#port/apercu"], ["journal", "#port/journal"], ["sanctions", "#port/sanctions"],
  ["tickets", "#port/tickets"], ["repertoire", "#port/repertoire"], ["salons", "#port/salons/questions"], ["nettoyage", "#port/nettoyage"],
  ["candidatures", "#equipage/candidatures/decidees"], ["affiches", "#capitainerie/affiches"], ["annonces", "#equipage/annonces"],
];
const filtre = opt("rubriques", "") ? String(opt("rubriques")).split(",") : null;
const PAGE_ENTIERE = !opt("sans-capture", false);
const trace = (...x) => { if (process.env.PERF_TRACE) console.log("  ·", ...x); };

let ws, prochainId = 1;
const attente = new Map(), ecouteurs = [];
const pause = (ms) => new Promise((ok) => setTimeout(ok, ms));
function envoyer(methode, params = {}, sessionId) {
  const id = prochainId++;
  ws.send(JSON.stringify({ id, method: methode, params, sessionId }));
  return new Promise((ok, ko) => attente.set(id, { ok, ko, methode }));
}

async function lancer() {
  const exe = NAVIGATEURS.find((p) => existsSync(p));
  if (!exe) throw new Error("Aucun Chrome ni Edge trouvé (option --navigateur <exe>).");
  const profil = mkdtempSync(join(tmpdir(), "perf-page-profil-"));
  const proc = spawn(exe, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profil}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--disable-sync", "--lang=fr-FR", "--enable-precise-memory-info", "about:blank"], { stdio: "ignore" });
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); if (r.ok) return { proc, profil, exe, url: (await r.json()).webSocketDebuggerUrl }; } catch (e) { /* pas encore */ }
    await pause(250);
  }
  throw new Error("Le navigateur ne répond pas.");
}

async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  const nav = await lancer();
  const resultats = [];
  try {
    ws = new WebSocket(nav.url);
    await new Promise((ok, ko) => { ws.onopen = ok; ws.onerror = ko; });
    ws.onmessage = (m) => {
      const d = JSON.parse(typeof m.data === "string" ? m.data : m.data.toString());
      if (d.id && attente.has(d.id)) { const a = attente.get(d.id); attente.delete(d.id); if (d.error) a.ko(new Error(a.methode + " : " + d.error.message)); else a.ok(d.result); }
      else if (d.method) for (const f of ecouteurs) f(d);
    };
    const { targetId } = await envoyer("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await envoyer("Target.attachToTarget", { targetId, flatten: true });
    const s = (m, p) => envoyer(m, p, sessionId);
    for (const d of ["Page.enable", "Runtime.enable", "Network.enable", "Performance.enable"]) await s(d);
    //  Le service worker servirait les données de sa mémoire : la mesure veut le réseau, comme à la première visite.
    await s("Network.setBypassServiceWorker", { bypass: true });
    await s("Emulation.setDeviceMetricsOverride", { width: LARGEUR, height: HAUTEUR, deviceScaleFactor: 1, mobile: LARGEUR < 720 });
    // Les requêtes : en cours, et les octets reçus par adresse.
    const enCours = new Map(), octets = new Map();
    let erreurs = [];
    ecouteurs.push((d) => {
      if (d.sessionId !== sessionId) return;
      if (d.method === "Network.requestWillBeSent") enCours.set(d.params.requestId, d.params.request.url);
      else if (d.method === "Network.loadingFinished" || d.method === "Network.loadingFailed") {
        const url = enCours.get(d.params.requestId) || "";
        enCours.delete(d.params.requestId);
        if (d.method === "Network.loadingFinished") octets.set(url, (octets.get(url) || 0) + (d.params.encodedDataLength || 0));
      } else if (d.method === "Runtime.exceptionThrown") erreurs.push(d.params.exceptionDetails.text);
    });
    const evaluer = async (e) => (await s("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true })).result.value;
    await s("Page.navigate", { url: BASE + "/tableau/demo" });
    await pause(2500);
    for (const [nom, ancre] of RUBRIQUES.filter(([n]) => !filtre || filtre.includes(n))) {
      await s("Network.clearBrowserCache");
      await s("Page.navigate", { url: "about:blank" });
      await pause(300);
      enCours.clear(); octets.clear(); erreurs = [];
      const t0 = Date.now();
      await s("Page.navigate", { url: BASE + "/tableau/espace/" + ancre });
      let pret = false, calme = 0;
      while (Date.now() - t0 < 30000) {
        const affiche = await evaluer("!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')").catch(() => false);
        const reseau = [...enCours.values()].filter((u) => !/\/direct|sw\.js/.test(u)).length;
        if (affiche && reseau === 0) { calme += 1; if (calme >= 3) { pret = true; break; } } else calme = 0;
        await pause(100);
      }
      trace(nom, "prête", pret, Date.now() - t0, "ms");
      const ms = Date.now() - t0 - (pret ? 200 : 0);
      const m = Object.fromEntries((await s("Performance.getMetrics")).metrics.map((x) => [x.name, x.value]));
      const recu = [...octets.entries()];
      const donnees = recu.filter(([u]) => /\/(donnees|api\/)/.test(u)).reduce((a, [, v]) => a + v, 0);
      const r = { rubrique: nom, pret, ms, tas_mo: +(m.JSHeapUsedSize / 1048576).toFixed(1), noeuds: m.Nodes, mises_en_page: m.LayoutCount,
        script_ms: Math.round((m.ScriptDuration || 0) * 1000), taches_ms: Math.round((m.TaskDuration || 0) * 1000),
        recu_ko: Math.round(recu.reduce((a, [, v]) => a + v, 0) / 1024), donnees_ko: Math.round(donnees / 1024), erreurs: [...new Set(erreurs)] };
      resultats.push(r);
      await s("Emulation.setDeviceMetricsOverride", { width: LARGEUR, height: HAUTEUR, deviceScaleFactor: 1, mobile: LARGEUR < 720 });
      trace(nom, "mesures lues");
      //  La page entière (hauteur bornée : une liste de milliers de lignes ferait une image géante).
      const hauteur = Math.min(12000, Number(await evaluer("document.documentElement.scrollHeight")) || HAUTEUR);
      //  La page entière : la fenêtre agrandie à sa hauteur (`captureBeyondViewport` ne finissait jamais sur le mur des
      //  affiches, des centaines de portraits), puis remise à sa taille.
      //  (Les murs d'images — affiches, annonces — restent à l'écran seul : leur capture entière ne finit jamais sans fenêtre.)
      const entiere = PAGE_ENTIERE && !["affiches", "annonces"].includes(nom);
      if (entiere) { await s("Emulation.setDeviceMetricsOverride", { width: LARGEUR, height: hauteur, deviceScaleFactor: 1, mobile: LARGEUR < 720 }); await pause(900); }
      const cap = await s("Page.captureScreenshot", { format: "png" });
      await s("Emulation.setDeviceMetricsOverride", { width: LARGEUR, height: HAUTEUR, deviceScaleFactor: 1, mobile: LARGEUR < 720 });
      writeFileSync(join(SORTIE, `page-${nom}.png`), Buffer.from(cap.data, "base64"));
      trace(nom, "capture", hauteur, "px");
      console.log(`${pret ? "ok   " : "LENT "} ${nom.padEnd(14)} ${String(r.ms).padStart(6)} ms · tas ${String(r.tas_mo).padStart(5)} Mo · ${String(r.noeuds).padStart(6)} nœuds · script ${String(r.script_ms).padStart(5)} ms · reçu ${r.recu_ko} Ko (données ${r.donnees_ko} Ko)${r.erreurs.length ? " · ERREURS " + r.erreurs.join(" | ") : ""}`);
    }
  } finally {
    try { await envoyer("Browser.close"); } catch (e) { /* fermé */ }
    await pause(300);
    try { nav.proc.kill(); } catch (e) { /* rien */ }
    try { rmSync(nav.profil, { recursive: true, force: true }); } catch (e) { /* reste */ }
  }
  writeFileSync(join(SORTIE, "perf_page.json"), JSON.stringify({ base: BASE, taille: `${LARGEUR}x${HAUTEUR}`, resultats }, null, 1));
  if (resultats.some((r) => !r.pret || r.erreurs.length)) process.exitCode = 1;
}
principal().catch((e) => { console.error("Mesure interrompue : " + e.message); process.exitCode = 2; });
