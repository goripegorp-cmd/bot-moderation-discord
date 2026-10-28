// fiche.js — la fiche d'une personne (tout ce qui la concerne) et la conversation complète d'un ticket.
// Aussi : couleurs, libellés et entrées partagés par les rubriques.

import { h, icone, date, heure, depuis, dans, duree, nombre, cleJour, libelleJour, sansEmoji, maintenant, srcSure, BASE, remplacer, quantite, ajouter } from "./dom.js";
import { etat, P, peutAgir, retenirPersonnes, poserAncre, aller, emettre, nommerOnglets } from "./noyau.js";
import { lire, action as envoyerAction, lienExport } from "./api.js";
import { charger, vue as vueJeu } from "./donnees.js";
import { pancarte, confirmer, bouton, avatar, pastille, tampon, vide, squelettes, boutonCopie, nomDe, lienNom, toast, liste, champ, zoneTexte } from "./ui.js";
import { ligne, groupesParJours, outilsGroupes } from "./rangement.js";
import { ligneEquipe } from "./equipes_admin.js";
import { blocTickets } from "./tickets_interdits.js";

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
/** Un salon tel que le serveur l'écrit (« # », un émoji, « ・ », puis le nom) : « #annonces » — ni émoji ni séparateur
 *  décoratif, même derrière le dièse (sansEmoji ne nettoie que le début du texte, et le dièse y est). */
export function nomSalon(s) {
  const t = String(s || "").trim();
  const diese = t.startsWith("#");
  const n = sansEmoji(diese ? t.slice(1) : t);
  return n ? (diese ? "#" + n : n) : "";
}
/** Du plus récent au plus ancien, sans toucher à la liste reçue (`quand` absent : à la fin). */
/** Un nom ou un libellé venu de Discord (pseudo, type de ticket) : sans émoji ni décor ; tel quel s'il n'est fait que de
 *  cela (mieux qu'un vide). */
export const propre = (s) => sansEmoji(s) || String(s ?? "");
export const recentsDabord = (l, cle) => (l || []).slice().sort((a, b) => (Number(b[cle]) || 0) - (Number(a[cle]) || 0));

// ─── L'étape d'une candidature en cours ─────────────────────────────────────
// `donnees` ne porte pas l'étape des candidatures en cours : le serveur la tient dans le suivi du recrutement
// (`api/recrutement/suivi` : « etape1 », « etape2 » questionnaire envoyé, « reponses » à corriger). Sans suivi lisible
// (hors ligne, serveur plus ancien), les champs de la candidature servent (`etape`, `recrutement`).
export const SUIVI_RECRUTEMENT = "recrutement/suivi";
export const chargerSuivi = (forcer) => charger(SUIVI_RECRUTEMENT, { forcer: !!forcer });
export const ETAPES_CANDIDATURE = { decider: ["Étape 1 à décider", "ambre"], attente: ["Étape 2 en cours", "mer"],
  corriger: ["Étape 2 à corriger", "ambre"], decidee: ["Décidée · fermeture prévue", "encre"] };
/** « decider » (questionnaire d'ouverture à juger), « attente » (questionnaire envoyé, pas encore de réponse),
 *  « corriger » (réponses arrivées) ou « decidee » (décision prise, le ticket se ferme bientôt). */
export function etapeCandidature(c) {
  const v = vueJeu(SUIVI_RECRUTEMENT);
  const s = v && Array.isArray(v.ouverts) ? v.ouverts.find((o) => String(o.ticket) === String(c && c.ticket)) : null;
  const texte = String((s && s.etape) || (c && (c.recrutement || c.etape)) || "");
  if ((s && s.fermeture_prevue) || /accepte|refus|ferme/.test(texte)) return "decidee";
  if (/reponse|partiel|corrig/.test(texte)) return "corriger";
  if (/etape2|attente|envoy/.test(texte) || Number(c && c.etape) === 2) return "attente";
  return "decider";
}

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
    a || e.salon ? h("div", { classe: "meta" }, a ? ["par ", lienNom(a, ouvrir || ouvrirFiche)] : null, a && e.salon ? " · " : null, e.salon ? nomSalon(e.salon) || e.salon : null) : null);
}

/** Une ligne compacte du journal : l'heure, le texte sur une ligne, la catégorie et qui ; le texte complet au clic.
 *  sujet : la personne de la fiche (ni nommée ni liée) ; avecDate : le jour à droite (listes de plusieurs jours). */
export function ligneJournal(e, sujet, avecDate) {
  const a = e.auteur && e.auteur !== e.membre && e.auteur !== sujet ? e.auteur : null;
  const m = e.membre && e.membre !== sujet ? e.membre : null;
  const grave = e.gravite >= 2;
  return ligne({
    visuel: h("span", { classe: "lc-heure" }, heure(e.quand)), titre: e.texte || e.cat,
    sous: [h("span", { classe: "lc-cat", vars: { "--teinte": teinteCat(e.cat) } }, e.cat), m ? [" · ", lienNom(m, ouvrirFiche)] : null,
      a ? [" · par ", lienNom(a, ouvrirFiche)] : null, e.salon ? " · " + (nomSalon(e.salon) || e.salon) : null],
    badges: grave ? [pastille("Grave", "#8e2a24")] : [], teinte: grave ? "#8e2a24" : teinteCat(e.cat),
    date: avecDate ? libelleJour(cleJour(e.quand)) : "", dateTitre: avecDate ? date(e.quand, true) : "",
    deplier: () => [h("p", { classe: "texte" }, e.texte), e.detail ? h("p", { classe: "meta" }, e.detail) : null, h("p", { classe: "meta" }, date(e.quand, true))],
  });
}

// ─── La fiche ───────────────────────────────────────────────────────────────
const ONGLETS = nommerOnglets("site.fiche.onglet", [["chrono", "Chronologie", "journal"], ["sanctions", "Sanctions", "sanctions"], ["tickets", "Tickets", "tickets"],
  ["candidatures", "Candidatures", "candidatures"], ["questions", "Questions", "salons"], ["sondages", "Sondages et idées", "salons"],
  ["journal", "Journal", "parchemin"], ["donnees", "Décidées par lui", "plume"]]);
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
    m.restreint ? pastille("Restreint par la direction", "#5e3a4e") : null,
    !m.present ? pastille(m.banni ? "Banni" : "A quitté le serveur", m.banni ? "#8e2a24" : "#4a5560") : null,
    f.alerte ? pastille("Alerte en cours", "#8e2a24") : null,
    m.bot ? pastille("Robot", "#4a5560") : null,
  ].filter(Boolean);
  const corps = [];
  const chef = h("div", { classe: "rangee fiche-chef" });   // « Chef d'équipe · <métier> » (recrutement_chefs.js)
  emettre("fiche:rendue", { membre: m, zone: chef });
  if (etatFiche.horsLigne) corps.push(h("p", { classe: "aide" }, icone("hors_ligne", "ic-p"), " Fiche lue dans la mémoire de l'appareil (hors ligne)."));
  // L'identité, ramassée (le nom est dans le titre de la fenêtre) : ce qui la distingue, depuis quand, ses rôles, ses liens.
  corps.push(h("div", { classe: "fiche-entete" },
    avatar(p, "g"),
    h("div", { classe: "fiche-ident" },
      pastilles_.length ? h("div", { classe: "pastilles" }, pastilles_) : null, chef,
      h("div", { classe: "sous-nom" }, [m.present ? "Sur le serveur depuis le " + date(m.arrivee) : m.banni ? "Banni du serveur" : "A quitté le serveur",
        m.cree ? "compte Discord créé le " + date(m.cree) : ""].filter(Boolean).join(" · "), h("span", { classe: "ident" }, " · " + p.id), boutonCopie(p.id, "Identifiant copié")),
      m.roles && m.roles.length ? h("div", { classe: "pastilles fiche-roles", title: "Rôles sur Discord (lecture seule)" },
        m.roles.slice(0, 8).map((r) => pastille(sansEmoji(r.nom) || "Rôle", r.couleur || null)), m.roles.length > 8 ? pastille("+" + (m.roles.length - 8), null, m.roles.slice(8).map((r) => sansEmoji(r.nom)).join(", "), true) : null) : null,
      m.clan ? ligneEquipe(m.id) : null,   // 27/10/2026 : « Équipe : … (chef : …) » (equipes_admin.js)
      h("div", { classe: "rangee fiche-liens" },
        h("a", { classe: "bouton p", href: "https://discord.com/users/" + m.id }, icone("discord"), h("span", {}, "Profil Discord")),
        h("a", { classe: "bouton p discret avance", href: lienExport({ quoi: "membre", membre: m.id }), download: "" }, icone("exporter"), h("span", {}, "Exporter sa fiche")),
        m.clan ? bouton("Son affiche", { classe: "p discret", icone: "affiches", onclick: () => { pan.fermer(); aller("capitainerie", "affiches", "membre-" + m.id); } }) : null))));
  if (m.restreint) corps.push(bandeauRestreint(m.restreint));
  if (f.alerte) corps.push(h("div", { classe: "bandeau rouge" }, icone("attention"), h("div", { classe: "bandeau-texte" },
    h("span", {}, h("b", {}, "Alerte en cours · "), quantite(f.alerte.incidents, "incident(s)") + " en 24 h."),
    h("div", { classe: "rangee" }, bouton("Marquer gérée", { classe: "p vert", icone: "valider", reseau: true, onclick: () => agir({ action: "alerte_geree", membre: m.id }, "Alerte gérée ?", "Elle disparaît des alertes ; son compteur repart de zéro.", {}, "Gérée", "vert") })))));
  // Agir : une ligne pour sanctionner, une pour le casier — en haut de la fiche, jamais sous le pli ni sous le pied.
  const lignesAgir = [];
  if (f.agir && m.present && peutAgir()) {
    lignesAgir.push(h("div", { classe: "fiche-agir-ligne" }, h("span", { classe: "champ-lib" }, "Sanctionner"), h("div", { classe: "rangee" },
      bouton("Avertir", { classe: "p", icone: "plume", reseau: true, onclick: () => moderer(m, "warn") }),
      m.mute_jusqu ? bouton("Lever le mute", { classe: "p vert", icone: "valider", reseau: true, onclick: () => moderer(m, "unmute") }) : bouton("Muter", { classe: "p", icone: "minuteur", reseau: true, onclick: () => moderer(m, "mute") }),
      bouton("Expulser", { classe: "p danger", icone: "deconnexion", reseau: true, onclick: () => moderer(m, "kick") }),
      bouton("Bannir", { classe: "p danger", icone: "sabre", reseau: true, onclick: () => moderer(m, "ban") }),
      m.clan ? bouton("Retirer du clan", { classe: "p danger", icone: "equipage", reseau: true, onclick: () => agir({ action: "clan_retirer", membre: m.id }, "Retirer " + nomDe(p) + " du clan ?", "Seul le rôle du clan lui est retiré, sur Discord.", {}, "Retirer du clan", "danger") }) : null)));
  } else if (m.protege && peutAgir()) corps.push(h("p", { classe: "aide" }, "Fondateur ou direction : protégé, aucune action possible depuis le site."));
  if (peutAgir() && !m.protege && (f.sanctions.length || (!m.present && m.banni))) {
    const warns = f.sanctions.filter((s) => s.type === "warn").length;
    lignesAgir.push(h("div", { classe: "fiche-agir-ligne" }, h("span", { classe: "champ-lib" }, "Casier"), h("div", { classe: "rangee" },
      warns ? bouton("Effacer ses avertissements · " + warns, { classe: "p", icone: "nettoyage", reseau: true, onclick: () => agir({ action: "casier_effacer", membre: m.id, quoi: "warns" }, "Effacer ses avertissements ?", quantite(warns, "avertissement(s)") + (warns > 1 ? " sortent" : " sort") + " du casier d'un coup. Annulable pendant 30 jours.", {}, "Effacer", "danger") }) : null,
      f.sanctions.length ? bouton("Effacer tout son casier", { classe: "p danger", icone: "supprimer", reseau: true, onclick: () => agir({ action: "casier_effacer", membre: m.id, quoi: "tout" }, "Effacer tout son casier ?", quantite(f.sanctions.length, "entrée(s)") + "." + (m.mute_jusqu ? " Son mute en cours est levé." : "") + " Annulable pendant 30 jours.", {}, "Tout effacer", "danger") }) : null,
      !m.present && m.banni ? bouton("Lever le bannissement", { classe: "p vert", icone: "valider", reseau: true, onclick: () => agir({ action: "debannir", membre: m.id }, "Lever son bannissement ?", "Il pourra revenir sur le serveur.", {}, "Débannir", "vert") }) : null)));
  }
  if (lignesAgir.length) corps.push(h("div", { classe: "cadre pile serree fiche-agir" }, ...lignesAgir,
    h("p", { classe: "aide avance" }, "Même circuit que les commandes : fiche au casier, message privé au membre au nom du serveur, journal ; motif obligatoire. Un casier effacé se rétablit pendant 30 jours, dans Sanctions.")));
  corps.push(blocTickets(m));   // 27/10/2026 : « Tickets » — ce qui lui est interdit, sous les sanctions (tickets_interdits.js)
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
/** Restreint par la direction (/direction : `restricted_members`) : depuis quand, par qui, pourquoi, jusqu'à quand. */
function bandeauRestreint(r) {
  const fin = r.duree && r.depuis ? r.depuis + r.duree * 60 : 0;   // la durée est en MINUTES (bot.py)
  return h("div", { classe: "bandeau restreint", role: "status" }, icone("cadenas"), h("div", { classe: "bandeau-texte" },
    h("span", {}, h("b", {}, "Restreint par la direction"), r.depuis ? " depuis le " + date(r.depuis, true) + " (" + depuis(r.depuis) + ")" : "",
      r.par ? ", par " + nomDe(P(r.par)) : "", "."),
    h("span", {}, r.raison ? "Motif : " + r.raison + ". " : "Sans motif noté. ", fin ? (fin > maintenant() ? "Fin prévue " + dans(fin) + " (le " + date(fin, true) + ")." : "Durée écoulée : la levée est en cours.") : "Sans fin prévue : la direction la lève à la main.")));
}

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
    texte: s.libelle + (s.duree ? " · " + s.duree : "") + (s.raison ? " — " + s.raison : ""), meta: s.auto ? "Automatique" : "Par " + propre(s.par) }));
  f.tickets.forEach((t) => {
    items.push({ t: t.ouvert, cat: "Ticket", teinte: "#7a4b2a", texte: "Ticket #" + t.ticket + " ouvert · " + propre(t.type), meta: t.pris_par ? "pris par " + propre(t.pris_par) : "" });
    if (t.ferme) items.push({ t: t.ferme, cat: "Ticket", teinte: "#7a4b2a", texte: "Ticket #" + t.ticket + " fermé" + (t.motif ? " — " + t.motif : ""), meta: t.ferme_par ? "par " + propre(t.ferme_par) : "", lien: t.transcript });
  });
  f.candidatures.forEach((c) => items.push({ t: c.ferme, cat: "Candidature", teinte: "#3f6b3a", texte: "Candidature fermée" + (c.raison ? " — " + c.raison : ""), lien: c.transcript }));
  f.questions.forEach((q) => items.push({ t: q.quand, cat: "Question", teinte: "#1f4e5a", texte: q.texte, meta: nomSalon(q.salon) + " · " + (STATUTS_Q[q.statut] || [q.libelle])[0], lien: q.message }));
  (f.sondages || []).forEach((x) => items.push({ t: x.cree, cat: "Sondage", teinte: "#5e3a4e", texte: x.question, meta: nomSalon(x.salon) + " · " + (STATUTS_S[x.statut] || [x.statut])[0] + " · " + quantite(x.total, "vote(s)"), lien: x.statut !== "retire" ? x.lien : "" }));
  (f.idees || []).forEach((x) => items.push({ t: x.cree, cat: "Idée", teinte: "#7a5a22", texte: x.titre, meta: nomSalon(x.salon) + " · " + (STATUTS_I[x.statut] || [x.libelle])[0] + " · " + x.pour + " pour, " + x.contre + " contre", lien: x.retire_le ? "" : x.lien }));
  f.journal.forEach((e) => {
    if (/^(mod\.|ticket\.|question\.|sondage\.|suggestion\.)/.test(e.type || "") || (/^sec\./.test(e.type || "") && proche(e.quand))) return;
    items.push({ t: e.quand, cat: e.cat, teinte: teinteCat(e.cat), grave: e.gravite >= 2, texte: e.texte, meta: [e.auteur && e.auteur !== f.membre.id ? "par " + nomDe(P(e.auteur)) : "", nomSalon(e.salon)].filter(Boolean).join(" · ") });
  });
  return items.filter((x) => x.t).sort((a, b) => b.t - a.t);
}

/** L'historique d'un onglet de la fiche : un groupe par jour (aujourd'hui, hier, vendredi 23…), puis par semaine et par
 *  mois, chacun avec son compte ; le plus récent ouvert, les autres fermés ; une ligne par élément, « Voir plus » par 20. */
function parJour(items, rendreUn) {
  if (!items.length) return vide("Rien ici", "Rien de conservé pour cette personne.");
  items = recentsDabord(items, "t");
  const zone = h("div", { classe: "groupes-zone" }, groupesParJours("fiche-" + etatFiche.id + "-" + etatFiche.onglet, items, (x) => x.t, rendreUn, { ouverts: 1 }));
  return h("div", { classe: "pile serree" }, items.length > 20 ? h("div", { classe: "rangee droite" }, outilsGroupes(zone)) : null, zone);
}
const heureL = (t) => h("span", { classe: "lc-heure" }, heure(t));
function entreeChrono(x) {
  return ligne({
    visuel: heureL(x.t), titre: x.texte, sous: [h("span", { classe: "lc-cat", vars: { "--teinte": x.teinte } }, x.cat), x.meta ? " · " + x.meta : ""],
    teinte: x.grave ? "#8e2a24" : x.teinte, badges: x.grave ? [pastille("Grave", "#8e2a24")] : [],
    actions: [x.lien ? { icone: "lien", libelle: "Ouvrir", href: x.lien } : null], deplier: () => [h("p", { classe: "texte" }, x.texte), x.meta ? h("p", { classe: "meta" }, x.meta) : null],
  });
}

function contenuOnglet(f, m, p) {
  const o = etatFiche.onglet;
  if (o === "chrono") return parJour(chronologie(f), entreeChrono);
  if (o === "sanctions") return parJour(f.sanctions.map((s) => Object.assign({ t: s.date }, s)), (s) => ligne({
    visuel: heureL(s.date), titre: s.libelle + (s.duree ? " · " + s.duree : "") + (s.raison ? " — " + s.raison : ""), sous: s.auto ? "Automatique" : "Par " + propre(s.par),
    teinte: teinteType(s.type), etat: ["kick", "ban"].includes(s.type) ? "alerte" : null, deplier: s.raison ? () => h("p", { classe: "texte" }, s.raison) : undefined,
    actions: [peutAgir() ? { icone: "supprimer", libelle: "Retirer du casier", danger: true, reseau: true,
      onclick: () => agir({ action: "sanction_retirer", sanction: s.sanction }, "Retirer cette sanction du casier ?", s.libelle + " — " + (s.raison || "sans motif") + ". Elle sort du casier.", {}, "Retirer", "danger") } : null],
  }));
  if (o === "tickets") return parJour(f.tickets.map((x) => Object.assign({ t: x.ferme || x.ouvert }, x)), (x) => {
    const conv = () => ouvrirConversation(x.ticket, "Ticket #" + x.ticket + " · " + nomDe(p));
    return ligne({
      visuel: heureL(x.t), titre: "#" + x.ticket + " · " + propre(x.type) + " — " + (x.motif || (x.statut === "ouvert" ? "en cours" : "sans motif")),
      sous: "ouvert le " + date(x.ouvert, true) + (x.ferme ? " · fermé le " + date(x.ferme, true) + (x.ferme_par ? " par " + propre(x.ferme_par) : "") : "") + (x.pris_par ? " · pris par " + propre(x.pris_par) : ""),
      badges: [x.statut === "ouvert" ? tampon("Ouvert", "vert", true) : tampon("Fermé", "encre", true)],
      actions: [{ icone: "parchemin", libelle: "Conversation", onclick: conv }, x.salon ? { icone: "discord", libelle: "Ouvrir le ticket sur Discord", href: x.salon } : null],
      ouvrir: conv, libelleOuvrir: "Conversation du ticket #" + x.ticket,
    });
  });
  if (o === "candidatures") return h("div", { classe: "pile" }, candidaturesFiche(f));
  if (o === "questions") return parJour(f.questions.map((q) => Object.assign({ t: q.quand }, q)), (q) => ligne({
    visuel: heureL(q.quand), titre: q.texte, sous: nomSalon(q.salon) + (q.par ? " · répondu par " + propre(q.par) : ""),
    badges: [pastille((STATUTS_Q[q.statut] || [q.libelle])[0], (STATUTS_Q[q.statut] || [])[1])],
    actions: [q.message ? { icone: "discord", libelle: "Voir sur Discord", href: q.message } : null], deplier: () => h("p", { classe: "texte" }, q.texte),
  }));
  if (o === "sondages") return parJour([...(f.sondages || []).map((x) => Object.assign({ t: x.cree, _type: "sondage" }, x)), ...(f.idees || []).map((x) => Object.assign({ t: x.cree, _type: "idee" }, x))].sort((a, b) => b.t - a.t),
    (x) => x._type === "idee" ? entreeIdee(x) : entreeSondage(x));
  if (o === "journal") return parJour(f.journal.map((e) => Object.assign({ t: e.quand }, e)), (e) => ligneJournal(e, m.id));
  if (o === "donnees") return parJour(f.donnees.map((s) => Object.assign({ t: s.date }, s)), (s) => ligne({
    visuel: heureL(s.date), titre: s.libelle + " · " + nomDe(P(s.id)), sous: s.raison || "Sans motif", teinte: teinteType(s.type),
    ouvrir: () => ouvrirFiche(s.id, "sanctions"), libelleOuvrir: "Ouvrir la fiche de " + nomDe(P(s.id)),
  }));
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
  return ligne({
    visuel: heureL(x.cree), titre: x.question, sous: "Sondage · " + nomSalon(x.salon) + " · " + quantite(x.total, "vote(s)") + (x.multiple ? " · plusieurs choix" : ""),
    badges: [pastille(lib, teinte)], teinte: "#5e3a4e", deplier: () => sondageVotes(x),
  });
}
function entreeIdee(x) {
  const [lib, teinte] = STATUTS_I[x.statut] || [x.libelle, null];
  return ligne({
    visuel: heureL(x.cree), titre: x.titre, sous: "Idée n°" + x.id + " · " + nomSalon(x.salon) + " · " + x.pour + " pour · " + x.contre + " contre",
    badges: [pastille(x.retire_le ? "Retirée du salon" : lib, x.retire_le ? "#4a5560" : teinte)], teinte: "#7a5a22",
    deplier: () => [x.details ? h("p", { classe: "texte" }, x.details) : null, x.note ? h("p", { classe: "meta" }, "Réponse : " + x.note) : null],
  });
}

function candidaturesFiche(f) {
  const blocs = [];
  const enCours = ((etat.d && etat.d.en_cours) || []).find((c) => c.id === f.membre.id);
  if (enCours) blocs.push(h("div", { classe: "cadre pile serree" }, h("div", { classe: "rangee entre" },
    h("h3", {}, "Candidature en cours · ticket #" + enCours.ticket), tampon(...ETAPES_CANDIDATURE[etapeCandidature(enCours)])),
    h("p", { classe: "aide" }, "Ouverte " + depuis(enCours.ouvert) + (enCours.pris_par ? " · prise par " + propre(enCours.pris_par) : " · pas encore prise") + "."),
    h("div", { classe: "rangee" }, bouton("Ouvrir le dossier de recrutement", { classe: "p principal", icone: "candidatures", onclick: () => { etatFiche.pan.fermer(); emettre("dossier:ouvrir", enCours.ticket); } }),
      enCours.salon ? h("a", { classe: "bouton p", href: enCours.salon }, icone("ouvrir"), h("span", {}, "Ouvrir le ticket")) : null),
    reponses(enCours.reponses), transcriptEnLigne(enCours.ticket, "Candidature · ticket #" + enCours.ticket, false)));
  //  27/10/2026 : sa dernière décision vient de SA fiche (le serveur la lit à l'ouverture) ; `donnees` ne porte plus que
  //  le résumé des dernières candidatures décidées.
  const fiche = (f.candidatures || []).find((c) => c.statut === "acceptes" || c.statut === "refuses");
  if (fiche) blocs.push(h("div", { classe: "cadre pile serree" }, h("h3", {}, "Dernière décision : " + STATUTS_CAND[fiche.statut][0]),
    h("p", { classe: "aide" }, "Fermée le " + date(fiche.ferme, true) + (fiche.ferme_par ? " par " + propre(fiche.ferme_par) : "") + (fiche.raison ? " — " + fiche.raison : "")),
    reponses(fiche.reponses),
    peutAgir() ? h("div", { classe: "rangee" }, bouton("Retirer ses fiches", { classe: "p danger", reseau: true, onclick: () => agir({ action: "fiche_retirer", candidat: f.membre.id }, "Retirer ses fiches de candidature ?", "Elles disparaissent du site. Les transcripts restent.", {}, "Retirer", "danger") })) : null,
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
    return h("div", { classe: "conv-etape" }, icone(ic, "ic-p"), h("b", {}, lib), e.qui ? h("span", {}, " par " + propre(e.qui)) : null, h("span", { classe: "quand" }, " · " + date(e.quand, true)),
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
