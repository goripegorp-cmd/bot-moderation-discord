"""textes.py — les textes du bot et les noms du site, réécrits par la direction (26/10/2026).

Le fondateur, mot pour mot : « laisses la possibilité au directeur de nommer tout ce qu'il souhaite. Genre, par exemple,
s'il y a un rôle qui lui plaît pas, s'il y a un texte qui lui plaît pas, qu'il puisse modifier à sa sauce et que ça
s'enregistre en fonction de ce qu'il fait… même pour le clan… le système de recrutement et tout, les questions… Avec de
vrais boutons de modification et d'enregistrement, et ça prend bien en compte. »

LE REGISTRE
  · Chaque module DÉCLARE ses textes au chargement : `declarer(cle, defaut, groupe=, titre=, aide=, max_=, lignes=,
    variables=, ordre=)`. Le texte d'origine reste dans le code ; la base ne garde que ce que la direction a changé.
  · `await texte(guild_id, cle, **valeurs)` : le texte enregistré pour ce serveur, sinon celui d'origine. Seules les
    variables DÉCLARÉES (`{nombre}`) sont remplacées — jamais `str.format` : une accolade écrite sur le site reste telle
    quelle et rien ne casse. `texte_cache(...)` : la même chose, synchrone (les cartes construites sans attendre).
  · La table `site_textes` ; un cache mémoire chargé au démarrage et relu à chaque écriture : le bot emploie le nouveau
    texte dès l'enregistrement — le prochain message le porte.
  · Jamais d'échec vers le bot : une base qui ne répond pas donne le texte d'origine (et le journal le dit).
  · `quand_change(prefixe, fn)` : un module est prévenu quand un de ses textes change (le guide du clan se réécrit).
  · Un module qui déclare sa propre famille de textes la nomme dans l'onglet : `nommer_groupe(cle, nom, ordre)`.
  · 26/10, le fondateur : « modifier même ce qui existe déjà… tout le site ». Déclarés : le recrutement (le candidat,
    la carte de l'équipe, ses boutons, le formulaire du refus), les métiers (le choix, les réponses, l'acceptation), le
    guide du clan (`zones.py`), les annonces & événements (boutons, cartes, rappels, listing), et le site (les trois
    parties, chaque rubrique et sa phrase, les sous-onglets, les onglets de la fiche, les statuts d'affiche). Restent
    fixes, exprès : les messages techniques d'échec (« Discord ne répond pas »…) — ils doivent dire la vérité.

LE SITE (La Capitainerie → Textes & noms)
  · GET textes · POST texte {cle, valeur, version} (rejoué hors ligne, conflit 409 par version) · POST texte/defaut
    {cle, version?} (le texte d'origine) · GET textes/site (les noms du site changés, lus au démarrage de la page).
  · POST rell/role/renommer {role_id, nom} : un rôle lié (métiers, autres types du catalogue) ou rattaché au clan,
    renommé sur Discord ; pour un métier, ce nom sert aussi s'il faut recréer son rôle (`metiers.nom_du_role`).
"""
from __future__ import annotations

import asyncio
import inspect
import re
import time

import discord

import diag

#  Les familles de textes de l'onglet, dans cet ordre (un groupe inconnu passe après, sous son nom ; un module qui
#  déclare sa propre famille la nomme avec `nommer_groupe`).
GROUPES = {"recrutement": ("Recrutement", 10), "metiers": ("Métiers", 20), "guide": ("Le guide du clan", 25),
           "evenements": ("Annonces & événements", 30), "site": ("Le site", 40)}
FORMAT_CLE = re.compile(r"[a-z][a-z0-9_]{0,30}(?:\.[a-z0-9_]{1,30}){1,5}")
FORMAT_VARIABLE = re.compile(r"[a-z][a-z0-9_]{0,30}")
VARIABLE = re.compile(r"\{([a-z][a-z0-9_]{0,30})\}")
#  Ce qu'un texte enregistré ne garde jamais : les caractères de contrôle et les marques invisibles (sens d'écriture,
#  largeur nulle) — ils fausseraient la longueur et l'affichage sur Discord.
_INVISIBLES = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠-⁤⁦-⁩﻿]")
MAX_ABSOLU = 4000                # Discord : 4 000 caractères de texte par message Components V2
NOM_ROLE_MAX = 100               # Discord : le nom d'un rôle
REESSAI_LECTURE_S = 60.0         # une base illisible n'est pas relue à chaque texte demandé

_DECLARES: dict = {}             # clé → la déclaration (texte d'origine, groupe, titre, aide, bornes, variables)
_cache: dict = {}                # serveur → {clé: (valeur | None, version, maj_le, maj_par)}
_etat = {"charge": False, "echec": 0.0}
_ecouteurs: list = []            # (préfixe, fonction(g, clé)) : prévenus après une écriture
_verrous: dict = {}              # boucle → verrou des écritures (un verrou né dans une autre boucle y lèverait)
_get_db = None
_log = print


class _Invalide(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message, self.status = message, status


def setup(*, get_db, log=None) -> None:
    """`get_db()` : la base du bot (aiosqlite). Rebrancher vide le cache : `init_db` (ou le premier texte demandé) le
    recharge."""
    global _get_db, _log
    _get_db, _log = get_db, log or print
    _cache.clear()
    _etat.update(charge=False, echec=0.0)
    _verrous.clear()


def pret() -> bool:
    return _get_db is not None


def _signaler(code: str, message: str, detail: str = "", ex=None) -> None:
    """Un message STABLE (le tableau des erreurs ne sature pas), le détail sur une ligne à part."""
    _log(f"[TEXTES][{code}] {message}")
    _log(f"[TEXTES][{code}:DETAIL] {detail} {type(ex).__name__ + ' ' + str(ex) if ex is not None else ''}".rstrip())
    if ex is not None:
        diag.compter("textes", code, ex)


# ═══════════════════════════════════════════════════════════════════════════════
#  Déclarer un texte (au chargement de chaque module)
# ═══════════════════════════════════════════════════════════════════════════════

def _variables(variables) -> tuple:
    """((nom, ce qu'elle montre), …) : `"nombre"` ou `("nombre", "le nombre de questions")`."""
    out = []
    for v in variables or ():
        nom, description = (v, "") if isinstance(v, str) else (tuple(v) + ("",))[:2]
        if not isinstance(nom, str) or not FORMAT_VARIABLE.fullmatch(nom):
            raise ValueError(f"textes : variable invalide {nom!r}")
        if any(nom == x[0] for x in out):
            raise ValueError(f"textes : variable en double {nom!r}")
        out.append((nom, str(description or f"« {nom} »")))
    return tuple(out)


def declarer(cle: str, defaut: str, *, groupe: str, titre: str, aide: str = "", max_: int = 2000, lignes: bool = True,
             variables=(), ordre: int = 0, requis: bool = True, partie: str = "") -> str:
    """Un texte que la direction peut réécrire sur le site. Rend le texte d'origine (le module le garde en constante).
    Une erreur ici est une erreur de câblage : elle se voit au démarrage, jamais devant un membre."""
    if not isinstance(cle, str) or not FORMAT_CLE.fullmatch(cle):
        raise ValueError(f"textes : clé invalide {cle!r}")
    if not isinstance(defaut, str) or not isinstance(titre, str) or not titre.strip() or not isinstance(groupe, str) \
            or not groupe:
        raise ValueError(f"textes : déclaration incomplète ({cle})")
    if isinstance(max_, bool) or not isinstance(max_, int) or not 1 <= max_ <= MAX_ABSOLU or len(defaut) > max_:
        raise ValueError(f"textes : longueur hors bornes ({cle})")
    if not lignes and "\n" in defaut:
        raise ValueError(f"textes : un texte d'une ligne n'a pas de retour à la ligne ({cle})")
    if requis and not defaut.strip():
        raise ValueError(f"textes : un texte requis n'est pas vide ({cle})")
    vs = _variables(variables)
    inconnues = sorted({m.group(1) for m in VARIABLE.finditer(defaut)} - {n for n, _d in vs})
    if inconnues:
        raise ValueError(f"textes : variable non déclarée {inconnues} ({cle})")
    _DECLARES[cle] = {"cle": cle, "defaut": defaut, "groupe": groupe, "titre": titre.strip()[:80],
                      "aide": str(aide or "").strip()[:300], "max": max_, "lignes": bool(lignes), "variables": vs,
                      "noms": frozenset(n for n, _d in vs), "ordre": int(ordre), "requis": bool(requis),
                      "partie": str(partie or "").strip()[:60]}
    return defaut


def nommer_groupe(cle: str, nom: str, ordre: int = 90) -> None:
    """Le nom (et la place) d'une famille de textes dans l'onglet « Textes & noms » — pour un module qui déclare ses
    propres textes sous un groupe à lui (`declarer(…, groupe=cle)`)."""
    if not isinstance(cle, str) or not FORMAT_VARIABLE.fullmatch(cle) or not isinstance(nom, str) or not nom.strip():
        raise ValueError(f"textes : groupe invalide {cle!r}")
    GROUPES[cle] = (nom.strip()[:60], int(ordre))


def declare(cle: str) -> bool:
    return cle in _DECLARES


def defaut(cle: str) -> str:
    return _DECLARES[cle]["defaut"]


def quand_change(prefixe: str, fn) -> None:
    """`fn(g, cle)` (synchrone ou non) après l'écriture réussie d'un texte dont la clé commence par `prefixe`."""
    if not any(p == prefixe and f is fn for p, f in _ecouteurs):
        _ecouteurs.append((prefixe, fn))


# ═══════════════════════════════════════════════════════════════════════════════
#  Lire un texte (le bot)
# ═══════════════════════════════════════════════════════════════════════════════

def remplir(modele: str, noms, valeurs: dict) -> str:
    """Les variables DÉCLARÉES et fournies remplacées, d'un seul passage (une valeur qui contient « {x} » n'est jamais
    relue) ; tout le reste — accolades, variables inconnues — reste tel quel."""
    def remplacer(m):
        nom = m.group(1)
        return str(valeurs[nom]) if nom in noms and nom in valeurs else m.group(0)
    return VARIABLE.sub(remplacer, str(modele))


def _brut(guild_id, cle: str):
    """(le modèle à employer, la déclaration) — None si la clé n'est pas déclarée (une faute de câblage)."""
    d = _DECLARES.get(cle)
    if d is None:
        _signaler("E1", "texte non déclaré demandé", cle)
        return None, None
    try:
        gid = int(getattr(guild_id, "id", guild_id) or 0)
    except (TypeError, ValueError):
        gid = 0
    ligne = _cache.get(gid, {}).get(cle)
    return (ligne[0] if ligne is not None and ligne[0] is not None else d["defaut"]), d


def texte_cache(guild_id, cle: str, **valeurs) -> str:
    """Le texte de ce serveur (le cache mémoire), sinon celui d'origine — synchrone, pour les cartes construites sans
    attendre. Une clé jamais déclarée : la clé elle-même (visible, jamais un message vide refusé par Discord)."""
    modele, d = _brut(guild_id, cle)
    if d is None:
        return cle
    return remplir(modele, d["noms"], valeurs)


async def texte(guild_id, cle: str, **valeurs) -> str:
    """Le texte de ce serveur, sinon celui d'origine. Le cache est chargé au démarrage ; s'il ne l'est pas encore, il
    l'est ici (une base illisible : le texte d'origine, et pas de nouvel essai avant une minute)."""
    if not _etat["charge"] and _get_db is not None and time.monotonic() - _etat["echec"] > REESSAI_LECTURE_S:
        await charger()
    return texte_cache(guild_id, cle, **valeurs)


async def charger() -> bool:
    """Tout le cache relu depuis la base (quelques centaines de lignes au plus)."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            async with db.execute("SELECT guild_id, cle, valeur, version, maj_le, maj_par FROM site_textes") as cur:
                lignes = await cur.fetchall()
    except Exception as ex:  # la base ne répond pas : les textes d'origine, dits au journal
        _etat["echec"] = time.monotonic()
        _signaler("E2", "textes du site illisibles : textes d'origine employés", "", ex)
        return False
    nouveau: dict = {}
    for gid, cle, valeur, version, maj_le, maj_par in lignes:
        nouveau.setdefault(int(gid), {})[str(cle)] = (valeur, int(version or 0), int(maj_le or 0), int(maj_par or 0))
    _cache.clear()
    _cache.update(nouveau)
    _etat.update(charge=True, echec=0.0)
    return True


async def init_db() -> None:
    async with _get_db() as db:
        await db.execute("CREATE TABLE IF NOT EXISTS site_textes (guild_id INTEGER NOT NULL, cle TEXT NOT NULL,"
                         " valeur TEXT, version INTEGER NOT NULL DEFAULT 0, maj_le INTEGER NOT NULL DEFAULT 0,"
                         " maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, cle))")
        await db.commit()
    await charger()


def _verrou() -> asyncio.Lock:
    boucle = asyncio.get_running_loop()
    v = _verrous.get(id(boucle))
    if v is None or v[0] is not boucle:
        v = _verrous[id(boucle)] = (boucle, asyncio.Lock())
    return v[1]


# ═══════════════════════════════════════════════════════════════════════════════
#  Écrire un texte (le site)
# ═══════════════════════════════════════════════════════════════════════════════

def _qui(g, uid) -> dict | None:
    if not uid:
        return None
    m = g.get_member(int(uid)) if g is not None else None
    return {"id": str(uid), "nom": getattr(m, "display_name", "") or "Membre parti"}


def propre(valeur, d: dict) -> str:
    """Le texte reçu, nettoyé et vérifié : fins de ligne, caractères invisibles, une ligne pour un texte d'une ligne,
    la longueur, vide refusé si le texte est requis."""
    if not isinstance(valeur, str):
        raise _Invalide("« valeur » : un texte est attendu.")
    v = _INVISIBLES.sub("", valeur.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " "))
    v = " ".join(v.split()) if not d["lignes"] else "\n".join(x.rstrip() for x in v.split("\n")).strip()
    if not v and d["requis"]:
        raise _Invalide("Ce texte ne peut pas être vide : écris-en un, ou reviens au texte d'origine.")
    if len(v) > d["max"]:
        raise _Invalide(f"{d['max']} caractères au plus ({len(v)} écrits).")
    return v


def avertissements(valeur: str, d: dict) -> list:
    """Ce que la page doit dire avant tout : une variable du texte d'origine qui n'apparaît plus, une variable inconnue
    (elle s'affichera telle quelle)."""
    presentes = {m.group(1) for m in VARIABLE.finditer(valeur)}
    dans_origine = {m.group(1) for m in VARIABLE.finditer(d["defaut"])}
    out = [f"{{{nom}}} n'apparaît plus : {description} ne s'affichera pas."
           for nom, description in d["variables"] if nom in dans_origine and nom not in presentes]
    out += [f"{{{nom}}} n'est pas une variable de ce texte : il s'affichera tel quel."
            for nom in sorted(presentes - d["noms"])]
    return out


def item(g, cle: str) -> dict:
    """Un texte tel que le site le lit."""
    d = _DECLARES[cle]
    ligne = _cache.get(int(getattr(g, "id", 0) or 0), {}).get(cle)
    modifie = ligne is not None and ligne[0] is not None
    return {"cle": cle, "titre": d["titre"], "aide": d["aide"], "partie": d["partie"], "groupe": d["groupe"],
            "defaut": d["defaut"], "valeur": ligne[0] if modifie else d["defaut"], "modifie": modifie,
            "version": ligne[1] if ligne is not None else 0, "max": d["max"], "lignes": d["lignes"],
            "requis": d["requis"], "ordre": d["ordre"],
            "variables": [{"nom": n, "description": desc} for n, desc in d["variables"]],
            "maj_le": ligne[2] if ligne is not None else 0,
            "maj_par": _qui(g, ligne[3]) if ligne is not None and ligne[3] else None}


def groupes(g) -> list:
    """Les textes déclarés, par groupe (dans l'ordre de `GROUPES`), chacun dans son ordre."""
    par_groupe: dict = {}
    for cle, d in _DECLARES.items():
        par_groupe.setdefault(d["groupe"], []).append(cle)
    out = []
    for gcle, cles in par_groupe.items():
        nom, ordre = GROUPES.get(gcle, (gcle.capitalize(), 99))
        textes_ = sorted((item(g, c) for c in cles), key=lambda x: (x["ordre"], x["cle"]))
        out.append({"cle": gcle, "nom": nom, "ordre": ordre, "textes": textes_})
    return sorted(out, key=lambda x: (x["ordre"], x["cle"]))


def valeurs_site(guild_id: int) -> dict:
    """Les noms du site (clés « site.… ») CHANGÉS par la direction : la page garde les siens pour le reste."""
    return {cle: ligne[0] for cle, ligne in sorted(_cache.get(int(guild_id or 0), {}).items())
            if cle.startswith("site.") and cle in _DECLARES and ligne[0] is not None}


async def _ligne_en_base(db, guild_id: int, cle: str):
    async with db.execute("SELECT valeur, version, maj_le, maj_par FROM site_textes WHERE guild_id=? AND cle=?",
                          (int(guild_id), cle)) as cur:
        return await cur.fetchone()


async def _relire(guild_id: int, cle: str) -> None:
    """L'entrée du cache relue depuis la base après une écriture : le cache dit toujours ce que dit la base."""
    async with _get_db() as db:
        r = await _ligne_en_base(db, guild_id, cle)
    if r is None:
        _cache.get(int(guild_id), {}).pop(cle, None)
    else:
        _cache.setdefault(int(guild_id), {})[cle] = (r[0], int(r[1] or 0), int(r[2] or 0), int(r[3] or 0))


async def _prevenir(g, cle: str) -> None:
    for prefixe, fn in list(_ecouteurs):
        if not cle.startswith(prefixe):
            continue
        try:
            r = fn(g, cle)
            if inspect.isawaitable(r):
                await r
        except Exception as ex:  # un module prévenu en échec ne défait jamais l'écriture : dit au journal
            _signaler("E4", "module non prévenu d'un texte changé", f"{prefixe} {cle}", ex)


def _version(corps: dict, requise: bool) -> int | None:
    v = corps.get("version")
    if v is None and not requise:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise _Invalide("« version » : la version lue (un entier) est demandée.")
    return v


def _cle(corps) -> str:
    cle = corps.get("cle") if isinstance(corps, dict) else None
    if not isinstance(cle, str) or not FORMAT_CLE.fullmatch(cle):
        raise _Invalide("« cle » : un texte du registre est attendu.")
    if cle not in _DECLARES:
        raise _Invalide("Ce texte n'existe pas (ou plus).", 404)
    return cle


async def ecrire(g, auteur, corps) -> tuple[int, dict]:
    """`{cle, valeur, version}` : le texte du serveur, dès maintenant employé par le bot. La version lue ne correspond
    plus : 409 et la version enregistrée. Le texte d'origine recopié tel quel : le texte d'origine (rien de « modifié »)."""
    if _get_db is None:
        return 503, {"erreur": "Les textes démarrent : réessaie dans un instant."}
    try:
        corps = corps if isinstance(corps, dict) else {}
        cle = _cle(corps)
        d = _DECLARES[cle]
        valeur = propre(corps.get("valeur"), d)
        version = _version(corps, True)
    except _Invalide as ex:
        return ex.status, {"erreur": ex.message}
    garde = None if valeur == d["defaut"] else valeur
    t, par = int(time.time()), int(getattr(auteur, "id", 0) or 0)
    async with _verrou():
        async with _get_db() as db:
            r = await _ligne_en_base(db, g.id, cle)
            actuelle = int(r[1] or 0) if r is not None else 0
            conflit = version != actuelle
            if not conflit and r is None:
                await db.execute("INSERT INTO site_textes (guild_id, cle, valeur, version, maj_le, maj_par)"
                                 " VALUES (?,?,?,1,?,?)", (g.id, cle, garde, t, par))
            elif not conflit:
                await db.execute("UPDATE site_textes SET valeur=?, version=version+1, maj_le=?, maj_par=?"
                                 " WHERE guild_id=? AND cle=? AND version=?", (garde, t, par, g.id, cle, actuelle))
            await db.commit()
        await _relire(g.id, cle)
    if conflit:
        return 409, {"conflit": True, "erreur": "Ce texte a changé entre-temps.", "actuelle": item(g, cle)}
    await _prevenir(g, cle)
    journal = (f"Textes & noms : « {d['titre']} » modifié" if garde is not None
               else f"Textes & noms : « {d['titre']} » remis au texte d'origine")
    return 200, {"ok": True, "texte": item(g, cle), "avertissements": avertissements(valeur, d),
                 "_journal": {"texte": journal, "detail": cle}}


async def remettre(g, auteur, corps) -> tuple[int, dict]:
    """`{cle, version?}` : le texte d'origine, de nouveau (« Revenir au texte d'origine »)."""
    if _get_db is None:
        return 503, {"erreur": "Les textes démarrent : réessaie dans un instant."}
    try:
        corps = corps if isinstance(corps, dict) else {}
        cle = _cle(corps)
        version = _version(corps, False)
    except _Invalide as ex:
        return ex.status, {"erreur": ex.message}
    d = _DECLARES[cle]
    async with _verrou():
        async with _get_db() as db:
            r = await _ligne_en_base(db, g.id, cle)
            deja = r is None or r[0] is None
            conflit = not deja and version is not None and version != int(r[1] or 0)
            if not deja and not conflit:
                await db.execute("UPDATE site_textes SET valeur=NULL, version=version+1, maj_le=?, maj_par=?"
                                 " WHERE guild_id=? AND cle=?",
                                 (int(time.time()), int(getattr(auteur, "id", 0) or 0), g.id, cle))
                await db.commit()
        await _relire(g.id, cle)
    if deja:
        return 200, {"ok": True, "deja": True, "texte": item(g, cle), "_journal": None}
    if conflit:
        return 409, {"conflit": True, "erreur": "Ce texte a changé entre-temps.", "actuelle": item(g, cle)}
    await _prevenir(g, cle)
    return 200, {"ok": True, "texte": item(g, cle),
                 "_journal": {"texte": f"Textes & noms : « {d['titre']} » remis au texte d'origine", "detail": cle}}


# ═══════════════════════════════════════════════════════════════════════════════
#  Renommer un rôle (Capitainerie → Rôles & métiers)
# ═══════════════════════════════════════════════════════════════════════════════

def _nom_role(v) -> str:
    if not isinstance(v, str):
        raise _Invalide("« nom » : un texte est attendu.")
    nom = " ".join(_INVISIBLES.sub("", v).split())
    if not nom:
        raise _Invalide("Le nom du rôle ne peut pas être vide.")
    if len(nom) > NOM_ROLE_MAX:
        raise _Invalide(f"{NOM_ROLE_MAX} caractères au plus pour un rôle.")
    if nom.casefold() in ("@everyone", "@here", "everyone", "here"):
        raise _Invalide("Ce nom est réservé par Discord.")
    return nom


async def renommer_role(g, auteur, corps) -> tuple[int, dict]:
    """`{role_id, nom}` : un rôle lié à un élément du catalogue (métiers, races…) ou rattaché au clan, renommé sur
    Discord. Jamais un autre rôle (ni @everyone, ni un rôle géré, ni un rôle au-dessus du bot, ni un rôle à droits de
    gestion). Pour un métier, le nom sert aussi quand il faut recréer son rôle."""
    import affiches   # chargés à l'usage : affiches importe tableau, metiers importe ce module
    import metiers
    corps = corps if isinstance(corps, dict) else {}
    try:
        brut = str(corps.get("role_id") if corps.get("role_id") is not None else "")
        if not brut.isdigit() or not 0 < len(brut) <= 20:
            raise _Invalide("« role_id » : l'identifiant du rôle est attendu.")
        role_id = int(brut)
        nom = _nom_role(corps.get("nom"))
    except _Invalide as ex:
        return ex.status, {"erreur": ex.message}
    role = g.get_role(role_id)
    if role is None:
        return 404, {"erreur": "Ce rôle n'existe plus sur le serveur."}
    liens = [x for x in await affiches._liens(g.id) if int(x["role_id"]) == role.id]
    rattaches = (await metiers.reglages(g))["rattaches"] if metiers.pret() else []
    if not liens and role.id not in rattaches:
        return 403, {"erreur": "Ici, seuls les rôles liés au catalogue (métiers…) et les rôles rattachés au clan se "
                               "renomment."}
    refus = affiches.refus_role(g, role)
    if refus is not None:
        return 400, {"erreur": refus}
    if not affiches._peut_gerer_roles(g):
        return 403, {"erreur": "Il me manque la permission « Gérer les rôles »."}
    ancien = str(role.name)
    sortie = {"id": str(role.id), "nom": nom, "couleur": affiches._couleur_role(role)}
    if ancien == nom:
        return 200, {"ok": True, "deja": True, "role": sortie, "message": "Le rôle porte déjà ce nom.", "_journal": None}
    try:
        await role.edit(name=nom, reason=f"Renommé depuis le site par {auteur} ({getattr(auteur, 'id', 0)})"[:400])
    except discord.HTTPException as ex:
        _signaler("E5", "rôle non renommé : Discord a refusé", f"serveur={g.id} role={role.id}", ex)
        return 502, {"erreur": "Discord a refusé de renommer le rôle (hiérarchie ou permission)."}
    metiers_lies = [x["cle"] for x in liens if x["type"] == affiches.TYPE_METIER]
    if metiers_lies and metiers.pret():
        try:
            await metiers.retenir_noms(g, {cle: nom for cle in metiers_lies})
            metiers.planifier_guide(g)
        except Exception as ex:  # le rôle est renommé ; seul le nom gardé pour une future création manque : dit
            _signaler("E6", "nom du rôle de métier non gardé", f"serveur={g.id} {metiers_lies}", ex)
    return 200, {"ok": True, "role": sortie, "metiers": metiers_lies, "message": f"Rôle renommé « {nom} ».",
                 "_journal": f"Rôle « {ancien} » renommé « {nom} »"}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les adresses du site (`tableau.monter(textes)`)
# ═══════════════════════════════════════════════════════════════════════════════

async def _r_textes(g, auteur, requete, corps):
    if not _etat["charge"] and _get_db is not None:
        await charger()
    return 200, {"groupes": groupes(g)}


async def _r_site(g, auteur, requete, corps):
    if not _etat["charge"] and _get_db is not None:
        await charger()
    return 200, {"valeurs": valeurs_site(g.id)}


async def _r_texte(g, auteur, requete, corps):
    return await ecrire(g, auteur, corps)


async def _r_defaut(g, auteur, requete, corps):
    return await remettre(g, auteur, corps)


async def _r_renommer(g, auteur, requete, corps):
    return await renommer_role(g, auteur, corps)


def _verrou_texte(corps) -> str:
    """Le verrou d'édition d'un texte (équipe « Présence en direct ») : un texte à la fois par personne."""
    return "texte:" + str((corps or {}).get("cle") or "")


ROUTES_SITE = {
    "textes": {"methode": "GET", "fn": _r_textes, "corps_max": 0},
    "textes/site": {"methode": "GET", "fn": _r_site, "corps_max": 0},
    "texte": {"methode": "POST", "fn": _r_texte, "ecriture": True, "hors_ligne": True, "corps_max": 16 * 1024,
              "verrou": _verrou_texte},
    "texte/defaut": {"methode": "POST", "fn": _r_defaut, "ecriture": True, "hors_ligne": True, "corps_max": 2048,
                     "verrou": _verrou_texte},
    #  Un rôle renommé change tout de suite sur Discord : jamais rejoué hors ligne, compté dans les actions graves.
    "rell/role/renommer": {"methode": "POST", "fn": _r_renommer, "ecriture": True, "corps_max": 2048,
                           "grave": "roles"},
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les noms du site (`site/noyau.js` : CATEGORIES ; `site/affiche.js` : les statuts d'affiche)
# ═══════════════════════════════════════════════════════════════════════════════
#  Les mêmes que la page : un test compare cette liste à `site/noyau.js` (rien ne dérive sans se voir).

SITE_CATEGORIES = (
    ("accueil", "Accueil", "Accueil", "Ce qui t'attend", (
        ("attente", "Ce qui t'attend", "Tout ce qui demande une action, du plus urgent au moins urgent : un bouton par ligne."),)),
    ("port", "Le Port", "Le Port", "Discord", (
        ("apercu", "Aperçu", "Ce qui demande ton attention, en un coup d'œil."),
        ("journal", "Journal", "Tout ce qui s'est passé sur le serveur : l'important d'abord, puis jour par jour."),
        ("sanctions", "Sanctions", "Le casier de chaque membre, les modérateurs, le nettoyage du casier."),
        ("tickets", "Tickets", "Les tickets du serveur, ouverts et fermés, avec toute leur conversation."),
        ("repertoire", "Répertoire", "Toutes les personnes, de A à Z : chaque fiche réunit tout ce qui la concerne."),
        ("salons", "Salons & questions", "Questions, idées, sondages, entraide, annonces, et ce que chacun peut faire "
                                         "dans chaque salon."),
        ("nettoyage", "Nettoyage", "Ce qui est gardé, combien de temps, et le grand ménage quand tu veux."))),
    ("equipage", "L'Équipage", "Équipage", "Clan GoRP", (
        ("membres", "Équipage", "Les membres du clan, leur présence, les rappels d'inactivité."),
        ("fiches", "Fiches techniques", "Chaque membre et son affiche : par métier, par grade, de A à Z."),
        ("tickets", "Tickets du clan", "Les tickets Rell Seas du clan, ouverts et fermés."),
        ("annonces", "Annonces & événements", "Composer pour le salon Info : événements avec minuteur et réponses, "
                                               "annonces, métiers, listing."))),
    ("capitainerie", "La Capitainerie", "Capitainerie", "Fondateur & direction", (
        ("recrutement", "Demande de recrutement", "Les demandes et leurs étapes, les chefs d'équipe, les questions, les "
                                                  "réglages : tout le recrutement au même endroit."),
        ("affiches", "Affiches", "L'atelier des avis de recherche de l'équipage : créer, modifier, ranger par métier."),
        ("catalogue", "Catalogue RELL Seas", "Tout ce qui existe dans le jeu, et seulement cela : types, éléments, "
                                             "icônes officielles."),
        ("roles", "Rôles & métiers", "Un rôle Discord par métier, donné tout seul si tu le veux."),
        ("textes", "Textes & noms", "Chaque texte du bot et chaque nom du site, à ta façon : enregistré, il sert tout "
                                    "de suite."))),
)
#  Les sous-onglets des rubriques (`site/discord.js`, `site/recrutement_zone.js`, `site/annonces.js` : leur clé, « - »
#  devenu « _ ») et les onglets de la fiche d'une personne (`site/fiche.js`).
SITE_SOUS = (
    ("port", "salons", (("questions", "Questions"), ("idees", "Idées"), ("sondages", "Sondages"),
                        ("entraide", "Entraide & trade"), ("annonces", "Annonces"), ("droits", "Droits des salons"))),
    ("capitainerie", "recrutement", (("candidatures", "Candidatures"), ("chefs", "Chefs d'équipe"), ("questions", "Questions"),
                                     ("reglages", "Réglages"))),
    ("equipage", "annonces", (("composer", "Composer"), ("brouillons", "Brouillons"), ("a_venir", "À venir"),
                              ("publiees", "Publiées"), ("passes", "Passés"))),
)
SITE_FICHE = (("chrono", "Chronologie"), ("sanctions", "Sanctions"), ("tickets", "Tickets"),
              ("candidatures", "Candidatures"), ("questions", "Questions"), ("sondages", "Sondages et idées"),
              ("journal", "Journal"), ("donnees", "Décidées par lui"))
SITE_STATUTS = (("actif", "En service"), ("en_mer", "En mer"), ("absent", "Absent"), ("ancien", "Ancien de l'équipage"))
SITE_TAMPONS = (("en_mer", "En mer"), ("absent", "Absent"), ("ancien", "Ancien"))


def _declarer_site() -> None:
    ordre = 0
    for cat, titre, court, sous, rubriques in SITE_CATEGORIES:
        ordre += 10
        declarer(f"site.cat.{cat}.titre", titre, groupe="site", partie="Les grandes parties du site", ordre=ordre,
                 titre=f"{titre} · le nom", aide="En haut du site, sur la pancarte de cette partie.", max_=40,
                 lignes=False)
        declarer(f"site.cat.{cat}.court", court, groupe="site", partie="Les grandes parties du site", ordre=ordre + 1,
                 titre=f"{titre} · le nom court", aide="Sur téléphone, quand la place manque. Laissé tel quel, il suit "
                                                       "le nom choisi au-dessus.", max_=20, lignes=False)
        declarer(f"site.cat.{cat}.sous", sous, groupe="site", partie="Les grandes parties du site", ordre=ordre + 2,
                 titre=f"{titre} · le sous-titre", aide="La petite ligne sous le nom de la pancarte.", max_=40,
                 lignes=False)
    ordre = 100
    onglets_de = {(c, r): o for c, r, o in SITE_SOUS}
    for cat, titre_cat, _court, _sous, rubriques in SITE_CATEGORIES:
        for rub, titre, phrase in rubriques:
            ordre += 10          # le nom, la phrase, puis les sous-onglets dans leur ordre (6 au plus)
            partie = f"Les rubriques · {titre_cat}"
            declarer(f"site.rub.{cat}.{rub}.titre", titre, groupe="site", partie=partie, ordre=ordre, titre=titre,
                     aide="Le nom de la rubrique : sur son onglet et en titre de la page.", max_=40, lignes=False)
            declarer(f"site.rub.{cat}.{rub}.phrase", phrase, groupe="site", partie=partie, ordre=ordre + 1,
                     titre=f"{titre} · la phrase", aide="La phrase sous le titre de la rubrique.", max_=160,
                     lignes=False)
            for k, (sous, nom) in enumerate(onglets_de.get((cat, rub), ())):
                declarer(f"site.sous.{cat}.{rub}.{sous}", nom, groupe="site", partie=partie, ordre=ordre + 2 + k,
                         titre=f"{titre} · l'onglet « {nom} »", max_=30, lignes=False,
                         aide="Un sous-onglet de la rubrique (court : il tient sur un téléphone).")
    for k, (onglet, nom) in enumerate(SITE_FICHE):
        declarer(f"site.fiche.onglet.{onglet}", nom, groupe="site", partie="La fiche d'une personne", ordre=400 + k,
                 titre=f"L'onglet « {nom} »", aide="Un onglet de la fiche d'une personne (Répertoire, Équipage…).",
                 max_=30, lignes=False)
    for k, (statut, nom) in enumerate(SITE_STATUTS):
        declarer(f"site.affiche.statut.{statut}", nom, groupe="site", partie="Les affiches", ordre=420 + k,
                 titre=f"Statut « {nom} »", aide="Le statut d'une affiche, dans l'atelier et sur sa fiche.", max_=40,
                 lignes=False)
    for k, (statut, nom) in enumerate(SITE_TAMPONS):
        declarer(f"site.affiche.tampon.{statut}", nom, groupe="site", partie="Les affiches", ordre=440 + k,
                 titre=f"Tampon « {nom} »", aide="Le tampon posé en travers de l'affiche (court : il doit tenir).",
                 max_=16, lignes=False)


_declarer_site()
