// sw.js — le service worker de la Capitainerie (portée /tableau/espace/).
// · La coquille (la page) et les fichiers statiques restent en cache : le site s'ouvre même sans réseau.
// · Les données (GET) : le réseau d'abord (4 s), puis la dernière réponse gardée, marquée « X-Hors-Ligne » et datée
//   (« X-Sauve-Le ») pour que la page dise « données d'il y a X min ». Jamais une erreur (401, 403, 5xx) en cache.
// · Les écritures ne passent pas par ici : la page les garde dans sa file (IndexedDB) et les envoie au retour.
// · « vider » (déconnexion) efface tout.

const V = new URL(self.location.href).searchParams.get("v") || "0";
const BASE = "/tableau/espace";
const C_STAT = "cap-statiques";
const C_COQUILLE = "cap-coquille";
const C_DONNEES = "cap-donnees";
const C_MEDIAS = "cap-medias";
const NOS_CACHES = [C_STAT, C_COQUILLE, C_DONNEES, C_MEDIAS];
const DELAI_DONNEES = 4000;
const DELAI_STATIQUE = 3500;
const DELAI_PAGE = 6000;
const MAX_DONNEES = 160;
const MAX_MEDIAS = 400;
const MODULES = ["app.js", "noyau.js", "dom.js", "ui.js", "api.js", "hors_ligne.js", "donnees.js", "discord.js", "fiche.js", "clan.js",
  "recrutement.js", "annonces.js", "capitainerie.js", "affiche.js", "direct.js", "textes.js", "accueil.js", "recherche.js", "rangement.js", "mode.js",
  "recrutement_zone.js", "recrutement_chefs.js", "candidature_direct.js"];
const VERSIONNES = ["app.js", "style.css", "composants.css", "pieces.css", "ateliers.css", "direct.css", "candidature_direct.css", "textes.css", "rangement.css", "recrutement_zone.css", "polices/polices.css", "icones/ui.svg", "manifest.webmanifest",
  "app-192.png"];
// Le direct (qui est à bord, les verrous) n'est jamais servi de mémoire : un état d'il y a une heure mentirait.
const DONNEES = /^\/tableau\/espace\/(donnees|membre|conversation|recherche|api\/(?!direct\/).+)$/;

const attendre = (ms) => new Promise((ok) => setTimeout(() => ok("delai"), ms));

// ─── Installation : la coquille et les fichiers ─────────────────────────────
self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(C_STAT);
    await Promise.allSettled([
      ...VERSIONNES.map((f) => garder(c, BASE + "/s/" + f + "?v=" + encodeURIComponent(V))),
      ...MODULES.map((f) => garder(c, BASE + "/s/" + f)),
      garderCoquille(),
    ]);
    await garderReferences(c);
    await self.skipWaiting();
  })());
});
/** Tout ce que les feuilles de style appellent (polices, textures, ornements) : sans cela, hors ligne, plus de
 *  polices ni de papier. Lu dans les feuilles elles-mêmes : la liste suit les fichiers, sans rien recopier ici. */
async function garderReferences(c) {
  const urls = new Set();
  for (const f of VERSIONNES.filter((x) => x.endsWith(".css"))) {
    const adresse = BASE + "/s/" + f + "?v=" + encodeURIComponent(V);
    try {
      const r = await c.match(adresse);
      if (!r) continue;
      const texte = await r.clone().text();
      for (const m of texte.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)) {
        if (/^(data:|https?:|#)/.test(m[1])) continue;
        const u = new URL(m[1], self.location.origin + BASE + "/s/" + f);
        if (u.origin === self.location.origin && u.pathname.startsWith(BASE + "/s/")) urls.add(u.pathname);
      }
    } catch (err) { /* la feuille suivante */ }
  }
  await Promise.allSettled([...urls].map((u) => garder(c, u)));
}
async function garder(cache, url) {
  try {
    const r = await fetch(url, { cache: "no-cache", credentials: "same-origin" });
    if (r.ok) await cache.put(url, r);
  } catch (e) { /* hors ligne pendant l'installation : la page le gardera plus tard */ }
}
async function garderCoquille() {
  for (const url of [BASE + "/", BASE]) {
    try {
      const r = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (r.ok && estPage(r)) { await (await caches.open(C_COQUILLE)).put(BASE + "/", r); return; }
    } catch (e) { /* rien */ }
  }
}
const estPage = (r) => (r.headers.get("Content-Type") || "").includes("text/html");

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith("cap-") && !NOS_CACHES.includes(k)) await caches.delete(k);
    // Les fichiers versionnés d'anciennes versions partent, sauf ceux de la coquille gardée (elle doit pouvoir s'ouvrir).
    const garde = new Set([V, await versionCoquille()]);
    const c = await caches.open(C_STAT);
    for (const req of await c.keys()) {
      const v = new URL(req.url).searchParams.get("v");
      if (v && !garde.has(v)) await c.delete(req);
    }
    await self.clients.claim();
  })());
});
async function versionCoquille() {
  try {
    const r = await (await caches.open(C_COQUILLE)).match(BASE + "/");
    if (!r) return "";
    const m = /s\/app\.js\?v=([A-Za-z0-9_.%-]+)/.exec(await r.text());
    return m ? decodeURIComponent(m[1]) : "";
  } catch (e) { return ""; }
}

// ─── Messages de la page ────────────────────────────────────────────────────
self.addEventListener("message", (e) => {
  const d = e.data || {};
  if (d.type === "precacher" && Array.isArray(d.urls)) e.waitUntil(precacher(d.urls));
  else if (d.type === "vider") e.waitUntil(vider());
});
async function precacher(urls) {
  const c = await caches.open(C_STAT);
  for (const u of urls.slice(0, 250)) {
    try {
      const url = new URL(u);
      if (url.origin !== self.location.origin || !url.pathname.startsWith(BASE + "/s/")) continue;
      if (await c.match(u)) continue;
      const r = await fetch(u, { credentials: "same-origin" });
      if (r.ok) await c.put(u, r);
    } catch (e) { /* le suivant */ }
  }
}
async function vider() {
  for (const k of await caches.keys()) if (k.startsWith("cap-")) await caches.delete(k);
}

// ─── Les requêtes ───────────────────────────────────────────────────────────
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const u = new URL(req.url);
  if (u.origin !== self.location.origin || !(u.pathname === BASE || u.pathname.startsWith(BASE + "/"))) return;
  if (u.pathname === BASE + "/sw.js") return;
  if (req.mode === "navigate") e.respondWith(page(req, u));
  else if (u.pathname.startsWith(BASE + "/s/")) e.respondWith(statique(req, u));
  else if (u.pathname.startsWith(BASE + "/media/")) e.respondWith(media(req));
  else if (DONNEES.test(u.pathname)) e.respondWith(donnees(req));
  // le reste (exports…) : le réseau seul
});

async function page(req, u) {
  const coq = await caches.open(C_COQUILLE);
  const reseau = fetch(req).catch(() => null);
  const r = await Promise.race([reseau, attendre(DELAI_PAGE)]);
  if (r && r !== "delai") {
    if (r.ok && estPage(r)) { coq.put(BASE + "/", r.clone()); return r; }
    if (r.status === 404 && u.pathname === BASE + "/") { // le serveur ne sert la page qu'à /tableau/espace
      try { const r2 = await fetch(BASE, { credentials: "same-origin" }); if (r2.ok && estPage(r2)) { coq.put(BASE + "/", r2.clone()); return r2; } } catch (e) { /* rien */ }
    }
    if (r.status < 500) return r; // 403 : lien expiré, la page du serveur le dit
  }
  const gardee = await coq.match(BASE + "/");
  if (gardee) return gardee;
  if (r === "delai") { const tard = await reseau; if (tard) return tard; }
  if (r && r !== "delai") return r;
  return new Response("<!doctype html><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Hors ligne</title>"
    + "<p>Hors ligne, et la Capitainerie n'a pas encore été ouverte sur cet appareil. Réessaie avec du réseau.</p>",
  { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'none'", "Cache-Control": "no-store" } });
}

async function statique(req, u) {
  const c = await caches.open(C_STAT);
  if (u.searchParams.has("v")) { // versionné : immuable, le cache d'abord
    const m = await c.match(req);
    if (m) return m;
    try {
      const r = await fetch(req);
      if (r.ok) c.put(req, r.clone());
      return r;
    } catch (e) {
      return (await c.match(req, { ignoreSearch: true })) || Response.error();
    }
  }
  if (/\.(js|css)$/.test(u.pathname)) { // modules et styles : le réseau d'abord (jamais deux versions mêlées), puis le cache
    const reseau = fetch(req, { cache: "no-cache" }).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => null);
    const r = await Promise.race([reseau, attendre(DELAI_STATIQUE)]);
    if (r && r !== "delai" && r.ok) return r;
    const m = await c.match(req);
    if (m) return m;
    const tard = r === "delai" ? await reseau : r;
    return tard || Response.error();
  }
  // images, polices, dessins : le cache tout de suite, rafraîchi derrière
  const m = await c.match(req);
  const reseau = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => null);
  if (m) return m;
  return (await reseau) || Response.error();
}

async function media(req) {
  const c = await caches.open(C_MEDIAS);
  const m = await c.match(req);
  const reseau = fetch(req).then(async (r) => {
    if (r.ok && (r.headers.get("Content-Type") || "").startsWith("image/")) { await c.put(req, r.clone()); elaguer(C_MEDIAS, MAX_MEDIAS); }
    return r;
  }).catch(() => null);
  if (m) return m;
  return (await reseau) || new Response("", { status: 503 });
}

async function donnees(req) {
  const c = await caches.open(C_DONNEES);
  const cle = new Request(req.url);
  const reseau = fetch(req).then(async (r) => {
    if (r.status === 200) { await c.put(cle, await dater(r.clone())); elaguer(C_DONNEES, MAX_DONNEES); }
    return r;
  }).catch(() => null);
  const r = await Promise.race([reseau, attendre(DELAI_DONNEES)]);
  if (r && r !== "delai" && r.status < 500) return r; // 200, 304, 4xx : tels quels (jamais gardés s'ils sont des erreurs)
  const m = await c.match(cle, { ignoreVary: true });
  if (m) return marquer(m);
  if (r === "delai") { const tard = await reseau; if (tard) return tard; }
  if (r && r !== "delai") return r;
  return new Response(JSON.stringify({ erreur: "Hors ligne." }), { status: 503, headers: { "Content-Type": "application/json", "X-Hors-Ligne": "1", "Cache-Control": "no-store" } });
}
async function dater(r) {
  const entetes = new Headers(r.headers);
  entetes.set("X-Sauve-Le", String(Date.now()));
  return new Response(await r.blob(), { status: r.status, statusText: r.statusText, headers: entetes });
}
function marquer(m) {
  const entetes = new Headers(m.headers);
  entetes.set("X-Hors-Ligne", "1");
  return new Response(m.body, { status: m.status, statusText: m.statusText, headers: entetes });
}
async function elaguer(nom, max) {
  try {
    const c = await caches.open(nom);
    const cles = await c.keys();
    for (const k of cles.slice(0, Math.max(0, cles.length - max))) await c.delete(k);
  } catch (e) { /* rien */ }
}
