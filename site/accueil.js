// accueil.js — « Ce qui t'attend », la première page : UNE liste, du plus urgent au moins urgent, de tout ce qui demande
// une action — chaque ligne est une phrase et UN bouton qui fait l'action ou ouvre exactement le bon endroit ; « Rien ne
// t'attend » quand tout est fait. Puis les grands raccourcis par tâche.
// Les sources : les données du serveur (alertes, tickets, questions, candidatures, clan, idées), la file d'envoi, et
// les jeux chargés à la demande (publications du clan, banque de questions, catalogue, rôles des métiers, affiches).
// 27/10/2026 : l'accueil a absorbé l'Aperçu du Port — ses chiffres en tuiles au-dessus de la liste et ses graphiques
// dans « Tendances », en bas (« Tout afficher » : le mode simple les cache, comme partout) ; sa liste « À traiter
// maintenant » était celle-ci.

import { h, icone, depuis, dans, maintenant, remplacer, quantite, ajouter, date, cleJour, duree, nombre } from "./dom.js";
import { etat, P, peutAgir, aller, emettre, filtres, CATEGORIES } from "./noyau.js";
import { charger, vue as vueJeu } from "./donnees.js";
import * as HL from "./hors_ligne.js";
import { avatar, nomDe, vide, section, tuile, tuiles, groupe, barres, barresH, ENCRES } from "./ui.js";
import { ouvrirFiche, etapeCandidature, chargerSuivi, nomSalon, propre } from "./fiche.js";
import { insignes } from "./affiche.js";
import { ligne, pastilleIcone } from "./rangement.js";
import { commencer, ouvrirPublication, NOMS_PUBLICATIONS } from "./annonces.js";
import { indisponible } from "./discord.js";
import { editer as editerAffiche } from "./capitainerie.js";
import { avecVerrou } from "./direct.js";

const HEURE = 3600, JOUR = 86400;
// La priorité : son nom (lu par les lecteurs d'écran) et sa teinte (le filet à gauche de la ligne).
const PRIORITES = { 1: ["Urgent", "#8e2a24"], 2: ["À faire", "#a8641c"], 3: ["À voir", "#1f4e5a"], 4: ["Quand tu as le temps", "#6e553f"] };
const PAR_SORTE = 3;   // au-delà, une ligne « et N autres » ouvre la bonne page
const JEUX = ["evenements", "banque", "catalogue", "metiers_reglages", "affiches"];

const rubriqueExiste = (cat, rub) => CATEGORIES.some((c) => c.cle === cat && c.rubriques.some((r) => r.cle === rub));

// ─── Ce qui attend ──────────────────────────────────────────────────────────
/** Tout ce qui demande une action : [{ sorte, prio (1 à 4), phrase, sous, quand, visuel, action: { libelle, icone,
 *  faire | href } }], du plus urgent au moins urgent (à priorité égale, ce qui attend depuis le plus longtemps). */
export function aFaire() {
  const d = etat.d, n = maintenant(), out = [];
  const pousser = (x) => out.push(x);
  const regler = HL.enConflit().length + HL.enRefus().length;
  if (regler) pousser({ sorte: "file", prio: 1, icone: "attention", phrase: quantite(regler, "modification(s) à régler"), sous: "Changée(s) ailleurs ou refusée(s) par le serveur : choisis la bonne version.",
    action: { libelle: "Régler", icone: "synchro", faire: () => emettre("file:ouvrir") } });
  if (d) {
    for (const a of d.alertes || []) {
      const p = P(a.id);
      pousser({ sorte: "alerte", prio: 1, personne: p, phrase: "Alerte : " + nomDe(p) + " cumule du grave", sous: quantite(a.incidents, "incident(s)") + " · " + quantite(a.points, "point(s)") + " en 24 h",
        quand: a.maj_le || a.ouverte_le, action: { libelle: "Voir la fiche", icone: "oeil", faire: () => ouvrirFiche(a.id) } });
    }
    const candidatures = new Set();
    for (const c of d.en_cours || []) {
      candidatures.add(c.ticket);
      const e = etapeCandidature(c);
      if (e === "corriger") pousser({ sorte: "corriger", prio: 2, personne: c, phrase: nomDe(c) + " : réponses à corriger", sous: "Candidature · ticket #" + c.ticket + " · étape 2",
        quand: c.ouvert, objet: "dossier:" + c.ticket, action: { libelle: "Corriger", icone: "plume", faire: () => emettre("dossier:ouvrir", c.ticket) } });
      else if (e === "decider") pousser({ sorte: "decider", prio: c.ouvert && n - c.ouvert > 2 * JOUR ? 1 : 2, personne: c, phrase: nomDe(c) + " : étape 1 à décider",
        sous: "Candidature · ticket #" + c.ticket + (c.pris_par ? " · prise par " + propre(c.pris_par) : " · pas encore prise"),
        quand: c.ouvert, objet: "dossier:" + c.ticket, action: { libelle: "Décider", icone: "candidatures", faire: () => emettre("dossier:ouvrir", c.ticket) } });
    }
    for (const m of (d.clan && d.clan.membres) || []) {
      if (!m.rappel || m.rappel.statut !== "echu") continue;
      pousser({ sorte: "inactif", prio: 2, personne: m, phrase: nomDe(m) + " : toujours inactif après le rappel", sous: "Prévenu le " + date(m.rappel.envoye_le) + " · le garder ou le retirer du clan",
        quand: m.rappel.envoye_le, action: { libelle: "Décider", icone: "equipage", faire: () => aller("equipage", "membres") } });
    }
    for (const t of d.tickets.ouverts || []) {
      if (t.pris_par || !t.ouvert || n - t.ouvert < 6 * HEURE || candidatures.has(t.ticket)) continue;
      pousser({ sorte: "ticket", prio: n - t.ouvert > JOUR ? 2 : 3, personne: t, phrase: "Ticket #" + t.ticket + " de " + nomDe(t) + " : personne ne l'a pris",
        sous: propre(t.type) + " · ouvert " + depuis(t.ouvert), quand: t.ouvert,
        action: t.salon ? { libelle: "Ouvrir sur Discord", icone: "discord", href: t.salon } : { libelle: "Voir", icone: "tickets", faire: () => aller("port", "tickets", t.rellseas ? "clan" : "normaux") } });
    }
    for (const q of (d.questions && d.questions.liste) || []) {
      if (q.statut !== "ouverte" || n - q.quand < 30 * 60) continue;
      const p = P(q.id);
      pousser({ sorte: "question", prio: 3, personne: p, phrase: "Question de " + nomDe(p) + " sans réponse", sous: nomSalon(q.salon) + " · « " + q.texte + " »", quand: q.quand,
        action: q.message ? { libelle: "Répondre", icone: "discord", href: q.message } : { libelle: "Voir", icone: "salons", faire: () => aller("port", "salons", "questions") } });
    }
    const idees = ((d.suggestions && d.suggestions.liste) || []).filter((x) => !x.retire_le && x.statut === "attente");
    if (idees.length) pousser({ sorte: "idees", prio: 4, icone: "etoile", phrase: idees.length > 1 ? idees.length + " idées attendent ta réponse" : "Une idée attend ta réponse",
      sous: idees.slice(0, 3).map((x) => "« " + x.titre + " »").join(" · "), quand: Math.min(...idees.map((x) => x.cree || n)),
      action: { libelle: "Répondre", icone: "plume", faire: () => aller("port", "salons", "idees") } });
  }
  // Les publications du clan : les événements proches sans réponse, les brouillons pas encore publiés.
  const E = vueJeu("evenements");
  if (E && !E.erreur) {
    for (const el of E.a_venir || []) {
      const v = el.valeurs || {}, r = el.reponses || {};
      if (el.type !== "evenement" || el.statut !== "publie" || el.phase === "en_cours" || el.phase === "termine" || !el.quand) continue;
      if (el.quand - n > 2 * JOUR || el.quand < n || !v.reponses || (r.disponibles || 0) > 0) continue;
      pousser({ sorte: "evenement", prio: 3, icone: "calendrier", phrase: "« " + (el.titre || "Événement") + " » : personne n'a encore répondu", sous: "Commence " + dans(el.quand), quand: el.publie || el.quand,
        action: { libelle: "Voir", icone: "calendrier", faire: () => aller("equipage", "annonces", "a-venir") } });
    }
    for (const el of E.brouillons || []) pousser({ sorte: "brouillon", prio: 4, icone: "parchemin", phrase: "Brouillon « " + (el.titre || NOMS_PUBLICATIONS[el.type] || "Sans titre") + " » pas encore publié",
      sous: (NOMS_PUBLICATIONS[el.type] || "Publication") + " · modifié " + depuis(el.maj || n), quand: el.maj, objet: el.id ? "brouillon:" + el.id : null,
      action: { libelle: "Ouvrir", icone: "plume", faire: () => ouvrirPublication(el, "brouillons") } });
  }
  // Les rôles des métiers : ce qui les empêche de marcher.
  const M = vueJeu("metiers_reglages");
  if (M && !M.erreur) {
    const roles = (texte, sous) => pousser({ sorte: "roles", prio: 2, icone: "roles", phrase: texte, sous, action: { libelle: "Régler", icone: "roles", faire: () => aller("capitainerie", "roles") } });
    if (M.actif === false) roles("Rôles des métiers en sommeil", "Le rôle du clan n'est pas réglé : rien n'est créé, donné ni retiré.");
    else if (M.gestion === false) roles("Le bot ne peut pas gérer les rôles des métiers", "Il lui manque la permission « Gérer les rôles ».");
    const details = (M.rattaches_details || []).filter((x) => x && (!x.existe || !x.attribuable));
    if (details.length) roles(details.length > 1 ? details.length + " rôles rattachés au clan sont à revoir" : "Un rôle rattaché au clan est à revoir", "Il n'existe plus, ou le bot ne peut pas le retirer.");
  }
  // Ce qui est « à vérifier » : la banque de questions, le catalogue, les insignes des affiches.
  const B = vueJeu("banque");
  if (B && !B.erreur) {
    const nb = (B.questions || []).filter((q) => !q.retiree && (q.statut || "a_verifier") === "a_verifier").length;
    if (nb) pousser({ sorte: "banque", prio: 4, icone: "parchemin", phrase: nb > 1 ? nb + " questions de la banque à vérifier" : "Une question de la banque à vérifier",
      sous: "Recrutement · confirme-les à la source, ou corrige-les", action: { libelle: "Vérifier", icone: "valider", faire: () => {
        Object.assign(filtres("questionnaire", {}), { q: "", theme: "tous", diff: "0", statut: "a_verifier", actives: "toutes" });
        aller("capitainerie", "recrutement", "questions");
      } } });
  }
  const cat = vueJeu("catalogue");
  if (cat && !cat.erreur) {
    const nb = (cat.elements || []).filter((e) => e.actif !== false && e.statut === "a_verifier").length;
    if (nb) pousser({ sorte: "catalogue", prio: 4, icone: "catalogue", phrase: nb > 1 ? nb + " éléments du catalogue à vérifier" : "Un élément du catalogue à vérifier",
      sous: "RELL Seas · pas encore confirmés dans le jeu", action: { libelle: "Vérifier", icone: "valider", faire: () => {
        Object.assign(filtres("catalogue", {}), { q: "", type: "", statut: "a_verifier", movie3: false, inactifs: false });
        aller("capitainerie", "catalogue");
      } } });
    const aff = vueJeu("affiches");
    if (aff && !aff.erreur) {
      const nbA = (aff.affiches || []).filter((a) => !a.retire_le && insignes(a, cat).some((i) => !i.existe || i.actif === false)).length;
      if (nbA) pousser({ sorte: "insignes", prio: 4, icone: "affiches", phrase: nbA > 1 ? nbA + " affiches ont des insignes à revoir" : "Une affiche a des insignes à revoir",
        sous: "Des insignes retirés ou absents du catalogue", action: { libelle: "Revoir", icone: "affiches", faire: () => aller("capitainerie", "affiches") } });
    }
  }
  return out.sort((a, b) => a.prio - b.prio || (a.quand || n) - (b.quand || n));
}
/** Le compteur de l'accueil (pancarte et étiquette) : ce qui est urgent ou à faire. */
export const nombreAFaire = () => aFaire().filter((x) => x.prio <= 3).length;

// Au-delà de trois choses de la même sorte : les trois plus anciennes, puis « et N autres » vers la bonne page.
const TOUT_VOIR = {
  ticket: ["autres tickets que personne n'a pris", () => aller("port", "tickets")], question: ["autres questions sans réponse", () => aller("port", "salons", "questions")],
  decider: ["autres candidatures à décider", () => aller("capitainerie", "recrutement")], corriger: ["autres candidatures à corriger", () => aller("capitainerie", "recrutement")],
  inactif: ["autres membres inactifs après le rappel", () => aller("equipage", "membres")], alerte: ["autres alertes", () => voirAlertes()],
  brouillon: ["autres brouillons", () => aller("equipage", "annonces", "brouillons")], evenement: ["autres événements sans réponse", () => aller("equipage", "annonces", "a-venir")],
};
export function resserrer(items) {
  const parSorte = new Map();
  for (const x of items) { if (!parSorte.has(x.sorte)) parSorte.set(x.sorte, []); parSorte.get(x.sorte).push(x); }
  const out = [];
  for (const x of items) {
    const l = parSorte.get(x.sorte), rang = l.indexOf(x);
    if (rang < PAR_SORTE || !TOUT_VOIR[x.sorte]) { out.push(x); continue; }
    if (rang === PAR_SORTE) {
      const [texte, faire] = TOUT_VOIR[x.sorte];
      out.push({ sorte: x.sorte + "-reste", prio: x.prio, icone: "plus", phrase: "Et " + (l.length - PAR_SORTE) + " " + texte, sous: "La liste complète, sur sa page", action: { libelle: "Tout voir", icone: "droite", faire } });
    }
  }
  return out;
}

export function ligneAFaire(x) {
  const [nomPrio, teinte] = PRIORITES[x.prio] || PRIORITES[4];
  // Présence en direct : le dossier ou le brouillon que quelqu'un d'autre a ouvert porte son cadenas (déjà pris en main).
  return avecVerrou(ligne({
    visuel: x.personne ? avatar(x.personne, "p") : pastilleIcone(x.icone || "info", teinte), titre: x.phrase, sous: [h("span", { classe: "sr" }, nomPrio + " · "), x.sous || ""],
    date: x.quand ? depuis(x.quand) : "", dateTitre: x.quand ? date(x.quand, true) : "", teinte, classe: "a-faire", donnees: { sorte: x.sorte, prio: x.prio },
    actions: [Object.assign({ texte: true, onclick: x.action.faire, classe: x.prio === 1 ? "principal" : "" }, x.action)],
  }), x.objet);
}

// ─── Les raccourcis par tâche ───────────────────────────────────────────────
/** Les grandes tâches, en un clic : [{ cle, titre, sous, icone, faire }] (celles qu'on peut faire ici). */
export function raccourcis() {
  return [
    { cle: "evenement", titre: "Annoncer un événement", sous: "Une date, des rappels, qui vient", icone: "calendrier", faire: () => commencer("evenement") },
    { cle: "annonce", titre: "Faire une annonce", sous: "Un message pour tout l'équipage", icone: "cloche", faire: () => commencer("annonce") },
    peutAgir() ? { cle: "affiche", titre: "Créer une affiche", sous: "L'avis de recherche d'un membre", icone: "affiches", faire: () => { aller("capitainerie", "affiches"); editerAffiche(null); } } : null,
    { cle: "candidatures", titre: "Voir les candidatures", sous: "Décider, corriger, recruter", icone: "candidatures", faire: () => aller("capitainerie", "recrutement") },
    { cle: "membre", titre: "Chercher un membre", sous: "Sa fiche, son casier, ses tickets", icone: "rechercher", faire: () => emettre("recherche:ouvrir") },
    rubriqueExiste("capitainerie", "reglages") ? { cle: "textes", titre: "Modifier les textes", sous: "Ce que disent le bot et le site", icone: "plume", faire: () => aller("capitainerie", "reglages", "textes") } : null,
  ].filter(Boolean);
}
const tuileTache = (r) => h("button", { classe: "tache", type: "button", "data-tache": r.cle, onclick: r.faire },
  h("span", { classe: "tache-ic", "aria-hidden": "true" }, icone(r.icone)), h("span", { classe: "tache-texte" }, h("b", {}, r.titre), h("span", {}, r.sous)));

// ─── Les chiffres du bord (l'ancien Aperçu du Port, 27/10/2026) ─────────────
/** Les alertes en cours : le Répertoire, filtré sur « Alertes ». */
function voirAlertes() {
  Object.assign(filtres("repertoire", {}), { q: "", filtre: "alertes", lettre: "" });
  aller("port", "repertoire");
}
/** Les tuiles d'un coup d'œil (« Tout afficher ») : chacune ouvre sa page. */
function chiffresBord() {
  const d = etat.d;
  if (!d) return null;
  const ouverts = d.tickets.ouverts, nonPris = ouverts.filter((t) => !t.pris_par);
  const qOuvertes = ((d.questions && d.questions.liste) || []).filter((q) => q.statut === "ouverte");
  const alertes = d.alertes || [], clan = (d.clan && d.clan.membres) || [];
  const inactifs = clan.filter((m) => m.rang === 2).length;
  const st = (d.questions && d.questions.stats) || {};
  const etapes = new Map(d.en_cours.map((c) => [c, etapeCandidature(c)]));
  const aCorriger = d.en_cours.filter((c) => etapes.get(c) === "corriger").length;
  const aDecider = d.en_cours.filter((c) => etapes.get(c) === "decider").length;
  const attente = HL.file.ops.length;
  return tuiles(
    tuile({ cle: "a1", lib: "Tickets ouverts", val: ouverts.length, icone: "tickets", sous: nonPris.length + " pas encore pris", teinte: "#a8641c", clic: () => aller("port", "tickets") }),
    tuile({ cle: "a2", lib: "Questions sans réponse", val: qOuvertes.length, icone: "salons", sous: st.delai_median ? "réponse médiane : " + duree(st.delai_median) : "aucune réponse mesurée", teinte: "#1f4e5a", clic: () => aller("port", "salons", "questions") }),
    tuile({ cle: "a3", lib: "Alertes en cours", val: alertes.length, icone: "attention", sous: alertes.length ? "membres qui cumulent du grave" : "rien à signaler", teinte: alertes.length ? "#8e2a24" : "#3f6b3a", clic: alertes.length ? voirAlertes : null }),
    tuile({ cle: "a4", lib: "Sanctions · 30 jours", val: d.sanctions.trente_jours, icone: "sanctions", sous: nombre(d.sanctions.total) + " au casier", teinte: "#5e3a4e", clic: () => aller("port", "sanctions") }),
    tuile({ cle: "a5", lib: "Candidatures", val: d.en_cours.length, icone: "candidatures", sous: aDecider + " à décider · " + aCorriger + " à corriger", teinte: "#7a4b2a", clic: () => aller("capitainerie", "recrutement") }),
    tuile({ cle: "a6", lib: "Membres du clan", val: clan.length, icone: "equipage", sous: quantite(inactifs, "inactif(s)") + " depuis un mois", teinte: "#3f6b3a", clic: () => aller("equipage", "membres") }),
    attente ? tuile({ cle: "a7", lib: "Modifications à envoyer", val: attente, icone: "synchro", sous: "faites hors ligne, elles partent au retour", teinte: "#7a5a22", clic: () => emettre("file:ouvrir") }) : null);
}
/** « Tendances », replié en bas (« Tout afficher ») : l'activité du journal sur 14 jours, le travail de l'équipe sur 30. */
function tendancesBord() {
  const d = etat.d;
  if (!d) return null;
  const n = maintenant(), pj = (d.journal && d.journal.par_jour) || {}, jours = [], fam = {};
  for (let i = 13; i >= 0; i--) jours.push(cleJour(n - i * JOUR));
  const connues = ["Modération", "Sécurité", "Tickets", "Questions", "Clan", "Membres", "Messages", "Vocal"];
  for (const k of jours) {
    const v = pj[k] || {};
    fam[k] = { mod: (v["Modération"] || 0) + (v["Sécurité"] || 0), sup: (v["Tickets"] || 0) + (v["Questions"] || 0) + (v["Clan"] || 0),
      mem: v["Membres"] || 0, msg: (v["Messages"] || 0) + (v["Vocal"] || 0),
      autre: Object.entries(v).filter(([c]) => !connues.includes(c)).reduce((a, [, x]) => a + x, 0) };
  }
  const eq = d.equipe || [];
  return groupe({ titre: "Tendances", cle: "accueil-tendances", icone: "carte", classe: "avance" }, () => h("div", { classe: "duo" },
    h("div", { classe: "cadre" }, h("h3", {}, "Activité · 14 jours"), h("p", { classe: "aide" }, "Tout ce que le journal a consigné, jour par jour."),
      barres(jours, fam, [["mod", ENCRES.cire, "Modération et sécurité"], ["sup", ENCRES.sienne, "Tickets, questions, clan"], ["mem", ENCRES.vert, "Arrivées et départs"],
        ["msg", ENCRES.mer, "Messages et vocal"], ["autre", ENCRES.corde, "Autre"]], "Le journal se remplit au fil des évènements.")),
    h("div", { classe: "cadre" }, h("h3", {}, "Équipe · 30 jours"), h("p", { classe: "aide" }, "Tickets pris ou fermés, sanctions, questions répondues. Direction et fondateur à part."),
      eq.length ? barresH(eq.map((x) => [nomDe(P(x.id)), x.tickets + x.sanctions + x.questions, quantite(x.tickets, "ticket(s)") + " · " + quantite(x.sanctions, "sanction(s)") + " · " + quantite(x.questions, "question(s)"), () => ouvrirFiche(x.id)])) : vide("Rien sur 30 jours"))));
}

// ─── La page ────────────────────────────────────────────────────────────────
export function accueil(vue) {
  const haut = h("div", { classe: "pile" }), tendances = h("div", { classe: "pile" });
  const zone = h("div", { classe: "pile accueil" });
  const taches = section("Raccourcis", "boussole", "", h("div", { classe: "taches" }, raccourcis().map(tuileTache)));
  ajouter(vue, [haut, zone, taches, tendances]);
  const maj = () => {
    if (!zone.isConnected) return;
    remplacer(haut, chiffresBord());
    remplacer(tendances, tendancesBord());
    const tous = aFaire(), items = resserrer(tous);
    // Le même nombre que la pastille de l'onglet (nombreAFaire) : ce qui est à traiter, sans les « quand tu as le temps ».
    const n = tous.filter((x) => x.prio <= 3).length, urgents = tous.filter((x) => x.prio === 1).length;
    remplacer(zone, section("À faire", "attention", n ? quantite(n, "à traiter") + (urgents ? " · " + quantite(urgents, "urgente(s)") : "") : items.length ? "rien d'urgent" : "",
      items.length ? h("ul", { classe: "lignes-c a-faire-liste" }, items.map(ligneAFaire))
        : !etat.d ? (etat.chargementEnCours ? h("p", { classe: "aide" }, "Lecture du livre de bord…") : indisponible())
          : vide("Rien ne t'attend", "Pas d'alerte, pas de ticket oublié, pas de candidature en attente : tout est à jour.", "succes")));
  };
  for (const nom of JEUX) charger(nom);
  chargerSuivi();
  maj();
  return { maj, majJeu: maj, majFile: maj };
}
