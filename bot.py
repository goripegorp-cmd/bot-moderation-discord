# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v9.1 🌟                                 ║
# ║     Protection + Tickets + Network Social Media Tracker                       ║
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
import aiohttp
import os
import re
import json
import asyncio
import xml.etree.ElementTree as ET
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
spam_tracker = {}

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

PLATFORM_INFO = {
    'youtube': {'color': 0xFF0000, 'emoji': '📺', 'name': 'YouTube'},
    'twitter': {'color': 0x1DA1F2, 'emoji': '🐦', 'name': 'Twitter/X'},
    'twitch': {'color': 0x9146FF, 'emoji': '🎮', 'name': 'Twitch'},
    'tiktok': {'color': 0x010101, 'emoji': '🎵', 'name': 'TikTok'},
    'instagram': {'color': 0xE1306C, 'emoji': '📸', 'name': 'Instagram'},
}

PHISHING_DOMAINS = [
    'discord-nitro.gift', 'discordgift.site', 'free-nitro.com', 'steampowered.ru',
    'dlscord.com', 'discordi.gift', 'discord-app.com', 'discordapp.co', 'discrod.com',
    'dlscord.org', 'discordc.gift', 'discord-airdrop.com', 'steamcommunity.ru',
    'steamcommunitiy.com', 'steamcomunity.com', 'store-steampowered.com',
    'discord-give.com', 'discord-free.com', 'nitro-discord.com', 'discord.gift.com'
]

SUSPICIOUS_PATTERNS = [
    r'free\s*nitro', r'discord\s*nitro\s*free', r'steam\s*gift', r'free\s*steam',
    r'claim\s*your\s*gift', r'@everyone.*http', r'@here.*http', r'won\s*a?\s*nitro',
    r'airdrop.*discord', r'bitcoin.*free', r'crypto.*giveaway'
]

def now():
    return datetime.now(timezone.utc)

def today():
    return datetime.now(timezone.utc).date()

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
                anti_newaccount INTEGER DEFAULT 0,
                newaccount_days INTEGER DEFAULT 7,
                welcome_on INTEGER DEFAULT 0,
                welcome_msg TEXT DEFAULT 'Bienvenue {member} !'
            );
            CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id));
            CREATE TABLE IF NOT EXISTS activity (guild_id INTEGER, user_id INTEGER, last_message DATETIME, last_voice DATETIME, PRIMARY KEY (guild_id, user_id));
            CREATE TABLE IF NOT EXISTS ticket_config (
                guild_id INTEGER PRIMARY KEY, category_id INTEGER, staff_role_id INTEGER,
                ticket_name TEXT DEFAULT 'ticket-{user}-{number}',
                panel_title TEXT DEFAULT '🎫 Support',
                panel_description TEXT DEFAULT 'Cliquez pour créer un ticket',
                questions TEXT DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS ticket_immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id));
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER,
                user_id INTEGER, claimed_by INTEGER, status TEXT DEFAULT 'open',
                answers TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                closed_at DATETIME, closed_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS message_stats (guild_id INTEGER, user_id INTEGER, channel_id INTEGER, date TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (guild_id, user_id, channel_id, date));
            CREATE TABLE IF NOT EXISTS voice_stats (guild_id INTEGER, user_id INTEGER, channel_id INTEGER, date TEXT, seconds INTEGER DEFAULT 0, PRIMARY KEY (guild_id, user_id, channel_id, date));
            CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, duration INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS role_permissions (guild_id INTEGER, role_id INTEGER, permission TEXT, PRIMARY KEY (guild_id, role_id, permission));
            CREATE TABLE IF NOT EXISTS social_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, platform TEXT,
                account_id TEXT, account_name TEXT, channel_id INTEGER,
                last_post_id TEXT, last_check DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_social_feeds ON social_feeds(guild_id, platform);
        ''')
        await db.commit()
    print(f"✅ DB OK ({DB_PATH})")

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
        return {'guild_id': gid, 'category_id': None, 'staff_role_id': None, 'ticket_name': 'ticket-{user}-{number}', 'panel_title': '🎫 Support', 'panel_description': 'Cliquez pour créer un ticket', 'questions': '[]'}

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
            cur = await db.execute('SELECT 1 FROM role_permissions WHERE guild_id=? AND role_id=? AND permission=?', (member.guild.id, role.id, permission))
            if await cur.fetchone(): return True
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
        await db.execute('INSERT INTO infractions (guild_id, user_id, mod_id, type, reason, duration) VALUES (?,?,?,?,?,?)', (gid, uid, mod_id, inf_type, reason, duration))
        await db.commit()
        cur = await db.execute('SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=?', (gid, uid))
        return (await cur.fetchone())[0]

async def get_infractions(gid, uid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM infractions WHERE guild_id=? AND user_id=? ORDER BY created_at DESC', (gid, uid))
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO activity (guild_id, user_id) VALUES (?,?)', (gid, uid))
        await db.execute('UPDATE activity SET last_message=? WHERE guild_id=? AND user_id=?', (now().isoformat(), gid, uid))
        await db.execute('INSERT OR IGNORE INTO message_stats (guild_id, user_id, channel_id, date, count) VALUES (?,?,?,?,0)', (gid, uid, cid, date_str))
        await db.execute('UPDATE message_stats SET count = count + 1 WHERE guild_id=? AND user_id=? AND channel_id=? AND date=?', (gid, uid, cid, date_str))
        await db.commit()

async def track_voice_start(gid, uid, cid):
    voice_sessions[(gid, uid)] = {'start': now(), 'channel_id': cid}
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO activity (guild_id, user_id) VALUES (?,?)', (gid, uid))
        await db.execute('UPDATE activity SET last_voice=? WHERE guild_id=? AND user_id=?', (now().isoformat(), gid, uid))
        await db.commit()

async def track_voice_end(gid, uid):
    key = (gid, uid)
    if key not in voice_sessions: return
    session = voice_sessions.pop(key)
    duration = (now() - session['start']).total_seconds()
    date_str = today().strftime('%Y-%m-%d')
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO voice_stats (guild_id, user_id, channel_id, date, seconds) VALUES (?,?,?,?,0)', (gid, uid, session['channel_id'], date_str))
        await db.execute('UPDATE voice_stats SET seconds = seconds + ? WHERE guild_id=? AND user_id=? AND channel_id=? AND date=?', (int(duration), gid, uid, session['channel_id'], date_str))
        await db.commit()

async def get_ticket_immune_roles(gid):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT role_id FROM ticket_immune_roles WHERE guild_id=?', (gid,))
        return [r[0] for r in await cur.fetchall()]

async def cleanup_member_data(gid, uid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM message_stats WHERE guild_id=? AND user_id=?', (gid, uid))
        await db.execute('DELETE FROM voice_stats WHERE guild_id=? AND user_id=?', (gid, uid))
        await db.execute('DELETE FROM activity WHERE guild_id=? AND user_id=?', (gid, uid))
        await db.commit()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🌐 NETWORK / SOCIAL FEEDS
# ═══════════════════════════════════════════════════════════════════════════════

async def add_social_feed(gid, platform, account_id, account_name, channel_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO social_feeds (guild_id, platform, account_id, account_name, channel_id) VALUES (?,?,?,?,?)', (gid, platform, account_id, account_name, channel_id))
        await db.commit()

async def get_social_feeds(gid, platform=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if platform:
            cur = await db.execute('SELECT * FROM social_feeds WHERE guild_id=? AND platform=?', (gid, platform))
        else:
            cur = await db.execute('SELECT * FROM social_feeds WHERE guild_id=?', (gid,))
        return [dict(r) for r in await cur.fetchall()]

async def delete_social_feed(feed_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM social_feeds WHERE id=?', (feed_id,))
        await db.commit()

async def update_feed_last_post(feed_id, post_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE social_feeds SET last_post_id=?, last_check=? WHERE id=?', (post_id, now().isoformat(), feed_id))
        await db.commit()

async def fetch_youtube_feed(channel_id):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    xml_data = await resp.text()
                    root = ET.fromstring(xml_data)
                    ns = {'atom': 'http://www.w3.org/2005/Atom', 'media': 'http://search.yahoo.com/mrss/', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
                    channel_name = root.find('atom:title', ns)
                    channel_name = channel_name.text if channel_name is not None else "YouTube"
                    videos = []
                    for entry in root.findall('atom:entry', ns)[:5]:
                        video_id = entry.find('yt:videoId', ns)
                        title = entry.find('atom:title', ns)
                        published = entry.find('atom:published', ns)
                        media_group = entry.find('media:group', ns)
                        description = media_group.find('media:description', ns) if media_group is not None else None
                        thumbnail = media_group.find('media:thumbnail', ns) if media_group is not None else None
                        videos.append({
                            'id': video_id.text if video_id is not None else None,
                            'title': title.text if title is not None else "Sans titre",
                            'published': published.text[:10] if published is not None else None,
                            'description': (description.text[:200] + "...") if description is not None and description.text and len(description.text) > 200 else (description.text if description is not None else ""),
                            'thumbnail': thumbnail.get('url') if thumbnail is not None else None,
                            'url': f"https://www.youtube.com/watch?v={video_id.text}" if video_id is not None else None
                        })
                    return {'channel_name': channel_name, 'videos': videos}
    except Exception as e:
        print(f"YouTube error: {e}")
    return None

async def fetch_rss_feed(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    xml_data = await resp.text()
                    root = ET.fromstring(xml_data)
                    channel = root.find('channel')
                    if channel is None: return None
                    items = []
                    for item in channel.findall('item')[:5]:
                        title = item.find('title')
                        link = item.find('link')
                        description = item.find('description')
                        pub_date = item.find('pubDate')
                        enclosure = item.find('enclosure')
                        image_url = None
                        if enclosure is not None and 'image' in enclosure.get('type', ''):
                            image_url = enclosure.get('url')
                        if not image_url and description is not None:
                            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description.text or '')
                            if img_match: image_url = img_match.group(1)
                        desc_text = re.sub(r'<[^>]+>', '', description.text or '') if description is not None else ''
                        items.append({
                            'id': link.text if link is not None else None,
                            'title': title.text if title is not None else '',
                            'description': desc_text[:200],
                            'url': link.text if link is not None else None,
                            'image': image_url,
                            'published': pub_date.text if pub_date is not None else None
                        })
                    return {'items': items}
    except Exception as e:
        print(f"RSS error: {e}")
    return None

async def fetch_twitch_status(username):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://www.twitch.tv/{username}", timeout=15) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    is_live = '"isLiveBroadcast":true' in html
                    return {'username': username, 'is_live': is_live, 'url': f"https://www.twitch.tv/{username}"}
    except: pass
    return None

def create_social_embed(platform, data):
    info = PLATFORM_INFO.get(platform, {'color': C.BLURPLE, 'emoji': '🌐', 'name': platform})
    e = discord.Embed(color=info['color'])
    
    if platform == 'youtube' and data.get('video'):
        video = data['video']
        e.title = video.get('title', 'Nouvelle vidéo')
        e.url = video.get('url')
        e.description = video.get('description', '')[:200]
        e.set_author(name=f"{info['emoji']} {data.get('channel_name', 'YouTube')}")
        if video.get('thumbnail'): e.set_image(url=video['thumbnail'])
        if video.get('published'): e.add_field(name="📅 Publié", value=video['published'], inline=True)
        e.set_footer(text="YouTube • Nouvelle vidéo")
    
    elif platform == 'twitch' and data.get('is_live'):
        e.title = f"🔴 {data['username']} est en LIVE !"
        e.url = data['url']
        e.description = "Cliquez pour regarder le stream"
        e.set_footer(text="Twitch • En direct")
    
    elif platform in ['tiktok', 'instagram', 'twitter'] and data.get('post'):
        post = data['post']
        e.title = post.get('title', 'Nouveau post')[:100] or f"Nouveau post {info['name']}"
        e.url = post.get('url')
        e.description = post.get('description', '')[:200]
        e.set_author(name=f"{info['emoji']} {data.get('account_name', info['name'])}")
        if post.get('image'): e.set_image(url=post['image'])
        e.set_footer(text=f"{info['name']} • Nouveau post")
    
    e.timestamp = now()
    return e

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 UTILS
# ═══════════════════════════════════════════════════════════════════════════════

def format_time(seconds):
    if seconds < 60: return f"{int(seconds)}s"
    elif seconds < 3600: return f"{int(seconds)//60}m"
    else: return f"{int(seconds)//3600}h {(int(seconds)%3600)//60}m"

def format_duration(seconds):
    if seconds < 60: return f"{seconds} sec"
    elif seconds < 3600: return f"{seconds // 60} min"
    elif seconds < 86400: return f"{seconds // 3600}h"
    else: return f"{seconds // 86400}j"

def parse_duration(duration_str):
    match = re.match(r'^(\d+)([smhdw])$', duration_str.lower().strip())
    if not match: return None
    value, unit = int(match.group(1)), match.group(2)
    multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
    return min(value * multipliers[unit], 604800 * 4)

def check_phishing(content):
    return any(d in content.lower() for d in PHISHING_DOMAINS)

def check_scam_patterns(content):
    return any(re.search(p, content.lower(), re.IGNORECASE) for p in SUSPICIOUS_PATTERNS)

def check_discord_invite(content):
    return bool(re.search(r'(discord\.gg|discord\.com/invite)/[a-zA-Z0-9]+', content))

def check_mass_mentions(message):
    return len(message.mentions) > 5 or message.mention_everyone

def check_caps(content):
    if len(content) < 10: return False
    return sum(1 for c in content if c.isupper()) / len(content) > 0.7

async def check_spam(message):
    key = (message.guild.id, message.author.id)
    current_time = now()
    if key not in spam_tracker:
        spam_tracker[key] = {'messages': [], 'last_content': ''}
    tracker = spam_tracker[key]
    tracker['messages'] = [t for t in tracker['messages'] if (current_time - t).total_seconds() < 10]
    tracker['messages'].append(current_time)
    if len(tracker['messages']) > 5: return True
    if tracker['last_content'] == message.content and len(message.content) > 5: return True
    tracker['last_content'] = message.content
    return False

async def get_ticket_transcript(channel, limit=100):
    messages = []
    try:
        async for msg in channel.history(limit=limit, oldest_first=True):
            timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
            content = msg.content or "[Embed/Fichier]"
            messages.append(f"[{timestamp}] {msg.author.display_name}: {content}")
    except: pass
    return "\n".join(messages) if messages else "Aucun message"

async def close_ticket(channel, reason, closed_by=None):
    guild = channel.guild
    c = await gcfg(guild.id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM tickets WHERE channel_id=?', (channel.id,))
        ticket = await cur.fetchone()
        if not ticket: return
        ticket = dict(ticket)
    transcript = await get_ticket_transcript(channel)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE tickets SET status="closed", closed_at=?, closed_reason=? WHERE channel_id=?', (now().isoformat(), reason, channel.id))
        await db.commit()
    if c.get('ticket_log_channel'):
        log_channel = guild.get_channel(c['ticket_log_channel'])
        if log_channel:
            user = guild.get_member(ticket['user_id'])
            claimer = guild.get_member(ticket['claimed_by']) if ticket['claimed_by'] else None
            e = discord.Embed(title="🎫 Ticket Fermé", color=C.RED)
            e.add_field(name="📝 ID", value=f"#{ticket['id']}", inline=True)
            e.add_field(name="👤 Créé par", value=user.mention if user else f"ID: {ticket['user_id']}", inline=True)
            e.add_field(name="🙋 Pris par", value=claimer.mention if claimer else "Personne", inline=True)
            e.add_field(name="❓ Raison", value=reason, inline=False)
            if len(transcript) > 1000: transcript = transcript[:1000] + "\n...[Tronqué]"
            e.add_field(name="📜 Transcript", value=f"```\n{transcript}\n```", inline=False)
            e.timestamp = now()
            await log_channel.send(embed=e)
    try: await channel.delete()
    except: pass

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
        return e
    
    @discord.ui.button(label="Permissions", emoji="🔐", style=discord.ButtonStyle.danger, row=0)
    async def b0(self, i, b):
        v = PermPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)
    
    @discord.ui.button(label="Sanctions", emoji="⚖️", style=discord.ButtonStyle.danger, row=0)
    async def b1(self, i, b):
        v = SanctPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def b2(self, i, b):
        v = LogsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=1)
    async def b3(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def b4(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def b5(self, i, b):
        v = WelcPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Network", emoji="🌐", style=discord.ButtonStyle.primary, row=2)
    async def b_network(self, i, b):
        v = NetworkPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Activité", emoji="📊", style=discord.ButtonStyle.secondary, row=2)
    async def b6(self, i, b):
        v = ActPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.primary, row=3)
    async def b7(self, i, b):
        v = TicketPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=3)
    async def b8(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🌐 NETWORK PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class NetworkPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        feeds = await get_social_feeds(self.g.id)
        counts = {}
        for f in feeds:
            counts[f['platform']] = counts.get(f['platform'], 0) + 1
        feed_list = ""
        for platform, count in counts.items():
            info = PLATFORM_INFO.get(platform, {'emoji': '🌐', 'name': platform})
            feed_list += f"{info['emoji']} {info['name']}: {count}\n"
        e = discord.Embed(title="🌐 Network - Réseaux Sociaux", color=C.BLURPLE)
        e.description = f"""```yml
📡 Suivi des réseaux sociaux
──────────────────────────────────────────
{feed_list or 'Aucun compte suivi'}
──────────────────────────────────────────
Total : {len(feeds)} compte(s)
```
**Plateformes :** 📺 YouTube • 🐦 Twitter • 🎮 Twitch • 🎵 TikTok • 📸 Instagram

⚠️ **TikTok/Instagram** : Utilisez un flux RSS (rss.app)"""
        return e
    
    @discord.ui.button(label="YouTube", emoji="📺", style=discord.ButtonStyle.danger, row=0)
    async def youtube(self, i, b):
        v = PlatformPanel(self.u, self.g, 'youtube')
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Twitter", emoji="🐦", style=discord.ButtonStyle.primary, row=0)
    async def twitter(self, i, b):
        v = PlatformPanel(self.u, self.g, 'twitter')
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Twitch", emoji="🎮", style=discord.ButtonStyle.secondary, row=0)
    async def twitch(self, i, b):
        v = PlatformPanel(self.u, self.g, 'twitch')
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="TikTok", emoji="🎵", style=discord.ButtonStyle.secondary, row=1)
    async def tiktok(self, i, b):
        v = PlatformPanel(self.u, self.g, 'tiktok')
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Instagram", emoji="📸", style=discord.ButtonStyle.secondary, row=1)
    async def instagram(self, i, b):
        v = PlatformPanel(self.u, self.g, 'instagram')
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class PlatformPanel(View):
    def __init__(self, u, g, platform):
        super().__init__(timeout=900)
        self.u, self.g, self.platform = u, g, platform
        self.info = PLATFORM_INFO.get(platform, {'emoji': '🌐', 'name': platform, 'color': C.BLURPLE})
    
    async def embed(self):
        feeds = await get_social_feeds(self.g.id, self.platform)
        feed_list = ""
        for f in feeds:
            ch = self.g.get_channel(f['channel_id'])
            ch_name = f"#{ch.name}" if ch else "❌"
            feed_list += f"• **{f['account_name']}** → {ch_name}\n"
        
        help_text = ""
        if self.platform == 'youtube':
            help_text = "**ID chaîne:** `UCxxxxx` (dans l'URL)"
        elif self.platform == 'tiktok':
            help_text = "**Utilisez RSS.app** pour créer un flux RSS\n→ https://rss.app/rss-feed/tiktok-to-rss"
        elif self.platform == 'instagram':
            help_text = "**Utilisez RSS.app** pour créer un flux RSS\n→ https://rss.app/rss-feed/create-instagram-rss-feed"
        elif self.platform == 'twitter':
            help_text = "**Flux RSS** ou nom d'utilisateur"
        elif self.platform == 'twitch':
            help_text = "**Nom d'utilisateur** Twitch"
        
        e = discord.Embed(title=f"{self.info['emoji']} {self.info['name']}", color=self.info['color'])
        e.description = f"```yml\nComptes suivis:\n──────────────────────────────────────────\n{feed_list or 'Aucun'}\n```\n{help_text}"
        return e
    
    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddFeedModal(self.g, self.platform))
    
    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=0)
    async def remove(self, i, b):
        v = RemoveFeedPanel(self.u, self.g, self.platform)
        await v.setup()
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🔄 Tester", style=discord.ButtonStyle.primary, row=0)
    async def test(self, i, b):
        await i.response.defer(ephemeral=True)
        feeds = await get_social_feeds(self.g.id, self.platform)
        if not feeds:
            return await i.followup.send("❌ Aucun compte", ephemeral=True)
        feed = feeds[0]
        if self.platform == 'youtube':
            data = await fetch_youtube_feed(feed['account_id'])
            if data and data['videos']:
                embed = create_social_embed('youtube', {'video': data['videos'][0], 'channel_name': data['channel_name']})
                view = View()
                view.add_item(Button(label="▶️ Regarder", url=data['videos'][0]['url'], style=discord.ButtonStyle.link))
                await i.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await i.followup.send("❌ Impossible de récupérer", ephemeral=True)
        elif self.platform == 'twitch':
            data = await fetch_twitch_status(feed['account_id'])
            if data:
                embed = create_social_embed('twitch', data)
                await i.followup.send(embed=embed, ephemeral=True)
            else:
                await i.followup.send("❌ Erreur Twitch", ephemeral=True)
        elif self.platform in ['tiktok', 'instagram', 'twitter']:
            data = await fetch_rss_feed(feed['account_id'])
            if data and data['items']:
                post = data['items'][0]
                embed = create_social_embed(self.platform, {'post': post, 'account_name': feed['account_name']})
                view = View()
                if post.get('url'):
                    view.add_item(Button(label="🔗 Voir", url=post['url'], style=discord.ButtonStyle.link))
                await i.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await i.followup.send("❌ Impossible de récupérer le flux RSS", ephemeral=True)
        else:
            await i.followup.send("⚠️ Test non disponible", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = NetworkPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddFeedModal(Modal):
    def __init__(self, g, platform):
        super().__init__(title=f"Ajouter {PLATFORM_INFO.get(platform, {}).get('name', platform)}")
        self.g, self.platform = g, platform
        placeholders = {
            'youtube': "ID chaîne (UCxxxxx)",
            'twitter': "URL RSS ou @username",
            'twitch': "Nom d'utilisateur",
            'tiktok': "URL du flux RSS (rss.app)",
            'instagram': "URL du flux RSS (rss.app)"
        }
        self.account = TextInput(label="Identifiant / URL RSS", placeholder=placeholders.get(platform, "Identifiant"), max_length=200)
        self.add_item(self.account)
        self.channel = TextInput(label="ID du salon Discord", placeholder="Clic droit > Copier l'ID", max_length=20)
        self.add_item(self.channel)
    
    async def on_submit(self, i):
        account_input = self.account.value.strip()
        account_id = account_input
        account_name = account_input
        if self.platform == 'youtube':
            match = re.search(r'channel/([a-zA-Z0-9_-]+)', account_input)
            if match: account_id = match.group(1)
            account_name = account_id[:20]
        elif self.platform == 'twitch':
            account_id = account_input.replace('@', '').split('/')[-1]
            account_name = account_id
        elif self.platform in ['tiktok', 'instagram', 'twitter']:
            if 'http' in account_input:
                account_id = account_input
                match = re.search(r'@?([a-zA-Z0-9_]+)', account_input.split('/')[-1])
                account_name = match.group(1) if match else account_input[:20]
            else:
                account_name = account_input.replace('@', '')
        try:
            channel_id = int(self.channel.value.strip())
            channel = i.guild.get_channel(channel_id)
            if not channel:
                return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
        except:
            return await i.response.send_message("❌ ID invalide", ephemeral=True)
        await add_social_feed(i.guild.id, self.platform, account_id, account_name, channel_id)
        info = PLATFORM_INFO.get(self.platform, {'emoji': '🌐'})
        await i.response.send_message(f"✅ {info['emoji']} **{account_name}** ajouté → {channel.mention}", ephemeral=True)

class RemoveFeedPanel(View):
    def __init__(self, u, g, platform):
        super().__init__(timeout=300)
        self.u, self.g, self.platform = u, g, platform
    
    async def setup(self):
        feeds = await get_social_feeds(self.g.id, self.platform)
        if feeds:
            options = [discord.SelectOption(label=f['account_name'][:25], value=str(f['id'])) for f in feeds[:25]]
            sel = Select(placeholder="🗑️ Sélectionner...", options=options)
            sel.callback = self.remove
            self.add_item(sel)
    
    async def remove(self, i):
        await delete_social_feed(int(i.data['values'][0]))
        await i.response.send_message("✅ Supprimé", ephemeral=True)
    
    async def embed(self):
        return discord.Embed(title="🗑️ Supprimer", color=C.RED)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = PlatformPanel(self.u, self.g, self.platform)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔐 PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════════

class PermPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            options = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
            sel = Select(placeholder="🔐 Sélectionner un rôle...", options=options)
            sel.callback = self.role_selected
            self.add_item(sel)
    
    async def role_selected(self, i):
        v = RolePermEditor(self.u, self.g, self.g.get_role(int(i.data['values'][0])))
        await v.setup()
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    def embed(self):
        e = discord.Embed(title="🔐 Permissions", color=C.RED)
        e.description = "```yml\n⚠️ warn        : /warn\n⏰ timeout     : /timeout\n📜 infractions : /infractions\n```\n👇 Sélectionnez un rôle"
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
        e = discord.Embed(title=f"🔐 @{self.role.name}", color=self.role.color)
        e.description = f"```yml\n⚠️ warn        : {s('warn')}\n⏰ timeout     : {s('timeout')}\n📜 infractions : {s('infractions')}\n```"
        return e
    
    @discord.ui.button(label="Warn", emoji="⚠️", style=discord.ButtonStyle.secondary, row=0)
    async def tw(self, i, b):
        enabled = 'warn' not in self.perms
        await set_role_permission(self.g.id, self.role.id, 'warn', enabled)
        if enabled: self.perms.append('warn')
        else: self.perms.remove('warn')
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Timeout", emoji="⏰", style=discord.ButtonStyle.secondary, row=0)
    async def tt(self, i, b):
        enabled = 'timeout' not in self.perms
        await set_role_permission(self.g.id, self.role.id, 'timeout', enabled)
        if enabled: self.perms.append('timeout')
        else: self.perms.remove('timeout')
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="Infractions", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def ti(self, i, b):
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
#                           ⚖️ SANCTIONS + 📜 LOGS + 🛡️ PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class SanctPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        c = await gcfg(self.g.id)
        wk = c.get('warns_kick', 0)
        wb = c.get('warns_ban', 0)
        e = discord.Embed(title="⚖️ Sanctions Auto", color=C.PINK)
        e.description = f"```yml\n👢 Kick: {f'{wk} warns' if wk else 'Off'}\n🔨 Ban : {f'{wb} warns' if wb else 'Off'}\n```"
        return e
    
    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.primary)
    async def config(self, i, b):
        await i.response.send_modal(SanctConfigM(self.g))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class SanctConfigM(Modal, title="⚖️ Sanctions"):
    wk = TextInput(label="Warns pour Kick (0=off)", required=False, max_length=2)
    wb = TextInput(label="Warns pour Ban (0=off)", required=False, max_length=2)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        k = int(self.wk.value) if self.wk.value.isdigit() else 0
        b = int(self.wb.value) if self.wb.value.isdigit() else 0
        await scfg(self.g.id, warns_kick=k, warns_ban=b)
        await i.response.send_message(f"✅ Kick: {k} | Ban: {b}", ephemeral=True)

class LogsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        channels = [c for c in g.text_channels][:25]
        if channels:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
            s1 = Select(placeholder="📝 Logs généraux...", options=opts, row=1); s1.callback = self.l1; self.add_item(s1)
            s2 = Select(placeholder="⚔️ Logs modération...", options=opts.copy(), row=2); s2.callback = self.l2; self.add_item(s2)
            s3 = Select(placeholder="🎫 Logs tickets...", options=opts.copy(), row=3); s3.callback = self.l3; self.add_item(s3)
    async def l1(self, i): await scfg(self.g.id, log_channel=int(i.data['values'][0])); await i.response.send_message("✅", ephemeral=True)
    async def l2(self, i): await scfg(self.g.id, mod_log_channel=int(i.data['values'][0])); await i.response.send_message("✅", ephemeral=True)
    async def l3(self, i): await scfg(self.g.id, ticket_log_channel=int(i.data['values'][0])); await i.response.send_message("✅", ephemeral=True)
    async def embed(self):
        c = await gcfg(self.g.id)
        lc, mc, tc = self.g.get_channel(c.get('log_channel')), self.g.get_channel(c.get('mod_log_channel')), self.g.get_channel(c.get('ticket_log_channel'))
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        e.description = f"```yml\n📝 Généraux  : {f'#{lc.name}' if lc else '❌'}\n⚔️ Modération: {f'#{mc.name}' if mc else '❌'}\n🎫 Tickets   : {f'#{tc.name}' if tc else '❌'}\n```"
        return e
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, i, b): v = MainPanel(self.u, self.g); await i.response.edit_message(embed=v.embed(), view=v)

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    async def embed(self):
        c = await gcfg(self.g.id)
        def s(v): return "✅" if v else "❌"
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = f"```yml\n🔗 Anti-Liens    : {s(c.get('anti_link'))}\n🎟️ Anti-Invite   : {s(c.get('anti_invite'))}\n🖼️ Anti-Images   : {s(c.get('anti_image'))}\n🎣 Anti-Phishing : {s(c.get('anti_phishing'))}\n🚨 Anti-Scam     : {s(c.get('anti_scam'))}\n📨 Anti-Spam     : {s(c.get('anti_spam'))}\n📢 Anti-Mention  : {s(c.get('anti_mention_spam'))}\n🔠 Anti-Caps     : {s(c.get('anti_caps'))}\n👶 Anti-NewAcc   : {s(c.get('anti_newaccount'))}\n```"
        return e
    @discord.ui.button(label="Liens", emoji="🔗", style=discord.ButtonStyle.primary, row=0)
    async def al(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_link=not c.get('anti_link')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Invite", emoji="🎟️", style=discord.ButtonStyle.primary, row=0)
    async def ai(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_invite=not c.get('anti_invite')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Images", emoji="🖼️", style=discord.ButtonStyle.primary, row=0)
    async def aim(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_image=not c.get('anti_image')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Phishing", emoji="🎣", style=discord.ButtonStyle.danger, row=1)
    async def ap(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_phishing=not c.get('anti_phishing')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Scam", emoji="🚨", style=discord.ButtonStyle.danger, row=1)
    async def asc(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_scam=not c.get('anti_scam')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Spam", emoji="📨", style=discord.ButtonStyle.secondary, row=2)
    async def asp(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_spam=not c.get('anti_spam')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Mention", emoji="📢", style=discord.ButtonStyle.secondary, row=2)
    async def am(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_mention_spam=not c.get('anti_mention_spam')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Caps", emoji="🔠", style=discord.ButtonStyle.secondary, row=2)
    async def ac(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_caps=not c.get('anti_caps')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="NewAcc", emoji="👶", style=discord.ButtonStyle.danger, row=3)
    async def ana(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, anti_newaccount=not c.get('anti_newaccount')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, i, b): v = MainPanel(self.u, self.g); await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👑 IMMUNITÉS + 👋 BIENVENUE + 📊 ACTIVITÉ
# ═══════════════════════════════════════════════════════════════════════════════

class ImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
            sel = Select(placeholder="👑 Ajouter...", options=opts, row=1); sel.callback = self.add; self.add_item(sel)
    async def add(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES (?,?)', (self.g.id, int(i.data['values'][0])))
            await db.commit()
        await i.response.send_message("✅", ephemeral=True)
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,))
            ir = [self.g.get_role(r[0]) for r in await cur.fetchall() if self.g.get_role(r[0])]
        e = discord.Embed(title="👑 Immunités", color=C.GOLD)
        e.description = f"```yml\n{', '.join([r.name for r in ir]) or 'Aucun'}\n```"
        return e
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b): v = MainPanel(self.u, self.g); await i.response.edit_message(embed=v.embed(), view=v)

class WelcPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        channels = [c for c in g.text_channels][:25]
        if channels:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
            sel = Select(placeholder="👋 Salon...", options=opts, row=2); sel.callback = self.ch; self.add_item(sel)
    async def ch(self, i): await scfg(self.g.id, welcome_channel=int(i.data['values'][0])); await i.response.send_message("✅", ephemeral=True)
    async def embed(self):
        c = await gcfg(self.g.id)
        ch = self.g.get_channel(c.get('welcome_channel'))
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"```yml\nÉtat: {'✅' if c.get('welcome_on') else '❌'}\nSalon: {f'#{ch.name}' if ch else '❌'}\n```"
        return e
    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def tog(self, i, b): c = await gcfg(self.g.id); await scfg(self.g.id, welcome_on=not c.get('welcome_on')); await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Message", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def msg(self, i, b): await i.response.send_modal(WelcMsgM(self.g))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b): v = MainPanel(self.u, self.g); await i.response.edit_message(embed=v.embed(), view=v)

class WelcMsgM(Modal, title="✏️ Message"):
    msg = TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=500)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i): await scfg(self.g.id, welcome_msg=self.msg.value); await i.response.send_message("✅", ephemeral=True)

class ActPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        self.i7, self.i30 = [], []
    async def embed(self):
        n = now()
        d7, d30 = n - timedelta(days=7), n - timedelta(days=30)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM activity WHERE guild_id=?', (self.g.id,))
            act = {r['user_id']: dict(r) for r in await cur.fetchall()}
        self.i7, self.i30 = [], []
        for m in self.g.members:
            if m.bot: continue
            a = act.get(m.id)
            if not a or (not a['last_message'] and not a['last_voice']):
                self.i7.append(m); self.i30.append(m); continue
            lm = lv = None
            try:
                if a['last_message']: lm = datetime.fromisoformat(a['last_message'].replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
                if a['last_voice']: lv = datetime.fromisoformat(a['last_voice'].replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
            except: pass
            last = max([x for x in [lm, lv] if x], default=None)
            if not last or last < d30: self.i7.append(m); self.i30.append(m)
            elif last < d7: self.i7.append(m)
        e = discord.Embed(title="📊 Activité", color=C.ORANGE)
        e.description = f"```yml\n⚠️ Inactifs 7j : {len(self.i7)}\n🔴 Inactifs 30j: {len(self.i30)}\n```"
        return e
    @discord.ui.button(label="7j", emoji="⚠️", style=discord.ButtonStyle.primary, row=0)
    async def b7(self, i, b): v = InactList(self.u, self.g, 7, self.i7); await i.response.edit_message(embed=v.embed(), view=v)
    @discord.ui.button(label="30j", emoji="🔴", style=discord.ButtonStyle.danger, row=0)
    async def b30(self, i, b): v = InactList(self.u, self.g, 30, self.i30); await i.response.edit_message(embed=v.embed(), view=v)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b): v = MainPanel(self.u, self.g); await i.response.edit_message(embed=v.embed(), view=v)

class InactList(View):
    def __init__(self, u, g, d, m):
        super().__init__(timeout=900)
        self.u, self.g, self.d, self.all_members, self.page = u, g, d, m, 0
    def embed(self):
        start, end = self.page * 20, (self.page + 1) * 20
        lst = "\n".join([f"• {x.display_name}" for x in self.all_members[start:end]])
        e = discord.Embed(title=f"Inactifs {self.d}j ({len(self.all_members)})", color=C.ORANGE)
        e.description = f"```\n{lst or 'Aucun'}\n```"
        return e
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev(self, i, b):
        if self.page > 0: self.page -= 1
        await i.response.edit_message(embed=self.embed(), view=self)
    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, i, b):
        if (self.page + 1) * 20 < len(self.all_members): self.page += 1
        await i.response.edit_message(embed=self.embed(), view=self)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ActPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

class TicketPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        cats = [c for c in g.categories][:25]
        if cats:
            opts = [discord.SelectOption(label=c.name[:25], value=str(c.id)) for c in cats]
            sel = Select(placeholder="📁 Catégorie...", options=opts, row=2); sel.callback = self.cat; self.add_item(sel)
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
            sel = Select(placeholder="👮 Staff...", options=opts, row=3); sel.callback = self.rol; self.add_item(sel)
    async def cat(self, i): await stcfg(self.g.id, category_id=int(i.data['values'][0])); await i.response.send_message("✅", ephemeral=True)
    async def rol(self, i): await stcfg(self.g.id, staff_role_id=int(i.data['values'][0])); await i.response.send_message("✅", ephemeral=True)
    async def embed(self):
        tc = await gtcfg(self.g.id)
        cat, rl = self.g.get_channel(tc['category_id']), self.g.get_role(tc['staff_role_id'])
        e = discord.Embed(title="🎫 Tickets", color=C.PURPLE)
        e.description = f"```yml\n📁 Catégorie: {cat.name if cat else '❌'}\n👮 Staff: {'@'+rl.name if rl else '❌'}\n```"
        return e
    @discord.ui.button(label="📤 Déployer", style=discord.ButtonStyle.success, row=0)
    async def deploy(self, i, b): v = DeployPanel(self.u, self.g); await i.response.edit_message(embed=v.embed(), view=v)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b): v = MainPanel(self.u, self.g); await i.response.edit_message(embed=v.embed(), view=v)

class DeployPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u, self.g = u, g
        channels = [c for c in g.text_channels][:25]
        if channels:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in channels]
            sel = Select(placeholder="📤 Salon...", options=opts); sel.callback = self.deploy; self.add_item(sel)
    def embed(self): return discord.Embed(title="📤 Déployer", color=C.GREEN)
    async def deploy(self, i):
        tc = await gtcfg(self.g.id)
        if not tc['category_id'] or not tc['staff_role_id']:
            return await i.response.send_message("❌ Configurez catégorie et staff", ephemeral=True)
        ch = self.g.get_channel(int(i.data['values'][0]))
        e = discord.Embed(title=tc['panel_title'], description=tc['panel_description'], color=C.PURPLE)
        if self.g.icon: e.set_thumbnail(url=self.g.icon.url)
        await ch.send(embed=e, view=TkBtn(self.g.id))
        await i.response.send_message(f"✅ Déployé dans {ch.mention}", ephemeral=True)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b): v = TicketPanel(self.u, self.g); await i.response.edit_message(embed=await v.embed(), view=v)

class TkBtn(View):
    def __init__(self, gid):
        super().__init__(timeout=None)
        self.gid = gid
    @discord.ui.button(label="📩 Créer un ticket", style=discord.ButtonStyle.success, custom_id="tk_create")
    async def cr(self, i, b): await make_ticket(i, {})

async def make_ticket(i, ans):
    tc = await gtcfg(i.guild.id)
    cat, rl = i.guild.get_channel(tc['category_id']), i.guild.get_role(tc['staff_role_id'])
    if not cat or not rl: return await i.response.send_message("❌", ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=?', (i.guild.id,))
        n = (await cur.fetchone())[0] + 1
    nm = re.sub(r'[^a-z0-9-]', '', f"ticket-{i.user.name.lower()[:10]}-{n}")[:100]
    immune = await get_ticket_immune_roles(i.guild.id)
    ow = {
        i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        rl: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }
    for rid in immune:
        role = i.guild.get_role(rid)
        if role: ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    ch = await cat.create_text_channel(name=nm, overwrites=ow)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO tickets (guild_id, channel_id, user_id, answers, created_at) VALUES (?,?,?,?,?)', (i.guild.id, ch.id, i.user.id, json.dumps(ans), now().isoformat()))
        await db.commit()
    e = discord.Embed(title="🎫 Ticket", description=f"👤 {i.user.mention}", color=C.GREEN)
    await ch.send(content=f"{i.user.mention} {rl.mention}", embed=e, view=TkActs(i.guild.id, ch.id, i.user.id))
    await i.response.send_message(f"✅ {ch.mention}", ephemeral=True)

class TkActs(View):
    def __init__(self, gid, cid, uid):
        super().__init__(timeout=None)
        self.gid, self.cid, self.uid = gid, cid, uid
    @discord.ui.button(label="🙋 Prendre", style=discord.ButtonStyle.success, custom_id="tk_claim")
    async def cl(self, i, b):
        tc = await gtcfg(i.guild.id)
        rl = i.guild.get_role(tc['staff_role_id'])
        if not rl or (rl not in i.user.roles and not i.user.guild_permissions.administrator):
            return await i.response.send_message("❌", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (i.user.id, i.channel.id))
            await db.commit()
        u = i.guild.get_member(self.uid)
        immune = await get_ticket_immune_roles(i.guild.id)
        ow = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        if u: ow[u] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        for r in i.guild.roles:
            if r.position > i.user.top_role.position and not r.is_bot_managed():
                ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        for rid in immune:
            role = i.guild.get_role(rid)
            if role: ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        await i.channel.edit(overwrites=ow)
        b.disabled, b.label = True, f"Pris par {i.user.display_name}"
        await i.response.edit_message(view=self)
        await i.channel.send(f"🙋 **{i.user.mention}** a pris ce ticket")
    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="tk_close")
    async def close(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM tickets WHERE channel_id=?', (i.channel.id,))
            ticket = await cur.fetchone()
        if not ticket: return await i.response.send_message("❌", ephemeral=True)
        ticket = dict(ticket)
        if i.user.id != ticket['claimed_by'] and i.user.id != i.guild.owner_id:
            return await i.response.send_message("❌ Seul celui qui a pris le ticket peut le fermer", ephemeral=True)
        await i.response.send_message("🔒 Fermeture...")
        await asyncio.sleep(2)
        await close_ticket(i.channel, f"Fermé par {i.user.display_name}")

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(TkBtn(0))
    bot.add_view(TkActs(0, 0, 0))
    for guild in bot.guilds:
        try: await guild.chunk(); print(f"📥 {guild.name}: {guild.member_count}")
        except: pass
    await bot.tree.sync()
    print(f"✅ {bot.user.name} connecté")
    check_social_feeds.start()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/help"))

@tasks.loop(minutes=5)
async def check_social_feeds():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM social_feeds')
        feeds = [dict(r) for r in await cur.fetchall()]
    for feed in feeds:
        try:
            guild = bot.get_guild(feed['guild_id'])
            if not guild: continue
            channel = guild.get_channel(feed['channel_id'])
            if not channel: continue
            if feed['platform'] == 'youtube':
                data = await fetch_youtube_feed(feed['account_id'])
                if data and data['videos']:
                    latest = data['videos'][0]
                    if feed['last_post_id'] != latest['id']:
                        embed = create_social_embed('youtube', {'video': latest, 'channel_name': data['channel_name']})
                        view = View(); view.add_item(Button(label="▶️ Regarder", url=latest['url'], style=discord.ButtonStyle.link))
                        await channel.send(embed=embed, view=view)
                        await update_feed_last_post(feed['id'], latest['id'])
            elif feed['platform'] == 'twitch':
                data = await fetch_twitch_status(feed['account_id'])
                if data and data['is_live'] and feed['last_post_id'] != 'live':
                    embed = create_social_embed('twitch', data)
                    view = View(); view.add_item(Button(label="🎮 Regarder", url=data['url'], style=discord.ButtonStyle.link))
                    await channel.send(embed=embed, view=view)
                    await update_feed_last_post(feed['id'], 'live')
                elif data and not data['is_live']:
                    await update_feed_last_post(feed['id'], 'offline')
            elif feed['platform'] in ['tiktok', 'instagram', 'twitter']:
                data = await fetch_rss_feed(feed['account_id'])
                if data and data['items']:
                    latest = data['items'][0]
                    if feed['last_post_id'] != latest['id']:
                        embed = create_social_embed(feed['platform'], {'post': latest, 'account_name': feed['account_name']})
                        view = View()
                        if latest.get('url'): view.add_item(Button(label="🔗 Voir", url=latest['url'], style=discord.ButtonStyle.link))
                        await channel.send(embed=embed, view=view)
                        await update_feed_last_post(feed['id'], latest['id'])
        except Exception as e:
            print(f"Feed error {feed['id']}: {e}")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    await track_message(msg.guild.id, msg.author.id, msg.channel.id)
    if await is_immune(msg.author): return
    c = await gcfg(msg.guild.id)
    content = msg.content
    if c.get('anti_phishing') and check_phishing(content):
        await msg.delete()
        try: await msg.author.timeout(timedelta(hours=1), reason="Phishing")
        except: pass
        return
    if c.get('anti_scam') and check_scam_patterns(content): await msg.delete(); return
    if c.get('anti_invite') and check_discord_invite(content): await msg.delete(); return
    if c.get('anti_link') and re.search(r'https?://[^\s]+', content): await msg.delete(); return
    if c.get('anti_image') and msg.attachments:
        for a in msg.attachments:
            if a.filename.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp')): await msg.delete(); return
    if c.get('anti_spam') and await check_spam(msg):
        await msg.delete()
        try: await msg.author.timeout(timedelta(minutes=5), reason="Spam")
        except: pass
        return
    if c.get('anti_mention_spam') and check_mass_mentions(msg):
        await msg.delete()
        try: await msg.author.timeout(timedelta(minutes=10), reason="Mention spam")
        except: pass
        return
    if c.get('anti_caps') and check_caps(content): await msg.delete(); return

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    if after.channel and not before.channel: await track_voice_start(member.guild.id, member.id, after.channel.id)
    elif before.channel and not after.channel: await track_voice_end(member.guild.id, member.id)
    elif before.channel and after.channel and before.channel != after.channel:
        await track_voice_end(member.guild.id, member.id)
        await track_voice_start(member.guild.id, member.id, after.channel.id)

@bot.event
async def on_member_join(m):
    c = await gcfg(m.guild.id)
    if c.get('anti_newaccount'):
        days = c.get('newaccount_days', 7)
        if (now() - m.created_at.replace(tzinfo=timezone.utc)).days < days:
            try: await m.kick(reason=f"Compte < {days}j")
            except: pass
            return
    if c.get('welcome_on') and c.get('welcome_channel'):
        ch = m.guild.get_channel(c['welcome_channel'])
        if ch:
            txt = c.get('welcome_msg', 'Bienvenue {member}!').format(member=m.mention, server=m.guild.name, count=m.guild.member_count)
            e = discord.Embed(title="👋 Bienvenue!", description=txt, color=C.GREEN)
            e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)

@bot.event
async def on_member_remove(m):
    if m.bot: return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (m.guild.id, m.id))
        tickets = await cur.fetchall()
    for (channel_id,) in tickets:
        channel = m.guild.get_channel(channel_id)
        if channel: await close_ticket(channel, f"Membre parti ({m.name})")
    await cleanup_member_data(m.guild.id, m.id)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDES
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Membre", raison="Raison")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not await has_permission(i.user, 'warn'): return await i.response.send_message("❌ Permission refusée", ephemeral=True)
    if await is_immune(membre): return await i.response.send_message("❌ Immunisé", ephemeral=True)
    count = await add_infraction(i.guild.id, membre.id, i.user.id, 'warn', raison)
    e = discord.Embed(title="⚠️ Warn", color=C.YELLOW)
    e.add_field(name="Membre", value=membre.mention, inline=True)
    e.add_field(name="Par", value=i.user.mention, inline=True)
    e.add_field(name="Raison", value=raison, inline=False)
    e.add_field(name="Total", value=f"{count} warn(s)", inline=True)
    await i.response.send_message(embed=e)
    c = await gcfg(i.guild.id)
    if c.get('mod_log_channel'):
        lc = i.guild.get_channel(c['mod_log_channel'])
        if lc: await lc.send(embed=e)
    wc = await get_warn_count(i.guild.id, membre.id)
    if c.get('warns_ban') and wc >= c['warns_ban']: await membre.ban(reason=f"Auto: {wc} warns")
    elif c.get('warns_kick') and wc >= c['warns_kick']: await membre.kick(reason=f"Auto: {wc} warns")

@bot.tree.command(name="timeout", description="⏰ Timeout")
@app_commands.describe(membre="Membre", duree="Durée (30s, 5m, 2h, 1d, 1w)", raison="Raison")
async def timeout_cmd(i: discord.Interaction, membre: discord.Member, duree: str, raison: str):
    if not await has_permission(i.user, 'timeout'): return await i.response.send_message("❌ Permission refusée", ephemeral=True)
    if await is_immune(membre): return await i.response.send_message("❌ Immunisé", ephemeral=True)
    seconds = parse_duration(duree)
    if not seconds: return await i.response.send_message("❌ Format: 30s, 5m, 2h, 1d, 1w", ephemeral=True)
    try: await membre.timeout(now() + timedelta(seconds=seconds), reason=raison)
    except: return await i.response.send_message("❌ Erreur", ephemeral=True)
    await add_infraction(i.guild.id, membre.id, i.user.id, 'timeout', raison, seconds)
    e = discord.Embed(title="⏰ Timeout", color=C.ORANGE)
    e.add_field(name="Membre", value=membre.mention, inline=True)
    e.add_field(name="Durée", value=format_duration(seconds), inline=True)
    e.add_field(name="Raison", value=raison, inline=False)
    await i.response.send_message(embed=e)
    c = await gcfg(i.guild.id)
    if c.get('mod_log_channel'):
        lc = i.guild.get_channel(c['mod_log_channel'])
        if lc: await lc.send(embed=e)

@bot.tree.command(name="infractions", description="📜 Voir les infractions")
@app_commands.describe(membre="Membre")
async def infractions_cmd(i: discord.Interaction, membre: discord.Member):
    if not await has_permission(i.user, 'infractions'): return await i.response.send_message("❌ Permission refusée", ephemeral=True)
    infs = await get_infractions(i.guild.id, membre.id)
    e = discord.Embed(title=f"📜 {membre.display_name}", color=C.RED)
    if not infs: e.description = "✅ Aucune infraction"
    else:
        e.description = f"**{len(infs)}** infraction(s)\n"
        for idx, inf in enumerate(infs[:10]):
            mod = i.guild.get_member(inf['mod_id'])
            e.add_field(name=f"{'⚠️' if inf['type']=='warn' else '⏰'} #{idx+1}", value=f"{inf['reason'][:50]}\nPar: {mod.display_name if mod else '?'}", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="configure", description="⚙️ Configuration (Admin)")
async def cfg_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Admin requis", ephemeral=True)
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.embed(), view=v, ephemeral=True)

if __name__ == "__main__":
    print("🚀 Démarrage...")
    bot.run(TOKEN)
