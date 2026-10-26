// mode.js — « Mode simple » (par défaut) ou « Tout afficher ». En mode simple, les chiffres, les graphiques, les filtres
// avancés et les détails techniques sont cachés : la classe `mode-simple` sur <html>, et chaque bloc avancé porte la
// classe `avance` (rangement.css). Le choix est gardé pour cette personne, sur cet appareil.

import { h, icone } from "./dom.js";
import { emettre } from "./noyau.js";

const CLE = "capitainerie.mode";
let simple = true;
try { simple = localStorage.getItem(CLE) !== "tout"; } catch (e) { simple = true; }   // stockage refusé : le mode simple

export const modeSimple = () => simple;
export function appliquerMode() {
  document.documentElement.classList.toggle("mode-simple", simple);
  for (const b of document.querySelectorAll(".bascule-mode")) b.setAttribute("aria-pressed", String(!simple));
}
export function changerMode(s) {
  simple = !!s;
  try { localStorage.setItem(CLE, simple ? "simple" : "tout"); } catch (e) { /* le choix vaut pour cet onglet */ }
  appliquerMode();
  emettre("mode", simple);
}
appliquerMode();   // dès le chargement : jamais un éclair de chiffres avant le mode simple

/** Le bouton du titre de chaque rubrique : « Tout afficher » en mode simple, « Mode simple » sinon (le libellé suit la
 *  classe de <html>, sans écoute à défaire). */
export function basculeMode() {
  return h("button", { classe: "bascule-mode", type: "button", "aria-pressed": String(!simple), onclick: () => changerMode(!simple) },
    h("span", { classe: "bm-simple", title: "Montrer aussi les chiffres, les graphiques, les filtres avancés et les détails" }, icone("oeil"), h("span", {}, "Tout afficher")),
    h("span", { classe: "bm-tout", title: "Revenir à l'essentiel : sans les chiffres, les graphiques ni les détails" }, icone("masquer"), h("span", {}, "Mode simple")));
}
