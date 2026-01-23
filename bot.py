# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                                                                               ║
# ║                        🌟 BOT TOUT-EN-UN PREMIUM 🌟                           ║
# ║                                                                               ║
# ║                    Une seule commande : /configure                            ║
# ║                    Tout se gère depuis le panneau                             ║
# ║                                                                               ║
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
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
DB = 'database.db'

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎨 DESIGN SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

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
    DARK = 0x2C2F33

class Box:
    """Caractères pour les boîtes"""
    TL = "╭"  # Top Left
    TR = "╮"  # Top Right
    BL = "╰"  # Bottom Left
    BR = "╯"  # Bottom Right
    H = "─"   # Horizontal
    V = "│"   # Vertical
    
    @staticmethod
    def create(title, content, width=40):
        """Crée une boîte stylisée"""
        lines = content.split('\n')
        box = f"{Box.TL}{Box.H * 2} {title} {Box.H * (width - len(title) - 4)}{Box.TR}\n"
        for line in lines:
            padding = width - len(line) - 2
            box += f"{Box.V} {line}{' ' * padding}{Box.V}\n"
        box += f"{Box.BL}{Box.H * width}{Box.BR}"
        return box

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
            welcome_on INTEGER DEFAULT 0, welcome_msg TEXT DEFAULT 'Bienvenue {member} ! 🎉')''')
        await db.execute('''CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
            mod_id INTEGER, reason TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS staff_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS mod_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
            mod_id INTEGER, action TEXT, reason TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.commit()
    print("✅ Database initialisée")

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
                'welcome_on': 0, 'welcome_msg': 'Bienvenue {member} ! 🎉'}

async def set_config(gid, **kw):
    async with aiosqlite.connect(DB) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE config SET {k}=? WHERE guild_id=?', (v, gid))
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
        super().__init__(timeout=900)  # 15 minutes
        self.user = user
        self.guild = guild
    
    async def interaction_check(self, interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ **Ce panneau ne vous appartient pas**", color=Color.RED),
                ephemeral=True
            )
            return False
        return True
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        
        # Stats
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute('SELECT COUNT(*) FROM staff_roles WHERE guild_id=?', (self.guild.id,))
            staff_count = (await cur.fetchone())[0]
            cur = await db.execute('SELECT COUNT(*) FROM immune_roles WHERE guild_id=?', (self.guild.id,))
            immune_count = (await cur.fetchone())[0]
            cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=?', (self.guild.id,))
            warns_count = (await cur.fetchone())[0]
            cur = await db.execute('SELECT COUNT(*) FROM mod_logs WHERE guild_id=?', (self.guild.id,))
            actions_count = (await cur.fetchone())[0]
        
        prots = sum([c['anti_link'], c['anti_image'], c['anti_phishing'], c['anti_spam']])
        
        embed = discord.Embed(color=Color.BLURPLE)
        
        # Header avec ASCII art stylisé
        embed.title = "⚙️ Panneau de Configuration"
        
        embed.description = f"""
```ansi
[2;34m╔══════════════════════════════════════════════════╗[0m
[2;34m║[0m  [1;37m🎛️  CENTRE DE CONTRÔLE[0m                          [2;34m║[0m
[2;34m║[0m  [2;37mGérez votre serveur en toute simplicité[0m         [2;34m║[0m
[2;34m╚══════════════════════════════════════════════════╝[0m
```
"""
        
        # Statistiques en bloc de code
        stats = f"""```yml
📊 Aperçu Rapide
────────────────────────────────
👥 Membres       : {self.guild.member_count}
🛡️ Protections   : {prots}/4 actives
👮 Rôles Staff   : {staff_count}
👑 Immunisés     : {immune_count}
⚠️ Warns actifs  : {warns_count}
📜 Actions mod   : {actions_count}
────────────────────────────────
```"""
        embed.add_field(name="​", value=stats, inline=False)
        
        # Menu des catégories
        menu = """```yml
📂 Catégories Disponibles
────────────────────────────────
⚔️ Modération    → Sanctions, warns, mute...
📜 Logs          → Configurer les salons de logs
🛡️ Protection    → Anti-spam, anti-link...
👥 Rôles         → Staff et immunisés
👋 Bienvenue     → Messages d'accueil
📊 Statistiques  → Données du serveur
────────────────────────────────
```"""
        embed.add_field(name="​", value=menu, inline=False)
        
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        
        embed.set_footer(
            text=f"👤 {self.user.display_name} • Expire dans 15 minutes",
            icon_url=self.user.display_avatar.url
        )
        
        embed.set_author(
            name=self.guild.name,
            icon_url=self.guild.icon.url if self.guild.icon else None
        )
        
        return embed
    
    @discord.ui.button(label="Modération", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def mod_btn(self, interaction, button):
        view = ModerationPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.create_embed(), view=view)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def logs_btn(self, interaction, button):
        view = LogsPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.create_embed(), view=view)
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot_btn(self, interaction, button):
        view = ProtectionPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.create_embed(), view=view)
    
    @discord.ui.button(label="Rôles", emoji="👥", style=discord.ButtonStyle.secondary, row=1)
    async def roles_btn(self, interaction, button):
        view = RolesPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.create_embed(), view=view)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def welcome_btn(self, interaction, button):
        view = WelcomePanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.create_embed(), view=view)
    
    @discord.ui.button(label="Statistiques", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
    async def stats_btn(self, interaction, button):
        view = StatsPanel(self.user, self.guild)
        await interaction.response.edit_message(embed=await view.create_embed(), view=view)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close_btn(self, interaction, button):
        embed = discord.Embed(
            description="```\n✅ Panneau de configuration fermé\n```",
            color=Color.GREEN
        )
        await interaction.response.edit_message(embed=embed, view=None)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚔️ PANNEAU MODÉRATION
# ═══════════════════════════════════════════════════════════════════════════════

class ModerationPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def interaction_check(self, i):
        return i.user.id == self.user.id
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        mute_role = self.guild.get_role(c['mute_role'])
        
        embed = discord.Embed(color=Color.PINK)
        embed.title = "⚔️ Centre de Modération"
        
        # Configuration actuelle
        config_box = f"""```yml
📋 Configuration Actuelle
────────────────────────────────
🔇 Rôle Mute : {mute_role.name if mute_role else '❌ Non configuré'}
────────────────────────────────

⚖️ Sanctions Automatiques
────────────────────────────────
🔇 Mute après  : {f'{c["warns_mute"]} warns' if c['warns_mute'] else '❌ Désactivé'}
👢 Kick après  : {f'{c["warns_kick"]} warns' if c['warns_kick'] else '❌ Désactivé'}
🔨 Ban après   : {f'{c["warns_ban"]} warns' if c['warns_ban'] else '❌ Désactivé'}
────────────────────────────────
```"""
        embed.description = config_box
        
        # Actions disponibles
        actions = """```yml
🎮 Actions Disponibles
────────────────────────────────
⚠️ Warn      → Avertir un membre
🔇 Mute      → Rendre muet
👢 Kick      → Expulser du serveur
🔨 Ban       → Bannir définitivement
📋 Warns     → Voir les avertissements
🗑️ Clear     → Supprimer des warns
────────────────────────────────
```"""
        embed.add_field(name="​", value=actions, inline=False)
        
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        
        return embed
    
    @discord.ui.button(label="Warn", emoji="⚠️", style=discord.ButtonStyle.danger, row=0)
    async def warn_btn(self, i, b):
        await i.response.send_modal(WarnModal(self.guild, self.user))
    
    @discord.ui.button(label="Mute", emoji="🔇", style=discord.ButtonStyle.danger, row=0)
    async def mute_btn(self, i, b):
        await i.response.send_modal(MuteModal(self.guild, self.user))
    
    @discord.ui.button(label="Kick", emoji="👢", style=discord.ButtonStyle.danger, row=0)
    async def kick_btn(self, i, b):
        await i.response.send_modal(KickModal(self.guild, self.user))
    
    @discord.ui.button(label="Ban", emoji="🔨", style=discord.ButtonStyle.danger, row=0)
    async def ban_btn(self, i, b):
        await i.response.send_modal(BanModal(self.guild, self.user))
    
    @discord.ui.button(label="Voir Warns", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def view_warns_btn(self, i, b):
        await i.response.send_modal(ViewWarnsModal(self.guild))
    
    @discord.ui.button(label="Clear Warns", emoji="🗑️", style=discord.ButtonStyle.secondary, row=1)
    async def clear_warns_btn(self, i, b):
        await i.response.send_modal(ClearWarnsModal(self.guild))
    
    @discord.ui.button(label="Unmute", emoji="🔊", style=discord.ButtonStyle.success, row=1)
    async def unmute_btn(self, i, b):
        await i.response.send_modal(UnmuteModal(self.guild, self.user))
    
    @discord.ui.button(label="Config Sanctions", emoji="⚖️", style=discord.ButtonStyle.primary, row=2)
    async def sanctions_btn(self, i, b):
        await i.response.send_modal(SanctionsModal(self.guild))
    
    @discord.ui.button(label="Rôle Mute", emoji="🎭", style=discord.ButtonStyle.primary, row=2)
    async def mute_role_btn(self, i, b):
        view = SelectRoleForConfig(self.user, self.guild, "mute_role", "Rôle Mute", ModerationPanel)
        await i.response.edit_message(embed=view.create_embed(), view=view)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, i, b):
        view = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                              📝 MODALS MODÉRATION
# ═══════════════════════════════════════════════════════════════════════════════

class WarnModal(Modal, title="⚠️ Avertir un membre"):
    member_id = TextInput(label="ID du membre", placeholder="Clic droit sur le membre → Copier l'identifiant", max_length=20)
    reason = TextInput(label="Raison de l'avertissement", placeholder="Raison...", style=discord.TextStyle.paragraph, required=False, max_length=200)
    
    def __init__(self, guild, mod):
        super().__init__()
        self.guild = guild
        self.mod = mod
    
    async def on_submit(self, interaction):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member:
                return await interaction.response.send_message(embed=self.error("Membre introuvable"), ephemeral=True)
            if await is_immune(member):
                return await interaction.response.send_message(embed=self.error("Ce membre est immunisé"), ephemeral=True)
            if member.id == self.mod.id:
                return await interaction.response.send_message(embed=self.error("Vous ne pouvez pas vous warn vous-même"), ephemeral=True)
            
            reason = self.reason.value or "Aucune raison spécifiée"
            
            async with aiosqlite.connect(DB) as db:
                await db.execute('INSERT INTO warns (guild_id, user_id, mod_id, reason) VALUES (?,?,?,?)',
                                (self.guild.id, member.id, self.mod.id, reason))
                await db.commit()
                cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?', (self.guild.id, member.id))
                count = (await cur.fetchone())[0]
                await db.execute('INSERT INTO mod_logs (guild_id, user_id, mod_id, action, reason) VALUES (?,?,?,?,?)',
                                (self.guild.id, member.id, self.mod.id, "WARN", reason))
                await db.commit()
            
            embed = discord.Embed(color=Color.YELLOW)
            embed.title = "⚠️ Avertissement"
            embed.description = f"""```yml
✅ Membre averti avec succès
────────────────────────────────
👤 Membre     : {member}
👮 Modérateur : {self.mod}
📊 Total      : {count} warn(s)
📝 Raison     : {reason}
────────────────────────────────
```"""
            embed.set_thumbnail(url=member.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Log
            log_embed = discord.Embed(title="⚠️ Nouveau Warn", color=Color.YELLOW)
            log_embed.add_field(name="Membre", value=f"{member.mention} (`{member.id}`)", inline=True)
            log_embed.add_field(name="Modérateur", value=self.mod.mention, inline=True)
            log_embed.add_field(name="Total warns", value=str(count), inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            log_embed.set_thumbnail(url=member.display_avatar.url)
            await send_log(self.guild, log_embed, True)
            
            # Sanctions auto
            c = await get_config(self.guild.id)
            if c['warns_ban'] and count >= c['warns_ban']:
                await member.ban(reason=f"[AUTO] {count} warns atteints")
                await interaction.followup.send(embed=self.success(f"🔨 **{member}** a été banni automatiquement ({count} warns)"), ephemeral=True)
            elif c['warns_kick'] and count >= c['warns_kick']:
                await member.kick(reason=f"[AUTO] {count} warns atteints")
                await interaction.followup.send(embed=self.success(f"👢 **{member}** a été expulsé automatiquement ({count} warns)"), ephemeral=True)
            elif c['warns_mute'] and count >= c['warns_mute']:
                role = self.guild.get_role(c['mute_role'])
                if role:
                    await member.add_roles(role)
                    await interaction.followup.send(embed=self.success(f"🔇 **{member}** a été mute automatiquement ({count} warns)"), ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message(embed=self.error("ID invalide"), ephemeral=True)
    
    def error(self, msg):
        return discord.Embed(description=f"```\n❌ {msg}\n```", color=Color.RED)
    
    def success(self, msg):
        return discord.Embed(description=f"```\n{msg}\n```", color=Color.GREEN)

class MuteModal(Modal, title="🔇 Mute un membre"):
    member_id = TextInput(label="ID du membre", placeholder="Clic droit → Copier l'identifiant", max_length=20)
    reason = TextInput(label="Raison", placeholder="Raison du mute...", required=False, max_length=200)
    
    def __init__(self, guild, mod):
        super().__init__()
        self.guild = guild
        self.mod = mod
    
    async def on_submit(self, interaction):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member:
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Membre introuvable\n```", color=Color.RED), ephemeral=True)
            if await is_immune(member):
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Ce membre est immunisé\n```", color=Color.RED), ephemeral=True)
            
            c = await get_config(self.guild.id)
            role = self.guild.get_role(c['mute_role'])
            if not role:
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Rôle mute non configuré\n```", color=Color.RED), ephemeral=True)
            
            reason = self.reason.value or "Aucune raison"
            await member.add_roles(role, reason=reason)
            
            async with aiosqlite.connect(DB) as db:
                await db.execute('INSERT INTO mod_logs (guild_id, user_id, mod_id, action, reason) VALUES (?,?,?,?,?)',
                                (self.guild.id, member.id, self.mod.id, "MUTE", reason))
                await db.commit()
            
            embed = discord.Embed(color=Color.PINK)
            embed.description = f"""```yml
🔇 Membre mute avec succès
────────────────────────────────
👤 Membre     : {member}
👮 Modérateur : {self.mod}
📝 Raison     : {reason}
────────────────────────────────
```"""
            embed.set_thumbnail(url=member.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            log_embed = discord.Embed(title="🔇 Mute", color=Color.PINK)
            log_embed.add_field(name="Membre", value=f"{member.mention}", inline=True)
            log_embed.add_field(name="Modérateur", value=self.mod.mention, inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            await send_log(self.guild, log_embed, True)
            
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(description="```\n❌ ID invalide\n```", color=Color.RED), ephemeral=True)

class UnmuteModal(Modal, title="🔊 Unmute un membre"):
    member_id = TextInput(label="ID du membre", placeholder="Clic droit → Copier l'identifiant", max_length=20)
    
    def __init__(self, guild, mod):
        super().__init__()
        self.guild = guild
        self.mod = mod
    
    async def on_submit(self, interaction):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member:
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Membre introuvable\n```", color=Color.RED), ephemeral=True)
            
            c = await get_config(self.guild.id)
            role = self.guild.get_role(c['mute_role'])
            
            if role and role in member.roles:
                await member.remove_roles(role)
                embed = discord.Embed(description=f"```\n🔊 {member} a été unmute\n```", color=Color.GREEN)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Ce membre n'est pas mute\n```", color=Color.RED), ephemeral=True)
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(description="```\n❌ ID invalide\n```", color=Color.RED), ephemeral=True)

class KickModal(Modal, title="👢 Expulser un membre"):
    member_id = TextInput(label="ID du membre", placeholder="Clic droit → Copier l'identifiant", max_length=20)
    reason = TextInput(label="Raison", placeholder="Raison de l'expulsion...", required=False, max_length=200)
    
    def __init__(self, guild, mod):
        super().__init__()
        self.guild = guild
        self.mod = mod
    
    async def on_submit(self, interaction):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member:
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Membre introuvable\n```", color=Color.RED), ephemeral=True)
            if await is_immune(member):
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Ce membre est immunisé\n```", color=Color.RED), ephemeral=True)
            
            reason = self.reason.value or "Aucune raison"
            name = str(member)
            avatar = member.display_avatar.url
            await member.kick(reason=reason)
            
            async with aiosqlite.connect(DB) as db:
                await db.execute('INSERT INTO mod_logs (guild_id, user_id, mod_id, action, reason) VALUES (?,?,?,?,?)',
                                (self.guild.id, member.id, self.mod.id, "KICK", reason))
                await db.commit()
            
            embed = discord.Embed(color=Color.RED)
            embed.description = f"""```yml
👢 Membre expulsé
────────────────────────────────
👤 Membre     : {name}
👮 Modérateur : {self.mod}
📝 Raison     : {reason}
────────────────────────────────
```"""
            embed.set_thumbnail(url=avatar)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            log_embed = discord.Embed(title="👢 Expulsion", color=Color.RED)
            log_embed.add_field(name="Membre", value=f"`{name}`", inline=True)
            log_embed.add_field(name="Modérateur", value=self.mod.mention, inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            await send_log(self.guild, log_embed, True)
            
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(description="```\n❌ ID invalide\n```", color=Color.RED), ephemeral=True)

class BanModal(Modal, title="🔨 Bannir un membre"):
    member_id = TextInput(label="ID du membre", placeholder="Clic droit → Copier l'identifiant", max_length=20)
    reason = TextInput(label="Raison", placeholder="Raison du bannissement...", required=False, max_length=200)
    
    def __init__(self, guild, mod):
        super().__init__()
        self.guild = guild
        self.mod = mod
    
    async def on_submit(self, interaction):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member:
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Membre introuvable\n```", color=Color.RED), ephemeral=True)
            if await is_immune(member):
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Ce membre est immunisé\n```", color=Color.RED), ephemeral=True)
            
            reason = self.reason.value or "Aucune raison"
            name = str(member)
            avatar = member.display_avatar.url
            await member.ban(reason=reason)
            
            async with aiosqlite.connect(DB) as db:
                await db.execute('INSERT INTO mod_logs (guild_id, user_id, mod_id, action, reason) VALUES (?,?,?,?,?)',
                                (self.guild.id, member.id, self.mod.id, "BAN", reason))
                await db.commit()
            
            embed = discord.Embed(color=Color.RED)
            embed.description = f"""```yml
🔨 Membre banni
────────────────────────────────
👤 Membre     : {name}
👮 Modérateur : {self.mod}
📝 Raison     : {reason}
────────────────────────────────
```"""
            embed.set_thumbnail(url=avatar)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            log_embed = discord.Embed(title="🔨 Bannissement", color=Color.RED)
            log_embed.add_field(name="Membre", value=f"`{name}`", inline=True)
            log_embed.add_field(name="Modérateur", value=self.mod.mention, inline=True)
            log_embed.add_field(name="Raison", value=reason, inline=False)
            await send_log(self.guild, log_embed, True)
            
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(description="```\n❌ ID invalide\n```", color=Color.RED), ephemeral=True)

class ViewWarnsModal(Modal, title="📋 Voir les warns d'un membre"):
    member_id = TextInput(label="ID du membre", placeholder="Clic droit → Copier l'identifiant", max_length=20)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    
    async def on_submit(self, interaction):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member:
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Membre introuvable\n```", color=Color.RED), ephemeral=True)
            
            async with aiosqlite.connect(DB) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute('SELECT * FROM warns WHERE guild_id=? AND user_id=? ORDER BY ts DESC LIMIT 10', (self.guild.id, member.id))
                warns = [dict(r) for r in await cur.fetchall()]
            
            if not warns:
                embed = discord.Embed(description=f"```\n✅ {member} n'a aucun avertissement\n```", color=Color.GREEN)
                embed.set_thumbnail(url=member.display_avatar.url)
                return await interaction.response.send_message(embed=embed, ephemeral=True)
            
            embed = discord.Embed(title=f"📋 Warns de {member}", color=Color.YELLOW)
            embed.set_thumbnail(url=member.display_avatar.url)
            
            warns_text = f"```yml\nTotal : {len(warns)} avertissement(s)\n────────────────────────────────\n"
            for w in warns[:5]:
                mod = self.guild.get_member(w['mod_id'])
                mod_name = mod.name if mod else "Inconnu"
                date = str(w['ts'])[:10]
                warns_text += f"#{w['id']} │ {date}\n"
                warns_text += f"   Par : {mod_name}\n"
                warns_text += f"   Raison : {w['reason'][:30]}...\n\n"
            warns_text += "────────────────────────────────```"
            
            embed.description = warns_text
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(description="```\n❌ ID invalide\n```", color=Color.RED), ephemeral=True)

class ClearWarnsModal(Modal, title="🗑️ Supprimer les warns"):
    member_id = TextInput(label="ID du membre", placeholder="Clic droit → Copier l'identifiant", max_length=20)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    
    async def on_submit(self, interaction):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member:
                return await interaction.response.send_message(embed=discord.Embed(description="```\n❌ Membre introuvable\n```", color=Color.RED), ephemeral=True)
            
            async with aiosqlite.connect(DB) as db:
                cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?', (self.guild.id, member.id))
                count = (await cur.fetchone())[0]
                await db.execute('DELETE FROM warns WHERE guild_id=? AND user_id=?', (self.guild.id, member.id))
                await db.commit()
            
            embed = discord.Embed(description=f"```\n🗑️ {count} warn(s) supprimé(s) pour {member}\n```", color=Color.GREEN)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except ValueError:
            await interaction.response.send_message(embed=discord.Embed(description="```\n❌ ID invalide\n```", color=Color.RED), ephemeral=True)

class SanctionsModal(Modal, title="⚖️ Sanctions Automatiques"):
    warns_mute = TextInput(label="Warns pour MUTE (0 = désactivé)", placeholder="Ex: 3", required=False, max_length=2)
    warns_kick = TextInput(label="Warns pour KICK (0 = désactivé)", placeholder="Ex: 5", required=False, max_length=2)
    warns_ban = TextInput(label="Warns pour BAN (0 = désactivé)", placeholder="Ex: 7", required=False, max_length=2)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    
    async def on_submit(self, interaction):
        m = int(self.warns_mute.value) if self.warns_mute.value.isdigit() else 0
        k = int(self.warns_kick.value) if self.warns_kick.value.isdigit() else 0
        b = int(self.warns_ban.value) if self.warns_ban.value.isdigit() else 0
        
        await set_config(self.guild.id, warns_mute=m, warns_kick=k, warns_ban=b)
        
        embed = discord.Embed(color=Color.GREEN)
        embed.description = f"""```yml
✅ Sanctions configurées
────────────────────────────────
🔇 Mute après : {f'{m} warns' if m else 'Désactivé'}
👢 Kick après : {f'{k} warns' if k else 'Désactivé'}
🔨 Ban après  : {f'{b} warns' if b else 'Désactivé'}
────────────────────────────────
```"""
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              📜 PANNEAU LOGS
# ═══════════════════════════════════════════════════════════════════════════════

class LogsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        log_ch = self.guild.get_channel(c['log_channel'])
        mod_ch = self.guild.get_channel(c['mod_log_channel'])
        
        embed = discord.Embed(title="📜 Configuration des Logs", color=Color.PURPLE)
        embed.description = f"""```yml
📊 Salons Configurés
────────────────────────────────
📝 Logs Généraux   : {f'#{log_ch.name}' if log_ch else '❌ Non configuré'}
⚔️ Logs Modération : {f'#{mod_ch.name}' if mod_ch else '❌ Non configuré'}
────────────────────────────────

📖 Description des Logs
────────────────────────────────
📝 Logs Généraux
   • Messages supprimés
   • Messages modifiés
   • Arrivées de membres
   • Départs de membres

⚔️ Logs Modération
   • Avertissements (warns)
   • Mutes / Unmutes
   • Kicks
   • Bans / Unbans
────────────────────────────────
```"""
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        return embed
    
    @discord.ui.button(label="Logs Généraux", emoji="📝", style=discord.ButtonStyle.primary)
    async def general_btn(self, i, b):
        view = SelectChannelForConfig(self.user, self.guild, "log_channel", "Logs Généraux", LogsPanel)
        await i.response.edit_message(embed=view.create_embed(), view=view)
    
    @discord.ui.button(label="Logs Modération", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def mod_btn(self, i, b):
        view = SelectChannelForConfig(self.user, self.guild, "mod_log_channel", "Logs Modération", LogsPanel)
        await i.response.edit_message(embed=view.create_embed(), view=view)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        view = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                            🛡️ PANNEAU PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

class ProtectionPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        
        def status(val):
            return "✅ Activé" if val else "❌ Désactivé"
        
        embed = discord.Embed(title="🛡️ Protections du Serveur", color=Color.BLUE)
        embed.description = f"""```yml
📊 État des Protections
────────────────────────────────
🔗 Anti-Liens    : {status(c['anti_link'])}
🖼️ Anti-Images   : {status(c['anti_image'])}
🎣 Anti-Phishing : {status(c['anti_phishing'])}
📨 Anti-Spam     : {status(c['anti_spam'])}
────────────────────────────────

📖 Description
────────────────────────────────
🔗 Anti-Liens
   Supprime automatiquement tous
   les liens postés

🖼️ Anti-Images
   Supprime automatiquement toutes
   les images envoyées

🎣 Anti-Phishing
   Détecte et supprime les liens
   de scam/phishing Discord/Steam

📨 Anti-Spam
   Empêche le spam de messages
   répétitifs
────────────────────────────────

💡 Cliquez sur un bouton pour
   activer/désactiver
```"""
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        return embed
    
    @discord.ui.button(label="Anti-Liens", emoji="🔗", style=discord.ButtonStyle.primary)
    async def link_btn(self, i, b):
        c = await get_config(self.guild.id)
        await set_config(self.guild.id, anti_link=not c['anti_link'])
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="Anti-Images", emoji="🖼️", style=discord.ButtonStyle.primary)
    async def image_btn(self, i, b):
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
        view = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                              👥 PANNEAU RÔLES
# ═══════════════════════════════════════════════════════════════════════════════

class RolesPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def create_embed(self):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id=?', (self.guild.id,))
            staff_ids = [r[0] for r in await cur.fetchall()]
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.guild.id,))
            immune_ids = [r[0] for r in await cur.fetchall()]
        
        staff_roles = [self.guild.get_role(rid) for rid in staff_ids if self.guild.get_role(rid)]
        immune_roles = [self.guild.get_role(rid) for rid in immune_ids if self.guild.get_role(rid)]
        
        staff_list = '\n   • '.join([r.name for r in staff_roles]) if staff_roles else "Aucun"
        immune_list = '\n   • '.join([r.name for r in immune_roles]) if immune_roles else "Aucun"
        
        embed = discord.Embed(title="👥 Gestion des Rôles", color=Color.ORANGE)
        embed.description = f"""```yml
👮 Rôles Staff ({len(staff_roles)})
────────────────────────────────
   • {staff_list}
────────────────────────────────
   Ces rôles peuvent utiliser
   les commandes de modération

👑 Rôles Immunisés ({len(immune_roles)})
────────────────────────────────
   • {immune_list}
────────────────────────────────
   Ces rôles ne peuvent pas
   recevoir de sanctions
```"""
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        return embed
    
    @discord.ui.button(label="+ Staff", emoji="👮", style=discord.ButtonStyle.success)
    async def add_staff(self, i, b):
        view = AddRoleView(self.user, self.guild, "staff_roles", "Staff")
        await i.response.edit_message(embed=view.create_embed(), view=view)
    
    @discord.ui.button(label="- Staff", emoji="👮", style=discord.ButtonStyle.danger)
    async def rem_staff(self, i, b):
        view = RemoveRoleView(self.user, self.guild, "staff_roles", "Staff")
        await i.response.edit_message(embed=await view.create_embed(), view=view)
    
    @discord.ui.button(label="+ Immunisé", emoji="👑", style=discord.ButtonStyle.success)
    async def add_immune(self, i, b):
        view = AddRoleView(self.user, self.guild, "immune_roles", "Immunisé")
        await i.response.edit_message(embed=view.create_embed(), view=view)
    
    @discord.ui.button(label="- Immunisé", emoji="👑", style=discord.ButtonStyle.danger)
    async def rem_immune(self, i, b):
        view = RemoveRoleView(self.user, self.guild, "immune_roles", "Immunisé")
        await i.response.edit_message(embed=await view.create_embed(), view=view)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        view = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                            👋 PANNEAU BIENVENUE
# ═══════════════════════════════════════════════════════════════════════════════

class WelcomePanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        ch = self.guild.get_channel(c['welcome_channel'])
        
        embed = discord.Embed(title="👋 Messages de Bienvenue", color=Color.GREEN)
        embed.description = f"""```yml
📊 Configuration
────────────────────────────────
État  : {'✅ Activé' if c['welcome_on'] else '❌ Désactivé'}
Salon : {f'#{ch.name}' if ch else '❌ Non configuré'}
────────────────────────────────

💬 Message Actuel
────────────────────────────────
{c['welcome_msg']}
────────────────────────────────

📝 Variables Disponibles
────────────────────────────────
{{member}} → Mentionne le membre
{{server}} → Nom du serveur  
{{count}}  → Nombre de membres
────────────────────────────────

💡 Exemple de résultat :
"Bienvenue @User sur MonServeur !
Tu es le membre #150"
```"""
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        return embed
    
    @discord.ui.button(label="ON / OFF", emoji="🔄", style=discord.ButtonStyle.primary)
    async def toggle_btn(self, i, b):
        c = await get_config(self.guild.id)
        await set_config(self.guild.id, welcome_on=not c['welcome_on'])
        await i.response.edit_message(embed=await self.create_embed(), view=self)
    
    @discord.ui.button(label="Choisir Salon", emoji="📝", style=discord.ButtonStyle.primary)
    async def channel_btn(self, i, b):
        view = SelectChannelForConfig(self.user, self.guild, "welcome_channel", "Salon Bienvenue", WelcomePanel)
        await i.response.edit_message(embed=view.create_embed(), view=view)
    
    @discord.ui.button(label="Modifier Message", emoji="✏️", style=discord.ButtonStyle.primary)
    async def msg_btn(self, i, b):
        await i.response.send_modal(WelcomeMessageModal(self.guild))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        view = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

class WelcomeMessageModal(Modal, title="✏️ Message de Bienvenue"):
    message = TextInput(label="Message", style=discord.TextStyle.paragraph,
                       placeholder="Bienvenue {member} sur {server} ! Tu es le membre #{count}",
                       max_length=500)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    
    async def on_submit(self, interaction):
        await set_config(self.guild.id, welcome_msg=self.message.value)
        embed = discord.Embed(color=Color.GREEN)
        embed.description = f"""```yml
✅ Message de bienvenue configuré
────────────────────────────────
{self.message.value}
────────────────────────────────
```"""
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 PANNEAU STATISTIQUES
# ═══════════════════════════════════════════════════════════════════════════════

class StatsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=?', (self.guild.id,))
            warns = (await cur.fetchone())[0]
            cur = await db.execute('SELECT COUNT(*) FROM mod_logs WHERE guild_id=?', (self.guild.id,))
            actions = (await cur.fetchone())[0]
            cur = await db.execute('SELECT action, COUNT(*) FROM mod_logs WHERE guild_id=? GROUP BY action', (self.guild.id,))
            by_action = {r[0]: r[1] for r in await cur.fetchall()}
        
        prots = sum([c['anti_link'], c['anti_image'], c['anti_phishing'], c['anti_spam']])
        online = len([m for m in self.guild.members if m.status != discord.Status.offline])
        bots = len([m for m in self.guild.members if m.bot])
        humans = self.guild.member_count - bots
        
        embed = discord.Embed(title="📊 Statistiques du Serveur", color=Color.CYAN)
        embed.description = f"""```yml
👥 Membres
────────────────────────────────
Total      : {self.guild.member_count}
Humains    : {humans}
Bots       : {bots}
En ligne   : {online}
────────────────────────────────

🏠 Serveur
────────────────────────────────
Salons     : {len(self.guild.channels)}
Rôles      : {len(self.guild.roles)}
Emojis     : {len(self.guild.emojis)}
Boosts     : {self.guild.premium_subscription_count}
Niveau     : {self.guild.premium_tier}
────────────────────────────────

⚔️ Modération
────────────────────────────────
Warns      : {warns}
Actions    : {actions}
├ Mutes    : {by_action.get('MUTE', 0)}
├ Kicks    : {by_action.get('KICK', 0)}
└ Bans     : {by_action.get('BAN', 0)}
────────────────────────────────

🛡️ Protection
────────────────────────────────
Actives    : {prots}/4
────────────────────────────────
```"""
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        return embed
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
    async def back_btn(self, i, b):
        view = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔧 VUES UTILITAIRES
# ═══════════════════════════════════════════════════════════════════════════════

class SelectChannelForConfig(View):
    def __init__(self, user, guild, config_key, title, back_panel):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.config_key = config_key
        self.title = title
        self.back_panel = back_panel
        
        options = [discord.SelectOption(label=f"#{ch.name}", value=str(ch.id), emoji="📝")
                   for ch in guild.text_channels[:25]]
        if options:
            select = Select(placeholder="📝 Sélectionnez un salon...", options=options)
            select.callback = self.select_callback
            self.add_item(select)
    
    def create_embed(self):
        return discord.Embed(
            title=f"📝 Sélection : {self.title}",
            description="```\nChoisissez un salon dans le menu ci-dessous\n```",
            color=Color.BLURPLE
        )
    
    async def select_callback(self, interaction):
        channel_id = int(interaction.data['values'][0])
        await set_config(self.guild.id, **{self.config_key: channel_id})
        channel = self.guild.get_channel(channel_id)
        embed = discord.Embed(description=f"```\n✅ {self.title} → #{channel.name}\n```", color=Color.GREEN)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        view = self.back_panel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

class SelectRoleForConfig(View):
    def __init__(self, user, guild, config_key, title, back_panel):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.config_key = config_key
        self.title = title
        self.back_panel = back_panel
        
        options = [discord.SelectOption(label=f"@{r.name}", value=str(r.id), emoji="🎭")
                   for r in guild.roles[1:25] if not r.is_bot_managed()]
        if options:
            select = Select(placeholder="🎭 Sélectionnez un rôle...", options=options)
            select.callback = self.select_callback
            self.add_item(select)
    
    def create_embed(self):
        return discord.Embed(
            title=f"🎭 Sélection : {self.title}",
            description="```\nChoisissez un rôle dans le menu ci-dessous\n```",
            color=Color.BLURPLE
        )
    
    async def select_callback(self, interaction):
        role_id = int(interaction.data['values'][0])
        await set_config(self.guild.id, **{self.config_key: role_id})
        role = self.guild.get_role(role_id)
        embed = discord.Embed(description=f"```\n✅ {self.title} → @{role.name}\n```", color=Color.GREEN)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        view = self.back_panel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

class AddRoleView(View):
    def __init__(self, user, guild, table, role_type):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.table = table
        self.role_type = role_type
        
        options = [discord.SelectOption(label=f"@{r.name}", value=str(r.id))
                   for r in guild.roles[1:25] if not r.is_bot_managed()]
        if options:
            select = Select(placeholder=f"➕ Ajouter un rôle {role_type}...", options=options)
            select.callback = self.select_callback
            self.add_item(select)
    
    def create_embed(self):
        return discord.Embed(
            title=f"➕ Ajouter un rôle {self.role_type}",
            description="```\nSélectionnez un rôle dans le menu\n```",
            color=Color.GREEN
        )
    
    async def select_callback(self, interaction):
        role_id = int(interaction.data['values'][0])
        async with aiosqlite.connect(DB) as db:
            await db.execute(f'INSERT OR IGNORE INTO {self.table} VALUES (?,?)', (self.guild.id, role_id))
            await db.commit()
        role = self.guild.get_role(role_id)
        embed = discord.Embed(description=f"```\n✅ @{role.name} ajouté aux {self.role_type}s\n```", color=Color.GREEN)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        view = RolesPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

class RemoveRoleView(View):
    def __init__(self, user, guild, table, role_type):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.table = table
        self.role_type = role_type
    
    async def create_embed(self):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute(f'SELECT role_id FROM {self.table} WHERE guild_id=?', (self.guild.id,))
            role_ids = [r[0] for r in await cur.fetchall()]
        
        if role_ids:
            options = []
            for rid in role_ids:
                role = self.guild.get_role(rid)
                if role:
                    options.append(discord.SelectOption(label=f"@{role.name}", value=str(rid)))
            if options:
                select = Select(placeholder=f"➖ Retirer un rôle {self.role_type}...", options=options)
                select.callback = self.select_callback
                self.add_item(select)
        
        return discord.Embed(
            title=f"➖ Retirer un rôle {self.role_type}",
            description="```\nSélectionnez un rôle dans le menu\n```",
            color=Color.RED
        )
    
    async def select_callback(self, interaction):
        role_id = int(interaction.data['values'][0])
        async with aiosqlite.connect(DB) as db:
            await db.execute(f'DELETE FROM {self.table} WHERE guild_id=? AND role_id=?', (self.guild.id, role_id))
            await db.commit()
        role = self.guild.get_role(role_id)
        embed = discord.Embed(description=f"```\n✅ @{role.name if role else 'Rôle'} retiré des {self.role_type}s\n```", color=Color.GREEN)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        view = RolesPanel(self.user, self.guild)
        await i.response.edit_message(embed=await view.create_embed(), view=view)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 ÉVÉNEMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    bot.start_time = datetime.utcnow()
    await init_db()
    await bot.tree.sync()
    print(f"✅ Connecté : {bot.user}")
    print(f"✅ Serveurs : {len(bot.guilds)}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/configure"))

@bot.event
async def on_guild_join(guild):
    await get_config(guild.id)

@bot.event
async def on_member_join(member):
    c = await get_config(member.guild.id)
    
    # Message de bienvenue
    if c['welcome_on'] and c['welcome_channel']:
        ch = member.guild.get_channel(c['welcome_channel'])
        if ch:
            msg = c['welcome_msg'].format(
                member=member.mention,
                server=member.guild.name,
                count=member.guild.member_count
            )
            embed = discord.Embed(title="👋 Bienvenue !", description=msg, color=Color.GREEN)
            embed.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=embed)
    
    # Log
    embed = discord.Embed(title="👋 Nouveau membre", color=Color.GREEN)
    embed.add_field(name="Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
    embed.add_field(name="Compte créé", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await send_log(member.guild, embed)

@bot.event
async def on_member_remove(member):
    embed = discord.Embed(title="👋 Membre parti", color=Color.RED)
    embed.add_field(name="Membre", value=f"`{member}`\n`{member.id}`", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await send_log(member.guild, embed)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    if await is_immune(message.author):
        return
    
    c = await get_config(message.guild.id)
    
    # Anti-Phishing
    PHISHING_DOMAINS = ['discord-nitro.gift', 'discordgift.site', 'free-nitro.com', 'steampowered.ru', 'dlscord.com', 'discord-app.com']
    if c['anti_phishing']:
        for domain in PHISHING_DOMAINS:
            if domain in message.content.lower():
                await message.delete()
                embed = discord.Embed(description=f"```\n🎣 Lien de phishing détecté !\nMessage de {message.author} supprimé\n```", color=Color.RED)
                await message.channel.send(embed=embed, delete_after=10)
                return
    
    # Anti-Link
    if c['anti_link'] and re.search(r'https?://[^\s]+', message.content):
        await message.delete()
        embed = discord.Embed(description=f"```\n🔗 Liens non autorisés !\nMessage de {message.author} supprimé\n```", color=Color.YELLOW)
        await message.channel.send(embed=embed, delete_after=10)
        return
    
    # Anti-Image
    if c['anti_image'] and message.attachments:
        for att in message.attachments:
            if att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                await message.delete()
                embed = discord.Embed(description=f"```\n🖼️ Images non autorisées !\nMessage de {message.author} supprimé\n```", color=Color.YELLOW)
                await message.channel.send(embed=embed, delete_after=10)
                return

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return
    embed = discord.Embed(title="🗑️ Message supprimé", color=Color.YELLOW)
    embed.add_field(name="Auteur", value=message.author.mention, inline=True)
    embed.add_field(name="Salon", value=message.channel.mention, inline=True)
    if message.content:
        embed.add_field(name="Contenu", value=f"```{message.content[:500]}```", inline=False)
    embed.set_thumbnail(url=message.author.display_avatar.url)
    await send_log(message.guild, embed)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    embed = discord.Embed(title="✏️ Message modifié", color=Color.BLURPLE)
    embed.add_field(name="Auteur", value=before.author.mention, inline=True)
    embed.add_field(name="Salon", value=before.channel.mention, inline=True)
    embed.add_field(name="Avant", value=f"```{before.content[:300]}```", inline=False)
    embed.add_field(name="Après", value=f"```{after.content[:300]}```", inline=False)
    embed.set_thumbnail(url=before.author.display_avatar.url)
    await send_log(before.guild, embed)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDE UNIQUE : /configure
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Ouvrir le panneau de configuration du serveur")
async def configure_command(interaction: discord.Interaction):
    # Vérifier les permissions
    if not interaction.user.guild_permissions.administrator:
        if interaction.user.id != interaction.guild.owner_id:
            if not await is_staff(interaction.user):
                embed = discord.Embed(
                    description="```\n❌ Accès refusé\n\nVous devez être administrateur ou\navoir un rôle staff pour accéder\nau panneau de configuration.\n```",
                    color=Color.RED
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    view = MainPanel(interaction.user, interaction.guild)
    await interaction.response.send_message(embed=await view.create_embed(), view=view, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🚀 LANCEMENT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("═" * 50)
    print("🚀 Démarrage du bot...")
    print("═" * 50)
    bot.run(TOKEN)
