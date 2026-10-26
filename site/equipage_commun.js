// equipage_commun.js — ce que partagent les pages du site de l'équipage : l'état, les lectures (`/tableau/equipage/api/…`,
// en lecture seule), les textes renommables par la direction, l'affiche en grand, le texte « riche » (**gras** seulement).
// Aucune donnée n'est écrite en HTML : tout passe par h() (dom.js).

import { h, icone, sansEmoji, nombre, ajouter, majuscule } from "./dom.js";
import { etat } from "./noyau.js";
import { sessionTerminee, poster } from "./api.js";
import { pancarte, bouton, toast, interrupteur } from "./ui.js";
import { affiche, insignes, nomAffiche, gradeDe, insigneImage, STATUTS_AFFICHE, primeNoeud } from "./affiche.js";

export const RACINE = "/tableau/equipage";
const DELAI = 15000;

/** L'état de la page : `depart` (qui, le serveur, le mode édition), `equipage` (affiches, catalogue, la mienne),
 *  `accueil` (blocs et leurs données), `textes` (les libellés renommés par la direction). */
export const E = { depart: null, equipage: null, accueil: null, textes: {}, peutEditer: false, modeEdition: false };

/** Un libellé de la page : celui que la direction a choisi (registre `textes.py`, famille « Le site de l'équipage »,
 *  servi par la lecture `depart`), sinon le texte d'origine donné ici en repli. */
export function T(cle, defaut) {
  const v = E.textes && E.textes["equipage_site." + cle];
  return typeof v === "string" && v.trim() ? v : defaut;
}

/** GET `/tableau/equipage/api/<nom>` → { ok, status, donnees, erreur } — ne lève jamais. 401 / 403 : la session est
 *  finie (rôle du clan retiré, lien expiré, déconnexion ailleurs) : la page le dit et n'appelle plus le serveur. */
export async function lire(nom) {
  if (etat.session !== "ok") return { ok: false, status: 401, erreur: "Session terminée." };
  let r;
  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), DELAI);
  try {
    r = await fetch(RACINE + "/api/" + nom, { credentials: "same-origin", cache: "no-store", signal: ctrl.signal });
  } catch (e) {
    return { ok: false, status: 0, erreur: "Pas de connexion : réessaie dans un instant." };
  } finally {
    clearTimeout(minuteur);
  }
  let corps = null;
  try { corps = await r.json(); } catch (e) { corps = null; }
  const message = (corps && (corps.erreur || corps.message)) || "";
  if (r.status === 401 || r.status === 403) {
    sessionTerminee(message || "Accès retiré.");
    return { ok: false, status: r.status, erreur: message || "Accès retiré." };
  }
  if (!r.ok || !corps) return { ok: false, status: r.status, erreur: message || "Indisponible pour le moment." };
  return { ok: true, status: r.status, donnees: corps };
}

// ─── Le texte « riche » : des paragraphes, des retours à la ligne, le **gras** — rien d'autre ──────────────
function gras(ligne) {
  return String(ligne).split(/(\*\*[^*\n]+\*\*)/g).filter(Boolean)
    .map((s) => (/^\*\*[^*\n]+\*\*$/.test(s) ? h("b", {}, s.slice(2, -2)) : s));
}
export function texteRiche(texte, classe) {
  const paragraphes = String(texte || "").replace(/\r\n?/g, "\n").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return h("div", { classe: "texte-riche" + (classe ? " " + classe : "") }, paragraphes.map((p) => h("p", {},
    p.split("\n").flatMap((l, i) => (i ? [h("br"), ...gras(l)] : gras(l))))));
}
/** Le texte sans ses marques de gras (un résumé sur une ligne). */
export const textePlat = (texte) => String(texte || "").replace(/\*\*/g, "").replace(/\s+/g, " ").trim();

// ─── Les affiches ───────────────────────────────────────────────────────────
export const afficheParId = (id) => ((E.equipage && E.equipage.affiches) || []).find((a) => String(a.id) === String(id)) || null;
export const catalogue = () => (E.equipage && E.equipage.catalogue) || { types: [], elements: [] };

/** Le rang d'une prime dans l'équipage (1 : la plus haute), ou 0 sans prime. */
export function rangPrime(a) {
  if (!a || !(Number(a.prime) > 0)) return 0;
  return 1 + ((E.equipage && E.equipage.affiches) || []).filter((x) => Number(x.prime) > Number(a.prime)).length;
}

/** Les détails lus d'une affiche : prime, grade, niveau, statut, puis ses insignes (icônes officielles). */
export function detailsAffiche(a) {
  const cat = catalogue();
  const ins = insignes(a, cat);
  const ligne = (k, v) => h("div", {}, h("dt", {}, k), h("dd", {}, v));
  const rang = rangPrime(a);
  const total = ((E.equipage && E.equipage.affiches) || []).length;
  return h("div", { classe: "pile affiche-details" },
    h("dl", { classe: "champs-lus" },
      ligne("Prime", h("span", { classe: "num" }, primeNoeud(a.prime || 0), rang ? h("span", { classe: "rang-prime" }, " · " + rang + (rang === 1 ? "re" : "e") + " sur " + nombre(total)) : null)),
      ligne("Grade", gradeDe(a, cat) || "—"),
      ligne("Niveau", a.niveau ? nombre(a.niveau) : "—"),
      ligne("Statut", STATUTS_AFFICHE[a.statut] || majuscule(sansEmoji(a.statut)) || "—"),
      a.membre && a.membre.nom ? ligne("Sur Discord", sansEmoji(a.membre.nom)) : null),
    ins.length
      ? h("ul", { classe: "insignes-liste" }, ins.map((i) => h("li", {}, insigneImage(i, "insigne-liste-img"), h("span", {}, h("b", {}, i.nom), h("small", {}, i.typeNom)))))
      : h("p", { classe: "aide" }, "Aucun insigne pour le moment."));
}

/** Une affiche en grand, en lecture seule : aucun bouton d'action, seulement « Fermer » (la direction, en plus : la
 *  vitrine publique, oui ou non). */
export function ouvrirAffiche(id) {
  const a = afficheParId(id);
  if (!a) { toast("Cette affiche n'est plus au mur.", "erreur"); return; }
  const p = pancarte({ titre: "Affiche de " + nomAffiche(a), sous: a.surnom ? "« " + sansEmoji(a.surnom) + " »" : "", icone: "affiches", taille: "large" });
  ajouter(p.corps, [h("div", { classe: "affiche-grand" }, h("div", { classe: "affiche-grand-mur" }, affiche(a, catalogue(), { taille: "grande" })),
    h("div", { classe: "pile" }, detailsAffiche(a), reglageVitrine(a)))]);
  ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
}

/** La direction (site de l'équipage) : cette affiche sur la vitrine publique — oui par défaut — ou retirée (elle reste
 *  au mur de l'équipage). L'équipage et la vitrine ne voient jamais ce réglage. */
function reglageVitrine(a) {
  const v = E.peutEditer && E.equipage && E.equipage.vitrine;
  if (!v) return null;
  const visible = !(v.masquees || []).includes(String(a.id));
  return h("div", { classe: "reglage-vitrine" },
    interrupteur("Visible sur la vitrine publique", visible, async (oui, i) => {
      i.disabled = true;
      const r = await poster("equipage/vitrine/affiche", { id: a.id, visible: oui });
      i.disabled = false;
      if (!r.ok) { i.checked = !oui; toast(r.erreur || "Refusé.", "erreur"); return; }
      v.masquees = (r.donnees && r.donnees.masquees) || [];
      toast(oui ? "Affiche remise sur la vitrine publique." : "Affiche retirée de la vitrine publique : seul l'équipage la voit.", "succes");
      if (E.majMur) E.majMur();
    }),
    h("p", { classe: "aide" }, "La vitrine publique, c'est le lien de l'équipage : tout le monde la voit, sans compte."));
}

/** Le sceau rond d'un titre de bloc (comme ceux des rubriques). */
export const sceau = (nomIcone) => h("span", { classe: "sceau-bloc", "aria-hidden": "true" }, icone(nomIcone));
