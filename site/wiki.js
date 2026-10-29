// wiki.js — le wiki public de RELL Seas (29/10/2026). Données : GET /wiki/donnees. FR · EN.
// Seul le VÉRIFIÉ est montré (le serveur trie) ; chaque fiche porte sa preuve, la vidéo officielle et la minute.
// Les freins à la copie (clic droit, sélection, glisser, raccourcis d'inspection, impression) ralentissent la copie
// facile ; ils ne rendent rien invisible à qui le veut vraiment — le texte des crédits le dit.

const ICONES = { metier: "⚒", race: "🧬", faction: "⚑", mer: "🌊", trait: "✦", classe: "⚔", fruit: "🍈", haki: "🌀",
  carte_haki: "🂠", poster: "📜", style: "🥋", arme: "🗡", equipement: "🧭", navire: "⛵", piece_navire: "💣", monture: "🐾",
  monnaie: "🪙", boss: "☠", lieu: "🏝", systeme: "⚙" };
const T = {
  fr: { sous: "Vérifié · preuves officielles", chercher: "Chercher une fiche (nom français ou anglais)…", tout: "Tout",
    intro: (n) => `<strong>${n} fiches vérifiées</strong> sur RELL Seas, le jeu de RELL Games. Ici, seulement ce que les vidéos officielles et le studio ont montré : jamais de rumeur, ni de façon d'obtenir quoi que ce soit avant la sortie du jeu.`,
    preuve: "Vu dans", regarder: "Regarder", sans: "Aucune fiche ne correspond.", m3: "Movie 3", verifie: "Vérifié",
    videos: "Les vidéos officielles", fondateur: "Fondateur", direction: "Direction", rejoindre: "Rejoindre le clan sur Discord",
    droits: (c) => `Wiki non officiel réalisé par le clan ${c} : textes, tri et mise en page © ${c}, reproduction interdite sans accord. RELL Seas, ses noms et ses images appartiennent à RELL Games.`,
    releve: (d) => `Relevé du ${d}.`, fermer: "Fermer" },
  en: { sous: "Verified · official proof", chercher: "Search an entry (French or English name)…", tout: "All",
    intro: (n) => `<strong>${n} verified entries</strong> about RELL Seas, the game by RELL Games. Only what the official videos and the studio have shown: never rumours, nor how to obtain anything before the game is out.`,
    preuve: "Shown in", regarder: "Watch", sans: "No entry matches.", m3: "Movie 3", verifie: "Verified",
    videos: "Official videos", fondateur: "Founder", direction: "Leadership", rejoindre: "Join the clan on Discord",
    droits: (c) => `Unofficial wiki made by the ${c} clan: texts, sorting and layout © ${c}, no reproduction without permission. RELL Seas, its names and images belong to RELL Games.`,
    releve: (d) => `Updated ${d}.`, fermer: "Close" } };

let D = null, langue = (navigator.language || "fr").toLowerCase().startsWith("fr") ? "fr" : "en", filtre = "tout", q = "";
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
const plier = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
const nomType = (cle) => { const t = (D.types || []).find((x) => x.cle === cle); return t ? t[langue] : cle; };

function image(e) {
  const b = el("span", { classe: "w-image" + (e.image ? "" : " vide"), "aria-hidden": "true" });
  if (e.image) b.style.backgroundImage = `url("/tableau/espace/${e.image.replace(/"/g, "")}")`;   // en fond : pas de « enregistrer l'image »
  else b.textContent = ICONES[e.type] || "✦";
  return b;
}

function carte(e) {
  const t = T[langue];
  return el("button", { type: "button", classe: "w-carte", onclick: () => fiche(e) }, image(e),
    el("span", { classe: "w-carte-texte" },
      el("div", { classe: "w-nom" }, langue === "fr" ? e.nom : e.nom_en),
      (langue === "fr" ? e.nom !== e.nom_en : false) ? el("div", { classe: "w-nom-en" }, e.nom_en) : null,
      el("div", { classe: "w-resume" }, e[langue]),
      el("div", { classe: "w-badges" }, el("span", { classe: "w-badge" }, "✓ " + t.verifie), e.m3 ? el("span", { classe: "w-badge m3" }, t.m3) : null)));
}

function fiche(e) {
  const t = T[langue];
  const fond = el("div", { classe: "w-fond", role: "dialog", "aria-modal": "true", onclick: (ev) => { if (ev.target === fond) fond.remove(); } });
  const fermer = el("button", { type: "button", classe: "w-fermer", "aria-label": t.fermer, onclick: () => fond.remove() }, "×");
  fond.append(el("div", { classe: "w-fiche" }, fermer,
    el("div", { classe: "w-fiche-tete" }, image(e),
      el("div", {}, el("h2", {}, langue === "fr" ? e.nom : e.nom_en),
        el("div", { classe: "w-nom-en" }, [nomType(e.type), e.groupe, langue === "fr" && e.nom !== e.nom_en ? e.nom_en : ""].filter(Boolean).join(" · ")))),
    el("p", {}, e[langue]),
    ...(e.preuves || []).map((p) => el("div", { classe: "w-preuve" }, el("span", {}, `${t.preuve} « ${p.titre} » · ${p.minute}`),
      el("a", { classe: "w-lien", href: p.url, target: "_blank", rel: "noopener noreferrer" }, "▶ " + t.regarder)))));
  document.body.append(fond);
  fermer.focus();
  const echap = (ev) => { if (ev.key === "Escape") { fond.remove(); document.removeEventListener("keydown", echap); } };
  document.addEventListener("keydown", echap);
}

function dessiner() {
  const t = T[langue], zone = document.getElementById("w-contenu");
  document.documentElement.lang = langue;
  document.getElementById("w-sous").textContent = t.sous;
  document.getElementById("w-langue").textContent = langue === "fr" ? "EN" : "FR";
  const intro = el("p", { classe: "w-intro" }); intro.innerHTML = t.intro(D.entrees.length);   // texte du fichier, aucun contenu tiers
  const recherche = el("input", { classe: "w-recherche", type: "search", placeholder: t.chercher, value: q, "aria-label": t.chercher,
    oninput: (ev) => { q = ev.target.value; dessinerListe(); } });
  const puces = el("div", { classe: "w-puces", role: "group" },
    [["tout", t.tout], ...D.types.map((x) => [x.cle, x[langue]])].map(([cle, lib]) =>
      el("button", { type: "button", classe: "w-puce", "aria-pressed": String(filtre === cle), onclick: () => { filtre = cle; dessiner(); } }, lib)));
  const liste = el("div", { id: "w-liste" });
  zone.replaceChildren(intro, recherche, puces, liste);
  dessinerListe();
  if (q) { recherche.focus(); recherche.setSelectionRange(q.length, q.length); }
  pied();
  function dessinerListe() {
    const sel = D.entrees.filter((e) => (filtre === "tout" || e.type === filtre)
      && (!q || plier([e.nom, e.nom_en, e.fr, e.en].join(" ")).includes(plier(q))));
    const blocs = [];
    for (const ty of D.types) {
      const l = sel.filter((e) => e.type === ty.cle);
      if (l.length) blocs.push(el("h2", { classe: "w-section" }, ty[langue] + " · " + l.length), el("div", { classe: "w-grille" }, l.map(carte)));
    }
    liste.replaceChildren(...(blocs.length ? blocs : [el("p", { classe: "w-attente" }, t.sans)]));
  }
}

function pied() {
  const t = T[langue], c = D.credits || {}, p = document.getElementById("w-pied");
  p.replaceChildren(
    el("div", { classe: "w-credits" },
      el("div", {}, el("div", {}, el("strong", {}, t.fondateur + " : "), c.fondateur || ""),
        (c.direction || []).length ? el("div", {}, el("strong", {}, t.direction + " : "), c.direction.join(", ")) : null),
      c.discord ? el("a", { classe: "w-rejoindre", href: c.discord, target: "_blank", rel: "noopener noreferrer" }, "⚓ " + t.rejoindre) : null),
    el("p", {}, el("strong", {}, t.videos + " : ")),
    el("ul", { classe: "w-videos" }, (D.videos || []).slice(0, 12).map((v) => el("li", {}, el("a", { href: v.url, target: "_blank", rel: "noopener noreferrer" }, v.titre)))),
    el("p", { classe: "w-note" }, t.droits(c.clan || "GoRP SEA") + (D.releve ? " " + t.releve(D.releve) : "")));
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
  .catch(() => { document.getElementById("w-attente").textContent = "Le wiki est indisponible pour le moment. · The wiki is unavailable right now."; });
