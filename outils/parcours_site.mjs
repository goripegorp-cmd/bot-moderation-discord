// outils/parcours_site.mjs — les VRAIS parcours du site v2, joués dans la vraie page contre le vrai serveur local.
//
// Un Edge (ou Chrome) SANS FENÊTRE ouvre le site local (`python outils/site_local.py` : le même serveur que le bot,
// un faux Discord, une base neuve à chaque démarrage), clique comme une personne, puis RELIT l'état par l'API après
// chaque geste : un bouton qui « marche » à l'écran sans rien changer au serveur est un échec. Une capture par étape.
//
//   node outils/parcours_site.mjs [--url http://localhost:8790] [--sortie <dossier>] [--parcours recrutement,capitainerie,metiers,textes]
//                                 [--navigateur <exe>]
//   Parcours : recrutement, capitainerie, metiers, accueil (« Ce qui t'attend » : chaque ligne mène au bon endroit),
//              recherche (Ctrl+K : membre, ticket, affiche, catalogue, banque, rubrique), recrutement_zone (« Demande de
//              recrutement » de bout en bout : le vrai chemin du bot sur le site local seulement), recrutement_decidees
//              (les décidées par morceaux, « Voir plus » : sur la base --lourd).
//              navigation (27/10/2026 : les rubriques regroupées, les anciennes adresses, les vues sur place, les noms).
//              tickets_interdits (27/10/2026 : la fiche interdit les tickets du clan, refus au clic, serveur ouvert, levée).
//   « textes » (Textes & noms) lit aussi ce que le FAUX Discord du site local a reçu (`/tableau/demo/discord`) : il ne se
//   joue que sur le site local, jamais sur la maquette.
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
  return { s, targetId };
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
/** Déplier le groupe repliable dont le titre contient `titre` (rangement.js, 26/10 : les réglages rarement touchés sont repliés). */
const deplier = (o, titre) => evaluer(o, `(async () => { const d = [...document.querySelectorAll("details.groupe")].find((x) => x.querySelector("summary").textContent.includes(${JSON.stringify(titre)}));
  if (!d) return false; if (!d.open) { d.open = true; await new Promise((r) => setTimeout(r, 200)); } return true; })()`);

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
// 26/10/2026 : tout le recrutement est dans La Capitainerie, « Demande de recrutement » (recrutement_zone.js). Les
// lignes portent leur ticket (`data-ticket`) ; le dossier s'ouvre au clic, ses décisions sont en bas de la fenêtre.
const ZONE_RECRUTEMENT = "#capitainerie/recrutement";
async function ouvrirCandidature(o, ticket, attendu) {
  await fermerTout(o);
  //  La liste relue : on passe par une autre page (la même adresse ne redessinerait rien).
  if ((await evaluer(o, "location.hash")).startsWith(ZONE_RECRUTEMENT)) await aller(o, "#accueil/attente");
  await aller(o, ZONE_RECRUTEMENT);
  await evaluer(o, "(async () => { for (const d of document.querySelectorAll('#contenu .zr-scene details.groupe')) d.open = true; await new Promise((r) => setTimeout(r, 500)); return 1; })()");
  const clic = await evaluer(o, `(() => { const li = document.querySelector('#contenu li.lc[data-ticket="${Number(ticket)}"]');
    const b = li && li.querySelector(".lc-ouvrir"); if (!b) return false; b.scrollIntoView({ block: "center" }); b.click(); return true; })()`);
  if (!clic) return false;
  return attendre(async () => { const t = await texteZone(o); return t.includes("Dossier de") && t.includes(attendu) ? t : null; }, 10000);
}
/** Le nombre affiché dans le titre d'un groupe de la zone (0 : le groupe n'est pas là). */
const compteGroupe = (o, titre) => evaluer(o, `(() => { const d = [...document.querySelectorAll("#contenu details.groupe")].find((x) => x.querySelector(".groupe-titre").textContent.trim() === ${JSON.stringify(titre)});
  if (!d) return 0; const c = d.querySelector("summary .compteur"); return c ? Number(c.textContent) : 0; })()`);

async function parcoursRecrutement(o) {
  const dossier = (t) => api(o, "recrutement/dossier?ticket=" + t);
  const suivi = await api(o, "recrutement/suivi");
  const ouverts = (suivi.ouverts || []).filter((x) => !x.fermeture_prevue);
  const parEtape = (e) => ouverts.filter((x) => x.etape === e).map((x) => x.ticket);
  const [t1, t1bis] = parEtape("etape1");
  const [tAttente] = parEtape("etape2");
  const [tCorr, tCorr2] = parEtape("reponses");

  await etape(o, "Liste : les étapes du serveur, rangées par prochaine action", async () => {
    await aller(o, ZONE_RECRUTEMENT);
    const n = (a) => ouverts.filter((x) => a.includes(x.action)).length;
    const page = [await compteGroupe(o, "À analyser"), await compteGroupe(o, "À corriger"), await compteGroupe(o, "En cours")];
    const serveur = [n(["analyser", "etape_suivante"]), n(["corriger"]), n(["attendre"])];
    return { ok: JSON.stringify(page) === JSON.stringify(serveur), detail: `page : ${page.join("/")} · serveur : ${serveur.join("/")}` };
  });

  await etape(o, "Demande approuvée : le questionnaire prévu part", async () => {
    if (!await ouvrirCandidature(o, t1, "Sa demande")) return { ok: false, detail: "dossier de la demande introuvable (ticket " + t1 + ")" };
    if (!await cliquer(o, "dialog[open] button", "Approuver la demande")) return { ok: false, detail: "bouton « Approuver la demande » absent" };
    const d = await attendre(async () => { const x = await dossier(t1); return x.etape === "etape2" && x.envois.length === 1 ? x : null; });
    if (!d) return { ok: false, detail: "le serveur n'a pas l'envoi : " + JSON.stringify(await dossier(t1)).slice(0, 200) };
    const vu = await attendre(async () => (await texteZone(o)).includes("Son questionnaire"), 6000);
    return { ok: !!vu, detail: d.envois[0].nb + " questions envoyées" + (vu ? "" : " — la page ne l'affiche pas") };
  });

  await etape(o, "En attente : questions listées, aucune correction possible", async () => {
    if (!await ouvrirCandidature(o, tAttente, "Son questionnaire")) return { ok: false, detail: "dossier en attente introuvable" };
    const t = await texteZone(o);
    const corrigeable = await evaluer(o, `${ZONE}.querySelectorAll(".correction-reponse").length`);
    return { ok: t.includes("En attente des réponses du candidat") && !corrigeable, detail: corrigeable ? corrigeable + " cartes de correction" : "" };
  });

  await etape(o, "Correction : tout juste, puis accepter", async () => {
    if (!await ouvrirCandidature(o, tCorr, "Son questionnaire")) return { ok: false, detail: "dossier à corriger introuvable" };
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
    if (!await ouvrirCandidature(o, tCorr2, "Son questionnaire")) return { ok: false, detail: "second dossier à corriger introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Refuser")) return { ok: false, detail: "bouton « Refuser » absent" };
    const t = await attendre(async () => { const x = await texteZone(o); return x.includes("La direction a étudié ta candidature") ? x : null; }, 6000);
    if (!t) return { ok: false, detail: "la confirmation ne montre pas le message exact du serveur" };
    if (t.includes("-#")) return { ok: false, detail: "le message montre la syntaxe Discord « -# »" };
    if (!await cliquer(o, "dialog[open] button", "Refuser et fermer le ticket")) return { ok: false, detail: "confirmation absente" };
    const prevu = await attendre(async () => { const x = await dossier(tCorr2); return x.fermeture_prevue || x.etape === "refuse" ? x : null; }, 10000);
    if (!prevu) return { ok: false, detail: "le serveur n'a pas prévu la fermeture" };
    const ferme = await attendre(async () => { const x = await dossier(tCorr2); return x.statut_ticket === "ferme" && x.etape === "refuse" ? x : null; }, 45000, 1000);
    return { ok: !!ferme, detail: ferme ? "refusé, ticket fermé" : "état : " + JSON.stringify(await dossier(tCorr2)).slice(0, 200) };
  });

  await etape(o, "Refuser la demande : message exact, fermeture prévue", async () => {
    if (!await ouvrirCandidature(o, t1bis, "Sa demande")) return { ok: false, detail: "seconde demande introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Refuser la demande")) return { ok: false, detail: "bouton absent" };
    const t = await attendre(async () => { const x = await texteZone(o); return x.includes("ne correspondent pas à ce que nous attendons") ? x : null; }, 6000);
    if (!t) return { ok: false, detail: "la confirmation ne montre pas le message du serveur" };
    if (!await cliquer(o, "dialog[open] button", "Refuser et fermer le ticket")) return { ok: false, detail: "confirmation absente" };
    const d = await attendre(async () => { const x = await dossier(t1bis); return x.etape === "refus_etape1" ? x : null; }, 10000);
    return { ok: !!d, detail: d ? "demande refusée" + (d.fermeture_prevue ? ", fermeture prévue" : ", ticket fermé") : "état : " + JSON.stringify(await dossier(t1bis)).slice(0, 200) };
  });

  // ─── La banque de questions ───
  const QUESTION = "Combien de joueurs au plus un équipage du parcours compte-t-il ?";
  const banque = () => api(o, "recrutement/banque");
  const laQuestion = async () => ((await banque()).questions || []).find((q) => q.question === QUESTION);
  const QUESTIONS = ZONE_RECRUTEMENT + "/questions";

  await etape(o, "Banque : ajouter une question", async () => {
    await fermerTout(o);
    await aller(o, QUESTIONS);
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
    await aller(o, QUESTIONS);
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
    await aller(o, QUESTIONS);
    await ecrire(o, "Question, réponse, source…", QUESTION);
    await pause(700);
    const clic = await evaluer(o, `(() => { const l = [...document.querySelectorAll(".banque-ligne")].find((x) => x.textContent.includes(${JSON.stringify(QUESTION)}));
      const b = l && [...l.querySelectorAll("button")].find((x) => x.textContent.includes("Retirer")); if (!b) return false; b.click(); return true; })()`);
    if (!clic) return { ok: false, detail: "bouton « Retirer » introuvable" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Retirer"), 5000)) return { ok: false, detail: "confirmation absente" };
    const q = await attendre(async () => { const x = await laQuestion(); return x && x.retiree ? x : null; });
    if (!q) return { ok: false, detail: "retrait non reçu" };
    await aller(o, QUESTIONS);
    await ecrire(o, "Question, réponse, source…", QUESTION);
    await pause(700);
    const encore = await evaluer(o, `[...document.querySelectorAll(".banque-ligne")].some((x) => x.textContent.includes(${JSON.stringify(QUESTION)}))`);
    return { ok: !encore, detail: encore ? "la question retirée est encore affichée" : "" };
  });

  await etape(o, "Liens : en ajouter un", async () => {
    await aller(o, QUESTIONS);
    const avant = (await banque()).liens.length;
    await deplier(o, "Les liens donnés au candidat");
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
    await aller(o, QUESTIONS);
    const avant = (await banque()).reglages.nombre;
    await deplier(o, "Les réglages");
    if (!await cliquer(o, "button", "Une de plus")) return { ok: false, detail: "bouton « Une de plus » absent" };
    if (!await cliquer(o, "button", "Enregistrer les réglages")) return { ok: false, detail: "bouton absent" };
    const b = await attendre(async () => { const x = await banque(); return x.reglages.nombre === avant + 1 ? x : null; });
    return { ok: !!b, detail: b ? avant + " → " + b.reglages.nombre : "réglages non reçus" };
  });

  await etape(o, "Modèles : enregistrer la sélection précédente, la mettre par défaut", async () => {
    await aller(o, QUESTIONS);
    await deplier(o, "Les modèles");
    if (!await cliquer(o, "button", "Nouveau modèle")) return { ok: false, detail: "bouton « Nouveau modèle » absent" };
    if (!await attendre(() => cliquer(o, "button.depart", "Reprendre la sélection précédente"), 6000)) return { ok: false, detail: "départ absent" };
    if (!await cliquer(o, "button", "Enregistrer le modèle")) return { ok: false, detail: "bouton « Enregistrer le modèle » absent" };
    if (!await attendre(() => ecrire(o, "Spécial Movie 3", "Parcours complet"), 5000)) return { ok: false, detail: "nom du modèle introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "confirmation absente" };
    const m = await attendre(async () => ((await banque()).modeles || []).find((x) => x.nom === "Parcours complet"));
    if (!m) return { ok: false, detail: "le serveur n'a pas le modèle" };
    await fermerTout(o);
    await aller(o, QUESTIONS);
    await deplier(o, "Les modèles");
    const clic = await evaluer(o, `(() => { const f = [...document.querySelectorAll(".feuillet")].find((x) => x.textContent.includes("Parcours complet"));
      const b = f && [...f.querySelectorAll("button")].find((x) => x.textContent.trim() === "Par défaut"); if (!b) return false; b.click(); return true; })()`);
    if (!clic) return { ok: false, detail: "bouton « Par défaut » introuvable" };
    const d = await attendre(async () => ((await banque()).modeles || []).find((x) => x.nom === "Parcours complet" && x.par_defaut));
    return { ok: !!d, detail: d ? d.questions.length + " questions, par défaut" : "« par défaut » non reçu" };
  });
}

// ═══ LA ZONE « DEMANDE DE RECRUTEMENT » DE BOUT EN BOUT (26/10/2026) ═════════
// Le VRAI chemin du bot (le site local : `/tableau/demo/recrutement/…` joue le panneau, « Oui », la fiche, les réponses
// du candidat), le FAUX Discord relu (`/tableau/demo/discord`) : la preuve est ce que le candidat voit dans son ticket
// et en message privé, jamais seulement l'écran du site.
async function parcoursRecrutementZone(o) {
  const N = Date.now().toString(36).slice(-4);
  const demo = (chemin) => evaluer(o, `fetch(${JSON.stringify(BASE + "/tableau/demo/")} + ${JSON.stringify(chemin)}, { cache: "no-store", credentials: "same-origin" }).then((r) => r.json())`);
  const ecrireApi = (chemin, corps) => evaluer(o, `fetch(${JSON.stringify(SITE + "api/")} + ${JSON.stringify(chemin)}, { method: "POST", credentials: "same-origin",
    headers: { "X-Tableau": "1", "Content-Type": "application/json" }, body: ${JSON.stringify(JSON.stringify(corps))} }).then(async (r) => ({ status: r.status, corps: await r.json() }))`);
  const dossier = (t) => api(o, "recrutement/dossier?ticket=" + t);
  const parcoursP1 = async () => ((await api(o, "recrutement/parcours")).panneaux || []).find((p) => p.panneau === "p1");
  const visibles = async (t) => ((await demo("discord?ticket=" + t)).messages || []);
  const d0 = await donneesSite(o);
  //  Des candidats hors du clan, pas encore en ticket : trois personnes du serveur.
  const clan = new Set(((await api(o, "recrutement/chefs")).membres || []).map((m) => String(m.id)));
  //  Ni un candidat en cours, ni quelqu'un sur la liste noire (un parcours d'avant a pu refuser sa demande).
  const pris = new Set([...(d0.en_cours || []).map((c) => String(c.id)),
    ...((await api(o, "recrutement/liste_noire")).actifs || []).map((x) => String(x.membre.id))]);
  const libres = Object.values(d0.personnes || {}).filter((p) => p && /^\d+$/.test(String(p.id)) && !pris.has(String(p.id)) && !clan.has(String(p.id))
    && !(d0.a_part || []).includes(String(p.id)));
  const [cand, elimine, refuse] = libres.slice(-3);
  let tid = 0;

  await etape(o, "Zone : l'ancienne adresse mène à « Demande de recrutement », ses quatre sous-onglets", async () => {
    await aller(o, "#equipage/candidatures");
    const h = await evaluer(o, "location.hash");
    const planches = await evaluer(o, "[...document.querySelectorAll('.zr-planche .zr-planche-titre')].map((x) => x.textContent.trim())");
    const equipage = await evaluer(o, "(async () => { location.hash = '#equipage/membres'; await new Promise((r) => setTimeout(r, 800)); return [...document.querySelectorAll('#rubriques a')].map((a) => a.textContent.trim()); })()");
    const ok = h.startsWith("#capitainerie/recrutement") && JSON.stringify(planches) === JSON.stringify(["Candidatures", "Chefs d'équipe", "Questions", "Réglages"])
      && !equipage.some((t) => t.includes("Candidatures"));
    return { ok, detail: h + " · " + planches.join(", ") + " · Équipage : " + equipage.join(", ") };
  });

  await etape(o, "Réglages : le parcours (approbation, la fiche avec un choix éliminatoire, deux étapes)", async () => {
    await aller(o, ZONE_RECRUTEMENT + "/reglages");
    const fait = await evaluer(o, `(async () => {
      const pause = (ms) => new Promise((r) => setTimeout(r, ms));
      const cadre = document.querySelector(".zr-parcours"); if (!cadre) return "cadre absent";
      for (const d of cadre.querySelectorAll("details.groupe")) d.open = true; await pause(400);
      [...cadre.querySelectorAll(".zr-mode")].find((b) => b.textContent.includes("Approbation")).click();
      // La fiche : on retire les champs du panneau, puis deux champs — la tranche d'âge (un choix, « Moins de 13 ans » éliminatoire), le pseudo.
      while (cadre.querySelector('[aria-label="Retirer ce champ"]')) { cadre.querySelector('[aria-label="Retirer ce champ"]').click(); await pause(150); }
      const ajouterChamp = async () => { [...cadre.querySelectorAll("button")].find((b) => b.textContent.includes("Ajouter un champ")).click(); await pause(250); };
      await ajouterChamp();
      let champs = cadre.querySelectorAll(".zr-champ");
      let c = champs[champs.length - 1];
      const titre = c.querySelector('input[aria-label^="Titre du champ"]'); titre.value = "Tranche d'âge"; titre.dispatchEvent(new Event("input", { bubbles: true }));
      c.querySelector('button.liste-bouton').click(); await pause(300);
      const opt = [...document.querySelectorAll(".menu-pop button.option")].find((b) => b.textContent.includes("Un choix dans une liste")); if (!opt) return "type « choix » absent"; opt.click(); await pause(300);
      champs = cadre.querySelectorAll(".zr-champ"); c = [...champs].find((x) => x.querySelector('input[aria-label="Nouveau choix"]'));
      for (const t of ["Moins de 13 ans", "13 à 15 ans", "16 à 17 ans", "18 ans ou plus"]) {
        const s = c.querySelector('input[aria-label="Nouveau choix"]'); s.value = t; s.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); await pause(200);
        c = [...cadre.querySelectorAll(".zr-champ")].find((x) => x.querySelector('input[aria-label="Nouveau choix"]'));
      }
      const elim = c.querySelector('input[aria-label="Éliminatoire : Moins de 13 ans"]'); if (!elim) return "case éliminatoire absente"; elim.click(); await pause(200);
      await ajouterChamp();
      champs = cadre.querySelectorAll(".zr-champ"); c = [...champs].filter((x) => x.querySelector('input[aria-label^="Titre du champ"]')).pop();
      const t2 = c.querySelector('input[aria-label^="Titre du champ"]'); t2.value = "Pseudo Roblox"; t2.dispatchEvent(new Event("input", { bubbles: true }));
      // Deux étapes : le jeu (un tirage de 3), le clan (un tirage de 2).
      while (cadre.querySelector('[aria-label="Retirer l\\'étape"]')) { cadre.querySelector('[aria-label="Retirer l\\'étape"]').click(); await pause(150); }
      for (const [n, nb] of [["Le jeu", "3"], ["Le clan", "2"]]) {
        [...cadre.querySelectorAll("button")].find((b) => b.textContent.includes("Ajouter une étape")).click(); await pause(250);
        const e = [...cadre.querySelectorAll(".zr-champ")].filter((x) => x.querySelector('input[aria-label^="Titre de l\\'étape"]')).pop();
        const ti = e.querySelector('input[aria-label^="Titre de l\\'étape"]'); ti.value = n; ti.dispatchEvent(new Event("input", { bubbles: true }));
        const nbr = e.querySelector('input[aria-label="Nombre de questions tirées"]'); nbr.value = nb; nbr.dispatchEvent(new Event("input", { bubbles: true }));
      }
      [...cadre.querySelectorAll("button")].find((b) => b.textContent.includes("Enregistrer le parcours")).click();
      return "ok"; })()`);
    if (fait !== "ok") return { ok: false, detail: fait };
    const p = await attendre(async () => { const x = await parcoursP1(); return x && x.version >= 1 && (x.gabarit || []).length === 2 && (x.fiche || []).length === 2 ? x : null; }, 15000);
    if (!p) return { ok: false, detail: "le serveur n'a pas le parcours : " + JSON.stringify(await parcoursP1()).slice(0, 300) };
    const age = p.fiche[0];
    const ok = p.mode === "approbation" && age.type === "choix" && JSON.stringify(age.eliminatoires) === JSON.stringify(["Moins de 13 ans"]) && p.gabarit[0].titre === "Le jeu" && p.gabarit[1].nombre === 2;
    return { ok, detail: "version " + p.version + " · fiche : " + p.fiche.map((c) => c.titre + (c.eliminatoires.length ? " (" + c.eliminatoires.join(", ") + " éliminatoire)" : "")).join(", ") + " · étapes : " + p.gabarit.map((e) => e.titre).join(", ") };
  });

  await etape(o, "Ticket : « Es-tu sûr ? », la fiche, puis l'affiche seule (le vrai chemin du bot)", async () => {
    if (!cand) return { ok: false, detail: "aucun candidat libre" };
    const r = await demo(`recrutement/ouvrir?membre=${cand.id}&choix=2&pseudo=Parcours_${N}`);
    if (!r.ok || !r.ticket) return { ok: false, detail: "pas de ticket : " + JSON.stringify(r).slice(0, 300) };
    tid = r.ticket;
    const m = await visibles(tid);
    const t = (m[0] || {}).texte || "";
    const ok = r.confirmation.includes("Es-tu sûr") && r.fiche.map((c) => c.titre).join(",") === "Tranche d'âge,Pseudo Roblox" && m.length === 1
      && t.includes("Parcours\\_" + N) && t.includes("16 à 17 ans") && !/Ticket (n°|#)/.test(t) && JSON.stringify(m[0].boutons) === JSON.stringify(["Direction"]);
    return { ok, detail: "ticket #" + tid + " · " + m.length + " message(s) · « " + t.slice(0, 110) + "… » · boutons " + JSON.stringify((m[0] || {}).boutons) };
  });

  await etape(o, "Élimination d'office : aucun ticket, un message privé, « Éliminé d'office » dans les décidées", async () => {
    if (!elimine) return { ok: false, detail: "aucun second candidat libre" };
    const r = await demo(`recrutement/ouvrir?membre=${elimine.id}&choix=0`);
    if (r.ticket) return { ok: false, detail: "un ticket a été ouvert : #" + r.ticket };
    const mp = ((await demo("discord?mp=" + elimine.id)).mp || []).map((x) => x.texte).join(" | ");
    await aller(o, ZONE_RECRUTEMENT);
    await evaluer(o, `(async () => { const d = [...document.querySelectorAll("#contenu details.groupe")].find((x) => x.querySelector(".groupe-titre").textContent.trim() === "Décidées"); if (d) d.open = true; await new Promise((r) => setTimeout(r, 900)); return 1; })()`);
    const vu = await attendre(async () => (await texteZone(o)).includes("Éliminé d'office · Tranche d'âge"), 8000);
    const noire = ((await api(o, "recrutement/liste_noire")).actifs || []).some((x) => x.membre.id === String(elimine.id));
    return { ok: r.elimine && mp.includes("n'est pas retenue") && !!vu && noire, detail: "lu : « " + (r.lu || "").slice(0, 80) + "… » · MP : « " + mp.slice(0, 60) + "… » · liste noire " + noire };
  });

  await etape(o, "Approbation : ses étapes, une question écrite pour lui — le ticket reçoit exactement cela", async () => {
    if (!await ouvrirCandidature(o, tid, "Sa demande")) return { ok: false, detail: "dossier du ticket #" + tid + " introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Choisir ses étapes")) return { ok: false, detail: "« Choisir ses étapes » absent" };
    if (!await attendre(async () => (await texteZone(o)).includes("Ses étapes, pour lui seul"), 8000)) return { ok: false, detail: "l'éditeur ne s'ouvre pas" };
    const etapes = await evaluer(o, `[...${ZONE}.querySelectorAll(".zr-etape-edit h4")].map((x) => x.textContent)`);
    if (!await cliquer(o, "dialog[open] button", "Écrire une question pour lui")) return { ok: false, detail: "« Écrire une question pour lui » absent" };
    await pause(500);
    const QUESTION = "Quel est le nom du navire amiral de l'équipage " + N + " ?";
    const ecrit = await evaluer(o, `(() => { const d = [...document.querySelectorAll("dialog[open]")].pop();
      const t = d.querySelector("textarea"); t.value = ${JSON.stringify(QUESTION)}; t.dispatchEvent(new Event("input", { bubbles: true }));
      const r = d.querySelector('input[placeholder="Charpentier"]'); r.value = "La Sirène"; r.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
    if (!ecrit || !await cliquer(o, "dialog[open] button", "Ajouter à l'étape")) return { ok: false, detail: "la question n'a pas pu être écrite" };
    await pause(400);
    if (!await cliquer(o, "dialog[open] button", "Approuver et ouvrir l'étape 2")) return { ok: false, detail: "bouton d'approbation absent" };
    const d = await attendre(async () => { const x = await dossier(tid); return x.etape === "etape2" && x.envois.length === 1 ? x : null; }, 15000);
    if (!d) return { ok: false, detail: "le serveur n'a pas l'envoi" };
    const e = d.envois[0];
    const perso = e.questions.find((q) => q.question === QUESTION);
    const m = await attendre(async () => { const x = await visibles(tid); return x.length === 2 ? x : null; }, 8000);
    const message = ((m || [])[1] || {}).texte || "";
    const affiche = ((m || [])[0] || {}).texte || "";
    const mp = ((await demo("discord?mp=" + cand.id)).mp || []).map((x) => x.texte).join(" | ");
    //  27/10/2026 : la page du candidat est branchée (comme `_activite_boot`) — « Répondre au questionnaire » donne son
    //  lien, ses questions sont sur SA page, jamais dans le ticket ; sans elle, le ticket les liste (les formulaires).
    const pageWeb = !!(await demo("recrutement/lien?ticket=" + tid)).url;
    const ok = !!perso && perso.id.startsWith("p-") && perso.etape === 1 && e.etapes.map((x) => x.titre).join(",") === "Le jeu,Le clan"
      && (pageWeb ? !message.includes(QUESTION) : message.includes(QUESTION)) && message.includes("Étape 2 sur 3") && !message.includes("La Sirène")
      && affiche.includes("Étape 2 sur 3 : à toi") && mp.includes("Ta demande de recrutement est acceptée");
    return { ok, detail: "éditeur : " + etapes.join(", ") + " · envoi : " + e.etapes.map((x) => x.titre + " (" + e.questions.filter((q) => q.etape === x.numero).length + ")").join(", ")
      + " · messages du ticket : " + (m || []).length + " · « " + message.slice(0, 80) + "… »" };
  });

  await etape(o, "Passage d'étape : il envoie l'étape 2, la direction ouvre l'étape 3 (l'ancien message s'efface)", async () => {
    const avant = (await visibles(tid)).map((x) => x.id);
    const r = await demo("recrutement/repondre?ticket=" + tid);
    if (!r.ok || r.etape_envoyee !== 1) return { ok: false, detail: "réponses du candidat : " + JSON.stringify(r).slice(0, 200) };
    const recue = ((await visibles(tid))[1] || {}).texte || "";
    if (!await ouvrirCandidature(o, tid, "Étape 2 reçue")) return { ok: false, detail: "le dossier ne dit pas « Étape 2 reçue »" };
    if (!await cliquer(o, "dialog[open] button", "Ouvrir l'étape 3")) return { ok: false, detail: "bouton « Ouvrir l'étape 3 » absent" };
    const d = await attendre(async () => { const x = await dossier(tid); return x.envois[0].etape_ouverte === 2 ? x : null; }, 10000);
    if (!d) return { ok: false, detail: "le serveur n'a pas ouvert l'étape suivante" };
    const apres = await visibles(tid);
    const ok = recue.includes("réponses reçues") && apres.length === 2 && !apres.some((x) => x.id === avant[1]) && apres[1].texte.includes("Étape 3 sur 3");
    return { ok, detail: "après l'étape 2 : « " + recue.slice(0, 60) + "… » · ticket : " + apres.length + " messages, « " + ((apres[1] || {}).texte || "").slice(0, 60) + "… »" };
  });

  await etape(o, "Voir comme le candidat : l'affiche, ses formulaires, jamais les réponses attendues", async () => {
    if (!await ouvrirCandidature(o, tid, "Son questionnaire")) return { ok: false, detail: "dossier introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Voir comme le candidat")) return { ok: false, detail: "bouton absent" };
    const t = await attendre(async () => { const x = await texteZone(o); return x.includes("Ses formulaires") ? x : null; }, 8000);
    const banniere = await evaluer(o, "!!([...document.querySelectorAll('dialog[open]')].pop().querySelector('.discord-media img'))");
    //  Ses réponses à lui y sont (il a répondu) ; jamais la réponse attendue ni ses variantes.
    return { ok: !!t && t.includes("L'affiche, dans son ticket") && !/Réponse attendue|Variantes admises/.test(t) && banniere,
      detail: t ? "bannière " + banniere + " · " + t.slice(0, 120).replace(/\s+/g, " ") : "aperçu absent" };
  });

  await etape(o, "Toutes ses réponses : à corriger, les identiques marquées, puis accepté (le rôle, le message, le MP)", async () => {
    const r = await demo("recrutement/repondre?ticket=" + tid);
    if (!r.ok || r.statut !== "repondu") return { ok: false, detail: "réponses : " + JSON.stringify(r).slice(0, 200) };
    if (!await ouvrirCandidature(o, tid, "Son questionnaire")) return { ok: false, detail: "dossier introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Marquer justes les")) return { ok: false, detail: "« Marquer justes » absent" };
    const corrige = await attendre(async () => { const x = await dossier(tid); const b = x.envois[0].bilan; return b.justes === b.total ? x : null; }, 20000);
    if (!corrige) return { ok: false, detail: "corrections : " + JSON.stringify((await dossier(tid)).envois[0].bilan) };
    const total = corrige.envois[0].questions.length;
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Accepter · " + total + "/" + total), 8000)) return { ok: false, detail: "« Accepter » absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Accepter"), 6000)) return { ok: false, detail: "confirmation absente" };
    const d = await attendre(async () => { const x = await dossier(tid); return x.etape === "accepte" ? x : null; }, 15000);
    const m = await visibles(tid);
    const mp = ((await demo("discord?mp=" + cand.id)).mp || []).map((x) => x.texte).join(" | ");
    const ok = !!d && m.some((x) => x.texte.includes("Bienvenue dans le clan")) && mp.includes("Tu es accepté dans le clan") && m.length <= 2;
    return { ok, detail: (d ? "accepté" : "pas accepté") + " · ticket : " + m.length + " message(s) visibles · MP : « " + mp.slice(-70) + " »" };
  });

  await etape(o, "Liste noire : une demande refusée, puis levée", async () => {
    if (!refuse) return { ok: false, detail: "aucun troisième candidat libre" };
    const r = await demo(`recrutement/ouvrir?membre=${refuse.id}&choix=3`);
    if (!r.ticket) return { ok: false, detail: "pas de ticket : " + JSON.stringify(r).slice(0, 200) };
    if (!await ouvrirCandidature(o, r.ticket, "Sa demande")) return { ok: false, detail: "dossier introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Refuser la demande")) return { ok: false, detail: "bouton absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Refuser et fermer le ticket"), 6000)) return { ok: false, detail: "confirmation absente" };
    const noire = await attendre(async () => ((await api(o, "recrutement/liste_noire")).actifs || []).find((x) => x.membre.id === String(refuse.id)), 10000);
    if (!noire) return { ok: false, detail: "pas sur la liste noire" };
    await aller(o, ZONE_RECRUTEMENT + "/reglages");
    await deplier(o, "La liste noire");
    await pause(800);
    const clic = await evaluer(o, `(() => { const l = [...document.querySelectorAll("#contenu li.lc")].find((x) => x.textContent.includes(${JSON.stringify(noire.membre.nom)}));
      const b = l && [...l.querySelectorAll("button")].find((x) => x.textContent.includes("Lever")); if (!b) return false; b.click(); return true; })()`);
    if (!clic) return { ok: false, detail: "« Lever » introuvable (" + noire.membre.nom + ")" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Lever"), 6000)) return { ok: false, detail: "confirmation absente" };
    const leve = await attendre(async () => !((await api(o, "recrutement/liste_noire")).actifs || []).some((x) => x.membre.id === String(refuse.id)), 10000);
    return { ok: !!leve, detail: noire.membre.nom + " · motif « " + noire.motif + " » · levée " + !!leve };
  });

  await etape(o, "Chefs d'équipe : une question de chef, puis proposer un membre du clan", async () => {
    await aller(o, ZONE_RECRUTEMENT + "/questions");
    await deplier(o, "La banque des chefs d'équipe");
    await pause(600);
    const ouvre = await attendre(() => evaluer(o, `(() => { const g = [...document.querySelectorAll("#contenu details.groupe")].find((x) => x.querySelector("summary").textContent.includes("La banque des chefs"));
      const b = g && [...g.querySelectorAll("button")].find((x) => x.textContent.includes("Ajouter une question")); if (!b) return false; b.scrollIntoView({ block: "center" }); b.click(); return true; })()`), 8000);
    if (!ouvre) return { ok: false, detail: "« Ajouter une question » (chefs) absent" };
    const QUESTION = "Combien de voiles porte un galion de guerre " + N + " ?";
    const ecrit = await attendre(() => evaluer(o, `(() => { const d = [...document.querySelectorAll("dialog[open]")].pop(); if (!d || !d.textContent.includes("question de chef")) return false;
      const t = d.querySelector("textarea"); t.value = ${JSON.stringify(QUESTION)}; t.dispatchEvent(new Event("input", { bubbles: true }));
      const r = d.querySelector('input[placeholder="Douze"]'); r.value = "Trois"; r.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`), 6000);
    if (!ecrit || !await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "la question de chef n'a pas pu être écrite" };
    const q = await attendre(async () => ((await api(o, "recrutement/chefs")).questions || []).find((x) => x.question === QUESTION), 10000);
    if (!q) return { ok: false, detail: "le serveur n'a pas la question de chef" };
    await aller(o, ZONE_RECRUTEMENT + "/chefs");
    await deplier(o, "Proposer d'être chef");
    await pause(600);
    const qui = await evaluer(o, `(() => { const l = [...document.querySelectorAll("#contenu li.lc")].find((x) => [...x.querySelectorAll("button")].some((b) => b.textContent.includes("Proposer d'être chef")));
      if (!l) return ""; const nom = l.querySelector(".lc-titre").textContent.trim(); [...l.querySelectorAll("button")].find((b) => b.textContent.includes("Proposer d'être chef")).click(); return nom; })()`);
    if (!qui) return { ok: false, detail: "aucun membre du clan à proposer" };
    if (!await attendre(async () => (await texteFenetre(o)).includes(QUESTION), 8000)) return { ok: false, detail: "la question de chef n'est pas proposée" };
    const coche = await evaluer(o, `(() => { const l = [...[...document.querySelectorAll("dialog[open]")].pop().querySelectorAll("label.case")].find((x) => x.textContent.includes(${JSON.stringify(QUESTION)}));
      const i = l && l.querySelector("input"); if (!i) return false; if (!i.checked) i.click(); return true; })()`);
    if (!coche || !await attendre(() => cliquer(o, "dialog[open] button", "Envoyer ·"), 6000)) return { ok: false, detail: "envoi impossible" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Envoyer"), 6000)) return { ok: false, detail: "confirmation absente" };
    const c = await attendre(async () => ((await api(o, "recrutement/chefs")).candidatures || []).find((x) => x.membre.nom === qui), 10000);
    return { ok: !!c && c.etat === "en_cours", detail: qui + (c ? " : candidature de chef « " + c.metier_nom + " » en cours" : " : pas de candidature") };
  });

  await etape(o, "Équipes : le chef validé est badgé et proposé en premier dans l'éditeur d'une équipe", async () => {
    //  Le dernier du clan par son nom, nommé chef par le vrai chemin (`/tableau/demo/recrutement/chef` : proposé, ses
    //  réponses, la correction à 100 %, « Accepter ») : son badge le fait passer devant tous les autres.
    const c0 = await api(o, "recrutement/chefs");
    const eq0 = await api(o, "equipage/equipes");
    const occupes = new Set([...(c0.candidatures || []).filter((x) => x.etat === "en_cours" || x.etat === "corriger").map((x) => String(x.membre.id)),
      ...(eq0.equipes || []).filter((e) => e.chef).map((e) => String(e.chef.id))]);
    const qui = (c0.membres || []).filter((m) => !m.chef && !occupes.has(String(m.id)))
      .sort((a, b) => b.nom.localeCompare(a.nom, "fr", { sensitivity: "base" }))[0];
    if (!qui) return { ok: false, detail: "aucun membre du clan à nommer" };
    const r = await demo("recrutement/chef?membre=" + qui.id);
    if (!r.ok) return { ok: false, detail: "nomination refusée : " + JSON.stringify(r).slice(0, 240) };
    const badge = ((await api(o, "equipage/equipes")).badges || {})[String(qui.id)] || "";
    if (!badge.startsWith("Chef validé · ")) return { ok: false, detail: "le serveur ne badge pas " + qui.nom + " (« " + badge + " »)" };
    await aller(o, "#equipage/membres/equipes");
    await o.s("Page.reload", {});   // les équipes relues (la page les garde 20 s)
    await attendre(() => evaluer(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 12000, 200);
    await pause(600);
    if (!await evaluer(o, "(document.querySelector('#contenu .sous-onglets [aria-selected=true]') || {}).textContent === 'Équipes'")) return { ok: false, detail: "la vue « Équipes » n'est pas ouverte" };
    if (!await attendre(() => cliquer(o, "#contenu button", "Nouvelle équipe"), 8000)) return { ok: false, detail: "« Nouvelle équipe » absent" };
    const premier = await attendre(() => evaluer(o, `(() => { const d = [...document.querySelectorAll("dialog[open]")].pop();
      const li = d && d.querySelector('ol.choix-equipe[role="radiogroup"] > li'); if (!li) return null;
      const r = li.querySelector('input[type="radio"]'); return { id: r ? r.value : "", texte: li.innerText.replace(/\\s+/g, " ").trim() }; })()`), 8000);
    const ok = !!premier && premier.id === String(qui.id) && premier.texte.includes(badge);
    return { ok, detail: qui.nom + " · « " + badge + " » · en tête du choix du chef : « " + (premier ? premier.texte : "rien") + " »" };
  });

  await etape(o, "Ses messages, dans l'ordre : « Modifier ce message » réécrit les conditions de l'affiche", async () => {
    await aller(o, ZONE_RECRUTEMENT + "/reglages");
    await deplier(o, "Ses messages, dans l'ordre");
    await pause(800);
    const clic = await evaluer(o, `(() => { const li = [...document.querySelectorAll(".zr-message")].find((x) => x.querySelector("b").textContent.trim() === "L'affiche");
      const b = li && [...li.querySelectorAll("button")].find((x) => x.textContent.includes("Modifier ce message")); if (!b) return false; b.click(); return true; })()`);
    if (!clic) return { ok: false, detail: "« Modifier ce message » absent sur l'affiche" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Les conditions"), 6000)) return { ok: false, detail: "le texte des conditions n'est pas proposé" };
    const CONDITIONS = "**Pour rejoindre le clan " + N + "**\n- Jouer à RELL Seas.";
    const ok1 = await attendre(() => evaluer(o, `(() => { const c = [...document.querySelectorAll("dialog[open] .texte-champ")].pop(); if (!c) return false;
      c.focus(); c.value = ${JSON.stringify(CONDITIONS)}; c.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`), 6000);
    if (!ok1 || !await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "éditeur ou enregistrement absent" };
    const p = await attendre(async () => { const x = await parcoursP1(); const m = (x.messages || []).find((y) => y.cle === "affiche"); return m && JSON.stringify(m.blocs).includes("Pour rejoindre le clan " + N) ? x : null; }, 10000);
    return { ok: !!p, detail: p ? "l'aperçu de l'affiche montre les nouvelles conditions" : "l'aperçu ne suit pas" };
  });

  await etape(o, "Purge exceptionnelle : l'aperçu, le mot à taper, puis plus rien à effacer", async () => {
    await aller(o, ZONE_RECRUTEMENT + "/reglages");
    await deplier(o, "La purge exceptionnelle");
    await pause(500);
    const avant = await api(o, "recrutement/purge");
    if (!await cliquer(o, "#contenu button", "Voir ce qui serait effacé")) return { ok: false, detail: "« Voir ce qui serait effacé » absent" };
    if (!await attendre(async () => (await texteFenetre(o)).includes("rien n'est effacé ici"), 8000)) return { ok: false, detail: "aperçu absent" };
    if (!avant.total_personnes) return { ok: true, detail: "personne n'est concerné : rien à purger" };
    if (!await cliquer(o, "dialog[open] button", "Purger…")) return { ok: false, detail: "« Purger… » absent" };
    const bloque = await attendre(() => evaluer(o, `(() => { const b = [...[...document.querySelectorAll("dialog[open]")].pop().querySelectorAll("button")].find((x) => x.textContent.trim() === "Purger"); return b ? b.disabled : null; })()`), 6000);
    if (bloque !== true) return { ok: false, detail: "« Purger » n'attend pas le mot tapé" };
    await evaluer(o, `(() => { const i = [...document.querySelectorAll("dialog[open]")].pop().querySelector('input[name="confirmation"]'); i.value = ${JSON.stringify(avant.confirmation)}; i.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
    if (!await cliquer(o, "dialog[open] button", "Purger")) return { ok: false, detail: "« Purger » absent" };
    const apres = await attendre(async () => { const x = await api(o, "recrutement/purge"); return x.total_personnes === 0 ? x : null; }, 15000);
    return { ok: !!apres, detail: avant.total_personnes + " personne(s), " + avant.total_candidatures + " candidature(s) → " + (apres ? "0" : "encore là") };
  });
}

// ═══ LES DÉCIDÉES PAR MORCEAUX (27/10/2026) ═══════════════════════════════════
// L'historique des décisions se lit par morceaux, comme le journal : le premier morceau (25), puis « Voir plus ». À jouer
// sur une base qui a plus de 25 décisions (`site_local.py --lourd`) : sur la base légère, le parcours le dit et échoue.
async function parcoursDecidees(o) {
  const lignesD = () => evaluer(o, `(() => { const d = [...document.querySelectorAll("#contenu details.groupe")].find((x) => x.querySelector(".groupe-titre").textContent.trim() === "Décidées");
    return d ? [...d.querySelectorAll("li.lc")].map((li) => li.dataset.decision || "") : null; })()`);
  await etape(o, "Décidées : le premier morceau, puis « Voir plus » ajoute le suivant, sans doublon, du plus récent", async () => {
    const d0 = await api(o, "recrutement/decidees");
    if (!d0.suite) return { ok: false, detail: (d0.total || 0) + " décision(s) : un seul morceau — jouer sur la base --lourd" };
    await aller(o, ZONE_RECRUTEMENT);
    await evaluer(o, `(async () => { const d = [...document.querySelectorAll("#contenu details.groupe")].find((x) => x.querySelector(".groupe-titre").textContent.trim() === "Décidées"); if (d) d.open = true; await new Promise((r) => setTimeout(r, 600)); return 1; })()`);
    const avant = await attendre(async () => { const l = await lignesD(); return l && l.length ? l : null; }, 8000);
    if (!avant || avant.length !== d0.lignes.length) return { ok: false, detail: "premier morceau : " + (avant ? avant.length : 0) + " ligne(s) à l'écran, " + d0.lignes.length + " servies" };
    if (!await cliquer(o, "#contenu button", "décisions de plus")) return { ok: false, detail: "« Voir plus » absent" };
    const attendu = Math.min(d0.total, avant.length + (d0.n || 25));
    const apres = await attendre(async () => { const l = await lignesD(); return l && l.length === attendu ? l : null; }, 8000);
    if (!apres) return { ok: false, detail: "après « Voir plus » : " + ((await lignesD()) || []).length + " ligne(s), " + attendu + " attendues" };
    const d1 = await api(o, "recrutement/decidees?avant=" + encodeURIComponent(d0.suite));
    const serveur = [...d0.lignes, ...(d1.lignes || [])].map((x) => x.quand + ":" + x.ticket + ":" + x.membre.id);
    const quand = apres.map((k) => Number(k.split(":")[0]));
    const ok = new Set(apres).size === apres.length && JSON.stringify(apres) === JSON.stringify(serveur.slice(0, apres.length))
      && quand.every((q, i) => i === 0 || quand[i - 1] >= q);
    return { ok, detail: avant.length + " → " + apres.length + " ligne(s) sur " + d0.total + " · sans doublon " + (new Set(apres).size === apres.length)
      + " · comme le serveur " + (JSON.stringify(apres) === JSON.stringify(serveur.slice(0, apres.length))) };
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
      await deplier(o, "Les réglages");
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
    await deplier(o, "Les réglages");
    if (!await cliquer(o, "button", vise > avant ? "Un de plus" : "Un de moins")) return { ok: false, detail: "bouton du nombre absent" };
    if (!await cliquer(o, "button", "Enregistrer les réglages")) return { ok: false, detail: "bouton absent" };
    const x = await attendre(async () => { const y = await reglages(); return y.max_metiers === vise ? y : null; });
    return { ok: !!x, detail: x ? avant + " → " + vise : "non reçu" };
  });

  await etape(o, "Rôles des métiers : créer les rôles manquants", async () => {
    await aller(o, "#capitainerie/roles");
    await deplier(o, "Les réglages");
    if (!await cliquer(o, "button", "Créer les rôles manquants")) return { ok: false, detail: "bouton absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Créer les rôles manquants"), 5000)) return { ok: false, detail: "confirmation absente" };
    const x = await attendre(async () => { const y = await reglages(); const actifs = (y.metiers || []).filter((m) => m.actif); return actifs.length && actifs.every((m) => m.lie) ? y : null; }, 20000);
    return { ok: !!x, detail: x ? compte_(x.metiers.filter((m) => m.lie).length) + " métiers ont leur rôle" : "des métiers restent sans rôle : " + JSON.stringify(((await reglages()).metiers || []).filter((m) => m.actif && !m.lie).map((m) => m.nom)) };
  });

  await etape(o, "Rôles des métiers : vérifier maintenant", async () => {
    const avant = ((await reglages()).derniere_reconciliation || {}).quand || 0;
    await aller(o, "#capitainerie/roles");
    await deplier(o, "Les réglages");
    if (!await cliquer(o, "button", "Vérifier maintenant")) return { ok: false, detail: "bouton absent" };
    if (!await attendre(() => cliquer(o, "dialog[open] button", "Vérifier maintenant"), 5000)) return { ok: false, detail: "confirmation absente" };
    const x = await attendre(async () => { const y = await reglages(); const q = (y.derniere_reconciliation || {}).quand || 0; return q > avant ? y : null; }, 20000);
    if (!x) return { ok: false, detail: "aucune vérification enregistrée" };
    await aller(o, "#capitainerie/roles");
    await deplier(o, "Les réglages");
    const vu = await evaluer(o, "document.querySelector('#contenu').innerText.includes('Dernière vérification')");
    return { ok: vu, detail: JSON.stringify(x.derniere_reconciliation) + (vu ? "" : " — la page ne montre pas la dernière vérification") };
  });
}
const compte_ = (n) => String(n);

// ═══ L'ACCUEIL « CE QUI T'ATTEND » ══════════════════════════════════════════
// Chaque ligne « à faire » ouvre exactement le bon endroit (ou porte le bon lien) ; chaque raccourci aussi.
const donneesSite = (o) => evaluer(o, `fetch(${JSON.stringify(SITE + "donnees")}, { credentials: "same-origin" }).then((r) => r.json())`);
const lignesAFaire = (o) => evaluer(o, `[...document.querySelectorAll(".a-faire-liste .lc")].map((l) => ({ sorte: l.dataset.sorte, prio: Number(l.dataset.prio),
  titre: l.querySelector(".lc-titre").textContent, sous: l.querySelector(".lc-sous-texte").textContent,
  bouton: ((l.querySelector(".lc-actions .bouton") || {}).textContent || "").trim(), href: (l.querySelector(".lc-actions a") || {}).href || "" }))`);
/** Le bouton de la première ligne « à faire » d'une sorte (dont le titre contient `texte`). */
const boutonAFaire = (o, sorte, texte = "") => evaluer(o, `(() => { const l = [...document.querySelectorAll(".a-faire-liste .lc")].find((x) => x.dataset.sorte === ${JSON.stringify(sorte)}
  && x.querySelector(".lc-titre").textContent.includes(${JSON.stringify(texte)})); if (!l) return false; l.querySelector(".lc-actions .bouton").click(); return true; })()`);
async function allerAccueil(o) {
  await aller(o, "#accueil/attente");
  // Les jeux chargés à la demande (publications, banque, catalogue, rôles, affiches) : la liste se complète.
  await attendre(async () => { const a = await lignesAFaire(o); await pause(700); const b = await lignesAFaire(o); return a.length && a.length === b.length; }, 8000, 300);
}
const texteFenetre = (o) => evaluer(o, "(() => { const d = [...document.querySelectorAll('dialog[open]')].pop(); return d ? d.innerText : ''; })()");

async function parcoursAccueil(o) {
  await etape(o, "Accueil : la première page d'un nouvel onglet, une liste priorisée", async () => {
    const o2 = await onglet();
    await o2.s("Page.navigate", { url: SITE });
    await attendre(() => evaluer(o2, "!!document.querySelector('#contenu .titre-rubrique') && !!document.querySelector('.a-faire-liste, #contenu .vide')"), 12000, 200);
    await pause(1200);
    const vu = await evaluer(o2, "({ hash: location.hash, titre: document.querySelector('#contenu h1').textContent, n: document.querySelectorAll('.a-faire-liste .lc').length,"
      + " prios: [...document.querySelectorAll('.a-faire-liste .lc')].map((l) => Number(l.dataset.prio)), boutons: [...document.querySelectorAll('.a-faire-liste .lc')].every((l) => l.querySelectorAll('.lc-actions .bouton').length === 1),"
      + " pastille: (document.querySelector('.pancarte-nav[data-cat=accueil] .pancarte-pastille') || {}).textContent || '' })");
    try { await envoyer("Target.closeTarget", { targetId: o2.targetId }); } catch (e) { /* déjà fermé */ }
    const trie = vu.prios.every((p, i) => !i || vu.prios[i - 1] <= p);
    return { ok: vu.titre === "Ce qui t'attend" && vu.n > 0 && trie && vu.boutons && !!vu.pastille, detail: JSON.stringify(vu).slice(0, 240) };
  });

  // Les raccourcis par tâche (avant toute publication ouverte : le composeur part d'un brouillon neuf).
  await etape(o, "Raccourci « Annoncer un événement » : le composeur, sur un événement neuf", async () => {
    await aller(o, "#accueil/attente");
    if (!await cliquer(o, "button.tache", "Annoncer un événement")) return { ok: false, detail: "raccourci absent" };
    const ok = await attendre(() => evaluer(o, "location.hash.includes('annonces/composer') && /Événement/.test((document.querySelector('.choix-type.actif') || {}).textContent || '')"), 8000);
    return { ok: !!ok, detail: await evaluer(o, "location.hash + ' · ' + ((document.querySelector('.choix-type.actif') || {}).textContent || '')") };
  });
  await etape(o, "Raccourci « Faire une annonce » : le composeur, sur une annonce", async () => {
    await aller(o, "#accueil/attente");
    if (!await cliquer(o, "button.tache", "Faire une annonce")) return { ok: false, detail: "raccourci absent" };
    const ok = await attendre(() => evaluer(o, "location.hash.includes('annonces/composer') && /Annonce/.test((document.querySelector('.choix-type.actif') || {}).textContent || '')"), 8000);
    return { ok: !!ok, detail: await evaluer(o, "location.hash + ' · ' + ((document.querySelector('.choix-type.actif') || {}).textContent || '')") };
  });
  await etape(o, "Raccourci « Créer une affiche » : l'éditeur d'une nouvelle affiche", async () => {
    await aller(o, "#accueil/attente");
    if (!await cliquer(o, "button.tache", "Créer une affiche")) return { ok: false, detail: "raccourci absent" };
    const t = await attendre(async () => { const x = await texteFenetre(o); return x.includes("Nouvelle affiche") ? x : null; }, 8000);
    return { ok: !!t && (await evaluer(o, "location.hash")).includes("capitainerie/affiches"), detail: (t || "").slice(0, 80) };
  });
  await etape(o, "Raccourcis « Voir les candidatures » et « Chercher un membre »", async () => {
    await aller(o, "#accueil/attente");
    await cliquer(o, "button.tache", "Voir les candidatures");
    const cand = await attendre(() => evaluer(o, "location.hash.includes('capitainerie/recrutement')"), 6000);
    await aller(o, "#accueil/attente");
    await cliquer(o, "button.tache", "Chercher un membre");
    const rech = await attendre(() => evaluer(o, "!!document.querySelector('dialog[open] .recherche-champ') && document.activeElement === document.querySelector('dialog[open] .recherche-champ')"), 6000);
    return { ok: !!cand && !!rech, detail: "candidatures " + !!cand + " · recherche ouverte, le champ a le focus " + !!rech };
  });

  // Chaque ligne « à faire » présente : le bon endroit.
  const d = await donneesSite(o);
  await allerAccueil(o);
  const lignes = await lignesAFaire(o);
  await etape(o, "Accueil : les sortes présentes (" + [...new Set(lignes.map((l) => l.sorte))].join(", ") + ")", async () => ({ ok: lignes.length > 0, detail: lignes.length + " lignes" }));
  const ticketDe = (l) => Number((/ticket #(\d+)/i.exec(l.sous) || /#(\d+)/.exec(l.titre) || [])[1]);
  const essais = {
    decider: async (l) => {
      const t = ticketDe(l);
      if (!await boutonAFaire(o, "decider", l.titre)) return { ok: false, detail: "bouton absent" };
      const x = await attendre(async () => { const y = await texteFenetre(o); return y.includes("ticket #" + t) && y.includes("Dossier de") ? y : null; }, 10000);
      return { ok: !!x && (await evaluer(o, "location.hash")).includes("capitainerie/recrutement"), detail: "ticket #" + t + (x ? " : son dossier s'ouvre" : " : dossier absent") };
    },
    corriger: async (l) => {
      const t = ticketDe(l);
      if (!await boutonAFaire(o, "corriger", l.titre)) return { ok: false, detail: "bouton absent" };
      const x = await attendre(async () => { const y = await texteFenetre(o); return y.includes("ticket #" + t) && /Son questionnaire|correction/i.test(y) ? y : null; }, 10000);
      return { ok: !!x, detail: "ticket #" + t + (x ? " : la correction s'ouvre" : " : correction absente") };
    },
    alerte: async (l) => {
      const nom = l.titre.replace(/^Alerte : /, "").replace(/ cumule du grave$/, "");
      if (!await boutonAFaire(o, "alerte", l.titre)) return { ok: false, detail: "bouton absent" };
      const x = await attendre(async () => { const y = await evaluer(o, "(() => { const d = [...document.querySelectorAll('dialog[open]')].pop(); return d ? d.querySelector('h2').textContent : ''; })()"); return y.includes(nom) ? y : null; }, 10000);
      return { ok: !!x, detail: nom + (x ? " : sa fiche s'ouvre" : " : fiche absente") };
    },
    inactif: async (l) => {
      if (!await boutonAFaire(o, "inactif", l.titre)) return { ok: false, detail: "bouton absent" };
      const x = await attendre(() => evaluer(o, "location.hash.includes('equipage/membres') && document.querySelector('#contenu').innerText.includes('À décider')"), 8000);
      return { ok: !!x, detail: "Équipage, cadre « À décider »" };
    },
    ticket: async (l) => {
      const t = d.tickets.ouverts.find((x) => l.titre.includes("#" + x.ticket + " "));
      return { ok: !!t && (t.salon ? l.href === t.salon : l.bouton.includes("Voir")), detail: "ticket #" + (t && t.ticket) + " → " + (l.href || l.bouton) };
    },
    question: async (l) => {
      const q = d.questions.liste.find((x) => x.statut === "ouverte" && l.sous.includes(x.texte));
      return { ok: !!q && (q.message ? l.href === q.message : l.bouton.includes("Voir")), detail: (q ? q.texte.slice(0, 40) : "question introuvable") + " → " + (l.href || l.bouton) };
    },
    idees: async (l) => {
      if (!await boutonAFaire(o, "idees", l.titre)) return { ok: false, detail: "bouton absent" };
      const x = await attendre(() => evaluer(o, "location.hash.includes('port/salons/idees')"), 6000);
      return { ok: !!x, detail: "Salons, Idées" };
    },
    brouillon: async (l) => {
      const titre = (/« (.+) »/.exec(l.titre) || [])[1];
      if (!await boutonAFaire(o, "brouillon", l.titre)) return { ok: false, detail: "bouton absent" };
      const x = await attendre(() => evaluer(o, `location.hash.includes('annonces/composer') && (document.querySelector('.composeur-form input.saisie') || {}).value === ${JSON.stringify(titre)}`), 8000);
      return { ok: !!x, detail: "« " + titre + " » ouvert dans le composeur" };
    },
    banque: async (l) => {
      if (!await boutonAFaire(o, "banque", l.titre)) return { ok: false, detail: "bouton absent" };
      const x = await attendre(() => evaluer(o, "location.hash.includes('recrutement/questions') && [...document.querySelectorAll('button.liste-bouton')].some((b) => b.textContent.includes('À vérifier'))"
        + " && document.querySelectorAll('.banque-ligne').length > 0 && [...document.querySelectorAll('.banque-ligne')].every((b) => b.textContent.includes('À vérifier'))"), 8000);
      return { ok: !!x, detail: "la banque, filtrée sur « À vérifier »" };
    },
    catalogue: async (l) => {
      if (!await boutonAFaire(o, "catalogue", l.titre)) return { ok: false, detail: "bouton absent" };
      const x = await attendre(() => evaluer(o, "location.hash.includes('capitainerie/catalogue') && [...document.querySelectorAll('button.liste-bouton')].some((b) => b.textContent.includes('À vérifier'))"
        + " && [...document.querySelectorAll('button.element-carte')].every((b) => b.textContent.includes('À vérifier'))"), 8000);
      return { ok: !!x, detail: "le catalogue, filtré sur « À vérifier »" };
    },
    evenement: async (l) => {
      if (!await boutonAFaire(o, "evenement", l.titre)) return { ok: false, detail: "bouton absent" };
      return { ok: !!await attendre(() => evaluer(o, "location.hash.includes('annonces/a-venir')"), 6000), detail: "À venir" };
    },
    roles: async (l) => {
      if (!await boutonAFaire(o, "roles", l.titre)) return { ok: false, detail: "bouton absent" };
      return { ok: !!await attendre(() => evaluer(o, "location.hash.includes('capitainerie/roles')"), 6000), detail: "Rôles & métiers" };
    },
    insignes: async (l) => {
      if (!await boutonAFaire(o, "insignes", l.titre)) return { ok: false, detail: "bouton absent" };
      return { ok: !!await attendre(() => evaluer(o, "location.hash.includes('capitainerie/affiches')"), 6000), detail: "Affiches" };
    },
  };
  const RESTES = { "ticket-reste": "port/tickets", "question-reste": "port/salons/questions", "decider-reste": "capitainerie/recrutement", "corriger-reste": "capitainerie/recrutement",
    "inactif-reste": "equipage/membres", "alerte-reste": "port/repertoire", "brouillon-reste": "annonces/brouillons", "evenement-reste": "annonces/a-venir" };
  const vues = new Set();
  for (const l of lignes) {
    if (vues.has(l.sorte)) continue;
    vues.add(l.sorte);
    if (RESTES[l.sorte]) {
      await etape(o, "Accueil · « " + l.titre + " » → Tout voir", async () => {
        await fermerTout(o); await allerAccueil(o);
        if (!await boutonAFaire(o, l.sorte, l.titre)) return { ok: false, detail: "bouton absent" };
        return { ok: !!await attendre(() => evaluer(o, `location.hash.includes(${JSON.stringify(RESTES[l.sorte])})`), 6000), detail: RESTES[l.sorte] };
      });
      continue;
    }
    if (!essais[l.sorte]) continue;
    await etape(o, "Accueil · « " + l.titre.slice(0, 60) + " » (" + l.bouton + ")", async () => { await fermerTout(o); await allerAccueil(o); return essais[l.sorte](l); });
  }
  await fermerTout(o);
}

// ═══ LA RECHERCHE UNIVERSELLE ═══════════════════════════════════════════════
async function parcoursRecherche(o) {
  const d = await donneesSite(o);
  const ouvrir = async (texte) => {
    await fermerTout(o);
    await evaluer(o, "(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); return 1; })()");
    if (!await attendre(() => evaluer(o, "!!document.querySelector('dialog[open] .recherche-champ')"), 5000, 150)) return false;
    await evaluer(o, `(() => { const i = document.querySelector('dialog[open] .recherche-champ'); i.value = ${JSON.stringify(texte)}; i.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()`);
    await pause(900);
    return true;
  };
  const groupes = () => evaluer(o, "[...document.querySelectorAll('dialog[open] .rech-groupe')].map((g) => ({ g: g.getAttribute('aria-label'), r: [...g.querySelectorAll('.rech-titre')].map((t) => t.textContent) }))");
  const touche = (k) => evaluer(o, `(() => { const i = document.querySelector('dialog[open] .recherche-champ'); i.dispatchEvent(new KeyboardEvent('keydown', { key: ${JSON.stringify(k)}, bubbles: true })); return 1; })()`);
  const h2 = () => evaluer(o, "(() => { const d = [...document.querySelectorAll('dialog[open]')].pop(); return d ? d.querySelector('h2').textContent : ''; })()");
  await aller(o, "#port/journal");

  await etape(o, "Recherche : Ctrl+K l'ouvre, le champ a le focus, le sommaire des rubriques est là", async () => {
    if (!await ouvrir("")) return { ok: false, detail: "Ctrl+K n'ouvre rien" };
    const vu = await evaluer(o, "({ focus: document.activeElement === document.querySelector('dialog[open] .recherche-champ'), rubriques: document.querySelectorAll('dialog[open] .rech-option').length })");
    return { ok: vu.focus && vu.rubriques >= 10, detail: JSON.stringify(vu) };
  });
  const membre = (d.clan.membres || []).find((m) => (m.nom || "").length >= 4);
  await etape(o, "Recherche : un membre, Entrée ouvre sa fiche", async () => {
    await ouvrir(membre.nom);
    const g = await groupes();
    const premier = g[0];
    if (!premier || premier.g !== "Membres" || !premier.r.some((x) => x.includes(membre.nom))) return { ok: false, detail: JSON.stringify(g).slice(0, 200) };
    await touche("Enter");
    const x = await attendre(async () => { const t = await h2(); return t.includes(membre.nom) && !t.includes("Rechercher") ? t : null; }, 8000);
    return { ok: !!x, detail: membre.nom + (x ? " : sa fiche s'ouvre" : " : rien d'ouvert") };
  });
  const ferme = d.tickets.fermes[0];
  await etape(o, "Recherche : « #" + ferme.ticket + " », le ticket d'abord, Entrée ouvre sa conversation", async () => {
    await ouvrir("#" + ferme.ticket);
    const g = await groupes();
    if (!g.length || g[0].g !== "Tickets" || !g[0].r[0].startsWith("Ticket #" + ferme.ticket + " ")) return { ok: false, detail: JSON.stringify(g).slice(0, 200) };
    await touche("Enter");
    const x = await attendre(async () => { const t = await h2(); return t.startsWith("Ticket #" + ferme.ticket + " ") ? t : null; }, 8000);
    return { ok: !!x, detail: x || "conversation absente" };
  });
  await etape(o, "Recherche : les flèches choisissent (aria-activedescendant suit)", async () => {
    await ouvrir("a");
    const avant = await evaluer(o, "document.querySelector('dialog[open] .recherche-champ').getAttribute('aria-activedescendant')");
    await touche("ArrowDown"); await touche("ArrowDown");
    const apres = await evaluer(o, "(() => { const i = document.querySelector('dialog[open] .recherche-champ'); const id = i.getAttribute('aria-activedescendant'); const el = document.getElementById(id); return { id, choisi: el && el.getAttribute('aria-selected'), rang: [...document.querySelectorAll('dialog[open] .rech-option')].indexOf(el) }; })()");
    return { ok: !!avant && apres.id !== avant && apres.choisi === "true" && apres.rang === 2, detail: JSON.stringify(apres) };
  });
  const aff = await api(o, "rell/affiches");
  const a = (aff.affiches || []).find((x) => !x.retire_le);   // la recherche ne propose pas les affiches retirées
  await etape(o, "Recherche : une affiche s'ouvre en grand", async () => {
    if (!a) return { ok: false, detail: "aucune affiche" };
    const nom = (a.roblox && a.roblox.nom) || (a.membre && a.membre.nom);
    await ouvrir(nom);
    const ok = await evaluer(o, `(() => { const o = [...document.querySelectorAll('dialog[open] .rech-groupe[aria-label="Affiches"] .rech-option')][0]; if (!o) return false; o.click(); return true; })()`);
    if (!ok) return { ok: false, detail: "pas de groupe « Affiches » pour " + nom };
    const x = await attendre(async () => { const t = await h2(); return t.startsWith("Affiche de") ? t : null; }, 8000);
    return { ok: !!x, detail: x || "affiche absente" };
  });
  const cat = await api(o, "rell/catalogue");
  const el = (cat.elements || []).find((e) => e.actif !== false && (e.nom || "").length >= 5);
  await etape(o, "Recherche : un élément du catalogue ouvre sa fiche", async () => {
    await ouvrir(el.nom);
    const ok = await evaluer(o, `(() => { const o = [...document.querySelectorAll('dialog[open] .rech-groupe[aria-label="Catalogue RELL Seas"] .rech-option')].find((x) => x.querySelector('.rech-titre').textContent === ${JSON.stringify(el.nom)}); if (!o) return false; o.click(); return true; })()`);
    if (!ok) return { ok: false, detail: "« " + el.nom + " » absent du groupe Catalogue" };
    const x = await attendre(async () => { const t = await h2(); return t.includes(el.nom) ? t : null; }, 8000);
    return { ok: !!x, detail: x || "fiche de l'élément absente" };
  });
  const B = await api(o, "recrutement/banque");
  const q = (B.questions || []).find((x) => !x.retiree && (x.question || "").length > 10);
  await etape(o, "Recherche : une question de la banque, la banque filtrée sur elle", async () => {
    await ouvrir(q.question.slice(0, 30));
    const ok = await evaluer(o, `(() => { const o = [...document.querySelectorAll('dialog[open] .rech-groupe[aria-label="Questions de la banque"] .rech-option')][0]; if (!o) return false; o.click(); return true; })()`);
    if (!ok) return { ok: false, detail: "groupe « Questions de la banque » absent" };
    const x = await attendre(() => evaluer(o, `location.hash.includes('recrutement/questions') && [...document.querySelectorAll('.banque-ligne')].some((b) => b.textContent.includes(${JSON.stringify(q.question)}))`), 8000);
    return { ok: !!x, detail: q.question.slice(0, 60) };
  });
  await etape(o, "Recherche : « Nettoyage » (un onglet de Réglages) y mène", async () => {
    await ouvrir("Nettoyage");
    const ok = await evaluer(o, `(() => { const o = [...document.querySelectorAll('dialog[open] .rech-groupe[aria-label="Rubriques"] .rech-option')].find((x) => x.querySelector('.rech-titre').textContent === 'Nettoyage'); if (!o) return false; o.click(); return true; })()`);
    if (!ok) return { ok: false, detail: "rubrique absente" };
    return { ok: !!await attendre(() => evaluer(o, "location.hash.includes('reglages/nettoyage')"), 6000), detail: "#capitainerie/reglages/nettoyage" };
  });
  await etape(o, "Recherche : « / » l'ouvre aussi, Échap la ferme", async () => {
    await fermerTout(o);
    await evaluer(o, "(() => { document.activeElement && document.activeElement.blur && document.activeElement.blur(); document.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true })); return 1; })()");
    const ouverte = await attendre(() => evaluer(o, "!!document.querySelector('dialog[open] .recherche-champ')"), 4000, 150);
    await evaluer(o, "(() => { const d = document.querySelector('dialog[open]'); d.dispatchEvent(new Event('cancel', { cancelable: true })); return 1; })()");
    const fermee = await attendre(() => evaluer(o, "!document.querySelector('dialog[open]')"), 4000, 150);
    return { ok: !!ouverte && !!fermee, detail: "ouverte " + !!ouverte + " · fermée " + !!fermee };
  });
  await fermerTout(o);
}

// ═══ TEXTES & NOMS : un texte réécrit sur le site, et son EFFET (le faux Discord du site local le montre) ═════════
// Le site local seul a `/tableau/demo/discord` (ce que le faux Discord a reçu) : la preuve n'est pas l'écran du site,
// c'est le message posté dans le ticket, la carte publiée, le rôle renommé.
async function parcoursTextes(o) {
  const N = Date.now().toString(36).slice(-4);
  const leTexte = async (cle) => { const d = await api(o, "textes"); for (const g of d.groupes || []) for (const t of g.textes || []) if (t.cle === cle) return t; return null; };
  const discordLu = (params) => evaluer(o, `fetch(${JSON.stringify(BASE + "/tableau/demo/discord?")} + ${JSON.stringify(params)}, { cache: "no-store" }).then((r) => r.json())`);
  const ecrireApi = (chemin, corps) => evaluer(o, `fetch(${JSON.stringify(SITE + "api/")} + ${JSON.stringify(chemin)}, { method: "POST", credentials: "same-origin",
    headers: { "X-Tableau": "1", "Content-Type": "application/json" }, body: ${JSON.stringify(JSON.stringify(corps))} }).then(async (r) => ({ status: r.status, corps: await r.json() }))`);
  /** Textes & noms : le groupe ouvert, « Modifier » sur le texte de ce titre. */
  const ouvrirTexte = async (groupe, titre) => {
    await aller(o, "#capitainerie/reglages/textes");
    await evaluer(o, `(() => { const g = [...document.querySelectorAll("details.groupe")].find((x) => x.querySelector("summary").textContent.includes(${JSON.stringify(groupe)})); if (g) g.open = true; return !!g; })()`);
    await pause(500);
    const ok = await evaluer(o, `(() => { const li = [...document.querySelectorAll(".texte-ligne")].find((x) => x.querySelector(".texte-titre").textContent.replace(/\\s+/g, " ").trim() === ${JSON.stringify(titre)});
      const b = li && li.querySelector(".texte-tete .bouton"); if (!b) return false; b.scrollIntoView({ block: "center" }); b.click(); return true; })()`);
    return ok && attendre(() => evaluer(o, "!!document.querySelector('dialog[open] .texte-champ')"), 6000);
  };
  const ecrireTexte = (valeur) => evaluer(o, `(() => { const c = [...document.querySelectorAll("dialog[open] .texte-champ")].pop(); if (!c) return false;
    c.focus(); c.value = ${JSON.stringify(valeur)}; c.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const titrePort = () => evaluer(o, "(document.querySelector('#pancartes a[data-cat=\"port\"] .pancarte-titre') || {}).textContent || ''");
  /** Une liste de textes ouverte là où ils s'affichent (« La carte de l'équipe », « Renommer »…) : « Modifier » sur la ligne
   *  de ce titre, puis l'éditeur ouvert. */
  const modifierLigne = async (titre) => {
    const ok = await attendre(() => evaluer(o, `(() => { const li = [...document.querySelectorAll("dialog[open] .texte-ligne")].find((x) => x.querySelector(".texte-titre").textContent.replace(/\\s+/g, " ").trim() === ${JSON.stringify(titre)});
      const b = li && li.querySelector(".texte-tete .bouton"); if (!b) return false; b.scrollIntoView({ block: "center" }); b.click(); return true; })()`), 8000);
    return ok && attendre(() => evaluer(o, "!!document.querySelector('dialog[open] .texte-champ')"), 6000);
  };

  // 1. Le refus de l'étape 1, réécrit dans « Textes & noms ».
  const REFUS = "Merci pour ta candidature " + N + " : elle ne convient pas pour l'instant. Ce ticket va être clôturé.\n-# Thank you for applying: it doesn't fit for now. This ticket will be closed.";
  await etape(o, "Textes : réécrire le refus de l'étape 1", async () => {
    if (!await ouvrirTexte("Recrutement", "Demande refusée (dans le ticket)")) return { ok: false, detail: "éditeur du refus introuvable" };
    if (!await ecrireTexte(REFUS)) return { ok: false, detail: "champ du texte introuvable" };
    const vivant = await evaluer(o, "(document.querySelector('dialog[open] .texte-apercu-vivant') || {}).innerText || ''");
    if (!vivant.includes("Merci pour ta candidature " + N)) return { ok: false, detail: "l'aperçu ne suit pas la saisie : " + vivant.slice(0, 120) };
    if (!await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "bouton « Enregistrer » absent" };
    const t = await attendre(async () => { const x = await leTexte("recrutement.refus_etape1"); return x && x.valeur === REFUS && x.modifie ? x : null; });
    if (!t) return { ok: false, detail: "le serveur n'a pas le nouveau texte" };
    const vu = await attendre(async () => (await texteZone(o)).includes("Merci pour ta candidature " + N), 6000);
    return { ok: !!vu, detail: "version " + t.version + (vu ? "" : " — la liste ne montre pas le nouveau texte") };
  });

  // 1 b. La carte de l'équipe (dans le ticket), réécrite là où on règle le questionnaire (Demande de recrutement → Questions).
  const CARTE = "### Demande refusée " + N + "\nPar {par} {quand} : le message est posté, le ticket se ferme.";
  await etape(o, "Textes : la carte de l'équipe, réécrite depuis Demande de recrutement → Questions", async () => {
    await fermerTout(o);
    await aller(o, "#capitainerie/recrutement/questions");
    // Les messages du bot sont rangés dans un groupe replié du questionnaire (rangement.js) : on le déplie.
    if (!await attendre(async () => { await deplier(o, "Les messages du bot"); return cliquer(o, "button", "La carte de l'équipe"); }, 10000)) return { ok: false, detail: "bouton « La carte de l'équipe » absent" };
    if (!await modifierLigne("Demande refusée")) return { ok: false, detail: "ligne « Demande refusée » ou éditeur absent" };
    if (!await ecrireTexte(CARTE) || !await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "saisie ou enregistrement impossible" };
    const t = await attendre(async () => { const x = await leTexte("recrutement.equipe.refus_etape1"); return x && x.valeur === CARTE ? x : null; });
    await fermerTout(o);
    return { ok: !!t, detail: t ? "enregistré (version " + t.version + ")" : "le serveur n'a pas le nouveau texte" };
  });

  // 2. Refuser une candidature : le ticket reçoit le NOUVEAU texte — réécrit encore une fois depuis la confirmation.
  const REFUS2 = REFUS.replace("Merci pour ta candidature", "Merci pour ton intérêt");
  await etape(o, "Textes : refuser la demande — le ticket reçoit le texte réécrit (« Modifier ce message »)", async () => {
    //  Un ticket d'AVANT l'affiche (sa carte de l'équipe y est encore) : la carte réécrite se voit dans le fil.
    const suivi = await api(o, "recrutement/suivi");
    let tid = 0;
    for (const x of (suivi.ouverts || []).filter((y) => y.etape === "etape1" && !y.fermeture_prevue && !y.affiche)) {
      const d = await api(o, "recrutement/dossier?ticket=" + x.ticket);
      if (d.liens_discord && d.liens_discord.carte_etape1) { tid = x.ticket; break; }
    }
    if (!tid) return { ok: false, detail: "aucune demande d'avant l'affiche, avec sa carte" };
    if (!await ouvrirCandidature(o, tid, "Sa demande")) return { ok: false, detail: "dossier du ticket " + tid + " introuvable" };
    if (!await cliquer(o, "dialog[open] button", "Refuser la demande")) return { ok: false, detail: "bouton « Refuser la demande » absent" };
    const montre = await attendre(async () => (await texteZone(o)).includes("Merci pour ta candidature " + N), 6000);
    if (!montre) return { ok: false, detail: "la confirmation ne montre pas le texte réécrit" };
    if (!await cliquer(o, "dialog[open] button", "Modifier ce message")) return { ok: false, detail: "« Modifier ce message » absent" };
    if (!await attendre(() => evaluer(o, "!!document.querySelector('dialog[open] .texte-champ')"), 6000) || !await ecrireTexte(REFUS2)) return { ok: false, detail: "éditeur non ouvert" };
    if (!await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "« Enregistrer » absent" };
    if (!await attendre(() => evaluer(o, "!document.querySelector('dialog[open] .texte-champ')"), 8000)) return { ok: false, detail: "l'éditeur ne se ferme pas après l'enregistrement" };
    const suit = await attendre(async () => (await evaluer(o, "(document.querySelector('dialog[open] .zr-citation') || {}).innerText || ''")).includes("Merci pour ton intérêt " + N), 8000);
    if (!suit) return { ok: false, detail: "la confirmation ne montre pas le texte modifié sur place" };
    if (!await cliquer(o, "dialog[open] button", "Refuser et fermer le ticket")) return { ok: false, detail: "confirmation absente" };
    const d = await attendre(async () => { const x = await api(o, "recrutement/dossier?ticket=" + tid); return x.etape === "refus_etape1" ? x : null; }, 10000);
    if (!d) return { ok: false, detail: "le serveur n'a pas refusé la demande" };
    const fil = await attendre(async () => { const x = await discordLu("ticket=" + tid); return (x.messages || []).some((m) => m.texte.includes("Merci pour ton intérêt " + N)) ? x : null; }, 8000);
    if (!fil) return { ok: false, detail: "le faux Discord n'a pas le nouveau texte : " + JSON.stringify(await discordLu("ticket=" + tid)).slice(0, 300) };
    const ancien = fil.messages.some((m) => m.texte.includes("Tes réponses ne correspondent pas"));
    // La carte de l'équipe, dans le même ticket, réécrite avec le texte choisi en 1 b.
    const carteEquipe = await attendre(async () => { const x = await discordLu("ticket=" + tid); return (x.messages || []).find((m) => m.reecrit && m.texte.includes("Demande refusée " + N)); }, 8000);
    return { ok: !ancien && !!carteEquipe, detail: "ticket #" + tid + " : « " + fil.messages.find((m) => m.texte.includes("Merci pour ton intérêt " + N)).texte.slice(0, 90) + "… »"
      + (ancien ? " — L'ANCIEN texte est aussi parti" : "") + (carteEquipe ? " · carte de l'équipe : « " + carteEquipe.texte.slice(0, 60) + "… »" : " — la carte de l'équipe n'a pas le texte réécrit") };
  });

  // 3. Le bouton « Disponible » réécrit : la carte publiée porte le nouveau libellé.
  const DISPO = "Présent · Here";
  await etape(o, "Textes : réécrire le bouton « Disponible »", async () => {
    if (!await ouvrirTexte("Annonces & événements", "Le bouton « Disponible »")) return { ok: false, detail: "éditeur du bouton introuvable" };
    if (!await ecrireTexte(DISPO) || !await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "saisie ou enregistrement impossible" };
    const t = await attendre(async () => { const x = await leTexte("evenements.bouton.dispo"); return x && x.valeur === DISPO ? x : null; });
    return { ok: !!t, detail: t ? "enregistré (version " + t.version + ")" : "le serveur n'a pas le nouveau libellé" };
  });
  const TITRE = "Essai des textes " + N;
  await etape(o, "Textes : publier un événement — la carte a le nouveau bouton", async () => {
    await aller(o, "#equipage/annonces/composer");
    if (!await attendre(() => evaluer(o, "!!document.querySelector('.composeur-form input.saisie')"), 8000)) return { ok: false, detail: "composeur absent" };
    // Un composeur NEUF, de type « Événement » : un parcours précédent (l'accueil ouvre un brouillon) peut l'avoir laissé
    // sur autre chose — le composeur garde sa saisie d'une page à l'autre.
    if (await cliquer(o, "button", "Nouveau")) {
      await pause(400);
      if (await evaluer(o, "!!document.querySelector('dialog[open]')")) await cliquer(o, "dialog[open] button", "Repartir de zéro");
      await pause(500);
    }
    if (!await evaluer(o, "(() => { const b = [...document.querySelectorAll('.choix-type')].find((x) => x.textContent.includes('Événement')); if (!b) return false; b.click(); return true; })()")) return { ok: false, detail: "type « Événement » introuvable" };
    await pause(400);
    await evaluer(o, `(() => { const t = document.querySelector('.composeur-form input.saisie'); t.value = ${JSON.stringify(TITRE)}; t.dispatchEvent(new Event("input", { bubbles: true })); return 1; })()`);
    const apercu = await attendre(async () => { const x = await evaluer(o, "(document.querySelector('.apercu-discord-zone') || {}).innerText || ''"); return x.includes(DISPO) ? x : null; }, 6000);
    if (!apercu) return { ok: false, detail: "l'aperçu de la saisie ne montre pas le nouveau bouton" };
    if (!await cliquer(o, "button", "Publier…")) return { ok: false, detail: "bouton « Publier… » absent" };
    if (!await attendre(async () => (await texteZone(o)).includes("Publier « " + TITRE), 10000)) return { ok: false, detail: "confirmation de publication absente" };
    if (!await cliquer(o, "dialog[open] button", "Publier")) return { ok: false, detail: "bouton « Publier » de la confirmation absent" };
    const el = await attendre(async () => { const E = await api(o, "clan/evenements"); return (E.a_venir || []).find((x) => x.titre === TITRE && x.statut === "publie" && x.lien); }, 15000);
    if (!el) return { ok: false, detail: "l'événement n'est pas publié" };
    const salon = (el.lien.match(/channels\/\d+\/(\d+)/) || [])[1];
    const carte = await attendre(async () => { const x = await discordLu("salon=" + salon); return (x.messages || []).find((m) => m.texte.includes(TITRE)); }, 8000);
    if (!carte) return { ok: false, detail: "la carte n'est pas dans le post " + salon };
    const ok = carte.boutons.includes(DISPO) && !carte.boutons.includes("Disponible · Available");
    return { ok, detail: "boutons de la carte : " + carte.boutons.join(" | ") };
  });

  // 4. Un conflit : le même texte modifié ailleurs pendant qu'on l'écrit — les deux versions, côte à côte.
  await etape(o, "Textes : un conflit montre les deux versions et garde la mienne", async () => {
    if (!await ouvrirTexte("Annonces & événements", "Le bouton « Peut-être »")) return { ok: false, detail: "éditeur introuvable" };
    const avant = await leTexte("evenements.bouton.peut_etre");
    const ailleurs = await ecrireApi("texte", { cle: "evenements.bouton.peut_etre", valeur: "Pourquoi pas · Why not", version: avant.version });
    if (ailleurs.status !== 200) return { ok: false, detail: "écriture « ailleurs » refusée : " + JSON.stringify(ailleurs).slice(0, 200) };
    if (!await ecrireTexte("Je verrai · Maybe later") || !await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "saisie impossible" };
    const deux = await attendre(async () => { const x = await evaluer(o, "(document.querySelector('dialog[open] .texte-conflit') || {}).innerText || ''"); return x.includes("Ta version") && x.includes("La version enregistrée") && x.includes("Pourquoi pas") ? x : null; }, 8000);
    if (!deux) return { ok: false, detail: "pas de vue du conflit" };
    if (!await cliquer(o, "dialog[open] button", "Garder la mienne")) return { ok: false, detail: "« Garder la mienne » absent" };
    const t = await attendre(async () => { const x = await leTexte("evenements.bouton.peut_etre"); return x && x.valeur === "Je verrai · Maybe later" ? x : null; });
    return { ok: !!t, detail: t ? "ma version gardée (version " + t.version + ")" : "le serveur n'a pas ma version" };
  });

  // 5. Renommer le rôle d'un métier : le rôle Discord change de nom, et le nom servira pour le recréer.
  await etape(o, "Rôles : renommer le rôle d'un métier", async () => {
    const avant = (await discordLu("roles=1")).roles || [];
    await aller(o, "#capitainerie/roles");
    const nomAvant = await evaluer(o, `(() => { const l = [...document.querySelectorAll(".registre-ligne")].find((x) => [...x.querySelectorAll("button")].some((b) => b.textContent.includes("Renommer")));
      return l ? l.querySelector(".role-lie").textContent.trim() : ""; })()`);
    if (!nomAvant) return { ok: false, detail: "aucun rôle de métier à renommer" };
    const role = avant.find((r) => r.nom === nomAvant);
    if (!await cliquer(o, "button", "Renommer…")) return { ok: false, detail: "bouton « Renommer… » absent" };
    const NOUVEAU = "Maître " + N;
    if (!await attendre(() => ecrire(o, "Nouveau nom du rôle", NOUVEAU), 5000)) return { ok: false, detail: "champ du nom absent" };
    if (!await cliquer(o, "dialog[open] button", "Renommer")) return { ok: false, detail: "confirmation absente" };
    const apres = await attendre(async () => { const x = (await discordLu("roles=1")).roles || []; return x.find((r) => r.nom === NOUVEAU) ? x : null; }, 10000);
    if (!apres) return { ok: false, detail: "le faux Discord n'a pas de rôle « " + NOUVEAU + " »" };
    const meme = role && apres.find((r) => r.nom === NOUVEAU).id === role.id;
    const reg = await api(o, "rell/metiers/reglages");
    const metier = (reg.metiers || []).find((m) => m.role && m.role.id === (role && role.id));
    const vu = await attendre(async () => (await texteZone(o)).includes(NOUVEAU), 6000);
    return { ok: !!(meme && metier && metier.role_nom === NOUVEAU && vu), detail: "« " + nomAvant + " » → « " + NOUVEAU + " » (même rôle : " + !!meme + ", nom gardé pour le recréer : " + (metier && metier.role_nom) + (vu ? "" : ", pas affiché") + ")" };
  });

  // 5 b. Un sous-onglet renommé depuis l'en-tête de sa rubrique (« Renommer ») : la rubrique se redessine avec lui.
  const PARUES = "Déjà parues";
  const onglets = () => evaluer(o, "[...document.querySelectorAll('#contenu .sous-onglets .etiquette')].map((a) => a.textContent).join(' | ')");
  await etape(o, "Site : renommer un sous-onglet depuis l'en-tête de sa rubrique", async () => {
    await fermerTout(o);
    await aller(o, "#equipage/annonces/composer");
    if (!await attendre(() => cliquer(o, "#contenu .titre-rubrique button", "Renommer"), 8000)) return { ok: false, detail: "« Renommer » absent de l'en-tête" };
    if (!await modifierLigne("Annonces & événements · l'onglet « Publiées »")) return { ok: false, detail: "ligne de l'onglet « Publiées » absente" };
    if (!await ecrireTexte(PARUES) || !await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "saisie ou enregistrement impossible" };
    const t = await attendre(async () => { const x = await leTexte("site.sous.equipage.annonces.publiees"); return x && x.valeur === PARUES ? x : null; });
    if (!t) return { ok: false, detail: "le serveur n'a pas le nouveau nom" };
    if (!await attendre(() => evaluer(o, "!document.querySelector('dialog[open] .texte-champ')"), 6000)) return { ok: false, detail: "l'éditeur reste ouvert" };
    if (!await cliquer(o, "dialog[open] button", "Fermer")) return { ok: false, detail: "« Fermer » absent" };
    const vu = await attendre(async () => { const x = await onglets(); return x.includes(PARUES) ? x : null; }, 8000);
    return { ok: !!vu, detail: vu ? "onglets : " + vu : "les onglets disent encore : " + await onglets() };
  });

  // 5 c. Le guide du clan (le post 🧭 Guide du clan), réécrit depuis Rôles & métiers : le post suit tout seul.
  const LIRE = "Lire le tableau " + N;
  await etape(o, "Textes : le guide du clan réécrit depuis Rôles & métiers — le post du guide suit", async () => {
    const avant = ((await discordLu("post=guide")).messages || [])[0];
    if (!avant || avant.boutons[0] !== "Lire · Read") return { ok: false, detail: "guide du clan absent du faux Discord : " + JSON.stringify(avant || {}).slice(0, 200) };
    await fermerTout(o);
    await aller(o, "#capitainerie/roles");
    if (!await attendre(() => cliquer(o, "button", "Les textes du guide du clan"), 10000)) return { ok: false, detail: "bouton « Les textes du guide du clan » absent" };
    if (!await modifierLigne("Le post 📢 Infos · le bouton")) return { ok: false, detail: "ligne du bouton des infos absente" };
    if (!await ecrireTexte(LIRE) || !await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "saisie ou enregistrement impossible" };
    const t = await attendre(async () => { const x = await leTexte("guide.infos.bouton"); return x && x.valeur === LIRE ? x : null; });
    await fermerTout(o);
    if (!t) return { ok: false, detail: "le serveur n'a pas le nouveau texte" };
    const apres = await attendre(async () => { const m = ((await discordLu("post=guide")).messages || [])[0]; return m && m.boutons[0] === LIRE ? m : null; }, 25000);
    return { ok: !!apres, detail: apres ? "boutons du guide : " + apres.boutons.join(" | ") : "le post du guide n'a pas été réécrit : " + JSON.stringify(((await discordLu("post=guide")).messages || [])[0] || {}).slice(0, 200) };
  });

  // 6. Renommer « Le Port » : la navigation l'affiche tout de suite, et après un rechargement.
  await etape(o, "Site : renommer « Le Port » — la navigation suit", async () => {
    if (!await ouvrirTexte("Le site", "Le Port · le nom")) return { ok: false, detail: "éditeur du nom introuvable" };
    if (!await ecrireTexte("La Taverne") || !await cliquer(o, "dialog[open] button", "Enregistrer")) return { ok: false, detail: "saisie impossible" };
    const tout_de_suite = await attendre(async () => (await titrePort()) === "La Taverne", 6000);
    if (!tout_de_suite) return { ok: false, detail: "la pancarte dit encore « " + await titrePort() + " »" };
    await o.s("Page.reload");
    await attendre(() => evaluer(o, "!!document.querySelector('#contenu .titre-rubrique')"), 12000);
    const apres = await attendre(async () => (await titrePort()) === "La Taverne", 6000);
    return { ok: !!apres, detail: apres ? "« La Taverne », aussi après rechargement" : "après rechargement : « " + await titrePort() + " »" };
  });

  // 7. « Revenir au texte d'origine » : l'ancien revient (le nom, le refus, le bouton).
  await etape(o, "Textes : revenir au texte d'origine", async () => {
    const remettre = async (groupe, titre) => {
      if (!await ouvrirTexte(groupe, titre)) return "éditeur « " + titre + " » introuvable";
      if (!await cliquer(o, "dialog[open] button", "Revenir au texte d'origine")) return "« Revenir au texte d'origine » absent (" + titre + ")";
      if (!await attendre(() => cliquer(o, "dialog[open] button", "Revenir à l'origine"), 5000)) return "confirmation absente (" + titre + ")";
      return "";
    };
    for (const [groupe, titre] of [["Le site", "Le Port · le nom"], ["Recrutement", "Demande refusée (dans le ticket)"], ["Annonces & événements", "Le bouton « Disponible »"],
      ["Recrutement", "Demande refusée"], ["Le site", "Annonces & événements · l'onglet « Publiées »"], ["Le guide du clan", "Le post 📢 Infos · le bouton"]]) {
      const faute = await remettre(groupe, titre);
      if (faute) return { ok: false, detail: faute };
      await pause(600);
    }
    const port = await attendre(async () => (await titrePort()) === "Le Port", 6000);
    const textes_ = await Promise.all(["site.cat.port.titre", "recrutement.refus_etape1", "evenements.bouton.dispo", "recrutement.equipe.refus_etape1",
      "site.sous.equipage.annonces.publiees", "guide.infos.bouton"].map(leTexte));
    const origine = textes_.every((t) => t && !t.modifie && t.valeur === t.defaut);
    return { ok: !!port && origine, detail: "pancarte « " + await titrePort() + " » · " + textes_.map((t) => t && t.cle + (t.modifie ? " MODIFIÉ" : " d'origine")).join(", ") };
  });
}

// ═══ LA NAVIGATION REGROUPÉE (27/10/2026) ═══════════════════════════════════
// Le fondateur : « regrouper tous les onglets, pas des milliers de sous-onglets ». Les rubriques de chaque pancarte ;
// chaque ancienne adresse mène au bon endroit ; les vues d'une rubrique changent sur place (la recherche tapée reste, la
// page ne se redessine pas ni ne remonte) ; les noms suivent (renommés, la présence en direct, la recherche).
const ANCIENNES = [   // [ancienne adresse, nouvelle, titre, sous-onglet ouvert (ou puce choisie), un texte de la page]
  ["#port/apercu", "#accueil/attente", "Ce qui t'attend", "", "À faire"],   // une ancienne adresse
  ["#port/nettoyage", "#capitainerie/reglages/nettoyage", "Réglages", "Nettoyage", "Le grand ménage"],   // une ancienne adresse
  ["#capitainerie/textes", "#capitainerie/reglages/textes", "Réglages", "Textes & noms", "le bot emploie ton texte"],   // une ancienne adresse
  ["#equipage/fiches", "#equipage/membres/fiches", "Équipage", "Fiches techniques", "fiches vierges"],   // une ancienne adresse
  ["#equipage/tickets", "#port/tickets/clan", "Tickets", "Clan · RELL Seas", "Ouverts"],   // une ancienne adresse
  ["#capitainerie/securite", "#capitainerie/reglages/securite", "Réglages", "Sécurité", "En cas de doute"],   // la Sécurité : un sous-onglet
];
async function parcoursNavigation(o) {
  const titre = () => evaluer(o, "(document.querySelector('#contenu h1') || {}).textContent || ''");
  const ouvert = () => evaluer(o, "((document.querySelector('#contenu .sous-onglets [aria-selected=true]') || document.querySelector('#contenu .puces [aria-pressed=true]') || {}).textContent || '').replace(/\\d+$/, '').trim()");
  const texte = () => evaluer(o, "document.querySelector('#contenu').innerText");
  const marquer = () => evaluer(o, "(() => { document.querySelector('#contenu .titre-rubrique').dataset.marque = 'nav'; return 1; })()");
  const marque = () => evaluer(o, "(document.querySelector('#contenu .titre-rubrique') || { dataset: {} }).dataset.marque === 'nav'");
  const hash = () => evaluer(o, "location.hash");
  const ecrireApi = (chemin, corps) => evaluer(o, `fetch(${JSON.stringify(SITE + "api/")} + ${JSON.stringify(chemin)}, { method: "POST", credentials: "same-origin",
    headers: { "X-Tableau": "1", "Content-Type": "application/json" }, body: ${JSON.stringify(JSON.stringify(corps))} }).then(async (r) => ({ status: r.status, corps: await r.json() }))`);

  //  Joué après d'autres parcours : leurs filtres gardés (statut « à vérifier » du catalogue…) oubliés, la page relue.
  await aller(o, "#accueil/attente");
  await evaluer(o, "(() => { sessionStorage.removeItem('capitainerie.filtres'); return 1; })()");
  await o.s("Page.reload", {});
  await attendre(() => evaluer(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 12000, 200);
  await etape(o, "Navigation : quinze rubriques (dix-neuf avant), cinq au plus par pancarte", async () => {
    const vu = {};
    for (const cat of ["accueil", "port", "equipage", "capitainerie"]) {
      await aller(o, "#" + cat);
      vu[cat] = await evaluer(o, "[...document.querySelectorAll('#rubriques a')].map((a) => a.querySelector('span:not(.compteur)').textContent.trim())");
    }
    const attendu = { accueil: ["Ce qui t'attend"], port: ["Journal", "Sanctions", "Tickets", "Répertoire", "Salons & questions"],
      equipage: ["Équipage", "Annonces & événements"], capitainerie: ["Demande de recrutement", "Affiches", "Catalogue RELL Seas", "Rôles & métiers", "Réglages"] };
    return { ok: JSON.stringify(vu) === JSON.stringify(attendu), detail: Object.entries(vu).map(([c, l]) => c + " : " + l.join(", ")).join(" · ") };
  });

  for (const [avant, apres, t, sous, mot] of ANCIENNES) {
    await etape(o, "Ancienne adresse " + avant + " → " + apres, async () => {
      await aller(o, avant);
      await attendre(async () => (await texte()).includes(mot), 8000, 250);
      const vu = { hash: await hash(), titre: await titre(), ouvert: await ouvert(), mot: (await texte()).includes(mot) };
      return { ok: vu.hash === apres && vu.titre === t && (!sous || vu.ouvert === sous) && vu.mot, detail: JSON.stringify(vu) };
    });
  }
  await etape(o, "Réglages : le sous-onglet « Sécurité » (sessions, actions du site, permissions dangereuses)", async () => {
    await aller(o, "#capitainerie/reglages");
    if (!await cliquer(o, "#contenu .sous-onglets a", "Sécurité")) return { ok: false, detail: "onglet « Sécurité » absent" };
    const ok = await attendre(async () => (await hash()) === "#capitainerie/reglages/securite" && (await ouvert()) === "Sécurité"
      && (await texte()).toLowerCase().includes("fermer toutes les autres sessions"), 8000, 250);
    const vu = await evaluer(o, "[...document.querySelectorAll('#contenu h2')].map((x) => x.textContent.trim()).join(' | ')");
    return { ok: !!ok, detail: (await hash()) + " · " + vu };
  });

  const d = await donneesSite(o);
  //  Un vrai identifiant Discord (5 chiffres au moins : la page ignore les autres dans l'adresse).
  const membre = Object.values(d.personnes || {}).find((p) => /^\d{5,22}$/.test(String(p.id)) && p.nom && p.nom !== "Membre parti");
  await etape(o, "Ancienne adresse avec une fiche ouverte (l'Aperçu et un membre) : l'accueil, et la fiche", async () => {
    await aller(o, ANCIENNES[0][0] + "&membre=" + membre.id);
    const fiche = await attendre(() => evaluer(o, "(() => { const d = [...document.querySelectorAll('dialog[open]')].pop(); return d ? d.querySelector('h2').textContent : ''; })()"), 8000);
    const h = await hash();
    return { ok: h === "#accueil/attente&membre=" + membre.id && !!fiche && fiche.includes(membre.nom), detail: h + " · " + fiche };
  });

  await etape(o, "Équipage : Présence → Fiches techniques → Équipes, sur place (la recherche tapée reste)", async () => {
    await aller(o, "#equipage/membres");
    await marquer();
    await evaluer(o, "(() => { const i = document.querySelector('#contenu .outils input[type=search]'); i.value = 'a'; i.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()");
    await pause(500);
    const etapes = [];
    const equipes = "[...document.querySelectorAll('#contenu button')].some((b) => b.textContent.includes('Nouvelle équipe'))";
    for (const [onglet, attendu, preuve] of [["Fiches techniques", "#equipage/membres/fiches", "document.querySelector('#contenu').innerText.includes('fiches vierges')"],
      ["Équipes", "#equipage/membres/equipes", equipes], ["Présence", "#equipage/membres", "!!document.querySelector('#contenu [aria-label=Présence]') && !" + equipes]]) {
      if (!await cliquer(o, "#contenu .sous-onglets a", onglet)) return { ok: false, detail: "onglet « " + onglet + " » absent" };
      const ok = await attendre(async () => (await hash()) === attendu && (await ouvert()) === onglet && await evaluer(o, preuve), 8000, 250);
      const v = await evaluer(o, "document.querySelector('#contenu .outils input[type=search]').value");
      etapes.push(onglet + " : " + (ok ? "ok" : "ÉCHEC " + await hash()) + ", recherche « " + v + " », " + (await marque() ? "sur place" : "page redessinée"));
      if (!ok || v !== "a" || !await marque()) return { ok: false, detail: etapes.join(" · ") };
    }
    return { ok: true, detail: etapes.join(" · ") };
  });

  await etape(o, "Tickets : la famille « Clan · RELL Seas » sur place (la page ne remonte pas), puis « Tous »", async () => {
    await aller(o, "#port/tickets");
    await o.s("Page.reload", {});   // les données de la page relues : les mêmes que celles lues ci-dessous
    await attendre(() => evaluer(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 12000, 200);
    await pause(600);
    const rell = new Set(((await donneesSite(o)).tickets.ouverts || []).filter((t) => t.rellseas).map((t) => String(t.ticket)));
    await marquer();
    const avant = await evaluer(o, "(() => { const b = [...document.querySelectorAll('#contenu .puces .puce')].find((x) => x.textContent.includes('Clan · RELL Seas')); b.scrollIntoView({ block: 'center' }); return scrollY; })()");
    await evaluer(o, "(() => { [...document.querySelectorAll('#contenu .puces .puce')].find((x) => x.textContent.includes('Clan · RELL Seas')).click(); return 1; })()");
    const ok = await attendre(async () => (await hash()) === "#port/tickets/clan" && (await ouvert()) === "Clan · RELL Seas", 6000, 200);
    await pause(400);
    const apres = await evaluer(o, "scrollY");
    await evaluer(o, "(() => { for (const g of document.querySelectorAll('#contenu details.groupe')) g.open = true; return 1; })()");
    await pause(500);
    const lignes = await evaluer(o, "[...document.querySelectorAll('#contenu .lc[data-ticket]')].filter((l) => l.closest('section') && l.closest('section').querySelector('h2').textContent.includes('Ouverts')).map((l) => l.dataset.ticket)");
    const tousClan = lignes.length > 0 && lignes.every((t) => rell.has(t));
    const surPlace = await marque();
    await cliquer(o, "#contenu .puces .puce", "Tous");
    const retour = await attendre(async () => (await hash()) === "#port/tickets", 6000, 200);
    return { ok: !!ok && tousClan && surPlace && Math.abs(apres - avant) < 6 && !!retour,
      detail: `${lignes.length} ticket(s) ouvert(s), tous du clan : ${tousClan} · défilement ${avant} → ${apres} · ${surPlace ? "sur place" : "page redessinée"} · retour « Tous » ${!!retour}` };
  });

  await etape(o, "Salons : « Idées & sondages », ses deux vues sur place (#…/idees ↔ #…/sondages)", async () => {
    await aller(o, "#port/salons/idees");
    await marquer();
    const onglet0 = await ouvert();
    if (!await cliquer(o, "#contenu .outils .segment button", "Sondages")) return { ok: false, detail: "« Sondages » absent" };
    const ok = await attendre(async () => (await hash()) === "#port/salons/sondages" && (await texte()).includes("Créés par les membres sur Discord"), 6000, 200);
    const onglet1 = await ouvert();
    const nb = await evaluer(o, "document.querySelectorAll('#contenu .sous-onglets a').length");
    return { ok: !!ok && onglet0 === "Idées & sondages" && onglet1 === "Idées & sondages" && await marque() && nb === 5,
      detail: `onglet « ${onglet0} » puis « ${onglet1} » · ${nb} onglets · ${await marque() ? "sur place" : "page redessinée"}` };
  });

  await etape(o, "Réglages : Textes & noms, Nettoyage ; « Régler les durées » du recrutement y mène", async () => {
    await aller(o, "#capitainerie/reglages");
    const o1 = await ouvert();
    if (!await cliquer(o, "#contenu .sous-onglets a", "Nettoyage")) return { ok: false, detail: "onglet « Nettoyage » absent" };
    const n = await attendre(async () => (await hash()) === "#capitainerie/reglages/nettoyage" && (await texte()).includes("Le grand ménage"), 8000, 250);
    await aller(o, "#capitainerie/recrutement/reglages");
    await deplier(o, "Le nettoyage");
    const b = await attendre(() => cliquer(o, "#contenu button", "Régler les durées"), 6000);
    const r = await attendre(async () => (await hash()) === "#capitainerie/reglages/nettoyage" && (await titre()) === "Réglages", 6000, 200);
    return { ok: o1 === "Textes & noms" && !!n && !!b && !!r, detail: `ouvert d'abord « ${o1} » · Nettoyage ${!!n} · depuis le recrutement ${!!r}` };
  });

  await etape(o, "Accueil : les chiffres de l'Aperçu (« Tout afficher ») ; « Alertes en cours » ouvre le Répertoire filtré", async () => {
    await aller(o, "#accueil/attente");
    await evaluer(o, "(() => { if (document.documentElement.classList.contains('mode-simple')) document.querySelector('.bascule-mode').click(); return 1; })()");
    await pause(300);
    const tuiles = await evaluer(o, "[...document.querySelectorAll('#contenu .tuile .lib')].filter((x) => x.getClientRects().length).map((x) => x.textContent)");
    const tendances = await evaluer(o, "[...document.querySelectorAll('#contenu details.groupe summary')].some((s) => s.textContent.includes('Tendances'))");
    const alertes = (d.alertes || []).length;
    let filtre = "";
    if (alertes) {
      await evaluer(o, "(() => { [...document.querySelectorAll('#contenu button.tuile')].find((b) => b.textContent.includes('Alertes en cours')).click(); return 1; })()");
      await attendre(async () => (await hash()) === "#port/repertoire", 6000, 200);
      filtre = await evaluer(o, "((document.querySelector('#contenu .puces [aria-pressed=true]') || {}).textContent || '').replace(/\\d+$/, '').trim()");
    }
    await evaluer(o, "(() => { if (!document.documentElement.classList.contains('mode-simple')) document.querySelector('.bascule-mode').click(); return 1; })()");
    const attendues = ["Tickets ouverts", "Questions sans réponse", "Alertes en cours", "Sanctions · 30 jours", "Candidatures", "Membres du clan"];
    return { ok: attendues.every((x) => tuiles.includes(x)) && tendances && (!alertes || filtre === "Alertes"),
      detail: tuiles.join(", ") + " · Tendances " + tendances + (alertes ? " · Répertoire filtré « " + filtre + " »" : "") };
  });

  await etape(o, "Catalogue : le type dans une liste (plus de rangée d'onglets) ; « Métiers » ne montre que les métiers", async () => {
    await aller(o, "#capitainerie/catalogue");
    const rangee = await evaluer(o, "!!document.querySelector('#contenu .sous-onglets')");
    const cat = await api(o, "rell/catalogue");
    const metiers = (cat.elements || []).filter((e) => e.type === "metier" && e.actif !== false).length;
    await evaluer(o, "(async () => { const g = [...document.querySelectorAll('#contenu .liste-groupe')].find((x) => x.querySelector('.liste-lib').textContent.trim() === 'Type'); g.querySelector('.liste-bouton').click(); await new Promise((r) => setTimeout(r, 400)); [...document.querySelectorAll('[role=option]')].find((x) => x.textContent.includes('Métiers')).click(); return 1; })()");
    const vus = await attendre(async () => { const n = await evaluer(o, "document.querySelectorAll('#contenu button.element-carte, #contenu article.element-carte').length"); return n ? n : null; }, 6000, 200);
    await evaluer(o, "(async () => { const g = [...document.querySelectorAll('#contenu .liste-groupe')].find((x) => x.querySelector('.liste-lib').textContent.trim() === 'Type'); g.querySelector('.liste-bouton').click(); await new Promise((r) => setTimeout(r, 400)); [...document.querySelectorAll('[role=option]')].find((x) => x.textContent.includes('Tous les types')).click(); return 1; })()");
    return { ok: !rangee && vus === Math.min(metiers, 24), detail: `rangée d'onglets : ${rangee} · ${vus} carte(s) pour ${metiers} métier(s)` };
  });

  await etape(o, "Recherche : les anciens noms trouvent leur nouvelle place (« aperçu », « tickets du clan », « fiches techniques »)", async () => {
    const essais = [["aperçu", "Les chiffres du bord", "#accueil/attente"], ["tickets du clan", "Tickets · Clan · RELL Seas", "#port/tickets/clan"],
      ["fiches techniques", "Fiches techniques", "#equipage/membres/fiches"]];
    const vus = [];
    for (const [q, option, cible] of essais) {
      await aller(o, "#port/journal");
      await evaluer(o, "(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); return 1; })()");
      await attendre(() => evaluer(o, "!!document.querySelector('dialog[open] .recherche-champ')"), 5000, 150);
      await evaluer(o, `(() => { const i = document.querySelector('dialog[open] .recherche-champ'); i.value = ${JSON.stringify(q)}; i.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()`);
      await pause(800);
      const ok = await evaluer(o, `(() => { const x = [...document.querySelectorAll('dialog[open] .rech-groupe[aria-label="Rubriques"] .rech-option')].find((e) => e.querySelector('.rech-titre').textContent === ${JSON.stringify(option)}); if (!x) return false; x.click(); return true; })()`);
      const arrive = ok && await attendre(async () => (await hash()) === cible, 6000, 200);
      vus.push(q + " → " + (arrive ? cible : ok ? "pas arrivé" : "absent"));
      if (!arrive) return { ok: false, detail: vus.join(" · ") };
    }
    return { ok: true, detail: vus.join(" · ") };
  });

  await etape(o, "Noms : une vue renommée (Textes & noms) se lit partout — l'onglet, la présence en direct", async () => {
    const cle = "site.sous.equipage.membres.fiches";
    const t0 = await api(o, "textes");
    const t = (t0.groupes || []).flatMap((g) => g.textes || []).find((x) => x.cle === cle);
    if (!t) return { ok: false, detail: "nom « " + cle + " » absent du registre" };
    const r = await ecrireApi("texte", { cle, valeur: "Fiches du bord", version: t.version });
    if (r.status !== 200) return { ok: false, detail: "écriture refusée : " + JSON.stringify(r).slice(0, 200) };
    await evaluer(o, "(() => { localStorage.removeItem('capitainerie.libelles'); return 1; })()");
    await aller(o, "#equipage/membres");
    await o.s("Page.reload", {});   // la page relit les noms (sinon toutes les deux minutes)
    await attendre(() => evaluer(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')"), 12000, 200);
    const onglet = await attendre(async () => { const l = await evaluer(o, "[...document.querySelectorAll('#contenu .sous-onglets a')].map((a) => a.textContent.trim())"); return l.includes("Fiches du bord") ? l : null; }, 8000, 300);
    //  La présence en direct dit la page de chacun, aussi celle d'un onglet pas encore rechargé (une ancienne adresse).
    const pages = [ANCIENNES[3][0], ANCIENNES[1][0], "#port/tickets/clan", ANCIENNES[0][0]].map((x) => x.slice(1));
    const presence = await evaluer(o, "import('/tableau/espace/s/direct.js').then((m) => " + JSON.stringify(pages) + ".map((p) => m.libellePage(p)))");
    const t1 = (await api(o, "textes")).groupes.flatMap((g) => g.textes || []).find((x) => x.cle === cle);
    const remis = await ecrireApi("texte/defaut", { cle, version: t1.version });
    const ok = !!onglet && presence[0] === "Équipage › Équipage › Fiches du bord" && presence[1] === "Capitainerie › Réglages › Nettoyage"
      && presence[2] === "Le Port › Tickets › Clan · RELL Seas" && presence[3] === "Accueil › Ce qui t'attend" && remis.status === 200;
    return { ok, detail: "onglets : " + (onglet || []).join(", ") + " · présence : " + presence.join(" | ") + " · remis : " + remis.status };
  });
}

// ═══ LES INTERDICTIONS DE TICKETS (27/10/2026) ═══════════════════════════════════════════════════════════════
// La fiche d'une personne, son bloc « Tickets » : la tête interdit les tickets du clan à un membre ; il touche un panneau
// du clan (le VRAI chemin du bot, faux Discord) : refusé, un avis générique ; un panneau du serveur : accepté ; aucun message
// privé ; la tête lève l'interdiction. L'état est relu par l'API après chaque geste. Le site local seulement.
const MEMBRE_TI = "1012";   // Corsaire, du clan, sans interdiction au départ
async function parcoursTicketsInterdits(o) {
  const etatTI = () => api(o, "tickets/interdictions?membre=" + MEMBRE_TI);
  const demo = (chemin) => evaluer(o, `fetch(${JSON.stringify(BASE + chemin)}, { credentials: "same-origin" }).then((r) => r.json())`);
  const bloc = (famille) => evaluer(o, `(() => { const l = document.querySelector('dialog[open] .fiche-tickets .ti-ligne[data-famille="${famille}"]'); return l ? { etat: l.dataset.etat, texte: l.innerText } : null; })()`);
  const ouvrirFiche = async () => {
    await aller(o, "#port/repertoire");   // « &membre= » ne lit que les identifiants de Discord (5 chiffres et plus)
    await evaluer(o, "import('/tableau/espace/s/fiche.js').then((m) => { m.ouvrirFiche('" + MEMBRE_TI + "'); return 1; })");
    return attendre(() => evaluer(o, "!!document.querySelector('dialog[open] .fiche-tickets .ti-ligne[data-etat]')"), 10000, 200);
  };

  await etape(o, "Fiche : le bloc « Tickets » sous les sanctions, serveur et clan autorisés", async () => {
    if (!await ouvrirFiche()) return { ok: false, detail: "bloc Tickets absent de la fiche" };
    const place = await evaluer(o, "(() => { const d = document.querySelector('dialog[open]'); const t = d.querySelector('.fiche-tickets'), on = d.querySelector('.onglets-fiche'), a = d.querySelector('.fiche-agir:not(.fiche-tickets)');"
      + " return !!t && !!on && !!(t.compareDocumentPosition(on) & 4) && (!a || !!(a.compareDocumentPosition(t) & 4)); })()");
    const s = await bloc("serveur"), c = await bloc("clan"), e = await etatTI();
    const ok = place && s.etat === "autorise" && c.etat === "autorise" && e.familles.clan.etat === "autorise";
    return { ok, detail: `place ${place} · serveur ${s.etat} · clan ${c.etat}` };
  });

  await etape(o, "La tête interdit les tickets du clan, avec un motif", async () => {
    if (!await cliquer(o, 'dialog[open] .ti-ligne[data-famille="clan"] button', "Interdire")) return { ok: false, detail: "bouton « Interdire » absent" };
    await attendre(() => evaluer(o, "!!document.querySelectorAll('dialog[open]')[1]"), 4000, 150);
    await ecrire(o, "Motif (facultatif)", "Parcours : réponses copiées");
    if (!await cliquer(o, "dialog[open] .pancarte-pied button", "Interdire")) return { ok: false, detail: "confirmation absente" };
    const e = await attendre(async () => { const x = await etatTI(); return x.familles.clan.etat === "interdit" ? x : null; }, 8000);
    if (!e) return { ok: false, detail: "le serveur n'a pas l'interdiction : " + JSON.stringify(await etatTI()).slice(0, 200) };
    const c = await attendre(async () => { const x = await bloc("clan"); return x && x.etat === "interdit" ? x : null; }, 5000, 200);
    const noire = await api(o, "recrutement/liste_noire");
    const liste = (noire.actifs || []).some((x) => x.membre && x.membre.id === MEMBRE_TI);
    const ok = e.familles.clan.motif === "Parcours : réponses copiées" && e.familles.serveur.etat === "autorise" && !!c && liste;
    return { ok, detail: `clan ${e.familles.clan.etat} « ${e.familles.clan.motif} » · bloc ${c && c.texte.replace(/\s+/g, " ")} · liste noire du recrutement : ${liste}` };
  });

  await etape(o, "Le membre touche un panneau du clan : refusé, un avis générique", async () => {
    const r = await demo("/tableau/demo/recrutement/ouvrir?membre=" + MEMBRE_TI + "&panneau=p1");
    const lu = String(r.lu || "");
    const ok = r.ok === false && lu.includes("Tu ne peux pas ouvrir ce type de ticket") && !/réponses copiées|liste noire|GoRipe/i.test(lu);
    return { ok, detail: "lu : " + lu.slice(0, 160) };
  });

  await etape(o, "Il touche un panneau du serveur : accepté (un ticket s'ouvre)", async () => {
    const r = await demo("/tableau/demo/recrutement/ouvrir?membre=" + MEMBRE_TI + "&panneau=p2");
    return { ok: r.ok === true && Number(r.ticket) > 0, detail: "ticket " + r.ticket + " · " + String(r.confirmation || "").slice(0, 80) };
  });

  await etape(o, "Silence : aucun message privé ne lui est parti", async () => {
    const mp = await demo("/tableau/demo/mp?membre=" + MEMBRE_TI);
    return { ok: Array.isArray(mp.messages) && mp.messages.length === 0, detail: (mp.messages || []).length + " message(s) privé(s)" };
  });

  await etape(o, "La tête lève l'interdiction ; le panneau du clan se rouvre", async () => {
    if (!await ouvrirFiche()) return { ok: false, detail: "fiche introuvable" };
    if (!await cliquer(o, 'dialog[open] .ti-ligne[data-famille="clan"] button', "Lever")) return { ok: false, detail: "bouton « Lever l'interdiction » absent" };
    await attendre(() => evaluer(o, "!!document.querySelectorAll('dialog[open]')[1]"), 4000, 150);
    if (!await cliquer(o, "dialog[open] .pancarte-pied button", "Lever")) return { ok: false, detail: "confirmation absente" };
    const e = await attendre(async () => { const x = await etatTI(); return x.familles.clan.etat === "autorise" ? x : null; }, 8000);
    const c = await attendre(async () => { const x = await bloc("clan"); return x && x.etat === "autorise" ? x : null; }, 5000, 200);
    const r = await demo("/tableau/demo/recrutement/ouvrir?membre=" + MEMBRE_TI + "&panneau=p1");
    const mp = await demo("/tableau/demo/mp?membre=" + MEMBRE_TI);
    const ok = !!e && !!c && r.ok === true && String(r.confirmation || "").includes("Es-tu sûr") && (mp.messages || []).length === 0;
    return { ok, detail: `clan ${e && e.familles.clan.etat} · bloc ${c && c.etat} · p1 : ${r.ok} · MP ${(mp.messages || []).length}` };
  });
}

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
    if (PARCOURS.includes("recrutement_zone")) await parcoursRecrutementZone(o);
    if (PARCOURS.includes("recrutement_decidees")) await parcoursDecidees(o);
    if (PARCOURS.includes("capitainerie")) await parcoursCapitainerie(o);
    if (PARCOURS.includes("metiers")) await parcoursMetiers(o);
    if (PARCOURS.includes("accueil")) await parcoursAccueil(o);
    if (PARCOURS.includes("recherche")) await parcoursRecherche(o);
    if (PARCOURS.includes("textes")) await parcoursTextes(o);
    if (PARCOURS.includes("navigation")) await parcoursNavigation(o);
    if (PARCOURS.includes("tickets_interdits")) await parcoursTicketsInterdits(o);
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
