# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v9.7 🌟                                 ║
# ║     Corrections Complètes - Gestion Erreurs Robuste                           ║
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
DB_PATH = os.getenv('DB_PATH', '/data/database.db')
if not os.path.exists('/data'):
    DB_PATH = 'database.db'

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}
mention_tracker = {}

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PINK=0xEB459E; PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22

PHISHING_DOMAINS = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com','discordi.gift','discord-app.com','discordapp.co','discrod.com','dlscord.org']
SCAM_PATTERNS = [r'free\s*nitro',r'discord\s*nitro\s*free',r'steam\s*gift',r'claim\s*your\s*gift',r'@everyone.*http']

LEET_MAP = {
    'a': ['a','@','4','à','á','â','ã','ä','å'], 'b': ['b','8','ß'], 'c': ['c','(','<','ç'],
    'e': ['e','3','€','è','é','ê','ë'], 'g': ['g','9','6'], 'i': ['i','1','!','|','ì','í','î','ï'],
    'l': ['l','1','|'], 'o': ['o','0','ò','ó','ô','õ','ö'], 's': ['s','$','5'],
    't': ['t','7','+'], 'u': ['u','ù','ú','û','ü'], 'z': ['z','2'],
}

def now():
    return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            log_channel INTEGER DEFAULT 0,
            mod_log_channel INTEGER DEFAULT 0,
            welcome_channel INTEGER DEFAULT 0,
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
            badwords_list TEXT DEFAULT '[]',
            mention_protected_roles TEXT DEFAULT '[]',
            mention_protected_users TEXT DEFAULT '[]',
            phishing_action TEXT DEFAULT 'ban',
            scam_action TEXT DEFAULT 'mute',
            scam_duration INTEGER DEFAULT 60,
            spam_max_msg INTEGER DEFAULT 5,
            spam_interval INTEGER DEFAULT 5,
            spam_action TEXT DEFAULT 'mute',
            spam_duration INTEGER DEFAULT 10,
            mention_max_count INTEGER DEFAULT 3,
            mention_action TEXT DEFAULT 'warn',
            caps_percent INTEGER DEFAULT 70,
            caps_min_len INTEGER DEFAULT 10,
            caps_action TEXT DEFAULT 'delete',
            newaccount_value INTEGER DEFAULT 7,
            newaccount_unit TEXT DEFAULT 'jours',
            badwords_action TEXT DEFAULT 'delete',
            welcome_on INTEGER DEFAULT 0,
            welcome_msg TEXT DEFAULT 'Bienvenue {member} !'
        )''')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS ticket_config (guild_id INTEGER PRIMARY KEY, category_id INTEGER, staff_role_id INTEGER)')
        await db.execute('CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, status TEXT DEFAULT "open")')
        await db.execute('CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT)')
        await db.commit()
    print(f"✅ DB initialisée: {DB_PATH}")

async def get_config(guild_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM config WHERE guild_id = ?', (guild_id,)) as cur:
                row = await cur.fetchone()
                if row:
                    return dict(row)
            await db.execute('INSERT OR IGNORE INTO config (guild_id) VALUES (?)', (guild_id,))
            await db.commit()
            async with db.execute('SELECT * FROM config WHERE guild_id = ?', (guild_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else {}
    except Exception as e:
        print(f"[GET_CONFIG ERROR] {e}")
        return {}

async def set_config(guild_id, key, value):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO config (guild_id) VALUES (?)', (guild_id,))
            await db.execute(f'UPDATE config SET {key} = ? WHERE guild_id = ?', (value, guild_id))
            await db.commit()
            print(f"[SET_CONFIG] {guild_id} | {key} = {value[:50] if isinstance(value, str) else value}")
            return True
    except Exception as e:
        print(f"[SET_CONFIG ERROR] {e}")
        return False

def parse_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except:
        return []

async def get_list(guild_id, key):
    config = await get_config(guild_id)
    return parse_list(config.get(key, '[]'))

async def set_list(guild_id, key, items):
    return await set_config(guild_id, key, json.dumps(items, ensure_ascii=False))

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
        found = False
        for letter, variants in LEET_MAP.items():
            if char in variants:
                result.append(letter)
                found = True
                break
        if not found:
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

async def check_mentions(msg, roles, users, max_count):
    count = sum(1 for r in msg.role_mentions if r.id in roles)
    count += sum(1 for u in msg.mentions if u.id in users)
    if count == 0:
        return False
    key = (msg.guild.id, msg.author.id)
    if key not in mention_tracker:
        mention_tracker[key] = 0
    mention_tracker[key] += count
    return mention_tracker[key] >= max_count

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
        self.user = user
        self.guild = guild

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"Serveur: **{self.guild.name}**"
        return e

    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def protection(self, interaction, button):
        try:
            view = ProtectionPanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            print(f"[ERROR] {e}")
            await interaction.response.send_message(f"❌ Erreur", ephemeral=True)

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def logs(self, interaction, button):
        try:
            view = LogsPanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur", ephemeral=True)

    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def immunity(self, interaction, button):
        try:
            view = ImmunityPanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur", ephemeral=True)

    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def welcome(self, interaction, button):
        try:
            view = WelcomePanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur", ephemeral=True)

    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.primary, row=1)
    async def tickets(self, interaction, button):
        try:
            view = TicketsPanel(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur", ephemeral=True)

    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close(self, interaction, button):
        await interaction.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class ProtectionPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def embed(self):
        config = await get_config(self.guild.id)
        lines = []
        for p in PROTECTIONS:
            status = "✅" if config.get(p["key"]) else "❌"
            lines.append(f"{p['emoji']} {p['name']}: {status}")
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = "```\n" + "\n".join(lines) + "\n```\n**Sélectionnez une protection:**"
        return e

    @discord.ui.select(
        placeholder="🛡️ Choisir une protection...",
        options=[discord.SelectOption(label=p["name"], value=p["key"], emoji=p["emoji"]) for p in PROTECTIONS],
        row=0
    )
    async def select_protection(self, interaction, select):
        try:
            key = select.values[0]
            prot = next(p for p in PROTECTIONS if p["key"] == key)
            view = ProtectionDetail(self.user, self.guild, prot)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            print(f"[SELECT ERROR] {e}\n{traceback.format_exc()}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = MainPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION DETAIL
# ═══════════════════════════════════════════════════════════════════════════════

class ProtectionDetail(View):
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
        is_on = bool(config.get(self.key))
        
        e = discord.Embed(
            title=f"{self.prot['emoji']} {self.prot['name']}",
            color=C.GREEN if is_on else C.RED
        )
        e.add_field(name="État", value="✅ ACTIVÉ" if is_on else "❌ DÉSACTIVÉ", inline=False)
        
        if self.key == "anti_link":
            items = parse_list(config.get('link_whitelist'))
            e.add_field(name=f"Domaines autorisés ({len(items)})", 
                value=", ".join([f"`{d}`" for d in items[:20]]) or "*Aucun*", inline=False)
        elif self.key == "anti_image":
            items = parse_list(config.get('image_allowed'))
            all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
            allowed = " ".join([f"✅`{f}`" for f in items]) or "*Aucun*"
            blocked = " ".join([f"❌`{f}`" for f in all_fmt if f not in items])
            e.add_field(name="Autorisés", value=allowed, inline=False)
            e.add_field(name="Bloqués", value=blocked or "*Aucun*", inline=False)
        elif self.key == "anti_badwords":
            items = parse_list(config.get('badwords_list'))
            e.add_field(name=f"Mots interdits ({len(items)})", 
                value=", ".join([f"`{w}`" for w in items[:20]]) or "*Aucun*", inline=False)
            e.add_field(name="Sanction", value=f"`{config.get('badwords_action', 'delete')}`", inline=False)
        elif self.key == "anti_mention":
            roles = parse_list(config.get('mention_protected_roles'))
            users = parse_list(config.get('mention_protected_users'))
            e.add_field(name=f"Rôles protégés ({len(roles)})", 
                value=", ".join([f"<@&{r}>" for r in roles[:10]]) or "*Aucun*", inline=False)
            e.add_field(name=f"Membres protégés ({len(users)})", 
                value=", ".join([f"<@{u}>" for u in users[:10]]) or "*Aucun*", inline=False)
        elif self.key == "anti_phishing":
            e.add_field(name="Sanction", value=f"`{config.get('phishing_action', 'ban')}`", inline=False)
        elif self.key == "anti_scam":
            e.add_field(name="Sanction", value=f"`{config.get('scam_action', 'mute')}`", inline=False)
        elif self.key == "anti_spam":
            e.add_field(name="Config", value=f"{config.get('spam_max_msg', 5)} msg / {config.get('spam_interval', 5)}s", inline=False)
        elif self.key == "anti_caps":
            e.add_field(name="Config", value=f"{config.get('caps_percent', 70)}% max", inline=False)
        elif self.key == "anti_newaccount":
            e.add_field(name="Config", value=f"{config.get('newaccount_value', 7)} {config.get('newaccount_unit', 'jours')}", inline=False)
        
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction, button):
        try:
            config = await get_config(self.guild.id)
            new_val = 0 if config.get(self.key) else 1
            await set_config(self.guild.id, self.key, new_val)
            await interaction.response.edit_message(embed=await self.embed(), view=self)
        except Exception as e:
            print(f"[TOGGLE ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def configure(self, interaction, button):
        try:
            if self.key == "anti_link":
                view = LinkConfig(self.user, self.guild)
                await interaction.response.edit_message(embed=await view.embed(), view=view)
            elif self.key == "anti_image":
                view = ImageConfig(self.user, self.guild)
                await interaction.response.edit_message(embed=await view.embed(), view=view)
            elif self.key == "anti_badwords":
                view = BadwordsConfig(self.user, self.guild)
                await interaction.response.edit_message(embed=await view.embed(), view=view)
            elif self.key == "anti_mention":
                view = MentionConfig(self.user, self.guild)
                await interaction.response.edit_message(embed=await view.embed(), view=view)
            elif self.key in ["anti_phishing", "anti_scam", "anti_spam", "anti_caps", "anti_newaccount"]:
                await interaction.response.send_modal(ConfigModal(self.guild, self.key))
            else:
                await interaction.response.send_message("❌ Pas de config", ephemeral=True)
        except Exception as e:
            print(f"[CONFIG ERROR] {e}\n{traceback.format_exc()}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = ProtectionPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔗 ANTI-LIENS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def embed(self):
        items = await get_list(self.guild.id, 'link_whitelist')
        e = discord.Embed(title="🔗 Anti-Liens - Config", color=C.BLUE)
        e.add_field(name=f"Domaines ({len(items)})", 
            value="\n".join([f"• `{d}`" for d in items]) or "*Vide*", inline=False)
        e.add_field(name="💡 Astuce", value="Ajoutez plusieurs: `youtube.com,twitter.com`", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, button):
        try:
            await interaction.response.send_modal(AddItemModal(self.guild, 'link_whitelist', "domaine(s)"))
        except Exception as e:
            print(f"[ADD ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, interaction, button):
        try:
            items = await get_list(self.guild.id, 'link_whitelist')
            if not items:
                return await interaction.response.send_message("❌ Liste vide", ephemeral=True)
            view = RemoveItem(self.user, self.guild, items, 'link_whitelist')
            await interaction.response.edit_message(embed=view.embed(), view=view)
        except Exception as e:
            print(f"[REMOVE ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_link")
        view = ProtectionDetail(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🖼️ ANTI-IMAGES CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ImageConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def embed(self):
        items = await get_list(self.guild.id, 'image_allowed')
        all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        e = discord.Embed(title="🖼️ Anti-Images - Config", color=C.BLUE)
        e.add_field(name="✅ Autorisés", value=" ".join([f"`{f}`" for f in items]) or "*Aucun (tout bloqué)*", inline=False)
        blocked = [f for f in all_fmt if f not in items]
        e.add_field(name="❌ Bloqués", value=" ".join([f"`{f}`" for f in blocked]) or "*Aucun*", inline=False)
        return e

    @discord.ui.button(label="➕ Autoriser", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, button):
        try:
            items = await get_list(self.guild.id, 'image_allowed')
            all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
            available = [f for f in all_fmt if f not in items]
            if not available:
                return await interaction.response.send_message("✅ Tous autorisés", ephemeral=True)
            view = AddFormat(self.user, self.guild, available)
            await interaction.response.edit_message(embed=discord.Embed(title="➕ Autoriser", color=C.GREEN), view=view)
        except Exception as e:
            print(f"[ADD FORMAT ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="➖ Bloquer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, interaction, button):
        try:
            items = await get_list(self.guild.id, 'image_allowed')
            if not items:
                return await interaction.response.send_message("❌ Liste vide", ephemeral=True)
            view = RemoveFormat(self.user, self.guild, items)
            await interaction.response.edit_message(embed=discord.Embed(title="➖ Bloquer", color=C.RED), view=view)
        except Exception as e:
            print(f"[REMOVE FORMAT ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_image")
        view = ProtectionDetail(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class AddFormat(View):
    def __init__(self, user, guild, formats):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        # Créer le select avec les options
        options = [discord.SelectOption(label=f.upper(), value=f) for f in formats]
        select = Select(placeholder="Format à autoriser...", options=options, row=0)
        select.callback = self.on_select
        self.add_item(select)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def on_select(self, interaction):
        try:
            fmt = interaction.data['values'][0]
            items = await get_list(self.guild.id, 'image_allowed')
            if fmt not in items:
                items.append(fmt)
                await set_list(self.guild.id, 'image_allowed', items)
            view = ImageConfig(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            print(f"[SELECT FORMAT ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = ImageConfig(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class RemoveFormat(View):
    def __init__(self, user, guild, formats):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        # Créer le select avec les options
        options = [discord.SelectOption(label=f.upper(), value=f) for f in formats]
        select = Select(placeholder="Format à bloquer...", options=options, row=0)
        select.callback = self.on_select
        self.add_item(select)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def on_select(self, interaction):
        try:
            fmt = interaction.data['values'][0]
            items = await get_list(self.guild.id, 'image_allowed')
            if fmt in items:
                items.remove(fmt)
                await set_list(self.guild.id, 'image_allowed', items)
            view = ImageConfig(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            print(f"[REMOVE FORMAT ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = ImageConfig(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🤬 ANTI-BADWORDS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class BadwordsConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def embed(self):
        items = await get_list(self.guild.id, 'badwords_list')
        config = await get_config(self.guild.id)
        e = discord.Embed(title="🤬 Anti-Insultes - Config", color=C.BLUE)
        e.add_field(name="Sanction", value=f"`{config.get('badwords_action', 'delete')}`", inline=False)
        e.add_field(name=f"Mots ({len(items)})", 
            value=", ".join([f"`{w}`" for w in items[:30]]) or "*Vide*", inline=False)
        e.add_field(name="💡 Astuce", value="Ajoutez plusieurs: `mot1,mot2,mot3` (sans espaces)", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, button):
        try:
            await interaction.response.send_modal(AddItemModal(self.guild, 'badwords_list', "mot(s)"))
        except Exception as e:
            print(f"[ADD BADWORD ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, interaction, button):
        try:
            items = await get_list(self.guild.id, 'badwords_list')
            if not items:
                return await interaction.response.send_message("❌ Liste vide", ephemeral=True)
            view = RemoveItem(self.user, self.guild, items, 'badwords_list')
            await interaction.response.edit_message(embed=view.embed(), view=view)
        except Exception as e:
            print(f"[REMOVE BADWORD ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="⚙️ Sanction", style=discord.ButtonStyle.secondary, row=0)
    async def action(self, interaction, button):
        try:
            await interaction.response.send_modal(ActionOnlyModal(self.guild, 'badwords_action'))
        except Exception as e:
            print(f"[ACTION ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_badwords")
        view = ProtectionDetail(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 ANTI-MENTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class MentionConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def embed(self):
        config = await get_config(self.guild.id)
        roles = parse_list(config.get('mention_protected_roles'))
        users = parse_list(config.get('mention_protected_users'))
        e = discord.Embed(title="📢 Anti-Ping - Config", color=C.BLUE)
        e.add_field(name=f"Rôles protégés ({len(roles)})", 
            value=", ".join([f"<@&{r}>" for r in roles[:10]]) or "*Aucun*", inline=False)
        e.add_field(name=f"Membres protégés ({len(users)})", 
            value=", ".join([f"<@{u}>" for u in users[:10]]) or "*Aucun*", inline=False)
        e.add_field(name="Config", 
            value=f"Max: {config.get('mention_max_count', 3)} pings → `{config.get('mention_action', 'warn')}`", inline=False)
        return e

    @discord.ui.button(label="➕ Rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, interaction, button):
        try:
            roles = [r for r in self.guild.roles[1:] if not r.is_bot_managed()][:25]
            if not roles:
                return await interaction.response.send_message("❌ Aucun rôle", ephemeral=True)
            view = AddRole(self.user, self.guild, roles)
            await interaction.response.edit_message(embed=discord.Embed(title="➕ Rôle", color=C.GREEN), view=view)
        except Exception as e:
            print(f"[ADD ROLE ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="➕ Membre", style=discord.ButtonStyle.success, row=0)
    async def add_user(self, interaction, button):
        try:
            await interaction.response.send_modal(AddUserModal(self.guild))
        except Exception as e:
            print(f"[ADD USER ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="⚙️ Config", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, interaction, button):
        try:
            await interaction.response.send_modal(MentionModal(self.guild))
        except Exception as e:
            print(f"[MENTION CONFIG ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_mention")
        view = ProtectionDetail(self.user, self.guild, prot)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class AddRole(View):
    def __init__(self, user, guild, roles):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles[:25]]
        select = Select(placeholder="Rôle...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def on_select(self, interaction):
        try:
            rid = int(interaction.data['values'][0])
            items = await get_list(self.guild.id, 'mention_protected_roles')
            if rid not in items:
                items.append(rid)
                await set_list(self.guild.id, 'mention_protected_roles', items)
            view = MentionConfig(self.user, self.guild)
            await interaction.response.edit_message(embed=await view.embed(), view=view)
        except Exception as e:
            print(f"[SELECT ROLE ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        view = MentionConfig(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📝 MODALS
# ═══════════════════════════════════════════════════════════════════════════════

class AddItemModal(Modal):
    def __init__(self, guild, key, item_type):
        super().__init__(title=f"➕ Ajouter {item_type}")
        self.guild = guild
        self.key = key
        self.input = TextInput(
            label=f"{item_type} (séparés par virgule)",
            placeholder="item1,item2,item3",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=True
        )
        self.add_item(self.input)

    async def on_submit(self, interaction):
        try:
            items = await get_list(self.guild.id, self.key)
            new_items = [i.strip().lower() for i in self.input.value.replace(' ', '').split(',') if i.strip()]
            added = []
            for item in new_items:
                if item and item not in items:
                    items.append(item)
                    added.append(item)
            await set_list(self.guild.id, self.key, items)
            if added:
                await interaction.response.send_message(f"✅ Ajouté: `{', '.join(added)}`", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ Rien de nouveau", ephemeral=True)
        except Exception as e:
            print(f"[MODAL ERROR] {e}\n{traceback.format_exc()}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

class RemoveItem(View):
    def __init__(self, user, guild, items, key):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.key = key
        options = [discord.SelectOption(label=str(i)[:25], value=str(i)) for i in items[:25]]
        select = Select(placeholder="Supprimer...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    def embed(self):
        return discord.Embed(title="➖ Supprimer", color=C.RED)

    async def interaction_check(self, interaction):
        return interaction.user.id == self.user.id

    async def on_select(self, interaction):
        try:
            value = interaction.data['values'][0]
            items = await get_list(self.guild.id, self.key)
            # Try int first (for IDs)
            try:
                int_val = int(value)
                if int_val in items:
                    items.remove(int_val)
            except:
                if value in items:
                    items.remove(value)
            await set_list(self.guild.id, self.key, items)
            await interaction.response.send_message(f"✅ Supprimé: `{value}`", ephemeral=True)
        except Exception as e:
            print(f"[REMOVE ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        if self.key == 'link_whitelist':
            view = LinkConfig(self.user, self.guild)
        elif self.key == 'badwords_list':
            view = BadwordsConfig(self.user, self.guild)
        else:
            view = ProtectionPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.embed(), view=view)

class ActionOnlyModal(Modal):
    def __init__(self, guild, key):
        super().__init__(title="⚙️ Sanction")
        self.guild = guild
        self.key = key
        self.action = TextInput(label="Sanction (delete/warn/kick)", placeholder="delete", default="delete", max_length=10, required=True)
        self.add_item(self.action)

    async def on_submit(self, interaction):
        try:
            action = self.action.value.lower().strip()
            if action not in ['delete', 'warn', 'kick', 'mute', 'ban']:
                action = 'delete'
            await set_config(self.guild.id, self.key, action)
            await interaction.response.send_message(f"✅ Sanction: `{action}`", ephemeral=True)
        except Exception as e:
            print(f"[ACTION MODAL ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

class ConfigModal(Modal):
    def __init__(self, guild, key):
        super().__init__(title="⚙️ Configuration")
        self.guild = guild
        self.key = key
        
        if key == "anti_phishing":
            self.action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="ban", default="ban", max_length=10)
            self.add_item(self.action)
        elif key == "anti_scam":
            self.action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="mute", default="mute", max_length=10)
            self.add_item(self.action)
        elif key == "anti_spam":
            self.max_msg = TextInput(label="Messages max", placeholder="5", default="5", max_length=3)
            self.interval = TextInput(label="Intervalle (secondes)", placeholder="5", default="5", max_length=3)
            self.action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="mute", default="mute", max_length=10)
            self.add_item(self.max_msg)
            self.add_item(self.interval)
            self.add_item(self.action)
        elif key == "anti_caps":
            self.percent = TextInput(label="Pourcentage max", placeholder="70", default="70", max_length=3)
            self.action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="delete", default="delete", max_length=10)
            self.add_item(self.percent)
            self.add_item(self.action)
        elif key == "anti_newaccount":
            self.value = TextInput(label="Âge minimum", placeholder="7", default="7", max_length=4)
            self.unit = TextInput(label="Unité (jours/semaines/mois)", placeholder="jours", default="jours", max_length=10)
            self.add_item(self.value)
            self.add_item(self.unit)

    async def on_submit(self, interaction):
        try:
            if self.key == "anti_phishing":
                action = self.action.value.lower().strip()
                if action not in ['delete', 'mute', 'kick', 'ban']:
                    action = 'ban'
                await set_config(self.guild.id, 'phishing_action', action)
            elif self.key == "anti_scam":
                action = self.action.value.lower().strip()
                if action not in ['delete', 'mute', 'kick', 'ban']:
                    action = 'mute'
                await set_config(self.guild.id, 'scam_action', action)
            elif self.key == "anti_spam":
                mm = int(self.max_msg.value) if self.max_msg.value.isdigit() else 5
                itv = int(self.interval.value) if self.interval.value.isdigit() else 5
                action = self.action.value.lower().strip()
                await set_config(self.guild.id, 'spam_max_msg', mm)
                await set_config(self.guild.id, 'spam_interval', itv)
                await set_config(self.guild.id, 'spam_action', action)
            elif self.key == "anti_caps":
                pct = int(self.percent.value) if self.percent.value.isdigit() else 70
                action = self.action.value.lower().strip()
                await set_config(self.guild.id, 'caps_percent', pct)
                await set_config(self.guild.id, 'caps_action', action)
            elif self.key == "anti_newaccount":
                val = int(self.value.value) if self.value.value.isdigit() else 7
                unit = self.unit.value.lower().strip()
                if unit not in ['jours', 'semaines', 'mois']:
                    unit = 'jours'
                await set_config(self.guild.id, 'newaccount_value', val)
                await set_config(self.guild.id, 'newaccount_unit', unit)
            await interaction.response.send_message("✅ Configuré!", ephemeral=True)
        except Exception as e:
            print(f"[CONFIG MODAL ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

class AddUserModal(Modal):
    def __init__(self, guild):
        super().__init__(title="➕ Ajouter membre")
        self.guild = guild
        self.user_id = TextInput(label="ID du membre", placeholder="123456789", max_length=20)
        self.add_item(self.user_id)

    async def on_submit(self, interaction):
        try:
            uid = int(self.user_id.value)
            member = interaction.guild.get_member(uid)
            if not member:
                return await interaction.response.send_message("❌ Membre introuvable", ephemeral=True)
            items = await get_list(self.guild.id, 'mention_protected_users')
            if uid not in items:
                items.append(uid)
                await set_list(self.guild.id, 'mention_protected_users', items)
            await interaction.response.send_message(f"✅ {member.mention} ajouté", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ ID invalide", ephemeral=True)
        except Exception as e:
            print(f"[ADD USER ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

class MentionModal(Modal):
    def __init__(self, guild):
        super().__init__(title="⚙️ Config Anti-Ping")
        self.guild = guild
        self.max_count = TextInput(label="Pings max avant sanction", placeholder="3", default="3", max_length=3)
        self.action = TextInput(label="Sanction (warn/mute/kick/ban)", placeholder="warn", default="warn", max_length=10)
        self.add_item(self.max_count)
        self.add_item(self.action)

    async def on_submit(self, interaction):
        try:
            count = int(self.max_count.value) if self.max_count.value.isdigit() else 3
            action = self.action.value.lower().strip()
            if action not in ['warn', 'mute', 'kick', 'ban']:
                action = 'warn'
            await set_config(self.guild.id, 'mention_max_count', count)
            await set_config(self.guild.id, 'mention_action', action)
            await interaction.response.send_message(f"✅ {count} pings → `{action}`", ephemeral=True)
        except Exception as e:
            print(f"[MENTION MODAL ERROR] {e}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           OTHER PANELS
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        config = await get_config(self.guild.id)
        lc = self.guild.get_channel(config.get('log_channel', 0))
        mc = self.guild.get_channel(config.get('mod_log_channel', 0))
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        e.description = f"📝 Généraux: {lc.mention if lc else '❌'}\n⚔️ Modération: {mc.mention if mc else '❌'}"
        return e

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction, button):
        view = MainPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=view.embed(), view=view)

class ImmunityPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (self.guild.id,)) as cur:
                rows = await cur.fetchall()
        roles = [self.guild.get_role(r[0]) for r in rows if self.guild.get_role(r[0])]
        e = discord.Embed(title="👑 Immunités", color=C.YELLOW)
        e.description = ", ".join([r.mention for r in roles]) if roles else "*Aucun*"
        return e

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction, button):
        view = MainPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=view.embed(), view=view)

class WelcomePanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        config = await get_config(self.guild.id)
        ch = self.guild.get_channel(config.get('welcome_channel', 0))
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"État: {'✅' if config.get('welcome_on') else '❌'}\nSalon: {ch.mention if ch else '❌'}"
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction, button):
        config = await get_config(self.guild.id)
        await set_config(self.guild.id, 'welcome_on', 0 if config.get('welcome_on') else 1)
        await interaction.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction, button):
        view = MainPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=view.embed(), view=view)

class TicketsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild

    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT category_id, staff_role_id FROM ticket_config WHERE guild_id = ?', (self.guild.id,)) as cur:
                row = await cur.fetchone()
        cat = self.guild.get_channel(row[0]) if row and row[0] else None
        staff = self.guild.get_role(row[1]) if row and row[1] else None
        e = discord.Embed(title="🎫 Tickets", color=C.PURPLE)
        e.description = f"📁 Catégorie: {cat.name if cat else '❌'}\n👮 Staff: {staff.mention if staff else '❌'}"
        return e

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction, button):
        view = MainPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=view.embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v9.7 prêt!")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return
    if await is_immune(msg.author):
        return

    try:
        config = await get_config(msg.guild.id)
        content = msg.content

        # Anti-Phishing
        if config.get('anti_phishing') and check_phishing(content):
            await msg.delete()
            await apply_action(msg.author, config.get('phishing_action', 'ban'), 60, "Phishing")
            return

        # Anti-Scam
        if config.get('anti_scam') and check_scam(content):
            await msg.delete()
            await apply_action(msg.author, config.get('scam_action', 'mute'), config.get('scam_duration', 60), "Scam")
            return

        # Anti-Badwords
        if config.get('anti_badwords'):
            badwords = parse_list(config.get('badwords_list'))
            is_bad, word = check_badwords(content, badwords)
            if is_bad:
                await msg.delete()
                action = config.get('badwords_action', 'delete')
                if action != 'delete':
                    await apply_action(msg.author, action, 0, "Mot interdit")
                return

        # Anti-Invite
        if config.get('anti_invite') and check_invite(content):
            await msg.delete()
            return

        # Anti-Links
        if config.get('anti_link'):
            whitelist = parse_list(config.get('link_whitelist'))
            if check_link(content, whitelist):
                await msg.delete()
                return

        # Anti-Images
        if config.get('anti_image') and msg.attachments:
            allowed = parse_list(config.get('image_allowed'))
            for att in msg.attachments:
                if check_image(att, allowed):
                    await msg.delete()
                    return

        # Anti-Spam
        if config.get('anti_spam'):
            if await check_spam(msg, config.get('spam_max_msg', 5), config.get('spam_interval', 5)):
                await msg.delete()
                await apply_action(msg.author, config.get('spam_action', 'mute'), config.get('spam_duration', 10), "Spam")
                return

        # Anti-Mention
        if config.get('anti_mention'):
            roles = parse_list(config.get('mention_protected_roles'))
            users = parse_list(config.get('mention_protected_users'))
            if await check_mentions(msg, roles, users, config.get('mention_max_count', 3)):
                await msg.delete()
                await apply_action(msg.author, config.get('mention_action', 'warn'), 10, "Ping abusif")
                return

        # Anti-Caps
        if config.get('anti_caps'):
            if check_caps(content, config.get('caps_percent', 70), config.get('caps_min_len', 10)):
                await msg.delete()
                action = config.get('caps_action', 'delete')
                if action != 'delete':
                    await apply_action(msg.author, action, 5, "Majuscules")
                return
    except Exception as e:
        print(f"[MESSAGE ERROR] {e}")

@bot.event
async def on_member_join(member):
    try:
        config = await get_config(member.guild.id)

        # Anti-NewAccount
        if config.get('anti_newaccount'):
            val = config.get('newaccount_value', 7)
            unit = config.get('newaccount_unit', 'jours')
            days = val * (7 if unit == 'semaines' else 30 if unit == 'mois' else 1)
            age = (now() - member.created_at.replace(tzinfo=timezone.utc)).days
            if age < days:
                await member.kick(reason=f"Compte trop récent ({age}j)")
                return

        # Welcome
        if config.get('welcome_on') and config.get('welcome_channel'):
            ch = member.guild.get_channel(config['welcome_channel'])
            if ch:
                txt = config.get('welcome_msg', 'Bienvenue {member}!').format(
                    member=member.mention, server=member.guild.name, count=member.guild.member_count)
                e = discord.Embed(title="👋 Bienvenue!", description=txt, color=C.GREEN)
                e.set_thumbnail(url=member.display_avatar.url)
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

if __name__ == "__main__":
    print("🚀 v9.7...")
    bot.run(TOKEN)
