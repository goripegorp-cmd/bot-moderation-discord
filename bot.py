# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT PREMIUM v6.0 🌟                                 ║
# ║                    Avec système de statistiques                               ║
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
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
DB = 'database.db'

# Sessions vocales en cours (pour calculer le temps)
voice_sessions = {}  # {(guild_id, user_id): datetime}

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

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.executescript('''
            CREATE TABLE IF NOT EXISTS config (
                guild_id INTEGER PRIMARY KEY, log_channel INTEGER, mod_log_channel INTEGER,
                welcome_channel INTEGER, mute_role INTEGER, warns_mute INTEGER DEFAULT 0,
                warns_kick INTEGER DEFAULT 0, warns_ban INTEGER DEFAULT 0, anti_link INTEGER DEFAULT 0,
                anti_image INTEGER DEFAULT 0, anti_phishing INTEGER DEFAULT 1, anti_spam INTEGER DEFAULT 0,
                welcome_on INTEGER DEFAULT 0, welcome_msg TEXT DEFAULT 'Bienvenue {member} !');
            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
                mod_id INTEGER, reason TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id));
            CREATE TABLE IF NOT EXISTS staff_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id));
            CREATE TABLE IF NOT EXISTS activity (
                guild_id INTEGER, user_id INTEGER, last_message DATETIME, last_voice DATETIME,
                PRIMARY KEY (guild_id, user_id));
            CREATE TABLE IF NOT EXISTS ticket_config (
                guild_id INTEGER PRIMARY KEY, category_id INTEGER, staff_role_id INTEGER,
                ticket_name TEXT DEFAULT 'ticket-{user}-{number}', panel_title TEXT DEFAULT '🎫 Support',
                panel_description TEXT DEFAULT 'Cliquez pour créer un ticket', questions TEXT DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER,
                user_id INTEGER, claimed_by INTEGER, status TEXT DEFAULT 'open', answers TEXT);
            
            -- 🆕 STATS MESSAGES (par jour)
            CREATE TABLE IF NOT EXISTS message_stats (
                guild_id INTEGER, user_id INTEGER, date TEXT, count INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, date));
            
            -- 🆕 STATS VOCAL (secondes par jour)
            CREATE TABLE IF NOT EXISTS voice_stats (
                guild_id INTEGER, user_id INTEGER, date TEXT, seconds INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, date));
        ''')
        await db.commit()
    print("✅ DB OK")

async def gcfg(gid):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM config WHERE guild_id=?', (gid,))
        r = await cur.fetchone()
        if r: return dict(r)
        await db.execute('INSERT OR IGNORE INTO config (guild_id) VALUES (?)', (gid,))
        await db.commit()
        return {'guild_id': gid, 'log_channel': None, 'mod_log_channel': None, 'welcome_channel': None,
                'mute_role': None, 'warns_mute': 0, 'warns_kick': 0, 'warns_ban': 0,
                'anti_link': 0, 'anti_image': 0, 'anti_phishing': 1, 'anti_spam': 0,
                'welcome_on': 0, 'welcome_msg': 'Bienvenue {member} !'}

async def scfg(gid, **kw):
    async with aiosqlite.connect(DB) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE config SET {k}=? WHERE guild_id=?', (v, gid))
        await db.commit()

async def gtcfg(gid):
    async with aiosqlite.connect(DB) as db:
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
    async with aiosqlite.connect(DB) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE ticket_config SET {k}=? WHERE guild_id=?', (v, gid))
        await db.commit()

# 🆕 Tracking messages
async def track_message(gid, uid):
    today = datetime.utcnow().strftime('%Y-%m-%d')
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB) as db:
        # Update activity
        await db.execute('INSERT OR IGNORE INTO activity (guild_id, user_id) VALUES (?,?)', (gid, uid))
        await db.execute('UPDATE activity SET last_message=? WHERE guild_id=? AND user_id=?', (now, gid, uid))
        # Update message stats
        await db.execute('INSERT OR IGNORE INTO message_stats (guild_id, user_id, date, count) VALUES (?,?,?,0)', (gid, uid, today))
        await db.execute('UPDATE message_stats SET count = count + 1 WHERE guild_id=? AND user_id=? AND date=?', (gid, uid, today))
        await db.commit()

# 🆕 Tracking vocal
async def track_voice_start(gid, uid):
    voice_sessions[(gid, uid)] = datetime.utcnow()
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB) as db:
        await db.execute('INSERT OR IGNORE INTO activity (guild_id, user_id) VALUES (?,?)', (gid, uid))
        await db.execute('UPDATE activity SET last_voice=? WHERE guild_id=? AND user_id=?', (now, gid, uid))
        await db.commit()

async def track_voice_end(gid, uid):
    key = (gid, uid)
    if key not in voice_sessions:
        return
    start = voice_sessions.pop(key)
    duration = (datetime.utcnow() - start).total_seconds()
    today = datetime.utcnow().strftime('%Y-%m-%d')
    async with aiosqlite.connect(DB) as db:
        await db.execute('INSERT OR IGNORE INTO voice_stats (guild_id, user_id, date, seconds) VALUES (?,?,?,0)', (gid, uid, today))
        await db.execute('UPDATE voice_stats SET seconds = seconds + ? WHERE guild_id=? AND user_id=? AND date=?', (int(duration), gid, uid, today))
        await db.commit()

# 🆕 Récupérer les stats
async def get_user_stats(gid, uid):
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    stats = {
        'msg_today': 0, 'msg_week': 0, 'msg_month': 0, 'msg_total': 0,
        'voice_today': 0, 'voice_week': 0, 'voice_month': 0, 'voice_total': 0,
        'msg_by_day': [], 'voice_by_day': []
    }
    
    async with aiosqlite.connect(DB) as db:
        # Messages par jour (7 derniers jours)
        for i in range(6, -1, -1):
            d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            cur = await db.execute('SELECT count FROM message_stats WHERE guild_id=? AND user_id=? AND date=?', (gid, uid, d))
            r = await cur.fetchone()
            stats['msg_by_day'].append(r[0] if r else 0)
        
        # Voice par jour (7 derniers jours)
        for i in range(6, -1, -1):
            d = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            cur = await db.execute('SELECT seconds FROM voice_stats WHERE guild_id=? AND user_id=? AND date=?', (gid, uid, d))
            r = await cur.fetchone()
            stats['voice_by_day'].append(r[0] if r else 0)
        
        # Messages aujourd'hui
        cur = await db.execute('SELECT count FROM message_stats WHERE guild_id=? AND user_id=? AND date=?', 
                              (gid, uid, today.strftime('%Y-%m-%d')))
        r = await cur.fetchone()
        stats['msg_today'] = r[0] if r else 0
        
        # Messages cette semaine
        cur = await db.execute('SELECT SUM(count) FROM message_stats WHERE guild_id=? AND user_id=? AND date>=?',
                              (gid, uid, week_start.strftime('%Y-%m-%d')))
        r = await cur.fetchone()
        stats['msg_week'] = r[0] or 0
        
        # Messages ce mois
        cur = await db.execute('SELECT SUM(count) FROM message_stats WHERE guild_id=? AND user_id=? AND date>=?',
                              (gid, uid, month_start.strftime('%Y-%m-%d')))
        r = await cur.fetchone()
        stats['msg_month'] = r[0] or 0
        
        # Messages total
        cur = await db.execute('SELECT SUM(count) FROM message_stats WHERE guild_id=? AND user_id=?', (gid, uid))
        r = await cur.fetchone()
        stats['msg_total'] = r[0] or 0
        
        # Voice aujourd'hui
        cur = await db.execute('SELECT seconds FROM voice_stats WHERE guild_id=? AND user_id=? AND date=?',
                              (gid, uid, today.strftime('%Y-%m-%d')))
        r = await cur.fetchone()
        stats['voice_today'] = r[0] if r else 0
        
        # Voice cette semaine
        cur = await db.execute('SELECT SUM(seconds) FROM voice_stats WHERE guild_id=? AND user_id=? AND date>=?',
                              (gid, uid, week_start.strftime('%Y-%m-%d')))
        r = await cur.fetchone()
        stats['voice_week'] = r[0] or 0
        
        # Voice ce mois
        cur = await db.execute('SELECT SUM(seconds) FROM voice_stats WHERE guild_id=? AND user_id=? AND date>=?',
                              (gid, uid, month_start.strftime('%Y-%m-%d')))
        r = await cur.fetchone()
        stats['voice_month'] = r[0] or 0
        
        # Voice total
        cur = await db.execute('SELECT SUM(seconds) FROM voice_stats WHERE guild_id=? AND user_id=?', (gid, uid))
        r = await cur.fetchone()
        stats['voice_total'] = r[0] or 0
    
    return stats

async def is_immune(m):
    if m.id == m.guild.owner_id: return True
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,))
        ids = [r[0] for r in await cur.fetchall()]
    return any(r.id in ids for r in m.roles)

async def is_staff(m):
    if m.id == m.guild.owner_id or m.guild_permissions.administrator: return True
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id=?', (m.guild.id,))
        ids = [r[0] for r in await cur.fetchall()]
    return any(r.id in ids for r in m.roles)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 HELPERS STATS
# ═══════════════════════════════════════════════════════════════════════════════

def format_time(seconds):
    """Convertit les secondes en format lisible"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"

def make_bar(value, max_value, length=10):
    """Crée une barre de progression"""
    if max_value == 0:
        filled = 0
    else:
        filled = int((value / max_value) * length)
    empty = length - filled
    return "█" * filled + "░" * empty

def make_graph(data, height=5):
    """Crée un graphique ASCII des 7 derniers jours"""
    if not data or max(data) == 0:
        return "```\nPas de données\n```"
    
    max_val = max(data)
    days = ['L', 'M', 'M', 'J', 'V', 'S', 'D']
    today_idx = datetime.utcnow().weekday()
    
    # Ajuster les labels pour les 7 derniers jours
    labels = []
    for i in range(7):
        day_idx = (today_idx - 6 + i) % 7
        labels.append(days[day_idx])
    
    graph = "```\n"
    
    # Dessiner le graphique
    for row in range(height, 0, -1):
        threshold = (row / height) * max_val
        line = ""
        for val in data:
            if val >= threshold:
                line += " ▓▓"
            else:
                line += " ░░"
        graph += f"{line}\n"
    
    # Ligne de base
    graph += " ──" * len(data) + "\n"
    
    # Labels des jours
    graph += " " + "  ".join(labels) + "\n"
    graph += "```"
    
    return graph

def get_activity_level(msg_week, voice_week):
    """Détermine le niveau d'activité"""
    score = msg_week + (voice_week / 60)  # 1 minute de vocal = 1 message
    
    if score >= 500:
        return "🔥 Hyperactif", "Vous êtes partout !", C.RED
    elif score >= 200:
        return "⭐ Très actif", "Excellente participation !", C.GOLD
    elif score >= 100:
        return "✨ Actif", "Bonne activité !", C.GREEN
    elif score >= 30:
        return "📊 Modéré", "Activité correcte", C.BLUE
    elif score >= 10:
        return "💤 Peu actif", "Vous pouvez faire mieux !", C.ORANGE
    else:
        return "👻 Fantôme", "On vous voit peu...", C.PURPLE

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
        e.description = f"""```yml
╔════════════════════════════════════════╗
║      🎛️ CENTRE DE CONTRÔLE            ║
╚════════════════════════════════════════╝

👥 Membres : {self.g.member_count}

📂 Catégories
──────────────────────────────────────────
⚔️ Modération   │ 📜 Logs
🛡️ Protection   │ 👥 Rôles  
👋 Bienvenue    │ 📊 Activité
🎫 Tickets
──────────────────────────────────────────
```"""
        if self.g.icon: e.set_thumbnail(url=self.g.icon.url)
        e.set_footer(text=f"👤 {self.u.display_name}", icon_url=self.u.display_avatar.url)
        return e
    
    @discord.ui.button(label="Modération", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def b1(self, i, b):
        await i.response.defer()
        v = ModPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def b2(self, i, b):
        await i.response.defer()
        v = LogsPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def b3(self, i, b):
        await i.response.defer()
        v = ProtPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Rôles", emoji="👥", style=discord.ButtonStyle.secondary, row=1)
    async def b4(self, i, b):
        await i.response.defer()
        v = RolesPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def b5(self, i, b):
        await i.response.defer()
        v = WelcPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Activité", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
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
#                           ⚔️ MODERATION
# ═══════════════════════════════════════════════════════════════════════════════

class ModPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        c = await gcfg(self.g.id)
        mr = self.g.get_role(c['mute_role'])
        e = discord.Embed(title="⚔️ Modération", color=C.PINK)
        e.description = f"""```yml
🔇 Rôle Mute : {mr.name if mr else '❌'}

⚖️ Sanctions Auto
──────────────────────────────────────────
Mute : {f'{c["warns_mute"]} warns' if c['warns_mute'] else 'Off'}
Kick : {f'{c["warns_kick"]} warns' if c['warns_kick'] else 'Off'}
Ban  : {f'{c["warns_ban"]} warns' if c['warns_ban'] else 'Off'}
```"""
        return e
    
    @discord.ui.button(label="Warn", emoji="⚠️", style=discord.ButtonStyle.danger, row=0)
    async def w(self, i, b): await i.response.send_modal(WarnM(self.g, self.u))
    @discord.ui.button(label="Mute", emoji="🔇", style=discord.ButtonStyle.danger, row=0)
    async def m(self, i, b): await i.response.send_modal(MuteM(self.g, self.u))
    @discord.ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.danger, row=0)
    async def k(self, i, b): await i.response.send_modal(KickM(self.g, self.u))
    @discord.ui.button(label="Ban", emoji="🔨", style=discord.ButtonStyle.danger, row=0)
    async def ba(self, i, b): await i.response.send_modal(BanM(self.g, self.u))
    @discord.ui.button(label="Sanctions Auto", emoji="⚖️", style=discord.ButtonStyle.primary, row=1)
    async def sa(self, i, b): await i.response.send_modal(SanctM(self.g))
    @discord.ui.button(label="Rôle Mute", emoji="🎭", style=discord.ButtonStyle.primary, row=1)
    async def rm(self, i, b): await i.response.send_modal(MuteRM(self.g))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class WarnM(Modal, title="⚠️ Warn"):
    mid = TextInput(label="ID membre", max_length=20)
    rsn = TextInput(label="Raison", required=False)
    def __init__(self, g, m): super().__init__(); self.g, self.m = g, m
    async def on_submit(self, i):
        try:
            mb = self.g.get_member(int(self.mid.value))
            if not mb: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            if await is_immune(mb): return await i.response.send_message("❌ Immunisé", ephemeral=True)
            r = self.rsn.value or "Aucune raison"
            async with aiosqlite.connect(DB) as db:
                await db.execute('INSERT INTO warns (guild_id,user_id,mod_id,reason) VALUES (?,?,?,?)', (self.g.id,mb.id,self.m.id,r))
                await db.commit()
                cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?', (self.g.id,mb.id))
                cnt = (await cur.fetchone())[0]
            await i.response.send_message(f"✅ **{mb}** warn #{cnt}", ephemeral=True)
            c = await gcfg(self.g.id)
            if c['warns_ban'] and cnt >= c['warns_ban']: await mb.ban(reason=f"Auto: {cnt} warns")
            elif c['warns_kick'] and cnt >= c['warns_kick']: await mb.kick(reason=f"Auto: {cnt} warns")
            elif c['warns_mute'] and cnt >= c['warns_mute']:
                rl = self.g.get_role(c['mute_role'])
                if rl: await mb.add_roles(rl)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class MuteM(Modal, title="🔇 Mute"):
    mid = TextInput(label="ID membre", max_length=20)
    def __init__(self, g, m): super().__init__(); self.g, self.m = g, m
    async def on_submit(self, i):
        try:
            mb = self.g.get_member(int(self.mid.value))
            if not mb: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            c = await gcfg(self.g.id)
            rl = self.g.get_role(c['mute_role'])
            if not rl: return await i.response.send_message("❌ Rôle mute non configuré", ephemeral=True)
            await mb.add_roles(rl)
            await i.response.send_message(f"✅ **{mb}** mute", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class KickM(Modal, title="👢 Kick"):
    mid = TextInput(label="ID membre", max_length=20)
    rsn = TextInput(label="Raison", required=False)
    def __init__(self, g, m): super().__init__(); self.g, self.m = g, m
    async def on_submit(self, i):
        try:
            mb = self.g.get_member(int(self.mid.value))
            if not mb: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            if await is_immune(mb): return await i.response.send_message("❌ Immunisé", ephemeral=True)
            await mb.kick(reason=self.rsn.value or "Aucune")
            await i.response.send_message(f"✅ **{mb}** kick", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class BanM(Modal, title="🔨 Ban"):
    mid = TextInput(label="ID membre", max_length=20)
    rsn = TextInput(label="Raison", required=False)
    def __init__(self, g, m): super().__init__(); self.g, self.m = g, m
    async def on_submit(self, i):
        try:
            mb = self.g.get_member(int(self.mid.value))
            if not mb: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            if await is_immune(mb): return await i.response.send_message("❌ Immunisé", ephemeral=True)
            await mb.ban(reason=self.rsn.value or "Aucune")
            await i.response.send_message(f"✅ **{mb}** ban", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class SanctM(Modal, title="⚖️ Sanctions"):
    wm = TextInput(label="Warns pour Mute (0=off)", required=False, max_length=2)
    wk = TextInput(label="Warns pour Kick (0=off)", required=False, max_length=2)
    wb = TextInput(label="Warns pour Ban (0=off)", required=False, max_length=2)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        m = int(self.wm.value) if self.wm.value.isdigit() else 0
        k = int(self.wk.value) if self.wk.value.isdigit() else 0
        b = int(self.wb.value) if self.wb.value.isdigit() else 0
        await scfg(self.g.id, warns_mute=m, warns_kick=k, warns_ban=b)
        await i.response.send_message(f"✅ Mute:{m} Kick:{k} Ban:{b}", ephemeral=True)

class MuteRM(Modal, title="🎭 Rôle Mute"):
    rid = TextInput(label="ID du rôle", max_length=20)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        try:
            rl = self.g.get_role(int(self.rid.value))
            if not rl: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            await scfg(self.g.id, mute_role=rl.id)
            await i.response.send_message(f"✅ Rôle mute: **{rl.name}**", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📜 LOGS
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        c = await gcfg(self.g.id)
        lc = self.g.get_channel(c['log_channel'])
        mc = self.g.get_channel(c['mod_log_channel'])
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        e.description = f"""```yml
📝 Généraux   : {lc.name if lc else '❌'}
⚔️ Modération : {mc.name if mc else '❌'}
```"""
        return e
    
    @discord.ui.button(label="Logs Généraux", emoji="📝", style=discord.ButtonStyle.primary)
    async def lg(self, i, b): await i.response.send_modal(LogM(self.g, "log_channel"))
    @discord.ui.button(label="Logs Modération", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def lm(self, i, b): await i.response.send_modal(LogM(self.g, "mod_log_channel"))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class LogM(Modal, title="📝 Salon"):
    cid = TextInput(label="ID du salon", max_length=20)
    def __init__(self, g, k): super().__init__(); self.g, self.k = g, k
    async def on_submit(self, i):
        try:
            ch = self.g.get_channel(int(self.cid.value))
            if not ch: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            await scfg(self.g.id, **{self.k: ch.id})
            await i.response.send_message(f"✅ #{ch.name}", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        c = await gcfg(self.g.id)
        s = lambda v: "✅" if v else "❌"
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = f"""```yml
🔗 Anti-Liens    : {s(c['anti_link'])}
🖼️ Anti-Images   : {s(c['anti_image'])}
🎣 Anti-Phishing : {s(c['anti_phishing'])}
📨 Anti-Spam     : {s(c['anti_spam'])}
```"""
        return e
    
    @discord.ui.button(label="Anti-Liens", emoji="🔗", style=discord.ButtonStyle.primary)
    async def al(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_link=not c['anti_link'])
        await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Anti-Images", emoji="🖼️", style=discord.ButtonStyle.primary)
    async def ai(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_image=not c['anti_image'])
        await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Anti-Phishing", emoji="🎣", style=discord.ButtonStyle.primary)
    async def ap(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_phishing=not c['anti_phishing'])
        await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Anti-Spam", emoji="📨", style=discord.ButtonStyle.primary)
    async def asp(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, anti_spam=not c['anti_spam'])
        await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👥 ROLES
# ═══════════════════════════════════════════════════════════════════════════════

class RolesPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id=?', (self.g.id,))
            sr = [self.g.get_role(r[0]) for r in await cur.fetchall() if self.g.get_role(r[0])]
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,))
            ir = [self.g.get_role(r[0]) for r in await cur.fetchall() if self.g.get_role(r[0])]
        e = discord.Embed(title="👥 Rôles", color=C.ORANGE)
        e.description = f"""```yml
👮 Staff    : {', '.join([r.name for r in sr]) or 'Aucun'}
👑 Immunisés: {', '.join([r.name for r in ir]) or 'Aucun'}
```"""
        return e
    
    @discord.ui.button(label="+ Staff", emoji="👮", style=discord.ButtonStyle.success)
    async def as_(self, i, b): await i.response.send_modal(AddRM(self.g, "staff_roles"))
    @discord.ui.button(label="- Staff", emoji="👮", style=discord.ButtonStyle.danger)
    async def rs(self, i, b): await i.response.send_modal(RemRM(self.g, "staff_roles"))
    @discord.ui.button(label="+ Immunisé", emoji="👑", style=discord.ButtonStyle.success)
    async def aiu(self, i, b): await i.response.send_modal(AddRM(self.g, "immune_roles"))
    @discord.ui.button(label="- Immunisé", emoji="👑", style=discord.ButtonStyle.danger)
    async def ri(self, i, b): await i.response.send_modal(RemRM(self.g, "immune_roles"))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class AddRM(Modal, title="➕ Ajouter"):
    rid = TextInput(label="ID du rôle", max_length=20)
    def __init__(self, g, t): super().__init__(); self.g, self.t = g, t
    async def on_submit(self, i):
        try:
            rl = self.g.get_role(int(self.rid.value))
            if not rl: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            async with aiosqlite.connect(DB) as db:
                await db.execute(f'INSERT OR IGNORE INTO {self.t} VALUES (?,?)', (self.g.id, rl.id))
                await db.commit()
            await i.response.send_message(f"✅ **{rl.name}** ajouté", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class RemRM(Modal, title="➖ Retirer"):
    rid = TextInput(label="ID du rôle", max_length=20)
    def __init__(self, g, t): super().__init__(); self.g, self.t = g, t
    async def on_submit(self, i):
        try:
            async with aiosqlite.connect(DB) as db:
                await db.execute(f'DELETE FROM {self.t} WHERE guild_id=? AND role_id=?', (self.g.id, int(self.rid.value)))
                await db.commit()
            await i.response.send_message("✅ Retiré", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👋 BIENVENUE
# ═══════════════════════════════════════════════════════════════════════════════

class WelcPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
    
    async def embed(self):
        c = await gcfg(self.g.id)
        ch = self.g.get_channel(c['welcome_channel'])
        e = discord.Embed(title="👋 Bienvenue", color=C.GREEN)
        e.description = f"""```yml
État  : {'✅' if c['welcome_on'] else '❌'}
Salon : {ch.name if ch else '❌'}
Message : {c['welcome_msg'][:50]}...
```"""
        return e
    
    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary)
    async def tog(self, i, b):
        c = await gcfg(self.g.id); await scfg(self.g.id, welcome_on=not c['welcome_on'])
        await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="Salon", emoji="📝", style=discord.ButtonStyle.primary)
    async def ch(self, i, b): await i.response.send_modal(WelcChM(self.g))
    @discord.ui.button(label="Message", emoji="✏️", style=discord.ButtonStyle.primary)
    async def msg(self, i, b): await i.response.send_modal(WelcMsgM(self.g))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class WelcChM(Modal, title="📝 Salon"):
    cid = TextInput(label="ID du salon", max_length=20)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        try:
            ch = self.g.get_channel(int(self.cid.value))
            if not ch: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            await scfg(self.g.id, welcome_channel=ch.id)
            await i.response.send_message(f"✅ #{ch.name}", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class WelcMsgM(Modal, title="✏️ Message"):
    msg = TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=500)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        await scfg(self.g.id, welcome_msg=self.msg.value)
        await i.response.send_message("✅", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 ACTIVITÉ (ADMIN)
# ═══════════════════════════════════════════════════════════════════════════════

class ActPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=900)
        self.u, self.g = u, g
        self.i7, self.i30 = [], []
    
    async def embed(self):
        now = datetime.utcnow()
        d7, d30 = now - timedelta(days=7), now - timedelta(days=30)
        
        async with aiosqlite.connect(DB) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM activity WHERE guild_id=?', (self.g.id,))
            act = {r['user_id']: dict(r) for r in await cur.fetchall()}
        
        self.i7, self.i30 = [], []
        for m in self.g.members:
            if m.bot: continue
            a = act.get(m.id)
            if not a:
                self.i7.append(m); self.i30.append(m)
                continue
            lm = datetime.fromisoformat(a['last_message']) if a['last_message'] else None
            lv = datetime.fromisoformat(a['last_voice']) if a['last_voice'] else None
            last = max(filter(None, [lm, lv]), default=None)
            if not last or last < d30:
                self.i30.append(m); self.i7.append(m)
            elif last < d7:
                self.i7.append(m)
        
        e = discord.Embed(title="📊 Activité (Admin)", color=C.ORANGE)
        e.description = f"""```yml
👥 Membres : {self.g.member_count}
⚠️ Inactifs 7j  : {len(self.i7)}
🔴 Inactifs 30j : {len(self.i30)}
```"""
        return e
    
    @discord.ui.button(label="Inactifs 7j", emoji="⚠️", style=discord.ButtonStyle.primary)
    async def b7(self, i, b):
        v = InactList(self.u, self.g, 7, self.i7)
        await i.response.edit_message(embed=v.embed(), view=v)
    @discord.ui.button(label="Inactifs 30j", emoji="🔴", style=discord.ButtonStyle.danger)
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
        self.u, self.g, self.d, self.m = u, g, d, m[:100]
    
    def embed(self):
        lst = "\n".join([f"• {x.name}" for x in self.m[:15]])
        if len(self.m) > 15: lst += f"\n... +{len(self.m)-15}"
        e = discord.Embed(title=f"{'⚠️' if self.d==7 else '🔴'} Inactifs {self.d}j", color=C.ORANGE if self.d==7 else C.RED)
        e.description = f"**{len(self.m)} membres**\n```\n{lst or 'Aucun 🎉'}\n```"
        return e
    
    @discord.ui.button(label="📢 Mentionner", emoji="📢", style=discord.ButtonStyle.primary)
    async def ment(self, i, b):
        if not self.m: return await i.response.send_message("❌", ephemeral=True)
        await i.response.send_message(f"📢 **Inactifs {self.d}j:**\n{' '.join([x.mention for x in self.m[:40]])}")
    @discord.ui.button(label="👢 Expulser", emoji="👢", style=discord.ButtonStyle.danger)
    async def kick(self, i, b):
        if not self.m: return await i.response.send_message("❌", ephemeral=True)
        v = ConfKick(self.u, self.g, self.m, self.d)
        await i.response.edit_message(embed=discord.Embed(title="⚠️ Confirmer?", description=f"Expulser **{len(self.m)}** membres?", color=C.RED), view=v)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        await i.response.defer()
        v = ActPanel(self.u, self.g)
        await i.edit_original_response(embed=await v.embed(), view=v)

class ConfKick(View):
    def __init__(self, u, g, m, d):
        super().__init__(timeout=60)
        self.u, self.g, self.m, self.d = u, g, m, d
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def yes(self, i, b):
        await i.response.defer()
        ok, fail = 0, 0
        for m in self.m:
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
    
    async def embed(self):
        tc = await gtcfg(self.g.id)
        cat = self.g.get_channel(tc['category_id'])
        rl = self.g.get_role(tc['staff_role_id'])
        qs = json.loads(tc['questions']) if tc['questions'] else []
        e = discord.Embed(title="🎫 Tickets", color=C.PURPLE)
        e.description = f"""```yml
📁 Catégorie  : {cat.name if cat else '❌'}
👮 Rôle Staff : {rl.name if rl else '❌'}
📝 Format     : {tc['ticket_name']}

❓ Questions ({len(qs)}/5)
{chr(10).join([f'{i+1}. {q}' for i,q in enumerate(qs)]) or 'Aucune'}
```"""
        return e
    
    @discord.ui.button(label="Catégorie", emoji="📁", style=discord.ButtonStyle.primary, row=0)
    async def cat(self, i, b): await i.response.send_modal(TkCatM(self.g))
    @discord.ui.button(label="Rôle Staff", emoji="👮", style=discord.ButtonStyle.primary, row=0)
    async def rl(self, i, b): await i.response.send_modal(TkRoleM(self.g))
    @discord.ui.button(label="Format Nom", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def nm(self, i, b): await i.response.send_modal(TkNameM(self.g))
    @discord.ui.button(label="+ Question", emoji="❓", style=discord.ButtonStyle.secondary, row=1)
    async def aq(self, i, b): await i.response.send_modal(TkAddQM(self.g))
    @discord.ui.button(label="Clear Questions", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def cq(self, i, b):
        await stcfg(self.g.id, questions='[]')
        await i.response.edit_message(embed=await self.embed(), view=self)
    @discord.ui.button(label="📤 Déployer", emoji="📤", style=discord.ButtonStyle.success, row=2)
    async def dep(self, i, b): await i.response.send_modal(TkDeployM(self.g))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class TkCatM(Modal, title="📁 Catégorie"):
    cid = TextInput(label="ID catégorie", max_length=20)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        try:
            c = self.g.get_channel(int(self.cid.value))
            if not c or not isinstance(c, discord.CategoryChannel): return await i.response.send_message("❌", ephemeral=True)
            await stcfg(self.g.id, category_id=c.id)
            await i.response.send_message(f"✅ {c.name}", ephemeral=True)
        except: await i.response.send_message("❌", ephemeral=True)

class TkRoleM(Modal, title="👮 Rôle Staff"):
    rid = TextInput(label="ID rôle", max_length=20)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        try:
            r = self.g.get_role(int(self.rid.value))
            if not r: return await i.response.send_message("❌", ephemeral=True)
            await stcfg(self.g.id, staff_role_id=r.id)
            await i.response.send_message(f"✅ {r.name}", ephemeral=True)
        except: await i.response.send_message("❌", ephemeral=True)

class TkNameM(Modal, title="📝 Format"):
    nm = TextInput(label="Format", placeholder="ticket-{user}-{number}", default="ticket-{user}-{number}")
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        await stcfg(self.g.id, ticket_name=self.nm.value)
        await i.response.send_message(f"✅ {self.nm.value}", ephemeral=True)

class TkAddQM(Modal, title="❓ Question"):
    q = TextInput(label="Question", max_length=100)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        tc = await gtcfg(self.g.id)
        qs = json.loads(tc['questions']) if tc['questions'] else []
        if len(qs) >= 5: return await i.response.send_message("❌ Max 5", ephemeral=True)
        qs.append(self.q.value)
        await stcfg(self.g.id, questions=json.dumps(qs))
        await i.response.send_message("✅", ephemeral=True)

class TkDeployM(Modal, title="📤 Déployer"):
    cid = TextInput(label="ID salon", max_length=20)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        try:
            ch = self.g.get_channel(int(self.cid.value))
            if not ch: return await i.response.send_message("❌", ephemeral=True)
            tc = await gtcfg(self.g.id)
            if not tc['category_id'] or not tc['staff_role_id']:
                return await i.response.send_message("❌ Config d'abord", ephemeral=True)
            e = discord.Embed(title=tc['panel_title'], description=tc['panel_description'], color=C.PURPLE)
            if self.g.icon: e.set_thumbnail(url=self.g.icon.url)
            await ch.send(embed=e, view=TkBtn(self.g.id))
            await i.response.send_message(f"✅ #{ch.name}", ephemeral=True)
        except: await i.response.send_message("❌", ephemeral=True)

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

class TkFormM(Modal, title="📩 Ticket"):
    def __init__(self, g, qs):
        super().__init__()
        self.g, self.qs = g, qs
        for idx, q in enumerate(qs[:5]):
            self.add_item(TextInput(label=q[:45], style=discord.TextStyle.paragraph, max_length=500, custom_id=f"q{idx}"))
    async def on_submit(self, i):
        ans = {self.qs[idx]: self.children[idx].value for idx in range(len(self.qs[:5]))}
        await make_ticket(i, ans)

async def make_ticket(i, ans):
    tc = await gtcfg(i.guild.id)
    cat, rl = i.guild.get_channel(tc['category_id']), i.guild.get_role(tc['staff_role_id'])
    if not cat or not rl: return await i.response.send_message("❌", ephemeral=True)
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=?', (i.guild.id,))
        n = (await cur.fetchone())[0] + 1
    nm = tc['ticket_name'].format(user=i.user.name.lower()[:10], number=n)
    nm = re.sub(r'[^a-z0-9-]', '', nm)[:100]
    ow = {
        i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        rl: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }
    ch = await cat.create_text_channel(name=nm, overwrites=ow)
    async with aiosqlite.connect(DB) as db:
        await db.execute('INSERT INTO tickets (guild_id,channel_id,user_id,answers) VALUES (?,?,?,?)', (i.guild.id,ch.id,i.user.id,json.dumps(ans)))
        await db.commit()
    e = discord.Embed(title="🎫 Ticket", description=f"👤 **{i.user}**", color=C.GREEN)
    if ans:
        for q, a in ans.items(): e.add_field(name=f"❓ {q}", value=f"```{a[:200]}```", inline=False)
    await ch.send(content=f"{i.user.mention} {rl.mention}", embed=e, view=TkActs(i.guild.id, ch.id, i.user.id))
    await i.response.send_message(f"✅ {ch.mention}", ephemeral=True)

class TkActs(View):
    def __init__(self, gid, cid, uid):
        super().__init__(timeout=None)
        self.gid, self.cid, self.uid = gid, cid, uid
    @discord.ui.button(label="🙋 Prendre", emoji="🙋", style=discord.ButtonStyle.success, custom_id="tk_claim")
    async def cl(self, i, b):
        tc = await gtcfg(i.guild.id)
        rl = i.guild.get_role(tc['staff_role_id'])
        if not rl or (rl not in i.user.roles and not i.user.guild_permissions.administrator):
            return await i.response.send_message("❌", ephemeral=True)
        async with aiosqlite.connect(DB) as db:
            await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (i.user.id, i.channel.id))
            await db.commit()
        u = i.guild.get_member(self.uid)
        ow = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            u: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        for r in i.guild.roles:
            if r.position > i.user.top_role.position and not r.is_bot_managed():
                ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        await i.channel.edit(overwrites=ow)
        b.disabled, b.label, b.style = True, f"Pris par {i.user.name}", discord.ButtonStyle.secondary
        await i.response.edit_message(view=self)
        await i.channel.send(f"🙋 **{i.user}** a pris ce ticket")
    @discord.ui.button(label="🔒 Fermer", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tk_close")
    async def close(self, i, b):
        tc = await gtcfg(i.guild.id)
        rl = i.guild.get_role(tc['staff_role_id'])
        ok = (rl and rl in i.user.roles) or i.user.guild_permissions.administrator or i.user.id == self.uid
        if not ok: return await i.response.send_message("❌", ephemeral=True)
        await i.response.send_message("🔒 Fermeture...")
        async with aiosqlite.connect(DB) as db:
            await db.execute('UPDATE tickets SET status="closed" WHERE channel_id=?', (i.channel.id,))
            await db.commit()
        await asyncio.sleep(3)
        await i.channel.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(TkBtn(0))
    bot.add_view(TkActs(0, 0, 0))
    await bot.tree.sync()
    print(f"✅ {bot.user.name} connecté")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/stats"))

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    
    # 🆕 Tracker le message
    await track_message(msg.guild.id, msg.author.id)
    
    if await is_immune(msg.author): return
    c = await gcfg(msg.guild.id)
    if c['anti_phishing']:
        for d in ['discord-nitro.gift', 'discordgift.site', 'free-nitro.com']:
            if d in msg.content.lower():
                await msg.delete(); return
    if c['anti_link'] and re.search(r'https?://[^\s]+', msg.content):
        await msg.delete(); return
    if c['anti_image'] and msg.attachments:
        for a in msg.attachments:
            if a.filename.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp')):
                await msg.delete(); return

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    
    # Rejoint un vocal
    if after.channel and not before.channel:
        await track_voice_start(member.guild.id, member.id)
    
    # Quitte un vocal
    elif before.channel and not after.channel:
        await track_voice_end(member.guild.id, member.id)
    
    # Change de salon
    elif before.channel and after.channel and before.channel != after.channel:
        # On garde la session active, pas besoin de reset

@bot.event
async def on_member_join(m):
    c = await gcfg(m.guild.id)
    if c['welcome_on'] and c['welcome_channel']:
        ch = m.guild.get_channel(c['welcome_channel'])
        if ch:
            txt = c['welcome_msg'].format(member=m.mention, server=m.guild.name, count=m.guild.member_count)
            e = discord.Embed(title="👋 Bienvenue!", description=txt, color=C.GREEN)
            e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDES
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Panneau de configuration (Admin)")
async def cfg_cmd(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    if not i.user.guild_permissions.administrator and i.user.id != i.guild.owner_id:
        if not await is_staff(i.user):
            return await i.followup.send("❌ Accès refusé")
    v = MainPanel(i.user, i.guild)
    await i.followup.send(embed=v.embed(), view=v)

@bot.tree.command(name="stats", description="📊 Voir vos statistiques d'activité")
@app_commands.describe(membre="Membre dont vous voulez voir les stats (optionnel)")
async def stats_cmd(i: discord.Interaction, membre: discord.Member = None):
    await i.response.defer(ephemeral=True)
    
    target = membre or i.user
    stats = await get_user_stats(i.guild.id, target.id)
    
    # Niveau d'activité
    level, level_desc, level_color = get_activity_level(stats['msg_week'], stats['voice_week'])
    
    # Créer l'embed principal
    e = discord.Embed(color=level_color)
    e.set_author(name=f"📊 Statistiques de {target.display_name}", icon_url=target.display_avatar.url)
    e.set_thumbnail(url=target.display_avatar.url)
    
    # Niveau d'activité
    e.add_field(
        name="🏆 Niveau d'activité",
        value=f"**{level}**\n*{level_desc}*",
        inline=False
    )
    
    # Messages
    max_msg = max(stats['msg_today'], stats['msg_week'], stats['msg_month'], 1)
    msg_section = f"""```yml
📅 Aujourd'hui : {stats['msg_today']:,} messages
   {make_bar(stats['msg_today'], max_msg, 15)}

📆 Cette semaine : {stats['msg_week']:,} messages
   {make_bar(stats['msg_week'], max_msg, 15)}

📅 Ce mois : {stats['msg_month']:,} messages
   {make_bar(stats['msg_month'], max_msg, 15)}

📊 Total : {stats['msg_total']:,} messages
```"""
    e.add_field(name="💬 Messages", value=msg_section, inline=False)
    
    # Temps vocal
    max_voice = max(stats['voice_today'], stats['voice_week'], stats['voice_month'], 1)
    voice_section = f"""```yml
📅 Aujourd'hui : {format_time(stats['voice_today'])}
   {make_bar(stats['voice_today'], max_voice, 15)}

📆 Cette semaine : {format_time(stats['voice_week'])}
   {make_bar(stats['voice_week'], max_voice, 15)}

📅 Ce mois : {format_time(stats['voice_month'])}
   {make_bar(stats['voice_month'], max_voice, 15)}

📊 Total : {format_time(stats['voice_total'])}
```"""
    e.add_field(name="🎙️ Temps en vocal", value=voice_section, inline=False)
    
    # Graphique des 7 derniers jours (messages)
    graph = make_graph(stats['msg_by_day'])
    e.add_field(name="📈 Messages (7 derniers jours)", value=graph, inline=True)
    
    # Graphique des 7 derniers jours (vocal)
    voice_graph = make_graph([s // 60 for s in stats['voice_by_day']])  # En minutes
    e.add_field(name="📈 Vocal en minutes (7 derniers jours)", value=voice_graph, inline=True)
    
    # Footer
    e.set_footer(text=f"Statistiques de {i.guild.name}", icon_url=i.guild.icon.url if i.guild.icon else None)
    e.timestamp = datetime.utcnow()
    
    await i.followup.send(embed=e)

# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("🚀 Démarrage...")
    bot.run(TOKEN)
