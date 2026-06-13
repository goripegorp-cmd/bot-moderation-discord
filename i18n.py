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
}


def lang_choice_label(lang) -> str:
    """Libellé prêt à l'emploi pour un menu de choix de langue : « 🇫🇷 Français ».
    FAIL-SAFE : code brut si inconnu."""
    l = normalize_lang(lang)
    flag = LANG_FLAGS.get(l, "")
    label = LANG_LABELS.get(l, l)
    return f"{flag} {label}".strip()
