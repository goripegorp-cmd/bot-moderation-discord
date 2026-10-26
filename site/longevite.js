// longevite.js — le site sur plusieurs années (26/10/2026).
//
// « Est-ce qu'il peut tenir le coup sur plusieurs années ? » Les données de la page (`donnees`) ne portent que le
// début des longues listes : les 400 derniers évènements du journal, les 300 derniers tickets fermés, les 250
// personnes les plus récentes du casier. À 5 ans de serveur (outils/banc_annees.py) : 4 000 évènements PAR JOUR,
// 3 500 tickets fermés, des milliers de personnes au casier — tout envoyer d'un coup alourdirait chaque page. La suite
// est demandée au serveur quand on en a besoin :
//   · le journal filtré par le serveur dès que la période, la catégorie, la gravité ou la recherche dépassent ce qui
//     est chargé (`api/journal`, 300 par page, « Voir plus ») ; ses chiffres restent exacts (comptage par jour) ;
//   · les tickets fermés : un mois des archives quand on ouvre son groupe (`api/tickets/fermes?mois=`), les récents
//     ou une recherche quand les 300 ne suffisent pas ;
//   · le reste du casier, d'un bouton (`api/casier/membres`), et la recherche dans tout le casier ;
//   · dans « Nettoyage » : ce qu'une durée retirerait avant de l'enregistrer, « Nettoyer maintenant » par règle, la
//     place que prennent la base et les dossiers.

import { h, remplacer, quantite, nombre, depuis, cleJour } from "./dom.js";
import { etat, retenirPersonnes } from "./noyau.js";
import { lire, poster } from "./api.js";
import { bouton, squelettes, vide, tuile, tuiles, toast, confirmer, bandeau } from "./ui.js";
import { parJours } from "./rangement.js";

const JOUR = 86400;
const CHARGES = 400;            // les évènements du journal portés par les données (tableau._journal)
const PAGE_JOURNAL = 300;
const minute = (t) => Math.floor(t / 60) * 60;

// ─── Le journal ──────────────────────────────────────────────────────────────
/** La suite du journal : `vue(f, base, limite)` → { evts, serveur, charge, erreur, total, plus }. `base` : les
 *  évènements des données (les plus récents d'abord) ; ils suffisent s'ils couvrent la période et qu'il n'y a pas de
 *  recherche. Sinon le serveur filtre et rend 300 évènements par page ; `plus` : le bouton « Voir plus » (ou null). */
export function journalSuite(redessiner) {
  const s = { cle: null, params: null, evts: [], suite: null, total: 0, charge: false, erreur: "", jeton: 0, parCategorie: null, parJour: null };
  const demander = async (ajout) => {
    const jeton = ++s.jeton;
    s.charge = true;
    // La première page porte aussi les comptes exacts : par catégorie (les puces) et par jour (« 300 sur 3 610 »).
    const r = await lire("journal", Object.assign({ n: PAGE_JOURNAL }, s.params, ajout ? { avant: s.suite } : { comptes: 1 }));
    if (jeton !== s.jeton) return;
    s.charge = false;
    if (r.ok && r.donnees) {
      retenirPersonnes(r.donnees.personnes);
      s.evts = (ajout ? s.evts : []).concat(r.donnees.evenements || []);
      s.suite = r.donnees.suite || null;
      s.total = Number(r.donnees.total) || s.evts.length;
      if (!ajout) { s.parCategorie = r.donnees.par_categorie || null; s.parJour = r.donnees.par_jour || null; }
      s.erreur = "";
    } else if (!ajout) s.erreur = r.erreur || "Le journal ne répond pas.";
    else toast(r.erreur || "La suite du journal n'a pas pu être chargée.", "erreur");
    redessiner();
  };
  return {
    vue(f, base, limite) {
      const plusVieux = base.length ? base[base.length - 1].quand : 0;
      if (!f.q && (base.length < CHARGES || (limite > 0 && plusVieux <= limite))) { s.cle = null; return { evts: base, serveur: false }; }
      const params = { depuis: limite > 0 ? minute(limite) : "", cat: f.cat !== "tous" ? f.cat : "", gravite: Number(f.gravite) || "", q: f.q || "" };
      const cle = JSON.stringify(params);
      if (s.cle !== cle) { Object.assign(s, { cle, params, evts: [], suite: null, total: 0, erreur: "", parCategorie: null, parJour: null }); demander(false); }
      const reste = Math.max(0, s.total - s.evts.length);
      const plus = s.suite && !s.charge ? bouton("Voir " + nombre(Math.min(PAGE_JOURNAL, reste || PAGE_JOURNAL)) + " évènements de plus", {
        classe: "p discret", icone: "bas", reseau: true, onclick: () => demander(true) }) : null;
      return { evts: s.evts, serveur: true, charge: s.charge, erreur: s.erreur, total: s.total, plus, parCategorie: s.parCategorie, parJour: s.parJour };
    },
    /** Les groupes « jour par jour » quand le serveur filtre : un par jour, puis par semaine et par mois (comme
     *  `parJours`), chacun avec son compte exact ; son contenu se demande quand on l'ouvre (500 à la fois, « Voir les
     *  autres »). `base` : les évènements déjà là (un jour entier déjà chargé n'est pas redemandé). */
    groupes(base, rendre) {
      //  Le plus récent d'abord ; chaque jour rangé d'après sa fin (21 h 59 UTC : encore ce jour-là à Paris), comme un
      //  évènement de ses dernières heures — un jour à cheval sur la limite des 7 jours reste un jour.
      const jours = Object.entries(s.parJour || {}).filter(([, k]) => k > 0).sort((a, b) => (a[0] < b[0] ? 1 : -1))
        .map(([jour, k]) => ({ jour, k, quand: Date.parse(jour + "T21:59:59Z") / 1000 }));
      return parJours(jours, (x) => x.quand).map(([cle, titre, l]) => {
        const du = l.reduce((a, x) => (x.jour < a ? x.jour : a), l[0].jour), au = l.reduce((a, x) => (x.jour > a ? x.jour : a), l[0].jour);
        const total = l.reduce((a, x) => a + x.k, 0);
        return { cle: "jour-s-" + cle, titre, compte: total, contenu: () => plage(du, au, total, cle, base, rendre) };
      });
    },
  };
  function plage(du, au, total, cle, base, rendre) {
    const deja = base.filter((e) => { const j = cleJour(e.quand); return j >= du && j <= au; });
    if (deja.length >= total) return rendre(deja, cle);
    const zone = h("div", { classe: "pile" }, squelettes(2));
    const p = { evts: [], suite: null };
    const charger = async () => {
      const r = await lire("journal", Object.assign({}, s.params, { du, au, n: 500 }, p.suite ? { avant: p.suite } : {}));
      if (!r.ok || !r.donnees) {
        if (p.evts.length) toast(r.erreur || "La suite n'a pas pu être chargée.", "erreur");
        else remplacer(zone, vide("Indisponible pour le moment", r.erreur || "Le journal ne répond pas.", "hors_ligne"));
        return;
      }
      retenirPersonnes(r.donnees.personnes);
      p.evts = p.evts.concat(r.donnees.evenements || []);
      p.suite = r.donnees.suite || null;
      remplacer(zone, rendre(p.evts, cle), p.suite ? h("div", { classe: "rangee" }, bouton("Voir les " + quantite(Math.max(0, total - p.evts.length), "autre(s)") + " de ce groupe",
        { classe: "p discret", icone: "bas", reseau: true, onclick: charger })) : null);
    };
    charger();
    return zone;
  }
}

/** Les comptes par catégorie d'une période de 7 ou 30 jours, d'après le comptage jour par jour des données (exact,
 *  quel que soit le nombre d'évènements chargés) — null pour une autre période. */
export function comptesParCategorie(parJour, periode, n) {
  if (!parJour || !["7", "30"].includes(String(periode))) return null;
  const debut = cleJour(n - (Number(periode) - 1) * JOUR), out = {};
  for (const [jour, cats] of Object.entries(parJour)) {
    if (jour < debut) continue;
    for (const [c, k] of Object.entries(cats || {})) out[c] = (out[c] || 0) + (Number(k) || 0);
  }
  return out;
}

// Les chiffres des tuiles du journal : « Aujourd'hui » vient du comptage jour par jour ; « Graves » et « Personnes »
// sur 7 jours, des évènements chargés s'ils couvrent la semaine, sinon d'un résumé du serveur (gardé 5 minutes).
const resume7 = { t: 0, valeur: null, charge: false };
export function chiffresJournal(parJour, base, n, redessiner) {
  const auj = Object.values((parJour || {})[cleJour(n)] || {}).reduce((a, k) => a + (Number(k) || 0), 0);
  const aujBase = base.filter((e) => cleJour(e.quand) === cleJour(n)).length;
  const sept = base.filter((e) => n - e.quand <= 7 * JOUR);
  const couvre = base.length < CHARGES || (base.length && base[base.length - 1].quand <= n - 7 * JOUR);
  let graves = sept.filter((e) => e.gravite >= 2).length, personnes = new Set(sept.map((e) => e.membre).filter(Boolean)).size;
  if (!couvre) {
    if (resume7.valeur) ({ graves, personnes } = resume7.valeur);
    if (!resume7.charge && Date.now() - resume7.t > 300000) {
      resume7.charge = true;
      lire("journal", { depuis: minute(n - 7 * JOUR), n: 1, resume: 1 }).then((r) => {
        resume7.charge = false;
        resume7.t = Date.now();
        if (r.ok && r.donnees) { resume7.valeur = { graves: Number(r.donnees.graves) || 0, personnes: Number(r.donnees.personnes_n) || 0 }; redessiner(); }
      });
    }
  }
  return { aujourdhui: Math.max(auj, aujBase), graves, personnes };
}

// ─── Les tickets fermés ─────────────────────────────────────────────────────
// Les données portent les 300 plus récents et, pour chaque mois de fermeture, combien il en compte par type
// (`tickets.fermes_mois`). Un mois des archives incomplet se charge en entier quand on ouvre son groupe ; les fermés
// récents et une recherche passent par le serveur quand les 300 ne suffisent pas. Ce qui est chargé est gardé tant
// que les données ne changent pas de forme (un mois passé ne bouge plus).
const fermes = { mois: new Map(), depuis: null, recherche: null, total: null };
const incomplet = () => { const tk = etat.d && etat.d.tickets; return !!(tk && Number(tk.fermes_total) > (tk.fermes || []).length); };
// Un ticket fermé de plus, ou un nettoyage : ce qui avait été chargé est relu à la demande suivante.
const fraicheur = () => {
  const total = etat.d && etat.d.tickets ? etat.d.tickets.fermes_total : null;
  if (fermes.total !== total) { fermes.mois.clear(); Object.assign(fermes, { total, depuis: null, recherche: null }); }
};

/** Combien de tickets fermés chaque mois compte, pour ce filtre (`garde` : la même fonction que la liste). */
export function comptesMois(garde) {
  const out = new Map();
  for (const x of ((etat.d && etat.d.tickets && etat.d.tickets.fermes_mois) || [])) {
    if (garde({ type: x.type, rellseas: !!x.rellseas })) out.set(x.mois, (out.get(x.mois) || 0) + (Number(x.n) || 0));
  }
  return out;
}

async function lireFermes(params) {
  const r = await lire("tickets/fermes", params);
  if (!r.ok || !r.donnees) return { erreur: r.erreur || "Les tickets fermés ne répondent pas." };
  retenirPersonnes(r.donnees.personnes);
  return { liste: r.donnees.fermes || [] };
}

/** Le contenu d'un groupe « mois » des archives : la liste chargée si elle est complète, sinon le mois demandé au
 *  serveur (squelettes en attendant). `rendre(liste)` dessine la liste, filtrée comme la page. */
export function moisArchive(mois, charges, attendus, rendre) {
  fraicheur();
  if (charges.length >= attendus || !incomplet()) return rendre(charges);
  const zone = h("div", { classe: "pile" }, squelettes(2));
  const deja = fermes.mois.get(mois);
  const finir = (res) => { if (!zone.isConnected && !zone.parentNode) return; remplacer(zone, res.erreur ? vide("Mois indisponible", res.erreur, "hors_ligne") : rendre(res.liste)); };
  if (deja && deja.liste) finir(deja);
  else {
    const p = (deja && deja.promesse) || lireFermes({ mois });
    fermes.mois.set(mois, { promesse: p });
    p.then((res) => { if (!res.erreur) fermes.mois.set(mois, res); else fermes.mois.delete(mois); finir(res); });
  }
  return zone;
}

/** Les fermés depuis `depuisT` quand les 300 des données ne remontent pas jusque-là (sinon null : elles suffisent). */
export function fermesDepuis(depuisT, redessiner) {
  fraicheur();
  const tk = etat.d && etat.d.tickets;
  if (!tk || !incomplet()) return null;
  const plusVieux = Math.min(...(tk.fermes || []).map((t) => t.ferme || t.ouvert || Infinity));
  if (plusVieux <= depuisT) return null;
  const cle = minute(depuisT - (depuisT % 3600));
  if (!fermes.depuis || fermes.depuis.cle !== cle) {
    fermes.depuis = { cle, liste: null };
    lireFermes({ depuis: cle }).then((res) => { if (fermes.depuis && fermes.depuis.cle === cle) { fermes.depuis.liste = res.liste || []; redessiner(); } });
  }
  return fermes.depuis.liste;
}

/** Une recherche dans TOUS les tickets fermés, quand les 300 des données ne les ont pas tous (sinon null). */
export function fermesRecherche(q, redessiner) {
  fraicheur();
  if (!q || !incomplet()) return null;
  if (!fermes.recherche || fermes.recherche.q !== q) {
    fermes.recherche = { q, liste: null };
    lireFermes({ q }).then((res) => { if (fermes.recherche && fermes.recherche.q === q) { fermes.recherche.liste = res.liste || []; redessiner(); } });
  }
  return fermes.recherche.liste;
}

/** Deux listes de tickets fermés réunies (sans doublon), les plus récents d'abord. */
export function reunirFermes(a, b) {
  const vus = new Map();
  for (const t of [...(a || []), ...(b || [])]) if (!vus.has(t.ticket)) vus.set(t.ticket, t);
  return [...vus.values()].sort((x, y) => (y.ferme || y.ouvert || 0) - (x.ferme || x.ouvert || 0));
}

// ─── Le casier ──────────────────────────────────────────────────────────────
// Les données portent les 250 personnes les plus récentes du casier (`sanctions.membres`) et le total
// (`sanctions.membres_total`). Le reste se charge d'un bouton (500 par demande), et une recherche cherche dans tout le
// casier quand il n'est pas entier.
const casier = { autres: [], complet: false, charge: false, recherche: null, total: 0 };

export function casierMembres() {
  const s = etat.d && etat.d.sanctions;
  if (!s) return [];
  if (casier.total !== s.membres_total) Object.assign(casier, { autres: [], complet: false, recherche: null, total: s.membres_total });
  const vus = new Set(s.membres.map((m) => m.id));
  return s.membres.concat(casier.autres.filter((m) => !vus.has(m.id)));
}

/** Le bouton « Afficher les N autres personnes du casier » (null quand tout est là). */
export function casierPlus(redessiner) {
  const s = etat.d && etat.d.sanctions;
  const restant = s ? Number(s.membres_total || 0) - casierMembres().length : 0;
  if (!s || restant <= 0 || casier.complet) return null;
  //  Court : au téléphone, un bouton ne passe pas à la ligne (« Afficher les 4 510 autres personnes du casier » débordait).
  return bouton(casier.charge ? "Chargement…" : "Voir les " + quantite(restant, "autre(s) personne(s)"), {
    classe: "p discret", icone: "bas", reseau: true, disabled: casier.charge, onclick: async () => {
      casier.charge = true; redessiner();
      let apres = s.membres.length + casier.autres.length;
      for (let tour = 0; tour < 40; tour++) {
        const r = await lire("casier/membres", { apres, n: 500 });
        if (!r.ok || !r.donnees) { toast(r.erreur || "Le casier ne répond pas.", "erreur"); break; }
        retenirPersonnes(r.donnees.personnes);
        casier.autres = casier.autres.concat(r.donnees.membres || []);
        if (r.donnees.suite == null) { casier.complet = true; break; }
        apres = r.donnees.suite;
      }
      casier.charge = false; redessiner();
    } });
}

/** Une recherche dans tout le casier, quand il n'est pas entier dans la page (sinon null). */
export function casierRecherche(q, redessiner) {
  const s = etat.d && etat.d.sanctions;
  if (!q || !s || casier.complet || Number(s.membres_total || 0) <= casierMembres().length) return null;
  if (!casier.recherche || casier.recherche.q !== q) {
    casier.recherche = { q, liste: null };
    lire("casier/membres", { q, n: 500 }).then((r) => {
      if (!casier.recherche || casier.recherche.q !== q) return;
      if (r.ok && r.donnees) retenirPersonnes(r.donnees.personnes);
      casier.recherche.liste = (r.ok && r.donnees && r.donnees.membres) || [];
      redessiner();
    });
  }
  return casier.recherche.liste;
}

// ─── Nettoyage : l'aperçu, « Nettoyer maintenant », la place prise ───────────
/** « 1 234 éléments partiront au prochain passage », ou avec une autre durée « avec 45 j : 3 éléments partiraient »
 *  (rien si la règle n'en dit rien). */
export function texteApercu(n, jours) {
  if (n === undefined) return "";
  if (n === null) return "aperçu indisponible";
  const avec = jours ? "avec " + jours + " j : " : "", un = Number(n) < 2;
  if (!Number(n)) return avec + (jours ? "rien ne partirait" : "rien ne partira au prochain passage");
  return avec + quantite(n, "élément(s)") + (jours ? (un ? " partirait" : " partiraient") : (un ? " partira" : " partiront") + " au prochain passage");
}

/** L'aperçu d'une durée sur la réglette, demandé au serveur (300 ms après le dernier geste). */
export function apercuReglette(cle, sortie) {
  let minuteur = 0, jeton = 0;
  return (jours) => {
    clearTimeout(minuteur);
    sortie.textContent = "…";
    minuteur = setTimeout(async () => {
      const j = ++jeton;
      const r = await lire("nettoyage/apercu", { cle, jours });
      if (j !== jeton) return;
      sortie.textContent = r.ok && r.donnees ? texteApercu(r.donnees.partiront, jours) : "";
    }, 300);
  };
}

/** « Nettoyer maintenant » d'une règle : la confirmation dit combien partent pour de bon ; le bilan va au journal. */
export function boutonNettoyerRegle(r, n, recharger) {
  if (r.auto === false || !n) return null;
  return bouton("Nettoyer maintenant", { classe: "p discret", icone: "nettoyage", reseau: true, onclick: async () => {
    const ok = await confirmer({ titre: "Nettoyer « " + r.nom + " » maintenant ?", texte: quantite(n, "élément(s)") + " " + (n > 1 ? "vont être effacés" : "va être effacé")
      + " pour de bon (règle : " + r.garde_jours + " jours). Le bilan est noté au journal.", libelleOk: "Nettoyer", style: "danger" });
    if (!ok) return;
    const rep = await poster("nettoyage/lancer", { cle: r.cle });
    if (!rep.ok) { toast(rep.erreur || "Le nettoyage n'a pas pu être lancé.", "erreur"); return; }
    const parti = Number(((rep.donnees && rep.donnees.retires) || {})[r.cle]) || 0;
    toast(r.nom + " : " + (parti > 0 ? quantite(parti, "élément(s) retiré(s)") : parti < 0 ? "en échec, voir le journal" : "rien à retirer") + ".", parti < 0 ? "erreur" : "succes");
    recharger();
  } });
}

// Le nombre et son unité ne se séparent jamais (espace insécable).
const mo = (o) => (Number(o) >= 1073741824 ? (o / 1073741824).toFixed(1).replace(".", ",") + " Go" : Math.max(0, Math.round((Number(o) || 0) / 1048576)) + " Mo");

/** La place prise : la base (ses pages libres, son compactage de la nuit), les dossiers, les copies, le volume. */
export function cadreStockage(st) {
  if (!st) return null;
  const dos = st.dossiers || {}, vol = st.volume || {};
  const occupe = vol.total && vol.libre !== null && vol.libre !== undefined ? Math.round(100 * (vol.total - vol.libre) / vol.total) : null;
  const libres = Number(st.libres) || 0;
  const images = ((dos.images || {}).octets || 0) + ((dos.portraits || {}).octets || 0);
  return h("div", { classe: "cadre pile serree" }, h("h3", {}, "La place prise"),
    h("p", { classe: "aide" }, "La base " + mo(st.base) + (libres > 1048576 ? " (dont " + mo(libres) + " à rendre au disque cette nuit)" : "") + " · conversations "
      + mo((dos.transcripts || {}).octets) + " · images " + mo(images) + " · copies " + mo((dos.copies || {}).octets)
      + (occupe !== null ? " — le disque est rempli à " + occupe + " %." : ".")),
    tuiles(
      tuile({ cle: "st1", lib: "La base", texte: mo(st.base), icone: "coffre", sous: libres > 1048576 ? mo(libres) + " à rendre cette nuit" : st.compacte_le ? "compactée " + depuis(st.compacte_le) : "compactée chaque nuit", teinte: "#1f4e5a" }),
      tuile({ cle: "st2", lib: "Conversations", texte: mo((dos.transcripts || {}).octets), icone: "parchemin", sous: quantite((dos.transcripts || {}).fichiers || 0, "fichier(s)"), teinte: "#7a4b2a" }),
      tuile({ cle: "st3", lib: "Images et portraits", texte: mo(((dos.images || {}).octets || 0) + ((dos.portraits || {}).octets || 0)), icone: "image", sous: quantite(((dos.images || {}).fichiers || 0) + ((dos.portraits || {}).fichiers || 0), "fichier(s)"), teinte: "#a8641c" }),
      tuile({ cle: "st4", lib: "Copies de la base", texte: mo((dos.copies || {}).octets), icone: "restaurer", sous: quantite((dos.copies || {}).fichiers || 0, "copie(s)"), teinte: "#5e3a4e" }),
      occupe !== null ? tuile({ cle: "st5", lib: "Le disque", texte: occupe + " %", icone: "carte", sous: mo(vol.libre) + " libres sur " + mo(vol.total), teinte: occupe >= 80 ? "#8e2a24" : "#3f6b3a" }) : null),
    occupe !== null && occupe >= 80 ? bandeau("Le disque est presque plein : raccourcis les durées les plus lourdes (conversations, tickets fermés).", "rouge") : null);
}

// Les familles de règles (par leur ordre) : la rubrique les range ainsi, une famille par groupe.
export const FAMILLES = [[0, 20, "Le journal", "journal"], [20, 30, "Les tickets", "tickets"], [30, 40, "Le recrutement", "candidatures"],
  [40, 50, "Le casier", "sanctions"], [50, 60, "Le clan", "equipage"], [60, 70, "Les affiches", "affiches"], [70, 73, "Les membres", "membres"],
  [73, 80, "Les salons", "salons"], [80, 1000, "Le site et ses fichiers", "nettoyage"]];
export const familleDe = (ordre) => FAMILLES.find(([a, b]) => ordre >= a && ordre < b) || FAMILLES[FAMILLES.length - 1];
