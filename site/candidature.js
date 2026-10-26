// candidature.js — le questionnaire en ligne du candidat (26/10/2026) : étape par étape, enregistré pendant la saisie,
// gardé sur l'appareil si la connexion saute, envoyé une seule fois.
// Le serveur : candidature_site.py (/tableau/candidature/api/…, portée « candidat » : SON questionnaire, rien d'autre).
// Deux façons d'envoyer (`portes.mode`) :
//   · « etapes » — le passage d'étape : chaque étape est une porte que la direction ouvre. Le candidat ne voit que les
//     étapes ouvertes, envoie CETTE étape, puis attend (« Réponses envoyées… ») ; les suivantes sont comptées, pas
//     montrées ; la fiche du ticket est son « Étape 1 ». La page relit quand elle redevient visible.
//   · « unique » — un envoi d'avant : tout est ouvert, « Relire et envoyer », un seul envoi.
// Un questionnaire de chef d'équipe (`nature` « chef ») a ses titres et sa règle : chaque réponse doit être juste.
// Rien du site de la direction n'est chargé ici ; aucune donnée n'est écrite en HTML : tout passe par h() (dom.js). Les
// textes viennent du registre (« Le questionnaire en ligne ») ; ceux d'ici sont les textes d'origine, en repli.

import { h, icone, $, chargerSprite, completerSprite, remplacer, sansEmoji, srcSure, reduit } from "./dom.js";
import { bouton, toast, confirmer } from "./ui.js";

const RACINE = "/tableau/candidature";
/** La version des fichiers : celle de la balise <script> de cette page (s/candidature.js?v=…), posée par le serveur. */
const V = (() => {
  try {
    const s = document.querySelector('script[type="module"][src*="/s/candidature.js"]');
    return (s && new URL(s.src).searchParams.get("v")) || "dev";
  } catch (e) { return "dev"; }
})();
const ICONES = ["parchemin", "plume", "succes", "attention", "info", "gauche", "droite", "valider", "lien", "hors_ligne", "synchro",
  "modifier", "cloche", "coche", "carte", "cadenas", "minuteur", "etoile", "sabre"];
const DELAI = 15000;
const SAISIE_MS = 400;            // au plus une frappe envoyée au direct toutes les 0,4 s (le serveur en regroupe aussi)
const ENREGISTRER_MS = 1200;      // le brouillon part 1,2 s après la dernière frappe…
const ENREGISTRER_MAX_MS = 8000;  // … et au plus tard 8 s après la première frappe pas encore gardée
const REESSAI_MS = 6000;          // sans connexion : un nouvel essai toutes les 6 s (et dès que le réseau revient)
const BATTEMENT_MS = 20000;       // la page donne de ses nouvelles (le direct sait qu'elle est ouverte ; elle apprend la suite)
const RELIRE_MIN_MS = 4000;       // la relecture (page revenue, focus) : pas plus d'une toutes les 4 s

const E = {
  q: null,               // la lecture « questionnaire » : etat, portes, etapes (ouvertes), liens, reponses, textes…
  textes: {},
  vue: "",               // etape · relire · attente · merci · message
  message: "",           // remplace · ferme · expire
  etape: 0,              // l'étape affichée (son index parmi les étapes visibles)
  rang: 0,               // la question où le candidat écrit
  reponses: {},          // rang → texte (ce qui est à l'écran)
  sales: new Set(),      // les rangs pas encore gardés par le serveur
  horsLigne: false,
  enVol: false,
  enVolTextes: null,     // ce que porte le brouillon en route (rang → texte) : la fermeture de la page ne le renvoie pas
  envoi: 0,
  fini: false,
  envoiEnCours: false,
  manque: false,         // « Envoyer » touché avec des questions vides : la page les montre
};

// ─── Les textes : ceux de la direction (registre), sinon ceux d'origine ────
function T(cle, defaut, valeurs) {
  const v = E.textes["candidature." + cle];
  const s = typeof v === "string" && v.trim() ? v : defaut;
  return valeurs ? s.replace(/\{([a-z_]+)\}/g, (m, k) => (k in valeurs ? String(valeurs[k]) : m)) : s;
}
const chef = () => !!(E.q && E.q.nature === "chef");
const metier = () => sansEmoji(E.q && E.q.metier);
function gras(ligne) {
  return String(ligne).split(/(\*\*[^*\n]+\*\*)/g).filter(Boolean)
    .map((s) => (/^\*\*[^*\n]+\*\*$/.test(s) ? h("b", {}, s.slice(2, -2)) : s));
}
/** Un texte du registre : des paragraphes, des retours à la ligne, le **gras** ; une ligne « -# … » s'écrit en petit. */
function texteRiche(texte, classe) {
  const blocs = [];
  let courant = [];
  const finir = () => { if (courant.length) { blocs.push(h("p", {}, courant.flatMap((l, i) => (i ? [h("br"), ...gras(l)] : gras(l))))); courant = []; } };
  for (const l of String(texte || "").replace(/\r\n?/g, "\n").split("\n")) {
    if (/^-#\s/.test(l)) { finir(); blocs.push(h("p", { classe: "petit" }, gras(l.replace(/^-#\s*/, "")))); }
    else if (!l.trim()) finir();
    else courant.push(l);
  }
  finir();
  return h("div", { classe: "cand-texte" + (classe ? " " + classe : "") }, blocs);
}

// Les textes qui changent pour un chef d'équipe.
const texteEntete = () => (chef() ? T("chef.entete", "Questionnaire de chef d'équipe") : T("entete", "Questionnaire de candidature"));
const texteTitre = () => (chef() ? (metier() ? T("chef.titre", "Questionnaire de chef d'équipe · {metier}", { metier: metier() }) : T("chef.entete", "Questionnaire de chef d'équipe"))
  : T("titre", "Ta candidature"));
const textePhrase = () => (chef() ? T("chef.phrase", "Chaque réponse doit être juste : prends le temps de vérifier.") : T("phrase", "Le questionnaire du clan, étape par étape."));
const texteIntro = () => (chef() ? T("chef.intro", "La direction te propose de devenir chef d'équipe. Réponds avec tes propres mots : chaque réponse doit être juste, il n'y a pas droit à l'erreur.\n-# Every answer must be right: there is no room for mistakes.")
  : T("intro", "Réponds à chaque question avec tes propres mots. Tes réponses s'enregistrent toutes seules : tu peux faire une pause et revenir avec ton lien.\n-# Answer each question in your own words. Your answers save automatically: you can take a break and come back."));
const texteAttente = () => (chef() ? T("chef.attente", "La direction les regarde : tu seras prévenu par message privé.\n-# The leadership is reviewing them: you'll be notified by direct message.")
  : T("attente.texte", "La direction les regarde : tu seras prévenu dans ton ticket.\n-# The leadership is reviewing them: you'll be notified in your ticket."));
const texteMerci = () => (chef() ? T("chef.merci", "Tes réponses sont transmises à la direction : tu seras prévenu par message privé.\n-# Your answers have been sent to the leadership.")
  : T("merci.texte", "Tes réponses sont transmises à la direction. Tu peux fermer cette page.\n-# Thank you, your answers have been sent to the leadership. You can close this page."));

// ─── Parler au serveur (ne lève jamais) ─────────────────────────────────────
async function appel(methode, nom, corps, o = {}) {
  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), o.delai || DELAI);
  let r;
  try {
    r = await fetch(RACINE + "/api/" + nom, {
      method: methode, credentials: "same-origin", cache: "no-store", signal: ctrl.signal, keepalive: !!o.keepalive,
      headers: methode === "POST" ? { "Content-Type": "application/json", "X-Tableau": "1" } : {},
      body: methode === "POST" ? JSON.stringify(corps || {}) : undefined,
    });
  } catch (e) {
    return { ok: false, status: 0, reseau: true, donnees: {} };
  } finally {
    clearTimeout(minuteur);
  }
  let d = null;
  try { d = await r.json(); } catch (e) { d = null; }
  if (r.status === 401 || r.status === 403) {   // lien expiré, session finie ou fermée ailleurs : la page le dit
    if (!o.discret) finir("expire");
    return { ok: false, status: r.status, fin: true, donnees: d || {} };
  }
  return { ok: r.ok, status: r.status, donnees: d || {}, reseau: r.status >= 502 && !(d && d.erreur) };
}

// ─── Le brouillon gardé sur l'appareil (rien de perdu si la connexion saute) ──
const cleLocale = () => "candidature." + E.envoi;
function lireLocal() {
  try {
    const d = JSON.parse(localStorage.getItem(cleLocale()) || "null");
    return d && typeof d === "object" && d.v === 1 ? d : null;
  } catch (e) { return null; }
}
function sauverLocal() {
  if (!E.envoi || E.fini) return;
  try {
    localStorage.setItem(cleLocale(), JSON.stringify({ v: 1, reponses: E.reponses, sales: [...E.sales], etape: E.etape, t: Date.now() }));
  } catch (e) { /* stockage plein ou refusé : le serveur garde déjà l'essentiel */ }
}
function oublierLocal() {
  try { localStorage.removeItem(cleLocale()); } catch (e) { /* rien à oublier */ }
}

// ─── Les étapes et leurs portes ─────────────────────────────────────────────
const portes = () => (E.q && E.q.portes) || { mode: "unique", ouverte: 0, envoyee: 0, fiche: 0, total: 1, courante: 0 };
const parEtapes = () => portes().mode === "etapes";
const visibles = () => (E.q && E.q.etapes) || [];
const toutes = () => visibles().flatMap((e) => e.questions);
const repondue = (q) => !!String(E.reponses[String(q.rang)] || "").trim();
const indexCourante = () => visibles().findIndex((e) => e.courante);
/** Les questions que le candidat peut écrire maintenant (le serveur refuse les autres). */
function modifiables() {
  if (!E.q || E.q.etat !== "ouvert") return new Set();
  if (!parEtapes()) return new Set(toutes().map((q) => String(q.rang)));
  const c = visibles().find((e) => e.courante);
  return new Set(c ? c.questions.map((q) => String(q.rang)) : []);
}
/** « Étape 2 sur 4 » : la place de l'étape parmi toutes, la fiche du ticket comptée comme l'étape 1. */
function libelleEtape(position) {
  const p = portes();
  const total = (Number(p.total) || visibles().length || 1) + (p.fiche ? 1 : 0);
  return total > 1 ? T("etape", "Étape {numero} sur {total}", { numero: position + (p.fiche ? 1 : 0), total }) : T("etape.seule", "Le questionnaire");
}

// ─── Le démarrage ───────────────────────────────────────────────────────────
async function demarrer() {
  await Promise.race([chargerSprite("/tableau/espace/s/icones/ui.svg?v=" + V), new Promise((ok) => setTimeout(ok, 2500))]);
  completerSprite(ICONES);
  const r = await appel("GET", "questionnaire", null, { discret: true });
  document.body.classList.remove("demarrage");
  if (!r.ok) {
    if (r.fin) { finir("expire"); return; }
    rendreMessage("hors_ligne_depart");
    return;
  }
  appliquer(r.donnees);
  addEventListener("online", () => { E.horsLigne = false; majIndicateur(); enregistrer(); });
  addEventListener("offline", () => { E.horsLigne = true; majIndicateur(); });
  document.addEventListener("visibilitychange", () => {
    if (E.fini) return;
    clearTimeout(minuteurCachee);
    if (document.hidden) {   // cachée (le candidat cherche sur le wiki) — dit un instant après : une page qui se FERME le dit d'abord
      enregistrer();
      minuteurCachee = setTimeout(() => presence("cachee"), 500);
      return;
    }
    relireEtat();   // revenue sur la page : la direction a peut-être ouvert la suite
    presence("ouverte");
  });
  addEventListener("focus", () => { if (!E.fini) relireEtat(); });
  addEventListener("pagehide", auDepart);
  setInterval(() => { if (!E.fini) presence(document.hidden ? "cachee" : "ouverte"); }, BATTEMENT_MS);
}

/** La lecture du serveur appliquée. `douce` : la même étape à remplir qu'avant — rien n'est redessiné (la saisie en cours
 *  ne bouge pas). Le brouillon local passe par-dessus ce que le serveur n'avait pas encore gardé. */
function appliquer(d, douce) {
  const avant = E.q;
  const memeQuestionnaire = avant && avant.envoi === d.envoi && avant.etat === d.etat
    && JSON.stringify(avant.portes || null) === JSON.stringify(d.portes || null);
  E.q = d;
  E.textes = d.textes || {};
  monterEntete(d);
  if (d.etat === "remplace" || d.etat === "ferme") { finir(d.etat); return; }
  if (douce && memeQuestionnaire && E.vue && E.vue !== "message") return;
  E.envoi = Number(d.envoi) || 0;
  E.fini = false;
  const garder = {};
  for (const rang of E.sales) garder[rang] = E.reponses[rang];
  E.reponses = {};
  for (const [rang, texte] of Object.entries(d.reponses || {})) E.reponses[rang] = String(texte || "");
  if (d.etat === "envoye") { oublierLocal(); E.fini = true; E.sales.clear(); E.vue = "merci"; rendre(); return; }
  const permis = modifiables();
  const local = lireLocal();
  for (const [rang, texte] of Object.entries(garder)) if (permis.has(rang) && typeof texte === "string") E.reponses[rang] = texte;
  if (local) {
    for (const rang of local.sales || []) {
      if (permis.has(String(rang)) && typeof (local.reponses || {})[rang] === "string" && !(rang in garder)) { E.reponses[rang] = local.reponses[rang]; E.sales.add(String(rang)); }
    }
  }
  for (const rang of [...E.sales]) if (!permis.has(rang)) E.sales.delete(rang);
  if (d.etat === "attente") { E.vue = "attente"; rendre(); presence("ouverte"); return; }
  const nb = visibles().length;
  if (parEtapes()) E.etape = Math.max(0, indexCourante());
  else E.etape = Math.max(0, Math.min(nb - 1, local && Number.isInteger(local.etape) ? local.etape : (Number(d.etape) || 1) - 1));
  E.vue = "etape";
  rendre();
  presence("ouverte");
  if (E.sales.size) { majIndicateur(); enregistrer(); }
}

function monterEntete(d) {
  const nomServeur = sansEmoji(d.serveur && d.serveur.nom);
  $("#nom-page").textContent = texteEntete();
  $("#sous-titre").textContent = [nomServeur, sansEmoji(d.moi && d.moi.nom)].filter(Boolean).join(" · ");
  document.title = texteEntete() + (nomServeur ? " · " + nomServeur : "");
  document.body.classList.toggle("questionnaire-chef", chef());
  const logo = $("#logo-serveur");
  if (logo.dataset.pose === "1") return;
  logo.dataset.pose = "1";
  const src = srcSure(d.serveur && d.serveur.icone);
  if (src) {
    const img = h("img", { src, alt: "", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => remplacer(logo, (nomServeur || "?").slice(0, 1)), { once: true });
    remplacer(logo, img);
  } else remplacer(logo, (nomServeur || "?").slice(0, 1));
}

/** Le questionnaire n'attend plus de réponse ici (remplacé, terminé, lien expiré) : la page le dit, et n'écrit plus. */
function finir(quoi) {
  if (E.fini && E.vue === "message" && E.message === quoi) return;
  E.fini = true;
  if (quoi === "remplace" || quoi === "ferme") oublierLocal();
  E.vue = "message";
  E.message = quoi;
  rendre();
}

// ═══ LES VUES ═══════════════════════════════════════════════════════════════
function rendre() {
  const c = $("#contenu");
  try {
    if (E.vue === "etape") remplacer(c, ...vueEtape());
    else if (E.vue === "relire") remplacer(c, ...vueRelire());
    else if (E.vue === "attente") remplacer(c, ...vueAttente());
    else if (E.vue === "merci") remplacer(c, ...vueMerci());
    else remplacer(c, ...vueMessage(E.message));
  } catch (e) {
    console.error("[candidature] vue", E.vue, e);
    remplacer(c, titre("attention", "Cette page n'a pas pu s'afficher", "Recharge la page : tes réponses enregistrées t'attendent."));
  }
  majIndicateur();
}
function titre(nomIcone, texte, phrase) {
  return h("header", { classe: "titre-rubrique" }, h("span", { classe: "sceau-rubrique", "aria-hidden": "true" }, icone(nomIcone)),
    h("h1", {}, texte), h("p", {}, phrase || ""));
}
const enTete = () => titre(chef() ? "sabre" : "parchemin", texteTitre(), textePhrase());

// ─── Une étape ───
function vueEtape() {
  const etapes = visibles();
  const et = etapes[E.etape];
  const ecrire = !parEtapes() || et.courante;
  const tete = h("h2", { classe: "cand-etape-titre", tabindex: "-1", id: "etape-titre" },
    h("span", { classe: "cand-etape-num" }, libelleEtape(et.position || E.etape + 1)), et.titre ? h("span", { classe: "cand-etape-nom" }, et.titre) : null,
    et.envoyee ? h("span", { classe: "tampon vert cand-tampon" }, T("envoyee", "Envoyée")) : null);
  const manquantes = ecrire && E.manque ? et.questions.filter((q) => !repondue(q)).length : 0;
  const corps = h("section", { classe: "cand-etape" + (ecrire ? "" : " lecture"), "aria-labelledby": "etape-titre" }, tete,
    et.consigne ? texteRiche(et.consigne, "cand-consigne") : null,
    manquantes ? h("div", { classe: "bandeau rouge", role: "alert" }, icone("attention"), h("div", { classe: "bandeau-texte" }, T("manque", "Réponses manquantes : {n}. Chaque question en demande une.", { n: manquantes }))) : null,
    ecrire ? h("ol", { classe: "cand-questions" }, et.questions.map(question)) : lecture(et.questions, false));
  const premiere = E.etape === 0 && ecrire;
  return [
    enTete(),
    premiere ? h("section", { classe: "cand-intro" }, texteRiche(texteIntro())) : null,
    blocLiens(),
    progression(),
    corps,
    barre(...boutonsEtape(et)),
  ];
}
/** Le geste de gauche de la barre : au téléphone, sa seule flèche (son nom reste dit aux lecteurs d'écran). */
const boutonRetour = (libelle, onclick) => bouton(libelle, { classe: "discret cand-precedent", icone: "gauche", aria: libelle, titre: libelle, onclick });
function boutonsEtape(et) {
  const etapes = visibles();
  const precedent = E.etape > 0 ? boutonRetour(T("precedent", "Étape précédente"), () => allerEtape(E.etape - 1)) : h("span", { classe: "cand-vide" });
  if (!parEtapes()) {
    const derniere = E.etape === etapes.length - 1;
    return [precedent, derniere ? bouton(T("relire", "Relire et envoyer"), { classe: "principal cand-suivant", icone: "valider", onclick: () => allerRelire() })
      : bouton(T("suivant", "Étape suivante"), { classe: "principal cand-suivant", icone: "droite", onclick: () => allerEtape(E.etape + 1) })];
  }
  if (et.courante) {
    return [precedent, bouton(T("envoyer_etape", "Envoyer cette étape"), { classe: "principal cand-envoyer", icone: "cloche", onclick: () => envoyerEtape() })];
  }
  const ic = indexCourante();
  if (E.etape < etapes.length - 1) {   // une étape envoyée : la suivante (envoyée elle aussi, ou en cours)
    return [precedent, bouton(ic === E.etape + 1 ? T("en_cours", "Étape en cours") : T("suivant", "Étape suivante"), { classe: ic === E.etape + 1 ? "principal cand-suivant" : "cand-suivant", icone: "droite", onclick: () => allerEtape(E.etape + 1) })];
  }
  return [precedent, E.q.etat === "attente" ? bouton(T("attente.titre", "Réponses envoyées"), { classe: "cand-suivant", icone: "minuteur", onclick: () => { E.vue = "attente"; rendre(); remonter("#contenu"); } }) : h("span", { classe: "cand-vide" })];
}
function question(q) {
  const rang = String(q.rang);
  const id = "q-" + rang;
  const limite = Number(E.q.limite) || 400;
  const compteur = h("span", { classe: "cand-compteur", id: id + "-compte" });
  const vide = E.manque && !repondue(q);
  const zone = h("textarea", { classe: "saisie cand-reponse", id, rows: 4, maxlength: String(limite), placeholder: T("exemple", "Ta réponse"),
    "aria-describedby": id + "-compte", "aria-invalid": vide ? "true" : null, autocomplete: "off", spellcheck: "true", proprietes: { value: E.reponses[rang] || "" } });
  const majCompteur = () => { compteur.textContent = zone.value.length + " / " + limite; compteur.classList.toggle("proche", zone.value.length > limite * 0.9); };
  majCompteur();
  zone.addEventListener("input", () => { majCompteur(); zone.removeAttribute("aria-invalid"); saisir(rang, zone.value); });
  zone.addEventListener("focus", () => { if (E.rang !== Number(rang)) { E.rang = Number(rang); presenceRapide(); } });
  zone.addEventListener("blur", () => enregistrer());
  return h("li", { classe: "cand-question" + (repondue(q) ? " repondue" : "") },
    h("label", { for: id, classe: "cand-question-lib" },
      h("span", { classe: "cand-num" }, T("question", "Question {numero}", { numero: q.rang })),
      h("span", { classe: "cand-intitule" }, q.question)),
    zone, compteur);
}
/** « Où trouver les réponses » : un volet replié (les questions d'abord), ouvert d'un geste. */
function blocLiens() {
  const liens = (E.q && E.q.liens) || [];
  if (!liens.length) return null;
  const phrase = T("liens.phrase", "Toutes les réponses sont dans ces pages, ou à un clic depuis elles.");
  const d = h("details", { classe: "cand-liens" },
    h("summary", {}, icone("carte"), h("span", { classe: "cand-liens-titre" }, T("liens", "Où trouver les réponses")), h("span", { classe: "cand-liens-n" }, String(liens.length))),
    h("div", { classe: "cand-liens-corps" },
      phrase ? h("p", { classe: "aide" }, phrase) : null,
      h("ul", {}, liens.map((l) => h("li", {}, h("a", { href: l.url, classe: "cand-lien" }, icone("lien"),
        h("span", { classe: "cand-lien-texte" }, h("b", {}, l.titre), l.description ? h("span", {}, l.description) : null)))))));
  return d;
}
/** Les étapes (des jalons : la fiche, les envoyées, l'étape en cours, les suivantes sous cadenas), la barre et « 3 / 10
 *  répondues ». */
function progression() {
  const p = portes();
  const etapes = visibles();
  const qs = toutes();
  const faites = qs.filter(repondue).length;
  const pc = qs.length ? Math.round(100 * faites / qs.length) : 0;
  const total = Number(p.total) || etapes.length;
  const jalons = [];
  if (p.fiche) jalons.push(h("li", {}, h("span", { classe: "cand-jalon complete fiche", role: "img", title: T("etape", "Étape {numero} sur {total}", { numero: 1, total: total + 1 }) + " — " + T("fiche", "Ta fiche de candidature"),
    "aria-label": T("etape", "Étape {numero} sur {total}", { numero: 1, total: total + 1 }) + " — " + T("fiche", "Ta fiche de candidature") }, icone("coche"))));
  for (let k = 0; k < total; k++) {
    const et = etapes[k];
    const nom = libelleEtape(k + 1) + (et && et.titre ? " — " + et.titre : "");
    if (!et) {   // pas encore ouverte : comptée, sous cadenas
      jalons.push(h("li", {}, h("span", { classe: "cand-jalon fermee", role: "img", title: nom + " — " + T("fermee", "Pas encore ouverte"), "aria-label": nom + " — " + T("fermee", "Pas encore ouverte") }, icone("cadenas"))));
      continue;
    }
    const complete = parEtapes() ? !!et.envoyee : et.questions.every(repondue);
    const ici = (E.vue === "etape" && k === E.etape);
    jalons.push(h("li", {}, h("button", { type: "button", classe: "cand-jalon" + (ici ? " courante" : "") + (complete ? " complete" : "") + (et.courante ? " a-remplir" : ""),
      "aria-current": ici ? "step" : null, title: nom, "aria-label": nom + (complete ? (parEtapes() ? " — " + T("envoyee", "Envoyée") : " (complète)") : ""),
      onclick: () => allerEtape(k) }, complete && !ici ? icone("coche") : String(k + 1 + (p.fiche ? 1 : 0)))));
  }
  return h("div", { classe: "cand-progression" },
    total + (p.fiche ? 1 : 0) > 1 ? h("ol", { classe: "cand-jalons", "aria-label": "Les étapes" }, jalons) : null,
    h("div", { classe: "cand-avance" },
      h("span", { classe: "cand-barre-fond", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(qs.length), "aria-valuenow": String(faites),
        "aria-label": T("progression", "{faites} / {total} répondues", { faites, total: qs.length }) }, h("span", { classe: "cand-barre-plein", vars: { "--pc": pc + "%" } })),
      h("span", { classe: "cand-compte" }, T("progression", "{faites} / {total} répondues", { faites, total: qs.length }))));
}
/** La barre du bas (collée en bas de l'écran au téléphone) : les deux gestes, et ce qui est gardé. */
function barre(gauche, droite) {
  return h("nav", { classe: "cand-barre", "aria-label": "Navigation du questionnaire" },
    h("div", { classe: "cand-etat-enr", id: "etat-enr", role: "status", "aria-live": "polite" }),
    h("div", { classe: "cand-barre-boutons" }, gauche, droite));
}
function allerEtape(i) {
  const nb = visibles().length;
  E.etape = Math.max(0, Math.min(nb - 1, i));
  E.vue = "etape";
  E.manque = false;
  enregistrer();
  sauverLocal();
  rendre();
  presenceRapide();
  remonter("#etape-titre");
}
function allerRelire() {
  enregistrer();
  E.vue = "relire";
  rendre();
  presenceRapide();
  remonter("#relire-titre");
}
function remonter(cible) {
  scrollTo({ top: 0, behavior: reduit.matches ? "auto" : "smooth" });
  const el = $(cible);
  if (el) el.focus({ preventScroll: true });
}

// ─── Relire, puis envoyer (un envoi d'avant : tout d'un coup) ───
function vueRelire() {
  const etapes = visibles();
  const manque = toutes().filter((q) => !repondue(q)).length;
  const envoyerB = bouton(T("envoyer", "Envoyer mes réponses"), { classe: "principal cand-envoyer", icone: "cloche", onclick: () => envoyerTout(), disabled: manque > 0 });
  return [
    enTete(),
    progression(),
    h("section", { classe: "cand-relire", "aria-labelledby": "relire-titre" },
      h("h2", { classe: "cand-etape-titre", id: "relire-titre", tabindex: "-1" }, h("span", { classe: "cand-etape-num" }, T("relire.titre", "Relis tes réponses"))),
      h("p", { classe: "aide" }, T("relire.phrase", "Vérifie tout avant d'envoyer : une fois envoyées, tes réponses ne se modifient plus.")),
      manque ? h("div", { classe: "bandeau rouge", role: "alert" }, icone("attention"), h("div", { classe: "bandeau-texte" }, T("manque", "Réponses manquantes : {n}. Chaque question en demande une.", { n: manque }))) : null,
      etapes.map((et, i) => h("div", { classe: "cand-relire-etape" },
        h("div", { classe: "cand-relire-tete" },
          h("h3", {}, h("span", {}, libelleEtape(et.position || i + 1)), et.titre ? h("span", { classe: "cand-etape-nom" }, et.titre) : null),
          bouton(T("modifier", "Modifier"), { classe: "p discret", icone: "modifier", onclick: () => allerEtape(i) })),
        lecture(et.questions, true)))),
    barre(boutonRetour(T("modifier", "Modifier"), () => allerEtape(etapes.length - 1)), envoyerB),
  ];
}
/** Les questions et leurs réponses, en lecture seule. */
function lecture(questions, signalerManque) {
  return h("dl", { classe: "cand-lecture" }, questions.map((q) => {
    const texte = String(E.reponses[String(q.rang)] || "").trim();
    return h("div", { classe: "cand-lecture-q" + (texte ? "" : " manque") },
      h("dt", {}, h("span", { classe: "cand-num" }, T("question", "Question {numero}", { numero: q.rang })), h("span", { classe: "cand-intitule" }, q.question)),
      h("dd", {}, texte || h("span", { classe: signalerManque ? "cand-manque" : "aide" }, T("vide", "Pas encore de réponse"))));
  }));
}
async function confirmerEnvoi() {
  return confirmer({ titre: T("confirmer.titre", "Envoyer tes réponses ?"), texte: T("confirmer.texte", "Une fois envoyées, elles ne se modifient plus. La direction les lit."),
    libelleOk: parEtapes() ? T("envoyer_etape", "Envoyer cette étape") : T("envoyer", "Envoyer mes réponses"), iconeOk: "cloche", icone: "cloche" });
}
async function envoyerTout() {
  if (E.envoiEnCours || !(await confirmerEnvoi())) return;
  const corps = { reponses: {} };
  for (const q of toutes()) corps.reponses[String(q.rang)] = String(E.reponses[String(q.rang)] || "");
  await partir("envoyer", corps, toutes().map((q) => String(q.rang)));
}
/** Le passage d'étape : CETTE étape, toutes ses questions remplies, confirmée, envoyée une fois — puis l'attente. */
async function envoyerEtape() {
  const et = visibles().find((e) => e.courante);
  if (!et || E.envoiEnCours) return;
  const vides = et.questions.filter((q) => !repondue(q));
  if (vides.length) {
    E.manque = true;
    rendre();
    const z = $("#q-" + vides[0].rang);
    if (z) { z.scrollIntoView({ block: "center", behavior: reduit.matches ? "auto" : "smooth" }); z.focus({ preventScroll: true }); }
    return;
  }
  if (!(await confirmerEnvoi())) return;
  const corps = { etape: et.numero, reponses: {} };
  for (const q of et.questions) corps.reponses[String(q.rang)] = String(E.reponses[String(q.rang)] || "");
  await partir("envoyer_etape", corps, et.questions.map((q) => String(q.rang)));
}
async function partir(nom, corps, rangs) {
  E.envoiEnCours = true;
  const b = $(".cand-envoyer");
  if (b) b.disabled = true;
  clearTimeout(minuteurEnr);
  const r = await appel("POST", nom, corps, { delai: 25000 });
  E.envoiEnCours = false;
  if (r.ok || (r.status === 409 && ["envoye", "attente"].includes(r.donnees.etat))) {
    for (const rang of rangs) E.sales.delete(rang);
    E.manque = false;
    sauverLocal();
    const l = await appel("GET", "questionnaire", null);
    if (l.ok) appliquer(l.donnees);
    else if (r.donnees.etat === "envoye" || (r.donnees.portes && r.donnees.portes.mode === "unique")) { E.fini = true; oublierLocal(); E.vue = "merci"; rendre(); }
    else { E.q.etat = "attente"; E.vue = "attente"; rendre(); }
    remonter("#contenu");
    return;
  }
  if (b) b.disabled = false;
  if (r.fin) return;
  if (r.status === 409) { relireEtat(true); return; }
  toast(r.reseau || r.status === 0 ? T("envoi_impossible", "L'envoi n'est pas parti : vérifie ta connexion et réessaie.")
    : (r.donnees.erreur || T("envoi_impossible", "L'envoi n'est pas parti : vérifie ta connexion et réessaie.")), "erreur");
}

// ─── L'attente, merci, et les messages ───
function mesReponses(ouvert) {
  const etapes = visibles().filter((et) => !parEtapes() || et.envoyee);
  if (!etapes.length) return null;
  const d = h("details", { classe: "cand-liens cand-mes-reponses" },
    h("summary", {}, icone("parchemin"), h("span", { classe: "cand-liens-titre" }, T("merci.reponses", "Tes réponses"))),
    h("div", { classe: "cand-liens-corps" }, etapes.map((et, i) => h("div", { classe: "cand-relire-etape" },
      visibles().length > 1 || portes().fiche ? h("h3", {}, h("span", {}, libelleEtape(et.position || i + 1)), et.titre ? h("span", { classe: "cand-etape-nom" }, et.titre) : null) : null,
      lecture(et.questions, false)))));
  d.open = !!ouvert;
  return d;
}
function vueAttente() {
  return [
    enTete(),
    progression(),
    h("section", { classe: "cand-merci cand-attente", "aria-labelledby": "attente-titre" },
      h("span", { classe: "cand-sceau", "aria-hidden": "true" }, icone("minuteur")),
      h("div", { classe: "pile serree" }, h("h2", { classe: "cand-etape-titre", id: "attente-titre", tabindex: "-1" }, h("span", { classe: "cand-etape-num" }, T("attente.titre", "Réponses envoyées"))),
        texteRiche(texteAttente()))),
    mesReponses(false),
  ];
}
function vueMerci() {
  return [
    enTete(),
    h("section", { classe: "cand-merci", "aria-labelledby": "merci-titre" }, h("span", { classe: "cand-sceau", "aria-hidden": "true" }, icone("succes")),
      h("div", { classe: "pile serree" }, h("h2", { classe: "cand-etape-titre", id: "merci-titre", tabindex: "-1" }, h("span", { classe: "cand-etape-num" }, T("merci.titre", "Merci"))),
        texteRiche(texteMerci()))),
    mesReponses(false),
  ];
}
function vueMessage(quoi) {
  if (quoi === "hors_ligne_depart") {
    return [titre("hors_ligne", "Pas de connexion", "Le questionnaire n'a pas pu s'ouvrir."),
      h("section", { classe: "cand-message" }, h("p", {}, "Vérifie ta connexion, puis recharge la page."),
        bouton("Recharger", { classe: "principal", icone: "synchro", onclick: () => location.reload() }))];
  }
  const messages = {
    remplace: ["synchro", T("remplace.titre", "Ce questionnaire a été remplacé"), chef() ? T("chef.remplace", "Un nouveau questionnaire t'attend : ouvre le dernier message privé de la direction.\n-# A new questionnaire is waiting for you in your direct messages.")
      : T("remplace.texte", "Un nouveau questionnaire t'attend : dans ton ticket, touche « Répondre au questionnaire ».\n-# A new questionnaire is waiting for you in your ticket.")],
    ferme: ["cadenas", T("ferme.titre", "Ta candidature est terminée"), T("ferme.texte", "Ce questionnaire n'attend plus de réponse.\n-# Your application is over: this questionnaire no longer takes answers.")],
    expire: ["minuteur", T("expire.titre", "Ce lien n'est plus valable"), chef() ? T("chef.expire", "Rouvre le message privé de la direction et touche « Répondre au questionnaire » pour en recevoir un nouveau : tes réponses enregistrées t'y attendent.\n-# Open the leadership's direct message again to get a new link.")
      : T("expire.texte", "Dans ton ticket sur Discord, touche « Répondre au questionnaire » pour en recevoir un nouveau : tes réponses enregistrées t'y attendent.\n-# Ask for a new link in your ticket: your saved answers are kept.")],
  };
  const [ic, t, x] = messages[quoi] || messages.expire;
  return [E.q ? enTete() : titre("parchemin", texteEntete(), ""),
    h("section", { classe: "cand-message", "aria-labelledby": "message-titre" }, h("span", { classe: "cand-sceau gris", "aria-hidden": "true" }, icone(ic)),
      h("div", { classe: "pile serree" }, h("h2", { classe: "cand-etape-titre", id: "message-titre", tabindex: "-1" }, h("span", { classe: "cand-etape-num" }, t)), texteRiche(x)))];
}
function rendreMessage(quoi) { E.vue = "message"; E.message = quoi; rendre(); }

// ═══ LA SAISIE : le direct, le brouillon, la présence ══════════════════════
function saisir(rang, valeur) {
  E.reponses[rang] = valeur;
  E.sales.add(rang);
  E.rang = Number(rang);
  sauverLocal();
  majProgression();
  envoyerSaisie(rang);
  planifierEnregistrement();
}
function majProgression() {
  const ancien = $(".cand-progression");
  if (ancien) ancien.replaceWith(progression());
  for (const li of document.querySelectorAll(".cand-question")) {
    const zone = li.querySelector("textarea");
    if (zone) li.classList.toggle("repondue", !!zone.value.trim());
  }
}

// Le direct : la frappe part au plus toutes les 0,4 s (la dernière part toujours) ; rien n'est gardé par elle.
const saisiesEnAttente = new Set();
let derniereSaisie = 0, minuteurSaisie = 0;
function envoyerSaisie(rang) {
  saisiesEnAttente.add(rang);
  if (minuteurSaisie) return;
  minuteurSaisie = setTimeout(partirSaisies, Math.max(0, SAISIE_MS - (Date.now() - derniereSaisie)));
}
function partirSaisies() {
  minuteurSaisie = 0;
  if (E.fini || E.horsLigne) { saisiesEnAttente.clear(); return; }
  derniereSaisie = Date.now();
  for (const rang of [...saisiesEnAttente]) {
    saisiesEnAttente.delete(rang);
    appel("POST", "saisie", { rang: Number(rang), texte: E.reponses[rang] || "", etape: E.etape + 1 }).then((r) => {
      if (r.reseau || r.status === 0) passerHorsLigne();
      else if (r.status === 409) relireEtat(true);
    });
  }
}

// Le brouillon : gardé par le serveur 1,2 s après la dernière frappe (8 s au plus), au changement d'étape, quand la
// page se cache ou se ferme. Sans connexion : gardé ici, renvoyé dès que le réseau revient.
let minuteurEnr = 0, premiereSale = 0;
function planifierEnregistrement() {
  clearTimeout(minuteurEnr);
  if (!premiereSale) premiereSale = Date.now();
  const attente = Math.max(0, Math.min(ENREGISTRER_MS, ENREGISTRER_MAX_MS - (Date.now() - premiereSale)));
  minuteurEnr = setTimeout(enregistrer, attente);
  majIndicateur();
}
async function enregistrer() {
  clearTimeout(minuteurEnr);
  if (E.fini || !E.sales.size || E.envoiEnCours) return;
  if (E.enVol) { minuteurEnr = setTimeout(enregistrer, 400); return; }
  E.enVol = true;
  majIndicateur();
  const rangs = [...E.sales];
  const reponses = {};
  for (const rang of rangs) reponses[rang] = E.reponses[rang] || "";
  E.enVolTextes = reponses;
  // keepalive : un brouillon en route arrive même si la page se ferme pendant ce temps (la limite du navigateur :
  // 64 Ko en route — un brouillon plus gros part comme une requête ordinaire).
  const corps = { reponses, etape: E.etape + 1, rang: E.rang || 0 };
  const r = await appel("POST", "brouillon", corps, { keepalive: new TextEncoder().encode(JSON.stringify(corps)).length < 60000 });
  E.enVol = false;
  E.enVolTextes = null;
  if (r.ok) {
    for (const rang of rangs) if ((E.reponses[rang] || "") === reponses[rang]) E.sales.delete(rang);
    premiereSale = E.sales.size ? Date.now() : 0;
    E.horsLigne = false;
    sauverLocal();
    if (E.sales.size) planifierEnregistrement();
  } else if (r.status === 409 || r.status === 400) {
    relireEtat(true);   // le questionnaire a changé (étape envoyée ailleurs, candidature terminée) : la page le relit
  } else if (!r.fin) {
    if (r.reseau || r.status === 0) passerHorsLigne();
    minuteurEnr = setTimeout(enregistrer, REESSAI_MS);
  }
  majIndicateur();
}
function passerHorsLigne() {
  if (!E.horsLigne) { E.horsLigne = true; majIndicateur(); }
  clearTimeout(minuteurEnr);
  minuteurEnr = setTimeout(enregistrer, REESSAI_MS);
}
/** Ce que dit le petit mot du bas : enregistré, en cours, ou gardé ici faute de connexion. */
function majIndicateur() {
  const el = $("#etat-enr");
  if (!el) return;
  let genre = "", ic = null, texte = "";
  if (E.horsLigne) { genre = "hors-ligne"; ic = "hors_ligne"; texte = T("hors_ligne", "Pas de connexion : tes réponses sont gardées sur cet appareil et partiront dès son retour."); }
  else if (E.enVol || E.sales.size) { genre = "en-cours"; ic = "plume"; texte = T("enregistrement", "Enregistrement…"); }
  else if ([...modifiables()].some((rang) => String(E.reponses[rang] || "").trim())) { genre = "ok"; ic = "succes"; texte = T("enregistre", "Enregistré"); }
  el.className = "cand-etat-enr" + (genre ? " " + genre : "");
  remplacer(el, ic ? icone(ic) : null, texte ? h("span", {}, texte) : null);
}
/** La relecture légère (page revenue, focus, battement qui annonce un changement) : jamais plus d'une toutes les 4 s.
 *  `forcer` : tout de suite (un refus du serveur). */
let derniereRelecture = 0;
async function relireEtat(forcer) {
  if (E.fini || E.envoiEnCours || (!forcer && Date.now() - derniereRelecture < RELIRE_MIN_MS)) return;
  derniereRelecture = Date.now();
  const r = await appel("GET", "questionnaire", null);
  if (r.ok) appliquer(r.donnees, true);
}

// La présence : la page ouverte, cachée (le candidat cherche sur le wiki), fermée. Sa réponse dit où en est le
// questionnaire : la direction a ouvert la suite, ou la candidature est terminée → la page relit.
let dernierePresence = 0, minuteurPresence = 0;
function presence(vue, keepalive) {
  if (E.fini && vue !== "fermee") return;
  dernierePresence = Date.now();
  appel("POST", "presence", { vue, etape: E.etape + 1, rang: E.rang || 0 }, { keepalive: !!keepalive, discret: true }).then((r) => {
    if (!r.ok || E.fini || !E.q) return;
    const d = r.donnees;
    const change = (d.etat && d.etat !== E.q.etat) || (d.portes && JSON.stringify(d.portes) !== JSON.stringify(E.q.portes || null));
    if (change) relireEtat(true);
  });
}
/** Une question ou une étape changée : dite au direct (au plus une fois par seconde et demie). */
function presenceRapide() {
  if (minuteurPresence) return;
  minuteurPresence = setTimeout(() => { minuteurPresence = 0; presence(document.hidden ? "cachee" : "ouverte"); }, Math.max(0, 1500 - (Date.now() - dernierePresence)));
}
/** La page se ferme : ce qui n'était pas encore gardé part (keepalive), et le direct sait qu'elle est fermée. Rien n'est
 *  envoyé deux fois : ce que porte déjà le brouillon en route (keepalive lui aussi) reste à lui. Sans connexion, rien ne
 *  part : tout est gardé sur l'appareil et repart à la prochaine ouverture (des envois en double s'accumuleraient
 *  jusqu'au retour du réseau, puis arriveraient d'un coup). */
let minuteurCachee = 0;
function auDepart() {
  clearTimeout(minuteurCachee);
  sauverLocal();
  if (E.fini || !E.envoi) return;
  if (E.sales.size && !E.horsLigne) {
    const reponses = {};
    for (const rang of E.sales) {
      const texte = E.reponses[rang] || "";
      if (!E.enVolTextes || E.enVolTextes[rang] !== texte) reponses[rang] = texte;
    }
    if (Object.keys(reponses).length) appel("POST", "brouillon", { reponses, etape: E.etape + 1, rang: E.rang || 0 }, { keepalive: true, discret: true });
  }
  presence("fermee", true);
}

demarrer().catch((e) => {
  console.error("[candidature] démarrage", e);
  document.body.classList.remove("demarrage");
  remplacer($("#contenu"), titre("attention", "Le questionnaire n'a pas pu s'ouvrir", "Recharge la page dans un instant."));
});

// Pour les contrôles (lecture seule) : l'état de la page, jamais envoyé ailleurs.
window.__candidature = { etat: () => ({ vue: E.vue, etape: E.etape, sales: [...E.sales], horsLigne: E.horsLigne, envoi: E.envoi, mode: portes().mode }) };
