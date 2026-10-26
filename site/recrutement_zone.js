// recrutement_zone.js — « Demande de recrutement » (La Capitainerie, 26/10/2026) : tout le recrutement au même endroit.
// Candidatures (à analyser, à corriger, en cours, décidées) · Chefs d'équipe (recrutement_chefs.js) · Questions (la
// banque, les modèles, les liens, la banque des chefs) · Réglages (le parcours de chaque panneau et ses messages dans
// l'ordre, la liste noire, le nettoyage, la purge exceptionnelle). Le dossier d'un candidat : sa fiche, la demande à
// approuver (ses étapes, choisies pour lui), le passage d'étape, la correction, la décision, « Voir comme le candidat ».

import { h, icone, date, depuis, nombre, sansEmoji, contient, remplacer, compte, quantite, ajouter, moisDe, libelleMois } from "./dom.js";
import { peutAgir, filtres, enLigne, emettre, nommerOnglets, retenirPersonnes } from "./noyau.js";
import { lire, poster, action } from "./api.js";
import { charger, vue as vueJeu, perime } from "./donnees.js";
import { mettreEnFile } from "./hors_ligne.js";
import {
  bouton, boutonIcone, avatar, pastille, tampon, vide, tuile, tuiles, puces, recherche, liste, champ, saisie, zoneTexte,
  interrupteur, caseACocher, confirmer, pancarte, toast, squelettes, groupe, bandeau, nomDe, majBoutonsReseau,
} from "./ui.js";
import { ouvrirFiche, reponses as listeReponses, transcriptEnLigne } from "./fiche.js";
import { ligne, lignes, groupes, quandLigne, pastilleIcone } from "./rangement.js";
import { modifierTexte, apercuMarkdown } from "./textes.js";
import { avecVerrou, protegerEditeur, protegerZone, siLibre } from "./direct.js";
import * as R from "./recrutement.js";
import { chefsZone, banqueChefs } from "./recrutement_chefs.js";

export const SUIVI = "recrutement/suivi";
const DECIDEES = "recrutement/decidees";
const PARCOURS = "recrutement/parcours";
const SOUS = nommerOnglets("site.sous.capitainerie.recrutement", [["candidatures", "Candidatures", "candidatures"],
  ["chefs", "Chefs d'équipe", "equipage"], ["questions", "Questions", "parchemin"], ["reglages", "Réglages", "cle"]]);
const MODES = { approbation: "Approbation", automatique: "Automatique", direct: "Sans questionnaire" };
const AIDE_MODES = {
  approbation: "La direction lit sa fiche, puis approuve : elle choisit ses étapes et ses questions.",
  automatique: "Le questionnaire part tout seul à l'ouverture du ticket.",
  direct: "Aucun questionnaire : la décision se prend sur sa fiche.",
};
const ACTIONS = { analyser: ["Demande à lire", "ambre"], etape_suivante: ["Étape reçue", "ambre"], attendre: ["Il répond", "mer"],
  corriger: ["À corriger", ""] };
const DECISIONS = { acceptes: ["Accepté", "vert"], refuses: ["Refusé", ""], elimine: ["Éliminé d'office", "encre"] };
const ETATS = { etape1: ["Demande", "ambre"], etape2: ["Questionnaire", "mer"], reponses: ["Réponses reçues", ""], accepte: ["Accepté", "vert"],
  refuse: ["Refusé", ""], refus_etape1: ["Demande refusée", ""], ferme: ["Fermé", "encre"] };
const FINALES = new Set(["accepte", "refuse", "refus_etape1", "ferme"]);
const STYLES_DISCORD = { 1: "primary", 2: "", 3: "success", 4: "danger", 5: "lien" };
const RE_BANNIERE = /^\/v\/[A-Za-z0-9_-]{1,40}\.(png|gif)(\?v=[A-Za-z0-9_.-]{1,20})?$/;   // la bannière de l'affiche (/v/)
const SOURCES = [["defaut", "La sélection par défaut"], ["tirage", "Un tirage dans la banque"], ["modele", "Un modèle"], ["questions", "Des questions choisies"]];
const TYPES_CHAMP = [["court", "Texte court"], ["long", "Texte long"], ["choix", "Un choix dans une liste"]];

// ═══ LA ZONE ══════════════════════════════════════════════════════════════
export function zone(vue, ctx) {
  const sous = SOUS.some(([k]) => k === ctx.sous) ? ctx.sous : "candidatures";
  const planches = h("div", { classe: "zr-planches", role: "tablist", "aria-label": "Demande de recrutement" });
  const scene = h("div", { classe: "zr-scene", role: "tabpanel", id: "zr-scene" });
  ajouter(vue, [planches, scene]);
  const majPlanches = () => {
    const n = compteursZone();
    remplacer(planches, ...SOUS.map(([k, l, ic]) => h("a", { classe: "zr-planche", role: "tab", href: "#capitainerie/recrutement/" + k,
      "aria-selected": String(k === sous), "aria-controls": "zr-scene" }, icone(ic), h("span", { classe: "zr-planche-titre" }, l),
    n[k] ? h("span", { classe: "compteur chaud" }, n[k] > 99 ? "99+" : String(n[k])) : null)));
  };
  majPlanches();
  const fabriques = { candidatures: candidaturesZone, chefs: chefsZone, questions: questionsZone, reglages: reglagesZone };
  const ctrl = fabriques[sous](scene) || {};
  requestAnimationFrame(() => scene.classList.add("zr-entree"));
  return {
    maj: () => { majPlanches(); if (ctrl.maj) ctrl.maj(); },
    majJeu: () => { majPlanches(); if (ctrl.majJeu) ctrl.majJeu(); },
    majFile: () => { if (ctrl.majFile) ctrl.majFile(); },
    quitter: () => { if (ctrl.quitter) ctrl.quitter(); },
  };
}
/** Ce qui attend la direction : les pastilles des sous-onglets, l'étiquette de la rubrique. */
export function compteursZone() {
  const s = vueJeu(SUIVI);
  const ouverts = (s && Array.isArray(s.ouverts)) ? s.ouverts : [];
  const c = vueJeu("recrutement/chefs");
  return {
    candidatures: ouverts.filter((o) => ["analyser", "etape_suivante", "corriger"].includes(o.action)).length,
    chefs: c && !c.erreur ? (c.candidatures || []).filter((x) => x.etat === "corriger").length : 0,
  };
}

// ═══ LES CANDIDATURES ════════════════════════════════════════════════════
function candidaturesZone(scene) {
  const f = filtres("zr-candidatures", { q: "", page: 1 });
  const resultats = h("div", { classe: "pile" }, squelettes(3));
  remplacer(scene, h("div", { classe: "outils" }, recherche(f.q, "Nom, pseudo, ticket…", (q) => { f.q = q; maj(); })), resultats);
  let vivant = true;
  async function maj(forcer) {
    const [S, D] = await Promise.all([charger(SUIVI, { forcer }), charger(DECIDEES, { params: { page: String(f.page || 1) }, forcer })]);
    if (!vivant || !resultats.isConnected) return;
    if (!S || S.erreur) { remplacer(resultats, vide("Candidatures indisponibles", (S && S.erreur) || "Réessaie dans un instant.", "hors_ligne")); return; }
    const garde = (o) => contient([nomDe(o.candidat), o.candidat && o.candidat.pseudo, o.ticket, o.panneau].join(" "), f.q);
    const par = { analyser: [], corriger: [], attendre: [] };
    for (const o of (S.ouverts || []).filter(garde)) {
      if (o.fermeture_prevue) continue;
      (o.action === "etape_suivante" || o.action === "analyser" ? par.analyser : o.action === "corriger" ? par.corriger : par.attendre).push(o);
    }
    for (const k of Object.keys(par)) par[k].sort((a, b) => (a.ouvert || 0) - (b.ouvert || 0));
    const dec = D && !D.erreur ? D : null;
    const elimines30 = (S.elimines || []).length;
    remplacer(resultats,
      tuiles(tuile({ cle: "zr-t1", lib: "À analyser", val: par.analyser.length, icone: "oeil", sous: "demandes et étapes reçues", teinte: "#a8641c" }),
        tuile({ cle: "zr-t2", lib: "À corriger", val: par.corriger.length, icone: "plume", teinte: "#8e2a24" }),
        tuile({ cle: "zr-t3", lib: "En cours", val: par.attendre.length, icone: "minuteur", sous: "il répond", teinte: "#1f4e5a" }),
        tuile({ cle: "zr-t4", lib: "Décidées", val: dec ? dec.total : (S.recents || []).length, icone: "coffre", sous: elimines30 ? quantite(elimines30, "éliminé(s) d'office en 30 jours") : "acceptées, refusées", teinte: "#4a5560" })),
      h("div", { classe: "groupes-zone" }, groupes([
        { cle: "zr-analyser", titre: "À analyser", icone: "oeil", compte: par.analyser.length, chaud: par.analyser.length > 0,
          info: "sa fiche, ou l'étape qu'il vient d'envoyer",
          contenu: () => (par.analyser.length ? lignes("zr-analyser", par.analyser, ligneCandidature) : vide("Rien à analyser", "Une nouvelle demande arrive ici dès l'ouverture du ticket.", "succes")) },
        //  Un groupe vide ne prend pas de place (sauf « À analyser » : il dit que tout est lu).
        par.corriger.length ? { cle: "zr-corriger", titre: "À corriger", icone: "plume", compte: par.corriger.length, chaud: true,
          contenu: () => lignes("zr-corriger", par.corriger, ligneCandidature) } : null,
        par.attendre.length ? { cle: "zr-encours", titre: "En cours", icone: "minuteur", compte: par.attendre.length, info: "le candidat répond",
          contenu: () => lignes("zr-encours", par.attendre, ligneCandidature) } : null,
        { cle: "zr-decidees", titre: "Décidées", icone: "coffre", compte: dec ? dec.total : 0, contenu: () => blocDecidees(dec, f, () => maj(true)) },
      ], { ouverts: 2, forcer: !!f.q })));
    majBoutonsReseau(resultats);
  }
  maj(true);
  return { maj: () => maj(false), majJeu: () => maj(false), quitter: () => { vivant = false; } };
}

function etapeTexte(o) {
  const e = o.envoi;
  if (o.action === "analyser") return o.mode === "direct" ? "sans questionnaire : décider sur sa fiche" : "sa fiche attend ta décision";
  if (!e) return "";
  if (o.action === "corriger") return quantite(e.nb, "réponse(s)") + " à corriger";
  if (e.porte) return o.action === "etape_suivante" ? "étape " + e.etape_envoyee + " sur " + e.total + " reçue" : "étape " + e.etape_ouverte + " sur " + e.total + " ouverte";
  return quantite(e.nb, "question(s)") + " envoyée(s)";
}
/** Une candidature ouverte : qui, où il en est, sa prochaine action ; son dossier au clic. */
function ligneCandidature(o) {
  const [lib, coul] = ACTIONS[o.action] || ["En cours", "mer"];
  const c = o.candidat || {};
  return avecVerrou(ligne({
    visuel: avatar(c, "p"), titre: nomDe(c),
    sous: [c.pseudo ? "@" + c.pseudo : "", etapeTexte(o), MODES[o.mode] && o.mode !== "approbation" ? MODES[o.mode] : "",
      o.pris_par ? "suivi par " + nomDe(o.pris_par) : ""].filter(Boolean).join(" · "),
    badges: [tampon(lib, coul, true), c.present === false ? pastille("A quitté le serveur", "#4a5560") : null], ...quandLigne(o.ouvert),
    etat: o.action === "corriger" ? "alerte" : o.action === "analyser" || o.action === "etape_suivante" ? "chaude" : null,
    ouvrir: () => ouvrirDossier(o.ticket), libelleOuvrir: "Ouvrir le dossier de " + nomDe(c), donnees: { ticket: o.ticket },
  }), "dossier:" + o.ticket);
}

/** L'historique des décisions, page par page (25), rangé par mois : quand, qui, par qui, le transcript. */
function blocDecidees(D, f, recharger) {
  if (!D) return vide("Historique indisponible", "Réessaie dans un instant.", "hors_ligne");
  if (!D.total) return vide("Aucune décision pour l'instant", "Les candidatures acceptées, refusées ou éliminées d'office arrivent ici.", "coffre");
  const parMois = new Map();
  for (const x of D.lignes || []) { const k = x.quand ? moisDe(x.quand) : "inconnu"; if (!parMois.has(k)) parMois.set(k, []); parMois.get(k).push(x); }
  const c = D.comptes || {};
  const pages = Number(D.pages) || 1, page = Number(D.page) || 1;
  const aller_ = (p) => { f.page = Math.max(1, Math.min(pages, p)); recharger(); };
  return h("div", { classe: "pile serree" },
    h("p", { classe: "meta" }, [quantite(c.acceptes || 0, "acceptée(s)"), quantite(c.refuses || 0, "refusée(s)"), quantite(c.elimine || 0, "éliminé(s) d'office")].join(" · ")),
    ...[...parMois.entries()].map(([k, l]) => h("div", { classe: "zr-mois" }, h("h3", { classe: "zr-mois-titre" }, k === "inconnu" ? "Date inconnue" : libelleMois(k)),
      h("ul", { classe: "lignes-c" }, l.map(ligneDecidee)))),
    pages > 1 ? h("div", { classe: "rangee entre zr-pages" },
      bouton("Plus récentes", { classe: "p discret", icone: "gauche", disabled: page <= 1, onclick: () => aller_(page - 1) }),
      h("span", { classe: "meta" }, "Page " + page + " sur " + pages),
      bouton("Plus anciennes", { classe: "p discret", icone: "droite", disabled: page >= pages, onclick: () => aller_(page + 1) })) : null);
}
function ligneDecidee(x) {
  const [lib, coul] = DECISIONS[x.decision] || [x.decision, "encre"];
  const m = x.membre || {};
  retenirPersonnes({ [String(m.id)]: m });
  return ligne({
    visuel: avatar(m, "p"), titre: nomDe(m),
    sous: [x.motif || "", x.par ? "par " + nomDe(x.par) : "", x.ticket ? "ticket #" + x.ticket : ""].filter(Boolean).join(" · "),
    badges: [tampon(lib, coul, true)], ...quandLigne(x.quand),
    actions: x.transcript ? [{ icone: "parchemin", libelle: "Le transcript", href: x.transcript }] : [],
    ouvrir: () => (x.ticket ? ouvrirDossier(x.ticket) : ouvrirFiche(m.id)), libelleOuvrir: "Ouvrir " + (x.ticket ? "le dossier" : "la fiche") + " de " + nomDe(m),
    donnees: { membre: m.id },
  });
}

// ═══ LE DOSSIER D'UN CANDIDAT ═════════════════════════════════════════════
let dossierOuvert = null;
export async function ouvrirDossier(ticket) {
  if (dossierOuvert && !dossierOuvert.p.fermee()) dossierOuvert.p.fermer();
  const p = pancarte({ titre: "Dossier", sous: "Demande de recrutement · ticket #" + ticket, icone: "candidatures", taille: "tres-large",
    surFermer: () => { if (dossierOuvert && dossierOuvert.p === p) { quitterDirect(dossierOuvert); dossierOuvert = null; } } });
  const etatD = { p, ticket: String(ticket), vue: "dossier" };
  etatD.rendre = (forcer) => rendreDossier(etatD, forcer);
  dossierOuvert = etatD;
  etatD.verrou = protegerEditeur(p, "dossier:" + ticket, "ce dossier", { surPlace: true, relire: () => { etatD.vue = "dossier"; return rendreDossier(etatD, true); } });
  remplacer(p.corps, squelettes(3));
  await rendreDossier(etatD, true);
}

async function rendreDossier(etatD, forcer) {
  const D = await charger("dossier", { params: { ticket: etatD.ticket }, forcer: forcer !== false });
  const p = etatD.p;
  if (p.fermee()) return;
  if (!D || D.erreur) {
    remplacer(p.corps, vide("Dossier indisponible", (D && D.erreur) || "Réessaie dans un instant.", "attention"));
    remplacer(p.pied, bouton("Fermer", { classe: "discret", onclick: () => p.fermer() }));
    return;
  }
  etatD.D = D;
  const cand = D.candidat || {};
  retenirPersonnes({ [String(cand.id)]: cand });
  p.titre.firstChild.textContent = "Dossier de " + nomDe(cand);
  if (etatD.verrou && etatD.verrou.changerObjet) etatD.verrou.changerObjet("dossier:" + etatD.ticket, "le dossier de " + nomDe(cand));
  if (etatD.vue === "etapes") return editeurEtapes(etatD, D);
  const peut = D.peut || {};
  const [lib, coul] = ETATS[D.etape] || [D.etape, "encre"];
  const e = (D.envois || []).find((x) => x.id === D.envoi_courant) || (D.envois || [])[(D.envois || []).length - 1];
  const tete = h("div", { classe: "dossier-tete" }, avatar(cand, "g"),
    h("div", { classe: "bloc" }, h("div", { classe: "fiche-nom" }, nomDe(cand)),
      h("div", { classe: "sous-nom" }, [cand.pseudo ? "@" + cand.pseudo : "", D.ouvert_le ? "demande " + depuis(D.ouvert_le) : "", MODES[D.mode] || ""].filter(Boolean).join(" · ")),
      h("div", { classe: "rangee" }, tampon(lib, coul, true),
        e && e.porte && !FINALES.has(D.etape) ? tampon("Étape " + (e.etape_ouverte + e.etape_fiche) + " sur " + ((e.etapes || []).length + e.etape_fiche), "mer", true) : null,
        cand.id ? bouton("Sa fiche", { classe: "p discret", icone: "personne", onclick: () => { p.fermer(); ouvrirFiche(cand.id, "candidatures"); } }) : null,
        D.affiche || e ? bouton("Voir comme le candidat", { classe: "p discret", icone: "oeil", onclick: () => voirCommeLeCandidat(D) }) : null,
        D.liens_discord && D.liens_discord.ticket ? h("a", { classe: "bouton p discret", href: D.liens_discord.ticket }, icone("discord"), h("span", {}, "Le ticket")) : null,
        D.transcript ? h("a", { classe: "bouton p discret", href: D.transcript }, icone("parchemin"), h("span", {}, "Le transcript")) : null)));
  const blocs = [tete];
  if (D.fermeture_prevue) blocs.push(bandeau("La décision est partie dans le ticket : il se ferme dans un instant.", ""));
  if (D.liste_noire) blocs.push(bandeau("Sur la liste noire des tickets de recrutement : il ne peut plus ouvrir de demande.", "rouge"));
  if (D.vue_direct && D.envoi_courant && !FINALES.has(D.etape)) blocs.push(zoneDirect(etatD, D));   // dès qu'un questionnaire est parti
  blocs.push(groupe({ titre: "Étape 1 · sa fiche", icone: "candidatures", cle: "zr-dossier-fiche", defaut: D.etape === "etape1" }, () => [
    listeReponses(Object.entries((D.etape1 && D.etape1.reponses) || {})),
    transcriptEnLigne(Number(D.ticket), "Ticket #" + D.ticket, false)]));
  if (peut.etape1) blocs.push(blocDemande(etatD, D));
  if (peut.accepter_direct) blocs.push(h("div", { classe: "cadre pile serree zr-demande" }, h("h3", {}, "Décider sur sa fiche"),
    h("p", { classe: "aide" }, "Ce panneau est réglé sans questionnaire : accepte ou refuse en lisant sa fiche (les boutons sont en bas).")));
  if (peut.etape_suivante && e) blocs.push(h("div", { classe: "cadre pile serree zr-suivante" },
    h("h3", {}, "Étape " + (e.etape_envoyee + e.etape_fiche) + " reçue"),
    h("p", { classe: "aide" }, "Regarde ses réponses ci-dessous, puis ouvre l'étape suivante (en bas) : elle part dans son ticket et il est prévenu.")));
  const envois = (D.envois || []).slice().sort((a, b) => (b.envoye_le || 0) - (a.envoye_le || 0));
  envois.forEach((x, i) => {
    if (i === 0) blocs.push(blocQuestionnaire(etatD, D, x, true));
    else blocs.push(groupe({ titre: "Questionnaire du " + date(x.envoye_le), compte: (x.questions || []).length, cle: "zr-envoi-" + x.id }, () => blocQuestionnaire(etatD, D, x, false)));
  });
  if ((D.decisions || []).length) blocs.push(groupe({ titre: "Historique", icone: "journal", compte: D.decisions.length, cle: "zr-dossier-hist" }, () =>
    h("ul", { classe: "lignes-c" }, D.decisions.slice().reverse().map((x) => ligne({ visuel: pastilleIcone("journal", "#5a4330"), titre: quoiHistorique(x.quoi),
      sous: [x.par ? "par " + nomDe(x.par) : "", x.detail || ""].filter(Boolean).join(" · "), ...quandLigne(x.quand) })))));
  remplacer(p.corps, ...blocs);
  //  Les décisions, toujours en vue (en bas de la fenêtre) : la demande, la décision sur sa fiche, l'étape suivante,
  //  la décision finale.
  const pied = [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })];
  if (peutAgir() && D.statut_ticket !== "ferme" && !D.fermeture_prevue) pied.unshift(bouton("Fermer le ticket sans décider", { classe: "discret danger gauche", icone: "cadenas", reseau: true, onclick: () => fermerSansDecider(etatD, D) }));
  if (peut.etape1) {
    pied.push(bouton("Refuser la demande", { classe: "danger", icone: "annuler", reseau: true, onclick: () => refuserDemande(etatD, D) }),
      bouton("Choisir ses étapes…", { icone: "parchemin", onclick: () => { etatD.vue = "etapes"; etatD.mode = "approbation"; editeurEtapes(etatD, D); } }),
      bouton("Approuver la demande", { classe: "principal", icone: "valider", reseau: true, onclick: () => approuver(etatD, D, null) }));
  } else if (peut.accepter_direct) {
    pied.push(bouton("Refuser", { classe: "danger", icone: "annuler", reseau: true, onclick: () => decider(etatD, D, "refuser") }),
      bouton("Accepter", { classe: "principal", icone: "valider", reseau: true, onclick: () => decider(etatD, D, "accepter") }));
  } else if (e && (peut.refuser || peut.accepter)) {
    const qs = e.questions || [], justes = qs.filter((q) => justeDe(q) === true).length;
    if (peut.renvoyer) pied.splice(1, 0, bouton("Renvoyer d'autres questions", { icone: "parchemin", onclick: () => { etatD.vue = "etapes"; etatD.mode = "renvoi"; editeurEtapes(etatD, D); } }));
    if (peut.refuser) pied.push(bouton("Refuser", { classe: "danger", icone: "annuler", reseau: true, onclick: () => decider(etatD, D, "refuser") }));
    if (peut.etape_suivante) pied.push(bouton("Ouvrir l'étape " + (e.etape_ouverte + e.etape_fiche + 1), { classe: "principal", icone: "droite", reseau: true, onclick: () => etapeSuivante(etatD, D) }));
    else if (peut.accepter && D.etape === "reponses") pied.push(bouton("Accepter · " + justes + "/" + qs.length, { classe: "principal", icone: "valider", reseau: true, onclick: () => decider(etatD, D, "accepter", justes, qs.length) }));
  }
  remplacer(p.pied, ...pied);
  majBoutonsReseau(p.pied);
  majBoutonsReseau(p.corps);
}
const QUOI = { questionnaire: "Demande approuvée : questionnaire envoyé", questionnaire_auto: "Questionnaire envoyé à l'ouverture", renvoi: "Nouveau questionnaire",
  reponses: "Réponses reçues", etape_recue: "Étape reçue", etape_suivante: "Étape suivante ouverte", accepte: "Accepté", refuse: "Refusé",
  refus_etape1: "Demande refusée", mp_impossible: "Message privé impossible", automatique_echec: "Questionnaire automatique non parti" };
const quoiHistorique = (q) => QUOI[q] || q;
const justeDe = (q) => ("juste" in q ? q.juste : q.correction ? q.correction.juste : null);

/** La demande (étape 1) : approuver avec le questionnaire prévu, choisir ses étapes, ou refuser. */
function blocDemande(etatD, D) {
  const zoneProp = h("div", { classe: "pile serree" }, squelettes(1));
  lire("recrutement/proposition", { ticket: etatD.ticket }).then((r) => {
    if (!zoneProp.isConnected) return;
    if (!r.ok || !r.donnees) { remplacer(zoneProp, h("p", { classe: "aide" }, r.erreur || "Le questionnaire prévu n'a pas pu être lu.")); return; }
    etatD.proposition = r.donnees;
    remplacer(zoneProp, resumeEtapes(r.donnees.etapes || []));
  });
  return h("div", { classe: "cadre pile serree zr-demande" }, h("h3", {}, "Sa demande"),
    h("p", { classe: "aide" }, "Lis sa fiche. Approuver ouvre son questionnaire dans le ticket (il est prévenu) ; refuser lui envoie un message, puis le ticket se ferme. Le questionnaire prévu :"),
    zoneProp);
}
function resumeEtapes(etapes) {
  if (!etapes.length) return h("p", { classe: "aide" }, "Aucune question posable : règle le questionnaire de ce panneau.");
  return h("ol", { classe: "zr-etapes-resume" }, etapes.map((e) => h("li", {},
    h("b", {}, "Étape " + (e.numero_candidat || e.numero + 1) + (e.titre ? " · " + e.titre : "")),
    h("span", { classe: "meta" }, " — " + quantite((e.questions || []).length, "question(s)")))));
}

/** Le questionnaire d'un candidat : ses étapes, ses réponses, la correction (une aide, la personne décide). */
function blocQuestionnaire(etatD, D, e, courant) {
  const qs = e.questions || [];
  const fiche = e.etape_fiche || 0;
  const corrigeable = courant && !FINALES.has(D.etape) && peutAgir();
  const repondues = qs.filter((q) => q.reponse_candidat !== null && q.reponse_candidat !== undefined).length;
  const justes = qs.filter((q) => justeDe(q) === true).length, faux = qs.filter((q) => justeDe(q) === false).length;
  const parEtape = new Map();
  for (const q of qs) { const n = Number(q.etape) || 1; if (!parEtape.has(n)) parEtape.set(n, []); parEtape.get(n).push(q); }
  const etapes = (e.etapes || []).length ? e.etapes : [{ numero: 1, titre: "", consigne: "" }];
  const pc = qs.length ? Math.round(100 * justes / qs.length) : 0;
  const tete = [h("p", { classe: "meta" }, [e.envoye_le ? "Envoyé " + depuis(e.envoye_le) : "", e.envoye_par ? "par " + nomDe(e.envoye_par) : "",
    quantite(qs.length, "question(s)"), repondues ? quantite(repondues, "réponse(s)") : "aucune réponse encore"].filter(Boolean).join(" · "))];
  if (repondues) tete.push(h("div", { classe: "correction-barre" + (justes === qs.length && qs.length ? " complet" : "") },
    h("div", { classe: "correction-compte" }, h("b", { classe: "num" }, justes + " / " + qs.length), " justes — " + (D.exigence ?? 100) + " % exigés"),
    h("span", { classe: "vote-fond" }, h("span", { classe: "vote-plein", vars: { "--pc": pc + "%" } })),
    h("span", { classe: "meta" }, faux ? quantite(faux, "fausse(s)") + " · " : "", quantite(qs.length - justes - faux, "à corriger"))));
  const preJustes = qs.filter((q) => q.pre_juste && justeDe(q) === null);
  if (corrigeable && preJustes.length) tete.push(h("div", { classe: "rangee" }, bouton("Marquer justes les " + preJustes.length + " réponses identiques à l'attendue", {
    classe: "p", icone: "valider", onclick: async () => {
      for (const q of preJustes) await mettreEnFile("recrutement/corriger", { envoi: e.id, question: q.id, juste: true }, { genre: "correction", cle: e.id + ":" + q.id, resume: "Correction : juste" });
      toast(quantite(preJustes.length, "réponse(s) marquée(s) juste(s)") + ".", "succes");
      etatD.rendre();
    } }), h("span", { classe: "meta" }, "Une aide : vérifie-les quand même.")));
  const corps = etapes.map((x) => {
    const n = Number(x.numero) || 1, liste_ = parEtape.get(n) || [];
    const ouverte = !e.porte || n <= e.etape_ouverte, envoyee = !e.porte || n <= e.etape_envoyee || e.statut === "repondu";
    const etat_ = !ouverte ? ["À venir", "encre"] : envoyee && liste_.some((q) => q.reponse_candidat != null) ? ["Reçue", "vert"] : ["Ouverte · il répond", "mer"];
    //  Les réponses reçues : la correction ; les questions sans réponse : leur seul texte (rien à corriger encore).
    const recues = liste_.filter((q) => q.reponse_candidat != null), attente = liste_.filter((q) => q.reponse_candidat == null);
    return h("section", { classe: "zr-etape" + (ouverte ? "" : " a-venir") },
      h("div", { classe: "zr-etape-tete" }, h("h4", {}, "Étape " + (n + fiche) + (x.titre ? " · " + x.titre : "")), tampon(etat_[0], etat_[1], true)),
      x.consigne ? h("p", { classe: "aide" }, x.consigne) : null,
      recues.length ? h("ol", { classe: "correction-liste" }, recues.map((q) => R.carteCorrection(etatD, e, q, Number(q.rang) - 1, corrigeable))) : null,
      attente.length ? h("div", { classe: "pile serree" },
        h("p", { classe: "aide" }, ouverte ? "En attente des réponses du candidat." : "Ces questions partent quand tu ouvres cette étape."),
        h("ol", { classe: "questions-envoyees" }, attente.map((q) => h("li", { value: Number(q.rang) }, q.question)))) : null);
  });
  return h("section", { classe: "cadre pile envoi" + (courant ? " courant" : "") },
    h("h3", {}, courant ? (e.statut === "remplace" ? "Questionnaire remplacé" : "Son questionnaire") : "Questionnaire"), ...tete, ...corps);
}

// ─── Les décisions ──────────────────────────────────────────────────────
/** Un texte que le candidat lira, cité tel quel, avec « Modifier ce message » (Textes & noms). */
function citation(texte, cle) {
  const bloc = h("div", { classe: "texte-discord zr-citation" }, apercuMarkdown(texte || ""));
  return [bloc, bouton("Modifier ce message", { classe: "p discret", icone: "plume", onclick: () => modifierTexte(cle, {
    apres: (t) => { if (t && typeof t.valeur === "string") remplacer(bloc, apercuMarkdown(t.valeur)); } }) })];
}
async function refuserDemande(etatD, D) {
  const r = await confirmer({ titre: "Refuser la demande ?", icone: "annuler", style: "danger", libelleOk: "Refuser et fermer le ticket", taille: "",
    texte: "Ce message part dans son ticket, puis le ticket se ferme" + (D.delai ? " (" + D.delai + " s plus tard)" : "") + " :",
    motif: true, motifLib: "Note interne (jamais montrée au candidat)",
    contenu: [...citation(D.message_refus_etape1, "recrutement.refus_etape1"), h("p", { classe: "meta" }, "Et en message privé :"),
      ...citation(D.mp_refus_demande, "recrutement.mp.demande_refusee"),
      D.liste_noire_au_refus ? h("p", { classe: "aide" }, "Ce panneau met sur la liste noire au refus : il ne pourra plus ouvrir de demande.") : null] });
  if (!r) return;
  const rep = await poster("recrutement/etape1", { ticket: Number(D.ticket), decision: "refuser", note: r.motif || "" });
  toast(rep.ok ? rep.donnees.message || "Refus envoyé." : rep.erreur, rep.ok ? "succes" : "erreur");
  if (rep.ok) { etatD.p.fermer(); rafraichir(); }
}
async function approuver(etatD, D, etapes) {
  const corps = { ticket: Number(D.ticket), decision: "approuver" };
  if (etapes) corps.etapes = etapes;
  const rep = await poster("recrutement/etape1", corps);
  if (!rep.ok) { toast(rep.erreur || "Impossible d'approuver.", "erreur"); return false; }
  const ign = (rep.donnees && rep.donnees.ignorees) || [];
  toast(rep.donnees.message || "Demande approuvée.", ign.length ? "erreur" : "succes");
  etatD.vue = "dossier";
  rafraichir();
  await rendreDossier(etatD, true);
  return true;
}
async function etapeSuivante(etatD, D) {
  const rep = await poster("recrutement/etape_suivante", { ticket: Number(D.ticket) });
  toast(rep.ok ? rep.donnees.message || "Étape ouverte." : rep.erreur, rep.ok ? "succes" : "erreur");
  if (rep.ok) { rafraichir(); await rendreDossier(etatD, true); }
}
async function decider(etatD, D, quoi, justes, total) {
  const nom = nomDe(D.candidat || {});
  const direct = D.etape === "etape1" && D.mode === "direct";
  let corps = { ticket: Number(D.ticket), decision: quoi };
  if (quoi === "accepter") {
    const complet = direct || (total && justes === total);
    const exigence = D.exigence ?? 100;
    const r = await confirmer({ titre: "Accepter " + nom + " ?", icone: "valider", libelleOk: "Accepter", style: complet ? "vert" : "danger", taille: "",
      texte: complet ? "Il reçoit le rôle du clan, ce message dans son ticket, puis le ticket se ferme :"
        : "Attention : " + justes + " / " + total + " réponses cochées justes (" + exigence + " % exigés). Accepter quand même ?",
      contenu: [...citation(D.message_acceptee, "recrutement.decision.acceptee"), h("p", { classe: "meta" }, "En message privé :"), ...citation(D.mp_accepte, "recrutement.mp.acceptee")] });
    if (!r) return;
    if (!complet) corps.forcer = true;
  } else {
    const r = await confirmer({ titre: "Refuser la candidature de " + nom + " ?", icone: "annuler", style: "danger", libelleOk: "Refuser et fermer le ticket", taille: "",
      texte: "Ce message neutre part dans son ticket (jamais où il s'est trompé), puis le ticket se ferme :", motif: true, motifLib: "Note interne (jamais montrée au candidat)",
      contenu: [...citation(D.message_refus, "recrutement.refus_final"), h("p", { classe: "meta" }, "Et en message privé :"), ...citation(D.mp_refus, "recrutement.mp.refusee"),
        D.liste_noire_au_refus ? h("p", { classe: "aide" }, "Ce panneau met sur la liste noire au refus.") : null] });
    if (!r) return;
    corps = Object.assign(corps, { motif: r.motif || "" });
  }
  const rep = await poster("recrutement/decision", corps);
  toast(rep.ok ? rep.donnees.message || "C'est fait." : rep.erreur, rep.ok ? "succes" : "erreur");
  if (rep.ok) { etatD.p.fermer(); rafraichir(); }
}
async function fermerSansDecider(etatD, D) {
  const r = await confirmer({ titre: "Fermer le ticket sans décider ?", texte: "Le ticket est fermé ; le transcript et le dossier sont gardés. Aucun message de refus n'est envoyé.", motif: true, libelleOk: "Fermer le ticket", style: "danger" });
  if (!r) return;
  const rep = await action({ action: "ticket_fermer", ticket: Number(D.ticket), motif: r.motif || "" });
  toast(rep.message, rep.ok ? "succes" : "erreur");
  if (rep.ok) { etatD.p.fermer(); rafraichir(); }
}
function rafraichir() { perime(SUIVI); perime(DECIDEES); perime("dossier"); emettre("recharger"); charger(SUIVI, { forcer: true }); }

// ─── Ses étapes, pour lui seul (approbation, ou nouveau questionnaire) ──
async function editeurEtapes(etatD, D) {
  const p = etatD.p;
  remplacer(p.corps, squelettes(2));
  remplacer(p.pied);
  const [prop, B, PA] = await Promise.all([
    etatD.mode === "renvoi" ? Promise.resolve({ ok: true, donnees: { etapes: [{ numero: 1, titre: "", consigne: "", questions: [] }] } }) : lire("recrutement/proposition", { ticket: etatD.ticket }),
    charger("banque"), charger(PARCOURS)]);
  if (p.fermee()) return;
  const limites = (PA && PA.limites) || { etapes: 8, par_envoi: 40, nouvelles: 10, etape_titre: 80, etape_consigne: 200 };
  const banque = ((B && B.questions) || []).filter((q) => q.actif !== false && !q.retiree && q.posable !== false);
  const parId = new Map(banque.map((q) => [String(q.id), q]));
  const deja = new Set((D.envois || []).flatMap((e) => (e.questions || []).map((q) => String(q.id))));
  const etapes = ((prop.ok && prop.donnees && prop.donnees.etapes) || [{ titre: "", consigne: "", questions: [] }]).map((e) => ({
    titre: e.titre || "", consigne: e.consigne || "", questions: (e.questions || []).map((q) => String(q.id)), nouvelles: [] }));
  const fiche = D.affiche ? 1 : 0;
  const zoneE = h("div", { classe: "pile" });
  const total = () => etapes.reduce((n, e) => n + e.questions.length + e.nouvelles.length, 0);
  const envoyerB = bouton("", { classe: "principal", icone: "valider", reseau: true, onclick: async () => {
    const corps = etapes.filter((e) => e.questions.length || e.nouvelles.length).map((e) => ({ titre: e.titre.trim(), consigne: e.consigne.trim(), questions: e.questions,
      nouvelles: e.nouvelles.map((n) => ({ question: n.question.trim(), reponse: n.reponse.trim(), variantes: n.variantes, theme: n.theme, banque: !!n.banque })) }));
    if (!corps.length) { toast("Coche au moins une question.", "erreur"); return; }
    envoyerB.disabled = true;
    if (etatD.mode === "renvoi") {
      const rep = await poster("recrutement/decision", { ticket: Number(D.ticket), decision: "renvoyer", etapes: corps });
      envoyerB.disabled = false;
      if (!rep.ok) { toast(rep.erreur || "Envoi impossible.", "erreur"); return; }
      toast(rep.donnees.message || "Questionnaire envoyé.", "succes");
      etatD.vue = "dossier"; rafraichir(); rendreDossier(etatD, true);
    } else if (!(await approuver(etatD, D, corps))) envoyerB.disabled = false;
  } });
  const dessiner = () => {
    remplacer(zoneE, ...etapes.map((e, i) => carteEtape(e, i)),
      etapes.length < limites.etapes ? h("div", { classe: "rangee" }, bouton("Ajouter une étape", { classe: "p", icone: "ajouter", onclick: () => { etapes.push({ titre: "", consigne: "", questions: [], nouvelles: [] }); dessiner(); } })) : null);
    remplacer(envoyerB, icone("valider"), h("span", {}, (etatD.mode === "renvoi" ? "Envoyer ce questionnaire · " : D.affiche ? "Approuver et ouvrir l'étape " + (1 + fiche) + " · "
      : "Approuver et envoyer le questionnaire · ") + compte(total(), "question")));
    envoyerB.disabled = !total() || !enLigne();
  };
  const carteEtape = (e, i) => {
    const titre = saisie({ value: e.titre, maxlength: limites.etape_titre, placeholder: "Le jeu, le clan…", "aria-label": "Titre de l'étape " + (i + 1 + fiche) });
    titre.addEventListener("input", () => { e.titre = titre.value; });
    const consigne = saisie({ value: e.consigne, maxlength: limites.etape_consigne, placeholder: "Ce qu'il doit savoir avant de répondre (facultatif)", "aria-label": "Consigne de l'étape " + (i + 1 + fiche) });
    consigne.addEventListener("input", () => { e.consigne = consigne.value; });
    const qs = e.questions.map((id, k) => {
      const q = parId.get(id) || {};
      return h("li", { classe: "zr-q" }, h("span", { classe: "selection-num" }, String(k + 1)), h("span", { classe: "zr-q-texte" }, q.question || "Question retirée de la banque",
        deja.has(id) ? h("span", { classe: "marque-deja" }, " déjà posée") : null),
      boutonIcone("fermer", "Retirer cette question", () => { e.questions.splice(k, 1); dessiner(); }));
    });
    const persos = e.nouvelles.map((n, k) => h("li", { classe: "zr-q perso" }, h("span", { classe: "selection-num" }, "+"),
      h("span", { classe: "zr-q-texte" }, n.question, h("span", { classe: "meta" }, " — écrite pour lui" + (n.banque ? ", ajoutée à la banque" : ""))),
      boutonIcone("fermer", "Retirer cette question", () => { e.nouvelles.splice(k, 1); dessiner(); })));
    return h("section", { classe: "cadre pile serree zr-etape-edit" },
      h("div", { classe: "rangee entre" }, h("h4", {}, "Étape " + (i + 1 + fiche)),
        etapes.length > 1 ? bouton("Retirer l'étape", { classe: "p discret danger", icone: "supprimer", onclick: () => { etapes.splice(i, 1); dessiner(); } }) : null),
      h("div", { classe: "champs" }, champ("Titre", titre, { optionnel: true }), champ("Consigne", consigne, { optionnel: true })),
      qs.length || persos.length ? h("ol", { classe: "zr-qs" }, ...qs, ...persos) : h("p", { classe: "aide" }, "Aucune question dans cette étape."),
      h("div", { classe: "rangee" },
        bouton("Ajouter des questions de la banque", { classe: "p", icone: "parchemin", onclick: () => choisirDansBanque(banque, etapes, e, deja, dessiner) }),
        bouton("Écrire une question pour lui", { classe: "p discret", icone: "plume", onclick: () => ecrireQuestion(e, etapes, limites, (B && B.themes) || R.THEMES, dessiner) })));
  };
  remplacer(p.corps, h("p", { classe: "aide" }, etatD.mode === "renvoi"
    ? "Un nouveau questionnaire remplace le précédent. Choisis ses étapes et ses questions."
    : "Ses étapes, pour lui seul : le questionnaire prévu pour ce panneau est déjà là. Ajoute ou retire des questions, écris-en une pour lui."),
  prop.ok ? null : bandeau(prop.erreur || "Le questionnaire prévu n'a pas pu être lu : compose-le ici.", ""), zoneE);
  remplacer(p.pied, bouton("Retour au dossier", { classe: "discret gauche", icone: "gauche", onclick: () => { etatD.vue = "dossier"; rendreDossier(etatD, false); } }), envoyerB);
  dessiner();
}
function choisirDansBanque(banque, etapes, e, deja, apres, themes) {
  themesConnus = listeThemes(themes || (vueJeu("banque") || {}).themes);
  const pris = new Set(etapes.flatMap((x) => x.questions));
  const choix = new Set();
  const pc = pancarte({ titre: "Ajouter des questions", sous: "La banque du recrutement", icone: "parchemin", taille: "large" });
  const f = { q: "" };
  const zoneL = h("div", { classe: "pile" });
  const ok = bouton("Ajouter", { classe: "principal", icone: "ajouter", onclick: () => { e.questions.push(...choix); pc.fermer(); apres(); } });
  const maj = () => {
    const l = banque.filter((q) => !pris.has(String(q.id)) && contient([q.question, q.reponse, q.theme].join(" "), f.q));
    const parTheme = new Map();
    for (const q of l) { const k = q.theme || "autre"; if (!parTheme.has(k)) parTheme.set(k, []); parTheme.get(k).push(q); }
    remplacer(zoneL, ...(l.length ? [...parTheme.entries()].map(([k, qs]) => groupe({ titre: nomTheme(k), compte: qs.length, cle: "zr-bq-" + k, ouvert: !!f.q || parTheme.size <= 3 ? true : undefined },
      () => h("ul", { classe: "banque-liste" }, qs.map((q) => h("li", { classe: "banque-choix" }, caseACocher(h("span", { classe: "banque-q" }, h("span", {}, q.question),
        h("span", { classe: "banque-meta" }, deja.has(String(q.id)) ? h("span", { classe: "marque-deja" }, "déjà posée") : null)), choix.has(String(q.id)),
      (v) => { if (v) choix.add(String(q.id)); else choix.delete(String(q.id)); remplacer(ok, icone("ajouter"), h("span", {}, "Ajouter · " + choix.size)); }, { classe: "case-large" })))))) : [vide("Aucune question ici", "Change la recherche.")]));
  };
  ajouter(pc.corps, [h("div", { classe: "outils" }, recherche("", "Chercher une question…", (q) => { f.q = q; maj(); })), zoneL]);
  ajouter(pc.pied, [bouton("Annuler", { classe: "discret", onclick: () => pc.fermer() }), ok]);
  maj();
}
/** Les thèmes [[clé, nom]] : ceux du serveur (un objet { clé: nom } ou une liste), sinon ceux de la page. */
const listeThemes = (t) => (Array.isArray(t) && t.length ? t.map((x) => (Array.isArray(x) ? x : [x.cle || x.id, x.nom || x.cle]))
  : t && typeof t === "object" && Object.keys(t).length ? Object.entries(t) : R.THEMES);
let themesConnus = R.THEMES;
const nomTheme = (k) => ((themesConnus.find(([c]) => c === k) || [k, k || "Sans thème"])[1]);
function ecrireQuestion(e, etapes, limites, themes, apres) {
  const n_ = etapes.reduce((n, x) => n + x.nouvelles.length, 0);
  if (n_ >= (limites.nouvelles || 10)) { toast((limites.nouvelles || 10) + " questions écrites pour lui au plus.", "erreur"); return; }
  const v = { question: "", reponse: "", variantes: [], theme: "jeu", banque: false };
  const pc = pancarte({ titre: "Une question pour lui", sous: "Jamais la réponse dans la question", icone: "plume", taille: "" });
  const q = zoneTexte({ rows: 3, maxlength: 400, placeholder: "Quel métier répare un navire en pleine mer ?" });
  const r = saisie({ maxlength: 200, placeholder: "Charpentier" });
  const vars = saisie({ maxlength: 400, placeholder: "Autres façons justes, séparées par « ; » (facultatif)" });
  const listeThemes = (Array.isArray(themes) ? themes : Object.entries(themes || {})).map((x) => (Array.isArray(x) ? { v: x[0], l: x[1] } : { v: x.cle || x.id, l: x.nom || x.cle }));
  ajouter(pc.corps, [champ("La question", q), champ("La réponse attendue", r), champ("Variantes admises", vars, { optionnel: true }),
    liste({ valeur: v.theme, label: "Thème", plein: true, options: listeThemes, changer: (x) => { v.theme = x; } }),
    caseACocher("L'ajouter aussi à la banque (pour les prochains candidats)", false, (x) => { v.banque = x; })]);
  ajouter(pc.pied, [bouton("Annuler", { classe: "discret", onclick: () => pc.fermer() }), bouton("Ajouter à l'étape", { classe: "principal", icone: "valider", onclick: () => {
    v.question = q.value.trim(); v.reponse = r.value.trim();
    v.variantes = vars.value.split(";").map((s) => s.trim()).filter(Boolean).slice(0, 20);
    if (v.question.length < 8 || !v.reponse) { toast("Écris la question (8 caractères au moins) et sa réponse attendue.", "erreur"); return; }
    const norme = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    if ([v.reponse, ...v.variantes].some((x) => x.length >= 3 && norme(v.question).includes(norme(x)))) { toast("La réponse attendue apparaît dans la question : reformule-la.", "erreur"); return; }
    e.nouvelles.push(v); pc.fermer(); apres();
  } })]);
  requestAnimationFrame(() => q.focus());
}

// ─── « Voir comme le candidat » (lecture seule) ─────────────────────────
async function voirCommeLeCandidat(D) {
  const pc = pancarte({ titre: "Comme le voit " + nomDe(D.candidat || {}), sous: "Lecture seule : jamais les réponses attendues", icone: "oeil", taille: "large" });
  ajouter(pc.corps, [squelettes(2)]);
  ajouter(pc.pied, [bouton("Fermer", { classe: "discret", onclick: () => pc.fermer() })]);
  const r = await lire("recrutement/apercu", { ticket: D.ticket });
  if (pc.fermee()) return;
  if (!r.ok || !r.donnees) { remplacer(pc.corps, vide("Aperçu indisponible", r.erreur || "Réessaie dans un instant.", "attention")); return; }
  const A = r.donnees;
  const blocs = [];
  if ((A.affiche || []).length) blocs.push(h("h3", {}, "L'affiche, dans son ticket"), discordApercu(A.affiche));
  if ((A.etape || []).length) blocs.push(h("h3", {}, "Le message de l'étape"), discordApercu(A.etape));
  if ((A.pages || []).length) {
    blocs.push(h("h3", {}, "Ses formulaires · " + (A.repondues || 0) + " / " + (A.total || 0) + " répondues"));
    for (const pg of A.pages) blocs.push(h("div", { classe: "zr-fenetre" }, h("div", { classe: "zr-fenetre-titre" }, pg.fenetre || ("Étape " + pg.numero)),
      pg.titre || pg.consigne ? h("p", { classe: "meta" }, [pg.titre, pg.consigne].filter(Boolean).join(" — ")) : null,
      h("ol", { classe: "zr-fenetre-q" }, (pg.questions || []).map((q) => h("li", {}, h("span", { classe: "zr-fenetre-question" }, q.question),
        q.reponse ? h("span", { classe: "zr-fenetre-reponse" }, q.reponse) : h("span", { classe: "meta" }, "pas encore répondu"))))));
  }
  remplacer(pc.corps, ...(blocs.length ? blocs : [vide("Rien à montrer", "Le questionnaire n'est pas encore parti.", "oeil")]));
}
/** Des messages de Discord, rendus comme Discord les affiche (blocs envoyés par le serveur : texte, séparateur,
 *  image, boutons). */
export function discordApercu(cartes) {
  return h("div", { classe: "discord zr-discord" },
    h("div", { classe: "discord-auteur" }, h("span", { classe: "discord-av" }, "G"), h("b", {}, "GoRP"), h("span", { classe: "discord-app" }, "APP")),
    (cartes || []).map((c) => h("div", { classe: "discord-message" }, h("div", { classe: "discord-carte", vars: { "--accent": /^#[0-9a-f]{6}$/i.test(c.couleur || "") && c.couleur !== "#000000" ? c.couleur : "#4f545c" } },
      (c.blocs || []).map(blocDiscord)))));
}
function blocDiscord(b) {
  if (!b) return null;
  if (b.type === "texte") return h("div", { classe: "discord-texte" }, apercuMarkdown(b.texte || ""));
  if (b.type === "separateur") return h("hr", { classe: "discord-sep" });
  if (b.type === "image") {
    //  La bannière de l'affiche (/v/<nom>.png, servie par ce serveur) : l'adresse est vérifiée ici, dom.js ne connaît
    //  pas /v/ (comme les bandeaux des annonces).
    const u = String(b.src || "");
    if (!RE_BANNIERE.test(u)) return h("p", { classe: "discord-vide" }, "(la bannière)");
    const img = h("img", { alt: b.description || "" });
    img.setAttribute("src", u);
    return h("figure", { classe: "discord-media" }, img);
  }
  if (b.type === "boutons") return h("div", { classe: "discord-boutons" }, (b.boutons || []).map((x) => h("span", { classe: "discord-bouton " + (x.lien ? "lien" : STYLES_DISCORD[x.style] || "") + (x.desactive ? " desactive" : "") }, x.libelle || "")));
  if (b.type === "section") return h("div", { classe: "discord-texte" }, (b.blocs || []).map(blocDiscord));
  return null;
}

// ─── La vue en direct (la page du candidat, module de l'équipe « candidature ») ──
function zoneDirect(etatD, D) {
  const z = h("div", { classe: "zr-direct" });
  import("./candidature_direct.js").then((m) => {
    if (!z.isConnected || !m || typeof m.vueEnDirect !== "function") return;
    //  26/10/2026 : ses dernières réponses, ou une étape envoyée — le dossier se relit (la décision, l'étape suivante).
    const v = m.vueEnDirect(Number(D.ticket), {
      surEnvoye: () => { if (etatD.p.fermee()) return; toast("Réponses reçues : " + (nomDe(D.candidat || {}) || "le candidat") + " a tout envoyé.", "succes"); etatD.rendre(true); },
      surEtape: () => { if (etatD.p.fermee()) return; toast("Une étape du questionnaire est arrivée : à toi de décider de la suite.", "succes"); etatD.rendre(true); },
    });
    Promise.resolve(v).then((x) => {
      if (!z.isConnected || !x) return;
      const el = x instanceof Node ? x : x.el;
      if (el instanceof Node) ajouter(z, [el]);
      if (x && typeof x.quitter === "function") etatD.quitterDirect = x.quitter;
    });
  }).catch(() => { z.remove(); });
  return z;
}
function quitterDirect(etatD) { try { if (etatD && etatD.quitterDirect) etatD.quitterDirect(); } catch (e) { /* la vue en direct se ferme seule */ } }

// ═══ LES QUESTIONS ══════════════════════════════════════════════════════
function questionsZone(scene) {
  const haut = h("div", { classe: "pile" });
  const bas = h("div", { classe: "pile" });
  let ctrlChefs = {};
  //  La banque des chefs se construit à la première ouverture de son groupe (le groupe est alors dans la page).
  remplacer(scene, h("p", { classe: "aide" }, "La banque du recrutement, les modèles et les liens donnés au candidat. La fiche et les étapes de chaque panneau se règlent dans Réglages."),
    haut, h("div", { classe: "groupes-zone" }, groupe({ titre: "La banque des chefs d'équipe", icone: "equipage", cle: "zr-banque-chefs" }, () => { ctrlChefs = banqueChefs(bas) || {}; return bas; })));
  const ctrl = R.questionnaire(haut) || {};
  return {
    maj: () => { if (ctrl.maj) ctrl.maj(); },
    majJeu: () => { if (ctrl.majJeu) ctrl.majJeu(); if (ctrlChefs.majJeu) ctrlChefs.majJeu(); },
    majFile: () => { if (ctrl.majFile) ctrl.majFile(); if (ctrlChefs.majFile) ctrlChefs.majFile(); },
  };
}

// ═══ LES RÉGLAGES ═══════════════════════════════════════════════════════
function reglagesZone(scene) {
  const zoneP = h("div", { classe: "pile" }, squelettes(2));
  const groupesZ = h("div", { classe: "groupes-zone" });
  remplacer(scene, zoneP, groupesZ);
  remplacer(groupesZ, ...groupes([
    { cle: "zr-liste-noire", titre: "La liste noire", icone: "cadenas", contenu: () => blocListeNoire() },
    { cle: "zr-nettoyage", titre: "Le nettoyage", icone: "nettoyage", contenu: () => blocNettoyage() },
    { cle: "zr-purge", titre: "La purge exceptionnelle", icone: "attention", contenu: () => blocPurge() },
  ], { ouverts: 0 }));
  let vivant = true;
  const maj = async (forcer) => {
    const PA = await charger(PARCOURS, { forcer });
    if (!vivant || !zoneP.isConnected) return;
    if (!PA || PA.erreur) { remplacer(zoneP, vide("Réglages indisponibles", (PA && PA.erreur) || "Réessaie dans un instant.", "hors_ligne")); return; }
    if (zoneP.querySelector(".zr-parcours.modifie")) return;   // une saisie en cours n'est jamais écrasée
    const panneaux = PA.panneaux || [];
    remplacer(zoneP, ...(panneaux.length ? panneaux.map((x) => blocParcours(PA, x, () => maj(true))) : [vide("Aucun panneau de recrutement", "Dans /configure, choisis le panneau de tickets du clan.", "tickets")]));
  };
  maj(true);
  return { maj: () => maj(false), majJeu: () => maj(false), quitter: () => { vivant = false; } };
}

/** Le parcours d'un panneau : le mode, la fiche, les étapes, l'exigence, le délai, la liste noire, le choix du métier,
 *  puis ses messages dans l'ordre (aperçus de Discord, « Modifier ce message »). */
function blocParcours(PA, x, recharger) {
  const lim = PA.limites || {};
  const v = { mode: x.mode, fiche: (x.fiche || []).map((c) => Object.assign({ options: [], eliminatoires: [] }, c)), gabarit: (x.gabarit || []).map((e) => Object.assign({}, e)),
    exigence: x.exigence, delai: x.delai, liste_noire: x.liste_noire, metier: x.metier };
  const cadre = h("section", { classe: "cadre pile zr-parcours" });
  const marquer = () => { cadre.classList.add("modifie"); };
  protegerZone(cadre, "parcours:" + x.panneau, "le parcours « " + sansEmoji(x.nom) + " »", { des: "saisie", relire: recharger });
  const zoneFiche = h("div", { classe: "pile serree" }), zoneGab = h("div", { classe: "pile serree" });
  const dessinerFiche = () => remplacer(zoneFiche, ...v.fiche.map((c, i) => champFiche(v, c, i, lim, () => { marquer(); dessinerFiche(); })),
    v.fiche.length < (lim.fiche || 5) ? h("div", { classe: "rangee" }, bouton("Ajouter un champ", { classe: "p", icone: "ajouter", onclick: () => { v.fiche.push({ titre: "", type: "court", requis: true, max: 300, options: [], eliminatoires: [] }); marquer(); dessinerFiche(); } }),
      !v.fiche.length && (PA.fiche_conseillee || []).length ? bouton("Partir de la fiche conseillée", { classe: "p discret", icone: "etoile", onclick: () => { v.fiche = PA.fiche_conseillee.map((c) => Object.assign({ options: [], eliminatoires: [] }, JSON.parse(JSON.stringify(c)))); marquer(); dessinerFiche(); } }) : null) : null);
  const dessinerGab = () => remplacer(zoneGab, ...v.gabarit.map((e, i) => etapeGabarit(v, e, i, PA, lim, () => { marquer(); dessinerGab(); }, v.fiche.length || (x.fiche_panneau || []).length ? 1 : 0)),
    v.gabarit.length < (lim.etapes || 8) ? h("div", { classe: "rangee" }, bouton("Ajouter une étape", { classe: "p", icone: "ajouter", onclick: () => { v.gabarit.push({ titre: "", consigne: "", source: "tirage", nombre: 5, theme: "" }); marquer(); dessinerGab(); } })) : null,
    !v.gabarit.length ? h("p", { classe: "aide" }, "Sans étape réglée : une seule étape, la sélection par défaut de la banque (" + quantite((x.annonce || {}).questions || 0, "question(s)") + ").") : null);
  dessinerFiche(); dessinerGab();
  const exig = h("input", { type: "number", classe: "saisie zr-nombre", min: 0, max: 100, value: v.exigence, inputmode: "numeric", "aria-label": "Réponses justes exigées (%)" });
  exig.addEventListener("input", () => { v.exigence = Math.max(0, Math.min(100, Number(exig.value) || 0)); marquer(); });
  const delai = h("input", { type: "number", classe: "saisie zr-nombre", min: (lim.delai || [5])[0], max: (lim.delai || [5, 3600])[1], value: v.delai, inputmode: "numeric", "aria-label": "Délai avant la fermeture (secondes)" });
  delai.addEventListener("input", () => { v.delai = Number(delai.value) || 20; marquer(); });
  const avert = (x.avertissements || []).map((a) => bandeau(h("span", {}, h("b", {}, "« " + a.titre + " » : "), a.raison + ". Garde la fiche minimale et utile à sa candidature."), "rouge"));
  const enregistrer = bouton("Enregistrer le parcours", { classe: "principal", icone: "valider", onclick: async () => {
    const corps = { panneau: x.panneau, version: x.version, mode: v.mode, exigence: v.exigence, delai: v.delai, liste_noire: v.liste_noire, metier: v.metier,
      gabarit: v.gabarit.map(nettoyerEtape), fiche: v.fiche.length ? v.fiche.map(nettoyerChamp) : null };
    if (corps.fiche === null) delete corps.fiche;
    const op = await mettreEnFile(PARCOURS, corps, { genre: "parcours", cle: x.panneau, resume: "Le parcours « " + sansEmoji(x.nom) + " »" });
    cadre.classList.remove("modifie");
    toast(enLigne() ? "Parcours enregistré : il sert dès la prochaine demande." : "Parcours gardé sur l'appareil : il partira au retour de la connexion.", "succes");
    if (op) setTimeout(() => { perime(PARCOURS); recharger(); }, 900);
  } });
  ajouter(cadre, [
    h("div", { classe: "rangee entre" }, h("h3", {}, "Le parcours · " + sansEmoji(x.nom)), x.maj_par && x.maj_le ? h("span", { classe: "meta" }, "réglé par " + nomDe(x.maj_par) + " " + depuis(x.maj_le)) : null),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Le mode"),
      h("div", { classe: "zr-modes", role: "radiogroup", "aria-label": "Le mode du panneau" }, Object.entries(MODES).map(([k, l]) => {
        const b = h("button", { type: "button", classe: "zr-mode", role: "radio", "aria-checked": String(v.mode === k), onclick: () => {
          v.mode = k; marquer();
          for (const y of b.parentNode.children) y.setAttribute("aria-checked", String(y === b));
        } }, h("b", {}, l), h("span", {}, AIDE_MODES[k]));
        return b;
      }))),
    groupe({ titre: "Étape 1 · sa fiche", icone: "candidatures", compte: v.fiche.length || (x.fiche_panneau || []).length, cle: "zr-fiche-" + x.panneau },
      () => [h("p", { classe: "aide" }, "Remplie avant que le ticket existe (5 champs au plus) : une tranche d'âge plutôt qu'une date de naissance, jamais son pseudo Discord ni une donnée sensible. Un choix « éliminatoire » n'ouvre aucun ticket."),
        ...avert, x.fiche_reglee ? null : h("p", { classe: "meta" }, "Pas encore réglée ici : le bot pose les questions du panneau (/configure)."), zoneFiche]),
    v.mode === "direct" && !v.gabarit.length ? null : groupe({ titre: "Les étapes du questionnaire", icone: "parchemin", compte: v.gabarit.length || 1, cle: "zr-gab-" + x.panneau },
      () => [h("p", { classe: "aide" }, "Une étape à la fois : la direction ouvre la suivante quand elle a lu ses réponses. En approbation, ces étapes sont proposées, puis modifiables pour chaque candidat."), zoneGab]),
    h("div", { classe: "champs zr-reglages-ligne" },
      champ("Réponses justes exigées (%)", exig, { aide: "100 % par défaut. Accepter en dessous demande une confirmation." }),
      champ("Délai avant la fermeture (s)", delai, { aide: "Le temps de lire la décision avant que le ticket se ferme." })),
    interrupteur("Au refus : la liste noire (il ne pourra plus ouvrir de demande)", v.liste_noire, (b) => { v.liste_noire = b; marquer(); }),
    interrupteur("À l'acceptation : la carte du choix du métier", v.metier, (b) => { v.metier = b; marquer(); }),
    h("div", { classe: "rangee droite" }, enregistrer),
    groupe({ titre: "Ses messages, dans l'ordre", icone: "discord", compte: (x.messages || []).length, cle: "zr-msg-" + x.panneau }, () => blocMessages(x, recharger)),
  ]);
  return cadre;
}
function nettoyerChamp(c) {
  const o = { titre: String(c.titre || "").trim(), aide: String(c.aide || "").trim(), exemple: String(c.exemple || "").trim(), type: c.type || "court", requis: c.requis !== false };
  if (o.type === "choix") { o.options = (c.options || []).map((s) => String(s).trim()).filter(Boolean); o.eliminatoires = (c.eliminatoires || []).filter((s) => o.options.includes(s)); }
  else o.max = Number(c.max) || 300;
  return o;
}
function nettoyerEtape(e) {
  const o = { titre: String(e.titre || "").trim(), consigne: String(e.consigne || "").trim(), source: e.source || "defaut" };
  if (o.source === "tirage") { o.nombre = Math.max(1, Number(e.nombre) || 1); o.theme = e.theme || ""; }
  if (o.source === "modele") o.modele = e.modele || "";
  if (o.source === "questions") o.questions = (e.questions || []).slice();
  return o;
}
function champFiche(v, c, i, lim, apres) {
  const titre = saisie({ value: c.titre || "", maxlength: lim.champ_titre || 45, placeholder: "Tranche d'âge", "aria-label": "Titre du champ " + (i + 1) });
  titre.addEventListener("input", () => { c.titre = titre.value; titre.closest(".zr-parcours") && titre.closest(".zr-parcours").classList.add("modifie"); });
  const aide = saisie({ value: c.aide || "", maxlength: lim.champ_aide || 100, placeholder: "Pourquoi on le demande (facultatif)", "aria-label": "Aide du champ " + (i + 1) });
  aide.addEventListener("input", () => { c.aide = aide.value; aide.closest(".zr-parcours") && aide.closest(".zr-parcours").classList.add("modifie"); });
  const options = c.type === "choix" ? h("div", { classe: "pile serree" },
    h("span", { classe: "champ-lib" }, "Les choix (cocher : éliminatoire, aucun ticket n'est créé)"),
    ...(c.options || []).map((o, k) => h("div", { classe: "rangee zr-option" },
      caseACocher(o, (c.eliminatoires || []).includes(o), (b) => { c.eliminatoires = b ? [...(c.eliminatoires || []), o] : (c.eliminatoires || []).filter((x) => x !== o); apres(); }, { aria: "Éliminatoire : " + o }),
      boutonIcone("fermer", "Retirer le choix « " + o + " »", () => { c.options.splice(k, 1); c.eliminatoires = (c.eliminatoires || []).filter((x) => x !== o); apres(); }))),
    (() => { const s = saisie({ maxlength: lim.option || 100, placeholder: "Ajoute un choix puis Entrée", "aria-label": "Nouveau choix" });
      s.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const t = s.value.trim(); if (t && !(c.options || []).includes(t) && (c.options || []).length < (lim.options || 25)) { c.options = [...(c.options || []), t]; apres(); } } });
      return s; })()) : null;
  return h("div", { classe: "zr-champ" },
    h("div", { classe: "rangee entre" }, h("b", {}, "Champ " + (i + 1)),
      h("div", { classe: "rangee" }, liste({ valeur: c.type || "court", label: "Type", options: TYPES_CHAMP.map(([k, l]) => ({ v: k, l })), changer: (t) => { c.type = t; apres(); } }),
        interrupteur("Obligatoire", c.requis !== false, (b) => { c.requis = b; apres(); }),
        boutonIcone("supprimer", "Retirer ce champ", () => { v.fiche.splice(i, 1); apres(); }))),
    h("div", { classe: "champs" }, champ("Titre", titre), champ("Aide", aide, { optionnel: true })), options);
}
function etapeGabarit(v, e, i, PA, lim, apres, decalage) {
  const titre = saisie({ value: e.titre || "", maxlength: lim.etape_titre || 80, placeholder: "Le jeu", "aria-label": "Titre de l'étape " + (i + 1) });
  titre.addEventListener("input", () => { e.titre = titre.value; titre.closest(".zr-parcours") && titre.closest(".zr-parcours").classList.add("modifie"); });
  const consigne = saisie({ value: e.consigne || "", maxlength: lim.etape_consigne || 200, placeholder: "Ce qu'il doit savoir (facultatif)", "aria-label": "Consigne de l'étape " + (i + 1) });
  consigne.addEventListener("input", () => { e.consigne = consigne.value; consigne.closest(".zr-parcours") && consigne.closest(".zr-parcours").classList.add("modifie"); });
  let detail = null;
  if (e.source === "tirage") {
    const n = h("input", { type: "number", classe: "saisie zr-nombre", min: 1, max: lim.par_envoi || 40, value: e.nombre || 5, inputmode: "numeric", "aria-label": "Nombre de questions tirées" });
    n.addEventListener("input", () => { e.nombre = Math.max(1, Number(n.value) || 1); n.closest(".zr-parcours") && n.closest(".zr-parcours").classList.add("modifie"); });
    const themes = listeThemes(PA.themes).map(([k, l]) => ({ v: k, l }));
    detail = h("div", { classe: "champs" }, champ("Questions tirées", n),
      liste({ valeur: e.theme || "", label: "Thème", options: [{ v: "", l: "Tous les thèmes" }, ...themes], changer: (t) => { e.theme = t; apres(); } }));
  } else if (e.source === "modele") {
    detail = liste({ valeur: e.modele || "", label: "Modèle", plein: true, options: [{ v: "", l: "Choisir…" }, ...(PA.modeles || []).map((m) => ({ v: m.id, l: sansEmoji(m.nom) + " · " + compte(m.questions, "question") }))], changer: (m) => { e.modele = m; apres(); } });
  } else if (e.source === "questions") {
    detail = h("div", { classe: "rangee" }, h("span", { classe: "meta" }, quantite((e.questions || []).length, "question(s) choisie(s)")),
      bouton("Choisir les questions", { classe: "p", icone: "parchemin", onclick: async () => {
        const B = await charger("banque");
        const banque = ((B && B.questions) || []).filter((q) => q.actif !== false && !q.retiree);
        const tmp = { questions: (e.questions || []).slice(), nouvelles: [] };
        choisirDansBanque(banque, [{ questions: [] }], tmp, new Set(), () => { e.questions = tmp.questions; apres(); });
      } }));
  }
  return h("div", { classe: "zr-champ" },
    h("div", { classe: "rangee entre" }, h("b", {}, "Étape " + (i + 1 + decalage)),
      h("div", { classe: "rangee" }, liste({ valeur: e.source || "defaut", label: "Les questions", options: SOURCES.map(([k, l]) => ({ v: k, l })), changer: (s) => { e.source = s; apres(); } }),
        boutonIcone("haut", "Monter l'étape", () => { if (i > 0) { [v.gabarit[i - 1], v.gabarit[i]] = [v.gabarit[i], v.gabarit[i - 1]]; apres(); } }),
        boutonIcone("supprimer", "Retirer l'étape", () => { v.gabarit.splice(i, 1); apres(); }))),
    h("div", { classe: "champs" }, champ("Titre", titre, { optionnel: true }), champ("Consigne", consigne, { optionnel: true })), detail);
}
/** Les messages du parcours, dans l'ordre où ils apparaissent : où, quand, l'aperçu de Discord, « Modifier ce message ». */
function blocMessages(x, recharger) {
  return h("ol", { classe: "zr-messages" }, (x.messages || []).map((m, i) => h("li", { classe: "zr-message" },
    h("div", { classe: "zr-message-tete" }, h("span", { classe: "selection-num" }, String(i + 1)),
      h("div", { classe: "bloc" }, h("b", {}, m.titre), h("span", { classe: "meta" }, " — " + m.ou + " · " + m.quand)),
      (m.cles || []).length ? bouton("Modifier ce message", { classe: "p discret", icone: "plume", onclick: () => modifierMessage(m, recharger) }) : null),
    m.fiche ? apercuFiche(m) : (m.blocs || []).length ? discordApercu(m.blocs) : null)));
}
function apercuFiche(m) {
  return h("div", { classe: "zr-fenetre" }, h("div", { classe: "zr-fenetre-titre" }, m.titre_fenetre || "Ta fiche"),
    h("ol", { classe: "zr-fenetre-q" }, (m.fiche || []).map((c) => h("li", {}, h("span", { classe: "zr-fenetre-question" }, c.titre + (c.requis === false ? " (facultatif)" : "")),
      c.aide ? h("span", { classe: "meta" }, c.aide) : null,
      c.type === "choix" ? h("span", { classe: "meta" }, (c.options || []).map((o) => o + ((c.eliminatoires || []).includes(o) ? " (éliminatoire)" : "")).join(" · ")) : null))));
}
async function modifierMessage(m, recharger) {
  const cles = m.cles || [];
  const apres = () => { perime(PARCOURS); recharger(); };
  if (cles.length === 1) { await modifierTexte(cles[0], { apres }); return; }
  //  Le nom de chaque texte (Textes & noms), jamais sa clé technique.
  const T = await charger("textes");
  const titres = new Map();
  for (const g of (T && T.groupes) || []) for (const t of g.textes || []) titres.set(t.cle, t.titre || t.cle);
  const pc = pancarte({ titre: "Modifier : " + m.titre, sous: "Chaque texte de ce message", icone: "plume", taille: "" });
  ajouter(pc.corps, [h("p", { classe: "aide" }, "Choisis le texte à réécrire : enregistré, il sert dès le message suivant."),
    h("div", { classe: "pile serree" }, cles.map((c) => bouton(titres.get(c) || c, { classe: "p zr-cle", icone: "plume", onclick: () => { pc.fermer(); modifierTexte(c, { apres }); } })))]);
  ajouter(pc.pied, [bouton("Fermer", { classe: "discret", onclick: () => pc.fermer() })]);
}

// ─── La liste noire ─────────────────────────────────────────────────────
function blocListeNoire() {
  const zoneL = h("div", { classe: "pile serree" }, squelettes(2));
  const f = { q: "" };
  const maj = async () => {
    const r = await lire("recrutement/liste_noire");
    if (!zoneL.isConnected) return;
    if (!r.ok || !r.donnees) { remplacer(zoneL, vide("Liste noire indisponible", r.erreur || "", "hors_ligne")); return; }
    const L = r.donnees;
    const actifs = (L.actifs || []).filter((x) => contient([nomDe(x.membre || {}), x.motif, x.membre && x.membre.id].join(" "), f.q));
    remplacer(zoneL,
      h("p", { classe: "aide" }, "Qui ne peut plus ouvrir de demande de recrutement : depuis quand, pourquoi, par qui. « Lever » lui rend le droit de candidater."),
      h("div", { classe: "outils" }, recherche(f.q, "Nom, motif…", (q) => { f.q = q; maj(); }),
        peutAgir() && (L.actifs || []).length ? bouton("Tout lever", { classe: "p danger", icone: "annuler", reseau: true, onclick: () => leverTout(L, maj) }) : null),
      actifs.length ? h("div", { classe: "groupes-zone" }, groupes(parPeriode_(actifs).map(([k, lib, l]) => ({ cle: "zr-ln-" + k, titre: lib, compte: l.length,
        contenu: () => lignes("zr-ln-" + k, l, (x) => ligneListeNoire(x, maj)) })), { ouverts: 2, forcer: !!f.q }))
        : vide("Personne sur la liste noire", "", "succes"),
      (L.leves || []).length ? groupe({ titre: "Levées récemment", compte: L.leves.length, cle: "zr-ln-leves" }, () => lignes("zr-ln-leves", L.leves, (x) => ligne({
        visuel: avatar(x.membre || {}, "p"), titre: nomDe(x.membre || {}), sous: ["levée par " + nomDe(x.leve_par || {}), x.motif].filter(Boolean).join(" · "), ...quandLigne(x.leve_le) }))) : null);
    majBoutonsReseau(zoneL);
  };
  maj();
  return zoneL;
}
function parPeriode_(l) {
  const PER = [["mois", "Ce mois-ci", 31], ["trimestre", "Ces trois derniers mois", 92], ["annee", "Cette année", 366], ["avant", "Plus ancien", Infinity]];
  const n = Date.now() / 1000, out = PER.map(([k, lib]) => [k, lib, []]);
  for (const x of l) { const age = x.depuis ? (n - x.depuis) / 86400 : Infinity; out[PER.findIndex(([, , j]) => age <= j)][2].push(x); }
  return out.filter(([, , g]) => g.length);
}
function ligneListeNoire(x, maj) {
  const m = x.membre || {};
  retenirPersonnes({ [String(m.id)]: m });
  return ligne({
    visuel: avatar(m, "p"), titre: nomDe(m),
    sous: x.ancien ? "posée avant le site (bouton « Blacklist » d'un ticket)" : [x.motif || "sans motif", x.par ? "par " + nomDe(x.par) : "", quantite(x.candidatures || 0, "candidature(s)")].filter(Boolean).join(" · "),
    badges: [x.ancien ? pastille("Ancienne", "#4a5560") : null], ...quandLigne(x.depuis),
    actions: [x.transcript ? { icone: "parchemin", libelle: "Le transcript", href: x.transcript } : null, x.ticket ? { icone: "candidatures", libelle: "Le dossier", onclick: () => ouvrirDossier(x.ticket) } : null,
      peutAgir() ? { icone: "valider", libelle: "Lever", texte: true, reseau: true, onclick: async () => {
        const ok = await confirmer({ titre: "Lever la liste noire de " + nomDe(m) + " ?", texte: "Il pourra de nouveau ouvrir une demande de recrutement.", libelleOk: "Lever" });
        if (!ok) return;
        const r = await poster("recrutement/liste_noire/lever", { membre: String(m.id) });
        toast(r.ok ? r.donnees.message : r.erreur, r.ok ? "succes" : "erreur");
        if (r.ok) maj();
      } } : null].filter(Boolean),
    ouvrir: () => ouvrirFiche(m.id), libelleOuvrir: "Ouvrir la fiche de " + nomDe(m),
  });
}
async function leverTout(L, maj) {
  const ok = await confirmer({ titre: "Lever toute la liste noire ?", icone: "attention", style: "danger", libelleOk: "Tout lever",
    texte: quantite(L.total || 0, "personne(s)") + " pourront de nouveau candidater. Journalisé.", mot: L.confirmation || "LEVER" });
  if (!ok) return;
  const r = await poster("recrutement/liste_noire/lever", { tout: true, confirmation: L.confirmation || "LEVER" });
  toast(r.ok ? r.donnees.message : r.erreur, r.ok ? "succes" : "erreur");
  if (r.ok) maj();
}

// ─── Le nettoyage ───────────────────────────────────────────────────────
function blocNettoyage() {
  const z = h("div", { classe: "pile serree" }, squelettes(1));
  const maj = async () => {
    const r = await lire("recrutement/nettoyage");
    if (!z.isConnected) return;
    if (!r.ok || !r.donnees) { remplacer(z, vide("Nettoyage indisponible", r.erreur || "", "hors_ligne")); return; }
    const regles = r.donnees.regles || [];
    const total = regles.reduce((n, x) => n + (x.a_retirer || 0), 0);
    remplacer(z, h("p", { classe: "aide" }, "Combien de temps le recrutement garde ses traces. Les durées se règlent dans Le Port, Nettoyage (le même réglage partout)."),
      h("ul", { classe: "lignes-c" }, regles.map((x) => ligne({ visuel: pastilleIcone("nettoyage", "#4a5560"), titre: x.nom,
        sous: x.quoi + " · gardé " + quantite(x.garde_jours, "jour(s)"), badges: [x.a_retirer ? tampon(quantite(x.a_retirer, "à retirer"), "ambre", true) : tampon("Rien à retirer", "vert", true)] }))),
      h("div", { classe: "rangee" }, bouton("Régler les durées", { classe: "p discret", icone: "cle", onclick: () => { location.hash = "#port/nettoyage"; } }),
        peutAgir() ? bouton("Nettoyer maintenant" + (total ? " · " + total : ""), { classe: "p", icone: "nettoyage", reseau: true, disabled: !total, onclick: async () => {
          const ok = await confirmer({ titre: "Nettoyer maintenant ?", texte: quantite(total, "élément(s)") + " plus vieux que leur durée sont retirés. Une entrée active de la liste noire reste toujours.", libelleOk: "Nettoyer" });
          if (!ok) return;
          const rep = await poster("recrutement/nettoyage", {});
          toast(rep.ok ? rep.donnees.message : rep.erreur, rep.ok ? "succes" : "erreur");
          if (rep.ok) maj();
        } }) : null));
    majBoutonsReseau(z);
  };
  maj();
  return z;
}

// ─── La purge exceptionnelle (irréversible, jamais automatique) ─────────
function blocPurge() {
  const z = h("div", { classe: "pile serree" });
  remplacer(z, bandeau(h("span", {}, h("b", {}, "Irréversible. "), "Efface tout ce qui reste des candidatures refusées de ceux qui n'ont jamais été acceptés et n'ont aucune demande en cours : tickets, transcripts, réponses, journal de leur candidature, liste noire. Jamais leurs sanctions, ni leurs autres tickets."), "rouge"),
    h("div", { classe: "rangee" }, bouton("Voir ce qui serait effacé", { classe: "p", icone: "oeil", onclick: () => apercuPurge(z) })));
  return z;
}
async function apercuPurge(z) {
  const r = await lire("recrutement/purge");
  if (!r.ok || !r.donnees) { toast(r.erreur || "Aperçu impossible.", "erreur"); return; }
  const A = r.donnees;
  const pc = pancarte({ titre: "La purge exceptionnelle", sous: "Aperçu : rien n'est effacé ici", icone: "attention", taille: "large" });
  ajouter(pc.corps, [
    h("p", {}, A.total_personnes ? quantite(A.total_personnes, "personne(s)") + " · " + quantite(A.total_candidatures, "candidature(s) refusée(s)") + " · " + taille(A.total_octets) + " de transcripts." : "Personne n'est concerné : rien à effacer."),
    A.total_personnes ? lignes("zr-purge", A.personnes || [], (x) => ligne({ visuel: avatar(x.membre || {}, "p"), titre: nomDe(x.membre || {}),
      sous: [quantite(x.tickets, "ticket(s) refusé(s)"), x.elimines ? quantite(x.elimines, "élimination(s)") : "", x.premier ? "du " + date(x.premier) + " au " + date(x.dernier) : "", taille(x.octets)].filter(Boolean).join(" · ") })) : null]);
  ajouter(pc.pied, [bouton("Fermer", { classe: "discret", onclick: () => pc.fermer() }), A.total_personnes && peutAgir() ? bouton("Purger…", { classe: "danger", icone: "supprimer", reseau: true, onclick: async () => {
    const ok = await confirmer({ titre: "Purger définitivement ?", icone: "attention", style: "danger", libelleOk: "Purger", mot: A.confirmation || "PURGER",
      texte: quantite(A.total_candidatures, "candidature(s) refusée(s)") + " de " + quantite(A.total_personnes, "personne(s)") + " effacées pour toujours. Elles pourront recandidater." });
    if (!ok) return;
    const rep = await poster("recrutement/purge", { confirmation: A.confirmation || "PURGER" });
    toast(rep.ok ? rep.donnees.message : rep.erreur, rep.ok ? "succes" : "erreur");
    if (rep.ok) { pc.fermer(); rafraichir(); }
  } }) : null]);
  majBoutonsReseau(pc.pied);
  z.dataset.vu = "1";
}
const taille = (o) => (o >= 1048576 ? (o / 1048576).toFixed(1).replace(".", ",") + " Mo" : o >= 1024 ? Math.round(o / 1024) + " Ko" : nombre(o || 0) + " octets");

