// api.js — parler au serveur : lectures (avec ETag), écritures (en-tête X-Tableau), état du réseau et de la session.
// Les routes existantes sont à /tableau/espace/<nom> ; les nouvelles à /tableau/espace/api/<nom>.

import { BASE } from "./dom.js";
import { etat, emettre } from "./noyau.js";

const EXISTANTES = new Set(["donnees", "membre", "conversation", "recherche", "export", "action", "sortir", "sync"]);
const DELAI_LECTURE = 15000;
const DELAI_ECRITURE = 25000;
// Une session terminée n'appelle plus le serveur : chaque appel avec un cookie périmé y compte comme un « essai »,
// et trop d'essais bloquent l'adresse — même le nouveau lien — pendant dix minutes. Seule la déconnexion passe.
const SANS_SESSION = { ok: false, status: 401, erreur: "Session terminée : ouvre un nouveau lien depuis le salon « logs »." };
const sessionFinie = (nom) => etat.session !== "ok" && nom !== "sortir";

export function url(nom, params) {
  const chemin = EXISTANTES.has(nom) ? BASE + "/" + nom : BASE + "/api/" + nom;
  const q = params ? new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)])).toString() : "";
  return chemin + (q ? "?" + q : "");
}

/** Le réseau répond (ou non). Prévient la page quand l'état change. */
export function noterReseau(ok, raison) {
  const avant = etat.reseau.enLigne;
  etat.reseau.enLigne = !!ok;
  etat.reseau.raison = ok ? "" : raison || "reseau";
  if (avant !== etat.reseau.enLigne) {
    etat.reseau.depuis = Date.now();
    emettre("reseau", etat.reseau);
  }
}

const RE_SESSION = /expir|retir|suspendu|session/i;
export function sessionTerminee(message) {
  if (etat.session === "expiree") return;
  etat.session = "expiree";
  etat.messageSession = message || "";
  emettre("session", { message });
}

async function avecDelai(adresse, options, delai) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), delai);
  try {
    return await fetch(adresse, Object.assign({ signal: ctrl.signal }, options));
  } finally {
    clearTimeout(t);
  }
}

/** Un 5xx est une PANNE (serveur injoignable) seulement s'il vient du service worker hors ligne (« X-Hors-Ligne »)
 *  ou n'est pas une réponse de notre serveur (page d'erreur du proxy). Un 5xx de notre serveur — un JSON avec
 *  « erreur », par exemple « Discord ne répond pas » — dit que le serveur répond : la page reste en ligne. */
const panne = (r, corps) => r.status >= 500 && (r.headers.get("X-Hors-Ligne") === "1" || !(corps && typeof corps.erreur === "string"));

async function corpsJson(r) {
  if (r.status === 204) return {};
  try { return await r.json(); } catch (e) { return null; }
}

/** GET → { ok, status, donnees, horsLigne, sauveLe, etag, erreur } — ne lève jamais. */
export async function lire(nom, params, { etag } = {}) {
  if (sessionFinie(nom)) return Object.assign({}, SANS_SESSION);
  let r;
  try {
    r = await avecDelai(url(nom, params), { credentials: "same-origin", cache: "no-store", headers: etag ? { "If-None-Match": etag } : {} }, DELAI_LECTURE);
  } catch (e) {
    noterReseau(false, "reseau");
    return { ok: false, status: 0, horsLigne: true, erreur: "Pas de connexion." };
  }
  const horsLigne = r.headers.get("X-Hors-Ligne") === "1";
  const sauveLe = Number(r.headers.get("X-Sauve-Le") || 0) || 0;
  if (horsLigne) noterReseau(false, "cache");
  else if (r.status < 500) noterReseau(true);
  if (r.status === 304) return { ok: true, status: 304, etag };
  const corps = await corpsJson(r);
  if (!horsLigne && r.status >= 500 && !panne(r, corps)) noterReseau(true);
  if (r.status === 401 || r.status === 403) {
    const m = (corps && (corps.erreur || corps.message)) || "";
    if (r.status === 401 || RE_SESSION.test(m) || nom === "donnees") sessionTerminee(m);
    return { ok: false, status: r.status, erreur: m || "Accès refusé." };
  }
  if (!r.ok) {
    if (panne(r, corps)) noterReseau(false, "serveur");
    let erreur = (corps && (corps.erreur || corps.message)) || "";
    // Une adresse que ce serveur ne connaît pas encore (module pas encore branché) : le dire simplement.
    if (r.status === 404 && (!erreur || /^adresse inconnue/i.test(erreur))) erreur = "Pas encore disponible sur ce serveur.";
    return { ok: false, status: r.status, erreur: erreur || (r.status === 429 ? "Trop de demandes d'un coup : un instant." : "Indisponible pour le moment."), corps,
      apres: (Number(r.headers.get("Retry-After")) || 0) * 1000 };
  }
  return { ok: true, status: r.status, donnees: corps, horsLigne, sauveLe, etag: r.headers.get("ETag") };
}

/** POST (écriture) → { ok, status, donnees, erreur, reseau } — ne lève jamais. */
export async function poster(nom, corps, params) {
  if (sessionFinie(nom)) return Object.assign({}, SANS_SESSION);
  let r;
  try {
    r = await avecDelai(url(nom, params), {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Tableau": "1" },
      body: corps === undefined ? undefined : JSON.stringify(corps),
    }, DELAI_ECRITURE);
  } catch (e) {
    noterReseau(false, "reseau");
    return { ok: false, status: 0, reseau: true, erreur: "Pas de connexion : rien n'est parti." };
  }
  const donnees = await corpsJson(r);
  const enPanne = panne(r, donnees);
  if (enPanne) noterReseau(false, "serveur"); else noterReseau(true);
  const message = (donnees && (donnees.erreur || donnees.message)) || "";
  if (r.status === 401 || (r.status === 403 && RE_SESSION.test(message))) {
    sessionTerminee(message);
    return { ok: false, status: r.status, erreur: message || "Session terminée.", donnees };
  }
  if (!r.ok) {
    return { ok: false, status: r.status, erreur: message || (r.status >= 500 ? "Le serveur ne répond pas : réessaie dans un instant." : "Refusé."), donnees, reseau: enPanne };
  }
  const ok = !donnees || donnees.ok !== false;
  return { ok, status: r.status, donnees: donnees || {}, erreur: ok ? "" : message || "Refusé." };
}

/** Une action du tableau (modération, clan…) : POST action → { ok, message }. */
export async function action(corps) {
  const r = await poster("action", corps);
  const message = (r.donnees && r.donnees.message) || r.erreur || (r.ok ? "C'est fait." : "Refusé.");
  return { ok: r.ok && !!(r.donnees && r.donnees.ok !== false), message, reseau: !!r.reseau, status: r.status };
}

export const lienExport = (params) => url("export", params);
