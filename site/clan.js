// clan.js — « L'Équipage » (clan GoRP) : les membres, les fiches techniques (affiches), les tickets du clan.
// Les candidatures : recrutement.js ; les annonces et événements : annonces.js.

import { h, icone, date, depuis, nombre, sansEmoji, contient, lettre, compte, maintenant, remplacer, quantite, accord, ajouter } from "./dom.js";
import { etat, P, peutAgir, aller, filtres, enLigne, emettre } from "./noyau.js";
import { lire, action as envoyerAction } from "./api.js";
import { charger, typeMetier, typeGrade, elementsDe, element } from "./donnees.js";
import {
  bouton, avatar, pastille, tampon, vide, tuile, tuiles, puces, segment, recherche, groupe, paginer, section, lienNom, nomDe,
  toast, copier, confirmer, caseACocher, liste, squelettes, compteur, boutonCopie, champ,
} from "./ui.js";
import { ouvrirFiche, agir, RANGS } from "./fiche.js";
import { ticketsVue, indisponible } from "./discord.js";
import { affiche, afficheVierge, nomAffiche, metiersDe, gradeDe, insigneImage } from "./affiche.js";
import { avecVerrou } from "./direct.js";

const resetPages = (p) => { for (const k of Object.keys(etat.pages)) if (k.startsWith(p)) delete etat.pages[k]; };

// ─── L'équipage ─────────────────────────────────────────────────────────────
export function membres(vue) {
  const f = filtres("clan", { q: "", rang: "tous", ajout: "" });
  const haut = h("div", { classe: "pile" }), resultats = h("div", { classe: "pile" }), bas = h("div", { classe: "pile" });
  const lot = h("div", { classe: "lot-hote" });
  const changer = () => { resetPages("clan"); majResultats(); };
  ajouter(vue, [haut, h("div", { classe: "outils" },
    recherche(f.q, "Rechercher un membre ou un identifiant…", (q) => { f.q = q; changer(); }),
    bouton("Copier la liste", { icone: "copier", onclick: () => {
      const l = (etat.d && etat.d.clan && etat.d.clan.membres) || [];
      const larg = Math.max(4, ...l.map((x) => nomDe(x).length));
      copier(l.map((x) => nomDe(x).padEnd(larg + 2) + x.id + "  " + x.statut).join("\n"), quantite(l.length, "membre(s) copié(s)"));
    } })), resultats, bas, lot]);
  const majHaut = () => {
    const c = etat.d && etat.d.clan;
    if (!c) { remplacer(haut, indisponible()); return; }
    const nb = [0, 0, 0, 0, 0];
    c.membres.forEach((m) => { nb[m.rang] = (nb[m.rang] || 0) + 1; });
    remplacer(haut, tuiles(
      tuile({ cle: "k1", lib: "Membres", val: c.membres.length, icone: "equipage", sous: c.role ? "rôle « " + sansEmoji(c.role) + " »" : "aucun rôle réglé", teinte: "#1f4e5a" }),
      tuile({ cle: "k2", lib: "Actifs", val: nb[0], icone: "succes", sous: "présents cette semaine", teinte: "#3f6b3a" }),
      tuile({ cle: "k3", lib: "Peu présents", val: nb[1], icone: "minuteur", sous: "absents plus de 7 jours", teinte: "#a8641c" }),
      tuile({ cle: "k4", lib: "Inactifs", val: nb[2], icone: "attention", sous: "absents un mois ou plus", teinte: "#8e2a24" })),
    peutAgir() && c.role ? cadreAjout(f) : null,
    peutAgir() ? h("p", { classe: "aide" }, "Coche des membres pour les prévenir de leur inactivité ou leur retirer le rôle du clan (25 au plus d'un coup). Le fondateur et la direction ne sont jamais touchés.") : null);
    remplacer(bas, (c.direction || []).length ? h("div", { classe: "cadre pile serree" }, h("h3", {}, "Fondateur et direction"),
      h("p", { classe: "aide" }, "Mis à part : hors statistiques, intouchables depuis le site."),
      h("div", { classe: "pastilles" }, c.direction.map((m) => h("button", { classe: "puce", type: "button", onclick: () => ouvrirFiche(m.id) }, avatar(m, "xs"), h("span", { classe: "puce-lib" }, nomDe(m)))))) : "");
  };
  const majLot = () => {
    const n = etat.selection.size;
    if (!n || !peutAgir()) { remplacer(lot); return; }
    remplacer(lot, h("div", { classe: "lot", role: "region", "aria-label": "Sélection" },
      h("span", {}, h("b", { classe: "num" }, String(n)), " " + accord(n, "membre(s) sélectionné(s)")),
      h("div", { classe: "rangee" },
        bouton("Tout désélectionner", { classe: "p bois", onclick: () => { etat.selection.clear(); majResultats(); } }),
        bouton("Prévenir", { classe: "p laiton", icone: "cloche", reseau: true, onclick: async () => {
          const r = await dialoguePrevenir(n);
          if (!r) return;
          const ok = await agir(Object.assign({ action: "clan_prevenir", membres: [...etat.selection] }, r), "", "", { direct: true });
          if (ok) { etat.selection.clear(); majResultats(); }
        } }),
        bouton("Retirer du clan", { classe: "p principal", reseau: true, onclick: async () => {
          const ok = await agir({ action: "clan_retirer_lot", membres: [...etat.selection] }, "Retirer " + quantite(n, "membre(s)") + " du clan ?",
            "Seul le rôle du clan leur est retiré, sur Discord. Chacun est vérifié : le fondateur et la direction ne sont jamais touchés.", {}, "Retirer " + n + " du clan", "danger");
          if (ok) { etat.selection.clear(); majResultats(); }
        } }))));
  };
  const majResultats = () => {
    const c = etat.d && etat.d.clan;
    if (!c) { remplacer(resultats); return; }
    if (!c.role) { remplacer(resultats, vide("Aucun rôle du clan réglé", "Choisis-le dans /configure sur Discord.")); return; }
    const echus = c.membres.filter((m) => m.rappel && m.rappel.statut === "echu");
    const nb = [0, 0, 0, 0, 0];
    c.membres.forEach((m) => { nb[m.rang] = (nb[m.rang] || 0) + 1; });
    const l = c.membres.filter((m) => (f.rang === "tous" || String(m.rang) === String(f.rang)) && contient(m.nom + " " + m.pseudo + " " + m.id, f.q));
    const blocs = [];
    if (echus.length) blocs.push(h("div", { classe: "cadre pile serree alerte-cadre" }, h("h3", {}, "À décider · " + echus.length),
      h("p", { classe: "aide" }, "Prévenus il y a une semaine, toujours inactifs : le retrait du clan est proposé."),
      h("div", { classe: "lignes" }, echus.map((m) => h("div", { classe: "ligne" }, avatar(m, "p"),
        h("div", { classe: "bloc" }, h("div", { classe: "nom" }, lienNom(m.id, ouvrirFiche)),
          h("div", { classe: "sous-nom" }, "Prévenu le " + date(m.rappel.envoye_le) + (m.rappel.par ? " par " + sansEmoji(m.rappel.par) : "")
            + (m.rappel.mode === "mp" ? ", en message privé" : sansEmoji(m.rappel.salon) ? ", dans #" + sansEmoji(m.rappel.salon) : ", dans un salon")
            + " · dernière activité : " + m.derniere)),
        h("div", { classe: "droite" },
          bouton("Le garder", { classe: "p discret", reseau: true, onclick: () => agir({ action: "clan_rappel_annuler", membre: m.id }, "", "", { direct: true }) }),
          bouton("Retirer du clan", { classe: "p danger", reseau: true, onclick: () => agir({ action: "clan_retirer", membre: m.id }, "Retirer " + nomDe(m) + " du clan ?", "Prévenu il y a une semaine, toujours inactif. Seul le rôle du clan lui est retiré.", {}, "Retirer du clan", "danger") })))))));
    blocs.push(puces([["tous", "Tous", c.membres.length], ...RANGS.map(([lib, t], r) => (nb[r] ? [String(r), lib, nb[r], t] : null)).filter(Boolean)], String(f.rang), (v) => { f.rang = v; changer(); }, "Présence"));
    if (!l.length) blocs.push(vide("Personne ici", "Change le filtre ou la recherche."));
    for (const r of [2, 1, 3, 4, 0]) {
      const g = l.filter((m) => m.rang === r);
      if (!g.length) continue;
      const [lib, teinte] = RANGS[r];
      blocs.push(groupe({ titre: lib, compte: g.length, chaud: r === 2, cle: "clan-" + r, ouvert: r === 2 || r === 1 || !!f.q || f.rang !== "tous" ? true : undefined },
        () => paginer("clan-" + r, g, (m) => ligneClan(m, teinte, () => { majLot(); }), { classe: "lignes", pas: 30 })));
    }
    remplacer(resultats, ...blocs);
    majLot();
  };
  const maj = () => { majHaut(); majResultats(); };
  maj();
  return { maj, quitter: () => etat.selection.clear() };
}

function ligneClan(m, teinte, surSelection) {
  const presents = /^\d+\/\d+$/.test(m.jours) ? +m.jours.split("/")[0] : 0;
  const ligne = h("div", { classe: "ligne" + (etat.selection.has(m.id) ? " choisie" : "") });
  const coche = peutAgir() ? caseACocher(null, etat.selection.has(m.id), (v, entree) => {
    if (v && etat.selection.size >= 25) { entree.checked = false; toast("25 au plus d'un coup.", "erreur"); return; }
    if (v) etat.selection.add(m.id); else etat.selection.delete(m.id);
    ligne.classList.toggle("choisie", v);
    surSelection();
  }, { aria: "Sélectionner " + nomDe(m) }) : null;
  ajouter(ligne, [
    h("div", { classe: "qui" }, coche, avatar(m, "p")),
    h("div", { classe: "bloc" }, h("div", { classe: "nom" }, lienNom(m.id, ouvrirFiche)),
      h("div", { classe: "sous-nom" }, "@" + m.pseudo + " · ", h("span", { classe: "ident" }, m.id), boutonCopie(m.id, "Identifiant copié")),
      h("div", { classe: "sous-nom" }, "Dernière activité : " + m.derniere + " · arrivé le " + m.arrivee)),
    h("div", { classe: "droite" },
      m.jours !== "—" ? h("span", { classe: "jauge", vars: { "--teinte": teinte }, title: quantite(m.jours, "jour(s) actif(s)") + " sur 7" }, Array.from({ length: 7 }, (_, k) => h("i", { classe: k < presents ? "on" : "" }))) : null,
      pastilleRappel(m.rappel), pastille(m.statut, teinte),
      peutAgir() ? bouton("Retirer", { classe: "p danger", reseau: true, onclick: () => agir({ action: "clan_retirer", membre: m.id }, "Retirer " + nomDe(m) + " du clan ?", "Seul le rôle du clan lui est retiré, sur Discord.", {}, "Retirer du clan", "danger") }) : null)]);
  return ligne;
}
function pastilleRappel(r) {
  if (!r) return null;
  if (r.statut === "echu") return pastille("Délai écoulé", "#8e2a24", "Prévenu le " + date(r.envoye_le));
  if (r.statut === "en_attente") return pastille("Prévenu · " + date(r.echeance), "#a8641c", r.remis ? "Retrait proposé le " + date(r.echeance) : "Message privé refusé");
  if (r.statut === "revenu") return pastille("Revenu", "#3f6b3a", "Actif depuis le rappel du " + date(r.envoye_le));
  return null;
}
function cadreAjout(f) {
  const res = h("div", { classe: "lignes" });
  let dernier = null;
  const lancer = async (q) => {
    dernier = q;
    remplacer(res, squelettes(2));
    const r = await lire("recherche", { q });
    if (q !== dernier || !res.isConnected) return;
    if (!r.ok) { remplacer(res, vide("Recherche indisponible", r.status === 0 ? "Hors ligne : la recherche dans tout le serveur demande la connexion." : r.erreur, "hors_ligne")); return; }
    const l = (r.donnees.membres || []).slice(0, q ? 12 : 6);
    remplacer(res, ...(l.length ? l.map(ligneAjout) : [vide("Personne", "Essaie un autre nom ou l'identifiant.")]));
  };
  let charge = false;
  const champ_ = recherche(f.ajout, "Nom, pseudo ou identifiant…", (q) => { f.ajout = q; lancer(q); }, { delai: 280, nom: "chercher-membre" });
  const g = groupe({ titre: "Ajouter au clan", icone: "ajouter", cle: "clan-ajout", ouvert: !!f.ajout || undefined }, () => [
    h("p", { classe: "aide" }, "Tout le serveur : cherche une personne, ou parcours les arrivées récentes. Seul le rôle du clan est donné."), champ_, res]);
  g.addEventListener("toggle", () => { if (g.open && !charge) { charge = true; lancer(f.ajout); } });
  if (g.open) { charge = true; lancer(f.ajout); }
  return g;
}
function ligneAjout(x) {
  const [lib, teinte] = RANGS[x.rang] || ["", null];
  return h("div", { classe: "ligne" }, avatar(x, "p"),
    h("div", { classe: "bloc" }, h("div", { classe: "nom" }, h("button", { classe: "lien-nom", type: "button", onclick: () => ouvrirFiche(x.id) }, nomDe(x))),
      h("div", { classe: "sous-nom" }, (x.pseudo ? "@" + x.pseudo + " · " : "") + "arrivé " + (x.arrivee ? depuis(x.arrivee) : "—"))),
    h("div", { classe: "droite" }, lib ? pastille(lib, teinte) : null,
      x.clan ? pastille("Déjà au clan", "#1f4e5a") : x.a_part ? pastille("Direction", "#5e3a4e")
        : bouton("Ajouter au clan", { classe: "p vert", icone: "ajouter", reseau: true, onclick: () => agir({ action: "clan_ajouter", membre: x.id }, "Ajouter " + nomDe(x) + " au clan ?", "Il reçoit le rôle du clan sur Discord, et l'accès à ses salons.", {}, "Ajouter au clan", "vert") })));
}
async function dialoguePrevenir(n) {
  const salons = (etat.d.clan && etat.d.clan.salons) || [];
  let mode = "mp", salon = salons[0] ? salons[0].id : "";
  const apercu = h("p", { classe: "aide" });
  const salonL = liste({ valeur: salon, label: "Salon", plein: true, options: salons.map((s) => ({ v: s.id, l: "#" + sansEmoji(s.nom), sous: sansEmoji(s.cat) })), changer: (v) => { salon = v; } });
  const majApercu = () => {
    salonL.hidden = mode !== "salon";
    apercu.textContent = mode === "mp" ? "« Attention, vous êtes inactif : vous allez être retiré du clan d'ici une semaine. »" : salons.length ? "Un seul message qui les mentionne, dans le salon choisi." : "Aucun salon du clan où le bot peut écrire.";
  };
  const modeL = liste({ valeur: mode, label: "Comment", plein: true, options: [{ v: "mp", l: "Message privé" }, { v: "salon", l: "Mention dans un salon" }], changer: (v) => { mode = v; majApercu(); } });
  majApercu();
  const r = await confirmer({ titre: "Prévenir " + quantite(n, "membre(s)") + (n > 1 ? " de leur inactivité" : " de son inactivité"), texte: "Sans activité d'ici une semaine, le site te rappelle et propose de les retirer du clan.", contenu: [modeL, salonL, apercu], libelleOk: "Prévenir", icone: "cloche" });
  if (!r) return null;
  if (mode === "salon" && !salon) { toast("Aucun salon possible.", "erreur"); return null; }
  return { mode, salon: mode === "salon" ? salon : "" };
}

// ─── Les fiches techniques (affiches des membres) ───────────────────────────
export function fiches(vue) {
  const f = filtres("fiches", { q: "", vue: "metier", quoi: "tous" });
  const resultats = h("div", { classe: "pile" }, squelettes(3));
  const changer = () => { resetPages("fic"); maj(); };
  ajouter(vue, [h("div", { classe: "outils" },
    recherche(f.q, "Nom, surnom, nom Roblox…", (q) => { f.q = q; changer(); }),
    segment(f.vue, [["metier", "Par métier"], ["grade", "Par grade"], ["az", "De A à Z"]], (v) => { f.vue = v; changer(); }, "Regrouper"),
    liste({ valeur: f.quoi, label: "Afficher", options: [{ v: "tous", l: "Tout l'équipage" }, { v: "avec", l: "Avec une affiche" }, { v: "sans", l: "Sans affiche" }], changer: (v) => { f.quoi = v; changer(); } }),
    bouton("Ouvrir l'atelier", { icone: "affiches", classe: "discret", onclick: () => aller("capitainerie", "affiches") })), resultats]);
  let pret = false;
  const maj = async () => {
    const [cat, aff] = [await charger("catalogue"), await charger("affiches")];
    if (!resultats.isConnected) return;
    if (!etat.d || !etat.d.clan) { remplacer(resultats, indisponible()); return; }
    if (!aff || aff.erreur) { remplacer(resultats, vide("Affiches indisponibles", aff && aff.erreur, "hors_ligne")); return; }
    pret = true;
    const parMembre = new Map();
    for (const a of aff.affiches || []) if (!a.retire_le && a.membre && a.membre.id) parMembre.set(String(a.membre.id), a);
    let lignes = etat.d.clan.membres.map((m) => ({ m, a: parMembre.get(String(m.id)) || null }));
    if (f.quoi === "avec") lignes = lignes.filter((x) => x.a);
    if (f.quoi === "sans") lignes = lignes.filter((x) => !x.a);
    lignes = lignes.filter((x) => contient([x.m.nom, x.m.pseudo, x.m.id, x.a && x.a.surnom, x.a && x.a.roblox && x.a.roblox.nom].join(" "), f.q));
    const avec = lignes.filter((x) => x.a).length;
    const rendre = (x) => (x.a ? avecVerrou(affiche(x.a, cat, { taille: "mini", clic: () => emettre("affiche:ouvrir", x.a.id) }), "affiche:" + x.a.id)
      : avecVerrou(afficheVierge(x.m, () => { if (peutAgir()) aller("capitainerie", "affiches", "nouvelle-" + x.m.id); else ouvrirFiche(x.m.id); }), "affiche-membre:" + x.m.id));
    const blocs = [h("p", { classe: "aide" }, compte(lignes.length, "membre") + " · " + compte(avec, "affiche") + " · " + compte(lignes.length - avec, "fiche vierge", "fiches vierges") + ". Touche une affiche pour la voir en grand.")];
    if (!lignes.length) { remplacer(resultats, ...blocs, vide("Personne ici", "Change le filtre ou la recherche.")); return; }
    if (f.vue === "az") {
      const parL = new Map();
      lignes.sort((x, y) => nomDe(x.m).localeCompare(nomDe(y.m), "fr", { sensitivity: "base" })).forEach((x) => { const l = lettre(x.m.nom); if (!parL.has(l)) parL.set(l, []); parL.get(l).push(x); });
      blocs.push(...[...parL.entries()].map(([l, g]) => groupe({ titre: l, compte: g.length, cle: "fic-az-" + l, ouvert: lignes.length <= 40 ? true : undefined },
        () => paginer("fic-az-" + l, g, rendre, { classe: "grille affiches", pas: 18 }))));
    } else {
      const t = f.vue === "metier" ? typeMetier(cat) : typeGrade(cat);
      const groupes = new Map();
      for (const x of lignes) {
        const cles = !x.a ? ["__sans"] : f.vue === "metier" ? (metiersDe(x.a, cat).length ? metiersDe(x.a, cat) : ["__aucun"]) : [x.a.grade || "__aucun"];
        for (const k of cles) { if (!groupes.has(k)) groupes.set(k, []); groupes.get(k).push(x); }
      }
      const ordre = t ? elementsDe(cat, t.cle).map((e) => e.cle) : [];
      const cles = [...groupes.keys()].sort((a, b) => (a.startsWith("__") - b.startsWith("__")) || ((ordre.indexOf(a) + 1 || 999) - (ordre.indexOf(b) + 1 || 999)) || a.localeCompare(b));
      blocs.push(...cles.map((k) => {
        const e = t && !k.startsWith("__") ? element(cat, t.cle, k) : null;
        const titre = k === "__sans" ? "Sans affiche" : k === "__aucun" ? (f.vue === "metier" ? "Sans métier" : "Sans grade") : e ? e.nom : sansEmoji(k);
        return groupe({ titre, compte: groupes.get(k).length, visuel: e ? insigneImage(e, "groupe-visuel") : null,
          icone: !e ? (k === "__sans" ? "plume" : "drapeau") : null, cle: "fic-" + f.vue + "-" + k, ouvert: cles.length <= 3 || !!f.q || cles.indexOf(k) < 2 ? true : undefined },
        () => paginer("fic-" + f.vue + "-" + k, groupes.get(k), rendre, { classe: "grille affiches", pas: 18 }));
      }));
    }
    remplacer(resultats, ...blocs);
  };
  maj();
  return { maj: () => { if (pret) maj(); } };
}

// ─── Les tickets du clan ────────────────────────────────────────────────────
export const tickets = (vue) => ticketsVue(vue, "clan");
