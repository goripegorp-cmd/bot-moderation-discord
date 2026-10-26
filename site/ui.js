// ui.js — les composants de la Capitainerie : boutons, cases sur mesure, listes, menus, pancarte qui s'ouvre,
// confirmations, groupes repliables, « voir plus », index A–Z, tuiles, graphiques à l'encre, notes épinglées.

import { h, icone, $, $$, nombre, sansEmoji, initiales, srcSure, norm, reduit, telephone, retarder, libelleMoisCourt, libelleJour, remplacer, quantite, ajouter } from "./dom.js";
import { etat, enLigne, raisonHorsLigne, ecouter, P } from "./noyau.js";

let compteurId = 0;
export const idUnique = (p) => (p || "u") + "-" + (++compteurId);
const popoverOk = typeof HTMLElement !== "undefined" && "showPopover" in HTMLElement.prototype;

// ─── Notes épinglées ───────────────────────────────────────────────────────
export function toast(texte, genre) {
  const hote = $("#toasts");
  if (!hote) return;
  const ic = genre === "erreur" ? "attention" : genre === "succes" ? "succes" : "info";
  const t = h("div", { classe: "toast " + (genre || "") }, icone(ic), h("div", { classe: "toast-texte" }, texte));
  ajouter(hote, [t]);
  while (hote.children.length > 3) hote.firstElementChild.remove();
  if (popoverOk) {
    if (!hote.hasAttribute("popover")) hote.setAttribute("popover", "manual");
    try { if (hote.matches(":popover-open")) hote.hidePopover(); hote.showPopover(); } catch (e) { /* hors couche supérieure */ }
  }
  setTimeout(() => {
    t.remove();
    if (popoverOk && !hote.children.length) { try { hote.hidePopover(); } catch (e) { /* déjà fermé */ } }
  }, genre === "erreur" ? 6500 : 3800);
}

export async function copier(texte, message) {
  try { await navigator.clipboard.writeText(texte); toast(message || "Copié", "succes"); }
  catch (e) { toast("Copie impossible ici : sélectionne le texte à la main.", "erreur"); }
}
export const boutonCopie = (texte, message) => h("button", {
  classe: "bouton-icone copier", type: "button", title: "Copier", "aria-label": "Copier",
  onclick: (e) => { e.stopPropagation(); copier(texte, message); },
}, icone("copier"));

// ─── Boutons ───────────────────────────────────────────────────────────────
/** Un bouton. reseau: true → désactivé hors ligne, avec la raison. */
export function bouton(libelle, o = {}) {
  const b = h("button", {
    classe: "bouton" + (o.classe ? " " + o.classe : ""), type: o.type || "button",
    title: o.titre || null, "aria-label": o.aria || null, onclick: o.onclick || null, disabled: o.disabled || null,
  }, o.icone ? icone(o.icone) : null, libelle ? h("span", {}, libelle) : null);
  if (o.reseau) { b.dataset.reseau = "1"; b.dataset.titre = o.titre || ""; majBoutonReseau(b); }
  return b;
}
export function boutonIcone(nomIcone, aria, onclick, classe) {
  return h("button", { classe: "bouton-icone" + (classe ? " " + classe : ""), type: "button", "aria-label": aria, title: aria, onclick }, icone(nomIcone));
}
function majBoutonReseau(b) {
  const ok = enLigne();
  if (b.dataset.forceOff === "1") return;
  b.disabled = !ok;
  b.classList.toggle("sans-reseau", !ok);
  b.title = ok ? (b.dataset.titre || "") : raisonHorsLigne();
}
export function majBoutonsReseau(racine) { for (const b of $$("[data-reseau]", racine || document)) majBoutonReseau(b); }
ecouter("reseau", () => majBoutonsReseau());
ecouter("session", () => majBoutonsReseau());

export const lienNom = (id, ouvrir) => h("button", {
  classe: "lien-nom", type: "button", title: "Ouvrir sa fiche",
  onclick: (e) => { e.stopPropagation(); ouvrir(id); },
}, nomDe(P(id)));

export const nomDe = (p) => sansEmoji(p && p.nom) || (p && p.pseudo) || "Sans nom";

// ─── Personnes, pastilles, tampons ─────────────────────────────────────────
export function avatar(p, taille) {
  const c = "avatar" + (taille ? " " + taille : "");
  const init = initiales((p && (p.nom || p.pseudo)) || "?");
  const src = srcSure(p && p.avatar);
  if (src) {
    const i = h("img", { classe: c, src, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" });
    i.addEventListener("error", () => i.replaceWith(h("span", { classe: c, "aria-hidden": "true" }, init)), { once: true });
    return i;
  }
  return h("span", { classe: c, "aria-hidden": "true" }, init);
}
export const pastille = (texte, teinte, titre, sansPoint) =>
  h("span", { classe: "pastille" + (sansPoint ? " sans-point" : ""), vars: teinte ? { "--teinte": teinte } : null, title: titre || null }, texte);
export const tampon = (texte, couleur, droit) => h("span", { classe: "tampon" + (couleur ? " " + couleur : "") + (droit ? " droit" : "") }, texte);
export const compteur = (n, chaud) => h("span", { classe: "compteur" + (chaud ? " chaud" : "") }, n > 999 ? "999+" : String(n));

export function vide(titre, texte, nomIcone) {
  return h("div", { classe: "vide" }, icone(nomIcone || "boussole"), h("b", {}, titre), texte ? h("p", {}, texte) : null);
}
export function squelettes(n, classe) {
  return h("div", { classe: "pile", "aria-hidden": "true" }, Array.from({ length: n || 3 }, () => h("div", { classe: "squelette " + (classe || "") })));
}
export function chargement(texte) {
  return h("div", { classe: "attente-depart" }, h("span", { classe: "attente-boussole", "aria-hidden": "true" }), h("p", {}, texte || "Chargement…"));
}

// ─── Titres ────────────────────────────────────────────────────────────────
export function titreRubrique(rub, extra) {
  return h("header", { classe: "titre-rubrique" },
    h("span", { classe: "sceau-rubrique", "aria-hidden": "true" }, icone(rub.icone)),
    h("h1", {}, rub.titre),
    h("p", {}, extra || rub.phrase || ""));
}
export function sectionTete(titre, nomIcone, compte, ...droite) {
  return h("div", { classe: "section-tete" },
    h("h2", {}, nomIcone ? icone(nomIcone) : null, h("span", { classe: "titre-texte" }, titre)),
    compte !== undefined && compte !== null && compte !== "" ? h("span", { classe: "compte" }, compte) : null,
    droite.length ? h("div", { classe: "rangee" }, droite) : null);
}
export function section(titre, nomIcone, compte, contenu, ...droite) {
  return h("section", { classe: "section" }, sectionTete(titre, nomIcone, compte, ...droite), contenu);
}

// ─── Tuiles ────────────────────────────────────────────────────────────────
const precedents = new Map();
export function tuile(o) {
  const val = h("div", { classe: "val" + (o.texte !== undefined ? " texte" : "") }, o.texte !== undefined ? o.texte : nombre(o.val));
  const corps = [h("div", { classe: "tuile-tete" }, o.icone ? icone(o.icone) : null, h("span", { classe: "lib" }, o.lib)), val, o.sous ? h("div", { classe: "sous" }, o.sous) : null];
  const t = o.clic
    ? h("button", { classe: "tuile", type: "button", onclick: o.clic, vars: { "--teinte": o.teinte || null }, title: o.titre || null }, corps)
    : h("div", { classe: "tuile", vars: { "--teinte": o.teinte || null } }, corps);
  if (o.texte === undefined && o.cle) animerNombre(val, o.cle, Number(o.val) || 0, o.suffixe || "");
  else if (o.suffixe) val.textContent += o.suffixe;
  return t;
}
function animerNombre(el, cle, cible, suffixe) {
  const avant = precedents.get(cle);
  precedents.set(cle, cible);
  if (reduit.matches || avant === cible || avant === undefined) { el.textContent = nombre(cible) + suffixe; return; }
  const t0 = performance.now();
  const pas = (t) => {
    const p = Math.min(1, (t - t0) / 700);
    el.textContent = nombre(Math.round(avant + (cible - avant) * (1 - Math.pow(1 - p, 3)))) + suffixe;
    if (p < 1) requestAnimationFrame(pas);
  };
  requestAnimationFrame(pas);
}
export const tuiles = (...l) => h("div", { classe: "tuiles" }, l);

// ─── Filtres ───────────────────────────────────────────────────────────────
/** options : [[cle, libelle, nombre?, teinte?]] */
export function puces(options, actif, choisir, label) {
  return h("div", { classe: "puces", role: "group", "aria-label": label || "Filtres" }, options.filter(Boolean).map(([cle, lib, n, teinte]) =>
    h("button", { classe: "puce", type: "button", "aria-pressed": String(String(actif) === String(cle)), onclick: () => choisir(cle), vars: teinte ? { "--teinte": teinte } : null },
      teinte ? h("i", { classe: "goutte", "aria-hidden": "true" }) : null, h("span", { classe: "puce-lib" }, lib),
      n !== undefined && n !== null ? h("span", { classe: "n" }, nombre(n)) : null)));
}
export function segment(valeur, options, changer, label) {
  const g = h("div", { classe: "segment", role: "group", "aria-label": label || null });
  for (const [v, l] of options) {
    ajouter(g, [h("button", { type: "button", "aria-pressed": String(String(valeur) === String(v)), onclick: (e) => {
      for (const b of g.children) b.setAttribute("aria-pressed", String(b === e.currentTarget));
      changer(v);
    } }, l)]);
  }
  return g;
}
export function recherche(valeur, placeholder, changer, o = {}) {
  const i = h("input", { type: "search", name: o.nom || "recherche", value: valeur || "", placeholder, "aria-label": placeholder, autocomplete: "off", spellcheck: "false", enterkeyhint: "search" });
  const declencher = retarder(() => changer(norm(i.value.trim())), o.delai ?? 120);
  i.addEventListener("input", () => { effacer.hidden = !i.value; declencher(); });
  const effacer = boutonIcone("fermer", "Effacer la recherche", () => { i.value = ""; effacer.hidden = true; changer(""); i.focus(); }, "effacer");
  effacer.hidden = !valeur;
  const lbl = h("label", { classe: "recherche" }, icone("rechercher"), i, effacer);
  lbl.champ = i;
  return lbl;
}

// ─── Cases, interrupteurs, radios (sur mesure) ─────────────────────────────
export function caseACocher(libelle, coche, changer, o = {}) {
  const i = h("input", { type: "checkbox", name: o.nom || null, disabled: o.disabled || null, "aria-label": o.aria || null });
  i.checked = !!coche;
  if (o.indetermine) i.indeterminate = true;
  i.addEventListener("change", () => changer && changer(i.checked, i));
  const l = h("label", { classe: "case" + (o.classe ? " " + o.classe : ""), title: o.titre || null }, i, h("span", { classe: "case-boite", "aria-hidden": "true" }), libelle !== null && libelle !== undefined ? h("span", { classe: "case-texte" }, libelle) : null);
  l.entree = i;
  return l;
}
export function interrupteur(libelle, coche, changer, o = {}) {
  const i = h("input", { type: "checkbox", role: "switch", name: o.nom || null, disabled: o.disabled || null });
  i.checked = !!coche;
  i.addEventListener("change", () => changer && changer(i.checked, i));
  const l = h("label", { classe: "interrupteur", title: o.titre || null }, i, h("span", { classe: "interrupteur-rail", "aria-hidden": "true" }), h("span", { classe: "case-texte" }, libelle));
  l.entree = i;
  return l;
}
export function radios(nom, options, valeur, changer, legende) {
  return h("fieldset", { classe: "choix-groupe" }, legende ? h("legend", {}, legende) : null, options.map(([v, l, aide]) => {
    const i = h("input", { type: "radio", name: nom, value: v });
    i.checked = String(v) === String(valeur);
    i.addEventListener("change", () => { if (i.checked) changer(v); });
    return h("label", { classe: "radio" }, i, h("span", { classe: "radio-rond", "aria-hidden": "true" }),
      h("span", { classe: "case-texte" }, l, aide ? h("span", { classe: "option-sous" }, " — " + aide) : null));
  }));
}

// ─── Champs ────────────────────────────────────────────────────────────────
export function champ(libelle, controle, o = {}) {
  const id = controle.id || idUnique("champ");
  if (!controle.id && controle.tagName && /^(INPUT|TEXTAREA|SELECT)$/.test(controle.tagName)) controle.id = id;
  const aide = o.aide ? h("span", { classe: "champ-aide", id: id + "-aide" }, o.aide) : null;
  if (aide && controle.setAttribute) controle.setAttribute("aria-describedby", id + "-aide");
  const erreur = h("span", { classe: "champ-erreur", role: "alert", hidden: true });
  const lib = /^(INPUT|TEXTAREA|SELECT)$/.test(controle.tagName || "")
    ? h("label", { classe: "champ-lib", for: controle.id }, libelle, o.optionnel ? h("span", { classe: "optionnel" }, " (facultatif)") : null)
    : h("span", { classe: "champ-lib" }, libelle, o.optionnel ? h("span", { classe: "optionnel" }, " (facultatif)") : null);
  const c = h("div", { classe: "champ" + (o.large ? " large" : "") + (o.classe ? " " + o.classe : "") }, lib, controle, aide, erreur);
  c.erreur = (texte) => { erreur.textContent = texte || ""; erreur.hidden = !texte; if (controle.setAttribute) controle.setAttribute("aria-invalid", texte ? "true" : "false"); };
  return c;
}
export const saisie = (attrs) => h("input", Object.assign({ type: "text", autocomplete: "off", spellcheck: "false", classe: "saisie" }, attrs));
export const zoneTexte = (attrs, valeur) => { const t = h("textarea", Object.assign({ rows: 4, classe: "saisie" }, attrs)); t.value = valeur || ""; return t; };

// ─── Couche supérieure : placer une fenêtre flottante près de son déclencheur ─
function placer(pop, ancre) {
  const r = ancre.getBoundingClientRect();
  const vv = window.visualViewport;
  const lv = vv ? vv.width : innerWidth, hv = vv ? vv.height : innerHeight;
  const marge = 8;
  if (telephone.matches && pop.classList.contains("feuille-basse")) return;
  pop.style.setProperty("min-width", Math.min(Math.max(r.width, 200), lv - 2 * marge) + "px");
  const lp = Math.min(pop.offsetWidth || 260, lv - 2 * marge);
  const dessous = hv - r.bottom - marge, dessus = r.top - marge;
  const enHaut = dessous < 200 && dessus > dessous;
  const dispo = Math.max(140, enHaut ? dessus - 6 : dessous - 6);
  pop.style.setProperty("max-height", Math.min(420, dispo) + "px");
  let gauche = r.left;
  if (gauche + lp > lv - marge) gauche = Math.max(marge, r.right - lp);
  gauche = Math.max(marge, Math.min(gauche, lv - marge - lp));
  pop.style.setProperty("left", gauche + "px");
  const hp = Math.min(pop.offsetHeight || 0, dispo);
  pop.style.setProperty("top", (enHaut ? Math.max(marge, r.top - 6 - hp) : r.bottom + 6) + "px");
}

function montrerFlottant(pop, ancre, surFermer) {
  const hote = ancre.closest("dialog[open]") || document.body;
  ajouter(hote, [pop]);
  let ferme = false;
  const fermer = (rendreFocus) => {
    if (ferme) return;
    ferme = true;
    if (popoverOk) { try { pop.hidePopover(); } catch (e) { /* déjà fermé */ } }
    pop.remove();
    document.removeEventListener("pointerdown", dehors, true);
    removeEventListener("resize", repl);
    removeEventListener("scroll", repl, true);
    ancre.setAttribute("aria-expanded", "false");
    if (rendreFocus && ancre.isConnected) ancre.focus({ preventScroll: true });
    if (surFermer) surFermer();
  };
  const dehors = (e) => { if (!pop.contains(e.target) && !ancre.contains(e.target)) fermer(false); };
  const repl = () => { if (!telephone.matches) placer(pop, ancre); };
  if (popoverOk) {
    pop.setAttribute("popover", "manual");
    pop.showPopover();
  }
  ancre.setAttribute("aria-expanded", "true");
  placer(pop, ancre);
  requestAnimationFrame(() => placer(pop, ancre));
  document.addEventListener("pointerdown", dehors, true);
  addEventListener("resize", repl);
  addEventListener("scroll", repl, true);
  pop.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); fermer(true); } });
  return fermer;
}

// ─── Liste déroulante sur mesure ───────────────────────────────────────────
/** options : [{ v, l, sous?, icone?, img?, teinte? }] */
export function liste({ valeur, options, label, changer, plein, titre, desactive, cacherLabel }) {
  const valeurEl = h("span", { classe: "liste-valeur" });
  const b = h("button", { classe: "liste-bouton" + (plein ? " plein" : ""), type: "button", "aria-haspopup": "listbox", "aria-expanded": "false", "aria-label": label || null, disabled: desactive || null }, valeurEl, icone("bas"));
  let courant = valeur;
  let opts = options;
  const contenu = (o) => [o && o.img ? h("img", { src: o.img, alt: "" }) : null, o && o.icone ? icone(o.icone) : null,
    o && o.teinte ? h("i", { classe: "pastille-couleur", vars: { "--teinte": o.teinte } }) : null, h("span", { classe: "une-ligne" }, o ? o.l : "—")];
  const maj = () => {
    const o = opts.find((x) => String(x.v) === String(courant));
    remplacer(valeurEl, ...contenu(o || { l: titre || "Choisir…" }));
    b.title = (label ? label + " : " : "") + (o ? o.l : "");
  };
  b.addEventListener("click", () => {
    if (b.getAttribute("aria-expanded") === "true") return;
    ouvrirListe(b, opts, courant, (v) => { courant = v; maj(); changer && changer(v); }, label, contenu);
  });
  b.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); b.click(); }
  });
  maj();
  b.valeur = () => courant;
  b.poser = (v) => { courant = v; maj(); };
  b.options = (o) => { opts = o; maj(); };
  if (!label || cacherLabel) return b;
  return Object.assign(h("div", { classe: "liste-groupe" + (plein ? " plein" : "") }, h("span", { classe: "liste-lib", "aria-hidden": "true" }, label), b), { valeur: b.valeur, poser: b.poser, options: b.options, bouton: b });
}

function ouvrirListe(ancre, options, courant, choisir, label, contenu) {
  const id = idUnique("liste");
  const pop = h("div", { classe: "menu-pop feuille-basse", role: "listbox", id, "aria-label": label || "Choix", tabindex: "-1" });
  if (label && telephone.matches) ajouter(pop, [h("div", { classe: "menu-titre" }, label)]);
  const items = options.map((o) => h("button", {
    classe: "option", type: "button", role: "option", "aria-selected": String(String(o.v) === String(courant)), disabled: o.desactive || null,
    onclick: () => { choisir(o.v); fermer(true); },
  }, contenu(o).filter((x) => x && x.tagName !== "SPAN"), h("span", { classe: "option-lib" }, o.l, o.sous ? h("span", { classe: "option-sous" }, o.sous) : null)));
  ajouter(pop, [...items]);
  ancre.setAttribute("aria-controls", id);
  const fermer = montrerFlottant(pop, ancre);
  let tape = "", minuteur = 0;
  pop.addEventListener("keydown", (e) => {
    const actifs = items.filter((x) => !x.disabled);
    const i = actifs.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); actifs[Math.min(actifs.length - 1, i + 1)]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); actifs[Math.max(0, i - 1)]?.focus(); }
    else if (e.key === "Home") { e.preventDefault(); actifs[0]?.focus(); }
    else if (e.key === "End") { e.preventDefault(); actifs[actifs.length - 1]?.focus(); }
    else if (e.key === "Tab") { fermer(false); }
    else if (e.key.length === 1 && /\S/.test(e.key)) {
      tape += norm(e.key); clearTimeout(minuteur); minuteur = setTimeout(() => { tape = ""; }, 700);
      const t = actifs.find((x) => norm(x.textContent).startsWith(tape));
      if (t) t.focus();
    }
  });
  const sel = items.find((x) => x.getAttribute("aria-selected") === "true" && !x.disabled) || items.find((x) => !x.disabled);
  requestAnimationFrame(() => { sel?.focus({ preventScroll: true }); sel?.scrollIntoView({ block: "nearest" }); });
}

// ─── Menus (actions) ───────────────────────────────────────────────────────
/** items : [{ l, icone?, onclick?, href?, telecharger?, danger?, desactive?, sous? } | "-" | { titre }] */
export function menu(declencheur, items) {
  declencheur.setAttribute("aria-haspopup", "menu");
  declencheur.setAttribute("aria-expanded", "false");
  declencheur.addEventListener("click", (e) => {
    e.stopPropagation();
    if (declencheur.getAttribute("aria-expanded") === "true") return;
    const liste_ = typeof items === "function" ? items() : items;
    const pop = h("div", { classe: "menu-pop feuille-basse", role: "menu" });
    const boutons = [];
    for (const it of liste_.filter(Boolean)) {
      if (it === "-") { ajouter(pop, [h("hr")]); continue; }
      if (it.titre) { ajouter(pop, [h("div", { classe: "menu-titre" }, it.titre)]); continue; }
      const contenu = [it.icone ? icone(it.icone) : null, h("span", { classe: "option-lib" }, it.l, it.sous ? h("span", { classe: "option-sous" }, it.sous) : null)];
      const el = it.href
        ? h("a", { classe: "option" + (it.danger ? " danger" : ""), role: "menuitem", href: it.href, download: it.telecharger ? "" : null, "aria-disabled": it.desactive ? "true" : null, onclick: (ev) => { if (it.desactive) { ev.preventDefault(); return; } fermer(false); } }, contenu)
        : h("button", { classe: "option" + (it.danger ? " danger" : ""), role: "menuitem", type: "button", disabled: it.desactive || null, title: it.titre_ || null, onclick: () => { fermer(true); it.onclick && it.onclick(); } }, contenu);
      boutons.push(el);
      ajouter(pop, [el]);
    }
    const fermer = montrerFlottant(pop, declencheur);
    pop.addEventListener("keydown", (ev) => {
      const i = boutons.indexOf(document.activeElement);
      if (ev.key === "ArrowDown") { ev.preventDefault(); boutons[Math.min(boutons.length - 1, i + 1)]?.focus(); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); boutons[Math.max(0, i - 1)]?.focus(); }
      else if (ev.key === "Tab") fermer(false);
    });
    requestAnimationFrame(() => boutons.find((b) => !b.disabled)?.focus({ preventScroll: true }));
  });
  return declencheur;
}

// ─── La pancarte qui s'ouvre (fenêtre modale) ──────────────────────────────
const ouvertes = [];
/** Ouvre une pancarte. o : { titre, sous, icone, taille, garde (async → bool), surFermer, fermerSurFond } */
export function pancarte(o) {
  const idT = idUnique("pancarte-titre");
  const corps = h("div", { classe: "pancarte-corps" });
  const pied = h("div", { classe: "pancarte-pied" });
  const titreEl = h("h2", { id: idT }, o.titre, o.sous ? h("span", { classe: "sous-titre" }, o.sous) : null);
  const fermerB = boutonIcone("fermer", "Fermer", () => fermer());
  const dlg = h("dialog", { classe: "pancarte " + (o.taille || ""), "aria-labelledby": idT },
    h("div", { classe: "pancarte-cadre" }, h("div", { classe: "pancarte-feuille" },
      h("header", { classe: "pancarte-tete" }, o.icone ? icone(o.icone, "tete-ic") : null, titreEl, fermerB), corps, pied)));
  const avant = document.activeElement;
  ajouter(document.body, [dlg]);
  dlg.showModal();
  document.documentElement.classList.add("verrou");
  ouvertes.push(dlg);
  let ferme = false;
  async function fermer(valeur) {
    if (ferme) return;
    if (o.garde && !(await o.garde(valeur))) return;
    ferme = true;
    dlg.classList.add("ferme");
    await new Promise((ok) => setTimeout(ok, reduit.matches ? 120 : 200));
    dlg.close();
    dlg.remove();
    ouvertes.splice(ouvertes.indexOf(dlg), 1);
    if (!ouvertes.length) document.documentElement.classList.remove("verrou");
    if (avant && avant.isConnected && avant.focus) avant.focus({ preventScroll: true });
    if (o.surFermer) o.surFermer(valeur);
  }
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); fermer(); });
  if (o.fermerSurFond !== false) dlg.addEventListener("click", (e) => { if (e.target === dlg) fermer(); });
  const p = { dlg, corps, pied, titre: titreEl, fermer, fermee: () => ferme };
  return p;
}
export const pancartesOuvertes = () => ouvertes.length;

/** Une confirmation. o : { titre, texte, libelleOk, style, motif, motifRequis, motifLib, durees, choix, choixDefaut,
 *  mot (mot à recopier), contenu (nœuds en plus) } → Promise<{ motif, duree, choix } | null> */
export function confirmer(o) {
  return new Promise((fin) => {
    let resultat = null;
    const p = pancarte({ titre: o.titre, icone: o.icone || (o.style === "danger" ? "attention" : "info"), taille: o.taille || "etroite", surFermer: () => fin(resultat) });
    if (o.texte) ajouter(p.corps, [h("p", {}, o.texte)]);
    if (o.contenu) ajouter(p.corps, [...[o.contenu].flat()]);
    let choixL = null, dureeL = null, motifT = null, motT = null;
    if (o.choix) { choixL = liste({ valeur: o.choixDefaut ?? o.choix[0][0], options: o.choix.map(([v, l]) => ({ v, l })), label: o.choixLib || "Statut", plein: true }); ajouter(p.corps, [choixL]); }
    if (o.durees) {
      dureeL = liste({ valeur: 60, options: [[10, "10 minutes"], [60, "1 heure"], [360, "6 heures"], [1440, "1 jour"], [10080, "7 jours"]].map(([v, l]) => ({ v, l })), label: "Durée", plein: true });
      ajouter(p.corps, [dureeL]);
    }
    if (o.motif) {
      motifT = zoneTexte({ name: "motif", rows: 3, maxlength: 300, placeholder: o.motifRequis ? "Motif (obligatoire)" : "Motif (facultatif)" });
      ajouter(p.corps, [champ(o.motifLib || (o.motifRequis ? "Motif" : "Motif"), motifT, { optionnel: !o.motifRequis })]);
    }
    if (o.mot) {
      motT = saisie({ name: "confirmation", placeholder: o.mot });
      ajouter(p.corps, [champ("Écris " + o.mot + " pour confirmer", motT)]);
    }
    const ok = bouton(o.libelleOk || "Confirmer", { classe: o.style === "danger" ? "danger" : o.style === "vert" ? "vert" : "principal", icone: o.iconeOk || null });
    const verifier = () => { if (motT) ok.disabled = motT.value.trim().toUpperCase() !== o.mot.toUpperCase(); };
    if (motT) { motT.addEventListener("input", verifier); verifier(); }
    ok.addEventListener("click", () => {
      const texte = motifT ? motifT.value.trim() : "";
      if (o.motifRequis && texte.length < 3) { motifT.closest(".champ").erreur("Indique un motif (3 caractères au moins)."); motifT.focus(); return; }
      resultat = { motif: texte, duree: dureeL ? Number(dureeL.valeur()) : null, choix: choixL ? choixL.valeur() : null };
      p.fermer(true);
    });
    ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), ok]);
    requestAnimationFrame(() => (motifT || motT || ok).focus());
  });
}

// ─── Groupes repliables, « voir plus », index A–Z ──────────────────────────
const groupesOuverts = new Map();   // cle → ouvert : le choix de la personne, gardé d'un rendu à l'autre
/** Un groupe repliable avec compteur ; le contenu n'est construit qu'à la première ouverture.
 *  o.ouvert : imposé (true : une recherche en cours) ; o.defaut : l'état de départ, tant que la personne n'a pas
 *  ouvert ni fermé ce groupe (une mise à jour des données ne rouvre plus un groupe fermé). */
/** Une petite image de titre ; si elle ne se charge pas, une icône maison à sa place (jamais une image cassée). */
function imageOuIcone(src, repli = "drapeau") {
  if (!src) return null;
  const i = h("img", { src, alt: "" });
  if (!i.getAttribute("src")) return icone(repli);
  i.addEventListener("error", () => i.replaceWith(icone(repli)), { once: true });
  return i;
}
export function groupe(o, fabriquer) {
  const cle = o.cle || null;
  const ouvert = o.ouvert ?? (cle && groupesOuverts.has(cle) ? groupesOuverts.get(cle) : !!o.defaut);
  const corps = h("div", { classe: "groupe-corps" });
  const d = h("details", { classe: "groupe" + (o.classe ? " " + o.classe : "") },
    h("summary", {}, icone("droite", "chevron"),
      h("span", { classe: "groupe-titre" }, o.visuel || imageOuIcone(o.img), o.icone ? icone(o.icone) : null, h("span", {}, o.titre)),
      o.info ? h("span", { classe: "groupe-info" }, o.info) : null,
      o.compte !== undefined ? compteur(o.compte, o.chaud) : null),
    corps);
  let construit = false;
  const construire = () => {
    if (construit) return;
    construit = true;
    const c = typeof fabriquer === "function" ? fabriquer() : fabriquer;
    ajouter(corps, [...[c].flat().filter(Boolean)]);
  };
  d.addEventListener("toggle", () => {
    if (d.open) construire();
    if (cle) groupesOuverts.set(cle, d.open);
  });
  if (ouvert) { d.open = true; construire(); }
  return d;
}

/** Une liste paginée : n éléments, puis « voir plus » (jamais des milliers d'un coup). */
export function paginer(cle, liste, rendreUn, o = {}) {
  const pas = o.pas || 24;
  const conteneur = h("div", { classe: "pile" });
  const zone = h(o.balise || "div", { classe: o.classe || "grille" });
  ajouter(conteneur, [zone]);
  const pied = h("div", { classe: "plus" });
  ajouter(conteneur, [pied]);
  let n = 0;
  const montrer = (jusqua) => {
    const fin = Math.min(liste.length, jusqua);
    const frag = document.createDocumentFragment();
    for (let i = n; i < fin; i++) { const el = rendreUn(liste[i], i); if (el) ajouter(frag, [el]); }
    ajouter(zone, [frag]);
    n = fin;
    etat.pages[cle] = n;
    remplacer(pied);
    if (n < liste.length) {
      ajouter(pied, [bouton("Voir " + Math.min(pas, liste.length - n) + " de plus", { icone: "plus", onclick: () => montrer(n + pas) }),
        h("span", { classe: "compte" }, nombre(n) + " sur " + nombre(liste.length))]);
      if (liste.length - n > pas * 2) ajouter(pied, [bouton("Tout voir", { classe: "discret", onclick: () => montrer(liste.length) })]);
    } else if (n > pas) {
      ajouter(pied, [bouton("Replier", { classe: "discret", icone: "haut", onclick: () => { remplacer(zone); n = 0; montrer(pas); conteneur.scrollIntoView({ block: "start", behavior: reduit.matches ? "auto" : "smooth" }); } })]);
    }
  };
  montrer(Math.max(pas, Math.min(etat.pages[cle] || pas, liste.length)));
  return conteneur;
}

export function indexAZ(dispo, actif, choisir) {
  const lettres = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
  return h("div", { classe: "index-az", role: "group", "aria-label": "Index alphabétique" }, lettres.map((l) => h("button", {
    type: "button", disabled: !dispo.has(l) || null, "aria-pressed": String(actif === l), title: dispo.has(l) ? (dispo.get ? quantite(dispo.get(l), "personne(s)") : "") : "Personne",
    onclick: () => choisir(actif === l ? "" : l),
  }, l)));
}

// ─── Bandeaux ──────────────────────────────────────────────────────────────
export function bandeau(texte, genre, ...actions) {
  return h("div", { classe: "bandeau " + (genre || ""), role: genre === "rouge" ? "alert" : "status" },
    icone(genre === "vert" ? "succes" : genre === "rouge" ? "attention" : "info"),
    h("div", { classe: "bandeau-texte" }, texte, actions.length ? h("div", { classe: "rangee" }, actions) : null));
}

// ─── Graphiques à l'encre (SVG construit, aucune bibliothèque) ─────────────
const NS = "http://www.w3.org/2000/svg";
export const ENCRES = { encre: "#2b1d12", cire: "#8e2a24", mer: "#1f4e5a", vert: "#3f6b3a", ambre: "#a8641c", laiton: "#a8823f", prune: "#5e3a4e", ardoise: "#4a5560", sienne: "#7a4b2a", corde: "#b99a6b" };
/** Barres empilées. cles : jours (AAAA-MM-JJ) ou mois (AAAA-MM). series : [[cle, couleur, libellé]]. */
export function barres(cles, valeurs, series, sansDonnees) {
  const zone = h("div", { classe: "graphe" });
  if (!cles.length) { ajouter(zone, [vide("Pas encore de données", sansDonnees)]); return zone; }
  const total = (k) => series.reduce((a, [s]) => a + (((valeurs[k] || {})[s]) || 0), 0);
  const W = 640, H = 220, bas = 26, haut = 22, max = Math.max(1, ...cles.map(total));
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Graphique en barres");
  const ajoute = (tag, a, txt) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); if (txt !== undefined) e.textContent = txt; ajouter(svg, [e]); return e; };
  for (const f of [0, 0.5, 1]) ajoute("line", { x1: 0, x2: W, y1: H - bas - (H - bas - haut) * f, y2: H - bas - (H - bas - haut) * f, stroke: "rgba(43,29,18,.18)", "stroke-dasharray": f ? "3 4" : "0" });
  const pasX = W / cles.length, larg = Math.min(38, pasX * 0.62), etiq = Math.ceil(cles.length / 12);
  cles.forEach((k, i) => {
    let y = H - bas;
    const x = i * pasX + (pasX - larg) / 2;
    for (const [s, coul, lib] of series) {
      const v = ((valeurs[k] || {})[s]) || 0;
      if (!v) continue;
      const hh = (H - bas - haut) * v / max;
      y -= hh;
      const r = ajoute("rect", { x, y, width: larg, height: Math.max(hh - 1.5, 1.5), fill: coul, rx: 1 });
      const t = document.createElementNS(NS, "title");
      t.textContent = (k.length === 7 ? libelleMoisCourt(k) : libelleJour(k)) + " · " + lib + " : " + v;
      ajouter(r, [t]);
    }
    if (i % etiq === 0) ajoute("text", { x: x + larg / 2, y: H - 8, "text-anchor": "middle" }, k.length === 7 ? libelleMoisCourt(k) : k.slice(8) + "/" + k.slice(5, 7));
    const tot = total(k);
    if (tot) ajoute("text", { x: x + larg / 2, y: y - 6, "text-anchor": "middle", class: "total" }, String(tot));
  });
  ajouter(zone, [svg, h("div", { classe: "legende" }, series.map(([, coul, lib]) => h("span", {}, h("i", { vars: { "--teinte": coul } }), lib)))]);
  return zone;
}
/** Barres horizontales : [[libellé, n, titre?, clic?]] */
export function barresH(lignes) {
  const max = Math.max(1, ...lignes.map((l) => l[1]));
  return h("div", {}, lignes.map(([lib, n, titre, clic]) => h(clic ? "button" : "div", {
    classe: "barre-h", type: clic ? "button" : null, onclick: clic || null, title: titre || null,
  }, h("span", { classe: "lib" }, lib), h("span", { classe: "fond" }, h("span", { classe: "plein", vars: { "--pc": Math.round(100 * n / max) + "%" } })), h("b", { classe: "num" }, nombre(n)))));
}
