// recrutement_chefs.js — les chefs d'équipe (26/10/2026). Proposer à un membre DU CLAN d'être chef de son métier, son
// questionnaire (la banque des chefs, à part de celle du recrutement ; un gabarit par métier), la correction à 100 %
// (jamais forcée), la décision, le rôle « Chef · <métier> », « Retirer le titre de chef » — et, sur la fiche d'un
// membre, sa pastille « Chef d'équipe · <métier> » et « Proposer d'être chef ».

import { h, icone, date, depuis, sansEmoji, contient, remplacer, compte, quantite, ajouter } from "./dom.js";
import { peutAgir, enLigne, emettre, ecouter, retenirPersonnes } from "./noyau.js";
import { lire, poster } from "./api.js";
import { charger, perime } from "./donnees.js";
import { mettreEnFile } from "./hors_ligne.js";
import {
  bouton, boutonIcone, avatar, pastille, tampon, vide, tuile, tuiles, recherche, liste, champ, saisie, zoneTexte,
  caseACocher, confirmer, pancarte, toast, squelettes, groupe, bandeau, nomDe, majBoutonsReseau,
} from "./ui.js";
import { ligne, lignes, groupes, quandLigne, pastilleIcone } from "./rangement.js";
import { avecVerrou, protegerEditeur, siLibre } from "./direct.js";
import * as R from "./recrutement.js";

export const CHEFS = "recrutement/chefs";
const ETATS = { en_cours: ["Il répond", "mer"], corriger: ["À corriger", ""], attente: ["En attente", "ambre"], accepte: ["Nommé chef", "vert"], refuse: ["Refusé", "encre"] };
const justeDe = (q) => ("juste" in q ? q.juste : q.correction ? q.correction.juste : null);
const nomMetier = (C, k) => (k === (C && C.tous) || k === "tous" ? "Tous les métiers" : (((C && C.metiers) || []).find((m) => m.cle === k) || { nom: k }).nom);

// ═══ LA PAGE DES CHEFS ═════════════════════════════════════════════════
export function chefsZone(scene) {
  const f = { q: "" };
  const resultats = h("div", { classe: "pile" }, squelettes(3));
  remplacer(scene, resultats);
  let vivant = true;
  async function maj(forcer) {
    const C = await charger(CHEFS, { forcer });
    if (!vivant || !resultats.isConnected) return;
    if (!C || C.erreur) { remplacer(resultats, vide("Chefs d'équipe indisponibles", (C && C.erreur) || "Réessaie dans un instant.", "hors_ligne")); return; }
    for (const m of C.membres || []) retenirPersonnes({ [String(m.id)]: m });
    const cands = C.candidatures || [];
    const par = { corriger: cands.filter((x) => x.etat === "corriger"), en_cours: cands.filter((x) => x.etat === "en_cours" || x.etat === "attente"),
      decidees: cands.filter((x) => x.etat === "accepte" || x.etat === "refuse") };
    const enCours = new Set([...par.corriger, ...par.en_cours].map((x) => String(x.membre.id)));
    const membres = (C.membres || []).filter((m) => contient([nomDe(m), m.pseudo, (m.metiers || []).map((k) => nomMetier(C, k)).join(" ")].join(" "), f.q));
    remplacer(resultats,
      tuiles(tuile({ cle: "zc-1", lib: "Chefs nommés", val: (C.chefs || []).length, icone: "etoile", teinte: "#3f6b3a" }),
        tuile({ cle: "zc-2", lib: "À corriger", val: par.corriger.length, icone: "plume", teinte: "#8e2a24" }),
        tuile({ cle: "zc-3", lib: "En cours", val: par.en_cours.length, icone: "minuteur", sous: "il répond, ou en attente", teinte: "#1f4e5a" })),
      h("p", { classe: "aide" }, "Un chef d'équipe est un membre du clan qui répond à un questionnaire de son métier (la banque des chefs). " + (C.exigence || 100) + " % de réponses justes : jamais moins, jamais forcé."),
      h("div", { classe: "groupes-zone" }, groupes([
        //  Un groupe vide ne prend pas de place.
        par.corriger.length ? { cle: "zc-corriger", titre: "À corriger", icone: "plume", compte: par.corriger.length, chaud: true,
          contenu: () => lignes("zc-corriger", par.corriger, (x) => ligneCandidature(C, x)) } : null,
        par.en_cours.length ? { cle: "zc-encours", titre: "En cours", icone: "minuteur", compte: par.en_cours.length,
          contenu: () => lignes("zc-encours", par.en_cours, (x) => ligneCandidature(C, x)) } : null,
        { cle: "zc-chefs", titre: "Les chefs d'équipe", icone: "etoile", compte: (C.chefs || []).length,
          contenu: () => ((C.chefs || []).length ? lignes("zc-chefs", C.chefs, (x) => ligneChef(C, x, () => maj(true))) : vide("Aucun chef nommé", "Propose un membre du clan ci-dessous.", "etoile")) },
        { cle: "zc-proposer", titre: "Proposer d'être chef", icone: "membres", compte: (C.membres || []).length, info: "les membres du clan",
          contenu: () => h("div", { classe: "pile serree" }, h("div", { classe: "outils" }, recherche(f.q, "Nom, métier…", (q) => { f.q = q; maj(false); })),
            membres.length ? lignes("zc-membres", membres, (m) => ligneMembre(C, m, enCours.has(String(m.id)), () => maj(true))) : vide("Aucun membre du clan trouvé", "", "membres")) },
        { cle: "zc-roles", titre: "Les rôles des chefs", icone: "roles", compte: Object.keys(C.roles || {}).length, contenu: () => blocRoles(C, () => maj(true)) },
        par.decidees.length ? { cle: "zc-decidees", titre: "Décidées (30 jours)", icone: "coffre", compte: par.decidees.length,
          contenu: () => lignes("zc-decidees", par.decidees, (x) => ligneCandidature(C, x)) } : null,
      ], { ouverts: 3, forcer: !!f.q })));
    majBoutonsReseau(resultats);
  }
  maj(true);
  return { maj: () => maj(false), majJeu: () => maj(false), quitter: () => { vivant = false; } };
}
function ligneCandidature(C, x) {
  const [lib, coul] = ETATS[x.etat] || [x.etat, "encre"];
  const b = x.bilan || {};
  return avecVerrou(ligne({
    visuel: avatar(x.membre, "p"), titre: nomDe(x.membre),
    sous: ["Chef · " + (x.metier_nom || nomMetier(C, x.metier)), x.etapes > 1 && x.etape_ouverte ? "étape " + x.etape_ouverte + " sur " + x.etapes : "",
      b.repondues ? b.justes + " / " + b.total + " justes" : "", x.decide_par ? "par " + nomDe(x.decide_par) : ""].filter(Boolean).join(" · "),
    badges: [tampon(lib, coul, true)], ...quandLigne(x.decide_le || x.cree_le), etat: x.etat === "corriger" ? "alerte" : null,
    ouvrir: () => ouvrirCandidatureChef(x.envoi), libelleOuvrir: "Ouvrir la candidature de chef de " + nomDe(x.membre), donnees: { envoi: x.envoi },
  }), "chef:" + x.envoi);
}
function ligneChef(C, x, recharger) {
  return ligne({
    visuel: avatar(x.membre, "p"), titre: nomDe(x.membre), sous: "Chef d'équipe · " + (x.metier_nom || nomMetier(C, x.metier)) + (x.depuis ? " · depuis le " + date(x.depuis) : ""),
    badges: [pastille("Chef · " + (x.metier_nom || nomMetier(C, x.metier)), "#3f6b3a")],
    actions: peutAgir() ? [{ icone: "annuler", libelle: "Retirer le titre", danger: true, reseau: true, onclick: () => retirerTitre(x, recharger) }] : [],
  });
}
function ligneMembre(C, m, enCours, recharger) {
  const chef = m.chef;
  return ligne({
    visuel: avatar(m, "p"), titre: nomDe(m), sous: [(m.metiers || []).map((k) => nomMetier(C, k)).join(", ") || "aucun métier choisi"].join(" · "),
    badges: [chef ? pastille("Chef · " + nomMetier(C, chef.metier), "#3f6b3a") : null, enCours ? tampon("Candidature en cours", "mer", true) : null],
    actions: peutAgir() && !chef && !enCours ? [{ icone: "etoile", libelle: "Proposer d'être chef", texte: true, reseau: true, onclick: () => proposerChef(m, C, recharger) }] : [],
  });
}
async function retirerTitre(x, recharger) {
  const ok = await confirmer({ titre: "Retirer le titre de chef de " + nomDe(x.membre) + " ?", style: "danger", libelleOk: "Retirer le titre",
    texte: "Son titre de chef et son rôle de chef (celui-là seulement) lui sont retirés. Il reste du clan." });
  if (!ok) return;
  const r = await poster("recrutement/chefs/retirer", { membre: String(x.membre.id) });
  toast(r.ok ? r.donnees.message : r.erreur, r.ok ? "succes" : "erreur");
  if (r.ok) { perime(CHEFS); recharger(); }
}

// ─── Les rôles des chefs, métier par métier ─────────────────────────────
function blocRoles(C, recharger) {
  const z = h("div", { classe: "pile serree" }, squelettes(1));
  charger("roles").then((RO) => {
    if (!z.isConnected) return;
    const roles = ((RO && RO.roles) || []).map((r) => ({ v: String(r.id), l: sansEmoji(r.nom) || "Rôle", teinte: r.couleur || null }));
    remplacer(z, h("p", { classe: "aide" }, "Le rôle donné à l'acceptation d'un chef de ce métier, et retiré avec son titre. Jamais un autre rôle : le bot le vérifie (sous son rôle, sans droit de gestion)."),
      h("ul", { classe: "lignes-c" }, (C.metiers || []).map((m) => {
        const r = (C.roles || {})[m.cle];
        return ligne({ visuel: pastilleIcone("roles", "#7a4b2a"), titre: m.nom,
          sous: r ? (r.existe ? "Rôle « " + sansEmoji(r.nom) + " »" + (r.refus ? " — " + r.refus : "") : "Le rôle a disparu de Discord") : "Aucun rôle : le titre seul",
          badges: [r && r.refus ? pastille("À revoir", "#8e2a24") : null],
          actions: peutAgir() ? [{ noeud: liste({ valeur: r ? r.id : "", label: "Rôle des chefs " + m.nom, cacherLabel: true, options: [{ v: "", l: "Aucun rôle" }, { v: "creer", l: "Créer « Chef · " + m.nom + " »" }, ...roles],
            changer: async (v) => {
              if (!siLibre("chef_role:" + m.cle)) return;
              const corps = v === "creer" ? { metier: m.cle, creer: true } : { metier: m.cle, role: v || null };
              const rep = await poster("recrutement/chefs/role", corps);
              toast(rep.ok ? "Rôle des chefs " + m.nom + " enregistré." : rep.erreur, rep.ok ? "succes" : "erreur");
              perime(CHEFS); recharger();
            } }) }] : [],
        });
      })));
  });
  return z;
}

// ─── Proposer d'être chef : le métier, ses étapes, l'aperçu, l'envoi ────
export async function proposerChef(m, C0, recharger) {
  const C = C0 || await charger(CHEFS);
  if (!C || C.erreur) { toast("Les chefs d'équipe ne sont pas lisibles pour le moment.", "erreur"); return; }
  const p = pancarte({ titre: "Proposer d'être chef", sous: nomDe(m), icone: "etoile", taille: "large" });
  protegerEditeur(p, "chef_membre:" + m.id, "la proposition de chef de " + nomDe(m));
  const etat_ = { metier: (m.metiers || [])[0] || ((C.metiers || [])[0] || {}).cle || "", etapes: [], banque: [] };
  const zoneE = h("div", { classe: "pile" });
  const envoyerB = bouton("Envoyer le questionnaire", { classe: "principal", icone: "cloche", reseau: true, onclick: () => envoyer() });
  const charger_ = async () => {
    remplacer(zoneE, squelettes(1));
    const r = await lire("recrutement/chefs/proposition", { membre: String(m.id), metier: etat_.metier });
    if (p.fermee()) return;
    if (!r.ok || !r.donnees) { remplacer(zoneE, vide("Proposition impossible", r.erreur || "", "attention")); envoyerB.disabled = true; return; }
    etat_.banque = r.donnees.banque || [];
    etat_.etapes = (r.donnees.etapes || []).map((e) => ({ titre: e.titre || "", consigne: e.consigne || "", questions: (e.questions || []).slice() }));
    if (!etat_.etapes.length) etat_.etapes = [{ titre: "", consigne: "", questions: [] }];
    dessiner();
  };
  const dessiner = () => {
    const parId = new Map(etat_.banque.map((q) => [q.id, q]));
    const total = etat_.etapes.reduce((n, e) => n + e.questions.length, 0);
    remplacer(zoneE,
      etat_.banque.length ? null : bandeau("La banque des chefs n'a aucune question pour ce métier : ajoute-en dans Questions, « La banque des chefs d'équipe ».", "rouge"),
      ...etat_.etapes.map((e, i) => h("section", { classe: "cadre pile serree zr-etape-edit" },
        h("div", { classe: "rangee entre" }, h("h4", {}, "Étape " + (i + 1)),
          etat_.etapes.length > 1 ? bouton("Retirer l'étape", { classe: "p discret danger", icone: "supprimer", onclick: () => { etat_.etapes.splice(i, 1); dessiner(); } }) : null),
        champ("Titre", (() => { const s = saisie({ value: e.titre, maxlength: 80, placeholder: "La mer, le navire…" }); s.addEventListener("input", () => { e.titre = s.value; }); return s; })(), { optionnel: true }),
        h("ul", { classe: "banque-liste" }, etat_.banque.map((q) => h("li", { classe: "banque-choix" }, caseACocher(h("span", { classe: "banque-q" }, h("span", {}, q.question),
          h("span", { classe: "banque-meta" }, (q.metiers || []).map((k) => nomMetier(C, k)).join(", "))), e.questions.includes(q.id),
        (v) => { const autres = etat_.etapes.filter((x) => x !== e); if (v) { for (const x of autres) x.questions = x.questions.filter((y) => y !== q.id); e.questions.push(q.id); } else e.questions = e.questions.filter((y) => y !== q.id); dessiner(); },
        { classe: "case-large" })))))),
      etat_.etapes.length < 8 ? h("div", { classe: "rangee" }, bouton("Ajouter une étape", { classe: "p", icone: "ajouter", onclick: () => { etat_.etapes.push({ titre: "", consigne: "", questions: [] }); dessiner(); } })) : null,
      h("div", { classe: "cadre pile serree" }, h("h4", {}, "Aperçu"), h("ol", { classe: "zr-etapes-resume" }, etat_.etapes.map((e, i) => h("li", {},
        h("b", {}, "Étape " + (i + 1) + (e.titre ? " · " + e.titre : "")), h("span", { classe: "meta" }, " — " + quantite(e.questions.length, "question(s)")),
        h("ul", {}, e.questions.map((id) => h("li", { classe: "meta" }, (parId.get(id) || {}).question || id))))))));
    remplacer(envoyerB, icone("cloche"), h("span", {}, "Envoyer · " + compte(total, "question")));
    envoyerB.disabled = !total || !enLigne();
  };
  async function envoyer() {
    const etapes = etat_.etapes.filter((e) => e.questions.length).map((e) => ({ titre: e.titre.trim(), consigne: e.consigne.trim(), questions: e.questions }));
    const ok = await confirmer({ titre: "Proposer à " + nomDe(m) + " d'être chef ?", libelleOk: "Envoyer", texte: "Il reçoit son questionnaire en message privé (" + nomMetier(C, etat_.metier) + ", " + quantite(etapes.reduce((n, e) => n + e.questions.length, 0), "question(s)") + "). " + (C.exigence || 100) + " % de réponses justes exigés." });
    if (!ok) return;
    const r = await poster("recrutement/chefs/proposer", { membre: String(m.id), metier: etat_.metier, etapes });
    toast(r.ok ? r.donnees.message : r.erreur, r.ok ? (r.donnees.invite ? "succes" : "erreur") : "erreur");
    if (r.ok) { p.fermer(); perime(CHEFS); if (recharger) recharger(); emettre("recharger"); }
  }
  ajouter(p.corps, [liste({ valeur: etat_.metier, label: "Son métier", plein: true, options: (C.metiers || []).map((x) => ({ v: x.cle, l: x.nom, sous: (m.metiers || []).includes(x.cle) ? "son métier" : "" })), changer: (v) => { etat_.metier = v; charger_(); } }),
    h("p", { classe: "aide" }, "Les questions viennent de la banque des chefs (ce métier, et « tous les métiers ») ; un gabarit réglé pour ce métier est déjà coché."), zoneE]);
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), envoyerB]);
  charger_();
}

// ─── La candidature d'un chef : correction, étape suivante, décision ────
export async function ouvrirCandidatureChef(envoi) {
  const p = pancarte({ titre: "Candidature de chef", icone: "etoile", taille: "tres-large" });
  const etatC = { p, envoi: String(envoi) };
  etatC.rendre = () => rendre();
  etatC.verrou = protegerEditeur(p, "chef:" + envoi, "cette candidature de chef", { surPlace: true, relire: () => rendre() });
  ajouter(p.corps, [squelettes(3)]);
  async function rendre() {
    const r = await lire("recrutement/chefs/dossier", { envoi: etatC.envoi });
    if (p.fermee()) return;
    if (!r.ok || !r.donnees) { remplacer(p.corps, vide("Candidature indisponible", r.erreur || "", "attention")); remplacer(p.pied, bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })); return; }
    const CD = r.donnees, e = CD.questionnaire || {}, peut = CD.peut || {};
    p.titre.firstChild.textContent = "Chef · " + (CD.metier_nom || CD.metier) + " — " + nomDe(CD.membre);
    const qs = e.questions || [];
    const b = e.bilan || {};
    const [lib, coul] = ETATS[CD.decision || (e.statut === "repondu" ? "corriger" : "en_cours")] || ["En cours", "mer"];
    const pre = qs.filter((q) => q.pre_juste && justeDe(q) === null);
    const parEtape = new Map();
    for (const q of qs) { const n = Number(q.etape) || 1; if (!parEtape.has(n)) parEtape.set(n, []); parEtape.get(n).push(q); }
    remplacer(p.corps,
      h("div", { classe: "dossier-tete" }, avatar(CD.membre, "g"), h("div", { classe: "bloc" }, h("div", { classe: "fiche-nom" }, nomDe(CD.membre)),
        h("div", { classe: "sous-nom" }, "Chef d'équipe · " + (CD.metier_nom || CD.metier) + (e.envoye_le ? " · proposé " + depuis(e.envoye_le) : "") + (e.envoye_par ? " par " + nomDe(e.envoye_par) : "")),
        h("div", { classe: "rangee" }, tampon(lib, coul, true), e.porte && !CD.decision ? tampon("Étape " + e.etape_ouverte + " sur " + (e.etapes || []).length, "mer", true) : null))),
      h("div", { classe: "correction-barre" + (b.total && b.justes === b.total ? " complet" : "") },
        h("div", { classe: "correction-compte" }, h("b", { classe: "num" }, (b.justes || 0) + " / " + (b.total || 0)), " justes — " + (CD.exigence || 100) + " % exigés, jamais forcé"),
        h("span", { classe: "meta" }, quantite(b.repondues || 0, "réponse(s)") + " · " + quantite(b.corrigees || 0, "corrigée(s)"))),
      peut.corriger && pre.length ? h("div", { classe: "rangee" }, bouton("Marquer justes les " + pre.length + " réponses identiques à l'attendue", { classe: "p", icone: "valider", onclick: async () => {
        for (const q of pre) await mettreEnFile("recrutement/corriger", { envoi: e.id, question: q.id, juste: true }, { genre: "correction", cle: e.id + ":" + q.id, resume: "Correction : juste" });
        rendre();
      } }), h("span", { classe: "meta" }, "Une aide : vérifie-les quand même.")) : null,
      ...(e.etapes || [{ numero: 1, titre: "" }]).map((x) => h("section", { classe: "zr-etape" },
        h("div", { classe: "zr-etape-tete" }, h("h4", {}, "Étape " + x.numero + (x.titre ? " · " + x.titre : ""))),
        h("ol", { classe: "correction-liste" }, (parEtape.get(Number(x.numero)) || []).map((q) => R.carteCorrection(etatC, e, q, Number(q.rang) - 1, !CD.decision && q.reponse_candidat != null))))),
      !peut.accepter && CD.raison_accepter && !CD.decision ? h("p", { classe: "aide" }, icone("info", "ic-p"), " Accepter : " + CD.raison_accepter) : null,
      CD.note ? h("p", { classe: "meta" }, "Note : " + CD.note) : null);
    const pied = [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })];
    if (peut.etape_suivante) pied.push(bouton("Ouvrir l'étape suivante", { icone: "droite", reseau: true, onclick: async () => {
      const rep = await poster("recrutement/etape_suivante", { envoi: Number(e.id) });
      toast(rep.ok ? rep.donnees.message : rep.erreur, rep.ok ? "succes" : "erreur");
      if (rep.ok) { perime(CHEFS); rendre(); }
    } }));
    if (peut.attente) pied.push(bouton("Mettre en attente", { classe: "discret", icone: "minuteur", reseau: true, onclick: () => decider("attente") }));
    if (peut.refuser) pied.push(bouton("Refuser", { classe: "danger", icone: "annuler", reseau: true, onclick: () => decider("refuser") }));
    if (!CD.decision || CD.decision === "attente") {
      const a = bouton("Nommer chef", { classe: "principal", icone: "valider", reseau: true, titre: peut.accepter ? "" : CD.raison_accepter, onclick: () => decider("accepter") });
      if (!peut.accepter) { a.disabled = true; a.dataset.forceOff = "1"; }
      pied.push(a);
    }
    remplacer(p.pied, ...pied);
    majBoutonsReseau(p.pied);
    async function decider(quoi) {
      const textes = { accepter: ["Nommer " + nomDe(CD.membre) + " chef d'équipe · " + (CD.metier_nom || CD.metier) + " ?", "Son rôle de chef (s'il est réglé) lui est donné, et un message privé part.", "Nommer chef"],
        refuser: ["Refuser sa candidature de chef ?", "Un message privé part. Il reste du clan (pas de liste noire).", "Refuser"],
        attente: ["Mettre sa candidature en attente ?", "Elle garde son état ; un message privé le prévient.", "Mettre en attente"] };
      const [titre, texte, ok] = textes[quoi];
      const rr = await confirmer({ titre, texte, libelleOk: ok, style: quoi === "refuser" ? "danger" : quoi === "accepter" ? "vert" : "", motif: quoi !== "accepter", motifLib: "Note (jamais montrée au membre)" });
      if (!rr) return;
      const rep = await poster("recrutement/chefs/decision", { envoi: Number(e.id), decision: quoi, note: rr.motif || "" });
      toast(rep.ok ? rep.donnees.message : rep.erreur, rep.ok ? "succes" : "erreur");
      if (rep.ok) { perime(CHEFS); emettre("recharger"); if (quoi === "attente") rendre(); else p.fermer(); }
    }
  }
  await rendre();
}

// ═══ LA BANQUE DES CHEFS (dans « Questions ») ═══════════════════════════
export function banqueChefs(zone) {
  const f = { q: "", metier: "tous_" };
  const z = h("div", { classe: "pile" }, squelettes(2));
  remplacer(zone, z);
  async function maj(forcer) {
    const C = await charger(CHEFS, { forcer });
    if (!z.isConnected) return;
    if (!C || C.erreur) { remplacer(z, vide("Banque des chefs indisponible", (C && C.erreur) || "", "hors_ligne")); return; }
    const qs = (C.questions || []).filter((q) => !q.retiree && (f.metier === "tous_" || (q.metiers || []).includes(f.metier) || (q.metiers || []).includes(C.tous))
      && contient([q.question, q.reponse, ...(q.variantes || [])].join(" "), f.q));
    const retirees = (C.questions || []).filter((q) => q.retiree);
    const parMetier = new Map();
    for (const q of qs) { const k = (q.metiers || [C.tous])[0] === C.tous ? C.tous : (q.metiers || [])[0]; if (!parMetier.has(k)) parMetier.set(k, []); parMetier.get(k).push(q); }
    remplacer(z, h("p", { classe: "aide" }, "À part de la banque du recrutement : des questions écrites par la direction pour les chefs de chaque métier, avec leur réponse attendue."),
      h("div", { classe: "outils" }, recherche(f.q, "Question, réponse…", (q) => { f.q = q; maj(false); }),
        liste({ valeur: f.metier, label: "Métier", options: [{ v: "tous_", l: "Tous" }, ...(C.metiers || []).map((m) => ({ v: m.cle, l: m.nom }))], changer: (v) => { f.metier = v; maj(false); } }),
        peutAgir() ? bouton("Ajouter une question", { classe: "principal", icone: "ajouter", onclick: () => editerQuestionChef(C, null, () => maj(true)) }) : null),
      qs.length ? h("div", { classe: "groupes-zone" }, groupes([...parMetier.entries()].map(([k, l]) => ({ cle: "zc-bq-" + k, titre: nomMetier(C, k), compte: l.length,
        contenu: () => lignes("zc-bq-" + k, l, (q) => ligneQuestionChef(C, q, () => maj(true))) })), { ouverts: 1, forcer: !!f.q }))
        : vide("Aucune question de chef ici", "Ajoute la première question.", "parchemin"),
      retirees.length ? groupe({ titre: "Retirées", compte: retirees.length, cle: "zc-bq-retirees" }, () => lignes("zc-bq-ret", retirees, (q) => ligneQuestionChef(C, q, () => maj(true)))) : null,
      groupe({ titre: "Le questionnaire de chaque métier", icone: "parchemin", compte: Object.keys(C.gabarits || {}).length, cle: "zc-gabarits" }, () => blocGabarits(C, () => maj(true))));
    majBoutonsReseau(z);
  }
  maj(true);
  return { majJeu: () => maj(false), majFile: () => maj(false) };
}
function ligneQuestionChef(C, q, recharger) {
  return avecVerrou(ligne({
    titre: q.question, sous: "Réponse : " + (q.reponse || "—") + ((q.variantes || []).length ? " · " + quantite(q.variantes.length, "variante(s)") : "") + " · " + (q.metiers || []).map((k) => nomMetier(C, k)).join(", "),
    badges: [q.retiree ? tampon("Retirée", "encre", true) : null, q.fuite ? tampon("Dit sa réponse", "", true) : null],
    actions: peutAgir() ? [{ icone: "plume", libelle: "Modifier", onclick: () => editerQuestionChef(C, q, recharger) },
      { icone: q.retiree ? "valider" : "supprimer", libelle: q.retiree ? "Remettre" : "Retirer", danger: !q.retiree, onclick: async () => {
        if (!siLibre("chef_question:" + q.id)) return;
        await mettreEnFile("recrutement/chefs/question/retirer", { id: q.id, restaurer: !!q.retiree }, { genre: "chef_question", cle: String(q.id), resume: (q.retiree ? "Remettre" : "Retirer") + " une question de chef" });
        perime(CHEFS); setTimeout(recharger, 600);
      } }] : [],
  }), "chef_question:" + q.id);
}
function editerQuestionChef(C, q, recharger) {
  const v = q ? { question: q.question, reponse: q.reponse, variantes: (q.variantes || []).slice(), metiers: (q.metiers || []).slice() } : { question: "", reponse: "", variantes: [], metiers: [C.tous || "tous"] };
  const p = pancarte({ titre: q ? "Modifier la question de chef" : "Nouvelle question de chef", sous: "Jamais la réponse dans la question", icone: "parchemin", taille: "" });
  if (q) protegerEditeur(p, "chef_question:" + q.id, "la question de chef");
  const texte = zoneTexte({ rows: 3, maxlength: 400, placeholder: "Combien d'hommes faut-il pour manœuvrer un galion ?" }, v.question);
  const rep = saisie({ value: v.reponse, maxlength: 200, placeholder: "Douze" });
  const vars = saisie({ value: v.variantes.join(" ; "), maxlength: 400, placeholder: "Autres façons justes, séparées par « ; »" });
  const cases = h("div", { classe: "pile serree" });
  const dessinerCases = () => remplacer(cases, h("span", { classe: "champ-lib" }, "Pour quels métiers"),
    caseACocher("Tous les métiers", v.metiers.includes(C.tous || "tous"), (b) => { v.metiers = b ? [C.tous || "tous"] : []; dessinerCases(); }),
    ...(C.metiers || []).map((m) => caseACocher(m.nom, v.metiers.includes(m.cle), (b) => { v.metiers = v.metiers.filter((x) => x !== (C.tous || "tous") && x !== m.cle); if (b) v.metiers.push(m.cle); dessinerCases(); },
      { disabled: v.metiers.includes(C.tous || "tous") })));
  dessinerCases();
  ajouter(p.corps, [champ("La question", texte), champ("La réponse attendue", rep), champ("Variantes admises", vars, { optionnel: true }), cases]);
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), bouton("Enregistrer", { classe: "principal", icone: "valider", onclick: async () => {
    const corps = { question: texte.value.trim(), reponse: rep.value.trim(), variantes: vars.value.split(";").map((s) => s.trim()).filter(Boolean).slice(0, 20), metiers: v.metiers.length ? v.metiers : [C.tous || "tous"] };
    if (corps.question.length < 8 || !corps.reponse) { toast("La question (8 caractères au moins) et la réponse attendue sont demandées.", "erreur"); return; }
    if (q) { corps.id = q.id; corps.version = q.version; }
    await mettreEnFile("recrutement/chefs/question", corps, { genre: "chef_question", cle: q ? String(q.id) : "tmp-" + Date.now(), resume: "Question de chef : " + corps.question.slice(0, 50) });
    p.fermer();
    toast(enLigne() ? "Question enregistrée." : "Question gardée sur l'appareil : elle partira au retour de la connexion.", "succes");
    perime(CHEFS); setTimeout(recharger, 600);
  } })]);
}
/** Le gabarit de chaque métier : ses étapes et leurs questions, proposées à chaque nouveau chef de ce métier. */
function blocGabarits(C, recharger) {
  const qs = (C.questions || []).filter((q) => !q.retiree && q.actif !== false);
  return h("ul", { classe: "lignes-c" }, (C.metiers || []).map((m) => {
    const g = (C.gabarits || {})[m.cle];
    return ligne({ visuel: pastilleIcone("parchemin", "#7a5a22"), titre: m.nom,
      sous: g ? quantite(g.etapes.length, "étape(s)") + " · " + quantite(g.etapes.reduce((n, e) => n + (e.questions || []).length, 0), "question(s)") : "Pas de gabarit : toutes les questions du métier, en une étape",
      actions: peutAgir() ? [{ icone: "plume", libelle: "Régler", texte: true, onclick: () => editerGabarit(C, m, g, qs.filter((q) => (q.metiers || []).includes(m.cle) || (q.metiers || []).includes(C.tous)), recharger) }] : [] });
  }));
}
function editerGabarit(C, m, g, banque, recharger) {
  const p = pancarte({ titre: "Le questionnaire des chefs · " + m.nom, icone: "parchemin", taille: "large" });
  protegerEditeur(p, "chef_gabarit:" + m.cle, "le questionnaire des chefs " + m.nom);
  const etapes = g ? g.etapes.map((e) => ({ titre: e.titre || "", consigne: e.consigne || "", questions: (e.questions || []).slice() })) : [{ titre: "", consigne: "", questions: [] }];
  const zoneE = h("div", { classe: "pile" });
  const dessiner = () => remplacer(zoneE, ...etapes.map((e, i) => h("section", { classe: "cadre pile serree zr-etape-edit" },
    h("div", { classe: "rangee entre" }, h("h4", {}, "Étape " + (i + 1)), etapes.length > 1 ? bouton("Retirer l'étape", { classe: "p discret danger", icone: "supprimer", onclick: () => { etapes.splice(i, 1); dessiner(); } }) : null),
    champ("Titre", (() => { const s = saisie({ value: e.titre, maxlength: 80 }); s.addEventListener("input", () => { e.titre = s.value; }); return s; })(), { optionnel: true }),
    banque.length ? h("ul", { classe: "banque-liste" }, banque.map((q) => h("li", { classe: "banque-choix" }, caseACocher(q.question, e.questions.includes(q.id), (b) => {
      for (const x of etapes) x.questions = x.questions.filter((y) => y !== q.id);
      if (b) e.questions.push(q.id);
      dessiner();
    }, { classe: "case-large" })))) : h("p", { classe: "aide" }, "La banque des chefs n'a aucune question pour ce métier."))),
  etapes.length < 8 ? h("div", { classe: "rangee" }, bouton("Ajouter une étape", { classe: "p", icone: "ajouter", onclick: () => { etapes.push({ titre: "", consigne: "", questions: [] }); dessiner(); } })) : null);
  dessiner();
  ajouter(p.corps, [h("p", { classe: "aide" }, "Proposé à chaque nouveau chef de ce métier ; modifiable avant chaque envoi."), zoneE]);
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), bouton("Enregistrer", { classe: "principal", icone: "valider", onclick: async () => {
    const corps = { metier: m.cle, version: g ? g.version : 0, etapes: etapes.filter((e) => e.questions.length).map((e) => ({ titre: e.titre.trim(), consigne: "", questions: e.questions })) };
    if (!corps.etapes.length) { toast("Coche au moins une question.", "erreur"); return; }
    await mettreEnFile("recrutement/chefs/gabarit", corps, { genre: "chef_gabarit", cle: m.cle, resume: "Le questionnaire des chefs " + m.nom });
    p.fermer(); toast("Questionnaire du métier enregistré.", "succes");
    perime(CHEFS); setTimeout(recharger, 600);
  } })]);
}

// ═══ LA FICHE D'UN MEMBRE : sa pastille de chef, « Proposer d'être chef » ═
const memoire = new Map();
ecouter("fiche:rendue", async ({ membre, zone }) => {
  if (!membre || !zone) return;
  const k = String(membre.id);
  let chef = memoire.get(k);
  if (!chef || Date.now() - chef.t > 60000) {
    const r = await lire("recrutement/chef", { membre: k });
    if (!r.ok) return;
    chef = { t: Date.now(), v: r.donnees && r.donnees.chef };
    memoire.set(k, chef);
  }
  if (!zone.isConnected) return;
  const c = chef.v;
  remplacer(zone, c ? pastille(c.titre || "Chef d'équipe", "#3f6b3a") : null,
    !c && membre.clan && peutAgir() ? bouton("Proposer d'être chef", { classe: "p discret", icone: "etoile", reseau: true, onclick: async () => {
      const C = await charger(CHEFS);
      const m = ((C && C.membres) || []).find((x) => String(x.id) === k) || { id: k, nom: membre.nom, metiers: [] };
      proposerChef(m, C, () => memoire.delete(k));
    } }) : null);
});
ecouter("recharger", () => memoire.clear());
