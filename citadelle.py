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

import discord
from discord.ui import Button

# ─── Dépendances injectées au boot (setup) ─────────────────────────────────────
_get_db = None          # async context manager : async with _get_db() as db
_add_coins = None        # callback optionnel (non utilisé au socle)
_v2 = {}                 # helpers Components V2 (title/subtitle/body/divider/container/LayoutView)

ECLATS_EMOJI = "✨"
ECLATS_NAME = "Éclats de Création"


def setup(get_db_fn, v2_helpers: dict | None = None, add_coins_fn=None):
    """Injecte les dépendances. Appelé une fois dans on_ready (bot.py)."""
    global _get_db, _v2, _add_coins
    _get_db = get_db_fn
    _v2 = dict(v2_helpers or {})
    _add_coins = add_coins_fn


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
    """Débit ATOMIQUE conditionnel (FAIL-CLOSED) : True seulement si le solde suffisait."""
    if _get_db is None or amount <= 0:
        return False
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
        for mk, q in (materials or {}).items():
            await grant_material(guild_id, user_id, mk, q)
    except Exception as ex:
        print(f"[citadelle award] {ex}")


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
        v2_title("🏛️  LA CITÉ"),
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


# Registre des salles OUVERTES (les autres → teaser). On le remplit phase par phase.
_SECTION_HANDLERS = {
    "forge": _forge,
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
