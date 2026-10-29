// wiki_icones.js — les icônes du Grimoire, dessinées pour lui (29/10/2026). Le fondateur : « je déteste les émojis…
// je préfère que ce soit créé de toutes pièces, propre, qui correspond au thème ». Un trait de laiton sur une grille de
// 24 : chaque icône est une liste de tracés SVG (aucun fichier chargé, aucune police d'émojis).

const P = {
  ancre: ["M12 3a2 2 0 1 1 0 4a2 2 0 1 1 0-4z", "M12 7v14", "M8 11h8", "M4 14c0 4 4 7 8 7s8-3 8-7", "M4 14l-1.5 1.5M4 14l1.5 1.5M20 14l-1.5 1.5M20 14l1.5 1.5"],
  gouvernail: ["M12 5a7 7 0 1 1 0 14a7 7 0 1 1 0-14z", "M12 9.5a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5z", "M12 2v7M12 15v7M2 12h7M15 12h7", "M5 5l4.2 4.2M14.8 14.8L19 19M19 5l-4.2 4.2M9.2 14.8L5 19"],
  carte: ["M3 6l6-2l6 2l6-2v14l-6 2l-6-2l-6 2z", "M9 4v14M15 6v14", "M5.5 10l2 1.5M7.5 10l-2 1.5", "M17 11.5l1.5 1.5"],
  livre: ["M4 5c3-1.5 5.5-1.5 8 0v14c-2.5-1.5-5-1.5-8 0z", "M20 5c-3-1.5-5.5-1.5-8 0v14c2.5-1.5 5-1.5 8 0z", "M6.5 8.5c1.5-.5 2.5-.5 3.5 0M6.5 11.5c1.5-.5 2.5-.5 3.5 0M14 8.5c1-.5 2-.5 3.5 0"],
  parchemin: ["M7 4h11a2 2 0 0 1 0 4h-1v10a2 2 0 0 1-2 2H6a2 2 0 0 1 0-4h1z", "M7 16V4M6 20a2 2 0 0 0 2-2v-2", "M10 9h5M10 12h5"],
  pellicule: ["M4 6h16v12H4z", "M4 9h16M4 15h16", "M7 6v3M10.5 6v3M14 6v3M17.5 6v3M7 15v3M10.5 15v3M14 15v3M17.5 15v3", "M11 10.8v2.4l2-1.2z"],
  maillons: ["M10 14a4 4 0 0 1 0-5.6l2-2a4 4 0 0 1 5.6 5.6l-1 1", "M14 10a4 4 0 0 1 0 5.6l-2 2a4 4 0 0 1-5.6-5.6l1-1"],
  marteau: ["M14 4l6 6l-2 2l-6-6z", "M13 7l-9 9a1.5 1.5 0 0 0 2 2l9-9"],
  masque: ["M5 5c4 1.5 10 1.5 14 0c1 6-1 13-7 14c-6-1-8-8-7-14z", "M8.5 10.5c1 .8 2 .8 3 0M12.5 10.5c1 .8 2 .8 3 0", "M9.5 15c1.5 1 3.5 1 5 0"],
  drapeau: ["M5 21V3", "M5 4c3-1.5 5 1.5 8 0s5 1.5 6 0v8c-1 1.5-3-1.5-6 0s-5-1.5-8 0"],
  vague: ["M2 9c2.5 0 2.5-2 5-2s2.5 2 5 2s2.5-2 5-2s2.5 2 5 2", "M2 14c2.5 0 2.5-2 5-2s2.5 2 5 2s2.5-2 5-2s2.5 2 5 2", "M2 19c2.5 0 2.5-2 5-2s2.5 2 5 2s2.5-2 5-2s2.5 2 5 2"],
  etoile: ["M12 3l2.6 5.6l6.1.7l-4.5 4.2l1.2 6l-5.4-3l-5.4 3l1.2-6l-4.5-4.2l6.1-.7z"],
  epees: ["M5 3l9 9M3 5l9 9", "M4 4l-1-1M19 3l-9 9M21 5l-9 9", "M20 4l1-1", "M7 15l-3 3l2 2l3-3M17 15l3 3l-2 2l-3-3"],
  fruit: ["M12 7c-4-2-8 1-7 6s4 8 7 7c3 1 6-2 7-7s-3-8-7-6z", "M12 7c0-2 1-3.5 3-4", "M9 11c.5-1 1.5-1.5 2.5-1.5M14 13c1 .3 1.8 1 2 2"],
  spirale: ["M12 12a1.5 1.5 0 1 1 1.5 1.5a3 3 0 1 1-3-3a4.5 4.5 0 1 1 4.5 4.5a6 6 0 1 1-6-6a7.5 7.5 0 1 1 7.5 7.5"],
  carte_jeu: ["M6 3h9a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z", "M10.5 9l2 3l-2 3l-2-3z", "M19 7l1.5.5a2 2 0 0 1 1.2 2.5l-3 9"],
  affiche: ["M5 3h14v18H5z", "M8 7h8M8 10h8", "M12 13a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5z", "M5 3l1.5 1.5M19 3l-1.5 1.5"],
  poing: ["M7 11V8a1.5 1.5 0 0 1 3 0v2M10 9.5V7a1.5 1.5 0 0 1 3 0v3M13 9.5V8a1.5 1.5 0 0 1 3 0v3", "M16 10.5a1.5 1.5 0 0 1 3 0V14a6 6 0 0 1-6 6h-1a5 5 0 0 1-5-5v-4"],
  dague: ["M12 2l2 9h-4z", "M8 11h8", "M12 11v5", "M10.5 16h3l-.5 5h-2z"],
  boussole: ["M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18z", "M15.5 8.5l-2 5l-5 2l2-5z", "M12 3v2M12 19v2M3 12h2M19 12h2"],
  navire: ["M3 15l2 4h14l2-4z", "M12 3v12", "M12 4l6 9h-6", "M12 6l-5 7h5", "M2 21c2 0 2-1 4-1s2 1 4 1s2-1 4-1s2 1 4 1s2-1 4-1"],
  canon: ["M4 13l12-6l2 4l-12 6z", "M8 16a3 3 0 1 1-6 0a3 3 0 1 1 6 0z", "M18 9l2-1", "M14 18a2 2 0 1 1 4 0a2 2 0 1 1-4 0z"],
  patte: ["M12 13c-3 0-5 2.5-5 4.5S9 20 12 20s5-.5 5-2.5S15 13 12 13z", "M6 9.5a1.5 2 0 1 1 3 0a1.5 2 0 1 1-3 0zM15 9.5a1.5 2 0 1 1 3 0a1.5 2 0 1 1-3 0zM9.5 6a1.5 2 0 1 1 3 0a1.5 2 0 1 1-3 0zM11.5 6a1.5 2 0 1 1 3 0"],
  piece: ["M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18z", "M12 6a6 6 0 1 1 0 12a6 6 0 1 1 0-12z", "M10 10.5c0-1 1-1.5 2-1.5s2 .5 2 1.5s-1 1.3-2 1.5s-2 .5-2 1.5s1 1.5 2 1.5s2-.5 2-1.5M12 8v1M12 15v1"],
  crane: ["M12 3c-4.5 0-7.5 3-7.5 7c0 2.5 1.2 4 2.5 5v3h10v-3c1.3-1 2.5-2.5 2.5-5c0-4-3-7-7.5-7z", "M9 11a1.5 1.5 0 1 1 0 .1zM15 11a1.5 1.5 0 1 1 0 .1z", "M12 13.5l-1 2h2z", "M10 18v3M14 18v3"],
  ile: ["M2 18c2.5 0 2.5-1.5 5-1.5s2.5 1.5 5 1.5s2.5-1.5 5-1.5s2.5 1.5 5 1.5", "M5 16c1.5-3 4-4 7-4s5.5 1 7 4", "M12 12V6", "M12 6c-2-2-5-2-6.5 0M12 6c2-2 5-2 6.5 0M12 6c-1-2.5-3-3.5-5-3M12 6c1-2.5 3-3.5 5-3"],
  engrenage: ["M12 8.5a3.5 3.5 0 1 1 0 7a3.5 3.5 0 1 1 0-7z", "M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"],
  lecture: ["M8 5l11 7l-11 7z"],
  verifie: ["M5 12.5l4.5 4.5L19 7"],
  alerte: ["M12 3l10 18H2z", "M12 10v5M12 18v.5"],
  fermer: ["M6 6l12 12M18 6L6 18"],
  fleche: ["M15 5l-7 7l7 7"],
  discord: ["M8 7c2.5-1 5.5-1 8 0l1.5 1c1.5 2.5 2 5 2 8c-1.5 1.2-3 2-4.5 2.5l-1-2M8 7L6.5 8C5 10.5 4.5 13 4.5 16c1.5 1.2 3 2 4.5 2.5l1-2", "M8 16c2.5 1 5.5 1 8 0", "M9.5 12a1 1.2 0 1 1 0 .1zM14.5 12a1 1.2 0 1 1 0 .1z"],
  youtube: ["M3 8c0-1.7 1.3-3 3-3h12c1.7 0 3 1.3 3 3v8c0 1.7-1.3 3-3 3H6c-1.7 0-3-1.3-3-3z", "M10 9v6l5-3z"],
  roblox: ["M6 3l15 4l-4 14l-15-4z", "M10.5 10l3.5 1l-1 3.5l-3.5-1z"],
  x: ["M4 4l16 16M20 4L4 20", "M4 4h4.5l11.5 16h-4.5z"],
  tiktok: ["M14 3v11.5a3.5 3.5 0 1 1-3.5-3.5", "M14 3c.3 2.6 2 4.4 5 4.6"],
  instagram: ["M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4z", "M12 8.5a3.5 3.5 0 1 1 0 7a3.5 3.5 0 1 1 0-7z", "M17.2 6.6v.1"],
  plume: ["M20 4c-6 0-11 4-13 11l-2 5", "M20 4c0 6-4 11-11 12", "M7 15l4-4"],
  oeil: ["M2 12c2.5-4.5 6-7 10-7s7.5 2.5 10 7c-2.5 4.5-6 7-10 7s-7.5-2.5-10-7z", "M12 9a3 3 0 1 1 0 6a3 3 0 1 1 0-6z"],
};

/** <svg class="w-ico"> du nom donné (vide si inconnu). */
export function icone(nom, classe = "") {
  const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", ("w-ico " + classe).trim());
  for (const d of P[nom] || []) {
    const p = document.createElementNS(ns, "path");
    p.setAttribute("d", d);
    svg.append(p);
  }
  return svg;
}

export const PAR_TYPE = { metier: "marteau", race: "masque", faction: "drapeau", mer: "vague", trait: "etoile", classe: "epees",
  fruit: "fruit", haki: "spirale", carte_haki: "carte_jeu", poster: "affiche", style: "poing", arme: "dague", equipement: "boussole",
  navire: "navire", piece_navire: "canon", monture: "patte", monnaie: "piece", boss: "crane", lieu: "ile", systeme: "engrenage" };
export const PAR_ONGLET = { accueil: "ancre", encyclo: "boussole", jeu: "gouvernail", monde: "carte", lore: "livre", fiches: "parchemin", actus: "pellicule", liens: "maillons" };
