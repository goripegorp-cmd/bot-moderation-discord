// lien_equipage.js — « Copier le lien de l'équipage » : l'adresse PUBLIQUE de la vitrine (`/equipage`), le lien officiel
// à partager. Copiée dans le presse-papiers et dite (« Lien copié ») ; si le navigateur refuse, le lien est montré,
// sélectionné, prêt à copier. Sur le site de la direction (en haut à droite, près de « À bord »), sur le site de
// l'équipage et sur la vitrine elle-même. Les libellés se renomment (Textes & noms : « site.equipage.lien… »).

import { h, icone, ajouter } from "./dom.js";
import { libelle, ecouter, etat } from "./noyau.js";
import { toast, pancarte, bouton } from "./ui.js";

export const ADRESSE_VITRINE = "/equipage";
export const lienVitrine = () => location.origin + ADRESSE_VITRINE;
const libelleLien = () => libelle("site.equipage.lien", "Copier le lien de l'équipage");

/** Copier `texte` : le presse-papiers, sinon l'ancienne commande de copie ; true si c'est fait. */
async function copier(texte) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(texte);
      return true;
    }
  } catch (e) { /* refusé (permission, page en arrière-plan) : l'autre façon */ }
  const zone = h("textarea", { classe: "copie-cachee", readonly: "", "aria-hidden": "true", tabindex: "-1" });
  zone.value = texte;
  document.body.append(zone);
  try {
    zone.focus({ preventScroll: true });   // aucun saut de page vers le champ (il part aussitôt)
    zone.select();
    return document.execCommand("copy");
  } catch (e) {
    return false;
  } finally {
    zone.remove();
  }
}

/** Le lien montré, sélectionné : quand rien ne peut le copier tout seul. */
function montrer(lien) {
  const p = pancarte({ titre: libelleLien(), sous: "Le lien officiel de l'équipage", icone: "lien" });
  const champ = h("input", { classe: "saisie lien-equipage-champ", type: "text", readonly: "", value: lien, "aria-label": "Le lien de l'équipage" });
  champ.addEventListener("focus", () => champ.select());
  ajouter(p.corps, [h("p", {}, libelle("site.equipage.lien.repli", "Copie ce lien pour le partager :")), champ]);
  ajouter(p.pied, [bouton("Fermer", { classe: "discret", onclick: () => p.fermer() })]);
  setTimeout(() => { champ.focus(); champ.select(); }, 60);
}

/** Copier le lien de la vitrine, et le dire. */
export async function copierLienEquipage() {
  const lien = lienVitrine();
  if (await copier(lien)) toast(libelle("site.equipage.lien.copie", "Lien copié"), "succes");
  else montrer(lien);
}

/** Le bouton de l'en-tête : l'icône et le libellé (« Copier le lien de l'équipage ») sur une planche de bois ; au
 *  téléphone, l'icône seule. `o.iconeSeule` (l'en-tête chargé du site de la direction) : un bouton rond comme ses
 *  voisins (synchro, menu). Le libellé reste son nom pour les lecteurs d'écran et au survol ; renommé sur le site, il
 *  suit. */
export function boutonLienEquipage(o = {}) {
  const texte = o.iconeSeule ? null : h("span", { classe: "lien-equipage-lib" });
  const b = h("button", { classe: (o.iconeSeule ? "bouton-icone sur-bois" : "bouton bois") + " lien-equipage", type: "button",
    onclick: copierLienEquipage }, icone("lien"), texte);
  const nommer = () => {
    const l = libelleLien();
    if (texte) texte.textContent = l;
    b.title = l;
    b.setAttribute("aria-label", l);
  };
  nommer();
  ecouter("libelles", nommer);
  return b;
}

// ─── L'atelier des affiches (direction) : l'affiche d'un ANCIEN membre ──────
//  27/10/2026 : la vitrine montre l'équipage ACTUEL. L'affiche d'un membre qui n'a plus le rôle du clan (ou a quitté le
//  serveur) n'y paraît plus : elle reste dans l'atelier (rien n'est supprimé), avec cette mention, et revient sur la
//  vitrine s'il revient au clan. Une affiche sans membre lié : rien (la direction la gère à la main).
let memoClan = null, memoDonnees = null;
function idsDuClan() {
  const c = etat.d && etat.d.clan;
  if (!c || !c.role) return null;
  if (memoDonnees !== etat.d) {
    memoDonnees = etat.d;
    memoClan = new Set([...(c.membres || []), ...(c.direction || [])].map((m) => String(m.id)));
  }
  return memoClan;
}
export const texteAncien = () => libelle("site.equipage.ancien", "Ancien membre · masquée de la vitrine");
/** La carte `el` d'une affiche `a` (atelier) : la mention si son membre n'est plus au clan ; rend `el`. */
export function mentionAncien(el, a) {
  const id = a && a.membre && a.membre.id ? String(a.membre.id) : "";
  const clan = id ? idsDuClan() : null;
  if (!el || !clan || (clan.has(id) && a.membre.present !== false)) return el;
  el.classList.add("affiche-ancienne");
  ajouter(el, [h("span", { classe: "ruban-ancien", title: "Plus au clan : elle reste ici, et revient sur la vitrine s'il revient au clan." }, texteAncien())]);
  return el;
}
