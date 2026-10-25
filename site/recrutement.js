// recrutement.js — les candidatures du clan, en deux étapes.
// Étape 1 : le questionnaire d'ouverture → « Refuser l'étape 1 » (message automatique) ou « Passer à l'étape 2 ».
// Étape 2 : les questions choisies dans la banque → la correction ICI, question par question : la réponse du candidat,
// la réponse attendue, ses variantes, une simple indication de proximité (jamais une décision) ; le fondateur ou la
// direction coche « Juste » ou « Faux » ; 100 % exigés ; puis Accepter, Refuser ou Renvoyer d'autres questions.
// Questionnaire : la banque (modifiable), les modèles, les liens donnés au candidat, les réglages.

import { h, icone, date, depuis, nombre, sansEmoji, contient, norm, maintenant, uuid, remplacer, moisDe, libelleMois, compte, copie, telephone, retarder, quantite, ajouter } from "./dom.js";
import { etat, P, peutAgir, aller, filtres, enLigne, emettre, ecouter } from "./noyau.js";
import { lire, poster, action } from "./api.js";
import { charger, vue as vueJeu, perime } from "./donnees.js";
import { mettreEnFile, opsDe } from "./hors_ligne.js";
import {
  bouton, boutonIcone, avatar, pastille, tampon, vide, tuile, tuiles, puces, segment, recherche, liste, champ, saisie, zoneTexte, interrupteur,
  caseACocher, radios, confirmer, pancarte, toast, section, squelettes, paginer, groupe, bandeau, compteur, nomDe, majBoutonsReseau, barres, ENCRES,
} from "./ui.js";
import { ouvrirFiche, reponses, transcriptEnLigne, STATUTS_CAND, etapeCandidature, chargerSuivi } from "./fiche.js";
import { indisponible } from "./discord.js";

export const THEMES = [["studio", "Studio RELL Games"], ["jeu", "Le jeu RELL Seas"], ["races", "Races"], ["factions", "Factions"], ["fruits", "Fruits"],
  ["combat", "Combat"], ["navires", "Navires"], ["monde", "Le monde"], ["evenements", "Évènements"], ["boss", "Boss"], ["personnages", "Personnages"], ["actualites", "Actualités · Movie 3"]];
const DIFFICULTES = { 1: "Facile", 2: "Moyenne", 3: "Difficile" };
const MESSAGE_REFUS_1 = "Tes réponses ne correspondent pas à ce que nous attendons : ce ticket va être clôturé. Merci d'avoir créé un ticket.\nYour answers don't match what we are looking for: this ticket will be closed. Thank you for opening a ticket.";
const MESSAGE_REFUS_2 = "La direction a étudié ta candidature : elle n'est pas retenue. Ce ticket va être clôturé. Merci d'avoir créé un ticket.\nThe leadership has reviewed your application: it was not accepted. This ticket will be closed. Thank you for opening a ticket.";
const resetPages = (p) => { for (const k of Object.keys(etat.pages)) if (k.startsWith(p)) delete etat.pages[k]; };

// ─── Lire avec tolérance (les champs exacts viennent du serveur) ────────────
const themesDe = (B) => {
  const t = B && B.themes;
  if (Array.isArray(t) && t.length) return t.map((x) => (Array.isArray(x) ? x : [x.cle || x.id, x.nom || x.cle]));
  if (t && typeof t === "object" && Object.keys(t).length) return Object.entries(t);   // le serveur : { cle: nom }
  return THEMES;
};
const nomTheme = (B, k) => (themesDe(B).find(([c]) => c === k) || [k, k || "Sans thème"])[1];
const qTexte = (q) => q.question || q.texte || q.intitule || "";
const qReponse = (q) => q.reponse || q.reponse_attendue || q.attendue || "";
const qVariantes = (q) => (Array.isArray(q.variantes) ? q.variantes : typeof q.variantes === "string" && q.variantes ? q.variantes.split(/\n|;/).map((s) => s.trim()).filter(Boolean) : []);
const qActive = (q) => q.active !== false && q.actif !== false;
const qDifficulte = (q) => Number(q.difficulte) || ({ facile: 1, moyenne: 2, difficile: 3 })[q.difficulte] || 1;
function qSource(q) {
  const s = q.source;
  if (s && typeof s === "object") return { titre: s.titre || s.nom || "", url: s.url || s.lien || "", minutage: s.minutage || s.temps || "" };
  if (typeof s === "string" && /^https?:\/\//.test(s)) return { titre: q.source_titre || "", url: s, minutage: "" };
  return { titre: typeof s === "string" ? s : q.source_titre || "", url: q.source_url || q.lien || "", minutage: q.minutage || "" };
}
const qRetiree = (q) => !!q.retiree;
const DIFF_NOMS = { 1: "facile", 2: "moyenne", 3: "difficile" };
// Le dossier (questionnaire.py) : la réponse du candidat, l'attendue, la correction, l'indication — avec repli sur
// les noms de la maquette d'origine.
const repCandidat = (q) => (q.reponse_candidat !== undefined ? q.reponse_candidat : q.reponse);
const repAttendue = (q) => q.attendue || q.reponse_attendue || "";
const justeDe = (q) => ("juste" in q ? q.juste : q.correction ? q.correction.juste : null);
const indicationDe = (q) => (q.indication && typeof q.indication === "object" ? q.indication : { niveau: q.indication || "", detail: "" });
const etapeDossier = (D) => Number(D.etape) || (/^(etape1|refus_etape1)$/.test(String(D.etape || "")) ? 1 : (D.envois || []).length ? 2 : 1);
const paires = (x) => (Array.isArray(x) ? x : x && typeof x === "object" ? Object.entries(x) : []);
const lignesMessage = (t) => String(t || "").split("\n").map((l) => l.replace(/^-#\s*/, ""));
// L'étape d'une candidature : la même règle partout (aperçu, pastille, cette page) — `fiche.etapeCandidature` lit le
// suivi du recrutement, sinon l'étape portée par les données. « decidee » : décidée, le ticket se ferme dans un instant.
const etatCandidature = (c) => etapeCandidature(c);

/** Une simple aide à la correction : identique, proche ou différent (casse, accents, espaces, ponctuation, distance). */
export function proximite(reponse, attendue, variantes) {
  const n = (s) => norm(s).replace(/[^\p{L}\p{N}]+/gu, " ").replace(/\b(le|la|les|l|un|une|des|du|de|d|the|a|an)\b/g, " ").replace(/\s+/g, " ").trim();
  const r = n(reponse);
  if (!r) return "vide";
  const cibles = [attendue, ...(variantes || [])].map(n).filter(Boolean);
  if (cibles.includes(r)) return "identique";
  for (const c of cibles) {
    const d = levenshtein(r, c), lg = Math.max(r.length, c.length);
    if (d <= Math.max(1, Math.floor(lg * 0.2))) return "proche";
    if (c.length >= 4 && (r.includes(c) || (r.length >= 4 && c.includes(r)))) return "proche";
  }
  return "different";
}
function levenshtein(a, b) {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  let prec = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cour = [i];
    for (let j = 1; j <= b.length; j++) cour[j] = Math.min(prec[j] + 1, cour[j - 1] + 1, prec[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    prec = cour;
  }
  return prec[b.length];
}
const INDICATIONS = { identique: ["Identique", "vert"], proche: ["Proche", "ambre"], different: ["Différent", ""], vide: ["Sans réponse", "encre"] };

// ═══ LA RUBRIQUE ════════════════════════════════════════════════════════
const SOUS = [["en-cours", "En cours", "candidatures"], ["decidees", "Décidées", "coffre"], ["questionnaire", "Questionnaire", "parchemin"]];
export function candidatures(vue, ctx) {
  const sous = SOUS.some(([k]) => k === ctx.sous) ? ctx.sous : "en-cours";
  const onglets = h("div", { classe: "sous-onglets", role: "tablist", "aria-label": "Candidatures" });
  const zone = h("div", { classe: "pile" });
  ajouter(vue, [onglets, zone]);
  let ctrl = null;
  const majOnglets = () => {
    const d = etat.d;
    const nb = d ? { "en-cours": d.en_cours.length, decidees: d.candidats.length } : {};
    const chaud = d ? d.en_cours.filter((c) => ["decider", "corriger"].includes(etatCandidature(c))).length : 0;
    remplacer(onglets, ...SOUS.map(([k, l, ic]) => h("a", { classe: "etiquette", role: "tab", href: "#equipage/candidatures/" + k, "aria-selected": String(k === sous) },
      icone(ic), l, nb[k] ? h("span", { classe: "compteur" + (k === "en-cours" && chaud ? " chaud" : " calme") }, String(nb[k])) : null)));
  };
  majOnglets();
  if (sous === "questionnaire") ctrl = questionnaire(zone);
  else if (sous === "decidees") ctrl = decidees(zone);
  else ctrl = enCours(zone);
  return { maj: () => { majOnglets(); ctrl && ctrl.maj && ctrl.maj(); }, majJeu: () => ctrl && ctrl.majJeu && ctrl.majJeu(), majFile: () => ctrl && ctrl.majFile && ctrl.majFile() };
}

// ─── En cours ───────────────────────────────────────────────────────────────
function enCours(zone) {
  const f = filtres("cand-encours", { q: "" });
  const resultats = h("div", { classe: "pile" });
  remplacer(zone, h("div", { classe: "outils" }, recherche(f.q, "Nom, pseudo, réponse…", (q) => { f.q = q; maj(); }),
    bouton("La banque de questions", { classe: "discret", icone: "parchemin", onclick: () => aller("equipage", "candidatures", "questionnaire") })), resultats);
  const maj = () => {
    const d = etat.d;
    if (!d) { remplacer(resultats, indisponible()); return; }
    const l = d.en_cours.filter((c) => contient([c.nom, c.pseudo, c.id, ...(c.reponses || []).flat()].join(" "), f.q));
    const parEtat = { decider: [], corriger: [], attente: [] };
    l.forEach((c) => { const e = etatCandidature(c); if (parEtat[e]) parEtat[e].push(c); });   // « decidee » : plus en cours
    remplacer(resultats,
      tuiles(tuile({ cle: "r1", lib: "Étape 1 à décider", val: parEtat.decider.length, icone: "candidatures", teinte: "#a8641c" }),
        tuile({ cle: "r2", lib: "Réponses à corriger", val: parEtat.corriger.length, icone: "plume", teinte: "#8e2a24" }),
        tuile({ cle: "r3", lib: "Questions envoyées", val: parEtat.attente.length, icone: "minuteur", sous: "en attente du candidat", teinte: "#1f4e5a" }),
        tuile({ cle: "r4", lib: "Écartées", val: d.ecartes || 0, icone: "coffre", sous: "sans décision, vides, doublons", teinte: "#4a5560" })),
      h("p", { classe: "aide" }, "Deux étapes : le questionnaire d'ouverture (étape 1), puis les questions choisies ici dans la banque (étape 2). Le candidat n'apprend jamais où il s'est trompé ; c'est toi qui corriges. 100 % de réponses justes exigés."),
      l.length ? null : vide("Aucune candidature en cours", "Les nouvelles candidatures apparaissent ici dès l'ouverture du ticket.", "candidatures"),
      parEtat.corriger.length ? section("Réponses à corriger", "plume", compte(parEtat.corriger.length, "candidat"), h("div", { classe: "grille" }, parEtat.corriger.map(carteCandidat))) : null,
      parEtat.decider.length ? section("Étape 1 · à décider", "candidatures", compte(parEtat.decider.length, "candidat"), h("div", { classe: "grille" }, parEtat.decider.map(carteCandidat))) : null,
      parEtat.attente.length ? section("Étape 2 · questions envoyées", "minuteur", compte(parEtat.attente.length, "candidat"), h("div", { classe: "grille" }, parEtat.attente.map(carteCandidat))) : null);
  };
  maj();
  chargerSuivi();   // l'étape la plus fraîche : la liste se redessine à son arrivée (« jeu »)
  return { maj, majJeu: maj };
}
function carteCandidat(c) {
  const e = etatCandidature(c);
  const [lib, coul] = { decider: ["Étape 1 · à décider", "ambre"], corriger: ["Étape 2 · à corriger", ""], attente: ["Étape 2 · en attente", "mer"],
    decidee: ["Décidée · fermeture prévue", "encre"] }[e] || ["Candidature", "encre"];
  const ouvrir = () => ouvrirDossier(c.ticket);
  return h("article", { classe: "feuillet lien" + (e === "corriger" ? " alerte" : e === "decider" ? " chaude" : ""), tabindex: 0, onclick: ouvrir, onkeydown: (ev) => { if (ev.key === "Enter") ouvrir(); } },
    h("div", { classe: "qui" }, avatar(c), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, nomDe(c)), h("div", { classe: "sous-nom" }, "Ticket #" + c.ticket + " · ouvert " + depuis(c.ouvert))), tampon(lib, coul)),
    (c.reponses || []).length ? h("ul", { classe: "entrees" }, c.reponses.slice(0, 2).map(([q, r]) => h("li", { classe: "entree" }, h("div", { classe: "meta" }, q), h("div", { classe: "texte coupe2" }, r)))) : h("p", { classe: "aide" }, "Formulaire non rempli."),
    h("div", { classe: "sous-nom" }, c.pris_par ? "Pris par " + sansEmoji(c.pris_par) : "Pas encore pris"));
}

// ─── Décidées ───────────────────────────────────────────────────────────────
function decidees(zone) {
  const f = filtres("cand-decidees", { q: "", statut: "tous", tri: "recent" });
  const resultats = h("div", { classe: "pile" });
  const changer = () => { resetPages("cand"); maj(); };
  remplacer(zone, h("div", { classe: "outils" }, recherche(f.q, "Nom, identifiant, motif…", (q) => { f.q = q; changer(); }),
    liste({ valeur: f.tri, label: "Tri", options: [{ v: "recent", l: "Plus récentes" }, { v: "ancien", l: "Plus anciennes" }, { v: "nom", l: "Nom A → Z" }], changer: (v) => { f.tri = v; changer(); } })), resultats);
  const maj = () => {
    const d = etat.d;
    if (!d) { remplacer(resultats, indisponible()); return; }
    const toutes = d.candidats;
    const nb = { tous: toutes.length, acceptes: toutes.filter((c) => c.statut === "acceptes").length, refuses: toutes.filter((c) => c.statut === "refuses").length };
    let l = toutes.filter((c) => (f.statut === "tous" || c.statut === f.statut) && contient([c.nom, c.pseudo, c.id, c.motif, c.pris_par, ...(c.reponses || []).flat()].join(" "), f.q));
    const cle = (c) => c.ferme || c.ouvert || 0;
    l.sort(f.tri === "nom" ? (a, b) => nomDe(a).localeCompare(nomDe(b), "fr") : f.tri === "ancien" ? (a, b) => cle(a) - cle(b) : (a, b) => cle(b) - cle(a));
    const parMois = new Map();
    l.forEach((c) => { const k = cle(c) ? moisDe(cle(c)) : "inconnu"; if (!parMois.has(k)) parMois.set(k, []); parMois.get(k).push(c); });
    const stats = {};
    toutes.forEach((c) => { if (!c.ferme) return; const k = moisDe(c.ferme); (stats[k] = stats[k] || { acceptes: 0, refuses: 0 })[c.statut] = ((stats[k] || {})[c.statut] || 0) + 1; });
    const taux = nb.acceptes + nb.refuses ? Math.round(100 * nb.acceptes / (nb.acceptes + nb.refuses)) : 0;
    remplacer(resultats,
      tuiles(tuile({ cle: "d1", lib: "Acceptés", val: nb.acceptes, icone: "succes", teinte: "#3f6b3a" }), tuile({ cle: "d2", lib: "Refusés", val: nb.refuses, icone: "annuler", teinte: "#8e2a24" }),
        tuile({ cle: "d3", lib: "Taux d'acceptation", val: taux, suffixe: " %", icone: "boussole", teinte: "#1f4e5a" })),
      puces([["tous", "Toutes", nb.tous], ["acceptes", "Acceptés", nb.acceptes, "#3f6b3a"], ["refuses", "Refusés", nb.refuses, "#8e2a24"]], f.statut, (v) => { f.statut = v; changer(); }, "Décision"),
      l.length ? h("div", {}, [...parMois.entries()].map(([k, g], i) => groupe({ titre: k === "inconnu" ? "Date inconnue" : libelleMois(k), compte: g.length, info: quantite(g.filter((c) => c.statut === "acceptes").length, "acceptée(s)"),
        cle: "cand-m-" + k, ouvert: i === 0 || !!f.q ? true : undefined }, () => paginer("cand-m-" + k, g, carteDecidee)))) : vide("Rien ici", "Change le filtre ou la recherche."),
      groupe({ titre: "Tendances", cle: "cand-tendances", icone: "carte" }, () => h("div", { classe: "cadre" }, h("h3", {}, "Candidatures par mois"), h("p", { classe: "aide" }, "Selon la date de la décision."),
        barres(Object.keys(stats).sort().slice(-12), stats, [["acceptes", ENCRES.vert, "Acceptés"], ["refuses", ENCRES.cire, "Refusés"]], "Les mois apparaîtront avec les premières décisions."))));
  };
  maj();
  return { maj };
}
function carteDecidee(c) {
  const [lib, teinte] = STATUTS_CAND[c.statut] || [c.statut, null];
  const ouvrir = () => ouvrirFiche(c.id, "candidatures");
  return h("article", { classe: "feuillet lien", tabindex: 0, onclick: ouvrir, onkeydown: (e) => { if (e.key === "Enter") ouvrir(); } },
    h("div", { classe: "qui" }, avatar(c), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, nomDe(c)), h("div", { classe: "sous-nom" }, (c.pseudo ? "@" + c.pseudo + " · " : "") + date(c.ferme || c.ouvert))),
      tampon(lib, c.statut === "acceptes" ? "vert" : "")),
    c.parti ? h("div", { classe: "pastilles" }, pastille("A quitté le serveur", "#4a5560")) : null,
    c.motif ? h("p", { classe: "texte coupe2" }, c.motif) : null,
    h("div", { classe: "sous-nom" }, (c.pris_par || c.ferme_par ? "Traité par " + sansEmoji(c.pris_par || c.ferme_par) : "Traitement non renseigné") + ((c.candidatures || []).length > 1 ? " · " + c.candidatures.length + " candidatures" : "")));
}

// ═══ LE DOSSIER D'UN CANDIDAT ═══════════════════════════════════════════
let dossierOuvert = null;
export async function ouvrirDossier(ticket) {
  if (dossierOuvert && !dossierOuvert.p.fermee()) dossierOuvert.p.fermer();
  const c0 = ((etat.d && etat.d.en_cours) || []).find((c) => String(c.ticket) === String(ticket)) || {};
  const p = pancarte({ titre: "Dossier de " + (nomDe(c0) || "candidat"), sous: "Ticket #" + ticket, icone: "candidatures", taille: "tres-large", surFermer: () => { if (dossierOuvert && dossierOuvert.p === p) dossierOuvert = null; } });
  const etatD = { p, ticket: String(ticket), vue: "dossier", choix: null };
  dossierOuvert = etatD;
  remplacer(p.corps, squelettes(3));
  await rendreDossier(etatD, true);
}
async function rendreDossier(etatD, forcer) {
  const [D, B] = [await charger("dossier", { params: { ticket: etatD.ticket }, forcer }), await charger("banque")];
  const p = etatD.p;
  if (p.fermee()) return;
  if (!D || D.erreur) { remplacer(p.corps, vide("Dossier indisponible", (D && D.erreur) || "Réessaie dans un instant.", "attention")); remplacer(p.pied, bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })); return; }
  const cand = D.candidat || {};
  p.titre.firstChild.textContent = "Dossier de " + (nomDe(cand) || nomDe(P(cand.id)) || "candidat");
  if (etatD.vue === "choix") return rendreChoix(etatD, D, B);
  const envois = (D.envois || []).slice().sort((a, b) => (b.envoye_le || 0) - (a.envoye_le || 0));
  const dernier = envois[0];
  const etape = etapeDossier(D);
  const peut = D.peut || null;
  const pe = (k) => (peut ? !!peut[k] : true);
  etatD.peutCorriger = pe("corriger");
  const tete = h("div", { classe: "dossier-tete" }, avatar(cand, "g"),
    h("div", { classe: "bloc" }, h("div", { classe: "fiche-nom" }, nomDe(cand)), h("div", { classe: "sous-nom" }, (cand.pseudo ? "@" + cand.pseudo + " · " : "") + "ticket #" + D.ticket + (D.ouvert || D.ouvert_le ? " · ouvert " + depuis(D.ouvert || D.ouvert_le) : "")),
      h("div", { classe: "rangee" }, tampon(etape === 1 ? "Étape 1" : "Étape 2", etape === 1 ? "ambre" : "mer", true),
        cand.id ? bouton("Sa fiche", { classe: "p discret", icone: "personne", onclick: () => { p.fermer(); ouvrirFiche(cand.id, "candidatures"); } }) : null)));
  const blocs = [tete];
  if (D.fermeture_prevue) blocs.push(bandeau("Le message est parti dans le ticket : il se ferme dans quelques secondes.", ""));
  blocs.push(groupe({ titre: "Étape 1 · le questionnaire d'ouverture", icone: "candidatures", ouvert: etape === 1, cle: "dossier-e1" }, () => [
    reponses(paires(D.etape1 && D.etape1.reponses)),
    transcriptEnLigne(Number(D.ticket), "Ticket #" + D.ticket, false)]));
  if (etape === 1 && pe("etape1")) {
    blocs.push(h("div", { classe: "cadre pile serree" }, h("h3", {}, "La décision de l'étape 1"),
      h("p", { classe: "aide" }, "Refuser envoie un message automatique dans le ticket, puis il se ferme. Passer à l'étape 2 ouvre le choix des questions."),
      h("div", { classe: "rangee" },
        bouton("Refuser l'étape 1", { classe: "danger", icone: "annuler", reseau: true, onclick: () => refuserEtape1(etatD, D) }),
        bouton("Passer à l'étape 2…", { classe: "principal", icone: "parchemin", onclick: () => { etatD.vue = "choix"; etatD.mode = "etape2"; rendreDossier(etatD); } }))));
  } else if (dernier) {
    blocs.push(blocEnvoi(etatD, D, dernier, true));
    for (const e of envois.slice(1)) blocs.push(groupe({ titre: "Envoi du " + date(e.envoye_le), compte: (e.questions || []).length, cle: "dossier-envoi-" + e.id }, () => blocEnvoi(etatD, D, e, false)));
  }
  remplacer(p.corps, ...blocs);
  const pied = [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })];
  // Comme sur le site d'avant : fermer le ticket sans décider (transcript et dossier gardés).
  if (peutAgir() && D.statut_ticket !== "ferme" && !D.fermeture_prevue) pied.unshift(bouton("Fermer le ticket sans décider", { classe: "discret danger gauche", icone: "cadenas", reseau: true, onclick: async () => {
    const r = await confirmer({ titre: "Fermer le ticket sans décider ?", texte: "Le ticket est fermé ; le transcript et le dossier sont gardés. Aucun message de refus n'est envoyé.", motif: true, libelleOk: "Fermer le ticket", style: "danger" });
    if (!r) return;
    const rep = await action({ action: "ticket_fermer", ticket: Number(D.ticket) || D.ticket, motif: r.motif || "" });
    toast(rep.message, rep.ok ? "succes" : "erreur");
    if (rep.ok) { p.fermer(); emettre("recharger"); }
  } }));
  if (etape === 2 && dernier) {
    const qs = dernier.questions || [];
    const justes = qs.filter((q) => justeDe(q) === true).length;
    if (pe("renvoyer")) pied.splice(1, 0, bouton("Renvoyer d'autres questions", { icone: "parchemin", onclick: () => { etatD.vue = "choix"; etatD.mode = "renvoi"; rendreDossier(etatD); } }));
    if (pe("refuser")) pied.push(bouton("Refuser", { classe: "danger", icone: "annuler", reseau: true, onclick: () => decision(etatD, D, "refuser") }));
    if (pe("accepter")) pied.push(bouton("Accepter" + (qs.length ? " · " + justes + "/" + qs.length : ""), { classe: "principal", icone: "valider", reseau: true, onclick: () => decision(etatD, D, "accepter", justes, qs.length) }));
  }
  remplacer(p.pied, ...pied);
  majBoutonsReseau(p.pied);
  majBoutonsReseau(p.corps);
}

function blocEnvoi(etatD, D, e, courant) {
  const qs = e.questions || [];
  const repondu = qs.some((q) => repCandidat(q) !== null && repCandidat(q) !== undefined) || /repondu|reponses/.test(e.statut || "");
  const justes = qs.filter((q) => justeDe(q) === true).length, faux = qs.filter((q) => justeDe(q) === false).length;
  const par = e.par ? sansEmoji(e.par) : e.envoye_par ? nomDe(P(e.envoye_par)) : "";
  const corps = [];
  corps.push(h("p", { classe: "meta" }, "Envoyé " + depuis(e.envoye_le) + (par ? " par " + par : "") + " · " + compte(qs.length, "question") + (e.repondu_le ? " · réponses reçues " + depuis(e.repondu_le) : "")));
  if (e.statut === "remplace") corps.push(h("p", { classe: "aide" }, "Remplacé par un questionnaire plus récent."));
  if (!repondu) {
    corps.push(bandeau("En attente des réponses du candidat. Il a reçu les " + qs.length + " questions et les liens où se trouvent toutes les réponses.", ""));
    corps.push(h("ol", { classe: "questions-envoyees" }, qs.map((q) => h("li", {}, q.question || qTexte(q)))));
    return h("section", { classe: "cadre pile envoi" + (courant ? " courant" : "") }, h("h3", {}, courant ? "Étape 2 · questions envoyées" : "Envoi"), corps);
  }
  const pc = qs.length ? Math.round(100 * justes / qs.length) : 0;
  const barre = h("div", { classe: "correction-barre" + (justes === qs.length && qs.length ? " complet" : "") },
    h("div", { classe: "correction-compte" }, h("b", { classe: "num" }, justes + " / " + qs.length), " justes — 100 % exigés"),
    h("span", { classe: "vote-fond" }, h("span", { classe: "vote-plein", vars: { "--pc": pc + "%" } })),
    h("span", { classe: "meta" }, faux ? compte(faux, "faux", "faux") + " · " : "", compte(qs.length - justes - faux, "à corriger", "à corriger")));
  corps.push(barre);
  corps.push(h("p", { classe: "aide" }, "L'indication de proximité n'est qu'une aide (fautes, accents, mots proches) : c'est toi qui décides si c'est juste."));
  corps.push(h("ol", { classe: "correction-liste" }, qs.map((q, i) => carteCorrection(etatD, e, q, i, courant && etatD.peutCorriger !== false))));
  return h("section", { classe: "cadre pile envoi" + (courant ? " courant" : "") }, h("h3", {}, courant ? "Étape 2 · la correction" : "Correction"), corps);
}
function carteCorrection(etatD, e, q, i, modifiable = true) {
  const variantes = qVariantes(q);
  const rc = repCandidat(q), attendue = repAttendue(q) || qReponse(q), juste = justeDe(q);
  const indic = indicationDe(q);
  const ind = !String(rc || "").trim() ? "vide" : INDICATIONS[indic.niveau] ? indic.niveau : proximite(rc, attendue, variantes);
  const [lib, coul] = INDICATIONS[ind] || [ind, "encre"];
  const marquer = async (valeur) => {
    const nouvelle = juste === valeur ? null : valeur;
    await mettreEnFile("recrutement/corriger", { envoi: e.id, question: q.id, juste: nouvelle }, { genre: "correction", cle: e.id + ":" + q.id, resume: "Correction de la question " + (i + 1) + (nouvelle === true ? " : juste" : nouvelle === false ? " : faux" : " : à revoir") });
    q.juste = nouvelle;
    if (q.correction !== undefined) q.correction = Object.assign({}, q.correction || {}, { juste: nouvelle });
    rendreDossier(etatD);
  };
  return h("li", { classe: "correction" + (juste === true ? " juste" : juste === false ? " faux" : "") + (q._attente ? " en-attente" : "") },
    h("div", { classe: "correction-tete" }, h("span", { classe: "correction-num" }, String(i + 1)), h("b", { classe: "correction-question" }, q.question || qTexte(q)), q.theme ? h("span", { classe: "meta" }, nomTheme(vueJeu("banque"), q.theme)) : null),
    h("div", { classe: "correction-corps" },
      h("div", { classe: "correction-reponse" }, h("span", { classe: "champ-lib" }, "Réponse du candidat"), rc ? h("p", {}, rc) : h("p", { classe: "aide" }, "Pas de réponse.")),
      h("div", { classe: "correction-attendue" }, h("span", { classe: "champ-lib" }, "Réponse attendue"), h("p", {}, attendue || "—"),
        variantes.length ? h("div", { classe: "variantes" }, h("span", { classe: "meta" }, "Variantes admises : "), variantes.map((v) => h("span", { classe: "variante" }, v))) : null)),
    h("div", { classe: "correction-pied" }, h("span", { classe: "indication " + ind }, h("span", { classe: "meta" }, "Indication : "), tampon(lib, coul, true),
        indic.detail && ind !== "vide" ? h("span", { classe: "meta" }, " " + indic.detail) : null),
      h("div", { classe: "juste-faux", role: "group", "aria-label": "Correction de la question " + (i + 1) },
        h("button", { type: "button", classe: "bouton-juste", "aria-pressed": String(juste === true), disabled: !modifiable, onclick: () => marquer(true) }, icone("valider"), "Juste"),
        h("button", { type: "button", classe: "bouton-faux", "aria-pressed": String(juste === false), disabled: !modifiable, onclick: () => marquer(false) }, icone("annuler"), "Faux")),
      q._attente ? h("span", { classe: "meta" }, q._attente === "conflit" ? "conflit" : "gardé sur l'appareil") : null));
}

async function refuserEtape1(etatD, D) {
  const message = lignesMessage(D.message_refus_etape1 || MESSAGE_REFUS_1);
  const ok = await confirmer({ titre: "Refuser l'étape 1 ?", icone: "annuler", style: "danger", libelleOk: "Refuser et fermer le ticket", taille: "",
    texte: "Ce message part tout seul dans le ticket, puis le ticket se ferme (transcript et dossier gardés) :",
    contenu: [h("blockquote", { classe: "message-auto" }, message.map((l) => h("p", {}, l)))] });
  if (!ok) return;
  const r = await poster("recrutement/etape1", { ticket: Number(D.ticket) || D.ticket, decision: "refuser" });
  toast(r.ok ? (r.donnees.message || "Refus envoyé ; le ticket se ferme.") : r.erreur, r.ok ? "succes" : "erreur");
  if (r.ok) { etatD.p.fermer(); emettre("recharger"); }
}
async function decision(etatD, D, quoi, justes, total) {
  if (quoi === "accepter") {
    const complet = total && justes === total;
    const ok = await confirmer({ titre: "Accepter " + (nomDe(D.candidat) || "le candidat") + " ?", icone: "valider", libelleOk: "Accepter", style: complet ? "vert" : "danger",
      texte: complet ? "Toutes les réponses sont justes. Il reçoit le rôle du clan et le ticket se ferme." : "Attention : " + justes + " / " + total + " réponses cochées justes, alors que 100 % sont exigés. Accepter quand même ? Il reçoit le rôle du clan et le ticket se ferme." });
    if (!ok) return;
  } else {
    const ok = await confirmer({ titre: "Refuser la candidature ?", icone: "annuler", style: "danger", libelleOk: "Refuser et fermer le ticket",
      texte: "Ce message neutre part dans le ticket (sans dire où il s'est trompé), puis le ticket se ferme :", contenu: [h("blockquote", { classe: "message-auto" }, lignesMessage(D.message_refus || MESSAGE_REFUS_2).map((l) => h("p", {}, l)))] });
    if (!ok) return;
  }
  const corps = { ticket: Number(D.ticket) || D.ticket, decision: quoi };
  if (quoi === "accepter" && !(total && justes === total)) corps.forcer = true;  // confirmé malgré moins de 100 %
  const r = await poster("recrutement/decision", corps);
  toast(r.ok ? (r.donnees.message || "C'est fait.") : r.erreur, r.ok ? "succes" : "erreur");
  if (r.ok) { etatD.p.fermer(); emettre("recharger"); }
}

// ─── Le choix des questions ─────────────────────────────────────────────────
/** etatD.mode : "etape2" | "renvoi" (un candidat) · "modele" | "defaut" (depuis le Questionnaire). */
function rendreChoix(etatD, D, B) {
  const p = etatD.p;
  if (!B || B.erreur) { remplacer(p.corps, vide("La banque de questions est indisponible", (B && B.erreur) || "", "hors_ligne")); return; }
  const banque = (B.questions || []).filter((q) => qActive(q) && !qRetiree(q) && q.posable !== false);
  const parId = new Map((B.questions || []).map((q) => [String(q.id), q]));
  const dejaPosees = new Set(((D && D.envois) || []).flatMap((e) => (e.questions || []).map((q) => String(q.id))));
  if (!etatD.choix) {
    etatD.choix = etatD.depart ? etatD.depart.slice() : etatD.mode === "renvoi" ? [] : (modeleDefaut(B) || []).slice();
    etatD.choix = etatD.choix.filter((id) => parId.has(String(id))).map(String);
  }
  const f = etatD.filtres || (etatD.filtres = { q: "", diff: "0", statut: "tous", masquer: etatD.mode === "renvoi" });
  const sel = new Set(etatD.choix);
  const candidat = D ? nomDe(D.candidat || {}) : "";
  const zoneBanque = h("div", { classe: "pile" }), zoneSel = h("div", { classe: "selection-panneau" }), zoneAction = h("span", { classe: "choix-action" });
  const majTout = () => { majBanque(); majSelection(); };
  const basculer = (id) => { id = String(id); if (sel.has(id)) { sel.delete(id); etatD.choix = etatD.choix.filter((x) => x !== id); } else { sel.add(id); etatD.choix.push(id); } majTout(); };
  const remplacerSel = (ids) => { etatD.choix = ids.map(String).filter((x) => parId.has(x)); sel.clear(); etatD.choix.forEach((x) => sel.add(x)); majTout(); };

  // Les départs en un clic
  const der = B.derniere_selection;
  const departs = h("div", { classe: "departs" },
    der && (der.questions || []).length ? h("button", { classe: "depart", type: "button", onclick: () => { remplacerSel(der.questions); toast("Sélection précédente reprise.", "succes"); } },
      icone("synchro"), h("b", {}, "Reprendre la sélection précédente"), h("span", {}, compte(der.questions.length, "question") + (der.envoye_le ? " · envoyée le " + date(der.envoye_le) : "") + (der.candidat ? " · à " + sansEmoji(der.candidat) : ""))) : null,
    (() => { const m = modeleDefautObjet(B); const ids = modeleDefaut(B); return ids && ids.length ? h("button", { classe: "depart", type: "button", onclick: () => { remplacerSel(ids); toast("Modèle par défaut chargé.", "succes"); } },
      icone("etoile"), h("b", {}, "Modèle par défaut"), h("span", {}, (m ? sansEmoji(m.nom) + " · " : "") + compte(ids.length, "question"))) : null; })(),
    ...(B.modeles || []).filter((m) => !m.par_defaut).map((m) => h("button", { classe: "depart modele", type: "button", onclick: () => { remplacerSel(m.questions || []); toast("Modèle « " + m.nom + " » chargé.", "succes"); } },
      icone("parchemin"), h("b", {}, sansEmoji(m.nom)), h("span", {}, compte((m.questions || []).length, "question")))));

  const outils = h("div", { classe: "outils" },
    recherche(f.q, "Chercher une question, une réponse…", (q) => { f.q = q; majBanque(); }),
    segment(f.diff, [["0", "Toutes"], ["1", "Faciles"], ["2", "Moyennes"], ["3", "Difficiles"]], (v) => { f.diff = v; majBanque(); }, "Difficulté"),
    liste({ valeur: f.statut, label: "Statut", options: [{ v: "tous", l: "Tous" }, { v: "confirme", l: "Confirmées" }, { v: "a_verifier", l: "À vérifier" }], changer: (v) => { f.statut = v; majBanque(); } }),
    D ? caseACocher("Masquer celles déjà posées à " + (candidat || "ce candidat"), f.masquer, (v) => { f.masquer = v; majBanque(); }) : null);

  function majBanque() {
    const l = banque.filter((q) => (f.diff === "0" || String(qDifficulte(q)) === f.diff) && (f.statut === "tous" || (q.statut || "a_verifier") === f.statut)
      && (!f.masquer || !dejaPosees.has(String(q.id)) || sel.has(String(q.id))) && contient([qTexte(q), qReponse(q), ...qVariantes(q), q.section].join(" "), f.q));
    const parTheme = new Map();
    l.forEach((q) => { const k = q.theme || "autre"; if (!parTheme.has(k)) parTheme.set(k, []); parTheme.get(k).push(q); });
    const ordre = themesDe(B).map(([k]) => k);
    const cles = [...parTheme.keys()].sort((a, b) => ((ordre.indexOf(a) + 1) || 99) - ((ordre.indexOf(b) + 1) || 99));
    remplacer(zoneBanque, ...(cles.length ? cles.map((k) => {
      const qs = parTheme.get(k), choisies = qs.filter((q) => sel.has(String(q.id))).length;
      return groupe({ titre: nomTheme(B, k), compte: qs.length, info: choisies ? quantite(choisies, "choisie(s)") : "", cle: "choix-" + k, ouvert: !!f.q || cles.length <= 3 || choisies > 0 ? true : undefined },
        () => h("ul", { classe: "banque-liste" }, qs.map((q) => ligneChoix(q))));
    }) : [vide("Aucune question ici", "Change les filtres ou la recherche.")]));
  }
  function ligneChoix(q) {
    const id = String(q.id), coche = sel.has(id), deja = dejaPosees.has(id);
    return h("li", { classe: "banque-choix" + (coche ? " coche" : "") },
      caseACocher(h("span", { classe: "banque-q" }, h("span", {}, qTexte(q)),
        h("span", { classe: "banque-meta" }, h("span", { classe: "difficulte d" + qDifficulte(q), title: "Difficulté : " + DIFFICULTES[qDifficulte(q)] }, DIFFICULTES[qDifficulte(q)]),
          (q.statut || "a_verifier") === "a_verifier" ? h("span", { classe: "marque-verifier" }, "à vérifier") : null, deja ? h("span", { classe: "marque-deja" }, "déjà posée") : null)),
        coche, () => basculer(id), { classe: "case-large" }));
  }
  function majSelection() {
    const n = etatD.choix.length;
    const themes = new Set(etatD.choix.map((id) => (parId.get(id) || {}).theme));
    const liste_ = h("ol", { classe: "selection-liste" }, etatD.choix.map((id, i) => {
      const q = parId.get(id) || {};
      return h("li", { classe: "selection-item" }, h("span", { classe: "selection-num" }, String(i + 1)), h("span", { classe: "selection-q" }, qTexte(q) || "Question retirée de la banque"),
        h("span", { classe: "selection-outils" },
          boutonIcone("haut", "Monter", () => { if (i > 0) { [etatD.choix[i - 1], etatD.choix[i]] = [etatD.choix[i], etatD.choix[i - 1]]; majSelection(); } }),
          boutonIcone("bas", "Descendre", () => { if (i < n - 1) { [etatD.choix[i + 1], etatD.choix[i]] = [etatD.choix[i], etatD.choix[i + 1]]; majSelection(); } }),
          boutonIcone("fermer", "Retirer de la sélection", () => basculer(id))));
    }));
    const boutonFinal = etatD.mode === "modele" ? bouton("Enregistrer le modèle (" + n + ")", { classe: "principal", icone: "valider", onclick: () => etatD.surValider(etatD.choix.slice()) })
      : etatD.mode === "defaut" ? bouton("Enregistrer la sélection par défaut (" + n + ")", { classe: "principal", icone: "valider", onclick: () => etatD.surValider(etatD.choix.slice()) })
        : bouton("Envoyer " + compte(n, "question") + " à " + (candidat || "ce candidat"), { classe: "principal envoyer", icone: "cloche", reseau: true, onclick: () => envoyerQuestions(etatD, D, B) });
    boutonFinal.disabled = !n || boutonFinal.disabled;
    if (zoneAction.isConnected || !p.pied.contains(zoneAction)) remplacer(zoneAction, boutonFinal);
    remplacer(zoneSel,
      h("div", { classe: "selection-tete" }, h("b", {}, "Sélection"), h("span", { classe: "selection-resume" }, compte(n, "question") + (n ? " · " + compte(themes.size, "thème") : ""))),
      n ? liste_ : h("p", { classe: "aide" }, "Coche des questions dans la banque, ou pars d'une sélection en haut."),
      h("div", { classe: "selection-actions" },
        n ? bouton("Tout retirer", { classe: "p discret", icone: "supprimer", onclick: () => remplacerSel([]) }) : null,
        n && etatD.mode !== "modele" ? bouton("Enregistrer comme modèle…", { classe: "p", icone: "parchemin", onclick: () => enregistrerModele(etatD.choix.slice(), false) }) : null,
        n && etatD.mode !== "modele" ? bouton("Définir comme modèle par défaut", { classe: "p discret", icone: "etoile", onclick: () => enregistrerModele(etatD.choix.slice(), true) }) : null));
    majBoutonsReseau(zoneSel);
    majBoutonsReseau(zoneAction);
  }
  majTout();
  const tete = h("div", { classe: "choix-tete" },
    h("p", { classe: "aide" }, etatD.mode === "renvoi" ? "Choisis les nouvelles questions à envoyer à " + candidat + " (celles déjà posées sont masquées)." : etatD.mode === "modele" ? "Compose le modèle : coche les questions, range-les dans l'ordre voulu."
      : etatD.mode === "defaut" ? "La sélection proposée par défaut à chaque candidat (et utilisée sur Discord)." : "Les questions que " + candidat + " recevra dans son ticket, avec les liens où se trouvent toutes les réponses."),
    departs.children.length ? h("div", {}, h("span", { classe: "champ-lib" }, "Partir de…"), departs) : null);
  const bascule = segment("banque", [["banque", "La banque"], ["selection", "Sélection"]], (v) => { cadre.classList.toggle("voir-selection", v === "selection"); }, "Vue");
  bascule.classList.add("seulement-telephone");
  const cadre = h("div", { classe: "choix-questions" }, h("div", { classe: "choix-banque pile" }, outils, zoneBanque), h("aside", { classe: "choix-selection" }, zoneSel));
  remplacer(p.corps, tete, bascule, cadre);
  remplacer(p.pied, bouton(etatD.retour ? "Fermer" : "Retour au dossier", { classe: "discret gauche", icone: etatD.retour ? null : "gauche", onclick: () => { if (etatD.retour) p.fermer(); else { etatD.vue = "dossier"; etatD.choix = null; rendreDossier(etatD); } } }), zoneAction);
  majSelection();
}
function modeleDefautObjet(B) { return (B.modeles || []).find((m) => m.par_defaut) || null; }
function modeleDefaut(B) {
  const m = modeleDefautObjet(B);
  return m && (m.questions || []).length ? m.questions.map(String) : [];
}
async function enregistrerModele(ids, parDefaut, existant) {
  const nom = saisie({ value: existant ? existant.nom : "", maxlength: 60, placeholder: "Spécial Movie 3" });
  const ok = await confirmer({ titre: parDefaut ? "Modèle par défaut" : "Enregistrer comme modèle", icone: "parchemin", libelleOk: "Enregistrer",
    texte: compte(ids.length, "question") + (parDefaut ? ". Il sera proposé d'emblée à chaque candidat, et utilisé sur Discord." : "."), contenu: [champ("Nom du modèle", nom)] });
  if (!ok) return;
  const n = nom.value.trim() || (parDefaut ? "Par défaut" : "Modèle du " + date(maintenant()));
  const corps = { nom: n, questions: ids, par_defaut: !!parDefaut };
  if (existant && existant.id) { corps.id = existant.id; corps.version = existant.version; }
  const cle = existant && existant.id ? String(existant.id) : "tmp-" + uuid();
  await mettreEnFile("recrutement/modele", corps, { genre: "modele", cle, resume: "Modèle de questions « " + n + " »", objet: Object.assign({}, existant || {}, corps, { id: existant ? existant.id : cle, _cle: cle }) });
  toast("Modèle « " + n + " » enregistré.", "succes");
  emettre("jeu", { nom: "banque" });
}
async function envoyerQuestions(etatD, D, B) {
  const ids = etatD.choix.slice();
  const route = etatD.mode === "renvoi" ? "recrutement/decision" : "recrutement/etape1";
  const corps = etatD.mode === "renvoi" ? { ticket: Number(D.ticket) || D.ticket, decision: "renvoyer", questions: ids } : { ticket: Number(D.ticket) || D.ticket, decision: "etape2", questions: ids };
  const r = await poster(route, corps);
  if (!r.ok) { toast(r.erreur || "Envoi impossible.", "erreur"); return; }
  const ign = (r.donnees && r.donnees.ignorees) || [];
  toast(ign.length ? (ign.length > 1 ? compte(ign.length, "question") + " n'existaient plus et ont été ignorées" : "Une question n'existait plus et a été ignorée") + " ; le reste est parti." : (r.donnees.message || "Questions envoyées dans le ticket."), ign.length ? "erreur" : "succes");
  perime("banque");
  etatD.vue = "dossier";
  etatD.choix = null;
  emettre("recharger");
  await rendreDossier(etatD, true);
}
/** Le choix des questions hors dossier (modèle, sélection par défaut). */
async function choisirHorsDossier(mode, depart, surValider, titre) {
  const p = pancarte({ titre, icone: "parchemin", taille: "tres-large" });
  const etatD = { p, ticket: null, vue: "choix", mode, depart, choix: null, retour: true, surValider: async (ids) => { await surValider(ids); p.fermer(); } };
  const B = await charger("banque");
  rendreChoix(etatD, null, B);
}

// ═══ LE QUESTIONNAIRE (la banque, les modèles, les liens, les réglages) ═══
function questionnaire(zone) {
  const f = filtres("questionnaire", { q: "", theme: "tous", diff: "0", statut: "tous", actives: "toutes" });
  const resultats = h("div", { classe: "pile" }, squelettes(3));
  const changer = () => { resetPages("bq"); maj(); };
  remplacer(zone, resultats);
  const maj = async (forcer) => {
    const B = await charger("banque", { forcer });
    if (!resultats.isConnected) return;
    if (!B || B.erreur) { remplacer(resultats, vide("Questionnaire indisponible", B && B.erreur, "hors_ligne")); return; }
    const qs = (B.questions || []).filter((q) => !qRetiree(q));
    const nbTheme = {};
    qs.forEach((q) => { nbTheme[q.theme] = (nbTheme[q.theme] || 0) + 1; });
    const l = qs.filter((q) => (f.theme === "tous" || q.theme === f.theme) && (f.diff === "0" || String(qDifficulte(q)) === f.diff) && (f.statut === "tous" || (q.statut || "a_verifier") === f.statut)
      && (f.actives === "toutes" || (f.actives === "actives") === qActive(q)) && contient([qTexte(q), qReponse(q), ...qVariantes(q), q.section, q.extrait, qSource(q).titre].join(" "), f.q));
    const parTheme = new Map();
    l.forEach((q) => { const k = q.theme || "autre"; if (!parTheme.has(k)) parTheme.set(k, []); parTheme.get(k).push(q); });
    const ordre = themesDe(B).map(([k]) => k);
    const reglages = B.reglages || {};
    remplacer(resultats,
      tuiles(tuile({ cle: "b1", lib: "Questions actives", val: qs.filter(qActive).length, icone: "parchemin", sous: compte(qs.length, "question") + " dans la banque", teinte: "#1f4e5a" }),
        tuile({ cle: "b2", lib: "À vérifier", val: qs.filter((q) => (q.statut || "a_verifier") === "a_verifier").length, icone: "attention", teinte: "#a8641c", clic: () => { f.statut = "a_verifier"; changer(); } }),
        tuile({ cle: "b3", lib: "Questions par candidat", val: Number(reglages.annonce || reglages.nombre || reglages.nombre_defaut) || 0, icone: "candidatures", sous: "annoncées au candidat", teinte: "#7a4b2a" }),
        tuile({ cle: "b4", lib: "Modèles", val: (B.modeles || []).length, icone: "etoile", teinte: "#7a5a22" })),
      section("La banque de questions", "parchemin", compte(l.length, "question"),
        h("div", { classe: "pile" },
          h("div", { classe: "outils" }, recherche(f.q, "Question, réponse, source…", (q) => { f.q = q; changer(); }),
            segment(f.diff, [["0", "Toutes"], ["1", "Faciles"], ["2", "Moyennes"], ["3", "Difficiles"]], (v) => { f.diff = v; changer(); }, "Difficulté"),
            liste({ valeur: f.statut, label: "Statut", options: [{ v: "tous", l: "Tous" }, { v: "confirme", l: "Confirmées" }, { v: "a_verifier", l: "À vérifier" }], changer: (v) => { f.statut = v; changer(); } }),
            liste({ valeur: f.actives, label: "Actives", options: [{ v: "toutes", l: "Actives et désactivées" }, { v: "actives", l: "Actives" }, { v: "inactives", l: "Désactivées" }], changer: (v) => { f.actives = v; changer(); } }),
            peutAgir() ? bouton("Ajouter une question", { classe: "principal", icone: "ajouter", onclick: () => editerQuestion(B, null) }) : null),
          puces([["tous", "Tous les thèmes", qs.length], ...themesDe(B).map(([k, n]) => [k, n, nbTheme[k] || 0])], f.theme, (v) => { f.theme = v; changer(); }, "Thèmes"),
          l.length ? h("div", {}, [...parTheme.keys()].sort((a, b) => ((ordre.indexOf(a) + 1) || 99) - ((ordre.indexOf(b) + 1) || 99)).map((k) => groupe({ titre: nomTheme(B, k), compte: parTheme.get(k).length,
            cle: "bq-" + k, ouvert: f.theme !== "tous" || !!f.q ? true : undefined }, () => paginer("bq-" + k, parTheme.get(k), (q) => ligneBanque(B, q), { classe: "banque-registre", pas: 20 })))) : vide("Aucune question ici", "Change les filtres, ou ajoute une question."))),
      section("Les modèles", "etoile", compte((B.modeles || []).length, "modèle"), blocModeles(B)),
      section("Les liens donnés au candidat", "lien", compte((B.liens || []).length, "lien"), blocLiens(B)),
      section("Les réglages", "cle", "", blocReglages(B)));
    majBoutonsReseau(resultats);
  };
  maj();
  return { maj: () => maj(false), majJeu: () => maj(false), majFile: () => maj(false) };
}
function ligneBanque(B, q) {
  const src = qSource(q), vari = qVariantes(q);
  return h("article", { classe: "banque-ligne" + (qActive(q) ? "" : " inactive") + (q._attente ? " en-attente" : "") },
    h("div", { classe: "banque-ligne-tete" }, h("b", { classe: "banque-question" }, qTexte(q)),
      h("span", { classe: "rangee" }, h("span", { classe: "difficulte d" + qDifficulte(q) }, DIFFICULTES[qDifficulte(q)]),
        (q.statut || "a_verifier") === "a_verifier" ? tampon("À vérifier", "ambre", true) : tampon("Confirmée", "vert", true), q._attente ? tampon("En attente", "", true) : null)),
    h("div", { classe: "banque-reponse" }, h("span", { classe: "champ-lib" }, "Réponse attendue"), h("span", {}, qReponse(q) || "—")),
    vari.length ? h("div", { classe: "variantes" }, h("span", { classe: "meta" }, "Variantes : "), vari.map((v) => h("span", { classe: "variante" }, v))) : null,
    src.titre || src.url ? h("div", { classe: "meta banque-source" }, icone("lien", "ic-p"), " ", src.url ? h("a", { href: src.url }, src.titre || src.url) : src.titre, src.minutage ? " · à " + src.minutage : "",
      q.section ? " · " + q.section : "") : null,
    q.extrait ? h("p", { classe: "banque-extrait" }, q.extrait) : null,
    peutAgir() ? h("div", { classe: "rangee" },
      interrupteur("Active", qActive(q), (v) => enregistrerQuestion(Object.assign({}, q, { active: v, actif: v }), q)),
      bouton("Modifier", { classe: "p", icone: "plume", onclick: () => editerQuestion(B, q) }),
      bouton("Retirer", { classe: "p discret danger", icone: "supprimer", onclick: async () => {
        const ok = await confirmer({ titre: "Retirer cette question de la banque ?", texte: "« " + qTexte(q) + " » ne sera plus proposée. Les dossiers qui l'ont déjà gardent leur réponse.", libelleOk: "Retirer", style: "danger" });
        if (ok) { await mettreEnFile("recrutement/question/retirer", { id: q.id }, { genre: "question", cle: String(q.id), resume: "Retirer une question de la banque", retrait: true }); emettre("jeu", { nom: "banque" }); }
      } })) : null);
}
async function enregistrerQuestion(v, q) {
  const corps = { theme: v.theme, question: qTexte(v).trim(), reponse: qReponse(v).trim(), variantes: qVariantes(v), source: (qSource(v).url || "").trim(),
    section: v.section || "", extrait: v.extrait || "", difficulte: DIFF_NOMS[qDifficulte(v)] || "moyenne", statut: v.statut === "confirme" ? "confirme" : "a_verifier",
    actif: qActive(v) };
  if (v.type) corps.type = v.type;
  if (q && q.id && !String(q.id).startsWith("tmp-")) { corps.id = q.id; corps.version = q.version; }
  const cle = q && q.id ? String(q.id) : "tmp-" + uuid();
  await mettreEnFile("recrutement/question", corps, { genre: "question", cle, resume: "Question : " + corps.question.slice(0, 60), objet: Object.assign({}, q || {}, corps, { id: q && q.id ? q.id : cle, _cle: cle }) });
  emettre("jeu", { nom: "banque" });
}
function editerQuestion(B, q) {
  const v = q ? Object.assign({}, q, { question: qTexte(q), reponse: qReponse(q), variantes: qVariantes(q).slice(), source: qSource(q), difficulte: qDifficulte(q) })
    : { theme: themesDe(B)[0][0], question: "", reponse: "", variantes: [], source: { titre: "", url: "", minutage: "" }, section: "", extrait: "", difficulte: 1, statut: "a_verifier", active: true };
  const p = pancarte({ titre: q ? "Modifier la question" : "Nouvelle question", sous: "Uniquement des faits vérifiables, avec leur source.", icone: "parchemin", taille: "large" });
  const texte = zoneTexte({ rows: 3, maxlength: 400, placeholder: "Quel studio développe RELL Seas ?" }, v.question);
  texte.addEventListener("input", () => { v.question = texte.value; });
  const rep = saisie({ value: v.reponse, maxlength: 200, placeholder: "RELL Games" });
  rep.addEventListener("input", () => { v.reponse = rep.value; });
  const variantesZone = h("div", { classe: "variantes edition" });
  const majVariantes = () => remplacer(variantesZone, ...v.variantes.map((x, i) => h("span", { classe: "variante" }, x, boutonIcone("fermer", "Retirer « " + x + " »", () => { v.variantes.splice(i, 1); majVariantes(); }, "variante-retirer"))));
  majVariantes();
  const ajout = saisie({ maxlength: 200, placeholder: "Ajoute une variante puis Entrée" });
  ajout.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const x = ajout.value.trim(); if (x && !v.variantes.includes(x) && v.variantes.length < 20) { v.variantes.push(x); majVariantes(); } ajout.value = ""; } });
  const s = (obj, k, attrs) => { const x = saisie(Object.assign({ value: obj[k] || "" }, attrs)); x.addEventListener("input", () => { obj[k] = x.value; }); return x; };
  const extrait = zoneTexte({ rows: 2, maxlength: 600, placeholder: "La phrase exacte de la source (facultatif)" }, v.extrait);
  extrait.addEventListener("input", () => { v.extrait = extrait.value; });
  ajouter(p.corps, [
    liste({ valeur: v.theme, label: "Thème", plein: true, options: themesDe(B).map(([k, n]) => ({ v: k, l: n })), changer: (x) => { v.theme = x; } }),
    champ("La question", texte), champ("La réponse attendue", rep),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Variantes admises"), variantesZone, ajout, h("span", { classe: "champ-aide" }, "D'autres façons justes de répondre (autre langue, abréviation…). Elles aident l'indication de proximité.")),
    h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "La source"),
      champ("Lien (https)", s(v.source, "url", { maxlength: 500, placeholder: "https://rellseas.fandom.com/wiki/…", inputmode: "url" }), { aide: "La page du wiki, ou la vidéo avec son minutage dans l'adresse." }),
      h("div", { classe: "champs" }, champ("Section", s(v, "section", { maxlength: 120 }), { optionnel: true })),
      champ("Extrait", extrait, { optionnel: true })),
    radios("diff-q", [["1", "Facile"], ["2", "Moyenne"], ["3", "Difficile"]], String(v.difficulte), (x) => { v.difficulte = Number(x); }, "Difficulté"),
    radios("statut-q", [["confirme", "Confirmée", "vérifiée à la source"], ["a_verifier", "À vérifier"]], v.statut === "confirme" ? "confirme" : "a_verifier", (x) => { v.statut = x; }, "Statut"),
    interrupteur("Active (proposée dans le choix des questions)", qActive(v), (x) => { v.active = x; v.actif = x; })]);
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), bouton("Enregistrer", { classe: "principal", icone: "valider", onclick: async () => {
    if (!v.question.trim() || !v.reponse.trim()) { toast("La question et la réponse attendue sont obligatoires.", "erreur"); return; }
    if (v.source.url && !/^https:\/\//.test(v.source.url)) { toast("Le lien de la source doit commencer par https://", "erreur"); return; }
    await enregistrerQuestion(v, q);
    p.fermer();
    toast(enLigne() ? "Question enregistrée." : "Question gardée sur l'appareil : elle partira au retour de la connexion.", "succes");
  } })]);
}
function blocModeles(B) {
  const modeles = B.modeles || [];
  return h("div", { classe: "pile" },
    h("p", { classe: "aide" }, "Un modèle, c'est une sélection de questions prête à envoyer en un clic. Le modèle par défaut est proposé d'emblée à chaque candidat (et utilisé sur Discord)."),
    modeles.length ? h("div", { classe: "grille" }, modeles.map((m) => h("article", { classe: "feuillet" + (m.par_defaut ? " calme" : "") + (m._attente ? " en-attente" : "") },
      h("div", { classe: "rangee entre" }, h("h3", { classe: "titre-carte" }, sansEmoji(m.nom)), m.par_defaut ? tampon("Par défaut", "vert", true) : null),
      h("p", { classe: "meta" }, compte((m.questions || []).length, "question")),
      peutAgir() ? h("div", { classe: "feuillet-pied" },
        bouton("Les questions", { classe: "p", icone: "plume", onclick: () => choisirHorsDossier("modele", (m.questions || []).map(String), (ids) => enregistrerModeleDirect(m, { questions: ids }), "Modèle « " + m.nom + " »") }),
        bouton("Renommer", { classe: "p discret", onclick: async () => {
          const nom = saisie({ value: m.nom, maxlength: 60 });
          const ok = await confirmer({ titre: "Renommer le modèle", contenu: [champ("Nom", nom)], libelleOk: "Renommer" });
          if (ok && nom.value.trim()) enregistrerModeleDirect(m, { nom: nom.value.trim() });
        } }),
        m.par_defaut ? null : bouton("Par défaut", { classe: "p discret", icone: "etoile", onclick: () => enregistrerModeleDirect(m, { par_defaut: true }) }),
        bouton("Supprimer", { classe: "p discret danger", icone: "supprimer", onclick: async () => {
          const ok = await confirmer({ titre: "Supprimer le modèle « " + m.nom + " » ?", texte: "Les questions restent dans la banque.", libelleOk: "Supprimer", style: "danger" });
          if (ok) { await mettreEnFile("recrutement/modele/retirer", { id: m.id }, { genre: "modele", cle: String(m.id), resume: "Supprimer le modèle « " + m.nom + " »", retrait: true }); emettre("jeu", { nom: "banque" }); }
        } })) : null))) : vide("Aucun modèle", "Dans le choix des questions d'un candidat, « Enregistrer comme modèle »."),
    peutAgir() ? h("div", { classe: "rangee" }, bouton("Nouveau modèle", { icone: "ajouter", onclick: () => choisirHorsDossier("modele", [], (ids) => enregistrerModele(ids, false), "Nouveau modèle") })) : null);
}
async function enregistrerModeleDirect(m, changements) {
  const corps = { id: m.id, version: m.version, nom: changements.nom || m.nom, questions: (changements.questions || m.questions || []).map(String), par_defaut: changements.par_defaut ?? !!m.par_defaut };
  await mettreEnFile("recrutement/modele", corps, { genre: "modele", cle: String(m.id), resume: "Modèle « " + corps.nom + " »", objet: Object.assign({}, m, corps) });
  toast("Modèle enregistré.", "succes");
  emettre("jeu", { nom: "banque" });
}
function blocLiens(B) {
  const liens = copie(B.liens || []);
  const zone = h("div", { classe: "pile" });
  const ligne = (l, i) => {
    const titre = saisie({ value: l.titre || "", maxlength: 120, "aria-label": "Titre du lien", placeholder: "Vidéo officielle du Movie 3" });
    const url = saisie({ value: l.url || "", maxlength: 500, "aria-label": "Adresse", placeholder: "https://…", inputmode: "url" });
    const desc = saisie({ value: l.description || "", maxlength: 300, "aria-label": "Description", placeholder: "Ce qu'on y trouve" });
    titre.addEventListener("input", () => { l.titre = titre.value; });
    url.addEventListener("input", () => { l.url = url.value.trim(); });
    desc.addEventListener("input", () => { l.description = desc.value; });
    return h("div", { classe: "lien-ligne" }, h("span", { classe: "selection-num" }, String(i + 1)), h("div", { classe: "champs" }, titre, url, desc),
      h("span", { classe: "selection-outils" },
        boutonIcone("haut", "Monter", () => { if (i > 0) { [liens[i - 1], liens[i]] = [liens[i], liens[i - 1]]; dessiner(); } }),
        boutonIcone("bas", "Descendre", () => { if (i < liens.length - 1) { [liens[i + 1], liens[i]] = [liens[i], liens[i + 1]]; dessiner(); } }),
        boutonIcone("supprimer", "Retirer ce lien", () => { liens.splice(i, 1); dessiner(); })));
  };
  const dessiner = () => remplacer(zone,
    h("p", { classe: "aide" }, "Rappelés dans chaque questionnaire de l'étape 2 : « toutes les réponses se trouvent dans ces liens »."),
    B._liensAttente ? bandeau("Liens gardés sur l'appareil : ils partiront au retour de la connexion.", "") : null,
    liens.length ? h("div", { classe: "pile serree" }, liens.map(ligne)) : vide("Aucun lien", "Ajoute la vidéo du Movie 3, le wiki, le guide du clan…", "lien"),
    peutAgir() ? h("div", { classe: "rangee" },
      bouton("Ajouter un lien", { classe: "p", icone: "ajouter", onclick: () => { const max = (B.limites && B.limites.liens) || 10; if (liens.length >= max) { toast(max + " liens au plus.", "erreur"); return; } liens.push({ titre: "", url: "", description: "" }); dessiner(); } }),
      bouton("Enregistrer les liens", { classe: "p principal", icone: "valider", onclick: async () => {
        const propres = liens.filter((l) => (l.titre || "").trim() || l.url);
        const mauvais = propres.find((l) => !/^https:\/\/\S+$/.test(l.url || ""));
        if (mauvais) { toast("Chaque lien doit commencer par https:// (« " + (mauvais.titre || mauvais.url) + " »).", "erreur"); return; }
        const sansTitre = propres.find((l) => !(l.titre || "").trim());
        if (sansTitre) { toast("Chaque lien a besoin d'un titre (« " + sansTitre.url + " »).", "erreur"); return; }
        await mettreEnFile("recrutement/liens", { version: B.liens_version, liens: propres.map((l) => ({ id: l.id, titre: (l.titre || "").trim(), url: l.url, description: (l.description || "").trim() })) }, { genre: "liens", cle: "liens", resume: "Les liens du questionnaire (" + propres.length + ")" });
        toast("Liens enregistrés.", "succes");
        emettre("jeu", { nom: "banque" });
      } })) : null);
  dessiner();
  return zone;
}
function blocReglages(B) {
  const r = B.reglages || {};
  const max = (B.limites && B.limites.par_envoi) || 40;
  const v = { nombre: Math.max(1, Math.min(max, Number(r.nombre || r.nombre_defaut) || 10)), version: r.version };
  const nombreE = h("input", { type: "number", classe: "saisie", min: 1, max, value: v.nombre, inputmode: "numeric", "aria-label": "Nombre de questions par défaut" });
  nombreE.addEventListener("input", () => { v.nombre = Math.max(1, Math.min(max, Number(nombreE.value) || 1)); });
  const pas = (d) => () => { v.nombre = Math.max(1, Math.min(max, v.nombre + d)); nombreE.value = v.nombre; };
  const defaut = modeleDefautObjet(B);
  return h("div", { classe: "cadre pile serree" },
    B._reglagesAttente ? bandeau("Réglages gardés sur l'appareil : ils partiront au retour de la connexion.", "") : null,
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Nombre de questions par défaut"),
      h("div", { classe: "pas-a-pas" }, boutonIcone("moins", "Une de moins", pas(-1)), nombreE, boutonIcone("plus", "Une de plus", pas(1))),
      h("span", { classe: "champ-aide" }, "Tirées parmi les questions confirmées quand aucun modèle n'est « par défaut ». Le candidat lit dès l'ouverture du ticket combien de questions l'attendent"
        + (r.annonce ? " (aujourd'hui : " + r.annonce + ")." : "."))),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Sélection par défaut"),
      h("p", { classe: "aide" }, defaut ? "Le modèle « " + sansEmoji(defaut.nom) + " » (" + compte((defaut.questions || []).length, "question") + ") : proposé à chaque candidat, et envoyé quand on passe à l'étape 2 depuis Discord."
        : "Aucun modèle par défaut : marque un modèle « Par défaut » pour choisir les questions envoyées d'office.")),
    peutAgir() ? h("div", { classe: "rangee" }, bouton("Enregistrer les réglages", { classe: "p principal", icone: "valider", onclick: () => enregistrerReglages(v) })) : null);
}
async function enregistrerReglages(v) {
  await mettreEnFile("recrutement/reglages", { nombre: v.nombre, version: v.version }, { genre: "reglages", cle: "reglages", resume: "Réglages du questionnaire" });
  toast("Réglages enregistrés.", "succes");
  emettre("jeu", { nom: "banque" });
}
