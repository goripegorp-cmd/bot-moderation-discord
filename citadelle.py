"""La Cité — socle central de customisation, construction & économie long terme.

Phase 259 (socle) : module autonome, branché au boot via setup(get_db, v2_helpers,
add_coins_fn). Tout en BOUTONS (zéro commande), un seul point d'entrée depuis le
hub existant. Les boutons du menu portent un custom_id `cite:<section>` capté par
UN SEUL DynamicItem persistant (CitadelleButton) → survit aux reboots, défère en
tête → JAMAIS d'« Échec de l'interaction ».

Design :
- Monnaie cosmétique « Éclats de Création » (séparée des pièces → n'impacte pas
  l'équilibre du jeu ; sert à la customisation infinie qui est 100 % cosmétique).
- Matériaux de construction (table normalisée, upsert atomique).
- Cosmétiques possédés + équipés (tables normalisées).
Les fonctions économiques sont ATOMIQUES (UPDATE … WHERE … + rowcount), comme
add_coins/add_bank de bot.py — le pool DB n'a pas de row-lock.

Les phases suivantes (B→K) remplissent chaque salle ; ici chaque salle non encore
ouverte affiche un teaser clair et encourageant (le menu explique tout dès J1).
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import discord
from discord.ui import Button

# ─── Dépendances injectées au boot (setup) ─────────────────────────────────────
_get_db = None          # async context manager : async with _get_db() as db
_add_coins = None        # callback optionnel (non utilisé au socle)
_v2 = {}                 # helpers Components V2 (title/subtitle/body/divider/container/LayoutView)
_pet_rente_bonus_fn = None  # Phase 268 : async (gid, uid) -> (bonus:int, label:str|None)
_is_frozen_fn = None     # TASK A5 : async (gid, uid) -> bool ; True si compte gelé (compromis)

ECLATS_EMOJI = "✨"
ECLATS_NAME = "Éclats de Création"


def setup(get_db_fn, v2_helpers: dict | None = None, add_coins_fn=None,
          pet_rente_bonus_fn=None, is_frozen_fn=None):
    """Injecte les dépendances. Appelé une fois dans on_ready (bot.py).

    Phase 268 : pet_rente_bonus_fn (optionnel) = async (gid, uid) -> (bonus, label)
    qui renvoie le petit bonus de rente (Éclats) du familier équipé. Décorrèle
    La Cité du système de familiers (vit dans bot.py/engagement41). Fail-safe :
    absent ou en erreur → bonus 0 (la rente fonctionne normalement).

    TASK A5 : is_frozen_fn (optionnel) = async (gid, uid) -> bool. True si le compte
    est gelé (compromis) → on REFUSE les dépenses d'Éclats. Fail-open : absent ou
    en erreur → considéré non gelé (ne bloque pas un membre légitime)."""
    global _get_db, _v2, _add_coins, _pet_rente_bonus_fn, _is_frozen_fn
    _get_db = get_db_fn
    _v2 = dict(v2_helpers or {})
    _add_coins = add_coins_fn
    _pet_rente_bonus_fn = pet_rente_bonus_fn
    _is_frozen_fn = is_frozen_fn


async def _pet_rente_extra(gid: int, uid: int) -> tuple:
    """Renvoie (bonus:int, label:str|None) du familier équipé. Tout fail-safe."""
    if _pet_rente_bonus_fn is None:
        return (0, None)
    try:
        res = await _pet_rente_bonus_fn(int(gid), int(uid))
        if not res:
            return (0, None)
        bonus, label = res
        return (max(0, int(bonus or 0)), label)
    except Exception as ex:
        print(f"[citadelle _pet_rente_extra] {ex}")
        return (0, None)


# ═══════════════════════════════════════════════════════════════════════════════
#  Catalogue des salles de la Cité (titre + teaser, sert au menu ET aux stubs)
#  status : 'soon' (en construction) | 'live' (ouverte). On bascule à 'live' en
#  remplaçant le routage dans la phase correspondante.
# ═══════════════════════════════════════════════════════════════════════════════
SECTIONS = {
    # key            (emoji, label,                phase, teaser)
    "forge":        ("🎨", "Forge d'Apparence",   "B", "Teins et skinne ton équipement **sans toucher aux stats** — customisation infinie, 100 % cosmétique."),
    "carte":        ("🪪", "Carte de Joueur",      "C", "Compose ta carte : fond, cadre, titre, familier vedette, devise. Ton identité, visible par tous."),
    "emblemes":     ("🛡️", "Atelier d'Emblèmes",  "D", "Crée un emblème unique (formes + couleurs + symboles). Version blason pour ton alliance."),
    "sanctuaire":   ("🏯", "Sanctuaire Personnel", "F", "Bâtis ton espace à partir de modules gagnés : salles, vitrines, trophées, déco. Visitable par les autres."),
    "jardin":       ("🌿", "Jardin & Élevage",     "I", "Fais pousser et élever en temps réel — produit des ressources si tu reviens régulièrement."),
    "domaine":      ("🏰", "Domaine d'Alliance",   "I", "Améliorez un QG partagé avec vos contributions : paliers, petits bonus d'alliance et déco collective."),
    "passe":        ("🎟️", "Passe de Saison",      "E", "Events + activité → paliers → cosmétiques, familiers et titres **exclusifs**. Remis à zéro chaque saison."),
    "collections":  ("📜", "Collections & Reliques", "H", "Complète des sets d'objets via les events → titre ou cosmétique **permanent**. Chasse longue durée."),
    "maitrises":    ("🏆", "Maîtrises",            "K", "Pistes de maîtrise par arme et par activité, courbes très longues, jalons cosmétiques. Toujours un objectif."),
    "metiers":      ("⚒️", "Métiers & Récolte",    "G", "Professions (mineur, herboriste, forgeron, enchanteur…) à niveaux indépendants. Un vrai chemin sans combat."),
    "revenus":      ("💰", "Revenus Passifs",      "J", "Ton sanctuaire, ta banque et tes investissements génèrent un revenu lent. Être fidèle paie."),
    "marche":       ("🛒", "Marché du Vendeur",    "J", "Vendeur aux prix qui fluctuent + rachats rares. Un puits à pièces propre (jamais d'échange entre joueurs)."),
    "pantheon":     ("🏛️", "Panthéon",             "K", "L'archive permanente des meilleurs de chaque saison. Grave ta légende sur le serveur."),
    "rivalites":    ("⚔️", "Rivalités & Mises",    "K", "Défis 100 % volontaires (joueur ou alliance) avec une cagnotte en pièces misées. Le perdant cède la mise."),
}

# Regroupement par catégorie pour l'affichage du menu (ordre des rangées).
_MENU_GROUPS = [
    ("🎨 **Customisation** — personnalise sans aucune limite", ["forge", "carte", "emblemes"]),
    ("🏗️ **Construction** — bâtis ton propre espace", ["sanctuaire", "jardin", "domaine"]),
    ("📈 **Progression** — des objectifs qui ne s'épuisent jamais", ["passe", "collections", "maitrises"]),
    ("💰 **Économie** — gagne vraiment, sur le long terme", ["metiers", "revenus", "marche"]),
    ("🏅 **Statut** — ta légende sur le serveur", ["pantheon", "rivalites"]),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  DB
# ═══════════════════════════════════════════════════════════════════════════════
async def init_db():
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            # Monnaie cosmétique
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_wallet ("
                "guild_id INTEGER, user_id INTEGER, "
                "eclats INTEGER DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id))"
            )
            # Matériaux de construction (1 ligne par type → upsert atomique)
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_materials ("
                "guild_id INTEGER, user_id INTEGER, mat_key TEXT, "
                "qty INTEGER DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id, mat_key))"
            )
            # Cosmétiques possédés (1 ligne par item)
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_cosmetics ("
                "guild_id INTEGER, user_id INTEGER, kind TEXT, item_key TEXT, "
                "obtained_at TEXT, "
                "PRIMARY KEY (guild_id, user_id, kind, item_key))"
            )
            # Cosmétiques équipés (1 ligne par slot)
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_active ("
                "guild_id INTEGER, user_id INTEGER, slot TEXT, item_key TEXT, "
                "PRIMARY KEY (guild_id, user_id, slot))"
            )
            # Phase E : Passe de Saison (track cosmétique gratuit, reset mensuel)
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_passe ("
                "guild_id INTEGER, user_id INTEGER, season TEXT, "
                "points INTEGER DEFAULT 0, claimed TEXT DEFAULT '', "
                "PRIMARY KEY (guild_id, user_id, season))"
            )
            # Phase G : Métiers (professions non-combat à niveaux indépendants)
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_professions ("
                "guild_id INTEGER, user_id INTEGER, prof TEXT, "
                "xp INTEGER DEFAULT 0, last_work REAL DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id, prof))"
            )
            # Phase I : Jardin (récolte idle quotidienne) + Domaine collectif du serveur
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_garden ("
                "guild_id INTEGER, user_id INTEGER, last REAL DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id))"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_domaine ("
                "guild_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0)"
            )
            # Phase J : rente quotidienne (revenu passif) · Phase K : maîtrise (cumul à vie)
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_rente ("
                "guild_id INTEGER, user_id INTEGER, last REAL DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id))"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS citadelle_mastery ("
                "guild_id INTEGER, user_id INTEGER, points INTEGER DEFAULT 0, "
                "PRIMARY KEY (guild_id, user_id))"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_cite_cosmo "
                "ON citadelle_cosmetics(guild_id, user_id, kind)"
            )
            await db.commit()
    except Exception as ex:
        print(f"[citadelle init_db] {ex}")


# ─── Éclats de Création (monnaie cosmétique, atomique) ─────────────────────────
async def get_eclats(guild_id: int, user_id: int) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT eclats FROM citadelle_wallet WHERE guild_id=? AND user_id=?",
                (int(guild_id), int(user_id)),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


async def grant_eclats(guild_id: int, user_id: int, amount: int) -> int:
    """Ajoute (ou retire) des Éclats de façon ATOMIQUE, borné à >= 0. Renvoie le solde."""
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO citadelle_wallet (guild_id, user_id, eclats) VALUES (?,?,0)",
                (int(guild_id), int(user_id)),
            )
            await db.execute(
                "UPDATE citadelle_wallet SET eclats = MAX(0, eclats + ?) "
                "WHERE guild_id=? AND user_id=?",
                (int(amount), int(guild_id), int(user_id)),
            )
            await db.commit()
            async with db.execute(
                "SELECT eclats FROM citadelle_wallet WHERE guild_id=? AND user_id=?",
                (int(guild_id), int(user_id)),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as ex:
        print(f"[citadelle grant_eclats] {ex}")
        return 0


async def spend_eclats(guild_id: int, user_id: int, amount: int) -> bool:
    """Débit ATOMIQUE conditionnel (FAIL-CLOSED) : True seulement si le solde suffisait.

    TASK A5 : si le compte est GELÉ (compromis), on REFUSE la dépense d'Éclats
    (anti-drain de la 2e monnaie). Fail-open sur erreur du check (ne bloque pas un
    membre légitime sur un hoquet)."""
    if _get_db is None or amount <= 0:
        return False
    if _is_frozen_fn is not None:
        try:
            if await _is_frozen_fn(int(guild_id), int(user_id)):
                print(f"[spend_eclats] DÉPENSE REFUSÉE (compte gelé) "
                      f"guild={guild_id} user={user_id} amount={amount}")
                return False
        except Exception:
            pass  # fail-open
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE citadelle_wallet SET eclats = eclats - ? "
                "WHERE guild_id=? AND user_id=? AND eclats >= ?",
                (int(amount), int(guild_id), int(user_id), int(amount)),
            )
            await db.commit()
            return getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[citadelle spend_eclats] {ex}")
        return False


# ─── Matériaux de construction (upsert atomique) ───────────────────────────────
async def grant_material(guild_id: int, user_id: int, mat_key: str, qty: int = 1) -> None:
    if _get_db is None or qty == 0:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO citadelle_materials (guild_id, user_id, mat_key, qty) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT(guild_id, user_id, mat_key) DO UPDATE SET "
                "qty = MAX(0, qty + ?)",
                (int(guild_id), int(user_id), str(mat_key), int(qty), int(qty)),
            )
            await db.commit()
    except Exception as ex:
        print(f"[citadelle grant_material] {ex}")


async def spend_material(guild_id: int, user_id: int, mat_key: str, qty: int) -> bool:
    if _get_db is None or qty <= 0:
        return False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE citadelle_materials SET qty = qty - ? "
                "WHERE guild_id=? AND user_id=? AND mat_key=? AND qty >= ?",
                (int(qty), int(guild_id), int(user_id), str(mat_key), int(qty)),
            )
            await db.commit()
            return getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[citadelle spend_material] {ex}")
        return False


async def get_materials(guild_id: int, user_id: int) -> dict:
    if _get_db is None:
        return {}
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT mat_key, qty FROM citadelle_materials "
                "WHERE guild_id=? AND user_id=? AND qty > 0",
                (int(guild_id), int(user_id)),
            ) as cur:
                rows = await cur.fetchall()
        return {r[0]: int(r[1]) for r in rows}
    except Exception:
        return {}


# ─── Cosmétiques possédés / équipés ────────────────────────────────────────────
async def grant_cosmetic(guild_id: int, user_id: int, kind: str, item_key: str) -> bool:
    """Ajoute un cosmétique à la collection. True si NOUVEAU (sinon déjà possédé)."""
    if _get_db is None:
        return False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "INSERT OR IGNORE INTO citadelle_cosmetics "
                "(guild_id, user_id, kind, item_key, obtained_at) "
                "VALUES (?,?,?,?, datetime('now'))",
                (int(guild_id), int(user_id), str(kind), str(item_key)),
            )
            await db.commit()
            return getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[citadelle grant_cosmetic] {ex}")
        return False


async def owned_cosmetics(guild_id: int, user_id: int, kind: str) -> list:
    if _get_db is None:
        return []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT item_key FROM citadelle_cosmetics "
                "WHERE guild_id=? AND user_id=? AND kind=?",
                (int(guild_id), int(user_id), str(kind)),
            ) as cur:
                rows = await cur.fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


async def set_active(guild_id: int, user_id: int, slot: str, item_key: str) -> None:
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO citadelle_active "
                "(guild_id, user_id, slot, item_key) VALUES (?,?,?,?)",
                (int(guild_id), int(user_id), str(slot), str(item_key)),
            )
            await db.commit()
    except Exception as ex:
        print(f"[citadelle set_active] {ex}")


async def get_active(guild_id: int, user_id: int) -> dict:
    if _get_db is None:
        return {}
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT slot, item_key FROM citadelle_active WHERE guild_id=? AND user_id=?",
                (int(guild_id), int(user_id)),
            ) as cur:
                rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


# ─── Récompense générique (branchée sur les events en Phase H) ─────────────────
async def award(guild_id: int, user_id: int, eclats: int = 0, materials: dict | None = None) -> None:
    """Helper unique pour récompenser la Cité depuis un event/une action (fail-safe)."""
    try:
        if eclats:
            await grant_eclats(guild_id, user_id, eclats)
            await grant_passe_points(guild_id, user_id, eclats)  # Phase E : alimente la passe
            await grant_mastery(guild_id, user_id, eclats)       # Phase K : maîtrise (cumul à vie)
            # Phase H : boucle event → build — 50 % de chance de lâcher un matériau.
            if random.random() < 0.5:
                try:
                    _mk = random.choice([v[2] for v in PROFESSIONS.values()])
                    await grant_material(guild_id, user_id, _mk, 1)
                except Exception:
                    pass
        for mk, q in (materials or {}).items():
            await grant_material(guild_id, user_id, mk, q)
    except Exception as ex:
        print(f"[citadelle award] {ex}")


async def fortune_snapshot(guild_id: int, user_id: int) -> dict:
    """Lecture seule (aucune mutation) pour le panneau « Ma Fortune » de bot.py.

    Retourne {eclats, rente_gain, rente_ready, rente_remain_h}. Tout fail-safe :
    chaque sous-lecture est isolée pour qu'une erreur n'efface pas le reste.
    Ne perçoit RIEN : c'est un miroir du panneau Revenus passifs, pas un claim.
    """
    out = {"eclats": 0, "rente_gain": 0, "rente_ready": False, "rente_remain_h": 0}
    try:
        out["eclats"] = await get_eclats(guild_id, user_id)
    except Exception:
        pass
    try:
        sanctu = len(await owned_cosmetics(guild_id, user_id, "sanctuaire_module"))
        titles = len(await owned_cosmetics(guild_id, user_id, "title"))
        out["rente_gain"] = 15 + sanctu * 2 + titles * 5
        now = datetime.now(timezone.utc).timestamp()
        last = 0.0
        if _get_db is not None:
            async with _get_db() as db:
                async with db.execute(
                    "SELECT last FROM citadelle_rente WHERE guild_id=? AND user_id=?",
                    (int(guild_id), int(user_id)),
                ) as cur:
                    row = await cur.fetchone()
            last = float(row[0]) if row and row[0] is not None else 0.0
        ready = (now - last) >= _RENTE_COOLDOWN
        out["rente_ready"] = ready
        out["rente_remain_h"] = 0 if ready else max(0, int((_RENTE_COOLDOWN - (now - last)) // 3600) + 1)
    except Exception:
        pass
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  MENU « La Cité » (LayoutView V2, < 40 composants, boutons cite:<section>)
# ═══════════════════════════════════════════════════════════════════════════════
async def build_hub(guild_id: int, user_id: int):
    """Construit le panneau menu de la Cité. Boutons nus → captés par CitadelleButton."""
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title")
    v2_subtitle = _v2.get("subtitle")
    v2_body = _v2.get("body")
    v2_divider = _v2.get("divider")
    v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None

    eclats = await get_eclats(guild_id, user_id)
    mats = await get_materials(guild_id, user_id)
    mat_total = sum(mats.values()) if mats else 0

    items = [
        v2_title("🏛️ La Cité"),
        v2_subtitle("Ton espace de création, de construction et de richesse — tout en boutons"),
        v2_divider(),
        v2_body(
            f"{ECLATS_EMOJI} **{ECLATS_NAME} :** `{eclats:,}`  ·  "
            f"🧱 **Matériaux :** `{mat_total:,}`\n"
            f"-# Gagnés en participant aux events et en étant actif — ils servent à customiser et à bâtir."
        ),
        v2_divider(),
    ]

    for header, keys in _MENU_GROUPS:
        items.append(v2_body(header))
        row_btns = []
        for k in keys:
            emoji, label, _phase, _teaser = SECTIONS[k]
            row_btns.append(Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"cite:{k}",
            ))
        items.append(discord.ui.ActionRow(*row_btns))

    items.append(v2_divider())
    items.append(v2_subtitle(
        "🔓 Les salles s'ouvrent une par une, très vite. Clique pour découvrir ce que chacune réserve."
    ))

    class _CitadelleHub(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0xCBA135))  # or doré

    return _CitadelleHub()


async def open_hub(i: discord.Interaction):
    """Ouvre le menu Cité en ephemeral. ACK d'abord (zéro échec d'interaction)."""
    try:
        if not i.response.is_done():
            await i.response.defer(ephemeral=True)
    except Exception:
        pass
    if i.guild is None:
        try:
            await i.followup.send("❌ La Cité est accessible uniquement sur le serveur.", ephemeral=True)
        except Exception:
            pass
        return
    try:
        view = await build_hub(i.guild.id, i.user.id)
        if view is None:
            await i.followup.send("❌ La Cité est momentanément indisponible, réessaie.", ephemeral=True)
            return
        await i.followup.send(view=view, ephemeral=True)
    except Exception as ex:
        print(f"[citadelle open_hub] {ex}")
        try:
            await i.followup.send("❌ La Cité est momentanément indisponible, réessaie.", ephemeral=True)
        except Exception:
            pass


async def _nav(i: discord.Interaction, view):
    """Navigue/rafraîchit le panneau IN-PLACE (edit_message = ACK) ; fallback followup.
    Garantit l'ACK → jamais d'« Échec de l'interaction »."""
    if view is None:
        try:
            if not i.response.is_done():
                await i.response.send_message("❌ Panneau indisponible, réessaie.", ephemeral=True)
        except Exception:
            pass
        return
    try:
        if not i.response.is_done():
            await i.response.edit_message(view=view)
            return
    except Exception:
        pass
    try:
        await i.edit_original_response(view=view)
    except Exception:
        try:
            await i.followup.send(view=view, ephemeral=True)
        except Exception:
            pass


def _retour_row():
    return discord.ui.ActionRow(
        Button(label="⬅️ Retour à la Cité", style=discord.ButtonStyle.secondary, custom_id="cite:home")
    )


def _build_soon_panel(section: str):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title")
    v2_body = _v2.get("body")
    v2_divider = _v2.get("divider")
    v2_container = _v2.get("container")
    meta = SECTIONS.get(section)
    if not (LayoutView and v2_title and v2_body and v2_divider and v2_container and meta):
        return None
    emoji, label, phase, teaser = meta
    items = [
        v2_title(f"{emoji}  {label}"),
        v2_body(teaser),
        v2_divider(),
        v2_body(
            f"🔒 **En cours de construction** — ouverture imminente _(Phase {phase})_.\n"
            f"-# Tes {ECLATS_EMOJI} {ECLATS_NAME} et tes 🧱 matériaux t'y attendront : rien n'est perdu."
        ),
        _retour_row(),
    ]

    class _Soon(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x6E7681))

    return _Soon()


async def _route(i: discord.Interaction, rest: str):
    """Routage de tout `cite:<rest>` (menu + sous-actions). Navigation IN-PLACE."""
    parts = (rest or "home").split(":")
    section = parts[0] or "home"
    args = parts[1:]
    if i.guild is None:
        try:
            if not i.response.is_done():
                await i.response.send_message("❌ Serveur uniquement.", ephemeral=True)
        except Exception:
            pass
        return
    try:
        if section == "home":
            return await _nav(i, await build_hub(i.guild.id, i.user.id))
        handler = _SECTION_HANDLERS.get(section)
        if handler is not None:
            return await handler(i, args)
        return await _nav(i, _build_soon_panel(section))
    except Exception as ex:
        print(f"[citadelle _route {rest}] {ex}")
        try:
            if not i.response.is_done():
                await i.response.send_message("❌ Erreur, réessaie.", ephemeral=True)
            else:
                await i.followup.send("❌ Erreur, réessaie.", ephemeral=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE B — Forge d'Apparence (teintures cosmétiques, 0 impact sur les stats)
# ═══════════════════════════════════════════════════════════════════════════════
# key -> (emoji, nom, prix en Éclats de Création). 100 % COSMÉTIQUE.
DYES = {
    "azur":      ("🔵", "Azur Royal",    40),
    "cramoisi":  ("🔴", "Cramoisi",      40),
    "emeraude":  ("🟢", "Émeraude",      40),
    "ambre":     ("🟠", "Ambre",         60),
    "amethyste": ("🟣", "Améthyste",     60),
    "ivoire":    ("⚪", "Ivoire",        60),
    "onyx":      ("⚫", "Onyx",          80),
    "turquoise": ("🩵", "Turquoise",    120),
    "rose":      ("🩷", "Rose Pâle",    120),
    "or":        ("🟡", "Or Pur",       160),
    "prisme":    ("🌈", "Prisme",       400),
    "abyssal":   ("🟦", "Bleu Abyssal", 650),
}
_DYE_ORDER = list(DYES.keys())


def dye_label(key: str) -> str:
    d = DYES.get(key)
    return f"{d[0]} {d[1]}" if d else ""


async def _forge_apply(gid: int, uid: int, key: str) -> str:
    if key == "none":
        await set_active(gid, uid, "dye", "none")
        return "🚫 Teinture retirée — apparence d'origine."
    d = DYES.get(key)
    if not d:
        return "❓ Teinture inconnue."
    emoji, name, price = d
    owned = await owned_cosmetics(gid, uid, "dye")
    if key in owned:
        await set_active(gid, uid, "dye", key)
        return f"✅ Teinture **{emoji} {name}** appliquée !"
    if await spend_eclats(gid, uid, price):
        await grant_cosmetic(gid, uid, "dye", key)
        await set_active(gid, uid, "dye", key)
        return f"🛒 **{emoji} {name}** achetée et appliquée ! (−{price} {ECLATS_EMOJI})"
    bal = await get_eclats(gid, uid)
    return f"❌ Il te manque des {ECLATS_EMOJI} — **{name}** coûte `{price}`, tu as `{bal}`."


async def build_forge_panel(gid: int, uid: int, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title")
    v2_subtitle = _v2.get("subtitle")
    v2_body = _v2.get("body")
    v2_divider = _v2.get("divider")
    v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    eclats = await get_eclats(gid, uid)
    owned = set(await owned_cosmetics(gid, uid, "dye"))
    active = (await get_active(gid, uid)).get("dye", "none")
    active_txt = dye_label(active) if active and active != "none" else "_aucune_"

    items = [v2_title("🎨  Forge d'Apparence")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Teintures 100 % cosmétiques — elles ne changent JAMAIS tes stats."))
    items.append(v2_body(
        f"{ECLATS_EMOJI} **{ECLATS_NAME} :** `{eclats:,}`  ·  🎨 **Teinture actuelle :** {active_txt}\n"
        f"-# Possédée ✅ = applique en 1 clic · sinon elle coûte des {ECLATS_EMOJI} (prix ci-dessous)."
    ))
    legend = "  ·  ".join(
        f"{DYES[k][0]} {DYES[k][1]} `{DYES[k][2]}`" + (" ✅" if k in owned else "")
        for k in _DYE_ORDER
    )
    items.append(v2_body(legend))
    items.append(v2_divider())

    row = []
    for k in _DYE_ORDER:
        emoji, name, _price = DYES[k]
        style = (discord.ButtonStyle.success if k == active
                 else discord.ButtonStyle.primary if k in owned
                 else discord.ButtonStyle.secondary)
        row.append(Button(label=name[:20], emoji=emoji, style=style, custom_id=f"cite:forge:eq:{k}"))
        if len(row) == 4:
            items.append(discord.ui.ActionRow(*row))
            row = []
    if row:
        items.append(discord.ui.ActionRow(*row))

    items.append(discord.ui.ActionRow(
        Button(label="🚫 Retirer", style=discord.ButtonStyle.danger, custom_id="cite:forge:eq:none"),
        Button(label="⬅️ Retour à la Cité", style=discord.ButtonStyle.secondary, custom_id="cite:home"),
    ))

    class _Forge(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0xCBA135))

    return _Forge()


async def _forge(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if args and args[0] == "eq":
        key = args[1] if len(args) > 1 else "none"
        status = await _forge_apply(gid, uid, key)
    await _nav(i, await build_forge_panel(gid, uid, status))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE C — Carte de Joueur (identité cosmétique : thème + cadre + devise)
# ═══════════════════════════════════════════════════════════════════════════════
# Thèmes = couleur d'accent de la carte. key -> (emoji, nom, couleur, prix Éclats)
THEMES = {
    "defaut":  ("⬜", "Ardoise",  0x2B2D31,   0),
    "or":      ("🟡", "Doré",     0xCBA135,   0),
    "azur":    ("🔵", "Azur",     0x3498DB,  60),
    "sang":    ("🔴", "Sang",     0xC0392B,  60),
    "foret":   ("🟢", "Forêt",    0x27AE60,  60),
    "royal":   ("🟣", "Royal",    0x8E44AD, 100),
    "abysse":  ("🟦", "Abysse",   0x1F3A93, 150),
    "prisme":  ("🌈", "Prisme",   0xE91E63, 400),
}
_THEME_ORDER = list(THEMES.keys())
# Cadres = bordure décorative. key -> (emoji, nom, prix Éclats)
FRAMES = {
    "aucun":    ("▫️", "Aucun",     0),
    "etoiles":  ("✨", "Étoilé",   40),
    "flammes":  ("🔥", "Flammes",  60),
    "laurier":  ("🌿", "Laurier",  60),
    "cristaux": ("💠", "Cristaux", 120),
    "couronne": ("👑", "Couronne", 150),
}
_FRAME_ORDER = list(FRAMES.keys())


def _sanitize_devise(txt: str) -> str:
    txt = (txt or "").replace("\n", " ").replace("`", "'").replace("@", "＠")
    return txt.strip()[:80]


async def build_carte_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    eclats = await get_eclats(gid, uid)
    active = await get_active(gid, uid)
    theme_k = active.get("theme", "defaut") if active.get("theme") in THEMES else "defaut"
    frame_k = active.get("frame", "aucun") if active.get("frame") in FRAMES else "aucun"
    dye_k = active.get("dye", "none")
    devise = active.get("devise", "none")
    t_emoji, t_name, t_color, _ = THEMES[theme_k]
    f_emoji, f_name, _ = FRAMES[frame_k]
    f_border = "" if frame_k == "aucun" else f_emoji
    name = getattr(i.user, "display_name", "Aventurier")
    name_line = f"{f_border} **{name}** {f_border}".strip()
    dye_txt = dye_label(dye_k) if dye_k and dye_k != "none" else "_aucune_"
    devise_txt = f"_« {devise} »_" if devise and devise != "none" else "_(pas encore de devise)_"
    title_k = active.get("cite_title")
    title_line = ""
    try:
        if title_k and title_k in CITE_TITLES:
            _te, _tl = CITE_TITLES[title_k]
            title_line = f"\n🏷️ Titre : **{_te} {_tl}**"
    except Exception:
        title_line = ""

    items = [v2_title("🪪  Carte de Joueur")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Compose ton identité — 100 % cosmétique, visible par tous."))
    items.append(v2_divider())
    # ─ Aperçu de la carte ─
    items.append(v2_body(
        f"{emblem_string(active)}  {name_line}{title_line}\n"
        f"🎨 Thème : **{t_emoji} {t_name}**  ·  🖼️ Cadre : **{f_emoji} {f_name}**\n"
        f"🩹 Teinture : {dye_txt}\n"
        f"{devise_txt}"
    ))
    items.append(v2_divider())
    items.append(v2_body(
        f"{ECLATS_EMOJI} **{ECLATS_NAME} :** `{eclats:,}`\n"
        f"-# Personnalise via les boutons ci-dessous."
    ))
    items.append(discord.ui.ActionRow(
        Button(label="🎨 Thème", style=discord.ButtonStyle.primary, custom_id="cite:carte:theme"),
        Button(label="🖼️ Cadre", style=discord.ButtonStyle.primary, custom_id="cite:carte:frame"),
        Button(label="✍️ Devise", style=discord.ButtonStyle.success, custom_id="cite:carte:devise"),
    ))
    items.append(_retour_row())

    class _Carte(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=t_color))

    return _Carte()


async def _build_picker(i, kind: str, status: str | None = None):
    """Panneau de choix générique pour thème/cadre (boutons achat+équipe)."""
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    gid, uid = i.guild.id, i.user.id
    eclats = await get_eclats(gid, uid)
    owned = set(await owned_cosmetics(gid, uid, kind))
    active = (await get_active(gid, uid)).get(kind, "defaut" if kind == "theme" else "aucun")
    if kind == "theme":
        catalog, order, title, slot_emoji = THEMES, _THEME_ORDER, "🎨  Thème de la carte", "🎨"
    else:
        catalog, order, title, slot_emoji = FRAMES, _FRAME_ORDER, "🖼️  Cadre de la carte", "🖼️"

    items = [v2_title(title)]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Possédé ✅ = applique en 1 clic · sinon coûte des Éclats (gratuit = ⭐)."))
    legend_parts = []
    for k in order:
        meta = catalog[k]
        emoji, nm = meta[0], meta[1]
        price = meta[-1]
        tag = " ✅" if (k in owned or price == 0) else f" `{price}`"
        legend_parts.append(f"{emoji} {nm}{tag}")
    items.append(v2_body("  ·  ".join(legend_parts)))
    items.append(v2_body(f"{ECLATS_EMOJI} **{ECLATS_NAME} :** `{eclats:,}`"))
    items.append(v2_divider())

    row = []
    for k in order:
        meta = catalog[k]
        emoji, nm = meta[0], meta[1]
        style = (discord.ButtonStyle.success if k == active
                 else discord.ButtonStyle.primary if (k in owned or meta[-1] == 0)
                 else discord.ButtonStyle.secondary)
        row.append(Button(label=nm[:18], emoji=emoji, style=style,
                          custom_id=f"cite:carte:{kind}:eq:{k}"))
        if len(row) == 4:
            items.append(discord.ui.ActionRow(*row)); row = []
    if row:
        items.append(discord.ui.ActionRow(*row))
    items.append(discord.ui.ActionRow(
        Button(label="⬅️ Retour à la carte", style=discord.ButtonStyle.secondary, custom_id="cite:carte"),
    ))

    color = THEMES[active][2] if (kind == "theme" and active in THEMES) else 0xCBA135

    class _Picker(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=color))

    return _Picker()


async def _carte_apply(gid: int, uid: int, kind: str, key: str) -> str:
    catalog = THEMES if kind == "theme" else FRAMES
    meta = catalog.get(key)
    if not meta:
        return "❓ Choix inconnu."
    emoji, nm = meta[0], meta[1]
    price = meta[-1]
    owned = await owned_cosmetics(gid, uid, kind)
    if key in owned or price == 0:
        await set_active(gid, uid, kind, key)
        return f"✅ **{emoji} {nm}** appliqué !"
    if await spend_eclats(gid, uid, price):
        await grant_cosmetic(gid, uid, kind, key)
        await set_active(gid, uid, kind, key)
        return f"🛒 **{emoji} {nm}** acheté et appliqué ! (−{price} {ECLATS_EMOJI})"
    bal = await get_eclats(gid, uid)
    return f"❌ Il te manque des {ECLATS_EMOJI} — **{nm}** coûte `{price}`, tu as `{bal}`."


class _DeviseModal(discord.ui.Modal, title="✍️ Ta devise"):
    devise = discord.ui.TextInput(
        label="Ta devise (80 caractères max)",
        placeholder="Ex : Toujours plus haut !",
        required=False, max_length=80, style=discord.TextStyle.short,
    )

    def __init__(self, current: str = ""):
        super().__init__()
        if current and current != "none":
            self.devise.default = current

    async def on_submit(self, i: discord.Interaction):
        try:
            txt = _sanitize_devise(self.devise.value)
            await set_active(i.guild.id, i.user.id, "devise", txt if txt else "none")
            status = "✍️ Devise mise à jour !" if txt else "✍️ Devise effacée."
            await _nav(i, await build_carte_panel(i, status))
        except Exception as ex:
            print(f"[citadelle DeviseModal] {ex}")
            try:
                await i.response.send_message("❌ Erreur, réessaie.", ephemeral=True)
            except Exception:
                pass


async def _carte(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    if not args:
        return await _nav(i, await build_carte_panel(i))
    head = args[0]
    if head in ("theme", "frame"):
        if len(args) >= 3 and args[1] == "eq":
            status = await _carte_apply(gid, uid, head, args[2])
            return await _nav(i, await _build_picker(i, head, status))
        return await _nav(i, await _build_picker(i, head))
    if head == "devise":
        current = (await get_active(gid, uid)).get("devise", "")
        try:
            return await i.response.send_modal(_DeviseModal(current))
        except Exception as ex:
            print(f"[citadelle carte devise modal] {ex}")
            return await _nav(i, await build_carte_panel(i))
    return await _nav(i, await build_carte_panel(i))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE D — Atelier d'Emblèmes (forme × symbole × couleur ≈ 384 combinaisons)
# ═══════════════════════════════════════════════════════════════════════════════
EMB_SHAPES = {
    "ecu":      ("🛡️", "Écu",       0),
    "banniere": ("🚩", "Bannière",  0),
    "sceau":    ("🔰", "Sceau",    60),
    "blason":   ("🏵️", "Blason",  100),
}
EMB_SYMBOLS = {
    "epee":     ("⚔️", "Épées",     0),
    "etoile":   ("🌟", "Étoile",    0),
    "loup":     ("🐺", "Loup",     40),
    "aigle":    ("🦅", "Aigle",    60),
    "flamme":   ("🔥", "Flamme",   40),
    "lune":     ("🌙", "Lune",     40),
    "soleil":   ("☀️", "Soleil",   40),
    "foudre":   ("⚡", "Foudre",   60),
    "rose":     ("🌹", "Rose",     40),
    "dragon":   ("🐉", "Dragon",   80),
    "crane":    ("💀", "Crâne",    80),
    "couronne": ("👑", "Couronne", 150),
}
EMB_COLORS = {
    "or":     ("🟡", "Or",     0xCBA135,   0),
    "azur":   ("🔵", "Azur",   0x3498DB,   0),
    "sang":   ("🔴", "Sang",   0xC0392B,  40),
    "foret":  ("🟢", "Forêt",  0x27AE60,  40),
    "onyx":   ("⚫", "Onyx",   0x2B2D31,  60),
    "argent": ("⚪", "Argent", 0xBDC3C7,  60),
    "royal":  ("🟣", "Royal",  0x8E44AD,  80),
    "prisme": ("🌈", "Prisme", 0xE91E63, 300),
}
_EMB_CATS = {
    "shape":  (EMB_SHAPES,  list(EMB_SHAPES),  "Forme",    "emb_shape",  "ecu"),
    "symbol": (EMB_SYMBOLS, list(EMB_SYMBOLS), "Symbole",  "emb_symbol", "epee"),
    "color":  (EMB_COLORS,  list(EMB_COLORS),  "Couleur",  "emb_color",  "or"),
}


def _emb_state(active: dict):
    sh = active.get("emb_shape", "ecu") if active.get("emb_shape") in EMB_SHAPES else "ecu"
    sy = active.get("emb_symbol", "epee") if active.get("emb_symbol") in EMB_SYMBOLS else "epee"
    co = active.get("emb_color", "or") if active.get("emb_color") in EMB_COLORS else "or"
    return sh, sy, co


def emblem_string(active: dict) -> str:
    sh, sy, co = _emb_state(active)
    return f"{EMB_COLORS[co][0]}{EMB_SHAPES[sh][0]}{EMB_SYMBOLS[sy][0]}"


async def build_embleme_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    eclats = await get_eclats(gid, uid)
    active = await get_active(gid, uid)
    sh, sy, co = _emb_state(active)
    color = EMB_COLORS[co][2]

    items = [v2_title("🛡️  Atelier d'Emblèmes")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Compose un emblème unique — forme × symbole × couleur (cosmétique)."))
    items.append(v2_divider())
    items.append(v2_body(
        f"# {emblem_string(active)}\n"
        f"🛡️ Forme : **{EMB_SHAPES[sh][1]}**  ·  ✨ Symbole : **{EMB_SYMBOLS[sy][1]}**  ·  "
        f"🎨 Couleur : **{EMB_COLORS[co][1]}**"
    ))
    items.append(v2_divider())
    items.append(v2_body(f"{ECLATS_EMOJI} **{ECLATS_NAME} :** `{eclats:,}`"))
    items.append(discord.ui.ActionRow(
        Button(label="🛡️ Forme", style=discord.ButtonStyle.primary, custom_id="cite:emblemes:shape"),
        Button(label="✨ Symbole", style=discord.ButtonStyle.primary, custom_id="cite:emblemes:symbol"),
        Button(label="🎨 Couleur", style=discord.ButtonStyle.primary, custom_id="cite:emblemes:color"),
    ))
    items.append(_retour_row())

    class _Emb(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=color))

    return _Emb()


async def _build_emb_picker(i: discord.Interaction, cat: str, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    info = _EMB_CATS.get(cat)
    if not info:
        return await build_embleme_panel(i)
    catalog, order, label, slot, default = info
    gid, uid = i.guild.id, i.user.id
    eclats = await get_eclats(gid, uid)
    owned = set(await owned_cosmetics(gid, uid, slot))
    active = (await get_active(gid, uid)).get(slot, default)

    items = [v2_title(f"{label} de l'emblème")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Possédé ✅ ou gratuit ⭐ = applique en 1 clic · sinon coûte des Éclats."))
    legend = "  ·  ".join(
        f"{catalog[k][0]} {catalog[k][1]}" + (" ✅" if (k in owned or catalog[k][-1] == 0) else f" `{catalog[k][-1]}`")
        for k in order
    )
    items.append(v2_body(legend))
    items.append(v2_body(f"{ECLATS_EMOJI} **{ECLATS_NAME} :** `{eclats:,}`"))
    items.append(v2_divider())

    row = []
    for k in order:
        meta = catalog[k]
        style = (discord.ButtonStyle.success if k == active
                 else discord.ButtonStyle.primary if (k in owned or meta[-1] == 0)
                 else discord.ButtonStyle.secondary)
        row.append(Button(label=meta[1][:18], emoji=meta[0], style=style,
                          custom_id=f"cite:emblemes:{cat}:eq:{k}"))
        if len(row) == 4:
            items.append(discord.ui.ActionRow(*row)); row = []
    if row:
        items.append(discord.ui.ActionRow(*row))
    items.append(discord.ui.ActionRow(
        Button(label="⬅️ Retour à l'emblème", style=discord.ButtonStyle.secondary, custom_id="cite:emblemes"),
    ))

    class _EmbPick(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0xCBA135))

    return _EmbPick()


async def _emb_apply(gid: int, uid: int, cat: str, key: str) -> str:
    info = _EMB_CATS.get(cat)
    if not info:
        return "❓ Catégorie inconnue."
    catalog, _order, _label, slot, _default = info
    meta = catalog.get(key)
    if not meta:
        return "❓ Choix inconnu."
    emoji, nm = meta[0], meta[1]
    price = meta[-1]
    owned = await owned_cosmetics(gid, uid, slot)
    if key in owned or price == 0:
        await set_active(gid, uid, slot, key)
        return f"✅ **{emoji} {nm}** appliqué !"
    if await spend_eclats(gid, uid, price):
        await grant_cosmetic(gid, uid, slot, key)
        await set_active(gid, uid, slot, key)
        return f"🛒 **{emoji} {nm}** acheté et appliqué ! (−{price} {ECLATS_EMOJI})"
    bal = await get_eclats(gid, uid)
    return f"❌ Il te manque des {ECLATS_EMOJI} — **{nm}** coûte `{price}`, tu as `{bal}`."


async def _emblemes(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    if not args:
        return await _nav(i, await build_embleme_panel(i))
    cat = args[0]
    if cat in _EMB_CATS:
        if len(args) >= 3 and args[1] == "eq":
            status = await _emb_apply(gid, uid, cat, args[2])
            return await _nav(i, await _build_emb_picker(i, cat, status))
        return await _nav(i, await _build_emb_picker(i, cat))
    return await _nav(i, await build_embleme_panel(i))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE E — Passe de Saison de la Cité (GRATUITE, reset mensuel, 100 % cosmétique)
# ═══════════════════════════════════════════════════════════════════════════════
def _season_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


# Paliers : (seuil_points, label, éclats, [(kind, key) cosmétiques à débloquer])
PASSE_TIERS = [
    (20,  "30 Éclats",                  30, []),
    (50,  "Teinture Turquoise",          0, [("dye", "turquoise")]),
    (90,  "50 Éclats",                  50, []),
    (140, "Cadre Étoilé",                0, [("frame", "etoiles")]),
    (200, "80 Éclats",                  80, []),
    (280, "Thème Royal",                 0, [("theme", "royal")]),
    (370, "Symbole Dragon",              0, [("emb_symbol", "dragon")]),
    (480, "120 Éclats",                120, []),
    (620, "Cadre Couronne",              0, [("frame", "couronne")]),
    (800, "Thème Prisme + 200 Éclats", 200, [("theme", "prisme")]),
]


async def get_passe(gid: int, uid: int):
    """(points, set(claimed_idx)) pour la SAISON COURANTE (auto-crée la ligne)."""
    season = _season_key()
    if _get_db is None:
        return 0, set()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO citadelle_passe (guild_id, user_id, season, points, claimed) "
                "VALUES (?,?,?,0,'')", (int(gid), int(uid), season))
            await db.commit()
            async with db.execute(
                "SELECT points, claimed FROM citadelle_passe "
                "WHERE guild_id=? AND user_id=? AND season=?",
                (int(gid), int(uid), season)) as cur:
                row = await cur.fetchone()
        pts = int(row[0]) if row else 0
        claimed = set(int(x) for x in (row[1] or "").split(",") if x.strip().isdigit())
        return pts, claimed
    except Exception:
        return 0, set()


async def grant_passe_points(gid: int, uid: int, n: int) -> None:
    if _get_db is None or not n:
        return
    season = _season_key()
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO citadelle_passe (guild_id, user_id, season, points, claimed) "
                "VALUES (?,?,?,?,'') "
                "ON CONFLICT(guild_id, user_id, season) DO UPDATE SET points = MAX(0, points + ?)",
                (int(gid), int(uid), season, int(n), int(n)))
            await db.commit()
    except Exception as ex:
        print(f"[citadelle grant_passe_points] {ex}")


async def _passe_claim(gid: int, uid: int, idx: int) -> str:
    if idx < 0 or idx >= len(PASSE_TIERS):
        return "❓ Palier inconnu."
    threshold, label, eclats, grants = PASSE_TIERS[idx]
    pts, claimed = await get_passe(gid, uid)
    if idx in claimed:
        return "✅ Palier déjà réclamé."
    if pts < threshold:
        return f"🔒 Palier {idx+1} : il te faut `{threshold}` pts (tu as `{pts}`)."
    season = _season_key()
    ok = False
    try:
        async with _get_db() as db:
            cur = await db.execute(
                "UPDATE citadelle_passe SET claimed = claimed || ? "
                "WHERE guild_id=? AND user_id=? AND season=? AND points >= ? "
                "AND (',' || claimed || ',') NOT LIKE ?",
                (f"{idx},", int(gid), int(uid), season, threshold, f"%,{idx},%"))
            await db.commit()
            ok = getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[citadelle _passe_claim] {ex}")
        return "❌ Erreur, réessaie."
    if not ok:
        return "✅ Palier déjà réclamé."
    if eclats:
        await grant_eclats(gid, uid, eclats)
    for kind, key in grants:
        await grant_cosmetic(gid, uid, kind, key)
    return f"🎁 Palier {idx+1} réclamé : **{label}** !"


async def build_passe_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    pts, claimed = await get_passe(gid, uid)
    season = _season_key()

    items = [v2_title(f"🎟️  Passe de Saison — {season}")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("GRATUITE. Gagne des points en participant aux events/à l'activité → réclame des récompenses cosmétiques. Remise à zéro chaque mois."))
    items.append(v2_body(f"⭐ **Points de passe :** `{pts}`"))
    items.append(v2_divider())

    lines = []
    claimable = []
    for idx, (th, label, _ec, _gr) in enumerate(PASSE_TIERS):
        if idx in claimed:
            mark = "✅"
        elif pts >= th:
            mark = "🎁"
            claimable.append(idx)
        else:
            mark = "🔒"
        lines.append(f"{mark} **P{idx+1}** _(≥{th} pts)_ — {label}")
    items.append(v2_body("\n".join(lines)))
    items.append(v2_divider())

    if claimable:
        row = []
        for idx in claimable[:10]:
            row.append(Button(label=f"🎁 Réclamer P{idx+1}", style=discord.ButtonStyle.success,
                              custom_id=f"cite:passe:claim:{idx}"))
            if len(row) == 5:
                items.append(discord.ui.ActionRow(*row)); row = []
        if row:
            items.append(discord.ui.ActionRow(*row))
    else:
        items.append(v2_body("-# Continue à participer pour atteindre le prochain palier !"))
    items.append(_retour_row())

    class _Passe(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x9B59B6))

    return _Passe()


async def _passe(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if len(args) >= 2 and args[0] == "claim":
        try:
            idx = int(args[1])
        except Exception:
            idx = -1
        status = await _passe_claim(gid, uid, idx)
    await _nav(i, await build_passe_panel(i, status))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE F — Sanctuaire Personnel (housing : on collecte et place des modules)
# ═══════════════════════════════════════════════════════════════════════════════
# key -> (emoji, nom, prix Éclats). Les modules possédés sont « placés » dans le sanctuaire.
SANCTU_MODULES = {
    "cheminee":     ("🔥", "Cheminée",            60),
    "biblio":       ("📚", "Bibliothèque",        80),
    "jardin":       ("🌳", "Jardin intérieur",    80),
    "statue":       ("🗿", "Statue",             100),
    "armes":        ("⚔️", "Salle d'armes",      120),
    "autel":        ("🕯️", "Autel",             120),
    "trophees":     ("🏆", "Galerie de trophées", 150),
    "fontaine":     ("⛲", "Fontaine",           150),
    "chambre":      ("🛏️", "Chambre royale",     200),
    "observatoire": ("🔭", "Observatoire",       220),
    "forge_perso":  ("🔨", "Forge privée",       250),
    "trone":        ("🐉", "Trône du Dragon",    500),
}
_SANCTU_ORDER = list(SANCTU_MODULES.keys())


async def _sanctu_buy(gid: int, uid: int, key: str) -> str:
    d = SANCTU_MODULES.get(key)
    if not d:
        return "❓ Module inconnu."
    emoji, name, price = d
    owned = await owned_cosmetics(gid, uid, "sanctuaire_module")
    if key in owned:
        return f"🏯 **{emoji} {name}** est déjà construit dans ton sanctuaire."
    if await spend_eclats(gid, uid, price):
        await grant_cosmetic(gid, uid, "sanctuaire_module", key)
        return f"🏗️ **{emoji} {name}** construit ! (−{price} {ECLATS_EMOJI})"
    bal = await get_eclats(gid, uid)
    return f"❌ Il te manque des {ECLATS_EMOJI} — **{name}** coûte `{price}`, tu as `{bal}`."


async def build_sanctu_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    eclats = await get_eclats(gid, uid)
    owned = set(await owned_cosmetics(gid, uid, "sanctuaire_module"))
    placed = "  ".join(SANCTU_MODULES[k][0] for k in _SANCTU_ORDER if k in owned)
    placed_display = placed if placed else "_(sanctuaire encore vide — construis ton premier module !)_"

    items = [v2_title("🏯  Sanctuaire Personnel")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Bâtis ton espace : chaque module construit y reste à vie."))
    items.append(v2_body(
        f"**🏛️ Niveau du sanctuaire : `{len(owned)}/{len(SANCTU_MODULES)}`**\n"
        f"{placed_display}"
    ))
    items.append(v2_divider())
    legend = "  ·  ".join(
        f"{SANCTU_MODULES[k][0]} {SANCTU_MODULES[k][1]}" + (" ✅" if k in owned else f" `{SANCTU_MODULES[k][2]}`")
        for k in _SANCTU_ORDER
    )
    items.append(v2_body(legend))
    items.append(v2_body(f"{ECLATS_EMOJI} **{ECLATS_NAME} :** `{eclats:,}`"))
    items.append(v2_divider())

    row = []
    for k in _SANCTU_ORDER:
        emoji, name, _price = SANCTU_MODULES[k]
        style = discord.ButtonStyle.success if k in owned else discord.ButtonStyle.secondary
        row.append(Button(label=name[:18], emoji=emoji, style=style,
                          custom_id=f"cite:sanctuaire:buy:{k}"))
        if len(row) == 4:
            items.append(discord.ui.ActionRow(*row)); row = []
    if row:
        items.append(discord.ui.ActionRow(*row))
    items.append(_retour_row())

    class _Sanctu(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x8E5A2B))

    return _Sanctu()


async def _sanctuaire(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if len(args) >= 2 and args[0] == "buy":
        status = await _sanctu_buy(gid, uid, args[1])
    await _nav(i, await build_sanctu_panel(i, status))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE G — Métiers & Récolte (professions non-combat, produisent des matériaux)
# ═══════════════════════════════════════════════════════════════════════════════
# key -> (emoji, nom, mat_key, mat_emoji). « Travailler » = +XP + matériaux (cooldown).
PROFESSIONS = {
    "mineur":     ("⛏️", "Mineur",     "minerai", "⛏️"),
    "herboriste": ("🌿", "Herboriste", "herbe",   "🌿"),
    "pecheur":    ("🎣", "Pêcheur",    "poisson", "🐟"),
    "forgeron":   ("🔨", "Forgeron",   "lingot",  "🧱"),
    "enchanteur": ("✨", "Enchanteur", "essence", "🔮"),
}
_PROF_ORDER = list(PROFESSIONS.keys())
_PROF_COOLDOWN = 3600.0   # 1 h entre deux récoltes par métier
_PROF_XP_GAIN = 12        # XP par récolte
_PROF_XP_PER_LVL = 100    # 100 XP / niveau


def _prof_level(xp: int) -> int:
    return 1 + int(xp) // _PROF_XP_PER_LVL


async def get_professions(gid: int, uid: int) -> dict:
    """{prof: (xp, last_work)} — auto-crée les lignes manquantes."""
    out = {}
    if _get_db is None:
        return {k: (0, 0.0) for k in _PROF_ORDER}
    try:
        async with _get_db() as db:
            for k in _PROF_ORDER:
                await db.execute(
                    "INSERT OR IGNORE INTO citadelle_professions (guild_id, user_id, prof, xp, last_work) "
                    "VALUES (?,?,?,0,0)", (int(gid), int(uid), k))
            await db.commit()
            async with db.execute(
                "SELECT prof, xp, last_work FROM citadelle_professions "
                "WHERE guild_id=? AND user_id=?", (int(gid), int(uid))) as cur:
                rows = await cur.fetchall()
        for prof, xp, lw in rows:
            out[prof] = (int(xp or 0), float(lw or 0))
    except Exception:
        pass
    for k in _PROF_ORDER:
        out.setdefault(k, (0, 0.0))
    return out


async def _prof_work(gid: int, uid: int, prof: str) -> str:
    d = PROFESSIONS.get(prof)
    if not d:
        return "❓ Métier inconnu."
    emoji, name, mat_key, mat_emoji = d
    now = datetime.now(timezone.utc).timestamp()
    worked = False
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO citadelle_professions (guild_id, user_id, prof, xp, last_work) "
                "VALUES (?,?,?,0,0)", (int(gid), int(uid), prof))
            cur = await db.execute(
                "UPDATE citadelle_professions SET xp = xp + ?, last_work = ? "
                "WHERE guild_id=? AND user_id=? AND prof=? AND (? - last_work) >= ?",
                (_PROF_XP_GAIN, now, int(gid), int(uid), prof, now, _PROF_COOLDOWN))
            await db.commit()
            worked = getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[citadelle _prof_work] {ex}")
        return "❌ Erreur, réessaie."
    if not worked:
        return f"⏳ **{emoji} {name}** se repose encore — reviens un peu plus tard."
    qty = random.randint(1, 3)
    await grant_material(gid, uid, mat_key, qty)
    # petite chance d'Éclats bonus (alimente aussi la passe)
    bonus = 2 if random.random() < 0.5 else 0
    if bonus:
        await award(gid, uid, eclats=bonus)
    extra = f" · +{bonus} {ECLATS_EMOJI}" if bonus else ""
    return f"{emoji} **{name}** : +{qty} {mat_emoji} {mat_key} · +{_PROF_XP_GAIN} XP{extra}"


async def build_metiers_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    profs = await get_professions(gid, uid)
    mats = await get_materials(gid, uid)
    now = datetime.now(timezone.utc).timestamp()

    items = [v2_title("⚒️  Métiers & Récolte")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Un vrai chemin SANS combat. Récolte (1×/h par métier) → XP + matériaux."))
    lines = []
    for k in _PROF_ORDER:
        emoji, name, mat_key, mat_emoji = PROFESSIONS[k]
        xp, lw = profs.get(k, (0, 0.0))
        lvl = _prof_level(xp)
        into = int(xp) % _PROF_XP_PER_LVL
        ready = (now - lw) >= _PROF_COOLDOWN
        when = "✅ prêt" if ready else f"⏳ {int((_PROF_COOLDOWN - (now - lw)) // 60) + 1} min"
        lines.append(f"{emoji} **{name}** — Niv `{lvl}` ({into}/{_PROF_XP_PER_LVL} XP) · {when}")
    items.append(v2_body("\n".join(lines)))
    if mats:
        mat_line = "  ·  ".join(f"`{q}` {k}" for k, q in sorted(mats.items()))
        items.append(v2_body(f"🧱 **Tes matériaux :** {mat_line}"))
    items.append(v2_divider())

    row = []
    for k in _PROF_ORDER:
        emoji, name, _mk, _me = PROFESSIONS[k]
        xp, lw = profs.get(k, (0, 0.0))
        ready = (now - lw) >= _PROF_COOLDOWN
        row.append(Button(label=f"{name}", emoji=emoji,
                          style=discord.ButtonStyle.success if ready else discord.ButtonStyle.secondary,
                          custom_id=f"cite:metiers:work:{k}"))
        if len(row) == 5:
            items.append(discord.ui.ActionRow(*row)); row = []
    if row:
        items.append(discord.ui.ActionRow(*row))
    items.append(_retour_row())

    class _Metiers(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x6D4C41))

    return _Metiers()


async def _metiers(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if len(args) >= 2 and args[0] == "work":
        status = await _prof_work(gid, uid, args[1])
    await _nav(i, await build_metiers_panel(i, status))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE H — Collections & Reliques (compléter un set = titre PERMANENT)
# ═══════════════════════════════════════════════════════════════════════════════
CITE_TITLES = {
    "maitre_couleurs": ("🎨", "Maître des Couleurs"),
    "batisseur":       ("🏛️", "Bâtisseur de la Cité"),
    "heraldiste":      ("🛡️", "Maître Héraldiste"),
}
# key -> (emoji, nom, kind, [clés requises], titre_clé, éclats)
COLLECTIONS = {
    "teinturier": ("🎨", "Toutes les Teintures", "dye",
                   list(DYES.keys()), "maitre_couleurs", 200),
    "architecte": ("🏯", "Tous les Modules du Sanctuaire", "sanctuaire_module",
                   list(SANCTU_MODULES.keys()), "batisseur", 300),
    "heraldiste": ("🛡️", "Tous les Symboles d'Emblème", "emb_symbol",
                   list(EMB_SYMBOLS.keys()), "heraldiste", 200),
}
_COLL_ORDER = list(COLLECTIONS.keys())


async def _collection_claim(gid: int, uid: int, key: str) -> str:
    c = COLLECTIONS.get(key)
    if not c:
        return "❓ Collection inconnue."
    emoji, name, kind, required, title_key, eclats = c
    owned = set(await owned_cosmetics(gid, uid, kind))
    have = sum(1 for k in required if k in owned)
    if have < len(required):
        return f"🔒 **{name}** : encore `{len(required) - have}` à débloquer ({have}/{len(required)})."
    # claim ATOMIQUE : grant_cosmetic renvoie True uniquement si NOUVEAU
    if not await grant_cosmetic(gid, uid, "collection_claimed", key):
        return "✅ Récompense déjà réclamée."
    await grant_cosmetic(gid, uid, "title", title_key)
    await set_active(gid, uid, "cite_title", title_key)
    if eclats:
        await grant_eclats(gid, uid, eclats)
    te, tl = CITE_TITLES.get(title_key, ("🏷️", "Titre"))
    return f"🏆 **{name}** complétée ! Titre **{te} {tl}** débloqué + {eclats} {ECLATS_EMOJI} !"


async def build_collections_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    claimed = set(await owned_cosmetics(gid, uid, "collection_claimed"))

    items = [v2_title("📜  Collections & Reliques")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Complète un set (via la Forge, le Sanctuaire, les Emblèmes…) → titre PERMANENT."))
    lines = []
    completable = []
    for k in _COLL_ORDER:
        emoji, name, kind, required, title_key, eclats = COLLECTIONS[k]
        owned = set(await owned_cosmetics(gid, uid, kind))
        have = sum(1 for rk in required if rk in owned)
        full = have >= len(required)
        if k in claimed:
            mark = "✅"
        elif full:
            mark = "🏆"
            completable.append(k)
        else:
            mark = "🔒"
        te, tl = CITE_TITLES.get(title_key, ("🏷️", "Titre"))
        lines.append(f"{mark} **{emoji} {name}** — `{have}/{len(required)}` → titre **{te} {tl}** + {eclats} {ECLATS_EMOJI}")
    items.append(v2_body("\n".join(lines)))
    items.append(v2_divider())

    if completable:
        row = []
        for k in completable[:5]:
            row.append(Button(label=f"🏆 Réclamer {COLLECTIONS[k][1][:16]}",
                              style=discord.ButtonStyle.success,
                              custom_id=f"cite:collections:claim:{k}"))
            if len(row) == 5:
                items.append(discord.ui.ActionRow(*row)); row = []
        if row:
            items.append(discord.ui.ActionRow(*row))
    else:
        items.append(v2_body("-# Continue à collectionner pour compléter un set !"))
    items.append(_retour_row())

    class _Coll(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0xE67E22))

    return _Coll()


async def _collections(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if len(args) >= 2 and args[0] == "claim":
        status = await _collection_claim(gid, uid, args[1])
    await _nav(i, await build_collections_panel(i, status))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE I — Jardin & Élevage (récolte idle) + Domaine collectif (build serveur)
# ═══════════════════════════════════════════════════════════════════════════════
_GARDEN_COOLDOWN = 72000.0   # ~20 h : une récolte par jour


async def _garden_harvest(gid: int, uid: int) -> str:
    now = datetime.now(timezone.utc).timestamp()
    worked = False
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO citadelle_garden (guild_id, user_id, last) VALUES (?,?,0)",
                (int(gid), int(uid)))
            cur = await db.execute(
                "UPDATE citadelle_garden SET last = ? "
                "WHERE guild_id=? AND user_id=? AND (? - last) >= ?",
                (now, int(gid), int(uid), now, _GARDEN_COOLDOWN))
            await db.commit()
            worked = getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[citadelle _garden_harvest] {ex}")
        return "❌ Erreur, réessaie."
    if not worked:
        return "🌙 Ton jardin a déjà été récolté aujourd'hui — reviens demain."
    sanctu = len(await owned_cosmetics(gid, uid, "sanctuaire_module"))
    eclats = 10 + sanctu * 3   # le sanctuaire booste le rendement (lie F → revenu)
    await award(gid, uid, eclats=eclats)
    mat = random.choice([v[2] for v in PROFESSIONS.values()])
    qty = 1 + (1 if random.random() < 0.5 else 0)
    await grant_material(gid, uid, mat, qty)
    boost = f" _(boost sanctuaire +{sanctu*3})_" if sanctu else ""
    return f"🌿 Récolte du jardin : +{eclats} {ECLATS_EMOJI}{boost} · +{qty} {mat}"


async def build_jardin_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    now = datetime.now(timezone.utc).timestamp()
    ready = True
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT last FROM citadelle_garden WHERE guild_id=? AND user_id=?",
                (int(gid), int(uid))) as cur:
                row = await cur.fetchone()
        last = float(row[0]) if row else 0.0
        ready = (now - last) >= _GARDEN_COOLDOWN
        remain_h = max(0, int((_GARDEN_COOLDOWN - (now - last)) // 3600) + 1)
    except Exception:
        remain_h = 0
    sanctu = len(await owned_cosmetics(gid, uid, "sanctuaire_module"))

    items = [v2_title("🌿  Jardin & Élevage")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Reviens chaque jour récolter — plus ton Sanctuaire est grand, plus ça rapporte."))
    items.append(v2_body(
        f"🏯 Niveau sanctuaire : `{sanctu}` → rendement `{10 + sanctu*3}` {ECLATS_EMOJI}/jour\n"
        + ("✅ **Prêt à récolter !**" if ready else f"🌙 Prochaine récolte dans ~`{remain_h}h`")
    ))
    items.append(v2_divider())
    items.append(discord.ui.ActionRow(
        Button(label="🌿 Récolter le jardin",
               style=discord.ButtonStyle.success if ready else discord.ButtonStyle.secondary,
               custom_id="cite:jardin:harvest"),
    ))
    items.append(_retour_row())

    class _Jardin(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x2E7D32))

    return _Jardin()


async def _jardin(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if args and args[0] == "harvest":
        status = await _garden_harvest(gid, uid)
    await _nav(i, await build_jardin_panel(i, status))


# ─── Domaine collectif du serveur (Grand Œuvre commun) ─────────────────────────
DOMAINE_TIERS = [
    (500,   "🏗️ Fondations"),
    (2000,  "🏛️ Grandes Portes"),
    (5000,  "🗼 Tour de Guet"),
    (12000, "🏰 Citadelle Dorée"),
    (25000, "🌟 Merveille de la Cité"),
]
_DOMAINE_GIVE = 50  # Éclats par contribution


def _progress_bar(cur: int, lo: int, hi: int, width: int = 12) -> str:
    """Petite barre de progression texte entre deux paliers (lo→hi). FAIL-SAFE."""
    try:
        span = max(1, hi - lo)
        ratio = min(1.0, max(0.0, (cur - lo) / span))
        filled = int(round(ratio * width))
        return "🟩" * filled + "⬜" * (width - filled) + f"  {int(ratio*100)}%"
    except Exception:
        return ""


async def get_domaine(gid: int) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT points FROM citadelle_domaine WHERE guild_id=?", (int(gid),)) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


async def _domaine_give(gid: int, uid: int) -> str:
    if not await spend_eclats(gid, uid, _DOMAINE_GIVE):
        bal = await get_eclats(gid, uid)
        return f"❌ Il te faut `{_DOMAINE_GIVE}` {ECLATS_EMOJI} pour contribuer (tu as `{bal}`)."
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO citadelle_domaine (guild_id, points) VALUES (?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET points = points + ?",
                (int(gid), _DOMAINE_GIVE, _DOMAINE_GIVE))
            await db.commit()
    except Exception as ex:
        print(f"[citadelle _domaine_give] {ex}")
    # contribuer fait aussi avancer la passe perso
    await grant_passe_points(gid, uid, _DOMAINE_GIVE)
    return f"🤝 Merci ! Tu as offert `{_DOMAINE_GIVE}` {ECLATS_EMOJI} au Grand Œuvre du serveur."


async def build_domaine_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    pts = await get_domaine(gid)
    eclats = await get_eclats(gid, uid)
    tier_idx = sum(1 for th, _ in DOMAINE_TIERS if pts >= th)
    cur_label = DOMAINE_TIERS[tier_idx - 1][1] if tier_idx > 0 else "🚧 Chantier"
    nxt = DOMAINE_TIERS[tier_idx] if tier_idx < len(DOMAINE_TIERS) else None

    items = [v2_title("🏰  Domaine — Grand Œuvre du serveur")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Tout le monde contribue à un monument commun. Un objectif collectif qui grandit avec vous."))
    lines = [f"🏆 **Palier actuel : {cur_label}**", f"📊 **Contribution totale : `{pts:,}`** points"]
    if nxt:
        # TASK C.3 : OBJECTIF ALLIANCE VISIBLE — barre de progression vers le
        # prochain palier de construction débloquable.
        lo = DOMAINE_TIERS[tier_idx - 1][0] if tier_idx > 0 else 0
        bar = _progress_bar(pts, lo, nxt[0])
        lines.append(f"➡️ Prochain : **{nxt[1]}** à `{nxt[0]:,}` (`{nxt[0]-pts:,}` restants)")
        if bar:
            lines.append(bar)
    else:
        lines.append("🌟 **Merveille atteinte — le serveur est entré dans la légende !**")
    items.append(v2_body("\n".join(lines)))
    items.append(v2_body("\n".join(
        f"{'✅' if pts >= th else '🔒'} {lbl} _(≥{th:,})_" for th, lbl in DOMAINE_TIERS)))
    items.append(v2_divider())
    items.append(v2_body(
        f"{ECLATS_EMOJI} **Tes Éclats :** `{eclats:,}`\n"
        f"-# 🌿 Pas assez d'Éclats ? Récolte ton **Jardin** chaque jour pour en gagner."))
    items.append(discord.ui.ActionRow(
        Button(label=f"🤝 Contribuer ({_DOMAINE_GIVE} ✨)", style=discord.ButtonStyle.success,
               custom_id="cite:domaine:give"),
    ))
    items.append(_retour_row())

    class _Domaine(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x455A64))

    return _Domaine()


async def _domaine(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if args and args[0] == "give":
        status = await _domaine_give(gid, uid)
    await _nav(i, await build_domaine_panel(i, status))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE K (helpers) — Maîtrise (cumul à vie, jamais remis à zéro)
# ═══════════════════════════════════════════════════════════════════════════════
async def get_mastery(gid: int, uid: int) -> int:
    if _get_db is None:
        return 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT points FROM citadelle_mastery WHERE guild_id=? AND user_id=?",
                (int(gid), int(uid))) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


async def grant_mastery(gid: int, uid: int, n: int) -> None:
    if _get_db is None or not n:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT INTO citadelle_mastery (guild_id, user_id, points) VALUES (?,?,?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET points = MAX(0, points + ?)",
                (int(gid), int(uid), int(n), int(n)))
            await db.commit()
    except Exception as ex:
        print(f"[citadelle grant_mastery] {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE J — Revenus passifs (rente quotidienne) + Marché du Vendeur (matériaux ↔ Éclats)
# ═══════════════════════════════════════════════════════════════════════════════
_RENTE_COOLDOWN = 72000.0   # ~20 h


async def _rente_collect(gid: int, uid: int) -> str:
    now = datetime.now(timezone.utc).timestamp()
    worked = False
    try:
        async with _get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO citadelle_rente (guild_id, user_id, last) VALUES (?,?,0)",
                (int(gid), int(uid)))
            cur = await db.execute(
                "UPDATE citadelle_rente SET last = ? "
                "WHERE guild_id=? AND user_id=? AND (? - last) >= ?",
                (now, int(gid), int(uid), now, _RENTE_COOLDOWN))
            await db.commit()
            worked = getattr(cur, "rowcount", 0) == 1
    except Exception as ex:
        print(f"[citadelle _rente_collect] {ex}")
        return "❌ Erreur, réessaie."
    if not worked:
        return "🌙 Rente déjà perçue aujourd'hui — reviens demain."
    sanctu = len(await owned_cosmetics(gid, uid, "sanctuaire_module"))
    titles = len(await owned_cosmetics(gid, uid, "title"))
    base = 15 + sanctu * 2 + titles * 5
    # Phase 268 : perk passif doux du familier équipé (additif, plafonné, Éclats).
    pet_bonus, pet_label = await _pet_rente_extra(gid, uid)
    gain = base + pet_bonus
    await award(gid, uid, eclats=gain)
    detail = f"sanctuaire {sanctu}, titres {titles}"
    if pet_bonus:
        detail += f", familier +{pet_bonus}"
    return f"💰 Rente perçue : **+{gain} {ECLATS_EMOJI}** ({detail})."


async def build_revenus_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    now = datetime.now(timezone.utc).timestamp()
    sanctu = len(await owned_cosmetics(gid, uid, "sanctuaire_module"))
    titles = len(await owned_cosmetics(gid, uid, "title"))
    base = 15 + sanctu * 2 + titles * 5
    # Phase 268 : perk passif doux du familier équipé (additif, plafonné).
    pet_bonus, pet_label = await _pet_rente_extra(gid, uid)
    gain = base + pet_bonus
    ready = True
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT last FROM citadelle_rente WHERE guild_id=? AND user_id=?",
                (int(gid), int(uid))) as cur:
                row = await cur.fetchone()
        last = float(row[0]) if row else 0.0
        ready = (now - last) >= _RENTE_COOLDOWN
        remain_h = max(0, int((_RENTE_COOLDOWN - (now - last)) // 3600) + 1)
    except Exception:
        remain_h = 0

    items = [v2_title("💰  Revenus Passifs")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Être fidèle paie : ta rente grandit avec ton Sanctuaire, tes titres et ton familier."))
    pet_line = (
        f"\n🐾 Familier : {pet_label} (+{pet_bonus})" if pet_bonus and pet_label
        else "\n🐾 Familier : _aucun bonus — équipe un familier (rareté = bonus)_"
    )
    items.append(v2_body(
        f"🏯 Sanctuaire : `{sanctu}` (+{sanctu*2})  ·  🏷️ Titres : `{titles}` (+{titles*5})"
        + pet_line + "\n"
        f"**💵 Rente du jour : `{gain}` {ECLATS_EMOJI}**\n"
        + ("✅ **Disponible !**" if ready else f"🌙 Prochaine dans ~`{remain_h}h`")
    ))
    items.append(v2_divider())
    items.append(discord.ui.ActionRow(
        Button(label="💰 Percevoir ma rente",
               style=discord.ButtonStyle.success if ready else discord.ButtonStyle.secondary,
               custom_id="cite:revenus:collect"),
    ))
    items.append(_retour_row())

    class _Rev(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x2E7D32))

    return _Rev()


async def _revenus(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if args and args[0] == "collect":
        status = await _rente_collect(gid, uid)
    await _nav(i, await build_revenus_panel(i, status))


def _market_day_rate() -> int:
    try:
        seed = int(datetime.now(timezone.utc).strftime("%Y%m%d"))
    except Exception:
        seed = 0
    return 3 + (seed % 4)   # 3 à 6 Éclats / matériau, change chaque jour


_MARKET_BUY_COST = 30


async def _market_sell_all(gid: int, uid: int) -> str:
    rate = _market_day_rate()
    total = 0
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT COALESCE(SUM(qty),0) FROM citadelle_materials "
                "WHERE guild_id=? AND user_id=? AND qty>0", (int(gid), int(uid))) as cur:
                row = await cur.fetchone()
            total = int(row[0]) if row else 0
            if total <= 0:
                return "📦 Tu n'as aucun matériau à vendre."
            # Phase 263 : DELETE ATOMIQUE — on ne crédite QUE si ce DELETE a vraiment
            # retiré des lignes (rowcount>0). Un 2e appel concurrent (double-clic) voit
            # rowcount=0 (inventaire déjà vidé par le 1er) → AUCUN double-crédit.
            _dc = await db.execute(
                "DELETE FROM citadelle_materials WHERE guild_id=? AND user_id=? AND qty>0",
                (int(gid), int(uid)))
            _deleted = getattr(_dc, "rowcount", 0) or 0
            await db.commit()
    except Exception as ex:
        print(f"[citadelle _market_sell_all] {ex}")
        return "❌ Erreur, réessaie."
    if _deleted <= 0:
        return "📦 Tu n'as aucun matériau à vendre."
    gain = total * rate
    await grant_eclats(gid, uid, gain)
    return f"💰 Vendu `{total}` matériaux × `{rate}` = **+{gain} {ECLATS_EMOJI}** !"


async def _market_buy(gid: int, uid: int) -> str:
    if not await spend_eclats(gid, uid, _MARKET_BUY_COST):
        bal = await get_eclats(gid, uid)
        return f"❌ Il te faut `{_MARKET_BUY_COST}` {ECLATS_EMOJI} (tu as `{bal}`)."
    got = {}
    for _ in range(3):
        mk = random.choice([v[2] for v in PROFESSIONS.values()])
        await grant_material(gid, uid, mk, 1)
        got[mk] = got.get(mk, 0) + 1
    desc = ", ".join(f"{q} {k}" for k, q in got.items())
    return f"🛒 Lot acheté : {desc} (−{_MARKET_BUY_COST} {ECLATS_EMOJI})."


async def build_marche_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    eclats = await get_eclats(gid, uid)
    mats = await get_materials(gid, uid)
    total = sum(mats.values()) if mats else 0
    rate = _market_day_rate()

    items = [v2_title("🛒  Marché du Vendeur")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Échange avec le vendeur (jamais entre joueurs). Le cours change chaque jour."))
    items.append(v2_body(
        f"📈 **Cours du jour : `{rate}` {ECLATS_EMOJI} / matériau**\n"
        f"🧱 Tes matériaux : `{total}`  ·  {ECLATS_EMOJI} `{eclats:,}`"
    ))
    items.append(v2_divider())
    items.append(discord.ui.ActionRow(
        Button(label=f"💰 Tout vendre (×{rate})", style=discord.ButtonStyle.success,
               custom_id="cite:marche:sell"),
        Button(label=f"🛒 Acheter un lot ({_MARKET_BUY_COST} ✨)", style=discord.ButtonStyle.primary,
               custom_id="cite:marche:buy"),
    ))
    items.append(_retour_row())

    class _Marche(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0x00897B))

    return _Marche()


async def _marche(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if args and args[0] == "sell":
        status = await _market_sell_all(gid, uid)
    elif args and args[0] == "buy":
        status = await _market_buy(gid, uid)
    await _nav(i, await build_marche_panel(i, status))


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE K — Maîtrises (rangs à vie) + Panthéon (classement) + Rivalités (mises)
# ═══════════════════════════════════════════════════════════════════════════════
MASTERY_TIERS = [
    (500,   "🔰", "Initié de la Cité",  "m_inite"),
    (2000,  "⚜️", "Artisan de la Cité", "m_artisan"),
    (6000,  "💠", "Maître de la Cité",   "m_maitre"),
    (15000, "👑", "Grand Maître",        "m_grandmaitre"),
    (40000, "🌌", "Légende de la Cité",  "m_legende"),
]
# Les titres de maîtrise s'affichent aussi sur la Carte.
CITE_TITLES.update({tk: (em, nm) for _th, em, nm, tk in MASTERY_TIERS})


async def _sync_mastery_titles(gid: int, uid: int, points: int) -> None:
    for th, _em, _nm, tk in MASTERY_TIERS:
        if points >= th:
            await grant_cosmetic(gid, uid, "title", tk)


async def build_maitrises_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    pts = await get_mastery(gid, uid)
    await _sync_mastery_titles(gid, uid, pts)
    rank_idx = sum(1 for th, *_ in MASTERY_TIERS if pts >= th)
    rank_label = f"{MASTERY_TIERS[rank_idx-1][1]} {MASTERY_TIERS[rank_idx-1][2]}" if rank_idx > 0 else "🌱 Novice"
    nxt = MASTERY_TIERS[rank_idx] if rank_idx < len(MASTERY_TIERS) else None

    items = [v2_title("🏆  Maîtrises de la Cité")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Cumul à vie — jamais remis à zéro. Chaque palier débloque un titre permanent."))
    line = f"**Rang : {rank_label}**  ·  Points de maîtrise : `{pts:,}`"
    if nxt:
        line += f"\n➡️ Prochain : **{nxt[1]} {nxt[2]}** à `{nxt[0]:,}` (`{nxt[0]-pts:,}` restants)"
    else:
        line += "\n🌌 **Maîtrise ultime atteinte — tu es une Légende !**"
    items.append(v2_body(line))
    items.append(v2_body("\n".join(
        f"{'✅' if pts >= th else '🔒'} {em} **{nm}** _(≥{th:,})_" for th, em, nm, _tk in MASTERY_TIERS)))
    items.append(v2_divider())
    items.append(discord.ui.ActionRow(
        Button(label="🏷️ Afficher mon plus haut titre", style=discord.ButtonStyle.primary,
               custom_id="cite:maitrises:show"),
    ))
    items.append(_retour_row())

    class _Mait(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0xD4AF37))

    return _Mait()


async def _maitrises(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if args and args[0] == "show":
        owned = set(await owned_cosmetics(gid, uid, "title"))
        chosen = None
        for th, _em, _nm, tk in reversed(MASTERY_TIERS):
            if tk in owned:
                chosen = tk
                break
        if chosen:
            await set_active(gid, uid, "cite_title", chosen)
            te, tl = CITE_TITLES.get(chosen, ("🏷️", "Titre"))
            status = f"🏷️ Titre **{te} {tl}** affiché sur ta carte !"
        else:
            status = "🔒 Atteins un palier de maîtrise pour débloquer un titre."
    await _nav(i, await build_maitrises_panel(i, status))


async def build_pantheon_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    rows = []
    try:
        async with _get_db() as db:
            async with db.execute(
                "SELECT user_id, points FROM citadelle_mastery "
                "WHERE guild_id=? AND points>0 ORDER BY points DESC LIMIT 10",
                (int(gid),)) as cur:
                rows = await cur.fetchall()
    except Exception:
        rows = []
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, (ruid, pts) in enumerate(rows):
        m = i.guild.get_member(int(ruid))
        nm = m.display_name if m else f"Joueur {ruid}"
        mark = medals[idx] if idx < 3 else f"`#{idx+1}`"
        lines.append(f"{mark} **{nm}** — `{int(pts):,}` pts")
    body = "\n".join(lines) if lines else "_Personne au Panthéon pour l'instant — sois le premier !_"
    me_pts = await get_mastery(gid, uid)

    items = [v2_title("🏛️  Panthéon de la Cité")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Les plus grands bâtisseurs du serveur, par maîtrise totale."))
    items.append(v2_body(body))
    items.append(v2_divider())
    items.append(v2_body(f"⭐ **Toi :** `{me_pts:,}` points de maîtrise"))
    items.append(_retour_row())

    class _Panth(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0xB8860B))

    return _Panth()


async def _pantheon(i: discord.Interaction, args: list):
    await _nav(i, await build_pantheon_panel(i))


_RIVAL_BETS = (20, 50, 100)


async def _rivalites_bet(gid: int, uid: int, amount: int) -> str:
    if amount not in _RIVAL_BETS:
        return "❓ Mise invalide."
    if not await spend_eclats(gid, uid, amount):
        bal = await get_eclats(gid, uid)
        return f"❌ Il te faut `{amount}` {ECLATS_EMOJI} (tu as `{bal}`)."
    if random.random() < 0.5:
        await grant_eclats(gid, uid, amount * 2)
        return f"🎉 **GAGNÉ !** Mise doublée → +`{amount}` {ECLATS_EMOJI} net !"
    return f"💀 **Perdu...** la mise de `{amount}` {ECLATS_EMOJI} est cédée. Retente ta chance !"


async def build_rivalites_panel(i: discord.Interaction, status: str | None = None):
    LayoutView = _v2.get("LayoutView")
    v2_title = _v2.get("title"); v2_subtitle = _v2.get("subtitle"); v2_body = _v2.get("body")
    v2_divider = _v2.get("divider"); v2_container = _v2.get("container")
    if not all((LayoutView, v2_title, v2_subtitle, v2_body, v2_divider, v2_container)):
        return None
    gid, uid = i.guild.id, i.user.id
    eclats = await get_eclats(gid, uid)

    items = [v2_title("⚔️  Rivalités & Mises")]
    if status:
        items.append(v2_body(status))
    items.append(v2_subtitle("Le Défi de la Cité : mise des Éclats, 50 % de chance de doubler. 100 % volontaire."))
    items.append(v2_body(
        f"{ECLATS_EMOJI} **Tes Éclats :** `{eclats:,}`\n"
        f"-# Choisis ta mise. Gagne = ×2 · Perds = la mise est cédée. (Duels joueur-contre-joueur : bientôt.)"
    ))
    items.append(v2_divider())
    items.append(discord.ui.ActionRow(*[
        Button(label=f"🎲 Miser {b} ✨", style=discord.ButtonStyle.danger,
               custom_id=f"cite:rivalites:bet:{b}")
        for b in _RIVAL_BETS
    ]))
    items.append(_retour_row())

    class _Rival(LayoutView):
        def __init__(self):
            super().__init__(timeout=600)
            self.add_item(v2_container(*items, color=0xC0392B))

    return _Rival()


async def _rivalites(i: discord.Interaction, args: list):
    gid, uid = i.guild.id, i.user.id
    status = None
    if len(args) >= 2 and args[0] == "bet":
        try:
            amount = int(args[1])
        except Exception:
            amount = 0
        status = await _rivalites_bet(gid, uid, amount)
    await _nav(i, await build_rivalites_panel(i, status))


# Registre des salles OUVERTES — TOUTES ouvertes (Phases A→K). 🎉
_SECTION_HANDLERS = {
    "forge": _forge,
    "carte": _carte,
    "emblemes": _emblemes,
    "passe": _passe,
    "sanctuaire": _sanctuaire,
    "metiers": _metiers,
    "collections": _collections,
    "jardin": _jardin,
    "domaine": _domaine,
    "revenus": _revenus,
    "marche": _marche,
    "maitrises": _maitrises,
    "pantheon": _pantheon,
    "rivalites": _rivalites,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  Bouton persistant unique : capte TOUS les `cite:<section>` (menu + entrée)
# ═══════════════════════════════════════════════════════════════════════════════
class CitadelleButton(discord.ui.DynamicItem[Button], template=r"cite:(?P<rest>.+)"):
    """Capte TOUT `cite:<rest>` (menu + sous-actions) → un seul item persistant."""

    def __init__(self, rest: str):
        super().__init__(
            Button(label="Cité", style=discord.ButtonStyle.secondary,
                   custom_id=f"cite:{rest}")
        )
        self.rest = rest

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["rest"])

    async def callback(self, i: discord.Interaction):
        try:
            await _route(i, self.rest)
        except Exception as ex:
            print(f"[CitadelleButton callback] {ex}")
            try:
                if not i.response.is_done():
                    await i.response.send_message("❌ Erreur, réessaie.", ephemeral=True)
                else:
                    await i.followup.send("❌ Erreur, réessaie.", ephemeral=True)
            except Exception:
                pass


def register_persistent_views(bot):
    """Enregistre le DynamicItem (survit aux reboots). Appelé au boot."""
    try:
        bot.add_dynamic_items(CitadelleButton)
    except Exception as ex:
        print(f"[citadelle register_persistent_views] {ex}")
