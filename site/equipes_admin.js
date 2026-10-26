// equipes_admin.js — les ÉQUIPES du clan, côté direction (27/10/2026). Dans « L'Équipage › Équipage » : les membres
// rangés par équipe (le chef d'abord, mis en avant), et l'éditeur d'une équipe en panneau — nom, type (un métier du
// catalogue, ou un libellé), chef (n'importe quel membre du clan ; les badges du fournisseur d'abord : les chefs validés
// du recrutement), membres (un membre n'est que dans UNE équipe : l'ajouter ici le retire de l'autre).
// Écrit par la tête seule (`equipage/equipe…`, journal du site), protégé par les verrous de la présence en direct
// (`equipe:<id>`). La fiche d'un membre porte sa ligne « Équipe : … (chef : …) » (`ligneEquipe`).

import { h, icone, ajouter, remplacer, sansEmoji, srcSure, contient, quantite } from "./dom.js";
import { etat, libelle, peutAgir } from "./noyau.js";
import { lire, poster } from "./api.js";
import { bouton, boutonIcone, pancarte, confirmer, toast, vide, liste, recherche, pastille, tampon, champ, saisie, nomDe, avatar } from "./ui.js";
import { groupes, lignes } from "./rangement.js";
import { protegerEditeur, avecVerrou, siLibre } from "./direct.js";

const L = (cle, defaut) => libelle("site.equipes." + cle, defaut);
const nomChef = () => L("chef", "Chef d'équipe");
let cache = null, cacheT = 0, enCours = null;

/** Les équipes (`GET equipage/equipes` : équipes, métiers, badges du sélecteur), gardées 20 s ; `forcer` : relues. */
export async function lireEquipes(forcer) {
  if (!forcer && cache && Date.now() - cacheT < 20000) return cache;
  if (!enCours) {
    enCours = lire("equipage/equipes").then((r) => {
      if (r.ok && r.donnees) { cache = r.donnees; cacheT = Date.now(); }
      return r.ok ? cache : null;
    }).finally(() => { enCours = null; });
  }
  return enCours;
}
function accepter(d) {
  if (d && Array.isArray(d.equipes)) { cache = { equipes: d.equipes, badges: d.badges || {}, metiers: d.metiers || [] }; cacheT = Date.now(); }
}

/** L'insigne d'un type d'équipe (l'icône du métier), ou rien. */
function insigne(t, classe) {
  const src = t && srcSure(t.icone);
  if (!src) return null;
  const img = h("img", { classe, src, alt: "", loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => img.remove(), { once: true });
  return img;
}

// ─── « Par équipe » (L'Équipage › Équipage) ─────────────────────────────────
/** Les membres (déjà filtrés par la recherche et la présence), rangés par équipe : le chef d'abord, tamponné, puis les
 *  membres ; « Sans équipe » à la fin. `rendreLigne(m, badge)` : la ligne d'un membre (clan.js). */
export async function vueParEquipe(zone, membres, rendreLigne, surChange, filtre) {
  const d = await lireEquipes();
  if (!zone.isConnected) return;
  if (!d) { remplacer(zone, vide("Équipes indisponibles", "Réessaie dans un instant.", "hors_ligne")); return; }
  const parId = new Map(membres.map((m) => [String(m.id), m]));
  const places = new Set();
  const n = d.equipes.length;
  const defs = d.equipes.map((e, i) => {
    [e.chef, ...e.membres].forEach((p) => { if (p) places.add(String(p.id)); });
    const chef = e.chef ? parId.get(String(e.chef.id)) : null;
    const gens = e.membres.map((p) => parId.get(String(p.id))).filter(Boolean);
    if (filtre && !chef && !gens.length) return null;   // une recherche : seulement les équipes où elle trouve quelqu'un
    return {
      titre: sansEmoji(e.nom), info: e.type ? e.type.nom : "Sans type", visuel: insigne(e.type, "groupe-visuel"), icone: e.type && e.type.icone ? null : "equipage",
      compte: gens.length + (chef ? 1 : 0), cle: "clan-eq-" + e.id,
      contenu: () => avecVerrou(h("div", { classe: "pile serree" },
        peutAgir() ? h("div", { classe: "rangee" },
          bouton("Modifier l'équipe", { classe: "p", icone: "modifier", onclick: () => editerEquipe(e, surChange) }),
          inactif(boutonIcone("haut", "Monter cette équipe", () => deplacer(e, "haut", surChange)), i === 0),
          inactif(boutonIcone("bas", "Descendre cette équipe", () => deplacer(e, "bas", surChange)), i === n - 1)) : null,
        chef ? h("ul", { classe: "lignes-c" }, rendreLigne(chef, tampon(nomChef(), "ambre", true)))
          : h("p", { classe: "aide" }, e.chef ? nomChef() + " : " + sansEmoji(e.chef.nom) + " (hors du filtre)." : "Aucun chef nommé."),
        gens.length ? lignes("clan-eq-" + e.id, gens, (m) => rendreLigne(m)) : h("p", { classe: "aide" }, "Aucun membre ici.")), "equipe:" + e.id),
    };
  }).filter(Boolean);
  const sans = membres.filter((m) => !places.has(String(m.id)));
  if (sans.length) defs.push({ titre: L("sans", "Sans équipe"), icone: "membres", compte: sans.length, cle: "clan-eq-sans",
    contenu: () => lignes("clan-eq-sans", sans, (m) => rendreLigne(m)) });
  remplacer(zone,
    h("div", { classe: "rangee entre" }, h("p", { classe: "aide" }, quantite(d.equipes.length, "équipe(s)") + " · chacune avec son chef d'équipe. Un membre n'est que dans une équipe."),
      peutAgir() ? bouton("Nouvelle équipe", { classe: "p", icone: "ajouter", onclick: () => editerEquipe(null, surChange) }) : null),
    defs.length ? h("div", { classe: "groupes-zone" }, groupes(defs, { ouverts: 2, forcer: !!filtre })) : vide("Personne ici", "Change le filtre ou la recherche."));
}
const inactif = (b, oui) => { b.disabled = !!oui; return b; };

async function deplacer(e, sens, surChange) {
  if (!siLibre("equipe:" + e.id)) return;
  const r = await poster("equipage/equipe/deplacer", { id: e.id, sens });
  if (r.ok) { accepter(r.donnees); if (surChange) surChange(); } else toast(r.erreur || "Refusé.", "erreur");
}

// ─── L'éditeur d'une équipe ─────────────────────────────────────────────────
/** Créer (`e` absent) ou modifier une équipe. */
export async function editerEquipe(e, surChange) {
  if (e && !siLibre("equipe:" + e.id)) return;
  const d = (await lireEquipes()) || { equipes: [], metiers: [], badges: {} };
  const clan = ((etat.d && etat.d.clan && etat.d.clan.membres) || []).slice();
  const st = e && e.saisie_type;
  const v = {
    nom: e ? e.nom : "", type: st ? (st.genre === "metier" ? "metier:" + st.cle : "libre") : "", libre: st && st.genre === "libre" ? st.texte : "",
    chef: e && e.chef ? String(e.chef.id) : "", membres: new Set(e ? e.membres.map((p) => String(p.id)) : []), version: e ? e.version : 0,
  };
  //  Le titre : le nom seul (la police des titres n'a pas les guillemets « »).
  const p = pancarte({ titre: e ? sansEmoji(e.nom) : "Nouvelle équipe", sous: e ? "L'équipe : son chef d'équipe et les membres qu'il a sous sa main." : "Son chef d'équipe et les membres qu'il a sous sa main.", icone: "equipage", taille: "large" });
  if (e) {
    protegerEditeur(p, "equipe:" + e.id, "l'équipe « " + sansEmoji(e.nom).slice(0, 60) + " »", { relire: async () => {
      const frais = ((await lireEquipes(true)) || { equipes: [] }).equipes.find((x) => x.id === e.id);
      if (!frais) throw new Error("équipe supprimée");
      editerEquipe(frais, surChange);
    } });
  }
  //  Qui est où, dans les AUTRES équipes : un chef ailleurs ne peut pas venir ici ; un membre ailleurs y change d'équipe.
  const autres = d.equipes.filter((x) => !e || x.id !== e.id);
  const chefDe = new Map(autres.filter((x) => x.chef).map((x) => [String(x.chef.id), x]));
  const dans = new Map();
  autres.forEach((x) => x.membres.forEach((m) => dans.set(String(m.id), x)));
  const badges = d.badges || {};
  const nomI = saisie({ value: v.nom, maxlength: 60, placeholder: "Les Cuistots du Requin" });
  nomI.addEventListener("input", () => { v.nom = nomI.value; });
  const libreI = saisie({ value: v.libre, maxlength: 40, placeholder: "Abordage, Garde du navire…" });
  libreI.addEventListener("input", () => { v.libre = libreI.value; });
  const libreC = champ("Le type, en quelques mots", libreI);
  libreC.hidden = v.type !== "libre";
  const typeL = liste({ valeur: v.type, label: "Type d'équipe", plein: true, changer: (x) => { v.type = x; libreC.hidden = x !== "libre"; },
    options: [{ v: "", l: "Aucun type" }, ...(d.metiers || []).map((m) => ({ v: "metier:" + m.cle, l: m.nom, img: srcSure(m.icone) || null })), { v: "libre", l: "Un autre type (un libellé)…" }] });
  const chefZone = h("div", { classe: "pile serree" }), membresZone = h("div", { classe: "pile serree" });
  let qChef = "", qMembres = "";
  const trier = (l) => l.sort((a, b) => (!!badges[String(b.id)] - !!badges[String(a.id)]) || nomDe(a).localeCompare(nomDe(b), "fr", { sensitivity: "base" }));
  const ident = (m, sous, badge) => h("span", { classe: "choix-personne" }, avatar(m, "p"), h("span", { classe: "choix-personne-texte" }, h("b", {}, nomDe(m)), sous ? h("small", {}, sous) : null), badge);
  function dessinerChef() {
    const l = trier(clan.filter((m) => contient(nomDe(m) + " " + (m.pseudo || "") + " " + m.id, qChef)));
    const actuel = clan.find((m) => String(m.id) === v.chef);
    remplacer(chefZone,
      h("p", { classe: "aide" }, actuel ? h("span", {}, nomChef() + " : ", h("b", {}, nomDe(actuel)), " ") : "Aucun chef choisi. ",
        actuel ? bouton("Retirer le chef", { classe: "p discret", onclick: () => { v.chef = ""; dessinerChef(); dessinerMembres(); } }) : null),
      recherche(qChef, "Chercher un membre du clan…", (q) => { qChef = q; dessinerChef(); }, { nom: "chercher-chef" }),
      h("ol", { classe: "selection-liste choix-equipe", role: "radiogroup", "aria-label": nomChef() }, l.slice(0, 120).map((m) => {
        const id = String(m.id), ailleurs = chefDe.get(id);
        const radio = h("input", { type: "radio", name: "chef-equipe", value: id, disabled: ailleurs ? true : null });
        radio.checked = v.chef === id;
        radio.addEventListener("change", () => { if (radio.checked) { v.chef = id; v.membres.delete(id); dessinerChef(); dessinerMembres(); } });
        const sous = ailleurs ? "déjà chef de « " + sansEmoji(ailleurs.nom) + " »" : dans.has(id) ? "dans « " + sansEmoji(dans.get(id).nom) + " » : il en changera" : "";
        return h("li", {}, h("label", { classe: "selection-item" + (v.chef === id ? " choisie" : "") }, radio,
          ident(m, sous, null), badges[id] ? pastille(badges[id], "#a8823f") : null));
      })));
  }
  function dessinerMembres() {
    const l = trier(clan.filter((m) => String(m.id) !== v.chef && contient(nomDe(m) + " " + (m.pseudo || "") + " " + m.id, qMembres)));
    remplacer(membresZone,
      h("p", { classe: "aide" }, quantite(v.membres.size, "membre(s) choisi(s)") + ". Un membre déjà dans une autre équipe la quitte pour celle-ci."),
      recherche(qMembres, "Chercher un membre du clan…", (q) => { qMembres = q; dessinerMembres(); }, { nom: "chercher-membres" }),
      h("ol", { classe: "selection-liste choix-equipe", "aria-label": "Les membres de l'équipe" }, l.slice(0, 200).map((m) => {
        const id = String(m.id), chefAilleurs = chefDe.get(id);
        const caseM = h("input", { type: "checkbox", value: id, disabled: chefAilleurs ? true : null });
        caseM.checked = v.membres.has(id);
        caseM.addEventListener("change", () => { if (caseM.checked) v.membres.add(id); else v.membres.delete(id); dessinerMembres(); });
        const sous = chefAilleurs ? nomChef().toLowerCase() + " de « " + sansEmoji(chefAilleurs.nom) + " »" : dans.has(id) ? "dans « " + sansEmoji(dans.get(id).nom) + " »" : "";
        return h("li", {}, h("label", { classe: "selection-item" + (v.membres.has(id) ? " choisie" : "") }, caseM, ident(m, sous, null),
          dans.has(id) && !chefAilleurs ? pastille("Change d'équipe", "#a8641c") : null));
      })));
  }
  dessinerChef();
  dessinerMembres();
  ajouter(p.corps, [champ("Nom de l'équipe", nomI), typeL, libreC,
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, nomChef()), h("span", { classe: "champ-aide" }, "N'importe quel membre du clan ; un badge signale un chef validé (proposé en premier)."), chefZone),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Les membres"), membresZone)]);
  const enregistrerB = bouton(e ? "Enregistrer l'équipe" : "Créer l'équipe", { classe: "principal", icone: "valider", reseau: true, onclick: enregistrer });
  ajouter(p.pied, [e ? bouton("Supprimer", { classe: "discret danger", icone: "supprimer", onclick: supprimer }) : null,
    bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), enregistrerB]);
  setTimeout(() => nomI.focus(), 60);

  async function enregistrer() {
    if (!v.nom.trim()) { toast("Donne un nom à l'équipe.", "erreur"); nomI.focus(); return; }
    if (v.type === "libre" && !v.libre.trim()) { toast("Écris le type de l'équipe, ou choisis un métier.", "erreur"); libreI.focus(); return; }
    const type = !v.type ? null : v.type === "libre" ? { genre: "libre", texte: v.libre.trim() } : { genre: "metier", cle: v.type.slice(7) };
    const corps = { nom: v.nom.trim(), type, chef: v.chef || null, membres: [...v.membres].filter((x) => x !== v.chef) };
    if (e) Object.assign(corps, { id: e.id, version: v.version });
    enregistrerB.disabled = true;
    const r = await poster("equipage/equipe", corps);
    enregistrerB.disabled = false;
    if (r.ok) {
      accepter(r.donnees);
      toast(e ? "Équipe enregistrée." : "Équipe créée.", "succes");
      p.fermer();
      if (surChange) surChange();
      return;
    }
    if (r.status === 409) {
      toast("Cette équipe a changé ailleurs pendant que tu la modifiais : voici la version enregistrée.", "erreur");
      const frais = ((await lireEquipes(true)) || { equipes: [] }).equipes.find((x) => x.id === e.id);
      p.fermer();
      if (frais) editerEquipe(frais, surChange);
      return;
    }
    toast(r.erreur || "Refusé.", "erreur");
  }
  async function supprimer() {
    const ok = await confirmer({ titre: "Supprimer l'équipe « " + sansEmoji(e.nom) + " » ?", texte: "Son chef et ses membres restent au clan, sans équipe.", libelleOk: "Supprimer", style: "danger" });
    if (!ok) return;
    const r = await poster("equipage/equipe/supprimer", { id: e.id });
    if (!r.ok) { toast(r.erreur || "Refusé.", "erreur"); return; }
    accepter(r.donnees);
    toast("Équipe supprimée.", "succes");
    p.fermer();
    if (surChange) surChange();
  }
}

// ─── La fiche d'un membre : « Équipe : … (chef : …) » ───────────────────────
/** Sa ligne d'équipe, remplie dès que les équipes sont lues (rien si elles ne le sont pas). */
export function ligneEquipe(id) {
  const el = h("div", { classe: "fiche-equipe sous-nom" });
  lireEquipes().then((d) => {
    if (!d || !el.isConnected) return;
    const sid = String(id);
    const e = d.equipes.find((x) => (x.chef && String(x.chef.id) === sid) || x.membres.some((m) => String(m.id) === sid));
    remplacer(el, icone("equipage", "ic-p"), " Équipe : ", e ? h("b", {}, sansEmoji(e.nom)) : "aucune",
      e ? (e.chef && String(e.chef.id) === sid ? " · " + nomChef().toLowerCase() : e.chef ? " (chef : " + sansEmoji(e.chef.nom) + ")" : " (sans chef)") : "");
  });
  return el;
}
