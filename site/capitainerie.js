// capitainerie.js — « La Capitainerie » : l'atelier des affiches (galerie par métier, éditeur, historique, corbeille),
// le catalogue RELL Seas (uniquement ce qui existe dans le jeu, modifiable), les rôles des métiers.

import { h, icone, date, depuis, nombre, prime, sansEmoji, contient, norm, maintenant, uuid, retarder, srcSure, remplacer, trier, compte, telephone, BASE, copie, ajouter } from "./dom.js";
import { etat, P, peutAgir, aller, filtres, enLigne, emettre, ecouter, poserAncre } from "./noyau.js";
import { lire, poster } from "./api.js";
import { charger, vue as vueJeu, perime, typesTries, elementsDe, element, typeMetier, typeGrade } from "./donnees.js";
import { mettreEnFile, garderSaisie, lireSaisie, oublierSaisie, opsDe } from "./hors_ligne.js";
import {
  bouton, boutonIcone, avatar, pastille, tampon, vide, tuile, tuiles, puces, segment, recherche, liste, champ, saisie, zoneTexte,
  interrupteur, caseACocher, radios, confirmer, pancarte, toast, section, squelettes, paginer, groupe, bandeau, compteur, nomDe, majBoutonsReseau,
} from "./ui.js";
import { affiche, insignes, nomAffiche, metiersDe, gradeDe, insigneImage, STATUTS_AFFICHE, monogramme, primeNoeud, logo } from "./affiche.js";
import { ouvrirFiche } from "./fiche.js";

const resetPages = (p) => { for (const k of Object.keys(etat.pages)) if (k.startsWith(p)) delete etat.pages[k]; };
const RAYON_CORBEILLE = 30;

// ═══ L'ATELIER DES AFFICHES ═════════════════════════════════════════════
export function affiches(vue, ctx) {
  const f = filtres("affiches", { q: "", vue: "metier", statut: "tous", tri: "nom" });
  const haut = h("div", { classe: "pile" }), resultats = h("div", { classe: "pile" }, squelettes(3));
  const changer = () => { resetPages("aff"); maj(); };
  ajouter(vue, [haut, h("div", { classe: "outils" },
    recherche(f.q, "Nom, surnom, nom Roblox, métier…", (q) => { f.q = q; changer(); }),
    segment(f.vue, [["metier", "Par métier"], ["tout", "Toutes"], ["corbeille", "Corbeille"]], (v) => { f.vue = v; changer(); }, "Présentation"),
    liste({ valeur: f.statut, label: "Statut", options: [{ v: "tous", l: "Tous les statuts" }, ...Object.entries(STATUTS_AFFICHE).map(([v, l]) => ({ v, l }))], changer: (v) => { f.statut = v; changer(); } }),
    liste({ valeur: f.tri, label: "Tri", options: [{ v: "nom", l: "Nom A → Z" }, { v: "prime", l: "Prime la plus haute" }, { v: "recent", l: "Modifiées récemment" }], changer: (v) => { f.tri = v; changer(); } }),
    peutAgir() ? bouton("Nouvelle affiche", { classe: "principal", icone: "plume", onclick: () => editer(null) }) : null), resultats]);
  let premier = true;
  const maj = async () => {
    const [cat, aff] = [await charger("catalogue"), await charger("affiches")];
    if (!resultats.isConnected) return;
    if (!aff || aff.erreur) { remplacer(resultats, vide("Affiches indisponibles", aff && aff.erreur, "hors_ligne")); remplacer(haut); return; }
    const { actives, corbeille } = rangerAffiches(aff);
    const aVerifier = actives.filter((a) => insignes(a, cat).some((i) => !i.existe || i.actif === false)).length;
    const attente = actives.filter((a) => a._attente).length;
    remplacer(haut, tuiles(
      tuile({ cle: "af1", lib: "Affiches", val: actives.length, icone: "affiches", sous: compte(new Set(actives.map((a) => a.membre && a.membre.id).filter(Boolean)).size, "membre"), teinte: "#7a4b2a" }),
      tuile({ cle: "af2", lib: "Primes cumulées", texte: primeNoeud(actives.reduce((s, a) => s + (Number(a.prime) || 0), 0)), icone: "berry", teinte: "#7a5a22" }),
      tuile({ cle: "af3", lib: "Insignes à revoir", val: aVerifier, icone: "attention", sous: "retirés ou absents du catalogue", teinte: aVerifier ? "#8e2a24" : "#3f6b3a" }),
      tuile({ cle: "af4", lib: "Corbeille", val: corbeille.length, icone: "supprimer", sous: "effacées après " + RAYON_CORBEILLE + " jours", teinte: "#4a5560", clic: () => { f.vue = "corbeille"; changer(); } }),
      attente ? tuile({ cle: "af5", lib: "En attente d'envoi", val: attente, icone: "synchro", teinte: "#a8641c", clic: () => emettre("file:ouvrir") }) : null));
    const texte = (a) => [nomAffiche(a), a.surnom, a.membre && a.membre.nom, a.roblox && a.roblox.nom, ...insignes(a, cat).map((i) => i.nom), gradeDe(a, cat)].join(" ");
    let l = (f.vue === "corbeille" ? corbeille : actives).filter((a) => (f.statut === "tous" || a.statut === f.statut) && contient(texte(a), f.q));
    l = f.tri === "prime" ? l.sort((a, b) => (b.prime || 0) - (a.prime || 0)) : f.tri === "recent" ? l.sort((a, b) => (b.maj_le || 0) - (a.maj_le || 0)) : l.sort((a, b) => nomAffiche(a).localeCompare(nomAffiche(b), "fr", { sensitivity: "base" }));
    const carte = (a) => affiche(a, cat, { taille: "mini", clic: () => ouvrirAffiche(a.id) });
    if (!l.length) remplacer(resultats, vide(f.vue === "corbeille" ? "La corbeille est vide" : "Aucune affiche ici", f.vue === "corbeille" ? "Une affiche mise à la corbeille y reste " + RAYON_CORBEILLE + " jours." : "Crée la première : « Nouvelle affiche ».", f.vue === "corbeille" ? "supprimer" : "affiches"));
    else if (f.vue === "corbeille") remplacer(resultats, h("p", { classe: "aide" }, "Dans la corbeille : restaure une affiche pour la remettre au mur. Au-delà de " + RAYON_CORBEILLE + " jours, elle est effacée pour de bon."),
      paginer("aff-corbeille", l, (a) => h("div", { classe: "corbeille-item" }, carte(a),
        h("p", { classe: "meta" }, "À la corbeille " + depuis(a.retire_le) + " · effacée dans " + Math.max(0, RAYON_CORBEILLE - Math.floor((maintenant() - a.retire_le) / 86400)) + " j"),
        peutAgir() ? bouton("Restaurer", { classe: "p vert", icone: "synchro", onclick: () => restaurer(a) }) : null), { classe: "grille affiches", pas: 18 }));
    else if (f.vue === "tout") remplacer(resultats, paginer("aff-tout", l, carte, { classe: "grille affiches", pas: 24 }));
    else {
      const t = typeMetier(cat);
      const groupes = new Map();
      for (const a of l) for (const k of (metiersDe(a, cat).length ? metiersDe(a, cat) : ["__aucun"])) { if (!groupes.has(k)) groupes.set(k, []); groupes.get(k).push(a); }
      const ordre = t ? elementsDe(cat, t.cle).map((e) => e.cle) : [];
      const cles = [...groupes.keys()].sort((a, b) => (a === "__aucun") - (b === "__aucun") || ((ordre.indexOf(a) + 1 || 999) - (ordre.indexOf(b) + 1 || 999)) || a.localeCompare(b));
      remplacer(resultats, h("p", { classe: "aide" }, "Une affiche à plusieurs métiers apparaît dans chacun. Touche une affiche pour la voir en grand, la modifier ou voir son historique."),
        ...cles.map((k) => {
          const e = t && k !== "__aucun" ? element(cat, t.cle, k) : null;
          return groupe({ titre: k === "__aucun" ? "Sans métier" : e ? e.nom : sansEmoji(k), compte: groupes.get(k).length,
            visuel: e ? insigneImage(e, "groupe-visuel") : null, icone: e ? null : "drapeau",
            info: e && e.nouveau_movie3 ? "nouveau · Movie 3" : "", cle: "aff-m-" + k, ouvert: cles.length <= 4 || !!f.q || cles.indexOf(k) < 2 ? true : undefined },
          () => paginer("aff-m-" + k, groupes.get(k), carte, { classe: "grille affiches", pas: 18 }));
        }));
    }
    if (premier) {
      premier = false;
      const s = ctx.sous || "";
      if (s.startsWith("nouvelle-")) editer(null, { membre_id: s.slice(9) });
      else if (s.startsWith("membre-")) {
        const a = actives.find((x) => x.membre && String(x.membre.id) === s.slice(7));
        if (a) ouvrirAffiche(a.id); else if (peutAgir()) editer(null, { membre_id: s.slice(7) });
      }
    }
  };
  maj();
  return { maj, majJeu: maj, majFile: maj };
}

/** Les affiches actives et la corbeille (le serveur les sépare ; les modifications en attente aussi). */
export function rangerAffiches(aff) {
  const vues = new Map();
  for (const a of [...((aff && aff.affiches) || []), ...((aff && aff.corbeille) || [])]) vues.set(String(a.id), a);
  const l = [...vues.values()];
  return { actives: l.filter((a) => !a.retire_le), corbeille: l.filter((a) => a.retire_le) };
}
async function restaurer(a) {
  await mettreEnFile("rell/affiche/retirer", { id: a.id, restaurer: true }, { genre: "affiche", cle: String(a.id), resume: "Restaurer l'affiche de " + nomAffiche(a), objet: Object.assign({}, a, { retire_le: null }) });
  toast(enLigne() ? "Affiche restaurée." : "Restauration gardée sur l'appareil : elle partira au retour de la connexion.", "succes");
  emettre("jeu", { nom: "affiches" });
}

/** Une affiche en grand, avec ses détails et ses actions. */
export async function ouvrirAffiche(id) {
  const [cat, aff] = [await charger("catalogue"), await charger("affiches")];
  const a = [...((aff && aff.affiches) || []), ...((aff && aff.corbeille) || [])].find((x) => String(x.id) === String(id));
  if (!a) { toast("Affiche introuvable (peut-être pas encore envoyée).", "erreur"); return; }
  const p = pancarte({ titre: "Affiche de " + nomAffiche(a), sous: a.surnom ? "« " + sansEmoji(a.surnom) + " »" : "", icone: "affiches", taille: "large" });
  const ins = insignes(a, cat);
  const historique = h("div", { classe: "pile serree" });
  const detail = h("div", { classe: "pile affiche-details" },
    a._attente ? bandeau(a._attente === "conflit" ? "Conflit : cette affiche a changé ailleurs pendant que tu la modifiais. Règle-le dans la file d'envoi." : "Modification gardée sur cet appareil : elle partira au retour de la connexion.", a._attente === "conflit" ? "rouge" : "") : null,
    h("dl", { classe: "champs-lus" },
      h("div", {}, h("dt", {}, "Membre"), h("dd", {}, a.membre && a.membre.id ? h("button", { classe: "lien-nom", type: "button", onclick: () => { p.fermer(); ouvrirFiche(a.membre.id); } }, sansEmoji(a.membre.nom) || a.membre.id) : "—")),
      h("div", {}, h("dt", {}, "Roblox"), h("dd", {}, a.roblox && a.roblox.nom ? a.roblox.nom + (a.roblox.id ? " · " + a.roblox.id : "") : "—")),
      h("div", {}, h("dt", {}, "Prime"), h("dd", { classe: "num" }, primeNoeud(a.prime || 0))),
      h("div", {}, h("dt", {}, "Grade"), h("dd", {}, gradeDe(a, cat) || "—")),
      h("div", {}, h("dt", {}, "Niveau"), h("dd", { classe: "num" }, a.niveau ? nombre(a.niveau) : "—")),
      h("div", {}, h("dt", {}, "Statut"), h("dd", {}, STATUTS_AFFICHE[a.statut] || a.statut || "—"))),
    ins.length ? h("ul", { classe: "insignes-liste" }, ins.map((i) => h("li", { classe: i.existe && i.actif !== false ? "" : "a-revoir" }, insigneImage(i, "insigne-liste-img"),
      h("span", {}, h("b", {}, i.nom), h("small", {}, i.typeNom)), !i.existe ? tampon("Absent du catalogue", "", true) : i.actif === false ? tampon("Retiré du catalogue", "ambre", true) : null))) : h("p", { classe: "aide" }, "Aucun insigne."),
    a.notes ? h("div", { classe: "reponse" }, h("dt", {}, "Notes"), h("dd", {}, a.notes)) : null,
    h("p", { classe: "meta" }, "Créée " + depuis(a.cree_le) + (a.cree_par ? " par " + nomDe(P(a.cree_par)) : "") + (a.maj_le && a.maj_le !== a.cree_le ? " · modifiée " + depuis(a.maj_le) + (a.maj_par ? " par " + nomDe(P(a.maj_par)) : "") : "")),
    groupe({ titre: "Historique", icone: "journal", cle: "aff-hist" }, () => { chargerHistorique(a, historique); return historique; }));
  ajouter(p.corps, [h("div", { classe: "affiche-grand" }, h("div", { classe: "affiche-grand-mur" }, affiche(a, cat, { taille: "grande" })), detail)]);
  if (peutAgir()) {
    ajouter(p.pied, [
      a.retire_le ? bouton("Restaurer", { classe: "vert", icone: "synchro", onclick: () => { restaurer(a); p.fermer(); } })
        : bouton("Mettre à la corbeille", { classe: "discret danger gauche", icone: "supprimer", onclick: async () => {
          const ok = await confirmer({ titre: "Mettre cette affiche à la corbeille ?", texte: "Elle quitte le mur ; tu peux la restaurer pendant " + RAYON_CORBEILLE + " jours.", libelleOk: "À la corbeille", style: "danger" });
          if (!ok) return;
          await mettreEnFile("rell/affiche/retirer", { id: a.id }, { genre: "affiche", cle: String(a.id), resume: "Corbeille : affiche de " + nomAffiche(a), objet: Object.assign({}, a, { retire_le: maintenant() }) });
          p.fermer();
          toast("Affiche mise à la corbeille.", "succes");
          emettre("jeu", { nom: "affiches" });
        } }),
      bouton("Appliquer les rôles", { icone: "roles", reseau: true, titre: "Donne ou retire les rôles Discord liés à ses métiers", onclick: () => appliquerRoles(a) }),
      bouton("Modifier", { classe: "principal", icone: "plume", onclick: () => { p.fermer(); editer(a); } })]);
  } else ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
  majBoutonsReseau(p.pied);
}
async function chargerHistorique(a, zone) {
  remplacer(zone, squelettes(2));
  const r = await lire("rell/affiche", { id: a.id });
  if (!zone.isConnected) return;
  const hist = (r.ok && r.donnees && r.donnees.historique) || [];
  if (!r.ok) { remplacer(zone, h("p", { classe: "aide" }, r.status === 0 ? "Hors ligne : l'historique n'a pas encore été lu sur cet appareil." : r.erreur)); return; }
  const cat = await charger("catalogue");
  const changements = (c) => (Array.isArray(c) ? c : c && typeof c === "object" ? Object.entries(c).map(([cle, v]) => Object.assign({ champ: cle }, v && typeof v === "object" ? v : { apres: v })) : []);
  const quiEst = (q) => (q && typeof q === "object" ? nomDe(P(q)) : /^\d{5,22}$/.test(String(q)) ? nomDe(P(q)) : sansEmoji(q));
  // Chaque changement en clair : les noms du catalogue (jamais la fiche brute), les primes en berrys, le membre par son nom.
  const LIBELLES = { membre_id: "Membre", roblox_nom: "Pseudo Roblox", roblox_id: "Compte Roblox", surnom: "Surnom", prime: "Prime", niveau: "Niveau", grade: "Grade",
    statut: "Statut", attributs: "Fiche du jeu", notes: "Notes" };
  const vide_ = (v) => v === null || v === undefined || v === "" || v === 0;
  const valeur = (champ, v) => {
    if (vide_(v)) return "(vide)";
    if (champ === "prime") return nombre(Number(v) || 0) + " berrys";
    if (champ === "niveau") return nombre(Number(v) || 0);
    if (champ === "membre_id") return nomDe(P(v));
    if (champ === "statut") return STATUTS_AFFICHE[v] || String(v);
    if (champ === "grade") { const tg = typeGrade(cat); const e = tg && element(cat, tg.cle, v); return e ? e.nom : String(v); }
    return typeof v === "object" ? "" : String(v);
  };
  const nomsDe = (fiche) => { const out = new Map(); for (const [t, cles] of Object.entries(fiche || {})) for (const k of cles || []) { const e = element(cat, t, k); out.set(t + ":" + k, e ? e.nom : k); } return out; };
  const ligne = (c) => {
    const champ = c.champ || c.nom || "";
    const lib = LIBELLES[champ] || champ || "Champ";
    if (champ === "notes") return h("li", {}, h("b", {}, lib), " : modifiées");
    if (champ === "attributs") {
      const avant = nomsDe(c.avant), apres = nomsDe(c.apres);
      const plus = [...apres].filter(([k]) => !avant.has(k)).map(([, n]) => n), moins = [...avant].filter(([k]) => !apres.has(k)).map(([, n]) => n);
      return h("li", {}, h("b", {}, lib), " : ", plus.length ? "ajouté " + plus.join(", ") : "", plus.length && moins.length ? " · " : "", moins.length ? "retiré " + moins.join(", ") : "", !plus.length && !moins.length ? "réordonnée" : "");
    }
    // Une valeur d'avant vide (la création, un champ rempli pour la première fois) : la nouvelle seule, sans « (vide) → ».
    return h("li", {}, h("b", {}, lib), " : ", !vide_(c.avant) ? [h("s", {}, valeur(champ, c.avant)), " → "] : null, valeur(champ, c.apres !== undefined ? c.apres : c.valeur));
  };
  remplacer(zone, hist.length ? h("ul", { classe: "entrees" }, hist.map((x) => h("li", { classe: "entree" }, h("div", { classe: "haut" }, h("span", { classe: "quoi" }, x.quoi || "Modification"), h("span", { classe: "quand" }, date(x.quand, true))),
    x.par || x.qui ? h("div", { classe: "meta" }, "par " + quiEst(x.par || x.qui)) : null,
    changements(x.changements).length ? h("ul", { classe: "changements" }, changements(x.changements).slice(0, 10).map(ligne)) : null))) : h("p", { classe: "aide" }, "Aucun changement noté."));
}
async function appliquerRoles(a) {
  const ok = await confirmer({ titre: "Appliquer les rôles de ses métiers ?", texte: "Les rôles Discord liés à ses métiers (rubrique Rôles & métiers) lui sont donnés ; ceux des métiers qu'il n'a plus lui sont retirés. C'est noté au journal.", libelleOk: "Appliquer", icone: "roles" });
  if (!ok) return;
  const r = await poster("rell/roles/appliquer", { affiche_id: a.id });
  toast(r.ok ? (r.donnees.message || "Rôles appliqués.") : r.erreur, r.ok ? "succes" : "erreur");
}

// ─── L'éditeur d'affiche ────────────────────────────────────────────────────
/** Crée (a = null) ou modifie une affiche. Les choix viennent UNIQUEMENT du catalogue. */
export async function editer(a, preremplir) {
  const cat = await charger("catalogue");
  if (!cat || cat.erreur) { toast("Le catalogue est indisponible : impossible de choisir les insignes.", "erreur"); return; }
  const cleSaisie = "affiche:" + (a ? a.id : "nouvelle");
  const gardee = await lireSaisie(cleSaisie);
  const base_ = a ? {
    membre_id: a.membre && a.membre.id ? String(a.membre.id) : "", membre: a.membre || null, roblox: { nom: (a.roblox && a.roblox.nom) || "", id: (a.roblox && a.roblox.id) || "", avatar: (a.roblox && a.roblox.avatar) || "" },
    surnom: a.surnom || "", prime: a.prime || 0, niveau: a.niveau || 0, grade: a.grade || "", statut: a.statut || "actif", attributs: copie(a.attributs || {}), notes: a.notes || "",
  } : { membre_id: "", membre: null, roblox: { nom: "", id: "", avatar: "" }, surnom: "", prime: 0, niveau: 0, grade: "", statut: "actif", attributs: {}, notes: "" };
  const v = gardee && gardee.valeur ? gardee.valeur : base_;
  if (!a && preremplir && preremplir.membre_id && !v.membre_id) {
    v.membre_id = String(preremplir.membre_id);
    const m = ((etat.d && etat.d.clan && etat.d.clan.membres) || []).find((x) => String(x.id) === v.membre_id) || P(v.membre_id);
    v.membre = { id: v.membre_id, nom: m.nom, avatar: m.avatar };
  }
  let modifie = false;
  const p = pancarte({
    titre: a ? "Modifier l'affiche" : "Nouvelle affiche", sous: "Les insignes viennent uniquement du catalogue du jeu.", icone: "plume", taille: "tres-large",
    garde: async (valeur) => {
      if (valeur === "enregistre" || !modifie) return true;
      return !!(await confirmer({ titre: "Quitter sans enregistrer ?", texte: "Ta saisie reste gardée sur cet appareil : tu la retrouveras en rouvrant l'éditeur.", libelleOk: "Quitter", style: "danger" }));
    },
  });
  const apercu = h("div", { classe: "affiche-apercu" });
  const garder = retarder(() => garderSaisie(cleSaisie, v), 300);
  const objetApercu = () => ({
    id: a ? a.id : "apercu", membre: v.membre || { id: v.membre_id, nom: "", avatar: "" }, roblox: v.roblox, surnom: v.surnom, prime: v.prime, niveau: v.niveau,
    grade: v.grade, statut: v.statut, attributs: v.attributs, notes: v.notes,
  });
  const majApercu = () => remplacer(apercu, affiche(objetApercu(), cat, { taille: "grande" }));
  const changer = (k, x) => { v[k] = x; modifie = true; garder(); majApercu(); };
  const form = h("div", { classe: "pile" });
  if (gardee && gardee.valeur) ajouter(form, [bandeau("Ta saisie précédente a été retrouvée sur cet appareil.", "vert", bouton("Revenir à la version enregistrée", { classe: "p discret", onclick: async () => { await oublierSaisie(cleSaisie); p.fermer("enregistre"); editer(a, preremplir); } }))]);

  // Le membre
  const membreZone = h("div", { classe: "membre-choisi" });
  const majMembre = () => remplacer(membreZone, v.membre && v.membre_id
    ? h("div", { classe: "qui" }, avatar(v.membre, "p"), h("div", { classe: "bloc" }, h("div", { classe: "nom" }, sansEmoji(v.membre.nom) || v.membre_id), h("div", { classe: "sous-nom ident" }, v.membre_id)),
      bouton("Changer", { classe: "p discret", onclick: () => choisirMembre() }))
    : bouton("Choisir le membre", { classe: "p", icone: "personne", onclick: () => choisirMembre() }));
  const choisirMembre = async () => {
    const m = await selecteurMembre();
    if (m) { v.membre_id = String(m.id); v.membre = { id: String(m.id), nom: m.nom, avatar: m.avatar }; modifie = true; garder(); majMembre(); majApercu(); }
  };
  majMembre();
  // Roblox
  const robloxNom = saisie({ value: v.roblox.nom || "", maxlength: 20, placeholder: "NomRoblox_123", spellcheck: "false" });
  const portraitEtat = h("span", { classe: "meta" }, v.roblox.id ? "Portrait trouvé (identifiant " + v.roblox.id + ")." : "");
  robloxNom.addEventListener("input", () => { v.roblox = { nom: robloxNom.value.trim(), id: "", avatar: "" }; portraitEtat.textContent = ""; modifie = true; garder(); majApercu(); });
  const chercher = bouton("Chercher le portrait", { classe: "p", icone: "roblox", reseau: true, onclick: async () => {
    const nomR = robloxNom.value.trim();
    if (!/^[A-Za-z0-9_]{3,20}$/.test(nomR)) { toast("Nom Roblox : 3 à 20 lettres, chiffres ou « _ ».", "erreur"); return; }
    portraitEtat.textContent = "Recherche…";
    const r = await poster("rell/avatar", { roblox_nom: nomR });
    if (r.ok && r.donnees) { v.roblox = { nom: r.donnees.nom || nomR, id: String(r.donnees.roblox_id || ""), avatar: r.donnees.avatar || "" }; portraitEtat.textContent = "Portrait trouvé (identifiant " + v.roblox.id + ")."; modifie = true; garder(); majApercu(); }
    else portraitEtat.textContent = r.erreur || "Introuvable.";
  } });
  const surnom = saisie({ value: v.surnom, maxlength: 60, placeholder: "l'Ombre des Mers" });
  surnom.addEventListener("input", () => changer("surnom", surnom.value));
  const primeE = h("input", { type: "number", classe: "saisie", min: 0, max: 1e12, step: 1000, value: v.prime || 0, inputmode: "numeric" });
  const primeLue = h("span", { classe: "meta num" }, primeNoeud(v.prime || 0));
  primeE.addEventListener("input", () => { const n = Math.max(0, Math.min(1e12, Math.round(Number(primeE.value) || 0))); remplacer(primeLue, primeNoeud(n)); changer("prime", n); });
  const niveau = h("input", { type: "number", classe: "saisie", min: 0, max: 10000, step: 1, value: v.niveau || 0, inputmode: "numeric" });
  niveau.addEventListener("input", () => changer("niveau", Math.max(0, Math.min(10000, Math.round(Number(niveau.value) || 0)))));
  const tg = typeGrade(cat);
  const gradeC = tg
    ? liste({ valeur: v.grade || "", label: "Grade", plein: true, options: [{ v: "", l: "Aucun grade" }, ...elementsDe(cat, tg.cle).filter((e) => e.actif !== false || e.cle === v.grade).map((e) => ({ v: e.cle, l: e.nom, img: srcSure(e.icone) || null }))], changer: (x) => changer("grade", x) })
    : champ("Grade", (() => { const s = saisie({ value: v.grade, maxlength: 40 }); s.addEventListener("input", () => changer("grade", s.value)); return s; })());
  const statut = liste({ valeur: v.statut || "actif", label: "Statut", plein: true, options: Object.entries(STATUTS_AFFICHE).map(([k, l]) => ({ v: k, l })), changer: (x) => changer("statut", x) });
  ajouter(form, [
    h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "Qui"),
      h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Membre Discord"), membreZone),
      champ("Nom Roblox", robloxNom, { aide: "Le portrait est cherché par le serveur : ton adresse ne part jamais chez Roblox." }),
      h("div", { classe: "rangee" }, chercher, portraitEtat),
      champ("Surnom", surnom, { optionnel: true })),
    h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "La prime et le rang"),
      h("div", { classe: "champs" }, champ("Prime (en berrys)", primeE, { aide: primeLue }), champ("Niveau", niveau)),
      h("div", { classe: "champs" }, gradeC, statut))]);
  // Les insignes : un bloc par type du catalogue (sauf le grade, choisi au-dessus)
  const reglagesMetiers = await charger("metiers_reglages").catch(() => null);
  const maxMetiers = reglagesMetiers && !reglagesMetiers.erreur ? Math.max(1, Math.min(5, Number(reglagesMetiers.max_metiers) || 0)) || null : null;
  const tm = typeMetier(cat);
  for (const t of typesTries(cat)) {
    if (tg && t.cle === tg.cle) continue;
    ajouter(form, [blocInsignes(cat, t, v, () => { modifie = true; garder(); majApercu(); }, tm && t.cle === tm.cle ? maxMetiers : null)]);
  }
  const notes = zoneTexte({ rows: 3, maxlength: 1000, placeholder: "Pour la direction seulement : rien de ceci n'apparaît sur l'affiche." }, v.notes);
  notes.addEventListener("input", () => changer("notes", notes.value));
  ajouter(form, [champ("Notes de la direction", notes, { optionnel: true })]);
  ajouter(p.corps, [h("div", { classe: "atelier editeur-affiche" }, form, h("div", { classe: "collant" }, h("div", { classe: "apercu-titre" }, icone("oeil"), "L'affiche, telle qu'elle sera"), apercu))]);
  majApercu();
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }),
    bouton("Enregistrer l'affiche", { classe: "principal", icone: "valider", onclick: async () => {
      const corps = {
        membre_id: v.membre_id || "", roblox: { nom: v.roblox.nom || "", id: v.roblox.id || "" }, surnom: v.surnom.trim(), prime: v.prime || 0, niveau: v.niveau || 0,
        grade: v.grade || "", statut: v.statut || "actif", attributs: Object.fromEntries(Object.entries(v.attributs).filter(([, l]) => l && l.length)), notes: v.notes || "",
      };
      if (!corps.membre_id && !corps.roblox.nom) { toast("Choisis au moins le membre ou son nom Roblox.", "erreur"); return; }
      // L'identifiant d'une nouvelle affiche est choisi ici (texte) : elle peut naître hors ligne sans changer de nom.
      const cle = a ? String(a.id) : uuid();
      corps.id = cle;
      if (a && a.version) corps.version = a.version;
      const objet = Object.assign(objetApercu(), { id: a ? a.id : cle, _cle: cle, version: a ? a.version : 0, cree_le: a ? a.cree_le : maintenant(), maj_le: maintenant(), retire_le: null,
        cree_par: a ? a.cree_par : etat.d && etat.d.droits && etat.d.droits.moi, maj_par: etat.d && etat.d.droits && etat.d.droits.moi });
      await mettreEnFile("rell/affiche", corps, { genre: "affiche", cle, resume: (a ? "Affiche modifiée : " : "Nouvelle affiche : ") + nomAffiche(objet), objet });
      await oublierSaisie(cleSaisie);
      p.fermer("enregistre");
      toast(enLigne() ? "Affiche enregistrée." : "Affiche gardée sur l'appareil : elle partira au retour de la connexion.", "succes");
      emettre("jeu", { nom: "affiches" });
    } })]);
}

/** Les choix d'un type (métiers, race, faction…) : des cases ou des boutons radio dessinés, avec l'icône officielle. */
function blocInsignes(cat, t, v, apres, maximum) {
  const elements = elementsDe(cat, t.cle);
  const choisis = new Set(v.attributs[t.cle] || []);
  const actifs = elements.filter((e) => e.actif !== false || choisis.has(e.cle));
  const grille = h("div", { classe: "choix-insignes" });
  let filtre = "";
  const majGrille = () => {
    const l = actifs.filter((e) => contient(e.nom + " " + (e.nom_en || ""), filtre));
    remplacer(grille, ...l.map((e) => {
      const coche = choisis.has(e.cle);
      const id = "ins-" + t.cle + "-" + e.cle;
      const entree = h("input", { type: t.multiple ? "checkbox" : "radio", name: "ins-" + t.cle, id, value: e.cle });
      entree.checked = coche;
      entree.addEventListener("change", () => {
        if (t.multiple && entree.checked && maximum && choisis.size >= maximum) {
          entree.checked = false;
          toast(maximum + " " + t.nom.toLowerCase() + " au plus par membre (réglage de Rôles & métiers).", "erreur");
          return;
        }
        if (t.multiple) { if (entree.checked) choisis.add(e.cle); else choisis.delete(e.cle); }
        else { choisis.clear(); if (entree.checked) choisis.add(e.cle); }
        v.attributs[t.cle] = [...choisis];
        apres();
        majGrille();
      });
      return h("label", { classe: "choix-insigne" + (coche ? " coche" : "") + (e.actif === false ? " retire" : ""), for: id, title: [e.nom_en, e.description].filter(Boolean).join(" — ") },
        entree, insigneImage(e, "choix-insigne-img"),
        h("span", { classe: "choix-insigne-nom" }, e.nom),
        e.statut === "a_verifier" ? h("span", { classe: "choix-insigne-marque" }, "à vérifier") : e.nouveau_movie3 ? h("span", { classe: "choix-insigne-marque neuf" }, "Movie 3") : null,
        h("span", { classe: "choix-insigne-coche", "aria-hidden": "true" }));
    }));
  };
  majGrille();
  const enTete = h("div", { classe: "rangee entre" },
    h("span", { classe: "champ-lib" }, t.nom + (t.multiple ? (maximum ? " · " + maximum + " au plus" : " · plusieurs choix") : " · un seul choix")),
    !t.multiple && choisis.size ? bouton("Aucun", { classe: "p discret", onclick: () => { choisis.clear(); v.attributs[t.cle] = []; apres(); majGrille(); } }) : null);
  const rech = elements.length > 12 ? recherche("", "Filtrer les " + t.nom.toLowerCase() + "…", (q) => { filtre = q; majGrille(); }) : null;
  return h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, t.nom), enTete, rech,
    actifs.length ? grille : h("p", { classe: "aide" }, "Rien dans le catalogue pour ce type : ajoute d'abord les éléments (Catalogue RELL Seas)."));
}

/** Choisir un membre : le clan d'abord, puis tout le serveur (en ligne). */
function selecteurMembre() {
  return new Promise((fin) => {
    let choix = null;
    const p = pancarte({ titre: "Choisir le membre", icone: "personne", taille: "etroite", surFermer: () => fin(choix) });
    const res = h("div", { classe: "lignes" });
    const clan = ((etat.d && etat.d.clan && etat.d.clan.membres) || []);
    const montrer = (l) => remplacer(res, ...(l.length ? l.slice(0, 30).map((m) => h("button", { classe: "ligne lien choix-membre", type: "button", onclick: () => { choix = m; p.fermer(); } },
      avatar(m, "p"), h("div", { classe: "bloc" }, h("div", { classe: "nom une-ligne" }, nomDe(m)), h("div", { classe: "sous-nom" }, (m.pseudo ? "@" + m.pseudo + " · " : "") + (m.clan === false ? "hors du clan" : "clan"))))) : [vide("Personne", "Essaie un autre nom ou l'identifiant.")]));
    let dernier = "";
    const r = recherche("", "Nom, pseudo ou identifiant…", async (q) => {
      dernier = q;
      const locaux = clan.filter((m) => contient(m.nom + " " + m.pseudo + " " + m.id, q));
      montrer(locaux);
      if (q.length >= 2 && enLigne()) {
        const rr = await lire("recherche", { q });
        if (dernier !== q || !rr.ok) return;
        const vus = new Set(locaux.map((m) => m.id));
        montrer(locaux.concat((rr.donnees.membres || []).filter((m) => !vus.has(m.id))));
      }
    });
    ajouter(p.corps, [r, h("p", { classe: "aide" }, enLigne() ? "Le clan d'abord ; à partir de deux lettres, tout le serveur." : "Hors ligne : seulement les membres du clan."), res]);
    montrer(clan.slice().sort((a, b) => nomDe(a).localeCompare(nomDe(b), "fr")));
    requestAnimationFrame(() => r.champ.focus());
  });
}

// ═══ LE CATALOGUE RELL SEAS ═════════════════════════════════════════════
export function catalogue(vue) {
  const f = filtres("catalogue", { q: "", type: "", statut: "tous", movie3: false, inactifs: false });
  const haut = h("div", { classe: "pile" }), onglets = h("div", { classe: "sous-onglets", role: "tablist", "aria-label": "Types" }), resultats = h("div", { classe: "pile" }, squelettes(3));
  const changer = () => { resetPages("cat"); maj(); };
  ajouter(vue, [haut, h("div", { classe: "outils" },
    recherche(f.q, "Chercher dans tout le catalogue…", (q) => { f.q = q; changer(); }),
    liste({ valeur: f.statut, label: "Statut", options: [{ v: "tous", l: "Tous" }, { v: "confirme", l: "Confirmés" }, { v: "a_verifier", l: "À vérifier" }], changer: (v) => { f.statut = v; changer(); } }),
    caseACocher("Nouveautés du Movie 3", f.movie3, (v) => { f.movie3 = v; changer(); }),
    caseACocher("Montrer les retirés", f.inactifs, (v) => { f.inactifs = v; changer(); }),
    peutAgir() ? bouton("Ajouter un élément", { classe: "principal", icone: "ajouter", onclick: () => editerElement(null, f.type) }) : null,
    peutAgir() ? bouton("Les types", { icone: "filtrer", onclick: () => gererTypes() }) : null), onglets, resultats, creditsRell()]);
  const maj = async () => {
    const cat = await charger("catalogue");
    if (!resultats.isConnected) return;
    if (!cat || cat.erreur) { remplacer(resultats, vide("Catalogue indisponible", cat && cat.erreur, "hors_ligne")); return; }
    const types = typesTries(cat), els = cat.elements || [];
    if (f.type && !types.some((t) => t.cle === f.type)) f.type = "";
    const aVerifier = els.filter((e) => e.statut === "a_verifier" && e.actif !== false).length, neufs = els.filter((e) => e.nouveau_movie3 && e.actif !== false).length;
    remplacer(haut, tuiles(
      tuile({ cle: "c1", lib: "Éléments", val: els.filter((e) => e.actif !== false).length, icone: "catalogue", sous: compte(types.length, "type"), teinte: "#1f4e5a" }),
      tuile({ cle: "c2", lib: "À vérifier", val: aVerifier, icone: "attention", sous: "pas encore confirmés", teinte: aVerifier ? "#a8641c" : "#3f6b3a", clic: () => { f.statut = "a_verifier"; changer(); } }),
      tuile({ cle: "c3", lib: "Nouveautés · Movie 3", val: neufs, icone: "etoile", teinte: "#7a5a22", clic: () => { f.movie3 = true; changer(); } }),
      tuile({ cle: "c4", lib: "Mis à jour", texte: cat.maj ? depuis(cat.maj) : "—", icone: "calendrier", teinte: "#4a5560" })),
      h("p", { classe: "aide" }, "Uniquement ce qui existe dans le jeu. Ce qui n'est pas encore sûr porte le tampon « à vérifier », avec sa source. Les affiches ne proposent que ces éléments."));
    const garde = (e) => (f.inactifs || e.actif !== false) && (f.statut === "tous" || e.statut === f.statut) && (!f.movie3 || e.nouveau_movie3)
      && contient([e.nom, e.nom_en, e.description, e.categorie, e.rarete, e.source].join(" "), f.q);
    const nb = Object.fromEntries(types.map((t) => [t.cle, els.filter((e) => e.type === t.cle && garde(e)).length]));
    remplacer(onglets, h("button", { classe: "etiquette", type: "button", role: "tab", "aria-selected": String(!f.type), onclick: () => { f.type = ""; changer(); } }, icone("catalogue"), "Tout", h("span", { classe: "compteur calme" }, String(Object.values(nb).reduce((a, b) => a + b, 0)))),
      ...types.map((t) => h("button", { classe: "etiquette", type: "button", role: "tab", "aria-selected": String(f.type === t.cle), onclick: () => { f.type = t.cle; changer(); } }, sansEmoji(t.nom), h("span", { classe: "compteur calme" }, String(nb[t.cle] || 0)))));
    const visibles = types.filter((t) => !f.type || t.cle === f.type);
    const blocs = visibles.map((t) => {
      const l = elementsDe(cat, t.cle).filter(garde);
      if (!l.length && (!f.type || f.q)) return null;
      const contenu = l.length ? paginer("cat-" + t.cle, l, (e) => carteElement(e), { classe: "grille catalogue-grille", pas: 24 }) : vide("Rien ici", "Ajoute le premier élément de ce type.");
      return f.type ? contenu : groupe({ titre: sansEmoji(t.nom), compte: l.length, cle: "cat-g-" + t.cle, info: t.nom_en || "", ouvert: visibles.length <= 2 || !!f.q || f.movie3 || f.statut !== "tous" || visibles.indexOf(t) === 0 ? true : undefined }, () => contenu);
    }).filter(Boolean);
    remplacer(resultats, ...(blocs.length ? blocs : [vide("Rien ici", "Change le filtre ou la recherche.")]));
  };
  maj();
  return { maj, majJeu: maj, majFile: maj };
}
/** Les logos officiels (site/logos/) et à qui ils appartiennent ; un logo absent devient une pastille gravée. */
function creditsRell() {
  const LOGOS = [["logos/rellseas_jeu.webp", "RELL Seas", "le jeu"], ["logos/rellseas_groupe.webp", "RELL Seas", "le groupe Roblox"],
    ["logos/rellgames_groupe.webp", "RELL GAMES", "le studio"], ["logos/rellseas_discord.webp", "RELL Seas", "le Discord officiel"]];
  return h("div", { classe: "cadre pile serree credits-rell" },
    h("div", { classe: "logos-rell" }, LOGOS.map(([src, nom, sous]) => h("span", { classe: "logo-rell" }, logo(src, nom, "logo-rell-img"), h("span", {}, h("b", {}, nom), " · " + sous)))),
    h("p", { classe: "meta" }, "Icônes, logos et rendus : RELL Seas, du studio RELL Games. Ils leur appartiennent ; ils servent ici, sur le site privé du clan."));
}
const sourceCourte = (s) => String(s || "").replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
function carteElement(e) {
  const ouvrir = () => (peutAgir() ? editerElement(e) : null);
  return h(peutAgir() ? "button" : "article", { classe: "feuillet element-carte" + (e.actif === false ? " retire" : "") + (e._attente ? " en-attente" : ""), type: peutAgir() ? "button" : null, onclick: peutAgir() ? ouvrir : null },
    e.nouveau_movie3 ? h("span", { classe: "ruban-neuf" }, "Movie 3") : null,
    h("div", { classe: "element-tete" }, insigneImage(e, "element-icone"),
      h("div", { classe: "bloc" }, h("b", { classe: "element-nom" }, e.nom), e.nom_en ? h("span", { classe: "element-en" }, e.nom_en) : null)),
    e.description ? h("p", { classe: "element-desc coupe3" }, e.description) : null,
    h("div", { classe: "pastilles" }, e.categorie ? pastille(e.categorie, "#4a5560") : null, e.rarete ? pastille(e.rarete, "#7a5a22") : null),
    h("div", { classe: "element-pied" },
      e.actif === false ? tampon("Retiré", "encre", true) : e.statut === "a_verifier" ? tampon("À vérifier", "ambre", true) : tampon("Confirmé", "vert", true),
      e._attente ? tampon(e._attente === "conflit" ? "Conflit" : "En attente", "", true) : null,
      e.source ? h("span", { classe: "meta une-ligne", title: e.source }, "Source : " + sourceCourte(e.source)) : null));
}
async function editerElement(e, typeParDefaut) {
  const cat = await charger("catalogue");
  if (!cat || cat.erreur) return;
  const types = typesTries(cat);
  const v = e ? Object.assign({}, e) : { type: typeParDefaut || (types[0] && types[0].cle) || "", nom: "", nom_en: "", description: "", categorie: "", rarete: "", icone: "", statut: "a_verifier", source: "", ordre: 0, actif: true, nouveau_movie3: false };
  const p = pancarte({ titre: e ? "« " + e.nom + " »" : "Ajouter un élément", sous: e ? (types.find((t) => t.cle === e.type) || {}).nom : "Uniquement ce qui existe dans le jeu.", icone: "catalogue", taille: "large" });
  const icZone = h("div", { classe: "rangee icone-choix" });
  const majIcone = () => {
    remplacer(icZone, insigneImage({ icone: v.icone, nom: v.nom || "?", type: v.type }, "element-icone grand"),
      bouton(v.icone ? "Remplacer l'icône" : "Ajouter une icône", { classe: "p", icone: "ajouter", reseau: true, onclick: () => televerser((id) => { v.icone = "media/" + id; majIcone(); }) }),
      e && e.icone && v.icone !== e.icone ? bouton("Remettre l'icône d'origine", { classe: "p discret", onclick: () => { v.icone = e.icone; majIcone(); } }) : null);
    majBoutonsReseau(icZone);
  };
  majIcone();
  const s = (k, attrs) => { const x = saisie(Object.assign({ value: v[k] || "" }, attrs)); x.addEventListener("input", () => { v[k] = x.value; }); return x; };
  const desc = zoneTexte({ rows: 3, maxlength: 1000 }, v.description);
  desc.addEventListener("input", () => { v.description = desc.value; });
  const ordre = h("input", { type: "number", classe: "saisie", value: v.ordre || 0, min: 0, max: 9999 });
  ordre.addEventListener("input", () => { v.ordre = Number(ordre.value) || 0; });
  ajouter(p.corps, [
    e ? null : liste({ valeur: v.type, label: "Type", plein: true, options: types.map((t) => ({ v: t.cle, l: sansEmoji(t.nom) })), changer: (x) => { v.type = x; } }),
    h("div", { classe: "champs" }, champ("Nom (français)", s("nom", { maxlength: 80 })), champ("Nom en anglais", s("nom_en", { maxlength: 80 }), { optionnel: true })),
    champ("Description", desc, { optionnel: true }),
    h("div", { classe: "champs" }, champ("Catégorie", s("categorie", { maxlength: 60 }), { optionnel: true }), champ("Rareté", s("rarete", { maxlength: 40 }), { optionnel: true }), champ("Ordre", ordre)),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Icône officielle"), icZone),
    champ("Source (où c'est vérifié)", s("source", { maxlength: 200, placeholder: "Wiki RELL Seas, vidéo du Movie 3 à 12:40…" }), { optionnel: true }),
    radios("statut-element", [["confirme", "Confirmé", "vérifié dans le jeu"], ["a_verifier", "À vérifier", "pas encore sûr"]], v.statut, (x) => { v.statut = x; }, "Statut"),
    interrupteur("Nouveauté du Movie 3", v.nouveau_movie3, (x) => { v.nouveau_movie3 = x; }),
    interrupteur("Présent dans le jeu (décoché : retiré du catalogue)", v.actif !== false, (x) => { v.actif = x; })]);
  ajouter(p.pied, [
    e && e.actif !== false ? bouton("Retirer du catalogue", { classe: "discret danger gauche", icone: "supprimer", onclick: async () => {
      const ok = await confirmer({ titre: "Retirer « " + e.nom + " » ?", texte: "Il n'est plus proposé sur les affiches. Celles qui l'ont déjà le gardent, marqué « retiré du catalogue ».", libelleOk: "Retirer", style: "danger" });
      if (!ok) return;
      await mettreEnFile("rell/catalogue/retirer", { type: e.type, cle: e.cle }, { genre: "element", cle: e.type + ":" + e.cle, resume: "Retirer « " + e.nom + " » du catalogue" });
      p.fermer(); emettre("jeu", { nom: "catalogue" });
    } }) : null,
    bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }),
    bouton("Enregistrer", { classe: "principal", icone: "valider", onclick: async () => {
      if (!v.nom.trim()) { toast("Le nom est obligatoire.", "erreur"); return; }
      const corps = { type: v.type, nom: v.nom.trim(), nom_en: v.nom_en || "", description: v.description || "", categorie: v.categorie || "", rarete: v.rarete || "", icone: v.icone || "",
        statut: v.statut, source: v.source || "", ordre: v.ordre || 0, actif: v.actif !== false, nouveau_movie3: !!v.nouveau_movie3 };
      if (e) { corps.cle = e.cle; corps.version = e.version; }
      const cle = e ? e.type + ":" + e.cle : v.type + ":tmp-" + uuid();
      const objet = Object.assign({}, v, corps, { cle: e ? e.cle : cle.split(":")[1], version: e ? e.version : 0 });
      await mettreEnFile("rell/catalogue/element", corps, { genre: "element", cle, resume: (e ? "Catalogue modifié : " : "Catalogue, ajout : ") + corps.nom, objet });
      p.fermer();
      toast(enLigne() ? "Catalogue mis à jour." : "Gardé sur l'appareil : envoyé au retour de la connexion.", "succes");
      emettre("jeu", { nom: "catalogue" });
    } })]);
}
function televerser(fin) {
  const entree = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" });
  entree.addEventListener("change", async () => {
    const f = entree.files && entree.files[0];
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) { toast("8 Mo au plus.", "erreur"); return; }
    const b64 = await new Promise((ok, ko) => { const l = new FileReader(); l.onload = () => ok(String(l.result).split(",")[1] || ""); l.onerror = ko; l.readAsDataURL(f); });
    const r = await poster("media", { nom: f.name.slice(0, 80), type: f.type, base64: b64 });
    if (r.ok && r.donnees && r.donnees.id) { fin(r.donnees.id); toast("Image ajoutée.", "succes"); } else toast(r.erreur || "Image refusée.", "erreur");
  });
  entree.click();
}
async function gererTypes() {
  const cat = await charger("catalogue");
  const p = pancarte({ titre: "Les types du catalogue", sous: "Métiers, races, factions… : l'ordre est celui des insignes sur les affiches.", icone: "filtrer", taille: "large" });
  const zone = h("div", { classe: "registre" });
  const ligne = (t) => {
    const nom = saisie({ value: t.nom || "", maxlength: 60, "aria-label": "Nom" });
    const en = saisie({ value: t.nom_en || "", maxlength: 60, "aria-label": "Nom en anglais", placeholder: "English" });
    const ordre = h("input", { type: "number", classe: "saisie", value: t.ordre || 0, min: 0, max: 999, "aria-label": "Ordre" });
    let multiple = !!t.multiple;
    return h("div", { classe: "registre-ligne", vars: { "--colonnes": "minmax(0, 1.4fr) minmax(0, 1.2fr) 90px auto auto" } },
      nom, en, ordre, interrupteur("Plusieurs", multiple, (x) => { multiple = x; }),
      bouton("Enregistrer", { classe: "p", icone: "valider", onclick: async () => {
        if (!nom.value.trim()) { toast("Le nom est obligatoire.", "erreur"); return; }
        const corps = { cle: t.cle || undefined, nom: nom.value.trim(), nom_en: en.value.trim(), multiple, ordre: Number(ordre.value) || 0, version: t.version };
        const cle = t.cle || "tmp-" + uuid();
        await mettreEnFile("rell/catalogue/type", corps, { genre: "type", cle, resume: "Type du catalogue : " + corps.nom, objet: Object.assign({}, t, corps, { cle: t.cle || cle, champ: t.champ || cle }) });
        toast("Type enregistré.", "succes");
        emettre("jeu", { nom: "catalogue" });
      } }));
  };
  remplacer(zone, h("div", { classe: "registre-ligne entete-registre", vars: { "--colonnes": "minmax(0, 1.4fr) minmax(0, 1.2fr) 90px auto auto" } }, h("span", {}, "Nom"), h("span", {}, "En anglais"), h("span", {}, "Ordre"), h("span", {}, "Choix"), h("span", {})),
    ...typesTries(cat).map(ligne), ligne({ nom: "", nom_en: "", ordre: (typesTries(cat).length + 1), multiple: false }));
  ajouter(p.corps, [zone]);
  ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
}

// ═══ LES RÔLES DES MÉTIERS ══════════════════════════════════════════════
// Les métiers deviennent des rôles Discord (créés au premier choix, donnés, retirés quand le métier part) ; un membre
// qui quitte le clan perd tous les rôles du clan (métiers + rôles rattachés). Rien de tout cela n'attend hors ligne :
// ça change tout de suite sur Discord.
const LIBELLES_BILAN = { crees: ["rôle créé", "rôles créés"], lies: ["rôle lié", "rôles liés"], donnes: ["rôle donné", "rôles donnés"],
  rendus: ["rôle rendu", "rôles rendus"], retires: ["rôle retiré", "rôles retirés"], verifies: ["membre vérifié", "membres vérifiés"],
  membres: ["membre vérifié", "membres vérifiés"], ignores: ["ignoré", "ignorés"], erreurs: ["erreur", "erreurs"], deja: ["déjà en place", "déjà en place"] };
/** Le bilan d'une action sur les rôles, lisible : les comptes d'abord ; le message du serveur seulement s'il dit
 *  autre chose qu'un compte (une permission manquante, par exemple). */
function bilanLisible(d) {
  if (!d || typeof d !== "object") return "C'est fait.";
  const b = d.bilan && typeof d.bilan === "object" ? d.bilan : d;
  const morceaux = [];
  for (const [k, v] of Object.entries(b)) {
    if (["ok", "message", "bilan"].includes(k)) continue;
    const n = Array.isArray(v) ? v.length : typeof v === "number" ? v : null;
    if (n === null) continue;
    const lib = LIBELLES_BILAN[k] || [k.replace(/_/g, " "), k.replace(/_/g, " ")];
    morceaux.push(compte(n, lib[0], lib[1]));
  }
  const message = String(d.message || b.message || "").trim();
  if (!morceaux.length) return message || "Rien à changer : tout était en place.";
  return morceaux.join(" · ") + (message && !/\d/.test(message) ? ". " + message : ".");
}

export function roles(vue) {
  const zone = h("div", { classe: "pile" }, squelettes(3));
  ajouter(vue, [zone]);
  let dernierBilan = null;
  const maj = async (forcer) => {
    const [cat, R, M, aff] = [await charger("catalogue"), await charger("roles", { forcer }), await charger("metiers_reglages", { forcer }), await charger("affiches")];
    if (!zone.isConnected) return;
    if (!R || R.erreur || !cat || cat.erreur) { remplacer(zone, vide("Rôles indisponibles", (R && R.erreur) || (cat && cat.erreur), "hors_ligne")); return; }
    const liens = R.liens || [];
    const rolesD = ((M && !M.erreur && M.roles_disponibles) || R.roles || []).slice().sort((a, b) => (b.position || 0) - (a.position || 0));
    const tm = typeMetier(cat);
    const types = typesTries(cat);
    const lienDe = (t, c) => liens.find((l) => l.type === t && l.cle === c);
    const { actives } = rangerAffiches(aff && !aff.erreur ? aff : {});
    const nbMembres = (t, c) => actives.filter((a) => ((a.attributs || {})[t] || []).includes(c)).length;
    const blocType = (t) => {
      const els = elementsDe(cat, t.cle).filter((e) => e.actif !== false);
      const lies = els.filter((e) => lienDe(t.cle, e.cle)).length;
      const contenu = () => h("div", { classe: "registre roles-registre" },
        h("div", { classe: "registre-ligne entete-registre" }, h("span", {}, sansEmoji(t.nom)), h("span", {}, "Rôle Discord"), h("span", {}, "Membres"), h("span", {})),
        els.map((e) => ligneRole(t, e, lienDe(t.cle, e.cle), rolesD, nbMembres(t.cle, e.cle), t === tm && !!M && !M.erreur && M.auto !== false, () => maj(true))));
      return t === tm ? section(sansEmoji(t.nom), "roles", compte(lies, "rôle", "rôles") + " sur " + compte(els.length, "métier", "métiers"), contenu())
        : groupe({ titre: sansEmoji(t.nom), compte: lies, info: compte(lies, "lié", "liés") + " sur " + nombre(els.length), cle: "roles-" + t.cle }, contenu);
    };
    remplacer(zone,
      h("p", { classe: "aide" }, "Chaque métier a son rôle Discord : il est créé au premier membre qui choisit ce métier, donné à ceux qui l'ont, retiré à ceux qui ne l'ont plus. Quand quelqu'un quitte le clan, il perd tous les rôles du clan : ses métiers et les rôles rattachés ci-dessous. Tout est noté au journal."),
      !enLigne() ? bandeau("Hors ligne : les rôles se règlent avec la connexion (ils changent tout de suite sur Discord).", "") : null,
      blocReglagesMetiers(M, rolesD, (b) => { dernierBilan = b; maj(true); }),
      dernierBilan ? bandeau(dernierBilan, "vert") : null,
      tm ? blocType(tm) : vide("Pas de type « Métiers » dans le catalogue", "Ajoute-le dans Catalogue RELL Seas, « Les types »."),
      ...types.filter((t) => t !== tm).map(blocType));
    majBoutonsReseau(zone);
  };
  maj();
  return { maj: () => maj(false), majJeu: () => maj(false) };
}

/** Les réglages des rôles de métier (jamais hors ligne). */
function blocReglagesMetiers(M, rolesD, apres) {
  if (!M || M.erreur) return bandeau("Les réglages des rôles de métier sont indisponibles pour le moment" + (M && M.erreur ? " : " + M.erreur : "."), "");
  const v = { auto: M.auto !== false, max_metiers: Math.max(1, Math.min(5, Number(M.max_metiers) || 2)), rattaches: new Set((M.rattaches || []).map(String)) };
  const initial = JSON.stringify({ a: v.auto, m: v.max_metiers, r: [...v.rattaches].sort() });
  const enregistrer = bouton("Enregistrer les réglages", { classe: "p principal", icone: "valider", reseau: true });
  const sale = () => JSON.stringify({ a: v.auto, m: v.max_metiers, r: [...v.rattaches].sort() }) !== initial;
  const etat_ = () => { if (enLigne()) enregistrer.disabled = !sale(); };
  const nombreE = h("input", { type: "number", classe: "saisie", min: 1, max: 5, value: v.max_metiers, inputmode: "numeric", "aria-label": "Nombre de métiers par membre" });
  nombreE.addEventListener("input", () => { v.max_metiers = Math.max(1, Math.min(5, Number(nombreE.value) || 1)); etat_(); });
  const pas = (d) => () => { v.max_metiers = Math.max(1, Math.min(5, v.max_metiers + d)); nombreE.value = v.max_metiers; etat_(); };
  // Les rôles des métiers partent déjà avec le clan : ils ne se « rattachent » pas (sauf s'ils l'étaient déjà, pour les décocher).
  const rolesMetiers = new Set((M.metiers || []).map((m) => m.role && m.role.id).filter(Boolean).map(String));
  const candidats = rolesD.filter((r) => !/^@?everyone$/i.test(r.nom || "") && (!rolesMetiers.has(String(r.id)) || v.rattaches.has(String(r.id))));
  const grille = h("div", { classe: "roles-rattaches" }, candidats.map((r) => caseACocher(h("span", { classe: "role-nom" }, h("i", { classe: "pastille-couleur", vars: { "--teinte": r.couleur || "#6e553f" } }), sansEmoji(r.nom) || "Rôle"),
    v.rattaches.has(String(r.id)), (x) => { if (x) v.rattaches.add(String(r.id)); else v.rattaches.delete(String(r.id)); etat_(); })));
  enregistrer.addEventListener("click", async () => {
    const r = await poster("rell/metiers/reglages", { auto: v.auto, max_metiers: v.max_metiers, rattaches: [...v.rattaches] });
    toast(r.ok ? "Réglages des rôles enregistrés." : r.erreur, r.ok ? "succes" : "erreur");
    if (r.ok) apres(null);
  });
  const action = (libelle, icone_, route, question, texte, titreBilan) => bouton(libelle, { classe: "p", icone: icone_, reseau: true, onclick: async () => {
    const ok = await confirmer({ titre: question, texte, libelleOk: libelle, icone: "roles" });
    if (!ok) return;
    const r = await poster(route, {});
    if (!r.ok) { toast(r.erreur || "Impossible pour le moment.", "erreur"); return; }
    const b = bilanLisible(r.donnees);
    toast(titreBilan + " : " + b, "succes");
    apres(titreBilan + " : " + b);
  } });
  etat_();
  // Ce que le serveur sait et que la personne doit voir avant de toucher aux rôles.
  const alertes = [];
  if (M.actif === false) alertes.push(bandeau("Le rôle du clan n'est pas réglé : les rôles de métier sont en sommeil (rien n'est créé, donné ni retiré). Règle-le dans la configuration du bot.", "rouge"));
  if (M.gestion === false) alertes.push(bandeau("Le bot n'a pas la permission « Gérer les rôles » : il ne peut ni créer ni donner les rôles de métier.", "rouge"));
  const details = new Map((M.rattaches_details || []).map((d) => [String(d.id), d]));
  const avisRattaches = [...v.rattaches].map((id) => details.get(id)).filter(Boolean).map((d) => !d.existe
    ? h("p", { classe: "meta alerte-texte" }, "Un rôle rattaché n'existe plus sur le serveur : décoche-le.")
    : !d.attribuable ? h("p", { classe: "meta alerte-texte" }, "« " + sansEmoji(d.nom) + " » : " + (d.raison || "le bot ne peut pas le retirer."))
      : d.non_membres ? h("p", { classe: "meta alerte-texte" }, "« " + sansEmoji(d.nom) + " » : " + compte(d.non_membres, "personne hors du clan l'a", "personnes hors du clan l'ont") + " — " + (d.non_membres > 1 ? "elles le perdront" : "elle le perdra") + " à la prochaine vérification.")
        : null).filter(Boolean);
  const derniere = M.derniere_reconciliation && M.derniere_reconciliation.quand ? M.derniere_reconciliation : null;
  return h("div", { classe: "cadre pile serree" }, h("h3", {}, "Les réglages"),
    ...alertes,
    interrupteur("Attribution automatique des rôles de métier", v.auto, (x) => { v.auto = x; etat_(); }),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Nombre de métiers par membre"),
      h("div", { classe: "pas-a-pas" }, boutonIcone("moins", "Un de moins", pas(-1)), nombreE, boutonIcone("plus", "Un de plus", pas(1))),
      h("span", { classe: "champ-aide" }, "De 1 à 5. L'atelier des affiches n'en laisse pas choisir davantage.")),
    h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Rôles rattachés au clan"),
      h("span", { classe: "champ-aide" }, "Coche les rôles qui partent avec le clan : quand quelqu'un quitte le clan, ils lui sont retirés en même temps que ses métiers."),
      candidats.length ? grille : h("p", { classe: "aide" }, "Aucun rôle attribuable trouvé."), ...avisRattaches),
    h("p", { classe: "meta" }, icone(M.icones_roles ? "succes" : "info", "ic-p"), M.icones_roles
      ? " Ce serveur peut afficher une icône sur les rôles : chaque rôle de métier prend l'icône officielle de son métier."
      : " Ce serveur ne peut pas encore afficher d'icône sur les rôles (il faut le niveau 2 de boost) : les rôles de métier n'ont que leur couleur."),
    derniere ? h("p", { classe: "meta" }, icone("synchro", "ic-p"), " Dernière vérification " + depuis(derniere.quand) + " : " + compte(derniere.verifies || derniere.membres || 0, "membre vérifié", "membres vérifiés")
      + (derniere.rendus ? " · " + compte(derniere.rendus, "rôle rendu", "rôles rendus") : "") + (derniere.retires ? " · " + compte(derniere.retires, "rôle retiré", "rôles retirés") : "")
      + (derniere.erreurs ? " · " + compte(derniere.erreurs, "erreur", "erreurs") : "") + ". Elle repasse toute seule toutes les 30 minutes.") : null,
    h("div", { classe: "rangee" }, enregistrer,
      action("Créer les rôles manquants", "ajouter", "rell/metiers/installer", "Créer les rôles manquants ?",
        "Un rôle est créé pour chaque métier qui n'en a pas encore" + (v.auto ? ", puis donné à ceux qui ont ce métier (attribution automatique)." : ". L'attribution automatique est coupée : personne ne le reçoit pour l'instant."), "Rôles des métiers"),
      action("Vérifier maintenant", "synchro", "rell/metiers/reconcilier", "Vérifier tous les rôles maintenant ?",
        "Chaque membre est comparé à son affiche : les rôles en trop sont retirés (métiers abandonnés, départs du clan)" + (v.auto ? " et les rôles manquants rendus." : ". L'attribution automatique est coupée : les rôles manquants ne sont pas rendus."), "Vérification")));
}

function ligneRole(t, e, lien, rolesD, nbMembres, autoMetiers, recharger) {
  let roleId = lien ? String(lien.role_id) : "";
  const auto = lien ? !!lien.auto : autoMetiers;
  const options = [{ v: "", l: autoMetiers ? "Créé au premier choix" : "Aucun rôle" }, ...rolesD.map((r) => ({ v: String(r.id), l: sansEmoji(r.nom) || "Rôle", teinte: r.couleur || null }))];
  const enregistrer = bouton("Enregistrer", { classe: "p", icone: "valider", reseau: true });
  // « Enregistrer » n'apparaît qu'une fois le rôle changé : une ligne au repos ne montre que l'essentiel.
  const etatBouton = () => { const change = roleId !== (lien ? String(lien.role_id) : ""); enregistrer.hidden = !change; enregistrer.disabled = !enLigne() || !change; };
  const choix = liste({ valeur: roleId, label: "Rôle de " + e.nom, cacherLabel: true, plein: true, options, changer: (v) => { roleId = v; etatBouton(); } });
  enregistrer.addEventListener("click", async () => {
    const corps = roleId ? { type: t.cle, cle: e.cle, role_id: roleId, auto } : { type: t.cle, cle: e.cle, retirer: true };
    const r = await poster("rell/role", corps);
    toast(r.ok ? (roleId ? "Rôle lié à « " + e.nom + " »." : "Lien retiré.") : r.erreur, r.ok ? "succes" : "erreur");
    if (r.ok) recharger();
  });
  const creer = bouton("Créer le rôle…", { classe: "p discret", icone: "ajouter", reseau: true, onclick: async () => {
    let couleur = "#a8823f";
    const nom = saisie({ value: e.nom, maxlength: 100 });
    const nuancier = h("div", { classe: "nuancier" }, ["#a8823f", "#8e2a24", "#1f4e5a", "#3f6b3a", "#a8641c", "#5e3a4e", "#4a5560", "#7a4b2a"].map((c) => {
      const b = h("button", { classe: "nuance", type: "button", role: "radio", "aria-checked": String(c === couleur), vars: { "--teinte": c }, "aria-label": "Couleur " + c, onclick: () => { couleur = c; for (const x of nuancier.children) x.setAttribute("aria-checked", String(x === b)); } });
      return b;
    }));
    const ok = await confirmer({ titre: "Créer le rôle de « " + e.nom + " »", icone: "roles", libelleOk: "Créer le rôle", contenu: [champ("Nom du rôle", nom), h("div", { classe: "champ" }, h("span", { classe: "champ-lib" }, "Couleur"), nuancier)] });
    if (!ok) return;
    const r = await poster("rell/role", { type: t.cle, cle: e.cle, creer: { nom: nom.value.trim() || e.nom, couleur }, auto: true });
    toast(r.ok ? (autoMetiers ? "Rôle créé, lié, et donné à ceux qui ont ce métier." : "Rôle créé et lié : il sera donné à l'enregistrement de chaque affiche concernée, ou avec « Appliquer les rôles ».") : r.erreur, r.ok ? "succes" : "erreur");
    if (r.ok) recharger();
  } });
  etatBouton();
  ecouter("reseau", etatBouton);
  const roleLie = lien ? h("span", { classe: "role-lie" }, h("i", { classe: "pastille-couleur", vars: { "--teinte": lien.couleur || "#6e553f" } }), sansEmoji(lien.role_nom || "") || "rôle")
    : h("span", { classe: "role-lie a-venir" }, autoMetiers ? "sera créé au premier choix" : "aucun rôle");
  return h("div", { classe: "registre-ligne" },
    h("div", { classe: "qui" }, insigneImage(e, "element-icone petit"), h("div", { classe: "bloc" }, h("b", {}, e.nom), roleLie)),
    choix,
    h("span", { classe: "num role-membres" }, nombre(nbMembres), h("span", { classe: "meta" }, nbMembres > 1 ? " membres" : " membre")),
    h("div", { classe: "rangee" }, enregistrer, lien ? null : creer));
}
