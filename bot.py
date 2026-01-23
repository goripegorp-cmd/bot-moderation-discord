# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                        🌟 BOT TOUT-EN-UN PREMIUM 🌟                           ║
# ║              Version 5.1 - Optimisé (fix timeout)                             ║
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

class Color:
    BLURPLE = 0x5865F2
    GREEN = 0x57F287
    RED = 0xED4245
    YELLOW = 0xFEE75C
    PINK = 0xEB459E
    PURPLE = 0x9B59B6
    BLUE = 0x3498DB
    ORANGE = 0xE67E22
    CYAN = 0x1ABC9C

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 BASE DE DONNÉES
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            log_channel INTEGER, mod_log_channel INTEGER, welcome_channel INTEGER,
            mute_role INTEGER, warns_mute INTEGER DEFAULT 0, warns_kick INTEGER DEFAULT 0,
            warns_ban INTEGER DEFAULT 0, anti_link INTEGER DEFAULT 0, anti_image INTEGER DEFAULT 0,
            anti_phishing INTEGER DEFAULT 1, anti_spam INTEGER DEFAULT 0,
            welcome_on INTEGER DEFAULT 0, welcome_msg TEXT DEFAULT 'Bienvenue {member} !')''')
        await db.execute('''CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
            mod_id INTEGER, reason TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS staff_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS mod_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
            mod_id INTEGER, action TEXT, reason TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS activity (
            guild_id INTEGER, user_id INTEGER, last_message DATETIME, last_voice DATETIME,
            PRIMARY KEY (guild_id, user_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS ticket_config (
            guild_id INTEGER PRIMARY KEY, category_id INTEGER, staff_role_id INTEGER,
            ticket_name TEXT DEFAULT 'ticket-{user}-{number}', panel_title TEXT DEFAULT '🎫 Support',
            panel_description TEXT DEFAULT 'Cliquez pour créer un ticket', questions TEXT DEFAULT '[]')''')
        await db.execute('''CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER,
            user_id INTEGER, claimed_by INTEGER, status TEXT DEFAULT 'open',
            answers TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.commit()
    print("✅ DB OK")

async def get_config(gid):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM config WHERE guild_id=?', (gid,))
        r = await cur.fetchone()
        if r: return dict(r)
        await db.execute('INSERT INTO config (guild_id) VALUES (?)', (gid,))
        await db.commit()
        return {'guild_id': gid, 'log_channel': None, 'mod_log_channel': None, 'welcome_channel': None,
                'mute_role': None, 'warns_mute': 0, 'warns_kick': 0, 'warns_ban': 0,
                'anti_link': 0, 'anti_image': 0, 'anti_phishing': 1, 'anti_spam': 0,
                'welcome_on': 0, 'welcome_msg': 'Bienvenue {member} !'}

async def set_config(gid, **kw):
    async with aiosqlite.connect(DB) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE config SET {k}=? WHERE guild_id=?', (v, gid))
        await db.commit()

async def get_ticket_config(gid):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM ticket_config WHERE guild_id=?', (gid,))
        r = await cur.fetchone()
        if r: return dict(r)
        await db.execute('INSERT INTO ticket_config (guild_id) VALUES (?)', (gid,))
        await db.commit()
        return {'guild_id': gid, 'category_id': None, 'staff_role_id': None,
                'ticket_name': 'ticket-{user}-{number}', 'panel_title': '🎫 Support',
                'panel_description': 'Cliquez pour créer un ticket', 'questions': '[]'}

async def set_ticket_config(gid, **kw):
    async with aiosqlite.connect(DB) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE ticket_config SET {k}=? WHERE guild_id=?', (v, gid))
        await db.commit()

async def update_activity(gid, uid, msg=False, voice=False):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('SELECT * FROM activity WHERE guild_id=? AND user_id=?', (gid, uid))
        if await cur.fetchone():
            if msg: await db.execute('UPDATE activity SET last_message=? WHERE guild_id=? AND user_id=?', (now, gid, uid))
            if voice: await db.execute('UPDATE activity SET last_voice=? WHERE guild_id=? AND user_id=?', (now, gid, uid))
        else:
            await db.execute('INSERT INTO activity (guild_id, user_id, last_message, last_voice) VALUES (?,?,?,?)',
                           (gid, uid, now if msg else None, now if voice else None))
        await db.commit()

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

async def send_log(guild, embed, mod=False):
    c = await get_config(guild.id)
    ch_id = c['mod_log_channel'] if mod else c['log_channel']
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            try: await ch.send(embed=embed)
            except: pass

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 PANNEAU PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

class MainPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def interaction_check(self, i):
        if i.user.id != self.user.id:
            await i.response.send_message("❌ Ce panneau ne vous appartient pas", ephemeral=True)
            return False
        return True
    
    def create_embed(self):
        embed = discord.Embed(color=Color.BLURPLE)
        embed.title = "⚙️ Panneau de Configuration"
        embed.description = f"""```yml
╔══════════════════════════════════════════╗
║     🎛️  CENTRE DE CONTRÔLE               ║
╚══════════════════════════════════════════╝

👥 Membres : {self.guild.member_count}

📂 Catégories
────────────────────────────────────────────
⚔️ Modération  → Sanctions, warns
📜 Logs        → Salons de logs
🛡️ Protection  → Anti-spam, anti-link
👥 Rôles       → Staff et immunisés
👋 Bienvenue   → Messages d'accueil
📊 Activité    → Membres inactifs
🎫 Tickets     → Système de support
────────────────────────────────────────────
```"""
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        return embed
    
    @discord.ui.button(label="Modération", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def mod_btn(self, i, b):
        await i.response.defer()
        v = ModerationPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def logs_btn(self, i, b):
        await i.response.defer()
        v = LogsPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot_btn(self, i, b):
        await i.response.defer()
        v = ProtectionPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Rôles", emoji="👥", style=discord.ButtonStyle.secondary, row=1)
    async def roles_btn(self, i, b):
        await i.response.defer()
        v = RolesPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def welcome_btn(self, i, b):
        await i.response.defer()
        v = WelcomePanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Activité", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
    async def activity_btn(self, i, b):
        await i.response.defer()
        v = ActivityPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.primary, row=2)
    async def tickets_btn(self, i, b):
        await i.response.defer()
        v = TicketConfigPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close_btn(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚔️ MODÉRATION
# ═══════════════════════════════════════════════════════════════════════════════

class ModerationPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        mute_role = self.guild.get_role(c['mute_role'])
        embed = discord.Embed(title="⚔️ Modération", color=Color.PINK)
        embed.description = f"""```yml
⚙️ Configuration
────────────────────────────────────────────
🔇 Rôle Mute : {mute_role.name if mute_role else '❌ Non configuré'}

⚖️ Sanctions Auto
────────────────────────────────────────────
🔇 Mute après : {f'{c["warns_mute"]} warns' if c['warns_mute'] else 'Désactivé'}
👢 Kick après : {f'{c["warns_kick"]} warns' if c['warns_kick'] else 'Désactivé'}
🔨 Ban après  : {f'{c["warns_ban"]} warns' if c['warns_ban'] else 'Désactivé'}
────────────────────────────────────────────
```"""
        return embed
    
    @discord.ui.button(label="Warn", emoji="⚠️", style=discord.ButtonStyle.danger, row=0)
    async def warn_btn(self, i, b): await i.response.send_modal(WarnModal(self.guild, self.user))
    
    @discord.ui.button(label="Mute", emoji="🔇", style=discord.ButtonStyle.danger, row=0)
    async def mute_btn(self, i, b): await i.response.send_modal(MuteModal(self.guild, self.user))
    
    @discord.ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.danger, row=0)
    async def kick_btn(self, i, b): await i.response.send_modal(KickModal(self.guild, self.user))
    
    @discord.ui.button(label="Ban", emoji="🔨", style=discord.ButtonStyle.danger, row=0)
    async def ban_btn(self, i, b): await i.response.send_modal(BanModal(self.guild, self.user))
    
    @discord.ui.button(label="Voir Warns", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def view_warns(self, i, b): await i.response.send_modal(ViewWarnsModal(self.guild))
    
    @discord.ui.button(label="Clear Warns", emoji="🗑️", style=discord.ButtonStyle.secondary, row=1)
    async def clear_warns(self, i, b): await i.response.send_modal(ClearWarnsModal(self.guild))
    
    @discord.ui.button(label="Config Sanctions", emoji="⚖️", style=discord.ButtonStyle.primary, row=2)
    async def sanctions_btn(self, i, b): await i.response.send_modal(SanctionsModal(self.guild))
    
    @discord.ui.button(label="Rôle Mute", emoji="🎭", style=discord.ButtonStyle.primary, row=2)
    async def mute_role_btn(self, i, b): await i.response.send_modal(MuteRoleModal(self.guild))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)

class WarnModal(Modal, title="⚠️ Warn"):
    member_id = TextInput(label="ID du membre", placeholder="Clic droit → Copier ID", max_length=20)
    reason = TextInput(label="Raison", required=False, max_length=200)
    def __init__(self, guild, mod): super().__init__(); self.guild, self.mod = guild, mod
    async def on_submit(self, i):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member: return await i.response.send_message("❌ Membre introuvable", ephemeral=True)
            if await is_immune(member): return await i.response.send_message("❌ Membre immunisé", ephemeral=True)
            reason = self.reason.value or "Aucune raison"
            async with aiosqlite.connect(DB) as db:
                await db.execute('INSERT INTO warns (guild_id,user_id,mod_id,reason) VALUES (?,?,?,?)', (self.guild.id,member.id,self.mod.id,reason))
                await db.commit()
                cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?', (self.guild.id,member.id))
                count = (await cur.fetchone())[0]
            await i.response.send_message(f"✅ **{member}** averti (warn #{count})\nRaison: {reason}", ephemeral=True)
            c = await get_config(self.guild.id)
            if c['warns_ban'] and count >= c['warns_ban']: await member.ban(reason=f"Auto: {count} warns")
            elif c['warns_kick'] and count >= c['warns_kick']: await member.kick(reason=f"Auto: {count} warns")
            elif c['warns_mute'] and count >= c['warns_mute']:
                r = self.guild.get_role(c['mute_role'])
                if r: await member.add_roles(r)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

class MuteModal(Modal, title="🔇 Mute"):
    member_id = TextInput(label="ID du membre", max_length=20)
    reason = TextInput(label="Raison", required=False)
    def __init__(self, guild, mod): super().__init__(); self.guild, self.mod = guild, mod
    async def on_submit(self, i):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            c = await get_config(self.guild.id)
            role = self.guild.get_role(c['mute_role'])
            if not role: return await i.response.send_message("❌ Rôle mute non configuré", ephemeral=True)
            await member.add_roles(role)
            await i.response.send_message(f"✅ **{member}** mute", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class KickModal(Modal, title="👢 Kick"):
    member_id = TextInput(label="ID du membre", max_length=20)
    reason = TextInput(label="Raison", required=False)
    def __init__(self, guild, mod): super().__init__(); self.guild, self.mod = guild, mod
    async def on_submit(self, i):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            if await is_immune(member): return await i.response.send_message("❌ Immunisé", ephemeral=True)
            await member.kick(reason=self.reason.value or "Aucune raison")
            await i.response.send_message(f"✅ **{member}** expulsé", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class BanModal(Modal, title="🔨 Ban"):
    member_id = TextInput(label="ID du membre", max_length=20)
    reason = TextInput(label="Raison", required=False)
    def __init__(self, guild, mod): super().__init__(); self.guild, self.mod = guild, mod
    async def on_submit(self, i):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            if await is_immune(member): return await i.response.send_message("❌ Immunisé", ephemeral=True)
            await member.ban(reason=self.reason.value or "Aucune raison")
            await i.response.send_message(f"✅ **{member}** banni", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

class ViewWarnsModal(Modal, title="📋 Voir Warns"):
    member_id = TextInput(label="ID du membre", max_length=20)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            async with aiosqlite.connect(DB) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute('SELECT * FROM warns WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 5', (self.guild.id,member.id))
                warns = [dict(r) for r in await cur.fetchall()]
            if not warns: return await i.response.send_message(f"✅ **{member}** n'a aucun warn", ephemeral=True)
            txt = f"**{member}** - {len(warns)} warn(s)\n"
            for w in warns: txt += f"• #{w['id']} - {w['reason'][:30]}\n"
            await i.response.send_message(txt, ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

class ClearWarnsModal(Modal, title="🗑️ Clear Warns"):
    member_id = TextInput(label="ID du membre", max_length=20)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member: return await i.response.send_message("❌ Introuvable", ephemeral=True)
            async with aiosqlite.connect(DB) as db:
                cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?', (self.guild.id,member.id))
                count = (await cur.fetchone())[0]
                await db.execute('DELETE FROM warns WHERE guild_id=? AND user_id=?', (self.guild.id,member.id))
                await db.commit()
            await i.response.send_message(f"✅ {count} warn(s) supprimé(s) pour **{member}**", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

class SanctionsModal(Modal, title="⚖️ Sanctions Auto"):
    w_mute = TextInput(label="Warns pour Mute (0=off)", required=False, max_length=2)
    w_kick = TextInput(label="Warns pour Kick (0=off)", required=False, max_length=2)
    w_ban = TextInput(label="Warns pour Ban (0=off)", required=False, max_length=2)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        m = int(self.w_mute.value) if self.w_mute.value.isdigit() else 0
        k = int(self.w_kick.value) if self.w_kick.value.isdigit() else 0
        b = int(self.w_ban.value) if self.w_ban.value.isdigit() else 0
        await set_config(self.guild.id, warns_mute=m, warns_kick=k, warns_ban=b)
        await i.response.send_message(f"✅ Mute:{m} | Kick:{k} | Ban:{b}", ephemeral=True)

class MuteRoleModal(Modal, title="🎭 Rôle Mute"):
    role_id = TextInput(label="ID du rôle", max_length=20)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        try:
            role = self.guild.get_role(int(self.role_id.value))
            if not role: return await i.response.send_message("❌ Rôle introuvable", ephemeral=True)
            await set_config(self.guild.id, mute_role=role.id)
            await i.response.send_message(f"✅ Rôle mute: **{role.name}**", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📜 LOGS
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        log_ch = self.guild.get_channel(c['log_channel'])
        mod_ch = self.guild.get_channel(c['mod_log_channel'])
        embed = discord.Embed(title="📜 Logs", color=Color.PURPLE)
        embed.description = f"""```yml
📊 Configuration
────────────────────────────────────────────
📝 Logs Généraux   : {log_ch.name if log_ch else '❌ Non configuré'}
⚔️ Logs Modération : {mod_ch.name if mod_ch else '❌ Non configuré'}
────────────────────────────────────────────
```"""
        return embed
    
    @discord.ui.button(label="Logs Généraux", emoji="📝", style=discord.ButtonStyle.primary)
    async def gen_btn(self, i, b): await i.response.send_modal(LogChannelModal(self.guild, "log_channel", "Logs Généraux"))
    
    @discord.ui.button(label="Logs Modération", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def mod_btn(self, i, b): await i.response.send_modal(LogChannelModal(self.guild, "mod_log_channel", "Logs Modération"))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)

class LogChannelModal(Modal, title="📝 Configurer Salon"):
    channel_id = TextInput(label="ID du salon", max_length=20)
    def __init__(self, guild, key, name): super().__init__(); self.guild, self.key, self.name = guild, key, name
    async def on_submit(self, i):
        try:
            ch = self.guild.get_channel(int(self.channel_id.value))
            if not ch: return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
            await set_config(self.guild.id, **{self.key: ch.id})
            await i.response.send_message(f"✅ {self.name}: **#{ch.name}**", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class ProtectionPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        s = lambda v: "✅ Activé" if v else "❌ Désactivé"
        embed = discord.Embed(title="🛡️ Protection", color=Color.BLUE)
        embed.description = f"""```yml
📊 État des Protections
────────────────────────────────────────────
🔗 Anti-Liens    : {s(c['anti_link'])}
🖼️ Anti-Images   : {s(c['anti_image'])}
🎣 Anti-Phishing : {s(c['anti_phishing'])}
📨 Anti-Spam     : {s(c['anti_spam'])}
────────────────────────────────────────────

Cliquez pour activer/désactiver
```"""
        return embed
    
    @discord.ui.button(label="Anti-Liens", emoji="🔗", style=discord.ButtonStyle.primary)
    async def link_btn(self, i, b):
        c = await get_config(self.guild.id)
        await set_config(self.guild.id, anti_link=not c['anti_link'])
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="Anti-Images", emoji="🖼️", style=discord.ButtonStyle.primary)
    async def img_btn(self, i, b):
        c = await get_config(self.guild.id)
        await set_config(self.guild.id, anti_image=not c['anti_image'])
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="Anti-Phishing", emoji="🎣", style=discord.ButtonStyle.primary)
    async def phish_btn(self, i, b):
        c = await get_config(self.guild.id)
        await set_config(self.guild.id, anti_phishing=not c['anti_phishing'])
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="Anti-Spam", emoji="📨", style=discord.ButtonStyle.primary)
    async def spam_btn(self, i, b):
        c = await get_config(self.guild.id)
        await set_config(self.guild.id, anti_spam=not c['anti_spam'])
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👥 RÔLES
# ═══════════════════════════════════════════════════════════════════════════════

class RolesPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
    
    async def create_embed(self):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id=?', (self.guild.id,))
            staff = [self.guild.get_role(r[0]) for r in await cur.fetchall() if self.guild.get_role(r[0])]
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.guild.id,))
            immune = [self.guild.get_role(r[0]) for r in await cur.fetchall() if self.guild.get_role(r[0])]
        embed = discord.Embed(title="👥 Rôles", color=Color.ORANGE)
        embed.description = f"""```yml
👮 Rôles Staff ({len(staff)})
────────────────────────────────────────────
{', '.join([r.name for r in staff]) or 'Aucun'}

👑 Rôles Immunisés ({len(immune)})
────────────────────────────────────────────
{', '.join([r.name for r in immune]) or 'Aucun'}
```"""
        return embed
    
    @discord.ui.button(label="+ Staff", emoji="👮", style=discord.ButtonStyle.success)
    async def add_staff(self, i, b): await i.response.send_modal(AddRoleModal(self.guild, "staff_roles", "Staff"))
    
    @discord.ui.button(label="- Staff", emoji="👮", style=discord.ButtonStyle.danger)
    async def rem_staff(self, i, b): await i.response.send_modal(RemRoleModal(self.guild, "staff_roles", "Staff"))
    
    @discord.ui.button(label="+ Immunisé", emoji="👑", style=discord.ButtonStyle.success)
    async def add_immune(self, i, b): await i.response.send_modal(AddRoleModal(self.guild, "immune_roles", "Immunisé"))
    
    @discord.ui.button(label="- Immunisé", emoji="👑", style=discord.ButtonStyle.danger)
    async def rem_immune(self, i, b): await i.response.send_modal(RemRoleModal(self.guild, "immune_roles", "Immunisé"))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)

class AddRoleModal(Modal, title="➕ Ajouter Rôle"):
    role_id = TextInput(label="ID du rôle", max_length=20)
    def __init__(self, guild, table, typ): super().__init__(); self.guild, self.table, self.typ = guild, table, typ
    async def on_submit(self, i):
        try:
            role = self.guild.get_role(int(self.role_id.value))
            if not role: return await i.response.send_message("❌ Rôle introuvable", ephemeral=True)
            async with aiosqlite.connect(DB) as db:
                await db.execute(f'INSERT OR IGNORE INTO {self.table} VALUES (?,?)', (self.guild.id, role.id))
                await db.commit()
            await i.response.send_message(f"✅ **{role.name}** ajouté aux {self.typ}", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

class RemRoleModal(Modal, title="➖ Retirer Rôle"):
    role_id = TextInput(label="ID du rôle", max_length=20)
    def __init__(self, guild, table, typ): super().__init__(); self.guild, self.table, self.typ = guild, table, typ
    async def on_submit(self, i):
        try:
            rid = int(self.role_id.value)
            async with aiosqlite.connect(DB) as db:
                await db.execute(f'DELETE FROM {self.table} WHERE guild_id=? AND role_id=?', (self.guild.id, rid))
                await db.commit()
            await i.response.send_message(f"✅ Rôle retiré des {self.typ}", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👋 BIENVENUE
# ═══════════════════════════════════════════════════════════════════════════════

class WelcomePanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        ch = self.guild.get_channel(c['welcome_channel'])
        embed = discord.Embed(title="👋 Bienvenue", color=Color.GREEN)
        embed.description = f"""```yml
📊 Configuration
────────────────────────────────────────────
État  : {'✅ Activé' if c['welcome_on'] else '❌ Désactivé'}
Salon : {ch.name if ch else '❌ Non configuré'}
────────────────────────────────────────────

💬 Message
────────────────────────────────────────────
{c['welcome_msg'][:100]}
────────────────────────────────────────────

Variables: {{member}} {{server}} {{count}}
```"""
        return embed
    
    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary)
    async def toggle_btn(self, i, b):
        c = await get_config(self.guild.id)
        await set_config(self.guild.id, welcome_on=not c['welcome_on'])
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="Salon", emoji="📝", style=discord.ButtonStyle.primary)
    async def channel_btn(self, i, b): await i.response.send_modal(WelcomeChannelModal(self.guild))
    
    @discord.ui.button(label="Message", emoji="✏️", style=discord.ButtonStyle.primary)
    async def msg_btn(self, i, b): await i.response.send_modal(WelcomeMessageModal(self.guild))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)

class WelcomeChannelModal(Modal, title="📝 Salon Bienvenue"):
    channel_id = TextInput(label="ID du salon", max_length=20)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        try:
            ch = self.guild.get_channel(int(self.channel_id.value))
            if not ch: return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
            await set_config(self.guild.id, welcome_channel=ch.id)
            await i.response.send_message(f"✅ Salon: **#{ch.name}**", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

class WelcomeMessageModal(Modal, title="✏️ Message Bienvenue"):
    message = TextInput(label="Message", style=discord.TextStyle.paragraph, placeholder="Bienvenue {member} !", max_length=500)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        await set_config(self.guild.id, welcome_msg=self.message.value)
        await i.response.send_message(f"✅ Message configuré", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 ACTIVITÉ
# ═══════════════════════════════════════════════════════════════════════════════

class ActivityPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
        self.inactive_7 = []
        self.inactive_30 = []
    
    async def create_embed(self):
        now = datetime.utcnow()
        seven_days = now - timedelta(days=7)
        thirty_days = now - timedelta(days=30)
        
        async with aiosqlite.connect(DB) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM activity WHERE guild_id=?', (self.guild.id,))
            activities = {r['user_id']: dict(r) for r in await cur.fetchall()}
        
        self.inactive_7 = []
        self.inactive_30 = []
        
        for member in self.guild.members:
            if member.bot: continue
            act = activities.get(member.id)
            if not act:
                self.inactive_30.append(member)
                self.inactive_7.append(member)
                continue
            last_msg = datetime.fromisoformat(act['last_message']) if act['last_message'] else None
            last_voice = datetime.fromisoformat(act['last_voice']) if act['last_voice'] else None
            last = max(filter(None, [last_msg, last_voice]), default=None)
            if not last or last < thirty_days:
                self.inactive_30.append(member)
            elif last < seven_days:
                self.inactive_7.append(member)
        
        embed = discord.Embed(title="📊 Activité des Membres", color=Color.ORANGE)
        embed.description = f"""```yml
📈 Statistiques
────────────────────────────────────────────
👥 Total membres   : {self.guild.member_count}
👤 Humains         : {len([m for m in self.guild.members if not m.bot])}
────────────────────────────────────────────

⚠️ Inactifs 7 jours  : {len(self.inactive_7)} membres
🔴 Inactifs 30 jours : {len(self.inactive_30)} membres
────────────────────────────────────────────
```"""
        return embed
    
    @discord.ui.button(label="Inactifs 7j", emoji="⚠️", style=discord.ButtonStyle.primary)
    async def btn_7(self, i, b):
        v = InactivePanel(self.user, self.guild, 7, self.inactive_7)
        await i.response.edit_message(embed=v.create_embed(), view=v)
    
    @discord.ui.button(label="Inactifs 30j", emoji="🔴", style=discord.ButtonStyle.danger)
    async def btn_30(self, i, b):
        v = InactivePanel(self.user, self.guild, 30, self.inactive_30)
        await i.response.edit_message(embed=v.create_embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)


class InactivePanel(View):
    def __init__(self, user, guild, days, members):
        super().__init__(timeout=900)
        self.user, self.guild, self.days = user, guild, days
        self.members = members[:100]
    
    def create_embed(self):
        lst = "\n".join([f"• {m.name}" for m in self.members[:15]])
        if len(self.members) > 15: lst += f"\n... et {len(self.members)-15} autres"
        embed = discord.Embed(title=f"{'⚠️' if self.days==7 else '🔴'} Inactifs {self.days}j", color=Color.ORANGE if self.days==7 else Color.RED)
        embed.description = f"**{len(self.members)} membres inactifs**\n```\n{lst or 'Aucun 🎉'}\n```"
        return embed
    
    @discord.ui.button(label="📢 Mentionner", emoji="📢", style=discord.ButtonStyle.primary)
    async def mention_btn(self, i, b):
        if not self.members: return await i.response.send_message("❌ Aucun membre", ephemeral=True)
        mentions = " ".join([m.mention for m in self.members[:40]])
        await i.response.send_message(f"📢 **Inactifs {self.days}j:**\n{mentions}")
    
    @discord.ui.button(label="👢 Expulser", emoji="👢", style=discord.ButtonStyle.danger)
    async def kick_btn(self, i, b):
        if not self.members: return await i.response.send_message("❌ Aucun membre", ephemeral=True)
        v = ConfirmKick(self.user, self.guild, self.members, self.days)
        await i.response.edit_message(embed=discord.Embed(title="⚠️ Confirmer ?", description=f"Expulser **{len(self.members)}** membres ?", color=Color.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        await i.response.defer()
        v = ActivityPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)


class ConfirmKick(View):
    def __init__(self, user, guild, members, days):
        super().__init__(timeout=60)
        self.user, self.guild, self.members, self.days = user, guild, members, days
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        await i.response.defer()
        kicked, failed = 0, 0
        for m in self.members:
            try: await m.kick(reason=f"Inactif {self.days}j"); kicked += 1
            except: failed += 1
        await i.edit_original_response(embed=discord.Embed(title="👢 Terminé", description=f"✅ {kicked} expulsés\n❌ {failed} échoués", color=Color.GREEN), view=None)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.defer()
        v = ActivityPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

class TicketConfigPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user, self.guild = user, guild
    
    async def create_embed(self):
        tc = await get_ticket_config(self.guild.id)
        cat = self.guild.get_channel(tc['category_id'])
        role = self.guild.get_role(tc['staff_role_id'])
        questions = json.loads(tc['questions']) if tc['questions'] else []
        embed = discord.Embed(title="🎫 Tickets", color=Color.PURPLE)
        embed.description = f"""```yml
⚙️ Configuration
────────────────────────────────────────────
📁 Catégorie  : {cat.name if cat else '❌ Non configurée'}
👮 Rôle Staff : {role.name if role else '❌ Non configuré'}
📝 Nom Format : {tc['ticket_name']}
────────────────────────────────────────────

❓ Questions ({len(questions)}/5)
────────────────────────────────────────────
{chr(10).join([f'{i+1}. {q}' for i,q in enumerate(questions)]) or 'Aucune'}
────────────────────────────────────────────

🎨 Panneau
────────────────────────────────────────────
Titre : {tc['panel_title']}
────────────────────────────────────────────
```"""
        return embed
    
    @discord.ui.button(label="Catégorie", emoji="📁", style=discord.ButtonStyle.primary, row=0)
    async def cat_btn(self, i, b): await i.response.send_modal(TicketCategoryModal(self.guild))
    
    @discord.ui.button(label="Rôle Staff", emoji="👮", style=discord.ButtonStyle.primary, row=0)
    async def role_btn(self, i, b): await i.response.send_modal(TicketRoleModal(self.guild))
    
    @discord.ui.button(label="Nom Format", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def name_btn(self, i, b): await i.response.send_modal(TicketNameModal(self.guild))
    
    @discord.ui.button(label="Questions", emoji="❓", style=discord.ButtonStyle.secondary, row=1)
    async def questions_btn(self, i, b):
        v = QuestionsPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Personnaliser", emoji="🎨", style=discord.ButtonStyle.secondary, row=1)
    async def custom_btn(self, i, b): await i.response.send_modal(TicketPanelModal(self.guild))
    
    @discord.ui.button(label="📤 Déployer", emoji="📤", style=discord.ButtonStyle.success, row=2)
    async def deploy_btn(self, i, b): await i.response.send_modal(DeployModal(self.guild))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)


class TicketCategoryModal(Modal, title="📁 Catégorie Tickets"):
    cat_id = TextInput(label="ID de la catégorie", max_length=20)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        try:
            cat = self.guild.get_channel(int(self.cat_id.value))
            if not cat or not isinstance(cat, discord.CategoryChannel): return await i.response.send_message("❌ Catégorie introuvable", ephemeral=True)
            await set_ticket_config(self.guild.id, category_id=cat.id)
            await i.response.send_message(f"✅ Catégorie: **{cat.name}**", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)


class TicketRoleModal(Modal, title="👮 Rôle Staff Tickets"):
    role_id = TextInput(label="ID du rôle", max_length=20)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        try:
            role = self.guild.get_role(int(self.role_id.value))
            if not role: return await i.response.send_message("❌ Rôle introuvable", ephemeral=True)
            await set_ticket_config(self.guild.id, staff_role_id=role.id)
            await i.response.send_message(f"✅ Rôle Staff: **{role.name}**", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)


class TicketNameModal(Modal, title="📝 Format Nom Ticket"):
    name = TextInput(label="Format", placeholder="ticket-{user}-{number}", default="ticket-{user}-{number}", max_length=50)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        await set_ticket_config(self.guild.id, ticket_name=self.name.value)
        await i.response.send_message(f"✅ Format: **{self.name.value}**", ephemeral=True)


class TicketPanelModal(Modal, title="🎨 Personnaliser Panneau"):
    title_input = TextInput(label="Titre", default="🎫 Support", max_length=100)
    desc_input = TextInput(label="Description", style=discord.TextStyle.paragraph, default="Cliquez pour créer un ticket", max_length=500)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        await set_ticket_config(self.guild.id, panel_title=self.title_input.value, panel_description=self.desc_input.value)
        await i.response.send_message("✅ Panneau personnalisé", ephemeral=True)


class DeployModal(Modal, title="📤 Déployer Panneau"):
    channel_id = TextInput(label="ID du salon", max_length=20)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        try:
            ch = self.guild.get_channel(int(self.channel_id.value))
            if not ch: return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
            tc = await get_ticket_config(self.guild.id)
            if not tc['category_id'] or not tc['staff_role_id']:
                return await i.response.send_message("❌ Configurez d'abord catégorie et rôle staff", ephemeral=True)
            embed = discord.Embed(title=tc['panel_title'], description=tc['panel_description'], color=Color.PURPLE)
            if self.guild.icon: embed.set_thumbnail(url=self.guild.icon.url)
            view = TicketButton(self.guild.id)
            await ch.send(embed=embed, view=view)
            await i.response.send_message(f"✅ Panneau déployé dans **#{ch.name}**", ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)


class QuestionsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
    
    async def create_embed(self):
        tc = await get_ticket_config(self.guild.id)
        questions = json.loads(tc['questions']) if tc['questions'] else []
        embed = discord.Embed(title="❓ Questions", color=Color.PURPLE)
        embed.description = f"```yml\n{chr(10).join([f'{i+1}. {q}' for i,q in enumerate(questions)]) or 'Aucune question'}\n```\nMax: 5 questions"
        return embed
    
    @discord.ui.button(label="➕ Ajouter", emoji="➕", style=discord.ButtonStyle.success)
    async def add_btn(self, i, b):
        tc = await get_ticket_config(self.guild.id)
        questions = json.loads(tc['questions']) if tc['questions'] else []
        if len(questions) >= 5: return await i.response.send_message("❌ Max 5 questions", ephemeral=True)
        await i.response.send_modal(AddQuestionModal(self.guild))
    
    @discord.ui.button(label="🗑️ Tout supprimer", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def clear_btn(self, i, b):
        await set_ticket_config(self.guild.id, questions='[]')
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        await i.response.defer()
        v = TicketConfigPanel(self.user, self.guild)
        await i.edit_original_response(embed=await v.create_embed(), view=v)


class AddQuestionModal(Modal, title="➕ Ajouter Question"):
    question = TextInput(label="Question", placeholder="Pourquoi créez-vous ce ticket ?", max_length=100)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        tc = await get_ticket_config(self.guild.id)
        questions = json.loads(tc['questions']) if tc['questions'] else []
        questions.append(self.question.value)
        await set_ticket_config(self.guild.id, questions=json.dumps(questions))
        await i.response.send_message(f"✅ Question ajoutée", ephemeral=True)


class TicketButton(View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
    
    @discord.ui.button(label="📩 Créer un ticket", emoji="📩", style=discord.ButtonStyle.success, custom_id="create_ticket")
    async def create_btn(self, i, b):
        tc = await get_ticket_config(i.guild.id)
        questions = json.loads(tc['questions']) if tc['questions'] else []
        if questions:
            await i.response.send_modal(TicketFormModal(i.guild, questions))
        else:
            await create_ticket(i, {})


class TicketFormModal(Modal, title="📩 Créer un ticket"):
    def __init__(self, guild, questions):
        super().__init__()
        self.guild = guild
        self.questions = questions
        for idx, q in enumerate(questions[:5]):
            self.add_item(TextInput(label=q[:45], placeholder="Votre réponse...", style=discord.TextStyle.paragraph, required=True, max_length=500, custom_id=f"q{idx}"))
    
    async def on_submit(self, i):
        answers = {self.questions[idx]: self.children[idx].value for idx in range(len(self.questions[:5]))}
        await create_ticket(i, answers)


async def create_ticket(interaction, answers):
    tc = await get_ticket_config(interaction.guild.id)
    cat = interaction.guild.get_channel(tc['category_id'])
    role = interaction.guild.get_role(tc['staff_role_id'])
    
    if not cat or not role:
        return await interaction.response.send_message("❌ Tickets non configurés", ephemeral=True)
    
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=?', (interaction.guild.id,))
        num = (await cur.fetchone())[0] + 1
    
    name = tc['ticket_name'].format(user=interaction.user.name.lower()[:10], number=num)
    name = re.sub(r'[^a-z0-9-]', '', name)[:100]
    
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }
    
    channel = await cat.create_text_channel(name=name, overwrites=overwrites)
    
    async with aiosqlite.connect(DB) as db:
        await db.execute('INSERT INTO tickets (guild_id, channel_id, user_id, answers) VALUES (?,?,?,?)',
                        (interaction.guild.id, channel.id, interaction.user.id, json.dumps(answers)))
        await db.commit()
    
    embed = discord.Embed(title="🎫 Ticket", color=Color.GREEN)
    embed.description = f"👤 **{interaction.user}**\n📅 {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}"
    if answers:
        for q, a in answers.items():
            embed.add_field(name=f"❓ {q}", value=f"```{a[:200]}```", inline=False)
    
    view = TicketActions(interaction.guild.id, channel.id, interaction.user.id)
    await channel.send(content=f"{interaction.user.mention} {role.mention}", embed=embed, view=view)
    await interaction.response.send_message(f"✅ Ticket créé: {channel.mention}", ephemeral=True)


class TicketActions(View):
    def __init__(self, guild_id, channel_id, user_id):
        super().__init__(timeout=None)
        self.guild_id, self.channel_id, self.user_id = guild_id, channel_id, user_id
    
    @discord.ui.button(label="🙋 Prendre", emoji="🙋", style=discord.ButtonStyle.success, custom_id="claim_ticket")
    async def claim_btn(self, i, b):
        tc = await get_ticket_config(i.guild.id)
        role = i.guild.get_role(tc['staff_role_id'])
        if not role or (role not in i.user.roles and not i.user.guild_permissions.administrator):
            return await i.response.send_message("❌ Pas staff", ephemeral=True)
        
        async with aiosqlite.connect(DB) as db:
            await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (i.user.id, i.channel.id))
            await db.commit()
        
        user = i.guild.get_member(self.user_id)
        overwrites = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        for r in i.guild.roles:
            if r.position > i.user.top_role.position and not r.is_bot_managed():
                overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        await i.channel.edit(overwrites=overwrites)
        
        b.disabled, b.label, b.style = True, f"Pris par {i.user.name}", discord.ButtonStyle.secondary
        await i.response.edit_message(view=self)
        await i.channel.send(f"🙋 **{i.user}** a pris ce ticket")
    
    @discord.ui.button(label="🔒 Fermer", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_btn(self, i, b):
        tc = await get_ticket_config(i.guild.id)
        role = i.guild.get_role(tc['staff_role_id'])
        is_staff = role and role in i.user.roles
        if not (is_staff or i.user.guild_permissions.administrator or i.user.id == self.user_id):
            return await i.response.send_message("❌ Non autorisé", ephemeral=True)
        
        await i.response.send_message("🔒 Fermeture dans 5s...")
        async with aiosqlite.connect(DB) as db:
            await db.execute('UPDATE tickets SET status="closed" WHERE channel_id=?', (i.channel.id,))
            await db.commit()
        await asyncio.sleep(5)
        await i.channel.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 ÉVÉNEMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(TicketButton(0))
    bot.add_view(TicketActions(0, 0, 0))
    await bot.tree.sync()
    print(f"✅ {bot.user} connecté")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/configure"))

@bot.event
async def on_guild_join(g):
    await get_config(g.id)
    await get_ticket_config(g.id)

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    await update_activity(msg.guild.id, msg.author.id, msg=True)
    if await is_immune(msg.author): return
    c = await get_config(msg.guild.id)
    PHISH = ['discord-nitro.gift', 'discordgift.site', 'free-nitro.com', 'steampowered.ru', 'dlscord.com']
    if c['anti_phishing']:
        for d in PHISH:
            if d in msg.content.lower():
                await msg.delete(); await msg.channel.send(f"🎣 Phishing ({msg.author})", delete_after=10); return
    if c['anti_link'] and re.search(r'https?://[^\s]+', msg.content):
        await msg.delete(); await msg.channel.send(f"🔗 Lien supprimé ({msg.author})", delete_after=10); return
    if c['anti_image'] and msg.attachments:
        for a in msg.attachments:
            if a.filename.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp')):
                await msg.delete(); await msg.channel.send(f"🖼️ Image supprimée ({msg.author})", delete_after=10); return

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    if after.channel and not before.channel:
        await update_activity(member.guild.id, member.id, voice=True)

@bot.event
async def on_member_join(member):
    c = await get_config(member.guild.id)
    if c['welcome_on'] and c['welcome_channel']:
        ch = member.guild.get_channel(c['welcome_channel'])
        if ch:
            msg = c['welcome_msg'].format(member=member.mention, server=member.guild.name, count=member.guild.member_count)
            embed = discord.Embed(title="👋 Bienvenue !", description=msg, color=Color.GREEN)
            embed.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=embed)

@bot.event
async def on_message_delete(msg):
    if msg.author.bot or not msg.guild: return
    embed = discord.Embed(title="🗑️ Message supprimé", color=Color.YELLOW)
    embed.add_field(name="Auteur", value=msg.author.mention, inline=True)
    embed.add_field(name="Salon", value=msg.channel.mention, inline=True)
    if msg.content: embed.add_field(name="Contenu", value=f"```{msg.content[:500]}```", inline=False)
    await send_log(msg.guild, embed)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDE UNIQUE
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Panneau de configuration")
async def configure_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator and i.user.id != i.guild.owner_id:
        if not await is_staff(i.user):
            return await i.response.send_message("❌ Accès refusé", ephemeral=True)
    
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.create_embed(), view=v, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("🚀 Démarrage...")
    bot.run(TOKEN)
