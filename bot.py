try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput, Button
import aiosqlite, os, re, json, asyncio, unicodedata, io, time, aiohttp, hashlib, secrets
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')  # Backend non-interactif
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from collections import defaultdict
from functools import wraps

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
DB_PATH = '/data/bot.db' if os.path.exists('/data') else 'bot.db'
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}
voice_join_tracker = {}  # {(guild_id, user_id): datetime} - pour tracker le temps en vocal

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚡ SYSTÈME DE CACHE OPTIMISÉ
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigCache:
    """Cache LRU avec TTL pour les configurations - évite les appels DB répétitifs"""
    
    def __init__(self, max_size=100, ttl_seconds=30):
        self._cache = {}  # {guild_id: (data, timestamp)}
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
    
    def get(self, guild_id):
        """Récupère depuis le cache si valide"""
        if guild_id in self._cache:
            data, ts = self._cache[guild_id]
            if time.time() - ts < self._ttl:
                return data
            else:
                del self._cache[guild_id]
        return None
    
    def set(self, guild_id, data):
        """Stocke dans le cache"""
        # Nettoyage LRU si trop gros
        if len(self._cache) >= self._max_size:
            # Supprimer les plus anciens
            oldest = sorted(self._cache.items(), key=lambda x: x[1][1])[:self._max_size // 4]
            for gid, _ in oldest:
                del self._cache[gid]
        
        self._cache[guild_id] = (data.copy(), time.time())
    
    def invalidate(self, guild_id):
        """Invalide le cache pour un serveur"""
        if guild_id in self._cache:
            del self._cache[guild_id]
    
    def clear(self):
        """Vide tout le cache"""
        self._cache.clear()

# Instance globale du cache
_config_cache = ConfigCache(max_size=200, ttl_seconds=30)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚡ SYSTÈME D'INTERACTION OPTIMISÉ
# ═══════════════════════════════════════════════════════════════════════════════

def safe_callback(func):
    """Décorateur pour protéger les callbacks d'interaction"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except discord.errors.InteractionResponded:
            pass  # Déjà répondu
        except discord.errors.NotFound:
            pass  # Interaction expirée
        except discord.errors.HTTPException as e:
            if e.code == 10062:  # Unknown interaction
                pass
            else:
                print(f"[CALLBACK HTTP ERROR] {func.__name__}: {e}")
        except Exception as ex:
            print(f"[CALLBACK ERROR] {func.__name__}: {ex}")
            # Essayer de répondre avec une erreur
            try:
                i = args[1] if len(args) > 1 else kwargs.get('i') or kwargs.get('interaction')
                if i and not i.response.is_done():
                    await i.response.send_message("❌ Erreur, réessayez.", ephemeral=True)
            except:
                pass
    return wrapper

async def safe_respond(interaction, **kwargs):
    """Répond à une interaction de manière sécurisée - évite les erreurs de timeout"""
    try:
        if interaction.response.is_done():
            try:
                await interaction.edit_original_response(**kwargs)
            except:
                try:
                    await interaction.followup.send(**kwargs, ephemeral=True)
                except:
                    pass
        else:
            await interaction.response.edit_message(**kwargs)
    except discord.errors.InteractionResponded:
        try:
            await interaction.edit_original_response(**kwargs)
        except:
            pass
    except discord.errors.NotFound:
        pass
    except discord.errors.HTTPException as e:
        if e.code != 10062:
            print(f"[SAFE_RESPOND] HTTP Error: {e}")
    except Exception as ex:
        print(f"[SAFE_RESPOND] Erreur: {ex}")

async def safe_defer(interaction, ephemeral=False):
    """Defer une interaction de manière sécurisée"""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
            return True
    except:
        pass
    return False

async def safe_send_message(interaction, content=None, embed=None, view=None, ephemeral=True):
    """Envoie un message de manière sécurisée"""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, view=view, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content=content, embed=embed, view=view, ephemeral=ephemeral)
    except:
        pass

async def safe_edit(interaction, **kwargs):
    """Modifie un message de manière sécurisée"""
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs)
        else:
            await interaction.response.edit_message(**kwargs)
    except discord.errors.InteractionResponded:
        try:
            await interaction.edit_original_response(**kwargs)
        except:
            pass
    except:
        pass

class SafeView(View):
    """View optimisée avec gestion d'erreur automatique"""
    
    def __init__(self, user, guild, timeout=300):
        super().__init__(timeout=timeout)
        self.u = user
        self.g = guild
        self._error_count = 0
    
    async def on_error(self, interaction, error, item):
        """Gestion centralisée des erreurs"""
        self._error_count += 1
        print(f"[VIEW ERROR] {self.__class__.__name__}: {error}")
        
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Une erreur est survenue. Réessayez.",
                    ephemeral=True
                )
        except:
            pass
    
    async def on_timeout(self):
        """Nettoyage lors du timeout"""
        pass
    
    async def interaction_check(self, interaction) -> bool:
        """Vérifie que l'utilisateur est autorisé"""
        # Seul l'utilisateur qui a ouvert le menu peut interagir
        if interaction.user.id != self.u.id:
            try:
                await interaction.response.send_message(
                    "❌ Vous ne pouvez pas utiliser ce menu.",
                    ephemeral=True
                )
            except:
                pass
            return False
        return True

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔒 SYSTÈME DE SÉCURITÉ
# ═══════════════════════════════════════════════════════════════════════════════

class Security:
    """Système de sécurité centralisé pour le bot"""
    
    # Rate limiting par utilisateur
    _rate_limits = {}  # {user_id: {action: [timestamps]}}
    _blocked_users = set()  # Utilisateurs temporairement bloqués
    _security_logs = []  # Logs de sécurité
    
    # Configuration des limites
    RATE_LIMITS = {
        'command': (10, 60),      # 10 commandes par 60 secondes
        'button': (20, 60),       # 20 clics par 60 secondes
        'modal': (5, 60),         # 5 modals par 60 secondes
        'api_call': (30, 60),     # 30 appels API par 60 secondes
    }
    
    # Patterns dangereux à bloquer
    DANGEROUS_PATTERNS = [
        r'(?i)eval\s*\(',
        r'(?i)exec\s*\(',
        r'(?i)__import__',
        r'(?i)subprocess',
        r'(?i)os\.system',
        r'(?i)import\s+os',
        r'<script',
        r'javascript:',
        r'data:text/html',
        r'(?i)on\w+\s*=',  # Event handlers HTML
    ]
    
    @classmethod
    def sanitize_input(cls, text: str, max_length: int = 2000) -> str:
        """Nettoie et valide les entrées utilisateur"""
        if not text:
            return ""
        
        # Limiter la longueur
        text = str(text)[:max_length]
        
        # Supprimer les caractères de contrôle (sauf newlines et tabs)
        text = ''.join(c for c in text if c.isprintable() or c in '\n\t')
        
        # Échapper les mentions dangereuses
        text = text.replace('@everyone', '@\u200beveryone')
        text = text.replace('@here', '@\u200bhere')
        
        return text.strip()
    
    @classmethod
    def validate_url(cls, url: str) -> bool:
        """Valide une URL"""
        if not url:
            return True  # URL optionnelle
        
        # Pattern URL basique sécurisé
        url_pattern = r'^https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+$'
        if not re.match(url_pattern, url):
            return False
        
        # Bloquer les schemes dangereux
        dangerous = ['javascript:', 'data:', 'vbscript:', 'file:']
        if any(url.lower().startswith(d) for d in dangerous):
            return False
        
        return len(url) <= 2000
    
    @classmethod
    def check_dangerous_content(cls, text: str) -> bool:
        """Vérifie si le texte contient du contenu dangereux"""
        if not text:
            return False
        
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, text):
                return True
        return False
    
    @classmethod
    async def check_rate_limit(cls, user_id: int, action: str = 'command') -> bool:
        """Vérifie si l'utilisateur dépasse le rate limit. Retourne True si bloqué."""
        if user_id in cls._blocked_users:
            return True
        
        now_ts = time.time()
        limit, window = cls.RATE_LIMITS.get(action, (10, 60))
        
        if user_id not in cls._rate_limits:
            cls._rate_limits[user_id] = {}
        
        if action not in cls._rate_limits[user_id]:
            cls._rate_limits[user_id][action] = []
        
        # Nettoyer les vieux timestamps
        cls._rate_limits[user_id][action] = [
            ts for ts in cls._rate_limits[user_id][action]
            if now_ts - ts < window
        ]
        
        # Vérifier la limite
        if len(cls._rate_limits[user_id][action]) >= limit:
            cls._log_security(f"RATE_LIMIT: User {user_id} exceeded {action} limit")
            return True
        
        cls._rate_limits[user_id][action].append(now_ts)
        return False
    
    @classmethod
    def _log_security(cls, message: str):
        """Log un événement de sécurité"""
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = f"[{timestamp}] {message}"
        cls._security_logs.append(log_entry)
        
        # Garder seulement les 1000 derniers logs
        if len(cls._security_logs) > 1000:
            cls._security_logs = cls._security_logs[-1000:]
        
        print(f"🔒 SECURITY: {message}")
    
    @classmethod
    def validate_snowflake(cls, value) -> bool:
        """Valide un Discord Snowflake ID"""
        try:
            snowflake = int(value)
            # Discord Snowflakes sont >= 2^22 (environ 4194304)
            return 4194304 <= snowflake <= 9223372036854775807
        except (ValueError, TypeError):
            return False
    
    @classmethod
    def hash_sensitive_data(cls, data: str) -> str:
        """Hash des données sensibles pour les logs"""
        return hashlib.sha256(data.encode()).hexdigest()[:16]

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22; GOLD=0xFFD700

# Références aux nouvelles bases de données (définies dans PROTS section)
PHISHING = []  # Sera remplacé par PHISHING_DOMAINS après la définition
SCAM_PATTERNS = []  # Sera remplacé après la définition
LEET = {'a':['@','4'],'e':['3','€'],'i':['1','!'],'o':['0'],'s':['$','5'],'t':['7']}

def now(): return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔒 SÉCURITÉ AVANCÉE
# ═══════════════════════════════════════════════════════════════════════════════

import hashlib
import secrets

# Rate limiting pour prévenir les abus
rate_limits = {}  # {(guild_id, user_id, action): [timestamps]}
RATE_LIMITS_CONFIG = {
    'command': {'max': 10, 'window': 60},  # 10 commandes par minute
    'message': {'max': 30, 'window': 60},  # 30 messages par minute
    'button': {'max': 20, 'window': 60},   # 20 clics par minute
    'api_call': {'max': 50, 'window': 60}, # 50 appels API par minute
}

# Blacklist temporaire des utilisateurs suspects
security_blacklist = {}  # {user_id: {'until': datetime, 'reason': str}}

# Cache des tentatives de sécurité
security_attempts = {}  # {user_id: {'attempts': int, 'last': datetime}}

def check_rate_limit(guild_id, user_id, action='command'):
    """Vérifie si un utilisateur dépasse la limite de rate"""
    key = (guild_id, user_id, action)
    current = now()
    config = RATE_LIMITS_CONFIG.get(action, {'max': 10, 'window': 60})
    
    if key not in rate_limits:
        rate_limits[key] = []
    
    # Nettoyer les anciennes entrées
    rate_limits[key] = [t for t in rate_limits[key] if (current - t).total_seconds() < config['window']]
    
    # Vérifier la limite
    if len(rate_limits[key]) >= config['max']:
        return False  # Limite atteinte
    
    # Ajouter cette action
    rate_limits[key].append(current)
    return True

def is_blacklisted(user_id):
    """Vérifie si un utilisateur est temporairement blacklisté"""
    if user_id in security_blacklist:
        if security_blacklist[user_id]['until'] > now():
            return True, security_blacklist[user_id]['reason']
        else:
            del security_blacklist[user_id]
    return False, None

def blacklist_user(user_id, duration_minutes, reason):
    """Blackliste temporairement un utilisateur"""
    security_blacklist[user_id] = {
        'until': now() + timedelta(minutes=duration_minutes),
        'reason': reason
    }

def sanitize_input(text, max_length=2000):
    """Nettoie et valide une entrée utilisateur"""
    if text is None:
        return ""
    
    # Convertir en string
    text = str(text)
    
    # Limiter la longueur
    if len(text) > max_length:
        text = text[:max_length]
    
    # Supprimer les caractères de contrôle dangereux
    dangerous_chars = ['\x00', '\x1a', '\x7f']
    for char in dangerous_chars:
        text = text.replace(char, '')
    
    return text

def validate_id(value):
    """Valide qu'une valeur est un ID Discord valide"""
    try:
        id_val = int(value)
        # Les IDs Discord sont des snowflakes 64-bit
        if id_val < 0 or id_val > 2**63:
            return None
        return id_val
    except (ValueError, TypeError):
        return None

def hash_sensitive_data(data):
    """Hash des données sensibles de manière sécurisée"""
    if not data:
        return None
    salt = secrets.token_hex(16)
    return hashlib.sha256(f"{salt}{data}".encode()).hexdigest()

def detect_injection_attempt(text):
    """Détecte les tentatives d'injection SQL/Code"""
    if not text:
        return False
    
    injection_patterns = [
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE|TRUNCATE)\b)",  # SQL
        r"(--|;|/\*|\*/|@@|@)",  # SQL comments/special
        r"(<script|javascript:|on\w+\s*=)",  # XSS
        r"(\$\{|\{\{|<%|%>)",  # Template injection
        r"(__import__|eval|exec|compile|open\s*\()",  # Python injection
        r"(\.\.\/|\.\.\\)",  # Path traversal
    ]
    
    text_lower = text.lower()
    for pattern in injection_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False

async def log_security_event(guild_id, user_id, action, details):
    """Enregistre un événement de sécurité dans la base de données"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO security_logs (guild_id, user_id, action, details) VALUES (?, ?, ?, ?)',
                (guild_id, user_id, sanitize_input(action, 100), sanitize_input(details, 500))
            )
            await db.commit()
    except Exception as ex:
        print(f"[SECURITY LOG ERROR] {ex}")

def validate_config_value(key, value):
    """Valide les valeurs de configuration"""
    # Limites de valeurs
    limits = {
        'spam_max': (1, 50),
        'spam_interval': (1, 300),
        'caps_percent': (10, 100),
        'newaccount_days': (0, 365),
        'join_threshold': (3, 100),
        'join_interval': (5, 300),
        'min_account_age': (0, 365),
    }
    
    if key in limits:
        min_val, max_val = limits[key]
        try:
            val = int(value)
            return max(min_val, min(max_val, val))
        except:
            return min_val
    
    return value

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('CREATE TABLE IF NOT EXISTS guild_config(guild_id INTEGER PRIMARY KEY, data TEXT DEFAULT "{}")')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles(guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id, role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_users(guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id, user_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_channels(guild_id INTEGER, channel_id INTEGER, PRIMARY KEY(guild_id, channel_id))')
        # Table pour les logs de sécurité
        await db.execute('''CREATE TABLE IF NOT EXISTS security_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            ip_hash TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS infractions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            mod_id INTEGER,
            type TEXT,
            reason TEXT,
            duration TEXT DEFAULT "",
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour tracker l'activité Realsy
        await db.execute('''CREATE TABLE IF NOT EXISTS realsy_tracking(
            guild_id INTEGER,
            user_id INTEGER,
            last_activity TEXT,
            warn_count INTEGER DEFAULT 0,
            PRIMARY KEY(guild_id, user_id)
        )''')
        # Table pour les suggestions
        await db.execute('''CREATE TABLE IF NOT EXISTS suggestions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour tracker l'activité des membres
        await db.execute('''CREATE TABLE IF NOT EXISTS member_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            activity_type TEXT,
            channel_id INTEGER,
            duration INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0,
            reactions INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Index pour améliorer les performances des requêtes de stats
        try:
            await db.execute('CREATE INDEX IF NOT EXISTS idx_member_activity_guild_user ON member_activity(guild_id, user_id, activity_type, created_at)')
        except:
            pass
        
        # Table pour les stats d'inactivité
        await db.execute('''CREATE TABLE IF NOT EXISTS activity_tracking (
            guild_id INTEGER,
            user_id INTEGER,
            last_message DATETIME,
            last_vocal DATETIME,
            total_messages INTEGER DEFAULT 0,
            total_vocal_time INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )''')
        # Table pour les giveaways (cadeaux)
        await db.execute('''CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            message_id INTEGER,
            title TEXT,
            description TEXT,
            prize TEXT,
            image_url TEXT,
            end_time DATETIME,
            winner_count INTEGER DEFAULT 1,
            participants TEXT DEFAULT "[]",
            conditions TEXT DEFAULT "{}",
            ended INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour les messages automatiques
        await db.execute('''CREATE TABLE IF NOT EXISTS scheduled_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            title TEXT,
            description TEXT,
            color TEXT DEFAULT "#5865F2",
            image_url TEXT,
            footer TEXT,
            frequency TEXT,
            frequency_value INTEGER DEFAULT 1,
            send_hour INTEGER DEFAULT 12,
            send_minute INTEGER DEFAULT 0,
            last_sent DATETIME,
            enabled INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'") as cur:
            if not await cur.fetchone():
                await db.execute('CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, panel_id TEXT DEFAULT "", claimed_by INTEGER DEFAULT 0, status TEXT DEFAULT "open", answers TEXT DEFAULT "{}", created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
            else:
                async with db.execute("PRAGMA table_info(tickets)") as cur2:
                    cols = [r[1] for r in await cur2.fetchall()]
                for cn, ct in [('panel_id','TEXT DEFAULT ""'),('claimed_by','INTEGER DEFAULT 0'),('status','TEXT DEFAULT "open"'),('answers','TEXT DEFAULT "{}"')]:
                    if cn not in cols:
                        try: await db.execute(f'ALTER TABLE tickets ADD COLUMN {cn} {ct}')
                        except: pass
        # Migration infractions
        async with db.execute("PRAGMA table_info(infractions)") as cur:
            cols = [r[1] for r in await cur.fetchall()]
        if 'duration' not in cols:
            try: await db.execute('ALTER TABLE infractions ADD COLUMN duration TEXT DEFAULT ""')
            except: pass
        if 'created_at' not in cols:
            try: await db.execute('ALTER TABLE infractions ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP')
            except: pass
        
        # ═══════════════ TABLES ÉCONOMIE & MINI-JEUX ═══════════════
        # Table économie des membres
        await db.execute('''CREATE TABLE IF NOT EXISTS economy (
            guild_id INTEGER,
            user_id INTEGER,
            coins INTEGER DEFAULT 0,
            bank INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_daily DATETIME,
            last_work DATETIME,
            PRIMARY KEY (guild_id, user_id)
        )''')
        
        # Table des niveaux (pour récompenses automatiques)
        await db.execute('''CREATE TABLE IF NOT EXISTS level_rewards (
            guild_id INTEGER,
            level INTEGER,
            role_id INTEGER,
            PRIMARY KEY (guild_id, level)
        )''')
        
        # Table des achats boutique (rôles temporaires)
        await db.execute('''CREATE TABLE IF NOT EXISTS shop_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            role_id INTEGER,
            expires_at DATETIME
        )''')
        
        # Ajouter colonne message_count si elle n'existe pas
        async with db.execute('PRAGMA table_info(economy)') as cursor:
            cols = [r[1] for r in await cursor.fetchall()]
        if 'message_count' not in cols:
            try: await db.execute('ALTER TABLE economy ADD COLUMN message_count INTEGER DEFAULT 0')
            except: pass
        
        # ═══════════════ TABLES DÉTECTION COMPTES SECONDAIRES ═══════════════
        # Table pour stocker les relations de comptes secondaires détectés
        await db.execute('''CREATE TABLE IF NOT EXISTS alt_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            main_account_id INTEGER,
            alt_account_id INTEGER,
            confidence INTEGER DEFAULT 0,
            reasons TEXT DEFAULT "[]",
            status TEXT DEFAULT "suspected",
            detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            action_taken TEXT DEFAULT "",
            UNIQUE(guild_id, main_account_id, alt_account_id)
        )''')
        
        # Table pour stocker les fingerprints des utilisateurs (pour détection)
        await db.execute('''CREATE TABLE IF NOT EXISTS user_fingerprints (
            guild_id INTEGER,
            user_id INTEGER,
            avatar_hash TEXT,
            username_normalized TEXT,
            created_at_ts INTEGER,
            joined_at_ts INTEGER,
            first_message_at DATETIME,
            first_message_channel INTEGER,
            behavior_hash TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, user_id)
        )''')
        
        # Table pour stocker les bans (pour détecter les contournements)
        await db.execute('''CREATE TABLE IF NOT EXISTS ban_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            username TEXT,
            avatar_hash TEXT,
            reason TEXT,
            banned_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        
        await db.commit()
    print("✅ DB OK")

async def db_get(gid):
    """Récupère la configuration d'un serveur de manière sécurisée"""
    try:
        # Valider l'ID
        gid = validate_id(gid)
        if gid is None:
            return {}
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM guild_config WHERE guild_id=?', (gid,)) as c:
                r = await c.fetchone()
                if r and r[0]:
                    try:
                        return json.loads(r[0])
                    except json.JSONDecodeError:
                        print(f"[DB] JSON invalide pour guild {gid}")
                        return {}
                return {}
    except Exception as ex:
        print(f"[DB GET ERROR] {ex}")
        return {}

async def db_set(gid, key, val):
    """Enregistre une valeur de configuration de manière sécurisée"""
    try:
        # Valider l'ID
        gid = validate_id(gid)
        if gid is None:
            return False
        
        # Valider la clé (pas d'injection)
        key = sanitize_input(str(key), 100)
        if detect_injection_attempt(key):
            print(f"[SECURITY] Tentative d'injection détectée dans la clé: {key}")
            return False
        
        # Valider certaines valeurs numériques
        val = validate_config_value(key, val)
        
        data = await db_get(gid)
        data[key] = val
        
        # Limiter la taille totale de la config
        jd = json.dumps(data, ensure_ascii=False)
        if len(jd) > 100000:  # 100KB max
            print(f"[DB] Config trop grande pour guild {gid}")
            return False
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO guild_config(guild_id, data) VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET data=?', (gid, jd, jd))
            await db.commit()
        
        # Invalider le cache après modification
        _config_cache.invalidate(gid)
        return True
    except Exception as ex:
        print(f"[DB SET ERROR] {ex}")
        return False

async def cfg(gid):
    """Récupère la configuration avec cache pour optimiser les performances"""
    # Vérifier le cache d'abord
    cached = _config_cache.get(gid)
    if cached is not None:
        return cached
    
    # Si pas en cache, récupérer de la DB
    data = await db_get(gid)
    defaults = {
        'anti_link': 0, 'anti_invite': 0, 'anti_image': 0, 'anti_phishing': 1, 'anti_scam': 1,
        'anti_spam': 0, 'anti_caps': 0, 'anti_newaccount': 0, 'anti_badwords': 0,
        'anti_raid': 0, 'anti_compromised': 1, 'anti_qrcode': 1, 'anti_alt': 0,
        'link_whitelist': [], 'image_allowed': [], 'badwords_list': [],
        'link_allowed_channels': [], 'image_allowed_channels': [],
        'phishing_action': 'ban', 'scam_action': 'mute', 'spam_action': 'mute',
        'compromised_action': 'mute', 'qrcode_action': 'mute', 'alt_action': 'kick',
        'spam_max': 5, 'spam_interval': 5, 'caps_percent': 70, 'newaccount_days': 7,
        'log_anti_link': 0, 'log_anti_image': 0, 'log_anti_phishing': 0, 'log_anti_scam': 0,
        'log_anti_spam': 0, 'log_anti_caps': 0, 'log_anti_badwords': 0, 'log_anti_invite': 0, 
        'log_anti_newaccount': 0, 'log_anti_raid': 0, 'log_anti_compromised': 0, 'log_anti_qrcode': 0,
        'log_anti_alt': 0,
        'raid_config': {'join_threshold': 10, 'join_interval': 10, 'min_account_age': 7, 'auto_mode': True, 'block_invites': True, 'action': 'kick'},
        'alt_config': {'auto_action': False, 'min_confidence': 70},
        'channel_configs': {},
        'ticket_staff': 0, 'ticket_log': 0, 'ticket_panels': {},
        'mod_warn_role': 0, 'mod_mute_role': 0, 'mod_infractions_role': 0, 'mod_log_channel': 0
    }
    for k, v in defaults.items():
        if k not in data: data[k] = v
    
    # Mettre en cache
    _config_cache.set(gid, data)
    return data

async def is_immune(m, key, channel=None):
    """
    Vérifie si un membre est immunisé contre une protection.
    Les rôles/utilisateurs immunisés ont un accès TOTAL sauf pour:
    - anti_phishing (jamais ignoré - sécurité critique)
    - anti_compromised (jamais ignoré - détection de hack)
    """
    
    # Protections CRITIQUES - JAMAIS ignorées même pour les immunisés
    # Ces protections protègent contre les comptes hackés
    critical_protections = ['anti_phishing', 'anti_compromised']
    
    if key in critical_protections:
        return False  # Personne n'est immunisé contre le phishing
    
    # Owner du serveur = toujours immunisé pour tout le reste
    if m.id == m.guild.owner_id:
        return True
    
    # Admins sont immunisés contre tout (sauf critique)
    if m.guild_permissions.administrator:
        return True
    
    # Vérifier immunité personnalisée (rôles/utilisateurs/salons)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Utilisateurs immunisés
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (m.guild.id,)) as c:
                immune_users = [r[0] for r in await c.fetchall()]
            
            # Rôles immunisés
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,)) as c:
                immune_roles = [r[0] for r in await c.fetchall()]
            
            # Salons immunisés
            if channel:
                async with db.execute('SELECT channel_id FROM immune_channels WHERE guild_id=?', (m.guild.id,)) as c:
                    immune_channels = [r[0] for r in await c.fetchall()]
                if channel.id in immune_channels:
                    return True
        
        # Vérifier si l'utilisateur est immunisé
        is_user_immune = m.id in immune_users
        is_role_immune = any(role.id in immune_roles for role in m.roles)
        
        if is_user_immune or is_role_immune:
            return True  # Immunisé = accès total (sauf protections critiques)
            
    except Exception as ex:
        print(f"[IMMUNE ERROR] {ex}")
    
    return False

async def is_fully_immune(m):
    """Vérifie si un membre a une immunité totale (pour les commandes)"""
    if m.id == m.guild.owner_id or m.guild_permissions.administrator:
        return True
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (m.guild.id,)) as c:
                immune_users = [r[0] for r in await c.fetchall()]
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,)) as c:
                immune_roles = [r[0] for r in await c.fetchall()]
        return m.id in immune_users or any(role.id in immune_roles for role in m.roles)
    except:
        return False

async def is_channel_immune(guild_id, channel_id):
    """Vérifie si un salon est immunisé"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT channel_id FROM immune_channels WHERE guild_id=? AND channel_id=?', (guild_id, channel_id)) as c:
                return await c.fetchone() is not None
    except:
        return False

async def is_ticket_channel(channel):
    """
    Vérifie si un salon est un ticket.
    Les tickets sont immunisés contre toutes les protections SAUF anti-phishing et anti-scam.
    """
    try:
        # Vérifier dans la base de données des tickets
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT id FROM tickets WHERE channel_id=? AND status="open"',
                (channel.id,)
            ) as c:
                if await c.fetchone():
                    return True
        
        # Vérifier aussi par le nom du salon (backup)
        channel_name = channel.name.lower()
        if channel_name.startswith('ticket-') or channel_name.startswith('🎫'):
            return True
            
    except:
        pass
    
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#                           📺 SÉLECTEURS PAGINÉS UNIVERSELS
# ═══════════════════════════════════════════════════════════════════════════════

class UniversalChannelSelect(View):
    """
    Sélecteur de salon universel avec pagination.
    Supporte tous les types de salons et toutes les callbacks.
    """
    def __init__(self, u, g, callback_func, return_view_func, channel_type='text', page=0, 
                 title="📺 Choisir un salon", allow_none=True, none_label="❌ Aucun", extra_data=None):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.callback_func = callback_func  # Fonction async à appeler avec (interaction, channel_id)
        self.return_view_func = return_view_func  # Fonction qui retourne la view de retour
        self.channel_type = channel_type
        self.page = page
        self.title = title
        self.allow_none = allow_none
        self.none_label = none_label
        self.extra_data = extra_data or {}
        
        # Récupérer les salons selon le type
        if channel_type == 'text':
            self.channels = list(g.text_channels)
        elif channel_type == 'voice':
            self.channels = list(g.voice_channels)
        elif channel_type == 'category':
            self.channels = list(g.categories)
        else:
            self.channels = list(g.channels)
        
        self.per_page = 23 if allow_none else 24
        self.max_page = max(0, (len(self.channels) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        self.clear_items()
        
        start = self.page * self.per_page
        end = start + self.per_page
        page_channels = self.channels[start:end]
        
        opts = []
        if self.allow_none and self.page == 0:
            opts.append(discord.SelectOption(label=self.none_label, value="0", emoji="🚫"))
        
        for ch in page_channels:
            if self.channel_type == 'voice':
                label = f"🔊 {ch.name}"[:25]
            elif self.channel_type == 'category':
                label = f"📁 {ch.name}"[:25]
            else:
                label = f"# {ch.name}"[:25]
            
            desc = ch.category.name[:50] if hasattr(ch, 'category') and ch.category else "Sans catégorie"
            opts.append(discord.SelectOption(label=label, value=str(ch.id), description=desc))
        
        if opts:
            select = UniversalChannelSelectMenu(self, opts)
            self.add_item(select)
        
        # Navigation si plusieurs pages
        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            page_btn = discord.ui.Button(label=f"{self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(page_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page), row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        self.page -= 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def next_page(self, i):
        self.page += 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def go_back(self, i):
        v = self.return_view_func()
        if hasattr(v, 'embed'):
            embed = await v.embed() if asyncio.iscoroutinefunction(v.embed) else v.embed()
            await i.response.edit_message(content=None, embed=embed, view=v)
        else:
            await i.response.edit_message(content=None, view=v)

class UniversalChannelSelectMenu(Select):
    def __init__(self, parent, opts):
        placeholder = f"Page {parent.page + 1}/{parent.max_page + 1} - {parent.title}"[:100]
        super().__init__(placeholder=placeholder, options=opts)
        self.parent = parent
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        await self.parent.callback_func(i, channel_id, self.parent.extra_data)


class UniversalRoleSelect(View):
    """
    Sélecteur de rôle universel avec pagination.
    """
    def __init__(self, u, g, callback_func, return_view_func, page=0,
                 title="🎭 Choisir un rôle", allow_none=True, none_label="❌ Aucun rôle", 
                 exclude_bots=True, extra_data=None):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.callback_func = callback_func
        self.return_view_func = return_view_func
        self.page = page
        self.title = title
        self.allow_none = allow_none
        self.none_label = none_label
        self.extra_data = extra_data or {}
        
        # Récupérer les rôles (exclure @everyone et les rôles de bot si demandé)
        if exclude_bots:
            self.roles = [r for r in g.roles[1:] if not r.is_bot_managed()]
        else:
            self.roles = list(g.roles[1:])
        
        self.per_page = 23 if allow_none else 24
        self.max_page = max(0, (len(self.roles) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        self.clear_items()
        
        start = self.page * self.per_page
        end = start + self.per_page
        page_roles = self.roles[start:end]
        
        opts = []
        if self.allow_none and self.page == 0:
            opts.append(discord.SelectOption(label=self.none_label, value="0", emoji="🚫"))
        
        for r in page_roles:
            desc = f"{len(r.members)} membres"[:50]
            opts.append(discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id), description=desc))
        
        if opts:
            select = UniversalRoleSelectMenu(self, opts)
            self.add_item(select)
        
        # Navigation
        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            page_btn = discord.ui.Button(label=f"{self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(page_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page), row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        self.page -= 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def next_page(self, i):
        self.page += 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def go_back(self, i):
        v = self.return_view_func()
        if hasattr(v, 'embed'):
            embed = await v.embed() if asyncio.iscoroutinefunction(v.embed) else v.embed()
            await i.response.edit_message(content=None, embed=embed, view=v)
        else:
            await i.response.edit_message(content=None, view=v)

class UniversalRoleSelectMenu(Select):
    def __init__(self, parent, opts):
        placeholder = f"Page {parent.page + 1}/{parent.max_page + 1} - {parent.title}"[:100]
        super().__init__(placeholder=placeholder, options=opts)
        self.parent = parent
    
    async def callback(self, i):
        role_id = int(self.values[0])
        await self.parent.callback_func(i, role_id, self.parent.extra_data)


class UniversalCategorySelect(View):
    """
    Sélecteur de catégorie universel avec pagination.
    """
    def __init__(self, u, g, callback_func, return_view_func, page=0,
                 title="📁 Choisir une catégorie", allow_none=True, none_label="❌ Aucune catégorie", extra_data=None):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.callback_func = callback_func
        self.return_view_func = return_view_func
        self.page = page
        self.title = title
        self.allow_none = allow_none
        self.none_label = none_label
        self.extra_data = extra_data or {}
        
        self.categories = list(g.categories)
        self.per_page = 23 if allow_none else 24
        self.max_page = max(0, (len(self.categories) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        self.clear_items()
        
        start = self.page * self.per_page
        end = start + self.per_page
        page_cats = self.categories[start:end]
        
        opts = []
        if self.allow_none and self.page == 0:
            opts.append(discord.SelectOption(label=self.none_label, value="0", emoji="🚫"))
        
        for cat in page_cats:
            desc = f"{len(cat.channels)} salons"[:50]
            opts.append(discord.SelectOption(label=f"📁 {cat.name}"[:25], value=str(cat.id), description=desc))
        
        if opts:
            select = UniversalCategorySelectMenu(self, opts)
            self.add_item(select)
        
        # Navigation
        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            page_btn = discord.ui.Button(label=f"{self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(page_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page), row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        self.page -= 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def next_page(self, i):
        self.page += 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def go_back(self, i):
        v = self.return_view_func()
        if hasattr(v, 'embed'):
            embed = await v.embed() if asyncio.iscoroutinefunction(v.embed) else v.embed()
            await i.response.edit_message(content=None, embed=embed, view=v)
        else:
            await i.response.edit_message(content=None, view=v)

class UniversalCategorySelectMenu(Select):
    def __init__(self, parent, opts):
        placeholder = f"Page {parent.page + 1}/{parent.max_page + 1} - {parent.title}"[:100]
        super().__init__(placeholder=placeholder, options=opts)
        self.parent = parent
    
    async def callback(self, i):
        cat_id = int(self.values[0])
        await self.parent.callback_func(i, cat_id, self.parent.extra_data)


# Ancien système gardé pour compatibilité
class PaginatedChannelSelect(View):
    """Sélecteur de salon avec pagination pour supporter plus de 25 salons"""
    def __init__(self, u, g, callback_key, return_panel_class, page=0, multi=False, current_channels=None):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.callback_key = callback_key
        self.return_panel_class = return_panel_class
        self.page = page
        self.multi = multi
        self.current_channels = list(current_channels) if current_channels else []
        self.channels = list(g.text_channels)
        self.max_page = max(0, (len(self.channels) - 1) // 23)
        
        self._build()
    
    def _build(self):
        self.clear_items()
        
        # Calculer les salons de cette page
        start = self.page * 23
        end = start + 23
        page_channels = self.channels[start:end]
        
        opts = []
        
        # Option "Aucun" seulement en mode simple
        if not self.multi and self.page == 0:
            opts.append(discord.SelectOption(label="❌ Aucun / Désactiver", value="0", emoji="❌"))
        
        for ch in page_channels:
            is_selected = ch.id in self.current_channels
            # Marquer clairement les salons sélectionnés
            if is_selected:
                label = f"✅ {ch.name}"[:25]
                emoji = "✅"
            else:
                label = f"# {ch.name}"[:25]
                emoji = "💬"
            
            desc = ch.category.name[:50] if ch.category else "Sans catégorie"
            if is_selected:
                desc = "✓ Sélectionné • " + desc
            
            opts.append(discord.SelectOption(
                label=label, 
                value=str(ch.id),
                description=desc[:50],
                emoji=emoji
            ))
        
        if opts:
            placeholder = f"Page {self.page + 1}/{self.max_page + 1}"
            if self.multi:
                placeholder += f" • {len(self.current_channels)} salon(s) sélectionné(s)"
            
            select = Select(
                placeholder=placeholder,
                options=opts,
                max_values=min(len(opts), 5) if self.multi else 1,
                min_values=0 if self.multi else 1,
                row=0
            )
            select.callback = self._on_select
            self.add_item(select)
        
        # Navigation
        if self.max_page > 0:
            prev_btn = Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
            prev_btn.callback = self._prev
            self.add_item(prev_btn)
            
            page_btn = Button(label=f"{self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(page_btn)
            
            next_btn = Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page), row=1)
            next_btn.callback = self._next
            self.add_item(next_btn)
        
        # Boutons d'action pour le mode multi
        if self.multi:
            # Bouton Valider - TOUJOURS visible
            validate_btn = Button(
                label=f"✅ Valider ({len(self.current_channels)})", 
                style=discord.ButtonStyle.success,
                row=2
            )
            validate_btn.callback = self._validate
            self.add_item(validate_btn)
            
            # Bouton Vider
            if self.current_channels:
                clear_btn = Button(label="🗑️ Tout effacer", style=discord.ButtonStyle.danger, row=2)
                clear_btn.callback = self._clear
                self.add_item(clear_btn)
        
        # Bouton retour
        back_btn = Button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
        back_btn.callback = self._back
        self.add_item(back_btn)
    
    async def _on_select(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        selected_ids = [int(v) for v in i.data.get('values', []) if v != "0"]
        
        if self.multi:
            # Mode multi : toggle chaque salon sélectionné
            for ch_id in selected_ids:
                if ch_id in self.current_channels:
                    self.current_channels.remove(ch_id)
                else:
                    self.current_channels.append(ch_id)
            
            # Rafraîchir la vue
            self._build()
            
            try:
                await i.edit_original_response(view=self)
            except:
                pass
        else:
            # Mode simple : sauvegarder directement
            value = int(i.data['values'][0]) if i.data.get('values') and i.data['values'][0] != "0" else 0
            await db_set(self.g.id, self.callback_key, value)
            
            try:
                v = self.return_panel_class(self.u, self.g)
                await i.edit_original_response(embed=await v.embed(), view=v)
            except:
                pass
    
    async def _prev(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        if self.page > 0:
            self.page -= 1
            self._build()
        
        try:
            await i.edit_original_response(view=self)
        except:
            pass
    
    async def _next(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        if self.page < self.max_page:
            self.page += 1
            self._build()
        
        try:
            await i.edit_original_response(view=self)
        except:
            pass
    
    async def _back(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        try:
            v = self.return_panel_class(self.u, self.g)
            await i.edit_original_response(embed=await v.embed(), view=v)
        except:
            pass
    
    async def _validate(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        # Sauvegarder les salons sélectionnés
        await db_set(self.g.id, self.callback_key, self.current_channels)
        
        try:
            v = self.return_panel_class(self.u, self.g)
            count = len(self.current_channels)
            content = f"✅ **{count} salon(s)** configuré(s) !" if count > 0 else "✅ Aucun salon configuré (commande désactivée)"
            await i.edit_original_response(content=content, embed=await v.embed(), view=v)
        except:
            pass
    
    async def _clear(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        self.current_channels = []
        self._build()
        
        try:
            await i.edit_original_response(view=self)
        except:
            pass

# Garder l'ancienne classe pour compatibilité mais elle n'est plus utilisée
class PaginatedChannelSelectMenu(Select):
    def __init__(self, parent_view, opts, multi=False, placeholder="Sélectionner..."):
        max_vals = min(len(opts), 10) if multi else 1
        super().__init__(placeholder=placeholder, options=opts, max_values=max_vals if multi else 1)
        self.parent_view = parent_view
        self.multi = multi
    
    async def callback(self, i):
        selected_ids = [int(v) for v in self.values if v != "0"]
        
        if self.multi:
            # Mode multi : ajouter/retirer de la liste
            for ch_id in selected_ids:
                if ch_id in self.parent_view.current_channels:
                    self.parent_view.current_channels.remove(ch_id)
                else:
                    self.parent_view.current_channels.append(ch_id)
            
            # Rafraîchir la vue
            v = PaginatedChannelSelect(
                self.parent_view.u, self.parent_view.g, 
                self.parent_view.callback_key, self.parent_view.return_panel_class,
                page=self.parent_view.page, multi=True, 
                current_channels=self.parent_view.current_channels
            )
            await i.response.edit_message(view=v)
        else:
            # Mode simple : sauvegarder directement
            value = int(self.values[0]) if self.values[0] != "0" else 0
            await db_set(self.parent_view.g.id, self.parent_view.callback_key, value)
            v = self.parent_view.return_panel_class(self.parent_view.u, self.parent_view.g)
            await i.response.edit_message(embed=await v.embed(), view=v)

async def is_fully_immune(member):
    """Vérifie si un membre est totalement immunisé (rôle ou utilisateur)"""
    if not member or not member.guild:
        return False
    
    # Owner et admins sont toujours immunisés
    if member.id == member.guild.owner_id or member.guild_permissions.administrator:
        return True
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Vérifier les rôles immunisés
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (member.guild.id,)) as c:
                immune_roles = {r[0] for r in await c.fetchall()}
            
            # Vérifier les utilisateurs immunisés
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (member.guild.id,)) as c:
                immune_users = {r[0] for r in await c.fetchall()}
        
        # Vérifier si le membre a un rôle immunisé
        if any(role.id in immune_roles for role in member.roles):
            return True
        
        # Vérifier si l'utilisateur est directement immunisé
        if member.id in immune_users:
            return True
            
    except Exception as ex:
        print(f"Erreur vérification immunité: {ex}")
    
    return False

async def sanction(m, action, dur, reason, g):
    try:
        if action == 'mute': await m.timeout(timedelta(minutes=dur), reason=reason)
        elif action == 'kick': await m.kick(reason=reason)
        elif action == 'ban': await m.ban(reason=reason)
    except: pass

async def send_log(g, key, m, msg, reason, extra=None):
    """Envoie un log détaillé dans le salon configuré"""
    try:
        c = await cfg(g.id)
        ch = g.get_channel(c.get(f'log_{key}', 0))
        if not ch: return
        
        # Couleurs par type de protection
        colors = {
            'anti_phishing': 0xFF0000,  # Rouge vif
            'anti_scam': 0xE74C3C,
            'anti_spam': 0xE67E22,
            'anti_raid': 0x9B59B6,
            'anti_compromised': 0xFF5733,
            'anti_qrcode': 0xC70039,
            'anti_link': 0x3498DB,
            'anti_invite': 0x2ECC71,
            'anti_badwords': 0xF39C12,
            'anti_caps': 0x95A5A6,
            'anti_image': 0x1ABC9C,
            'anti_newaccount': 0x9B59B6,
        }
        
        # Emojis par type
        emojis = {
            'anti_phishing': '🎣',
            'anti_scam': '🚨',
            'anti_spam': '📨',
            'anti_raid': '⚔️',
            'anti_compromised': '🔐',
            'anti_qrcode': '📱',
            'anti_link': '🔗',
            'anti_invite': '🎟️',
            'anti_badwords': '🤬',
            'anti_caps': '🔠',
            'anti_image': '🖼️',
            'anti_newaccount': '👶',
        }
        
        emoji = emojis.get(key, '🛡️')
        color = colors.get(key, C.RED)
        title = key.replace('anti_', '').upper()
        
        e = discord.Embed(
            title=f"{emoji} PROTECTION {title}",
            color=color,
            timestamp=now()
        )
        
        # Informations utilisateur détaillées
        user_info = f"**Nom:** {m.display_name}\n**Tag:** {m.name}\n**ID:** `{m.id}`"
        try:
            account_age = (now() - m.created_at.replace(tzinfo=timezone.utc)).days
            user_info += f"\n**Âge compte:** {account_age} jours"
        except:
            pass
        e.add_field(name="👤 Utilisateur", value=user_info, inline=True)
        
        # Informations salon
        if msg and msg.channel:
            channel_info = f"**Salon:** {msg.channel.mention}\n**ID:** `{msg.channel.id}`"
            e.add_field(name="📍 Localisation", value=channel_info, inline=True)
        
        # Action prise
        action_taken = c.get(f'{key.replace("anti_", "")}_action', 'mute')
        if key == 'anti_phishing':
            action_taken = c.get('phishing_action', 'ban')
        elif key == 'anti_scam':
            action_taken = c.get('scam_action', 'mute')
        elif key == 'anti_compromised':
            action_taken = c.get('compromised_action', 'mute')
        
        action_emoji = {'mute': '🔇', 'kick': '👢', 'ban': '🔨'}.get(action_taken, '⚡')
        e.add_field(name="⚡ Action", value=f"{action_emoji} {action_taken.upper()}", inline=True)
        
        # Raison détaillée
        e.add_field(name="⚠️ Raison", value=reason[:1024], inline=False)
        
        # Détails supplémentaires
        if extra:
            e.add_field(name="🔍 Détails", value=str(extra)[:1024], inline=False)
        
        # Contenu du message (censuré si trop long)
        if msg and msg.content:
            content = msg.content
            if len(content) > 500:
                content = content[:500] + "..."
            # Censurer les liens
            content = re.sub(r'https?://\S+', '[LIEN CENSURÉ]', content)
            e.add_field(name="💬 Message (censuré)", value=f"```{content}```", inline=False)
        
        # Avatar et footer
        e.set_thumbnail(url=m.display_avatar.url)
        e.set_footer(text=f"Protection {g.name} • ID: {m.id}", icon_url=g.icon.url if g.icon else None)
        
        await ch.send(embed=e)
    except Exception as ex:
        print(f"[LOG ERROR] {key}: {ex}")

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔍 CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def get_gif_type(msg):
    ct = (msg.content or "").lower()
    if 'tenor.com' in ct: return 'tenor'
    if 'giphy.com' in ct: return 'giphy'
    for emb in msg.embeds:
        if emb.url and 'tenor' in emb.url.lower(): return 'tenor'
        if emb.url and 'giphy' in emb.url.lower(): return 'giphy'
    for att in msg.attachments:
        if att.filename.lower().endswith('.gif'): return 'gif'
    return None

def normalize(t):
    t = t.lower()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    for l, vs in LEET.items():
        for v in vs: t = t.replace(v, l)
    return t

def check_badwords(ct, words):
    """Vérifie si le message contient des mots interdits (mots entiers uniquement)"""
    if not words: return False, None
    
    # Normaliser le texte
    text_lower = ct.lower()
    
    # Remplacer les caractères d'évasion courants
    evasion_map = {
        '@': 'a', '4': 'a', '0': 'o', '1': 'i', '!': 'i', '3': 'e',
        '$': 's', '5': 's', '7': 't', '*': '', '.': '', '-': '', '_': '',
        ' ': '', '|': 'i', '€': 'e', '£': 'l'
    }
    
    for word in words:
        word = word.strip().lower()
        if not word:
            continue
        
        # 1. Vérification mot entier exact (avec limites de mots)
        # \b = limite de mot (début/fin de mot)
        pattern = r'\b' + re.escape(word) + r'\b'
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True, word
        
        # 2. Vérification avec évasion (ex: c.o.n, c-o-n, c0n)
        # Nettoyer le texte des caractères d'évasion
        cleaned_text = text_lower
        for char, replacement in evasion_map.items():
            cleaned_text = cleaned_text.replace(char, replacement)
        
        # Vérifier si le mot apparaît comme mot entier dans le texte nettoyé
        # On construit un pattern qui cherche le mot avec des limites
        if re.search(r'\b' + re.escape(word) + r'\b', cleaned_text):
            return True, word
        
        # 3. Vérification du mot avec caractères séparateurs (c.o.n, c o n, c-o-n)
        # Créer un pattern qui accepte des séparateurs entre chaque lettre
        spaced_pattern = r'\b' + r'[\s.\-_*|]*'.join(re.escape(c) for c in word) + r'\b'
        if re.search(spaced_pattern, text_lower, re.IGNORECASE):
            return True, word
    
    return False, None

def check_link(ct, wl):
    """
    Vérifie si un message contient des liens non autorisés.
    Retourne (True, url) si un lien non autorisé est trouvé.
    La whitelist contient des domaines autorisés (ex: trello.com, youtube.com)
    """
    # Extraire toutes les URLs du message
    urls = re.findall(r'https?://([^\s<>"\']+)', ct, re.IGNORECASE)
    
    if not urls:
        return False, None
    
    # Normaliser la whitelist
    whitelist = []
    for w in (wl or []):
        w = str(w).lower().strip()
        # Enlever http:// ou https:// si présent
        w = re.sub(r'^https?://', '', w)
        # Enlever le / final
        w = w.rstrip('/')
        if w:
            whitelist.append(w)
    
    # Toujours autoriser certains domaines de base
    default_whitelist = [
        'discord.com', 'discordapp.com', 'cdn.discordapp.com',
        'media.discordapp.net', 'images-ext-1.discordapp.net',
        'tenor.com', 'giphy.com', 'imgur.com',
    ]
    whitelist.extend(default_whitelist)
    
    for url in urls:
        url_lower = url.lower()
        # Extraire le domaine (avant le premier /)
        domain = url_lower.split('/')[0].split('?')[0]
        
        # Vérifier si le domaine est dans la whitelist
        is_allowed = False
        for allowed in whitelist:
            # Vérifier correspondance exacte ou sous-domaine
            if domain == allowed or domain.endswith('.' + allowed):
                is_allowed = True
                break
            # Vérifier si le domaine autorisé est contenu dans le domaine
            if allowed in domain:
                is_allowed = True
                break
        
        if not is_allowed:
            return True, url
    
    return False, None

def check_invite(ct):
    m = re.search(r'discord\.gg/\w+|discord\.com/invite/\w+|discordapp\.com/invite/\w+', ct, re.I)
    return (True, m.group()) if m else (False, None)

def check_phishing(ct):
    """Vérification de phishing améliorée"""
    # Utiliser la fonction avancée
    found, detail, ptype = advanced_phishing_check(ct)
    if found:
        return True, detail
    
    # Fallback sur les domaines basiques
    ct_lower = ct.lower()
    for d in PHISHING_DOMAINS:
        if d in ct_lower:
            return True, d
    return False, None

def check_scam(ct):
    """Vérification de scam améliorée"""
    # Utiliser la fonction avancée
    found, detail, score = advanced_scam_check(ct)
    if found:
        return True, detail
    
    # Patterns compilés
    for p in SCAM_PATTERNS:
        if p.search(ct):
            return True, p.pattern
    return False, None

def check_caps(ct, pct):
    ltrs = [c for c in ct if c.isalpha()]
    if len(ltrs) < 10: return False
    return sum(1 for c in ltrs if c.isupper()) / len(ltrs) * 100 >= pct

def check_image(msg, allowed):
    blocked = []
    gt = get_gif_type(msg)
    if gt and gt not in allowed: blocked.append(gt)
    for att in msg.attachments:
        ext = att.filename.lower().split('.')[-1]
        if ext in ['png', 'jpg', 'jpeg', 'webp', 'bmp'] and ext not in allowed:
            blocked.append(ext)
    return blocked

async def check_spam(msg, mx, intv):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker: spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n - t).total_seconds() < intv]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > mx

def check_channel_cfg(msg, conf):
    if not conf: return False, None
    ct = (msg.content or "").strip()
    # Commands only - bloque tout sauf les commandes slash (qui n'apparaissent pas comme messages normaux)
    if conf.get('commands_only', False):
        # Si le message n'est pas vide, c'est pas une commande slash
        if ct or msg.attachments:
            return True, "commands_only"
    if not conf.get('messages', True):
        has_txt = bool(re.sub(r'<a?:\w+:\d+>|https?://\S+', '', ct).strip())
        if has_txt and not msg.attachments and not msg.embeds:
            return True, "messages"
    if not conf.get('images', True):
        for att in msg.attachments:
            if att.filename.lower().split('.')[-1] in ['png', 'jpg', 'jpeg', 'webp', 'bmp']:
                return True, "images"
    if not conf.get('gifs', True) and get_gif_type(msg):
        return True, "gifs"
    if not conf.get('emojis', True) and re.search(r'<a?:\w+:\d+>', ct):
        return True, "emojis"
    if not conf.get('links', True) and re.search(r'https?://', ct):
        return True, "links"
    return False, None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_ticket(ch_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id, user_id, claimed_by, answers, panel_id FROM tickets WHERE channel_id=? AND status="open"', (ch_id,)) as c:
                r = await c.fetchone()
                if r:
                    ans = {}
                    try: ans = json.loads(r[3]) if r[3] else {}
                    except: pass
                    return {'id': r[0], 'user': r[1], 'claimed': r[2] or 0, 'answers': ans, 'panel_id': r[4] or ''}
                return None
    except: return None

async def count_user_tickets(g, uid, pid=None):
    cnt = 0
    to_close = []
    try:
        q = "SELECT id, channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'"
        p = [g.id, uid]
        if pid:
            q += " AND panel_id=?"
            p.append(pid)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(q, p) as c:
                tks = await c.fetchall()
        for tid, chid in tks:
            if g.get_channel(chid): cnt += 1
            else: to_close.append(tid)
        if to_close:
            async with aiosqlite.connect(DB_PATH) as db:
                for t in to_close:
                    await db.execute("UPDATE tickets SET status='closed' WHERE id=?", (t,))
                await db.commit()
        return cnt
    except: return 0

async def send_ticket_log(g, lt, user, ti, extra=None, closer=None, ch=None):
    try:
        c = await cfg(g.id)
        lch = g.get_channel(c.get('ticket_log', 0))
        if not lch: return
        colors = {'create': C.GREEN, 'claim': C.BLUE, 'close': C.RED, 'leave': C.ORANGE, 'add_staff': C.PURPLE}
        titles = {'create': '🎫 Ticket Créé', 'claim': '🙋 Ticket Pris', 'close': '🔒 Ticket Fermé', 'leave': '🚪 Utilisateur Parti', 'add_staff': '➕ Staff Ajouté'}
        e = discord.Embed(title=titles.get(lt, '🎫'), color=colors.get(lt, C.BLURPLE), timestamp=now())
        e.add_field(name="🎫 Ticket", value=f"#{ti.get('id', '?')}", inline=True)
        uid = user.id if hasattr(user, 'id') else user
        e.add_field(name="👤 Utilisateur", value=f"<@{uid}>", inline=True)
        if lt == 'claim' and extra:
            e.add_field(name="🙋 Pris par", value=f"<@{extra}>", inline=True)
        elif lt == 'close' and closer:
            e.add_field(name="🔒 Fermé par", value=closer.mention, inline=True)
        elif lt == 'add_staff' and extra:
            e.add_field(name="➕ Staff ajouté", value=f"<@{extra}>", inline=True)
        if ti.get('answers') and lt in ['create', 'close']:
            at = "\n".join([f"**{q}**: {a[:80]}" for q, a in list(ti['answers'].items())[:5]])
            if at: e.add_field(name="📝 Réponses", value=at[:1024], inline=False)
        if lt == 'close' and ch:
            lines = []
            try:
                async for m in ch.history(limit=200, oldest_first=True):
                    lines.append(f"[{m.created_at.strftime('%H:%M')}] {m.author.name}: {m.content or '[média]'}")
                f = discord.File(io.BytesIO(("\n".join(lines)).encode()), filename=f"ticket-{ti['id']}.txt")
                await lch.send(embed=e, file=f)
                return
            except: pass
        if hasattr(user, 'display_avatar'):
            e.set_thumbnail(url=user.display_avatar.url)
        await lch.send(embed=e)
    except: pass

async def create_ticket(i, pid, ans=None):
    ch = None
    try:
        c = await cfg(i.guild.id)
        pnl = c.get('ticket_panels', {}).get(pid, {})
        cat = i.guild.get_channel(pnl.get('category', 0))
        
        # Utiliser le rôle staff du panel, sinon le rôle staff global
        staff_role_id = pnl.get('staff_role', 0) or c.get('ticket_staff', 0)
        staff = i.guild.get_role(staff_role_id)
        
        mx = pnl.get('max', 1)
        if not cat: return None, "❌ Catégorie non configurée"
        if await count_user_tickets(i.guild, i.user.id, pid) >= mx:
            return None, f"❌ Max {mx} ticket(s)"
        ow = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True)
        }
        if staff:
            ow[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if i.guild.owner:
            ow[i.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
        ch = await i.guild.create_text_channel(f"ticket-{i.user.name}"[:50], category=cat, overwrites=ow)
        aj = json.dumps(ans or {}, ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO tickets(guild_id, channel_id, user_id, panel_id, claimed_by, status, answers) VALUES(?,?,?,?,0,"open",?)',
                (i.guild.id, ch.id, i.user.id, pid, aj))
            await db.commit()
            async with db.execute('SELECT id FROM tickets WHERE channel_id=?', (ch.id,)) as cur:
                row = await cur.fetchone()
                tid = row[0] if row else 0
        emb = discord.Embed(title="🎫 Nouveau Ticket", color=C.BLURPLE, timestamp=now())
        emb.add_field(name="👤 Créé par", value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
        emb.add_field(name="🎫 ID", value=f"#{tid}", inline=True)
        emb.set_thumbnail(url=i.user.display_avatar.url)
        if ans:
            for t, a in ans.items():
                emb.add_field(name=f"📝 {t}", value=a[:1024], inline=False)
        emb.set_footer(text="Un staff va prendre en charge")
        mention = i.user.mention
        if staff: mention += f" {staff.mention}"
        await ch.send(content=mention, embed=emb, view=TicketControlView())
        await send_ticket_log(i.guild, 'create', i.user, {'id': tid, 'answers': ans or {}})
        return ch, None
    except Exception as ex:
        if ch:
            try: await ch.delete()
            except: pass
        return None, f"❌ {ex}"

class TicketQuestionnaireModal(Modal):
    def __init__(self, pid, qs):
        super().__init__(title="📝 Créer un ticket")
        self.pid = pid
        self.qs = qs
        for i, q in enumerate(qs[:5]):
            self.add_item(TextInput(
                label=q.get('title', f'Q{i+1}')[:45],
                placeholder=q.get('question', '')[:100],
                style=discord.TextStyle.paragraph if len(q.get('question', '')) > 50 else discord.TextStyle.short,
                required=True,
                max_length=500
            ))
    
    async def on_submit(self, i):
        try:
            ans = {self.qs[j].get('title', f'Q{j+1}'): ch.value for j, ch in enumerate(self.children) if j < len(self.qs)}
            await i.response.defer(ephemeral=True)
            ch, err = await create_ticket(i, self.pid, ans)
            await i.followup.send(err if err else f"✅ Ticket créé: {ch.mention}", ephemeral=True)
        except Exception as ex:
            try: await i.followup.send(f"❌ {ex}", ephemeral=True)
            except: pass

class TicketCreateButton(Button):
    def __init__(self, pid):
        super().__init__(label="📩 Créer un ticket", style=discord.ButtonStyle.success, custom_id=f"ticket_create_{pid}")
        self.pid = pid
    
    async def callback(self, i):
        try:
            c = await cfg(i.guild.id)
            pnl = c.get('ticket_panels', {}).get(self.pid, {})
            if not pnl:
                return await i.response.send_message("❌ Panel introuvable", ephemeral=True)
            qs = pnl.get('questions', [])
            mx = pnl.get('max', 1)
            if await count_user_tickets(i.guild, i.user.id, self.pid) >= mx:
                return await i.response.send_message(f"❌ Max {mx} ticket(s)", ephemeral=True)
            if qs:
                await i.response.send_modal(TicketQuestionnaireModal(self.pid, qs))
            else:
                await i.response.defer(ephemeral=True)
                ch, err = await create_ticket(i, self.pid)
                await i.followup.send(err if err else f"✅ Ticket créé: {ch.mention}", ephemeral=True)
        except: pass

class TicketCreateView(View):
    def __init__(self, pid):
        super().__init__(timeout=None)
        self.add_item(TicketCreateButton(pid))

class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🙋 Prendre en charge", style=discord.ButtonStyle.success, custom_id="ticket_ctrl_claim")
    async def claim(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            
            if i.user.id == tk['user']:
                return await i.response.send_message("❌ Vous ne pouvez pas prendre votre propre ticket", ephemeral=True)
            
            # Vérifier si l'utilisateur est immunisé (peut tout faire sur les tickets)
            is_immune = await is_fully_immune(i.user)
            
            is_s = sr and sr in i.user.roles
            is_o = i.user.id == i.guild.owner_id
            is_a = i.user.guild_permissions.administrator
            
            if not (is_s or is_o or is_a or is_immune):
                return await i.response.send_message("❌ Réservé au staff", ephemeral=True)
            
            # Si le ticket est déjà claim, vérifier si on peut sur-claim
            if tk['claimed'] and tk['claimed'] != i.user.id:
                if not (is_immune or is_o or is_a):
                    return await i.response.send_message(
                        f"❌ Ce ticket est déjà pris par <@{tk['claimed']}>.\n"
                        "*Seuls les immunisés/admins peuvent sur-claim.*",
                        ephemeral=True
                    )
                # Sur-claim autorisé
                await i.channel.send(f"⚠️ **Sur-claim** : {i.user.mention} reprend ce ticket (anciennement <@{tk['claimed']}>)")
            
            tu = i.guild.get_member(tk['user'])
            ow = {
                i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True),
                i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            }
            if tu:
                ow[tu] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
            if i.guild.owner and i.guild.owner != i.user:
                ow[i.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
            if sr:
                ow[sr] = discord.PermissionOverwrite(view_channel=False)
            await i.channel.edit(overwrites=ow)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (i.user.id, i.channel.id))
                await db.commit()
            await i.response.send_message(f"✅ **{i.user.display_name}** prend ce ticket en charge\n\n*Les autres staffs ne peuvent plus voir ce ticket.*")
            btn.disabled = True
            btn.label = f"Pris par {i.user.display_name}"
            btn.style = discord.ButtonStyle.secondary
            await i.message.edit(view=self)
            await send_ticket_log(i.guild, 'claim', tk['user'], tk, extra=i.user.id)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="➕ Ajouter Staff", style=discord.ButtonStyle.primary, custom_id="ticket_ctrl_add")
    async def add_staff(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            
            # Vérifier l'immunité
            is_immune = await is_fully_immune(i.user)
            is_o = i.user.id == i.guild.owner_id
            is_c = i.user.id == tk['claimed']
            is_a = i.user.guild_permissions.administrator
            
            # Les immunisés peuvent toujours ajouter du staff
            if not tk['claimed'] and not is_immune:
                return await i.response.send_message("❌ Le ticket doit d'abord être pris en charge", ephemeral=True)
            
            if not (is_c or is_o or is_a or is_immune):
                return await i.response.send_message("❌ Seul le staff en charge peut ajouter quelqu'un", ephemeral=True)
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            if not sr:
                return await i.response.send_message("❌ Aucun rôle staff configuré", ephemeral=True)
            staffs = [m for m in sr.members if m.id != tk['claimed'] and m.id != tk['user']][:25]
            if not staffs:
                return await i.response.send_message("❌ Aucun autre staff disponible", ephemeral=True)
            opts = [discord.SelectOption(label=f"@{m.display_name}"[:25], value=str(m.id)) for m in staffs]
            await i.response.send_message("👥 Choisir un staff:", view=AddStaffView(opts, i.channel.id), ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="ticket_ctrl_close")
    async def close(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            
            # Vérifier l'immunité
            is_immune = await is_fully_immune(i.user)
            is_o = i.user.id == i.guild.owner_id
            is_a = i.user.guild_permissions.administrator
            is_c = i.user.id == tk['claimed']
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            is_s = sr and sr in i.user.roles
            
            # Les immunisés peuvent toujours fermer
            if tk['claimed']:
                if not (is_c or is_o or is_a or is_immune):
                    return await i.response.send_message("❌ Seul le staff en charge ou un admin peut fermer", ephemeral=True)
            else:
                if not (is_s or is_o or is_a or is_immune):
                    return await i.response.send_message("❌ Seul le staff peut fermer", ephemeral=True)
            
            tu = i.guild.get_member(tk['user'])
            await send_ticket_log(i.guild, 'close', tu or tk['user'], tk, closer=i.user, ch=i.channel)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (i.channel.id,))
                await db.commit()
            await i.response.send_message("🔒 Fermeture dans 3 secondes...")
            await asyncio.sleep(3)
            await i.channel.delete()
        except: pass

class AddStaffView(View):
    def __init__(self, opts, chid):
        super().__init__(timeout=60)
        self.add_item(AddStaffSelect(opts, chid))

class AddStaffSelect(Select):
    def __init__(self, opts, chid):
        super().__init__(placeholder="Choisir un staff...", options=opts)
        self.chid = chid
    
    async def callback(self, i):
        try:
            st = i.guild.get_member(int(self.values[0]))
            ch = i.guild.get_channel(self.chid)
            if st and ch:
                await ch.set_permissions(st, view_channel=True, send_messages=True, read_message_history=True)
                await i.response.send_message(f"✅ {st.mention} ajouté au ticket!", ephemeral=True)
                await ch.send(f"➕ **{st.display_name}** a été ajouté par {i.user.mention}")
                tk = await get_ticket(self.chid)
                if tk:
                    await send_ticket_log(i.guild, 'add_staff', tk['user'], tk, extra=st.id)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════

PROTS = [
    ("anti_link", "🔗", "Anti-Liens"),
    ("anti_invite", "🎟️", "Anti-Invite"),
    ("anti_image", "🖼️", "Anti-Images"),
    ("anti_phishing", "🎣", "Anti-Phishing"),
    ("anti_scam", "🚨", "Anti-Scam"),
    ("anti_spam", "📨", "Anti-Spam"),
    ("anti_caps", "🔠", "Anti-Caps"),
    ("anti_badwords", "🤬", "Anti-Insultes"),
    ("anti_newaccount", "👶", "Anti-NewAccount"),
    ("anti_raid", "⚔️", "Anti-Raid"),
    ("anti_compromised", "🔐", "Anti-Compromis"),
    ("anti_qrcode", "📱", "Anti-QRCode"),
    ("anti_alt", "👥", "Anti-MultiCompte")
]

# Cache pour l'anti-raid : {guild_id: {'joins': [(user_id, timestamp), ...], 'lockdown': bool}}
raid_tracker = {}

# Cache pour les détections de comptes secondaires
alt_account_cache = {}  # {guild_id: {user_id: {'main_account': user_id, 'alts': [user_ids], 'reasons': []}}

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ BASES DE DONNÉES DE PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

# Domaines de phishing connus (2026 - mise à jour)
PHISHING_DOMAINS = [
    # Faux Discord
    'discord-gift.com', 'discord-nitro.gift', 'discordgift.site', 'discordnitro.com',
    'dlscord.com', 'dlscord.gift', 'discorcl.com', 'discrod.com', 'discordc.com',
    'discord-app.com', 'discordapp.gift', 'discord.gift', 'discord-airdrop.com',
    'discordn.com', 'discordi.com', 'discord-claim.com', 'discordnitros.com',
    'dlscord-nitro.com', 'discordd.gift', 'disc0rd.gift', 'disc0rd-nitro.com',
    'discorid.gift', 'discordl.com', 'discord-free.com', 'discordgiveaway.com',
    'steamcomminuty.com', 'steampowored.com', 'steamcommunlty.com', 'steancommunity.com',
    'store-steampowered.com', 'steamcommunity.ru.com', 'steamcommunitv.com',
    # Faux Steam
    'steamcommunity-login.com', 'steam-guard.com', 'steamguard-code.com',
    # Crypto scams
    'free-ethereum.com', 'free-bitcoin.gift', 'crypto-airdrop.com', 'nft-free.com',
    'opensea-drop.com', 'metamask-airdrop.com', 'eth-giveaway.com',
    # Faux services
    'paypal-verify.com', 'amazon-gift.com', 'netflix-free.com', 'spotify-premium.gift',
    # IP grabbers
    'grabify.link', 'iplogger.org', 'blasze.tk', '2no.co', 'iplogger.com',
    'ps3cfw.com', 'urlz.fr', 'webresolver.nl', 'ezstat.ru',
    # Raccourcisseurs suspects
    'bit.do', 'adf.ly', 'bc.vc', 'j.gs', 'sh.st', 'ouo.io',
]

# Patterns de phishing dans les URLs
PHISHING_URL_PATTERNS = [
    r'discord.*gift', r'discord.*nitro', r'discord.*free', r'discord.*claim',
    r'steam.*community.*login', r'steam.*guard', r'steam.*trade',
    r'free.*nitro', r'nitro.*free', r'claim.*nitro', r'get.*nitro',
    r'crypto.*airdrop', r'free.*eth', r'free.*btc', r'nft.*drop',
    r'discord.*airdrop', r'discord.*giveaway',
    r'paypal.*verify', r'amazon.*gift', r'netflix.*free',
    r'@everyone.*http', r'@here.*http',  # Mention + lien
    r'\.gift\/', r'\.ru\/.*discord', r'\.tk\/.*gift',
]

# Mots-clés de scam dans les messages
SCAM_KEYWORDS = [
    # Nitro scams
    'free nitro', 'nitro gratuit', 'nitro free', 'claim nitro', 'get nitro',
    'nitro gift', 'discord nitro free', '3 months free', '1 month free',
    'steam gift', 'free steam', 'cs2 skins free', 'csgo skins free',
    # Crypto scams
    'crypto giveaway', 'eth giveaway', 'btc giveaway', 'free crypto',
    'airdrop claim', 'nft drop', 'mint free', 'whitelist spot',
    'send 0.1 eth', 'double your', 'x2 your crypto',
    # Fake emergencies
    'account will be deleted', 'verify your account', 'account suspended',
    'unusual activity', 'confirm your identity', 'action required',
    'your account has been', 'limited time only', 'expires in 24',
    # Investment scams
    'guaranteed profit', 'easy money', 'make money fast', 'passive income',
    'forex signals', 'binary options', 'investment opportunity',
    # Job scams
    'work from home', 'easy job', '$500/day', '€500/jour', 'hiring now dm',
    # Romance/Social scams
    'im a girl', 'add me on', 'check my profile', 'link in bio',
    'onlyfans free', 'leaked content', 'exclusive content',
]

# Patterns de messages de comptes compromis
COMPROMISED_PATTERNS = [
    r'@everyone.*http', r'@here.*http',  # Mention de masse + lien
    r'check.*this.*http', r'look.*what.*found.*http',
    r'bro.*check.*http', r'dude.*look.*http',
    r'yo.*this.*real.*http', r'omg.*http',
    r'free.*gift.*http', r'won.*http',
    r'http.*\.(gift|ru|tk|ml|ga|cf|gq)(\s|$)',  # TLD suspects
]

# Extensions de fichiers dangereux
DANGEROUS_EXTENSIONS = [
    '.exe', '.bat', '.cmd', '.msi', '.scr', '.pif', '.com',
    '.vbs', '.vbe', '.js', '.jse', '.ws', '.wsf', '.wsc', '.wsh',
    '.ps1', '.psm1', '.psd1',  # PowerShell
    '.hta', '.cpl', '.msc', '.jar',  # Autres exécutables
    '.dll', '.sys', '.drv',  # Bibliothèques
]

# Cache pour détecter les comportements suspects
compromised_cache = {}  # {user_id: {'messages': [], 'flags': 0}}

# Initialiser les variables globales avec les nouvelles bases
PHISHING = PHISHING_DOMAINS
SCAM_PATTERNS = [re.compile(p, re.IGNORECASE) for p in COMPROMISED_PATTERNS]

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ FONCTIONS DE PROTECTION AVANCÉES
# ═══════════════════════════════════════════════════════════════════════════════

def advanced_phishing_check(content):
    """Vérifie le contenu pour détecter le phishing avec analyse avancée"""
    content_lower = content.lower()
    detected = []
    
    # 1. Vérifier les domaines de phishing connus
    urls = re.findall(r'https?://([^\s<>"\']+)', content_lower)
    for url in urls:
        domain = url.split('/')[0].split('?')[0]
        
        # Domaines exacts
        for phish_domain in PHISHING_DOMAINS:
            if phish_domain in domain:
                return True, f"Domaine phishing: {domain}", "domain"
        
        # Patterns d'URL suspects
        for pattern in PHISHING_URL_PATTERNS:
            if re.search(pattern, url):
                return True, f"URL suspecte: {url[:50]}", "url_pattern"
        
        # Typosquatting Discord
        if 'disc' in domain and 'discord.com' not in domain and 'discord.gg' not in domain:
            if any(x in domain for x in ['gift', 'nitro', 'free', 'claim', 'app']):
                return True, f"Typosquatting Discord: {domain}", "typosquatting"
        
        # Typosquatting Steam
        if 'steam' in domain and 'steampowered.com' not in domain and 'steamcommunity.com' not in domain:
            if any(x in domain for x in ['community', 'trade', 'gift', 'login']):
                return True, f"Typosquatting Steam: {domain}", "typosquatting"
        
        # TLD suspects avec mots-clés
        suspect_tlds = ['.ru', '.tk', '.ml', '.ga', '.cf', '.gq', '.xyz', '.top', '.buzz']
        if any(domain.endswith(tld) for tld in suspect_tlds):
            if any(kw in domain for kw in ['discord', 'nitro', 'steam', 'gift', 'free', 'crypto']):
                return True, f"TLD suspect: {domain}", "suspect_tld"
    
    # 2. Vérifier les patterns de messages phishing
    phishing_message_patterns = [
        r'(click|cliquez).*link.*claim',
        r'congratulations.*won',
        r'félicitations.*gagné',
        r'verify.*account.*http',
        r'vérifier.*compte.*http',
        r'@everyone.*free.*http',
        r'@here.*free.*http',
        r'limited.*time.*http',
        r'expire.*24.*hour',
    ]
    
    for pattern in phishing_message_patterns:
        if re.search(pattern, content_lower):
            return True, f"Pattern phishing: {pattern}", "message_pattern"
    
    return False, None, None

def advanced_scam_check(content):
    """Vérifie le contenu pour détecter les scams avec analyse avancée"""
    content_lower = content.lower()
    
    # 1. Vérifier les mots-clés de scam
    scam_score = 0
    detected_keywords = []
    
    for keyword in SCAM_KEYWORDS:
        if keyword in content_lower:
            scam_score += 10
            detected_keywords.append(keyword)
    
    # 2. Combinaisons dangereuses
    dangerous_combos = [
        (['free', 'nitro', 'http'], 30),
        (['@everyone', 'http'], 25),
        (['@here', 'http'], 25),
        (['free', 'gift', 'http'], 25),
        (['click', 'claim', 'http'], 20),
        (['dm', 'me', 'money'], 15),
        (['crypto', 'investment', 'profit'], 20),
        (['send', 'eth', 'receive'], 30),
        (['double', 'crypto'], 30),
    ]
    
    for combo, score in dangerous_combos:
        if all(word in content_lower for word in combo):
            scam_score += score
            detected_keywords.extend(combo)
    
    # 3. Urgence artificielle
    urgency_patterns = [
        r'(only|seulement)\s*\d+\s*(left|remaining|restant)',
        r'(expire|end)s?\s*(in|dans)\s*\d+',
        r'(hurry|vite|dépêche)',
        r'(last|dernier)\s*(chance|opportunit)',
        r'(act|agir)\s*(now|maintenant)',
    ]
    
    for pattern in urgency_patterns:
        if re.search(pattern, content_lower):
            scam_score += 10
    
    # Seuil de détection
    if scam_score >= 25:
        return True, ", ".join(set(detected_keywords[:5])), scam_score
    
    return False, None, 0

def check_compromised_behavior(user_id, guild_id, content, has_mentions_everyone=False):
    """Détecte si un compte semble compromis basé sur son comportement"""
    key = (guild_id, user_id)
    current_time = now()
    
    # Initialiser le cache
    if key not in compromised_cache:
        compromised_cache[key] = {
            'messages': [],
            'flags': 0,
            'last_flag': None
        }
    
    cache = compromised_cache[key]
    
    # Nettoyer les anciens messages (garder 5 min)
    cache['messages'] = [
        m for m in cache['messages']
        if (current_time - m['time']).total_seconds() < 300
    ]
    
    # Ajouter ce message
    cache['messages'].append({
        'time': current_time,
        'has_link': bool(re.search(r'https?://', content)),
        'has_everyone': has_mentions_everyone,
        'length': len(content)
    })
    
    # Analyser le comportement
    flags = 0
    reasons = []
    
    recent_messages = cache['messages']
    
    # 1. Plusieurs @everyone avec liens en peu de temps
    everyone_with_links = sum(1 for m in recent_messages if m['has_everyone'] and m['has_link'])
    if everyone_with_links >= 2:
        flags += 50
        reasons.append("Spam @everyone + liens")
    
    # 2. Messages identiques répétés
    if len(recent_messages) >= 3:
        # Vérifier si c'est le même pattern
        link_count = sum(1 for m in recent_messages if m['has_link'])
        if link_count >= 3:
            flags += 30
            reasons.append("Spam de liens")
    
    # 3. Comportement anormal (premier message = @everyone + lien)
    if len(recent_messages) == 1 and has_mentions_everyone and re.search(r'https?://', content):
        flags += 40
        reasons.append("Premier message suspect")
    
    cache['flags'] = flags
    
    return flags >= 40, reasons, flags

def check_dangerous_file(filename):
    """Vérifie si un fichier a une extension dangereuse"""
    filename_lower = filename.lower()
    for ext in DANGEROUS_EXTENSIONS:
        if filename_lower.endswith(ext):
            return True, ext
    return False, None

def check_qr_code_scam(content):
    """Détecte les tentatives de scam par QR code"""
    qr_patterns = [
        r'scan.*qr.*code',
        r'qr.*code.*scan',
        r'scanner.*code',
        r'discord.*token',
        r'login.*qr',
        r'authenticate.*qr',
        r'qr.*gift',
        r'qr.*nitro',
    ]
    
    content_lower = content.lower()
    for pattern in qr_patterns:
        if re.search(pattern, content_lower):
            return True, pattern
    
    return False, None

# ═══════════════════════════════════════════════════════════════════════════════
#                           👥 DÉTECTION COMPTES SECONDAIRES
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_username(name):
    """Normalise un nom d'utilisateur pour comparaison"""
    name = name.lower()
    # Supprimer les chiffres à la fin
    name = re.sub(r'\d+$', '', name)
    # Supprimer les caractères spéciaux
    name = re.sub(r'[^a-z0-9]', '', name)
    # Remplacer les substitutions courantes
    replacements = {
        '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's',
        '7': 't', '8': 'b', '@': 'a', '$': 's'
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    return name

def levenshtein_distance(s1, s2):
    """Calcule la distance de Levenshtein entre deux chaînes"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]

def username_similarity(name1, name2):
    """Calcule la similarité entre deux noms d'utilisateur (0-100)"""
    n1 = normalize_username(name1)
    n2 = normalize_username(name2)
    
    if not n1 or not n2:
        return 0
    
    # Distance de Levenshtein
    distance = levenshtein_distance(n1, n2)
    max_len = max(len(n1), len(n2))
    
    if max_len == 0:
        return 0
    
    similarity = (1 - distance / max_len) * 100
    return max(0, min(100, similarity))

def get_avatar_hash(member):
    """Récupère le hash de l'avatar d'un membre"""
    if member.avatar:
        return str(member.avatar.key)
    return "default"

async def save_user_fingerprint(guild_id, member):
    """Sauvegarde l'empreinte d'un utilisateur pour détection future"""
    try:
        avatar_hash = get_avatar_hash(member)
        username_norm = normalize_username(member.name)
        created_ts = int(member.created_at.timestamp()) if member.created_at else 0
        joined_ts = int(member.joined_at.timestamp()) if member.joined_at else 0
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO user_fingerprints 
                (guild_id, user_id, avatar_hash, username_normalized, created_at_ts, joined_at_ts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    avatar_hash = ?, username_normalized = ?, updated_at = ?
            ''', (guild_id, member.id, avatar_hash, username_norm, created_ts, joined_ts, now().isoformat(),
                  avatar_hash, username_norm, now().isoformat()))
            await db.commit()
    except Exception as ex:
        print(f"[ALT] Erreur save fingerprint: {ex}")

async def save_ban_info(guild_id, user_id, username, avatar_hash, reason):
    """Sauvegarde les infos d'un ban pour détection de contournement"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO ban_history (guild_id, user_id, username, avatar_hash, reason)
                VALUES (?, ?, ?, ?, ?)
            ''', (guild_id, user_id, username, avatar_hash, reason))
            await db.commit()
    except Exception as ex:
        print(f"[ALT] Erreur save ban: {ex}")

async def detect_alt_account(guild, new_member):
    """
    Détecte si un nouveau membre est potentiellement un compte secondaire.
    Retourne: (is_alt, confidence, main_account_id, reasons)
    """
    reasons = []
    confidence = 0
    main_account_id = None
    
    try:
        new_avatar = get_avatar_hash(new_member)
        new_username_norm = normalize_username(new_member.name)
        new_created_ts = int(new_member.created_at.timestamp()) if new_member.created_at else 0
        
        async with aiosqlite.connect(DB_PATH) as db:
            # 1. Vérifier si l'avatar correspond à un utilisateur banni
            async with db.execute('''
                SELECT user_id, username FROM ban_history 
                WHERE guild_id = ? AND avatar_hash = ? AND avatar_hash != "default"
            ''', (guild.id, new_avatar)) as cursor:
                banned_match = await cursor.fetchone()
                if banned_match:
                    confidence += 60
                    main_account_id = banned_match[0]
                    reasons.append(f"Avatar identique à l'utilisateur banni {banned_match[1]} ({banned_match[0]})")
            
            # 2. Vérifier les noms similaires avec des utilisateurs bannis
            async with db.execute('''
                SELECT user_id, username FROM ban_history WHERE guild_id = ?
            ''', (guild.id,)) as cursor:
                banned_users = await cursor.fetchall()
                for banned_id, banned_name in banned_users:
                    sim = username_similarity(new_member.name, banned_name)
                    if sim >= 80:
                        confidence += 40
                        if not main_account_id:
                            main_account_id = banned_id
                        reasons.append(f"Nom similaire ({int(sim)}%) à l'utilisateur banni {banned_name}")
            
            # 3. Vérifier si l'avatar correspond à un membre existant (même avatar = même personne)
            async with db.execute('''
                SELECT user_id FROM user_fingerprints 
                WHERE guild_id = ? AND avatar_hash = ? AND avatar_hash != "default" AND user_id != ?
            ''', (guild.id, new_avatar, new_member.id)) as cursor:
                avatar_matches = await cursor.fetchall()
                for (existing_id,) in avatar_matches:
                    existing_member = guild.get_member(existing_id)
                    if existing_member:
                        confidence += 50
                        if not main_account_id:
                            main_account_id = existing_id
                        reasons.append(f"Avatar identique à {existing_member.name} ({existing_id})")
            
            # 4. Vérifier les noms très similaires avec des membres existants
            async with db.execute('''
                SELECT user_id, username_normalized FROM user_fingerprints 
                WHERE guild_id = ? AND user_id != ?
            ''', (guild.id, new_member.id)) as cursor:
                existing_users = await cursor.fetchall()
                for existing_id, existing_norm in existing_users:
                    if existing_norm and new_username_norm:
                        sim = username_similarity(new_member.name, existing_norm)
                        if sim >= 85:
                            existing_member = guild.get_member(existing_id)
                            if existing_member:
                                confidence += 30
                                if not main_account_id:
                                    main_account_id = existing_id
                                reasons.append(f"Nom très similaire ({int(sim)}%) à {existing_member.name}")
            
            # 5. Vérifier si le compte a été créé juste après un ban
            async with db.execute('''
                SELECT user_id, username, banned_at FROM ban_history 
                WHERE guild_id = ? 
                ORDER BY banned_at DESC LIMIT 10
            ''', (guild.id,)) as cursor:
                recent_bans = await cursor.fetchall()
                for banned_id, banned_name, banned_at in recent_bans:
                    try:
                        ban_ts = datetime.fromisoformat(banned_at).timestamp()
                        # Si le compte a été créé dans les 7 jours suivant un ban
                        if 0 < new_created_ts - ban_ts < 7 * 86400:
                            confidence += 25
                            if not main_account_id:
                                main_account_id = banned_id
                            reasons.append(f"Compte créé peu après le ban de {banned_name}")
                    except:
                        pass
            
            # 6. Compte très récent (moins de 7 jours) = plus suspect
            account_age_days = (now() - new_member.created_at.replace(tzinfo=timezone.utc)).days if new_member.created_at else 365
            if account_age_days < 1:
                confidence += 15
                reasons.append("Compte créé aujourd'hui")
            elif account_age_days < 7:
                confidence += 10
                reasons.append(f"Compte très récent ({account_age_days} jours)")
        
        # Plafonner la confiance à 100
        confidence = min(100, confidence)
        
        # Sauvegarder la détection si suffisamment confiant
        if confidence >= 40 and main_account_id:
            await save_alt_detection(guild.id, main_account_id, new_member.id, confidence, reasons)
        
        return confidence >= 40, confidence, main_account_id, reasons
        
    except Exception as ex:
        print(f"[ALT] Erreur détection: {ex}")
        return False, 0, None, []

async def save_alt_detection(guild_id, main_id, alt_id, confidence, reasons):
    """Sauvegarde une détection de compte secondaire"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO alt_accounts (guild_id, main_account_id, alt_account_id, confidence, reasons, status)
                VALUES (?, ?, ?, ?, ?, "suspected")
                ON CONFLICT(guild_id, main_account_id, alt_account_id) DO UPDATE SET
                    confidence = ?, reasons = ?, detected_at = CURRENT_TIMESTAMP
            ''', (guild_id, main_id, alt_id, confidence, json.dumps(reasons), confidence, json.dumps(reasons)))
            await db.commit()
    except Exception as ex:
        print(f"[ALT] Erreur save detection: {ex}")

async def get_alt_accounts(guild_id):
    """Récupère tous les comptes secondaires détectés pour un serveur"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT id, main_account_id, alt_account_id, confidence, reasons, status, detected_at, action_taken
                FROM alt_accounts WHERE guild_id = ?
                ORDER BY confidence DESC, detected_at DESC
            ''', (guild_id,)) as cursor:
                return await cursor.fetchall()
    except:
        return []

async def update_alt_status(guild_id, alt_id, status, action=""):
    """Met à jour le statut d'un compte secondaire"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                UPDATE alt_accounts SET status = ?, action_taken = ?
                WHERE guild_id = ? AND alt_account_id = ?
            ''', (status, action, guild_id, alt_id))
            await db.commit()
    except Exception as ex:
        print(f"[ALT] Erreur update status: {ex}")

async def scan_all_members_for_alts(guild):
    """Scanne tous les membres du serveur pour détecter les comptes secondaires"""
    detected = []
    
    try:
        # D'abord, sauvegarder les fingerprints de tous les membres
        for member in guild.members:
            if not member.bot:
                await save_user_fingerprint(guild.id, member)
        
        # Ensuite, détecter les alts
        for member in guild.members:
            if not member.bot:
                is_alt, confidence, main_id, reasons = await detect_alt_account(guild, member)
                if is_alt:
                    detected.append({
                        'member': member,
                        'confidence': confidence,
                        'main_id': main_id,
                        'reasons': reasons
                    })
    except Exception as ex:
        print(f"[ALT] Erreur scan: {ex}")
    
    return detected

class MainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def interaction_check(self, i):
        return i.user.id == self.u.id
    
    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"**{self.g.name}**\n👥 {self.g.member_count} membres"
        if self.g.icon:
            e.set_thumbnail(url=self.g.icon.url)
        return e
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Modération", emoji="🔨", style=discord.ButtonStyle.primary, row=0)
    async def moderation(self, i, b):
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Commandes", emoji="⚡", style=discord.ButtonStyle.primary, row=0)
    async def commands(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def immune(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Config Salon", emoji="📺", style=discord.ButtonStyle.secondary, row=1)
    async def chan(self, i, b):
        v = ChanPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.success, row=1)
    async def tickets(self, i, b):
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Publicité", emoji="📢", style=discord.ButtonStyle.success, row=2)
    async def ads(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Statistiques", emoji="📊", style=discord.ButtonStyle.success, row=2)
    async def stats(self, i, b):
        v = StatPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Centre", emoji="🎯", style=discord.ButtonStyle.success, row=2)
    async def centre(self, i, b):
        v = CentrePanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)
    
    @discord.ui.button(label="Niveaux", emoji="📈", style=discord.ButtonStyle.primary, row=3)
    async def levels(self, i, b):
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Création", emoji="🔊", style=discord.ButtonStyle.primary, row=3)
    async def temp_voice(self, i, b):
        v = TempVoicePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Aide Auto", emoji="💡", style=discord.ButtonStyle.primary, row=3)
    async def auto_help(self, i, b):
        v = AutoHelpPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=4)
    async def close(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL (REFAIT PROPREMENT)
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        lines = []
        for key, emoji, name in PROTS:
            status = "✅" if c.get(key) else "❌"
            log_ch = self.g.get_channel(c.get(f'log_{key}', 0))
            log_txt = f"→ {log_ch.mention}" if log_ch else ""
            lines.append(f"{emoji} **{name}**: {status} {log_txt}")
        e.description = "\n".join(lines)
        return e
    
    @discord.ui.select(
        placeholder="🛡️ Sélectionner une protection...",
        options=[discord.SelectOption(label=nm, value=k, emoji=em) for k, em, nm in PROTS]
    )
    async def sel(self, i, s):
        prot = next(p for p in PROTS if p[0] == s.values[0])
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ProtDetail(View):
    def __init__(self, u, g, prot):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.prot = prot
        self.key = prot[0]
    
    async def embed(self):
        c = await cfg(self.g.id)
        on = bool(c.get(self.key))
        e = discord.Embed(
            title=f"{self.prot[1]} {self.prot[2]}",
            color=C.GREEN if on else C.RED
        )
        e.add_field(name="🔘 État", value="✅ ACTIVÉ" if on else "❌ DÉSACTIVÉ", inline=False)
        
        # Configs spécifiques
        if self.key == "anti_link":
            wl = c.get('link_whitelist', [])
            e.add_field(name="🌐 Whitelist domaines", value=f"`{', '.join(wl[:15])}`" if wl else "*Aucun domaine*", inline=False)
            chs = c.get('link_allowed_channels', [])
            ch_txt = ", ".join([f"<#{x}>" for x in chs[:10]]) if chs else "*Aucun salon*"
            e.add_field(name="📍 Salons autorisés", value=ch_txt, inline=False)
        
        elif self.key == "anti_image":
            items = c.get('image_allowed', [])
            fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy']
            fmt_txt = " ".join([f"{'✅' if f in items else '❌'} `{f}`" for f in fmts])
            e.add_field(name="📁 Formats autorisés", value=fmt_txt, inline=False)
        
        elif self.key == "anti_badwords":
            words = c.get('badwords_list', [])
            if words:
                # Afficher tous les mots, ou limiter avec compteur
                if len(words) <= 30:
                    words_txt = ", ".join([f"`{w}`" for w in words])
                else:
                    words_txt = ", ".join([f"`{w}`" for w in words[:30]]) + f"\n*... et {len(words) - 30} autres*"
                e.add_field(name=f"🚫 Mots interdits ({len(words)})", value=words_txt[:1024], inline=False)
            else:
                e.add_field(name="🚫 Mots interdits", value="*Aucun mot configuré*", inline=False)
        
        elif self.key == "anti_spam":
            e.add_field(name="📊 Max messages", value=str(c.get('spam_max', 5)), inline=True)
            e.add_field(name="⏱️ Intervalle (sec)", value=str(c.get('spam_interval', 5)), inline=True)
            e.add_field(name="⚡ Action", value=c.get('spam_action', 'mute').upper(), inline=True)
        
        elif self.key == "anti_caps":
            e.add_field(name="📊 Pourcentage max", value=f"{c.get('caps_percent', 70)}%", inline=True)
        
        elif self.key == "anti_newaccount":
            e.add_field(name="📅 Jours minimum", value=str(c.get('newaccount_days', 7)), inline=True)
        
        elif self.key in ["anti_phishing", "anti_scam"]:
            ak = 'phishing_action' if self.key == "anti_phishing" else 'scam_action'
            e.add_field(name="⚡ Action", value=c.get(ak, 'ban' if 'phishing' in ak else 'mute').upper(), inline=True)
        
        elif self.key == "anti_raid":
            raid_cfg = c.get('raid_config', {})
            e.add_field(name="👥 Seuil de détection", value=f"`{raid_cfg.get('join_threshold', 10)}` membres en `{raid_cfg.get('join_interval', 10)}` sec", inline=False)
            e.add_field(name="📅 Âge compte min", value=f"`{raid_cfg.get('min_account_age', 7)}` jours", inline=True)
            e.add_field(name="🤖 Mode auto", value="✅ Oui" if raid_cfg.get('auto_mode', True) else "❌ Non", inline=True)
            e.add_field(name="🔒 Bloquer invitations", value="✅ Oui" if raid_cfg.get('block_invites', True) else "❌ Non", inline=True)
            action = raid_cfg.get('action', 'kick')
            e.add_field(name="⚡ Action", value=action.upper(), inline=True)
            
            # État du lockdown
            lockdown = raid_tracker.get(self.g.id, {}).get('lockdown', False)
            e.add_field(name="🚨 Lockdown actif", value="⚠️ **OUI**" if lockdown else "✅ Non", inline=True)
        
        elif self.key == "anti_compromised":
            e.description = "🔐 **Détection des comptes compromis/hackés**\n\nDétecte les comportements suspects indiquant qu'un compte a été compromis :\n• Spam de @everyone avec liens\n• Messages identiques répétés\n• Premier message = lien suspect"
            action = c.get('compromised_action', 'mute')
            e.add_field(name="⚡ Action", value=action.upper(), inline=True)
            e.add_field(name="📊 Détections", value=f"`{len(PHISHING_DOMAINS)}` domaines\n`{len(SCAM_KEYWORDS)}` mots-clés\n`{len(COMPROMISED_PATTERNS)}` patterns", inline=True)
        
        elif self.key == "anti_qrcode":
            e.description = "📱 **Protection contre les scams par QR Code**\n\nDétecte les tentatives de vol de compte via QR code Discord :\n• Messages demandant de scanner un QR code\n• Faux QR codes de 'cadeaux'\n• Tentatives de vol de token"
            action = c.get('qrcode_action', 'mute')
            e.add_field(name="⚡ Action", value=action.upper(), inline=True)
        
        elif self.key == "anti_phishing":
            e.description = "🎣 **Protection Anti-Phishing Avancée 2026**\n\nProtège contre :\n• Faux sites Discord/Steam/Nitro\n• Typosquatting (dlscord, steampowored...)\n• IP grabbers et raccourcisseurs suspects\n• TLD dangereux (.ru, .tk, .xyz...)"
            action = c.get('phishing_action', 'ban')
            e.add_field(name="⚡ Action", value=action.upper(), inline=True)
            e.add_field(name="📊 Base de données", value=f"`{len(PHISHING_DOMAINS)}` domaines blacklistés", inline=True)
        
        elif self.key == "anti_scam":
            e.description = "🚨 **Protection Anti-Scam Avancée 2026**\n\nDétecte :\n• Free Nitro / Steam Gift scams\n• Crypto giveaway / Airdrop scams\n• Investment scams\n• Faux jobs / Romance scams\n• Urgence artificielle"
            action = c.get('scam_action', 'mute')
            e.add_field(name="⚡ Action", value=action.upper(), inline=True)
            e.add_field(name="📊 Base de données", value=f"`{len(SCAM_KEYWORDS)}` mots-clés détectés", inline=True)
        
        elif self.key == "anti_alt":
            alt_cfg = c.get('alt_config', {})
            e.description = (
                "👥 **Détection des Comptes Secondaires**\n\n"
                "Détecte automatiquement les comptes secondaires (alts) :\n"
                "• Avatar identique à un membre existant/banni\n"
                "• Nom d'utilisateur similaire\n"
                "• Compte créé juste après un ban\n"
                "• Comportement suspect"
            )
            
            action = c.get('alt_action', 'kick')
            auto = alt_cfg.get('auto_action', False)
            min_conf = alt_cfg.get('min_confidence', 70)
            
            e.add_field(name="⚡ Action", value=action.upper(), inline=True)
            e.add_field(name="🤖 Action auto", value="✅ Activé" if auto else "❌ Désactivé", inline=True)
            e.add_field(name="📊 Confiance min.", value=f"{min_conf}%", inline=True)
            
            # Comptes secondaires détectés
            alts = await get_alt_accounts(self.g.id)
            suspected = len([a for a in alts if a[5] == 'suspected'])
            confirmed = len([a for a in alts if a[5] == 'confirmed'])
            e.add_field(name="🔍 Détections", value=f"⚠️ {suspected} suspects\n✅ {confirmed} confirmés", inline=False)
        
        # Salon de log
        log_ch = self.g.get_channel(c.get(f'log_{self.key}', 0))
        e.add_field(name="📜 Salon de log", value=log_ch.mention if log_ch else "❌ Non configuré", inline=False)
        
        return e
    
    @discord.ui.button(label="🔄 ON/OFF", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        c = await cfg(self.g.id)
        await db_set(self.g.id, self.key, 0 if c.get(self.key) else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="⚙️ Configurer", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        if self.key == "anti_image":
            v = ImageConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_badwords":
            v = BadwordsConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_link":
            v = LinkConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key in ["anti_spam", "anti_caps", "anti_newaccount"]:
            await i.response.send_modal(NumberConfigModal(self.g, self.u, self.key))
        elif self.key in ["anti_phishing", "anti_scam", "anti_compromised", "anti_qrcode"]:
            v = ActionConfigPanel(self.u, self.g, self.key)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_raid":
            v = AntiRaidConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_alt":
            v = AltConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        else:
            await i.response.send_message("ℹ️ Pas de configuration supplémentaire", ephemeral=True)
    
    @discord.ui.button(label="📜 Définir Log", style=discord.ButtonStyle.secondary, row=0)
    async def set_log(self, i, b):
        try:
            total_channels = len(list(self.g.text_channels))
            v = LogSelectView(self.u, self.g, self.key, self.prot)
            await i.response.edit_message(
                embed=discord.Embed(
                    title="📜 Choisir le salon de log",
                    description=f"Pour la protection **{self.prot[2]}**\n\n📊 {total_channels} salons disponibles",
                    color=C.PURPLE
                ),
                view=v
            )
        except Exception as ex:
            print(f"[LOG SELECT ERROR] {ex}")
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LogSelectView(View):
    """Sélecteur de salon de log PAGINÉ pour supporter tous les salons"""
    def __init__(self, u, g, key, prot, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.key = key
        self.prot = prot
        self.page = page
        self.channels = list(g.text_channels)
        self.max_page = max(0, (len(self.channels) - 1) // 23)  # 23 salons par page + option "Aucun"
        
        self._build()
    
    def _build(self):
        # Nettoyer les anciens items
        self.clear_items()
        
        # Calculer les salons de cette page
        start = self.page * 23
        end = start + 23
        page_channels = self.channels[start:end]
        
        # Construire les options
        opts = []
        if self.page == 0:
            opts.append(discord.SelectOption(label="❌ Aucun log", value="0", emoji="🚫"))
        
        for ch in page_channels:
            desc = ch.category.name[:50] if ch.category else "Sans catégorie"
            opts.append(discord.SelectOption(
                label=f"# {ch.name}"[:25],
                value=str(ch.id),
                description=desc
            ))
        
        if opts:
            select = LogChannelSelectMenu(self, opts)
            self.add_item(select)
        
        # Boutons de navigation
        if self.max_page > 0:
            prev_btn = discord.ui.Button(
                label="◀️ Préc.",
                style=discord.ButtonStyle.primary,
                disabled=(self.page == 0),
                row=1
            )
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            # Indicateur de page
            page_btn = discord.ui.Button(
                label=f"{self.page + 1}/{self.max_page + 1}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                row=1
            )
            self.add_item(page_btn)
            
            next_btn = discord.ui.Button(
                label="Suiv. ▶️",
                style=discord.ButtonStyle.primary,
                disabled=(self.page >= self.max_page),
                row=1
            )
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        # Bouton retour
        back_btn = discord.ui.Button(
            label="◀️ Retour",
            style=discord.ButtonStyle.danger,
            row=2
        )
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        self.page -= 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def next_page(self, i):
        self.page += 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def go_back(self, i):
        v = ProtDetail(self.u, self.g, self.prot)
        await i.response.edit_message(content=None, embed=await v.embed(), view=v)

class LogChannelSelectMenu(Select):
    def __init__(self, parent, opts):
        super().__init__(
            placeholder=f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un salon...",
            options=opts
        )
        self.parent = parent
    
    async def callback(self, i):
        try:
            channel_id = int(self.values[0])
            await db_set(i.guild.id, f'log_{self.parent.key}', channel_id)
            
            if channel_id == 0:
                msg = f"✅ Logs désactivés pour **{self.parent.prot[2]}**"
            else:
                ch = i.guild.get_channel(channel_id)
                msg = f"✅ Logs de **{self.parent.prot[2]}** définis dans {ch.mention if ch else 'salon inconnu'}"
            
            v = ProtDetail(self.parent.u, self.parent.g, self.parent.prot)
            await i.response.edit_message(content=msg, embed=await v.embed(), view=v)
        except Exception as ex:
            print(f"[LOG SELECT ERROR] {ex}")
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🖼️ ANTI-IMAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ImageConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy']
        e = discord.Embed(title="🖼️ Formats autorisés", color=C.BLUE)
        lines = []
        for f in fmts:
            status = "✅ Autorisé" if f in items else "❌ Bloqué"
            lines.append(f"`{f.upper()}` : {status}")
        e.description = "\n".join(lines)
        e.set_footer(text="Cliquez sur un format pour le toggle")
        return e
    
    @discord.ui.select(
        placeholder="Sélectionner un format à toggle...",
        options=[
            discord.SelectOption(label="PNG", value="png", emoji="🖼️"),
            discord.SelectOption(label="JPG", value="jpg", emoji="🖼️"),
            discord.SelectOption(label="JPEG", value="jpeg", emoji="🖼️"),
            discord.SelectOption(label="GIF (fichier)", value="gif", emoji="🎞️"),
            discord.SelectOption(label="WEBP", value="webp", emoji="🖼️"),
            discord.SelectOption(label="Tenor", value="tenor", emoji="🎬"),
            discord.SelectOption(label="Giphy", value="giphy", emoji="🎬")
        ]
    )
    async def toggle_format(self, i, s):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmt = s.values[0]
        if fmt in items:
            items.remove(fmt)
        else:
            items.append(fmt)
        await db_set(self.g.id, 'image_allowed', items)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="✅ Tout autoriser", style=discord.ButtonStyle.success, row=1)
    async def allow_all(self, i, b):
        await db_set(self.g.id, 'image_allowed', ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy'])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="❌ Tout bloquer", style=discord.ButtonStyle.danger, row=1)
    async def block_all(self, i, b):
        await db_set(self.g.id, 'image_allowed', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_image")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🤬 ANTI-BADWORDS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class BadwordsConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        words = c.get('badwords_list', [])
        e = discord.Embed(title="🤬 Mots interdits", color=C.BLUE)
        if words:
            # Afficher tous les mots avec pagination si nécessaire
            all_words = ", ".join([f"`{w}`" for w in words])
            if len(all_words) > 4000:
                all_words = all_words[:4000] + "..."
            e.description = f"**{len(words)} mot(s) configuré(s):**\n\n{all_words}"
        else:
            e.description = "*Aucun mot interdit configuré*\n\nCliquez sur ➕ Ajouter pour ajouter des mots."
        return e
    
    @discord.ui.button(label="➕ Ajouter des mots", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddBadwordsModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer tout", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, i, b):
        await db_set(self.g.id, 'badwords_list', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_badwords")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddBadwordsModal(Modal, title="➕ Ajouter des mots interdits"):
    words = TextInput(
        label="Mots (séparés par des virgules)",
        placeholder="mot1, mot2, mot3, expression interdite, ...",
        style=discord.TextStyle.paragraph,
        max_length=4000
    )
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('badwords_list', [])
        new = [x.strip().lower() for x in self.words.value.split(',') if x.strip()]
        added = 0
        for w in new:
            if w and w not in items:
                items.append(w)
                added += 1
        await db_set(self.g.id, 'badwords_list', items)
        v = BadwordsConfigPanel(self.u, self.g)
        await i.response.edit_message(content=f"✅ {added} mot(s) ajouté(s)!", embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔗 ANTI-LINK CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔗 Configuration Anti-Liens", color=C.BLUE)
        
        wl = c.get('link_whitelist', [])
        e.add_field(
            name=f"🌐 Whitelist domaines ({len(wl)})",
            value=f"`{', '.join(wl)}`" if wl else "*Aucun domaine autorisé*",
            inline=False
        )
        
        chs = c.get('link_allowed_channels', [])
        ch_txt = ", ".join([f"<#{x}>" for x in chs]) if chs else "*Aucun salon*"
        e.add_field(
            name=f"📍 Salons autorisés ({len(chs)})",
            value=ch_txt,
            inline=False
        )
        
        return e
    
    @discord.ui.button(label="➕ Ajouter domaines", style=discord.ButtonStyle.success, row=0)
    async def add_domain(self, i, b):
        await i.response.send_modal(AddDomainModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Vider whitelist", style=discord.ButtonStyle.danger, row=0)
    async def clear_wl(self, i, b):
        await db_set(self.g.id, 'link_whitelist', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="➕ Ajouter salon", style=discord.ButtonStyle.primary, row=1)
    async def add_chan(self, i, b):
        total_channels = len(list(self.g.text_channels))
        v = PaginatedLinkChanSelectView(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Choisir un salon à autoriser",
                description=f"📊 {total_channels} salons disponibles",
                color=C.PURPLE
            ),
            view=v
        )
    
    @discord.ui.button(label="🗑️ Vider salons", style=discord.ButtonStyle.danger, row=1)
    async def clear_chs(self, i, b):
        await db_set(self.g.id, 'link_allowed_channels', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_link")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddDomainModal(Modal, title="➕ Ajouter des domaines"):
    doms = TextInput(
        label="Domaines (séparés par des virgules)",
        placeholder="youtube.com, twitter.com, trello.com",
        style=discord.TextStyle.paragraph,
        max_length=2000
    )
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('link_whitelist', [])
        
        # Nettoyer et normaliser les domaines
        new_domains = []
        for x in self.doms.value.split(','):
            domain = x.strip().lower()
            # Enlever http:// ou https:// si présent
            domain = re.sub(r'^https?://', '', domain)
            # Enlever les / finaux
            domain = domain.rstrip('/')
            # Enlever www. si présent
            if domain.startswith('www.'):
                domain = domain[4:]
            if domain and domain not in items and domain not in new_domains:
                new_domains.append(domain)
        
        # Ajouter les nouveaux domaines
        items.extend(new_domains)
        await db_set(self.g.id, 'link_whitelist', items)
        
        v = LinkConfigPanel(self.u, self.g)
        if new_domains:
            await i.response.edit_message(
                content=f"✅ **{len(new_domains)} domaine(s) ajouté(s) !**\n`{', '.join(new_domains)}`",
                embed=await v.embed(), 
                view=v
            )
        else:
            await i.response.edit_message(
                content="⚠️ Aucun nouveau domaine ajouté (déjà présents ou invalides)",
                embed=await v.embed(), 
                view=v
            )

class PaginatedLinkChanSelectView(View):
    """Sélecteur de salon paginé pour les liens autorisés"""
    def __init__(self, u, g, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.page = page
        self.channels = list(g.text_channels)
        self.max_page = max(0, (len(self.channels) - 1) // 24)
        self._build()
    
    def _build(self):
        self.clear_items()
        
        start = self.page * 24
        end = start + 24
        page_channels = self.channels[start:end]
        
        opts = []
        for ch in page_channels:
            desc = ch.category.name[:50] if ch.category else "Sans catégorie"
            opts.append(discord.SelectOption(
                label=f"# {ch.name}"[:25],
                value=str(ch.id),
                description=desc
            ))
        
        if opts:
            select = LinkChanSelectMenu(self, opts)
            self.add_item(select)
        
        # Navigation
        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            page_btn = discord.ui.Button(label=f"{self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(page_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page), row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        self.page -= 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def next_page(self, i):
        self.page += 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def go_back(self, i):
        v = LinkConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LinkChanSelectMenu(Select):
    def __init__(self, parent, opts):
        super().__init__(placeholder=f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un salon...", options=opts)
        self.parent = parent
    
    async def callback(self, i):
        c = await cfg(i.guild.id)
        chs = c.get('link_allowed_channels', [])
        chid = int(self.values[0])
        ch = i.guild.get_channel(chid)
        if chid not in chs:
            chs.append(chid)
            await db_set(i.guild.id, 'link_allowed_channels', chs)
        v = LinkConfigPanel(self.parent.u, self.parent.g)
        await i.response.edit_message(
            content=f"✅ Salon **{ch.name if ch else 'inconnu'}** ajouté aux salons autorisés",
            embed=await v.embed(),
            view=v
        )

# Garder l'ancienne classe pour compatibilité
class LinkChanSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(LinkChanSelect(u, g, opts))

class LinkChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        c = await cfg(i.guild.id)
        chs = c.get('link_allowed_channels', [])
        chid = int(self.values[0])
        if chid not in chs:
            chs.append(chid)
            await db_set(i.guild.id, 'link_allowed_channels', chs)
        v = LinkConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚙️ NUMBER CONFIG MODAL
# ═══════════════════════════════════════════════════════════════════════════════

class NumberConfigModal(Modal, title="⚙️ Configuration"):
    val = TextInput(label="Valeur", placeholder="5", max_length=3)
    
    def __init__(self, g, u, key):
        super().__init__()
        self.g = g
        self.u = u
        self.key = key
        if key == "anti_spam":
            self.val.label = "Nombre max de messages"
            self.val.placeholder = "5"
        elif key == "anti_caps":
            self.val.label = "Pourcentage max de majuscules"
            self.val.placeholder = "70"
        elif key == "anti_newaccount":
            self.val.label = "Âge minimum du compte (jours)"
            self.val.placeholder = "7"
    
    async def on_submit(self, i):
        v = int(self.val.value) if self.val.value.isdigit() else 5
        if self.key == "anti_spam":
            await db_set(self.g.id, 'spam_max', max(1, min(20, v)))
        elif self.key == "anti_caps":
            await db_set(self.g.id, 'caps_percent', max(10, min(100, v)))
        elif self.key == "anti_newaccount":
            await db_set(self.g.id, 'newaccount_days', max(1, min(365, v)))
        prot = next(p for p in PROTS if p[0] == self.key)
        vw = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await vw.embed(), view=vw)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚡ ACTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ActionConfigPanel(View):
    def __init__(self, u, g, key):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.key = key
    
    def _get_action_key(self):
        """Retourne la clé de configuration pour l'action"""
        action_keys = {
            'anti_phishing': 'phishing_action',
            'anti_scam': 'scam_action',
            'anti_compromised': 'compromised_action',
            'anti_qrcode': 'qrcode_action',
        }
        return action_keys.get(self.key, f'{self.key.replace("anti_", "")}_action')
    
    def _get_default_action(self):
        """Retourne l'action par défaut"""
        defaults = {
            'anti_phishing': 'ban',
            'anti_scam': 'mute',
            'anti_compromised': 'mute',
            'anti_qrcode': 'mute',
        }
        return defaults.get(self.key, 'mute')
    
    async def embed(self):
        c = await cfg(self.g.id)
        ak = self._get_action_key()
        current = c.get(ak, self._get_default_action())
        
        name = self.key.replace('anti_', '').replace('_', ' ').title()
        e = discord.Embed(title=f"⚡ Action pour {name}", color=C.BLUE)
        e.description = f"**Action actuelle:** `{current.upper()}`\n\nChoisissez l'action à effectuer lorsqu'une violation est détectée:"
        
        e.add_field(name="🔇 Mute", value="Rend muet temporairement", inline=True)
        e.add_field(name="👢 Kick", value="Expulse du serveur", inline=True)
        e.add_field(name="🔨 Ban", value="Bannit définitivement", inline=True)
        
        return e
    
    @discord.ui.button(label="🔇 Mute", style=discord.ButtonStyle.primary, row=0)
    async def mute(self, i, b):
        await self._set(i, 'mute')
    
    @discord.ui.button(label="👢 Kick", style=discord.ButtonStyle.secondary, row=0)
    async def kick(self, i, b):
        await self._set(i, 'kick')
    
    @discord.ui.button(label="🔨 Ban", style=discord.ButtonStyle.danger, row=0)
    async def ban(self, i, b):
        await self._set(i, 'ban')
    
    async def _set(self, i, act):
        ak = self._get_action_key()
        await db_set(self.g.id, ak, act)
        prot = next(p for p in PROTS if p[0] == self.key)
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == self.key)
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚔️ ANTI-RAID CONFIG PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class AntiRaidConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        raid_cfg = c.get('raid_config', {})
        
        e = discord.Embed(title="⚔️ Configuration Anti-Raid", color=0xE74C3C)
        e.description = "Protégez votre serveur contre les attaques massives."
        
        # Seuil de détection
        e.add_field(
            name="👥 Seuil de détection",
            value=f"`{raid_cfg.get('join_threshold', 10)}` membres en `{raid_cfg.get('join_interval', 10)}` secondes",
            inline=False
        )
        
        # Âge minimum du compte
        e.add_field(
            name="📅 Âge minimum du compte",
            value=f"`{raid_cfg.get('min_account_age', 7)}` jours",
            inline=True
        )
        
        # Mode automatique
        auto_mode = raid_cfg.get('auto_mode', True)
        e.add_field(
            name="🤖 Mode automatique",
            value="✅ Oui" if auto_mode else "❌ Non",
            inline=True
        )
        
        # Bloquer les invitations
        block_invites = raid_cfg.get('block_invites', True)
        e.add_field(
            name="🔒 Bloquer invit.",
            value="✅ Oui" if block_invites else "❌ Non",
            inline=True
        )
        
        # Action
        action = raid_cfg.get('action', 'kick')
        actions_txt = {'kick': '👢 Kick', 'ban': '🔨 Ban', 'mute': '🔇 Mute'}
        e.add_field(name="⚡ Action", value=actions_txt.get(action, action), inline=True)
        
        # État du lockdown
        lockdown = raid_tracker.get(self.g.id, {}).get('lockdown', False)
        e.add_field(name="🚨 Lockdown", value="⚠️ **ACTIF**" if lockdown else "✅ Inactif", inline=True)
        
        return e
    
    @discord.ui.button(label="👥 Seuil", style=discord.ButtonStyle.primary, row=0)
    async def set_threshold(self, i, b):
        await i.response.send_modal(RaidThresholdModal(self.g, self.u))
    
    @discord.ui.button(label="📅 Âge", style=discord.ButtonStyle.primary, row=0)
    async def set_age(self, i, b):
        await i.response.send_modal(RaidAgeModal(self.g, self.u))
    
    @discord.ui.button(label="🤖 Auto", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_auto(self, i, b):
        c = await cfg(self.g.id)
        raid_cfg = c.get('raid_config', {})
        raid_cfg['auto_mode'] = not raid_cfg.get('auto_mode', True)
        await db_set(self.g.id, 'raid_config', raid_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="⚡ Action", style=discord.ButtonStyle.secondary, row=0)
    async def set_action(self, i, b):
        v = RaidActionSelect(self.u, self.g)
        await i.response.edit_message(embed=discord.Embed(title="⚡ Choisir l'action anti-raid", color=0xE74C3C), view=v)
    
    @discord.ui.button(label="🔒 Invit.", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_block(self, i, b):
        c = await cfg(self.g.id)
        raid_cfg = c.get('raid_config', {})
        raid_cfg['block_invites'] = not raid_cfg.get('block_invites', True)
        await db_set(self.g.id, 'raid_config', raid_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="🚨 Lockdown", style=discord.ButtonStyle.danger, row=1)
    async def manual_lockdown(self, i, b):
        guild_id = self.g.id
        if guild_id not in raid_tracker:
            raid_tracker[guild_id] = {'joins': [], 'lockdown': False}
        
        raid_tracker[guild_id]['lockdown'] = not raid_tracker[guild_id].get('lockdown', False)
        status = "🚨 **ACTIVÉ**" if raid_tracker[guild_id]['lockdown'] else "✅ **DÉSACTIVÉ**"
        
        await i.response.edit_message(embed=await self.embed(), view=self)
        await i.followup.send(f"Lockdown {status}", ephemeral=True)
    
    @discord.ui.button(label="🔍 Scanner", style=discord.ButtonStyle.success, row=1)
    async def scan_suspects(self, i, b):
        """Scanne le serveur pour détecter les comptes suspects"""
        try:
            # Répondre immédiatement avec un message de chargement
            await i.response.send_message("🔍 **Scan en cours...**\n\nAnalyse des membres du serveur...", ephemeral=True)
            
            # Créer le scanner et lancer le scan
            scanner = SuspectScanPanel(self.u, self.g)
            await scanner.scan_members()
            
            # Éditer le message avec les résultats
            await i.edit_original_response(
                content=None,
                embed=await scanner.embed(),
                view=scanner
            )
        except Exception as ex:
            import traceback
            error_details = traceback.format_exc()
            print(f"[SCANNER ERROR] {error_details}")
            try:
                await i.edit_original_response(
                    content=f"❌ **Erreur lors du scan**\n```{str(ex)[:500]}```",
                    embed=None,
                    view=None
                )
            except:
                pass
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_raid")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👥 ANTI-ALT CONFIG (Comptes Secondaires)
# ═══════════════════════════════════════════════════════════════════════════════

class AltConfigPanel(View):
    """Panel de configuration pour la détection de comptes secondaires"""
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        alt_cfg = c.get('alt_config', {})
        
        e = discord.Embed(title="👥 Configuration Anti-MultiCompte", color=0x9B59B6)
        e.description = (
            "Détecte et gère les comptes secondaires (alts).\n\n"
            "**Méthodes de détection :**\n"
            "• 🖼️ Avatar identique\n"
            "• 📝 Nom similaire\n"
            "• ⏰ Compte créé après un ban\n"
            "• 🔍 Comportement suspect"
        )
        
        # État
        enabled = c.get('anti_alt', 0)
        e.add_field(name="🔘 État", value="✅ ACTIVÉ" if enabled else "❌ DÉSACTIVÉ", inline=True)
        
        # Action
        action = c.get('alt_action', 'kick')
        action_emoji = {'kick': '👢', 'ban': '🔨', 'mute': '🔇'}.get(action, '⚡')
        e.add_field(name="⚡ Action", value=f"{action_emoji} {action.upper()}", inline=True)
        
        # Action auto
        auto = alt_cfg.get('auto_action', False)
        e.add_field(name="🤖 Action auto", value="✅ Activé" if auto else "❌ Désactivé", inline=True)
        
        # Confiance minimale
        min_conf = alt_cfg.get('min_confidence', 70)
        e.add_field(name="📊 Confiance minimum", value=f"{min_conf}%", inline=True)
        
        # Stats
        alts = await get_alt_accounts(self.g.id)
        suspected = len([a for a in alts if a[5] == 'suspected'])
        confirmed = len([a for a in alts if a[5] == 'confirmed'])
        actioned = len([a for a in alts if a[7]])  # action_taken non vide
        
        e.add_field(name="📈 Statistiques", value=(
            f"⚠️ **{suspected}** suspects\n"
            f"✅ **{confirmed}** confirmés\n"
            f"⚡ **{actioned}** sanctionnés"
        ), inline=True)
        
        e.set_footer(text="💡 Utilisez 'Scanner' pour analyser tous les membres")
        return e
    
    @discord.ui.button(label="🔄 ON/OFF", style=discord.ButtonStyle.success, row=0)
    async def toggle(self, i, b):
        c = await cfg(self.g.id)
        await db_set(self.g.id, 'anti_alt', 0 if c.get('anti_alt') else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="⚡ Action", style=discord.ButtonStyle.primary, row=0)
    async def set_action(self, i, b):
        c = await cfg(self.g.id)
        actions = ['kick', 'ban', 'mute']
        current = c.get('alt_action', 'kick')
        next_idx = (actions.index(current) + 1) % len(actions)
        await db_set(self.g.id, 'alt_action', actions[next_idx])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="🤖 Auto ON/OFF", style=discord.ButtonStyle.primary, row=0)
    async def toggle_auto(self, i, b):
        c = await cfg(self.g.id)
        alt_cfg = c.get('alt_config', {})
        alt_cfg['auto_action'] = not alt_cfg.get('auto_action', False)
        await db_set(self.g.id, 'alt_config', alt_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="📊 Confiance", style=discord.ButtonStyle.secondary, row=0)
    async def set_confidence(self, i, b):
        await i.response.send_modal(AltConfidenceModal(self.g, self.u))
    
    @discord.ui.button(label="🔍 Scanner", style=discord.ButtonStyle.success, row=1)
    async def scan_alts(self, i, b):
        """Scanne tous les membres pour détecter les comptes secondaires"""
        await i.response.send_message("🔍 **Scan des comptes secondaires en cours...**", ephemeral=True)
        
        try:
            detected = await scan_all_members_for_alts(self.g)
            
            if detected:
                v = AltScanResultsPanel(self.u, self.g, detected)
                await i.edit_original_response(
                    content=None,
                    embed=await v.embed(),
                    view=v
                )
            else:
                await i.edit_original_response(
                    content="✅ **Aucun compte secondaire détecté !**\n\nTous les membres semblent être des comptes uniques.",
                    embed=None,
                    view=None
                )
        except Exception as ex:
            print(f"[ALT SCAN ERROR] {ex}")
            await i.edit_original_response(content=f"❌ Erreur: {ex}")
    
    @discord.ui.button(label="📋 Voir détections", style=discord.ButtonStyle.secondary, row=1)
    async def view_detections(self, i, b):
        """Affiche les comptes secondaires déjà détectés"""
        alts = await get_alt_accounts(self.g.id)
        
        if not alts:
            return await i.response.send_message("📋 Aucun compte secondaire détecté pour le moment.", ephemeral=True)
        
        v = AltDetectionsPanel(self.u, self.g, alts)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_alt")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AltConfidenceModal(Modal, title="📊 Confiance minimum"):
    value = TextInput(
        label="Pourcentage de confiance (40-100)",
        placeholder="70",
        default="70",
        max_length=3
    )
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            val = int(self.value.value)
            val = max(40, min(100, val))
            
            c = await cfg(self.g.id)
            alt_cfg = c.get('alt_config', {})
            alt_cfg['min_confidence'] = val
            await db_set(self.g.id, 'alt_config', alt_cfg)
            
            v = AltConfigPanel(self.u, self.g)
            await i.response.edit_message(content=f"✅ Confiance minimum définie à **{val}%**", embed=await v.embed(), view=v)
        except:
            await i.response.send_message("❌ Valeur invalide", ephemeral=True)

class AltScanResultsPanel(View):
    """Affiche les résultats d'un scan de comptes secondaires"""
    def __init__(self, u, g, detected):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.detected = detected
        self.page = 0
        self.per_page = 5
    
    async def embed(self):
        e = discord.Embed(title="🔍 Résultats du Scan", color=0xE74C3C)
        
        total = len(self.detected)
        high_conf = len([d for d in self.detected if d['confidence'] >= 70])
        
        e.description = f"**{total}** comptes secondaires potentiels détectés\n**{high_conf}** avec haute confiance (≥70%)"
        
        # Pagination
        start = self.page * self.per_page
        end = start + self.per_page
        page_items = self.detected[start:end]
        
        for item in page_items:
            member = item['member']
            confidence = item['confidence']
            main_id = item['main_id']
            reasons = item['reasons']
            
            # Emoji de confiance
            if confidence >= 80:
                conf_emoji = "🔴"
            elif confidence >= 60:
                conf_emoji = "🟠"
            else:
                conf_emoji = "🟡"
            
            # Compte principal
            main_member = self.g.get_member(main_id)
            main_txt = f"{main_member.name}" if main_member else f"ID: {main_id} (banni/parti)"
            
            field_value = (
                f"**Confiance:** {conf_emoji} {confidence}%\n"
                f"**Compte principal:** {main_txt}\n"
                f"**Raisons:** {', '.join(reasons[:2])}"
            )
            
            e.add_field(
                name=f"👤 {member.display_name} (`{member.id}`)",
                value=field_value,
                inline=False
            )
        
        total_pages = max(1, (total - 1) // self.per_page + 1)
        e.set_footer(text=f"Page {self.page + 1}/{total_pages} • Cliquez sur les boutons pour agir")
        
        return e
    
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=0)
    async def prev_page(self, i, b):
        if self.page > 0:
            self.page -= 1
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, i, b):
        max_page = max(0, (len(self.detected) - 1) // self.per_page)
        if self.page < max_page:
            self.page += 1
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="👢 Kick tous (≥70%)", style=discord.ButtonStyle.danger, row=1)
    async def kick_high_conf(self, i, b):
        high_conf = [d for d in self.detected if d['confidence'] >= 70]
        if not high_conf:
            return await i.response.send_message("✅ Aucun compte avec ≥70% de confiance", ephemeral=True)
        
        v = ConfirmAltActionView(self.u, self.g, high_conf, 'kick')
        await i.response.send_message(
            embed=discord.Embed(
                title="⚠️ Confirmation",
                description=f"Voulez-vous **KICK** {len(high_conf)} compte(s) secondaire(s) avec ≥70% de confiance ?",
                color=0xE74C3C
            ),
            view=v,
            ephemeral=True
        )
    
    @discord.ui.button(label="🔨 Ban tous (≥80%)", style=discord.ButtonStyle.danger, row=1)
    async def ban_high_conf(self, i, b):
        very_high = [d for d in self.detected if d['confidence'] >= 80]
        if not very_high:
            return await i.response.send_message("✅ Aucun compte avec ≥80% de confiance", ephemeral=True)
        
        v = ConfirmAltActionView(self.u, self.g, very_high, 'ban')
        await i.response.send_message(
            embed=discord.Embed(
                title="⚠️ Confirmation",
                description=f"Voulez-vous **BAN** {len(very_high)} compte(s) secondaire(s) avec ≥80% de confiance ?",
                color=0xE74C3C
            ),
            view=v,
            ephemeral=True
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = AltConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ConfirmAltActionView(View):
    def __init__(self, u, g, targets, action):
        super().__init__(timeout=60)
        self.u = u
        self.g = g
        self.targets = targets
        self.action = action
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger, row=0)
    async def confirm(self, i, b):
        await i.response.edit_message(content="⏳ Exécution en cours...", embed=None, view=None)
        
        success = 0
        failed = 0
        
        for item in self.targets:
            member = item['member']
            try:
                if self.action == 'kick':
                    await member.kick(reason=f"Compte secondaire détecté (confiance: {item['confidence']}%)")
                elif self.action == 'ban':
                    await member.ban(reason=f"Compte secondaire détecté (confiance: {item['confidence']}%)")
                
                await update_alt_status(self.g.id, member.id, 'actioned', self.action)
                success += 1
            except:
                failed += 1
        
        await i.edit_original_response(
            content=f"✅ **{success}** compte(s) {self.action}{'s' if success > 1 else ''}\n❌ **{failed}** échec(s)"
        )
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Action annulée", embed=None, view=None)

class AltDetectionsPanel(View):
    """Affiche l'historique des détections de comptes secondaires"""
    def __init__(self, u, g, alts):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.alts = alts
        self.page = 0
        self.per_page = 5
    
    async def embed(self):
        e = discord.Embed(title="📋 Détections de Comptes Secondaires", color=0x9B59B6)
        
        if not self.alts:
            e.description = "*Aucune détection enregistrée*"
            return e
        
        # Pagination
        start = self.page * self.per_page
        end = start + self.per_page
        page_items = self.alts[start:end]
        
        for alt in page_items:
            # id, main_account_id, alt_account_id, confidence, reasons, status, detected_at, action_taken
            _, main_id, alt_id, confidence, reasons_json, status, detected_at, action_taken = alt
            
            try:
                reasons = json.loads(reasons_json) if reasons_json else []
            except:
                reasons = []
            
            # Status emoji
            status_emoji = {'suspected': '⚠️', 'confirmed': '✅', 'dismissed': '❌', 'actioned': '⚡'}.get(status, '❓')
            
            # Confiance emoji
            if confidence >= 80:
                conf_emoji = "🔴"
            elif confidence >= 60:
                conf_emoji = "🟠"
            else:
                conf_emoji = "🟡"
            
            # Membres
            alt_member = self.g.get_member(alt_id)
            main_member = self.g.get_member(main_id)
            
            alt_txt = f"{alt_member.name}" if alt_member else f"ID: {alt_id} (parti)"
            main_txt = f"{main_member.name}" if main_member else f"ID: {main_id}"
            
            field_value = (
                f"**Principal:** {main_txt}\n"
                f"**Confiance:** {conf_emoji} {confidence}%\n"
                f"**Status:** {status_emoji} {status}\n"
                f"**Raisons:** {', '.join(reasons[:2]) if reasons else 'N/A'}"
            )
            
            if action_taken:
                field_value += f"\n**Action:** {action_taken.upper()}"
            
            e.add_field(name=f"👤 {alt_txt}", value=field_value, inline=False)
        
        total_pages = max(1, (len(self.alts) - 1) // self.per_page + 1)
        e.set_footer(text=f"Page {self.page + 1}/{total_pages}")
        
        return e
    
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=0)
    async def prev_page(self, i, b):
        if self.page > 0:
            self.page -= 1
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, i, b):
        max_page = max(0, (len(self.alts) - 1) // self.per_page)
        if self.page < max_page:
            self.page += 1
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="🗑️ Effacer historique", style=discord.ButtonStyle.danger, row=1)
    async def clear_history(self, i, b):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('DELETE FROM alt_accounts WHERE guild_id = ?', (self.g.id,))
                await db.commit()
            await i.response.send_message("✅ Historique effacé", ephemeral=True)
            v = AltConfigPanel(self.u, self.g)
            await i.message.edit(embed=await v.embed(), view=v)
        except Exception as ex:
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AltConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SuspectScanPanel(View):
    """Panel pour scanner et afficher les comptes suspects"""
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.suspects = []
        self.bots = []
        self.page = 0
        self.per_page = 8
        self.scan_complete = False
    
    async def scan_members(self):
        """Scanne tous les membres pour détecter les comptes suspects"""
        self.suspects = []
        self.bots = []
        self.scan_complete = False
        
        try:
            # Récupérer la liste des membres
            members = list(self.g.members)
            print(f"[SCANNER] Scan de {len(members)} membres sur {self.g.name}")
            
            for member in members:
                try:
                    # Ignorer le bot lui-même
                    if member.id == bot.user.id:
                        continue
                    
                    if member.bot:
                        # Vérifier si c'est un bot non vérifié
                        try:
                            if not member.public_flags.verified_bot:
                                self.bots.append({
                                    'member': member,
                                    'reason': "Bot non vérifié par Discord",
                                    'severity': 'medium'
                                })
                        except:
                            pass
                        continue
                    
                    # Calculer le score de suspicion
                    suspicion_score = 0
                    reasons = []
                    
                    # 1. Âge du compte
                    try:
                        created = member.created_at
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=timezone.utc)
                        account_age = (now() - created).days
                        
                        if account_age < 1:
                            suspicion_score += 50
                            reasons.append(f"Créé aujourd'hui")
                        elif account_age < 7:
                            suspicion_score += 30
                            reasons.append(f"Compte récent ({account_age}j)")
                        elif account_age < 30:
                            suspicion_score += 10
                            reasons.append(f"Compte jeune ({account_age}j)")
                    except Exception as e:
                        print(f"[SCANNER] Erreur âge {member.id}: {e}")
                    
                    # 2. Pas d'avatar personnalisé
                    try:
                        if member.avatar is None:
                            suspicion_score += 15
                            reasons.append("Pas d'avatar")
                    except:
                        pass
                    
                    # 3. Nom suspect
                    try:
                        name = member.name.lower()
                        # Finit par des chiffres
                        if len(name) > 4 and name[-4:].isdigit():
                            suspicion_score += 10
                            reasons.append("Nom générique")
                        # Pattern de bot (User1234)
                        if re.match(r'^[a-z]+\d{4,}$', name):
                            suspicion_score += 20
                            reasons.append("Pattern bot")
                    except:
                        pass
                    
                    # 4. Flags Discord
                    try:
                        flags = member.public_flags
                        if flags.spammer:
                            suspicion_score += 100
                            reasons.append("🚨 SPAMMER Discord")
                    except:
                        pass
                    
                    # 5. Pas de rôles
                    try:
                        if len(member.roles) <= 1:
                            suspicion_score += 5
                            reasons.append("Aucun rôle")
                    except:
                        pass
                    
                    # 6. Rejoint récemment
                    try:
                        if member.joined_at:
                            joined = member.joined_at
                            if joined.tzinfo is None:
                                joined = joined.replace(tzinfo=timezone.utc)
                            joined_hours = (now() - joined).total_seconds() / 3600
                            if joined_hours < 1:
                                suspicion_score += 15
                                reasons.append("Rejoint < 1h")
                            elif joined_hours < 24:
                                suspicion_score += 5
                                reasons.append("Rejoint aujourd'hui")
                    except:
                        pass
                    
                    # Ajouter si score suffisant
                    if suspicion_score >= 15 and reasons:
                        severity = 'critical' if suspicion_score >= 80 else 'high' if suspicion_score >= 50 else 'medium' if suspicion_score >= 30 else 'low'
                        self.suspects.append({
                            'member': member,
                            'score': suspicion_score,
                            'reasons': reasons,
                            'severity': severity
                        })
                        
                except Exception as ex:
                    print(f"[SCANNER] Erreur membre {member.id}: {ex}")
                    continue
            
            # Trier par score décroissant
            self.suspects.sort(key=lambda x: x['score'], reverse=True)
            self.scan_complete = True
            print(f"[SCANNER] Terminé: {len(self.suspects)} suspects, {len(self.bots)} bots non vérifiés")
            
        except Exception as ex:
            print(f"[SCANNER] Erreur globale: {ex}")
            import traceback
            traceback.print_exc()
            self.scan_complete = True
    
    async def embed(self):
        e = discord.Embed(title="🔍 Scan des Comptes Suspects", color=0xE74C3C)
        
        # Résumé
        critical = len([s for s in self.suspects if s['severity'] == 'critical'])
        high = len([s for s in self.suspects if s['severity'] == 'high'])
        medium = len([s for s in self.suspects if s['severity'] == 'medium'])
        
        summary = f"**🚨 Critiques:** {critical}\n**⚠️ Élevés:** {high}\n**⚡ Moyens:** {medium}\n**🤖 Bots non vérifiés:** {len(self.bots)}"
        e.add_field(name="📊 Résumé", value=summary, inline=False)
        
        # Liste des suspects (paginée)
        if self.suspects:
            start = self.page * self.per_page
            end = start + self.per_page
            page_suspects = self.suspects[start:end]
            
            lines = []
            for s in page_suspects:
                member = s['member']
                severity_emoji = {'critical': '🚨', 'high': '⚠️', 'medium': '⚡', 'low': '📋'}.get(s['severity'], '📋')
                reasons_short = ", ".join(s['reasons'][:2])
                lines.append(f"{severity_emoji} **{member.display_name}** (`{member.id}`)\n   └ {reasons_short}")
            
            e.add_field(
                name=f"👥 Suspects ({len(self.suspects)}) - Page {self.page + 1}/{max(1, (len(self.suspects) - 1) // self.per_page + 1)}",
                value="\n".join(lines) if lines else "*Aucun*",
                inline=False
            )
        else:
            e.add_field(name="👥 Suspects", value="✅ Aucun compte suspect détecté !", inline=False)
        
        # Bots non vérifiés
        if self.bots:
            bot_lines = [f"🤖 **{b['member'].name}** (`{b['member'].id}`)" for b in self.bots[:5]]
            if len(self.bots) > 5:
                bot_lines.append(f"*... et {len(self.bots) - 5} autres*")
            e.add_field(name="🤖 Bots non vérifiés", value="\n".join(bot_lines), inline=False)
        
        e.set_footer(text="⚠️ Vérifiez manuellement avant d'agir • Les scores sont indicatifs")
        return e
    
    @discord.ui.button(label="◀️ Préc.", style=discord.ButtonStyle.secondary, row=0)
    async def prev_page(self, i, b):
        if self.page > 0:
            self.page -= 1
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="▶️ Suiv.", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, i, b):
        max_page = max(0, (len(self.suspects) - 1) // self.per_page)
        if self.page < max_page:
            self.page += 1
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="🔄 Re-scanner", style=discord.ButtonStyle.primary, row=0)
    async def rescan(self, i, b):
        await i.response.defer()
        await self.scan_members()
        await i.edit_original_response(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="👢 Kick Critiques", style=discord.ButtonStyle.danger, row=1)
    async def kick_critical(self, i, b):
        critical = [s for s in self.suspects if s['severity'] == 'critical']
        if not critical:
            return await i.response.send_message("✅ Aucun compte critique à kick", ephemeral=True)
        
        v = ConfirmKickView(self.u, self.g, critical, 'critical')
        await i.response.send_message(
            embed=discord.Embed(
                title="⚠️ Confirmer le kick",
                description=f"Vous allez kick **{len(critical)}** compte(s) critique(s).\n\nÊtes-vous sûr ?",
                color=0xFF0000
            ),
            view=v,
            ephemeral=True
        )
    
    @discord.ui.button(label="🤖 Kick Bots", style=discord.ButtonStyle.danger, row=1)
    async def kick_bots(self, i, b):
        if not self.bots:
            return await i.response.send_message("✅ Aucun bot non vérifié à kick", ephemeral=True)
        
        v = ConfirmKickView(self.u, self.g, self.bots, 'bots')
        await i.response.send_message(
            embed=discord.Embed(
                title="⚠️ Confirmer le kick des bots",
                description=f"Vous allez kick **{len(self.bots)}** bot(s) non vérifié(s).\n\nÊtes-vous sûr ?",
                color=0xFF0000
            ),
            view=v,
            ephemeral=True
        )
    
    @discord.ui.button(label="👢 Kick Tous Suspects", style=discord.ButtonStyle.danger, row=1)
    async def kick_all(self, i, b):
        high_and_critical = [s for s in self.suspects if s['severity'] in ['critical', 'high']]
        if not high_and_critical:
            return await i.response.send_message("✅ Aucun compte à kick", ephemeral=True)
        
        v = ConfirmKickView(self.u, self.g, high_and_critical, 'all')
        await i.response.send_message(
            embed=discord.Embed(
                title="⚠️ Confirmer le kick massif",
                description=f"Vous allez kick **{len(high_and_critical)}** compte(s) suspects (critiques + élevés).\n\n**⚠️ Cette action est irréversible !**",
                color=0xFF0000
            ),
            view=v,
            ephemeral=True
        )
    
    @discord.ui.button(label="❌ Fermer", style=discord.ButtonStyle.secondary, row=2)
    async def close(self, i, b):
        await i.response.edit_message(content="✅ Scan fermé", embed=None, view=None)

class ConfirmKickView(View):
    """Vue de confirmation pour kick les suspects"""
    def __init__(self, u, g, targets, kick_type):
        super().__init__(timeout=60)
        self.u = u
        self.g = g
        self.targets = targets
        self.kick_type = kick_type
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        await i.response.defer()
        
        kicked = 0
        failed = 0
        
        for t in self.targets:
            member = t['member']
            try:
                reason = f"Anti-Raid: {t.get('reason', 'Compte suspect')} (score: {t.get('score', 'N/A')})"
                await member.kick(reason=reason)
                kicked += 1
            except:
                failed += 1
        
        await i.edit_original_response(
            embed=discord.Embed(
                title="✅ Kick terminé",
                description=f"**{kicked}** membre(s) kick\n**{failed}** échec(s)",
                color=0x2ECC71 if failed == 0 else 0xE67E22
            ),
            view=None
        )
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Kick annulé", embed=None, view=None)

class RaidThresholdModal(Modal, title="👥 Seuil de détection"):
    threshold_input = TextInput(label="Nombre de membres", placeholder="10", max_length=3)
    interval_input = TextInput(label="Intervalle (secondes)", placeholder="10", max_length=3)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            threshold = max(3, min(50, int(self.threshold_input.value)))
            interval = max(5, min(60, int(self.interval_input.value)))
            c = await cfg(self.g.id)
            raid_cfg = c.get('raid_config', {})
            raid_cfg['join_threshold'] = threshold
            raid_cfg['join_interval'] = interval
            await db_set(self.g.id, 'raid_config', raid_cfg)
        except:
            pass
        v = AntiRaidConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RaidAgeModal(Modal, title="📅 Âge minimum du compte"):
    age_input = TextInput(label="Jours minimum", placeholder="7", max_length=4)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            age = max(0, min(365, int(self.age_input.value)))
            c = await cfg(self.g.id)
            raid_cfg = c.get('raid_config', {})
            raid_cfg['min_account_age'] = age
            await db_set(self.g.id, 'raid_config', raid_cfg)
        except:
            pass
        v = AntiRaidConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RaidActionSelect(View):
    def __init__(self, u, g):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
    
    @discord.ui.button(label="👢 Kick", style=discord.ButtonStyle.primary)
    async def kick(self, i, b):
        await self._set(i, 'kick')
    
    @discord.ui.button(label="🔨 Ban", style=discord.ButtonStyle.danger)
    async def ban(self, i, b):
        await self._set(i, 'ban')
    
    @discord.ui.button(label="🔇 Mute", style=discord.ButtonStyle.secondary)
    async def mute(self, i, b):
        await self._set(i, 'mute')
    
    async def _set(self, i, action):
        c = await cfg(self.g.id)
        raid_cfg = c.get('raid_config', {})
        raid_cfg['action'] = action
        await db_set(self.g.id, 'raid_config', raid_cfg)
        v = AntiRaidConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AntiRaidConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔨 MODÉRATION PANEL
# ═══════════════════════════════════════════════════════════════════════════════

async def send_mod_log(guild, action, mod, target, reason=None, duration=None, extra=None):
    """Envoie un log de modération"""
    try:
        c = await cfg(guild.id)
        log_ch = guild.get_channel(c.get('mod_log_channel', 0))
        if not log_ch:
            return
        
        colors = {'warn': C.YELLOW, 'unwarn': C.GREEN, 'mute': C.ORANGE, 'unmute': C.GREEN, 'infractions': C.BLUE}
        emojis = {'warn': '⚠️', 'unwarn': '✅', 'mute': '🔇', 'unmute': '🔊', 'infractions': '📋'}
        titles = {'warn': 'Avertissement', 'unwarn': 'Warn supprimé', 'mute': 'Mute', 'unmute': 'Unmute', 'infractions': 'Consultation infractions'}
        
        e = discord.Embed(
            title=f"{emojis.get(action, '🔨')} {titles.get(action, action.upper())}",
            color=colors.get(action, C.ORANGE),
            timestamp=now()
        )
        e.add_field(name="👮 Modérateur", value=f"{mod.mention}\n`{mod.id}`", inline=True)
        e.add_field(name="👤 Membre", value=f"{target.mention}\n`{target.id}`", inline=True)
        
        if duration:
            e.add_field(name="⏱️ Durée", value=duration, inline=True)
        if reason:
            e.add_field(name="📝 Raison", value=reason[:1024], inline=False)
        if extra:
            e.add_field(name="ℹ️ Info", value=extra, inline=False)
        
        e.set_thumbnail(url=target.display_avatar.url)
        await log_ch.send(embed=e)
    except Exception as ex:
        print(f"[MOD LOG ERROR] {ex}")

class ModerationPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔨 Modération", color=C.ORANGE)
        e.description = "Configurez les rôles et logs pour les commandes de modération."
        
        # Salon logs
        log_ch = self.g.get_channel(c.get('mod_log_channel', 0))
        e.add_field(
            name="📜 Salon Logs",
            value=log_ch.mention if log_ch else "❌ Non configuré",
            inline=False
        )
        
        # Warn
        warn_role = self.g.get_role(c.get('mod_warn_role', 0))
        e.add_field(
            name="⚠️ /warn & /unwarn",
            value=f"Rôle: {warn_role.mention if warn_role else '❌ Non configuré'}",
            inline=True
        )
        
        # Mute
        mute_role = self.g.get_role(c.get('mod_mute_role', 0))
        e.add_field(
            name="🔇 /mute & /unmute",
            value=f"Rôle: {mute_role.mention if mute_role else '❌ Non configuré'}",
            inline=True
        )
        
        # Infractions
        inf_role = self.g.get_role(c.get('mod_infractions_role', 0))
        e.add_field(
            name="📋 /infractions",
            value=f"Rôle: {inf_role.mention if inf_role else '❌ Non configuré'}",
            inline=True
        )
        
        e.set_footer(text="Les admins et le owner ont toujours accès à toutes les commandes")
        return e
    
    @discord.ui.button(label="📜 Salon Logs", style=discord.ButtonStyle.success, row=0)
    async def set_logs(self, i, b):
        try:
            async def callback(interaction, channel_id, extra):
                await db_set(interaction.guild.id, 'mod_log_channel', channel_id)
                v = ModerationPanel(self.u, self.g)
                ch = interaction.guild.get_channel(channel_id)
                await interaction.response.edit_message(
                    content=f"✅ Salon logs défini: **{ch.mention if ch else 'Aucun'}**",
                    embed=await v.embed(), view=v
                )
            
            v = UniversalChannelSelect(
                self.u, self.g,
                callback_func=callback,
                return_view_func=lambda: ModerationPanel(self.u, self.g),
                title="Salon Logs"
            )
            await i.response.edit_message(
                embed=discord.Embed(
                    title="📜 Salon des logs modération",
                    description=f"📊 {len(list(self.g.text_channels))} salons disponibles",
                    color=C.ORANGE
                ),
                view=v
            )
        except Exception as ex:
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    @discord.ui.button(label="⚠️ Rôle /warn", style=discord.ButtonStyle.primary, row=1)
    async def set_warn(self, i, b):
        try:
            async def callback(interaction, role_id, extra):
                await db_set(interaction.guild.id, 'mod_warn_role', role_id)
                v = ModerationPanel(self.u, self.g)
                role = interaction.guild.get_role(role_id)
                await interaction.response.edit_message(
                    content=f"✅ Rôle /warn défini: **{role.name if role else 'Aucun'}**",
                    embed=await v.embed(), view=v
                )
            
            v = UniversalRoleSelect(
                self.u, self.g,
                callback_func=callback,
                return_view_func=lambda: ModerationPanel(self.u, self.g),
                title="Rôle /warn",
                none_label="❌ Aucun rôle requis"
            )
            await i.response.edit_message(
                embed=discord.Embed(
                    title="⚠️ Rôle pour /warn & /unwarn",
                    description=f"Sélectionnez le rôle minimum requis.\n📊 {len([r for r in self.g.roles[1:] if not r.is_bot_managed()])} rôles disponibles",
                    color=C.ORANGE
                ),
                view=v
            )
        except Exception as ex:
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    @discord.ui.button(label="🔇 Rôle /mute", style=discord.ButtonStyle.primary, row=1)
    async def set_mute(self, i, b):
        try:
            async def callback(interaction, role_id, extra):
                await db_set(interaction.guild.id, 'mod_mute_role', role_id)
                v = ModerationPanel(self.u, self.g)
                role = interaction.guild.get_role(role_id)
                await interaction.response.edit_message(
                    content=f"✅ Rôle /mute défini: **{role.name if role else 'Aucun'}**",
                    embed=await v.embed(), view=v
                )
            
            v = UniversalRoleSelect(
                self.u, self.g,
                callback_func=callback,
                return_view_func=lambda: ModerationPanel(self.u, self.g),
                title="Rôle /mute",
                none_label="❌ Aucun rôle requis"
            )
            await i.response.edit_message(
                embed=discord.Embed(
                    title="🔇 Rôle pour /mute & /unmute",
                    description=f"Sélectionnez le rôle minimum requis.\n📊 {len([r for r in self.g.roles[1:] if not r.is_bot_managed()])} rôles disponibles",
                    color=C.ORANGE
                ),
                view=v
            )
        except Exception as ex:
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    @discord.ui.button(label="📋 Rôle /infractions", style=discord.ButtonStyle.primary, row=1)
    async def set_inf(self, i, b):
        try:
            async def callback(interaction, role_id, extra):
                await db_set(interaction.guild.id, 'mod_infractions_role', role_id)
                v = ModerationPanel(self.u, self.g)
                role = interaction.guild.get_role(role_id)
                await interaction.response.edit_message(
                    content=f"✅ Rôle /infractions défini: **{role.name if role else 'Aucun'}**",
                    embed=await v.embed(), view=v
                )
            
            v = UniversalRoleSelect(
                self.u, self.g,
                callback_func=callback,
                return_view_func=lambda: ModerationPanel(self.u, self.g),
                title="Rôle /infractions",
                none_label="❌ Aucun rôle requis"
            )
            await i.response.edit_message(
                embed=discord.Embed(
                    title="📋 Rôle pour /infractions",
                    description=f"Sélectionnez le rôle minimum requis.\n📊 {len([r for r in self.g.roles[1:] if not r.is_bot_managed()])} rôles disponibles",
                    color=C.ORANGE
                ),
                view=v
            )
        except Exception as ex:
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# Anciennes classes gardées pour compatibilité
class ModLogSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.add_item(ModLogSelect(u, g, opts))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ModLogSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'mod_log_channel', int(self.values[0]))
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ModRoleSelectView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.add_item(ModRoleSelect(u, g, opts, key))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ModRoleSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👑 IMMUNITÉS (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

class ImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,)) as c:
                rids = [r[0] for r in await c.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (self.g.id,)) as c:
                uids = [r[0] for r in await c.fetchall()]
            async with db.execute('SELECT channel_id FROM immune_channels WHERE guild_id=?', (self.g.id,)) as c:
                chids = [r[0] for r in await c.fetchall()]
        
        e = discord.Embed(title="👑 Immunités", color=C.YELLOW)
        e.description = (
            "Les éléments immunisés peuvent :\n"
            "✅ Envoyer des liens librement\n"
            "✅ Envoyer des images/GIFs partout\n"
            "✅ Envoyer des invitations Discord\n"
            "✅ Utiliser les majuscules librement\n\n"
            "⚠️ **Protection maintenue contre :**\n"
            "🎣 Phishing (protection critique)\n"
            "🚨 Scams (détection automatique)"
        )
        
        e.add_field(name=f"🎭 Rôles ({len(rids)})", value=", ".join([f"<@&{r}>" for r in rids[:10]]) or "*Aucun*", inline=False)
        e.add_field(name=f"👤 Utilisateurs ({len(uids)})", value=", ".join([f"<@{u}>" for u in uids[:10]]) or "*Aucun*", inline=False)
        e.add_field(name=f"📺 Salons ({len(chids)})", value=", ".join([f"<#{c}>" for c in chids[:10]]) or "*Aucun*", inline=False)
        
        e.set_footer(text="💡 Les tickets sont automatiquement immunisés (sauf phishing/scam)")
        return e
    
    @discord.ui.button(label="➕ Rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        total_roles = len([r for r in self.g.roles[1:] if not r.is_bot_managed()])
        v = PaginatedImmuneRoleView(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(
                title="👑 Ajouter un rôle immunisé",
                description=f"📊 {total_roles} rôles disponibles",
                color=C.YELLOW
            ),
            view=v
        )
    
    @discord.ui.button(label="➕ Utilisateur", style=discord.ButtonStyle.success, row=0)
    async def add_user(self, i, b):
        await i.response.send_modal(AddImmuneUserModal(self.g, self.u))
    
    @discord.ui.button(label="➕ Salon", style=discord.ButtonStyle.success, row=0)
    async def add_channel(self, i, b):
        total_channels = len(list(self.g.text_channels))
        v = PaginatedImmuneChannelView(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(
                title="📺 Ajouter un salon immunisé",
                description=f"Ce salon ignorera toutes les protections.\n\n📊 {total_channels} salons disponibles",
                color=C.YELLOW
            ),
            view=v
        )
    
    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=1)
    async def remove_item(self, i, b):
        # Créer une vue avec les options de suppression
        v = ImmuneRemoveView(self.u, self.g)
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer une immunité", description="Choisissez le type d'élément à supprimer.", color=C.RED), view=v)
    
    @discord.ui.button(label="🗑️ Tout supprimer", style=discord.ButtonStyle.danger, row=1)
    async def clear(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM immune_roles WHERE guild_id=?', (self.g.id,))
            await db.execute('DELETE FROM immune_users WHERE guild_id=?', (self.g.id,))
            await db.execute('DELETE FROM immune_channels WHERE guild_id=?', (self.g.id,))
            await db.commit()
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class PaginatedImmuneRoleView(View):
    """Sélecteur de rôle paginé pour les immunités"""
    def __init__(self, u, g, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.page = page
        self.roles = [r for r in g.roles[1:] if not r.is_bot_managed()]
        self.max_page = max(0, (len(self.roles) - 1) // 24)
        self._build()
    
    def _build(self):
        self.clear_items()
        
        start = self.page * 24
        end = start + 24
        page_roles = self.roles[start:end]
        
        opts = []
        for r in page_roles:
            opts.append(discord.SelectOption(
                label=f"@{r.name}"[:25],
                value=str(r.id),
                description=f"{len(r.members)} membres"[:50]
            ))
        
        if opts:
            select = ImmuneRoleSelectMenu(self, opts)
            self.add_item(select)
        
        # Navigation
        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            page_btn = discord.ui.Button(label=f"{self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(page_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page), row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        self.page -= 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def next_page(self, i):
        self.page += 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def go_back(self, i):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneRoleSelectMenu(Select):
    def __init__(self, parent, opts):
        super().__init__(placeholder=f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un rôle...", options=opts)
        self.parent = parent
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES(?,?)', (i.guild.id, int(self.values[0])))
            await db.commit()
        role = i.guild.get_role(int(self.values[0]))
        v = ImmunePanel(self.parent.u, self.parent.g)
        await i.response.edit_message(
            content=f"✅ Rôle **{role.name if role else 'inconnu'}** ajouté aux immunités",
            embed=await v.embed(),
            view=v
        )

class PaginatedImmuneChannelView(View):
    """Sélecteur de salon paginé pour les immunités"""
    def __init__(self, u, g, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.page = page
        self.channels = list(g.text_channels)
        self.max_page = max(0, (len(self.channels) - 1) // 24)
        self._build()
    
    def _build(self):
        self.clear_items()
        
        start = self.page * 24
        end = start + 24
        page_channels = self.channels[start:end]
        
        opts = []
        for ch in page_channels:
            desc = ch.category.name[:50] if ch.category else "Sans catégorie"
            opts.append(discord.SelectOption(
                label=f"# {ch.name}"[:25],
                value=str(ch.id),
                description=desc
            ))
        
        if opts:
            select = ImmuneChannelSelectMenu(self, opts)
            self.add_item(select)
        
        # Navigation
        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            page_btn = discord.ui.Button(label=f"{self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(page_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page), row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        self.page -= 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def next_page(self, i):
        self.page += 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def go_back(self, i):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneChannelSelectMenu(Select):
    def __init__(self, parent, opts):
        super().__init__(placeholder=f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un salon...", options=opts)
        self.parent = parent
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_channels VALUES(?,?)', (i.guild.id, int(self.values[0])))
            await db.commit()
        ch = i.guild.get_channel(int(self.values[0]))
        v = ImmunePanel(self.parent.u, self.parent.g)
        await i.response.edit_message(
            content=f"✅ Salon **{ch.name if ch else 'inconnu'}** ajouté aux immunités",
            embed=await v.embed(),
            view=v
        )

# Garder les anciennes classes pour compatibilité (mais elles ne seront plus utilisées)
class ImmuneRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.add_item(ImmuneRoleSelect(u, g, opts))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES(?,?)', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneChannelView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.add_item(ImmuneChannelSelect(u, g, opts))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneChannelSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_channels VALUES(?,?)', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneRemoveView(View):
    def __init__(self, u, g):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=0)
    async def remove_role(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,)) as c:
                rids = [r[0] for r in await c.fetchall()]
        if not rids:
            return await i.response.send_message("❌ Aucun rôle immunisé", ephemeral=True)
        opts = []
        for rid in rids[:25]:
            role = self.g.get_role(rid)
            opts.append(discord.SelectOption(label=f"@{role.name if role else rid}"[:25], value=str(rid)))
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un rôle", color=C.RED), view=ImmuneRemoveRoleView(self.u, self.g, opts))
    
    @discord.ui.button(label="👤 Utilisateur", style=discord.ButtonStyle.primary, row=0)
    async def remove_user(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (self.g.id,)) as c:
                uids = [r[0] for r in await c.fetchall()]
        if not uids:
            return await i.response.send_message("❌ Aucun utilisateur immunisé", ephemeral=True)
        opts = []
        for uid in uids[:25]:
            member = self.g.get_member(uid)
            opts.append(discord.SelectOption(label=f"@{member.display_name if member else uid}"[:25], value=str(uid)))
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un utilisateur", color=C.RED), view=ImmuneRemoveUserView(self.u, self.g, opts))
    
    @discord.ui.button(label="📺 Salon", style=discord.ButtonStyle.primary, row=0)
    async def remove_channel(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT channel_id FROM immune_channels WHERE guild_id=?', (self.g.id,)) as c:
                chids = [r[0] for r in await c.fetchall()]
        if not chids:
            return await i.response.send_message("❌ Aucun salon immunisé", ephemeral=True)
        opts = []
        for chid in chids[:25]:
            ch = self.g.get_channel(chid)
            opts.append(discord.SelectOption(label=f"# {ch.name if ch else chid}"[:25], value=str(chid)))
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un salon", color=C.RED), view=ImmuneRemoveChannelView(self.u, self.g, opts))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneRemoveRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ImmuneRemoveRoleSelect(u, g, opts))

class ImmuneRemoveRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle à supprimer...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM immune_roles WHERE guild_id=? AND role_id=?', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneRemoveUserView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ImmuneRemoveUserSelect(u, g, opts))

class ImmuneRemoveUserSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un utilisateur à supprimer...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM immune_users WHERE guild_id=? AND user_id=?', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImmuneRemoveChannelView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ImmuneRemoveChannelSelect(u, g, opts))

class ImmuneRemoveChannelSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon à supprimer...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM immune_channels WHERE guild_id=? AND channel_id=?', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddImmuneUserModal(Modal, title="➕ Ajouter un utilisateur immunisé"):
    uid = TextInput(label="ID de l'utilisateur", placeholder="123456789012345678")
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            user_id = int(self.uid.value)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT OR IGNORE INTO immune_users VALUES(?,?)', (self.g.id, user_id))
                await db.commit()
        except: pass
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚡ COMMANDES PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class CommandsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="⚡ Commandes Personnalisées", color=C.PURPLE)
        e.description = "Configurez les commandes spéciales du serveur."
        
        # RellSeas
        rellseas_user = self.g.get_member(c.get('rellseas_user', 0))
        rellseas_role = self.g.get_role(c.get('rellseas_role', 0))
        e.add_field(
            name="🎭 RellSeas",
            value=f"👤 {rellseas_user.mention if rellseas_user else '❌'}\n🎭 {rellseas_role.mention if rellseas_role else '❌'}",
            inline=True
        )
        
        # Suggestions
        sugg_role = self.g.get_role(c.get('suggestion_role', 0))
        sugg_ch = self.g.get_channel(c.get('suggestion_channel', 0))
        e.add_field(
            name="💡 Suggestions",
            value=f"🎭 {sugg_role.mention if sugg_role else 'Tous'}\n📍 {sugg_ch.mention if sugg_ch else '❌'}",
            inline=True
        )
        
        # Trade
        trade_role = self.g.get_role(c.get('trade_role', 0))
        trade_cd = c.get('trade_cooldown', 1)
        trade_unit = c.get('trade_cooldown_unit', 'heures')
        trade_allowed = c.get('trade_allowed_channels', [])
        trade_count = len(trade_allowed) if trade_allowed else 0
        e.add_field(
            name="🔄 Trade",
            value=f"🎭 {trade_role.mention if trade_role else 'Tous'}\n📌 {trade_count} salon(s)\n⏱️ {trade_cd} {trade_unit}",
            inline=True
        )
        
        return e
    
    @discord.ui.button(label="🎭 RellSeas", style=discord.ButtonStyle.primary, row=0)
    async def rellseas(self, i, b):
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="💡 Suggestions", style=discord.ButtonStyle.primary, row=0)
    async def suggestions(self, i, b):
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🔄 Trade", style=discord.ButtonStyle.primary, row=0)
    async def trade(self, i, b):
        v = TradePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎭 RELLSEAS
# ═══════════════════════════════════════════════════════════════════════════════

class RellSeasPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎭 Configuration RellSeas", color=C.PURPLE)
        
        rellseas_user = self.g.get_member(c.get('rellseas_user', 0))
        rellseas_role = self.g.get_role(c.get('rellseas_role', 0))
        warn_ch = self.g.get_channel(c.get('rellseas_warn_channel', 0))
        log_ch = self.g.get_channel(c.get('rellseas_log_channel', 0))
        
        e.description = "L'utilisateur autorisé reçoit **automatiquement** le rôle Realsy et peut le donner à d'autres."
        
        e.add_field(name="👤 Utilisateur autorisé", value=rellseas_user.mention if rellseas_user else "❌ Non configuré", inline=False)
        e.add_field(name="🎭 Rôle Realsy", value=rellseas_role.mention if rellseas_role else "❌ Non configuré", inline=False)
        e.add_field(name="⚠️ Salon warn", value=warn_ch.mention if warn_ch else "❌", inline=True)
        e.add_field(name="📜 Salon logs", value=log_ch.mention if log_ch else "❌", inline=True)
        
        e.set_footer(text="⏱️ 7 jours inactif = Warn | 14 jours = Rôle retiré")
        return e
    
    @discord.ui.button(label="👤 Utilisateur", style=discord.ButtonStyle.primary, row=0)
    async def set_user(self, i, b):
        await i.response.send_modal(RellSeasUserModal(self.g, self.u))
    
    @discord.ui.button(label="🎭 Rôle Realsy", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        async def callback(interaction, role_id, extra):
            await db_set(interaction.guild.id, 'rellseas_role', role_id)
            v = RellSeasPanel(self.u, self.g)
            role = interaction.guild.get_role(role_id)
            await interaction.response.edit_message(
                content=f"✅ Rôle Realsy défini: **{role.name if role else 'Aucun'}**",
                embed=await v.embed(), view=v
            )
        
        v = UniversalRoleSelect(
            self.u, self.g,
            callback_func=callback,
            return_view_func=lambda: RellSeasPanel(self.u, self.g),
            title="Rôle Realsy"
        )
        await i.response.edit_message(
            embed=discord.Embed(title="🎭 Choisir le rôle Realsy", description=f"📊 {len([r for r in self.g.roles[1:] if not r.is_bot_managed()])} rôles disponibles", color=C.PURPLE),
            view=v
        )
    
    @discord.ui.button(label="⚠️ Salon Warn", style=discord.ButtonStyle.secondary, row=1)
    async def set_warn_ch(self, i, b):
        async def callback(interaction, channel_id, extra):
            await db_set(interaction.guild.id, 'rellseas_warn_channel', channel_id)
            v = RellSeasPanel(self.u, self.g)
            ch = interaction.guild.get_channel(channel_id)
            await interaction.response.edit_message(
                content=f"✅ Salon warn défini: **{ch.mention if ch else 'Aucun'}**",
                embed=await v.embed(), view=v
            )
        
        v = UniversalChannelSelect(
            self.u, self.g,
            callback_func=callback,
            return_view_func=lambda: RellSeasPanel(self.u, self.g),
            title="Salon Warn"
        )
        await i.response.edit_message(
            embed=discord.Embed(title="⚠️ Salon des warns", description=f"📊 {len(list(self.g.text_channels))} salons disponibles", color=C.PURPLE),
            view=v
        )
    
    @discord.ui.button(label="📜 Salon Logs", style=discord.ButtonStyle.secondary, row=1)
    async def set_log_ch(self, i, b):
        async def callback(interaction, channel_id, extra):
            await db_set(interaction.guild.id, 'rellseas_log_channel', channel_id)
            v = RellSeasPanel(self.u, self.g)
            ch = interaction.guild.get_channel(channel_id)
            await interaction.response.edit_message(
                content=f"✅ Salon logs défini: **{ch.mention if ch else 'Aucun'}**",
                embed=await v.embed(), view=v
            )
        
        v = UniversalChannelSelect(
            self.u, self.g,
            callback_func=callback,
            return_view_func=lambda: RellSeasPanel(self.u, self.g),
            title="Salon Logs"
        )
        await i.response.edit_message(
            embed=discord.Embed(title="📜 Salon des logs", description=f"📊 {len(list(self.g.text_channels))} salons disponibles", color=C.PURPLE),
            view=v
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasUserModal(Modal, title="👤 Utilisateur RellSeas"):
    uid = TextInput(label="ID de l'utilisateur", placeholder="123456789012345678")
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            user_id = int(self.uid.value)
            await db_set(self.g.id, 'rellseas_user', user_id)
            
            # Donner automatiquement le rôle à l'utilisateur autorisé
            c = await cfg(self.g.id)
            role = self.g.get_role(c.get('rellseas_role', 0))
            member = self.g.get_member(user_id)
            
            if role and member and role not in member.roles:
                try:
                    await member.add_roles(role, reason="RellSeas - Utilisateur autorisé")
                    # Enregistrer dans le tracking
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('''INSERT OR REPLACE INTO realsy_tracking 
                            (guild_id, user_id, last_activity, warn_count) VALUES (?, ?, ?, 0)''',
                            (self.g.id, user_id, now().isoformat()))
                        await db.commit()
                except:
                    pass
        except:
            pass
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(RellSeasRoleSelect(u, g, opts))

class RellSeasRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'rellseas_role', int(self.values[0]))
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasChanView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(RellSeasChanSelect(u, g, opts, key))

class RellSeasChanSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           💡 SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class SuggestionPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="💡 Configuration Suggestions", color=C.PURPLE)
        
        sugg_role = self.g.get_role(c.get('suggestion_role', 0))
        sugg_ch = self.g.get_channel(c.get('suggestion_channel', 0))
        sugg_cd = c.get('suggestion_cooldown', 1)
        sugg_unit = c.get('suggestion_cooldown_unit', 'jours')
        
        # Salons autorisés pour la commande
        allowed_chs = c.get('suggestion_allowed_channels', [])
        if allowed_chs:
            ch_mentions = []
            for ch_id in allowed_chs[:5]:
                ch = self.g.get_channel(ch_id)
                if ch:
                    ch_mentions.append(ch.mention)
            allowed_txt = ", ".join(ch_mentions)
            if len(allowed_chs) > 5:
                allowed_txt += f" +{len(allowed_chs) - 5} autres"
        else:
            allowed_txt = "*Partout*"
        
        e.add_field(name="🎭 Rôle autorisé", value=sugg_role.mention if sugg_role else "*Tout le monde*", inline=True)
        e.add_field(name="⏱️ Cooldown", value=f"{sugg_cd} {sugg_unit}", inline=True)
        e.add_field(name="📍 Salon de publication", value=sugg_ch.mention if sugg_ch else "❌ Non configuré", inline=False)
        e.add_field(name="📌 Salons autorisés", value=allowed_txt, inline=False)
        
        e.set_footer(text="💡 /suggestion • Salon publication ≠ Salons où utiliser la commande")
        return e
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        v = PaginatedRoleSelect(self.u, self.g, 'suggestion_role', SuggestionPanel)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Rôle autorisé pour /suggestion", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📍 Salon publication", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedChannelSelect(self.u, self.g, 'suggestion_channel', SuggestionPanel)
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon de publication", description="Où les suggestions seront envoyées", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📌 Salons commande", style=discord.ButtonStyle.success, row=0)
    async def set_allowed_channels(self, i, b):
        c = await cfg(self.g.id)
        current = c.get('suggestion_allowed_channels', [])
        v = PaginatedChannelSelect(self.u, self.g, 'suggestion_allowed_channels', SuggestionPanel, multi=True, current_channels=current)
        await i.response.edit_message(embed=discord.Embed(
            title="📌 Salons autorisés pour /suggestion", 
            description="Sélectionnez les salons où la commande peut être utilisée.\n*Vide = partout*",
            color=C.PURPLE
        ), view=v)
    
    @discord.ui.button(label="⏱️ Cooldown", style=discord.ButtonStyle.secondary, row=1)
    async def set_cooldown(self, i, b):
        await i.response.send_modal(SuggCooldownModal(self.g, self.u))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# Sélecteur de rôle paginé
class PaginatedRoleSelect(View):
    def __init__(self, u, g, callback_key, return_panel_class, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.callback_key = callback_key
        self.return_panel_class = return_panel_class
        self.page = page
        self.roles = [r for r in g.roles[1:] if not r.is_bot_managed()]
        self.max_page = (len(self.roles) - 1) // 24
        
        self._build()
    
    def _build(self):
        start = self.page * 24
        end = start + 24
        page_roles = self.roles[start:end]
        
        opts = []
        if self.page == 0:
            opts.append(discord.SelectOption(label="❌ Aucun / Tout le monde", value="0"))
        
        for r in page_roles:
            opts.append(discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)))
        
        if opts:
            self.add_item(PaginatedRoleSelectMenu(self, opts))
        
        # Boutons de pagination
        if self.page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
        
        if self.page < self.max_page:
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        v = PaginatedRoleSelect(self.u, self.g, self.callback_key, self.return_panel_class, page=self.page - 1)
        await i.response.edit_message(view=v)
    
    async def next_page(self, i):
        v = PaginatedRoleSelect(self.u, self.g, self.callback_key, self.return_panel_class, page=self.page + 1)
        await i.response.edit_message(view=v)
    
    async def go_back(self, i):
        v = self.return_panel_class(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class PaginatedRoleSelectMenu(Select):
    def __init__(self, parent, opts):
        super().__init__(placeholder=f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un rôle...", options=opts)
        self.parent = parent
    
    async def callback(self, i):
        await db_set(self.parent.g.id, self.parent.callback_key, int(self.values[0]))
        v = self.parent.return_panel_class(self.parent.u, self.parent.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SuggCooldownModal(Modal, title="⏱️ Cooldown Suggestions"):
    duree = TextInput(label="Durée (nombre)", placeholder="1", default="1", max_length=3)
    unite = TextInput(label="Unité (jours ou semaines)", placeholder="jours", default="jours", max_length=10)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            cd = max(1, int(self.duree.value))
            unit = self.unite.value.lower()
            if unit not in ['jours', 'semaines']:
                unit = 'jours'
            await db_set(self.g.id, 'suggestion_cooldown', cd)
            await db_set(self.g.id, 'suggestion_cooldown_unit', unit)
        except: pass
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔄 TRADE PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class TradePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔄 Configuration Trade", color=C.PURPLE)
        
        trade_role = self.g.get_role(c.get('trade_role', 0))
        trade_cd = c.get('trade_cooldown', 1)
        trade_unit = c.get('trade_cooldown_unit', 'heures')
        
        # Salons autorisés pour la commande
        allowed_chs = c.get('trade_allowed_channels', [])
        if allowed_chs:
            ch_mentions = []
            for ch_id in allowed_chs[:5]:
                ch = self.g.get_channel(ch_id)
                if ch:
                    ch_mentions.append(ch.mention)
            allowed_txt = ", ".join(ch_mentions)
            if len(allowed_chs) > 5:
                allowed_txt += f" +{len(allowed_chs) - 5} autres"
        else:
            allowed_txt = "❌ Non configuré"
        
        e.description = "Configurez le système d'échange pour votre serveur.\n\n📢 *Les trades sont publiés dans le salon où la commande est utilisée.*"
        
        e.add_field(name="🎭 Rôle autorisé", value=trade_role.mention if trade_role else "*Tout le monde*", inline=True)
        e.add_field(name="⏱️ Cooldown", value=f"{trade_cd} {trade_unit}", inline=True)
        e.add_field(name="📌 Salons autorisés", value=allowed_txt, inline=False)
        
        e.set_footer(text="💡 /trade • Définissez les salons où la commande peut être utilisée")
        return e
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        v = PaginatedRoleSelect(self.u, self.g, 'trade_role', TradePanel)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Rôle autorisé pour /trade", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📌 Salons autorisés", style=discord.ButtonStyle.success, row=0)
    async def set_allowed_channels(self, i, b):
        c = await cfg(self.g.id)
        current = c.get('trade_allowed_channels', [])
        v = PaginatedChannelSelect(self.u, self.g, 'trade_allowed_channels', TradePanel, multi=True, current_channels=current)
        
        # Afficher les salons actuellement sélectionnés
        if current:
            selected_txt = ""
            for ch_id in current[:5]:
                ch = self.g.get_channel(ch_id)
                if ch:
                    selected_txt += f"• {ch.mention}\n"
            if len(current) > 5:
                selected_txt += f"*+{len(current) - 5} autres...*\n"
        else:
            selected_txt = "*Aucun salon sélectionné*"
        
        await i.response.edit_message(embed=discord.Embed(
            title="📌 Salons autorisés pour /trade", 
            description=(
                "**Sélectionnez les salons** où `/trade` peut être utilisée.\n\n"
                "👆 **Cliquez sur un salon** pour l'ajouter/retirer\n"
                "✅ **Cliquez sur Valider** pour sauvegarder\n\n"
                f"📋 **Actuellement sélectionnés ({len(current)}) :**\n{selected_txt}"
            ),
            color=C.PURPLE
        ), view=v)
    
    @discord.ui.button(label="⏱️ Cooldown", style=discord.ButtonStyle.secondary, row=1)
    async def set_cooldown(self, i, b):
        await i.response.send_modal(TradeCooldownModal(self.g, self.u))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TradeCooldownModal(Modal, title="⏱️ Cooldown Trade"):
    duree = TextInput(label="Durée (nombre)", placeholder="1", default="1", max_length=3)
    unite = TextInput(label="Unité (secondes/minutes/heures/jours)", placeholder="heures", default="heures", max_length=10)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            cd = max(1, int(self.duree.value))
            unit = self.unite.value.lower()
            if unit not in ['secondes', 'minutes', 'heures', 'jours', 'semaines']:
                unit = 'heures'
            await db_set(self.g.id, 'trade_cooldown', cd)
            await db_set(self.g.id, 'trade_cooldown_unit', unit)
        except:
            pass
        
        v = TradePanel(self.u, self.g)
        e = await v.embed()
        await i.response.edit_message(embed=e, view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 PUBLICITÉ / NOTIFICATIONS SOCIALES
# ═══════════════════════════════════════════════════════════════════════════════

# Cache pour éviter de republier les mêmes posts
posted_content = {}

class AdsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📢 Publicité & Notifications", color=C.PURPLE)
        e.description = "Recevez les dernières publications de vos créateurs préférés!"
        
        # YouTube
        yt_ch = self.g.get_channel(c.get('ads_youtube_channel', 0))
        yt_feeds = c.get('ads_youtube_feeds', [])
        e.add_field(
            name="🔴 YouTube",
            value=f"📍 {yt_ch.mention if yt_ch else '❌'}\n📺 {len(yt_feeds)} chaîne(s)",
            inline=True
        )
        
        # Twitch
        tw_ch = self.g.get_channel(c.get('ads_twitch_channel', 0))
        tw_feeds = c.get('ads_twitch_feeds', [])
        e.add_field(
            name="🟣 Twitch",
            value=f"📍 {tw_ch.mention if tw_ch else '❌'}\n🎮 {len(tw_feeds)} streamer(s)",
            inline=True
        )
        
        # Twitter/X
        x_ch = self.g.get_channel(c.get('ads_twitter_channel', 0))
        x_feeds = c.get('ads_twitter_feeds', [])
        e.add_field(
            name="🐦 Twitter/X",
            value=f"📍 {x_ch.mention if x_ch else '❌'}\n👤 {len(x_feeds)} compte(s)",
            inline=True
        )
        
        # Reddit
        rd_ch = self.g.get_channel(c.get('ads_reddit_channel', 0))
        rd_feeds = c.get('ads_reddit_feeds', [])
        e.add_field(
            name="🟠 Reddit",
            value=f"📍 {rd_ch.mention if rd_ch else '❌'}\n📰 {len(rd_feeds)} subreddit(s)",
            inline=True
        )
        
        # Discord
        dc_ch = self.g.get_channel(c.get('ads_discord_channel', 0))
        dc_feeds = c.get('ads_discord_feeds', [])
        e.add_field(
            name="📡 Discord",
            value=f"📍 {dc_ch.mention if dc_ch else '❌'}\n💬 {len(dc_feeds)} salon(s)",
            inline=True
        )
        
        # RoSocial
        rs_ch = self.g.get_channel(c.get('ads_rosocial_channel', 0))
        rs_feeds = c.get('ads_rosocial_feeds', [])
        e.add_field(
            name="🎮 RoSocial",
            value=f"📍 {rs_ch.mention if rs_ch else '❌'}\n👤 {len(rs_feeds)} profil(s)",
            inline=True
        )
        
        # Roblox UGC
        rblx_ch = self.g.get_channel(c.get('ads_roblox_channel', 0))
        rblx_feeds = c.get('ads_roblox_feeds', [])
        e.add_field(
            name="🟢 Roblox UGC",
            value=f"📍 {rblx_ch.mention if rblx_ch else '❌'}\n🎨 {len(rblx_feeds)} créateur(s)",
            inline=True
        )
        
        # Réductions Jeux
        deals_ch = self.g.get_channel(c.get('ads_deals_channel', 0))
        deals_enabled = c.get('ads_deals_enabled', False)
        e.add_field(
            name="🎯 Réductions",
            value=f"📍 {deals_ch.mention if deals_ch else '❌'}\n{'✅ Activé' if deals_enabled else '❌ Désactivé'}",
            inline=True
        )
        
        e.set_footer(text="💡 Les notifications sont vérifiées toutes les 5 minutes")
        return e
    
    @discord.ui.button(label="🔴 YouTube", style=discord.ButtonStyle.danger, row=0)
    async def youtube(self, i, b):
        v = AdsYouTubePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🟣 Twitch", style=discord.ButtonStyle.primary, row=0)
    async def twitch(self, i, b):
        v = AdsTwitchPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🐦 Twitter/X", style=discord.ButtonStyle.secondary, row=0)
    async def twitter(self, i, b):
        v = AdsTwitterPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🟠 Reddit", style=discord.ButtonStyle.secondary, row=0)
    async def reddit(self, i, b):
        v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📡 Discord", style=discord.ButtonStyle.primary, row=1)
    async def discord_btn(self, i, b):
        v = AdsDiscordPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🎮 RoSocial", style=discord.ButtonStyle.success, row=1)
    async def rosocial(self, i, b):
        v = AdsRoSocialPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🟢 Roblox UGC", style=discord.ButtonStyle.success, row=1)
    async def roblox_ugc(self, i, b):
        v = AdsRobloxPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🎯 Réductions", style=discord.ButtonStyle.primary, row=1)
    async def deals(self, i, b):
        v = AdsDealsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ─────────────────────────────── YOUTUBE ───────────────────────────────

class AdsYouTubePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔴 YouTube - Notifications", color=0xFF0000)
        
        yt_ch = self.g.get_channel(c.get('ads_youtube_channel', 0))
        yt_feeds = c.get('ads_youtube_feeds', [])
        
        e.add_field(name="📍 Salon par défaut", value=yt_ch.mention if yt_ch else "❌ Non configuré", inline=False)
        
        if yt_feeds:
            feeds_txt = ""
            for f in yt_feeds[:10]:
                # Support ancien et nouveau format
                if isinstance(f, dict):
                    name = f.get('name', '?')
                    feed_ch_id = f.get('channel_id', 0)
                    feed_ch = self.g.get_channel(feed_ch_id) if feed_ch_id else None
                    salon_txt = f" → {feed_ch.mention}" if feed_ch else ""
                    feeds_txt += f"• `{name}`{salon_txt}\n"
                else:
                    feeds_txt += f"• `{f}`\n"
            e.add_field(name=f"📺 Chaînes suivies ({len(yt_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="📺 Chaînes suivies", value="*Aucune chaîne configurée*", inline=False)
        
        e.set_footer(text="💡 Chaque chaîne peut avoir son propre salon de publication")
        return e
    
    @discord.ui.button(label="📍 Salon par défaut", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedAdsChannelSelect(self.u, self.g, 'ads_youtube_channel', 'youtube')
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Salon YouTube par défaut",
                description=f"📊 {len(list(self.g.text_channels))} salons disponibles",
                color=0xFF0000
            ),
            view=v
        )
    
    @discord.ui.button(label="➕ Ajouter Chaîne", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsYouTubeAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Chaîne", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_youtube_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucune chaîne à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f.get('name', str(idx))[:25] if isinstance(f, dict) else str(f)[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_youtube_feeds', 'youtube')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer une chaîne", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsYouTubeAddModal(Modal, title="➕ Ajouter une chaîne YouTube"):
    name = TextInput(label="Nom de la chaîne", placeholder="Ex: MrBeast", max_length=50)
    channel_id = TextInput(label="ID de la chaîne YouTube", placeholder="UCX6OQ3DkcsbYNE6H8uQQuVA", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_youtube_feeds', [])
        
        # Vérifier si déjà ajouté
        for f in feeds:
            if isinstance(f, dict) and f.get('id') == self.channel_id.value:
                return await i.response.send_message("❌ Cette chaîne est déjà ajoutée!", ephemeral=True)
        
        # Demander le salon
        chs = list(self.g.text_channels)[:24]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="📍 Salon par défaut", value="0", description="Utiliser le salon par défaut configuré"))
        
        new_feed = {'name': self.name.value, 'id': self.channel_id.value}
        v = AdsYouTubeChannelSelectView(self.u, self.g, opts, new_feed)
        await i.response.send_message("📍 Dans quel salon publier les vidéos de cette chaîne ?", view=v, ephemeral=True)

class AdsYouTubeChannelSelectView(View):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.feed_data = feed_data
        self.add_item(AdsYouTubeChannelSelect(u, g, opts, feed_data))

class AdsYouTubeChannelSelect(Select):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.feed_data = feed_data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        
        c = await cfg(self.g.id)
        feeds = c.get('ads_youtube_feeds', [])
        
        # Ajouter le salon si différent de 0
        if channel_id > 0:
            self.feed_data['channel_id'] = channel_id
        
        feeds.append(self.feed_data)
        await db_set(self.g.id, 'ads_youtube_feeds', feeds)
        
        channel = self.g.get_channel(channel_id) if channel_id else None
        salon_txt = channel.mention if channel else "salon par défaut"
        
        await i.response.edit_message(content=f"✅ Chaîne **{self.feed_data['name']}** ajoutée ! Publications dans {salon_txt}", view=None)

# ─────────────────────────────── TWITCH ───────────────────────────────

class AdsTwitchPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🟣 Twitch - Notifications", color=0x9146FF)
        
        tw_ch = self.g.get_channel(c.get('ads_twitch_channel', 0))
        tw_feeds = c.get('ads_twitch_feeds', [])
        
        e.add_field(name="📍 Salon par défaut", value=tw_ch.mention if tw_ch else "❌ Non configuré", inline=False)
        
        if tw_feeds:
            feeds_txt = ""
            for f in tw_feeds[:10]:
                if isinstance(f, dict):
                    name = f.get('username', '?')
                    feed_ch_id = f.get('channel_id', 0)
                    feed_ch = self.g.get_channel(feed_ch_id) if feed_ch_id else None
                    salon_txt = f" → {feed_ch.mention}" if feed_ch else ""
                    feeds_txt += f"• `{name}`{salon_txt}\n"
                else:
                    feeds_txt += f"• `{f}`\n"
            e.add_field(name=f"🎮 Streamers suivis ({len(tw_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="🎮 Streamers suivis", value="*Aucun streamer configuré*", inline=False)
        
        e.set_footer(text="💡 Chaque streamer peut avoir son propre salon de publication")
        return e
    
    @discord.ui.button(label="📍 Salon par défaut", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedAdsChannelSelect(self.u, self.g, 'ads_twitch_channel', 'twitch')
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Salon Twitch par défaut",
                description=f"📊 {len(list(self.g.text_channels))} salons disponibles",
                color=0x9146FF
            ),
            view=v
        )
    
    @discord.ui.button(label="➕ Ajouter Streamer", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsTwitchAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Streamer", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitch_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun streamer à supprimer", ephemeral=True)
        opts = []
        for idx, f in enumerate(feeds[:25]):
            if isinstance(f, dict):
                opts.append(discord.SelectOption(label=f.get('username', str(idx))[:25], value=str(idx)))
            else:
                opts.append(discord.SelectOption(label=str(f)[:25], value=str(idx)))
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_twitch_feeds', 'twitch')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un streamer", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsTwitchAddModal(Modal, title="➕ Ajouter un streamer Twitch"):
    username = TextInput(label="Nom d'utilisateur Twitch", placeholder="Ex: ninja", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitch_feeds', [])
        
        username = self.username.value.lower().strip()
        
        # Vérifier si déjà ajouté
        for f in feeds:
            if isinstance(f, dict) and f.get('username') == username:
                return await i.response.send_message("❌ Ce streamer est déjà ajouté!", ephemeral=True)
            elif isinstance(f, str) and f == username:
                return await i.response.send_message("❌ Ce streamer est déjà ajouté!", ephemeral=True)
        
        # Demander le salon
        chs = list(self.g.text_channels)[:24]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="📍 Salon par défaut", value="0", description="Utiliser le salon par défaut configuré"))
        
        new_feed = {'username': username}
        v = AdsTwitchChannelSelectView(self.u, self.g, opts, new_feed)
        await i.response.send_message("📍 Dans quel salon publier les lives de ce streamer ?", view=v, ephemeral=True)

class AdsTwitchChannelSelectView(View):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.feed_data = feed_data
        self.add_item(AdsTwitchChannelSelect(u, g, opts, feed_data))

class AdsTwitchChannelSelect(Select):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.feed_data = feed_data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitch_feeds', [])
        
        if channel_id > 0:
            self.feed_data['channel_id'] = channel_id
        
        feeds.append(self.feed_data)
        await db_set(self.g.id, 'ads_twitch_feeds', feeds)
        
        channel = self.g.get_channel(channel_id) if channel_id else None
        salon_txt = channel.mention if channel else "salon par défaut"
        
        await i.response.edit_message(content=f"✅ Streamer **{self.feed_data['username']}** ajouté ! Publications dans {salon_txt}", view=None)

# ─────────────────────────────── REDDIT ───────────────────────────────

class AdsRedditPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🟠 Reddit - Notifications", color=0xFF4500)
        
        rd_ch = self.g.get_channel(c.get('ads_reddit_channel', 0))
        rd_feeds = c.get('ads_reddit_feeds', [])
        
        e.add_field(name="📍 Salon par défaut", value=rd_ch.mention if rd_ch else "❌ Non configuré", inline=False)
        
        if rd_feeds:
            feeds_txt = ""
            for f in rd_feeds[:10]:
                if isinstance(f, dict):
                    name = f.get('subreddit', '?')
                    feed_ch_id = f.get('channel_id', 0)
                    feed_ch = self.g.get_channel(feed_ch_id) if feed_ch_id else None
                    salon_txt = f" → {feed_ch.mention}" if feed_ch else ""
                    feeds_txt += f"• r/{name}{salon_txt}\n"
                else:
                    feeds_txt += f"• r/{f}\n"
            e.add_field(name=f"📰 Subreddits suivis ({len(rd_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="📰 Subreddits suivis", value="*Aucun subreddit configuré*", inline=False)
        
        e.set_footer(text="💡 Chaque subreddit peut avoir son propre salon de publication")
        return e
    
    @discord.ui.button(label="📍 Salon par défaut", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedAdsChannelSelect(self.u, self.g, 'ads_reddit_channel', 'reddit')
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Salon Reddit par défaut",
                description=f"📊 {len(list(self.g.text_channels))} salons disponibles",
                color=0xFF4500
            ),
            view=v
        )
    
    @discord.ui.button(label="➕ Ajouter Subreddit", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsRedditAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Subreddit", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_reddit_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun subreddit à supprimer", ephemeral=True)
        opts = []
        for idx, f in enumerate(feeds[:25]):
            if isinstance(f, dict):
                opts.append(discord.SelectOption(label=f"r/{f.get('subreddit', str(idx))}"[:25], value=str(idx)))
            else:
                opts.append(discord.SelectOption(label=f"r/{f}"[:25], value=str(idx)))
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_reddit_feeds', 'reddit')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un subreddit", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsRedditAddModal(Modal, title="➕ Ajouter un subreddit"):
    subreddit = TextInput(label="Nom du subreddit (sans r/)", placeholder="Ex: gaming", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_reddit_feeds', [])
        
        sub = self.subreddit.value.lower().strip().replace('r/', '')
        
        # Vérifier si déjà ajouté
        for f in feeds:
            if isinstance(f, dict) and f.get('subreddit') == sub:
                return await i.response.send_message("❌ Ce subreddit est déjà ajouté!", ephemeral=True)
            elif isinstance(f, str) and f == sub:
                return await i.response.send_message("❌ Ce subreddit est déjà ajouté!", ephemeral=True)
        
        # Demander le salon
        chs = list(self.g.text_channels)[:24]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="📍 Salon par défaut", value="0", description="Utiliser le salon par défaut configuré"))
        
        new_feed = {'subreddit': sub}
        v = AdsRedditChannelSelectView(self.u, self.g, opts, new_feed)
        await i.response.send_message("📍 Dans quel salon publier les posts de ce subreddit ?", view=v, ephemeral=True)

class AdsRedditChannelSelectView(View):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.feed_data = feed_data
        self.add_item(AdsRedditChannelSelect(u, g, opts, feed_data))

class AdsRedditChannelSelect(Select):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.feed_data = feed_data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        
        c = await cfg(self.g.id)
        feeds = c.get('ads_reddit_feeds', [])
        
        if channel_id > 0:
            self.feed_data['channel_id'] = channel_id
        
        feeds.append(self.feed_data)
        await db_set(self.g.id, 'ads_reddit_feeds', feeds)
        
        channel = self.g.get_channel(channel_id) if channel_id else None
        salon_txt = channel.mention if channel else "salon par défaut"
        
        await i.response.edit_message(content=f"✅ Subreddit **r/{self.feed_data['subreddit']}** ajouté ! Publications dans {salon_txt}", view=None)

# ─────────────────────────────── TWITTER/X ───────────────────────────────

# Liste d'instances Nitter fonctionnelles (fallback)
NITTER_INSTANCES = [
    "nitter.poast.org",
    "xcancel.com", 
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
    "nitter.1d4.us",
    "nitter.kavin.rocks",
    "nitter.unixfox.eu",
]

class AdsTwitterPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🐦 Twitter/X - Notifications", color=0x1DA1F2)
        
        x_ch = self.g.get_channel(c.get('ads_twitter_channel', 0))
        x_feeds = c.get('ads_twitter_feeds', [])
        
        e.add_field(name="📍 Salon par défaut", value=x_ch.mention if x_ch else "❌ Non configuré", inline=False)
        
        if x_feeds:
            feeds_txt = ""
            for f in x_feeds[:10]:
                if isinstance(f, dict):
                    name = f.get('username', '?')
                    feed_ch_id = f.get('channel_id', 0)
                    feed_ch = self.g.get_channel(feed_ch_id) if feed_ch_id else None
                    salon_txt = f" → {feed_ch.mention}" if feed_ch else ""
                    feeds_txt += f"• @{name}{salon_txt}\n"
                else:
                    feeds_txt += f"• @{f}\n"
            e.add_field(name=f"👤 Comptes suivis ({len(x_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="👤 Comptes suivis", value="*Aucun compte configuré*", inline=False)
        
        e.set_footer(text="💡 Chaque compte peut avoir son propre salon de publication")
        return e
    
    @discord.ui.button(label="📍 Salon par défaut", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedAdsChannelSelect(self.u, self.g, 'ads_twitter_channel', 'twitter')
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Salon Twitter par défaut",
                description=f"📊 {len(list(self.g.text_channels))} salons disponibles",
                color=0x1DA1F2
            ),
            view=v
        )
    
    @discord.ui.button(label="➕ Ajouter Compte", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsTwitterAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Compte", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitter_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun compte à supprimer", ephemeral=True)
        opts = []
        for idx, f in enumerate(feeds[:25]):
            if isinstance(f, dict):
                opts.append(discord.SelectOption(label=f"@{f.get('username', str(idx))}"[:25], value=str(idx)))
            else:
                opts.append(discord.SelectOption(label=f"@{f}"[:25], value=str(idx)))
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_twitter_feeds', 'twitter')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un compte", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsTwitterAddModal(Modal, title="➕ Ajouter un compte Twitter"):
    username = TextInput(label="Nom d'utilisateur (sans @)", placeholder="Ex: elonmusk", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitter_feeds', [])
        
        username = self.username.value.lower().strip().replace('@', '')
        
        # Vérifier si déjà ajouté
        for f in feeds:
            if isinstance(f, dict) and f.get('username') == username:
                return await i.response.send_message("❌ Ce compte est déjà ajouté!", ephemeral=True)
            elif isinstance(f, str) and f == username:
                return await i.response.send_message("❌ Ce compte est déjà ajouté!", ephemeral=True)
        
        # Demander le salon
        chs = list(self.g.text_channels)[:24]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="📍 Salon par défaut", value="0", description="Utiliser le salon par défaut configuré"))
        
        new_feed = {'username': username}
        v = AdsTwitterChannelSelectView(self.u, self.g, opts, new_feed)
        await i.response.send_message("📍 Dans quel salon publier les tweets de ce compte ?", view=v, ephemeral=True)

class AdsTwitterChannelSelectView(View):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.feed_data = feed_data
        self.add_item(AdsTwitterChannelSelect(u, g, opts, feed_data))

class AdsTwitterChannelSelect(Select):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.feed_data = feed_data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitter_feeds', [])
        
        if channel_id > 0:
            self.feed_data['channel_id'] = channel_id
        
        feeds.append(self.feed_data)
        await db_set(self.g.id, 'ads_twitter_feeds', feeds)
        
        channel = self.g.get_channel(channel_id) if channel_id else None
        salon_txt = channel.mention if channel else "salon par défaut"
        
        await i.response.edit_message(content=f"✅ Compte **@{self.feed_data['username']}** ajouté ! Publications dans {salon_txt}", view=None)

# ─────────────────────────────── DISCORD CHANNELS ───────────────────────────────

class AdsDiscordPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📡 Discord - Suivi de Salons", color=C.BLURPLE)
        
        dc_ch = self.g.get_channel(c.get('ads_discord_channel', 0))
        dc_feeds = c.get('ads_discord_feeds', [])
        
        e.add_field(name="📍 Salon par défaut", value=dc_ch.mention if dc_ch else "❌ Non configuré", inline=False)
        
        if dc_feeds:
            feeds_txt = []
            for f in dc_feeds[:10]:
                ch = bot.get_channel(int(f['channel_id']))
                dest_ch_id = f.get('dest_channel_id', 0)
                dest_ch = self.g.get_channel(dest_ch_id) if dest_ch_id else None
                dest_txt = f" → {dest_ch.mention}" if dest_ch else ""
                if ch:
                    feeds_txt.append(f"• #{ch.name} ({ch.guild.name[:15]}){dest_txt}")
                else:
                    feeds_txt.append(f"• `{f['channel_id']}` (inaccessible){dest_txt}")
            e.add_field(name=f"💬 Salons suivis ({len(dc_feeds)})", value="\n".join(feeds_txt), inline=False)
        else:
            e.add_field(name="💬 Salons suivis", value="*Aucun salon configuré*", inline=False)
        
        e.set_footer(text="💡 Chaque source peut avoir son propre salon de destination")
        return e
    
    @discord.ui.button(label="📍 Salon par défaut", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedAdsChannelSelect(self.u, self.g, 'ads_discord_channel', 'discord')
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Salon de destination par défaut",
                description=f"📊 {len(list(self.g.text_channels))} salons disponibles",
                color=C.BLURPLE
            ),
            view=v
        )
    
    @discord.ui.button(label="➕ Ajouter Salon", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsDiscordAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Salon", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_discord_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun salon à supprimer", ephemeral=True)
        opts = []
        for idx, f in enumerate(feeds[:25]):
            ch = bot.get_channel(int(f['channel_id']))
            label = f"#{ch.name}"[:25] if ch else f"ID: {f['channel_id']}"[:25]
            opts.append(discord.SelectOption(label=label, value=str(idx)))
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_discord_feeds', 'discord')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un salon", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsDiscordAddModal(Modal, title="➕ Suivre un salon Discord"):
    channel_id = TextInput(label="ID du salon à suivre", placeholder="Ex: 1234567890123456789", max_length=25)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_discord_feeds', [])
        
        try:
            ch_id = int(self.channel_id.value.strip())
        except:
            return await i.response.send_message("❌ ID invalide!", ephemeral=True)
        
        # Vérifier si le bot a accès au salon
        ch = bot.get_channel(ch_id)
        if not ch:
            return await i.response.send_message("❌ Salon introuvable! Le bot doit être présent sur le serveur.", ephemeral=True)
        
        # Vérifier si déjà ajouté
        if any(f['channel_id'] == str(ch_id) for f in feeds):
            return await i.response.send_message("❌ Ce salon est déjà suivi!", ephemeral=True)
        
        # Demander le salon de destination
        chs = list(self.g.text_channels)[:24]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="📍 Salon par défaut", value="0", description="Utiliser le salon par défaut configuré"))
        
        new_feed = {'channel_id': str(ch_id), 'guild_name': ch.guild.name, 'channel_name': ch.name}
        v = AdsDiscordDestSelectView(self.u, self.g, opts, new_feed)
        await i.response.send_message(f"📍 Dans quel salon publier les messages de **#{ch.name}** ?", view=v, ephemeral=True)

class AdsDiscordDestSelectView(View):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.feed_data = feed_data
        self.add_item(AdsDiscordDestSelect(u, g, opts, feed_data))

class AdsDiscordDestSelect(Select):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.feed_data = feed_data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        
        c = await cfg(self.g.id)
        feeds = c.get('ads_discord_feeds', [])
        
        if channel_id > 0:
            self.feed_data['dest_channel_id'] = channel_id
        
        feeds.append(self.feed_data)
        await db_set(self.g.id, 'ads_discord_feeds', feeds)
        
        channel = self.g.get_channel(channel_id) if channel_id else None
        salon_txt = channel.mention if channel else "salon par défaut"
        
        await i.response.edit_message(content=f"✅ Salon **#{self.feed_data['channel_name']}** suivi ! Publications dans {salon_txt}", view=None)

# ─────────────────────────────── ROSOCIAL ───────────────────────────────

class AdsRoSocialPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎮 RoSocial - Notifications", color=0x00D4AA)
        
        rs_ch = self.g.get_channel(c.get('ads_rosocial_channel', 0))
        rs_feeds = c.get('ads_rosocial_feeds', [])
        
        e.add_field(name="📍 Salon par défaut", value=rs_ch.mention if rs_ch else "❌ Non configuré", inline=False)
        
        if rs_feeds:
            feeds_txt = ""
            for f in rs_feeds[:10]:
                if isinstance(f, dict):
                    name = f.get('username', '?')
                    feed_ch_id = f.get('channel_id', 0)
                    feed_ch = self.g.get_channel(feed_ch_id) if feed_ch_id else None
                    salon_txt = f" → {feed_ch.mention}" if feed_ch else ""
                    feeds_txt += f"• `{name}`{salon_txt}\n"
                else:
                    feeds_txt += f"• `{f}`\n"
            e.add_field(name=f"👤 Profils suivis ({len(rs_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="👤 Profils suivis", value="*Aucun profil configuré*", inline=False)
        
        e.set_footer(text="💡 Chaque profil peut avoir son propre salon de publication")
        return e
    
    @discord.ui.button(label="📍 Salon par défaut", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedAdsChannelSelect(self.u, self.g, 'ads_rosocial_channel', 'rosocial')
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Salon RoSocial par défaut",
                description=f"📊 {len(list(self.g.text_channels))} salons disponibles",
                color=0x00D4AA
            ),
            view=v
        )
    
    @discord.ui.button(label="➕ Ajouter Profil", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsRoSocialAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Profil", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_rosocial_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun profil à supprimer", ephemeral=True)
        opts = []
        for idx, f in enumerate(feeds[:25]):
            if isinstance(f, dict):
                opts.append(discord.SelectOption(label=f.get('username', str(idx))[:25], value=str(idx)))
            else:
                opts.append(discord.SelectOption(label=str(f)[:25], value=str(idx)))
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_rosocial_feeds', 'rosocial')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un profil", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsRoSocialAddModal(Modal, title="➕ Ajouter un profil RoSocial"):
    username = TextInput(label="Nom d'utilisateur RoSocial", placeholder="Ex: GoRipe", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_rosocial_feeds', [])
        
        username = self.username.value.strip()
        
        # Vérifier si déjà ajouté
        for f in feeds:
            if isinstance(f, dict) and f.get('username', '').lower() == username.lower():
                return await i.response.send_message("❌ Ce profil est déjà ajouté!", ephemeral=True)
            elif isinstance(f, str) and f.lower() == username.lower():
                return await i.response.send_message("❌ Ce profil est déjà ajouté!", ephemeral=True)
        
        # Demander le salon
        chs = list(self.g.text_channels)[:24]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="📍 Salon par défaut", value="0", description="Utiliser le salon par défaut configuré"))
        
        new_feed = {'username': username}
        v = AdsRoSocialChannelSelectView(self.u, self.g, opts, new_feed)
        await i.response.send_message("📍 Dans quel salon publier les posts de ce profil ?", view=v, ephemeral=True)

class AdsRoSocialChannelSelectView(View):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.feed_data = feed_data
        self.add_item(AdsRoSocialChannelSelect(u, g, opts, feed_data))

class AdsRoSocialChannelSelect(Select):
    def __init__(self, u, g, opts, feed_data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.feed_data = feed_data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        
        c = await cfg(self.g.id)
        feeds = c.get('ads_rosocial_feeds', [])
        
        if channel_id > 0:
            self.feed_data['channel_id'] = channel_id
        
        feeds.append(self.feed_data)
        await db_set(self.g.id, 'ads_rosocial_feeds', feeds)
        
        channel = self.g.get_channel(channel_id) if channel_id else None
        salon_txt = channel.mention if channel else "salon par défaut"
        
        await i.response.edit_message(content=f"✅ Profil **{self.feed_data['username']}** ajouté ! Publications dans {salon_txt}", view=None)

# ─────────────────────────────── ROBLOX UGC ───────────────────────────────

class AdsRobloxPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🟢 Roblox UGC - Créations", color=0x00A86B)
        
        rblx_ch = self.g.get_channel(c.get('ads_roblox_channel', 0))
        rblx_feeds = c.get('ads_roblox_feeds', [])
        
        e.description = "Recevez automatiquement les nouvelles créations UGC de vos créateurs Roblox préférés!"
        
        e.add_field(name="📍 Salon de publication", value=rblx_ch.mention if rblx_ch else "❌ Non configuré", inline=False)
        
        if rblx_feeds:
            feeds_txt = ""
            for f in rblx_feeds[:10]:
                if isinstance(f, dict):
                    name = f.get('username', '?')
                    user_id = f.get('user_id', '?')
                    feeds_txt += f"• `{name}` (ID: {user_id})\n"
                else:
                    feeds_txt += f"• `{f}`\n"
            e.add_field(name=f"🎨 Créateurs suivis ({len(rblx_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="🎨 Créateurs suivis", value="*Aucun créateur configuré*", inline=False)
        
        e.set_footer(text="💡 Les nouvelles créations UGC sont vérifiées toutes les 10 minutes")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedAdsChannelSelect(self.u, self.g, 'ads_roblox_channel', 'roblox')
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Salon Roblox UGC",
                description="Où publier les nouvelles créations UGC",
                color=0x00A86B
            ),
            view=v
        )
    
    @discord.ui.button(label="➕ Ajouter Créateur", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsRobloxAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_roblox_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun créateur à supprimer", ephemeral=True)
        opts = []
        for idx, f in enumerate(feeds[:25]):
            if isinstance(f, dict):
                opts.append(discord.SelectOption(label=f.get('username', str(idx))[:25], value=str(idx)))
            else:
                opts.append(discord.SelectOption(label=str(f)[:25], value=str(idx)))
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_roblox_feeds', 'roblox')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un créateur", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsRobloxAddModal(Modal, title="➕ Ajouter un créateur Roblox"):
    username = TextInput(label="Nom d'utilisateur Roblox", placeholder="Ex: Roblox", max_length=50)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        
        username = self.username.value.strip()
        
        # Récupérer l'ID utilisateur Roblox via l'API
        try:
            async with aiohttp.ClientSession() as session:
                # API pour obtenir l'ID utilisateur
                async with session.post(
                    'https://users.roblox.com/v1/usernames/users',
                    json={'usernames': [username], 'excludeBannedUsers': True}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('data') and len(data['data']) > 0:
                            user_data = data['data'][0]
                            user_id = user_data.get('id')
                            display_name = user_data.get('displayName', username)
                            
                            # Vérifier si déjà ajouté
                            c = await cfg(self.g.id)
                            feeds = c.get('ads_roblox_feeds', [])
                            
                            for f in feeds:
                                if isinstance(f, dict) and f.get('user_id') == user_id:
                                    return await i.followup.send("❌ Ce créateur est déjà ajouté!", ephemeral=True)
                            
                            # Ajouter le créateur
                            new_feed = {
                                'username': display_name,
                                'user_id': user_id
                            }
                            feeds.append(new_feed)
                            await db_set(self.g.id, 'ads_roblox_feeds', feeds)
                            
                            await i.followup.send(f"✅ Créateur **{display_name}** (ID: {user_id}) ajouté !", ephemeral=True)
                        else:
                            await i.followup.send(f"❌ Utilisateur Roblox `{username}` introuvable", ephemeral=True)
                    else:
                        await i.followup.send("❌ Erreur lors de la recherche Roblox", ephemeral=True)
        except Exception as ex:
            print(f"Erreur Roblox API: {ex}")
            await i.followup.send("❌ Erreur de connexion à l'API Roblox", ephemeral=True)

# ─────────────────────────────── RÉDUCTIONS JEUX ───────────────────────────────

class AdsDealsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎯 Réductions de Jeux Vidéo", color=0xFF6B35)
        
        deals_ch = self.g.get_channel(c.get('ads_deals_channel', 0))
        deals_enabled = c.get('ads_deals_enabled', False)
        deals_min_discount = c.get('ads_deals_min_discount', 50)
        
        e.description = (
            "Recevez automatiquement les meilleures promotions de jeux vidéo !\n\n"
            "**🏪 +20 Plateformes supportées :**"
        )
        
        # Plateformes majeures
        e.add_field(
            name="🎮 Majeures",
            value="Steam • Epic Games • GOG\nUbisoft • EA/Origin • Battle.net",
            inline=True
        )
        
        # Revendeurs de clés
        e.add_field(
            name="🔑 Revendeurs",
            value="Humble Bundle • Fanatical\nGreen Man Gaming • Gamesplanet",
            inline=True
        )
        
        # Autres
        e.add_field(
            name="🛒 Autres",
            value="GameBillet • IndieGala\nVoidu • DLGamer • +10 autres",
            inline=True
        )
        
        e.add_field(name="📍 Salon", value=deals_ch.mention if deals_ch else "❌ Non configuré", inline=True)
        e.add_field(name="📊 Statut", value="✅ Activé" if deals_enabled else "❌ Désactivé", inline=True)
        e.add_field(name="🔻 Minimum", value=f"**-{deals_min_discount}%**", inline=True)
        
        e.set_footer(text="💡 Données via CheapShark API • Vérification toutes les 30 min")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        v = PaginatedAdsChannelSelect(self.u, self.g, 'ads_deals_channel', 'deals')
        await i.response.edit_message(
            embed=discord.Embed(
                title="📍 Salon des Réductions",
                description="Où publier les promotions de jeux",
                color=0xFF6B35
            ),
            view=v
        )
    
    @discord.ui.button(label="✅ Activer", style=discord.ButtonStyle.success, row=0)
    async def enable(self, i, b):
        c = await cfg(self.g.id)
        if not c.get('ads_deals_channel'):
            return await i.response.send_message("❌ Configurez d'abord un salon!", ephemeral=True)
        await db_set(self.g.id, 'ads_deals_enabled', True)
        v = AdsDealsPanel(self.u, self.g)
        await i.response.edit_message(content="✅ Réductions activées!", embed=await v.embed(), view=v)
    
    @discord.ui.button(label="❌ Désactiver", style=discord.ButtonStyle.danger, row=0)
    async def disable(self, i, b):
        await db_set(self.g.id, 'ads_deals_enabled', False)
        v = AdsDealsPanel(self.u, self.g)
        await i.response.edit_message(content="❌ Réductions désactivées", embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🔻 Réduction min", style=discord.ButtonStyle.secondary, row=1)
    async def set_min_discount(self, i, b):
        await i.response.send_modal(AdsDealsMinDiscountModal(self.g, self.u))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsDealsMinDiscountModal(Modal, title="🔻 Réduction Minimum"):
    discount = TextInput(label="Pourcentage minimum (ex: 50)", placeholder="50", default="50", max_length=3)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            value = int(self.discount.value)
            value = max(10, min(90, value))  # Entre 10% et 90%
            await db_set(self.g.id, 'ads_deals_min_discount', value)
            
            v = AdsDealsPanel(self.u, self.g)
            await i.response.edit_message(content=f"✅ Réduction minimum: **{value}%**", embed=await v.embed(), view=v)
        except:
            await i.response.send_message("❌ Entrez un nombre valide (10-90)", ephemeral=True)

# ─────────────────────────────── COMMON VIEWS ───────────────────────────────

class PaginatedAdsChannelSelect(View):
    """Sélecteur de salon paginé pour les Ads"""
    def __init__(self, u, g, key, platform, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.key = key
        self.platform = platform
        self.page = page
        self.channels = list(g.text_channels)
        self.max_page = max(0, (len(self.channels) - 1) // 24)
        self._build()
    
    def _get_return_panel(self):
        if self.platform == 'youtube':
            return AdsYouTubePanel(self.u, self.g)
        elif self.platform == 'twitch':
            return AdsTwitchPanel(self.u, self.g)
        elif self.platform == 'twitter':
            return AdsTwitterPanel(self.u, self.g)
        elif self.platform == 'discord':
            return AdsDiscordPanel(self.u, self.g)
        elif self.platform == 'rosocial':
            return AdsRoSocialPanel(self.u, self.g)
        elif self.platform == 'roblox':
            return AdsRobloxPanel(self.u, self.g)
        elif self.platform == 'deals':
            return AdsDealsPanel(self.u, self.g)
        else:
            return AdsRedditPanel(self.u, self.g)
    
    def _build(self):
        self.clear_items()
        
        start = self.page * 24
        end = start + 24
        page_channels = self.channels[start:end]
        
        opts = []
        for ch in page_channels:
            desc = ch.category.name[:50] if ch.category else "Sans catégorie"
            opts.append(discord.SelectOption(
                label=f"# {ch.name}"[:25],
                value=str(ch.id),
                description=desc
            ))
        
        if opts:
            select = PaginatedAdsChannelMenu(self, opts)
            self.add_item(select)
        
        # Navigation
        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0), row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            page_btn = discord.ui.Button(label=f"{self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(page_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page), row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        self.page -= 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def next_page(self, i):
        self.page += 1
        self._build()
        await i.response.edit_message(view=self)
    
    async def go_back(self, i):
        v = self._get_return_panel()
        await i.response.edit_message(embed=await v.embed(), view=v)

class PaginatedAdsChannelMenu(Select):
    def __init__(self, parent, opts):
        super().__init__(placeholder=f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un salon...", options=opts)
        self.parent = parent
    
    async def callback(self, i):
        await db_set(i.guild.id, self.parent.key, int(self.values[0]))
        ch = i.guild.get_channel(int(self.values[0]))
        v = self.parent._get_return_panel()
        await i.response.edit_message(
            content=f"✅ Salon défini: **{ch.mention if ch else 'Aucun'}**",
            embed=await v.embed(), view=v
        )

# Anciennes classes gardées pour compatibilité
class AdsChannelSelectView(View):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(timeout=120)
        self.add_item(AdsChannelSelect(u, g, opts, key, platform))

class AdsChannelSelect(Select):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
        self.platform = platform
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        if self.platform == 'youtube':
            v = AdsYouTubePanel(self.u, self.g)
        elif self.platform == 'twitch':
            v = AdsTwitchPanel(self.u, self.g)
        elif self.platform == 'twitter':
            v = AdsTwitterPanel(self.u, self.g)
        elif self.platform == 'discord':
            v = AdsDiscordPanel(self.u, self.g)
        elif self.platform == 'rosocial':
            v = AdsRoSocialPanel(self.u, self.g)
        else:
            v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsFeedRemoveView(View):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(timeout=120)
        self.add_item(AdsFeedRemoveSelect(u, g, opts, key, platform))

class AdsFeedRemoveSelect(Select):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(placeholder="Sélectionner à supprimer...", options=opts)
        self.u = u
        self.g = g
        self.key = key
        self.platform = platform
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        feeds = c.get(self.key, [])
        idx = int(self.values[0])
        if 0 <= idx < len(feeds):
            feeds.pop(idx)
            await db_set(self.g.id, self.key, feeds)
        
        if self.platform == 'youtube':
            v = AdsYouTubePanel(self.u, self.g)
        elif self.platform == 'twitch':
            v = AdsTwitchPanel(self.u, self.g)
        elif self.platform == 'twitter':
            v = AdsTwitterPanel(self.u, self.g)
        elif self.platform == 'discord':
            v = AdsDiscordPanel(self.u, self.g)
        elif self.platform == 'rosocial':
            v = AdsRoSocialPanel(self.u, self.g)
        else:
            v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎯 CENTRE PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class CentrePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    def embed(self):
        e = discord.Embed(title="🎯 Centre de Gestion", color=C.BLURPLE)
        e.description = "Gérez les fonctionnalités avancées de votre serveur."
        
        e.add_field(
            name="🎁 Cadeau (Giveaway)",
            value="Créez et gérez des cadeaux avec conditions personnalisées",
            inline=False
        )
        e.add_field(
            name="📢 Annonces",
            value="Envoyez de belles annonces dans vos salons",
            inline=False
        )
        e.add_field(
            name="📨 Messages Automatiques",
            value="Programmez des messages récurrents",
            inline=False
        )
        
        e.set_footer(text="Sélectionnez une option ci-dessous")
        return e
    
    @discord.ui.button(label="🎁 Cadeau", style=discord.ButtonStyle.success, row=0)
    async def giveaway(self, i, b):
        v = GiveawayPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📢 Annonce", style=discord.ButtonStyle.primary, row=0)
    async def announcement(self, i, b):
        v = AnnouncementPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)
    
    @discord.ui.button(label="📨 Messages", style=discord.ButtonStyle.primary, row=0)
    async def messages(self, i, b):
        v = MessagePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 ANNONCE PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class AnnouncementPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    def embed(self):
        e = discord.Embed(title="📢 Système d'Annonces", color=C.YELLOW)
        e.description = (
            "Créez de belles annonces pour votre serveur.\n"
            "Les annonces sont envoyées une seule fois et ne sont pas stockées."
        )
        
        e.add_field(
            name="✨ Fonctionnalités",
            value=(
                "• Titre personnalisé\n"
                "• Description détaillée\n"
                "• Couleur au choix\n"
                "• Image optionnelle\n"
                "• Mention optionnelle (@everyone, @here, rôle)"
            ),
            inline=False
        )
        
        e.set_footer(text="💡 L'annonce sera envoyée immédiatement après création")
        return e
    
    @discord.ui.button(label="📢 Créer une Annonce", style=discord.ButtonStyle.success, row=0)
    async def create(self, i, b):
        await i.response.send_modal(AnnouncementCreateModal(self.u, self.g))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = CentrePanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class AnnouncementCreateModal(Modal):
    def __init__(self, u, g):
        super().__init__(title="📢 Créer une Annonce")
        self.u = u
        self.g = g
        
        self.title_input = TextInput(
            label="Titre de l'annonce",
            placeholder="Ex: 🎉 Grande Mise à Jour !",
            max_length=100
        )
        self.description_input = TextInput(
            label="Description",
            placeholder="Décrivez votre annonce en détail...",
            style=discord.TextStyle.paragraph,
            max_length=2000
        )
        self.color_input = TextInput(
            label="Couleur (hex)",
            placeholder="#FF5733 ou rouge, bleu, vert, jaune, violet",
            required=False,
            max_length=20,
            default="#5865F2"
        )
        self.image_input = TextInput(
            label="URL de l'image (optionnel)",
            placeholder="https://...",
            required=False,
            max_length=500
        )
        self.mention_input = TextInput(
            label="Mention (optionnel)",
            placeholder="@everyone, @here, ou ID de rôle",
            required=False,
            max_length=50
        )
        
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.color_input)
        self.add_item(self.image_input)
        self.add_item(self.mention_input)
    
    async def on_submit(self, i):
        # Parser la couleur
        color_str = self.color_input.value.strip().lower() if self.color_input.value else "#5865F2"
        color_map = {
            'rouge': 0xFF0000, 'red': 0xFF0000,
            'bleu': 0x0066FF, 'blue': 0x0066FF,
            'vert': 0x00FF00, 'green': 0x00FF00,
            'jaune': 0xFFFF00, 'yellow': 0xFFFF00,
            'violet': 0x9B59B6, 'purple': 0x9B59B6,
            'orange': 0xFF8C00,
            'rose': 0xFF69B4, 'pink': 0xFF69B4,
            'cyan': 0x00FFFF,
            'blanc': 0xFFFFFF, 'white': 0xFFFFFF,
            'noir': 0x000000, 'black': 0x000000,
        }
        
        if color_str in color_map:
            color = color_map[color_str]
        else:
            try:
                color = int(color_str.replace('#', ''), 16)
            except:
                color = C.BLURPLE
        
        # Sauvegarder les données et demander le salon
        announcement_data = {
            'title': self.title_input.value,
            'description': self.description_input.value,
            'color': color,
            'image_url': self.image_input.value or None,
            'mention': self.mention_input.value or None
        }
        
        channels = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in channels]
        v = AnnouncementChannelSelectView(self.u, self.g, opts, announcement_data)
        await i.response.send_message("📍 **Sélectionnez le salon** où envoyer l'annonce:", view=v, ephemeral=True)

class AnnouncementChannelSelectView(View):
    def __init__(self, u, g, opts, data):
        super().__init__(timeout=120)
        self.add_item(AnnouncementChannelSelect(u, g, opts, data))

class AnnouncementChannelSelect(Select):
    def __init__(self, u, g, opts, data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.data = data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        channel = self.g.get_channel(channel_id)
        
        if not channel:
            return await i.response.edit_message(content="❌ Salon introuvable", view=None)
        
        # Créer l'embed d'annonce
        e = discord.Embed(color=self.data['color'])
        
        # Titre stylisé
        e.title = self.data['title']
        
        # Description formatée
        e.description = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{self.data['description']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        # Image
        if self.data['image_url']:
            e.set_image(url=self.data['image_url'])
        
        # Footer
        e.set_footer(text=f"📢 Annonce par {self.u.display_name}", icon_url=self.u.display_avatar.url if self.u.display_avatar else None)
        e.timestamp = now()
        
        # Préparer le contenu de mention
        content = None
        mention = self.data.get('mention', '')
        if mention:
            mention_lower = mention.lower().strip()
            if mention_lower == '@everyone':
                content = "@everyone"
            elif mention_lower == '@here':
                content = "@here"
            elif mention.isdigit():
                content = f"<@&{mention}>"
        
        # Envoyer l'annonce
        try:
            await channel.send(content=content, embed=e)
            await i.response.edit_message(content=f"✅ **Annonce envoyée** dans {channel.mention} !", view=None)
        except Exception as ex:
            await i.response.edit_message(content=f"❌ Erreur: {ex}", view=None)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎁 GIVEAWAY (CADEAU) PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class GiveawayPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        e = discord.Embed(title="🎁 Gestion des Cadeaux", color=C.GREEN)
        e.description = "Créez des cadeaux pour récompenser votre communauté !"
        
        # Compter les giveaways actifs
        active_count = 0
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'SELECT COUNT(*) FROM giveaways WHERE guild_id=? AND ended=0',
                    (self.g.id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    active_count = row[0] if row else 0
        except:
            pass
        
        e.add_field(
            name="📊 Statistiques",
            value=f"```\n🎁 Cadeaux actifs: {active_count}\n```",
            inline=False
        )
        
        e.add_field(
            name="✨ Conditions personnalisables",
            value=(
                "• 📝 Nombre minimum de messages\n"
                "• 🎤 Temps minimum en vocal\n"
                "• 🎭 Rôle obligatoire\n"
                "• 📅 Ancienneté minimum\n"
                "• ❌ Pas AFK (configurable)"
            ),
            inline=False
        )
        
        e.set_footer(text="💡 Créez un cadeau avec ou sans conditions")
        return e
    
    @discord.ui.button(label="➕ Créer un Cadeau", style=discord.ButtonStyle.success, row=0)
    async def create(self, i, b):
        modal = GiveawayCreateModal(self.u, self.g)
        await i.response.send_modal(modal)
    
    @discord.ui.button(label="📋 Voir les Cadeaux", style=discord.ButtonStyle.primary, row=0)
    async def view_list(self, i, b):
        v = GiveawayListPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = CentrePanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class GiveawayCreateModal(Modal):
    def __init__(self, u, g):
        super().__init__(title="🎁 Créer un Cadeau")
        self.u = u
        self.g = g
        
        self.title_input = TextInput(label="Titre du cadeau", placeholder="Ex: Nitro Discord", max_length=100)
        self.description_input = TextInput(label="Description", placeholder="Décrivez le cadeau...", style=discord.TextStyle.paragraph, max_length=500)
        self.prize_input = TextInput(label="Ce qu'il va gagner", placeholder="Ex: 1 mois de Nitro Discord", max_length=200)
        self.duration_input = TextInput(label="Durée (ex: 1h, 2d, 1w)", placeholder="s=secondes, m=minutes, h=heures, d=jours, w=semaines", max_length=10)
        self.image_input = TextInput(label="URL de l'image (optionnel)", placeholder="https://...", required=False, max_length=500)
        
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.prize_input)
        self.add_item(self.duration_input)
        self.add_item(self.image_input)
    
    async def on_submit(self, i):
        # Parser la durée
        duration_str = self.duration_input.value.lower().strip()
        seconds = parse_duration_to_seconds(duration_str)
        
        if seconds <= 0:
            return await i.response.send_message("❌ Durée invalide ! Utilisez: 30s, 5m, 2h, 1d, 1w", ephemeral=True)
        
        # Sauvegarder temporairement
        giveaway_data = {
            'title': self.title_input.value,
            'description': self.description_input.value,
            'prize': self.prize_input.value,
            'duration_seconds': seconds,
            'image_url': self.image_input.value or None,
            'conditions': {}  # Conditions vides par défaut
        }
        
        # Afficher le panneau de conditions
        v = GiveawayConditionsPanel(self.u, self.g, giveaway_data)
        await i.response.send_message(embed=v.embed(), view=v, ephemeral=True)

class GiveawayConditionsPanel(View):
    def __init__(self, u, g, data):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.data = data
    
    def embed(self):
        e = discord.Embed(title="⚙️ Conditions de Participation", color=C.ORANGE)
        e.description = "Configurez les conditions pour participer au cadeau.\n**Laissez vide = tout le monde peut participer**"
        
        conditions = self.data.get('conditions', {})
        
        # Messages minimum
        min_msgs = conditions.get('min_messages', 0)
        e.add_field(name="📝 Messages minimum", value=f"`{min_msgs}`" if min_msgs else "*Aucun*", inline=True)
        
        # Temps vocal minimum (en minutes)
        min_vocal = conditions.get('min_vocal_minutes', 0)
        e.add_field(name="🎤 Vocal minimum", value=f"`{min_vocal} min`" if min_vocal else "*Aucun*", inline=True)
        
        # Rôle requis
        role_id = conditions.get('required_role', 0)
        role = self.g.get_role(role_id) if role_id else None
        e.add_field(name="🎭 Rôle requis", value=role.mention if role else "*Aucun*", inline=True)
        
        # Ancienneté minimum (en jours)
        min_days = conditions.get('min_account_days', 0)
        e.add_field(name="📅 Ancienneté", value=f"`{min_days} jours`" if min_days else "*Aucun*", inline=True)
        
        # AFK check
        no_afk = conditions.get('no_afk', True)
        afk_days = conditions.get('afk_days', 7)
        e.add_field(name="❌ Pas AFK", value=f"`{afk_days} jours`" if no_afk else "*Désactivé*", inline=True)
        
        e.set_footer(text="💡 Cliquez sur Publier quand vous avez fini")
        return e
    
    @discord.ui.button(label="📝 Messages min", style=discord.ButtonStyle.secondary, row=0)
    async def set_messages(self, i, b):
        await i.response.send_modal(GiveawayConditionModal(self, 'min_messages', "Nombre minimum de messages", "Ex: 100"))
    
    @discord.ui.button(label="🎤 Vocal min", style=discord.ButtonStyle.secondary, row=0)
    async def set_vocal(self, i, b):
        await i.response.send_modal(GiveawayConditionModal(self, 'min_vocal_minutes', "Minutes minimum en vocal", "Ex: 60"))
    
    @discord.ui.button(label="🎭 Rôle requis", style=discord.ButtonStyle.secondary, row=0)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles if not r.is_default() and not r.is_bot_managed()][:24]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Aucun rôle requis", value="0"))
        v = GiveawayRoleSelectView(self, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Sélectionner le rôle requis", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="📅 Ancienneté", style=discord.ButtonStyle.secondary, row=1)
    async def set_account_age(self, i, b):
        await i.response.send_modal(GiveawayConditionModal(self, 'min_account_days', "Jours d'ancienneté minimum", "Ex: 30"))
    
    @discord.ui.button(label="❌ AFK", style=discord.ButtonStyle.secondary, row=1)
    async def set_afk(self, i, b):
        await i.response.send_modal(GiveawayConditionModal(self, 'afk_days', "Jours AFK max (0 = désactivé)", "Ex: 7 (ou 0 pour désactiver)"))
    
    @discord.ui.button(label="✅ Publier le Cadeau", style=discord.ButtonStyle.success, row=2)
    async def publish(self, i, b):
        # Demander le salon
        channels = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in channels]
        v = GiveawayChannelSelectView(self.u, self.g, opts, self.data)
        await i.response.edit_message(content="📢 **Sélectionnez le salon** où publier le cadeau:", embed=None, view=v)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Création annulée", embed=None, view=None)

class GiveawayConditionModal(Modal):
    def __init__(self, panel, condition_key, label, placeholder):
        super().__init__(title=f"⚙️ {label}")
        self.panel = panel
        self.condition_key = condition_key
        
        current_val = self.panel.data.get('conditions', {}).get(condition_key, '')
        self.value_input = TextInput(
            label=label,
            placeholder=placeholder,
            required=False,
            default=str(current_val) if current_val else ""
        )
        self.add_item(self.value_input)
    
    async def on_submit(self, i):
        try:
            value = int(self.value_input.value) if self.value_input.value else 0
        except:
            value = 0
        
        if 'conditions' not in self.panel.data:
            self.panel.data['conditions'] = {}
        
        if value > 0:
            self.panel.data['conditions'][self.condition_key] = value
            # Gérer le cas spécial de no_afk
            if self.condition_key == 'afk_days':
                self.panel.data['conditions']['no_afk'] = True
        else:
            self.panel.data['conditions'].pop(self.condition_key, None)
            if self.condition_key == 'afk_days':
                self.panel.data['conditions']['no_afk'] = False
        
        await i.response.edit_message(embed=self.panel.embed(), view=self.panel)

class GiveawayRoleSelectView(View):
    def __init__(self, panel, opts):
        super().__init__(timeout=120)
        self.panel = panel
        self.add_item(GiveawayRoleSelect(panel, opts))

class GiveawayRoleSelect(Select):
    def __init__(self, panel, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.panel = panel
    
    async def callback(self, i):
        role_id = int(self.values[0])
        
        if 'conditions' not in self.panel.data:
            self.panel.data['conditions'] = {}
        
        if role_id > 0:
            self.panel.data['conditions']['required_role'] = role_id
        else:
            self.panel.data['conditions'].pop('required_role', None)
        
        await i.response.edit_message(embed=self.panel.embed(), view=self.panel)

def parse_duration_to_seconds(duration_str):
    """Convertit une durée (1h, 2d, etc.) en secondes"""
    import re
    total = 0
    matches = re.findall(r'(\d+)([smhdw])', duration_str)
    for value, unit in matches:
        value = int(value)
        if unit == 's':
            total += value
        elif unit == 'm':
            total += value * 60
        elif unit == 'h':
            total += value * 3600
        elif unit == 'd':
            total += value * 86400
        elif unit == 'w':
            total += value * 604800
    return total

class GiveawayChannelSelectView(View):
    def __init__(self, u, g, opts, data):
        super().__init__(timeout=120)
        self.add_item(GiveawayChannelSelect(u, g, opts, data))

class GiveawayChannelSelect(Select):
    def __init__(self, u, g, opts, data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.data = data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        channel = self.g.get_channel(channel_id)
        
        if not channel:
            return await i.response.edit_message(content="❌ Salon introuvable", view=None)
        
        # Calculer la fin
        end_time = now() + timedelta(seconds=self.data['duration_seconds'])
        
        # Créer l'embed du giveaway
        e = discord.Embed(title=f"🎁 {self.data['title']}", color=C.GREEN)
        e.description = f"{self.data['description']}\n\n━━━━━━━━━━━━━━━━━━━━━━"
        
        e.add_field(name="🏆 À Gagner", value=f"```{self.data['prize']}```", inline=False)
        e.add_field(name="⏰ Fin", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
        e.add_field(name="👥 Participants", value="```0```", inline=True)
        
        # Construire le texte des conditions
        conditions = self.data.get('conditions', {})
        conditions_txt = ""
        
        if conditions.get('min_messages', 0) > 0:
            conditions_txt += f"• 📝 Minimum **{conditions['min_messages']}** messages\n"
        
        if conditions.get('min_vocal_minutes', 0) > 0:
            conditions_txt += f"• 🎤 Minimum **{conditions['min_vocal_minutes']}** minutes en vocal\n"
        
        if conditions.get('required_role', 0) > 0:
            role = self.g.get_role(conditions['required_role'])
            if role:
                conditions_txt += f"• 🎭 Rôle requis: {role.mention}\n"
        
        if conditions.get('min_account_days', 0) > 0:
            conditions_txt += f"• 📅 Compte d'au moins **{conditions['min_account_days']}** jours\n"
        
        if conditions.get('no_afk', True):
            afk_days = conditions.get('afk_days', 7)
            conditions_txt += f"• ❌ Ne pas être AFK depuis **{afk_days}** jours\n"
        
        if not conditions_txt:
            conditions_txt = "• ✅ Aucune condition - Tout le monde peut participer !"
        
        conditions_txt += "\n*Cliquez sur le bouton pour participer*"
        
        e.add_field(name="📋 Conditions", value=conditions_txt, inline=False)
        
        if self.data['image_url']:
            e.set_image(url=self.data['image_url'])
        
        e.set_footer(text=f"Créé par {self.u.display_name}")
        e.timestamp = now()
        
        # Envoyer le message
        giveaway_view = GiveawayParticipateView()
        msg = await channel.send(embed=e, view=giveaway_view)
        
        # Sauvegarder en BDD avec les conditions
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    INSERT INTO giveaways (guild_id, channel_id, message_id, title, description, prize, image_url, end_time, conditions, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    self.g.id, channel_id, msg.id,
                    self.data['title'], self.data['description'], self.data['prize'],
                    self.data['image_url'], end_time.isoformat(), 
                    json.dumps(conditions),
                    self.u.id
                ))
                await db.commit()
        except Exception as ex:
            print(f"Erreur sauvegarde giveaway: {ex}")
        
        await i.response.edit_message(content=f"✅ **Cadeau créé !** Publié dans {channel.mention}", view=None)

class GiveawayParticipateView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🎉 Participer", style=discord.ButtonStyle.success, custom_id="giveaway_participate")
    async def participate(self, i, b):
        try:
            # Obtenir le membre complet
            member = i.guild.get_member(i.user.id)
            if not member:
                return await i.response.send_message("❌ Erreur: membre introuvable", ephemeral=True)
            
            # ═══════════════ ÉTAPE 1: Récupérer le giveaway ═══════════════
            giveaway_data = None
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute(
                        'SELECT id, participants, ended, conditions FROM giveaways WHERE message_id=?',
                        (i.message.id,)
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            giveaway_data = {
                                'id': row[0],
                                'participants': json.loads(row[1]) if row[1] else [],
                                'ended': row[2],
                                'conditions': json.loads(row[3]) if row[3] else {}
                            }
            except Exception as e:
                print(f"Erreur lecture giveaway: {e}")
                return await i.response.send_message("❌ Erreur de lecture du cadeau", ephemeral=True)
            
            if not giveaway_data:
                return await i.response.send_message("❌ Cadeau introuvable", ephemeral=True)
            
            if giveaway_data['ended']:
                return await i.response.send_message("❌ Ce cadeau est terminé !", ephemeral=True)
            
            if i.user.id in giveaway_data['participants']:
                return await i.response.send_message("✅ Vous participez déjà !", ephemeral=True)
            
            # ═══════════════ ÉTAPE 2: Vérifier les conditions ═══════════════
            conditions = giveaway_data['conditions']
            failed_conditions = []
            
            # 1. Vérifier AFK (seulement si configuré)
            afk_days = conditions.get('afk_days', 0)
            if afk_days > 0:
                try:
                    is_afk = await check_member_afk(i.guild.id, i.user.id, days=afk_days)
                    if is_afk:
                        failed_conditions.append(f"❌ Vous êtes **inactif** depuis plus de {afk_days} jours")
                except Exception as e:
                    print(f"Erreur check AFK: {e}")
            
            # 2. Vérifier les messages minimum
            min_messages = conditions.get('min_messages', 0)
            if min_messages > 0:
                try:
                    user_msgs = 0
                    async with aiosqlite.connect(DB_PATH) as db:
                        async with db.execute(
                            'SELECT total_messages FROM activity_tracking WHERE guild_id=? AND user_id=?',
                            (i.guild.id, i.user.id)
                        ) as cursor:
                            msg_row = await cursor.fetchone()
                            user_msgs = msg_row[0] if msg_row and msg_row[0] else 0
                    
                    if user_msgs < min_messages:
                        failed_conditions.append(f"📝 Vous avez **{user_msgs}** messages (minimum: **{min_messages}**)")
                except Exception as e:
                    print(f"Erreur check messages: {e}")
            
            # 3. Vérifier le temps vocal minimum
            min_vocal = conditions.get('min_vocal_minutes', 0)
            if min_vocal > 0:
                try:
                    user_vocal_minutes = 0
                    async with aiosqlite.connect(DB_PATH) as db:
                        async with db.execute(
                            'SELECT total_vocal_time FROM activity_tracking WHERE guild_id=? AND user_id=?',
                            (i.guild.id, i.user.id)
                        ) as cursor:
                            vocal_row = await cursor.fetchone()
                            user_vocal_seconds = vocal_row[0] if vocal_row and vocal_row[0] else 0
                            user_vocal_minutes = user_vocal_seconds // 60
                    
                    if user_vocal_minutes < min_vocal:
                        failed_conditions.append(f"🎤 Vous avez **{user_vocal_minutes}** min en vocal (minimum: **{min_vocal}**)")
                except Exception as e:
                    print(f"Erreur check vocal: {e}")
            
            # 4. Vérifier le rôle requis
            required_role_id = conditions.get('required_role', 0)
            if required_role_id > 0:
                try:
                    role = i.guild.get_role(required_role_id)
                    if role:
                        member_role_ids = [r.id for r in member.roles]
                        if role.id not in member_role_ids:
                            failed_conditions.append(f"🎭 Vous devez avoir le rôle **{role.name}**")
                except Exception as e:
                    print(f"Erreur check role: {e}")
            
            # 5. Vérifier l'ancienneté du compte
            min_days = conditions.get('min_account_days', 0)
            if min_days > 0:
                try:
                    created = member.created_at
                    if created.tzinfo:
                        created = created.replace(tzinfo=None)
                    account_age = (now() - created).days
                    if account_age < min_days:
                        failed_conditions.append(f"📅 Votre compte a **{account_age}** jours (minimum: **{min_days}**)")
                except Exception as e:
                    print(f"Erreur check account age: {e}")
            
            # Si des conditions ne sont pas remplies
            if failed_conditions:
                error_msg = "❌ **Vous ne pouvez pas participer !**\n\n**Conditions non remplies:**\n"
                error_msg += "\n".join(failed_conditions)
                error_msg += "\n\n*Remplissez ces conditions pour pouvoir participer.*"
                return await i.response.send_message(error_msg, ephemeral=True)
            
            # ═══════════════ ÉTAPE 3: Ajouter le participant ═══════════════
            giveaway_data['participants'].append(i.user.id)
            
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        'UPDATE giveaways SET participants=? WHERE id=?',
                        (json.dumps(giveaway_data['participants']), giveaway_data['id'])
                    )
                    await db.commit()
            except Exception as e:
                print(f"Erreur update participants: {e}")
                return await i.response.send_message("❌ Erreur lors de l'enregistrement", ephemeral=True)
            
            # ═══════════════ ÉTAPE 4: Mettre à jour l'embed ═══════════════
            try:
                embed = i.message.embeds[0].copy()
                for idx, field in enumerate(embed.fields):
                    if "Participants" in field.name:
                        embed.set_field_at(idx, name="👥 Participants", value=f"```{len(giveaway_data['participants'])}```", inline=True)
                        break
                await i.message.edit(embed=embed)
            except Exception as e:
                print(f"Erreur update embed: {e}")
            
            await i.response.send_message(f"🎉 **Vous participez au cadeau !**\nBonne chance !", ephemeral=True)
            
        except Exception as ex:
            import traceback
            print(f"Erreur participation giveaway: {ex}")
            traceback.print_exc()
            try:
                await i.response.send_message("❌ Erreur lors de la participation. Réessayez.", ephemeral=True)
            except:
                pass

async def check_member_afk(guild_id, user_id, days=7):
    """Vérifie si un membre est AFK depuis X jours (les immunisés ne sont jamais AFK)"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # ⚠️ VÉRIFIER L'IMMUNITÉ D'ABORD
            # Vérifier si l'utilisateur est immunisé directement
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=? AND user_id=?', (guild_id, user_id)) as cursor:
                if await cursor.fetchone():
                    return False  # Immunisé = jamais AFK
            
            # Vérifier les rôles immunisés (nécessite de récupérer le membre)
            guild = bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    # Admin = immunisé
                    if member.guild_permissions.administrator or member.id == guild.owner_id:
                        return False
                    
                    # Vérifier les rôles immunisés
                    async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (guild_id,)) as cursor:
                        immune_roles = {r[0] for r in await cursor.fetchall()}
                        if any(r.id in immune_roles for r in member.roles):
                            return False  # A un rôle immunisé = jamais AFK
            
            # Vérifier l'activité normale
            async with db.execute(
                'SELECT last_message, last_vocal FROM activity_tracking WHERE guild_id=? AND user_id=?',
                (guild_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                
                if not row:
                    return True  # Non tracké = considéré AFK
                
                last_msg, last_vocal = row
                last_activity = None
                
                if last_msg:
                    try:
                        last_activity = datetime.fromisoformat(last_msg)
                    except:
                        pass
                
                if last_vocal:
                    try:
                        lv = datetime.fromisoformat(last_vocal)
                        if not last_activity or lv > last_activity:
                            last_activity = lv
                    except:
                        pass
                
                if not last_activity:
                    return True
                
                cutoff = now() - timedelta(days=days)
                la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
                return la_utc < cutoff.replace(tzinfo=timezone.utc)
                
    except:
        return False

# ═══════════════════════════════════════════════════════════════════════════════
#                           📈 SYSTÈME DE NIVEAUX & BOUTIQUE
# ═══════════════════════════════════════════════════════════════════════════════

class LevelSystemPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        
        e = discord.Embed(title="📈 Système de Niveaux & Boutique", color=0x9B59B6)
        e.description = "Configurez le système de progression de votre serveur."
        
        # État
        enabled = level_cfg.get('enabled', False)
        e.add_field(name="État", value="✅ Activé" if enabled else "❌ Désactivé", inline=True)
        
        # XP par message
        xp_per_msg = level_cfg.get('xp_per_message', 15)
        e.add_field(name="✨ XP/message", value=f"`{xp_per_msg}` XP", inline=True)
        
        # XP par vocal avec unité
        xp_per_vocal = level_cfg.get('xp_per_vocal', 5)
        xp_vocal_unit = level_cfg.get('xp_vocal_unit', 'minute')
        unit_labels = {'minute': 'min', 'hour': 'h', 'day': 'jour'}
        e.add_field(name="🎤 XP/vocal", value=f"`{xp_per_vocal}` XP/{unit_labels.get(xp_vocal_unit, 'min')}", inline=True)
        
        # Pièces par messages
        coins_msgs = level_cfg.get('coins_per_messages', 1)
        coins_amount = level_cfg.get('coins_amount', 1)
        e.add_field(name="🪙 Pièces/msg", value=f"`{coins_amount}` / `{coins_msgs}` msg", inline=True)
        
        # Pièces par vocal avec unité
        coins_per_vocal = level_cfg.get('coins_per_vocal', 1)
        coins_vocal_unit = level_cfg.get('coins_vocal_unit', 'minute')
        e.add_field(name="🎤 Pièces/vocal", value=f"`{coins_per_vocal}` /{unit_labels.get(coins_vocal_unit, 'min')}", inline=True)
        
        # Boutique
        shop_items = level_cfg.get('shop_items', [])
        e.add_field(name="🛒 Boutique", value=f"`{len(shop_items)}` article(s)", inline=True)
        
        # Salons autorisés pour XP (texte)
        xp_text_channels = level_cfg.get('xp_text_channels', [])
        if xp_text_channels:
            ch_list = ", ".join([f"<#{c}>" for c in xp_text_channels[:3]])
            e.add_field(name="📝 Salons XP (msg)", value=ch_list + (f"... +{len(xp_text_channels)-3}" if len(xp_text_channels) > 3 else ""), inline=True)
        else:
            e.add_field(name="📝 Salons XP (msg)", value="*Tous*", inline=True)
        
        # Salons autorisés pour XP (vocal)
        xp_voice_channels = level_cfg.get('xp_voice_channels', [])
        if xp_voice_channels:
            ch_list = ", ".join([f"`{self.g.get_channel(c).name if self.g.get_channel(c) else c}`" for c in xp_voice_channels[:3]])
            e.add_field(name="🎤 Salons XP (voc)", value=ch_list + (f"... +{len(xp_voice_channels)-3}" if len(xp_voice_channels) > 3 else ""), inline=True)
        else:
            e.add_field(name="🎤 Salons XP (voc)", value="*Tous*", inline=True)
        
        e.set_footer(text="💡 /level pour voir sa progression • /shop pour acheter")
        return e
    
    @discord.ui.button(label="✅ ON/OFF", style=discord.ButtonStyle.success, row=0)
    async def toggle(self, i, b):
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        level_cfg['enabled'] = not level_cfg.get('enabled', False)
        await db_set(self.g.id, 'level_config', level_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="✨ XP/msg", style=discord.ButtonStyle.primary, row=0)
    async def set_xp(self, i, b):
        await i.response.send_modal(LevelXPModal(self.g, self.u))
    
    @discord.ui.button(label="🪙 Pièces/msg", style=discord.ButtonStyle.primary, row=0)
    async def set_coins(self, i, b):
        await i.response.send_modal(LevelCoinsModal(self.g, self.u))
    
    @discord.ui.button(label="🎤 XP/voc", style=discord.ButtonStyle.primary, row=0)
    async def set_xp_vocal(self, i, b):
        await i.response.send_modal(LevelXPVocalModal(self.g, self.u))
    
    @discord.ui.button(label="🎤 Pièces/voc", style=discord.ButtonStyle.secondary, row=1)
    async def set_coins_vocal(self, i, b):
        await i.response.send_modal(LevelCoinsVocalModal(self.g, self.u))
    
    @discord.ui.button(label="🎭 Rôles", style=discord.ButtonStyle.secondary, row=1)
    async def level_roles(self, i, b):
        v = LevelRolesPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🛒 Boutique", style=discord.ButtonStyle.success, row=1)
    async def shop_config(self, i, b):
        v = ShopConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📝 Salons Msg", style=discord.ButtonStyle.secondary, row=2)
    async def xp_text_channels(self, i, b):
        v = XPChannelsSelectPanel(self.u, self.g, 'text')
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🎤 Salons Voc", style=discord.ButtonStyle.secondary, row=2)
    async def xp_voice_channels(self, i, b):
        v = XPChannelsSelectPanel(self.u, self.g, 'voice')
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📢 Annonces", style=discord.ButtonStyle.secondary, row=2)
    async def levelup_channel(self, i, b):
        v = LevelUpChannelSelect(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(title="📢 Salon des annonces level-up", color=0x9B59B6),
            view=v
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=3)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class XPChannelsSelectPanel(View):
    """Panel pour sélectionner les salons où on gagne de l'XP/pièces"""
    def __init__(self, u, g, channel_type='text', page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.channel_type = channel_type  # 'text' ou 'voice'
        self.page = page
        self.per_page = 23
        
        if channel_type == 'text':
            self.channels = list(g.text_channels)
        else:
            self.channels = list(g.voice_channels)
        
        self.max_page = max(0, (len(self.channels) - 1) // self.per_page)
        self._build()
    
    async def embed(self):
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        key = 'xp_text_channels' if self.channel_type == 'text' else 'xp_voice_channels'
        current = level_cfg.get(key, [])
        
        title = "📝 Salons pour XP/Pièces (Messages)" if self.channel_type == 'text' else "🎤 Salons pour XP/Pièces (Vocal)"
        e = discord.Embed(title=title, color=0x9B59B6)
        
        if current:
            ch_list = []
            for ch_id in current[:15]:
                ch = self.g.get_channel(ch_id)
                if ch:
                    ch_list.append(f"• {'#' if self.channel_type == 'text' else '🔊'} {ch.name}")
            e.description = f"**Salons autorisés ({len(current)}):**\n" + "\n".join(ch_list)
            if len(current) > 15:
                e.description += f"\n*... et {len(current) - 15} autres*"
        else:
            e.description = "**Tous les salons sont autorisés**\n\nSélectionnez des salons pour restreindre."
        
        e.set_footer(text=f"Page {self.page + 1}/{self.max_page + 1}")
        return e
    
    def _build(self):
        self.clear_items()
        
        start = self.page * self.per_page
        end = start + self.per_page
        page_chs = self.channels[start:end]
        
        opts = []
        if self.page == 0:
            opts.append(discord.SelectOption(label="🔓 Tous les salons (reset)", value="all", emoji="🌐"))
        
        for ch in page_chs:
            emoji = "📝" if self.channel_type == 'text' else "🔊"
            opts.append(discord.SelectOption(label=f"{ch.name}"[:25], value=str(ch.id), emoji=emoji))
        
        if opts:
            select = Select(placeholder=f"Ajouter/Retirer des salons...", options=opts, max_values=min(len(opts), 25))
            select.callback = self.select_callback
            self.add_item(select)
        
        # Boutons de navigation
        if self.max_page > 0:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=self.page == 0, row=1)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=self.page >= self.max_page, row=1)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def select_callback(self, i):
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        key = 'xp_text_channels' if self.channel_type == 'text' else 'xp_voice_channels'
        current = set(level_cfg.get(key, []))
        
        for val in i.data['values']:
            if val == 'all':
                current = set()
                break
            else:
                ch_id = int(val)
                if ch_id in current:
                    current.remove(ch_id)
                else:
                    current.add(ch_id)
        
        level_cfg[key] = list(current)
        await db_set(self.g.id, 'level_config', level_cfg)
        
        self._build()
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    async def prev_page(self, i):
        self.page = max(0, self.page - 1)
        self._build()
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    async def next_page(self, i):
        self.page = min(self.max_page, self.page + 1)
        self._build()
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    async def go_back(self, i):
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LevelXPModal(Modal, title="✨ XP par message"):
    xp_input = TextInput(label="XP gagné par message", placeholder="15", max_length=4)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            xp = max(1, min(100, int(self.xp_input.value)))
            c = await cfg(self.g.id)
            level_cfg = c.get('level_config', {})
            level_cfg['xp_per_message'] = xp
            await db_set(self.g.id, 'level_config', level_cfg)
        except:
            pass
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LevelCoinsModal(Modal, title="🪙 Configuration Pièces"):
    msgs_input = TextInput(label="Nombre de messages requis", placeholder="1", max_length=3)
    coins_input = TextInput(label="Pièces gagnées", placeholder="1", max_length=4)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            msgs = max(1, int(self.msgs_input.value))
            coins = max(1, int(self.coins_input.value))
            c = await cfg(self.g.id)
            level_cfg = c.get('level_config', {})
            level_cfg['coins_per_messages'] = msgs
            level_cfg['coins_amount'] = coins
            await db_set(self.g.id, 'level_config', level_cfg)
        except:
            pass
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LevelXPVocalModal(Modal, title="🎤 XP en vocal"):
    xp_input = TextInput(label="XP gagné", placeholder="5", max_length=4)
    unit_input = TextInput(label="Unité (minute, hour, day)", placeholder="minute", max_length=10, default="minute")
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            xp = max(0, min(1000, int(self.xp_input.value)))
            unit = self.unit_input.value.lower().strip()
            if unit not in ['minute', 'hour', 'day']:
                unit = 'minute'
            
            c = await cfg(self.g.id)
            level_cfg = c.get('level_config', {})
            level_cfg['xp_per_vocal'] = xp
            level_cfg['xp_vocal_unit'] = unit
            await db_set(self.g.id, 'level_config', level_cfg)
        except:
            pass
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LevelCoinsVocalModal(Modal, title="🎤 Pièces en vocal"):
    coins_input = TextInput(label="Pièces gagnées", placeholder="1", max_length=4)
    unit_input = TextInput(label="Unité (minute, hour, day)", placeholder="minute", max_length=10, default="minute")
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            coins = max(0, min(1000, int(self.coins_input.value)))
            unit = self.unit_input.value.lower().strip()
            if unit not in ['minute', 'hour', 'day']:
                unit = 'minute'
            
            c = await cfg(self.g.id)
            level_cfg = c.get('level_config', {})
            level_cfg['coins_per_vocal'] = coins
            level_cfg['coins_vocal_unit'] = unit
            await db_set(self.g.id, 'level_config', level_cfg)
        except:
            pass
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LevelUpChannelSelect(View):
    def __init__(self, u, g, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.page = page
        self.channels = list(g.text_channels)
        self.per_page = 23
        self.max_page = max(0, (len(self.channels) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        start = self.page * self.per_page
        end = start + self.per_page
        page_chs = self.channels[start:end]
        
        opts = []
        if self.page == 0:
            opts.append(discord.SelectOption(label="📍 Salon actif", value="0", description="Annonce dans le salon où le membre écrit"))
        
        for ch in page_chs:
            opts.append(discord.SelectOption(label=f"# {ch.name}"[:25], value=str(ch.id)))
        
        if opts:
            select = Select(placeholder=f"Page {self.page+1}/{self.max_page+1} - Choisir...", options=opts)
            select.callback = self.select_callback
            self.add_item(select)
        
        if self.page > 0:
            btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.prev_page
            self.add_item(btn)
        
        if self.page < self.max_page:
            btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.next_page
            self.add_item(btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def select_callback(self, i):
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        level_cfg['levelup_channel'] = int(i.data['values'][0])
        await db_set(self.g.id, 'level_config', level_cfg)
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    async def prev_page(self, i):
        v = LevelUpChannelSelect(self.u, self.g, self.page - 1)
        await i.response.edit_message(view=v)
    
    async def next_page(self, i):
        v = LevelUpChannelSelect(self.u, self.g, self.page + 1)
        await i.response.edit_message(view=v)
    
    async def go_back(self, i):
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── RÔLES NIVEAU ───────────────────────────────

class LevelRolesPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        e = discord.Embed(title="🎭 Rôles par Niveau", color=0x9B59B6)
        e.description = "Rôles donnés automatiquement quand un membre atteint un niveau."
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT level, role_id FROM level_rewards WHERE guild_id=? ORDER BY level', (self.g.id,)) as cursor:
                rewards = await cursor.fetchall()
        
        if rewards:
            txt = ""
            for lvl, role_id in rewards[:15]:
                role = self.g.get_role(role_id)
                if role:
                    txt += f"**Niveau {lvl}** → {role.mention}\n"
            e.add_field(name="📋 Récompenses", value=txt or "*Aucune*", inline=False)
        else:
            e.add_field(name="📋 Récompenses", value="*Aucune configurée*", inline=False)
        
        return e
    
    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddLevelRoleModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT level, role_id FROM level_rewards WHERE guild_id=?', (self.g.id,)) as cursor:
                rewards = await cursor.fetchall()
        
        if not rewards:
            return await i.response.send_message("❌ Aucune récompense", ephemeral=True)
        
        opts = []
        for lvl, role_id in rewards[:25]:
            role = self.g.get_role(role_id)
            opts.append(discord.SelectOption(label=f"Niveau {lvl} - {role.name if role else '?'}"[:25], value=str(lvl)))
        
        v = RemoveLevelRoleView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer une récompense", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddLevelRoleModal(Modal, title="➕ Ajouter une récompense"):
    level_input = TextInput(label="Niveau requis", placeholder="Ex: 10", max_length=3)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            level = int(self.level_input.value)
            v = SelectRoleForLevelView(self.u, self.g, level)
            await i.response.send_message(f"🎭 Sélectionnez le rôle pour le niveau **{level}**:", view=v, ephemeral=True)
        except:
            await i.response.send_message("❌ Niveau invalide", ephemeral=True)

class SelectRoleForLevelView(View):
    def __init__(self, u, g, level, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.level = level
        self.page = page
        self.roles = [r for r in g.roles[1:] if not r.is_bot_managed()]
        self.per_page = 24
        self.max_page = max(0, (len(self.roles) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        start = self.page * self.per_page
        end = start + self.per_page
        page_roles = self.roles[start:end]
        
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in page_roles]
        
        if opts:
            select = Select(placeholder=f"Page {self.page+1}/{self.max_page+1} - Choisir un rôle...", options=opts)
            select.callback = self.select_callback
            self.add_item(select)
        
        if self.page > 0:
            btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.prev_page
            self.add_item(btn)
        
        if self.page < self.max_page:
            btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.next_page
            self.add_item(btn)
    
    async def select_callback(self, i):
        role_id = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO level_rewards VALUES(?,?,?)', (self.g.id, self.level, role_id))
            await db.commit()
        role = self.g.get_role(role_id)
        await i.response.edit_message(content=f"✅ Niveau **{self.level}** → {role.mention if role else 'Rôle'}", view=None)
    
    async def prev_page(self, i):
        v = SelectRoleForLevelView(self.u, self.g, self.level, self.page - 1)
        await i.response.edit_message(view=v)
    
    async def next_page(self, i):
        v = SelectRoleForLevelView(self.u, self.g, self.level, self.page + 1)
        await i.response.edit_message(view=v)

class RemoveLevelRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        select = Select(placeholder="Choisir une récompense...", options=opts)
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, i):
        level = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM level_rewards WHERE guild_id=? AND level=?', (self.g.id, level))
            await db.commit()
        v = LevelRolesPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── BOUTIQUE CONFIG ───────────────────────────────

class ShopConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        shop_items = level_cfg.get('shop_items', [])
        
        e = discord.Embed(title="🛒 Configuration Boutique", color=0xE67E22)
        e.description = "Configurez les articles achetables avec `/shop`."
        
        if shop_items:
            txt = ""
            for idx, item in enumerate(shop_items[:10]):
                role = self.g.get_role(item.get('role_id', 0))
                price = item.get('price', 0)
                duration = item.get('duration', 3600)
                dur_txt = format_duration(duration)
                txt += f"`{idx+1}.` {role.mention if role else '?'} - **{price}** 🪙 ({dur_txt})\n"
            e.add_field(name="📦 Articles", value=txt, inline=False)
        else:
            e.add_field(name="📦 Articles", value="*Aucun article*\nAjoutez des rôles à vendre !", inline=False)
        
        e.set_footer(text="💡 Les rôles sont temporaires et retirés automatiquement")
        return e
    
    @discord.ui.button(label="➕ Ajouter Article", style=discord.ButtonStyle.success, row=0)
    async def add_item(self, i, b):
        await i.response.send_modal(AddShopItemModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Article", style=discord.ButtonStyle.danger, row=0)
    async def remove_item(self, i, b):
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        shop_items = level_cfg.get('shop_items', [])
        
        if not shop_items:
            return await i.response.send_message("❌ Aucun article", ephemeral=True)
        
        opts = []
        for idx, item in enumerate(shop_items[:25]):
            role = self.g.get_role(item.get('role_id', 0))
            opts.append(discord.SelectOption(label=f"{role.name if role else '?'} - {item.get('price', 0)} 🪙"[:25], value=str(idx)))
        
        v = RemoveShopItemView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un article", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = LevelSystemPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddShopItemModal(Modal, title="➕ Ajouter un article"):
    price_input = TextInput(label="Prix (en pièces)", placeholder="100", max_length=6)
    duration_input = TextInput(label="Durée (en minutes)", placeholder="60", max_length=6)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            price = max(1, int(self.price_input.value))
            duration_min = max(1, int(self.duration_input.value))
            duration_sec = duration_min * 60
            
            v = SelectRoleForShopView(self.u, self.g, price, duration_sec)
            await i.response.send_message(f"🎭 Sélectionnez le rôle à vendre pour **{price}** 🪙 (durée: {duration_min} min):", view=v, ephemeral=True)
        except:
            await i.response.send_message("❌ Valeurs invalides", ephemeral=True)

class SelectRoleForShopView(View):
    def __init__(self, u, g, price, duration, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.price = price
        self.duration = duration
        self.page = page
        self.roles = [r for r in g.roles[1:] if not r.is_bot_managed()]
        self.per_page = 24
        self.max_page = max(0, (len(self.roles) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        start = self.page * self.per_page
        end = start + self.per_page
        page_roles = self.roles[start:end]
        
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in page_roles]
        
        if opts:
            select = Select(placeholder=f"Page {self.page+1}/{self.max_page+1} - Choisir un rôle...", options=opts)
            select.callback = self.select_callback
            self.add_item(select)
        
        if self.page > 0:
            btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.prev_page
            self.add_item(btn)
        
        if self.page < self.max_page:
            btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.next_page
            self.add_item(btn)
    
    async def select_callback(self, i):
        role_id = int(i.data['values'][0])
        
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        shop_items = level_cfg.get('shop_items', [])
        
        shop_items.append({
            'role_id': role_id,
            'price': self.price,
            'duration': self.duration
        })
        
        level_cfg['shop_items'] = shop_items
        await db_set(self.g.id, 'level_config', level_cfg)
        
        role = self.g.get_role(role_id)
        await i.response.edit_message(content=f"✅ Article ajouté: {role.mention if role else 'Rôle'} pour **{self.price}** 🪙", view=None)
    
    async def prev_page(self, i):
        v = SelectRoleForShopView(self.u, self.g, self.price, self.duration, self.page - 1)
        await i.response.edit_message(view=v)
    
    async def next_page(self, i):
        v = SelectRoleForShopView(self.u, self.g, self.price, self.duration, self.page + 1)
        await i.response.edit_message(view=v)

class RemoveShopItemView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        select = Select(placeholder="Choisir un article...", options=opts)
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, i):
        idx = int(i.data['values'][0])
        
        c = await cfg(self.g.id)
        level_cfg = c.get('level_config', {})
        shop_items = level_cfg.get('shop_items', [])
        
        if 0 <= idx < len(shop_items):
            del shop_items[idx]
            level_cfg['shop_items'] = shop_items
            await db_set(self.g.id, 'level_config', level_cfg)
        
        v = ShopConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

def format_duration(seconds):
    """Formate une durée en texte lisible"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}min"
    elif seconds < 86400:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h{mins}min" if mins else f"{hours}h"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}j{hours}h" if hours else f"{days}j"

# Sélecteur de salons générique avec callback personnalisé
class PaginatedChannelSelectGeneric(View):
    def __init__(self, u, g, config_key, current_channels, return_panel_class, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.config_key = config_key
        self.current_channels = list(current_channels) if current_channels else []
        self.return_panel_class = return_panel_class
        self.page = page
        self.channels = list(g.text_channels)
        self.per_page = 23
        self.max_page = max(0, (len(self.channels) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        start = self.page * self.per_page
        end = start + self.per_page
        page_chs = self.channels[start:end]
        
        opts = []
        if self.page == 0:
            opts.append(discord.SelectOption(label="✅ Sauvegarder", value="save", emoji="💾"))
        
        for ch in page_chs:
            is_selected = ch.id in self.current_channels
            opts.append(discord.SelectOption(
                label=f"# {ch.name}"[:25], 
                value=str(ch.id),
                default=is_selected,
                emoji="✅" if is_selected else "⬜"
            ))
        
        if opts:
            select = Select(placeholder=f"Page {self.page+1}/{self.max_page+1}", options=opts, max_values=min(len(opts), 25))
            select.callback = self.select_callback
            self.add_item(select)
        
        if self.page > 0:
            btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.prev_page
            self.add_item(btn)
        
        if self.page < self.max_page:
            btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.next_page
            self.add_item(btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def select_callback(self, i):
        values = i.data['values']
        
        if 'save' in values:
            # Sauvegarder
            c = await cfg(self.g.id)
            level_cfg = c.get('level_config', {})
            level_cfg['allowed_channels'] = self.current_channels
            await db_set(self.g.id, 'level_config', level_cfg)
            v = self.return_panel_class(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
            return
        
        for val in values:
            if val == 'save':
                continue
            ch_id = int(val)
            if ch_id in self.current_channels:
                self.current_channels.remove(ch_id)
            else:
                self.current_channels.append(ch_id)
        
        v = PaginatedChannelSelectGeneric(self.u, self.g, self.config_key, self.current_channels, self.return_panel_class, self.page)
        await i.response.edit_message(view=v)
    
    async def prev_page(self, i):
        v = PaginatedChannelSelectGeneric(self.u, self.g, self.config_key, self.current_channels, self.return_panel_class, self.page - 1)
        await i.response.edit_message(view=v)
    
    async def next_page(self, i):
        v = PaginatedChannelSelectGeneric(self.u, self.g, self.config_key, self.current_channels, self.return_panel_class, self.page + 1)
        await i.response.edit_message(view=v)
    
    async def go_back(self, i):
        v = self.return_panel_class(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔊 VOCAUX TEMPORAIRES
# ═══════════════════════════════════════════════════════════════════════════════

# Cache des vocaux temporaires : {channel_id: {'owner': user_id, 'created_at': datetime}}
temp_voice_channels = {}

class TempVoicePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        hubs = voice_cfg.get('hubs', {})  # Nouveau format multi-hubs
        
        e = discord.Embed(title="🔊 Vocaux Temporaires", color=0x9B59B6)
        e.description = (
            "Créez des salons hubs qui génèrent des vocaux personnalisés.\n\n"
            "**Configuration automatique :**\n"
            "✅ Détection vocale (pas de push-to-talk)\n"
            "✅ Stream autorisé\n"
            "❌ Écriture bloquée\n"
            "🗑️ Suppression auto si vide\n\n"
            "**Restriction par rôle :**\n"
            "🔒 Si un hub a un rôle défini, le vocal créé sera **invisible** pour les membres sans ce rôle"
        )
        
        # État
        enabled = voice_cfg.get('enabled', False)
        e.add_field(name="État", value="✅ Activé" if enabled else "❌ Désactivé", inline=True)
        
        # Nombre de hubs configurés
        active_hubs = len([h for h_id, h in hubs.items() if self.g.get_channel(int(h_id))])
        e.add_field(name="🎤 Hubs configurés", value=str(active_hubs), inline=True)
        
        # Vocaux actifs
        active_count = len([ch for ch in temp_voice_channels.keys() if self.g.get_channel(ch)])
        e.add_field(name="📊 Vocaux actifs", value=str(active_count), inline=True)
        
        # Liste des hubs
        if hubs:
            hub_list = []
            for hub_id, hub_data in list(hubs.items())[:5]:  # Max 5 affichés
                hub_ch = self.g.get_channel(int(hub_id))
                if hub_ch:
                    role_id = hub_data.get('required_role', 0)
                    role = self.g.get_role(role_id) if role_id else None
                    if role:
                        role_txt = f"🔒 {role.name} (privé)"
                    else:
                        role_txt = "🔓 Public"
                    cat = self.g.get_channel(hub_data.get('category', 0))
                    cat_txt = cat.name if cat else "Non défini"
                    hub_list.append(f"🎤 **{hub_ch.name}**\n┗ {role_txt} • 📁 {cat_txt}")
            
            if len(hubs) > 5:
                hub_list.append(f"*... et {len(hubs) - 5} autres*")
            
            e.add_field(name="📋 Hubs configurés", value="\n".join(hub_list) if hub_list else "*Aucun*", inline=False)
        else:
            e.add_field(name="📋 Hubs configurés", value="*Aucun hub configuré*\nCliquez sur '➕ Ajouter Hub' pour commencer", inline=False)
        
        # Permissions du propriétaire
        perms = voice_cfg.get('owner_permissions', {})
        perm_list = []
        if perms.get('can_rename', True):
            perm_list.append("✏️ Renommer")
        if perms.get('can_limit', True):
            perm_list.append("🔢 Limite")
        if perms.get('can_mute', True):
            perm_list.append("🔇 Mute")
        if perms.get('can_kick', True):
            perm_list.append("👢 Expulser")
        
        e.add_field(name="👑 Permissions Propriétaire", value=" • ".join(perm_list) if perm_list else "*Aucune*", inline=False)
        
        e.set_footer(text="💡 Chaque hub peut avoir un rôle requis différent")
        return e
    
    @discord.ui.button(label="✅ Activer/Désactiver", style=discord.ButtonStyle.success, row=0)
    async def toggle(self, i, b):
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        voice_cfg['enabled'] = not voice_cfg.get('enabled', False)
        await db_set(self.g.id, 'temp_voice_config', voice_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="➕ Ajouter Hub", style=discord.ButtonStyle.primary, row=0)
    async def add_hub(self, i, b):
        v = TempVoiceAddHubSelect(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(
                title="➕ Ajouter un Hub Vocal",
                description="**Étape 1/3** - Choisissez le salon vocal qui servira de hub.\n\nQuand un membre rejoindra ce salon, un vocal personnel sera créé.",
                color=0x9B59B6
            ),
            view=v
        )
    
    @discord.ui.button(label="📋 Gérer Hubs", style=discord.ButtonStyle.primary, row=0)
    async def manage_hubs(self, i, b):
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        hubs = voice_cfg.get('hubs', {})
        
        if not hubs:
            return await i.response.send_message("❌ Aucun hub configuré. Ajoutez d'abord un hub.", ephemeral=True)
        
        v = TempVoiceHubsListPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="👑 Permissions", style=discord.ButtonStyle.secondary, row=1)
    async def set_permissions(self, i, b):
        v = TempVoicePermissionsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class TempVoiceAddHubSelect(View):
    """Étape 1: Sélection du salon hub"""
    def __init__(self, u, g):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        
        # Récupérer les hubs déjà configurés
        voice_channels = [c for c in g.channels if isinstance(c, discord.VoiceChannel)][:25]
        
        opts = [discord.SelectOption(label=f"🔊 {c.name}"[:25], value=str(c.id)) for c in voice_channels]
        if opts:
            select = Select(placeholder="Choisir un salon vocal...", options=opts)
            select.callback = self.select_callback
            self.add_item(select)
    
    async def select_callback(self, i):
        hub_id = int(i.data['values'][0])
        hub_ch = self.g.get_channel(hub_id)
        
        # Passer à l'étape 2: choisir la catégorie
        v = TempVoiceAddHubCategory(self.u, self.g, hub_id)
        await i.response.edit_message(
            embed=discord.Embed(
                title="➕ Ajouter un Hub Vocal",
                description=f"**Étape 2/3** - Choisissez la catégorie où les vocaux seront créés.\n\n🎤 Hub sélectionné: **{hub_ch.name}**",
                color=0x9B59B6
            ),
            view=v
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TempVoicePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TempVoiceAddHubCategory(View):
    """Étape 2: Sélection de la catégorie"""
    def __init__(self, u, g, hub_id):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.hub_id = hub_id
        
        categories = list(g.categories)[:25]
        opts = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in categories]
        if opts:
            select = Select(placeholder="Choisir une catégorie...", options=opts)
            select.callback = self.select_callback
            self.add_item(select)
    
    async def select_callback(self, i):
        cat_id = int(i.data['values'][0])
        cat = self.g.get_channel(cat_id)
        hub_ch = self.g.get_channel(self.hub_id)
        
        # Passer à l'étape 3: choisir le rôle requis (optionnel)
        v = TempVoiceAddHubRole(self.u, self.g, self.hub_id, cat_id)
        await i.response.edit_message(
            embed=discord.Embed(
                title="➕ Ajouter un Hub Vocal",
                description=(
                    f"**Étape 3/3** - Choisissez un rôle requis (optionnel).\n\n"
                    f"🎤 Hub: **{hub_ch.name}**\n"
                    f"📁 Catégorie: **{cat.name}**\n\n"
                    f"**🔒 Effet du rôle requis :**\n"
                    f"• Seuls les membres avec ce rôle peuvent créer un vocal\n"
                    f"• Le vocal créé sera **invisible** pour les autres membres\n"
                    f"• Seuls les membres avec le rôle peuvent voir/rejoindre le vocal"
                ),
                color=0x9B59B6
            ),
            view=v
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TempVoiceAddHubSelect(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(
                title="➕ Ajouter un Hub Vocal",
                description="**Étape 1/3** - Choisissez le salon vocal qui servira de hub.",
                color=0x9B59B6
            ),
            view=v
        )

class TempVoiceAddHubRole(View):
    """Étape 3: Sélection du rôle requis avec pagination complète"""
    def __init__(self, u, g, hub_id, cat_id, page=0):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.hub_id = hub_id
        self.cat_id = cat_id
        self.page = page
        
        # Filtrer les rôles (exclure @everyone et les rôles de bot) - triés par position
        self.all_roles = [r for r in sorted(g.roles, key=lambda x: x.position, reverse=True) if not r.is_default() and not r.managed]
        self.per_page = 24  # Max 25 options par select, on garde 24 pour la marge
        self.max_page = max(0, len(self.all_roles) // self.per_page)
        
        self._build()
    
    def _build(self):
        self.clear_items()
        
        # Calculer les rôles pour cette page
        start = self.page * self.per_page
        end = min(start + self.per_page, len(self.all_roles))
        page_roles = self.all_roles[start:end]
        
        # Construire les options
        opts = []
        
        # Option "Public" seulement sur la première page
        if self.page == 0:
            opts.append(discord.SelectOption(
                label="🔓 Public (tous peuvent rejoindre)",
                value="0",
                description="Aucune restriction de rôle",
                emoji="✅"
            ))
        
        # Ajouter les rôles de cette page
        for r in page_roles:
            if len(opts) >= 25:
                break
            opts.append(discord.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                description=f"Réservé aux membres avec ce rôle",
                emoji="🔒"
            ))
        
        # Créer le select si on a des options
        if opts:
            select = Select(
                placeholder=f"Sélectionner un rôle ({len(self.all_roles)} disponibles)...",
                options=opts,
                row=0
            )
            select.callback = self._on_select
            self.add_item(select)
        
        # Boutons de navigation si plusieurs pages
        if self.max_page > 0:
            # Bouton précédent
            prev_btn = Button(label="◀️ Précédent", style=discord.ButtonStyle.primary, row=1, disabled=(self.page == 0))
            prev_btn.callback = self._prev
            self.add_item(prev_btn)
            
            # Indicateur de page
            info_btn = Button(label=f"Page {self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, row=1, disabled=True)
            self.add_item(info_btn)
            
            # Bouton suivant
            next_btn = Button(label="Suivant ▶️", style=discord.ButtonStyle.primary, row=1, disabled=(self.page >= self.max_page))
            next_btn.callback = self._next
            self.add_item(next_btn)
        
        # Bouton retour
        back_btn = Button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
        back_btn.callback = self._back
        self.add_item(back_btn)
    
    async def _prev(self, i: discord.Interaction):
        # Répondre IMMÉDIATEMENT pour éviter le timeout
        try:
            await i.response.defer()
        except:
            pass
        
        if self.page > 0:
            self.page -= 1
            self._build()
        
        try:
            await i.edit_original_response(view=self)
        except:
            pass
    
    async def _next(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        if self.page < self.max_page:
            self.page += 1
            self._build()
        
        try:
            await i.edit_original_response(view=self)
        except:
            pass
    
    async def _back(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        try:
            v = TempVoiceAddHubCategory(self.u, self.g, self.hub_id)
            hub_ch = self.g.get_channel(self.hub_id)
            await i.edit_original_response(
                embed=discord.Embed(
                    title="➕ Ajouter un Hub Vocal",
                    description=f"**Étape 2/3** - Choisissez la catégorie.\n\n🎤 Hub: **{hub_ch.name if hub_ch else 'Inconnu'}**",
                    color=0x9B59B6
                ),
                view=v
            )
        except Exception as ex:
            print(f"[TempVoiceAddHubRole._back] {ex}")
    
    async def _on_select(self, i: discord.Interaction):
        # Répondre immédiatement
        try:
            await i.response.defer()
        except:
            pass
        
        try:
            role_id = int(i.data['values'][0])
            
            # Sauvegarder le hub
            c = await cfg(self.g.id)
            voice_cfg = c.get('temp_voice_config', {})
            hubs = voice_cfg.get('hubs', {})
            
            hubs[str(self.hub_id)] = {
                'category': self.cat_id,
                'required_role': role_id,
                'default_name': '🔊 Vocal de {user}'
            }
            
            voice_cfg['hubs'] = hubs
            await db_set(self.g.id, 'temp_voice_config', voice_cfg)
            
            # Confirmation
            hub_ch = self.g.get_channel(self.hub_id)
            cat = self.g.get_channel(self.cat_id)
            role = self.g.get_role(role_id) if role_id else None
            
            if role:
                visibility_txt = f"🔒 **PRIVÉ** - Réservé à @{role.name}\n*Les vocaux créés seront invisibles pour les autres*"
            else:
                visibility_txt = "🔓 **PUBLIC** - Tout le monde peut voir et rejoindre"
            
            v = TempVoicePanel(self.u, self.g)
            await i.edit_original_response(
                content=f"✅ **Hub ajouté avec succès !**\n\n🎤 Hub: **{hub_ch.name if hub_ch else 'Inconnu'}**\n📁 Catégorie: **{cat.name if cat else 'Inconnue'}**\n{visibility_txt}",
                embed=await v.embed(),
                view=v
            )
        except Exception as ex:
            print(f"[TempVoiceAddHubRole._on_select] {ex}")
            try:
                await i.edit_original_response(content="❌ Une erreur est survenue. Réessayez.")
            except:
                pass

class TempVoiceHubsListPanel(View):
    """Panel pour lister et gérer les hubs existants"""
    def __init__(self, u, g, page=0):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.page = page
        self.per_page = 5
    
    async def get_hubs(self):
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        return voice_cfg.get('hubs', {})
    
    async def embed(self):
        hubs = await self.get_hubs()
        
        e = discord.Embed(title="📋 Liste des Hubs Vocaux", color=0x9B59B6)
        
        if not hubs:
            e.description = "*Aucun hub configuré*"
            return e
        
        # Pagination
        hub_items = list(hubs.items())
        start = self.page * self.per_page
        end = start + self.per_page
        page_hubs = hub_items[start:end]
        
        description_parts = []
        for idx, (hub_id, hub_data) in enumerate(page_hubs, start=start+1):
            hub_ch = self.g.get_channel(int(hub_id))
            if not hub_ch:
                description_parts.append(f"**{idx}.** ❌ *Salon supprimé* (ID: {hub_id})")
                continue
            
            cat = self.g.get_channel(hub_data.get('category', 0))
            role_id = hub_data.get('required_role', 0)
            role = self.g.get_role(role_id) if role_id else None
            default_name = hub_data.get('default_name', '🔊 Vocal de {user}')
            
            description_parts.append(
                f"**{idx}. 🎤 {hub_ch.name}**\n"
                f"┣ 📁 Catégorie: {cat.name if cat else '❌ Non définie'}\n"
                f"┣ 🔒 Rôle: {role.mention if role else '🔓 Aucun (tous)'}\n"
                f"┗ 📝 Nom: `{default_name}`"
            )
        
        e.description = "\n\n".join(description_parts)
        
        total_pages = max(1, (len(hubs) - 1) // self.per_page + 1)
        e.set_footer(text=f"Page {self.page + 1}/{total_pages} • {len(hubs)} hub(s) configuré(s)")
        
        return e
    
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=0)
    async def prev_page(self, i, b):
        if self.page > 0:
            self.page -= 1
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, i, b):
        hubs = await self.get_hubs()
        max_page = max(0, (len(hubs) - 1) // self.per_page)
        if self.page < max_page:
            self.page += 1
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="✏️ Modifier Hub", style=discord.ButtonStyle.primary, row=1)
    async def edit_hub(self, i, b):
        hubs = await self.get_hubs()
        if not hubs:
            return await i.response.send_message("❌ Aucun hub à modifier", ephemeral=True)
        
        v = TempVoiceHubEditSelect(self.u, self.g, hubs)
        await i.response.edit_message(
            embed=discord.Embed(
                title="✏️ Modifier un Hub",
                description="Sélectionnez le hub à modifier.",
                color=0x9B59B6
            ),
            view=v
        )
    
    @discord.ui.button(label="🗑️ Supprimer Hub", style=discord.ButtonStyle.danger, row=1)
    async def delete_hub(self, i, b):
        hubs = await self.get_hubs()
        if not hubs:
            return await i.response.send_message("❌ Aucun hub à supprimer", ephemeral=True)
        
        v = TempVoiceHubDeleteSelect(self.u, self.g, hubs)
        await i.response.edit_message(
            embed=discord.Embed(
                title="🗑️ Supprimer un Hub",
                description="Sélectionnez le hub à supprimer.",
                color=0xE74C3C
            ),
            view=v
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = TempVoicePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TempVoiceHubEditSelect(View):
    """Sélection d'un hub à modifier"""
    def __init__(self, u, g, hubs):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        
        opts = []
        for hub_id, hub_data in list(hubs.items())[:25]:
            hub_ch = g.get_channel(int(hub_id))
            if hub_ch:
                role_id = hub_data.get('required_role', 0)
                role = g.get_role(role_id) if role_id else None
                label = f"🎤 {hub_ch.name}"[:25]
                desc = f"Rôle: {role.name if role else 'Aucun'}"[:50]
                opts.append(discord.SelectOption(label=label, value=hub_id, description=desc))
        
        if opts:
            select = Select(placeholder="Choisir un hub...", options=opts)
            select.callback = self.select_callback
            self.add_item(select)
    
    async def select_callback(self, i):
        hub_id = i.data['values'][0]
        v = TempVoiceHubEditPanel(self.u, self.g, hub_id)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TempVoiceHubsListPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TempVoiceHubEditPanel(View):
    """Panel pour modifier un hub spécifique"""
    def __init__(self, u, g, hub_id):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.hub_id = hub_id
    
    async def get_hub_data(self):
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        hubs = voice_cfg.get('hubs', {})
        return hubs.get(str(self.hub_id), {})
    
    async def embed(self):
        hub_data = await self.get_hub_data()
        hub_ch = self.g.get_channel(int(self.hub_id))
        
        e = discord.Embed(title=f"✏️ Modifier: {hub_ch.name if hub_ch else 'Hub'}", color=0x9B59B6)
        
        # Catégorie
        cat = self.g.get_channel(hub_data.get('category', 0))
        e.add_field(name="📁 Catégorie", value=cat.name if cat else "❌ Non définie", inline=True)
        
        # Rôle requis / Mode
        role_id = hub_data.get('required_role', 0)
        role = self.g.get_role(role_id) if role_id else None
        
        if role:
            mode_txt = f"🔒 **PRIVÉ**\n{role.mention}"
            e.add_field(name="🔐 Mode", value=mode_txt, inline=True)
            e.description = f"*Les vocaux créés seront invisibles pour les membres sans le rôle {role.name}*"
        else:
            e.add_field(name="🔐 Mode", value="🔓 **PUBLIC**\nTout le monde", inline=True)
            e.description = "*Tout le monde peut voir et rejoindre les vocaux créés*"
        
        # Nom par défaut
        default_name = hub_data.get('default_name', '🔊 Vocal de {user}')
        e.add_field(name="📝 Nom par défaut", value=f"`{default_name}`", inline=False)
        
        return e
    
    @discord.ui.button(label="📁 Catégorie", style=discord.ButtonStyle.primary, row=0)
    async def change_category(self, i, b):
        v = TempVoiceHubEditCategory(self.u, self.g, self.hub_id)
        await i.response.edit_message(
            embed=discord.Embed(title="📁 Changer la catégorie", description="Sélectionnez la nouvelle catégorie.", color=0x9B59B6),
            view=v
        )
    
    @discord.ui.button(label="🔐 Mode/Rôle", style=discord.ButtonStyle.primary, row=0)
    async def change_role(self, i, b):
        v = TempVoiceHubEditRole(self.u, self.g, self.hub_id)
        await i.response.edit_message(
            embed=discord.Embed(
                title="🔐 Changer le mode",
                description="**🔓 Public** = Tout le monde voit/rejoint les vocaux\n**🔒 Privé** = Seul le rôle choisi voit/rejoint les vocaux",
                color=0x9B59B6
            ),
            view=v
        )
    
    @discord.ui.button(label="📝 Nom par défaut", style=discord.ButtonStyle.secondary, row=0)
    async def change_name(self, i, b):
        await i.response.send_modal(TempVoiceHubNameModal(self.g, self.u, self.hub_id))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TempVoiceHubsListPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TempVoiceHubEditCategory(View):
    """Modifier la catégorie d'un hub"""
    def __init__(self, u, g, hub_id):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        self.hub_id = hub_id
        
        categories = list(g.categories)[:25]
        opts = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in categories]
        if opts:
            select = Select(placeholder="Choisir une catégorie...", options=opts)
            select.callback = self.select_callback
            self.add_item(select)
    
    async def select_callback(self, i):
        cat_id = int(i.data['values'][0])
        
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        hubs = voice_cfg.get('hubs', {})
        
        if str(self.hub_id) in hubs:
            hubs[str(self.hub_id)]['category'] = cat_id
            voice_cfg['hubs'] = hubs
            await db_set(self.g.id, 'temp_voice_config', voice_cfg)
        
        cat = self.g.get_channel(cat_id)
        v = TempVoiceHubEditPanel(self.u, self.g, self.hub_id)
        await i.response.edit_message(
            content=f"✅ Catégorie changée: **{cat.name}**",
            embed=await v.embed(),
            view=v
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TempVoiceHubEditPanel(self.u, self.g, self.hub_id)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TempVoiceHubEditRole(View):
    """Modifier le rôle requis d'un hub avec pagination complète"""
    def __init__(self, u, g, hub_id, page=0):
        super().__init__(timeout=300)
        self.u = u
        self.g = g
        self.hub_id = hub_id
        self.page = page
        
        # Filtrer les rôles
        self.all_roles = [r for r in sorted(g.roles, key=lambda x: x.position, reverse=True) if not r.is_default() and not r.managed]
        self.per_page = 24
        self.max_page = max(0, len(self.all_roles) // self.per_page)
        
        self._build()
    
    def _build(self):
        self.clear_items()
        
        start = self.page * self.per_page
        end = min(start + self.per_page, len(self.all_roles))
        page_roles = self.all_roles[start:end]
        
        opts = []
        if self.page == 0:
            opts.append(discord.SelectOption(
                label="🔓 Public (tous peuvent rejoindre)",
                value="0",
                description="Aucune restriction de rôle",
                emoji="✅"
            ))
        
        for r in page_roles:
            if len(opts) >= 25:
                break
            opts.append(discord.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                description="Réservé aux membres avec ce rôle",
                emoji="🔒"
            ))
        
        if opts:
            select = Select(
                placeholder=f"Sélectionner un rôle ({len(self.all_roles)} disponibles)...",
                options=opts,
                row=0
            )
            select.callback = self._on_select
            self.add_item(select)
        
        if self.max_page > 0:
            prev_btn = Button(label="◀️ Précédent", style=discord.ButtonStyle.primary, row=1, disabled=(self.page == 0))
            prev_btn.callback = self._prev
            self.add_item(prev_btn)
            
            info_btn = Button(label=f"Page {self.page + 1}/{self.max_page + 1}", style=discord.ButtonStyle.secondary, row=1, disabled=True)
            self.add_item(info_btn)
            
            next_btn = Button(label="Suivant ▶️", style=discord.ButtonStyle.primary, row=1, disabled=(self.page >= self.max_page))
            next_btn.callback = self._next
            self.add_item(next_btn)
        
        back_btn = Button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
        back_btn.callback = self._back
        self.add_item(back_btn)
    
    async def _prev(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        if self.page > 0:
            self.page -= 1
            self._build()
        
        try:
            await i.edit_original_response(view=self)
        except:
            pass
    
    async def _next(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        if self.page < self.max_page:
            self.page += 1
            self._build()
        
        try:
            await i.edit_original_response(view=self)
        except:
            pass
    
    async def _back(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        try:
            v = TempVoiceHubEditPanel(self.u, self.g, self.hub_id)
            await i.edit_original_response(embed=await v.embed(), view=v)
        except:
            pass
    
    async def _on_select(self, i: discord.Interaction):
        try:
            await i.response.defer()
        except:
            pass
        
        try:
            role_id = int(i.data['values'][0])
            
            c = await cfg(self.g.id)
            voice_cfg = c.get('temp_voice_config', {})
            hubs = voice_cfg.get('hubs', {})
            
            if str(self.hub_id) in hubs:
                hubs[str(self.hub_id)]['required_role'] = role_id
                voice_cfg['hubs'] = hubs
                await db_set(self.g.id, 'temp_voice_config', voice_cfg)
            
            role = self.g.get_role(role_id) if role_id else None
            
            if role:
                msg = f"✅ **Rôle changé: @{role.name}**\n🔒 Les vocaux seront invisibles pour les membres sans ce rôle"
            else:
                msg = f"✅ **Mode PUBLIC activé**\n🔓 Tout le monde peut voir et rejoindre les vocaux créés"
            
            v = TempVoiceHubEditPanel(self.u, self.g, self.hub_id)
            await i.edit_original_response(content=msg, embed=await v.embed(), view=v)
        except Exception as ex:
            print(f"[TempVoiceHubEditRole._on_select] {ex}")

class TempVoiceHubNameModal(Modal, title="📝 Nom par défaut"):
    name_input = TextInput(
        label="Nom du vocal (utilise {user} pour le pseudo)", 
        placeholder="🔊 Vocal de {user}", 
        default="🔊 Vocal de {user}",
        max_length=50
    )
    
    def __init__(self, g, u, hub_id):
        super().__init__()
        self.g = g
        self.u = u
        self.hub_id = hub_id
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        hubs = voice_cfg.get('hubs', {})
        
        if str(self.hub_id) in hubs:
            hubs[str(self.hub_id)]['default_name'] = self.name_input.value
            voice_cfg['hubs'] = hubs
            await db_set(self.g.id, 'temp_voice_config', voice_cfg)
        
        v = TempVoiceHubEditPanel(self.u, self.g, self.hub_id)
        await i.response.edit_message(
            content=f"✅ Nom par défaut changé: `{self.name_input.value}`",
            embed=await v.embed(),
            view=v
        )

class TempVoiceHubDeleteSelect(View):
    """Sélection d'un hub à supprimer"""
    def __init__(self, u, g, hubs):
        super().__init__(timeout=120)
        self.u = u
        self.g = g
        
        opts = []
        for hub_id, hub_data in list(hubs.items())[:25]:
            hub_ch = g.get_channel(int(hub_id))
            if hub_ch:
                opts.append(discord.SelectOption(label=f"🎤 {hub_ch.name}"[:25], value=hub_id))
            else:
                opts.append(discord.SelectOption(label=f"❌ Salon supprimé", value=hub_id, description=f"ID: {hub_id}"))
        
        if opts:
            select = Select(placeholder="Choisir un hub à supprimer...", options=opts)
            select.callback = self.select_callback
            self.add_item(select)
    
    async def select_callback(self, i):
        hub_id = i.data['values'][0]
        
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        hubs = voice_cfg.get('hubs', {})
        
        hub_ch = self.g.get_channel(int(hub_id))
        hub_name = hub_ch.name if hub_ch else f"ID: {hub_id}"
        
        if hub_id in hubs:
            del hubs[hub_id]
            voice_cfg['hubs'] = hubs
            await db_set(self.g.id, 'temp_voice_config', voice_cfg)
        
        v = TempVoicePanel(self.u, self.g)
        await i.response.edit_message(
            content=f"✅ Hub **{hub_name}** supprimé !",
            embed=await v.embed(),
            view=v
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TempVoiceHubsListPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TempVoicePermissionsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        perms = voice_cfg.get('owner_permissions', {
            'can_rename': True,
            'can_limit': True,
            'can_mute': True,
            'can_kick': True
        })
        
        e = discord.Embed(title="👑 Permissions du Propriétaire", color=0x9B59B6)
        e.description = "Définissez ce que le créateur du vocal peut faire."
        
        e.add_field(name="✏️ Renommer", value="✅ Oui" if perms.get('can_rename', True) else "❌ Non", inline=True)
        e.add_field(name="🔢 Limite membres", value="✅ Oui" if perms.get('can_limit', True) else "❌ Non", inline=True)
        e.add_field(name="🔇 Mute membres", value="✅ Oui" if perms.get('can_mute', True) else "❌ Non", inline=True)
        e.add_field(name="👢 Expulser membres", value="✅ Oui" if perms.get('can_kick', True) else "❌ Non", inline=True)
        
        return e
    
    async def toggle_perm(self, i, perm_key):
        c = await cfg(self.g.id)
        voice_cfg = c.get('temp_voice_config', {})
        perms = voice_cfg.get('owner_permissions', {
            'can_rename': True, 'can_limit': True, 'can_mute': True, 'can_kick': True
        })
        perms[perm_key] = not perms.get(perm_key, True)
        voice_cfg['owner_permissions'] = perms
        await db_set(self.g.id, 'temp_voice_config', voice_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="✏️ Renommer", style=discord.ButtonStyle.primary, row=0)
    async def toggle_rename(self, i, b):
        await self.toggle_perm(i, 'can_rename')
    
    @discord.ui.button(label="🔢 Limite", style=discord.ButtonStyle.primary, row=0)
    async def toggle_limit(self, i, b):
        await self.toggle_perm(i, 'can_limit')
    
    @discord.ui.button(label="🔇 Mute", style=discord.ButtonStyle.primary, row=0)
    async def toggle_mute(self, i, b):
        await self.toggle_perm(i, 'can_mute')
    
    @discord.ui.button(label="👢 Expulser", style=discord.ButtonStyle.primary, row=0)
    async def toggle_kick(self, i, b):
        await self.toggle_perm(i, 'can_kick')
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TempVoicePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── SALONS COMMANDES ───────────────────────────────

class CommandChannelsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        cmd_channels = c.get('command_channels', {})
        
        e = discord.Embed(title="📍 Salons des Commandes", color=C.BLURPLE)
        e.description = "Définissez dans quels salons chaque commande peut être utilisée.\n*Vide = partout*"
        
        commands = [
            ('stat', '📊 /stat'),
            ('daily', '💵 /daily'),
            ('work', '💼 /work'),
            ('balance', '💰 /balance'),
            ('games', '🎮 Jeux'),
        ]
        
        for cmd_key, cmd_name in commands:
            allowed = cmd_channels.get(cmd_key, [])
            if isinstance(allowed, int):
                # Ancien format (un seul salon)
                ch = self.g.get_channel(allowed) if allowed else None
                value = ch.mention if ch else "*Partout*"
            elif isinstance(allowed, list) and allowed:
                mentions = []
                for ch_id in allowed[:3]:
                    ch = self.g.get_channel(ch_id)
                    if ch:
                        mentions.append(ch.mention)
                value = ", ".join(mentions)
                if len(allowed) > 3:
                    value += f" +{len(allowed) - 3}"
            else:
                value = "*Partout*"
            e.add_field(name=cmd_name, value=value, inline=True)
        
        e.set_footer(text="💡 /suggestion et /trade se configurent dans Commandes")
        return e
    
    @discord.ui.select(
        placeholder="📍 Sélectionner une commande...",
        options=[
            discord.SelectOption(label="/stat", value="stat", emoji="📊"),
            discord.SelectOption(label="/daily", value="daily", emoji="💵"),
            discord.SelectOption(label="/work", value="work", emoji="💼"),
            discord.SelectOption(label="/balance", value="balance", emoji="💰"),
            discord.SelectOption(label="Tous les jeux", value="games", emoji="🎮"),
        ],
        row=0
    )
    async def select_cmd(self, i, s):
        cmd_key = s.values[0]
        c = await cfg(self.g.id)
        cmd_channels = c.get('command_channels', {})
        current = cmd_channels.get(cmd_key, [])
        # Convertir ancien format si nécessaire
        if isinstance(current, int):
            current = [current] if current else []
        
        v = PaginatedChannelSelectForCmd(self.u, self.g, cmd_key, current)
        await i.response.edit_message(
            embed=discord.Embed(
                title=f"📍 Salons pour /{cmd_key}", 
                description="Sélectionnez les salons autorisés.\nCliquez sur un salon pour l'ajouter/retirer.\n*Vide = partout*",
                color=C.BLURPLE
            ), 
            view=v
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class PaginatedChannelSelectForCmd(View):
    """Sélecteur paginé multi-salons pour les commandes"""
    def __init__(self, u, g, cmd_key, current_channels, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.cmd_key = cmd_key
        self.current_channels = current_channels or []
        self.page = page
        self.channels = list(g.text_channels)
        self.max_page = max(0, (len(self.channels) - 1) // 23)
        
        self._build()
    
    def _build(self):
        start = self.page * 23
        end = start + 23
        page_channels = self.channels[start:end]
        
        opts = []
        for ch in page_channels:
            is_selected = ch.id in self.current_channels
            label = f"{'✅ ' if is_selected else ''}# {ch.name}"[:25]
            desc = ch.category.name[:50] if ch.category else "Sans catégorie"
            opts.append(discord.SelectOption(
                label=label, 
                value=str(ch.id),
                description=desc
            ))
        
        if opts:
            select = CmdChannelSelectMenu(self, opts)
            self.add_item(select)
        
        # Boutons navigation
        if self.page > 0:
            btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.prev_page
            self.add_item(btn)
        
        if self.page < self.max_page:
            btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.next_page
            self.add_item(btn)
        
        # Bouton valider
        if self.current_channels:
            btn = discord.ui.Button(label=f"✅ Valider ({len(self.current_channels)})", style=discord.ButtonStyle.success, row=1)
        else:
            btn = discord.ui.Button(label="✅ Partout", style=discord.ButtonStyle.success, row=1)
        btn.callback = self.validate
        self.add_item(btn)
        
        # Bouton retour
        btn = discord.ui.Button(label="❌ Annuler", style=discord.ButtonStyle.danger, row=1)
        btn.callback = self.cancel
        self.add_item(btn)
    
    async def prev_page(self, i):
        v = PaginatedChannelSelectForCmd(self.u, self.g, self.cmd_key, self.current_channels, self.page - 1)
        await i.response.edit_message(view=v)
    
    async def next_page(self, i):
        v = PaginatedChannelSelectForCmd(self.u, self.g, self.cmd_key, self.current_channels, self.page + 1)
        await i.response.edit_message(view=v)
    
    async def validate(self, i):
        c = await cfg(self.g.id)
        cmd_channels = c.get('command_channels', {})
        cmd_channels[self.cmd_key] = self.current_channels
        await db_set(self.g.id, 'command_channels', cmd_channels)
        v = CommandChannelsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    async def cancel(self, i):
        v = CommandChannelsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class CmdChannelSelectMenu(Select):
    def __init__(self, parent, opts):
        super().__init__(
            placeholder=f"Page {parent.page + 1}/{parent.max_page + 1} - Cliquez pour ajouter/retirer",
            options=opts,
            max_values=min(len(opts), 10)
        )
        self.parent = parent
    
    async def callback(self, i):
        for val in self.values:
            ch_id = int(val)
            if ch_id in self.parent.current_channels:
                self.parent.current_channels.remove(ch_id)
            else:
                self.parent.current_channels.append(ch_id)
        
        v = PaginatedChannelSelectForCmd(
            self.parent.u, self.parent.g, 
            self.parent.cmd_key, self.parent.current_channels, 
            self.parent.page
        )
        await i.response.edit_message(view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           💡 SYSTÈME D'AIDE AUTOMATIQUE
# ═══════════════════════════════════════════════════════════════════════════════

# Cache pour stocker les IDs des messages d'aide actuels
auto_help_messages = {}  # {channel_id: message_id}

class AutoHelpPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        auto_helps = c.get('auto_help_channels', {})
        
        e = discord.Embed(title="💡 Messages d'Aide Automatiques", color=0x3498DB)
        e.description = "Configurez des messages d'aide qui restent toujours en bas du salon.\n\n*À chaque nouveau message, l'aide se repositionne en bas automatiquement.*"
        
        if auto_helps:
            help_list = []
            for ch_id, help_data in list(auto_helps.items())[:10]:
                ch = self.g.get_channel(int(ch_id))
                if ch:
                    title = help_data.get('title', 'Aide')[:30]
                    help_list.append(f"• {ch.mention} - **{title}**")
            if help_list:
                e.add_field(name=f"📋 Salons configurés ({len(auto_helps)})", value="\n".join(help_list), inline=False)
        else:
            e.add_field(name="📋 Salons configurés", value="*Aucun salon configuré*", inline=False)
        
        e.set_footer(text="💡 L'aide est renvoyée automatiquement après chaque message")
        return e
    
    @discord.ui.button(label="➕ Ajouter un salon", style=discord.ButtonStyle.success, row=0)
    async def add_channel(self, i, b):
        v = AutoHelpChannelSelect(self.u, self.g)
        await i.response.edit_message(
            embed=discord.Embed(title="📍 Choisir le salon", description="Sélectionnez le salon où afficher l'aide automatique", color=0x3498DB),
            view=v
        )
    
    @discord.ui.button(label="📋 Gérer les aides", style=discord.ButtonStyle.primary, row=0)
    async def manage_helps(self, i, b):
        c = await cfg(self.g.id)
        auto_helps = c.get('auto_help_channels', {})
        if not auto_helps:
            return await i.response.send_message("❌ Aucun salon configuré", ephemeral=True)
        
        v = await AutoHelpManageView.create(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class AutoHelpChannelSelect(View):
    def __init__(self, u, g, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.page = page
        self.channels = list(g.text_channels)
        self.max_page = max(0, (len(self.channels) - 1) // 24)
        self._build()
    
    def _build(self):
        start = self.page * 24
        end = start + 24
        page_channels = self.channels[start:end]
        
        opts = []
        for ch in page_channels:
            desc = ch.category.name[:50] if ch.category else "Sans catégorie"
            opts.append(discord.SelectOption(label=f"# {ch.name}"[:25], value=str(ch.id), description=desc))
        
        if opts:
            self.add_item(AutoHelpChannelSelectMenu(self, opts))
        
        if self.page > 0:
            btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.prev_page
            self.add_item(btn)
        
        if self.page < self.max_page:
            btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.next_page
            self.add_item(btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        v = AutoHelpChannelSelect(self.u, self.g, self.page - 1)
        await i.response.edit_message(view=v)
    
    async def next_page(self, i):
        v = AutoHelpChannelSelect(self.u, self.g, self.page + 1)
        await i.response.edit_message(view=v)
    
    async def go_back(self, i):
        v = AutoHelpPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AutoHelpChannelSelectMenu(Select):
    def __init__(self, parent, opts):
        super().__init__(placeholder=f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un salon...", options=opts)
        self.parent = parent
    
    async def callback(self, i):
        channel_id = self.values[0]
        await i.response.send_modal(AutoHelpConfigModal(self.parent.u, self.parent.g, channel_id))

class AutoHelpConfigModal(Modal, title="💡 Configurer l'aide automatique"):
    help_title = TextInput(
        label="Titre de l'aide",
        placeholder="Ex: Comment faire une suggestion ?",
        max_length=100
    )
    help_content = TextInput(
        label="Contenu de l'aide",
        placeholder="Ex: Utilisez la commande /suggestion pour proposer une idée !",
        style=discord.TextStyle.paragraph,
        max_length=1500
    )
    help_color = TextInput(
        label="Couleur (hex sans #)",
        placeholder="Ex: 3498DB",
        default="3498DB",
        max_length=6,
        required=False
    )
    
    def __init__(self, u, g, channel_id):
        super().__init__()
        self.u = u
        self.g = g
        self.channel_id = channel_id
    
    async def on_submit(self, i):
        try:
            # Valider la couleur
            color_hex = self.help_color.value or "3498DB"
            try:
                color = int(color_hex, 16)
            except:
                color = 0x3498DB
            
            # Sauvegarder la configuration
            c = await cfg(self.g.id)
            auto_helps = c.get('auto_help_channels', {})
            auto_helps[str(self.channel_id)] = {
                'title': self.help_title.value,
                'content': self.help_content.value,
                'color': color,
                'enabled': True
            }
            await db_set(self.g.id, 'auto_help_channels', auto_helps)
            
            # Envoyer le premier message d'aide
            channel = self.g.get_channel(int(self.channel_id))
            if channel:
                e = discord.Embed(title=f"💡 {self.help_title.value}", color=color)
                e.description = self.help_content.value
                e.set_footer(text="Ce message se repositionne automatiquement")
                msg = await channel.send(embed=e)
                auto_help_messages[int(self.channel_id)] = msg.id
            
            v = AutoHelpPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        except Exception as ex:
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)

class AutoHelpManageView(View):
    def __init__(self, u, g, opts=None):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        
        # Ajouter le sélecteur si des options sont fournies
        if opts:
            select = Select(placeholder="🗑️ Supprimer une aide...", options=opts, row=0)
            select.callback = self.delete_callback
            self.add_item(select)
    
    @classmethod
    async def create(cls, u, g):
        """Factory method pour créer la vue avec les options chargées"""
        c = await cfg(g.id)
        auto_helps = c.get('auto_help_channels', {})
        
        opts = []
        for ch_id, help_data in list(auto_helps.items())[:25]:
            ch = g.get_channel(int(ch_id))
            if ch:
                opts.append(discord.SelectOption(
                    label=f"# {ch.name}"[:25],
                    value=ch_id,
                    description=help_data.get('title', 'Aide')[:50]
                ))
        
        return cls(u, g, opts if opts else None)
    
    async def embed(self):
        c = await cfg(self.g.id)
        auto_helps = c.get('auto_help_channels', {})
        
        e = discord.Embed(title="📋 Gérer les aides automatiques", color=0x3498DB)
        
        help_list = []
        for ch_id, help_data in list(auto_helps.items())[:15]:
            ch = self.g.get_channel(int(ch_id))
            if ch:
                status = "✅" if help_data.get('enabled', True) else "❌"
                title = help_data.get('title', 'Aide')[:30]
                help_list.append(f"{status} {ch.mention} - **{title}**")
        
        e.description = "\n".join(help_list) if help_list else "*Aucune aide configurée*"
        return e
    
    async def delete_callback(self, i):
        channel_id = i.data['values'][0]
        c = await cfg(self.g.id)
        auto_helps = c.get('auto_help_channels', {})
        
        if channel_id in auto_helps:
            del auto_helps[channel_id]
            await db_set(self.g.id, 'auto_help_channels', auto_helps)
            
            # Supprimer le message d'aide actuel
            ch_id = int(channel_id)
            if ch_id in auto_help_messages:
                try:
                    ch = self.g.get_channel(ch_id)
                    if ch:
                        msg = await ch.fetch_message(auto_help_messages[ch_id])
                        await msg.delete()
                except:
                    pass
                del auto_help_messages[ch_id]
        
        if auto_helps:
            v = await AutoHelpManageView.create(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        else:
            v = AutoHelpPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AutoHelpPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

async def handle_auto_help(message):
    """Gère le repositionnement automatique des messages d'aide"""
    
    try:
        c = await cfg(message.guild.id)
        auto_helps = c.get('auto_help_channels', {})
        
        channel_id_str = str(message.channel.id)
        if channel_id_str not in auto_helps:
            return
        
        help_data = auto_helps[channel_id_str]
        if not help_data.get('enabled', True):
            return
        
        channel_id = message.channel.id
        
        # Vérifier si le message n'est pas le message d'aide lui-même
        if channel_id in auto_help_messages:
            if message.id == auto_help_messages[channel_id]:
                return  # C'est notre propre message d'aide, ne pas boucler
        
        # ═══════════════ SUPPRESSION ROBUSTE DE L'ANCIEN MESSAGE ═══════════════
        old_msg_id = auto_help_messages.get(channel_id)
        if old_msg_id:
            # Supprimer du cache immédiatement pour éviter les doublons
            del auto_help_messages[channel_id]
            
            # Essayer plusieurs méthodes de suppression
            try:
                old_msg = await message.channel.fetch_message(old_msg_id)
                await old_msg.delete()
            except discord.NotFound:
                pass  # Message déjà supprimé
            except discord.Forbidden:
                pass  # Pas les permissions
            except Exception as ex:
                print(f"[AUTO_HELP] Erreur suppression ancien message: {ex}")
                # Essayer de supprimer via l'historique
                try:
                    async for msg in message.channel.history(limit=50):
                        if msg.author.id == bot.user.id and msg.embeds:
                            if msg.embeds[0].footer and "repositionne automatiquement" in str(msg.embeds[0].footer.text or ""):
                                await msg.delete()
                                break
                except:
                    pass
        
        # Petit délai pour que le message soit bien envoyé
        await asyncio.sleep(0.3)
        
        # Créer et envoyer le nouveau message d'aide
        e = discord.Embed(title=f"💡 {help_data.get('title', 'Aide')}", color=help_data.get('color', 0x3498DB))
        e.description = help_data.get('content', '')
        e.set_footer(text="Ce message se repositionne automatiquement")
        
        new_msg = await message.channel.send(embed=e)
        auto_help_messages[channel_id] = new_msg.id
        
    except Exception as ex:
        print(f"Erreur auto_help: {ex}")

# ═══════════════════════════════════════════════════════════════════════════════
#                           💰 FONCTIONS ÉCONOMIE
# ═══════════════════════════════════════════════════════════════════════════════

async def get_user_economy(guild_id, user_id):
    """Récupère les données économiques d'un utilisateur"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT coins, bank, xp, level, last_daily, last_work, message_count FROM economy WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'coins': row[0] or 0, 
                    'bank': row[1] or 0, 
                    'xp': row[2] or 0, 
                    'level': row[3] or 1,
                    'last_daily': row[4], 
                    'last_work': row[5],
                    'message_count': row[6] or 0
                }
            else:
                # Créer l'entrée
                await db.execute(
                    'INSERT INTO economy (guild_id, user_id, coins, bank, xp, level, message_count) VALUES (?, ?, 0, 0, 0, 1, 0)',
                    (guild_id, user_id)
                )
                await db.commit()
                return {'coins': 0, 'bank': 0, 'xp': 0, 'level': 1, 'last_daily': None, 'last_work': None, 'message_count': 0}

async def update_user_economy(guild_id, user_id, **kwargs):
    """Met à jour les données économiques d'un utilisateur"""
    async with aiosqlite.connect(DB_PATH) as db:
        # S'assurer que l'utilisateur existe
        await db.execute(
            'INSERT OR IGNORE INTO economy (guild_id, user_id, coins, bank, xp, level) VALUES (?, ?, 0, 0, 0, 1)',
            (guild_id, user_id)
        )
        
        # Construire la requête de mise à jour
        updates = []
        values = []
        for key, value in kwargs.items():
            updates.append(f"{key}=?")
            values.append(value)
        
        if updates:
            values.extend([guild_id, user_id])
            await db.execute(
                f'UPDATE economy SET {", ".join(updates)} WHERE guild_id=? AND user_id=?',
                values
            )
            await db.commit()

async def add_coins(guild_id, user_id, amount):
    """Ajoute des coins à un utilisateur de manière atomique"""
    async with aiosqlite.connect(DB_PATH) as db:
        # S'assurer que l'utilisateur existe
        await db.execute(
            'INSERT OR IGNORE INTO economy (guild_id, user_id, coins, bank, xp, level) VALUES (?, ?, 0, 0, 0, 1)',
            (guild_id, user_id)
        )
        # Mise à jour atomique
        await db.execute(
            'UPDATE economy SET coins = MAX(0, coins + ?) WHERE guild_id=? AND user_id=?',
            (amount, guild_id, user_id)
        )
        await db.commit()
        
        # Récupérer le nouveau solde
        async with db.execute(
            'SELECT coins FROM economy WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_xp(guild_id, user_id, amount, channel=None):
    """Ajoute de l'XP et vérifie le level up"""
    eco = await get_user_economy(guild_id, user_id)
    new_xp = eco['xp'] + amount
    current_level = eco['level']
    
    # Calcul du niveau (formule: XP requis = niveau * 100)
    xp_for_next = current_level * 100
    new_level = current_level
    
    while new_xp >= xp_for_next:
        new_xp -= xp_for_next
        new_level += 1
        xp_for_next = new_level * 100
    
    await update_user_economy(guild_id, user_id, xp=new_xp, level=new_level)
    
    # Vérifier si level up
    if new_level > current_level:
        return new_level  # Retourne le nouveau niveau si level up
    return None

async def check_command_channel(interaction, cmd_key):
    """Vérifie si la commande peut être exécutée dans ce salon - supporte un salon ou une liste"""
    c = await cfg(interaction.guild.id)
    cmd_channels = c.get('command_channels', {})
    allowed = cmd_channels.get(cmd_key, 0)
    
    # Si pas de restriction
    if not allowed:
        return True
    
    # Si c'est une liste de salons
    if isinstance(allowed, list):
        if not allowed or interaction.channel.id in allowed:
            return True
        # Construire la liste des salons autorisés
        mentions = []
        for ch_id in allowed[:5]:  # Max 5 mentions
            ch = interaction.guild.get_channel(ch_id)
            if ch:
                mentions.append(ch.mention)
        if len(allowed) > 5:
            mentions.append(f"et {len(allowed) - 5} autres...")
        await interaction.response.send_message(
            f"❌ Cette commande n'est utilisable que dans: {', '.join(mentions)}",
            ephemeral=True
        )
        return False
    
    # Si c'est un seul salon (ancien format)
    if allowed and allowed != interaction.channel.id:
        ch = interaction.guild.get_channel(allowed)
        if ch:
            await interaction.response.send_message(
                f"❌ Cette commande n'est utilisable que dans {ch.mention}",
                ephemeral=True
            )
            return False
    return True

class GiveawayListPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        e = discord.Embed(title="📋 Cadeaux Actifs", color=C.GREEN)
        
        giveaways = []
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'SELECT id, title, end_time, participants FROM giveaways WHERE guild_id=? AND ended=0 ORDER BY end_time',
                    (self.g.id,)
                ) as cursor:
                    async for row in cursor:
                        giveaways.append(row)
        except:
            pass
        
        if not giveaways:
            e.description = "❌ Aucun cadeau actif"
        else:
            desc = ""
            for gw_id, title, end_time_str, participants_str in giveaways[:10]:
                try:
                    end_time = datetime.fromisoformat(end_time_str)
                    participants = json.loads(participants_str) if participants_str else []
                    desc += f"**#{gw_id}** • {title}\n"
                    desc += f"└ ⏰ <t:{int(end_time.timestamp())}:R> • 👥 {len(participants)} participants\n\n"
                except:
                    pass
            e.description = desc or "❌ Aucun cadeau"
        
        return e
    
    @discord.ui.button(label="🏁 Terminer un Cadeau", style=discord.ButtonStyle.danger, row=0)
    async def end_giveaway(self, i, b):
        # Récupérer les giveaways actifs
        giveaways = []
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'SELECT id, title FROM giveaways WHERE guild_id=? AND ended=0',
                    (self.g.id,)
                ) as cursor:
                    async for row in cursor:
                        giveaways.append(row)
        except:
            pass
        
        if not giveaways:
            return await i.response.send_message("❌ Aucun cadeau actif", ephemeral=True)
        
        opts = [discord.SelectOption(label=f"#{gw_id} - {title[:40]}", value=str(gw_id)) for gw_id, title in giveaways[:25]]
        v = GiveawayEndSelectView(self.u, self.g, opts)
        await i.response.send_message("🏁 Sélectionnez le cadeau à terminer:", view=v, ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = GiveawayPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class GiveawayEndSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(GiveawayEndSelect(u, g, opts))

class GiveawayEndSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un cadeau...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        giveaway_id = int(self.values[0])
        result = await end_giveaway(self.g, giveaway_id)
        await i.response.edit_message(content=result, view=None)

async def end_giveaway(guild, giveaway_id):
    """Termine un giveaway et tire un gagnant"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT channel_id, message_id, title, prize, participants FROM giveaways WHERE id=? AND guild_id=?',
                (giveaway_id, guild.id)
            ) as cursor:
                row = await cursor.fetchone()
                
                if not row:
                    return "❌ Cadeau introuvable"
                
                channel_id, message_id, title, prize, participants_str = row
                participants = json.loads(participants_str) if participants_str else []
                
                # Marquer comme terminé
                await db.execute('UPDATE giveaways SET ended=1 WHERE id=?', (giveaway_id,))
                await db.commit()
        
        channel = guild.get_channel(channel_id)
        
        if not participants:
            # Pas de participants
            if channel:
                e = discord.Embed(title=f"🎁 {title} - Terminé", color=C.RED)
                e.description = "❌ **Aucun participant !**\n\nLe cadeau n'a pas pu être attribué."
                try:
                    msg = await channel.fetch_message(message_id)
                    await msg.edit(embed=e, view=None)
                except:
                    pass
            return "❌ Aucun participant pour ce cadeau"
        
        # Tirer un gagnant au hasard
        import random
        winner_id = random.choice(participants)
        winner = guild.get_member(winner_id)
        
        if channel:
            e = discord.Embed(title=f"🎁 {title} - Terminé !", color=C.GOLD)
            e.description = f"🎉 **FÉLICITATIONS !**\n\n🏆 Le gagnant est: **{winner.mention if winner else f'<@{winner_id}>'}**"
            e.add_field(name="🎁 Prix", value=f"```{prize}```", inline=False)
            e.add_field(name="👥 Participants", value=f"```{len(participants)}```", inline=True)
            e.set_footer(text="Merci à tous les participants !")
            e.timestamp = now()
            
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=e, view=None)
                await channel.send(f"🎉 **{winner.mention if winner else f'<@{winner_id}>'}** a gagné **{title}** !")
            except:
                pass
        
        return f"✅ Cadeau terminé ! Gagnant: {winner.display_name if winner else winner_id}"
        
    except Exception as ex:
        return f"❌ Erreur: {ex}"

# ═══════════════════════════════════════════════════════════════════════════════
#                           📨 MESSAGE PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class MessagePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        e = discord.Embed(title="📨 Messages Automatiques", color=C.BLURPLE)
        e.description = "Programmez des messages récurrents pour votre serveur."
        
        # Compter les messages programmés
        count = 0
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'SELECT COUNT(*) FROM scheduled_messages WHERE guild_id=? AND enabled=1',
                    (self.g.id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    count = row[0] if row else 0
        except:
            pass
        
        e.add_field(
            name="📊 Statistiques",
            value=f"```\n📨 Messages actifs: {count}\n```",
            inline=False
        )
        
        e.add_field(
            name="💡 Fonctionnalités",
            value="• Messages récurrents (minutes, heures, jours, semaines)\n"
                  "• Heure d'envoi personnalisable\n"
                  "• Embeds personnalisés avec image",
            inline=False
        )
        
        return e
    
    @discord.ui.button(label="➕ Créer un Message", style=discord.ButtonStyle.success, row=0)
    async def create(self, i, b):
        modal = AutoMessageCreateModal(self.u, self.g)
        await i.response.send_modal(modal)
    
    @discord.ui.button(label="📋 Voir les Messages", style=discord.ButtonStyle.primary, row=0)
    async def view_list(self, i, b):
        v = AutoMessageListPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = CentrePanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class AutoMessageCreateModal(Modal):
    def __init__(self, u, g):
        super().__init__(title="📨 Créer un Message Auto")
        self.u = u
        self.g = g
        
        self.title_input = TextInput(label="Titre de l'embed", placeholder="Ex: Rappel quotidien", max_length=100)
        self.description_input = TextInput(label="Description", placeholder="Le contenu du message...", style=discord.TextStyle.paragraph, max_length=2000)
        self.frequency_input = TextInput(label="Fréquence (ex: 1h, 12h, 1d, 1w)", placeholder="m=minutes, h=heures, d=jours, w=semaines", max_length=10)
        self.hour_input = TextInput(label="Heure d'envoi (0-23)", placeholder="Ex: 12 pour midi, 0 pour minuit", max_length=2)
        self.image_input = TextInput(label="URL de l'image (optionnel)", placeholder="https://...", required=False, max_length=500)
        
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.frequency_input)
        self.add_item(self.hour_input)
        self.add_item(self.image_input)
    
    async def on_submit(self, i):
        # Parser la fréquence
        freq_str = self.frequency_input.value.lower().strip()
        freq_seconds = parse_duration_to_seconds(freq_str)
        
        if freq_seconds < 60:
            return await i.response.send_message("❌ La fréquence minimum est de 1 minute (1m)", ephemeral=True)
        
        # Déterminer le type de fréquence
        if 'w' in freq_str:
            frequency_type = 'weekly'
            frequency_value = freq_seconds // 604800
        elif 'd' in freq_str:
            frequency_type = 'daily'
            frequency_value = freq_seconds // 86400
        elif 'h' in freq_str:
            frequency_type = 'hourly'
            frequency_value = freq_seconds // 3600
        else:
            frequency_type = 'minutes'
            frequency_value = freq_seconds // 60
        
        # Parser l'heure
        try:
            send_hour = int(self.hour_input.value)
            if not 0 <= send_hour <= 23:
                raise ValueError()
        except:
            return await i.response.send_message("❌ L'heure doit être entre 0 et 23", ephemeral=True)
        
        # Sauvegarder les données
        msg_data = {
            'title': self.title_input.value,
            'description': self.description_input.value,
            'frequency': frequency_type,
            'frequency_value': frequency_value,
            'send_hour': send_hour,
            'image_url': self.image_input.value or None
        }
        
        # Demander le salon
        channels = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in channels]
        v = AutoMessageChannelSelectView(self.u, self.g, opts, msg_data)
        await i.response.send_message("📢 **Sélectionnez le salon** où publier le message:", view=v, ephemeral=True)

class AutoMessageChannelSelectView(View):
    def __init__(self, u, g, opts, data):
        super().__init__(timeout=120)
        self.add_item(AutoMessageChannelSelect(u, g, opts, data))

class AutoMessageChannelSelect(Select):
    def __init__(self, u, g, opts, data):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.data = data
    
    async def callback(self, i):
        channel_id = int(self.values[0])
        channel = self.g.get_channel(channel_id)
        
        if not channel:
            return await i.response.edit_message(content="❌ Salon introuvable", view=None)
        
        # Sauvegarder en BDD
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    INSERT INTO scheduled_messages (guild_id, channel_id, title, description, image_url, frequency, frequency_value, send_hour)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    self.g.id, channel_id,
                    self.data['title'], self.data['description'], self.data['image_url'],
                    self.data['frequency'], self.data['frequency_value'], self.data['send_hour']
                ))
                await db.commit()
        except Exception as ex:
            print(f"Erreur sauvegarde message auto: {ex}")
            return await i.response.edit_message(content=f"❌ Erreur: {ex}", view=None)
        
        freq_labels = {
            'minutes': f"toutes les {self.data['frequency_value']} minute(s)",
            'hourly': f"toutes les {self.data['frequency_value']} heure(s)",
            'daily': f"tous les {self.data['frequency_value']} jour(s)",
            'weekly': f"toutes les {self.data['frequency_value']} semaine(s)"
        }
        
        await i.response.edit_message(
            content=f"✅ **Message automatique créé !**\n\n"
                    f"📢 Salon: {channel.mention}\n"
                    f"🔄 Fréquence: {freq_labels.get(self.data['frequency'], self.data['frequency'])}\n"
                    f"⏰ Heure d'envoi: {self.data['send_hour']}h00",
            view=None
        )

class AutoMessageListPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        e = discord.Embed(title="📋 Messages Automatiques", color=C.BLURPLE)
        
        messages = []
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'SELECT id, channel_id, title, frequency, frequency_value, send_hour, enabled FROM scheduled_messages WHERE guild_id=? ORDER BY id',
                    (self.g.id,)
                ) as cursor:
                    async for row in cursor:
                        messages.append(row)
        except:
            pass
        
        if not messages:
            e.description = "❌ Aucun message automatique configuré"
        else:
            freq_labels = {'minutes': 'min', 'hourly': 'h', 'daily': 'j', 'weekly': 'sem'}
            desc = ""
            for msg_id, channel_id, title, freq, freq_val, hour, enabled in messages[:10]:
                channel = self.g.get_channel(channel_id)
                status = "✅" if enabled else "❌"
                desc += f"**#{msg_id}** {status} • {title[:30]}\n"
                desc += f"└ {channel.mention if channel else 'Salon inconnu'} • {freq_val}{freq_labels.get(freq, freq)} • {hour}h00\n\n"
            e.description = desc
        
        return e
    
    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def delete_msg(self, i, b):
        messages = []
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'SELECT id, title FROM scheduled_messages WHERE guild_id=?',
                    (self.g.id,)
                ) as cursor:
                    async for row in cursor:
                        messages.append(row)
        except:
            pass
        
        if not messages:
            return await i.response.send_message("❌ Aucun message à supprimer", ephemeral=True)
        
        opts = [discord.SelectOption(label=f"#{msg_id} - {title[:40]}", value=str(msg_id)) for msg_id, title in messages[:25]]
        v = AutoMessageDeleteSelectView(self.u, self.g, opts)
        await i.response.send_message("🗑️ Sélectionnez le message à supprimer:", view=v, ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MessagePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AutoMessageDeleteSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(AutoMessageDeleteSelect(u, g, opts))

class AutoMessageDeleteSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un message...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        msg_id = int(self.values[0])
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('DELETE FROM scheduled_messages WHERE id=? AND guild_id=?', (msg_id, self.g.id))
                await db.commit()
            await i.response.edit_message(content="✅ Message automatique supprimé !", view=None)
        except:
            await i.response.edit_message(content="❌ Erreur lors de la suppression", view=None)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 STATISTIQUES PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class StatPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📊 Statistiques & Activité", color=C.PURPLE)
        e.description = "**🔄 Système automatique** - Les actions sont exécutées automatiquement chaque jour.\n*⚠️ Aucune mention automatique des membres*"
        
        # Config actuelle
        stat_cfg = c.get('stat_config', {})
        
        # Actions multiples
        action_labels = {'ping': '📊 Rapport', 'remove_role': '🎭 Rôle', 'kick': '👢 Kick'}
        
        actions_7d = stat_cfg.get('actions_7d', [])
        actions_30d = stat_cfg.get('actions_30d', [])
        
        actions_7d_txt = " + ".join([action_labels.get(a, a) for a in actions_7d]) if actions_7d else "❌ Aucune"
        actions_30d_txt = " + ".join([action_labels.get(a, a) for a in actions_30d]) if actions_30d else "❌ Aucune"
        
        role_id = stat_cfg.get('activity_role', 0)
        notif_ch = self.g.get_channel(stat_cfg.get('notif_channel', 0))
        recovery_ch = self.g.get_channel(stat_cfg.get('recovery_channel', 0))
        
        role = self.g.get_role(role_id) if role_id else None
        
        e.add_field(
            name="⚙️ Configuration",
            value=f"**Actions 7j:** {actions_7d_txt}\n"
                  f"**Actions 30j:** {actions_30d_txt}\n"
                  f"**Rôle:** {role.mention if role else '❌'} | **Notifs:** {notif_ch.mention if notif_ch else '❌'} | **Récup:** {recovery_ch.mention if recovery_ch else '❌'}",
            inline=False
        )
        
        # Compter les membres AFK
        afk_7d, afk_30d = await self.count_afk_members()
        e.add_field(name="😴 AFK 7 jours", value=f"**{afk_7d}** membre(s)", inline=True)
        e.add_field(name="💤 AFK 30 jours", value=f"**{afk_30d}** membre(s)", inline=True)
        e.add_field(name="👥 Total membres", value=f"**{self.g.member_count}**", inline=True)
        
        e.set_footer(text="💡 Les membres récupèrent leur rôle en envoyant un message ou en rejoignant un vocal")
        
        return e
    
    async def count_afk_members(self):
        """Compte les membres AFK sur 7j et 30j"""
        afk_7d = 0
        afk_30d = 0
        now_dt = now()
        seven_days_ago = now_dt - timedelta(days=7)
        thirty_days_ago = now_dt - timedelta(days=30)
        
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Membres trackés
                async with db.execute(
                    'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                    (self.g.id,)
                ) as cursor:
                    tracked_users = set()
                    async for row in cursor:
                        user_id, last_msg, last_vocal = row
                        tracked_users.add(user_id)
                        
                        last_activity = None
                        if last_msg:
                            try:
                                last_activity = datetime.fromisoformat(last_msg)
                            except:
                                pass
                        if last_vocal:
                            try:
                                lv = datetime.fromisoformat(last_vocal)
                                if not last_activity or lv > last_activity:
                                    last_activity = lv
                            except:
                                pass
                        
                        if last_activity:
                            if last_activity.replace(tzinfo=timezone.utc) < seven_days_ago.replace(tzinfo=timezone.utc):
                                afk_7d += 1
                            if last_activity.replace(tzinfo=timezone.utc) < thirty_days_ago.replace(tzinfo=timezone.utc):
                                afk_30d += 1
                
                # Membres non trackés = considérés comme AFK
                for member in self.g.members:
                    if not member.bot and member.id not in tracked_users:
                        afk_7d += 1
                        afk_30d += 1
        except:
            pass
        
        return afk_7d, afk_30d
    
    @discord.ui.button(label="⚙️ Configurer Actions", style=discord.ButtonStyle.primary, row=0)
    async def config_actions(self, i, b):
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📈 Voir Graphique", style=discord.ButtonStyle.success, row=0)
    async def view_graph(self, i, b):
        await i.response.defer()
        
        # Générer le graphique
        img = await self.generate_afk_graph()
        
        if img:
            file = discord.File(img, filename="afk_stats.png")
            e = discord.Embed(title="📊 Statistiques d'Activité", color=C.PURPLE)
            e.set_image(url="attachment://afk_stats.png")
            e.set_footer(text=f"{self.g.name} • Statistiques d'activité")
            await i.followup.send(embed=e, file=file, ephemeral=True)
        else:
            await i.followup.send("❌ Erreur lors de la génération du graphique", ephemeral=True)
    
    async def generate_afk_graph(self):
        """Génère un graphique des membres AFK"""
        try:
            afk_7d, afk_30d = await self.count_afk_members()
            active_members = self.g.member_count - afk_7d
            
            # Créer le graphique
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
            fig.patch.set_facecolor('#2f3136')
            
            # Graphique 1: Camembert AFK
            colors1 = ['#57F287', '#FEE75C', '#ED4245']
            sizes1 = [active_members, afk_7d - afk_30d, afk_30d]
            labels1 = [f'Actifs\n({active_members})', f'AFK 7j\n({afk_7d - afk_30d})', f'AFK 30j\n({afk_30d})']
            
            # Filtrer les valeurs nulles
            filtered = [(s, l, c) for s, l, c in zip(sizes1, labels1, colors1) if s > 0]
            if filtered:
                sizes1, labels1, colors1 = zip(*filtered)
            
            ax1.pie(sizes1, labels=labels1, colors=colors1, autopct='%1.1f%%', startangle=90,
                   textprops={'color': 'white', 'fontsize': 11, 'fontweight': 'bold'})
            ax1.set_title('📊 Répartition des Membres', color='white', fontsize=14, fontweight='bold', pad=20)
            ax1.set_facecolor('#2f3136')
            
            # Graphique 2: Barres
            categories = ['Actifs', 'AFK 7 jours', 'AFK 30 jours']
            values = [active_members, afk_7d, afk_30d]
            colors2 = ['#57F287', '#FEE75C', '#ED4245']
            
            bars = ax2.bar(categories, values, color=colors2, edgecolor='white', linewidth=2)
            ax2.set_ylabel('Nombre de membres', color='white', fontsize=12)
            ax2.set_title('📈 Statistiques d\'Activité', color='white', fontsize=14, fontweight='bold', pad=20)
            ax2.set_facecolor('#36393f')
            ax2.tick_params(colors='white')
            ax2.spines['bottom'].set_color('white')
            ax2.spines['left'].set_color('white')
            ax2.spines['top'].set_visible(False)
            ax2.spines['right'].set_visible(False)
            
            # Ajouter les valeurs sur les barres
            for bar, val in zip(bars, values):
                ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                        str(val), ha='center', color='white', fontweight='bold', fontsize=12)
            
            plt.tight_layout()
            
            # Sauvegarder en buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
            buf.seek(0)
            plt.close(fig)
            
            return buf
        except Exception as ex:
            print(f"Erreur graphique: {ex}")
            return None
    
    @discord.ui.button(label="⚡ Exécuter maintenant", style=discord.ButtonStyle.danger, row=0)
    async def execute_actions(self, i, b):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        actions_7d = stat_cfg.get('actions_7d', [])
        actions_30d = stat_cfg.get('actions_30d', [])
        
        if not actions_7d and not actions_30d:
            return await i.response.send_message("❌ Aucune action configurée. Configurez d'abord les actions.", ephemeral=True)
        
        afk_7d, afk_30d = await self.count_afk_members()
        
        await i.response.send_message(
            f"⚠️ **Exécution manuelle des actions**\n\n"
            f"**Membres concernés:**\n"
            f"• 😴 AFK 7 jours: **{afk_7d}** membres\n"
            f"• 💤 AFK 30 jours: **{afk_30d}** membres\n\n"
            f"*Le système s'exécute automatiquement chaque jour, mais vous pouvez forcer l'exécution maintenant.*",
            view=StatExecuteConfirmView(self.u, self.g),
            ephemeral=True
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class StatActionPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        
        e = discord.Embed(title="⚙️ Configuration des Actions", color=C.ORANGE)
        e.description = "Configurez les actions automatiques sur les membres inactifs.\n**Vous pouvez sélectionner plusieurs actions !**\n\n*⚠️ Aucune mention automatique - Vous ferez le @here/@everyone vous-même*"
        
        action_labels = {'ping': '📊 Rapport', 'remove_role': '🎭 Retirer rôle', 'kick': '👢 Kick'}
        
        # Actions 7 jours (maintenant une liste)
        actions_7d = stat_cfg.get('actions_7d', [])
        if actions_7d:
            actions_7d_txt = " + ".join([action_labels.get(a, a) for a in actions_7d])
        else:
            actions_7d_txt = "❌ Aucune"
        
        # Actions 30 jours (maintenant une liste)
        actions_30d = stat_cfg.get('actions_30d', [])
        if actions_30d:
            actions_30d_txt = " + ".join([action_labels.get(a, a) for a in actions_30d])
        else:
            actions_30d_txt = "❌ Aucune"
        
        role_id = stat_cfg.get('activity_role', 0)
        notif_ch = self.g.get_channel(stat_cfg.get('notif_channel', 0))
        recovery_ch = self.g.get_channel(stat_cfg.get('recovery_channel', 0))
        role = self.g.get_role(role_id) if role_id else None
        
        e.add_field(
            name="😴 Actions après 7 jours",
            value=actions_7d_txt,
            inline=True
        )
        e.add_field(
            name="💤 Actions après 30 jours",
            value=actions_30d_txt,
            inline=True
        )
        e.add_field(name="\u200b", value="\u200b", inline=True)
        
        e.add_field(
            name="🎭 Rôle d'activité",
            value=role.mention if role else "❌ Non défini",
            inline=True
        )
        e.add_field(
            name="📢 Salon notifications",
            value=notif_ch.mention if notif_ch else "❌ Non défini",
            inline=True
        )
        e.add_field(
            name="💬 Salon récupération",
            value=recovery_ch.mention if recovery_ch else "❌ Non défini",
            inline=True
        )
        
        e.set_footer(text="💡 Le rôle sera redonné automatiquement si le membre envoie un message ou rejoint un vocal")
        return e
    
    @discord.ui.select(
        placeholder="😴 Actions 7 jours (multi-sélection)...",
        options=[
            discord.SelectOption(label="Envoyer le rapport", value="ping", emoji="📊", description="Afficher le rapport dans le salon de notifications"),
            discord.SelectOption(label="Retirer le rôle", value="remove_role", emoji="🎭", description="Enlever le rôle d'activité"),
            discord.SelectOption(label="Kick les membres", value="kick", emoji="👢", description="Expulser du serveur"),
        ],
        min_values=0,
        max_values=3,
        row=0
    )
    async def action_7d(self, i, s):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['actions_7d'] = s.values  # Liste d'actions
        await db_set(self.g.id, 'stat_config', stat_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.select(
        placeholder="💤 Actions 30 jours (multi-sélection)...",
        options=[
            discord.SelectOption(label="Envoyer le rapport", value="ping", emoji="📊", description="Afficher le rapport dans le salon de notifications"),
            discord.SelectOption(label="Retirer le rôle", value="remove_role", emoji="🎭", description="Enlever le rôle d'activité"),
            discord.SelectOption(label="Kick les membres", value="kick", emoji="👢", description="Expulser du serveur"),
        ],
        min_values=0,
        max_values=3,
        row=1
    )
    async def action_30d(self, i, s):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['actions_30d'] = s.values  # Liste d'actions
        await db_set(self.g.id, 'stat_config', stat_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=2)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles if not r.is_default() and not r.managed and r < self.g.me.top_role][:25]
        if not roles:
            return await i.response.send_message("❌ Aucun rôle disponible", ephemeral=True)
        opts = [discord.SelectOption(label=r.name[:25], value=str(r.id)) for r in roles]
        v = StatRoleSelectView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Sélectionner le rôle d'activité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📢 Notifs", style=discord.ButtonStyle.primary, row=2)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = StatChannelSelectView(self.u, self.g, opts, 'notif_channel')
        await i.response.edit_message(embed=discord.Embed(title="📢 Salon de notifications", description="Salon où seront envoyées les alertes d'inactivité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="💬 Récup", style=discord.ButtonStyle.primary, row=2)
    async def set_recovery(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = StatChannelSelectView(self.u, self.g, opts, 'recovery_channel')
        await i.response.edit_message(embed=discord.Embed(title="💬 Salon de récupération", description="Salon où les membres doivent écrire pour récupérer leur activité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = StatPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="👢 Expulser AFK 7j", style=discord.ButtonStyle.danger, row=3)
    async def kick_7d(self, i, b):
        count = await count_afk_members_by_days(self.g, 7)
        await i.response.send_message(
            f"⚠️ **ATTENTION - Action irréversible !**\n\n"
            f"Vous êtes sur le point d'expulser **{count}** membre(s) inactif(s) depuis **7 jours**.\n\n"
            f"Cette action est **DÉFINITIVE** et ne peut pas être annulée.",
            view=KickConfirmView(self.u, self.g, 7, count),
            ephemeral=True
        )
    
    @discord.ui.button(label="👢 Expulser AFK 30j", style=discord.ButtonStyle.danger, row=3)
    async def kick_30d(self, i, b):
        count = await count_afk_members_by_days(self.g, 30)
        await i.response.send_message(
            f"⚠️ **ATTENTION - Action irréversible !**\n\n"
            f"Vous êtes sur le point d'expulser **{count}** membre(s) inactif(s) depuis **30 jours**.\n\n"
            f"Cette action est **DÉFINITIVE** et ne peut pas être annulée.",
            view=KickConfirmView(self.u, self.g, 30, count),
            ephemeral=True
        )

async def count_afk_members_by_days(guild, days):
    """Compte les membres AFK depuis X jours"""
    count = 0
    now_dt = now()
    cutoff = now_dt - timedelta(days=days)
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                tracked_users = set()
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    tracked_users.add(user_id)
                    
                    last_activity = None
                    if last_msg:
                        try:
                            last_activity = datetime.fromisoformat(last_msg)
                        except:
                            pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except:
                            pass
                    
                    if last_activity:
                        if last_activity.replace(tzinfo=timezone.utc) < cutoff.replace(tzinfo=timezone.utc):
                            member = guild.get_member(user_id)
                            if member and not member.bot and member.id != guild.owner_id:
                                count += 1
            
            for member in guild.members:
                if not member.bot and member.id not in tracked_users and member.id != guild.owner_id:
                    count += 1
    except:
        pass
    
    return count

class KickConfirmView(View):
    def __init__(self, u, g, days, count):
        super().__init__(timeout=60)
        self.u = u
        self.g = g
        self.days = days
        self.count = count
    
    @discord.ui.button(label="✅ Confirmer l'expulsion", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        await i.response.defer()
        for item in self.children:
            item.disabled = True
        await i.message.edit(view=self)
        result = await kick_afk_members(self.g, self.days)
        await i.followup.send(result, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Expulsion annulée.", view=None)

async def kick_afk_members(guild, days):
    """Expulse tous les membres AFK depuis X jours"""
    now_dt = now()
    cutoff = now_dt - timedelta(days=days)
    
    kicked = 0
    failed = 0
    skipped = 0
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                tracked_users = {}
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    last_activity = None
                    if last_msg:
                        try: last_activity = datetime.fromisoformat(last_msg)
                        except: pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except: pass
                    tracked_users[user_id] = last_activity
        
        for member in list(guild.members):
            if member.bot:
                continue
            if member.id == guild.owner_id:
                skipped += 1
                continue
            if member.top_role >= guild.me.top_role:
                skipped += 1
                continue
            
            last_activity = tracked_users.get(member.id)
            is_afk = False
            if not last_activity:
                is_afk = True
            else:
                la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
                is_afk = la_utc < cutoff.replace(tzinfo=timezone.utc)
            
            if is_afk:
                try:
                    await member.kick(reason=f"Inactivité de plus de {days} jours")
                    kicked += 1
                    await asyncio.sleep(0.5)
                except:
                    failed += 1
        
        result = f"✅ **Expulsion terminée !**\n\n"
        result += f"👢 **{kicked}** membre(s) expulsé(s)\n"
        if failed > 0:
            result += f"❌ **{failed}** échec(s)\n"
        if skipped > 0:
            result += f"⏭️ **{skipped}** ignoré(s)\n"
        result += f"\n*Critère: inactif depuis plus de {days} jours*"
        return result
        
    except Exception as ex:
        return f"❌ Erreur: {ex}"

class StatRoleSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(StatRoleSelect(u, g, opts))

class StatRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['activity_role'] = int(self.values[0])
        await db_set(self.g.id, 'stat_config', stat_cfg)
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class StatChannelSelectView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(StatChannelSelect(u, g, opts, key))

class StatChannelSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg[self.key] = int(self.values[0])
        await db_set(self.g.id, 'stat_config', stat_cfg)
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class StatExecuteConfirmView(View):
    def __init__(self, u, g):
        super().__init__(timeout=60)
        self.u = u
        self.g = g
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        await i.response.defer()
        result = await execute_afk_actions(self.g)
        await i.followup.send(result, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Action annulée", view=None)

async def execute_afk_actions(guild):
    """Exécute les actions sur les membres AFK - Version ULTRA optimisée"""
    c = await cfg(guild.id)
    stat_cfg = c.get('stat_config', {})
    
    actions_7d = stat_cfg.get('actions_7d', [])
    actions_30d = stat_cfg.get('actions_30d', [])
    role_id = stat_cfg.get('activity_role', 0)
    notif_ch_id = stat_cfg.get('notif_channel', 0)
    recovery_ch_id = stat_cfg.get('recovery_channel', 0)
    
    role = guild.get_role(role_id) if role_id else None
    notif_ch = guild.get_channel(notif_ch_id) if notif_ch_id else None
    recovery_ch = guild.get_channel(recovery_ch_id) if recovery_ch_id else None
    
    now_dt = now()
    seven_days_ago = now_dt - timedelta(days=7)
    thirty_days_ago = now_dt - timedelta(days=30)
    
    results = {
        'ping_7d': 0, 'remove_role_7d': 0, 'kick_7d': 0,
        'ping_30d': 0, 'remove_role_30d': 0, 'kick_30d': 0,
        'immune_skipped': 0
    }
    
    try:
        # ═══════════════ ÉTAPE 1: COLLECTE DES DONNÉES ═══════════════
        user_activities = {}
        immune_roles = set()
        immune_users = set()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Activités
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    last_activity = None
                    if last_msg:
                        try: last_activity = datetime.fromisoformat(last_msg)
                        except: pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except: pass
                    user_activities[user_id] = last_activity
            
            # Rôles immunisés
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (guild.id,)) as cursor:
                async for row in cursor:
                    immune_roles.add(row[0])
            
            # Utilisateurs immunisés
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (guild.id,)) as cursor:
                async for row in cursor:
                    immune_users.add(row[0])
        
        # ═══════════════ ÉTAPE 2: CLASSIFICATION (avec immunité) ═══════════════
        afk_members_7d = []
        afk_members_30d = []
        members_to_remove_role_7d = []
        members_to_remove_role_30d = []
        members_to_kick_7d = []
        members_to_kick_30d = []
        
        for member in guild.members:
            if member.bot or member.id == guild.owner_id:
                continue
            
            # ⚠️ VÉRIFICATION IMMUNITÉ - Les immunisés sont ignorés !
            if member.id in immune_users or any(r.id in immune_roles for r in member.roles):
                results['immune_skipped'] += 1
                continue
            
            # Admins sont aussi immunisés
            if member.guild_permissions.administrator:
                results['immune_skipped'] += 1
                continue
            
            last_activity = user_activities.get(member.id)
            
            if not last_activity:
                is_afk_7d = True
                is_afk_30d = True
            else:
                la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
                is_afk_7d = la_utc < seven_days_ago.replace(tzinfo=timezone.utc)
                is_afk_30d = la_utc < thirty_days_ago.replace(tzinfo=timezone.utc)
            
            if is_afk_30d:
                afk_members_30d.append(member)
                if role and role in member.roles and actions_30d:
                    members_to_remove_role_30d.append(member)
                if 'kick' in actions_30d and member.top_role < guild.me.top_role:
                    members_to_kick_30d.append(member)
            elif is_afk_7d:
                afk_members_7d.append(member)
                if role and role in member.roles and actions_7d:
                    members_to_remove_role_7d.append(member)
                if 'kick' in actions_7d and member.top_role < guild.me.top_role:
                    members_to_kick_7d.append(member)
        
        # ═══════════════ ÉTAPE 3: RETRAIT DES RÔLES EN BATCH ═══════════════
        async def remove_role_batch(members_list, reason):
            """Retire les rôles par batch de 10 en parallèle"""
            removed = 0
            batch_size = 10
            
            for i in range(0, len(members_list), batch_size):
                batch = members_list[i:i + batch_size]
                tasks = []
                for member in batch:
                    tasks.append(member.remove_roles(role, reason=reason))
                
                results_batch = await asyncio.gather(*tasks, return_exceptions=True)
                removed += sum(1 for r in results_batch if not isinstance(r, Exception))
                
                # Petit délai entre les batches pour éviter le rate limit
                if i + batch_size < len(members_list):
                    await asyncio.sleep(0.5)
            
            return removed
        
        # Retirer les rôles 30j
        if members_to_remove_role_30d:
            results['remove_role_30d'] = await remove_role_batch(members_to_remove_role_30d, "Inactivité 30 jours")
        
        # Retirer les rôles 7j
        if members_to_remove_role_7d:
            results['remove_role_7d'] = await remove_role_batch(members_to_remove_role_7d, "Inactivité 7 jours")
        
        # ═══════════════ ÉTAPE 4: KICKS (séquentiels car plus sensible) ═══════════════
        for member in members_to_kick_30d:
            try:
                await member.kick(reason="Inactivité 30 jours")
                results['kick_30d'] += 1
            except:
                pass
        
        for member in members_to_kick_7d:
            try:
                await member.kick(reason="Inactivité 7 jours")
                results['kick_7d'] += 1
            except:
                pass
        
        # ═══════════════ ÉTAPE 5: NOTIFICATIONS ═══════════════
        if notif_ch:
            recovery_mention = recovery_ch.mention if recovery_ch else "un salon textuel ou vocal"
            
            # Notification 30 jours (si ping activé et membres non kickés)
            members_to_ping_30d = [m for m in afk_members_30d if 'kick' not in actions_30d]
            if 'ping' in actions_30d and members_to_ping_30d:
                results['ping_30d'] = len(members_to_ping_30d)
                await send_compact_afk_notification(
                    notif_ch, members_to_ping_30d, 30, recovery_mention, role
                )
            
            # Notification 7 jours (si ping activé et membres non kickés)
            members_to_ping_7d = [m for m in afk_members_7d if 'kick' not in actions_7d]
            if 'ping' in actions_7d and members_to_ping_7d:
                results['ping_7d'] = len(members_to_ping_7d)
                await send_compact_afk_notification(
                    notif_ch, members_to_ping_7d, 7, recovery_mention, role
                )
        
        # Résumé
        summary = "✅ **Actions exécutées:**\n\n"
        
        if results['ping_7d']: summary += f"📊 **Rapport 7j** envoyé ({results['ping_7d']} membre(s) inactifs)\n"
        if results['remove_role_7d']: summary += f"🎭 **{results['remove_role_7d']}** rôle(s) retiré(s) (7j)\n"
        if results['kick_7d']: summary += f"👢 **{results['kick_7d']}** membre(s) expulsé(s) (7j)\n"
        
        if results['ping_30d']: summary += f"📊 **Rapport 30j** envoyé ({results['ping_30d']} membre(s) inactifs)\n"
        if results['remove_role_30d']: summary += f"🎭 **{results['remove_role_30d']}** rôle(s) retiré(s) (30j)\n"
        if results['kick_30d']: summary += f"👢 **{results['kick_30d']}** membre(s) expulsé(s) (30j)\n"
        
        if results['immune_skipped']: summary += f"\n👑 **{results['immune_skipped']}** membre(s) immunisé(s) ignoré(s)\n"
        
        total_actions = results['ping_7d'] + results['remove_role_7d'] + results['kick_7d'] + results['ping_30d'] + results['remove_role_30d'] + results['kick_30d']
        
        if total_actions == 0:
            summary = "ℹ️ Aucune action effectuée.\n\n**Vérifiez:**\n• Les actions sont-elles configurées ?\n• Y a-t-il des membres inactifs ?"
            if results['immune_skipped']:
                summary += f"\n\n👑 *{results['immune_skipped']} membre(s) immunisé(s) ont été ignorés*"
        else:
            summary += "\n💡 *Vous pouvez maintenant utiliser @here ou @everyone pour notifier les membres*"
        
        return summary
        
    except Exception as ex:
        return f"❌ Erreur: {ex}"

async def send_compact_afk_notification(channel, members, days, recovery_mention, role):
    """Envoie uniquement le rapport d'inactivité - SANS liste de membres"""
    if not members:
        return
    
    # Configuration selon la durée
    if days == 7:
        title = "😴 Rapport d'Inactivité - 7 Jours"
        color = C.YELLOW
        emoji = "⚠️"
        severity = "modérée"
    else:
        title = "💤 Rapport d'Inactivité - 30 Jours"
        color = C.RED
        emoji = "🚨"
        severity = "critique"
    
    role_txt = f"**{role.name}**" if role else "d'activité"
    
    # ═══════════════ EMBED PRINCIPAL (UNIQUE) ═══════════════
    e = discord.Embed(title=title, color=color)
    
    e.description = (
        f"{emoji} **{len(members)}** membre(s) ont été détectés comme inactifs.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    # Statistiques
    e.add_field(
        name="📊 Statistiques",
        value=f"```\n"
              f"Membres concernés : {len(members)}\n"
              f"Durée d'inactivité: {days} jours\n"
              f"Sévérité          : {severity.upper()}\n"
              f"```",
        inline=False
    )
    
    # Actions effectuées
    actions_txt = ""
    if role:
        actions_txt += f"🎭 Le rôle {role_txt} a été **retiré** aux membres inactifs"
    else:
        actions_txt += f"📋 {len(members)} membre(s) détecté(s) comme inactif(s)"
    
    e.add_field(
        name="⚡ Actions effectuées",
        value=actions_txt,
        inline=False
    )
    
    # Comment récupérer
    e.add_field(
        name="🔄 Comment récupérer son activité ?",
        value=f"```\n"
              f"1️⃣ Envoyer un message dans {recovery_mention}\n"
              f"   → Le message sera supprimé automatiquement\n"
              f"   → Le rôle sera redonné instantanément\n\n"
              f"2️⃣ OU rejoindre un salon vocal\n"
              f"   → Le rôle sera redonné automatiquement\n"
              f"```",
        inline=False
    )
    
    e.set_footer(text=f"📌 Aucune mention automatique • L'administrateur peut ping @here ou @everyone")
    e.timestamp = now()
    
    await channel.send(embed=e)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔄 TÂCHE AUTOMATIQUE INACTIVITÉ
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(hours=24)
async def check_afk_automatic():
    """Vérifie automatiquement l'inactivité des membres chaque jour"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, data FROM guild_config') as cursor:
                async for row in cursor:
                    guild_id, data_str = row
                    try:
                        data = json.loads(data_str) if data_str else {}
                        guild = bot.get_guild(guild_id)
                        if not guild:
                            continue
                        
                        stat_cfg = data.get('stat_config', {})
                        actions_7d = stat_cfg.get('actions_7d', [])
                        actions_30d = stat_cfg.get('actions_30d', [])
                        
                        # Si aucune action configurée, passer
                        if not actions_7d and not actions_30d:
                            continue
                        
                        # Exécuter les actions automatiques
                        await execute_afk_actions_auto(guild, stat_cfg)
                        
                    except Exception as ex:
                        print(f"Erreur AFK auto {guild_id}: {ex}")
                        continue
    except Exception as ex:
        print(f"Erreur tâche AFK: {ex}")

@check_afk_automatic.before_loop
async def before_afk_check():
    await bot.wait_until_ready()

async def execute_afk_actions_auto(guild, stat_cfg):
    """Exécute les actions automatiques sur les membres AFK"""
    actions_7d = stat_cfg.get('actions_7d', [])
    actions_30d = stat_cfg.get('actions_30d', [])
    role_id = stat_cfg.get('activity_role', 0)
    notif_ch_id = stat_cfg.get('notif_channel', 0)
    recovery_ch_id = stat_cfg.get('recovery_channel', 0)
    
    role = guild.get_role(role_id) if role_id else None
    notif_ch = guild.get_channel(notif_ch_id) if notif_ch_id else None
    recovery_ch = guild.get_channel(recovery_ch_id) if recovery_ch_id else None
    
    now_dt = now()
    seven_days_ago = now_dt - timedelta(days=7)
    thirty_days_ago = now_dt - timedelta(days=30)
    
    # Récupérer les activités
    user_activities = {}
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    last_activity = None
                    if last_msg:
                        try: last_activity = datetime.fromisoformat(last_msg)
                        except: pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except: pass
                    user_activities[user_id] = last_activity
    except:
        return
    
    # Classifier les membres
    afk_members_7d = []
    afk_members_30d = []
    
    for member in guild.members:
        if member.bot or member.id == guild.owner_id:
            continue
        
        last_activity = user_activities.get(member.id)
        
        if not last_activity:
            is_afk_7d = True
            is_afk_30d = True
        else:
            la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
            is_afk_7d = la_utc < seven_days_ago.replace(tzinfo=timezone.utc)
            is_afk_30d = la_utc < thirty_days_ago.replace(tzinfo=timezone.utc)
        
        if is_afk_30d:
            afk_members_30d.append(member)
        elif is_afk_7d:
            afk_members_7d.append(member)
    
    # ═══════════════ ACTIONS 30 JOURS ═══════════════
    kicked_30d = []
    role_removed_30d = []
    
    for member in afk_members_30d:
        # Retirer le rôle
        if 'remove_role' in actions_30d and role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Inactivité 30 jours (auto)")
                role_removed_30d.append(member)
            except: pass
        
        # Kick
        if 'kick' in actions_30d:
            try:
                if member.top_role < guild.me.top_role:
                    await member.kick(reason="Inactivité 30 jours (auto)")
                    kicked_30d.append(member)
                    await asyncio.sleep(0.3)
            except: pass
    
    # Notification 30j (seulement si ping ET pas kick)
    members_to_notify_30d = [m for m in afk_members_30d if m not in kicked_30d]
    if 'ping' in actions_30d and members_to_notify_30d and notif_ch:
        recovery_mention = recovery_ch.mention if recovery_ch else "un salon textuel"
        await send_compact_afk_notification(notif_ch, members_to_notify_30d, 30, recovery_mention, role if 'remove_role' in actions_30d else None)
    
    # ═══════════════ ACTIONS 7 JOURS ═══════════════
    kicked_7d = []
    role_removed_7d = []
    
    for member in afk_members_7d:
        # Retirer le rôle
        if 'remove_role' in actions_7d and role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Inactivité 7 jours (auto)")
                role_removed_7d.append(member)
            except: pass
        
        # Kick
        if 'kick' in actions_7d:
            try:
                if member.top_role < guild.me.top_role:
                    await member.kick(reason="Inactivité 7 jours (auto)")
                    kicked_7d.append(member)
                    await asyncio.sleep(0.3)
            except: pass
    
    # Notification 7j (seulement si ping ET pas kick)
    members_to_notify_7d = [m for m in afk_members_7d if m not in kicked_7d]
    if 'ping' in actions_7d and members_to_notify_7d and notif_ch:
        recovery_mention = recovery_ch.mention if recovery_ch else "un salon textuel"
        await send_compact_afk_notification(notif_ch, members_to_notify_7d, 7, recovery_mention, role if 'remove_role' in actions_7d else None)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📺 CONFIG SALON
# ═══════════════════════════════════════════════════════════════════════════════

class ChanPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        e = discord.Embed(title="📺 Configuration des salons", color=C.ORANGE)
        if configs:
            lines = []
            for ch_id, conf in list(configs.items())[:15]:
                ch = self.g.get_channel(int(ch_id))
                if ch:
                    icons = ""
                    if not conf.get('messages', True): icons += "💬❌ "
                    if not conf.get('images', True): icons += "🖼️❌ "
                    if not conf.get('gifs', True): icons += "🎞️❌ "
                    if not conf.get('emojis', True): icons += "😀❌ "
                    if not conf.get('links', True): icons += "🔗❌ "
                    if conf.get('commands_only', False): icons += "🤖✅ "
                    lines.append(f"{ch.mention}: {icons or '✅ Tout autorisé'}")
            e.description = "\n".join(lines)
        else:
            e.description = "*Aucun salon configuré*"
        return e
    
    @discord.ui.button(label="➕ Configurer un salon", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        await i.response.edit_message(embed=discord.Embed(title="📺 Choisir un salon", color=C.ORANGE), view=ChanSelectView(self.u, self.g, opts))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ChanSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ChanSelect(u, g, opts))

class ChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        v = EditChanCfg(self.u, self.g, self.values[0])
        await i.response.edit_message(embed=await v.embed(), view=v)

class EditChanCfg(View):
    def __init__(self, u, g, ch_id):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.ch_id = ch_id
    
    async def get_conf(self):
        c = await cfg(self.g.id)
        return c.get('channel_configs', {}).get(str(self.ch_id), {'messages': True, 'images': True, 'gifs': True, 'emojis': True, 'links': True, 'commands_only': False})
    
    async def save(self, conf):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        configs[str(self.ch_id)] = conf
        await db_set(self.g.id, 'channel_configs', configs)
    
    async def embed(self):
        ch = self.g.get_channel(int(self.ch_id))
        conf = await self.get_conf()
        s = lambda k: "✅ Autorisé" if conf.get(k, True) else "❌ Bloqué"
        so = lambda k: "✅ Activé" if conf.get(k, False) else "❌ Désactivé"
        e = discord.Embed(title=f"📺 Configuration de #{ch.name if ch else '?'}", color=C.ORANGE)
        e.description = f"💬 Messages: {s('messages')}\n🖼️ Images: {s('images')}\n🎞️ GIFs: {s('gifs')}\n😀 Emojis: {s('emojis')}\n🔗 Liens: {s('links')}\n\n🤖 **Commandes bot uniquement**: {so('commands_only')}"
        return e
    
    async def toggle(self, i, key, default=True):
        conf = await self.get_conf()
        conf[key] = not conf.get(key, default)
        await self.save(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="💬 Messages", style=discord.ButtonStyle.primary, row=0)
    async def t1(self, i, b): await self.toggle(i, 'messages')
    
    @discord.ui.button(label="🖼️ Images", style=discord.ButtonStyle.primary, row=0)
    async def t2(self, i, b): await self.toggle(i, 'images')
    
    @discord.ui.button(label="🎞️ GIFs", style=discord.ButtonStyle.primary, row=0)
    async def t3(self, i, b): await self.toggle(i, 'gifs')
    
    @discord.ui.button(label="😀 Emojis", style=discord.ButtonStyle.primary, row=1)
    async def t4(self, i, b): await self.toggle(i, 'emojis')
    
    @discord.ui.button(label="🔗 Liens", style=discord.ButtonStyle.primary, row=1)
    async def t5(self, i, b): await self.toggle(i, 'links')
    
    @discord.ui.button(label="🤖 Commandes uniquement", style=discord.ButtonStyle.success, row=1)
    async def t6(self, i, b): await self.toggle(i, 'commands_only', False)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = ChanPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎫 TICKET CONFIG PANEL (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

class TicketMainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎫 Configuration Tickets", color=C.PURPLE)
        staff = self.g.get_role(c.get('ticket_staff', 0))
        lch = self.g.get_channel(c.get('ticket_log', 0))
        e.add_field(name="👮 Rôle Staff", value=staff.mention if staff else "❌ Non configuré", inline=True)
        e.add_field(name="📜 Salon Logs", value=lch.mention if lch else "❌ Non configuré", inline=True)
        panels = c.get('ticket_panels', {})
        if panels:
            pl = []
            for pid, pd in list(panels.items())[:10]:
                cat = self.g.get_channel(pd.get('category', 0))
                pl.append(f"• **{pd.get('name', pid)[:20]}** → `{cat.name if cat else '❌'}` ({len(pd.get('questions', []))} questions, max {pd.get('max', 1)})")
            e.add_field(name=f"📋 Panels ({len(panels)})", value="\n".join(pl), inline=False)
        else:
            e.add_field(name="📋 Panels", value="*Aucun panel créé*", inline=False)
        return e
    
    @discord.ui.button(label="👮 Définir Staff", style=discord.ButtonStyle.primary, row=0)
    async def staff(self, i, b):
        v = PaginatedRoleSelectForStaffGlobal(self.u, self.g)
        total_roles = len(v.roles)
        total_pages = v.max_page + 1
        await i.response.edit_message(
            embed=discord.Embed(
                title="👮 Choisir le rôle Staff", 
                description=f"**{total_roles} rôles** disponibles • Page 1/{total_pages}\n\nCe rôle aura accès à **tous** les tickets.",
                color=C.PURPLE
            ), 
            view=v
        )
    
    @discord.ui.button(label="📜 Définir Logs", style=discord.ButtonStyle.primary, row=0)
    async def logs(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        await i.response.edit_message(embed=discord.Embed(title="📜 Choisir le salon Logs", color=C.PURPLE), view=TkLogView(self.u, self.g, opts))
    
    @discord.ui.button(label="➕ Nouveau Panel", style=discord.ButtonStyle.success, row=1)
    async def new(self, i, b):
        await i.response.send_modal(NewPanelModal(self.u, self.g))
    
    @discord.ui.button(label="📝 Modifier Panel", style=discord.ButtonStyle.secondary, row=1)
    async def edit(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if not panels:
            return await i.response.send_message("❌ Aucun panel créé", ephemeral=True)
        opts = [discord.SelectOption(label=pd.get('name', pid)[:25], value=pid) for pid, pd in list(panels.items())[:25]]
        await i.response.edit_message(embed=discord.Embed(title="📝 Choisir un panel", color=C.PURPLE), view=EditPanelSelectView(self.u, self.g, opts))
    
    @discord.ui.button(label="🔄 Rafraîchir", style=discord.ButtonStyle.secondary, row=2)
    async def ref(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class TkStaffView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TkStaffSel(u, g, opts))

class PaginatedRoleSelectForStaffGlobal(View):
    """Sélecteur de rôle staff global avec pagination"""
    def __init__(self, u, g, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.page = page
        self.roles = [r for r in g.roles[1:] if not r.is_bot_managed()]
        self.per_page = 24
        self.max_page = max(0, (len(self.roles) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        start = self.page * self.per_page
        end = start + self.per_page
        page_roles = self.roles[start:end]
        
        opts = []
        for r in page_roles:
            color_hex = f"#{r.color.value:06x}" if r.color.value else "Défaut"
            opts.append(discord.SelectOption(
                label=f"@{r.name}"[:25], 
                value=str(r.id),
                description=f"Couleur: {color_hex}"[:50]
            ))
        
        if opts:
            self.add_item(StaffGlobalRoleSelect(self, opts))
        
        # Boutons de pagination
        if self.page > 0:
            btn = discord.ui.Button(label="◀️ Page préc.", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.prev_page
            self.add_item(btn)
        
        if self.page < self.max_page:
            btn = discord.ui.Button(label="▶️ Page suiv.", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.next_page
            self.add_item(btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        v = PaginatedRoleSelectForStaffGlobal(self.u, self.g, self.page - 1)
        embed = discord.Embed(
            title="👮 Choisir le rôle Staff", 
            description=f"**{len(self.roles)} rôles** disponibles • Page {self.page}/{self.max_page + 1}\n\nCe rôle aura accès à **tous** les tickets.",
            color=C.PURPLE
        )
        await i.response.edit_message(embed=embed, view=v)
    
    async def next_page(self, i):
        v = PaginatedRoleSelectForStaffGlobal(self.u, self.g, self.page + 1)
        embed = discord.Embed(
            title="👮 Choisir le rôle Staff", 
            description=f"**{len(self.roles)} rôles** disponibles • Page {self.page + 2}/{self.max_page + 1}\n\nCe rôle aura accès à **tous** les tickets.",
            color=C.PURPLE
        )
        await i.response.edit_message(embed=embed, view=v)
    
    async def go_back(self, i):
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class StaffGlobalRoleSelect(Select):
    def __init__(self, parent, opts):
        placeholder = f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un rôle..."
        super().__init__(placeholder=placeholder, options=opts)
        self.parent = parent
    
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_staff', int(self.values[0]))
        v = TicketMainPanel(self.parent.u, self.parent.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TkStaffSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_staff', int(self.values[0]))
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TkLogView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TkLogSel(u, g, opts))

class TkLogSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_log', int(self.values[0]))
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class NewPanelModal(Modal, title="➕ Nouveau Panel"):
    name = TextInput(label="Nom du panel", placeholder="Support, Partenariat...", max_length=30)
    mx = TextInput(label="Max tickets par utilisateur", placeholder="1", default="1", max_length=2)
    
    def __init__(self, u, g):
        super().__init__()
        self.u = u
        self.g = g
    
    async def on_submit(self, i):
        pid = str(int(time.time()))
        mxt = max(1, min(10, int(self.mx.value) if self.mx.value.isdigit() else 1))
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        panels[pid] = {'name': self.name.value, 'category': 0, 'questions': [], 'max': mxt}
        await db_set(self.g.id, 'ticket_panels', panels)
        v = PanelEditView(self.u, self.g, pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class EditPanelSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(EditPanelSel(u, g, opts))

class EditPanelSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un panel...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        v = PanelEditView(self.u, self.g, self.values[0])
        await i.response.edit_message(embed=await v.embed(), view=v)

class PanelEditView(View):
    def __init__(self, u, g, pid):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def get_panel(self):
        c = await cfg(self.g.id)
        return c.get('ticket_panels', {}).get(self.pid, {})
    
    async def embed(self):
        pnl = await self.get_panel()
        c = await cfg(self.g.id)
        e = discord.Embed(title=f"🎫 Panel: {pnl.get('name', '?')}", color=C.PURPLE)
        cat = self.g.get_channel(pnl.get('category', 0))
        
        # Rôle staff du panel ou global
        staff_role_id = pnl.get('staff_role', 0)
        if staff_role_id:
            staff_role = self.g.get_role(staff_role_id)
            staff_txt = staff_role.mention if staff_role else "❌ Rôle introuvable"
        else:
            global_staff = self.g.get_role(c.get('ticket_staff', 0))
            staff_txt = f"{global_staff.mention} *(global)*" if global_staff else "❌ Non configuré"
        
        e.add_field(name="📁 Catégorie", value=cat.name if cat else "❌ Non configuré", inline=True)
        e.add_field(name="🔢 Max tickets", value=str(pnl.get('max', 1)), inline=True)
        e.add_field(name="👥 Rôle Staff", value=staff_txt, inline=True)
        
        qs = pnl.get('questions', [])
        if qs:
            e.add_field(name=f"📝 Questions ({len(qs)})", value="\n".join([f"• {q['title']}" for q in qs[:5]]), inline=False)
        else:
            e.add_field(name="📝 Questions", value="*Aucune question*", inline=False)
        return e
    
    @discord.ui.button(label="📁 Catégorie", style=discord.ButtonStyle.primary, row=0)
    async def cat(self, i, b):
        cats = list(self.g.categories)[:25]
        if not cats:
            return await i.response.send_message("❌ Aucune catégorie sur ce serveur", ephemeral=True)
        opts = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in cats]
        await i.response.edit_message(embed=discord.Embed(title="📁 Choisir la catégorie", color=C.PURPLE), view=PanelCatView(self.u, self.g, self.pid, opts))
    
    @discord.ui.button(label="👥 Rôle Staff", style=discord.ButtonStyle.primary, row=0)
    async def staff_role(self, i, b):
        v = PaginatedRoleSelectForPanel(self.u, self.g, self.pid)
        total_roles = len(v.roles)
        total_pages = v.max_page + 1
        await i.response.edit_message(
            embed=discord.Embed(
                title="👥 Rôle Staff du Panel", 
                description=f"**{total_roles} rôles** disponibles • Page 1/{total_pages}\n\nChoisissez le rôle qui gère ce panel.\n*Aucun = utilise le rôle staff global*",
                color=C.PURPLE
            ), 
            view=v
        )
    
    @discord.ui.button(label="📝 Questions", style=discord.ButtonStyle.primary, row=0)
    async def qs(self, i, b):
        v = PanelQsView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🔢 Max tickets", style=discord.ButtonStyle.secondary, row=1)
    async def mx(self, i, b):
        await i.response.send_modal(SetMaxModal(self.u, self.g, self.pid))
    
    @discord.ui.button(label="📤 Envoyer", style=discord.ButtonStyle.success, row=1)
    async def send(self, i, b):
        pnl = await self.get_panel()
        c = await cfg(self.g.id)
        if not pnl.get('category'):
            return await i.response.send_message("❌ Configure la catégorie d'abord!", ephemeral=True)
        # Vérifier qu'un rôle staff est configuré (panel ou global)
        if not pnl.get('staff_role') and not c.get('ticket_staff'):
            return await i.response.send_message("❌ Configure le rôle Staff d'abord (panel ou global)!", ephemeral=True)
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {ch.name}"[:25], value=str(ch.id)) for ch in chs]
        await i.response.edit_message(embed=discord.Embed(title="📤 Où envoyer le panel?", color=C.PURPLE), view=SendPanelView(self.u, self.g, self.pid, opts))
    
    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            del panels[self.pid]
        await db_set(self.g.id, 'ticket_panels', panels)
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class PaginatedRoleSelectForPanel(View):
    """Sélecteur de rôle pour le panel de ticket avec pagination"""
    def __init__(self, u, g, pid, page=0):
        super().__init__(timeout=180)
        self.u = u
        self.g = g
        self.pid = pid
        self.page = page
        self.roles = [r for r in g.roles[1:] if not r.is_bot_managed()]
        # 23 rôles par page pour laisser place à "Aucun" sur la page 0
        self.per_page = 23
        self.max_page = max(0, (len(self.roles) - 1) // self.per_page)
        self._build()
    
    def _build(self):
        start = self.page * self.per_page
        end = start + self.per_page
        page_roles = self.roles[start:end]
        
        opts = []
        if self.page == 0:
            opts.append(discord.SelectOption(label="❌ Aucun (utiliser global)", value="0"))
        
        for r in page_roles:
            # Ajouter une description avec la couleur du rôle
            color_hex = f"#{r.color.value:06x}" if r.color.value else "Par défaut"
            opts.append(discord.SelectOption(
                label=f"@{r.name}"[:25], 
                value=str(r.id),
                description=f"Couleur: {color_hex}"[:50]
            ))
        
        if opts:
            self.add_item(PanelStaffRoleSelect(self, opts))
        
        # Boutons de pagination
        if self.page > 0:
            btn = discord.ui.Button(label="◀️ Page préc.", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.prev_page
            self.add_item(btn)
        
        if self.page < self.max_page:
            btn = discord.ui.Button(label="▶️ Page suiv.", style=discord.ButtonStyle.secondary, row=1)
            btn.callback = self.next_page
            self.add_item(btn)
        
        back_btn = discord.ui.Button(label="◀️ Retour", style=discord.ButtonStyle.danger, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)
    
    async def prev_page(self, i):
        v = PaginatedRoleSelectForPanel(self.u, self.g, self.pid, self.page - 1)
        embed = discord.Embed(
            title="👥 Rôle Staff du Panel", 
            description=f"Page {self.page}/{self.max_page + 1} - {len(self.roles)} rôles disponibles\n*Aucun = utilise le rôle staff global*",
            color=C.PURPLE
        )
        await i.response.edit_message(embed=embed, view=v)
    
    async def next_page(self, i):
        v = PaginatedRoleSelectForPanel(self.u, self.g, self.pid, self.page + 1)
        embed = discord.Embed(
            title="👥 Rôle Staff du Panel", 
            description=f"Page {self.page + 2}/{self.max_page + 1} - {len(self.roles)} rôles disponibles\n*Aucun = utilise le rôle staff global*",
            color=C.PURPLE
        )
        await i.response.edit_message(embed=embed, view=v)
    
    async def go_back(self, i):
        v = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class PanelStaffRoleSelect(Select):
    def __init__(self, parent, opts):
        placeholder = f"Page {parent.page + 1}/{parent.max_page + 1} - Choisir un rôle..."
        super().__init__(placeholder=placeholder, options=opts)
        self.parent = parent
    
    async def callback(self, i):
        c = await cfg(i.guild.id)
        panels = c.get('ticket_panels', {})
        if self.parent.pid in panels:
            panels[self.parent.pid]['staff_role'] = int(self.values[0])
            await db_set(i.guild.id, 'ticket_panels', panels)
        v = PanelEditView(self.parent.u, self.parent.g, self.parent.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class PanelCatView(View):
    def __init__(self, u, g, pid, opts):
        super().__init__(timeout=120)
        self.add_item(PanelCatSel(u, g, pid, opts))

class PanelCatSel(Select):
    def __init__(self, u, g, pid, opts):
        super().__init__(placeholder="Choisir une catégorie...", options=opts)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def callback(self, i):
        c = await cfg(i.guild.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['category'] = int(self.values[0])
            await db_set(i.guild.id, 'ticket_panels', panels)
        v = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SetMaxModal(Modal, title="🔢 Max tickets par utilisateur"):
    mx = TextInput(label="Nombre maximum", placeholder="1-10", default="1", max_length=2)
    
    def __init__(self, u, g, pid):
        super().__init__()
        self.u = u
        self.g = g
        self.pid = pid
    
    async def on_submit(self, i):
        v = max(1, min(10, int(self.mx.value) if self.mx.value.isdigit() else 1))
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['max'] = v
            await db_set(self.g.id, 'ticket_panels', panels)
        vw = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await vw.embed(), view=vw)

class PanelQsView(View):
    def __init__(self, u, g, pid):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def embed(self):
        c = await cfg(self.g.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        qs = pnl.get('questions', [])
        e = discord.Embed(title="📝 Questions du panel", color=C.PURPLE)
        if qs:
            for j, q in enumerate(qs, 1):
                e.add_field(name=f"{j}. {q['title']}", value=q['question'][:100], inline=False)
        else:
            e.description = "*Aucune question configurée*"
        e.set_footer(text="Maximum 5 questions")
        return e
    
    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        c = await cfg(self.g.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        if len(pnl.get('questions', [])) >= 5:
            return await i.response.send_message("❌ Maximum 5 questions", ephemeral=True)
        await i.response.send_modal(AddQModal(self.u, self.g, self.pid))
    
    @discord.ui.button(label="🗑️ Tout supprimer", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['questions'] = []
            await db_set(self.g.id, 'ticket_panels', panels)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddQModal(Modal, title="➕ Ajouter une question"):
    t = TextInput(label="Titre (affiché dans le formulaire)", placeholder="Ex: Pseudo en jeu", max_length=45)
    q = TextInput(label="Question complète", placeholder="Ex: Quel est votre pseudo sur le serveur?", style=discord.TextStyle.paragraph, max_length=100)
    
    def __init__(self, u, g, pid):
        super().__init__()
        self.u = u
        self.g = g
        self.pid = pid
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid].setdefault('questions', []).append({'title': self.t.value, 'question': self.q.value})
            await db_set(self.g.id, 'ticket_panels', panels)
        v = PanelQsView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SendPanelView(View):
    def __init__(self, u, g, pid, opts):
        super().__init__(timeout=120)
        self.add_item(SendPanelSel(u, g, pid, opts))

class SendPanelSel(Select):
    def __init__(self, u, g, pid, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def callback(self, i):
        ch = i.guild.get_channel(int(self.values[0]))
        if not ch:
            return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
        c = await cfg(i.guild.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        qs = pnl.get('questions', [])
        mx = pnl.get('max', 1)
        desc = "Cliquez sur le bouton ci-dessous pour créer un ticket."
        if qs:
            desc += f"\n\n📝 Vous devrez répondre à **{len(qs)}** question(s)."
        desc += f"\n🔢 Maximum **{mx}** ticket(s) simultané(s)."
        emb = discord.Embed(title=f"🎫 {pnl.get('name', 'Support')}", description=desc, color=C.BLURPLE)
        await ch.send(embed=emb, view=TicketCreateView(self.pid))
        await i.response.send_message(f"✅ Panel envoyé dans {ch.mention}!", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

async def update_realsy_activity(guild_id, user_id):
    """Met à jour la dernière activité d'un utilisateur avec le rôle Realsy"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT user_id FROM realsy_tracking WHERE guild_id=? AND user_id=?', 
                (guild_id, user_id)) as c:
                if await c.fetchone():
                    await db.execute('UPDATE realsy_tracking SET last_activity=?, warn_count=0 WHERE guild_id=? AND user_id=?',
                        (now().isoformat(), guild_id, user_id))
                    await db.commit()
    except:
        pass

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ GESTIONNAIRE D'ERREURS GLOBAL
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    """Gestionnaire d'erreur global pour les commandes slash - évite 'échec de l'interaction'"""
    try:
        # Log l'erreur
        print(f"[APP CMD ERROR] {interaction.command.name if interaction.command else 'Unknown'}: {error}")
        
        # Essayer de répondre
        error_msg = "❌ Une erreur est survenue. Réessayez."
        
        if isinstance(error, discord.app_commands.errors.MissingPermissions):
            error_msg = "❌ Vous n'avez pas les permissions nécessaires."
        elif isinstance(error, discord.app_commands.errors.CommandOnCooldown):
            error_msg = f"⏱️ Commande en cooldown. Réessayez dans {error.retry_after:.0f}s"
        elif isinstance(error, discord.app_commands.errors.MissingRole):
            error_msg = "❌ Vous n'avez pas le rôle requis."
        
        if not interaction.response.is_done():
            await interaction.response.send_message(error_msg, ephemeral=True)
        else:
            try:
                await interaction.followup.send(error_msg, ephemeral=True)
            except:
                pass
    except Exception as ex:
        print(f"[APP CMD ERROR HANDLER] {ex}")

@bot.event
async def on_ready():
    await db_init()
    bot.add_view(TicketControlView())
    bot.add_view(GiveawayParticipateView())  # Pour les boutons de participation aux giveaways
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM guild_config') as c:
                for row in await c.fetchall():
                    try:
                        data = json.loads(row[0]) if row[0] else {}
                        for pid in data.get('ticket_panels', {}):
                            bot.add_view(TicketCreateView(pid))
                    except: pass
    except: pass
    
    # Sync global des commandes
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées:")
        for cmd in synced:
            print(f"   - /{cmd.name}")
    except Exception as ex:
        print(f"❌ Erreur sync global: {ex}")
    
    # ═══════════════ INITIALISER LE TRACKING VOCAL ═══════════════
    # Tracker tous les membres déjà en vocal au démarrage
    vocal_count = 0
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot:
                    key = (guild.id, member.id)
                    voice_join_tracker[key] = now()
                    vocal_count += 1
    if vocal_count > 0:
        print(f"🎤 {vocal_count} membres en vocal trackés au démarrage")
    
    # Lancer la tâche d'inactivité
    if not check_realsy_inactivity.is_running():
        check_realsy_inactivity.start()
    
    # Lancer la tâche des feeds sociaux
    if not check_social_feeds.is_running():
        check_social_feeds.start()
    
    # Lancer la tâche de vérification AFK automatique
    if not check_afk_automatic.is_running():
        check_afk_automatic.start()
    
    # Lancer la tâche des giveaways
    if not check_giveaways.is_running():
        check_giveaways.start()
    
    # Lancer la tâche des messages automatiques
    if not check_scheduled_messages.is_running():
        check_scheduled_messages.start()
    
    # Lancer la tâche des rôles boutique expirés
    if not check_expired_roles.is_running():
        check_expired_roles.start()
    
    print(f"✅ {bot.user.name} v27 prêt!")
    print(f"🌐 Serveurs: {len(bot.guilds)}")
    print(f"📢 Vérification feeds sociaux toutes les 5 minutes")
    print(f"🎁 Vérification giveaways toutes les 30 secondes")
    print(f"📨 Vérification messages auto toutes les minutes")
    print(f"🛒 Vérification rôles boutique expirés toutes les minutes")
    print(f"🔊 Vocaux temporaires activés")
    print(f"⚔️ Système anti-raid activé")

# ═══════════════════════════════════════════════════════════════════════════════
#                           📨 ON_INTERACTION POUR MESSAGES AUTO
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_interaction(interaction: discord.Interaction):
    """Repositionne les messages d'aide après les interactions (commandes slash, boutons, etc.)"""
    # Ignorer si pas de channel ou pas de guild
    if not interaction.channel or not interaction.guild:
        return
    
    # Ignorer si c'est une interaction sans réponse visible (ephemeral check)
    # On ne peut pas toujours savoir si la réponse est ephemeral, donc on vérifie après un délai
    
    # Vérifier si ce salon a une aide automatique configurée
    try:
        c = await cfg(interaction.guild.id)
        auto_helps = c.get('auto_help_channels', {})
        channel_id_str = str(interaction.channel.id)
        
        if channel_id_str not in auto_helps:
            return
        
        help_data = auto_helps[channel_id_str]
        if not help_data.get('enabled', True):
            return
        
        # Attendre que la réponse de l'interaction soit envoyée
        await asyncio.sleep(1.5)
        
        # Vérifier si le dernier message n'est pas déjà notre message d'aide
        try:
            last_msg = [m async for m in interaction.channel.history(limit=1)]
            if last_msg:
                last_msg = last_msg[0]
                # Si c'est déjà notre message d'aide, ne rien faire
                if interaction.channel.id in auto_help_messages:
                    if last_msg.id == auto_help_messages[interaction.channel.id]:
                        return
                
                # Si le dernier message n'est pas de notre bot, repositionner
                if last_msg.author.id != bot.user.id or last_msg.id != auto_help_messages.get(interaction.channel.id, 0):
                    # Supprimer l'ancien message d'aide
                    if interaction.channel.id in auto_help_messages:
                        try:
                            old_msg = await interaction.channel.fetch_message(auto_help_messages[interaction.channel.id])
                            await old_msg.delete()
                        except:
                            pass
                        del auto_help_messages[interaction.channel.id]
                    
                    # Créer et envoyer le nouveau message d'aide
                    e = discord.Embed(title=f"💡 {help_data.get('title', 'Aide')}", color=help_data.get('color', 0x3498DB))
                    e.description = help_data.get('content', '')
                    e.set_footer(text="Ce message se repositionne automatiquement")
                    
                    new_msg = await interaction.channel.send(embed=e)
                    auto_help_messages[interaction.channel.id] = new_msg.id
        except:
            pass
    except Exception as ex:
        print(f"Erreur on_interaction auto_help: {ex}")

@bot.tree.command(name="sync", description="🔄 Synchroniser les commandes (Admin)")
async def sync_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin requis", ephemeral=True)
    
    await i.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        cmd_list = "\n".join([f"• `/{c.name}`" for c in synced])
        await i.followup.send(f"✅ **{len(synced)} commandes synchronisées!**\n\n{cmd_list}", ephemeral=True)
    except Exception as ex:
        await i.followup.send(f"❌ Erreur: {ex}", ephemeral=True)

@bot.event
async def on_member_ban(guild, user):
    """Sauvegarde les informations du membre banni pour détection de comptes secondaires"""
    try:
        # Récupérer le hash de l'avatar
        avatar_hash = str(user.avatar.key) if user.avatar else "default"
        
        # Essayer de récupérer la raison du ban
        reason = "Non spécifiée"
        try:
            ban_entry = await guild.fetch_ban(user)
            if ban_entry.reason:
                reason = ban_entry.reason
        except:
            pass
        
        # Sauvegarder les infos du ban
        await save_ban_info(guild.id, user.id, user.name, avatar_hash, reason)
        print(f"[BAN] Sauvegardé: {user.name} ({user.id}) sur {guild.name}")
        
    except Exception as ex:
        print(f"[BAN] Erreur sauvegarde: {ex}")

@bot.event
async def on_member_remove(m):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id, channel_id, claimed_by, answers FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (m.guild.id, m.id)) as c:
                tks = await c.fetchall()
        for tk in tks:
            ans = {}
            try: ans = json.loads(tk[3]) if tk[3] else {}
            except: pass
            ti = {'id': tk[0], 'user': m.id, 'claimed': tk[2] or 0, 'answers': ans}
            ch = m.guild.get_channel(tk[1])
            await send_ticket_log(m.guild, 'leave', m, ti)
            if ch:
                await ch.send(embed=discord.Embed(title="🚪 Utilisateur parti", description=f"**{m.display_name}** a quitté le serveur.", color=C.ORANGE))
    except: pass

@bot.event
async def on_member_join(m):
    try:
        c = await cfg(m.guild.id)
        guild_id = m.guild.id
        
        # ═══════════════ ANTI-RAID SYSTÈME ═══════════════
        if c.get('anti_raid'):
            raid_cfg = c.get('raid_config', {})
            join_threshold = raid_cfg.get('join_threshold', 10)
            join_interval = raid_cfg.get('join_interval', 10)
            min_account_age = raid_cfg.get('min_account_age', 7)
            auto_mode = raid_cfg.get('auto_mode', True)
            block_invites = raid_cfg.get('block_invites', True)
            action = raid_cfg.get('action', 'kick')
            
            # Initialiser le tracker si nécessaire
            if guild_id not in raid_tracker:
                raid_tracker[guild_id] = {'joins': [], 'lockdown': False}
            
            current_time = now()
            
            # Nettoyer les anciennes entrées (hors intervalle)
            cutoff = current_time - timedelta(seconds=join_interval)
            raid_tracker[guild_id]['joins'] = [
                (uid, ts) for uid, ts in raid_tracker[guild_id]['joins']
                if ts > cutoff
            ]
            
            # Ajouter cette arrivée
            raid_tracker[guild_id]['joins'].append((m.id, current_time))
            
            # Vérifier l'âge du compte
            account_age = (current_time - m.created_at.replace(tzinfo=timezone.utc)).days
            is_suspicious = account_age < min_account_age
            
            # Vérifier si c'est un raid (trop de joins récents)
            recent_joins = len(raid_tracker[guild_id]['joins'])
            is_raid = recent_joins >= join_threshold
            
            # Si raid détecté
            if is_raid and not raid_tracker[guild_id].get('lockdown', False):
                raid_tracker[guild_id]['lockdown'] = True
                
                # Envoyer alerte
                log_ch = m.guild.get_channel(c.get('log_anti_raid', 0))
                if log_ch:
                    e = discord.Embed(
                        title="🚨 RAID DÉTECTÉ !",
                        description=f"**{recent_joins} membres** ont rejoint en moins de **{join_interval} secondes**\n\n"
                                    f"⚡ **Action automatique:** {'Activée' if auto_mode else 'Désactivée'}\n"
                                    f"🔒 **Blocage invitations:** {'Activé' if block_invites else 'Désactivé'}",
                        color=0xFF0000
                    )
                    e.set_footer(text="Utilisez /configure > Protection > Anti-Raid pour gérer")
                    e.timestamp = current_time
                    await log_ch.send(content="@here" if auto_mode else "", embed=e)
            
            # Appliquer l'action si nécessaire
            should_act = (is_raid or is_suspicious) and (auto_mode or raid_tracker[guild_id].get('lockdown', False))
            
            if should_act:
                reason = f"Anti-Raid: {'Raid détecté' if is_raid else 'Compte suspect'} (âge: {account_age}j)"
                
                try:
                    if action == 'ban':
                        await m.ban(reason=reason)
                    elif action == 'kick':
                        await m.kick(reason=reason)
                    elif action == 'mute':
                        # Mute avec timeout
                        await m.timeout(timedelta(hours=24), reason=reason)
                    
                    # Log l'action
                    await send_log(m.guild, 'anti_raid', m, None, reason, f"Action: {action.upper()}")
                except:
                    pass
                
                return  # Ne pas continuer le traitement
        
        # ═══════════════ ANTI-NEWACCOUNT (standalone) ═══════════════
        if c.get('anti_newaccount'):
            days = c.get('newaccount_days', 7)
            age = (now() - m.created_at.replace(tzinfo=timezone.utc)).days
            if age < days:
                await send_log(m.guild, 'anti_newaccount', m, None, "Compte trop récent", f"Âge: {age} jour(s)")
                await m.kick(reason=f"Compte trop récent ({age} jours)")
                return  # Ne pas continuer
        
        # ═══════════════ ANTI-ALT (Comptes Secondaires) ═══════════════
        # Toujours sauvegarder le fingerprint du nouveau membre
        await save_user_fingerprint(m.guild.id, m)
        
        if c.get('anti_alt'):
            alt_cfg = c.get('alt_config', {})
            auto_action = alt_cfg.get('auto_action', False)
            min_confidence = alt_cfg.get('min_confidence', 70)
            action = c.get('alt_action', 'kick')
            
            # Détecter si c'est un compte secondaire
            is_alt, confidence, main_id, reasons = await detect_alt_account(m.guild, m)
            
            if is_alt and confidence >= min_confidence:
                # Envoyer le log
                main_member = m.guild.get_member(main_id)
                main_txt = f"{main_member.name} ({main_id})" if main_member else f"ID: {main_id} (banni/parti)"
                
                log_ch = m.guild.get_channel(c.get('log_anti_alt', 0))
                if log_ch:
                    e = discord.Embed(
                        title="👥 COMPTE SECONDAIRE DÉTECTÉ !",
                        description=f"**Compte secondaire:** {m.mention} (`{m.id}`)\n**Compte principal:** {main_txt}\n**Confiance:** {confidence}%",
                        color=0xE74C3C
                    )
                    e.add_field(name="📋 Raisons", value="\n".join([f"• {r}" for r in reasons[:5]]), inline=False)
                    e.add_field(name="⚡ Action auto", value="✅ Activée" if auto_action else "❌ Désactivée", inline=True)
                    e.set_thumbnail(url=m.display_avatar.url if m.display_avatar else None)
                    e.timestamp = now()
                    await log_ch.send(embed=e)
                
                # Appliquer l'action automatique si activée
                if auto_action:
                    reason = f"Compte secondaire détecté (confiance: {confidence}%, principal: {main_id})"
                    try:
                        if action == 'ban':
                            await m.ban(reason=reason)
                        elif action == 'kick':
                            await m.kick(reason=reason)
                        elif action == 'mute':
                            await m.timeout(timedelta(hours=24), reason=reason)
                        
                        await update_alt_status(m.guild.id, m.id, 'actioned', action)
                        await send_log(m.guild, 'anti_alt', m, None, "Compte secondaire", f"Confiance: {confidence}%, Action: {action.upper()}")
                    except Exception as ex:
                        print(f"[ALT] Erreur action: {ex}")
                    
                    return  # Ne pas continuer
                    
    except Exception as ex:
        print(f"Erreur on_member_join: {ex}")

async def relay_discord_message(msg):
    """Relay un message vers les serveurs qui suivent ce salon"""
    try:
        channel_id = str(msg.channel.id)
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, data FROM guild_config') as cursor:
                async for row in cursor:
                    guild_id, data_str = row
                    if guild_id == msg.guild.id:
                        continue
                    
                    try:
                        data = json.loads(data_str) if data_str else {}
                        feeds = data.get('ads_discord_feeds', [])
                        dest_channel_id = data.get('ads_discord_channel', 0)
                        
                        is_followed = any(f['channel_id'] == channel_id for f in feeds)
                        if not is_followed or not dest_channel_id:
                            continue
                        
                        dest_guild = bot.get_guild(guild_id)
                        if not dest_guild:
                            continue
                        dest_channel = dest_guild.get_channel(dest_channel_id)
                        if not dest_channel:
                            continue
                        
                        # ═══════════════ EMBED DISCORD RELAY PROFESSIONNEL ═══════════════
                        e = discord.Embed(color=0x5865F2)
                        
                        # Auteur avec le nom du serveur
                        e.set_author(
                            name=f"📡 DISCORD • {msg.guild.name}",
                            icon_url=msg.guild.icon.url if msg.guild.icon else "https://discord.com/assets/847541504914fd33810e70a0ea73177e.ico"
                        )
                        
                        # Thumbnail avec avatar de l'auteur
                        if msg.author.display_avatar:
                            e.set_thumbnail(url=msg.author.display_avatar.url)
                        
                        # Info du message
                        e.add_field(
                            name="👤 Auteur",
                            value=f"**{msg.author.display_name}**",
                            inline=True
                        )
                        e.add_field(
                            name="📍 Salon",
                            value=f"#{msg.channel.name}",
                            inline=True
                        )
                        
                        # Contenu du message
                        content = msg.content[:1500] if msg.content else ""
                        if content:
                            e.add_field(
                                name="💬 Message",
                                value=content,
                                inline=False
                            )
                        
                        # Images
                        if msg.attachments:
                            for att in msg.attachments[:1]:
                                if att.content_type and att.content_type.startswith('image'):
                                    e.set_image(url=att.url)
                                    break
                        
                        e.set_footer(
                            text=f"Discord • {msg.guild.name}",
                            icon_url="https://discord.com/assets/847541504914fd33810e70a0ea73177e.ico"
                        )
                        e.timestamp = msg.created_at
                        
                        await dest_channel.send(embed=e)
                        
                    except:
                        continue
    except:
        pass

@bot.event
async def on_message(msg):
    if not msg.guild:
        return
    
    # ═══════════════ MESSAGES D'AIDE AUTOMATIQUES ═══════════════
    # Doit être appelé AVANT le filtre bot pour repositionner après les messages de bots
    # Mais on ignore le propre message du bot (éviter boucle infinie)
    if msg.author.id != bot.user.id:
        asyncio.create_task(handle_auto_help(msg))
    
    # Ignorer les bots pour le reste du traitement
    if msg.author.bot:
        return
    
    # Relay Discord - Vérifier si ce salon est suivi par d'autres serveurs
    await relay_discord_message(msg)
    
    # Mise à jour activité Realsy
    await update_realsy_activity(msg.guild.id, msg.author.id)
    
    # ═══════════════ SALON DE RÉCUPÉRATION D'ACTIVITÉ ═══════════════
    try:
        c = await cfg(msg.guild.id)
        stat_cfg = c.get('stat_config', {})
        recovery_ch_id = stat_cfg.get('recovery_channel', 0)
        
        # Si le message est dans le salon de récupération
        if recovery_ch_id and msg.channel.id == recovery_ch_id:
            await handle_recovery_message(msg, stat_cfg)
            return  # Ne pas traiter le reste
    except:
        pass
    
    # ═══════════════ TRACKING ACTIVITÉ MEMBRE ═══════════════
    await track_member_message(msg)
    
    try:
        c = await cfg(msg.guild.id)
        ct = msg.content or ""
        chid = msg.channel.id
        gt = get_gif_type(msg)
        ag = c.get('image_allowed', [])
        iag = gt and gt in ag
        
        # ═══════════════ VÉRIFICATIONS D'IMMUNITÉ ═══════════════
        
        # 1. Salon immunisé = ignorer TOUTE l'automodération
        if await is_channel_immune(msg.guild.id, chid):
            # SAUF anti-phishing qui reste actif partout
            if c.get('anti_phishing'):
                f, d = check_phishing(ct)
                if f:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_phishing', msg.author, msg, "Lien de phishing détecté", f"`{d}`")
                    await sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing", msg.guild)
            return
        
        # 2. Vérifier si c'est un ticket (immunité partielle)
        is_ticket = await is_ticket_channel(msg.channel)
        
        # 3. Vérifier immunité de l'utilisateur
        user_immune = await is_immune(msg.author, 'general', msg.channel)
        
        # ═══════════════ PROTECTIONS CRITIQUES (JAMAIS IGNORÉES) ═══════════════
        
        # Anti-phishing - TOUJOURS ACTIF pour TOUT LE MONDE
        if c.get('anti_phishing'):
            f, d = check_phishing(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_phishing', msg.author, msg, "Lien de phishing détecté", f"`{d}`")
                await sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing", msg.guild)
                return
        
        # Anti-scam - Actif même dans les tickets (protection contre les hacks)
        if c.get('anti_scam'):
            f, p = check_scam(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_scam', msg.author, msg, "Message de scam détecté", f"`{p}`")
                await sanction(msg.author, c.get('scam_action', 'mute'), 60, "Scam", msg.guild)
                return
        
        # Si utilisateur immunisé OU dans un ticket = ignorer les autres protections
        if user_immune or is_ticket:
            return  # Accès total (liens, images, etc.)
        
        # ═══════════════ PROTECTIONS STANDARD (IGNORÉES SI IMMUNISÉ) ═══════════════
        
        # Config salon spécifique
        chcf = c.get('channel_configs', {}).get(str(chid))
        if chcf and not (iag and chcf.get('gifs', True)):
            vio, _ = check_channel_cfg(msg, chcf)
            if vio:
                await msg.delete()
                return
        
        # Anti-badwords
        if c.get('anti_badwords'):
            f, w = check_badwords(ct, c.get('badwords_list', []))
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_badwords', msg.author, msg, "Mot interdit détecté", f"`{w}`")
                return
        
        # Anti-invite
        if c.get('anti_invite'):
            f, inv = check_invite(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_invite', msg.author, msg, "Invitation Discord", f"`{inv}`")
                return
        
        # Anti-link
        if c.get('anti_link') and not iag:
            if chid not in c.get('link_allowed_channels', []):
                f, url = check_link(ct, c.get('link_whitelist', []))
                if f:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_link', msg.author, msg, "Lien non autorisé", f"`{url}`")
                    return
        
        # Anti-image
        if c.get('anti_image') and not iag:
            if chid not in c.get('image_allowed_channels', []):
                bl = check_image(msg, c.get('image_allowed', []))
                if bl:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_image', msg.author, msg, "Format non autorisé", f"`{', '.join(bl)}`")
                    return
        
        # Anti-spam
        if c.get('anti_spam'):
            if await check_spam(msg, c.get('spam_max', 5), c.get('spam_interval', 5)):
                await msg.delete()
                await send_log(msg.guild, 'anti_spam', msg.author, msg, "Spam détecté", None)
                await sanction(msg.author, c.get('spam_action', 'mute'), 10, "Spam", msg.guild)
                return
        
        # Anti-caps
        if c.get('anti_caps'):
            if check_caps(ct, c.get('caps_percent', 70)):
                await msg.delete()
                await send_log(msg.guild, 'anti_caps', msg.author, msg, "Trop de majuscules", None)
                return
        
        # Anti-QRCode (détection de scams par QR code) - Actif pour tous
        if c.get('anti_qrcode'):
            is_qr_scam, qr_pattern = check_qr_code_scam(ct)
            if is_qr_scam:
                await msg.delete()
                await send_log(msg.guild, 'anti_qrcode', msg.author, msg, 
                              "Scam QR Code détecté", f"Pattern: {qr_pattern}")
                await sanction(msg.author, c.get('qrcode_action', 'mute'), 30, "Scam QR Code", msg.guild)
                return
        
        # Fichiers dangereux - Actif pour tous
        if msg.attachments:
            for att in msg.attachments:
                is_dangerous, ext = check_dangerous_file(att.filename)
                if is_dangerous:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_phishing', msg.author, msg, 
                                  "Fichier dangereux détecté", f"Extension: {ext}")
                    await msg.channel.send(
                        f"⚠️ {msg.author.mention} a envoyé un fichier potentiellement dangereux (`{ext}`). Le fichier a été supprimé.",
                        delete_after=10
                    )
                    return
        
    except: pass

# ═══════════════════════════════════════════════════════════════════════════════
#                              📋 COMMANDES SLASH
# ═══════════════════════════════════════════════════════════════════════════════

async def security_check(i: discord.Interaction, command_name: str = "command"):
    """Vérifie la sécurité avant d'exécuter une commande"""
    user_id = i.user.id
    guild_id = i.guild.id if i.guild else 0
    
    # Vérifier blacklist temporaire
    is_blocked, reason = is_blacklisted(user_id)
    if is_blocked:
        return False, f"⛔ Vous êtes temporairement bloqué: {reason}"
    
    # Vérifier rate limit
    if not check_rate_limit(guild_id, user_id, 'command'):
        # Blacklister temporairement si abuse répété
        if user_id in security_attempts:
            security_attempts[user_id]['attempts'] += 1
            if security_attempts[user_id]['attempts'] >= 5:
                blacklist_user(user_id, 10, "Spam de commandes")
                await log_security_event(guild_id, user_id, "RATE_LIMIT_BAN", f"Commande: {command_name}")
        else:
            security_attempts[user_id] = {'attempts': 1, 'last': now()}
        return False, "⚠️ Trop de commandes ! Attendez un moment."
    
    return True, None

@bot.tree.command(name="configure", description="⚙️ Ouvrir le panneau de configuration")
async def configure_cmd(i: discord.Interaction):
    # Vérification de sécurité
    ok, msg = await security_check(i, "configure")
    if not ok:
        return await i.response.send_message(msg, ephemeral=True)
    
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Vous devez être administrateur", ephemeral=True)
    
    # Log l'accès à la configuration
    await log_security_event(i.guild.id, i.user.id, "CONFIG_ACCESS", "Ouverture du panneau de configuration")
    
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.embed(), view=v, ephemeral=True)

async def check_mod_perm(i, cmd_key):
    """Vérifie si l'utilisateur a la permission pour cette commande de modération"""
    c = await cfg(i.guild.id)
    role_id = c.get(cmd_key, 0)
    
    # Admins et owner ont toujours accès
    if i.user.guild_permissions.administrator or i.user.id == i.guild.owner_id:
        return True
    
    # ⚠️ Les immunisés ont accès à TOUTES les commandes de modération
    if await is_fully_immune(i.user):
        return True
    
    # Vérifier si l'utilisateur a le rôle configuré
    if role_id:
        role = i.guild.get_role(role_id)
        if role and role in i.user.roles:
            return True
    
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#                              ⚠️ WARN / UNWARN
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not await check_mod_perm(i, 'mod_warn_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if membre.id == i.user.id:
        return await i.response.send_message("❌ Vous ne pouvez pas vous warn vous-même", ephemeral=True)
    
    if membre.bot:
        return await i.response.send_message("❌ Vous ne pouvez pas warn un bot", ephemeral=True)
    
    if membre.top_role >= i.user.top_role and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Vous ne pouvez pas warn ce membre", ephemeral=True)
    
    # Enregistrer l'infraction
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, duration) VALUES(?,?,?,?,?,?)',
            (i.guild.id, membre.id, i.user.id, 'warn', raison, '')
        )
        await db.commit()
        # Compter les warns
        async with db.execute('SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type="warn"', (i.guild.id, membre.id)) as c:
            warn_count = (await c.fetchone())[0]
    
    # Créer l'embed
    e = discord.Embed(title="⚠️ Avertissement", color=C.YELLOW, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="📊 Total warns", value=str(warn_count), inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'warn', i.user, membre, raison, extra=f"Total warns: {warn_count}")

@bot.tree.command(name="unwarn", description="✅ Supprimer un avertissement d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez supprimer un warn")
async def unwarn_cmd(i: discord.Interaction, membre: discord.Member):
    if not await check_mod_perm(i, 'mod_warn_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    # Récupérer les warns (sans created_at pour éviter l'erreur)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, reason FROM infractions WHERE guild_id=? AND user_id=? AND type="warn" ORDER BY id DESC LIMIT 25',
            (i.guild.id, membre.id)
        ) as c:
            warns = await c.fetchall()
    
    if not warns:
        return await i.response.send_message(f"❌ {membre.mention} n'a aucun warn", ephemeral=True)
    
    # Créer les options
    opts = []
    for warn_id, reason in warns:
        label = f"#{warn_id} - {reason[:50]}{'...' if len(reason) > 50 else ''}"
        opts.append(discord.SelectOption(label=label[:100], value=str(warn_id)))
    
    e = discord.Embed(
        title=f"✅ Supprimer un warn de {membre.display_name}",
        description=f"Sélectionnez le warn à supprimer ({len(warns)} warn(s))",
        color=C.GREEN
    )
    e.set_thumbnail(url=membre.display_avatar.url)
    
    v = UnwarnSelectView(membre, opts)
    await i.response.send_message(embed=e, view=v, ephemeral=True)

class UnwarnSelectView(View):
    def __init__(self, membre, opts):
        super().__init__(timeout=120)
        self.add_item(UnwarnSelect(membre, opts))

class UnwarnSelect(Select):
    def __init__(self, membre, opts):
        super().__init__(placeholder="Sélectionner le warn à supprimer...", options=opts)
        self.membre = membre
    
    async def callback(self, i):
        warn_id = int(self.values[0])
        
        # Récupérer info du warn avant suppression
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT reason FROM infractions WHERE id=?', (warn_id,)) as c:
                row = await c.fetchone()
                reason = row[0] if row else "?"
            
            # Supprimer
            await db.execute('DELETE FROM infractions WHERE id=?', (warn_id,))
            await db.commit()
            
            # Compter les warns restants
            async with db.execute('SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type="warn"', (i.guild.id, self.membre.id)) as c:
                warn_count = (await c.fetchone())[0]
        
        e = discord.Embed(title="✅ Warn supprimé", color=C.GREEN, timestamp=now())
        e.add_field(name="👤 Membre", value=f"{self.membre.mention}", inline=True)
        e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
        e.add_field(name="📊 Warns restants", value=str(warn_count), inline=True)
        e.add_field(name="📝 Warn supprimé", value=reason[:1024], inline=False)
        
        await i.response.edit_message(embed=e, view=None)
        
        # Log
        await send_mod_log(i.guild, 'unwarn', i.user, self.membre, reason, extra=f"Warns restants: {warn_count}")

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔇 MUTE / UNMUTE
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="mute", description="🔇 Timeout un membre")
@app_commands.describe(membre="Le membre à mute", duree="La durée (nombre)", unite="L'unité de temps", raison="La raison du mute")
@app_commands.choices(unite=[
    app_commands.Choice(name="Minutes", value="minutes"),
    app_commands.Choice(name="Heures", value="heures"),
    app_commands.Choice(name="Jours", value="jours"),
    app_commands.Choice(name="Semaine (max)", value="semaine")
])
async def mute_cmd(i: discord.Interaction, membre: discord.Member, duree: int, unite: str, raison: str):
    if not await check_mod_perm(i, 'mod_mute_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if membre.id == i.user.id:
        return await i.response.send_message("❌ Vous ne pouvez pas vous mute vous-même", ephemeral=True)
    
    if membre.bot:
        return await i.response.send_message("❌ Vous ne pouvez pas mute un bot", ephemeral=True)
    
    if membre.top_role >= i.user.top_role and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Vous ne pouvez pas mute ce membre", ephemeral=True)
    
    # Calculer la durée
    duree = max(1, duree)
    if unite == "minutes":
        delta = timedelta(minutes=duree)
        dur_txt = f"{duree} minute(s)"
    elif unite == "heures":
        delta = timedelta(hours=duree)
        dur_txt = f"{duree} heure(s)"
    elif unite == "jours":
        duree = min(duree, 7)
        delta = timedelta(days=duree)
        dur_txt = f"{duree} jour(s)"
    else:
        delta = timedelta(weeks=1)
        dur_txt = "1 semaine"
    
    if delta > timedelta(days=7):
        delta = timedelta(days=7)
        dur_txt = "7 jours (maximum)"
    
    # Appliquer le timeout
    try:
        await membre.timeout(delta, reason=f"{raison} - Par {i.user.name}")
    except discord.Forbidden:
        return await i.response.send_message("❌ Je ne peux pas mute ce membre (permissions)", ephemeral=True)
    except Exception as ex:
        return await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    # Enregistrer l'infraction
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, duration) VALUES(?,?,?,?,?,?)',
            (i.guild.id, membre.id, i.user.id, 'mute', raison, dur_txt)
        )
        await db.commit()
    
    # Créer l'embed
    e = discord.Embed(title="🔇 Membre mute", color=C.ORANGE, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="⏱️ Durée", value=dur_txt, inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'mute', i.user, membre, raison, duration=dur_txt)

@bot.tree.command(name="unmute", description="🔊 Retirer le mute d'un membre")
@app_commands.describe(membre="Le membre à unmute", raison="La raison du unmute (optionnel)")
async def unmute_cmd(i: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    if not await check_mod_perm(i, 'mod_mute_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if not membre.is_timed_out():
        return await i.response.send_message(f"❌ {membre.mention} n'est pas mute", ephemeral=True)
    
    try:
        await membre.timeout(None, reason=f"Unmute par {i.user.name}: {raison}")
    except discord.Forbidden:
        return await i.response.send_message("❌ Je ne peux pas unmute ce membre", ephemeral=True)
    except Exception as ex:
        return await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    e = discord.Embed(title="🔊 Membre unmute", color=C.GREEN, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'unmute', i.user, membre, raison)

# ═══════════════════════════════════════════════════════════════════════════════
#                              📋 INFRACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="infractions", description="📋 Voir les infractions d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez voir les infractions")
async def infractions_cmd(i: discord.Interaction, membre: discord.Member):
    if not await check_mod_perm(i, 'mod_infractions_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    # Récupérer les infractions (sans ORDER BY created_at pour éviter erreur si colonne n'existe pas)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT type, reason, duration, mod_id FROM infractions WHERE guild_id=? AND user_id=? ORDER BY id DESC',
            (i.guild.id, membre.id)
        ) as c:
            rows = await c.fetchall()
    
    # Calculer le temps sur le serveur
    joined = membre.joined_at
    if joined:
        days_on_server = (now() - joined.replace(tzinfo=timezone.utc)).days
        time_on_server = f"{days_on_server} jour(s)"
    else:
        time_on_server = "Inconnu"
    
    # Compter les types
    warns = sum(1 for r in rows if r[0] == 'warn')
    mutes = sum(1 for r in rows if r[0] == 'mute')
    
    # Créer l'embed
    e = discord.Embed(title=f"📋 Infractions de {membre.display_name}", color=C.BLUE, timestamp=now())
    e.set_thumbnail(url=membre.display_avatar.url)
    
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="📅 Sur le serveur", value=time_on_server, inline=True)
    e.add_field(name="📊 Total", value=str(len(rows)), inline=True)
    
    e.add_field(name="⚠️ Warns", value=str(warns), inline=True)
    e.add_field(name="🔇 Mutes", value=str(mutes), inline=True)
    
    # Statut mute actuel
    if membre.is_timed_out():
        timeout_until = membre.timed_out_until
        if timeout_until:
            e.add_field(name="🔇 Mute actif", value=f"Jusqu'à <t:{int(timeout_until.timestamp())}:R>", inline=True)
        else:
            e.add_field(name="\u200b", value="\u200b", inline=True)
    else:
        e.add_field(name="\u200b", value="\u200b", inline=True)
    
    if rows:
        inf_lines = []
        for j, (typ, reason, duration, mod_id) in enumerate(rows[:10], 1):
            emoji = "⚠️" if typ == "warn" else "🔇"
            dur_txt = f" ({duration})" if duration else ""
            reason_short = reason[:40] + "..." if len(reason) > 40 else reason
            inf_lines.append(f"`{j}.` {emoji} **{typ.upper()}**{dur_txt}\n└ {reason_short}")
        
        e.add_field(name="📜 Historique (10 dernières)", value="\n".join(inf_lines)[:1024], inline=False)
    else:
        e.add_field(name="📜 Historique", value="✅ Aucune infraction", inline=False)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'infractions', i.user, membre, extra=f"Total: {len(rows)} infractions")

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎭 RELLSEAS COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="rellseas", description="🎭 Donner ou retirer le rôle Realsy à un membre")
@app_commands.describe(membre="Le membre", action="Donner ou retirer le rôle")
@app_commands.choices(action=[
    app_commands.Choice(name="Donner le rôle", value="add"),
    app_commands.Choice(name="Retirer le rôle", value="remove")
])
async def rellseas_cmd(i: discord.Interaction, membre: discord.Member, action: str):
    c = await cfg(i.guild.id)
    
    # Vérifier si l'utilisateur est autorisé
    if i.user.id != c.get('rellseas_user', 0) and not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Vous n'êtes pas autorisé à utiliser cette commande", ephemeral=True)
    
    # Vérifier si le rôle est configuré
    role = i.guild.get_role(c.get('rellseas_role', 0))
    if not role:
        return await i.response.send_message("❌ Le rôle Realsy n'est pas configuré", ephemeral=True)
    
    if action == "add":
        if role in membre.roles:
            return await i.response.send_message(f"❌ {membre.mention} a déjà le rôle {role.mention}", ephemeral=True)
        
        try:
            await membre.add_roles(role, reason=f"RellSeas par {i.user.name}")
            
            # Enregistrer l'activité initiale
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''INSERT OR REPLACE INTO realsy_tracking 
                    (guild_id, user_id, last_activity, warn_count) VALUES (?, ?, ?, 0)''',
                    (i.guild.id, membre.id, now().isoformat()))
                await db.commit()
            
            e = discord.Embed(title="🎭 Rôle Realsy donné", color=C.GREEN, timestamp=now())
            e.add_field(name="👤 Membre", value=f"{membre.mention}", inline=True)
            e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
            e.set_thumbnail(url=membre.display_avatar.url)
            await i.response.send_message(embed=e)
            
            # Log
            log_ch = i.guild.get_channel(c.get('rellseas_log_channel', 0))
            if log_ch:
                await log_ch.send(embed=e)
                
        except discord.Forbidden:
            return await i.response.send_message("❌ Je ne peux pas donner ce rôle", ephemeral=True)
    
    else:  # remove
        if role not in membre.roles:
            return await i.response.send_message(f"❌ {membre.mention} n'a pas le rôle {role.mention}", ephemeral=True)
        
        try:
            await membre.remove_roles(role, reason=f"RellSeas retiré par {i.user.name}")
            
            # Supprimer du tracking
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                    (i.guild.id, membre.id))
                await db.commit()
            
            e = discord.Embed(title="🎭 Rôle Realsy retiré", color=C.RED, timestamp=now())
            e.add_field(name="👤 Membre", value=f"{membre.mention}", inline=True)
            e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
            e.set_thumbnail(url=membre.display_avatar.url)
            await i.response.send_message(embed=e)
            
            # Log
            log_ch = i.guild.get_channel(c.get('rellseas_log_channel', 0))
            if log_ch:
                await log_ch.send(embed=e)
                
        except discord.Forbidden:
            return await i.response.send_message("❌ Je ne peux pas retirer ce rôle", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💡 SUGGESTION COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

suggestion_cooldowns = {}

@bot.tree.command(name="suggestion", description="💡 Proposer une suggestion")
@app_commands.describe(titre="Titre de votre suggestion", proposition="Décrivez votre suggestion en détail")
async def suggestion_cmd(i: discord.Interaction, titre: str, proposition: str):
    c = await cfg(i.guild.id)
    
    # Vérifier les salons autorisés pour la commande
    allowed_channels = c.get('suggestion_allowed_channels', [])
    if allowed_channels and i.channel.id not in allowed_channels:
        mentions = []
        for ch_id in allowed_channels[:3]:
            ch = i.guild.get_channel(ch_id)
            if ch:
                mentions.append(ch.mention)
        msg = f"❌ Cette commande n'est utilisable que dans: {', '.join(mentions)}"
        if len(allowed_channels) > 3:
            msg += f" +{len(allowed_channels) - 3} autres"
        return await i.response.send_message(msg, ephemeral=True)
    
    # ⚠️ Les immunisés bypass les restrictions de rôle et cooldown
    is_immune = await is_fully_immune(i.user)
    
    # Vérifier le rôle (sauf immunisés)
    if not is_immune:
        role_id = c.get('suggestion_role', 0)
        if role_id:
            role = i.guild.get_role(role_id)
            if role and role not in i.user.roles:
                return await i.response.send_message(f"❌ Vous devez avoir le rôle {role.mention}", ephemeral=True)
    
    # Vérifier le salon de publication
    sugg_ch = i.guild.get_channel(c.get('suggestion_channel', 0))
    if not sugg_ch:
        return await i.response.send_message("❌ Le salon des suggestions n'est pas configuré", ephemeral=True)
    
    # Vérifier le cooldown (sauf immunisés)
    if not is_immune:
        cooldown_key = (i.guild.id, i.user.id)
        cd_duration = c.get('suggestion_cooldown', 1)
        cd_unit = c.get('suggestion_cooldown_unit', 'jours')
        
        if cd_unit == 'semaines':
            cd_seconds = cd_duration * 7 * 24 * 3600
        else:
            cd_seconds = cd_duration * 24 * 3600
        
        if cooldown_key in suggestion_cooldowns:
            last_time = suggestion_cooldowns[cooldown_key]
            elapsed = (now() - last_time).total_seconds()
            if elapsed < cd_seconds:
                remaining = cd_seconds - elapsed
                days = int(remaining // 86400)
                hours = int((remaining % 86400) // 3600)
                return await i.response.send_message(
                    f"⏱️ Attendez encore **{days}j {hours}h**",
                    ephemeral=True
                )
    
    # Sécurité: Sanitiser les entrées
    titre = Security.sanitize_input(titre, 100)
    proposition = Security.sanitize_input(proposition, 1000)
    
    # Créer un bel embed de suggestion
    e = discord.Embed(color=C.BLURPLE, timestamp=now())
    e.set_author(name="💡 Nouvelle Suggestion", icon_url=i.guild.icon.url if i.guild.icon else None)
    
    e.add_field(name="📋 Titre", value=f"```{titre[:100]}```", inline=False)
    e.add_field(name="📝 Proposition", value=proposition[:1000], inline=False)
    
    e.add_field(name="👤 Auteur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="🆔 ID", value=f"`{i.user.id}`", inline=True)
    e.add_field(name="📅 Date", value=f"<t:{int(now().timestamp())}:R>", inline=True)
    
    e.set_thumbnail(url=i.user.display_avatar.url)
    e.set_footer(text="Votez ci-dessous! ✅ Pour | 🟠 Neutre | ❌ Contre")
    
    # Envoyer
    msg = await sugg_ch.send(embed=e)
    
    # Ajouter les réactions
    await msg.add_reaction("✅")
    await msg.add_reaction("🟠")
    await msg.add_reaction("❌")
    
    # Enregistrer le cooldown (sauf immunisés)
    if not is_immune:
        cooldown_key = (i.guild.id, i.user.id)
        suggestion_cooldowns[cooldown_key] = now()
    
    # Stocker pour le tracking
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO suggestions (guild_id, message_id, user_id, title) VALUES (?, ?, ?, ?)',
            (i.guild.id, msg.id, i.user.id, titre))
        await db.commit()
    
    # Confirmation
    confirm = discord.Embed(title="✅ Suggestion envoyée!", color=C.GREEN)
    confirm.description = f"Votre suggestion a été publiée dans {sugg_ch.mention}"
    confirm.add_field(name="📋 Titre", value=titre[:100], inline=False)
    await i.response.send_message(embed=confirm, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔄 TRADE COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

trade_cooldowns = {}

@bot.tree.command(name="trade", description="🔄 Créer une annonce d'échange")
async def trade_cmd(i: discord.Interaction):
    c = await cfg(i.guild.id)
    
    # Vérifier les salons autorisés pour la commande
    allowed_channels = c.get('trade_allowed_channels', [])
    if not allowed_channels:
        return await i.response.send_message("❌ Aucun salon n'est configuré pour les trades. Demandez à un admin de configurer `/configure` → Commandes → Trade", ephemeral=True)
    
    if i.channel.id not in allowed_channels:
        mentions = []
        for ch_id in allowed_channels[:3]:
            ch = i.guild.get_channel(ch_id)
            if ch:
                mentions.append(ch.mention)
        msg = f"❌ Cette commande n'est utilisable que dans: {', '.join(mentions)}"
        if len(allowed_channels) > 3:
            msg += f" +{len(allowed_channels) - 3} autres"
        return await i.response.send_message(msg, ephemeral=True)
    
    # ⚠️ Les immunisés bypass les restrictions de rôle et cooldown
    is_immune = await is_fully_immune(i.user)
    
    # Vérifier le rôle (sauf immunisés)
    if not is_immune:
        role_id = c.get('trade_role', 0)
        if role_id:
            role = i.guild.get_role(role_id)
            if role and role not in i.user.roles:
                return await i.response.send_message(f"❌ Vous devez avoir le rôle {role.mention}", ephemeral=True)
    
    # Le trade sera publié dans le même salon où la commande est utilisée
    trade_ch = i.channel
    
    # Vérifier le cooldown (sauf immunisés)
    if not is_immune:
        cooldown_key = (i.guild.id, i.user.id)
        cd_duration = c.get('trade_cooldown', 1)
        cd_unit = c.get('trade_cooldown_unit', 'heures')
        
        if cd_unit == 'secondes':
            cd_seconds = cd_duration
        elif cd_unit == 'minutes':
            cd_seconds = cd_duration * 60
        elif cd_unit == 'heures':
            cd_seconds = cd_duration * 3600
        elif cd_unit == 'jours':
            cd_seconds = cd_duration * 86400
        elif cd_unit == 'semaines':
            cd_seconds = cd_duration * 604800
        else:
            cd_seconds = cd_duration * 3600
        
        if cooldown_key in trade_cooldowns:
            last_time = trade_cooldowns[cooldown_key]
            elapsed = (now() - last_time).total_seconds()
            if elapsed < cd_seconds:
                remaining = cd_seconds - elapsed
                if remaining >= 86400:
                    time_txt = f"{int(remaining // 86400)}j {int((remaining % 86400) // 3600)}h"
                elif remaining >= 3600:
                    time_txt = f"{int(remaining // 3600)}h {int((remaining % 3600) // 60)}min"
                elif remaining >= 60:
                    time_txt = f"{int(remaining // 60)}min {int(remaining % 60)}s"
                else:
                    time_txt = f"{int(remaining)}s"
                return await i.response.send_message(f"⏱️ Attendez encore **{time_txt}**", ephemeral=True)
    
    # Afficher le menu de création
    v = TradeBuilderView(i.user, i.guild, i.channel, trade_ch, is_immune)
    e = v.get_embed()
    await i.response.send_message(embed=e, view=v, ephemeral=True)

class TradeBuilderView(View):
    def __init__(self, user, guild, channel, trade_ch, is_immune=False):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.channel = channel
        self.trade_ch = trade_ch
        self.is_immune = is_immune  # Pour éviter le cooldown à l'envoi
        self.trade_ch = trade_ch
        self.jeu = ""
        self.je_donne = []
        self.je_veux = []
        self.texte_donne = ""
        self.texte_veux = ""
        
        # Ajouter les selects d'emojis si le serveur en a
        emojis = list(guild.emojis)[:25]
        if emojis:
            self.add_item(TradeEmojiGiveSelect(self, emojis))
            self.add_item(TradeEmojiWantSelect(self, emojis))
    
    def get_embed(self):
        e = discord.Embed(title="🔄 Créer un Trade", color=C.PURPLE)
        
        # Construire l'affichage
        donne_display = " ".join(self.je_donne) + (" " + self.texte_donne if self.texte_donne else "")
        veux_display = " ".join(self.je_veux) + (" " + self.texte_veux if self.texte_veux else "")
        
        e.add_field(name="🎮 Jeu", value=self.jeu if self.jeu else "*Non défini*", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        
        e.add_field(name="📤 Je DONNE", value=donne_display.strip() if donne_display.strip() else "*Rien sélectionné*", inline=True)
        e.add_field(name="➡️", value="🔄", inline=True)
        e.add_field(name="📥 Je VEUX", value=veux_display.strip() if veux_display.strip() else "*Rien sélectionné*", inline=True)
        
        # Instructions
        if self.jeu and (donne_display.strip() or veux_display.strip()):
            e.set_footer(text="✅ Cliquez sur Confirmer pour continuer")
            e.color = C.GREEN
        else:
            e.set_footer(text="1️⃣ Définissez le jeu • 2️⃣ Sélectionnez/écrivez vos items • 3️⃣ Confirmez")
        
        return e
    
    @discord.ui.button(label="🎮 Définir le Jeu", style=discord.ButtonStyle.primary, row=2)
    async def set_game(self, i, b):
        await i.response.send_modal(TradeGameModal(self))
    
    @discord.ui.button(label="✏️ Texte Donne", style=discord.ButtonStyle.secondary, row=2)
    async def set_text_give(self, i, b):
        await i.response.send_modal(TradeTextGiveModal(self))
    
    @discord.ui.button(label="✏️ Texte Veux", style=discord.ButtonStyle.secondary, row=2)
    async def set_text_want(self, i, b):
        await i.response.send_modal(TradeTextWantModal(self))
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.success, row=3)
    async def confirm(self, i, b):
        donne_display = " ".join(self.je_donne) + (" " + self.texte_donne if self.texte_donne else "")
        veux_display = " ".join(self.je_veux) + (" " + self.texte_veux if self.texte_veux else "")
        
        if not self.jeu:
            return await i.response.send_message("❌ Définissez le jeu d'abord!", ephemeral=True)
        if not donne_display.strip() and not veux_display.strip():
            return await i.response.send_message("❌ Ajoutez au moins un item!", ephemeral=True)
        
        # Demander la preuve
        e = discord.Embed(title="📸 Preuve requise", color=C.ORANGE)
        e.description = "**Envoyez une image** de preuve dans les **3 minutes**."
        await i.response.edit_message(embed=e, view=None)
        
        # Attendre l'image
        def check(m):
            return m.author.id == self.user.id and m.channel.id == self.channel.id and m.attachments
        
        try:
            msg = await bot.wait_for('message', timeout=180.0, check=check)
            
            attachment = msg.attachments[0]
            image_data = await attachment.read()
            image_filename = attachment.filename
            
            try:
                await msg.delete()
            except:
                pass
            
        except asyncio.TimeoutError:
            return await i.followup.send("❌ Temps écoulé!", ephemeral=True)
        
        # Créer le post professionnel
        e = discord.Embed(color=C.GOLD)
        e.set_author(name=f"🔄 TRADE • {self.jeu.upper()}", icon_url=self.user.display_avatar.url)
        
        # Affichage horizontal bien propre
        e.add_field(
            name="📤 DONNE",
            value=donne_display.strip() if donne_display.strip() else "—",
            inline=True
        )
        e.add_field(
            name="⚡",
            value="🔄",
            inline=True
        )
        e.add_field(
            name="📥 VEUT",
            value=veux_display.strip() if veux_display.strip() else "—",
            inline=True
        )
        
        # Infos trader compactes
        e.add_field(
            name="",
            value=f"👤 {self.user.mention} • `{self.user.id}` • <t:{int(now().timestamp())}:R>",
            inline=False
        )
        
        # Image en petit (thumbnail en haut à droite)
        image_file = discord.File(io.BytesIO(image_data), filename=image_filename)
        e.set_thumbnail(url=f"attachment://{image_filename}")
        
        e.set_footer(text="✅ Intéressé? Réagissez! • 💬 MP pour négocier")
        
        # Envoyer
        trade_msg = await self.trade_ch.send(embed=e, file=image_file)
        await trade_msg.add_reaction("✅")
        await trade_msg.add_reaction("💬")
        
        trade_cooldowns[(self.guild.id, self.user.id)] = now()
        
        confirm = discord.Embed(title="✅ Trade publié!", color=C.GREEN)
        confirm.description = f"Votre offre a été publiée dans {self.trade_ch.mention}"
        await i.followup.send(embed=confirm, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger, row=3)
    async def cancel(self, i, b):
        await i.response.edit_message(embed=discord.Embed(title="❌ Trade annulé", color=C.RED), view=None)

class TradeEmojiGiveSelect(Select):
    def __init__(self, parent, emojis):
        self.parent = parent
        self.emoji_map = {}  # Stocker le mapping id -> format string
        options = []
        for e in emojis[:25]:
            # Stocker le format complet de l'emoji
            if e.animated:
                self.emoji_map[str(e.id)] = f"<a:{e.name}:{e.id}>"
            else:
                self.emoji_map[str(e.id)] = f"<:{e.name}:{e.id}>"
            options.append(discord.SelectOption(
                label=e.name[:25],
                value=str(e.id),
                emoji=e
            ))
        super().__init__(
            placeholder="📤 Emojis à DONNER...",
            options=options,
            min_values=0,
            max_values=min(len(options), 10),
            row=0
        )
    
    async def callback(self, i):
        self.parent.je_donne = []
        for emoji_id in self.values:
            # Utiliser le format stocké directement
            if emoji_id in self.emoji_map:
                self.parent.je_donne.append(self.emoji_map[emoji_id])
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeEmojiWantSelect(Select):
    def __init__(self, parent, emojis):
        self.parent = parent
        self.emoji_map = {}  # Stocker le mapping id -> format string
        options = []
        for e in emojis[:25]:
            # Stocker le format complet de l'emoji
            if e.animated:
                self.emoji_map[str(e.id)] = f"<a:{e.name}:{e.id}>"
            else:
                self.emoji_map[str(e.id)] = f"<:{e.name}:{e.id}>"
            options.append(discord.SelectOption(
                label=e.name[:25],
                value=str(e.id),
                emoji=e
            ))
        super().__init__(
            placeholder="📥 Emojis que je VEUX...",
            options=options,
            min_values=0,
            max_values=min(len(options), 10),
            row=1
        )
    
    async def callback(self, i):
        self.parent.je_veux = []
        for emoji_id in self.values:
            # Utiliser le format stocké directement
            if emoji_id in self.emoji_map:
                self.parent.je_veux.append(self.emoji_map[emoji_id])
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeGameModal(Modal, title="🎮 Définir le Jeu"):
    jeu = TextInput(label="Nom du jeu", placeholder="Ex: Rocket League, Fortnite, GTA RP...", max_length=50)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.jeu = self.jeu.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeTextGiveModal(Modal, title="📤 Ce que je DONNE (texte)"):
    texte = TextInput(label="Description", placeholder="Ex: 500 crédits, Voiture TW...", style=discord.TextStyle.paragraph, max_length=150, required=False)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.texte_donne = self.texte.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeTextWantModal(Modal, title="📥 Ce que je VEUX (texte)"):
    texte = TextInput(label="Description", placeholder="Ex: Octane TW, 1000 crédits...", style=discord.TextStyle.paragraph, max_length=150, required=False)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.texte_veux = self.texte.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

# ═══════════════════════════════════════════════════════════════════════════════
#                              📊 COMMANDE /STAT - STATISTIQUES MEMBRE
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="stat", description="📊 Voir les statistiques d'activité d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez voir les stats (vous par défaut)")
async def stat_cmd(i: discord.Interaction, membre: discord.Member = None):
    # Vérifier le salon autorisé
    if not await check_command_channel(i, 'stat'):
        return
    
    target = membre or i.user
    
    if target.bot:
        return await i.response.send_message("❌ Les bots n'ont pas de statistiques", ephemeral=True)
    
    await i.response.defer()
    
    # Générer les stats pour 7 jours par défaut
    stats = await get_member_stats(i.guild, target, 7)
    embed, file = await create_stat_embed(i.guild, target, stats, 7)
    
    v = StatMemberView(i.user, i.guild, target)
    
    if file:
        await i.followup.send(embed=embed, file=file, view=v)
    else:
        await i.followup.send(embed=embed, view=v)

class StatMemberView(View):
    def __init__(self, user, guild, target):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.target = target
        self.period = 7
    
    @discord.ui.button(label="📅 7 Jours", style=discord.ButtonStyle.primary, disabled=True)
    async def btn_7d(self, i, b):
        self.period = 7
        self.btn_7d.disabled = True
        self.btn_30d.disabled = False
        await self.refresh(i)
    
    @discord.ui.button(label="📅 30 Jours", style=discord.ButtonStyle.secondary)
    async def btn_30d(self, i, b):
        self.period = 30
        self.btn_7d.disabled = False
        self.btn_30d.disabled = True
        await self.refresh(i)
    
    @discord.ui.button(label="📈 Graphique Détaillé", style=discord.ButtonStyle.success, row=1)
    async def btn_graph(self, i, b):
        await i.response.defer()
        img = await generate_detailed_stat_graph(self.guild, self.target, self.period)
        if img:
            file = discord.File(img, filename="stats_detailed.png")
            e = discord.Embed(
                title=f"📊 Statistiques Détaillées - {self.target.display_name}",
                color=C.PURPLE
            )
            e.set_image(url="attachment://stats_detailed.png")
            e.set_footer(text=f"Période: {self.period} jours • {self.guild.name}")
            await i.followup.send(embed=e, file=file, ephemeral=True)
        else:
            await i.followup.send("❌ Pas assez de données pour générer un graphique", ephemeral=True)
    
    async def refresh(self, i):
        await i.response.defer()
        stats = await get_member_stats(self.guild, self.target, self.period)
        embed, file = await create_stat_embed(self.guild, self.target, stats, self.period)
        
        if file:
            await i.message.delete()
            await i.followup.send(embed=embed, file=file, view=self)
        else:
            await i.message.edit(embed=embed, view=self)

async def get_member_stats(guild, member, days):
    """Récupère les statistiques d'un membre sur une période donnée"""
    stats = {
        'total_messages': 0,
        'total_vocal_time': 0,
        'channels_messages': {},  # {channel_id: count}
        'channels_vocal': {},  # {channel_id: duration}
        'messages_per_day': {},  # {date: count}
        'vocal_per_day': {},  # {date: duration}
        'most_popular_message': None,
        'first_activity': None,
        'last_activity': None
    }
    
    try:
        cutoff = now() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Récupérer les messages
            async with db.execute('''
                SELECT channel_id, message_id, created_at FROM member_activity 
                WHERE guild_id=? AND user_id=? AND activity_type='message' AND created_at >= ?
                ORDER BY created_at ASC
            ''', (guild.id, member.id, cutoff_str)) as cursor:
                async for row in cursor:
                    ch_id, msg_id, created_at = row
                    stats['total_messages'] += 1
                    
                    # Par salon
                    stats['channels_messages'][ch_id] = stats['channels_messages'].get(ch_id, 0) + 1
                    
                    # Par jour
                    try:
                        dt = datetime.fromisoformat(created_at)
                        date_key = dt.strftime('%Y-%m-%d')
                        stats['messages_per_day'][date_key] = stats['messages_per_day'].get(date_key, 0) + 1
                        
                        if not stats['first_activity'] or dt < stats['first_activity']:
                            stats['first_activity'] = dt
                        if not stats['last_activity'] or dt > stats['last_activity']:
                            stats['last_activity'] = dt
                    except:
                        pass
            
            # Récupérer les sessions vocales
            async with db.execute('''
                SELECT channel_id, duration, created_at FROM member_activity 
                WHERE guild_id=? AND user_id=? AND activity_type='vocal' AND created_at >= ?
                ORDER BY created_at ASC
            ''', (guild.id, member.id, cutoff_str)) as cursor:
                async for row in cursor:
                    ch_id, duration, created_at = row
                    stats['total_vocal_time'] += duration or 0
                    
                    # Par salon
                    stats['channels_vocal'][ch_id] = stats['channels_vocal'].get(ch_id, 0) + (duration or 0)
                    
                    # Par jour
                    try:
                        dt = datetime.fromisoformat(created_at)
                        date_key = dt.strftime('%Y-%m-%d')
                        stats['vocal_per_day'][date_key] = stats['vocal_per_day'].get(date_key, 0) + (duration or 0)
                        
                        if not stats['first_activity'] or dt < stats['first_activity']:
                            stats['first_activity'] = dt
                        if not stats['last_activity'] or dt > stats['last_activity']:
                            stats['last_activity'] = dt
                    except:
                        pass
        
        # Trouver le message le plus populaire (avec le plus de réactions)
        # On cherche dans les derniers messages du membre
        if stats['channels_messages']:
            top_channel_id = max(stats['channels_messages'], key=stats['channels_messages'].get)
            channel = guild.get_channel(top_channel_id)
            if channel:
                try:
                    async for msg in channel.history(limit=100):
                        if msg.author.id == member.id:
                            reaction_count = sum(r.count for r in msg.reactions) if msg.reactions else 0
                            if reaction_count > 0:
                                if not stats['most_popular_message'] or reaction_count > stats['most_popular_message']['reactions']:
                                    stats['most_popular_message'] = {
                                        'content': msg.content[:100] + "..." if len(msg.content) > 100 else msg.content,
                                        'reactions': reaction_count,
                                        'url': msg.jump_url
                                    }
                except:
                    pass
                    
    except Exception as ex:
        print(f"Erreur get_member_stats: {ex}")
    
    return stats

async def create_stat_embed(guild, member, stats, days):
    """Crée l'embed des statistiques avec graphique"""
    e = discord.Embed(
        title=f"📊 Statistiques de {member.display_name}",
        color=C.PURPLE
    )
    e.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
    
    # Période
    e.description = f"**Période:** {days} derniers jours"
    
    # Messages
    e.add_field(
        name="💬 Messages",
        value=f"**{stats['total_messages']}** messages envoyés",
        inline=True
    )
    
    # Temps vocal
    vocal_time = stats['total_vocal_time']
    if vocal_time >= 3600:
        time_str = f"{vocal_time // 3600}h {(vocal_time % 3600) // 60}min"
    elif vocal_time >= 60:
        time_str = f"{vocal_time // 60}min {vocal_time % 60}s"
    else:
        time_str = f"{vocal_time}s"
    
    e.add_field(
        name="🔊 Temps en vocal",
        value=f"**{time_str}**",
        inline=True
    )
    
    # Moyenne par jour
    avg_messages = stats['total_messages'] / days if days > 0 else 0
    e.add_field(
        name="📈 Moyenne/jour",
        value=f"**{avg_messages:.1f}** msg/jour",
        inline=True
    )
    
    # Salon écrit le plus actif
    if stats['channels_messages']:
        top_ch_id = max(stats['channels_messages'], key=stats['channels_messages'].get)
        top_ch = guild.get_channel(top_ch_id)
        top_count = stats['channels_messages'][top_ch_id]
        e.add_field(
            name="📝 Salon écrit favoris",
            value=f"{top_ch.mention if top_ch else 'Inconnu'}\n({top_count} messages)",
            inline=True
        )
    else:
        e.add_field(name="📝 Salon écrit favoris", value="*Aucune donnée*", inline=True)
    
    # Salon vocal le plus utilisé
    if stats['channels_vocal']:
        top_vc_id = max(stats['channels_vocal'], key=stats['channels_vocal'].get)
        top_vc = guild.get_channel(top_vc_id)
        top_duration = stats['channels_vocal'][top_vc_id]
        if top_duration >= 3600:
            dur_str = f"{top_duration // 3600}h {(top_duration % 3600) // 60}min"
        elif top_duration >= 60:
            dur_str = f"{top_duration // 60}min"
        else:
            dur_str = f"{top_duration}s"
        e.add_field(
            name="🎤 Salon vocal favoris",
            value=f"{top_vc.name if top_vc else 'Inconnu'}\n({dur_str})",
            inline=True
        )
    else:
        e.add_field(name="🎤 Salon vocal favoris", value="*Aucune donnée*", inline=True)
    
    # Dernière activité
    if stats['last_activity']:
        e.add_field(
            name="🕐 Dernière activité",
            value=f"<t:{int(stats['last_activity'].timestamp())}:R>",
            inline=True
        )
    else:
        e.add_field(name="🕐 Dernière activité", value="*Inconnue*", inline=True)
    
    # Message le plus populaire
    if stats['most_popular_message']:
        mp = stats['most_popular_message']
        e.add_field(
            name=f"⭐ Message populaire ({mp['reactions']} réactions)",
            value=f"*\"{mp['content']}\"*\n[Voir le message]({mp['url']})",
            inline=False
        )
    
    # Générer le graphique
    img = await generate_stat_graph(stats, days, member.display_name)
    file = None
    if img:
        file = discord.File(img, filename="stats.png")
        e.set_image(url="attachment://stats.png")
    
    e.set_footer(text=f"{guild.name} • /stat", icon_url=guild.icon.url if guild.icon else None)
    e.timestamp = now()
    
    return e, file

async def generate_stat_graph(stats, days, username):
    """Génère un graphique des statistiques"""
    try:
        if not stats['messages_per_day'] and not stats['vocal_per_day']:
            return None
        
        # Préparer les données pour tous les jours de la période
        dates = []
        messages = []
        vocal = []
        
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            dates.append(dt.strftime('%d/%m'))
            messages.append(stats['messages_per_day'].get(date_key, 0))
            vocal.append(stats['vocal_per_day'].get(date_key, 0) / 60)  # Convertir en minutes
        
        # Créer le graphique
        fig, ax1 = plt.subplots(figsize=(12, 5))
        fig.patch.set_facecolor('#2f3136')
        ax1.set_facecolor('#36393f')
        
        # Barres pour les messages
        x = range(len(dates))
        bars = ax1.bar([i - 0.2 for i in x], messages, 0.4, label='Messages', color='#5865F2', alpha=0.8)
        ax1.set_xlabel('Date', color='white', fontsize=10)
        ax1.set_ylabel('Messages', color='#5865F2', fontsize=10)
        ax1.tick_params(axis='y', labelcolor='#5865F2')
        ax1.tick_params(axis='x', colors='white')
        
        # Deuxième axe pour le vocal
        ax2 = ax1.twinx()
        bars2 = ax2.bar([i + 0.2 for i in x], vocal, 0.4, label='Vocal (min)', color='#57F287', alpha=0.8)
        ax2.set_ylabel('Minutes en vocal', color='#57F287', fontsize=10)
        ax2.tick_params(axis='y', labelcolor='#57F287')
        
        # Style
        ax1.set_xticks(x)
        ax1.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        ax1.spines['bottom'].set_color('white')
        ax1.spines['left'].set_color('#5865F2')
        ax1.spines['top'].set_visible(False)
        ax2.spines['right'].set_color('#57F287')
        ax2.spines['top'].set_visible(False)
        
        # Titre
        plt.title(f'📊 Activité de {username}', color='white', fontsize=14, fontweight='bold', pad=15)
        
        # Légende
        fig.legend(loc='upper right', bbox_to_anchor=(0.98, 0.98), facecolor='#36393f', edgecolor='white', labelcolor='white')
        
        plt.tight_layout()
        
        # Sauvegarder
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
        buf.seek(0)
        plt.close(fig)
        
        return buf
        
    except Exception as ex:
        print(f"Erreur génération graphique: {ex}")
        return None

async def generate_detailed_stat_graph(guild, member, days):
    """Génère un graphique détaillé avec plusieurs visualisations"""
    try:
        stats = await get_member_stats(guild, member, days)
        
        if not stats['total_messages'] and not stats['total_vocal_time']:
            return None
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.patch.set_facecolor('#2f3136')
        
        # 1. Camembert des salons écrits (haut gauche)
        ax1 = axes[0, 0]
        ax1.set_facecolor('#2f3136')
        
        if stats['channels_messages']:
            # Top 5 salons
            sorted_channels = sorted(stats['channels_messages'].items(), key=lambda x: x[1], reverse=True)[:5]
            labels = []
            sizes = []
            for ch_id, count in sorted_channels:
                ch = guild.get_channel(ch_id)
                labels.append(f"#{ch.name[:15]}" if ch else f"#{ch_id}")
                sizes.append(count)
            
            colors = ['#5865F2', '#57F287', '#FEE75C', '#ED4245', '#9B59B6']
            ax1.pie(sizes, labels=labels, colors=colors[:len(sizes)], autopct='%1.1f%%',
                   textprops={'color': 'white', 'fontsize': 9})
            ax1.set_title('📝 Top Salons Écrits', color='white', fontsize=12, fontweight='bold')
        else:
            ax1.text(0.5, 0.5, 'Aucune donnée', ha='center', va='center', color='white', fontsize=12)
            ax1.set_title('📝 Top Salons Écrits', color='white', fontsize=12, fontweight='bold')
        
        # 2. Camembert des salons vocaux (haut droit)
        ax2 = axes[0, 1]
        ax2.set_facecolor('#2f3136')
        
        if stats['channels_vocal']:
            sorted_vocal = sorted(stats['channels_vocal'].items(), key=lambda x: x[1], reverse=True)[:5]
            labels = []
            sizes = []
            for ch_id, duration in sorted_vocal:
                ch = guild.get_channel(ch_id)
                labels.append(f"🔊 {ch.name[:15]}" if ch else f"🔊 {ch_id}")
                sizes.append(duration)
            
            colors = ['#57F287', '#5865F2', '#FEE75C', '#ED4245', '#9B59B6']
            ax2.pie(sizes, labels=labels, colors=colors[:len(sizes)], autopct='%1.1f%%',
                   textprops={'color': 'white', 'fontsize': 9})
            ax2.set_title('🎤 Top Salons Vocaux', color='white', fontsize=12, fontweight='bold')
        else:
            ax2.text(0.5, 0.5, 'Aucune donnée', ha='center', va='center', color='white', fontsize=12)
            ax2.set_title('🎤 Top Salons Vocaux', color='white', fontsize=12, fontweight='bold')
        
        # 3. Courbe d'activité messages (bas gauche)
        ax3 = axes[1, 0]
        ax3.set_facecolor('#36393f')
        
        dates = []
        messages = []
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            dates.append(dt.strftime('%d/%m'))
            messages.append(stats['messages_per_day'].get(date_key, 0))
        
        ax3.fill_between(range(len(dates)), messages, alpha=0.3, color='#5865F2')
        ax3.plot(range(len(dates)), messages, color='#5865F2', linewidth=2, marker='o', markersize=4)
        ax3.set_xlabel('Date', color='white', fontsize=10)
        ax3.set_ylabel('Messages', color='white', fontsize=10)
        ax3.set_title('💬 Messages par jour', color='white', fontsize=12, fontweight='bold')
        ax3.tick_params(colors='white')
        ax3.set_xticks(range(0, len(dates), max(1, len(dates)//7)))
        ax3.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45, fontsize=8)
        ax3.spines['bottom'].set_color('white')
        ax3.spines['left'].set_color('white')
        ax3.spines['top'].set_visible(False)
        ax3.spines['right'].set_visible(False)
        ax3.grid(True, alpha=0.2, color='white')
        
        # 4. Courbe d'activité vocale (bas droit)
        ax4 = axes[1, 1]
        ax4.set_facecolor('#36393f')
        
        vocal = []
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            vocal.append(stats['vocal_per_day'].get(date_key, 0) / 60)  # En minutes
        
        ax4.fill_between(range(len(dates)), vocal, alpha=0.3, color='#57F287')
        ax4.plot(range(len(dates)), vocal, color='#57F287', linewidth=2, marker='o', markersize=4)
        ax4.set_xlabel('Date', color='white', fontsize=10)
        ax4.set_ylabel('Minutes', color='white', fontsize=10)
        ax4.set_title('🎤 Temps vocal par jour', color='white', fontsize=12, fontweight='bold')
        ax4.tick_params(colors='white')
        ax4.set_xticks(range(0, len(dates), max(1, len(dates)//7)))
        ax4.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45, fontsize=8)
        ax4.spines['bottom'].set_color('white')
        ax4.spines['left'].set_color('white')
        ax4.spines['top'].set_visible(False)
        ax4.spines['right'].set_visible(False)
        ax4.grid(True, alpha=0.2, color='white')
        
        # Titre principal
        fig.suptitle(f'📊 Statistiques détaillées de {member.display_name}', 
                    color='white', fontsize=16, fontweight='bold', y=0.98)
        
        plt.tight_layout(rect=[0, 0, 1, 0.96])
        
        # Sauvegarder
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
        buf.seek(0)
        plt.close(fig)
        
        return buf
        
    except Exception as ex:
        print(f"Erreur génération graphique détaillé: {ex}")
        return None

# ═══════════════════════════════════════════════════════════════════════════════
#                              📊 SUGGESTION VOTE TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    
    # Vérifier si c'est une suggestion
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id FROM suggestions WHERE message_id=?', (payload.message_id,)) as c:
                if not await c.fetchone():
                    return
        
        # Mettre à jour la couleur de l'embed
        channel = bot.get_channel(payload.channel_id)
        if not channel:
            return
        
        msg = await channel.fetch_message(payload.message_id)
        
        # Compter les votes
        votes = {"✅": 0, "🟠": 0, "❌": 0}
        for reaction in msg.reactions:
            if reaction.emoji in votes:
                votes[reaction.emoji] = reaction.count - 1  # -1 pour le bot
        
        # Déterminer la couleur
        total = sum(votes.values())
        if total == 0:
            color = C.BLURPLE
        elif votes["✅"] > votes["❌"] and votes["✅"] > votes["🟠"]:
            color = C.GREEN
        elif votes["❌"] > votes["✅"] and votes["❌"] > votes["🟠"]:
            color = C.RED
        elif votes["🟠"] > votes["✅"] and votes["🟠"] > votes["❌"]:
            color = C.ORANGE
        else:
            color = C.BLURPLE
        
        # Mettre à jour l'embed
        if msg.embeds:
            old_embed = msg.embeds[0]
            new_embed = discord.Embed(
                title=old_embed.title,
                description=old_embed.description,
                color=color,
                timestamp=old_embed.timestamp
            )
            for field in old_embed.fields:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            if old_embed.thumbnail:
                new_embed.set_thumbnail(url=old_embed.thumbnail.url)
            new_embed.set_footer(text=f"✅ {votes['✅']} | 🟠 {votes['🟠']} | ❌ {votes['❌']}")
            
            await msg.edit(embed=new_embed)
    except:
        pass

@bot.event
async def on_raw_reaction_remove(payload):
    await on_raw_reaction_add(payload)  # Même logique

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎭 REALSY INACTIVITY TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(hours=24)
async def check_realsy_inactivity():
    """Vérifie l'inactivité des utilisateurs avec le rôle Realsy chaque jour"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, user_id, last_activity, warn_count FROM realsy_tracking') as c:
                rows = await c.fetchall()
        
        for guild_id, user_id, last_activity, warn_count in rows:
            try:
                guild = bot.get_guild(guild_id)
                if not guild:
                    continue
                
                c = await cfg(guild_id)
                role = guild.get_role(c.get('rellseas_role', 0))
                if not role:
                    continue
                
                member = guild.get_member(user_id)
                if not member or role not in member.roles:
                    # L'utilisateur n'a plus le rôle, supprimer du tracking
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                            (guild_id, user_id))
                        await db.commit()
                    continue
                
                # Calculer l'inactivité
                try:
                    last_dt = datetime.fromisoformat(last_activity)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                except:
                    last_dt = now() - timedelta(days=8)  # Considérer comme inactif si erreur
                
                days_inactive = (now() - last_dt).days
                
                if days_inactive >= 7:
                    warn_ch = guild.get_channel(c.get('rellseas_warn_channel', 0))
                    log_ch = guild.get_channel(c.get('rellseas_log_channel', 0))
                    
                    if warn_count == 0:
                        # Premier warn
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute('UPDATE realsy_tracking SET warn_count=1 WHERE guild_id=? AND user_id=?',
                                (guild_id, user_id))
                            await db.commit()
                        
                        if warn_ch:
                            e = discord.Embed(title="⚠️ Avertissement Inactivité", color=C.YELLOW, timestamp=now())
                            e.description = f"{member.mention}, vous êtes inactif depuis **{days_inactive} jours**.\n\n⚠️ Si vous restez inactif, votre rôle **{role.name}** sera retiré."
                            e.set_thumbnail(url=member.display_avatar.url)
                            await warn_ch.send(content=member.mention, embed=e)
                        
                        if log_ch:
                            log_e = discord.Embed(title="⚠️ Warn Inactivité #1", color=C.YELLOW, timestamp=now())
                            log_e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
                            log_e.add_field(name="📅 Inactif depuis", value=f"{days_inactive} jours", inline=True)
                            log_e.set_thumbnail(url=member.display_avatar.url)
                            await log_ch.send(embed=log_e)
                    
                    elif warn_count >= 1 and days_inactive >= 14:
                        # Deuxième warn - retirer le rôle
                        try:
                            await member.remove_roles(role, reason="Inactivité - 2ème avertissement")
                            
                            # Supprimer du tracking
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                                    (guild_id, user_id))
                                await db.commit()
                            
                            if warn_ch:
                                e = discord.Embed(title="🚫 Rôle Retiré - Inactivité", color=C.RED, timestamp=now())
                                e.description = f"{member.mention}, votre rôle **{role.name}** a été retiré pour cause d'inactivité prolongée ({days_inactive} jours)."
                                e.set_thumbnail(url=member.display_avatar.url)
                                await warn_ch.send(content=member.mention, embed=e)
                            
                            if log_ch:
                                log_e = discord.Embed(title="🚫 Rôle Retiré - AFK", color=C.RED, timestamp=now())
                                log_e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
                                log_e.add_field(name="🎭 Rôle retiré", value=role.mention, inline=True)
                                log_e.add_field(name="📅 Inactif depuis", value=f"{days_inactive} jours", inline=True)
                                log_e.set_thumbnail(url=member.display_avatar.url)
                                await log_ch.send(embed=log_e)
                        except:
                            pass
            except:
                continue
    except:
        pass

@check_realsy_inactivity.before_loop
async def before_check():
    await bot.wait_until_ready()

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 TÂCHE VÉRIFICATION FEEDS SOCIAUX
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=5)
async def check_social_feeds():
    """Vérifie les nouveaux posts YouTube, Twitch, Twitter, Reddit, Discord et RoSocial"""
    try:
        async with aiohttp.ClientSession() as session:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT guild_id, data FROM guild_config') as cursor:
                    async for row in cursor:
                        guild_id, data_str = row
                        try:
                            data = json.loads(data_str) if data_str else {}
                            guild = bot.get_guild(guild_id)
                            if not guild:
                                continue
                            
                            # YouTube
                            await check_youtube_feeds(session, guild, data)
                            
                            # Twitch
                            await check_twitch_feeds(session, guild, data)
                            
                            # Twitter/X
                            await check_twitter_feeds(session, guild, data)
                            
                            # Reddit
                            await check_reddit_feeds(session, guild, data)
                            
                            # RoSocial
                            await check_rosocial_feeds(session, guild, data)
                            
                            # Roblox UGC
                            await check_roblox_ugc_feeds(session, guild, data)
                            
                            # Réductions de jeux (vérifiée moins souvent via counter)
                            await check_game_deals(session, guild, data)
                            
                        except Exception as ex:
                            print(f"Erreur feed {guild_id}: {ex}")
                            continue
    except Exception as ex:
        print(f"Erreur check_social_feeds: {ex}")

async def check_youtube_feeds(session, guild, data):
    """Vérifie les nouvelles vidéos YouTube"""
    default_channel = guild.get_channel(data.get('ads_youtube_channel', 0))
    feeds = data.get('ads_youtube_feeds', [])
    if not feeds:
        return
    
    for feed in feeds:
        try:
            # Support ancien et nouveau format
            if isinstance(feed, dict):
                channel_id = feed.get('id', '')
                channel_name = feed.get('name', 'YouTube')
                # Utiliser le salon spécifique ou le salon par défaut
                feed_channel_id = feed.get('channel_id', 0)
                target_channel = guild.get_channel(feed_channel_id) if feed_channel_id else default_channel
            else:
                continue
            
            if not target_channel:
                continue
            
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            
            async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                xml_text = await resp.text()
            
            root = ET.fromstring(xml_text)
            ns = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015', 'media': 'http://search.yahoo.com/mrss/'}
            
            entries = root.findall('atom:entry', ns)
            if not entries:
                continue
            
            entry = entries[0]
            video_id_elem = entry.find('yt:videoId', ns)
            title_elem = entry.find('atom:title', ns)
            published_elem = entry.find('atom:published', ns)
            
            # Essayer de trouver la description
            media_group = entry.find('media:group', ns)
            description = ""
            if media_group is not None:
                desc_elem = media_group.find('media:description', ns)
                if desc_elem is not None and desc_elem.text:
                    description = desc_elem.text[:200] + "..." if len(desc_elem.text) > 200 else desc_elem.text
            
            if video_id_elem is None or title_elem is None:
                continue
            
            video_id = video_id_elem.text
            title = title_elem.text
            cache_key = f"yt_{guild.id}_{channel_id}"
            
            if cache_key in posted_content and posted_content[cache_key] == video_id:
                continue
            
            posted_content[cache_key] = video_id
            
            # ═══════════════ EMBED YOUTUBE PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0xFF0000)
            
            # Titre avec bannière
            e.title = f"▶️ {title}"
            e.url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Description du post
            if description:
                e.description = f"*{description}*"
            
            # Auteur avec logo YouTube
            e.set_author(
                name=f"🔴 YOUTUBE • {channel_name}",
                url=f"https://www.youtube.com/channel/{channel_id}",
                icon_url="https://www.gstatic.com/youtube/img/branding/youtubelogo/svg/youtubelogo.svg"
            )
            
            # Miniature grande
            e.set_image(url=f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")
            
            # Bouton "Regarder"
            e.add_field(
                name="",
                value=f"[▶️ **Regarder la vidéo**](https://www.youtube.com/watch?v={video_id})",
                inline=False
            )
            
            # Footer avec icône
            e.set_footer(
                text=f"YouTube • {channel_name}",
                icon_url="https://www.youtube.com/s/desktop/28b67e7f/img/favicon_144x144.png"
            )
            e.timestamp = now()
            
            await target_channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur YouTube feed {feed}: {ex}")
            continue

async def check_twitch_feeds(session, guild, data):
    """Vérifie si des streamers sont en live sur Twitch"""
    channel = guild.get_channel(data.get('ads_twitch_channel', 0))
    feeds = data.get('ads_twitch_feeds', [])
    if not channel or not feeds:
        return
    
    for username in feeds:
        try:
            url = f"https://www.twitch.tv/{username}"
            cache_key = f"twitch_{guild.id}_{username}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
            
            is_live = '"isLiveBroadcast":true' in html or 'isLiveBroadcast' in html
            
            was_live = posted_content.get(cache_key, False)
            
            if is_live and not was_live:
                posted_content[cache_key] = True
                
                # ═══════════════ EMBED TWITCH PROFESSIONNEL ═══════════════
                e = discord.Embed(color=0x9146FF)
                
                e.title = f"🔴 {username} est en LIVE !"
                e.url = f"https://www.twitch.tv/{username}"
                
                e.description = f"**{username}** vient de lancer un stream !\nRejoins le live maintenant !"
                
                e.set_author(
                    name=f"🟣 TWITCH • {username}",
                    url=f"https://www.twitch.tv/{username}",
                    icon_url="https://static.twitchcdn.net/assets/favicon-32-e29e246c157142c94346.png"
                )
                
                # Preview du stream (avec timestamp pour éviter le cache)
                e.set_image(url=f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{username.lower()}-1280x720.jpg?t={int(now().timestamp())}")
                
                e.add_field(
                    name="",
                    value=f"[🟣 **Rejoindre le stream**](https://www.twitch.tv/{username})",
                    inline=False
                )
                
                e.set_footer(
                    text=f"Twitch • {username}",
                    icon_url="https://static.twitchcdn.net/assets/favicon-32-e29e246c157142c94346.png"
                )
                e.timestamp = now()
                
                await channel.send(embed=e)
                
            elif not is_live and was_live:
                posted_content[cache_key] = False
            
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Twitch feed {username}: {ex}")
            continue

async def check_reddit_feeds(session, guild, data):
    """Vérifie les nouveaux posts Reddit"""
    channel = guild.get_channel(data.get('ads_reddit_channel', 0))
    feeds = data.get('ads_reddit_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Discord Bot 1.0'}
    
    for subreddit in feeds:
        try:
            rss_url = f"https://www.reddit.com/r/{subreddit}/new.rss?limit=1"
            
            async with session.get(rss_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                xml_text = await resp.text()
            
            root = ET.fromstring(xml_text)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            
            entries = root.findall('atom:entry', ns)
            if not entries:
                continue
            
            entry = entries[0]
            post_id = entry.find('atom:id', ns)
            title = entry.find('atom:title', ns)
            link = entry.find('atom:link', ns)
            author = entry.find('atom:author/atom:name', ns)
            content = entry.find('atom:content', ns)
            
            if post_id is None or title is None:
                continue
            
            post_id = post_id.text
            title = title.text
            link = link.get('href') if link is not None else f"https://reddit.com/r/{subreddit}"
            author = author.text if author is not None else "Unknown"
            
            # Extraire image si présente dans le contenu HTML
            image_url = None
            if content is not None and content.text:
                import re
                img_match = re.search(r'<img[^>]+src="([^"]+)"', content.text)
                if img_match:
                    image_url = img_match.group(1)
            
            cache_key = f"rd_{guild.id}_{subreddit}"
            
            if cache_key in posted_content and posted_content[cache_key] == post_id:
                continue
            
            posted_content[cache_key] = post_id
            
            # ═══════════════ EMBED REDDIT PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0xFF4500)
            
            e.title = f"📰 {title[:200]}"
            e.url = link
            
            e.set_author(
                name=f"🟠 REDDIT • r/{subreddit}",
                url=f"https://www.reddit.com/r/{subreddit}",
                icon_url="https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png"
            )
            
            e.add_field(name="👤 Auteur", value=f"u/{author}", inline=True)
            e.add_field(name="📁 Subreddit", value=f"r/{subreddit}", inline=True)
            
            if image_url and ('i.redd.it' in image_url or 'preview.redd.it' in image_url):
                e.set_image(url=image_url)
            
            e.add_field(
                name="",
                value=f"[🔗 **Voir le post complet**]({link})",
                inline=False
            )
            
            e.set_footer(
                text=f"Reddit • r/{subreddit}",
                icon_url="https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Reddit feed {subreddit}: {ex}")
            continue

async def check_twitter_feeds(session, guild, data):
    """Vérifie les nouveaux tweets via Nitter"""
    channel = guild.get_channel(data.get('ads_twitter_channel', 0))
    feeds = data.get('ads_twitter_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for username in feeds:
        try:
            xml_text = None
            working_instance = None
            for instance in NITTER_INSTANCES:
                try:
                    rss_url = f"https://{instance}/{username}/rss"
                    async with session.get(rss_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            xml_text = await resp.text()
                            working_instance = instance
                            break
                except:
                    continue
            
            if not xml_text:
                continue
            
            root = ET.fromstring(xml_text)
            items = root.findall('.//item')
            if not items:
                continue
            
            item = items[0]
            title = item.find('title')
            link = item.find('link')
            guid = item.find('guid')
            description = item.find('description')
            
            if title is None or guid is None:
                continue
            
            tweet_id = guid.text if guid is not None else ""
            tweet_text = title.text if title is not None else ""
            tweet_link = link.text if link is not None else f"https://twitter.com/{username}"
            
            # Convertir lien Nitter en lien Twitter
            tweet_link = tweet_link.replace(f"https://{working_instance}", "https://twitter.com") if working_instance else tweet_link
            
            # Extraire image si présente
            image_url = None
            if description is not None and description.text:
                import re
                img_match = re.search(r'<img[^>]+src="([^"]+)"', description.text)
                if img_match:
                    image_url = img_match.group(1)
            
            cache_key = f"twitter_{guild.id}_{username}"
            
            if cache_key in posted_content and posted_content[cache_key] == tweet_id:
                continue
            
            posted_content[cache_key] = tweet_id
            
            # ═══════════════ EMBED TWITTER PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0x1DA1F2)
            
            e.description = f"💬 {tweet_text[:1900]}"
            
            e.set_author(
                name=f"🐦 TWITTER/X • @{username}",
                url=f"https://twitter.com/{username}",
                icon_url="https://abs.twimg.com/responsive-web/client-web/icon-ios.77d25eba.png"
            )
            
            if image_url:
                # Convertir URL Nitter en URL Twitter si nécessaire
                if working_instance and working_instance in image_url:
                    image_url = image_url.replace(f"https://{working_instance}", "https://pbs.twimg.com")
                e.set_image(url=image_url)
            
            e.add_field(
                name="",
                value=f"[🐦 **Voir le tweet**]({tweet_link})",
                inline=False
            )
            
            e.set_footer(
                text=f"Twitter/X • @{username}",
                icon_url="https://abs.twimg.com/responsive-web/client-web/icon-ios.77d25eba.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Twitter feed {username}: {ex}")
            continue

async def check_rosocial_feeds(session, guild, data):
    """Vérifie les nouveaux posts RoSocial"""
    default_channel = guild.get_channel(data.get('ads_rosocial_channel', 0))
    feeds = data.get('ads_rosocial_feeds', [])
    if not feeds:
        return
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8'
    }
    
    for feed in feeds:
        try:
            # Gérer le format dict ou string
            if isinstance(feed, dict):
                username = feed.get('username', '')
                feed_channel_id = feed.get('channel_id', 0)
                channel = guild.get_channel(feed_channel_id) if feed_channel_id else default_channel
            else:
                username = str(feed)
                channel = default_channel
            
            if not username or not channel:
                continue
            
            profile_url = f"https://rosocial.net/{username}"
            
            # Récupérer la page du profil
            async with session.get(profile_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
            
            import re
            
            # Trouver le dernier post (plusieurs patterns)
            posts = re.findall(r'href="https://rosocial\.net/posts/(\d+)"', html)
            if not posts:
                posts = re.findall(r'/posts/(\d+)', html)
            if not posts:
                posts = re.findall(r'data-post-id="(\d+)"', html)
            
            if not posts:
                continue
            
            latest_post_id = posts[0]
            cache_key = f"rs_{guild.id}_{username}"
            
            if cache_key in posted_content and posted_content[cache_key] == latest_post_id:
                continue
            
            posted_content[cache_key] = latest_post_id
            
            post_url = f"https://rosocial.net/posts/{latest_post_id}"
            
            # ═══════════════════════════════════════════════════════════════════════════════
            #                    📥 RÉCUPÉRER LA PAGE DU POST POUR L'IMAGE
            # ═══════════════════════════════════════════════════════════════════════════════
            post_content = ""
            image_url = None
            avatar_url = None
            
            try:
                async with session.get(post_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as post_resp:
                    if post_resp.status == 200:
                        post_html = await post_resp.text()
                        
                        # Extraire le contenu du post
                        content_patterns = [
                            r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>',
                            r'<p[^>]*class="[^"]*post-text[^"]*"[^>]*>(.*?)</p>',
                            r'<div[^>]*class="[^"]*activity-text[^"]*"[^>]*>(.*?)</div>',
                            r'<div[^>]*id="post-content"[^>]*>(.*?)</div>',
                        ]
                        for pattern in content_patterns:
                            match = re.search(pattern, post_html, re.DOTALL | re.IGNORECASE)
                            if match:
                                # Nettoyer le HTML
                                content = re.sub(r'<[^>]+>', '', match.group(1))
                                content = content.strip()
                                if content and len(content) > 5:
                                    post_content = content[:300]
                                    break
                        
                        # Extraire l'image du post (plusieurs patterns)
                        image_patterns = [
                            r'<img[^>]+src="(https://rosocial\.net/content/uploads/photos/[^"]+)"',
                            r'<img[^>]+data-src="(https://rosocial\.net/content/uploads/photos/[^"]+)"',
                            r'src="(https://rosocial\.net/content/uploads/[^"]+\.(jpg|jpeg|png|gif|webp))"',
                            r'"(https://rosocial\.net/content/uploads/photos/\d+/\d+/[^"]+)"',
                            r'og:image"[^>]+content="([^"]+)"',
                        ]
                        for pattern in image_patterns:
                            match = re.search(pattern, post_html, re.IGNORECASE)
                            if match:
                                img = match.group(1)
                                # Vérifier que c'est une vraie image et pas un avatar
                                if 'avatar' not in img.lower() and 'profile' not in img.lower():
                                    image_url = img
                                    break
                        
                        # Extraire l'avatar
                        avatar_patterns = [
                            r'<img[^>]+class="[^"]*avatar[^"]*"[^>]+src="([^"]+)"',
                            r'<img[^>]+src="([^"]+)"[^>]+class="[^"]*avatar[^"]*"',
                            rf'{username}[^>]*<img[^>]+src="([^"]+)"',
                        ]
                        for pattern in avatar_patterns:
                            match = re.search(pattern, post_html, re.IGNORECASE)
                            if match:
                                avatar_url = match.group(1)
                                break
            except:
                pass
            
            # Avatar par défaut si non trouvé
            if not avatar_url:
                avatar_url = "https://rosocial.net/themes/flavor/flavor-developer/img/user-avatar.png"
            
            # ═══════════════════════════════════════════════════════════════════════════════
            #                        🎨 EMBED ROSOCIAL - DESIGN PROFESSIONNEL
            # ═══════════════════════════════════════════════════════════════════════════════
            
            e = discord.Embed(color=0x00D4AA)  # Vert RoSocial
            
            # Header avec le nom de l'auteur
            e.set_author(
                name=f"🎮 ROSOCIAL • {username}",
                url=profile_url,
                icon_url=avatar_url
            )
            
            # Titre
            e.title = f"📝 Nouveau post"
            e.url = post_url
            
            # Contenu du post
            if post_content and post_content.strip():
                # Nettoyer le contenu
                clean_content = post_content.replace('\n', ' ').strip()
                if clean_content:
                    e.description = f"*{clean_content}*"
            
            # IMAGE PRINCIPALE (le plus important !)
            if image_url:
                e.set_image(url=image_url)
            
            # Thumbnail avec avatar
            e.set_thumbnail(url=avatar_url)
            
            # Liens
            e.add_field(
                name="",
                value=f"### [🔗 Voir le post]({post_url}) • [👤 Profil]({profile_url})",
                inline=False
            )
            
            # Footer
            e.set_footer(
                text=f"RoSocial • {username}",
                icon_url="https://rosocial.net/themes/flavor/flavor-developer/img/logo.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur RoSocial feed {feed}: {ex}")
            continue

async def check_roblox_ugc_feeds(session, guild, data):
    """Vérifie les nouvelles créations UGC Roblox"""
    channel = guild.get_channel(data.get('ads_roblox_channel', 0))
    feeds = data.get('ads_roblox_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for feed in feeds:
        try:
            if isinstance(feed, dict):
                user_id = feed.get('user_id')
                username = feed.get('username', 'Créateur')
            else:
                continue
            
            if not user_id:
                continue
            
            # API Roblox Catalog - Récupérer les créations récentes
            catalog_url = f"https://catalog.roblox.com/v1/search/items?creatorTargetId={user_id}&creatorType=User&limit=10&sortType=3"
            
            async with session.get(catalog_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    continue
                catalog_data = await resp.json()
            
            items = catalog_data.get('data', [])
            if not items:
                continue
            
            # Vérifier chaque item
            for item in items[:3]:
                item_id = item.get('id')
                item_type = item.get('itemType', 'Asset')
                
                cache_key = f"rblx_{guild.id}_{user_id}_{item_id}"
                
                if cache_key in posted_content:
                    continue
                
                posted_content[cache_key] = True
                
                # Récupérer les détails de l'item
                if item_type == 'Asset':
                    details_url = f"https://economy.roblox.com/v2/assets/{item_id}/details"
                else:
                    details_url = f"https://catalog.roblox.com/v1/catalog/items/{item_id}/details?itemType={item_type}"
                
                try:
                    async with session.get(details_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                        if resp2.status == 200:
                            details = await resp2.json()
                        else:
                            details = {}
                except:
                    details = {}
                
                item_name = details.get('Name') or details.get('name') or f"Création #{item_id}"
                item_price = details.get('PriceInRobux') or details.get('price') or 0
                
                # URL de l'item
                item_url = f"https://www.roblox.com/catalog/{item_id}"
                
                # ═══════════════════════════════════════════════════════════════════════════════
                #                    🖼️ RÉCUPÉRATION DE L'IMAGE VIA THUMBNAILS API
                # ═══════════════════════════════════════════════════════════════════════════════
                thumb_url = None
                try:
                    thumb_api = f"https://thumbnails.roblox.com/v1/assets?assetIds={item_id}&returnPolicy=PlaceHolder&size=420x420&format=Png&isCircular=false"
                    async with session.get(thumb_api, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as thumb_resp:
                        if thumb_resp.status == 200:
                            thumb_data = await thumb_resp.json()
                            thumb_list = thumb_data.get('data', [])
                            if thumb_list and thumb_list[0].get('imageUrl'):
                                thumb_url = thumb_list[0]['imageUrl']
                except:
                    pass
                
                # Fallback si l'API ne retourne rien
                if not thumb_url:
                    thumb_url = f"https://rbxcdn.com/asset-thumbnail/image?assetId={item_id}&width=420&height=420&format=Png"
                
                # ═══════════════════════════════════════════════════════════════════════════════
                #                        🎨 EMBED ROBLOX UGC - DESIGN ÉPURÉ
                # ═══════════════════════════════════════════════════════════════════════════════
                
                e = discord.Embed(color=0x00B06B)  # Vert Roblox
                
                # Titre simple = Nom de l'article
                e.title = f"🎨 {item_name}"
                e.url = item_url
                
                # Image GRANDE de l'article (c'est le plus important)
                if thumb_url:
                    e.set_image(url=thumb_url)
                
                # Prix - bien visible
                if item_price and item_price > 0:
                    price_txt = f"**{item_price:,}** R$"
                else:
                    price_txt = "**Gratuit** 🎁"
                
                # Informations simples en ligne
                e.add_field(name="💰 Prix", value=price_txt, inline=True)
                e.add_field(name="👤 Créateur", value=f"**{username}**", inline=True)
                
                # Lien d'achat bien visible
                e.add_field(
                    name="",
                    value=f"### [🛒 Voir sur Roblox]({item_url})",
                    inline=False
                )
                
                # Footer simple
                e.set_footer(
                    text=f"Roblox UGC • {username}",
                    icon_url="https://images.rbxcdn.com/0785a14c892a503ab498b8f4100d4340.png"
                )
                e.timestamp = now()
                
                await channel.send(embed=e)
                await asyncio.sleep(2)
                
        except Exception as ex:
            print(f"Erreur Roblox UGC feed {feed}: {ex}")
            continue

# Cache pour éviter de republier les mêmes deals
_deals_cache = {}
_deals_last_check = {}

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎮 CONFIGURATION DES PLATEFORMES DE JEUX
# ═══════════════════════════════════════════════════════════════════════════════

# Mapping CheapShark Store IDs vers nos configs
CHEAPSHARK_STORES = {
    '1': 'steam',
    '2': 'gamersgate',
    '3': 'greenmangaming',
    '7': 'gog',
    '8': 'origin',
    '11': 'humble',
    '13': 'uplay',
    '15': 'fanatical',
    '21': 'wingamestore',
    '23': 'gamebillet',
    '24': 'voidu',
    '25': 'epic',
    '27': 'gamesplanet',
    '28': 'gamesload',
    '29': '2game',
    '30': 'indiegala',
    '31': 'blizzard',
    '33': 'dlgamer',
    '34': 'noctre',
    '35': 'dreamgame',
}

GAME_PLATFORMS = {
    # === PLATEFORMES MAJEURES ===
    'steam': {
        'name': 'Steam',
        'color': 0x1B2838,
        'icon': 'https://store.steampowered.com/favicon.ico',
        'emoji': '🎮',
    },
    'epic': {
        'name': 'Epic Games',
        'color': 0x0078F2,
        'icon': 'https://static-assets-prod.epicgames.com/epic-store/static/favicon.ico',
        'emoji': '🎯',
    },
    'gog': {
        'name': 'GOG',
        'color': 0x86328A,
        'icon': 'https://www.gog.com/favicon.ico',
        'emoji': '🟣',
    },
    'uplay': {
        'name': 'Ubisoft Connect',
        'color': 0x0070FF,
        'icon': 'https://ubistatic3-a.akamaihd.net/orbit/uplay_launcher_3_0/prod/latest/assets/favicon.ico',
        'emoji': '🔵',
    },
    'origin': {
        'name': 'EA App / Origin',
        'color': 0xFF4747,
        'icon': 'https://www.ea.com/favicon.ico',
        'emoji': '🔴',
    },
    'blizzard': {
        'name': 'Battle.net',
        'color': 0x00AEFF,
        'icon': 'https://www.blizzard.com/favicon.ico',
        'emoji': '❄️',
    },
    
    # === REVENDEURS CLÉS OFFICIELLES ===
    'instant': {
        'name': 'Instant Gaming',
        'color': 0xFF6B00,
        'icon': 'https://www.instant-gaming.com/favicon.ico',
        'emoji': '⚡',
    },
    'humble': {
        'name': 'Humble Bundle',
        'color': 0xCC2929,
        'icon': 'https://humblebundle-a.akamaihd.net/static/hashed/47e474bc43d5b4a7.ico',
        'emoji': '❤️',
    },
    'fanatical': {
        'name': 'Fanatical',
        'color': 0xFF5500,
        'icon': 'https://www.fanatical.com/favicon.ico',
        'emoji': '🔥',
    },
    'greenmangaming': {
        'name': 'Green Man Gaming',
        'color': 0x2ECC71,
        'icon': 'https://www.greenmangaming.com/favicon.ico',
        'emoji': '🟢',
    },
    'gamesplanet': {
        'name': 'Gamesplanet',
        'color': 0x3498DB,
        'icon': 'https://www.gamesplanet.com/favicon.ico',
        'emoji': '🌍',
    },
    'gamersgate': {
        'name': 'GamersGate',
        'color': 0x2C3E50,
        'icon': 'https://www.gamersgate.com/favicon.ico',
        'emoji': '🚪',
    },
    'gamebillet': {
        'name': 'GameBillet',
        'color': 0x9B59B6,
        'icon': 'https://www.gamebillet.com/favicon.ico',
        'emoji': '🎫',
    },
    'voidu': {
        'name': 'Voidu',
        'color': 0x1ABC9C,
        'icon': 'https://www.voidu.com/favicon.ico',
        'emoji': '🎪',
    },
    'wingamestore': {
        'name': 'WinGameStore',
        'color': 0x3498DB,
        'icon': 'https://www.wingamestore.com/favicon.ico',
        'emoji': '🏪',
    },
    'indiegala': {
        'name': 'IndieGala',
        'color': 0xE74C3C,
        'icon': 'https://www.indiegala.com/favicon.ico',
        'emoji': '🎭',
    },
    '2game': {
        'name': '2Game',
        'color': 0xF39C12,
        'icon': 'https://2game.com/favicon.ico',
        'emoji': '2️⃣',
    },
    'gamesload': {
        'name': 'Gamesload',
        'color': 0x27AE60,
        'icon': 'https://www.gamesload.com/favicon.ico',
        'emoji': '📥',
    },
    'dlgamer': {
        'name': 'DLGamer',
        'color': 0x8E44AD,
        'icon': 'https://www.dlgamer.com/favicon.ico',
        'emoji': '💾',
    },
    'noctre': {
        'name': 'Noctre',
        'color': 0x2C3E50,
        'icon': 'https://www.noctre.com/favicon.ico',
        'emoji': '🌙',
    },
    'dreamgame': {
        'name': 'DreamGame',
        'color': 0x9B59B6,
        'icon': 'https://www.dreamgame.com/favicon.ico',
        'emoji': '💭',
    },
    
    # === FALLBACK ===
    'unknown': {
        'name': 'Boutique',
        'color': 0x7F8C8D,
        'icon': 'https://cdn-icons-png.flaticon.com/512/3081/3081559.png',
        'emoji': '🛒',
    },
}

async def check_game_deals(session, guild, data):
    """Vérifie les réductions de jeux vidéo sur TOUTES les plateformes via CheapShark API"""
    if not data.get('ads_deals_enabled', False):
        return
    
    channel = guild.get_channel(data.get('ads_deals_channel', 0))
    if not channel:
        return
    
    min_discount = data.get('ads_deals_min_discount', 50)
    
    # Vérifier seulement toutes les 30 minutes par serveur
    cache_key = f"deals_{guild.id}"
    last_check = _deals_last_check.get(cache_key, 0)
    if time.time() - last_check < 1800:  # 30 minutes
        return
    _deals_last_check[cache_key] = time.time()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
    }
    
    deals_posted = 0
    max_deals = 8  # Maximum de deals à poster par vérification
    
    # ═══════════════════════════════════════════════════════════════════════════════
    #                    🎮 API CHEAPSHARK - TOUTES LES PLATEFORMES
    # ═══════════════════════════════════════════════════════════════════════════════
    # CheapShark agrège les deals de : Steam, GOG, Humble, GreenManGaming, Fanatical,
    # GamersGate, Epic Games, Ubisoft, EA/Origin, Blizzard, et bien d'autres !
    
    try:
        # Récupérer les meilleurs deals triés par économie
        cheapshark_url = f"https://www.cheapshark.com/api/1.0/deals?sortBy=Savings&pageSize=30&onSale=1"
        
        async with session.get(cheapshark_url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                print(f"CheapShark API error: {resp.status}")
                return
            
            deals = await resp.json()
        
        for deal in deals:
            if deals_posted >= max_deals:
                break
            
            try:
                # Infos du deal
                game_name = deal.get('title', 'Jeu inconnu')
                store_id = deal.get('storeID', '1')
                deal_id = deal.get('dealID', '')
                
                # Prix
                sale_price = float(deal.get('salePrice', 0))
                normal_price = float(deal.get('normalPrice', 0))
                
                # Calculer la réduction
                if normal_price > 0:
                    discount = int(((normal_price - sale_price) / normal_price) * 100)
                else:
                    discount = 0
                
                # Vérifier si la réduction est suffisante
                if discount < min_discount:
                    continue
                
                # Éviter les doublons
                deal_key = f"cs_{guild.id}_{deal_id}"
                if deal_key in _deals_cache:
                    continue
                _deals_cache[deal_key] = time.time()
                
                # Déterminer la plateforme
                platform_key = CHEAPSHARK_STORES.get(store_id, 'unknown')
                
                # URL du deal (redirige vers la boutique)
                game_url = f"https://www.cheapshark.com/redirect?dealID={deal_id}"
                
                # Image du jeu (via Steam si disponible, sinon CheapShark)
                steam_app_id = deal.get('steamAppID')
                if steam_app_id:
                    image_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{steam_app_id}/header.jpg"
                else:
                    thumb = deal.get('thumb', '')
                    image_url = thumb if thumb.startswith('http') else None
                
                # Score Metacritic si disponible
                metacritic = deal.get('metacriticScore', '0')
                
                # Créer l'embed
                e = await create_deal_embed(
                    platform=platform_key,
                    game_name=game_name,
                    game_url=game_url,
                    image_url=image_url,
                    original_price=normal_price,
                    final_price=sale_price,
                    discount=discount,
                    metacritic=metacritic
                )
                
                await channel.send(embed=e)
                deals_posted += 1
                await asyncio.sleep(2)
                
            except Exception as ex:
                print(f"Erreur deal CheapShark: {ex}")
                continue
    
    except Exception as ex:
        print(f"Erreur CheapShark API: {ex}")
    
    # ═══════════════════════════════════════════════════════════════════════════════
    #                         🎁 EPIC GAMES - JEUX GRATUITS
    # ═══════════════════════════════════════════════════════════════════════════════
    # Epic Games offre des jeux gratuits chaque semaine - on les affiche toujours !
    
    try:
        epic_url = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=fr&country=FR&allowCountries=FR"
        
        async with session.get(epic_url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status == 200:
                epic_data = await resp.json()
                
                games = epic_data.get('data', {}).get('Catalog', {}).get('searchStore', {}).get('elements', [])
                
                for game in games[:3]:
                    if deals_posted >= max_deals:
                        break
                    
                    try:
                        game_name = game.get('title', 'Jeu inconnu')
                        
                        # Vérifier les promotions actives
                        promotions = game.get('promotions')
                        if not promotions:
                            continue
                        
                        promo_offers = promotions.get('promotionalOffers', [])
                        if not promo_offers or not promo_offers[0].get('promotionalOffers'):
                            continue
                        
                        # Vérifier si c'est gratuit
                        price_info = game.get('price', {}).get('totalPrice', {})
                        original_price = price_info.get('originalPrice', 0) / 100
                        final_price = price_info.get('discountPrice', 0) / 100
                        
                        # On veut surtout les jeux gratuits
                        if final_price > 0 and original_price <= 0:
                            continue
                        
                        discount = 100 if final_price == 0 and original_price > 0 else 0
                        if discount == 0:
                            discount = int((1 - final_price / original_price) * 100) if original_price > 0 else 0
                        
                        if discount < min_discount:
                            continue
                        
                        # Slug pour l'URL
                        slug = game.get('productSlug') or game.get('urlSlug') or game.get('catalogNs', {}).get('mappings', [{}])[0].get('pageSlug', '')
                        if not slug or slug == '[]':
                            continue
                        
                        deal_key = f"epic_{guild.id}_{slug}"
                        if deal_key in _deals_cache:
                            continue
                        _deals_cache[deal_key] = time.time()
                        
                        game_url = f"https://store.epicgames.com/fr/p/{slug}"
                        
                        # Image
                        images = game.get('keyImages', [])
                        image_url = None
                        for img in images:
                            if img.get('type') in ['OfferImageWide', 'DieselStoreFrontWide', 'Thumbnail', 'VaultClosed']:
                                image_url = img.get('url')
                                break
                        if not image_url and images:
                            image_url = images[0].get('url')
                        
                        e = await create_deal_embed(
                            platform='epic',
                            game_name=game_name,
                            game_url=game_url,
                            image_url=image_url,
                            original_price=original_price,
                            final_price=final_price,
                            discount=discount
                        )
                        
                        await channel.send(embed=e)
                        deals_posted += 1
                        await asyncio.sleep(2)
                        
                    except Exception as ex:
                        continue
                        
    except Exception as ex:
        print(f"Erreur Epic Games: {ex}")
    
    # Nettoyer le cache périodiquement (garder 24h)
    current_time = time.time()
    keys_to_remove = [k for k, v in _deals_cache.items() if current_time - v > 86400]
    for k in keys_to_remove:
        del _deals_cache[k]

async def create_deal_embed(platform: str, game_name: str, game_url: str, image_url: str, original_price: float, final_price: float, discount: int, metacritic: str = None):
    """Crée un embed uniforme et beau pour les deals de jeux"""
    
    plat = GAME_PLATFORMS.get(platform, GAME_PLATFORMS.get('unknown', GAME_PLATFORMS['steam']))
    
    e = discord.Embed(color=plat['color'])
    
    # ═══════════════════════════════════════════════════════════════════════════════
    #                         🎮 DESIGN ÉPURÉ ET PROFESSIONNEL
    # ═══════════════════════════════════════════════════════════════════════════════
    
    # Header avec la plateforme
    e.set_author(
        name=f"{plat['emoji']} {plat['name'].upper()} • PROMOTION",
        icon_url=plat.get('icon')
    )
    
    # Titre = Nom du jeu (bien visible)
    e.title = f"🎮 {game_name}"
    e.url = game_url
    
    # Image du jeu - GRANDE et bien visible
    if image_url:
        e.set_image(url=image_url)
    
    # ═══════════════ AFFICHAGE DES PRIX ═══════════════
    
    # Badge de réduction avec style selon le pourcentage
    if discount >= 90:
        discount_badge = f"🔥🔥 **-{discount}%** 🔥🔥"
    elif discount >= 75:
        discount_badge = f"🔥 **-{discount}%** 🔥"
    elif discount >= 50:
        discount_badge = f"⭐ **-{discount}%**"
    else:
        discount_badge = f"**-{discount}%**"
    
    # Prix formaté
    if final_price == 0:
        price_display = f"~~{original_price:.2f}€~~\n## **GRATUIT** 🎁"
    else:
        price_display = f"~~{original_price:.2f}€~~\n## **{final_price:.2f}€**"
    
    # Économie
    savings = original_price - final_price
    
    # Affichage en colonnes
    e.add_field(name="💰 Prix", value=price_display, inline=True)
    e.add_field(name="🔻 Réduction", value=discount_badge, inline=True)
    
    if savings > 0:
        e.add_field(name="💵 Économie", value=f"**{savings:.2f}€**", inline=True)
    
    # Score Metacritic si disponible
    if metacritic and metacritic not in ['0', '']:
        try:
            score = int(metacritic)
            if score >= 75:
                score_emoji = "🟢"
            elif score >= 50:
                score_emoji = "🟡"
            else:
                score_emoji = "🔴"
            e.add_field(name="📊 Metacritic", value=f"{score_emoji} **{score}/100**", inline=True)
        except:
            pass
    
    # Lien d'achat - TRÈS VISIBLE
    e.add_field(
        name="",
        value=f"### [{plat['emoji']} Acheter sur {plat['name']}]({game_url})",
        inline=False
    )
    
    # Footer avec plateforme
    e.set_footer(
        text=f"{plat['name']} • Offre limitée",
        icon_url=plat['icon']
    )
    e.timestamp = now()
    
    return e

@check_social_feeds.before_loop
async def before_social_check():
    await bot.wait_until_ready()

# Mise à jour activité sur vocal + Vocaux Temporaires
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    guild_id = member.guild.id
    user_id = member.id
    key = (guild_id, user_id)
    
    # ═══════════════ VOCAUX TEMPORAIRES (MULTI-HUBS) ═══════════════
    try:
        c = await cfg(guild_id)
        voice_cfg = c.get('temp_voice_config', {})
        
        if voice_cfg.get('enabled', False):
            hubs = voice_cfg.get('hubs', {})
            perms = voice_cfg.get('owner_permissions', {
                'can_rename': True, 'can_limit': True, 'can_mute': True, 'can_kick': True
            })
            
            # Vérifier si l'utilisateur rejoint un des hubs configurés
            if after.channel:
                hub_data = hubs.get(str(after.channel.id))
                
                if hub_data:
                    # C'est un hub configuré !
                    cat_id = hub_data.get('category', 0)
                    required_role_id = hub_data.get('required_role', 0)
                    default_name = hub_data.get('default_name', '🔊 Vocal de {user}')
                    
                    # Vérifier si le membre a le rôle requis (si défini)
                    if required_role_id:
                        required_role = member.guild.get_role(required_role_id)
                        if required_role and required_role not in member.roles:
                            # Le membre n'a pas le rôle requis → le déconnecter
                            try:
                                await member.move_to(None)
                                # Envoyer un message privé expliquant pourquoi
                                try:
                                    await member.send(
                                        f"❌ Vous ne pouvez pas créer de vocal dans ce hub.\n"
                                        f"🔒 Rôle requis: **{required_role.name}**\n"
                                        f"📍 Serveur: {member.guild.name}"
                                    )
                                except:
                                    pass  # DM désactivés
                                print(f"[TEMP VOICE] {member.display_name} expulsé du hub (rôle manquant: {required_role.name})")
                            except:
                                pass
                            return
                    
                    # Le membre peut créer un vocal
                    category = member.guild.get_channel(cat_id)
                    if category:
                        channel_name = default_name.replace('{user}', member.display_name)[:50]
                        
                        # Récupérer le rôle requis pour les permissions
                        required_role = member.guild.get_role(required_role_id) if required_role_id else None
                        
                        # Permissions de base
                        overwrites = {}
                        
                        if required_role:
                            # ═══ VOCAL RESTREINT AU RÔLE ═══
                            # @everyone ne peut PAS voir ni rejoindre le vocal
                            overwrites[member.guild.default_role] = discord.PermissionOverwrite(
                                view_channel=False,  # ❌ Invisible pour ceux sans le rôle
                                connect=False,
                                speak=False
                            )
                            
                            # Le rôle requis PEUT voir et rejoindre le vocal
                            overwrites[required_role] = discord.PermissionOverwrite(
                                view_channel=True,   # ✅ Visible pour ceux avec le rôle
                                connect=True,
                                speak=True,
                                use_voice_activation=True,
                                stream=True,
                                send_messages=False,
                                read_messages=True
                            )
                        else:
                            # ═══ VOCAL PUBLIC ═══
                            # @everyone peut voir et rejoindre
                            overwrites[member.guild.default_role] = discord.PermissionOverwrite(
                                view_channel=True,
                                connect=True,
                                speak=True,
                                use_voice_activation=True,
                                stream=True,
                                send_messages=False,
                                read_messages=True
                            )
                        
                        # Le propriétaire a toutes les permissions
                        overwrites[member] = discord.PermissionOverwrite(
                            view_channel=True,
                            connect=True,
                            speak=True,
                            use_voice_activation=True,
                            stream=True,
                            send_messages=False,
                            read_messages=True,
                            mute_members=perms.get('can_mute', True),
                            move_members=perms.get('can_kick', True),
                            manage_channels=perms.get('can_rename', True) or perms.get('can_limit', True)
                        )
                        
                        # Le bot a toutes les permissions
                        overwrites[member.guild.me] = discord.PermissionOverwrite(
                            view_channel=True,
                            connect=True,
                            speak=True,
                            manage_channels=True,
                            move_members=True,
                            send_messages=True
                        )
                        
                        new_channel = await member.guild.create_voice_channel(
                            name=channel_name,
                            category=category,
                            overwrites=overwrites
                        )
                        
                        temp_voice_channels[new_channel.id] = {
                            'owner': member.id,
                            'hub_id': after.channel.id,
                            'created_at': now()
                        }
                        
                        await member.move_to(new_channel)
                        print(f"[TEMP VOICE] Créé vocal '{channel_name}' pour {member.display_name} (hub: {after.channel.name})")
            
            # Si l'utilisateur quitte un vocal temporaire → vérifier si vide et supprimer
            if before.channel and before.channel.id in temp_voice_channels:
                await asyncio.sleep(1)
                
                try:
                    channel = member.guild.get_channel(before.channel.id)
                    if channel and len(channel.members) == 0:
                        await channel.delete(reason="Vocal temporaire vide")
                        del temp_voice_channels[before.channel.id]
                        print(f"[TEMP VOICE] Supprimé vocal vide: {before.channel.name}")
                except discord.NotFound:
                    if before.channel.id in temp_voice_channels:
                        del temp_voice_channels[before.channel.id]
                except Exception as ex:
                    print(f"[TEMP VOICE] Erreur suppression: {ex}")
                    
    except Exception as ex:
        print(f"Erreur temp voice: {ex}")
    
    # ═══════════════ TRACKING ACTIVITÉ VOCALE ═══════════════
    try:
        # Cas 1: L'utilisateur REJOINT un vocal (était pas en vocal ou change de salon)
        if after.channel and (before.channel is None or before.channel.id != after.channel.id):
            print(f"[VOCAL] {member.display_name} rejoint {after.channel.name}")
            
            # Enregistrer l'heure de connexion
            voice_join_tracker[key] = now()
            
            # Mettre à jour last_vocal et redonner le rôle si configuré
            await track_member_vocal_join(member, after.channel)
            await update_realsy_activity(guild_id, user_id)
        
        # Cas 2: L'utilisateur QUITTE un vocal (quitte complètement ou change de salon)
        if before.channel and (after.channel is None or before.channel.id != after.channel.id):
            print(f"[VOCAL] {member.display_name} quitte {before.channel.name}")
            
            # Calculer le temps passé
            join_time = voice_join_tracker.pop(key, None)
            if join_time:
                duration = int((now() - join_time).total_seconds())
                print(f"[VOCAL] Durée: {duration} secondes")
                if duration > 0:
                    await track_member_vocal_leave(member, before.channel, duration)
            else:
                print(f"[VOCAL] Pas de join_time trouvé pour {member.display_name}")
    except Exception as ex:
        print(f"Erreur tracking vocal: {ex}")

async def track_member_message(msg):
    """Enregistre un message dans le tracking d'activité"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour activity_tracking
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_message, total_messages)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_message = ?,
                    total_messages = total_messages + 1
            ''', (msg.guild.id, msg.author.id, now_str, now_str))
            
            # Enregistrer dans member_activity pour les stats détaillées
            await db.execute('''
                INSERT INTO member_activity (guild_id, user_id, activity_type, channel_id, message_id, created_at)
                VALUES (?, ?, 'message', ?, ?, ?)
            ''', (msg.guild.id, msg.author.id, msg.channel.id, msg.id, now_str))
            
            await db.commit()
        
        # ═══════════════ NOUVEAU SYSTÈME DE NIVEAUX ═══════════════
        try:
            c = await cfg(msg.guild.id)
            level_cfg = c.get('level_config', {})
            
            # Vérifier si le système est activé
            if not level_cfg.get('enabled', False):
                return
            
            # ═══════════════ VÉRIFIER SI LE SALON EST AUTORISÉ ═══════════════
            xp_text_channels = level_cfg.get('xp_text_channels', [])
            if xp_text_channels and msg.channel.id not in xp_text_channels:
                return  # Salon non autorisé, pas de gains
            
            # Ajouter de l'XP
            xp_per_msg = level_cfg.get('xp_per_message', 15)
            if xp_per_msg > 0:
                new_level = await add_xp(msg.guild.id, msg.author.id, xp_per_msg)
                
                # Si level up
                if new_level:
                    # Annoncer le level up
                    levelup_ch_id = level_cfg.get('levelup_channel', 0)
                    levelup_ch = msg.guild.get_channel(levelup_ch_id) if levelup_ch_id else msg.channel
                    
                    e = discord.Embed(title="🎉 Level Up !", color=0xF1C40F)
                    e.description = f"{msg.author.mention} est passé au **niveau {new_level}** !"
                    e.set_thumbnail(url=msg.author.display_avatar.url if msg.author.display_avatar else None)
                    
                    try:
                        await levelup_ch.send(embed=e, delete_after=30)
                    except:
                        pass
                    
                    # Vérifier les récompenses de niveau
                    async with aiosqlite.connect(DB_PATH) as db:
                        async with db.execute('SELECT role_id FROM level_rewards WHERE guild_id=? AND level=?', (msg.guild.id, new_level)) as cursor:
                            row = await cursor.fetchone()
                            if row:
                                role = msg.guild.get_role(row[0])
                                if role:
                                    try:
                                        await msg.author.add_roles(role, reason=f"Récompense niveau {new_level}")
                                    except:
                                        pass
            
            # Ajouter des pièces (basé sur le nombre de messages)
            coins_per_messages = level_cfg.get('coins_per_messages', 1)
            coins_amount = level_cfg.get('coins_amount', 1)
            
            if coins_per_messages > 0 and coins_amount > 0:
                # Récupérer le compteur de messages pour les pièces
                eco = await get_user_economy(msg.guild.id, msg.author.id)
                msg_count = eco.get('message_count', 0) + 1
                
                if msg_count >= coins_per_messages:
                    # Donner les pièces et réinitialiser le compteur
                    await add_coins(msg.guild.id, msg.author.id, coins_amount)
                    await update_user_economy(msg.guild.id, msg.author.id, message_count=0)
                else:
                    # Incrémenter le compteur
                    await update_user_economy(msg.guild.id, msg.author.id, message_count=msg_count)
        except Exception as ex:
            print(f"Erreur level system: {ex}")
    except:
        pass

async def handle_recovery_message(msg, stat_cfg):
    """Gère un message dans le salon de récupération - supprime le message et redonne le rôle"""
    try:
        role_id = stat_cfg.get('activity_role', 0)
        
        role = msg.guild.get_role(role_id) if role_id else None
        
        # ═══════════════ ÉTAPE 1: METTRE À JOUR L'ACTIVITÉ EN PREMIER ═══════════════
        now_str = now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_message, total_messages)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_message = ?,
                    total_messages = total_messages + 1
            ''', (msg.guild.id, msg.author.id, now_str, now_str))
            await db.commit()
        
        # ═══════════════ ÉTAPE 2: REDONNER LE RÔLE ═══════════════
        if role and role not in msg.author.roles:
            try:
                await msg.author.add_roles(role, reason="Récupération d'activité via salon dédié")
            except:
                pass
        
        # ═══════════════ ÉTAPE 3: SUPPRIMER LE MESSAGE ═══════════════
        try:
            await msg.delete()
        except:
            pass
        
        # Pas de notification - silencieux
        
    except Exception as ex:
        print(f"Erreur handle_recovery_message: {ex}")

async def track_member_vocal_join(member, channel):
    """Enregistre une connexion vocale"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour last_vocal
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_vocal)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_vocal = ?
            ''', (member.guild.id, member.id, now_str, now_str))
            
            await db.commit()
        
        # Redonner le rôle d'activité si configuré
        await restore_activity_role(member)
        
    except Exception as ex:
        print(f"Erreur track vocal join: {ex}")

async def track_member_vocal_leave(member, channel, duration):
    """Enregistre le temps passé en vocal et donne XP/pièces"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour le temps total en vocal
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, total_vocal_time)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    total_vocal_time = COALESCE(total_vocal_time, 0) + ?
            ''', (member.guild.id, member.id, duration, duration))
            
            # Enregistrer la session vocale
            await db.execute('''
                INSERT INTO member_activity (guild_id, user_id, activity_type, channel_id, duration, created_at)
                VALUES (?, ?, 'vocal', ?, ?, ?)
            ''', (member.guild.id, member.id, channel.id, duration, now_str))
            
            await db.commit()
            print(f"[VOCAL DB] Enregistré {duration}s pour {member.display_name} dans {channel.name}")
        
        # ═══════════════ XP ET PIÈCES VOCAUX ═══════════════
        try:
            c = await cfg(member.guild.id)
            level_cfg = c.get('level_config', {})
            
            if level_cfg.get('enabled', False) and duration > 0:
                # ═══════════════ VÉRIFIER SI LE SALON EST AUTORISÉ ═══════════════
                xp_voice_channels = level_cfg.get('xp_voice_channels', [])
                if xp_voice_channels and channel.id not in xp_voice_channels:
                    print(f"[VOCAL] Salon {channel.name} non autorisé pour XP/pièces")
                    return  # Salon non autorisé, pas de gains
                
                # Fonction pour convertir la durée selon l'unité
                def get_units(seconds, unit):
                    if unit == 'minute':
                        return seconds // 60
                    elif unit == 'hour':
                        return seconds // 3600
                    elif unit == 'day':
                        return seconds // 86400
                    return seconds // 60  # Par défaut en minutes
                
                # XP Vocal
                xp_per_vocal = level_cfg.get('xp_per_vocal', level_cfg.get('xp_per_vocal_minute', 5))
                xp_vocal_unit = level_cfg.get('xp_vocal_unit', 'minute')
                xp_units = get_units(duration, xp_vocal_unit)
                
                if xp_units > 0 and xp_per_vocal > 0:
                    total_xp = xp_units * xp_per_vocal
                    print(f"[VOCAL XP] {member.display_name}: {xp_units} {xp_vocal_unit}s x {xp_per_vocal} = {total_xp} XP")
                    new_level = await add_xp(member.guild.id, member.id, total_xp)
                    
                    # Si level up
                    if new_level:
                        levelup_ch_id = level_cfg.get('levelup_channel', 0)
                        levelup_ch = member.guild.get_channel(levelup_ch_id) if levelup_ch_id else None
                        
                        if levelup_ch:
                            e = discord.Embed(title="🎉 Level Up !", color=0xF1C40F)
                            e.description = f"{member.mention} est passé au **niveau {new_level}** !"
                            e.set_footer(text=f"🎤 Temps en vocal: {duration // 60} min")
                            try:
                                await levelup_ch.send(embed=e, delete_after=30)
                            except:
                                pass
                        
                        # Vérifier les récompenses de niveau
                        async with aiosqlite.connect(DB_PATH) as db:
                            async with db.execute('SELECT role_id FROM level_rewards WHERE guild_id=? AND level=?', (member.guild.id, new_level)) as cursor:
                                row = await cursor.fetchone()
                                if row:
                                    role = member.guild.get_role(row[0])
                                    if role:
                                        try:
                                            await member.add_roles(role, reason=f"Récompense niveau {new_level}")
                                        except:
                                            pass
                
                # Pièces Vocal
                coins_per_vocal = level_cfg.get('coins_per_vocal', level_cfg.get('coins_per_vocal_minute', 1))
                coins_vocal_unit = level_cfg.get('coins_vocal_unit', 'minute')
                coins_units = get_units(duration, coins_vocal_unit)
                
                if coins_units > 0 and coins_per_vocal > 0:
                    total_coins = coins_units * coins_per_vocal
                    print(f"[VOCAL COINS] {member.display_name}: {coins_units} {coins_vocal_unit}s x {coins_per_vocal} = {total_coins} pièces")
                    await add_coins(member.guild.id, member.id, total_coins)
        except Exception as ex:
            print(f"Erreur XP/coins vocal: {ex}")
            
    except Exception as ex:
        print(f"Erreur track vocal leave: {ex}")

async def restore_activity_role(member):
    """Redonne le rôle d'activité si le membre rejoint un vocal"""
    try:
        c = await cfg(member.guild.id)
        stat_cfg = c.get('stat_config', {})
        role_id = stat_cfg.get('activity_role', 0)
        
        if not role_id:
            return
        
        role = member.guild.get_role(role_id)
        if not role:
            return
        
        # ═══════════════ ENREGISTRER L'ACTIVITÉ ═══════════════
        now_str = now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_vocal)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_vocal = ?
            ''', (member.guild.id, member.id, now_str, now_str))
            await db.commit()
        
        # Redonner le rôle silencieusement
        if role not in member.roles:
            try:
                await member.add_roles(role, reason="Retour d'activité via vocal")
            except:
                pass
                
    except Exception as ex:
        print(f"Erreur restore role: {ex}")

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎁 TÂCHE AUTOMATIQUE GIVEAWAYS
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(seconds=30)
async def check_giveaways():
    """Vérifie et termine les giveaways expirés"""
    try:
        now_dt = now()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Récupérer les giveaways à terminer
            async with db.execute(
                'SELECT id, guild_id, channel_id, message_id, title, prize, participants FROM giveaways WHERE ended=0 AND end_time <= ?',
                (now_dt.isoformat(),)
            ) as cursor:
                giveaways_to_end = []
                async for row in cursor:
                    giveaways_to_end.append(row)
            
            # Terminer chaque giveaway
            for gw_id, guild_id, channel_id, message_id, title, prize, participants_str in giveaways_to_end:
                try:
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                    
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue
                    
                    participants = json.loads(participants_str) if participants_str else []
                    
                    # Marquer comme terminé
                    await db.execute('UPDATE giveaways SET ended=1 WHERE id=?', (gw_id,))
                    
                    if not participants:
                        # Pas de participants
                        e = discord.Embed(title=f"🎁 {title} - Terminé", color=C.RED)
                        e.description = "❌ **Aucun participant !**\n\nLe cadeau n'a pas pu être attribué."
                        e.timestamp = now()
                        
                        try:
                            msg = await channel.fetch_message(message_id)
                            await msg.edit(embed=e, view=None)
                        except:
                            pass
                    else:
                        # Tirer un gagnant
                        import random
                        winner_id = random.choice(participants)
                        winner = guild.get_member(winner_id)
                        
                        e = discord.Embed(title=f"🎁 {title} - Terminé !", color=C.GOLD)
                        e.description = f"🎉 **FÉLICITATIONS !**\n\n🏆 Le gagnant est: **{winner.mention if winner else f'<@{winner_id}>'}**"
                        e.add_field(name="🎁 Prix", value=f"```{prize}```", inline=False)
                        e.add_field(name="👥 Participants", value=f"```{len(participants)}```", inline=True)
                        e.set_footer(text="Merci à tous les participants !")
                        e.timestamp = now()
                        
                        try:
                            msg = await channel.fetch_message(message_id)
                            await msg.edit(embed=e, view=None)
                            await channel.send(f"🎉 **{winner.mention if winner else f'<@{winner_id}>'}** a gagné **{title}** !")
                        except:
                            pass
                    
                except Exception as ex:
                    print(f"Erreur fin giveaway {gw_id}: {ex}")
            
            await db.commit()
            
    except Exception as ex:
        print(f"Erreur tâche giveaways: {ex}")

@check_giveaways.before_loop
async def before_check_giveaways():
    await bot.wait_until_ready()

# ═══════════════════════════════════════════════════════════════════════════════
#                           📨 TÂCHE AUTOMATIQUE MESSAGES PROGRAMMÉS
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=1)
async def check_scheduled_messages():
    """Vérifie et envoie les messages programmés"""
    try:
        now_dt = now()
        current_hour = now_dt.hour
        current_minute = now_dt.minute
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Récupérer tous les messages actifs
            async with db.execute(
                'SELECT id, guild_id, channel_id, title, description, color, image_url, footer, frequency, frequency_value, send_hour, send_minute, last_sent FROM scheduled_messages WHERE enabled=1'
            ) as cursor:
                messages = []
                async for row in cursor:
                    messages.append(row)
            
            for msg_id, guild_id, channel_id, title, description, color, image_url, footer, frequency, freq_val, send_hour, send_minute, last_sent_str in messages:
                try:
                    # Vérifier si c'est l'heure d'envoyer
                    if current_hour != send_hour:
                        continue
                    
                    # Vérifier le dernier envoi
                    if last_sent_str:
                        try:
                            last_sent = datetime.fromisoformat(last_sent_str)
                            
                            # Calculer l'intervalle minimum
                            if frequency == 'minutes':
                                min_interval = timedelta(minutes=freq_val)
                            elif frequency == 'hourly':
                                min_interval = timedelta(hours=freq_val)
                            elif frequency == 'daily':
                                min_interval = timedelta(days=freq_val)
                            elif frequency == 'weekly':
                                min_interval = timedelta(weeks=freq_val)
                            else:
                                continue
                            
                            # Si pas assez de temps écoulé, passer
                            if now_dt - last_sent < min_interval:
                                continue
                        except:
                            pass
                    
                    # Envoyer le message
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                    
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue
                    
                    # Créer l'embed
                    try:
                        embed_color = int(color.replace('#', ''), 16) if color else C.BLURPLE
                    except:
                        embed_color = C.BLURPLE
                    
                    e = discord.Embed(title=title, description=description, color=embed_color)
                    
                    if image_url:
                        e.set_image(url=image_url)
                    
                    if footer:
                        e.set_footer(text=footer)
                    
                    e.timestamp = now()
                    
                    await channel.send(embed=e)
                    
                    # Mettre à jour last_sent
                    await db.execute(
                        'UPDATE scheduled_messages SET last_sent=? WHERE id=?',
                        (now_dt.isoformat(), msg_id)
                    )
                    
                except Exception as ex:
                    print(f"Erreur message programmé {msg_id}: {ex}")
            
            await db.commit()
            
    except Exception as ex:
        print(f"Erreur tâche messages programmés: {ex}")

@check_scheduled_messages.before_loop
async def before_check_scheduled_messages():
    await bot.wait_until_ready()

# ═══════════════════════════════════════════════════════════════════════════════
#                           📈 COMMANDES NIVEAU & BOUTIQUE
# ═══════════════════════════════════════════════════════════════════════════════

async def check_level_channel(i):
    """Vérifie si la commande peut être utilisée dans ce salon"""
    c = await cfg(i.guild.id)
    level_cfg = c.get('level_config', {})
    allowed = level_cfg.get('allowed_channels', [])
    
    if allowed and i.channel.id not in allowed:
        mentions = ", ".join([f"<#{ch}>" for ch in allowed[:3]])
        await i.response.send_message(f"❌ Cette commande n'est utilisable que dans: {mentions}", ephemeral=True)
        return False
    return True

def create_progress_bar(current, total, length=20):
    """Crée une barre de progression visuelle"""
    filled = int(length * current / total) if total > 0 else 0
    empty = length - filled
    return "█" * filled + "░" * empty

@bot.tree.command(name="level", description="📈 Voir votre progression de niveau")
@app_commands.describe(membre="Le membre dont vous voulez voir le niveau")
async def level_cmd(i: discord.Interaction, membre: discord.Member = None):
    # Vérifier le salon
    if not await check_level_channel(i):
        return
    
    # Vérifier si le système est activé
    c = await cfg(i.guild.id)
    level_cfg = c.get('level_config', {})
    if not level_cfg.get('enabled', False):
        return await i.response.send_message("❌ Le système de niveaux n'est pas activé", ephemeral=True)
    
    target = membre or i.user
    eco = await get_user_economy(i.guild.id, target.id)
    
    current_level = eco['level']
    current_xp = eco['xp']
    xp_for_next = current_level * 100  # XP requis pour le niveau actuel
    xp_progress = current_xp % 100 if current_level > 1 else current_xp  # XP vers le prochain niveau
    xp_needed = 100  # XP nécessaire pour chaque niveau
    
    progress_bar = create_progress_bar(xp_progress, xp_needed)
    percentage = int((xp_progress / xp_needed) * 100) if xp_needed > 0 else 0
    
    e = discord.Embed(title=f"📈 Niveau de {target.display_name}", color=0x9B59B6)
    e.add_field(name="🏆 Niveau", value=f"**{current_level}**", inline=True)
    e.add_field(name="✨ XP Total", value=f"**{current_xp}**", inline=True)
    e.add_field(name="🪙 Pièces", value=f"**{eco['coins']}**", inline=True)
    
    e.add_field(
        name=f"📊 Progression ({percentage}%)",
        value=f"`{progress_bar}` {xp_progress}/{xp_needed}",
        inline=False
    )
    
    # Prochain rôle de niveau
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT level, role_id FROM level_rewards WHERE guild_id=? AND level > ? ORDER BY level LIMIT 1',
            (i.guild.id, current_level)
        ) as cursor:
            next_reward = await cursor.fetchone()
    
    if next_reward:
        role = i.guild.get_role(next_reward[1])
        if role:
            e.add_field(name="🎁 Prochain rôle", value=f"Niveau {next_reward[0]} → {role.mention}", inline=False)
    
    e.set_thumbnail(url=target.display_avatar.url)
    e.set_footer(text=f"XP par message: {level_cfg.get('xp_per_message', 15)}")
    
    await i.response.send_message(embed=e)

@bot.tree.command(name="shop", description="🛒 Ouvrir la boutique")
async def shop_cmd(i: discord.Interaction):
    # Vérifier le salon
    if not await check_level_channel(i):
        return
    
    # Vérifier si le système est activé
    c = await cfg(i.guild.id)
    level_cfg = c.get('level_config', {})
    if not level_cfg.get('enabled', False):
        return await i.response.send_message("❌ Le système de niveaux n'est pas activé", ephemeral=True)
    
    shop_items = level_cfg.get('shop_items', [])
    if not shop_items:
        return await i.response.send_message("❌ La boutique est vide", ephemeral=True)
    
    eco = await get_user_economy(i.guild.id, i.user.id)
    
    e = discord.Embed(title="🛒 Boutique", color=0xE67E22)
    e.description = f"💰 Vos pièces: **{eco['coins']}** 🪙\n\nSélectionnez un article à acheter:"
    
    for idx, item in enumerate(shop_items[:10]):
        role = i.guild.get_role(item.get('role_id', 0))
        price = item.get('price', 0)
        duration = item.get('duration', 3600)
        dur_txt = format_duration(duration)
        
        can_afford = "✅" if eco['coins'] >= price else "❌"
        e.add_field(
            name=f"{can_afford} {role.name if role else '?'}",
            value=f"**{price}** 🪙 • Durée: {dur_txt}",
            inline=True
        )
    
    # Créer la vue avec le sélecteur
    view = ShopPurchaseView(i.user, i.guild, shop_items, eco['coins'])
    
    await i.response.send_message(embed=e, view=view, ephemeral=True)

class ShopPurchaseView(View):
    def __init__(self, user, guild, items, coins):
        super().__init__(timeout=120)
        self.user = user
        self.guild = guild
        self.items = items
        self.coins = coins
        
        # Créer les options
        opts = []
        for idx, item in enumerate(items[:25]):
            role = guild.get_role(item.get('role_id', 0))
            price = item.get('price', 0)
            duration = item.get('duration', 3600)
            dur_txt = format_duration(duration)
            
            can_afford = coins >= price
            emoji = "✅" if can_afford else "❌"
            
            opts.append(discord.SelectOption(
                label=f"{role.name if role else '?'} - {price} 🪙"[:25],
                value=str(idx),
                description=f"Durée: {dur_txt}" + (" (pas assez)" if not can_afford else ""),
                emoji=emoji
            ))
        
        if opts:
            select = Select(placeholder="Choisir un article...", options=opts)
            select.callback = self.purchase_callback
            self.add_item(select)
    
    async def purchase_callback(self, i: discord.Interaction):
        if i.user.id != self.user.id:
            return await i.response.send_message("❌ Ce n'est pas votre boutique", ephemeral=True)
        
        idx = int(i.data['values'][0])
        if idx >= len(self.items):
            return await i.response.send_message("❌ Article invalide", ephemeral=True)
        
        item = self.items[idx]
        price = item.get('price', 0)
        duration = item.get('duration', 3600)
        role_id = item.get('role_id', 0)
        
        # Vérifier les pièces
        eco = await get_user_economy(self.guild.id, i.user.id)
        if eco['coins'] < price:
            return await i.response.send_message(f"❌ Vous n'avez pas assez de pièces ({eco['coins']}/{price})", ephemeral=True)
        
        role = self.guild.get_role(role_id)
        if not role:
            return await i.response.send_message("❌ Rôle introuvable", ephemeral=True)
        
        # Retirer les pièces
        await add_coins(self.guild.id, i.user.id, -price)
        
        # Donner le rôle
        try:
            await i.user.add_roles(role, reason=f"Achat boutique - {price} pièces")
        except:
            # Rembourser si erreur
            await add_coins(self.guild.id, i.user.id, price)
            return await i.response.send_message("❌ Impossible d'ajouter le rôle", ephemeral=True)
        
        # Enregistrer l'achat pour retrait automatique
        expires_at = now() + timedelta(seconds=duration)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO shop_purchases (guild_id, user_id, role_id, expires_at) VALUES (?, ?, ?, ?)',
                (self.guild.id, i.user.id, role_id, expires_at.isoformat())
            )
            await db.commit()
        
        dur_txt = format_duration(duration)
        e = discord.Embed(title="✅ Achat réussi !", color=0x2ECC71)
        e.description = f"Vous avez acheté {role.mention} pour **{price}** 🪙\n\n⏱️ Ce rôle expirera dans **{dur_txt}**"
        
        await i.response.edit_message(embed=e, view=None)

# Tâche pour retirer les rôles expirés
@tasks.loop(minutes=1)
async def check_expired_roles():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Récupérer les achats expirés
            async with db.execute(
                'SELECT id, guild_id, user_id, role_id FROM shop_purchases WHERE expires_at < ?',
                (now_str,)
            ) as cursor:
                expired = await cursor.fetchall()
            
            for purchase_id, guild_id, user_id, role_id in expired:
                try:
                    guild = bot.get_guild(guild_id)
                    if guild:
                        member = guild.get_member(user_id)
                        role = guild.get_role(role_id)
                        
                        if member and role and role in member.roles:
                            await member.remove_roles(role, reason="Rôle boutique expiré")
                except:
                    pass
                
                # Supprimer l'entrée
                await db.execute('DELETE FROM shop_purchases WHERE id=?', (purchase_id,))
            
            await db.commit()
    except:
        pass

@check_expired_roles.before_loop
async def before_check_expired():
    await bot.wait_until_ready()

@bot.tree.command(name="leaderboard", description="🏆 Voir le classement des plus riches")
async def leaderboard_cmd(i: discord.Interaction):
    # Vérifier si l'économie est activée
    c = await cfg(i.guild.id)
    games_cfg = c.get('minigames_config', {})
    if not games_cfg.get('economy_enabled', False):
        return await i.response.send_message("❌ L'économie n'est pas activée sur ce serveur", ephemeral=True)
    
    # Récupérer le top 10
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT user_id, coins, bank, level FROM economy WHERE guild_id=? ORDER BY (coins + bank) DESC LIMIT 10',
            (i.guild.id,)
        ) as cursor:
            rows = await cursor.fetchall()
    
    if not rows:
        return await i.response.send_message("❌ Aucune donnée disponible", ephemeral=True)
    
    e = discord.Embed(title="🏆 Classement des plus riches", color=0xF1C40F)
    
    desc = ""
    medals = ["🥇", "🥈", "🥉"]
    for idx, (user_id, coins, bank, level) in enumerate(rows):
        member = i.guild.get_member(user_id)
        name = member.display_name if member else f"User {user_id}"
        medal = medals[idx] if idx < 3 else f"**{idx + 1}.**"
        total = coins + bank
        desc += f"{medal} **{name}** - {total} 🪙 (Nv.{level})\n"
    
    e.description = desc
    e.set_footer(text=f"Demandé par {i.user.display_name}")
    
    await i.response.send_message(embed=e)


if __name__ == "__main__":
    print("🚀 Bot v27.5 - Démarrage...")
    print("🔒 Système de sécurité activé")
    print("👑 Système d'immunités complet")
    print("🎙️ Vocaux temporaires multi-hubs")
    print("🛡️ Anti-badwords amélioré (mots entiers)")
    bot.run(TOKEN)

