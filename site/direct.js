// direct.js — la présence en direct et les verrous d'édition : « À bord » (qui est sur le site, où, ce qu'il modifie)
// et la ZONE VERROUILLÉE (un objet en cours de modification par quelqu'un d'autre ne se touche pas : cadenas, lecture
// seule, « Demander la main », puis la dernière version relue quand il se libère).
//
// Le serveur : `tableau.py`, section « présence en direct » — une WebSocket par onglet (/tableau/espace/direct), sinon
// l'interrogation de `api/direct/etat` toutes les 10 s (un proxy qui bloque la WebSocket). Rien de bloquant : sans
// direct, le site reste utilisable, et le serveur refuse quand même d'écrire un objet tenu par quelqu'un d'autre (423).
//
// ─── L'API (pour les autres modules) ──────────────────────────────────────────────────────────────────────────────
//   demarrerDirect()                  une fois, au démarrage (app.js) : la connexion, et « À bord » dans l'en-tête.
//   presents()                        [{ id, nom, avatar, couleur, pages: [{ cle, lib, depuis }], onglets, depuis, moi,
//                                       modifie: [{ objet, titre, depuis }] }] — les personnes à bord, moi en dernier.
//   verrouDe(objet)                   { objet, titre, id, nom, avatar, couleur, depuis, moi, ici, ailleurs } | null
//                                       moi : tenu par moi ; ici : par cet onglet ; ailleurs : aussi par un autre de mes onglets.
//   prendre(objet, titre)             Promise<{ ok, par?, nom?, horsDirect? }> — la main sur l'objet (réentrant pour soi).
//   lacher(objet)                     rend la main (une fois la file d'envoi partie : jamais avant la modification).
//   surDirect(fn)                     fn({ type, objet?, id? }) à chaque changement ; rend la fonction « se désabonner ».
//   badgeVerrou(objet)                un élément vivant : le cadenas et la personne si l'objet est pris par un autre.
//   avecVerrou(el, objet)             pose ce badge sur une carte (la carte est alors marquée « prise ») ; rend la carte.
//   protegerEditeur(pancarte, objet, titre, { relire, surPlace })
//                                     l'éditeur prend la main à l'ouverture et la rend à la fermeture. Pris par un autre :
//                                     lecture seule, « Demander la main » ; quand il se libère, `relire()` relit la
//                                     dernière version et rouvre l'éditeur (surPlace : le redessine dans la même
//                                     pancarte). Sans saisie depuis 5 min : la main est rendue (la saisie reste à l'écran).
//                                     Rend { changerObjet(objet, titre), etat(), finir() }.
//   protegerZone(zone, objet, titre, { relire, des, compact, quitter })
//                                     la même chose pour une zone de la page (composeur, réglages en ligne) ; des :
//                                     "ouverture" (la main tout de suite) ou "saisie" (à la première modification, rendue
//                                     quand la zone quitte la page) ; compact : pas de bandeau (une ligne de tableau).
//   siLibre(objet)                    avant un geste rapide (renommer, supprimer) : false, avec un avis, si quelqu'un
//                                     d'autre le tient.
//   cleObjet(objet)                   la clé telle que le serveur la garde (100 caractères au plus).
//
// Les clés (les mêmes que tableau.VERROUS_ROUTES) : affiche:<id> · affiche-membre:<membre> (nouvelle affiche) ·
// element:<type>:<cle> · catalogue:types · question:<id> · modele:<id> · questionnaire:liens · questionnaire:reglages ·
// dossier:<ticket> · brouillon:<id> · evenement:<id> · metiers:reglages · role:<type>:<cle> · nettoyage:<règle> ·
// texte:<cle> (l'onglet « Textes & noms »). Le titre est un groupe nominal : « l'affiche de Kolax », « les liens du
// questionnaire » — la page écrit « Mira modifie l'affiche de Kolax ».

import { h, icone, BASE, remplacer, ajouter, initiales, srcSure, sansEmoji, retarder, telephone, uuid, quantite } from "./dom.js";
import { etat, emettre, ecouter, CATEGORIES, aller, enLigne, suivreAlias, libelle } from "./noyau.js";
import { lire, poster, sessionTerminee, url } from "./api.js";
import * as HL from "./hors_ligne.js";
import { perime, charger, vue as vueJeu } from "./donnees.js";
import { bouton, toast } from "./ui.js";

// Huit encres du livre de bord : la couleur du liseré d'une personne, toujours la même (FNV de son identifiant).
const PALETTE = ["#3f6b3a", "#1f4e5a", "#8e2a24", "#a8641c", "#5e3a4e", "#4a5560", "#7a4b2a", "#7a5a22"];
const RE_OBJET = /^[a-z][a-z0-9_-]{0,29}:[A-Za-z0-9_.:@~-]{1,270}$/;
const ESSAIS_AVANT_REPLI = 3;          // ouvertures ratées de la WebSocket avant l'interrogation
const REESSAI_WS = 120000;             // ms : en interrogation, la WebSocket est retentée de temps en temps
const POPOVER = typeof HTMLElement !== "undefined" && "showPopover" in HTMLElement.prototype;
const LECTURE = new Set(["autre", "rendu", "relecture", "libre"]);
// Les sous-pages qui ont un nom (les autres ne sont pas dites) ; un nom renommé sur le site (Textes & noms) passe devant.
// 27/10/2026 : la navigation regroupée — les vues d'Équipage, les familles de Tickets, les onglets de Réglages.
const SOUS = { questionnaire: "Questionnaire", "en-cours": "En cours", decidees: "Décidées", composer: "Composer", brouillons: "Brouillons",
  "a-venir": "À venir", passes: "Passés", questions: "Questions", idees: "Idées", droits: "Droits des salons", sondages: "Sondages",
  entraide: "Entraide", annonces: "Annonces", candidatures: "Candidatures", chefs: "Chefs d'équipe", reglages: "Réglages", publiees: "Publiées",
  fiches: "Fiches techniques", equipes: "Équipes", normaux: "Tickets normaux", clan: "Clan · RELL Seas", textes: "Textes & noms", nettoyage: "Nettoyage",
  avis: "Idées & sondages" };
// Les jeux de données que relit une page quand quelqu'un d'autre écrit (« ecrit »).
const JEUX = { affiche: ["affiches"], "affiche-membre": ["affiches"], element: ["catalogue"], catalogue: ["catalogue"], question: ["banque"],
  modele: ["banque"], questionnaire: ["banque"], dossier: ["dossier"], brouillon: ["evenements"], evenement: ["evenements"], role: ["roles"],
  metiers: ["metiers_reglages", "roles"], nettoyage: ["nettoyage"] };

const D = {
  mode: "arret",        // arret · connexion · ws · http · coupe · fini
  ws: null, essais: 0, ratees: 0, minuteur: 0, battement: 0, tour: 0, essaiWs: 0, resync: false,
  moi: "", onglet: "", ecart: 0, page: "",
  cfg: { bat: 20, bail: 60, inactif: 300, tour: 10 },
  personnes: new Map(),  // id → { id, nom, av, pages: [[cle, t]], n, d }
  verrous: new Map(),    // objet → { o, ti, id, d, nb }
  tenus: new Map(),      // objet → { titre, veut, statut (demande · tenu · refuse · reprendre · perdu · horsdirect), n, attentes }
  emprises: new Set(),
  ecouteurs: new Set(),
};

// ─── Petits outils ──────────────────────────────────────────────────────────
function fnv(s) {
  let x = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 0x01000193) >>> 0; }
  return x >>> 0;
}
/** La clé d'un objet telle que le serveur la garde (tableau.objet_direct) : null si elle est invalide. */
export function cleObjet(o) {
  if (typeof o !== "string" || o.length > 300 || !RE_OBJET.test(o)) return null;
  return o.length <= 100 ? o : o.slice(0, 91) + "~" + fnv(o).toString(16).padStart(8, "0");
}
export const couleurDe = (id) => PALETTE[fnv(String(id || "")) % PALETTE.length];
const local = (t) => (Number(t) || 0) - D.ecart;      // une heure du serveur, sur l'horloge de cet appareil
const vivant = () => D.mode === "ws" || D.mode === "http";
function duree(t) {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return "depuis un instant";
  if (s < 3600) return "depuis " + Math.round(s / 60) + " min";
  const m = Math.round((s % 3600) / 60);
  if (s < 86400) return "depuis " + Math.floor(s / 3600) + " h" + (m ? " " + String(m).padStart(2, "0") : "");
  return "depuis " + Math.floor(s / 86400) + " j";
}
const majuscule = (s) => s.charAt(0).toUpperCase() + s.slice(1);
/** « Capitainerie › Affiches » : le libellé d'une page (catégorie › rubrique › sous-page connue). */
export function libellePage(cle) {
  const bruts = String(cle || "").split("/");
  // 26/10/2026 : le site de l'équipage (`/tableau/equipage/`, ses trois onglets) n'est pas une catégorie de ce site-ci.
  if (bruts[0] === "site-equipage") return ["Site de l'équipage", { accueil: "Accueil", equipage: "L'équipage", fiche: "Ma fiche" }[bruts[1]] || ""].filter(Boolean).join(" › ");
  // 27/10/2026 : une page d'avant la navigation regroupée (un onglet pas encore rechargé) est dite à sa place d'aujourd'hui.
  const [c, r, s] = suivreAlias(bruts.filter(Boolean));
  const cat = CATEGORIES.find((x) => x.cle === c);
  if (!cat) return c ? majuscule(c) : "Le site";
  const rub = cat.rubriques.find((x) => x.cle === r);
  const sous = s && SOUS[s] ? libelle("site.sous." + c + "." + r + "." + s.replace(/-/g, "_"), SOUS[s]) : "";
  return [cat.court || cat.titre, rub ? rub.titre : "", sous].filter(Boolean).join(" › ");
}
function signaler(ev) {
  for (const f of [...D.ecouteurs]) { try { f(ev); } catch (e) { /* un abonné en échec n'arrête pas les autres */ } }
}
export function surDirect(fn) { D.ecouteurs.add(fn); return () => D.ecouteurs.delete(fn); }

// ─── Ce que la page sait ────────────────────────────────────────────────────
export function presents() {
  return [...D.personnes.values()].map((p) => ({
    id: p.id, nom: sansEmoji(p.nom) || "Sans nom", avatar: p.av || "", couleur: couleurDe(p.id), moi: p.id === D.moi,
    pages: (p.pages || []).map(([cle, t]) => ({ cle, lib: libellePage(cle), depuis: local(t) })), onglets: p.n || 1, depuis: local(p.d),
    modifie: [...D.verrous.values()].filter((v) => v.id === p.id).map((v) => ({ objet: v.o, titre: v.ti, depuis: local(v.d) })),
  })).sort((a, b) => (a.moi - b.moi) || a.depuis - b.depuis);
}
export function verrouDe(objet) {
  const o = cleObjet(objet);
  const v = o && D.verrous.get(o);
  if (!v) return null;
  const p = D.personnes.get(v.id) || {};
  const t = D.tenus.get(o);
  const ici = !!t && t.statut === "tenu";
  const moi = v.id === D.moi;
  return { objet: o, titre: v.ti || "", id: v.id, nom: sansEmoji(p.nom) || "Quelqu'un", avatar: p.av || "", couleur: couleurDe(v.id),
    depuis: local(v.d), moi, ici, ailleurs: moi && (v.nb || 0) > (ici ? 1 : 0) };
}

// ═══ LA CONNEXION ═══════════════════════════════════════════════════════════
export function demarrerDirect() {
  if (D.mode !== "arret") return;
  D.mode = "connexion";
  D.onglet = uuid().replace(/-/g, "").slice(0, 24);
  D.page = pageCourante();
  monterBord();
  addEventListener("hashchange", () => setTimeout(signalerPage, 0));
  document.addEventListener("visibilitychange", surVisibilite);
  addEventListener("pagehide", surDepart);
  ecouter("session", () => { if (etat.session !== "ok") arreter(); });
  ecouter("reseau", () => { if (etat.reseau.enLigne && D.mode === "coupe") reconnecter(400); });
  ecouter("file:verrou", ({ op }) => {
    if (op._avisVerrou) return;
    op._avisVerrou = true;
    const nom = (op.verrou && op.verrou.nom) || "Quelqu'un";
    toast("« " + (op.resume || "Ta modification") + " » attend : " + nom + " modifie cet élément en ce moment. Elle partira dès que ce sera libre.", "");
  });
  setInterval(veille, 15000);
  connecter();
}

/** Le direct ne concerne pas cette session (une autre portée que la tête), ou le serveur ne l'a pas : il s'arrête, sans
 *  bruit, et « À bord » disparaît. Le site reste utilisable (aucune main n'est demandée : les éditeurs restent ouverts). */
function horsPortee() {
  arreter();
  if (bord) { bord.remove(); bord = null; }
}
function arreter() {
  D.mode = "fini";
  clearTimeout(D.minuteur); clearTimeout(D.tour); clearTimeout(D.essaiWs); clearInterval(D.battement);
  if (D.ws) { const ws = D.ws; D.ws = null; try { ws.close(1000); } catch (e) { /* déjà fermée */ } }
  majBord();
}

function connecter() {
  if (D.mode === "fini" || etat.session !== "ok") return;
  clearTimeout(D.minuteur);
  if (!("WebSocket" in window)) { passerHttp(); return; }
  if (D.mode !== "http") D.mode = "connexion";
  let ws;
  try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + BASE + "/direct"); } catch (e) { finSocket(null, 1006, false); return; }
  D.ws = ws;
  let ouverte = false;
  ws.onopen = () => {
    ouverte = true;
    D.essais = 0; D.ratees = 0;
    clearTimeout(D.tour); clearTimeout(D.essaiWs);
    D.mode = "ws"; D.resync = true;
    // L'onglet donne son identifiant : s'il interrogeait (sans WebSocket), le serveur lui rend ses verrous.
    ws.send(JSON.stringify({ t: "bonjour", page: D.page, onglet: D.onglet }));
    majBord();
  };
  ws.onmessage = (ev) => { let m = null; try { m = JSON.parse(ev.data); } catch (e) { return; } recevoir(m); };
  ws.onclose = (ev) => finSocket(ws, ev.code, ouverte);
}

function finSocket(ws, code, ouverte) {
  if (ws && D.ws !== ws) return;
  D.ws = null;
  clearInterval(D.battement);
  if (D.mode === "fini") return;
  if (code === 4401 || code === 4403) {   // session finie, accès retiré : la page le dit, plus de reconnexion
    sessionTerminee(code === 4403 ? "Accès retiré." : "Session expirée.");
    arreter();
    return;
  }
  if (code === 4406) { horsPortee(); return; }   // une session qui n'est pas celle de la tête : le direct ne la concerne pas
  for (const t of D.tenus.values()) if (t.statut === "tenu" || t.statut === "demande") t.statut = "reprendre";
  if (!ouverte) D.ratees += 1;
  D.essais += 1;
  if (D.mode === "http") { planifierEssaiWs(); return; }
  if (!ouverte && D.ratees >= ESSAIS_AVANT_REPLI) { passerHttp(); planifierEssaiWs(); return; }
  D.mode = "coupe";
  majBord();
  signaler({ type: "mode" });
  const base = code === 4429 ? 60000 : Math.min(60000, 1000 * Math.pow(2, Math.min(D.essais - 1, 6)));
  reconnecter(base * (0.75 + Math.random() * 0.5));
}
function reconnecter(ms) {
  clearTimeout(D.minuteur);
  D.minuteur = setTimeout(() => {
    if (D.mode === "fini") return;
    if (!etat.reseau.enLigne || document.hidden) { reconnecter(15000 * (0.75 + Math.random() * 0.5)); return; }
    connecter();
  }, ms);
}

// ─── Sans WebSocket : l'interrogation (automatique et silencieuse) ─────────
function passerHttp() {
  if (D.mode === "fini") return;
  D.mode = "http"; D.resync = true;
  majBord();
  signaler({ type: "mode" });
  interroger();
}
function planifierEssaiWs() {
  clearTimeout(D.essaiWs);
  D.essaiWs = setTimeout(() => { if (D.mode === "http" && !document.hidden) connecter(); else planifierEssaiWs(); }, REESSAI_WS * (0.8 + Math.random() * 0.4));
}
async function interroger() {
  clearTimeout(D.tour);
  if (D.mode !== "http" || etat.session !== "ok") return;
  if (enLigne()) {
    const r = await lire("direct/etat", { onglet: D.onglet, page: D.page, cache: document.hidden ? 1 : 0 });
    if (D.mode !== "http") return;
    if (r.ok && r.donnees && !r.horsLigne) {
      recevoir(r.donnees);
      for (const m of r.donnees.msgs || []) recevoir(m);
    } else if (r.status === 403 || r.status === 404) {   // pas pour cette session, ou un serveur sans direct : on s'arrête
      horsPortee();
      return;
    }
  }
  clearTimeout(D.tour);
  D.tour = setTimeout(interroger, (document.hidden ? 60 : D.cfg.tour || 10) * 1000);
}
async function envoyerHttp(m, deuxieme) {
  const r = await poster("direct/envoi", Object.assign({ onglet: D.onglet }, m));
  if (r.ok && r.donnees) { for (const x of r.donnees.r || []) recevoir(x); return; }
  if (r.status === 409 && !deuxieme) { await interroger(); envoyerHttp(m, true); return; }
  if (m.t === "prendre") recevoir({ t: "refuse", o: m.o, err: "direct" });   // sans réponse : on n'empêche pas d'écrire
}
function envoyer(m) {
  if (D.mode === "ws" && D.ws && D.ws.readyState === 1) { D.ws.send(JSON.stringify(m)); return true; }
  if (D.mode === "http") { envoyerHttp(m); return true; }
  return false;
}

// ─── Le battement, la page, l'onglet caché ──────────────────────────────────
const tientQuelqueChose = () => [...D.tenus.values()].some((t) => t.statut === "tenu");
function demarrerBattement() {
  clearInterval(D.battement);
  D.battement = setInterval(() => {
    if (D.mode === "ws" && !document.hidden && tientQuelqueChose()) envoyer({ t: "vivant" });
  }, (D.cfg.bat || 20) * 1000);
}
function surVisibilite() {
  if (document.hidden) {   // caché : plus de battement ; le serveur garde les verrous de cet onglet plus longtemps
    if (D.mode === "ws" && tientQuelqueChose()) envoyer({ t: "vivant", cache: true });
    return;
  }
  if (D.mode === "ws" && tientQuelqueChose()) envoyer({ t: "vivant" });
  if (D.mode === "http") interroger();
  if (D.mode === "coupe") reconnecter(300);
  for (const em of [...D.emprises]) em.surVisible();
}
/** La page se ferme (onglet fermé, rechargement, autre adresse) : la main est rendue aux autres tout de suite, sans
 *  attendre la grâce du serveur — sauf si une modification est encore en route (la file la renverra ; la grâce garde
 *  la main jusque-là). Une coupure du réseau, elle, garde la grâce. */
function surDepart() {
  if (!vivant() || HL.file.enCours || HL.enAttente().some((op) => !op.verrou)) return;
  for (const [o, t] of D.tenus) {
    if (t.statut !== "tenu") continue;
    if (D.mode === "ws") envoyer({ t: "lacher", o });
    else fetch(url("direct/envoi"), { method: "POST", keepalive: true, credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Tableau": "1" },
      body: JSON.stringify({ onglet: D.onglet, t: "lacher", o }) }).catch(() => { /* la page part : le bail du serveur s'en chargera */ });
    t.statut = "reprendre";   // une page gardée par le navigateur (retour arrière) la redemande à sa reconnexion
  }
}
function pageCourante() {
  const r = etat.route || {};
  return [r.cat, r.rub, r.sous].filter(Boolean).join("/").toLowerCase().replace(/[^a-z0-9_/-]/g, "").slice(0, 150);
}
const signalerPage = retarder(() => {
  const p = pageCourante();
  if (p === D.page) return;
  D.page = p;
  if (D.mode === "ws") envoyer({ t: "page", page: p });
}, 250);

// ─── Ce qui arrive du serveur ───────────────────────────────────────────────
function recevoir(m) {
  if (!m || typeof m !== "object") return;
  switch (m.t) {
    case "etat": appliquerEtat(m); break;
    case "present": if (m.p && m.p.id) { D.personnes.set(m.p.id, m.p); majBord(); signaler({ type: "present", id: m.p.id }); } break;
    case "absent": D.personnes.delete(m.id); majBord(); signaler({ type: "absent", id: m.id }); break;
    case "page": { const p = D.personnes.get(m.id); if (p) { p.pages = m.pages || []; p.n = m.n || 1; majBord(); } signaler({ type: "page", id: m.id }); break; }
    case "verrou": if (m.v && m.v.o) { D.verrous.set(m.v.o, m.v); surVerrou(m.v); } break;
    case "libre": surLibre(m.o); break;
    case "ecrit": surEcrit(Array.isArray(m.o) ? m.o : [], m.id); break;
    case "pris": surPris(m); break;
    case "refuse": surRefuse(m); break;
    case "demande": surDemande(m); break;
    case "demandee": for (const em of emprisesDe(m.o)) em.demandeEnvoyee(!!m.deja); break;
    default: break;
  }
}
function appliquerEtat(m) {
  D.moi = String(m.moi || D.moi);
  if (m.s) D.ecart = m.s - Date.now() / 1000;
  Object.assign(D.cfg, m.cfg || {});
  D.personnes = new Map((m.p || []).map((p) => [p.id, p]));
  const avant = D.verrous;
  D.verrous = new Map((m.v || []).map((v) => [v.o, v]));
  // Ce qui a changé depuis la dernière fois (une reconnexion, ou le tour suivant sans WebSocket) : comme des deltas.
  for (const [o, v] of D.verrous) { const a = avant.get(o); if (!a || a.id !== v.id || a.nb !== v.nb || a.ti !== v.ti) surVerrou(v); }
  for (const o of avant.keys()) if (!D.verrous.has(o)) surLibre(o);
  if (D.resync) {   // (re)connecté : ce que cet onglet tenait ou voulait est redemandé
    D.resync = false;
    for (const [o, t] of D.tenus) if (t.veut > 0) { t.statut = ""; demanderPrise(o, t); }
  }
  if (D.mode === "ws") demarrerBattement();
  majBord();
  majBadges();
  signaler({ type: "etat" });
}
function surVerrou(v) {
  majBadges(v.o);
  majBord();
  for (const em of emprisesDe(v.o)) em.surChangement();
  signaler({ type: "verrou", objet: v.o, id: v.id });
}
function surLibre(o) {
  if (!o) return;
  D.verrous.delete(o);
  const t = D.tenus.get(o);
  if (t && t.statut === "tenu") t.statut = "perdu";   // le serveur l'a lâché (bail échu) : cet onglet ne le tient plus
  // Une modification de la file qui attendait cet objet repart tout de suite.
  const attente = HL.file.ops.filter((op) => op.verrou && op.verrou.objet === o);
  if (attente.length) {
    for (const op of attente) { op.verrou = null; op.erreur = ""; op._avisVerrou = false; }
    HL.planifierEnvoi(150);
  }
  majBadges(o);
  majBord();
  for (const em of emprisesDe(o)) em.surLibre();
  signaler({ type: "libre", objet: o });
}
const relectures = new Map();
function surEcrit(objets, par) {
  emettre("direct:ecrit", { objets, par });
  const occupe = [...D.emprises].some((em) => em.genre === "zone" && em.etat === "moi");
  for (const o of objets) {
    for (const nom of JEUX[String(o).split(":")[0]] || []) {
      perime(nom);
      if (occupe || nom === "dossier" || !vueJeu(nom)) continue;   // une saisie en cours dans la page : elle relira plus tard
      clearTimeout(relectures.get(nom));
      relectures.set(nom, setTimeout(() => { relectures.delete(nom); charger(nom, { forcer: true }); }, 400));
    }
  }
  signaler({ type: "ecrit", objets, id: par });
}

// ═══ PRENDRE ET RENDRE LA MAIN ══════════════════════════════════════════════
// Chaque demande (un éditeur, une zone, un appel de `prendre`) compte une fois dans `veut` ; la main est rendue au
// serveur quand plus rien ne la veut dans cet onglet.
export function prendre(objet, titre) { return prendreAvec(objet, titre, null); }
function prendreAvec(objet, titre, n) {
  const o = cleObjet(objet);
  if (!o) return Promise.resolve({ ok: true, horsDirect: true });
  let t = D.tenus.get(o);
  if (!t) { t = { titre: titre || "", veut: 0, statut: "", n: null, attentes: [] }; D.tenus.set(o, t); }
  t.veut += 1;
  if (titre) t.titre = titre;
  if (n !== null && n !== undefined) t.n = n;
  clearTimeout(t.lacher); t.lacher = 0;
  if (t.statut === "tenu") return Promise.resolve({ ok: true, n: t.n, deja: true });
  return demanderPrise(o, t);
}
function demanderPrise(o, t) {
  return new Promise((fin) => {
    t.attentes.push(fin);
    if (t.statut === "demande") return;
    t.statut = "demande";
    const m = { t: "prendre", o, ti: t.titre };
    if (t.n !== null && t.n !== undefined) m.n = t.n;
    if (!envoyer(m)) {   // pas de direct : on n'empêche pas d'écrire ; la main sera demandée à la reconnexion
      t.statut = "reprendre";
      resoudre(t, { ok: true, horsDirect: true });
      return;
    }
    clearTimeout(t.delai);
    t.delai = setTimeout(() => { if (t.statut === "demande") { t.statut = "reprendre"; resoudre(t, { ok: true, horsDirect: true }); } }, 6000);
  });
}
function resoudre(t, r) {
  const a = t.attentes;
  t.attentes = [];
  for (const f of a) f(r);
}
function surPris(m) {
  const t = D.tenus.get(m.o);
  if (m.v) D.verrous.set(m.o, m.v);
  if (!t || t.veut <= 0) { envoyer({ t: "lacher", o: m.o }); majBadges(m.o); return; }   // plus voulu entre-temps
  clearTimeout(t.delai);
  t.statut = "tenu"; t.n = m.n;
  const r = { ok: true, n: m.n, change: !!m.ch };
  resoudre(t, r);
  majBadges(m.o);
  majBord();
  for (const em of emprisesDe(m.o)) em.reponse(r);
  signaler({ type: "pris", objet: m.o });
}
function surRefuse(m) {
  const t = D.tenus.get(m.o);
  if (!t) return;
  clearTimeout(t.delai);
  if (m.err) {   // une clé refusée, trop de verrous, pas de réponse : on n'empêche pas d'écrire
    t.statut = "horsdirect";
    resoudre(t, { ok: true, horsDirect: true });
    return;
  }
  t.statut = "refuse";
  const r = { ok: false, par: m.par, nom: m.nom };
  resoudre(t, r);
  for (const em of emprisesDe(m.o)) em.reponse(r);
  majBadges(m.o);
  signaler({ type: "refuse", objet: m.o, id: m.par });
}
export function lacher(objet) {
  const o = cleObjet(objet);
  const t = o && D.tenus.get(o);
  if (!t) return;
  t.veut = Math.max(0, t.veut - 1);
  if (t.veut > 0) return;
  clearTimeout(t.lacher);
  t.lacher = setTimeout(() => rendre(o, t), 700);   // un éditeur rouvert aussitôt reprend la même main sans la rendre
}
async function rendre(o, t) {
  await fileVide(15000);   // jamais avant que la modification soit partie : l'autre relirait une version périmée
  if (t.veut > 0 || D.tenus.get(o) !== t) return;
  D.tenus.delete(o);
  if (["tenu", "demande", "reprendre"].includes(t.statut)) { envoyer({ t: "lacher", o }); oublierLocal(o); }
  resoudre(t, { ok: false, abandon: true });
  majBadges(o);
  majBord();
}
/** Le verrou que cet onglet seul tenait : oublié tout de suite (sans attendre « libre », la carte ne clignote pas). */
function oublierLocal(o) {
  const v = D.verrous.get(o);
  if (v && v.id === D.moi && (v.nb || 0) <= 1) D.verrous.delete(o);
}
/** Rendre la main tout de suite (refusée, ou prise ailleurs) : rien n'a été écrit par ici. */
function lacherSansAttente(o) {
  const t = D.tenus.get(o);
  if (!t) return;
  t.veut = Math.max(0, t.veut - 1);
  if (t.veut > 0) return;
  clearTimeout(t.lacher);
  D.tenus.delete(o);
  if (t.statut === "tenu" || t.statut === "demande") { envoyer({ t: "lacher", o }); if (t.statut === "tenu") oublierLocal(o); }
  resoudre(t, { ok: false, abandon: true });
  majBadges(o);
}
function fileVide(max) {
  const t0 = Date.now();
  return new Promise((fin) => {
    const voir = () => {
      const enVol = HL.file.enCours || HL.enAttente().some((op) => !op.verrou && (op.essais || 0) < 3);
      if (!enVol || !enLigne() || Date.now() - t0 > max) { fin(); return; }
      setTimeout(voir, 200);
    };
    voir();
  });
}

/** Avant un geste rapide sur un objet (renommer, supprimer…) : false, avec un avis, si quelqu'un d'autre le tient. */
export function siLibre(objet) {
  const v = verrouDe(objet);
  if (!v || v.moi) return true;
  toast(v.nom + " modifie " + (v.titre || "cet élément") + " en ce moment : attends que ce soit libre, ou demande-lui la main.", "erreur");
  return false;
}

// ─── Demander la main ───────────────────────────────────────────────────────
function surDemande(m) {
  const t = D.tenus.get(m.o);
  toast((sansEmoji(m.nom) || "Quelqu'un") + " voudrait modifier " + ((t && t.titre) || "ce que tu modifies") + ".", "");
  for (const em of emprisesDe(m.o)) if (em.etat === "moi") em.montrerDemande(m);
  signaler({ type: "demande", objet: m.o, id: m.par });
}

// ═══ LES BADGES : le cadenas sur les cartes ═════════════════════════════════
export function badgeVerrou(objet) {
  const o = cleObjet(objet);
  const b = h("span", { classe: "direct-badge", "data-direct-objet": o || "", role: "note", hidden: true });
  if (o) requestAnimationFrame(() => majBadge(b));
  return b;
}
export function avecVerrou(el, objet) {
  if (!el || !cleObjet(objet)) return el;
  const b = badgeVerrou(objet);
  ajouter(el, [b]);
  majBadge(b);
  return el;
}
function majBadges(o) {
  const sel = o ? '[data-direct-objet="' + (window.CSS && CSS.escape ? CSS.escape(o) : o) + '"]' : "[data-direct-objet]";
  for (const b of document.querySelectorAll(sel)) majBadge(b);
}
function majBadge(b) {
  const o = b.dataset.directObjet;
  if (!o) return;
  const v = verrouDe(o);
  const parent = b.parentElement;
  const autre = !!v && !v.moi;
  const ailleurs = !!v && v.moi && !v.ici;
  b.hidden = !(autre || ailleurs);
  if (parent) {
    parent.classList.toggle("direct-sous-verrou", autre);
    parent.classList.toggle("direct-chez-moi", ailleurs);
  }
  if (!autre && !ailleurs) {
    if (b.firstChild) remplacer(b);
    b.removeAttribute("aria-label");
    if (parent && parent.dataset.directDescription) { parent.removeAttribute("aria-description"); delete parent.dataset.directDescription; }
    return;
  }
  const titre = autre ? "En cours de modification par " + v.nom + " (" + duree(v.depuis) + ")" : "Ouvert dans un autre de tes onglets";
  // Le sceau de cire (le cadenas) et la plaque : la personne, « En cours de modification / par X ».
  remplacer(b, h("span", { classe: "direct-sceau", "aria-hidden": "true" }, icone("cadenas")),
    h("span", { classe: "direct-badge-plaque" },
      autre ? avatarDirect({ id: v.id, nom: v.nom, avatar: v.avatar, couleur: v.couleur }, "mini") : null,
      autre ? h("span", { classe: "direct-badge-texte" }, h("span", { classe: "direct-badge-quoi" }, "En cours de modification"), h("b", {}, "par " + v.nom))
        : h("span", { classe: "direct-badge-texte" }, h("b", {}, "Dans un autre de tes onglets"))));
  b.title = titre;
  b.setAttribute("aria-label", titre);
  if (parent) { parent.setAttribute("aria-description", titre); parent.dataset.directDescription = "1"; }
}

/** Un avatar rond, liseré de la couleur de la personne (l'image de Discord, sinon ses initiales). */
export function avatarDirect(p, taille) {
  const el = h("span", { classe: "direct-avatar" + (taille ? " " + taille : "") + (p.moi ? " moi" : ""), vars: { "--lisere": p.couleur || couleurDe(p.id) }, "aria-hidden": "true" });
  const init = h("span", { classe: "direct-initiales" }, initiales(p.nom || "?"));
  const src = srcSure(p.avatar);
  if (src) {
    const img = h("img", { src, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => img.replaceWith(init), { once: true });
    ajouter(el, [img]);
  } else ajouter(el, [init]);
  return el;
}

// ═══ « À BORD » : l'en-tête et la liste ═════════════════════════════════════
let bord = null;
let liste = null;
function monterBord() {
  const outils = document.getElementById("entete-outils");
  if (!outils || bord) return;
  bord = h("button", { classe: "direct-bord", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false",
    onclick: (e) => { e.stopPropagation(); if (liste) fermerListe(); else ouvrirListe(); } });
  const plaque = document.getElementById("plaque-etat");
  if (plaque && plaque.parentElement === outils) outils.insertBefore(bord, plaque);
  else outils.prepend(bord);
  telephone.addEventListener("change", majBord);
  majBord();
}
function majBord() {
  if (liste) dessinerListe();
  if (!bord) return;
  const l = presents();
  const autres = l.filter((p) => !p.moi);
  // Au téléphone, l'en-tête est court : une seule personne (une autre que soi s'il y en a), « +n » ne compte que les autres.
  const tel = telephone.matches;
  const montres = tel ? (autres.length ? autres : l).slice(0, 1) : [...autres, ...l.filter((p) => p.moi)].slice(0, 4);
  const reste = (tel ? autres.length || l.length : l.length) - montres.length;
  const coupe = D.mode === "coupe" || D.mode === "fini";
  bord.classList.toggle("coupe", coupe);
  bord.classList.toggle("seul", !autres.length);
  remplacer(bord, h("span", { classe: "direct-bord-lib" }, "À bord"),
    montres.length && !coupe ? h("span", { classe: "direct-equipage" }, montres.map((p) => avatarDirect(p, "bord"))) : icone("longue_vue", "direct-lunette"),
    reste > 0 && !coupe ? h("span", { classe: "direct-plus" }, "+" + reste) : null);
  const qui = autres.map((p) => p.nom).join(", ");
  const texte = coupe ? "Le direct est coupé : le site reste utilisable." : !vivant() ? "Le direct se branche…"
    : autres.length ? "À bord : " + qui + (l.some((p) => p.moi) ? " et toi" : "") + "." : "Personne d'autre à bord.";
  bord.title = texte;
  bord.setAttribute("aria-label", texte + " Ouvrir la liste.");
}
function ouvrirListe() {
  if (!bord) return;
  const pop = h("div", { classe: "menu-pop feuille-basse direct-liste", role: "dialog", "aria-label": "À bord", tabindex: "-1" });
  document.body.append(pop);
  if (POPOVER) { pop.setAttribute("popover", "manual"); try { pop.showPopover(); } catch (e) { /* hors couche supérieure */ } }
  const dehors = (e) => { if (!pop.contains(e.target) && !bord.contains(e.target)) fermerListe(); };
  const touche = (e) => { if (e.key === "Escape") { e.preventDefault(); fermerListe(true); } };
  const placer = () => {
    if (telephone.matches) return;
    const r = bord.getBoundingClientRect();
    pop.style.setProperty("top", Math.round(r.bottom + 8) + "px");
    pop.style.setProperty("right", Math.max(8, Math.round(document.documentElement.clientWidth - r.right)) + "px");
    pop.style.setProperty("left", "auto");
  };
  liste = { pop, dehors, placer };
  document.addEventListener("pointerdown", dehors, true);
  pop.addEventListener("keydown", touche);
  addEventListener("resize", placer);
  bord.setAttribute("aria-expanded", "true");
  dessinerListe();
  placer();
  requestAnimationFrame(() => pop.focus({ preventScroll: true }));
}
function fermerListe(rendreFocus) {
  if (!liste) return;
  const { pop, dehors, placer } = liste;
  liste = null;
  document.removeEventListener("pointerdown", dehors, true);
  removeEventListener("resize", placer);
  if (POPOVER) { try { pop.hidePopover(); } catch (e) { /* déjà fermé */ } }
  pop.remove();
  if (bord) { bord.setAttribute("aria-expanded", "false"); if (rendreFocus) bord.focus({ preventScroll: true }); }
}
function dessinerListe() {
  if (!liste) return;
  const l = presents();
  const coupe = D.mode === "coupe" || D.mode === "fini";
  remplacer(liste.pop,
    h("div", { classe: "direct-liste-tete" }, icone("longue_vue"), h("b", {}, "À bord"),
      h("span", { classe: "direct-liste-compte" }, coupe ? "direct coupé" : quantite(l.length, "personne(s)"))),
    l.length ? h("ul", { classe: "direct-personnes" }, l.map(lignePersonne))
      : h("p", { classe: "aide" }, coupe ? "Le direct est coupé : le site reste utilisable. La liste revient avec lui." : "Le direct se branche…"),
    !coupe && l.length && !l.some((p) => !p.moi) ? h("p", { classe: "direct-liste-note" }, "Personne d'autre à bord pour l'instant.") : null,
    coupe && l.length ? h("p", { classe: "direct-liste-note" }, "Le direct est coupé : cette liste peut être en retard.") : null);
}
function lignePersonne(p) {
  const ou = p.pages[0];
  return h("li", { classe: "direct-personne" + (p.moi ? " moi" : "") },
    avatarDirect(p, "liste"),
    h("div", { classe: "direct-personne-bloc" },
      h("div", { classe: "direct-personne-nom" }, h("b", {}, p.nom), p.moi ? h("span", { classe: "direct-toi" }, "toi") : null,
        !p.moi && ou ? bouton("Y aller", { classe: "p discret", icone: "droite", titre: "Ouvrir " + ou.lib, onclick: () => { fermerListe(); allerVers(ou.cle); } }) : null),
      ou ? h("div", { classe: "direct-ou" }, icone("boussole", "ic-p"), h("span", {}, ou.lib + (p.onglets > 1 ? " · " + p.onglets + " onglets" : ""))) : null,
      p.modifie.map((m) => h("div", { classe: "direct-quoi" }, icone("plume", "ic-p"),
        h("span", {}, "modifie " + (m.titre || "un élément"), h("span", { classe: "direct-depuis" }, " · " + duree(m.depuis))))),
      h("div", { classe: "direct-arrivee" }, "à bord " + duree(p.depuis))));
}
function allerVers(cle) {
  const [c, r, s] = String(cle || "").split("/");
  if (CATEGORIES.some((x) => x.cle === c)) aller(c, r, SOUS[s] ? s : "");
}

// ═══ LES EMPRISES : un éditeur ou une zone qui tient un objet ═══════════════
const emprisesDe = (o) => [...D.emprises].filter((em) => em.objet && em.objet === o);
const TEXTES_RENDU = {
  inactif: "Tu n'as rien modifié depuis 5 minutes : la main est rendue aux autres. Ta saisie reste ici.",
  libere: "Tu as laissé la main. Ta saisie reste ici.",
  perdu: "La connexion a été coupée trop longtemps : la main est rendue. Ta saisie reste ici.",
};

class Emprise {
  /** o : { genre: "editeur" | "zone", objet, titre, opts, pancarte?, zone? } */
  constructor(o) {
    this.genre = o.genre;
    this.objet = cleObjet(o.objet);
    this.titre = o.titre || "";
    this.opts = o.opts || {};
    this.p = o.pancarte || null;
    this.zone = o.zone || null;
    this.hote = this.p ? this.p.corps : this.zone;   // où vont le bandeau, et ce qui se fige
    this.etat = "neuf";       // neuf · attente · moi · autre · rendu · relecture · libre · hors · fini
    this.veut = false;        // compte une demande de la main dans cet onglet (prendre), pas encore rendue
    this.n = null;            // le compteur d'écritures connu à la dernière prise
    this.raison = "";
    this.actif = Date.now();
    this.bandeau = null; this.avis = null; this.fermerB = null; this.avisDemande = null;
    this.figes = []; this.caches = [];
    this.observateur = null;
    this.demandeLe = 0;
    this.cible = this.p ? this.p.dlg : this.zone;
    this.activite = () => { this.actif = Date.now(); };
    for (const ev of ["input", "change", "keydown", "pointerdown"]) this.cible.addEventListener(ev, this.activite, true);
    if (this.parSaisie()) {
      this.premiereSaisie = (e) => {
        if (this.etat !== "neuf") return;
        if (e.type === "click" && !(e.target.closest && e.target.closest("button, [role=button], [role=switch]"))) return;
        this.reclamer();
      };
      for (const ev of ["input", "change", "click"]) this.zone.addEventListener(ev, this.premiereSaisie, true);
    }
    D.emprises.add(this);
    if (this.genre === "zone") guetterZones();
  }
  parSaisie() { return this.genre === "zone" && this.opts.des === "saisie"; }

  demarrer() {
    if (!this.objet) { this.etat = "hors"; this.dessiner(); return; }
    const v = verrouDe(this.objet);
    if (v && !v.moi) { this.etat = "autre"; this.dessiner(); return; }   // pris ailleurs : pas un éclair de formulaire ouvert
    if (this.parSaisie()) { this.etat = "neuf"; this.dessiner(); return; }
    this.reclamer();
  }
  /** Demander la main (une seule demande comptée par emprise) ; la réponse arrive par `reponse`. */
  reclamer() {
    if (this.etat === "fini" || !this.objet) return;
    if (this.etat !== "autre") this.etat = "attente";
    const t = D.tenus.get(this.objet);
    let p;
    if (!this.veut || !t) { this.veut = true; p = prendreAvec(this.objet, this.titre, this.n); }
    else if (t.statut === "tenu") p = Promise.resolve({ ok: true, n: t.n, deja: true });
    else { if (this.n !== null) t.n = this.n; p = demanderPrise(this.objet, t); }
    // Les réponses du serveur (pris, refuse) arrivent par `reponse` ; la promesse ne porte que le reste.
    p.then((r) => { if (r.deja || r.horsDirect) this.reponse(r); });
  }
  renoncer(attendre) {
    if (!this.veut) return;
    this.veut = false;
    if (attendre) lacher(this.objet); else lacherSansAttente(this.objet);
  }
  reponse(r) {
    if (this.etat === "fini" || !this.veut || r.abandon) return;
    if (r.ok && r.horsDirect) { this.etat = "hors"; this.dessiner(); return; }
    if (r.ok) {
      const change = r.change && this.n !== null && this.opts.relire;
      this.n = r.n ?? this.n;
      if (change) {
        toast("Pendant ta pause, " + (this.titre || "cet élément") + " a changé : la dernière version s'ouvre.", "");
        this.relireEtReprendre(true);
        return;
      }
      this.etat = "moi"; this.actif = Date.now(); this.raison = "";
      this.dessiner();
      return;
    }
    this.renoncer(false);   // refusée : rien n'est tenu ; on attend que l'objet se libère
    this.etat = "autre";
    this.dessiner();
  }
  /** Rendre la main (inactivité, « Libérer ») : la saisie reste à l'écran. */
  rendreLaMain(raison) {
    this.renoncer(true);
    if (this.parSaisie()) { this.etat = "neuf"; this.dessiner(); return; }   // une zone : la prochaine saisie la reprend
    this.etat = "rendu"; this.raison = raison || "inactif";
    this.dessiner();
  }
  surChangement() {
    if (this.etat === "fini" || this.etat === "relecture") return;
    const v = verrouDe(this.objet);
    if (v && !v.moi && this.etat !== "autre") {   // quelqu'un d'autre l'a (pendant une coupure, ou après ma main rendue)
      this.renoncer(false);
      this.etat = "autre";
    }
    this.dessiner();
  }
  surLibre() {
    if (this.etat === "autre" || this.etat === "libre") { this.relireEtReprendre(false); return; }
    if (this.etat === "moi") {
      const t = D.tenus.get(this.objet);
      if (t && t.statut === "perdu") {   // le serveur l'a lâché (connexion coupée trop longtemps)
        this.renoncer(false);
        if (this.parSaisie()) this.etat = "neuf"; else { this.etat = "rendu"; this.raison = "perdu"; }
      }
    }
    this.dessiner();
  }
  surVisible() { if (this.etat === "libre" && this.raison !== "relecture") this.relireEtReprendre(false); }
  async relireEtReprendre(dejaTenu) {
    if (this.etat === "fini") return;
    if (document.hidden && !dejaTenu) { this.etat = "libre"; this.raison = ""; this.dessiner(); return; }   // caché : il attend qu'on revienne
    this.etat = "relecture";
    this.dessiner();
    const relire = this.opts.relire;
    if (relire) {
      try {
        await relire();
      } catch (e) {
        this.renoncer(false);
        this.etat = "libre"; this.raison = "relecture";
        this.dessiner();
        return;
      }
      if (this.etat === "fini") return;
      if (this.genre === "editeur" && !this.opts.surPlace) { this.fermerPancarte(); return; }   // le nouvel éditeur a la main
      if (this.genre === "zone" && !this.zone.isConnected) { this.finir(); return; }           // la page s'est redessinée
    }
    this.n = null;
    this.etat = "attente";
    if (this.parSaisie() && !this.veut) { this.etat = "neuf"; this.dessiner(); return; }
    this.reclamer();
  }
  fermerPancarte() {
    const p = this.p;
    this.finir();
    if (p && !p.fermee()) p.fermer("enregistre");
  }
  changer(objet, titre) {
    const o = cleObjet(objet);
    if (o === this.objet) {
      if (titre && titre !== this.titre) { this.titre = titre; if (this.etat === "moi") envoyer({ t: "prendre", o, ti: titre }); }
      return;
    }
    this.renoncer(true);
    this.objet = o; this.titre = titre || this.titre; this.n = null; this.etat = "neuf"; this.avisDemande = null;
    this.demarrer();
  }
  demandeEnvoyee(deja) {
    this.demandeLe = Date.now();
    this.dessiner();
    if (!deja) toast("Demande envoyée : la personne est prévenue.", "succes");
  }
  montrerDemande(m) {
    this.avisDemande = { par: String(m.par || ""), nom: sansEmoji(m.nom) || "Quelqu'un" };
    this.dessiner();
  }
  finir() {
    if (this.etat === "fini") return;
    this.renoncer(true);
    this.etat = "fini";
    this.dessiner();
    for (const ev of ["input", "change", "keydown", "pointerdown"]) this.cible.removeEventListener(ev, this.activite, true);
    if (this.premiereSaisie) for (const ev of ["input", "change", "click"]) this.zone.removeEventListener(ev, this.premiereSaisie, true);
    D.emprises.delete(this);
    if (this.genre === "zone") guetterZones();
  }

  // ─── Le dessin : bandeau, lecture seule, pied ───
  dessiner() {
    if (this.etat === "fini") {
      this.poser("bandeau", null); this.poser("avis", null); this.figer(false); this.pied(false);
      if (this.zone) this.zone.classList.remove("direct-zone-lecture");
      if (this.p) this.p.dlg.classList.remove("direct-lecture");
      this.observer(false);
      return;
    }
    const v = this.objet ? verrouDe(this.objet) : null;
    const lecture = LECTURE.has(this.etat);
    let bandeau = null;
    if (!this.opts.compact) {
      if (this.etat === "autre") bandeau = this.consigne(v && !v.moi ? v : null);
      else if (this.etat === "relecture") bandeau = cadre("relecture", "synchro", [h("p", {}, h("b", {}, "C'est libre. "), "La dernière version s'ouvre…")]);
      else if (this.etat === "libre") bandeau = this.libre();
      else if (this.etat === "rendu") bandeau = this.rendu();
      else if (this.etat === "moi" && v && v.ailleurs) bandeau = cadre("ailleurs", "info", [h("p", {}, "Ouvert aussi dans un autre de tes onglets : n'enregistre que depuis un seul.")]);
    }
    if (this.etat !== "moi") this.avisDemande = null;
    this.poser("bandeau", bandeau);
    this.poser("avis", this.avisDemande && !this.opts.compact ? this.demande() : null);
    this.figer(lecture);
    this.pied(lecture);
    if (this.zone) this.zone.classList.toggle("direct-zone-lecture", lecture);
    if (this.p) this.p.dlg.classList.toggle("direct-lecture", lecture);
    this.observer(lecture || !!bandeau || !!this.avis);
  }
  poser(cle, el) {
    const avant = this[cle];
    if (avant && avant !== el) avant.remove();
    this[cle] = el;
    if (!el || !this.hote) return;
    const apres = cle === "avis" && this.bandeau && this.bandeau.parentElement === this.hote ? this.bandeau.nextSibling : this.hote.firstChild;
    if (el.parentElement !== this.hote) this.hote.insertBefore(el, apres);
  }
  figer(oui) {
    if (!this.hote) return;
    if (!oui) {
      for (const el of this.figes) { el.inert = false; el.classList.remove("direct-fige"); }
      this.figes = [];
      return;
    }
    this.figes = this.figes.filter((el) => el.isConnected);
    for (const el of [...this.hote.children]) {
      if (el === this.bandeau || el === this.avis || el.classList.contains("direct-badge") || this.figes.includes(el)) continue;
      el.inert = true;
      el.classList.add("direct-fige");
      this.figes.push(el);
    }
  }
  pied(lecture) {
    if (!this.p) return;
    const pied = this.p.pied;
    if (!lecture) {
      for (const [el, cache] of this.caches) if (el.isConnected) el.hidden = cache;
      this.caches = [];
      if (this.fermerB) { this.fermerB.remove(); this.fermerB = null; }
      return;
    }
    for (const el of [...pied.children]) {   // « Enregistrer » et les autres gestes : cachés tant que ce n'est pas à moi
      if (el === this.fermerB || this.caches.some((c) => c[0] === el)) continue;
      this.caches.push([el, el.hidden]);
      el.hidden = true;
    }
    if (!this.fermerB) this.fermerB = bouton("Fermer", { classe: "discret", onclick: () => this.fermerPancarte() });
    if (this.fermerB.parentElement !== pied) pied.append(this.fermerB);
  }
  /** Un éditeur ou une zone que sa page redessine : le bandeau, le figé et le pied se reposent d'eux-mêmes. */
  observer(oui) {
    if (!oui) { if (this.observateur) { this.observateur.disconnect(); this.observateur = null; } return; }
    if (this.observateur || !this.hote) return;
    this.observateur = new MutationObserver(() => {
      if (this.etat === "fini") return;
      if (this.bandeau && this.bandeau.parentElement !== this.hote) this.poser("bandeau", this.bandeau);
      if (this.avis && this.avis.parentElement !== this.hote) this.poser("avis", this.avis);
      const lecture = LECTURE.has(this.etat);
      this.figer(lecture);
      if (lecture) this.pied(true);
    });
    this.observateur.observe(this.hote, { childList: true });
    if (this.p) this.observateur.observe(this.p.pied, { childList: true });
  }

  // ─── Les bandeaux ───
  consigne(v) {
    const recent = Date.now() - this.demandeLe < 20000;
    const demander = bouton(recent ? "Demande envoyée" : "Demander la main", { classe: "p", icone: recent ? "succes" : "cle", disabled: recent || !v || !vivant(),
      titre: v ? "Prévenir " + v.nom + " que tu voudrais modifier" : "", onclick: () => envoyer({ t: "demande", o: this.objet }) });
    if (recent && !this.minuteurDemande) this.minuteurDemande = setTimeout(() => { this.minuteurDemande = 0; if (this.etat === "autre") this.dessiner(); }, 20500 - (Date.now() - this.demandeLe));
    const actions = [demander];
    if (this.opts.quitter) actions.push(bouton(this.opts.quitter.libelle, { classe: "p discret", onclick: () => this.opts.quitter.fn() }));
    return h("div", { classe: "direct-consigne", role: "status" },
      h("span", { classe: "direct-consigne-qui" }, avatarDirect(v || { nom: "?", couleur: "#4a5560" }, "grand"), h("span", { classe: "direct-sceau", "aria-hidden": "true" }, icone("cadenas"))),
      h("div", { classe: "direct-consigne-texte" },
        h("p", { classe: "direct-consigne-titre" }, v ? [h("b", {}, v.nom), " modifie " + (this.titre || "cet élément") + " en ce moment."] : "En cours de modification par quelqu'un d'autre."),
        h("p", { classe: "direct-consigne-meta" }, (v ? majuscule(duree(v.depuis)) + ". " : "") + (recent ? "Ta demande est partie. " : "")
          + "Tu vois la version enregistrée ; dès que c'est libre, la dernière version s'ouvre pour toi.")),
      h("div", { classe: "direct-consigne-actions" }, actions));
  }
  libre() {
    const echec = this.raison === "relecture";
    return cadre("libre", echec ? "attention" : "succes", [h("p", {}, h("b", {}, "C'est libre. "), echec ? "La dernière version n'a pas pu être lue." : "Ouvre la dernière version pour modifier."),
      h("div", { classe: "rangee" }, bouton(echec ? "Réessayer" : "Ouvrir la dernière version", { classe: "p principal", icone: "synchro", onclick: () => this.relireEtReprendre(false) }))]);
  }
  rendu() {
    return cadre("rendu", "minuteur", [h("p", {}, TEXTES_RENDU[this.raison] || TEXTES_RENDU.inactif),
      h("div", { classe: "rangee" }, bouton("Reprendre la main", { classe: "p principal", icone: "plume", onclick: () => this.reclamer() }))]);
  }
  demande() {
    const a = this.avisDemande;
    const p = D.personnes.get(a.par) || {};
    return h("div", { classe: "direct-avis", role: "alert" },
      avatarDirect({ id: a.par, nom: a.nom, avatar: p.av || "" }, "moyen"),
      h("div", { classe: "direct-avis-texte" }, h("p", {}, h("b", {}, a.nom), " voudrait modifier " + (this.titre || "ceci") + "."),
        h("p", { classe: "direct-consigne-meta" }, "Libérer : ta saisie reste à l'écran, et la main passe à " + a.nom + ".")),
      h("div", { classe: "direct-consigne-actions" },
        bouton("Libérer", { classe: "p principal", icone: "cle", onclick: () => { this.avisDemande = null; this.rendreLaMain("libere"); } }),
        bouton("Garder la main", { classe: "p discret", onclick: () => { this.avisDemande = null; this.dessiner(); } })));
  }
}
function cadre(genre, ic, contenu) {
  return h("div", { classe: "direct-cadre " + genre, role: "status" }, icone(ic), h("div", { classe: "direct-cadre-texte" }, contenu));
}
/** La veille : une main gardée sans saisie depuis 5 min est rendue ; une zone sortie de la page la rend aussi. */
function veille() {
  const limite = (D.cfg.inactif || 300) * 1000;
  for (const em of [...D.emprises]) if (em.etat === "moi" && Date.now() - em.actif > limite) em.rendreLaMain("inactif");
  verifierZones();
}
function verifierZones() {
  for (const em of [...D.emprises]) if (em.genre === "zone" && !em.zone.isConnected) em.finir();
}
// Une zone qui quitte la page rend la main tout de suite : la page n'est observée que tant qu'une zone est protégée.
let guetteur = null;
function guetterZones() {
  const zones = [...D.emprises].some((em) => em.genre === "zone");
  if (zones && !guetteur) {
    guetteur = new MutationObserver(retarder(verifierZones, 150));
    guetteur.observe(document.body, { childList: true, subtree: true });
  } else if (!zones && guetteur) { guetteur.disconnect(); guetteur = null; }
}

/** L'éditeur (une pancarte) protégé : voir l'en-tête du fichier. */
export function protegerEditeur(pancarte, objet, titre, opts = {}) {
  const em = new Emprise({ genre: "editeur", objet, titre, opts, pancarte });
  pancarte.dlg.addEventListener("close", () => em.finir(), { once: true });
  em.demarrer();
  return { changerObjet: (o, t) => em.changer(o, t), etat: () => em.etat, finir: () => em.finir() };
}
/** Une zone de la page protégée (composeur, réglages en ligne) : voir l'en-tête du fichier. */
export function protegerZone(zone, objet, titre, opts = {}) {
  const em = new Emprise({ genre: "zone", objet, titre, opts, zone });
  em.demarrer();
  return { changerObjet: (o, t) => em.changer(o, t), etat: () => em.etat, finir: () => em.finir() };
}
