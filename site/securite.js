// securite.js — « Sécurité » (Le Port), 26/10/2026 : qui est connecté au site et depuis quel appareil, ce que le site a
// fait sur Discord, les refus comptés, les alertes, et qui détient une permission dangereuse sur le serveur.
// Lecture seule, sauf le bouton d'urgence « Fermer toutes les autres sessions ». Rien n'y est automatique ; ce que font le
// fondateur et la direction n'y est jamais une alerte, seulement visible (décisions du fondateur).
// `api/securite` (securite_site.route_securite) : sessions [{id, qui, moi, appareil, adresse, ouverte, vue, fin, nouveau}],
// equipage (sessions ouvertes du site de l'équipage), fondateur, actions [{quand, qui, quoi, statut, texte, appareil}],
// evenements [{quand, type, alerte, texte, detail, qui}], refus [{cle, libelle, n}], depuis, permissions {roles
// [{id, nom, couleur, permissions, membres, n, bots, gere, tous}], proprietaire, audit}, personnes.

import { h, date, depuis, quantite, remplacer, ajouter, sansEmoji } from "./dom.js";
import { P, retenirPersonnes } from "./noyau.js";
import { poster } from "./api.js";
import { charger } from "./donnees.js";
import { bouton, avatar, pastille, vide, tuile, tuiles, section, confirmer, toast, squelettes, nomDe, ENCRES } from "./ui.js";
import { ligne, lignes, groupes, pastilleIcone } from "./rangement.js";

export function securite(vue) {
  const zone = h("div", { classe: "pile" }, squelettes(3));
  ajouter(vue, [zone]);
  const maj = async (forcer) => {
    const s = await charger("securite", { forcer });
    if (!zone.isConnected) return;
    if (!s || s.erreur) { remplacer(zone, s && s.erreur ? vide("Sécurité indisponible", s.erreur, "hors_ligne") : squelettes(3)); return; }
    retenirPersonnes(s.personnes);
    const sessions = s.sessions || [], actions = s.actions || [], evts = s.evenements || [];
    const alertes = evts.filter((e) => e.alerte);
    const refus = (s.refus || []).reduce((a, r) => a + (Number(r.n) || 0), 0);
    const nouveaux = sessions.filter((x) => x.nouveau).length;
    const echecs = actions.filter((a) => Number(a.statut) >= 400).length;
    remplacer(zone,
      tuiles(
        tuile({ cle: "sec1", lib: "Sessions ouvertes", val: sessions.length, icone: "personne", teinte: ENCRES.mer,
          sous: nouveaux ? quantite(nouveaux, "nouvel appareil") : "aucun nouvel appareil" }),
        tuile({ cle: "sec2", lib: "Actions du site", val: actions.length, icone: "discord", teinte: ENCRES.laiton,
          sous: actions.length ? "la dernière " + depuis(actions[0].quand) + (echecs ? " · " + quantite(echecs, "refusée(s)") : "") : "aucune encore" }),
        tuile({ cle: "sec3", lib: "Alertes", val: alertes.length, icone: "attention", teinte: alertes.length ? ENCRES.cire : ENCRES.vert,
          sous: alertes.length ? "la dernière " + depuis(alertes[0].quand) : "aucun signal fort" }),
        tuile({ cle: "sec4", lib: "Refus comptés", val: refus, icone: "cadenas", teinte: ENCRES.ardoise,
          sous: "depuis " + depuis(s.depuis) })),
      sectionSessions(s, () => maj(true)),
      section("Ce que le site a fait sur Discord", "discord", quantite(actions.length, "action(s)"),
        actions.length ? lignes("sec-actions", actions, ligneAction, { pas: 15 })
          : vide("Aucune action encore", "Chaque écriture faite depuis le site sera notée ici, réussie ou non.", "discord")),
      sectionPermissions(s.permissions || {}),
      h("div", { classe: "groupes-zone" }, groupes([
        { cle: "sec-evts", titre: "Alertes et faits notés", icone: "attention", compte: evts.length, chaud: alertes.length > 0,
          info: alertes.length ? quantite(alertes.length, "alerte(s)") : "aucune alerte",
          contenu: () => (evts.length ? lignes("sec-evts-l", evts, ligneEvenement)
            : vide("Rien à signaler", "Une alerte n'arrive ici que pour un signal fort : une action du site hors de la tête, une permission dangereuse donnée.", "succes")) },
        { cle: "sec-refus", titre: "Refus comptés", icone: "cadenas", compte: refus, info: "depuis le démarrage du bot",
          contenu: () => h("ul", { classe: "lignes-c" }, (s.refus || []).map((r) => ligne({
            visuel: pastilleIcone("cadenas", Number(r.n) ? ENCRES.ambre : ENCRES.ardoise), titre: r.libelle,
            badges: [pastille(String(r.n || 0), Number(r.n) ? ENCRES.ambre : null)] }))) },
      ], { ouverts: alertes.length ? 1 : 0 })));
  };
  maj();
  return { maj: () => maj(false) };
}

function sectionSessions(s, recharger) {
  const sessions = s.sessions || [];
  const urgence = bouton("Fermer toutes les autres sessions", { classe: "p danger", icone: "deconnexion", reseau: true, onclick: async () => {
    const ok = await confirmer({ titre: "Fermer toutes les autres sessions ?",
      texte: s.fondateur ? "Chaque autre navigateur ouvert sur le site, la direction comprise, devra redemander un lien. Le tien reste ouvert."
        : "Tes autres navigateurs devront redemander un lien. Celui-ci reste ouvert.", libelleOk: "Fermer les autres", style: "danger" });
    if (!ok) return;
    const r = await poster("securite/fermer_autres", {});
    if (!r.ok) { toast(r.erreur || "Les sessions n'ont pas pu être fermées.", "erreur"); return; }
    const n = (r.donnees && r.donnees.fermees) || 0;
    toast(n ? quantite(n, "session(s) fermée(s)") + "." : "Aucune autre session n'était ouverte.", "succes");
    recharger();
  } });
  return section("Les sessions ouvertes", "personne", quantite(sessions.length, "session(s)"),
    h("div", { classe: "pile serree" },
      h("ul", { classe: "lignes-c" }, sessions.map((x) => ligne({
        visuel: avatar(P(x.qui), "p"), titre: nomDe(P(x.qui)) + (x.moi ? " · cette session" : ""),
        sous: [x.appareil, x.adresse, "ouverte " + depuis(x.ouverte)].filter(Boolean).join(" · "),
        date: depuis(x.vue), dateTitre: "Dernière activité : " + date(x.vue, true),
        badges: [x.nouveau ? pastille("Nouvel appareil", ENCRES.ambre, "Première session depuis cet appareil et cette adresse") : null,
          x.moi ? pastille("Toi, ici", ENCRES.vert) : null], etat: x.moi ? "calme" : null }))),
      h("p", { classe: "aide" }, "Site de l'équipage : " + quantite(s.equipage || 0, "session(s) ouverte(s)") + ", en lecture seule."),
      h("div", { classe: "rangee entre" }, h("p", { classe: "aide" }, s.fondateur ? "En cas de doute (un appareil que tu ne connais pas), ferme tout le reste : la tienne reste ouverte."
        : "En cas de doute, ferme tes autres sessions : celle-ci reste ouverte."), urgence)));
}

function ligneAction(a) {
  const ok = Number(a.statut) < 400;
  return ligne({ visuel: pastilleIcone(ok ? "valider" : "attention", ok ? ENCRES.vert : ENCRES.cire), titre: sansEmoji(a.texte) || a.quoi,
    sous: [nomDe(P(a.qui)), a.appareil].filter(Boolean).join(" · "), date: depuis(a.quand), dateTitre: date(a.quand, true),
    badges: ok ? [] : [pastille(Number(a.statut) >= 500 ? "en échec" : "refusée", ENCRES.cire)] });
}

function ligneEvenement(e) {
  return ligne({ visuel: pastilleIcone(e.alerte ? "attention" : "journal", e.alerte ? ENCRES.cire : ENCRES.ardoise), titre: sansEmoji(e.texte),
    sous: e.qui ? nomDe(P(e.qui)) : "", date: depuis(e.quand), dateTitre: date(e.quand, true),
    badges: e.alerte ? [pastille("Alerte", ENCRES.cire)] : [],
    deplier: e.detail ? () => h("p", { classe: "texte" }, e.detail) : undefined });
}

function sectionPermissions(p) {
  const roles = p.roles || [];
  const proprio = p.proprietaire ? P(p.proprietaire) : null;
  return section("Qui a une permission dangereuse", "cle", quantite(roles.length, "rôle(s)"),
    h("div", { classe: "pile serree" },
      h("p", { classe: "aide" }, "Administrateur, gérer le serveur, gérer les rôles, bannir, expulser, gérer les webhooks : qui les a, et par quel rôle. Lecture seule : rien n'est retiré d'ici."),
      p.audit ? null : h("p", { classe: "aide" }, "Le bot ne peut pas lire le journal d'audit du serveur : une permission dangereuse donnée ne peut pas être signalée."),
      h("ul", { classe: "lignes-c" },
        proprio ? ligne({ visuel: avatar(proprio, "p"), titre: nomDe(proprio), sous: "Propriétaire du serveur : toutes les permissions",
          badges: [pastille("Propriétaire", ENCRES.laiton)] }) : null,
        roles.map((r) => ligne({ visuel: pastilleIcone("cle", r.couleur || ENCRES.ardoise), titre: r.tous ? "Tout le monde (@everyone)" : sansEmoji(r.nom) || "Rôle sans nom",
          sous: (r.permissions || []).join(", "), teinte: r.couleur || null,
          badges: [pastille(quantite(r.n, "membre(s)"), r.n ? null : ENCRES.vert), r.bots ? pastille(quantite(r.bots, "bot(s)")) : null,
            r.gere ? pastille("rôle d'une application") : null],
          deplier: (r.membres || []).length ? () => h("ul", { classe: "lignes-c" }, r.membres.map((id) => ligne({ visuel: avatar(P(id), "p"), titre: nomDe(P(id)) })))
            : undefined })))));
}
