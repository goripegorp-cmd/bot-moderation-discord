// equipage_equipes.js — les ÉQUIPES du clan (27/10/2026) : chaque équipe, son chef d'équipe MIS EN AVANT (son insigne,
// le métier de l'équipe, son affiche) et ses membres, rangés par la hiérarchie EXISTANTE (le chef, puis l'ordre des
// grades du catalogue, puis le rang de prime). Tri et filtre par type d'équipe et par hiérarchie ; « Mon équipe » sur
// « Ma fiche ». Le site de l'équipage, et la vitrine publique (qui n'y montre que les affiches qu'elle montre déjà).
// Lecture seule : les équipes se composent sur le site de la direction (equipes_admin.js).

import { h, icone, ajouter, remplacer, sansEmoji, srcSure, contient, compte, nombre } from "./dom.js";
import { filtres, libelle } from "./noyau.js";
import { vide, groupe, liste, recherche, avatar } from "./ui.js";
import { affiche, nomAffiche, gradeDe, portrait } from "./affiche.js";
import { E, ouvrirAffiche, afficheParId, catalogue, sceau } from "./equipage_commun.js";

const L = (cle, defaut) => libelle("site.equipes." + cle, defaut);
export const nomChef = () => L("chef", "Chef d'équipe");
export const avecEquipes = () => !!(E.equipage && (E.equipage.equipes || []).length);

const afficheDe = (p) => (p && p.affiche ? afficheParId(p.affiche) : null);
const nomDe = (p) => { const a = afficheDe(p); return a ? nomAffiche(a) : sansEmoji((p && p.nom) || ""); };
const effectif = (e) => e.membres.length + (e.chef ? 1 : 0);

/** L'insigne d'un type d'équipe (l'icône officielle du métier), ou rien. */
function insigneType(t, classe) {
  const src = t && srcSure(t.icone);
  if (!src) return null;
  const img = h("img", { classe, src, alt: "", loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => img.remove(), { once: true });
  return img;
}

/** Une personne d'une équipe : son affiche (mini) ; sans affiche (site de l'équipage), son nom et son portrait. */
function personne(p) {
  const a = afficheDe(p);
  if (a) return h("div", { classe: "affiche-case" }, affiche(a, catalogue(), { taille: "mini", clic: () => ouvrirAffiche(a.id) }));
  if (!p || !p.nom) return null;
  return h("div", { classe: "membre-sans-affiche" }, avatar({ nom: p.nom, avatar: p.avatar }, "g"),
    h("span", { classe: "membre-sans-affiche-nom" }, sansEmoji(p.nom)), h("span", { classe: "membre-sans-affiche-sous" }, "Pas encore d'affiche"));
}

/** Le corps d'une équipe : le chef à part, mis en avant (insigne, titre, métier, affiche), puis ses membres. */
export function corpsEquipe(e, o = {}) {
  const t = e.type;
  const titre = nomChef() + (t && t.genre === "metier" ? " · " + t.nom : "");
  const chef = e.chef ? personne(e.chef) : null;
  return h("div", { classe: "equipe-corps" },
    h("div", { classe: "equipe-chef" + (chef ? "" : " vacant") },
      h("p", { classe: "equipe-chef-titre" }, insigneType(t, "equipe-chef-insigne") || icone("etoile"), h("span", {}, titre)),
      chef || h("p", { classe: "equipe-chef-vide" }, "À nommer par la direction.")),
    h("div", { classe: "equipe-membres" },
      o.sousMain ? h("p", { classe: "equipe-membres-titre" }, icone("membres"), h("span", {}, o.sousMain)) : null,
      e.membres.length ? h("div", { classe: "grille affiches equipe-grille" }, e.membres.map(personne).filter(Boolean))
        : h("p", { classe: "aide" }, "Aucun membre pour le moment.")));
}

/** L'en-tête d'une équipe (dans un groupe repliable) : son type, et combien ils sont. */
function groupeEquipe(e, defaut, cle) {
  const t = e.type;
  return groupe({ titre: sansEmoji(e.nom), visuel: insigneType(t, "groupe-visuel"), icone: t && t.icone ? null : "equipage",
    info: t ? t.nom : null, compte: effectif(e), cle, defaut, classe: "groupe-equipe" }, () => corpsEquipe(e));
}

// ─── Les équipes, triées et filtrées ────────────────────────────────────────
const typeCle = (t) => (t ? t.genre + ":" + (t.cle || t.nom) : "");
function typesPresents(equipes) {
  const vus = new Map();
  for (const e of equipes) if (e.type && !vus.has(typeCle(e.type))) vus.set(typeCle(e.type), e.type);
  return [...vus.entries()].sort((a, b) => (a[1].genre !== b[1].genre ? (a[1].genre === "metier" ? -1 : 1) : a[1].nom.localeCompare(b[1].nom, "fr")));
}

/** La vue « Les équipes ». o : { cle (les filtres gardés pour cette page) }. */
export function rendreEquipes(corps, o = {}) {
  const eq = E.equipage || {};
  const equipes = eq.equipes || [];
  const sans = eq.sans_equipe || [];
  const f = filtres(o.cle || "site-equipes", { q: "", type: "", tri: "equipe" });
  const types = typesPresents(equipes);
  if (f.type && !types.some(([k]) => k === f.type)) f.type = "";
  const resultats = h("div", { classe: "pile" });
  const resume = h("p", { classe: "aide" });
  const changer = () => maj();
  ajouter(corps, [h("p", { classe: "equipes-phrase" }, L("phrase", "Chaque équipe, son chef d'équipe et les matelots qu'il a sous sa main.")),
    h("div", { classe: "outils" },
      recherche(f.q, "Équipe, chef ou membre…", (q) => { f.q = q; changer(); }),
      types.length > 1 ? liste({ valeur: f.type, label: "Type d'équipe", changer: (v) => { f.type = v; changer(); },
        options: [{ v: "", l: "Tous les types" }, ...types.map(([k, t]) => ({ v: k, l: t.nom, img: srcSure(t.icone) || null }))] }) : null,
      liste({ valeur: f.tri, label: "Trier", changer: (v) => { f.tri = v; changer(); },
        options: [{ v: "equipe", l: "Par équipe" }, { v: "type", l: "Par type d'équipe" }, { v: "hierarchie", l: "Par hiérarchie" }] })),
    resume, resultats]);
  const texteEquipe = (e) => [e.nom, e.type && e.type.nom, nomDe(e.chef), ...e.membres.map(nomDe)].join(" ");
  function maj() {
    const l = equipes.filter((e) => (!f.type || typeCle(e.type) === f.type) && contient(texteEquipe(e), f.q));
    const sansL = f.type ? [] : sans.filter((p) => contient(nomDe(p), f.q));
    const gens = l.reduce((n, e) => n + effectif(e), 0);
    remplacer(resume, compte(l.length, "équipe") + " · " + compte(gens, "membre") + (sansL.length ? " · " + nombre(sansL.length) + " " + L("sans", "Sans équipe").toLowerCase() : "") + ".");
    if (!l.length && !sansL.length) { remplacer(resultats, vide("Personne ici", "Change le filtre ou la recherche.", "rechercher")); return; }
    if (f.tri === "hierarchie") { remplacer(resultats, hierarchie(l, sansL)); return; }
    //  Rien à défiler sans fin : le premier groupe ouvert, et les suivants tant qu'au plus douze personnes y sont.
    //  Contigus : le premier, puis les suivants tant qu'ils tiennent ; le premier qui ne tient pas ferme tous les autres.
    let ouvertes = 0, encore = true;
    const ouvrir = (n, i) => { const oui = !!f.q || i === 0 || (encore && ouvertes + n <= 12); if (!oui) encore = false; else ouvertes += n; return oui; };
    const blocs = [];
    if (f.tri === "type") {
      const parType = new Map();
      for (const e of l) { const k = typeCle(e.type) || "__aucun"; if (!parType.has(k)) parType.set(k, []); parType.get(k).push(e); }
      const ordre = [...types.map(([k]) => k), "__aucun"];
      let i = 0;
      for (const k of ordre.filter((x) => parType.has(x))) {
        const t = k === "__aucun" ? null : types.find(([x]) => x === k)[1];
        blocs.push(h("h3", { classe: "equipes-type" }, insigneType(t, "equipes-type-insigne") || icone("drapeau"), h("span", {}, t ? t.nom : "Sans type")));
        for (const e of parType.get(k)) blocs.push(groupeEquipe(e, ouvrir(effectif(e), i++), "eq-team-" + e.id));
      }
    } else l.forEach((e, i) => blocs.push(groupeEquipe(e, ouvrir(effectif(e), i), "eq-team-" + e.id)));
    if (sansL.length) blocs.push(groupe({ titre: L("sans", "Sans équipe"), icone: "membres", compte: sansL.length, cle: "eq-team-sans", defaut: false },
      () => h("div", { classe: "grille affiches equipe-grille" }, sansL.map(personne).filter(Boolean))));
    remplacer(resultats, ...blocs);
  }
  maj();
}

/** « Par hiérarchie » : tout l'équipage en un rang — les chefs d'abord (l'ordre des équipes), puis chacun par la
 *  hiérarchie existante (le grade, puis la prime) ; son équipe à côté. */
function hierarchie(equipes, sans) {
  const cat = catalogue();
  const rangs = [];
  equipes.forEach((e) => { if (e.chef) rangs.push({ p: e.chef, e, chef: true }); });
  const autres = [];
  equipes.forEach((e) => e.membres.forEach((p) => autres.push({ p, e, chef: false })));
  sans.forEach((p) => autres.push({ p, e: null, chef: false }));
  autres.sort((x, y) => (x.p.h || 0) - (y.p.h || 0));
  rangs.push(...autres);
  return h("ol", { classe: "hierarchie" }, rangs.map((x, i) => {
    const a = afficheDe(x.p);
    const src = a ? srcSure(portrait(a)) : "";
    const visuel = src ? h("img", { classe: "avatar p", src, alt: "", loading: "lazy", decoding: "async" }) : avatar({ nom: nomDe(x.p), avatar: x.p.avatar }, "p");
    const grade = a ? gradeDe(a, cat) : "";
    const contenu = [h("span", { classe: "hierarchie-rang num" }, String(i + 1)), visuel,
      h("span", { classe: "hierarchie-texte" }, h("b", {}, nomDe(x.p)),
        h("span", { classe: "hierarchie-sous" }, [x.chef ? nomChef() + (x.e.type && x.e.type.genre === "metier" ? " · " + x.e.type.nom : "") : grade,
          x.e ? sansEmoji(x.e.nom) : L("sans", "Sans équipe")].filter(Boolean).join(" · "))),
      x.chef ? h("span", { classe: "hierarchie-chef", title: nomChef() }, insigneType(x.e.type, "hierarchie-insigne") || icone("etoile")) : null];
    return h("li", { classe: "hierarchie-ligne" + (x.chef ? " chef" : "") },
      a ? h("button", { classe: "hierarchie-bouton", type: "button", onclick: () => ouvrirAffiche(a.id), "aria-label": "Affiche de " + nomDe(x.p) }, contenu)
        : h("div", { classe: "hierarchie-bouton" }, contenu));
  }));
}

// ─── « Mon équipe » (Ma fiche) ──────────────────────────────────────────────
/** Mon équipe : le chef y lit les membres qu'il a sous sa main ; un membre, son chef et ses équipiers. */
export function sectionMonEquipe() {
  const eq = E.equipage || {};
  const mon = eq.mon_equipe;
  const e = mon ? (eq.equipes || []).find((x) => x.id === mon.id) : null;
  const titre = L("mon", "Mon équipe");
  if (!e) return h("section", { classe: "mon-equipe vide", "aria-label": titre },
    h("div", { classe: "section-tete tete-bloc" }, h("h2", {}, sceau("equipage"), h("span", { classe: "titre-texte" }, titre))),
    h("p", { classe: "aide" }, L("aucune", "Pas encore d'équipe : la direction forme les équipes.")));
  const chef = mon.role === "chef";
  return h("section", { classe: "mon-equipe" + (chef ? " je-suis-chef" : ""), "aria-label": titre },
    h("div", { classe: "section-tete tete-bloc" }, h("h2", {}, sceau("equipage"), h("span", { classe: "titre-texte" }, titre + " · " + sansEmoji(e.nom))),
      e.type ? h("span", { classe: "compte" }, e.type.nom) : null),
    corpsEquipe(e, { sousMain: chef ? L("sous_main", "Sous ta main") + " · " + compte(e.membres.length, "matelot") : null }));
}

