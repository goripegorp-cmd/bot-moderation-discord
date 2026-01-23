# ============================================
# BOT DISCORD - TOUT-EN-UN
# ============================================
# Version 3.0 - Configuration Interactive
# Un seul bot pour tout gérer
# ============================================

# Fix pour Python 3.13+
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
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
DB_PATH = 'bot_database.db'

# ============================================
# COULEURS & EMOJIS
# ============================================

class C:  # Colors
    PRIMARY = 0x5865F2
    SUCCESS = 0x57F287
    ERROR = 0xED4245
    WARNING = 0xFEE75C
    MOD = 0xEB459E
    LOGS = 0x9B59B6
    PROTECT = 0x3498DB
    CONFIG = 0xF39C12

class E:  # Emojis
    HOME, BACK, NEXT, CLOSE = "🏠", "◀️", "▶️", "❌"
    ADMIN, LOGS, PROTECT, CONFIG, ROLES = "⚔️", "📜", "🛡️", "⚙️", "👥"
    WARN, MUTE, KICK, BAN, TIMEOUT, CLEAR = "⚠️", "🔇", "👢", "🔨", "⏰", "🗑️"
    ON, OFF, CHECK, EDIT = "✅", "❌", "☑️", "✏️"
    MEMBER, CHANNEL, ROLE, STATS, INFO = "👤", "📝", "🎭", "📊", "ℹ️"

# ============================================
# BASE DE DONNÉES
# ============================================

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY, log_channel INTEGER, mod_log_channel INTEGER,
            welcome_channel INTEGER, mute_role INTEGER, warns_mute INTEGER DEFAULT 0,
            warns_kick INTEGER DEFAULT 0, warns_ban INTEGER DEFAULT 0,
            anti_link INTEGER DEFAULT 0, anti_image INTEGER DEFAULT 0,
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
        await db.commit()
    print("✅ Base de données OK")

async def get_cfg(gid):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM config WHERE guild_id=?', (gid,))
        row = await cur.fetchone()
        if row: return dict(row)
        await db.execute('INSERT INTO config (guild_id) VALUES (?)', (gid,))
        await db.commit()
        return {'guild_id': gid, 'log_channel': None, 'mod_log_channel': None, 'welcome_channel': None,
                'mute_role': None, 'warns_mute': 0, 'warns_kick': 0, 'warns_ban': 0,
                'anti_link': 0, 'anti_image': 0, 'anti_phishing': 1, 'anti_spam': 0,
                'welcome_on': 0, 'welcome_msg': 'Bienvenue {member} !'}

async def set_cfg(gid, **kw):
    async with aiosqlite.connect(DB_PATH) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE config SET {k}=? WHERE guild_id=?', (v, gid))
        await db.commit()

async def is_immune(m):
    if m.id == m.guild.owner_id: return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,))
        ids = [r[0] for r in await cur.fetchall()]
    return any(r.id in ids for r in m.roles)

async def is_staff(m):
    if m.id == m.guild.owner_id or m.guild_permissions.administrator: return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id=?', (m.guild.id,))
        ids = [r[0] for r in await cur.fetchall()]
    return any(r.id in ids for r in m.roles)

async def send_log(guild, emb, mod=False):
    cfg = await get_cfg(guild.id)
    ch_id = cfg['mod_log_channel'] if mod else cfg['log_channel']
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            try: await ch.send(embed=emb)
            except: pass

# ============================================
# EMBEDS HELPERS
# ============================================

def emb(title=None, desc=None, color=C.PRIMARY, **kw):
    e = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.utcnow())
    if kw.get('thumb'): e.set_thumbnail(url=kw['thumb'])
    if kw.get('foot'): e.set_footer(text=kw['foot'])
    return e

def ok(t, d=None): return emb(f"{E.ON} {t}", d, C.SUCCESS)
def err(t, d=None): return emb(f"{E.OFF} {t}", d, C.ERROR)
def warn(t, d=None): return emb(f"{E.WARN} {t}", d, C.WARNING)

# ============================================
# MENUS DE CONFIGURATION
# ============================================

class MainMenu(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
    
    async def interaction_check(self, i): 
        if i.user.id != self.user.id:
            await i.response.send_message("❌ Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True
    
    def get_embed(self):
        e = emb(f"{E.CONFIG} Configuration de {self.guild.name}", 
               "Sélectionnez une catégorie ci-dessous.", C.CONFIG)
        e.add_field(name=f"{E.ADMIN} Modération", value="Sanctions et commandes", inline=True)
        e.add_field(name=f"{E.LOGS} Logs", value="Salons de logs", inline=True)
        e.add_field(name=f"{E.PROTECT} Protection", value="Anti-spam, liens...", inline=True)
        e.add_field(name=f"{E.ROLES} Rôles", value="Staff et immunisés", inline=True)
        e.add_field(name="👋 Bienvenue", value="Messages d'accueil", inline=True)
        e.add_field(name=f"{E.STATS} Stats", value="Statistiques", inline=True)
        if self.guild.icon: e.set_thumbnail(url=self.guild.icon.url)
        e.set_footer(text=f"Par {self.user}")
        return e
    
    @discord.ui.button(label="Modération", emoji="⚔️", style=discord.ButtonStyle.primary, row=0)
    async def mod_btn(self, i, b):
        v = ModMenu(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def logs_btn(self, i, b):
        v = LogsMenu(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot_btn(self, i, b):
        v = ProtectMenu(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)
    
    @discord.ui.button(label="Rôles", emoji="👥", style=discord.ButtonStyle.primary, row=1)
    async def roles_btn(self, i, b):
        v = RolesMenu(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.primary, row=1)
    async def welc_btn(self, i, b):
        v = WelcomeMenu(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)
    
    @discord.ui.button(label="Stats", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
    async def stats_btn(self, i, b):
        cfg = await get_cfg(self.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=?', (self.guild.id,))
            warns = (await cur.fetchone())[0]
            cur = await db.execute('SELECT COUNT(*) FROM mod_logs WHERE guild_id=?', (self.guild.id,))
            actions = (await cur.fetchone())[0]
        e = emb(f"{E.STATS} Statistiques", color=C.PRIMARY)
        e.add_field(name="👥 Membres", value=f"```{self.guild.member_count}```", inline=True)
        e.add_field(name="📝 Salons", value=f"```{len(self.guild.channels)}```", inline=True)
        e.add_field(name="🎭 Rôles", value=f"```{len(self.guild.roles)}```", inline=True)
        e.add_field(name="⚠️ Warns", value=f"```{warns}```", inline=True)
        e.add_field(name="📜 Actions mod", value=f"```{actions}```", inline=True)
        prots = sum([cfg['anti_link'], cfg['anti_image'], cfg['anti_phishing'], cfg['anti_spam']])
        e.add_field(name="🛡️ Protections", value=f"```{prots}/4```", inline=True)
        await i.response.edit_message(embed=e, view=BackBtn(self.user, self.guild))
    
    @discord.ui.button(label="Fermer", emoji="❌", style=discord.ButtonStyle.danger, row=2)
    async def close_btn(self, i, b):
        await i.message.delete()

class BackBtn(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def back(self, i, b):
        v = MainMenu(self.user, self.guild)
        await i.response.edit_message(embed=v.get_embed(), view=v)

# --- MODÉRATION ---
class ModMenu(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
    
    async def get_embed(self):
        cfg = await get_cfg(self.guild.id)
        mute_role = self.guild.get_role(cfg['mute_role'])
        e = emb(f"{E.ADMIN} Modération", "Configuration des sanctions et commandes.", C.MOD)
        e.add_field(name="🔇 Rôle Mute", value=mute_role.mention if mute_role else "`Non configuré`", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        e.add_field(name="⚖️ Sanctions automatiques", value=f"""
🔇 Mute après **{cfg['warns_mute']}** warns {' (désactivé)' if not cfg['warns_mute'] else ''}
👢 Kick après **{cfg['warns_kick']}** warns {' (désactivé)' if not cfg['warns_kick'] else ''}
🔨 Ban après **{cfg['warns_ban']}** warns {' (désactivé)' if not cfg['warns_ban'] else ''}
""", inline=False)
        e.add_field(name="📋 Commandes disponibles", value="""
`/warn` `/warnings` `/clearwarns`
`/mute` `/unmute` `/timeout`
`/kick` `/ban` `/unban` `/clear`
`/modlogs`
""", inline=False)
        return e
    
    @discord.ui.button(label="Sanctions Auto", emoji="⚖️", style=discord.ButtonStyle.primary)
    async def sanctions(self, i, b):
        await i.response.send_modal(SanctionsModal(self.guild, self.user))
    
    @discord.ui.button(label="Rôle Mute", emoji="🔇", style=discord.ButtonStyle.primary)
    async def mute_role(self, i, b):
        v = SelectRole(self.user, self.guild, "mute_role", "Rôle Mute", ModMenu)
        await i.response.edit_message(embed=v.get_embed(), view=v)
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def back(self, i, b):
        v = MainMenu(self.user, self.guild)
        await i.response.edit_message(embed=v.get_embed(), view=v)

class SanctionsModal(Modal, title="⚖️ Sanctions Automatiques"):
    w_mute = TextInput(label="Warns pour MUTE (0=désactivé)", placeholder="3", required=False, max_length=2)
    w_kick = TextInput(label="Warns pour KICK (0=désactivé)", placeholder="5", required=False, max_length=2)
    w_ban = TextInput(label="Warns pour BAN (0=désactivé)", placeholder="7", required=False, max_length=2)
    
    def __init__(self, guild, user):
        super().__init__()
        self.guild, self.user = guild, user
    
    async def on_submit(self, i):
        m = int(self.w_mute.value) if self.w_mute.value.isdigit() else 0
        k = int(self.w_kick.value) if self.w_kick.value.isdigit() else 0
        b = int(self.w_ban.value) if self.w_ban.value.isdigit() else 0
        await set_cfg(self.guild.id, warns_mute=m, warns_kick=k, warns_ban=b)
        e = ok("Sanctions configurées !")
        e.add_field(name="🔇 Mute", value=f"**{m}** warns" if m else "Désactivé", inline=True)
        e.add_field(name="👢 Kick", value=f"**{k}** warns" if k else "Désactivé", inline=True)
        e.add_field(name="🔨 Ban", value=f"**{b}** warns" if b else "Désactivé", inline=True)
        await i.response.send_message(embed=e, ephemeral=True)

# --- LOGS ---
class LogsMenu(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
    
    async def get_embed(self):
        cfg = await get_cfg(self.guild.id)
        log_ch = self.guild.get_channel(cfg['log_channel'])
        mod_ch = self.guild.get_channel(cfg['mod_log_channel'])
        e = emb(f"{E.LOGS} Configuration des Logs", "Définissez où envoyer les logs.", C.LOGS)
        e.add_field(name="📜 Logs Généraux", value=log_ch.mention if log_ch else "`Non configuré`", inline=True)
        e.add_field(name="⚔️ Logs Modération", value=mod_ch.mention if mod_ch else "`Non configuré`", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        e.add_field(name="ℹ️ Logs Généraux", value="Messages supprimés/modifiés\nArrivées/départs", inline=True)
        e.add_field(name="ℹ️ Logs Modération", value="Warn, mute, kick, ban...", inline=True)
        return e
    
    @discord.ui.button(label="Logs Généraux", emoji="📜", style=discord.ButtonStyle.primary)
    async def gen_logs(self, i, b):
        v = SelectChannel(self.user, self.guild, "log_channel", "Logs Généraux", LogsMenu)
        await i.response.edit_message(embed=v.get_embed(), view=v)
    
    @discord.ui.button(label="Logs Modération", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def mod_logs(self, i, b):
        v = SelectChannel(self.user, self.guild, "mod_log_channel", "Logs Modération", LogsMenu)
        await i.response.edit_message(embed=v.get_embed(), view=v)
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def back(self, i, b):
        v = MainMenu(self.user, self.guild)
        await i.response.edit_message(embed=v.get_embed(), view=v)

class SelectChannel(View):
    def __init__(self, user, guild, key, title, back_to):
        super().__init__(timeout=300)
        self.user, self.guild, self.key, self.title, self.back_to = user, guild, key, title, back_to
        opts = [discord.SelectOption(label=ch.name, value=str(ch.id), emoji="📝") for ch in guild.text_channels[:25]]
        if opts:
            sel = Select(placeholder="Sélectionnez un salon...", options=opts)
            sel.callback = self.sel_cb
            self.add_item(sel)
    
    def get_embed(self):
        return emb(f"📝 {self.title}", "Sélectionnez un salon.", C.CONFIG)
    
    async def sel_cb(self, i):
        ch_id = int(i.data['values'][0])
        await set_cfg(self.guild.id, **{self.key: ch_id})
        ch = self.guild.get_channel(ch_id)
        await i.response.send_message(embed=ok(f"{self.title} configuré", f"Salon: {ch.mention}"), ephemeral=True)
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = self.back_to(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)

class SelectRole(View):
    def __init__(self, user, guild, key, title, back_to):
        super().__init__(timeout=300)
        self.user, self.guild, self.key, self.title, self.back_to = user, guild, key, title, back_to
        opts = [discord.SelectOption(label=r.name, value=str(r.id), emoji="🎭") for r in guild.roles[1:25] if not r.is_bot_managed()]
        if opts:
            sel = Select(placeholder="Sélectionnez un rôle...", options=opts)
            sel.callback = self.sel_cb
            self.add_item(sel)
    
    def get_embed(self):
        return emb(f"🎭 {self.title}", "Sélectionnez un rôle.", C.CONFIG)
    
    async def sel_cb(self, i):
        role_id = int(i.data['values'][0])
        await set_cfg(self.guild.id, **{self.key: role_id})
        role = self.guild.get_role(role_id)
        await i.response.send_message(embed=ok(f"{self.title} configuré", f"Rôle: {role.mention}"), ephemeral=True)
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = self.back_to(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)

# --- PROTECTION ---
class ProtectMenu(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
    
    async def get_embed(self):
        cfg = await get_cfg(self.guild.id)
        e = emb(f"{E.PROTECT} Protections", "Cliquez pour activer/désactiver.", C.PROTECT)
        e.add_field(name=f"{'✅' if cfg['anti_link'] else '❌'} Anti-Liens", value="Bloque les liens", inline=True)
        e.add_field(name=f"{'✅' if cfg['anti_image'] else '❌'} Anti-Images", value="Bloque les images", inline=True)
        e.add_field(name=f"{'✅' if cfg['anti_phishing'] else '❌'} Anti-Phishing", value="Bloque les scams", inline=True)
        e.add_field(name=f"{'✅' if cfg['anti_spam'] else '❌'} Anti-Spam", value="Bloque le spam", inline=True)
        return e
    
    @discord.ui.button(label="Anti-Liens", emoji="🔗", style=discord.ButtonStyle.primary)
    async def al(self, i, b):
        cfg = await get_cfg(self.guild.id)
        await set_cfg(self.guild.id, anti_link=not cfg['anti_link'])
        await i.response.edit_message(embed=await self.get_embed(), view=self)
    
    @discord.ui.button(label="Anti-Images", emoji="🖼️", style=discord.ButtonStyle.primary)
    async def ai(self, i, b):
        cfg = await get_cfg(self.guild.id)
        await set_cfg(self.guild.id, anti_image=not cfg['anti_image'])
        await i.response.edit_message(embed=await self.get_embed(), view=self)
    
    @discord.ui.button(label="Anti-Phishing", emoji="🎣", style=discord.ButtonStyle.primary)
    async def ap(self, i, b):
        cfg = await get_cfg(self.guild.id)
        await set_cfg(self.guild.id, anti_phishing=not cfg['anti_phishing'])
        await i.response.edit_message(embed=await self.get_embed(), view=self)
    
    @discord.ui.button(label="Anti-Spam", emoji="📨", style=discord.ButtonStyle.primary)
    async def asp(self, i, b):
        cfg = await get_cfg(self.guild.id)
        await set_cfg(self.guild.id, anti_spam=not cfg['anti_spam'])
        await i.response.edit_message(embed=await self.get_embed(), view=self)
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainMenu(self.user, self.guild)
        await i.response.edit_message(embed=v.get_embed(), view=v)

# --- RÔLES ---
class RolesMenu(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
    
    async def get_embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id=?', (self.guild.id,))
            staff_ids = [r[0] for r in await cur.fetchall()]
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.guild.id,))
            immune_ids = [r[0] for r in await cur.fetchall()]
        staff = [self.guild.get_role(rid) for rid in staff_ids if self.guild.get_role(rid)]
        immune = [self.guild.get_role(rid) for rid in immune_ids if self.guild.get_role(rid)]
        e = emb(f"{E.ROLES} Gestion des Rôles", color=C.CONFIG)
        e.add_field(name="👮 Rôles Staff", value=", ".join([r.mention for r in staff]) or "`Aucun`", inline=False)
        e.add_field(name="👑 Rôles Immunisés", value=", ".join([r.mention for r in immune]) or "`Aucun`", inline=False)
        e.add_field(name="ℹ️ Staff", value="Peuvent utiliser les commandes de modération", inline=True)
        e.add_field(name="ℹ️ Immunisés", value="Ne peuvent pas recevoir de sanctions", inline=True)
        return e
    
    @discord.ui.button(label="+ Staff", emoji="➕", style=discord.ButtonStyle.success)
    async def add_staff(self, i, b):
        v = AddRole(self.user, self.guild, "staff_roles", "Staff")
        await i.response.edit_message(embed=v.get_embed(), view=v)
    
    @discord.ui.button(label="- Staff", emoji="➖", style=discord.ButtonStyle.danger)
    async def rem_staff(self, i, b):
        v = RemRole(self.user, self.guild, "staff_roles", "Staff")
        await i.response.edit_message(embed=await v.get_embed(), view=v)
    
    @discord.ui.button(label="+ Immunisé", emoji="➕", style=discord.ButtonStyle.success)
    async def add_imm(self, i, b):
        v = AddRole(self.user, self.guild, "immune_roles", "Immunisé")
        await i.response.edit_message(embed=v.get_embed(), view=v)
    
    @discord.ui.button(label="- Immunisé", emoji="➖", style=discord.ButtonStyle.danger)
    async def rem_imm(self, i, b):
        v = RemRole(self.user, self.guild, "immune_roles", "Immunisé")
        await i.response.edit_message(embed=await v.get_embed(), view=v)
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainMenu(self.user, self.guild)
        await i.response.edit_message(embed=v.get_embed(), view=v)

class AddRole(View):
    def __init__(self, user, guild, table, typ):
        super().__init__(timeout=300)
        self.user, self.guild, self.table, self.typ = user, guild, table, typ
        opts = [discord.SelectOption(label=r.name, value=str(r.id)) for r in guild.roles[1:25] if not r.is_bot_managed()]
        if opts:
            sel = Select(placeholder=f"Ajouter un rôle {typ}...", options=opts)
            sel.callback = self.sel_cb
            self.add_item(sel)
    
    def get_embed(self):
        return emb(f"➕ Ajouter {self.typ}", color=C.SUCCESS)
    
    async def sel_cb(self, i):
        rid = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f'INSERT OR IGNORE INTO {self.table} VALUES (?,?)', (self.guild.id, rid))
            await db.commit()
        role = self.guild.get_role(rid)
        await i.response.send_message(embed=ok(f"{self.typ} ajouté", role.mention), ephemeral=True)
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = RolesMenu(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)

class RemRole(View):
    def __init__(self, user, guild, table, typ):
        super().__init__(timeout=300)
        self.user, self.guild, self.table, self.typ = user, guild, table, typ
    
    async def get_embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(f'SELECT role_id FROM {self.table} WHERE guild_id=?', (self.guild.id,))
            ids = [r[0] for r in await cur.fetchall()]
        if ids:
            opts = [discord.SelectOption(label=self.guild.get_role(rid).name if self.guild.get_role(rid) else "?", value=str(rid)) for rid in ids if self.guild.get_role(rid)]
            if opts:
                sel = Select(placeholder=f"Retirer un rôle {self.typ}...", options=opts)
                sel.callback = self.sel_cb
                self.add_item(sel)
        return emb(f"➖ Retirer {self.typ}", color=C.ERROR)
    
    async def sel_cb(self, i):
        rid = int(i.data['values'][0])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f'DELETE FROM {self.table} WHERE guild_id=? AND role_id=?', (self.guild.id, rid))
            await db.commit()
        role = self.guild.get_role(rid)
        await i.response.send_message(embed=ok(f"{self.typ} retiré", role.mention if role else "Rôle"), ephemeral=True)
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = RolesMenu(self.user, self.guild)
        await i.response.edit_message(embed=await v.get_embed(), view=v)

# --- BIENVENUE ---
class WelcomeMenu(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user, self.guild = user, guild
    
    async def get_embed(self):
        cfg = await get_cfg(self.guild.id)
        ch = self.guild.get_channel(cfg['welcome_channel'])
        e = emb("👋 Bienvenue", "Configurez les messages de bienvenue.", C.SUCCESS)
        e.add_field(name="État", value="✅ Activé" if cfg['welcome_on'] else "❌ Désactivé", inline=True)
        e.add_field(name="Salon", value=ch.mention if ch else "`Non configuré`", inline=True)
        e.add_field(name="Message", value=f"```{cfg['welcome_msg']}```", inline=False)
        e.add_field(name="Variables", value="`{member}` = mention\n`{server}` = nom serveur\n`{count}` = nb membres", inline=False)
        return e
    
    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary)
    async def toggle(self, i, b):
        cfg = await get_cfg(self.guild.id)
        await set_cfg(self.guild.id, welcome_on=not cfg['welcome_on'])
        await i.response.edit_message(embed=await self.get_embed(), view=self)
    
    @discord.ui.button(label="Salon", emoji="📝", style=discord.ButtonStyle.primary)
    async def channel(self, i, b):
        v = SelectChannel(self.user, self.guild, "welcome_channel", "Salon Bienvenue", WelcomeMenu)
        await i.response.edit_message(embed=v.get_embed(), view=v)
    
    @discord.ui.button(label="Message", emoji="✏️", style=discord.ButtonStyle.primary)
    async def msg(self, i, b):
        await i.response.send_modal(WelcomeModal(self.guild))
    
    @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def back(self, i, b):
        v = MainMenu(self.user, self.guild)
        await i.response.edit_message(embed=v.get_embed(), view=v)

class WelcomeModal(Modal, title="✏️ Message de Bienvenue"):
    msg = TextInput(label="Message", style=discord.TextStyle.paragraph, placeholder="Bienvenue {member} !", max_length=500)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i):
        await set_cfg(self.guild.id, welcome_msg=self.msg.value)
        await i.response.send_message(embed=ok("Message configuré", f"```{self.msg.value}```"), ephemeral=True)

# ============================================
# ÉVÉNEMENTS
# ============================================

@bot.event
async def on_ready():
    bot.start_time = datetime.utcnow()
    await init_db()
    try:
        await bot.tree.sync()
        print(f"✅ Commandes synchronisées")
    except Exception as e: print(f"❌ {e}")
    print(f"✅ Bot: {bot.user}")
    print(f"✅ Serveurs: {len(bot.guilds)}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/configure"))

@bot.event
async def on_guild_join(g): await get_cfg(g.id)

@bot.event
async def on_member_join(m):
    cfg = await get_cfg(m.guild.id)
    if cfg['welcome_on'] and cfg['welcome_channel']:
        ch = m.guild.get_channel(cfg['welcome_channel'])
        if ch:
            msg = cfg['welcome_msg'].format(member=m.mention, server=m.guild.name, count=m.guild.member_count)
            e = emb("👋 Bienvenue !", msg, C.SUCCESS, thumb=m.display_avatar.url)
            await ch.send(embed=e)
    e = emb("👋 Nouveau Membre", color=C.SUCCESS, thumb=m.display_avatar.url)
    e.add_field(name="Membre", value=f"{m.mention}\n`{m.id}`", inline=True)
    e.add_field(name="Compte créé", value=f"<t:{int(m.created_at.timestamp())}:R>", inline=True)
    await send_log(m.guild, e)

@bot.event
async def on_member_remove(m):
    e = emb("👋 Membre Parti", color=C.ERROR, thumb=m.display_avatar.url)
    e.add_field(name="Membre", value=f"`{m}`\n`{m.id}`", inline=True)
    await send_log(m.guild, e)

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    if await is_immune(msg.author): return
    cfg = await get_cfg(msg.guild.id)
    PHISH = ['discord-nitro.gift', 'discordgift.site', 'free-nitro.com', 'steampowered.ru']
    if cfg['anti_phishing']:
        for d in PHISH:
            if d in msg.content.lower():
                await msg.delete()
                await msg.channel.send(embed=warn("Phishing détecté", f"{msg.author.mention}"), delete_after=10)
                return
    if cfg['anti_link'] and re.search(r'https?://[^\s]+', msg.content):
        await msg.delete()
        await msg.channel.send(embed=warn("Lien non autorisé", f"{msg.author.mention}"), delete_after=10)
        return
    if cfg['anti_image'] and msg.attachments:
        for a in msg.attachments:
            if a.filename.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp')):
                await msg.delete()
                await msg.channel.send(embed=warn("Image non autorisée", f"{msg.author.mention}"), delete_after=10)
                return

@bot.event
async def on_message_delete(msg):
    if msg.author.bot or not msg.guild: return
    e = emb("🗑️ Message Supprimé", color=C.WARNING, thumb=msg.author.display_avatar.url)
    e.add_field(name="Auteur", value=msg.author.mention, inline=True)
    e.add_field(name="Salon", value=msg.channel.mention, inline=True)
    if msg.content: e.add_field(name="Contenu", value=f"```{msg.content[:500]}```", inline=False)
    await send_log(msg.guild, e)

@bot.event
async def on_message_edit(b, a):
    if b.author.bot or not b.guild or b.content == a.content: return
    e = emb("✏️ Message Modifié", color=C.PRIMARY, thumb=b.author.display_avatar.url)
    e.add_field(name="Auteur", value=b.author.mention, inline=True)
    e.add_field(name="Salon", value=b.channel.mention, inline=True)
    e.add_field(name="Avant", value=f"```{b.content[:300]}```", inline=False)
    e.add_field(name="Après", value=f"```{a.content[:300]}```", inline=False)
    await send_log(b.guild, e)

# ============================================
# COMMANDES
# ============================================

@bot.tree.command(name="configure", description="⚙️ Panneau de configuration")
async def configure(i: discord.Interaction):
    if i.user.id != i.guild.owner_id and not i.user.guild_permissions.administrator:
        return await i.response.send_message(embed=err("Accès refusé", "Réservé aux administrateurs."), ephemeral=True)
    v = MainMenu(i.user, i.guild)
    await i.response.send_message(embed=v.get_embed(), view=v, ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.default_permissions(moderate_members=True)
async def warn_cmd(i: discord.Interaction, member: discord.Member, reason: str = "Aucune raison"):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    if await is_immune(member): return await i.response.send_message(embed=err("Membre immunisé"), ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO warns (guild_id,user_id,mod_id,reason) VALUES (?,?,?,?)', (i.guild.id,member.id,i.user.id,reason))
        await db.commit()
        cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?', (i.guild.id,member.id))
        cnt = (await cur.fetchone())[0]
        await db.execute('INSERT INTO mod_logs (guild_id,user_id,mod_id,action,reason) VALUES (?,?,?,?,?)', (i.guild.id,member.id,i.user.id,"WARN",reason))
        await db.commit()
    e = emb(f"{E.WARN} Warn", f"{member.mention} averti", C.WARNING, thumb=member.display_avatar.url)
    e.add_field(name="Membre", value=member.mention, inline=True)
    e.add_field(name="Par", value=i.user.mention, inline=True)
    e.add_field(name="Total", value=f"**{cnt}**", inline=True)
    e.add_field(name="Raison", value=f"```{reason}```", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)
    await send_log(i.guild, e, True)
    cfg = await get_cfg(i.guild.id)
    if cfg['warns_ban'] and cnt >= cfg['warns_ban']:
        await member.ban(reason=f"[AUTO] {cnt} warns")
        await i.followup.send(embed=warn("Ban Auto", f"{member}"), ephemeral=True)
    elif cfg['warns_kick'] and cnt >= cfg['warns_kick']:
        await member.kick(reason=f"[AUTO] {cnt} warns")
        await i.followup.send(embed=warn("Kick Auto", f"{member}"), ephemeral=True)
    elif cfg['warns_mute'] and cnt >= cfg['warns_mute']:
        r = i.guild.get_role(cfg['mute_role'])
        if r: await member.add_roles(r); await i.followup.send(embed=warn("Mute Auto", f"{member}"), ephemeral=True)

@bot.tree.command(name="warnings", description="📋 Voir les warns")
@app_commands.default_permissions(moderate_members=True)
async def warnings_cmd(i: discord.Interaction, member: discord.Member):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM warns WHERE guild_id=? AND user_id=? ORDER BY ts DESC', (i.guild.id,member.id))
        ws = [dict(r) for r in await cur.fetchall()]
    e = emb(f"{E.LOGS} Warns de {member}", f"**{len(ws)}** warns", C.WARNING, thumb=member.display_avatar.url)
    for w in ws[:5]:
        mod = i.guild.get_member(w['mod_id'])
        e.add_field(name=f"#{w['id']} • {str(w['ts'])[:10]}", value=f"Par: {mod.name if mod else '?'}\nRaison: {w['reason']}", inline=False)
    if not ws: e.add_field(name="✅ Clean", value="Aucun warn", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="clearwarns", description="🗑️ Supprimer tous les warns")
@app_commands.default_permissions(administrator=True)
async def clearwarns_cmd(i: discord.Interaction, member: discord.Member):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?', (i.guild.id,member.id))
        cnt = (await cur.fetchone())[0]
        await db.execute('DELETE FROM warns WHERE guild_id=? AND user_id=?', (i.guild.id,member.id))
        await db.commit()
    await i.response.send_message(embed=ok("Warns supprimés", f"**{cnt}** warns pour {member.mention}"), ephemeral=True)

@bot.tree.command(name="mute", description="🔇 Mute un membre")
@app_commands.default_permissions(moderate_members=True)
async def mute_cmd(i: discord.Interaction, member: discord.Member, reason: str = "Aucune raison"):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    if await is_immune(member): return await i.response.send_message(embed=err("Membre immunisé"), ephemeral=True)
    cfg = await get_cfg(i.guild.id)
    r = i.guild.get_role(cfg['mute_role'])
    if not r: return await i.response.send_message(embed=err("Config", "Rôle mute non configuré → /configure"), ephemeral=True)
    await member.add_roles(r, reason=reason)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO mod_logs (guild_id,user_id,mod_id,action,reason) VALUES (?,?,?,?,?)', (i.guild.id,member.id,i.user.id,"MUTE",reason))
        await db.commit()
    e = emb(f"{E.MUTE} Mute", color=C.MOD, thumb=member.display_avatar.url)
    e.add_field(name="Membre", value=member.mention, inline=True)
    e.add_field(name="Par", value=i.user.mention, inline=True)
    e.add_field(name="Raison", value=f"```{reason}```", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)
    await send_log(i.guild, e, True)

@bot.tree.command(name="unmute", description="🔊 Unmute")
@app_commands.default_permissions(moderate_members=True)
async def unmute_cmd(i: discord.Interaction, member: discord.Member):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    cfg = await get_cfg(i.guild.id)
    r = i.guild.get_role(cfg['mute_role'])
    if r and r in member.roles:
        await member.remove_roles(r)
        await i.response.send_message(embed=ok("Unmute", member.mention), ephemeral=True)
    else:
        await i.response.send_message(embed=err("Non mute"), ephemeral=True)

@bot.tree.command(name="timeout", description="⏰ Timeout")
@app_commands.default_permissions(moderate_members=True)
async def timeout_cmd(i: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Aucune raison"):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    if await is_immune(member): return await i.response.send_message(embed=err("Membre immunisé"), ephemeral=True)
    await member.timeout(timedelta(minutes=min(40320, minutes)), reason=reason)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO mod_logs (guild_id,user_id,mod_id,action,reason) VALUES (?,?,?,?,?)', (i.guild.id,member.id,i.user.id,"TIMEOUT",reason))
        await db.commit()
    d = f"{minutes//1440}j" if minutes>=1440 else f"{minutes//60}h" if minutes>=60 else f"{minutes}m"
    e = emb(f"{E.TIMEOUT} Timeout", color=C.MOD, thumb=member.display_avatar.url)
    e.add_field(name="Membre", value=member.mention, inline=True)
    e.add_field(name="Durée", value=d, inline=True)
    e.add_field(name="Raison", value=f"```{reason}```", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)
    await send_log(i.guild, e, True)

@bot.tree.command(name="kick", description="👢 Kick")
@app_commands.default_permissions(kick_members=True)
async def kick_cmd(i: discord.Interaction, member: discord.Member, reason: str = "Aucune raison"):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    if await is_immune(member): return await i.response.send_message(embed=err("Membre immunisé"), ephemeral=True)
    n, av = str(member), member.display_avatar.url
    await member.kick(reason=reason)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO mod_logs (guild_id,user_id,mod_id,action,reason) VALUES (?,?,?,?,?)', (i.guild.id,member.id,i.user.id,"KICK",reason))
        await db.commit()
    e = emb(f"{E.KICK} Kick", color=C.ERROR, thumb=av)
    e.add_field(name="Membre", value=f"`{n}`", inline=True)
    e.add_field(name="Par", value=i.user.mention, inline=True)
    e.add_field(name="Raison", value=f"```{reason}```", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)
    await send_log(i.guild, e, True)

@bot.tree.command(name="ban", description="🔨 Ban")
@app_commands.default_permissions(ban_members=True)
async def ban_cmd(i: discord.Interaction, member: discord.Member, reason: str = "Aucune raison"):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    if await is_immune(member): return await i.response.send_message(embed=err("Membre immunisé"), ephemeral=True)
    n, av = str(member), member.display_avatar.url
    await member.ban(reason=reason)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO mod_logs (guild_id,user_id,mod_id,action,reason) VALUES (?,?,?,?,?)', (i.guild.id,member.id,i.user.id,"BAN",reason))
        await db.commit()
    e = emb(f"{E.BAN} Ban", color=C.ERROR, thumb=av)
    e.add_field(name="Membre", value=f"`{n}`", inline=True)
    e.add_field(name="Par", value=i.user.mention, inline=True)
    e.add_field(name="Raison", value=f"```{reason}```", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)
    await send_log(i.guild, e, True)

@bot.tree.command(name="unban", description="🔓 Unban")
@app_commands.default_permissions(ban_members=True)
async def unban_cmd(i: discord.Interaction, user_id: str):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    try:
        u = await bot.fetch_user(int(user_id))
        await i.guild.unban(u)
        await i.response.send_message(embed=ok("Unban", f"`{u}`"), ephemeral=True)
    except: await i.response.send_message(embed=err("Erreur", "ID invalide"), ephemeral=True)

@bot.tree.command(name="clear", description="🗑️ Supprimer messages")
@app_commands.default_permissions(manage_messages=True)
async def clear_cmd(i: discord.Interaction, amount: int):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    await i.response.defer(ephemeral=True)
    d = await i.channel.purge(limit=min(100, max(1, amount)))
    await i.followup.send(embed=ok("Supprimés", f"**{len(d)}** messages"), ephemeral=True)

@bot.tree.command(name="modlogs", description="📜 Historique sanctions")
@app_commands.default_permissions(moderate_members=True)
async def modlogs_cmd(i: discord.Interaction, member: discord.Member):
    if not await is_staff(i.user): return await i.response.send_message(embed=err("Permission refusée"), ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM mod_logs WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 10', (i.guild.id,member.id))
        logs = [dict(r) for r in await cur.fetchall()]
    emo = {"WARN":"⚠️","MUTE":"🔇","UNMUTE":"🔊","TIMEOUT":"⏰","KICK":"👢","BAN":"🔨"}
    e = emb(f"{E.LOGS} Historique de {member}", f"**{len(logs)}** actions", C.PRIMARY, thumb=member.display_avatar.url)
    for l in logs:
        mod = i.guild.get_member(l['mod_id'])
        e.add_field(name=f"{emo.get(l['action'],'📝')} {l['action']} • {str(l['ts'])[:10]}", value=f"Par: {mod.name if mod else '?'}\nRaison: {l['reason'] or 'N/A'}", inline=False)
    if not logs: e.add_field(name="✅ Vide", value="Aucune sanction", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="help", description="📚 Aide")
async def help_cmd(i: discord.Interaction):
    e = emb("📚 Aide", "Utilisez `/configure` pour le panneau interactif.", C.PRIMARY, thumb=bot.user.display_avatar.url)
    e.add_field(name="⚙️ Configuration", value="`/configure`", inline=False)
    e.add_field(name="⚔️ Modération", value="`/warn` `/warnings` `/clearwarns`\n`/mute` `/unmute` `/timeout`\n`/kick` `/ban` `/unban` `/clear`\n`/modlogs`", inline=False)
    e.add_field(name="📊 Autres", value="`/status` `/help`", inline=False)
    await i.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="status", description="📊 Statut")
async def status_cmd(i: discord.Interaction):
    up = datetime.utcnow() - bot.start_time
    h, r = divmod(int(up.total_seconds()), 3600)
    m, s = divmod(r, 60)
    d, h = divmod(h, 24)
    t = f"{d}j {h}h {m}m" if d else f"{h}h {m}m {s}s"
    e = emb("📊 Statut", color=C.PRIMARY, thumb=bot.user.display_avatar.url)
    e.add_field(name="🤖 Bot", value=f"`{bot.user}`", inline=True)
    e.add_field(name="📡 Ping", value=f"`{round(bot.latency*1000)}ms`", inline=True)
    e.add_field(name="⏱️ Uptime", value=f"`{t}`", inline=True)
    e.add_field(name="🏠 Serveurs", value=f"`{len(bot.guilds)}`", inline=True)
    e.add_field(name="👥 Membres", value=f"`{sum(g.member_count for g in bot.guilds)}`", inline=True)
    await i.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="shutdown", description="🔴 Éteindre")
async def shutdown_cmd(i: discord.Interaction):
    if i.user.id != OWNER_ID: return await i.response.send_message(embed=err("Accès refusé"), ephemeral=True)
    await i.response.send_message(embed=warn("Arrêt", "Bot en cours d'arrêt..."), ephemeral=True)
    await asyncio.sleep(2)
    await bot.close()

@bot.tree.error
async def on_err(i, e):
    try: await i.response.send_message(embed=err("Erreur", f"```{str(e)[:200]}```"), ephemeral=True)
    except: await i.followup.send(embed=err("Erreur", f"```{str(e)[:200]}```"), ephemeral=True)

# ============================================
# LANCEMENT
# ============================================

if __name__ == "__main__":
    print("🚀 Démarrage...")
    bot.run(TOKEN)
