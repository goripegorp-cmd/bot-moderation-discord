"""hierarchie.py — la HIÉRARCHIE de l'équipage (27/10/2026).

Le fondateur, mot pour mot : « un truc aussi extrêmement important sur le site, c'est qu'on puisse créer notre hiérarchie
au propre, qui soit visible par tout le monde, et nous, quand on la customise, renommer nos rôles, nos grades, qu'on
puisse savoir qui est le capitaine, qui est le bras droit, comme la vraie hiérarchie. […] Le capitaine, c'est le
fondateur. Le second, c'est le fameux la direction. […] on attribue correctement au personnel le rôle et l'affichage doit
être propre pour distinguer correctement. »

LES RANGS (par serveur : `hierarchie_rangs`, posés une fois, jamais reposés s'ils ont été changés)
  · Une liste ordonnée — au départ Capitaine · Second · Commandant · Chef de flotte · Vigie · Charpentier · Corsaire ·
    Moussaillon. Chaque rang : un nom RENOMMABLE, un insigne (une icône du site), une couleur, une phrase courte
    facultative, un rôle Discord facultatif, une version (deux écrans ne s'écrasent jamais : 409).
  · Trois rangs sont VERROUILLÉS (ni retirés, ni déplacés ; renommables) : le Capitaine (le fondateur, lui seul, en
    tête) et le Second (la direction, le bras droit, juste dessous) — ils suivent TETE_IDS (`tableau._tete`, le fondateur
    étant le super-owner) et ne s'attribuent jamais sur le site — et le dernier, le rang par défaut (Moussaillon), celui
    de tout membre du clan sans autre rang : le rang d'arrivée. Les rangs intermédiaires s'ajoutent, se renomment, se
    réordonnent et se retirent.

LE RANG D'UN MEMBRE (calculé à chaque lecture, jamais recopié)
  1. le fondateur → Capitaine ; la direction → Second ;
  2. hors du clan (rôle du clan perdu, parti du serveur) → aucun rang affiché — rien n'est effacé : il le retrouve s'il
     revient ;
  3. un rang intermédiaire LIÉ à un rôle Discord : qui porte ce rôle a ce rang (le plus haut s'il en porte plusieurs) —
     un rôle donné ou retiré directement sur Discord se lit aussitôt ;
  4. le rang attribué sur le site (`hierarchie_membres`) — sauf un rang lié dont il n'a plus le rôle (retiré sur Discord) ;
  5. la reprise de l'ancien grade écrit sur son affiche (`hierarchie_reprise`, par le NOM du grade) ;
  6. sinon, le rang par défaut.

L'ATTRIBUTION (la tête seule, comme toute écriture du site : `tableau._executer`)
  · Un membre du clan, un rang (jamais Capitaine ni Second), la version de son attribution vérifiée (409), au journal.
  · Les rôles Discord : le rôle du rang donné, les AUTRES rôles de rang liés retirés — jamais un autre rôle, jamais ceux
    du Capitaine, du Second ni du rang par défaut (il peut être le rôle du clan : le retirer sortirait le membre du clan).
    Tout est vérifié AVANT (permission « Gérer les rôles », hiérarchie du bot) : un refus a une raison claire et rien ne
    bouge ; un refus de Discord à mi-chemin est défait.
  · Un rôle ne se lie à un rang qu'à ces conditions : ni @everyone, ni géré par une intégration, ni rôle de sanction, ni
    une permission dangereuse (`securite_site.PERMISSIONS` : Administrateur, Gérer le serveur, Gérer les rôles, Bannir,
    Expulser, Gérer les webhooks), ni déjà lié ailleurs ; pour un rang intermédiaire, ni le rôle du clan ni un rôle
    au-dessus du bot.

LA REPRISE DE L'EXISTANT (les affiches portent déjà un grade écrit, parfois une clé d'un type « grade » du catalogue)
  · Chaque grade (des affiches actives et du type « grade » du catalogue) est repris par son NOM : une correspondance par
    nom (« Moussaillon » → Moussaillon), posée une fois par nom, visible et corrigeable sur le site. Un nom sans rang du
    même nom — ou celui d'un rang verrouillé — reste « à relier » : son affiche prend le rang par défaut.
  · Le champ « grade » des affiches n'est jamais touché : il reste lisible dans l'atelier. Une affiche SANS membre lié
    garde son grade écrit, partout.

LES ADRESSES (`tableau.monter`, la tête seule, verrous de la présence en direct, journal du site)
  GET  equipage/hierarchie                 tout ce que la vue de la direction montre
  POST equipage/hierarchie/rang            {id?, nom, insigne, couleur, phrase, version?} — ajouter ou modifier un rang
  POST equipage/hierarchie/rang/supprimer  {id} — un rang intermédiaire (ses membres reviennent au rang par défaut)
  POST equipage/hierarchie/rang/deplacer   {id, sens} — un rang intermédiaire, parmi les intermédiaires
  POST equipage/hierarchie/rang/role       {id, role_id} | {id, creer} | {id, retirer} — le rôle Discord d'un rang
  POST equipage/hierarchie/attribuer       {membre, rang, version} | {affectations: [...]} — 25 au plus d'un coup
  POST equipage/hierarchie/reprise         {cle, rang, version} | {cle, creer} — la correspondance d'un ancien grade
La lecture de l'équipage (`site_equipage.lecture_equipage`) et la vitrine (`site_vitrine`) lisent `vue_equipage` et
`vue_publique` ; les affiches, `rang_affiche` et `grade_affiche` (le grade montré vient du rang du membre lié).
"""
from __future__ import annotations

import asyncio
import re
import secrets
import sys
import time
import unicodedata

import discord

import affiches
import diag
import owner_ids
import rellseas_panneau
import securite_site
import tableau
import textes

# ═══════════════════════════════════════════════════════════════════════════════
#  Réglages
# ═══════════════════════════════════════════════════════════════════════════════

FORMAT_RANG = re.compile(r"[A-Za-z0-9_-]{2,32}")
FORMAT_COULEUR = re.compile(r"#[0-9a-fA-F]{6}")
FORMAT_CLE_GRADE = re.compile(r"[a-z0-9 ]{1,60}")
CAPITAINE, SECOND, DEFAUT = "capitaine", "second", "defaut"
VERROUS = (CAPITAINE, SECOND, DEFAUT)
RANGS_MAX = 24                  # rangs au plus par serveur (les trois verrouillés compris)
NOM_MAX, PHRASE_MAX = 40, 140
AFFECTATIONS_MAX = 25           # membres nommés d'un coup (comme le retrait du clan par lot)
GRADES_FRAIS = 1.0              # s : les grades écrits des affiches, relus au plus une fois par seconde
#  Les insignes : des icônes du site (site/icones/ui.svg), choisies pour une hiérarchie de pirates.
INSIGNES = ("capitainerie", "boussole", "drapeau", "navire", "longue_vue", "coffre", "sabre", "ancre", "canon", "crane",
            "etoile", "grade", "roles", "cloche", "carte", "parchemin", "plume", "cle", "port", "equipage")
#  Les couleurs proposées (les encres du site ; une autre couleur #RRVVBB reste acceptée).
COULEURS = ("#8e2a24", "#8a6a2c", "#1f4e5a", "#3f6b3a", "#5e3a4e", "#7a4b2a", "#4a5560", "#7a5a22", "#a8641c", "#3d2f5e",
            "#6a1c17", "#2b1d12")
#  Le départ : (identifiant, nom, insigne, couleur, phrase, verrou) — dans l'ordre.
DEPART = (
    ("capitaine", "Capitaine", "capitainerie", "#8e2a24", "Le fondateur, maître à bord.", CAPITAINE),
    ("second", "Second", "boussole", "#8a6a2c", "Le bras droit du capitaine.", SECOND),
    ("commandant", "Commandant", "drapeau", "#1f4e5a", "Il commande les opérations de l'équipage.", ""),
    ("chef-de-flotte", "Chef de flotte", "navire", "#3f6b3a", "Il mène la flotte en mer.", ""),
    ("vigie", "Vigie", "longue_vue", "#5e3a4e", "L'œil de l'équipage, toujours aux aguets.", ""),
    ("charpentier", "Charpentier", "coffre", "#7a4b2a", "Il bâtit et entretient le navire.", ""),
    ("corsaire", "Corsaire", "sabre", "#4a5560", "Un pirate aguerri de l'équipage.", ""),
    ("moussaillon", "Moussaillon", "ancre", "#7a5a22", "Le rang d'arrivée de chaque membre du clan.", DEFAUT),
)

#  Les textes des trois pages (la direction, l'équipage, la vitrine) : des noms « site. », lus par `libelle`, rangés dans
#  la famille « Le site de l'équipage » (Capitainerie › Réglages › Textes & noms).
GROUPE_TEXTES = "equipage_site"
TEXTES_SITE = (
    ("site.hierarchie.titre", "La hiérarchie", "La hiérarchie · le titre",
     "Le nom de la vue, sur le site de l'équipage, la vitrine et le site de la direction.", 40),
    ("site.hierarchie.phrase", "Du capitaine au dernier moussaillon : le rang de chacun à bord.", "La hiérarchie · la phrase",
     "Sous le titre de la hiérarchie.", 160),
    ("site.hierarchie.bras_droit", "Bras droit du capitaine", "Le second · sa mention",
     "Le ruban du second, dans la hiérarchie.", 60),
    ("site.hierarchie.vacant", "À nommer", "Un rang sans personne", "Dans un rang où personne n'est nommé.", 60),
    ("site.hierarchie.liste", "Voir la liste", "Le dernier rang · sa liste",
     "Le titre de la liste repliable du dernier rang (les plus nombreux).", 40),
)
for _k, (_cle, _defaut, _titre, _aide, _max) in enumerate(TEXTES_SITE):
    textes.declarer(_cle, _defaut, groupe=GROUPE_TEXTES, titre=_titre, aide=_aide, max_=_max, lignes=False,
                    partie="La hiérarchie", ordre=400 + _k)

_get_db = None
_cfg = None
_log = print
_verrou = None
_etats: dict = {}               # serveur → l'état en mémoire (rangs, attributions, reprise, grades des affiches)


def setup(*, get_db, cfg, log=None) -> None:
    """`cfg(guild_id)` (async) : les réglages du serveur (le rôle du clan : `rellseas_panneau.CLE_ROLE_CIBLE`). Branche le
    rang affiché sur les affiches (`affiches.brancher_hierarchie`) : après l'étape « affiches » (son `setup` le défait)."""
    global _get_db, _cfg, _log, _verrou
    _get_db, _cfg, _log = get_db, cfg, log or print
    _verrou = None
    _etats.clear()
    affiches.brancher_hierarchie(sys.modules[__name__])


def pret() -> bool:
    return _get_db is not None and _cfg is not None


def connu(g) -> bool:
    """L'état de ce serveur est en mémoire (`assurer` l'a lu) : les lectures synchrones (affiches) peuvent s'en servir."""
    return pret() and g is not None and getattr(g, "id", None) in _etats


def _signaler(code: str, message: str, ex=None, detail: str = "") -> None:
    """Un message STABLE (le tableau des erreurs ne sature pas), le détail sur une ligne à part."""
    _log(f"[HIERARCHIE][{code}] {message}")
    _log(f"[HIERARCHIE][{code}:DETAIL] {detail} {type(ex).__name__ + ' ' + str(ex) if ex is not None else ''}".rstrip())
    if ex is not None:
        diag.compter("hierarchie", code, ex)


def _verrou_ecriture() -> asyncio.Lock:
    """Une écriture à la fois (lire la version, la comparer, écrire). Un verrou par boucle d'évènements."""
    global _verrou
    boucle = asyncio.get_running_loop()
    if _verrou is None or _verrou[0] is not boucle:
        _verrou = (boucle, asyncio.Lock())
    return _verrou[1]


async def init_db() -> None:
    async with _get_db() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS hierarchie_rangs (guild_id INTEGER NOT NULL, id TEXT NOT NULL, nom TEXT NOT NULL,"
            " insigne TEXT NOT NULL DEFAULT '', couleur TEXT NOT NULL DEFAULT '', phrase TEXT NOT NULL DEFAULT '',"
            " ordre INTEGER NOT NULL DEFAULT 0, verrou TEXT NOT NULL DEFAULT '', role_id INTEGER NOT NULL DEFAULT 0,"
            " version INTEGER NOT NULL DEFAULT 1, cree_le INTEGER NOT NULL, maj_le INTEGER NOT NULL,"
            " maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, id))")
        #  Le rang attribué sur le site : une ligne par membre. Un membre qui quitte le clan la garde (rien n'est effacé).
        await db.execute(
            "CREATE TABLE IF NOT EXISTS hierarchie_membres (guild_id INTEGER NOT NULL, membre_id INTEGER NOT NULL,"
            " rang_id TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, maj_le INTEGER NOT NULL,"
            " maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, membre_id))")
        #  La reprise des anciens grades : un nom de grade (normalisé) → un rang ('' : le rang par défaut).
        await db.execute(
            "CREATE TABLE IF NOT EXISTS hierarchie_reprise (guild_id INTEGER NOT NULL, cle TEXT NOT NULL, nom TEXT NOT NULL,"
            " rang_id TEXT NOT NULL DEFAULT '', auto INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,"
            " maj_le INTEGER NOT NULL, maj_par INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, cle))")
        await db.execute("CREATE TABLE IF NOT EXISTS hierarchie_etat (guild_id INTEGER PRIMARY KEY,"
                         " depart_pose INTEGER NOT NULL DEFAULT 0)")
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Les petits outils
# ═══════════════════════════════════════════════════════════════════════════════

def cle_grade(nom) -> str:
    """Un nom de grade comparable : sans accents, en minuscules, la ponctuation en espaces (« Chef-de-flotte » →
    « chef de flotte »)."""
    s = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()[:60]


def _type_grade(types: dict):
    """La clé du type « grade » du catalogue (par sa clé, sinon par son nom), ou None."""
    if "grade" in (types or {}):
        return "grade"
    for k, t in sorted((types or {}).items(), key=lambda x: (x[1].get("ordre", 0), x[0])):
        if re.search(r"\bgrades?\b", f"{t.get('champ', '')} {t.get('nom', '')}", re.I):
            return k
    return None


def nom_du_grade(grade) -> str:
    """Le NOM d'un grade écrit sur une affiche : l'élément du type « grade » du catalogue s'il en est une clé, sinon le
    texte lui-même (« quartier_maitre » → « quartier maitre »)."""
    g = str(grade or "").strip()
    if not g:
        return ""
    types, elements = affiches._cat.get("types") or {}, affiches._cat.get("elements") or {}
    gt = _type_grade(types)
    e = elements.get((gt, g)) if gt else None
    return str(e["nom"]) if e else g.replace("_", " ")


def _sans_emoji(texte) -> str:
    import site_equipage   # chargé à l'usage : site_equipage importe ce module
    return site_equipage.sans_emoji(texte)


def _tete() -> tuple[list, list]:
    """(capitaines, seconds) : TETE_IDS, le fondateur étant le super-owner (`owner_ids`), la direction les autres."""
    tete = sorted(int(x) for x in tableau._tete)
    capitaines = [u for u in tete if owner_ids.is_super_owner(u)]
    return capitaines, [u for u in tete if u not in capitaines]


def _role_lie(g, r):
    """Le rôle Discord d'un rang, s'il existe encore sur le serveur (sinon None : le lien ne compte pas)."""
    return g.get_role(int(r["role_id"])) if r.get("role_id") and g is not None else None


def _haut_du_bot(g) -> int:
    return int(getattr(getattr(getattr(g, "me", None), "top_role", None), "position", 0) or 0)


# ═══════════════════════════════════════════════════════════════════════════════
#  L'état d'un serveur (en mémoire, relu après chaque écriture)
# ═══════════════════════════════════════════════════════════════════════════════

_COL_RANGS = ("id", "nom", "insigne", "couleur", "phrase", "ordre", "verrou", "role_id", "version", "cree_le", "maj_le",
              "maj_par")


async def _assurer_depart(gid: int) -> None:
    """Les rangs de départ, posés UNE fois par serveur (effacés ou changés par la tête, ils ne reviennent pas) — et les
    trois rangs verrouillés, toujours là (un rang verrouillé ne se retire pas : s'il manque, il revient)."""
    async with _verrou_ecriture():
        async with _get_db() as db:
            async with db.execute("SELECT depart_pose FROM hierarchie_etat WHERE guild_id=?", (gid,)) as cur:
                r = await cur.fetchone()
            async with db.execute("SELECT id, verrou FROM hierarchie_rangs WHERE guild_id=?", (gid,)) as cur:
                lignes = await cur.fetchall()
            t = int(time.time())
            change = False
            if (r is None or not int(r[0] or 0)) and not lignes:
                for n, (ident, nom, insigne, couleur, phrase, verrou) in enumerate(DEPART, start=1):
                    await db.execute("INSERT INTO hierarchie_rangs (guild_id, id, nom, insigne, couleur, phrase, ordre, verrou,"
                                     " role_id, version, cree_le, maj_le, maj_par) VALUES (?,?,?,?,?,?,?,?,0,1,?,?,0)",
                                     (gid, ident, nom, insigne, couleur, phrase, n, verrou, t, t))
                change = True
            else:
                ids, verrous = {i for i, _v in lignes}, {v for _i, v in lignes if v}
                for ident, nom, insigne, couleur, phrase, verrou in DEPART:
                    if verrou and verrou not in verrous:
                        libre = ident if ident not in ids else f"{ident}-{secrets.token_urlsafe(4)}"
                        ordre = {CAPITAINE: -2, SECOND: -1}.get(verrou, 10 ** 6)
                        await db.execute("INSERT INTO hierarchie_rangs (guild_id, id, nom, insigne, couleur, phrase, ordre,"
                                         " verrou, role_id, version, cree_le, maj_le, maj_par) VALUES (?,?,?,?,?,?,?,?,0,1,?,?,0)",
                                         (gid, libre, nom, insigne, couleur, phrase, ordre, verrou, t, t))
                        change = True
                        _signaler("E1", "rang verrouillé absent : reposé", detail=f"serveur={gid} verrou={verrou}")
            if r is None or not int(r[0] or 0):
                await db.execute("INSERT OR REPLACE INTO hierarchie_etat (guild_id, depart_pose) VALUES (?, 1)", (gid,))
                change = True
            if change:
                await _renumeroter(db, gid)
                await db.commit()


async def _renumeroter(db, gid: int) -> None:
    """L'ordre rangé : le Capitaine, le Second, les intermédiaires dans leur ordre, le rang par défaut en dernier."""
    async with db.execute("SELECT id, verrou FROM hierarchie_rangs WHERE guild_id=? ORDER BY ordre, cree_le, id", (gid,)) as cur:
        lignes = await cur.fetchall()
    rang = {CAPITAINE: 0, SECOND: 1, "": 2, DEFAUT: 3}
    for n, (ident, _v) in enumerate(sorted(lignes, key=lambda x: rang.get(x[1], 2)), start=1):
        await db.execute("UPDATE hierarchie_rangs SET ordre=? WHERE guild_id=? AND id=?", (n, gid, ident))


async def _charger(gid: int, clan_role: int | None = None) -> dict:
    """L'état de ce serveur, relu de la base (quelques dizaines de lignes) : il remplace l'ancien."""
    async with _get_db() as db:
        async with db.execute(f"SELECT {', '.join(_COL_RANGS)} FROM hierarchie_rangs WHERE guild_id=?"
                              " ORDER BY ordre, cree_le, id", (gid,)) as cur:
            rangs = [dict(zip(_COL_RANGS, r)) for r in await cur.fetchall()]
        async with db.execute("SELECT membre_id, rang_id, version, maj_le, maj_par FROM hierarchie_membres WHERE guild_id=?",
                              (gid,)) as cur:
            explicites = {int(m): {"rang": str(r), "version": int(v), "maj_le": int(t), "maj_par": int(p)}
                          for m, r, v, t, p in await cur.fetchall()}
        async with db.execute("SELECT cle, nom, rang_id, auto, version, maj_le, maj_par FROM hierarchie_reprise WHERE guild_id=?",
                              (gid,)) as cur:
            reprise = {str(c): {"nom": str(n), "rang": str(r or ""), "auto": bool(a), "version": int(v), "maj_le": int(t),
                                "maj_par": int(p)} for c, n, r, a, v, t, p in await cur.fetchall()}
    for r in rangs:
        r["role_id"] = int(r["role_id"] or 0)
        r["version"] = int(r["version"])
        r["verrou"] = str(r["verrou"] or "")
    ancien = _etats.get(gid) or {}
    st = {"rangs": rangs, "par_id": {r["id"]: r for r in rangs},
          "intermediaires": [r for r in rangs if not r["verrou"]],
          "par_verrou": {r["verrou"]: r for r in rangs if r["verrou"]},
          "explicites": explicites, "reprise": reprise,
          "affiches": ancien.get("affiches", {}), "grades_t": ancien.get("grades_t", 0.0), "noms_grades": ancien.get("noms_grades", {}),
          "clan_role": int(clan_role if clan_role is not None else ancien.get("clan_role", 0) or 0)}
    _etats[gid] = st
    return st


async def _lire_grades(g, st) -> None:
    """Les affiches ACTIVES de ce serveur (membre, grade écrit, prime) et les noms de grade à reprendre : ceux des affiches
    et ceux d'un type « grade » du catalogue. Un nom jamais vu prend sa correspondance par son nom (sous le verrou)."""
    types, elements = await affiches._catalogue()
    async with _get_db() as db:
        async with db.execute("SELECT id, membre_id, grade, prime FROM rell_affiches WHERE guild_id=? AND retire_le=0",
                              (g.id,)) as cur:
            lignes = await cur.fetchall()
    par_membre, noms = {}, {}
    for ident, mid, grade, prime in lignes:
        nom = nom_du_grade(grade)
        k = cle_grade(nom)
        if k:
            noms.setdefault(k, [nom, 0])[1] += 1
        if int(mid or 0):
            par_membre[int(mid)] = {"id": str(ident), "grade": str(grade or ""), "prime": int(prime or 0)}
    gt = _type_grade(types)
    for (t, _cle), e in elements.items():
        if gt and t == gt and cle_grade(e["nom"]):
            noms.setdefault(cle_grade(e["nom"]), [str(e["nom"]), 0])
    st["affiches"], st["noms_grades"], st["grades_t"] = par_membre, {k: v[1] for k, v in noms.items()}, time.monotonic()
    nouveaux = {k: v[0] for k, v in noms.items() if k not in st["reprise"]}
    if not nouveaux:
        return
    async with _verrou_ecriture():
        t = int(time.time())
        async with _get_db() as db:
            for k, nom in sorted(nouveaux.items()):
                cible = _rang_du_nom(st, nom)
                await db.execute("INSERT OR IGNORE INTO hierarchie_reprise (guild_id, cle, nom, rang_id, auto, version, maj_le,"
                                 " maj_par) VALUES (?,?,?,?,1,1,?,0)", (g.id, k, nom[:60], cible["id"] if cible else "", t))
            await db.commit()
        await _charger(g.id)
    _log("[HIERARCHIE] anciens grades repris par leur nom")
    _log(f"[HIERARCHIE:DETAIL] serveur={g.id} {len(nouveaux)} nom(s)")


def affiches_changees(guild_id: int) -> None:
    """Une affiche écrite (créée, modifiée, mise à la corbeille, restaurée) : ses grades sont relus à la prochaine lecture."""
    st = _etats.get(int(guild_id or 0))
    if st is not None:
        st["grades_t"] = 0.0


def _rang_du_nom(st, nom):
    """Le rang de ce nom (comparé sans accents ni casse) — jamais le Capitaine ni le Second (ils suivent TETE_IDS) —, ou
    None."""
    k = cle_grade(nom)
    return next((r for r in st["rangs"] if k and cle_grade(r["nom"]) == k and r["verrou"] not in (CAPITAINE, SECOND)), None)


async def assurer(g) -> dict | None:
    """L'état de ce serveur, prêt à lire : les rangs de départ posés, le rôle du clan relu, les grades des affiches frais.
    None quand la hiérarchie n'est pas branchée (les lectures gardent alors leur comportement d'avant)."""
    if not pret() or g is None:
        return None
    try:
        c = await _cfg(g.id)
    except Exception as ex:   # sans réglages lisibles, le rôle du clan d'avant reste (le détail part au journal)
        _signaler("E2", "réglages illisibles", ex)
        c = None
    clan_role = int((c or {}).get(rellseas_panneau.CLE_ROLE_CIBLE, 0) or 0) if c is not None else None
    st = _etats.get(g.id)
    if st is None:
        await _assurer_depart(g.id)
        st = await _charger(g.id, clan_role)
    if clan_role is not None:
        st["clan_role"] = clan_role
    if time.monotonic() - st["grades_t"] > GRADES_FRAIS:
        await _lire_grades(g, st)
        st = _etats[g.id]
        if clan_role is not None:
            st["clan_role"] = clan_role
    return st


# ═══════════════════════════════════════════════════════════════════════════════
#  Le rang d'un membre
# ═══════════════════════════════════════════════════════════════════════════════

def _au_clan(m, st) -> bool:
    rid = int(st.get("clan_role") or 0)
    return m is not None and not getattr(m, "bot", False) and rid > 0 and \
        any(int(getattr(r, "id", 0) or 0) == rid for r in (getattr(m, "roles", None) or []))


def _par_site(g, r) -> bool:
    """Ce rang se donne par le site (attribution ou reprise) : le rang par défaut, ou un intermédiaire SANS rôle lié
    existant (un rang lié se lit par son rôle Discord)."""
    return r is not None and (r["verrou"] == DEFAUT or (not r["verrou"] and _role_lie(g, r) is None))


def _rang_et_source(g, st, mid: int):
    """(le rang de ce membre, d'où il vient : tete · role · site · reprise · defaut) — (None, "hors") hors du clan."""
    capitaines, seconds = _tete()
    if mid in capitaines and CAPITAINE in st["par_verrou"]:
        return st["par_verrou"][CAPITAINE], "tete"
    if mid in seconds and SECOND in st["par_verrou"]:
        return st["par_verrou"][SECOND], "tete"
    m = g.get_member(int(mid)) if g is not None else None
    if not _au_clan(m, st):
        return None, "hors"
    tient = {int(getattr(r, "id", 0) or 0) for r in getattr(m, "roles", None) or []}
    for r in st["intermediaires"]:   # dans l'ordre : le plus haut d'abord
        role = _role_lie(g, r)
        if role is not None and role.id in tient:
            return r, "role"
    e = st["explicites"].get(int(mid))
    if e:
        r = st["par_id"].get(e["rang"])
        if _par_site(g, r):
            return r, "site"
    a = st["affiches"].get(int(mid))
    k = cle_grade(nom_du_grade(a["grade"])) if a else ""
    if k and k in st["reprise"]:
        r = st["par_id"].get(st["reprise"][k]["rang"])
        if _par_site(g, r):
            return r, "reprise"
    return st["par_verrou"].get(DEFAUT), "defaut"


def rang_de(g, membre_id: int):
    """Le rang de ce membre (dict), ou None (hors du clan, ou la hiérarchie pas encore lue)."""
    st = _etats.get(getattr(g, "id", None)) if pret() else None
    return _rang_et_source(g, st, int(membre_id))[0] if st else None


def _court(r) -> dict:
    return {"id": r["id"], "nom": r["nom"], "couleur": r["couleur"], "insigne": r["insigne"]}


def rang_affiche(g, a: dict):
    """Le rang que montre une affiche : None sans membre lié (elle garde son grade écrit) ; un rang vide (`nom` "") pour
    un membre hors du clan (il perd son rang affiché, rien n'est effacé) ; sinon le rang de son membre."""
    st = _etats.get(getattr(g, "id", None)) if pret() else None
    if st is None or not int(a.get("membre_id") or 0):
        return None
    r, _s = _rang_et_source(g, st, int(a["membre_id"]))
    return _court(r) if r else {"id": "", "nom": "", "couleur": "", "insigne": ""}


def grade_affiche(g, a: dict) -> str:
    """Le grade MONTRÉ sur une affiche : le nom du rang de son membre (rien s'il a quitté le clan), sinon — sans membre lié,
    ou sans hiérarchie lue — son grade écrit."""
    r = rang_affiche(g, a) if connu(g) else None
    return str(a.get("grade") or "") if r is None else r["nom"]


def ordre_de(g, membre_id: int) -> int:
    """La place de son rang dans la hiérarchie (0 : le Capitaine) ; hors du clan ou sans hiérarchie : après tous."""
    st = _etats.get(getattr(g, "id", None)) if pret() else None
    if st is None:
        return 0
    r = _rang_et_source(g, st, int(membre_id))[0]
    return st["rangs"].index(r) if r in st["rangs"] else len(st["rangs"])


def _gens(g, st) -> list:
    """Les membres de la hiérarchie : le rôle du clan (sans les robots) et la tête présente sur le serveur."""
    role = g.get_role(int(st.get("clan_role") or 0)) if st.get("clan_role") else None
    ids = {m.id for m in (getattr(role, "members", None) or []) if not getattr(m, "bot", False)}
    capitaines, seconds = _tete()
    ids |= {u for u in capitaines + seconds if g.get_member(u) is not None}
    return sorted(ids)


def _composition(g, st) -> tuple[dict, dict]:
    """({rang: [membres, du plus haut au plus bas : la prime, puis le nom]}, {membre: (rang, source)})."""
    par_rang, de = {}, {}
    for mid in _gens(g, st):
        r, source = _rang_et_source(g, st, mid)
        if r is None:
            continue
        de[mid] = (r, source)
        par_rang.setdefault(r["id"], []).append(mid)

    def cle(mid):
        m = g.get_member(mid)
        return (-int((st["affiches"].get(mid) or {}).get("prime", 0)), str(getattr(m, "display_name", "") or "").casefold(), mid)
    for k in par_rang:
        par_rang[k].sort(key=cle)
    return par_rang, de


# ═══════════════════════════════════════════════════════════════════════════════
#  Les lectures : la direction, l'équipage, la vitrine
# ═══════════════════════════════════════════════════════════════════════════════

def _sortie_role(g, st, r) -> dict | None:
    if not r["role_id"]:
        return None
    role = g.get_role(r["role_id"])
    if role is None:
        return {"id": str(r["role_id"]), "nom": "", "couleur": "", "existe": False, "gere": False,
                "raison": "Ce rôle n'existe plus sur Discord : le rang se donne de nouveau par le site."}
    gere = r["verrou"] == ""
    raison = "" if gere else "Le bot ne donne ni ne retire ce rôle : il est seulement montré avec le rang."
    if gere:
        raison = _refus_role_bot(g, role) or ""
    return {"id": str(role.id), "nom": role.name, "couleur": affiches._couleur_role(role), "existe": True, "gere": gere,
            "raison": raison}


def _sortie_rang(g, st, r) -> dict:
    return {"id": r["id"], "nom": r["nom"], "insigne": r["insigne"], "couleur": r["couleur"], "phrase": r["phrase"],
            "verrou": r["verrou"], "version": int(r["version"]), "ordre": int(r["ordre"]), "role": _sortie_role(g, st, r)}


def _personne(g, mid: int) -> dict:
    m = g.get_member(int(mid))
    return {"id": str(mid), "nom": _sans_emoji(m.display_name) if m is not None else "Membre parti",
            "avatar": str(m.display_avatar.with_size(64).url) if m is not None else ""}


async def _liens_catalogue(g) -> set:
    return {int(x["role_id"]) for x in await affiches._liens(g.id)}


async def sortie_direction(g, st) -> dict:
    """Tout ce que la vue de la direction montre : les rangs et leurs membres, la source de chaque rang, la reprise des
    anciens grades, les rôles du serveur (pour lier un rang) et ce que le bot peut faire."""
    par_rang, de = _composition(g, st)
    capitaines, seconds = _tete()
    rangs = []
    for r in st["rangs"]:
        sortie = _sortie_rang(g, st, r)
        sortie["membres"] = [_personne(g, mid) for mid in par_rang.get(r["id"], [])]
        sortie["n"] = len(sortie["membres"])
        rangs.append(sortie)
    membres = {str(mid): {"rang": r["id"], "source": s,
                          "version": int((st["explicites"].get(mid) or {}).get("version", 0))}
               for mid, (r, s) in de.items()}
    #  Ceux qui ont quitté le clan gardent leur rang écrit (rien n'est effacé) : il leur revient s'ils reviennent.
    hors = {str(mid): e["rang"] for mid, e in sorted(st["explicites"].items())[:2000]
            if mid not in de and e["rang"] in st["par_id"]}
    reserves = {cle_grade(r["nom"]) for r in st["rangs"] if r["verrou"] in (CAPITAINE, SECOND)}
    reprise = sorted(({"cle": k, "nom": x["nom"], "rang": x["rang"] if x["rang"] in st["par_id"] else "", "auto": x["auto"],
                       "version": x["version"], "n": int(st["noms_grades"].get(k, 0)), "reserve": k in reserves}
                      for k, x in st["reprise"].items() if k in st["noms_grades"]),
                     key=lambda x: (-x["n"], x["nom"].casefold()))
    liens = await _liens_catalogue(g)
    haut, clan_role = _haut_du_bot(g), int(st.get("clan_role") or 0)
    roles = []
    for role in sorted(getattr(g, "roles", []) or [], key=lambda x: -int(getattr(x, "position", 0) or 0)):
        if role.id == g.id or getattr(role, "is_default", lambda: False)():
            continue
        roles.append({"id": str(role.id), "nom": role.name, "couleur": affiches._couleur_role(role),
                      "position": int(getattr(role, "position", 0) or 0), "refus": _refus_general(role, liens) or "",
                      "au_dessus": int(getattr(role, "position", 0) or 0) >= haut, "clan": role.id == clan_role,
                      "porteurs": sum(1 for m in (getattr(role, "members", None) or []) if not getattr(m, "bot", False))})
    return {"rangs": rangs, "membres": membres, "hors": hors, "reprise": reprise, "roles": roles,
            "gestion": affiches._peut_gerer_roles(g), "insignes": list(INSIGNES), "couleurs": list(COULEURS),
            "tete": {"capitaines": [str(x) for x in capitaines], "seconds": [str(x) for x in seconds]},
            "maximum": RANGS_MAX, "lot": AFFECTATIONS_MAX}


def _sortie_publique(r) -> dict:
    return {"id": r["id"], "nom": r["nom"], "insigne": r["insigne"], "couleur": r["couleur"], "phrase": r["phrase"],
            "verrou": r["verrou"]}


async def vue_equipage(g, lignes: list) -> dict | None:
    """Pour le site de l'équipage (lecture seule) : chaque rang dans l'ordre, et ses membres — nom et portrait Discord,
    son affiche (identifiant) s'il en a une. Aucun identifiant Discord."""
    st = await assurer(g)
    if st is None:
        return None
    par_rang, _de = _composition(g, st)
    affiche_de = {int(a["membre_id"]): a["id"] for a in lignes if a["membre_id"]}
    rangs = []
    for r in st["rangs"]:
        gens = []
        for mid in par_rang.get(r["id"], []):
            p = _personne(g, mid)
            gens.append({"nom": p["nom"], "avatar": p["avatar"], "affiche": affiche_de.get(mid)})
        rangs.append(dict(_sortie_publique(r), n=len(gens), membres=gens))
    return {"rangs": rangs}


async def vue_publique(g, lignes: list, jetons: dict) -> dict | None:
    """Pour la VITRINE publique : chaque rang dans l'ordre, combien ils sont, et ceux dont l'affiche y est montrée (par son
    jeton) — jamais un nom ni un identifiant Discord."""
    st = await assurer(g)
    if st is None:
        return None
    par_rang, _de = _composition(g, st)
    affiche_de = {int(a["membre_id"]): a["id"] for a in lignes if a["membre_id"]}
    rangs = []
    for r in st["rangs"]:
        gens = par_rang.get(r["id"], [])
        montres = [{"affiche": jetons[affiche_de[mid]]} for mid in gens if affiche_de.get(mid) in jetons]
        rangs.append(dict(_sortie_publique(r), nom=_sans_emoji(r["nom"])[:NOM_MAX], phrase=_sans_emoji(r["phrase"])[:PHRASE_MAX],
                          n=len(gens), membres=montres))
    return {"rangs": rangs}


# ═══════════════════════════════════════════════════════════════════════════════
#  Les rôles Discord : ce qui se lie, ce que le bot peut donner
# ═══════════════════════════════════════════════════════════════════════════════

def _refus_general(role, liens_catalogue: set) -> str | None:
    """Pourquoi ce rôle ne se lie à AUCUN rang — None s'il le peut."""
    if getattr(role, "managed", False):
        return "Un rôle géré par une intégration (robot, boost…) ne se lie pas à un rang."
    dangereuses = [lib for attr, lib in securite_site.PERMISSIONS if getattr(getattr(role, "permissions", None), attr, False) is True]
    if dangereuses:
        return f"Ce rôle porte une permission dangereuse ({', '.join(dangereuses)}) : il ne se lie jamais à un rang."
    if getattr(role, "name", "") in ("🔒 Restricted", tableau._radie):
        return "Un rôle de sanction ne se lie pas à un rang."
    if role.id in liens_catalogue:
        return "Ce rôle est déjà celui d'un élément du catalogue (un métier…) : choisis-en un autre."
    return None


async def _refus_lien(g, st, rang, role) -> str | None:
    """Pourquoi ce rôle ne peut pas être celui de CE rang — None s'il le peut."""
    if role is None:
        return "Ce rôle n'existe plus sur le serveur."
    if role.id == g.id or getattr(role, "is_default", lambda: False)():
        return "Le rôle @everyone ne se lie pas à un rang."
    refus = _refus_general(role, await _liens_catalogue(g))
    if refus:
        return refus
    autre = next((r for r in st["rangs"] if r["role_id"] == role.id and r["id"] != rang["id"]), None)
    if autre is not None:
        return f"Ce rôle est déjà celui du rang « {autre['nom']} »."
    if not rang["verrou"]:
        if role.id == int(st.get("clan_role") or 0):
            return "Le rôle du clan ne peut pas être celui d'un rang : le retirer sortirait le membre du clan."
        if int(getattr(role, "position", 0) or 0) >= _haut_du_bot(g):
            return "Ce rôle est au-dessus du mien : je ne pourrais ni le donner ni le retirer."
    return None


def _refus_role_bot(g, role) -> str | None:
    """Pourquoi le bot ne peut pas donner ni retirer ce rôle — None s'il le peut."""
    if not affiches._peut_gerer_roles(g):
        return "Il me manque la permission « Gérer les rôles » sur Discord."
    if getattr(role, "managed", False):
        return f"Le rôle « {role.name} » est géré par une intégration : je ne peux pas le donner."
    if int(getattr(role, "position", 0) or 0) >= _haut_du_bot(g):
        return f"Le rôle « {role.name} » est au-dessus du mien : je ne peux ni le donner ni le retirer."
    return None


def _roles_a_changer(g, st, m, rang) -> tuple[list, list]:
    """(à donner, à retirer) pour que ce membre ait CE rang : le rôle du rang s'il est lié (un intermédiaire), et les
    AUTRES rôles de rang liés qu'il porte. Jamais un autre rôle ; jamais ceux du Capitaine, du Second ni du rang par
    défaut (seuls les intermédiaires se donnent)."""
    tient = {int(getattr(r, "id", 0) or 0) for r in getattr(m, "roles", None) or []}
    donner = []
    if not rang["verrou"]:
        role = _role_lie(g, rang)
        if role is not None and role.id not in tient:
            donner.append(role)
    retirer = []
    for r in st["intermediaires"]:
        role = _role_lie(g, r)
        if r["id"] != rang["id"] and role is not None and role.id in tient:
            retirer.append(role)
    return donner, retirer


async def _appliquer_roles(g, auteur, m, donner: list, retirer: list) -> str:
    """Les rôles posés sur Discord ; "" si tout est fait — sinon la raison, et ce qui avait été donné est repris."""
    if not donner and not retirer:
        return ""
    raison = f"Hiérarchie — site de la direction ({auteur})"[:400]
    donnes = []
    try:
        if donner:
            await m.add_roles(*donner, reason=raison)
            donnes = list(donner)
        if retirer:
            await m.remove_roles(*retirer, reason=raison)
    except discord.HTTPException as ex:
        _signaler("E4", "rôles de rang non appliqués : Discord a refusé", ex, detail=f"serveur={g.id} membre={m.id}")
        if donnes:
            try:
                await m.remove_roles(*donnes, reason=raison + " · annulé")
            except discord.HTTPException as ex2:
                _signaler("E5", "rôle de rang donné à moitié, non repris", ex2, detail=f"serveur={g.id} membre={m.id}")
                return "Discord a refusé à mi-chemin : un rôle de rang est peut-être resté, vérifie sur Discord."
        return "Discord a refusé de changer ses rôles (hiérarchie des rôles ou permission) : rien n'a changé."
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Les écritures de la tête (`tableau._executer` : tête seule, verrous, cadence, journal)
# ═══════════════════════════════════════════════════════════════════════════════

def _apres_ecriture(g) -> None:
    """La vitrine publique et les images de l'équipage renouvellent leurs réponses (comme une écriture de l'accueil)."""
    try:
        import site_equipage
        site_equipage._apres_ecriture(g)
    except Exception as ex:   # la vitrine attendra son délai (60 s) ; l'écriture, elle, est faite
        _signaler("E6", "vitrine non prévenue d'une écriture", ex)


async def _ecrire_rang(db, gid: int, st, mid: int, rang_id: str, t: int, par: int) -> None:
    """Le rang écrit d'un membre, sa version suivante (lue sous le verrou des écritures)."""
    version = int((st["explicites"].get(int(mid)) or {}).get("version", 0)) + 1
    await db.execute("INSERT OR REPLACE INTO hierarchie_membres (guild_id, membre_id, rang_id, version, maj_le, maj_par)"
                     " VALUES (?,?,?,?,?,?)", (gid, int(mid), rang_id, version, t, int(par)))


def _ident(v, champ: str) -> str:
    if not isinstance(v, str) or not FORMAT_RANG.fullmatch(v):
        raise affiches.Invalide(champ, "Identifiant de rang invalide.")
    return v


def _valider_rang(corps) -> dict:
    T = affiches._texte
    nom = _sans_emoji(T(corps.get("nom"), "nom", NOM_MAX, requis=True))
    if not nom:
        raise affiches.Invalide("nom", "Donne un nom au rang.")
    insigne = corps.get("insigne")
    if insigne not in INSIGNES:
        raise affiches.Invalide("insigne", "Choisis un insigne parmi ceux proposés.")
    couleur = corps.get("couleur")
    if not isinstance(couleur, str) or not FORMAT_COULEUR.fullmatch(couleur):
        raise affiches.Invalide("couleur", "Couleur attendue : #RRVVBB.")
    phrase = _sans_emoji(T(corps.get("phrase"), "phrase", PHRASE_MAX))
    return {"nom": nom, "insigne": insigne, "couleur": couleur.lower(), "phrase": phrase}


async def _rapprocher(db, g, st) -> int:
    """Les anciens grades encore « à relier » (correspondance automatique, sans rang) prennent un rang qui porte désormais
    leur nom (un rang ajouté ou renommé). Jamais une correspondance choisie par la tête."""
    n = 0
    for k, x in st["reprise"].items():
        if x["auto"] and not x["rang"]:
            r = _rang_du_nom(st, x["nom"])
            if r is not None:
                await db.execute("UPDATE hierarchie_reprise SET rang_id=?, version=version+1 WHERE guild_id=? AND cle=?",
                                 (r["id"], g.id, k))
                n += 1
    return n


async def _route_hierarchie(g, auteur, requete, corps):
    """`GET equipage/hierarchie` : la vue de la direction."""
    st = await assurer(g)
    if st is None:
        return 503, {"erreur": "La hiérarchie démarre : réessaie dans un instant."}
    return 200, await sortie_direction(g, st)


async def _route_rang(g, auteur, requete, corps):
    """`POST equipage/hierarchie/rang` `{id?, nom, insigne, couleur, phrase, version?}` : ajouter un rang (juste au-dessus
    du rang par défaut) ou modifier un rang (même verrouillé : son nom, son insigne, sa couleur, sa phrase). Un rôle
    Discord lié qui portait l'ancien nom (ou l'ancienne couleur) du rang le suit."""
    ident = corps.get("id")
    try:
        version = affiches._entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)
        v = _valider_rang(corps)
        if ident not in (None, ""):
            ident = _ident(ident, "id")
    except affiches.Invalide as ex:
        return 400, ex.corps()
    if await assurer(g) is None:
        return 503, {"erreur": "La hiérarchie démarre : réessaie dans un instant."}
    suivi = ""
    async with _verrou_ecriture():
        st = await _charger(g.id)
        deja = st["par_id"].get(ident) if ident else None
        if ident and deja is None:
            return 404, {"erreur": "Ce rang n'existe plus."}
        if deja is not None and version != deja["version"]:
            return 409, {"conflit": True, "erreur": "Ce rang a changé entre-temps.", "actuel": _sortie_rang(g, st, deja)}
        if deja is None and len(st["rangs"]) >= RANGS_MAX:
            return 400, {"erreur": f"{RANGS_MAX} rangs au plus : retire d'abord un rang."}
        if any(cle_grade(r["nom"]) == cle_grade(v["nom"]) and (deja is None or r["id"] != deja["id"]) for r in st["rangs"]):
            return 400, {"erreur": "Un autre rang porte déjà ce nom.", "champ": "nom"}
        t = int(time.time())
        async with _get_db() as db:
            if deja is None:
                ident = secrets.token_urlsafe(6)
                defaut = st["par_verrou"].get(DEFAUT)
                await db.execute("INSERT INTO hierarchie_rangs (guild_id, id, nom, insigne, couleur, phrase, ordre, verrou,"
                                 " role_id, version, cree_le, maj_le, maj_par) VALUES (?,?,?,?,?,?,?,'',0,1,?,?,?)",
                                 (g.id, ident, v["nom"], v["insigne"], v["couleur"], v["phrase"],
                                  int(defaut["ordre"]) if defaut else 10 ** 6, t, t, auteur.id))
            else:
                await db.execute("UPDATE hierarchie_rangs SET nom=?, insigne=?, couleur=?, phrase=?, version=version+1,"
                                 " maj_le=?, maj_par=? WHERE guild_id=? AND id=?",
                                 (v["nom"], v["insigne"], v["couleur"], v["phrase"], t, auteur.id, g.id, ident))
            await _renumeroter(db, g.id)
            await db.commit()
        st = await _charger(g.id)
        async with _get_db() as db:
            if await _rapprocher(db, g, st):
                await db.commit()
        st = await _charger(g.id)
        if deja is not None:
            suivi = await _role_suit_le_rang(g, auteur, deja, st["par_id"][ident])
    _apres_ecriture(g)
    if deja is None:
        journal = f"Hiérarchie : rang « {v['nom']} » ajouté"
    elif deja["nom"] != v["nom"]:
        journal = f"Hiérarchie : rang « {deja['nom']} » renommé « {v['nom']} »"
    else:
        journal = f"Hiérarchie : rang « {v['nom']} » modifié"
    return 200, {"ok": True, "id": ident, "message": suivi, **(await sortie_direction(g, _etats[g.id])),
                 "_journal": journal + (f" ({suivi})" if suivi else "")}


async def _role_suit_le_rang(g, auteur, avant: dict, apres: dict) -> str:
    """Un rôle lié qui portait le nom (ou la couleur) du rang le suit quand le rang change — seulement un rôle que le bot
    peut modifier. "" si rien à faire ; sinon ce qui a été fait (ou pourquoi pas), pour la page et le journal."""
    role = _role_lie(g, apres)
    if role is None or (avant["nom"] == apres["nom"] and avant["couleur"] == apres["couleur"]):
        return ""
    changer = {}
    if avant["nom"] != apres["nom"] and role.name == avant["nom"]:
        changer["name"] = apres["nom"]
    if avant["couleur"] != apres["couleur"] and affiches._couleur_role(role) == avant["couleur"].lower():
        changer["colour"] = discord.Colour(int(apres["couleur"][1:], 16))
    if not changer:
        return ""
    if _refus_role_bot(g, role):
        return "le rôle Discord garde son nom : je ne peux pas le modifier"
    try:
        await role.edit(reason=f"Hiérarchie — rang renommé sur le site ({auteur})"[:400], **changer)
    except discord.HTTPException as ex:
        _signaler("E7", "rôle de rang non renommé : Discord a refusé", ex, detail=f"serveur={g.id} role={role.id}")
        return "le rôle Discord garde son nom : Discord a refusé"
    return "le rôle Discord suit"


async def _route_rang_supprimer(g, auteur, requete, corps):
    """`POST equipage/hierarchie/rang/supprimer` `{id}` : un rang intermédiaire part ; ses membres reviennent au rang par
    défaut (le rôle Discord lié reste sur Discord, il n'est plus celui d'un rang)."""
    try:
        ident = _ident(corps.get("id"), "id")
    except affiches.Invalide as ex:
        return 400, ex.corps()
    if await assurer(g) is None:
        return 503, {"erreur": "La hiérarchie démarre : réessaie dans un instant."}
    async with _verrou_ecriture():
        st = await _charger(g.id)
        r = st["par_id"].get(ident)
        if r is None:
            return 200, {"ok": True, **(await sortie_direction(g, st)), "_journal": None}
        if r["verrou"]:
            return 400, {"erreur": "Ce rang est verrouillé : il ne se retire pas.", "champ": "id"}
        par_rang, _de = _composition(g, st)
        n = len(par_rang.get(ident, []))
        async with _get_db() as db:
            await db.execute("DELETE FROM hierarchie_membres WHERE guild_id=? AND rang_id=?", (g.id, ident))
            await db.execute("UPDATE hierarchie_reprise SET rang_id='', version=version+1 WHERE guild_id=? AND rang_id=?",
                             (g.id, ident))
            await db.execute("DELETE FROM hierarchie_rangs WHERE guild_id=? AND id=?", (g.id, ident))
            await _renumeroter(db, g.id)
            await db.commit()
        st = await _charger(g.id)
    _apres_ecriture(g)
    defaut = st["par_verrou"].get(DEFAUT, {"nom": "par défaut"})
    return 200, {"ok": True, **(await sortie_direction(g, st)),
                 "_journal": f"Hiérarchie : rang « {r['nom']} » retiré ({n} membre{'s' if n > 1 else ''} au rang "
                             f"« {defaut['nom']} »)"}


async def _route_rang_deplacer(g, auteur, requete, corps):
    """`POST equipage/hierarchie/rang/deplacer` `{id, sens: "haut" | "bas"}` : un intermédiaire échange sa place avec son
    voisin (les rangs verrouillés ne bougent jamais)."""
    sens = corps.get("sens")
    try:
        ident = _ident(corps.get("id"), "id")
    except affiches.Invalide as ex:
        return 400, ex.corps()
    if sens not in ("haut", "bas"):
        return 400, {"erreur": "Sens : « haut » ou « bas ».", "champ": "sens"}
    if await assurer(g) is None:
        return 503, {"erreur": "La hiérarchie démarre : réessaie dans un instant."}
    async with _verrou_ecriture():
        st = await _charger(g.id)
        l = list(st["intermediaires"])
        i = next((k for k, r in enumerate(l) if r["id"] == ident), None)
        if i is None:
            if ident in st["par_id"]:
                return 400, {"erreur": "Ce rang est verrouillé : il garde sa place.", "champ": "id"}
            return 404, {"erreur": "Ce rang n'existe plus."}
        j = i - 1 if sens == "haut" else i + 1
        bouge = 0 <= j < len(l)
        if bouge:
            l[i], l[j] = l[j], l[i]
            base = int(st["par_verrou"][SECOND]["ordre"]) if SECOND in st["par_verrou"] else 0
            async with _get_db() as db:
                for n, r in enumerate(l, start=1):
                    await db.execute("UPDATE hierarchie_rangs SET ordre=? WHERE guild_id=? AND id=?", (base + n, g.id, r["id"]))
                await _renumeroter(db, g.id)
                await db.commit()
            st = await _charger(g.id)
    if bouge:
        _apres_ecriture(g)
    r = st["par_id"][ident]
    return 200, {"ok": True, **(await sortie_direction(g, st)),
                 "_journal": f"Hiérarchie : rang « {r['nom']} » déplacé vers le {sens}" if bouge else None}


async def _route_rang_role(g, auteur, requete, corps):
    """`POST equipage/hierarchie/rang/role` : `{id, role_id}` lier un rôle existant ; `{id, creer: true}` le créer (sans
    aucune permission, au nom et à la couleur du rang) ; `{id, retirer: true}` délier (le rôle reste sur Discord). Lié à
    un intermédiaire, le rôle est donné tout de suite à ceux qui ont ce rang ; qui le porte déjà sur Discord prend ce rang."""
    try:
        ident = _ident(corps.get("id"), "id")
        creer = affiches._booleen(corps.get("creer"), "creer", False)
        retirer = affiches._booleen(corps.get("retirer"), "retirer", False)
        role_id = 0 if (creer or retirer) else affiches._identifiant(corps.get("role_id"), "role_id")
    except affiches.Invalide as ex:
        return 400, ex.corps()
    if await assurer(g) is None:
        return 503, {"erreur": "La hiérarchie démarre : réessaie dans un instant."}
    async with _verrou_ecriture():
        st = await _charger(g.id)
        r = st["par_id"].get(ident)
        if r is None:
            return 404, {"erreur": "Ce rang n'existe plus."}
        t = int(time.time())
        if retirer:
            ancien = _role_lie(g, r)
            if not r["role_id"]:
                return 200, {"ok": True, **(await sortie_direction(g, st)), "_journal": None}
            #  Ceux qui avaient ce rang par leur rôle le gardent : leur rang est désormais écrit sur le site.
            par_rang, de = _composition(g, st)
            gardes = [mid for mid in par_rang.get(ident, []) if de[mid][1] == "role"]
            async with _get_db() as db:
                for mid in gardes:
                    await _ecrire_rang(db, g.id, st, mid, ident, t, auteur.id)
                await db.execute("UPDATE hierarchie_rangs SET role_id=0, version=version+1, maj_le=?, maj_par=? WHERE guild_id=?"
                                 " AND id=?", (t, auteur.id, g.id, ident))
                await db.commit()
            st = await _charger(g.id)
            _apres_ecriture(g)
            nom_role = f"« {ancien.name} »" if ancien is not None else "supprimé"
            return 200, {"ok": True, **(await sortie_direction(g, st)),
                         "_journal": f"Hiérarchie : rôle Discord {nom_role} délié du rang « {r['nom']} » (il reste sur Discord)"}
        if creer:
            if _role_lie(g, r) is not None:
                return 400, {"erreur": "Ce rang a déjà son rôle Discord : délie-le d'abord.", "champ": "role_id"}
            if not affiches._peut_gerer_roles(g):
                return 403, {"erreur": "Il me manque la permission « Gérer les rôles » sur Discord."}
            try:
                role = await g.create_role(name=r["nom"][:100], colour=discord.Colour(int(r["couleur"][1:], 16)),
                                           permissions=discord.Permissions.none(), hoist=False, mentionable=False,
                                           reason=f"Rang « {r['nom']} » — site de la direction ({auteur})"[:400])
            except discord.HTTPException as ex:
                _signaler("E3", "rôle de rang non créé : Discord a refusé", ex, detail=f"serveur={g.id} rang={ident}")
                return 502, {"erreur": "Discord a refusé de créer le rôle."}
        else:
            role = g.get_role(role_id)
            refus = await _refus_lien(g, st, r, role)
            if refus is None and not r["verrou"]:
                #  Un intermédiaire se donne par son rôle : le bot doit pouvoir le donner et le retirer.
                refus = _refus_role_bot(g, role)
            if refus:
                return 400, {"erreur": refus, "champ": "role_id"}
        #  Ceux qui ont ce rang AVANT le lien (attribué, repris) reçoivent le rôle : le rang ne leur échappe pas.
        par_rang, _de = _composition(g, st)
        a_donner = [g.get_member(mid) for mid in par_rang.get(ident, []) if not r["verrou"]]
        a_donner = [m for m in a_donner if m is not None and role not in (getattr(m, "roles", None) or [])]
        if a_donner:
            refus = await tableau.limite_grave(g, auteur, "roles", len(a_donner))
            if refus:
                return 403, {"erreur": refus}
        async with _get_db() as db:
            await db.execute("UPDATE hierarchie_rangs SET role_id=?, version=version+1, maj_le=?, maj_par=? WHERE guild_id=?"
                             " AND id=?", (role.id, t, auteur.id, g.id, ident))
            await db.commit()
        st = await _charger(g.id)
        manques = []
        for m in a_donner:
            if await _appliquer_roles(g, auteur, m, [role], []):
                manques.append(_sans_emoji(m.display_name))
    _apres_ecriture(g)
    morceaux = []
    if a_donner:
        morceaux.append(f"donné à {len(a_donner) - len(manques)}")
    if manques:
        morceaux.append(f"refusé pour {', '.join(manques[:5])}{'…' if len(manques) > 5 else ''}")
    message = ("Rôle créé et lié." if creer else "Rôle lié.") + (" Discord a refusé pour " + ", ".join(manques[:5]) + "."
                                                                  if manques else "")
    return 200, {"ok": True, "message": message, "manques": manques, **(await sortie_direction(g, st)),
                 "_journal": f"Hiérarchie : rôle Discord « {role.name} »{' créé et' if creer else ''} lié au rang "
                             f"« {r['nom']} »" + (f" ({', '.join(morceaux)})" if morceaux else "")}


def _lire_affectations(corps) -> list:
    """[(membre, rang, version)] : `{membre, rang, version}` ou `{affectations: [{membre, rang, version}, …]}`."""
    brut = corps.get("affectations")
    if brut is None:
        brut = [corps]
    if not isinstance(brut, list) or not 1 <= len(brut) <= AFFECTATIONS_MAX:
        raise affiches.Invalide("affectations", f"De 1 à {AFFECTATIONS_MAX} membres d'un coup.")
    out, vus = [], set()
    for x in brut:
        if not isinstance(x, dict):
            raise affiches.Invalide("affectations", "Affectation invalide.")
        mid = affiches._identifiant(x.get("membre"), "membre")
        if mid in vus:
            raise affiches.Invalide("membre", "Un membre deux fois dans la même demande.")
        vus.add(mid)
        rid = x.get("rang")
        if not isinstance(rid, str) or not FORMAT_RANG.fullmatch(rid):
            raise affiches.Invalide("rang", "Rang invalide.")
        out.append((mid, rid, affiches._entier(x.get("version"), "version", 0, 10 ** 9, defaut=0)))
    return out


async def _route_attribuer(g, auteur, requete, corps):
    """`POST equipage/hierarchie/attribuer` : nommer un ou plusieurs membres du clan à un rang (25 au plus). Tout est
    vérifié avant de rien toucher — le clan, le rang (jamais Capitaine ni Second), la version, les rôles Discord que le bot
    doit donner ou retirer ; puis chaque membre : ses rôles (défaits si Discord refuse à mi-chemin), son rang écrit."""
    try:
        demandes = _lire_affectations(corps)
    except affiches.Invalide as ex:
        return 400, ex.corps()
    if await assurer(g) is None:
        return 503, {"erreur": "La hiérarchie démarre : réessaie dans un instant."}
    capitaines, seconds = _tete()
    async with _verrou_ecriture():
        st = await _charger(g.id)
        plan = []
        for mid, rid, version in demandes:
            m = g.get_member(mid)
            nom = _sans_emoji(getattr(m, "display_name", "")) or "Ce membre"
            if mid in capitaines or mid in seconds:
                return 400, {"erreur": f"{nom} suit la direction du site (Capitaine ou Second) : son rang ne s'attribue pas.",
                             "champ": "membre"}
            if not _au_clan(m, st):
                return 400, {"erreur": f"{nom} n'est pas dans le clan : seul un membre du clan reçoit un rang.",
                             "champ": "membre"}
            r = st["par_id"].get(rid)
            if r is None:
                return 404, {"erreur": "Ce rang n'existe plus.", "champ": "rang"}
            if r["verrou"] in (CAPITAINE, SECOND):
                return 400, {"erreur": f"« {r['nom']} » suit la direction du site : il ne s'attribue pas.", "champ": "rang"}
            actuelle = int((st["explicites"].get(mid) or {}).get("version", 0))
            if version != actuelle:
                avant, source = _rang_et_source(g, st, mid)
                return 409, {"conflit": True, "erreur": f"Le rang de {nom} a changé entre-temps.",
                             "actuel": {"membre": str(mid), "rang": avant["id"] if avant else "", "source": source,
                                        "version": actuelle}}
            donner, retirer = _roles_a_changer(g, st, m, r)
            plan.append((m, r, donner, retirer))
        for m, r, donner, retirer in plan:
            for role in donner + retirer:
                refus = _refus_role_bot(g, role)
                if refus:
                    return 403, {"erreur": refus, "champ": "rang"}
        bougent = sum(1 for _m, _r, d, x in plan if d or x)
        if bougent:
            refus = await tableau.limite_grave(g, auteur, "roles", bougent)
            if refus:
                return 403, {"erreur": refus}
        faits, refus = [], []
        t = int(time.time())
        for m, r, donner, retirer in plan:
            raison = await _appliquer_roles(g, auteur, m, donner, retirer)
            if raison:
                refus.append({"membre": str(m.id), "nom": _sans_emoji(m.display_name), "raison": raison})
                continue
            faits.append((m, r, donner, retirer))
        if faits:
            async with _get_db() as db:
                for m, r, _d, _x in faits:
                    await _ecrire_rang(db, g.id, st, m.id, r["id"], t, auteur.id)
                await db.commit()
        st = await _charger(g.id)
    if not faits:
        return 502, {"erreur": refus[0]["raison"] if refus else "Rien n'a changé.", "refus": refus}
    _apres_ecriture(g)
    rangs = {r["id"]: r for _m, r, _d, _x in faits}
    roles = [f"+{x.name}" for _m, _r, d, _x in faits for x in d] + [f"−{x.name}" for _m, _r, _d, xs in faits for x in xs]
    if len(faits) == 1:
        m, r, _d, _x = faits[0]
        texte = f"Hiérarchie : {_sans_emoji(m.display_name)} nommé {r['nom']}"
    elif len(rangs) == 1:
        texte = (f"Hiérarchie : {len(faits)} membres nommés {next(iter(rangs.values()))['nom']} ("
                 + ", ".join(_sans_emoji(m.display_name) for m, *_r in faits[:6]) + ("…" if len(faits) > 6 else "") + ")")
    else:
        texte = f"Hiérarchie : {len(faits)} membres changent de rang"
    journal = {"texte": texte + (f" · rôles {' '.join(roles[:8])}" if roles else ""),
               "membre_id": faits[0][0].id if len(faits) == 1 else 0,
               "detail": " ; ".join(f"{m.id}→{r['id']}" for m, r, _d, _x in faits)[:600]}
    return 200, {"ok": True, "faits": [str(m.id) for m, *_r in faits], "refus": refus,
                 **(await sortie_direction(g, st)), "_journal": journal}


async def _route_reprise(g, auteur, requete, corps):
    """`POST equipage/hierarchie/reprise` : `{cle, rang, version}` relier un ancien grade à un rang ("" : le rang par
    défaut) ; `{cle, creer: true}` créer le rang qui porte ce nom et l'y relier. Le grade écrit des affiches ne change pas."""
    cle = corps.get("cle")
    try:
        if not isinstance(cle, str) or not FORMAT_CLE_GRADE.fullmatch(cle):
            raise affiches.Invalide("cle", "Grade invalide.")
        creer = affiches._booleen(corps.get("creer"), "creer", False)
        version = affiches._entier(corps.get("version"), "version", 0, 10 ** 9, defaut=0)
        rid = "" if creer else corps.get("rang")
        if not creer and rid not in ("", None) and (not isinstance(rid, str) or not FORMAT_RANG.fullmatch(rid)):
            raise affiches.Invalide("rang", "Rang invalide.")
        rid = rid or ""
    except affiches.Invalide as ex:
        return 400, ex.corps()
    if await assurer(g) is None:
        return 503, {"erreur": "La hiérarchie démarre : réessaie dans un instant."}
    cree = None
    async with _verrou_ecriture():
        st = await _charger(g.id)
        x = st["reprise"].get(cle)
        if x is None:
            return 404, {"erreur": "Cet ancien grade n'existe plus."}
        if not creer and version != x["version"]:
            return 409, {"conflit": True, "erreur": "Cette correspondance a changé entre-temps.",
                         "actuelle": {"cle": cle, "rang": x["rang"], "version": x["version"]}}
        t = int(time.time())
        async with _get_db() as db:
            if creer:
                cible = _rang_du_nom(st, x["nom"])
                if cible is None:
                    if any(cle_grade(r["nom"]) == cle and r["verrou"] in (CAPITAINE, SECOND) for r in st["rangs"]):
                        return 400, {"erreur": "Ce nom est celui d'un rang verrouillé : relie ce grade à un autre rang.",
                                     "champ": "cle"}
                    if len(st["rangs"]) >= RANGS_MAX:
                        return 400, {"erreur": f"{RANGS_MAX} rangs au plus : retire d'abord un rang."}
                    rid = secrets.token_urlsafe(6)
                    defaut = st["par_verrou"].get(DEFAUT)
                    nom = _sans_emoji(x["nom"])[:NOM_MAX] or "Nouveau rang"
                    await db.execute("INSERT INTO hierarchie_rangs (guild_id, id, nom, insigne, couleur, phrase, ordre, verrou,"
                                     " role_id, version, cree_le, maj_le, maj_par) VALUES (?,?,?,?,?,'',?,'',0,1,?,?,?)",
                                     (g.id, rid, nom, "etoile", "#7a5a22", int(defaut["ordre"]) if defaut else 10 ** 6, t, t,
                                      auteur.id))
                    await _renumeroter(db, g.id)
                    cree = nom
                else:
                    rid = cible["id"]
            else:
                r = st["par_id"].get(rid) if rid else None
                if rid and r is None:
                    return 404, {"erreur": "Ce rang n'existe plus.", "champ": "rang"}
                if r is not None and r["verrou"] in (CAPITAINE, SECOND):
                    return 400, {"erreur": f"« {r['nom']} » suit la direction du site : aucun ancien grade n'y mène.",
                                 "champ": "rang"}
            await db.execute("UPDATE hierarchie_reprise SET rang_id=?, auto=0, version=version+1, maj_le=?, maj_par=?"
                             " WHERE guild_id=? AND cle=?", (rid, t, auteur.id, g.id, cle))
            await db.commit()
        st = await _charger(g.id)
    _apres_ecriture(g)
    cible = st["par_id"].get(rid) or st["par_verrou"].get(DEFAUT) or {"nom": "le rang par défaut"}
    return 200, {"ok": True, **(await sortie_direction(g, st)),
                 "_journal": f"Hiérarchie : l'ancien grade « {x['nom']} » relié au rang « {cible['nom']} »"
                             + (" (rang créé)" if cree else "")}


def _cle_verrou(genre: str):
    """La clé que touche une écriture (`rang:<id>`) : la présence en direct refuse (423) d'écrire un rang que quelqu'un
    d'autre est en train de modifier. Un ajout (sans identifiant) ne touche rien d'existant."""
    def objet(corps):
        ident = corps.get("id") if isinstance(corps, dict) else None
        return f"{genre}:{ident}" if isinstance(ident, str) and FORMAT_RANG.fullmatch(ident) else None
    objet.__name__ = f"_cle_verrou_{genre}"
    return objet


def _verrou_membres(corps):
    """Les membres que touche une attribution (`rang-membre:<id>`) : leur rang ne s'écrit pas pendant que quelqu'un
    d'autre le change."""
    if not isinstance(corps, dict):
        return []
    brut = corps.get("affectations") if isinstance(corps.get("affectations"), list) else [corps]
    out = []
    for x in brut[:AFFECTATIONS_MAX]:
        mid = x.get("membre") if isinstance(x, dict) else None
        if isinstance(mid, (str, int)) and not isinstance(mid, bool) and tableau.chiffres(mid):
            out.append(f"rang-membre:{int(mid)}")
    return out


ROUTES_SITE = {
    "equipage/hierarchie": {"methode": "GET", "fn": _route_hierarchie},
    "equipage/hierarchie/rang": {"methode": "POST", "fn": _route_rang, "ecriture": True, "corps_max": 4096,
                                 "verrou": _cle_verrou("rang")},
    "equipage/hierarchie/rang/supprimer": {"methode": "POST", "fn": _route_rang_supprimer, "ecriture": True,
                                           "corps_max": 1024, "verrou": _cle_verrou("rang")},
    "equipage/hierarchie/rang/deplacer": {"methode": "POST", "fn": _route_rang_deplacer, "ecriture": True,
                                          "corps_max": 1024, "verrou": _cle_verrou("rang")},
    #  Un rôle lié change Discord tout de suite : jamais rejoué hors ligne, compté dans les actions graves « roles ».
    "equipage/hierarchie/rang/role": {"methode": "POST", "fn": _route_rang_role, "ecriture": True, "corps_max": 1024,
                                      "grave": "roles", "verrou": _cle_verrou("rang")},
    "equipage/hierarchie/attribuer": {"methode": "POST", "fn": _route_attribuer, "ecriture": True, "corps_max": 8192,
                                      "verrou": _verrou_membres},
    "equipage/hierarchie/reprise": {"methode": "POST", "fn": _route_reprise, "ecriture": True, "corps_max": 1024,
                                    "verrou": lambda corps: "hierarchie:reprise"},
}

__all__ = ["setup", "init_db", "assurer", "pret", "connu", "rang_de", "rang_affiche", "grade_affiche", "ordre_de",
           "vue_equipage", "vue_publique", "sortie_direction", "cle_grade", "nom_du_grade", "ROUTES_SITE", "INSIGNES",
           "COULEURS", "DEPART"]
