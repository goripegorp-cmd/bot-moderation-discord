// tickets_interdits.js — le bloc « Tickets » de la fiche d'une personne (27/10/2026), juste sous les sanctions : ce qui lui
// est interdit (les tickets du serveur, ceux du clan), depuis quand, par qui, pourquoi ; interdire, lever l'interdiction,
// et le réglage fin panneau par panneau. Le fondateur : « qu'on décide de quel type de ticket il n'a pas le droit de
// créer… plutôt que d'utiliser une commande sur le serveur Discord. » SILENCIEUX : la personne n'est jamais prévenue ;
// elle l'apprend en touchant un panneau interdit (un avis générique, pour elle seule). Serveur : tickets_interdits.py.

import { h, date, sansEmoji, remplacer, ajouter } from "./dom.js";
import { peutAgir, libelle, ecouter, emettre, P } from "./noyau.js";
import { lire, poster } from "./api.js";
import { bouton, tampon, confirmer, toast, pancarte, nomDe, champ, saisie, majBoutonsReseau } from "./ui.js";

const L = (cle, defaut) => libelle("site.fiche.tickets." + cle, defaut);
const NOMS = { serveur: () => L("serveur", "Tickets du serveur"), clan: () => L("clan", "Tickets du clan") };
const ETATS = { autorise: ["Autorisé", "vert"], interdit: ["Interdit", ""], partiel: ["En partie", "ambre"] };
const memoire = new Map();   // membre → { t, v } : relu après une minute, et après chaque écriture
ecouter("recharger", () => memoire.clear());

async function lireEtat(id, forcer) {
  const c = memoire.get(id);
  if (c && !forcer && Date.now() - c.t < 60000) return c.v;
  const r = await lire("tickets/interdictions", { membre: id });
  if (!r.ok || !r.donnees) return null;
  memoire.set(id, { t: Date.now(), v: r.donnees });
  return r.donnees;
}

/** Depuis quand, par qui, pourquoi (la tête seule le lit). */
function decor(x) {
  return [x.depuis ? "depuis le " + date(x.depuis) : "posée sur Discord, sans date", x.par ? "par " + nomDe(P(x.par)) : "",
    x.motif ? "« " + x.motif + " »" : ""].filter(Boolean).join(" · ");
}

/** Le bloc de la fiche (null : rien à montrer — pas la tête, un robot, le fondateur ou la direction). */
export function blocTickets(m) {
  if (!m || !peutAgir() || m.bot || m.protege) return null;
  const id = String(m.id);
  const zone = h("section", { classe: "cadre pile serree fiche-agir fiche-tickets", "aria-label": L("titre", "Tickets") });
  const montrer = (e) => {
    if (!zone.isConnected && zone.dataset.vu) return;
    zone.dataset.vu = "1";
    remplacer(zone, ...contenu(m, e));
    majBoutonsReseau(zone);
  };
  // La place gardée pendant la lecture : la même hauteur que le bloc (rien ne saute sous les doigts).
  remplacer(zone, tete(null), ...["serveur", "clan"].map((f) => h("div", { classe: "ti-ligne" }, h("span", { classe: "ti-nom" }, NOMS[f]()),
    h("span", { classe: "squelette ti-squelette", "aria-hidden": "true" }))));
  lireEtat(id).then((e) => { if (e) montrer(e); else remplacer(zone, tete(null), h("p", { classe: "aide" }, "Interdictions de tickets illisibles pour le moment.")); });
  const stop = ecouter("tickets:interdictions", (qui) => {
    if (zone.dataset.vu && !zone.isConnected) { stop(); return; }
    if (qui === id && memoire.has(id)) montrer(memoire.get(id).v);
  });
  return zone;
}

function tete(e) {
  const F = e && e.familles;
  const deux = F && F.serveur.etat !== "aucun" && F.clan.etat !== "aucun" && (F.serveur.etat !== "interdit" || F.clan.etat !== "interdit");
  return h("div", { classe: "ti-tete" }, h("span", { classe: "champ-lib" }, L("titre", "Tickets")),
    e && !e.protege ? h("div", { classe: "rangee" },
      deux ? bouton(L("deux", "Interdire les deux"), { classe: "p danger", icone: "cadenas", reseau: true, onclick: () => interdire(e, ["serveur", "clan"], []) }) : null,
      bouton(L("panneaux", "Panneau par panneau"), { classe: "p discret", icone: "tickets", onclick: () => ouvrirPanneaux(e) })) : null);
}

function contenu(m, e) {
  if (e.protege) return [tete(e), h("p", { classe: "aide" }, e.protege)];
  return [tete(e), ...["serveur", "clan"].map((f) => ligneFamille(e, f)).filter(Boolean)];
}

function ligneFamille(e, f) {
  const x = e.familles[f];
  if (!x || x.etat === "aucun") return null;
  const [lib, teinte] = ETATS[x.etat] || ETATS.autorise;
  const detail = x.etat === "autorise" ? "" : (x.etat === "partiel" ? (x.noms || []).map(sansEmoji).join(", ") + " · " : "") + decor(x);
  const action = x.etat === "autorise"
    ? bouton(L("interdire", "Interdire"), { classe: "p", icone: "cadenas", reseau: true, onclick: () => interdire(e, [f], []) })
    : bouton(L("lever", "Lever l'interdiction"), { classe: "p vert", icone: "valider", reseau: true, onclick: () => lever(e, [f], []) });
  return h("div", { classe: "ti-ligne", "data-famille": f, "data-etat": x.etat }, h("span", { classe: "ti-nom" }, NOMS[f]()),
    tampon(lib, teinte, true), h("span", { classe: "ti-detail" }, detail), h("div", { classe: "rangee ti-actions" }, action));
}

/** « les tickets du serveur », « les tickets du serveur et du clan », « le panneau « Support » ». */
function quoi(e, familles, panneaux) {
  if (familles.length === 2) return "les tickets du serveur et du clan";
  if (familles.length) return familles[0] === "clan" ? "les tickets du clan" : "les tickets du serveur";
  const p = e.panneaux.find((x) => x.id === panneaux[0]);
  return "le panneau « " + sansEmoji(p ? p.nom : panneaux[0]) + " »";
}

async function interdire(e, familles, panneaux) {
  const motif = saisie({ name: "motif", maxlength: 150, placeholder: "Motif (facultatif)" });
  const r = await confirmer({ titre: "Interdire " + quoi(e, familles, panneaux) + " ?", style: "danger", libelleOk: "Interdire", iconeOk: "cadenas",
    texte: nomDe(P(e.membre)) + " ne pourra plus les ouvrir. Il n'est pas prévenu : s'il touche un panneau interdit, un avis lui dit seulement qu'il ne peut pas ouvrir ce type de ticket.",
    contenu: champ("Motif court", motif, { optionnel: true, aide: "Lu par la direction seule, ici et au journal." }) });
  if (!r) return;
  await ecrire(e, "tickets/interdire", { membre: e.membre, version: e.version, familles, panneaux, motif: motif.value.trim() });
}

async function lever(e, familles, panneaux) {
  const r = await confirmer({ titre: "Lever l'interdiction : " + quoi(e, familles, panneaux) + " ?", style: "vert", libelleOk: "Lever", iconeOk: "valider",
    texte: nomDe(P(e.membre)) + " pourra de nouveau les ouvrir. Il n'est pas prévenu." });
  if (!r) return;
  await ecrire(e, "tickets/lever", { membre: e.membre, version: e.version, familles, panneaux });
}

async function ecrire(e, nom, corps) {
  const r = await poster(nom, corps);
  const d = r.donnees || {};
  if (d.etat) memoire.set(e.membre, { t: Date.now(), v: d.etat });
  else await lireEtat(e.membre, true);
  toast(r.ok ? d.message : r.erreur, r.ok ? "succes" : "erreur");
  emettre("tickets:interdictions", e.membre);   // le bloc de la fiche et la fenêtre « Panneau par panneau » se redessinent
}

// ─── Le réglage fin : chaque panneau, un par un ─────────────────────────────
function ouvrirPanneaux(e0) {
  const p = pancarte({ titre: L("panneaux", "Panneau par panneau"), sous: nomDe(P(e0.membre)), icone: "tickets" });
  const zone = h("div", { classe: "pile serree" });
  const dessiner = (e) => {
    const groupes = [["serveur", "Serveur"], ["clan", "Clan · RELL Seas"]].map(([f, titre]) => {
      const liste = e.panneaux.filter((x) => x.famille === f);
      return liste.length ? h("section", { classe: "ti-famille" }, h("h3", { classe: "champ-lib" }, titre),
        h("ul", { classe: "ti-panneaux" }, liste.map((x) => h("li", { classe: "ti-panneau", "data-panneau": x.id },
          h("span", { classe: "ti-nom" }, sansEmoji(x.nom) || x.nom, x.ferme ? h("span", { classe: "ti-ferme" }, " · fermé") : null),
          tampon(x.interdit ? "Interdit" : "Autorisé", x.interdit ? "" : "vert", true),
          x.interdit ? h("span", { classe: "ti-detail" }, decor(x)) : null,
          x.interdit ? bouton("Lever", { classe: "p vert", icone: "valider", reseau: true, onclick: () => lever(e, [], [x.id]) })
            : bouton("Interdire", { classe: "p", icone: "cadenas", reseau: true, onclick: () => interdire(e, [], [x.id]) }))))) : null;
    }).filter(Boolean);
    remplacer(zone, h("p", { classe: "aide" }, "Un panneau à la fois. Le clan entier passe aussi par la liste noire du recrutement."), ...groupes);
    majBoutonsReseau(zone);
  };
  ajouter(p.corps, [zone]);
  ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
  dessiner(e0);
  const stop = ecouter("tickets:interdictions", (qui) => {
    if (p.fermee()) { stop(); return; }
    if (qui === e0.membre && memoire.has(qui)) dessiner(memoire.get(qui).v);
  });
}
