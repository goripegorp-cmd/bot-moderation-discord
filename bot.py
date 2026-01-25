# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v9.6 🌟                                 ║
# ║     Système de Sauvegarde Corrigé + Multi-Mots                                ║
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
#                              💾 DATABASE - CORRIGÉ
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY,
                log_channel INTEGER,
                mod_log_channel INTEGER,
                welcome_channel INTEGER,
                warns_kick INTEGER DEFAULT 0,
                warns_ban INTEGER DEFAULT 0,
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
                link_whitelist TEXT DEFAULT '[]',
                image_allowed TEXT DEFAULT '[]',
                phishing_action TEXT DEFAULT 'ban',
                scam_action TEXT DEFAULT 'mute',
                scam_duration INTEGER DEFAULT 60,
                spam_max_msg INTEGER DEFAULT 5,
                spam_interval INTEGER DEFAULT 5,
                spam_action TEXT DEFAULT 'mute',
                spam_duration INTEGER DEFAULT 10,
                mention_protected_roles TEXT DEFAULT '[]',
                mention_protected_users TEXT DEFAULT '[]',
                mention_max_count INTEGER DEFAULT 3,
                mention_action TEXT DEFAULT 'warn',
                mention_duration INTEGER DEFAULT 10,
                caps_percent INTEGER DEFAULT 70,
                caps_min_len INTEGER DEFAULT 10,
                caps_action TEXT DEFAULT 'delete',
                newaccount_value INTEGER DEFAULT 7,
                newaccount_unit TEXT DEFAULT 'jours',
                badwords_list TEXT DEFAULT '[]',
                badwords_action TEXT DEFAULT 'delete',
                welcome_on INTEGER DEFAULT 0,
                welcome_msg TEXT DEFAULT 'Bienvenue {member} !'
            )
        ''')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS ticket_config (guild_id INTEGER PRIMARY KEY, category_id INTEGER, staff_role_id INTEGER)')
        await db.execute('CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, status TEXT DEFAULT "open", created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        await db.execute('CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        await db.execute('CREATE TABLE IF NOT EXISTS role_permissions (guild_id INTEGER, role_id INTEGER, permission TEXT, PRIMARY KEY(guild_id,role_id,permission))')
        await db.commit()
    print(f"✅ DB: {DB_PATH}")

async def ensure_guild_config(guild_id):
    """S'assure que la config du serveur existe"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT guild_id FROM config WHERE guild_id = ?', (guild_id,))
        exists = await cursor.fetchone()
        if not exists:
            await db.execute('INSERT INTO config (guild_id) VALUES (?)', (guild_id,))
            await db.commit()

async def get_config(guild_id):
    """Récupère la config d'un serveur"""
    await ensure_guild_config(guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM config WHERE guild_id = ?', (guild_id,))
        row = await cursor.fetchone()
        return dict(row) if row else {}

async def save_config(guild_id, key, value):
    """Sauvegarde une valeur de config"""
    await ensure_guild_config(guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f'UPDATE config SET {key} = ? WHERE guild_id = ?', (value, guild_id))
        await db.commit()
        # Vérification
        cursor = await db.execute(f'SELECT {key} FROM config WHERE guild_id = ?', (guild_id,))
        result = await cursor.fetchone()
        print(f"[SAVE] {key} = {result[0] if result else 'ERROR'}")

def parse_json_list(value):
    """Parse une liste JSON de manière sécurisée"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        if not value or value.strip() == '':
            return []
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except:
            return []
    return []

async def get_list_config(guild_id, key):
    """Récupère une liste depuis la config"""
    config = await get_config(guild_id)
    return parse_json_list(config.get(key))

async def save_list_config(guild_id, key, items):
    """Sauvegarde une liste dans la config"""
    json_value = json.dumps(items, ensure_ascii=False)
    await save_config(guild_id, key, json_value)

async def is_immune(member):
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (member.guild.id,))
        immune_ids = [row[0] for row in await cursor.fetchall()]
    return any(role.id in immune_ids for role in member.roles)

async def apply_action(member, action, duration_min, reason):
    try:
        if action == 'delete':
            pass
        elif action == 'mute' and duration_min > 0:
            await member.timeout(timedelta(minutes=duration_min), reason=reason)
        elif action == 'warn':
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT INTO infractions (guild_id, user_id, mod_id, type, reason) VALUES (?, ?, ?, ?, ?)',
                    (member.guild.id, member.id, member.guild.me.id, 'warn', reason))
                await db.commit()
        elif action == 'kick':
            await member.kick(reason=reason)
        elif action == 'ban':
            await member.ban(reason=reason, delete_message_days=1)
    except Exception as e:
        print(f"[ACTION ERROR] {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#                           🚫 ANTI-BADWORDS
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_text(text):
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    
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
    
    cleaned = []
    prev_char = ''
    for char in text:
        if char != prev_char or not char.isalpha():
            cleaned.append(char)
        prev_char = char
    return ''.join(cleaned)

def check_badwords(content, badwords_list):
    if not badwords_list:
        return False, None
    
    original = content.lower()
    normalized = normalize_text(content)
    no_spaces = re.sub(r'[^a-z]', '', normalized)
    
    for word in badwords_list:
        word_clean = word.lower().strip()
        word_norm = normalize_text(word_clean)
        if not word_norm:
            continue
        
        if word_clean in original:
            return True, word
        if word_norm in normalized:
            return True, word
        if word_norm in no_spaces:
            return True, word
        
        if len(word_norm) >= 3:
            pattern = '.*'.join(re.escape(c) for c in word_norm)
            if len(word_norm) >= 4:
                for i in range(len(no_spaces) - len(word_norm) + 1):
                    window = no_spaces[i:i + len(word_norm) * 3]
                    if re.search(pattern, window):
                        return True, word
    
    return False, None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def check_link(content, whitelist):
    urls = re.findall(r'https?://([^\s/]+)', content.lower())
    if not urls:
        return False
    for url in urls:
        if not any(allowed.lower() in url for allowed in whitelist):
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

def check_image_blocked(attachment, allowed_formats):
    ext = attachment.filename.lower().split('.')[-1]
    image_exts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
    if ext not in image_exts:
        return False
    if not allowed_formats:
        return True
    allowed_clean = [f.lower().replace('.', '').strip() for f in allowed_formats]
    return ext not in allowed_clean

async def check_spam(msg, max_msg=5, interval=5):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker:
        spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n - t).total_seconds() < interval]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > max_msg

async def check_protected_mentions(msg, protected_roles, protected_users, max_count):
    count = 0
    for role in msg.role_mentions:
        if role.id in protected_roles:
            count += 1
    for user in msg.mentions:
        if user.id in protected_users:
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
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id
    
    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"Serveur: **{self.guild.name}**\nMembres: **{self.guild.member_count}**"
        if self.guild.icon:
            e.set_thumbnail(url=self.guild.icon.url)
        return e
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def protection(self, interaction, button):
        view = ProtectionPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def logs(self, interaction, button):
        view = LogsPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)
    
    @discord.ui.button(label="Sanctions", emoji="⚖️", style=discord.ButtonStyle.danger, row=0)
    async def sanctions(self, interaction, button):
        view = SanctionsPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)
    
    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def immunites(self, interaction, button):
        view = ImmunityPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def bienvenue(self, interaction, button):
        view = WelcomePanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.primary, row=1)
    async def tickets(self, interaction, button):
        view = TicketsPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close(self, interaction, button):
        await interaction.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL
# ═══════════════════════════════════════════════════════════════════════════════

PROTECTIONS = [
    {"key": "anti_link", "emoji": "🔗", "name": "Anti-Liens", "desc": "Bloque liens non autorisés"},
    {"key": "anti_invite", "emoji": "🎟️", "name": "Anti-Invite", "desc": "Bloque invitations Discord"},
    {"key": "anti_image", "emoji": "🖼️", "name": "Anti-Images", "desc": "Bloque formats d'images"},
    {"key": "anti_phishing", "emoji": "🎣", "name": "Anti-Phishing", "desc": "Détecte faux sites"},
    {"key": "anti_scam", "emoji": "🚨", "name": "Anti-Scam", "desc": "Détecte arnaques"},
    {"key": "anti_spam", "emoji": "📨", "name": "Anti-Spam", "desc": "Limite messages rapides"},
    {"key": "anti_mention", "emoji": "📢", "name": "Anti-Ping", "desc": "Protège des pings"},
    {"key": "anti_caps", "emoji": "🔠", "name": "Anti-Caps", "desc": "Bloque MAJUSCULES"},
    {"key": "anti_badwords", "emoji": "🤬", "name": "Anti-Insultes", "desc": "Bloque mots interdits"},
    {"key": "anti_newaccount", "emoji": "👶", "name": "Anti-NewAccount", "desc": "Bloque comptes récents"},
]

class ProtectionPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
        
        options = [discord.SelectOption(label=p["name"], value=p["key"], emoji=p["emoji"], description=p["desc"]) for p in PROTECTIONS]
        select = Select(placeholder="🛡️ Sélectionner une protection...", options=options, row=0)
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def embed(self):
        config = await get_config(self.guild.id)
        
        def status(key):
            return "✅" if config.get(key) else "❌"
        
        links = parse_json_list(config.get('link_whitelist'))
        images = parse_json_list(config.get('image_allowed'))
        badwords = parse_json_list(config.get('badwords_list'))
        prot_roles = parse_json_list(config.get('mention_protected_roles'))
        prot_users = parse_json_list(config.get('mention_protected_users'))
        
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = f"""```yml
🔗 Anti-Liens     : {status('anti_link')}  │ {len(links)} domaines
🎟️ Anti-Invite    : {status('anti_invite')}  │ Invitations
🖼️ Anti-Images    : {status('anti_image')}  │ {len(images)} formats
🎣 Anti-Phishing  : {status('anti_phishing')}  │ {config.get('phishing_action','ban')}
🚨 Anti-Scam      : {status('anti_scam')}  │ {config.get('scam_action','mute')}
📨 Anti-Spam      : {status('anti_spam')}  │ {config.get('spam_max_msg',5)}msg/{config.get('spam_interval',5)}s
📢 Anti-Ping      : {status('anti_mention')}  │ {len(prot_roles)}R/{len(prot_users)}U
🔠 Anti-Caps      : {status('anti_caps')}  │ {config.get('caps_percent',70)}%
🤬 Anti-Insultes  : {status('anti_badwords')}  │ {len(badwords)} mots
👶 Anti-NewAccount: {status('anti_newaccount')}  │ {config.get('newaccount_value',7)} {config.get('newaccount_unit','jours')}
```
**▼ Sélectionnez une protection**"""
        return e

    async def select_callback(self, interaction):
        key = interaction.data['values'][0]
        prot = next(p for p in PROTECTIONS if p["key"] == key)
        view = ProtectionDetailPanel(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = MainPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🛡️ PROTECTION DETAIL
# ═══════════════════════════════════════════════════════════════════════════════

class ProtectionDetailPanel(View):
    def __init__(self, user, guild, prot):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
        self.prot = prot
        self.key = prot["key"]

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def embed(self):
        config = await get_config(self.guild.id)
        is_on = config.get(self.key, 0)
        
        e = discord.Embed(title=f"{self.prot['emoji']} {self.prot['name']}", color=C.GREEN if is_on else C.RED)
        e.add_field(name="État", value="✅ **ACTIVÉ**" if is_on else "❌ **DÉSACTIVÉ**", inline=False)
        
        if self.key == "anti_link":
            domains = parse_json_list(config.get('link_whitelist'))
            domain_text = "\n".join([f"✅ `{d}`" for d in domains]) if domains else "*Aucun (tous bloqués)*"
            e.add_field(name="📝 Fonctionnement", value="Bloque tous les liens **SAUF** ceux en whitelist", inline=False)
            e.add_field(name=f"✅ Domaines autorisés ({len(domains)})", value=domain_text[:1000], inline=False)
            
        elif self.key == "anti_image":
            formats = parse_json_list(config.get('image_allowed'))
            all_fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
            allowed_text = " ".join([f"✅ `{f}`" for f in formats]) if formats else "*Aucun (tous bloqués)*"
            blocked = [f for f in all_fmts if f not in formats]
            blocked_text = " ".join([f"❌ `{f}`" for f in blocked])
            e.add_field(name="📝 Fonctionnement", value="Bloque les images **SAUF** les formats autorisés", inline=False)
            e.add_field(name=f"✅ Autorisés ({len(formats)})", value=allowed_text, inline=False)
            e.add_field(name=f"❌ Bloqués ({len(blocked)})", value=blocked_text or "*Aucun*", inline=False)
            
        elif self.key == "anti_badwords":
            words = parse_json_list(config.get('badwords_list'))
            words_text = ", ".join([f"`{w}`" for w in words[:30]]) if words else "*Aucun*"
            if len(words) > 30:
                words_text += f" ... +{len(words)-30}"
            e.add_field(name="📝 Fonctionnement", value="Bloque les mots interdits (anti-contournement)", inline=False)
            e.add_field(name=f"🚫 Mots interdits ({len(words)})", value=words_text[:1000], inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{config.get('badwords_action', 'delete')}`", inline=False)
            e.add_field(name="💡 Astuce", value="Ajoutez plusieurs mots d'un coup avec des virgules:\n`mot1,mot2,mot3`", inline=False)
            
        elif self.key == "anti_mention":
            roles = parse_json_list(config.get('mention_protected_roles'))
            users = parse_json_list(config.get('mention_protected_users'))
            role_names = [f"@{self.guild.get_role(r).name}" for r in roles if self.guild.get_role(r)]
            user_names = [f"@{self.guild.get_member(u).display_name}" for u in users if self.guild.get_member(u)]
            e.add_field(name="📝 Fonctionnement", value=f"Sanction après **{config.get('mention_max_count', 3)}** pings", inline=False)
            e.add_field(name=f"🛡️ Rôles ({len(roles)})", value=", ".join(role_names) or "*Aucun*", inline=True)
            e.add_field(name=f"🛡️ Membres ({len(users)})", value=", ".join(user_names) or "*Aucun*", inline=True)
            
        elif self.key == "anti_phishing":
            e.add_field(name="📝 Fonctionnement", value="Détecte les liens de phishing", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{config.get('phishing_action', 'ban')}`", inline=False)
            
        elif self.key == "anti_scam":
            e.add_field(name="📝 Fonctionnement", value="Détecte les arnaques", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{config.get('scam_action', 'mute')}`", inline=False)
            
        elif self.key == "anti_spam":
            e.add_field(name="📝 Fonctionnement", value=f"Bloque si {config.get('spam_max_msg',5)}+ msg en {config.get('spam_interval',5)}s", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{config.get('spam_action', 'mute')}`", inline=False)
            
        elif self.key == "anti_caps":
            e.add_field(name="📝 Fonctionnement", value=f"Bloque si {config.get('caps_percent',70)}%+ majuscules", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{config.get('caps_action', 'delete')}`", inline=False)
            
        elif self.key == "anti_newaccount":
            e.add_field(name="📝 Fonctionnement", value=f"Kick comptes < {config.get('newaccount_value',7)} {config.get('newaccount_unit','jours')}", inline=False)
            
        elif self.key == "anti_invite":
            e.add_field(name="📝 Fonctionnement", value="Bloque toutes les invitations Discord", inline=False)
        
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction, button):
        config = await get_config(self.guild.id)
        new_value = 0 if config.get(self.key) else 1
        await save_config(self.guild.id, self.key, new_value)
        await interaction.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def configure(self, interaction, button):
        if self.key == "anti_link":
            view = LinkConfigPanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        elif self.key == "anti_image":
            view = ImageConfigPanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        elif self.key == "anti_badwords":
            view = BadwordsConfigPanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        elif self.key == "anti_mention":
            view = MentionConfigPanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        elif self.key == "anti_phishing":
            await interaction.response.send_modal(ActionModal(self.guild, "phishing_action", "🎣 Anti-Phishing"))
        elif self.key == "anti_scam":
            await interaction.response.send_modal(ActionModal(self.guild, "scam_action", "🚨 Anti-Scam"))
        elif self.key == "anti_spam":
            await interaction.response.send_modal(SpamModal(self.guild))
        elif self.key == "anti_caps":
            await interaction.response.send_modal(CapsModal(self.guild))
        elif self.key == "anti_newaccount":
            await interaction.response.send_modal(NewAccountModal(self.guild))
        else:
            await interaction.response.send_message("❌ Pas de config", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = ProtectionPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🔗 ANTI-LIENS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfigPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        domains = await get_list_config(self.guild.id, 'link_whitelist')
        e = discord.Embed(title="🔗 Anti-Liens - Configuration", color=C.BLUE)
        domain_text = "\n".join([f"• `{d}`" for d in domains]) if domains else "*Liste vide*"
        e.add_field(name=f"✅ Domaines autorisés ({len(domains)})", value=domain_text[:1000], inline=False)
        e.add_field(name="💡 Info", value="Ajoutez plusieurs domaines avec des virgules:\n`youtube.com,twitter.com,twitch.tv`", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, button):
        await interaction.response.send_modal(AddDomainsModal(self.guild, self.user))

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, interaction, button):
        domains = await get_list_config(self.guild.id, 'link_whitelist')
        if not domains:
            return await interaction.response.send_message("❌ Liste vide", ephemeral=True)
        view = RemoveItemPanel(self.user, self.guild, domains, 'link_whitelist', "🔗 Supprimer domaine")
        await interaction.response.edit_message(embed=view.embed(), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_link")
        view = ProtectionDetailPanel(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class AddDomainsModal(Modal, title="➕ Ajouter domaine(s)"):
    domains_input = TextInput(label="Domaine(s) - séparés par virgule", placeholder="youtube.com,twitter.com,twitch.tv", style=discord.TextStyle.paragraph, max_length=500)
    
    def __init__(self, guild, user):
        super().__init__()
        self.guild = guild
        self.user = user
    
    async def on_submit(self, interaction):
        current = await get_list_config(self.guild.id, 'link_whitelist')
        
        # Parser les nouveaux domaines (virgule, pas d'espace)
        new_domains = [d.strip().lower() for d in self.domains_input.value.replace(' ', '').split(',') if d.strip()]
        
        added = []
        for domain in new_domains:
            if domain and domain not in current:
                current.append(domain)
                added.append(domain)
        
        await save_list_config(self.guild.id, 'link_whitelist', current)
        
        if added:
            await interaction.response.send_message(f"✅ Ajouté(s): `{', '.join(added)}`\nTotal: **{len(current)}** domaines", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Aucun nouveau domaine ajouté (déjà existants)", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🖼️ ANTI-IMAGES CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ImageConfigPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        formats = await get_list_config(self.guild.id, 'image_allowed')
        all_fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        
        e = discord.Embed(title="🖼️ Anti-Images - Configuration", color=C.BLUE)
        allowed_text = " ".join([f"✅ `{f}`" for f in formats]) if formats else "*Aucun (tout bloqué)*"
        blocked = [f for f in all_fmts if f not in formats]
        blocked_text = " ".join([f"❌ `{f}`" for f in blocked])
        
        e.add_field(name=f"✅ Autorisés ({len(formats)})", value=allowed_text, inline=False)
        e.add_field(name=f"❌ Bloqués ({len(blocked)})", value=blocked_text or "*Aucun*", inline=False)
        return e

    @discord.ui.button(label="➕ Autoriser", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, button):
        current = await get_list_config(self.guild.id, 'image_allowed')
        all_fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        available = [f for f in all_fmts if f not in current]
        
        if not available:
            return await interaction.response.send_message("✅ Tous autorisés", ephemeral=True)
        
        options = [discord.SelectOption(label=f.upper(), value=f) for f in available]
        view = AddFormatPanel(self.user, self.guild, options)
        await interaction.response.edit_message(embed=discord.Embed(title="➕ Autoriser format", color=C.GREEN), view=view)

    @discord.ui.button(label="➖ Bloquer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, interaction, button):
        current = await get_list_config(self.guild.id, 'image_allowed')
        if not current:
            return await interaction.response.send_message("❌ Liste vide", ephemeral=True)
        
        options = [discord.SelectOption(label=f.upper(), value=f) for f in current]
        view = RemoveFormatPanel(self.user, self.guild, options)
        await interaction.response.edit_message(embed=discord.Embed(title="➖ Bloquer format", color=C.RED), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_image")
        view = ProtectionDetailPanel(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class AddFormatPanel(View):
    def __init__(self, user, guild, options):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        select = Select(placeholder="Format à autoriser...", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction):
        fmt = interaction.data['values'][0]
        current = await get_list_config(self.guild.id, 'image_allowed')
        if fmt not in current:
            current.append(fmt)
            await save_list_config(self.guild.id, 'image_allowed', current)
        
        view = ImageConfigPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = ImageConfigPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class RemoveFormatPanel(View):
    def __init__(self, user, guild, options):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        select = Select(placeholder="Format à bloquer...", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction):
        fmt = interaction.data['values'][0]
        current = await get_list_config(self.guild.id, 'image_allowed')
        if fmt in current:
            current.remove(fmt)
            await save_list_config(self.guild.id, 'image_allowed', current)
        
        view = ImageConfigPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = ImageConfigPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🤬 ANTI-BADWORDS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class BadwordsConfigPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        words = await get_list_config(self.guild.id, 'badwords_list')
        config = await get_config(self.guild.id)
        action = config.get('badwords_action', 'delete')
        
        e = discord.Embed(title="🤬 Anti-Insultes - Configuration", color=C.BLUE)
        e.add_field(name="⚡ Sanction", value=f"`{action}`", inline=False)
        
        words_text = ", ".join([f"`{w}`" for w in words[:40]]) if words else "*Aucun mot*"
        if len(words) > 40:
            words_text += f" ... +{len(words)-40}"
        e.add_field(name=f"🚫 Mots interdits ({len(words)})", value=words_text[:1000], inline=False)
        e.add_field(name="💡 Astuce", value="Ajoutez plusieurs mots d'un coup:\n`insulte1,insulte2,insulte3` (sans espaces)", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter mot(s)", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, button):
        await interaction.response.send_modal(AddBadwordsModal(self.guild, self.user))

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, interaction, button):
        words = await get_list_config(self.guild.id, 'badwords_list')
        if not words:
            return await interaction.response.send_message("❌ Liste vide", ephemeral=True)
        view = RemoveItemPanel(self.user, self.guild, words, 'badwords_list', "🤬 Supprimer mot")
        await interaction.response.edit_message(embed=view.embed(), view=view)

    @discord.ui.button(label="⚙️ Sanction", style=discord.ButtonStyle.secondary, row=0)
    async def config_action(self, interaction, button):
        await interaction.response.send_modal(BadwordActionModal(self.guild))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_badwords")
        view = ProtectionDetailPanel(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class AddBadwordsModal(Modal, title="➕ Ajouter mot(s) interdit(s)"):
    words_input = TextInput(label="Mot(s) - séparés par virgule, sans espace", placeholder="mot1,mot2,mot3", style=discord.TextStyle.paragraph, max_length=500)
    
    def __init__(self, guild, user):
        super().__init__()
        self.guild = guild
        self.user = user
    
    async def on_submit(self, interaction):
        current = await get_list_config(self.guild.id, 'badwords_list')
        
        # Parser les mots (virgule, pas d'espace)
        new_words = [w.strip().lower() for w in self.words_input.value.replace(' ', '').split(',') if w.strip()]
        
        added = []
        for word in new_words:
            if word and word not in current:
                current.append(word)
                added.append(word)
        
        await save_list_config(self.guild.id, 'badwords_list', current)
        
        if added:
            await interaction.response.send_message(f"✅ Ajouté(s): `{', '.join(added)}`\nTotal: **{len(current)}** mots interdits", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Aucun nouveau mot ajouté", ephemeral=True)

class BadwordActionModal(Modal, title="⚙️ Sanction Anti-Insultes"):
    action = TextInput(label="Sanction (delete / warn / kick)", placeholder="delete", default="delete", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    
    async def on_submit(self, interaction):
        action = self.action.value.lower().strip()
        if action not in ['delete', 'warn', 'kick']:
            action = 'delete'
        await save_config(self.guild.id, 'badwords_action', action)
        await interaction.response.send_message(f"✅ Sanction: `{action}`", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                    📢 ANTI-MENTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class MentionConfigPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        config = await get_config(self.guild.id)
        roles = parse_json_list(config.get('mention_protected_roles'))
        users = parse_json_list(config.get('mention_protected_users'))
        
        role_names = [f"@{self.guild.get_role(r).name}" for r in roles if self.guild.get_role(r)]
        user_names = [f"@{self.guild.get_member(u).display_name}" for u in users if self.guild.get_member(u)]
        
        e = discord.Embed(title="📢 Anti-Ping - Configuration", color=C.BLUE)
        e.add_field(name="📝 Sanction après", value=f"**{config.get('mention_max_count', 3)}** pings → `{config.get('mention_action', 'warn')}`", inline=False)
        e.add_field(name=f"🛡️ Rôles ({len(roles)})", value=", ".join(role_names) or "*Aucun*", inline=True)
        e.add_field(name=f"🛡️ Membres ({len(users)})", value=", ".join(user_names) or "*Aucun*", inline=True)
        return e

    @discord.ui.button(label="➕ Rôle", emoji="🛡️", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, interaction, button):
        roles = [r for r in self.guild.roles[1:] if not r.is_bot_managed()][:25]
        if not roles:
            return await interaction.response.send_message("❌ Aucun rôle", ephemeral=True)
        options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        view = AddProtectedRolePanel(self.user, self.guild, options)
        await interaction.response.edit_message(embed=discord.Embed(title="➕ Ajouter rôle protégé", color=C.GREEN), view=view)

    @discord.ui.button(label="➖ Rôle", style=discord.ButtonStyle.danger, row=0)
    async def remove_role(self, interaction, button):
        roles = await get_list_config(self.guild.id, 'mention_protected_roles')
        if not roles:
            return await interaction.response.send_message("❌ Aucun rôle", ephemeral=True)
        options = [discord.SelectOption(label=f"@{self.guild.get_role(r).name}"[:25], value=str(r)) for r in roles if self.guild.get_role(r)]
        if options:
            view = RemoveProtectedRolePanel(self.user, self.guild, options)
            await interaction.response.edit_message(embed=discord.Embed(title="➖ Retirer rôle", color=C.RED), view=view)

    @discord.ui.button(label="➕ Membre", emoji="👤", style=discord.ButtonStyle.success, row=1)
    async def add_user(self, interaction, button):
        await interaction.response.send_modal(AddProtectedUserModal(self.guild))

    @discord.ui.button(label="➖ Membre", style=discord.ButtonStyle.danger, row=1)
    async def remove_user(self, interaction, button):
        users = await get_list_config(self.guild.id, 'mention_protected_users')
        if not users:
            return await interaction.response.send_message("❌ Aucun membre", ephemeral=True)
        options = [discord.SelectOption(label=f"@{self.guild.get_member(u).display_name}"[:25], value=str(u)) for u in users if self.guild.get_member(u)]
        if options:
            view = RemoveProtectedUserPanel(self.user, self.guild, options)
            await interaction.response.edit_message(embed=discord.Embed(title="➖ Retirer membre", color=C.RED), view=view)

    @discord.ui.button(label="⚙️ Sanction", style=discord.ButtonStyle.secondary, row=2)
    async def config_sanction(self, interaction, button):
        await interaction.response.send_modal(MentionSanctionModal(self.guild))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_mention")
        view = ProtectionDetailPanel(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class AddProtectedRolePanel(View):
    def __init__(self, user, guild, options):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        select = Select(placeholder="Rôle...", options=options)
        select.callback = self.callback
        self.add_item(select)
    async def callback(self, i):
        rid = int(i.data['values'][0])
        current = await get_list_config(self.guild.id, 'mention_protected_roles')
        if rid not in current:
            current.append(rid)
            await save_list_config(self.guild.id, 'mention_protected_roles', current)
        v = MentionConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MentionConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RemoveProtectedRolePanel(View):
    def __init__(self, user, guild, options):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        select = Select(placeholder="Rôle...", options=options)
        select.callback = self.callback
        self.add_item(select)
    async def callback(self, i):
        rid = int(i.data['values'][0])
        current = await get_list_config(self.guild.id, 'mention_protected_roles')
        if rid in current:
            current.remove(rid)
            await save_list_config(self.guild.id, 'mention_protected_roles', current)
        v = MentionConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MentionConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddProtectedUserModal(Modal, title="➕ Ajouter membre protégé"):
    user_id = TextInput(label="ID du membre", placeholder="Clic droit > Copier l'ID", max_length=20)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        try:
            uid = int(self.user_id.value)
            member = i.guild.get_member(uid)
            if not member:
                return await i.response.send_message("❌ Introuvable", ephemeral=True)
        except:
            return await i.response.send_message("❌ ID invalide", ephemeral=True)
        current = await get_list_config(self.guild.id, 'mention_protected_users')
        if uid not in current:
            current.append(uid)
            await save_list_config(self.guild.id, 'mention_protected_users', current)
        await i.response.send_message(f"✅ {member.mention} protégé", ephemeral=True)

class RemoveProtectedUserPanel(View):
    def __init__(self, user, guild, options):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        select = Select(placeholder="Membre...", options=options)
        select.callback = self.callback
        self.add_item(select)
    async def callback(self, i):
        uid = int(i.data['values'][0])
        current = await get_list_config(self.guild.id, 'mention_protected_users')
        if uid in current:
            current.remove(uid)
            await save_list_config(self.guild.id, 'mention_protected_users', current)
        v = MentionConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MentionConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class MentionSanctionModal(Modal, title="⚙️ Sanction"):
    max_count = TextInput(label="Nombre de pings avant sanction", placeholder="3", default="3", max_length=3)
    action = TextInput(label="Sanction (warn/mute/kick/ban)", placeholder="warn", default="warn", max_length=10)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        count = int(self.max_count.value) if self.max_count.value.isdigit() else 3
        action = self.action.value.lower().strip()
        if action not in ['warn', 'mute', 'kick', 'ban']:
            action = 'warn'
        await save_config(self.guild.id, 'mention_max_count', count)
        await save_config(self.guild.id, 'mention_action', action)
        await i.response.send_message(f"✅ {count} pings → `{action}`", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🗑️ REMOVE ITEM PANEL (Generic)
# ═══════════════════════════════════════════════════════════════════════════════

class RemoveItemPanel(View):
    def __init__(self, user, guild, items, config_key, title):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        self.config_key = config_key
        self.title = title
        options = [discord.SelectOption(label=str(item)[:25], value=str(item)) for item in items[:25]]
        select = Select(placeholder="Sélectionner...", options=options)
        select.callback = self.callback
        self.add_item(select)

    def embed(self):
        return discord.Embed(title=self.title, color=C.RED)

    async def callback(self, interaction):
        item = interaction.data['values'][0]
        current = await get_list_config(self.guild.id, self.config_key)
        
        # Convertir en int si c'est un ID
        try:
            item_to_remove = int(item)
        except:
            item_to_remove = item
        
        if item_to_remove in current:
            current.remove(item_to_remove)
        elif item in current:
            current.remove(item)
            
        await save_list_config(self.guild.id, self.config_key, current)
        await interaction.response.send_message(f"✅ `{item}` supprimé", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        if self.config_key == 'link_whitelist':
            view = LinkConfigPanel(self.user, self.guild)
        elif self.config_key == 'badwords_list':
            view = BadwordsConfigPanel(self.user, self.guild)
        else:
            view = ProtectionPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                    ⚙️ OTHER MODALS
# ═══════════════════════════════════════════════════════════════════════════════

class ActionModal(Modal):
    action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="ban", default="ban", max_length=10)
    def __init__(self, guild, config_key, title):
        super().__init__(title=title)
        self.guild, self.config_key = guild, config_key
    async def on_submit(self, i):
        action = self.action.value.lower().strip()
        if action not in ['delete', 'mute', 'kick', 'ban']:
            action = 'ban'
        await save_config(self.guild.id, self.config_key, action)
        await i.response.send_message(f"✅ Sanction: `{action}`", ephemeral=True)

class SpamModal(Modal, title="📨 Anti-Spam"):
    max_msg = TextInput(label="Messages max", placeholder="5", default="5", max_length=3)
    interval = TextInput(label="Intervalle (secondes)", placeholder="5", default="5", max_length=3)
    action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="mute", default="mute", max_length=10)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        mm = int(self.max_msg.value) if self.max_msg.value.isdigit() else 5
        itv = int(self.interval.value) if self.interval.value.isdigit() else 5
        action = self.action.value.lower().strip()
        if action not in ['delete', 'mute', 'kick', 'ban']:
            action = 'mute'
        await save_config(self.guild.id, 'spam_max_msg', mm)
        await save_config(self.guild.id, 'spam_interval', itv)
        await save_config(self.guild.id, 'spam_action', action)
        await i.response.send_message(f"✅ {mm}msg/{itv}s → `{action}`", ephemeral=True)

class CapsModal(Modal, title="🔠 Anti-Caps"):
    percent = TextInput(label="Pourcentage max", placeholder="70", default="70", max_length=3)
    action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="delete", default="delete", max_length=10)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        pct = int(self.percent.value) if self.percent.value.isdigit() else 70
        action = self.action.value.lower().strip()
        if action not in ['delete', 'mute', 'kick', 'ban']:
            action = 'delete'
        await save_config(self.guild.id, 'caps_percent', pct)
        await save_config(self.guild.id, 'caps_action', action)
        await i.response.send_message(f"✅ {pct}% → `{action}`", ephemeral=True)

class NewAccountModal(Modal, title="👶 Anti-NewAccount"):
    value = TextInput(label="Âge minimum", placeholder="7", default="7", max_length=4)
    unit = TextInput(label="Unité (jours/semaines/mois)", placeholder="jours", default="jours", max_length=10)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        val = int(self.value.value) if self.value.value.isdigit() else 7
        unit = self.unit.value.lower().strip()
        if unit not in ['jours', 'semaines', 'mois']:
            unit = 'jours'
        await save_config(self.guild.id, 'newaccount_value', val)
        await save_config(self.guild.id, 'newaccount_unit', unit)
        await i.response.send_message(f"✅ < {val} {unit} → kick", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                    OTHER PANELS (Logs, Sanctions, etc.)
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
        channels = [c for c in guild.text_channels][:25]
        if channels:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
            s1 = Select(placeholder="📝 Logs généraux...", options=opts, row=1)
            s1.callback = lambda i: self.set_log(i, 'log_channel')
            self.add_item(s1)
            s2 = Select(placeholder="⚔️ Logs modération...", options=opts.copy(), row=2)
            s2.callback = lambda i: self.set_log(i, 'mod_log_channel')
            self.add_item(s2)
    async def set_log(self, i, key):
        await save_config(self.guild.id, key, int(i.data['values'][0]))
        await i.response.send_message("✅", ephemeral=True)
    async def embed(self):
        config = await get_config(self.guild.id)
        lc = self.guild.get_channel(config.get('log_channel'))
        mc = self.guild.get_channel(config.get('mod_log_channel'))
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        e.description = f"📝 Généraux: {lc.mention if lc else '❌'}\n⚔️ Modération: {mc.mention if mc else '❌'}"
        return e
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class SanctionsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
    async def embed(self):
        config = await get_config(self.guild.id)
        e = discord.Embed(title="⚖️ Sanctions Auto", color=C.PINK)
        wk, wb = config.get('warns_kick', 0), config.get('warns_ban', 0)
        e.description = f"👢 Kick: **{wk}** warns {'(off)' if not wk else ''}\n🔨 Ban: **{wb}** warns {'(off)' if not wb else ''}"
        return e
    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.primary)
    async def cfg(self, i, b):
        await i.response.send_modal(SanctionsModal(self.guild))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class SanctionsModal(Modal, title="⚖️ Sanctions"):
    wk = TextInput(label="Warns pour Kick (0=off)", placeholder="3", default="0", max_length=2)
    wb = TextInput(label="Warns pour Ban (0=off)", placeholder="5", default="0", max_length=2)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        k = int(self.wk.value) if self.wk.value.isdigit() else 0
        b = int(self.wb.value) if self.wb.value.isdigit() else 0
        await save_config(self.guild.id, 'warns_kick', k)
        await save_config(self.guild.id, 'warns_ban', b)
        await i.response.send_message(f"✅ Kick: {k} | Ban: {b}", ephemeral=True)

class ImmunityPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
        roles = [r for r in guild.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
            sel = Select(placeholder="👑 Ajouter...", options=opts, row=1)
            sel.callback = self.add
            self.add_item(sel)
    async def add(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES (?, ?)', (self.guild.id, int(i.data['values'][0])))
            await db.commit()
        await i.response.send_message("✅", ephemeral=True)
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (self.guild.id,))
            ids = [r[0] for r in await cur.fetchall()]
        roles = [self.guild.get_role(rid) for rid in ids if self.guild.get_role(rid)]
        e = discord.Embed(title="👑 Rôles Immunisés", color=C.YELLOW)
        e.description = ", ".join([r.mention for r in roles]) if roles else "*Aucun*"
        return e
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class WelcomePanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
        channels = [c for c in guild.text_channels][:25]
        if channels:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
            sel = Select(placeholder="👋 Salon...", options=opts, row=2)
            sel.callback = self.set_channel
            self.add_item(sel)
    async def set_channel(self, i):
        await save_config(self.guild.id, 'welcome_channel', int(i.data['values'][0]))
        await i.response.send_message("✅", ephemeral=True)
    async def embed(self):
        config = await get_config(self.guild.id)
        ch = self.guild.get_channel(config.get('welcome_channel'))
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"État: {'✅' if config.get('welcome_on') else '❌'}\nSalon: {ch.mention if ch else '❌'}"
        return e
    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        config = await get_config(self.guild.id)
        await save_config(self.guild.id, 'welcome_on', 0 if config.get('welcome_on') else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎫 TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

class TicketsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
        cats = [c for c in guild.categories][:25]
        if cats:
            opts = [discord.SelectOption(label=c.name[:25], value=str(c.id)) for c in cats]
            sel = Select(placeholder="📁 Catégorie...", options=opts, row=1)
            sel.callback = lambda i: self.set_config(i, 'category_id')
            self.add_item(sel)
        roles = [r for r in guild.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
            sel = Select(placeholder="👮 Staff...", options=opts, row=2)
            sel.callback = lambda i: self.set_config(i, 'staff_role_id')
            self.add_item(sel)
    async def set_config(self, i, key):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO ticket_config (guild_id) VALUES (?)', (self.guild.id,))
            await db.execute(f'UPDATE ticket_config SET {key} = ? WHERE guild_id = ?', (int(i.data['values'][0]), self.guild.id))
            await db.commit()
        await i.response.send_message("✅", ephemeral=True)
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM ticket_config WHERE guild_id = ?', (self.guild.id,))
            row = await cur.fetchone()
            tc = dict(row) if row else {}
        cat = self.guild.get_channel(tc.get('category_id'))
        rl = self.guild.get_role(tc.get('staff_role_id'))
        e = discord.Embed(title="🎫 Tickets", color=C.PURPLE)
        e.description = f"📁 Catégorie: {cat.name if cat else '❌'}\n👮 Staff: {rl.mention if rl else '❌'}"
        return e
    @discord.ui.button(label="📤 Déployer", style=discord.ButtonStyle.success, row=0)
    async def deploy(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT category_id, staff_role_id FROM ticket_config WHERE guild_id = ?', (self.guild.id,))
            row = await cur.fetchone()
        if not row or not row[0] or not row[1]:
            return await i.response.send_message("❌ Config incomplète", ephemeral=True)
        channels = [c for c in self.guild.text_channels][:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
        view = DeployTicketPanel(self.user, self.guild, opts)
        await i.response.edit_message(embed=discord.Embed(title="📤 Choisir salon", color=C.GREEN), view=view)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class DeployTicketPanel(View):
    def __init__(self, user, guild, opts):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        sel = Select(placeholder="Salon...", options=opts)
        sel.callback = self.deploy
        self.add_item(sel)
    async def deploy(self, i):
        ch = self.guild.get_channel(int(i.data['values'][0]))
        e = discord.Embed(title="🎫 Support", description="Cliquez pour créer un ticket", color=C.PURPLE)
        await ch.send(embed=e, view=TicketButton(self.guild.id))
        await i.response.send_message(f"✅ Déployé dans {ch.mention}", ephemeral=True)

class TicketButton(View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
    @discord.ui.button(label="📩 Créer", style=discord.ButtonStyle.success, custom_id="ticket_create")
    async def create(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT category_id, staff_role_id FROM ticket_config WHERE guild_id = ?', (i.guild.id,))
            row = await cur.fetchone()
        if not row:
            return await i.response.send_message("❌", ephemeral=True)
        cat, staff = i.guild.get_channel(row[0]), i.guild.get_role(row[1])
        if not cat or not staff:
            return await i.response.send_message("❌", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id = ?', (i.guild.id,))
            n = (await cur.fetchone())[0] + 1
        overwrites = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            staff: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        ch = await cat.create_text_channel(name=f"ticket-{i.user.name[:10]}-{n}", overwrites=overwrites)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO tickets (guild_id, channel_id, user_id) VALUES (?, ?, ?)', (i.guild.id, ch.id, i.user.id))
            await db.commit()
        await ch.send(content=f"{i.user.mention} {staff.mention}", embed=discord.Embed(title="🎫 Ticket", color=C.GREEN), view=TicketActions())
        await i.response.send_message(f"✅ {ch.mention}", ephemeral=True)

class TicketActions(View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, i, b):
        await i.response.send_message("🔒 Fermeture...")
        await asyncio.sleep(2)
        try:
            await i.channel.delete()
        except:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(TicketButton(0))
    bot.add_view(TicketActions())
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v9.6 prêt!")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return
    if await is_immune(msg.author):
        return
    
    config = await get_config(msg.guild.id)
    content = msg.content
    
    # 🎣 Anti-Phishing
    if config.get('anti_phishing') and check_phishing(content):
        await msg.delete()
        await apply_action(msg.author, config.get('phishing_action', 'ban'), 60, "Phishing")
        return
    
    # 🚨 Anti-Scam
    if config.get('anti_scam') and check_scam(content):
        await msg.delete()
        await apply_action(msg.author, config.get('scam_action', 'mute'), config.get('scam_duration', 60), "Scam")
        return
    
    # 🤬 Anti-Badwords
    if config.get('anti_badwords'):
        badwords = parse_json_list(config.get('badwords_list'))
        is_bad, word = check_badwords(content, badwords)
        if is_bad:
            await msg.delete()
            action = config.get('badwords_action', 'delete')
            if action != 'delete':
                await apply_action(msg.author, action, 0, f"Mot interdit")
            return
    
    # 🎟️ Anti-Invite
    if config.get('anti_invite') and check_invite(content):
        await msg.delete()
        return
    
    # 🔗 Anti-Liens
    if config.get('anti_link'):
        whitelist = parse_json_list(config.get('link_whitelist'))
        if check_link(content, whitelist):
            await msg.delete()
            return
    
    # 🖼️ Anti-Images
    if config.get('anti_image') and msg.attachments:
        allowed = parse_json_list(config.get('image_allowed'))
        for att in msg.attachments:
            if check_image_blocked(att, allowed):
                await msg.delete()
                return
    
    # 📨 Anti-Spam
    if config.get('anti_spam'):
        if await check_spam(msg, config.get('spam_max_msg', 5), config.get('spam_interval', 5)):
            await msg.delete()
            await apply_action(msg.author, config.get('spam_action', 'mute'), config.get('spam_duration', 10), "Spam")
            return
    
    # 📢 Anti-Mention
    if config.get('anti_mention'):
        prot_roles = parse_json_list(config.get('mention_protected_roles'))
        prot_users = parse_json_list(config.get('mention_protected_users'))
        if await check_protected_mentions(msg, prot_roles, prot_users, config.get('mention_max_count', 3)):
            await msg.delete()
            await apply_action(msg.author, config.get('mention_action', 'warn'), config.get('mention_duration', 10), "Ping abusif")
            return
    
    # 🔠 Anti-Caps
    if config.get('anti_caps'):
        if check_caps(content, config.get('caps_percent', 70), config.get('caps_min_len', 10)):
            await msg.delete()
            action = config.get('caps_action', 'delete')
            if action != 'delete':
                await apply_action(msg.author, action, 5, "Majuscules")
            return

@bot.event
async def on_member_join(member):
    config = await get_config(member.guild.id)
    
    # 👶 Anti-NewAccount
    if config.get('anti_newaccount'):
        val = config.get('newaccount_value', 7)
        unit = config.get('newaccount_unit', 'jours')
        if unit == 'semaines':
            days = val * 7
        elif unit == 'mois':
            days = val * 30
        else:
            days = val
        
        age = (now() - member.created_at.replace(tzinfo=timezone.utc)).days
        if age < days:
            try:
                await member.kick(reason=f"Compte trop récent ({age}j < {days}j)")
            except:
                pass
            return
    
    # 👋 Welcome
    if config.get('welcome_on') and config.get('welcome_channel'):
        ch = member.guild.get_channel(config['welcome_channel'])
        if ch:
            txt = config.get('welcome_msg', 'Bienvenue {member}!').format(
                member=member.mention, server=member.guild.name, count=member.guild.member_count
            )
            e = discord.Embed(title="👋 Bienvenue!", description=txt, color=C.GREEN)
            e.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=e)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Configuration du bot")
async def configure_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("❌ Admin requis", ephemeral=True)
    view = MainPanel(interaction.user, interaction.guild)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Membre", raison="Raison")
async def warn_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message("❌", ephemeral=True)
    if await is_immune(membre):
        return await interaction.response.send_message("❌ Immunisé", ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions (guild_id, user_id, mod_id, type, reason) VALUES (?, ?, ?, ?, ?)',
            (interaction.guild.id, membre.id, interaction.user.id, 'warn', raison))
        await db.commit()
        cur = await db.execute("SELECT COUNT(*) FROM infractions WHERE guild_id = ? AND user_id = ? AND type = 'warn'",
            (interaction.guild.id, membre.id))
        count = (await cur.fetchone())[0]
    e = discord.Embed(title="⚠️ Warn", color=C.YELLOW)
    e.add_field(name="Membre", value=membre.mention)
    e.add_field(name="Raison", value=raison)
    e.add_field(name="Total", value=f"{count} warn(s)")
    await interaction.response.send_message(embed=e)
    config = await get_config(interaction.guild.id)
    if config.get('warns_ban') and count >= config['warns_ban']:
        await membre.ban(reason=f"Auto: {count} warns")
    elif config.get('warns_kick') and count >= config['warns_kick']:
        await membre.kick(reason=f"Auto: {count} warns")

@bot.tree.command(name="timeout", description="⏰ Timeout un membre")
@app_commands.describe(membre="Membre", duree="Durée (5m, 1h, 1d)", raison="Raison")
async def timeout_cmd(interaction: discord.Interaction, membre: discord.Member, duree: str, raison: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message("❌", ephemeral=True)
    if await is_immune(membre):
        return await interaction.response.send_message("❌ Immunisé", ephemeral=True)
    match = re.match(r'^(\d+)([smhd])$', duree.lower())
    if not match:
        return await interaction.response.send_message("❌ Format: 5m, 1h, 1d", ephemeral=True)
    val, unit = int(match.group(1)), match.group(2)
    mult = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    await membre.timeout(timedelta(seconds=val * mult[unit]), reason=raison)
    await interaction.response.send_message(f"⏰ {membre.mention} timeout **{duree}** - {raison}")

if __name__ == "__main__":
    print("🚀 Démarrage v9.6...")
    bot.run(TOKEN)
