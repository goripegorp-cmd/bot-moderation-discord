# ═══════════════════════════════════════════════════════════════════════════════
#                        🌟 BOT PREMIUM v11.0 🌟
#          Système Tickets Avancé : Questionnaire + Permissions + Logs
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
        'ticket_panel':0,'ticket_category':0,'ticket_staff':0,'ticket_log':0,
        'ticket_questions':[]  # Liste de {"title": "...", "question": "..."}
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
#                    🎞️ GIF DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def get_gif_type(msg):
    content = (msg.content or "").lower()
    if 'tenor.com' in content or 'tenor' in content: return 'tenor'
    if 'giphy.com' in content or 'giphy' in content: return 'giphy'
    for embed in msg.embeds:
        urls = []
        if embed.url: urls.append(embed.url.lower())
        if embed.thumbnail and embed.thumbnail.url: urls.append(embed.thumbnail.url.lower())
        if embed.video and embed.video.url: urls.append(embed.video.url.lower())
        for url in urls:
            if 'tenor' in url: return 'tenor'
            if 'giphy' in url: return 'giphy'
        if embed.provider and embed.provider.name:
            pn = embed.provider.name.lower()
            if 'tenor' in pn: return 'tenor'
            if 'giphy' in pn: return 'giphy'
        if embed.type == 'gifv': return 'gif'
    for att in msg.attachments:
        if att.filename.lower().endswith('.gif'): return 'gif'
    return None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

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
    nospace = re.sub(r'[^a-z]', '', norm)
    for w in words:
        wn = normalize(w.strip())
        if wn and (wn in norm or wn in nospace): return True, w
    return False, None

def check_link(content, whitelist):
    urls = re.findall(r'https?://([^\s<>"]+)', content.lower())
    if not urls: return False, None
    for url in urls:
        domain = url.split('/')[0]
        allowed = any(w.lower() in domain for w in whitelist)
        if not allowed: return True, url
    return False, None

def check_invite(content):
    for p in [r'discord\.gg/\w+', r'discord\.com/invite/\w+']:
        m = re.search(p, content, re.I)
        if m: return True, m.group()
    return False, None

def check_phishing(content):
    cl = content.lower()
    for d in PHISHING:
        if d in cl: return True, d
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
    al = [f.lower() for f in allowed]
    gif_type = get_gif_type(msg)
    if gif_type and gif_type not in al: blocked.append(gif_type)
    for att in msg.attachments:
        ext = att.filename.lower().split('.')[-1]
        if ext in ['png','jpg','jpeg','webp','bmp'] and ext not in al: blocked.append(ext)
    return blocked

async def check_spam(msg, max_msg, interval):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker: spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n-t).total_seconds() < interval]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > max_msg

def check_channel_cfg(msg, conf):
    if not conf: return False, None
    content = (msg.content or "").strip()
    if not conf.get('messages', True):
        has_text = bool(re.sub(r'<a?:\w+:\d+>|https?://\S+', '', content).strip())
        if has_text and not msg.attachments and not msg.embeds: return True, "messages"
    if not conf.get('images', True):
        for att in msg.attachments:
            if att.filename.lower().split('.')[-1] in ['png','jpg','jpeg','webp','bmp']: return True, "images"
    if not conf.get('gifs', True) and get_gif_type(msg): return True, "gifs"
    if not conf.get('emojis', True) and re.search(r'<a?:\w+:\d+>', content): return True, "emojis"
    if not conf.get('links', True) and re.search(r'https?://', content): return True, "links"
    return False, None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS - SYSTÈME AVANCÉ
# ═══════════════════════════════════════════════════════════════════════════════

async def get_ticket(ch_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id,user_id,claimed_by,answers FROM tickets WHERE channel_id=? AND status="open"', (ch_id,)) as c:
                r = await c.fetchone()
                if r:
                    return {'id':r[0],'user':r[1],'claimed':r[2],'answers':json.loads(r[3]) if r[3] else {}}
                return None
    except:
        return None

async def send_ticket_log(guild, log_type, user, ticket_info, extra_info=None, closer=None, channel=None):
    """Envoie un log de ticket"""
    try:
        c = await cfg(guild.id)
        log_ch = guild.get_channel(c.get('ticket_log', 0))
        if not log_ch: return
        
        colors = {'create': C.GREEN, 'claim': C.BLUE, 'close': C.RED, 'leave': C.ORANGE, 'add_staff': C.PURPLE}
        titles = {'create': '🎫 Ticket Créé', 'claim': '🙋 Ticket Pris', 'close': '🔒 Ticket Fermé', 'leave': '🚪 Utilisateur Parti', 'add_staff': '➕ Staff Ajouté'}
        
        e = discord.Embed(title=titles.get(log_type, '🎫 Ticket'), color=colors.get(log_type, C.BLURPLE), timestamp=now())
        e.add_field(name="🎫 Ticket", value=f"#{ticket_info.get('id', '?')}", inline=True)
        e.add_field(name="👤 Utilisateur", value=f"<@{user.id}>" if hasattr(user, 'id') else f"<@{user}>", inline=True)
        
        if log_type == 'claim' and extra_info:
            e.add_field(name="🙋 Pris par", value=f"<@{extra_info}>", inline=True)
        elif log_type == 'close' and closer:
            e.add_field(name="🔒 Fermé par", value=closer.mention, inline=True)
        elif log_type == 'add_staff' and extra_info:
            e.add_field(name="➕ Staff ajouté", value=f"<@{extra_info}>", inline=True)
        
        # Réponses au questionnaire
        if ticket_info.get('answers') and log_type in ['create', 'close']:
            answers_text = ""
            for q, a in ticket_info['answers'].items():
                answers_text += f"**{q}**\n{a}\n\n"
            if answers_text:
                e.add_field(name="📝 Réponses", value=answers_text[:1024], inline=False)
        
        # Transcript pour fermeture
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


class TicketQuestionnaireModal(Modal):
    """Modal dynamique pour le questionnaire"""
    def __init__(self, guild_id, questions):
        super().__init__(title="📝 Créer un ticket")
        self.guild_id = guild_id
        self.questions = questions
        self.answers = {}
        
        # Ajouter les champs (max 5 pour Discord)
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
            
            # Créer le ticket
            c = await cfg(interaction.guild.id)
            cat = interaction.guild.get_channel(c.get('ticket_category', 0))
            staff = interaction.guild.get_role(c.get('ticket_staff', 0))
            
            if not cat:
                return await interaction.followup.send("❌ Système non configuré", ephemeral=True)
            
            # Vérifier ticket existant
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (interaction.guild.id, interaction.user.id)) as cursor:
                    if await cursor.fetchone():
                        return await interaction.followup.send("❌ Vous avez déjà un ticket ouvert", ephemeral=True)
            
            # Permissions initiales (avant claim)
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True)
            }
            # Staff peut voir avant claim
            if staff:
                overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            # Owner peut toujours voir
            if interaction.guild.owner:
                overwrites[interaction.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
            
            channel = await interaction.guild.create_text_channel(
                f"ticket-{interaction.user.name}"[:50], 
                category=cat, 
                overwrites=overwrites
            )
            
            # Sauvegarder avec réponses
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT INTO tickets (guild_id,channel_id,user_id,answers) VALUES (?,?,?,?)', 
                    (interaction.guild.id, channel.id, interaction.user.id, json.dumps(answers, ensure_ascii=False)))
                await db.commit()
                
                # Récupérer l'ID
                async with db.execute('SELECT id FROM tickets WHERE channel_id=?', (channel.id,)) as c:
                    ticket_row = await c.fetchone()
                    ticket_id = ticket_row[0] if ticket_row else 0
            
            # Embed avec réponses
            embed = discord.Embed(title="🎫 Nouveau Ticket", color=C.BLURPLE, timestamp=now())
            embed.add_field(name="👤 Créé par", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
            embed.add_field(name="🎫 ID", value=f"#{ticket_id}", inline=True)
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            
            # Ajouter les réponses
            for title, answer in answers.items():
                embed.add_field(name=f"📝 {title}", value=answer[:1024], inline=False)
            
            embed.set_footer(text="Un membre du staff va prendre votre ticket en charge")
            
            mention = interaction.user.mention
            if staff: mention += f" {staff.mention}"
            
            await channel.send(content=mention, embed=embed, view=TicketControlView())
            await interaction.followup.send(f"✅ Ticket créé: {channel.mention}", ephemeral=True)
            
            # Log création
            await send_ticket_log(interaction.guild, 'create', interaction.user, {'id': ticket_id, 'answers': answers})
            
        except Exception as ex:
            print(f"[QUESTIONNAIRE ERROR] {ex}\n{traceback.format_exc()}")
            try:
                await interaction.followup.send("❌ Erreur lors de la création", ephemeral=True)
            except: pass


class TicketCreateView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📩 Créer un ticket", style=discord.ButtonStyle.success, custom_id="ticket_btn_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        try:
            c = await cfg(interaction.guild.id)
            questions = c.get('ticket_questions', [])
            
            # Si questionnaire configuré
            if questions:
                modal = TicketQuestionnaireModal(interaction.guild.id, questions)
                await interaction.response.send_modal(modal)
            else:
                # Création directe sans questionnaire
                await interaction.response.defer(ephemeral=True)
                
                cat = interaction.guild.get_channel(c.get('ticket_category', 0))
                staff = interaction.guild.get_role(c.get('ticket_staff', 0))
                
                if not cat:
                    return await interaction.followup.send("❌ Système non configuré", ephemeral=True)
                
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (interaction.guild.id, interaction.user.id)) as cursor:
                        if await cursor.fetchone():
                            return await interaction.followup.send("❌ Vous avez déjà un ticket ouvert", ephemeral=True)
                
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
                    interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True)
                }
                if staff:
                    overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                if interaction.guild.owner:
                    overwrites[interaction.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
                
                channel = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name}"[:50], category=cat, overwrites=overwrites)
                
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute('INSERT INTO tickets (guild_id,channel_id,user_id) VALUES (?,?,?)', (interaction.guild.id, channel.id, interaction.user.id))
                    await db.commit()
                    async with db.execute('SELECT id FROM tickets WHERE channel_id=?', (channel.id,)) as cursor:
                        ticket_row = await cursor.fetchone()
                        ticket_id = ticket_row[0] if ticket_row else 0
                
                embed = discord.Embed(title="🎫 Nouveau Ticket", color=C.BLURPLE, timestamp=now())
                embed.add_field(name="👤 Créé par", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
                embed.add_field(name="🎫 ID", value=f"#{ticket_id}", inline=True)
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                embed.set_footer(text="Décrivez votre problème ci-dessous")
                
                mention = interaction.user.mention
                if staff: mention += f" {staff.mention}"
                
                await channel.send(content=mention, embed=embed, view=TicketControlView())
                await interaction.followup.send(f"✅ Ticket créé: {channel.mention}", ephemeral=True)
                
                await send_ticket_log(interaction.guild, 'create', interaction.user, {'id': ticket_id, 'answers': {}})
                
        except Exception as ex:
            print(f"[TICKET CREATE ERROR] {ex}\n{traceback.format_exc()}")
            try:
                await interaction.followup.send("❌ Erreur", ephemeral=True)
            except: pass


class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🙋 Prendre en charge", style=discord.ButtonStyle.success, custom_id="ticket_btn_claim")
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
            
            # Seul staff ou owner peut claim
            is_staff = staff_role and staff_role in interaction.user.roles
            is_owner = interaction.user.id == interaction.guild.owner_id
            is_admin = interaction.user.guild_permissions.administrator
            
            if not (is_staff or is_owner or is_admin):
                return await interaction.response.send_message("❌ Réservé au staff", ephemeral=True)
            
            # Mettre à jour les permissions - Seuls user, staff qui claim, owner voient
            ticket_user = interaction.guild.get_member(ticket['user'])
            
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)  # Staff qui claim
            }
            if ticket_user:
                overwrites[ticket_user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
            if interaction.guild.owner and interaction.guild.owner != interaction.user:
                overwrites[interaction.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
            
            # Retirer le rôle staff des permissions (ils ne voient plus)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=False)
            
            await interaction.channel.edit(overwrites=overwrites)
            
            # Mettre à jour DB
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (interaction.user.id, interaction.channel.id))
                await db.commit()
            
            await interaction.response.send_message(f"✅ **{interaction.user.display_name}** prend ce ticket en charge\n\n*Les autres staffs ne peuvent plus voir ce ticket.*")
            
            # Désactiver le bouton claim
            button.disabled = True
            button.label = f"Pris par {interaction.user.display_name}"
            button.style = discord.ButtonStyle.secondary
            await interaction.message.edit(view=self)
            
            # Log
            ticket['claimed'] = interaction.user.id
            await send_ticket_log(interaction.guild, 'claim', ticket_user or ticket['user'], ticket, extra_info=interaction.user.id)
            
        except Exception as ex:
            print(f"[TICKET CLAIM ERROR] {ex}\n{traceback.format_exc()}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="➕ Ajouter Staff", style=discord.ButtonStyle.primary, custom_id="ticket_btn_addstaff")
    async def add_staff(self, interaction: discord.Interaction, button: Button):
        try:
            ticket = await get_ticket(interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            
            # Seul le staff qui a claim ou owner peut ajouter
            is_owner = interaction.user.id == interaction.guild.owner_id
            is_claimer = interaction.user.id == ticket['claimed']
            
            if not ticket['claimed']:
                return await interaction.response.send_message("❌ Le ticket doit d'abord être pris en charge", ephemeral=True)
            
            if not (is_claimer or is_owner):
                return await interaction.response.send_message("❌ Seul le staff en charge ou le fondateur peut ajouter quelqu'un", ephemeral=True)
            
            # Afficher select pour choisir un staff
            c = await cfg(interaction.guild.id)
            staff_role = interaction.guild.get_role(c.get('ticket_staff', 0))
            
            if not staff_role:
                return await interaction.response.send_message("❌ Aucun rôle staff configuré", ephemeral=True)
            
            # Liste des staffs (sauf celui qui a déjà claim)
            staffs = [m for m in staff_role.members if m.id != ticket['claimed'] and m.id != ticket['user']][:25]
            
            if not staffs:
                return await interaction.response.send_message("❌ Aucun autre staff disponible", ephemeral=True)
            
            opts = [discord.SelectOption(label=f"@{m.display_name}"[:25], value=str(m.id)) for m in staffs]
            v = AddStaffSelectView(opts, interaction.channel.id)
            await interaction.response.send_message("👥 Choisir un staff à ajouter:", view=v, ephemeral=True)
            
        except Exception as ex:
            print(f"[ADD STAFF ERROR] {ex}")
            await interaction.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="ticket_btn_close")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        try:
            ticket = await get_ticket(interaction.channel.id)
            if not ticket:
                return await interaction.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            
            # Seul le staff qui a claim ou owner peut fermer
            is_owner = interaction.user.id == interaction.guild.owner_id
            is_claimer = interaction.user.id == ticket['claimed']
            
            # Si pas encore claim, staff ou owner peut fermer
            if ticket['claimed']:
                if not (is_claimer or is_owner):
                    return await interaction.response.send_message("❌ Seul le staff en charge ou le fondateur peut fermer ce ticket", ephemeral=True)
            else:
                c = await cfg(interaction.guild.id)
                staff_role = interaction.guild.get_role(c.get('ticket_staff', 0))
                is_staff = staff_role and staff_role in interaction.user.roles
                if not (is_staff or is_owner):
                    return await interaction.response.send_message("❌ Seul le staff ou le fondateur peut fermer", ephemeral=True)
            
            # Log avant suppression
            ticket_user = interaction.guild.get_member(ticket['user'])
            await send_ticket_log(interaction.guild, 'close', ticket_user or ticket['user'], ticket, closer=interaction.user, channel=interaction.channel)
            
            # Fermer
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (interaction.channel.id,))
                await db.commit()
            
            await interaction.response.send_message("🔒 Fermeture du ticket dans 3 secondes...")
            await asyncio.sleep(3)
            await interaction.channel.delete()
            
        except Exception as ex:
            print(f"[TICKET CLOSE ERROR] {ex}\n{traceback.format_exc()}")
            try:
                await interaction.response.send_message("❌ Erreur", ephemeral=True)
            except: pass


class AddStaffSelectView(View):
    def __init__(self, opts, channel_id):
        super().__init__(timeout=60)
        self.channel_id = channel_id
        self.add_item(AddStaffSelect(opts, channel_id))


class AddStaffSelect(Select):
    def __init__(self, opts, channel_id):
        super().__init__(placeholder="Choisir un staff...", options=opts)
        self.channel_id = channel_id
    
    async def callback(self, interaction: discord.Interaction):
        try:
            staff_id = int(self.values[0])
            staff = interaction.guild.get_member(staff_id)
            channel = interaction.guild.get_channel(self.channel_id)
            
            if not staff or not channel:
                return await interaction.response.send_message("❌ Erreur", ephemeral=True)
            
            # Ajouter les permissions
            await channel.set_permissions(staff, view_channel=True, send_messages=True, read_message_history=True)
            
            await interaction.response.send_message(f"✅ {staff.mention} a été ajouté au ticket!", ephemeral=True)
            await channel.send(f"➕ **{staff.display_name}** a été ajouté au ticket par {interaction.user.mention}")
            
            # Log
            ticket = await get_ticket(self.channel_id)
            if ticket:
                await send_ticket_log(interaction.guild, 'add_staff', ticket['user'], ticket, extra_info=staff_id)
            
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
        v = TicketConfigPanel(self.u, self.g)
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
#                           🛡️ PROTECTION PANEL
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
        
        if self.key == "anti_link":
            e.add_field(name="Whitelist", value=", ".join([f"`{d}`" for d in c.get('link_whitelist',[])[:8]]) or "*Aucun*", inline=False)
        elif self.key == "anti_image":
            items = c.get('image_allowed',[])
            fmts = ['png','jpg','jpeg','gif','webp','tenor','giphy']
            e.add_field(name="Formats", value=" ".join([f"{'✅' if f in items else '❌'}`{f}`" for f in fmts]), inline=False)
        elif self.key == "anti_badwords":
            e.add_field(name="Mots", value=", ".join([f"`{w}`" for w in c.get('badwords_list',[])[:10]]) or "*Aucun*", inline=False)
        
        log_ch = self.g.get_channel(c.get(f'log_{self.key}',0))
        e.add_field(name="📜 Log", value=log_ch.mention if log_ch else "❌", inline=False)
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        await db_set(self.g.id, self.key, 0 if c.get(self.key) else 1)
        await interaction.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="Config", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, interaction: discord.Interaction, button: Button):
        if self.key == "anti_image":
            v = ImageCfgPanel(self.u, self.g)
            await interaction.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_badwords":
            await interaction.response.send_modal(AddWordsModal(self.g))
        else:
            await interaction.response.send_message("⚙️ Pas de config", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = ProtPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

class AddWordsModal(Modal, title="➕ Ajouter des mots"):
    words = TextInput(label="Mot(s) séparés par virgules", placeholder="mot1, mot2", style=discord.TextStyle.paragraph)
    def __init__(self, g): super().__init__(); self.g = g
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('badwords_list', [])
        new = [x.strip().lower() for x in self.words.value.split(',') if x.strip()]
        items.extend([x for x in new if x not in items])
        await db_set(self.g.id, 'badwords_list', items)
        await i.response.send_message(f"✅ Ajouté", ephemeral=True)

class ImageCfgPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmts = ['png','jpg','jpeg','gif','webp','tenor','giphy']
        e = discord.Embed(title="🖼️ Anti-Images", color=C.BLUE)
        e.add_field(name="Formats", value=" ".join([f"{'✅' if f in items else '❌'} `{f}`" for f in fmts]), inline=False)
        return e

    @discord.ui.button(label="➕ Format", style=discord.ButtonStyle.success, row=0)
    async def add_fmt(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmts = ['png','jpg','jpeg','gif','webp','tenor','giphy']
        avail = [f for f in fmts if f not in items]
        if not avail:
            return await interaction.response.send_message("✅ Tous autorisés", ephemeral=True)
        v = FormatSelectView(self.u, self.g, avail, 'add')
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="➖ Format", style=discord.ButtonStyle.danger, row=0)
    async def rem_fmt(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        if not items:
            return await interaction.response.send_message("❌ Vide", ephemeral=True)
        v = FormatSelectView(self.u, self.g, items, 'rem')
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        prot = next(p for p in PROTS if p[0]=="anti_image")
        v = ProtDetail(self.u, self.g, prot)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

class FormatSelectView(View):
    def __init__(self, u, g, fmts, action):
        super().__init__(timeout=120)
        self.u, self.g, self.action = u, g, action
        opts = [discord.SelectOption(label=f.upper(), value=f) for f in fmts]
        self.add_item(FormatSelect(u, g, opts, action))

class FormatSelect(Select):
    def __init__(self, u, g, opts, action):
        super().__init__(placeholder="Format...", options=opts)
        self.u, self.g, self.action = u, g, action
    async def callback(self, i):
        c = await cfg(i.guild.id)
        items = c.get('image_allowed', [])
        f = self.values[0]
        if self.action == 'add' and f not in items: items.append(f)
        elif self.action == 'rem' and f in items: items.remove(f)
        await db_set(i.guild.id, 'image_allowed', items)
        v = ImageCfgPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👑 IMMUNITÉS
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

# ═══════════════════════════════════════════════════════════════════════════════
#                           📺 CONFIG SALON
# ═══════════════════════════════════════════════════════════════════════════════

class ChanPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        e = discord.Embed(title="📺 Config Salon", color=C.ORANGE)
        if configs:
            lines = []
            for ch_id, conf in list(configs.items())[:10]:
                ch = self.g.get_channel(int(ch_id))
                if ch:
                    icons = "💬" if conf.get('messages', True) else ""
                    icons += "🖼️" if conf.get('images', True) else ""
                    icons += "🎞️" if conf.get('gifs', True) else ""
                    lines.append(f"{ch.mention}: {icons or '🚫'}")
            e.description = "\n".join(lines) or "*Aucun*"
        else:
            e.description = "*Aucun*"
        return e

    @discord.ui.button(label="➕ Config", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction: discord.Interaction, button: Button):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        v = ChanSelectView(self.u, self.g, opts)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = MainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=v.embed(), view=v)

class ChanSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ChanSelect(u, g, opts))

class ChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Salon...", options=opts)
        self.u, self.g = u, g
    async def callback(self, i):
        v = EditChanCfg(self.u, self.g, self.values[0])
        await i.response.edit_message(embed=await v.embed(), view=v)

class EditChanCfg(View):
    def __init__(self, u, g, ch_id):
        super().__init__(timeout=600)
        self.u, self.g, self.ch_id = u, g, ch_id

    async def get_conf(self):
        c = await cfg(self.g.id)
        return c.get('channel_configs', {}).get(str(self.ch_id), {'messages':True,'images':True,'gifs':True,'emojis':True,'links':True})

    async def save(self, conf):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        configs[str(self.ch_id)] = conf
        await db_set(self.g.id, 'channel_configs', configs)

    async def embed(self):
        ch = self.g.get_channel(int(self.ch_id))
        conf = await self.get_conf()
        s = lambda k: "✅" if conf.get(k, True) else "❌"
        e = discord.Embed(title=f"📺 #{ch.name if ch else '?'}", color=C.ORANGE)
        e.description = f"💬 Messages: {s('messages')}\n🖼️ Images: {s('images')}\n🎞️ GIFs: {s('gifs')}\n😀 Emojis: {s('emojis')}\n🔗 Liens: {s('links')}"
        return e

    async def toggle(self, i, key):
        conf = await self.get_conf()
        conf[key] = not conf.get(key, True)
        await self.save(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="💬", style=discord.ButtonStyle.primary, row=0)
    async def t1(self, i, b): await self.toggle(i, 'messages')
    @discord.ui.button(label="🖼️", style=discord.ButtonStyle.primary, row=0)
    async def t2(self, i, b): await self.toggle(i, 'images')
    @discord.ui.button(label="🎞️", style=discord.ButtonStyle.primary, row=0)
    async def t3(self, i, b): await self.toggle(i, 'gifs')
    @discord.ui.button(label="😀", style=discord.ButtonStyle.primary, row=1)
    async def t4(self, i, b): await self.toggle(i, 'emojis')
    @discord.ui.button(label="🔗", style=discord.ButtonStyle.primary, row=1)
    async def t5(self, i, b): await self.toggle(i, 'links')

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = ChanPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎫 TICKET CONFIG PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class TicketConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎫 Configuration Tickets", color=C.PURPLE)
        
        panel_ch = self.g.get_channel(c.get('ticket_panel', 0))
        e.add_field(name="📍 Salon", value=panel_ch.mention if panel_ch else "❌", inline=True)
        
        cat = self.g.get_channel(c.get('ticket_category', 0))
        e.add_field(name="📁 Catégorie", value=cat.name if cat else "❌", inline=True)
        
        staff = self.g.get_role(c.get('ticket_staff', 0))
        e.add_field(name="👮 Staff", value=staff.mention if staff else "❌", inline=True)
        
        log_ch = self.g.get_channel(c.get('ticket_log', 0))
        e.add_field(name="📜 Logs", value=log_ch.mention if log_ch else "❌", inline=True)
        
        # Questions
        questions = c.get('ticket_questions', [])
        if questions:
            q_text = "\n".join([f"• **{q['title']}**: {q['question'][:50]}..." for q in questions[:5]])
            e.add_field(name=f"📝 Questions ({len(questions)})", value=q_text, inline=False)
        else:
            e.add_field(name="📝 Questions", value="*Aucune (création directe)*", inline=False)
        
        return e

    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_panel(self, interaction: discord.Interaction, button: Button):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        v = TicketSelectView(self.u, self.g, opts, 'ticket_panel')
        await interaction.response.edit_message(embed=discord.Embed(title="📍 Choisir le salon", color=C.PURPLE), view=v)

    @discord.ui.button(label="📁 Catégorie", style=discord.ButtonStyle.primary, row=0)
    async def set_cat(self, interaction: discord.Interaction, button: Button):
        cats = list(self.g.categories)[:25]
        if not cats:
            return await interaction.response.send_message("❌ Aucune catégorie", ephemeral=True)
        opts = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in cats]
        v = TicketSelectView(self.u, self.g, opts, 'ticket_category')
        await interaction.response.edit_message(embed=discord.Embed(title="📁 Choisir la catégorie", color=C.PURPLE), view=v)

    @discord.ui.button(label="👮 Staff", style=discord.ButtonStyle.primary, row=0)
    async def set_staff(self, interaction: discord.Interaction, button: Button):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        if not roles:
            return await interaction.response.send_message("❌ Aucun rôle", ephemeral=True)
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = TicketSelectView(self.u, self.g, opts, 'ticket_staff')
        await interaction.response.edit_message(embed=discord.Embed(title="👮 Choisir le rôle staff", color=C.PURPLE), view=v)

    @discord.ui.button(label="📜 Logs", style=discord.ButtonStyle.secondary, row=1)
    async def set_log(self, interaction: discord.Interaction, button: Button):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        v = TicketSelectView(self.u, self.g, opts, 'ticket_log')
        await interaction.response.edit_message(embed=discord.Embed(title="📜 Choisir le salon logs", color=C.PURPLE), view=v)

    @discord.ui.button(label="📝 Questions", style=discord.ButtonStyle.secondary, row=1)
    async def set_questions(self, interaction: discord.Interaction, button: Button):
        v = QuestionConfigPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="📤 Envoyer Panel", style=discord.ButtonStyle.success, row=1)
    async def send_panel(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        
        if not c.get('ticket_panel'):
            return await interaction.response.send_message("❌ Configure le **Salon** d'abord!", ephemeral=True)
        if not c.get('ticket_category'):
            return await interaction.response.send_message("❌ Configure la **Catégorie** d'abord!", ephemeral=True)
        if not c.get('ticket_staff'):
            return await interaction.response.send_message("❌ Configure le **Staff** d'abord!", ephemeral=True)
        
        ch = self.g.get_channel(c['ticket_panel'])
        if not ch:
            return await interaction.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        questions = c.get('ticket_questions', [])
        desc = "Cliquez sur le bouton ci-dessous pour créer un ticket."
        if questions:
            desc += f"\n\n📝 Vous devrez répondre à **{len(questions)}** question(s)."
        
        embed = discord.Embed(
            title="🎫 Support - Créer un ticket",
            description=desc,
            color=C.BLURPLE
        )
        await ch.send(embed=embed, view=TicketCreateView())
        await interaction.response.send_message(f"✅ Panel envoyé dans {ch.mention}!", ephemeral=True)

    @discord.ui.button(label="🔄 Rafraîchir", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = MainPanel(self.u, self.g)
        await interaction.response.edit_message(embed=v.embed(), view=v)


class QuestionConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        questions = c.get('ticket_questions', [])
        e = discord.Embed(title="📝 Configuration Questions", color=C.PURPLE)
        
        if questions:
            for i, q in enumerate(questions, 1):
                e.add_field(name=f"{i}. {q['title']}", value=q['question'][:100], inline=False)
        else:
            e.description = "*Aucune question configurée*\n\nSans questions, les tickets seront créés directement."
        
        e.set_footer(text="Maximum 5 questions (limite Discord)")
        return e

    @discord.ui.button(label="➕ Ajouter Question", style=discord.ButtonStyle.success, row=0)
    async def add_question(self, interaction: discord.Interaction, button: Button):
        c = await cfg(self.g.id)
        questions = c.get('ticket_questions', [])
        
        if len(questions) >= 5:
            return await interaction.response.send_message("❌ Maximum 5 questions (limite Discord)", ephemeral=True)
        
        await interaction.response.send_modal(AddQuestionModal(self.g, self.u))

    @discord.ui.button(label="🗑️ Supprimer Tout", style=discord.ButtonStyle.danger, row=0)
    async def clear_questions(self, interaction: discord.Interaction, button: Button):
        await db_set(self.g.id, 'ticket_questions', [])
        await interaction.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: Button):
        v = TicketConfigPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)


class AddQuestionModal(Modal, title="➕ Ajouter une question"):
    q_title = TextInput(label="Titre (affiché comme label)", placeholder="Ex: Pseudo en jeu", max_length=45)
    q_question = TextInput(label="Question / Description", placeholder="Ex: Quel est votre pseudo sur le serveur ?", style=discord.TextStyle.paragraph, max_length=100)
    
    def __init__(self, g, u):
        super().__init__()
        self.g, self.u = g, u
    
    async def on_submit(self, interaction: discord.Interaction):
        c = await cfg(self.g.id)
        questions = c.get('ticket_questions', [])
        
        questions.append({
            'title': self.q_title.value,
            'question': self.q_question.value
        })
        
        await db_set(self.g.id, 'ticket_questions', questions)
        
        v = QuestionConfigPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)


class TicketSelectView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(TicketConfigSelect(u, g, opts, key))


class TicketConfigSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Sélectionner...", options=opts)
        self.u, self.g, self.key = u, g, key
    
    async def callback(self, interaction: discord.Interaction):
        value = int(self.values[0])
        await db_set(interaction.guild.id, self.key, value)
        v = TicketConfigPanel(self.u, self.g)
        await interaction.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await db_init()
    bot.add_view(TicketCreateView())
    bot.add_view(TicketControlView())
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v11.0 prêt!")

@bot.event
async def on_member_remove(member):
    """Quand un membre quitte - vérifier s'il avait un ticket ouvert"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id, channel_id, claimed_by, answers FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (member.guild.id, member.id)) as c:
                ticket = await c.fetchone()
                
        if ticket:
            ticket_info = {'id': ticket[0], 'user': member.id, 'claimed': ticket[2], 'answers': json.loads(ticket[3]) if ticket[3] else {}}
            channel = member.guild.get_channel(ticket[1])
            
            # Log que l'utilisateur est parti
            await send_ticket_log(member.guild, 'leave', member, ticket_info)
            
            # Message dans le ticket
            if channel:
                embed = discord.Embed(
                    title="🚪 Utilisateur parti",
                    description=f"**{member.display_name}** a quitté le serveur.\nLe ticket reste ouvert pour archivage.",
                    color=C.ORANGE
                )
                await channel.send(embed=embed)
    except Exception as ex:
        print(f"[MEMBER REMOVE TICKET] {ex}")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return

    try:
        c = await cfg(msg.guild.id)
        content = msg.content or ""
        ch_id = msg.channel.id

        gif_type = get_gif_type(msg)
        allowed_gifs = c.get('image_allowed', [])
        is_allowed_gif = gif_type is not None and gif_type in allowed_gifs

        ch_conf = c.get('channel_configs', {}).get(str(ch_id))
        if ch_conf:
            if not (is_allowed_gif and ch_conf.get('gifs', True)):
                violation, vtype = check_channel_cfg(msg, ch_conf)
                if violation:
                    await msg.delete()
                    return

        if c.get('anti_phishing'):
            found, domain = check_phishing(content)
            if found:
                await msg.delete()
                await send_log(msg.guild, 'anti_phishing', msg.author, msg, "Phishing", f"`{domain}`")
                await sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing", msg.guild)
                return

        if c.get('anti_scam') and not await is_immune(msg.author, 'anti_scam'):
            found, pattern = check_scam(content)
            if found:
                await msg.delete()
                await send_log(msg.guild, 'anti_scam', msg.author, msg, "Scam", f"`{pattern}`")
                await sanction(msg.author, c.get('scam_action', 'mute'), 60, "Scam", msg.guild)
                return

        if c.get('anti_badwords') and not await is_immune(msg.author, 'anti_badwords'):
            found, word = check_badwords(content, c.get('badwords_list', []))
            if found:
                await msg.delete()
                await send_log(msg.guild, 'anti_badwords', msg.author, msg, "Mot interdit", f"`{word}`")
                return

        if c.get('anti_invite'):
            found, invite = check_invite(content)
            if found:
                await msg.delete()
                await send_log(msg.guild, 'anti_invite', msg.author, msg, "Invitation", f"`{invite}`")
                return

        if c.get('anti_link') and not is_allowed_gif:
            if ch_id not in c.get('link_allowed_channels', []):
                found, url = check_link(content, c.get('link_whitelist', []))
                if found:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_link', msg.author, msg, "Lien", f"`{url}`")
                    return

        if c.get('anti_image') and not await is_immune(msg.author, 'anti_image') and not is_allowed_gif:
            if ch_id not in c.get('image_allowed_channels', []):
                blocked = check_image(msg, c.get('image_allowed', []))
                if blocked:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_image', msg.author, msg, "Format", f"`{', '.join(blocked)}`")
                    return

        if c.get('anti_spam') and not await is_immune(msg.author, 'anti_spam'):
            if await check_spam(msg, c.get('spam_max', 5), c.get('spam_interval', 5)):
                await msg.delete()
                await send_log(msg.guild, 'anti_spam', msg.author, msg, "Spam", None)
                await sanction(msg.author, c.get('spam_action', 'mute'), 10, "Spam", msg.guild)
                return

        if c.get('anti_caps') and not await is_immune(msg.author, 'anti_caps'):
            if check_caps(content, c.get('caps_percent', 70)):
                await msg.delete()
                await send_log(msg.guild, 'anti_caps', msg.author, msg, "Caps", None)
                return

    except Exception as e:
        print(f"[MSG ERROR] {e}")

@bot.event
async def on_member_join(member):
    try:
        c = await cfg(member.guild.id)
        if c.get('anti_newaccount'):
            days = c.get('newaccount_days', 7)
            age = (now() - member.created_at.replace(tzinfo=timezone.utc)).days
            if age < days:
                await send_log(member.guild, 'anti_newaccount', member, None, "Compte récent", f"{age}j")
                await member.kick(reason=f"Compte récent ({age}j)")
    except: pass

@bot.tree.command(name="configure", description="⚙️ Configuration")
async def configure_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin requis", ephemeral=True)
    view = MainPanel(interaction.user, interaction.guild)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir")
@app_commands.describe(membre="Membre", raison="Raison")
async def warn_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message("❌", ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions (guild_id,user_id,mod_id,type,reason) VALUES (?,?,?,?,?)', (interaction.guild.id, membre.id, interaction.user.id, 'warn', raison))
        await db.commit()
    await interaction.response.send_message(f"⚠️ {membre.mention}: {raison}")

if __name__ == "__main__":
    print("🚀 v11.0")
    bot.run(TOKEN)
