// outils/parcours_annonces.mjs — le parcours complet de l'onglet « Annonces & événements » (Clan GoRP), de vrais gestes
// dans un Edge ou un Chrome SANS FENÊTRE (protocole DevTools, aucune dépendance, Node 22+), l'état relu par l'API après
// chaque geste : composer un événement (date et heure de PARIS, l'appareil réglé sur New York), le brouillon, le rouvrir,
// le publier, le modifier (lieu puis horaire), actualiser sa carte, l'annuler ; une annonce avec image, publiée puis
// retirée ; l'annonce des métiers (aperçu du serveur) ; un listing supprimé ; un modèle ; un brouillon fait hors ligne.
// Échoue sur une erreur de console, une valeur absente affichée (undefined, null, NaN, [object Object]) ou un état
// du serveur qui ne correspond pas au geste. Captures (PNG) à chaque étape.
//
// Lancer (le vrai site local d'abord : python outils/site_local.py --port 8793) :
//   node outils/parcours_annonces.mjs [--base http://localhost:8793] [--entree /tableau/demo] [--sortie <dossier>]
//   La maquette (python outils/site_maquette.py --port 8797) : --base http://localhost:8797 --entree /tableau/espace/
//   (elle seule éprouve aussi la publication « incertaine », par sa bascule /maquette/incertain).
//   Sous Git Bash, un argument « /tableau/… » est réécrit en chemin Windows : préfixer la commande de MSYS_NO_PATHCONV=1.

import { spawn } from "node:child_process";
import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync, existsSync, rmSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const args = process.argv.slice(2);
const opt = (nom, defaut) => { const i = args.indexOf("--" + nom); return i >= 0 ? (args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : true) : defaut; };
const BASE = String(opt("base", "http://localhost:8793")).replace(/\/$/, "");
const ENTREE = String(opt("entree", "/tableau/demo"));
const ESPACE = BASE + "/tableau/espace/";
const SORTIE = String(opt("sortie", join(tmpdir(), "parcours-annonces")));
const FUSEAU = String(opt("fuseau", "America/New_York"));
const PORT = 9739 + Math.floor(Math.random() * 400);
const NAVIGATEURS = [opt("navigateur", ""), process.env.CHROME || "",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Microsoft/EdgeCore/155.0.4283.62/msedge.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].filter(Boolean);
const pause = (ms) => new Promise((ok) => setTimeout(ok, ms));
const N = Date.now().toString(36).slice(-4);

// ─── Le protocole DevTools (comme outils/controle_site.mjs) ─────────────────
let ws, prochainId = 1;
const attente = new Map();
const ecouteurs = [];
function envoyer(methode, params = {}, sessionId) {
  const id = prochainId++;
  ws.send(JSON.stringify({ id, method: methode, params, sessionId }));
  return new Promise((ok, ko) => attente.set(id, { ok, ko, methode }));
}
async function lancerNavigateur() {
  const exe = NAVIGATEURS.find((p) => existsSync(p));
  if (!exe) throw new Error("Aucun Chrome ni Edge trouvé (option --navigateur <exe>).");
  const profil = mkdtempSync(join(tmpdir(), "parcours-profil-"));
  const proc = spawn(exe, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profil}`, "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-sync", "--disable-features=Translate,MediaRouter,OptimizationHints", "--lang=fr-FR", "about:blank"], { stdio: "ignore" });
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); if (r.ok) return { proc, profil, exe, wsUrl: (await r.json()).webSocketDebuggerUrl }; } catch (e) { /* pas encore */ }
    await pause(250);
  }
  throw new Error("Le navigateur ne répond pas sur le port " + PORT);
}
async function connecter(wsUrl) {
  ws = new WebSocket(wsUrl);
  await new Promise((ok, ko) => { ws.onopen = ok; ws.onerror = ko; });
  ws.onmessage = (m) => {
    const d = JSON.parse(typeof m.data === "string" ? m.data : m.data.toString());
    if (d.id && attente.has(d.id)) { const a = attente.get(d.id); attente.delete(d.id); if (d.error) a.ko(new Error(a.methode + " : " + d.error.message)); else a.ok(d.result); }
    else if (d.method) for (const f of ecouteurs) f(d);
  };
}
async function nouvelOnglet() {
  const { targetId } = await envoyer("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await envoyer("Target.attachToTarget", { targetId, flatten: true });
  const s = (m, p) => envoyer(m, p, sessionId);
  for (const m of ["Page.enable", "Runtime.enable", "Log.enable", "Network.enable", "DOM.enable"]) await s(m);
  return { s, sessionId };
}
async function evaluer(o, expression, geste) {
  const r = await o.s("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true, userGesture: !!geste });
  if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description || r.exceptionDetails.text || "").split("\n")[0]);
  return r.result.value;
}

// ─── Les gestes dans la page ────────────────────────────────────────────────
const AIDE = `(() => {
  const vis = (el) => !!el && el.getClientRects().length > 0;
  const racine = () => [...document.querySelectorAll('dialog[open]')].pop() || document;
  const net = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  window.__p = {
    bouton(texte, o = {}) {
      const r = o.dans ? document.querySelector(o.dans) : racine();
      const l = [...r.querySelectorAll('button, a.bouton')].filter((b) => vis(b));
      return l.find((b) => o.exact ? net(b.textContent) === texte : net(b.textContent).includes(texte));
    },
    clic(texte, o = {}) { const b = this.bouton(texte, o); if (!b) throw new Error('bouton absent : ' + texte); if (b.disabled) throw new Error('bouton désactivé : ' + texte); b.click(); return 1; },
    saisir(sel, valeur) {
      const e = document.querySelector(sel); if (!e) throw new Error('champ absent : ' + sel);
      const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, valeur);
      e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); return 1;
    },
    carte(titre) { return [...document.querySelectorAll('article.evt-carte')].find((a) => net(a.querySelector('h3') && a.querySelector('h3').textContent) === titre); },
    clicCarte(titre, texte) {
      const a = this.carte(titre); if (!a) throw new Error('carte absente : ' + titre);
      const b = [...a.querySelectorAll('button, a.bouton')].find((x) => net(x.textContent).includes(texte)); if (!b) throw new Error('geste absent sur la carte : ' + texte);
      if (b.disabled) throw new Error('geste désactivé : ' + texte); b.click(); return 1;
    },
    interrupteur(texte, voulu) {
      const l = [...document.querySelectorAll('label.interrupteur, label.case')].find((x) => net(x.textContent).includes(texte)); if (!l) throw new Error('interrupteur absent : ' + texte);
      const i = l.querySelector('input'); if (i.checked !== voulu) i.click(); return i.checked;
    },
    async choisir(label, option) {
      const b = [...document.querySelectorAll('button.liste-bouton')].find((x) => x.getAttribute('aria-label') === label); if (!b) throw new Error('liste absente : ' + label);
      b.click(); await new Promise((r) => setTimeout(r, 250));
      const o = [...document.querySelectorAll('.menu-pop [role=option]')].find((x) => net(x.textContent).startsWith(option)); if (!o) throw new Error('option absente : ' + option);
      o.click(); await new Promise((r) => setTimeout(r, 150)); return 1;
    },
    puce(groupe, texte) {
      const g = document.querySelector('[aria-label="' + groupe + '"]'); if (!g) throw new Error('groupe absent : ' + groupe);
      const b = [...g.querySelectorAll('button')].find((x) => net(x.textContent) === texte); if (!b) throw new Error('puce absente : ' + texte); b.click(); return b.getAttribute('aria-pressed');
    },
    radio(nom, valeur) { const i = document.querySelector('input[name="' + nom + '"][value="' + valeur + '"]'); if (!i) throw new Error('choix absent : ' + valeur); i.click(); return i.checked; },
    suspects() {
      const out = []; const m = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = m.nextNode(); n; n = m.nextNode()) {
        const t = n.nodeValue.trim(), mots = t.split(/[^A-Za-z]+/);
        if (['null', 'undefined', 'NaN', '[object Object]'].includes(t) || mots.includes('undefined') || mots.includes('NaN') || t.includes('[object Object]'))
          if (n.parentElement && n.parentElement.getClientRects().length) out.push(t.slice(0, 60));
      }
      return out;
    },
    toasts() { return [...document.querySelectorAll('#toasts .toast')].map((t) => net(t.textContent)); },
    statut() { const s = document.querySelector('.composeur-statut'); return s ? net(s.textContent) : ''; },
  };
  return 1;
})()`;

// ─── L'API, relue de l'extérieur ────────────────────────────────────────────
let cookie = "";
async function session() {
  const r = await fetch(BASE + "/tableau/demo", { redirect: "manual" });
  const c = (r.headers.getSetCookie ? r.headers.getSetCookie() : [r.headers.get("set-cookie") || ""]).find((x) => /=/.test(x || ""));
  cookie = c ? c.split(";")[0] : "";
}
async function api(nom, params) {
  const q = params ? "?" + new URLSearchParams(params) : "";
  const r = await fetch(BASE + "/tableau/espace/api/" + nom + q, { headers: cookie ? { Cookie: cookie } : {} });
  return { status: r.status, corps: await r.json().catch(() => ({})) };
}
/** Une écriture faite « ailleurs » (une autre page) : une opération rejouée par sync, comme le ferait la file. */
async function ecrire(nomApi, corps) {
  const r = await fetch(BASE + "/tableau/espace/sync", { method: "POST", body: JSON.stringify({ ops: [{ op_id: crypto.randomUUID(), api: nomApi, corps }] }),
    headers: Object.assign({ "Content-Type": "application/json", "X-Tableau": "1", Origin: BASE }, cookie ? { Cookie: cookie } : {}) });
  const res = ((await r.json().catch(() => ({}))).resultats || [])[0] || {};
  return { status: res.status || r.status, corps: res.corps || {} };
}
async function element(titre) {
  const { corps } = await api("clan/evenements");
  for (const liste of ["brouillons", "a_venir", "passes"]) for (const e of corps[liste] || []) if (e.titre === titre) return Object.assign({ _liste: liste }, e);
  return null;
}

// ─── L'heure de Paris (le calcul attendu, indépendant de la page) ───────────
function parisVersEpoch(a, m, j, H, M) {
  const f = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const voulu = Date.UTC(a, m - 1, j, H, M) / 1000;
  let t = voulu;
  for (let i = 0; i < 3; i++) {
    const p = Object.fromEntries(f.formatToParts(new Date(t * 1000)).filter((x) => x.type !== "literal").map((x) => [x.type, Number(x.value)]));
    const vu = Date.UTC(p.year, p.month - 1, p.day, p.hour % 24, p.minute) / 1000;
    if (vu === voulu) break;
    t += voulu - vu;
  }
  return t;
}
function jourParis(decalageJours) {
  const f = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" });
  return f.format(new Date(Date.now() + decalageJours * 86400000));
}

// ─── Le parcours ────────────────────────────────────────────────────────────
const etapes = [];
let erreurs = [];
// Les erreurs que le navigateur journalise et qu'une étape attend (un 502 voulu : « Discord n'a pas confirmé »).
const attendues = [];
function note(ok, texte, detail) {
  etapes.push({ ok: !!ok, texte, detail: detail || "" });
  console.log(`${ok ? "ok    " : "ÉCHEC "} ${texte}${detail && !ok ? " — " + detail : ""}`);
}
async function attendre(o, expression, max = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < max) {
    try { if (await evaluer(o, expression)) return true; } catch (e) { /* pas encore */ }
    await pause(150);
  }
  return false;
}
async function attendreServeur(cond, max = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < max) {
    const r = await cond();
    if (r) return r;
    await pause(250);
  }
  return null;
}
async function aller(o, ancre) {
  await o.s("Page.navigate", { url: ESPACE + ancre });
  await attendre(o, "!!document.querySelector('#contenu .titre-rubrique') && !document.querySelector('#contenu .squelette')", 12000);
  await pause(400);
  await evaluer(o, AIDE);
}
let nCapture = 0;
async function capture(o, nom) {
  const r = await o.s("Page.captureScreenshot", { format: "png" });
  const f = join(SORTIE, `${String(++nCapture).padStart(2, "0")}-${nom}.png`);
  writeFileSync(f, Buffer.from(r.data, "base64"));
  const suspects = await evaluer(o, "window.__p ? window.__p.suspects() : []").catch(() => []);
  if (suspects.length) note(false, "valeur absente affichée (" + nom + ")", suspects.slice(0, 4).join(" | "));
}
const g = (o, code, geste) => evaluer(o, "(async () => { " + code + " })()", geste);

/** Une vraie image PNG (dégradé), écrite sans dépendance : signature, IHDR, IDAT (zlib), IEND. */
function png(l, hh) {
  const crcT = Array.from({ length: 256 }, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = (b) => { let c = 0xffffffff; for (const x of b) c = crcT[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const bloc = (type, data) => { const t = Buffer.from(type, "ascii"), lg = Buffer.alloc(4), cr = Buffer.alloc(4); lg.writeUInt32BE(data.length); cr.writeUInt32BE(crc(Buffer.concat([t, data]))); return Buffer.concat([lg, t, data, cr]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(l, 0); ihdr.writeUInt32BE(hh, 4); ihdr[8] = 8; ihdr[9] = 2;
  const brut = Buffer.alloc((l * 3 + 1) * hh);
  for (let y = 0; y < hh; y++) for (let x = 0; x < l; x++) { const i = y * (l * 3 + 1) + 1 + x * 3; brut[i] = 31 + x % 120; brut[i + 1] = 78 + y % 90; brut[i + 2] = 90; }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), bloc("IHDR", ihdr), bloc("IDAT", deflateSync(brut)), bloc("IEND", Buffer.alloc(0))]);
}

async function parcours(o) {
  const J3 = jourParis(3);
  const [a, m, j] = J3.split("-").map(Number);
  const attendu = parisVersEpoch(a, m, j, 20, 45);
  const TITRE = "Essai parcours " + N + " : sortie du soir";

  // 1. Un événement composé sur un appareil réglé sur New York : l'heure saisie est celle de Paris.
  await aller(o, "#equipage/annonces/composer");
  await attendre(o, "!!document.querySelector('.composeur-form input[type=date]')");
  await g(o, `
    __p.saisir('.composeur-form input.saisie', ${JSON.stringify(TITRE)});
    __p.saisir('#composeur-texte', 'Rendez-vous au port **un quart d\\'heure avant**.\\n> Les absents passent leur tour.');
    __p.saisir('.composeur-form input[type=date]', ${JSON.stringify(J3)});
    __p.saisir('.composeur-form input[type=time]', '20:45');
    __p.saisir('.composeur-form input[placeholder="Port de l\\'île centrale"]', 'Île du Crâne');
    __p.puce('Rappels', '1 jour avant'); __p.puce('Rappels', 'Au début');
    __p.saisir('.composeur-form input[type=number]', '8');
    __p.radio('mention-evenement', 'clan');
    __p.interrupteur("Créer aussi l'évènement Discord", true);
    await __p.choisir('Durée', '2 h');
    return 1;`);
  const minuteur = await evaluer(o, "document.querySelector('.composeur-form .minuteur-vivant').textContent");
  const heureVue = await evaluer(o, "document.querySelector('.composeur-form input[type=time]').value");
  note(/20:45/.test(minuteur) && /heure de Paris/.test(minuteur) && heureVue === "20:45", "le minuteur du composeur lit l'heure de Paris (appareil sur " + FUSEAU + ")", minuteur);
  const apercuLocal = await evaluer(o, "document.querySelector('.apercu-discord-zone').innerText");
  note(apercuLocal.includes("20:45") && apercuLocal.includes("Île du Crâne") && apercuLocal.includes("8 places") && apercuLocal.includes("1 j, 1 h avant · before · au début"),
    "l'aperçu pendant la saisie suit la carte du serveur (heure, lieu, places, rappels)", apercuLocal.replace(/\s+/g, " ").slice(0, 300));
  await capture(o, "composeur-evenement");
  await g(o, "__p.clic('Enregistrer le brouillon'); return 1;");
  const b1 = await attendreServeur(() => element(TITRE));
  const v1 = b1 && b1.valeurs;
  note(b1 && b1.statut === "brouillon" && b1.quand === attendu && v1.lieu === "Île du Crâne" && JSON.stringify(v1.rappels) === "[1440,60,0]" && v1.places === 8
    && v1.mention === "clan" && v1.discord_event === true && v1.duree_min === 120 && v1.texte.includes("**un quart d'heure avant**"),
    "le brouillon est sur le serveur, champ par champ (début = " + new Date(attendu * 1000).toISOString() + ")", JSON.stringify(b1 && { quand: b1.quand, v: v1 }));
  const rendu = await attendre(o, "document.querySelector('.apercu-tete') && document.querySelector('.apercu-tete').textContent.includes('rendu du serveur')", 8000);
  note(rendu, "après l'enregistrement, l'aperçu est celui du serveur");
  await capture(o, "composeur-apercu-serveur");

  // 2. Rouvrir le brouillon depuis la liste, le modifier, l'enregistrer (le post choisi repart tel quel).
  await aller(o, "#equipage/annonces/brouillons");
  await g(o, `__p.clicCarte(${JSON.stringify(TITRE)}, 'Ouvrir'); return 1;`);
  await attendre(o, `(document.querySelector('.composeur-form input.saisie') || {}).value === ${JSON.stringify(TITRE)}`);
  await evaluer(o, AIDE);
  const relu = await evaluer(o, "({ jour: document.querySelector('.composeur-form input[type=date]').value, heure: document.querySelector('.composeur-form input[type=time]').value, places: document.querySelector('.composeur-form input[type=number]').value })");
  note(relu.jour === J3 && relu.heure === "20:45" && relu.places === "8", "rouvert, le composeur montre le jour et l'heure de Paris", JSON.stringify(relu));
  const TITRE2 = TITRE + " (modifié)";
  await g(o, `__p.saisir('.composeur-form input.saisie', ${JSON.stringify(TITRE2)}); __p.clic('Enregistrer le brouillon'); return 1;`);
  const b2 = await attendreServeur(async () => { const e = await element(TITRE2); return e && e.version > b1.version ? e : null; });
  note(b2 && b2.id === b1.id, "le brouillon rouvert s'enregistre (même élément, nouvelle version)", JSON.stringify(b2 && { id: b2.id, version: b2.version }));
  const refus = await evaluer(o, "__p.statut()");
  note(!/refusé/i.test(refus), "aucun refus du serveur dans le composeur", refus);

  // 2 bis. Le même brouillon modifié ailleurs pendant qu'on l'édite ici : le conflit se règle champ par champ.
  const avantC = await element(TITRE2);
  const ailleurs = await ecrire("clan/brouillon", { id: avantC.id, version: avantC.version, type: "evenement", lieu: "Modifié ailleurs" });
  note(ailleurs.status === 200, "le brouillon est modifié ailleurs (une autre page)", JSON.stringify(ailleurs));
  await g(o, "__p.saisir('#composeur-texte', 'Texte écrit ici pendant ce temps.'); __p.clic('Enregistrer le brouillon'); return 1;");
  const conflit = await attendre(o, "/conflit/i.test(__p.statut())", 8000);
  note(conflit, "le composeur annonce le conflit", await evaluer(o, "__p.statut()"));
  await g(o, "document.querySelector('#plaque-etat').click(); return 1;");
  await attendre(o, "!!__p.bouton('Régler le conflit')", 5000);
  await g(o, "__p.clic('Régler le conflit'); return 1;");
  await attendre(o, "[...document.querySelectorAll('dialog[open]')].pop().textContent.includes('Ma version')", 5000);
  const fenetre = await evaluer(o, "[...document.querySelectorAll('dialog[open]')].pop().innerText");
  note(/Texte/.test(fenetre) && /Lieu/.test(fenetre) && !/Post/.test(fenetre) && !/\{"id"|object Object/.test(fenetre),
    "la fenêtre du conflit montre les deux versions des seuls champs changés (texte, lieu)", fenetre.replace(/\s+/g, " ").slice(0, 300));
  await capture(o, "conflit-brouillon");
  // Mon texte, et le lieu changé ailleurs.
  await g(o, `const d = [...document.querySelectorAll('dialog[open]')].pop();
    [...d.querySelectorAll('fieldset.conflit-champ')].find((x) => x.querySelector('legend').textContent === 'Lieu').querySelector('input[value=serveur]').click();
    [...d.querySelectorAll('button')].find((b) => b.textContent.includes('Envoyer ce choix')).click(); return 1;`);
  const regle = await attendreServeur(async () => { const e = await element(TITRE2); return e && e.valeurs.texte === "Texte écrit ici pendant ce temps." && e.valeurs.lieu === "Modifié ailleurs" ? e : null; });
  note(!!regle, "après le choix, le serveur a mon texte et le lieu gardé d'ailleurs", JSON.stringify(regle && regle.valeurs));
  await pause(600);
  await g(o, "for (const d of document.querySelectorAll('dialog[open]')) { const b = [...d.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Fermer'); if (b) b.click(); } return 1;");
  const lieuVu = await attendre(o, "(document.querySelector('.composeur-form input[placeholder=\"Port de l\\'île centrale\"]') || {}).value === 'Modifié ailleurs'", 6000);
  note(lieuVu, "le composeur montre la version réglée (le lieu venu d'ailleurs)");
  await pause(400);
  await evaluer(o, AIDE);

  // 3. Publier : la confirmation dit le post, l'heure de Paris, la mention.
  await g(o, "__p.clic('Publier…'); return 1;");
  const dlg = await attendre(o, "!!document.querySelector('dialog[open]') && document.querySelector('dialog[open]').textContent.includes('Publier « ')", 10000);
  const texteDlg = dlg ? await evaluer(o, "document.querySelector('dialog[open]').innerText") : "";
  note(dlg && texteDlg.includes("Infos · Info") && texteDlg.includes("20:45") && texteDlg.includes("heure de Paris") && /Le clan .* est mentionné/.test(texteDlg),
    "la confirmation dit où, quand (Paris) et qui est mentionné", texteDlg.replace(/\s+/g, " ").slice(0, 300));
  await capture(o, "confirmation-publier");
  await g(o, "__p.clic('Publier', { exact: true }); return 1;");
  const p1 = await attendreServeur(async () => { const e = await element(TITRE2); return e && e.statut === "publie" ? e : null; }, 10000);
  note(p1 && p1.lien && p1.discord_event && p1.discord_event.lien && p1.quand === attendu, "publié : la carte est partie, l'évènement Discord est créé", JSON.stringify(p1 && { lien: p1.lien, de: p1.discord_event }));
  const surAVenir = await attendre(o, `location.hash.includes('a-venir') && !!__p.carte(${JSON.stringify(TITRE2)})`, 10000);
  note(surAVenir, "la page passe dans « À venir », où l'événement est listé");
  await evaluer(o, AIDE);
  const carteTexte = await evaluer(o, `(__p.carte(${JSON.stringify(TITRE2)}) || {}).textContent || ''`);
  note(/0 \/ 8 places/.test(carteTexte) && /Sur Discord/.test(carteTexte) && /Évènement Discord/.test(carteTexte) && /Publié .+ par \S/.test(carteTexte),
    "la carte de la liste : places, liens, auteur", carteTexte.replace(/\s+/g, " ").slice(0, 300));
  await capture(o, "a-venir-publie");

  // 4. Modifier une publication : le lieu, puis l'horaire (confirmation, les disponibles prévenus).
  await g(o, `__p.clicCarte(${JSON.stringify(TITRE2)}, 'Modifier'); return 1;`);
  await attendre(o, `(document.querySelector('.composeur-form input.saisie') || {}).value === ${JSON.stringify(TITRE2)}`);
  await evaluer(o, AIDE);
  const verrous = await evaluer(o, "({ type: [...document.querySelectorAll('.choix-type')].every((b) => b.disabled), post: document.querySelector('button.liste-bouton[aria-label=\"Où publier\"]').disabled, bouton: !!__p.bouton('Enregistrer sur Discord') })");
  note(verrous.type && verrous.post && verrous.bouton, "une publication rouverte : type et post figés, « Enregistrer sur Discord »", JSON.stringify(verrous));
  await g(o, "__p.saisir('.composeur-form input[placeholder=\"Port de l\\'île centrale\"]', 'Fosse des abysses'); __p.clic('Enregistrer sur Discord'); return 1;");
  const m1 = await attendreServeur(async () => { const e = await element(TITRE2); return e && e.valeurs.lieu === "Fosse des abysses" ? e : null; });
  note(m1 && m1.statut === "publie" && m1.version > p1.version, "le lieu modifié est sur Discord (publication toujours en ligne)", JSON.stringify(m1 && { v: m1.version, lieu: m1.valeurs.lieu }));
  const attendu2 = parisVersEpoch(a, m, j, 21, 30);
  await evaluer(o, AIDE);
  await g(o, "__p.saisir('.composeur-form input[type=time]', '21:30'); __p.clic('Enregistrer sur Discord'); return 1;");
  const dlg2 = await attendre(o, "!!document.querySelector('dialog[open]') && document.querySelector('dialog[open]').textContent.includes('Changer l')", 6000);
  note(dlg2, "changer l'horaire demande confirmation");
  if (dlg2) await g(o, "__p.clic('Enregistrer sur Discord'); return 1;");
  const m2 = await attendreServeur(async () => { const e = await element(TITRE2); return e && e.quand === attendu2 ? e : null; });
  note(!!m2, "le nouvel horaire (21:30, heure de Paris) est enregistré", JSON.stringify(m2 && { quand: m2.quand, attendu: attendu2 }));
  await capture(o, "modifier-publie");

  // 5. Actualiser la carte, puis annuler l'événement.
  await aller(o, "#equipage/annonces/a-venir");
  const avantAct = (await element(TITRE2)).version;
  await g(o, `__p.clicCarte(${JSON.stringify(TITRE2)}, 'Actualiser la carte'); return 1;`);
  const act = await attendreServeur(async () => { const e = await element(TITRE2); return e && e.version > avantAct ? e : null; });
  note(!!act, "« Actualiser la carte » réécrit la carte (nouvelle version)");
  await evaluer(o, AIDE);
  await g(o, `__p.clicCarte(${JSON.stringify(TITRE2)}, "Annuler l'événement"); return 1;`);
  await attendre(o, "!!document.querySelector('dialog[open]')");
  await capture(o, "confirmation-annuler");
  await g(o, "__p.clic(\"Annuler l'événement\", { exact: true }); return 1;");
  const an = await attendreServeur(async () => { const e = await element(TITRE2); return e && e.statut === "annule" ? e : null; });
  note(an && an._liste === "passes", "annulé : l'événement passe dans « Passés »", JSON.stringify(an && { statut: an.statut, liste: an._liste }));
  await aller(o, "#equipage/annonces/passes");
  await attendre(o, `!!__p.carte(${JSON.stringify(TITRE2)})`, 8000);
  const carteAnnulee = await evaluer(o, `(__p.carte(${JSON.stringify(TITRE2)}) || {}).textContent || ''`);
  note(/Annulé/.test(carteAnnulee) && /· annulé/.test(carteAnnulee) && !/dans \d/.test(carteAnnulee) && /Refaire/.test(carteAnnulee) && !/Modifier/.test(carteAnnulee),
    "dans « Passés », un événement annulé le dit (pas de minuteur), « Refaire » seulement", carteAnnulee.replace(/\s+/g, " ").slice(0, 300));
  await capture(o, "passes-annule");

  // 6. Une annonce avec une image (fichier choisi sur l'appareil), publiée puis retirée.
  const ANNONCE = "Essai parcours " + N + " : annonce";
  await aller(o, "#equipage/annonces/composer");
  await g(o, "__p.clic('Nouveau'); return 1;");
  await pause(300);
  if (await evaluer(o, "!!document.querySelector('dialog[open]')")) await g(o, "__p.clic('Repartir de zéro', { exact: true }); return 1;");
  await pause(400);
  await evaluer(o, AIDE);
  await g(o, "[...document.querySelectorAll('.choix-type')].find((b) => b.textContent.includes('Annonce')).click(); return 1;");
  await pause(300);
  await evaluer(o, AIDE);
  await g(o, `__p.saisir('.composeur-form input.saisie', ${JSON.stringify(ANNONCE)}); __p.saisir('#composeur-texte', 'Le **Movie 3** est là.'); __p.radio('mention-annonce', 'clan'); return 1;`);
  const image = join(SORTIE, "image-essai.png");
  writeFileSync(image, png(480, 180));
  await o.s("Page.setInterceptFileChooserDialog", { enabled: true });
  const choisi = new Promise((ok) => { const f = (d) => { if (d.method === "Page.fileChooserOpened") { ecouteurs.splice(ecouteurs.indexOf(f), 1); ok(d.params); } }; ecouteurs.push(f); });
  await g(o, "__p.clic('Ajouter une image'); return 1;", true);
  const fc = await Promise.race([choisi, pause(5000).then(() => null)]);
  if (fc) await o.s("DOM.setFileInputFiles", { files: [image], backendNodeId: fc.backendNodeId });
  await o.s("Page.setInterceptFileChooserDialog", { enabled: false });
  const imgOk = await attendre(o, "!!document.querySelector('.image-choix img') && document.querySelector('.image-choix img').naturalWidth > 0", 10000);
  note(fc && imgOk, "l'image choisie sur l'appareil est envoyée (api/media) et affichée");
  await g(o, "__p.clic('Publier…'); return 1;");
  await attendre(o, "!!document.querySelector('dialog[open]') && document.querySelector('dialog[open]').textContent.includes('Publier « ')", 10000);
  await g(o, "__p.clic('Publier', { exact: true }); return 1;");
  const pa = await attendreServeur(async () => { const e = await element(ANNONCE); return e && e.statut === "publie" ? e : null; }, 10000);
  note(pa && pa.valeurs.image && pa._liste === "passes", "l'annonce est publiée avec son image (elle est rangée dans « Passés »)", JSON.stringify(pa && { image: pa.valeurs.image, liste: pa._liste }));
  const surPasses = await attendre(o, `location.hash.includes('passes') && !!__p.carte(${JSON.stringify(ANNONCE)})`, 10000);
  const carteAnnonce = await evaluer(o, `(__p.carte(${JSON.stringify(ANNONCE)}) || {}).textContent || ''`);
  note(surPasses && /Personne ne l'a encore marquée/.test(carteAnnonce) && /Retirer/.test(carteAnnonce) && /Modifier/.test(carteAnnonce),
    "après publication, la page montre l'annonce dans « Passés » : « Vu », Modifier, Retirer", carteAnnonce.replace(/\s+/g, " ").slice(0, 300));
  await capture(o, "passes-annonce");
  await g(o, `__p.clicCarte(${JSON.stringify(ANNONCE)}, 'Retirer'); return 1;`);
  await attendre(o, "!!document.querySelector('dialog[open]')");
  await g(o, "__p.clic('Retirer', { exact: true }); return 1;");
  const ra = await attendreServeur(async () => { const e = await element(ANNONCE); return e && e.statut === "retire" ? e : null; });
  note(!!ra, "l'annonce est retirée du post");

  // 6 bis. Sur la maquette (sa bascule /maquette/incertain) : Discord ne confirme pas l'envoi → « Publication
  // incertaine », puis « Forcer la publication » (la version a changé entre-temps : la page la relit).
  const surMaquette = await fetch(BASE + "/maquette/etat").then((r) => r.ok).catch(() => false);
  if (surMaquette) {
    const INCERTAINE = "Essai parcours " + N + " : incertaine";
    await aller(o, "#equipage/annonces/composer");
    await g(o, "[...document.querySelectorAll('.choix-type')].find((b) => b.textContent.includes('Annonce')).click(); return 1;");
    await pause(300);
    await evaluer(o, AIDE);
    await g(o, `__p.saisir('.composeur-form input.saisie', ${JSON.stringify(INCERTAINE)}); __p.saisir('#composeur-texte', 'Texte.'); __p.clic('Enregistrer le brouillon'); return 1;`);
    await attendreServeur(() => element(INCERTAINE));
    await fetch(BASE + "/maquette/incertain?etat=1");
    attendues.push(/status of 502 .*clan\/publier/);
    await g(o, "__p.clic('Publier…'); return 1;");
    await attendre(o, "!!document.querySelector('dialog[open]') && document.querySelector('dialog[open]').textContent.includes('Publier « ')", 10000);
    await g(o, "__p.clic('Publier', { exact: true }); return 1;");
    const pancarte = await attendre(o, "[...document.querySelectorAll('dialog[open]')].some((d) => d.textContent.includes('Publication incertaine'))", 8000);
    const inc = await element(INCERTAINE);
    note(pancarte && inc && inc.statut === "incertain", "Discord ne confirme pas : la page le dit, l'élément est « incertain »", JSON.stringify(inc && inc.statut));
    await capture(o, "publication-incertaine");
    await g(o, "__p.clic('Forcer la publication'); return 1;");
    const forcee = await attendreServeur(async () => { const e = await element(INCERTAINE); return e && e.statut === "publie" ? e : null; }, 10000);
    note(!!forcee, "« Forcer la publication » publie (avec la version relue) ; la page n'est pas restée « hors ligne »");
  }

  // 7. L'annonce des métiers : pas de « Ranger par », l'aperçu du serveur montre les métiers des affiches.
  const METIERS = "Essai parcours " + N + " : les métiers";
  await aller(o, "#equipage/annonces/composer");
  await g(o, "[...document.querySelectorAll('.choix-type')].find((b) => b.textContent.includes('Les métiers')).click(); return 1;");
  await pause(300);
  await evaluer(o, AIDE);
  const sansRanger = await evaluer(o, "!document.querySelector('.composeur-form [aria-label=\"Ranger par\"]')");
  note(sansRanger, "l'annonce des métiers se range par métier (aucun autre choix proposé)");
  await g(o, `__p.saisir('.composeur-form input.saisie', ${JSON.stringify(METIERS)}); __p.clic('Enregistrer le brouillon'); return 1;`);
  const bm = await attendreServeur(() => element(METIERS));
  // Un groupe par métier (« Navigation — 1 »), puis ses membres mentionnés (@nom) : le rendu du serveur.
  const renduM = await attendre(o, "document.querySelector('.apercu-tete').textContent.includes('rendu du serveur') && [...document.querySelectorAll('.discord .discord-ligne.h3')].some((l) => / — \\d+$/.test(l.textContent.trim())) && !!document.querySelector('.discord .md-mention')", 10000);
  note(bm && renduM, "l'aperçu du serveur liste les métiers d'après les affiches");
  await capture(o, "metiers-apercu-serveur");
  await g(o, "__p.clic('Publier…'); return 1;");
  await attendre(o, "!!document.querySelector('dialog[open]') && document.querySelector('dialog[open]').textContent.includes('Publier « ')", 10000);
  await g(o, "__p.clic('Publier', { exact: true }); return 1;");
  const pm = await attendreServeur(async () => { const e = await element(METIERS); return e && e.statut === "publie" ? e : null; }, 10000);
  note(!!pm, "l'annonce des métiers est publiée");

  // 8. Un listing rangé par race, enregistré, puis supprimé depuis les brouillons.
  const LISTING = "Essai parcours " + N + " : le listing";
  await aller(o, "#equipage/annonces/composer");
  await g(o, "[...document.querySelectorAll('.choix-type')].find((b) => b.textContent.includes('Le listing')).click(); return 1;");
  await pause(300);
  await evaluer(o, AIDE);
  await g(o, `__p.saisir('.composeur-form input.saisie', ${JSON.stringify(LISTING)});
    [...document.querySelector('.composeur-form [aria-label="Ranger par"]').querySelectorAll('button')].find((b) => b.textContent === 'Race').click(); return 1;`);
  await pause(300);
  await evaluer(o, AIDE);
  const casesListing = await evaluer(o, "[...document.querySelectorAll('.composeur-form label.case')].map((l) => l.textContent.trim())");
  note(JSON.stringify(casesListing) === JSON.stringify(["Métiers", "Grade"]), "rangé par race : « Race » n'est plus à cocher pour chacun", JSON.stringify(casesListing));
  await g(o, "__p.clic('Enregistrer le brouillon'); return 1;");
  const bl = await attendreServeur(() => element(LISTING));
  note(bl && bl.valeurs.groupement === "race", "le listing rangé par race est enregistré", JSON.stringify(bl && bl.valeurs));
  await aller(o, "#equipage/annonces/brouillons");
  await g(o, `__p.clicCarte(${JSON.stringify(LISTING)}, 'Supprimer'); return 1;`);
  await attendre(o, "!!document.querySelector('dialog[open]')");
  await g(o, "__p.clic('Supprimer', { exact: true }); return 1;");
  const parti = await attendreServeur(async () => ((await element(LISTING)) ? null : true));
  note(!!parti, "le brouillon supprimé n'est plus sur le serveur");
  await capture(o, "brouillons");

  // 9. Partir d'un modèle.
  await aller(o, "#equipage/annonces/composer");
  await evaluer(o, AIDE);
  await g(o, "await __p.choisir('Partir d\\'un modèle', 'Entraînement'); return 1;");
  await pause(400);
  const MODELE = "Essai parcours " + N + " : entraînement";
  await evaluer(o, AIDE);
  await g(o, `__p.saisir('.composeur-form input.saisie', ${JSON.stringify(MODELE)}); __p.clic('Enregistrer le brouillon'); return 1;`);
  const bmo = await attendreServeur(() => element(MODELE));
  note(bmo && bmo.valeurs.places === 10 && JSON.stringify(bmo.valeurs.rappels) === "[60,10]" && bmo.valeurs.duree_min === 90,
    "le modèle « Entraînement » remplit places, rappels et durée", JSON.stringify(bmo && bmo.valeurs));

  // 10. Un brouillon fait hors ligne part au retour de la connexion.
  const HL = "Essai parcours " + N + " : hors ligne";
  await g(o, "__p.clic('Nouveau'); return 1;");
  await pause(300);
  if (await evaluer(o, "!!document.querySelector('dialog[open]')")) await g(o, "__p.clic('Repartir de zéro', { exact: true }); return 1;");
  await pause(300);
  await o.s("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await evaluer(o, "window.dispatchEvent(new Event('offline')); 1");
  await evaluer(o, AIDE);
  await g(o, `__p.saisir('.composeur-form input.saisie', ${JSON.stringify(HL)}); __p.clic('Enregistrer le brouillon'); return 1;`);
  await pause(1200);
  const garde = await evaluer(o, "__p.statut()");
  note(/gardé sur cet appareil/i.test(garde), "hors ligne, le brouillon est gardé sur l'appareil", garde);
  await capture(o, "hors-ligne-brouillon");
  await o.s("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await evaluer(o, "window.dispatchEvent(new Event('online')); 1");
  const arrive = await attendreServeur(() => element(HL), 15000);
  note(!!arrive, "au retour de la connexion, le brouillon est sur le serveur");
}

async function principal() {
  mkdirSync(SORTIE, { recursive: true });
  await session();
  const nav = await lancerNavigateur();
  console.log("Navigateur : " + nav.exe + "\nSite : " + BASE + "\nCaptures : " + SORTIE);
  try {
    await connecter(nav.wsUrl);
    ecouteurs.push((d) => {
      if (d.method === "Runtime.exceptionThrown") erreurs.push("exception : " + (d.params.exceptionDetails.exception && d.params.exceptionDetails.exception.description || d.params.exceptionDetails.text));
      else if (d.method === "Runtime.consoleAPICalled" && (d.params.type === "error" || d.params.type === "assert")) erreurs.push("console : " + d.params.args.map((x) => x.value ?? x.description ?? "").join(" "));
      else if (d.method === "Log.entryAdded" && d.params.entry.level === "error" && !/net::ERR_INTERNET_DISCONNECTED|Failed to fetch/.test(d.params.entry.text || "")) {
        const texte = d.params.entry.text + (d.params.entry.url ? " (" + d.params.entry.url + ")" : "");
        if (!attendues.some((re) => re.test(texte))) erreurs.push("journal : " + texte);
      }
    });
    const o = await nouvelOnglet();
    await o.s("Emulation.setTimezoneOverride", { timezoneId: FUSEAU });
    await o.s("Emulation.setDeviceMetricsOverride", { width: 1366, height: 900, deviceScaleFactor: 1, mobile: false });
    await o.s("Page.navigate", { url: BASE + ENTREE });
    await pause(1500);
    try { await parcours(o); } catch (e) { note(false, "parcours interrompu", e.message); try { await capture(o, "interrompu"); } catch (x) { /* rien */ } }
  } finally {
    try { await envoyer("Browser.close"); } catch (e) { /* déjà fermé */ }
    await pause(400);
    try { nav.proc.kill(); } catch (e) { /* rien */ }
    try { rmSync(nav.profil, { recursive: true, force: true }); } catch (e) { /* le profil temporaire reste */ }
  }
  const vues = [...new Set(erreurs)].filter((e) => !/ERR_INTERNET_DISCONNECTED|Failed to fetch|net::ERR/.test(e));
  for (const e of vues.slice(0, 10)) note(false, "erreur de la page", e);
  const echecs = etapes.filter((e) => !e.ok);
  writeFileSync(join(SORTIE, "parcours.json"), JSON.stringify({ base: BASE, etapes, erreurs: vues }, null, 1));
  console.log(`\n${etapes.length} vérification(s), ${echecs.length} en échec.`);
  if (echecs.length) process.exitCode = 1;
}
principal().catch((e) => { console.error("Parcours interrompu : " + e.message); process.exitCode = 2; });
