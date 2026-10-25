// annonces.js — « Annonces & événements » du salon Info du clan : composer (événement avec date, minuteur, rappels,
// réponses, places et évènement Discord ; annonce ; annonce officielle des métiers ; listing complet), aperçu FIDÈLE
// de la carte Discord, brouillons (gardés hors ligne), à venir, passés.
// Contrat : evenements.py (GET clan/evenements, POST clan/brouillon | supprimer_brouillon [hors ligne],
// GET clan/apercu, POST clan/publier | modifier | annuler [connexion exigée]).

import { h, icone, date, heure, depuis, dans, dateLongue, nombre, sansEmoji, uuid, retarder, contient, maintenant, srcSure, dureeMinutes, majuscule, remplacer, telephone, BASE, ajouter } from "./dom.js";
import { etat, emettre, ecouter, enLigne, raisonHorsLigne, filtres, aller } from "./noyau.js";
import { lire, poster } from "./api.js";
import { charger, vue as vueJeu, perime, typeMetier, element as elementCat } from "./donnees.js";
import { mettreEnFile, garderSaisie, lireSaisie, oublierSaisie, opsDe, file } from "./hors_ligne.js";
import {
  bouton, boutonIcone, pastille, tampon, vide, tuile, tuiles, segment, recherche, liste, champ, saisie, zoneTexte, interrupteur,
  caseACocher, radios, confirmer, pancarte, toast, section, squelettes, paginer, bandeau, compteur, majBoutonsReseau,
} from "./ui.js";

const TYPES = [
  ["evenement", "Événement", "calendrier", "Une date, un minuteur, des rappels, et les réponses « Dispo · Peut-être · Pas dispo »."],
  ["annonce", "Annonce", "cloche", "Un message soigné pour tout l'équipage, avec ou sans image."],
  ["metiers", "Les métiers", "drapeau", "L'annonce officielle du métier de chacun, tirée des affiches."],
  ["listing", "Le listing", "parchemin", "La liste complète de l'équipage, rangée comme tu veux."],
];
const LIB_TYPE = Object.fromEntries(TYPES.map(([k, l]) => [k, l]));
const STATUTS = { brouillon: ["Brouillon", "encre"], envoi: ["Envoi en cours", "mer"], publie: ["Publié", "vert"], annule: ["Annulé", ""], retire: ["Retiré", "encre"], incertain: ["À vérifier", "ambre"] };
const CHAMPS = {
  evenement: ["titre", "texte", "quand", "duree_min", "lieu", "image", "couleur", "rappels", "mention", "destination", "reponses", "places", "discord_event", "reserve_clan"],
  annonce: ["titre", "texte", "image", "couleur", "mention", "destination"],
  metiers: ["titre", "texte", "image", "couleur", "mention", "destination", "groupement", "champs"],
  listing: ["titre", "texte", "image", "couleur", "mention", "destination", "groupement", "champs"],
};
const LIMITE_TEXTE = { evenement: 2000, annonce: 3500, metiers: 1500, listing: 1500 };
const COULEURS = ["#a8823f", "#8e2a24", "#1f4e5a", "#3f6b3a", "#a8641c", "#5e3a4e", "#4a5560", "#2b1d12"];
const RAPPELS = [10080, 1440, 180, 60, 30, 15, 5];
const libRappel = (m) => (m >= 1440 && m % 1440 === 0 ? (m / 1440) + " j" : m >= 60 && m % 60 === 0 ? (m / 60) + " h" : m + " min");

/** Un élément du serveur, à plat : ses champs (valeurs) au même niveau. */
export function aplatir(el) {
  if (!el) return {};
  const v = el.valeurs || {};
  return Object.assign({}, v, { id: el.id, version: el.version, cle_client: el.cle_client, type: el.type, titre: el.titre ?? v.titre, quand: el.quand ?? v.quand, destination: el.destination ?? v.destination, statut: el.statut });
}

// ─── La rubrique ────────────────────────────────────────────────────────────
const SOUS = [["composer", "Composer", "plume"], ["brouillons", "Brouillons", "parchemin"], ["a-venir", "À venir", "minuteur"], ["passes", "Passés", "coffre"]];
let composeur = null; // l'état du formulaire (survit aux changements de sous-onglet)

export function annonces(vue, ctx) {
  const sous = SOUS.some(([k]) => k === ctx.sous) ? ctx.sous : "composer";
  const onglets = h("div", { classe: "sous-onglets", role: "tablist", "aria-label": "Annonces et événements" });
  const zone = h("div", { classe: "pile" }, squelettes(3));
  ajouter(vue, [onglets, zone]);
  let construit = false, ctrl = null;
  const maj = async (forcer) => {
    const E = await charger("evenements", { forcer });
    if (!zone.isConnected) return;
    const nb = E && !E.erreur ? { brouillons: (E.brouillons || []).length, "a-venir": (E.a_venir || []).length, passes: E.passes_total ?? (E.passes || []).length } : {};
    remplacer(onglets, ...SOUS.map(([k, l, ic]) => h("a", { classe: "etiquette", role: "tab", href: "#equipage/annonces/" + k, "aria-selected": String(k === sous) },
      icone(ic), l, nb[k] ? h("span", { classe: "compteur calme" }, String(nb[k])) : null)));
    if (!E || E.erreur) { remplacer(zone, vide("Annonces indisponibles", (E && E.erreur) || "Réessaie dans un instant.", "hors_ligne")); return; }
    if (sous === "composer") {
      if (!construit) { construit = true; ctrl = await composer(zone, E); }
      else if (ctrl) ctrl.majDonnees(E);
    } else remplacer(zone, ...[{ brouillons: listeBrouillons, "a-venir": listeAVenir, passes: listePasses }[sous](E, () => maj(true))].flat());
  };
  maj();
  return { maj: () => maj(false), majJeu: () => maj(false), majFile: () => maj(false) };
}

// ─── Le composeur ───────────────────────────────────────────────────────────
function valeursNeuves(E, type) {
  const d = Object.assign({}, (E && E.defauts) || {});
  const dest = ((E && E.destinations) || []).find((x) => x.defaut) || ((E && E.destinations) || [])[0];
  const demain = new Date(Date.now() + 86400000);
  demain.setHours(21, 0, 0, 0);
  const base = {
    type, titre: "", texte: "", quand: Math.floor(demain.getTime() / 1000), duree_min: 60, lieu: "", image: "", couleur: COULEURS[0],
    rappels: ((E && E.rappels_suggeres) || [60, 15]).slice(0, 5), mention: type === "evenement" ? "clan" : "aucune", destination: dest ? String(dest.id) : "",
    reponses: type === "evenement", places: 0, discord_event: type === "evenement" && !!(E && E.droits && E.droits.discord_event), reserve_clan: false,
    groupement: "metier", champs: ["metiers", "grade"],
  };
  // Les défauts du serveur : à plat ({duree_min: 90}), communs ({commun: {…}}) ou par type ({evenement: {…}}).
  // Seuls les champs connus du composeur sont repris (le serveur refuse un champ inconnu).
  const connus = (o) => Object.fromEntries(Object.entries(o && typeof o === "object" && !Array.isArray(o) ? o : {}).filter(([k]) => k in base && k !== "type"));
  return Object.assign(base, connus(d), connus(d.commun), connus(d[type]), { type });
}

async function composer(zone, E0) {
  let E = E0;
  const garde = await lireSaisie("composeur");
  if (!composeur && garde && garde.valeur && garde.valeur.v) composeur = Object.assign({ restaure: true }, garde.valeur);
  if (!composeur) composeur = { v: valeursNeuves(E, "evenement"), id: null, version: null, cle_client: null, publie: false, sale: false };
  const formulaire = h("div", { classe: "composeur-form pile" });
  const apercuZone = h("div", { classe: "apercu-discord-zone" });
  const statut = h("p", { classe: "composeur-statut", "aria-live": "polite" });
  const actions = h("div", { classe: "rangee composeur-actions" });
  const bascule = segment("form", [["form", "Rédiger"], ["apercu", "Aperçu Discord"]], (v) => { zone.classList.toggle("voir-apercu", v === "apercu"); }, "Vue");
  bascule.classList.add("seulement-telephone");
  zone.classList.remove("voir-apercu");
  remplacer(zone, bascule, h("div", { classe: "atelier composeur" }, h("div", { classe: "pile" }, formulaire, statut, actions), h("div", { classe: "collant" }, apercuZone)));
  const garderLocal = retarder(() => garderSaisie("composeur", composeur), 400);
  const apercuServeur = retarder(() => majApercu(true), 900);
  let apercuDistant = null;

  const changer = (k, v, sansRendu) => {
    composeur.v[k] = v;
    composeur.sale = true;
    garderLocal();
    majApercu(false);
    majStatut();
    if (!sansRendu) construire();
  };
  const etiquetteType = (t) => h("button", { classe: "choix-type" + (composeur.v.type === t[0] ? " actif" : ""), type: "button", "aria-pressed": String(composeur.v.type === t[0]),
    disabled: composeur.publie || null, onclick: () => { if (composeur.v.type !== t[0]) { const ancien = composeur.v; composeur.v = Object.assign(valeursNeuves(E, t[0]), { titre: ancien.titre, texte: ancien.texte, couleur: ancien.couleur, image: ancien.image, destination: ancien.destination }); composeur.sale = true; garderLocal(); construire(); majApercu(false); } } },
  icone(t[2]), h("b", {}, t[1]), h("span", {}, t[3]));

  function construire() {
    const v = composeur.v, t = v.type;
    const lim = (E.limites && E.limites[t]) || {};
    const blocs = [];
    if (composeur.restaure) blocs.push(bandeau("Ta dernière saisie a été retrouvée sur cet appareil : tu reprends où tu en étais.", "vert",
      bouton("Repartir de zéro", { classe: "p discret", onclick: () => nouveau() })));
    if (composeur.publie) blocs.push(bandeau(h("span", {}, h("b", {}, "Élément déjà publié. "), "Tes changements partent sur Discord avec « Enregistrer sur Discord » (connexion exigée)."), ""));
    blocs.push(h("div", { classe: "choix-types", role: "group", "aria-label": "Type" }, TYPES.map(etiquetteType)));
    const titre = saisie({ value: v.titre, maxlength: lim.titre || 100, placeholder: t === "evenement" ? "Sortie en mer : le boss des abysses" : "Le titre, en quelques mots" });
    titre.addEventListener("input", () => changer("titre", titre.value, true));
    blocs.push(champ("Titre", titre, { aide: compteurCaracteres(titre, lim.titre || 100) }));
    const texte = zoneTexte({ rows: 7, maxlength: lim.texte || LIMITE_TEXTE[t], placeholder: t === "metiers" ? "Un mot d'introduction (facultatif)" : "Le message. **gras**, *italique*, __souligné__, ~~barré~~, > citation, - liste" }, v.texte);
    texte.addEventListener("input", () => changer("texte", texte.value, true));
    blocs.push(h("div", { classe: "champ" }, h("label", { classe: "champ-lib", for: texte.id || (texte.id = "composeur-texte") }, t === "metiers" || t === "listing" ? "Introduction" : "Texte"),
      barreMarkdown(texte, () => changer("texte", texte.value, true)), texte, h("span", { classe: "champ-aide" }, compteurCaracteres(texte, lim.texte || LIMITE_TEXTE[t]), " · Markdown de Discord.")));
    if (t === "evenement") blocs.push(blocEvenement(v, changer, E));
    if (t === "metiers" || t === "listing") blocs.push(blocGroupement(v, changer));
    blocs.push(blocApparence(v, changer, E));
    blocs.push(blocEnvoi(v, changer, E));
    remplacer(formulaire, ...blocs);
    majActions();
    majBoutonsReseau(formulaire);
  }

  function majStatut() {
    const ops = composeur.cle_client || composeur.id ? opsDe("brouillon", composeur.cle_client || String(composeur.id)) : [];
    const att = ops.find((o) => o.etat === "attente"), conf = ops.find((o) => o.etat === "conflit");
    statut.textContent = conf ? "Conflit : ce brouillon a changé ailleurs. Ouvre la file d'envoi pour choisir la bonne version."
      : att ? (enLigne() ? "Envoi du brouillon…" : "Brouillon gardé sur cet appareil : il partira au retour de la connexion.")
        : composeur.sale ? "Modifications pas encore enregistrées (gardées sur cet appareil)."
          : composeur.id ? "Brouillon enregistré" + (composeur.maj ? " " + depuis(composeur.maj) : "") + "." : "Nouveau brouillon.";
    statut.classList.toggle("alerte", !!conf);
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

  async function enregistrer(silencieux) {
    if (composeur.publie) return modifierPublie();
    const v = composeur.v;
    const corps = { type: v.type };
    for (const k of CHAMPS[v.type]) corps[k] = v[k];
    if (!corps.reponses) corps.places = 0;
    if (composeur.id) { corps.id = composeur.id; corps.version = composeur.version; }
    else { composeur.cle_client = composeur.cle_client || uuid(); corps.cle_client = composeur.cle_client; }
    const cle = composeur.id ? String(composeur.id) : composeur.cle_client;
    const objet = { id: composeur.id || undefined, cle_client: composeur.cle_client || undefined, _cle: cle, type: v.type, statut: "brouillon", titre: v.titre, quand: v.quand,
      destination: v.destination, valeurs: Object.assign({}, v), version: composeur.version || 0, maj: maintenant() };
    await mettreEnFile("clan/brouillon", corps, { genre: "brouillon", cle, resume: "Brouillon « " + (v.titre || LIB_TYPE[v.type]) + " »", objet });
    composeur.sale = false;
    garderLocal();
    majStatut();
    if (!silencieux) toast(enLigne() ? "Brouillon enregistré." : "Brouillon gardé sur l'appareil : il partira au retour de la connexion.", "succes");
    emettre("jeu", { nom: "evenements" });
  }
  // Le serveur répond : on récupère l'identifiant et la version du brouillon.
  const stopSucces = ecouter("file:succes", ({ op, objet }) => {
    if (op.genre !== "brouillon" || !objet) return;
    if (op.cle === composeur.cle_client || (composeur.id && String(objet.id) === String(composeur.id))) {
      composeur.id = objet.id; composeur.version = objet.version; composeur.maj = objet.maj || maintenant();
      garderLocal(); majStatut(); apercuServeur();
    }
  });
  const stopFile = ecouter("file", majStatut);

  async function publier() {
    const v = composeur.v;
    if (!v.titre.trim()) { toast("Donne un titre avant de publier.", "erreur"); return; }
    if (composeur.sale || !composeur.id) await enregistrer(true);
    const att = await attendreEnregistrement();
    if (!att) { toast("Le brouillon n'a pas encore pu être enregistré sur le serveur : réessaie quand la connexion revient.", "erreur"); return; }
    const ap = await lire("clan/apercu", { id: composeur.id });
    const dest = (E.destinations || []).find((d) => String(d.id) === String(v.destination));
    const erreurs = (ap.ok && ap.donnees && ap.donnees.erreurs) || [];
    const avert = (ap.ok && ap.donnees && ap.donnees.avertissements) || [];
    if (erreurs.length) { toast("À corriger avant de publier : " + erreurs.join(" · "), "erreur"); majApercu(true); return; }
    const ok = await confirmer({
      titre: "Publier « " + (v.titre || LIB_TYPE[v.type]) + " » ?", icone: "cloche", libelleOk: "Publier", taille: "etroite",
      texte: "Dans « " + (dest ? sansEmoji(dest.nom) : "le salon Info") + " »" + (v.mention === "clan" ? ", en mentionnant le clan" : v.mention === "inscrits" ? ", en mentionnant les inscrits" : ", sans mention") + "."
        + (v.type === "evenement" ? " Minuteur et rappels démarrent tout de suite." + (v.discord_event ? " L'évènement Discord est créé aussi." : "") : ""),
      contenu: avert.length ? [bandeau(avert.join(" · "), "")] : null,
    });
    if (!ok) return;
    await envoyerPublication(false);
  }
  async function envoyerPublication(forcer) {
    const r = await poster("clan/publier", { id: composeur.id, version: composeur.version, forcer: forcer || undefined });
    const d = r.donnees || {};
    if (r.ok && d.ok !== false && !d.incertain) {
      toast("Publié sur Discord.", "succes");
      if (d.lien) toast("Le message : " + d.lien, "succes");
      nouveau(true);
      perime("evenements");
      emettre("recharger");
      aller("equipage", "annonces", "a-venir");
      return;
    }
    if (d.incertain || r.status === 409 && /incertain/i.test(d.erreur || "")) {
      const p = pancarte({ titre: "Publication incertaine", icone: "attention", taille: "etroite" });
      ajouter(p.corps, [h("p", {}, "Discord n'a pas confirmé la publication : le message est peut-être parti. Vérifie d'abord dans le salon ; s'il n'y est pas, force la publication.")]);
      ajouter(p.pied, [bouton("Vérifier", { classe: "discret", icone: "oeil", onclick: async () => { p.fermer(); perime("evenements"); await charger("evenements", { forcer: true }); aller("equipage", "annonces", "a-venir"); } }),
        bouton("Forcer la publication", { classe: "principal", reseau: true, onclick: async () => { p.fermer(); await envoyerPublication(true); } })]);
      return;
    }
    toast(r.status === 502 ? "Discord a refusé la publication : " + (d.erreur || "réessaie dans un instant.") : (d.erreur || r.erreur || "Publication impossible.") + ((d.erreurs || []).length ? " — " + d.erreurs.join(" · ") : ""), "erreur");
  }
  async function attendreEnregistrement() {
    for (let i = 0; i < 40; i++) {
      const cle = composeur.id ? String(composeur.id) : composeur.cle_client;
      const restantes = opsDe("brouillon", cle).concat(composeur.cle_client ? opsDe("brouillon", composeur.cle_client) : []);
      if (composeur.id && !restantes.length) return true;
      if (restantes.some((o) => o.etat !== "attente")) return false;
      if (!enLigne()) return false;
      await new Promise((ok) => setTimeout(ok, 250));
    }
    return false;
  }
  async function modifierPublie(actualiser) {
    const v = composeur.v;
    const corps = { id: composeur.id, version: composeur.version };
    if (!actualiser) for (const k of CHAMPS[v.type]) corps[k] = v[k];
    const r = await poster("clan/modifier", corps);
    const d = r.donnees || {};
    if (r.ok && d.ok !== false) {
      toast(actualiser ? "Carte actualisée sur Discord." : "Modifications enregistrées sur Discord.", "succes");
      if (d.element) { composeur.version = d.element.version; }
      composeur.sale = false; garderLocal(); majStatut(); perime("evenements"); emettre("recharger");
      return;
    }
    if (r.status === 409 && d.actuelle) {
      toast("Cet élément a changé ailleurs : la version enregistrée est rechargée.", "erreur");
      chargerElement(d.actuelle);
      return;
    }
    toast(d.erreur || r.erreur || "Modification impossible.", "erreur");
  }

  function nouveau(silencieux) {
    composeur = { v: valeursNeuves(E, composeur ? composeur.v.type : "evenement"), id: null, version: null, cle_client: null, publie: false, sale: false };
    oublierSaisie("composeur");
    apercuDistant = null;
    construire();
    majApercu(false);
    majStatut();
    if (!silencieux) toast("Nouveau brouillon.", "succes");
  }
  function chargerElement(el) {
    const f = aplatir(el);
    composeur = { v: Object.assign(valeursNeuves(E, f.type || "evenement"), f), id: el.id || null, version: el.version ?? null, cle_client: el.cle_client || null,
      publie: !!el.statut && el.statut !== "brouillon", sale: false, maj: el.maj };
    garderLocal();
    apercuDistant = null;
    construire();
    majApercu(true);
    majStatut();
  }
  composeurOuvrir = (el) => { chargerElement(el); };

  async function majApercu(serveur) {
    const v = composeur.v;
    if (serveur && composeur.id && enLigne() && !composeur.sale) {
      const r = await lire("clan/apercu", { id: composeur.id });
      if (r.ok && r.donnees && Array.isArray(r.donnees.cartes)) apercuDistant = r.donnees;
    }
    const local = apercuLocal(v, E);
    const d = apercuDistant && !composeur.sale ? apercuDistant : local;
    remplacer(apercuZone, apercuDiscord(d, { local: d === local, type: v.type, v }));
  }
  ecouter("reseau", () => { if (apercuZone.isConnected) { majActions(); majApercu(true); } });

  construire();
  majApercu(true);
  majStatut();
  return {
    majDonnees(nE) { E = nE; },
    quitter() { stopSucces(); stopFile(); },
  };
}
let composeurOuvrir = null;
/** Ouvre un élément (brouillon ou publié) dans le composeur. */
function ouvrirDansComposeur(el) {
  composeur = null;
  const f = aplatir(el);
  composeur = { v: Object.assign({}, f), id: el.id || null, version: el.version ?? null, cle_client: el.cle_client || null, publie: !!el.statut && el.statut !== "brouillon", sale: false, maj: el.maj };
  garderSaisie("composeur", composeur);
  aller("equipage", "annonces", "composer");
  if (composeurOuvrir && etat.route.sous === "composer") composeurOuvrir(el);
}

// Les blocs du formulaire
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
  const d = new Date((v.quand || maintenant()) * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  const jour = h("input", { type: "date", value: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, classe: "saisie" });
  const hh = h("input", { type: "time", value: `${pad(d.getHours())}:${pad(d.getMinutes())}`, classe: "saisie", step: 300 });
  const minuteur = h("p", { classe: "minuteur-vivant" });
  const majQuand = () => {
    const [a, m, j] = jour.value.split("-").map(Number), [H, M] = (hh.value || "00:00").split(":").map(Number);
    if (!a || !m || !j) return;
    const t = Math.floor(new Date(a, m - 1, j, H || 0, M || 0).getTime() / 1000);
    changer("quand", t, true);
    majMinuteur();
  };
  const majMinuteur = () => {
    const t = composeur.v.quand;
    remplacer(minuteur, icone("minuteur"), t ? h("span", {}, majuscule(dateLongue(t)), " · ", h("b", {}, t > maintenant() ? dans(t) : "date passée")) : "Choisis une date");
    minuteur.classList.toggle("alerte", !!t && t < maintenant());
  };
  jour.addEventListener("change", majQuand);
  hh.addEventListener("change", majQuand);
  majMinuteur();
  const tic = setInterval(() => { if (!minuteur.isConnected) clearInterval(tic); else majMinuteur(); }, 30000);
  const duree = liste({ valeur: [30, 60, 90, 120, 180, 240].includes(v.duree_min) ? v.duree_min : 60, label: "Durée", plein: true,
    options: [30, 60, 90, 120, 180, 240].map((m) => ({ v: m, l: dureeMinutes(m) })), changer: (x) => changer("duree_min", Number(x), true) });
  const lieu = saisie({ value: v.lieu || "", maxlength: 100, placeholder: "Port de l'île centrale", list: "lieux-suggeres" });
  lieu.addEventListener("input", () => changer("lieu", lieu.value, true));
  const suggestions = (E.lieux || []).slice(0, 8);
  const rappelsZone = h("div", { classe: "puces" });
  const majRappels = () => {
    const actifs = new Set(composeur.v.rappels || []);
    remplacer(rappelsZone, ...[...new Set([...RAPPELS, ...(E.rappels_suggeres || []), ...actifs])].sort((a, b) => b - a).map((m) => h("button", {
      classe: "puce", type: "button", "aria-pressed": String(actifs.has(m)),
      onclick: () => {
        const l = new Set(composeur.v.rappels || []);
        if (l.has(m)) l.delete(m); else if (l.size >= 5) { toast("5 rappels au plus.", "erreur"); return; } else l.add(m);
        changer("rappels", [...l].sort((a, b) => b - a), true);
        majRappels();
      },
    }, h("span", { classe: "puce-lib" }, libRappel(m) + " avant"))));
  };
  majRappels();
  const places = h("input", { type: "number", min: 0, max: 500, step: 1, value: v.places || 0, classe: "saisie", disabled: !v.reponses || null });
  places.addEventListener("input", () => changer("places", Math.max(0, Math.min(500, Number(places.value) || 0)), true));
  const droits = E.droits || {};
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "L'événement"),
    h("div", { classe: "champs" }, champ("Le jour", jour), champ("L'heure", hh), duree),
    minuteur,
    champ("Lieu", lieu, { optionnel: true }),
    suggestions.length ? h("div", { classe: "puces" }, suggestions.map((s) => h("button", { classe: "puce", type: "button", onclick: () => { lieu.value = s; changer("lieu", s, true); } }, h("span", { classe: "puce-lib" }, sansEmoji(s))))) : null,
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Rappels sur Discord (5 au plus)"), rappelsZone),
    interrupteur("Boutons de réponse « Dispo · Peut-être · Pas dispo »", v.reponses, (x) => { changer("reponses", x, true); places.disabled = !x; if (!x) { places.value = 0; changer("places", 0, true); } }),
    champ("Places", places, { aide: "0 = illimité. Au-delà, les suivants passent en liste d'attente." }),
    interrupteur("Réservé au clan (seuls les membres du clan peuvent répondre)", v.reserve_clan, (x) => changer("reserve_clan", x, true)),
    interrupteur("Créer aussi l'évènement Discord programmé", v.discord_event && droits.discord_event !== false, (x) => changer("discord_event", x, true),
      { disabled: droits.discord_event === false, titre: droits.discord_event === false ? "Le bot n'a pas la permission de créer des évènements sur ce serveur." : "" }),
    droits.discord_event === false ? h("p", { classe: "aide" }, "Le bot n'a pas la permission « Gérer les évènements » : l'évènement Discord ne peut pas être créé.") : null);
}
function blocGroupement(v, changer) {
  const champs = new Set(v.champs || []);
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, v.type === "metiers" ? "Les métiers" : "Le listing"),
    h("p", { classe: "aide" }, v.type === "metiers" ? "Chaque membre avec son métier officiel, tiré de son affiche (Capitainerie)." : "Tout l'équipage, rangé comme tu veux, avec ce que tu choisis de montrer."),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Ranger par"), segment(v.groupement || "metier", [["metier", "Métier"], ["grade", "Grade"], ["race", "Race"]], (x) => changer("groupement", x, true), "Ranger par")),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Montrer pour chacun"),
      h("div", { classe: "rangee" }, [["metiers", "Métiers"], ["grade", "Grade"], ["race", "Race"]].map(([k, l]) => caseACocher(l, champs.has(k), (x) => {
        if (x) champs.add(k); else champs.delete(k);
        changer("champs", [...champs], true);
      })))));
}
function blocApparence(v, changer, E) {
  const palette = [...new Set([...(E.couleurs || []), ...COULEURS])].filter((c) => /^#[0-9a-fA-F]{6}$/.test(c)).slice(0, 10);
  const nuancier = h("div", { classe: "nuancier", role: "radiogroup", "aria-label": "Couleur de la carte" });
  const majNuancier = () => remplacer(nuancier, ...palette.map((c) => h("button", { classe: "nuance", type: "button", role: "radio", "aria-checked": String(composeur.v.couleur === c), "aria-label": "Couleur " + c, title: c,
    vars: { "--teinte": c }, onclick: () => { changer("couleur", c, true); majNuancier(); } })));
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
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Image"), image));
}
function blocEnvoi(v, changer, E) {
  const dests = E.destinations || [];
  const destination = liste({ valeur: v.destination, label: "Où publier", plein: true, options: dests.map((d) => ({ v: String(d.id), l: sansEmoji(d.nom) || "Salon", sous: d.defaut ? "par défaut" : "" })), changer: (x) => changer("destination", x, true) });
  const mentions = [["aucune", "Aucune mention"], ["clan", "Le clan" + (E.droits && E.droits.role_clan_nom ? " (" + sansEmoji(E.droits.role_clan_nom) + ")" : "")]];
  if (v.type === "evenement") mentions.push(["inscrits", "Les inscrits (aux rappels)"]);
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "L'envoi"),
    destination, radios("mention-" + v.type, mentions, v.mention, (x) => changer("mention", x, true), "Mention"));
}
async function choisirImage(fin) {
  const entree = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" });
  entree.addEventListener("change", async () => {
    const f = entree.files && entree.files[0];
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) { toast("8 Mo au plus.", "erreur"); return; }
    const b64 = await new Promise((ok, ko) => { const lec = new FileReader(); lec.onload = () => ok(String(lec.result).split(",")[1] || ""); lec.onerror = ko; lec.readAsDataURL(f); });
    toast("Envoi de l'image…");
    const r = await poster("media", { nom: f.name.slice(0, 80), type: f.type, base64: b64 });
    if (r.ok && r.donnees && r.donnees.id) { fin(r.donnees.id); toast("Image ajoutée.", "succes"); }
    else toast(r.erreur || "Image refusée.", "erreur");
  });
  entree.click();
}

// ─── L'aperçu Discord (fidèle) ─────────────────────────────────────────────
/** Un aperçu local, de même forme que celui du serveur (cartes → blocs). */
function apercuLocal(v, E) {
  const blocs = [];
  const lignes = [];
  if (v.titre) lignes.push({ md: v.titre, niveau: 2 });
  if (v.texte) for (const l of v.texte.split("\n")) lignes.push({ md: l, niveau: 0 });
  if (lignes.length) blocs.push({ type: "texte", lignes });
  if (v.type === "evenement" && v.quand) {
    const q = Math.floor(v.quand);
    const l = [{ md: "**Quand · When** <t:" + q + ":F> (<t:" + q + ":R>)", icone: "minuteur" }];
    if (v.lieu) l.push({ md: "**Lieu · Where** " + v.lieu, icone: "lieu" });
    if (v.duree_min) l.push({ md: "**Durée · Duration** " + dureeMinutes(v.duree_min), icone: "calendrier" });
    if (v.reponses && v.places) l.push({ md: "**Places · Spots** 0 / " + v.places, icone: "membres" });
    blocs.push({ type: "separateur" }, { type: "texte", lignes: l });
  }
  if (v.type === "metiers" || v.type === "listing") {
    blocs.push({ type: "separateur" }, { type: "texte", lignes: [{ md: "La liste se remplit à partir des affiches de l'équipage au moment de publier.", niveau: "petit" }] });
  }
  if (v.image) blocs.push({ type: "image", media: v.image, url: "media/" + v.image });
  if (v.type === "evenement" && v.reponses) blocs.push({ type: "boutons", boutons: [{ label: "Dispo · Available", style: "success", icone: "valider" }, { label: "Peut-être · Maybe", style: "secondary", icone: "peut_etre" }, { label: "Pas dispo · Unavailable", style: "danger", icone: "annuler" }] });
  const haut = v.mention === "clan" ? "<@&clan>" : v.mention === "inscrits" ? "Inscrits · Registered" : "";
  return { cartes: [{ haut, couleur: v.couleur, blocs }], roles: { clan: (E.droits && E.droits.role_clan_nom) || "Clan" }, personnes: {},
    rappels: v.type === "evenement" ? (v.rappels || []).map((m) => ({ minutes: m, quand: v.quand - m * 60, fait: false, passe: v.quand - m * 60 < maintenant() })) : [] };
}

function apercuDiscord(d, o) {
  const cartes = (d && d.cartes) || [];
  const ctx = { personnes: d.personnes || {}, roles: d.roles || {}, salons: d.salons || {} };
  const n = cartes.reduce((a, c) => a + (c.caracteres || 0), 0);
  const tete = h("div", { classe: "apercu-tete" }, icone("discord"), h("b", {}, "Aperçu Discord"),
    h("span", { classe: "meta" }, o.local ? "aperçu sur l'appareil" : "rendu du serveur" + (n ? " · " + nombre(n) + " caractères" : "") + (cartes.length > 1 ? " · " + cartes.length + " messages" : "")));
  const corps = h("div", { classe: "discord", role: "img", "aria-label": "Aperçu du message tel qu'il apparaîtra sur Discord" },
    h("div", { classe: "discord-auteur" }, h("span", { classe: "discord-av" }, "G"), h("b", {}, "GoRP"), h("span", { classe: "discord-app" }, "APP"), h("span", { classe: "discord-quand" }, "Aujourd'hui à " + heure(maintenant()))),
    cartes.length ? cartes.map((c) => carteDiscord(c, ctx)) : h("p", { classe: "discord-vide" }, "Le message apparaîtra ici."));
  const notes = [];
  if ((d.erreurs || []).length) notes.push(bandeau(h("span", {}, h("b", {}, "À corriger : "), d.erreurs.join(" · ")), "rouge"));
  if ((d.avertissements || []).length) notes.push(bandeau(d.avertissements.join(" · "), ""));
  const rappels = (d.rappels || []).length ? h("div", { classe: "rappels-ligne" }, h("span", { classe: "champ-lib" }, "Rappels"), h("ul", { classe: "rappels" }, d.rappels.map((r) => h("li", { classe: r.fait ? "fait" : r.passe ? "passe" : "" },
    icone(r.fait ? "valider" : "cloche", "ic-p"), libRappel(r.minutes) + " avant", r.quand ? h("span", { classe: "meta" }, " · " + date(r.quand, true)) : null)))) : null;
  const de = d.discord_event && d.discord_event.demande ? h("p", { classe: "meta" }, icone("calendrier", "ic-p"), d.discord_event.permission === false ? " Évènement Discord : permission manquante." : d.discord_event.lien ? " Évènement Discord créé." : " L'évènement Discord sera créé à la publication.") : null;
  return h("div", { classe: "apercu-cadre" }, tete, corps, ...notes, rappels, de);
}
function carteDiscord(c, ctx) {
  const haut = c.haut ? h("div", { classe: "discord-haut" }, markdown(c.haut, ctx)) : null;
  const blocs = (c.blocs || []).map((b) => blocDiscord(b, ctx)).filter(Boolean);
  return h("div", { classe: "discord-message" }, haut, h("div", { classe: "discord-carte", vars: { "--accent": /^#[0-9a-fA-F]{6}$/.test(c.couleur || "") ? c.couleur : "#4f545c" } }, blocs));
}
function blocDiscord(b, ctx) {
  const t = b.type || (b.lignes ? "texte" : b.boutons ? "boutons" : b.url ? "image" : "");
  if (t === "separateur") return h("hr", { classe: "discord-sep" });
  if (t === "texte") return h("div", { classe: "discord-texte" }, (b.lignes || []).map((l) => {
    const niveau = l.niveau === 2 ? " h2" : l.niveau === 3 ? " h3" : l.niveau === "petit" ? " petit" : "";
    const jeu = l.jeu ? iconeJeu(l.jeu) : null;
    return h("div", { classe: "discord-ligne" + niveau }, l.icone ? icone(l.icone, "discord-emoji") : null, jeu, markdown(l.md || "", ctx));
  }));
  if (t === "image" || t === "bandeau") {
    const src = srcSure(b.url) || (b.media ? BASE + "/media/" + b.media : "");
    return src ? h("figure", { classe: "discord-media" + (t === "bandeau" ? " bandeau" : "") }, h("img", { src, alt: b.titre || "" })) : null;
  }
  if (t === "boutons") return h("div", { classe: "discord-boutons" }, (b.boutons || []).map((x) => h("span", { classe: "discord-bouton " + (x.url ? "lien" : x.style || "secondary") + (x.desactive ? " desactive" : "") },
    x.icone ? icone(x.icone, "discord-emoji") : null, x.label || "")));
  return null;
}
function iconeJeu(j) {
  const cat = vueJeu("catalogue");
  const e = cat && !cat.erreur ? elementCat(cat, j.type, j.cle) : null;
  const src = e && srcSure(e.icone);
  return src ? h("img", { classe: "discord-emoji", src, alt: "" }) : null;
}

/** Le Markdown de Discord, construit en nœuds (jamais d'HTML) : titres, gras, italique, souligné, barré, code,
 *  citations, listes, liens masqués, mentions (pastilles), horodatages <t:…:F|R|…>. */
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
  [/^\*\*(.+?)\*\*/, (m, c) => h("strong", {}, enLigne_(m[1], c))],
  [/^__(.+?)__/, (m, c) => h("u", {}, enLigne_(m[1], c))],
  [/^\*(?!\s)(.+?)\*/, (m, c) => h("em", {}, enLigne_(m[1], c))],
  [/^_(?!\s)(.+?)_(?!\w)/, (m, c) => h("em", {}, enLigne_(m[1], c))],
  [/^~~(.+?)~~/, (m, c) => h("s", {}, enLigne_(m[1], c))],
  [/^\|\|(.+?)\|\|/, (m, c) => h("span", { classe: "md-cache", title: "Texte caché" }, enLigne_(m[1], c))],
  [/^`([^`]+)`/, (m) => h("code", {}, m[1])],
  [/^\[([^\]]+)\]\((https:\/\/[^\s)]+)\)/, (m, c) => h("a", { href: m[2] }, enLigne_(m[1], c))],
  [/^<t:(-?\d+)(?::([tTdDfFR]))?>/, (m) => h("span", { classe: "md-heure", title: date(Number(m[1]), true) }, horodatage(Number(m[1]), m[2] || "f"))],
  [/^<@&(\w+)>/, (m, c) => h("span", { classe: "md-mention" }, "@" + sansEmoji((c.roles || {})[m[1]] || "rôle"))],
  [/^<@!?(\d+)>/, (m, c) => h("span", { classe: "md-mention" }, "@" + sansEmoji((c.personnes || {})[m[1]] || "membre"))],
  [/^<#(\d+)>/, (m, c) => h("span", { classe: "md-mention" }, "#" + sansEmoji((c.salons || {})[m[1]] || "salon"))],
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
function horodatage(t, f) {
  const d = new Date(t * 1000);
  const o = { t: { hour: "2-digit", minute: "2-digit" }, T: { hour: "2-digit", minute: "2-digit", second: "2-digit" }, d: { day: "2-digit", month: "2-digit", year: "numeric" },
    D: { day: "numeric", month: "long", year: "numeric" }, f: { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" },
    F: { weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" } }[f];
  if (f === "R") return dans(t).replace(/^date inconnue$/, "") || depuis(t);
  return new Intl.DateTimeFormat("fr-FR", Object.assign({ timeZone: "Europe/Paris" }, o || {})).format(d);
}

// ─── Les listes ─────────────────────────────────────────────────────────────
function enAttenteDe(el) {
  const ops = opsDe("brouillon", el.id ? String(el.id) : el.cle_client || el._cle).concat(el.cle_client ? opsDe("brouillon", el.cle_client) : []);
  return ops.length ? ops[ops.length - 1].etat : el._attente || "";
}
function carteElement(el, actions) {
  const f = aplatir(el);
  const [lib, coul] = STATUTS[el.statut] || [el.statut || "", "encre"];
  const att = enAttenteDe(el);
  const r = el.reponses || {};
  return h("article", { classe: "feuillet evt-carte" + (att ? " en-attente" : ""), vars: { "--accent": /^#[0-9a-fA-F]{6}$/.test(f.couleur || "") ? f.couleur : "#a8823f" } },
    h("div", { classe: "evt-tete" }, icone((TYPES.find((t) => t[0] === el.type) || TYPES[1])[2]), h("span", { classe: "champ-lib" }, LIB_TYPE[el.type] || el.type),
      el.statut && el.statut !== "brouillon" ? tampon(lib, coul, true) : null, att ? tampon(att === "conflit" ? "Conflit" : "En attente d'envoi", att === "conflit" ? "" : "ambre", true) : null),
    h("h3", { classe: "titre-carte" }, el.titre || f.titre || "Sans titre"),
    el.type === "evenement" && el.quand ? h("p", { classe: "minuteur-vivant" }, icone("minuteur"), h("span", {}, majuscule(dateLongue(el.quand)), " · ", h("b", {}, el.quand > maintenant() ? dans(el.quand) : el.phase === "en_cours" ? "en cours" : "passé"))) : null,
    f.texte ? h("p", { classe: "texte coupe2" }, f.texte) : null,
    el.type === "evenement" && el.statut && el.statut !== "brouillon" ? h("div", { classe: "reponses-evt" },
      pastille(nombre(r.disponibles || 0) + " dispo", "#3f6b3a"), pastille(nombre(r.peut_etre || 0) + " peut-être", "#a8641c"), pastille(nombre(r.pas_disponibles || 0) + " pas dispo", "#8e2a24"),
      f.places ? h("span", { classe: "meta" }, nombre(r.disponibles || 0) + " / " + f.places + " places") : null) : null,
    el.type !== "evenement" && r.vus ? h("p", { classe: "meta" }, "Vu par " + nombre(r.vus)) : null,
    el.note ? h("p", { classe: "aide" }, el.note) : null,
    h("p", { classe: "meta" }, el.statut === "brouillon" || !el.statut ? "Modifié " + depuis(el.maj || maintenant()) : el.publie ? "Publié " + depuis(el.publie) : ""),
    h("div", { classe: "feuillet-pied" }, actions));
}
function listeBrouillons(E, recharger) {
  const l = (E.brouillons || []).slice().sort((a, b) => (b.maj || 0) - (a.maj || 0));
  if (!l.length) return vide("Aucun brouillon", "Compose un événement ou une annonce : il est gardé ici jusqu'à sa publication.", "parchemin");
  return [h("p", { classe: "aide" }, "Les brouillons sont gardés sur le serveur — et sur cet appareil hors ligne, envoyés au retour."),
    paginer("evt-brouillons", l, (el) => carteElement(el, [
      bouton("Ouvrir", { classe: "p principal", icone: "plume", onclick: () => ouvrirDansComposeur(el) }),
      bouton("Dupliquer", { classe: "p", icone: "copier", onclick: () => dupliquer(el) }),
      bouton("Supprimer", { classe: "p discret danger", icone: "supprimer", onclick: async () => {
        const ok = await confirmer({ titre: "Supprimer ce brouillon ?", texte: "« " + (el.titre || "Sans titre") + " » disparaît. Rien n'a été publié.", libelleOk: "Supprimer", style: "danger" });
        if (!ok) return;
        const corps = el.id ? { id: el.id, version: el.version } : { cle_client: el.cle_client };
        await mettreEnFile("clan/supprimer_brouillon", corps, { genre: "brouillon", cle: el.id ? String(el.id) : el.cle_client || el._cle, resume: "Suppression du brouillon « " + (el.titre || "Sans titre") + " »", retrait: true });
        recharger();
      } }),
    ]))];
}
function dupliquer(el) {
  const f = aplatir(el);
  delete f.id; delete f.version; delete f.cle_client; delete f.statut;
  composeur = { v: Object.assign({}, f, { titre: (f.titre || "") + " (copie)" }), id: null, version: null, cle_client: null, publie: false, sale: true };
  garderSaisie("composeur", composeur);
  aller("equipage", "annonces", "composer");
  toast("Copie ouverte dans le composeur.", "succes");
}
function listeAVenir(E, recharger) {
  const l = (E.a_venir || []).slice().sort((a, b) => (a.quand || a.publie || 0) - (b.quand || b.publie || 0));
  if (!l.length) return vide("Rien à venir", "Les événements publiés et les annonces récentes apparaîtront ici, avec leur minuteur et les réponses.", "minuteur");
  return [paginer("evt-avenir", l, (el) => carteElement(el, [
    el.lien ? h("a", { classe: "bouton p", href: el.lien }, icone("discord"), h("span", {}, "Sur Discord")) : null,
    el.discord_event && el.discord_event.lien ? h("a", { classe: "bouton p discret", href: el.discord_event.lien }, icone("calendrier"), h("span", {}, "Évènement Discord")) : null,
    el.statut === "incertain" ? bouton("Vérifier", { classe: "p", icone: "oeil", onclick: recharger }) : null,
    el.statut === "incertain" ? bouton("Forcer la publication", { classe: "p principal", reseau: true, onclick: async () => {
      const r = await poster("clan/publier", { id: el.id, version: el.version, forcer: true });
      toast(r.ok ? "Publication forcée." : r.erreur, r.ok ? "succes" : "erreur"); recharger();
    } }) : null,
    bouton("Modifier", { classe: "p", icone: "plume", onclick: () => ouvrirDansComposeur(el) }),
    bouton("Actualiser la carte", { classe: "p discret", icone: "synchro", reseau: true, onclick: async () => {
      const r = await poster("clan/modifier", { id: el.id, version: el.version });
      toast(r.ok ? "Carte actualisée sur Discord." : r.erreur, r.ok ? "succes" : "erreur"); recharger();
    } }),
    bouton(el.type === "evenement" ? "Annuler l'événement" : "Retirer", { classe: "p danger", reseau: true, onclick: async () => {
      let prevenir = el.type === "evenement";
      const ok = await confirmer({
        titre: el.type === "evenement" ? "Annuler « " + el.titre + " » ?" : "Retirer « " + el.titre + " » ?", style: "danger", libelleOk: el.type === "evenement" ? "Annuler l'événement" : "Retirer",
        texte: el.type === "evenement" ? "La carte l'indique sur Discord, les rappels s'arrêtent" + (el.discord_event ? " et l'évènement Discord est annulé" : "") + "." : "La carte est retirée du salon.",
        contenu: el.type === "evenement" ? [caseACocher("Prévenir ceux qui ont répondu", true, (x) => { prevenir = x; })] : null,
      });
      if (!ok) return;
      const r = await poster("clan/annuler", { id: el.id, prevenir });
      toast(r.ok ? (r.donnees.deja ? "C'était déjà fait." : el.type === "evenement" ? "Événement annulé." : "Retiré.") : r.erreur, r.ok ? "succes" : "erreur");
      recharger();
    } }),
  ]), { pas: 12 })];
}
function listePasses(E) {
  const l = (E.passes || []).slice().sort((a, b) => (b.quand || b.publie || 0) - (a.quand || a.publie || 0));
  if (!l.length) return vide("Rien de passé pour l'instant", "Les événements terminés, annulés ou retirés restent ici (60 jours, rubrique Nettoyage).", "coffre");
  return [E.passes_total && E.passes_total > l.length ? h("p", { classe: "aide" }, "Les " + l.length + " plus récents sur " + nombre(E.passes_total) + ".") : null,
    paginer("evt-passes", l, (el) => carteElement(el, [
      el.lien ? h("a", { classe: "bouton p discret", href: el.lien }, icone("discord"), h("span", {}, "Sur Discord")) : null,
      bouton("Refaire à partir de celui-ci", { classe: "p", icone: "copier", onclick: () => dupliquer(el) }),
    ]), { pas: 12 })];
}
