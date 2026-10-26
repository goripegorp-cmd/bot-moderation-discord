// outils/parcours_annonces_equipage.mjs — modifier une annonce DÉJÀ PUBLIÉE depuis l'accueil du site de l'équipage,
// joué pour de vrai contre le vrai serveur local et son FAUX Discord (26/10/2026).
//
// Le fondateur : « que uniquement nous […] on puisse modifier les annonces qu'on a déjà postées, que ça se modifie
// bien, que ça riposte pas une annonce, mais que ça fasse un truc au propre […] une bannière au propre avec des
// dimensions exactes ».
//
// Deux personnes, chacune dans SON contexte de navigateur (son cookie) : la TÊTE (le fondateur, sur le site de
// l'équipage) et un MEMBRE du clan (Kolax, portée « equipage »). Elles cliquent comme une personne ; après chaque geste,
// l'état est RELU — par l'API du site ET par ce que le faux Discord a reçu (`/tableau/demo/discord`).
//   · le membre ne voit « Modifier » nulle part (cartes, lecture d'une annonce) et l'API lui répond 403 ;
//   · la tête ouvre « Modifier » sur l'annonce publiée : titre, texte, la bannière (trop petite : refusée avec les deux
//     tailles ; 1920 × 1080 : recadrée au centre à 1600 × 640), un lien ; l'aperçu Discord (rendu du serveur) et celui du
//     site suivent AVANT l'enregistrement ;
//   · « Enregistrer sur Discord » : le message Discord a le MÊME identifiant, il est réécrit, aucun message de plus ;
//   · l'administration voit la même version (liste « Publiées » et composeur) ; le membre lit la nouvelle version ;
//   · deux personnes ne s'écrasent pas : une version changée ailleurs pendant la saisie → la version enregistrée s'ouvre.
//
//   node outils/parcours_annonces_equipage.mjs [--url http://localhost:8790] [--sortie <dossier>] [--navigateur <exe>]
// La base du site local change à chaque parcours : relancer `python outils/site_local.py` avant de rejouer.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { deflateSync } from "node:zlib";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const BASE = String(opt("url", "http://localhost:8790")).replace(/\/+$/, "");
const PAGE = BASE + "/tableau/equipage/";
const SORTIE = opt("sortie", join(tmpdir(), "annonces-equipage-parcours"));
const PORT = 9989 + Math.floor(Math.random() * 40);
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);
const N = String(Date.now()).slice(-5);
const TITRE = "Le Movie 3 est sorti, corrigé " + N;
const LIEN = { nom: "Le site du jeu", url: "https://www.roblox.com/games/" + N };

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
  const profil = mkdtempSync(join(tmpdir(), "annonces-equipage-"));
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
/** Écrire dans un champ de la fenêtre ouverte (le dernier qui correspond au sélecteur). */
function ecrire(o, selecteur, valeur, rang = -1) {
  return evaluer(o, `(() => { const l = [...${ZONE}.querySelectorAll(${JSON.stringify(selecteur)})]; const el = l.at(${rang});
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
/** Lire une adresse du site comme la page (même cookie) : { st, d }. */
const lire = (o, chemin) => evaluer(o, `fetch(${JSON.stringify(chemin)}, { credentials: "same-origin", cache: "no-store", headers: { "X-Tableau": "1" } })
  .then(async (r) => ({ st: r.status, d: await r.json().catch(() => null) }))`);
const ecrireApi = (o, chemin, corps) => evaluer(o, `fetch(${JSON.stringify(chemin)}, { method: "POST", credentials: "same-origin",
  headers: { "Content-Type": "application/json", "X-Tableau": "1" }, body: ${JSON.stringify(JSON.stringify(corps))} }).then(async (r) => ({ st: r.status, d: await r.json().catch(() => null) }))`);
/** Ce que le FAUX Discord a reçu dans le post 📢 Infos (le site local seulement). */
const discordInfos = () => fetch(BASE + "/tableau/demo/discord?post=infos", { cache: "no-store" }).then((r) => r.json());
async function aller(o, url) {
  await evaluer(o, "(() => { for (const d of [...document.querySelectorAll('dialog[open]')].reverse()) d.close(); return true; })()").catch(() => null);
  await o.s("Page.navigate", { url });
  const pret = await attendre(() => evaluer(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 15000, 200);
  await pause(800);
  return pret;
}
const accueil = (o) => aller(o, PAGE + "?vu=" + Date.now() + "#accueil");   // toujours une page fraîche
const texteZone = (o) => evaluer(o, `${ZONE} === document ? document.body.innerText : ${ZONE}.innerText`);
/** Les boutons et liens visibles de la page (ou de la fenêtre ouverte) : leur texte. */
const gestes = (o) => evaluer(o, `(() => { const vis = ${visible}; return [...${ZONE}.querySelectorAll("button, a[href], [role=button]")].filter(vis)
  .map((x) => ((x.textContent || "") + " " + (x.getAttribute("aria-label") || "")).replace(/\\s+/g, " ").trim()); })()`);
/** Choisir un fichier dans le prochain sélecteur de fichier ouvert par `declencher` (un vrai clic). */
async function choisirFichier(o, declencher, chemin) {
  await o.s("Page.setInterceptFileChooserDialog", { enabled: true });
  const choix = new Promise((ok) => { const f = (e) => { if (e.sessionId === o.sessionId && e.method === "Page.fileChooserOpened") { ecouteurs.splice(ecouteurs.indexOf(f), 1); ok(e.params); } }; ecouteurs.push(f); });
  const ok = await declencher();
  const fc = ok ? await Promise.race([choix, pause(5000).then(() => null)]) : null;
  if (fc) await o.s("DOM.setFileInputFiles", { files: [chemin], backendNodeId: fc.backendNodeId });
  await o.s("Page.setInterceptFileChooserDialog", { enabled: false });
  return !!fc;
}

/** Une vraie image PNG (deux bandes et un disque au centre), écrite sans dépendance : signature, IHDR, IDAT, IEND. */
function png(l, hh) {
  const crcT = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (b) => { let c = 0xffffffff; for (const x of b) c = crcT[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const bloc = (type, data) => { const t = Buffer.from(type, "ascii"), lg = Buffer.alloc(4), cr = Buffer.alloc(4); lg.writeUInt32BE(data.length); cr.writeUInt32BE(crc(Buffer.concat([t, data]))); return Buffer.concat([lg, t, data, cr]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(l, 0); ihdr.writeUInt32BE(hh, 4); ihdr[8] = 8; ihdr[9] = 2;
  const brut = Buffer.alloc((l * 3 + 1) * hh);
  const r2 = (Math.min(l, hh) * 0.3) ** 2;
  for (let y = 0; y < hh; y++) for (let x = 0; x < l; x++) {
    const i = y * (l * 3 + 1) + 1 + x * 3, dedans = (x - l / 2) ** 2 + (y - hh / 2) ** 2 < r2;
    brut[i] = dedans ? 236 : y < hh * 0.55 ? 196 - (y * 120 / hh | 0) : 24; brut[i + 1] = dedans ? 196 : y < hh * 0.55 ? 110 : 52; brut[i + 2] = dedans ? 120 : y < hh * 0.55 ? 60 : 70;
  }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), bloc("IHDR", ihdr), bloc("IDAT", deflateSync(brut)), bloc("IEND", Buffer.alloc(0))]);
}

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
  const fichier = join(SORTIE, String(numero).padStart(2, "0") + "-" + nom.replace(/[^a-z0-9]+/gi, "-").toLowerCase().slice(0, 80) + ".png");
  try { const c = await o.s("Page.captureScreenshot", { format: "png" }); writeFileSync(fichier, Buffer.from(c.data, "base64")); } catch (e) { /* capture impossible */ }
  resultats.push({ nom, ok, detail, capture: fichier });
  console.log(`${ok ? "ok    " : "ÉCHEC "} ${nom}${detail ? "\n        · " + detail : ""}`);
  return ok;
}

// ═══ LE PARCOURS ═════════════════════════════════════════════════════════════
async function parcours(t, m) {
  //  L'état de départ : l'annonce publiée telle que l'administration la lit, et ce que le faux Discord a reçu.
  const publiees = async () => ((await lire(t, "/tableau/espace/api/clan/evenements")).d || {}).publiees || [];
  const depart = (await publiees()).find((x) => x.titre.startsWith("Le Movie 3"));
  if (!depart) throw new Error("l'annonce de démonstration « Le Movie 3 » est absente (site local neuf ?)");
  const mid = depart.lien.split("/").pop();
  const avantDiscord = await discordInfos();
  const carteDe = (o, texte) => `[...document.querySelectorAll('article.actu')].find((a) => a.textContent.includes(${JSON.stringify(texte)}))`;

  await etape(m, "Membre : « Modifier » n'existe nulle part pour lui (cartes, lecture) ; l'API lui répond 403", async () => {
    if (!await accueil(m)) return { ok: false, detail: "l'accueil ne s'affiche pas" };
    const surCartes = await evaluer(m, "[...document.querySelectorAll('article.actu button')].filter((b) => /Modifier/.test(b.textContent)).length");
    if (!await cliquer(m, "button.lien-titre", "Le Movie 3")) return { ok: false, detail: "l'annonce n'est pas dans les actualités du membre" };
    await attendre(() => evaluer(m, "!!document.querySelector('dialog[open] .lecture-actu')"), 5000);
    const lecture = await gestes(m);
    const api = [await lire(m, "/tableau/espace/api/equipage/publication?id=" + depart.id),
      await ecrireApi(m, "/tableau/espace/api/equipage/publication", { id: depart.id, version: depart.version, titre: "Piraté" }),
      await ecrireApi(m, "/tableau/espace/api/clan/modifier", { id: depart.id, version: depart.version, titre: "Piraté" })].map((x) => x.st);
    const ok = surCartes === 0 && !lecture.some((x) => /Modifier/.test(x)) && api.every((x) => x === 403);
    return { ok, detail: `« Modifier » sur les cartes : ${surCartes} · lecture : ${lecture.join(", ")} · API : ${api.join(", ")}` };
  });

  await etape(t, "Tête : « Modifier » sur l'annonce publiée ouvre l'éditeur (titre, texte, bannière, liens, aperçu Discord)", async () => {
    if (!await accueil(t)) return { ok: false, detail: "l'accueil ne s'affiche pas" };
    const ok = await evaluer(t, `(() => { const c = ${carteDe(t, "Le Movie 3")}; const b = c && [...c.querySelectorAll('button')].find((x) => x.textContent.includes('Modifier'));
      if (!b) return false; b.scrollIntoView({ block: "center" }); b.click(); return true; })()`);
    if (!ok) return { ok: false, detail: "« Modifier » absent de la carte de l'annonce" };
    const apercu = await attendre(() => evaluer(t, "!!document.querySelector('dialog[open] .discord-carte')"), 8000);
    const z = await texteZone(t);
    const champs = ["Titre", "Texte", "Bannière : 1600 × 640 px (5:2) · PNG, JPG ou WebP · 8 Mo au plus", "Liens", "Sur Discord", "Sur le site",
      "rien n'est republié", "Enregistrer sur Discord"].filter((x) => !z.includes(x));
    return { ok: !!apercu && !champs.length, detail: champs.length ? "absent : " + champs.join(", ") : "aperçu Discord rendu par le serveur" };
  });

  await etape(t, "Tête : une bannière trop petite est refusée (taille reçue, taille demandée) ; 1920 × 1080 est recadrée au centre", async () => {
    const petite = join(SORTIE, "banniere-petite.png"), grande = join(SORTIE, "banniere-1920x1080.png");
    writeFileSync(petite, png(800, 320));
    writeFileSync(grande, png(1920, 1080));
    const bouton = () => cliquer(t, "dialog[open] .banniere-choix button", "image", { geste: true });
    if (!await choisirFichier(t, bouton, petite)) return { ok: false, detail: "le choix de fichier ne s'est pas ouvert" };
    const refus = await attendre(() => evaluer(t, "[...document.querySelectorAll('.toast')].map((x) => x.textContent).find((x) => x.includes('trop petite')) || ''"), 6000);
    const avant = await evaluer(t, "(document.querySelector('dialog[open] .banniere-choix .banniere-cadre img') || {}).src || ''");
    if (!await choisirFichier(t, bouton, grande)) return { ok: false, detail: "second choix de fichier impossible" };
    //  La NOUVELLE bannière (son adresse change), refaite par le serveur, et la phrase qui dit ce qui a été fait.
    const note = await attendre(() => evaluer(t, "(document.querySelector('dialog[open] .banniere-note') || {}).textContent || ''"), 15000);
    const taille = await attendre(() => evaluer(t, `(() => { const i = document.querySelector('dialog[open] .banniere-choix .banniere-cadre img');
      return i && i.src !== ${JSON.stringify(avant)} && i.complete && i.naturalWidth ? i.naturalWidth + "x" + i.naturalHeight : ""; })()`), 10000);
    const ok = /800 × 320 px reçue, il faut au moins 1600 × 640 px/.test(refus || "") && taille === "1600x640" && note.includes("Recadrée au centre : 1920 × 1080 px → 1600 × 640 px");
    return { ok, detail: `refus : « ${refus} » · bannière envoyée : ${taille} · ${note}` };
  });

  await etape(t, "Tête : titre, texte et un lien — l'aperçu Discord (serveur) et celui du site suivent AVANT d'enregistrer", async () => {
    await ecrire(t, "input.saisie", TITRE, 0);
    await ecrire(t, "textarea", "**Le Movie 3 est là**, corrigé depuis le site de l'équipage.\nTout est dans le post Infos.");
    if (!await cliquer(t, "dialog[open] .liens-editeur button", "Ajouter un lien")) return { ok: false, detail: "« Ajouter un lien » absent" };
    await pause(300);
    await ecrire(t, ".lien-ligne input", LIEN.nom, -2);
    await ecrire(t, ".lien-ligne input", LIEN.url, -1);
    const discord = await attendre(async () => { const x = await evaluer(t, "(document.querySelector('dialog[open] .apercu-zone') || {}).innerText || ''"); return x.includes(TITRE) && x.includes(LIEN.nom) ? x : null; }, 8000);
    if (!await cliquer(t, "dialog[open] .apercu-onglets button", "Sur le site")) return { ok: false, detail: "onglet « Sur le site » absent" };
    const site = await attendre(async () => { const x = await evaluer(t, "(document.querySelector('dialog[open] .apercu-site') || {}).innerText || ''"); return x.includes(TITRE) && x.includes(LIEN.nom) ? x : null; }, 6000);
    const versionPendant = (await publiees()).find((x) => x.id === depart.id).version;
    await cliquer(t, "dialog[open] .apercu-onglets button", "Sur Discord");
    return { ok: !!discord && !!site && versionPendant === depart.version, detail: (discord ? "Discord ok" : "aperçu Discord sans le titre ou le lien") + " · " + (site ? "site ok" : "aperçu du site incomplet")
      + " · rien d'enregistré pendant la saisie (version " + versionPendant + ")" };
  });

  await etape(t, "Tête : « Enregistrer sur Discord » — le MÊME message Discord (même identifiant), réécrit, aucun message de plus", async () => {
    if (!await cliquer(t, "dialog[open] .pancarte-pied button", "Enregistrer sur Discord")) return { ok: false, detail: "« Enregistrer sur Discord » absent" };
    const ferme = await attendre(() => evaluer(t, "!document.querySelector('dialog[open]')"), 10000);
    const apres = await attendre(async () => { const x = (await publiees()).find((e) => e.id === depart.id); return x && x.titre === TITRE ? x : null; }, 8000);
    const d = await discordInfos();
    const msg = d.messages.find((x) => x.id === mid);
    const memes = JSON.stringify(d.messages.map((x) => x.id)) === JSON.stringify(avantDiscord.messages.map((x) => x.id));
    const ok = !!ferme && !!apres && apres.version === depart.version + 1 && apres.lien === depart.lien && memes && !!msg && msg.reecrit
      && msg.texte.includes(TITRE) && msg.boutons.includes(LIEN.nom);
    return { ok, detail: `message ${mid} : ${msg ? (msg.reecrit ? "réécrit" : "PAS réécrit") : "DISPARU"} · messages du post : ${avantDiscord.messages.length} → ${d.messages.length}`
      + ` (${memes ? "les mêmes" : "CHANGÉS"}) · version ${depart.version} → ${apres && apres.version} · lien ${apres && apres.lien === depart.lien ? "identique" : "CHANGÉ"}` };
  });

  await etape(t, "Tête : l'accueil montre aussitôt la nouvelle version (bannière 5:2, sans rien rogner)", async () => {
    const carte = await attendre(() => evaluer(t, `(() => { const c = ${carteDe(t, TITRE)}; if (!c) return null; const i = c.querySelector('.banniere-cadre img');
      const f = c.querySelector('.banniere-cadre').getBoundingClientRect(); return i && i.complete ? { nw: i.naturalWidth, nh: i.naturalHeight, rapport: +(f.width / f.height).toFixed(2), hors: c.querySelector('.banniere-cadre').classList.contains('hors-format') } : null; })()`), 8000);
    return { ok: !!carte && carte.nw === 1600 && carte.nh === 640 && Math.abs(carte.rapport - 2.5) < 0.03 && !carte.hors, detail: JSON.stringify(carte) };
  });

  await etape(m, "Membre : il lit la nouvelle version (bannière, texte, lien), toujours sans « Modifier »", async () => {
    if (!await accueil(m)) return { ok: false, detail: "l'accueil ne s'affiche pas" };
    if (!await cliquer(m, "button.lien-titre", TITRE)) return { ok: false, detail: "le membre ne voit pas la nouvelle version" };
    await attendre(() => evaluer(m, "!!document.querySelector('dialog[open] .lecture-actu .banniere-cadre img')"), 5000);
    const z = await texteZone(m);
    const lien = await evaluer(m, `!![...document.querySelectorAll('dialog[open] .actu-liens a')].find((a) => a.href === ${JSON.stringify(LIEN.url)})`);
    const boutons = await gestes(m);
    const ok = z.includes("corrigé depuis le site de l'équipage") && lien && !boutons.some((x) => /Modifier/.test(x));
    return { ok, detail: `lien : ${lien ? "présent" : "absent"} · boutons : ${boutons.join(", ")}` };
  });

  await etape(t, "Administration : la même version dans « Publiées » et dans le composeur (titre, bannière, lien)", async () => {
    if (!await aller(t, BASE + "/tableau/espace/#equipage/annonces/publiees")) return { ok: false, detail: "« Publiées » ne s'affiche pas" };
    await evaluer(t, "(async () => { for (const g of document.querySelectorAll('details.groupe')) g.open = true; await new Promise(r => setTimeout(r, 400)); return 1; })()");
    const carte = await attendre(() => evaluer(t, `(() => { const c = [...document.querySelectorAll('article.evt-carte')].find((a) => a.textContent.includes(${JSON.stringify(TITRE)})); return c ? c.textContent : null; })()`), 8000);
    if (!carte) return { ok: false, detail: "la liste « Publiées » n'a pas la nouvelle version" };
    await evaluer(t, `(() => { const c = [...document.querySelectorAll('article.evt-carte')].find((a) => a.textContent.includes(${JSON.stringify(TITRE)})); [...c.querySelectorAll('button')].find((b) => b.textContent.includes('Modifier')).click(); return 1; })()`);
    const composeur = await attendre(() => evaluer(t, `(() => { const i = document.querySelector('.composeur-form input.saisie'); return i && i.value === ${JSON.stringify(TITRE)} ? 1 : 0; })()`), 8000);
    const lien = await evaluer(t, `[...document.querySelectorAll('.liens-editeur input')].map((i) => i.value).join(" | ")`);
    const banniere = await attendre(() => evaluer(t, "(() => { const i = document.querySelector('.composeur-form .banniere-cadre img'); return i && i.complete ? i.naturalWidth + 'x' + i.naturalHeight : ''; })()"), 6000);
    await evaluer(t, "(() => { const f = document.querySelector('.banniere-champ'); if (f) f.scrollIntoView({ block: 'start' }); return 1; })()");
    return { ok: !!composeur && lien.includes(LIEN.url) && banniere === "1600x640", detail: `composeur : ${composeur ? "titre identique" : "titre différent"} · liens : ${lien} · bannière ${banniere}` };
  });

  await etape(t, "Deux personnes ne s'écrasent pas : changée ailleurs pendant la saisie → la version enregistrée s'ouvre, rien d'écrasé", async () => {
    if (!await accueil(t)) return { ok: false, detail: "l'accueil ne s'affiche pas" };
    await evaluer(t, `(() => { const c = ${carteDe(t, TITRE)}; [...c.querySelectorAll('button')].find((x) => x.textContent.includes('Modifier')).click(); return 1; })()`);
    await attendre(() => evaluer(t, "!!document.querySelector('dialog[open] .discord-carte')"), 8000);
    //  Pendant ce temps, « quelqu'un d'autre » enregistre une autre version (par l'administration).
    const ailleurs = (await publiees()).find((x) => x.id === depart.id);
    const r = await ecrireApi(t, "/tableau/espace/api/clan/modifier", { id: depart.id, version: ailleurs.version, texte: "Écrit ailleurs " + N });
    if (r.st !== 200) return { ok: false, detail: "écriture d'à côté refusée : " + r.st };
    await ecrire(t, "textarea", "Ma version, saisie pendant ce temps.");
    await cliquer(t, "dialog[open] .pancarte-pied button", "Enregistrer sur Discord");
    const avis = await attendre(() => evaluer(t, "[...document.querySelectorAll('.toast')].map((x) => x.textContent).find((x) => x.includes('a changé ailleurs')) || ''"), 8000);
    const rouvert = await attendre(() => evaluer(t, "(() => { const z = document.querySelector('dialog[open] textarea'); return z && z.value.startsWith('Écrit ailleurs') ? 1 : 0; })()"), 8000);
    const fin = (await publiees()).find((x) => x.id === depart.id);
    const d = await discordInfos();
    const msg = d.messages.find((x) => x.id === mid);
    const ok = !!avis && !!rouvert && fin.valeurs.texte.startsWith("Écrit ailleurs") && msg && msg.texte.includes("Écrit ailleurs") && d.messages.length === avantDiscord.messages.length;
    await evaluer(t, "(() => { for (const d of [...document.querySelectorAll('dialog[open]')].reverse()) d.close(); return 1; })()");
    return { ok, detail: `avis : « ${avis} » · éditeur rouvert sur la version enregistrée : ${rouvert ? "oui" : "non"} · Discord : ${msg ? "le même message" : "?"}` };
  });
}

// ─── Le tout ────────────────────────────────────────────────────────────────
async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  const nav = await lancerNavigateur();
  console.log("Navigateur : " + nav.exe + "\nCaptures : " + SORTIE);
  try {
    await connecter(nav.wsUrl);
    const tete = await personne("tête", "/tableau/demo?vers=equipage");
    const membre = await personne("membre", "/tableau/demo?qui=equipage");
    await parcours(tete, membre);
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
