// wiki.js — le Grimoire de RELL Seas, le wiki public du clan (29/10/2026). Données : GET /wiki/donnees. FR · EN.
// Seul le VÉRIFIÉ est montré (le serveur trie) ; chaque fiche porte sa preuve, la vidéo officielle et la minute.
// Vivant : la bannière fait défiler les illustrations officielles de RELL, chaque catégorie a sa pancarte et son fond.
// Les freins à la copie (clic droit, sélection, glisser, raccourcis d'inspection, impression) ralentissent la copie
// facile ; ils ne rendent rien invisible à qui le veut vraiment.

const ICONES = { metier: "⚒", race: "🧬", faction: "⚑", mer: "🌊", trait: "✦", classe: "⚔", fruit: "🍈", haki: "🌀",
  carte_haki: "🂠", poster: "📜", style: "🥋", arme: "🗡", equipement: "🧭", navire: "⛵", piece_navire: "💣", monture: "🐾",
  monnaie: "🪙", boss: "☠", lieu: "🏝", systeme: "⚙" };
const T = {
  fr: { sous: "Le wiki vérifié du clan", titre1: "Le grimoire de", accroche: "Tout ce que RELL a vraiment montré de RELL Seas — fruits, races, Haki, navires, boss — vérifié une fiche à la fois, preuve vidéo officielle à l'appui.",
    explorer: "Ouvrir le grimoire", rejoindre: "Rejoindre le clan", fiches: "fiches", fruits: "fruits", boss: "boss", videos_n: "vidéos officielles",
    categories: "Les pancartes du port", une: "À la une · Movie 3", unePhrase: "Les nouveautés montrées dans RELL Seas: The Movie 3.",
    videos: "Les vidéos officielles de RELL", videosPhrase: "Les sources de ce wiki : chaque fiche renvoie à la minute exacte.",
    tout: "Toutes les fiches", chercher: "Chercher une fiche (nom français ou anglais)…", sans: "Aucune fiche ne correspond.",
    preuve: "Vu dans", regarder: "Regarder", m3: "Movie 3", verifie: "Vérifié", fermer: "Fermer", liste: "Le registre",
    fondateur: "Fondateur", direction: "Direction", regle: "Ici, jamais de rumeur ni de « comment l'obtenir » : le jeu n'est pas encore sorti, et personne ne le sait vraiment.",
    droits: (c) => `Wiki non officiel réalisé par le clan ${c} : textes, tri et mise en page © ${c}, reproduction interdite sans accord. RELL Seas, ses noms et ses images (illustrations des vidéos officielles) appartiennent à RELL Games.`,
    releve: (d) => `Relevé du ${d}.` },
  en: { sous: "The clan's verified wiki", titre1: "The grimoire of", accroche: "Everything RELL has really shown of RELL Seas — fruits, races, Haki, ships, bosses — verified one entry at a time, with official video proof.",
    explorer: "Open the grimoire", rejoindre: "Join the clan", fiches: "entries", fruits: "fruits", boss: "bosses", videos_n: "official videos",
    categories: "The harbour signs", une: "Featured · Movie 3", unePhrase: "What's new in RELL Seas: The Movie 3.",
    videos: "RELL's official videos", videosPhrase: "This wiki's sources: every entry links to the exact minute.",
    tout: "All entries", chercher: "Search an entry (French or English name)…", sans: "No entry matches.",
    preuve: "Shown in", regarder: "Watch", m3: "Movie 3", verifie: "Verified", fermer: "Close", liste: "The register",
    fondateur: "Founder", direction: "Leadership", regle: "Never rumours nor “how to get it” here: the game isn't out yet, and nobody really knows.",
    droits: (c) => `Unofficial wiki made by the ${c} clan: texts, sorting and layout © ${c}, no reproduction without permission. RELL Seas, its names and images (official video artwork) belong to RELL Games.`,
    releve: (d) => `Updated ${d}.` } };

let D = null, langue = (navigator.language || "fr").toLowerCase().startsWith("fr") ? "fr" : "en", filtre = "tout", q = "", minuteur = 0;
try { const l = localStorage.getItem("wiki-langue"); if (l === "fr" || l === "en") langue = l; } catch (_e) { /* navigation privée */ }

function el(tag, attrs, ...enfants) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "classe") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? "" : v);
  }
  for (const e of enfants.flat()) if (e != null && e !== false) n.append(e.nodeType ? e : document.createTextNode(String(e)));
  return n;
}
const plier = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
const src = (chemin) => "/tableau/espace/" + String(chemin || "").replace(/["\\]/g, "");
const fondDe = (chemin, petit) => (chemin ? `url("${src(chemin)}${petit ? "_p" : ""}.webp")` : "");
const nom = (e) => (langue === "fr" ? e.nom : e.nom_en);

function image(e) {
  const b = el("span", { classe: "w-image" + (e.image ? "" : " vide"), "aria-hidden": "true" });
  if (e.image) b.style.backgroundImage = `url("${src(e.image)}")`;   // en fond : pas d'« enregistrer l'image »
  else b.textContent = ICONES[e.type] || "✦";
  return b;
}

function carte(e, grande) {
  const t = T[langue];
  return el("button", { type: "button", classe: "w-carte" + (grande ? " grande" : ""), onclick: () => fiche(e) }, image(e),
    el("span", { classe: "w-carte-texte" },
      el("span", { classe: "w-nom" }, nom(e)),
      langue === "fr" && e.nom !== e.nom_en ? el("span", { classe: "w-nom-en" }, e.nom_en) : null,
      el("span", { classe: "w-resume" }, e[langue]),
      el("span", { classe: "w-badges" }, el("span", { classe: "w-badge" }, "✓ " + t.verifie), e.m3 ? el("span", { classe: "w-badge m3" }, t.m3) : null)));
}

function fiche(e) {
  const t = T[langue], ty = D.types.find((x) => x.cle === e.type) || {};
  const fond = el("div", { classe: "w-fond", role: "dialog", "aria-modal": "true", "aria-label": nom(e), onclick: (ev) => { if (ev.target === fond) fermer(); } });
  const bandeau = el("div", { classe: "w-fiche-bandeau" });
  const art = (e.preuves && e.preuves[0] && e.preuves[0].fond) || ty.fond;
  if (art) bandeau.style.backgroundImage = fondDe(art);
  const btn = el("button", { type: "button", classe: "w-fermer", "aria-label": t.fermer, onclick: () => fermer() }, "×");
  fond.append(el("div", { classe: "w-fiche" }, bandeau, btn,
    el("div", { classe: "w-fiche-corps" },
      el("div", { classe: "w-fiche-tete" }, image(e),
        el("div", {}, el("h2", {}, nom(e)),
          el("div", { classe: "w-nom-en" }, [ty[langue], e.groupe, langue === "fr" && e.nom !== e.nom_en ? e.nom_en : ""].filter(Boolean).join(" · ")))),
      el("p", { classe: "w-fiche-texte" }, e[langue]),
      ...(e.preuves || []).map((p) => el("div", { classe: "w-preuve" },
        el("span", {}, el("span", { classe: "w-sceau", "aria-hidden": "true" }), `${t.preuve} « ${p.titre} » · ${p.minute}`),
        el("a", { classe: "w-lien", href: p.url, target: "_blank", rel: "noopener noreferrer" }, "▶ " + t.regarder))))));
  document.body.append(fond);
  document.body.classList.add("w-bloque");
  btn.focus();
  const echap = (ev) => { if (ev.key === "Escape") fermer(); };
  document.addEventListener("keydown", echap);
  function fermer() { fond.remove(); document.body.classList.remove("w-bloque"); document.removeEventListener("keydown", echap); }
}

function heros() {
  const t = T[langue], c = D.credits || {}, n = D.entrees.length;
  const compte = (ty) => D.entrees.filter((e) => e.type === ty).length;
  const fonds = el("div", { classe: "w-heros-fonds", "aria-hidden": "true" },
    (D.heros || []).map((h, i) => { const f = el("span", { classe: "w-heros-fond" + (i === 0 ? " actif" : "") }); f.style.backgroundImage = fondDe(h.fond); return f; }));
  const pancarte = (val, lib) => el("div", { classe: "w-pancarte" }, el("span", { classe: "w-clou" }), el("strong", {}, String(val)), el("span", {}, lib));
  return el("section", { classe: "w-heros" }, fonds,
    el("div", { classe: "w-heros-contenu" },
      el("div", { classe: "w-affiche" },
        el("span", { classe: "w-ruban" }, t.sous + " " + (c.clan || "GoRP SEA")),
        el("span", { classe: "w-affiche-haut" }, t.titre1),
        el("h1", { classe: "w-affiche-titre" }, "RELL Seas"),
        el("p", { classe: "w-accroche" }, t.accroche),
        el("div", { classe: "w-actions" },
          el("a", { classe: "w-bouton laiton", href: "#w-registre", onclick: (ev) => { ev.preventDefault(); document.getElementById("w-registre").scrollIntoView({ behavior: "smooth" }); } }, "📖 " + t.explorer),
          c.discord ? el("a", { classe: "w-bouton bois", href: c.discord, target: "_blank", rel: "noopener noreferrer" }, "⚓ " + t.rejoindre) : null)),
      el("div", { classe: "w-pancartes" }, pancarte(n, t.fiches), pancarte(compte("fruit"), t.fruits), pancarte(compte("boss"), t.boss),
        pancarte((D.videos || []).length, t.videos_n))));
}

function enseignes() {
  const t = T[langue];
  return el("section", { classe: "w-bloc" }, el("h2", { classe: "w-section" }, t.categories),
    el("div", { classe: "w-enseignes" }, D.types.map((ty) => {
      const nb = D.entrees.filter((e) => e.type === ty.cle).length;
      const b = el("button", { type: "button", classe: "w-enseigne", onclick: () => { filtre = ty.cle; q = ""; dessinerRegistre(); document.getElementById("w-registre").scrollIntoView({ behavior: "smooth" }); } },
        el("span", { classe: "w-corde", "aria-hidden": "true" }),
        el("span", { classe: "w-planchette" }, el("span", { classe: "w-enseigne-image" + (ty.icone ? "" : " vide"), "aria-hidden": "true" }, ty.icone ? "" : (ICONES[ty.cle] || "✦")),
          el("span", { classe: "w-enseigne-nom" }, ty[langue]), el("span", { classe: "w-enseigne-nb" }, String(nb))));
      if (ty.icone) b.querySelector(".w-enseigne-image").style.backgroundImage = `url("${src(ty.icone)}")`;
      if (ty.fond) b.querySelector(".w-planchette").style.setProperty("--fond", fondDe(ty.fond, true));
      return b;
    })));
}

function aLaUne() {
  const t = T[langue], l = D.entrees.filter((e) => e.m3 && e.image).slice(0, 12);
  if (!l.length) return null;
  return el("section", { classe: "w-bloc w-une" }, el("h2", { classe: "w-section" }, "✨ " + t.une), el("p", { classe: "w-phrase" }, t.unePhrase),
    el("div", { classe: "w-defile" }, l.map((e) => carte(e, true))));
}

function videos() {
  const t = T[langue];
  return el("section", { classe: "w-bloc" }, el("h2", { classe: "w-section" }, "🎬 " + t.videos), el("p", { classe: "w-phrase" }, t.videosPhrase),
    el("div", { classe: "w-videos" }, (D.videos || []).map((v) => {
      const a = el("a", { classe: "w-video", href: v.url, target: "_blank", rel: "noopener noreferrer" },
        el("span", { classe: "w-video-image", "aria-hidden": "true" }, el("span", { classe: "w-lecture" }, "▶"), v.duree ? el("span", { classe: "w-duree" }, v.duree) : null),
        el("span", { classe: "w-video-titre" }, v.titre));
      if (v.fond) a.firstChild.style.backgroundImage = fondDe(v.fond, true);
      return a;
    })));
}

function registre() {
  const t = T[langue];
  return el("section", { classe: "w-bloc", id: "w-registre" }, el("h2", { classe: "w-section" }, "📜 " + t.liste),
    el("input", { classe: "w-recherche", type: "search", placeholder: t.chercher, value: q, "aria-label": t.chercher,
      oninput: (ev) => { q = ev.target.value; dessinerListe(); } }),
    el("div", { classe: "w-puces", role: "group", id: "w-puces" }), el("div", { id: "w-liste" }));
}

function dessinerRegistre() {
  const t = T[langue], puces = document.getElementById("w-puces");
  const r = document.querySelector(".w-recherche"); if (r && r.value !== q) r.value = q;
  puces.replaceChildren(...[["tout", t.tout], ...D.types.map((x) => [x.cle, x[langue]])].map(([cle, lib]) =>
    el("button", { type: "button", classe: "w-puce", "aria-pressed": String(filtre === cle), onclick: () => { filtre = cle; dessinerRegistre(); } }, lib)));
  dessinerListe();
}

function dessinerListe() {
  const t = T[langue], liste = document.getElementById("w-liste");
  const sel = D.entrees.filter((e) => (filtre === "tout" || e.type === filtre) && (!q || plier([e.nom, e.nom_en, e.fr, e.en].join(" ")).includes(plier(q))));
  const blocs = [];
  for (const ty of D.types) {
    const l = sel.filter((e) => e.type === ty.cle);
    if (!l.length) continue;
    const titre = el("h3", { classe: "w-rubrique" }, el("span", {}, ty[langue]), el("span", { classe: "w-rubrique-nb" }, String(l.length)));
    if (ty.fond) titre.style.setProperty("--fond", fondDe(ty.fond, true));
    blocs.push(titre, el("div", { classe: "w-grille" }, l.map((e) => carte(e))));
  }
  liste.replaceChildren(...(blocs.length ? blocs : [el("p", { classe: "w-attente" }, t.sans)]));
}

function pied() {
  const t = T[langue], c = D.credits || {};
  return [el("div", { classe: "w-credits" },
    el("div", { classe: "w-signature" }, el("span", { classe: "w-sceau grand", "aria-hidden": "true" }),
      el("div", {}, el("div", {}, el("strong", {}, t.fondateur + " : "), c.fondateur || ""),
        (c.direction || []).length ? el("div", {}, el("strong", {}, t.direction + " : "), c.direction.join(", ")) : null,
        el("div", { classe: "w-note" }, t.regle))),
    c.discord ? el("a", { classe: "w-bouton laiton", href: c.discord, target: "_blank", rel: "noopener noreferrer" }, "⚓ " + t.rejoindre) : null),
  el("p", { classe: "w-note" }, t.droits(c.clan || "GoRP SEA") + (D.releve ? " " + t.releve(D.releve) : ""))];
}

function dessiner() {
  const zone = document.getElementById("w-contenu");
  document.documentElement.lang = langue;
  document.getElementById("w-sous").textContent = T[langue].sous + " " + ((D.credits || {}).clan || "GoRP SEA");
  document.getElementById("w-langue").textContent = langue === "fr" ? "EN" : "FR";
  zone.replaceChildren(heros(), el("div", { classe: "w-feuille" }, enseignes(), aLaUne(), registre(), videos()));
  document.getElementById("w-pied").replaceChildren(...pied());
  dessinerRegistre();
  clearInterval(minuteur);
  const fonds = [...document.querySelectorAll(".w-heros-fond")];
  if (fonds.length > 1 && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    let i = 0;
    minuteur = setInterval(() => { fonds[i].classList.remove("actif"); i = (i + 1) % fonds.length; fonds[i].classList.add("actif"); }, 7000);
  }
}

// ── Les freins à la copie ──
const bloquer = (ev) => { if (!(ev.target && ev.target.closest && ev.target.closest("input"))) ev.preventDefault(); };
["contextmenu", "dragstart", "copy", "cut", "selectstart"].forEach((n) => document.addEventListener(n, bloquer));
document.addEventListener("keydown", (ev) => {
  const k = (ev.key || "").toLowerCase(), ctrl = ev.ctrlKey || ev.metaKey;
  if (k === "f12" || (ctrl && ev.shiftKey && ["i", "j", "c", "k"].includes(k)) || (ctrl && ["u", "s", "p"].includes(k))) ev.preventDefault();
});

document.getElementById("w-langue").addEventListener("click", () => {
  langue = langue === "fr" ? "en" : "fr";
  try { localStorage.setItem("wiki-langue", langue); } catch (_e) { /* rien */ }
  if (D) dessiner();
});

fetch("/wiki/donnees", { headers: { Accept: "application/json" } }).then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
  .then((d) => { D = d; dessiner(); })
  .catch(() => { const a = document.getElementById("w-attente"); if (a) a.textContent = "Le wiki est indisponible pour le moment. · The wiki is unavailable right now."; });
