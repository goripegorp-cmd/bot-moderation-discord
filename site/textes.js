// textes.js — « Textes & noms » (La Capitainerie) : chaque texte que le bot écrit et chaque nom du site, réécrits par
// la direction. Enregistré, un texte est employé par le bot tout de suite (le prochain message le porte).
// Contrat : textes.py — GET textes · POST texte { cle, valeur, version } (hors ligne : la file, conflit 409 par version)
// · POST texte/defaut { cle, version } · GET textes/site (les noms du site changés, lus au démarrage).
// Ailleurs dans le site : `modifierTexte(cle)` ouvre l'éditeur d'un texte là où on le voit (le refus d'une candidature) ;
// `choisirTextes({ groupe, parties, prefixes })` ouvre une famille de textes (l'aperçu d'une carte d'événement, le
// guide du clan) ; `boutonRenommer(cat, rub)` : « Renommer » dans l'en-tête de chaque rubrique (son nom, sa phrase,
// ses sous-onglets).

import { h, icone, depuis, date, contient, remplacer, ajouter, quantite, nombre, copie } from "./dom.js";
import { etat, ecouter, enLigne, peutAgir, filtres, poserLibelles, P } from "./noyau.js";
import { lire, poster } from "./api.js";
import { charger, perime } from "./donnees.js";
import { mettreEnFile, renvoyer, garderServeur, file } from "./hors_ligne.js";
import { bouton, vide, tampon, recherche, segment, champ, saisie, zoneTexte, confirmer, pancarte, toast, squelettes, groupe, bandeau, majBoutonsReseau, nomDe } from "./ui.js";

const VARIABLE = /\{([a-z][a-z0-9_]{0,30})\}/g;
const CLE_LOCALE = "capitainerie.libelles";

// ─── Le verrou d'édition (équipe « Présence en direct », site/direct.js) ─────
// Branché après la fusion : `brancherVerrou(protegerEditeur)` — l'éditeur d'un texte prend alors le verrou « texte:<clé> ».
let proteger = null;
export function brancherVerrou(fn) { proteger = typeof fn === "function" ? fn : null; }

// ─── Les noms du site (au démarrage, puis avec les données) ─────────────────
// Relus au plus toutes les deux minutes : la cadence du site compte chaque requête (240 par minute et par session),
// et un nom change rarement — celui qu'on enregistre ici s'applique tout de suite, sans relire.
const FRAIS_MS = 120000;
let etagSite = null;
let valeursSite = {};
let luLe = 0;
function poserSite(valeurs) {
  valeursSite = Object.assign({}, valeurs || {});
  poserLibelles(valeursSite);
  try { localStorage.setItem(CLE_LOCALE, JSON.stringify({ valeurs: valeursSite, lu: luLe })); } catch (e) { /* stockage refusé : la mémoire suffit */ }
}
/** Les noms choisis sur le site : ceux gardés sur l'appareil tout de suite, puis ceux du serveur (s'ils datent). */
export async function chargerLibelles() {
  try {
    const garde = JSON.parse(localStorage.getItem(CLE_LOCALE) || "null");
    const valeurs = garde && typeof garde === "object" ? (garde.valeurs && typeof garde.valeurs === "object" ? garde.valeurs : garde) : null;
    if (valeurs) { valeursSite = Object.assign({}, valeurs); poserLibelles(valeursSite); luLe = Math.min(Number(garde.lu) || 0, Date.now()); }
  } catch (e) { /* rien de gardé */ }
  await relireLibelles();
}
async function relireLibelles() {
  if (etat.session !== "ok" || Date.now() - luLe < FRAIS_MS) return;
  luLe = Date.now();
  const r = await lire("textes/site", null, { etag: etagSite });
  if (!r.ok) { luLe = 0; return; }   // refusée ou sans réseau : retentée avec les prochaines données
  if (r.status === 304) { poserSite(valeursSite); return; }   // inchangés : l'heure de lecture est gardée
  if (!r.donnees || typeof r.donnees.valeurs !== "object") return;
  if (!r.horsLigne) etagSite = r.etag;
  poserSite(r.donnees.valeurs);
}
ecouter("donnees", () => { relireLibelles(); });
/** Un texte « site.… » enregistré : la navigation suit sans attendre la prochaine lecture. */
function suivreSite(t) {
  if (!t || !String(t.cle).startsWith("site.")) return;
  const v = Object.assign({}, valeursSite);
  if (t.modifie) v[t.cle] = t.valeur; else delete v[t.cle];
  etagSite = null;
  poserSite(v);
}

// ─── Les données (la file appliquée par-dessus) ─────────────────────────────
function trouver(T, cle) {
  for (const g of (T && T.groupes) || []) for (const t of g.textes || []) if (t.cle === cle) return t;
  return null;
}
/** Les modifications pas encore parties (hors ligne), montrées tout de suite, marquées. */
function appliquerFile(T) {
  const d = copie(T);
  for (const op of file.ops) {
    if (op.genre !== "texte") continue;
    const t = trouver(d, op.cle);
    if (!t) continue;
    t._op = op;
    t._attente = op.etat;
    if (op.etat === "refus" || op.etat === "erreur") continue;
    if (op.api === "texte") Object.assign(t, { valeur: op.corps.valeur, modifie: op.corps.valeur !== t.defaut });
    else if (op.api === "texte/defaut") Object.assign(t, { valeur: t.defaut, modifie: false });
  }
  return d;
}
/** Un texte enregistré : la liste est relue (la version canonique du serveur), sans attendre. */
function relire() {
  perime("textes");
  charger("textes", { forcer: true });
}
ecouter("file:succes", ({ op, corps }) => {
  if (!op || op.genre !== "texte") return;
  if (corps && corps.texte) suivreSite(corps.texte);
  relire();
});

// ─── Le Markdown de Discord, en nœuds (jamais d'HTML), les variables en pastilles ───
function enLigne_(texte, vars) {
  const out = [];
  let reste = String(texte), tampon_ = "";
  const pousser = (n) => { if (tampon_) { out.push(tampon_); tampon_ = ""; } out.push(n); };
  const MOTIFS = [
    [/^\\([\\*_~`|>#[\]()<:@{-])/, (m) => m[1]],
    [/^\{([a-z][a-z0-9_]{0,30})\}/, (m) => (vars.has(m[1]) ? h("span", { classe: "var-pastille", title: vars.get(m[1]) || m[1] }, m[1]) : m[0])],
    [/^\*\*(.+?)\*\*/, (m) => h("strong", {}, enLigne_(m[1], vars))],
    [/^__(.+?)__/, (m) => h("u", {}, enLigne_(m[1], vars))],
    [/^\*(?!\s)(.+?)\*/, (m) => h("em", {}, enLigne_(m[1], vars))],
    [/^~~(.+?)~~/, (m) => h("s", {}, enLigne_(m[1], vars))],
    [/^\|\|(.+?)\|\|/, (m) => h("span", { classe: "md-cache", title: "Texte caché" }, enLigne_(m[1], vars))],
    [/^`([^`]+)`/, (m) => h("code", {}, m[1])],
    [/^\[([^\]]+)\]\((https:\/\/[^\s)]+)\)/, (m) => h("a", { href: m[2] }, enLigne_(m[1], vars))],
    [/^<t:(-?\d+)(?::([tTdDfFR]))?>/, (m) => h("span", { classe: "md-heure" }, date(Number(m[1]), true))],
    [/^<@&\d+>/, () => h("span", { classe: "md-mention" }, "@rôle")],
    [/^<@!?\d+>/, () => h("span", { classe: "md-mention" }, "@membre")],
    [/^<#\d+>/, () => h("span", { classe: "md-mention" }, "#salon")],
    [/^<a?:\w+:\d+>/, () => h("span", { classe: "md-emoji-app", "aria-hidden": "true" })],
  ];
  while (reste) {
    let trouve = false;
    for (const [re, fn] of MOTIFS) {
      const m = re.exec(reste);
      if (!m) continue;
      const n = fn(m);
      if (typeof n === "string") tampon_ += n; else pousser(n);
      reste = reste.slice(m[0].length);
      trouve = true;
      break;
    }
    if (!trouve) { tampon_ += reste[0]; reste = reste.slice(1); }
  }
  if (tampon_) out.push(tampon_);
  return out;
}
/** Un texte tel que Discord l'affichera (titres, -# petit texte, citations, listes, gras, italique…) ; les variables
 *  déclarées en pastilles. */
export function apercuMarkdown(texte, variables) {
  const vars = new Map((variables || []).map((v) => [v.nom, v.description]));
  const s = h("span", { classe: "md" });
  for (const brut of String(texte ?? "").split("\n")) {
    let l = brut, classe = "md-ligne", m;
    if ((m = /^(#{1,3}) (.*)$/.exec(l))) { classe += " md-h" + m[1].length; l = m[2]; }
    else if ((m = /^-# (.*)$/.exec(l))) { classe += " md-petit"; l = m[1]; }
    else if ((m = /^>>> ?(.*)$/.exec(l)) || (m = /^> ?(.*)$/.exec(l))) { classe += " md-citation"; l = m[1]; }
    else if ((m = /^\s*[-*] (.*)$/.exec(l))) { classe += " md-liste"; l = m[1]; }
    else if ((m = /^\s*(\d+)\. (.*)$/.exec(l))) { classe += " md-liste-num"; l = m[2]; }
    const el = h("div", { classe }, enLigne_(l, vars));
    if (!l.trim()) el.classList.add("md-vide");
    ajouter(s, [el]);
  }
  return s;
}
/** La forme d'un texte, pour son aperçu : un nom du site, un bouton, ou un texte de Discord. */
const formeDe = (t) => (String(t.cle).startsWith("site.") ? "nom" : /\.bouton(\.|$)/.test(t.cle) || t.cle === "evenements.complet" ? "bouton" : "texte");
/** Un nom du site sur sa plaque ; la phrase d'une rubrique, dans la police du texte (comme sous le titre). */
const classeNom = (t, grand) => "texte-nom" + (grand ? " grand" : "") + (/\.phrase$/.test(t.cle) ? " phrase" : "");
/** Les guillemets et la ponctuation haute tiennent à leur mot (espaces insécables, à la française). */
const insecable = (s) => String(s || "").replace(/« /g, "« ").replace(/ ([»:;?!])/g, " $1");
function apercu(t, valeur, grand) {
  const v = valeur ?? t.valeur;
  const forme = formeDe(t);
  if (forme === "nom") return h("span", { classe: classeNom(t, grand) }, v || "(vide)");
  if (forme === "bouton") return h("div", { classe: "texte-discord bouton-seul" }, h("span", { classe: "discord-bouton" }, apercuMarkdown(v, t.variables)));
  if (!String(v || "").trim()) return h("p", { classe: "aide" }, "(vide : rien ne s'affiche)");
  return h("div", { classe: "texte-discord" }, apercuMarkdown(v, t.variables));
}

// ─── La rubrique ────────────────────────────────────────────────────────────
export function textes(vue) {
  const f = filtres("textes", { q: "", quoi: "tous" });
  const zone = h("div", { classe: "pile" }, squelettes(3));
  ajouter(vue, [
    h("p", { classe: "aide" }, "Touche « Modifier », écris, puis « Enregistrer » : le bot emploie ton texte tout de suite. « Revenir au texte d'origine » remet celui du départ."),
    h("div", { classe: "outils" },
      recherche(f.q, "Chercher un texte, un bouton, un nom…", (q) => { f.q = q; maj(); }),
      segment(f.quoi, [["tous", "Tous"], ["modifies", "Modifiés"]], (v) => { f.quoi = v; maj(); }, "Afficher")),
    zone]);
  const maj = async (forcer) => {
    const T = await charger("textes", { forcer });
    if (!zone.isConnected) return;
    if (!T || T.erreur) { remplacer(zone, vide("Textes indisponibles", (T && T.erreur) || "Réessaie dans un instant.", "hors_ligne")); return; }
    rendreListe(zone, appliquerFile(T), f);
  };
  maj();
  return { maj: () => maj(false), majJeu: () => maj(false), majFile: () => maj(false) };
}

// Ce que chaque groupe contient, en quelques mots (à droite de son titre).
const RESUMES = { recrutement: "le candidat et la carte de l'équipe", metiers: "le choix du métier, l'acceptation", guide: "le message d'accueil du clan",
  evenements: "boutons, cartes, rappels, listing", site: "pancartes, rubriques, onglets, affiches" };
function rendreListe(zone, T, f) {
  const q = f.q || "";
  const garde = (t) => (f.quoi !== "modifies" || t.modifie || t._attente) && (!q || contient([t.titre, t.aide, t.valeur, t.defaut, t.partie].join(" "), q));
  const blocs = [];
  for (const g of T.groupes || []) {
    const l = (g.textes || []).filter(garde);
    if (!l.length) continue;
    const modifies = (g.textes || []).filter((t) => t.modifie).length;
    const info = [RESUMES[g.cle] || "", modifies ? quantite(modifies, "modifié(s)") : ""].filter(Boolean).join(" · ");
    blocs.push(groupe({ titre: g.nom, compte: l.length, info, cle: "textes-" + g.cle, classe: "groupe-textes",
      ouvert: q || f.quoi === "modifies" ? true : undefined }, () => contenuGroupe(l)));
  }
  const modifies = (T.groupes || []).reduce((n, g) => n + (g.textes || []).filter((t) => t.modifie).length, 0);
  remplacer(zone,
    h("p", { classe: "meta" }, quantite((T.groupes || []).reduce((n, g) => n + (g.textes || []).length, 0), "texte(s)") + " · " + (modifies ? quantite(modifies, "modifié(s)") : "aucun modifié pour l'instant") + "."),
    ...(blocs.length ? blocs : [vide(f.quoi === "modifies" && !q ? "Aucun texte modifié" : "Rien ici", f.quoi === "modifies" && !q ? "Les textes que tu changes apparaissent ici." : "Change la recherche.", "plume")]));
  majBoutonsReseau(zone);
}
/** Les textes d'un groupe, par partie (« Les boutons », « La carte »…), dans leur ordre. */
function contenuGroupe(l, surModifier) {
  const parties = new Map();
  for (const t of l) { const p = t.partie || ""; if (!parties.has(p)) parties.set(p, []); parties.get(p).push(t); }
  const out = [];
  for (const [partie, ts] of parties) {
    if (partie) out.push(h("h3", { classe: "texte-partie" }, partie));
    out.push(h("ul", { classe: "textes-liste" }, ts.map((t) => ligneTexte(t, surModifier))));
  }
  return out;
}
const ETATS_OP = { attente: ["En attente d'envoi", "ambre"], conflit: ["Conflit", ""], refus: ["Refusé", ""], erreur: ["Échec", ""] };
function ligneTexte(t, surModifier) {
  const [libOp, coulOp] = ETATS_OP[t._attente] || [];
  const ouvrir = () => (surModifier ? surModifier(t) : ouvrirEditeur(t));
  return h("li", { classe: "texte-ligne" + (t.modifie ? " modifie" : "") + (t._attente === "attente" ? " en-attente" : "") + (t._attente === "conflit" || t._attente === "refus" ? " conflit" : "") },
    h("div", { classe: "texte-tete" },
      h("b", { classe: "texte-titre" }, insecable(t.titre)),
      t.modifie ? tampon("Modifié", "vert", true) : null,
      libOp ? tampon(libOp, coulOp, true) : null,
      peutAgir() ? bouton(t._attente === "conflit" ? "Régler" : "Modifier", { classe: "p" + (t._attente === "conflit" ? " principal" : ""), icone: t._attente === "conflit" ? "attention" : "plume", onclick: ouvrir }) : null),
    t.aide ? h("p", { classe: "texte-aide" }, t.aide) : null,
    apercu(t),
    t._attente === "refus" && t._op ? h("p", { classe: "meta alerte-texte" }, "Refusé par le serveur : " + (t._op.erreur || "réessaie.")) : null,
    t.modifie && t.maj_le ? h("p", { classe: "meta" }, "Modifié " + depuis(t.maj_le) + (t.maj_par ? " par " + nomDe(P(t.maj_par)) : "") + ".") : null);
}

// ─── L'éditeur ──────────────────────────────────────────────────────────────
/** Ouvre l'éditeur d'un texte depuis n'importe où. o.apres(texte) : appelé quand il est enregistré (la page qui l'a
 *  ouvert montre la nouvelle version tout de suite). */
export async function modifierTexte(cle, o = {}) {
  const T = await charger("textes");
  const t = T && !T.erreur ? trouver(appliquerFile(T), cle) : null;
  if (!t) { toast(T && T.erreur ? T.erreur : "Ce texte est introuvable.", "erreur"); return; }
  ouvrirEditeur(t, o);
}

function avertissementsDe(valeur, t) {
  const presentes = new Set([...String(valeur).matchAll(VARIABLE)].map((m) => m[1]));
  const origine = new Set([...String(t.defaut).matchAll(VARIABLE)].map((m) => m[1]));
  const noms = new Set((t.variables || []).map((v) => v.nom));
  return [...(t.variables || []).filter((v) => origine.has(v.nom) && !presentes.has(v.nom)).map((v) => "{" + v.nom + "} n'apparaît plus : " + v.description + " ne s'affichera pas."),
    ...[...presentes].filter((n) => !noms.has(n)).sort().map((n) => "{" + n + "} n'est pas une variable de ce texte : il s'affichera tel quel.")];
}
const propre = (valeur, t) => (t.lignes ? String(valeur).replace(/\r\n?/g, "\n").split("\n").map((x) => x.trimEnd()).join("\n").trim() : String(valeur).split(/\s+/).filter(Boolean).join(" "));

function inserer(champ_, texte, max) {
  const d = champ_.selectionStart ?? champ_.value.length, f = champ_.selectionEnd ?? d;
  const nouveau = champ_.value.slice(0, d) + texte + champ_.value.slice(f);
  if (nouveau.length > max) { toast(max + " caractères au plus.", "erreur"); return; }
  champ_.value = nouveau;
  champ_.focus();
  champ_.setSelectionRange(d + texte.length, d + texte.length);
  champ_.dispatchEvent(new Event("input", { bubbles: true }));
}
function barreMarkdown(zone, max) {
  const entourer = (avant, apres_ = avant) => () => {
    const d = zone.selectionStart, f = zone.selectionEnd, s = zone.value;
    if (s.length + avant.length + apres_.length > max) { toast(max + " caractères au plus.", "erreur"); return; }
    zone.value = s.slice(0, d) + avant + s.slice(d, f) + apres_ + s.slice(f);
    zone.focus();
    zone.setSelectionRange(d + avant.length, f + avant.length);
    zone.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const ligne = (prefixe) => () => {
    const d = zone.selectionStart, s = zone.value;
    if (s.length + prefixe.length > max) { toast(max + " caractères au plus.", "erreur"); return; }
    const debut = s.lastIndexOf("\n", d - 1) + 1;
    zone.value = s.slice(0, debut) + prefixe + s.slice(debut);
    zone.focus();
    zone.setSelectionRange(d + prefixe.length, d + prefixe.length);
    zone.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const b = (lib, aria, fn) => h("button", { classe: "md-bouton", type: "button", title: aria, "aria-label": aria, onclick: fn }, lib);
  return h("div", { classe: "barre-md", role: "toolbar", "aria-label": "Mise en forme" },
    b("G", "Gras", entourer("**")), b("I", "Italique", entourer("*")), b("S", "Souligné", entourer("__")), b("B", "Barré", entourer("~~")),
    b("T", "Titre", ligne("### ")), b("–", "Liste", ligne("- ")), b("«", "Citation", ligne("> ")), b("petit", "Petit texte gris", ligne("-# ")));
}

function ouvrirEditeur(t, o = {}) {
  if (!peutAgir()) { toast("Réservé au fondateur et à la direction.", "erreur"); return; }
  const op = t._op && (t._attente === "conflit" || t._attente === "refus") ? t._op : null;
  const depart = op && op.api === "texte" ? op.corps.valeur : t.valeur;
  let enregistre = false;
  const p = pancarte({ titre: insecable(t.titre), sous: t.partie || "", icone: "plume", taille: "large",
    garde: async (v) => v === "enregistre" || enregistre || propre(champ_.value, t) === propre(depart, t)
      || !!(await confirmer({ titre: "Quitter sans enregistrer ?", texte: "Ce que tu as écrit dans ce texte sera perdu.", libelleOk: "Quitter", style: "danger" })) });
  if (proteger) {
    try { proteger(p, "texte:" + t.cle, t.titre); } catch (e) { console.warn("[TEXTES][E1] verrou d'édition indisponible"); }
  }
  const champ_ = t.lignes
    ? zoneTexte({ name: "texte", rows: Math.min(14, Math.max(4, String(depart).split("\n").length + 1)), maxlength: t.max, spellcheck: "true" }, depart)
    : saisie({ name: "texte", value: depart, maxlength: t.max, spellcheck: "true" });
  champ_.classList.add("texte-champ");
  const compteur = h("span", { classe: "texte-compteur num", "aria-live": "polite" });
  const avert = h("div", { classe: "texte-avertissements", "aria-live": "polite" });
  const erreur = h("p", { classe: "champ-erreur", role: "alert", hidden: true });
  const vivant = h("div", { classe: "texte-apercu-vivant" });
  const etatLigne = h("p", { classe: "meta" });
  const maj = () => {
    const v = champ_.value;
    compteur.textContent = nombre(v.length) + " / " + nombre(t.max);
    compteur.classList.toggle("alerte", v.length > t.max * 0.95);
    const a = avertissementsDe(v, t);
    remplacer(avert, ...a.map((x) => h("p", { classe: "texte-avert" }, icone("attention", "ic-p"), h("span", {}, x))));
    remplacer(vivant, cadreApercu(t, v));
    erreur.hidden = true;
  };
  champ_.addEventListener("input", maj);
  const variables = (t.variables || []).length ? h("div", { classe: "texte-variables", role: "group", "aria-label": "Variables à insérer" },
    h("span", { classe: "champ-lib" }, "Variables"),
    t.variables.map((v) => h("button", { classe: "var-bouton", type: "button", title: v.description, "aria-label": "Insérer " + v.nom + " : " + v.description,
      onclick: () => inserer(champ_, "{" + v.nom + "}", t.max) }, h("span", { classe: "var-pastille" }, v.nom), h("span", { classe: "var-desc" }, v.description)))) : null;
  const conflitZone = h("div", {});
  const origine = groupe({ titre: "Le texte d'origine", icone: "parchemin", cle: "texte-origine" }, () => [cadreApercu(t, t.defaut),
    bouton("Le reprendre ici", { classe: "p discret", icone: "copier", onclick: () => { champ_.value = t.defaut; maj(); champ_.focus(); } })]);
  remplacer(etatLigne, t.modifie ? "Modifié " + depuis(t.maj_le) + (t.maj_par ? " par " + nomDe(P(t.maj_par)) : "") + "." : "C'est le texte d'origine.",
    formeDe(t) === "nom" ? " Enregistré, le nom change tout de suite sur le site." : " Enregistré, il est employé par le bot tout de suite.");
  ajouter(p.corps, [h("div", { classe: "texte-editeur" },
    h("div", { classe: "pile serree" },
      t.aide ? h("p", { classe: "aide" }, t.aide) : null,
      conflitZone,
      variables,
      t.lignes ? barreMarkdown(champ_, t.max) : null,
      champ(formeDe(t) === "nom" ? "Le nom" : "Le texte", champ_, { aide: t.lignes ? "Les boutons au-dessus mettent en forme : gras, italique, titre, liste, citation, petit texte gris." : "" }),
      h("div", { classe: "rangee entre" }, etatLigne, compteur),
      erreur, avert, origine),
    h("div", { classe: "collant pile serree" }, h("div", { classe: "apercu-titre" }, icone("oeil"), formeDe(t) === "nom" ? "Sur le site" : "Sur Discord"), vivant))]);
  maj();

  const fermerEnregistre = () => { enregistre = true; p.fermer("enregistre"); };
  const montrerConflit = (actuelle, mienne, garderMienne, prendreServeur) => {
    remplacer(conflitZone, h("div", { classe: "texte-conflit" },
      bandeau(h("span", {}, h("b", {}, "Ce texte a changé entre-temps"), actuelle.maj_par ? " (" + nomDe(P(actuelle.maj_par)) + ", " + depuis(actuelle.maj_le) + ")" : "", ". Choisis la version à garder."), "rouge"),
      h("div", { classe: "texte-deux" },
        h("div", { classe: "texte-version" }, h("span", { classe: "champ-lib" }, "Ta version"), apercu(t, mienne, true),
          bouton("Garder la mienne", { classe: "p principal", icone: "valider", onclick: garderMienne })),
        h("div", { classe: "texte-version" }, h("span", { classe: "champ-lib" }, "La version enregistrée"), apercu(t, actuelle.valeur, true),
          bouton("Prendre l'enregistrée", { classe: "p", icone: "restaurer", onclick: prendreServeur })))));
    conflitZone.scrollIntoView({ block: "nearest" });
  };
  if (op && op.etat === "refus") { erreur.textContent = "Refusé par le serveur : " + (op.erreur || "réessaie.") + " Corrige, puis enregistre."; erreur.hidden = false; }
  // Un conflit venu de la file (une modification faite hors ligne) : les deux versions, côte à côte.
  if (op && op.etat === "conflit" && op.conflit) {
    montrerConflit(op.conflit, op.api === "texte" ? op.corps.valeur : t.defaut,
      async () => { await renvoyer(op, Object.assign({}, op.corps, { version: op.conflit.version })); fermerEnregistre(); toast("Ta version repart au serveur.", "succes"); },
      async () => { await garderServeur(op); fermerEnregistre(); toast("La version enregistrée est gardée.", "succes"); });
  }

  const apres = (texte) => {
    relire();
    suivreSite(texte);
    if (o.apres) { try { o.apres(texte); } catch (e) { console.warn("[TEXTES][E2] la page n'a pas suivi le texte enregistré"); } }
  };
  const envoyer = async (api, corps, resume, objet) => {
    if (enLigne()) {
      const r = await poster(api, corps);
      const d = r.donnees || {};
      if (r.ok && d.texte) {
        apres(d.texte);
        fermerEnregistre();
        toast(formeDe(t) === "nom" ? "Enregistré : le nom est changé sur le site." : d.deja ? "C'était déjà le texte d'origine." : "Enregistré : le bot emploie ce texte dès maintenant.", "succes");
        return;
      }
      if (r.status === 409 && d.actuelle) {
        const mienne = api === "texte" ? corps.valeur : t.defaut;
        montrerConflit(d.actuelle, mienne,
          () => { t.version = d.actuelle.version; envoyer(api, Object.assign({}, corps, { version: d.actuelle.version }), resume, objet); },
          () => { apres(d.actuelle); fermerEnregistre(); toast("La version enregistrée est gardée.", "succes"); });
        return;
      }
      if (!r.reseau && r.status !== 0) { erreur.textContent = r.erreur || "Refusé par le serveur."; erreur.hidden = false; return; }
    }
    // Sans réseau : gardé sur l'appareil, envoyé au retour de la connexion (et réglé ici en cas de conflit).
    await mettreEnFile(api, corps, { genre: "texte", cle: t.cle, resume, objet });
    fermerEnregistre();
    toast("Gardé sur cet appareil : il partira au retour de la connexion, puis le bot l'emploiera.", "succes");
  };

  ajouter(p.pied, [
    t.modifie || (op && op.api === "texte") ? bouton("Revenir au texte d'origine", { classe: "discret danger gauche", icone: "restaurer", onclick: async () => {
      const ok = await confirmer({ titre: "Revenir au texte d'origine ?", icone: "restaurer", libelleOk: "Revenir à l'origine", style: "danger", taille: "",
        texte: "Le bot emploiera de nouveau le texte du départ :", contenu: [cadreApercu(t, t.defaut)] });
      if (!ok) return;
      if (op) await garderServeur(op);
      await envoyer("texte/defaut", { cle: t.cle, version: t.version }, "Texte « " + t.titre + " » : retour à l'origine",
        Object.assign({}, t, { valeur: t.defaut, modifie: false, _op: undefined }));
    } }) : null,
    bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }),
    bouton("Enregistrer", { classe: "principal", icone: "valider", onclick: async () => {
      const valeur = propre(champ_.value, t);
      if (!valeur && t.requis) { erreur.textContent = "Ce texte ne peut pas être vide : écris-en un, ou reviens au texte d'origine."; erreur.hidden = false; champ_.focus(); return; }
      if (valeur.length > t.max) { erreur.textContent = t.max + " caractères au plus."; erreur.hidden = false; return; }
      if (op) await garderServeur(op);   // la modification d'avant (refusée, en conflit) est remplacée par celle-ci
      await envoyer("texte", { cle: t.cle, valeur, version: op && op.conflit ? op.conflit.version : t.version }, "Texte « " + t.titre + " »",
        Object.assign({}, t, { valeur, modifie: valeur !== t.defaut, _op: undefined }));
    } })]);
  requestAnimationFrame(() => { champ_.focus(); if (champ_.setSelectionRange) champ_.setSelectionRange(champ_.value.length, champ_.value.length); });
}

/** L'aperçu d'un texte dans son cadre : la pancarte du site pour un nom, un message de Discord pour le reste. */
function cadreApercu(t, valeur) {
  if (formeDe(t) === "nom") return h("div", { classe: "texte-cadre-site" }, h("span", { classe: classeNom(t, true) }, valeur || "(vide)"));
  return h("div", { classe: "discord", role: "img", "aria-label": "Aperçu du texte tel qu'il apparaîtra sur Discord" },
    h("div", { classe: "discord-auteur" }, h("span", { classe: "discord-av" }, "G"), h("b", {}, "GoRP"), h("span", { classe: "discord-app" }, "APP")),
    h("div", { classe: "discord-message" }, h("div", { classe: "discord-carte" }, apercu(t, valeur))));
}

// ─── Les textes d'un groupe, depuis une autre page ──────────────────────────
/** o : { groupe?, parties?: [noms], prefixes?: [débuts de clé], titre, surFermer? } — la liste de ces textes, chacun avec
 *  « Modifier ». */
export async function choisirTextes(o = {}) {
  const p = pancarte({ titre: o.titre || "Les textes", sous: "Enregistrés, ils sont employés tout de suite.", icone: "plume", taille: "large",
    surFermer: () => { if (o.surFermer) o.surFermer(); } });
  const zone = h("div", { classe: "pile" }, squelettes(2));
  ajouter(p.corps, [zone]);
  ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
  const maj = async (forcer) => {
    const T = await charger("textes", { forcer });
    if (p.fermee() || !zone.isConnected) return;
    if (!T || T.erreur) { remplacer(zone, vide("Textes indisponibles", (T && T.erreur) || "Réessaie dans un instant.", "hors_ligne")); return; }
    const l = (appliquerFile(T).groupes || []).flatMap((g) => g.textes || []).filter((t) => (!o.groupe || t.groupe === o.groupe)
      && (!o.parties || o.parties.includes(t.partie)) && (!o.prefixes || o.prefixes.some((x) => String(t.cle).startsWith(x))));
    remplacer(zone, ...(l.length ? contenuGroupe(l) : [vide("Aucun texte", "", "plume")]));
    majBoutonsReseau(zone);
  };
  const stop = [ecouter("jeu", () => maj(false)), ecouter("file", () => maj(false))];
  p.dlg.addEventListener("close", () => stop.forEach((f) => f()));
  maj();
}

/** « Renommer » dans l'en-tête d'une rubrique : son nom, sa phrase et ses sous-onglets, là où on les lit. `apres()` :
 *  appelé à la fermeture si un nom a changé (la rubrique se redessine avec ses nouveaux onglets). */
export function boutonRenommer(cat, rub, apres) {
  return bouton("Renommer", { classe: "p discret renommer-rubrique", icone: "plume", titre: "Le nom de cette rubrique, sa phrase et ses sous-onglets (Textes & noms)",
    onclick: () => {
      let change = false;
      const stop = ecouter("libelles", () => { change = true; });
      choisirTextes({ prefixes: ["site.rub." + cat + "." + rub + ".", "site.sous." + cat + "." + rub + "."], titre: "Les noms de cette rubrique",
        surFermer: () => { stop(); if (change && apres) apres(); } });
    } });
}
