// vitrine.js — la VITRINE PUBLIQUE de l'équipage (`/equipage`) : « l'affiche même de ce à quoi notre équipage
// ressemble », le lien officiel à partager. Sans session, en lecture seule : le bandeau et les blocs que la direction a
// rendus publics (le même rendu que le site de l'équipage), puis le mur des affiches rangé par métier.
// Les données viennent de `/equipage/donnees` : des champs publics seulement, les images par jetons opaques. Aucune
// écriture, aucun cookie : rien d'autre du site n'est appelé.

import { h, $, BASE, chargerSprite, completerSprite, remplacer, ajouter, sansEmoji } from "./dom.js";
import { poserLibelles, filtres, libelle } from "./noyau.js";
import { vide, segment } from "./ui.js";
import { E, T, sceau } from "./equipage_commun.js";
import * as accueil from "./equipage_accueil.js";
import { rendreMur } from "./equipage_mur.js";
import { rendreEquipes, avecEquipes } from "./equipage_equipes.js";
import { rendreHierarchie, titreHierarchie } from "./hierarchie.js";
import { boutonLienEquipage } from "./lien_equipage.js";

/** La version des fichiers : celle de la balise <script> de cette page (s/vitrine.js?v=…), posée par le serveur. */
const V = (() => {
  try {
    const s = document.querySelector('script[type="module"][src*="/s/vitrine.js"]');
    return (s && new URL(s.src).searchParams.get("v")) || "dev";
  } catch (e) { return "dev"; }
})();
const ICONES = ["navire", "affiches", "lien", "copier", "fermer", "rechercher", "filtrer", "journal", "calendrier", "etoile", "apercu",
  "parchemin", "image", "info", "attention", "succes", "minuteur", "lieu", "membres", "prime", "berry", "grade", "drapeau", "carte",
  "boussole", "ancre", "crane", "droite", "annonces", "evenements", "equipage", "longue_vue", "plume", "epingle"];

async function demarrer() {
  await Promise.race([chargerSprite(BASE + "/s/icones/ui.svg?v=" + V), new Promise((ok) => setTimeout(ok, 2500))]);
  completerSprite(ICONES);
  const d = await lireDonnees();
  document.body.classList.remove("demarrage");
  if (!d) {
    remplacer($("#contenu"), vide("La vitrine ne répond pas", "Recharge la page dans un instant.", "attention"));
    return;
  }
  E.textes = d.textes || {};
  poserLibelles(d.libelles || {});   // les noms d'affiche et le bouton « Copier le lien » renommés par la direction
  E.peutEditer = false;
  E.modeEdition = false;
  E.equipage = { affiches: d.affiches || [], catalogue: d.catalogue || { types: [], elements: [] }, moi: null,
    equipes: d.equipes || [], sans_equipe: [], hierarchie: d.hierarchie || null };
  E.accueil = d.accueil || { blocs: [], donnees: {} };
  monterEntete(d);
  rendre();
  pied();
}

/** `/equipage/donnees` (sans cookie) → les données publiques, ou null. */
async function lireDonnees() {
  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), 15000);
  try {
    const r = await fetch("/equipage/donnees", { credentials: "omit", cache: "no-cache", signal: ctrl.signal });
    return r.ok ? await r.json() : null;
  } catch (e) {
    return null;
  } finally {
    clearTimeout(minuteur);
  }
}

// ─── L'en-tête : le médaillon, le nom, le lien à copier ─────────────────────
function monterEntete(d) {
  const serveur = sansEmoji(d.serveur && d.serveur.nom);
  $("#nom-serveur").textContent = T("titre", "L'Équipage");
  $("#sous-titre").textContent = [d.clan ? "Clan " + d.clan : "", serveur].filter(Boolean).join(" · ");
  remplacer($("#logo-serveur"), (serveur || T("titre", "L'Équipage")).slice(0, 1));
  remplacer($("#entete-outils"), lienWiki(), boutonLienEquipage());
}

//  29/10/2026 : le wiki public de RELL Seas, le grimoire du clan (`/wiki`).
function lienWiki() {
  return h("a", { classe: "bouton", href: "/wiki", title: "Wiki RELL Seas" }, "Wiki", h("span", { classe: "vt-suite" }, " RELL Seas"));
}

// ─── La page : les blocs publics, puis le mur ───────────────────────────────
function rendre() {
  const blocs = E.accueil.blocs || [];
  const zoneBlocs = h("div", { classe: "vitrine-accueil" });
  const mur = h("div", { classe: "rubrique-corps" });
  //  Un bandeau en tête EST le titre de la page (son h1) ; sinon, le nom du site.
  const titre = blocs.length && blocs[0].type === "bandeau" ? null : h("h1", { classe: "vitrine-titre" }, T("titre", "L'Équipage"));
  remplacer($("#contenu"), titre, blocs.length ? zoneBlocs : null,
    h("section", { classe: "vitrine-mur", "aria-labelledby": "vitrine-mur-titre" },
      h("div", { classe: "section-tete tete-bloc" },
        h("h2", { id: "vitrine-mur-titre" }, sceau("affiches"), h("span", { classe: "titre-texte" }, T("onglet.equipage", "L'équipage")))),
      mur));
  try {
    if (blocs.length) accueil.rendre(zoneBlocs, null);
  } catch (e) {
    console.error("[vitrine] blocs", e);
    remplacer(zoneBlocs, vide("Cette partie n'a pas pu s'afficher", "Recharge la page dans un instant.", "attention"));
  }
  //  La phrase du mur accompagne la vue des affiches (les équipes ont la leur).
  const murSeul = (zone) => {
    ajouter(zone, [h("p", { classe: "vitrine-phrase" }, T("vitrine.phrase", "Les avis de recherche de tout l'équipage, rangés par métier."))]);
    rendreMur(zone, { cle: "vitrine-equipage", vide: [T("vitrine.vide", "Les avis de recherche arrivent bientôt."), ""] });
  };
  //  Les équipes du clan, leurs chefs mis en avant (par les seules affiches de la vitrine), la hiérarchie (27/10/2026 :
  //  les rangs, par les affiches montrées) — ou toutes les affiches.
  const vues = [avecEquipes() ? ["equipes", libelle("site.equipes.titre", "Les équipes")] : null,
    E.equipage.hierarchie ? ["hierarchie", titreHierarchie()] : null, ["affiches", "Toutes les affiches"]].filter(Boolean);
  if (vues.length === 1) { murSeul(mur); return; }
  const f = filtres("vitrine-vue", { vue: vues[0][0] });
  if (!vues.some(([k]) => k === f.vue)) f.vue = vues[0][0];
  const zone = h("div", { classe: "pile" });
  const dessiner = () => {
    remplacer(zone);
    if (f.vue === "affiches") murSeul(zone);
    else if (f.vue === "hierarchie") rendreHierarchie(zone, { cle: "vitrine-hierarchie" });
    else rendreEquipes(zone, { cle: "vitrine-equipes" });
  };
  remplacer(mur, segment(f.vue, vues, (v) => { f.vue = v; dessiner(); }, "Afficher"), zone);
  dessiner();
}

function pied() {
  remplacer($("#pied"), h("div", { classe: "pied-vitrine" },
    h("p", { classe: "pied-vitrine-texte" }, T("vitrine.pied", "La vitrine de l'équipage : ce que la direction choisit de montrer.")),
    h("div", { classe: "pied-vitrine-liens" }, lienWiki(), boutonLienEquipage()),
    h("p", { classe: "aide" }, T("vitrine.membre", "Membre du clan ? Ton accès personnel : le guide du clan sur Discord."))));
}

demarrer();
