"""i18n.py — Socle d'internationalisation (Lot 1, autonome, FAIL-SAFE).

Serveur MULTI-GAMING francophone INTERNATIONAL : on prépare le bot à parler 6
langues sans jamais rien casser. Ce module est le SOCLE — il n'affiche rien tout
seul, il expose une API que les lots suivants (boutons, hub, entraide, accueil…)
viendront brancher progressivement.

Principes NON NÉGOCIABLES (contrainte owner) :
- FAIL-SAFE TOTAL : la moindre erreur i18n → repli silencieux sur le FRANÇAIS.
  Jamais de crash, jamais de KeyError, jamais une UI qui « disparaît » parce
  qu'une traduction manque. Une clé inconnue renvoie la clé elle-même.
- ZÉRO nouvelle slash command : tout passe par cette API (les boutons/hub des
  lots suivants l'appelleront). Ce module n'enregistre aucune commande.
- Module AUTONOME : dépendances injectées via setup() (même patron que
  activity_system / seasonal_titles). La CI ne voit pas les NameError runtime →
  tout est défensif.

API exposée (résumé) :
  Constantes : SUPPORTED_LANGS, LANG_LABELS, LANG_FLAGS, DEFAULT_LANG, CATALOG
  Langue     : normalize_lang(loc) · t(key, lang, **kw)
  Préférence : set_user_lang(user_id, lang) · get_user_lang(user_id)
  Résolution : lang_of(user_id=None, interaction=None, guild_id=None)
  Serveur    : get_server_languages(cfg_dict_or_guild_id) [+ set, async]
  Boot       : setup(...) · init_db()
"""

from __future__ import annotations

# ─── Dépendances injectées (calque activity_system) ───
_get_db = None      # context manager DB : async with _get_db() as db:
_cfg = None         # coroutine cfg(gid) -> dict de config par-guilde
_db_set = None      # coroutine db_set(gid, key, val) -> bool

# ─── Langues supportées ───
DEFAULT_LANG = "fr"
SUPPORTED_LANGS = ("fr", "en", "es", "de", "it", "pt")

LANG_LABELS = {
    "fr": "Français",
    "en": "English",
    "es": "Español",
    "de": "Deutsch",
    "it": "Italiano",
    "pt": "Português",
}

LANG_FLAGS = {
    "fr": "🇫🇷",
    "en": "🇬🇧",
    "es": "🇪🇸",
    "de": "🇩🇪",
    "it": "🇮🇹",
    "pt": "🇵🇹",
}

# Langues officielles par défaut d'un serveur (I5). Le serveur est francophone
# international → FR + EN par défaut, l'owner pourra étendre via cfg plus tard.
DEFAULT_SERVER_LANGS = ["fr", "en"]
SERVER_LANGS_KEY = "server_languages"  # clé cfg par-guilde

# Mapping locale Discord (« en-US », « pt-BR », « es-ES »…) → code supporté.
# Discord envoie des locales BCP-47 ; on ne garde que la racine + quelques alias.
_LOCALE_ALIASES = {
    "en": "en", "en-us": "en", "en-gb": "en",
    "fr": "fr",
    "es": "es", "es-es": "es", "es-419": "es",
    "de": "de",
    "it": "it",
    "pt": "pt", "pt-br": "pt", "pt-pt": "pt",
}


# ═══════════════════════════════════════════════════════════════════════════
#  LANGUE — normalisation & traduction
# ═══════════════════════════════════════════════════════════════════════════

def normalize_lang(loc) -> str:
    """Mappe une locale Discord / un code arbitraire vers un code supporté.

    Accepte « en-US », « pt-BR », un discord.Locale, None… FAIL-SAFE : toute
    valeur non reconnue → DEFAULT_LANG (fr). Jamais d'exception."""
    try:
        if loc is None:
            return DEFAULT_LANG
        s = str(getattr(loc, "value", loc) or "").strip().lower()
        if not s:
            return DEFAULT_LANG
        if s in SUPPORTED_LANGS:
            return s
        if s in _LOCALE_ALIASES:
            return _LOCALE_ALIASES[s]
        # « xx-YY » inconnu → tente la racine « xx »
        root = s.split("-", 1)[0]
        if root in SUPPORTED_LANGS:
            return root
        return _LOCALE_ALIASES.get(root, DEFAULT_LANG)
    except Exception:
        return DEFAULT_LANG


def t(key, lang=None, **kw) -> str:
    """Traduit `key` dans `lang`, avec formatage **kw tolérant.

    Repli en cascade (FAIL-SAFE) :
      1. langue demandée manquante pour cette clé → FR
      2. clé totalement absente du catalogue   → renvoie la clé brute (jamais crash)
      3. erreur de str.format (placeholder absent) → renvoie le gabarit non formaté
    Aucune exception ne sort jamais de cette fonction."""
    try:
        lang = normalize_lang(lang)
        entry = CATALOG.get(key)
        if entry is None:
            return str(key)  # clé inconnue → la clé elle-même (jamais crash)
        template = entry.get(lang)
        if template is None:
            template = entry.get(DEFAULT_LANG)
        if template is None:
            # entrée présente mais ni lang ni FR → 1re valeur dispo, sinon la clé
            template = next(iter(entry.values()), None) or str(key)
        if not kw:
            return template
        try:
            return template.format(**kw)
        except Exception:
            return template  # placeholder manquant → gabarit brut, jamais crash
    except Exception:
        return str(key)


# ═══════════════════════════════════════════════════════════════════════════
#  PRÉFÉRENCE DE LANGUE PAR MEMBRE (table globale par user)
# ═══════════════════════════════════════════════════════════════════════════
# Globale (pas par-guilde) : un membre qui traverse plusieurs serveurs garde sa
# langue. Cache mémoire pour éviter un hit DB à chaque résolution.
_user_lang_cache: dict = {}   # user_id(int) -> lang(str)  ;  marqueur None = "pas de préf"


def setup(get_db_fn=None, *, cfg_fn=None, db_set_fn=None):
    """Injecte les dépendances (toutes optionnelles, calque activity_system).

    - get_db_fn : context manager DB (pour la table user_language).
    - cfg_fn    : coroutine cfg(gid) (lecture des langues officielles serveur).
    - db_set_fn : coroutine db_set(gid, key, val) (écriture langues officielles).
    Le module reste fonctionnel même sans DB : t()/normalize_lang() marchent
    toujours, seules les préférences persistées sont désactivées."""
    global _get_db, _cfg, _db_set
    if get_db_fn is not None:
        _get_db = get_db_fn
    if cfg_fn is not None:
        _cfg = cfg_fn
    if db_set_fn is not None:
        _db_set = db_set_fn


async def init_db():
    """Crée la table de préférences (CREATE IF NOT EXISTS) et amorce le cache.
    À appeler au boot (on_ready), après setup(). FAIL-SAFE."""
    if _get_db is None:
        return
    try:
        async with _get_db() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS user_language ("
                "user_id INTEGER PRIMARY KEY, lang TEXT)"
            )
            await db.commit()
            # Amorce le cache (table minuscule : 1 ligne / membre ayant choisi).
            async with db.execute("SELECT user_id, lang FROM user_language") as cur:
                for uid, lang in await cur.fetchall():
                    if lang in SUPPORTED_LANGS:
                        _user_lang_cache[int(uid)] = lang
    except Exception as ex:
        print(f"[i18n init_db] {ex}")


async def set_user_lang(user_id, lang) -> bool:
    """UPSERT la langue préférée d'un membre. Valide vs SUPPORTED_LANGS.
    Retourne True si écrit. FAIL-SAFE : False sur langue invalide / erreur DB."""
    try:
        lang = normalize_lang(lang)
        if lang not in SUPPORTED_LANGS:
            return False
        uid = int(user_id)
        if _get_db is not None:
            async with _get_db() as db:
                await db.execute(
                    "INSERT INTO user_language (user_id, lang) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET lang=?",
                    (uid, lang, lang),
                )
                await db.commit()
        _user_lang_cache[uid] = lang  # cache à jour même si DB indispo
        return True
    except Exception as ex:
        print(f"[i18n set_user_lang] {ex}")
        return False


async def get_user_lang(user_id):
    """Langue préférée d'un membre, ou None si non définie. FAIL-SAFE : None."""
    try:
        uid = int(user_id)
        if uid in _user_lang_cache:
            return _user_lang_cache[uid]
        if _get_db is None:
            return None
        async with _get_db() as db:
            async with db.execute(
                "SELECT lang FROM user_language WHERE user_id=?", (uid,)
            ) as cur:
                row = await cur.fetchone()
        lang = (row[0] if row else None)
        if lang in SUPPORTED_LANGS:
            _user_lang_cache[uid] = lang
            return lang
        return None
    except Exception as ex:
        print(f"[i18n get_user_lang] {ex}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  LANGUES OFFICIELLES DU SERVEUR (I5) — pour les posts publics multilingues
# ═══════════════════════════════════════════════════════════════════════════

def get_server_languages(cfg_dict_or_guild_id) -> list:
    """Liste des langues officielles d'un serveur (défaut DEFAULT_SERVER_LANGS).

    Accepte SOIT un dict de config déjà chargé (cfg(gid)), SOIT un guild_id (int)
    — dans ce dernier cas, lecture SYNCHRONE impossible donc on renvoie le défaut
    (les appelants async doivent passer le dict cfg). FAIL-SAFE : toujours une
    liste non vide de codes supportés."""
    try:
        cfg_dict = cfg_dict_or_guild_id
        if not isinstance(cfg_dict, dict):
            # On nous a passé un guild_id (ou autre) sans dict → défaut sûr.
            return list(DEFAULT_SERVER_LANGS)
        raw = cfg_dict.get(SERVER_LANGS_KEY)
        if not isinstance(raw, (list, tuple)) or not raw:
            return list(DEFAULT_SERVER_LANGS)
        langs = [l for l in (normalize_lang(x) for x in raw) if l in SUPPORTED_LANGS]
        # dédoublonne en gardant l'ordre
        seen, out = set(), []
        for l in langs:
            if l not in seen:
                seen.add(l)
                out.append(l)
        return out or list(DEFAULT_SERVER_LANGS)
    except Exception:
        return list(DEFAULT_SERVER_LANGS)


async def get_server_languages_async(guild_id) -> list:
    """Variante async : charge cfg(gid) puis délègue à get_server_languages.
    FAIL-SAFE : DEFAULT_SERVER_LANGS si cfg indispo / erreur."""
    try:
        if _cfg is None:
            return list(DEFAULT_SERVER_LANGS)
        c = await _cfg(int(guild_id))
        return get_server_languages(c if isinstance(c, dict) else {})
    except Exception:
        return list(DEFAULT_SERVER_LANGS)


async def set_server_languages(guild_id, langs) -> bool:
    """Écrit la liste des langues officielles du serveur (validée/dédoublonnée).
    FAIL-SAFE : False si db_set indispo / aucune langue valide / erreur."""
    try:
        if _db_set is None:
            return False
        clean, seen = [], set()
        for x in (langs or []):
            l = normalize_lang(x)
            if l in SUPPORTED_LANGS and l not in seen:
                seen.add(l)
                clean.append(l)
        if not clean:
            return False
        return bool(await _db_set(int(guild_id), SERVER_LANGS_KEY, clean))
    except Exception as ex:
        print(f"[i18n set_server_languages] {ex}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  RÉSOLUTION DE LA LANGUE À UTILISER
# ═══════════════════════════════════════════════════════════════════════════

async def lang_of(user_id=None, interaction=None, guild_id=None) -> str:
    """Résout la langue à utiliser pour un membre/contexte donné.

    Cascade (1er disponible gagne) :
      (a) préférence explicite du membre (table user_language) ;
      (b) sinon, locale Discord de l'interaction (interaction.locale normalisée) ;
      (c) sinon, 1re langue officielle du serveur (cfg server_languages) ;
      (d) sinon, fr.
    FAIL-SAFE TOTAL → fr en cas de pépin à n'importe quelle étape."""
    try:
        # (a) préférence membre
        uid = user_id
        if uid is None and interaction is not None:
            try:
                uid = getattr(getattr(interaction, "user", None), "id", None)
            except Exception:
                uid = None
        if uid is not None:
            pref = await get_user_lang(uid)
            if pref:
                return pref

        # (b) locale Discord de l'interaction
        if interaction is not None:
            try:
                loc = getattr(interaction, "locale", None)
                if loc:
                    return normalize_lang(loc)
            except Exception:
                pass

        # (c) 1re langue officielle du serveur
        gid = guild_id
        if gid is None and interaction is not None:
            try:
                gid = getattr(getattr(interaction, "guild", None), "id", None)
                if gid is None:
                    gid = getattr(interaction, "guild_id", None)
            except Exception:
                gid = None
        if gid is not None:
            langs = await get_server_languages_async(gid)
            if langs:
                return langs[0]

        # (d) repli ultime
        return DEFAULT_LANG
    except Exception:
        return DEFAULT_LANG


# ═══════════════════════════════════════════════════════════════════════════
#  CATALOGUE — clés HAUT-TRAFIC traduites dans les 6 langues
# ═══════════════════════════════════════════════════════════════════════════
# Convention : { "clé": { "fr":…, "en":…, "es":…, "de":…, "it":…, "pt":… } }.
# Toute clé manquante → t() renvoie la clé ; toute langue manquante → repli FR.
# Les placeholders {x} sont communs aux 6 langues (str.format tolérant côté t()).
CATALOG = {
    # ─── Boutons communs ───
    "btn.close": {
        "fr": "Fermer", "en": "Close", "es": "Cerrar",
        "de": "Schließen", "it": "Chiudi", "pt": "Fechar",
    },
    "btn.back": {
        "fr": "Retour", "en": "Back", "es": "Volver",
        "de": "Zurück", "it": "Indietro", "pt": "Voltar",
    },
    "btn.next": {
        "fr": "Suivant", "en": "Next", "es": "Siguiente",
        "de": "Weiter", "it": "Avanti", "pt": "Próximo",
    },
    "btn.previous": {
        "fr": "Précédent", "en": "Previous", "es": "Anterior",
        "de": "Vorherige", "it": "Precedente", "pt": "Anterior",
    },
    "btn.cancel": {
        "fr": "Annuler", "en": "Cancel", "es": "Cancelar",
        "de": "Abbrechen", "it": "Annulla", "pt": "Cancelar",
    },
    "btn.confirm": {
        "fr": "Confirmer", "en": "Confirm", "es": "Confirmar",
        "de": "Bestätigen", "it": "Conferma", "pt": "Confirmar",
    },
    "btn.open": {
        "fr": "Ouvrir", "en": "Open", "es": "Abrir",
        "de": "Öffnen", "it": "Apri", "pt": "Abrir",
    },
    "btn.save": {
        "fr": "Sauvegarder", "en": "Save", "es": "Guardar",
        "de": "Speichern", "it": "Salva", "pt": "Salvar",
    },
    "btn.refresh": {
        "fr": "Actualiser", "en": "Refresh", "es": "Actualizar",
        "de": "Aktualisieren", "it": "Aggiorna", "pt": "Atualizar",
    },
    "btn.details": {
        "fr": "Détails", "en": "Details", "es": "Detalles",
        "de": "Details", "it": "Dettagli", "pt": "Detalhes",
    },
    "btn.join": {
        "fr": "Rejoindre", "en": "Join", "es": "Unirse",
        "de": "Beitreten", "it": "Partecipa", "pt": "Entrar",
    },

    # ─── Statuts / messages génériques ───
    "common.loading": {
        "fr": "Chargement…", "en": "Loading…", "es": "Cargando…",
        "de": "Wird geladen…", "it": "Caricamento…", "pt": "Carregando…",
    },
    "common.error": {
        "fr": "Une erreur est survenue.", "en": "An error occurred.",
        "es": "Se produjo un error.", "de": "Ein Fehler ist aufgetreten.",
        "it": "Si è verificato un errore.", "pt": "Ocorreu um erro.",
    },
    "common.done": {
        "fr": "Terminé", "en": "Done", "es": "Hecho",
        "de": "Fertig", "it": "Fatto", "pt": "Concluído",
    },
    "common.enabled": {
        "fr": "Activé", "en": "Enabled", "es": "Activado",
        "de": "Aktiviert", "it": "Attivato", "pt": "Ativado",
    },
    "common.disabled": {
        "fr": "Désactivé", "en": "Disabled", "es": "Desactivado",
        "de": "Deaktiviert", "it": "Disattivato", "pt": "Desativado",
    },
    "common.not_permitted": {
        "fr": "Tu n'as pas la permission de faire ça.",
        "en": "You don't have permission to do that.",
        "es": "No tienes permiso para hacer eso.",
        "de": "Dazu hast du keine Berechtigung.",
        "it": "Non hai il permesso per farlo.",
        "pt": "Você não tem permissão para fazer isso.",
    },
    "common.timeout": {
        "fr": "Délai expiré. Recommence.", "en": "Timed out. Try again.",
        "es": "Tiempo agotado. Inténtalo de nuevo.",
        "de": "Zeit abgelaufen. Versuch es erneut.",
        "it": "Tempo scaduto. Riprova.", "pt": "Tempo esgotado. Tente novamente.",
    },

    # ─── Choix de langue ───
    "lang.choose": {
        "fr": "Choisis ta langue", "en": "Choose your language",
        "es": "Elige tu idioma", "de": "Wähle deine Sprache",
        "it": "Scegli la tua lingua", "pt": "Escolha o seu idioma",
    },
    "lang.changed": {
        "fr": "Langue définie : {lang}", "en": "Language set: {lang}",
        "es": "Idioma definido: {lang}", "de": "Sprache festgelegt: {lang}",
        "it": "Lingua impostata: {lang}", "pt": "Idioma definido: {lang}",
    },

    # ─── Hub / catégories ───
    "hub.title": {
        "fr": "Accueil", "en": "Home", "es": "Inicio",
        "de": "Startseite", "it": "Home", "pt": "Início",
    },
    "hub.subtitle": {
        "fr": "Choisis une catégorie", "en": "Choose a category",
        "es": "Elige una categoría", "de": "Wähle eine Kategorie",
        "it": "Scegli una categoria", "pt": "Escolha uma categoria",
    },
    "hub.category.games": {
        "fr": "Jeux", "en": "Games", "es": "Juegos",
        "de": "Spiele", "it": "Giochi", "pt": "Jogos",
    },
    "hub.category.community": {
        "fr": "Communauté", "en": "Community", "es": "Comunidad",
        "de": "Community", "it": "Comunità", "pt": "Comunidade",
    },
    "hub.category.events": {
        "fr": "Événements", "en": "Events", "es": "Eventos",
        "de": "Events", "it": "Eventi", "pt": "Eventos",
    },
    "hub.category.help": {
        "fr": "Aide", "en": "Help", "es": "Ayuda",
        "de": "Hilfe", "it": "Aiuto", "pt": "Ajuda",
    },
    # Hub V2 — titre/sous-titre du panneau d'engagement (haut-trafic /hub)
    "hub.v2.title": {
        "fr": "Ton Hub d'engagement", "en": "Your engagement Hub",
        "es": "Tu Hub de participación", "de": "Dein Engagement-Hub",
        "it": "Il tuo Hub di coinvolgimento", "pt": "Seu Hub de engajamento",
    },
    "hub.v2.subtitle_default": {
        "fr": "Choisis une catégorie — tout est en 1 clic",
        "en": "Pick a category — everything is one click away",
        "es": "Elige una categoría — todo a un clic",
        "de": "Wähle eine Kategorie — alles ist nur einen Klick entfernt",
        "it": "Scegli una categoria — tutto a un clic",
        "pt": "Escolha uma categoria — tudo a um clique",
    },
    # Hub V2 — les 6 catégories (titre + sous-titre court)
    "hub.cat.jeu.title": {
        "fr": "Jeu & Quotidien", "en": "Play & Daily",
        "es": "Juego y Diario", "de": "Spiel & Alltag",
        "it": "Gioco & Quotidiano", "pt": "Jogo & Diário",
    },
    "hub.cat.jeu.sub": {
        "fr": "Quêtes · Daily Wheel · Rencontre du jour · Roblox",
        "en": "Quests · Daily Wheel · Daily encounter · Roblox",
        "es": "Misiones · Ruleta diaria · Encuentro del día · Roblox",
        "de": "Quests · Daily Wheel · Begegnung des Tages · Roblox",
        "it": "Missioni · Daily Wheel · Incontro del giorno · Roblox",
        "pt": "Missões · Roleta diária · Encontro do dia · Roblox",
    },
    "hub.cat.combat.title": {
        "fr": "Combat & Compétitions", "en": "Combat & Competitions",
        "es": "Combate y Competiciones", "de": "Kampf & Wettbewerbe",
        "it": "Combattimento & Competizioni", "pt": "Combate & Competições",
    },
    "hub.cat.combat.sub": {
        "fr": "Bingo · Prédictions · Faction Wars · Donjon · Solo",
        "en": "Bingo · Predictions · Faction Wars · Dungeon · Solo",
        "es": "Bingo · Predicciones · Guerras de facción · Mazmorra · Solo",
        "de": "Bingo · Vorhersagen · Faction Wars · Dungeon · Solo",
        "it": "Bingo · Pronostici · Faction Wars · Dungeon · Solo",
        "pt": "Bingo · Previsões · Guerras de facção · Masmorra · Solo",
    },
    "hub.cat.eco.title": {
        "fr": "Économie & Inventaire", "en": "Economy & Inventory",
        "es": "Economía e Inventario", "de": "Wirtschaft & Inventar",
        "it": "Economia & Inventario", "pt": "Economia & Inventário",
    },
    "hub.cat.eco.sub": {
        "fr": "Outils · Banque · Loots · La Cité · Loterie",
        "en": "Tools · Bank · Loot · The City · Lottery",
        "es": "Herramientas · Banco · Botín · La Ciudad · Lotería",
        "de": "Werkzeuge · Bank · Loot · Die Stadt · Lotterie",
        "it": "Strumenti · Banca · Loot · La Città · Lotteria",
        "pt": "Ferramentas · Banco · Loot · A Cidade · Loteria",
    },
    "hub.cat.social.title": {
        "fr": "Social & Communauté", "en": "Social & Community",
        "es": "Social y Comunidad", "de": "Sozial & Community",
        "it": "Social & Comunità", "pt": "Social & Comunidade",
    },
    "hub.cat.social.sub": {
        "fr": "Shoutouts · Réputation · Objectif · Streams · Anniv · Confession",
        "en": "Shoutouts · Reputation · Goal · Streams · Birthdays · Confession",
        "es": "Menciones · Reputación · Objetivo · Streams · Cumpleaños · Confesión",
        "de": "Shoutouts · Ruf · Ziel · Streams · Geburtstage · Beichte",
        "it": "Shoutout · Reputazione · Obiettivo · Stream · Compleanni · Confessione",
        "pt": "Shoutouts · Reputação · Objetivo · Streams · Aniversários · Confissão",
    },
    "hub.cat.prog.title": {
        "fr": "Progression & Stats", "en": "Progress & Stats",
        "es": "Progreso y Estadísticas", "de": "Fortschritt & Statistiken",
        "it": "Progressi & Statistiche", "pt": "Progresso & Estatísticas",
    },
    "hub.cat.prog.sub": {
        "fr": "Profil · Hauts faits · Compagnon · Récap 7j · Pulse",
        "en": "Profile · Achievements · Companion · 7-day recap · Pulse",
        "es": "Perfil · Logros · Compañero · Resumen 7 días · Pulse",
        "de": "Profil · Erfolge · Begleiter · 7-Tage-Rückblick · Pulse",
        "it": "Profilo · Imprese · Compagno · Riepilogo 7g · Pulse",
        "pt": "Perfil · Conquistas · Companheiro · Resumo 7 dias · Pulse",
    },
    "hub.cat.aide.title": {
        "fr": "Récit & Aide", "en": "Story & Help",
        "es": "Relato y Ayuda", "de": "Story & Hilfe",
        "it": "Storia & Aiuto", "pt": "História & Ajuda",
    },
    "hub.cat.aide.sub": {
        "fr": "Saga · Chronique · Histoire · Mission · FAQ · Notifs · DMs",
        "en": "Saga · Chronicle · Story · Mission · FAQ · Notifs · DMs",
        "es": "Saga · Crónica · Historia · Misión · FAQ · Notifs · MD",
        "de": "Saga · Chronik · Geschichte · Mission · FAQ · Infos · DMs",
        "it": "Saga · Cronaca · Storia · Missione · FAQ · Notifiche · DM",
        "pt": "Saga · Crônica · História · Missão · FAQ · Notifs · DMs",
    },
    # Verbe « Ouvrir » du bouton accessory de chaque catégorie
    "hub.cat.open": {
        "fr": "Ouvrir", "en": "Open", "es": "Abrir",
        "de": "Öffnen", "it": "Apri", "pt": "Abrir",
    },
    # Bouton langue top-level (reste bilingue dans le libellé pour être universel)
    "hub.btn.language": {
        "fr": "Langue / Language", "en": "Language / Langue",
        "es": "Idioma / Language", "de": "Sprache / Language",
        "it": "Lingua / Language", "pt": "Idioma / Language",
    },
    "hub.btn.back": {
        "fr": "Retour au hub", "en": "Back to hub",
        "es": "Volver al hub", "de": "Zurück zum Hub",
        "it": "Torna al hub", "pt": "Voltar ao hub",
    },

    # ─── Entraide ───
    "entraide.title": {
        "fr": "Entraide", "en": "Mutual help", "es": "Ayuda mutua",
        "de": "Gegenseitige Hilfe", "it": "Aiuto reciproco", "pt": "Ajuda mútua",
    },
    "entraide.need_help": {
        "fr": "Besoin d'aide", "en": "Need help", "es": "Necesito ayuda",
        "de": "Brauche Hilfe", "it": "Ho bisogno di aiuto", "pt": "Preciso de ajuda",
    },
    "entraide.can_help": {
        "fr": "Je peux aider", "en": "I can help", "es": "Puedo ayudar",
        "de": "Ich kann helfen", "it": "Posso aiutare", "pt": "Posso ajudar",
    },
    "entraide.open_requests": {
        "fr": "Demandes en cours", "en": "Open requests", "es": "Solicitudes abiertas",
        "de": "Offene Anfragen", "it": "Richieste in corso", "pt": "Pedidos em aberto",
    },
    "entraide.find_help": {
        "fr": "Trouver de l'aide", "en": "Find help", "es": "Buscar ayuda",
        "de": "Hilfe finden", "it": "Trova aiuto", "pt": "Encontrar ajuda",
    },
    "entraide.helper_role": {
        "fr": "Aidant", "en": "Helper", "es": "Ayudante",
        "de": "Helfer", "it": "Aiutante", "pt": "Ajudante",
    },
    # Panneau Entraide V2 (éphémère, haut-trafic)
    "entraide.v2.title": {
        "fr": "Entraide multi-gaming", "en": "Multi-gaming mutual help",
        "es": "Ayuda mutua multi-gaming", "de": "Multi-Gaming-Hilfe",
        "it": "Aiuto reciproco multi-gaming", "pt": "Ajuda mútua multi-gaming",
    },
    "entraide.v2.subtitle": {
        "fr": "Besoin d'aide sur un jeu ? Ou envie d'aider ? Tout est ici.",
        "en": "Need help with a game? Or want to help? It's all here.",
        "es": "¿Necesitas ayuda con un juego? ¿O quieres ayudar? Todo está aquí.",
        "de": "Brauchst du Hilfe bei einem Spiel? Oder willst du helfen? Alles hier.",
        "it": "Hai bisogno di aiuto in un gioco? O vuoi aiutare? È tutto qui.",
        "pt": "Precisa de ajuda num jogo? Ou quer ajudar? Está tudo aqui.",
    },
    "entraide.v2.body": {
        "fr": "Demande de l'aide, propose la tienne, ou parcours les demandes en cours.",
        "en": "Ask for help, offer yours, or browse open requests.",
        "es": "Pide ayuda, ofrece la tuya o explora las solicitudes abiertas.",
        "de": "Bitte um Hilfe, biete deine an oder durchsuche offene Anfragen.",
        "it": "Chiedi aiuto, offri il tuo o sfoglia le richieste in corso.",
        "pt": "Peça ajuda, ofereça a sua ou veja os pedidos em aberto.",
    },
    "entraide.btn.need": {
        "fr": "J'ai besoin d'aide", "en": "I need help",
        "es": "Necesito ayuda", "de": "Ich brauche Hilfe",
        "it": "Ho bisogno di aiuto", "pt": "Preciso de ajuda",
    },
    "entraide.btn.help": {
        "fr": "Je peux aider", "en": "I can help",
        "es": "Puedo ayudar", "de": "Ich kann helfen",
        "it": "Posso aiutare", "pt": "Posso ajudar",
    },
    "entraide.btn.list": {
        "fr": "Demandes en cours", "en": "Open requests",
        "es": "Solicitudes abiertas", "de": "Offene Anfragen",
        "it": "Richieste in corso", "pt": "Pedidos em aberto",
    },
    "entraide.btn.top": {
        "fr": "Top aidants", "en": "Top helpers",
        "es": "Mejores ayudantes", "de": "Top-Helfer",
        "it": "Migliori aiutanti", "pt": "Melhores ajudantes",
    },
    "entraide.reputation": {
        "fr": "Ta réputation : {count} aide(s) apportée(s) à la communauté. Merci ! 💛",
        "en": "Your reputation: {count} help(s) given to the community. Thank you! 💛",
        "es": "Tu reputación: {count} ayuda(s) aportada(s) a la comunidad. ¡Gracias! 💛",
        "de": "Dein Ruf: {count} Hilfe(n) für die Community geleistet. Danke! 💛",
        "it": "La tua reputazione: {count} aiuto(i) dato(i) alla comunità. Grazie! 💛",
        "pt": "Sua reputação: {count} ajuda(s) dada(s) à comunidade. Obrigado! 💛",
    },

    # ─── Accueil ───
    "welcome.greeting": {
        "fr": "Bienvenue {user} !", "en": "Welcome {user}!",
        "es": "¡Bienvenido {user}!", "de": "Willkommen {user}!",
        "it": "Benvenuto {user}!", "pt": "Bem-vindo {user}!",
    },
    "welcome.member_count": {
        "fr": "Nous sommes maintenant {count} membres.",
        "en": "We are now {count} members.",
        "es": "Ahora somos {count} miembros.",
        "de": "Wir sind jetzt {count} Mitglieder.",
        "it": "Ora siamo {count} membri.",
        "pt": "Agora somos {count} membros.",
    },
    # En-tête « 👋 Bienvenue » de l'embed d'accueil (author name)
    "welcome.author": {
        "fr": "Bienvenue", "en": "Welcome", "es": "Bienvenido",
        "de": "Willkommen", "it": "Benvenuto", "pt": "Bem-vindo",
    },
    # Ligne par défaut (fallback) si l'owner n'a PAS configuré welcome_message.
    # {user} = mention, {guild} = nom serveur, {count} = nb de membres.
    "welcome.default_line": {
        "fr": "Bienvenue {user} ! Nous sommes maintenant {count} membres sur {guild}. 🎉",
        "en": "Welcome {user}! We are now {count} members on {guild}. 🎉",
        "es": "¡Bienvenido {user}! Ahora somos {count} miembros en {guild}. 🎉",
        "de": "Willkommen {user}! Wir sind jetzt {count} Mitglieder auf {guild}. 🎉",
        "it": "Benvenuto {user}! Ora siamo {count} membri su {guild}. 🎉",
        "pt": "Bem-vindo {user}! Agora somos {count} membros em {guild}. 🎉",
    },
    # Renvoi vers le salon d'entraide (ajouté sous l'accueil si configuré).
    # {channel} = mention du salon (<#id>).
    "welcome.entraide_hint": {
        "fr": "🆘 Besoin d'aide sur un jeu ? → {channel}",
        "en": "🆘 Need help with a game? → {channel}",
        "es": "🆘 ¿Necesitas ayuda con un juego? → {channel}",
        "de": "🆘 Brauchst du Hilfe bei einem Spiel? → {channel}",
        "it": "🆘 Hai bisogno di aiuto in un gioco? → {channel}",
        "pt": "🆘 Precisa de ajuda num jogo? → {channel}",
    },
    # Accueil onboarding events (poste quand welcome_message n'est PAS configuré).
    # {user} = mention.
    "welcome.onboarding_line": {
        "fr": "👋 Bienvenue {user} ! Sois **actif** (chat ou vocal) pour débloquer les "
              "**événements** et gagner loot & familiers — tout est dans `/hub`.",
        "en": "👋 Welcome {user}! Be **active** (chat or voice) to unlock **events** "
              "and earn loot & pets — everything is in `/hub`.",
        "es": "👋 ¡Bienvenido {user}! Sé **activo** (chat o voz) para desbloquear "
              "**eventos** y ganar botín y mascotas — todo está en `/hub`.",
        "de": "👋 Willkommen {user}! Sei **aktiv** (Chat oder Voice), um **Events** "
              "freizuschalten und Loot & Begleiter zu verdienen — alles in `/hub`.",
        "it": "👋 Benvenuto {user}! Sii **attivo** (chat o vocale) per sbloccare gli "
              "**eventi** e ottenere loot e familiari — tutto è in `/hub`.",
        "pt": "👋 Bem-vindo {user}! Seja **ativo** (chat ou voz) para desbloquear "
              "**eventos** e ganhar loot e mascotes — tudo está em `/hub`.",
    },

    # ─── Libellés génériques d'events ───
    "event.starts_in": {
        "fr": "Commence dans {time}", "en": "Starts in {time}",
        "es": "Comienza en {time}", "de": "Beginnt in {time}",
        "it": "Inizia tra {time}", "pt": "Começa em {time}",
    },
    "event.in_progress": {
        "fr": "En cours", "en": "In progress", "es": "En curso",
        "de": "Läuft", "it": "In corso", "pt": "Em andamento",
    },
    "event.ended": {
        "fr": "Terminé", "en": "Ended", "es": "Finalizado",
        "de": "Beendet", "it": "Terminato", "pt": "Encerrado",
    },
    "event.participate": {
        "fr": "Participer", "en": "Participate", "es": "Participar",
        "de": "Teilnehmen", "it": "Partecipa", "pt": "Participar",
    },
    "event.rewards": {
        "fr": "Récompenses", "en": "Rewards", "es": "Recompensas",
        "de": "Belohnungen", "it": "Ricompense", "pt": "Recompensas",
    },

    # ─── I4 — Entraide cross-langue (drapeau/langue du demandeur sur le post) ───
    # {lang} = nom de la langue dans CETTE langue (ex. « espagnol »). Suffixé au post
    # de demande : un aidant de la même langue sait qu'il peut aider. COMPACT.
    "entraide.speaks": {
        "fr": "parle {lang}", "en": "speaks {lang}", "es": "habla {lang}",
        "de": "spricht {lang}", "it": "parla {lang}", "pt": "fala {lang}",
    },
    # Noms de langues fléchis pour « parle … » (génitif/accusatif simple selon langue).
    "lang.name.fr": {
        "fr": "français", "en": "French", "es": "francés",
        "de": "Französisch", "it": "francese", "pt": "francês",
    },
    "lang.name.en": {
        "fr": "anglais", "en": "English", "es": "inglés",
        "de": "Englisch", "it": "inglese", "pt": "inglês",
    },
    "lang.name.es": {
        "fr": "espagnol", "en": "Spanish", "es": "español",
        "de": "Spanisch", "it": "spagnolo", "pt": "espanhol",
    },
    "lang.name.de": {
        "fr": "allemand", "en": "German", "es": "alemán",
        "de": "Deutsch", "it": "tedesco", "pt": "alemão",
    },
    "lang.name.it": {
        "fr": "italien", "en": "Italian", "es": "italiano",
        "de": "Italienisch", "it": "italiano", "pt": "italiano",
    },
    "lang.name.pt": {
        "fr": "portugais", "en": "Portuguese", "es": "portugués",
        "de": "Portugiesisch", "it": "portoghese", "pt": "português",
    },

    # ─── I3 — Posts publics multilingues (LIGNE D'ACCROCHE uniquement, compacte) ───
    # Accroche de l'écho d'event en salon chatty (sous l'emoji+label déjà rendu).
    # {channel} = mention du salon d'event (<#id>).
    "echo.join_invite": {
        "fr": "➡️ Rejoins-nous dans {channel} pour participer !",
        "en": "➡️ Join us in {channel} to take part!",
        "es": "➡️ ¡Únete a nosotros en {channel} para participar!",
        "de": "➡️ Mach mit in {channel}!",
        "it": "➡️ Unisciti a noi in {channel} per partecipare!",
        "pt": "➡️ Junta-te a nós em {channel} para participar!",
    },
    # Accroche du « Programme du jour ».
    "agenda.lead": {
        "fr": "Voici les rendez-vous combat d'aujourd'hui — prépare ton stuff et sois là. 💪",
        "en": "Here are today's combat events — gear up and be there. 💪",
        "es": "Estos son los combates de hoy — prepárate y no faltes. 💪",
        "de": "Das sind die heutigen Kämpfe — rüste dich und sei dabei. 💪",
        "it": "Ecco i combattimenti di oggi — preparati e ci sei. 💪",
        "pt": "Estes são os combates de hoje — prepara-te e marca presença. 💪",
    },
    # Accroche du « Héraut de la Semaine ».
    "herald.lead": {
        "fr": "Le tour d'horizon de la semaine — tout ce qui t'attend, en un seul message. 📯",
        "en": "Your week at a glance — everything ahead, in one message. 📯",
        "es": "Tu semana de un vistazo — todo lo que viene, en un solo mensaje. 📯",
        "de": "Deine Woche im Überblick — alles, was kommt, in einer Nachricht. 📯",
        "it": "La tua settimana in sintesi — tutto ciò che ti aspetta, in un solo messaggio. 📯",
        "pt": "A tua semana num relance — tudo o que vem aí, numa só mensagem. 📯",
    },
}


def lang_choice_label(lang) -> str:
    """Libellé prêt à l'emploi pour un menu de choix de langue : « 🇫🇷 Français ».
    FAIL-SAFE : code brut si inconnu."""
    l = normalize_lang(lang)
    flag = LANG_FLAGS.get(l, "")
    label = LANG_LABELS.get(l, l)
    return f"{flag} {label}".strip()
