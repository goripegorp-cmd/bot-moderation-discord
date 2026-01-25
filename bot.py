# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v10.1 🌟                                ║
# ║     Correction Tenor + Système Tickets Complet                                ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput
import aiosqlite
import os
import re
import json
import asyncio
import unicodedata
import traceback
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
DB_PATH = '/data/bot.db' if os.path.exists('/data') else 'bot.db'
print(f"📁 Database: {DB_PATH}")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}
mention_tracker = {}

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PINK=0xEB459E; PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22

PHISHING_DOMAINS = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com','discordi.gift','discord-app.com','steamcommunity.ru','store-steampowered.com']
SCAM_PATTERNS = [r'free\s*nitro',r'discord\s*nitro\s*free',r'steam\s*gift',r'claim\s*your\s*gift',r'@everyone.*http',r'airdrop.*nitro']

LEET_MAP = {
    'a': ['a','@','4','à','á','â','ä','α'], 'b': ['b','8','ß'], 'c': ['c','(','ç'],
    'e': ['e','3','€','è','é','ê','ë'], 'g': ['g','9','6'], 'i': ['i','1','!','|','ì','í'],
    'l': ['l','1','|'], 'o': ['o','0','ò','ó','ô','ö'], 's': ['s','$','5'],
    't': ['t','7','+'], 'u': ['u','ù','ú','û','ü'], 'z': ['z','2'],
}

def now():
    return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY, data TEXT DEFAULT '{}'
        )''')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_users (guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id,user_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        await db.execute('''CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            user_id INTEGER,
            claimed_by INTEGER DEFAULT 0,
            description TEXT,
            status TEXT DEFAULT 'open',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS ticket_config (
            guild_id INTEGER PRIMARY KEY,
            panel_channel_id INTEGER DEFAULT 0,
            category_id INTEGER DEFAULT 0,
            staff_role_id INTEGER DEFAULT 0,
            panel_message_id INTEGER DEFAULT 0
        )''')
        await db.commit()
    print("✅ Database OK")

async def db_get(guild_id: int) -> dict:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM guild_config WHERE guild_id = ?', (guild_id,)) as cur:
                row = await cur.fetchone()
                if row and row[0]:
                    return json.loads(row[0])
    except Exception as e:
        print(f"[DB_GET ERROR] {e}")
    return {}

async def db_set(guild_id: int, key: str, value) -> bool:
    try:
        data = await db_get(guild_id)
        data[key] = value
        json_data = json.dumps(data, ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO guild_config (guild_id, data) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET data = ?', 
                (guild_id, json_data, json_data))
            await db.commit()
        return True
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return False

def get_default():
    return {
        'anti_link': 0, 'anti_invite': 0, 'anti_image': 0, 'anti_phishing': 1,
        'anti_scam': 1, 'anti_spam': 0, 'anti_mention': 0, 'anti_caps': 0,
        'anti_newaccount': 0, 'anti_badwords': 0,
        'link_whitelist': [], 'image_allowed': [], 'badwords_list': [],
        'mention_protected_roles': [], 'mention_protected_users': [],
        'link_allowed_channels': [], 'image_allowed_channels': [],
        'phishing_action': 'ban', 'scam_action': 'mute', 'scam_duration': 60,
        'spam_max_msg': 5, 'spam_interval': 5, 'spam_action': 'mute', 'spam_duration': 10,
        'mention_max_count': 3, 'mention_action': 'warn',
        'caps_percent': 70, 'caps_min_len': 10, 'caps_action': 'delete',
        'newaccount_value': 7, 'newaccount_unit': 'jours',
        'badwords_action': 'delete',
        'log_anti_link': 0, 'log_anti_invite': 0, 'log_anti_image': 0,
        'log_anti_phishing': 0, 'log_anti_scam': 0, 'log_anti_spam': 0,
        'log_anti_mention': 0, 'log_anti_caps': 0, 'log_anti_badwords': 0,
        'log_anti_newaccount': 0,
        'channel_configs': {},
        'welcome_on': 0, 'welcome_channel': 0, 'welcome_msg': 'Bienvenue {member}!'
    }

async def cfg(guild_id: int) -> dict:
    data = await db_get(guild_id)
    defaults = get_default()
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
    return data

async def is_immune(member, protection_key):
    if protection_key != 'anti_phishing':
        if member.guild_permissions.administrator or member.id == member.guild.owner_id:
            return True
    no_immunity = ['anti_phishing', 'anti_link', 'anti_invite']
    if protection_key in no_immunity:
        return False
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (member.guild.id,)) as cur:
                rows = await cur.fetchall()
                immune_role_ids = [r[0] for r in rows]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id = ?', (member.guild.id,)) as cur:
                rows = await cur.fetchall()
                immune_user_ids = [r[0] for r in rows]
        if any(role.id in immune_role_ids for role in member.roles):
            return True
        if member.id in immune_user_ids:
            return True
    except:
        pass
    return False

async def apply_sanction(member, action, duration, reason, guild):
    try:
        if action == 'warn':
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT INTO infractions (guild_id, user_id, mod_id, type, reason) VALUES (?, ?, ?, ?, ?)',
                    (guild.id, member.id, guild.me.id, 'warn', reason))
                await db.commit()
        elif action == 'mute':
            await member.timeout(timedelta(minutes=duration), reason=reason)
        elif action == 'kick':
            await member.kick(reason=reason)
        elif action == 'ban':
            await member.ban(reason=reason, delete_message_days=1)
    except Exception as e:
        print(f"[SANCTION ERROR] {e}")

async def send_protection_log(guild, protection_key, member, message, reason, extra_info=None):
    try:
        c = await cfg(guild.id)
        log_channel_id = c.get(f'log_{protection_key}', 0)
        if not log_channel_id:
            return
        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return
        emojis = {'anti_link': '🔗', 'anti_invite': '🎟️', 'anti_image': '🖼️', 'anti_phishing': '🎣', 'anti_scam': '🚨', 'anti_spam': '📨', 'anti_mention': '📢', 'anti_caps': '🔠', 'anti_badwords': '🤬', 'anti_newaccount': '👶'}
        names = {'anti_link': 'Anti-Liens', 'anti_invite': 'Anti-Invite', 'anti_image': 'Anti-Images', 'anti_phishing': 'Anti-Phishing', 'anti_scam': 'Anti-Scam', 'anti_spam': 'Anti-Spam', 'anti_mention': 'Anti-Ping', 'anti_caps': 'Anti-Caps', 'anti_badwords': 'Anti-Insultes', 'anti_newaccount': 'Anti-NewAccount'}
        e = discord.Embed(title=f"{emojis.get(protection_key, '🛡️')} {names.get(protection_key, protection_key)}", color=C.RED, timestamp=now())
        e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.name}` (ID: {member.id})", inline=True)
        e.add_field(name="📍 Salon", value=f"{message.channel.mention}" if message else "N/A", inline=True)
        e.add_field(name="⚠️ Raison", value=reason, inline=False)
        if message and message.content:
            content = message.content[:500] + "..." if len(message.content) > 500 else message.content
            e.add_field(name="💬 Message", value=f"```{content}```", inline=False)
        if extra_info:
            e.add_field(name="ℹ️ Détails", value=extra_info, inline=False)
        e.set_thumbnail(url=member.display_avatar.url)
        await log_channel.send(embed=e)
    except Exception as e:
        print(f"[LOG ERROR] {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_text(text):
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    result = []
    for char in text:
        for letter, variants in LEET_MAP.items():
            if char in variants:
                result.append(letter)
                break
        else:
            result.append(char)
    cleaned = []
    prev = ''
    for c in result:
        if c != prev or not c.isalpha():
            cleaned.append(c)
        prev = c
    return ''.join(cleaned)

def check_badwords(content, badwords):
    if not badwords:
        return False, None
    normalized = normalize_text(content)
    no_spaces = re.sub(r'[^a-z]', '', normalized)
    for word in badwords:
        word_norm = normalize_text(word.strip())
        if not word_norm:
            continue
        if word_norm in normalized or word_norm in no_spaces:
            return True, word
    return False, None

def check_link(content, whitelist):
    urls = re.findall(r'https?://([^\s<>"]+)', content.lower())
    if not urls:
        return False, None
    for url in urls:
        domain = url.split('/')[0]
        is_allowed = False
        for allowed in whitelist:
            allowed = allowed.lower().strip()
            if '/' in allowed:
                if url.startswith(allowed.replace('https://', '').replace('http://', '')):
                    is_allowed = True
                    break
            else:
                if allowed in domain:
                    is_allowed = True
                    break
        if not is_allowed:
            return True, url
    return False, None

def check_invite(content):
    patterns = [r'discord\.gg/[a-zA-Z0-9]+', r'discord\.com/invite/[a-zA-Z0-9]+', r'discordapp\.com/invite/[a-zA-Z0-9]+']
    for p in patterns:
        match = re.search(p, content, re.I)
        if match:
            return True, match.group()
    return False, None

def check_phishing(content):
    content_lower = content.lower()
    for domain in PHISHING_DOMAINS:
        if domain in content_lower:
            return True, domain
    return False, None

def check_scam(content):
    for pattern in SCAM_PATTERNS:
        if re.search(pattern, content, re.I):
            return True, pattern
    return False, None

def check_caps(content, percent, min_len):
    if len(content) < min_len:
        return False
    letters = [c for c in content if c.isalpha()]
    if len(letters) < min_len:
        return False
    ratio = sum(1 for c in letters if c.isupper()) / len(letters) * 100
    return ratio >= percent

def is_tenor_gif(message):
    """Vérifie si le message contient un GIF Tenor (via plusieurs méthodes)"""
    content = message.content.lower()
    
    # 1. Lien direct tenor.com
    if 'tenor.com' in content:
        return True
    
    # 2. Proxy Discord pour Tenor (images-ext-X.discordapp.net avec tenor dans l'URL)
    if 'discordapp.net' in content and 'tenor' in content:
        return True
    
    # 3. Vérifier les embeds
    for embed in message.embeds:
        if embed.url and 'tenor' in embed.url.lower():
            return True
        if embed.video and embed.video.url and 'tenor' in embed.video.url.lower():
            return True
        if embed.thumbnail and embed.thumbnail.url and 'tenor' in embed.thumbnail.url.lower():
            return True
        # Type gifv souvent utilisé pour Tenor
        if embed.type == 'gifv':
            if embed.provider and embed.provider.name and 'tenor' in embed.provider.name.lower():
                return True
    
    # 4. Vérifier les stickers (pas vraiment Tenor mais bon)
    
    return False

def is_giphy_gif(message):
    """Vérifie si le message contient un GIF Giphy"""
    content = message.content.lower()
    if 'giphy.com' in content or 'giphy' in content:
        return True
    for embed in message.embeds:
        if embed.url and 'giphy' in embed.url.lower():
            return True
    return False

def check_image(message, allowed_formats):
    """
    Vérifie les images/GIFs dans un message.
    allowed_formats peut contenir: png, jpg, jpeg, gif, webp, bmp, tenor, giphy
    """
    blocked_items = []
    allowed_lower = [f.lower().replace('.', '').strip() for f in allowed_formats]
    
    # 1. Vérifier les attachments (fichiers uploadés)
    for att in message.attachments:
        ext = att.filename.lower().split('.')[-1]
        image_exts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff']
        if ext in image_exts:
            if not allowed_formats:  # Liste vide = tout bloqué
                blocked_items.append(f"attachment:{ext}")
            elif ext not in allowed_lower:
                blocked_items.append(f"attachment:{ext}")
    
    # 2. Vérifier Tenor
    if is_tenor_gif(message):
        if 'tenor' not in allowed_lower:
            blocked_items.append("tenor")
    
    # 3. Vérifier Giphy
    if is_giphy_gif(message):
        if 'giphy' not in allowed_lower:
            blocked_items.append("giphy")
    
    # 4. Vérifier les embeds d'images (liens directs vers images)
    for embed in message.embeds:
        if embed.type == 'image' and embed.url:
            # Extraire l'extension de l'URL
            url_lower = embed.url.lower()
            for ext in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']:
                if f'.{ext}' in url_lower:
                    if not allowed_formats:
                        blocked_items.append(f"embed:{ext}")
                    elif ext not in allowed_lower:
                        blocked_items.append(f"embed:{ext}")
                    break
    
    return blocked_items

async def check_spam(msg, max_msg, interval):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker:
        spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n - t).total_seconds() < interval]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > max_msg

async def check_mentions(msg, protected_roles, protected_users, max_count):
    if not protected_roles and not protected_users:
        return False, 0
    count = sum(1 for r in msg.role_mentions if r.id in protected_roles)
    count += sum(1 for u in msg.mentions if u.id in protected_users)
    if count == 0:
        return False, 0
    key = (msg.guild.id, msg.author.id)
    if key not in mention_tracker:
        mention_tracker[key] = {'count': 0, 'time': now()}
    if (now() - mention_tracker[key]['time']).total_seconds() > 3600:
        mention_tracker[key] = {'count': 0, 'time': now()}
    mention_tracker[key]['count'] += count
    return mention_tracker[key]['count'] >= max_count, mention_tracker[key]['count']

def check_new_account(member, min_days):
    age = (now() - member.created_at.replace(tzinfo=timezone.utc)).days
    return age < min_days, age

def check_channel_config(message, channel_config):
    if not channel_config:
        return False, None
    content = message.content.strip()
    
    if not channel_config.get('messages', True):
        has_text = bool(re.sub(r'<a?:\w+:\d+>|https?://\S+', '', content).strip())
        has_no_media = not message.attachments and not message.embeds
        if has_text and has_no_media:
            return True, "messages"
    
    if not channel_config.get('images', True):
        image_exts = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff']
        for att in message.attachments:
            ext = att.filename.lower().split('.')[-1]
            if ext in image_exts:
                return True, "images"
    
    if not channel_config.get('gifs', True):
        for att in message.attachments:
            if att.filename.lower().endswith('.gif'):
                return True, "gifs"
        if is_tenor_gif(message) or is_giphy_gif(message):
            return True, "gifs"
    
    if not channel_config.get('emojis', True):
        if re.search(r'<a?:\w+:\d+>', content):
            return True, "emojis"
    
    if not channel_config.get('links', True):
        if re.search(r'https?://', content):
            return True, "links"
    
    if not channel_config.get('commands', True):
        if content.startswith('/') or content.startswith('!'):
            return True, "commands"
    
    return False, None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 PANELS
# ═══════════════════════════════════════════════════════════════════════════════

PROTECTIONS = [
    {"key": "anti_link", "emoji": "🔗", "name": "Anti-Liens"},
    {"key": "anti_invite", "emoji": "🎟️", "name": "Anti-Invite"},
    {"key": "anti_image", "emoji": "🖼️", "name": "Anti-Images"},
    {"key": "anti_phishing", "emoji": "🎣", "name": "Anti-Phishing"},
    {"key": "anti_scam", "emoji": "🚨", "name": "Anti-Scam"},
    {"key": "anti_spam", "emoji": "📨", "name": "Anti-Spam"},
    {"key": "anti_mention", "emoji": "📢", "name": "Anti-Ping"},
    {"key": "anti_caps", "emoji": "🔠", "name": "Anti-Caps"},
    {"key": "anti_badwords", "emoji": "🤬", "name": "Anti-Insultes"},
    {"key": "anti_newaccount", "emoji": "👶", "name": "Anti-NewAccount"},
]

class MainPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"Serveur: **{self.guild.name}**\nMembres: **{self.guild.member_count}**"
        if self.guild.icon:
            e.set_thumbnail(url=self.guild.icon.url)
        return e

    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot(self, i, b):
        v = ProtPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def logs(self, i, b):
        v = LogsPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=0)
    async def immune(self, i, b):
        v = ImmunePanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Config Salon", emoji="📺", style=discord.ButtonStyle.primary, row=1)
    async def chan_cfg(self, i, b):
        v = ChannelConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.success, row=1)
    async def tickets(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.secondary, row=1)
    async def welc(self, i, b):
        v = WelcomePanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        c = await cfg(self.guild.id)
        lines = []
        for p in PROTECTIONS:
            st = "✅" if c.get(p["key"]) else "❌"
            extra = ""
            if p["key"] == "anti_link":
                ch = len(c.get('link_allowed_channels', []))
                extra = f" ({len(c.get('link_whitelist', []))}D/{ch}S)"
            elif p["key"] == "anti_image":
                ch = len(c.get('image_allowed_channels', []))
                extra = f" ({len(c.get('image_allowed', []))}F/{ch}S)"
            elif p["key"] == "anti_badwords":
                extra = f" ({len(c.get('badwords_list', []))} mots)"
            lines.append(f"{p['emoji']} {p['name']}: {st}{extra}")
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = "```\n" + "\n".join(lines) + "\n```"
        return e

    @discord.ui.select(placeholder="🛡️ Sélectionner...", options=[discord.SelectOption(label=p["name"], value=p["key"], emoji=p["emoji"]) for p in PROTECTIONS], row=0)
    async def select(self, i, s):
        prot = next(p for p in PROTECTIONS if p["key"] == s.values[0])
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class ProtDetail(View):
    def __init__(self, user, guild, prot):
        super().__init__(timeout=900)
        self.user, self.guild, self.prot = user, guild, prot
        self.key = prot["key"]

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        c = await cfg(self.guild.id)
        on = bool(c.get(self.key))
        e = discord.Embed(title=f"{self.prot['emoji']} {self.prot['name']}", color=C.GREEN if on else C.RED)
        e.add_field(name="État", value="✅ ACTIVÉ" if on else "❌ DÉSACTIVÉ", inline=False)
        log_ch = self.guild.get_channel(c.get(f'log_{self.key}', 0))
        e.add_field(name="📜 Log", value=log_ch.mention if log_ch else "❌", inline=False)
        
        if self.key == "anti_link":
            items = c.get('link_whitelist', [])
            channels = c.get('link_allowed_channels', [])
            e.add_field(name=f"✅ Domaines ({len(items)})", value=", ".join([f"`{d}`" for d in items[:10]]) or "*Aucun*", inline=False)
            e.add_field(name=f"📍 Salons ({len(channels)})", value=", ".join([f"<#{ch}>" for ch in channels[:5]]) or "*Interdit partout*", inline=False)
        elif self.key == "anti_image":
            items = c.get('image_allowed', [])
            channels = c.get('image_allowed_channels', [])
            all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tenor', 'giphy']
            allowed = " ".join([f"✅`{f}`" for f in items]) if items else "*Aucun*"
            blocked = " ".join([f"❌`{f}`" for f in all_fmt if f not in items])
            e.add_field(name="Formats", value=f"{allowed}\n{blocked}", inline=False)
            e.add_field(name=f"📍 Salons ({len(channels)})", value=", ".join([f"<#{ch}>" for ch in channels[:5]]) or "*Interdit partout*", inline=False)
        elif self.key == "anti_badwords":
            items = c.get('badwords_list', [])
            e.add_field(name=f"🚫 Mots ({len(items)})", value=", ".join([f"`{w}`" for w in items[:15]]) or "*Aucun*", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('badwords_action', 'delete')}`", inline=False)
        elif self.key == "anti_mention":
            roles = c.get('mention_protected_roles', [])
            users = c.get('mention_protected_users', [])
            e.add_field(name=f"🛡️ Rôles ({len(roles)})", value=", ".join([f"<@&{r}>" for r in roles[:5]]) or "*Aucun*", inline=False)
            e.add_field(name=f"🛡️ Membres ({len(users)})", value=", ".join([f"<@{u}>" for u in users[:5]]) or "*Aucun*", inline=False)
            e.add_field(name="⚡", value=f"**{c.get('mention_max_count', 3)}** pings → `{c.get('mention_action', 'warn')}`", inline=False)
        elif self.key == "anti_spam":
            e.add_field(name="📝", value=f"**{c.get('spam_max_msg', 5)}** msg / **{c.get('spam_interval', 5)}**s → `{c.get('spam_action', 'mute')}`", inline=False)
        elif self.key == "anti_caps":
            e.add_field(name="📝", value=f"Max **{c.get('caps_percent', 70)}%** → `{c.get('caps_action', 'delete')}`", inline=False)
        elif self.key == "anti_newaccount":
            e.add_field(name="📝", value=f"< **{c.get('newaccount_value', 7)} {c.get('newaccount_unit', 'jours')}** → kick", inline=False)
        elif self.key in ["anti_phishing", "anti_scam"]:
            action_key = 'phishing_action' if self.key == 'anti_phishing' else 'scam_action'
            e.add_field(name="⚡ Sanction", value=f"`{c.get(action_key, 'ban')}`", inline=False)
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        c = await cfg(self.guild.id)
        await db_set(self.guild.id, self.key, 0 if c.get(self.key) else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        if self.key == "anti_link":
            v = LinkConfig(self.user, self.guild)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_image":
            v = ImageConfig(self.user, self.guild)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_badwords":
            v = BadwordsConfig(self.user, self.guild)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_mention":
            v = MentionConfig(self.user, self.guild)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_phishing":
            await i.response.send_modal(ActionModal(self.guild, 'phishing_action', "🎣"))
        elif self.key == "anti_scam":
            await i.response.send_modal(ActionModal(self.guild, 'scam_action', "🚨"))
        elif self.key == "anti_spam":
            await i.response.send_modal(SpamModal(self.guild))
        elif self.key == "anti_caps":
            await i.response.send_modal(CapsModal(self.guild))
        elif self.key == "anti_newaccount":
            await i.response.send_modal(NewAccModal(self.guild))
        else:
            await i.response.send_message("❌", ephemeral=True)

    @discord.ui.button(label="📜 Log", style=discord.ButtonStyle.success, row=0)
    async def set_log(self, i, b):
        v = SetLogChannelView(self.user, self.guild, self.key)
        await i.response.edit_message(embed=discord.Embed(title=f"📜 Log {self.prot['name']}", color=C.PURPLE), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ProtPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SetLogChannelView(View):
    def __init__(self, user, guild, prot_key):
        super().__init__(timeout=300)
        self.user, self.guild, self.prot_key = user, guild, prot_key
        chs = [c for c in guild.text_channels][:25]
        options = [discord.SelectOption(label="❌ Désactiver", value="0")]
        options += [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        select = Select(placeholder="Salon...", options=options[:25])
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        await db_set(self.guild.id, f'log_{self.prot_key}', int(i.data['values'][0]))
        prot = next(p for p in PROTECTIONS if p["key"] == self.prot_key)
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == self.prot_key)
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔗 LINK / 🖼️ IMAGE / 🤬 BADWORDS / 📢 MENTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        c = await cfg(self.guild.id)
        items = c.get('link_whitelist', [])
        channels = c.get('link_allowed_channels', [])
        e = discord.Embed(title="🔗 Anti-Liens", color=C.BLUE)
        e.add_field(name=f"✅ Domaines ({len(items)})", value="\n".join([f"• `{d}`" for d in items[:10]]) or "*Aucun*", inline=False)
        e.add_field(name=f"📍 Salons ({len(channels)})", value="\n".join([f"• <#{ch}>" for ch in channels[:10]]) or "*Interdit partout*", inline=False)
        return e

    @discord.ui.button(label="➕ Domaine", style=discord.ButtonStyle.success, row=0)
    async def add_d(self, i, b):
        await i.response.send_modal(AddListModal(self.guild, 'link_whitelist', "domaine(s)"))

    @discord.ui.button(label="➖ Domaine", style=discord.ButtonStyle.danger, row=0)
    async def rem_d(self, i, b):
        c = await cfg(self.guild.id)
        items = c.get('link_whitelist', [])
        if not items:
            return await i.response.send_message("❌ Vide", ephemeral=True)
        v = RemoveListView(self.user, self.guild, items, 'link_whitelist', 'anti_link')
        await i.response.edit_message(embed=discord.Embed(title="➖", color=C.RED), view=v)

    @discord.ui.button(label="➕ Salon", emoji="📍", style=discord.ButtonStyle.success, row=1)
    async def add_c(self, i, b):
        v = AddChannelView(self.user, self.guild, 'link_allowed_channels', 'anti_link')
        await i.response.edit_message(embed=discord.Embed(title="➕ Salon", color=C.GREEN), view=v)

    @discord.ui.button(label="➖ Salon", style=discord.ButtonStyle.danger, row=1)
    async def rem_c(self, i, b):
        c = await cfg(self.guild.id)
        channels = c.get('link_allowed_channels', [])
        if not channels:
            return await i.response.send_message("❌ Vide", ephemeral=True)
        v = RemoveChannelView(self.user, self.guild, channels, 'link_allowed_channels', 'anti_link')
        await i.response.edit_message(embed=discord.Embed(title="➖ Salon", color=C.RED), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_link")
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImageConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        c = await cfg(self.guild.id)
        items = c.get('image_allowed', [])
        channels = c.get('image_allowed_channels', [])
        all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tenor', 'giphy']
        e = discord.Embed(title="🖼️ Anti-Images", color=C.BLUE)
        allowed = " ".join([f"✅`{f}`" for f in items]) if items else "*Aucun*"
        blocked = " ".join([f"❌`{f}`" for f in all_fmt if f not in items])
        e.add_field(name="Formats", value=f"{allowed}\n{blocked}", inline=False)
        e.add_field(name=f"📍 Salons ({len(channels)})", value=", ".join([f"<#{ch}>" for ch in channels[:10]]) or "*Interdit partout*", inline=False)
        e.add_field(name="💡", value="`tenor` = GIFs Tenor\n`giphy` = GIFs Giphy", inline=False)
        return e

    @discord.ui.button(label="➕ Format", style=discord.ButtonStyle.success, row=0)
    async def add_f(self, i, b):
        c = await cfg(self.guild.id)
        items = c.get('image_allowed', [])
        all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tenor', 'giphy']
        available = [f for f in all_fmt if f not in items]
        if not available:
            return await i.response.send_message("✅ Tous autorisés", ephemeral=True)
        v = FormatSelectView(self.user, self.guild, available, 'add')
        await i.response.edit_message(embed=discord.Embed(title="➕ Format", color=C.GREEN), view=v)

    @discord.ui.button(label="➖ Format", style=discord.ButtonStyle.danger, row=0)
    async def rem_f(self, i, b):
        c = await cfg(self.guild.id)
        items = c.get('image_allowed', [])
        if not items:
            return await i.response.send_message("❌ Vide", ephemeral=True)
        v = FormatSelectView(self.user, self.guild, items, 'remove')
        await i.response.edit_message(embed=discord.Embed(title="➖ Format", color=C.RED), view=v)

    @discord.ui.button(label="➕ Salon", emoji="📍", style=discord.ButtonStyle.success, row=1)
    async def add_c(self, i, b):
        v = AddChannelView(self.user, self.guild, 'image_allowed_channels', 'anti_image')
        await i.response.edit_message(embed=discord.Embed(title="➕ Salon", color=C.GREEN), view=v)

    @discord.ui.button(label="➖ Salon", style=discord.ButtonStyle.danger, row=1)
    async def rem_c(self, i, b):
        c = await cfg(self.guild.id)
        channels = c.get('image_allowed_channels', [])
        if not channels:
            return await i.response.send_message("❌ Vide", ephemeral=True)
        v = RemoveChannelView(self.user, self.guild, channels, 'image_allowed_channels', 'anti_image')
        await i.response.edit_message(embed=discord.Embed(title="➖ Salon", color=C.RED), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_image")
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class FormatSelectView(View):
    def __init__(self, user, guild, formats, action):
        super().__init__(timeout=300)
        self.user, self.guild, self.action = user, guild, action
        labels = {'tenor': 'TENOR (GIFs)', 'giphy': 'GIPHY (GIFs)'}
        options = [discord.SelectOption(label=labels.get(f, f.upper()), value=f) for f in formats]
        select = Select(placeholder="Format...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        fmt = i.data['values'][0]
        c = await cfg(self.guild.id)
        items = c.get('image_allowed', [])
        if self.action == 'add' and fmt not in items:
            items.append(fmt)
        elif self.action == 'remove' and fmt in items:
            items.remove(fmt)
        await db_set(self.guild.id, 'image_allowed', items)
        v = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddChannelView(View):
    def __init__(self, user, guild, key, prot_key):
        super().__init__(timeout=300)
        self.user, self.guild, self.key, self.prot_key = user, guild, key, prot_key
        chs = [c for c in guild.text_channels][:25]
        options = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        select = Select(placeholder="Salon...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        ch_id = int(i.data['values'][0])
        c = await cfg(self.guild.id)
        items = c.get(self.key, [])
        if ch_id not in items:
            items.append(ch_id)
            await db_set(self.guild.id, self.key, items)
        if self.prot_key == 'anti_link':
            v = LinkConfig(self.user, self.guild)
        else:
            v = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        if self.prot_key == 'anti_link':
            v = LinkConfig(self.user, self.guild)
        else:
            v = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RemoveChannelView(View):
    def __init__(self, user, guild, channels, key, prot_key):
        super().__init__(timeout=300)
        self.user, self.guild, self.key, self.prot_key = user, guild, key, prot_key
        options = [discord.SelectOption(label=f"#{guild.get_channel(ch).name if guild.get_channel(ch) else ch}"[:25], value=str(ch)) for ch in channels[:25]]
        select = Select(placeholder="Salon...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        ch_id = int(i.data['values'][0])
        c = await cfg(self.guild.id)
        items = c.get(self.key, [])
        if ch_id in items:
            items.remove(ch_id)
            await db_set(self.guild.id, self.key, items)
        if self.prot_key == 'anti_link':
            v = LinkConfig(self.user, self.guild)
        else:
            v = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        if self.prot_key == 'anti_link':
            v = LinkConfig(self.user, self.guild)
        else:
            v = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class BadwordsConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        c = await cfg(self.guild.id)
        items = c.get('badwords_list', [])
        e = discord.Embed(title="🤬 Anti-Insultes", color=C.BLUE)
        e.add_field(name="⚡ Sanction", value=f"`{c.get('badwords_action', 'delete')}`", inline=False)
        e.add_field(name=f"Mots ({len(items)})", value=", ".join([f"`{w}`" for w in items[:25]]) or "*Aucun*", inline=False)
        return e

    @discord.ui.button(label="➕ Mot(s)", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddListModal(self.guild, 'badwords_list', "mot(s)"))

    @discord.ui.button(label="➖ Mot", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        c = await cfg(self.guild.id)
        items = c.get('badwords_list', [])
        if not items:
            return await i.response.send_message("❌ Vide", ephemeral=True)
        v = RemoveListView(self.user, self.guild, items, 'badwords_list', 'anti_badwords')
        await i.response.edit_message(embed=discord.Embed(title="➖", color=C.RED), view=v)

    @discord.ui.button(label="⚙️ Sanction", style=discord.ButtonStyle.secondary, row=0)
    async def action(self, i, b):
        await i.response.send_modal(BadwordActionModal(self.guild))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_badwords")
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class MentionConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        c = await cfg(self.guild.id)
        roles = c.get('mention_protected_roles', [])
        users = c.get('mention_protected_users', [])
        e = discord.Embed(title="📢 Anti-Ping", color=C.BLUE)
        e.add_field(name=f"🛡️ Rôles ({len(roles)})", value=", ".join([f"<@&{r}>" for r in roles[:8]]) or "*Aucun*", inline=False)
        e.add_field(name=f"🛡️ Membres ({len(users)})", value=", ".join([f"<@{u}>" for u in users[:8]]) or "*Aucun*", inline=False)
        e.add_field(name="⚡", value=f"**{c.get('mention_max_count', 3)}** pings → `{c.get('mention_action', 'warn')}`", inline=False)
        return e

    @discord.ui.button(label="➕ Rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        roles = [r for r in self.guild.roles[1:] if not r.is_bot_managed()][:25]
        if not roles:
            return await i.response.send_message("❌", ephemeral=True)
        v = RoleSelectView(self.user, self.guild, roles, 'mention_protected_roles')
        await i.response.edit_message(embed=discord.Embed(title="➕ Rôle", color=C.GREEN), view=v)

    @discord.ui.button(label="➕ Membre", style=discord.ButtonStyle.success, row=0)
    async def add_user(self, i, b):
        await i.response.send_modal(AddUserModal(self.guild, 'mention_protected_users'))

    @discord.ui.button(label="⚙️ Config", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        await i.response.send_modal(MentionModal(self.guild))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_mention")
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RoleSelectView(View):
    def __init__(self, user, guild, roles, key):
        super().__init__(timeout=300)
        self.user, self.guild, self.key = user, guild, key
        options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        select = Select(placeholder="Rôle...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        rid = int(i.data['values'][0])
        c = await cfg(self.guild.id)
        items = c.get(self.key, [])
        if rid not in items:
            items.append(rid)
            await db_set(self.guild.id, self.key, items)
        v = MentionConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MentionConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

async def get_ticket_config(guild_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT panel_channel_id, category_id, staff_role_id, panel_message_id FROM ticket_config WHERE guild_id = ?', (guild_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return {'panel_channel_id': row[0], 'category_id': row[1], 'staff_role_id': row[2], 'panel_message_id': row[3]}
    return {'panel_channel_id': 0, 'category_id': 0, 'staff_role_id': 0, 'panel_message_id': 0}

async def set_ticket_config(guild_id, **kwargs):
    current = await get_ticket_config(guild_id)
    current.update(kwargs)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''INSERT INTO ticket_config (guild_id, panel_channel_id, category_id, staff_role_id, panel_message_id) 
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET 
            panel_channel_id = ?, category_id = ?, staff_role_id = ?, panel_message_id = ?''',
            (guild_id, current['panel_channel_id'], current['category_id'], current['staff_role_id'], current['panel_message_id'],
             current['panel_channel_id'], current['category_id'], current['staff_role_id'], current['panel_message_id']))
        await db.commit()

class TicketConfigPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        tc = await get_ticket_config(self.guild.id)
        panel_ch = self.guild.get_channel(tc['panel_channel_id'])
        category = self.guild.get_channel(tc['category_id'])
        staff_role = self.guild.get_role(tc['staff_role_id'])
        
        e = discord.Embed(title="🎫 Configuration Tickets", color=C.PURPLE)
        e.add_field(name="📍 Salon du panel", value=panel_ch.mention if panel_ch else "❌ Non configuré", inline=False)
        e.add_field(name="📁 Catégorie tickets", value=category.name if category else "❌ Non configurée", inline=False)
        e.add_field(name="👮 Rôle Staff", value=staff_role.mention if staff_role else "❌ Non configuré", inline=False)
        e.add_field(name="📝 Panel", value="✅ Envoyé" if tc['panel_message_id'] else "❌ Non envoyé", inline=False)
        return e

    @discord.ui.button(label="📍 Salon Panel", style=discord.ButtonStyle.primary, row=0)
    async def set_panel_channel(self, i, b):
        v = SelectChannelForTicket(self.user, self.guild, 'panel')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon du panel", color=C.GREEN), view=v)

    @discord.ui.button(label="📁 Catégorie", style=discord.ButtonStyle.primary, row=0)
    async def set_category(self, i, b):
        v = SelectCategoryForTicket(self.user, self.guild)
        await i.response.edit_message(embed=discord.Embed(title="📁 Catégorie", color=C.GREEN), view=v)

    @discord.ui.button(label="👮 Staff", style=discord.ButtonStyle.primary, row=0)
    async def set_staff(self, i, b):
        v = SelectStaffRole(self.user, self.guild)
        await i.response.edit_message(embed=discord.Embed(title="👮 Rôle Staff", color=C.GREEN), view=v)

    @discord.ui.button(label="📤 Envoyer Panel", style=discord.ButtonStyle.success, row=1)
    async def send_panel(self, i, b):
        tc = await get_ticket_config(self.guild.id)
        if not tc['panel_channel_id'] or not tc['category_id'] or not tc['staff_role_id']:
            return await i.response.send_message("❌ Configurez d'abord: salon, catégorie et staff", ephemeral=True)
        
        channel = self.guild.get_channel(tc['panel_channel_id'])
        if not channel:
            return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        e = discord.Embed(title="🎫 Support Tickets", color=C.BLURPLE)
        e.description = "Besoin d'aide ? Cliquez sur le bouton ci-dessous pour créer un ticket.\n\nUn membre du staff vous répondra dès que possible."
        e.set_footer(text="Veuillez décrire votre problème en détail")
        
        view = CreateTicketButton()
        msg = await channel.send(embed=e, view=view)
        await set_ticket_config(self.guild.id, panel_message_id=msg.id)
        await i.response.send_message(f"✅ Panel envoyé dans {channel.mention}", ephemeral=True)

    @discord.ui.button(label="🔧 Créer salon/catégorie", style=discord.ButtonStyle.secondary, row=1)
    async def create_auto(self, i, b):
        await i.response.send_modal(CreateTicketChannelsModal(self.guild))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class SelectChannelForTicket(View):
    def __init__(self, user, guild, type):
        super().__init__(timeout=300)
        self.user, self.guild, self.type = user, guild, type
        chs = [c for c in guild.text_channels][:25]
        options = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        select = Select(placeholder="Salon...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        await set_ticket_config(self.guild.id, panel_channel_id=int(i.data['values'][0]))
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SelectCategoryForTicket(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        cats = [c for c in guild.categories][:25]
        options = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in cats]
        if options:
            select = Select(placeholder="Catégorie...", options=options)
            select.callback = self.on_select
            self.add_item(select)

    async def on_select(self, i):
        await set_ticket_config(self.guild.id, category_id=int(i.data['values'][0]))
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SelectStaffRole(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        roles = [r for r in guild.roles[1:] if not r.is_bot_managed()][:25]
        options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        select = Select(placeholder="Rôle Staff...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        await set_ticket_config(self.guild.id, staff_role_id=int(i.data['values'][0]))
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class CreateTicketChannelsModal(Modal, title="🔧 Créer salon/catégorie"):
    cat_name = TextInput(label="Nom de la catégorie", placeholder="🎫 Tickets", default="🎫 Tickets", max_length=50)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        try:
            # Créer catégorie
            category = await self.guild.create_category(self.cat_name.value)
            
            # Créer salon panel
            panel_channel = await self.guild.create_text_channel("📩-créer-ticket", category=category)
            
            await set_ticket_config(self.guild.id, panel_channel_id=panel_channel.id, category_id=category.id)
            await i.response.send_message(f"✅ Créé:\n📁 Catégorie: `{category.name}`\n📍 Salon: {panel_channel.mention}", ephemeral=True)
        except Exception as e:
            await i.response.send_message(f"❌ Erreur: {e}", ephemeral=True)

class CreateTicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Créer un ticket", style=discord.ButtonStyle.success, custom_id="create_ticket_btn")
    async def create_ticket(self, i, b):
        await i.response.send_modal(TicketDescriptionModal(i.guild))

class TicketDescriptionModal(Modal, title="📩 Nouveau Ticket"):
    description = TextInput(label="Décrivez votre problème", placeholder="Expliquez en détail votre demande...", style=discord.TextStyle.paragraph, max_length=1000)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        try:
            tc = await get_ticket_config(self.guild.id)
            category = self.guild.get_channel(tc['category_id'])
            staff_role = self.guild.get_role(tc['staff_role_id'])
            
            if not category:
                return await i.response.send_message("❌ Catégorie non configurée", ephemeral=True)
            
            # Vérifier si l'user a déjà un ticket ouvert
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT id FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'", (self.guild.id, i.user.id)) as cur:
                    existing = await cur.fetchone()
            
            if existing:
                return await i.response.send_message("❌ Vous avez déjà un ticket ouvert", ephemeral=True)
            
            # Créer le salon
            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                self.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
            }
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            
            channel = await self.guild.create_text_channel(
                f"ticket-{i.user.name}"[:50],
                category=category,
                overwrites=overwrites
            )
            
            # Sauvegarder le ticket
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT INTO tickets (guild_id, channel_id, user_id, description) VALUES (?, ?, ?, ?)',
                    (self.guild.id, channel.id, i.user.id, self.description.value))
                await db.commit()
            
            # Envoyer le message dans le ticket
            e = discord.Embed(title="🎫 Nouveau Ticket", color=C.BLURPLE)
            e.add_field(name="👤 Créé par", value=i.user.mention, inline=True)
            e.add_field(name="📅 Date", value=f"<t:{int(now().timestamp())}:F>", inline=True)
            e.add_field(name="📝 Description", value=self.description.value, inline=False)
            e.set_footer(text="Un membre du staff va prendre en charge votre ticket")
            
            view = TicketControlView()
            await channel.send(content=f"{i.user.mention} {staff_role.mention if staff_role else ''}", embed=e, view=view)
            
            await i.response.send_message(f"✅ Ticket créé: {channel.mention}", ephemeral=True)
            
        except Exception as e:
            print(f"[TICKET ERROR] {e}\n{traceback.format_exc()}")
            await i.response.send_message(f"❌ Erreur: {e}", ephemeral=True)

class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🙋 Prendre en charge", style=discord.ButtonStyle.success, custom_id="ticket_claim")
    async def claim(self, i, b):
        tc = await get_ticket_config(i.guild.id)
        staff_role = i.guild.get_role(tc['staff_role_id'])
        
        if staff_role and staff_role not in i.user.roles and not i.user.guild_permissions.administrator:
            return await i.response.send_message("❌ Réservé au staff", ephemeral=True)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE tickets SET claimed_by = ? WHERE channel_id = ?', (i.user.id, i.channel.id))
            await db.commit()
        
        e = discord.Embed(title="✅ Ticket pris en charge", description=f"**{i.user.mention}** s'occupe de ce ticket", color=C.GREEN)
        await i.response.send_message(embed=e)
        
        # Désactiver le bouton claim
        b.disabled = True
        b.label = f"Pris par {i.user.name}"
        await i.message.edit(view=self)

    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close(self, i, b):
        e = discord.Embed(title="🔒 Fermer le ticket?", description="Cette action est irréversible", color=C.RED)
        v = ConfirmCloseTicket()
        await i.response.send_message(embed=e, view=v, ephemeral=True)

class ConfirmCloseTicket(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE tickets SET status = 'closed' WHERE channel_id = ?", (i.channel.id,))
            await db.commit()
        
        await i.response.send_message("🔒 Fermeture dans 5 secondes...")
        await asyncio.sleep(5)
        await i.channel.delete()

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.edit_message(content="Annulé", embed=None, view=None)

# ═══════════════════════════════════════════════════════════════════════════════
#                           OTHER PANELS (Logs, Immune, ChannelConfig, Welcome)
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def embed(self):
        c = await cfg(self.guild.id)
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        lines = []
        for p in PROTECTIONS:
            ch_id = c.get(f'log_{p["key"]}', 0)
            ch = self.guild.get_channel(ch_id) if ch_id else None
            lines.append(f"{p['emoji']} {p['name']}: {ch.mention if ch else '❌'}")
        e.description = "\n".join(lines)
        return e

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class ImmunePanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (self.guild.id,)) as cur:
                role_ids = [r[0] for r in await cur.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id = ?', (self.guild.id,)) as cur:
                user_ids = [r[0] for r in await cur.fetchall()]
        roles = [self.guild.get_role(rid) for rid in role_ids if self.guild.get_role(rid)]
        users = [self.guild.get_member(uid) for uid in user_ids if self.guild.get_member(uid)]
        e = discord.Embed(title="👑 Immunités", color=C.YELLOW)
        e.add_field(name=f"🎭 Rôles ({len(roles)})", value=", ".join([r.mention for r in roles]) or "*Aucun*", inline=False)
        e.add_field(name=f"👤 Membres ({len(users)})", value=", ".join([u.mention for u in users]) or "*Aucun*", inline=False)
        e.add_field(name="⚠️", value="Immunisés ignorent TOUT **sauf**: Anti-Phishing, Anti-Liens, Anti-Invite", inline=False)
        return e

    @discord.ui.button(label="➕ Rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        roles = [r for r in self.guild.roles[1:] if not r.is_bot_managed()][:25]
        options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = ImmuneRoleSelect(self.user, self.guild, options)
        await i.response.edit_message(embed=discord.Embed(title="➕ Rôle", color=C.GREEN), view=v)

    @discord.ui.button(label="➕ Membre", style=discord.ButtonStyle.success, row=0)
    async def add_user(self, i, b):
        await i.response.send_modal(AddImmuneUserModal(self.guild))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class ImmuneRoleSelect(View):
    def __init__(self, user, guild, options):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        select = Select(placeholder="Rôle...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        rid = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES (?, ?)', (self.guild.id, rid))
            await db.commit()
        v = ImmunePanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ImmunePanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddImmuneUserModal(Modal, title="➕ Membre immunisé"):
    user_id = TextInput(label="ID du membre", placeholder="123456789", max_length=20)
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    async def on_submit(self, i):
        try:
            uid = int(self.user_id.value)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT OR IGNORE INTO immune_users VALUES (?, ?)', (self.guild.id, uid))
                await db.commit()
            await i.response.send_message("✅", ephemeral=True)
        except:
            await i.response.send_message("❌", ephemeral=True)

class ChannelConfigPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def embed(self):
        c = await cfg(self.guild.id)
        configs = c.get('channel_configs', {})
        e = discord.Embed(title="📺 Config Salon", color=C.ORANGE)
        if configs:
            lines = []
            for ch_id, conf in list(configs.items())[:10]:
                ch = self.guild.get_channel(int(ch_id))
                if ch:
                    allowed = []
                    if conf.get('messages', True): allowed.append("💬")
                    if conf.get('images', True): allowed.append("🖼️")
                    if conf.get('gifs', True): allowed.append("🎞️")
                    if conf.get('emojis', True): allowed.append("😀")
                    if conf.get('links', True): allowed.append("🔗")
                    if conf.get('commands', True): allowed.append("⌨️")
                    lines.append(f"{ch.mention}: {' '.join(allowed) if allowed else '🚫'}")
            e.add_field(name=f"Salons ({len(configs)})", value="\n".join(lines), inline=False)
        else:
            e.add_field(name="Salons", value="*Aucun configuré*", inline=False)
        e.add_field(name="💡", value="💬Msg 🖼️Img 🎞️GIF 😀Emoji 🔗Lien ⌨️Cmd", inline=False)
        return e

    @discord.ui.button(label="➕ Configurer", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        chs = [c for c in self.guild.text_channels][:25]
        options = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        v = SelectChannelToConfig(self.user, self.guild, options)
        await i.response.edit_message(embed=discord.Embed(title="📺 Choisir", color=C.GREEN), view=v)

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        c = await cfg(self.guild.id)
        configs = c.get('channel_configs', {})
        if not configs:
            return await i.response.send_message("❌", ephemeral=True)
        options = [discord.SelectOption(label=f"#{self.guild.get_channel(int(ch_id)).name if self.guild.get_channel(int(ch_id)) else ch_id}"[:25], value=ch_id) for ch_id in list(configs.keys())[:25]]
        v = RemoveChannelConfigView(self.user, self.guild, options)
        await i.response.edit_message(embed=discord.Embed(title="➖ Supprimer", color=C.RED), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class SelectChannelToConfig(View):
    def __init__(self, user, guild, options):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        select = Select(placeholder="Salon...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        v = EditChannelConfig(self.user, self.guild, i.data['values'][0])
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ChannelConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class EditChannelConfig(View):
    def __init__(self, user, guild, channel_id):
        super().__init__(timeout=900)
        self.user, self.guild, self.channel_id = user, guild, channel_id

    async def get_config(self):
        c = await cfg(self.guild.id)
        configs = c.get('channel_configs', {})
        return configs.get(str(self.channel_id), {'messages': True, 'images': True, 'gifs': True, 'emojis': True, 'links': True, 'commands': True})

    async def save_config(self, conf):
        c = await cfg(self.guild.id)
        configs = c.get('channel_configs', {})
        configs[str(self.channel_id)] = conf
        await db_set(self.guild.id, 'channel_configs', configs)

    async def embed(self):
        ch = self.guild.get_channel(int(self.channel_id))
        conf = await self.get_config()
        e = discord.Embed(title=f"📺 #{ch.name if ch else self.channel_id}", color=C.ORANGE)
        status = lambda k: "✅" if conf.get(k, True) else "❌"
        e.description = f"💬 Messages: {status('messages')}\n🖼️ Images: {status('images')}\n🎞️ GIFs: {status('gifs')}\n😀 Emojis: {status('emojis')}\n🔗 Liens: {status('links')}\n⌨️ Commandes: {status('commands')}"
        return e

    @discord.ui.button(label="💬", style=discord.ButtonStyle.primary, row=0)
    async def t1(self, i, b):
        conf = await self.get_config()
        conf['messages'] = not conf.get('messages', True)
        await self.save_config(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="🖼️", style=discord.ButtonStyle.primary, row=0)
    async def t2(self, i, b):
        conf = await self.get_config()
        conf['images'] = not conf.get('images', True)
        await self.save_config(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="🎞️", style=discord.ButtonStyle.primary, row=0)
    async def t3(self, i, b):
        conf = await self.get_config()
        conf['gifs'] = not conf.get('gifs', True)
        await self.save_config(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="😀", style=discord.ButtonStyle.primary, row=1)
    async def t4(self, i, b):
        conf = await self.get_config()
        conf['emojis'] = not conf.get('emojis', True)
        await self.save_config(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="🔗", style=discord.ButtonStyle.primary, row=1)
    async def t5(self, i, b):
        conf = await self.get_config()
        conf['links'] = not conf.get('links', True)
        await self.save_config(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="⌨️", style=discord.ButtonStyle.primary, row=1)
    async def t6(self, i, b):
        conf = await self.get_config()
        conf['commands'] = not conf.get('commands', True)
        await self.save_config(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = ChannelConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RemoveChannelConfigView(View):
    def __init__(self, user, guild, options):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        select = Select(placeholder="Salon...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        c = await cfg(self.guild.id)
        configs = c.get('channel_configs', {})
        ch_id = i.data['values'][0]
        if ch_id in configs:
            del configs[ch_id]
            await db_set(self.guild.id, 'channel_configs', configs)
        v = ChannelConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ChannelConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class WelcomePanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def embed(self):
        c = await cfg(self.guild.id)
        ch = self.guild.get_channel(c.get('welcome_channel', 0))
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"État: {'✅' if c.get('welcome_on') else '❌'}\nSalon: {ch.mention if ch else '❌'}"
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def tog(self, i, b):
        c = await cfg(self.guild.id)
        await db_set(self.guild.id, 'welcome_on', 0 if c.get('welcome_on') else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           MODALS
# ═══════════════════════════════════════════════════════════════════════════════

class AddListModal(Modal):
    def __init__(self, guild, key, item_type):
        super().__init__(title=f"➕ Ajouter {item_type}")
        self.guild, self.key = guild, key
        self.input = TextInput(label=f"{item_type}", placeholder="item1,item2", style=discord.TextStyle.paragraph, max_length=500)
        self.add_item(self.input)

    async def on_submit(self, i):
        c = await cfg(self.guild.id)
        items = c.get(self.key, [])
        new = [x.strip().lower() for x in self.input.value.replace(' ', '').split(',') if x.strip()]
        added = [x for x in new if x not in items]
        items.extend(added)
        await db_set(self.guild.id, self.key, items)
        await i.response.send_message(f"✅ `{', '.join(added)}`" if added else "⚠️ Déjà présent", ephemeral=True)

class RemoveListView(View):
    def __init__(self, user, guild, items, key, prot_key):
        super().__init__(timeout=300)
        self.user, self.guild, self.key, self.prot_key = user, guild, key, prot_key
        options = [discord.SelectOption(label=str(x)[:25], value=str(x)) for x in items[:25]]
        select = Select(placeholder="...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        val = i.data['values'][0]
        c = await cfg(self.guild.id)
        items = c.get(self.key, [])
        try:
            items.remove(int(val))
        except:
            try:
                items.remove(val)
            except:
                pass
        await db_set(self.guild.id, self.key, items)
        await i.response.send_message("✅", ephemeral=True)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        if self.prot_key == 'anti_link':
            v = LinkConfig(self.user, self.guild)
        elif self.prot_key == 'anti_badwords':
            v = BadwordsConfig(self.user, self.guild)
        else:
            v = ProtPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ActionModal(Modal):
    def __init__(self, guild, key, emoji):
        super().__init__(title=f"{emoji} Sanction")
        self.guild, self.key = guild, key
        self.action = TextInput(label="Sanction", placeholder="ban", max_length=10)
        self.add_item(self.action)

    async def on_submit(self, i):
        act = self.action.value.lower().strip()
        if act not in ['delete', 'mute', 'kick', 'ban']:
            act = 'ban'
        await db_set(self.guild.id, self.key, act)
        await i.response.send_message(f"✅ `{act}`", ephemeral=True)

class SpamModal(Modal, title="📨 Anti-Spam"):
    max_msg = TextInput(label="Messages max", placeholder="5", default="5", max_length=3)
    interval = TextInput(label="Intervalle (sec)", placeholder="5", default="5", max_length=3)
    action = TextInput(label="Sanction", placeholder="mute", default="mute", max_length=10)
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    async def on_submit(self, i):
        await db_set(self.guild.id, 'spam_max_msg', int(self.max_msg.value) if self.max_msg.value.isdigit() else 5)
        await db_set(self.guild.id, 'spam_interval', int(self.interval.value) if self.interval.value.isdigit() else 5)
        await db_set(self.guild.id, 'spam_action', self.action.value.lower())
        await i.response.send_message("✅", ephemeral=True)

class CapsModal(Modal, title="🔠 Anti-Caps"):
    percent = TextInput(label="% max", placeholder="70", default="70", max_length=3)
    action = TextInput(label="Sanction", placeholder="delete", default="delete", max_length=10)
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    async def on_submit(self, i):
        await db_set(self.guild.id, 'caps_percent', int(self.percent.value) if self.percent.value.isdigit() else 70)
        await db_set(self.guild.id, 'caps_action', self.action.value.lower())
        await i.response.send_message("✅", ephemeral=True)

class NewAccModal(Modal, title="👶 Anti-NewAccount"):
    value = TextInput(label="Âge min", placeholder="7", default="7", max_length=4)
    unit = TextInput(label="Unité", placeholder="jours", default="jours", max_length=10)
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    async def on_submit(self, i):
        await db_set(self.guild.id, 'newaccount_value', int(self.value.value) if self.value.value.isdigit() else 7)
        await db_set(self.guild.id, 'newaccount_unit', self.unit.value.lower() if self.unit.value.lower() in ['jours','semaines','mois'] else 'jours')
        await i.response.send_message("✅", ephemeral=True)

class BadwordActionModal(Modal, title="⚙️ Sanction"):
    action = TextInput(label="Sanction", placeholder="delete", default="delete", max_length=10)
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    async def on_submit(self, i):
        await db_set(self.guild.id, 'badwords_action', self.action.value.lower() if self.action.value.lower() in ['delete','warn','kick'] else 'delete')
        await i.response.send_message("✅", ephemeral=True)

class AddUserModal(Modal, title="➕ Membre"):
    user_id = TextInput(label="ID", placeholder="123456789", max_length=20)
    def __init__(self, guild, key):
        super().__init__()
        self.guild, self.key = guild, key
    async def on_submit(self, i):
        try:
            uid = int(self.user_id.value)
            c = await cfg(self.guild.id)
            items = c.get(self.key, [])
            if uid not in items:
                items.append(uid)
                await db_set(self.guild.id, self.key, items)
            await i.response.send_message("✅", ephemeral=True)
        except:
            await i.response.send_message("❌", ephemeral=True)

class MentionModal(Modal, title="📢 Config"):
    max_count = TextInput(label="Pings max", placeholder="3", default="3", max_length=3)
    action = TextInput(label="Sanction", placeholder="warn", default="warn", max_length=10)
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    async def on_submit(self, i):
        await db_set(self.guild.id, 'mention_max_count', int(self.max_count.value) if self.max_count.value.isdigit() else 3)
        await db_set(self.guild.id, 'mention_action', self.action.value.lower() if self.action.value.lower() in ['warn','mute','kick','ban'] else 'warn')
        await i.response.send_message("✅", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await db_init()
    # Restaurer les views persistants
    bot.add_view(CreateTicketButton())
    bot.add_view(TicketControlView())
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v10.1 prêt!")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return

    try:
        c = await cfg(msg.guild.id)
        content = msg.content
        channel_id = msg.channel.id

        # 📺 CONFIG SALON
        ch_configs = c.get('channel_configs', {})
        ch_conf = ch_configs.get(str(channel_id))
        if ch_conf:
            violation, vtype = check_channel_config(msg, ch_conf)
            if violation:
                await msg.delete()
                return

        # 🎣 ANTI-PHISHING
        if c.get('anti_phishing'):
            found, domain = check_phishing(content)
            if found:
                await msg.delete()
                await send_protection_log(msg.guild, 'anti_phishing', msg.author, msg, "Phishing", f"Domaine: `{domain}`")
                await apply_sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing", msg.guild)
                return

        # 🚨 ANTI-SCAM
        if c.get('anti_scam') and not await is_immune(msg.author, 'anti_scam'):
            found, pattern = check_scam(content)
            if found:
                await msg.delete()
                await send_protection_log(msg.guild, 'anti_scam', msg.author, msg, "Scam", f"Pattern: `{pattern}`")
                await apply_sanction(msg.author, c.get('scam_action', 'mute'), c.get('scam_duration', 60), "Scam", msg.guild)
                return

        # 🤬 ANTI-BADWORDS
        if c.get('anti_badwords') and not await is_immune(msg.author, 'anti_badwords'):
            found, word = check_badwords(content, c.get('badwords_list', []))
            if found:
                await msg.delete()
                await send_protection_log(msg.guild, 'anti_badwords', msg.author, msg, "Insulte", f"Mot: `{word}`")
                action = c.get('badwords_action', 'delete')
                if action != 'delete':
                    await apply_sanction(msg.author, action, 0, "Insulte", msg.guild)
                return

        # 🎟️ ANTI-INVITE
        if c.get('anti_invite'):
            found, invite = check_invite(content)
            if found:
                await msg.delete()
                await send_protection_log(msg.guild, 'anti_invite', msg.author, msg, "Invitation", f"Lien: `{invite}`")
                return

        # 🔗 ANTI-LIENS
        if c.get('anti_link'):
            allowed_channels = c.get('link_allowed_channels', [])
            if channel_id not in allowed_channels:
                found, url = check_link(content, c.get('link_whitelist', []))
                if found:
                    await msg.delete()
                    await send_protection_log(msg.guild, 'anti_link', msg.author, msg, "Lien interdit", f"URL: `{url}`")
                    return

        # 🖼️ ANTI-IMAGES
        if c.get('anti_image') and not await is_immune(msg.author, 'anti_image'):
            allowed_channels = c.get('image_allowed_channels', [])
            if channel_id not in allowed_channels:
                blocked = check_image(msg, c.get('image_allowed', []))
                if blocked:
                    await msg.delete()
                    await send_protection_log(msg.guild, 'anti_image', msg.author, msg, "Format interdit", f"Bloqué: `{', '.join(blocked)}`")
                    return

        # 📨 ANTI-SPAM
        if c.get('anti_spam') and not await is_immune(msg.author, 'anti_spam'):
            if await check_spam(msg, c.get('spam_max_msg', 5), c.get('spam_interval', 5)):
                await msg.delete()
                await send_protection_log(msg.guild, 'anti_spam', msg.author, msg, "Spam", None)
                await apply_sanction(msg.author, c.get('spam_action', 'mute'), c.get('spam_duration', 10), "Spam", msg.guild)
                return

        # 📢 ANTI-MENTION
        if c.get('anti_mention') and not await is_immune(msg.author, 'anti_mention'):
            triggered, count = await check_mentions(msg, c.get('mention_protected_roles', []), c.get('mention_protected_users', []), c.get('mention_max_count', 3))
            if triggered:
                await msg.delete()
                await send_protection_log(msg.guild, 'anti_mention', msg.author, msg, "Ping abusif", f"Total: {count}")
                await apply_sanction(msg.author, c.get('mention_action', 'warn'), 10, "Ping", msg.guild)
                return

        # 🔠 ANTI-CAPS
        if c.get('anti_caps') and not await is_immune(msg.author, 'anti_caps'):
            if check_caps(content, c.get('caps_percent', 70), c.get('caps_min_len', 10)):
                await msg.delete()
                await send_protection_log(msg.guild, 'anti_caps', msg.author, msg, "Majuscules", None)
                return

    except Exception as e:
        print(f"[MSG ERROR] {e}\n{traceback.format_exc()}")

@bot.event
async def on_member_join(member):
    try:
        c = await cfg(member.guild.id)
        if c.get('anti_newaccount'):
            val = c.get('newaccount_value', 7)
            unit = c.get('newaccount_unit', 'jours')
            days = val * (7 if unit == 'semaines' else 30 if unit == 'mois' else 1)
            is_new, age = check_new_account(member, days)
            if is_new:
                await send_protection_log(member.guild, 'anti_newaccount', member, None, "Compte récent", f"Âge: {age}j")
                await member.kick(reason=f"Compte récent ({age}j)")
                return
        if c.get('welcome_on') and c.get('welcome_channel'):
            ch = member.guild.get_channel(c['welcome_channel'])
            if ch:
                txt = c.get('welcome_msg', 'Bienvenue {member}!').format(member=member.mention, server=member.guild.name, count=member.guild.member_count)
                e = discord.Embed(title="👋 Bienvenue!", description=txt, color=C.GREEN)
                e.set_thumbnail(url=member.display_avatar.url)
                await ch.send(embed=e)
    except Exception as e:
        print(f"[JOIN ERROR] {e}")

@bot.tree.command(name="configure", description="⚙️ Configuration")
async def configure_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin requis", ephemeral=True)
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.embed(), view=v, ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir")
@app_commands.describe(membre="Membre", raison="Raison")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not i.user.guild_permissions.moderate_members:
        return await i.response.send_message("❌", ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions (guild_id, user_id, mod_id, type, reason) VALUES (?, ?, ?, ?, ?)',
            (i.guild.id, membre.id, i.user.id, 'warn', raison))
        await db.commit()
    await i.response.send_message(f"⚠️ {membre.mention} averti: {raison}")

if __name__ == "__main__":
    print(f"🚀 v10.1")
    bot.run(TOKEN)
