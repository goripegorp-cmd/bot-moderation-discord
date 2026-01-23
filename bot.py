# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                                                                               ║
# ║                        🌟 BOT TOUT-EN-UN PREMIUM 🌟                           ║
# ║                                                                               ║
# ║              Version 5.0 - Activité + Tickets + Modération                    ║
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

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 BASE DE DONNÉES
# ═══════════════════════════════════════════════════════════════════════════════

async def init_db():
    async with aiosqlite.connect(DB) as db:
        # Config serveur
        await db.execute('''CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            log_channel INTEGER, mod_log_channel INTEGER, welcome_channel INTEGER,
            mute_role INTEGER, warns_mute INTEGER DEFAULT 0, warns_kick INTEGER DEFAULT 0,
            warns_ban INTEGER DEFAULT 0, anti_link INTEGER DEFAULT 0, anti_image INTEGER DEFAULT 0,
            anti_phishing INTEGER DEFAULT 1, anti_spam INTEGER DEFAULT 0,
            welcome_on INTEGER DEFAULT 0, welcome_msg TEXT DEFAULT 'Bienvenue {member} ! 🎉')''')
        
        # Warns
        await db.execute('''CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
            mod_id INTEGER, reason TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        # Rôles
        await db.execute('''CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id))''')
        await db.execute('''CREATE TABLE IF NOT EXISTS staff_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY (guild_id, role_id))''')
        
        # Logs modération
        await db.execute('''CREATE TABLE IF NOT EXISTS mod_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
            mod_id INTEGER, action TEXT, reason TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        # 🆕 ACTIVITÉ DES MEMBRES
        await db.execute('''CREATE TABLE IF NOT EXISTS activity (
            guild_id INTEGER, user_id INTEGER,
            last_message DATETIME, last_voice DATETIME,
            PRIMARY KEY (guild_id, user_id))''')
        
        # 🆕 CONFIG TICKETS
        await db.execute('''CREATE TABLE IF NOT EXISTS ticket_config (
            guild_id INTEGER PRIMARY KEY,
            category_id INTEGER,
            staff_role_id INTEGER,
            ticket_name TEXT DEFAULT 'ticket-{user}-{number}',
            panel_channel_id INTEGER,
            panel_message_id INTEGER,
            panel_title TEXT DEFAULT '🎫 Support',
            panel_description TEXT DEFAULT 'Cliquez sur le bouton pour créer un ticket',
            panel_color INTEGER DEFAULT 5865F2,
            questions TEXT DEFAULT '[]')''')
        
        # 🆕 TICKETS
        await db.execute('''CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER, channel_id INTEGER, user_id INTEGER,
            claimed_by INTEGER, status TEXT DEFAULT 'open',
            answers TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
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

async def get_ticket_config(gid):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM ticket_config WHERE guild_id=?', (gid,))
        r = await cur.fetchone()
        if r: return dict(r)
        await db.execute('INSERT INTO ticket_config (guild_id) VALUES (?)', (gid,))
        await db.commit()
        return {'guild_id': gid, 'category_id': None, 'staff_role_id': None,
                'ticket_name': 'ticket-{user}-{number}', 'panel_channel_id': None,
                'panel_message_id': None, 'panel_title': '🎫 Support',
                'panel_description': 'Cliquez sur le bouton pour créer un ticket',
                'panel_color': 0x5865F2, 'questions': '[]'}

async def set_ticket_config(gid, **kw):
    async with aiosqlite.connect(DB) as db:
        for k, v in kw.items():
            await db.execute(f'UPDATE ticket_config SET {k}=? WHERE guild_id=?', (v, gid))
        await db.commit()

async def update_activity(gid, uid, msg=False, voice=False):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('SELECT * FROM activity WHERE guild_id=? AND user_id=?', (gid, uid))
        exists = await cur.fetchone()
        if exists:
            if msg:
                await db.execute('UPDATE activity SET last_message=? WHERE guild_id=? AND user_id=?', (now, gid, uid))
            if voice:
                await db.execute('UPDATE activity SET last_voice=? WHERE guild_id=? AND user_id=?', (now, gid, uid))
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
    
    async def interaction_check(self, interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(embed=discord.Embed(description="❌ **Ce panneau ne vous appartient pas**", color=Color.RED), ephemeral=True)
            return False
        return True
    
    async def create_embed(self):
        c = await get_config(self.guild.id)
        
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute('SELECT COUNT(*) FROM staff_roles WHERE guild_id=?', (self.guild.id,))
            staff_count = (await cur.fetchone())[0]
            cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=?', (self.guild.id,))
            warns_count = (await cur.fetchone())[0]
            cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status="open"', (self.guild.id,))
            tickets_open = (await cur.fetchone())[0]
        
        prots = sum([c['anti_link'], c['anti_image'], c['anti_phishing'], c['anti_spam']])
        
        embed = discord.Embed(color=Color.BLURPLE)
        embed.title = "⚙️ Panneau de Configuration"
        
        embed.description = f"""```yml
╔══════════════════════════════════════════╗
║     🎛️  CENTRE DE CONTRÔLE               ║
║     Gérez votre serveur simplement       ║
╚══════════════════════════════════════════╝

📊 Aperçu Rapide
────────────────────────────────────────────
👥 Membres       : {self.guild.member_count}
🛡️ Protections   : {prots}/4 actives
👮 Rôles Staff   : {staff_count}
⚠️ Warns actifs  : {warns_count}
🎫 Tickets ouverts: {tickets_open}
────────────────────────────────────────────

📂 Catégories Disponibles
────────────────────────────────────────────
⚔️ Modération  → Sanctions, warns...
📜 Logs        → Salons de logs
🛡️ Protection  → Anti-spam, anti-link...
👥 Rôles       → Staff et immunisés
👋 Bienvenue   → Messages d'accueil
📊 Activité    → Membres inactifs
🎫 Tickets     → Système de support
────────────────────────────────────────────
```"""
        
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name} • Expire dans 15 min", icon_url=self.user.display_avatar.url)
        embed.set_author(name=self.guild.name, icon_url=self.guild.icon.url if self.guild.icon else None)
        
        return embed
    
    @discord.ui.button(label="Modération", emoji="⚔️", style=discord.ButtonStyle.danger, row=0)
    async def mod_btn(self, i, b):
        v = ModerationPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.primary, row=0)
    async def logs_btn(self, i, b):
        v = LogsPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot_btn(self, i, b):
        v = ProtectionPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Rôles", emoji="👥", style=discord.ButtonStyle.secondary, row=1)
    async def roles_btn(self, i, b):
        v = RolesPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Bienvenue", emoji="👋", style=discord.ButtonStyle.success, row=1)
    async def welcome_btn(self, i, b):
        v = WelcomePanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Activité", emoji="📊", style=discord.ButtonStyle.secondary, row=1)
    async def activity_btn(self, i, b):
        v = ActivityPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.primary, row=2)
    async def tickets_btn(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close_btn(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 PANNEAU ACTIVITÉ
# ═══════════════════════════════════════════════════════════════════════════════

class ActivityPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def create_embed(self):
        now = datetime.utcnow()
        seven_days = now - timedelta(days=7)
        thirty_days = now - timedelta(days=30)
        
        inactive_7 = []
        inactive_30 = []
        
        async with aiosqlite.connect(DB) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM activity WHERE guild_id=?', (self.guild.id,))
            activities = {r['user_id']: dict(r) for r in await cur.fetchall()}
        
        for member in self.guild.members:
            if member.bot:
                continue
            
            act = activities.get(member.id)
            if not act:
                # Jamais d'activité enregistrée = inactif
                inactive_30.append(member)
                inactive_7.append(member)
                continue
            
            last_msg = datetime.fromisoformat(act['last_message']) if act['last_message'] else None
            last_voice = datetime.fromisoformat(act['last_voice']) if act['last_voice'] else None
            
            last_activity = max(filter(None, [last_msg, last_voice]), default=None)
            
            if not last_activity or last_activity < thirty_days:
                inactive_30.append(member)
            elif last_activity < seven_days:
                inactive_7.append(member)
        
        # Stocker pour les boutons
        self.inactive_7 = inactive_7
        self.inactive_30 = inactive_30
        
        embed = discord.Embed(title="📊 Activité des Membres", color=Color.ORANGE)
        embed.description = f"""```yml
╔══════════════════════════════════════════╗
║     📊 SUIVI D'ACTIVITÉ                  ║
║     Gérez les membres inactifs           ║
╚══════════════════════════════════════════╝

📈 Statistiques
────────────────────────────────────────────
👥 Total membres      : {self.guild.member_count}
🤖 Bots               : {len([m for m in self.guild.members if m.bot])}
👤 Humains            : {len([m for m in self.guild.members if not m.bot])}
────────────────────────────────────────────

⚠️ Inactifs 7 jours   : {len(inactive_7)} membres
   Aucun message ni vocal depuis 7 jours

🔴 Inactifs 30 jours  : {len(inactive_30)} membres
   Aucun message ni vocal depuis 30 jours
────────────────────────────────────────────

💡 Utilisez les boutons ci-dessous pour
   gérer les membres inactifs
```"""
        
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        
        return embed
    
    @discord.ui.button(label="Inactifs 7j", emoji="⚠️", style=discord.ButtonStyle.primary)
    async def inactive_7_btn(self, i, b):
        v = InactiveListPanel(self.user, self.guild, 7, self.inactive_7)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Inactifs 30j", emoji="🔴", style=discord.ButtonStyle.danger)
    async def inactive_30_btn(self, i, b):
        v = InactiveListPanel(self.user, self.guild, 30, self.inactive_30)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)


class InactiveListPanel(View):
    def __init__(self, user, guild, days, members):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
        self.days = days
        self.members = members[:100]  # Limite à 100
    
    async def create_embed(self):
        member_list = "\n".join([f"• {m.name}#{m.discriminator}" for m in self.members[:20]])
        if len(self.members) > 20:
            member_list += f"\n... et {len(self.members) - 20} autres"
        
        embed = discord.Embed(title=f"{'⚠️' if self.days == 7 else '🔴'} Membres Inactifs ({self.days} jours)", color=Color.ORANGE if self.days == 7 else Color.RED)
        embed.description = f"""```yml
📊 {len(self.members)} membres inactifs
────────────────────────────────────────────
Aucune activité depuis {self.days} jours
(pas de message ni de vocal)
────────────────────────────────────────────
```

**Liste des membres :**
```
{member_list if self.members else "Aucun membre inactif ! 🎉"}
```

⚠️ **Attention** : Les actions sont irréversibles !"""
        
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        return embed
    
    @discord.ui.button(label="📢 Mentionner tous", emoji="📢", style=discord.ButtonStyle.primary)
    async def mention_btn(self, i, b):
        if not self.members:
            return await i.response.send_message("```\n❌ Aucun membre à mentionner\n```", ephemeral=True)
        
        # Créer les mentions par batch de 20
        mentions = [m.mention for m in self.members[:50]]
        mention_text = " ".join(mentions)
        
        await i.response.send_message(f"📢 **Membres inactifs depuis {self.days} jours :**\n{mention_text}", ephemeral=False)
    
    @discord.ui.button(label="👢 Expulser tous", emoji="👢", style=discord.ButtonStyle.danger)
    async def kick_btn(self, i, b):
        if not self.members:
            return await i.response.send_message("```\n❌ Aucun membre à expulser\n```", ephemeral=True)
        
        # Confirmation
        v = ConfirmKickView(self.user, self.guild, self.members, self.days)
        embed = discord.Embed(
            title="⚠️ Confirmation",
            description=f"```yml\nÊtes-vous sûr de vouloir expulser\n{len(self.members)} membres inactifs ?\n\nCette action est IRRÉVERSIBLE !\n```",
            color=Color.RED
        )
        await i.response.edit_message(embed=embed, view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = ActivityPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)


class ConfirmKickView(View):
    def __init__(self, user, guild, members, days):
        super().__init__(timeout=60)
        self.user = user
        self.guild = guild
        self.members = members
        self.days = days
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def confirm_btn(self, i, b):
        await i.response.defer()
        
        kicked = 0
        failed = 0
        
        for member in self.members:
            try:
                await member.kick(reason=f"Inactif depuis {self.days} jours")
                kicked += 1
            except:
                failed += 1
        
        embed = discord.Embed(
            title="👢 Expulsion terminée",
            description=f"```yml\n✅ Expulsés : {kicked}\n❌ Échoués  : {failed}\n```",
            color=Color.GREEN
        )
        await i.edit_original_response(embed=embed, view=None)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, i, b):
        v = ActivityPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 SYSTÈME DE TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

class TicketConfigPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=900)
        self.user = user
        self.guild = guild
    
    async def create_embed(self):
        tc = await get_ticket_config(self.guild.id)
        
        category = self.guild.get_channel(tc['category_id'])
        staff_role = self.guild.get_role(tc['staff_role_id'])
        questions = json.loads(tc['questions']) if tc['questions'] else []
        
        # Compter tickets
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=? AND status="open"', (self.guild.id,))
            open_tickets = (await cur.fetchone())[0]
            cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=?', (self.guild.id,))
            total_tickets = (await cur.fetchone())[0]
        
        questions_list = "\n".join([f"   {i+1}. {q}" for i, q in enumerate(questions)]) if questions else "   Aucune question configurée"
        
        embed = discord.Embed(title="🎫 Configuration des Tickets", color=Color.PURPLE)
        embed.description = f"""```yml
╔══════════════════════════════════════════╗
║     🎫 SYSTÈME DE TICKETS                ║
║     Support et assistance                ║
╚══════════════════════════════════════════╝

📊 Statistiques
────────────────────────────────────────────
🎫 Tickets ouverts : {open_tickets}
📁 Total tickets   : {total_tickets}
────────────────────────────────────────────

⚙️ Configuration
────────────────────────────────────────────
📁 Catégorie : {category.name if category else '❌ Non configurée'}
👮 Rôle Staff: {staff_role.name if staff_role else '❌ Non configuré'}
📝 Nom format: {tc['ticket_name']}
────────────────────────────────────────────

❓ Questions ({len(questions)}/5)
────────────────────────────────────────────
{questions_list}
────────────────────────────────────────────

🎨 Panneau
────────────────────────────────────────────
Titre : {tc['panel_title']}
Description : {tc['panel_description'][:30]}...
────────────────────────────────────────────
```"""
        
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        embed.set_footer(text=f"👤 {self.user.display_name}", icon_url=self.user.display_avatar.url)
        
        return embed
    
    @discord.ui.button(label="Catégorie", emoji="📁", style=discord.ButtonStyle.primary, row=0)
    async def category_btn(self, i, b):
        v = SelectCategoryView(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)
    
    @discord.ui.button(label="Rôle Staff", emoji="👮", style=discord.ButtonStyle.primary, row=0)
    async def staff_btn(self, i, b):
        v = SelectTicketStaffView(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)
    
    @discord.ui.button(label="Nom Format", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def name_btn(self, i, b):
        await i.response.send_modal(TicketNameModal(self.guild))
    
    @discord.ui.button(label="Questions", emoji="❓", style=discord.ButtonStyle.secondary, row=1)
    async def questions_btn(self, i, b):
        v = QuestionsPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)
    
    @discord.ui.button(label="Personnaliser Panneau", emoji="🎨", style=discord.ButtonStyle.secondary, row=1)
    async def customize_btn(self, i, b):
        await i.response.send_modal(CustomizePanelModal(self.guild))
    
    @discord.ui.button(label="📤 Déployer Panneau", emoji="📤", style=discord.ButtonStyle.success, row=2)
    async def deploy_btn(self, i, b):
        v = DeployPanelView(self.user, self.guild)
        await i.response.edit_message(embed=v.create_embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)


class SelectCategoryView(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        
        categories = [c for c in guild.categories][:25]
        if categories:
            options = [discord.SelectOption(label=c.name, value=str(c.id), emoji="📁") for c in categories]
            select = Select(placeholder="📁 Sélectionnez une catégorie...", options=options)
            select.callback = self.select_callback
            self.add_item(select)
    
    def create_embed(self):
        return discord.Embed(title="📁 Catégorie des Tickets", description="```\nSélectionnez où les tickets seront créés\n```", color=Color.PURPLE)
    
    async def select_callback(self, i):
        cat_id = int(i.data['values'][0])
        await set_ticket_config(self.guild.id, category_id=cat_id)
        cat = self.guild.get_channel(cat_id)
        await i.response.send_message(f"```\n✅ Catégorie : {cat.name}\n```", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)


class SelectTicketStaffView(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        
        roles = [r for r in guild.roles[1:25] if not r.is_bot_managed()]
        if roles:
            options = [discord.SelectOption(label=f"@{r.name}", value=str(r.id), emoji="👮") for r in roles]
            select = Select(placeholder="👮 Sélectionnez le rôle staff...", options=options)
            select.callback = self.select_callback
            self.add_item(select)
    
    def create_embed(self):
        return discord.Embed(title="👮 Rôle Staff Tickets", description="```\nSélectionnez le rôle qui gère les tickets\n```", color=Color.PURPLE)
    
    async def select_callback(self, i):
        role_id = int(i.data['values'][0])
        await set_ticket_config(self.guild.id, staff_role_id=role_id)
        role = self.guild.get_role(role_id)
        await i.response.send_message(f"```\n✅ Rôle Staff : @{role.name}\n```", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)


class TicketNameModal(Modal, title="📝 Format du nom des tickets"):
    name_format = TextInput(
        label="Format du nom",
        placeholder="ticket-{user}-{number}",
        default="ticket-{user}-{number}",
        max_length=50
    )
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    
    async def on_submit(self, i):
        await set_ticket_config(self.guild.id, ticket_name=self.name_format.value)
        embed = discord.Embed(description=f"```yml\n✅ Format configuré\n\nVariables disponibles :\n- {{user}} = nom utilisateur\n- {{number}} = numéro ticket\n\nRésultat : {self.name_format.value}\n```", color=Color.GREEN)
        await i.response.send_message(embed=embed, ephemeral=True)


class QuestionsPanel(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
    
    async def create_embed(self):
        tc = await get_ticket_config(self.guild.id)
        questions = json.loads(tc['questions']) if tc['questions'] else []
        
        questions_list = "\n".join([f"{i+1}. {q}" for i, q in enumerate(questions)]) if questions else "Aucune question"
        
        embed = discord.Embed(title="❓ Questions du Ticket", color=Color.PURPLE)
        embed.description = f"""```yml
Questions posées à l'utilisateur
avant la création du ticket
────────────────────────────────────────────
{questions_list}
────────────────────────────────────────────
Maximum : 5 questions
(limite des modals Discord)
```"""
        return embed
    
    @discord.ui.button(label="➕ Ajouter Question", emoji="➕", style=discord.ButtonStyle.success)
    async def add_btn(self, i, b):
        tc = await get_ticket_config(self.guild.id)
        questions = json.loads(tc['questions']) if tc['questions'] else []
        if len(questions) >= 5:
            return await i.response.send_message("```\n❌ Maximum 5 questions\n```", ephemeral=True)
        await i.response.send_modal(AddQuestionModal(self.guild))
    
    @discord.ui.button(label="🗑️ Supprimer Tout", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def clear_btn(self, i, b):
        await set_ticket_config(self.guild.id, questions='[]')
        await i.response.send_message("```\n✅ Questions supprimées\n```", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)


class AddQuestionModal(Modal, title="➕ Ajouter une question"):
    question = TextInput(label="Question", placeholder="Pourquoi créez-vous ce ticket ?", max_length=100)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    
    async def on_submit(self, i):
        tc = await get_ticket_config(self.guild.id)
        questions = json.loads(tc['questions']) if tc['questions'] else []
        questions.append(self.question.value)
        await set_ticket_config(self.guild.id, questions=json.dumps(questions))
        await i.response.send_message(f"```\n✅ Question ajoutée :\n{self.question.value}\n```", ephemeral=True)


class CustomizePanelModal(Modal, title="🎨 Personnaliser le panneau"):
    title_input = TextInput(label="Titre", placeholder="🎫 Support", max_length=100, default="🎫 Support")
    desc_input = TextInput(label="Description", placeholder="Cliquez pour créer un ticket", style=discord.TextStyle.paragraph, max_length=500)
    
    def __init__(self, guild):
        super().__init__()
        self.guild = guild
    
    async def on_submit(self, i):
        await set_ticket_config(self.guild.id, panel_title=self.title_input.value, panel_description=self.desc_input.value)
        await i.response.send_message("```\n✅ Panneau personnalisé !\n```", ephemeral=True)


class DeployPanelView(View):
    def __init__(self, user, guild):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        
        channels = [c for c in guild.text_channels][:25]
        if channels:
            options = [discord.SelectOption(label=f"#{c.name}", value=str(c.id), emoji="📝") for c in channels]
            select = Select(placeholder="📝 Salon où déployer le panneau...", options=options)
            select.callback = self.select_callback
            self.add_item(select)
    
    def create_embed(self):
        return discord.Embed(title="📤 Déployer le Panneau", description="```\nSélectionnez le salon où envoyer\nle panneau de création de tickets\n```", color=Color.GREEN)
    
    async def select_callback(self, i):
        channel_id = int(i.data['values'][0])
        channel = self.guild.get_channel(channel_id)
        
        tc = await get_ticket_config(self.guild.id)
        
        if not tc['category_id'] or not tc['staff_role_id']:
            return await i.response.send_message("```\n❌ Configurez d'abord la catégorie et le rôle staff\n```", ephemeral=True)
        
        embed = discord.Embed(
            title=tc['panel_title'],
            description=tc['panel_description'],
            color=tc['panel_color']
        )
        embed.set_footer(text="Cliquez sur le bouton ci-dessous")
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        
        view = TicketCreateButton(self.guild.id)
        msg = await channel.send(embed=embed, view=view)
        
        await set_ticket_config(self.guild.id, panel_channel_id=channel_id, panel_message_id=msg.id)
        await i.response.send_message(f"```\n✅ Panneau déployé dans #{channel.name}\n```", ephemeral=True)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = TicketConfigPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)


class TicketCreateButton(View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
    
    @discord.ui.button(label="📩 Créer un ticket", emoji="📩", style=discord.ButtonStyle.success, custom_id="create_ticket")
    async def create_btn(self, i, b):
        tc = await get_ticket_config(i.guild.id)
        questions = json.loads(tc['questions']) if tc['questions'] else []
        
        if questions:
            await i.response.send_modal(TicketQuestionsModal(i.guild, questions))
        else:
            await create_ticket(i, i.guild, i.user, {})


class TicketQuestionsModal(Modal, title="📩 Créer un ticket"):
    def __init__(self, guild, questions):
        super().__init__()
        self.guild = guild
        self.questions = questions
        
        for i, q in enumerate(questions[:5]):
            self.add_item(TextInput(label=q[:45], placeholder="Votre réponse...", style=discord.TextStyle.paragraph, required=True, max_length=500, custom_id=f"q{i}"))
    
    async def on_submit(self, i):
        answers = {}
        for j, q in enumerate(self.questions[:5]):
            child = self.children[j]
            answers[q] = child.value
        
        await create_ticket(i, self.guild, i.user, answers)


async def create_ticket(interaction, guild, user, answers):
    tc = await get_ticket_config(guild.id)
    
    category = guild.get_channel(tc['category_id'])
    staff_role = guild.get_role(tc['staff_role_id'])
    
    if not category or not staff_role:
        return await interaction.response.send_message("```\n❌ Système de tickets non configuré\n```", ephemeral=True)
    
    # Compter les tickets
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute('SELECT COUNT(*) FROM tickets WHERE guild_id=?', (guild.id,))
        ticket_number = (await cur.fetchone())[0] + 1
    
    # Nom du ticket
    channel_name = tc['ticket_name'].format(user=user.name.lower()[:10], number=ticket_number)
    channel_name = re.sub(r'[^a-z0-9-]', '', channel_name)[:100]
    
    # Créer le salon
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
    }
    
    channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)
    
    # Enregistrer le ticket
    async with aiosqlite.connect(DB) as db:
        await db.execute('INSERT INTO tickets (guild_id, channel_id, user_id, answers) VALUES (?,?,?,?)',
                        (guild.id, channel.id, user.id, json.dumps(answers)))
        await db.commit()
    
    # Embed dans le ticket
    embed = discord.Embed(title="🎫 Nouveau Ticket", color=Color.GREEN)
    embed.description = f"""```yml
Bienvenue dans votre ticket !
────────────────────────────────────────────
👤 Créé par : {user}
📅 Date     : {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}
────────────────────────────────────────────
```"""
    
    if answers:
        embed.add_field(name="📝 Réponses", value="", inline=False)
        for q, a in answers.items():
            embed.add_field(name=f"❓ {q}", value=f"```{a[:200]}```", inline=False)
    
    embed.add_field(name="ℹ️ Actions", value="Un membre du staff va prendre en charge votre ticket.", inline=False)
    
    view = TicketActionsView(guild.id, channel.id, user.id)
    await channel.send(content=f"{user.mention} {staff_role.mention}", embed=embed, view=view)
    
    await interaction.response.send_message(f"```\n✅ Ticket créé : {channel.mention}\n```", ephemeral=True)


class TicketActionsView(View):
    def __init__(self, guild_id, channel_id, user_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.user_id = user_id
    
    @discord.ui.button(label="🙋 Prendre le ticket", emoji="🙋", style=discord.ButtonStyle.success, custom_id="claim_ticket")
    async def claim_btn(self, i, b):
        tc = await get_ticket_config(i.guild.id)
        staff_role = i.guild.get_role(tc['staff_role_id'])
        
        if not staff_role or staff_role not in i.user.roles:
            if not i.user.guild_permissions.administrator:
                return await i.response.send_message("```\n❌ Vous n'êtes pas staff\n```", ephemeral=True)
        
        # Mettre à jour la BDD
        async with aiosqlite.connect(DB) as db:
            await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (i.user.id, i.channel.id))
            await db.commit()
        
        # Modifier les permissions - seul le staff qui a claim + rôles supérieurs voient
        user = i.guild.get_member(self.user_id)
        
        new_overwrites = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        
        # Ajouter les rôles supérieurs
        claimer_top_role = i.user.top_role
        for role in i.guild.roles:
            if role.position > claimer_top_role.position and not role.is_bot_managed():
                new_overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        
        await i.channel.edit(overwrites=new_overwrites)
        
        embed = discord.Embed(
            description=f"```yml\n🙋 Ticket pris en charge par {i.user.name}\n```",
            color=Color.BLUE
        )
        await i.response.send_message(embed=embed)
        
        # Désactiver le bouton claim
        b.disabled = True
        b.label = f"Pris par {i.user.name}"
        b.style = discord.ButtonStyle.secondary
        await i.message.edit(view=self)
    
    @discord.ui.button(label="🔒 Fermer le ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_btn(self, i, b):
        tc = await get_ticket_config(i.guild.id)
        staff_role = i.guild.get_role(tc['staff_role_id'])
        
        is_staff = staff_role and staff_role in i.user.roles
        is_admin = i.user.guild_permissions.administrator
        is_owner = i.user.id == self.user_id
        
        if not (is_staff or is_admin or is_owner):
            return await i.response.send_message("```\n❌ Vous ne pouvez pas fermer ce ticket\n```", ephemeral=True)
        
        await i.response.send_message("```\n🔒 Fermeture du ticket dans 5 secondes...\n```")
        
        # Mettre à jour la BDD
        async with aiosqlite.connect(DB) as db:
            await db.execute('UPDATE tickets SET status="closed" WHERE channel_id=?', (i.channel.id,))
            await db.commit()
        
        await asyncio.sleep(5)
        await i.channel.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                          AUTRES PANNEAUX (SIMPLIFIÉS)
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
🔇 Mute : {f'{c["warns_mute"]} warns' if c['warns_mute'] else '❌'}
👢 Kick : {f'{c["warns_kick"]} warns' if c['warns_kick'] else '❌'}
🔨 Ban  : {f'{c["warns_ban"]} warns' if c['warns_ban'] else '❌'}
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
    
    @discord.ui.button(label="Config Sanctions", emoji="⚖️", style=discord.ButtonStyle.primary, row=1)
    async def sanctions_btn(self, i, b): await i.response.send_modal(SanctionsModal(self.guild))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)

# Modals modération
class WarnModal(Modal, title="⚠️ Warn"):
    member_id = TextInput(label="ID du membre", max_length=20)
    reason = TextInput(label="Raison", required=False, max_length=200)
    def __init__(self, guild, mod): super().__init__(); self.guild, self.mod = guild, mod
    async def on_submit(self, i):
        try:
            member = self.guild.get_member(int(self.member_id.value))
            if not member: return await i.response.send_message("❌ Membre introuvable", ephemeral=True)
            if await is_immune(member): return await i.response.send_message("❌ Immunisé", ephemeral=True)
            reason = self.reason.value or "Aucune raison"
            async with aiosqlite.connect(DB) as db:
                await db.execute('INSERT INTO warns (guild_id,user_id,mod_id,reason) VALUES (?,?,?,?)', (self.guild.id,member.id,self.mod.id,reason))
                await db.commit()
                cur = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id=? AND user_id=?', (self.guild.id,member.id))
                count = (await cur.fetchone())[0]
            await i.response.send_message(f"✅ **{member}** warn #{count}\nRaison: {reason}", ephemeral=True)
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
        await i.response.send_message(f"✅ Mute:{m} Kick:{k} Ban:{b}", ephemeral=True)

class LogsPanel(View):
    def __init__(self, user, guild): super().__init__(timeout=900); self.user, self.guild = user, guild
    async def create_embed(self):
        c = await get_config(self.guild.id)
        log_ch = self.guild.get_channel(c['log_channel'])
        mod_ch = self.guild.get_channel(c['mod_log_channel'])
        return discord.Embed(title="📜 Logs", description=f"```yml\n📝 Généraux: {log_ch.name if log_ch else '❌'}\n⚔️ Modération: {mod_ch.name if mod_ch else '❌'}\n```", color=Color.PURPLE)
    
    @discord.ui.button(label="Logs Généraux", emoji="📝", style=discord.ButtonStyle.primary)
    async def gen_btn(self, i, b):
        v = SelectChannelView(self.user, self.guild, "log_channel", LogsPanel)
        await i.response.edit_message(embed=discord.Embed(title="Sélectionnez un salon", color=Color.BLURPLE), view=v)
    
    @discord.ui.button(label="Logs Modération", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def mod_btn(self, i, b):
        v = SelectChannelView(self.user, self.guild, "mod_log_channel", LogsPanel)
        await i.response.edit_message(embed=discord.Embed(title="Sélectionnez un salon", color=Color.BLURPLE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back_btn(self, i, b):
        v = MainPanel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)

class SelectChannelView(View):
    def __init__(self, user, guild, key, back_panel):
        super().__init__(timeout=300)
        self.user, self.guild, self.key, self.back_panel = user, guild, key, back_panel
        opts = [discord.SelectOption(label=f"#{c.name}", value=str(c.id)) for c in guild.text_channels[:25]]
        if opts:
            sel = Select(placeholder="Sélectionnez...", options=opts)
            sel.callback = self.cb
            self.add_item(sel)
    async def cb(self, i):
        await set_config(self.guild.id, **{self.key: int(i.data['values'][0])})
        await i.response.send_message("✅ Configuré", ephemeral=True)
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = self.back_panel(self.user, self.guild)
        await i.response.edit_message(embed=await v.create_embed(), view=v)

class ProtectionPanel(View):
    def __init__(self, user, guild): super().__init__(timeout=900); self.user, self.guild = user, guild
    async def create_embed(self):
        c = await get_config(self.guild.id)
        s = lambda v: "✅" if v else "❌"
        return discord.Embed(title="🛡️ Protection", description=f"```yml\n🔗 Anti-Liens: {s(c['anti_link'])}\n🖼️ Anti-Images: {s(c['anti_image'])}\n🎣 Anti-Phishing: {s(c['anti_phishing'])}\n📨 Anti-Spam: {s(c['anti_spam'])}\n```", color=Color.BLUE)
    @discord.ui.button(label="Anti-Liens", emoji="🔗", style=discord.ButtonStyle.primary)
    async def l(self, i, b): c = await get_config(self.guild.id); await set_config(self.guild.id, anti_link=not c['anti_link']); await i.response.edit_message(embed=await self.create_embed(), view=self)
    @discord.ui.button(label="Anti-Images", emoji="🖼️", style=discord.ButtonStyle.primary)
    async def im(self, i, b): c = await get_config(self.guild.id); await set_config(self.guild.id, anti_image=not c['anti_image']); await i.response.edit_message(embed=await self.create_embed(), view=self)
    @discord.ui.button(label="Anti-Phishing", emoji="🎣", style=discord.ButtonStyle.primary)
    async def p(self, i, b): c = await get_config(self.guild.id); await set_config(self.guild.id, anti_phishing=not c['anti_phishing']); await i.response.edit_message(embed=await self.create_embed(), view=self)
    @discord.ui.button(label="Anti-Spam", emoji="📨", style=discord.ButtonStyle.primary)
    async def s(self, i, b): c = await get_config(self.guild.id); await set_config(self.guild.id, anti_spam=not c['anti_spam']); await i.response.edit_message(embed=await self.create_embed(), view=self)
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b): v = MainPanel(self.user, self.guild); await i.response.edit_message(embed=await v.create_embed(), view=v)

class RolesPanel(View):
    def __init__(self, user, guild): super().__init__(timeout=900); self.user, self.guild = user, guild
    async def create_embed(self):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id=?', (self.guild.id,))
            staff = [self.guild.get_role(r[0]) for r in await cur.fetchall() if self.guild.get_role(r[0])]
            cur = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.guild.id,))
            immune = [self.guild.get_role(r[0]) for r in await cur.fetchall() if self.guild.get_role(r[0])]
        return discord.Embed(title="👥 Rôles", description=f"```yml\n👮 Staff: {', '.join([r.name for r in staff]) or 'Aucun'}\n👑 Immunisés: {', '.join([r.name for r in immune]) or 'Aucun'}\n```", color=Color.ORANGE)
    @discord.ui.button(label="+ Staff", emoji="👮", style=discord.ButtonStyle.success)
    async def as_(self, i, b): await i.response.send_modal(AddRoleModal(self.guild, "staff_roles"))
    @discord.ui.button(label="+ Immunisé", emoji="👑", style=discord.ButtonStyle.success)
    async def ai(self, i, b): await i.response.send_modal(AddRoleModal(self.guild, "immune_roles"))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b): v = MainPanel(self.user, self.guild); await i.response.edit_message(embed=await v.create_embed(), view=v)

class AddRoleModal(Modal, title="Ajouter un rôle"):
    role_id = TextInput(label="ID du rôle", max_length=20)
    def __init__(self, guild, table): super().__init__(); self.guild, self.table = guild, table
    async def on_submit(self, i):
        try:
            rid = int(self.role_id.value)
            async with aiosqlite.connect(DB) as db:
                await db.execute(f'INSERT OR IGNORE INTO {self.table} VALUES (?,?)', (self.guild.id, rid))
                await db.commit()
            await i.response.send_message("✅ Ajouté", ephemeral=True)
        except: await i.response.send_message("❌ ID invalide", ephemeral=True)

class WelcomePanel(View):
    def __init__(self, user, guild): super().__init__(timeout=900); self.user, self.guild = user, guild
    async def create_embed(self):
        c = await get_config(self.guild.id)
        ch = self.guild.get_channel(c['welcome_channel'])
        return discord.Embed(title="👋 Bienvenue", description=f"```yml\nÉtat: {'✅' if c['welcome_on'] else '❌'}\nSalon: {ch.name if ch else '❌'}\nMessage: {c['welcome_msg'][:50]}...\n```", color=Color.GREEN)
    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary)
    async def t(self, i, b): c = await get_config(self.guild.id); await set_config(self.guild.id, welcome_on=not c['welcome_on']); await i.response.edit_message(embed=await self.create_embed(), view=self)
    @discord.ui.button(label="Salon", emoji="📝", style=discord.ButtonStyle.primary)
    async def ch(self, i, b):
        v = SelectChannelView(self.user, self.guild, "welcome_channel", WelcomePanel)
        await i.response.edit_message(embed=discord.Embed(title="Sélectionnez", color=Color.BLURPLE), view=v)
    @discord.ui.button(label="Message", emoji="✏️", style=discord.ButtonStyle.primary)
    async def m(self, i, b): await i.response.send_modal(WelcomeMsgModal(self.guild))
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b): v = MainPanel(self.user, self.guild); await i.response.edit_message(embed=await v.create_embed(), view=v)

class WelcomeMsgModal(Modal, title="Message"):
    msg = TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=500)
    def __init__(self, guild): super().__init__(); self.guild = guild
    async def on_submit(self, i): await set_config(self.guild.id, welcome_msg=self.msg.value); await i.response.send_message("✅", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 ÉVÉNEMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await init_db()
    
    # Charger les views persistantes
    bot.add_view(TicketCreateButton(0))
    bot.add_view(TicketActionsView(0, 0, 0))
    
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
    
    # Tracker activité
    await update_activity(msg.guild.id, msg.author.id, msg=True)
    
    if await is_immune(msg.author): return
    c = await get_config(msg.guild.id)
    
    PHISHING = ['discord-nitro.gift', 'discordgift.site', 'free-nitro.com', 'steampowered.ru', 'dlscord.com']
    if c['anti_phishing']:
        for d in PHISHING:
            if d in msg.content.lower():
                await msg.delete()
                await msg.channel.send(f"🎣 Phishing détecté ! ({msg.author})", delete_after=10)
                return
    
    if c['anti_link'] and re.search(r'https?://[^\s]+', msg.content):
        await msg.delete()
        await msg.channel.send(f"🔗 Lien supprimé ({msg.author})", delete_after=10)
        return
    
    if c['anti_image'] and msg.attachments:
        for a in msg.attachments:
            if a.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                await msg.delete()
                await msg.channel.send(f"🖼️ Image supprimée ({msg.author})", delete_after=10)
                return

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    if after.channel and not before.channel:
        # Rejoint un vocal
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
    
    embed = discord.Embed(title="👋 Nouveau membre", color=Color.GREEN)
    embed.add_field(name="Membre", value=f"{member.mention}", inline=True)
    await send_log(member.guild, embed)

@bot.event
async def on_message_delete(msg):
    if msg.author.bot or not msg.guild: return
    embed = discord.Embed(title="🗑️ Message supprimé", color=Color.YELLOW)
    embed.add_field(name="Auteur", value=msg.author.mention, inline=True)
    embed.add_field(name="Salon", value=msg.channel.mention, inline=True)
    if msg.content: embed.add_field(name="Contenu", value=f"```{msg.content[:500]}```", inline=False)
    await send_log(msg.guild, embed)

# ═══════════════════════════════════════════════════════════════════════════════
#                        🎮 COMMANDE UNIQUE : /configure
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Panneau de configuration")
async def configure_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        if i.user.id != i.guild.owner_id:
            if not await is_staff(i.user):
                return await i.response.send_message("❌ Accès refusé", ephemeral=True)
    
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=await v.create_embed(), view=v, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🚀 LANCEMENT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("🚀 Démarrage...")
    bot.run(TOKEN)
