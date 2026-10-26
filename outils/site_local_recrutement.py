"""outils/site_local_recrutement.py — le VRAI chemin d'un ticket de recrutement dans le site local (26/10/2026).

Les fonctions de `bot.py` (le panneau touché, « Es-tu sûr ? », la fiche, l'élimination d'office, le ticket, son affiche,
l'équipe qui entre dans le fil sans notification) exécutées sur le faux serveur du site local — les mêmes que le banc
des tests (`tests/banc_ticket_recrutement.espace_du_bot`) : un seul chemin, le vrai. Les adresses de démonstration
(ce script seulement, jamais le bot) :

  GET /tableau/demo/recrutement/ouvrir?membre=<id>[&choix=<n>][&pseudo=<texte>][&panneau=p1]
      le panneau touché, « Oui », la fiche remplie (le choix n° <n> de chaque liste, le texte <pseudo> ailleurs), envoyée
  GET /tableau/demo/recrutement/repondre?ticket=<n>
      le candidat répond à l'étape ouverte (les réponses attendues), page par page, dans les formulaires de Discord
  GET /tableau/demo/discord?mp=<id>
      les messages privés reçus par ce membre (le refus, l'acceptation, la demande approuvée…)
"""
from __future__ import annotations

import json

import discord

import banc_ticket_recrutement as B    # tests/ est sur le chemin du site local
from conftest_discord import Obj, laisser_finir
from faux_serveur import textes as textes_vue


class CheminDuBot:
    """Le chemin du bot sur le faux serveur du site local. `metiers` : le vrai module (branché par le site local)."""

    def __init__(self, *, g, get_db, cfg, db_set, porteur, categorie, metiers, tete, carnet):
        self.g, self.get_db, self.tete, self.carnet = g, get_db, set(tete), carnet
        self.erreurs, self.logs, self.journal = [], [], []
        self.invitations = []
        if not hasattr(g, "owner"):   # `_create_ticket_corps` lit le propriétaire du serveur (discord.Guild.owner)
            g.owner = g.get_member(int(getattr(g, "owner_id", 0) or 0))

        async def autorise(i):
            return i.user.id in self.tete
        self.ns = B.espace_du_bot(g=g, get_db=get_db, cfg=cfg, db_set=db_set, porteur=porteur, categorie=categorie,
                                  journal=self.journal, logs=self.logs, erreurs=self.erreurs, metiers=metiers,
                                  autorise=autorise)

    # ─── La page du candidat (le module de l'équipe « candidature ») : simulée — les chefs reçoivent leur invitation ──
    def page_candidat(self):
        chemin = self

        async def inviter(_g, e):
            chemin.invitations.append({"envoi": int(e["id"]), "membre": int(e["candidat_id"]),
                                       "etape": int(e.get("etape_ouverte") or 0)})
            return True
        return Obj(inviter=inviter, lien_candidat=None)

    def hooks(self) -> dict:
        """Ce que `_activite_boot` donne à `questionnaire.setup` (bot.py), lu dans le même espace."""
        ns = self.ns
        return {"extras": ns["_recrutement_extras"], "liste_noire": ns["_liste_noire_recrutement"],
                "clan": ns["_role_clan_de"], "metiers": ns["_metiers_catalogue"],
                "est_tete": lambda m: getattr(m, "id", 0) in self.tete}

    # ─── Les gestes ───
    async def _dernier_ticket(self, uid: int, pid: str):
        async with self.get_db() as db:
            async with db.execute("SELECT id, channel_id FROM tickets WHERE user_id=? AND panel_id=? AND status='open'"
                                  " ORDER BY id DESC LIMIT 1", (int(uid), pid)) as cur:
                return await cur.fetchone()

    async def ouvrir(self, membre, pid: str = "p1", reponses: dict | None = None) -> tuple:
        """`create_ticket` (la fiche déjà remplie) : le ticket, son affiche, l'équipe qui entre dans le fil."""
        i = B.Inter(self, membre)
        ch, err = await self.ns["create_ticket"](i, pid, reponses or {})
        await laisser_finir()
        if err:
            raise RuntimeError(err)
        r = await self._dernier_ticket(membre.id, pid)
        return int(r[0]), ch

    async def ouvrir_par_le_panneau(self, membre, pid: str = "p1", choix: int = 0, texte: str = "") -> dict:
        """Le panneau touché → « Es-tu sûr ? » → « Oui » → la fiche → envoyée. Rend ce que la personne a lu."""
        avant = await self._dernier_ticket(membre.id, pid)
        i = B.Inter(self, membre)
        await self.ns["_ticket_ouvrir"](i, pid)
        vue = i.messages[0] if i.messages else None
        if vue is None or not hasattr(vue, "walk_children"):
            return {"ok": False, "lu": str(vue or "")}
        boutons = [x for x in vue.walk_children() if isinstance(x, discord.ui.Button)]
        oui = next((b for b in boutons if b.style == discord.ButtonStyle.success), None)
        confirmation = textes_vue(vue)
        if oui is None:   # un refus poli (la liste noire), sans bouton
            return {"ok": False, "lu": confirmation, "confirmation": ""}
        i2 = B.Inter(self, membre)
        await oui.callback(i2)
        if not i2.modals:
            await laisser_finir()
            r = await self._dernier_ticket(membre.id, pid)
            return {"ok": True, "confirmation": confirmation, "ticket": int(r[0]) if r and r != avant else 0, "fiche": []}
        fiche = i2.modals[0]
        champs = []
        for ch, comp in fiche.champs:
            if isinstance(comp, discord.ui.Select):
                comp._values = [str(min(int(choix), len(comp.options) - 1))]
                champs.append({"titre": ch.get("titre"), "choix": comp.options[int(comp._values[0])].label})
            else:
                comp._value = texte or "Kolax_RS"
                champs.append({"titre": ch.get("titre"), "texte": comp._value})
        i3 = B.Inter(self, membre)
        await fiche.on_submit(i3)
        await laisser_finir()
        apres = await self._dernier_ticket(membre.id, pid)
        nouveau = apres is not None and apres != avant
        return {"ok": True, "confirmation": confirmation, "fiche": champs, "titre_fiche": fiche.title,
                "ticket": int(apres[0]) if nouveau else 0, "salon": str(apres[1]) if nouveau else "",
                "elimine": not nouveau, "lu": " ".join(textes_vue(v) for v in i3.vues())}

    async def repondre(self, tid: int, questionnaire) -> dict:
        """Le candidat répond à l'étape ouverte de son questionnaire (les réponses attendues), page par page."""
        s = await questionnaire._suivi(self.g.id, int(tid))
        if s is None or not s["envoi_id"]:
            return {"ok": False, "erreur": "pas de questionnaire pour ce ticket"}
        eid = int(s["envoi_id"])
        e = await questionnaire._envoi(eid)
        cand = self.g.get_member(int(e["candidat_id"]))
        fil = self.g.get_channel_or_thread(int(s["salon_id"])) if s["salon_id"] else None
        attendues = {int(q["rang"]): str(q.get("reponse") or "?") for q in e["questions"]}
        lu = []
        for _ in range(20):
            i = B.Inter(self, cand, fil)
            await questionnaire.BoutonRepondre(eid).callback(i)
            lu += [textes_vue(v) for v in i.vues()]
            if not i.modals:
                break
            modal = i.modals[0]
            for rang, champ in modal.champs:
                champ._value = attendues.get(int(rang), "?")
            fin = B.Inter(self, cand, fil)
            await modal.on_submit(fin)
            lu += [textes_vue(v) for v in fin.vues()]
        await laisser_finir()
        e = await questionnaire._envoi(eid)
        return {"ok": True, "envoi": eid, "statut": e["statut"], "etape_ouverte": e["etape_ouverte"],
                "etape_envoyee": e["etape_envoyee"], "lu": lu[-3:]}

    def messages_prives(self, uid: int) -> list:
        """Les messages privés reçus par ce membre (le carnet du faux serveur : `site_local_port`)."""
        return [{"texte": " ".join(x for x in (str(c or ""), textes_vue(kw["view"]) if kw.get("view") is not None else "")
                                   if x)} for qui, c, kw in self.carnet.get("mp", []) if int(qui) == int(uid)]


def brancher_demo(app, chemin: CheminDuBot, questionnaire, g) -> None:
    """Les adresses de démonstration du recrutement (le site local seulement)."""
    from aiohttp import web

    def repondre(corps, statut=200):
        return web.json_response(corps, status=statut, headers={"Cache-Control": "no-store"},
                                 dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def ouvrir(request):
        brut = request.query.get("membre", "")
        m = g.get_member(int(brut)) if brut.isdigit() else None
        if m is None:
            return repondre({"erreur": "membre inconnu"}, 404)
        choix = request.query.get("choix", "0")
        r = await chemin.ouvrir_par_le_panneau(m, request.query.get("panneau", "p1"),
                                               int(choix) if choix.isdigit() else 0, request.query.get("pseudo", ""))
        return repondre(r)

    async def repondre_etape(request):
        brut = request.query.get("ticket", "")
        if not brut.isdigit():
            return repondre({"erreur": "ticket ?"}, 400)
        return repondre(await chemin.repondre(int(brut), questionnaire))
    app.router.add_get("/tableau/demo/recrutement/ouvrir", ouvrir)
    app.router.add_get("/tableau/demo/recrutement/repondre", repondre_etape)
