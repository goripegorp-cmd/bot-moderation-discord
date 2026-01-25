# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v9.9 🌟                                 ║
# ║              TOUTES LES PROTECTIONS FONCTIONNELLES                            ║
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

if os.path.exists('/data'):
    DB_PATH = '/data/bot.db'
else:
    DB_PATH = 'bot.db'

print(f"📁 Database: {DB_PATH}")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}
mention_tracker = {}

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PINK=0xEB459E; PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22

PHISHING_DOMAINS = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com','discordi.gift','discord-app.com','discordapp.co','steamcommunity.ru','store-steampowered.com']
SCAM_PATTERNS = [r'free\s*nitro',r'discord\s*nitro\s*free',r'steam\s*gift',r'claim\s*your\s*gift',r'@everyone.*http',r'airdrop.*nitro']

LEET_MAP = {
    'a': ['a','@','4','à','á','â','ä','å','α'], 'b': ['b','8','ß'], 'c': ['c','(','ç','¢'],
    'd': ['d'], 'e': ['e','3','€','è','é','ê','ë'], 'f': ['f'],
    'g': ['g','9','6'], 'h': ['h','#'], 'i': ['i','1','!','|','ì','í','î','ï'],
    'j': ['j'], 'k': ['k'], 'l': ['l','1','|'],
    'm': ['m'], 'n': ['n','ñ'], 'o': ['o','0','ò','ó','ô','ö','ø'],
    'p': ['p'], 'q': ['q'], 'r': ['r'],
    's': ['s','$','5','§'], 't': ['t','7','+'], 'u': ['u','ù','ú','û','ü','µ'],
    'v': ['v'], 'w': ['w'], 'x': ['x','×'],
    'y': ['y','¥'], 'z': ['z','2'],
}

def now():
    return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            data TEXT DEFAULT '{}'
        )''')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        await db.execute('CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, status TEXT DEFAULT "open")')
        await db.execute('CREATE TABLE IF NOT EXISTS ticket_config (guild_id INTEGER PRIMARY KEY, category_id INTEGER, staff_role_id INTEGER)')
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
        print(f"✅ [DB] {key} = {str(value)[:50]}")
        return True
    except Exception as e:
        print(f"❌ [DB ERROR] {e}")
        return False

def get_default():
    return {
        'anti_link': 0, 'anti_invite': 0, 'anti_image': 0, 'anti_phishing': 1,
        'anti_scam': 1, 'anti_spam': 0, 'anti_mention': 0, 'anti_caps': 0,
        'anti_newaccount': 0, 'anti_badwords': 0,
        'link_whitelist': [], 'image_allowed': [], 'badwords_list': [],
        'mention_protected_roles': [], 'mention_protected_users': [],
        'phishing_action': 'ban', 'scam_action': 'mute', 'scam_duration': 60,
        'spam_max_msg': 5, 'spam_interval': 5, 'spam_action': 'mute', 'spam_duration': 10,
        'mention_max_count': 3, 'mention_action': 'warn', 'mention_duration': 10,
        'caps_percent': 70, 'caps_min_len': 10, 'caps_action': 'delete',
        'newaccount_value': 7, 'newaccount_unit': 'jours',
        'badwords_action': 'delete',
        'welcome_on': 0, 'welcome_channel': 0, 'welcome_msg': 'Bienvenue {member} sur {server}!',
        'log_channel': 0, 'mod_log_channel': 0
    }

async def cfg(guild_id: int) -> dict:
    data = await db_get(guild_id)
    defaults = get_default()
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
                return any(role.id in [r[0] for r in rows] for role in member.roles)
    except:
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
        
        # Log
        c = await cfg(guild.id)
        log_ch = guild.get_channel(c.get('mod_log_channel', 0))
        if log_ch:
            e = discord.Embed(title=f"🛡️ {action.upper()}", color=C.RED)
            e.add_field(name="Membre", value=f"{member.mention}", inline=True)
            e.add_field(name="Raison", value=reason, inline=True)
            await log_ch.send(embed=e)
    except Exception as e:
        print(f"[SANCTION ERROR] {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_text(text):
    """Normalise le texte pour anti-contournement"""
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
    # Remove repeated chars
    cleaned = []
    prev = ''
    for c in result:
        if c != prev or not c.isalpha():
            cleaned.append(c)
        prev = c
    return ''.join(cleaned)

def check_badwords(content, badwords):
    """Vérifie les mots interdits avec anti-contournement"""
    if not badwords:
        return False, None
    normalized = normalize_text(content)
    no_spaces = re.sub(r'[^a-z]', '', normalized)
    
    for word in badwords:
        word_norm = normalize_text(word.strip())
        if not word_norm:
            continue
        # Check in normalized
        if word_norm in normalized:
            return True, word
        # Check in no spaces version
        if word_norm in no_spaces:
            return True, word
        # Check with word boundaries
        if re.search(r'\b' + re.escape(word_norm) + r'\b', normalized):
            return True, word
    return False, None

def check_link(content, whitelist):
    """Vérifie les liens - supporte domaines ET URLs complètes"""
    urls = re.findall(r'https?://([^\s<>"]+)', content.lower())
    if not urls:
        return False
    
    for url in urls:
        domain = url.split('/')[0]  # Extraire le domaine
        is_allowed = False
        
        for allowed in whitelist:
            allowed = allowed.lower().strip()
            # Vérifier si c'est une URL complète ou un domaine
            if '/' in allowed:
                # URL complète - doit matcher exactement
                if url.startswith(allowed.replace('https://', '').replace('http://', '')):
                    is_allowed = True
                    break
            else:
                # Domaine - vérifier si le domaine contient l'autorisé
                if allowed in domain:
                    is_allowed = True
                    break
        
        if not is_allowed:
            return True  # Lien non autorisé trouvé
    return False

def check_invite(content):
    """Vérifie les invitations Discord"""
    patterns = [
        r'discord\.gg/[a-zA-Z0-9]+',
        r'discord\.com/invite/[a-zA-Z0-9]+',
        r'discordapp\.com/invite/[a-zA-Z0-9]+'
    ]
    return any(re.search(p, content, re.I) for p in patterns)

def check_phishing(content):
    """Vérifie les liens de phishing"""
    content_lower = content.lower()
    return any(domain in content_lower for domain in PHISHING_DOMAINS)

def check_scam(content):
    """Vérifie les messages d'arnaque"""
    return any(re.search(pattern, content, re.I) for pattern in SCAM_PATTERNS)

def check_caps(content, percent, min_len):
    """Vérifie l'excès de majuscules"""
    if len(content) < min_len:
        return False
    letters = [c for c in content if c.isalpha()]
    if len(letters) < min_len:
        return False
    ratio = sum(1 for c in letters if c.isupper()) / len(letters) * 100
    return ratio >= percent

def check_image(attachment, allowed_formats):
    """Vérifie si une image doit être bloquée"""
    ext = attachment.filename.lower().split('.')[-1]
    image_exts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'ico']
    
    if ext not in image_exts:
        return False  # Pas une image
    
    if not allowed_formats:
        return True  # Liste vide = tout bloqué
    
    allowed_clean = [f.lower().replace('.', '').strip() for f in allowed_formats]
    return ext not in allowed_clean

async def check_spam(msg, max_msg, interval):
    """Vérifie le spam de messages"""
    key = (msg.guild.id, msg.author.id)
    n = now()
    
    if key not in spam_tracker:
        spam_tracker[key] = []
    
    # Nettoyer les anciens
    spam_tracker[key] = [t for t in spam_tracker[key] if (n - t).total_seconds() < interval]
    spam_tracker[key].append(n)
    
    return len(spam_tracker[key]) > max_msg

async def check_mentions(msg, protected_roles, protected_users, max_count):
    """Vérifie les mentions de rôles/membres protégés"""
    if not protected_roles and not protected_users:
        return False
    
    count = 0
    
    # Compter les rôles mentionnés
    for role in msg.role_mentions:
        if role.id in protected_roles:
            count += 1
    
    # Compter les membres mentionnés
    for user in msg.mentions:
        if user.id in protected_users:
            count += 1
    
    if count == 0:
        return False
    
    # Tracker par utilisateur
    key = (msg.guild.id, msg.author.id)
    if key not in mention_tracker:
        mention_tracker[key] = {'count': 0, 'time': now()}
    
    # Reset après 1h
    if (now() - mention_tracker[key]['time']).total_seconds() > 3600:
        mention_tracker[key] = {'count': 0, 'time': now()}
    
    mention_tracker[key]['count'] += count
    return mention_tracker[key]['count'] >= max_count

def check_new_account(member, min_days):
    """Vérifie si le compte est trop récent"""
    age = (now() - member.created_at.replace(tzinfo=timezone.utc)).days
    return age < min_days

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 PANELS
# ═══════════════════════════════════════════════════════════════════════════════

PROTECTIONS = [
    {"key": "anti_link", "emoji": "🔗", "name": "Anti-Liens", "desc": "Bloque les liens non autorisés"},
    {"key": "anti_invite", "emoji": "🎟️", "name": "Anti-Invite", "desc": "Bloque les invitations Discord"},
    {"key": "anti_image", "emoji": "🖼️", "name": "Anti-Images", "desc": "Bloque certains formats d'images"},
    {"key": "anti_phishing", "emoji": "🎣", "name": "Anti-Phishing", "desc": "Ban les liens de phishing"},
    {"key": "anti_scam", "emoji": "🚨", "name": "Anti-Scam", "desc": "Détecte les arnaques nitro/steam"},
    {"key": "anti_spam", "emoji": "📨", "name": "Anti-Spam", "desc": "Limite les messages rapides"},
    {"key": "anti_mention", "emoji": "📢", "name": "Anti-Ping", "desc": "Protège rôles/membres des pings"},
    {"key": "anti_caps", "emoji": "🔠", "name": "Anti-Caps", "desc": "Bloque les MAJUSCULES excessives"},
    {"key": "anti_badwords", "emoji": "🤬", "name": "Anti-Insultes", "desc": "Bloque les mots interdits"},
    {"key": "anti_newaccount", "emoji": "👶", "name": "Anti-NewAccount", "desc": "Kick les comptes récents"},
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

    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def welc(self, i, b):
        v = WelcomePanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.primary, row=1)
    async def tick(self, i, b):
        v = TicketPanel(self.user, self.guild)
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
                extra = f" ({len(c.get('link_whitelist', []))} domaines)"
            elif p["key"] == "anti_image":
                extra = f" ({len(c.get('image_allowed', []))} formats)"
            elif p["key"] == "anti_badwords":
                extra = f" ({len(c.get('badwords_list', []))} mots)"
            elif p["key"] == "anti_mention":
                r = len(c.get('mention_protected_roles', []))
                u = len(c.get('mention_protected_users', []))
                extra = f" ({r}R/{u}M)"
            lines.append(f"{p['emoji']} {p['name']}: {st}{extra}")
        
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = "```\n" + "\n".join(lines) + "\n```"
        return e

    @discord.ui.select(
        placeholder="🛡️ Sélectionner une protection...",
        options=[discord.SelectOption(label=p["name"], value=p["key"], emoji=p["emoji"], description=p["desc"][:50]) for p in PROTECTIONS],
        row=0
    )
    async def select(self, i, s):
        prot = next(p for p in PROTECTIONS if p["key"] == s.values[0])
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION DETAIL
# ═══════════════════════════════════════════════════════════════════════════════

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
        
        if self.key == "anti_link":
            items = c.get('link_whitelist', [])
            txt = "\n".join([f"• `{d}`" for d in items[:15]]) if items else "*Aucun (tous bloqués)*"
            if len(items) > 15:
                txt += f"\n... +{len(items)-15} autres"
            e.add_field(name=f"✅ Autorisés ({len(items)})", value=txt, inline=False)
            e.add_field(name="💡", value="Domaines: `youtube.com`\nURLs: `twitch.tv/channel`", inline=False)
            
        elif self.key == "anti_invite":
            e.add_field(name="📝 Info", value="Bloque toutes les invitations Discord\n(discord.gg, discord.com/invite)", inline=False)
            
        elif self.key == "anti_image":
            items = c.get('image_allowed', [])
            all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
            allowed = " ".join([f"✅`{f}`" for f in items]) if items else "*Aucun (tout bloqué)*"
            blocked = " ".join([f"❌`{f}`" for f in all_fmt if f not in items])
            e.add_field(name=f"Autorisés ({len(items)})", value=allowed, inline=False)
            e.add_field(name="Bloqués", value=blocked or "*Aucun*", inline=False)
            
        elif self.key == "anti_phishing":
            e.add_field(name="📝 Info", value="Détecte les faux sites Discord/Steam", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('phishing_action', 'ban')}`", inline=False)
            
        elif self.key == "anti_scam":
            e.add_field(name="📝 Info", value="Détecte: free nitro, steam gift, airdrop...", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('scam_action', 'mute')}`", inline=False)
            
        elif self.key == "anti_spam":
            e.add_field(name="📝 Config", value=f"**{c.get('spam_max_msg', 5)}** messages en **{c.get('spam_interval', 5)}**s", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('spam_action', 'mute')}` ({c.get('spam_duration', 10)} min)", inline=False)
            
        elif self.key == "anti_mention":
            roles = c.get('mention_protected_roles', [])
            users = c.get('mention_protected_users', [])
            role_txt = ", ".join([f"<@&{r}>" for r in roles[:5]]) if roles else "*Aucun*"
            user_txt = ", ".join([f"<@{u}>" for u in users[:5]]) if users else "*Aucun*"
            e.add_field(name=f"🛡️ Rôles protégés ({len(roles)})", value=role_txt, inline=False)
            e.add_field(name=f"🛡️ Membres protégés ({len(users)})", value=user_txt, inline=False)
            e.add_field(name="⚡ Config", value=f"**{c.get('mention_max_count', 3)}** pings → `{c.get('mention_action', 'warn')}`", inline=False)
            
        elif self.key == "anti_caps":
            e.add_field(name="📝 Config", value=f"Max **{c.get('caps_percent', 70)}%** de majuscules", inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('caps_action', 'delete')}`", inline=False)
            
        elif self.key == "anti_badwords":
            items = c.get('badwords_list', [])
            txt = ", ".join([f"`{w}`" for w in items[:20]]) if items else "*Aucun mot*"
            if len(items) > 20:
                txt += f" +{len(items)-20}"
            e.add_field(name=f"🚫 Mots interdits ({len(items)})", value=txt, inline=False)
            e.add_field(name="⚡ Sanction", value=f"`{c.get('badwords_action', 'delete')}`", inline=False)
            e.add_field(name="💡", value="Anti-contournement actif!\n`M0t` `m.o.t` `MoT` → détecté", inline=False)
            
        elif self.key == "anti_newaccount":
            val = c.get('newaccount_value', 7)
            unit = c.get('newaccount_unit', 'jours')
            e.add_field(name="📝 Config", value=f"Kick si compte < **{val} {unit}**", inline=False)
        
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
            await i.response.send_modal(ActionModal(self.guild, 'phishing_action', "🎣 Anti-Phishing"))
        elif self.key == "anti_scam":
            await i.response.send_modal(ActionModal(self.guild, 'scam_action', "🚨 Anti-Scam"))
        elif self.key == "anti_spam":
            await i.response.send_modal(SpamModal(self.guild))
        elif self.key == "anti_caps":
            await i.response.send_modal(CapsModal(self.guild))
        elif self.key == "anti_newaccount":
            await i.response.send_modal(NewAccModal(self.guild))
        else:
            await i.response.send_message("❌ Pas de configuration", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ProtPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔗 ANTI-LIENS CONFIG
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
        e = discord.Embed(title="🔗 Anti-Liens - Config", color=C.BLUE)
        txt = "\n".join([f"• `{d}`" for d in items[:20]]) if items else "*Aucun*"
        e.add_field(name=f"Domaines/URLs autorisés ({len(items)})", value=txt, inline=False)
        e.add_field(name="💡 Formats acceptés", value="• Domaine: `youtube.com`\n• URL complète: `twitch.tv/gorp`\n• Plusieurs: `youtube.com,twitter.com`", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddListModal(self.guild, 'link_whitelist', "domaine(s)/URL(s)"))

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        c = await cfg(self.guild.id)
        items = c.get('link_whitelist', [])
        if not items:
            return await i.response.send_message("❌ Liste vide", ephemeral=True)
        v = RemoveListView(self.user, self.guild, items, 'link_whitelist', 'anti_link')
        await i.response.edit_message(embed=discord.Embed(title="➖ Supprimer", color=C.RED), view=v)

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.primary, row=0)
    async def refresh(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_link")
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🖼️ ANTI-IMAGES CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ImageConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        c = await cfg(self.guild.id)
        items = c.get('image_allowed', [])
        all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        e = discord.Embed(title="🖼️ Anti-Images - Config", color=C.BLUE)
        allowed = " ".join([f"✅`{f}`" for f in items]) if items else "*Aucun (tout bloqué)*"
        blocked = [f for f in all_fmt if f not in items]
        e.add_field(name=f"Autorisés ({len(items)})", value=allowed, inline=False)
        e.add_field(name=f"Bloqués ({len(blocked)})", value=" ".join([f"❌`{f}`" for f in blocked]), inline=False)
        return e

    @discord.ui.button(label="➕ Autoriser", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        c = await cfg(self.guild.id)
        items = c.get('image_allowed', [])
        all_fmt = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        available = [f for f in all_fmt if f not in items]
        if not available:
            return await i.response.send_message("✅ Tous autorisés", ephemeral=True)
        v = FormatSelectView(self.user, self.guild, available, 'add')
        await i.response.edit_message(embed=discord.Embed(title="➕ Autoriser", color=C.GREEN), view=v)

    @discord.ui.button(label="➖ Bloquer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        c = await cfg(self.guild.id)
        items = c.get('image_allowed', [])
        if not items:
            return await i.response.send_message("❌ Liste vide", ephemeral=True)
        v = FormatSelectView(self.user, self.guild, items, 'remove')
        await i.response.edit_message(embed=discord.Embed(title="➖ Bloquer", color=C.RED), view=v)

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.primary, row=0)
    async def refresh(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_image")
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class FormatSelectView(View):
    def __init__(self, user, guild, formats, action):
        super().__init__(timeout=300)
        self.user, self.guild, self.action = user, guild, action
        options = [discord.SelectOption(label=f.upper(), value=f) for f in formats]
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

# ═══════════════════════════════════════════════════════════════════════════════
#                           🤬 ANTI-BADWORDS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class BadwordsConfig(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def interaction_check(self, i):
        return i.user.id == self.user.id

    async def embed(self):
        c = await cfg(self.guild.id)
        items = c.get('badwords_list', [])
        e = discord.Embed(title="🤬 Anti-Insultes - Config", color=C.BLUE)
        e.add_field(name="⚡ Sanction", value=f"`{c.get('badwords_action', 'delete')}`", inline=False)
        txt = ", ".join([f"`{w}`" for w in items[:30]]) if items else "*Aucun*"
        e.add_field(name=f"Mots interdits ({len(items)})", value=txt[:1000], inline=False)
        e.add_field(name="💡", value="Ajoutez plusieurs: `mot1,mot2,mot3`\nAnti-contournement: `m0t`, `M.O.T` détectés", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddListModal(self.guild, 'badwords_list', "mot(s)"))

    @discord.ui.button(label="➖ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        c = await cfg(self.guild.id)
        items = c.get('badwords_list', [])
        if not items:
            return await i.response.send_message("❌ Liste vide", ephemeral=True)
        v = RemoveListView(self.user, self.guild, items, 'badwords_list', 'anti_badwords')
        await i.response.edit_message(embed=discord.Embed(title="➖ Supprimer", color=C.RED), view=v)

    @discord.ui.button(label="⚙️ Sanction", style=discord.ButtonStyle.secondary, row=0)
    async def action(self, i, b):
        await i.response.send_modal(BadwordActionModal(self.guild))

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.primary, row=1)
    async def refresh(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_badwords")
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 ANTI-MENTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

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
        e = discord.Embed(title="📢 Anti-Ping - Config", color=C.BLUE)
        e.add_field(name=f"🛡️ Rôles ({len(roles)})", value=", ".join([f"<@&{r}>" for r in roles[:10]]) or "*Aucun*", inline=False)
        e.add_field(name=f"🛡️ Membres ({len(users)})", value=", ".join([f"<@{u}>" for u in users[:10]]) or "*Aucun*", inline=False)
        e.add_field(name="⚡ Config", value=f"**{c.get('mention_max_count', 3)}** pings → `{c.get('mention_action', 'warn')}`", inline=False)
        return e

    @discord.ui.button(label="➕ Rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        roles = [r for r in self.guild.roles[1:] if not r.is_bot_managed()][:25]
        if not roles:
            return await i.response.send_message("❌ Aucun rôle", ephemeral=True)
        v = RoleSelectView(self.user, self.guild, roles)
        await i.response.edit_message(embed=discord.Embed(title="➕ Rôle", color=C.GREEN), view=v)

    @discord.ui.button(label="➕ Membre", style=discord.ButtonStyle.success, row=0)
    async def add_user(self, i, b):
        await i.response.send_modal(AddUserModal(self.guild))

    @discord.ui.button(label="⚙️ Config", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        await i.response.send_modal(MentionModal(self.guild))

    @discord.ui.button(label="🔄", style=discord.ButtonStyle.primary, row=1)
    async def refresh(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTECTIONS if p["key"] == "anti_mention")
        v = ProtDetail(self.user, self.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RoleSelectView(View):
    def __init__(self, user, guild, roles):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
        options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        select = Select(placeholder="Rôle...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, i):
        rid = int(i.data['values'][0])
        c = await cfg(self.guild.id)
        items = c.get('mention_protected_roles', [])
        if rid not in items:
            items.append(rid)
            await db_set(self.guild.id, 'mention_protected_roles', items)
        v = MentionConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MentionConfig(self.user, self.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📝 MODALS
# ═══════════════════════════════════════════════════════════════════════════════

class AddListModal(Modal):
    def __init__(self, guild, key, item_type):
        super().__init__(title=f"➕ Ajouter {item_type}")
        self.guild, self.key = guild, key
        self.input = TextInput(label=f"{item_type} (virgule = plusieurs)", placeholder="item1,item2,item3", style=discord.TextStyle.paragraph, max_length=500)
        self.add_item(self.input)

    async def on_submit(self, i):
        c = await cfg(self.guild.id)
        items = c.get(self.key, [])
        if not isinstance(items, list):
            items = []
        
        raw = self.input.value.replace(' ', '')
        new = [x.strip().lower() for x in raw.split(',') if x.strip()]
        added = [x for x in new if x not in items]
        items.extend(added)
        
        await db_set(self.guild.id, self.key, items)
        if added:
            await i.response.send_message(f"✅ Ajouté: `{', '.join(added)}`\nTotal: {len(items)}", ephemeral=True)
        else:
            await i.response.send_message("⚠️ Déjà présent(s)", ephemeral=True)

class RemoveListView(View):
    def __init__(self, user, guild, items, key, prot_key):
        super().__init__(timeout=300)
        self.user, self.guild, self.key, self.prot_key = user, guild, key, prot_key
        options = [discord.SelectOption(label=str(x)[:25], value=str(x)) for x in items[:25]]
        select = Select(placeholder="Supprimer...", options=options)
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
        await i.response.send_message(f"✅ Supprimé: `{val}`", ephemeral=True)

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
    def __init__(self, guild, key, title):
        super().__init__(title=title)
        self.guild, self.key = guild, key
        self.action = TextInput(label="Sanction (delete/mute/kick/ban)", placeholder="ban", max_length=10)
        self.add_item(self.action)

    async def on_submit(self, i):
        act = self.action.value.lower().strip()
        if act not in ['delete', 'mute', 'kick', 'ban']:
            act = 'ban'
        await db_set(self.guild.id, self.key, act)
        await i.response.send_message(f"✅ Sanction: `{act}`", ephemeral=True)

class SpamModal(Modal, title="📨 Anti-Spam"):
    max_msg = TextInput(label="Messages max", placeholder="5", default="5", max_length=3)
    interval = TextInput(label="Intervalle (secondes)", placeholder="5", default="5", max_length=3)
    action = TextInput(label="Sanction (delete/mute/kick)", placeholder="mute", default="mute", max_length=10)
    duration = TextInput(label="Durée mute (minutes)", placeholder="10", default="10", max_length=4)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        await db_set(self.guild.id, 'spam_max_msg', int(self.max_msg.value) if self.max_msg.value.isdigit() else 5)
        await db_set(self.guild.id, 'spam_interval', int(self.interval.value) if self.interval.value.isdigit() else 5)
        await db_set(self.guild.id, 'spam_action', self.action.value.lower().strip())
        await db_set(self.guild.id, 'spam_duration', int(self.duration.value) if self.duration.value.isdigit() else 10)
        await i.response.send_message("✅ Config sauvegardée", ephemeral=True)

class CapsModal(Modal, title="🔠 Anti-Caps"):
    percent = TextInput(label="Pourcentage max", placeholder="70", default="70", max_length=3)
    action = TextInput(label="Sanction (delete/mute/kick)", placeholder="delete", default="delete", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        await db_set(self.guild.id, 'caps_percent', int(self.percent.value) if self.percent.value.isdigit() else 70)
        await db_set(self.guild.id, 'caps_action', self.action.value.lower().strip())
        await i.response.send_message("✅ Config sauvegardée", ephemeral=True)

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
        await i.response.send_message(f"✅ Compte < {val} {unit} → kick", ephemeral=True)

class BadwordActionModal(Modal, title="⚙️ Sanction"):
    action = TextInput(label="Sanction (delete/warn/kick)", placeholder="delete", default="delete", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        act = self.action.value.lower().strip()
        if act not in ['delete', 'warn', 'kick']:
            act = 'delete'
        await db_set(self.guild.id, 'badwords_action', act)
        await i.response.send_message(f"✅ Sanction: `{act}`", ephemeral=True)

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
            c = await cfg(self.guild.id)
            items = c.get('mention_protected_users', [])
            if uid not in items:
                items.append(uid)
                await db_set(self.guild.id, 'mention_protected_users', items)
            await i.response.send_message(f"✅ {member.mention} protégé", ephemeral=True)
        except:
            await i.response.send_message("❌ ID invalide", ephemeral=True)

class MentionModal(Modal, title="📢 Config"):
    max_count = TextInput(label="Pings max avant sanction", placeholder="3", default="3", max_length=3)
    action = TextInput(label="Sanction (warn/mute/kick/ban)", placeholder="warn", default="warn", max_length=10)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, i):
        count = int(self.max_count.value) if self.max_count.value.isdigit() else 3
        act = self.action.value.lower().strip()
        if act not in ['warn', 'mute', 'kick', 'ban']:
            act = 'warn'
        await db_set(self.guild.id, 'mention_max_count', count)
        await db_set(self.guild.id, 'mention_action', act)
        await i.response.send_message(f"✅ {count} pings → `{act}`", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📜 LOGS / 👑 IMMUNE / 👋 WELCOME / 🎫 TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
        chs = [c for c in guild.text_channels][:25]
        if chs:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
            s1 = Select(placeholder="📝 Logs généraux...", options=opts, row=1)
            s1.callback = lambda i: self.set_log(i, 'log_channel')
            self.add_item(s1)
            s2 = Select(placeholder="⚔️ Logs modération...", options=opts.copy(), row=2)
            s2.callback = lambda i: self.set_log(i, 'mod_log_channel')
            self.add_item(s2)

    async def set_log(self, i, key):
        await db_set(self.guild.id, key, int(i.data['values'][0]))
        await i.response.send_message("✅", ephemeral=True)

    async def embed(self):
        c = await cfg(self.guild.id)
        lc = self.guild.get_channel(c.get('log_channel', 0))
        mc = self.guild.get_channel(c.get('mod_log_channel', 0))
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        e.description = f"📝 Généraux: {lc.mention if lc else '❌'}\n⚔️ Modération: {mc.mention if mc else '❌'}"
        return e

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class ImmunePanel(View):
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
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (self.guild.id,)) as cur:
                ids = [r[0] for r in await cur.fetchall()]
        roles = [self.guild.get_role(rid) for rid in ids if self.guild.get_role(rid)]
        e = discord.Embed(title="👑 Rôles Immunisés", color=C.YELLOW)
        e.description = ", ".join([r.mention for r in roles]) if roles else "*Aucun*"
        e.add_field(name="💡", value="Ces rôles ignorent TOUTES les protections", inline=False)
        return e

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class WelcomePanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
        chs = [c for c in guild.text_channels][:25]
        if chs:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
            sel = Select(placeholder="👋 Salon...", options=opts, row=2)
            sel.callback = self.set_ch
            self.add_item(sel)

    async def set_ch(self, i):
        await db_set(self.guild.id, 'welcome_channel', int(i.data['values'][0]))
        await i.response.send_message("✅", ephemeral=True)

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

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

class TicketPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild

    async def embed(self):
        e = discord.Embed(title="🎫 Tickets", color=C.PURPLE)
        e.description = "Système de tickets support"
        return e

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await db_init()
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v9.9 prêt!")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return
    if await is_immune(msg.author):
        return

    try:
        c = await cfg(msg.guild.id)
        content = msg.content

        # 🎣 Anti-Phishing (PRIORITÉ MAX)
        if c.get('anti_phishing') and check_phishing(content):
            await msg.delete()
            await apply_sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing détecté", msg.guild)
            return

        # 🚨 Anti-Scam
        if c.get('anti_scam') and check_scam(content):
            await msg.delete()
            await apply_sanction(msg.author, c.get('scam_action', 'mute'), c.get('scam_duration', 60), "Scam détecté", msg.guild)
            return

        # 🤬 Anti-Badwords
        if c.get('anti_badwords'):
            badwords = c.get('badwords_list', [])
            is_bad, word = check_badwords(content, badwords)
            if is_bad:
                await msg.delete()
                action = c.get('badwords_action', 'delete')
                if action != 'delete':
                    await apply_sanction(msg.author, action, 0, f"Mot interdit", msg.guild)
                return

        # 🎟️ Anti-Invite
        if c.get('anti_invite') and check_invite(content):
            await msg.delete()
            return

        # 🔗 Anti-Liens
        if c.get('anti_link'):
            whitelist = c.get('link_whitelist', [])
            if check_link(content, whitelist):
                await msg.delete()
                return

        # 🖼️ Anti-Images
        if c.get('anti_image') and msg.attachments:
            allowed = c.get('image_allowed', [])
            for att in msg.attachments:
                if check_image(att, allowed):
                    await msg.delete()
                    return

        # 📨 Anti-Spam
        if c.get('anti_spam'):
            if await check_spam(msg, c.get('spam_max_msg', 5), c.get('spam_interval', 5)):
                await msg.delete()
                await apply_sanction(msg.author, c.get('spam_action', 'mute'), c.get('spam_duration', 10), "Spam", msg.guild)
                return

        # 📢 Anti-Mention
        if c.get('anti_mention'):
            roles = c.get('mention_protected_roles', [])
            users = c.get('mention_protected_users', [])
            if await check_mentions(msg, roles, users, c.get('mention_max_count', 3)):
                await msg.delete()
                await apply_sanction(msg.author, c.get('mention_action', 'warn'), c.get('mention_duration', 10), "Ping abusif", msg.guild)
                return

        # 🔠 Anti-Caps
        if c.get('anti_caps'):
            if check_caps(content, c.get('caps_percent', 70), c.get('caps_min_len', 10)):
                await msg.delete()
                action = c.get('caps_action', 'delete')
                if action != 'delete':
                    await apply_sanction(msg.author, action, 5, "Majuscules", msg.guild)
                return

    except Exception as e:
        print(f"[MSG ERROR] {e}\n{traceback.format_exc()}")

@bot.event
async def on_member_join(member):
    try:
        c = await cfg(member.guild.id)

        # 👶 Anti-NewAccount
        if c.get('anti_newaccount'):
            val = c.get('newaccount_value', 7)
            unit = c.get('newaccount_unit', 'jours')
            days = val * (7 if unit == 'semaines' else 30 if unit == 'mois' else 1)
            if check_new_account(member, days):
                await member.kick(reason=f"Compte trop récent")
                return

        # 👋 Welcome
        if c.get('welcome_on') and c.get('welcome_channel'):
            ch = member.guild.get_channel(c['welcome_channel'])
            if ch:
                txt = c.get('welcome_msg', 'Bienvenue {member}!').format(
                    member=member.mention, server=member.guild.name, count=member.guild.member_count)
                e = discord.Embed(title="👋 Bienvenue!", description=txt, color=C.GREEN)
                e.set_thumbnail(url=member.display_avatar.url)
                await ch.send(embed=e)
    except Exception as e:
        print(f"[JOIN ERROR] {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Configuration du bot")
async def configure_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin requis", ephemeral=True)
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.embed(), view=v, ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Membre", raison="Raison")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not i.user.guild_permissions.moderate_members:
        return await i.response.send_message("❌", ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions (guild_id, user_id, mod_id, type, reason) VALUES (?, ?, ?, ?, ?)',
            (i.guild.id, membre.id, i.user.id, 'warn', raison))
        await db.commit()
        async with db.execute("SELECT COUNT(*) FROM infractions WHERE guild_id = ? AND user_id = ? AND type = 'warn'", (i.guild.id, membre.id)) as cur:
            count = (await cur.fetchone())[0]
    e = discord.Embed(title="⚠️ Warn", color=C.YELLOW)
    e.add_field(name="Membre", value=membre.mention)
    e.add_field(name="Raison", value=raison)
    e.add_field(name="Total", value=f"{count} warn(s)")
    await i.response.send_message(embed=e)

@bot.tree.command(name="timeout", description="⏰ Timeout un membre")
@app_commands.describe(membre="Membre", duree="Durée (5m, 1h, 1d)", raison="Raison")
async def timeout_cmd(i: discord.Interaction, membre: discord.Member, duree: str, raison: str):
    if not i.user.guild_permissions.moderate_members:
        return await i.response.send_message("❌", ephemeral=True)
    match = re.match(r'^(\d+)([smhd])$', duree.lower())
    if not match:
        return await i.response.send_message("❌ Format: 5m, 1h, 1d", ephemeral=True)
    val, unit = int(match.group(1)), match.group(2)
    mult = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    await membre.timeout(timedelta(seconds=val * mult[unit]), reason=raison)
    await i.response.send_message(f"⏰ {membre.mention} timeout **{duree}** - {raison}")

if __name__ == "__main__":
    print(f"🚀 v9.9 | DB: {DB_PATH}")
    bot.run(TOKEN)
