# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v9.8 🌟                                 ║
# ║              Système DB Robuste + Debug Complet                               ║
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

# Database path - FIXED
if os.path.exists('/data'):
    DB_PATH = '/data/bot.db'
else:
    DB_PATH = 'bot.db'

print(f"📁 Database path: {DB_PATH}")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}
mention_tracker = {}

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PINK=0xEB459E; PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22

PHISHING_DOMAINS = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com']
SCAM_PATTERNS = [r'free\s*nitro',r'discord\s*nitro\s*free',r'steam\s*gift',r'@everyone.*http']

LEET_MAP = {
    'a': ['a','@','4','à','á','â'], 'b': ['b','8'], 'c': ['c','(','ç'],
    'e': ['e','3','€','è','é','ê'], 'i': ['i','1','!','|'], 'l': ['l','1'],
    'o': ['o','0','ò','ó','ô'], 's': ['s','$','5'], 't': ['t','7','+'],
    'u': ['u','ù','ú','û'], 'z': ['z','2'],
}

def now():
    return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE SIMPLE
# ═══════════════════════════════════════════════════════════════════════════════

async def db_init():
    """Initialise la base de données"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            data TEXT DEFAULT '{}'
        )''')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT)')
        await db.commit()
    print("✅ Database initialisée")

async def db_get(guild_id: int) -> dict:
    """Récupère la config d'un serveur"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT data FROM guild_config WHERE guild_id = ?', (guild_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except:
                    return {}
    return {}

async def db_set(guild_id: int, key: str, value) -> bool:
    """Sauvegarde une valeur"""
    try:
        # Get current data
        data = await db_get(guild_id)
        # Update
        data[key] = value
        json_data = json.dumps(data, ensure_ascii=False)
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Upsert
            await db.execute('''INSERT INTO guild_config (guild_id, data) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET data = ?''', (guild_id, json_data, json_data))
            await db.commit()
        
        # Verify
        verify = await db_get(guild_id)
        saved = verify.get(key)
        print(f"✅ [DB_SET] {guild_id} | {key} = {saved}")
        return True
    except Exception as e:
        print(f"❌ [DB_SET ERROR] {e}")
        traceback.print_exc()
        return False

async def db_get_list(guild_id: int, key: str) -> list:
    """Récupère une liste"""
    data = await db_get(guild_id)
    value = data.get(key, [])
    if isinstance(value, list):
        return value
    return []

async def db_set_list(guild_id: int, key: str, items: list) -> bool:
    """Sauvegarde une liste"""
    return await db_set(guild_id, key, items)

def get_default_config():
    return {
        'anti_link': 0, 'anti_invite': 0, 'anti_image': 0,
        'anti_phishing': 1, 'anti_scam': 1, 'anti_spam': 0,
        'anti_mention': 0, 'anti_caps': 0, 'anti_newaccount': 0,
        'anti_badwords': 0,
        'link_whitelist': [], 'image_allowed': [], 'badwords_list': [],
        'mention_protected_roles': [], 'mention_protected_users': [],
        'phishing_action': 'ban', 'scam_action': 'mute', 'scam_duration': 60,
        'spam_max_msg': 5, 'spam_interval': 5, 'spam_action': 'mute',
        'mention_max_count': 3, 'mention_action': 'warn',
        'caps_percent': 70, 'caps_min_len': 10, 'caps_action': 'delete',
        'newaccount_value': 7, 'newaccount_unit': 'jours',
        'badwords_action': 'delete',
        'welcome_on': 0, 'welcome_channel': 0, 'welcome_msg': 'Bienvenue {member}!'
    }

async def get_cfg(guild_id: int) -> dict:
    """Get config with defaults"""
    data = await db_get(guild_id)
    defaults = get_default_config()
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
    return data

async def is_immune(member):
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (member.guild.id,)) as cur:
                rows = await cur.fetchall()
                immune_ids = [r[0] for r in rows]
        return any(role.id in immune_ids for role in member.roles)
    except:
        return False

async def apply_action(member, action, duration, reason):
    try:
        if action == 'mute' and duration > 0:
            await member.timeout(timedelta(minutes=duration), reason=reason)
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
    return ''.join(result)

def check_badwords(content, badwords):
    if not badwords:
        return False, None
    normalized = normalize_text(content)
    no_spaces = re.sub(r'[^a-z]', '', normalized)
    for word in badwords:
        word_norm = normalize_text(word.strip())
        if word_norm in normalized or word_norm in no_spaces:
            return True, word
    return False, None

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

def check_caps(content, percent, min_len):
    if len(content) < min_len:
        return False
    letters = [c for c in content if c.isalpha()]
    if not letters:
        return False
    return (sum(1 for c in letters if c.isupper()) / len(letters) * 100) >= percent

def check_image(attachment, allowed):
    ext = attachment.filename.lower().split('.')[-1]
    if ext not in ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']:
        return False
    if not allowed:
        return True
    return ext not in [a.lower().replace('.', '') for a in allowed]

async def check_spam(msg, max_msg, interval):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker:
        spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n - t).total_seconds() < interval]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > max_msg

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════

PROTECTIONS = [
    {"key": "anti_link", "emoji": "🔗", "name": "Anti-Liens", "list_key": "link_whitelist"},
    {"key": "anti_invite", "emoji": "🎟️", "name": "Anti-Invite", "list_key": None},
    {"key": "anti_image", "emoji": "🖼️", "name": "Anti-Images", "list_key": "image_allowed"},
    {"key": "anti_phishing", "emoji": "🎣", "name": "Anti-Phishing", "list_key": None},
    {"key": "anti_scam", "emoji": "🚨", "name": "Anti-Scam", "list_key": None},
    {"key": "anti_spam", "emoji": "📨", "name": "Anti-Spam", "list_key": None},
    {"key": "anti_mention", "emoji": "📢", "name": "Anti-Ping", "list_key": "mention_protected_roles"},
    {"key": "anti_caps", "emoji": "🔠", "name": "Anti-Caps", "list_key": None},
    {"key": "anti_badwords", "emoji": "🤬", "name": "Anti-Insultes", "list_key": "badwords_list"},
    {"key": "anti_newaccount", "emoji": "👶", "name": "Anti-NewAccount", "list_key": None},
]

class MainPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"Serveur: **{self.guild.name}**"
        return e

    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def protection(self, i, b):
        view = ProtPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=0)
    async def welcome(self, i, b):
        view = WelcomePanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=1)
    async def close(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        cfg = await get_cfg(self.guild.id)
        lines = []
        for p in PROTECTIONS:
            status = "✅" if cfg.get(p["key"]) else "❌"
            extra = ""
            if p["list_key"]:
                lst = cfg.get(p["list_key"], [])
                if isinstance(lst, list):
                    extra = f" ({len(lst)})"
            lines.append(f"{p['emoji']} {p['name']}: {status}{extra}")
        
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = "```\n" + "\n".join(lines) + "\n```"
        return e

    @discord.ui.select(
        placeholder="🛡️ Choisir une protection...",
        options=[discord.SelectOption(label=p["name"], value=p["key"], emoji=p["emoji"]) for p in PROTECTIONS],
        row=0
    )
    async def select_prot(self, i, s):
        key = s.values[0]
        prot = next(p for p in PROTECTIONS if p["key"] == key)
        view = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        view = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION DETAIL
# ═══════════════════════════════════════════════════════════════════════════════

class ProtDetail(View):
    def __init__(self, user, guild, prot):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
        self.prot = prot
        self.key = prot["key"]

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        cfg = await get_cfg(self.guild.id)
        is_on = bool(cfg.get(self.key))
        
        e = discord.Embed(
            title=f"{self.prot['emoji']} {self.prot['name']}",
            color=C.GREEN if is_on else C.RED
        )
        e.add_field(name="État", value="✅ ACTIVÉ" if is_on else "❌ DÉSACTIVÉ", inline=False)
        
        # Affichage spécifique
        if self.key == "anti_link":
            items = cfg.get('link_whitelist', [])
            if not isinstance(items, list):
                items = []
            txt = "\n".join([f"• `{d}`" for d in items]) if items else "*Aucun domaine*"
            e.add_field(name=f"Domaines autorisés ({len(items)})", value=txt[:1000], inline=False)
            
        elif self.key == "anti_image":
            items = cfg.get('image_allowed', [])
            if not isinstance(items, list):
                items = []
            all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
            allowed = " ".join([f"✅`{f}`" for f in items]) if items else "*Aucun (tout bloqué)*"
            blocked = " ".join([f"❌`{f}`" for f in all_fmt if f not in items])
            e.add_field(name=f"Autorisés ({len(items)})", value=allowed, inline=False)
            e.add_field(name="Bloqués", value=blocked or "*Aucun*", inline=False)
            
        elif self.key == "anti_badwords":
            items = cfg.get('badwords_list', [])
            if not isinstance(items, list):
                items = []
            txt = ", ".join([f"`{w}`" for w in items[:30]]) if items else "*Aucun mot*"
            e.add_field(name=f"Mots interdits ({len(items)})", value=txt[:1000], inline=False)
            e.add_field(name="Sanction", value=f"`{cfg.get('badwords_action', 'delete')}`", inline=False)
            e.add_field(name="💡", value="Ajoutez plusieurs mots: `mot1,mot2,mot3`", inline=False)
            
        elif self.key == "anti_mention":
            roles = cfg.get('mention_protected_roles', [])
            users = cfg.get('mention_protected_users', [])
            if not isinstance(roles, list):
                roles = []
            if not isinstance(users, list):
                users = []
            e.add_field(name=f"Rôles protégés ({len(roles)})", 
                value=", ".join([f"<@&{r}>" for r in roles[:10]]) or "*Aucun*", inline=False)
            e.add_field(name=f"Membres protégés ({len(users)})", 
                value=", ".join([f"<@{u}>" for u in users[:10]]) or "*Aucun*", inline=False)
            e.add_field(name="Config", 
                value=f"Max: {cfg.get('mention_max_count', 3)} pings → `{cfg.get('mention_action', 'warn')}`", inline=False)
                
        elif self.key == "anti_spam":
            e.add_field(name="Config", value=f"{cfg.get('spam_max_msg', 5)} msg / {cfg.get('spam_interval', 5)}s → `{cfg.get('spam_action', 'mute')}`", inline=False)
            
        elif self.key == "anti_caps":
            e.add_field(name="Config", value=f"{cfg.get('caps_percent', 70)}% max → `{cfg.get('caps_action', 'delete')}`", inline=False)
            
        elif self.key == "anti_newaccount":
            e.add_field(name="Config", value=f"Compte < {cfg.get('newaccount_value', 7)} {cfg.get('newaccount_unit', 'jours')} → kick", inline=False)
            
        elif self.key == "anti_phishing":
            e.add_field(name="Sanction", value=f"`{cfg.get('phishing_action', 'ban')}`", inline=False)
            
        elif self.key == "anti_scam":
            e.add_field(name="Sanction", value=f"`{cfg.get('scam_action', 'mute')}`", inline=False)
        
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        cfg = await get_cfg(self.guild.id)
        new_val = 0 if cfg.get(self.key) else 1
        await db_set(self.guild.id, self.key, new_val)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def configure(self, i, b):
        if self.key == "anti_link":
            view = LinkConfig(self.user, self.guild)
            await i.response.edit_message(embed=await view.embed(), view=view)
        elif self.key == "anti_image":
            view = ImageConfig(self.user, self.guild)
            await i.response.edit_message(embed=await view.embed(), view=view)
        elif self.key == "anti_badwords":
            view = BadwordsConfig(self.user, self.guild)
            await i.response.edit_message(embed=await view.embed(), view=view)
        elif self.key == "anti_mention":
            view = MentionConfig(self.user, self.guild)
            await i.response.edit_message(embed=await view.embed(), view=view)
        elif self.key in ["anti_phishing", "anti_scam"]:
            await i.response.send_modal(ActionModal(self.guild, self.key))
        elif self.key == "anti_spam":
            await i.response.send_modal(SpamModal(self.guild))
        elif self.key == "anti_caps":
            await i.response.send_modal(CapsModal(self.guild))
        elif self.key == "anti_newaccount":
            await i.response.send_modal(NewAccModal(self.guild))
        else:
            await i.response.send_message("❌ Pas de config disponible", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        view = ProtPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔗 ANTI-LIENS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('link_whitelist', [])
        if not isinstance(items, list):
            items = []
        
        e = discord.Embed(title="🔗 Anti-Liens - Config", color=C.BLUE)
        txt = "\n".join([f"• `{d}`" for d in items]) if items else "*Aucun domaine autorisé*"
        e.add_field(name=f"Domaines ({len(items)})", value=txt[:1000], inline=False)
        e.add_field(name="💡 Astuce", value="Ajoutez plusieurs domaines:\n`youtube.com,twitter.com,twitch.tv`", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddListModal(self.guild, 'link_whitelist', "domaine(s)"))

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('link_whitelist', [])
        if not items:
            return await i.response.send_message("❌ Liste vide", ephemeral=True)
        view = RemoveListItem(self.user, self.guild, items, 'link_whitelist', "anti_link")
        await i.response.edit_message(embed=discord.Embed(title="➖ Supprimer", color=C.RED), view=view)

    @discord.ui.button(label="🔄 Rafraîchir", style=discord.ButtonStyle.primary, row=0)
    async def refresh(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_link")
        view = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🖼️ ANTI-IMAGES CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ImageConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('image_allowed', [])
        if not isinstance(items, list):
            items = []
        all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        
        e = discord.Embed(title="🖼️ Anti-Images - Config", color=C.BLUE)
        allowed = " ".join([f"✅`{f}`" for f in items]) if items else "*Aucun (tout bloqué)*"
        blocked = [f for f in all_fmt if f not in items]
        e.add_field(name=f"Autorisés ({len(items)})", value=allowed, inline=False)
        e.add_field(name=f"Bloqués ({len(blocked)})", value=" ".join([f"❌`{f}`" for f in blocked]) or "*Aucun*", inline=False)
        return e

    @discord.ui.button(label="➕ Autoriser", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('image_allowed', [])
        if not isinstance(items, list):
            items = []
        all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        available = [f for f in all_fmt if f not in items]
        if not available:
            return await i.response.send_message("✅ Tous les formats sont déjà autorisés", ephemeral=True)
        view = AddFormat(self.user, self.guild, available)
        await i.response.edit_message(embed=discord.Embed(title="➕ Autoriser format", color=C.GREEN), view=view)

    @discord.ui.button(label="➖ Bloquer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('image_allowed', [])
        if not items:
            return await i.response.send_message("❌ Liste vide", ephemeral=True)
        view = RemoveFormat(self.user, self.guild, items)
        await i.response.edit_message(embed=discord.Embed(title="➖ Bloquer format", color=C.RED), view=view)

    @discord.ui.button(label="🔄 Rafraîchir", style=discord.ButtonStyle.primary, row=0)
    async def refresh(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_image")
        view = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await view.embed(), view=view)

class AddFormat(View):
    def __init__(self, user, guild, formats):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        options = [discord.SelectOption(label=f.upper(), value=f) for f in formats]
        select = Select(placeholder="Format...", options=options, row=0)
        select.callback = self.on_select
        self.add_item(select)

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def on_select(self, i):
        fmt = i.data['values'][0]
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('image_allowed', [])
        if not isinstance(items, list):
            items = []
        if fmt not in items:
            items.append(fmt)
            await db_set(self.guild.id, 'image_allowed', items)
        view = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        view = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

class RemoveFormat(View):
    def __init__(self, user, guild, formats):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        options = [discord.SelectOption(label=f.upper(), value=f) for f in formats]
        select = Select(placeholder="Format...", options=options, row=0)
        select.callback = self.on_select
        self.add_item(select)

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def on_select(self, i):
        fmt = i.data['values'][0]
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('image_allowed', [])
        if isinstance(items, list) and fmt in items:
            items.remove(fmt)
            await db_set(self.guild.id, 'image_allowed', items)
        view = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        view = ImageConfig(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🤬 ANTI-BADWORDS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class BadwordsConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('badwords_list', [])
        if not isinstance(items, list):
            items = []
        
        e = discord.Embed(title="🤬 Anti-Insultes - Config", color=C.BLUE)
        e.add_field(name="Sanction", value=f"`{cfg.get('badwords_action', 'delete')}`", inline=False)
        txt = ", ".join([f"`{w}`" for w in items[:40]]) if items else "*Aucun mot*"
        e.add_field(name=f"Mots interdits ({len(items)})", value=txt[:1000], inline=False)
        e.add_field(name="💡", value="Ajoutez plusieurs: `mot1,mot2,mot3` (sans espaces)", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddListModal(self.guild, 'badwords_list', "mot(s)"))

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('badwords_list', [])
        if not items:
            return await i.response.send_message("❌ Liste vide", ephemeral=True)
        view = RemoveListItem(self.user, self.guild, items, 'badwords_list', "anti_badwords")
        await i.response.edit_message(embed=discord.Embed(title="➖ Supprimer", color=C.RED), view=view)

    @discord.ui.button(label="⚙️ Sanction", style=discord.ButtonStyle.secondary, row=0)
    async def action(self, i, b):
        await i.response.send_modal(BadwordActionModal(self.guild))

    @discord.ui.button(label="🔄 Rafraîchir", style=discord.ButtonStyle.primary, row=1)
    async def refresh(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_badwords")
        view = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 ANTI-MENTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class MentionConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        cfg = await get_cfg(self.guild.id)
        roles = cfg.get('mention_protected_roles', [])
        users = cfg.get('mention_protected_users', [])
        
        e = discord.Embed(title="📢 Anti-Ping - Config", color=C.BLUE)
        e.add_field(name=f"Rôles protégés ({len(roles)})", 
            value=", ".join([f"<@&{r}>" for r in roles[:10]]) or "*Aucun*", inline=False)
        e.add_field(name=f"Membres protégés ({len(users)})", 
            value=", ".join([f"<@{u}>" for u in users[:10]]) or "*Aucun*", inline=False)
        e.add_field(name="Config", 
            value=f"Max: {cfg.get('mention_max_count', 3)} pings → `{cfg.get('mention_action', 'warn')}`", inline=False)
        return e

    @discord.ui.button(label="➕ Rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        roles = [r for r in self.guild.roles[1:] if not r.is_bot_managed()][:25]
        if not roles:
            return await i.response.send_message("❌ Aucun rôle", ephemeral=True)
        view = AddRoleView(self.user, self.guild, roles)
        await i.response.edit_message(embed=discord.Embed(title="➕ Rôle", color=C.GREEN), view=view)

    @discord.ui.button(label="➕ Membre", style=discord.ButtonStyle.success, row=0)
    async def add_user(self, i, b):
        await i.response.send_modal(AddUserModal(self.guild))

    @discord.ui.button(label="⚙️ Config", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        await i.response.send_modal(MentionModal(self.guild))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_mention")
        view = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await view.embed(), view=view)

class AddRoleView(View):
    def __init__(self, user, guild, roles):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        select = Select(placeholder="Rôle...", options=options, row=0)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        rid = int(i.data['values'][0])
        cfg = await get_cfg(self.guild.id)
        items = cfg.get('mention_protected_roles', [])
        if rid not in items:
            items.append(rid)
            await db_set(self.guild.id, 'mention_protected_roles', items)
        view = MentionConfig(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        view = MentionConfig(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📝 MODALS
# ═══════════════════════════════════════════════════════════════════════════════

class AddListModal(Modal):
    def __init__(self, guild, key, item_type):
        super().__init__(title=f"➕ Ajouter {item_type}")
        self.guild = guild
        self.key = key
        self.input = TextInput(
            label=f"{item_type} (virgule = plusieurs)",
            placeholder="item1,item2,item3",
            style=discord.TextStyle.paragraph,
            max_length=500
        )
        self.add_item(self.input)

    async def on_submit(self, i):
        try:
            cfg = await get_cfg(self.guild.id)
            items = cfg.get(self.key, [])
            if not isinstance(items, list):
                items = []
            
            # Parse input (split by comma, remove spaces)
            raw = self.input.value.replace(' ', '')
            new_items = [x.strip().lower() for x in raw.split(',') if x.strip()]
            
            added = []
            for item in new_items:
                if item and item not in items:
                    items.append(item)
                    added.append(item)
            
            if added:
                success = await db_set(self.guild.id, self.key, items)
                if success:
                    await i.response.send_message(f"✅ Ajouté: `{', '.join(added)}`\nTotal: {len(items)}", ephemeral=True)
                else:
                    await i.response.send_message("❌ Erreur de sauvegarde", ephemeral=True)
            else:
                await i.response.send_message("⚠️ Rien de nouveau à ajouter", ephemeral=True)
        except Exception as e:
            print(f"[MODAL ERROR] {e}")
            traceback.print_exc()
            await i.response.send_message(f"❌ Erreur: {e}", ephemeral=True)

class RemoveListItem(View):
    def __init__(self, user, guild, items, key, prot_key):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.key = key
        self.prot_key = prot_key
        options = [discord.SelectOption(label=str(x)[:25], value=str(x)) for x in items[:25]]
        select = Select(placeholder="Supprimer...", options=options, row=0)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        value = i.data['values'][0]
        cfg = await get_cfg(self.guild.id)
        items = cfg.get(self.key, [])
        
        # Try as int first (for IDs)
        try:
            int_val = int(value)
            if int_val in items:
                items.remove(int_val)
        except:
            if value in items:
                items.remove(value)
        
        await db_set(self.guild.id, self.key, items)
        await i.response.send_message(f"✅ Supprimé: `{value}`", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        if self.prot_key == "anti_link":
            view = LinkConfig(self.user, self.guild)
        elif self.prot_key == "anti_badwords":
            view = BadwordsConfig(self.user, self.guild)
        else:
            view = ProtPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.embed(), view=view)

class ActionModal(Modal):
    def __init__(self, guild, key):
        super().__init__(title="⚙️ Sanction")
        self.guild = guild
        self.key = key
        self.action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="ban", max_length=10)
        self.add_item(self.action)

    async def on_submit(self, i):
        action = self.action.value.lower().strip()
        if action not in ['delete', 'mute', 'kick', 'ban']:
            action = 'ban'
        action_key = 'phishing_action' if self.key == 'anti_phishing' else 'scam_action'
        await db_set(self.guild.id, action_key, action)
        await i.response.send_message(f"✅ Sanction: `{action}`", ephemeral=True)

class SpamModal(Modal, title="📨 Anti-Spam"):
    max_msg = TextInput(label="Messages max", placeholder="5", default="5", max_length=3)
    interval = TextInput(label="Intervalle (secondes)", placeholder="5", default="5", max_length=3)
    action = TextInput(label="Sanction (delete/mute/kick)", placeholder="mute", default="mute", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        mm = int(self.max_msg.value) if self.max_msg.value.isdigit() else 5
        itv = int(self.interval.value) if self.interval.value.isdigit() else 5
        action = self.action.value.lower().strip()
        await db_set(self.guild.id, 'spam_max_msg', mm)
        await db_set(self.guild.id, 'spam_interval', itv)
        await db_set(self.guild.id, 'spam_action', action)
        await i.response.send_message(f"✅ {mm}msg/{itv}s → `{action}`", ephemeral=True)

class CapsModal(Modal, title="🔠 Anti-Caps"):
    percent = TextInput(label="Pourcentage max", placeholder="70", default="70", max_length=3)
    action = TextInput(label="Sanction (delete/mute/kick)", placeholder="delete", default="delete", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        pct = int(self.percent.value) if self.percent.value.isdigit() else 70
        action = self.action.value.lower().strip()
        await db_set(self.guild.id, 'caps_percent', pct)
        await db_set(self.guild.id, 'caps_action', action)
        await i.response.send_message(f"✅ {pct}% → `{action}`", ephemeral=True)

class NewAccModal(Modal, title="👶 Anti-NewAccount"):
    value = TextInput(label="Âge minimum", placeholder="7", default="7", max_length=4)
    unit = TextInput(label="Unité (jours/semaines/mois)", placeholder="jours", default="jours", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        val = int(self.value.value) if self.value.value.isdigit() else 7
        unit = self.unit.value.lower().strip()
        if unit not in ['jours', 'semaines', 'mois']:
            unit = 'jours'
        await db_set(self.guild.id, 'newaccount_value', val)
        await db_set(self.guild.id, 'newaccount_unit', unit)
        await i.response.send_message(f"✅ < {val} {unit} → kick", ephemeral=True)

class BadwordActionModal(Modal, title="⚙️ Sanction"):
    action = TextInput(label="Sanction (delete/warn/kick)", placeholder="delete", default="delete", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        action = self.action.value.lower().strip()
        if action not in ['delete', 'warn', 'kick']:
            action = 'delete'
        await db_set(self.guild.id, 'badwords_action', action)
        await i.response.send_message(f"✅ Sanction: `{action}`", ephemeral=True)

class AddUserModal(Modal, title="➕ Membre protégé"):
    user_id = TextInput(label="ID du membre", placeholder="123456789", max_length=20)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        try:
            uid = int(self.user_id.value)
            member = i.guild.get_member(uid)
            if not member:
                return await i.response.send_message("❌ Membre introuvable", ephemeral=True)
            cfg = await get_cfg(self.guild.id)
            items = cfg.get('mention_protected_users', [])
            if uid not in items:
                items.append(uid)
                await db_set(self.guild.id, 'mention_protected_users', items)
            await i.response.send_message(f"✅ {member.mention} ajouté", ephemeral=True)
        except ValueError:
            await i.response.send_message("❌ ID invalide", ephemeral=True)

class MentionModal(Modal, title="📢 Config Anti-Ping"):
    max_count = TextInput(label="Pings max", placeholder="3", default="3", max_length=3)
    action = TextInput(label="Sanction (warn/mute/kick/ban)", placeholder="warn", default="warn", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        count = int(self.max_count.value) if self.max_count.value.isdigit() else 3
        action = self.action.value.lower().strip()
        if action not in ['warn', 'mute', 'kick', 'ban']:
            action = 'warn'
        await db_set(self.guild.id, 'mention_max_count', count)
        await db_set(self.guild.id, 'mention_action', action)
        await i.response.send_message(f"✅ {count} pings → `{action}`", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👋 WELCOME PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class WelcomePanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        cfg = await get_cfg(self.guild.id)
        ch = self.guild.get_channel(cfg.get('welcome_channel', 0))
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"État: {'✅' if cfg.get('welcome_on') else '❌'}\nSalon: {ch.mention if ch else '❌'}"
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        cfg = await get_cfg(self.guild.id)
        await db_set(self.guild.id, 'welcome_on', 0 if cfg.get('welcome_on') else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, i, b):
        view = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await db_init()
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v9.8 prêt!")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return
    if await is_immune(msg.author):
        return

    try:
        cfg = await get_cfg(msg.guild.id)
        content = msg.content

        # Anti-Phishing
        if cfg.get('anti_phishing') and check_phishing(content):
            await msg.delete()
            await apply_action(msg.author, cfg.get('phishing_action', 'ban'), 60, "Phishing")
            return

        # Anti-Scam
        if cfg.get('anti_scam') and check_scam(content):
            await msg.delete()
            await apply_action(msg.author, cfg.get('scam_action', 'mute'), cfg.get('scam_duration', 60), "Scam")
            return

        # Anti-Badwords
        if cfg.get('anti_badwords'):
            badwords = cfg.get('badwords_list', [])
            is_bad, word = check_badwords(content, badwords)
            if is_bad:
                await msg.delete()
                action = cfg.get('badwords_action', 'delete')
                if action != 'delete':
                    await apply_action(msg.author, action, 0, "Mot interdit")
                return

        # Anti-Invite
        if cfg.get('anti_invite') and check_invite(content):
            await msg.delete()
            return

        # Anti-Links
        if cfg.get('anti_link'):
            whitelist = cfg.get('link_whitelist', [])
            if check_link(content, whitelist):
                await msg.delete()
                return

        # Anti-Images
        if cfg.get('anti_image') and msg.attachments:
            allowed = cfg.get('image_allowed', [])
            for att in msg.attachments:
                if check_image(att, allowed):
                    await msg.delete()
                    return

        # Anti-Spam
        if cfg.get('anti_spam'):
            if await check_spam(msg, cfg.get('spam_max_msg', 5), cfg.get('spam_interval', 5)):
                await msg.delete()
                await apply_action(msg.author, cfg.get('spam_action', 'mute'), 10, "Spam")
                return

        # Anti-Caps
        if cfg.get('anti_caps'):
            if check_caps(content, cfg.get('caps_percent', 70), cfg.get('caps_min_len', 10)):
                await msg.delete()
                return
    except Exception as e:
        print(f"[MSG ERROR] {e}")

@bot.event
async def on_member_join(member):
    try:
        cfg = await get_cfg(member.guild.id)

        # Anti-NewAccount
        if cfg.get('anti_newaccount'):
            val = cfg.get('newaccount_value', 7)
            unit = cfg.get('newaccount_unit', 'jours')
            days = val * (7 if unit == 'semaines' else 30 if unit == 'mois' else 1)
            age = (now() - member.created_at.replace(tzinfo=timezone.utc)).days
            if age < days:
                await member.kick(reason=f"Compte récent ({age}j)")
                return

        # Welcome
        if cfg.get('welcome_on') and cfg.get('welcome_channel'):
            ch = member.guild.get_channel(cfg['welcome_channel'])
            if ch:
                txt = cfg.get('welcome_msg', 'Bienvenue {member}!').format(
                    member=member.mention, server=member.guild.name)
                e = discord.Embed(title="👋", description=txt, color=C.GREEN)
                await ch.send(embed=e)
    except Exception as e:
        print(f"[JOIN ERROR] {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Configuration")
async def configure_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin requis", ephemeral=True)
    view = MainPanel(interaction.user, interaction.guild)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir")
@app_commands.describe(membre="Membre", raison="Raison")
async def warn_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message("❌", ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions (guild_id, user_id, mod_id, type, reason) VALUES (?, ?, ?, ?, ?)',
            (interaction.guild.id, membre.id, interaction.user.id, 'warn', raison))
        await db.commit()
    await interaction.response.send_message(f"⚠️ {membre.mention} averti: {raison}")

@bot.tree.command(name="dbtest", description="🔧 Test DB")
async def dbtest_cmd(interaction: discord.Interaction):
    """Test la base de données"""
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌", ephemeral=True)
    
    # Test write
    test_key = "test_value"
    await db_set(interaction.guild.id, "test_key", test_key)
    
    # Test read
    cfg = await get_cfg(interaction.guild.id)
    read_value = cfg.get("test_key")
    
    # Show current link whitelist
    whitelist = cfg.get('link_whitelist', [])
    
    await interaction.response.send_message(
        f"**🔧 Test DB**\n"
        f"📁 Path: `{DB_PATH}`\n"
        f"✅ Write: `test_key` = `{test_key}`\n"
        f"📖 Read: `{read_value}`\n"
        f"🔗 Whitelist: `{whitelist}`\n"
        f"{'✅ DB fonctionne!' if read_value == test_key else '❌ Erreur DB'}",
        ephemeral=True
    )

if __name__ == "__main__":
    print(f"🚀 v9.8 | DB: {DB_PATH}")
    bot.run(TOKEN)
