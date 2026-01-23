# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v9.0 🌟                                 ║
# ║     Protection avancée + Tickets complets + Logs + Transcripts                ║
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
from discord.ui import View, Button, Select, Modal, TextInput
import aiosqlite
import os
import re
import json
import asyncio
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))

DB_PATH = os.getenv('DB_PATH', '/data/database.db')
if not os.path.exists('/data'):
    DB_PATH = 'database.db'

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

voice_sessions = {}
spam_tracker = {}  # Anti-spam

class C:
    BLURPLE = 0x5865F2
    GREEN = 0x57F287
    RED = 0xED4245
    YELLOW = 0xFEE75C
    PINK = 0xEB459E
    PURPLE = 0x9B59B6
    BLUE = 0x3498DB
    ORANGE = 0xE67E22
    CYAN = 0x1ABC9C
    GOLD = 0xF1C40F

def now():
    return datetime.now(timezone.utc)

def today():
    return datetime.now(timezone.utc).date()

# Liens de phishing connus
PHISHING_DOMAINS = [
    'discord-nitro.gift', 'discordgift.site', 'free-nitro.com', 'steampowered.ru',
    'dlscord.com', 'discordi.gift', 'discord-app.com', 'discordapp.co', 'discrod.com',
    'dlscord.org', 'discordc.gift', 'discord-airdrop.com', 'steamcommunity.ru',
    'steamcommunitiy.com', 'steamcomunity.com', 'store-steampowered.com',
    'discord-give.com', 'discord-free.com', 'nitro-discord.com', 'discord.gift.com',
    'discordnitro.gift', 'free-discord-nitro.com', 'claim-nitro.com', 'discord-drop.com'
]

# Patterns suspects
SUSPICIOUS_PATTERNS = [
    r'free\s*nitro', r'discord\s*nitro\s*free', r'steam\s*gift', r'free\s*steam',
    r'claim\s*your\s*gift', r'@everyone.*http', r'@here.*http', r'won\s*a?\s*nitro',
    r'airdrop.*discord', r'bitcoin.*free', r'crypto.*giveaway'
]

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY,
                log_channel INTEGER,
                mod_log_channel INTEGER,
                ticket_log_channel INTEGER,
                welcome_channel INTEGER,
                warns_kick INTEGER DEFAULT 0,
                warns_ban INTEGER DEFAULT 0,
                anti_link INTEGER DEFAULT 0,
                anti_image INTEGER DEFAULT 0,
                anti_phishing INTEGER DEFAULT 1,
                anti_spam INTEGER DEFAULT 0,
                anti_mention_spam INTEGER DEFAULT 0,
                anti_caps INTEGER DEFAULT 0,
                anti_invite INTEGER DEFAULT 0,
                anti_scam INTEGER DEFAULT 1,
                anti_raid INTEGER DEFAULT 0,
                anti_newaccount INTEGER DEFAULT 0,
                newaccount_days INTEGER DEFAULT 7,
                welcome_on INTEGER DEFAULT 0,
                welcome_msg TEXT DEFAULT 'Bienvenue {member} !'
            );
            
            CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id));
            
            CREATE TABLE IF NOT EXISTS activity (
                guild_id INTEGER, user_id INTEGER, last_message DATETIME, last_voice DATETIME,
                PRIMARY KEY (guild_id, user_id));
            
            CREATE TABLE IF NOT EXISTS ticket_config (
                guild_id INTEGER PRIMARY KEY,
                category_id INTEGER,
                staff_role_id INTEGER,
                ticket_name TEXT DEFAULT 'ticket-{user}-{number}',
                panel_title TEXT DEFAULT '🎫 Support',
                panel_description TEXT DEFAULT 'Cliquez pour créer un ticket',
                questions TEXT DEFAULT '[]'
            );
            
            CREATE TABLE IF NOT EXISTS ticket_immune_roles (
                guild_id INTEGER,
                role_id INTEGER,
                PRIMARY KEY (guild_id, role_id)
            );
            
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                user_id INTEGER,
                claimed_by INTEGER,
                status TEXT DEFAULT 'open',
                answers TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME,
                closed_reason TEXT
            );
            
            CREATE TABLE IF NOT EXISTS message_stats (
                guild_id INTEGER, user_id INTEGER, channel_id INTEGER, date TEXT, count INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, channel_id, date));
            
            CREATE TABLE IF NOT EXISTS voice_stats (
                guild_id INTEGER, user_id INTEGER, channel_id INTEGER, date TEXT, seconds INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, channel_id, date));
            
            CREATE TABLE IF NOT EXISTS infractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                mod_id INTEGER,
                type TEXT,
                reason TEXT,
                duration INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS role_permissions (
                guild_id INTEGER,
                role_id INTEGER,
                permission TEXT,
                PRIMARY KEY (guild_id, role_id, permission)
            );
            
            CREATE INDEX IF NOT EXISTS idx_msg_stats ON message_stats(guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_voice_stats ON voice_stats(guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_infractions ON infractions(guild_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_tickets ON tickets(guild_id, channel_id);
        ''')
        await db.commit()
    print(f"✅ DB OK ({DB_PATH})")

async def cleanup_member_data(gid, uid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM message_stats WHERE guild_id=? AND user_id=?', (gid, uid))
        await db.execute('DELETE FROM voice_stats WHERE guild_id=? AND user_id=?', (gid, uid))
        await db.execute('DELETE FROM activity WHERE guild_id=? AND user_id=?', (gid, uid))
        await db.execute('DELETE FROM infractions WHERE guild_id=? AND user_id=?', (gid, uid))
        await db.commit()

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
        return dict(r) if r else {}

async def scfg(gid, **kw):
    async with aiosqlite.connect(DB_PATH) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE config SET {k}=? WHERE guild_id=?', (v, gid))
        await db.commit()

async def gtcfg(gid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM ticket_config WHERE guild_id=?', (gid,))
        r = await cur.fetchone()
        if r: return dict(r)
        await db.execute('INSERT OR IGNORE INTO ticket_config (guild_id) VALUES (?)', (gid,))
        await db.commit()
        return {'guild_id': gid, 'category_id': None, 'staff_role_id': None,
                'ticket_name': 'ticket-{user}-{number}', 'panel_title': '🎫 Support',
                'panel_description': 'Cliquez pour créer un ticket', 'questions': '[]'}

async def stcfg(gid, **kw):
    async with aiosqlite.connect(DB_PATH) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE ticket_config SET {k}=? WHERE guild_id=?', (v, gid))
        await db.commit()

async def has_permission(member, permission):
    if member.guild_permissions.administrator or member.id == member.guild.owner_id:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        for role in member.roles:
            cur = await db.execute(
                'SELECT 1 FROM role_permissions WHERE guild_id=? AND role_id=? AND permission=?',
                (member.guild.id, role.id, permission)
            )
            if await cur.fetchone():
                return True
    return False

async def get_role_permissions(gid, rid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT permission FROM role_permissions WHERE guild_id=? AND role_id=?', (gid, rid))
        return [r[0] for r in await cur.fetchall()]

async def set_role_permission(gid, rid, permission, enabled):
    async with aiosqlite.connect(DB_PATH) as db:
        if enabled:
            await db.execute('INSERT OR IGNORE INTO role_permissions VALUES (?,?,?)', (gid, rid, permission))
        else:
            await db.execute('DELETE FROM role_permissions WHERE guild_id=? AND role_id=? AND permission=?', (gid, rid, permission))
        await db.commit()

async def add_infraction(gid, uid, mod_id, inf_type, reason, duration=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO infractions (guild_id, user_id, mod_id, type, reason, duration) VALUES (?,?,?,?,?,?)',
            (gid, uid, mod_id, inf_type, reason, duration)
        )
        await db.commit()
        cur = await db.execute('SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=?', (gid, uid))
        return (await cur.fetchone())[0]

async def get_infractions(gid, uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            'SELECT * FROM infractions WHERE guild_id=? AND user_id=? ORDER BY created_at DESC',
            (gid, uid)
        )
        return [dict(r) for r in await cur.fetchall()]

async def get_warn_count(gid, uid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type='warn'", (gid, uid))
        return (await cur.fetchone())[0]

async def is_immune(m):
    if m.id == m.guild.owner_id: return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,))
        ids = [r[0] for r in await cur.fetchall()]
    return any(r.id in ids for r in m.roles)

async def track_message(gid, uid, cid):
    date_str = today().strftime('%Y-%m-%d')
    now_str = now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO activity (guild_id, user_id) VALUES (?,?)', (gid, uid))
        await db.execute('UPDATE activity SET last_message=? WHERE guild_id=? AND user_id=?', (now_str, gid, uid))
        await db.execute('INSERT OR IGNORE INTO message_stats (guild_id, user_id, channel_id, date, count) VALUES (?,?,?,?,0)', (gid, uid, cid, date_str))
        await db.execute('UPDATE message_stats SET count = count + 1 WHERE guild_id=? AND user_id=? AND channel_id=? AND date=?', (gid, uid, cid, date_str))
        await db.commit()

async def track_voice_start(gid, uid, cid):
    voice_sessions[(gid, uid)] = {'start': now(), 'channel_id': cid}
    now_str = now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO activity (guild_id, user_id) VALUES (?,?)', (gid, uid))
        await db.execute('UPDATE activity SET last_voice=? WHERE guild_id=? AND user_id=?', (now_str, gid, uid))
        await db.commit()

async def track_voice_end(gid, uid):
    key = (gid, uid)
    if key not in voice_sessions:
        return
    session = voice_sessions.pop(key)
    duration = (now() - session['start']).total_seconds()
    cid = session['channel_id']
    date_str = today().strftime('%Y-%m-%d')
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO voice_stats (guild_id, user_id, channel_id, date, seconds) VALUES (?,?,?,?,0)', (gid, uid, cid, date_str))
        await db.execute('UPDATE voice_stats SET seconds = seconds + ? WHERE guild_id=? AND user_id=? AND channel_id=? AND date=?', (int(duration), gid, uid, cid, date_str))
        await db.commit()

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 STATS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_advanced_stats(gid, uid, period='week'):
    td = today()
    if period == 'day':
        start_date = td
        days = 1
    elif period == 'week':
        start_date = td - timedelta(days=6)
        days = 7
    else:
        start_date = td - timedelta(days=29)
        days = 30
    
    stats = {
        'messages': 0, 'voice_seconds': 0,
        'msg_by_day': [], 'voice_by_day': [],
        'top_text_channel': None, 'top_voice_channel': None,
        'msg_by_channel': {}, 'voice_by_channel': {}
    }
    
    async with aiosqlite.connect(DB_PATH) as db:
        for i in range(days):
            d = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            cur = await db.execute('SELECT SUM(count) FROM message_stats WHERE guild_id=? AND user_id=? AND date=?', (gid, uid, d))
            r = await cur.fetchone()
            count = r[0] or 0
            stats['msg_by_day'].append(count)
            stats['messages'] += count
        
        for i in range(days):
            d = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            cur = await db.execute('SELECT SUM(seconds) FROM voice_stats WHERE guild_id=? AND user_id=? AND date=?', (gid, uid, d))
            r = await cur.fetchone()
            secs = r[0] or 0
            stats['voice_by_day'].append(secs)
            stats['voice_seconds'] += secs
        
        cur = await db.execute('''
            SELECT channel_id, SUM(count) as total FROM message_stats 
            WHERE guild_id=? AND user_id=? AND date>=?
            GROUP BY channel_id ORDER BY total DESC LIMIT 5
        ''', (gid, uid, start_date.strftime('%Y-%m-%d')))
        rows = await cur.fetchall()
        if rows:
            stats['top_text_channel'] = rows[0][0]
            stats['msg_by_channel'] = {r[0]: r[1] for r in rows}
        
        cur = await db.execute('''
            SELECT channel_id, SUM(seconds) as total FROM voice_stats 
            WHERE guild_id=? AND user_id=? AND date>=?
            GROUP BY channel_id ORDER BY total DESC LIMIT 5
        ''', (gid, uid, start_date.strftime('%Y-%m-%d')))
        rows = await cur.fetchall()
        if rows:
            stats['top_voice_channel'] = rows[0][0]
            stats['voice_by_channel'] = {r[0]: r[1] for r in rows}
    
    return stats

def format_time(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h, remainder = divmod(int(seconds), 3600)
        m = remainder // 60
        return f"{h}h {m}m"

def format_duration(seconds):
    if seconds < 60:
        return f"{seconds} seconde(s)"
    elif seconds < 3600:
        return f"{seconds // 60} minute(s)"
    elif seconds < 86400:
        return f"{seconds // 3600} heure(s)"
    else:
        return f"{seconds // 86400} jour(s)"

def parse_duration(duration_str):
    match = re.match(r'^(\d+)([smhdw])$', duration_str.lower().strip())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    seconds = value * multipliers[unit]
    max_seconds = 604800 * 4
    return min(seconds, max_seconds)

def get_day_labels(days):
    td = today()
    labels = []
    day_names = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
    for i in range(days):
        d = td - timedelta(days=days - 1 - i)
        labels.append(day_names[d.weekday()])
    return labels

def get_activity_rank(messages, voice_minutes):
    score = messages + voice_minutes
    if score >= 1000:
        return "🏆 LÉGENDE", "Tu es une légende !", C.GOLD
    elif score >= 500:
        return "💎 DIAMANT", "Exceptionnel !", C.CYAN
    elif score >= 200:
        return "🥇 OR", "Très actif !", C.GOLD
    elif score >= 100:
        return "🥈 ARGENT", "Belle activité !", C.BLUE
    elif score >= 50:
        return "🥉 BRONZE", "Bonne activité !", C.ORANGE
    elif score >= 20:
        return "⭐ ACTIF", "Continue !", C.GREEN
    elif score >= 5:
        return "📊 RÉGULIER", "Présent", C.PURPLE
    else:
        return "👻 FANTÔME", "On te voit peu...", C.RED

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def check_phishing(content):
    """Vérifie si le message contient des liens de phishing"""
    content_lower = content.lower()
    for domain in PHISHING_DOMAINS:
        if domain in content_lower:
            return True
    return False

def check_scam_patterns(content):
    """Vérifie les patterns de scam"""
    content_lower = content.lower()
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, content_lower, re.IGNORECASE):
            return True
    return False

def check_discord_invite(content):
    """Vérifie les invitations Discord"""
    invite_pattern = r'(discord\.gg|discord\.com/invite|discordapp\.com/invite)/[a-zA-Z0-9]+'
    return bool(re.search(invite_pattern, content))

def check_mass_mentions(message):
    """Vérifie le spam de mentions"""
    return len(message.mentions) > 5 or message.mention_everyone

def check_caps(content):
    """Vérifie l'abus de majuscules (>70% caps et >10 caractères)"""
    if len(content) < 10:
        return False
    caps = sum(1 for c in content if c.isupper())
    return caps / len(content) > 0.7

async def check_spam(message):
    """Anti-spam : détecte les messages répétitifs"""
    key = (message.guild.id, message.author.id)
    current_time = now()
    
    if key not in spam_tracker:
        spam_tracker[key] = {'messages': [], 'last_content': ''}
    
    tracker = spam_tracker[key]
    
    # Nettoyer les vieux messages (>10 secondes)
    tracker['messages'] = [t for t in tracker['messages'] if (current_time - t).total_seconds() < 10]
    
    # Ajouter le nouveau message
    tracker['messages'].append(current_time)
    
    # Spam si >5 messages en 10 secondes ou même message répété
    if len(tracker['messages']) > 5:
        return True
    
    if tracker['last_content'] == message.content and len(message.content) > 5:
        return True
    
    tracker['last_content'] = message.content
    return False

def check_new_account(member, days_required):
    """Vérifie si le compte est trop récent"""
    account_age = (now() - member.created_at.replace(tzinfo=timezone.utc)).days
    return account_age < days_required

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKET FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_ticket_transcript(channel, limit=100):
    """Génère un transcript du ticket"""
    messages = []
    try:
        async for msg in channel.history(limit=limit, oldest_first=True):
            timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
            content = msg.content or "[Embed/Fichier]"
            messages.append(f"[{timestamp}] {msg.author.display_name}: {content}")
    except:
        pass
    return "\n".join(messages) if messages else "Aucun message"

async def close_ticket(channel, reason, closed_by=None):
    """Ferme un ticket et envoie les logs"""
    guild = channel.guild
    c = await gcfg(guild.id)
    
    # Récupérer les infos du ticket
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM tickets WHERE channel_id=?', (channel.id,))
        ticket = await cur.fetchone()
        if not ticket:
            return
        ticket = dict(ticket)
    
    # Générer le transcript
    transcript = await get_ticket_transcript(channel)
    
    # Mettre à jour le ticket
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'UPDATE tickets SET status="closed", closed_at=?, closed_reason=? WHERE channel_id=?',
            (now().isoformat(), reason, channel.id)
        )
        await db.commit()
    
    # Envoyer les logs
    if c.get('ticket_log_channel'):
        log_channel = guild.get_channel(c['ticket_log_channel'])
        if log_channel:
            user = guild.get_member(ticket['user_id'])
            claimer = guild.get_member(ticket['claimed_by']) if ticket['claimed_by'] else None
            
            e = discord.Embed(title="🎫 Ticket Fermé", color=C.RED)
            e.add_field(name="📝 ID Ticket", value=f"#{ticket['id']}", inline=True)
            e.add_field(name="👤 Créé par", value=user.mention if user else f"ID: {ticket['user_id']}", inline=True)
            e.add_field(name="🙋 Pris par", value=claimer.mention if claimer else "Personne", inline=True)
            e.add_field(name="📅 Ouvert le", value=ticket['created_at'][:16] if ticket['created_at'] else "?", inline=True)
            e.add_field(name="📅 Fermé le", value=now().strftime('%d/%m/%Y %H:%M'), inline=True)
            e.add_field(name="❓ Raison", value=reason, inline=True)
            
            # Transcript (tronqué si trop long)
            if len(transcript) > 1000:
                transcript = transcript[:1000] + "\n... [Tronqué]"
            e.add_field(name="📜 Transcript", value=f"```\n{transcript}\n```", inline=False)
            
            e.timestamp = now()
            await log_channel.send(embed=e)
    
    # Supprimer le channel
    try:
        await channel.delete()
    except:
        pass

async def get_ticket_immune_roles(gid):
    """Récupère les rôles immunisés pour les tickets"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT role_id FROM ticket_immune_roles WHERE guild_id=?', (gid,))
        return [r[0] for r in await cur.fetchall()]

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class MainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def interaction_check(self, i):
        if i.user.id != self.u.id:
            await i.response.send_message("❌ Pas ton panneau", ephemeral=True)
            return False
        return True
    
    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"```yml\n👥 Membres : {self.g.member_count}\n```"
        if self.g.icon: e.set_thumbnail(url=self.g.icon.url)
        e.set_footer(text=f"👤 {self.u.display_name}", icon_url=self.u.display_avatar.url)
        return e
    
    @discord.ui.button(label="Permissions", emoji="🔐", style=discord.ButtonStyle.danger, row=0)
    async def b0(self, i, b):
        await i.response.defer()
        v = PermPanel(self.u, self.g)
        await i.edit_original_response(embed=v.embed(), view=v)
    
    @discord.ui.button(label="Sanctions", emoji="⚖️", style=discord.ButtonStyle.danger, row=0)
    async def b1(self, i, b):
        await i.response.defer()
        v = SanctPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def b2(self, i, b):
        await i.response.defer()
        v = LogsPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=1)
    async def b3(self, i, b):
        await i.response.defer()
        v = ProtPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def b4(self, i, b):
        await i.response.defer()
        v = ImmunePanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def b5(self, i, b):
        await i.response.defer()
        v = WelcPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Activité", emoji="📊", style=discord.ButtonStyle.secondary, row=2)
    async def b6(self, i, b):
        await i.response.defer()
        v = ActPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.primary, row=2)
    async def b7(self, i, b):
        await i.response.defer()
        v = TicketPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def b8(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔐 PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════════

class PermPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        roles = [r for r in g.roles[1:] if not r.is_bot_managed() and not r.is_premium_subscriber()][:25]
        if roles:
            options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
            sel = Select(placeholder="🔐 Sélectionner un rôle...", options=options)
            sel.callback = self.role_selected
            self.add_item(sel)
    
    async def role_selected(self, i):
        rid = int(i.data['values'][0])
        role = self.g.get_role(rid)
        v = RolePermEditor(self.u, self.g, role)
        await v.setup()
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    def embed(self):
        e = discord.Embed(title="🔐 Gestion des Permissions", color=C.RED)
        e.description = """```yml
📋 Permissions disponibles
──────────────────────────────────────────
⚠️ warn        : /warn - Avertir
⏰ timeout     : /timeout - Exclure temp.
📜 infractions : /infractions - Voir logs
──────────────────────────────────────────
```

👇 Sélectionnez un rôle à configurer"""
        return e
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class RolePermEditor(View):
    def __init__(self, u, g, role):
        super().__init__(timeout=300)
        self.u, self.g, self.role = u, g, role
        self.perms = []
    
    async def setup(self):
        self.perms = await get_role_permissions(self.g.id, self.role.id)
    
    async def embed(self):
        def s(p): return "✅" if p in self.perms else "❌"
        e = discord.Embed(title=f"🔐 Permissions de @{self.role.name}", color=self.role.color)
        e.description = f"```yml\n⚠️ warn        : {s('warn')}\n⏰ timeout     : {s('timeout')}\n📜 infractions : {s('infractions')}\n```\n**Cliquez pour activer/désactiver**"
        return e
    
    @discord.ui.button(label="Warn", emoji="⚠️", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_warn(self, i, b):
        enabled = 'warn' not in self.perms
        await set_role_permission(self.g.id, self.role.id, 'warn', enabled)
        if enabled: self.perms.append('warn')
        else: self.perms.remove('warn')
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Timeout", emoji="⏰", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_timeout(self, i, b):
        enabled = 'timeout' not in self.perms
        await set_role_permission(self.g.id, self.role.id, 'timeout', enabled)
        if enabled: self.perms.append('timeout')
        else: self.perms.remove('timeout')
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Infractions", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_infractions(self, i, b):
        enabled = 'infractions' not in self.perms
        await set_role_permission(self.g.id, self.role.id, 'infractions', enabled)
        if enabled: self.perms.append('infractions')
        else: self.perms.remove('infractions')
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = PermPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚖️ SANCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class SanctPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        c = await gcfg(self.g.id)
        e = discord.Embed(title="⚖️ Sanctions Automatiques", color=C.PINK)
        e.description = f"```yml\n👢 Kick après : {f'{c.get(\"warns_kick\", 0)} warns' if c.get('warns_kick') else 'Désactivé'}\n🔨 Ban après  : {f'{c.get(\"warns_ban\", 0)} warns' if c.get('warns_ban') else 'Désactivé'}\n```"
        return e
    
    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.primary)
    async def config(self, i, b):
        await i.response.send_modal(SanctConfigM(self.g))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class SanctConfigM(Modal, title="⚖️ Sanctions Auto"):
    wk = TextInput(label="Warns pour Kick (0=off)", required=False, max_length=2)
    wb = TextInput(label="Warns pour Ban (0=off)", required=False, max_length=2)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        k = int(self.wk.value) if self.wk.value.isdigit() else 0
        b = int(self.wb.value) if self.wb.value.isdigit() else 0
        await scfg(self.g.id, warns_kick=k, warns_ban=b)
        await i.response.send_message(f"✅ Kick: {k} warns | Ban: {b} warns", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📜 LOGS
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        channels = [c for c in g.text_channels][:25]
        if channels:
            options = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
            sel1 = Select(placeholder="📝 Logs généraux...", options=options, row=1)
            sel1.callback = self.log_selected
            self.add_item(sel1)
            sel2 = Select(placeholder="⚔️ Logs modération...", options=options.copy(), row=2)
            sel2.callback = self.mod_log_selected
            self.add_item(sel2)
            sel3 = Select(placeholder="🎫 Logs tickets...", options=options.copy(), row=3)
            sel3.callback = self.ticket_log_selected
            self.add_item(sel3)
    
    async def log_selected(self, i):
        cid = int(i.data['values'][0])
        await scfg(self.g.id, log_channel=cid)
        ch = self.g.get_channel(cid)
        await i.response.send_message(f"✅ Logs généraux → **#{ch.name}**", ephemeral=True)
    
    async def mod_log_selected(self, i):
        cid = int(i.data['values'][0])
        await scfg(self.g.id, mod_log_channel=cid)
        ch = self.g.get_channel(cid)
        await i.response.send_message(f"✅ Logs modération → **#{ch.name}**", ephemeral=True)
    
    async def ticket_log_selected(self, i):
        cid = int(i.data['values'][0])
        await scfg(self.g.id, ticket_log_channel=cid)
        ch = self.g.get_channel(cid)
        await i.response.send_message(f"✅ Logs tickets → **#{ch.name}**", ephemeral=True)
    
    async def embed(self):
        c = await gcfg(self.g.id)
        lc = self.g.get_channel(c.get('log_channel'))
        mc = self.g.get_channel(c.get('mod_log_channel'))
        tc = self.g.get_channel(c.get('ticket_log_channel'))
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        e.description = f"```yml\n📝 Généraux   : {f'#{lc.name}' if lc else '❌'}\n⚔️ Modération : {f'#{mc.name}' if mc else '❌'}\n🎫 Tickets    : {f'#{tc.name}' if tc else '❌'}\n```"
        return e
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        c = await gcfg(self.g.id)
        def s(v): return "✅" if v else "❌"
        e = discord.Embed(title="🛡️ Protection Avancée", color=C.BLUE)
        e.description = f"""```yml
🔗 LIENS & INVITATIONS
──────────────────────────────────────────
🔗 Anti-Liens       : {s(c.get('anti_link', 0))}
   Supprime tous les liens

🎟️ Anti-Invitations : {s(c.get('anti_invite', 0))}
   Bloque les invites Discord

🖼️ Anti-Images      : {s(c.get('anti_image', 0))}
   Supprime images/GIFs

🎣 PHISHING & SCAM
──────────────────────────────────────────
🎣 Anti-Phishing    : {s(c.get('anti_phishing', 1))}
   Bloque {len(PHISHING_DOMAINS)} domaines connus

🚨 Anti-Scam        : {s(c.get('anti_scam', 1))}
   Détecte patterns d'arnaque

📨 SPAM & ABUS
──────────────────────────────────────────
📨 Anti-Spam        : {s(c.get('anti_spam', 0))}
   Limite messages répétitifs

📢 Anti-Mention     : {s(c.get('anti_mention_spam', 0))}
   Bloque spam de @mentions

🔠 Anti-Majuscules  : {s(c.get('anti_caps', 0))}
   Limite abus de CAPS

🛡️ PROTECTION RAID
──────────────────────────────────────────
⚔️ Anti-Raid        : {s(c.get('anti_raid', 0))}
   Détecte les raids

👶 Anti-NewAccount  : {s(c.get('anti_newaccount', 0))}
   Bloque comptes < {c.get('newaccount_days', 7)} jours
```"""
        return e
    
    @discord.ui.button(label="Anti-Liens", emoji="🔗", style=discord.ButtonStyle.primary, row=0)
    async def al(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_link=not c.get('anti_link', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-Invite", emoji="🎟️", style=discord.ButtonStyle.primary, row=0)
    async def ainv(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_invite=not c.get('anti_invite', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-Images", emoji="🖼️", style=discord.ButtonStyle.primary, row=0)
    async def ai(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_image=not c.get('anti_image', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-Phishing", emoji="🎣", style=discord.ButtonStyle.danger, row=1)
    async def ap(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_phishing=not c.get('anti_phishing', 1))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-Scam", emoji="🚨", style=discord.ButtonStyle.danger, row=1)
    async def asc(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_scam=not c.get('anti_scam', 1))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-Spam", emoji="📨", style=discord.ButtonStyle.secondary, row=2)
    async def asp(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_spam=not c.get('anti_spam', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-Mention", emoji="📢", style=discord.ButtonStyle.secondary, row=2)
    async def am(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_mention_spam=not c.get('anti_mention_spam', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-Caps", emoji="🔠", style=discord.ButtonStyle.secondary, row=2)
    async def ac(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_caps=not c.get('anti_caps', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-Raid", emoji="⚔️", style=discord.ButtonStyle.danger, row=3)
    async def ar(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_raid=not c.get('anti_raid', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Anti-NewAccount", emoji="👶", style=discord.ButtonStyle.danger, row=3)
    async def ana(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_newaccount=not c.get('anti_newaccount', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👑 IMMUNITÉS
# ═══════════════════════════════════════════════════════════════════════════════

class ImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        roles = [r for r in g.roles[1:] if not r.is_bot_managed() and not r.is_premium_subscriber()][:25]
        if roles:
            options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
            sel = Select(placeholder="👑 Ajouter un rôle immunisé...", options=options, row=1)
            sel.callback = self.add_immune
            self.add_item(sel)
    
    async def add_immune(self, i):
        rid = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES (?,?)', (self.g.id, rid))
            await db.commit()
        role = self.g.get_role(rid)
        await i.response.send_message(f"✅ **@{role.name}** immunisé", ephemeral=True)
    
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,))
            ir = [self.g.get_role(r[0]) for r in await cur.fetchall() if self.g.get_role(r[0])]
        e = discord.Embed(title="👑 Rôles Immunisés", color=C.GOLD)
        e.description = f"```yml\nNe peuvent PAS être sanctionnés:\n{', '.join([r.name for r in ir]) or 'Aucun'}\n```"
        return e
    
    @discord.ui.button(label="Retirer", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def rem(self, i, b):
        v = RemImmunePanel(self.u, self.g)
        await v.setup()
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class RemImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u, self.g = u, g
    
    async def setup(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,))
            roles = [self.g.get_role(r[0]) for r in await cur.fetchall() if self.g.get_role(r[0])]
        if roles:
            options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles[:25]]
            sel = Select(placeholder="🗑️ Retirer...", options=options)
            sel.callback = self.remove
            self.add_item(sel)
    
    async def remove(self, i):
        rid = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM immune_roles WHERE guild_id=? AND role_id=?', (self.g.id, rid))
            await db.commit()
        await i.response.send_message("✅ Retiré", ephemeral=True)
    
    async def embed(self):
        return discord.Embed(title="🗑️ Retirer immunité", color=C.RED)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        await i.response.defer()
        v = ImmunePanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👋 BIENVENUE
# ═══════════════════════════════════════════════════════════════════════════════

class WelcPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        channels = [c for c in g.text_channels][:25]
        if channels:
            options = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
            sel = Select(placeholder="👋 Salon bienvenue...", options=options, row=2)
            sel.callback = self.channel_selected
            self.add_item(sel)
    
    async def channel_selected(self, i):
        cid = int(i.data['values'][0])
        await scfg(self.g.id, welcome_channel=cid)
        ch = self.g.get_channel(cid)
        await i.response.send_message(f"✅ Salon → **#{ch.name}**", ephemeral=True)
    
    async def embed(self):
        c = await gcfg(self.g.id)
        ch = self.g.get_channel(c.get('welcome_channel'))
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"```yml\nÉtat  : {'✅' if c.get('welcome_on') else '❌'}\nSalon : {f'#{ch.name}' if ch else '❌'}\nMessage: {c.get('welcome_msg', '')[:50]}...\n```"
        return e
    
    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def tog(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, welcome_on=not c.get('welcome_on', 0))
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Message", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def msg(self, i, b):
        await i.response.send_modal(WelcMsgM(self.g))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class WelcMsgM(Modal, title="✏️ Message"):
    msg = TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=500)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        await scfg(self.g.id, welcome_msg=self.msg.value)
        await i.response.send_message("✅", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 ACTIVITÉ
# ═══════════════════════════════════════════════════════════════════════════════

class ActPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        self.i7, self.i30 = [], []
        self.total_humans = 0
    
    async def embed(self):
        n = now()
        d7, d30 = n - timedelta(days=7), n - timedelta(days=30)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM activity WHERE guild_id=?', (self.g.id,))
            act = {r['user_id']: dict(r) for r in await cur.fetchall()}
        
        self.i7, self.i30 = [], []
        self.total_humans = 0
        
        for m in self.g.members:
            if m.bot: continue
            self.total_humans += 1
            a = act.get(m.id)
            if not a or (not a['last_message'] and not a['last_voice']):
                self.i7.append(m); self.i30.append(m)
                continue
            lm = lv = None
            if a['last_message']:
                try:
                    lm = datetime.fromisoformat(a['last_message'].replace('Z', '+00:00'))
                    if lm.tzinfo is None: lm = lm.replace(tzinfo=timezone.utc)
                except: pass
            if a['last_voice']:
                try:
                    lv = datetime.fromisoformat(a['last_voice'].replace('Z', '+00:00'))
                    if lv.tzinfo is None: lv = lv.replace(tzinfo=timezone.utc)
                except: pass
            activities = [x for x in [lm, lv] if x]
            last = max(activities) if activities else None
            if not last:
                self.i7.append(m); self.i30.append(m)
            elif last < d30:
                self.i7.append(m); self.i30.append(m)
            elif last < d7:
                self.i7.append(m)
        
        e = discord.Embed(title="📊 Activité", color=C.ORANGE)
        e.description = f"```yml\n👥 Humains: {self.total_humans}\n⚠️ Inactifs 7j : {len(self.i7)}\n🔴 Inactifs 30j: {len(self.i30)}\n```"
        return e
    
    @discord.ui.button(label="Inactifs 7j", emoji="⚠️", style=discord.ButtonStyle.primary, row=0)
    async def b7(self, i, b):
        v = InactList(self.u, self.g, 7, self.i7)
        await i.response.edit_message(embed=v.embed(), view=v)
    
    @discord.ui.button(label="Inactifs 30j", emoji="🔴", style=discord.ButtonStyle.danger, row=0)
    async def b30(self, i, b):
        v = InactList(self.u, self.g, 30, self.i30)
        await i.response.edit_message(embed=v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class InactList(View):
    def __init__(self, u, g, d, m):
        super().__init__(timeout=900)
        self.u, self.g, self.d = u, g, d
        self.all_members = m
        self.page = 0
        self.per_page = 20
    
    def embed(self):
        total = len(self.all_members)
        max_pages = max(1, (total + self.per_page - 1) // self.per_page)
        start = self.page * self.per_page
        end = start + self.per_page
        page_members = self.all_members[start:end]
        lst = "\n".join([f"• {x.display_name}" for x in page_members])
        e = discord.Embed(title=f"{'⚠️' if self.d==7 else '🔴'} Inactifs {self.d}j", color=C.ORANGE if self.d==7 else C.RED)
        e.description = f"**{total} membres**\n```\n{lst or '🎉 Aucun'}\n```"
        e.set_footer(text=f"Page {self.page + 1}/{max_pages}")
        return e
    
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=0)
    async def prev(self, i, b):
        if self.page > 0: self.page -= 1
        await i.response.edit_message(embed=self.embed(), view=self)
    
    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next(self, i, b):
        max_pages = max(1, (len(self.all_members) + self.per_page - 1) // self.per_page)
        if self.page < max_pages - 1: self.page += 1
        await i.response.edit_message(embed=self.embed(), view=self)
    
    @discord.ui.button(label="📢 Mentionner", style=discord.ButtonStyle.primary, row=1)
    async def ment(self, i, b):
        if not self.all_members: return await i.response.send_message("❌", ephemeral=True)
        members = self.all_members[:40]
        await i.response.send_message(f"📢 {' '.join([x.mention for x in members])}")
    
    @discord.ui.button(label="👢 Expulser", style=discord.ButtonStyle.danger, row=1)
    async def kick(self, i, b):
        if not self.all_members: return await i.response.send_message("❌", ephemeral=True)
        v = ConfKick(self.u, self.g, self.all_members, self.d)
        await i.response.edit_message(embed=discord.Embed(title="⚠️ Confirmer?", description=f"Expulser **{len(self.all_members)}** membres?", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        await i.response.defer()
        v = ActPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)

class ConfKick(View):
    def __init__(self, u, g, m, d):
        super().__init__(timeout=60)
        self.u, self.g, self.all_members, self.d = u, g, m, d
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def yes(self, i, b):
        await i.response.defer()
        ok, fail = 0, 0
        for m in self.all_members:
            try: await m.kick(reason=f"Inactif {self.d}j"); ok += 1
            except: fail += 1
        await i.edit_original_response(embed=discord.Embed(title="👢 Terminé", description=f"✅ {ok} | ❌ {fail}", color=C.GREEN), view=None)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def no(self, i, b):
        await i.response.defer()
        v = ActPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

class TicketPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        categories = [c for c in g.categories][:25]
        if categories:
            options = [discord.SelectOption(label=c.name[:25], value=str(c.id), emoji="📁") for c in categories]
            sel = Select(placeholder="📁 Catégorie...", options=options, row=2)
            sel.callback = self.cat_selected
            self.add_item(sel)
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id), emoji="👮") for r in roles]
            sel2 = Select(placeholder="👮 Rôle staff...", options=options, row=3)
            sel2.callback = self.role_selected
            self.add_item(sel2)
    
    async def cat_selected(self, i):
        cid = int(i.data['values'][0])
        await stcfg(self.g.id, category_id=cid)
        cat = self.g.get_channel(cid)
        await i.response.send_message(f"✅ Catégorie: **{cat.name}**", ephemeral=True)
    
    async def role_selected(self, i):
        rid = int(i.data['values'][0])
        await stcfg(self.g.id, staff_role_id=rid)
        role = self.g.get_role(rid)
        await i.response.send_message(f"✅ Staff: **@{role.name}**", ephemeral=True)
    
    async def embed(self):
        tc = await gtcfg(self.g.id)
        cat = self.g.get_channel(tc['category_id'])
        rl = self.g.get_role(tc['staff_role_id'])
        qs = json.loads(tc['questions']) if tc['questions'] else []
        
        # Récupérer rôles immunisés tickets
        immune_roles = await get_ticket_immune_roles(self.g.id)
        immune_names = [self.g.get_role(r).name for r in immune_roles if self.g.get_role(r)]
        
        e = discord.Embed(title="🎫 Tickets", color=C.PURPLE)
        e.description = f"""```yml
📁 Catégorie: {cat.name if cat else '❌'}
👮 Staff: {'@'+rl.name if rl else '❌'}
📝 Format: {tc['ticket_name']}

👁️ Rôles immunisés (voient tous tickets):
{', '.join(immune_names) or 'Aucun'}

❓ Questions ({len(qs)}/5):
{chr(10).join([f'{i+1}. {q["title"] if isinstance(q, dict) else q}' for i,q in enumerate(qs)]) or 'Aucune'}
```"""
        return e
    
    @discord.ui.button(label="Questions", emoji="❓", style=discord.ButtonStyle.secondary, row=0)
    async def questions(self, i, b):
        v = QuestionsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Immunités", emoji="👁️", style=discord.ButtonStyle.secondary, row=0)
    async def immunities(self, i, b):
        v = TicketImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📤 Déployer", emoji="📤", style=discord.ButtonStyle.success, row=1)
    async def deploy(self, i, b):
        v = DeployPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class TicketImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
            sel = Select(placeholder="👁️ Ajouter rôle immunisé...", options=options, row=1)
            sel.callback = self.add_immune
            self.add_item(sel)
    
    async def add_immune(self, i):
        rid = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO ticket_immune_roles VALUES (?,?)', (self.g.id, rid))
            await db.commit()
        role = self.g.get_role(rid)
        await i.response.send_message(f"✅ **@{role.name}** verra tous les tickets", ephemeral=True)
    
    async def embed(self):
        immune_roles = await get_ticket_immune_roles(self.g.id)
        names = [self.g.get_role(r).name for r in immune_roles if self.g.get_role(r)]
        e = discord.Embed(title="👁️ Immunités Tickets", color=C.PURPLE)
        e.description = f"```yml\nRôles qui voient TOUS les tickets:\n{', '.join(names) or 'Aucun'}\n```"
        return e
    
    @discord.ui.button(label="Retirer", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def rem(self, i, b):
        v = RemTicketImmunePanel(self.u, self.g)
        await v.setup()
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        await i.response.defer()
        v = TicketPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)

class RemTicketImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u, self.g = u, g
    
    async def setup(self):
        immune_roles = await get_ticket_immune_roles(self.g.id)
        roles = [self.g.get_role(r) for r in immune_roles if self.g.get_role(r)]
        if roles:
            options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles[:25]]
            sel = Select(placeholder="🗑️ Retirer...", options=options)
            sel.callback = self.remove
            self.add_item(sel)
    
    async def remove(self, i):
        rid = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM ticket_immune_roles WHERE guild_id=? AND role_id=?', (self.g.id, rid))
            await db.commit()
        await i.response.send_message("✅ Retiré", ephemeral=True)
    
    async def embed(self):
        return discord.Embed(title="🗑️ Retirer immunité ticket", color=C.RED)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = TicketImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class QuestionsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u, self.g = u, g
    
    async def embed(self):
        tc = await gtcfg(self.g.id)
        qs = json.loads(tc['questions']) if tc['questions'] else []
        q_list = ""
        for i, q in enumerate(qs):
            if isinstance(q, dict):
                q_list += f"{i+1}. {q['title']}\n   └─ {q.get('description', '')[:30]}...\n"
            else:
                q_list += f"{i+1}. {q}\n"
        e = discord.Embed(title="❓ Questions du ticket", color=C.PURPLE)
        e.description = f"```yml\n{q_list or 'Aucune question'}\n```\nMax: 5 questions"
        return e
    
    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success)
    async def add(self, i, b):
        tc = await gtcfg(self.g.id)
        qs = json.loads(tc['questions']) if tc['questions'] else []
        if len(qs) >= 5: return await i.response.send_message("❌ Max 5", ephemeral=True)
        await i.response.send_modal(AddQuestionM(self.g))
    
    @discord.ui.button(label="🗑️ Clear", style=discord.ButtonStyle.danger)
    async def clear(self, i, b):
        await stcfg(self.g.id, questions='[]')
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        await i.response.defer()
        v = TicketPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)

class AddQuestionM(Modal, title="➕ Ajouter une question"):
    q_title = TextInput(label="Titre de la question", placeholder="Ex: Raison du contact", max_length=45)
    q_desc = TextInput(label="Description (optionnel)", placeholder="Ex: Décrivez votre problème en détail", required=False, style=discord.TextStyle.paragraph, max_length=100)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        tc = await gtcfg(self.g.id)
        qs = json.loads(tc['questions']) if tc['questions'] else []
        qs.append({'title': self.q_title.value, 'description': self.q_desc.value or ''})
        await stcfg(self.g.id, questions=json.dumps(qs))
        await i.response.send_message("✅ Question ajoutée", ephemeral=True)

class DeployPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        channels = [c for c in g.text_channels][:25]
        if channels:
            options = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
            sel = Select(placeholder="📤 Salon...", options=options)
            sel.callback = self.deploy
            self.add_item(sel)
    
    def embed(self):
        return discord.Embed(title="📤 Déployer", description="Sélectionnez le salon", color=C.GREEN)
    
    async def deploy(self, i):
        tc = await gtcfg(self.g.id)
        if not tc['category_id'] or not tc['staff_role_id']:
            return await i.response.send_message("❌ Configurez catégorie et rôle staff", ephemeral=True)
        cid = int(i.data['values'][0])
        ch = self.g.get_channel(cid)
        e = discord.Embed(title=tc['panel_title'], description=tc['panel_description'], color=C.PURPLE)
        if self.g.icon: e.set_thumbnail(url=self.g.icon.url)
        await ch.send(embed=e, view=TkBtn(self.g.id))
        await i.response.send_message(f"✅ Déployé dans **#{ch.name}**", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        await i.response.defer()
        v = TicketPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)

class TkBtn(View):
    def __init__(self, gid):
        super().__init__(timeout=None)
        self.gid = gid
    
    @discord.ui.button(label="📩 Créer un ticket", emoji="📩", style=discord.ButtonStyle.success, custom_id="tk_create")
    async def cr(self, i, b):
        tc = await gtcfg(i.guild.id)
        qs = json.loads(tc['questions']) if tc['questions'] else []
        if qs:
            await i.response.send_modal(TkFormM(i.guild, qs))
        else:
            await make_ticket(i, {})

class TkFormM(Modal, title="📩 Créer un ticket"):
    def __init__(self, g, qs):
        super().__init__()
        self.g, self.qs = g, qs
        for idx, q in enumerate(qs[:5]):
            title = q['title'] if isinstance(q, dict) else q
            desc = q.get('description', '') if isinstance(q, dict) else ''
            self.add_item(TextInput(
                label=title[:45],
                placeholder=desc[:100] if desc else None,
                style=discord.TextStyle.paragraph,
                max_length=500,
                custom_id=f"q{idx}"
            ))
    
    async def on_submit(self, i):
        ans = {}
        for idx, q in enumerate(self.qs[:5]):
            title = q['title'] if isinstance(q, dict) else q
            ans[title] = self.children[idx].value
        await make_ticket(i, ans)

async def make_ticket(i, ans):
    tc = await gtcfg(i.guild.id)
    cat = i.guild.get_channel(tc['category_id'])
    rl = i.guild.get_role(tc['staff_role_id'])
    if not cat or not rl:
        return await i.response.send_message("❌ Tickets non configurés", ephemeral=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=?', (i.guild.id,))
        n = (await cur.fetchone())[0] + 1
    
    nm = tc['ticket_name'].format(user=i.user.name.lower()[:10], number=n)
    nm = re.sub(r'[^a-z0-9-]', '', nm)[:100]
    
    # Permissions : créateur + staff + bot
    ow = {
        i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        rl: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }
    
    # Ajouter les rôles immunisés
    immune_roles = await get_ticket_immune_roles(i.guild.id)
    for rid in immune_roles:
        role = i.guild.get_role(rid)
        if role:
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    
    ch = await cat.create_text_channel(name=nm, overwrites=ow)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO tickets (guild_id, channel_id, user_id, answers, created_at) VALUES (?,?,?,?,?)',
            (i.guild.id, ch.id, i.user.id, json.dumps(ans), now().isoformat())
        )
        await db.commit()
    
    e = discord.Embed(title="🎫 Nouveau Ticket", color=C.GREEN)
    e.description = f"👤 **Créé par:** {i.user.mention}\n📅 **Date:** {now().strftime('%d/%m/%Y %H:%M')}"
    if ans:
        for q, a in ans.items():
            e.add_field(name=f"❓ {q}", value=f"```{a[:200]}```", inline=False)
    
    await ch.send(content=f"{i.user.mention} {rl.mention}", embed=e, view=TkActs(i.guild.id, ch.id, i.user.id))
    await i.response.send_message(f"✅ Ticket créé: {ch.mention}", ephemeral=True)

class TkActs(View):
    def __init__(self, gid, cid, uid):
        super().__init__(timeout=None)
        self.gid, self.cid, self.uid = gid, cid, uid
    
    @discord.ui.button(label="🙋 Prendre", style=discord.ButtonStyle.success, custom_id="tk_claim")
    async def cl(self, i, b):
        tc = await gtcfg(i.guild.id)
        rl = i.guild.get_role(tc['staff_role_id'])
        if not rl or (rl not in i.user.roles and not i.user.guild_permissions.administrator):
            return await i.response.send_message("❌ Vous n'êtes pas staff", ephemeral=True)
        
        # Enregistrer qui a pris le ticket
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (i.user.id, i.channel.id))
            await db.commit()
        
        u = i.guild.get_member(self.uid)
        
        # Nouvelles permissions : SEUL le créateur + celui qui prend + immunisés + supérieurs
        ow = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        
        # Créateur peut voir
        if u:
            ow[u] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        
        # Celui qui prend peut voir
        ow[i.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        
        # Rôles au-dessus peuvent voir
        for r in i.guild.roles:
            if r.position > i.user.top_role.position and not r.is_bot_managed():
                ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        
        # Rôles immunisés peuvent voir
        immune_roles = await get_ticket_immune_roles(i.guild.id)
        for rid in immune_roles:
            role = i.guild.get_role(rid)
            if role:
                ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        
        await i.channel.edit(overwrites=ow)
        
        b.disabled, b.label, b.style = True, f"Pris par {i.user.display_name}", discord.ButtonStyle.secondary
        await i.response.edit_message(view=self)
        await i.channel.send(embed=discord.Embed(description=f"🙋 **{i.user.mention}** a pris ce ticket en charge", color=C.BLUE))
    
    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="tk_close")
    async def close(self, i, b):
        # Récupérer les infos du ticket
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM tickets WHERE channel_id=?', (i.channel.id,))
            ticket = await cur.fetchone()
        
        if not ticket:
            return await i.response.send_message("❌ Ticket introuvable", ephemeral=True)
        
        ticket = dict(ticket)
        
        # SEUL celui qui a pris le ticket ou le owner peut fermer
        can_close = (
            i.user.id == ticket['claimed_by'] or  # Celui qui a pris
            i.user.id == i.guild.owner_id  # Owner du serveur
        )
        
        if not can_close:
            claimer = i.guild.get_member(ticket['claimed_by']) if ticket['claimed_by'] else None
            claimer_name = claimer.display_name if claimer else "personne"
            return await i.response.send_message(
                f"❌ Seul **{claimer_name}** (celui qui a pris le ticket) ou le propriétaire du serveur peut fermer ce ticket",
                ephemeral=True
            )
        
        await i.response.send_message("🔒 Fermeture du ticket...")
        await asyncio.sleep(2)
        await close_ticket(i.channel, f"Fermé par {i.user.display_name}", i.user.id)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 STATS VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class StatsView(View):
    def __init__(self, user, target, guild, period='week'):
        super().__init__(timeout=300)
        self.user, self.target, self.guild, self.period = user, target, guild, period
    
    async def create_embed(self):
        stats = await get_advanced_stats(self.guild.id, self.target.id, self.period)
        period_names = {'day': "Aujourd'hui", 'week': 'Cette semaine', 'month': 'Ce mois'}
        voice_min = stats['voice_seconds'] // 60
        rank, rank_desc, rank_color = get_activity_rank(stats['messages'], voice_min)
        
        e = discord.Embed(color=rank_color)
        e.set_author(name=f"📊 Stats de {self.target.display_name}", icon_url=self.target.display_avatar.url)
        e.set_thumbnail(url=self.target.display_avatar.url)
        e.add_field(name="🏆 Rang", value=f"**{rank}**\n*{rank_desc}*", inline=False)
        e.add_field(name="📅 Période", value=f"**{period_names[self.period]}**", inline=False)
        e.add_field(name="💬 Messages", value=f"```{stats['messages']:,}```", inline=True)
        e.add_field(name="🎙️ Vocal", value=f"```{format_time(stats['voice_seconds'])}```", inline=True)
        
        if stats['top_text_channel']:
            ch = self.guild.get_channel(stats['top_text_channel'])
            e.add_field(name="💬 Salon préféré", value=f"#{ch.name if ch else '?'}", inline=True)
        
        if stats['top_voice_channel']:
            ch = self.guild.get_channel(stats['top_voice_channel'])
            e.add_field(name="🎙️ Vocal préféré", value=f"🔊 {ch.name if ch else '?'}", inline=True)
        
        e.set_footer(text=self.guild.name)
        e.timestamp = now()
        return e
    
    def update_buttons(self):
        for child in self.children:
            if isinstance(child, Button) and child.custom_id in ['day', 'week', 'month']:
                child.style = discord.ButtonStyle.success if child.custom_id == self.period else discord.ButtonStyle.secondary
    
    @discord.ui.button(label="Jour", emoji="📅", style=discord.ButtonStyle.secondary, custom_id="day")
    async def day_btn(self, i, b):
        self.period = 'day'; self.update_buttons()
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="Semaine", emoji="📆", style=discord.ButtonStyle.success, custom_id="week")
    async def week_btn(self, i, b):
        self.period = 'week'; self.update_buttons()
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="Mois", emoji="🗓️", style=discord.ButtonStyle.secondary, custom_id="month")
    async def month_btn(self, i, b):
        self.period = 'month'; self.update_buttons()
        await i.response.edit_message(embed=await self.create_embed(), view=self)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(TkBtn(0))
    bot.add_view(TkActs(0, 0, 0))
    
    for guild in bot.guilds:
        try:
            await guild.chunk()
            print(f"📥 {guild.name}: {guild.member_count} membres")
        except Exception as e:
            print(f"⚠️ {guild.name}: {e}")
    
    await bot.tree.sync()
    print(f"✅ {bot.user.name} connecté")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/help"))

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return
    
    # Tracker le message
    await track_message(msg.guild.id, msg.author.id, msg.channel.id)
    
    # Vérifier immunité
    if await is_immune(msg.author):
        return
    
    c = await gcfg(msg.guild.id)
    content = msg.content
    
    # Anti-Phishing
    if c.get('anti_phishing') and check_phishing(content):
        await msg.delete()
        try:
            await msg.author.timeout(timedelta(hours=1), reason="Lien de phishing détecté")
        except: pass
        return
    
    # Anti-Scam
    if c.get('anti_scam') and check_scam_patterns(content):
        await msg.delete()
        return
    
    # Anti-Invite
    if c.get('anti_invite') and check_discord_invite(content):
        await msg.delete()
        return
    
    # Anti-Link
    if c.get('anti_link') and re.search(r'https?://[^\s]+', content):
        await msg.delete()
        return
    
    # Anti-Image
    if c.get('anti_image') and msg.attachments:
        for a in msg.attachments:
            if a.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                await msg.delete()
                return
    
    # Anti-Spam
    if c.get('anti_spam') and await check_spam(msg):
        await msg.delete()
        try:
            await msg.author.timeout(timedelta(minutes=5), reason="Spam détecté")
        except: pass
        return
    
    # Anti-Mention Spam
    if c.get('anti_mention_spam') and check_mass_mentions(msg):
        await msg.delete()
        try:
            await msg.author.timeout(timedelta(minutes=10), reason="Spam de mentions")
        except: pass
        return
    
    # Anti-Caps
    if c.get('anti_caps') and check_caps(content):
        await msg.delete()
        return

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    if after.channel and not before.channel:
        await track_voice_start(member.guild.id, member.id, after.channel.id)
    elif before.channel and not after.channel:
        await track_voice_end(member.guild.id, member.id)
    elif before.channel and after.channel and before.channel != after.channel:
        await track_voice_end(member.guild.id, member.id)
        await track_voice_start(member.guild.id, member.id, after.channel.id)

@bot.event
async def on_member_join(m):
    c = await gcfg(m.guild.id)
    
    # Anti-NewAccount
    if c.get('anti_newaccount') and check_new_account(m, c.get('newaccount_days', 7)):
        try:
            await m.kick(reason=f"Compte trop récent (<{c.get('newaccount_days', 7)} jours)")
        except: pass
        return
    
    # Welcome
    if c.get('welcome_on') and c.get('welcome_channel'):
        ch = m.guild.get_channel(c['welcome_channel'])
        if ch:
            txt = c.get('welcome_msg', 'Bienvenue {member} !').format(
                member=m.mention, server=m.guild.name, count=m.guild.member_count
            )
            e = discord.Embed(title="👋 Bienvenue!", description=txt, color=C.GREEN)
            e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)

@bot.event
async def on_member_remove(m):
    if m.bot:
        return
    
    # Fermer les tickets ouverts par ce membre
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",
            (m.guild.id, m.id)
        )
        tickets = await cur.fetchall()
    
    for (channel_id,) in tickets:
        channel = m.guild.get_channel(channel_id)
        if channel:
            await close_ticket(channel, f"Membre a quitté le serveur ({m.name})")
    
    # Nettoyer les données
    await cleanup_member_data(m.guild.id, m.id)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDES
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Membre à avertir", raison="Raison de l'avertissement")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not await has_permission(i.user, 'warn'):
        return await i.response.send_message("❌ Permission refusée", ephemeral=True)
    if await is_immune(membre):
        return await i.response.send_message("❌ Membre immunisé", ephemeral=True)
    
    count = await add_infraction(i.guild.id, membre.id, i.user.id, 'warn', raison)
    
    e = discord.Embed(title="⚠️ Avertissement", color=C.YELLOW)
    e.add_field(name="👤 Membre", value=membre.mention, inline=True)
    e.add_field(name="👮 Modérateur", value=i.user.mention, inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.add_field(name="📊 Total", value=f"**{count}** warn(s)", inline=True)
    e.timestamp = now()
    
    await i.response.send_message(embed=e)
    
    c = await gcfg(i.guild.id)
    if c.get('mod_log_channel'):
        log_ch = i.guild.get_channel(c['mod_log_channel'])
        if log_ch: await log_ch.send(embed=e)
    
    warn_count = await get_warn_count(i.guild.id, membre.id)
    if c.get('warns_ban') and warn_count >= c['warns_ban']:
        await membre.ban(reason=f"Auto-ban: {warn_count} warns")
        await i.followup.send(f"🔨 **{membre}** auto-banni ({warn_count} warns)")
    elif c.get('warns_kick') and warn_count >= c['warns_kick']:
        await membre.kick(reason=f"Auto-kick: {warn_count} warns")
        await i.followup.send(f"👢 **{membre}** auto-expulsé ({warn_count} warns)")

@bot.tree.command(name="timeout", description="⏰ Exclure temporairement un membre")
@app_commands.describe(membre="Membre", duree="Durée (30s, 5m, 2h, 1d, 1w)", raison="Raison")
async def timeout_cmd(i: discord.Interaction, membre: discord.Member, duree: str, raison: str):
    if not await has_permission(i.user, 'timeout'):
        return await i.response.send_message("❌ Permission refusée", ephemeral=True)
    if await is_immune(membre):
        return await i.response.send_message("❌ Membre immunisé", ephemeral=True)
    
    seconds = parse_duration(duree)
    if not seconds:
        return await i.response.send_message("❌ Format: `30s`, `5m`, `2h`, `1d`, `1w`", ephemeral=True)
    
    try:
        until = now() + timedelta(seconds=seconds)
        await membre.timeout(until, reason=raison)
    except discord.Forbidden:
        return await i.response.send_message("❌ Permission Discord manquante", ephemeral=True)
    
    await add_infraction(i.guild.id, membre.id, i.user.id, 'timeout', raison, seconds)
    
    e = discord.Embed(title="⏰ Timeout", color=C.ORANGE)
    e.add_field(name="👤 Membre", value=membre.mention, inline=True)
    e.add_field(name="👮 Modérateur", value=i.user.mention, inline=True)
    e.add_field(name="⏱️ Durée", value=format_duration(seconds), inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.timestamp = now()
    
    await i.response.send_message(embed=e)
    
    c = await gcfg(i.guild.id)
    if c.get('mod_log_channel'):
        log_ch = i.guild.get_channel(c['mod_log_channel'])
        if log_ch: await log_ch.send(embed=e)

@bot.tree.command(name="untimeout", description="🔓 Retirer le timeout")
@app_commands.describe(membre="Membre")
async def untimeout_cmd(i: discord.Interaction, membre: discord.Member):
    if not await has_permission(i.user, 'timeout'):
        return await i.response.send_message("❌ Permission refusée", ephemeral=True)
    try:
        await membre.timeout(None, reason=f"Retiré par {i.user}")
        await i.response.send_message(f"✅ Timeout retiré pour **{membre.display_name}**", ephemeral=True)
    except:
        await i.response.send_message("❌ Erreur", ephemeral=True)

@bot.tree.command(name="infractions", description="📜 Voir les infractions d'un membre")
@app_commands.describe(membre="Membre")
async def infractions_cmd(i: discord.Interaction, membre: discord.Member):
    if not await has_permission(i.user, 'infractions'):
        return await i.response.send_message("❌ Permission refusée", ephemeral=True)
    
    infractions = await get_infractions(i.guild.id, membre.id)
    
    e = discord.Embed(title=f"📜 Infractions de {membre.display_name}", color=C.RED)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    if not infractions:
        e.description = "✅ Aucune infraction"
    else:
        e.description = f"**{len(infractions)}** infraction(s)\n\n"
        for idx, inf in enumerate(infractions[:10]):
            mod = i.guild.get_member(inf['mod_id'])
            mod_name = mod.display_name if mod else f"ID: {inf['mod_id']}"
            try:
                date = datetime.fromisoformat(inf['created_at']).strftime('%d/%m/%Y %H:%M')
            except:
                date = "?"
            emoji = "⚠️" if inf['type'] == 'warn' else "⏰"
            dur = f" ({format_duration(inf['duration'])})" if inf['duration'] else ""
            e.add_field(
                name=f"{emoji} #{idx+1} - {inf['type'].upper()}{dur}",
                value=f"**Raison:** {inf['reason'][:80]}\n**Par:** {mod_name}\n**Date:** {date}",
                inline=False
            )
    
    await i.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="configure", description="⚙️ Panneau de configuration (Admin)")
async def cfg_cmd(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    if not i.user.guild_permissions.administrator and i.user.id != i.guild.owner_id:
        return await i.followup.send("❌ Admin requis")
    v = MainPanel(i.user, i.guild)
    await i.followup.send(embed=v.embed(), view=v)

@bot.tree.command(name="stats", description="📊 Voir les statistiques d'activité")
@app_commands.describe(membre="Membre (optionnel)")
async def stats_cmd(i: discord.Interaction, membre: discord.Member = None):
    await i.response.defer()
    target = membre or i.user
    v = StatsView(i.user, target, i.guild, 'week')
    await i.followup.send(embed=await v.create_embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("🚀 Démarrage...")
    print(f"📁 DB: {DB_PATH}")
    bot.run(TOKEN)
