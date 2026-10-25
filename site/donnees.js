// donnees.js — les jeux de données chargés à la demande (catalogue, affiches, rôles, événements, nettoyage,
// questionnaire, dossiers), gardés en mémoire, et la file hors ligne appliquée par-dessus (affichage optimiste).

import { lire } from "./api.js";
import { file } from "./hors_ligne.js";
import { emettre, ecouter, etat } from "./noyau.js";
import { copie } from "./dom.js";

const SOURCES = {
  catalogue: "rell/catalogue", affiches: "rell/affiches", roles: "rell/roles", evenements: "clan/evenements",
  nettoyage: "nettoyage", banque: "recrutement/banque", dossier: "recrutement/dossier", affiche: "rell/affiche",
  metiers_reglages: "rell/metiers/reglages",
};
const FRAIS = 45000;
//  Après un échec (adresse absente, serveur saturé, panne), on ne redemande pas avant une pause qui s'allonge ;
//  un nouvel essai part tout seul à la fin de la pause (6 au plus, puis seulement à la prochaine demande).
const PAUSES = [15000, 30000, 60000, 120000, 300000];
const REPRISES_MAX = 6;
const jeux = new Map();

const cleDe = (nom, params) => (params ? nom + ":" + new URLSearchParams(params).toString() : nom);

/** Charge (ou reprend en mémoire) un jeu de données ; renvoie la vue avec la file appliquée.
 *  « jeu » n'est annoncé que si quelque chose a CHANGÉ (données, état hors ligne, erreur) : la page qui se redessine
 *  à cette annonce redemande ses jeux ; annoncer à chaque chargement ferait une boucle sans fin sur un jeu en erreur. */
export async function charger(nom, { forcer = false, params = null } = {}) {
  const cle = cleDe(nom, params);
  let j = jeux.get(cle);
  if (!j) { j = { nom, params, echecs: 0, pauseJusqu: 0 }; jeux.set(cle, j); }
  if (j.promesse) return j.promesse;
  if (!forcer && j.brut && Date.now() - j.t < FRAIS) return vue(nom, params);
  if (!forcer && j.pauseJusqu > Date.now()) return vue(nom, params);
  j.promesse = (async () => {
    const avant = j.sig;
    const r = await lire(SOURCES[nom] || nom, params || undefined);
    if (r.ok && r.donnees) {
      j.brut = r.donnees; j.t = Date.now(); j.horsLigne = !!r.horsLigne; j.sauveLe = r.sauveLe || 0; j.erreur = "";
      j.echecs = 0; j.pauseJusqu = 0;
      j.sig = (j.horsLigne ? "H" : "L") + j.sauveLe + ":" + JSON.stringify(r.donnees);
    } else {
      if (!j.brut) {
        j.erreur = r.status === 0 ? "Hors ligne, et rien n'est encore en mémoire pour cette page." : r.erreur || "Indisponible pour le moment.";
        j.status = r.status;
        j.sig = "E" + r.status + ":" + j.erreur;
      }
      j.echecs = (j.echecs || 0) + 1;
      const pause = Math.max(r.status === 429 ? 30000 : 0, r.apres || 0, PAUSES[Math.min(j.echecs - 1, PAUSES.length - 1)]);
      j.pauseJusqu = Date.now() + pause;
      if (!j.reprise && j.echecs <= REPRISES_MAX && etat.session === "ok") {
        j.reprise = setTimeout(() => { j.reprise = null; if (etat.session === "ok") charger(nom, { forcer: true, params }); }, pause + 250);
      }
    }
    j.promesse = null;
    if (j.sig !== avant) emettre("jeu", { nom, cle });
    return vue(nom, params);
  })();
  return j.promesse;
}

/** La vue actuelle (sans réseau) : données + modifications en attente. null si rien. */
export function vue(nom, params) {
  const j = jeux.get(cleDe(nom, params));
  if (!j) return null;
  if (!j.brut) return j.erreur ? { erreur: j.erreur, status: j.status } : null;
  const d = appliquer(nom, copie(j.brut), params);
  Object.defineProperty(d, "_meta", { value: { horsLigne: j.horsLigne, sauveLe: j.sauveLe, t: j.t }, enumerable: false });
  return d;
}

export function perime(nom) {
  for (const j of jeux.values()) if (j.nom === nom) j.t = 0;
}
export function oublierTout() { jeux.clear(); }

/** Remplace l'objet d'une réponse d'écriture dans le jeu brut (sans attendre un rechargement). */
export function integrer(nom, objet, params) {
  const j = jeux.get(cleDe(nom, params));
  if (!j || !j.brut || !objet) return;
  const b = j.brut;
  const maj = (liste, egal) => {
    const i = liste.findIndex(egal);
    if (i >= 0) liste[i] = objet; else liste.push(objet);
  };
  if (nom === "affiches" && Array.isArray(b.affiches)) {
    b.corbeille = (b.corbeille || []).filter((a) => String(a.id) !== String(objet.id));
    b.affiches = b.affiches.filter((a) => String(a.id) !== String(objet.id));
    (objet.retire_le ? b.corbeille : b.affiches).push(objet);
  }
  else if (nom === "catalogue" && objet.type !== undefined && Array.isArray(b.elements)) maj(b.elements, (e) => e.type === objet.type && e.cle === objet.cle);
  else if (nom === "evenements" && Array.isArray(b.brouillons)) maj(b.brouillons, (x) => String(x.id) === String(objet.id));
  emettre("jeu", { nom, cle: cleDe(nom, params) });
}

// Après chaque envoi réussi : le jeu concerné se recharge en arrière-plan (version canonique du serveur).
const GENRES = { affiche: "affiches", element: "catalogue", type: "catalogue", brouillon: "evenements", question: "banque",
  liens: "banque", reglages: "banque", modele: "banque", correction: "dossier" };
ecouter("file:succes", ({ op, objet }) => {
  const nom = GENRES[op.genre];
  if (!nom) return;
  if (objet && nom !== "dossier" && nom !== "banque") integrer(nom, objet);
  perime(nom);
  for (const j of jeux.values()) if (j.nom === nom) charger(nom, { forcer: true, params: j.params });
});
ecouter("file", () => emettre("jeux:file"));

// ─── La file par-dessus les données ─────────────────────────────────────────
function marque(objet, op) {
  return Object.assign({}, objet, { _attente: op.etat, _op: op.op_id });
}
function upsert(liste, objet, egal) {
  const i = liste.findIndex(egal);
  if (i >= 0) liste[i] = objet; else liste.push(objet);
}

function appliquer(nom, d, params) {
  const ops = file.ops.filter((o) => o.etat !== "refus");
  if (!ops.length) return d;
  if (nom === "affiches") return appliquerAffiches(d, ops);
  for (const op of ops) {
    const c = op.corps || {};
    const o = op.objet;
    if (nom === "affiches") {
      d.affiches = d.affiches || [];
      if (op.api === "rell/affiche" && o) upsert(d.affiches, marque(o, op), (a) => String(a.id) === String(c.id || op.cle) || String(a._cle) === String(op.cle));
      if (op.api === "rell/affiche/retirer") {
        const a = d.affiches.find((x) => String(x.id) === String(c.id));
        if (a) Object.assign(a, { retire_le: c.restaurer ? null : Math.floor(op.cree / 1000), _attente: op.etat, _op: op.op_id });
      }
    } else if (nom === "catalogue") {
      d.elements = d.elements || []; d.types = d.types || [];
      if (op.api === "rell/catalogue/element" && o) upsert(d.elements, marque(o, op), (e) => e.type === o.type && e.cle === o.cle);
      if (op.api === "rell/catalogue/retirer") {
        const e = d.elements.find((x) => x.type === c.type && x.cle === c.cle);
        if (e) Object.assign(e, { actif: false, _attente: op.etat, _op: op.op_id });
      }
      if (op.api === "rell/catalogue/type" && o) upsert(d.types, marque(o, op), (t) => t.cle === o.cle);
    } else if (nom === "evenements") {
      d.brouillons = d.brouillons || [];
      const meme = (b) => (c.id && String(b.id) === String(c.id)) || (c.cle_client && b.cle_client === c.cle_client) || String(b._cle) === String(op.cle) || String(b.id) === String(op.cle);
      if (op.api === "clan/brouillon" && o) {
        const avant = d.brouillons.find(meme);
        upsert(d.brouillons, marque(Object.assign({}, avant || {}, o, { valeurs: Object.assign({}, (avant && avant.valeurs) || {}, o.valeurs || {}) }), op), meme);
      }
      if (op.api === "clan/supprimer_brouillon") d.brouillons = d.brouillons.filter((b) => !meme(b));
    } else if (nom === "banque") {
      d.questions = d.questions || []; d.modeles = d.modeles || [];
      if (op.api === "recrutement/question" && o) upsert(d.questions, marque(o, op), (q) => String(q.id) === String(c.id || op.cle) || String(q._cle) === String(op.cle));
      if (op.api === "recrutement/question/retirer") d.questions = d.questions.filter((q) => String(q.id) !== String(c.id));
      if (op.api === "recrutement/liens" && Array.isArray(c.liens)) { d.liens = c.liens; d._liensAttente = op.etat; }
      if (op.api === "recrutement/reglages") { d.reglages = Object.assign({}, d.reglages, c); d._reglagesAttente = op.etat; }
      if (op.api === "recrutement/modele" && o) {
        if (c.par_defaut) d.modeles.forEach((m) => { m.par_defaut = false; });
        upsert(d.modeles, marque(o, op), (m) => String(m.id) === String(c.id || op.cle) || String(m._cle) === String(op.cle));
      }
      if (op.api === "recrutement/modele/retirer") d.modeles = d.modeles.filter((m) => String(m.id) !== String(c.id));
    } else if (nom === "dossier") {
      if (op.api === "recrutement/corriger") {
        for (const e of d.envois || []) {
          if (String(e.id) !== String(c.envoi)) continue;
          for (const q of e.questions || []) if (String(q.id) === String(c.question)) { q.juste = c.juste; q._attente = op.etat; }
        }
      }
    }
  }
  return d;
}

/** Les affiches : actives et corbeille réunies, les modifications appliquées, puis rangées à nouveau. */
function appliquerAffiches(d, ops) {
  const tous = new Map();
  for (const a of [...(d.affiches || []), ...(d.corbeille || [])]) tous.set(String(a.id), a);
  for (const op of ops) {
    const c = op.corps || {};
    const id = String(c.id || op.cle);
    if (op.api === "rell/affiche" && op.objet) tous.set(id, Object.assign({}, tous.get(id) || {}, op.objet, { id, _attente: op.etat, _op: op.op_id }));
    if (op.api === "rell/affiche/retirer" || op.api === "rell/affiche/restaurer") {
      const a = tous.get(id);
      const restaurer = op.api === "rell/affiche/restaurer" || !!c.restaurer;
      if (a) tous.set(id, Object.assign({}, a, { retire_le: restaurer ? null : Math.floor(op.cree / 1000), _attente: op.etat, _op: op.op_id }));
    }
  }
  const l = [...tous.values()];
  d.affiches = l.filter((a) => !a.retire_le);
  d.corbeille = l.filter((a) => a.retire_le);
  return d;
}

// ─── Petits accès communs ───────────────────────────────────────────────────
export function elementsDe(cat, type) {
  return ((cat && cat.elements) || []).filter((e) => e.type === type).sort((a, b) => (a.ordre || 0) - (b.ordre || 0) || String(a.nom).localeCompare(String(b.nom), "fr"));
}
export function typesTries(cat) {
  return ((cat && cat.types) || []).slice().sort((a, b) => (a.ordre || 0) - (b.ordre || 0));
}
export function element(cat, type, cle) {
  return ((cat && cat.elements) || []).find((e) => e.type === type && e.cle === cle) || null;
}
/** Le type qui porte les métiers (cle ou champ « metier »). */
export function typeMetier(cat) {
  const t = typesTries(cat);
  return t.find((x) => x.cle === "metier" || x.champ === "metier") || t.find((x) => /m[ée]tier/i.test(x.nom || "")) || null;
}
export function typeGrade(cat) {
  return typesTries(cat).find((x) => x.cle === "grade" || x.champ === "grade") || null;
}
export const donneesServeur = () => etat.d;
