// reglages.js — « Réglages » (La Capitainerie, 27/10/2026) : ce qui se règle pour tout le site, en sous-onglets —
// Textes & noms (textes.js, l'ancienne rubrique de la Capitainerie) · Nettoyage (discord.js, l'ancienne rubrique du
// Port). Les anciennes adresses (#capitainerie/textes, #port/nettoyage) mènent ici (noyau.js, ALIAS).
//
// AJOUTER UN SOUS-ONGLET (« Sécurité ») : UNE ligne dans SOUS_REGLAGES — [clé, nom, icône, rendu] —, le rendu ayant la
// forme d'une rubrique : (vue, ctx) → { maj, majJeu, majFile, quitter } (chacun facultatif). Son adresse :
// #capitainerie/reglages/<clé>. Son nom se renomme (Textes & noms) une fois déclaré dans textes.SITE_SOUS
// (« capitainerie », « reglages ») : le test T13 compare les deux listes.

import { h, icone, ajouter } from "./dom.js";
import { nommerOnglets } from "./noyau.js";
import { textes } from "./textes.js";
import { nettoyage } from "./discord.js";

export const SOUS_REGLAGES = nommerOnglets("site.sous.capitainerie.reglages", [["textes", "Textes & noms", "plume", textes], ["nettoyage", "Nettoyage", "nettoyage", nettoyage]]);

export function reglages(vue, ctx = {}) {
  const choisi = SOUS_REGLAGES.find(([k]) => k === ctx.sous) || SOUS_REGLAGES[0];
  const onglets = h("div", { classe: "sous-onglets", role: "tablist", "aria-label": "Réglages" },
    SOUS_REGLAGES.map(([k, l, ic]) => h("a", { classe: "etiquette", role: "tab", href: "#capitainerie/reglages/" + k, "aria-selected": String(k === choisi[0]) }, icone(ic), l)));
  const scene = h("div", { classe: "pile", role: "tabpanel", "aria-label": choisi[1] });
  ajouter(vue, [onglets, scene]);
  return choisi[3](scene, ctx) || null;
}
