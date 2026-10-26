// equipage.js — le site de l'équipage (26/10/2026) : démarrage, en-tête, trois onglets (Accueil · L'équipage ·
// Ma fiche), session et déconnexion. Pour les membres du rôle du clan : LECTURE SEULE, aucun bouton d'action. Pour le
// fondateur et la direction : le mode édition de l'accueil (equipage_accueil.js).
// Rien du site de la direction n'est chargé ici : ni ses données, ni sa file hors ligne, ni son service worker.

import { h, icone, $, BASE, chargerSprite, completerSprite, remplacer, ajouter, sansEmoji, srcSure, date, contient, nombre, compte, reduit } from "./dom.js";
import { etat, ecouter, filtres, poserLibelles } from "./noyau.js";
import { poster } from "./api.js";
import { bouton, boutonIcone, menu, confirmer, toast, titreRubrique, vide, bandeau, groupe, paginer, recherche, liste } from "./ui.js";
import { affiche, nomAffiche, metiersDe, gradeDe, insigneImage } from "./affiche.js";
import { typeMetier, typesTries, elementsDe, element } from "./donnees.js";
import { E, T, lire, ouvrirAffiche, detailsAffiche, catalogue, afficheParId, rangPrime } from "./equipage_commun.js";
import * as accueil from "./equipage_accueil.js";

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
  "carte", "boussole", "ancre", "crane", "droite", "synchro", "annonces", "evenements", "equipage", "longue_vue", "coffre", "sabre"];
const ONGLETS = [
  { cle: "accueil", icone: "navire", titre: () => T("onglet.accueil", "Accueil"), sous: () => T("onglet.accueil.sous", "Le pont du navire"),
    phrase: () => T("accueil.phrase", "Les nouvelles du bord, les sorties en mer et l'équipage en chiffres.") },
  { cle: "equipage", icone: "affiches", titre: () => T("onglet.equipage", "L'équipage"), sous: () => T("onglet.equipage.sous", "Toutes les affiches"),
    phrase: () => T("equipage.phrase", "Chaque pirate du clan et son avis de recherche, rangés par métier.") },
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
  const outils = [];
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

// ═══ L'ÉQUIPAGE : toutes les affiches, par métier ═══════════════════════════
function rendreEquipage(corps) {
  const eq = E.equipage;
  if (!eq) { remplacer(corps, vide("Les affiches ne se sont pas chargées", "Recharge la page dans un instant.", "attention")); return; }
  const cat = catalogue();
  const f = filtres("site-equipage", { q: "", metier: "", race: "", faction: "" });
  const tm = typeMetier(cat);
  const parCle = (cle, motif) => typesTries(cat).find((t) => t.cle === cle) || typesTries(cat).find((t) => motif.test(t.nom || "")) || null;
  const tr = parCle("race", /\braces?\b/i), tf = parCle("faction", /\bfactions?\b/i);
  const toutes = eq.affiches || [];
  const de = (a, t) => (t ? (a.attributs && a.attributs[t.cle]) || [] : []);
  const options = (t, tous) => {
    if (!t) return null;
    const n = new Map();
    for (const a of toutes) for (const k of de(a, t)) n.set(k, (n.get(k) || 0) + 1);
    return [{ v: "", l: tous }, ...elementsDe(cat, t.cle).filter((e) => n.has(e.cle)).map((e) => ({ v: e.cle, l: e.nom + " (" + n.get(e.cle) + ")", img: srcSure(e.icone) || null }))];
  };
  const resultats = h("div", { classe: "pile" });
  const resume = h("p", { classe: "aide" });
  const changer = () => { for (const k of Object.keys(etat.pages)) if (k.startsWith("eq-")) delete etat.pages[k]; maj(); };
  const filtresListes = [[tm, "metier", "Métier", "Tous les métiers"], [tr, "race", "Race", "Toutes les races"], [tf, "faction", "Faction", "Toutes les factions"]]
    .map(([t, k, lib, tous]) => {
      const opts = options(t, tous);
      if (!opts || opts.length < 2) { f[k] = ""; return null; }
      if (f[k] && !opts.some((o) => o.v === f[k])) f[k] = "";
      return liste({ valeur: f[k], options: opts, label: lib, changer: (v) => { f[k] = v; changer(); } });
    });
  ajouter(corps, [h("div", { classe: "outils" }, recherche(f.q, "Nom, surnom, métier…", (q) => { f.q = q; changer(); }), ...filtresListes), resume, resultats]);
  const texte = (a) => [nomAffiche(a), a.surnom, a.membre && a.membre.nom, gradeDe(a, cat), ...Object.entries(a.attributs || {}).flatMap(([t, ks]) => ks.map((k) => (element(cat, t, k) || {}).nom || k))].join(" ");
  function maj() {
    const l = toutes.filter((a) => contient(texte(a), f.q) && (!f.metier || de(a, tm).includes(f.metier))
      && (!f.race || de(a, tr).includes(f.race)) && (!f.faction || de(a, tf).includes(f.faction)));
    const carte = (a) => h("div", { classe: "affiche-case" + (eq.moi && String(a.id) === String(eq.moi) ? " la-mienne" : "") },
      affiche(a, cat, { taille: "mini", clic: () => ouvrirAffiche(a.id) }),
      eq.moi && String(a.id) === String(eq.moi) ? h("span", { classe: "ruban-mienne" }, "Ma fiche") : null);
    remplacer(resume, l.length === toutes.length ? compte(toutes.length, "affiche") + " au mur. Touche une affiche pour la voir en grand."
      : compte(l.length, "affiche") + " sur " + nombre(toutes.length) + " pour ce filtre.");
    if (!toutes.length) { remplacer(resultats, vide("Aucune affiche pour le moment", "La direction prépare les avis de recherche de l'équipage.", "affiches")); return; }
    if (!l.length) { remplacer(resultats, vide("Personne ici", "Change le filtre ou la recherche.", "rechercher")); return; }
    const groupes = new Map();
    for (const a of l) for (const k of (metiersDe(a, cat).length ? metiersDe(a, cat) : ["__aucun"])) {
      if (f.metier && k !== f.metier && k !== "__aucun") continue;
      if (!groupes.has(k)) groupes.set(k, []);
      groupes.get(k).push(a);
    }
    const ordre = tm ? elementsDe(cat, tm.cle).map((e) => e.cle) : [];
    const cles = [...groupes.keys()].sort((a, b) => (a === "__aucun") - (b === "__aucun") || ((ordre.indexOf(a) + 1 || 999) - (ordre.indexOf(b) + 1 || 999)) || a.localeCompare(b));
    //  Rien à défiler sans fin : au départ, le premier métier ouvert, et les suivants tant que le mur ouvert garde au plus
    //  douze affiches (un petit équipage reste tout ouvert) ; au téléphone (deux par rangée), « Voir plus » par 8.
    const pas = matchMedia("(max-width: 519px)").matches ? 8 : 18;
    let ouvertes = 0;
    remplacer(resultats, ...cles.map((k, i) => {
      const e = tm && k !== "__aucun" ? element(cat, tm.cle, k) : null;
      const n = groupes.get(k).length;
      const defaut = i === 0 || ouvertes + n <= 12;
      if (defaut) ouvertes += n;
      return groupe({ titre: k === "__aucun" ? "Sans métier" : e ? e.nom : sansEmoji(k), compte: n,
        visuel: e ? insigneImage(e, "groupe-visuel") : null, icone: e ? null : "drapeau", cle: "eq-g-" + k,
        ouvert: f.q || f.metier ? true : undefined, defaut },
      () => paginer("eq-" + k, groupes.get(k), carte, { classe: "grille affiches", pas }));
    }));
  }
  maj();
}

// ═══ MA FICHE ════════════════════════════════════════════════════════════
function rendreFiche(corps) {
  const eq = E.equipage;
  const a = eq && eq.moi ? afficheParId(eq.moi) : null;
  if (!a) {
    ajouter(corps, [vide(T("fiche.vide.titre", "Pas encore d'affiche"), T("fiche.vide.texte", "Demande à la direction : elle crée ton avis de recherche."), "affiches"),
      eq && (eq.affiches || []).length ? h("p", { classe: "aide centre" }, h("a", { href: "#equipage" }, "Voir les affiches de l'équipage")) : null]);
    return;
  }
  const rang = rangPrime(a);
  ajouter(corps, [h("div", { classe: "affiche-grand fiche-perso" },
    h("div", { classe: "affiche-grand-mur" }, affiche(a, catalogue(), { taille: "grande" })),
    h("div", { classe: "pile" },
      rang ? h("p", { classe: "fiche-rang" }, icone("prime"), h("span", {}, rang === 1 ? "La plus haute prime de l'équipage." : "La " + rang + "e prime de l'équipage, sur " + nombre((eq.affiches || []).length) + ".")) : null,
      detailsAffiche(a),
      h("p", { classe: "aide" }, "Une erreur sur ton affiche ? Demande à la direction : elle seule la modifie.")))]);
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
