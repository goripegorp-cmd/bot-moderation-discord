// banniere.js — la bannière aux dimensions exactes (26/10/2026). UNE taille pour chaque emplacement de bannière : la
// bannière d'une annonce ou d'un événement (en tête de sa carte Discord), le bandeau de l'Accueil du site de
// l'équipage, l'image d'une actualité — 1600 × 640 px, 5:2. L'éditeur l'annonce ; le serveur (`bannieres.py`, adresse
// `media` avec `format: "banniere"`) la REFAIT à cette taille : recadrage centré, jamais étirée ni agrandie ; trop petite,
// elle est refusée avec la taille reçue et la taille demandée. Partout où elle s'affiche, son cadre a le même rapport
// (`aspect-ratio: 5 / 2`, banniere.css) : rien d'écrasé, rien de rogné au hasard.
// Les nombres sont ceux de `bannieres.py` (tests/test_annonces_modifiables.py le vérifie).

import { h, icone, remplacer, srcSure } from "./dom.js";
import { poster } from "./api.js";
import { bouton, toast } from "./ui.js";

export const BANNIERE = Object.freeze({ largeur: 1600, hauteur: 640, rapport: "5:2", formats: "PNG, JPG ou WebP", octetsMax: 8 * 1024 * 1024,
  types: ["image/png", "image/jpeg", "image/webp"] });
export const CONSIGNE = "Bannière : 1600 × 640 px (5:2) · PNG, JPG ou WebP · 8 Mo au plus";
const TAILLE = BANNIERE.largeur + " × " + BANNIERE.hauteur + " px";
const RAPPORT = BANNIERE.largeur / BANNIERE.hauteur;

/** La taille d'une image TELLE QU'ELLE S'AFFICHE (orientation de l'appareil photo comprise), ou null si le navigateur
 *  ne sait pas la lire (le serveur tranchera). */
function tailleAffichee(fichier) {
  return new Promise((fin) => {
    let adresse = "";
    try { adresse = URL.createObjectURL(fichier); } catch (e) { fin(null); return; }
    const img = document.createElement("img");
    const finir = (x) => { try { URL.revokeObjectURL(adresse); } catch (e) { /* rien à rendre */ } fin(x); };
    img.onload = () => finir(img.naturalWidth && img.naturalHeight ? { l: img.naturalWidth, h: img.naturalHeight } : null);
    img.onerror = () => finir(null);
    img.src = adresse;
  });
}

/** Choisir une image sur l'appareil, la vérifier, l'envoyer comme bannière → la réponse du serveur ({ id, banniere: {
 *  source, coupe, recadree } }) ou null (refusée : l'avis est déjà dit). */
export function envoyerBanniere() {
  return new Promise((fin) => {
    const entree = h("input", { type: "file", accept: BANNIERE.types.join(",") });
    entree.addEventListener("change", async () => {
      const f = entree.files && entree.files[0];
      if (!f) { fin(null); return; }
      if (f.type && !BANNIERE.types.includes(f.type)) { toast("Format refusé : " + BANNIERE.formats + " seulement.", "erreur"); fin(null); return; }
      if (f.size > BANNIERE.octetsMax) { toast("Image trop lourde : 8 Mo au plus.", "erreur"); fin(null); return; }
      const t = await tailleAffichee(f);
      if (t && (t.l < BANNIERE.largeur || t.h < BANNIERE.hauteur)) {
        toast("Image trop petite : " + t.l + " × " + t.h + " px reçue, il faut au moins " + TAILLE + " (" + BANNIERE.rapport + ").", "erreur");
        fin(null);
        return;
      }
      let b64 = "";
      try {
        b64 = await new Promise((ok, ko) => { const l = new FileReader(); l.onload = () => ok(String(l.result).split(",")[1] || ""); l.onerror = () => ko(l.error); l.readAsDataURL(f); });
      } catch (e) {
        console.warn("[BANNIERE][E1] image illisible sur l'appareil");
        toast("Cette image ne se lit pas sur l'appareil.", "erreur");
        fin(null);
        return;
      }
      toast("Envoi de la bannière…");
      const r = await poster("media", { nom: f.name.slice(0, 80), type: f.type, base64: b64, format: "banniere" });
      if (r.ok && r.donnees && r.donnees.id) { fin(r.donnees); return; }
      toast(r.erreur || "Bannière refusée.", "erreur");
      fin(null);
    });
    entree.click();
  });
}

/** La phrase qui dit ce que le serveur a fait de l'image reçue. */
export function noteCadrage(b) {
  const x = (b && b.banniere) || null;
  if (!x || !Array.isArray(x.source)) return "";
  const [l, hh] = x.source;
  if (!x.recadree) return l === BANNIERE.largeur && hh === BANNIERE.hauteur ? "Aux dimensions exactes." : "Réduite à " + TAILLE + ", sans rien couper.";
  return "Recadrée au centre : " + l + " × " + hh + " px → " + TAILLE + ".";
}

/** Une bannière affichée dans son cadre 5:2. Une image d'avant (pas au rapport 5:2) n'est pas rognée : elle s'y montre
 *  entière, sur le papier. `src` : une adresse du site (« media/… »). */
export function cadreBanniere(src, o = {}) {
  const s = srcSure(src);
  const fig = h("figure", { classe: "banniere-cadre" + (o.classe ? " " + o.classe : "") });
  if (!s) { remplacer(fig, h("span", { classe: "banniere-vide" }, icone("image"), h("span", {}, o.vide || TAILLE))); fig.classList.add("vide"); return fig; }
  const img = h("img", { src: s, alt: o.alt || "", loading: o.paresseux === false ? null : "lazy", decoding: "async" });
  img.addEventListener("load", () => {
    const r = img.naturalWidth / (img.naturalHeight || 1);
    fig.classList.toggle("hors-format", Math.abs(r - RAPPORT) > 0.03);
  }, { once: true });
  img.addEventListener("error", () => { remplacer(fig, h("span", { classe: "banniere-vide" }, icone("image"), h("span", {}, "Image absente"))); fig.classList.add("vide"); }, { once: true });
  remplacer(fig, img);
  return fig;
}

const versMedia = (id) => (id ? (String(id).startsWith("media/") ? String(id) : "media/" + id) : "");

/** Le choix d'une bannière dans un formulaire : la taille demandée, l'aperçu dans son cadre, « Choisir une image » ou
 *  « Changer l'image », « Retirer ». `v[cle]` : un identifiant d'image (ou « media/… »). `changer()` : après chaque choix. */
export function choixBanniere(v, cle, o = {}) {
  const note = h("p", { classe: "aide banniere-note", "aria-live": "polite" });
  const zone = h("div", { classe: "image-choix banniere-choix" });
  const maj = () => {
    remplacer(zone, cadreBanniere(versMedia(v[cle]), { vide: TAILLE + " (" + BANNIERE.rapport + ")", paresseux: false }),
      h("div", { classe: "rangee" },
        bouton(v[cle] ? "Changer l'image" : "Choisir une image", { classe: "p", icone: "image", reseau: true, onclick: async () => {
          const r = await envoyerBanniere();
          if (!r) return;
          v[cle] = r.id;
          maj();
          note.textContent = noteCadrage(r);
          toast("Bannière prête. " + noteCadrage(r), "succes");
          if (o.changer) o.changer(v[cle]);
        } }),
        v[cle] && !o.requis ? bouton("Retirer l'image", { classe: "p discret", onclick: () => { v[cle] = ""; note.textContent = ""; maj(); if (o.changer) o.changer(""); } }) : null),
      note);
  };
  maj();
  return h("div", { classe: "champ banniere-champ" },
    h("span", { classe: "champ-lib" }, o.libelle || "Bannière", o.requis ? null : h("span", { classe: "optionnel" }, " (facultatif)")),
    h("p", { classe: "banniere-consigne" }, icone("image"), h("span", {}, CONSIGNE)),
    o.aide ? h("p", { classe: "aide" }, o.aide) : null,
    zone);
}
