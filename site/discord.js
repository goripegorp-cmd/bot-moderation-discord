// discord.js — « Le Port » : journal, sanctions, tickets (ceux du clan compris), répertoire, salons & questions ; et le
// nettoyage, montré dans La Capitainerie › Réglages (reglages.js). 27/10/2026 : l'Aperçu est dans l'accueil (accueil.js).

import { h, icone, date, heure, depuis, duree, nombre, cleJour, libelleMois, moisDe, maintenant, sansEmoji, norm, contient, lettre, trier, compte, remplacer, quantite, accord, ajouter } from "./dom.js";
import { etat, P, peutAgir, aller, filtres, enLigne, ecouter, retenirPersonnes, nommerOnglets } from "./noyau.js";
import { lienExport, lire, poster } from "./api.js";
import { charger, vue as vueJeu } from "./donnees.js";
import {
  bouton, avatar, pastille, tampon, vide, tuile, tuiles, puces, segment, recherche, liste, menu, groupe, indexAZ,
  section, sectionTete, barres, barresH, ENCRES, lienNom, nomDe, confirmer, toast, bandeau, caseACocher, compteur, squelettes, boutonCopie,
} from "./ui.js";
import {
  ouvrirFiche, ouvrirConversation, agir, teinteCat, teinteType, libelleType, GROUPES_SANCTION, STATUTS_Q, STATUTS_S,
  STATUTS_I, STATUTS_CAND, deplier, sondageVotes, nomSalon, recentsDabord, propre,
  ligneJournal,
} from "./fiche.js";
import { ligne, lignes, groupes, outilsGroupes, groupesParPeriode, groupesParJours, pastilleIcone, quandLigne, badgeRestreint, estRestreint, avance } from "./rangement.js";
import { avecVerrou, protegerZone } from "./direct.js";
import {
  journalSuite, comptesParCategorie, chiffresJournal, comptesMois, moisArchive, fermesDepuis, fermesRecherche, reunirFermes,
  casierMembres, casierPlus, casierRecherche, texteApercu, apercuReglette, boutonNettoyerRegle, cadreStockage, FAMILLES, familleDe as familleRegle,
} from "./longevite.js";

const JOUR = 86400;
const resetPages = (prefixe) => { for (const k of Object.keys(etat.pages)) if (k.startsWith(prefixe)) delete etat.pages[k]; };
export const indisponible = () => vide("Données indisponibles", etat.reseau.enLigne ? "Le serveur ne répond pas pour le moment : nouvel essai automatique." : "Hors ligne, et rien n'est encore en mémoire sur cet appareil.", "hors_ligne");
const exporter = (libelle, items) => menu(bouton(libelle || "Exporter", { icone: "exporter", reseau: true }), items.map(([l, p]) => ({ l, icone: "exporter", href: lienExport(p), telecharger: true })));

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
    avance(exporter("Exporter", [["Journal · 7 jours (CSV)", { quoi: "journal", jours: 7 }], ["Journal · 30 jours (CSV)", { quoi: "journal", jours: 30 }], ["Journal · 90 jours (CSV)", { quoi: "journal", jours: 90 }],
      ["Journal · 30 jours (JSON)", { quoi: "journal", jours: 30, format: "json" }], ...(peutAgir() ? [["Erreurs du bot · 30 jours (CSV)", { quoi: "erreurs" }]] : [])])));
  const tete = h("div");
  ajouter(vue, [tete, outils, h("p", { classe: "aide avance" }, "Plus aucun log sur Discord : tout arrive ici. Conservation : messages et vocal 30 jours, le reste 90 jours (Réglages, Nettoyage). Au-delà des derniers évènements, le serveur cherche pour toi ; l'export prend tout."), resultats]);
  // Au-delà des 400 derniers évènements des données, le serveur filtre (période, catégorie, gravité, recherche) : à
  // plusieurs années, un jour en compte des milliers (longevite.js).
  const suite = journalSuite(() => maj());
  const maj = () => {
    const d = etat.d;
    if (!d) { remplacer(resultats, indisponible()); return; }
    const j = d.journal || {}, base = recentsDabord(j.evenements, "quand"), n = maintenant();
    if (j.erreur) { remplacer(resultats, vide("Journal momentanément illisible", "Nouvel essai à la prochaine mise à jour.", "attention")); return; }
    const c = chiffresJournal(j.par_jour, base, n, () => maj());
    remplacer(tete, tuiles(
      tuile({ cle: "j1", lib: "Aujourd'hui", val: c.aujourdhui, icone: "journal", sous: "évènements consignés", teinte: "#1f4e5a" }),
      tuile({ cle: "j2", lib: "Graves · 7 jours", val: c.graves, icone: "attention", sous: "sanctions lourdes, détections", teinte: "#8e2a24" }),
      tuile({ cle: "j3", lib: "Personnes · 7 jours", val: c.personnes, icone: "membres", sous: "concernées par un évènement", teinte: "#3f6b3a" })));
    const limite = f.periode === "tout" ? 0 : n - Number(f.periode) * JOUR;
    const v = suite.vue(f, base, limite), evts = v.evts;
    const dansPeriode = evts.filter((e) => e.quand >= limite && (e.gravite || 0) >= Number(f.gravite));
    const nb = {};
    dansPeriode.forEach((e) => { nb[e.cat] = (nb[e.cat] || 0) + 1; });
    // Les comptes exacts : ceux du serveur pour ce filtre, sinon le comptage jour par jour des données.
    const exacts = !v.serveur ? null : v.parCategorie || (f.gravite === "0" && !f.q ? comptesParCategorie(j.par_jour, f.periode, n) : null);
    if (exacts) Object.assign(nb, exacts);
    if (f.cat !== "tous" && !nb[f.cat]) f.cat = "tous";
    const texte = (e) => [e.texte, e.detail, e.salon, e.cat, ...[e.membre, e.auteur].filter(Boolean).flatMap((id) => [id, P(id).nom, P(id).pseudo])].join(" ");
    const liste_ = v.serveur ? dansPeriode : dansPeriode.filter((e) => (f.cat === "tous" || e.cat === f.cat) && contient(texte(e), f.q));
    const tous = exacts ? Object.values(exacts).reduce((a, k) => a + k, 0) : v.serveur && f.cat === "tous" ? v.total : dansPeriode.length;
    const blocs = [puces([["tous", "Tout", tous], ...Object.keys(nb).sort((a, b) => nb[b] - nb[a]).map((c_) => [c_, c_, nb[c_], teinteCat(c_)])], f.cat, (val) => { f.cat = val; changer(); }, "Catégories")];
    if (v.serveur && !evts.length && (v.charge || v.erreur)) { remplacer(resultats, ...blocs, v.erreur ? vide("Journal momentanément illisible", v.erreur, "hors_ligne") : squelettes(4)); return; }
    if (!liste_.length) { remplacer(resultats, ...blocs, vide("Rien ici", "Change la période, la catégorie ou la recherche.")); return; }
    // L'important d'abord : les faits graves de la période, en tête (une ligne chacun, 8 puis « Voir plus »).
    const graves = liste_.filter((e) => e.gravite >= 2);
    if (graves.length && f.gravite !== "2") {
      blocs.push(section("L'important d'abord", "attention", compte(graves.length, "fait grave", "faits graves"),
        lignes("jour-graves", graves, (e) => ligneJournal(e, null, true), { pas: 8 })));
    }
    if (f.vue === "personnes") {
      const parQui = new Map();
      liste_.forEach((e) => { const k = e.membre || "serveur"; if (!parQui.has(k)) parQui.set(k, []); parQui.get(k).push(e); });
      blocs.push(section("Par personne", "membres", quantite(parQui.size, "personne(s)") + " · " + quantite(liste_.length, "évènement(s)"),
        lignes("jour-p", [...parQui.entries()], ([id, l]) => lignePersonneJournal(id, l))));
    } else if (v.serveur && v.parJour) {
      // Le serveur filtre : chaque groupe (jour, semaine, mois) a son compte exact et se charge quand on l'ouvre.
      const zone = h("div", { classe: "groupes-zone" }, groupes(suite.groupes(liste_, (l, k) => lignes("jour-s-" + k, l, (e) => ligneJournal(e, null))), { ouverts: 1 }));
      blocs.push(section("Jour par jour", "calendrier", compte(v.total, "évènement"), zone, outilsGroupes(zone)));
    } else {
      // Un groupe par jour (aujourd'hui, hier, vendredi 23…), puis par semaine et par mois : le plus récent ouvert, les
      // autres fermés avec leur compte ; une ligne par évènement, « Voir plus » par 20.
      const graves_ = (l) => l.filter((e) => e.gravite >= 2).length;
      const zone = h("div", { classe: "groupes-zone" }, groupesParJours("jour", liste_, (e) => e.quand, (e) => ligneJournal(e, null),
        { forcer: !!f.q || f.cat !== "tous", chaud: (l) => graves_(l) > 0, info: (l) => (graves_(l) ? compte(graves_(l), "grave", "graves") : "") }));
      blocs.push(section("Jour par jour", "calendrier", v.serveur && v.total > liste_.length ? nombre(liste_.length) + " sur " + compte(v.total, "évènement") : compte(liste_.length, "évènement"), zone, outilsGroupes(zone)));
    }
    if (v.plus && f.vue === "personnes") blocs.push(h("div", { classe: "rangee" }, v.plus));
    remplacer(resultats, ...blocs);
  };
  maj();
  return { maj };
}
/** Une personne au journal : combien, de quoi, le dernier évènement ; sa fiche au clic. */
function lignePersonneJournal(id, evts) {
  const serveur = id === "serveur", p = serveur ? { nom: "Serveur", pseudo: "", avatar: "" } : P(id);
  const cats = {};
  evts.forEach((e) => { cats[e.cat] = (cats[e.cat] || 0) + 1; });
  const graves = evts.filter((e) => e.gravite >= 2).length;
  return ligne({
    visuel: avatar(p, "p"), titre: nomDe(p), sous: quantite(evts.length, "évènement(s)") + " · dernier : " + (evts[0].texte || evts[0].cat),
    badges: [graves ? pastille(compte(graves, "grave", "graves"), "#8e2a24") : null, serveur ? null : badgeRestreint(id),
      ...Object.entries(cats).sort((a, b) => b[1] - a[1]).map(([c, k]) => pastille(k + " · " + c, teinteCat(c)))],
    maxBadges: 3, ...quandLigne(evts[0].quand), etat: graves ? "alerte" : null,
    ouvrir: serveur ? undefined : () => ouvrirFiche(id, "journal"), libelleOuvrir: serveur ? null : "Ouvrir la fiche de " + nomDe(p),
  });
}

// ─── Sanctions ──────────────────────────────────────────────────────────────
export function sanctions(vue) {
  const f = filtres("sanctions", { q: "", periode: "90", groupe: "tous", origine: "tous", tri: "recent" });
  const haut = h("div", { classe: "pile" }), resultats = h("div", { classe: "pile" }), bas = h("div", { classe: "pile" });
  const changer = () => { resetPages("mod"); majResultats(); };
  const outils = h("div", { classe: "outils" },
    recherche(f.q, "Membre, identifiant, motif, modérateur…", (q) => { f.q = q; changer(); }),
    liste({ valeur: f.periode, label: "Période", options: [["7", "7 jours"], ["30", "30 jours"], ["90", "90 jours"], ["365", "12 mois"], ["tout", "Tout le casier"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.periode = v; changer(); } }),
    avance(liste({ valeur: f.origine, label: "Origine", options: [["tous", "Staff et automatique"], ["staff", "Décidées par le staff"], ["auto", "Automatiques"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.origine = v; changer(); } })),
    avance(liste({ valeur: f.tri, label: "Tri", options: [["recent", "Plus récents"], ["nombre", "Plus sanctionnés"], ["nom", "Nom A → Z"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.tri = v; changer(); } })),
    avance(exporter("Exporter", [["Casier complet (CSV)", { quoi: "sanctions" }], ["Casier complet (JSON)", { quoi: "sanctions", format: "json" }]])));
  ajouter(vue, [haut, outils, resultats, bas]);
  const majHaut = () => {
    const s = etat.d && etat.d.sanctions;
    if (!s) { remplacer(haut, indisponible()); remplacer(bas); return; }
    const somme = (cles) => s.types.filter((t) => cles.includes(t.type)).reduce((a, t) => a + t.n, 0);
    const actives = s.actives.mutes.length + s.actives.radies.length + s.actives.restreints.length;
    const enCeMoment = actives ? h("div", { classe: "cadre pile serree" }, h("h3", {}, "En ce moment"),
      groupeActif("Mutés", s.actives.mutes, (m) => (m.jusqu ? "jusqu'à " + heure(m.jusqu) : "")),
      groupeActif("Radiés", s.actives.radies, () => ""),
      groupeActif("Restreints par la direction", s.actives.restreints, (m) => (m.par ? "par " + propre(m.par) : ""))) : null;
    remplacer(haut, tuiles(
      tuile({ cle: "m1", lib: "30 derniers jours", val: s.trente_jours, icone: "calendrier", sous: "tout le casier", teinte: "#1f4e5a" }),
      tuile({ cle: "m2", lib: "Avertissements", val: somme(["warn"]), icone: "plume", sous: "depuis le début", teinte: "#a8641c" }),
      tuile({ cle: "m3", lib: "Mutes", val: somme(["mute"]), icone: "cadenas", sous: "depuis le début", teinte: "#5e3a4e" }),
      tuile({ cle: "m4", lib: "Expulsions et bans", val: somme(["kick", "ban"]), icone: "sabre", sous: "depuis le début", teinte: "#8e2a24" }),
      tuile({ cle: "m5", lib: "Par le staff", val: s.manuel, icone: "personne", sous: quantite(s.auto, "automatique(s)"), teinte: "#4a5560" }),
      tuile({ cle: "m6", lib: "En ce moment", val: actives, icone: "minuteur", sous: "mutés, radiés, restreints", teinte: "#7a4b2a" })), enCeMoment, cadreNettoyageCasier());
    remplacer(bas,
      groupe({ titre: "Modérateurs", compte: s.staff.length, cle: "mod-staff", icone: "personne" }, () => [h("p", { classe: "aide" }, "Sanctions décidées à la main, par personne. Direction et fondateur à part."),
        s.staff.length ? lignes("mod-staff", s.staff, ligneModerateur) : vide("Aucune sanction décidée à la main")]),
      groupe({ titre: "Tendances", cle: "mod-tendances", icone: "carte", classe: "avance" }, () => h("div", { classe: "duo" },
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
    // Les 250 personnes des données, puis celles chargées d'un bouton ; une recherche cherche dans tout le casier (longevite.js).
    const membres = casierMembres(), connus = new Set(membres.map((m) => m.id));
    for (const m of (f.q && casierRecherche(f.q, () => majResultats())) || []) if (!connus.has(m.id)) { connus.add(m.id); membres.push(m); }
    for (const m of membres) {
      const p = P(m.id);
      if (f.q && !contient([p.nom, p.pseudo, m.id, ...m.liste.map((x) => x.raison + " " + x.par)].join(" "), f.q)) continue;
      const dansPeriode = recentsDabord(m.liste, "date").filter(garde);
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
    // Une ligne par personne. Triées par date : rangées par période de leur dernière sanction (la plus récente ouverte).
    const zone = h("div", { classe: "groupes-zone" });
    const rendreUn = ([m, e, c]) => ligneCasier(m, e, c);
    if (!cartes.length) ajouter(zone, [vide("Personne au casier ici", "Change la période, le type ou la recherche.")]);
    else if (f.tri !== "recent") ajouter(zone, [lignes("mod-liste", cartes, rendreUn)]);
    else ajouter(zone, groupesParPeriode("mod", cartes, ([, e]) => (e[0] && e[0].date) || 0, rendreUn, { forcer: !!f.q, chaud: (l) => l.some(([m]) => m.n30 >= 3) }));
    remplacer(resultats,
      puces([["tous", "Tous", nbGroupe.tous], ...Object.entries(GROUPES_SANCTION).map(([g, c]) => [g, g, nbGroupe[g], c])], f.groupe, (v) => { f.groupe = v; changer(); }, "Types"),
      section("Le casier, par membre", "repertoire", compte(cartes.length, "personne"),
        h("div", { classe: "pile" }, h("p", { classe: "aide" }, "Une ligne par personne : ce qu'elle a reçu sur la période, rangé par date de sa dernière sanction. Touche une ligne pour toute sa fiche."), zone,
          casierPlus(() => majResultats())),
        cartes.length && f.tri === "recent" ? outilsGroupes(zone) : null));
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
// Les nettoyages des 30 derniers jours, rangés par sorte (un groupe chacune, celle du plus récent ouverte) ; les casiers
// des membres partis regroupés à part (« 12 casiers de membres partis »), les nettoyages annulés à la fin.
const SORTES_LOTS = [["zones", "Nettoyages du serveur", "nettoyage"], ["avertissements", "Avertissements d'un membre", "plume"],
  ["casiers", "Casiers entiers d'un membre", "sanctions"], ["amnisties", "Amnisties automatiques", "minuteur"], ["annules", "Nettoyages annulés", "restaurer"]];
const sorteLot = (l) => (l.restaure_le ? "annules" : /^amnistie/i.test(String(l.lot || "")) || /^Amnistie/i.test(String(l.quoi || "")) ? "amnisties"
  : l.membre ? (/^Casier entier/i.test(String(l.quoi || "")) ? "casiers" : "avertissements") : "zones");
/** Parti du serveur : le serveur ne le connaît plus (« Membre parti »). */
const estParti = (id) => { const p = (etat.d && etat.d.personnes && etat.d.personnes[String(id)]) || null; return !p || p.nom === "Membre parti"; };
function cadreNettoyageCasier() {
  const c = (etat.d && etat.d.casier) || {}, lots = c.lots || [];
  if (!peutAgir() && !lots.length) return null;
  const zone = h("div", { classe: "groupes-zone" });
  if (lots.length) {
    const parSorte = new Map(SORTES_LOTS.map(([k]) => [k, []]));
    for (const l of lots) parSorte.get(sorteLot(l)).push(l);
    const recent = lots.find((l) => !l.restaure_le) || lots[0];
    ajouter(zone, SORTES_LOTS.filter(([k]) => parSorte.get(k).length).map(([k, titre, ic]) => {
      const l = parSorte.get(k), partis = k === "avertissements" || k === "casiers" ? l.filter((x) => estParti(x.membre)) : [];
      const presents = l.filter((x) => !partis.includes(x));
      return groupe({ cle: "casier-" + k, titre, icone: ic, compte: l.length, info: "dernier " + depuis(l[0].quand), defaut: sorteLot(recent) === k }, () => [
        presents.length ? lignes("casier-" + k, presents, ligneLot) : null,
        partis.length ? groupe({ cle: "casier-" + k + "-partis", titre: quantite(partis.length, k === "casiers" ? "casier(s) de membres partis" : "membre(s) parti(s)"), icone: "deconnexion", compte: partis.length },
          () => lignes("casier-" + k + "-partis", partis, ligneLot)) : null]);
    }));
  }
  return h("div", { classe: "cadre pile serree" }, h("div", { classe: "rangee entre" }, h("h3", { classe: "cadre-titre" }, "Nettoyer le casier"), lots.length > 1 ? outilsGroupes(zone) : null),
    h("p", { classe: "aide" }, "Repartir de zéro ou nettoyer une zone ; les bannissements restent, tout se défait pendant 30 jours. Amnistie automatique : 3 mois sans infraction."),
    peutAgir() ? h("div", { classe: "rangee" }, bouton("Nettoyer le casier…", { classe: "p danger", icone: "nettoyage", reseau: true, onclick: nettoyerCasier })) : null,
    lots.length ? zone : null);
}
/** Un nettoyage du casier : quoi, combien, par qui, quand ; « Annuler ce nettoyage » à droite (30 jours). */
function ligneLot(l) {
  const qui = l.membre ? P(l.membre) : null, parti = l.membre && estParti(l.membre);
  const titre = l.membre ? l.quoi + " de " + (parti ? "membre parti" : nomDe(qui)) : /^Amnistie/i.test(String(l.quoi || "")) ? "Amnistie automatique" : l.quoi;
  const sous = [quantite(l.n, "entrée(s)"), quantite(l.personnes, "personne(s)"), l.par ? "par " + nomDe(P(l.par)) : "automatique",
    l.restaure_le ? "annulé " + depuis(l.restaure_le) + (l.restaure_par ? " par " + nomDe(P(l.restaure_par)) : "") : ""].filter(Boolean).join(" · ");
  return ligne({
    visuel: qui && !parti ? avatar(qui, "p") : pastilleIcone(l.membre ? "personne" : /^Amnistie/i.test(String(l.quoi || "")) ? "minuteur" : "nettoyage", l.restaure_le ? "#6e553f" : "#7a4b2a"),
    titre, sous: [sous, parti ? h("span", { classe: "ident" }, " · identifiant " + l.membre) : null], ...quandLigne(l.quand),
    badges: l.restaure_le ? [tampon("Annulé", "encre", true)] : [], etat: l.restaure_le ? "eteinte" : null,
    actions: !l.restaure_le && peutAgir() ? [{ icone: "restaurer", libelle: "Annuler ce nettoyage", reseau: true,
      onclick: () => agir({ action: "casier_restaurer", lot: l.lot }, "Annuler ce nettoyage ?", quantite(l.n, "entrée(s)") + (l.n > 1 ? " reviennent" : " revient") + " au casier.", {}, "Remettre au casier") }] : [],
    ouvrir: qui && !parti ? () => ouvrirFiche(l.membre, "sanctions") : undefined, libelleOuvrir: qui && !parti ? "Ouvrir la fiche de " + nomDe(qui) : null,
    donnees: { lot: l.lot },
  });
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
// Les types de sanction en court dans les pastilles d'une ligne (le nom complet au survol).
const TYPES_COURTS = { warn: "Avert.", mute: "Mute", kick: "Expuls.", ban: "Ban" };
const badgeType = (t, n) => pastille(n + " × " + (TYPES_COURTS[t] || libelleType(t)), teinteType(t), n + " × " + libelleType(t));
/** Une personne au casier : son nombre sur la période, sa dernière sanction, ses types ; sa fiche au clic. */
function ligneCasier(m, entrees, nbr) {
  const p = P(m.id), der = entrees[0];
  const types = Object.entries(m.types).sort((a, b) => b[1] - a[1]);
  return ligne({
    visuel: avatar(p, "p"), titre: nomDe(p),
    sous: String(nbr) + " sur la période" + (der ? " · dernière : " + der.libelle + (der.duree ? " " + der.duree : "") + (der.raison ? " — " + der.raison : "") + " · " + (der.auto ? "automatique" : "par " + propre(der.par)) : ""),
    badges: [badgeRestreint(m.id), ...types.map(([t, n]) => badgeType(t, n))], maxBadges: 3,
    ...quandLigne(der ? der.date : m.derniere), etat: m.n30 >= 3 ? "alerte" : null,
    ouvrir: () => ouvrirFiche(m.id, "sanctions"), libelleOuvrir: "Ouvrir la fiche de " + nomDe(p), donnees: { membre: m.id },
  });
}
function ligneModerateur(x) {
  return ligne({
    visuel: avatar(P(x.id), "p"), titre: sansEmoji(x.nom), sous: quantite(x.total, "sanction(s) décidée(s)"),
    badges: Object.entries(x.types).sort((a, b) => b[1] - a[1]).map(([t, n]) => badgeType(t, n)), maxBadges: 3,
    ouvrir: () => ouvrirFiche(x.id, "donnees"), libelleOuvrir: "Ouvrir la fiche de " + sansEmoji(x.nom),
  });
}

// ─── Tickets (tous : ceux du serveur et ceux du clan) ───────────────────────
// 27/10/2026 : « Tickets » réunit TOUS les tickets ; l'ancien « Tickets du clan » (L'Équipage) est la famille « Clan ·
// RELL Seas ». La famille est la sous-page (#port/tickets · …/normaux · …/clan) et se choisit sans quitter la page
// (`sous`) ; le type, dans une liste (seulement s'il y en a plusieurs). Les tuiles et les tendances suivent la famille.
export const FAMILLES_TICKETS = nommerOnglets("site.sous.port.tickets", [["tous", "Tous", "tickets"], ["normaux", "Tickets normaux", "tickets"], ["clan", "Clan · RELL Seas", "equipage"]]);
const familleDe = (sous) => (FAMILLES_TICKETS.some(([k]) => k === sous) ? sous : "tous");
export function tickets(vue, ctx = {}) {
  let fam = familleDe(ctx.sous);
  const f = filtres("tickets", { q: "", sorte: "" });
  const haut = h("div", { classe: "pile" }), resultats = h("div", { classe: "pile" }), bas = h("div", { classe: "pile" });
  const pre = () => "tick-" + fam;
  const changer = () => { resetPages("tick-"); majResultats(); };
  const typeL = liste({ valeur: f.sorte, label: "Type", options: [], changer: (v) => { f.sorte = v; changer(); } });
  typeL.hidden = true;   // montrée avec les données, s'il y a plusieurs types
  ajouter(vue, [haut, h("div", { classe: "outils" }, recherche(f.q, "Membre, numéro, motif…", (q) => { f.q = q; changer(); }), typeL), resultats, bas]);
  const dansFamille = (t) => fam === "tous" || (fam === "clan") === !!t.rellseas;
  const majHaut = () => {
    const d = etat.d;
    if (!d) { remplacer(haut, indisponible()); return; }
    const tk = d.tickets, n = maintenant();
    const types = tk.types.filter(dansFamille);
    const prises = types.filter((t) => t.prise_mediane).map((t) => t.prise_mediane).sort((a, b) => a - b);
    const ouverts = tk.ouverts.filter(dansFamille);
    remplacer(haut, tuiles(
      tuile({ cle: "tick1", lib: "Ouverts", val: ouverts.length, icone: "tickets", teinte: "#a8641c" }),
      tuile({ cle: "tick2", lib: "Pas encore pris", val: ouverts.filter((t) => !t.pris_par).length, icone: "attention", teinte: "#8e2a24" }),
      tuile({ cle: "tick3", lib: "Prise en charge", texte: duree(prises.length ? prises[Math.floor(prises.length / 2)] : 0), icone: "minuteur", sous: "délai médian", teinte: "#1f4e5a" }),
      tuile({ cle: "tick4", lib: "Fermés · 30 jours", val: tk.fermes.filter((t) => dansFamille(t) && t.ferme && n - t.ferme <= 30 * JOUR).length, icone: "cadenas", teinte: "#3f6b3a" })));
    remplacer(bas, groupe({ titre: "Tendances", cle: "tick-tendances", icone: "carte", classe: "avance" }, () => h("div", { classe: "duo" },
      h("div", { classe: "cadre" }, h("h3", {}, "Tickets ouverts par mois"), h("p", { classe: "aide" }, "Rell Seas et tickets normaux, douze mois."),
        barres(Object.keys(tk.mois).sort(), tk.mois, [["Rell Seas", ENCRES.mer, "Rell Seas"], ["Tickets normaux", ENCRES.sienne, "Tickets normaux"]], "Les mois apparaîtront avec les premiers tickets.")),
      h("div", { classe: "cadre" }, h("h3", {}, "Staff"), h("p", { classe: "aide" }, "Tickets pris en charge et fermés, depuis le début. Direction et fondateur à part."),
        tk.staff.length ? barresH(tk.staff.map((x) => [sansEmoji(x.nom), x.pris + x.fermes, x.pris + " pris · " + x.fermes + " fermés"])) : vide("Rien à afficher")),
      h("div", { classe: "cadre" }, h("h3", {}, "Délais par type"), h("p", { classe: "aide" }, "Médianes : prise en charge, puis fermeture."),
        h("ul", { classe: "entrees" }, types.map((t) => h("li", { classe: "entree" }, h("div", { classe: "haut" }, h("span", { classe: "quoi" }, propre(t.nom)), h("span", { classe: "quand" }, t.total + " au total")),
          h("div", { classe: "meta" }, "prise en charge " + duree(t.prise_mediane) + " · fermeture " + duree(t.fermeture_mediane) + " · " + quantite(t.sans_prise, "fermé(s) sans prise")))))))));
  };
  const majResultats = () => {
    const d = etat.d;
    if (!d) { remplacer(resultats); return; }
    const tk = d.tickets, n = maintenant();
    const somme = (l) => l.reduce((a, t) => a + t.total, 0);
    const deFamille = (k) => tk.types.filter((t) => k === "tous" || (k === "clan") === !!t.rellseas);
    const types = deFamille(fam);
    // Le type : une liste, seulement quand la famille en a plusieurs (un type qui n'y est plus : tous les types).
    if (f.sorte && !types.some((t) => t.nom === f.sorte)) f.sorte = "";
    typeL.options([{ v: "", l: "Tous les types" }, ...types.map((t) => ({ v: t.nom, l: propre(t.nom), sous: quantite(t.total, "ticket(s)"), teinte: t.rellseas ? ENCRES.mer : ENCRES.sienne }))]);
    typeL.poser(f.sorte);
    typeL.hidden = types.length < 2;
    const teintes = { normaux: ENCRES.sienne, clan: ENCRES.mer };
    const familles = FAMILLES_TICKETS.map(([k, l]) => [k, l, somme(deFamille(k)), teintes[k]]);
    const garde = (t) => dansFamille(t) && (!f.sorte || t.type === f.sorte);
    const cherche = (t, p) => contient([p.nom, p.pseudo, p.id, "#" + t.ticket, t.motif, t.type].join(" "), f.q);
    const ouverts = tk.ouverts.filter((t) => garde(t) && cherche(t, t));
    const jours = Number(tk.archives_jours) || 30;
    // Les données portent les 300 fermés les plus récents : au-delà, les récents et une recherche viennent du serveur,
    // et chaque mois des archives se charge en entier quand on l'ouvre (longevite.js).
    const enPlus = [...(fermesDepuis(n - jours * JOUR, () => majResultats()) || []), ...((f.q && fermesRecherche(f.q, () => majResultats())) || [])];
    const fermes = (enPlus.length ? reunirFermes(tk.fermes, enPlus) : tk.fermes).filter((t) => garde(t) && cherche(t, P(t.id)));
    const recents = fermes.filter((t) => !t.ferme || n - t.ferme <= jours * JOUR), archives = fermes.filter((t) => t.ferme && n - t.ferme > jours * JOUR);
    const parMois = new Map();
    archives.forEach((t) => { const k = moisDe(t.ferme); if (!parMois.has(k)) parMois.set(k, []); parMois.get(k).push(t); });
    const attendus = new Map();   // mois → combien d'archives il compte en tout (pour ce filtre), chargées ou non
    if (!f.q) {
      const recentsParMois = new Map();
      recents.forEach((t) => { if (t.ferme) { const k = moisDe(t.ferme); recentsParMois.set(k, (recentsParMois.get(k) || 0) + 1); } });
      for (const [k, total] of comptesMois(garde)) {
        const reste = total - (recentsParMois.get(k) || 0);
        if (reste > 0) { attendus.set(k, reste); if (!parMois.has(k)) parMois.set(k, []); }
      }
    }
    const moisTries = [...parMois.keys()].sort().reverse();
    const nbArchives = moisTries.reduce((a, k) => a + Math.max(parMois.get(k).length, attendus.get(k) || 0), 0);
    // Les ouverts : ceux que personne n'a pris d'abord (les plus anciens en tête), puis ceux pris en charge.
    const nonPris = ouverts.filter((t) => !t.pris_par).sort((a, b) => (a.ouvert || 0) - (b.ouvert || 0)), pris = ouverts.filter((t) => t.pris_par);
    const p = pre();
    const zoneO = h("div", { classe: "groupes-zone" }, ouverts.length ? groupes([
      nonPris.length ? { cle: p + "-o-libres", titre: "Personne ne les a pris", icone: "attention", compte: nonPris.length, chaud: true, contenu: () => lignes(p + "-o-libres", nonPris, ligneTicketOuvert) } : null,
      pris.length ? { cle: p + "-o-pris", titre: "Pris en charge", icone: "personne", compte: pris.length, contenu: () => lignes(p + "-o-pris", pris, ligneTicketOuvert) } : null,
    ].filter(Boolean), { ouverts: 2, forcer: !!f.q }) : vide("Aucun ticket ouvert ici", "Tout est traité.", "succes"));
    const zoneF = h("div", { classe: "groupes-zone" }, recents.length ? groupesParPeriode(p + "-f", recents, (t) => t.ferme || t.ouvert, ligneTicketFerme, { forcer: !!f.q })
      : vide("Aucun ticket fermé ces " + jours + " derniers jours"));
    const rendreMois = (k) => (liste) => {
      const l = liste.filter((t) => garde(t) && cherche(t, P(t.id)) && t.ferme && n - t.ferme > jours * JOUR);
      return l.length ? lignes(p + "-a-" + k, l, ligneTicketFerme) : vide("Rien ce mois-ci", "Change le type ou la recherche.");
    };
    const zoneA = h("div", { classe: "groupes-zone" }, moisTries.length ? groupes(moisTries.map((k) => ({ cle: p + "-a-" + k, titre: libelleMois(k),
      compte: Math.max(parMois.get(k).length, attendus.get(k) || 0),
      contenu: () => moisArchive(k, parMois.get(k), attendus.get(k) || 0, rendreMois(k)) })), { ouverts: 0, forcer: !!f.q })
      : vide("Rien aux archives", "Les tickets y sont rangés " + jours + " jours après leur fermeture."));
    remplacer(resultats,
      // La famille change l'adresse (la présence en direct la dit, un rechargement la garde) ; la page suit sans se redessiner.
      puces(familles, fam, (k) => { if (k !== fam) aller("port", "tickets", k === "tous" ? "" : k); }, "Tickets"),
      section("Ouverts", "tickets", compte(ouverts.length, "ticket"), zoneO),
      section("Fermés ces " + jours + " derniers jours", "cadenas", compte(recents.length, "ticket"), zoneF, recents.length ? outilsGroupes(zoneF) : null),
      section("Archives", "coffre", compte(nbArchives, "ticket") + " · fermés depuis plus de " + jours + " jours", zoneA, moisTries.length > 1 ? outilsGroupes(zoneA) : null));
  };
  const maj = () => { majHaut(); majResultats(); };
  maj();
  return { maj, sous: (s) => { fam = familleDe(s); f.sorte = ""; resetPages("tick-"); maj(); } };
}

/** Un ticket ouvert : numéro et nom, type, qui l'a pris, depuis quand ; la conversation au clic. */
function ligneTicketOuvert(t) {
  const tard = !t.pris_par && t.ouvert && maintenant() - t.ouvert > JOUR;
  const conv = () => ouvrirConversation(t.ticket, "Ticket #" + t.ticket + " · " + nomDe(t));
  return ligne({
    visuel: avatar(t, "p"), titre: "#" + t.ticket + " · " + nomDe(t),
    sous: t.pris_par ? "pris par " + sansEmoji(t.pris_par) : tard ? "personne depuis plus de 24 h" : "pas encore pris",
    badges: [pastille(propre(t.type), t.rellseas ? ENCRES.mer : ENCRES.sienne), badgeRestreint(t.id)], ...quandLigne(t.ouvert), etat: tard ? "chaude" : null,
    actions: [{ icone: "parchemin", libelle: "Conversation", onclick: conv }, t.salon ? { icone: "discord", libelle: "Sur Discord", href: t.salon } : null,
      { icone: "personne", libelle: "Sa fiche", onclick: () => ouvrirFiche(t.id, "tickets") },
      peutAgir() ? { icone: "cadenas", libelle: "Fermer le ticket", danger: true, reseau: true, onclick: () => agir({ action: "ticket_fermer", ticket: t.ticket }, "Fermer le ticket #" + t.ticket + " ?", "Le salon du ticket est supprimé ; le transcript est gardé.", { motif: true }, "Fermer", "danger") } : null],
    ouvrir: conv, libelleOuvrir: "Conversation du ticket #" + t.ticket, donnees: { ticket: t.ticket },
  });
}
/** Un ticket fermé (récent ou aux archives) : motif, qui l'a fermé, durée ; la conversation au clic. */
function ligneTicketFerme(t) {
  const p = P(t.id), conv = () => ouvrirConversation(t.ticket, "Ticket #" + t.ticket + " · " + nomDe(p));
  return ligne({
    visuel: avatar(p, "p"), titre: "#" + t.ticket + " · " + nomDe(p),
    sous: [t.motif || "Sans motif", t.ferme_par ? "fermé par " + sansEmoji(t.ferme_par) : "", t.ferme && t.ouvert ? "durée " + duree(t.ferme - t.ouvert) : ""].filter(Boolean).join(" · "),
    badges: [pastille(propre(t.type), t.rellseas ? ENCRES.mer : ENCRES.sienne), badgeRestreint(t.id)], ...quandLigne(t.ferme || t.ouvert),
    actions: [{ icone: "parchemin", libelle: "Conversation", onclick: conv }, { icone: "personne", libelle: "Sa fiche", onclick: () => ouvrirFiche(t.id, "tickets") }],
    ouvrir: conv, libelleOuvrir: "Conversation du ticket #" + t.ticket, donnees: { ticket: t.ticket },
  });
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
  for (const r of (d.sanctions.actives && d.sanctions.actives.restreints) || []) inscrire(r);
  for (const id of d.a_part || []) inscrire(P(id), (f) => { f.direction = true; });
  return [...fiches.values()].filter((f) => f.nom !== "Membre parti" || f.casier || f.tickets);
}
export function repertoire(vue) {
  const f = filtres("repertoire", { q: "", filtre: "tous", lettre: "", tri: "nom" });
  const resultats = h("div", { classe: "pile" });
  const changer = () => { resetPages("rep"); maj(); };
  const champRecherche = recherche(f.q, "Nom, pseudo ou identifiant…", (q) => { f.q = q; f.lettre = ""; changer(); });
  ajouter(vue, [h("div", { classe: "outils" }, champRecherche,
    avance(liste({ valeur: f.tri, label: "Tri", options: [["nom", "Nom A → Z"], ["recent", "Activité récente"], ["casier", "Casier le plus lourd"]].map(([v, l]) => ({ v, l })), changer: (v) => { f.tri = v; changer(); } }))), resultats]);
  let cache = null, versionCache = null;
  const maj = () => {
    const d = etat.d;
    if (!d) { remplacer(resultats, indisponible()); return; }
    if (versionCache !== d) { cache = annuaire(); versionCache = d; }
    const FILTRES = [["tous", "Tout le monde", () => true], ["clan", "Clan", (x) => x.clan], ["casier", "Au casier", (x) => x.casier > 0], ["tickets", "Avec tickets", (x) => x.tickets > 0],
      ["candidats", "Candidats", (x) => !!x.candidat], ["alertes", "Alertes", (x) => x.alerte], ["restreints", "Restreints", (x) => estRestreint(x.id)], ["direction", "Direction", (x) => x.direction]];
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
        lignes("rep-liste", affiches, lignePersonne)));
    } else {
      // De A à Z : une lettre par groupe (toutes ouvertes s'il y a peu de monde, sinon la première), « Voir plus » par 20.
      const parLettre = new Map();
      affiches.forEach((x) => { const l = lettre(x.nom || x.pseudo); if (!parLettre.has(l)) parLettre.set(l, []); parLettre.get(l).push(x); });
      const ordre = [...parLettre.keys()].sort((a, b) => (a === "#") - (b === "#") || a.localeCompare(b));
      const zone = h("div", { classe: "groupes-zone" }, groupes(ordre.map((l) => ({ titre: l, compte: parLettre.get(l).length, cle: "rep-" + l,
        contenu: () => lignes("rep-l-" + l, parLettre.get(l), lignePersonne) })), { ouverts: affiches.length <= 60 ? ordre.length : 0 }));   // beaucoup de monde : on choisit sa lettre
      blocs.push(section("De A à Z", "repertoire", compte(affiches.length, "personne"), zone, ordre.length > 1 ? outilsGroupes(zone) : null));
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
  remplacer(zone, l.length ? section("Dans tout le serveur", "rechercher", compte(l.length, "personne"), h("ul", { classe: "lignes-c" }, l.slice(0, 25).map((m) => lignePersonne({
    id: String(m.id), nom: m.nom, pseudo: m.pseudo, avatar: m.avatar, clan: !!m.clan, direction: !!m.a_part, casier: 0, tickets: 0, candidat: "", alerte: false, journal: 0 })))) : null);
}
/** Une personne du répertoire : son nom, son pseudo, ses marques (les plus importantes d'abord) ; sa fiche au clic. */
function lignePersonne(x) {
  const marques = [
    x.alerte ? pastille("Alerte", "#8e2a24") : null,
    badgeRestreint(x.id),
    x.direction ? pastille("Direction", "#5e3a4e") : null,
    x.clan ? pastille("Clan", "#3f6b3a") : null,
    x.candidat ? pastille("Candidat · " + (STATUTS_CAND[x.candidat] || [x.candidat])[0], (STATUTS_CAND[x.candidat] || [])[1]) : null,
    x.casier ? pastille(x.casier + " au casier", "#a8641c") : null,
    x.tickets ? pastille(quantite(x.tickets, "ticket(s)"), "#7a4b2a") : null,
  ].filter(Boolean);
  return ligne({
    visuel: avatar(x, "p"), titre: nomDe(x), sous: [x.pseudo ? "@" + x.pseudo : "", h("span", { classe: "ident" }, (x.pseudo ? " · " : "") + x.id),
      !marques.length && x.journal ? " · " + quantite(x.journal, "évènement(s)") + " au journal" : ""],
    badges: marques, maxBadges: 3, date: x.derniere ? depuis(x.derniere) : "", dateTitre: x.derniere ? "Dernière trace : " + date(x.derniere, true) : "",
    ouvrir: () => ouvrirFiche(x.id), libelleOuvrir: "Ouvrir la fiche de " + nomDe(x), donnees: { membre: x.id },
  });
}

// ─── Salons & questions ─────────────────────────────────────────────────────
// 27/10/2026 : cinq onglets — « Idées & sondages » (avis) réunit deux vues, les idées et les sondages, aux adresses
// d'avant (#port/salons/idees, #port/salons/sondages), choisies sans quitter la page. Chaque nom se renomme (Textes &
// noms) : l'onglet et ses deux vues.
export const SOUS_SALONS = nommerOnglets("site.sous.port.salons", [["questions", "Questions", "salons"], ["avis", "Idées & sondages", "etoile"], ["idees", "Idées", "etoile"],
  ["sondages", "Sondages", "drapeau"], ["entraide", "Entraide & trade", "ancre"], ["annonces", "Annonces", "cloche"], ["droits", "Droits des salons", "cle"]]);
const ONGLETS_SALONS = ["questions", "avis", "entraide", "annonces", "droits"];
const VUES_AVIS = ["idees", "sondages"];
const nomSous = (k) => (SOUS_SALONS.find(([x]) => x === k) || [k, k])[1];
export function salons(vue, ctx) {
  let sous = ctx.sous === "avis" ? "idees" : SOUS_SALONS.some(([k]) => k === ctx.sous) ? ctx.sous : "questions";
  const f = filtres("salons", { q: "", ques: "ouverte", idees: "ouvertes", sond: "en_cours", entr: "ouvertes" });
  const onglets = h("div", { classe: "sous-onglets", role: "tablist", "aria-label": "Salons" });
  const resultats = h("div", { classe: "pile" });
  const outils = h("div", { classe: "outils" }, recherche(f.q, "Question, idée, membre, salon…", (q) => { f.q = q; resetPages("sal"); maj(); }));
  ajouter(vue, [onglets, outils, resultats]);
  let vues = null;   // « Idées | Sondages », à côté de la recherche
  const maj = () => {
    const d = etat.d;
    const nb = d ? {
      questions: ((d.questions && d.questions.stats) || {}).ouvertes || 0, idees: ((d.suggestions && d.suggestions.stats) || {}).ouvertes || 0,
      sondages: ((d.sondages && d.sondages.stats) || {}).en_cours || 0, entraide: ((d.entraide && d.entraide.stats) || {}).ouvertes || 0,
      annonces: ((d.annonces && d.annonces.stats) || {}).total || 0, droits: (Array.isArray(d.salons) ? d.salons : []).reduce((a, c) => a + ((c && c.salons) || []).length, 0),
    } : {};
    nb.avis = (nb.idees || 0) + (nb.sondages || 0);
    const avis = VUES_AVIS.includes(sous);
    remplacer(onglets, ...ONGLETS_SALONS.map((k) => {
      const [, l, ic] = SOUS_SALONS.find(([x]) => x === k);
      return h("a", { classe: "etiquette", role: "tab", href: "#port/salons/" + (k === "avis" ? (avis ? sous : "idees") : k), "aria-selected": String(k === (avis ? "avis" : sous)) },
        icone(ic), l, nb[k] ? h("span", { classe: "compteur" + (k === "questions" && nb[k] ? " chaud" : " calme") }, String(nb[k])) : null);
    }));
    if (vues) vues.remove();
    vues = avis ? segment(sous, VUES_AVIS.map((k) => [k, nomSous(k)]), (v) => { if (v !== sous) aller("port", "salons", v); }, nomSous("avis")) : null;
    if (vues) outils.append(vues);
    outils.hidden = sous === "droits";
    if (!d) { remplacer(resultats, indisponible()); return; }
    remplacer(resultats, ...[{ questions: sousQuestions, idees: sousIdees, sondages: sousSondages, entraide: sousEntraide, annonces: sousAnnonces, droits: sousDroits }[sous](d, f, maj)].flat());
  };
  maj();
  // Les deux vues d'« Idées & sondages » : sans quitter la page ; un autre onglet : la page neuve (`false`).
  return { maj, sous: (s) => { const n = s === "avis" ? "idees" : s; if (!VUES_AVIS.includes(n) || !VUES_AVIS.includes(sous)) return false; sous = n; resetPages("sal"); maj(); } };
}
function sousQuestions(d, f, maj) {
  const q = d.questions || {}, l = q.liste || [], st = q.stats || {};
  if (q.erreur) return vide("Questions momentanément illisibles");
  const top = (st.salons || [])[0];
  const nb = { tous: l.length };
  l.forEach((x) => { nb[x.statut] = (nb[x.statut] || 0) + 1; });
  const filtre = recentsDabord(l.filter((x) => (f.ques === "tous" || x.statut === f.ques) && contient([x.texte, x.salon, P(x.id).nom, P(x.id).pseudo, x.id].join(" "), f.q)), "quand");
  const zone = h("div", { classe: "groupes-zone" }, filtre.length ? groupesParPeriode("sal-q", filtre, (x) => x.quand, (x) => ligneQuestion(x, f.ques !== "tous"), { forcer: !!f.q, ouverts: f.ques === "ouverte" ? 5 : 1 })
    : vide(f.ques === "ouverte" ? "Aucune question en attente" : "Rien ici", f.ques === "ouverte" ? "Tout le monde a eu sa réponse." : "Change le filtre ou la recherche.", "succes"));
  return [tuiles(
    tuile({ cle: "q1", lib: "Sans réponse", val: st.ouvertes || 0, icone: "salons", teinte: "#a8641c" }),
    tuile({ cle: "q2", lib: "Répondues · 7 jours", val: st.repondues_7 || 0, icone: "valider", teinte: "#3f6b3a" }),
    tuile({ cle: "q3", lib: "Réponse du staff", texte: duree(st.delai_median), icone: "minuteur", sous: "délai médian", teinte: "#1f4e5a" }),
    tuile({ cle: "q4", lib: "Salon le plus questionné", texte: top ? nomSalon(top.salon) : "—", icone: "carte", sous: top ? quantite(top.n, "question(s)") + " sur 30 jours" : null, teinte: "#5e3a4e" })),
  h("div", { classe: "rangee entre" }, puces([["ouverte", "Sans réponse", nb.ouverte || 0, "#a8641c"], ["repondue", "Répondues", nb.repondue || 0, "#3f6b3a"], ["resolue", "Résolues", nb.resolue || 0, "#3f6b3a"],
    ["traitee", "Traitées", nb.traitee || 0, "#1f4e5a"], ["ignoree", "Pas des questions", nb.ignoree || 0, "#4a5560"], ["tous", "Toutes", nb.tous]], f.ques, (v) => { f.ques = v; resetPages("sal"); maj(); }, "Statut"),
    h("div", { classe: "rangee" }, filtre.length > 1 ? outilsGroupes(zone) : null,
      avance(exporter("Exporter", [["Questions · 30 jours (CSV)", { quoi: "questions" }], ["Questions · 30 jours (JSON)", { quoi: "questions", format: "json" }]])))),
  h("p", { classe: "aide avance" }, "Relevées toutes seules dans les salons publics. Elles se ferment quand le staff répond ou quand l'auteur dit que c'est bon."),
  zone];
}
/** Une question relevée dans un salon : le texte sur une ligne (en entier au clic), qui, où ; Discord et le statut à droite. */
function ligneQuestion(x, sansStatut) {   // sansStatut : la liste est déjà filtrée sur un statut, inutile de le répéter
  const [lib, teinte] = STATUTS_Q[x.statut] || [x.libelle, null];
  const ouverte = x.statut === "ouverte";
  return ligne({
    visuel: avatar(P(x.id), "p"), titre: x.texte,
    sous: [lienNom(x.id, ouvrirFiche), " · " + nomSalon(x.salon), x.par ? " · répondu par " + sansEmoji(x.par) + (x.repondu_le && x.repondu_le >= x.quand ? " en " + duree(x.repondu_le - x.quand) : "") : ""],
    badges: sansStatut ? [] : [pastille(lib, teinte)], ...quandLigne(x.quand), etat: ouverte ? "chaude" : null,
    actions: [x.message ? { icone: "discord", libelle: ouverte ? "Répondre sur Discord" : "Voir sur Discord", href: x.message } : null,
      ouverte ? { icone: "valider", libelle: "Traitée", reseau: true, onclick: () => agir({ action: "question", question: x.question, statut: "traitee" }, "", "", { direct: true }) }
        : { icone: "synchro", libelle: "Rouvrir", reseau: true, onclick: () => agir({ action: "question", question: x.question, statut: "ouverte" }, "", "", { direct: true }) },
      ouverte ? { icone: "annuler", libelle: "Pas une question", reseau: true, onclick: () => agir({ action: "question", question: x.question, statut: "ignoree" }, "", "", { direct: true }) } : null],
    visibles: 3, deplier: () => h("p", { classe: "texte" }, x.texte), donnees: { question: x.question },
  });
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
    filtre.length ? lignes("sal-i", filtre, ligneIdee) : vide(f.idees === "ouvertes" ? "Aucune idée à traiter" : "Rien ici", "Change le filtre ou la recherche.")];
}
const accordIdee = (x) => { const total = x.pour + x.contre; return total ? Math.round(100 * x.pour / total) + " % d'accord · " + nombre(x.pour) + " pour, " + nombre(x.contre) + " contre" : "pas encore de vote"; };
/** Une idée : son titre, qui, ses votes ; le détail, la barre des votes et la réponse au clic ; Répondre à droite. */
function ligneIdee(x) {
  const p = P(x.auteur), [lib, teinte] = STATUTS_I[x.statut] || [x.libelle, null];
  const total = x.pour + x.contre, pourcent = total ? Math.round(100 * x.pour / total) : 0;
  const ouverte = !x.retire_le && (x.statut === "attente" || x.statut === "etude");
  return ligne({
    visuel: avatar(p, "p"), titre: x.titre, sous: ["Idée n°" + x.id + " · ", lienNom(x.auteur, ouvrirFiche), " · " + accordIdee(x)],
    badges: [pastille(x.retire_le ? "Retirée du salon" : lib, x.retire_le ? "#4a5560" : teinte)], ...quandLigne(x.cree), etat: ouverte ? "chaude" : x.retire_le ? "eteinte" : null,
    actions: x.retire_le ? [] : [x.lien ? { icone: "discord", libelle: "Sur Discord", href: x.lien } : null,
      peutAgir() ? { icone: "plume", libelle: "Répondre", reseau: true, onclick: () => agir({ action: "suggestion_repondre", suggestion: x.id }, "Répondre à l'idée n°" + x.id, x.titre,
        { motif: true, choix: Object.entries(STATUTS_I).map(([k, [l]]) => [k, l]), choixDefaut: x.statut === "attente" ? "etude" : x.statut }, "Envoyer la réponse") } : null,
      peutAgir() ? { icone: "supprimer", libelle: "Retirer du salon", danger: true, reseau: true, onclick: () => agir({ action: "suggestion_retirer", suggestion: x.id }, "Retirer cette idée du salon ?", "Sa carte disparaît de Discord ; elle reste ici.", {}, "Retirer du salon", "danger") } : null],
    deplier: () => [x.details ? h("p", { classe: "texte" }, x.details) : null,
      h("div", { classe: "votes" }, h("div", { classe: "vote" + (total && pourcent >= 50 ? " tete" : "") },
        h("div", { classe: "vote-haut" }, h("span", {}, total ? pourcent + " % d'accord" : "Pas encore de vote"), h("b", { classe: "num" }, nombre(x.pour) + " pour", h("small", {}, nombre(x.contre) + " contre"))),
        h("span", { classe: "vote-fond" }, h("span", { classe: "vote-plein", vars: { "--pc": pourcent + "%" } })))),
      x.note ? h("div", { classe: "bandeau vert" }, icone("plume"), h("div", { classe: "bandeau-texte" }, h("span", {}, h("b", {}, "Réponse : "), x.note))) : null,
      x.decide_par ? h("p", { classe: "meta" }, "Décidée par " + nomDe(P(x.decide_par)) + (x.decide_le ? " · " + depuis(x.decide_le) : "")) : null],
  });
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
  filtre.length ? lignes("sal-s", filtre, ligneSondage) : vide(f.sond === "en_cours" ? "Aucun sondage en cours" : "Rien ici", "Change le filtre ou la recherche.")];
}
/** Un sondage : la question, qui, combien de votes ; les résultats au clic. */
function ligneSondage(x) {
  const p = P(x.auteur), [lib, teinte] = STATUTS_S[x.statut] || [x.statut, null];
  const quand = x.statut === "en_cours" ? "fin le " + date(x.fin, true) : x.statut === "retire" ? "retiré " + depuis(x.retire_le) + (x.retire_par ? " par " + nomDe(P(x.retire_par)) : "") : "terminé le " + date(x.fin, true);
  return ligne({
    visuel: avatar(p, "p"), titre: x.question, sous: [lienNom(x.auteur, ouvrirFiche), " · " + nomSalon(x.salon) + " · " + quantite(x.total, "vote(s)") + (x.multiple ? " · plusieurs choix" : "") + " · " + quand],
    badges: [pastille(lib, teinte)], ...quandLigne(x.cree), etat: x.statut === "retire" ? "eteinte" : null,
    actions: x.statut === "retire" ? [] : [x.lien ? { icone: "discord", libelle: "Sur Discord", href: x.lien } : null,
      peutAgir() ? { icone: "supprimer", libelle: "Retirer du salon", danger: true, reseau: true, onclick: () => agir({ action: "sondage_retirer", sondage: x.id }, "Retirer ce sondage du salon ?", "Le message disparaît de Discord ; son résultat reste ici.", {}, "Retirer du salon", "danger") } : null],
    deplier: () => sondageVotes(x),
  });
}
const STATUTS_E = { ouverte: ["Ouverte", "#3f6b3a"], prise: ["En cours", "#a8641c"], terminee: ["Terminée", "#1f4e5a"], fermee: ["Fermée", "#4a5560"], expiree: ["Fermée sans activité", "#4a5560"], retiree: ["Retirée", "#4a5560"] };
// Les zones d'échange du serveur : « trade » (Rell Seas) et « cl_trade » (Clover RPG) — entraide.ZONES.
const estEchange = (x) => /(^|_)trade$/.test(String(x.zone || ""));
function sousEntraide(d, f, maj) {
  const en = d.entraide || {}, le = en.liste || [];
  if (en.erreur) return vide("Entraide momentanément illisible");
  const ouverte = (x) => x.statut === "ouverte" || x.statut === "prise";
  const filtre = le.filter((x) => (f.entr === "toutes" || (f.entr === "ouvertes" ? ouverte(x) : f.entr === "trade" ? estEchange(x) : x.zone === f.entr)) && contient([x.titre, x.type, (x.champs || []).map((c) => c[1]).join(" "), P(x.auteur).nom].join(" "), f.q));
  return [h("p", { classe: "aide" }, "Chaque demande d'aide et de trade : qui l'a faite, qui est venu, qui l'a certifiée, avec qui l'échange s'est fait. Close, elle disparaît de Discord ; elle reste ici."),
    puces([["ouvertes", "En cours", le.filter(ouverte).length, "#3f6b3a"], ["trade", "Trade", le.filter(estEchange).length, "#a8641c"], ["toutes", "Toutes", le.length]], f.entr, (v) => { f.entr = v; resetPages("sal"); maj(); }, "Statut"),
    filtre.length ? lignes("sal-e", filtre, ligneDemande) : vide(f.entr === "ouvertes" ? "Aucune demande en cours" : "Rien ici", "Change le filtre ou la recherche.")];
}
/** Une demande d'entraide ou de trade : le titre, qui, où ; les champs, les aidants et l'échange au clic. */
function ligneDemande(x) {
  const p = P(x.auteur), [lib, teinte] = STATUTS_E[x.statut] || [x.libelle, null];
  const fin = x.certifie_par ? "certifiée par " + nomDe(P(x.certifie_par)) : x.ferme_par ? "close par " + nomDe(P(x.ferme_par)) : "";
  return ligne({
    visuel: avatar(p, "p"), titre: x.titre, sous: [sansEmoji(x.type) + " · n°" + x.id + " · ", lienNom(x.auteur, ouvrirFiche), fin ? " · " + fin : ""],
    badges: [pastille(lib, teinte)], ...quandLigne(x.cree), etat: x.statut === "ouverte" || x.statut === "prise" ? "chaude" : null,
    actions: [x.lien ? { icone: "discord", libelle: "Sur Discord", href: x.lien } : null, x.transcript ? { icone: "parchemin", libelle: "Historique", href: x.transcript } : null],
    deplier: () => [(x.champs || []).length ? h("dl", { classe: "champs-lus" }, x.champs.map(([l, v]) => h("div", {}, h("dt", {}, l), h("dd", {}, v)))) : null,
      (x.aidants || []).length ? h("p", { classe: "meta" }, (estEchange(x) ? "Intéressés : " : "Venus aider : ") + x.aidants.map((a) => nomDe(P(a))).join(", ")) : null,
      x.partenaire ? h("p", { classe: "meta" }, "Échange avec " + nomDe(P(x.partenaire))) : null,
      fin ? h("p", { classe: "meta" }, fin + (x.ferme ? " · " + depuis(x.ferme) : "")) : null],
  });
}
function sousAnnonces(d, f) {
  const an = d.annonces || {}, la = an.liste || [];
  if (an.erreur) return vide("Annonces momentanément illisibles");
  const filtre = la.filter((x) => contient([x.titre, x.texte, x.salon].join(" "), f.q));
  return [h("p", { classe: "aide" }, "Les annonces publiées depuis le salon « logs », et combien de membres les ont vues. Pour composer une annonce du clan : L'Équipage, Annonces & événements."),
    filtre.length ? lignes("sal-a", filtre, (x) => ligne({
      visuel: avatar(P(x.auteur), "p"), titre: x.titre, sous: nomSalon(x.salon) + " · par " + nomDe(P(x.auteur)) + (x.mention ? " · mention " + x.mention.replace(/^@/, "") : ""),
      badges: [pastille(x.vues ? "Vue par " + quantite(x.vues, "membre(s)") : "Pas encore vue", x.vues ? "#3f6b3a" : "#4a5560", (x.vus || []).length ? x.vus.map((v) => nomDe(P(v))).join(", ") : null)],
      ...quandLigne(x.cree), actions: [x.lien ? { icone: "discord", libelle: "Sur Discord", href: x.lien } : null],
      deplier: () => [h("p", { classe: "texte" }, x.texte), (x.vus || []).length ? h("p", { classe: "meta" }, "Vue par " + x.vus.map((v) => nomDe(P(v))).join(", ")) : null],
    })) : vide("Aucune annonce")];
}
const PROFILS = { ouvert: ["Ouvert à tous", "#3f6b3a"], lecture: ["Lecture seule", "#1f4e5a"], vitrine: ["Visible, fermé", "#5e3a4e"], clan: ["Clan seulement", "#7a4b2a"], cache: ["Réservé", "#4a5560"] };
function sousDroits(d) {
  const cats = d.salons || [];
  if (!Array.isArray(cats) || !cats.length) return vide("Aucun salon lisible");
  // Une catégorie de salons par groupe (la première ouverte), un salon par ligne : ce que chacun peut y faire.
  const zone = h("div", { classe: "groupes-zone" }, groupes(cats.map((cat, i) => ({ cle: "droits-" + i + "-" + (sansEmoji(cat.categorie) || "sans"), titre: sansEmoji(cat.categorie) || "Sans catégorie", compte: cat.salons.length,
    contenu: () => h("ul", { classe: "lignes-c" }, cat.salons.map((sl) => {
      const [lib, teinte] = PROFILS[sl.profil] || [sl.profil, null];
      const peut = sl.vocal ? [sl.rejoindre ? "rejoindre" : null] : [sl.ecrire ? "écrire" : null, sl.images ? "images" : null, sl.reagir ? "réagir" : null];
      return ligne({ visuel: pastilleIcone(sl.vocal ? "cloche" : "salons", teinte), titre: sansEmoji(sl.nom) || "salon",
        sous: "Chacun peut : " + (peut.filter(Boolean).join(", ") || "rien d'autre que voir"), badges: [pastille(lib, teinte)] });
    })) }))));
  return [h("div", { classe: "rangee entre" }, h("p", { classe: "aide" }, "Lecture seule : rien ne se règle d'ici. Ouvert à tous : on écrit. Lecture seule : on lit sans écrire. Visible, fermé : on voit le vocal sans y entrer. Clan seulement : réservé au rôle du clan. Réservé : caché à tout le monde."),
    cats.length > 1 ? outilsGroupes(zone) : null), zone];
}

// ─── Nettoyage ──────────────────────────────────────────────────────────────
// `api/nettoyage` (tableau.etat_nettoyage) : `regles` (durée, bornes, réglable, `auto` : elle efface), `compteurs`
// (ce que chaque règle GARDE aujourd'hui — null : compte illisible), `dernier` (le dernier passage, null : jamais),
// `bilan` (ce passage : règle → éléments retirés, -1 : en échec), `par` (qui l'a lancé, vide : la boucle du jour),
// `bilans` (les 10 derniers passages : quand, total, détail, par) et `personnes` (leurs noms).
const parQui = (id) => (id ? "par " + nomDe(P(id)) : "automatique");
export function nettoyage(vue) {
  const zone = h("div", { classe: "pile" }, squelettes(3));
  ajouter(vue, [zone]);
  const maj = async (forcer) => {
    const n = await charger("nettoyage", { forcer });
    if (!zone.isConnected) return;
    if (!n || n.erreur) { remplacer(zone, n && n.erreur ? vide("Nettoyage indisponible", n.erreur, "hors_ligne") : squelettes(3)); return; }
    retenirPersonnes(n.personnes);
    const regles = n.regles || [], compteurs = n.compteurs || {}, partiront = n.partiront || {};
    const garde = regles.reduce((a, r) => a + (Number(compteurs[r.cle]) || 0), 0);
    const aPartir = Object.values(partiront).reduce((a, k) => a + (Number(k) || 0), 0);
    const dernier = (n.bilans || [])[0] || null;
    const echecs = Object.entries(n.bilan || {}).filter(([, v]) => Number(v) < 0).map(([k]) => (regles.find((r) => r.cle === k) || { nom: k }).nom);
    remplacer(zone,
      tuiles(tuile({ cle: "n1", lib: "Dernier nettoyage", texte: n.dernier ? depuis(n.dernier) : "jamais", icone: "nettoyage",
        sous: n.dernier ? date(n.dernier, true) + " · " + parQui(n.par) : "il passe tout seul chaque jour", teinte: "#3f6b3a" }),
        tuile({ cle: "n2", lib: "Gardé aujourd'hui", val: garde, icone: "coffre", sous: "sous les " + quantite(regles.length, "règle(s)") + " ci-dessous", teinte: "#a8641c" }),
        tuile({ cle: "n4", lib: "Au prochain passage", val: aPartir, icone: "minuteur", sous: aPartir ? accord(aPartir, "élément(s) à effacer") : "rien n'a dépassé sa durée", teinte: "#7a4b2a" }),
        dernier ? tuile({ cle: "n3", lib: "Dernier bilan", val: dernier.total, icone: "journal", sous: echecs.length ? "en échec : " + echecs.join(", ") : dernier.total ? accord(dernier.total, "élément(s) retiré(s)") : "rien à retirer",
          teinte: echecs.length ? "#8e2a24" : "#4a5560" }) : null),
      cadreStockage(n.stockage),
      h("div", { classe: "cadre pile serree" }, h("h3", {}, "Le grand ménage"),
        h("p", { classe: "aide" }, "Il passe tout seul chaque jour. Tu peux aussi le lancer maintenant : chaque règle efface ce qui a dépassé sa durée, et le bilan est noté au journal."),
        h("p", { classe: "meta" }, icone("nettoyage", "ic-p"), " Dernier passage : " + (n.dernier ? depuis(n.dernier) + " · " + parQui(n.par) : "jamais")
          + (dernier ? " · " + (dernier.total ? quantite(dernier.total, "élément(s) retiré(s)") : "rien à retirer") : "") + (echecs.length ? " · en échec : " + echecs.join(", ") : "")),
        h("div", { classe: "rangee" }, bouton("Lancer le nettoyage maintenant", { classe: "principal", icone: "nettoyage", reseau: true, onclick: async () => {
          const ok = await confirmer({ titre: "Lancer le nettoyage maintenant ?", texte: "Chaque règle ci-dessous efface ce qui a dépassé sa durée" + (aPartir ? " (" + quantite(aPartir, "élément(s)") + ")" : "") + " ; les rangements n'effacent rien. Ce qui part du casier reste annulable 30 jours (Sanctions).", libelleOk: "Nettoyer", style: "principal" });
          if (!ok) return;
          const r = await poster("nettoyage/lancer", {});
          if (!r.ok) { toast(r.erreur || "Le nettoyage n'a pas pu être lancé.", "erreur"); return; }
          const b = ((r.donnees && r.donnees.bilans) || [])[0];
          toast(b ? "Nettoyage fait : " + (b.total ? quantite(b.total, "élément(s) retiré(s)") : "rien à retirer") + "." : "Nettoyage fait.", "succes");
          maj(true);
        } }), h("a", { classe: "bouton discret", href: "#port/sanctions" }, icone("sanctions"), h("span", {}, "Nettoyer le casier (Sanctions)")))),
      section("Les règles", "parchemin", compte(regles.length, "règle"), reglesRangees(regles, compteurs, partiront, () => maj(true))),
      (n.bilans || []).length ? groupe({ titre: "Les derniers bilans", compte: n.bilans.length, cle: "net-bilans", icone: "journal" }, () => lignes("net-bilans", n.bilans, (b) => ligne({
        visuel: pastilleIcone("nettoyage", b.total ? "#3f6b3a" : "#6e553f"), titre: b.total ? quantite(b.total, "élément(s) retiré(s)") : "Rien à retirer",
        sous: parQui(b.par) + (b.detail ? " · " + b.detail : ""), date: date(b.quand, true), deplier: b.detail ? () => h("p", { classe: "texte" }, b.detail) : undefined }))) : null);
  };
  maj();
  return { maj: () => maj(false) };
}
/** Les règles rangées par famille (le journal, les tickets, le casier…) : un groupe chacune, celles où quelque chose
 *  attend d'être effacé en avant ; des cartes de même hauteur (26/10/2026 : une règle par famille de données). */
function reglesRangees(regles, compteurs, partiront, recharger) {
  const parFamille = new Map(FAMILLES.map((f) => [f[2], []]));
  for (const r of regles) parFamille.get(familleRegle(Number(r.ordre) || 0)[2]).push(r);
  const grille = (l) => h("div", { classe: "grille egale" }, l.map((r) => carteRegle(r, compteurs[r.cle], recharger, partiront[r.cle])));
  return h("div", { classe: "groupes-zone" }, groupes(FAMILLES.filter((f) => parFamille.get(f[2]).length).map(([, , titre, ic]) => {
    const l = parFamille.get(titre), n = l.reduce((a, r) => a + (Number(partiront[r.cle]) || 0), 0);
    return { cle: "net-f-" + ic, titre, icone: ic, compte: l.length, chaud: n > 0, info: n ? quantite(n, "élément(s)") + " à effacer" : "", contenu: () => grille(l) };
  }), { ouverts: 1 }));
}
function carteRegle(r, garde, recharger, partira) {
  // Le compte : absent (la règle n'en donne pas), null (illisible côté serveur), ou ce que la règle garde aujourd'hui.
  const rangement = r.auto === false;
  const nb = garde === undefined ? "" : garde === null ? "compte indisponible"
    : garde ? quantite(garde, rangement ? "élément(s) rangé(s)" : "élément(s) gardé(s)") : rangement ? "rien de rangé" : "rien de gardé";
  const sorte = rangement ? "rangement : rien n'est effacé" : r.reglable === false ? "règle fixe, appliquée chaque jour" : "appliquée chaque jour";
  const duree = (j) => r.duree || (Number(j) ? j + " j" : "jusqu'à expiration");
  // Ce qui partira au prochain passage, et « Nettoyer maintenant » quand il y a quelque chose (26/10/2026).
  const apercu = h("p", { classe: "meta regle-apercu", "aria-live": "polite" }, texteApercu(partira));
  const maintenant_ = boutonNettoyerRegle(r, Number(partira) || 0, recharger);
  if (r.reglable === false) {
    return h("article", { classe: "feuillet regle" }, h("h3", { classe: "titre-carte" }, r.nom), h("p", { classe: "aide" }, r.quoi),
      h("div", { classe: "regle-ligne" }, h("span", { classe: "champ-lib" }, "Garder"), h("b", { classe: "num regle-valeur" }, duree(r.garde_jours))),
      h("p", { classe: "meta" }, [nb, sorte].filter(Boolean).join(" · ")), apercu, maintenant_ ? h("div", { classe: "rangee" }, maintenant_) : null);
  }
  const mini = Number(r.min) || 1, maxi = Number(r.max) || 365;
  let jours = Number(r.garde_jours) || mini;
  const valeur = h("b", { classe: "num regle-valeur" }, jours + " j");
  const reg = h("input", { classe: "reglette", type: "range", min: mini, max: maxi, step: 1, value: jours, "aria-label": "Garder pendant (jours)" });
  const enregistrer = bouton("Enregistrer", { classe: "p", icone: "valider", disabled: true });
  const etatBouton = () => { enregistrer.disabled = jours === Number(r.garde_jours) || !enLigne(); enregistrer.title = enLigne() ? "" : "Hors ligne : à enregistrer au retour de la connexion."; };
  const avecDuree = apercuReglette(r.cle, apercu);   // « avec 45 j : 1 234 éléments partiraient »
  reg.addEventListener("input", () => {
    jours = Number(reg.value); valeur.textContent = jours + " j"; etatBouton();
    if (r.auto !== false && partira !== undefined) { if (jours === Number(r.garde_jours)) apercu.textContent = texteApercu(partira); else avecDuree(jours); }
  });
  const stop = ecouter("reseau", () => { if (!enregistrer.isConnected) { stop(); return; } etatBouton(); });
  enregistrer.addEventListener("click", async () => {
    const rep = await poster("nettoyage/regle", { cle: r.cle, garde_jours: jours });
    toast(rep.ok ? "Règle enregistrée : " + r.nom + ", " + jours + " jours." : rep.erreur, rep.ok ? "succes" : "erreur");
    if (rep.ok) recharger();
  });
  const carte = h("article", { classe: "feuillet regle" },
    h("h3", { classe: "titre-carte" }, r.nom), h("p", { classe: "aide" }, r.quoi),
    h("div", { classe: "regle-ligne" }, h("span", { classe: "champ-lib" }, "Garder"), valeur),
    reg, h("div", { classe: "regle-bornes" }, h("span", {}, mini + " j"), h("span", {}, maxi + " j")),
    r.defaut && Number(r.defaut) !== Number(r.garde_jours) ? h("p", { classe: "meta" }, "Par défaut : " + r.defaut + " j ",
      h("button", { classe: "lien-nom", type: "button", onclick: () => { reg.value = r.defaut; reg.dispatchEvent(new Event("input")); } }, "remettre")) : null,
    h("div", { classe: "rangee entre" }, h("span", { classe: "meta" }, [nb, sorte].filter(Boolean).join(" · ")), enregistrer),
    apercu, maintenant_ ? h("div", { classe: "rangee" }, maintenant_) : null);
  // Présence en direct : la règle se prend au premier geste ; prise ailleurs, elle se fige sous le cadenas.
  protegerZone(carte, "nettoyage:" + r.cle, "la règle « " + r.nom + " »", { des: "saisie", compact: true, relire: recharger });
  return avecVerrou(carte, "nettoyage:" + r.cle);
}
