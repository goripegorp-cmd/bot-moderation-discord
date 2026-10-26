// dom.js — construire la page par nœuds (jamais d'innerHTML de données), les icônes du sprite, les formats.
// CSP : aucun attribut style ; les valeurs calculées passent par des variables CSS posées en CSSOM (setProperty).

export const BASE = "/tableau/espace";
export const NS = "http://www.w3.org/2000/svg";
export const TZ = "Europe/Paris";

// Relevé des violations de la CSP (diagnostic : lu par le script de contrôle, jamais envoyé ailleurs).
export const diagnostic = { violations: [] };
document.addEventListener("securitypolicyviolation", (e) => {
  if (diagnostic.violations.length < 50) diagnostic.violations.push({ directive: e.violatedDirective, source: e.sourceFile, ligne: e.lineNumber, extrait: e.sample, bloque: e.blockedURI });
});
window.__capitainerie = diagnostic;

// ─── Adresses sûres ─────────────────────────────────────────────────────────
const SRC_SURES = [
  /^https:\/\/(cdn\.discordapp\.com|media\.discordapp\.net|images-ext-\d+\.discordapp\.net)\/[^\s"'<>]+$/,
  /^\/tableau\/espace\/(media|s)\/[A-Za-z0-9_./%-]+(\?[A-Za-z0-9=&_.%-]*)?$/,
  /^\/equipage\/image\/[A-Za-z0-9_-]{22}$/,   // la vitrine publique : une image citée par ses données (jeton opaque)
  /^\/ta\/[A-Za-z0-9_-]{16,86}\/\d{1,4}$/,
  /^blob:/,
  /^data:image\/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$/,
];

/** Une adresse d'image venue des données : relative au site (« s/… », « media/… », ou un dossier de `site/` comme
 *  « icones/rell/fruit/love.webp » ou « logos/… »), CDN de Discord, ou rien. */
export function srcSure(u) {
  if (!u) return "";
  let s = String(u).trim();
  if (/^(s|media)\//.test(s)) s = BASE + "/" + s;
  else if (/^(icones|logos|ornements|textures)\//.test(s)) s = BASE + "/s/" + s;
  return SRC_SURES.some((re) => re.test(s)) ? s : "";
}

/** Un lien : https (ouvert à part), ou une adresse du site. Jamais javascript:, data:, etc. */
export function hrefSur(u) {
  if (!u) return "";
  const s = String(u).trim();
  if (/^https:\/\/[^\s"'<>]+$/.test(s)) return s;
  if (s.startsWith(BASE + "/") || s.startsWith("#")) return s;
  return "";
}

// ─── Construction ──────────────────────────────────────────────────────────
export function h(tag, attrs, ...enfants) {
  const e = document.createElement(tag);
  poserAttributs(e, attrs);
  ajouter(e, enfants);
  return e;
}

export function poserAttributs(e, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "classe") e.className = v;
    else if (k === "vars") { for (const [n, x] of Object.entries(v)) if (x !== null && x !== undefined) e.style.setProperty(n, String(x)); }
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "href") { const s = hrefSur(v); if (s) { e.setAttribute("href", s); if (/^https:/.test(s)) { e.setAttribute("target", "_blank"); e.setAttribute("rel", "noopener noreferrer"); } } }
    else if (k === "src") { const s = srcSure(v); if (s) e.setAttribute("src", s); }
    else if (k === "proprietes") Object.assign(e, v);
    else if (k === "style") continue; // CSP : jamais de style en ligne
    else e.setAttribute(k, v === true ? "" : String(v));
  }
}

export function ajouter(e, enfants) {
  for (const c of [enfants].flat(Infinity)) {
    if (c === null || c === undefined || c === false || c === "") continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

/** Remplace les enfants d'un nœud (les vides — null, false, "" — sont ignorés, jamais écrits en texte). */
export function remplacer(e, ...enfants) {
  e.replaceChildren();
  return ajouter(e, enfants);
}

export const $ = (s, r) => (r || document).querySelector(s);
export const $$ = (s, r) => [...(r || document).querySelectorAll(s)];

// ─── Icônes : le sprite dessiné par l'illustrateur, inséré comme nœuds ─────
const PROVISOIRE = "M16 5 27 16 16 27 5 16Z"; // losange sobre, en attendant un dessin manquant
export const icones = { manquantes: new Set(), pret: false };

export async function chargerSprite(url) {
  const hote = document.getElementById("sprite-hote");
  try {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error("sprite " + r.status);
    // Les commentaires partent avant l'analyse : un « -- » dans un commentaire rend tout le fichier invalide en XML
    // (et l'erreur d'analyse de Chrome fabrique un document stylé en ligne, que la CSP bloque).
    const texte = (await r.text()).replace(/<!--[\s\S]*?-->/g, "");
    const doc = new DOMParser().parseFromString(texte, "image/svg+xml");
    const svg = doc.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== "svg" || doc.getElementsByTagName("parsererror").length) throw new Error("sprite illisible");
    for (const n of svg.querySelectorAll("script, foreignObject")) n.remove();
    for (const n of svg.querySelectorAll("*")) for (const a of [...n.attributes]) if (/^on/i.test(a.name) || a.name === "style") n.removeAttribute(a.name);
    const importe = document.importNode(svg, true);
    importe.setAttribute("aria-hidden", "true");
    importe.setAttribute("focusable", "false");
    remplacer(hote, importe);
  } catch (e) {
    remplacer(hote, svgVide());
  }
  icones.pret = true;
}

function svgVide() {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("aria-hidden", "true");
  return s;
}

/** Ajoute un symbole provisoire pour chaque nom absent du sprite (et le note pour les contrôles). */
export function completerSprite(noms) {
  const hote = document.getElementById("sprite-hote");
  let svg = hote.querySelector("svg");
  if (!svg) { svg = svgVide(); hote.append(svg); }
  for (const nom of noms) {
    if (document.getElementById("i-" + nom)) continue;
    const s = document.createElementNS(NS, "symbol");
    s.setAttribute("id", "i-" + nom);
    s.setAttribute("viewBox", "0 0 32 32");
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", PROVISOIRE);
    p.setAttribute("fill", "none");
    p.setAttribute("stroke", "currentColor");
    p.setAttribute("stroke-width", "2.2");
    s.append(p);
    svg.append(s);
    icones.manquantes.add(nom);
  }
}

export function icone(nom, classe) {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("class", "ic" + (classe ? " " + classe : ""));
  s.setAttribute("viewBox", "0 0 32 32");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("focusable", "false");
  const u = document.createElementNS(NS, "use");
  u.setAttribute("href", "#i-" + nom);
  s.append(u);
  return s;
}

// ─── Textes : sans émoji dans les libellés, recherche sans accents ─────────
const RE_EMOJI = /[\p{Extended_Pictographic}\p{Regional_Indicator}\u{1F3FB}-\u{1F3FF}\u{FE0F}\u{FE0E}\u{200D}\u{20E3}\u{E0020}-\u{E007F}]/gu;
const RE_DECOR = /^[\s▷▶►▸・•·|>\-–—:~_.]+|[\s▷▶►▸・•·|<\-–—:~_.]+$/gu;

/** Un libellé venu de Discord (salon, rôle, nom) : sans émoji ni décor, espaces propres. */
export function sansEmoji(s) {
  return String(s ?? "").replace(RE_EMOJI, "").replace(RE_DECOR, "").replace(/\s{2,}/g, " ").trim();
}

export const norm = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
export const contient = (meule, aiguille) => !aiguille || norm(meule).includes(aiguille);
export function initiales(nom) {
  const mots = sansEmoji(nom).match(/[\p{L}\p{N}]+/gu) || [];
  return (mots.slice(0, 2).map((m) => m[0]).join("") || "?").toUpperCase();
}
export const pluriel = (n, un, plusieurs) => (Math.abs(n) >= 2 ? plusieurs || un + "s" : un);
export const compte = (n, un, plusieurs) => nombre(n) + " " + pluriel(n, un, plusieurs);
/** Accorde une phrase écrite avec des marques « (s) », « (es) », « (x) » : accord(3, "entrée(s) effacée(s)") → « entrées effacées ». */
export const accord = (n, texte) => String(texte).replace(/\((e?s|x)\)/g, Math.abs(Number(n) || 0) >= 2 ? "$1" : "");
/** Le nombre et sa phrase accordée : quantite(1, "vote(s)") → « 1 vote », quantite(4, "vote(s)") → « 4 votes ». */
export const quantite = (n, texte) => nombre(Number(n) || 0) + " " + accord(n, texte);

// ─── Dates et nombres (heure de Paris) ──────────────────────────────────────
export const fmt = {
  date: new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "numeric" }),
  dateHeure: new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }),
  heure: new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }),
  jour: new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, weekday: "long", day: "numeric", month: "long" }),
  jourAn: new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, weekday: "long", day: "numeric", month: "long", year: "numeric" }),
  longue: new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }),
  cle: new Intl.DateTimeFormat("fr-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }),
  mois: new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric", timeZone: "UTC" }),
  moisCourt: new Intl.DateTimeFormat("fr-FR", { month: "short", year: "2-digit", timeZone: "UTC" }),
  nombre: new Intl.NumberFormat("fr-FR"),
};
export const maintenant = () => Date.now() / 1000;
export const date = (t, avecHeure) => (t ? (avecHeure ? fmt.dateHeure : fmt.date).format(new Date(t * 1000)) : "—");
export const heure = (t) => (t ? fmt.heure.format(new Date(t * 1000)) : "");
export const dateLongue = (t) => (t ? majuscule(fmt.longue.format(new Date(t * 1000))) : "—");
export const cleJour = (t) => fmt.cle.format(new Date(t * 1000));
export const moisDe = (t) => cleJour(t).slice(0, 7);
export const nombre = (n) => fmt.nombre.format(Number(n) || 0).replace(/ /g, " "); // l'espace fine des milliers est presque invisible en Alegreya
export const majuscule = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
export const prime = (n) => nombre(n) + " berrys"; // le signe ฿ n'existe dans aucune police du site : en image, voir primeNoeud()

export function libelleJour(cle) {
  const auj = cleJour(maintenant()), hier = cleJour(maintenant() - 86400);
  if (cle === auj) return "Aujourd'hui";
  if (cle === hier) return "Hier";
  const [a, m, j] = cle.split("-").map(Number);
  const d = new Date(Date.UTC(a, m - 1, j, 12));
  const memeAnnee = a === new Date().getFullYear();
  return majuscule((memeAnnee ? fmt.jour : fmt.jourAn).format(d));
}
export function libelleMois(cle) {
  const [a, m] = cle.split("-").map(Number);
  return majuscule(fmt.mois.format(new Date(Date.UTC(a, m - 1, 15))));
}
export function libelleMoisCourt(cle) {
  const [a, m] = cle.split("-").map(Number);
  return fmt.moisCourt.format(new Date(Date.UTC(a, m - 1, 15)));
}
export function depuis(t) {
  if (!t) return "date inconnue";
  const s = maintenant() - t;
  if (s < 0) return dans(t);
  if (s < 60) return "à l'instant";
  if (s < 3600) return "il y a " + Math.round(s / 60) + " min";
  if (s < 86400) return "il y a " + Math.round(s / 3600) + " h";
  if (s < 86400 * 45) return "il y a " + Math.round(s / 86400) + " j";
  return "le " + date(t);
}
export function dans(t) {
  const s = t - maintenant();
  if (s <= 0) return depuis(t);
  if (s < 60) return "dans moins d'une minute";
  if (s < 3600) return "dans " + Math.round(s / 60) + " min";
  if (s < 86400) { const hh = Math.floor(s / 3600), mm = Math.round((s % 3600) / 60); return "dans " + hh + " h" + (mm ? " " + String(mm).padStart(2, "0") : ""); }
  const j = Math.floor(s / 86400), hh = Math.round((s % 86400) / 3600);
  return "dans " + j + " j" + (hh ? " " + hh + " h" : "");
}
export function duree(s) {
  if (!s || s < 0) return "—";
  const m = Math.round(s / 60), j = Math.floor(m / 1440), hh = Math.floor((m % 1440) / 60), mm = m % 60;
  return j ? j + " j " + hh + " h" : hh ? hh + " h " + String(mm).padStart(2, "0") : mm + " min";
}
export function dureeMinutes(min) {
  if (!min) return "—";
  if (min < 60) return min + " min";
  const hh = Math.floor(min / 60), mm = min % 60;
  return hh + " h" + (mm ? " " + String(mm).padStart(2, "0") : "");
}

// ─── Divers ─────────────────────────────────────────────────────────────────
export function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const x = [...b].map((v) => v.toString(16).padStart(2, "0")).join("");
  return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
}
export function retarder(fn, ms) {
  let t;
  const f = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  f.annuler = () => clearTimeout(t);
  return f;
}
export const auClavier = (fn) => (e) => {
  if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); fn(e); }
};
export const reduit = matchMedia("(prefers-reduced-motion: reduce)");
export const telephone = matchMedia("(max-width: 719px)");
export const copie = (o) => (o === undefined ? o : JSON.parse(JSON.stringify(o)));
export const egaux = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export function trier(liste, cle, sens = 1) {
  return liste.sort((a, b) => {
    const x = cle(a), y = cle(b);
    if (typeof x === "string" || typeof y === "string") return sens * String(x ?? "").localeCompare(String(y ?? ""), "fr", { sensitivity: "base" });
    return sens * ((x ?? 0) - (y ?? 0));
  });
}
export function lettre(nom) {
  const c = norm(sansEmoji(nom)).replace(/[^a-z0-9]/g, "").charAt(0);
  return /[a-z]/.test(c) ? c.toUpperCase() : "#";
}
