# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v9.2 🌟                                 ║
# ║     Protection Configurable + Tickets + Network                               ║
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
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PINK=0xEB459E; PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22

PHISHING_DOMAINS = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com','discordi.gift','discord-app.com','discordapp.co','discrod.com','dlscord.org','discordc.gift','discord-airdrop.com','steamcommunity.ru','steamcommunitiy.com','steamcomunity.com','store-steampowered.com','discord-give.com','discord-free.com','nitro-discord.com']
SCAM_PATTERNS = [r'free\s*nitro',r'discord\s*nitro\s*free',r'steam\s*gift',r'claim\s*your\s*gift',r'@everyone.*http',r'@here.*http',r'won\s*a?\s*nitro']

def now(): return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY,
                log_channel INTEGER, mod_log_channel INTEGER, ticket_log_channel INTEGER, welcome_channel INTEGER,
                warns_kick INTEGER DEFAULT 0, warns_ban INTEGER DEFAULT 0,
                -- Protection ON/OFF
                anti_link INTEGER DEFAULT 0, anti_invite INTEGER DEFAULT 0, anti_image INTEGER DEFAULT 0,
                anti_phishing INTEGER DEFAULT 1, anti_scam INTEGER DEFAULT 1, anti_spam INTEGER DEFAULT 0,
                anti_mention INTEGER DEFAULT 0, anti_caps INTEGER DEFAULT 0, anti_newaccount INTEGER DEFAULT 0,
                -- Config Anti-Liens
                link_action TEXT DEFAULT 'delete', link_timeout INTEGER DEFAULT 5, link_whitelist TEXT DEFAULT 'youtube.com,twitter.com,discord.com',
                -- Config Anti-Invite
                invite_action TEXT DEFAULT 'delete', invite_timeout INTEGER DEFAULT 5,
                -- Config Anti-Image
                image_action TEXT DEFAULT 'delete',
                -- Config Anti-Phishing
                phishing_action TEXT DEFAULT 'ban', phishing_timeout INTEGER DEFAULT 60,
                -- Config Anti-Scam
                scam_action TEXT DEFAULT 'timeout', scam_timeout INTEGER DEFAULT 30,
                -- Config Anti-Spam
                spam_max_msg INTEGER DEFAULT 5, spam_interval INTEGER DEFAULT 5, spam_action TEXT DEFAULT 'timeout', spam_timeout INTEGER DEFAULT 5,
                -- Config Anti-Mention
                mention_max INTEGER DEFAULT 5, mention_action TEXT DEFAULT 'timeout', mention_timeout INTEGER DEFAULT 10,
                -- Config Anti-Caps
                caps_percent INTEGER DEFAULT 70, caps_min_len INTEGER DEFAULT 10, caps_action TEXT DEFAULT 'delete',
                -- Config Anti-NewAccount
                newaccount_days INTEGER DEFAULT 7, newaccount_action TEXT DEFAULT 'kick',
                -- Welcome
                welcome_on INTEGER DEFAULT 0, welcome_msg TEXT DEFAULT 'Bienvenue {member} !'
            );
            CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id));
            CREATE TABLE IF NOT EXISTS ticket_config (guild_id INTEGER PRIMARY KEY, category_id INTEGER, staff_role_id INTEGER, panel_title TEXT DEFAULT '🎫 Support', panel_description TEXT DEFAULT 'Cliquez pour créer un ticket');
            CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, claimed_by INTEGER, status TEXT DEFAULT 'open', created_at DATETIME DEFAULT CURRENT_TIMESTAMP, closed_at DATETIME, closed_reason TEXT);
            CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, duration INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS role_permissions (guild_id INTEGER, role_id INTEGER, permission TEXT, PRIMARY KEY(guild_id,role_id,permission));
            CREATE TABLE IF NOT EXISTS activity (guild_id INTEGER, user_id INTEGER, last_message DATETIME, last_voice DATETIME, PRIMARY KEY(guild_id,user_id));
            CREATE TABLE IF NOT EXISTS social_feeds (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, platform TEXT, account_id TEXT, account_name TEXT, channel_id INTEGER, last_post_id TEXT);
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
            try: await db.execute(f'UPDATE config SET {k}=? WHERE guild_id=?', (v,gid))
            except Exception as e: print(f"scfg error: {e}")
        await db.commit()

async def is_immune(m):
    if m.guild_permissions.administrator or m.id == m.guild.owner_id: return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,))
        ids = [r[0] for r in await cur.fetchall()]
    return any(r.id in ids for r in m.roles)

async def apply_action(member, action, timeout_min, reason):
    try:
        if action == 'delete': pass
        elif action == 'timeout' and timeout_min > 0:
            await member.timeout(timedelta(minutes=timeout_min), reason=reason)
        elif action == 'kick':
            await member.kick(reason=reason)
        elif action == 'ban':
            await member.ban(reason=reason, delete_message_days=1)
    except Exception as e: print(f"Action error: {e}")

async def add_infraction(gid, uid, mod_id, itype, reason, duration=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions (guild_id,user_id,mod_id,type,reason,duration) VALUES (?,?,?,?,?,?)', (gid,uid,mod_id,itype,reason,duration))
        await db.commit()

async def has_permission(member, perm):
    if member.guild_permissions.administrator or member.id == member.guild.owner_id: return True
    async with aiosqlite.connect(DB_PATH) as db:
        for r in member.roles:
            cur = await db.execute('SELECT 1 FROM role_permissions WHERE guild_id=? AND role_id=? AND permission=?', (member.guild.id,r.id,perm))
            if await cur.fetchone(): return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def check_link(content, whitelist=''):
    urls = re.findall(r'https?://([^\s/]+)', content.lower())
    if not urls: return False
    allowed = [d.strip().lower() for d in whitelist.split(',') if d.strip()]
    for url in urls:
        if not any(a in url for a in allowed): return True
    return False

def check_invite(content):
    return bool(re.search(r'(discord\.gg|discord\.com/invite)/[a-zA-Z0-9]+', content))

def check_phishing(content):
    return any(d in content.lower() for d in PHISHING_DOMAINS)

def check_scam(content):
    return any(re.search(p, content, re.I) for p in SCAM_PATTERNS)

def check_caps(content, percent=70, min_len=10):
    if len(content) < min_len: return False
    letters = [c for c in content if c.isalpha()]
    if not letters: return False
    return (sum(1 for c in letters if c.isupper()) / len(letters) * 100) >= percent

def check_mentions(msg, max_m=5):
    return len(msg.mentions) >= max_m or msg.mention_everyone

async def check_spam(msg, max_msg=5, interval=5):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker: spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n-t).total_seconds() < interval]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > max_msg

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
        if self.g.icon: e.set_thumbnail(url=self.g.icon.url)
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
    
    @discord.ui.button(label="Network", emoji="🌐", style=discord.ButtonStyle.primary, row=2)
    async def netw(self, i, b):
        v = NetworkPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g

    async def interaction_check(self, i):
        return i.user.id == self.u.id

    async def embed(self):
        c = await gcfg(self.g.id)
        def s(k): return "✅" if c.get(k) else "❌"
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = f"""```yml
🔗 Anti-Liens    : {s('anti_link')}  │ {c.get('link_action','delete')} ({c.get('link_timeout',5)}min)
🎟️ Anti-Invite   : {s('anti_invite')}  │ {c.get('invite_action','delete')} ({c.get('invite_timeout',5)}min)
🖼️ Anti-Images   : {s('anti_image')}  │ {c.get('image_action','delete')}
🎣 Anti-Phishing : {s('anti_phishing')}  │ {c.get('phishing_action','ban')} ({c.get('phishing_timeout',60)}min)
🚨 Anti-Scam     : {s('anti_scam')}  │ {c.get('scam_action','timeout')} ({c.get('scam_timeout',30)}min)
📨 Anti-Spam     : {s('anti_spam')}  │ {c.get('spam_max_msg',5)}msg/{c.get('spam_interval',5)}s
📢 Anti-Mention  : {s('anti_mention')}  │ max {c.get('mention_max',5)} mentions
🔠 Anti-Caps     : {s('anti_caps')}  │ {c.get('caps_percent',70)}% (min {c.get('caps_min_len',10)} chars)
👶 Anti-NewAcc   : {s('anti_newaccount')}  │ {c.get('newaccount_days',7)} jours → {c.get('newaccount_action','kick')}
```
**Cliquez sur un bouton pour activer/désactiver**
**⚙️ = Configurer les paramètres détaillés**"""
        return e

    async def toggle(self, i, key):
        c = await gcfg(self.g.id)
        new_val = 0 if c.get(key) else 1
        await scfg(self.g.id, **{key: new_val})
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="Liens", emoji="🔗", style=discord.ButtonStyle.primary, row=0)
    async def b_link(self, i, b): await self.toggle(i, 'anti_link')

    @discord.ui.button(label="Invite", emoji="🎟️", style=discord.ButtonStyle.primary, row=0)
    async def b_invite(self, i, b): await self.toggle(i, 'anti_invite')

    @discord.ui.button(label="Images", emoji="🖼️", style=discord.ButtonStyle.primary, row=0)
    async def b_image(self, i, b): await self.toggle(i, 'anti_image')

    @discord.ui.button(label="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def cfg1(self, i, b): await i.response.send_modal(LinkConfigModal(self.g))

    @discord.ui.button(label="Phishing", emoji="🎣", style=discord.ButtonStyle.danger, row=1)
    async def b_phish(self, i, b): await self.toggle(i, 'anti_phishing')

    @discord.ui.button(label="Scam", emoji="🚨", style=discord.ButtonStyle.danger, row=1)
    async def b_scam(self, i, b): await self.toggle(i, 'anti_scam')

    @discord.ui.button(label="⚙️", style=discord.ButtonStyle.secondary, row=1)
    async def cfg2(self, i, b): await i.response.send_modal(PhishScamConfigModal(self.g))

    @discord.ui.button(label="Spam", emoji="📨", style=discord.ButtonStyle.secondary, row=2)
    async def b_spam(self, i, b): await self.toggle(i, 'anti_spam')

    @discord.ui.button(label="Mention", emoji="📢", style=discord.ButtonStyle.secondary, row=2)
    async def b_mention(self, i, b): await self.toggle(i, 'anti_mention')

    @discord.ui.button(label="Caps", emoji="🔠", style=discord.ButtonStyle.secondary, row=2)
    async def b_caps(self, i, b): await self.toggle(i, 'anti_caps')

    @discord.ui.button(label="⚙️", style=discord.ButtonStyle.secondary, row=2)
    async def cfg3(self, i, b): await i.response.send_modal(SpamMentionCapsConfigModal(self.g))

    @discord.ui.button(label="NewAcc", emoji="👶", style=discord.ButtonStyle.danger, row=3)
    async def b_new(self, i, b): await self.toggle(i, 'anti_newaccount')

    @discord.ui.button(label="⚙️ NewAcc", style=discord.ButtonStyle.secondary, row=3)
    async def cfg4(self, i, b): await i.response.send_modal(NewAccConfigModal(self.g))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚙️ CONFIG MODALS
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfigModal(Modal, title="🔗 Config Liens/Invite/Images"):
    link_action = TextInput(label="Action Liens (delete/timeout/kick/ban)", placeholder="delete", default="delete", max_length=10)
    link_timeout = TextInput(label="Timeout Liens (minutes)", placeholder="5", default="5", max_length=5)
    link_whitelist = TextInput(label="Domaines autorisés (séparés par ,)", placeholder="youtube.com, twitter.com", default="youtube.com,twitter.com,discord.com", style=discord.TextStyle.paragraph, max_length=500)
    invite_action = TextInput(label="Action Invite (delete/timeout/kick/ban)", placeholder="delete", default="delete", max_length=10)
    
    def __init__(self, g): super().__init__(); self.g = g
    
    async def on_submit(self, i):
        la = self.link_action.value.lower() if self.link_action.value.lower() in ['delete','timeout','kick','ban'] else 'delete'
        lt = int(self.link_timeout.value) if self.link_timeout.value.isdigit() else 5
        lw = self.link_whitelist.value
        ia = self.invite_action.value.lower() if self.invite_action.value.lower() in ['delete','timeout','kick','ban'] else 'delete'
        await scfg(self.g.id, link_action=la, link_timeout=lt, link_whitelist=lw, invite_action=ia)
        await i.response.send_message(f"✅ **Configuré**\n🔗 Liens: `{la}` (timeout {lt}min)\n📝 Whitelist: `{lw}`\n🎟️ Invite: `{ia}`", ephemeral=True)

class PhishScamConfigModal(Modal, title="🎣 Config Phishing/Scam"):
    phish_action = TextInput(label="Action Phishing (delete/timeout/kick/ban)", placeholder="ban", default="ban", max_length=10)
    phish_timeout = TextInput(label="Timeout Phishing (minutes)", placeholder="60", default="60", max_length=5)
    scam_action = TextInput(label="Action Scam (delete/timeout/kick/ban)", placeholder="timeout", default="timeout", max_length=10)
    scam_timeout = TextInput(label="Timeout Scam (minutes)", placeholder="30", default="30", max_length=5)
    
    def __init__(self, g): super().__init__(); self.g = g
    
    async def on_submit(self, i):
        pa = self.phish_action.value.lower() if self.phish_action.value.lower() in ['delete','timeout','kick','ban'] else 'ban'
        pt = int(self.phish_timeout.value) if self.phish_timeout.value.isdigit() else 60
        sa = self.scam_action.value.lower() if self.scam_action.value.lower() in ['delete','timeout','kick','ban'] else 'timeout'
        st = int(self.scam_timeout.value) if self.scam_timeout.value.isdigit() else 30
        await scfg(self.g.id, phishing_action=pa, phishing_timeout=pt, scam_action=sa, scam_timeout=st)
        await i.response.send_message(f"✅ **Configuré**\n🎣 Phishing: `{pa}` ({pt}min)\n🚨 Scam: `{sa}` ({st}min)", ephemeral=True)

class SpamMentionCapsConfigModal(Modal, title="📨 Config Spam/Mention/Caps"):
    spam_max = TextInput(label="Spam: Max messages", placeholder="5", default="5", max_length=3)
    spam_interval = TextInput(label="Spam: Intervalle (secondes)", placeholder="5", default="5", max_length=3)
    mention_max = TextInput(label="Mention: Max mentions", placeholder="5", default="5", max_length=3)
    caps_percent = TextInput(label="Caps: Pourcentage max (%)", placeholder="70", default="70", max_length=3)
    caps_min = TextInput(label="Caps: Longueur min message", placeholder="10", default="10", max_length=3)
    
    def __init__(self, g): super().__init__(); self.g = g
    
    async def on_submit(self, i):
        sm = int(self.spam_max.value) if self.spam_max.value.isdigit() else 5
        si = int(self.spam_interval.value) if self.spam_interval.value.isdigit() else 5
        mm = int(self.mention_max.value) if self.mention_max.value.isdigit() else 5
        cp = int(self.caps_percent.value) if self.caps_percent.value.isdigit() else 70
        cm = int(self.caps_min.value) if self.caps_min.value.isdigit() else 10
        await scfg(self.g.id, spam_max_msg=sm, spam_interval=si, mention_max=mm, caps_percent=cp, caps_min_len=cm)
        await i.response.send_message(f"✅ **Configuré**\n📨 Spam: `{sm}msg/{si}s`\n📢 Mention: max `{mm}`\n🔠 Caps: `{cp}%` (min `{cm}` chars)", ephemeral=True)

class NewAccConfigModal(Modal, title="👶 Config Nouveaux Comptes"):
    days = TextInput(label="Âge minimum (jours)", placeholder="7", default="7", max_length=4)
    action = TextInput(label="Action (kick/ban)", placeholder="kick", default="kick", max_length=10)
    
    def __init__(self, g): super().__init__(); self.g = g
    
    async def on_submit(self, i):
        d = int(self.days.value) if self.days.value.isdigit() else 7
        a = self.action.value.lower() if self.action.value.lower() in ['kick','ban'] else 'kick'
        await scfg(self.g.id, newaccount_days=d, newaccount_action=a)
        await i.response.send_message(f"✅ Comptes < `{d}` jours → `{a}`", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📜 LOGS + ⚖️ SANCTIONS + 👑 IMMUNITÉS
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        chs = [c for c in g.text_channels][:25]
        if chs:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
            s1=Select(placeholder="📝 Logs généraux...",options=opts,row=1);s1.callback=self.l1;self.add_item(s1)
            s2=Select(placeholder="⚔️ Logs modération...",options=opts.copy(),row=2);s2.callback=self.l2;self.add_item(s2)
            s3=Select(placeholder="🎫 Logs tickets...",options=opts.copy(),row=3);s3.callback=self.l3;self.add_item(s3)
    async def l1(self,i): await scfg(self.g.id,log_channel=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def l2(self,i): await scfg(self.g.id,mod_log_channel=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def l3(self,i): await scfg(self.g.id,ticket_log_channel=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def embed(self):
        c = await gcfg(self.g.id)
        lc,mc,tc = self.g.get_channel(c.get('log_channel')), self.g.get_channel(c.get('mod_log_channel')), self.g.get_channel(c.get('ticket_log_channel'))
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        e.description = f"📝 Généraux: {lc.mention if lc else '❌'}\n⚔️ Modération: {mc.mention if mc else '❌'}\n🎫 Tickets: {tc.mention if tc else '❌'}"
        return e
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=4)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class SanctPanel(View):
    def __init__(self, u, g): super().__init__(timeout=900); self.u,self.g = u,g
    async def embed(self):
        c = await gcfg(self.g.id)
        e = discord.Embed(title="⚖️ Sanctions Auto", color=C.PINK)
        wk,wb = c.get('warns_kick',0), c.get('warns_ban',0)
        e.description = f"👢 Kick après: **{wk} warns** {'(off)' if not wk else ''}\n🔨 Ban après: **{wb} warns** {'(off)' if not wb else ''}"
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
        await i.response.send_message(f"✅ Kick: {k} warns | Ban: {b} warns", ephemeral=True)

class ImmunePanel(View):
    def __init__(self,u,g):
        super().__init__(timeout=900); self.u,self.g = u,g
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            opts = [discord.SelectOption(label=f"@{r.name}"[:25],value=str(r.id)) for r in roles]
            sel = Select(placeholder="👑 Ajouter un rôle immunisé...",options=opts,row=1); sel.callback=self.add; self.add_item(sel)
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
        e.description = ", ".join([r.mention for r in roles]) if roles else "Aucun rôle immunisé"
        return e
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class WelcPanel(View):
    def __init__(self,u,g):
        super().__init__(timeout=900); self.u,self.g = u,g
        chs = [c for c in g.text_channels][:25]
        if chs:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25],value=str(c.id)) for c in chs]
            sel = Select(placeholder="👋 Salon bienvenue...",options=opts,row=2); sel.callback=self.ch; self.add_item(sel)
    async def ch(self,i): await scfg(self.g.id,welcome_channel=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def embed(self):
        c = await gcfg(self.g.id)
        ch = self.g.get_channel(c.get('welcome_channel'))
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"État: {'✅ Activé' if c.get('welcome_on') else '❌ Désactivé'}\nSalon: {ch.mention if ch else '❌'}\nMessage: `{c.get('welcome_msg','Bienvenue {member}!')[:50]}...`"
        return e
    @discord.ui.button(label="ON/OFF",emoji="🔄",style=discord.ButtonStyle.primary,row=0)
    async def tog(self,i,b): c=await gcfg(self.g.id); await scfg(self.g.id,welcome_on=0 if c.get('welcome_on') else 1); await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="Message",emoji="✏️",style=discord.ButtonStyle.primary,row=0)
    async def msg(self,i,b): await i.response.send_modal(WelcMsgModal(self.g))
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class WelcMsgModal(Modal, title="✏️ Message de bienvenue"):
    msg = TextInput(label="Message ({member}, {server}, {count})", style=discord.TextStyle.paragraph, max_length=500, default="Bienvenue {member} sur {server} ! 🎉")
    def __init__(self,g): super().__init__(); self.g=g
    async def on_submit(self,i): await scfg(self.g.id,welcome_msg=self.msg.value); await i.response.send_message("✅",ephemeral=True)

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
        return {'guild_id':gid,'category_id':None,'staff_role_id':None,'panel_title':'🎫 Support','panel_description':'Cliquez pour créer un ticket'}

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
            sel = Select(placeholder="📁 Catégorie...",options=opts,row=2); sel.callback=self.cat; self.add_item(sel)
        roles = [r for r in g.roles[1:] if not r.is_bot_managed()][:25]
        if roles:
            opts = [discord.SelectOption(label=f"@{r.name}"[:25],value=str(r.id)) for r in roles]
            sel = Select(placeholder="👮 Staff...",options=opts,row=3); sel.callback=self.rol; self.add_item(sel)
    async def cat(self,i): await stcfg(self.g.id,category_id=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def rol(self,i): await stcfg(self.g.id,staff_role_id=int(i.data['values'][0])); await i.response.send_message("✅",ephemeral=True)
    async def embed(self):
        tc = await gtcfg(self.g.id)
        cat,rl = self.g.get_channel(tc.get('category_id')), self.g.get_role(tc.get('staff_role_id'))
        e = discord.Embed(title="🎫 Tickets", color=C.PURPLE)
        e.description = f"📁 Catégorie: {cat.name if cat else '❌'}\n👮 Staff: {rl.mention if rl else '❌'}"
        return e
    @discord.ui.button(label="📤 Déployer",style=discord.ButtonStyle.success,row=0)
    async def deploy(self,i,b): v=DeployPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class DeployPanel(View):
    def __init__(self,u,g):
        super().__init__(timeout=300); self.u,self.g = u,g
        chs = [c for c in g.text_channels][:25]
        if chs:
            opts = [discord.SelectOption(label=f"#{c.name}"[:25],value=str(c.id)) for c in chs]
            sel = Select(placeholder="📤 Salon...",options=opts); sel.callback=self.deploy; self.add_item(sel)
    def embed(self): return discord.Embed(title="📤 Déployer le panel",color=C.GREEN)
    async def deploy(self,i):
        tc = await gtcfg(self.g.id)
        if not tc.get('category_id') or not tc.get('staff_role_id'): return await i.response.send_message("❌ Config incomplète",ephemeral=True)
        ch = self.g.get_channel(int(i.data['values'][0]))
        e = discord.Embed(title=tc.get('panel_title','🎫 Support'),description=tc.get('panel_description','Cliquez pour créer un ticket'),color=C.PURPLE)
        await ch.send(embed=e,view=TkBtn(self.g.id))
        await i.response.send_message(f"✅ Déployé dans {ch.mention}",ephemeral=True)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b): v=TicketPanel(self.u,self.g); await i.response.edit_message(embed=await v.embed(),view=v)

class TkBtn(View):
    def __init__(self,gid): super().__init__(timeout=None); self.gid=gid
    @discord.ui.button(label="📩 Créer un ticket",style=discord.ButtonStyle.success,custom_id="tk_create")
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
        e = discord.Embed(title="🎫 Ticket",description=f"👤 {i.user.mention}",color=C.GREEN)
        await ch.send(content=f"{i.user.mention} {rl.mention}",embed=e,view=TkActs())
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
#                           🌐 NETWORK
# ═══════════════════════════════════════════════════════════════════════════════

PLATFORMS = {'youtube':{'emoji':'📺','color':0xFF0000},'twitter':{'emoji':'🐦','color':0x1DA1F2},'twitch':{'emoji':'🎮','color':0x9146FF},'tiktok':{'emoji':'🎵','color':0x010101},'instagram':{'emoji':'📸','color':0xE1306C}}

class NetworkPanel(View):
    def __init__(self,u,g): super().__init__(timeout=900); self.u,self.g = u,g
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM social_feeds WHERE guild_id=?', (self.g.id,))
            feeds = [dict(r) for r in await cur.fetchall()]
        counts = {}
        for f in feeds: counts[f['platform']] = counts.get(f['platform'],0)+1
        e = discord.Embed(title="🌐 Network",color=C.BLURPLE)
        desc = "".join([f"{PLATFORMS[p]['emoji']} {p.title()}: **{c}**\n" for p,c in counts.items()]) or "Aucun flux configuré"
        e.description = desc + "\n⚠️ TikTok/Instagram: utilisez rss.app"
        return e
    @discord.ui.button(label="YouTube",emoji="📺",style=discord.ButtonStyle.danger,row=0)
    async def yt(self,i,b): await i.response.send_modal(AddFeedModal(self.g,'youtube'))
    @discord.ui.button(label="Twitter",emoji="🐦",style=discord.ButtonStyle.primary,row=0)
    async def tw(self,i,b): await i.response.send_modal(AddFeedModal(self.g,'twitter'))
    @discord.ui.button(label="Twitch",emoji="🎮",style=discord.ButtonStyle.secondary,row=0)
    async def ttv(self,i,b): await i.response.send_modal(AddFeedModal(self.g,'twitch'))
    @discord.ui.button(label="TikTok",emoji="🎵",style=discord.ButtonStyle.secondary,row=1)
    async def tt(self,i,b): await i.response.send_modal(AddFeedModal(self.g,'tiktok'))
    @discord.ui.button(label="Instagram",emoji="📸",style=discord.ButtonStyle.secondary,row=1)
    async def ig(self,i,b): await i.response.send_modal(AddFeedModal(self.g,'instagram'))
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b): v=MainPanel(self.u,self.g); await i.response.edit_message(embed=v.embed(),view=v)

class AddFeedModal(Modal):
    def __init__(self,g,platform):
        super().__init__(title=f"Ajouter {platform.title()}")
        self.g,self.platform = g,platform
        self.account = TextInput(label="ID/Username/URL RSS",placeholder="UCxxxxx ou @username ou URL RSS",max_length=200)
        self.add_item(self.account)
        self.channel = TextInput(label="ID du salon Discord",placeholder="Clic droit > Copier l'ID",max_length=20)
        self.add_item(self.channel)
    async def on_submit(self,i):
        try:
            ch_id = int(self.channel.value)
            ch = i.guild.get_channel(ch_id)
            if not ch: return await i.response.send_message("❌ Salon introuvable",ephemeral=True)
        except: return await i.response.send_message("❌ ID invalide",ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO social_feeds (guild_id,platform,account_id,account_name,channel_id) VALUES (?,?,?,?,?)', (i.guild.id,self.platform,self.account.value,self.account.value[:20],ch_id))
            await db.commit()
        await i.response.send_message(f"✅ {PLATFORMS[self.platform]['emoji']} **{self.account.value[:20]}** → {ch.mention}",ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(TkBtn(0))
    bot.add_view(TkActs())
    await bot.tree.sync()
    print(f"✅ {bot.user.name} prêt!")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    if await is_immune(msg.author): return
    
    c = await gcfg(msg.guild.id)
    content = msg.content
    
    # 🎣 Anti-Phishing (priorité max)
    if c.get('anti_phishing') and check_phishing(content):
        await msg.delete()
        await apply_action(msg.author, c.get('phishing_action','ban'), c.get('phishing_timeout',60), "Phishing")
        return
    
    # 🚨 Anti-Scam
    if c.get('anti_scam') and check_scam(content):
        await msg.delete()
        await apply_action(msg.author, c.get('scam_action','timeout'), c.get('scam_timeout',30), "Scam")
        return
    
    # 🎟️ Anti-Invite
    if c.get('anti_invite') and check_invite(content):
        await msg.delete()
        await apply_action(msg.author, c.get('invite_action','delete'), c.get('invite_timeout',5), "Invitation Discord")
        return
    
    # 🔗 Anti-Liens
    if c.get('anti_link') and check_link(content, c.get('link_whitelist','')):
        await msg.delete()
        await apply_action(msg.author, c.get('link_action','delete'), c.get('link_timeout',5), "Lien interdit")
        return
    
    # 🖼️ Anti-Images
    if c.get('anti_image') and msg.attachments:
        for a in msg.attachments:
            if a.filename.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp')):
                await msg.delete()
                return
    
    # 📨 Anti-Spam
    if c.get('anti_spam') and await check_spam(msg, c.get('spam_max_msg',5), c.get('spam_interval',5)):
        await msg.delete()
        await apply_action(msg.author, c.get('spam_action','timeout'), c.get('spam_timeout',5), "Spam")
        return
    
    # 📢 Anti-Mention
    if c.get('anti_mention') and check_mentions(msg, c.get('mention_max',5)):
        await msg.delete()
        await apply_action(msg.author, c.get('mention_action','timeout'), c.get('mention_timeout',10), "Mass mention")
        return
    
    # 🔠 Anti-Caps
    if c.get('anti_caps') and check_caps(content, c.get('caps_percent',70), c.get('caps_min_len',10)):
        await msg.delete()
        return

@bot.event
async def on_member_join(m):
    c = await gcfg(m.guild.id)
    # 👶 Anti-NewAccount
    if c.get('anti_newaccount'):
        days = c.get('newaccount_days',7)
        age = (now() - m.created_at.replace(tzinfo=timezone.utc)).days
        if age < days:
            action = c.get('newaccount_action','kick')
            if action == 'ban':
                try: await m.ban(reason=f"Compte trop récent ({age}j < {days}j)")
                except: pass
            else:
                try: await m.kick(reason=f"Compte trop récent ({age}j < {days}j)")
                except: pass
            return
    # 👋 Welcome
    if c.get('welcome_on') and c.get('welcome_channel'):
        ch = m.guild.get_channel(c['welcome_channel'])
        if ch:
            txt = c.get('welcome_msg','Bienvenue {member}!').format(member=m.mention,server=m.guild.name,count=m.guild.member_count)
            e = discord.Embed(title="👋 Bienvenue!",description=txt,color=C.GREEN)
            e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDES
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Configuration du bot")
async def cfg_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Admin requis",ephemeral=True)
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.embed(),view=v,ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Membre",raison="Raison")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not await has_permission(i.user,'warn'): return await i.response.send_message("❌",ephemeral=True)
    if await is_immune(membre): return await i.response.send_message("❌ Immunisé",ephemeral=True)
    await add_infraction(i.guild.id,membre.id,i.user.id,'warn',raison)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type='warn'", (i.guild.id,membre.id))
        count = (await cur.fetchone())[0]
    e = discord.Embed(title="⚠️ Warn",color=C.YELLOW)
    e.add_field(name="Membre",value=membre.mention)
    e.add_field(name="Raison",value=raison)
    e.add_field(name="Total",value=f"{count} warn(s)")
    await i.response.send_message(embed=e)
    c = await gcfg(i.guild.id)
    if c.get('warns_ban') and count >= c['warns_ban']: await membre.ban(reason=f"Auto: {count} warns")
    elif c.get('warns_kick') and count >= c['warns_kick']: await membre.kick(reason=f"Auto: {count} warns")

@bot.tree.command(name="timeout", description="⏰ Timeout un membre")
@app_commands.describe(membre="Membre",duree="Durée (ex: 5m, 1h, 1d)",raison="Raison")
async def timeout_cmd(i: discord.Interaction, membre: discord.Member, duree: str, raison: str):
    if not await has_permission(i.user,'timeout'): return await i.response.send_message("❌",ephemeral=True)
    if await is_immune(membre): return await i.response.send_message("❌ Immunisé",ephemeral=True)
    match = re.match(r'^(\d+)([smhd])$', duree.lower())
    if not match: return await i.response.send_message("❌ Format: 5m, 1h, 1d",ephemeral=True)
    val,unit = int(match.group(1)), match.group(2)
    mult = {'s':1,'m':60,'h':3600,'d':86400}
    secs = val * mult[unit]
    await membre.timeout(timedelta(seconds=secs),reason=raison)
    await add_infraction(i.guild.id,membre.id,i.user.id,'timeout',raison,secs)
    await i.response.send_message(f"⏰ {membre.mention} timeout {duree} - {raison}")

if __name__ == "__main__":
    print("🚀 Démarrage v9.2...")
    bot.run(TOKEN)
