// equipage_accueil.js — l'accueil du site de l'équipage : la page « dédiée à la piraterie » que la direction compose.
// Des blocs rangés (bandeau, texte, image, actualités, événements à venir, équipiers à l'honneur, analyses) ; pour
// l'équipage, la lecture seule ; pour le fondateur et la direction, le MODE ÉDITION : modifier, ajouter, monter,
// descendre, masquer, supprimer un bloc, publier une actualité (avec son image). Chaque écriture part à
// `/tableau/espace/api/equipage/…` (tête seule, origine vérifiée, journal du site) et la réponse redessine l'accueil.

import { h, icone, remplacer, ajouter, sansEmoji, srcSure, nombre, date, depuis, dans, majuscule, quantite, compte, egaux } from "./dom.js";
import { poster } from "./api.js";
import {
  bouton, boutonIcone, toast, pancarte, confirmer, vide, groupe, paginer, champ, saisie, zoneTexte, interrupteur, caseACocher,
  tuile, tuiles, barres, barresH, ENCRES, pastille, tampon,
} from "./ui.js";
import { affiche, insigneImage, primeNoeud, nomAffiche } from "./affiche.js";
import { E, T, lire, texteRiche, textePlat, ouvrirAffiche, afficheParId, catalogue, sceau } from "./equipage_commun.js";

// ─── Les types de blocs ─────────────────────────────────────────────────────
const TYPES = {
  bandeau: { nom: "Bandeau", icone: "drapeau", phrase: "Un grand titre en tête de page, avec une image si tu veux." },
  texte: { nom: "Texte", icone: "parchemin", phrase: "Un titre et quelques lignes : le code, une règle, un mot du capitaine." },
  image: { nom: "Image", icone: "image", phrase: "Une image seule, avec sa légende." },
  actualites: { nom: "Actualités", icone: "journal", phrase: "Les nouvelles de la direction, puis les annonces, recrues et affiches." },
  evenements: { nom: "Événements à venir", icone: "calendrier", phrase: "Les prochaines sorties publiées sur Discord, avec leurs réponses." },
  honneur: { nom: "Équipiers à l'honneur", icone: "etoile", phrase: "Des affiches choisies, ou les plus hautes primes." },
  analyses: { nom: "Analyses", icone: "apercu", phrase: "L'équipage en chiffres : métiers, races, primes, recrues…" },
};
const PARTIES = [["membres", "L'équipage"], ["metiers", "Métiers"], ["races", "Races"], ["factions", "Factions"], ["grades", "Grades"],
  ["statuts", "Statuts"], ["primes", "Primes"], ["niveaux", "Niveaux"], ["recrues", "Recrues par mois"], ["evenements", "Sorties en mer"]];
const GENRES = { direction: ["Mot de la direction", "plume"], annonce: ["Annonce", "annonces"], evenement: ["Événement", "calendrier"],
  recrue: ["Nouvelle recrue", "membres"], affiche: ["Nouvelle affiche", "affiches"] };

let zone = null;
let titreRub = null;

/** L'onglet Accueil. `titre` : l'en-tête de la rubrique (caché à l'œil quand un bandeau ouvre la page). */
export function rendre(corps, titre) {
  zone = corps;
  titreRub = titre;
  if (!E.accueil) {
    remplacer(zone, h("div", { classe: "pile", "aria-hidden": "true" }, h("div", { classe: "squelette" }), h("div", { classe: "squelette" })));
    recharger(true);
    return;
  }
  dessiner();
}

/** Relit l'accueil (au démarrage, chaque minute) ; ne redessine que s'il a changé. */
export async function recharger(force) {
  const r = await lire("accueil");
  if (!r.ok) {
    if (zone && zone.isConnected && !E.accueil) remplacer(zone, vide("L'accueil ne s'est pas chargé", r.erreur || "Recharge la page dans un instant.", "attention"));
    return;
  }
  if (!force && egaux(r.donnees, E.accueil)) return;
  E.accueil = r.donnees;
  if (zone && zone.isConnected) dessiner();
}

function accepter(accueil) {
  if (!accueil) return;
  E.accueil = accueil;
  if (zone && zone.isConnected) dessiner();
}

function dessiner() {
  const a = E.accueil;
  const edition = E.peutEditer && E.modeEdition;
  const blocs = a.blocs || [];
  const premierVisible = blocs.find((b) => edition || b.visible !== false);
  //  Un bandeau en tête : il EST le titre de la page (son h1) ; l'en-tête de rubrique s'efface (pas deux titres).
  const bandeauEnTete = !!premierVisible && premierVisible.type === "bandeau";
  if (titreRub) titreRub.classList.toggle("titre-cache", bandeauEnTete);
  const contenu = [];
  if (E.peutEditer) contenu.push(barreEdition());
  if (!blocs.some((b) => edition || b.visible !== false)) {
    contenu.push(vide("L'accueil est vide", E.peutEditer ? "Ajoute un premier bloc : « Modifier l'accueil », puis « Ajouter un bloc »." : "La direction prépare l'accueil.", "navire"));
  }
  blocs.forEach((b, i) => {
    if (!edition && b.visible === false) return;   // hors édition, la direction voit l'accueil comme l'équipage
    let rendu;
    try { rendu = rendreBloc(b, a.donnees || {}, bandeauEnTete && b === premierVisible); } catch (e) {
      console.error("[equipage] bloc", b.type, e);
      rendu = vide("Ce bloc n'a pas pu s'afficher", "", "attention");
    }
    contenu.push(cadenas(h("section", { classe: "bloc-eq bloc-" + b.type + (b.visible === false ? " masque" : "") + (edition ? " en-edition" : ""), "aria-label": TYPES[b.type] ? TYPES[b.type].nom : "Bloc" },
      edition ? barreBloc(b, i, blocs.length) : null, rendu), "accueil:" + b.id));
  });
  remplacer(zone, ...contenu);
}

// ═══ LES BLOCS ═══════════════════════════════════════════════════════════════
function rendreBloc(b, donnees, titrePage) {
  const c = b.contenu || {};
  switch (b.type) {
    case "bandeau": return blocBandeau(c, titrePage);
    case "texte": return blocTexte(c);
    case "image": return blocImage(c);
    case "actualites": return blocActualites(c, donnees.actualites || {});
    case "evenements": return blocEvenements(c, donnees.evenements || []);
    case "honneur": return blocHonneur(b, c, (donnees.honneur || {})[b.id] || []);
    case "analyses": return blocAnalyses(c, donnees.analyses || null);
    default: return null;
  }
}

/** Le titre d'un bloc : sceau, titre, filet d'encre (comme les sections du site), et le compte à droite. */
function tete(titre, nomIcone, compteTexte, ...droite) {
  return h("div", { classe: "section-tete tete-bloc" }, h("h2", {}, sceau(nomIcone), h("span", { classe: "titre-texte" }, titre)),
    compteTexte ? h("span", { classe: "compte" }, compteTexte) : null, droite.filter(Boolean).length ? h("div", { classe: "rangee" }, droite) : null);
}

function blocBandeau(c, titrePage) {
  const src = srcSure(c.image);
  const img = src ? h("img", { classe: "bandeau-eq-image", src, alt: "", decoding: "async" }) : null;
  if (img) img.addEventListener("error", () => img.remove(), { once: true });
  return h("div", { classe: "bandeau-eq" + (src ? " avec-image" : "") }, img,
    h("div", { classe: "bandeau-eq-texte" }, h(titrePage ? "h1" : "h2", { classe: "bandeau-eq-titre" }, sansEmoji(c.titre) || "L'équipage"),
      c.sous_titre ? h("p", { classe: "bandeau-eq-sous" }, c.sous_titre) : null));
}

function blocTexte(c) {
  return h("div", { classe: "cadre bloc-texte-cadre" }, c.titre ? h("h2", { classe: "cadre-titre" }, c.titre) : null, texteRiche(c.texte));
}

function blocImage(c) {
  const src = srcSure(c.image);
  if (!src) return vide("Image absente", "", "image");
  const img = h("img", { src, alt: c.legende || "", loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => img.replaceWith(h("span", { classe: "image-absente image-eq-absente", "aria-hidden": "true" }, icone("image"))), { once: true });
  return h("figure", { classe: "image-eq" }, img, c.legende ? h("figcaption", {}, c.legende) : null);
}

// ─── Les actualités ─────────────────────────────────────────────────────────
function actualitesDe(c, donnees) {
  const direction = donnees.direction || [];
  const auto = c.automatiques === false ? [] : donnees.auto || [];
  return [...direction.filter((a) => a.epingle), ...[...direction.filter((a) => !a.epingle), ...auto].sort((x, y) => (y.quand || 0) - (x.quand || 0))];
}
function blocActualites(c, donnees) {
  const toutes = actualitesDe(c, donnees);
  const n = Math.max(1, Math.min(12, Number(c.nombre) || 5));
  const edition = E.peutEditer && E.modeEdition;
  const plus = toutes.length > n ? bouton("Toutes les actualités (" + nombre(toutes.length) + ")", { classe: "p", icone: "journal", onclick: () => toutesActualites(c, toutes) }) : null;
  return h("div", { classe: "section" },
    tete(c.titre || "Actualités", "journal", toutes.length ? compte(toutes.length, "nouvelle") : "", E.peutEditer ? bouton("Publier une actualité", { classe: "p", icone: "plume", onclick: () => editerActualite(null) }) : null),
    toutes.length ? h("div", { classe: "actus" }, toutes.slice(0, n).map((a) => carteActu(a, edition)))
      : vide("Rien de neuf pour le moment", "Les nouvelles du bord arriveront ici.", "journal"),
    plus ? h("div", { classe: "plus" }, plus) : null);
}
function carteActu(a, edition) {
  const [genre, ic] = GENRES[a.genre] || GENRES.annonce;
  const src = srcSure(a.image);
  const visuel = src ? h("img", { classe: "actu-image", src, alt: "", loading: "lazy", decoding: "async" }) : h("span", { classe: "actu-sceau", "aria-hidden": "true" }, icone(ic));
  if (src) visuel.addEventListener("error", () => visuel.replaceWith(h("span", { classe: "actu-sceau", "aria-hidden": "true" }, icone(ic))), { once: true });
  const quand = a.evenement && a.evenement.quand ? (a.evenement.phase === "termine" ? "a eu lieu le " + date(a.evenement.quand) : a.evenement.phase === "annule" ? "prévu le " + date(a.evenement.quand) : "le " + date(a.evenement.quand, true))
    : depuis(a.quand);
  const ouvrir = a.affiche ? () => ouvrirAffiche(a.affiche) : () => lireActu(a);
  const carte = h("article", { classe: "actu" + (a.epingle ? " epinglee" : "") + " actu-" + (a.genre || "annonce") },
    visuel,
    h("div", { classe: "actu-corps" },
      h("div", { classe: "actu-tete" },
        h("h3", { classe: "actu-titre" }, h("button", { classe: "lien-titre", type: "button", onclick: ouvrir }, sansEmoji(a.titre) || genre)),
        a.epingle ? tampon("Épinglée", "", true) : null),
      h("p", { classe: "meta" }, genre + " · " + quand + (a.evenement && a.evenement.lieu ? " · " + a.evenement.lieu : "")),
      a.texte ? h("p", { classe: "actu-extrait coupe2" }, textePlat(a.texte)) : null,
      edition && a.genre === "direction" ? h("div", { classe: "rangee" },
        bouton("Modifier", { classe: "p", icone: "modifier", onclick: () => editerActualite(a) }),
        bouton("Retirer", { classe: "p discret danger", icone: "supprimer", onclick: () => retirerActualite(a) })) : null));
  return edition && a.genre === "direction" ? cadenas(carte, "actualite:" + a.id) : carte;
}
function lireActu(a) {
  const [genre] = GENRES[a.genre] || GENRES.annonce;
  const p = pancarte({ titre: sansEmoji(a.titre) || genre, sous: genre + " · " + (a.quand ? date(a.quand, true) : ""), icone: (GENRES[a.genre] || GENRES.annonce)[1], taille: "large" });
  const src = srcSure(a.image);
  ajouter(p.corps, [src ? h("img", { classe: "actu-image-grande", src, alt: "", decoding: "async" }) : null,
    a.evenement && a.evenement.quand ? h("p", { classe: "meta" }, icone("calendrier"), " ", majuscule(date(a.evenement.quand, true)) + (a.evenement.lieu ? " · " + a.evenement.lieu : "")) : null,
    a.texte ? texteRiche(a.texte) : h("p", { classe: "aide" }, "Pas de texte de plus.")]);
  ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
}
function toutesActualites(c, toutes) {
  const p = pancarte({ titre: c.titre || "Actualités", sous: compte(toutes.length, "nouvelle"), icone: "journal", taille: "large" });
  ajouter(p.corps, [paginer("eq-actus-toutes", toutes, (a) => carteActu(a, E.peutEditer && E.modeEdition), { classe: "actus", pas: 12 })]);
  ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
}

// ─── Les événements à venir ─────────────────────────────────────────────────
const JOUR_COURT = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", weekday: "short" });
const QUANTIEME = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", day: "numeric" });
const MOIS_COURT = new Intl.DateTimeFormat("fr-FR", { timeZone: "Europe/Paris", month: "short" });
function blocEvenements(c, evts) {
  const n = Math.max(1, Math.min(8, Number(c.nombre) || 4));
  return h("div", { classe: "section" }, tete(c.titre || "Événements à venir", "calendrier", evts.length ? compte(evts.length, "sortie") : ""),
    evts.length ? h("div", { classe: "evts-eq" }, evts.slice(0, n).map(carteEvt))
      : vide("Aucune sortie prévue", "Les prochaines sorties seront annoncées sur Discord et ici.", "navire"));
}
function carteEvt(e) {
  const d = e.quand ? new Date(e.quand * 1000) : null;
  const r = e.reponses || {};
  const enCours = e.phase === "en_cours";
  return h("article", { classe: "feuillet evt-eq" + (enCours ? " en-cours" : "") },
    h("div", { classe: "evt-sceau", "aria-hidden": "true" },
      d ? [h("span", { classe: "evt-jour" }, JOUR_COURT.format(d).replace(".", "")), h("b", {}, QUANTIEME.format(d)), h("span", { classe: "evt-mois" }, MOIS_COURT.format(d).replace(".", ""))] : icone("calendrier")),
    h("div", { classe: "evt-corps" },
      h("h3", {}, sansEmoji(e.titre) || "Sortie en mer"),
      h("p", { classe: "meta" }, enCours ? h("b", { classe: "evt-maintenant" }, "En cours") : e.quand ? majuscule(date(e.quand, true)) + " · " + dans(e.quand) : "Date à venir",
        e.lieu ? " · " + e.lieu : "", e.duree_min ? " · " + duree(e.duree_min) : ""),
      e.texte ? h("p", { classe: "evt-texte coupe2" }, textePlat(e.texte)) : null,
      h("div", { classe: "pastilles" },
        pastille(quantite(r.d || 0, "disponible(s)"), ENCRES.vert), pastille(quantite(r.p || 0, "peut-être"), ENCRES.ambre),
        r.n ? pastille(quantite(r.n, "absent(s)"), ENCRES.cire) : null,
        e.places ? pastille(Math.max(0, e.places - (r.d || 0)) + " place" + (e.places - (r.d || 0) > 1 ? "s" : "") + " sur " + e.places, ENCRES.mer) : null)));
}
const duree = (m) => (m >= 60 ? Math.floor(m / 60) + " h" + (m % 60 ? " " + String(m % 60).padStart(2, "0") : "") : m + " min");

// ─── Les équipiers à l'honneur ──────────────────────────────────────────────
function blocHonneur(b, c, ids) {
  const affiches = ids.map(afficheParId).filter(Boolean);
  return h("div", { classe: "section" }, tete(c.titre || "Équipiers à l'honneur", "etoile", ""),
    c.texte ? h("p", { classe: "aide" }, c.texte) : null,
    affiches.length ? h("div", { classe: "grille affiches honneur" }, affiches.map((a) => affiche(a, catalogue(), { taille: "mini", clic: () => ouvrirAffiche(a.id) })))
      : vide("Personne à l'honneur pour le moment", "Les plus hautes primes apparaîtront ici.", "etoile"));
}

// ─── Les analyses ───────────────────────────────────────────────────────────
function blocAnalyses(c, an) {
  const parties = new Set(Array.isArray(c.parties) && c.parties.length ? c.parties : PARTIES.map(([k]) => k));
  const corps = [tete(c.titre || "L'équipage en chiffres", "apercu", "")];
  if (!an) { corps.push(vide("Les chiffres ne sont pas disponibles", "Ils reviendront au prochain rafraîchissement.", "apercu")); return h("div", { classe: "section" }, corps); }
  const m = an.membres || {}, pr = an.primes || {}, ev = an.evenements || {}, rec = an.recrues || {};
  const t = [];
  if (parties.has("membres")) {
    t.push(tuile({ cle: "eq-a1", lib: "Pirates du clan", val: m.clan || 0, icone: "membres", sous: compte(m.affiches || 0, "affiche") + " au mur", teinte: ENCRES.mer }));
  }
  if (parties.has("primes")) t.push(tuile({ cle: "eq-a2", lib: "Primes cumulées", texte: primeNoeud(pr.total || 0), icone: "prime", sous: pr.max ? "la plus haute : " + nombre(pr.max) : "aucune prime", teinte: ENCRES.laiton }));
  if (parties.has("recrues")) t.push(tuile({ cle: "eq-a3", lib: "Recrues", val: rec.total_12 || 0, icone: "ancre", sous: "sur douze mois · " + (rec.trente_jours || 0) + " ce mois-ci", teinte: ENCRES.vert }));
  if (parties.has("evenements")) t.push(tuile({ cle: "eq-a4", lib: "Sorties à venir", val: ev.a_venir || 0, icone: "calendrier",
    sous: ev.taux_reponse !== null && ev.taux_reponse !== undefined ? "taux de réponse : " + ev.taux_reponse + " %" : "pas encore de sortie passée", teinte: ENCRES.cire }));
  if (t.length) corps.push(tuiles(...t));
  const groupes = [];
  const rep = (cle, titre, nomIcone, lignes, vides) => {
    if (!parties.has(cle)) return;
    groupes.push(groupe({ titre, icone: nomIcone, compte: lignes.length, cle: "eq-an-" + cle, ouvert: groupes.length === 0 ? true : undefined },
      () => (lignes.length ? barresH(lignes) : h("p", { classe: "aide" }, vides))));
  };
  const avecIcone = (x) => [h("span", { classe: "lib-icone" }, x.icone !== undefined ? insigneImage({ icone: x.icone, nom: x.nom, type: x.type }, "lib-icone-img") : null, h("span", { classe: "lib-texte" }, x.nom)), x.n, x.nom + " : " + quantite(x.n, "pirate(s)")];
  rep("metiers", "Métiers", "fiches", (an.metiers || []).map(avecIcone), "Aucun métier sur les affiches.");
  rep("races", "Races", "personne", (an.races || []).map(avecIcone), "Aucune race sur les affiches.");
  rep("factions", "Factions", "drapeau", (an.factions || []).map(avecIcone), "Aucune faction sur les affiches.");
  rep("grades", "Grades", "grade", (an.grades || []).map((x) => [x.nom, x.n, x.nom + " : " + quantite(x.n, "pirate(s)")]), "Aucun grade sur les affiches.");
  rep("statuts", "Statuts", "boussole", (an.statuts || []).map((x) => [x.nom, x.n]), "Aucune affiche.");
  if (parties.has("primes")) {
    groupes.push(groupe({ titre: "Primes", icone: "prime", compte: (pr.top || []).length, cle: "eq-an-primes" }, () => h("div", { classe: "pile serree" },
      h("dl", { classe: "champs-lus" }, h("div", {}, h("dt", {}, "Moyenne"), h("dd", {}, primeNoeud(pr.moyenne || 0))), h("div", {}, h("dt", {}, "Médiane"), h("dd", {}, primeNoeud(pr.mediane || 0)))),
      (pr.top || []).length ? h("ol", { classe: "classement" }, pr.top.map((x, i) => h("li", {},
        h("span", { classe: "classement-rang" }, String(i + 1)), h("button", { classe: "lien-nom", type: "button", onclick: () => ouvrirAffiche(x.affiche) }, sansEmoji(x.nom)),
        h("span", { classe: "classement-val num" }, primeNoeud(x.prime))))) : h("p", { classe: "aide" }, "Aucune prime pour le moment."))));
  }
  if (parties.has("niveaux")) {
    const nv = an.niveaux || {};
    groupes.push(groupe({ titre: "Niveaux", icone: "grade", compte: nv.renseignes || 0, cle: "eq-an-niveaux" }, () => h("div", { classe: "pile serree" },
      h("p", { classe: "aide" }, nv.renseignes ? "Niveau moyen : " + nombre(nv.moyen) + " · le plus haut : " + nombre(nv.max) + "." : "Aucun niveau renseigné."),
      (nv.tranches || []).length ? barresH(nv.tranches.map((x) => ["Niveaux " + nombre(x.de) + " à " + nombre(x.a), x.n])) : null)));
  }
  if (parties.has("recrues")) {
    const mois = rec.mois || [];
    groupes.push(groupe({ titre: "Recrues par mois", icone: "ancre", compte: rec.total_12 || 0, cle: "eq-an-recrues" },
      () => barres(mois, Object.fromEntries(mois.map((k) => [k, { r: (rec.par_mois || {})[k] || 0 }])), [["r", ENCRES.mer, "Recrues acceptées"]], "Aucune recrue sur douze mois.")));
  }
  if (parties.has("evenements")) {
    groupes.push(groupe({ titre: "Sorties en mer", icone: "navire", compte: ev.a_venir || 0, cle: "eq-an-sorties" }, () => h("dl", { classe: "champs-lus" },
      h("div", {}, h("dt", {}, "À venir"), h("dd", {}, ev.a_venir ? compte(ev.a_venir, "sortie") : "aucune")),
      h("div", {}, h("dt", {}, "Prochaine"), h("dd", {}, ev.prochain ? sansEmoji(ev.prochain.titre) + (ev.prochain.quand ? " · " + date(ev.prochain.quand, true) : "") : "—")),
      h("div", {}, h("dt", {}, "Réponses"), h("dd", {}, ev.taux_reponse !== null && ev.taux_reponse !== undefined ? ev.taux_reponse + " % de l'équipage répond (" + compte(ev.passes || 0, "dernière sortie", "dernières sorties") + ")" : "pas encore de sortie passée")),
      h("div", {}, h("dt", {}, "Annonces lues"), h("dd", {}, ev.taux_vu !== null && ev.taux_vu !== undefined ? ev.taux_vu + " % en moyenne (« Vu »)" : "—")))));
  }
  if (groupes.length) corps.push(h("div", { classe: "groupes-analyses" }, groupes));
  return h("div", { classe: "section" }, corps);
}

// ═══ LE MODE ÉDITION (fondateur et direction) ════════════════════════════════
function barreEdition() {
  if (!E.modeEdition) {
    return h("div", { classe: "barre-edition" },
      h("p", { classe: "aide" }, icone("plume"), " Tu vois l'accueil comme l'équipage. Toi seul peux le composer."),
      h("div", { classe: "rangee" },
        bouton("Publier une actualité", { classe: "p", icone: "journal", onclick: () => editerActualite(null) }),
        bouton("Modifier l'accueil", { classe: "principal", icone: "modifier", onclick: () => { E.modeEdition = true; dessiner(); } })));
  }
  return h("div", { classe: "barre-edition active" },
    h("p", { classe: "aide" }, h("b", {}, "Mode édition. "), "Chaque bloc a ses boutons ; ce qui est masqué reste visible pour toi seul."),
    h("div", { classe: "rangee" },
      bouton("Ajouter un bloc", { classe: "p", icone: "ajouter", onclick: choisirType }),
      bouton("Publier une actualité", { classe: "p", icone: "journal", onclick: () => editerActualite(null) }),
      bouton("Terminer", { classe: "principal", icone: "valider", onclick: () => { E.modeEdition = false; dessiner(); } })));
}

function barreBloc(b, i, n) {
  const t = TYPES[b.type] || { nom: b.type, icone: "info" };
  const masque = b.visible === false;
  return h("div", { classe: "barre-bloc", role: "group", "aria-label": "Bloc " + t.nom },
    h("span", { classe: "barre-bloc-nom" }, icone(t.icone), h("span", {}, t.nom), masque ? tampon("Masqué", "encre", true) : null),
    h("div", { classe: "barre-bloc-boutons" },
      bouton("Modifier", { classe: "p", icone: "modifier", onclick: () => editerBloc(b) }),
      inactif(boutonIcone("haut", "Monter ce bloc", () => deplacer(b, "haut")), i === 0),
      inactif(boutonIcone("bas", "Descendre ce bloc", () => deplacer(b, "bas")), i === n - 1),
      boutonIcone(masque ? "oeil" : "masquer", masque ? "Montrer ce bloc à l'équipage" : "Masquer ce bloc à l'équipage", () => basculer(b)),
      boutonIcone("supprimer", "Supprimer ce bloc", () => supprimer(b), "danger")));
}

const inactif = (b, oui) => { b.disabled = !!oui; return b; };

/** Une écriture de la direction : la réponse redessine l'accueil ; un refus est dit, un conflit relit l'accueil. */
async function ecrire(nom, corps, succes) {
  const r = await poster(nom, corps);
  if (r.ok && r.donnees && r.donnees.accueil) {
    accepter(r.donnees.accueil);
    if (succes) toast(succes, "succes");
    return r;
  }
  if (r.status === 409) {
    toast("Ce bloc a changé ailleurs pendant que tu le modifiais : voici la version enregistrée.", "erreur");
    await recharger(true);
  } else toast(r.erreur || "Refusé.", "erreur");
  return r;
}
/** Un geste rapide (monter, masquer, supprimer) : refusé, avec un avis, si quelqu'un d'autre modifie ce bloc. */
const libre = (objet) => !E.direct || E.direct.siLibre(objet);
const deplacer = (b, sens) => libre("accueil:" + b.id) && ecrire("equipage/bloc/deplacer", { id: b.id, sens });
const basculer = (b) => libre("accueil:" + b.id) && ecrire("equipage/bloc/visible", { id: b.id, visible: b.visible === false }, b.visible === false ? "Bloc montré à l'équipage." : "Bloc masqué : l'équipage ne le voit plus.");
async function supprimer(b) {
  const t = TYPES[b.type] || { nom: b.type };
  if (!libre("accueil:" + b.id)) return;
  const ok = await confirmer({ titre: "Supprimer ce bloc ?", texte: "« " + ((b.contenu && (b.contenu.titre || b.contenu.legende)) || t.nom) + " » quitte l'accueil pour de bon. Pour le cacher seulement, masque-le.", libelleOk: "Supprimer", style: "danger" });
  if (ok) ecrire("equipage/bloc/supprimer", { id: b.id }, "Bloc supprimé.");
}

/** « Ajouter un bloc » : le type d'abord (une phrase pour chacun), puis son formulaire. */
function choisirType() {
  const p = pancarte({ titre: "Ajouter un bloc", sous: "Il se pose à la fin de l'accueil : monte-le ensuite où tu veux.", icone: "ajouter", taille: "large" });
  ajouter(p.corps, [h("div", { classe: "choix-types" }, Object.entries(TYPES).map(([k, t]) => h("button", { classe: "choix-type", type: "button",
    onclick: () => { p.fermer(); editerBloc({ type: k, contenu: {}, visible: true }); } }, icone(t.icone), h("b", {}, t.nom), h("span", {}, t.phrase))))]);
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() })]);
}

/** Le point d'appel UNIQUE des verrous d'édition (site/direct.js) : une seule personne à la fois sur un bloc ou une
 *  actualité. Pris par quelqu'un d'autre : lecture seule, « Demander la main » ; libéré : `relire` rouvre la dernière
 *  version. Sans le direct (l'équipage n'édite pas, ou le module manque) : rien — le serveur refuse quand même (423). */
function proteger(p, objet, titre, relire) {
  if (E.direct && objet) E.direct.protegerEditeur(p, objet, titre, { relire });
}
/** Le cadenas d'un bloc ou d'une actualité que quelqu'un d'autre modifie (mode édition). */
const cadenas = (el, objet) => (E.direct && E.modeEdition ? E.direct.avecVerrou(el, objet) : el);

/** Envoyer une image (bandeau, image, actualité) : le serveur la refait ; rend son identifiant. */
function televerser() {
  return new Promise((fin) => {
    const entree = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" });
    entree.addEventListener("change", async () => {
      const f = entree.files && entree.files[0];
      if (!f) { fin(""); return; }
      if (f.size > 8 * 1024 * 1024) { toast("8 Mo au plus.", "erreur"); fin(""); return; }
      const b64 = await new Promise((ok, ko) => { const l = new FileReader(); l.onload = () => ok(String(l.result).split(",")[1] || ""); l.onerror = ko; l.readAsDataURL(f); });
      const r = await poster("media", { nom: f.name.slice(0, 80), type: f.type, base64: b64 });
      if (r.ok && r.donnees && r.donnees.id) { toast("Image ajoutée.", "succes"); fin(r.donnees.id); } else { toast(r.erreur || "Image refusée.", "erreur"); fin(""); }
    });
    entree.click();
  });
}

/** Le choix d'une image : l'aperçu, « Choisir une image », « Retirer ». `v.image` : un identifiant ou « media/… ». */
function choixImage(v, cle, requis) {
  const zone_ = h("div", { classe: "image-choix" });
  const maj = () => {
    const src = srcSure(v[cle] ? (String(v[cle]).startsWith("media/") ? v[cle] : "media/" + v[cle]) : "");
    remplacer(zone_, src ? h("img", { src, alt: "" }) : h("span", { classe: "image-vide" }, icone("image"), requis ? "Aucune image : choisis-en une." : "Aucune image."),
      h("div", { classe: "rangee" },
        bouton(v[cle] ? "Changer l'image" : "Choisir une image", { classe: "p", icone: "image", reseau: true, onclick: async () => { const id = await televerser(); if (id) { v[cle] = id; maj(); } } }),
        v[cle] && !requis ? bouton("Retirer l'image", { classe: "p discret", onclick: () => { v[cle] = ""; maj(); } }) : null));
  };
  maj();
  return zone_;
}
const idMedia = (x) => String(x || "").replace(/^media\//, "");

/** Le formulaire d'un bloc (nouveau : `b.id` absent). */
function editerBloc(b) {
  const t = TYPES[b.type];
  if (!t) return;
  const c = JSON.parse(JSON.stringify(b.contenu || {}));
  const v = Object.assign({}, c, { image: idMedia(c.image) });
  const p = pancarte({ titre: (b.id ? "Modifier : " : "Nouveau bloc : ") + t.nom, sous: t.phrase, icone: t.icone, taille: "large" });
  if (b.id) {
    proteger(p, "accueil:" + b.id, "le bloc « " + ((c.titre || c.legende || t.nom).slice(0, 60)) + " » de l'accueil", async () => {
      await recharger(true);
      const frais = ((E.accueil && E.accueil.blocs) || []).find((x) => x.id === b.id);
      if (!frais) throw new Error("bloc retiré");
      editerBloc(frais);
    });
  }
  const champs = [];
  const texteSimple = (k, lib, max, attrs, o) => { const s = saisie(Object.assign({ value: v[k] || "", maxlength: max }, attrs || {})); s.addEventListener("input", () => { v[k] = s.value; }); return champ(lib, s, o); };
  const zoneLongue = (k, lib, max, o) => { const z = zoneTexte({ rows: 6, maxlength: max }, v[k] || ""); z.addEventListener("input", () => { v[k] = z.value; }); return champ(lib, z, o); };
  if (b.type === "bandeau") {
    champs.push(texteSimple("titre", "Titre", 80, { placeholder: "L'équipage" }), texteSimple("sous_titre", "Sous-titre", 200, { placeholder: "Le pavillon est hissé. Bienvenue à bord, matelot." }, { optionnel: true }),
      h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Image de fond ", h("span", { classe: "optionnel" }, "(facultatif : sans image, la carte marine)")), choixImage(v, "image")));
  } else if (b.type === "texte") {
    champs.push(texteSimple("titre", "Titre", 80, { placeholder: "Le code de l'équipage" }, { optionnel: true }),
      zoneLongue("texte", "Texte", 2500, { aide: "Une ligne vide sépare deux paragraphes. **Entre deux paires d'étoiles** : en gras." }));
  } else if (b.type === "image") {
    champs.push(h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Image"), choixImage(v, "image", true)), texteSimple("legende", "Légende", 200, {}, { optionnel: true }));
  } else if (b.type === "actualites") {
    if (v.nombre === undefined) v.nombre = 5;
    if (v.automatiques === undefined) v.automatiques = true;
    champs.push(texteSimple("titre", "Titre", 80, { placeholder: "Le journal de bord" }, { optionnel: true }), nombreChoix(v, "nombre", "Nouvelles montrées", 1, 12),
      interrupteur("Ajouter les nouvelles automatiques : annonces et événements publiés, recrues, nouvelles affiches", v.automatiques !== false, (x) => { v.automatiques = x; }));
  } else if (b.type === "evenements") {
    if (v.nombre === undefined) v.nombre = 4;
    champs.push(texteSimple("titre", "Titre", 80, { placeholder: "Prochaines sorties en mer" }, { optionnel: true }), nombreChoix(v, "nombre", "Sorties montrées", 1, 8),
      h("p", { classe: "aide" }, "Les sorties viennent de « Annonces & événements » (site de la direction), une fois publiées sur Discord."));
  } else if (b.type === "honneur") {
    v.affiches = Array.isArray(v.affiches) ? v.affiches.slice() : [];
    champs.push(texteSimple("titre", "Titre", 80, { placeholder: "Équipiers à l'honneur" }, { optionnel: true }), texteSimple("texte", "Phrase", 200, { placeholder: "Pour leur courage au dernier raid." }, { optionnel: true }),
      choixAffiches(v));
  } else if (b.type === "analyses") {
    v.parties = Array.isArray(v.parties) && v.parties.length ? v.parties.slice() : PARTIES.map(([k]) => k);
    champs.push(texteSimple("titre", "Titre", 80, { placeholder: "L'équipage en chiffres" }, { optionnel: true }),
      h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "Ce qui est montré"),
        h("div", { classe: "parties-choix" }, PARTIES.map(([k, lib]) => caseACocher(lib, v.parties.includes(k), (x) => { v.parties = x ? [...new Set([...v.parties, k])] : v.parties.filter((y) => y !== k); })))));
  }
  let visible = b.visible !== false;
  if (b.id) champs.push(interrupteur("Visible par l'équipage", visible, (x) => { visible = x; }));
  ajouter(p.corps, [h("div", { classe: "pile" }, champs)]);
  const ok = bouton("Enregistrer", { classe: "principal", icone: "valider", reseau: true, onclick: async () => {
    const contenu = Object.assign({}, v);
    if (b.type === "honneur" && !contenu.affiches.length) contenu.affiches = [];
    if (b.type === "analyses" && !contenu.parties.length) { toast("Choisis au moins une partie à montrer.", "erreur"); return; }
    ok.disabled = true;
    const r = await ecrire("equipage/bloc", { id: b.id || undefined, type: b.type, contenu, visible, version: b.version || 0 },
      b.id ? "Bloc enregistré." : "Bloc ajouté à la fin de l'accueil.");
    ok.disabled = false;
    if (r.ok) p.fermer();
    else if (r.donnees && r.donnees.champ) {
      const lib = { titre: "Titre", texte: "Texte", image: "Image", affiches: "Affiches", legende: "Légende", parties: "Parties" }[r.donnees.champ];
      if (lib) toast(lib + " : " + (r.donnees.erreur || "à revoir."), "erreur");
    }
  } });
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), ok]);
}

function nombreChoix(v, cle, lib, min, max) {
  const val = h("b", { classe: "reglette-valeur num" }, String(v[cle]));
  const changer = (d) => { v[cle] = Math.max(min, Math.min(max, (Number(v[cle]) || min) + d)); val.textContent = String(v[cle]); };
  return h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, lib),
    h("div", { classe: "rangee nombre-choix" }, boutonIcone("moins", "Un de moins", () => changer(-1)), val, boutonIcone("plus", "Un de plus", () => changer(1))));
}

/** Les affiches à l'honneur : les choisies d'abord, puis toutes (6 au plus) ; aucune : les plus hautes primes. */
function choixAffiches(v) {
  const toutes = ((E.equipage && E.equipage.affiches) || []).slice().sort((a, b) => nomAffiche(a).localeCompare(nomAffiche(b), "fr", { sensitivity: "base" }));
  const zone_ = h("div", { classe: "choix-honneur" });
  const maj = () => remplacer(zone_, h("p", { classe: "aide" }, v.affiches.length ? quantite(v.affiches.length, "affiche(s) choisie(s)") + " (6 au plus)." : "Aucune choisie : les trois plus hautes primes de l'équipage."),
    toutes.length ? h("div", { classe: "choix-insignes" }, toutes.map((a) => caseACocher(nomAffiche(a) + (a.surnom ? " « " + sansEmoji(a.surnom) + " »" : ""), v.affiches.includes(a.id), (x, entree) => {
      if (x && v.affiches.length >= 6) { entree.checked = false; toast("6 affiches au plus.", "erreur"); return; }
      v.affiches = x ? [...v.affiches, a.id] : v.affiches.filter((y) => y !== a.id);
      maj();
    }, { classe: "choix-affiche" }))) : h("p", { classe: "aide" }, "Aucune affiche au mur."));
  maj();
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "Les affiches"), zone_);
}

// ─── Les actualités de la direction ─────────────────────────────────────────
function editerActualite(a) {
  const v = a ? { titre: a.titre, texte: a.texte, image: idMedia(a.image), epingle: !!a.epingle } : { titre: "", texte: "", image: "", epingle: false };
  const p = pancarte({ titre: a ? "Modifier l'actualité" : "Publier une actualité", sous: "Tout l'équipage la lit sur l'accueil.", icone: "journal", taille: "large" });
  if (a) {
    proteger(p, "actualite:" + a.id, "l'actualité « " + sansEmoji(a.titre).slice(0, 60) + " »", async () => {
      await recharger(true);
      const frais = ((((E.accueil || {}).donnees || {}).actualites || {}).direction || []).find((x) => x.id === a.id);
      if (!frais) throw new Error("actualité retirée");
      editerActualite(frais);
    });
  }
  const titre = saisie({ value: v.titre, maxlength: 100, placeholder: "Grande chasse au trésor samedi soir" });
  titre.addEventListener("input", () => { v.titre = titre.value; });
  const texte = zoneTexte({ rows: 6, maxlength: 2000, placeholder: "Rendez-vous au port à 21 h…" }, v.texte);
  texte.addEventListener("input", () => { v.texte = texte.value; });
  ajouter(p.corps, [h("div", { classe: "pile" },
    champ("Titre", titre), champ("Texte", texte, { optionnel: true, aide: "Une ligne vide sépare deux paragraphes. **Entre deux paires d'étoiles** : en gras." }),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Image ", h("span", { classe: "optionnel" }, "(facultatif)")), choixImage(v, "image")),
    interrupteur("Épingler en tête des actualités", v.epingle, (x) => { v.epingle = x; }))]);
  const ok = bouton(a ? "Enregistrer" : "Publier", { classe: "principal", icone: a ? "valider" : "plume", reseau: true, onclick: async () => {
    if (!v.titre.trim()) { titre.closest(".champ").erreur("Le titre est obligatoire."); titre.focus(); return; }
    ok.disabled = true;
    const r = await ecrire("equipage/actualite", { id: a ? a.id : undefined, titre: v.titre, texte: v.texte, image: v.image, epingle: v.epingle, version: a ? a.version : 0 },
      a ? "Actualité enregistrée." : "Actualité publiée : l'équipage la voit.");
    ok.disabled = false;
    if (r.ok) p.fermer();
  } });
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), ok]);
  requestAnimationFrame(() => titre.focus());
}
async function retirerActualite(a) {
  if (!libre("actualite:" + a.id)) return;
  const ok = await confirmer({ titre: "Retirer cette actualité ?", texte: "« " + sansEmoji(a.titre) + " » disparaît de l'accueil pour de bon.", libelleOk: "Retirer", style: "danger" });
  if (ok) ecrire("equipage/actualite/retirer", { id: a.id }, "Actualité retirée.");
}

