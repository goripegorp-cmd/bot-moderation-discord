"""L'écran « Renvoyer le message aux inactifs », et les boutons élagués.

DEMANDE DU PROPRIÉTAIRE (20/08/2026)
    « Fais en sorte que […] je puisse renvoyer le message qui pique tout le
      monde […] Refais les boutons d'ailleurs en bas pour que je puisse bien
      comprendre, pour renvoyer au propre et tout. Gardez que les boutons les
      plus efficaces. »

Il n'existait AUCUN bouton pour renvoyer : l'envoi n'était atteignable que le
jour configuré, une fois par semaine.

⚠️ CE QUE CET ÉCRAN NE FAIT PAS, ET C'EST VOLONTAIRE.
  · Il ne reclasse pas : il appelle `passage(dry_run=True)`, qui applique le
    rationnement du quota. Reclasser localement enverrait des membres qu'on a
    explicitement REPORTÉS, et le message annoncerait une action non faite.
  · Il n'écrit pas le marqueur hebdomadaire du groupe hors du jour prévu : un
    renvoi le mercredi ne doit pas consommer le rappel du dimanche.
  · Il ne SUPPRIME pas les messages en place quand il n'y a personne à
    relancer (`purger_si_vide=False`) — sinon un clic un jour calme viderait le
    salon en rapportant « 0 envoyé ».

⚠️ LE DEUXIÈME BOUTON N'EST PAS UN LUXE. Les étiquettes sont GLOBALES et le
marqueur anti-doublon est par groupe : si le rôle a déjà été mentionné cette
semaine, « Envoyer maintenant » repinguerait des centaines de personnes. D'où
« Envoyer sans mentionner », et l'avertissement affiché AVANT le clic.

Écrit dans un fichier puis exécuté (piège n°3 : les heredocs). `--apply`.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

CIBLE = Path(__file__).resolve().parent.parent / "activite_panneau.py"

#  ═══ 1. L'écran, posé juste avant la racine ═══
ANCRE = '''# ═══════════════════════════════════════════════════════════════════════════════
#  RACINE
# ═══════════════════════════════════════════════════════════════════════════════'''

ECRAN = '''# ═══════════════════════════════════════════════════════════════════════════════
#  RENVOI MANUEL DES RAPPELS
# ═══════════════════════════════════════════════════════════════════════════════

class ActiviteRenvoiPanelV2(_Base):
    """Renvoyer les messages d'inactivité, sans attendre le jour du rappel.

    Montre D'ABORD ce qui partirait, puis demande le clic. Le calcul est un
    `dry_run` du VRAI passage : ce qui est affiché est exactement ce qui sera
    envoyé, rationnement du quota compris.
    """

    async def render_to(self, i, edit: bool = False):
        try:
            #  ⚠️ ACQUITTER D'ABORD : le classement balaie tous les membres du
            #  serveur avec une lecture en base chacun — très au-delà des trois
            #  secondes de Discord sur un millier de membres.
            if not i.response.is_done():
                await i.response.defer()
            c = await activite.config(self.g.id)
            rap = await passage.passage(self.g, dry_run=True)
            cl = rap.get("fiches") or {}
            semaine = cal.semaine()
            deja = str(c.get("activite_derniere_semaine") or "") == semaine

            items = [
                v2_title("📣 Renvoyer le message aux inactifs"),
                v2_subtitle("Ce qui partirait maintenant, avant de cliquer"),
                v2_divider(),
            ]

            if not rap.get("actif"):
                items.append(v2_body(
                    f"⚪ **Rien ne partira** — {rap.get('raison') or 'système éteint'}."))
            elif rap.get("suivi_muet"):
                items.append(v2_body(
                    "🔴 **Rien ne partira** — aucune activité n'est enregistrée "
                    "alors que le suivi tourne. Les sondes ne captent rien ; "
                    "relancer maintenant accuserait tout le monde à tort."))
            else:
                cls = rap.get("classement") or {}
                items.append(v2_body(
                    f"👀 `{cls.get('doux', 0)}` peu actifs · "
                    f"💤 `{cls.get('rappel', 0)}` absents · "
                    f"🔒 `{cls.get('retrait', 0)}` rôles retirés · "
                    f"🚪 `{cls.get('expulsion', 0)}` abandonnés"))
                detail = (rap.get("actions") or {}).get("rappels_par_role") or []
                if detail:
                    items.append(v2_body("\\n".join(f"-# {d}" for d in detail[:6])))

            #  ⚠️ LA PERMISSION DE MENTIONNER, DITE AVANT LE CLIC. Sans elle la
            #  mention s'affiche et ne notifie personne — le bouton semblerait
            #  marcher alors que personne n'est prévenu.
            if not self.g.me.guild_permissions.mention_everyone:
                items.append(v2_body(
                    "-# 🔴 Il manque au bot **« Mentionner tous les rôles »** : "
                    "la mention s'affichera sans notifier personne."))
            if deja:
                items.append(v2_body(
                    "-# ⚠️ Les rôles ont **déjà été mentionnés cette semaine**. "
                    "Un nouvel envoi les notifierait une seconde fois : "
                    "préférez « Envoyer sans mentionner »."))

            b_go = Button(
                label="Mentionner quand même" if deja else "Envoyer maintenant",
                emoji="📣",
                style=(discord.ButtonStyle.danger if deja
                       else discord.ButtonStyle.primary),
                custom_id="act_rv_go",
                disabled=not rap.get("actif") or bool(rap.get("suivi_muet")))
            b_go.callback = self._cb_envoyer(muet=False)
            b_muet = Button(label="Envoyer sans mentionner", emoji="🔕",
                            style=discord.ButtonStyle.secondary,
                            custom_id="act_rv_muet",
                            disabled=not rap.get("actif"))
            b_muet.callback = self._cb_envoyer(muet=True)

            items.append(discord.ui.ActionRow(
                b_go, b_muet, _bouton_retour(self._cb_retour, "act_rv_back")))
            await self._envoyer(i, items, Palette.INFO, edit=True)
        except Exception as ex:
            await self._secours(i, ex, "renvoi")

    def _cb_envoyer(self, *, muet: bool):
        async def _cb(i):
            try:
                if not i.response.is_done():
                    await i.response.defer()
                c = await activite.config(self.g.id)
                rap = await passage.passage(self.g, dry_run=True)
                cl = rap.get("fiches") or {}
                #  ⚠️ LE MÊME CHEMIN QUE LA BOUCLE. Une seconde implémentation
                #  d'envoi divergerait au premier correctif.
                res = await passage.envoyer_rappels(
                    self.g, c, cl, forcer=True, muet_force=muet)
                n = res["envoyes"]
                if n:
                    txt_ = (f"✅ `{n}` message(s) envoyé(s)"
                            + ("" if muet else " · les rôles ont été mentionnés"))
                else:
                    #  ⚠️ ON DIT POURQUOI ZÉRO. « 0 envoyé » sans motif ferait
                    #  chercher une panne là où il n'y a personne à relancer.
                    motifs = " · ".join((res.get("detail") or [])[:3])
                    txt_ = f"⚪ Aucun message envoyé — {motifs or 'personne à relancer'}"
                await i.followup.send(txt_, ephemeral=True)
                await self.render_to(i, edit=True)
            except Exception as ex:
                await self._secours(i, ex, "renvoi envoi")
        return _cb

    async def _cb_retour(self, i):
        await ActivitePanelV2(self.u, self.g).render_to(i, edit=True)


''' + ANCRE

REMPLACEMENTS = [
    ("ecran", ANCRE, ECRAN),
    #  ═══ 2. La rangée « agir » de l'écran racine ═══
    ("racine",
     '''            items.append(discord.ui.ActionRow(b_on, b_cibles, b_salons, b_afk))
            items.append(discord.ui.ActionRow(
                b_rec, b_ap, b_disp, _bouton_retour(self._cb_retour, "act_back")))''',
     '''            #  ⚠️ DEUX RANGÉES, DEUX INTENTIONS — refait le 20/08 à la
            #  demande du propriétaire (« gardez que les boutons les plus
            #  efficaces »). En haut on RÈGLE, en bas on AGIT. Le bouton de
            #  renvoi est le premier de la rangée du bas : c'est celui qu'il
            #  vient chercher.
            #  « Dispenses » quitte la racine — une ActionRow tient 5
            #  composants, et il n'est utile qu'une fois, au réglage.
            b_rv = Button(label="Renvoyer le message aux inactifs", emoji="📣",
                          style=discord.ButtonStyle.primary, custom_id="act_renvoi")
            b_rv.callback = self._cb_renvoi
            items.append(discord.ui.ActionRow(b_on, b_cibles, b_salons, b_afk,
                                              b_rec))
            items.append(discord.ui.ActionRow(
                b_rv, b_ap, b_disp, _bouton_retour(self._cb_retour, "act_back")))'''),
]

CB_RENVOI = '''    async def _cb_renvoi(self, i):
        """Ouvre l'écran de renvoi. Demande n°1 du propriétaire le 20/08."""
        await ActiviteRenvoiPanelV2(self.u, self.g).render_to(i, edit=True)

'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    avant = {getattr(n, "name", None) for n in ast.parse(src).body}
    if "class ActiviteRenvoiPanelV2" in src:
        print("❌ déjà appliqué.")
        return 1

    neuf = src
    for nom, a, b in REMPLACEMENTS:
        if neuf.count(a) != 1:
            print(f"❌ ancre « {nom} » trouvée {neuf.count(a)} fois — abandon.")
            return 1
        neuf = neuf.replace(a, b, 1)

    #  Le callback, posé juste avant `_cb_apercu` de la racine.
    ancre_cb = "    async def _cb_apercu(self, i):"
    if neuf.count(ancre_cb) != 1:
        print(f"❌ ancre callback trouvée {neuf.count(ancre_cb)} fois.")
        return 1
    neuf = neuf.replace(ancre_cb, CB_RENVOI + ancre_cb, 1)

    try:
        arbre = ast.parse(neuf)
    except SyntaxError as ex:
        print(f"❌ ast.parse l.{ex.lineno} : {ex.msg}")
        return 1
    apres = {getattr(n, "name", None) for n in arbre.body}
    if avant - apres:
        print(f"❌ symboles perdus : {avant - apres}")
        return 1
    if "ActiviteRenvoiPanelV2" not in apres:
        print("❌ la classe n'est pas au niveau module.")
        return 1

    print(f"  activite_panneau.py {src.count(chr(10))} → {neuf.count(chr(10))} lignes · ast OK")
    if "--apply" not in sys.argv:
        print("  PREVIEW — rien écrit.")
        return 0
    CIBLE.write_text(neuf, encoding="utf-8", newline="")
    print("  ÉCRIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
