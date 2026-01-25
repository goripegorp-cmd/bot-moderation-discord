# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v9.5 🌟                                 ║
# ║     Anti-Image Corrigé + Anti-Badwords Anti-Contournement                     ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button, Select, Modal, TextInput
import aiosqlite
import os
import re
import json
import asyncio
import unicodedata
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
DB_PATH = os.getenv('DB_PATH', '/data/database.db')
if not os.path.exists('/data'): DB_PATH = 'database.db'

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}
mention_tracker = {}

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PINK=0xEB459E; PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22

PHISHING_DOMAINS = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com','discordi.gift','discord-app.com','discordapp.co','discrod.com','dlscord.org','discordc.gift','discord-airdrop.com','steamcommunity.ru','steamcommunitiy.com','store-steampowered.com']
SCAM_PATTERNS = [r'free\s*nitro',r'discord\s*nitro\s*free',r'steam\s*gift',r'claim\s*your\s*gift',r'@everyone.*http',r'won\s*a?\s*nitro']

# Caractères de substitution pour anti-contournement
LEET_MAP = {
    'a': ['a', '@', '4', 'α', 'à', 'á', 'â', 'ã', 'ä', 'å', 'ā', 'ă', 'ą'],
    'b': ['b', '8', 'ß', 'β'],
    'c': ['c', '(', '<', '¢', 'ç', 'ć', 'č'],
    'd': ['d', 'đ'],
    'e': ['e', '3', '€', 'è', 'é', 'ê', 'ë', 'ē', 'ė', 'ę', 'ě'],
    'f': ['f', 'ƒ'],
    'g': ['g', '9', '6', 'ğ'],
    'h': ['h', '#'],
    'i': ['i', '1', '!', '|', 'ì', 'í', 'î', 'ï', 'ī', 'į'],
    'j': ['j'],
    'k': ['k', 'κ'],
    'l': ['l', '1', '|', 'ł'],
    'm': ['m'],
    'n': ['n', 'ñ', 'ń', 'ň'],
    'o': ['o', '0', 'ø', 'ò', 'ó', 'ô', 'õ', 'ö', 'ō', 'ő'],
    'p': ['p', 'ρ'],
    'q': ['q'],
    'r': ['r', 'ř'],
    's': ['s', '$', '5', 'š', 'ś', 'ş'],
    't': ['t', '7', '+', 'ť', 'ţ'],
    'u': ['u', 'µ', 'ù', 'ú', 'û', 'ü', 'ū', 'ů', 'ű', 'ų'],
    'v': ['v'],
    'w': ['w', 'ω'],
    'x': ['x', '×'],
    'y': ['y', '¥', 'ý', 'ÿ'],
    'z': ['z', '2', 'ž', 'ź', 'ż'],
}

def now(): return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY,
                log_channel INTEGER, mod_log_channel INTEGER, welcome_channel INTEGER,
                warns_kick INTEGER DEFAULT 0, warns_ban INTEGER DEFAULT 0,
                -- Protection ON/OFF
                anti_link INTEGER DEFAULT 0,
                anti_invite INTEGER DEFAULT 0,
                anti_image INTEGER DEFAULT 0,
                anti_phishing INTEGER DEFAULT 1,
                anti_scam INTEGER DEFAULT 1,
                anti_spam INTEGER DEFAULT 0,
                anti_mention INTEGER DEFAULT 0,
                anti_caps INTEGER DEFAULT 0,
                anti_newaccount INTEGER DEFAULT 0,
                anti_badwords INTEGER DEFAULT 0,
                -- Config Anti-Liens (JSON array)
                link_whitelist TEXT DEFAULT '["youtube.com","twitter.com","discord.com","twitch.tv"]',
                -- Config Anti-Images (JSON array)
                image_allowed TEXT DEFAULT '[]',
                -- Config Anti-Phishing
                phishing_action TEXT DEFAULT 'ban',
                -- Config Anti-Scam
                scam_action TEXT DEFAULT 'mute',
                scam_duration INTEGER DEFAULT 60,
                -- Config Anti-Spam
                spam_max_msg INTEGER DEFAULT 5,
                spam_interval INTEGER DEFAULT 5,
                spam_action TEXT DEFAULT 'mute',
                spam_duration INTEGER DEFAULT 10,
                -- Config Anti-Mention
                mention_protected_roles TEXT DEFAULT '[]',
                mention_protected_users TEXT DEFAULT '[]',
                mention_max_count INTEGER DEFAULT 3,
                mention_action TEXT DEFAULT 'warn',
                mention_duration INTEGER DEFAULT 10,
                -- Config Anti-Caps
                caps_percent INTEGER DEFAULT 70,
                caps_min_len INTEGER DEFAULT 10,
                caps_action TEXT DEFAULT 'delete',
                -- Config Anti-NewAccount
                newaccount_value INTEGER DEFAULT 7,
                newaccount_unit TEXT DEFAULT 'jours',
                -- Config Anti-Badwords (JSON array)
                badwords_list TEXT DEFAULT '[]',
                badwords_action TEXT DEFAULT 'delete',
                -- Welcome
                welcome_on INTEGER DEFAULT 0,
                welcome_msg TEXT DEFAULT 'Bienvenue {member} !'
            );
            CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id));
            CREATE TABLE IF NOT EXISTS ticket_config (guild_id INTEGER PRIMARY KEY, category_id INTEGER, staff_role_id INTEGER);
            CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, status TEXT DEFAULT 'open', created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS role_permissions (guild_id INTEGER, role_id INTEGER, permission TEXT, PRIMARY KEY(guild_id,role_id,permission));
        ''')
        await db.commit()
    print(f"✅ DB: {DB_PATH}")

async def gcfg(gid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM config WHERE guild_id=?', (gid,))
        r = await cur.fetchone()
        if r: return dict(r)
        await db.execute('INSERT OR IGNORE INTO config (guild_id) VALUES (?)', (gid,))
        await db.commit()
        cur = await db.execute('SELECT * FROM config WHERE guild_id=?', (gid,))
        r = await cur.fetchone()
        return dict(r) if r else {'guild_id': gid}

async def scfg(gid, **kw):
    async with aiosqlite.connect(DB_PATH) as db:
        for k,v in kw.items():
            try:
                await db.execute(f'UPDATE config SET {k}=? WHERE guild_id=?', (v, gid))
            except Exception as e:
                print(f"scfg error {k}: {e}")
        await db.commit()

def get_json_list(data, key, default=None):
    if default is None:
        default = []
    try:
        val = data.get(key)
        if val is None:
            return default
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            if not val or val == '':
                return default
            return json.loads(val)
        return default
    except:
        return default

async def is_immune(m):
    if m.guild_permissions.administrator or m.id == m.guild.owner_id:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,))
        ids = [r[0] for r in await cur.fetchall()]
    return any(r.id in ids for r in m.roles)

async def apply_action(member, action, duration_min, reason):
    try:
        if action == 'delete':
            pass
        elif action == 'mute' and duration_min > 0:
            await member.timeout(timedelta(minutes=duration_min), reason=reason)
        elif action == 'warn':
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT INTO infractions (guild_id,user_id,mod_id,type,reason) VALUES (?,?,?,?,?)',
                    (member.guild.id, member.id, member.guild.me.id, 'warn', reason))
                await db.commit()
        elif action == 'kick':
            await member.kick(reason=reason)
        elif action == 'ban':
            await member.ban(reason=reason, delete_message_days=1)
    except Exception as e:
        print(f"Action error: {e}")

async def has_permission(member, perm):
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        for r in member.roles:
            cur = await db.execute('SELECT 1 FROM role_permissions WHERE guild_id=? AND role_id=? AND permission=?', (member.guild.id, r.id, perm))
            if await cur.fetchone():
                return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#                           🚫 ANTI-BADWORDS (Anti-Contournement)
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_text(text):
    """Normalise le texte pour détecter les contournements"""
    # Convertir en minuscules
    text = text.lower()
    
    # Supprimer les accents
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    
    # Remplacer les caractères leet speak
    result = []
    for char in text:
        found = False
        for letter, variants in LEET_MAP.items():
            if char in variants:
                result.append(letter)
                found = True
                break
        if not found:
            result.append(char)
    
    text = ''.join(result)
    
    # Supprimer les caractères répétés (ex: "moooot" -> "mot")
    cleaned = []
    prev_char = ''
    for char in text:
        if char != prev_char or not char.isalpha():
            cleaned.append(char)
        prev_char = char
    text = ''.join(cleaned)
    
    return text

def normalize_word(word):
    """Normalise un mot banni"""
    word = word.lower().strip()
    word = unicodedata.normalize('NFD', word)
    word = ''.join(c for c in word if unicodedata.category(c) != 'Mn')
    return word

def check_badwords(content, badwords_list):
    """Vérifie si le contenu contient des mots interdits (avec anti-contournement)"""
    if not badwords_list:
        return False, None
    
    # Version originale du contenu
    original = content.lower()
    
    # Version normalisée (anti-contournement)
    normalized = normalize_text(content)
    
    # Version sans espaces ni caractères spéciaux
    no_spaces = re.sub(r'[^a-z]', '', normalized)
    
    for word in badwords_list:
        word_normalized = normalize_word(word)
        if not word_normalized:
            continue
        
        # Vérification 1: Mot exact dans le texte original
        if re.search(r'\b' + re.escape(word.lower()) + r'\b', original):
            return True, word
        
        # Vérification 2: Mot dans le texte normalisé
        if re.search(r'\b' + re.escape(word_normalized) + r'\b', normalized):
            return True, word
        
        # Vérification 3: Mot dans le texte sans espaces (pour "m o t")
        if word_normalized in no_spaces:
            return True, word
        
        # Vérification 4: Regex flexible pour les variations
        # Ex: "test" -> t.*e.*s.*t (avec des caractères entre)
        if len(word_normalized) >= 3:
            pattern = '.*'.join(re.escape(c) for c in word_normalized)
            # Limiter la recherche pour éviter les faux positifs
            if len(word_normalized) >= 4:
                # Chercher le pattern dans une fenêtre raisonnable
                for i in range(len(no_spaces) - len(word_normalized) + 1):
                    window = no_spaces[i:i + len(word_normalized) * 3]  # Fenêtre de 3x la taille du mot
                    if re.search(pattern, window):
                        return True, word
    
    return False, None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ AUTRES PROTECTION CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def check_link(content, whitelist_json):
    urls = re.findall(r'https?://([^\s/]+)', content.lower())
    if not urls:
        return False
    allowed = get_json_list({'w': whitelist_json}, 'w', [])
    for url in urls:
        if not any(a.lower() in url for a in allowed):
            return True
    return False

def check_invite(content):
    return bool(re.search(r'(discord\.gg|discord\.com/invite)/[a-zA-Z0-9]+', content))

def check_phishing(content):
    return any(d in content.lower() for d in PHISHING_DOMAINS)

def check_scam(content):
    return any(re.search(p, content, re.I) for p in SCAM_PATTERNS)

def check_caps(content, percent=70, min_len=10):
    if len(content) < min_len:
        return False
    letters = [c for c in content if c.isalpha()]
    if not letters:
        return False
    return (sum(1 for c in letters if c.isupper()) / len(letters) * 100) >= percent

def check_image_blocked(attachment, allowed_list):
    """Vérifie si une image doit être bloquée"""
    ext = attachment.filename.lower().split('.')[-1]
    image_exts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
    
    # Si ce n'est pas une image, ne pas bloquer
    if ext not in image_exts:
        return False
    
    # Si la liste est vide, tout est bloqué
    if not allowed_list:
        return True
    
    # Normaliser la liste
    allowed_normalized = [a.lower().replace('.', '').strip() for a in allowed_list]
    
    # Si le format n'est pas dans la liste autorisée, bloquer
    return ext not in allowed_normalized

async def check_spam(msg, max_msg=5, interval=5):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker:
        spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n - t).total_seconds() < interval]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > max_msg

async def check_protected_mentions(msg, protected_roles, protected_users, max_count):
    roles = get_json_list({'r': protected_roles}, 'r', [])
    users = get_json_list({'u': protected_users}, 'u', [])
    
    count = 0
    for role in msg.role_mentions:
        if role.id in roles:
            count += 1
    for user in msg.mentions:
        if user.id in users:
            count += 1
    
    if count == 0:
        return False
    
    key = (msg.guild.id, msg.author.id)
    if key not in mention_tracker:
        mention_tracker[key] = {'count': 0, 'last_reset': now()}
    
    if (now() - mention_tracker[key]['last_reset']).total_seconds() > 3600:
        mention_tracker[key] = {'count': 0, 'last_reset': now()}
    
    mention_tracker[key]['count'] += count
    return mention_tracker[key]['count'] >= max_count

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class MainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def interaction_check(self, i):
        if i.user.id != self.u.id:
            await i.response.send_message("❌", ephemeral=True)
            return False
        return True
    
    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"Serveur: **{self.g.name}**\nMembres: **{self.g.member_count}**"
        if self.g.icon:
            e.set_thumbnail(url=self.g.icon.url)
        return e
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def logs(self, i, b):
        v = LogsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Sanctions", emoji="⚖️", style=discord.ButtonStyle.danger, row=0)
    async def sanct(self, i, b):
        v = SanctPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def immune(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def welc(self, i, b):
        v = WelcPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.primary, row=1)
    async def tick(self, i, b):
        v = TicketPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL
# ═══════════════════════════════════════════════════════════════════════════════

PROT_OPTIONS = [
    {"key": "anti_link", "emoji": "🔗", "name": "Anti-Liens", "desc": "Bloque les liens non autorisés"},
    {"key": "anti_invite", "emoji": "🎟️", "name": "Anti-Invite", "desc": "Bloque les invitations Discord"},
    {"key": "anti_image", "emoji": "🖼️", "name": "Anti-Images", "desc": "Bloque certains formats d'images"},
    {"key": "anti_phishing", "emoji": "🎣", "name": "Anti-Phishing", "desc": "Détecte les faux sites"},
    {"key": "anti_scam", "emoji": "🚨", "name": "Anti-Scam", "desc": "Détecte les arnaques"},
    {"key": "anti_spam", "emoji": "📨", "name": "Anti-Spam", "desc": "Limite les messages rapides"},
    {"key": "anti_mention", "emoji": "📢", "name": "Anti-Ping", "desc": "Protège des pings abusifs"},
    {"key": "anti_caps", "emoji": "🔠", "name": "Anti-Caps", "desc": "Bloque les MAJUSCULES"},
    {"key": "anti_badwords", "emoji": "🤬", "name": "Anti-Insultes", "desc": "Bloque les mots interdits"},
    {"key": "anti_newaccount", "emoji": "👶", "name": "Anti-NewAccount", "desc": "Bloque comptes récents"},
]

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        
        options = [
            discord.SelectOption(label=p["name"], value=p["key"], emoji=p["emoji"], description=p["desc"][:50])
            for p in PROT_OPTIONS
        ]
        select = Select(placeholder="🛡️ Sélectionner une protection...", options=options, row=0)
        select.callback = self.select_protection
        self.add_item(select)

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def embed(self):
        c = await gcfg(self.g.id)
        def s(k):
            return "✅" if c.get(k) else "❌"
        
        link_list = get_json_list(c, 'link_whitelist', [])
        img_list = get_json_list(c, 'image_allowed', [])
        badwords = get_json_list(c, 'badwords_list', [])
        prot_roles = get_json_list(c, 'mention_protected_roles', [])
        prot_users = get_json_list(c, 'mention_protected_users', [])
        
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = f"""```yml
🔗 Anti-Liens     : {s('anti_link')}  │ {len(link_list)} domaines whitelist
🎟️ Anti-Invite    : {s('anti_invite')}  │ Invitations Discord
🖼️ Anti-Images    : {s('anti_image')}  │ {len(img_list)} formats autorisés
🎣 Anti-Phishing  : {s('anti_phishing')}  │ {c.get('phishing_action','ban')}
🚨 Anti-Scam      : {s('anti_scam')}  │ {c.get('scam_action','mute')}
📨 Anti-Spam      : {s('anti_spam')}  │ {c.get('spam_max_msg',5)}msg/{c.get('spam_interval',5)}s
📢 Anti-Ping      : {s('anti_mention')}  │ {len(prot_roles)}R/{len(prot_users)}U protégés
🔠 Anti-Caps      : {s('anti_caps')}  │ {c.get('caps_percent',70)}%
🤬 Anti-Insultes  : {s('anti_badwords')}  │ {len(badwords)} mots interdits
👶 Anti-NewAccount: {s('anti_newaccount')}  │ {c.get('newaccount_value',7)} {c.get('newaccount_unit','jours')}
```
**▼ Sélectionnez une protection pour la configurer**"""
        return e

    async def select_protection(self, i):
        key = i.data['values'][0]
        prot = next((p for p in PROT_OPTIONS if p["key"] == key), None)
        if prot:
            v = ProtDetailPanel(self.u, self.g, prot)
            await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🛡️ PROTECTION DETAIL PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class ProtDetailPanel(View):
    def __init__(self, u, g, prot):
        super().__init__(timeout=900)
        self.u, self.g, self.prot = u, g, prot
        self.key = prot["key"]

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def embed(self):
        c = await gcfg(self.g.id)
        is_on = c.get(self.key, 0)
        
        e = discord.Embed(
            title=f"{self.prot['emoji']} {self.prot['name']}",
            color=C.GREEN if is_on else C.RED
        )
        
        status = "✅ **ACTIVÉ**" if is_on else "❌ **DÉSACTIVÉ**"
        e.add_field(name="État", value=status, inline=False)
        
        if self.key == "anti_link":
            domains = get_json_list(c, 'link_whitelist', [])
            if domains:
                domain_list = "\n".join([f"✅ `{d}`" for d in domains[:15]])
                if len(domains) > 15:
                    domain_list += f"\n... et {len(domains)-15} autres"
            else:
                domain_list = "*Aucun domaine (tous bloqués)*"
            e.add_field(name="📝 Fonctionnement", value="Bloque tous les liens **SAUF** ceux en whitelist", inline=False)
            e.add_field(name=f"✅ Domaines autorisés ({len(domains)})", value=domain_list, inline=False)
            
        elif self.key == "anti_invite":
            e.add_field(name="📝 Fonctionnement", value="Bloque toutes les invitations Discord", inline=False)
            
        elif self.key == "anti_image":
            formats = get_json_list(c, 'image_allowed', [])
            all_formats = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
            
            if formats:
                allowed_str = " ".join([f"✅ `{f}`" for f in formats])
            else:
                allowed_str = "*Aucun (toutes les images bloquées)*"
            
            blocked = [f for f in all_formats if f not in formats]
            blocked_str = " ".join([f"❌ `{f}`" for f in blocked]) if blocked else "*Aucun*"
            
            e.add_field(name="📝 Fonctionnement", value="Bloque les images **SAUF** les formats autorisés", inline=False)
            e.add_field(name=f"✅ Formats autorisés ({len(formats)})", value=allowed_str, inline=False)
            e.add_field(name=f"❌ Formats bloqués ({len(blocked)})", value=blocked_str, inline=False)
            
        elif self.key == "anti_phishing":
            e.add_field(name="📝 Fonctionnement", value="Détecte les liens de phishing", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('phishing_action', 'ban')}`", inline=False)
            
        elif self.key == "anti_scam":
            e.add_field(name="📝 Fonctionnement", value="Détecte les arnaques (free nitro, etc.)", inline=False)
            action = c.get('scam_action', 'mute')
            e.add_field(name="⚡ Sanction", value=f"`{action}`" + (f" ({c.get('scam_duration', 60)} min)" if action == 'mute' else ""), inline=False)
            
        elif self.key == "anti_spam":
            e.add_field(name="📝 Fonctionnement", value=f"Bloque si **{c.get('spam_max_msg',5)}+ messages** en **{c.get('spam_interval',5)}s**", inline=False)
            action = c.get('spam_action', 'mute')
            e.add_field(name="⚡ Sanction", value=f"`{action}`", inline=False)
            
        elif self.key == "anti_mention":
            roles = get_json_list(c, 'mention_protected_roles', [])
            users = get_json_list(c, 'mention_protected_users', [])
            role_names = [f"@{self.g.get_role(rid).name}" for rid in roles if self.g.get_role(rid)]
            user_names = [f"@{self.g.get_member(uid).display_name}" for uid in users if self.g.get_member(uid)]
            
            e.add_field(name="📝 Fonctionnement", value=f"Sanction après **{c.get('mention_max_count', 3)}** pings d'un rôle/membre protégé", inline=False)
            e.add_field(name=f"🛡️ Rôles ({len(roles)})", value=", ".join(role_names) or "*Aucun*", inline=True)
            e.add_field(name=f"🛡️ Membres ({len(users)})", value=", ".join(user_names) or "*Aucun*", inline=True)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('mention_action', 'warn')}`", inline=False)
            
        elif self.key == "anti_caps":
            e.add_field(name="📝 Fonctionnement", value=f"Bloque si **{c.get('caps_percent', 70)}%+** de majuscules", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('caps_action', 'delete')}`", inline=False)
            
        elif self.key == "anti_badwords":
            words = get_json_list(c, 'badwords_list', [])
            if words:
                words_display = ", ".join([f"`{w[:10]}{'...' if len(w)>10 else ''}`" for w in words[:20]])
                if len(words) > 20:
                    words_display += f" ... et {len(words)-20} autres"
            else:
                words_display = "*Aucun mot interdit*"
            
            e.add_field(name="📝 Fonctionnement", value="Bloque les mots interdits avec **détection anti-contournement**\n(majuscules, accents, leetspeak, espaces)", inline=False)
            e.add_field(name=f"🚫 Mots interdits ({len(words)})", value=words_display, inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('badwords_action', 'delete')}`", inline=False)
            
        elif self.key == "anti_newaccount":
            e.add_field(name="📝 Fonctionnement", value=f"Kick les comptes < **{c.get('newaccount_value', 7)} {c.get('newaccount_unit', 'jours')}**", inline=False)
            e.add_field(name="⚡ Sanction", value="`kick`", inline=False)
        
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        c = await gcfg(self.g.id)
        current = c.get(self.key, 0)
        new_val = 0 if current else 1
        await scfg(self.g.id, **{self.key: new_val})
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        if self.key == "anti_link":
            v = LinkConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_image":
            v = ImageConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_phishing":
            await i.response.send_modal(PhishingConfigModal(self.g))
        elif self.key == "anti_scam":
            await i.response.send_modal(ScamConfigModal(self.g))
        elif self.key == "anti_spam":
            await i.response.send_modal(SpamConfigModal(self.g))
        elif self.key == "anti_mention":
            v = MentionConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_caps":
            await i.response.send_modal(CapsConfigModal(self.g))
        elif self.key == "anti_badwords":
            v = BadwordsConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_newaccount":
            await i.response.send_modal(NewAccountConfigModal(self.g))
        else:
            await i.response.send_message("❌ Pas de configuration", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🔗 ANTI-LIENS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g

    async def embed(self):
        c = await gcfg(self.g.id)
        domains = get_json_list(c, 'link_whitelist', [])
        
        e = discord.Embed(title="🔗 Anti-Liens - Configuration", color=C.BLUE)
        if domains:
            domain_list = "\n".join([f"• `{d}`" for d in domains])
        else:
            domain_list = "*Liste vide - tous les liens sont bloqués*"
        e.add_field(name=f"✅ Domaines autorisés ({len(domains)})", value=domain_list, inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddDomainModal(self.g))

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        c = await gcfg(self.g.id)
        domains = get_json_list(c, 'link_whitelist', [])
        if not domains:
            return await i.response.send_message("❌ Liste vide", ephemeral=True)
        v = RemoveDomainPanel(self.u, self.g, domains)
        await i.response.edit_message(embed=v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROT_OPTIONS if p["key"] == "anti_link")
        v = ProtDetailPanel(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddDomainModal(Modal, title="➕ Ajouter un domaine"):
    domain = TextInput(label="Domaine à autoriser", placeholder="exemple.com", max_length=100)
    
    def __init__(self, g):
        super().__init__()
        self.g = g
    
    async def on_submit(self, i):
        c = await gcfg(self.g.id)
        domains = get_json_list(c, 'link_whitelist', [])
        new_domain = self.domain.value.lower().strip()
        
        if new_domain in [d.lower() for d in domains]:
            return await i.response.send_message(f"❌ `{new_domain}` existe déjà", ephemeral=True)
        
        domains.append(new_domain)
        await scfg(self.g.id, link_whitelist=json.dumps(domains))
        await i.response.send_message(f"✅ `{new_domain}` ajouté", ephemeral=True)

class RemoveDomainPanel(View):
    def __init__(self, u, g, domains):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        options = [discord.SelectOption(label=d[:25], value=d) for d in domains[:25]]
        select = Select(placeholder="Sélectionner...", options=options)
        select.callback = self.remove
        self.add_item(select)

    def embed(self):
        return discord.Embed(title="➖ Supprimer un domaine", color=C.RED)

    async def remove(self, i):
        domain = i.data['values'][0]
        c = await gcfg(self.g.id)
        domains = get_json_list(c, 'link_whitelist', [])
        if domain in domains:
            domains.remove(domain)
            await scfg(self.g.id, link_whitelist=json.dumps(domains))
        await i.response.send_message(f"✅ `{domain}` supprimé", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = LinkConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🖼️ ANTI-IMAGES CONFIG (CORRIGÉ)
# ═══════════════════════════════════════════════════════════════════════════════

class ImageConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g

    async def embed(self):
        c = await gcfg(self.g.id)
        formats = get_json_list(c, 'image_allowed', [])
        all_formats = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        
        e = discord.Embed(title="🖼️ Anti-Images - Configuration", color=C.BLUE)
        
        if formats:
            allowed_str = " ".join([f"✅ `{f}`" for f in formats])
        else:
            allowed_str = "*Aucun format autorisé = toutes les images bloquées*"
        e.add_field(name=f"✅ Formats autorisés ({len(formats)})", value=allowed_str, inline=False)
        
        blocked = [f for f in all_formats if f not in formats]
        if blocked:
            blocked_str = " ".join([f"❌ `{f}`" for f in blocked])
            e.add_field(name=f"❌ Formats bloqués ({len(blocked)})", value=blocked_str, inline=False)
        
        return e

    @discord.ui.button(label="➕ Autoriser format", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        c = await gcfg(self.g.id)
        formats = get_json_list(c, 'image_allowed', [])
        all_formats = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        available = [f for f in all_formats if f not in formats]
        
        if not available:
            return await i.response.send_message("✅ Tous les formats sont déjà autorisés", ephemeral=True)
        
        options = [discord.SelectOption(label=f.upper(), value=f, emoji="🖼️") for f in available]
        v = AddFormatPanel(self.u, self.g, options)
        await i.response.edit_message(embed=v.embed(), view=v)

    @discord.ui.button(label="➖ Bloquer format", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        c = await gcfg(self.g.id)
        formats = get_json_list(c, 'image_allowed', [])
        
        if not formats:
            return await i.response.send_message("❌ Aucun format à bloquer (tout est déjà bloqué)", ephemeral=True)
        
        options = [discord.SelectOption(label=f.upper(), value=f) for f in formats]
        v = RemoveFormatPanel(self.u, self.g, options)
        await i.response.edit_message(embed=v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROT_OPTIONS if p["key"] == "anti_image")
        v = ProtDetailPanel(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddFormatPanel(View):
    def __init__(self, u, g, options):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        select = Select(placeholder="Format à autoriser...", options=options)
        select.callback = self.add_format
        self.add_item(select)

    def embed(self):
        return discord.Embed(title="➕ Autoriser un format", description="Sélectionnez le format à autoriser", color=C.GREEN)

    async def add_format(self, i):
        fmt = i.data['values'][0]
        c = await gcfg(self.g.id)
        formats = get_json_list(c, 'image_allowed', [])
        
        if fmt not in formats:
            formats.append(fmt)
            await scfg(self.g.id, image_allowed=json.dumps(formats))
        
        # Retourner au panel avec mise à jour
        v = ImageConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ImageConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RemoveFormatPanel(View):
    def __init__(self, u, g, options):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        select = Select(placeholder="Format à bloquer...", options=options)
        select.callback = self.remove_format
        self.add_item(select)

    def embed(self):
        return discord.Embed(title="➖ Bloquer un format", description="Sélectionnez le format à bloquer", color=C.RED)

    async def remove_format(self, i):
        fmt = i.data['values'][0]
        c = await gcfg(self.g.id)
        formats = get_json_list(c, 'image_allowed', [])
        
        if fmt in formats:
            formats.remove(fmt)
            await scfg(self.g.id, image_allowed=json.dumps(formats))
        
        # Retourner au panel avec mise à jour
        v = ImageConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ImageConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🤬 ANTI-BADWORDS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class BadwordsConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g

    async def embed(self):
        c = await gcfg(self.g.id)
        words = get_json_list(c, 'badwords_list', [])
        action = c.get('badwords_action', 'delete')
        
        e = discord.Embed(title="🤬 Anti-Insultes - Configuration", color=C.BLUE)
        e.add_field(name="⚡ Sanction actuelle", value=f"`{action}`", inline=False)
        
        if words:
            words_list = "\n".join([f"• `{w}`" for w in words[:25]])
            if len(words) > 25:
                words_list += f"\n... et {len(words)-25} autres"
        else:
            words_list = "*Aucun mot interdit*"
        e.add_field(name=f"🚫 Mots interdits ({len(words)})", value=words_list, inline=False)
        
        e.add_field(name="💡 Anti-Contournement", value="Le système détecte automatiquement:\n• Majuscules (TeSt → test)\n• Accents (tëst → test)\n• Leetspeak (t3st, te$t → test)\n• Espaces (t e s t → test)\n• Répétitions (teeeest → test)", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter mot", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddBadwordModal(self.g))

    @discord.ui.button(label="➖ Supprimer mot", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        c = await gcfg(self.g.id)
        words = get_json_list(c, 'badwords_list', [])
        if not words:
            return await i.response.send_message("❌ Aucun mot à supprimer", ephemeral=True)
        v = RemoveBadwordPanel(self.u, self.g, words)
        await i.response.edit_message(embed=v.embed(), view=v)

    @discord.ui.button(label="⚙️ Sanction", style=discord.ButtonStyle.secondary, row=0)
    async def config_action(self, i, b):
        await i.response.send_modal(BadwordActionModal(self.g))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROT_OPTIONS if p["key"] == "anti_badwords")
        v = ProtDetailPanel(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddBadwordModal(Modal, title="➕ Ajouter un mot interdit"):
    word = TextInput(label="Mot à interdire", placeholder="insulte", max_length=50)
    
    def __init__(self, g):
        super().__init__()
        self.g = g
    
    async def on_submit(self, i):
        c = await gcfg(self.g.id)
        words = get_json_list(c, 'badwords_list', [])
        new_word = self.word.value.lower().strip()
        
        if new_word in [w.lower() for w in words]:
            return await i.response.send_message(f"❌ `{new_word}` existe déjà", ephemeral=True)
        
        words.append(new_word)
        await scfg(self.g.id, badwords_list=json.dumps(words))
        await i.response.send_message(f"✅ `{new_word}` ajouté aux mots interdits", ephemeral=True)

class RemoveBadwordPanel(View):
    def __init__(self, u, g, words):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        options = [discord.SelectOption(label=w[:25], value=w) for w in words[:25]]
        select = Select(placeholder="Mot à supprimer...", options=options)
        select.callback = self.remove
        self.add_item(select)

    def embed(self):
        return discord.Embed(title="➖ Supprimer un mot interdit", color=C.RED)

    async def remove(self, i):
        word = i.data['values'][0]
        c = await gcfg(self.g.id)
        words = get_json_list(c, 'badwords_list', [])
        if word in words:
            words.remove(word)
            await scfg(self.g.id, badwords_list=json.dumps(words))
        await i.response.send_message(f"✅ `{word}` supprimé", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = BadwordsConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class BadwordActionModal(Modal, title="⚙️ Sanction Anti-Insultes"):
    action = TextInput(label="Sanction (delete / warn / kick)", placeholder="delete", default="delete", max_length=10)
    
    def __init__(self, g):
        super().__init__()
        self.g = g
    
    async def on_submit(self, i):
        action = self.action.value.lower().strip()
        if action not in ['delete', 'warn', 'kick']:
            action = 'delete'
        await scfg(self.g.id, badwords_action=action)
        await i.response.send_message(f"✅ Sanction: `{action}`", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                    📢 ANTI-MENTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class MentionConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g

    async def embed(self):
        c = await gcfg(self.g.id)
        roles = get_json_list(c, 'mention_protected_roles', [])
        users = get_json_list(c, 'mention_protected_users', [])
        
        role_names = [f"@{self.g.get_role(rid).name}" for rid in roles if self.g.get_role(rid)]
        user_names = [f"@{self.g.get_member(uid).display_name}" for uid in users if self.g.get_member(uid)]
        
        e = discord.Embed(title="📢 Anti-Ping - Configuration", color=C.BLUE)
        e.add_field(name="📝 Fonctionnement", value=f"Sanction après **{c.get('mention_max_count', 3)}** pings → `{c.get('mention_action', 'warn')}`", inline=False)
        e.add_field(name=f"🛡️ Rôles protégés ({len(roles)})", value="\n".join(role_names) or "*Aucun*", inline=True)
        e.add_field(name=f"🛡️ Membres protégés ({len(users)})", value="\n".join(user_names) or "*Aucun*", inline=True)
        return e

    @discord.ui.button(label="➕ Rôle", emoji="🛡️", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        if not roles:
            return await i.response.send_message("❌ Aucun rôle", ephemeral=True)
        options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = AddProtRolePanel(self.u, self.g, options)
        await i.response.edit_message(embed=v.embed(), view=v)

    @discord.ui.button(label="➖ Rôle", style=discord.ButtonStyle.danger, row=0)
    async def remove_role(self, i, b):
        c = await gcfg(self.g.id)
        roles = get_json_list(c, 'mention_protected_roles', [])
        if not roles:
            return await i.response.send_message("❌ Aucun rôle", ephemeral=True)
        options = []
        for rid in roles[:25]:
            role = self.g.get_role(rid)
            if role:
                options.append(discord.SelectOption(label=f"@{role.name}"[:25], value=str(rid)))
        if options:
            v = RemoveProtRolePanel(self.u, self.g, options)
            await i.response.edit_message(embed=v.embed(), view=v)

    @discord.ui.button(label="➕ Membre", emoji="👤", style=discord.ButtonStyle.success, row=1)
    async def add_user(self, i, b):
        await i.response.send_modal(AddProtUserModal(self.g))

    @discord.ui.button(label="➖ Membre", style=discord.ButtonStyle.danger, row=1)
    async def remove_user(self, i, b):
        c = await gcfg(self.g.id)
        users = get_json_list(c, 'mention_protected_users', [])
        if not users:
            return await i.response.send_message("❌ Aucun membre", ephemeral=True)
        options = []
        for uid in users[:25]:
            member = self.g.get_member(uid)
            if member:
                options.append(discord.SelectOption(label=f"@{member.display_name}"[:25], value=str(uid)))
        if options:
            v = RemoveProtUserPanel(self.u, self.g, options)
            await i.response.edit_message(embed=v.embed(), view=v)

    @discord.ui.button(label="⚙️ Sanction", style=discord.ButtonStyle.secondary, row=2)
    async def config_sanction(self, i, b):
        await i.response.send_modal(MentionSanctionModal(self.g))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROT_OPTIONS if p["key"] == "anti_mention")
        v = ProtDetailPanel(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddProtRolePanel(View):
    def __init__(self, u, g, options):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        select = Select(placeholder="Rôle à protéger...", options=options)
        select.callback = self.add
        self.add_item(select)
    def embed(self): return discord.Embed(title="➕ Ajouter rôle protégé", color=C.GREEN)
    async def add(self, i):
        rid = int(i.data['values'][0])
        c = await gcfg(self.g.id)
        roles = get_json_list(c, 'mention_protected_roles', [])
        if rid not in roles:
            roles.append(rid)
            await scfg(self.g.id, mention_protected_roles=json.dumps(roles))
        v = MentionConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MentionConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RemoveProtRolePanel(View):
    def __init__(self, u, g, options):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        select = Select(placeholder="Rôle à retirer...", options=options)
        select.callback = self.remove
        self.add_item(select)
    def embed(self): return discord.Embed(title="➖ Retirer rôle protégé", color=C.RED)
    async def remove(self, i):
        rid = int(i.data['values'][0])
        c = await gcfg(self.g.id)
        roles = get_json_list(c, 'mention_protected_roles', [])
        if rid in roles:
            roles.remove(rid)
            await scfg(self.g.id, mention_protected_roles=json.dumps(roles))
        v = MentionConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MentionConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddProtUserModal(Modal, title="➕ Ajouter membre protégé"):
    user_id = TextInput(label="ID du membre", placeholder="Clic droit > Copier l'ID", max_length=20)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        try:
            uid = int(self.user_id.value)
            member = i.guild.get_member(uid)
            if not member:
                return await i.response.send_message("❌ Membre introuvable", ephemeral=True)
        except:
            return await i.response.send_message("❌ ID invalide", ephemeral=True)
        c = await gcfg(self.g.id)
        users = get_json_list(c, 'mention_protected_users', [])
        if uid not in users:
            users.append(uid)
            await scfg(self.g.id, mention_protected_users=json.dumps(users))
        await i.response.send_message(f"✅ {member.mention} protégé", ephemeral=True)

class RemoveProtUserPanel(View):
    def __init__(self, u, g, options):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        select = Select(placeholder="Membre à retirer...", options=options)
        select.callback = self.remove
        self.add_item(select)
    def embed(self): return discord.Embed(title="➖ Retirer membre protégé", color=C.RED)
    async def remove(self, i):
        uid = int(i.data['values'][0])
        c = await gcfg(self.g.id)
        users = get_json_list(c, 'mention_protected_users', [])
        if uid in users:
            users.remove(uid)
            await scfg(self.g.id, mention_protected_users=json.dumps(users))
        v = MentionConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MentionConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class MentionSanctionModal(Modal, title="⚙️ Sanction Anti-Ping"):
    max_count = TextInput(label="Nombre de pings avant sanction", placeholder="3", default="3", max_length=3)
    action = TextInput(label="Sanction (warn / mute / kick / ban)", placeholder="warn", default="warn", max_length=10)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        count = int(self.max_count.value) if self.max_count.value.isdigit() else 3
        action = self.action.value.lower().strip()
        if action not in ['warn', 'mute', 'kick', 'ban']:
            action = 'warn'
        await scfg(self.g.id, mention_max_count=count, mention_action=action)
        await i.response.send_message(f"✅ Après **{count}** pings → `{action}`", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚙️ AUTRES MODALS
# ═══════════════════════════════════════════════════════════════════════════════

class PhishingConfigModal(Modal, title="🎣 Anti-Phishing"):
    action = TextInput(label="Sanction (delete / mute / kick / ban)", placeholder="ban", default="ban", max_length=10)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        action = self.action.value.lower().strip()
        if action not in ['delete', 'mute', 'kick', 'ban']: action = 'ban'
        await scfg(self.g.id, phishing_action=action)
        await i.response.send_message(f"✅ Phishing → `{action}`", ephemeral=True)

class ScamConfigModal(Modal, title="🚨 Anti-Scam"):
    action = TextInput(label="Sanction (delete / mute / kick / ban)", placeholder="mute", default="mute", max_length=10)
    duration = TextInput(label="Durée mute (minutes)", placeholder="60", default="60", max_length=5, required=False)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        action = self.action.value.lower().strip()
        if action not in ['delete', 'mute', 'kick', 'ban']: action = 'mute'
        dur = int(self.duration.value) if self.duration.value.isdigit() else 60
        await scfg(self.g.id, scam_action=action, scam_duration=dur)
        await i.response.send_message(f"✅ Scam → `{action}`", ephemeral=True)

class SpamConfigModal(Modal, title="📨 Anti-Spam"):
    max_msg = TextInput(label="Nombre max de messages", placeholder="5", default="5", max_length=3)
    interval = TextInput(label="En combien de secondes", placeholder="5", default="5", max_length=3)
    action = TextInput(label="Sanction (delete / mute / kick / ban)", placeholder="mute", default="mute", max_length=10)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        mm = int(self.max_msg.value) if self.max_msg.value.isdigit() else 5
        itv = int(self.interval.value) if self.interval.value.isdigit() else 5
        action = self.action.value.lower().strip()
        if action not in ['delete', 'mute', 'kick', 'ban']: action = 'mute'
        await scfg(self.g.id, spam_max_msg=mm, spam_interval=itv, spam_action=action)
        await i.response.send_message(f"✅ Spam: {mm}msg/{itv}s → `{action}`", ephemeral=True)

class CapsConfigModal(Modal, title="🔠 Anti-Caps"):
    percent = TextInput(label="Pourcentage max", placeholder="70", default="70", max_length=3)
    action = TextInput(label="Sanction (delete / mute / kick / ban)", placeholder="delete", default="delete", max_length=10)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        pct = int(self.percent.value) if self.percent.value.isdigit() else 70
        action = self.action.value.lower().strip()
        if action not in ['delete', 'mute', 'kick', 'ban']: action = 'delete'
        await scfg(self.g.id, caps_percent=pct, caps_action=action)
        await i.response.send_message(f"✅ Caps: {pct}% → `{action}`", ephemeral=True)

class NewAccountConfigModal(Modal, title="👶 Anti-NewAccount"):
    value = TextInput(label="Âge minimum", placeholder="7", default="7", max_length=4)
    unit = TextInput(label="Unité (jours / semaines / mois)", placeholder="jours", default="jours", max_length=10)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        val = int(self.value.value) if self.value.value.isdigit() else 7
        unit = self.unit.value.lower().strip()
        if unit not in ['jours', 'semaines', 'mois']: unit = 'jours'
        await scfg(self.g.id, newaccount_value=val, newaccount_unit=unit)
        await i.response.send_message(f"✅ Compte < {val} {unit} → `kick`", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           AUTRES PANELS (Logs, Sanctions, etc.)
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900); self.u, self.g = u, g
        chs = [c for c in g.text_channels][:25]
        if chs:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
            s1=Select(placeholder="📝 Logs généraux...",options=opts,row=1);s1.callback=self.l1;self.add_item(s1)
            s2=Select(placeholder="⚔️ Logs modération...",options=opts.copy(),row=2);s2.callback=self.l2;self.add_item(s2)
    async def l1(self,i): await scfg(self.g.id,log_channel=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def l2(self,i): await scfg(self.g.id,mod_log_channel=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def embed(self):
        c = await gcfg(self.g.id)
        lc,mc = self.g.get_channel(c.get('log_channel')), self.g.get_channel(c.get('mod_log_channel'))
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        e.description = f"📝 Généraux: {lc.mention if lc else '❌'}\n⚔️ Modération: {mc.mention if mc else '❌'}"
        return e
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=3)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class SanctPanel(View):
    def __init__(self, u, g): super().__init__(timeout=900); self.u,self.g = u,g
    async def embed(self):
        c = await gcfg(self.g.id)
        e = discord.Embed(title="⚖️ Sanctions Auto", color=C.PINK)
        wk,wb = c.get('warns_kick',0), c.get('warns_ban',0)
        e.description = f"👢 Kick après: **{wk}** warns {'(off)' if not wk else ''}\n🔨 Ban après: **{wb}** warns {'(off)' if not wb else ''}"
        return e
    @discord.ui.button(label="Configurer",emoji="⚙️",style=discord.ButtonStyle.primary)
    async def cfg(self,i,b): await i.response.send_modal(SanctConfigModal(self.g))
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class SanctConfigModal(Modal, title="⚖️ Sanctions"):
    wk = TextInput(label="Warns pour Kick (0=off)", placeholder="3", default="0", max_length=2)
    wb = TextInput(label="Warns pour Ban (0=off)", placeholder="5", default="0", max_length=2)
    def __init__(self,g): super().__init__(); self.g=g
    async def on_submit(self,i):
        k = int(self.wk.value) if self.wk.value.isdigit() else 0
        b = int(self.wb.value) if self.wb.value.isdigit() else 0
        await scfg(self.g.id, warns_kick=k, warns_ban=b)
        await i.response.send_message(f"✅ Kick: {k} | Ban: {b}", ephemeral=True)

class ImmunePanel(View):
    def __init__(self,u,g):
        super().__init__(timeout=900); self.u,self.g = u,g
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            opts = [discord.SelectOption(label=f"@{r.name}"[:25],value=str(r.id)) for r in roles]
            sel = Select(placeholder="👑 Ajouter...",options=opts,row=1); sel.callback=self.add; self.add_item(sel)
    async def add(self,i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES (?,?)', (self.g.id,int(i.data['values'][0])))
            await db.commit()
        await i.response.send_message("✅",ephemeral=True)
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,))
            ids = [r[0] for r in await cur.fetchall()]
        roles = [self.g.get_role(rid) for rid in ids if self.g.get_role(rid)]
        e = discord.Embed(title="👑 Rôles Immunisés", color=C.YELLOW)
        e.description = ", ".join([r.mention for r in roles]) if roles else "*Aucun*"
        return e
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class WelcPanel(View):
    def __init__(self,u,g):
        super().__init__(timeout=900); self.u,self.g = u,g
        chs = [c for c in g.text_channels][:25]
        if chs:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25],value=str(c.id)) for c in chs]
            sel = Select(placeholder="👋 Salon...",options=opts,row=2); sel.callback=self.ch; self.add_item(sel)
    async def ch(self,i): await scfg(self.g.id,welcome_channel=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def embed(self):
        c = await gcfg(self.g.id)
        ch = self.g.get_channel(c.get('welcome_channel'))
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"État: {'✅' if c.get('welcome_on') else '❌'}\nSalon: {ch.mention if ch else '❌'}"
        return e
    @discord.ui.button(label="ON/OFF",emoji="🔄",style=discord.ButtonStyle.primary,row=0)
    async def tog(self,i,b): c=await gcfg(self.g.id); await scfg(self.g.id,welcome_on=0 if c.get('welcome_on') else 1); await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

async def gtcfg(gid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM ticket_config WHERE guild_id=?', (gid,))
        r = await cur.fetchone()
        if r: return dict(r)
        await db.execute('INSERT OR IGNORE INTO ticket_config (guild_id) VALUES (?)', (gid,))
        await db.commit()
        return {'guild_id':gid,'category_id':None,'staff_role_id':None}

async def stcfg(gid, **kw):
    async with aiosqlite.connect(DB_PATH) as db:
        for k,v in kw.items(): await db.execute(f'UPDATE ticket_config SET {k}=? WHERE guild_id=?', (v,gid))
        await db.commit()

class TicketPanel(View):
    def __init__(self,u,g):
        super().__init__(timeout=900); self.u,self.g = u,g
        cats = [c for c in g.categories][:25]
        if cats:
            opts = [discord.SelectOption(label=c.name[:25],value=str(c.id)) for c in cats]
            sel = Select(placeholder="📁 Catégorie...",options=opts,row=1); sel.callback=self.cat; self.add_item(sel)
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            opts = [discord.SelectOption(label=f"@{r.name}"[:25],value=str(r.id)) for r in roles]
            sel = Select(placeholder="👮 Staff...",options=opts,row=2); sel.callback=self.rol; self.add_item(sel)
    async def cat(self,i): await stcfg(self.g.id,category_id=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def rol(self,i): await stcfg(self.g.id,staff_role_id=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def embed(self):
        tc = await gtcfg(self.g.id)
        cat,rl = self.g.get_channel(tc.get('category_id')), self.g.get_role(tc.get('staff_role_id'))
        e = discord.Embed(title="🎫 Tickets", color=C.PURPLE)
        e.description = f"📁 Catégorie: {cat.name if cat else '❌'}\n👮 Staff: {rl.mention if rl else '❌'}"
        return e
    @discord.ui.button(label="📤 Déployer",style=discord.ButtonStyle.success,row=0)
    async def deploy(self,i,b):
        tc = await gtcfg(self.g.id)
        if not tc.get('category_id') or not tc.get('staff_role_id'): return await i.response.send_message("❌ Config incomplète",ephemeral=True)
        chs = [c for c in self.g.text_channels][:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25],value=str(c.id)) for c in chs]
        v = DeploySelectPanel(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📤 Choisir salon",color=C.GREEN),view=v)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=0)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class DeploySelectPanel(View):
    def __init__(self,u,g,opts):
        super().__init__(timeout=300); self.u,self.g = u,g
        sel = Select(placeholder="Salon...",options=opts); sel.callback=self.deploy; self.add_item(sel)
    async def deploy(self,i):
        ch = self.g.get_channel(int(i.data['values'][0]))
        e = discord.Embed(title="🎫 Support",description="Cliquez pour créer un ticket",color=C.PURPLE)
        await ch.send(embed=e,view=TkBtn(self.g.id))
        await i.response.send_message(f"✅ Déployé dans {ch.mention}",ephemeral=True)

class TkBtn(View):
    def __init__(self,gid): super().__init__(timeout=None); self.gid=gid
    @discord.ui.button(label="📩 Créer",style=discord.ButtonStyle.success,custom_id="tk_create")
    async def cr(self,i,b):
        tc = await gtcfg(i.guild.id)
        cat,rl = i.guild.get_channel(tc.get('category_id')), i.guild.get_role(tc.get('staff_role_id'))
        if not cat or not rl: return await i.response.send_message("❌",ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=?', (i.guild.id,))
            n = (await cur.fetchone())[0]+1
        nm = f"ticket-{i.user.name[:10]}-{n}"
        ow = {i.guild.default_role:discord.PermissionOverwrite(view_channel=False),i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True),rl:discord.PermissionOverwrite(view_channel=True,send_messages=True),i.guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True)}
        ch = await cat.create_text_channel(name=nm,overwrites=ow)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO tickets (guild_id,channel_id,user_id) VALUES (?,?,?)', (i.guild.id,ch.id,i.user.id))
            await db.commit()
        await ch.send(content=f"{i.user.mention} {rl.mention}",embed=discord.Embed(title="🎫 Ticket",color=C.GREEN),view=TkActs())
        await i.response.send_message(f"✅ {ch.mention}",ephemeral=True)

class TkActs(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🔒 Fermer",style=discord.ButtonStyle.danger,custom_id="tk_close")
    async def close(self,i,b):
        await i.response.send_message("🔒 Fermeture...")
        await asyncio.sleep(2)
        try: await i.channel.delete()
        except: pass

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(TkBtn(0))
    bot.add_view(TkActs())
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v9.5 prêt!")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return
    if await is_immune(msg.author):
        return
    
    c = await gcfg(msg.guild.id)
    content = msg.content
    
    # 🎣 Anti-Phishing
    if c.get('anti_phishing') and check_phishing(content):
        await msg.delete()
        await apply_action(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing")
        return
    
    # 🚨 Anti-Scam
    if c.get('anti_scam') and check_scam(content):
        await msg.delete()
        await apply_action(msg.author, c.get('scam_action', 'mute'), c.get('scam_duration', 60), "Scam")
        return
    
    # 🤬 Anti-Badwords
    if c.get('anti_badwords'):
        badwords = get_json_list(c, 'badwords_list', [])
        is_bad, bad_word = check_badwords(content, badwords)
        if is_bad:
            await msg.delete()
            action = c.get('badwords_action', 'delete')
            if action != 'delete':
                await apply_action(msg.author, action, 0, f"Mot interdit: {bad_word}")
            return
    
    # 🎟️ Anti-Invite
    if c.get('anti_invite') and check_invite(content):
        await msg.delete()
        return
    
    # 🔗 Anti-Liens
    if c.get('anti_link'):
        whitelist = c.get('link_whitelist', '[]')
        if check_link(content, whitelist):
            await msg.delete()
            return
    
    # 🖼️ Anti-Images
    if c.get('anti_image') and msg.attachments:
        allowed = get_json_list(c, 'image_allowed', [])
        for attachment in msg.attachments:
            if check_image_blocked(attachment, allowed):
                await msg.delete()
                return
    
    # 📨 Anti-Spam
    if c.get('anti_spam'):
        if await check_spam(msg, c.get('spam_max_msg', 5), c.get('spam_interval', 5)):
            await msg.delete()
            await apply_action(msg.author, c.get('spam_action', 'mute'), c.get('spam_duration', 10), "Spam")
            return
    
    # 📢 Anti-Mention
    if c.get('anti_mention'):
        if await check_protected_mentions(msg, c.get('mention_protected_roles', '[]'), c.get('mention_protected_users', '[]'), c.get('mention_max_count', 3)):
            await msg.delete()
            await apply_action(msg.author, c.get('mention_action', 'warn'), c.get('mention_duration', 10), "Ping abusif")
            return
    
    # 🔠 Anti-Caps
    if c.get('anti_caps'):
        if check_caps(content, c.get('caps_percent', 70), c.get('caps_min_len', 10)):
            await msg.delete()
            action = c.get('caps_action', 'delete')
            if action != 'delete':
                await apply_action(msg.author, action, 5, "Majuscules")
            return

@bot.event
async def on_member_join(m):
    c = await gcfg(m.guild.id)
    
    # 👶 Anti-NewAccount
    if c.get('anti_newaccount'):
        val = c.get('newaccount_value', 7)
        unit = c.get('newaccount_unit', 'jours')
        if unit == 'semaines':
            days = val * 7
        elif unit == 'mois':
            days = val * 30
        else:
            days = val
        
        age = (now() - m.created_at.replace(tzinfo=timezone.utc)).days
        if age < days:
            try:
                await m.kick(reason=f"Compte trop récent ({age}j < {days}j)")
            except:
                pass
            return
    
    # 👋 Welcome
    if c.get('welcome_on') and c.get('welcome_channel'):
        ch = m.guild.get_channel(c['welcome_channel'])
        if ch:
            txt = c.get('welcome_msg', 'Bienvenue {member}!').format(member=m.mention, server=m.guild.name, count=m.guild.member_count)
            e = discord.Embed(title="👋 Bienvenue!", description=txt, color=C.GREEN)
            e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDES
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Configuration du bot")
async def cfg_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Admin requis", ephemeral=True)
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.embed(), view=v, ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Membre", raison="Raison")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not await has_permission(i.user, 'warn'):
        return await i.response.send_message("❌", ephemeral=True)
    if await is_immune(membre):
        return await i.response.send_message("❌ Immunisé", ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions (guild_id,user_id,mod_id,type,reason) VALUES (?,?,?,?,?)', (i.guild.id, membre.id, i.user.id, 'warn', raison))
        await db.commit()
        cur = await db.execute("SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type='warn'", (i.guild.id, membre.id))
        count = (await cur.fetchone())[0]
    e = discord.Embed(title="⚠️ Warn", color=C.YELLOW)
    e.add_field(name="Membre", value=membre.mention)
    e.add_field(name="Raison", value=raison)
    e.add_field(name="Total", value=f"{count} warn(s)")
    await i.response.send_message(embed=e)
    c = await gcfg(i.guild.id)
    if c.get('warns_ban') and count >= c['warns_ban']:
        await membre.ban(reason=f"Auto: {count} warns")
    elif c.get('warns_kick') and count >= c['warns_kick']:
        await membre.kick(reason=f"Auto: {count} warns")

@bot.tree.command(name="timeout", description="⏰ Timeout un membre")
@app_commands.describe(membre="Membre", duree="Durée (5m, 1h, 1d)", raison="Raison")
async def timeout_cmd(i: discord.Interaction, membre: discord.Member, duree: str, raison: str):
    if not await has_permission(i.user, 'timeout'):
        return await i.response.send_message("❌", ephemeral=True)
    if await is_immune(membre):
        return await i.response.send_message("❌ Immunisé", ephemeral=True)
    match = re.match(r'^(\d+)([smhd])$', duree.lower())
    if not match:
        return await i.response.send_message("❌ Format: 5m, 1h, 1d", ephemeral=True)
    val, unit = int(match.group(1)), match.group(2)
    mult = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    await membre.timeout(timedelta(seconds=val * mult[unit]), reason=raison)
    await i.response.send_message(f"⏰ {membre.mention} timeout **{duree}** - {raison}")

if __name__ == "__main__":
    print("🚀 Démarrage v9.5...")
    bot.run(TOKEN)
