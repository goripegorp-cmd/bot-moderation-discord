// fiche.js — la fiche d'une personne (tout ce qui la concerne) et la conversation complète d'un ticket.
// Aussi : couleurs, libellés et entrées partagés par les rubriques.

import { h, icone, date, heure, depuis, duree, nombre, cleJour, libelleJour, sansEmoji, maintenant, srcSure, BASE, remplacer, quantite, ajouter } from "./dom.js";
import { etat, P, peutAgir, retenirPersonnes, poserAncre, aller, emettre } from "./noyau.js";
import { lire, action as envoyerAction, lienExport } from "./api.js";
import { pancarte, confirmer, bouton, avatar, pastille, tampon, vide, squelettes, boutonCopie, nomDe, lienNom, toast, liste, champ, zoneTexte } from "./ui.js";

// ─── Couleurs et libellés partagés ──────────────────────────────────────────
export const COULEURS_CAT = {
  "Modération": "#a8641c", "Sécurité": "#8e2a24", "Membres": "#3f6b3a", "Messages": "#1f4e5a", "Vocal": "#5e3a4e",
  "Serveur": "#4a5560", "Tickets": "#7a4b2a", "Config": "#4a5560", "Clan": "#3f6b3a", "Sondages": "#5e3a4e",
  "Suggestions": "#7a5a22", "Questions": "#1f4e5a", "Accès": "#8e2a24", "Entraide": "#3f6b3a", "Site": "#2b1d12",
};
export const teinteCat = (c) => COULEURS_CAT[c] || "#5a4330";
export const GROUPES_SANCTION = { "Avertissements": "#a8641c", "Mutes": "#5e3a4e", "Expulsions et bans": "#8e2a24", "Détections": "#4a5560" };
const GROUPE_DE = { warn: "Avertissements", mute: "Mutes", kick: "Expulsions et bans", ban: "Expulsions et bans" };
export const teinteType = (t) => GROUPES_SANCTION[GROUPE_DE[t] || "Détections"];
export const libelleType = (t) => ((etat.d && etat.d.sanctions && etat.d.sanctions.libelles) || {})[t] || t;
export const STATUTS_CAND = { en_cours: ["En cours", "#a8641c"], acceptes: ["Accepté", "#3f6b3a"], refuses: ["Refusé", "#8e2a24"] };
export const STATUTS_Q = { ouverte: ["Sans réponse", "#a8641c"], repondue: ["Répondue", "#3f6b3a"], resolue: ["Résolue", "#3f6b3a"], traitee: ["Traitée", "#1f4e5a"], ignoree: ["Pas une question", "#4a5560"] };
export const STATUTS_S = { en_cours: ["En cours", "#3f6b3a"], termine: ["Terminé", "#1f4e5a"], retire: ["Retiré du salon", "#4a5560"] };
export const STATUTS_I = { attente: ["En attente", "#a8641c"], etude: ["À l'étude", "#1f4e5a"], acceptee: ["Acceptée", "#3f6b3a"], refusee: ["Refusée", "#8e2a24"], realisee: ["Réalisée", "#3f6b3a"] };
export const RANGS = [["Actif", "#3f6b3a"], ["Peu présent", "#a8641c"], ["Inactif", "#8e2a24"], ["Jamais vu", "#4a5560"], ["Trop récent", "#4a5560"]];
export const deplier = (e) => { e.stopPropagation(); e.currentTarget.classList.toggle("ouvert"); };

/** Une action du tableau, confirmée puis envoyée ; prévient et rafraîchit. */
export async function agir(corps, titre, texte, opts = {}, libelleOk, style) {
  if (!opts.direct) {
    const r = await confirmer({ titre, texte, motif: !!opts.motif, motifRequis: !!opts.motifRequis, durees: !!opts.durees,
      choix: opts.choix, choixDefaut: opts.choixDefaut, libelleOk, style, mot: opts.mot, contenu: opts.contenu });
    if (!r) return false;
    if (r.motif) corps.motif = r.motif;
    if (r.duree) corps.duree = r.duree;
    if (r.choix) corps.statut = r.choix;
  }
  const rep = await envoyerAction(corps);
  toast(rep.message, rep.ok ? "succes" : "erreur");
  if (rep.ok) {
    emettre("action:faite", corps);
    setTimeout(() => emettre("recharger"), 900);
    if (etatFiche.id && etatFiche.pan && !etatFiche.pan.fermee()) setTimeout(() => rechargerFiche(), 1300);
  }
  return rep.ok;
}

/** Une ligne du journal, dans une liste d'entrées. */
export function entreeJournal(e, sujet, ouvrir) {
  const a = e.auteur && e.auteur !== e.membre && e.auteur !== sujet ? e.auteur : null;
  return h("li", { classe: "entree" + (e.gravite >= 2 ? " grave" : ""), vars: { "--teinte": teinteCat(e.cat) } },
    h("div", { classe: "haut" }, h("span", { classe: "quoi" }, e.cat), h("span", { classe: "quand" }, heure(e.quand) + " · " + libelleJour(cleJour(e.quand)))),
    h("div", { classe: "texte coupe3 deplier", onclick: deplier, title: "Afficher tout" }, e.texte),
    e.detail ? h("div", { classe: "meta coupe2 deplier", onclick: deplier }, e.detail) : null,
    a || e.salon ? h("div", { classe: "meta" }, a ? ["par ", lienNom(a, ouvrir || ouvrirFiche)] : null, a && e.salon ? " · " : null, e.salon ? sansEmoji(e.salon) || e.salon : null) : null);
}

// ─── La fiche ───────────────────────────────────────────────────────────────
const ONGLETS = [["chrono", "Chronologie", "journal"], ["sanctions", "Sanctions", "sanctions"], ["tickets", "Tickets", "tickets"],
  ["candidatures", "Candidatures", "candidatures"], ["questions", "Questions", "salons"], ["sondages", "Sondages et idées", "salons"],
  ["journal", "Journal", "parchemin"], ["donnees", "Décidées par lui", "plume"]];
const etatFiche = { id: null, onglet: "chrono", max: 40, f: null, pan: null, horsLigne: false };
export const ficheOuverte = () => etatFiche.id;

export async function ouvrirFiche(id, onglet) {
  if (!id || id === "serveur") return;
  if (etatFiche.pan && !etatFiche.pan.fermee()) etatFiche.pan.fermer();
  const p0 = P(id);
  const pan = pancarte({
    titre: nomDe(p0), sous: p0.pseudo ? "@" + p0.pseudo : "", icone: "personne", taille: "large",
    surFermer: () => { if (etatFiche.pan === pan) { etatFiche.id = null; etatFiche.pan = null; poserAncre(""); } },
  });
  Object.assign(etatFiche, { id: String(id), onglet: onglet || "chrono", max: 40, f: null, pan });
  poserAncre("membre=" + id);
  ajouter(pan.corps, [squelettes(3, "haut")]);
  await chargerFiche(pan, id);
}
async function rechargerFiche() { if (etatFiche.pan && etatFiche.id) await chargerFiche(etatFiche.pan, etatFiche.id, true); }

async function chargerFiche(pan, id, silencieux) {
  const r = await lire("membre", { id });
  if (pan.fermee() || etatFiche.pan !== pan) return;
  if (!r.ok || !r.donnees || r.donnees.erreur) {
    if (!silencieux) remplacer(pan.corps, vide("Fiche indisponible", r.status === 0 ? "Hors ligne : cette fiche n'a pas encore été ouverte sur cet appareil." : (r.erreur || "Réessaie dans un instant."), "attention"));
    return;
  }
  retenirPersonnes(r.donnees.personnes);
  etatFiche.f = r.donnees;
  etatFiche.horsLigne = !!r.horsLigne;
  rendreFiche();
}

function rendreFiche() {
  const f = etatFiche.f, pan = etatFiche.pan;
  if (!f || !pan) return;
  const m = f.membre, p = Object.assign({}, P(m.id), m);
  pan.titre.firstChild.textContent = nomDe(p);
  const pastilles_ = [
    m.a_part ? pastille("Fondateur ou direction · protégé", "#5e3a4e") : null,
    m.clan ? pastille("Clan GoRP", "#3f6b3a") : null,
    m.mute_jusqu ? pastille("Muté jusqu'au " + date(m.mute_jusqu, true), "#a8641c") : null,
    !m.present ? pastille(m.banni ? "Banni" : "A quitté le serveur", m.banni ? "#8e2a24" : "#4a5560") : null,
    f.alerte ? pastille("Alerte en cours", "#8e2a24") : null,
    m.bot ? pastille("Robot", "#4a5560") : null,
  ].filter(Boolean);
  const corps = [];
  if (etatFiche.horsLigne) corps.push(h("p", { classe: "aide" }, icone("hors_ligne", "ic-p"), " Fiche lue dans la mémoire de l'appareil (hors ligne)."));
  corps.push(h("div", { classe: "fiche-entete" },
    avatar(p, "tg"),
    h("div", { classe: "fiche-ident" },
      h("div", { classe: "nom fiche-nom" }, nomDe(p)),
      h("div", { classe: "sous-nom" }, p.pseudo ? "@" + p.pseudo + " · " : "", h("span", { classe: "ident" }, p.id), boutonCopie(p.id, "Identifiant copié")),
      pastilles_.length ? h("div", { classe: "pastilles" }, pastilles_) : null)));
  corps.push(h("div", { classe: "mini-tuiles" },
    miniTuile(f.sanctions.length, "sanction", "sanctions"), miniTuile(f.tickets.length, "ticket", "tickets"),
    miniTuile(f.journal.length, "au journal", "journal", true), miniTuile(f.questions.length, "question", "questions")));
  corps.push(h("div", { classe: "infos" },
    info("Sur le serveur", m.present ? "Depuis le " + date(m.arrivee) : m.banni ? "Non — banni" : "Non — parti"),
    info("Compte Discord créé", m.cree ? date(m.cree) : "—"),
    m.roles && m.roles.length ? h("div", { classe: "info large" }, h("div", { classe: "k" }, "Rôles (lecture seule)"),
      h("div", { classe: "pastilles" }, m.roles.map((r) => pastille(sansEmoji(r.nom) || "Rôle", r.couleur || null)))) : null));
  corps.push(h("div", { classe: "rangee" },
    h("a", { classe: "bouton p", href: "https://discord.com/users/" + m.id }, icone("discord"), h("span", {}, "Profil Discord")),
    h("a", { classe: "bouton p", href: lienExport({ quoi: "membre", membre: m.id }), download: "" }, icone("exporter"), h("span", {}, "Exporter sa fiche")),
    m.clan ? bouton("Son affiche", { classe: "p", icone: "affiches", onclick: () => { pan.fermer(); aller("capitainerie", "affiches", "membre-" + m.id); } }) : null));
  if (f.alerte) corps.push(h("div", { classe: "bandeau rouge" }, icone("attention"), h("div", { classe: "bandeau-texte" },
    h("span", {}, h("b", {}, "Alerte en cours · "), quantite(f.alerte.incidents, "incident(s)") + " en 24 h."),
    h("div", { classe: "rangee" }, bouton("Marquer gérée", { classe: "p vert", icone: "valider", reseau: true, onclick: () => agir({ action: "alerte_geree", membre: m.id }, "Alerte gérée ?", "Elle disparaît des alertes ; son compteur repart de zéro.", {}, "Gérée", "vert") })))));
  if (f.agir && m.present && peutAgir()) {
    corps.push(h("div", { classe: "cadre pile serree" }, h("h3", {}, "Modérer"),
      h("p", { classe: "aide" }, "Même circuit que les commandes : fiche au casier, message privé au membre au nom du serveur, journal. Motif obligatoire."),
      h("div", { classe: "rangee" },
        bouton("Avertir", { classe: "p", reseau: true, onclick: () => moderer(m, "warn") }),
        m.mute_jusqu ? bouton("Lever le mute", { classe: "p vert", reseau: true, onclick: () => moderer(m, "unmute") }) : bouton("Muter", { classe: "p", reseau: true, onclick: () => moderer(m, "mute") }),
        bouton("Expulser", { classe: "p danger", reseau: true, onclick: () => moderer(m, "kick") }),
        bouton("Bannir", { classe: "p danger", reseau: true, onclick: () => moderer(m, "ban") }),
        m.clan ? bouton("Retirer du clan", { classe: "p danger", reseau: true, onclick: () => agir({ action: "clan_retirer", membre: m.id }, "Retirer " + nomDe(p) + " du clan ?", "Seul le rôle du clan lui est retiré, sur Discord.", {}, "Retirer du clan", "danger") }) : null)));
  } else if (m.protege && peutAgir()) corps.push(h("p", { classe: "aide" }, "Fondateur ou direction : protégé, aucune action possible depuis le site."));
  if (peutAgir() && !m.protege && (f.sanctions.length || (!m.present && m.banni))) {
    const warns = f.sanctions.filter((s) => s.type === "warn").length;
    corps.push(h("div", { classe: "cadre pile serree" }, h("h3", {}, "Casier"),
      h("p", { classe: "aide" }, "Effacé du casier et de ses effets sur Discord (compteurs du filtre, rôle de récidive" + (m.mute_jusqu ? ", mute en cours" : "") + "). Annulable pendant 30 jours, dans Sanctions."),
      h("div", { classe: "rangee" },
        warns ? bouton("Effacer ses avertissements · " + warns, { classe: "p", reseau: true, onclick: () => agir({ action: "casier_effacer", membre: m.id, quoi: "warns" }, "Effacer ses avertissements ?", quantite(warns, "avertissement(s)") + (warns > 1 ? " sortent" : " sort") + " du casier d'un coup. Annulable pendant 30 jours.", {}, "Effacer", "danger") }) : null,
        f.sanctions.length ? bouton("Effacer tout son casier", { classe: "p danger", reseau: true, onclick: () => agir({ action: "casier_effacer", membre: m.id, quoi: "tout" }, "Effacer tout son casier ?", quantite(f.sanctions.length, "entrée(s)") + "." + (m.mute_jusqu ? " Son mute en cours est levé." : "") + " Annulable pendant 30 jours.", {}, "Tout effacer", "danger") }) : null,
        !m.present && m.banni ? bouton("Lever le bannissement", { classe: "p vert", reseau: true, onclick: () => agir({ action: "debannir", membre: m.id }, "Lever son bannissement ?", "Il pourra revenir sur le serveur.", {}, "Débannir", "vert") }) : null)));
  }
  const enCours = ((etat.d && etat.d.en_cours) || []).some((c) => c.id === m.id);
  const nb = { chrono: null, sanctions: f.sanctions.length, tickets: f.tickets.length, candidatures: f.candidatures.length + (enCours ? 1 : 0),
    questions: f.questions.length, sondages: (f.sondages || []).length + (f.idees || []).length, journal: f.journal.length, donnees: f.donnees.length };
  const dispo = ONGLETS.filter(([k]) => k === "chrono" || nb[k]);
  if (!dispo.some(([k]) => k === etatFiche.onglet)) etatFiche.onglet = "chrono";
  corps.push(h("div", { classe: "onglets-fiche", role: "tablist", "aria-label": "Rubriques de la fiche" }, dispo.map(([k, l, ic]) => h("button", {
    classe: "etiquette", type: "button", role: "tab", "aria-selected": String(etatFiche.onglet === k),
    onclick: () => { etatFiche.onglet = k; etatFiche.max = 40; rendreFiche(); },
  }, icone(ic), l, nb[k] ? h("span", { classe: "compteur calme" }, String(nb[k])) : null))));
  corps.push(contenuOnglet(f, m, p));
  const haut = pan.corps.scrollTop;
  remplacer(pan.corps, ...corps.filter(Boolean));
  pan.corps.scrollTop = haut;
}
const miniTuile = (n, lib, onglet, fixe) => h("button", { classe: "mini-tuile", type: "button", onclick: () => { etatFiche.onglet = onglet; rendreFiche(); } },
  h("b", { classe: "num" }, nombre(n)), h("span", {}, fixe ? lib : lib + (n > 1 ? "s" : "")));
const info = (k, v) => h("div", { classe: "info" }, h("div", { classe: "k" }, k), h("div", { classe: "v" }, v));

async function moderer(m, sanction) {
  const p = P(m.id), noms = { warn: "Avertir", mute: "Muter", unmute: "Lever le mute de", kick: "Expulser", ban: "Bannir" };
  const textes = {
    warn: "Une fiche au casier et un message privé au nom du serveur. L'escalade automatique s'applique (3ᵉ avertissement : mute).",
    mute: "Il ne peut plus écrire ni parler pendant la durée choisie.", unmute: "Il peut de nouveau écrire et parler.",
    kick: "Il est expulsé du serveur ; il pourra revenir avec une invitation.", ban: "Il est banni du serveur. Irréversible depuis cette fiche (le débannissement reste possible).",
  };
  await agir({ action: "moderer", membre: m.id, sanction }, noms[sanction] + " " + nomDe(p) + " ?", textes[sanction],
    { motif: true, motifRequis: sanction !== "unmute", durees: sanction === "mute" }, noms[sanction].replace(" de", ""), ["kick", "ban"].includes(sanction) ? "danger" : "");
}

function chronologie(f) {
  const items = [];
  const tSanctions = f.sanctions.map((s) => s.date || 0);
  const proche = (t) => tSanctions.some((x) => Math.abs(x - t) < 120);
  f.sanctions.forEach((s) => items.push({ t: s.date, cat: s.libelle, teinte: teinteType(s.type), grave: ["kick", "ban"].includes(s.type),
    texte: s.libelle + (s.duree ? " · " + s.duree : "") + (s.raison ? " — " + s.raison : ""), meta: s.auto ? "Automatique" : "Par " + s.par }));
  f.tickets.forEach((t) => {
    items.push({ t: t.ouvert, cat: "Ticket", teinte: "#7a4b2a", texte: "Ticket #" + t.ticket + " ouvert · " + t.type, meta: t.pris_par ? "pris par " + t.pris_par : "" });
    if (t.ferme) items.push({ t: t.ferme, cat: "Ticket", teinte: "#7a4b2a", texte: "Ticket #" + t.ticket + " fermé" + (t.motif ? " — " + t.motif : ""), meta: t.ferme_par ? "par " + t.ferme_par : "", lien: t.transcript });
  });
  f.candidatures.forEach((c) => items.push({ t: c.ferme, cat: "Candidature", teinte: "#3f6b3a", texte: "Candidature fermée" + (c.raison ? " — " + c.raison : ""), lien: c.transcript }));
  f.questions.forEach((q) => items.push({ t: q.quand, cat: "Question", teinte: "#1f4e5a", texte: q.texte, meta: sansEmoji(q.salon) + " · " + (STATUTS_Q[q.statut] || [q.libelle])[0], lien: q.message }));
  (f.sondages || []).forEach((x) => items.push({ t: x.cree, cat: "Sondage", teinte: "#5e3a4e", texte: x.question, meta: sansEmoji(x.salon) + " · " + (STATUTS_S[x.statut] || [x.statut])[0] + " · " + quantite(x.total, "vote(s)"), lien: x.statut !== "retire" ? x.lien : "" }));
  (f.idees || []).forEach((x) => items.push({ t: x.cree, cat: "Idée", teinte: "#7a5a22", texte: x.titre, meta: sansEmoji(x.salon) + " · " + (STATUTS_I[x.statut] || [x.libelle])[0] + " · " + x.pour + " pour, " + x.contre + " contre", lien: x.retire_le ? "" : x.lien }));
  f.journal.forEach((e) => {
    if (/^(mod\.|ticket\.|question\.|sondage\.|suggestion\.)/.test(e.type || "") || (/^sec\./.test(e.type || "") && proche(e.quand))) return;
    items.push({ t: e.quand, cat: e.cat, teinte: teinteCat(e.cat), grave: e.gravite >= 2, texte: e.texte, meta: [e.auteur && e.auteur !== f.membre.id ? "par " + nomDe(P(e.auteur)) : "", sansEmoji(e.salon)].filter(Boolean).join(" · ") });
  });
  return items.filter((x) => x.t).sort((a, b) => b.t - a.t);
}

function parJour(items, rendreUn) {
  if (!items.length) return vide("Rien ici", "Rien de conservé pour cette personne.");
  const max = etatFiche.max, jours = new Map();
  items.slice(0, max).forEach((x) => { const k = cleJour(x.t); if (!jours.has(k)) jours.set(k, []); jours.get(k).push(x); });
  const fil = h("div", { classe: "fil" });
  for (const [k, l] of jours) ajouter(fil, [h("section", { classe: "jour" }, h("h3", { classe: "jour-titre" }, libelleJour(k)), h("ul", { classe: "entrees" }, l.map(rendreUn)))]);
  if (items.length > max) ajouter(fil, [h("div", { classe: "plus" }, bouton("Voir 40 de plus", { icone: "plus", onclick: () => { etatFiche.max += 40; rendreFiche(); } }),
    h("span", { classe: "compte" }, nombre(max) + " sur " + nombre(items.length)))]);
  return fil;
}
function entreeChrono(x) {
  return h("li", { classe: "entree" + (x.grave ? " grave" : ""), vars: { "--teinte": x.teinte } },
    h("div", { classe: "haut" }, h("span", { classe: "quoi" }, x.cat), h("span", { classe: "quand" }, heure(x.t))),
    h("div", { classe: "texte coupe3 deplier", onclick: deplier }, x.texte),
    x.meta ? h("div", { classe: "meta" }, x.meta) : null,
    x.lien ? h("div", {}, h("a", { classe: "bouton p discret", href: x.lien }, icone("lien"), h("span", {}, "Ouvrir"))) : null);
}

function contenuOnglet(f, m, p) {
  const o = etatFiche.onglet;
  if (o === "chrono") return parJour(chronologie(f), entreeChrono);
  if (o === "sanctions") return parJour(f.sanctions.map((s) => Object.assign({ t: s.date }, s)), (s) => h("li", { classe: "entree" + (["kick", "ban"].includes(s.type) ? " grave" : ""), vars: { "--teinte": teinteType(s.type) } },
    h("div", { classe: "haut" }, h("span", { classe: "quoi" }, s.libelle + (s.duree ? " · " + s.duree : "")), h("span", { classe: "quand" }, heure(s.date))),
    s.raison ? h("div", { classe: "texte" }, s.raison) : null, h("div", { classe: "meta" }, s.auto ? "Automatique" : "Par " + s.par),
    peutAgir() ? h("div", {}, bouton("Retirer du casier", { classe: "p danger", reseau: true, onclick: () => agir({ action: "sanction_retirer", sanction: s.sanction }, "Retirer cette sanction du casier ?", s.libelle + " — " + (s.raison || "sans motif") + ". Elle sort du casier.", {}, "Retirer", "danger") })) : null));
  if (o === "tickets") {
    const dernier = (f.tickets.slice().sort((a, b) => (b.ouvert || 0) - (a.ouvert || 0))[0] || {}).ticket;
    return parJour(f.tickets.map((x) => Object.assign({ t: x.ferme || x.ouvert }, x)), (x) => h("li", { classe: "entree" },
      h("div", { classe: "haut" }, h("span", { classe: "quoi" }, "#" + x.ticket + " · " + x.type), x.statut === "ouvert" ? tampon("Ouvert", "vert", true) : tampon("Fermé", "encre", true)),
      h("div", { classe: "texte" }, x.motif || (x.statut === "ouvert" ? "En cours" : "Sans motif")),
      h("div", { classe: "meta" }, "ouvert le " + date(x.ouvert, true) + (x.ferme ? " · fermé le " + date(x.ferme, true) + (x.ferme_par ? " par " + x.ferme_par : "") : "") + (x.pris_par ? " · pris par " + x.pris_par : "")),
      x.salon ? h("div", { classe: "rangee" }, h("a", { classe: "bouton p discret", href: x.salon }, icone("ouvrir"), h("span", {}, "Ouvrir le ticket sur Discord"))) : null,
      transcriptEnLigne(x.ticket, "Ticket #" + x.ticket + " · " + nomDe(p), x.ticket === dernier)));
  }
  if (o === "candidatures") return h("div", { classe: "pile" }, candidaturesFiche(f));
  if (o === "questions") return parJour(f.questions.map((q) => Object.assign({ t: q.quand }, q)), (q) => h("li", { classe: "entree" },
    h("div", { classe: "haut" }, h("span", { classe: "quoi" }, sansEmoji(q.salon)), h("span", { classe: "quand" }, heure(q.quand))), h("div", { classe: "texte" }, q.texte),
    h("div", { classe: "pastilles" }, pastille((STATUTS_Q[q.statut] || [q.libelle])[0], (STATUTS_Q[q.statut] || [])[1]), q.par ? h("span", { classe: "meta" }, "par " + q.par) : null),
    q.message ? h("div", {}, h("a", { classe: "bouton p discret", href: q.message }, icone("lien"), h("span", {}, "Voir sur Discord"))) : null));
  if (o === "sondages") return parJour([...(f.sondages || []).map((x) => Object.assign({ t: x.cree, _type: "sondage" }, x)), ...(f.idees || []).map((x) => Object.assign({ t: x.cree, _type: "idee" }, x))].sort((a, b) => b.t - a.t),
    (x) => x._type === "idee" ? entreeIdee(x) : entreeSondage(x));
  if (o === "journal") return parJour(f.journal.map((e) => Object.assign({ t: e.quand }, e)), (e) => entreeJournal(e, m.id));
  if (o === "donnees") return parJour(f.donnees.map((s) => Object.assign({ t: s.date }, s)), (s) => h("li", { classe: "entree", vars: { "--teinte": teinteType(s.type) } },
    h("div", { classe: "haut" }, h("span", { classe: "quoi" }, s.libelle + " · " + nomDe(P(s.id))), h("span", { classe: "quand" }, heure(s.date))),
    s.raison ? h("div", { classe: "texte" }, s.raison) : null));
  return vide("Rien ici");
}

export function sondageVotes(x) {
  const total = (x.comptes || []).reduce((a, n) => a + n, 0), max = Math.max(0, ...(x.comptes || [0]));
  return h("div", { classe: "votes" }, (x.choix || []).map((c, i) => {
    const n = (x.comptes || [])[i] || 0, pc = total ? Math.round(100 * n / total) : 0;
    return h("div", { classe: "vote" + (total && n === max ? " tete" : "") },
      h("div", { classe: "vote-haut" }, h("span", {}, c), h("b", { classe: "num" }, pc + " %", h("small", {}, nombre(n)))),
      h("span", { classe: "vote-fond" }, h("span", { classe: "vote-plein", vars: { "--pc": pc + "%" } })));
  }));
}
function entreeSondage(x) {
  const [lib, teinte] = STATUTS_S[x.statut] || [x.statut, null];
  return h("li", { classe: "entree", vars: { "--teinte": "#5e3a4e" } },
    h("div", { classe: "haut" }, h("span", { classe: "quoi" }, "Sondage · " + sansEmoji(x.salon)), h("span", { classe: "quand" }, heure(x.cree))),
    h("div", { classe: "texte titre-entree" }, x.question), sondageVotes(x),
    h("div", { classe: "pastilles" }, pastille(lib, teinte), h("span", { classe: "meta" }, quantite(x.total, "vote(s)") + (x.multiple ? " · plusieurs choix" : ""))));
}
function entreeIdee(x) {
  const [lib, teinte] = STATUTS_I[x.statut] || [x.libelle, null];
  return h("li", { classe: "entree", vars: { "--teinte": "#7a5a22" } },
    h("div", { classe: "haut" }, h("span", { classe: "quoi" }, "Idée n°" + x.id + " · " + sansEmoji(x.salon)), h("span", { classe: "quand" }, heure(x.cree))),
    h("div", { classe: "texte titre-entree" }, x.titre), x.details ? h("div", { classe: "texte coupe3 deplier", onclick: deplier }, x.details) : null,
    x.note ? h("div", { classe: "meta" }, "Réponse : " + x.note) : null,
    h("div", { classe: "pastilles" }, pastille(x.retire_le ? "Retirée du salon" : lib, x.retire_le ? "#4a5560" : teinte), h("span", { classe: "meta" }, x.pour + " pour · " + x.contre + " contre")));
}

function candidaturesFiche(f) {
  const blocs = [];
  const enCours = ((etat.d && etat.d.en_cours) || []).find((c) => c.id === f.membre.id);
  if (enCours) blocs.push(h("div", { classe: "cadre pile serree" }, h("h3", {}, "Candidature en cours · ticket #" + enCours.ticket),
    h("p", { classe: "aide" }, "Ouverte " + depuis(enCours.ouvert) + (enCours.pris_par ? " · prise par " + enCours.pris_par : " · pas encore prise") + "."),
    h("div", { classe: "rangee" }, bouton("Ouvrir le dossier de recrutement", { classe: "p principal", icone: "candidatures", onclick: () => { etatFiche.pan.fermer(); emettre("dossier:ouvrir", enCours.ticket); } }),
      enCours.salon ? h("a", { classe: "bouton p", href: enCours.salon }, icone("ouvrir"), h("span", {}, "Ouvrir le ticket")) : null),
    reponses(enCours.reponses), transcriptEnLigne(enCours.ticket, "Candidature · ticket #" + enCours.ticket, false)));
  const fiche = ((etat.d && etat.d.candidats) || []).find((c) => c.id === f.membre.id);
  if (fiche) blocs.push(h("div", { classe: "cadre pile serree" }, h("h3", {}, "Dernière décision : " + (STATUTS_CAND[fiche.statut] || [fiche.statut])[0]),
    h("p", { classe: "aide" }, "Fermée le " + date(fiche.ferme, true) + (fiche.ferme_par ? " par " + fiche.ferme_par : "") + (fiche.motif ? " — " + fiche.motif : "")),
    reponses(fiche.reponses),
    peutAgir() ? h("div", { classe: "rangee" }, bouton("Retirer ses fiches", { classe: "p danger", reseau: true, onclick: () => agir({ action: "fiche_retirer", candidat: fiche.id }, "Retirer ses fiches de candidature ?", "Elles disparaissent du site. Les transcripts restent.", {}, "Retirer", "danger") })) : null,
    transcriptEnLigne(fiche.ticket, "Candidature · ticket #" + fiche.ticket, true)));
  f.candidatures.forEach((c) => blocs.push(h("div", { classe: "entree" }, h("div", { classe: "haut" }, h("span", { classe: "quoi" }, "Ticket #" + c.ticket), h("span", { classe: "quand" }, date(c.ferme, true))),
    h("div", { classe: "texte" }, c.raison || "Sans motif"), fiche && fiche.ticket === c.ticket ? null : transcriptEnLigne(c.ticket, "Candidature · ticket #" + c.ticket, false))));
  return blocs.length ? blocs : [vide("Aucune candidature")];
}

export function reponses(paires) {
  return (paires || []).length
    ? h("dl", { classe: "reponses" }, paires.map(([q, r]) => h("div", { classe: "reponse" }, h("dt", {}, q), h("dd", {}, r || h("i", {}, "Sans réponse")))))
    : h("p", { classe: "aide" }, "Formulaire non rempli.");
}

// ─── La conversation d'un ticket ────────────────────────────────────────────
const ETAPES = { create: ["ouvrir", "Ouvert"], claim: ["personne", "Pris en charge"], close: ["cadenas", "Fermé"], add_staff: ["ajouter", "Staff ajouté"],
  priority: ["drapeau", "Priorité"], note: ["plume", "Note interne"], leave: ["deconnexion", "A quitté le ticket"], blacklist: ["attention", "Blacklisté"] };
const memoire = new Map();
export async function lireConversation(ticket) {
  const m = memoire.get(ticket);
  if (m && Date.now() - m.t < 60000) return m.d;
  const r = await lire("conversation", { ticket });
  if (!r.ok) return { erreur: r.status === 0 ? "Hors ligne : ce transcript n'a pas encore été ouvert sur cet appareil." : r.erreur || "Transcript indisponible." };
  memoire.set(ticket, { t: Date.now(), d: r.donnees });
  return r.donnees;
}
function imageConv(u) {
  const s = srcSure(u);
  if (s) return h("img", { src: s, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
  return /^https:\/\//.test(u) ? h("a", { classe: "bouton p", href: u }, icone("lien"), h("span", {}, "Image")) : null;
}
function messageConv(m) {
  const liens = [...(m.videos || []).map((u) => ({ nom: "Vidéo", url: u })), ...(m.fichiers || [])].filter((f) => /^https:\/\//.test(f.url || ""));
  return h("article", { classe: "conv-msg" },
    m.avatar && srcSure(m.avatar) ? h("img", { classe: "conv-av", src: m.avatar, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("span", { classe: "conv-av" }, (m.auteur || "?").slice(0, 1).toUpperCase()),
    h("div", { classe: "conv-corps" },
      h("div", { classe: "conv-haut" }, h("b", {}, sansEmoji(m.auteur) || "?"), m.bot ? h("span", { classe: "conv-bot" }, "Robot") : null, h("span", { classe: "quand" }, m.quand ? date(m.quand, true) : "")),
      m.texte ? h("div", { classe: "conv-texte" }, m.texte) : null,
      (m.embeds || []).map((e) => h("div", { classe: "conv-embed" }, e.titre ? h("b", {}, e.titre) : null, e.texte || null,
        (e.champs || []).map(([n, v]) => h("div", { classe: "conv-champ" }, h("span", {}, n), v)), e.pied ? h("div", { classe: "meta" }, e.pied) : null)),
      (m.images || []).length ? h("div", { classe: "conv-medias" }, m.images.map(imageConv)) : null,
      liens.length ? h("div", { classe: "rangee" }, liens.map((f) => h("a", { classe: "bouton p", href: f.url }, icone("lien"), h("span", {}, f.nom)))) : null));
}
function suiviConv(d) {
  const ev = d.suivi || [];
  if (!ev.length) return null;
  return h("div", { classe: "conv-suivi" }, h("b", { classe: "conv-suivi-titre" }, "Suivi du ticket"), ev.map((e) => {
    const [ic, lib] = ETAPES[e.quoi] || ["info", e.quoi];
    return h("div", { classe: "conv-etape" }, icone(ic, "ic-p"), h("b", {}, lib), e.qui ? h("span", {}, " par " + e.qui) : null, h("span", { classe: "quand" }, " · " + date(e.quand, true)),
      e.detail ? h("div", { classe: "meta" }, e.detail) : null);
  }));
}
const resume = (d) => d.absent || (quantite((d.messages || []).length, "message(s)") + " · " + (d.source === "discord" ? "en direct de Discord" : "transcript enregistré à la fermeture"));

export async function ouvrirConversation(ticket, titre) {
  const p = pancarte({ titre, sous: "Chargement du transcript…", icone: "tickets", taille: "large" });
  ajouter(p.corps, [squelettes(3)]);
  ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
  const d = await lireConversation(ticket);
  if (p.fermee()) return;
  const sous = p.titre.querySelector(".sous-titre");
  if (d.erreur) { sous.textContent = d.erreur; remplacer(p.corps, vide("Transcript indisponible", d.erreur, "attention")); return; }
  sous.textContent = resume(d);
  const msgs = d.messages || [];
  const suivi = suiviConv(d);
  remplacer(p.corps, ...(suivi ? [suivi] : []), h("div", { classe: "conv-liste" }, msgs.length ? msgs.map(messageConv) : vide(d.absent ? "Pas de transcript" : "Aucun message")));
  if (d.lien && /^https:\/\//.test(d.lien)) p.pied.prepend(h("a", { classe: "bouton p gauche", href: d.lien }, icone("lien"), h("span", {}, "Page du transcript")));
}

const deplies = new Set();
export function transcriptEnLigne(ticket, titre, ouvert) {
  const bascule = h("button", { classe: "bouton p", type: "button", "aria-expanded": "false" });
  const outils = h("div", { classe: "rangee" }, bascule);
  const meta = h("p", { classe: "aide" });
  const liste_ = h("div", { classe: "conv-liste enligne" });
  const bloc = h("div", { classe: "conv-bloc" }, outils, meta, liste_);
  let charge = false;
  const masquer = () => { deplies.delete(ticket); liste_.hidden = meta.hidden = true; remplacer(bascule, icone("tickets"), h("span", {}, "Transcript complet")); bascule.setAttribute("aria-expanded", "false"); };
  const montrer = async () => {
    deplies.add(ticket); liste_.hidden = meta.hidden = false;
    remplacer(bascule, icone("tickets"), h("span", {}, "Masquer le transcript")); bascule.setAttribute("aria-expanded", "true");
    if (charge) return;
    charge = true;
    meta.textContent = "Chargement du transcript…";
    remplacer(liste_, squelettes(2));
    const d = await lireConversation(ticket);
    if (!bloc.isConnected) return;
    if (d.erreur) { charge = false; remplacer(meta, d.erreur + " ", bouton("Réessayer", { classe: "p", onclick: () => montrer() })); remplacer(liste_); return; }
    meta.textContent = resume(d);
    const suivi = suiviConv(d);
    remplacer(liste_, ...(suivi ? [suivi] : []), ...(d.messages || []).map(messageConv));
    ajouter(outils, [bouton("Agrandir", { classe: "p discret", icone: "ouvrir", onclick: () => ouvrirConversation(ticket, titre) })]);
    if (d.lien && /^https:\/\//.test(d.lien)) ajouter(outils, [h("a", { classe: "bouton p discret", href: d.lien }, icone("lien"), h("span", {}, "Page du transcript"))]);
  };
  bascule.addEventListener("click", () => { if (liste_.hidden) montrer(); else masquer(); });
  if (ouvert || deplies.has(ticket)) montrer(); else masquer();
  return bloc;
}
