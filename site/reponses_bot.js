// reponses_bot.js — Le Port › Salons › « Réponses du bot » (28/10/2026).
// Le fondateur : « c'est le bot qui doit leur répondre… c'est pas là pour ça le site. » Plus aucune question à traiter
// ici : le site MONTRE ce que le bot a répondu, retenu (son anti-spam), ce qu'il n'a pas su classer — et la tête règle
// où il répond (partout, par jeu, par salon). Données : GET api/reponses ; réglage : POST api/reponses/reglages.

import { h, remplacer, quantite, sansEmoji, contient } from "./dom.js";
import { peutAgir, etat } from "./noyau.js";
import { lire, poster } from "./api.js";
import { avatar, pastille, vide, tuile, tuiles, puces, interrupteur, groupe, toast, squelettes } from "./ui.js";
import { ligne, groupesParPeriode, quandLigne } from "./rangement.js";

const resetPages = (prefixe) => { for (const k of Object.keys(etat.pages || {})) if (k.startsWith(prefixe)) delete etat.pages[k]; };
const GENRES = { reponse: ["Répondu", "#3f6b3a"], rappel: ["Rappel", "#1f4e5a"], retenue: ["Retenue", "#4a5560"], inconnu: ["Pas su classer", "#a8641c"] };
let memoire = null;   // la dernière lecture : la vue se redessine aussitôt, puis se met à jour

/** La vue : un conteneur rempli dès que le serveur répond (la dernière lecture s'affiche en attendant). */
export function vueReponsesBot(f, maj) {
  const zone = h("div", { classe: "pile" }, memoire ? dessiner(memoire, f, maj) : squelettes(3));
  lire("reponses").then((r) => {
    if (!zone.isConnected && memoire) return;
    if (!r.ok) { remplacer(zone, vide("Réponses du bot indisponibles", r.erreur || "Réessaie dans un instant.", "attention")); return; }
    memoire = r.donnees;
    remplacer(zone, ...dessiner(memoire, f, maj));
  });
  return zone;
}

function dessiner(d, f, maj) {
  const l = d.liste || [], st = d.stats || {}, rg = d.regles || {};
  const filtre = f.rep || "tous", fam = f.dom || "tous", doms = d.domaines || {};
  const nb = { tous: l.length }, nd = { tous: l.length };
  l.forEach((x) => { nb[x.genre] = (nb[x.genre] || 0) + 1; nd[x.domaine || ""] = (nd[x.domaine || ""] || 0) + 1; });
  //  29/10/2026 : trois familles — le jeu, le site, le studio (le Discord, ses FAQ).
  const choisis = l.filter((x) => (filtre === "tous" || x.genre === filtre) && (fam === "tous" || (x.domaine || "") === fam)
    && contient([x.texte, x.salon, x.libelle, (x.membre || {}).nom, (x.membre || {}).pseudo].join(" "), f.q));
  return [
    tuiles(
      tuile({ cle: "rb1", lib: "Répondu · 7 jours", val: st.reponse_7 || 0, icone: "valider", teinte: "#3f6b3a" }),
      tuile({ cle: "rb2", lib: "Rappels · 7 jours", val: st.rappel_7 || 0, icone: "cloche", teinte: "#1f4e5a" }),
      tuile({ cle: "rb3", lib: "Retenues · 7 jours", val: st.retenue_7 || 0, icone: "minuteur", sous: "son anti-spam", teinte: "#4a5560" }),
      tuile({ cle: "rb4", lib: "Pas su classer · 7 jours", val: st.inconnu_7 || 0, icone: "salons", sous: "rien n'est envoyé", teinte: "#a8641c" })),
    puces([["tous", "Tout", nb.tous], ["reponse", "Répondu", nb.reponse || 0, "#3f6b3a"], ["rappel", "Rappels", nb.rappel || 0, "#1f4e5a"],
      ["retenue", "Retenues", nb.retenue || 0, "#4a5560"], ["inconnu", "Pas su classer", nb.inconnu || 0, "#a8641c"]],
    filtre, (v) => { f.rep = v; resetPages("sal"); maj(); }, "Ce que le bot a fait"),
    puces([["tous", "Toutes les familles", nd.tous], ...Object.entries(doms).map(([k, lib]) => [k, lib, nd[k] || 0]),
      ["", "Sans famille", nd[""] || 0]],
    fam, (v) => { f.dom = v; resetPages("sal"); maj(); }, "Famille de la question"),
    reglages(d.reglages || {}),
    h("p", { classe: "aide avance" }, "Le bot oriente une fois (demande d'aide du bon jeu, question fréquente, vrai salon), puis plus rien pendant "
      + (rg.cycle_h || 24) + " h ; un seul rappel s'il redemande au moins " + (rg.rappel_h || 1) + " h après sans avoir créé sa demande. "
      + "Ses réponses s'effacent seules au bout de " + (rg.effacer_min || 30) + " min."),
    h("div", { classe: "groupes-zone" }, choisis.length
      ? groupesParPeriode("sal-rb", choisis, (x) => x.quand, ligneReponse, { forcer: !!f.q, ouverts: 1 })
      : vide("Rien ici", filtre === "tous" ? "Le bot n'a encore rien eu à répondre." : "Change le filtre ou la recherche.", "succes")),
  ];
}

function ligneReponse(x) {
  const [lib, teinte] = GENRES[x.genre] || [x.genre, null];
  const m = x.membre || {};
  return ligne({
    visuel: avatar(m, "p"), titre: x.texte,
    sous: [sansEmoji(m.nom) || m.id || "", " · " + (sansEmoji(x.salon || "").trim() || "#salon"), x.libelle ? " · " + x.libelle : "", x.raison ? " · " + x.raison : ""],
    badges: [pastille(lib, teinte)], ...quandLigne(x.quand),
    actions: [x.message ? { icone: "discord", libelle: "Son message", href: x.message } : null,
      x.reponse ? { icone: "lien", libelle: x.genre === "inconnu" ? "La réponse" : "La réponse du bot", href: x.reponse } : null],
    visibles: 2, deplier: () => h("p", { classe: "texte" }, x.texte),
  });
}

/** Où le bot répond : partout, par jeu, par salon. Lecture pour tous, la tête seule change. */
function reglages(rg) {
  const tete = peutAgir();
  const regler = async (cible, actif, version, i) => {
    i.disabled = true;
    const r = await poster("reponses/reglages", { cible, actif, version });
    i.disabled = false;
    if (r.ok) {
      if (memoire && r.donnees && r.donnees.reglages) memoire.reglages = r.donnees.reglages;
      toast((r.donnees && r.donnees.message) || "Enregistré.", "succes");
    } else {
      i.checked = !actif;
      toast(r.erreur || "Refusé.", "erreur");
    }
  };
  const jeux = rg.jeux || [], salons = rg.salons || [];
  const coupes = jeux.filter((j) => !j.actif).length + salons.filter((s) => !s.actif).length;
  return groupe({ titre: "Où le bot répond", icone: "cle", cle: "rb-reglages",
    info: rg.actif === false ? "coupé partout" : coupes ? quantite(coupes, "endroit(s) coupé(s)") : "partout" }, () => [
    interrupteur("Réponses du bot actives", rg.actif !== false, (v, i) => regler("tout", v, rg.version || 0, i), { disabled: !tete }),
    jeux.length ? h("div", { classe: "pile serree" }, h("h4", {}, "Par jeu"),
      jeux.map((j) => interrupteur(sansEmoji(j.nom), j.actif, (v, i) => regler("jeu:" + j.cle, v, j.version || 0, i), { disabled: !tete }))) : null,
    salons.length ? h("div", { classe: "pile serree" }, h("h4", {}, "Par salon"),
      salons.map((s) => interrupteur(sansEmoji(s.nom), s.actif, (v, i) => regler("salon:" + s.id, v, s.version || 0, i), { disabled: !tete }))) : null,
    tete ? null : h("p", { classe: "aide" }, "Seule la tête change ces réglages."),
  ]);
}
