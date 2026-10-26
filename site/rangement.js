// rangement.js — ranger chaque onglet : la ligne compacte (titre · détails · badges · date · actions dans une colonne
// fixe à droite), les actions en icônes (libellé accessible, le reste dans « Plus d'actions »), les groupes repliables
// par période ou par type (les premiers ouverts, « Tout replier / Tout déplier »), et ce qui revient partout
// (membres restreints par la direction, noms des rubriques).
//
// Une liste de lignes : `paginer(cle, liste, rendreUn, { balise: "ul", classe: "lignes-c", pas: 20 })` (ui.js) — au
// bureau, les colonnes de toutes les lignes d'une liste s'alignent (sous-grille) ; au téléphone, chaque ligne tient sur
// deux lignes, ses actions à droite.

import { h, icone, cleJour, maintenant, depuis, date, ajouter, sansEmoji, libelleJour, libelleMois, moisDe } from "./dom.js";
import { etat, enLigne, raisonHorsLigne } from "./noyau.js";
import { bouton, menu, groupe, pastille, paginer } from "./ui.js";

// ─── Les noms des catégories et des rubriques ───────────────────────────────
/** LE point d'appel unique pour le nom d'une catégorie ou d'une rubrique affiché par l'accueil et la recherche
 *  (l'équipe « Textes & noms » rend ces noms modifiables : `libelle(cle, defaut)` de noyau.js se branche ici). */
export const titreNav = (x) => (x && x.titre) || "";

// ─── Les membres restreints par la direction (/direction : `restricted_members`) ─
let memoRestreints = null, memoDonnees = null;
/** id → { depuis, raison, par } des membres restreints en ce moment (données du serveur). */
export function restreints() {
  const d = etat.d;
  if (d !== memoDonnees) {
    memoDonnees = d;
    memoRestreints = new Map((((d && d.sanctions && d.sanctions.actives) || {}).restreints || []).map((r) => [String(r.id), r]));
  }
  return memoRestreints || new Map();
}
export const estRestreint = (id) => restreints().has(String(id || ""));
/** La pastille « Restreint » d'une personne restreinte par la direction (sinon rien). */
export function badgeRestreint(id) {
  const r = restreints().get(String(id || ""));
  if (!r) return null;
  const titre = "Restreint par la direction" + (r.depuis ? " depuis le " + date(r.depuis) : "") + (r.par ? " · par " + sansEmoji(r.par) : "")
    + (r.raison ? " · " + r.raison : "");
  return pastille("Restreint", "#5e3a4e", titre);
}

// ─── Les actions d'une ligne ────────────────────────────────────────────────
/** Une action en icône : libellé accessible (lu, et cherché par les parcours), au survol, et confirmation par son
 *  `onclick` (agir, confirmer). a : { icone, libelle, onclick?, href?, danger?, reseau?, desactive?, classe? } */
export function actionIcone(a) {
  const contenu = [icone(a.icone || "ouvrir"), h("span", { classe: "sr" }, a.libelle)];
  const classe = "action-ic" + (a.danger ? " danger" : "") + (a.classe ? " " + a.classe : "");
  if (a.href) return h("a", { classe, href: a.href, title: a.libelle, "aria-label": a.libelle, onclick: (e) => e.stopPropagation() }, contenu);
  const b = h("button", {
    classe, type: "button", title: a.libelle, "aria-label": a.libelle, disabled: a.desactive || null,
    onclick: (e) => { e.stopPropagation(); if (a.onclick) a.onclick(e); },
  }, contenu);
  if (a.reseau) {
    b.dataset.reseau = "1";
    b.dataset.titre = a.libelle;
    if (!enLigne()) { b.disabled = true; b.classList.add("sans-reseau"); b.title = raisonHorsLigne(); }
  }
  return b;
}
function actionNoeud(a) {
  if (a.noeud) return a.noeud;
  const classe = "p" + (a.danger ? " danger" : "") + (a.classe ? " " + a.classe : "");
  if (a.texte && a.href) return h("a", { classe: "bouton " + classe, href: a.href, onclick: (e) => e.stopPropagation() }, a.icone ? icone(a.icone) : null, h("span", {}, a.libelle));
  if (a.texte) return bouton(a.libelle, { classe, icone: a.icone, reseau: a.reseau, onclick: a.onclick, titre: a.titre, disabled: a.desactive });
  return actionIcone(a);
}
/** Les actions qui ne tiennent pas dans la colonne : un menu « Plus d'actions ». */
function menuActions(acts) {
  const b = h("button", { classe: "action-ic", type: "button", title: "Plus d'actions", "aria-label": "Plus d'actions" }, icone("menu"), h("span", { classe: "sr" }, "Plus d'actions"));
  return menu(b, () => acts.map((a) => ({ l: a.libelle, icone: a.icone, danger: a.danger, href: a.href, desactive: !!((a.reseau && !enLigne()) || a.desactive), onclick: a.onclick })));
}

// ─── La ligne compacte ──────────────────────────────────────────────────────
/** Une ligne : [visuel] [titre / détails] [badges] [date] [actions].
 *  o : { visuel, titre, titreTexte, sous, badges, maxBadges (2), date, dateTitre, actions, visibles (2),
 *        ouvrir (toute la ligne l'ouvre), libelleOuvrir, deplier (→ le détail, construit au premier dépli), teinte,
 *        etat ("alerte" | "chaude" | "calme" | "attente" | "eteinte"), classe, donnees (data-*), balise ("li") } */
export function ligne(o) {
  const clic = typeof o.ouvrir === "function", depl = typeof o.deplier === "function";
  const li = h(o.balise || "li", {
    classe: "lc" + (clic || depl ? " lc-clic" : "") + (o.etat ? " lc-" + o.etat : "") + (o.classe ? " " + o.classe : ""),
    vars: o.teinte ? { "--teinte": o.teinte } : null,
  });
  for (const [k, v] of Object.entries(o.donnees || {})) if (v !== undefined && v !== null) li.dataset[k] = String(v);
  const texteTitre = o.titreTexte || (typeof o.titre === "string" ? o.titre : "");
  const titre = h("span", { classe: "lc-titre", title: texteTitre || null }, o.titre);
  // Une ligne qui s'ouvre (ou se déplie) : un bouton transparent sur toute la ligne — la cible fait toute la hauteur au
  // doigt, le cadre du focus entoure la ligne, le titre complet s'affiche au survol ; les actions, les noms et le
  // détail passent au-dessus.
  const ouvreur = clic || depl ? h("button", { classe: "lc-ouvrir", type: "button", title: texteTitre || null,
    "aria-label": o.libelleOuvrir || texteTitre || "Ouvrir", "aria-expanded": depl ? "false" : null }) : null;
  const sousTexte = h("span", { classe: "lc-sous-texte" }, o.sous || null);
  const sous = h("span", { classe: "lc-sous" }, o.date ? h("span", { classe: "lc-date-m" }, o.date) : null, sousTexte);
  const bs = [o.badges].flat().filter(Boolean);
  const max = o.maxBadges ?? 2;
  const vus = bs.length > max ? bs.slice(0, Math.max(0, max - 1)) : bs;
  const reste = bs.slice(vus.length);
  const badges = h("span", { classe: "lc-badges" }, vus,
    reste.length ? pastille("+" + reste.length, null, reste.map((b) => b.textContent.trim()).join(" · "), true) : null);
  const acts = [o.actions].flat().filter(Boolean);
  const visibles = o.visibles ?? 2;
  const n = acts.length <= visibles + 1 ? acts.length : visibles;
  const actions = h("span", { classe: "lc-actions" }, acts.slice(0, n).map(actionNoeud), acts.length > n ? menuActions(acts.slice(n)) : null);
  if (acts.slice(0, n).some((a) => a.texte || a.noeud)) li.classList.add("lc-larges");   // au téléphone : leur rangée à elles
  ajouter(li, [
    ouvreur,
    h("span", { classe: "lc-visuel" }, o.visuel || null),
    h("span", { classe: "lc-corps" }, titre, sous),
    badges,
    h("span", { classe: "lc-date", title: o.dateTitre || null }, o.date || ""),
    actions,
  ]);
  if (!sousTexte.childNodes.length) sous.classList.add(o.date ? "seulement-date" : "vide");   // au téléphone, la date y reste
  else sousTexte.title = sousTexte.textContent.trim();   // le texte complet au survol
  let detail = null;
  const basculer = () => {
    if (!detail) { detail = h("div", { classe: "lc-detail" }, o.deplier()); ajouter(li, [detail]); }
    else detail.hidden = !detail.hidden;
    const ouvert = !detail.hidden;
    li.classList.toggle("deplie", ouvert);
    ouvreur.setAttribute("aria-expanded", String(ouvert));
  };
  if (ouvreur) {
    const agir = (e) => (clic ? o.ouvrir(e) : basculer());
    ouvreur.addEventListener("click", (e) => { e.stopPropagation(); agir(e); });
    // Un clic sur ce qui passe au-dessus sans être un bouton (une pastille qui explique au survol), ou posé sur la ligne
    // elle-même par un script : la ligne s'ouvre aussi.
    li.addEventListener("click", (e) => { if (!e.target.closest("button, a[href], input, label, select, textarea, .lc-detail")) agir(e); });
  }
  li.basculer = depl ? basculer : null;
  return li;
}

/** Une liste de lignes, « Voir plus » par 20 (jamais des centaines d'un coup). */
export function lignes(cle, liste, rendreUn, o = {}) {
  return paginer(cle, liste, rendreUn, { pas: o.pas || 20, balise: "ul", classe: "lignes-c" + (o.classe ? " " + o.classe : "") });
}
/** Une séparation dans une liste de lignes (le jour, dans une période). */
export const separation = (texte) => h("li", { classe: "lc-sep", role: "presentation" }, h("span", {}, texte));

// ─── Les groupes repliables ─────────────────────────────────────────────────
/** Des groupes : les `ouverts` premiers ouverts par défaut (puis comme la personne les a laissés), les autres fermés ;
 *  `forcer` : tous ouverts (une recherche en cours). defs : [{ cle, titre, compte, chaud, info, icone, visuel, classe,
 *  contenu: () => Node }] */
export function groupes(defs, o = {}) {
  const n = o.ouverts ?? 1;
  return defs.filter(Boolean).map((d, i) => groupe(Object.assign({}, d, { defaut: i < n, ouvert: o.forcer ? true : undefined }), d.contenu));
}
/** « Tout déplier » / « Tout replier » pour les groupes d'une zone (racine : un nœud, ou une fonction qui le donne). */
export function outilsGroupes(racine) {
  const regler = (ouvrir) => {
    const r = typeof racine === "function" ? racine() : racine;
    if (!r) return;
    for (const d of r.querySelectorAll("details.groupe")) if (d.open !== ouvrir && !d.closest(".lc-detail")) d.open = ouvrir;
  };
  return h("div", { classe: "outils-groupes", role: "group", "aria-label": "Ouvrir ou fermer les groupes" },
    bouton("Tout déplier", { classe: "p discret", icone: "bas", onclick: () => regler(true) }),
    bouton("Tout replier", { classe: "p discret", icone: "haut", onclick: () => regler(false) }));
}

// ─── Les périodes ───────────────────────────────────────────────────────────
export const PERIODES = [["jour", "Aujourd'hui"], ["hier", "Hier"], ["semaine", "Cette semaine"], ["mois", "Ce mois"], ["ancien", "Plus ancien"]];
const JOUR = 86400;
/** La période d'un instant passé (jour à Paris) : aujourd'hui, hier, 7 jours, 30 jours, plus ancien. */
export function periodeDe(t) {
  if (!t) return "ancien";
  const n = maintenant(), k = cleJour(t);
  if (k === cleJour(n)) return "jour";
  if (k === cleJour(n - JOUR)) return "hier";
  if (n - t < 7 * JOUR) return "semaine";
  if (n - t < 31 * JOUR) return "mois";
  return "ancien";
}
/** [[cle, libellé, éléments]] des périodes non vides, dans l'ordre (du plus récent au plus ancien). */
export function parPeriode(liste, quand) {
  const m = new Map(PERIODES.map(([k]) => [k, []]));
  for (const x of liste) m.get(periodeDe(quand(x))).push(x);
  return PERIODES.map(([k, l]) => [k, l, m.get(k)]).filter(([, , l]) => l.length);
}
/** Groupes par période d'une liste déjà triée : un groupe par période non vide, sa liste de lignes paginée. */
export function groupesParPeriode(cle, liste, quand, rendreUn, o = {}) {
  return groupes(parPeriode(liste, quand).map(([k, lib, l]) => ({
    cle: cle + "-" + k, titre: lib, compte: l.length, chaud: o.chaud ? o.chaud(l) : false, info: o.info ? o.info(l) : "",
    contenu: () => lignes(cle + "-" + k, l, rendreUn, { pas: o.pas || 20 }),
  })), { ouverts: o.ouverts ?? 1, forcer: o.forcer });
}

// ─── Les historiques : par jour, puis par semaine, puis par mois ────────────
/** Le lundi (clé AAAA-MM-JJ, à Paris) de la semaine d'un instant. */
function lundiDe(t) {
  const [a, m, j] = cleJour(t).split("-").map(Number);
  const d = new Date(Date.UTC(a, m - 1, j, 12));
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}
/** Les groupes d'un historique trié du plus récent au plus ancien : un par jour pour la dernière semaine (« Aujourd'hui »,
 *  « Hier », « Vendredi 23 octobre »…), puis un par semaine jusqu'à cinq semaines, puis un par mois.
 *  [[cle, titre, éléments]], dans l'ordre de la liste. */
export function parJours(liste, quand) {
  const n = maintenant(), m = new Map();
  for (const x of liste) {
    const t = quand(x) || 0, age = n - t;
    let cle, titre;
    if (age < 7 * JOUR) { cle = "j" + cleJour(t); titre = libelleJour(cleJour(t)); }
    else if (age < 35 * JOUR) { const l = lundiDe(t); cle = "s" + l; titre = "Semaine du " + libelleJour(l).toLowerCase(); }
    else { cle = "m" + moisDe(t); titre = libelleMois(moisDe(t)); }
    if (!m.has(cle)) m.set(cle, [cle, titre, []]);
    m.get(cle)[2].push(x);
  }
  return [...m.values()];
}
/** Un historique en groupes repliables (par jour, semaine, mois), chacun avec son compte ; les `ouverts` premiers
 *  ouverts, les plus anciens fermés ; une ligne par élément, « Voir plus » par 20. */
export function groupesParJours(cle, liste, quand, rendreUn, o = {}) {
  return groupes(parJours(liste, quand).map(([k, titre, l]) => ({
    cle: cle + "-" + k, titre, compte: l.length, chaud: o.chaud ? o.chaud(l) : false, info: o.info ? o.info(l) : "",
    contenu: () => lignes(cle + "-" + k, l, rendreUn, { pas: o.pas || 20 }),
  })), { ouverts: o.ouverts ?? 1, forcer: o.forcer });
}

// ─── Petits morceaux ────────────────────────────────────────────────────────
/** Un bloc avancé (filtre, export, détail technique) : caché en mode simple (mode.js). */
export function avance(el) { if (el && el.classList) el.classList.add("avance"); return el; }
/** Un visuel rond (icône teintée) pour une ligne sans personne. */
export const pastilleIcone = (nom, teinte) => h("span", { classe: "lc-ic", vars: teinte ? { "--teinte": teinte } : null, "aria-hidden": "true" }, icone(nom));
/** « il y a 3 j » avec la date complète au survol. */
export const quandLigne = (t) => ({ date: t ? depuis(t) : "", dateTitre: t ? date(t, true) : "" });
