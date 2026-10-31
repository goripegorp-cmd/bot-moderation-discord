// clan.js — « L'Équipage » (clan GoRP) : les membres et leurs trois vues — présence, fiches techniques (affiches),
// équipes. Les tickets du clan : Le Port › Tickets (discord.js) ; les candidatures : recrutement_zone.js ; les annonces
// et événements : annonces.js.

import { h, icone, date, depuis, nombre, sansEmoji, contient, lettre, compte, maintenant, remplacer, quantite, accord, ajouter } from "./dom.js";
import { etat, P, peutAgir, aller, filtres, enLigne, emettre, nommerOnglets } from "./noyau.js";
import { lire, action as envoyerAction } from "./api.js";
import { charger, typeMetier, typeGrade, elementsDe, element } from "./donnees.js";
import {
  bouton, avatar, pastille, tampon, vide, tuile, tuiles, puces, segment, recherche, groupe, paginer, section, nomDe,
  toast, copier, confirmer, caseACocher, liste, squelettes, compteur, champ,
} from "./ui.js";
import { ouvrirFiche, agir, RANGS } from "./fiche.js";
import { indisponible } from "./discord.js";
import { affiche, afficheVierge, nomAffiche, metiersDe, gradeDe, insigneImage } from "./affiche.js";
import { ligne, lignes, groupes, outilsGroupes, badgeRestreint, avance } from "./rangement.js";
import { avecVerrou } from "./direct.js";
import { vueParEquipe } from "./equipes_admin.js";
import { vueHierarchie, lireHierarchie, pastilleRangMembre, rangDuMembre, rangsLus } from "./hierarchie_admin.js";
import { sceauRang } from "./hierarchie.js";

const resetPages = (p) => { for (const k of Object.keys(etat.pages)) if (k.startsWith(p)) delete etat.pages[k]; };

// ─── L'équipage ─────────────────────────────────────────────────────────────
// 27/10/2026 : « Équipage » est UNE liste et ses trois vues, un sous-onglet chacune — Présence (#equipage/membres),
// Fiches techniques (…/fiches : l'ancienne rubrique) et Équipes (…/equipes : l'ancien « Par équipe ») ; on passe de
// l'une à l'autre sans quitter la page (la recherche, les tuiles et « Ajouter au clan » restent).
export const VUES_EQUIPAGE = nommerOnglets("site.sous.equipage.membres", [["presence", "Présence", "membres"], ["fiches", "Fiches techniques", "fiches"], ["equipes", "Équipes", "equipage"], ["hierarchie", "Hiérarchie", "grade"], ["staff", "Staff", "equipage"]]);
const vueEquipage = (sous) => (VUES_EQUIPAGE.some(([k]) => k === sous) ? sous : "presence");
export function membres(vue, ctx = {}) {
  const f = filtres("clan", { q: "", rang: "tous", ajout: "" });
  let v = vueEquipage(ctx.sous);
  let fic = null;   // la vue « Fiches techniques » (ou « Hiérarchie », 27/10/2026) : son contrôleur
  const onglets = h("div", { classe: "sous-onglets", role: "tablist", "aria-label": "L'équipage" });
  const haut = h("div", { classe: "pile" }), resultats = h("div", { classe: "pile" }), bas = h("div", { classe: "pile" });
  const lot = h("div", { classe: "lot-hote" });
  const changer = () => { resetPages("clan"); if (fic) fic.chercher(); else majResultats(); };
  lireHierarchie().then(() => { if (!fic && resultats.isConnected) majResultats(); });   // le rang de chacun sur sa ligne
  const champRecherche = recherche(f.q, "Rechercher un membre ou un identifiant…", (q) => { f.q = q; changer(); });
  const copierListe = bouton("Copier la liste", { icone: "copier", classe: "avance", onclick: () => {
    const l = (etat.d && etat.d.clan && etat.d.clan.membres) || [];
    const larg = Math.max(4, ...l.map((x) => nomDe(x).length));
    copier(l.map((x) => nomDe(x).padEnd(larg + 2) + x.id + "  " + x.statut).join("\n"), quantite(l.length, "membre(s) copié(s)"));
  } });
  const outils = h("div", { classe: "outils" }, champRecherche);
  ajouter(vue, [onglets, haut, outils, resultats, bas, lot]);
  /** La vue choisie : son onglet, ses outils (la recherche reste en place : elle garde ce qui est tapé), sa liste. */
  const montrerVue = () => {
    remplacer(onglets, ...VUES_EQUIPAGE.map(([k, l, ic]) => h("a", { classe: "etiquette", role: "tab", href: "#equipage/membres" + (k === "presence" ? "" : "/" + k),
      "aria-selected": String(k === v) }, icone(ic), l)));
    const indice = v === "fiches" ? "Nom, surnom, nom Roblox…" : "Rechercher un membre ou un identifiant…";
    champRecherche.champ.placeholder = indice;
    champRecherche.champ.setAttribute("aria-label", indice);
    for (const x of [...outils.children]) if (x !== champRecherche) x.remove();
    if (v === "fiches") {
      etat.selection.clear();
      remplacer(lot); remplacer(bas); remplacer(resultats);
      fic = fiches(resultats, { q: () => f.q, outils: (commandes) => outils.append(...commandes) });
    } else if (v === "hierarchie") {
      etat.selection.clear();
      remplacer(lot); remplacer(bas); remplacer(resultats);
      fic = vueHierarchie(resultats, { q: () => f.q });
    } else if (v === "staff") {
      etat.selection.clear();
      remplacer(lot); remplacer(bas); remplacer(resultats);
      fic = vueStaff(resultats, { q: () => f.q, lot });
    } else {
      fic = null;
      outils.append(copierListe);
      majResultats(); majBas();
    }
  };
  const majHaut = () => {
    if (v === "staff") { remplacer(haut); return; }   // le staff a ses propres tuiles (vueStaff)
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
    peutAgir() && v !== "fiches" ? h("p", { classe: "aide avance" }, "Coche des membres pour les prévenir de leur inactivité ou leur retirer le rôle du clan (25 au plus d'un coup). Le fondateur et la direction ne sont jamais touchés.") : null);
  };
  const majBas = () => {
    const c = etat.d && etat.d.clan;
    remplacer(bas, c && (c.direction || []).length ? h("div", { classe: "cadre pile serree" }, h("h3", {}, "Fondateur et direction"),
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
      h("ul", { classe: "lignes-c" }, echus.map((m) => ligne({
        visuel: avatar(m, "p"), titre: nomDe(m), ouvrir: () => ouvrirFiche(m.id), libelleOuvrir: "Ouvrir la fiche de " + nomDe(m),
        sous: "Prévenu le " + date(m.rappel.envoye_le) + (m.rappel.par ? " par " + sansEmoji(m.rappel.par) : "")
          + (m.rappel.mode === "mp" ? ", en message privé" : sansEmoji(m.rappel.salon) ? ", dans #" + sansEmoji(m.rappel.salon) : ", dans un salon") + " · dernière activité : " + m.derniere,
        badges: [badgeRestreint(m.id)], etat: "alerte",
        actions: [{ texte: true, icone: "valider", libelle: "Le garder", reseau: true, classe: "discret", onclick: () => agir({ action: "clan_rappel_annuler", membre: m.id }, "", "", { direct: true }) },
          { texte: true, icone: "supprimer", libelle: "Retirer du clan", danger: true, reseau: true, onclick: () => agir({ action: "clan_retirer", membre: m.id }, "Retirer " + nomDe(m) + " du clan ?", "Prévenu il y a une semaine, toujours inactif. Seul le rôle du clan lui est retiré.", {}, "Retirer du clan", "danger") }],
      })))));
    blocs.push(puces([["tous", "Tous", c.membres.length], ...RANGS.map(([lib, t], r) => (nb[r] ? [String(r), lib, nb[r], t] : null)).filter(Boolean)], String(f.rang), (v) => { f.rang = v; changer(); }, "Présence"));
    if (!l.length) blocs.push(vide("Personne ici", "Change le filtre ou la recherche."));
    //  27/10/2026 : par équipe (le chef d'abord, tamponné ; l'éditeur d'une équipe en panneau : equipes_admin.js).
    if (v === "equipes" && l.length) {
      const zoneEq = h("div", { classe: "pile" });
      remplacer(resultats, ...blocs, zoneEq);
      vueParEquipe(zoneEq, l, (m, badge) => ligneClan(m, (RANGS[m.rang] || [])[1], () => { majLot(); }, badge), () => majResultats(), !!f.q || f.rang !== "tous");
      majLot();
      return;
    }
    // Un groupe par présence (les inactifs d'abord) ; les deux premiers ouverts, une ligne par membre, « Voir plus » par 20.
    const zone = h("div", { classe: "groupes-zone" }, groupes([2, 1, 3, 4, 0].map((r) => {
      const g = l.filter((m) => m.rang === r);
      if (!g.length) return null;
      const [lib, teinte] = RANGS[r];
      return { titre: lib, compte: g.length, chaud: r === 2, cle: "clan-" + r, contenu: () => lignes("clan-" + r, g, (m) => ligneClan(m, teinte, () => { majLot(); })) };
    }).filter(Boolean), { ouverts: 2, forcer: !!f.q || f.rang !== "tous" }));
    if (l.length) blocs.push(h("div", { classe: "rangee entre" }, h("span", { classe: "meta" }, quantite(l.length, "membre(s)")), outilsGroupes(zone)), zone);
    remplacer(resultats, ...blocs);
    majLot();
  };
  const maj = () => { majHaut(); if (fic) fic.maj(); else { majResultats(); majBas(); } };
  majHaut();
  montrerVue();
  return { maj, majJeu: () => { if (fic) fic.maj(); }, quitter: () => etat.selection.clear(),
    sous: (s) => { const n = vueEquipage(s); if (n !== v) { v = n; resetPages("clan"); majHaut(); montrerVue(); } } };
}

/** Un membre du clan : sa case (sélection), son nom, sa présence sur 7 jours, son rappel ; « Retirer » à droite. */
function ligneClan(m, teinte, surSelection, badgeSup) {
  const presents = /^\d+\/\d+$/.test(m.jours) ? +m.jours.split("/")[0] : 0;
  let l = null;
  const coche = peutAgir() ? caseACocher(null, etat.selection.has(m.id), (v, entree) => {
    if (v && etat.selection.size >= 25) { entree.checked = false; toast("25 au plus d'un coup.", "erreur"); return; }
    if (v) etat.selection.add(m.id); else etat.selection.delete(m.id);
    if (l) l.classList.toggle("choisie", v);
    surSelection();
  }, { aria: "Sélectionner " + nomDe(m) }) : null;
  l = ligne({
    visuel: [coche, avatar(m, "p")], titre: nomDe(m), libelleOuvrir: "Ouvrir la fiche de " + nomDe(m), ouvrir: () => ouvrirFiche(m.id),
    sous: ["@" + m.pseudo, h("span", { classe: "ident" }, " · " + m.id), " · arrivé le " + m.arrivee],
    badges: [badgeSup || null, pastilleRangMembre(m.id), m.jours !== "—" ? h("span", { classe: "jauge", vars: { "--teinte": teinte }, title: quantite(m.jours, "jour(s) actif(s)") + " sur 7" }, Array.from({ length: 7 }, (_, k) => h("i", { classe: k < presents ? "on" : "" }))) : null,
      pastilleRappel(m.rappel), badgeRestreint(m.id), pastille(m.statut, teinte)], maxBadges: badgeSup ? 6 : 5,
    date: m.derniere, dateTitre: "Dernière activité : " + m.derniere,
    actions: [peutAgir() ? { icone: "supprimer", libelle: "Retirer du clan", danger: true, reseau: true, onclick: () => agir({ action: "clan_retirer", membre: m.id }, "Retirer " + nomDe(m) + " du clan ?", "Seul le rôle du clan lui est retiré, sur Discord.", {}, "Retirer du clan", "danger") } : null],
    classe: etat.selection.has(m.id) ? "choisie" : "", donnees: { membre: m.id },
  });
  return l;
}
function pastilleRappel(r) {
  if (!r) return null;
  if (r.statut === "echu") return pastille("Délai écoulé", "#8e2a24", "Prévenu le " + date(r.envoye_le));
  if (r.statut === "en_attente") return pastille("Prévenu · " + date(r.echeance), "#a8641c", r.remis ? "Retrait proposé le " + date(r.echeance) : "Message privé refusé");
  if (r.statut === "revenu") return pastille("Revenu", "#3f6b3a", "Actif depuis le rappel du " + date(r.envoye_le));
  return null;
}
function cadreAjout(f) {
  const res = h("div", { classe: "pile" });
  let dernier = null;
  const lancer = async (q) => {
    dernier = q;
    remplacer(res, squelettes(2));
    const r = await lire("recherche", { q });
    if (q !== dernier || !res.isConnected) return;
    if (!r.ok) { remplacer(res, vide("Recherche indisponible", r.status === 0 ? "Hors ligne : la recherche dans tout le serveur demande la connexion." : r.erreur, "hors_ligne")); return; }
    const l = (r.donnees.membres || []).slice(0, q ? 12 : 6);
    remplacer(res, l.length ? h("ul", { classe: "lignes-c" }, l.map(ligneAjout)) : vide("Personne", "Essaie un autre nom ou l'identifiant."));
  };
  let charge = false;
  const champ_ = recherche(f.ajout, "Nom, pseudo ou identifiant…", (q) => { f.ajout = q; lancer(q); }, { delai: 280, nom: "chercher-membre" });
  const g = groupe({ titre: "Ajouter au clan", icone: "ajouter", cle: "clan-ajout", ouvert: !!f.ajout || undefined }, () => [
    h("p", { classe: "aide" }, "Tout le serveur : cherche une personne, ou parcours les arrivées récentes. Seul le rôle du clan est donné."), champ_, res]);
  g.addEventListener("toggle", () => { if (g.open && !charge) { charge = true; lancer(f.ajout); } });
  if (g.open) { charge = true; lancer(f.ajout); }
  return g;
}
/** Une personne du serveur à ajouter au clan : son arrivée, sa présence ; « Ajouter au clan » à droite. */
function ligneAjout(x) {
  const [lib, teinte] = RANGS[x.rang] || ["", null];
  return ligne({
    visuel: avatar(x, "p"), titre: nomDe(x), sous: (x.pseudo ? "@" + x.pseudo + " · " : "") + "arrivé " + (x.arrivee ? depuis(x.arrivee) : "—"),
    badges: [lib ? pastille(lib, teinte) : null, x.clan ? pastille("Déjà au clan", "#1f4e5a") : x.a_part ? pastille("Direction", "#5e3a4e") : null, badgeRestreint(x.id)],
    actions: [!x.clan && !x.a_part ? { texte: true, icone: "ajouter", libelle: "Ajouter au clan", classe: "vert", reseau: true,
      onclick: () => agir({ action: "clan_ajouter", membre: x.id }, "Ajouter " + nomDe(x) + " au clan ?", "Il reçoit le rôle du clan sur Discord, et l'accès à ses salons.", {}, "Ajouter au clan", "vert") } : null],
    ouvrir: () => ouvrirFiche(x.id), libelleOuvrir: "Ouvrir la fiche de " + nomDe(x),
  });
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

// ─── Le staff (31/10/2026) ──────────────────────────────────────────────────
// « Le même système d'activité dans une petite branche à part : on voit ceux du clan, on voit ceux du staff, et on peut
// prévenir en MP ceux du staff qui ne sont pas actifs. » Les mêmes barres sur 7 jours ; pas de retrait : la direction décide.
function vueStaff(zone, o) {
  const f = filtres("staff", { rang: "tous" });
  const majLot = () => {
    const n = etat.selection.size;
    if (!n || !peutAgir()) { remplacer(o.lot); return; }
    remplacer(o.lot, h("div", { classe: "lot", role: "region", "aria-label": "Sélection" },
      h("span", {}, h("b", { classe: "num" }, String(n)), " " + accord(n, "membre(s) du staff sélectionné(s)")),
      h("div", { classe: "rangee" },
        bouton("Tout désélectionner", { classe: "p bois", onclick: () => { etat.selection.clear(); dessiner(); } }),
        bouton("Prévenir", { classe: "p laiton", icone: "cloche", reseau: true, onclick: async () => {
          const r = await dialoguePrevenirStaff(n);
          if (!r) return;
          const ok = await agir(Object.assign({ action: "staff_prevenir", membres: [...etat.selection] }, r), "", "", { direct: true });
          if (ok) { etat.selection.clear(); dessiner(); }
        } }))));
  };
  const ligneStaff = (m, teinte) => {
    const presents = /^\d+\/\d+$/.test(m.jours) ? +m.jours.split("/")[0] : 0;
    let l = null;
    const coche = peutAgir() ? caseACocher(null, etat.selection.has(m.id), (val, entree) => {
      if (val && etat.selection.size >= 25) { entree.checked = false; toast("25 au plus d'un coup.", "erreur"); return; }
      if (val) etat.selection.add(m.id); else etat.selection.delete(m.id);
      if (l) l.classList.toggle("choisie", val);
      majLot();
    }, { aria: "Sélectionner " + nomDe(m) }) : null;
    l = ligne({
      visuel: [coche, avatar(m, "p")], titre: nomDe(m), libelleOuvrir: "Ouvrir la fiche de " + nomDe(m), ouvrir: () => ouvrirFiche(m.id),
      sous: ["@" + m.pseudo, h("span", { classe: "ident" }, " · " + m.id), " · arrivé le " + m.arrivee],
      badges: [m.jours !== "—" ? h("span", { classe: "jauge", vars: { "--teinte": teinte }, title: quantite(m.jours, "jour(s) actif(s)") + " sur 7" }, Array.from({ length: 7 }, (_, k) => h("i", { classe: k < presents ? "on" : "" }))) : null,
        pastilleRappelStaff(m.rappel), badgeRestreint(m.id), pastille(m.statut, teinte)], maxBadges: 5,
      date: m.derniere, dateTitre: "Dernière activité : " + m.derniere,
      classe: etat.selection.has(m.id) ? "choisie" : "", donnees: { membre: m.id },
    });
    return l;
  };
  const dessiner = () => {
    const s = etat.d && etat.d.staff_activite;
    if (!s) { remplacer(zone, indisponible()); return; }
    if (!s.roles.length) { remplacer(zone, vide("Aucun rôle du staff trouvé", "Les rôles du staff : ceux des tickets, et tout rôle dont le nom dit « staff ».")); return; }
    const nb = [0, 0, 0, 0, 0];
    s.membres.forEach((m) => { nb[m.rang] = (nb[m.rang] || 0) + 1; });
    const l = s.membres.filter((m) => (f.rang === "tous" || String(m.rang) === String(f.rang)) && contient(m.nom + " " + m.pseudo + " " + m.id, o.q()));
    const echus = s.membres.filter((m) => m.rappel && m.rappel.statut === "echu");
    const blocs = [tuiles(
      tuile({ cle: "s1", lib: "Staff", val: s.membres.length, icone: "equipage", sous: s.roles.map(sansEmoji).join(", ").slice(0, 60), teinte: "#1f4e5a" }),
      tuile({ cle: "s2", lib: "Actifs", val: nb[0], icone: "succes", sous: "présents cette semaine", teinte: "#3f6b3a" }),
      tuile({ cle: "s3", lib: "Peu présents", val: nb[1], icone: "minuteur", sous: "absents plus de 7 jours", teinte: "#a8641c" }),
      tuile({ cle: "s4", lib: "Inactifs", val: nb[2], icone: "attention", sous: "absents un mois ou plus", teinte: "#8e2a24" })),
    peutAgir() ? h("p", { classe: "aide avance" }, "Coche des membres du staff pour les prévenir (message privé ou mention dans un salon du staff, 25 au plus). La direction et le fondateur ne sont jamais touchés. L'activité du staff est suivie depuis le 31/10/2026 : la première semaine peut afficher « Jamais vu » pour qui n'a encore rien fait.") : null];
    if (echus.length) blocs.push(h("div", { classe: "cadre pile serree alerte-cadre" }, h("h3", {}, "À voir · " + echus.length),
      h("p", { classe: "aide" }, "Prévenus il y a une semaine, toujours peu présents : à la direction de faire le point."),
      h("ul", { classe: "lignes-c" }, echus.map((m) => ligne({
        visuel: avatar(m, "p"), titre: nomDe(m), ouvrir: () => ouvrirFiche(m.id), libelleOuvrir: "Ouvrir la fiche de " + nomDe(m),
        sous: "Prévenu le " + date(m.rappel.envoye_le) + (m.rappel.par ? " par " + sansEmoji(m.rappel.par) : "") + " · dernière activité : " + m.derniere,
        etat: "alerte", actions: [{ texte: true, icone: "valider", libelle: "Point fait", reseau: true, classe: "discret", onclick: () => agir({ action: "staff_rappel_annuler", membre: m.id }, "", "", { direct: true }) }],
      })))));
    blocs.push(puces([["tous", "Tous", s.membres.length], ...RANGS.map(([lib, t], r) => (nb[r] ? [String(r), lib, nb[r], t] : null)).filter(Boolean)], String(f.rang), (val) => { f.rang = val; dessiner(); }, "Présence"));
    if (!l.length) blocs.push(vide("Personne ici", "Change le filtre ou la recherche."));
    const groupesZone = h("div", { classe: "groupes-zone" }, groupes([2, 1, 3, 4, 0].map((r) => {
      const g = l.filter((m) => m.rang === r);
      if (!g.length) return null;
      const [lib, teinte] = RANGS[r];
      return { titre: lib, compte: g.length, chaud: r === 2, cle: "staff-" + r, contenu: () => lignes("staff-" + r, g, (m) => ligneStaff(m, teinte)) };
    }).filter(Boolean), { ouverts: 2, forcer: !!o.q() || f.rang !== "tous" }));
    if (l.length) blocs.push(h("div", { classe: "rangee entre" }, h("span", { classe: "meta" }, quantite(l.length, "membre(s) du staff")), outilsGroupes(groupesZone)), groupesZone);
    remplacer(zone, ...blocs);
    majLot();
  };
  dessiner();
  return { maj: dessiner, chercher: () => { resetPages("staff"); dessiner(); } };
}
function pastilleRappelStaff(r) {
  if (!r) return null;
  if (r.statut === "echu") return pastille("Délai écoulé", "#8e2a24", "Prévenu le " + date(r.envoye_le));
  if (r.statut === "en_attente") return pastille("Prévenu · " + date(r.echeance), "#a8641c", r.remis ? "Point proposé le " + date(r.echeance) : "Message privé refusé");
  if (r.statut === "revenu") return pastille("Revenu", "#3f6b3a", "Actif depuis le rappel du " + date(r.envoye_le));
  return null;
}
async function dialoguePrevenirStaff(n) {
  const salons = (etat.d.staff_activite && etat.d.staff_activite.salons) || [];
  let mode = "mp", salon = salons[0] ? salons[0].id : "";
  const apercu = h("p", { classe: "aide" });
  const salonL = liste({ valeur: salon, label: "Salon", plein: true, options: salons.map((s) => ({ v: s.id, l: "#" + sansEmoji(s.nom), sous: sansEmoji(s.cat) })), changer: (val) => { salon = val; } });
  const majApercu = () => {
    salonL.hidden = mode !== "salon";
    apercu.textContent = mode === "mp" ? "« On ne t'a pas beaucoup vu ces derniers temps. Sans activité d'ici une semaine, la direction fera le point avec toi sur ta place dans le staff. »" : salons.length ? "Un seul message qui les mentionne, dans le salon du staff choisi." : "Aucun salon du staff où le bot peut écrire.";
  };
  const modeL = liste({ valeur: mode, label: "Comment", plein: true, options: [{ v: "mp", l: "Message privé" }, { v: "salon", l: "Mention dans un salon du staff" }], changer: (val) => { mode = val; majApercu(); } });
  majApercu();
  const r = await confirmer({ titre: "Prévenir " + quantite(n, "membre(s) du staff"), texte: "Sans activité d'ici une semaine, le site te le rappelle : à la direction de faire le point.", contenu: [modeL, salonL, apercu], libelleOk: "Prévenir", icone: "cloche" });
  if (!r) return null;
  if (mode === "salon" && !salon) { toast("Aucun salon possible.", "erreur"); return null; }
  return { mode, salon: mode === "salon" ? salon : "" };
}

// ─── Les fiches techniques (affiches des membres) ───────────────────────────
// 27/10/2026 : une vue d'« Équipage » (l'ancienne rubrique) — `o.q()` : la recherche de la rubrique ; `o.outils(commandes)` :
// ses commandes (regrouper, afficher, l'atelier), rangées à côté de cette recherche.
export function fiches(vue, o) {
  const f = filtres("fiches", { vue: "metier", quoi: "tous" });
  const q = () => o.q() || "";
  const resultats = h("div", { classe: "pile" }, squelettes(3));
  const changer = () => { resetPages("fic"); maj(); };
  o.outils([
    segment(f.vue, [["metier", "Par métier"], ["grade", "Par grade"], ["az", "De A à Z"]], (v) => { f.vue = v; changer(); }, "Regrouper"),
    liste({ valeur: f.quoi, label: "Afficher", options: [{ v: "tous", l: "Tout l'équipage" }, { v: "avec", l: "Avec une affiche" }, { v: "sans", l: "Sans affiche" }], changer: (v) => { f.quoi = v; changer(); } }),
    bouton("Ouvrir l'atelier", { icone: "affiches", classe: "discret", onclick: () => aller("capitainerie", "affiches") })]);
  ajouter(vue, [resultats]);
  let pret = false;
  const maj = async () => {
    const [cat, aff] = [await charger("catalogue"), await charger("affiches")];
    if (f.vue === "grade") await lireHierarchie();
    if (!resultats.isConnected) return;
    if (!etat.d || !etat.d.clan) { remplacer(resultats, indisponible()); return; }
    if (!aff || aff.erreur) { remplacer(resultats, vide("Affiches indisponibles", aff && aff.erreur, "hors_ligne")); return; }
    pret = true;
    const parMembre = new Map();
    for (const a of aff.affiches || []) if (!a.retire_le && a.membre && a.membre.id) parMembre.set(String(a.membre.id), a);
    let equipage = etat.d.clan.membres.map((m) => ({ m, a: parMembre.get(String(m.id)) || null }));
    if (f.quoi === "avec") equipage = equipage.filter((x) => x.a);
    if (f.quoi === "sans") equipage = equipage.filter((x) => !x.a);
    equipage = equipage.filter((x) => contient([x.m.nom, x.m.pseudo, x.m.id, x.a && x.a.surnom, x.a && x.a.roblox && x.a.roblox.nom].join(" "), q()));
    const avec = equipage.filter((x) => x.a).length;
    const creer = (m) => { if (peutAgir()) aller("capitainerie", "affiches", "nouvelle-" + m.id); else ouvrirFiche(m.id); };
    // Présence en direct : le cadenas sur une affiche (ou sur la nouvelle affiche d'un membre) en cours de modification.
    const rendre = (x) => (x.a ? avecVerrou(affiche(x.a, cat, { taille: "mini", clic: () => emettre("affiche:ouvrir", x.a.id) }), "affiche:" + x.a.id)
      : avecVerrou(afficheVierge(x.m, () => creer(x.m)), "affiche-membre:" + x.m.id));
    // Les membres sans affiche : une ligne chacun (pas un mur de fiches vierges), « Créer l'affiche » à droite.
    const ligneSans = (x) => avecVerrou(ligne({ visuel: avatar(x.m, "p"), titre: nomDe(x.m), sous: x.m.pseudo ? "@" + x.m.pseudo : "", badges: [badgeRestreint(x.m.id)],
      actions: [peutAgir() ? { texte: true, icone: "plume", libelle: "Créer l'affiche", onclick: () => creer(x.m) } : null], ouvrir: () => ouvrirFiche(x.m.id), libelleOuvrir: "Ouvrir la fiche de " + nomDe(x.m) }),
      "affiche-membre:" + x.m.id);
    const zone = h("div", { classe: "groupes-zone" });
    const blocs = [h("div", { classe: "rangee entre" }, h("p", { classe: "aide" }, compte(equipage.length, "membre") + " · " + compte(avec, "affiche") + " · " + compte(equipage.length - avec, "fiche vierge", "fiches vierges") + ". Touche une affiche pour la voir en grand."),
      equipage.length ? outilsGroupes(zone) : null)];
    if (!equipage.length) { remplacer(resultats, ...blocs, vide("Personne ici", "Change le filtre ou la recherche.")); return; }
    if (f.vue === "az") {
      const parL = new Map();
      equipage.sort((x, y) => nomDe(x.m).localeCompare(nomDe(y.m), "fr", { sensitivity: "base" })).forEach((x) => { const l = lettre(x.m.nom); if (!parL.has(l)) parL.set(l, []); parL.get(l).push(x); });
      ajouter(zone, groupes([...parL.entries()].map(([l, g]) => ({ titre: l, compte: g.length, cle: "fic-az-" + l,
        contenu: () => paginer("fic-az-" + l, g, rendre, { classe: "grille affiches", pas: 18 }) })), { ouverts: equipage.length <= 40 ? parL.size : 1, forcer: !!q() }));
    } else {
      const t = f.vue === "metier" ? typeMetier(cat) : typeGrade(cat);
      //  27/10/2026 : « Par grade » suit la hiérarchie — le rang de chacun (hierarchie_admin.js), dans l'ordre des rangs.
      const rangs = f.vue === "grade" ? rangsLus() : [];
      const rang = (k) => rangs.find((r) => r.id === k) || null;
      const parCle = new Map();
      for (const x of equipage) {
        const cles = !x.a ? ["__sans"] : f.vue === "metier" ? (metiersDe(x.a, cat).length ? metiersDe(x.a, cat) : ["__aucun"])
          : [(rangs.length ? rangDuMembre(x.m.id) : x.a.grade) || "__aucun"];
        for (const k of cles) { if (!parCle.has(k)) parCle.set(k, []); parCle.get(k).push(x); }
      }
      const ordre = rangs.length ? rangs.map((r) => r.id) : t ? elementsDe(cat, t.cle).map((e) => e.cle) : [];
      const cles = [...parCle.keys()].sort((a, b) => (a.startsWith("__") - b.startsWith("__")) || ((ordre.indexOf(a) + 1 || 999) - (ordre.indexOf(b) + 1 || 999)) || a.localeCompare(b));
      ajouter(zone, groupes(cles.map((k) => {
        const r = rang(k);
        const e = !r && t && !k.startsWith("__") ? element(cat, t.cle, k) : null;
        const titre = k === "__sans" ? "Sans affiche" : k === "__aucun" ? (f.vue === "metier" ? "Sans métier" : "Sans grade") : r ? sansEmoji(r.nom) : e ? e.nom : sansEmoji(k);
        return { titre, compte: parCle.get(k).length, visuel: r ? sceauRang(r, "groupe-visuel") : e ? insigneImage(e, "groupe-visuel") : null, icone: !e && !r ? (k === "__sans" ? "plume" : "drapeau") : null, cle: "fic-" + f.vue + "-" + k,
          contenu: () => (k === "__sans" ? lignes("fic-" + f.vue + "-" + k, parCle.get(k), ligneSans) : paginer("fic-" + f.vue + "-" + k, parCle.get(k), rendre, { classe: "grille affiches", pas: 18 })) };
      }), { ouverts: cles.length <= 3 ? cles.length : 2, forcer: !!q() }));
    }
    remplacer(resultats, ...blocs, zone);
  };
  maj();
  return { maj: () => { if (pret) maj(); }, chercher: changer };
}
