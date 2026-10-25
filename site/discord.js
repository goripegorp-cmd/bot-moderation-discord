// discord.js — « Le Port » : aperçu, journal, sanctions, tickets, répertoire, salons & questions, nettoyage.

import { h, icone, date, heure, depuis, duree, nombre, cleJour, libelleJour, libelleMois, moisDe, maintenant, sansEmoji, norm, contient, lettre, trier, compte, remplacer, quantite, accord, ajouter } from "./dom.js";
import { etat, P, peutAgir, aller, filtres, enLigne, emettre, ecouter } from "./noyau.js";
import { lienExport, lire, poster } from "./api.js";
import { charger, vue as vueJeu } from "./donnees.js";
import { file } from "./hors_ligne.js";
import {
  bouton, avatar, pastille, tampon, vide, tuile, tuiles, puces, segment, recherche, liste, menu, groupe, paginer, indexAZ,
  section, sectionTete, barres, barresH, ENCRES, lienNom, nomDe, confirmer, toast, bandeau, caseACocher, compteur, squelettes, boutonCopie,
} from "./ui.js";
import {
  ouvrirFiche, ouvrirConversation, agir, entreeJournal, teinteCat, teinteType, libelleType, GROUPES_SANCTION, STATUTS_Q, STATUTS_S,
  STATUTS_I, STATUTS_CAND, deplier, sondageVotes,
} from "./fiche.js";

const JOUR = 86400;
const resetPages = (prefixe) => { for (const k of Object.keys(etat.pages)) if (k.startsWith(prefixe)) delete etat.pages[k]; };
export const indisponible = () => vide("Données indisponibles", etat.reseau.enLigne ? "Le serveur ne répond pas pour le moment : nouvel essai automatique." : "Hors ligne, et rien n'est encore en mémoire sur cet appareil.", "hors_ligne");
const exporter = (libelle, items) => menu(bouton(libelle || "Exporter", { icone: "exporter", reseau: true }), items.map(([l, p]) => ({ l, icone: "exporter", href: lienExport(p), telecharger: true })));

// ─── Aperçu ─────────────────────────────────────────────────────────────────
export function apercu(vue) {
  const zone = h("div", { classe: "pile" });
  ajouter(vue, [zone]);
  const maj = () => {
    const d = etat.d;
    if (!d) { remplacer(zone, indisponible()); return; }
    const n = maintenant();
    const ouverts = d.tickets.ouverts, nonPris = ouverts.filter((t) => !t.pris_par);
    const qs = (d.questions && d.questions.liste) || [], qOuvertes = qs.filter((q) => q.statut === "ouverte");
    const alertes = d.alertes || [], clan = (d.clan && d.clan.membres) || [];
    const inactifs = clan.filter((m) => m.rang === 2).length;
    const st = (d.questions && d.questions.stats) || {};
    const aCorriger = d.en_cours.filter((c) => /reponse|partiel|corriger/.test(c.recrutement || "")).length;
    const aDecider = d.en_cours.filter((c) => (c.etape || 1) === 1).length;
    const attente = file.ops.length;
    const t = tuiles(
      tuile({ cle: "a1", lib: "Tickets ouverts", val: ouverts.length, icone: "tickets", sous: nonPris.length + " pas encore pris", teinte: "#a8641c", clic: () => aller("port", "tickets") }),
      tuile({ cle: "a2", lib: "Questions sans réponse", val: qOuvertes.length, icone: "salons", sous: st.delai_median ? "réponse médiane : " + duree(st.delai_median) : "aucune réponse mesurée", teinte: "#1f4e5a", clic: () => aller("port", "salons", "questions") }),
      tuile({ cle: "a3", lib: "Alertes en cours", val: alertes.length, icone: "attention", sous: alertes.length ? "membres qui cumulent du grave" : "rien à signaler", teinte: alertes.length ? "#8e2a24" : "#3f6b3a" }),
      tuile({ cle: "a4", lib: "Sanctions · 30 jours", val: d.sanctions.trente_jours, icone: "sanctions", sous: nombre(d.sanctions.total) + " au casier", teinte: "#5e3a4e", clic: () => aller("port", "sanctions") }),
      tuile({ cle: "a5", lib: "Candidatures", val: d.en_cours.length, icone: "candidatures", sous: aDecider + " à décider · " + aCorriger + " à corriger", teinte: "#7a4b2a", clic: () => aller("equipage", "candidatures") }),
      tuile({ cle: "a6", lib: "Membres du clan", val: clan.length, icone: "equipage", sous: quantite(inactifs, "inactif(s)") + " depuis un mois", teinte: "#3f6b3a", clic: () => aller("equipage", "membres") }),
      attente ? tuile({ cle: "a7", lib: "Modifications à envoyer", val: attente, icone: "synchro", sous: "faites hors ligne, elles partent au retour", teinte: "#7a5a22", clic: () => emettre("file:ouvrir") }) : null);
    const items = [];
    alertes.forEach((a) => items.push(carteAlerte(a)));
    nonPris.filter((x) => x.ouvert && n - x.ouvert > 6 * 3600).slice(0, 4).forEach((x) => items.push(carteTicketOuvert(x)));
    qOuvertes.filter((q) => n - q.quand > 1800).slice(0, 4).forEach((q) => items.push(carteQuestions(q.id, [q])));
    d.en_cours.filter((c) => /reponse|partiel/.test(c.recrutement || "") || (c.ouvert && n - c.ouvert > 2 * JOUR && (c.etape || 1) === 1)).slice(0, 4).forEach((c) => items.push(carteCandidatureCourte(c)));
    const urgent = section("À traiter maintenant", "attention", items.length ? compte(items.length, "élément") : "",
      items.length ? h("div", { classe: "grille" }, items) : vide("Rien d'urgent", "Pas d'alerte, pas de ticket oublié, pas de question en attente.", "succes"));
    const pj = (d.journal && d.journal.par_jour) || {}, jours = [], fam = {};
    for (let i = 13; i >= 0; i--) jours.push(cleJour(n - i * JOUR));
    const connues = ["Modération", "Sécurité", "Tickets", "Questions", "Clan", "Membres", "Messages", "Vocal"];
    for (const k of jours) {
      const v = pj[k] || {};
      fam[k] = { mod: (v["Modération"] || 0) + (v["Sécurité"] || 0), sup: (v["Tickets"] || 0) + (v["Questions"] || 0) + (v["Clan"] || 0),
        mem: v["Membres"] || 0, msg: (v["Messages"] || 0) + (v["Vocal"] || 0),
        autre: Object.entries(v).filter(([c]) => !connues.includes(c)).reduce((a, [, x]) => a + x, 0) };
    }
    const eq = d.equipe || [];
    const graphes = h("div", { classe: "duo" },
      h("div", { classe: "cadre" }, h("h3", {}, "Activité · 14 jours"), h("p", { classe: "aide" }, "Tout ce que le journal a consigné, jour par jour."),
        barres(jours, fam, [["mod", ENCRES.cire, "Modération et sécurité"], ["sup", ENCRES.sienne, "Tickets, questions, clan"], ["mem", ENCRES.vert, "Arrivées et départs"],
          ["msg", ENCRES.mer, "Messages et vocal"], ["autre", ENCRES.corde, "Autre"]], "Le journal se remplit au fil des évènements.")),
      h("div", { classe: "cadre" }, h("h3", {}, "Équipe · 30 jours"), h("p", { classe: "aide" }, "Tickets pris ou fermés, sanctions, questions répondues. Direction et fondateur à part."),
        eq.length ? barresH(eq.map((x) => [nomDe(P(x.id)), x.tickets + x.sanctions + x.questions, quantite(x.tickets, "ticket(s)") + " · " + quantite(x.sanctions, "sanction(s)") + " · " + quantite(x.questions, "question(s)"), () => ouvrirFiche(x.id)])) : vide("Rien sur 30 jours")));
    remplacer(zone, t, urgent, graphes);
  };
  maj();
  return { maj };
}

function carteAlerte(a) {
  const p = P(a.id);
  return h("article", { classe: "feuillet alerte" },
    h("div", { classe: "qui" }, avatar(p), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, nomDe(p)),
      h("div", { classe: "sous-nom" }, quantite(a.incidents, "incident(s)") + " · " + quantite(a.points, "point(s)") + " en 24 h")), tampon("Alerte")),
    h("ul", { classe: "entrees" }, (a.evenements || []).slice(-3).reverse().map((e) => h("li", { classe: "entree" + (e.gravite >= 2 ? " grave" : "") },
      h("div", { classe: "haut" }, h("span", { classe: "quoi" }, heure(e.quand)), h("span", { classe: "quand" }, depuis(e.quand))), h("div", { classe: "texte coupe2" }, e.texte)))),
    h("div", { classe: "feuillet-pied" },
      bouton("Voir la fiche", { classe: "p", icone: "oeil", onclick: () => ouvrirFiche(a.id) }),
      bouton("Gérée", { classe: "p vert", icone: "valider", reseau: true, onclick: () => agir({ action: "alerte_geree", membre: a.id }, "Alerte gérée ?", "Elle disparaît des alertes ; le compteur de " + nomDe(p) + " repart de zéro.", {}, "Gérée", "vert") })));
}
function carteCandidatureCourte(c) {
  const etape = (c.etape || 1) === 1 ? "Étape 1 à décider" : /reponse|partiel/.test(c.recrutement || "") ? "Étape 2 à corriger" : "Étape 2 en cours";
  return h("article", { classe: "feuillet lien chaude", tabindex: 0, onclick: () => emettre("dossier:ouvrir", c.ticket), onkeydown: (e) => { if (e.key === "Enter") emettre("dossier:ouvrir", c.ticket); } },
    h("div", { classe: "qui" }, avatar(c), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, nomDe(c)), h("div", { classe: "sous-nom" }, "Candidature · ouverte " + depuis(c.ouvert))), tampon(etape, "ambre")),
    h("p", { classe: "aide" }, "Ouvre le dossier pour décider, choisir les questions ou corriger."));
}

// ─── Journal ────────────────────────────────────────────────────────────────
export function journal(vue) {
  const f = filtres("journal", { q: "", periode: "7", cat: "tous", vue: "jours", gravite: "0" });
  const resultats = h("div", { classe: "pile" });
  const changer = () => { resetPages("jour"); maj(); };
  const outils = h("div", { classe: "outils" },
    recherche(f.q, "Membre, identifiant, salon, texte…", (q) => { f.q = q; changer(); }),
    liste({ valeur: f.periode, label: "Période", options: [["1", "24 heures"], ["7", "7 jours"], ["30", "30 jours"], ["tout", "Tout ce qui est chargé"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.periode = v; changer(); } }),
    segment(f.gravite, [["0", "Tout"], ["1", "Important"], ["2", "Grave"]], (v) => { f.gravite = v; changer(); }, "Gravité"),
    segment(f.vue, [["jours", "Par jour"], ["personnes", "Par personne"]], (v) => { f.vue = v; changer(); }, "Présentation"),
    exporter("Exporter", [["Journal · 7 jours (CSV)", { quoi: "journal", jours: 7 }], ["Journal · 30 jours (CSV)", { quoi: "journal", jours: 30 }], ["Journal · 90 jours (CSV)", { quoi: "journal", jours: 90 }],
      ["Journal · 30 jours (JSON)", { quoi: "journal", jours: 30, format: "json" }], ...(peutAgir() ? [["Erreurs du bot · 30 jours (CSV)", { quoi: "erreurs" }]] : [])]));
  const tete = h("div");
  ajouter(vue, [tete, outils, h("p", { classe: "aide" }, "Plus aucun log sur Discord : tout arrive ici. Conservation : messages et vocal 30 jours, le reste 90 jours (rubrique Nettoyage). Les 400 derniers évènements sont chargés ; l'export prend tout."), resultats]);
  const maj = () => {
    const d = etat.d;
    if (!d) { remplacer(resultats, indisponible()); return; }
    const j = d.journal || {}, evts = j.evenements || [], n = maintenant();
    if (j.erreur) { remplacer(resultats, vide("Journal momentanément illisible", "Nouvel essai à la prochaine mise à jour.", "attention")); return; }
    const auj = cleJour(n), sept = evts.filter((e) => n - e.quand <= 7 * JOUR);
    remplacer(tete, tuiles(
      tuile({ cle: "j1", lib: "Aujourd'hui", val: evts.filter((e) => cleJour(e.quand) === auj).length, icone: "journal", sous: "évènements consignés", teinte: "#1f4e5a" }),
      tuile({ cle: "j2", lib: "Graves · 7 jours", val: sept.filter((e) => e.gravite >= 2).length, icone: "attention", sous: "sanctions lourdes, détections", teinte: "#8e2a24" }),
      tuile({ cle: "j3", lib: "Personnes · 7 jours", val: new Set(sept.map((e) => e.membre).filter(Boolean)).size, icone: "membres", sous: "concernées par un évènement", teinte: "#3f6b3a" })));
    const limite = f.periode === "tout" ? 0 : n - Number(f.periode) * JOUR;
    const dansPeriode = evts.filter((e) => e.quand >= limite && (e.gravite || 0) >= Number(f.gravite));
    const nb = {};
    dansPeriode.forEach((e) => { nb[e.cat] = (nb[e.cat] || 0) + 1; });
    if (f.cat !== "tous" && !nb[f.cat]) f.cat = "tous";
    const texte = (e) => [e.texte, e.detail, e.salon, e.cat, ...[e.membre, e.auteur].filter(Boolean).flatMap((id) => [id, P(id).nom, P(id).pseudo])].join(" ");
    const liste_ = dansPeriode.filter((e) => (f.cat === "tous" || e.cat === f.cat) && contient(texte(e), f.q));
    const blocs = [puces([["tous", "Tout", dansPeriode.length], ...Object.keys(nb).sort((a, b) => nb[b] - nb[a]).map((c) => [c, c, nb[c], teinteCat(c)])], f.cat, (v) => { f.cat = v; changer(); }, "Catégories")];
    if (!liste_.length) { remplacer(resultats, ...blocs, vide("Rien ici", "Change la période, la catégorie ou la recherche.")); return; }
    // L'important d'abord : les faits graves de la période, en tête.
    const graves = liste_.filter((e) => e.gravite >= 2);
    if (graves.length && f.gravite !== "2") {
      blocs.push(section("L'important d'abord", "attention", compte(graves.length, "fait grave", "faits graves"),
        h("div", { classe: "feuillet alerte" }, paginer("jour-graves", graves, (e) => entreeJournal(e, null), { classe: "entrees", balise: "ul", pas: 8 }))));
    }
    if (f.vue === "personnes") {
      const groupes = new Map();
      liste_.forEach((e) => { const k = e.membre || "serveur"; if (!groupes.has(k)) groupes.set(k, []); groupes.get(k).push(e); });
      blocs.push(section("Par personne", "membres", quantite(groupes.size, "personne(s)") + " · " + quantite(liste_.length, "évènement(s)"),
        paginer("jour-p", [...groupes.entries()], ([id, l]) => carteJournal(id, l))));
    } else {
      const jours = new Map();
      liste_.forEach((e) => { const k = cleJour(e.quand); if (!jours.has(k)) jours.set(k, []); jours.get(k).push(e); });
      const cles = [...jours.keys()];
      blocs.push(section("Jour par jour", "calendrier", compte(liste_.length, "évènement"),
        h("div", { classe: "jours" }, cles.map((k, i) => {
          const l = jours.get(k), g = l.filter((e) => e.gravite >= 2).length;
          return groupe({ titre: libelleJour(k), compte: l.length, chaud: g > 0, info: g ? compte(g, "grave", "graves") : "", cle: "jour-" + k, ouvert: i === 0 || !!f.q || f.cat !== "tous" ? true : undefined },
            () => h("div", { classe: "feuillet" }, paginer("jour-j-" + k, l, (e) => entreeJournal(e, null), { classe: "entrees", balise: "ul", pas: 30 })));
        }))));
    }
    remplacer(resultats, ...blocs);
  };
  maj();
  return { maj };
}
function carteJournal(id, evts) {
  const serveur = id === "serveur", p = serveur ? { nom: "Serveur", pseudo: "", avatar: "" } : P(id);
  const cats = {};
  evts.forEach((e) => { cats[e.cat] = (cats[e.cat] || 0) + 1; });
  const graves = evts.filter((e) => e.gravite >= 2).length;
  const ouvrir = () => ouvrirFiche(id, "journal");
  return h("article", { classe: "feuillet" + (serveur ? "" : " lien") + (graves ? " alerte" : ""), tabindex: serveur ? null : 0, onclick: serveur ? null : ouvrir, onkeydown: serveur ? null : (e) => { if (e.key === "Enter") ouvrir(); } },
    h("div", { classe: "qui" }, avatar(p), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, nomDe(p)), h("div", { classe: "sous-nom" }, quantite(evts.length, "évènement(s)") + " · dernier " + depuis(evts[0].quand)))),
    h("div", { classe: "pastilles" }, Object.entries(cats).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([c, k]) => pastille(k + " · " + c, teinteCat(c)))),
    h("ul", { classe: "entrees" }, evts.slice(0, 3).map((e) => entreeJournal(e, id))),
    evts.length > 3 ? h("div", { classe: "compte-pied" }, "+ " + quantite(evts.length - 3, "autre(s)") + (serveur ? "" : " — tout est dans la fiche")) : null);
}

// ─── Sanctions ──────────────────────────────────────────────────────────────
export function sanctions(vue) {
  const f = filtres("sanctions", { q: "", periode: "90", groupe: "tous", origine: "tous", tri: "recent" });
  const haut = h("div", { classe: "pile" }), resultats = h("div", { classe: "pile" }), bas = h("div", { classe: "pile" });
  const changer = () => { resetPages("mod"); majResultats(); };
  const outils = h("div", { classe: "outils" },
    recherche(f.q, "Membre, identifiant, motif, modérateur…", (q) => { f.q = q; changer(); }),
    liste({ valeur: f.periode, label: "Période", options: [["7", "7 jours"], ["30", "30 jours"], ["90", "90 jours"], ["365", "12 mois"], ["tout", "Tout le casier"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.periode = v; changer(); } }),
    liste({ valeur: f.origine, label: "Origine", options: [["tous", "Staff et automatique"], ["staff", "Décidées par le staff"], ["auto", "Automatiques"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.origine = v; changer(); } }),
    liste({ valeur: f.tri, label: "Tri", options: [["recent", "Plus récents"], ["nombre", "Plus sanctionnés"], ["nom", "Nom A → Z"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.tri = v; changer(); } }),
    exporter("Exporter", [["Casier complet (CSV)", { quoi: "sanctions" }], ["Casier complet (JSON)", { quoi: "sanctions", format: "json" }]]));
  ajouter(vue, [haut, outils, resultats, bas]);
  const majHaut = () => {
    const s = etat.d && etat.d.sanctions;
    if (!s) { remplacer(haut, indisponible()); remplacer(bas); return; }
    const somme = (cles) => s.types.filter((t) => cles.includes(t.type)).reduce((a, t) => a + t.n, 0);
    const actives = s.actives.mutes.length + s.actives.radies.length + s.actives.restreints.length;
    const enCeMoment = actives ? h("div", { classe: "cadre pile serree" }, h("h3", {}, "En ce moment"),
      groupeActif("Mutés", s.actives.mutes, (m) => (m.jusqu ? "jusqu'à " + heure(m.jusqu) : "")),
      groupeActif("Radiés", s.actives.radies, () => ""),
      groupeActif("Restreints par la direction", s.actives.restreints, (m) => (m.par ? "par " + m.par : ""))) : null;
    remplacer(haut, tuiles(
      tuile({ cle: "m1", lib: "30 derniers jours", val: s.trente_jours, icone: "calendrier", sous: "tout le casier", teinte: "#1f4e5a" }),
      tuile({ cle: "m2", lib: "Avertissements", val: somme(["warn"]), icone: "plume", sous: "depuis le début", teinte: "#a8641c" }),
      tuile({ cle: "m3", lib: "Mutes", val: somme(["mute"]), icone: "cadenas", sous: "depuis le début", teinte: "#5e3a4e" }),
      tuile({ cle: "m4", lib: "Expulsions et bans", val: somme(["kick", "ban"]), icone: "sabre", sous: "depuis le début", teinte: "#8e2a24" }),
      tuile({ cle: "m5", lib: "Par le staff", val: s.manuel, icone: "personne", sous: quantite(s.auto, "automatique(s)"), teinte: "#4a5560" }),
      tuile({ cle: "m6", lib: "En ce moment", val: actives, icone: "minuteur", sous: "mutés, radiés, restreints", teinte: "#7a4b2a" })), enCeMoment, cadreNettoyageCasier());
    remplacer(bas,
      groupe({ titre: "Modérateurs", compte: s.staff.length, cle: "mod-staff", icone: "personne" }, () => [h("p", { classe: "aide" }, "Sanctions décidées à la main, par personne. Direction et fondateur à part."),
        s.staff.length ? h("div", { classe: "grille etroite" }, s.staff.map(carteModerateur)) : vide("Aucune sanction décidée à la main")]),
      groupe({ titre: "Tendances", cle: "mod-tendances", icone: "carte" }, () => h("div", { classe: "duo" },
        h("div", { classe: "cadre" }, h("h3", {}, "Sanctions par mois"), h("p", { classe: "aide" }, "Tout le casier, sur douze mois."),
          barres(Object.keys(s.mois).sort(), s.mois, Object.entries(GROUPES_SANCTION).map(([g, c]) => [g, c, g]), "Le casier est vide pour l'instant.")),
        h("div", { classe: "cadre" }, h("h3", {}, "Par type"), h("p", { classe: "aide" }, "Depuis le début du casier."),
          s.types.length ? barresH(s.types.map((t) => [t.libelle, t.n])) : vide("Casier vide")))));
  };
  const majResultats = () => {
    const s = etat.d && etat.d.sanctions;
    if (!s) { remplacer(resultats); return; }
    const limite = f.periode === "tout" ? 0 : maintenant() - Number(f.periode) * JOUR;
    const garde = (x) => (x.date || 0) >= limite && (f.origine === "tous" || (f.origine === "auto") === !!x.auto);
    const nbGroupe = { tous: 0 };
    Object.keys(GROUPES_SANCTION).forEach((g) => { nbGroupe[g] = 0; });
    const cartes = [];
    for (const m of s.membres) {
      const p = P(m.id);
      if (f.q && !contient([p.nom, p.pseudo, m.id, ...m.liste.map((x) => x.raison + " " + x.par)].join(" "), f.q)) continue;
      const dansPeriode = m.liste.filter(garde);
      if (!dansPeriode.length) continue;
      nbGroupe.tous++;
      new Set(dansPeriode.map((x) => x.groupe)).forEach((g) => { nbGroupe[g] = (nbGroupe[g] || 0) + 1; });
      const entrees = f.groupe === "tous" ? dansPeriode : dansPeriode.filter((x) => x.groupe === f.groupe);
      if (!entrees.length) continue;
      const toutes = f.origine === "tous" && f.groupe === "tous";
      const nbr = toutes && f.periode === "tout" ? m.total : toutes && f.periode === "90" ? m.n90 : toutes && f.periode === "30" ? m.n30 : (m.liste.length >= 12 && entrees.length === m.liste.length ? entrees.length + "+" : entrees.length);
      cartes.push([m, entrees, nbr]);
    }
    if (f.tri === "nombre") cartes.sort((a, b) => parseInt(b[2], 10) - parseInt(a[2], 10) || b[0].derniere - a[0].derniere);
    else if (f.tri === "nom") cartes.sort((a, b) => nomDe(P(a[0].id)).localeCompare(nomDe(P(b[0].id)), "fr"));
    remplacer(resultats,
      puces([["tous", "Tous", nbGroupe.tous], ...Object.entries(GROUPES_SANCTION).map(([g, c]) => [g, g, nbGroupe[g], c])], f.groupe, (v) => { f.groupe = v; changer(); }, "Types"),
      section("Le casier, par membre", "repertoire", compte(cartes.length, "personne"),
        h("div", { classe: "pile" }, h("p", { classe: "aide" }, "Une case par personne : tout ce qu'elle a reçu sur la période. Clique pour toute sa fiche."),
          cartes.length ? paginer("mod", cartes, ([m, e, c]) => carteCasier(m, e, c)) : vide("Personne au casier ici", "Change la période, le type ou la recherche."))));
  };
  const maj = () => { majHaut(); majResultats(); };
  maj();
  return { maj };
}
function groupeActif(titre, l, extra) {
  if (!l.length) return null;
  return h("div", { classe: "pile serree" }, h("div", { classe: "champ-lib" }, titre + " · " + l.length),
    h("div", { classe: "pastilles" }, l.slice(0, 40).map((m) => h("button", { classe: "puce", type: "button", onclick: () => ouvrirFiche(m.id) }, avatar(m, "xs"), h("span", { classe: "puce-lib" }, nomDe(m)), extra(m) ? h("span", { classe: "n" }, extra(m)) : null))));
}
function cadreNettoyageCasier() {
  const c = (etat.d && etat.d.casier) || {}, lots = c.lots || [];
  if (!peutAgir() && !lots.length) return null;
  return h("div", { classe: "cadre pile serree" }, h("h3", {}, "Nettoyer le casier"),
    h("p", { classe: "aide" }, "Repartir de zéro ou nettoyer une zone ; les bannissements restent, tout se défait pendant 30 jours. Amnistie automatique : 3 mois sans infraction."),
    peutAgir() ? h("div", { classe: "rangee" }, bouton("Nettoyer le casier…", { classe: "p danger", icone: "nettoyage", reseau: true, onclick: nettoyerCasier })) : null,
    lots.length ? h("ul", { classe: "entrees" }, lots.map((l) => h("li", { classe: "entree" },
      h("div", { classe: "haut" }, h("span", { classe: "quoi" }, l.quoi), h("span", { classe: "quand" }, depuis(l.quand))),
      h("div", { classe: "meta" }, quantite(l.n, "entrée(s)") + " · " + quantite(l.personnes, "personne(s)") + " · " + (l.par ? "par " + nomDe(P(l.par)) : "automatique")
        + (l.restaure_le ? " · annulé " + depuis(l.restaure_le) + (l.restaure_par ? " par " + nomDe(P(l.restaure_par)) : "") : "")),
      l.restaure_le ? tampon("Annulé", "encre") : peutAgir() ? h("div", {}, bouton("Annuler ce nettoyage", { classe: "p discret", icone: "synchro", reseau: true, onclick: () => agir({ action: "casier_restaurer", lot: l.lot }, "Annuler ce nettoyage ?", quantite(l.n, "entrée(s)") + (l.n > 1 ? " reviennent" : " revient") + " au casier.", {}, "Remettre au casier") })) : null))) : null);
}
async function nettoyerCasier() {
  const compteParZone = (etat.d.casier && etat.d.casier.compte) || {};
  let zone = "warns", age = "0";
  const note = h("p", { classe: "bandeau-texte", "aria-live": "polite" });
  const majNote = () => { const n = (compteParZone[zone] || {})[age] || 0; note.textContent = n ? quantite(n, "entrée(s) effacée(s)") + " du casier, et " + (n > 1 ? "leurs" : "ses") + " effets sur Discord. Annulable pendant 30 jours." : "Rien à effacer dans cette zone."; };
  const zoneL = liste({ valeur: zone, label: "Quoi", plein: true, options: [["warns", "Tous les avertissements"], ["auto", "Les détections automatiques"], ["tout", "Tout le casier, sauf les bannissements"]].map(([v, l]) => ({ v, l })), changer: (v) => { zone = v; majNote(); } });
  const ageL = liste({ valeur: age, label: "Âge des entrées", plein: true, options: [["0", "Tout, même récent"], ["30", "Plus vieux que 30 jours"], ["90", "Plus vieux que 90 jours"]].map(([v, l]) => ({ v, l })), changer: (v) => { age = v; majNote(); } });
  majNote();
  const r = await confirmer({ titre: "Nettoyer le casier du serveur", texte: "Pour repartir de zéro, ou nettoyer une zone. Les bannissements restent toujours.", contenu: [zoneL, ageL, h("div", { classe: "bandeau" }, icone("info"), note)],
    mot: "EFFACER", libelleOk: "Effacer", style: "danger" });
  if (r) agir({ action: "casier_serveur", portee: zone, jours: Number(age), confirmation: "EFFACER" }, "", "", { direct: true });
}
function carteCasier(m, entrees, nbr) {
  const p = P(m.id), ouvrir = () => ouvrirFiche(m.id, "sanctions");
  const types = Object.entries(m.types).sort((a, b) => b[1] - a[1]);
  return h("article", { classe: "feuillet lien" + (m.n30 >= 3 ? " alerte" : ""), tabindex: 0, onclick: ouvrir, onkeydown: (e) => { if (e.key === "Enter") ouvrir(); } },
    h("div", { classe: "qui" }, avatar(p), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, nomDe(p)),
      h("div", { classe: "sous-nom" }, (p.pseudo ? "@" + p.pseudo + " · " : "") + "dernière " + depuis(m.derniere))),
      h("div", { classe: "gros-chiffre" }, h("b", { classe: "num" }, String(nbr)), h("span", {}, "sur la période"))),
    h("div", { classe: "pastilles" }, types.slice(0, 4).map(([t, n]) => pastille(n + " × " + libelleType(t), teinteType(t)))),
    h("ul", { classe: "entrees" }, entrees.slice(0, 3).map((x) => h("li", { classe: "entree" + (["kick", "ban"].includes(x.type) ? " grave" : ""), vars: { "--teinte": teinteType(x.type) } },
      h("div", { classe: "haut" }, h("span", { classe: "quoi" }, x.libelle + (x.duree ? " · " + x.duree : "")), h("span", { classe: "quand" }, date(x.date, true))),
      x.raison ? h("div", { classe: "texte coupe2" }, x.raison) : null, h("div", { classe: "meta" }, x.auto ? "Automatique" : "Par " + x.par)))),
    entrees.length > 3 ? h("div", { classe: "compte-pied" }, "+ " + quantite(entrees.length - 3, "autre(s)") + " — tout est dans la fiche") : null);
}
function carteModerateur(x) {
  const ouvrir = () => ouvrirFiche(x.id, "donnees");
  return h("article", { classe: "feuillet lien", tabindex: 0, onclick: ouvrir, onkeydown: (e) => { if (e.key === "Enter") ouvrir(); } },
    h("div", { classe: "qui" }, avatar(P(x.id), "p"), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, sansEmoji(x.nom)), h("div", { classe: "sous-nom" }, quantite(x.total, "sanction(s) décidée(s)")))),
    h("div", { classe: "pastilles" }, Object.entries(x.types).sort((a, b) => b[1] - a[1]).map(([t, n]) => pastille(n + " × " + libelleType(t), teinteType(t)))));
}

// ─── Tickets (partagé avec le clan) ─────────────────────────────────────────
/** portee : "serveur" (tickets normaux d'abord) ou "clan" (Rell Seas seulement). */
export function ticketsVue(vue, portee) {
  const clan = portee === "clan";
  const f = filtres("tickets-" + portee, { q: "", type: clan ? "tous" : "normaux" });
  const haut = h("div", { classe: "pile" }), resultats = h("div", { classe: "pile" }), bas = h("div", { classe: "pile" });
  const pre = "tick-" + portee;
  const changer = () => { resetPages(pre); majResultats(); };
  ajouter(vue, [haut, h("div", { classe: "outils" }, recherche(f.q, "Membre, numéro, motif…", (q) => { f.q = q; changer(); })), resultats, bas]);
  const dansPortee = (t) => (clan ? t.rellseas : true);
  const majHaut = () => {
    const d = etat.d;
    if (!d) { remplacer(haut, indisponible()); return; }
    const tk = d.tickets, n = maintenant();
    const types = tk.types.filter(dansPortee);
    const prises = types.filter((t) => t.prise_mediane).map((t) => t.prise_mediane).sort((a, b) => a - b);
    const ouverts = tk.ouverts.filter(dansPortee);
    remplacer(haut, tuiles(
      tuile({ cle: pre + "1", lib: "Ouverts", val: ouverts.length, icone: "tickets", teinte: "#a8641c" }),
      tuile({ cle: pre + "2", lib: "Pas encore pris", val: ouverts.filter((t) => !t.pris_par).length, icone: "attention", teinte: "#8e2a24" }),
      tuile({ cle: pre + "3", lib: "Prise en charge", texte: duree(prises.length ? prises[Math.floor(prises.length / 2)] : 0), icone: "minuteur", sous: "délai médian", teinte: "#1f4e5a" }),
      tuile({ cle: pre + "4", lib: "Fermés · 30 jours", val: tk.fermes.filter((t) => dansPortee(t) && t.ferme && n - t.ferme <= 30 * JOUR).length, icone: "cadenas", teinte: "#3f6b3a" })));
    remplacer(bas, groupe({ titre: "Tendances", cle: pre + "-tendances", icone: "carte" }, () => h("div", { classe: "duo" },
      h("div", { classe: "cadre" }, h("h3", {}, "Tickets ouverts par mois"), h("p", { classe: "aide" }, "Rell Seas et tickets normaux, douze mois."),
        barres(Object.keys(tk.mois).sort(), tk.mois, [["Rell Seas", ENCRES.mer, "Rell Seas"], ["Tickets normaux", ENCRES.sienne, "Tickets normaux"]], "Les mois apparaîtront avec les premiers tickets.")),
      h("div", { classe: "cadre" }, h("h3", {}, "Staff"), h("p", { classe: "aide" }, "Tickets pris en charge et fermés, depuis le début. Direction et fondateur à part."),
        tk.staff.length ? barresH(tk.staff.map((x) => [sansEmoji(x.nom), x.pris + x.fermes, x.pris + " pris · " + x.fermes + " fermés"])) : vide("Rien à afficher")),
      h("div", { classe: "cadre" }, h("h3", {}, "Délais par type"), h("p", { classe: "aide" }, "Médianes : prise en charge, puis fermeture."),
        h("ul", { classe: "entrees" }, types.map((t) => h("li", { classe: "entree" }, h("div", { classe: "haut" }, h("span", { classe: "quoi" }, t.nom), h("span", { classe: "quand" }, t.total + " au total")),
          h("div", { classe: "meta" }, "prise en charge " + duree(t.prise_mediane) + " · fermeture " + duree(t.fermeture_mediane) + " · " + quantite(t.sans_prise, "fermé(s) sans prise")))))))));
  };
  const majResultats = () => {
    const d = etat.d;
    if (!d) { remplacer(resultats); return; }
    const tk = d.tickets, n = maintenant();
    const types = tk.types.filter(dansPortee);
    const rell = types.filter((t) => t.rellseas), norm_ = types.filter((t) => !t.rellseas);
    const somme = (l) => l.reduce((a, t) => a + t.total, 0);
    const options = clan
      ? [["tous", "Tous", somme(types)], ...(types.length > 1 ? types.map((t) => ["t:" + t.nom, t.nom, t.total, ENCRES.mer]) : [])]
      : [["normaux", "Tickets normaux", somme(norm_), ENCRES.sienne], ["rell", "Rell Seas", somme(rell), ENCRES.mer], ["tous", "Tous", somme(types)],
        ...(norm_.length > 1 ? norm_.map((t) => ["t:" + t.nom, t.nom, t.total, ENCRES.sienne]) : [])];
    if (!options.some((o) => o[0] === f.type)) f.type = options[0][0];
    const garde = (t) => dansPortee(t) && (f.type === "tous" || (f.type === "rell" && t.rellseas) || (f.type === "normaux" && !t.rellseas) || f.type === "t:" + t.type);
    const cherche = (t, p) => contient([p.nom, p.pseudo, p.id, "#" + t.ticket, t.motif, t.type].join(" "), f.q);
    const ouverts = tk.ouverts.filter((t) => garde(t) && cherche(t, t));
    const fermes = tk.fermes.filter((t) => garde(t) && cherche(t, P(t.id)));
    const jours = Number(tk.archives_jours) || 30;
    const recents = fermes.filter((t) => !t.ferme || n - t.ferme <= jours * JOUR), archives = fermes.filter((t) => t.ferme && n - t.ferme > jours * JOUR);
    const groupes = new Map();
    recents.forEach((t) => { if (!groupes.has(t.id)) groupes.set(t.id, []); groupes.get(t.id).push(t); });
    const parMois = new Map();
    archives.forEach((t) => { const k = moisDe(t.ferme); if (!parMois.has(k)) parMois.set(k, []); parMois.get(k).push(t); });
    remplacer(resultats,
      puces(options, f.type, (v) => { f.type = v; changer(); }, "Types de tickets"),
      section("Ouverts", "tickets", compte(ouverts.length, "ticket"), ouverts.length ? paginer(pre + "-o", ouverts, carteTicketOuvert) : vide("Aucun ticket ouvert ici", "Tout est traité.", "succes")),
      section("Fermés ces " + jours + " derniers jours", "cadenas", quantite(groupes.size, "personne(s)") + " · " + compte(recents.length, "ticket"),
        groupes.size ? paginer(pre + "-f", [...groupes.entries()], ([id, l]) => carteTicketsFermes(id, l)) : vide("Aucun ticket fermé ces 30 derniers jours")),
      section("Archives", "coffre", compte(archives.length, "ticket") + " · fermés depuis plus de " + jours + " jours",
        archives.length ? h("div", {}, [...parMois.entries()].map(([k, l]) => groupe({ titre: libelleMois(k), compte: l.length, cle: pre + "-a-" + k },
          () => paginer(pre + "-a-" + k, l, ligneArchive, { classe: "lignes", pas: 30 })))) : vide("Rien aux archives", "Les tickets y sont rangés " + jours + " jours après leur fermeture.")));
  };
  const maj = () => { majHaut(); majResultats(); };
  maj();
  return { maj };
}
export const tickets = (vue) => ticketsVue(vue, "serveur");

export function carteTicketOuvert(t) {
  const tard = !t.pris_par && t.ouvert && maintenant() - t.ouvert > JOUR;
  return h("article", { classe: "feuillet" + (tard ? " chaude" : "") },
    h("div", { classe: "qui" }, avatar(t), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, nomDe(t)), h("div", { classe: "sous-nom" }, "Ticket #" + t.ticket + " · ouvert " + depuis(t.ouvert))),
      pastille(t.type, t.rellseas ? ENCRES.mer : ENCRES.sienne)),
    h("div", { classe: "pastilles" }, t.pris_par ? pastille("Pris par " + sansEmoji(t.pris_par), "#3f6b3a") : pastille(tard ? "Personne depuis plus de 24 h" : "Pas encore pris", "#a8641c")),
    h("div", { classe: "feuillet-pied" },
      t.salon ? h("a", { classe: "bouton p", href: t.salon }, icone("discord"), h("span", {}, "Sur Discord")) : null,
      bouton("Conversation", { classe: "p", icone: "parchemin", onclick: () => ouvrirConversation(t.ticket, "Ticket #" + t.ticket + " · " + nomDe(t)) }),
      bouton("Fiche", { classe: "p discret", icone: "personne", onclick: () => ouvrirFiche(t.id, "tickets") }),
      peutAgir() ? bouton("Fermer", { classe: "p danger", reseau: true, onclick: () => agir({ action: "ticket_fermer", ticket: t.ticket }, "Fermer le ticket #" + t.ticket + " ?", "Le salon du ticket est supprimé ; le transcript est gardé.", { motif: true }, "Fermer", "danger") }) : null));
}
function carteTicketsFermes(id, l) {
  const p = P(id), ouvrir = () => ouvrirFiche(id, "tickets");
  return h("article", { classe: "feuillet" },
    h("div", { classe: "qui" }, avatar(p), h("div", { classe: "bloc" }, h("button", { classe: "lien-nom nom", type: "button", onclick: ouvrir }, nomDe(p)),
      h("div", { classe: "sous-nom" }, quantite(l.length, "ticket(s)") + " · dernier fermé " + depuis(l[0].ferme || l[0].ouvert)))),
    h("ul", { classe: "entrees" }, l.slice(0, 3).map((t) => h("li", { classe: "entree" },
      h("div", { classe: "haut" }, h("span", { classe: "quoi" }, "#" + t.ticket + " · " + t.type), h("span", { classe: "quand" }, date(t.ferme || t.ouvert, true))),
      h("div", { classe: "texte coupe2" }, t.motif || "Sans motif"),
      h("div", { classe: "meta" }, (t.ferme_par ? "fermé par " + sansEmoji(t.ferme_par) + " · " : "") + "durée " + duree(t.ferme && t.ouvert ? t.ferme - t.ouvert : 0)),
      h("div", {}, bouton("Conversation", { classe: "p discret", icone: "parchemin", onclick: () => ouvrirConversation(t.ticket, "Ticket #" + t.ticket + " · " + nomDe(p)) }))))),
    l.length > 3 ? h("div", { classe: "compte-pied" }, "+ " + quantite(l.length - 3, "autre(s)") + " dans la fiche") : null);
}
function ligneArchive(t) {
  const p = P(t.id);
  return h("div", { classe: "ligne" }, avatar(p, "p"),
    h("div", { classe: "bloc" }, h("div", { classe: "nom une-ligne" }, "#" + t.ticket + " · " + nomDe(p)),
      h("div", { classe: "sous-nom" }, t.type + " · fermé le " + date(t.ferme) + (t.motif ? " · " + t.motif : ""))),
    h("div", { classe: "droite" }, tampon("Archivé", "encre", true),
      bouton("Conversation", { classe: "p discret", icone: "parchemin", onclick: () => ouvrirConversation(t.ticket, "Ticket #" + t.ticket + " · " + nomDe(p)) })));
}

// ─── Répertoire ─────────────────────────────────────────────────────────────
function annuaire() {
  const d = etat.d;
  const fiches = new Map();
  const inscrire = (p, extra) => {
    if (!p || !p.id) return;
    const id = String(p.id);
    const f = fiches.get(id) || { id, nom: p.nom || "", pseudo: p.pseudo || "", avatar: p.avatar || "", casier: 0, tickets: 0, questions: 0, journal: 0, clan: false, candidat: "", alerte: false, direction: false, derniere: 0 };
    if (!f.nom && p.nom) f.nom = p.nom;
    if (!f.avatar && p.avatar) f.avatar = p.avatar;
    if (extra) extra(f);
    fiches.set(id, f);
  };
  for (const p of Object.values(d.personnes || {})) inscrire(p);
  for (const m of (d.clan && d.clan.membres) || []) inscrire(m, (f) => { f.clan = true; });
  for (const m of (d.clan && d.clan.direction) || []) inscrire(m, (f) => { f.direction = true; });
  for (const c of d.candidats || []) inscrire(c, (f) => { f.candidat = f.candidat || c.statut; });
  for (const c of d.en_cours || []) inscrire(c, (f) => { f.candidat = "en_cours"; });
  for (const t of d.tickets.ouverts) inscrire(t, (f) => { f.tickets++; f.derniere = Math.max(f.derniere, t.ouvert || 0); });
  for (const t of d.tickets.fermes) inscrire(P(t.id), (f) => { f.tickets++; f.derniere = Math.max(f.derniere, t.ferme || 0); });
  for (const m of d.sanctions.membres) inscrire(P(m.id), (f) => { f.casier = m.total; f.derniere = Math.max(f.derniere, m.derniere || 0); });
  for (const e of (d.journal && d.journal.evenements) || []) if (e.membre) inscrire(P(e.membre), (f) => { f.journal++; f.derniere = Math.max(f.derniere, e.quand || 0); });
  for (const q of (d.questions && d.questions.liste) || []) inscrire(P(q.id), (f) => { f.questions++; });
  for (const a of d.alertes || []) inscrire(P(a.id), (f) => { f.alerte = true; });
  for (const id of d.a_part || []) inscrire(P(id), (f) => { f.direction = true; });
  return [...fiches.values()].filter((f) => f.nom !== "Membre parti" || f.casier || f.tickets);
}
export function repertoire(vue) {
  const f = filtres("repertoire", { q: "", filtre: "tous", lettre: "", tri: "nom" });
  const resultats = h("div", { classe: "pile" });
  const changer = () => { resetPages("rep"); maj(); };
  const champRecherche = recherche(f.q, "Nom, pseudo ou identifiant…", (q) => { f.q = q; f.lettre = ""; changer(); });
  ajouter(vue, [h("div", { classe: "outils" }, champRecherche,
    liste({ valeur: f.tri, label: "Tri", options: [["nom", "Nom A → Z"], ["recent", "Activité récente"], ["casier", "Casier le plus lourd"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.tri = v; changer(); } })), resultats]);
  let cache = null, versionCache = null;
  const maj = () => {
    const d = etat.d;
    if (!d) { remplacer(resultats, indisponible()); return; }
    if (versionCache !== d) { cache = annuaire(); versionCache = d; }
    const FILTRES = [["tous", "Tout le monde", () => true], ["clan", "Clan", (x) => x.clan], ["casier", "Au casier", (x) => x.casier > 0], ["tickets", "Avec tickets", (x) => x.tickets > 0],
      ["candidats", "Candidats", (x) => !!x.candidat], ["alertes", "Alertes", (x) => x.alerte], ["direction", "Direction", (x) => x.direction]];
    const nb = Object.fromEntries(FILTRES.map(([k, , fn]) => [k, cache.filter(fn).length]));
    const fn = (FILTRES.find(([k]) => k === f.filtre) || FILTRES[0])[2];
    const choisis = cache.filter((x) => fn(x) && contient([x.nom, x.pseudo, x.id].join(" "), f.q));
    const lettres = new Map();
    choisis.forEach((x) => { const l = lettre(x.nom || x.pseudo); lettres.set(l, (lettres.get(l) || 0) + 1); });
    if (f.lettre && !lettres.has(f.lettre)) f.lettre = "";
    const affiches = f.lettre ? choisis.filter((x) => lettre(x.nom || x.pseudo) === f.lettre) : choisis;
    const tri = f.tri === "recent" ? (a, b) => b.derniere - a.derniere : f.tri === "casier" ? (a, b) => b.casier - a.casier || b.derniere - a.derniere : (a, b) => nomDe(a).localeCompare(nomDe(b), "fr", { sensitivity: "base" });
    affiches.sort(tri);
    const blocs = [
      puces(FILTRES.map(([k, l]) => [k, l, nb[k]]), f.filtre, (v) => { f.filtre = v; f.lettre = ""; changer(); }, "Filtres"),
      indexAZ(lettres, f.lettre, (l) => { f.lettre = l; changer(); }),
    ];
    const serveur = f.q && f.q.length >= 2 && f.filtre === "tous" ? h("div", { classe: "pile" }) : null;
    if (serveur) chercherServeur(f.q, serveur, new Set(affiches.map((x) => x.id)));
    if (!affiches.length) { remplacer(resultats, ...blocs, vide("Personne ici", "Personne de connu ici : regarde « Dans tout le serveur » ci-dessous."), serveur); return; }
    if (f.tri !== "nom" || f.q || f.lettre) {
      blocs.push(section(f.lettre ? "Lettre " + f.lettre : f.q ? "Résultats" : "Tout le répertoire", "repertoire", compte(affiches.length, "personne"),
        paginer("rep-liste", affiches, lignePersonne, { classe: "lignes", pas: 40 })));
    } else {
      const parLettre = new Map();
      affiches.forEach((x) => { const l = lettre(x.nom || x.pseudo); if (!parLettre.has(l)) parLettre.set(l, []); parLettre.get(l).push(x); });
      const ordre = [...parLettre.keys()].sort((a, b) => (a === "#") - (b === "#") || a.localeCompare(b));
      blocs.push(section("De A à Z", "repertoire", compte(affiches.length, "personne"),
        h("div", {}, ordre.map((l) => groupe({ titre: l, compte: parLettre.get(l).length, cle: "rep-" + l, ouvert: affiches.length <= 60 ? true : undefined },
          () => paginer("rep-l-" + l, parLettre.get(l), lignePersonne, { classe: "lignes", pas: 30 }))))));
    }
    remplacer(resultats, ...blocs, serveur);
  };
  maj();
  return { maj };
}
/** Le reste du serveur (les personnes jamais citées dans les données) : la recherche du serveur, en ligne. */
async function chercherServeur(q, zone, deja) {
  if (!enLigne()) { remplacer(zone, h("p", { classe: "aide" }, "Hors ligne : la recherche dans tout le serveur reviendra avec la connexion.")); return; }
  remplacer(zone, h("p", { classe: "aide" }, "Recherche dans tout le serveur…"));
  const r = await lire("recherche", { q });
  if (!zone.isConnected) return;
  const l = r.ok ? (r.donnees.membres || []).filter((m) => !deja.has(String(m.id))) : [];
  remplacer(zone, l.length ? section("Dans tout le serveur", "rechercher", compte(l.length, "personne"), h("div", { classe: "lignes" }, l.slice(0, 25).map((m) => lignePersonne({
    id: String(m.id), nom: m.nom, pseudo: m.pseudo, avatar: m.avatar, clan: !!m.clan, direction: !!m.a_part, casier: 0, tickets: 0, candidat: "", alerte: false, journal: 0 })))) : null);
}
function lignePersonne(x) {
  const ouvrir = () => ouvrirFiche(x.id);
  const marques = [
    x.direction ? pastille("Direction", "#5e3a4e") : null,
    x.clan ? pastille("Clan", "#3f6b3a") : null,
    x.alerte ? pastille("Alerte", "#8e2a24") : null,
    x.casier ? pastille(x.casier + " au casier", "#a8641c") : null,
    x.tickets ? pastille(quantite(x.tickets, "ticket(s)"), "#7a4b2a") : null,
    x.candidat ? pastille("Candidat · " + (STATUTS_CAND[x.candidat] || [x.candidat])[0], (STATUTS_CAND[x.candidat] || [])[1]) : null,
  ].filter(Boolean);
  return h("div", { classe: "ligne lien", tabindex: 0, role: "button", onclick: ouvrir, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ouvrir(); } } },
    avatar(x, "p"),
    h("div", { classe: "bloc" }, h("div", { classe: "nom une-ligne" }, nomDe(x)), h("div", { classe: "sous-nom une-ligne" }, (x.pseudo ? "@" + x.pseudo + " · " : "") + x.id)),
    h("div", { classe: "droite" }, marques.length ? marques : h("span", { classe: "meta" }, x.journal ? x.journal + " au journal" : "")));
}

// ─── Salons & questions ─────────────────────────────────────────────────────
const SOUS_SALONS = [["questions", "Questions", "salons"], ["idees", "Idées", "etoile"], ["sondages", "Sondages", "drapeau"], ["entraide", "Entraide & trade", "ancre"],
  ["annonces", "Annonces", "cloche"], ["droits", "Droits des salons", "cle"]];
export function salons(vue, ctx) {
  const sous = SOUS_SALONS.some(([k]) => k === ctx.sous) ? ctx.sous : "questions";
  const f = filtres("salons", { q: "", ques: "ouverte", idees: "ouvertes", sond: "en_cours", entr: "ouvertes" });
  const onglets = h("div", { classe: "sous-onglets", role: "tablist", "aria-label": "Salons" });
  const resultats = h("div", { classe: "pile" });
  const outils = h("div", { classe: "outils" }, recherche(f.q, "Question, idée, membre, salon…", (q) => { f.q = q; resetPages("sal"); maj(); }));
  ajouter(vue, [onglets, outils, resultats]);
  const maj = () => {
    const d = etat.d;
    const nb = d ? {
      questions: ((d.questions && d.questions.stats) || {}).ouvertes || 0, idees: ((d.suggestions && d.suggestions.stats) || {}).ouvertes || 0,
      sondages: ((d.sondages && d.sondages.stats) || {}).en_cours || 0, entraide: ((d.entraide && d.entraide.stats) || {}).ouvertes || 0,
      annonces: ((d.annonces && d.annonces.stats) || {}).total || 0, droits: (d.salons || []).length,
    } : {};
    remplacer(onglets, ...SOUS_SALONS.map(([k, l, ic]) => h("a", { classe: "etiquette", role: "tab", href: "#port/salons/" + k, "aria-selected": String(k === sous) },
      icone(ic), l, nb[k] ? h("span", { classe: "compteur" + (k === "questions" && nb[k] ? " chaud" : " calme") }, String(nb[k])) : null)));
    outils.hidden = sous === "droits";
    if (!d) { remplacer(resultats, indisponible()); return; }
    remplacer(resultats, ...[{ questions: sousQuestions, idees: sousIdees, sondages: sousSondages, entraide: sousEntraide, annonces: sousAnnonces, droits: sousDroits }[sous](d, f, maj)].flat());
  };
  maj();
  return { maj };
}
function sousQuestions(d, f, maj) {
  const q = d.questions || {}, l = q.liste || [], st = q.stats || {};
  if (q.erreur) return vide("Questions momentanément illisibles");
  const top = (st.salons || [])[0];
  const nb = { tous: l.length };
  l.forEach((x) => { nb[x.statut] = (nb[x.statut] || 0) + 1; });
  const filtre = l.filter((x) => (f.ques === "tous" || x.statut === f.ques) && contient([x.texte, x.salon, P(x.id).nom, P(x.id).pseudo, x.id].join(" "), f.q));
  const groupes = new Map();
  filtre.forEach((x) => { if (!groupes.has(x.id)) groupes.set(x.id, []); groupes.get(x.id).push(x); });
  return [tuiles(
    tuile({ cle: "q1", lib: "Sans réponse", val: st.ouvertes || 0, icone: "salons", teinte: "#a8641c" }),
    tuile({ cle: "q2", lib: "Répondues · 7 jours", val: st.repondues_7 || 0, icone: "valider", teinte: "#3f6b3a" }),
    tuile({ cle: "q3", lib: "Réponse du staff", texte: duree(st.delai_median), icone: "minuteur", sous: "délai médian", teinte: "#1f4e5a" }),
    tuile({ cle: "q4", lib: "Salon le plus questionné", texte: top ? sansEmoji(top.salon) : "—", icone: "carte", sous: top ? quantite(top.n, "question(s)") + " sur 30 jours" : null, teinte: "#5e3a4e" })),
  h("div", { classe: "rangee entre" }, puces([["ouverte", "Sans réponse", nb.ouverte || 0, "#a8641c"], ["repondue", "Répondues", nb.repondue || 0, "#3f6b3a"], ["resolue", "Résolues", nb.resolue || 0, "#3f6b3a"],
    ["traitee", "Traitées", nb.traitee || 0, "#1f4e5a"], ["ignoree", "Pas des questions", nb.ignoree || 0, "#4a5560"], ["tous", "Toutes", nb.tous]], f.ques, (v) => { f.ques = v; resetPages("sal"); maj(); }, "Statut"),
    exporter("Exporter", [["Questions · 30 jours (CSV)", { quoi: "questions" }], ["Questions · 30 jours (JSON)", { quoi: "questions", format: "json" }]])),
  h("p", { classe: "aide" }, "Relevées toutes seules dans les salons publics. Elles se ferment quand le staff répond ou quand l'auteur dit que c'est bon."),
  filtre.length ? paginer("sal-q", [...groupes.entries()], ([id, x]) => carteQuestions(id, x)) : vide(f.ques === "ouverte" ? "Aucune question en attente" : "Rien ici", f.ques === "ouverte" ? "Tout le monde a eu sa réponse." : "Change le filtre ou la recherche.", "succes")];
}
export function carteQuestions(id, qs) {
  const p = P(id);
  return h("article", { classe: "feuillet" },
    h("div", { classe: "qui" }, avatar(p), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, lienNom(id, ouvrirFiche)), h("div", { classe: "sous-nom" }, quantite(qs.length, "question(s)") + " · dernière " + depuis(qs[0].quand)))),
    h("ul", { classe: "entrees" }, qs.slice(0, 4).map((x) => {
      const [lib, teinte] = STATUTS_Q[x.statut] || [x.libelle, null];
      return h("li", { classe: "entree" },
        h("div", { classe: "haut" }, h("span", { classe: "quoi" }, sansEmoji(x.salon)), h("span", { classe: "quand" }, depuis(x.quand))),
        h("div", { classe: "texte coupe3 deplier", onclick: deplier }, x.texte),
        h("div", { classe: "pastilles" }, pastille(lib, teinte), x.par ? h("span", { classe: "meta" }, "par " + sansEmoji(x.par) + (x.repondu_le && x.repondu_le >= x.quand ? " · en " + duree(x.repondu_le - x.quand) : "")) : null),
        h("div", { classe: "rangee" },
          x.message ? h("a", { classe: "bouton p", href: x.message }, icone("discord"), h("span", {}, x.statut === "ouverte" ? "Répondre sur Discord" : "Voir sur Discord")) : null,
          x.statut === "ouverte" ? [
            bouton("Traitée", { classe: "p vert", icone: "valider", reseau: true, onclick: () => agir({ action: "question", question: x.question, statut: "traitee" }, "", "", { direct: true }) }),
            bouton("Pas une question", { classe: "p discret", reseau: true, onclick: () => agir({ action: "question", question: x.question, statut: "ignoree" }, "", "", { direct: true }) }),
          ] : bouton("Rouvrir", { classe: "p discret", icone: "synchro", reseau: true, onclick: () => agir({ action: "question", question: x.question, statut: "ouverte" }, "", "", { direct: true }) })));
    })),
    qs.length > 4 ? h("div", { classe: "compte-pied" }, "+ " + quantite(qs.length - 4, "autre(s)") + " dans la fiche") : null);
}
function sousIdees(d, f, maj) {
  const idees = d.suggestions || {}, li = idees.liste || [];
  if (idees.erreur) return vide("Idées momentanément illisibles");
  const groupe_ = (x) => (x.retire_le ? "retirees" : x.statut === "attente" || x.statut === "etude" ? "ouvertes" : "decidees");
  const nb = { toutes: li.length };
  li.forEach((x) => { nb[groupe_(x)] = (nb[groupe_(x)] || 0) + 1; });
  const filtre = li.filter((x) => (f.idees === "toutes" || groupe_(x) === f.idees) && contient([x.titre, x.details, x.note, P(x.auteur).nom].join(" "), f.q));
  return [h("p", { classe: "aide" }, "Les idées des membres et leurs votes. Réponds d'ici : la carte change sur Discord et l'auteur reçoit ta réponse en privé."),
    puces([["ouvertes", "À traiter", nb.ouvertes || 0, "#a8641c"], ["decidees", "Décidées", nb.decidees || 0, "#3f6b3a"], ["retirees", "Retirées", nb.retirees || 0, "#4a5560"], ["toutes", "Toutes", nb.toutes]], f.idees, (v) => { f.idees = v; resetPages("sal"); maj(); }, "Statut"),
    filtre.length ? paginer("sal-i", filtre, carteIdee) : vide(f.idees === "ouvertes" ? "Aucune idée à traiter" : "Rien ici", "Change le filtre ou la recherche.")];
}
function carteIdee(x) {
  const p = P(x.auteur), [lib, teinte] = STATUTS_I[x.statut] || [x.libelle, null];
  const total = x.pour + x.contre, pourcent = total ? Math.round(100 * x.pour / total) : 0;
  const ouverte = !x.retire_le && (x.statut === "attente" || x.statut === "etude");
  return h("article", { classe: "feuillet" + (ouverte ? " chaude" : "") },
    h("div", { classe: "qui" }, avatar(p), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, lienNom(x.auteur, ouvrirFiche)), h("div", { classe: "sous-nom" }, "Idée n°" + x.id + " · " + sansEmoji(x.salon) + " · " + depuis(x.cree)))),
    h("h3", { classe: "titre-carte" }, x.titre),
    x.details ? h("p", { classe: "texte coupe3 deplier", onclick: deplier }, x.details) : null,
    h("div", { classe: "votes" }, h("div", { classe: "vote" + (total && pourcent >= 50 ? " tete" : "") },
      h("div", { classe: "vote-haut" }, h("span", {}, total ? pourcent + " % d'accord" : "Pas encore de vote"), h("b", { classe: "num" }, nombre(x.pour) + " pour", h("small", {}, nombre(x.contre) + " contre"))),
      h("span", { classe: "vote-fond" }, h("span", { classe: "vote-plein", vars: { "--pc": pourcent + "%" } })))),
    x.note ? h("div", { classe: "bandeau vert" }, icone("plume"), h("div", { classe: "bandeau-texte" }, h("span", {}, h("b", {}, "Réponse : "), x.note))) : null,
    h("div", { classe: "pastilles" }, pastille(x.retire_le ? "Retirée du salon" : lib, x.retire_le ? "#4a5560" : teinte), x.decide_par ? h("span", { classe: "meta" }, "par " + nomDe(P(x.decide_par)) + (x.decide_le ? " · " + depuis(x.decide_le) : "")) : null),
    !x.retire_le ? h("div", { classe: "feuillet-pied" },
      x.lien ? h("a", { classe: "bouton p", href: x.lien }, icone("discord"), h("span", {}, "Sur Discord")) : null,
      peutAgir() ? bouton("Répondre", { classe: "p vert", icone: "plume", reseau: true, onclick: () => agir({ action: "suggestion_repondre", suggestion: x.id }, "Répondre à l'idée n°" + x.id, x.titre,
        { motif: true, choix: Object.entries(STATUTS_I).map(([k, [l]]) => [k, l]), choixDefaut: x.statut === "attente" ? "etude" : x.statut }, "Envoyer la réponse") }) : null,
      peutAgir() ? bouton("Retirer", { classe: "p danger", reseau: true, onclick: () => agir({ action: "suggestion_retirer", suggestion: x.id }, "Retirer cette idée du salon ?", "Sa carte disparaît de Discord ; elle reste ici.", {}, "Retirer du salon", "danger") }) : null) : null);
}
function sousSondages(d, f, maj) {
  const s = d.sondages || {}, l = s.liste || [], st = s.stats || {};
  if (s.erreur) return vide("Sondages momentanément illisibles");
  const nb = { tous: l.length };
  l.forEach((x) => { nb[x.statut] = (nb[x.statut] || 0) + 1; });
  const filtre = l.filter((x) => (f.sond === "tous" || x.statut === f.sond) && contient([x.question, (x.choix || []).join(" "), x.salon, P(x.auteur).nom].join(" "), f.q));
  return [tuiles(tuile({ cle: "s1", lib: "Sondages en cours", val: st.en_cours || 0, icone: "drapeau", teinte: "#3f6b3a" }),
    tuile({ cle: "s2", lib: "Votes · 30 jours", val: st.votes_mois || 0, icone: "valider", teinte: "#1f4e5a" })),
  h("p", { classe: "aide" }, "Créés par les membres sur Discord ; les votes suivent en direct. Un sondage retiré quitte le salon, son résultat reste ici."),
  puces([["en_cours", "En cours", nb.en_cours || 0, "#3f6b3a"], ["termine", "Terminés", nb.termine || 0, "#1f4e5a"], ["retire", "Retirés", nb.retire || 0, "#4a5560"], ["tous", "Tous", nb.tous]], f.sond, (v) => { f.sond = v; resetPages("sal"); maj(); }, "Statut"),
  filtre.length ? paginer("sal-s", filtre, carteSondage) : vide(f.sond === "en_cours" ? "Aucun sondage en cours" : "Rien ici", "Change le filtre ou la recherche.")];
}
function carteSondage(x) {
  const p = P(x.auteur), [lib, teinte] = STATUTS_S[x.statut] || [x.statut, null];
  const quand = x.statut === "en_cours" ? "fin le " + date(x.fin, true) : x.statut === "retire" ? "retiré " + depuis(x.retire_le) + (x.retire_par ? " par " + nomDe(P(x.retire_par)) : "") : "terminé le " + date(x.fin, true);
  return h("article", { classe: "feuillet" },
    h("div", { classe: "qui" }, avatar(p), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, lienNom(x.auteur, ouvrirFiche)), h("div", { classe: "sous-nom" }, sansEmoji(x.salon) + " · " + depuis(x.cree)))),
    h("h3", { classe: "titre-carte" }, x.question), sondageVotes(x),
    h("div", { classe: "pastilles" }, pastille(lib, teinte), h("span", { classe: "meta" }, quantite(x.total, "vote(s)") + (x.multiple ? " · plusieurs choix" : "") + " · " + quand)),
    x.statut !== "retire" ? h("div", { classe: "feuillet-pied" },
      x.lien ? h("a", { classe: "bouton p", href: x.lien }, icone("discord"), h("span", {}, "Sur Discord")) : null,
      peutAgir() ? bouton("Retirer du salon", { classe: "p danger", reseau: true, onclick: () => agir({ action: "sondage_retirer", sondage: x.id }, "Retirer ce sondage du salon ?", "Le message disparaît de Discord ; son résultat reste ici.", {}, "Retirer du salon", "danger") }) : null) : null);
}
const STATUTS_E = { ouverte: ["Ouverte", "#3f6b3a"], prise: ["En cours", "#a8641c"], terminee: ["Terminée", "#1f4e5a"], fermee: ["Fermée", "#4a5560"], expiree: ["Fermée sans activité", "#4a5560"], retiree: ["Retirée", "#4a5560"] };
function sousEntraide(d, f, maj) {
  const en = d.entraide || {}, le = en.liste || [];
  if (en.erreur) return vide("Entraide momentanément illisible");
  const ouverte = (x) => x.statut === "ouverte" || x.statut === "prise";
  const filtre = le.filter((x) => (f.entr === "toutes" || (f.entr === "ouvertes" ? ouverte(x) : x.zone === f.entr)) && contient([x.titre, x.type, (x.champs || []).map((c) => c[1]).join(" "), P(x.auteur).nom].join(" "), f.q));
  return [h("p", { classe: "aide" }, "Chaque demande d'aide et de trade : qui l'a faite, qui est venu, qui l'a certifiée, avec qui l'échange s'est fait. Close, elle disparaît de Discord ; elle reste ici."),
    puces([["ouvertes", "En cours", le.filter(ouverte).length, "#3f6b3a"], ["trade", "Trade", le.filter((x) => x.zone === "trade").length, "#a8641c"], ["toutes", "Toutes", le.length]], f.entr, (v) => { f.entr = v; resetPages("sal"); maj(); }, "Statut"),
    filtre.length ? paginer("sal-e", filtre, carteDemande) : vide(f.entr === "ouvertes" ? "Aucune demande en cours" : "Rien ici", "Change le filtre ou la recherche.")];
}
function carteDemande(x) {
  const p = P(x.auteur), [lib, teinte] = STATUTS_E[x.statut] || [x.libelle, null];
  const fin = x.certifie_par ? "certifiée par " + nomDe(P(x.certifie_par)) : x.ferme_par ? "close par " + nomDe(P(x.ferme_par)) : "";
  return h("article", { classe: "feuillet" + (x.statut === "ouverte" || x.statut === "prise" ? " chaude" : "") },
    h("div", { classe: "qui" }, avatar(p), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, lienNom(x.auteur, ouvrirFiche)), h("div", { classe: "sous-nom" }, sansEmoji(x.type) + " · n°" + x.id + " · " + depuis(x.cree)))),
    h("h3", { classe: "titre-carte" }, x.titre),
    (x.champs || []).length ? h("dl", { classe: "champs-lus" }, x.champs.map(([l, v]) => h("div", {}, h("dt", {}, l), h("dd", {}, v)))) : null,
    (x.aidants || []).length ? h("div", { classe: "meta" }, (x.zone === "trade" ? "Intéressés : " : "Venus aider : ") + x.aidants.map((a) => nomDe(P(a))).join(", ")) : null,
    x.partenaire ? h("div", { classe: "meta" }, "Échange avec " + nomDe(P(x.partenaire))) : null,
    h("div", { classe: "pastilles" }, pastille(lib, teinte), fin ? h("span", { classe: "meta" }, fin + (x.ferme ? " · " + depuis(x.ferme) : "")) : null),
    x.lien || x.transcript ? h("div", { classe: "feuillet-pied" },
      x.lien ? h("a", { classe: "bouton p", href: x.lien }, icone("discord"), h("span", {}, "Sur Discord")) : null,
      x.transcript ? h("a", { classe: "bouton p discret", href: x.transcript }, icone("parchemin"), h("span", {}, "Historique")) : null) : null);
}
function sousAnnonces(d, f) {
  const an = d.annonces || {}, la = an.liste || [];
  if (an.erreur) return vide("Annonces momentanément illisibles");
  const filtre = la.filter((x) => contient([x.titre, x.texte, x.salon].join(" "), f.q));
  return [h("p", { classe: "aide" }, "Les annonces publiées depuis le salon « logs », et combien de membres les ont vues. Pour composer une annonce du clan : L'Équipage, Annonces & événements."),
    filtre.length ? paginer("sal-a", filtre, (x) => h("article", { classe: "feuillet" },
      h("div", { classe: "qui" }, avatar(P(x.auteur)), h("div", { classe: "bloc" }, h("h3", { classe: "titre-carte" }, x.titre),
        h("div", { classe: "sous-nom" }, sansEmoji(x.salon) + " · " + depuis(x.cree) + " · par " + nomDe(P(x.auteur))))),
      h("p", { classe: "texte coupe3 deplier", onclick: deplier }, x.texte),
      h("div", { classe: "pastilles" }, pastille("Vue par " + nombre(x.vues), "#3f6b3a", (x.vus || []).length ? x.vus.map((v) => nomDe(P(v))).join(", ") : null),
        x.mention ? h("span", { classe: "meta" }, "mention " + x.mention.replace(/^@/, "")) : null),
      x.lien ? h("div", { classe: "feuillet-pied" }, h("a", { classe: "bouton p", href: x.lien }, icone("discord"), h("span", {}, "Sur Discord"))) : null)) : vide("Aucune annonce")];
}
const PROFILS = { ouvert: ["Ouvert à tous", "#3f6b3a"], lecture: ["Lecture seule", "#1f4e5a"], vitrine: ["Visible, fermé", "#5e3a4e"], clan: ["Clan seulement", "#7a4b2a"], cache: ["Réservé", "#4a5560"] };
function sousDroits(d) {
  const cats = d.salons || [];
  if (!Array.isArray(cats) || !cats.length) return vide("Aucun salon lisible");
  return [h("p", { classe: "aide" }, "Lecture seule : rien ne se règle d'ici. Ouvert à tous : on écrit. Lecture seule : on lit sans écrire. Visible, fermé : on voit le vocal sans y entrer. Clan seulement : réservé au rôle du clan. Réservé : caché à tout le monde."),
    h("div", { classe: "grille" }, cats.map((cat) => h("article", { classe: "feuillet" }, h("h3", { classe: "titre-carte" }, sansEmoji(cat.categorie) || "Sans catégorie"),
      h("div", { classe: "salons-liste" }, cat.salons.map((sl) => {
        const [lib, teinte] = PROFILS[sl.profil] || [sl.profil, null];
        const peut = sl.vocal ? [sl.rejoindre ? "rejoindre" : null] : [sl.ecrire ? "écrire" : null, sl.images ? "images" : null, sl.reagir ? "réagir" : null];
        return h("div", { classe: "salon-ligne" }, h("span", { classe: "nom-salon" }, icone(sl.vocal ? "cloche" : "salons", "ic-p"), h("span", { classe: "une-ligne" }, sansEmoji(sl.nom) || "salon")),
          pastille(lib, teinte, peut.filter(Boolean).join(", ") || "rien d'autre que voir"));
      })))))];
}

// ─── Nettoyage ──────────────────────────────────────────────────────────────
export function nettoyage(vue) {
  const zone = h("div", { classe: "pile" }, squelettes(3));
  ajouter(vue, [zone]);
  const maj = async (forcer) => {
    const n = await charger("nettoyage", { forcer });
    if (!n || n.erreur) { remplacer(zone, n && n.erreur ? vide("Nettoyage indisponible", n.erreur, "hors_ligne") : squelettes(3)); return; }
    const compteurs = n.compteurs || {};
    const total = Object.values(compteurs).reduce((a, b) => a + (Number(b) || 0), 0);
    const bilan = n.bilan && typeof n.bilan === "object" ? n.bilan : null;
    remplacer(zone,
      tuiles(tuile({ cle: "n1", lib: "Dernier nettoyage", texte: n.dernier ? depuis(n.dernier) : "jamais", icone: "nettoyage",
        sous: n.dernier ? date(n.dernier, true) + (n.par ? " · " + (/^\d{5,22}$/.test(String(n.par)) ? nomDe(P(n.par)) : sansEmoji(n.par)) : " · automatique") : "", teinte: "#3f6b3a" }),
        tuile({ cle: "n2", lib: "À nettoyer maintenant", val: total, icone: "coffre", sous: "selon les règles ci-dessous", teinte: "#a8641c" }),
        bilan && bilan.total !== undefined ? tuile({ cle: "n3", lib: "Dernier bilan", val: bilan.total, icone: "journal", sous: accord(bilan.total, "élément(s) nettoyé(s)"), teinte: "#4a5560" }) : null),
      h("div", { classe: "cadre pile serree" }, h("h3", {}, "Le grand ménage"),
        h("p", { classe: "aide" }, "Il passe tout seul chaque jour. Tu peux aussi le lancer maintenant : il applique les règles ci-dessous et note son bilan."),
        h("div", { classe: "rangee" }, bouton("Lancer le nettoyage maintenant", { classe: "principal", icone: "nettoyage", reseau: true, onclick: async () => {
          const ok = await confirmer({ titre: "Lancer le nettoyage maintenant ?", texte: total ? quantite(total, "élément(s)") + (total > 1 ? " seront nettoyés" : " sera nettoyé") + " selon les règles." : "Rien n'est à nettoyer pour l'instant, le bilan le notera.", libelleOk: "Nettoyer", style: "principal" });
          if (!ok) return;
          const r = await poster("nettoyage/lancer", {});
          toast(r.ok ? (r.donnees.message || "Nettoyage fait.") : r.status === 429 ? "Un nettoyage vient d'être fait : attends quelques minutes avant le suivant." : r.erreur, r.ok ? "succes" : "erreur");
          if (r.ok) maj(true);
        } }), h("a", { classe: "bouton discret", href: "#port/sanctions" }, icone("sanctions"), h("span", {}, "Nettoyer le casier (Sanctions)")))),
      section("Les règles", "parchemin", compte((n.regles || []).length, "règle"), h("div", { classe: "grille" }, (n.regles || []).map((r) => carteRegle(r, compteurs[r.cle], () => maj(true))))),
      (n.bilans || []).length ? groupe({ titre: "Les derniers bilans", compte: n.bilans.length, cle: "net-bilans", icone: "journal" }, () => h("ul", { classe: "entrees feuillet" }, n.bilans.map((b) => h("li", { classe: "entree" },
        h("div", { classe: "haut" }, h("span", { classe: "quoi" }, quantite(b.total, "élément(s) nettoyé(s)")), h("span", { classe: "quand" }, date(b.quand, true))), b.detail ? h("div", { classe: "meta" }, b.detail) : null)))) : null);
  };
  maj();
  return { maj: () => maj(false) };
}
function carteRegle(r, enAttente, recharger) {
  if (r.reglable === false) {
    return h("article", { classe: "feuillet regle" }, h("h3", { classe: "titre-carte" }, r.nom), h("p", { classe: "aide" }, r.quoi),
      h("div", { classe: "regle-ligne" }, h("span", { classe: "champ-lib" }, "Garder"), h("b", { classe: "num regle-valeur" }, (r.garde_jours || 0) + " j")),
      h("p", { classe: "meta" }, "Règle fixe" + (r.auto ? " · appliquée chaque jour" : "") + " · " + (enAttente ? nombre(enAttente) + " à nettoyer" : "rien à nettoyer")));
  }
  let jours = Number(r.garde_jours) || r.min || 1;
  const valeur = h("b", { classe: "num regle-valeur" }, jours + " j");
  const reg = h("input", { classe: "reglette", type: "range", min: r.min || 1, max: r.max || 365, step: 1, value: jours, "aria-label": "Garder pendant (jours)" });
  const enregistrer = bouton("Enregistrer", { classe: "p", icone: "valider", disabled: true });
  const etatBouton = () => { enregistrer.disabled = jours === Number(r.garde_jours) || !enLigne(); enregistrer.title = enLigne() ? "" : "Hors ligne : à enregistrer au retour de la connexion."; };
  reg.addEventListener("input", () => { jours = Number(reg.value); valeur.textContent = jours + " j"; etatBouton(); });
  ecouter("reseau", etatBouton);
  enregistrer.addEventListener("click", async () => {
    const rep = await poster("nettoyage/regle", { cle: r.cle, garde_jours: jours });
    toast(rep.ok ? "Règle enregistrée : " + r.nom + ", " + jours + " jours." : rep.erreur, rep.ok ? "succes" : "erreur");
    if (rep.ok) recharger();
  });
  return h("article", { classe: "feuillet regle" },
    h("h3", { classe: "titre-carte" }, r.nom), h("p", { classe: "aide" }, r.quoi),
    h("div", { classe: "regle-ligne" }, h("span", { classe: "champ-lib" }, "Garder"), valeur),
    reg, h("div", { classe: "regle-bornes" }, h("span", {}, (r.min || 1) + " j"), h("span", {}, (r.max || 365) + " j")),
    r.defaut && Number(r.defaut) !== Number(r.garde_jours) ? h("p", { classe: "meta" }, "Par défaut : " + r.defaut + " j ",
      h("button", { classe: "lien-nom", type: "button", onclick: () => { reg.value = r.defaut; reg.dispatchEvent(new Event("input")); } }, "remettre")) : null,
    h("div", { classe: "rangee entre" }, h("span", { classe: "meta" }, (enAttente ? nombre(enAttente) + " à nettoyer" : "Rien à nettoyer") + (r.auto === false ? " · seulement à la main" : "")), enregistrer));
}
