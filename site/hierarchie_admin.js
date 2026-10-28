// hierarchie_admin.js — la HIÉRARCHIE côté direction (27/10/2026), dans « L'Équipage › Équipage › Hiérarchie » :
// l'organigramme (hierarchie.js) avec ses boutons — modifier un rang (nom, insigne, couleur, phrase, rôle Discord),
// l'ajouter, le déplacer, le retirer ; nommer des membres ; relier les anciens grades des affiches. Et la ligne
// « Rang : … » de la fiche d'un membre, avec « Changer le rang ». Tout s'écrit par la tête seule, sur le serveur
// (`equipage/hierarchie/…` : version vérifiée, verrous de la présence en direct, journal du site).

import { h, icone, ajouter, remplacer, sansEmoji, contient, quantite } from "./dom.js";
import { etat, peutAgir, ecouter, emettre } from "./noyau.js";
import { lire, poster } from "./api.js";
import { bouton, boutonIcone, pancarte, confirmer, toast, vide, liste, recherche, champ, saisie, nomDe, avatar, groupe, bandeau, squelettes } from "./ui.js";
import { protegerEditeur, siLibre } from "./direct.js";
import { organigramme, sceauRang, pastilleRang, L } from "./hierarchie.js";
import { ouvrirFiche } from "./fiche.js";

let cache = null, cacheT = 0, enCours = null;
const SOURCES = { role: "par son rôle Discord", reprise: "repris de son affiche", site: "", defaut: "", tete: "suit la direction du site" };

/** La hiérarchie (`GET equipage/hierarchie`), gardée 20 s ; `forcer` : relue. */
export async function lireHierarchie(forcer) {
  if (!forcer && cache && Date.now() - cacheT < 20000) return cache;
  if (!enCours) {
    enCours = lire("equipage/hierarchie").then((r) => { if (r.ok && r.donnees && Array.isArray(r.donnees.rangs)) accepter(r.donnees); return r.ok ? cache : null; })
      .finally(() => { enCours = null; });
  }
  return enCours;
}
function accepter(d) {
  if (d && Array.isArray(d.rangs)) { cache = d; cacheT = Date.now(); emettre("hierarchie", d); }
}
const rangParId = (d, id) => ((d && d.rangs) || []).find((r) => r.id === id) || null;
const defautDe = (d) => ((d && d.rangs) || []).find((r) => r.verrou === "defaut") || null;
/** La pastille du rang d'un membre (lignes du clan) — rien pour le rang par défaut, ni avant la première lecture. */
export function pastilleRangMembre(id) {
  const x = cache && cache.membres && cache.membres[String(id)];
  const r = x ? rangParId(cache, x.rang) : null;
  return r && r.verrou !== "defaut" ? pastilleRang(r, "Rang : " + sansEmoji(r.nom)) : null;
}
/** Le rang (identifiant) d'un membre, s'il est lu — ou "". */
export const rangDuMembre = (id) => (cache && cache.membres && cache.membres[String(id)] ? cache.membres[String(id)].rang : "");
export const rangsLus = () => (cache && cache.rangs) || [];

// ─── La vue « Hiérarchie » ──────────────────────────────────────────────────
/** La vue dans `zone`. o.q() : la recherche de la rubrique. Rend { maj, chercher }. */
export function vueHierarchie(zone, o = {}) {
  remplacer(zone, squelettes(3));
  const dessiner = (d) => {
    if (!zone.isConnected) return;
    if (!d) { remplacer(zone, vide("Hiérarchie indisponible", "Réessaie dans un instant.", "hors_ligne")); return; }
    const q = (o.q && o.q()) || "";
    const n = d.rangs.length;
    const inter = d.rangs.filter((r) => !r.verrou);
    const outils = (r) => {
      if (!peutAgir()) return [];
      const i = inter.indexOf(r);
      return [bouton("Modifier", { classe: "p discret", icone: "modifier", onclick: () => editerRang(r) }),
        !r.verrou ? bouton("Nommer", { classe: "p", icone: "ajouter", titre: "Nommer des membres à ce rang", onclick: () => nommerMembres(r) }) : null,
        !r.verrou ? inactif(boutonIcone("haut", "Monter ce rang", () => deplacer(r, "haut")), i <= 0) : null,
        !r.verrou ? inactif(boutonIcone("bas", "Descendre ce rang", () => deplacer(r, "bas")), i >= inter.length - 1) : null];
    };
    const personne = (m) => {
      const x = d.membres[m.id] || {};
      return { nom: m.nom, src: m.avatar, sous: SOURCES[x.source] || "", clic: () => ouvrirFiche(m.id), aria: "Ouvrir la fiche de " + m.nom };
    };
    const aRelier = (d.reprise || []).filter((x) => !x.rang && x.n);
    remplacer(zone,
      h("div", { classe: "rangee entre" }, h("p", { classe: "aide" }, quantite(n, "rang(s)") + " · le Capitaine et le Second suivent la direction du site ; chaque membre du clan sans autre rang est " + sansEmoji((defautDe(d) || { nom: "au rang d'arrivée" }).nom) + "."),
        peutAgir() ? bouton("Ajouter un rang", { classe: "p", icone: "ajouter", onclick: () => editerRang(null) }) : null),
      !d.gestion ? bandeau("Le bot n'a pas la permission « Gérer les rôles » : les rôles Discord des rangs ne se donnent pas.", "rouge") : null,
      aRelier.length && peutAgir() ? bandeau(quantite(aRelier.length, "ancien(s) grade(s)") + " des affiches à relier à un rang (en bas de la page).", "") : null,
      organigramme(d.rangs, { personne, outils, cle: "adm-hie", filtre: q ? (p) => contient(p.nom, q) : null }),
      (d.reprise || []).length ? groupe({ titre: "Les anciens grades des affiches", icone: "parchemin", compte: d.reprise.length, chaud: aRelier.length > 0,
        cle: "adm-hie-reprise", defaut: aRelier.length > 0 }, () => reprise(d)) : null);
  };
  const maj = async (forcer) => dessiner(await lireHierarchie(forcer));
  maj(true);
  const fin = ecouter("hierarchie", (d) => { if (zone.isConnected) dessiner(d); else fin(); });
  return { maj: () => maj(true), chercher: () => dessiner(cache) };
}
const inactif = (b, oui) => { b.disabled = !!oui; return b; };

async function ecrire(api, corps, reussi) {
  const r = await poster(api, corps);
  if (r.ok) { accepter(r.donnees); if (reussi) toast(reussi + (r.donnees && r.donnees.message ? " " + r.donnees.message : ""), "succes"); return r; }
  toast(r.erreur || "Refusé.", "erreur");
  return r;
}
async function deplacer(r, sens) {
  if (!siLibre("rang:" + r.id)) return;
  await ecrire("equipage/hierarchie/rang/deplacer", { id: r.id, sens });
}

// ─── L'éditeur d'un rang ────────────────────────────────────────────────────
/** Ajouter (`r` absent) ou modifier un rang : nom, insigne, couleur, phrase ; son rôle Discord (déjà enregistré). */
export async function editerRang(r) {
  if (r && !siLibre("rang:" + r.id)) return;
  const d = (await lireHierarchie()) || { insignes: [], couleurs: [], roles: [], rangs: [] };
  const v = { nom: r ? r.nom : "", insigne: r ? r.insigne : "etoile", couleur: r ? r.couleur : (d.couleurs || ["#7a5a22"])[0], phrase: r ? r.phrase : "" };
  const p = pancarte({ titre: r ? sansEmoji(r.nom) : "Nouveau rang", sous: r && r.verrou ? "Rang verrouillé : il se renomme, il garde sa place." : "Son nom, son insigne, sa couleur.", icone: "grade", taille: "large" });
  if (r) {
    protegerEditeur(p, "rang:" + r.id, "le rang « " + sansEmoji(r.nom).slice(0, 60) + " »", { relire: async () => {
      const frais = rangParId(await lireHierarchie(true), r.id);
      if (!frais) throw new Error("rang retiré");
      editerRang(frais);
    } });
  }
  const apercu = h("div", { classe: "rang-apercu" });
  const majApercu = () => remplacer(apercu, sceauRang(v, "grand"), h("b", {}, sansEmoji(v.nom) || "Nom du rang"));
  const nomI = saisie({ value: v.nom, maxlength: 40, placeholder: "Quartier-maître" });
  nomI.addEventListener("input", () => { v.nom = nomI.value; majApercu(); });
  const phraseI = saisie({ value: v.phrase, maxlength: 140, placeholder: "Une phrase courte (facultative)" });
  phraseI.addEventListener("input", () => { v.phrase = phraseI.value; });
  const choix = (nom, valeurs, rendu, cle, legende) => h("fieldset", { classe: "rang-choix " + cle }, h("legend", { classe: "champ-lib" }, legende),
    valeurs.map((x) => {
      const i = h("input", { type: "radio", name: nom, value: x, "aria-label": x });
      i.checked = v[cle] === x;
      i.addEventListener("change", () => { if (i.checked) { v[cle] = x; majApercu(); } });
      return h("label", { classe: "rang-option", title: x }, i, rendu(x));
    }));
  ajouter(p.corps, [apercu, champ("Nom du rang", nomI),
    choix("rang-insigne", d.insignes || [], (x) => icone(x), "insigne", "L'insigne"),
    choix("rang-couleur", d.couleurs || [], (x) => h("span", { classe: "rang-goutte", vars: { "--teinte": x } }), "couleur", "La couleur"),
    champ("La phrase", phraseI, { optionnel: true }), r ? zoneRole(r, d, p) : h("p", { classe: "aide" }, "Le rôle Discord se lie une fois le rang créé.")]);
  majApercu();
  const enregistrerB = bouton(r ? "Enregistrer le rang" : "Ajouter le rang", { classe: "principal", icone: "valider", reseau: true, onclick: async () => {
    if (!v.nom.trim()) { toast("Donne un nom au rang.", "erreur"); nomI.focus(); return; }
    enregistrerB.disabled = true;
    const corps = Object.assign({ nom: v.nom.trim(), insigne: v.insigne, couleur: v.couleur, phrase: v.phrase.trim() }, r ? { id: r.id, version: r.version } : {});
    const res = await ecrire("equipage/hierarchie/rang", corps, r ? "Rang enregistré." : "Rang ajouté.");
    enregistrerB.disabled = false;
    if (res.ok) { p.fermer(); return; }
    if (res.status === 409) { p.fermer(); const frais = rangParId(await lireHierarchie(true), r.id); if (frais) editerRang(frais); }
  } });
  ajouter(p.pied, [r && !r.verrou ? bouton("Retirer", { classe: "discret danger", icone: "supprimer", onclick: () => retirer(r, p) }) : null,
    bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), enregistrerB]);
  setTimeout(() => nomI.focus(), 60);
}

async function retirer(r, p) {
  const ok = await confirmer({ titre: "Retirer le rang « " + sansEmoji(r.nom) + " » ?", style: "danger", libelleOk: "Retirer",
    texte: "Ses membres reviennent au rang d'arrivée. Son rôle Discord, s'il en a un, reste sur Discord." });
  if (!ok) return;
  const res = await ecrire("equipage/hierarchie/rang/supprimer", { id: r.id }, "Rang retiré.");
  if (res.ok) p.fermer();
}

/** Le rôle Discord du rang : lié (le délier), ou à lier (un rôle existant, ou le créer). */
function zoneRole(r, d, p) {
  const z = h("div", { classe: "cadre pile serree rang-role" }, h("h3", { classe: "champ-lib" }, "Le rôle Discord (facultatif)"));
  const verrouille = !!r.verrou;
  if (verrouille) ajouter(z, [h("p", { classe: "aide" }, "Le bot ne donne ni ne retire jamais ce rôle : il est seulement montré avec le rang.")]);
  else ajouter(z, [h("p", { classe: "aide" }, "Nommer un membre à ce rang lui donne ce rôle et retire ses autres rôles de rang ; qui a ce rôle sur Discord a ce rang.")]);
  if (r.role) {
    ajouter(z, [h("p", {}, "Lié à ", h("b", {}, r.role.existe ? "@" + sansEmoji(r.role.nom) : "un rôle supprimé"), r.role.raison ? " · " + r.role.raison : ""),
      bouton("Délier le rôle", { classe: "p discret", icone: "fermer", reseau: true, onclick: async () => {
        const res = await ecrire("equipage/hierarchie/rang/role", { id: r.id, retirer: true }, "Rôle délié : il reste sur Discord.");
        if (res.ok) p.fermer();
      } })]);
    return z;
  }
  const autres = new Map((d.rangs || []).filter((x) => x.role && x.id !== r.id).map((x) => [x.role.id, x.nom]));
  const options = (d.roles || []).map((x) => {
    const raison = x.refus || (autres.has(x.id) ? "déjà celui du rang « " + autres.get(x.id) + " »" : "")
      || (!verrouille && x.clan ? "le rôle du clan" : "") || (!verrouille && x.au_dessus ? "au-dessus du bot" : "");
    return { v: x.id, l: sansEmoji(x.nom) || "Rôle", sous: raison || quantite(x.porteurs || 0, "porteur(s)"), desactive: !!raison, teinte: x.couleur || null };
  });
  let choisi = "";
  const l = liste({ valeur: "", options: [{ v: "", l: "Choisir un rôle…" }, ...options], label: "Un rôle existant", plein: true, changer: (x) => { choisi = x; } });
  ajouter(z, [l, h("div", { classe: "rangee" },
    bouton("Lier ce rôle", { classe: "p", icone: "lien", reseau: true, onclick: async () => {
      if (!choisi) { toast("Choisis d'abord un rôle.", "erreur"); return; }
      const res = await ecrire("equipage/hierarchie/rang/role", { id: r.id, role_id: choisi }, "Rôle lié.");
      if (res.ok) p.fermer();
    } }),
    bouton("Créer le rôle « " + sansEmoji(r.nom) + " »", { classe: "p discret", icone: "ajouter", reseau: true, onclick: async () => {
      const res = await ecrire("equipage/hierarchie/rang/role", { id: r.id, creer: true }, "Rôle créé et lié.");
      if (res.ok) p.fermer();
    } }))]);
  return z;
}

// ─── Nommer des membres ─────────────────────────────────────────────────────
/** Les membres du clan, cochés s'ils ont ce rang : cocher nomme, décocher renvoie au rang d'arrivée. */
export async function nommerMembres(r) {
  const d = await lireHierarchie(true);
  if (!d) { toast("Hiérarchie indisponible.", "erreur"); return; }
  const tete = new Set([...(d.tete.capitaines || []), ...(d.tete.seconds || [])]);
  const clan = ((etat.d && etat.d.clan && etat.d.clan.membres) || []).filter((m) => !tete.has(String(m.id)));
  const avant = new Set(clan.filter((m) => (d.membres[String(m.id)] || {}).rang === r.id).map((m) => String(m.id)));
  const choisis = new Set(avant);
  const p = pancarte({ titre: "Nommer · " + sansEmoji(r.nom), sous: "Coche ceux qui ont ce rang ; décoche pour les renvoyer au rang d'arrivée.", icone: "grade", taille: "large" });
  let q = "";
  const zone = h("div", { classe: "pile serree" });
  const dessiner = () => {
    const l = clan.filter((m) => contient(nomDe(m) + " " + (m.pseudo || "") + " " + m.id, q))
      .sort((a, b) => (choisis.has(String(b.id)) - choisis.has(String(a.id))) || nomDe(a).localeCompare(nomDe(b), "fr", { sensitivity: "base" }));
    remplacer(zone, h("p", { classe: "aide" }, quantite(choisis.size, "membre(s) à ce rang")),
      h("ol", { classe: "selection-liste choix-equipe", "aria-label": "Les membres du clan" }, l.slice(0, 200).map((m) => {
        const id = String(m.id);
        const c = h("input", { type: "checkbox", value: id });
        c.checked = choisis.has(id);
        c.addEventListener("change", () => { if (c.checked) choisis.add(id); else choisis.delete(id); dessiner(); });
        const actuel = rangParId(d, (d.membres[id] || {}).rang);
        return h("li", {}, h("label", { classe: "selection-item" + (c.checked ? " choisie" : "") }, c,
          h("span", { classe: "choix-personne" }, avatar(m, "p"), h("span", { classe: "choix-personne-texte" }, h("b", {}, nomDe(m)),
            actuel && actuel.id !== r.id ? h("small", {}, "aujourd'hui : " + sansEmoji(actuel.nom)) : null))));
      })));
  };
  ajouter(p.corps, [recherche("", "Chercher un membre du clan…", (x) => { q = x; dessiner(); }, { nom: "chercher-nommer" }), zone]);
  dessiner();
  const ok = bouton("Enregistrer", { classe: "principal", icone: "valider", reseau: true, onclick: async () => {
    const def = defautDe(d);
    const version = (id) => (d.membres[id] || {}).version || 0;
    const aff = [...choisis].filter((id) => !avant.has(id)).map((id) => ({ membre: id, rang: r.id, version: version(id) }))
      .concat([...avant].filter((id) => !choisis.has(id) && def).map((id) => ({ membre: id, rang: def.id, version: version(id) })));
    if (!aff.length) { p.fermer(); return; }
    ok.disabled = true;
    let faits = 0;
    const refus = [];
    for (let i = 0; i < aff.length; i += (d.lot || 25)) {
      const res = await poster("equipage/hierarchie/attribuer", { affectations: aff.slice(i, i + (d.lot || 25)) });
      if (res.ok) { accepter(res.donnees); faits += (res.donnees.faits || []).length; refus.push(...(res.donnees.refus || [])); }
      else { refus.push({ nom: "", raison: res.erreur || "Refusé." }); break; }
    }
    ok.disabled = false;
    if (faits) toast(quantite(faits, "membre(s)") + " à jour.", "succes");
    if (refus.length) toast(refus.slice(0, 2).map((x) => (x.nom ? x.nom + " : " : "") + x.raison).join(" · "), "erreur");
    if (faits || !refus.length) p.fermer();
  } });
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), ok]);
}

/** Changer le rang d'UN membre (sa fiche) : les rangs dans l'ordre, le Capitaine et le Second à part. */
export async function changerRang(id, nom) {
  if (!siLibre("rang-membre:" + id)) return;
  const d = await lireHierarchie(true);
  const x = d && d.membres[String(id)];
  if (!x) { toast("Ce membre n'est pas dans le clan.", "erreur"); return; }
  let choisi = x.rang;
  const p = pancarte({ titre: "Rang de " + sansEmoji(nom), sous: "Le rôle Discord du rang lui est donné ; ses autres rôles de rang lui sont retirés.", icone: "grade", taille: "etroite" });
  protegerEditeur(p, "rang-membre:" + id, "le rang de " + sansEmoji(nom).slice(0, 60), { relire: () => changerRang(id, nom) });
  ajouter(p.corps, [h("fieldset", { classe: "choix-groupe rang-liste" }, h("legend", { classe: "sr" }, "Son rang"), d.rangs.map((r) => {
    const tete = r.verrou === "capitaine" || r.verrou === "second";
    const i = h("input", { type: "radio", name: "rang-membre", value: r.id, disabled: tete ? true : null });
    i.checked = r.id === x.rang;
    i.addEventListener("change", () => { if (i.checked) choisi = r.id; });
    return h("label", { classe: "radio rang-radio" + (tete ? " inactif" : "") }, i, h("span", { classe: "radio-rond", "aria-hidden": "true" }),
      sceauRang(r), h("span", { classe: "case-texte" }, sansEmoji(r.nom), tete ? h("span", { classe: "option-sous" }, " — suit la direction du site") : null,
        r.role && r.role.existe && !r.verrou ? h("span", { classe: "option-sous" }, " · @" + sansEmoji(r.role.nom)) : null));
  }))]);
  const ok = bouton("Enregistrer", { classe: "principal", icone: "valider", reseau: true, onclick: async () => {
    if (choisi === x.rang) { p.fermer(); return; }
    ok.disabled = true;
    const res = await ecrire("equipage/hierarchie/attribuer", { membre: String(id), rang: choisi, version: x.version || 0 }, "Rang enregistré.");
    ok.disabled = false;
    if (res.ok) p.fermer();
    else if (res.status === 409) { p.fermer(); changerRang(id, nom); }
  } });
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), ok]);
}

// ─── Les anciens grades des affiches ────────────────────────────────────────
function reprise(d) {
  const def = defautDe(d);
  const options = [{ v: "", l: (def ? sansEmoji(def.nom) : "Le rang d'arrivée") + " (par défaut)" },
    ...d.rangs.filter((r) => r.verrou !== "capitaine" && r.verrou !== "second" && r.verrou !== "defaut").map((r) => ({ v: r.id, l: sansEmoji(r.nom), teinte: r.couleur }))];
  return h("div", { classe: "pile serree" }, h("p", { classe: "aide" }, "Le grade écrit sur les affiches, repris par son nom. Il ne change pas sur l'affiche : il dit seulement quel rang il donne à un membre qui n'a pas été nommé."),
    h("ul", { classe: "lignes-c reprise-liste" }, d.reprise.map((x) => h("li", { classe: "reprise-ligne" },
      h("span", { classe: "reprise-nom" }, h("b", {}, "« " + sansEmoji(x.nom) + " »"), h("small", {}, quantite(x.n, "affiche(s)") + (x.reserve ? " · ce nom est celui d'un rang réservé" : !x.rang ? " · à relier" : ""))),
      peutAgir() ? liste({ valeur: x.rang || "", options, label: "Rang", cacherLabel: true, changer: (v) => ecrire("equipage/hierarchie/reprise", { cle: x.cle, rang: v, version: x.version }, "Correspondance enregistrée.") }) : null,
      peutAgir() && !x.rang && !x.reserve && !d.rangs.some((r) => r.nom.toLowerCase() === x.nom.toLowerCase())
        ? bouton("Créer ce rang", { classe: "p discret", icone: "ajouter", reseau: true, onclick: () => ecrire("equipage/hierarchie/reprise", { cle: x.cle, creer: true }, "Rang créé et relié.") }) : null))));
}

// ─── La fiche d'un membre : « Rang : … » ────────────────────────────────────
//  Sous sa ligne « Équipe » (sa propre place : fiche.js ne change pas). La fiche est posée d'un coup (`rendreFiche`) :
//  la ligne s'y range juste après.
ecouter("fiche:rendue", ({ membre, zone }) => {
  if (!membre || !zone) return;
  queueMicrotask(async () => {
    const d = await lireHierarchie();
    const ident = zone.isConnected ? zone.closest(".fiche-ident") : null;
    if (!d || !ident) return;
    for (const x of ident.querySelectorAll(".fiche-rang-h")) x.remove();
    const el = ligneRang(membre, d);
    if (el) (ident.querySelector(".fiche-equipe") || ident.querySelector(".fiche-roles") || zone).after(el);
  });
});
function ligneRang(m, d) {
  const id = String(m.id);
  const x = d.membres[id];
  if (!x) {
    const garde = rangParId(d, (d.hors || {})[id]);
    return garde ? h("div", { classe: "fiche-rang-h sous-nom" }, icone("grade", "ic-p"), " Hors du clan : son rang « " + sansEmoji(garde.nom) + " » lui reviendra s'il revient.") : null;
  }
  const r = rangParId(d, x.rang);
  return h("div", { classe: "fiche-rang-h sous-nom" }, icone("grade", "ic-p"), " Rang : ", pastilleRang(r) || "—",
    SOURCES[x.source] ? h("span", { classe: "meta" }, " " + SOURCES[x.source]) : null,
    peutAgir() && x.source !== "tete" ? bouton("Changer le rang", { classe: "p discret", icone: "grade", onclick: () => changerRang(id, m.nom || id) }) : null);
}
