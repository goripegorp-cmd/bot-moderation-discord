// recherche.js — la recherche universelle, dans l'en-tête (Ctrl+K ou « / » au clavier, la loupe au téléphone) :
// membres (connus du site, puis tout le serveur), tickets (#numéro), candidatures, affiches, publications du clan,
// questions de la banque, éléments du catalogue, rubriques. Les résultats sont regroupés ; les flèches choisissent,
// Entrée ouvre ; chaque résultat ouvre directement ce qu'il désigne.

import { h, icone, $, norm, sansEmoji, depuis, retarder, remplacer, ajouter, dans, maintenant } from "./dom.js";
import { etat, P, CATEGORIES, aller, filtres, enLigne, ecouter, emettre, peutAgir } from "./noyau.js";
import { lire } from "./api.js";
import { charger, vue as vueJeu } from "./donnees.js";
import { pancarte, avatar, nomDe, idUnique } from "./ui.js";
import { ouvrirFiche, ouvrirConversation, propre, etapeCandidature, ETAPES_CANDIDATURE } from "./fiche.js";
import { nomAffiche, insigneImage } from "./affiche.js";
import { titreNav, estRestreint, pastilleIcone } from "./rangement.js";
import { ouvrirPublication, NOMS_PUBLICATIONS } from "./annonces.js";
import { ouvrirElement } from "./capitainerie.js";

const PAR_GROUPE = 6;
// Les sous-onglets, trouvés comme les rubriques.
const SOUS = [["port", "salons", "questions", "Questions des salons"], ["port", "salons", "idees", "Idées des membres"],
  ["port", "salons", "sondages", "Sondages"], ["port", "salons", "entraide", "Entraide et trade"], ["port", "salons", "annonces", "Annonces du serveur"],
  ["port", "salons", "droits", "Droits des salons"], ["capitainerie", "recrutement", "questions", "Banque de questions du recrutement"],
  ["capitainerie", "recrutement", "candidatures", "Candidatures décidées"], ["equipage", "annonces", "brouillons", "Brouillons d'annonces"],
  ["equipage", "annonces", "a-venir", "Événements à venir"], ["equipage", "annonces", "publiees", "Annonces publiées"],
  ["equipage", "annonces", "passes", "Publications passées"]];

// ─── L'en-tête ──────────────────────────────────────────────────────────────
const estSaisie = (el) => !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
let ouverte = null;

/** Le champ de l'en-tête (au milieu ; la loupe seule au téléphone) et les raccourcis clavier. Une fois. */
export function monterRecherche() {
  const planche = $("#entete .planche"), outils = $("#entete-outils");
  if (!planche || $("#recherche-entete")) return;
  const b = h("button", { classe: "recherche-entete", id: "recherche-entete", type: "button", "aria-label": "Rechercher (Ctrl+K)",
    "aria-keyshortcuts": "Control+K Meta+K /", "aria-haspopup": "dialog", onclick: () => ouvrirRecherche() },
  icone("rechercher"), h("span", { classe: "recherche-entete-texte" }, "Chercher un membre, un ticket, une affiche…"),
  h("kbd", { classe: "recherche-touche", "aria-hidden": "true" }, "Ctrl K"));
  planche.insertBefore(b, outils);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); ouvrirRecherche(); }
    else if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey && !estSaisie(document.activeElement) && !document.querySelector("dialog[open]")) { e.preventDefault(); ouvrirRecherche(); }
  });
}
ecouter("recherche:ouvrir", (q) => ouvrirRecherche(typeof q === "string" ? q : ""));

// ─── Les index ──────────────────────────────────────────────────────────────
/** Chaque mot de la recherche doit se trouver dans le texte ; 0 = tout le texte, 1 = au début, 2 = au début d'un mot,
 *  3 = ailleurs ; -1 : absent. */
function score(texte, mots) {
  const t = " " + norm(texte);
  let pire = 0;
  for (const m of mots) {
    const i = t.indexOf(m);
    if (i < 0) return -1;
    const s = t.trim() === m ? 0 : i === 1 ? 1 : /[\s'’\-·#@(]/.test(t[i - 1]) ? 2 : 3;
    pire = Math.max(pire, s);
  }
  return pire;
}
function trouver(liste, texte, mots, max) {
  const out = [];
  for (const x of liste) { const s = score(texte(x), mots); if (s >= 0) out.push([s, x]); }
  out.sort((a, b) => a[0] - b[0]);
  return { total: out.length, l: out.slice(0, max).map(([, x]) => x) };
}
function personnes() {
  const d = etat.d, m = new Map();
  const mettre = (p, marque) => {
    if (!p || !p.id) return;
    const id = String(p.id), x = m.get(id) || { id, nom: "", pseudo: "", avatar: "", marques: new Set() };
    if (!x.nom || x.nom === "Membre parti") x.nom = p.nom || x.nom;
    x.pseudo = x.pseudo || p.pseudo || "";
    x.avatar = x.avatar || p.avatar || "";
    if (marque) x.marques.add(marque);
    m.set(id, x);
  };
  if (!d) return [];
  for (const p of Object.values(d.personnes || {})) mettre(p);
  for (const p of (d.clan && d.clan.membres) || []) mettre(p, "Clan");
  for (const p of (d.clan && d.clan.direction) || []) mettre(p, "Direction");
  for (const p of d.en_cours || []) mettre(p, "Candidat");
  for (const p of d.tickets.ouverts || []) mettre(p);
  for (const id of d.a_part || []) mettre(P(id), "Direction");
  return [...m.values()].filter((x) => x.nom && x.nom !== "Membre parti");
}

/** Les résultats, groupe par groupe : [{ cle, titre, total, items: [{ titre, sous, visuel, ouvrir }] }]. */
function chercher(brut) {
  const q = norm(brut.trim()), mots = q.split(/\s+/).filter(Boolean);
  const d = etat.d, groupes = [];
  const g = (cle, titre, r, fn) => { if (r.l.length) groupes.push({ cle, titre, total: r.total, items: r.l.map(fn) }); };
  const numero = /^#?\d{1,7}$/.test(q) ? Number(q.replace("#", "")) : null;
  if (mots.length && d) {
    // Les membres
    g("membres", "Membres", trouver(personnes(), (x) => x.nom + " " + x.pseudo + " " + x.id, mots, 8), (x) => ({
      titre: sansEmoji(x.nom) || x.pseudo, sous: [x.pseudo ? "@" + x.pseudo : "", ...x.marques, estRestreint(x.id) ? "Restreint" : ""].filter(Boolean).join(" · ") || "Membre",
      visuel: () => avatar(x, "p"), ouvrir: () => ouvrirFiche(x.id), cle: "m" + x.id }));
    // Les tickets (un numéro : celui-là d'abord)
    const tickets = [...(d.tickets.ouverts || []).map((t) => Object.assign({ ouvertNow: true, p: t }, t)), ...(d.tickets.fermes || []).map((t) => Object.assign({ p: P(t.id) }, t))];
    const rt = numero !== null ? { l: tickets.filter((t) => t.ticket === numero), total: 0 } : trouver(tickets, (t) => "#" + t.ticket + " " + nomDe(t.p) + " " + propre(t.type) + " " + (t.motif || ""), mots, PAR_GROUPE);
    if (numero !== null) rt.total = rt.l.length;
    g("tickets", "Tickets", rt, (t) => ({
      titre: "Ticket #" + t.ticket + " · " + nomDe(t.p), sous: propre(t.type) + (t.ouvertNow ? " · ouvert " + depuis(t.ouvert) : " · fermé " + depuis(t.ferme || t.ouvert)) + (t.motif ? " · " + t.motif : ""),
      visuel: () => pastilleIcone("tickets", t.ouvertNow ? "#a8641c" : "#4a5560"), ouvrir: () => ouvrirConversation(t.ticket, "Ticket #" + t.ticket + " · " + nomDe(t.p)), cle: "t" + t.ticket }));
    // Les candidatures en cours
    g("candidatures", "Candidatures", trouver(d.en_cours || [], (c) => nomDe(c) + " " + (c.pseudo || "") + " #" + c.ticket + " candidature", mots, PAR_GROUPE), (c) => ({
      titre: "Candidature de " + nomDe(c), sous: "Ticket #" + c.ticket + " · " + (ETAPES_CANDIDATURE[etapeCandidature(c)] || ["En cours"])[0],
      visuel: () => avatar(c, "p"), ouvrir: () => emettre("dossier:ouvrir", c.ticket), cle: "c" + c.ticket }));
  }
  if (mots.length) {
    const aff = vueJeu("affiches");
    if (aff && !aff.erreur) g("affiches", "Affiches", trouver((aff.affiches || []).filter((a) => !a.retire_le), (a) => [nomAffiche(a), a.surnom, a.membre && a.membre.nom, a.roblox && a.roblox.nom].join(" "), mots, PAR_GROUPE), (a) => ({
      titre: "Affiche de " + nomAffiche(a), sous: [a.surnom ? "« " + sansEmoji(a.surnom) + " »" : "", a.membre && a.membre.nom ? sansEmoji(a.membre.nom) : ""].filter(Boolean).join(" · ") || "Affiche",
      visuel: () => pastilleIcone("affiches", "#7a4b2a"), ouvrir: () => emettre("affiche:ouvrir", a.id), cle: "a" + a.id }));
    const E = vueJeu("evenements");
    if (E && !E.erreur) {
      const tous = [...(E.brouillons || []).map((x) => ["brouillons", x]), ...(E.a_venir || []).map((x) => ["a-venir", x]), ...(E.publiees || []).map((x) => ["publiees", x]), ...(E.passes || []).map((x) => ["passes", x])];
      g("publications", "Annonces et événements", trouver(tous, ([, x]) => (x.titre || "") + " " + (NOMS_PUBLICATIONS[x.type] || ""), mots, PAR_GROUPE), ([ou, x]) => ({
        titre: x.titre || NOMS_PUBLICATIONS[x.type] || "Publication", sous: (NOMS_PUBLICATIONS[x.type] || "Publication") + " · " + (ou === "brouillons" ? "brouillon" : ou === "a-venir" ? (x.quand && x.quand > maintenant() ? dans(x.quand) : "à venir") : ou === "publiees" ? "en ligne" : "passé"),
        visuel: () => pastilleIcone(x.type === "evenement" ? "calendrier" : "cloche", "#1f4e5a"), ouvrir: () => ouvrirPublication(x, ou), cle: "e" + x.id }));
    }
    const B = vueJeu("banque");
    if (B && !B.erreur) g("banque", "Questions de la banque", trouver((B.questions || []).filter((x) => !x.retiree), (x) => (x.question || x.texte || "") + " " + (x.reponse || ""), mots, PAR_GROUPE), (x) => ({
      titre: x.question || x.texte || "Question", sous: "Réponse : " + (x.reponse || "—") + ((x.statut || "a_verifier") === "a_verifier" ? " · à vérifier" : ""),
      visuel: () => pastilleIcone("parchemin", "#7a5a22"), ouvrir: () => ouvrirQuestion(x), cle: "q" + x.id }));
    const cat = vueJeu("catalogue");
    if (cat && !cat.erreur) {
      const types = new Map((cat.types || []).map((t) => [t.cle, sansEmoji(t.nom)]));
      g("catalogue", "Catalogue RELL Seas", trouver(cat.elements || [], (e) => [e.nom, e.nom_en, e.categorie, types.get(e.type)].join(" "), mots, PAR_GROUPE), (e) => ({
        titre: e.nom, sous: [types.get(e.type) || e.type, e.nom_en, e.actif === false ? "retiré" : e.statut === "a_verifier" ? "à vérifier" : ""].filter(Boolean).join(" · "),
        visuel: () => insigneImage(e, "rech-insigne"), ouvrir: () => ouvrirElementCatalogue(e), cle: "k" + e.type + ":" + e.cle }));
    }
  }
  // Les rubriques (et, sans recherche, toutes : la recherche sert aussi de sommaire)
  const rubs = [];
  for (const c of CATEGORIES) for (const r of c.rubriques) rubs.push({ titre: titreNav(r), sous: titreNav(c), texte: titreNav(c) + " " + titreNav(r) + " " + (r.phrase || ""), cat: c.cle, rub: r.cle, icone: r.icone });
  for (const [cat, rub, sous, titre] of SOUS) rubs.push({ titre, sous: titreNav(CATEGORIES.find((c) => c.cle === cat) || {}), texte: titre, cat, rub, sous_: sous, icone: "droite" });
  const rr = mots.length ? trouver(rubs, (x) => x.texte, mots, PAR_GROUPE) : { l: rubs.filter((x) => !x.sous_), total: rubs.length };
  g("rubriques", mots.length ? "Rubriques" : "Aller à", rr, (x) => ({ titre: x.titre, sous: x.sous, visuel: () => pastilleIcone(x.icone, "#5a4330"),
    ouvrir: () => aller(x.cat, x.rub, x.sous_ || ""), cle: "r" + x.cat + x.rub + (x.sous_ || "") }));
  if (numero !== null) groupes.sort((a, b) => (b.cle === "tickets") - (a.cle === "tickets"));
  return groupes;
}

// Ouvrir ce qui n'a pas de fenêtre à soi : la bonne page, filtrée sur l'élément.
function ouvrirQuestion(x) {
  const f = filtres("questionnaire", {});
  Object.assign(f, { q: norm(String(x.question || x.texte || "").trim()).slice(0, 120), theme: "tous", diff: "0", statut: "tous", actives: "toutes" });
  aller("capitainerie", "recrutement", "questions");
}
function ouvrirElementCatalogue(e) {
  if (peutAgir()) { ouvrirElement(e); return; }
  const f = filtres("catalogue", {});
  Object.assign(f, { q: norm(e.nom), type: e.type, statut: "tous", movie3: false, inactifs: e.actif === false });
  aller("capitainerie", "catalogue");
}

// ─── La fenêtre ─────────────────────────────────────────────────────────────
/** Ouvre la recherche (ou y revient si elle est déjà ouverte). */
export function ouvrirRecherche(depart = "") {
  // Déjà ouverte : le champ reprend le focus. Fermée sans passer par la pancarte (dialog.close() direct) : on l'oublie.
  if (ouverte && !ouverte.p.fermee() && ouverte.p.dlg.open) { ouverte.champ.focus(); return; }
  ouverte = null;
  const idListe = idUnique("rech-liste");
  const p = pancarte({ titre: "Rechercher", sous: "Un membre, un ticket, une affiche, une question, un élément du jeu, une rubrique.", icone: "rechercher", taille: "large recherche-fenetre",
    surFermer: () => { stopJeu(); if (ouverte && ouverte.p === p) ouverte = null; } });
  const champ = h("input", { type: "search", classe: "saisie recherche-champ", role: "combobox", "aria-expanded": "true", "aria-controls": idListe,
    "aria-autocomplete": "list", "aria-label": "Rechercher", placeholder: "Nom, #numéro de ticket, affiche, question…", autocomplete: "off", spellcheck: "false", enterkeyhint: "go" });
  champ.value = depart;
  const liste = h("div", { classe: "recherche-resultats", role: "listbox", id: idListe, "aria-label": "Résultats" });
  const etatServeur = h("p", { classe: "aide recherche-serveur", "aria-live": "polite" });
  ajouter(p.corps, [h("div", { classe: "recherche-tete" }, champ), liste, etatServeur]);
  ajouter(p.pied, [h("p", { classe: "recherche-aide" }, h("kbd", {}, "↑"), h("kbd", {}, "↓"), " choisir · ", h("kbd", {}, "Entrée"), " ouvrir · ", h("kbd", {}, "Échap"), " fermer")]);
  let options = [], actif = -1, jeton = 0, serveur = { q: "", membres: [] };
  const choisir = (i) => {   // -1 : aucun résultat choisi
    actif = i < 0 || !options.length ? -1 : i % options.length;
    options.forEach((o, k) => { o.el.setAttribute("aria-selected", String(k === actif)); o.el.classList.toggle("actif", k === actif); });
    if (actif >= 0) { champ.setAttribute("aria-activedescendant", options[actif].el.id); options[actif].el.scrollIntoView({ block: "nearest" }); }
    else champ.removeAttribute("aria-activedescendant");
  };
  const activer = async (o) => { if (!o) return; await p.fermer(); o.ouvrir(); };
  const dessiner = (enHaut) => {
    const groupes = chercher(champ.value);
    const q = norm(champ.value.trim());
    const deja = new Set(groupes.filter((x) => x.cle === "membres").flatMap((x) => x.items.map((i) => i.cle)));
    if (serveur.q === q && serveur.membres.length) {
      const l = serveur.membres.filter((m) => !deja.has("m" + m.id)).slice(0, 8);
      // juste après les membres connus du site
      if (l.length) groupes.splice(groupes.findIndex((x) => x.cle === "membres") + 1, 0, {
        cle: "serveur", titre: "Dans tout le serveur", total: l.length, items: l.map((m) => ({ titre: sansEmoji(m.nom) || m.pseudo, sous: [m.pseudo ? "@" + m.pseudo : "", m.clan ? "Clan" : "", m.a_part ? "Direction" : "", estRestreint(m.id) ? "Restreint" : ""].filter(Boolean).join(" · ") || "Membre du serveur",
          visuel: () => avatar(m, "p"), ouvrir: () => ouvrirFiche(String(m.id)), cle: "s" + m.id })) });
    }
    options = [];
    const blocs = groupes.map((gr) => h("div", { classe: "rech-groupe", role: "group", "aria-label": gr.titre },
      h("div", { classe: "rech-groupe-titre", "aria-hidden": "true" }, h("span", {}, gr.titre), gr.total > gr.items.length ? h("span", { classe: "rech-plus" }, gr.items.length + " sur " + gr.total) : null),
      gr.items.map((it) => {
        const el = h("div", { classe: "rech-option", role: "option", id: idUnique("rech"), "aria-selected": "false", onclick: () => activer(it) },
          h("span", { classe: "rech-visuel" }, it.visuel()), h("span", { classe: "rech-texte" }, h("span", { classe: "rech-titre", title: it.titre }, it.titre), it.sous ? h("span", { classe: "rech-sous", title: it.sous }, it.sous) : null),
          icone("droite", "rech-fleche"));
        el.addEventListener("pointermove", () => { const k = options.findIndex((o) => o.el === el); if (k !== actif) choisir(k); });
        options.push({ el, ouvrir: it.ouvrir });
        return el;
      })));
    remplacer(liste, ...(blocs.length ? blocs : [h("div", { classe: "vide rech-vide" }, icone("boussole"), h("b", {}, "Rien trouvé"), h("p", {}, "Essaie un autre nom, un numéro de ticket (#12) ou un mot du titre."))]));
    if (enHaut) p.corps.scrollTop = 0;
    choisir(q ? 0 : -1);
  };
  const demanderServeur = retarder(async () => {
    const q = norm(champ.value.trim());
    if (q.length < 2 || /^#?\d+$/.test(q)) { etatServeur.textContent = ""; return; }
    if (!enLigne()) { etatServeur.textContent = "Hors ligne : la recherche dans tout le serveur reviendra avec la connexion."; return; }
    const n = ++jeton;
    etatServeur.textContent = "Recherche dans tout le serveur…";
    const r = await lire("recherche", { q: champ.value.trim().slice(0, 64) });
    if (n !== jeton || p.fermee()) return;
    etatServeur.textContent = r.ok ? "" : "La recherche dans tout le serveur ne répond pas pour le moment.";
    serveur = { q, membres: r.ok ? (r.donnees.membres || []) : [] };
    dessiner();
  }, 280);
  champ.addEventListener("input", () => { dessiner(true); demanderServeur(); });
  champ.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); choisir(actif + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); choisir(actif <= 0 ? options.length - 1 : actif - 1); }
    else if (e.key === "Enter") { e.preventDefault(); activer(options[actif >= 0 ? actif : 0]); }
  });
  // Les jeux de données de la recherche (affiches, publications, banque, catalogue) : chargés à l'ouverture, la liste
  // se redessine à leur arrivée.
  const stopJeu = ecouter("jeu", () => { if (!p.fermee()) dessiner(); });
  for (const nom of ["affiches", "evenements", "banque", "catalogue"]) charger(nom);
  ouverte = { p, champ };
  dessiner();
  if (depart) demanderServeur();
  requestAnimationFrame(() => { champ.focus(); champ.select(); });
}
