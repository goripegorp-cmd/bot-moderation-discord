# ═══════════════════════════════════════════════════════════════════════════════
#                        🌟 BOT PREMIUM v10.6 🌟
#     GIF Check AVANT Anti-Link + Tickets Ultra Simplifiés
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
        await db.execute('CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, claimed_by INTEGER DEFAULT 0, description TEXT, status TEXT DEFAULT "open", created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        await db.execute('CREATE TABLE IF NOT EXISTS ticket_config (guild_id INTEGER PRIMARY KEY, panel_channel INTEGER DEFAULT 0, category INTEGER DEFAULT 0, staff_role INTEGER DEFAULT 0, log_channel INTEGER DEFAULT 0)')
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
    except: return False

async def cfg(gid):
    data = await db_get(gid)
    defaults = {'anti_link':0,'anti_invite':0,'anti_image':0,'anti_phishing':1,'anti_scam':1,'anti_spam':0,'anti_mention':0,'anti_caps':0,'anti_newaccount':0,'anti_badwords':0,'link_whitelist':[],'image_allowed':[],'badwords_list':[],'link_allowed_channels':[],'image_allowed_channels':[],'phishing_action':'ban','scam_action':'mute','spam_action':'mute','spam_max':5,'spam_interval':5,'caps_percent':70,'newaccount_days':7,'badwords_action':'delete','log_anti_link':0,'log_anti_image':0,'log_anti_phishing':0,'log_anti_scam':0,'log_anti_spam':0,'log_anti_caps':0,'log_anti_badwords':0,'log_anti_invite':0,'log_anti_newaccount':0,'channel_configs':{}}
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
#                    🎞️ GIF DETECTION - NOUVELLE LOGIQUE
# ═══════════════════════════════════════════════════════════════════════════════

def get_gif_type(msg):
    """
    Détecte si le message contient un GIF.
    Retourne: 'tenor', 'giphy', 'gif', ou None
    
    Vérifie TOUT: contenu texte, embeds, attachments, proxy Discord
    """
    # 1. Vérifier dans le contenu texte
    content = (msg.content or "").lower()
    
    # Tenor (direct ou via proxy Discord)
    if 'tenor.com' in content or 'tenor' in content:
        return 'tenor'
    if 'giphy.com' in content or 'giphy' in content:
        return 'giphy'
    
    # 2. Vérifier les embeds (GIFs envoyés via le picker Discord)
    for embed in msg.embeds:
        # Collecter toutes les URLs de l'embed
        urls = []
        if embed.url: urls.append(embed.url.lower())
        if embed.thumbnail and embed.thumbnail.url: urls.append(embed.thumbnail.url.lower())
        if embed.video and embed.video.url: urls.append(embed.video.url.lower())
        if embed.image and embed.image.url: urls.append(embed.image.url.lower())
        
        # Vérifier chaque URL
        for url in urls:
            if 'tenor' in url: return 'tenor'
            if 'giphy' in url: return 'giphy'
        
        # Vérifier le provider (Tenor, Giphy)
        if embed.provider and embed.provider.name:
            pn = embed.provider.name.lower()
            if 'tenor' in pn: return 'tenor'
            if 'giphy' in pn: return 'giphy'
        
        # Type gifv = GIF vidéo
        if embed.type == 'gifv':
            for url in urls:
                if 'tenor' in url: return 'tenor'
                if 'giphy' in url: return 'giphy'
            return 'gif'
    
    # 3. Vérifier les attachments
    for att in msg.attachments:
        fn = att.filename.lower()
        if fn.endswith('.gif'): return 'gif'
        # Discord peut convertir les GIFs en MP4/WebM
        if att.content_type:
            ct = att.content_type.lower()
            if 'gif' in ct: return 'gif'
    
    return None

def message_is_only_gif(msg):
    """Vérifie si le message ne contient QU'un GIF (pas de texte)"""
    content = (msg.content or "").strip()
    # Message vide ou juste une URL
    if not content or re.match(r'^https?://\S+$', content):
        return get_gif_type(msg) is not None
    return False

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
    """Vérifie les liens dans le contenu texte"""
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
    """Vérifie images/GIFs. Retourne les formats bloqués."""
    blocked = []
    al = [f.lower() for f in allowed]
    
    gif_type = get_gif_type(msg)
    if gif_type and gif_type not in al:
        blocked.append(gif_type)
    
    for att in msg.attachments:
        ext = att.filename.lower().split('.')[-1]
        if ext in ['png','jpg','jpeg','webp','bmp'] and ext not in al:
            blocked.append(ext)
    
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
#                           🎫 TICKETS - ULTRA SIMPLE
# ═══════════════════════════════════════════════════════════════════════════════

async def get_tcfg(gid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT panel_channel,category,staff_role,log_channel FROM ticket_config WHERE guild_id=?', (gid,)) as c:
            r = await c.fetchone()
            return {'panel':r[0],'cat':r[1],'staff':r[2],'log':r[3]} if r else {'panel':0,'cat':0,'staff':0,'log':0}

async def set_tcfg(gid, **kw):
    cur = await get_tcfg(gid)
    cur.update(kw)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO ticket_config (guild_id,panel_channel,category,staff_role,log_channel) VALUES (?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET panel_channel=?,category=?,staff_role=?,log_channel=?',
            (gid, cur['panel'], cur['cat'], cur['staff'], cur['log'], cur['panel'], cur['cat'], cur['staff'], cur['log']))
        await db.commit()

async def get_ticket(ch_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT id,user_id,claimed_by,description,created_at FROM tickets WHERE channel_id=? AND status="open"', (ch_id,)) as c:
            r = await c.fetchone()
            return {'id':r[0],'user':r[1],'claimed':r[2],'desc':r[3],'created':r[4]} if r else None

async def create_transcript(ch):
    lines = []
    try:
        async for m in ch.history(limit=200, oldest_first=True):
            ts = m.created_at.strftime("%H:%M")
            lines.append(f"[{ts}] {m.author.name}: {m.content or '[média]'}")
    except: pass
    return f"=== TICKET #{ch.name} ===\n" + "\n".join(lines)

async def send_ticket_log(guild, info, ch, closer):
    try:
        tc = await get_tcfg(guild.id)
        log_ch = guild.get_channel(tc['log'])
        if not log_ch: return
        
        user = guild.get_member(info['user'])
        staff = guild.get_member(info['claimed']) if info['claimed'] else None
        
        e = discord.Embed(title="🎫 Ticket Fermé", color=C.RED, timestamp=now())
        e.add_field(name="ID", value=f"#{info['id']}", inline=True)
        e.add_field(name="Créateur", value=f"<@{info['user']}>", inline=True)
        e.add_field(name="Staff", value=staff.mention if staff else "Non pris", inline=True)
        e.add_field(name="Fermé par", value=closer.mention, inline=True)
        if user: e.set_thumbnail(url=user.display_avatar.url)
        
        transcript = await create_transcript(ch)
        f = discord.File(io.BytesIO(transcript.encode()), filename=f"ticket-{info['id']}.txt")
        await log_ch.send(embed=e, file=f)
    except Exception as ex:
        print(f"[TICKET LOG] {ex}")

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎫 TICKETS VIEWS - PERSISTANTES
# ═══════════════════════════════════════════════════════════════════════════════

class TicketCreateView(View):
    """Bouton pour créer un ticket - PERSISTANT"""
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📩 Créer un ticket", style=discord.ButtonStyle.success, custom_id="gorp_ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            tc = await get_tcfg(interaction.guild.id)
            cat = interaction.guild.get_channel(tc['cat'])
            staff = interaction.guild.get_role(tc['staff'])
            
            if not cat:
                return await interaction.followup.send("❌ Système non configuré", ephemeral=True)
            
            # Vérifier ticket existant
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (interaction.guild.id, interaction.user.id)) as c:
                    if await c.fetchone():
                        return await interaction.followup.send("❌ Vous avez déjà un ticket ouvert", ephemeral=True)
            
            # Créer le salon
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
            }
            if staff:
                overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            
            channel = await interaction.guild.create_text_channel(
                f"ticket-{interaction.user.name}"[:50], 
                category=cat, 
                overwrites=overwrites
            )
            
            # Sauvegarder en DB
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT INTO tickets (guild_id,channel_id,user_id,description) VALUES (?,?,?,?)', 
                    (interaction.guild.id, channel.id, interaction.user.id, "Nouveau ticket"))
                await db.commit()
            
            # Envoyer message dans le ticket
            embed = discord.Embed(title="🎫 Nouveau Ticket", color=C.BLURPLE, timestamp=now())
            embed.add_field(name="👤 Créé par", value=f"{interaction.user.mention}\nID: `{interaction.user.id}`", inline=True)
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(text="Décrivez votre problème ci-dessous")
            
            mention = interaction.user.mention
            if staff: mention += f" {staff.mention}"
            
            await channel.send(content=mention, embed=embed, view=TicketControlView())
            await interaction.followup.send(f"✅ Ticket créé: {channel.mention}", ephemeral=True)
            
        except Exception as ex:
            print(f"[TICKET CREATE ERROR] {ex}\n{traceback.format_exc()}")
            await interaction.followup.send("❌ Une erreur est survenue", ephemeral=True)


class TicketControlView(View):
    """Boutons de contrôle du ticket - PERSISTANT"""
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🙋 Prendre en charge", style=discord.ButtonStyle.success, custom_id="gorp_ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        
        try:
            tc = await get_tcfg(interaction.guild.id)
            staff = interaction.guild.get_role(tc['staff'])
            
            # Vérifier permissions
            if staff and staff not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
                return await interaction.followup.send("❌ Réservé au staff", ephemeral=True)
            
            # Mettre à jour la DB
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (interaction.user.id, interaction.channel.id))
                await db.commit()
            
            # Envoyer confirmation
            embed = discord.Embed(
                title="✅ Ticket pris en charge",
                description=f"**{interaction.user.mention}** s'occupe de ce ticket",
                color=C.GREEN
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await interaction.followup.send(embed=embed)
            
            # Désactiver le bouton
            button.disabled = True
            button.label = f"Pris par {interaction.user.display_name}"
            button.style = discord.ButtonStyle.secondary
            await interaction.message.edit(view=self)
            
        except Exception as ex:
            print(f"[TICKET CLAIM ERROR] {ex}")
    
    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="gorp_ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        
        try:
            info = await get_ticket(interaction.channel.id)
            if not info:
                return await interaction.followup.send("❌ Ticket non trouvé en DB", ephemeral=True)
            
            # Envoyer le log
            await send_ticket_log(interaction.guild, info, interaction.channel, interaction.user)
            
            # Mettre à jour DB
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (interaction.channel.id,))
                await db.commit()
            
            # Fermer
            await interaction.followup.send("🔒 Fermeture du ticket dans 3 secondes...")
            await asyncio.sleep(3)
            await interaction.channel.delete()
            
        except Exception as ex:
            print(f"[TICKET CLOSE ERROR] {ex}\n{traceback.format_exc()}")

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 PANELS DE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

PROTS = [("anti_link","🔗","Anti-Liens"),("anti_invite","🎟️","Anti-Invite"),("anti_image","🖼️","Anti-Images"),("anti_phishing","🎣","Anti-Phishing"),("anti_scam","🚨","Anti-Scam"),("anti_spam","📨","Anti-Spam"),("anti_caps","🔠","Anti-Caps"),("anti_badwords","🤬","Anti-Insultes"),("anti_newaccount","👶","Anti-NewAccount")]

class MainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g
    async def interaction_check(self, i): return i.user.id == self.u.id
    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"**{self.g.name}**\n{self.g.member_count} membres"
        if self.g.icon: e.set_thumbnail(url=self.g.icon.url)
        return e

    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, row=0)
    async def logs(self, i, b):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📜 Logs", color=C.PURPLE)
        lines = [f"{em} {nm}: {self.g.get_channel(c.get(f'log_{k}',0)).mention if c.get(f'log_{k}') and self.g.get_channel(c.get(f'log_{k}')) else '❌'}" for k,em,nm in PROTS]
        e.description = "\n".join(lines)
        await i.response.edit_message(embed=e, view=BackView(self.u, self.g))

    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=0)
    async def imm(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Config Salon", emoji="📺", style=discord.ButtonStyle.primary, row=1)
    async def chan(self, i, b):
        v = ChanPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.success, row=1)
    async def tick(self, i, b):
        v = TicketPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close(self, i, b): await i.message.delete()

class BackView(View):
    def __init__(self, u, g):
        super().__init__(timeout=300)
        self.u, self.g = u, g
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

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
    async def sel(self, i, s):
        prot = next(p for p in PROTS if p[0]==s.values[0])
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

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
            wl = c.get('link_whitelist',[])
            ch = c.get('link_allowed_channels',[])
            e.add_field(name=f"Whitelist ({len(wl)})", value=", ".join([f"`{d}`" for d in wl[:8]]) or "*Aucun*", inline=False)
            e.add_field(name=f"Salons ({len(ch)})", value=", ".join([f"<#{x}>" for x in ch[:5]]) or "*Aucun*", inline=False)
            e.add_field(name="💡 GIFs", value="**Les GIFs Tenor/Giphy autorisés dans Anti-Images passent automatiquement !**", inline=False)
        elif self.key == "anti_image":
            items = c.get('image_allowed',[])
            fmts = ['png','jpg','jpeg','gif','webp','tenor','giphy']
            e.add_field(name="Formats", value=" ".join([f"{'✅' if f in items else '❌'}`{f}`" for f in fmts]), inline=False)
            e.add_field(name="💡", value="`tenor` = GIFs Tenor\n`giphy` = GIFs Giphy\n`gif` = Fichiers .gif", inline=False)
        elif self.key == "anti_badwords":
            wds = c.get('badwords_list',[])
            e.add_field(name=f"Mots ({len(wds)})", value=", ".join([f"`{w}`" for w in wds[:12]]) or "*Aucun*", inline=False)
        
        log_ch = self.g.get_channel(c.get(f'log_{self.key}',0))
        e.add_field(name="📜 Log", value=log_ch.mention if log_ch else "❌ Non configuré", inline=False)
        return e

    @discord.ui.button(label="ON/OFF", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        c = await cfg(self.g.id)
        await db_set(self.g.id, self.key, 0 if c.get(self.key) else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)

    @discord.ui.button(label="Configurer", emoji="⚙️", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        if self.key == "anti_link":
            v = LinkCfgPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_image":
            v = ImageCfgPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_badwords":
            v = BadwordsCfgPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        else:
            await i.response.send_message("⚙️ Pas de config supplémentaire", ephemeral=True)

    @discord.ui.button(label="📜 Log", style=discord.ButtonStyle.success, row=0)
    async def log(self, i, b):
        v = LogSelectPanel(self.u, self.g, self.key, self.prot)
        await i.response.edit_message(embed=discord.Embed(title=f"📜 Salon de log pour {self.prot[2]}", color=C.PURPLE), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LogSelectPanel(View):
    def __init__(self, u, g, key, prot):
        super().__init__(timeout=120)
        self.u, self.g, self.key, self.prot = u, g, key, prot
        chs = list(g.text_channels)[:24]
        opts = [discord.SelectOption(label="❌ Désactiver", value="0")]
        opts += [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        self.add_item(LogSelect(opts, key, prot))

class LogSelect(Select):
    def __init__(self, opts, key, prot):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.key, self.prot = key, prot
    async def callback(self, i):
        await db_set(i.guild.id, f'log_{self.key}', int(self.values[0]))
        v = ProtDetail(i.user, i.guild, self.prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           CONFIG PROTECTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class LinkCfgPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        wl = c.get('link_whitelist',[])
        ch = c.get('link_allowed_channels',[])
        e = discord.Embed(title="🔗 Configuration Anti-Liens", color=C.BLUE)
        e.add_field(name=f"✅ Domaines autorisés ({len(wl)})", value="\n".join([f"• `{d}`" for d in wl[:15]]) or "*Aucun domaine*", inline=False)
        e.add_field(name=f"📍 Salons exemptés ({len(ch)})", value="\n".join([f"• <#{x}>" for x in ch[:10]]) or "*Aucun salon*", inline=False)
        e.add_field(name="💡 Note importante", value="Les **GIFs Tenor/Giphy** autorisés dans Anti-Images ne sont **jamais** bloqués par Anti-Liens !", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter domaine", style=discord.ButtonStyle.success, row=0)
    async def add_domain(self, i, b):
        await i.response.send_modal(AddDomainModal(self.g, self.u))

    @discord.ui.button(label="➕ Ajouter salon", style=discord.ButtonStyle.success, row=0)
    async def add_channel(self, i, b):
        v = AddChannelPanel(self.u, self.g, 'link_allowed_channels', 'anti_link')
        await i.response.edit_message(embed=discord.Embed(title="➕ Ajouter un salon", color=C.GREEN), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0]=="anti_link")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddDomainModal(Modal, title="➕ Ajouter des domaines"):
    domains = TextInput(label="Domaine(s) - séparés par des virgules", placeholder="youtube.com, twitch.tv, twitter.com", style=discord.TextStyle.paragraph)
    
    def __init__(self, g, u):
        super().__init__()
        self.g, self.u = g, u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('link_whitelist', [])
        new = [x.strip().lower() for x in self.domains.value.split(',') if x.strip()]
        added = [x for x in new if x not in items]
        items.extend(added)
        await db_set(self.g.id, 'link_whitelist', items)
        await i.response.send_message(f"✅ Ajouté: `{', '.join(added)}`" if added else "⚠️ Déjà présents", ephemeral=True)

class AddChannelPanel(View):
    def __init__(self, u, g, key, prot_key):
        super().__init__(timeout=120)
        self.u, self.g, self.key, self.prot_key = u, g, key, prot_key
        chs = list(g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        self.add_item(AddChannelSelect(opts, key, prot_key))

class AddChannelSelect(Select):
    def __init__(self, opts, key, prot_key):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.key, self.prot_key = key, prot_key
    async def callback(self, i):
        c = await cfg(i.guild.id)
        items = c.get(self.key, [])
        ch_id = int(self.values[0])
        if ch_id not in items:
            items.append(ch_id)
            await db_set(i.guild.id, self.key, items)
        prot = next(p for p in PROTS if p[0]==self.prot_key)
        v = ProtDetail(i.user, i.guild, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ImageCfgPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmts = ['png','jpg','jpeg','gif','webp','tenor','giphy']
        e = discord.Embed(title="🖼️ Configuration Anti-Images", color=C.BLUE)
        e.add_field(name="Formats", value=" ".join([f"{'✅' if f in items else '❌'} `{f}`" for f in fmts]), inline=False)
        e.add_field(name="📍 Salons exemptés", value=", ".join([f"<#{x}>" for x in c.get('image_allowed_channels',[])[:8]]) or "*Aucun*", inline=False)
        e.add_field(name="💡 Important", value="• `tenor` = GIFs envoyés via Tenor\n• `giphy` = GIFs envoyés via Giphy\n• `gif` = Fichiers .gif uploadés\n\n**Si autorisés, ces formats passent aussi Anti-Liens !**", inline=False)
        return e

    @discord.ui.button(label="➕ Autoriser format", style=discord.ButtonStyle.success, row=0)
    async def add_fmt(self, i, b):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmts = ['png','jpg','jpeg','gif','webp','tenor','giphy']
        avail = [f for f in fmts if f not in items]
        if not avail:
            return await i.response.send_message("✅ Tous les formats sont déjà autorisés", ephemeral=True)
        v = FormatSelectPanel(self.u, self.g, avail, 'add')
        await i.response.edit_message(embed=discord.Embed(title="➕ Autoriser un format", color=C.GREEN), view=v)

    @discord.ui.button(label="➖ Retirer format", style=discord.ButtonStyle.danger, row=0)
    async def rem_fmt(self, i, b):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        if not items:
            return await i.response.send_message("❌ Aucun format autorisé", ephemeral=True)
        v = FormatSelectPanel(self.u, self.g, items, 'remove')
        await i.response.edit_message(embed=discord.Embed(title="➖ Retirer un format", color=C.RED), view=v)

    @discord.ui.button(label="➕ Salon exempt", style=discord.ButtonStyle.success, row=1)
    async def add_ch(self, i, b):
        v = AddChannelPanel(self.u, self.g, 'image_allowed_channels', 'anti_image')
        await i.response.edit_message(embed=discord.Embed(title="➕ Ajouter salon", color=C.GREEN), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0]=="anti_image")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class FormatSelectPanel(View):
    def __init__(self, u, g, fmts, action):
        super().__init__(timeout=120)
        self.u, self.g = u, g
        labels = {'tenor': 'TENOR (GIFs)', 'giphy': 'GIPHY (GIFs)', 'gif': 'GIF (fichiers)'}
        opts = [discord.SelectOption(label=labels.get(f, f.upper()), value=f) for f in fmts]
        self.add_item(FormatSelect(opts, action))

class FormatSelect(Select):
    def __init__(self, opts, action):
        super().__init__(placeholder="Choisir un format...", options=opts)
        self.action = action
    async def callback(self, i):
        c = await cfg(i.guild.id)
        items = c.get('image_allowed', [])
        fmt = self.values[0]
        if self.action == 'add' and fmt not in items:
            items.append(fmt)
        elif self.action == 'remove' and fmt in items:
            items.remove(fmt)
        await db_set(i.guild.id, 'image_allowed', items)
        v = ImageCfgPanel(i.user, i.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class BadwordsCfgPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        c = await cfg(self.g.id)
        words = c.get('badwords_list', [])
        e = discord.Embed(title="🤬 Configuration Anti-Insultes", color=C.BLUE)
        e.add_field(name=f"Mots interdits ({len(words)})", value=", ".join([f"`{w}`" for w in words[:25]]) or "*Aucun mot*", inline=False)
        return e

    @discord.ui.button(label="➕ Ajouter mots", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddWordsModal(self.g, self.u))

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0]=="anti_badwords")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddWordsModal(Modal, title="➕ Ajouter des mots"):
    words = TextInput(label="Mot(s) - séparés par des virgules", placeholder="mot1, mot2, mot3", style=discord.TextStyle.paragraph)
    
    def __init__(self, g, u):
        super().__init__()
        self.g, self.u = g, u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('badwords_list', [])
        new = [x.strip().lower() for x in self.words.value.split(',') if x.strip()]
        added = [x for x in new if x not in items]
        items.extend(added)
        await db_set(self.g.id, 'badwords_list', items)
        await i.response.send_message(f"✅ Ajouté: `{', '.join(added)}`" if added else "⚠️ Déjà présents", ephemeral=True)

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
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (self.g.id,)) as c:
                uids = [r[0] for r in await c.fetchall()]
        e = discord.Embed(title="👑 Immunités", color=C.YELLOW)
        e.add_field(name=f"Rôles immunisés ({len(rids)})", value=", ".join([f"<@&{r}>" for r in rids]) or "*Aucun*", inline=False)
        e.add_field(name=f"Membres immunisés ({len(uids)})", value=", ".join([f"<@{u}>" for u in uids]) or "*Aucun*", inline=False)
        e.add_field(name="⚠️ Note", value="Les immunités ne s'appliquent **pas** à: Anti-Phishing, Anti-Liens, Anti-Invite", inline=False)
        return e

    @discord.ui.button(label="➕ Rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = ImmuneRolePanel(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="➕ Ajouter rôle immunisé", color=C.GREEN), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ImmuneRolePanel(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u, self.g = u, g
        self.add_item(ImmuneRoleSelect(opts))

class ImmuneRoleSelect(Select):
    def __init__(self, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES (?,?)', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(i.user, i.guild)
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
        e = discord.Embed(title="📺 Configuration par salon", color=C.ORANGE)
        if configs:
            lines = []
            for ch_id, conf in list(configs.items())[:10]:
                ch = self.g.get_channel(int(ch_id))
                if ch:
                    icons = ""
                    icons += "💬" if conf.get('messages', True) else ""
                    icons += "🖼️" if conf.get('images', True) else ""
                    icons += "🎞️" if conf.get('gifs', True) else ""
                    icons += "😀" if conf.get('emojis', True) else ""
                    icons += "🔗" if conf.get('links', True) else ""
                    lines.append(f"{ch.mention}: {icons or '🚫 Tout bloqué'}")
            e.description = "\n".join(lines)
        else:
            e.description = "*Aucune configuration personnalisée*"
        return e

    @discord.ui.button(label="➕ Configurer salon", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        v = ChanSelectPanel(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📺 Choisir un salon", color=C.ORANGE), view=v)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ChanSelectPanel(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u, self.g = u, g
        self.add_item(ChanSelect(opts))

class ChanSelect(Select):
    def __init__(self, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
    async def callback(self, i):
        v = EditChanCfg(i.user, i.guild, self.values[0])
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
        e = discord.Embed(title=f"📺 Configuration de #{ch.name if ch else '?'}", color=C.ORANGE)
        e.description = f"💬 Messages texte: {s('messages')}\n🖼️ Images: {s('images')}\n🎞️ GIFs: {s('gifs')}\n😀 Emojis: {s('emojis')}\n🔗 Liens: {s('links')}"
        e.set_footer(text="Cliquez sur les boutons pour activer/désactiver")
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
#                           🎫 TICKETS PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class TicketPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u, self.g = u, g

    async def embed(self):
        tc = await get_tcfg(self.g.id)
        e = discord.Embed(title="🎫 Configuration Tickets", color=C.PURPLE)
        e.add_field(name="📍 Salon du panel", value=f"<#{tc['panel']}>" if tc['panel'] else "❌ Non configuré", inline=True)
        e.add_field(name="📁 Catégorie", value=self.g.get_channel(tc['cat']).name if self.g.get_channel(tc['cat']) else "❌ Non configuré", inline=True)
        e.add_field(name="👮 Rôle Staff", value=f"<@&{tc['staff']}>" if tc['staff'] else "❌ Non configuré", inline=True)
        e.add_field(name="📜 Salon Logs", value=f"<#{tc['log']}>" if tc['log'] else "❌ Non configuré", inline=True)
        return e

    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_panel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        v = TicketChanPanel(self.u, self.g, opts, 'panel')
        await i.response.edit_message(embed=discord.Embed(title="📍 Choisir le salon du panel", color=C.PURPLE), view=v)

    @discord.ui.button(label="📁 Catégorie", style=discord.ButtonStyle.primary, row=0)
    async def set_cat(self, i, b):
        cats = list(self.g.categories)[:25]
        opts = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in cats]
        v = TicketCatPanel(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📁 Choisir la catégorie", color=C.PURPLE), view=v)

    @discord.ui.button(label="👮 Staff", style=discord.ButtonStyle.primary, row=0)
    async def set_staff(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = TicketRolePanel(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="👮 Choisir le rôle staff", color=C.PURPLE), view=v)

    @discord.ui.button(label="📜 Logs", style=discord.ButtonStyle.secondary, row=1)
    async def set_log(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chs]
        v = TicketChanPanel(self.u, self.g, opts, 'log')
        await i.response.edit_message(embed=discord.Embed(title="📜 Choisir le salon des logs", color=C.PURPLE), view=v)

    @discord.ui.button(label="🔧 Création auto", style=discord.ButtonStyle.secondary, row=1)
    async def auto_create(self, i, b):
        try:
            cat = await self.g.create_category("🎫 Tickets")
            panel_ch = await self.g.create_text_channel("📩-créer-ticket", category=cat)
            log_ch = await self.g.create_text_channel("📜-logs-tickets", category=cat)
            await set_tcfg(self.g.id, panel=panel_ch.id, cat=cat.id, log=log_ch.id)
            await i.response.send_message(f"✅ Créé !\n📁 {cat.name}\n📍 {panel_ch.mention}\n📜 {log_ch.mention}", ephemeral=True)
        except Exception as ex:
            await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)

    @discord.ui.button(label="📤 Envoyer le panel", style=discord.ButtonStyle.success, row=1)
    async def send_panel(self, i, b):
        tc = await get_tcfg(self.g.id)
        if not all([tc['panel'], tc['cat'], tc['staff']]):
            return await i.response.send_message("❌ Configurez d'abord: Salon, Catégorie et Staff !", ephemeral=True)
        
        ch = self.g.get_channel(tc['panel'])
        if not ch:
            return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
        
        embed = discord.Embed(
            title="🎫 Support - Créer un ticket",
            description="Besoin d'aide ? Cliquez sur le bouton ci-dessous pour créer un ticket.\n\nUn membre du staff vous répondra rapidement.",
            color=C.BLURPLE
        )
        embed.set_footer(text="Décrivez votre problème en détail dans le ticket")
        
        await ch.send(embed=embed, view=TicketCreateView())
        await i.response.send_message(f"✅ Panel envoyé dans {ch.mention} !", ephemeral=True)

    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class TicketChanPanel(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.u, self.g, self.key = u, g, key
        self.add_item(TicketChanSelect(opts, key))

class TicketChanSelect(Select):
    def __init__(self, opts, key):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.key = key
    async def callback(self, i):
        await set_tcfg(i.guild.id, **{self.key: int(self.values[0])})
        v = TicketPanel(i.user, i.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TicketCatPanel(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u, self.g = u, g
        self.add_item(TicketCatSelect(opts))

class TicketCatSelect(Select):
    def __init__(self, opts):
        super().__init__(placeholder="Choisir une catégorie...", options=opts)
    async def callback(self, i):
        await set_tcfg(i.guild.id, cat=int(self.values[0]))
        v = TicketPanel(i.user, i.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TicketRolePanel(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.u, self.g = u, g
        self.add_item(TicketRoleSelect(opts))

class TicketRoleSelect(Select):
    def __init__(self, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
    async def callback(self, i):
        await set_tcfg(i.guild.id, staff=int(self.values[0]))
        v = TicketPanel(i.user, i.guild)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await db_init()
    # Enregistrer les views persistantes
    bot.add_view(TicketCreateView())
    bot.add_view(TicketControlView())
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v10.6 prêt !")
    print(f"📁 Database: {DB_PATH}")

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:
        return

    try:
        c = await cfg(msg.guild.id)
        content = msg.content or ""
        ch_id = msg.channel.id

        # ═══════════════════════════════════════════════════════════════
        # 🎞️ DÉTECTION GIF EN PREMIER !
        # Si c'est un GIF autorisé, on skip Anti-Liens et Anti-Images
        # ═══════════════════════════════════════════════════════════════
        gif_type = get_gif_type(msg)
        allowed_gifs = c.get('image_allowed', [])
        is_allowed_gif = gif_type is not None and gif_type in allowed_gifs

        # 📺 CONFIG SALON
        ch_conf = c.get('channel_configs', {}).get(str(ch_id))
        if ch_conf:
            # Si GIF autorisé et gifs autorisé dans le salon, on skip
            if not (is_allowed_gif and ch_conf.get('gifs', True)):
                violation, vtype = check_channel_cfg(msg, ch_conf)
                if violation:
                    await msg.delete()
                    return

        # 🎣 PHISHING (toujours vérifié)
        if c.get('anti_phishing'):
            found, domain = check_phishing(content)
            if found:
                await msg.delete()
                await send_log(msg.guild, 'anti_phishing', msg.author, msg, "Phishing détecté", f"`{domain}`")
                await sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing", msg.guild)
                return

        # 🚨 SCAM
        if c.get('anti_scam') and not await is_immune(msg.author, 'anti_scam'):
            found, pattern = check_scam(content)
            if found:
                await msg.delete()
                await send_log(msg.guild, 'anti_scam', msg.author, msg, "Scam détecté", f"`{pattern}`")
                await sanction(msg.author, c.get('scam_action', 'mute'), 60, "Scam", msg.guild)
                return

        # 🤬 BADWORDS
        if c.get('anti_badwords') and not await is_immune(msg.author, 'anti_badwords'):
            found, word = check_badwords(content, c.get('badwords_list', []))
            if found:
                await msg.delete()
                await send_log(msg.guild, 'anti_badwords', msg.author, msg, "Mot interdit", f"`{word}`")
                return

        # 🎟️ INVITE
        if c.get('anti_invite'):
            found, invite = check_invite(content)
            if found:
                await msg.delete()
                await send_log(msg.guild, 'anti_invite', msg.author, msg, "Invitation Discord", f"`{invite}`")
                return

        # 🔗 LIENS - SKIP SI GIF AUTORISÉ !
        if c.get('anti_link') and not is_allowed_gif:
            if ch_id not in c.get('link_allowed_channels', []):
                found, url = check_link(content, c.get('link_whitelist', []))
                if found:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_link', msg.author, msg, "Lien non autorisé", f"`{url}`")
                    return

        # 🖼️ IMAGES - SKIP SI GIF AUTORISÉ !
        if c.get('anti_image') and not await is_immune(msg.author, 'anti_image') and not is_allowed_gif:
            if ch_id not in c.get('image_allowed_channels', []):
                blocked = check_image(msg, c.get('image_allowed', []))
                if blocked:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_image', msg.author, msg, "Format non autorisé", f"`{', '.join(blocked)}`")
                    return

        # 📨 SPAM
        if c.get('anti_spam') and not await is_immune(msg.author, 'anti_spam'):
            if await check_spam(msg, c.get('spam_max', 5), c.get('spam_interval', 5)):
                await msg.delete()
                await send_log(msg.guild, 'anti_spam', msg.author, msg, "Spam détecté", None)
                await sanction(msg.author, c.get('spam_action', 'mute'), 10, "Spam", msg.guild)
                return

        # 🔠 CAPS
        if c.get('anti_caps') and not await is_immune(msg.author, 'anti_caps'):
            if check_caps(content, c.get('caps_percent', 70)):
                await msg.delete()
                await send_log(msg.guild, 'anti_caps', msg.author, msg, "Trop de majuscules", None)
                return

    except Exception as e:
        print(f"[MSG ERROR] {e}\n{traceback.format_exc()}")

@bot.event
async def on_member_join(member):
    try:
        c = await cfg(member.guild.id)
        if c.get('anti_newaccount'):
            days = c.get('newaccount_days', 7)
            age = (now() - member.created_at.replace(tzinfo=timezone.utc)).days
            if age < days:
                await send_log(member.guild, 'anti_newaccount', member, None, "Compte trop récent", f"Âge: {age} jours")
                await member.kick(reason=f"Compte trop récent ({age} jours)")
    except Exception as e:
        print(f"[JOIN ERROR] {e}")

@bot.tree.command(name="configure", description="⚙️ Ouvrir le panneau de configuration")
async def configure_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Vous devez être administrateur", ephemeral=True)
    view = MainPanel(interaction.user, interaction.guild)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
async def warn_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message("❌ Permission insuffisante", ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions (guild_id,user_id,mod_id,type,reason) VALUES (?,?,?,?,?)', 
            (interaction.guild.id, membre.id, interaction.user.id, 'warn', raison))
        await db.commit()
    await interaction.response.send_message(f"⚠️ {membre.mention} a été averti: {raison}")

if __name__ == "__main__":
    print("🚀 Démarrage v10.6...")
    bot.run(TOKEN)
