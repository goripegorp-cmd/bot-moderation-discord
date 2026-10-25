// outils/parcours_site.mjs — les VRAIS parcours du site v2, joués dans la vraie page contre le vrai serveur local.
//
// Un Edge (ou Chrome) SANS FENÊTRE ouvre le site local (`python outils/site_local.py` : le même serveur que le bot,
// un faux Discord, une base neuve à chaque démarrage), clique comme une personne, puis RELIT l'état par l'API après
// chaque geste : un bouton qui « marche » à l'écran sans rien changer au serveur est un échec. Une capture par étape.
//
//   node outils/parcours_site.mjs [--url http://localhost:8790] [--sortie <dossier>] [--parcours recrutement,capitainerie,metiers]
//                                 [--navigateur <exe>]
//
// La base du site local change à chaque parcours : relancer le site local avant de rejouer.

import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const BASE = String(opt("url", "http://localhost:8790")).replace(/\/+$/, "");
const SITE = BASE + "/tableau/espace/";
const SORTIE = opt("sortie", join(tmpdir(), "capitainerie-parcours"));
const PARCOURS = String(opt("parcours", "recrutement")).split(",");
const PORT = 9739 + Math.floor(Math.random() * 200);
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);

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
  const profil = mkdtempSync(join(tmpdir(), "capitainerie-parcours-"));
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
async function onglet() {
  const { targetId } = await envoyer("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await envoyer("Target.attachToTarget", { targetId, flatten: true });
  const s = (m, p) => envoyer(m, p, sessionId);
  await s("Page.enable");
  await s("Runtime.enable");
  ecouteurs.push((d) => {
    if (d.sessionId !== sessionId) return;
    if (d.method === "Runtime.exceptionThrown") erreursPage.push("exception : " + ((d.params.exceptionDetails.exception || {}).description || d.params.exceptionDetails.text));
    if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") erreursPage.push("console : " + d.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
  });
  await s("Emulation.setDeviceMetricsOverride", { width: 1366, height: 900, deviceScaleFactor: 1, mobile: false });
  return { s };
}
async function evaluer(o, expression) {
  const r = await o.s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text);
  return r.result.value;
}

// ─── Les gestes, comme une personne ─────────────────────────────────────────
// La zone : la dernière pancarte ouverte (une confirmation s'ouvre par-dessus le dossier), sinon la page.
const ZONE = "([...document.querySelectorAll('dialog[open]')].pop() || document)";
const visible = "(x) => x.getClientRects().length && getComputedStyle(x).visibility !== 'hidden'";
/** Cliquer l'élément visible (et actif) dont le texte contient `texte`. */
function cliquer(o, selecteur, texte, { partout = false } = {}) {
  return evaluer(o, `(() => { const z = ${partout ? "document" : ZONE}; const vis = ${visible};
    const el = [...z.querySelectorAll(${JSON.stringify(selecteur)})].find((x) => vis(x) && !x.disabled && (x.textContent || x.getAttribute("aria-label") || "").replace(/\\s+/g, " ").includes(${JSON.stringify(texte)}));
    if (!el) return false; el.scrollIntoView({ block: "center" }); el.click(); return true; })()`);
}
/** Écrire dans le champ (input / textarea) repéré par son texte d'exemple ou son libellé accessible. */
function ecrire(o, repere, valeur) {
  return evaluer(o, `(() => { const z = ${ZONE};
    const el = [...z.querySelectorAll("input, textarea")].filter((x) => x.placeholder === ${JSON.stringify(repere)} || x.getAttribute("aria-label") === ${JSON.stringify(repere)}).pop();
    if (!el) return false; el.focus(); el.value = ${JSON.stringify(valeur)}; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
}
const texteZone = (o) => evaluer(o, `${ZONE}.body ? document.body.innerText : ${ZONE}.innerText`);
async function attendre(fn, ms = 15000, pas = 400) {
  const t0 = Date.now();
  let v = null;
  while (Date.now() - t0 < ms) {
    try { v = await fn(); } catch (e) { v = null; }
    if (v) return v;
    await pause(pas);
  }
  return v;
}
/** Lire l'API comme la page (même session, même en-tête). */
function api(o, chemin) {
  return evaluer(o, `fetch(${JSON.stringify(SITE + "api/" + chemin)}, { credentials: "same-origin", headers: { "X-Tableau": "1" } }).then((r) => r.json())`);
}
async function aller(o, ancre) {
  await fermerTout(o).catch(() => null);   // une étape ratée ne laisse pas sa pancarte à la suivante
  await o.s("Page.navigate", { url: SITE + ancre });
  const pret = await attendre(() => evaluer(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 12000, 200);
  await pause(600);
  return pret;
}
const fermerTout = (o) => evaluer(o, "(() => { for (const d of [...document.querySelectorAll('dialog[open]')].reverse()) d.close(); return true; })()");

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

// ═══ LE RECRUTEMENT ═════════════════════════════════════════════════════════
async function ouvrirCandidature(o, ticket, attendu) {
  await fermerTout(o);
  await aller(o, "#equipage/candidatures");
  if (!await cliquer(o, ".feuillet.lien", "Ticket #" + ticket + " ")) return false;
  return attendre(async () => (await texteZone(o)).includes(attendu), 10000);
}
async function parcoursRecrutement(o) {
  const dossier = (t) => api(o, "recrutement/dossier?ticket=" + t);
  const suivi = await api(o, "recrutement/suivi");
  const parEtape = (e) => (suivi.ouverts || []).filter((x) => x.etape === e).map((x) => x.ticket);
  const [t1, t1bis] = parEtape("etape1");
  const [tAttente] = parEtape("etape2");
  const [tCorr, tCorr2] = parEtape("reponses");

  await etape(o, "Liste : les étapes du serveur", async () => {
    await aller(o, "#equipage/candidatures");
    const t = await evaluer(o, "document.querySelector('#contenu').innerText");
    const nb = (lib) => { const m = t.match(new RegExp(lib + "\\s+(\\d+)")); return m ? Number(m[1]) : -1; };
    const ok = nb("Étape 1 à décider") === parEtape("etape1").length && nb("Réponses à corriger") === parEtape("reponses").length && nb("Questions envoyées") === parEtape("etape2").length;
    return { ok, detail: `page : ${nb("Étape 1 à décider")}/${nb("Réponses à corriger")}/${nb("Questions envoyées")} · serveur : ${parEtape("etape1").length}/${parEtape("reponses").length}/${parEtape("etape2").length}` };
  });

  await etape(o, "Étape 1 → étape 2 : la sélection précédente part", async () => {
    if (!await ouvrirCandidature(o, t1, "La décision de l'étape 1")) return { ok: false, detail: "dossier de l'étape 1 introuvable (ticket " + t1 + ")" };
    if (!await cliquer(o, "button", "Passer à l'étape 2")) return { ok: false, detail: "bouton « Passer à l'étape 2 » absent" };
    if (!await attendre(() => cliquer(o, "button.depart", "Reprendre la sélection précédente"), 6000)) return { ok: false, detail: "départ « sélection précédente » absent" };
    await pause(300);
    if (!await cliquer(o, "button.envoyer", "Envoyer")) return { ok: false, detail: "bouton d'envoi absent ou inactif" };
    const d = await attendre(async () => { const x = await dossier(t1); return x.etape === "etape2" && x.envois.length === 1 ? x : null; });
    if (!d) return { ok: false, detail: "le serveur n'a pas l'envoi : " + JSON.stringify(await dossier(t1)).slice(0, 200) };
    const vu = await attendre(async () => (await texteZone(o)).includes("questions envoyées"), 6000);
    return { ok: !!vu, detail: d.envois[0].nb + " questions envoyées" + (vu ? "" : " — la page ne l'affiche pas") };
  });

  await etape(o, "En attente : questions listées, aucune correction possible", async () => {
    if (!await ouvrirCandidature(o, tAttente, "questions envoyées")) return { ok: false, detail: "dossier en attente introuvable" };
    const t = await texteZone(o);
    return { ok: t.includes("En attente des réponses du candidat") && !t.includes("Réponse du candidat"), detail: "" };
  });

  await etape(o, "Correction : tout juste, puis accepter", async () => {
    if (!await ouvrirCandidature(o, tCorr, "la correction")) return { ok: false, detail: "dossier à corriger introuvable" };
    const avant = await dossier(tCorr);
    const total = avant.envois[0].questions.length;
    const rep = await evaluer(o, `[...${ZONE}.querySelectorAll(".correction-reponse p")].filter((p) => !p.classList.contains("aide")).length`);
    if (rep !== total) return { ok: false, detail: `réponses du candidat affichées : ${rep}/${total}` };
    for (let i = 0; i < total + 2; i++) {
      const fait = await evaluer(o, `(() => { const b = ${ZONE}.querySelector('.bouton-juste[aria-pressed="false"]:not([disabled])'); if (!b) return false; b.click(); return true; })()`);
      if (!fait) break;
      await pause(250);
    }
    const corrige = await attendre(async () => { const x = await dossier(tCorr); const b = x.envois[0].bilan; return b.justes === b.total ? x : null; }, 20000);
    if (!corrige) return { ok: false, detail: "corrections non arrivées au serveur : " + JSON.stringify((await dossier(tCorr)).envois[0].bilan) };
    if (!await attendre(() => cliquer(o, "button", "Accepter · " + total + "/" + total), 6000)) return { ok: false, detail: "bouton « Accepter · " + total + "/" + total + " » absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Accepter"), 6000)) return { ok: false, detail: "confirmation absente" };
    const d = await attendre(async () => { const x = await dossier(tCorr); return x.etape === "accepte" && x.statut_ticket === "ferme" ? x : null; }, 15000);
    return { ok: !!d, detail: d ? "accepté, ticket fermé" : "état : " + JSON.stringify(await dossier(tCorr)).slice(0, 200) };
  });

  await etape(o, "Refuser après correction : message, fermeture", async () => {
    if (!await ouvrirCandidature(o, tCorr2, "la correction")) return { ok: false, detail: "second dossier à corriger introuvable" };
    if (!await cliquer(o, "button", "Refuser")) return { ok: false, detail: "bouton « Refuser » absent" };
    const t = await attendre(async () => { const x = await texteZone(o); return x.includes("La direction a étudié ta candidature") ? x : null; }, 6000);
    if (!t) return { ok: false, detail: "la confirmation ne montre pas le message exact du serveur" };
    if (t.includes("-#")) return { ok: false, detail: "le message montre la syntaxe Discord « -# »" };
    if (!await cliquer(o, "dialog[open] button", "Refuser et fermer le ticket")) return { ok: false, detail: "confirmation absente" };
    const prevu = await attendre(async () => { const x = await dossier(tCorr2); return x.fermeture_prevue || x.etape === "refuse" ? x : null; }, 10000);
    if (!prevu) return { ok: false, detail: "le serveur n'a pas prévu la fermeture" };
    const ferme = await attendre(async () => { const x = await dossier(tCorr2); return x.statut_ticket === "ferme" && x.etape === "refuse" ? x : null; }, 45000, 1000);
    return { ok: !!ferme, detail: ferme ? "refusé, ticket fermé" : "état : " + JSON.stringify(await dossier(tCorr2)).slice(0, 200) };
  });

  await etape(o, "Refuser l'étape 1 : message exact, fermeture prévue", async () => {
    if (!await ouvrirCandidature(o, t1bis, "La décision de l'étape 1")) return { ok: false, detail: "second dossier de l'étape 1 introuvable" };
    if (!await cliquer(o, "button", "Refuser l'étape 1")) return { ok: false, detail: "bouton absent" };
    const t = await attendre(async () => { const x = await texteZone(o); return x.includes("ne correspondent pas à ce que nous attendons") ? x : null; }, 6000);
    if (!t) return { ok: false, detail: "la confirmation ne montre pas le message du serveur" };
    if (!await cliquer(o, "dialog[open] button", "Refuser et fermer le ticket")) return { ok: false, detail: "confirmation absente" };
    const d = await attendre(async () => { const x = await dossier(t1bis); return x.etape === "refus_etape1" ? x : null; }, 10000);
    return { ok: !!d, detail: d ? "étape 1 refusée" + (d.fermeture_prevue ? ", fermeture prévue" : ", ticket fermé") : "état : " + JSON.stringify(await dossier(t1bis)).slice(0, 200) };
  });

  // ─── La banque de questions ───
  const QUESTION = "Combien de joueurs au plus un équipage du parcours compte-t-il ?";
  const banque = () => api(o, "recrutement/banque");
  const laQuestion = async () => ((await banque()).questions || []).find((q) => q.question === QUESTION);

  await etape(o, "Banque : ajouter une question", async () => {
    await fermerTout(o);
    await aller(o, "#equipage/candidatures/questionnaire");
    if (!await cliquer(o, "button", "Ajouter une question")) return { ok: false, detail: "bouton absent" };
    await attendre(async () => (await texteZone(o)).includes("Nouvelle question"), 5000);
    const champs = [await ecrire(o, "Quel studio développe RELL Seas ?", QUESTION), await ecrire(o, "RELL Games", "Huit"),
      await ecrire(o, "https://rellseas.fandom.com/wiki/…", "https://rellseas.fandom.com/wiki/Crews")];
    if (champs.includes(false)) return { ok: false, detail: "champ introuvable : " + JSON.stringify(champs) };
    if (!await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "bouton « Enregistrer » absent" };
    const q = await attendre(laQuestion, 15000);
    if (!q) return { ok: false, detail: "le serveur n'a pas la question" };
    const ok = q.reponse === "Huit" && q.difficulte === "facile" && q.source === "https://rellseas.fandom.com/wiki/Crews" && q.actif === true && q.statut === "a_verifier";
    return { ok, detail: JSON.stringify({ reponse: q.reponse, difficulte: q.difficulte, source: q.source, actif: q.actif, statut: q.statut }) };
  });

  await etape(o, "Banque : désactiver puis réactiver", async () => {
    await aller(o, "#equipage/candidatures/questionnaire");
    if (!await ecrire(o, "Question, réponse, source…", QUESTION)) return { ok: false, detail: "recherche absente" };
    await pause(700);
    const basculer = () => evaluer(o, `(() => { const l = [...document.querySelectorAll(".banque-ligne")].find((x) => x.textContent.includes(${JSON.stringify(QUESTION)}));
      const i = l && l.querySelector("input[type=checkbox], [role=switch], button[aria-pressed]"); if (!i) return false; i.click(); return true; })()`);
    if (!await basculer()) return { ok: false, detail: "interrupteur « Active » introuvable" };
    const off = await attendre(async () => { const q = await laQuestion(); return q && q.actif === false ? q : null; });
    if (!off) return { ok: false, detail: "désactivation non reçue" };
    await pause(800);
    if (!await attendre(basculer, 5000)) return { ok: false, detail: "interrupteur introuvable après la désactivation" };
    const on = await attendre(async () => { const q = await laQuestion(); return q && q.actif === true ? q : null; });
    return { ok: !!on, detail: on ? "" : "réactivation non reçue" };
  });

  await etape(o, "Banque : retirer la question", async () => {
    await aller(o, "#equipage/candidatures/questionnaire");
    await ecrire(o, "Question, réponse, source…", QUESTION);
    await pause(700);
    const clic = await evaluer(o, `(() => { const l = [...document.querySelectorAll(".banque-ligne")].find((x) => x.textContent.includes(${JSON.stringify(QUESTION)}));
      const b = l && [...l.querySelectorAll("button")].find((x) => x.textContent.includes("Retirer")); if (!b) return false; b.click(); return true; })()`);
    if (!clic) return { ok: false, detail: "bouton « Retirer » introuvable" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Retirer"), 5000)) return { ok: false, detail: "confirmation absente" };
    const q = await attendre(async () => { const x = await laQuestion(); return x && x.retiree ? x : null; });
    if (!q) return { ok: false, detail: "retrait non reçu" };
    await aller(o, "#equipage/candidatures/questionnaire");
    await ecrire(o, "Question, réponse, source…", QUESTION);
    await pause(700);
    const encore = await evaluer(o, `[...document.querySelectorAll(".banque-ligne")].some((x) => x.textContent.includes(${JSON.stringify(QUESTION)}))`);
    return { ok: !encore, detail: encore ? "la question retirée est encore affichée" : "" };
  });

  await etape(o, "Liens : en ajouter un", async () => {
    await aller(o, "#equipage/candidatures/questionnaire");
    const avant = (await banque()).liens.length;
    if (!await cliquer(o, "button", "Ajouter un lien")) return { ok: false, detail: "bouton absent" };
    await pause(300);
    const ok1 = await ecrire(o, "Titre du lien", "Les équipages (wiki)");
    const ok2 = await ecrire(o, "Adresse", "https://rellseas.fandom.com/wiki/Crews");
    if (!ok1 || !ok2) return { ok: false, detail: "champs du lien introuvables" };
    if (!await cliquer(o, "button", "Enregistrer les liens")) return { ok: false, detail: "bouton « Enregistrer les liens » absent" };
    const b = await attendre(async () => { const x = await banque(); return x.liens.length === avant + 1 ? x : null; });
    return { ok: !!b && b.liens.some((l) => l.url === "https://rellseas.fandom.com/wiki/Crews" && l.titre === "Les équipages (wiki)"), detail: b ? "" : "liens non reçus" };
  });

  await etape(o, "Réglages : une question de plus", async () => {
    await aller(o, "#equipage/candidatures/questionnaire");
    const avant = (await banque()).reglages.nombre;
    if (!await cliquer(o, "button", "Une de plus")) return { ok: false, detail: "bouton « Une de plus » absent" };
    if (!await cliquer(o, "button", "Enregistrer les réglages")) return { ok: false, detail: "bouton absent" };
    const b = await attendre(async () => { const x = await banque(); return x.reglages.nombre === avant + 1 ? x : null; });
    return { ok: !!b, detail: b ? avant + " → " + b.reglages.nombre : "réglages non reçus" };
  });

  await etape(o, "Modèles : enregistrer la sélection précédente, la mettre par défaut", async () => {
    await aller(o, "#equipage/candidatures/questionnaire");
    if (!await cliquer(o, "button", "Nouveau modèle")) return { ok: false, detail: "bouton « Nouveau modèle » absent" };
    if (!await attendre(() => cliquer(o, "button.depart", "Reprendre la sélection précédente"), 6000)) return { ok: false, detail: "départ absent" };
    if (!await cliquer(o, "button", "Enregistrer le modèle")) return { ok: false, detail: "bouton « Enregistrer le modèle » absent" };
    if (!await attendre(() => ecrire(o, "Spécial Movie 3", "Parcours complet"), 5000)) return { ok: false, detail: "nom du modèle introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "confirmation absente" };
    const m = await attendre(async () => ((await banque()).modeles || []).find((x) => x.nom === "Parcours complet"));
    if (!m) return { ok: false, detail: "le serveur n'a pas le modèle" };
    await fermerTout(o);
    await aller(o, "#equipage/candidatures/questionnaire");
    const clic = await evaluer(o, `(() => { const f = [...document.querySelectorAll(".feuillet")].find((x) => x.textContent.includes("Parcours complet"));
      const b = f && [...f.querySelectorAll("button")].find((x) => x.textContent.trim() === "Par défaut"); if (!b) return false; b.click(); return true; })()`);
    if (!clic) return { ok: false, detail: "bouton « Par défaut » introuvable" };
    const d = await attendre(async () => ((await banque()).modeles || []).find((x) => x.nom === "Parcours complet" && x.par_defaut));
    return { ok: !!d, detail: d ? d.questions.length + " questions, par défaut" : "« par défaut » non reçu" };
  });
}

// ═══ LA CAPITAINERIE : affiches et catalogue ═══════════════════════════════
async function parcoursCapitainerie(o) {
  const affiches = () => api(o, "rell/affiches");
  const catalogue = () => api(o, "rell/catalogue");
  const cat0 = await catalogue();
  const lien = ((await api(o, "rell/roles")).liens || []).find((l) => l.type === "metier" && l.auto && l.existe && l.attribuable);
  const metier = (cat0.elements || []).find((e) => e.type === "metier" && e.actif !== false && (!lien || e.cle === lien.cle));
  /** Les rôles Discord du membre, lus sur sa fiche (la vraie source : le serveur Discord). */
  const rolesDe = async (id) => {
    const f = await evaluer(o, `fetch(${JSON.stringify(SITE + "membre?id=" + encodeURIComponent(String(id)))}, { credentials: "same-origin", headers: { "X-Tableau": "1" } }).then((r) => r.json())`);
    return (((f && f.membre) || {}).roles || []).map((x) => x.nom);
  };
  const race = (cat0.elements || []).find((e) => e.type === "race" && e.actif !== false);
  let choisi = null;
  const laMienne = async () => { const x = await affiches(); return [...(x.affiches || []), ...(x.corbeille || [])].find((a) => choisi && a.membre && a.membre.id === choisi); };

  await etape(o, "Affiche : en créer une (membre, prime, métier, race)", async () => {
    await aller(o, "#capitainerie/affiches");
    if (!await cliquer(o, "button", "Nouvelle affiche")) return { ok: false, detail: "bouton « Nouvelle affiche » absent" };
    if (!await attendre(() => cliquer(o, "button", "Choisir le membre"), 6000)) return { ok: false, detail: "« Choisir le membre » absent" };
    await pause(500);
    const pris = await evaluer(o, `(async () => { const d = [...document.querySelectorAll("dialog[open]")].pop();
      const deja = new Set(((await fetch(${JSON.stringify(SITE + "api/rell/affiches")}, { headers: { "X-Tableau": "1" } }).then((r) => r.json())).affiches || []).map((a) => a.membre && a.membre.nom));
      const b = [...d.querySelectorAll("button.choix-membre")].find((x) => !deja.has(x.querySelector(".nom").textContent.trim()));
      if (!b) return null; const nom = b.querySelector(".nom").textContent.trim(); b.click(); return nom; })()`);
    if (!pris) return { ok: false, detail: "aucun membre sans affiche à choisir" };
    await pause(500);
    const id = await evaluer(o, `(() => { const s = [...document.querySelectorAll("dialog[open] .membre-choisi .ident")].pop(); return s ? s.textContent.trim() : null; })()`);
    if (!id) return { ok: false, detail: "le membre choisi n'apparaît pas dans l'éditeur" };
    choisi = id;
    const prime = await evaluer(o, `(() => { const d = [...document.querySelectorAll("dialog[open]")].pop(); const i = d.querySelector('input[type=number][step="1000"]');
      if (!i) return false; i.value = "2500000"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
    if (!prime) return { ok: false, detail: "champ de la prime introuvable" };
    if (!await cliquer(o, "label.choix-insigne", metier.nom)) return { ok: false, detail: "insigne « " + metier.nom + " » introuvable" };
    if (!await cliquer(o, "label.choix-insigne", race.nom)) return { ok: false, detail: "insigne « " + race.nom + " » introuvable" };
    if (!await cliquer(o, "button", "Enregistrer l'affiche")) return { ok: false, detail: "bouton « Enregistrer l'affiche » absent" };
    const a = await attendre(laMienne, 15000);
    if (!a) return { ok: false, detail: "le serveur n'a pas l'affiche de " + pris };
    const ok = a.prime === 2500000 && (a.attributs.metier || []).includes(metier.cle) && (a.attributs.race || []).includes(race.cle) && a.version === 1;
    if (!ok) return { ok, detail: pris + " · " + JSON.stringify({ prime: a.prime, attributs: a.attributs, version: a.version }) };
    if (!lien) return { ok: true, detail: pris + " · aucun rôle de métier lié dans ce catalogue" };
    const roles = await attendre(async () => { const x = await rolesDe(choisi); return x.includes(lien.role_nom) ? x : null; }, 10000);
    return { ok: !!roles, detail: pris + (roles ? " · rôle « " + lien.role_nom + " » donné tout seul (métier en automatique)" : " · le rôle « " + lien.role_nom + " » n'a pas été donné : " + JSON.stringify(await rolesDe(choisi))) };
  });

  await etape(o, "Affiche : la modifier (prime, métier retiré → rôle retiré)", async () => {
    await aller(o, "#capitainerie/affiches");
    const a0 = await laMienne();
    if (!a0) return { ok: false, detail: "pas d'affiche créée" };
    const ouvert = await evaluer(o, `(() => { for (const g of document.querySelectorAll("details.groupe")) g.open = true; return true; })()`);
    await pause(600);
    const clic = await evaluer(o, `(() => { const b = [...document.querySelectorAll("button.affiche")].find((x) => x.textContent.toUpperCase().includes(${JSON.stringify((a0.membre.nom || "").toUpperCase())}));
      if (!b) return false; b.click(); return true; })()`);
    if (!ouvert || !clic) return { ok: false, detail: "affiche introuvable sur le mur" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Modifier"), 6000)) return { ok: false, detail: "bouton « Modifier » absent" };
    await pause(600);
    const prime = await evaluer(o, `(() => { const d = [...document.querySelectorAll("dialog[open]")].pop(); const i = d.querySelector('input[type=number][step="1000"]');
      if (!i) return false; i.value = "3000000"; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
    if (!prime) return { ok: false, detail: "champ de la prime introuvable" };
    if (!await cliquer(o, "label.choix-insigne", metier.nom)) return { ok: false, detail: "insigne « " + metier.nom + " » introuvable" };
    if (!await cliquer(o, "button", "Enregistrer l'affiche")) return { ok: false, detail: "bouton absent" };
    const a = await attendre(async () => { const x = await laMienne(); return x && x.prime === 3000000 ? x : null; });
    if (!a || a.version !== 2 || (a.attributs.metier || []).includes(metier.cle)) return { ok: false, detail: a ? JSON.stringify({ version: a.version, attributs: a.attributs }) : "modification non reçue" };
    if (!lien) return { ok: true, detail: "version 2" };
    const roles = await attendre(async () => { const x = await rolesDe(choisi); return x.includes(lien.role_nom) ? null : x; }, 10000);
    return { ok: !!roles, detail: roles ? "version 2 · rôle « " + lien.role_nom + " » retiré avec le métier" : "le rôle est resté : " + JSON.stringify(await rolesDe(choisi)) };
  });

  await etape(o, "Affiche : l'historique lisible", async () => {
    const a = await laMienne();
    const r = await api(o, "rell/affiche?id=" + encodeURIComponent(a.id));
    const h = r.historique || [];
    if (!(h.length >= 2 && h.some((x) => /Prime/.test(x.quoi || "")))) return { ok: false, detail: "API : " + h.map((x) => x.quoi).join(" | ").slice(0, 200) };
    // La page : l'historique déplié, en clair (les noms du catalogue, jamais la fiche brute).
    await aller(o, "#capitainerie/affiches");
    await evaluer(o, `(() => { for (const g of document.querySelectorAll("details.groupe")) g.open = true; return true; })()`);
    await pause(600);
    await evaluer(o, `(() => { const b = [...document.querySelectorAll("button.affiche")].find((x) => x.textContent.toUpperCase().includes(${JSON.stringify((a.membre.nom || "").toUpperCase())})); if (b) b.click(); return !!b; })()`);
    await pause(800);
    const t = await attendre(async () => {
      await evaluer(o, `(() => { const g = [...document.querySelectorAll("dialog[open] details.groupe")].find((x) => x.textContent.includes("Historique")); if (g && !g.open) g.open = true; return true; })()`);
      const x = await evaluer(o, `(() => { const g = [...document.querySelectorAll("dialog[open] details.groupe")].find((y) => y.textContent.includes("Historique")); return g ? g.innerText : ""; })()`);
      return x && x.includes("Fiche du jeu") ? x : null;
    }, 8000);
    if (!t) return { ok: false, detail: "historique non affiché dans la page" };
    const brut = /[{}[\]]/.test(t);
    return { ok: !brut && /retiré|ajouté/.test(t) && /berrys/.test(t), detail: t.replace(/\s+/g, " ").slice(0, 220) };
  });

  await etape(o, "Affiche : appliquer les rôles de ses métiers", async () => {
    await aller(o, "#capitainerie/affiches");
    const a = await laMienne();
    await evaluer(o, `(() => { for (const g of document.querySelectorAll("details.groupe")) g.open = true; return true; })()`);
    await pause(600);
    const clic = await evaluer(o, `(() => { const b = [...document.querySelectorAll("button.affiche")].find((x) => x.textContent.toUpperCase().includes(${JSON.stringify((a.membre.nom || "").toUpperCase())}));
      if (!b) return false; b.click(); return true; })()`);
    if (!clic) return { ok: false, detail: "affiche introuvable" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Appliquer les rôles"), 6000)) return { ok: false, detail: "bouton absent" };
    await evaluer(o, "(() => { for (const t of document.querySelectorAll('#toasts .toast')) t.remove(); return true; })()");
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Appliquer"), 6000)) return { ok: false, detail: "confirmation absente" };
    const t = await attendre(async () => { const x = await evaluer(o, "[...document.querySelectorAll('#toasts .toast')].map((e) => e.textContent).join(' | ')"); return /rôle|Rien à changer|Introuvable|impossible/i.test(x || "") ? x : null; }, 8000);
    if (!t || !/rôle|Rien à changer/.test(t) || /erreur|impossible/i.test(t)) return { ok: false, detail: (t || "aucun message").slice(0, 200) };
    const roles = await rolesDe(choisi);
    return { ok: !lien || !roles.includes(lien.role_nom), detail: t.slice(0, 120) + " · rôles : " + roles.join(", ") };
  });

  await etape(o, "Affiche : corbeille puis restauration", async () => {
    await aller(o, "#capitainerie/affiches");
    const a = await laMienne();
    await evaluer(o, `(() => { for (const g of document.querySelectorAll("details.groupe")) g.open = true; return true; })()`);
    await pause(600);
    await evaluer(o, `(() => { const b = [...document.querySelectorAll("button.affiche")].find((x) => x.textContent.toUpperCase().includes(${JSON.stringify((a.membre.nom || "").toUpperCase())})); if (b) b.click(); return !!b; })()`);
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Mettre à la corbeille"), 6000)) return { ok: false, detail: "bouton « Mettre à la corbeille » absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "À la corbeille"), 6000)) return { ok: false, detail: "confirmation absente" };
    const r1 = await attendre(async () => { const x = await laMienne(); return x && x.retire_le ? x : null; });
    if (!r1) return { ok: false, detail: "corbeille non reçue" };
    await aller(o, "#capitainerie/affiches");
    if (!await cliquer(o, "button", "Corbeille")) return { ok: false, detail: "vue « Corbeille » absente" };
    await pause(800);
    if (!await cliquer(o, ".corbeille-item button", "Restaurer")) return { ok: false, detail: "bouton « Restaurer » absent" };
    const r2 = await attendre(async () => { const x = await laMienne(); return x && !x.retire_le ? x : null; });
    return { ok: !!r2, detail: r2 ? "restaurée" : "restauration non reçue" };
  });

  // Un nom neuf à chaque passage : rejoué sur le même site local, l'élément d'avant (retiré) ferait un conflit.
  const NOM = "Charpentier d'essai " + "abcdefghij".split("").map((_, i) => "abcdefghijklmnopqrstuvwxyz"[Math.floor(Math.random() * 26)]).slice(0, 5).join("");
  const lElement = async () => ((await catalogue()).elements || []).find((e) => e.nom === NOM);
  await etape(o, "Catalogue : ajouter, confirmer, retirer un élément", async () => {
    await aller(o, "#capitainerie/catalogue");
    if (!await cliquer(o, "button", "Ajouter un élément")) return { ok: false, detail: "bouton absent" };
    await pause(600);
    const nomOk = await evaluer(o, `(() => { const d = [...document.querySelectorAll("dialog[open]")].pop(); const l = [...d.querySelectorAll("label.champ-lib")].find((x) => x.textContent.startsWith("Nom (français)"));
      const i = l && document.getElementById(l.htmlFor); if (!i) return false; i.value = ${JSON.stringify(NOM)}; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
    if (!nomOk) return { ok: false, detail: "champ du nom introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "bouton « Enregistrer » absent" };
    const e = await attendre(lElement);
    if (!e) return { ok: false, detail: "le serveur n'a pas l'élément" };
    await aller(o, "#capitainerie/catalogue");
    await ecrire(o, "Chercher dans tout le catalogue…", NOM);
    await pause(700);
    if (!await cliquer(o, "button.element-carte", NOM)) return { ok: false, detail: "carte de l'élément introuvable" };
    await pause(600);
    if (!await cliquer(o, "dialog[open] label, dialog[open] .radio, dialog[open] button", "Confirmé")) return { ok: false, detail: "choix « Confirmé » introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "bouton absent (modification)" };
    const e2 = await attendre(async () => { const x = await lElement(); return x && x.statut === "confirme" ? x : null; });
    if (!e2) return { ok: false, detail: "« confirmé » non reçu" };
    await aller(o, "#capitainerie/catalogue");
    await ecrire(o, "Chercher dans tout le catalogue…", NOM);
    await pause(700);
    await cliquer(o, "button.element-carte", NOM);
    await pause(600);
    if (!await cliquer(o, "dialog[open] button", "Retirer du catalogue")) return { ok: false, detail: "bouton « Retirer du catalogue » absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Retirer"), 5000)) return { ok: false, detail: "confirmation absente" };
    const e3 = await attendre(async () => { const x = await lElement(); return x && x.actif === false ? x : null; });
    return { ok: !!e3, detail: e3 ? "clé « " + e3.cle + " », retiré" : "retrait non reçu" };
  });
}

// ═══ LES RÔLES DES MÉTIERS ═════════════════════════════════════════════════
async function parcoursMetiers(o) {
  const reglages = () => api(o, "rell/metiers/reglages");
  const r0 = await reglages();
  if (r0.erreur) { await etape(o, "Rôles des métiers : réglages lisibles", async () => ({ ok: false, detail: r0.erreur })); return; }

  await etape(o, "Rôles des métiers : couper puis remettre l'attribution automatique", async () => {
    const basculer = async () => {
      await aller(o, "#capitainerie/roles");
      const fait = await evaluer(o, `(() => { const l = [...document.querySelectorAll("label, .interrupteur")].find((x) => x.textContent.includes("Attribution automatique des rôles de métier"));
        const i = l && (l.querySelector("input") || (l.htmlFor && document.getElementById(l.htmlFor))); if (!i) return false; i.click(); return true; })()`);
      if (!fait) return false;
      await pause(300);
      return cliquer(o, "button", "Enregistrer les réglages");
    };
    if (!await basculer()) return { ok: false, detail: "interrupteur ou « Enregistrer les réglages » introuvable" };
    const coupe = await attendre(async () => { const x = await reglages(); return x.auto === !r0.auto ? x : null; });
    if (!coupe) return { ok: false, detail: "le serveur n'a pas reçu le changement" };
    if (!await basculer()) return { ok: false, detail: "second basculement impossible" };
    const remis = await attendre(async () => { const x = await reglages(); return x.auto === r0.auto ? x : null; });
    return { ok: !!remis, detail: remis ? "auto " + r0.auto + " → " + !r0.auto + " → " + r0.auto : "retour non reçu" };
  });

  await etape(o, "Rôles des métiers : un métier de plus par membre", async () => {
    const avant = (await reglages()).max_metiers;
    const vise = avant < 5 ? avant + 1 : avant - 1;
    await aller(o, "#capitainerie/roles");
    if (!await cliquer(o, "button", vise > avant ? "Un de plus" : "Un de moins")) return { ok: false, detail: "bouton du nombre absent" };
    if (!await cliquer(o, "button", "Enregistrer les réglages")) return { ok: false, detail: "bouton absent" };
    const x = await attendre(async () => { const y = await reglages(); return y.max_metiers === vise ? y : null; });
    return { ok: !!x, detail: x ? avant + " → " + vise : "non reçu" };
  });

  await etape(o, "Rôles des métiers : créer les rôles manquants", async () => {
    await aller(o, "#capitainerie/roles");
    if (!await cliquer(o, "button", "Créer les rôles manquants")) return { ok: false, detail: "bouton absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Créer les rôles manquants"), 5000)) return { ok: false, detail: "confirmation absente" };
    const x = await attendre(async () => { const y = await reglages(); const actifs = (y.metiers || []).filter((m) => m.actif); return actifs.length && actifs.every((m) => m.lie) ? y : null; }, 20000);
    return { ok: !!x, detail: x ? compte_(x.metiers.filter((m) => m.lie).length) + " métiers ont leur rôle" : "des métiers restent sans rôle : " + JSON.stringify(((await reglages()).metiers || []).filter((m) => m.actif && !m.lie).map((m) => m.nom)) };
  });

  await etape(o, "Rôles des métiers : vérifier maintenant", async () => {
    const avant = ((await reglages()).derniere_reconciliation || {}).quand || 0;
    await aller(o, "#capitainerie/roles");
    if (!await cliquer(o, "button", "Vérifier maintenant")) return { ok: false, detail: "bouton absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Vérifier maintenant"), 5000)) return { ok: false, detail: "confirmation absente" };
    const x = await attendre(async () => { const y = await reglages(); const q = (y.derniere_reconciliation || {}).quand || 0; return q > avant ? y : null; }, 20000);
    if (!x) return { ok: false, detail: "aucune vérification enregistrée" };
    await aller(o, "#capitainerie/roles");
    const vu = await evaluer(o, "document.querySelector('#contenu').innerText.includes('Dernière vérification')");
    return { ok: vu, detail: JSON.stringify(x.derniere_reconciliation) + (vu ? "" : " — la page ne montre pas la dernière vérification") };
  });
}
const compte_ = (n) => String(n);

// ─── Le tout ────────────────────────────────────────────────────────────────
async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  const nav = await lancerNavigateur();
  console.log("Navigateur : " + nav.exe + "\nCaptures : " + SORTIE);
  try {
    await connecter(nav.wsUrl);
    const o = await onglet();
    await o.s("Page.navigate", { url: BASE + "/tableau/demo" });
    await pause(2000);
    if (PARCOURS.includes("recrutement")) await parcoursRecrutement(o);
    if (PARCOURS.includes("capitainerie")) await parcoursCapitainerie(o);
    if (PARCOURS.includes("metiers")) await parcoursMetiers(o);
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
