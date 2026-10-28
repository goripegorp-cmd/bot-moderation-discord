// hierarchie.js — la HIÉRARCHIE de l'équipage, dessinée comme un organigramme (27/10/2026) : le Capitaine en tête, le
// Second marqué « bras droit » juste dessous, puis chaque rang — son insigne sur la cire de sa couleur, son nom, sa
// phrase, ses membres — et le dernier rang (le rang d'arrivée, le plus nombreux) en nombre, sa liste repliable.
// Trois pages s'en servent : le site de l'équipage et la vitrine publique (lecture seule, `rendreHierarchie`) et la vue
// de la direction (hierarchie_admin.js : `organigramme` avec ses boutons). Aucune donnée écrite en HTML (dom.js).

import { h, icone, remplacer, ajouter, sansEmoji, srcSure, nombre, contient, compte } from "./dom.js";
import { libelle } from "./noyau.js";
import { groupe, paginer, avatar, vide, recherche } from "./ui.js";
import { nomAffiche, portrait } from "./affiche.js";
import { E, afficheParId, ouvrirAffiche } from "./equipage_commun.js";

/** Un texte de la hiérarchie (registre `textes.py`, famille « Le site de l'équipage ») : le nom choisi, sinon l'origine. */
export const L = (cle, defaut) => libelle("site.hierarchie." + cle, defaut);
export const titreHierarchie = () => L("titre", "La hiérarchie");
const teinte = (r) => (r && /^#[0-9a-fA-F]{6}$/.test(r.couleur || "") ? r.couleur : "#7a5a22");

/** Le sceau d'un rang : son insigne sur la cire de sa couleur. */
export function sceauRang(r, taille) {
  return h("span", { classe: "rang-sceau" + (taille ? " " + taille : ""), vars: { "--teinte": teinte(r) }, "aria-hidden": "true" },
    icone((r && r.insigne) || "etoile"));
}
/** La pastille d'un rang (son insigne, son nom, sa couleur) : partout où un membre est montré. */
export function pastilleRang(r, titre) {
  if (!r || !r.nom) return null;
  return h("span", { classe: "rang-pastille", vars: { "--teinte": teinte(r) }, title: titre || null }, icone(r.insigne || "etoile"),
    h("span", {}, sansEmoji(r.nom)));
}

/** Une personne d'un rang : son portrait (ou ses initiales) et son nom ; un bouton si elle s'ouvre. */
function carte(p, grande) {
  const src = srcSure(p.src);
  const visage = src ? h("img", { classe: "org-portrait", src, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" })
    : avatar({ nom: p.nom }, grande ? "g" : "p");
  if (src) visage.addEventListener("error", () => visage.replaceWith(avatar({ nom: p.nom }, grande ? "g" : "p")), { once: true });
  const contenu = [visage, h("span", { classe: "org-nom" }, sansEmoji(p.nom) || "Matelot"), p.sous ? h("span", { classe: "org-sous" }, p.sous) : null];
  return p.clic ? h("button", { classe: "org-membre" + (grande ? " grande" : ""), type: "button", onclick: p.clic, "aria-label": p.aria || null }, contenu)
    : h("div", { classe: "org-membre" + (grande ? " grande" : "") }, contenu);
}

/** L'organigramme. rangs : [{ id, nom, insigne, couleur, phrase, verrou, n, membres }] dans l'ordre.
 *  o.personne(m, r) → { nom, src, clic?, sous?, aria? } ou null ; o.outils(r, i) → nœuds (la direction) ;
 *  o.filtre(personne) → bool (une recherche) ; o.cle : les groupes repliables gardés pour cette page. */
export function organigramme(rangs, o = {}) {
  const gens = (r) => (r.membres || []).map((m) => o.personne(m, r)).filter(Boolean).filter((p) => !o.filtre || o.filtre(p));
  const tete = rangs.filter((r) => r.verrou === "capitaine" || r.verrou === "second");
  const autres = rangs.filter((r) => !tete.includes(r));
  const n = (r) => Number(r.n) || 0;
  const sansAffiche = (r, montres) => (n(r) > montres ? h("p", { classe: "org-note" }, compte(n(r) - montres, "membre") + " sans affiche montrée ici.") : null);
  const outils = (r, i) => (o.outils ? h("div", { classe: "org-outils" }, o.outils(r, i)) : null);
  const titre = (r, i, niveau) => h("div", { classe: "org-tete-rang" }, sceauRang(r, niveau === "haut" ? "grand" : ""),
    h("div", { classe: "org-titre" }, h("h3", {}, sansEmoji(r.nom)), r.phrase ? h("p", { classe: "org-phrase" }, sansEmoji(r.phrase)) : null),
    h("span", { classe: "org-compte", title: compte(n(r), "membre") }, nombre(n(r))), outils(r, i));
  const cartesHaut = tete.map((r) => {
    const l = gens(r);
    const i = rangs.indexOf(r);
    return h("section", { classe: "org-haut " + r.verrou, vars: { "--teinte": teinte(r) }, "aria-label": sansEmoji(r.nom) },
      r.verrou === "second" ? h("span", { classe: "org-ruban" }, L("bras_droit", "Bras droit du capitaine")) : null,
      titre(r, i, "haut"),
      l.length ? h("div", { classe: "org-gens haut" }, l.map((p) => carte(p, true))) : h("p", { classe: "org-vacant" }, L("vacant", "À nommer")),
      sansAffiche(r, l.length));
  });
  const paliers = autres.map((r) => {
    const l = gens(r);
    const i = rangs.indexOf(r);
    const dernier = r.verrou === "defaut";
    const corps = !l.length ? h("p", { classe: "org-vacant" }, n(r) && o.filtre ? "Personne pour cette recherche." : L("vacant", "À nommer"))
      : dernier ? groupe({ titre: L("liste", "Voir la liste"), compte: l.length, cle: (o.cle || "org") + "-dernier", ouvert: o.filtre ? true : undefined,
        classe: "org-liste" }, () => paginer((o.cle || "org") + "-dernier", l, (p) => carte(p), { classe: "org-gens", pas: 24 }))
        : h("div", { classe: "org-gens" }, l.map((p) => carte(p)));
    return h("section", { classe: "org-palier" + (dernier ? " dernier" : ""), vars: { "--teinte": teinte(r) }, "aria-label": sansEmoji(r.nom) },
      titre(r, i), corps, sansAffiche(r, (r.membres || []).filter((m) => o.personne(m, r)).length));
  });
  return h("div", { classe: "organigramme" }, h("div", { classe: "org-haut-zone" }, cartesHaut), h("div", { classe: "org-paliers" }, paliers));
}

// ─── Le site de l'équipage et la vitrine (lecture seule) ───────────────────
/** Une personne de la hiérarchie lue par la page : son affiche (portrait Roblox, nom de l'affiche) s'il en a une, sinon
 *  (le site de l'équipage seulement) son nom et son portrait Discord. Rien sans affiche sur la vitrine. */
function personneLue(m) {
  const a = m.affiche ? afficheParId(m.affiche) : null;
  if (a) return { nom: nomAffiche(a), src: portrait(a), clic: () => ouvrirAffiche(a.id), aria: "Affiche de " + nomAffiche(a) };
  if (!m.nom) return null;
  return { nom: m.nom, src: m.avatar || "", sous: "Pas encore d'affiche" };
}

/** La vue « La hiérarchie » d'une page en lecture seule (`E.equipage.hierarchie`). */
export function rendreHierarchie(corps, o = {}) {
  const hi = E.equipage && E.equipage.hierarchie;
  if (!hi || !(hi.rangs || []).length) { remplacer(corps, vide("La hiérarchie arrive bientôt", "La direction range l'équipage par rang.", "grade")); return; }
  let q = "";
  const zone = h("div", { classe: "pile" });
  const dessiner = () => remplacer(zone, organigramme(hi.rangs, { personne: personneLue, cle: o.cle || "eq-hie",
    filtre: q ? (p) => contient(p.nom, q) : null }));
  ajouter(corps, [h("p", { classe: "equipes-phrase" }, L("phrase", "Du capitaine au dernier moussaillon : le rang de chacun à bord.")),
    h("div", { classe: "outils" }, recherche("", "Chercher un pirate…", (v) => { q = v; dessiner(); }, { nom: "chercher-rang" })), zone]);
  dessiner();
}

/** Le rang d'identifiant `id` (site de l'équipage) — ou null. */
export function rangLu(id) {
  const hi = E.equipage && E.equipage.hierarchie;
  return (id && hi && (hi.rangs || []).find((r) => r.id === id)) || null;
}
