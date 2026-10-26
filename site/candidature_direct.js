// candidature_direct.js — le direct du questionnaire en ligne, pour le fondateur et la direction (26/10/2026) : chaque
// question avec la réponse qui s'écrit pendant que le candidat tape, « en train d'écrire », sa page (ouverte, en
// arrière-plan, fermée, inactive depuis…), l'étape ouverte et celles déjà envoyées, l'envoi.
//
//   vueEnDirect(cible, { surEnvoye, surEtape })  → un élément VIVANT à poser dans une page (le dossier, une zone) :
//     cible : un numéro de ticket, ou { ticket } / { envoi } (un chef d'équipe n'a pas de ticket : son envoi) ;
//     surEnvoye() : le candidat vient d'envoyer ses dernières réponses (la page relit son dossier) ;
//     surEtape(numero) : il vient d'envoyer une étape (la direction décide de la suite).
//   L'élément se débranche seul quand il quitte la page.
//
// Le serveur : candidature_site.py — `GET api/direct/candidat?ticket=|envoi=` (l'état complet, portée « tout »), puis
// les messages « candidat » de la présence en direct (direct.js, WebSocket : au plus quatre par seconde). Sans
// WebSocket (un proxy qui la bloque), la lecture est refaite toutes les 3,5 s tant que la page est visible.

import { h, icone, remplacer, heure, date, sansEmoji, maintenant } from "./dom.js";
import { lire } from "./api.js";
import { surDirect, modeDirect } from "./direct.js";

const TOUR_SANS_WS = 3500;        // ms : la lecture, sans WebSocket
const TOUR_AVEC_WS = 30000;       // ms : avec, une relecture de sûreté (un message perdu ne fausse rien longtemps)
const ECRIT_RECENT = 8;           // s : « en train d'écrire »
const OUVERTE_VIE = 75;           // s : une page ouverte qui ne donne plus de nouvelles est fermée (son battement : 20 s)
const CACHEE_VIE = 200;           // s : une page en arrière-plan (ses minuteurs ralentissent)

/** Les guillemets et la ponctuation haute tiennent à leur mot (espaces insécables, comme la page du candidat). */
const insecable = (s) => String(s ?? "").replace(/« /g, "« ").replace(/ ([»:;?!])/g, " $1");

function ilYa(s) {
  if (s < 10) return "à l'instant";
  if (s < 60) return "il y a " + Math.round(s) + " s";
  if (s < 3600) return "il y a " + Math.round(s / 60) + " min";
  if (s < 86400) return "il y a " + Math.round(s / 3600) + " h";
  return "il y a " + Math.round(s / 86400) + " j";
}
function depuisDuree(s) {
  if (s < 60) return "depuis un instant";
  if (s < 3600) return "depuis " + Math.round(s / 60) + " min";
  if (s < 86400) return "depuis " + Math.floor(s / 3600) + " h";
  return "depuis " + Math.floor(s / 86400) + " j";
}

export function vueEnDirect(cible, opts = {}) {
  const demande = typeof cible === "object" && cible ? { ticket: cible.ticket || undefined, envoi: cible.envoi || undefined } : { ticket: cible };
  const el = h("section", { classe: "en-direct", "aria-label": "En direct" });
  const S = { d: null, ecart: 0, dernierMessage: 0, lu: 0, enLecture: false, fini: false, minuteur: 0, horloge: 0, pret: false };
  const tete = h("div", { classe: "en-direct-tete" });
  const corps = h("div", { classe: "en-direct-corps" });
  el.append(tete, corps);
  remplacer(tete, point(""), h("h3", {}, "En direct"), h("span", { classe: "en-direct-etat" }, "Le direct se branche…"));

  const temps = () => maintenant() + S.ecart;   // l'heure du serveur, sur cette machine
  const debrancher = () => {
    if (S.fini) return;
    S.fini = true;
    clearInterval(S.minuteur); clearInterval(S.horloge);
    if (S.desabonner) S.desabonner();
  };
  /** L'état complet, relu. Une lecture déjà en route : une autre suivra (l'état a pu changer entre-temps), et c'est
   *  l'état d'AVANT ce changement qui sert à annoncer ce qui est arrivé (une étape, les dernières réponses). */
  async function lireEtat() {
    if (S.fini) return;
    if (S.enLecture) { S.encore = true; return; }
    if (!el.isConnected && S.pret) { debrancher(); return; }
    S.enLecture = true;
    const r = await lire("direct/candidat", demande);
    S.enLecture = false;
    S.lu = Date.now();
    if (S.fini) return;
    if (!r.ok || !r.donnees) {
      if (!S.d) remplacer(corps, h("p", { classe: "aide" }, r.status === 404 ? "Aucun questionnaire en cours ici." : "Le direct ne répond pas pour le moment."));
    } else {
      const avant = S.d;
      S.d = r.donnees;
      S.ecart = (Number(S.d.s) || maintenant()) - maintenant();
      rendre();
      annoncer(avant, S.d);
    }
    if (S.encore) { S.encore = false; lireEtat(); }
  }
  /** Ce qui a changé et que la page doit savoir : la dernière étape envoyée (le dossier relit), une étape envoyée. */
  function annoncer(avant, apres) {
    if (!avant || !apres) return;
    if (avant.etat !== "envoye" && apres.etat === "envoye" && opts.surEnvoye) opts.surEnvoye();
    const a = (avant.portes || {}).envoyee || 0, b = (apres.portes || {}).envoyee || 0;
    if (b > a && apres.etat !== "envoye" && opts.surEtape) opts.surEtape(b);
  }
  /** Un message « candidat » (la présence en direct) : appliqué sur place, sans relire. */
  function appliquer(m) {
    if (!S.d || Number(m.e) !== Number(S.d.envoi)) {
      //  Son questionnaire vient de partir (la vue attendait, « aucun ») : la lecture le trouve.
      if ((!S.d || !S.d.envoi) && demande.ticket && Number(m.k) === Number(demande.ticket)) lireEtat();
      return;
    }
    const avant = JSON.parse(JSON.stringify(S.d));
    S.dernierMessage = Date.now();
    if (m.s) S.ecart = Number(m.s) - maintenant();
    const d = S.d;
    if (m.rep) for (const [rang, texte] of Object.entries(m.rep)) { if (texte) d.reponses[rang] = texte; else delete d.reponses[rang]; }
    if (m.ec) for (const [rang, t] of Object.entries(m.ec)) d.ecrits[rang] = Number(t) || 0;
    if (m.ec) d.ecrit = Math.max(d.ecrit || 0, ...Object.values(m.ec).map(Number));
    if (m.vu) d.page.vu = Number(m.vu);
    if (m.vue) d.page.vue = m.vue;
    if (m.et) d.etape = Number(m.et);
    if (m.r) d.rang = Number(m.r);
    //  Une étape envoyée ou ouverte, l'envoi fini : tout relire. L'état (`etat`, `portes`) n'est PAS touché ici : la
    //  lecture compare l'avant et l'après pour annoncer ce qui est arrivé (« Réponses reçues », une étape).
    const changePortes = m.po && ((d.portes || {}).ouverte !== m.po.o || (d.portes || {}).envoyee !== m.po.env);
    if (changePortes || (m.etat && m.etat !== avant.etat)) { lireEtat(); return; }
    rendre();
  }
  S.desabonner = surDirect((ev) => {
    if (S.fini) return;
    if (!el.isConnected && S.pret) { debrancher(); return; }
    if (ev.type === "candidat" && ev.m) appliquer(ev.m);
    else if (ev.type === "etat" || ev.type === "mode") lireEtat();   // (re)connecté : l'état complet
  });
  S.minuteur = setInterval(() => {
    if (!el.isConnected) { if (S.pret) debrancher(); return; }
    S.pret = true;
    if (document.hidden) return;
    const ws = modeDirect() === "ws";
    if (Date.now() - S.lu >= (ws ? TOUR_AVEC_WS : TOUR_SANS_WS)) lireEtat();
  }, 1000);
  S.horloge = setInterval(() => { if (S.d && el.isConnected && !document.hidden) rendreTete(); }, 5000);   // « il y a 12 s »
  lireEtat();
  requestAnimationFrame(() => { if (el.isConnected) S.pret = true; });

  // ─── Le dessin ───
  function point(genre) {
    return h("span", { classe: "en-direct-point" + (genre ? " " + genre : ""), "aria-hidden": "true" });
  }
  /** L'état du candidat, en une phrase : où en est le questionnaire, et sa page. */
  function etatCandidat() {
    const d = S.d, p = d.portes || {}, t = temps();
    if (d.etat === "aucun") return ["", "Le questionnaire n'est pas encore parti"];
    const fiche = p.fiche ? 1 : 0;
    if (d.etat === "envoye") return ["vert", "Réponses envoyées" + (d.envoye_le ? " à " + heure(d.envoye_le) + (t - d.envoye_le > 86400 ? " le " + date(d.envoye_le) : "") : "")];
    if (d.etat === "ferme") return ["", "Candidature terminée : le questionnaire n'attend plus de réponse"];
    if (d.etat === "remplace") return ["", "Questionnaire remplacé par un plus récent"];
    const page = d.page || {};
    const age = page.vu ? t - page.vu : Infinity;
    let quoi;
    if (page.vue === "jamais" || !page.vu) quoi = ["", "Lien pas encore ouvert"];
    else if (page.vue === "fermee" || (page.vue === "ouverte" && age > OUVERTE_VIE) || (page.vue === "cachee" && age > CACHEE_VIE)) quoi = ["", "Page fermée · vue " + ilYa(age)];
    else if (page.vue === "cachee") quoi = ["ambre", "Page en arrière-plan · " + depuisDuree(age)];
    else if (d.ecrit && t - d.ecrit < ECRIT_RECENT) quoi = ["vif", "En train d'écrire"];
    else if (d.ecrit && t - d.ecrit < 60) quoi = ["vif", "Page ouverte · écrit " + ilYa(t - d.ecrit)];
    else if (Math.max(d.ecrit || 0, page.ouvert_le || 0)) quoi = ["vif", "Page ouverte · inactif " + depuisDuree(t - Math.max(d.ecrit || 0, page.ouvert_le || 0))];
    else quoi = ["vif", "Page ouverte"];
    if (d.etat === "attente") return ["ambre", "Étape " + ((p.envoyee || 0) + fiche) + " envoyée · il attend ta décision" + (quoi[0] === "vif" ? " · " + quoi[1].toLowerCase() : "")];
    return quoi;
  }
  function rendreTete() {
    if (!S.d) return;
    const [genre, texte] = etatCandidat();
    remplacer(tete, point(genre), h("h3", {}, "En direct"), h("span", { classe: "en-direct-etat " + genre }, texte));
    for (const q of corps.querySelectorAll("[data-ecrit]")) q.textContent = libelleEcrit(Number(q.dataset.ecrit), Number(q.dataset.rang));
  }
  function libelleEcrit(t, rang) {
    if (!t) return "";
    const d = S.d, s = temps() - t;
    if (Number(d.rang) === rang && d.etat === "ouvert" && s < ECRIT_RECENT && (d.page || {}).vue !== "fermee") return "en train d'écrire";
    return "écrit " + ilYa(s);
  }
  function rendre() {
    const d = S.d;
    if (!d) return;
    rendreTete();
    if (d.etat === "aucun" || !Array.isArray(d.etapes)) {   // sa demande attend : le direct se branchera avec le questionnaire
      remplacer(corps, h("p", { classe: "aide" }, "Dès que son questionnaire part, ce qu'il écrit apparaît ici pendant qu'il tape."));
      return;
    }
    const p = d.portes || {};
    const fiche = p.fiche ? 1 : 0;
    const totalAff = (Number(p.total) || d.etapes.length) + fiche;
    const toutes = d.etapes.flatMap((e) => e.questions);
    const faites = toutes.filter((q) => (d.reponses[String(q.rang)] || "").trim()).length;
    const resume = [];
    if (p.mode === "etapes") {
      if (d.etat === "ouvert" && p.courante) resume.push("Étape " + (d.etapes.findIndex((e) => e.courante) + 1 + fiche) + " sur " + totalAff + " ouverte");
      if (p.envoyee) resume.push(p.envoyee === 1 ? "1 étape envoyée" : p.envoyee + " étapes envoyées");
    } else if (totalAff > 1 && d.etat === "ouvert" && d.etape) resume.push("Sur l'étape " + Math.min(d.etape, totalAff) + " sur " + totalAff);
    resume.push(faites + " / " + toutes.length + " questions avec une réponse");
    remplacer(corps,
      h("p", { classe: "aide" }, d.etat === "ouvert" || d.etat === "attente" ? "Ce que le candidat écrit apparaît ici pendant qu'il tape. Rien n'est envoyé avant qu'il valide." : "Ce qu'il a envoyé."),
      h("p", { classe: "en-direct-resume" }, resume.join(" · ")),
      d.etapes.map((et) => etape(et, totalAff, fiche, d)));
  }
  function etape(et, totalAff, fiche, d) {
    const p = d.portes || {};
    const ouverte = et.ouverte !== false;
    const etiquette = p.mode === "etapes" ? (et.envoyee ? ["vert", "Envoyée"] : et.courante ? ["mer", d.etat === "ouvert" ? "En cours" : "Ouverte"] : !ouverte ? ["encre", "Pas encore ouverte"] : null) : null;
    const titre = h("h4", { classe: "en-direct-etape-titre" },
      totalAff > 1 ? h("span", {}, "Étape " + (et.position + fiche) + " sur " + totalAff) : h("span", {}, "Le questionnaire"),
      et.titre ? h("span", { classe: "en-direct-etape-nom" }, insecable(sansEmoji(et.titre))) : null,
      etiquette ? h("span", { classe: "tampon droit " + etiquette[0] }, etiquette[1]) : null);
    const classe = "en-direct-etape" + (et.envoyee ? " envoyee" : "") + (et.courante ? " courante" : "") + (!ouverte ? " fermee" : "");
    if (!ouverte) return h("div", { classe }, titre, h("p", { classe: "meta" }, et.questions.length + (et.questions.length > 1 ? " questions" : " question") + " · le candidat ne les voit pas encore"));
    return h("div", { classe }, titre, h("ol", { classe: "en-direct-questions" }, et.questions.map((q) => {
      const rang = String(q.rang);
      const texte = d.reponses[rang] || "";
      const ecrit = Number(d.ecrits[rang]) || 0;
      const actif = Number(d.rang) === q.rang && d.etat === "ouvert" && ecrit && temps() - ecrit < ECRIT_RECENT;
      return h("li", { classe: "en-direct-q" + (actif ? " actif" : "") + (texte ? "" : " vide") },
        h("div", { classe: "en-direct-question" }, h("span", { classe: "en-direct-num" }, String(q.rang)), h("span", {}, insecable(q.question))),
        h("div", { classe: "en-direct-reponse" }, texte ? texte : h("span", { classe: "aide" }, "Pas encore de réponse"), actif ? h("span", { classe: "en-direct-plume", "aria-hidden": "true" }, icone("plume")) : null),
        ecrit && texte ? h("div", { classe: "en-direct-ecrit", "data-ecrit": String(ecrit), "data-rang": rang }, libelleEcrit(ecrit, q.rang)) : null);
    })));
  }
  return el;
}
