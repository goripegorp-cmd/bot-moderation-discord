// noyau.js — l'état partagé, le bus d'événements, les catégories et rubriques, la navigation.

/** La version des fichiers : celle de la balise <script> de la page (s/app.js?v=…), posée par le serveur. */
export const V = (() => {
  try {
    const s = document.querySelector('script[type="module"][src*="/s/app.js"]');
    return (s && new URL(s.src).searchParams.get("v")) || "dev";
  } catch (e) { return "dev"; }
})();

export const CATEGORIES = [
  {
    // La première page : tout ce qui attend une action, et les raccourcis par tâche (accueil.js).
    cle: "accueil", titre: "Accueil", court: "Accueil", sous: "Ce qui t'attend", icone: "boussole",
    rubriques: [
      { cle: "attente", titre: "Ce qui t'attend", icone: "boussole", phrase: "Tout ce qui demande une action, du plus urgent au moins urgent : un bouton par ligne." },
    ],
  },
  {
    cle: "port", titre: "Le Port", court: "Le Port", sous: "Discord", icone: "port",
    rubriques: [
      { cle: "apercu", titre: "Aperçu", icone: "apercu", phrase: "Ce qui demande ton attention, en un coup d'œil." },
      { cle: "journal", titre: "Journal", icone: "journal", phrase: "Tout ce qui s'est passé sur le serveur : l'important d'abord, puis jour par jour." },
      { cle: "sanctions", titre: "Sanctions", icone: "sanctions", phrase: "Le casier de chaque membre, les modérateurs, le nettoyage du casier." },
      { cle: "tickets", titre: "Tickets", icone: "tickets", phrase: "Les tickets du serveur, ouverts et fermés, avec toute leur conversation." },
      { cle: "repertoire", titre: "Répertoire", icone: "repertoire", phrase: "Toutes les personnes, de A à Z : chaque fiche réunit tout ce qui la concerne." },
      { cle: "salons", titre: "Salons & questions", icone: "salons", phrase: "Questions, idées, sondages, entraide, annonces, et ce que chacun peut faire dans chaque salon." },
      { cle: "nettoyage", titre: "Nettoyage", icone: "nettoyage", phrase: "Ce qui est gardé, combien de temps, et le grand ménage quand tu veux." },
      { cle: "securite", titre: "Sécurité", icone: "cadenas", phrase: "Qui est connecté au site, ce que le site a fait sur Discord, et qui a les permissions dangereuses." },
    ],
  },
  {
    cle: "equipage", titre: "L'Équipage", court: "Équipage", sous: "Clan GoRP", icone: "equipage",
    rubriques: [
      { cle: "membres", titre: "Équipage", icone: "membres", phrase: "Les membres du clan, leur présence, les rappels d'inactivité." },
      { cle: "fiches", titre: "Fiches techniques", icone: "fiches", phrase: "Chaque membre et son affiche : par métier, par grade, de A à Z." },
      { cle: "tickets", titre: "Tickets du clan", icone: "tickets", phrase: "Les tickets Rell Seas du clan, ouverts et fermés." },
      { cle: "annonces", titre: "Annonces & événements", icone: "annonces", phrase: "Composer pour le salon Info : événements avec minuteur et réponses, annonces, métiers, listing." },
    ],
  },
  {
    cle: "capitainerie", titre: "La Capitainerie", court: "Capitainerie", sous: "Fondateur & direction", icone: "capitainerie",
    rubriques: [
      { cle: "recrutement", titre: "Demande de recrutement", icone: "candidatures", phrase: "Les demandes et leurs étapes, les chefs d'équipe, les questions, les réglages : tout le recrutement au même endroit." },
      { cle: "affiches", titre: "Affiches", icone: "affiches", phrase: "L'atelier des avis de recherche de l'équipage : créer, modifier, ranger par métier." },
      { cle: "catalogue", titre: "Catalogue RELL Seas", icone: "catalogue", phrase: "Tout ce qui existe dans le jeu, et seulement cela : types, éléments, icônes officielles." },
      { cle: "roles", titre: "Rôles & métiers", icone: "roles", phrase: "Un rôle Discord par métier, donné tout seul si tu le veux." },
      { cle: "textes", titre: "Textes & noms", icone: "plume", phrase: "Chaque texte du bot et chaque nom du site, à ta façon : enregistré, il sert tout de suite." },
    ],
  },
];

// ─── Les noms choisis par la direction (Capitainerie → Textes & noms) ────────
// Le serveur envoie les noms CHANGÉS (`textes/site`) ; tout le reste garde le nom écrit ici. Les catégories et les
// rubriques lisent leurs noms par `libelle` : renommées sur le site, elles le sont partout à la fois (navigation,
// titres, recherche).
const libelles = new Map();
/** Le nom choisi sur le site pour `cle` (« site.cat.port.titre »…), sinon `defaut`. */
export function libelle(cle, defaut) {
  const v = libelles.get(cle);
  return typeof v === "string" && v.trim() ? v : defaut;
}
/** Les noms reçus du serveur ({ clé: nom }) ; « libelles » est annoncé s'ils changent. */
export function poserLibelles(valeurs) {
  const avant = JSON.stringify([...libelles]);
  libelles.clear();
  for (const [k, v] of Object.entries(valeurs || {})) if (typeof v === "string" && v.trim()) libelles.set(k, v);
  if (JSON.stringify([...libelles]) !== avant) emettre("libelles", Object.fromEntries(libelles));
}
function nommer(objet, prefixe, champs) {
  for (const champ of champs) {
    const defaut = objet[champ];
    Object.defineProperty(objet, champ, { enumerable: true, configurable: true,
      // Le nom court suit le nom choisi tant qu'il n'est pas changé lui-même.
      get: () => (champ === "court" && !libelles.has(prefixe + ".court") && libelles.has(prefixe + ".titre")
        ? libelle(prefixe + ".titre", defaut) : libelle(prefixe + "." + champ, defaut)) });
  }
}
for (const c of CATEGORIES) {
  nommer(c, "site.cat." + c.cle, ["titre", "court", "sous"]);
  for (const r of c.rubriques) nommer(r, "site.rub." + c.cle + "." + r.cle, ["titre", "phrase"]);
}
/** Des onglets [[clé, nom, icône], …] dont le nom se lit par `libelle(prefixe + "." + clé)` (« a-venir » → « a_venir ») :
 *  renommés sur le site, ils le sont au prochain affichage. Rend la même liste. */
export function nommerOnglets(prefixe, onglets) {
  for (const o of onglets) {
    const defaut = o[1], cle = prefixe + "." + String(o[0]).replace(/-/g, "_");
    Object.defineProperty(o, 1, { enumerable: true, configurable: true, get: () => libelle(cle, defaut) });
  }
  return onglets;
}

export const categorie = (cle) => CATEGORIES.find((c) => c.cle === cle) || CATEGORIES[0];
export const rubrique = (cat, cle) => categorie(cat).rubriques.find((r) => r.cle === cle) || categorie(cat).rubriques[0];

// ─── L'état ─────────────────────────────────────────────────────────────────
export const etat = {
  d: null,            // GET donnees
  etag: null,
  dernier: 0,         // ms : dernière réponse fraîche du serveur
  ageCache: 0,        // ms : âge des données servies hors ligne (0 = fraîches)
  route: { cat: "port", rub: "apercu", sous: "" },
  reseau: { enLigne: navigator.onLine !== false, depuis: Date.now(), raison: "" },
  session: "ok",      // ok · expiree
  versionNeuve: false,
  ouverture: Date.now(),
  pages: {},          // pagination « voir plus » par liste
  selection: new Set(),
};

// ─── Le bus ─────────────────────────────────────────────────────────────────
const bus = new EventTarget();
export function emettre(nom, detail) { bus.dispatchEvent(new CustomEvent(nom, { detail })); }
export function ecouter(nom, fn) {
  const f = (e) => fn(e.detail);
  bus.addEventListener(nom, f);
  return () => bus.removeEventListener(nom, f);
}

// ─── Les droits ─────────────────────────────────────────────────────────────
export const peutAgir = () => !!(etat.d && etat.d.droits && etat.d.droits.actions);
export const enLigne = () => etat.reseau.enLigne && etat.session === "ok";
export function raisonHorsLigne() {
  if (etat.session !== "ok") return "Session terminée : ouvre un nouveau lien depuis le salon « logs » sur Discord.";
  return "Hors ligne : cette action part sur Discord, elle attend le retour de la connexion.";
}

// ─── Les personnes citées ───────────────────────────────────────────────────
/** Une personne par son identifiant — ou déjà décrite par le serveur (`{ id, nom, … }` : les affiches, le
 *  recrutement, les annonces envoient ainsi l'auteur d'une modification). Connue de la page : sa fiche complète. */
export function P(id) {
  const decrite = id && typeof id === "object" ? id : null;
  const k = String((decrite ? decrite.id : id) || "");
  const p = etat.d && etat.d.personnes && etat.d.personnes[k];
  if (p) return p;
  const autres = etat.personnesVues && etat.personnesVues[k];
  if (autres) return autres;
  if (decrite && decrite.nom) return { id: k, nom: decrite.nom, pseudo: decrite.pseudo || "", avatar: decrite.avatar || "" };
  return { id: k, nom: k ? "Membre parti" : "Serveur", pseudo: "", avatar: "" };
}
export function retenirPersonnes(dico) {
  if (!dico) return;
  etat.personnesVues = Object.assign(etat.personnesVues || {}, dico);
}
export const aPart = (id) => !!(etat.d && (etat.d.a_part || []).includes(String(id)));

// ─── La navigation (ancre) ──────────────────────────────────────────────────
// Forme : #port/journal · #equipage/candidatures/questionnaire · &membre=123 (fiche ouverte) · ancien #membre=123
// 26/10/2026 : « Candidatures » a quitté l'Équipage pour la Capitainerie (« Demande de recrutement ») — les anciennes
// adresses y mènent encore (signets, raccourcis, liens donnés).
const ALIAS = { "equipage/candidatures": ["capitainerie", "recrutement", { questionnaire: "questions", decidees: "candidatures", "en-cours": "candidatures" }] };
function suivreAlias(morceaux) {
  const a = ALIAS[morceaux.slice(0, 2).join("/")];
  return a ? [a[0], a[1], ...(morceaux[2] ? [a[2][morceaux[2]] || morceaux[2]] : [])] : morceaux;
}
export function lireAncre() {
  const brut = location.hash.replace(/^#/, "");
  const [chemin, ...reste] = brut.split("&");
  const params = new URLSearchParams(reste.join("&"));
  if (chemin.includes("=")) for (const [k, v] of new URLSearchParams(chemin)) params.set(k, v);
  const bruts = chemin.includes("=") ? [] : chemin.split("/").filter(Boolean);
  const morceaux = suivreAlias(bruts);
  const cat = CATEGORIES.some((c) => c.cle === morceaux[0]) ? morceaux[0] : null;
  const rub = cat && categorie(cat).rubriques.some((r) => r.cle === morceaux[1]) ? morceaux[1] : null;
  const membre = params.get("membre") || "";
  const ancien = params.get("onglet") || "";
  const recrutement = params.get("recrutement") || "";   // « Choisir sur le site » (Discord) : le dossier de ce ticket
  return { cat, rub, sous: morceaux[2] || "", membre: /^\d{5,22}$/.test(membre) ? membre : "", ancien,
    recrutement: /^\d{1,12}$/.test(recrutement) ? recrutement : "", alias: morceaux !== bruts };
}
export function ancre(cat, rub, sous, extra) {
  return "#" + [cat, rub, sous].filter(Boolean).join("/") + (extra ? "&" + extra : "");
}
export function aller(cat, rub, sous) {
  [cat, rub, sous] = suivreAlias([cat, rub, sous].filter(Boolean));
  const a = ancre(cat, rub || categorie(cat).rubriques[0].cle, sous);
  if (location.hash !== a) location.hash = a;
  else emettre("route:meme");
}
export function poserAncre(extra) {
  const r = etat.route;
  const a = ancre(r.cat, r.rub, r.sous, extra);
  try { history.replaceState(null, "", location.pathname + a); } catch (e) { /* adresse inchangée */ }
}

// ─── Préférences (par onglet du navigateur) ─────────────────────────────────
const CLE_PREF = "capitainerie.filtres";
let prefs = {};
try { prefs = JSON.parse(sessionStorage.getItem(CLE_PREF) || "{}") || {}; } catch (e) { prefs = {}; }
/** Les filtres d'une liste : gardés pendant la session de l'onglet. */
export function filtres(cle, defaut) {
  prefs[cle] = Object.assign({}, defaut, prefs[cle] || {});
  return new Proxy(prefs[cle], {
    set(o, k, v) { o[k] = v; sauverPrefs(); return true; },
  });
}
let minuteurPrefs = 0;
function sauverPrefs() {
  clearTimeout(minuteurPrefs);
  minuteurPrefs = setTimeout(() => { try { sessionStorage.setItem(CLE_PREF, JSON.stringify(prefs)); } catch (e) { /* rien à garder */ } }, 200);
}
export function oublierPrefs() { prefs = {}; try { sessionStorage.removeItem(CLE_PREF); } catch (e) { /* rien */ } }
