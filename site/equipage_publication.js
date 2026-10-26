// equipage_publication.js — modifier une annonce ou un événement DÉJÀ PUBLIÉ, depuis l'accueil du site de l'équipage
// (26/10/2026). La tête seule : l'équipage n'a jamais ce bouton, et le serveur le refuse quand même (portée, tête).
// Le fondateur : « modifier les annonces qu'on a déjà postées, que ça se modifie bien, que ça riposte pas une annonce,
// mais que ça fasse un truc au propre ».
//   · Un éditeur propre : titre, texte, bannière (1600 × 640, banniere.js), liens — les règles de l'administration.
//   · L'aperçu AVANT d'enregistrer : la carte Discord rendue par le serveur (annonces_modifiables.py →
//     evenements.apercu_modification, le code même de l'administration ; le rendu de sa page, annonces.js) et
//     l'actualité telle que l'équipage la lira sur le site.
//   · « Enregistrer sur Discord » réécrit le message EN PLACE (même identifiant) : jamais republié, jamais un message
//     de plus (refusé, la raison dite). Version vérifiée (409) ; verrou de présence `evenement:<id>`, celui de
//     l'administration (les deux sites ne modifient jamais la même publication en même temps).

import { h, icone, remplacer, ajouter, sansEmoji, nombre, retarder, depuis, date } from "./dom.js";
import { lire, poster } from "./api.js";
import { bouton, boutonIcone, toast, pancarte, champ, saisie, zoneTexte, confirmer, bandeau, segment } from "./ui.js";
import { choixBanniere, cadreBanniere } from "./banniere.js";
import { texteRiche } from "./equipage_commun.js";

const NOMS = { annonce: "l'annonce", evenement: "l'événement", metiers: "l'annonce des métiers", listing: "le listing" };
const RE_URL = /^https:\/\/[^\s<>"'`]{3,505}$/;

/** L'identifiant de la publication d'une actualité automatique (« auto-pub-12 » → 12), ou null. */
export function idPublication(a) {
  const m = /^auto-pub-(\d{1,12})$/.exec(String((a && a.id) || ""));
  return m ? Number(m[1]) : null;
}
/** Une actualité automatique qui se modifie encore : une annonce publiée, un événement ni terminé ni annulé. */
export function modifiable(a) {
  if (!a || !idPublication(a)) return false;
  if (a.genre === "annonce") return true;
  return a.genre === "evenement" && !!a.evenement && ["a_venir", "en_cours"].includes(a.evenement.phase);
}

/** Le rendu de l'aperçu Discord de l'administration (annonces.js), chargé à la demande : la tête seule ouvre cet
 *  éditeur, l'équipage ne charge jamais ce module. */
let rendu = null;
async function apercuDiscord(d, o) {
  if (!rendu) rendu = import("./annonces.js").then((m) => m.apercuDiscord);
  return (await rendu)(d, o);
}

/** Ouvrir l'éditeur d'une publication. o : { proteger(p, objet, titre, relire), apres(accueil), carte(actualite) }. */
export async function editerPublication(a, o = {}) {
  const id = idPublication(a);
  if (!id) return;
  const r = await lire("equipage/publication", { id });
  if (!r.ok || !r.donnees || !r.donnees.publication) { toast(r.erreur || "Cette publication ne se lit pas pour le moment.", "erreur"); return; }
  const P = r.donnees.publication, lim = r.donnees.limites || {};
  if (!P.modifiable) {
    toast(P.type === "evenement" ? "Cet événement est terminé ou annulé : il ne se modifie plus." : "Cette publication n'est plus en ligne : elle ne se modifie plus.", "erreur");
    return;
  }
  const nom = NOMS[P.type] || "la publication";
  const v = { titre: P.titre || "", texte: P.texte || "", image: P.image || "", liens: (P.liens || []).map((x) => ({ nom: x.nom, url: x.url })) };
  let sale = false, enCours = false, disparu = false;
  const p = pancarte({ titre: "Modifier " + nom, sous: "Le message Discord est modifié sur place : rien n'est republié.", icone: "modifier", taille: "large",
    garde: async () => !sale || !!(await confirmer({ titre: "Abandonner tes changements ?", texte: "Rien n'est parti sur Discord. Tes changements seront perdus.", libelleOk: "Abandonner", style: "danger" })) });
  if (o.proteger) {
    o.proteger(p, "evenement:" + id, nom + " « " + sansEmoji(P.titre || "").slice(0, 60) + " »", async () => {
      sale = false;
      p.fermer();
      await editerPublication(a, o);
    });
  }
  // ─── Le formulaire ───
  const changer = () => { sale = true; majApercu(); };
  const compteur = (el, max) => {
    const c = h("span", { classe: "compteur-texte num" });
    const maj = () => { c.textContent = nombre(el.value.length) + " / " + nombre(max); c.classList.toggle("alerte", el.value.length > max * 0.95); };
    el.addEventListener("input", maj);
    maj();
    return c;
  };
  const titre = saisie({ value: v.titre, maxlength: lim.titre || 100, placeholder: "Le titre, en quelques mots" });
  titre.addEventListener("input", () => { v.titre = titre.value; changer(); });
  const texte = zoneTexte({ rows: 7, maxlength: lim.texte || 2000, placeholder: "Le message. **gras**, *italique*, __souligné__, > citation, - liste" }, v.texte);
  texte.addEventListener("input", () => { v.texte = texte.value; changer(); });
  const champTitre = champ("Titre", titre, { aide: compteur(titre, lim.titre || 100) });
  const champTexte = champ("Texte", texte, { aide: h("span", {}, compteur(texte, lim.texte || 2000), " · Markdown de Discord.") });
  const liens = h("div", { classe: "liens-editeur" });
  const majLiens = () => {
    remplacer(liens, ...v.liens.map((x, k) => {
      const n = saisie({ value: x.nom, maxlength: lim.lien_nom || 80, placeholder: "Nom du bouton", "aria-label": "Nom du lien " + (k + 1) });
      const u = saisie({ value: x.url, maxlength: lim.lien_url || 512, placeholder: "https://…", inputmode: "url", "aria-label": "Adresse du lien " + (k + 1), classe: "saisie lien-url" });
      n.addEventListener("input", () => { x.nom = n.value; changer(); });
      u.addEventListener("input", () => { x.url = u.value.trim(); u.setAttribute("aria-invalid", x.url && !RE_URL.test(x.url) ? "true" : "false"); changer(); });
      return h("div", { classe: "lien-ligne" }, n, u, boutonIcone("supprimer", "Retirer ce lien", () => { v.liens.splice(k, 1); majLiens(); changer(); }, "danger"));
    }), v.liens.length < (lim.liens || 5) ? bouton("Ajouter un lien", { classe: "p discret", icone: "ajouter", onclick: () => { v.liens.push({ nom: "", url: "" }); majLiens(); } }) : null);
  };
  majLiens();
  const champLiens = h("fieldset", { classe: "cadre pile serree bloc-form" }, h("legend", { classe: "cadre-titre" }, "Liens"),
    h("p", { classe: "aide" }, "Des boutons sous le texte, sur Discord (" + (lim.liens || 5) + " au plus) : un nom, une adresse en https://."), liens);
  const etat = h("div", { classe: "publication-etat" });
  const publie = P.type === "evenement" || P.type === "listing" ? "Publié" : "Publiée";
  const majEtat = (extra) => remplacer(etat,
    h("p", { classe: "meta" }, icone("discord"), " " + (P.publie ? publie + " " + depuis(P.publie) : publie) + (P.destination && P.destination.nom ? " dans « " + sansEmoji(P.destination.nom) + " »" : "")
      + (P.type === "evenement" && P.quand ? " · le " + date(P.quand, true) : "")),
    P.lien ? h("a", { classe: "bouton p discret", href: P.lien }, icone("discord"), h("span", {}, "Voir sur Discord")) : null,
    extra || null);
  majEtat(P.note ? bandeau(P.note, "") : null);
  const form = h("div", { classe: "pile" }, etat, champTitre, champTexte,
    choixBanniere(v, "image", { changer: () => changer(), aide: "Elle remplace l'image en tête de la carte Discord et de l'actualité du site." }), champLiens);
  // ─── L'aperçu : Discord (le serveur) ou le site ───
  let vue = "discord", dernier = null, jeton = 0;
  const zoneApercu = h("div", { classe: "apercu-zone" });
  const onglets = segment("discord", [["discord", "Sur Discord"], ["site", "Sur le site"]], (x) => { vue = x; dessinerApercu(); }, "Aperçu");
  onglets.classList.add("apercu-onglets");
  const corpsApercu = () => ({ id, titre: v.titre, texte: v.texte, image: v.image, liens: v.liens.filter((x) => x.nom || x.url) });
  async function chercherApercu() {
    const n = ++jeton;
    const rep = await poster("equipage/publication/apercu", corpsApercu());
    if (n !== jeton || p.fermee()) return;
    dernier = rep.ok && rep.donnees ? rep.donnees : { erreurs: [rep.erreur || "L'aperçu ne répond pas : réessaie dans un instant."], cartes: [] };
    dessinerApercu();
  }
  const majApercu = retarder(chercherApercu, 450);
  async function dessinerApercu() {
    if (p.fermee()) return;
    if (!dernier) { remplacer(zoneApercu, h("p", { classe: "aide" }, "Aperçu…")); return; }
    if (vue === "site") {
      // Ce que l'équipage verra : la carte de l'actualité (la liste de l'accueil), puis l'actualité ouverte.
      const s = dernier.site || {};
      const actu = { id: "apercu-" + id, genre: a.genre, titre: s.titre || v.titre, texte: s.texte || "", image: s.image || "", quand: a.quand, evenement: a.evenement || null, liens: s.liens || [] };
      const liensSite = (actu.liens || []).filter((x) => x && x.url);
      remplacer(zoneApercu, h("div", { classe: "apercu-site" },
        h("p", { classe: "aide" }, "Dans les actualités de l'accueil :"),
        o.carte ? o.carte(actu) : null,
        h("p", { classe: "aide" }, "Une fois ouverte :"),
        h("div", { classe: "lecture-actu cadre" },
          actu.image ? cadreBanniere(actu.image, { paresseux: false }) : null,
          h("h3", { classe: "actu-titre" }, sansEmoji(actu.titre)),
          actu.texte ? texteRiche(actu.texte) : h("p", { classe: "aide" }, "Pas de texte de plus."),
          liensSite.length ? h("div", { classe: "actu-liens" }, liensSite.map((x) => h("a", { href: x.url }, icone("droite"), h("span", {}, sansEmoji(x.nom) || "Lien")))) : null)));
      return;
    }
    try {
      remplacer(zoneApercu, await apercuDiscord(dernier, { local: false, destination: dernier.destination || P.destination }));
    } catch (e) {
      console.error("[equipage] aperçu Discord", e);
      remplacer(zoneApercu, bandeau("L'aperçu Discord n'a pas pu s'afficher.", "rouge"));
    }
  }
  // Au téléphone et sur une tablette (une seule colonne) : « Rédiger » ou « Aperçu », comme le composeur de l'administration.
  const editeur = h("div", { classe: "editeur-publication" }, h("div", { classe: "formulaire-colonne" }, form),
    h("div", { classe: "pile serree apercu-colonne" }, onglets, zoneApercu));
  const bascule = segment("form", [["form", "Rédiger"], ["apercu", "Aperçu"]], (x) => { editeur.classList.toggle("voir-apercu", x === "apercu"); }, "Vue");
  bascule.classList.add("bascule-editeur");
  //  (dans une ligne à part : un enfant direct de la pancarte qui coupe son contenu serait écrasé par sa grille)
  ajouter(p.corps, [h("div", { classe: "bascule-ligne" }, bascule), editeur]);
  // ─── Enregistrer ───
  const ok = bouton("Enregistrer sur Discord", { classe: "principal", icone: "valider", reseau: true, onclick: () => enregistrer() });
  async function enregistrer() {
    if (enCours || disparu) return;
    for (const c of [champTitre, champTexte]) c.erreur("");
    if (!v.titre.trim()) { champTitre.erreur("Le titre est obligatoire."); titre.focus(); return; }
    const faux = v.liens.find((x) => (x.nom || x.url) && (!x.nom.trim() || !RE_URL.test(x.url)));
    if (faux) { toast("Un lien a besoin d'un nom et d'une adresse complète en https://.", "erreur"); return; }
    enCours = true;
    ok.disabled = true;
    const rep = await poster("equipage/publication", { ...corpsApercu(), version: P.version });
    enCours = false;
    ok.disabled = false;
    const d = rep.donnees || {};
    if (rep.ok) {
      sale = false;
      if (o.apres && d.accueil) o.apres(d.accueil);
      toast((P.type === "evenement" ? "Événement modifié" : "Annonce modifiée") + " sur Discord : le même message, rien de republié.", "succes");
      if ((d.avertissements || []).length) toast(d.avertissements.join(" · "), "");
      p.fermer();
      return;
    }
    if (rep.status === 409 && d.disparu) {
      disparu = true;
      ok.disabled = true;
      ok.dataset.forceOff = "1";
      majEtat(bandeau(h("span", {}, h("b", {}, "Le message n'existe plus sur Discord. "), d.erreur || "Rien n'a été republié."), "rouge"));
      toast(d.erreur || "Le message n'existe plus sur Discord.", "erreur");
      return;
    }
    if (rep.status === 409 && d.conflit) {
      toast("Cette publication a changé ailleurs pendant ta saisie : la version enregistrée s'ouvre.", "erreur");
      sale = false;
      p.fermer();
      await editerPublication(a, o);
      return;
    }
    if (rep.status === 409) { toast(d.erreur || "Cette publication ne se modifie plus.", "erreur"); sale = false; p.fermer(); return; }
    const champs = d.champs || {};
    if (champs.titre) champTitre.erreur(champs.titre);
    if (champs.texte) champTexte.erreur(champs.texte);
    toast(rep.erreur || d.erreur || "Modification refusée.", "erreur");
    chercherApercu();
  }
  ajouter(p.pied, [bouton("Annuler", { classe: "discret", onclick: () => p.fermer() }), ok]);
  dessinerApercu();
  chercherApercu();
  requestAnimationFrame(() => titre.focus({ preventScroll: true }));   // la fenêtre reste en haut (« Rédiger · Aperçu » en vue)
}
