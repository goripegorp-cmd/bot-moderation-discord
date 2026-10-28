// equipage_mur.js — le MUR des affiches, rangé par métier : recherche, filtres (métier, race, faction), groupes
// repliables (le premier ouvert, les suivants tant que le mur ouvert garde au plus douze affiches), « Voir plus ».
// Deux pages s'en servent : le site de l'équipage (onglet « L'équipage ») et la vitrine publique (`/equipage`).
// Lecture seule ; la direction (mode édition du site de l'équipage) voit en plus les affiches retirées de la vitrine.

import { h, ajouter, remplacer, sansEmoji, srcSure, contient, nombre, compte } from "./dom.js";
import { etat, filtres } from "./noyau.js";
import { vide, groupe, paginer, recherche, liste } from "./ui.js";
import { affiche, nomAffiche, metiersDe, gradeDe, insigneImage } from "./affiche.js";
import { typeMetier, typesTries, elementsDe, element } from "./donnees.js";
import { E, ouvrirAffiche, catalogue } from "./equipage_commun.js";
import { texteAncien } from "./lien_equipage.js";

/** Le mur dans `corps`. o : { cle (les filtres gardés pour cette page), vide: [titre, phrase] (aucune affiche) }. */
export function rendreMur(corps, o = {}) {
  const eq = E.equipage;
  if (!eq) { remplacer(corps, vide("Les affiches ne se sont pas chargées", "Recharge la page dans un instant.", "attention")); return; }
  const cat = catalogue();
  const f = filtres(o.cle || "site-equipage", { q: "", metier: "", race: "", faction: "" });
  const tm = typeMetier(cat);
  const parCle = (cle, motif) => typesTries(cat).find((t) => t.cle === cle) || typesTries(cat).find((t) => motif.test(t.nom || "")) || null;
  const tr = parCle("race", /\braces?\b/i), tf = parCle("faction", /\bfactions?\b/i);
  const toutes = eq.affiches || [];
  const masquees = new Set((E.peutEditer && eq.vitrine && eq.vitrine.masquees) || []);
  const anciennes = new Set((E.peutEditer && eq.vitrine && eq.vitrine.anciennes) || []);   // plus au clan : hors vitrine
  const de = (a, t) => (t ? (a.attributs && a.attributs[t.cle]) || [] : []);
  const options = (t, tous) => {
    if (!t) return null;
    const n = new Map();
    for (const a of toutes) for (const k of de(a, t)) n.set(k, (n.get(k) || 0) + 1);
    return [{ v: "", l: tous }, ...elementsDe(cat, t.cle).filter((e) => n.has(e.cle)).map((e) => ({ v: e.cle, l: e.nom + " (" + n.get(e.cle) + ")", img: srcSure(e.icone) || null }))];
  };
  const resultats = h("div", { classe: "pile" });
  const resume = h("p", { classe: "aide" });
  const changer = () => { for (const k of Object.keys(etat.pages)) if (k.startsWith("eq-")) delete etat.pages[k]; maj(); };
  const filtresListes = [[tm, "metier", "Métier", "Tous les métiers"], [tr, "race", "Race", "Toutes les races"], [tf, "faction", "Faction", "Toutes les factions"]]
    .map(([t, k, lib, tous]) => {
      const opts = options(t, tous);
      if (!opts || opts.length < 2) { f[k] = ""; return null; }
      if (f[k] && !opts.some((x) => x.v === f[k])) f[k] = "";
      return liste({ valeur: f[k], options: opts, label: lib, changer: (v) => { f[k] = v; changer(); } });
    });
  ajouter(corps, [h("div", { classe: "outils" }, recherche(f.q, "Nom, surnom, métier…", (q) => { f.q = q; changer(); }), ...filtresListes), resume, resultats]);
  const texte = (a) => [nomAffiche(a), a.surnom, a.membre && a.membre.nom, gradeDe(a, cat), ...Object.entries(a.attributs || {}).flatMap(([t, ks]) => ks.map((k) => (element(cat, t, k) || {}).nom || k))].join(" ");
  const carte = (a) => {
    const mienne = !!eq.moi && String(a.id) === String(eq.moi);
    const ancienne = anciennes.has(String(a.id));
    const hors = ancienne || masquees.has(String(a.id));
    return h("div", { classe: "affiche-case" + (mienne ? " la-mienne" : "") + (hors ? " hors-vitrine" : "") },
      affiche(a, cat, { taille: "mini", clic: () => ouvrirAffiche(a.id) }),
      mienne ? h("span", { classe: "ruban-mienne" }, "Ma fiche") : null,
      hors ? h("span", { classe: "ruban-hors-vitrine", title: ancienne ? "Plus au clan : elle revient sur la vitrine s'il revient au clan." : "Retirée de la vitrine publique : seul l'équipage la voit." },
        ancienne ? texteAncien() : "Hors vitrine") : null);
  };
  function maj() {
    const l = toutes.filter((a) => contient(texte(a), f.q) && (!f.metier || de(a, tm).includes(f.metier))
      && (!f.race || de(a, tr).includes(f.race)) && (!f.faction || de(a, tf).includes(f.faction)));
    remplacer(resume, l.length === toutes.length ? compte(toutes.length, "affiche") + " au mur. Touche une affiche pour la voir en grand."
      : compte(l.length, "affiche") + " sur " + nombre(toutes.length) + " pour ce filtre.");
    if (!toutes.length) {
      const [titre, phrase] = o.vide || ["Aucune affiche pour le moment", "La direction prépare les avis de recherche de l'équipage."];
      remplacer(resultats, vide(titre, phrase, "affiches"));
      return;
    }
    if (!l.length) { remplacer(resultats, vide("Personne ici", "Change le filtre ou la recherche.", "rechercher")); return; }
    const groupes = new Map();
    for (const a of l) for (const k of (metiersDe(a, cat).length ? metiersDe(a, cat) : ["__aucun"])) {
      if (f.metier && k !== f.metier && k !== "__aucun") continue;
      if (!groupes.has(k)) groupes.set(k, []);
      groupes.get(k).push(a);
    }
    const ordre = tm ? elementsDe(cat, tm.cle).map((e) => e.cle) : [];
    const cles = [...groupes.keys()].sort((a, b) => (a === "__aucun") - (b === "__aucun") || ((ordre.indexOf(a) + 1 || 999) - (ordre.indexOf(b) + 1 || 999)) || a.localeCompare(b));
    //  Rien à défiler sans fin : au départ, le premier métier ouvert, et les suivants tant que le mur ouvert garde au plus
    //  trente affiches (28/10/2026, le fondateur : des métiers repliés « cachés » sur la vitrine) ; au téléphone (deux par
    //  rangée), « Voir plus » par 8.
    const pas = matchMedia("(max-width: 519px)").matches ? 8 : 18;
    let ouvertes = 0, encore = true;   // contigus : le premier groupe qui ne tient pas ferme les suivants
    remplacer(resultats, ...cles.map((k, i) => {
      const e = tm && k !== "__aucun" ? element(cat, tm.cle, k) : null;
      const n = groupes.get(k).length;
      const defaut = i === 0 || (encore && ouvertes + n <= 30);
      if (defaut) ouvertes += n; else encore = false;
      return groupe({ titre: k === "__aucun" ? "Sans métier" : e ? e.nom : sansEmoji(k), compte: n,
        visuel: e ? insigneImage(e, "groupe-visuel") : null, icone: e ? null : "drapeau", cle: "eq-g-" + k,
        ouvert: f.q || f.metier ? true : undefined, defaut },
      () => paginer("eq-" + k, groupes.get(k), carte, { classe: "grille affiches", pas }));
    }));
  }
  maj();
}
