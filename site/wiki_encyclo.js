// wiki_encyclo.js — l'Encyclopédie du Grimoire (29/10/2026) : tout RELL Seas classé en catégories et sous-catégories,
// une page par sujet avec sa fiche (« Inconnu » quand l'info n'existe pas encore), ses images et ses animations.
// Données : site/wiki/encyclo.json, relevé du wiki communautaire RELL Seas (fandom, CC BY-SA), nettoyé et traduit.
// Adresses : #encyclo · #encyclo/c/<catégorie> · #encyclo/p/<page>.

import { icone } from "./wiki_icones.js";

const IC_CAT = { personnage: "masque", pouvoirs: "fruit", combat: "epees", mer: "navire", metiers: "marteau", monde: "ile", boss: "crane", modes: "engrenage" };
const T = {
  fr: { titre: "Encyclopédie", intro: "Tout le jeu, rangé : chaque sujet a sa page, sa fiche et ses images. Quand une information n'a pas encore été montrée, la fiche l'indique clairement : « Inconnu ».",
    chercher: "Chercher dans l'encyclopédie (nom anglais ou français)…", sans: "Aucune page ne correspond.", pages: (n) => `${n} page${n > 1 ? "s" : ""}`,
    accueil: "Encyclopédie", fiche: "Fiche", inconnu: "Inconnu", donnees: "Autres données", source: "Source : wiki communautaire RELL Seas (fandom), licence CC BY-SA. Textes nettoyés et traduits ; anecdotes hors jeu retirées.",
    voirSource: "Page d'origine", precedent: "Précédent", suivant: "Suivant", chargement: "Ouverture de l'encyclopédie…", erreur: "L'encyclopédie est indisponible pour le moment.",
    vide: "Cette page n'a encore aucun contenu vérifié : sa fiche sera complétée dès que RELL montrera le sujet.", fermer: "Fermer", agrandir: "Agrandir l'image", anim: "Animation" },
  en: { titre: "Encyclopedia", intro: "The whole game, sorted: every topic has its page, its sheet and its images. When something has not been shown yet, the sheet says so plainly: \"Unknown\".",
    chercher: "Search the encyclopedia…", sans: "No page matches.", pages: (n) => `${n} page${n > 1 ? "s" : ""}`,
    accueil: "Encyclopedia", fiche: "Sheet", inconnu: "Unknown", donnees: "Other data", source: "Source: RELL Seas community wiki (fandom), CC BY-SA licence. Texts cleaned; off-game trivia removed.",
    voirSource: "Original page", precedent: "Previous", suivant: "Next", chargement: "Opening the encyclopedia…", erreur: "The encyclopedia is unavailable right now.",
    vide: "This page has no verified content yet: its sheet will be filled as soon as RELL shows the topic.", fermer: "Close", agrandir: "Enlarge image", anim: "Animation" },
};

let E = null, attente = null, recherche = "";

export function chargerEncyclo() {
  if (E) return Promise.resolve(E);
  attente = attente || fetch("/tableau/espace/s/wiki/encyclo.json", { headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then((d) => (E = d));
  return attente;
}

// ctx : { el, langue, lien, animer, src, redessiner }
export function vueEncyclo(ctx, chemin) {
  const { el } = ctx, t = T[ctx.langue];
  if (!E) {
    const z = el("div", { classe: "w-feuille" }, el("p", { classe: "w-attente" }, t.chargement));
    chargerEncyclo().then(() => ctx.redessiner()).catch(() => { z.replaceChildren(el("p", { classe: "w-attente" }, t.erreur)); });
    return z;
  }
  const [genre, id] = chemin;
  if (genre === "p" && E.pages[id]) return vuePage(ctx, id);
  if (genre === "c" && E.cats.some((c) => c.id === id)) return vueCategorie(ctx, id);
  return vueSommaire(ctx);
}

// ── Petits outils ──
const tr = (ctx, o) => (ctx.langue === "fr" && o.f ? o.f : o.x);
const nomPage = (ctx, p) => (ctx.langue === "fr" && p.nom_fr ? p.nom_fr : p.nom);
const sousNom = (ctx, p) => (ctx.langue === "fr" && p.nom_fr && p.nom_fr !== p.nom ? p.nom : "");
const imgSrc = (ctx, i, anim) => ctx.src("s/wiki/encyclo/" + (anim && i.anim ? i.anim : i.src));
const plier = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

function image(ctx, i, classe, anim = true) {
  if (!i) return null;
  return ctx.el("img", { classe: "e-img " + (classe || ""), src: imgSrc(ctx, i, anim), width: i.w, height: i.h, alt: "", loading: "lazy", decoding: "async", draggable: "false" });
}

function fil(ctx, ...etapes) {
  const { el } = ctx, t = T[ctx.langue];
  return el("nav", { classe: "e-fil", "aria-label": "Fil d'Ariane" },
    el("a", { href: "#encyclo" }, icone("livre"), t.accueil),
    ...etapes.map((e) => [el("span", { classe: "e-sep", "aria-hidden": "true" }, "›"), e.href ? el("a", { href: e.href }, e.txt) : el("span", {}, e.txt)]).flat());
}

function catDe(pid) {
  for (const c of E.cats) for (const s of c.sous) if (s.pages.includes(pid)) return [c, s];
  return [null, null];
}

// ── Sommaire : les grandes catégories ──
function vueSommaire(ctx) {
  const { el } = ctx, t = T[ctx.langue];
  const zone = el("div", { classe: "w-feuille" });
  const champ = el("input", { classe: "w-recherche", type: "search", placeholder: t.chercher, value: recherche, "aria-label": t.chercher,
    oninput: (ev) => { recherche = ev.target.value; corps(); } });
  const res = el("div", {});
  zone.append(el("h2", { classe: "w-section revele" }, icone("livre"), el("span", {}, t.titre)), el("p", { classe: "w-chapeau revele" }, t.intro), champ, res);
  function corps() {
    const q = plier(recherche.trim());
    if (q.length >= 2) {
      const ids = Object.keys(E.pages).filter((k) => {
        const p = E.pages[k];
        return plier([p.nom, p.nom_fr].join(" ")).includes(q) || plier(p.blocs.filter((b) => b.t === "p").map((b) => b.x + " " + (b.f || "")).join(" ")).includes(q);
      }).sort((a, b) => Number(!plier(E.pages[a].nom + " " + (E.pages[a].nom_fr || "")).includes(q)) - Number(!plier(E.pages[b].nom + " " + (E.pages[b].nom_fr || "")).includes(q)));
      res.replaceChildren(ids.length ? el("div", { classe: "e-grille" }, ids.slice(0, 60).map((k) => cartePage(ctx, k))) : el("p", { classe: "w-attente" }, t.sans));
    } else {
      res.replaceChildren(el("div", { classe: "e-cats" }, E.cats.map((c) => {
        const n = c.sous.reduce((a, s) => a + s.pages.length, 0);
        const vitrine = c.sous.flatMap((s) => s.pages).map((k) => E.pages[k]).find((p) => p.img && p.img.w >= 200);
        const tuile = el("a", { classe: "e-cat revele", href: "#encyclo/c/" + c.id },
          el("span", { classe: "e-cat-fond", "aria-hidden": "true" }),
          el("span", { classe: "e-cat-tete" }, icone(IC_CAT[c.id] || "etoile"), el("strong", {}, c[ctx.langue]), el("span", { classe: "e-nb" }, t.pages(n))),
          el("span", { classe: "e-cat-sous" }, c.sous.map((s) => el("span", {}, s[ctx.langue]))));
        if (vitrine) tuile.querySelector(".e-cat-fond").style.backgroundImage = `url("${imgSrc(ctx, vitrine.img, false)}")`;
        return tuile;
      })));
    }
    ctx.animer(res);
  }
  corps();
  if (recherche) requestAnimationFrame(() => { champ.focus(); champ.setSelectionRange(recherche.length, recherche.length); });
  return zone;
}

function resumeFiche(ctx, p) {
  const v = (p.fiche || []).find((f) => f[2]);
  return v ? `${ctx.langue === "fr" ? v[0] : v[1]} : ${ctx.langue === "fr" ? v[2] : v[3]}` : "";
}

function cartePage(ctx, k) {
  const { el } = ctx, p = E.pages[k];
  return el("a", { classe: "e-carte revele", href: "#encyclo/p/" + k },
    el("span", { classe: "e-carte-img" + (p.img ? "" : " vide") }, p.img ? image(ctx, p.img, "", false) : icone("parchemin")),
    el("span", { classe: "e-carte-texte" }, el("strong", {}, nomPage(ctx, p)),
      sousNom(ctx, p) ? el("span", { classe: "w-nom-en" }, sousNom(ctx, p)) : null,
      resumeFiche(ctx, p) ? el("span", { classe: "e-carte-info" }, resumeFiche(ctx, p)) : null));
}

// ── Une catégorie : ses sous-catégories et leurs pages ──
function vueCategorie(ctx, id) {
  const { el } = ctx, c = E.cats.find((x) => x.id === id);
  return el("div", { classe: "w-feuille" }, fil(ctx, { txt: c[ctx.langue] }),
    el("h2", { classe: "w-section revele" }, icone(IC_CAT[c.id] || "etoile"), el("span", {}, c[ctx.langue])),
    el("nav", { classe: "e-ancres" }, c.sous.map((s) => el("a", { href: "#encyclo/c/" + c.id, onclick: (ev) => { ev.preventDefault(); const n = document.getElementById("e-s-" + s.id); if (n) n.scrollIntoView({ behavior: "smooth", block: "start" }); } }, s[ctx.langue]))),
    c.sous.map((s) => el("section", { classe: "e-sous", id: "e-s-" + s.id },
      el("h3", { classe: "e-sous-titre revele" }, s[ctx.langue], el("span", { classe: "e-nb" }, String(s.pages.length))),
      el("div", { classe: "e-grille" }, s.pages.map((k) => cartePage(ctx, k))))));
}

// ── Une page ──
function vuePage(ctx, id) {
  const { el } = ctx, t = T[ctx.langue], p = E.pages[id];
  const [c, s] = catDe(id);
  const voisins = s ? s.pages : [], i = voisins.indexOf(id);
  const corps = el("div", { classe: "e-corps" });
  const galeries = [];
  let deja = new Set([p.img && p.img.src]);
  for (const b of p.blocs) {
    if (b.t === "h") corps.append(el(b.n <= 2 ? "h3" : "h4", { classe: "e-titre revele" }, tr(ctx, b)));
    else if (b.t === "p") corps.append(el("p", { classe: "e-texte revele" }, tr(ctx, b)));
    else if (b.t === "liste") corps.append(el("ul", { classe: "e-liste revele" }, b.items.map((it) => el("li", {}, it.img ? image(ctx, it.img, "mini") : null, el("span", {}, tr(ctx, it))))));
    else if (b.t === "cartes") corps.append(el("div", { classe: "e-vignettes" }, b.items.map((it) => {
      if (it.img) deja.add(it.img.src);
      return el("figure", { classe: "e-vignette revele" }, it.img ? boutonImage(ctx, it.img, tr(ctx, it), galeries) : el("span", { classe: "e-carte-img vide" }, icone("parchemin")), el("figcaption", {}, tr(ctx, it)));
    })));
    else if (b.t === "galerie") {
      const items = b.items.filter((it) => !deja.has(it.img.src));
      items.forEach((it) => deja.add(it.img.src));
      if (items.length) corps.append(el("div", { classe: "e-galerie" + (items.length === 1 ? " seule" : "") }, items.map((it) => el("figure", { classe: "e-vignette revele" + (it.img.anim ? " anime" : "") },
        boutonImage(ctx, it.img, it.x ? tr(ctx, it) : "", galeries), it.x ? el("figcaption", {}, tr(ctx, it)) : null))));
    } else if (b.t === "table") corps.append(el("div", { classe: "e-table revele" }, el("table", {}, b.lignes.map((r, n) => el("tr", {},
      r.map((cel) => el(n === 0 ? "th" : "td", {}, cel.img ? image(ctx, cel.img, "mini") : null, cel.x ? el("span", {}, tr(ctx, cel)) : null)))))));
    else if (b.t === "infobox") {
      const autres = b.images.filter((im) => !deja.has(im.src));
      autres.forEach((im) => deja.add(im.src));
      if (autres.length) corps.append(el("div", { classe: "e-galerie" }, autres.map((im) => el("figure", { classe: "e-vignette revele" }, boutonImage(ctx, im, "", galeries)))));
      const libres = b.champs.filter((ch) => !(p.fiche || []).some((f) => f[3] === ch[2]));
      if (libres.length) corps.append(el("div", { classe: "e-table revele" }, el("table", {}, el("caption", {}, t.donnees),
        libres.map((ch) => el("tr", {}, el("th", {}, ctx.langue === "fr" ? ch[1] : ch[0]), el("td", {}, ctx.langue === "fr" ? ch[3] : ch[2]))))));
    }
  }
  if (!corps.children.length) corps.append(el("p", { classe: "w-attente" }, t.vide));
  const fiche = (p.fiche || []).length ? el("aside", { classe: "e-fiche revele" }, el("div", { classe: "e-fiche-titre" }, icone("parchemin"), t.fiche),
    el("dl", {}, p.fiche.map((f) => [el("dt", {}, ctx.langue === "fr" ? f[0] : f[1]), el("dd", { classe: f[2] ? "" : "inconnu" }, f[2] ? (ctx.langue === "fr" ? f[2] : f[3]) : t.inconnu)]).flat())) : null;
  return el("div", { classe: "w-feuille e-page" },
    fil(ctx, ...(c ? [{ txt: c[ctx.langue], href: "#encyclo/c/" + c.id }, { txt: s[ctx.langue] }] : [])),
    el("header", { classe: "e-entete revele" },
      p.img ? el("div", { classe: "e-entete-img" }, boutonImage(ctx, p.img, nomPage(ctx, p), galeries)) : null,
      el("div", { classe: "e-entete-texte" }, el("h2", {}, nomPage(ctx, p)), sousNom(ctx, p) ? el("div", { classe: "w-nom-en" }, sousNom(ctx, p)) : null,
        s ? el("span", { classe: "w-badge" }, s[ctx.langue]) : null)),
    el("div", { classe: "e-colonnes" }, corps, fiche),
    el("nav", { classe: "e-voisins" },
      i > 0 ? el("a", { href: "#encyclo/p/" + voisins[i - 1] }, "‹ ", nomPage(ctx, E.pages[voisins[i - 1]])) : el("span", {}),
      i >= 0 && i < voisins.length - 1 ? el("a", { href: "#encyclo/p/" + voisins[i + 1] }, nomPage(ctx, E.pages[voisins[i + 1]]), " ›") : el("span", {})),
    el("p", { classe: "w-note e-source" }, t.source, " ", ctx.lien(p.url, t.voirSource)));
}

// ── Agrandir une image (visionneuse) ──
function boutonImage(ctx, im, legende, galeries) {
  const idx = galeries.push({ im, legende }) - 1;
  return ctx.el("button", { type: "button", classe: "e-agrandir", "aria-label": T[ctx.langue].agrandir, onclick: () => visionneuse(ctx, galeries, idx) }, image(ctx, im));
}

function visionneuse(ctx, liste, depart) {
  const { el } = ctx, t = T[ctx.langue];
  let i = depart;
  const img = el("img", { classe: "e-vue-img", alt: "", draggable: "false" }), leg = el("p", { classe: "e-vue-leg" });
  const voile = el("div", { classe: "w-fond e-vue", role: "dialog", "aria-modal": "true", onclick: (ev) => { if (ev.target === voile) fermer(); } },
    el("button", { type: "button", classe: "w-fermer", "aria-label": t.fermer, onclick: () => fermer() }, icone("fermer")),
    liste.length > 1 ? el("button", { type: "button", classe: "e-vue-nav g", "aria-label": t.precedent, onclick: () => aller(-1) }, "‹") : null,
    el("figure", {}, img, leg),
    liste.length > 1 ? el("button", { type: "button", classe: "e-vue-nav d", "aria-label": t.suivant, onclick: () => aller(1) }, "›") : null);
  function montrer() { const x = liste[i]; img.src = imgSrc(ctx, x.im, true); leg.textContent = x.legende || ""; }
  function aller(d) { i = (i + d + liste.length) % liste.length; montrer(); }
  const touche = (ev) => { if (ev.key === "Escape") fermer(); else if (ev.key === "ArrowLeft") aller(-1); else if (ev.key === "ArrowRight") aller(1); };
  function fermer() { voile.remove(); document.body.classList.remove("w-bloque"); document.removeEventListener("keydown", touche); }
  montrer();
  document.body.append(voile); document.body.classList.add("w-bloque"); document.addEventListener("keydown", touche);
}
