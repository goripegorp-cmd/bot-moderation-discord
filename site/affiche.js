// affiche.js — l'avis de recherche de l'équipage (« WANTED »), sur les calques dessinés par l'illustrateur :
// 1. le papier (bords déchirés transparents), 2. le portrait, 3. le cadre gravé (affiche.svg : WANTED, « Avis de
// l'équipage », cadre du portrait, plaque de laiton, « RELL Seas »), 4. les textes posés dans les zones exactes de
// ornements/affiche.json (viewBox 600 × 840). Toutes les tailles sont des fractions de la largeur de l'affiche :
// elle garde ses proportions, du mur de la galerie jusqu'à la grande pancarte.

import { h, icone, srcSure, nombre, sansEmoji, majuscule } from "./dom.js";
import { element, typesTries, typeMetier, typeGrade } from "./donnees.js";

export const STATUTS_AFFICHE = { actif: "En service", en_mer: "En mer", absent: "Absent", ancien: "Ancien de l'équipage" };
const TAMPONS = { en_mer: "En mer", absent: "Absent", ancien: "Ancien" };

export const nomAffiche = (a) => sansEmoji((a.roblox && a.roblox.nom) || (a.membre && a.membre.nom) || "") || "Inconnu";
export function portrait(a) {
  return srcSure(a.roblox && a.roblox.avatar) || srcSure(a.membre && a.membre.avatar) || "";
}

/** La prime avec le ฿ dessiné (aucune police du site n'a ce signe). */
export function primeNoeud(n, classe) {
  return h("span", { classe: "prime" + (classe ? " " + classe : ""), "aria-label": nombre(n || 0) + " berrys" },
    h("span", { classe: "symbole-prime", "aria-hidden": "true" }), h("span", { "aria-hidden": "true" }, nombre(n || 0)));
}

/** Les insignes d'une affiche, dans l'ordre des types du catalogue. */
export function insignes(a, cat) {
  const out = [];
  const attributs = a.attributs || {};
  const types = typesTries(cat);
  const connus = new Set(types.map((t) => t.cle));
  for (const t of types) {
    for (const cle of attributs[t.cle] || []) {
      const e = element(cat, t.cle, cle);
      out.push({ type: t.cle, typeNom: t.nom, cle, nom: e ? e.nom : cle, icone: e ? e.icone : "", existe: !!e, actif: e ? e.actif !== false : false });
    }
  }
  for (const [type, cles] of Object.entries(attributs)) {
    if (connus.has(type)) continue;
    for (const cle of cles || []) out.push({ type, typeNom: type, cle, nom: cle, icone: "", existe: false, actif: false });
  }
  return out;
}
export function gradeDe(a, cat) {
  if (!a.grade) return "";
  const t = typeGrade(cat);
  const e = t ? element(cat, t.cle, a.grade) : null;
  return e ? e.nom : majuscule(sansEmoji(String(a.grade)).replace(/_/g, " ").trim());  // une clé sans fiche : « quartier_maitre » → « Quartier maitre »
}
export function metiersDe(a, cat) {
  const t = typeMetier(cat);
  return t ? (a.attributs && a.attributs[t.cle]) || [] : [];
}

// ─── Icônes du catalogue : l'officielle si elle est là, sinon une pastille gravée ─────
// Beaucoup d'icônes officielles manquent encore (le wiki bloque les téléchargements) : champ `icone` vide, ou image
// qui ne se charge pas. Jamais d'image cassée ni de vide : l'initiale gravée (Pirata One), teintée selon le type,
// avec l'icône maison du type en petit sur les grandes pastilles. Une adresse qui a échoué n'est plus redemandée.
const ICONES_TYPE = {
  metier: "roles", race: "personne", faction: "drapeau", mer: "carte", trait: "etoile", classe: "grade", fruit: "coffre",
  haki: "oeil", carte_haki: "parchemin", poster: "affiches", style: "crane", arme: "sabre", equipement: "cle",
  enchantement: "etoile", navire: "navire", piece_navire: "ancre", monture: "boussole", monnaie: "berry", grade: "grade",
};
const TEINTES_TYPE = {
  metier: "#7a5a22", race: "#5a4330", faction: "#8e2a24", mer: "#1f4e5a", trait: "#a8641c", classe: "#4a5560",
  fruit: "#5e3a4e", haki: "#3d2f5e", carte_haki: "#3d2f5e", poster: "#8a4f12", style: "#8e2a24", arme: "#4a5560",
  equipement: "#5a4330", enchantement: "#3f6b3a", navire: "#1f4e5a", piece_navire: "#1f4e5a", monture: "#7a4b2a", monnaie: "#7a5a22",
};
const ICONES_ABSENTES = new Set();
export const iconeDuType = (type) => ICONES_TYPE[type] || "catalogue";

export function insigneImage(i, classe) {
  const src = srcSure(i.icone);
  if (src && !ICONES_ABSENTES.has(src)) {
    const img = h("img", { classe: classe || "", src, alt: "", loading: "lazy", decoding: "async" });
    img.addEventListener("error", () => { ICONES_ABSENTES.add(src); img.replaceWith(pastilleGravee(i, classe)); }, { once: true });
    return img;
  }
  return pastilleGravee(i, classe);
}
/** La pastille gravée d'un élément sans icône : son initiale, la teinte et l'icône de son type. */
const MOTS_VIDES = new Set(["fruit", "de", "du", "des", "la", "le", "les", "l", "d", "un", "une", "the", "of", "a"]);
/** L'initiale qui distingue : « Fruit de la Glace » → G (les mots communs du début sont sautés). */
function initialeParlante(nom) {
  const mots = String(sansEmoji(nom || "")).split(/[\s'’\-]+/u).filter((m) => /[\p{L}\p{N}]/u.test(m));
  const mot = mots.find((m) => !MOTS_VIDES.has(m.toLocaleLowerCase("fr"))) || mots[0] || "";
  return (mot.match(/[\p{L}\p{N}]/u) || [""])[0].toLocaleUpperCase("fr");
}
export function pastilleGravee(i, classe) {
  const lettre = initialeParlante(i.nom);
  return h("span", { classe: "monogramme gravee " + (classe || ""), "aria-hidden": "true", vars: { "--teinte": TEINTES_TYPE[i.type] || "#7a5a22" } },
    lettre ? h("span", { classe: "monogramme-lettre" }, lettre) : icone(iconeDuType(i.type), "monogramme-seul"),
    lettre ? icone(iconeDuType(i.type), "monogramme-type") : null);
}
/** Une pastille gravée pour un nom seul (logo absent, élément inconnu). */
export const monogramme = (nom, classe, type) => pastilleGravee({ nom, type }, classe);
/** Un logo de `site/logos/` (ou une adresse du serveur) : l'image, ou la pastille gravée de son initiale si elle manque. */
export function logo(src, nom, classe) {
  const s = srcSure(src);
  if (!s || ICONES_ABSENTES.has(s)) return monogramme(nom, classe);
  const img = h("img", { classe: classe || "", src: s, alt: nom, loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => { ICONES_ABSENTES.add(s); img.replaceWith(monogramme(nom, classe)); }, { once: true });
  return img;
}

function photo(src, nom) {
  if (!src) return h("span", { classe: "affiche-photo vide", "aria-hidden": "true" }, icone("personne"));
  const img = h("img", { classe: "affiche-photo", src, alt: "Portrait de " + nom, loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" });
  img.addEventListener("error", () => img.replaceWith(h("span", { classe: "affiche-photo vide", "aria-hidden": "true" }, icone("personne"))), { once: true });
  return img;
}
const classeNom = (n) => (n > 22 ? " tres-long" : n > 15 ? " long" : n > 11 ? " moyen" : "");

/** L'affiche. o : { taille: "mini" | "normale" | "grande", clic } */
export function affiche(a, cat, o = {}) {
  const nom = nomAffiche(a);
  const ins = insignes(a, cat);
  const grade = gradeDe(a, cat);
  const visibles = ins.slice(0, 6);
  const etiquette = [nom, a.surnom ? "« " + a.surnom + " »" : "", nombre(a.prime || 0) + " berrys", grade].filter(Boolean).join(", ");
  return h(o.clic ? "button" : "article", {
    classe: "affiche taille-" + (o.taille || "normale") + (a._attente ? " en-attente" : "") + (a.retire_le ? " retiree" : ""),
    type: o.clic ? "button" : null, onclick: o.clic || null, "aria-label": o.clic ? "Affiche de " + etiquette : null,
    vars: { "--incl": ((Number(String(a.id).replace(/\D/g, "").slice(-2)) || String(a.id).length) % 5 - 2) * 0.45 + "deg" },
  },
  h("div", { classe: "affiche-papier" },
    h("div", { classe: "affiche-portrait" }, photo(portrait(a), nom)),
    h("span", { classe: "affiche-cadre", "aria-hidden": "true" }),
    h("span", { classe: "affiche-clou", "aria-hidden": "true" }),
    h("p", { classe: "affiche-grade" }, grade || " "),
    h("p", { classe: "affiche-surnom" }, a.surnom ? "« " + sansEmoji(a.surnom) + " »" : " "),
    h("p", { classe: "affiche-nom" + classeNom(nom.length) }, nom),
    h("p", { classe: "affiche-prime" }, primeNoeud(a.prime || 0)),
    h("ul", { classe: "affiche-insignes", "aria-label": "Insignes" },
      visibles.map((i) => h("li", { classe: "insigne" + (i.existe && i.actif !== false ? "" : " inconnu"), title: i.typeNom + " : " + i.nom }, insigneImage(i, "insigne-img"), h("span", { classe: "sr" }, i.nom))),
      ins.length > visibles.length ? h("li", { classe: "insigne plus", title: ins.slice(6).map((i) => i.nom).join(", ") }, h("span", { classe: "monogramme insigne-img" }, "+" + (ins.length - 6))) : null),
    TAMPONS[a.statut] ? h("span", { classe: "affiche-tampon" }, TAMPONS[a.statut]) : null,
    a.retire_le ? h("span", { classe: "affiche-tampon corbeille" }, "Corbeille") : null,
    a._attente ? h("span", { classe: "affiche-attente" }, a._attente === "conflit" ? "Conflit à régler" : "En attente d'envoi") : null));
}

/** Une fiche vierge : un membre du clan sans affiche (le cadre est là, le portrait attend). */
export function afficheVierge(m, creer) {
  const nom = sansEmoji(m.nom) || m.pseudo || "Sans nom";
  return h("button", { classe: "affiche taille-mini vierge", type: "button", onclick: creer, "aria-label": "Créer l'affiche de " + nom },
    h("div", { classe: "affiche-papier" },
      h("div", { classe: "affiche-portrait" }, photo(srcSure(m.avatar), nom)),
      h("span", { classe: "affiche-cadre", "aria-hidden": "true" }),
      h("p", { classe: "affiche-nom" + classeNom(nom.length) }, nom),
      h("p", { classe: "affiche-creer" }, icone("plume"), h("span", {}, "Créer l'affiche"))));
}
