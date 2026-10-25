// app.js — la Capitainerie démarre ici : routes, pancartes, plaque d'état, file d'envoi, mises à jour,
// service worker (hors ligne), session et déconnexion.

import { h, icone, $, BASE, chargerSprite, completerSprite, icones, depuis, date, nombre, sansEmoji, srcSure, retarder, reduit, telephone, remplacer, quantite, ajouter } from "./dom.js";
import { V, CATEGORIES, categorie, rubrique, etat, emettre, ecouter, lireAncre, poserAncre, aller, peutAgir, enLigne, retenirPersonnes, oublierPrefs, P } from "./noyau.js";
import { lire, poster, noterReseau } from "./api.js";
import * as HL from "./hors_ligne.js";
import { oublierTout, perime, vue as vueJeu } from "./donnees.js";
import { bouton, boutonIcone, menu, pancarte, confirmer, toast, titreRubrique, vide, bandeau, majBoutonsReseau, pancartesOuvertes, chargement, nomDe, compteur } from "./ui.js";
import { ouvrirFiche } from "./fiche.js";
import { monogramme } from "./affiche.js";
import * as port from "./discord.js";
import * as clan from "./clan.js";
import * as recrutement from "./recrutement.js";
import * as annonces from "./annonces.js";
import * as cap from "./capitainerie.js";

const RAFRAICHIR = 60000;
const ICONES = ["port", "equipage", "capitainerie", "apercu", "journal", "sanctions", "tickets", "repertoire", "salons", "nettoyage", "membres", "fiches",
  "candidatures", "annonces", "evenements", "affiches", "catalogue", "roles", "ajouter", "modifier", "supprimer", "fermer", "valider", "annuler", "rechercher",
  "filtrer", "exporter", "copier", "lien", "ouvrir", "plus", "moins", "gauche", "droite", "haut", "bas", "menu", "deconnexion", "en_ligne", "hors_ligne",
  "synchro", "attention", "info", "succes", "erreur", "minuteur", "calendrier", "lieu", "prime", "drapeau", "navire", "ancre", "boussole", "longue_vue",
  "cloche", "parchemin", "plume", "cadenas", "cle", "coffre", "sabre", "canon", "carte", "etoile", "oeil", "personne", "discord", "roblox", "peut_etre"];

const RENDUS = {
  "port/apercu": port.apercu, "port/journal": port.journal, "port/sanctions": port.sanctions, "port/tickets": port.tickets,
  "port/repertoire": port.repertoire, "port/salons": port.salons, "port/nettoyage": port.nettoyage,
  "equipage/membres": clan.membres, "equipage/fiches": clan.fiches, "equipage/candidatures": recrutement.candidatures,
  "equipage/tickets": clan.tickets, "equipage/annonces": annonces.annonces,
  "capitainerie/affiches": cap.affiches, "capitainerie/catalogue": cap.catalogue, "capitainerie/roles": cap.roles,
};
// Ces rubriques n'ont pas besoin des grandes données du serveur pour s'afficher.
const AUTONOMES = new Set(["port/nettoyage", "capitainerie/affiches", "capitainerie/catalogue", "capitainerie/roles", "equipage/annonces"]);

let courante = null;
const plaque = h("button", { classe: "plaque-etat", type: "button", id: "plaque-etat", "aria-live": "polite", title: "État de la connexion et des envois" });

// Filet de sécurité : une image qui ne se charge pas et que personne n'a remplacée (icône, logo, aperçu, pièce
// jointe…) ne reste jamais cassée : une plaque « image » de même taille prend sa place. Les composants qui ont
// leur propre repli (pastille gravée, initiales) l'ont déjà posé : l'image n'est alors plus dans la page.
document.addEventListener("error", (ev) => {
  const img = ev.target;
  if (!(img instanceof HTMLImageElement)) return;
  setTimeout(() => {
    if (!img.isConnected) return;
    img.replaceWith(h("span", { classe: ("image-absente " + img.className).trim(), role: img.alt ? "img" : null, "aria-label": img.alt || null,
      "aria-hidden": img.alt ? null : "true" }, icone("image")));
  }, 0);
}, true);

// ─── Démarrage ──────────────────────────────────────────────────────────────
async function demarrer() {
  await canoniser();
  enregistrerServiceWorker();
  await Promise.race([chargerSprite(BASE + "/s/icones/ui.svg?v=" + V), new Promise((ok) => setTimeout(ok, 2500))]);
  completerSprite(ICONES);
  await HL.ouvrir();
  monterEntete();
  monterPancartes();
  lireRoute(true);
  document.body.classList.remove("demarrage");
  await chargerDonnees();
  rendre(true);
  const a = lireAncre();
  if (a.membre) ouvrirFiche(a.membre);
  planifier();
  setInterval(() => { if (HL.enAttente().length && enLigne() && !document.hidden) HL.envoyer(); }, 30000);
  setInterval(majPlaque, 20000);
  setInterval(verifierVersion, 15000);
  if (HL.enAttente().length) HL.envoyer();
}

/** La page doit être sous /tableau/espace/ pour que le service worker la garde hors ligne. */
async function canoniser() {
  if (location.pathname !== BASE || !("serviceWorker" in navigator)) return;
  try {
    const r = await fetch(BASE + "/", { credentials: "same-origin", cache: "no-store" });
    if (r.ok && (r.headers.get("Content-Type") || "").includes("text/html")) history.replaceState(null, "", BASE + "/" + location.hash);
  } catch (e) { /* on reste où l'on est */ }
}

function enregistrerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register(BASE + "/sw.js?v=" + encodeURIComponent(V), { scope: BASE + "/", updateViaCache: "none" })
    .then(() => navigator.serviceWorker.ready)
    .then((reg) => setTimeout(() => {
      // Tout ce que la page a chargé (polices, textures, icônes) reste disponible hors ligne.
      const urls = performance.getEntriesByType("resource").map((e) => e.name).filter((u) => u.startsWith(location.origin + BASE + "/s/"));
      if (reg.active) reg.active.postMessage({ type: "precacher", urls });
    }, 1500))
    .catch(() => { /* sans service worker : le site marche, sans la coquille hors ligne */ });
}

// ─── En-tête ────────────────────────────────────────────────────────────────
function monterEntete() {
  const outils = $("#entete-outils");
  const rafraichir = boutonIcone("synchro", "Mettre à jour maintenant", () => { chargerDonnees(true); if (HL.enAttente().length) HL.envoyer(); }, "sur-bois");
  const menuB = menu(boutonIcone("menu", "Menu du capitaine", null, "sur-bois"), () => [
    { titre: "Session" },
    { l: "File d'envoi", sous: HL.file.ops.length ? quantite(HL.file.ops.length, "modification(s) en attente") : "rien en attente", icone: "synchro", onclick: ouvrirFile },
    { l: "Exporter le journal (30 jours)", icone: "exporter", href: BASE + "/export?quoi=journal&jours=30", telecharger: true, desactive: !enLigne() },
    { l: "Exporter le casier", icone: "exporter", href: BASE + "/export?quoi=sanctions", telecharger: true, desactive: !enLigne() },
    "-",
    { l: "Fermer toutes mes sessions", icone: "cadenas", onclick: fermerPartout, desactive: !enLigne() },
    { l: "Se déconnecter", icone: "deconnexion", onclick: deconnecter, danger: true },
  ]);
  plaque.addEventListener("click", ouvrirFile);
  remplacer(outils, plaque, rafraichir, menuB);
  majPlaque();
}

function majMarque() {
  const d = etat.d;
  if (!d || !d.serveur) return;
  const nom = sansEmoji(d.serveur.nom) || "La Capitainerie";
  $("#nom-serveur").textContent = nom;
  document.title = "La Capitainerie · " + nom;
  const logo = $("#logo-serveur");
  const src = srcSure(d.serveur.icone);
  if (src && !logo.querySelector("img")) {
    const img = h("img", { src, alt: "", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => { remplacer(logo, nom.slice(0, 1)); }, { once: true });
    remplacer(logo, img);
  } else if (!src && !logo.textContent) logo.textContent = nom.slice(0, 1);
  // Le logo officiel de RELL Seas : celui que donne le serveur, sinon l'icône du jeu de site/logos/ ;
  // s'il manque, une pastille gravée « R » (jamais une image cassée).
  const jeu = $("#logo-jeu");
  const srcJeu = srcSure(d.serveur.logo_jeu || d.serveur.logo_rell || "logos/rellseas_jeu.webp");
  if (srcJeu && jeu.dataset.src !== srcJeu) {
    jeu.dataset.src = srcJeu;
    const img = h("img", { src: srcJeu, alt: "RELL Seas" });
    img.addEventListener("load", () => { jeu.hidden = false; }, { once: true });
    img.addEventListener("error", () => { remplacer(jeu, monogramme("RELL Seas", "medaillon-repli")); jeu.hidden = false; }, { once: true });
    remplacer(jeu, img);
  }
}

function majPlaque() {
  const att = HL.enAttente().length, conf = HL.enConflit().length, refus = HL.enRefus().length;
  let classe = "", ic = "en_ligne", texte;
  if (etat.session !== "ok") { classe = "session"; ic = "cadenas"; texte = att ? "Session terminée · " + att + " en attente" : "Session terminée"; }
  else if (conf) { classe = "conflit"; ic = "attention"; texte = conf + " conflit" + (conf > 1 ? "s" : "") + " à régler"; }
  else if (HL.file.enCours) { classe = "envoi"; ic = "synchro"; texte = "Envoi…"; }
  else if (!etat.reseau.enLigne) {
    classe = "hors-ligne"; ic = "hors_ligne";
    texte = att ? "Hors ligne — " + att + " modification" + (att > 1 ? "s" : "") + " en attente" : "Hors ligne" + (etat.ageCache ? " · données d'il y a " + ageTexte(etat.ageCache) : "");
  } else if (att) { classe = "envoi"; ic = "synchro"; texte = att + " modification" + (att > 1 ? "s" : "") + " à envoyer"; }
  else if (refus) { classe = "conflit"; ic = "attention"; texte = refus + " refus à voir"; }
  else texte = "En ligne · à jour";
  plaque.className = "plaque-etat " + classe;
  const n = att + conf;
  remplacer(plaque, icone(ic), h("span", { classe: "plaque-texte" }, texte), n ? h("span", { classe: "plaque-nombre", "aria-hidden": "true" }, n > 99 ? "99+" : String(n)) : null);
  plaque.setAttribute("aria-label", texte + ". Ouvrir la file d'envoi.");
  const sous = $("#sous-titre");
  if (sous) {
    if (etat.session !== "ok") sous.textContent = "Session terminée";
    else if (!etat.dernier && !etat.d) sous.textContent = "Ouverture du livre de bord…";
    else if (!etat.reseau.enLigne && etat.ageCache) sous.textContent = "Livre de bord · données d'il y a " + ageTexte(etat.ageCache);
    else sous.textContent = "Livre de bord · à jour " + (Date.now() - etat.dernier < 20000 ? "à l'instant" : depuis(etat.dernier / 1000));
  }
}
const ageTexte = (ms) => { const m = Math.round(ms / 60000); return m < 60 ? Math.max(1, m) + " min" : m < 1440 ? Math.round(m / 60) + " h" : Math.round(m / 1440) + " j"; };

// ─── Les trois pancartes et les étiquettes des rubriques ────────────────────
function monterPancartes() {
  const nav = $("#pancartes");
  remplacer(nav, ...CATEGORIES.map((c) => h("a", { classe: "pancarte-nav", href: "#" + c.cle + "/" + c.rubriques[0].cle, "data-cat": c.cle },
    icone(c.icone), h("span", { classe: "pancarte-titre" }, c.titre), h("span", { classe: "pancarte-court", "aria-hidden": "true" }, c.court || c.titre),
    h("span", { classe: "pancarte-sous" }, c.sous), h("span", { classe: "pancarte-pastille", hidden: true }))));
  for (const a of nav.querySelectorAll("a")) a.addEventListener("click", (e) => {
    const cat = a.dataset.cat;
    if (cat === etat.route.cat) { e.preventDefault(); scrollTo({ top: 0, behavior: reduit.matches ? "auto" : "smooth" }); return; }
    const derniere = memoireRubrique[cat];
    if (derniere) { e.preventDefault(); aller(cat, derniere); }
  });
  const r = $("#rubriques");
  r.addEventListener("scroll", majFondus, { passive: true });
  addEventListener("resize", retarder(centrerEtiquette, 120));
}
const memoireRubrique = {};
function majRubriques() {
  const c = categorie(etat.route.cat);
  const r = $("#rubriques");
  remplacer(r, ...c.rubriques.map((x) => h("a", { classe: "etiquette", href: "#" + c.cle + "/" + x.cle, "aria-current": x.cle === etat.route.rub ? "page" : null, "data-rub": x.cle },
    icone(x.icone), h("span", {}, x.titre), h("span", { classe: "compteur", hidden: true }))));
  for (const a of $("#pancartes").querySelectorAll("a")) a.setAttribute("aria-current", a.dataset.cat === c.cle ? "page" : "false");
  majCompteurs();
  requestAnimationFrame(centrerEtiquette);
}
/** L'étiquette active bien visible (au centre si la rangée défile), mesurée une fois la page posée. */
function centrerEtiquette() {
  const r = $("#rubriques");
  const actif = r.querySelector('[aria-current="page"]');
  if (actif && r.clientWidth > 0 && r.scrollWidth > r.clientWidth) {
    const g = actif.offsetLeft, d = g + actif.offsetWidth;
    if (g < r.scrollLeft + 30 || d > r.scrollLeft + r.clientWidth - 30) r.scrollTo({ left: Math.max(0, g - (r.clientWidth - actif.offsetWidth) / 2), behavior: "auto" });
  } else if (r.scrollLeft && r.scrollWidth <= r.clientWidth) r.scrollLeft = 0;
  majFondus();
}
if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => requestAnimationFrame(centrerEtiquette));
/** Les rangées d'onglets qui défilent en largeur montrent un fondu du côté où il reste quelque chose. */
const defilements = new WeakSet();
function fonduSur(el) {
  const maj = () => {
    el.classList.toggle("fondu-gauche", el.scrollLeft > 4);
    el.classList.toggle("fondu-droite", el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  };
  if (!defilements.has(el)) { defilements.add(el); el.addEventListener("scroll", maj, { passive: true }); }
  maj();
}
const observateurOnglets = "MutationObserver" in window ? new MutationObserver(() => surveillerDefilements()) : null;
function surveillerDefilements() {
  requestAnimationFrame(() => { for (const el of document.querySelectorAll(".sous-onglets, .onglets-fiche")) fonduSur(el); });
}
if (observateurOnglets) observateurOnglets.observe(document.body, { childList: true, subtree: true });
addEventListener("resize", retarder(surveillerDefilements, 150));
function majFondus() {
  const r = $("#rubriques");
  r.classList.toggle("fondu-gauche", r.scrollLeft > 4);
  r.classList.toggle("fondu-droite", r.scrollLeft + r.clientWidth < r.scrollWidth - 4);
}
/** Ce qui demande l'attention : les compteurs des pancartes et des étiquettes. */
function compteurs() {
  const d = etat.d, n = Date.now() / 1000;
  if (!d) return {};
  const qOuvertes = ((d.questions && d.questions.liste) || []).filter((q) => q.statut === "ouverte").length;
  const oublies = d.tickets.ouverts.filter((t) => !t.pris_par && t.ouvert && n - t.ouvert > 86400 && !t.rellseas).length;
  const ticketsClan = d.tickets.ouverts.filter((t) => t.rellseas).length;
  const echus = ((d.clan && d.clan.membres) || []).filter((m) => m.rappel && m.rappel.statut === "echu").length;
  const aDecider = d.en_cours.filter((c) => (c.etape || 1) === 1 || /reponse|partiel/.test(c.recrutement || "")).length;
  const alertes = (d.alertes || []).length;
  const att = HL.file.ops.length;
  const brouillons = ((vueJeu("evenements") || {}).brouillons || []).length;
  return {
    "port/apercu": [alertes, alertes > 0], "port/tickets": [d.tickets.ouverts.filter((t) => !t.rellseas).length, oublies > 0], "port/salons": [qOuvertes, qOuvertes > 0],
    "equipage/membres": [echus, echus > 0], "equipage/candidatures": [aDecider, aDecider > 0], "equipage/tickets": [ticketsClan, false],
    "equipage/annonces": [brouillons, false],
    port: alertes + qOuvertes + oublies, equipage: echus + aDecider, capitainerie: att,
  };
}
function majCompteurs() {
  const c = compteurs();
  for (const a of $("#pancartes").querySelectorAll("a")) {
    const p = a.querySelector(".pancarte-pastille");
    const v = c[a.dataset.cat] || 0;
    p.hidden = !v;
    p.textContent = v > 99 ? "99+" : String(v);
  }
  for (const a of $("#rubriques").querySelectorAll("a")) {
    const k = etat.route.cat + "/" + a.dataset.rub;
    const [v, chaud] = c[k] || [0, false];
    const b = a.querySelector(".compteur");
    b.hidden = !v;
    b.textContent = v > 999 ? "999+" : String(v);
    b.classList.toggle("chaud", !!chaud);
  }
}

// ─── Les routes ─────────────────────────────────────────────────────────────
function lireRoute(premiere) {
  const a = lireAncre();
  let cat = a.cat, rub = a.rub;
  if (!cat && a.ancien) {
    const anciens = { apercu: ["port", "apercu"], candidatures: ["equipage", "candidatures"], tickets: ["port", "tickets"], moderation: ["port", "sanctions"],
      journal: ["port", "journal"], questions: ["port", "salons"], sondages: ["port", "salons"], clan: ["equipage", "membres"] };
    [cat, rub] = anciens[a.ancien] || [];
  }
  if (!cat) {
    let mem = null;
    try { mem = JSON.parse(sessionStorage.getItem("capitainerie.route") || "null"); } catch (e) { mem = null; }
    cat = (mem && CATEGORIES.some((c) => c.cle === mem.cat) && mem.cat) || "port";
    rub = (mem && mem.cat === cat && mem.rub) || null;
  }
  rub = rubrique(cat, rub).cle;
  const change = premiere || cat !== etat.route.cat || rub !== etat.route.rub || (a.sous || "") !== etat.route.sous;
  etat.route = { cat, rub, sous: a.sous || "" };
  memoireRubrique[cat] = rub;
  try { sessionStorage.setItem("capitainerie.route", JSON.stringify({ cat, rub })); } catch (e) { /* rien */ }
  if (premiere) poserAncre(a.membre ? "membre=" + a.membre : "");
  majRubriques();
  return change;
}
addEventListener("hashchange", () => {
  const a = lireAncre();
  if (lireRoute(false)) { rendre(true); scrollTo({ top: 0 }); }
  if (a.membre) ouvrirFiche(a.membre);
});

function rendre(force) {
  const { cat, rub, sous } = etat.route;
  const cle = cat + "/" + rub;
  const contenu = $("#contenu");
  if (!force && courante && courante.cle === cle && courante.sous === sous && courante.ctrl && courante.ctrl.maj) { courante.ctrl.maj(); majCompteurs(); return; }
  if (courante && courante.ctrl && courante.ctrl.quitter) { try { courante.ctrl.quitter(); } catch (e) { /* rien */ } }
  const r = rubrique(cat, rub);
  const corps = h("div", { classe: "rubrique-corps" });
  remplacer(contenu, titreRubrique(r), corps);
  let ctrl = null;
  if (!etat.d && !AUTONOMES.has(cle)) {
    ajouter(corps, [etat.chargementEnCours ? chargement("Lecture du livre de bord…") : port.indisponible()]);
  } else {
    try { ctrl = RENDUS[cle](corps, { sous, rub: r }) || null; }
    catch (e) {
      console.error("[capitainerie] rubrique", cle, e);
      remplacer(corps, vide("Cette page n'a pas pu s'afficher", "Recharge la page. Si cela recommence, note ce qui a été fait juste avant.", "attention"));
    }
  }
  courante = { cle, sous, ctrl };
  surveillerDefilements();
  document.title = r.titre + " · La Capitainerie";
  majCompteurs();
  majBoutonsReseau(contenu);
  if (!force) return;
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest(".etiquette")) contenu.focus({ preventScroll: true });
}

// ─── Les données du serveur ─────────────────────────────────────────────────
async function chargerDonnees(manuel) {
  if (etat.chargementEnCours || etat.session !== "ok") return;
  etat.chargementEnCours = true;
  majPlaque();
  const r = await lire("donnees", null, { etag: etat.etag });
  etat.chargementEnCours = false;
  if (r.ok && r.status === 304) {
    etat.dernier = Date.now(); etat.ageCache = 0;
  } else if (r.ok && r.donnees) {
    const d = r.donnees;
    if (r.horsLigne) {
      etat.ageCache = r.sauveLe ? Date.now() - r.sauveLe : 0;
      if (!etat.d || (r.sauveLe && r.sauveLe > etat.dernier)) accepter(d);
    } else {
      etat.etag = r.etag; etat.dernier = Date.now(); etat.ageCache = 0;
      accepter(d);
    }
  } else if (manuel) {
    toast(r.status === 0 ? "Pas de connexion : les données affichées restent celles d'avant." : r.erreur || "Le serveur ne répond pas.", "erreur");
  }
  majBandeaux();
  majPlaque();
  majCompteurs();
  if (etat.d && !courante) rendre(true);
}
function accepter(d) {
  const premiere = !etat.d;
  etat.d = d;
  retenirPersonnes(d.personnes);
  if (d.version) {
    if (etat.premiereVersion === undefined) etat.premiereVersion = d.version;
    if ((V !== "dev" && d.version !== V) || d.version !== etat.premiereVersion) etat.versionNeuve = true;
  }
  majMarque();
  pied();
  if (!premiere) rendre(false);
  emettre("donnees");
}
function planifier() {
  clearTimeout(planifier.t);
  planifier.t = setTimeout(async () => {
    if (!document.hidden && etat.session === "ok") await chargerDonnees();
    planifier();
  }, etat.reseau.enLigne ? RAFRAICHIR : RAFRAICHIR / 2);
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if (Date.now() - etat.dernier > 45000) chargerDonnees();
  if (HL.enAttente().length) HL.envoyer();
  if (etat.versionNeuve) verifierVersion();
});
addEventListener("online", () => { noterReseau(true); chargerDonnees(); HL.envoyer(); });
addEventListener("offline", () => noterReseau(false, "reseau"));
ecouter("reseau", () => {
  majPlaque(); majBandeaux();
  if (etat.reseau.enLigne && HL.enAttente().length) HL.planifierEnvoi(300);
});
ecouter("session", () => { majPlaque(); majBandeaux(); pied(); });
ecouter("file", () => { majPlaque(); majCompteurs(); if (courante && courante.ctrl && courante.ctrl.majFile) courante.ctrl.majFile(); });
ecouter("file:succes", ({ abandon }) => { if (!abandon && !HL.enAttente().length && !HL.file.enCours) toast("Tout est envoyé : le serveur a enregistré tes modifications.", "succes"); });
ecouter("file:conflit", ({ op }) => toast("Conflit : « " + (op.resume || "une modification") + " » a changé ailleurs. Choisis la bonne version.", "erreur"));
ecouter("file:refus", ({ op }) => toast("Refusé par le serveur : " + (op.erreur || op.resume), "erreur"));
ecouter("file:ouvrir", () => ouvrirFile());
ecouter("recharger", () => chargerDonnees());
ecouter("jeu", () => { if (courante && courante.ctrl && courante.ctrl.majJeu) courante.ctrl.majJeu(); majCompteurs(); });
ecouter("dossier:ouvrir", (ticket) => { if (etat.route.cat !== "equipage" || etat.route.rub !== "candidatures") aller("equipage", "candidatures"); setTimeout(() => recrutement.ouvrirDossier(ticket), 60); });
ecouter("affiche:ouvrir", (id) => cap.ouvrirAffiche(id));

// ─── Bandeaux (session, hors ligne, nouvelle version) ───────────────────────
function majBandeaux() {
  const zone = $("#bandeaux");
  const b = [];
  const att = HL.enAttente().length + HL.enConflit().length;
  if (etat.session !== "ok") {
    b.push(bandeau(h("span", {}, h("b", {}, "Ta session est terminée. "), "Pour continuer, ouvre un nouveau lien depuis le salon « logs » sur Discord (bouton « Ouvrir le tableau de bord »)."
      + (att ? " Reconnecte-toi pour envoyer " + att + " modification" + (att > 1 ? "s" : "") + " : elles sont gardées sur cet appareil." : "")), "rouge"));
  } else if (!etat.reseau.enLigne) {
    b.push(bandeau(h("span", {}, h("b", {}, "Hors ligne. "), "Tu peux continuer : affiches, catalogue, brouillons et questionnaire sont gardés sur cet appareil et partiront au retour de la connexion. "
      + "Les actions sur Discord (modération, rôles, publications) attendent la connexion." + (etat.ageCache ? " Données d'il y a " + ageTexte(etat.ageCache) + "." : "")), "",
      bouton("Réessayer", { classe: "p", icone: "synchro", onclick: () => { chargerDonnees(true); HL.envoyer(); } })));
  }
  if (etat.versionNeuve) b.push(bandeau(h("span", {}, h("b", {}, "Une nouvelle version du site est prête. "), "Elle se chargera d'elle-même dès que tu ne seras plus en train d'écrire."), "vert",
    bouton("Recharger maintenant", { classe: "p", icone: "synchro", onclick: () => location.reload() })));
  remplacer(zone, ...b);
}
function calme() {
  const a = document.activeElement;
  return !pancartesOuvertes() && !(a && /INPUT|TEXTAREA|SELECT/.test(a.tagName)) && !String(getSelection() || "") && !etat.selection.size && !HL.file.enCours;
}
function verifierVersion() {
  if (!etat.versionNeuve) return;
  majBandeaux();
  if (document.hidden || !calme()) return;
  // Un seul rechargement automatique par version et par quart d'heure : jamais de boucle si le serveur et la page
  // ne s'accordent pas sur la version (le bandeau reste, avec « Recharger maintenant »).
  let deja = null;
  try { deja = JSON.parse(sessionStorage.getItem("capitainerie.recharge") || "null"); } catch (e) { deja = null; }
  const cible = String((etat.d && etat.d.version) || "");
  if (deja && deja.version === cible && Date.now() - deja.quand < 15 * 60000) return;
  try { sessionStorage.setItem("capitainerie.recharge", JSON.stringify({ version: cible, quand: Date.now() })); } catch (e) { return; }
  location.reload();
}

// ─── La file d'envoi (pancarte) ─────────────────────────────────────────────
function ouvrirFile() {
  const p = pancarte({ titre: "File d'envoi", sous: "Les modifications faites ici partent au serveur dès qu'il répond.", icone: "synchro", taille: "large" });
  const majFile = () => {
    if (p.fermee()) return;
    const ops = HL.file.ops;
    const blocs = [];
    blocs.push(h("p", { classe: "aide" }, etat.session !== "ok" ? "Session terminée : reconnecte-toi par le salon « logs » ; tout ce qui est ici partira à la reconnexion."
      : etat.reseau.enLigne ? "En ligne : l'envoi se fait tout seul (au retour de la connexion, à la reprise de la page, et toutes les 30 secondes)."
        : "Hors ligne : rien n'est perdu. L'envoi reprendra tout seul au retour de la connexion."));
    if (!ops.length) blocs.push(h("div", { classe: "vide" }, icone("succes"), h("b", {}, "Rien en attente"), h("p", {}, HL.file.dernierEnvoi ? "Dernier envoi " + depuis(HL.file.dernierEnvoi / 1000) + "." : "Tout est enregistré sur le serveur.")));
    else blocs.push(h("ul", { classe: "file-liste" }, ops.map((op) => ligneOp(op, p))));
    if (HL.file.memoireSeule) blocs.push(bandeau("Ce navigateur ne permet pas de garder la file sur l'appareil (navigation privée ?) : elle vit tant que l'onglet est ouvert.", ""));
    remplacer(p.corps, ...blocs);
    remplacer(p.pied, bouton("Fermer", { classe: "discret", onclick: () => p.fermer() }),
      HL.enAttente().length ? bouton("Envoyer maintenant", { classe: "principal", icone: "synchro", reseau: true, onclick: async () => { const r = await HL.envoyer(); if (r.erreur) toast("Envoi impossible pour le moment : tout reste dans la file.", "erreur"); } }) : null);
  };
  const stop = ecouter("file", majFile);
  p.dlg.addEventListener("close", stop);
  majFile();
}
const ETATS_OP = { attente: ["En attente", "ambre"], conflit: ["Conflit", ""], refus: ["Refusé", ""], erreur: ["Échec", ""] };
function ligneOp(op, p) {
  const [lib, coul] = ETATS_OP[op.etat] || [op.etat, "encre"];
  return h("li", { classe: "file-op" },
    h("div", { classe: "file-op-tete" }, h("b", {}, op.resume || op.api), op.envoi ? h("span", { classe: "tampon mer" }, "Envoi") : h("span", { classe: "tampon " + coul }, lib)),
    h("div", { classe: "meta" }, "Faite " + depuis(op.cree / 1000) + (op.essais ? " · " + quantite(op.essais, "essai(s)") : "") + (op.erreur ? " · " + op.erreur : "")),
    op.etat === "conflit" && op.conflitGenre === "doublon" ? h("p", { classe: "aide" }, "Ce membre a déjà une affiche active : une seule par membre. Modifie celle qui existe, ou mets-la d'abord à la corbeille.") : null,
    op.etat === "conflit" && op.conflitGenre === "retiree" ? h("p", { classe: "aide" }, "Cette affiche est dans la corbeille : restaure-la, puis renvoie la modification.") : null,
    op.etat === "conflit" && op.conflitGenre === "publie" ? h("p", { classe: "aide" }, "Cet élément a été publié entre-temps : modifie-le depuis « À venir ».") : null,
    h("div", { classe: "rangee" },
      op.etat === "conflit" && (!op.conflitGenre || op.conflitGenre === "version") ? bouton("Régler le conflit", { classe: "p principal", icone: "attention", onclick: () => reglerConflit(op) }) : null,
      op.etat === "conflit" && op.conflitGenre === "retiree" ? bouton("Restaurer puis renvoyer", { classe: "p principal", icone: "restaurer", reseau: true, onclick: async () => {
        const r = await poster("rell/affiche/restaurer", { id: op.corps.id });
        if (!r.ok) { toast(r.erreur, "erreur"); return; }
        const v = r.donnees && r.donnees.affiche && r.donnees.affiche.version;
        await HL.renvoyer(op, Object.assign({}, op.corps, v !== undefined ? { version: v } : {}));
      } }) : null,
      op.etat === "erreur" ? bouton("Réessayer", { classe: "p", icone: "synchro", onclick: () => HL.renvoyer(op, op.corps) }) : null,
      bouton(op.etat === "attente" ? "Annuler cette modification" : "Retirer de la file", { classe: "p discret danger", icone: "supprimer", onclick: async () => {
        const ok = await confirmer({ titre: "Abandonner cette modification ?", texte: "« " + (op.resume || op.api) + " » ne sera jamais envoyée. L'affichage revient à la version du serveur.", libelleOk: "Abandonner", style: "danger" });
        if (ok) { await HL.abandonner(op); for (const n of ["affiches", "catalogue", "evenements", "banque", "dossier"]) perime(n); emettre("jeu", {}); }
      } })));
}

/** La version du serveur ramenée à la forme de ce que la page envoie (sinon : de fausses différences). */
const FORMES = {
  affiche: (a) => ({ id: a.id, membre_id: String((a.membre && a.membre.id) || a.membre_id || ""), roblox: { nom: (a.roblox && a.roblox.nom) || "", id: String((a.roblox && a.roblox.id) || "") },
    surnom: a.surnom || "", prime: a.prime || 0, niveau: a.niveau || 0, grade: a.grade || "", statut: a.statut || "actif", attributs: a.attributs || {}, notes: a.notes || "", version: a.version }),
  brouillon: (e) => Object.assign({}, e.valeurs || {}, { id: e.id, type: e.type, titre: e.titre, quand: e.quand, destination: e.destination, version: e.version }),
  question: (q) => Object.assign({}, q, { question: q.question || q.texte || "", reponse: q.reponse || q.reponse_attendue || "" }),
};
const LIBELLES_CHAMPS = { membre_id: "Membre", roblox: "Nom Roblox", surnom: "Surnom", prime: "Prime", niveau: "Niveau", grade: "Grade", statut: "Statut", attributs: "Insignes",
  notes: "Notes", titre: "Titre", texte: "Texte", quand: "Date", duree_min: "Durée", lieu: "Lieu", image: "Image", couleur: "Couleur", rappels: "Rappels", mention: "Mention",
  destination: "Salon", reponses: "Boutons de réponse", places: "Places", discord_event: "Évènement Discord", reserve_clan: "Réservé au clan", nom: "Nom", nom_en: "Nom en anglais",
  description: "Description", categorie: "Catégorie", rarete: "Rareté", icone: "Icône", source: "Source", actif: "Présent dans le jeu", nouveau_movie3: "Nouveauté du Movie 3",
  question: "Question", reponse: "Réponse attendue", variantes: "Variantes", difficulte: "Difficulté", active: "Active", questions: "Questions", par_defaut: "Par défaut" };
function valeurLisible(k, v) {
  if (v === undefined || v === null || v === "") return "(vide)";
  if (k === "membre_id") return nomDe(P(v)) + " (" + v + ")";
  if (k === "roblox" && typeof v === "object") return v.nom || "(vide)";
  if (k === "quand" && typeof v === "number") return date(v, true);
  if (k === "prime") return nombre(v) + " berrys";
  if (typeof v === "boolean") return v ? "oui" : "non";
  if (k === "attributs" && typeof v === "object") return Object.entries(v).map(([t, l]) => t + " : " + (l || []).join(", ")).join(" · ") || "(aucun)";
  if (Array.isArray(v)) return v.join(", ") || "(aucun)";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Les deux versions côte à côte : champ par champ, on garde la sienne ou celle du serveur. */
function reglerConflit(op) {
  const mien = op.corps || {}, serveur = (FORMES[op.genre] || ((x) => x))(op.conflit || {});
  const ignorer = new Set(["id", "cle_client", "version", "maj_le", "maj_par", "cree_le", "cree_par", "maj", "cree", "historique", "_attente", "_op"]);
  const champs = [...new Set(Object.keys(mien))].filter((k) => !ignorer.has(k) && JSON.stringify(mien[k] ?? null) !== JSON.stringify(serveur[k] ?? null));
  const choix = Object.fromEntries(champs.map((k) => [k, "mien"]));
  const p = pancarte({ titre: "Régler le conflit", sous: op.resume || "", icone: "attention", taille: "large" });
  ajouter(p.corps, [h("p", {}, "Pendant que tu travaillais, cet élément a été modifié ailleurs (version " + (serveur.version ?? "?") + "). Pour chaque différence, choisis la version à garder.")]);
  if (!champs.length) ajouter(p.corps, [h("p", { classe: "aide" }, "Aucune différence visible : ta version peut repartir telle quelle.")]);
  ajouter(p.corps, [h("div", { classe: "conflit-liste" }, champs.map((k) => {
    const nom = "conflit-" + k + "-" + op.op_id.slice(0, 6);
    const opt = (val, lib, contenu) => {
      const i = h("input", { type: "radio", name: nom, value: val });
      i.checked = choix[k] === val;
      i.addEventListener("change", () => { choix[k] = val; });
      return h("label", { classe: "conflit-choix radio" }, i, h("span", { classe: "radio-rond", "aria-hidden": "true" }), h("span", { classe: "case-texte" }, h("b", {}, lib), h("span", { classe: "conflit-valeur" }, contenu)));
    };
    return h("fieldset", { classe: "conflit-champ" }, h("legend", {}, LIBELLES_CHAMPS[k] || k), opt("mien", "Ma version", valeurLisible(k, mien[k])), opt("serveur", "Version enregistrée", valeurLisible(k, serveur[k])));
  }))]);
  ajouter(p.pied, [
    bouton("Garder la version enregistrée", { classe: "discret", onclick: async () => { await HL.garderServeur(op); p.fermer(); toast("Version enregistrée gardée.", "succes"); } }),
    bouton("Envoyer ce choix", { classe: "principal", icone: "valider", onclick: async () => {
      const corps = Object.assign({}, mien);
      for (const k of champs) if (choix[k] === "serveur") corps[k] = serveur[k];
      corps.version = serveur.version;
      const objet = op.objet ? Object.assign({}, op.objet, corps, { version: serveur.version }) : null;
      await HL.renvoyer(op, corps, objet);
      p.fermer();
      toast("Ton choix part au serveur.", "succes");
    } })]);
}
ecouter("conflit:regler", (op) => reglerConflit(op));

// ─── Pied de page, session, déconnexion ─────────────────────────────────────
function pied() {
  const d = etat.d;
  const zone = $("#pied");
  if (!d) { remplacer(zone); return; }
  remplacer(zone,
    h("p", {}, etat.session !== "ok" ? "Session terminée." : "Session personnelle jusqu'au " + date(d.expire, true) + ". "
      + (peutAgir() ? "Chaque action est confirmée et inscrite au journal ; le fondateur et la direction ne peuvent pas être touchés depuis le site." : "Consultation seule.")
      + " Hors ligne, tu peux continuer : tout est gardé et envoyé au retour."),
    h("div", { classe: "rangee" },
      bouton("Fermer toutes mes sessions", { classe: "p discret", icone: "cadenas", reseau: true, onclick: fermerPartout }),
      bouton("Se déconnecter", { classe: "p discret", icone: "deconnexion", onclick: deconnecter })));
}

async function proposerEnvoi() {
  const n = HL.file.ops.length;
  if (!n) return true;
  return new Promise((fin) => {
    let choix = null;
    const p = pancarte({ titre: n + " modification" + (n > 1 ? "s" : "") + " pas encore envoyée" + (n > 1 ? "s" : ""), icone: "synchro", taille: "etroite", surFermer: () => fin(choix) });
    ajouter(p.corps, [h("p", {}, "Elles sont gardées sur cet appareil. Se déconnecter les efface : envoie-les d'abord.")]);
    ajouter(p.pied, [
      bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }),
      bouton("Effacer et se déconnecter", { classe: "danger", onclick: () => { choix = true; p.fermer(); } }),
      bouton("Envoyer d'abord", { classe: "principal", icone: "synchro", reseau: true, onclick: async () => {
        await HL.envoyer();
        if (HL.file.ops.length) { toast("Certaines modifications n'ont pas pu partir : elles restent dans la file.", "erreur"); choix = false; }
        else choix = true;
        p.fermer();
      } })]);
  });
}
async function nettoyerAppareil() {
  await HL.toutEffacer();
  oublierTout();
  oublierPrefs();
  try { sessionStorage.clear(); } catch (e) { /* rien */ }
  try { for (const k of Object.keys(localStorage)) if (k.startsWith("capitainerie")) localStorage.removeItem(k); } catch (e) { /* rien */ }
  try {
    if ("caches" in self) for (const k of await caches.keys()) await caches.delete(k);
    const reg = navigator.serviceWorker && (await navigator.serviceWorker.getRegistration(BASE + "/"));
    if (reg && reg.active) reg.active.postMessage({ type: "vider" });
  } catch (e) { /* rien */ }
}
async function deconnecter() {
  if (!(await proposerEnvoi())) return;
  try { await fetch(BASE + "/sortir", { method: "POST", credentials: "same-origin", headers: { "X-Tableau": "1" } }); } catch (e) { /* la session expirera d'elle-même */ }
  await nettoyerAppareil();
  fin("Tu es déconnecté, et cet appareil est nettoyé. Pour revenir : salon « logs » sur Discord, « Ouvrir le tableau de bord ».");
}
async function fermerPartout() {
  const ok = await confirmer({ titre: "Fermer toutes tes sessions ?", texte: "Chaque navigateur connecté au site avec ton compte est déconnecté, celui-ci compris. Pour revenir : salon « logs » sur Discord, « Ouvrir le tableau de bord ».", libelleOk: "Tout fermer", style: "danger" });
  if (!ok || !(await proposerEnvoi())) return;
  const r = await poster("sortir", undefined, { partout: 1 });
  if (!r.ok && r.status !== 403) { toast(r.erreur || "Les sessions n'ont pas pu être fermées.", "erreur"); return; }
  await nettoyerAppareil();
  fin("Toutes tes sessions sont fermées, celle-ci comprise, et cet appareil est nettoyé. Pour revenir : salon « logs » sur Discord.");
}
function fin(texte) {
  etat.session = "expiree";
  clearTimeout(planifier.t);
  remplacer($("#rubriques"));
  $("#pancartes").hidden = true;
  remplacer($("#entete-outils"));
  remplacer($("#pied"));
  remplacer($("#bandeaux"));
  remplacer($("#contenu"), h("div", { classe: "adieu" }, h("span", { classe: "attente-boussole", "aria-hidden": "true" }), h("h1", {}, "Bon vent, capitaine"), h("p", {}, texte)));
  document.title = "La Capitainerie";
}

demarrer();
