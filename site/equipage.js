// equipage.js — le site de l'équipage (26/10/2026) : démarrage, en-tête, trois onglets (Accueil · L'équipage ·
// Ma fiche), session et déconnexion. Pour les membres du rôle du clan : LECTURE SEULE, aucun bouton d'action. Pour le
// fondateur et la direction : le mode édition de l'accueil (equipage_accueil.js).
// Rien du site de la direction n'est chargé ici : ni ses données, ni sa file hors ligne, ni son service worker.

import { h, icone, $, BASE, chargerSprite, completerSprite, remplacer, ajouter, sansEmoji, srcSure, date, nombre, reduit } from "./dom.js";
import { etat, ecouter, poserLibelles, filtres, libelle } from "./noyau.js";
import { poster } from "./api.js";
import { bouton, boutonIcone, menu, confirmer, toast, titreRubrique, vide, bandeau, segment } from "./ui.js";
import { affiche } from "./affiche.js";
import { E, T, lire, ouvrirAffiche, detailsAffiche, catalogue, afficheParId, rangPrime } from "./equipage_commun.js";
import * as accueil from "./equipage_accueil.js";
import { rendreMur } from "./equipage_mur.js";
import { rendreEquipes, sectionMonEquipe, avecEquipes } from "./equipage_equipes.js";
import { boutonLienEquipage } from "./lien_equipage.js";

/** La version des fichiers : celle de la balise <script> de cette page (s/equipage.js?v=…), posée par le serveur. */
const V = (() => {
  try {
    const s = document.querySelector('script[type="module"][src*="/s/equipage.js"]');
    return (s && new URL(s.src).searchParams.get("v")) || "dev";
  } catch (e) { return "dev"; }
})();
const RAFRAICHIR = 60000;
const ICONES = ["navire", "affiches", "personne", "capitainerie", "menu", "deconnexion", "cadenas", "fermer", "rechercher", "filtrer",
  "journal", "calendrier", "etoile", "apercu", "parchemin", "image", "plume", "ajouter", "modifier", "supprimer", "haut", "bas", "oeil",
  "masquer", "valider", "epingle", "info", "attention", "succes", "minuteur", "lieu", "membres", "prime", "berry", "grade", "drapeau",
  "carte", "boussole", "ancre", "crane", "droite", "synchro", "annonces", "evenements", "equipage", "longue_vue", "coffre", "sabre",
  "lien", "copier"];
const ONGLETS = [
  { cle: "accueil", icone: "navire", titre: () => T("onglet.accueil", "Accueil"), sous: () => T("onglet.accueil.sous", "Le pont du navire"),
    phrase: () => T("accueil.phrase", "Les nouvelles du bord, les sorties en mer et l'équipage en chiffres.") },
  { cle: "equipage", icone: "affiches", titre: () => T("onglet.equipage", "L'équipage"), sous: () => T("onglet.equipage.sous", "Toutes les affiches"),
    phrase: () => T("equipage.phrase", "Les équipes du clan, leur chef en tête, et l'avis de recherche de chaque pirate.") },
  { cle: "fiche", icone: "personne", titre: () => T("onglet.fiche", "Ma fiche"), sous: () => T("onglet.fiche.sous", "Mon avis de recherche"),
    phrase: () => T("fiche.phrase", "Ton avis de recherche, tel que tout l'équipage le voit.") },
];
const onglet = (cle) => ONGLETS.find((o) => o.cle === cle) || ONGLETS[0];
let courant = "";
let versionNeuve = false;

// ─── Démarrage ──────────────────────────────────────────────────────────────
async function demarrer() {
  await Promise.race([chargerSprite(BASE + "/s/icones/ui.svg?v=" + V), new Promise((ok) => setTimeout(ok, 2500))]);
  completerSprite(ICONES);
  const [d, eq] = await Promise.all([lire("depart"), lire("equipage")]);
  document.body.classList.remove("demarrage");
  if (!d.ok) {
    if (etat.session === "ok") remplacer($("#contenu"), vide("Le navire ne répond pas", (d.erreur || "Indisponible pour le moment.") + " Recharge la page dans un instant.", "attention"));
    return;
  }
  E.depart = d.donnees;
  E.textes = d.donnees.textes || {};
  poserLibelles(d.donnees.libelles || {});   // les statuts et tampons d'affiche renommés (affiche.js les lit)
  E.peutEditer = !!d.donnees.edition;
  if (eq.ok) E.equipage = eq.donnees;
  if (d.donnees.version && V !== "dev" && d.donnees.version !== V) versionNeuve = true;
  monterEntete();
  monterPancartes();
  pied();
  lireRoute(true);
  if (E.peutEditer && d.donnees.modules && d.donnees.modules.direct) chargerDirect();
  setInterval(rafraichir, RAFRAICHIR);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && Date.now() - dernier > RAFRAICHIR / 2) rafraichir(); });
}

/** La présence en direct (« À bord ») et les verrous d'édition (site/direct.js), pour le fondateur et la direction
 *  seulement : l'équipage, en lecture seule, ne la charge jamais (le serveur la lui refuse aussi). */
async function chargerDirect() {
  try {
    const m = await import("./direct.js");
    E.direct = m;
    m.demarrerDirect();
  } catch (e) {
    console.error("[equipage] présence en direct indisponible", e);
  }
}

// ─── En-tête : le médaillon, le nom, les outils ─────────────────────────────
function monterEntete() {
  const d = E.depart;
  const nom = sansEmoji(d.serveur && d.serveur.nom) || "L'Équipage";
  $("#nom-serveur").textContent = T("titre", "L'Équipage");
  $("#sous-titre").textContent = (d.clan ? "Clan " + d.clan + " · " : "") + nom;
  const logo = $("#logo-serveur");
  const src = srcSure(d.serveur && d.serveur.icone);
  if (src) {
    const img = h("img", { src, alt: "", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => remplacer(logo, nom.slice(0, 1)), { once: true });
    remplacer(logo, img);
  } else remplacer(logo, nom.slice(0, 1));
  const outils = [boutonLienEquipage()];   // le lien PUBLIC de la vitrine, à partager (tout le monde peut le copier)
  if (E.peutEditer) {
    outils.push(h("button", { classe: "bouton bois vers-capitainerie", type: "button", title: "Le site de la direction", onclick: () => { location.href = BASE + "/"; } },
      icone("capitainerie"), h("span", {}, "La Capitainerie")));
  }
  outils.push(menu(boutonIcone("menu", "Menu", null, "sur-bois"), () => [
    { titre: (E.depart.moi && sansEmoji(E.depart.moi.nom)) || "Session" },
    E.peutEditer ? { l: "La Capitainerie", sous: "le site de la direction", icone: "capitainerie", onclick: () => { location.href = BASE + "/"; } } : null,
    { l: "Fermer toutes mes sessions", icone: "cadenas", onclick: fermerPartout },
    { l: "Se déconnecter", icone: "deconnexion", onclick: deconnecter, danger: true },
  ]));
  remplacer($("#entete-outils"), ...outils);
}

// ─── Les trois pancartes ────────────────────────────────────────────────────
function monterPancartes() {
  const nav = $("#pancartes");
  remplacer(nav, ...ONGLETS.map((o) => h("a", { classe: "pancarte-nav", href: "#" + o.cle, "data-onglet": o.cle },
    icone(o.icone), h("span", { classe: "pancarte-titre" }, o.titre()), h("span", { classe: "pancarte-court", "aria-hidden": "true" }, o.titre()),
    h("span", { classe: "pancarte-sous" }, o.sous()))));
  for (const a of nav.querySelectorAll("a")) a.addEventListener("click", (e) => {
    if (a.dataset.onglet === courant) { e.preventDefault(); scrollTo({ top: 0, behavior: reduit.matches ? "auto" : "smooth" }); }
  });
}

// ─── Les routes : #accueil · #equipage · #fiche (&affiche=<id> : une affiche ouverte) ─────
function lireAncre() {
  const [chemin, ...reste] = location.hash.replace(/^#/, "").split("&");
  const params = new URLSearchParams(reste.join("&"));
  return { cle: ONGLETS.some((o) => o.cle === chemin) ? chemin : "accueil", affiche: params.get("affiche") || "" };
}
function lireRoute(premiere) {
  const a = lireAncre();
  const change = premiere || a.cle !== courant;
  courant = a.cle;
  etat.route = { cat: "site-equipage", rub: courant, sous: "" };   // ce que « À bord » dit de cette page (direct.js)
  for (const x of $("#pancartes").querySelectorAll("a")) x.setAttribute("aria-current", x.dataset.onglet === courant ? "page" : "false");
  if (change) rendre();
  if (a.affiche) {
    try { history.replaceState(null, "", location.pathname + "#" + courant); } catch (e) { /* adresse inchangée */ }
    ouvrirAffiche(a.affiche);
  }
}
addEventListener("hashchange", () => { lireRoute(false); scrollTo({ top: 0 }); });

function rendre() {
  if (etat.session !== "ok") return;
  const o = onglet(courant);
  const corps = h("div", { classe: "rubrique-corps" });
  const titre = titreRubrique({ icone: o.icone, titre: o.titre(), phrase: o.phrase() });
  remplacer($("#contenu"), titre, corps);
  document.title = o.titre() + " · " + T("titre", "L'Équipage");
  try {
    if (courant === "accueil") accueil.rendre(corps, titre);
    else if (courant === "equipage") rendreEquipage(corps);
    else rendreFiche(corps);
  } catch (e) {
    console.error("[equipage] onglet", courant, e);
    remplacer(corps, vide("Cette page n'a pas pu s'afficher", "Recharge la page. Si cela recommence, préviens la direction.", "attention"));
  }
}
ecouter("equipage:rendre", () => { if (courant === "accueil") rendre(); });

// ═══ L'ÉQUIPAGE : toutes les affiches, par métier (equipage_mur.js, le même mur que la vitrine publique) ═════
function rendreEquipage(corps) {
  if (!avecEquipes()) { rendreMur(corps, { cle: "site-equipage" }); return; }
  //  27/10/2026 : les équipes du clan (le chef mis en avant), ou toutes les affiches par métier.
  const f = filtres("site-equipage-vue", { vue: "equipes" });
  const zone = h("div", { classe: "pile" });
  const dessiner = () => { remplacer(zone); if (f.vue === "affiches") rendreMur(zone, { cle: "site-equipage" }); else rendreEquipes(zone, { cle: "site-equipes" }); };
  ajouter(corps, [segment(f.vue, [["equipes", libelle("site.equipes.titre", "Les équipes")], ["affiches", "Toutes les affiches"]], (v) => { f.vue = v; dessiner(); }, "Afficher"), zone]);
  dessiner();
}
/** Après un réglage de la direction (une affiche retirée de la vitrine, ou remise) : le mur se redessine. */
E.majMur = () => { if (courant === "equipage") rendre(); };

// ═══ MA FICHE ════════════════════════════════════════════════════════════
function rendreFiche(corps) {
  const eq = E.equipage;
  const a = eq && eq.moi ? afficheParId(eq.moi) : null;
  //  Mon équipe (27/10/2026) : le chef y voit les membres qu'il a sous sa main ; un membre, son équipe.
  const equipe = avecEquipes() ? sectionMonEquipe() : null;
  if (!a) {
    ajouter(corps, [vide(T("fiche.vide.titre", "Pas encore d'affiche"), T("fiche.vide.texte", "Demande à la direction : elle crée ton avis de recherche."), "affiches"),
      eq && (eq.affiches || []).length ? h("p", { classe: "aide centre" }, h("a", { href: "#equipage" }, "Voir les affiches de l'équipage")) : null, equipe]);
    return;
  }
  const rang = rangPrime(a);
  ajouter(corps, [h("div", { classe: "affiche-grand fiche-perso" },
    h("div", { classe: "affiche-grand-mur" }, affiche(a, catalogue(), { taille: "grande" })),
    h("div", { classe: "pile" },
      rang ? h("p", { classe: "fiche-rang" }, icone("prime"), h("span", {}, rang === 1 ? "La plus haute prime de l'équipage." : "La " + rang + "e prime de l'équipage, sur " + nombre((eq.affiches || []).length) + ".")) : null,
      detailsAffiche(a),
      h("p", { classe: "aide" }, "Une erreur sur ton affiche ? Demande à la direction : elle seule la modifie."))), equipe]);
}

// ─── Le rafraîchissement (chaque minute, page visible, rien en cours d'écriture) ─────
let dernier = Date.now();
async function rafraichir() {
  if (document.hidden || etat.session !== "ok") return;
  dernier = Date.now();
  const [eq, d] = await Promise.all([lire("equipage"), lire("depart")]);
  if (eq.ok && JSON.stringify(eq.donnees) !== JSON.stringify(E.equipage)) {
    E.equipage = eq.donnees;
    if (calme() && courant !== "accueil") rendre();
  }
  if (d.ok && d.donnees.version && V !== "dev" && d.donnees.version !== V) versionNeuve = true;
  if (courant === "accueil" && calme()) await accueil.recharger();
  majBandeaux();
}
function calme() {
  const a = document.activeElement;
  return !document.querySelector("dialog[open]") && !(a && /INPUT|TEXTAREA|SELECT/.test(a.tagName)) && !E.modeEdition;
}
function majBandeaux() {
  const zone = $("#bandeaux");
  if (!versionNeuve) { remplacer(zone); return; }
  if (calme() && !document.hidden) {
    let deja = null;
    try { deja = JSON.parse(sessionStorage.getItem("equipage.recharge") || "null"); } catch (e) { deja = null; }
    if (!deja || Date.now() - deja.quand > 15 * 60000) {
      try { sessionStorage.setItem("equipage.recharge", JSON.stringify({ quand: Date.now() })); location.reload(); return; } catch (e) { /* le bandeau reste */ }
    }
  }
  remplacer(zone, bandeau(h("span", {}, h("b", {}, "Une nouvelle version du site est prête. "), "Elle se chargera dès que tu auras fini."), "vert",
    bouton("Recharger maintenant", { classe: "p", icone: "synchro", onclick: () => location.reload() })));
}

// ─── Pied de page, session, déconnexion ─────────────────────────────────────
function pied() {
  const d = E.depart;
  remplacer($("#pied"),
    h("p", {}, (d.expire ? "Session personnelle jusqu'au " + date(d.expire, true) + ". " : "")
      + (E.peutEditer ? T("pied.edition", "Tu peux composer l'accueil : bouton « Modifier l'accueil ».") : T("pied.lecture", "Lecture seule : rien ne se modifie ici."))),
    h("div", { classe: "rangee" }, bouton("Se déconnecter", { classe: "p discret", icone: "deconnexion", onclick: deconnecter })));
}
async function deconnecter() {
  try { await fetch(BASE + "/sortir", { method: "POST", credentials: "same-origin", headers: { "X-Tableau": "1" } }); } catch (e) { /* la session expirera d'elle-même */ }
  fin(T("adieu.titre", "Bon vent, matelot"), T("adieu.texte", "Tu es déconnecté. Pour revenir : le guide du clan sur Discord, « Le site de l'équipage »."));
}
async function fermerPartout() {
  const ok = await confirmer({ titre: "Fermer toutes tes sessions ?", texte: "Chaque navigateur connecté avec ton compte est déconnecté, celui-ci compris.", libelleOk: "Tout fermer", style: "danger" });
  if (!ok) return;
  const r = await poster("sortir", undefined, { partout: 1 });
  if (!r.ok && r.status !== 403) { toast(r.erreur || "Les sessions n'ont pas pu être fermées.", "erreur"); return; }
  fin(T("adieu.titre", "Bon vent, matelot"), "Toutes tes sessions sont fermées. Pour revenir : le guide du clan sur Discord.");
}
function fin(titre, texte) {
  etat.session = "expiree";
  try { sessionStorage.clear(); } catch (e) { /* rien */ }
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
  $("#pancartes").hidden = true;
  remplacer($("#entete-outils"));
  remplacer($("#pied"));
  remplacer($("#bandeaux"));
  remplacer($("#contenu"), h("div", { classe: "adieu" }, h("span", { classe: "attente-boussole", "aria-hidden": "true" }), h("h1", {}, titre), h("p", {}, texte)));
  document.title = T("titre", "L'Équipage");
}
ecouter("session", () => {
  if (document.querySelector(".adieu")) return;
  fin(T("retire.titre", "Accès retiré"), T("retire.texte", "Ce site est réservé à l'équipage. Pour revenir : le guide du clan sur Discord."));
});

demarrer();
