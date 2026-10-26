// annonces.js — « Annonces & événements » du salon Info du clan : composer (événement avec date, minuteur, rappels,
// réponses, places et évènement Discord ; annonce ; annonce officielle des métiers ; listing complet), aperçu FIDÈLE
// de la carte Discord, brouillons (gardés hors ligne), à venir, passés.
// Contrat : evenements.py — GET clan/evenements · GET clan/apercu?id= · POST clan/brouillon et clan/supprimer_brouillon
// (file hors ligne, rejoués par sync) · POST clan/publier, clan/modifier, clan/annuler (connexion exigée) · POST media.
// Une date saisie est une heure de PARIS, quel que soit le fuseau de l'appareil (le minuteur Discord <t:…> en découle).

import { h, icone, date, heure, depuis, dans, dateLongue, nombre, sansEmoji, uuid, retarder, maintenant, srcSure, majuscule, remplacer, BASE, ajouter } from "./dom.js";
import { etat, emettre, ecouter, enLigne, aller, P } from "./noyau.js";
import { lire, poster, noterReseau } from "./api.js";
import { charger, vue as vueJeu, perime, element as elementCat } from "./donnees.js";
import { mettreEnFile, garderSaisie, lireSaisie, oublierSaisie, opsDe, abandonner } from "./hors_ligne.js";
import {
  bouton, pastille, tampon, vide, segment, liste, champ, saisie, zoneTexte, interrupteur, caseACocher, radios, confirmer, pancarte,
  toast, squelettes, paginer, bandeau, majBoutonsReseau, nomDe,
} from "./ui.js";
import { groupes, outilsGroupes, parPeriode } from "./rangement.js";

const TYPES = [
  ["evenement", "Événement", "calendrier", "Une date, un minuteur, des rappels, et qui est disponible."],
  ["annonce", "Annonce", "cloche", "Un message soigné pour tout l'équipage, avec ou sans image, et son « Vu »."],
  ["metiers", "Les métiers", "drapeau", "L'annonce officielle du métier de chacun, tirée des affiches."],
  ["listing", "Le listing", "parchemin", "La liste complète de l'équipage, rangée comme tu veux."],
];
const LIB_TYPE = Object.fromEntries(TYPES.map(([k, l]) => [k, l]));
// Le titre que la carte prend quand il manque (comme evenements.NOMS_TYPES).
const NOMS_TYPES = { evenement: "Événement", annonce: "Annonce", metiers: "Annonce des métiers", listing: "Listing du clan" };
const STATUTS = { brouillon: ["Brouillon", "encre"], envoi: ["Envoi en cours", "mer"], publie: ["Publié", "vert"], annule: ["Annulé", ""], retire: ["Retiré", "encre"], incertain: ["À vérifier", "ambre"] };
// Les champs de chaque type (evenements.CHAMPS_TYPE) : le serveur refuse un champ inconnu.
const CHAMPS = {
  evenement: ["titre", "texte", "quand", "duree_min", "lieu", "image", "couleur", "rappels", "mention", "destination", "reponses", "places", "discord_event", "reserve_clan"],
  annonce: ["titre", "texte", "image", "couleur", "mention", "destination"],
  metiers: ["titre", "texte", "image", "couleur", "mention", "destination", "groupement", "champs"],
  listing: ["titre", "texte", "image", "couleur", "mention", "destination", "groupement", "champs"],
};
// Les limites du serveur (evenements.py), quand il ne les envoie pas.
const LIMITES = { titre: 100, texte: { evenement: 2000, annonce: 3500, metiers: 1500, listing: 1500 }, lieu: 100, places: 500, rappels: 5, duree_min: 10080 };
const COULEURS = [["Laiton", "#a8823f"], ["Clan", "#14b8a6"], ["Cire", "#8e2a24"], ["Mer", "#1f4e5a"], ["Vert", "#3f6b3a"], ["Ambre", "#a8641c"], ["Encre", "#2b1d12"]];
const RAPPELS = [[10080, "1 semaine avant"], [1440, "1 jour avant"], [180, "3 h avant"], [60, "1 h avant"], [30, "30 min avant"], [15, "15 min avant"], [10, "10 min avant"], [0, "Au début"]];
const DUREES = [0, 30, 45, 60, 90, 120, 180, 240, 360, 1440];
const GROUPES = { metier: ["métier", "trade"], grade: ["grade", "rank"], race: ["race", "race"] };
const CHAMP_DU_GROUPE = { metier: "metiers", grade: "grade", race: "race" };
// Le serveur nomme les styles en français (succes, secondaire, primaire) ; la feuille de style, comme Discord.
const STYLE_BOUTON = { succes: "success", success: "success", secondaire: "secondary", secondary: "secondary", danger: "danger", primaire: "primary", primary: "primary", lien: "lien" };
// Les bandeaux du bot (visuels/), servis par ce même serveur sous /v/ : l'en-tête d'une annonce ou d'un listing sans image.
const BANDEAUX = { annonce: ["an_clan", "Annonce du clan"], listing: ["clan", "Liste du clan"] };
const RE_BANDEAU = /^\/v\/[A-Za-z0-9_-]{1,40}\.gif(\?v=[A-Za-z0-9_.-]{1,20})?$/;
const RE_HEX = /^#[0-9a-fA-F]{6}$/;
const NOM_CLAN = "Clan GoRP";

// ─── L'heure de Paris ───────────────────────────────────────────────────────
const FMT_PARIS = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
/** { a, m, j, H, M } : la date et l'heure à Paris d'un instant (secondes). */
export function partiesParis(t) {
  const p = {};
  for (const x of FMT_PARIS.formatToParts(new Date(t * 1000))) if (x.type !== "literal") p[x.type] = Number(x.value);
  return { a: p.year, m: p.month, j: p.day, H: p.hour % 24, M: p.minute };
}
/** L'instant (secondes) d'une date et d'une heure lues à Paris (changement d'heure compris). */
export function depuisParis(a, m, j, H, M) {
  const voulu = Date.UTC(a, m - 1, j, H, M) / 1000;
  let t = voulu;
  for (let i = 0; i < 3; i++) {
    const p = partiesParis(t);
    const vu = Date.UTC(p.a, p.m - 1, p.j, p.H, p.M) / 1000;
    if (vu === voulu) break;
    t += voulu - vu;
  }
  return t;
}
function demainParis(H, M) {
  const p = partiesParis(maintenant() + 86400);
  return depuisParis(p.a, p.m, p.j, H, M);
}
/** Le même jour de la semaine, à la même heure de Paris, la prochaine fois (dans une heure au moins). */
function prochaineFois(q) {
  const p = partiesParis(q);
  let t = q;
  for (let n = 1; t <= maintenant() + 3600 && n < 600; n++) {
    const d = new Date(Date.UTC(p.a, p.m - 1, p.j + 7 * n));
    t = depuisParis(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate(), p.H, p.M);
  }
  return t;
}
const deux = (n) => String(n).padStart(2, "0");

// ─── Les données du serveur, lues telles qu'il les envoie ───────────────────
const minutes = (x) => Math.max(0, Math.round(Number(Array.isArray(x) ? x[0] : x) || 0));
/** Une durée comme sur la carte Discord (evenements._duree_txt) : « 1 j », « 1 h 30 », « 10 min ». */
export function dureeTxt(min) {
  const n = minutes(min);
  const j = Math.floor(n / 1440), hh = Math.floor((n % 1440) / 60), mm = n % 60;
  const morceaux = [];
  if (j) morceaux.push(j + " j");
  if (hh) morceaux.push(hh + " h" + (mm && !j ? " " + deux(mm) : ""));
  if (mm && (j || !hh)) morceaux.push(mm + " min");
  return morceaux.join(" ") || "0 min";
}
export const libRappel = (m) => (minutes(m) === 0 ? "Au début" : dureeTxt(m) + " avant");
/** [[minutes, libellé]] : le serveur envoie des paires, une ancienne réponse des nombres. */
function rappelsSuggeres(E) {
  const l = E && Array.isArray(E.rappels_suggeres) && E.rappels_suggeres.length ? E.rappels_suggeres : RAPPELS;
  return l.map((x) => [minutes(x), Array.isArray(x) && x[1] ? String(x[1]) : libRappel(x)]);
}
/** [[nom, #rrggbb]] : la palette du serveur (paires « nom, couleur »), puis celle du site. */
function couleursDe(E) {
  const l = [];
  for (const x of [...((E && E.couleurs) || []), ...COULEURS]) {
    const [nom, hex] = Array.isArray(x) ? [String(x[0] || ""), String(x[1] || "")] : ["", String(x || "")];
    if (RE_HEX.test(hex) && !l.some((c) => c[1] === hex.toLowerCase())) l.push([sansEmoji(nom) || hex.toLowerCase(), hex.toLowerCase()]);
  }
  return l.slice(0, 10);
}
/** Les lieux du jeu proposés : des objets { type, cle, nom } (ou des noms). */
const lieuxDe = (E) => [...new Set(((E && E.lieux) || []).map((x) => sansEmoji(typeof x === "string" ? x : x && x.nom)).filter(Boolean))].slice(0, 8);
function limitesDe(E, type) {
  const l = (E && E.limites) || {};
  const nb = (x, d) => (Number(x) > 0 ? Number(x) : d);
  const texte = l.texte && typeof l.texte === "object" ? l.texte[type] : l.texte;
  return { titre: nb(l.titre, LIMITES.titre), texte: nb(texte, LIMITES.texte[type] || 2000), lieu: nb(l.lieu, LIMITES.lieu), places: nb(l.places, LIMITES.places),
    rappels: nb(l.rappels, LIMITES.rappels), duree_min: nb(l.duree_min, LIMITES.duree_min) };
}
const destinationsDe = (E) => ((E && E.destinations) || []).filter((d) => d && d.id);
const destDefaut = (E) => destinationsDe(E).find((d) => d.defaut) || destinationsDe(E)[0] || null;
/** Le post choisi ; vide = celui par défaut (le serveur fait de même). */
function destinationDe(E, v) {
  const id = String((v && v.destination) || "");
  return id ? destinationsDe(E).find((d) => String(d.id) === id) || null : destDefaut(E);
}
/** L'identifiant d'un post : le serveur envoie l'objet { id, nom } en tête d'élément, l'identifiant dans ses valeurs. */
const idPost = (d) => (d && typeof d === "object" ? String(d.id || "") : d === null || d === undefined ? "" : String(d));

/** Un élément du serveur, à plat : ses valeurs (ce que la page envoie) et ses repères. */
export function aplatir(el) {
  if (!el) return {};
  const v = el.valeurs || {};
  return Object.assign({}, v, { id: el.id, version: el.version, cle_client: el.cle_client, type: el.type, statut: el.statut,
    titre: el.titre ?? v.titre ?? "", quand: el.quand ?? v.quand ?? null, destination: idPost(v.destination ?? el.destination) });
}
/** Des valeurs remises dans la forme que le serveur accepte (une saisie gardée par une version plus ancienne du site). */
function nettoyer(v) {
  const o = Object.assign({}, v);
  o.destination = idPost(o.destination);
  if (o.rappels !== undefined) o.rappels = [...new Set((Array.isArray(o.rappels) ? o.rappels : []).map(minutes))].sort((a, b) => b - a);
  if (o.couleur !== undefined && !RE_HEX.test(String(o.couleur || ""))) delete o.couleur;
  if (o.couleur) o.couleur = String(o.couleur).toLowerCase();
  if (o.quand !== undefined) o.quand = Math.floor(Number(o.quand)) || null;
  if (o.champs !== undefined && !Array.isArray(o.champs)) delete o.champs;
  for (const k of ["places", "duree_min"]) if (o[k] !== undefined) o[k] = minutes(o[k]);
  if (o.type && o.type !== "evenement" && o.mention === "inscrits") o.mention = "aucune"; // « inscrits » n'existe que pour un événement
  return o;
}

// ─── La rubrique ────────────────────────────────────────────────────────────
const SOUS = [["composer", "Composer", "plume"], ["brouillons", "Brouillons", "parchemin"], ["a-venir", "À venir", "minuteur"], ["passes", "Passés", "coffre"]];
let composeur = null;    // l'état du formulaire (survit aux changements de sous-onglet)
let composeurOuvrir = null;
let dernierE = null;     // le dernier contenu de clan/evenements (pour ouvrir, dupliquer)

export function annonces(vue, ctx) {
  const sous = SOUS.some(([k]) => k === ctx.sous) ? ctx.sous : "composer";
  const onglets = h("div", { classe: "sous-onglets", role: "tablist", "aria-label": "Annonces et événements" });
  const zone = h("div", { classe: "pile" }, squelettes(3));
  ajouter(vue, [onglets, zone]);
  let construction = null, ctrl = null, fini = false, centre = false;
  const maj = async (forcer) => {
    const E = await charger("evenements", { forcer });
    if (fini || !zone.isConnected) return;
    if (E && !E.erreur) dernierE = E;
    const nb = E && !E.erreur ? { brouillons: (E.brouillons || []).length, "a-venir": (E.a_venir || []).length, passes: E.passes_total ?? (E.passes || []).length } : {};
    remplacer(onglets, ...SOUS.map(([k, l, ic]) => h("a", { classe: "etiquette", role: "tab", href: "#equipage/annonces/" + k, "aria-selected": String(k === sous) },
      icone(ic), l, nb[k] ? h("span", { classe: "compteur calme" }, String(nb[k])) : null)));
    if (!centre) { centre = true; requestAnimationFrame(() => centrerOnglet(onglets)); }
    if (!E || E.erreur) { remplacer(zone, vide("Annonces indisponibles", (E && E.erreur) || "Réessaie dans un instant.", "hors_ligne")); return; }
    if (sous === "composer") {
      if (!construction) construction = composer(zone, E).then((c) => { ctrl = c; if (fini && c) c.quitter(); return c; });
      else if (ctrl) ctrl.majDonnees(E);
    } else remplacer(zone, ...[{ brouillons: listeBrouillons, "a-venir": listeAVenir, passes: listePasses }[sous](E, () => maj(true))].flat());
  };
  maj();
  return { maj: () => maj(false), majJeu: () => maj(false), majFile: () => maj(false), quitter: () => { fini = true; if (ctrl) ctrl.quitter(); } };
}

/** Au téléphone, la rangée des sous-onglets défile : l'onglet ouvert (« Passés » après une publication) bien en vue. */
function centrerOnglet(rangee) {
  const actif = rangee.querySelector('[aria-selected="true"]');
  if (!actif || rangee.scrollWidth <= rangee.clientWidth) return;
  const ra = actif.getBoundingClientRect(), rr = rangee.getBoundingClientRect();
  const g = ra.left - rr.left + rangee.scrollLeft, d = g + ra.width;
  if (g < rangee.scrollLeft + 30 || d > rangee.scrollLeft + rangee.clientWidth - 30) rangee.scrollTo({ left: Math.max(0, g - (rangee.clientWidth - ra.width) / 2), behavior: "auto" });
}

// ─── Le composeur ───────────────────────────────────────────────────────────
/** Les valeurs d'un élément neuf : celles du serveur (`defauts[type]`), un début demain à 21 h (Paris), le post par défaut. */
function valeursNeuves(E, type) {
  const base = {
    type, titre: "", texte: "", quand: type === "evenement" ? demainParis(21, 0) : null, duree_min: 60, lieu: "", image: "", couleur: COULEURS[0][1],
    rappels: [60], mention: type === "evenement" ? "inscrits" : "aucune", destination: "", reponses: type === "evenement", places: 0, discord_event: false,
    reserve_clan: true, groupement: type === "listing" ? "grade" : "metier", champs: type === "listing" ? ["metiers", "race"] : ["grade"],
  };
  // Seuls les champs connus du composeur sont repris ; une valeur vide du serveur (pas de date, post par défaut) laisse la nôtre.
  const d = ((E && E.defauts) || {})[type];
  const connus = Object.entries(d && typeof d === "object" && !Array.isArray(d) ? d : {}).filter(([k, x]) => k in base && k !== "type" && x !== null && x !== undefined && x !== "");
  return nettoyer(Object.assign(base, Object.fromEntries(connus), { type }));
}
const neuf = (E, type) => ({ v: valeursNeuves(E, type), id: null, version: null, cle_client: null, publie: false, sale: false });

async function composer(zone, E0) {
  let E = E0;
  const garde = await lireSaisie("composeur");
  if (!zone.isConnected) return null;
  if (!composeur && garde && garde.valeur && garde.valeur.v) composeur = Object.assign({}, garde.valeur, { restaure: true, v: nettoyer(garde.valeur.v) });
  if (!composeur) composeur = neuf(E, "evenement");
  const formulaire = h("div", { classe: "composeur-form pile" });
  const apercuZone = h("div", { classe: "apercu-discord-zone" });
  const statut = h("p", { classe: "composeur-statut", "aria-live": "polite" });
  const actions = h("div", { classe: "rangee composeur-actions" });
  const bascule = segment("form", [["form", "Rédiger"], ["apercu", "Aperçu Discord"]], (x) => { zone.classList.toggle("voir-apercu", x === "apercu"); }, "Vue");
  bascule.classList.add("seulement-telephone");
  zone.classList.remove("voir-apercu");
  remplacer(zone, bascule, h("div", { classe: "atelier composeur" }, h("div", { classe: "pile" }, formulaire, statut, actions), h("div", { classe: "collant" }, apercuZone)));
  const garderLocal = retarder(() => garderSaisie("composeur", composeur), 400);
  const apercuServeur = retarder(() => majApercu(true), 900);
  let apercuDistant = null, jeton = 0;

  const changer = (k, x, sansRendu) => {
    composeur.v[k] = x;
    composeur.sale = true;
    garderLocal();
    majApercu(false);
    majStatut();
    if (!sansRendu) construire();
  };
  function choisirType(t) {
    if (composeur.publie || composeur.v.type === t) return;
    // Ce qui est commun suit (titre, texte, image, post) ; une couleur ou un titre laissés par défaut prennent ceux du nouveau type.
    const ancien = composeur.v, avant = valeursNeuves(E, ancien.type), apres = valeursNeuves(E, t);
    composeur.v = Object.assign(apres, {
      titre: ancien.titre && ancien.titre !== avant.titre ? ancien.titre : apres.titre, texte: ancien.texte || "", image: ancien.image || "",
      destination: ancien.destination || "", couleur: ancien.couleur && ancien.couleur !== avant.couleur ? ancien.couleur : apres.couleur,
    });
    composeur.sale = true;
    garderLocal();
    construire();
    majApercu(false);
    majStatut();
  }
  const etiquetteType = (t) => h("button", { classe: "choix-type" + (composeur.v.type === t[0] ? " actif" : ""), type: "button", "aria-pressed": String(composeur.v.type === t[0]),
    disabled: composeur.publie || null, onclick: () => choisirType(t[0]) }, icone(t[2]), h("b", {}, t[1]), h("span", {}, t[3]));

  function construire() {
    const v = composeur.v, t = v.type;
    const lim = limitesDe(E, t);
    const blocs = [];
    if (composeur.restaure && (composeur.id || v.titre || v.texte)) blocs.push(bandeau("Ta dernière saisie a été retrouvée sur cet appareil : tu reprends où tu en étais.", "vert",
      bouton("Repartir de zéro", { classe: "p discret", onclick: () => nouveau() })));
    if (composeur.publie) blocs.push(bandeau(h("span", {}, h("b", {}, "Déjà publié. "), "Tes changements partent sur Discord avec « Enregistrer sur Discord » (connexion exigée)."), ""));
    blocs.push(h("div", { classe: "choix-types", role: "group", "aria-label": "Type de publication" }, TYPES.map(etiquetteType)));
    blocs.push(blocModeles());
    const titre = saisie({ value: v.titre || "", maxlength: lim.titre, placeholder: t === "evenement" ? "Sortie en mer : le boss des abysses" : "Le titre, en quelques mots" });
    titre.addEventListener("input", () => changer("titre", titre.value, true));
    blocs.push(champ("Titre", titre, { aide: compteurCaracteres(titre, lim.titre) }));
    const texte = zoneTexte({ rows: 7, maxlength: lim.texte, placeholder: t === "metiers" || t === "listing" ? "Un mot d'introduction (facultatif)" : "Le message. **gras**, *italique*, __souligné__, ~~barré~~, > citation, - liste" }, v.texte || "");
    texte.id = "composeur-texte";
    texte.addEventListener("input", () => changer("texte", texte.value, true));
    blocs.push(h("div", { classe: "champ" }, h("label", { classe: "champ-lib", for: texte.id }, t === "metiers" || t === "listing" ? "Introduction" : "Texte"),
      barreMarkdown(texte, () => changer("texte", texte.value, true)), texte, h("span", { classe: "champ-aide" }, compteurCaracteres(texte, lim.texte), " · Markdown de Discord.")));
    if (t === "evenement") blocs.push(blocEvenement(v, changer, E));
    if (t === "metiers" || t === "listing") blocs.push(blocGroupement(v, changer));
    blocs.push(blocApparence(v, changer, E));
    blocs.push(blocEnvoi(v, changer, E));
    remplacer(formulaire, ...blocs);
    majActions();
    majBoutonsReseau(formulaire);
  }

  function blocModeles() {
    const modeles = ((E && E.modeles) || []).filter((m) => m && LIB_TYPE[m.type] && m.valeurs && typeof m.valeurs === "object");
    if (!modeles.length || composeur.id || composeur.publie) return null;
    const choix = liste({ valeur: "", label: "Partir d'un modèle", titre: "Choisir un modèle…", plein: true,
      options: modeles.map((m, i) => ({ v: String(i), l: sansEmoji(m.nom) || LIB_TYPE[m.type], sous: LIB_TYPE[m.type] + (m.description ? " · " + m.description : "") })),
      changer: (x) => { choix.poser(""); const m = modeles[Number(x)]; if (m) appliquerModele(m); } });
    return choix;
  }
  async function appliquerModele(m) {
    const v = composeur.v, d = valeursNeuves(E, v.type);
    if (((v.titre && v.titre !== d.titre) || v.texte) && !(await confirmer({ titre: "Partir du modèle « " + sansEmoji(m.nom) + " » ?", icone: "parchemin",
      texte: "Le titre, le texte et les réglages actuels sont remplacés par ceux du modèle. L'image, le post et la date restent.", libelleOk: "Utiliser ce modèle" }))) return;
    const apres = valeursNeuves(E, m.type);
    const repris = Object.fromEntries(Object.entries(m.valeurs).filter(([k, x]) => k in apres && k !== "type" && x !== null && x !== undefined && !(x === "" && k === "titre")));
    composeur.v = nettoyer(Object.assign(apres, repris, { type: m.type, image: v.image || "", destination: v.destination || "",
      quand: m.type === "evenement" ? (v.type === "evenement" && v.quand ? v.quand : apres.quand) : null }));
    composeur.sale = true;
    garderLocal();
    construire();
    majApercu(false);
    majStatut();
    toast("Modèle « " + sansEmoji(m.nom) + " » : complète, puis enregistre.", "succes");
  }

  function opsComposeur() {
    const cles = [...new Set([composeur.id ? String(composeur.id) : "", composeur.cle_client || ""].filter(Boolean))];
    return cles.flatMap((c) => opsDe("brouillon", c));
  }
  function majStatut() {
    const ops = opsComposeur();
    const conf = ops.find((o) => o.etat === "conflit"), refus = ops.find((o) => o.etat === "refus" || o.etat === "erreur"), att = ops.find((o) => o.etat === "attente");
    statut.textContent = conf ? "Conflit : ce brouillon a changé ailleurs. Ouvre la file d'envoi pour choisir la bonne version."
      : refus ? "Le serveur a refusé ce brouillon : " + (refus.erreur || "réessaie.") + " Corrige, puis enregistre à nouveau."
        : att ? (enLigne() ? "Envoi du brouillon…" : "Brouillon gardé sur cet appareil : il partira au retour de la connexion.")
          : composeur.sale ? (composeur.publie ? "Modifications pas encore envoyées sur Discord." : "Modifications pas encore enregistrées (gardées sur cet appareil).")
            : composeur.publie ? "Publié" + (composeur.maj ? ", dernière modification " + depuis(composeur.maj) : "") + "."
              : composeur.id ? "Brouillon enregistré" + (composeur.maj ? " " + depuis(composeur.maj) : "") + "." : "Nouveau brouillon.";
    statut.classList.toggle("alerte", !!(conf || refus));
  }
  function majActions() {
    const pub = composeur.publie;
    remplacer(actions,
      bouton("Nouveau", { classe: "discret", icone: "ajouter", onclick: () => nouveau() }),
      pub ? null : bouton("Enregistrer le brouillon", { icone: "parchemin", onclick: () => enregistrer() }),
      pub ? bouton("Enregistrer sur Discord", { classe: "principal", icone: "valider", reseau: true, onclick: () => modifierPublie() })
        : bouton("Publier…", { classe: "principal", icone: "cloche", reseau: true, onclick: () => publier() }));
    majBoutonsReseau(actions);
  }

  function corpsDe(v) {
    const corps = {};
    for (const k of CHAMPS[v.type]) if (v[k] !== undefined) corps[k] = v[k];
    if ("destination" in corps) corps.destination = idPost(corps.destination);
    if (v.type === "evenement" && !corps.reponses) corps.places = 0;
    return corps;
  }
  async function enregistrer(silencieux) {
    if (composeur.publie) return modifierPublie();
    const v = composeur.v;
    const corps = Object.assign({ type: v.type }, corpsDe(v));
    if (composeur.id) { corps.id = composeur.id; corps.version = composeur.version; }
    else { composeur.cle_client = composeur.cle_client || uuid(); corps.cle_client = composeur.cle_client; }
    const cle = composeur.id ? String(composeur.id) : composeur.cle_client;
    // Une saisie que le serveur a refusée est remplacée par celle-ci (corrigée) : elle ne bloque plus la publication.
    for (const o of opsComposeur()) if (o.etat === "refus" || o.etat === "erreur") await abandonner(o);
    const objet = { id: composeur.id || undefined, cle_client: composeur.cle_client || undefined, _cle: cle, type: v.type, statut: "brouillon", titre: v.titre,
      quand: v.type === "evenement" ? v.quand : null, valeurs: Object.assign({}, v), version: composeur.version || 0, maj: Math.floor(maintenant()) };
    await mettreEnFile("clan/brouillon", corps, { genre: "brouillon", cle, resume: "Brouillon « " + (v.titre || LIB_TYPE[v.type]) + " »", objet });
    composeur.sale = false;
    composeur.restaure = false;
    garderLocal();
    majStatut();
    if (!silencieux) toast(enLigne() ? "Brouillon enregistré." : "Brouillon gardé sur l'appareil : il partira au retour de la connexion.", "succes");
    emettre("jeu", { nom: "evenements" });
  }
  // Le serveur a enregistré : l'identifiant et la version du brouillon reviennent.
  const stopSucces = ecouter("file:succes", ({ op, objet }) => {
    if (op.genre !== "brouillon" || !objet || objet.id === undefined || objet.id === null) return;
    const meme = (composeur.cle_client && (op.cle === composeur.cle_client || objet.cle_client === composeur.cle_client)) || (composeur.id && String(objet.id) === String(composeur.id));
    if (!meme) return;
    composeur.id = objet.id; composeur.version = objet.version; composeur.maj = objet.maj || Math.floor(maintenant());
    // Rien de saisi depuis : le composeur montre la version enregistrée (un conflit réglé champ par champ, un texte
    // nettoyé par le serveur). Il ne se redessine que si elle diffère de ce qui est à l'écran.
    if (!composeur.sale && objet.valeurs && objet.type) {
      const serveur = etatDepuis(objet, E).v;
      if (serveur.type !== composeur.v.type || CHAMPS[serveur.type].some((k) => JSON.stringify(serveur[k] ?? null) !== JSON.stringify(composeur.v[k] ?? null))) {
        composeur.v = serveur;
        construire();
      }
    }
    garderLocal(); majStatut(); apercuServeur();
  });
  const stopFile = ecouter("file", majStatut);
  const stopReseau = ecouter("reseau", () => { if (apercuZone.isConnected) { majActions(); majApercu(true); } });

  /** Attendre que la file ait envoyé ce brouillon : true, ou la raison (l'opération refusée, en conflit, la connexion). */
  async function attendreEnregistrement() {
    for (let i = 0; i < 40; i++) {
      const ops = opsComposeur();
      const bloque = ops.find((o) => o.etat !== "attente");
      if (bloque) return bloque;
      if (composeur.id && !ops.length) return true;
      if (!enLigne()) return "hors_ligne";
      await new Promise((ok) => setTimeout(ok, 250));
    }
    return "delai";
  }
  /** Relire la version enregistrée (après un envoi raté, le serveur l'a changée). */
  async function rafraichirVersion() {
    if (!composeur.id) return null;
    const nE = await charger("evenements", { forcer: true });
    const el = trouver(nE, composeur.id);
    if (el && !composeur.sale) { composeur.version = el.version; composeur.maj = el.maj; garderLocal(); majStatut(); }
    return el;
  }
  function mentionTexte(v) {
    const role = E.droits && E.droits.role_clan_nom ? " (" + sansEmoji(E.droits.role_clan_nom) + ")" : "";
    if (v.mention === "clan") return "Le clan" + role + " est mentionné" + (v.type === "evenement" && v.reponses ? " ; les rappels mentionnent les disponibles." : ".");
    if (v.mention === "inscrits") return "Personne n'est mentionné à la publication ; les rappels mentionnent les disponibles.";
    return "Personne n'est mentionné.";
  }

  async function publier() {
    const v = composeur.v;
    if (!String(v.titre || "").trim()) { toast("Donne un titre avant de publier.", "erreur"); return; }
    if (v.type === "evenement" && !(v.quand > maintenant() + 60)) { toast("Choisis un début dans le futur (une minute au moins).", "erreur"); return; }
    if (!destinationsDe(E).length) { toast("Le forum du clan n'est pas installé : il n'y a aucun post où publier.", "erreur"); return; }
    if (composeur.sale || !composeur.id) await enregistrer(true);
    const att = await attendreEnregistrement();
    if (att !== true) {
      toast(att && att.etat === "conflit" ? "Ce brouillon a changé ailleurs : règle le conflit dans la file d'envoi, puis publie."
        : att && att.erreur ? "Le serveur a refusé le brouillon : " + att.erreur
          : "Le brouillon n'a pas encore pu être enregistré sur le serveur : réessaie quand la connexion revient.", "erreur");
      return;
    }
    const ap = await lire("clan/apercu", { id: composeur.id });
    if (!ap.ok || !ap.donnees) { toast(ap.erreur || "L'aperçu ne répond pas : réessaie dans un instant.", "erreur"); return; }
    const d = ap.donnees;
    apercuDistant = d;
    rendreApercu();
    const erreurs = d.erreurs || [], avert = d.avertissements || [];
    if (erreurs.length) { toast("À corriger avant de publier : " + erreurs.join(" · "), "erreur"); return; }
    // L'aperçu montre exactement ce qui part : on publie cette version-là (un changement d'ici là : conflit, rien ne part).
    if (d.version !== undefined && d.version !== null) composeur.version = d.version;
    const dest = d.destination || destinationDe(E, v);
    const lignes = ["Dans « " + (dest ? sansEmoji(dest.nom) : "Infos") + " »."];
    if (v.type === "evenement") lignes.push("Début : " + dateLongue(v.quand) + " (heure de Paris), " + dans(v.quand) + ".");
    lignes.push(mentionTexte(v));
    if (v.type === "evenement") lignes.push("Le minuteur et les rappels démarrent tout de suite." + (v.discord_event && E.droits && E.droits.discord_event ? " L'évènement Discord est créé aussi." : ""));
    const ok = await confirmer({
      titre: "Publier « " + (v.titre || LIB_TYPE[v.type]) + " » ?", icone: "cloche", libelleOk: "Publier", taille: "etroite",
      contenu: [...lignes.map((l) => h("p", {}, l)), avert.length ? bandeau(avert.join(" · "), "") : null].filter(Boolean),
    });
    if (!ok) return;
    await envoyerPublication(false);
  }
  async function envoyerPublication(forcer) {
    const r = await versDiscord("clan/publier", { id: composeur.id, version: composeur.version ?? undefined, forcer: forcer || undefined });
    const d = r.donnees || {};
    if (r.ok && d.ok !== false && !d.incertain) {
      const type = composeur.v.type, el = d.element || {};
      nouveau(true);
      perime("evenements");
      emettre("recharger");
      toast("Publié sur Discord" + (el.destination && el.destination.nom ? " dans « " + sansEmoji(el.destination.nom) + " »" : "") + ".", "succes");
      if ((d.avertissements || []).length) remarques("Publié, avec une remarque", d.avertissements);
      aller("equipage", "annonces", type === "evenement" ? "a-venir" : "passes");
      return;
    }
    if (d.incertain) {
      const p = pancarte({ titre: "Publication incertaine", icone: "attention", taille: "etroite" });
      ajouter(p.corps, [h("p", {}, d.erreur || "Discord n'a pas confirmé la publication : le message est peut-être parti."),
        h("p", {}, "Regarde d'abord dans le post. S'il n'y est pas, force la publication ; s'il y est, rien à faire.")]);
      ajouter(p.pied, [bouton("Vérifier plus tard", { classe: "discret", icone: "oeil", onclick: async () => { p.fermer(); nouveau(true); perime("evenements"); aller("equipage", "annonces", "a-venir"); } }),
        bouton("Forcer la publication", { classe: "principal", reseau: true, onclick: async () => { p.fermer(); await rafraichirVersion(); await envoyerPublication(true); } })]);
      return;
    }
    if (r.status === 409 && d.actuelle) {
      if (d.actuelle.statut && d.actuelle.statut !== "brouillon") {
        toast((d.erreur || "Ce n'est plus un brouillon.") + " Il est dans la liste.", "erreur");
        nouveau(true);
        perime("evenements");
        aller("equipage", "annonces", d.actuelle.statut === "publie" && d.actuelle.type !== "evenement" ? "passes" : "a-venir");
      } else {
        toast("Ce brouillon a changé ailleurs : la version enregistrée est rechargée. Vérifie-la, puis publie.", "erreur");
        chargerElement(d.actuelle);
      }
      return;
    }
    toast(messageErreur(r, "Publication impossible."), "erreur");
    await rafraichirVersion();
    majApercu(true);
  }

  async function modifierPublie() {
    const v = composeur.v;
    const corps = Object.assign({ id: composeur.id, version: composeur.version }, corpsDe(v));
    if (v.type === "evenement" && composeur.quandPublie && v.quand !== composeur.quandPublie) {
      if (!(v.quand > maintenant() + 60)) { toast("Le nouveau début doit être dans le futur (une minute au moins).", "erreur"); return; }
      const ok = await confirmer({ titre: "Changer l'horaire ?", icone: "calendrier", libelleOk: "Enregistrer sur Discord", taille: "etroite",
        texte: "Nouveau début : " + dateLongue(v.quand) + " (heure de Paris). Les rappels repartent de zéro et les disponibles reçoivent un message « Nouvel horaire »." });
      if (!ok) return;
    }
    const r = await versDiscord("clan/modifier", corps);
    const d = r.donnees || {};
    if (r.ok && d.ok !== false) {
      if (d.element) chargerElement(d.element);
      perime("evenements");
      emettre("recharger");
      toast("Modifications enregistrées sur Discord.", "succes");
      if ((d.avertissements || []).length) remarques("Modifié, avec une remarque", d.avertissements);
      return;
    }
    if (r.status === 409 && d.actuelle) {
      const el = d.actuelle;
      if (d.conflit && enLigneSurDiscord(el)) {
        toast("Cette publication a changé ailleurs : la version enregistrée est rechargée.", "erreur");
        chargerElement(el);
      } else {
        toast(d.erreur || "Cette publication ne se modifie plus.", "erreur");
        nouveau(true);
        perime("evenements");
        aller("equipage", "annonces", el.type === "evenement" && el.statut === "publie" && el.phase !== "termine" ? "a-venir" : "passes");
      }
      return;
    }
    toast(messageErreur(r, "Modification impossible."), "erreur");
  }

  async function nouveau(silencieux) {
    if (!silencieux && composeur && composeur.sale && (composeur.v.titre || composeur.v.texte)
      && !(await confirmer({ titre: "Repartir de zéro ?", texte: "Les modifications pas encore enregistrées sont perdues.", libelleOk: "Repartir de zéro", style: "danger" }))) return;
    composeur = neuf(E, composeur ? composeur.v.type : "evenement");
    oublierSaisie("composeur");
    apercuDistant = null;
    construire();
    majApercu(false);
    majStatut();
    if (!silencieux) toast("Nouveau brouillon.", "succes");
  }
  /** Un élément du serveur dans le composeur (brouillon, publication, ou la réponse du serveur après un envoi). */
  function chargerElement(el) {
    composeur = etatDepuis(el, E);
    garderLocal();
    apercuDistant = null;
    construire();
    majApercu(true);
    majStatut();
  }
  composeurOuvrir = (el) => chargerElement(el);

  async function majApercu(serveur) {
    if (!composeur || !apercuZone.isConnected) return;
    if (serveur && composeur.id && enLigne() && !composeur.sale) {
      const n = ++jeton, id = composeur.id;
      const r = await lire("clan/apercu", { id });
      if (n !== jeton || !composeur || String(composeur.id) !== String(id)) return;
      if (r.ok && r.donnees && Array.isArray(r.donnees.cartes)) apercuDistant = r.donnees;
    }
    rendreApercu();
  }
  function rendreApercu() {
    if (!composeur || !apercuZone.isConnected) return;
    const v = composeur.v;
    const distant = apercuDistant && !composeur.sale && String(apercuDistant.id) === String(composeur.id) ? apercuDistant : null;
    remplacer(apercuZone, apercuDiscord(distant || apercuLocal(v, E, composeur), { local: !distant, destination: destinationDe(E, v) }));
    // Les icônes officielles des métiers (listing, annonce des métiers) viennent du catalogue des affiches.
    if (distant && (v.type === "metiers" || v.type === "listing") && !vueJeu("catalogue")) charger("catalogue").then(() => rendreApercu());
  }

  construire();
  majApercu(true);
  majStatut();
  return {
    majDonnees(nE) { E = nE; },
    // Quitter le composeur : ses écoutes et ses minuteries s'arrêtent (la saisie est gardée tout de suite) ; un brouillon
    // supprimé depuis la liste ne doit plus être relu par un aperçu différé.
    quitter() {
      stopSucces(); stopFile(); stopReseau();
      apercuServeur.annuler();
      garderLocal.annuler();
      if (composeur) garderSaisie("composeur", composeur);
      composeurOuvrir = null;
    },
  };
}
/** L'état du composeur pour un élément du serveur (brouillon ou publié). */
function etatDepuis(el, E) {
  const f = nettoyer(aplatir(el));
  for (const k of ["id", "version", "cle_client", "statut"]) delete f[k];
  const v = Object.assign(valeursNeuves(E, el.type || "evenement"), f, { type: el.type || "evenement" });
  const publie = !!el.statut && el.statut !== "brouillon";
  return { v, id: el.id || null, version: el.version ?? null, cle_client: el.cle_client || null, publie, sale: false, maj: el.maj,
    quandPublie: publie ? el.quand || null : null, publieLe: el.publie || null, vus: (el.reponses && el.reponses.vus) || 0 };
}
/** Une écriture qui passe par Discord (publier, modifier, annuler). Un 502 qui porte son message vient du serveur : il a
 *  bien répondu, c'est Discord qui a refusé ou n'a pas confirmé — la page ne se croit pas hors ligne pour autant (elle
 *  griserait « Forcer la publication »). */
async function versDiscord(nom, corps) {
  const r = await poster(nom, corps);
  if (r.status === 502 && r.donnees && typeof r.donnees.erreur === "string") noterReseau(true);
  return r;
}
const trouver = (E, id) => (E && !E.erreur ? [...(E.brouillons || []), ...(E.a_venir || []), ...(E.passes || [])].find((x) => String(x.id) === String(id)) : null);
const enLigneSurDiscord = (el) => el.statut === "publie" && !(el.type === "evenement" && el.phase === "termine");
function messageErreur(r, defaut) {
  const d = r.donnees || {};
  return (Array.isArray(d.erreurs) && d.erreurs.length ? d.erreurs.join(" · ") : d.erreur || r.erreur || defaut);
}
/** Ce que le serveur signale après un envoi réussi (l'évènement Discord pas créé, une mention qui ne notifie personne…). */
function remarques(titre, liste_) {
  const p = pancarte({ titre, icone: "info", taille: "etroite" });
  ajouter(p.corps, liste_.map((x) => h("p", {}, x)));
  ajouter(p.pied, [bouton("Compris", { classe: "principal", onclick: () => p.fermer() })]);
}
/** Ouvre un élément (brouillon ou publié) dans le composeur. */
function ouvrirDansComposeur(el) {
  composeur = etatDepuis(el, dernierE);
  garderSaisie("composeur", composeur);
  if (composeurOuvrir && etat.route.sous === "composer") composeurOuvrir(el);
  else aller("equipage", "annonces", "composer");
}
/** Les noms des sortes de publication (accueil, recherche). */
export const NOMS_PUBLICATIONS = NOMS_TYPES;
/** Ouvrir une publication depuis l'accueil ou la recherche : un brouillon ou une publication en ligne dans le
 *  composeur ; une publication passée, annulée ou incertaine dans sa liste. */
export function ouvrirPublication(el, ou) {
  if (!el) return;
  if (!el.statut || el.statut === "brouillon" || enLigneSurDiscord(el)) ouvrirDansComposeur(el);
  else aller("equipage", "annonces", ou === "a-venir" ? "a-venir" : "passes");
}
/** Commencer une publication d'un type (raccourcis de l'accueil) : le composeur, sur un brouillon neuf de ce type —
 *  sauf une saisie déjà en cours, rouverte telle quelle (« Nouveau » repart de zéro). */
export async function commencer(type) {
  if (!composeur) {
    const garde = await lireSaisie("composeur");
    if (garde && garde.valeur && garde.valeur.v) composeur = Object.assign({}, garde.valeur, { restaure: true, v: nettoyer(garde.valeur.v) });
  }
  const enCours = composeur && (composeur.id || composeur.publie || (composeur.v && (composeur.v.titre || composeur.v.texte)));
  if (enCours) toast("Ta publication en cours est rouverte : « Nouveau » pour en commencer une autre.");
  else composeur = neuf(dernierE, LIB_TYPE[type] ? type : "evenement");
  aller("equipage", "annonces", "composer");
}

// ─── Les blocs du formulaire ────────────────────────────────────────────────
function compteurCaracteres(entree, max) {
  const c = h("span", { classe: "num" });
  const maj = () => { c.textContent = nombre(entree.value.length) + " / " + nombre(max); c.classList.toggle("alerte", entree.value.length > max * 0.95); };
  entree.addEventListener("input", maj);
  maj();
  return c;
}
function barreMarkdown(zone, apres) {
  const entourer = (avant, apres_ = avant) => () => {
    const d = zone.selectionStart, f = zone.selectionEnd, s = zone.value;
    zone.value = s.slice(0, d) + avant + s.slice(d, f) + apres_ + s.slice(f);
    zone.focus();
    zone.setSelectionRange(d + avant.length, f + avant.length);
    apres();
  };
  const ligne = (prefixe) => () => {
    const d = zone.selectionStart, s = zone.value;
    const debut = s.lastIndexOf("\n", d - 1) + 1;
    zone.value = s.slice(0, debut) + prefixe + s.slice(debut);
    zone.focus();
    zone.setSelectionRange(d + prefixe.length, d + prefixe.length);
    apres();
  };
  const b = (lib, aria, fn) => h("button", { classe: "md-bouton", type: "button", title: aria, "aria-label": aria, onclick: fn }, lib);
  return h("div", { classe: "barre-md", role: "toolbar", "aria-label": "Mise en forme" },
    b("G", "Gras", entourer("**")), b("I", "Italique", entourer("*")), b("S", "Souligné", entourer("__")), b("B", "Barré", entourer("~~")),
    b("T", "Titre", ligne("### ")), b("–", "Liste", ligne("- ")), b("«", "Citation", ligne("> ")), b("lien", "Lien", entourer("[", "](https://)")));
}
function blocEvenement(v, changer, E) {
  const lim = limitesDe(E, "evenement");
  const p = v.quand ? partiesParis(v.quand) : null, auj = partiesParis(maintenant());
  const jour = h("input", { type: "date", classe: "saisie", value: p ? `${p.a}-${deux(p.m)}-${deux(p.j)}` : "", min: `${auj.a}-${deux(auj.m)}-${deux(auj.j)}` });
  const hh = h("input", { type: "time", classe: "saisie", value: p ? `${deux(p.H)}:${deux(p.M)}` : "", step: 300 });
  const minuteur = h("p", { classe: "minuteur-vivant", "aria-live": "polite" });
  const majMinuteur = () => {
    const t = composeur.v.quand;
    remplacer(minuteur, icone("minuteur"), t ? h("span", {}, dateLongue(t), " (heure de Paris) · ", h("b", {}, t > maintenant() + 60 ? dans(t) : "date passée"))
      : h("span", {}, "Choisis le jour et l'heure (heure de Paris)."));
    minuteur.classList.toggle("alerte", !t || t <= maintenant() + 60);
  };
  const majQuand = () => {
    const [a, m, j] = jour.value.split("-").map(Number);
    if (!a || !m || !j) { changer("quand", null, true); majMinuteur(); return; }
    if (!hh.value) hh.value = "21:00";
    const [H, M] = hh.value.split(":").map(Number);
    changer("quand", depuisParis(a, m, j, H || 0, M || 0), true);
    majMinuteur();
  };
  jour.addEventListener("change", majQuand);
  hh.addEventListener("change", majQuand);
  majMinuteur();
  const tic = setInterval(() => { if (!minuteur.isConnected) clearInterval(tic); else majMinuteur(); }, 30000);
  const courante = minutes(v.duree_min);
  const durees = [...new Set([...DUREES.filter((m) => m <= lim.duree_min), courante])].sort((a, b) => a - b);
  const duree = liste({ valeur: courante, label: "Durée", plein: true, options: durees.map((m) => ({ v: m, l: m ? dureeTxt(m) : "Non précisée" })),
    changer: (x) => changer("duree_min", Number(x), true) });
  const lieu = saisie({ value: v.lieu || "", maxlength: lim.lieu, placeholder: "Port de l'île centrale" });
  lieu.addEventListener("input", () => changer("lieu", lieu.value, true));
  const suggestions = lieuxDe(E);
  const rappelsZone = h("div", { classe: "puces", role: "group", "aria-label": "Rappels" });
  const suggeres = rappelsSuggeres(E);
  const majRappels = () => {
    const actifs = new Set((composeur.v.rappels || []).map(minutes));
    const tous = new Map(suggeres);
    for (const m of actifs) if (!tous.has(m)) tous.set(m, libRappel(m));
    remplacer(rappelsZone, ...[...tous].sort((a, b) => b[0] - a[0]).map(([m, l]) => h("button", {
      classe: "puce", type: "button", "aria-pressed": String(actifs.has(m)),
      onclick: () => {
        const n = new Set((composeur.v.rappels || []).map(minutes));
        if (n.has(m)) n.delete(m);
        else if (n.size >= lim.rappels) { toast(lim.rappels + " rappels au plus.", "erreur"); return; }
        else n.add(m);
        changer("rappels", [...n].sort((a, b) => b - a), true);
        majRappels();
      },
    }, h("span", { classe: "puce-lib" }, l))));
  };
  majRappels();
  const places = h("input", { type: "number", min: 0, max: lim.places, step: 1, value: minutes(v.places), classe: "saisie", disabled: !v.reponses || null });
  places.addEventListener("input", () => changer("places", Math.max(0, Math.min(lim.places, Math.floor(Number(places.value) || 0))), true));
  const droits = E.droits || {};
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "L'événement"),
    h("div", { classe: "champs" }, champ("Le jour", jour), champ("L'heure (Paris)", hh), duree),
    minuteur,
    champ("Lieu", lieu, { optionnel: true }),
    suggestions.length ? h("div", { classe: "puces", role: "group", "aria-label": "Lieux du jeu" }, suggestions.map((s) => h("button", { classe: "puce", type: "button",
      onclick: () => { lieu.value = s; changer("lieu", s, true); } }, h("span", { classe: "puce-lib" }, s)))) : null,
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Rappels sur Discord (" + lim.rappels + " au plus)"), rappelsZone),
    interrupteur("Boutons de réponse « Disponible · Peut-être · Pas disponible »", v.reponses, (x) => { changer("reponses", x, true); places.disabled = !x; if (!x) { places.value = 0; changer("places", 0, true); } }),
    champ("Places", places, { aide: "0 = illimité. Une fois les places prises, « Disponible » affiche « Complet »." }),
    interrupteur("Réservé au clan (seuls les membres du clan peuvent répondre)", v.reserve_clan, (x) => changer("reserve_clan", x, true)),
    interrupteur("Créer aussi l'évènement Discord programmé", v.discord_event && droits.discord_event !== false, (x) => changer("discord_event", x, true),
      { disabled: droits.discord_event === false, titre: droits.discord_event === false ? "Le bot n'a pas la permission de créer des évènements sur ce serveur." : "" }),
    droits.discord_event === false ? h("p", { classe: "aide" }, "Le bot n'a pas la permission « Créer des évènements » : l'évènement Discord ne peut pas être créé.") : null);
}
function blocGroupement(v, changer) {
  const metiers = v.type === "metiers";
  const groupement = metiers ? "metier" : GROUPES[v.groupement] ? v.groupement : "grade";
  const champs = new Set(v.champs || []);
  const montrables = [["metiers", "Métiers"], ["grade", "Grade"], ["race", "Race"]].filter(([k]) => k !== CHAMP_DU_GROUPE[groupement]);
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, metiers ? "Les métiers" : "Le listing"),
    h("p", { classe: "aide" }, metiers ? "Chaque métier et qui l'exerce, d'après les affiches (Capitainerie). Un membre à plusieurs métiers figure dans chacun."
      : "Tout l'équipage, rangé comme tu veux, avec ce que tu choisis de montrer. Ceux sans affiche sont à la fin."),
    metiers ? null : h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Ranger par"),
      segment(groupement, [["grade", "Grade"], ["metier", "Métier"], ["race", "Race"]], (x) => changer("groupement", x), "Ranger par")),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Montrer pour chacun"),
      h("div", { classe: "rangee" }, montrables.map(([k, l]) => caseACocher(l, champs.has(k), (x) => {
        const n = new Set(composeur.v.champs || []);
        if (x) n.add(k); else n.delete(k);
        changer("champs", ["metiers", "grade", "race"].filter((c) => n.has(c)), true);
      })))));
}
function blocApparence(v, changer, E) {
  const palette = couleursDe(E);
  const nuancier = h("div", { classe: "nuancier", role: "radiogroup", "aria-label": "Couleur de la carte" });
  const majNuancier = () => remplacer(nuancier, ...palette.map(([nom, c]) => h("button", { classe: "nuance", type: "button", role: "radio", "aria-checked": String(composeur.v.couleur === c),
    "aria-label": "Couleur " + nom, title: nom, vars: { "--teinte": c }, onclick: () => { changer("couleur", c, true); majNuancier(); } })));
  majNuancier();
  const image = h("div", { classe: "image-choix" });
  const majImage = () => {
    const id = composeur.v.image;
    remplacer(image, id ? h("img", { src: BASE + "/media/" + id, alt: "Image de la carte" }) : h("span", { classe: "image-vide" }, icone("carte"), "Aucune image"),
      h("div", { classe: "rangee" },
        bouton(id ? "Changer l'image" : "Ajouter une image", { classe: "p", icone: "ajouter", reseau: true, onclick: () => choisirImage((nouvel) => { changer("image", nouvel, true); majImage(); }) }),
        id ? bouton("Retirer", { classe: "p discret", icone: "supprimer", onclick: () => { changer("image", "", true); majImage(); } }) : null));
    majBoutonsReseau(image);
  };
  majImage();
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "L'apparence"),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Couleur de la carte"), nuancier),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Image"), image,
      h("span", { classe: "champ-aide" }, v.type === "annonce" || v.type === "listing" ? "Sans image, la carte porte le bandeau du clan." : "PNG, JPEG, WebP ou GIF, 8 Mo au plus.")));
}
function blocEnvoi(v, changer, E) {
  const dests = destinationsDe(E), def = destDefaut(E);
  const valeur = String(v.destination || (def ? def.id : ""));
  const destination = liste({ valeur, label: "Où publier", plein: true, desactive: composeur.publie || !dests.length,
    options: dests.map((d) => ({ v: String(d.id), l: sansEmoji(d.nom) || "Post", sous: d.defaut ? "par défaut" : "" })),
    changer: (x) => changer("destination", String(x), true) });
  const ev = v.type === "evenement";
  const role = E.droits && E.droits.role_clan_nom ? sansEmoji(E.droits.role_clan_nom) : "";
  const mentions = [["aucune", "Aucune mention", ev ? "personne n'est notifié, même aux rappels" : ""],
    ["clan", "Le clan" + (role ? " (" + role + ")" : ""), ev ? "à la publication, puis les disponibles aux rappels" : "à la publication"]];
  if (ev) mentions.push(["inscrits", "Les disponibles", "seulement aux rappels"]);
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "L'envoi"),
    !dests.length ? bandeau("Le forum du clan n'est pas installé : il n'y a aucun post où publier. Les brouillons restent possibles.", "rouge") : null,
    destination,
    composeur.publie ? h("p", { classe: "aide" }, "Une publication ne change pas de post : pour la mettre ailleurs, annule-la et republie.") : null,
    radios("mention-" + v.type, mentions, ev || v.mention !== "inscrits" ? v.mention : "aucune", (x) => changer("mention", x, true), "Mention"));
}
async function choisirImage(fin) {
  const entree = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" });
  entree.addEventListener("change", async () => {
    const f = entree.files && entree.files[0];
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) { toast("8 Mo au plus.", "erreur"); return; }
    let b64 = "";
    try {
      b64 = await new Promise((ok, ko) => { const lec = new FileReader(); lec.onload = () => ok(String(lec.result).split(",")[1] || ""); lec.onerror = () => ko(lec.error); lec.readAsDataURL(f); });
    } catch (e) {
      console.warn("[ANNONCES][E1] image illisible sur l'appareil");
      toast("Cette image ne se lit pas sur l'appareil.", "erreur");
      return;
    }
    toast("Envoi de l'image…");
    const r = await poster("media", { nom: f.name.slice(0, 80), type: f.type, base64: b64 });
    if (r.ok && r.donnees && r.donnees.id) { fin(r.donnees.id); toast("Image ajoutée.", "succes"); }
    else toast(r.erreur || "Image refusée.", "erreur");
  });
  entree.click();
}

// ─── L'aperçu Discord (fidèle) ─────────────────────────────────────────────
const ligne = (md, ic, niveau) => ({ md, icone: ic || "", niveau: niveau || 0 });
const texteBloc = (...lignes) => ({ type: "texte", lignes });
const SEP = { type: "separateur" };
const boutonBloc = (label, style, ic) => ({ label, style, icone: ic, desactive: false, url: "" });
/** Échapper le Markdown comme `discord.utils.escape_markdown` (le lieu, sur la carte). */
const echapper = (s) => String(s || "").replace(/([\\*_~`|>#[\]()-])/g, "\\$1");

/** Un aperçu local, de même forme que celui du serveur (evenements._cartes_*) : il suit la saisie avant l'enregistrement. */
function apercuLocal(v, E, c) {
  const t = v.type, now = maintenant(), blocs = [];
  const droits = (E && E.droits) || {};
  const haut = v.mention === "clan" && droits.role_clan !== false ? "<@&clan>" : "";
  const image = v.image ? { type: "image", media: v.image, url: "media/" + v.image } : null;
  const q = Math.floor(Number(v.quand) || 0);
  let rappels = [];
  if (t === "evenement") {
    if (image) blocs.push(image);
    blocs.push(texteBloc(ligne(v.titre || "(sans titre)", "", 2), ligne("Événement du clan · Clan event", "drapeau", "petit")));
    if (v.texte) blocs.push(texteBloc(ligne(v.texte)));
    const lq = q ? [ligne("**Début · Starts** <t:" + q + ":F>", "calendrier"), ligne("<t:" + q + ":R>", "minuteur", 3)] : [ligne("**Début · Starts** à choisir · to be set", "calendrier")];
    if (v.duree_min) lq.push(ligne("**Durée · Duration** " + dureeTxt(v.duree_min), "horloge"));
    if (v.lieu) lq.push(ligne("**Lieu · Location** RELL Seas · " + echapper(v.lieu), "lieu"));
    blocs.push(SEP, texteBloc(...lq));
    if (v.reponses) {
      const places = minutes(v.places);
      blocs.push(SEP, texteBloc(ligne("**Disponibles · Available — 0" + (places ? " / " + places + " places · spots" : "") + "**", "valider"),
        ligne("Personne pour l'instant · Nobody yet", "", "petit"), ligne("**Peut-être · Maybe — 0**", "peut_etre"), ligne("**Pas disponibles · Unavailable — 0**", "annuler")));
      blocs.push({ type: "boutons", boutons: [boutonBloc("Disponible · Available", "succes", "valider"), boutonBloc("Peut-être · Maybe", "secondaire", "peut_etre"),
        boutonBloc("Pas disponible · Unavailable", "secondaire", "annuler")] });
    }
    const pied = [ligne(NOM_CLAN + (v.reserve_clan ? " · Réservé au clan · Clan only" : ""), "ancre", "petit")];
    // Les rappels déjà passés ne partiront pas : la carte ne les promet pas (comme le serveur).
    const restants = (v.rappels || []).map(minutes).filter((m) => !q || q - m * 60 > now);
    if (restants.length) {
      const avant = restants.filter((m) => m > 0);
      pied.push(ligne("Rappels · Reminders : " + [...(avant.length ? [avant.map(dureeTxt).join(", ") + " avant · before"] : []), ...(restants.includes(0) ? ["au début · at start"] : [])].join(" · "), "cloche", "petit"));
      if (v.mention !== "aucune" && v.reponses) pied.push(ligne("Les rappels mentionnent les disponibles · Reminders ping available members", "", "petit"));
    }
    blocs.push(texteBloc(...pied));
    rappels = (v.rappels || []).map(minutes).map((m) => ({ minutes: m, quand: q ? q - m * 60 : null, fait: false, passe: !!q && q - m * 60 <= now }));
  } else if (t === "annonce") {
    const [cle, titre] = BANDEAUX.annonce;
    blocs.push(image || { type: "bandeau", cle, titre, url: "/v/" + cle + ".gif" });
    blocs.push(texteBloc(ligne(v.titre || "(sans titre)", "", 2)));
    if (v.texte) blocs.push(texteBloc(ligne(v.texte)));
    blocs.push(SEP, texteBloc(ligne(NOM_CLAN + (c && c.publieLe ? " · <t:" + c.publieLe + ":D>" : ""), "ancre", "petit")));
    blocs.push({ type: "boutons", boutons: [boutonBloc("Vu · Seen" + (c && c.vus ? " · " + c.vus : ""), "succes", "valider")] });
  } else {
    const groupement = t === "metiers" ? "metier" : GROUPES[v.groupement] ? v.groupement : "grade";
    const [fr, en] = GROUPES[groupement];
    if (image) blocs.push(image);
    else if (BANDEAUX[t]) blocs.push({ type: "bandeau", cle: BANDEAUX[t][0], titre: BANDEAUX[t][1], url: "/v/" + BANDEAUX[t][0] + ".gif" });
    blocs.push(texteBloc(ligne(v.titre || NOMS_TYPES[t], "", 2), ligne("**Les membres du clan · Clan members** · par " + fr + " · by " + en, "membres")));
    if (v.texte) blocs.push(texteBloc(ligne(v.texte)));
    blocs.push(SEP, texteBloc(ligne("Chaque " + fr + ", puis ses membres, d'après les affiches au moment de publier. Enregistre le brouillon : l'aperçu montre alors la liste exacte.", "", "petit")));
    blocs.push(texteBloc(ligne(NOM_CLAN, "ancre", "petit")));
  }
  const couleur = RE_HEX.test(v.couleur || "") ? v.couleur : COULEURS[0][1];
  return { cartes: [{ haut, couleur, blocs }], roles: { clan: sansEmoji(droits.role_clan_nom) || "Clan" }, personnes: {}, rappels,
    discord_event: t === "evenement" ? { demande: !!v.discord_event, permission: droits.discord_event !== false, lien: "" } : null };
}

function apercuDiscord(d, o) {
  const cartes = (d && d.cartes) || [];
  const ctx = { personnes: d.personnes || {}, roles: d.roles || {}, salons: d.salons || {} };
  const n = cartes.reduce((a, c) => a + (Number(c.caracteres) || 0), 0);
  const dest = d.destination || o.destination;
  const tete = h("div", { classe: "apercu-tete" }, icone("discord"), h("b", {}, "Aperçu Discord"),
    h("span", { classe: "meta" }, o.local ? "pendant la saisie" : "rendu du serveur" + (n ? " · " + nombre(n) + " caractères" : "") + (cartes.length > 1 ? " · " + cartes.length + " messages" : "")));
  const ou = dest && dest.nom ? h("p", { classe: "meta" }, icone("discord", "ic-p"), " Dans « " + sansEmoji(dest.nom) + " »") : null;
  const corps = h("div", { classe: "discord", role: "img", "aria-label": "Aperçu du message tel qu'il apparaîtra sur Discord" },
    h("div", { classe: "discord-auteur" }, h("span", { classe: "discord-av" }, "G"), h("b", {}, "GoRP"), h("span", { classe: "discord-app" }, "APP"), h("span", { classe: "discord-quand" }, "Aujourd'hui à " + heure(maintenant()))),
    cartes.length ? cartes.map((c) => carteDiscord(c, ctx)) : h("p", { classe: "discord-vide" }, "Le message apparaîtra ici."));
  const notes = [];
  if ((d.erreurs || []).length) notes.push(bandeau(h("span", {}, h("b", {}, "À corriger : "), d.erreurs.join(" · ")), "rouge"));
  if ((d.avertissements || []).length) notes.push(bandeau(d.avertissements.join(" · "), ""));
  const rappels = (d.rappels || []).length ? h("div", { classe: "rappels-ligne" }, h("span", { classe: "champ-lib" }, "Rappels"), h("ul", { classe: "rappels" }, d.rappels.map((r) => h("li", { classe: r.fait ? "fait" : r.passe ? "passe" : "" },
    icone(r.fait ? "valider" : "cloche", "ic-p"), libRappel(r.minutes), r.quand ? h("span", { classe: "meta" }, " · " + date(r.quand, true)) : null)))) : null;
  const de = d.discord_event && d.discord_event.demande ? h("p", { classe: "meta" }, icone("calendrier", "ic-p"),
    d.discord_event.lien ? " Évènement Discord créé." : d.discord_event.permission === false ? " Évènement Discord : permission manquante." : " L'évènement Discord sera créé à la publication.") : null;
  return h("div", { classe: "apercu-cadre" }, tete, ou, corps, ...notes, rappels, de);
}
function carteDiscord(c, ctx) {
  const haut = c.haut ? h("div", { classe: "discord-haut" }, markdown(c.haut, ctx)) : null;
  const blocs = (c.blocs || []).map((b) => blocDiscord(b, ctx)).filter(Boolean);
  return h("div", { classe: "discord-message" }, haut, h("div", { classe: "discord-carte", vars: { "--accent": RE_HEX.test(c.couleur || "") ? c.couleur : "#4f545c" } }, blocs));
}
function blocDiscord(b, ctx) {
  const t = b.type || (b.lignes ? "texte" : b.boutons ? "boutons" : b.url ? "image" : "");
  if (t === "separateur") return h("hr", { classe: "discord-sep" });
  if (t === "texte") return h("div", { classe: "discord-texte" }, (b.lignes || []).map((l) => {
    const niveau = l.niveau === 1 ? " h1" : l.niveau === 2 ? " h2" : l.niveau === 3 ? " h3" : l.niveau === "petit" ? " petit" : "";
    return h("div", { classe: "discord-ligne" + niveau }, l.icone ? icone(l.icone, "discord-emoji") : null, l.jeu ? iconeJeu(l.jeu) : null, markdown(l.md || "", ctx));
  }));
  if (t === "image") {
    const src = srcSure(b.url) || (b.media ? srcSure("media/" + b.media) : "");
    return src ? h("figure", { classe: "discord-media" }, h("img", { src, alt: b.titre || "" })) : null;
  }
  if (t === "bandeau") {
    // Un bandeau du bot (/v/<nom>.gif, servi par ce serveur) : l'adresse est vérifiée ici, dom.js ne connaît pas /v/.
    const u = String(b.url || "");
    if (!RE_BANDEAU.test(u)) return null;
    const img = h("img", { alt: b.titre || "" });
    img.setAttribute("src", u);
    return h("figure", { classe: "discord-media bandeau" }, img);
  }
  if (t === "boutons") return h("div", { classe: "discord-boutons" }, (b.boutons || []).map((x) => h("span", { classe: "discord-bouton " + (x.url ? "lien" : STYLE_BOUTON[x.style] || "secondary") + (x.desactive ? " desactive" : "") },
    x.icone ? icone(x.icone, "discord-emoji") : null, x.label || "")));
  return null;
}
function iconeJeu(j) {
  const type = Array.isArray(j) ? j[0] : j && j.type, cle = Array.isArray(j) ? j[1] : j && j.cle;
  const cat = vueJeu("catalogue");
  const e = cat && !cat.erreur && type ? elementCat(cat, type, cle) : null;
  const src = e && srcSure(e.icone);
  if (!src) return null;
  // L'icône officielle pas encore livrée (404) : rien plutôt qu'une image cassée (Discord n'en montre pas non plus).
  const img = h("img", { classe: "discord-emoji", src, alt: "" });
  img.addEventListener("error", () => img.remove(), { once: true });
  return img;
}
/** Un extrait lisible d'un texte Markdown (les listes) : sans les marques, une seule ligne. */
function texteSimple(md) {
  return String(md || "").replace(/<t:(-?\d+)(?::[tTdDfFR])?>/g, (_m, t) => date(Number(t), true)).replace(/<@&?!?\d+>/g, "@…").replace(/<#\d+>/g, "#…")
    .replace(/<a?:\w+:\d+>/g, "").replace(/^(#{1,3}|-#|>>>|>|\s*[-*]|\s*\d+\.)\s+/gm, "").replace(/\[([^\]]+)\]\((https:[^)]+)\)/g, "$1")
    .replace(/(\*\*|__|~~|\|\|)(.+?)\1/g, "$2").replace(/\*(?!\s)(.+?)\*/g, "$1").replace(/(^|[^\w\\])_(?!\s)(.+?)_(?!\w)/g, "$1$2").replace(/`([^`]+)`/g, "$1")
    .replace(/\\([\\*_~`|>#[\]()<:@-])/g, "$1").replace(/\s+/g, " ").trim();
}

/** Le Markdown de Discord, construit en nœuds (jamais d'HTML) : titres, gras, italique, souligné, barré, code,
 *  citations, listes, liens masqués, mentions (pastilles), horodatages <t:…:F|R|…>, caractères échappés (\*). */
export function markdown(texte, ctx = {}) {
  const frag = document.createDocumentFragment();
  const lignes = String(texte ?? "").split("\n");
  let dansCode = false, code = [];
  for (const brut of lignes) {
    if (/^```/.test(brut.trim())) {
      if (dansCode) { ajouter(frag, [h("pre", { classe: "discord-code" }, code.join("\n"))]); code = []; }
      dansCode = !dansCode;
      continue;
    }
    if (dansCode) { code.push(brut); continue; }
    let l = brut, classe = "md-ligne";
    let m;
    if ((m = /^(#{1,3}) (.*)$/.exec(l))) { classe += " md-h" + m[1].length; l = m[2]; }
    else if ((m = /^-# (.*)$/.exec(l))) { classe += " md-petit"; l = m[1]; }
    else if ((m = /^>>> ?(.*)$/.exec(l)) || (m = /^> ?(.*)$/.exec(l))) { classe += " md-citation"; l = m[1]; }
    else if ((m = /^\s*[-*] (.*)$/.exec(l))) { classe += " md-liste"; l = m[1]; }
    else if ((m = /^\s*(\d+)\. (.*)$/.exec(l))) { classe += " md-liste-num"; l = m[2]; }
    const el = h("div", { classe }, enLigne_(l, ctx));
    if (!l.trim() && classe === "md-ligne") el.classList.add("md-vide");
    ajouter(frag, [el]);
  }
  if (dansCode && code.length) ajouter(frag, [h("pre", { classe: "discord-code" }, code.join("\n"))]);
  const s = h("span", { classe: "md" });
  ajouter(s, [frag]);
  return s;
}
const MOTIFS = [
  [/^\\([\\*_~`|>#[\]()<:@-])/, (m) => m[1]],
  [/^\*\*(.+?)\*\*/, (m, c) => h("strong", {}, enLigne_(m[1], c))],
  [/^__(.+?)__/, (m, c) => h("u", {}, enLigne_(m[1], c))],
  [/^\*(?!\s)(.+?)\*/, (m, c) => h("em", {}, enLigne_(m[1], c))],
  [/^_(?!\s)(.+?)_(?!\w)/, (m, c) => h("em", {}, enLigne_(m[1], c))],
  [/^~~(.+?)~~/, (m, c) => h("s", {}, enLigne_(m[1], c))],
  [/^\|\|(.+?)\|\|/, (m, c) => h("span", { classe: "md-cache", title: "Texte caché" }, enLigne_(m[1], c))],
  [/^`([^`]+)`/, (m) => h("code", {}, m[1])],
  [/^\[([^\]]+)\]\((https:\/\/[^\s)]+)\)/, (m, c) => h("a", { href: m[2] }, enLigne_(m[1], c))],
  [/^<t:(-?\d+)(?::([tTdDfFR]))?>/, (m) => h("span", { classe: "md-heure", title: date(Number(m[1]), true) }, horodatage(Number(m[1]), m[2] || "f"))],
  [/^<@&(\w+)>/, (m, c) => h("span", { classe: "md-mention" }, "@" + (sansEmoji((c.roles || {})[m[1]]) || "rôle"))],
  [/^<@!?(\d+)>/, (m, c) => h("span", { classe: "md-mention" }, "@" + (sansEmoji((c.personnes || {})[m[1]]) || "membre"))],
  [/^<#(\d+)>/, (m, c) => h("span", { classe: "md-mention" }, "#" + (sansEmoji((c.salons || {})[m[1]]) || "salon"))],
  [/^@(everyone|here)\b/, (m) => h("span", { classe: "md-mention" }, "@" + m[1])],
  [/^<a?:\w+:\d+>/, () => h("span", { classe: "md-emoji-app", "aria-hidden": "true" })],
  [/^https:\/\/[^\s<]+[^\s<.,;:!?)]/, (m) => h("a", { href: m[0] }, m[0])],
];
function enLigne_(texte, ctx) {
  const out = [];
  let reste = String(texte), tampon_ = "";
  while (reste) {
    let trouve = false;
    for (const [re, fn] of MOTIFS) {
      const m = re.exec(reste);
      if (m) {
        if (tampon_) { out.push(tampon_); tampon_ = ""; }
        out.push(fn(m, ctx));
        reste = reste.slice(m[0].length);
        trouve = true;
        break;
      }
    }
    if (!trouve) { tampon_ += reste[0]; reste = reste.slice(1); }
  }
  if (tampon_) out.push(tampon_);
  return out;
}
/** <t:X:…> comme Discord l'affiche à un lecteur de Paris. */
function horodatage(t, f) {
  if (f === "R") return t > maintenant() ? dans(t) : depuis(t);
  const o = { t: { hour: "2-digit", minute: "2-digit" }, T: { hour: "2-digit", minute: "2-digit", second: "2-digit" }, d: { day: "2-digit", month: "2-digit", year: "numeric" },
    D: { day: "numeric", month: "long", year: "numeric" }, f: { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" },
    F: { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" } }[f];
  return new Intl.DateTimeFormat("fr-FR", Object.assign({ timeZone: "Europe/Paris" }, o || {})).format(new Date(t * 1000));
}

// ─── Les listes ─────────────────────────────────────────────────────────────
function enAttenteDe(el) {
  const cles = [...new Set([el.id ? String(el.id) : "", el.cle_client || "", el._cle || ""].filter(Boolean))];
  const ops = cles.flatMap((c) => opsDe("brouillon", c));
  return ops.length ? ops[ops.length - 1].etat : el._attente || "";
}
function etatDe(el) {
  if (el.statut === "publie" && el.type === "evenement") return el.phase === "en_cours" ? ["En cours", "vert"] : el.phase === "termine" ? ["Terminé", "encre"] : ["Publié", "vert"];
  return STATUTS[el.statut] || [el.statut || "", "encre"];
}
function ligneQuand(el) {
  if (el.type !== "evenement") return null;
  const brouillon = !el.statut || el.statut === "brouillon";
  if (!el.quand) return brouillon ? h("p", { classe: "minuteur-vivant alerte" }, icone("minuteur"), h("span", {}, "Date à choisir")) : null;
  const futur = el.quand > maintenant();
  const etatTxt = el.statut === "annule" ? "annulé" : brouillon ? (futur ? dans(el.quand) : "date passée")
    : el.phase === "en_cours" ? "en cours" : el.phase === "termine" || !futur ? "passé" : dans(el.quand);
  return h("p", { classe: "minuteur-vivant" + (brouillon && !futur ? " alerte" : "") }, icone("minuteur"), h("span", {}, dateLongue(el.quand), " · ", h("b", {}, etatTxt)));
}
function ligneMeta(el) {
  const par = (x) => (x ? " par " + nomDe(P(x)) : "");
  const morceaux = [];
  if (!el.statut || el.statut === "brouillon") morceaux.push("Modifié " + depuis(el.maj || maintenant()) + par(el.maj_par));
  else {
    if (el.publie) morceaux.push("Publié " + depuis(el.publie) + par(el.publie_par));
    if (el.statut === "annule" || el.statut === "retire") morceaux.push((el.statut === "annule" ? "annulé " : "retiré ") + depuis(el.maj) + par(el.maj_par));
  }
  if (el.destination && typeof el.destination === "object" && el.destination.nom) morceaux.push((el.statut === "brouillon" ? "pour « " : "dans « ") + sansEmoji(el.destination.nom) + " »");
  return majuscule(morceaux.join(" · "));
}
function carteElement(el, actions) {
  const f = aplatir(el);
  const [lib, coul] = etatDe(el);
  const att = enAttenteDe(el);
  const r = el.reponses || {};
  const evenementPublie = el.type === "evenement" && el.statut && el.statut !== "brouillon";
  return h("article", { classe: "feuillet evt-carte" + (att ? " en-attente" : ""), vars: { "--accent": RE_HEX.test(f.couleur || "") ? f.couleur : "#a8823f" } },
    h("div", { classe: "evt-tete" }, icone((TYPES.find((t) => t[0] === el.type) || TYPES[1])[2]), h("span", { classe: "champ-lib" }, LIB_TYPE[el.type] || el.type),
      el.statut && el.statut !== "brouillon" ? tampon(lib, coul, true) : null, att ? tampon(att === "conflit" ? "Conflit" : att === "refus" || att === "erreur" ? "Refusé" : "En attente d'envoi", att === "attente" ? "ambre" : "", true) : null),
    h("h3", { classe: "titre-carte" }, el.titre || f.titre || "Sans titre"),
    ligneQuand(el),
    f.texte ? h("p", { classe: "texte coupe2" }, texteSimple(f.texte)) : null,
    evenementPublie && f.reponses ? h("div", { classe: "reponses-evt" },
      pastille(nombre(r.disponibles || 0) + " disponible" + ((r.disponibles || 0) > 1 ? "s" : ""), "#3f6b3a"), pastille(nombre(r.peut_etre || 0) + " peut-être", "#a8641c"),
      pastille(nombre(r.pas_disponibles || 0) + " pas disponible" + ((r.pas_disponibles || 0) > 1 ? "s" : ""), "#8e2a24"),
      f.places ? h("span", { classe: "meta" }, nombre(r.disponibles || 0) + " / " + nombre(f.places) + " places") : null) : null,
    el.type === "annonce" && el.statut && el.statut !== "brouillon" ? h("p", { classe: "meta" }, r.vus ? "Vu par " + nombre(r.vus) + (r.vus > 1 ? " membres" : " membre") : "Personne ne l'a encore marquée « Vu ».") : null,
    el.note ? h("p", { classe: "aide" }, el.note) : null,
    h("p", { classe: "meta" }, ligneMeta(el)),
    h("div", { classe: "feuillet-pied" }, actions));
}
/** Les gestes possibles selon l'état réel de l'élément (le serveur refuse le reste). */
function actionsDe(el, recharger) {
  if (!el.statut || el.statut === "brouillon") return [
    bouton("Ouvrir", { classe: "p principal", icone: "plume", onclick: () => ouvrirDansComposeur(el) }),
    bouton("Dupliquer", { classe: "p", icone: "copier", onclick: () => dupliquer(el, true) }),
    bouton("Supprimer", { classe: "p discret danger", icone: "supprimer", onclick: () => supprimerBrouillon(el, recharger) }),
  ];
  const a = [];
  if (el.lien && el.statut !== "retire") a.push(h("a", { classe: "bouton p", href: el.lien }, icone("discord"), h("span", {}, "Sur Discord")));
  if (el.discord_event && el.discord_event.lien && el.statut === "publie" && el.phase !== "termine") a.push(h("a", { classe: "bouton p discret", href: el.discord_event.lien }, icone("calendrier"), h("span", {}, "Évènement Discord")));
  if (el.statut === "envoi" || el.statut === "incertain") a.push(bouton("Vérifier", { classe: "p", icone: "oeil", onclick: recharger }));
  if (el.statut === "incertain") a.push(bouton("Forcer la publication", { classe: "p principal", reseau: true, onclick: async () => {
    const ok = await confirmer({ titre: "Forcer la publication ?", texte: "À faire seulement si la carte n'est pas dans le post : sinon, elle y serait deux fois.", libelleOk: "Forcer la publication", taille: "etroite" });
    if (!ok) return;
    const r = await versDiscord("clan/publier", { id: el.id, version: el.version, forcer: true });
    toast(r.ok && !(r.donnees && r.donnees.incertain) ? "Publication forcée." : messageErreur(r, "Publication impossible."), r.ok ? "succes" : "erreur");
    recharger();
  } }));
  if (enLigneSurDiscord(el)) {
    a.push(bouton("Modifier", { classe: "p", icone: "plume", onclick: () => ouvrirDansComposeur(el) }),
      bouton("Actualiser la carte", { classe: "p discret", icone: "synchro", reseau: true, titre: "Réécrire la carte sur Discord d'après les données du jour (réponses, noms, affiches).", onclick: async () => {
        const r = await versDiscord("clan/modifier", { id: el.id, version: el.version });
        toast(r.ok ? "Carte actualisée sur Discord." : messageErreur(r, "Actualisation impossible."), r.ok ? "succes" : "erreur");
        recharger();
      } }));
  }
  if (enLigneSurDiscord(el) || el.statut === "incertain") a.push(boutonAnnuler(el, recharger));
  if (["annule", "retire"].includes(el.statut) || (el.statut === "publie" && !enLigneSurDiscord(el))) a.push(bouton("Refaire à partir de celui-ci", { classe: "p", icone: "copier", onclick: () => dupliquer(el, false) }));
  return a;
}
function boutonAnnuler(el, recharger) {
  const evenement = el.type === "evenement" && el.statut === "publie";
  return bouton(evenement ? "Annuler l'événement" : "Retirer", { classe: "p danger", reseau: true, onclick: async () => {
    const v = el.valeurs || {};
    const prevenirPossible = evenement && v.reponses && v.mention !== "aucune" && (el.reponses || {}).disponibles > 0;
    let prevenir = prevenirPossible;
    const ok = await confirmer({
      titre: (evenement ? "Annuler « " : "Retirer « ") + (el.titre || "Sans titre") + " » ?", style: "danger", libelleOk: evenement ? "Annuler l'événement" : "Retirer",
      texte: evenement ? "La carte l'indique sur Discord, les réponses et les rappels s'arrêtent" + (el.discord_event ? ", l'évènement Discord est annulé" : "") + "."
        : "Les messages de la publication sont supprimés du post.",
      contenu: prevenirPossible ? [caseACocher("Prévenir les disponibles (un message les mentionne)", true, (x) => { prevenir = x; })] : null,
    });
    if (!ok) return;
    const r = await versDiscord("clan/annuler", { id: el.id, prevenir: !!prevenir });
    toast(r.ok ? (r.donnees && r.donnees.deja ? "C'était déjà fait." : evenement ? "Événement annulé." : "Retiré du post.") : messageErreur(r, "Impossible pour le moment."), r.ok ? "succes" : "erreur");
    recharger();
  } });
}
async function supprimerBrouillon(el, recharger) {
  const ok = await confirmer({ titre: "Supprimer ce brouillon ?", texte: "« " + (el.titre || "Sans titre") + " » disparaît. Rien n'a été publié.", libelleOk: "Supprimer", style: "danger" });
  if (!ok) return;
  // Le brouillon ouvert dans le composeur : le composeur repart de zéro (sinon il enregistrerait un brouillon disparu).
  if (composeur && ((el.id && String(composeur.id) === String(el.id)) || (el.cle_client && composeur.cle_client === el.cle_client))) {
    composeur = null;
    await oublierSaisie("composeur");
  }
  const corps = el.id ? { id: el.id, version: el.version } : { cle_client: el.cle_client };
  await mettreEnFile("clan/supprimer_brouillon", corps, { genre: "brouillon", cle: el.id ? String(el.id) : el.cle_client || el._cle, resume: "Suppression du brouillon « " + (el.titre || "Sans titre") + " »", retrait: true });
  recharger();
}
/** Un nouveau brouillon d'après un élément (« Dupliquer » un brouillon, « Refaire » une publication passée). */
function dupliquer(el, copie) {
  const f = nettoyer(aplatir(el));
  for (const k of ["id", "version", "cle_client", "statut"]) delete f[k];
  const type = el.type || "evenement";
  const v = Object.assign(valeursNeuves(dernierE, type), f, { type });
  if (copie) v.titre = ((v.titre || "") + " (copie)").slice(0, LIMITES.titre);
  if (type === "evenement" && v.quand && v.quand <= maintenant() + 3600) v.quand = prochaineFois(v.quand);
  composeur = { v, id: null, version: null, cle_client: null, publie: false, sale: true };
  garderSaisie("composeur", composeur);
  aller("equipage", "annonces", "composer");
  toast(copie ? "Copie ouverte dans le composeur." : "Ouvert dans le composeur : vérifie la date, puis publie.", "succes");
}
function listeBrouillons(E, recharger) {
  const l = (E.brouillons || []).slice().sort((a, b) => (b.maj || 0) - (a.maj || 0));
  if (!l.length) return vide("Aucun brouillon", "Compose un événement ou une annonce : il est gardé ici jusqu'à sa publication.", "parchemin");
  return [h("p", { classe: "aide avance" }, "Les brouillons sont gardés sur le serveur — et sur cet appareil hors ligne, envoyés au retour de la connexion."),
    paginer("evt-brouillons", l, (el) => carteElement(el, actionsDe(el, recharger)), { classe: "grille egale" })];
}
function listeAVenir(E, recharger) {
  const l = (E.a_venir || []).slice().sort((a, b) => (a.quand || a.publie || 0) - (b.quand || b.publie || 0));
  if (!l.length) return vide("Rien à venir", "Un événement publié reste ici jusqu'à sa fin, avec son minuteur et les réponses.", "minuteur");
  return [paginer("evt-avenir", l, (el) => carteElement(el, actionsDe(el, recharger)), { pas: 12, classe: "grille egale" })];
}
function listePasses(E, recharger) {
  // Du plus récemment touché au plus ancien, rangés par période (la plus récente ouverte) : jamais un long mur de cartes.
  const quand = (el) => el.maj || el.publie || el.quand || 0;
  const l = (E.passes || []).slice().sort((a, b) => quand(b) - quand(a));
  if (!l.length) return vide("Rien de passé pour l'instant", "Les annonces publiées viennent ici, ainsi que les événements terminés, annulés ou retirés.", "coffre");
  const periodes = parPeriode(l, quand);
  const zone = h("div", { classe: "groupes-zone" }, groupes(periodes.map(([k, lib, g]) => ({ cle: "evt-passes-" + k, titre: lib, compte: g.length,
    contenu: () => paginer("evt-passes-" + k, g, (el) => carteElement(el, actionsDe(el, recharger)), { pas: 12, classe: "grille egale" }) }))));
  return [
    h("div", { classe: "rangee entre" }, h("p", { classe: "aide avance" }, "Les annonces, métiers et listings publiés restent ici : leur « Vu », les modifier, les retirer. Les événements terminés, annulés ou retirés y restent 60 jours (rubrique Nettoyage)."),
      periodes.length > 1 ? outilsGroupes(zone) : null),
    E.passes_total && E.passes_total > l.length ? h("p", { classe: "aide" }, "Les " + nombre(l.length) + " plus récents sur " + nombre(E.passes_total) + ".") : null,
    zone,
  ];
}
