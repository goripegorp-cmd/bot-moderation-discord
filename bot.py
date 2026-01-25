# ═══════════════════════════════════════════════════════════════════════════════
#                        🌟 BOT PREMIUM v11.2 🌟
#       Tickets Multi-Panels : Chaque panel a sa propre catégorie/config
# ═══════════════════════════════════════════════════════════════════════════════

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput, Button
import aiosqlite
import os
import re
import json
import asyncio
import unicodedata
import traceback
import io
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
DB_PATH = '/data/bot.db' if os.path.exists('/data') else 'bot.db'

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22

PHISHING = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com']
SCAM_PATTERNS = [r'free\s*nitro',r'steam\s*gift',r'@everyone.*http']
LEET = {'a':['@','4'],'e':['3','€'],'i':['1','!'],'o':['0'],'s':['$','5'],'t':['7']}

def now(): return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('CREATE TABLE IF NOT EXISTS guild_config (guild_id INTEGER PRIMARY KEY, data TEXT DEFAULT "{}")')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles (guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_users (guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id,user_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS infractions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, mod_id INTEGER, type TEXT, reason TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        await db.execute('''CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            guild_id INTEGER, 
            channel_id INTEGER, 
            user_id INTEGER, 
            panel_id TEXT DEFAULT "",
            claimed_by INTEGER DEFAULT 0, 
            status TEXT DEFAULT "open",
            answers TEXT DEFAULT "{}",
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.commit()
    print("✅ DB OK")

async def db_get(gid):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM guild_config WHERE guild_id=?', (gid,)) as c:
                r = await c.fetchone()
                return json.loads(r[0]) if r and r[0] else {}
    except: return {}

async def db_set(gid, key, val):
    try:
        data = await db_get(gid)
        data[key] = val
        jd = json.dumps(data, ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO guild_config (guild_id,data) VALUES (?,?) ON CONFLICT(guild_id) DO UPDATE SET data=?', (gid,jd,jd))
            await db.commit()
        return True
    except Exception as e:
        print(f"[DB_SET ERROR] {e}")
        return False

async def cfg(gid):
    data = await db_get(gid)
    defaults = {
        'anti_link':0,'anti_invite':0,'anti_image':0,'anti_phishing':1,'anti_scam':1,'anti_spam':0,'anti_caps':0,'anti_newaccount':0,'anti_badwords':0,
        'link_whitelist':[],'image_allowed':[],'badwords_list':[],'link_allowed_channels':[],'image_allowed_channels':[],
        'phishing_action':'ban','scam_action':'mute','spam_action':'mute','spam_max':5,'spam_interval':5,'caps_percent':70,'newaccount_days':7,
        'log_anti_link':0,'log_anti_image':0,'log_anti_phishing':0,'log_anti_scam':0,'log_anti_spam':0,'log_anti_caps':0,'log_anti_badwords':0,'log_anti_invite':0,'log_anti_newaccount':0,
        'channel_configs':{},
        'ticket_staff':0,'ticket_log':0,
        'ticket_panels':{}  # {panel_id: {category, questions, max, name}}
    }
    for k,v in defaults.items():
        if k not in data: data[k]=v
    return data

async def is_immune(member, key):
    if key != 'anti_phishing' and (member.guild_permissions.administrator or member.id == member.guild.owner_id): return True
    if key in ['anti_phishing','anti_link','anti_invite']: return False
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (member.guild.id,)) as c:
                rids = [r[0] for r in await c.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (member.guild.id,)) as c:
                uids = [r[0] for r in await c.fetchall()]
        if any(role.id in rids for role in member.roles) or member.id in uids: return True
    except: pass
    return False

async def sanction(member, action, duration, reason, guild):
    try:
        if action == 'mute': await member.timeout(timedelta(minutes=duration), reason=reason)
        elif action == 'kick': await member.kick(reason=reason)
        elif action == 'ban': await member.ban(reason=reason)
    except: pass

async def send_log(guild, key, member, msg, reason, extra=None):
    try:
        c = await cfg(guild.id)
        ch = guild.get_channel(c.get(f'log_{key}',0))
        if not ch: return
        e = discord.Embed(title=f"🛡️ {key}", color=C.RED, timestamp=now())
        e.add_field(name="👤", value=f"{member.mention} `{member.id}`", inline=True)
        if msg and msg.channel: e.add_field(name="📍", value=msg.channel.mention, inline=True)
        e.add_field(name="⚠️", value=reason, inline=False)
        if extra: e.add_field(name="ℹ️", value=extra, inline=False)
        e.set_thumbnail(url=member.display_avatar.url)
        await ch.send(embed=e)
    except: pass

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎞️ GIF DETECTION & PROTECTION CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def get_gif_type(msg):
    content = (msg.content or "").lower()
    if 'tenor.com' in content: return 'tenor'
    if 'giphy.com' in content: return 'giphy'
    for embed in msg.embeds:
        if embed.url and 'tenor' in embed.url.lower(): return 'tenor'
        if embed.url and 'giphy' in embed.url.lower(): return 'giphy'
    for att in msg.attachments:
        if att.filename.lower().endswith('.gif'): return 'gif'
    return None

def normalize(text):
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    for letter, variants in LEET.items():
        for v in variants: text = text.replace(v, letter)
    return text

def check_badwords(content, words):
    if not words: return False, None
    norm = normalize(content)
    for w in words:
        if normalize(w.strip()) in norm: return True, w
    return False, None

def check_link(content, whitelist):
    urls = re.findall(r'https?://([^\s<>"]+)', content.lower())
    for url in urls:
        domain = url.split('/')[0]
        if not any(w.lower() in domain for w in whitelist): return True, url
    return False, None

def check_invite(content):
    m = re.search(r'discord\.gg/\w+|discord\.com/invite/\w+', content, re.I)
    return (True, m.group()) if m else (False, None)

def check_phishing(content):
    for d in PHISHING:
        if d in content.lower(): return True, d
    return False, None

def check_scam(content):
    for p in SCAM_PATTERNS:
        if re.search(p, content, re.I): return True, p
    return False, None

def check_caps(content, percent):
    letters = [c for c in content if c.isalpha()]
    if len(letters) < 10: return False
    return sum(1 for c in letters if c.isupper()) / len(letters) * 100 >= percent

def check_image(msg, allowed):
    blocked = []
    gif_type = get_gif_type(msg)
    if gif_type and gif_type not in allowed: blocked.append(gif_type)
    for att in msg.attachments:
        ext = att.filename.lower().split('.')[-1]
        if ext in ['png','jpg','jpeg','webp','bmp'] and ext not in allowed: blocked.append(ext)
    return blocked

async def check_spam(msg, max_msg, interval):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker: spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n-t).total_seconds() < interval]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > max_msg

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS - SYSTÈME MULTI-PANELS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_ticket(ch_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id,user_id,claimed_by,answers,panel_id FROM tickets WHERE channel_id=? AND status="open"', (ch_id,)) as c:
                r = await c.fetchone()
                if r:
                    return {'id':r[0],'user':r[1],'claimed':r[2],'answers':json.loads(r[3]) if r[3] else {},'panel_id':r[4]}
                return None
    except:
        return None

async def count_user_open_tickets(guild, user_id, panel_id=None):
    """Compte les tickets ouverts (vérifie que le channel existe)"""
    count = 0
    tickets_to_close = []
    
    try:
        query = "SELECT id, channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'"
        params = [guild.id, user_id]
        if panel_id:
            query += " AND panel_id=?"
            params.append(panel_id)
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(query, params) as c:
                tickets = await c.fetchall()
        
        for ticket_id, channel_id in tickets:
            channel = guild.get_channel(channel_id)
            if channel:
                count += 1
            else:
                tickets_to_close.append(ticket_id)
        
        if tickets_to_close:
            async with aiosqlite.connect(DB_PATH) as db:
                for tid in tickets_to_close:
                    await db.execute("UPDATE tickets SET status='closed' WHERE id=?", (tid,))
                await db.commit()
        
        return count
    except Exception as e:
        print(f"[COUNT TICKETS ERROR] {e}")
        return 0

async def send_ticket_log(guild, log_type, user, ticket_info, extra_info=None, closer=None, channel=None):
    try:
        c = await cfg(guild.id)
        log_ch = guild.get_channel(c.get('ticket_log', 0))
        if not log_ch: return
        
        colors = {'create': C.GREEN, 'claim': C.BLUE, 'close': C.RED, 'leave': C.ORANGE, 'add_staff': C.PURPLE}
        titles = {'create': '🎫 Ticket Créé', 'claim': '🙋 Ticket Pris', 'close': '🔒 Ticket Fermé', 'leave': '🚪 Utilisateur Parti', 'add_staff': '➕ Staff Ajouté'}
        
        e = discord.Embed(title=titles.get(log_type, '🎫 Ticket'), color=colors.get(log_type, C.BLURPLE), timestamp=now())
        e.add_field(name="🎫 Ticket", value=f"#{ticket_info.get('id', '?')}", inline=True)
        
        user_id = user.id if hasattr(user, 'id') else user
        e.add_field(name="👤 Utilisateur", value=f"<@{user_id}>", inline=True)
        
        if log_type == 'claim' and extra_info:
            e.add_field(name="🙋 Pris par", value=f"<@{extra_info}>", inline=True)
        elif log_type == 'close' and closer:
            e.add_field(name="🔒 Fermé par", value=closer.mention, inline=True)
        elif log_type == 'add_staff' and extra_info:
            e.add_field(name="➕ Staff ajouté", value=f"<@{extra_info}>", inline=True)
        
        if ticket_info.get('answers') and log_type in ['create', 'close']:
            answers_text = "\n".join([f"**{q}**: {a[:100]}" for q, a in list(ticket_info['answers'].items())[:5]])
            if answers_text:
                e.add_field(name="📝 Réponses", value=answers_text[:1024], inline=False)
        
        if log_type == 'close' and channel:
            lines = []
            try:
                async for m in channel.history(limit=200, oldest_first=True):
                    lines.append(f"[{m.created_at.strftime('%H:%M')}] {m.author.name}: {m.content or '[média]'}")
                transcript = f"=== TICKET #{ticket_info['id']} ===\n" + "\n".join(lines)
                f = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket-{ticket_info['id']}.txt")
                await log_ch.send(embed=e, file=f)
                return
            except: pass
        
        if hasattr(user, 'display_avatar'):
            e.set_thumbnail(url=user.display_avatar.url)
        
        await log_ch.send(embed=e)
    except Exception as ex:
        print(f"[TICKET LOG ERROR] {ex}")


async def create_ticket_channel(interaction, panel_id, answers=None):
    """Crée le channel du ticket"""
    try:
        c = await cfg(interaction.guild.id)
        panels = c.get('ticket_panels', {})
        panel = panels.get(panel_id, {})
        
        cat_id = panel.get('category', 0)
        cat = interaction.guild.get_channel(cat_id)
        staff = interaction.guild.get_role(c.get('ticket_staff', 0))
        max_tickets = panel.get('max', 1)
        
        if not cat:
            return None, "❌ Catégorie non configurée pour ce panel"
        
        # Vérifier limite
        open_count = await count_user_open_tickets(interaction.guild, interaction.user.id, panel_id)
        if open_count >= max_tickets:
            return None, f"❌ Vous avez déjà **{open_count}** ticket(s) ouvert(s) (max: {max_tickets})"
        
        # Permissions
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True)
        }
        if staff:
            overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if interaction.guild.owner:
            overwrites[interaction.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
        
        # Créer le channel
        channel = await interaction.guild.create_text_channel(
            f"ticket-{interaction.user.name}"[:50], 
            category=cat, 
            overwrites=overwrites
        )
        
        # Sauvegarder en DB
        answers_json = json.dumps(answers or {}, ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO tickets (guild_id,channel_id,user_id,panel_id,answers) VALUES (?,?,?,?,?)', 
                (interaction.guild.id, channel.id, interaction.user.id, panel_id, answers_json))
            await db.commit()
            async with db.execute('SELECT id FROM tickets WHERE channel_id=?', (channel.id,)) as cur:
                row = await cur.fetchone()
                ticket_id = row[0] if row else 0
        
        # Créer l'embed
        embed = discord.Embed(title="🎫 Nouveau Ticket", color=C.BLURPLE, timestamp=now())
        embed.add_field(name="👤 Créé par", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
        embed.add_field(name="🎫 ID", value=f"#{ticket_id}", inline=True)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        # Ajouter les réponses
        if answers:
            for title, answer in answers.items():
                embed.add_field(name=f"📝 {title}", value=answer[:1024], inline=False)
        
        embed.set_footer(text="Un membre du staff va prendre votre ticket en charge")
        
        # Envoyer le message avec les boutons
        mention = interaction.user.mention
        if staff: mention += f" {staff.mention}"
        
        await channel.send(content=mention, embed=embed, view=TicketControlView())
        
        # Log
        await send_ticket_log(interaction.guild, 'create', interaction.user, {'id': ticket_id, 'answers': answers or {}})
        
        return channel, None
        
    except Exception as ex:
        print(f"[CREATE TICKET ERROR] {ex}\n{traceback.format_exc()}")
        return None, f"❌ Erreur: {ex}"


class TicketQuestionnaireModal(Modal):
    """Modal dynamique pour le questionnaire"""
    def __init__(self, panel_id, questions):
        super().__init__(title="📝 Créer un ticket")
        self.panel_id = panel_id
        self.questions = questions
        
        for i, q in enumerate(questions[:5]):
            field = TextInput(
                label=q.get('title', f'Question {i+1}')[:45],
                placeholder=q.get('question', '')[:100],
                style=discord.TextStyle.paragraph if len(q.get('question', '')) > 50 else discord.TextStyle.short,
                required=True,
                max_length=500
            )
            self.add_item(field)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Récupérer les réponses
            answers = {}
            for i, child in enumerate(self.children):
                if i < len(self.questions):
                    answers[self.questions[i].get('title', f'Question {i+1}')] = child.value
            
            await interaction.response.defer(ephemeral=True)
            
            channel, error = await create_ticket_channel(interaction, self.panel_id, answers)
            
            if error:
                await interaction.followup.send(error, ephemeral=True)
            else:
                await interaction.followup.send(f"✅ Ticket créé: {channel.mention}", ephemeral=True)
            
        except Exception as ex:
            print(f"[MODAL SUBMIT ERROR] {ex}\n{traceback.format_exc()}")
            try:
                await interaction.followup.send(f"❌ Erreur: {ex}", ephemeral=True)
            except: pass


class TicketCreateButton(Button):
    """Bouton de création de ticket avec panel_id"""
    def __init__(self, panel_id):
        super().__init__(
            label="📩 Créer un ticket",
            style=discord.ButtonStyle.success,
            custom_id=f"ticket_create_{panel_id}"
        )
        self.panel_id = panel_id
    
    async def callback(self, interaction: discord.Interaction):
        try:
            c = await cfg(interaction.guild.id)
            panels = c.get('ticket_panels', {})
            panel = panels.get(self.panel_id, {})
            
            if not panel:
                return await interaction.response.send_message("❌ Panel non trouvé", ephemeral=True)
            
            questions = panel.get('questions', [])
            max_tickets = panel.get('max', 1)
            
            # Vérifier limite AVANT d'ouvrir le modal
            open_count = await count_user_open_tickets(interaction.guild, interaction.user.id, self.panel_id)
            if open_count >= max_tickets:
                return await interaction.response.send_message(
                    f"❌ Vous avez déjà **{open_count}** ticket(s) ouvert(s) (max: {max_tickets})", 
                    ephemeral=True
                )
            
            if questions:
                modal = TicketQuestionnaireModal(self.panel_id, questions)
                await interaction.response.send_modal(modal)
            else:
                # Création directe
                await interaction.response.defer(ephemeral=True)
                channel, error = await create_ticket_channel(interaction, self.panel_id)
                if error:
                    await interaction.followup.send(error, ephemeral=True)
                else:
                    await interaction.followup.send(f"✅ Ticket créé: {channel.mention}", ephemeral=True)
                    
        except Exception as ex:
            print(f"[TICKET BTN ERROR] {ex}\n{traceback.format_exc()}")
            try:
                await interaction.response.send_message(f"❌ Erreur", ephemeral=True)
            except: pass


class TicketCreateView(View):
    """Vue persistante pour créer un ticket"""
    def __init__(self, panel_id):
        super().__init__(timeout=None)
        self.add_item(TicketCreateButton(panel_id))


class TicketControlView(View):
    """Boutons de contrôle dans le ticket"""
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🙋 Prendre en charge", style=discord.ButtonStyle.success, custom_id="ticket_ctrl_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: Button):
        try:
            ticket = await get_ticket(interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            
            c = await cfg(interaction.guild.id)
            staff_role = interaction.guild.get_role(c.get('ticket_staff', 0))
            
            # L'utilisateur ne peut pas claim son propre ticket
            if interaction.user.id == ticket['user']:
                return await interaction.response.send_message("❌ Vous ne pouvez pas prendre votre propre ticket", ephemeral=True)
            
            # Vérifier permissions
            is_staff = staff_role and staff_role in interaction.user.roles
            is_owner = interaction.user.id == interaction.guild.owner_id
            is_admin = interaction.user.guild_permissions.administrator
            
            if not (is_staff or is_owner or is_admin):
                return await interaction.response.send_message("❌ Réservé au staff", ephemeral=True)
            
            # Mettre à jour les permissions
            ticket_user = interaction.guild.get_member(ticket['user'])
            
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            }
            if ticket_user:
                overwrites[ticket_user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
            if interaction.guild.owner and interaction.guild.owner != interaction.user:
                overwrites[interaction.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=False)
            
            await interaction.channel.edit(overwrites=overwrites)
            
            # Mettre à jour DB
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (interaction.user.id, interaction.channel.id))
                await db.commit()
            
            await interaction.response.send_message(f"✅ **{interaction.user.display_name}** prend ce ticket en charge\n\n*Les autres staffs ne peuvent plus voir ce ticket.*")
            
            # Modifier le bouton
            button.disabled = True
            button.label = f"Pris par {interaction.user.display_name}"
            button.style = discord.ButtonStyle.secondary
            await interaction.message.edit(view=self)
            
            # Log
            await send_ticket_log(interaction.guild, 'claim', ticket['user'], ticket, extra_info=interaction.user.id)
            
        except Exception as ex:
            print(f"[CLAIM ERROR] {ex}\n{traceback.format_exc()}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="➕ Ajouter Staff", style=discord.ButtonStyle.primary, custom_id="ticket_ctrl_addstaff")
    async def add_staff(self, interaction: discord.Interaction, button: Button):
        try:
            ticket = await get_ticket(interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            
            is_owner = interaction.user.id == interaction.guild.owner_id
            is_claimer = interaction.user.id == ticket['claimed']
            is_admin = interaction.user.guild_permissions.administrator
            
            if not ticket['claimed']:
                return await interaction.response.send_message("❌ Le ticket doit d'abord être pris en charge", ephemeral=True)
            
            if not (is_claimer or is_owner or is_admin):
                return await interaction.response.send_message("❌ Seul le staff en charge peut ajouter quelqu'un", ephemeral=True)
            
            c = await cfg(interaction.guild.id)
            staff_role = interaction.guild.get_role(c.get('ticket_staff', 0))
            
            if not staff_role:
                return await interaction.response.send_message("❌ Aucun rôle staff configuré", ephemeral=True)
            
            staffs = [m for m in staff_role.members if m.id != ticket['claimed'] and m.id != ticket['user']][:25]
            
            if not staffs:
                return await interaction.response.send_message("❌ Aucun autre staff disponible", ephemeral=True)
            
            opts = [discord.SelectOption(label=f"@{m.display_name}"[:25], value=str(m.id)) for m in staffs]
            v = AddStaffSelectView(opts, interaction.channel.id)
            await interaction.response.send_message("👥 Choisir un staff:", view=v, ephemeral=True)
            
        except Exception as ex:
            print(f"[ADD STAFF ERROR] {ex}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="ticket_ctrl_close")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        try:
            ticket = await get_ticket(interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            
            is_owner = interaction.user.id == interaction.guild.owner_id
            is_admin = interaction.user.guild_permissions.administrator
            is_claimer = interaction.user.id == ticket['claimed']
            
            c = await cfg(interaction.guild.id)
            staff_role = interaction.guild.get_role(c.get('ticket_staff', 0))
            is_staff = staff_role and staff_role in interaction.user.roles
            
            if ticket['claimed']:
                if not (is_claimer or is_owner or is_admin):
                    return await interaction.response.send_message("❌ Seul le staff en charge ou un admin peut fermer", ephemeral=True)
            else:
                if not (is_staff or is_owner or is_admin):
                    return await interaction.response.send_message("❌ Seul le staff peut fermer", ephemeral=True)
            
            # Log
            ticket_user = interaction.guild.get_member(ticket['user'])
            await send_ticket_log(interaction.guild, 'close', ticket_user or ticket['user'], ticket, closer=interaction.user, channel=interaction.channel)
            
            # Fermer
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (interaction.channel.id,))
                await db.commit()
            
            await interaction.response.send_message("🔒 Fermeture dans 3 secondes...")
            await asyncio.sleep(3)
            await interaction.channel.delete()
            
        except Exception as ex:
            print(f"[CLOSE ERROR] {ex}\n{traceback.format_exc()}")
            try:
                await interaction.response.send_message("❌ Erreur", ephemeral=True)
            except: pass


class AddStaffSelectView(View):
    def __init__(self, opts, channel_id):
        super().__init__(timeout=60)
        self.add_item(AddStaffSelect(opts, channel_id))


class AddStaffSelect(Select):
    def __init__(self, opts, channel_id):
        super().__init__(placeholder="Choisir...", options=opts)
        self.channel_id = channel_id
    
    async def callback(self, interaction: discord.Interaction):
        try:
            staff = interaction.guild.get_member(int(self.values[0]))
            channel = interaction.guild.get_channel(self.channel_id)
            
            if staff and channel:
                await channel.set_permissions(staff, view_channel=True, send_messages=True, read_message_history=True)
                await interaction.response.send_message(f"✅ {staff.mention} ajouté!", ephemeral=True)
                await channel.send(f"➕ **{staff.display_name}** a été ajouté par {interaction.user.mention}")
                
                ticket = await get_ticket(self.channel_id)
                if ticket:
                    await send_ticket_log(interaction.guild, 'add_staff', ticket['user'], ticket, extra_info=staff.id)
            else:
                await interaction.response.send_message("❌ Erreur", ephemeral=True)
        except Exception as ex:
            print(f"[ADD STAFF SELECT ERROR] {ex}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════

PROTS = [("anti_link","🔗","Anti-Liens"),("anti_invite","🎟️","Anti-Invite"),("anti_image","🖼️","Anti-Images"),("anti_phishing","🎣","Anti-Phishing"),("anti_scam","🚨","Anti-Scam"),("anti_spam","📨","Anti-Spam"),("anti_caps","🔠","Anti-Caps"),("anti_badwords","🤬","Anti-Insultes"),("anti_newaccount","👶","Anti-NewAccount")]

class MainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g
    
    async def interaction_check(self, i): 
        return i.user.id == self.u.id
    
    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"**{self.g.name}**\n{self.g.member_count} membres"
        if self.g.icon: e.set_thumbnail(url=self.g.icon.url)
        return e

    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def btn_prot(self, interaction: discord.Interaction, button: Button):
        v = ProtPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def btn_logs(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        lines = [f"{em} {nm}: {self.g.get_channel(c.get(f'log_{k}',0)).mention if c.get(f'log_{k}') and self.g.get_channel(c.get(f'log_{k}')) else '❌'}" for k,em,nm in PROTS]
        e.description = "\n".join(lines)
        await interaction.response.edit_message(embed=e, view=BackView(self.u, self.g))

    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=0)
    async def btn_immune(self, interaction: discord.Interaction, button: Button):
        v = ImmunePanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Config Salon", emoji="📺", style=discord.ButtonStyle.primary, row=1)
    async def btn_chan(self, interaction: discord.Interaction, button: Button):
        v = ChanPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.success, row=1)
    async def btn_tickets(self, interaction: discord.Interaction, button: Button):
        v = TicketMainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def btn_close(self, interaction: discord.Interaction, button: Button):
        await interaction.message.delete()

class BackView(View):
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u, self.g = u, g
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = MainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL (simplifié)
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        lines = [f"{em} {nm}: {'✅' if c.get(k) else '❌'}" for k,em,nm in PROTS]
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        e.description = "```\n" + "\n".join(lines) + "\n```"
        return e

    @discord.ui.select(placeholder="Sélectionner...", options=[discord.SelectOption(label=nm, value=k, emoji=em) for k,em,nm in PROTS])
    async def sel(self, interaction: discord.Interaction, select: Select):
        prot = next(p for p in PROTS if p[0]==select.values[0])
        v = ProtDetail(self.u, self.g, prot)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = MainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=v.embed(), view=v)

class ProtDetail(View):
    def __init__(self, u, g, prot):
        super().__init__(timeout=600)
        self.u, self.g, self.prot, self.key = u, g, prot, prot[0]

    async def embed(self):
        c = await cfg(self.g.id)
        on = bool(c.get(self.key))
        e = discord.Embed(title=f"{self.prot[1]} {self.prot[2]}", color=C.GREEN if on else C.RED)
        e.add_field(name="État", value="✅ ACTIVÉ" if on else "❌ DÉSACTIVÉ", inline=False)
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        await db_set(self.g.id, self.key, 0 if c.get(self.key) else 1)
        await interaction.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = ProtPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👑 IMMUNITÉS & 📺 CONFIG SALON (simplifié)
# ═══════════════════════════════════════════════════════════════════════════════

class ImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,)) as c:
                rids = [r[0] for r in await c.fetchall()]
        e = discord.Embed(title="👑 Immunités", color=C.YELLOW)
        e.add_field(name="Rôles", value=", ".join([f"<@&{r}>" for r in rids]) or "*Aucun*", inline=False)
        return e

    @discord.ui.button(label="➕ Rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, interaction: discord.Interaction, button: Button):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = ImmuneRoleView(self.u, self.g, opts)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = MainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=v.embed(), view=v)

class ImmuneRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ImmuneRoleSelect(u, g, opts))

class ImmuneRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Rôle...", options=opts)
        self.u, self.g = u, g
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES (?,?)', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ChanPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        e = discord.Embed(title="📺 Config Salon", color=C.ORANGE)
        e.description = f"{len(configs)} salon(s) configuré(s)" if configs else "*Aucun*"
        return e

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = MainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎫 TICKET MAIN PANEL - Multi-panels
# ═══════════════════════════════════════════════════════════════════════════════

class TicketMainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎫 Configuration Tickets", color=C.PURPLE)
        
        # Config globale
        staff = self.g.get_role(c.get('ticket_staff', 0))
        log_ch = self.g.get_channel(c.get('ticket_log', 0))
        e.add_field(name="👮 Staff", value=staff.mention if staff else "❌", inline=True)
        e.add_field(name="📜 Logs", value=log_ch.mention if log_ch else "❌", inline=True)
        
        # Panels
        panels = c.get('ticket_panels', {})
        if panels:
            panel_list = []
            for pid, pdata in list(panels.items())[:10]:
                cat = self.g.get_channel(pdata.get('category', 0))
                cat_name = cat.name if cat else "❌"
                qcount = len(pdata.get('questions', []))
                panel_list.append(f"• **{pdata.get('name', pid)[:20]}** → `{cat_name}` ({qcount} Q, max {pdata.get('max', 1)})")
            e.add_field(name=f"📋 Panels ({len(panels)})", value="\n".join(panel_list), inline=False)
        else:
            e.add_field(name="📋 Panels", value="*Aucun panel créé*", inline=False)
        
        return e

    @discord.ui.button(label="👮 Staff", style=discord.ButtonStyle.primary, row=0)
    async def set_staff(self, interaction: discord.Interaction, button: Button):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = TicketStaffSelectView(self.u, self.g, opts)
        await interaction.response.edit_message(embed=discord.Embed(title="👮 Rôle Staff", color=C.PURPLE), view=v)

    @discord.ui.button(label="📜 Logs", style=discord.ButtonStyle.primary, row=0)
    async def set_log(self, interaction: discord.Interaction, button: Button):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        v = TicketLogSelectView(self.u, self.g, opts)
        await interaction.response.edit_message(embed=discord.Embed(title="📜 Salon Logs", color=C.PURPLE), view=v)

    @discord.ui.button(label="➕ Nouveau Panel", style=discord.ButtonStyle.success, row=1)
    async def new_panel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(NewPanelModal(self.u, self.g))

    @discord.ui.button(label="📝 Modifier Panel", style=discord.ButtonStyle.secondary, row=1)
    async def edit_panel(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if not panels:
            return await interaction.response.send_message("❌ Aucun panel", ephemeral=True)
        opts = [discord.SelectOption(label=pdata.get('name', pid)[:25], value=pid) for pid, pdata in list(panels.items())[:25]]
        v = EditPanelSelectView(self.u, self.g, opts)
        await interaction.response.edit_message(embed=discord.Embed(title="📝 Choisir un panel", color=C.PURPLE), view=v)

    @discord.ui.button(label="🔄 Rafraîchir", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = MainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=v.embed(), view=v)


class TicketStaffSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TicketStaffSelect(u, g, opts))

class TicketStaffSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Rôle...", options=opts)
        self.u, self.g = u, g
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_staff', int(self.values[0]))
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TicketLogSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TicketLogSelect(u, g, opts))

class TicketLogSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Salon...", options=opts)
        self.u, self.g = u, g
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_log', int(self.values[0]))
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)


class NewPanelModal(Modal, title="➕ Nouveau Panel"):
    name = TextInput(label="Nom du panel", placeholder="Ex: Support, Partenariat...", max_length=30)
    max_tickets = TextInput(label="Max tickets par utilisateur", placeholder="1", default="1", max_length=2)
    
    def __init__(self, u, g):
        super().__init__()
        self.u, self.g = u, g
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            panel_id = str(int(time.time()))
            max_t = int(self.max_tickets.value) if self.max_tickets.value.isdigit() else 1
            if max_t < 1: max_t = 1
            if max_t > 10: max_t = 10
            
            c = await cfg(self.g.id)
            panels = c.get('ticket_panels', {})
            panels[panel_id] = {
                'name': self.name.value,
                'category': 0,
                'questions': [],
                'max': max_t
            }
            await db_set(self.g.id, 'ticket_panels', panels)
            
            # Aller à l'édition du panel
            v = PanelEditView(self.u, self.g, panel_id)
            await interaction.response.edit_message(embed=await v.embed(), view=v)
        except Exception as ex:
            await interaction.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)


class EditPanelSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(EditPanelSelect(u, g, opts))

class EditPanelSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Panel...", options=opts)
        self.u, self.g = u, g
    async def callback(self, i):
        v = PanelEditView(self.u, self.g, self.values[0])
        await i.response.edit_message(embed=await v.embed(), view=v)


class PanelEditView(View):
    def __init__(self, u, g, panel_id):
        super().__init__(timeout=600)
        self.u, self.g, self.panel_id = u, g, panel_id

    async def get_panel(self):
        c = await cfg(self.g.id)
        return c.get('ticket_panels', {}).get(self.panel_id, {})

    async def embed(self):
        panel = await self.get_panel()
        e = discord.Embed(title=f"🎫 Panel: {panel.get('name', '?')}", color=C.PURPLE)
        
        cat = self.g.get_channel(panel.get('category', 0))
        e.add_field(name="📁 Catégorie", value=cat.name if cat else "❌ Non configuré", inline=True)
        e.add_field(name="🔢 Max tickets", value=str(panel.get('max', 1)), inline=True)
        
        questions = panel.get('questions', [])
        if questions:
            q_text = "\n".join([f"• {q['title']}" for q in questions[:5]])
            e.add_field(name=f"📝 Questions ({len(questions)})", value=q_text, inline=False)
        else:
            e.add_field(name="📝 Questions", value="*Aucune*", inline=False)
        
        return e

    @discord.ui.button(label="📁 Catégorie", style=discord.ButtonStyle.primary, row=0)
    async def set_category(self, interaction: discord.Interaction, button: Button):
        cats = list(self.g.categories)[:25]
        if not cats:
            return await interaction.response.send_message("❌ Aucune catégorie", ephemeral=True)
        opts = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in cats]
        v = PanelCategorySelectView(self.u, self.g, self.panel_id, opts)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="📝 Questions", style=discord.ButtonStyle.primary, row=0)
    async def edit_questions(self, interaction: discord.Interaction, button: Button):
        v = PanelQuestionsView(self.u, self.g, self.panel_id)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="🔢 Max", style=discord.ButtonStyle.secondary, row=0)
    async def set_max(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(SetMaxModal(self.u, self.g, self.panel_id))

    @discord.ui.button(label="📤 Envoyer", style=discord.ButtonStyle.success, row=1)
    async def send_panel(self, interaction: discord.Interaction, button: Button):
        panel = await self.get_panel()
        c = await cfg(self.g.id)
        
        if not panel.get('category'):
            return await interaction.response.send_message("❌ Configure la **Catégorie** d'abord!", ephemeral=True)
        if not c.get('ticket_staff'):
            return await interaction.response.send_message("❌ Configure le **Staff** d'abord (menu principal)!", ephemeral=True)
        
        # Choisir où envoyer
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{ch.name}"[:25], value=str(ch.id)) for ch in chs]
        v = SendPanelSelectView(self.u, self.g, self.panel_id, opts)
        await interaction.response.edit_message(embed=discord.Embed(title="📤 Où envoyer le panel?", color=C.PURPLE), view=v)

    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=1)
    async def delete_panel(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.panel_id in panels:
            del panels[self.panel_id]
            await db_set(self.g.id, 'ticket_panels', panels)
        v = TicketMainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = TicketMainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)


class PanelCategorySelectView(View):
    def __init__(self, u, g, panel_id, opts):
        super().__init__(timeout=120)
        self.add_item(PanelCategorySelect(u, g, panel_id, opts))

class PanelCategorySelect(Select):
    def __init__(self, u, g, panel_id, opts):
        super().__init__(placeholder="Catégorie...", options=opts)
        self.u, self.g, self.panel_id = u, g, panel_id
    async def callback(self, i):
        c = await cfg(i.guild.id)
        panels = c.get('ticket_panels', {})
        if self.panel_id in panels:
            panels[self.panel_id]['category'] = int(self.values[0])
            await db_set(i.guild.id, 'ticket_panels', panels)
        v = PanelEditView(self.u, self.g, self.panel_id)
        await i.response.edit_message(embed=await v.embed(), view=v)


class SetMaxModal(Modal, title="🔢 Max tickets"):
    max_val = TextInput(label="Nombre max", placeholder="1-10", default="1", max_length=2)
    def __init__(self, u, g, pid):
        super().__init__()
        self.u, self.g, self.pid = u, g, pid
    async def on_submit(self, i):
        val = int(self.max_val.value) if self.max_val.value.isdigit() else 1
        val = max(1, min(10, val))
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['max'] = val
            await db_set(self.g.id, 'ticket_panels', panels)
        v = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)


class PanelQuestionsView(View):
    def __init__(self, u, g, panel_id):
        super().__init__(timeout=600)
        self.u, self.g, self.panel_id = u, g, panel_id

    async def embed(self):
        c = await cfg(self.g.id)
        panel = c.get('ticket_panels', {}).get(self.panel_id, {})
        questions = panel.get('questions', [])
        
        e = discord.Embed(title="📝 Questions", color=C.PURPLE)
        if questions:
            for i, q in enumerate(questions, 1):
                e.add_field(name=f"{i}. {q['title']}", value=q['question'][:100], inline=False)
        else:
            e.description = "*Aucune question*"
        e.set_footer(text="Max 5 questions")
        return e

    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add_q(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        panel = c.get('ticket_panels', {}).get(self.panel_id, {})
        if len(panel.get('questions', [])) >= 5:
            return await interaction.response.send_message("❌ Max 5 questions", ephemeral=True)
        await interaction.response.send_modal(AddQuestionModal(self.u, self.g, self.panel_id))

    @discord.ui.button(label="🗑️ Supprimer tout", style=discord.ButtonStyle.danger, row=0)
    async def clear_q(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.panel_id in panels:
            panels[self.panel_id]['questions'] = []
            await db_set(self.g.id, 'ticket_panels', panels)
        await interaction.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = PanelEditView(self.u, self.g, self.panel_id)
        await interaction.response.edit_message(embed=await v.embed(), view=v)


class AddQuestionModal(Modal, title="➕ Ajouter question"):
    q_title = TextInput(label="Titre", placeholder="Ex: Pseudo", max_length=45)
    q_question = TextInput(label="Question", placeholder="Ex: Quel est votre pseudo?", style=discord.TextStyle.paragraph, max_length=100)
    
    def __init__(self, u, g, pid):
        super().__init__()
        self.u, self.g, self.pid = u, g, pid
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid].setdefault('questions', []).append({
                'title': self.q_title.value,
                'question': self.q_question.value
            })
            await db_set(self.g.id, 'ticket_panels', panels)
        v = PanelQuestionsView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)


class SendPanelSelectView(View):
    def __init__(self, u, g, panel_id, opts):
        super().__init__(timeout=120)
        self.add_item(SendPanelSelect(u, g, panel_id, opts))

class SendPanelSelect(Select):
    def __init__(self, u, g, panel_id, opts):
        super().__init__(placeholder="Salon...", options=opts)
        self.u, self.g, self.panel_id = u, g, panel_id
    
    async def callback(self, i):
        ch = i.guild.get_channel(int(self.values[0]))
        if not ch:
            return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        c = await cfg(i.guild.id)
        panel = c.get('ticket_panels', {}).get(self.panel_id, {})
        
        questions = panel.get('questions', [])
        max_t = panel.get('max', 1)
        
        desc = "Cliquez sur le bouton ci-dessous pour créer un ticket."
        if questions:
            desc += f"\n\n📝 Vous devrez répondre à **{len(questions)}** question(s)."
        desc += f"\n🔢 Maximum **{max_t}** ticket(s) simultané(s)."
        
        embed = discord.Embed(
            title=f"🎫 {panel.get('name', 'Support')}",
            description=desc,
            color=C.BLURPLE
        )
        
        await ch.send(embed=embed, view=TicketCreateView(self.panel_id))
        await i.response.send_message(f"✅ Panel envoyé dans {ch.mention}!", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await db_init()
    
    # Enregistrer les vues persistantes pour les tickets
    bot.add_view(TicketControlView())
    
    # Charger les panels existants
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, data FROM guild_config') as c:
                rows = await c.fetchall()
        for guild_id, data_str in rows:
            try:
                data = json.loads(data_str) if data_str else {}
                panels = data.get('ticket_panels', {})
                for panel_id in panels:
                    bot.add_view(TicketCreateView(panel_id))
            except: pass
    except: pass
    
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v11.2 prêt!")

@bot.event
async def on_member_remove(member):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id, channel_id, claimed_by, answers FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (member.guild.id, member.id)) as c:
                tickets = await c.fetchall()
                
        for ticket in tickets:
            ticket_info = {'id': ticket[0], 'user': member.id, 'claimed': ticket[2], 'answers': json.loads(ticket[3]) if ticket[3] else {}}
            channel = member.guild.get_channel(ticket[1])
            
            await send_ticket_log(member.guild, 'leave', member, ticket_info)
            
            if channel:
                embed = discord.Embed(title="🚪 Utilisateur parti", description=f"**{member.display_name}** a quitté.", color=C.ORANGE)
                await channel.send(embed=embed)
    except: pass

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    try:
        c = await cfg(msg.guild.id)
        content = msg.content or ""
        
        if c.get('anti_phishing'):
            found, domain = check_phishing(content)
            if found:
                await msg.delete()
                await sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing", msg.guild)
                return

        if c.get('anti_scam') and not await is_immune(msg.author, 'anti_scam'):
            found, _ = check_scam(content)
            if found:
                await msg.delete()
                await sanction(msg.author, c.get('scam_action', 'mute'), 60, "Scam", msg.guild)
                return
    except: pass

@bot.tree.command(name="configure", description="⚙️ Configuration")
async def configure_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin requis", ephemeral=True)
    view = MainPanel(interaction.user, interaction.guild)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

if __name__ == "__main__":
    print("🚀 v11.2")
    bot.run(TOKEN)
