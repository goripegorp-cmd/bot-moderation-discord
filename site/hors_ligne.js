// hors_ligne.js — la file des modifications faites sans réseau (IndexedDB « file_ops »), envoyée par POST sync
// au retour (en ligne, reprise de la page, toutes les 30 s). Chaque modification a son op_id : le serveur ne
// l'applique qu'une fois, même renvoyée. Conflit (409) : la page montre les deux versions et laisse choisir.
// Les saisies en cours (formulaires) sont aussi gardées (« saisies ») : un plantage ne perd rien.

import { uuid } from "./dom.js";
import { etat, emettre } from "./noyau.js";
import { poster } from "./api.js";

export const ROUTES_HORS_LIGNE = new Set([
  "rell/catalogue/element", "rell/catalogue/retirer", "rell/catalogue/type",
  "rell/affiche", "rell/affiche/retirer",
  "clan/brouillon",
  "recrutement/question", "recrutement/question/retirer", "recrutement/liens", "recrutement/reglages",
  "recrutement/corriger", "recrutement/modele", "recrutement/modele/retirer",
]);

const NOM_BASE = "capitainerie";
const VERSION_BASE = 1;
const LOT = 50;
let base = null;

export const file = { ops: [], enCours: false, dernierEssai: 0, dernierEnvoi: 0, memoireSeule: false };

const req = (r) => new Promise((ok, ko) => { r.onsuccess = () => ok(r.result); r.onerror = () => ko(r.error); });
const finTx = (t) => new Promise((ok, ko) => { t.oncomplete = () => ok(); t.onerror = () => ko(t.error); t.onabort = () => ko(t.error); });

export async function ouvrir() {
  if (!("indexedDB" in window)) { file.memoireSeule = true; emettre("file"); return; }
  try {
    base = await new Promise((ok, ko) => {
      const r = indexedDB.open(NOM_BASE, VERSION_BASE);
      r.onupgradeneeded = () => {
        const db = r.result;
        if (!db.objectStoreNames.contains("file_ops")) db.createObjectStore("file_ops", { keyPath: "op_id" });
        if (!db.objectStoreNames.contains("saisies")) db.createObjectStore("saisies", { keyPath: "cle" });
      };
      r.onsuccess = () => ok(r.result);
      r.onerror = () => ko(r.error);
      r.onblocked = () => ko(new Error("base bloquée"));
    });
    base.onversionchange = () => { base.close(); base = null; };
    const t = base.transaction("file_ops", "readonly");
    const toutes = await req(t.objectStore("file_ops").getAll());
    file.ops = toutes.map((o) => Object.assign(o, { envoi: false })).sort((a, b) => a.cree - b.cree);
  } catch (e) {
    base = null;
    file.memoireSeule = true; // navigation privée stricte : la file vit le temps de l'onglet
  }
  emettre("file");
}

async function persister(op) {
  if (!base) return;
  try {
    const t = base.transaction("file_ops", "readwrite");
    const { envoi, ...propre } = op;
    t.objectStore("file_ops").put(propre);
    await finTx(t);
  } catch (e) { file.memoireSeule = true; }
}
async function effacer(opId) {
  if (!base) return;
  try {
    const t = base.transaction("file_ops", "readwrite");
    t.objectStore("file_ops").delete(opId);
    await finTx(t);
  } catch (e) { /* elle repartira : le serveur reconnaîtra son op_id */ }
}

// ─── Compter ────────────────────────────────────────────────────────────────
export const enAttente = () => file.ops.filter((o) => o.etat === "attente");
export const enConflit = () => file.ops.filter((o) => o.etat === "conflit");
export const enRefus = () => file.ops.filter((o) => o.etat === "refus" || o.etat === "erreur");
export const opsDe = (genre, cle) => file.ops.filter((o) => o.genre === genre && String(o.cle) === String(cle));

// ─── Ajouter à la file ─────────────────────────────────────────────────────
/** Garde une modification et la montre tout de suite (objet optimiste). meta : { genre, cle, resume, objet, retrait }. */
export async function mettreEnFile(api, corps, meta = {}) {
  const { genre = "", cle = "", resume = "", objet = null, retrait = false } = meta;
  // Retirer un objet créé ici et jamais envoyé : sa création est simplement annulée.
  if (retrait && String(cle).startsWith("tmp-")) {
    const crees = file.ops.filter((o) => o.genre === genre && o.cle === cle && !o.envoi);
    if (crees.length && crees.length === opsDe(genre, cle).length) {
      for (const o of crees) await retirerOp(o, false);
      emettre("file");
      return null;
    }
  }
  // Une modification du même objet qui attend encore : on la remplace (une seule à envoyer).
  const pareille = !retrait && genre && cle !== ""
    ? file.ops.find((o) => o.genre === genre && String(o.cle) === String(cle) && o.api === api && o.etat === "attente" && !o.envoi)
    : null;
  if (pareille) {
    // L'objet affiché garde la version du serveur : la nouvelle saisie part sur la même base que la précédente.
    pareille.corps = corps;
    pareille.objet = objet;
    pareille.resume = resume || pareille.resume;
    pareille.maj = Date.now();
    await persister(pareille);
    emettre("file");
    planifierEnvoi();
    return pareille;
  }
  const op = { op_id: uuid(), api, corps, genre, cle: String(cle), resume, objet, cree: Date.now(), essais: 0, etat: "attente", envoi: false };
  file.ops.push(op);
  await persister(op);
  emettre("file");
  planifierEnvoi();
  return op;
}

async function retirerOp(op, prevenir = true) {
  file.ops = file.ops.filter((o) => o !== op);
  await effacer(op.op_id);
  if (prevenir) emettre("file");
}

let minuteurEnvoi = 0;
export function planifierEnvoi(delai = 60) {
  clearTimeout(minuteurEnvoi);
  minuteurEnvoi = setTimeout(() => { envoyer(); }, delai);
}

// ─── Envoyer ───────────────────────────────────────────────────────────────
export async function envoyer() {
  if (file.enCours || etat.session !== "ok") return { envoyees: 0 };
  const lot = enAttente().slice(0, LOT);
  if (!lot.length) return { envoyees: 0 };
  file.enCours = true;
  lot.forEach((o) => { o.envoi = true; });
  emettre("file");
  const rep = await poster("sync", { ops: lot.map((o) => ({ op_id: o.op_id, api: o.api, corps: o.corps })) });
  lot.forEach((o) => { o.envoi = false; });
  file.enCours = false;
  file.dernierEssai = Date.now();
  let envoyees = 0;
  if (rep.ok && rep.donnees && Array.isArray(rep.donnees.resultats)) {
    for (const res of rep.donnees.resultats) envoyees += (await traiter(res)) ? 1 : 0;
    file.dernierEnvoi = Date.now();
    emettre("file");
    if (enAttente().some((o) => o.essais === 0)) planifierEnvoi(400);
  } else {
    // Réseau absent, serveur tombé ou session expirée : tout reste dans la file, rien n'est perdu.
    emettre("file");
  }
  return { envoyees, erreur: rep.ok ? "" : rep.erreur };
}

function objetDe(corps) {
  if (!corps || typeof corps !== "object") return null;
  for (const k of ["affiche", "element", "brouillon", "question", "modele", "correction", "type"]) {
    const o = corps[k];
    if (o && typeof o === "object" && !Array.isArray(o)) return o;
  }
  return null;
}

async function traiter(res) {
  const op = file.ops.find((o) => o.op_id === res.op_id);
  if (!op) return false;
  const st = Number(res.status) || 0;
  const corps = res.corps || {};
  if (st >= 200 && st < 300 && corps.ok !== false) {
    const obj = objetDe(corps);
    // Les modifications suivantes du même objet partent sur la nouvelle version (et le vrai identifiant).
    for (const o of file.ops) {
      if (o === op || o.genre !== op.genre || String(o.cle) !== String(op.cle) || !o.corps) continue;
      if (obj && obj.version !== undefined && "version" in o.corps) o.corps.version = obj.version;
      if (obj && obj.id !== undefined && String(op.cle).startsWith("tmp-")) { o.corps.id = obj.id; o.cle = String(obj.id); }
      await persister(o);
    }
    await retirerOp(op, false);
    emettre("file:succes", { op, corps, objet: obj });
    return true;
  }
  if (st === 409) {
    op.etat = "conflit";
    op.conflit = corps.actuelle || null;
    op.conflitGenre = corps.doublon ? "doublon" : corps.retiree ? "retiree" : corps.publie ? "publie" : "version";
    op.conflitDetail = corps.doublon || corps.retiree || null;
    op.erreur = corps.erreur || "";
    await persister(op);
    emettre("file:conflit", { op });
    return false;
  }
  if (st === 423) { // en cours de modification par quelqu'un d'autre (direct.js) : elle attend, et repart quand c'est libre
    op.verrou = corps.verrou || { objet: "", nom: "" };
    op.erreur = corps.erreur || "";
    await persister(op);
    emettre("file:verrou", { op });
    return false;
  }
  if (st === 429) { // trop d'écritures d'un coup : elle repartira au prochain passage
    op.essais += 1;
    await persister(op);
    planifierEnvoi(30000);
    return false;
  }
  if (st >= 400 && st < 500) {
    op.etat = "refus";
    op.erreur = (corps.erreur || corps.message || "Refusé par le serveur.") + (corps.champ ? " (" + corps.champ + ")" : "");
    await persister(op);
    emettre("file:refus", { op });
    return false;
  }
  op.essais += 1;
  if (op.essais >= 6) { op.etat = "erreur"; op.erreur = "Le serveur n'a pas pu l'enregistrer après plusieurs essais."; }
  await persister(op);
  return false;
}

// ─── Régler un conflit, abandonner une modification ────────────────────────
/** Garder la version enregistrée : la modification locale est abandonnée. */
export async function garderServeur(op) {
  await retirerOp(op);
  emettre("file:succes", { op, corps: {}, objet: null, abandon: true });
}
/** Envoyer ma version (fusionnée), sur la version actuelle du serveur. Après un conflit ou un refus, c'est une
 *  NOUVELLE opération (nouvel op_id) : le serveur a déjà rendu son verdict sur l'ancienne et le redonnerait. */
export async function renvoyer(op, corps, objet) {
  if (op.etat === "conflit" || op.etat === "refus") {
    await effacer(op.op_id);
    op.op_id = uuid();
  }
  op.corps = corps;
  if (objet) op.objet = objet;
  op.etat = "attente";
  op.conflit = null;
  op.erreur = "";
  op.essais = 0;
  await persister(op);
  emettre("file");
  planifierEnvoi(30);
}
export const abandonner = (op) => retirerOp(op);

// ─── Saisies en cours (formulaires) ─────────────────────────────────────────
const saisiesMemoire = new Map();
export async function garderSaisie(cle, valeur) {
  const v = { cle, valeur, maj: Date.now() };
  saisiesMemoire.set(cle, v);
  if (!base) return;
  try { const t = base.transaction("saisies", "readwrite"); t.objectStore("saisies").put(v); await finTx(t); } catch (e) { /* mémoire seule */ }
}
export async function lireSaisie(cle) {
  if (base) {
    try { const t = base.transaction("saisies", "readonly"); const v = await req(t.objectStore("saisies").get(cle)); if (v) return v; } catch (e) { /* mémoire */ }
  }
  return saisiesMemoire.get(cle) || null;
}
export async function oublierSaisie(cle) {
  saisiesMemoire.delete(cle);
  if (!base) return;
  try { const t = base.transaction("saisies", "readwrite"); t.objectStore("saisies").delete(cle); await finTx(t); } catch (e) { /* rien */ }
}

// ─── Tout effacer (déconnexion) ─────────────────────────────────────────────
export async function toutEffacer() {
  file.ops = [];
  saisiesMemoire.clear();
  if (base) { base.close(); base = null; }
  await new Promise((ok) => {
    try {
      const r = indexedDB.deleteDatabase(NOM_BASE);
      r.onsuccess = r.onerror = r.onblocked = () => ok();
    } catch (e) { ok(); }
  });
  emettre("file");
}
