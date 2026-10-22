"""Bandeaux animés des menus (GIF) et icônes des boutons (PNG) — identité visuelle du bot.

Rendu hors ligne puis versionné dans `visuels/` ; le bot les sert lui-même (`/v/<nom>`) et
installe les icônes comme émojis d'application.
Usage : python outils/visuels.py [cle …]     (sans argument : tout)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "visuels"
POLICES = Path("C:/Windows/Fonts")
F_TITRE = POLICES / "seguibl.ttf"        # Segoe UI Black
F_SOUS = POLICES / "segoeuisl.ttf"       # Segoe UI Semilight
F_SURTITRE = POLICES / "seguisb.ttf"     # Segoe UI Semibold
F_ICONES = POLICES / "SegoeIcons.ttf"    # Segoe Fluent Icons

L, H = 960, 240
ECH = 2
IMAGES = 24
DUREE = 80

INDIGO, CYAN = (88, 101, 242), (56, 189, 248)
BANDEAUX = {
    #  clé           surtitre         titre                 sous-titre                               glyphe   couleurs
    "configuration": ("CONFIGURATION", "Configuration", "Tout le bot, au même endroit", "\uE713", INDIGO, CYAN),
    "protections": ("SÉCURITÉ", "Protections", "Filtres et boucliers du serveur", "\uEA18", (16, 185, 129), (6, 182, 212)),
    "sanctions": ("MODÉRATION", "Sanctions", "Rôles, salons et barèmes", "\uE730", (239, 68, 68), (249, 115, 22)),
    "immunites": ("MODÉRATION", "Immunités", "Qui n'est jamais sanctionné", "\uE7EF", (245, 158, 11), (250, 204, 21)),
    "antiraid": ("SÉCURITÉ", "Anti-raid", "Les vagues d'arrivées sous contrôle", "\uE7BA", (244, 63, 94), (220, 38, 38)),
    "tickets": ("SUPPORT", "Tickets", "Un fil privé par demande", "\uEA8E", (139, 92, 246), (217, 70, 239)),
    "logs": ("SUIVI", "Logs & audit", "Chaque événement, à sa place", "\uE9D5", (99, 102, 241), (14, 165, 233)),
    "actualites": ("ROBLOX", "Actualités", "DevForum, notes de version, presse", "\uE789", (37, 99, 235), (16, 185, 129)),
    "sondages": ("COMMUNAUTÉ", "Sondages", "La communauté décide", "\uEB05", INDIGO, (235, 69, 158)),
    "suggestions": ("COMMUNAUTÉ", "Suggestions", "Vos idées pour le serveur", "\uE82F", (251, 191, 36), (249, 115, 22)),
    "social": ("RÉSEAUX", "Réseaux sociaux", "YouTube, Twitch, TikTok, X", "\uE774", (14, 165, 233), (99, 102, 241)),
    "rellseas": ("RELL SEAS", "Rell Seas", "Le clan et son activité", "\uEB48", (6, 182, 212), (37, 99, 235)),
    "rgpd": ("DONNÉES", "Données & RGPD", "Le droit à l'effacement", "\uE72E", (100, 116, 139), (71, 85, 105)),
    "casier": ("MODÉRATION", "Casier", "L'historique d'un membre", "\uE9F9", (220, 38, 38), (244, 63, 94)),
    "aide": ("AIDE", "Aide", "Les commandes du bot", "\uE9CE", (34, 211, 238), (59, 130, 246)),
    "moderation": ("MODÉRATION", "Tableau de bord", "La modération d'un coup d'œil", "\uEAFC", (124, 58, 237), (79, 70, 229)),
    "rapport": ("SUIVI", "Rapport", "Le serveur en chiffres", "\uE9D2", (20, 184, 166), (34, 197, 94)),
    "erreurs": ("TECHNIQUE", "Erreurs", "Ce qui a coincé", "\uE783", (249, 115, 22), (239, 68, 68)),
    "webhooks": ("SÉCURITÉ", "Webhooks", "Qui publie au nom du serveur", "\uE71B", (99, 102, 241), (139, 92, 246)),
    "risques": ("SÉCURITÉ", "Arrivées à risque", "Les comptes à surveiller", "\uE928", (244, 63, 94), (139, 92, 246)),
    "raid": ("ALERTE", "Raid détecté", "Riposte en cours", "\uE7BA", (239, 68, 68), (127, 29, 29)),
    "signalement": ("MODÉRATION", "Signalement", "Une décision du staff est attendue", "\uE730", (239, 68, 68), (249, 115, 22)),
    "entraide": ("COMMUNAUTÉ", "Entraide", "Trouver de l'aide pour jouer", "\uE8F2", (16, 185, 129), (132, 204, 22)),
    "bienvenue": ("ACCUEIL", "Bienvenue", "Choisis ta langue", "\uE775", (14, 165, 233), (16, 185, 129)),
    "boost": ("SOUTIEN", "Boosts", "Merci de soutenir le serveur", "\uE735", (244, 114, 182), (168, 85, 247)),
    "zones": ("COMMUNAUTÉ", "Groupes & échanges", "Des espaces privés à plusieurs", "\uE716", (6, 182, 212), (139, 92, 246)),
    "radiation": ("MODÉRATION", "Radiation", "Retirer un membre de tout", "\uE733", (153, 27, 27), (71, 85, 105)),
    "bouclier": ("SÉCURITÉ", "Bouclier", "Verrouiller le serveur", "\uEA18", (239, 68, 68), (245, 158, 11)),
    "transcripts": ("SUPPORT", "Transcripts", "L'archive des tickets", "\uE8A5", (139, 92, 246), (79, 70, 229)),
    "salons": ("CONFIGURATION", "Salons", "Qui voit quoi, qui parle où", "\uE8BD", INDIGO, (16, 185, 129)),
    "ticket_creation": ("SUPPORT", "Ouvrir un ticket", "Choisis le type de ta demande", "\uEA8E", (139, 92, 246), (217, 70, 239)),
    "ticket_gestion": ("SUPPORT", "Gestion du ticket", "Priorité, étiquettes, suivi", "\uE713", (139, 92, 246), (99, 102, 241)),
    "tickets_modifier": ("SUPPORT", "Modifier un panneau", "Choisis le panneau à régler", "\uE70F", (139, 92, 246), (217, 70, 239)),
    "tickets_envoyer": ("SUPPORT", "Envoyer le panneau", "Choisis son salon", "\uE724", (139, 92, 246), (217, 70, 239)),
    "tickets_panneau": ("SUPPORT", "Panneau de tickets", "Questions, apparence, accueil", "\uEA8E", (139, 92, 246), (217, 70, 239)),
    "modeles": ("SUPPORT", "Modèles de réponse", "Des réponses prêtes à l'emploi", "\uE8BD", (139, 92, 246), (99, 102, 241)),
    "tickets_stats": ("SUPPORT", "Statistiques", "Les tickets en chiffres", "\uEAFC", (139, 92, 246), (99, 102, 241)),
    "antiraid_action": ("SÉCURITÉ", "Riposte au raid", "Ce que fait le bot pendant un raid", "\uE7BA", (244, 63, 94), (220, 38, 38)),
    "salons_securite": ("SÉCURITÉ", "Salons de sécurité", "Salon piège et alertes du staff", "\uEA18", (16, 185, 129), (6, 182, 212)),
    "logs_routage": ("SUIVI", "Salon par catégorie", "Un salon par type de log", "\uE9D5", (99, 102, 241), (14, 165, 233)),
    "logs_evenement": ("SUIVI", "Salon par évènement", "Un salon pour un évènement précis", "\uE9D5", (99, 102, 241), (14, 165, 233)),
    "logs_categories": ("SUIVI", "Catégories de logs", "Ce qui est journalisé", "\uE71D", (99, 102, 241), (14, 165, 233)),
    "logs_details": ("SUIVI", "Détail par évènement", "Un interrupteur par évènement", "\uE9E9", (99, 102, 241), (14, 165, 233)),
    "logs_exclusions": ("SUIVI", "Rôles épargnés", "Ces rôles ne sont pas journalisés", "\uE7EF", (99, 102, 241), (14, 165, 233)),
    "images": ("SÉCURITÉ", "Formats d'image", "Ce qui peut être envoyé", "\uE91B", (16, 185, 129), (6, 182, 212)),
    "mots_interdits": ("SÉCURITÉ", "Mots interdits", "La liste du serveur", "\uE8C9", (16, 185, 129), (6, 182, 212)),
    "mots_sanction": ("SÉCURITÉ", "Sanction des mots interdits", "Au seuil d'avertissements", "\uE730", (239, 68, 68), (249, 115, 22)),
    "liens": ("SÉCURITÉ", "Liens", "Domaines et salons autorisés", "\uE71B", (16, 185, 129), (6, 182, 212)),
    "multicomptes": ("SÉCURITÉ", "Multi-comptes", "Repérer les comptes secondaires", "\uE716", (244, 63, 94), (139, 92, 246)),
    "multicomptes_detections": ("SÉCURITÉ", "Détections", "Les comptes secondaires repérés", "\uE716", (244, 63, 94), (139, 92, 246)),
    "scan_resultats": ("SÉCURITÉ", "Résultats du scan", "Les comptes repérés", "\uE721", (244, 63, 94), (139, 92, 246)),
    "scan_suspects": ("SÉCURITÉ", "Comptes suspects", "Le scan du serveur", "\uE721", (244, 63, 94), (139, 92, 246)),
    "immunites_retrait": ("MODÉRATION", "Retirer une immunité", "Rôle, membre ou salon", "\uE74D", (245, 158, 11), (250, 204, 21)),
    "au_revoir": ("COMMUNAUTÉ", "Au revoir", "Un membre nous a quittés", "\uE72B", (100, 116, 139), (99, 102, 241)),
    "recap": ("POUR TOI", "Ton récap du jour", "Ce qui s'est passé pendant ton absence", "\uE787", (14, 165, 233), (139, 92, 246)),
    "mes_mp": ("POUR TOI", "Mes messages privés", "Ce que le bot peut t'envoyer", "\uE715", (14, 165, 233), (139, 92, 246)),
    "historique": ("SUIVI", "Historique", "Le serveur sur la durée", "\uE81C", (20, 184, 166), (34, 197, 94)),
    "retention": ("SUIVI", "Rétention", "Qui reste, qui part", "\uE716", (20, 184, 166), (34, 197, 94)),
    "anomalies": ("SUIVI", "Anomalies", "Ce qui sort de l'ordinaire", "\uE7BA", (249, 115, 22), (239, 68, 68)),
    "rellseas_gestion": ("RELL SEAS", "Gestion du rôle", "Donner ou retirer à plusieurs", "\uE716", (6, 182, 212), (37, 99, 235)),
    "clan": ("RELL SEAS", "Liste du clan", "Qui est dedans, qui est actif", "\uE8FD", (6, 182, 212), (37, 99, 235)),
    "recrutement": ("RELL SEAS", "Recrutement", "Le dossier complet du candidat", "\uE77B", (6, 182, 212), (79, 70, 229)),
    "tableau": ("STAFF", "Tableau de bord", "Candidatures · tickets · sanctions · clan", "\uE9D2", (14, 165, 233), (99, 102, 241)),
    #  Entraide Rell Seas (22/10/2026) : l'orientation et une zone par besoin.
    "rs_port": ("RELL SEAS", "Entraide", "Aide · Trade · Boss · Farm · Chill", "\uEB48", (6, 182, 212), (37, 99, 235)),
    "rs_entraide": ("RELL SEAS", "Entraide · Help", "Aide · Boss · Farm · Chill", "\uEB48", (34, 197, 94), (16, 185, 129)),
    "rs_crews": ("RELL SEAS", "Équipages · Crews", "Pirates · Marine", "\uE7C1", (30, 41, 59), (37, 99, 235)),
    "orientation": ("AIDE · HELP", "Bienvenue · Welcome", "Français · English — trouve ta place · find your way", "\uE909", (14, 165, 233), (99, 102, 241)),
    "rs_trade": ("RELL SEAS", "Trade", "Fruits et objets · Fruits & items", "\uE8AB", (245, 158, 11), (234, 88, 12)),
}

#  Icônes des boutons : (glyphe, famille de couleur)
VERT, ROUGE, BLEU, AMBRE, GRIS = ((34, 197, 94), (16, 185, 129)), ((239, 68, 68), (244, 63, 94)), \
    (INDIGO, (99, 102, 241)), ((245, 158, 11), (249, 115, 22)), ((100, 116, 139), (71, 85, 105))
ICONES = {
    "retour": ("\uE72B", GRIS), "fermer": ("\uE711", GRIS), "actualiser": ("\uE72C", BLEU),
    "ajouter": ("\uE710", VERT), "supprimer": ("\uE74D", ROUGE), "modifier": ("\uE70F", BLEU),
    "valider": ("\uE8FB", VERT), "annuler": ("\uE7A7", GRIS), "reglages": ("\uE713", BLEU),
    "cloche": ("\uEA8F", AMBRE), "cloche_off": ("\uE7ED", GRIS), "idee": ("\uE82F", AMBRE),
    "pour": ("\uE8E1", VERT), "contre": ("\uE8E0", ROUGE), "terminer": ("\uE71A", ROUGE),
    "pause": ("\uE769", GRIS), "activer": ("\uE768", VERT), "salon": ("\uE8BD", BLEU),
    "membre": ("\uE77B", BLEU), "membres": ("\uE716", BLEU), "recherche": ("\uE721", BLEU),
    "bouclier": ("\uEA18", VERT), "ticket": ("\uEA8E", BLEU), "journal": ("\uE9D5", BLEU),
    "stats": ("\uEAFC", BLEU), "exporter": ("\uE72D", BLEU), "lien": ("\uE71B", BLEU),
    "verrou": ("\uE72E", ROUGE), "deverrou": ("\uE785", VERT), "avertir": ("\uE7BA", AMBRE),
    "info": ("\uE946", BLEU), "aide": ("\uE9CE", BLEU), "horloge": ("\uE823", BLEU),
    "calendrier": ("\uE787", BLEU), "balai": ("\uEA99", GRIS), "epingle": ("\uE718", BLEU),
    "envoyer": ("\uE724", BLEU), "sondage": ("\uEB05", BLEU), "actu": ("\uE789", BLEU),
    "navire": ("\uEB48", BLEU), "globe": ("\uE774", BLEU), "cle": ("\uE8D7", AMBRE),
    "sanction": ("\uE730", ROUGE), "muet": ("\uE74F", ROUGE), "etoile": ("\uE735", AMBRE),
    "expulser": ("\uF3B1", ROUGE), "interdit": ("\uE733", ROUGE), "son": ("\uE767", BLEU),
    "musique": ("\uE8D6", BLEU), "alerte": ("\uE814", ROUGE), "dossier": ("\uE8B7", BLEU),
    "clavier": ("\uE765", GRIS), "heriter": ("\uE7A6", GRIS), "video": ("\uE714", BLEU),
    "diagnostic": ("\uE9D9", VERT), "cible": ("\uEB44", BLEU), "sommeil": ("\uE708", GRIS),
    "suivant": ("\uE893", GRIS), "palette": ("\uE790", BLEU), "accueil": ("\uE76E", AMBRE),
    "numero": ("\uE8EF", GRIS), "role": ("\uE8D4", BLEU), "staff": ("\uECA7", BLEU),
    "robot": ("\uE99A", GRIS), "image": ("\uE8B9", BLEU), "position": ("\uE707", BLEU),
    "detail": ("\uE8A3", BLEU), "curseurs": ("\uE9E9", BLEU),
    "drapeau": ("\uE7C1", AMBRE), "etiquette": ("\uE8EC", BLEU), "retirer": ("\uE738", ROUGE),
}


def _police(chemin, taille):
    return ImageFont.truetype(str(chemin), taille)


def _degrade(taille, c1, c2, melange=0.35):
    w, h = taille
    x = Image.linear_gradient("L").rotate(-90).resize((w, h))
    y = Image.linear_gradient("L").resize((w, h))
    m = Image.blend(x, y, melange)
    return Image.composite(Image.new("RGB", taille, c2), Image.new("RGB", taille, c1), m)


def _halo(taille, centre, rayon, couleur, force):
    calque = Image.new("RGBA", taille, (0, 0, 0, 0))
    cx, cy = centre
    ImageDraw.Draw(calque).ellipse((cx - rayon, cy - rayon, cx + rayon, cy + rayon),
                                   fill=couleur + (int(255 * force),))
    return calque.filter(ImageFilter.GaussianBlur(rayon * 0.55))


def _texte_espace(d, xy, texte, police, couleur, espace):
    x, y = xy
    for c in texte:
        d.text((x, y), c, font=police, fill=couleur)
        x += d.textlength(c, font=police) + espace
    return x


def fond(c1, c2):
    """Nuit profonde, deux halos de la couleur du menu, trame fine, rayons obliques, filet."""
    w, h = L * ECH, H * ECH
    base = _degrade((w, h), (8, 11, 20), (15, 19, 34)).convert("RGBA")
    base.alpha_composite(_halo((w, h), (int(w * 0.16), int(h * 0.1)), int(h * 0.95), c1, 0.55))
    base.alpha_composite(_halo((w, h), (int(w * 0.98), int(h * 1.05)), int(h * 1.15), c2, 0.5))
    rayons = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(rayons)
    for k, x in enumerate((0.42, 0.55, 0.63, 0.78)):
        x0 = int(w * x)
        d.polygon([(x0, 0), (x0 + 40 * ECH, 0), (x0 - 120 * ECH, h), (x0 - 160 * ECH, h)],
                  fill=(255, 255, 255, 7 + 3 * (k % 2)))
    base.alpha_composite(rayons.filter(ImageFilter.GaussianBlur(10 * ECH)))
    trame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(trame)
    pas = 22 * ECH
    for y in range(pas // 2, h, pas):
        for x in range(pas // 2, w, pas):
            d.ellipse((x - 1.1 * ECH, y - 1.1 * ECH, x + 1.1 * ECH, y + 1.1 * ECH), fill=(255, 255, 255, 12))
    base.alpha_composite(trame)
    filet = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(filet).rounded_rectangle((ECH, ECH, w - ECH, h - ECH), radius=28 * ECH,
                                             outline=(255, 255, 255, 30), width=2 * ECH)
    base.alpha_composite(filet)
    return base


def tuile(c1, c2, glyphe, t, rayon=0.28, part=0.5, reflet=True):
    masque = Image.new("L", (t, t), 0)
    ImageDraw.Draw(masque).rounded_rectangle((0, 0, t - 1, t - 1), radius=int(t * rayon), fill=255)
    couleur = _degrade((t, t), c1, c2, 0.5).convert("RGBA")
    if reflet:
        r = Image.new("RGBA", (t, t), (0, 0, 0, 0))
        ImageDraw.Draw(r).ellipse((-t * 0.4, -t * 0.9, t * 1.2, t * 0.55), fill=(255, 255, 255, 46))
        couleur.alpha_composite(r)
    couleur.putalpha(masque)
    p = _police(F_ICONES, int(t * part))
    d = ImageDraw.Draw(couleur)
    bb = d.textbbox((0, 0), glyphe, font=p)
    pos = ((t - (bb[2] - bb[0])) / 2 - bb[0], (t - (bb[3] - bb[1])) / 2 - bb[1])
    ombre = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    ImageDraw.Draw(ombre).text((pos[0], pos[1] + t * 0.02), glyphe, font=p, fill=(0, 0, 0, 90))
    couleur.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(max(1, t * 0.02))))
    d.text(pos, glyphe, font=p, fill=(255, 255, 255, 255))
    return couleur, masque


def textes(base, surtitre, titre, sous_titre, x, c1):
    d = ImageDraw.Draw(base)
    pe = _police(F_SURTITRE, 17 * ECH)
    pt = _police(F_TITRE, 58 * ECH)
    ps = _police(F_SOUS, 25 * ECH)
    h = H * ECH
    be, bt, bs = d.textbbox((0, 0), "A", font=pe), d.textbbox((0, 0), titre, font=pt), \
        d.textbbox((0, 0), sous_titre, font=ps)
    he, ht, hs = be[3] - be[1], bt[3] - bt[1], bs[3] - bs[1]
    total = he + 14 * ECH + ht + 16 * ECH + hs
    y0 = (h - total) / 2
    clair = tuple(min(255, int(v * 0.55 + 255 * 0.45)) for v in c1)
    _texte_espace(d, (x + 2 * ECH, y0 - be[1]), surtitre, pe, clair + (255,), 3 * ECH)
    yt = y0 + he + 14 * ECH
    ombre = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(ombre).text((x, yt - bt[1] + 3 * ECH), titre, font=pt, fill=(0, 0, 0, 130))
    base.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(7 * ECH)))
    d.text((x, yt - bt[1]), titre, font=pt, fill=(255, 255, 255, 255))
    ys = yt + ht + 16 * ECH
    d.text((x + 2 * ECH, ys - bs[1]), sous_titre, font=ps, fill=(190, 198, 222, 255))
    return x, x + max(bt[2] - bt[0], bs[2] - bs[0])


def bandeau(cle):
    surtitre, titre, sous_titre, glyphe, c1, c2 = BANDEAUX[cle]
    w, h = L * ECH, H * ECH
    t = 128 * ECH
    tx, ty = 52 * ECH, (h - t) // 2
    base = fond(c1, c2)
    base.alpha_composite(_halo((w, h), (tx + t // 2, ty + t // 2), int(t * 0.6), c1, 0.75))
    tu, masque = tuile(c1, c2, glyphe, t)
    textes(base, surtitre, titre, sous_titre, tx + t + 44 * ECH, c1)
    statique = base.copy()
    statique.alpha_composite(tu, (tx, ty))
    petit = statique.resize((L, H), Image.LANCZOS).convert("RGB")
    palette = petit.quantize(colors=200, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    fixe = petit.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
    # seule la tuile s'anime : un reflet la traverse, puis repos
    zone = (tx // ECH - 2, ty // ECH - 2, (tx + t) // ECH + 2, (ty + t) // ECH + 2)
    images = []
    for k in range(IMAGES):
        cadre = base.copy()
        tk = tu.copy()
        avance = k / (IMAGES * 0.55)
        if avance <= 1:
            bande = Image.new("RGBA", (t, t), (0, 0, 0, 0))
            p = -t * 0.6 + 2.2 * t * avance
            ImageDraw.Draw(bande).polygon([(p, 0), (p + t * 0.26, 0), (p - t * 0.18, t), (p - t * 0.44, t)],
                                          fill=(255, 255, 255, 95))
            bande = bande.filter(ImageFilter.GaussianBlur(t * 0.035))
            bande.putalpha(ImageChops.multiply(bande.getchannel("A"), masque))
            tk.alpha_composite(bande)
        cadre.alpha_composite(tk, (tx, ty))
        complet = cadre.resize((L, H), Image.LANCZOS).convert("RGB").quantize(
            palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        img = fixe.copy()
        img.paste(complet.crop(zone), zone[:2])
        images.append(img)
    SORTIE.mkdir(exist_ok=True)
    chemin = SORTIE / f"{cle}.gif"
    images[0].save(chemin, save_all=True, append_images=images[1:], duration=[DUREE] * IMAGES,
                   loop=0, optimize=False, disposal=1)
    return chemin


def icone(nom):
    glyphe, (c1, c2) = ICONES[nom]
    t = 128
    img, _ = tuile(c1, c2, glyphe, t, rayon=0.3, part=0.56, reflet=False)
    (SORTIE / "icones").mkdir(parents=True, exist_ok=True)
    chemin = SORTIE / "icones" / f"{nom}.png"
    img.save(chemin)
    return chemin


if __name__ == "__main__":
    demandes = sys.argv[1:] or list(BANDEAUX) + ["icones"]
    for cle in demandes:
        if cle == "icones":
            for nom in ICONES:
                icone(nom)
            print(len(ICONES), "icônes")
            continue
        c = bandeau(cle)
        print(c.name, f"{c.stat().st_size // 1024} Ko")
