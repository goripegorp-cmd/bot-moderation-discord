try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import discord
from discord.ext import commands, taskstry:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput, Button
import aiosqlite, os, re, json, asyncio, unicodedata, io, time, aiohttp
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')  # Backend non-interactif
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from collections import defaultdict

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
DB_PATH = '/data/bot.db' if os.path.exists('/data') else 'bot.db'
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}
voice_join_tracker = {}  # {(guild_id, user_id): datetime} - pour tracker le temps en vocal

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22; GOLD=0xFFD700

PHISHING = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com']
SCAM_PATTERNS = [r'free\s*nitro', r'steam\s*gift', r'@everyone.*http']
LEET = {'a':['@','4'],'e':['3','€'],'i':['1','!'],'o':['0'],'s':['$','5'],'t':['7']}

def now(): return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('CREATE TABLE IF NOT EXISTS guild_config(guild_id INTEGER PRIMARY KEY, data TEXT DEFAULT "{}")')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles(guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id, role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_users(guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id, user_id))')
        await db.execute('''CREATE TABLE IF NOT EXISTS infractions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            mod_id INTEGER,
            type TEXT,
            reason TEXT,
            duration TEXT DEFAULT "",
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour tracker l'activité Realsy
        await db.execute('''CREATE TABLE IF NOT EXISTS realsy_tracking(
            guild_id INTEGER,
            user_id INTEGER,
            last_activity TEXT,
            warn_count INTEGER DEFAULT 0,
            PRIMARY KEY(guild_id, user_id)
        )''')
        # Table pour les suggestions
        await db.execute('''CREATE TABLE IF NOT EXISTS suggestions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour tracker l'activité des membres
        await db.execute('''CREATE TABLE IF NOT EXISTS member_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            activity_type TEXT,
            channel_id INTEGER,
            duration INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0,
            reactions INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour les stats d'inactivité
        await db.execute('''CREATE TABLE IF NOT EXISTS activity_tracking (
            guild_id INTEGER,
            user_id INTEGER,
            last_message DATETIME,
            last_vocal DATETIME,
            total_messages INTEGER DEFAULT 0,
            total_vocal_time INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )''')
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'") as cur:
            if not await cur.fetchone():
                await db.execute('CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, panel_id TEXT DEFAULT "", claimed_by INTEGER DEFAULT 0, status TEXT DEFAULT "open", answers TEXT DEFAULT "{}", created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
            else:
                async with db.execute("PRAGMA table_info(tickets)") as cur2:
                    cols = [r[1] for r in await cur2.fetchall()]
                for cn, ct in [('panel_id','TEXT DEFAULT ""'),('claimed_by','INTEGER DEFAULT 0'),('status','TEXT DEFAULT "open"'),('answers','TEXT DEFAULT "{}"')]:
                    if cn not in cols:
                        try: await db.execute(f'ALTER TABLE tickets ADD COLUMN {cn} {ct}')
                        except: pass
        # Migration infractions
        async with db.execute("PRAGMA table_info(infractions)") as cur:
            cols = [r[1] for r in await cur.fetchall()]
        if 'duration' not in cols:
            try: await db.execute('ALTER TABLE infractions ADD COLUMN duration TEXT DEFAULT ""')
            except: pass
        if 'created_at' not in cols:
            try: await db.execute('ALTER TABLE infractions ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP')
            except: pass
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
            await db.execute('INSERT INTO guild_config(guild_id, data) VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET data=?', (gid, jd, jd))
            await db.commit()
        return True
    except: return False

async def cfg(gid):
    data = await db_get(gid)
    defaults = {
        'anti_link': 0, 'anti_invite': 0, 'anti_image': 0, 'anti_phishing': 1, 'anti_scam': 1,
        'anti_spam': 0, 'anti_caps': 0, 'anti_newaccount': 0, 'anti_badwords': 0,
        'link_whitelist': [], 'image_allowed': [], 'badwords_list': [],
        'link_allowed_channels': [], 'image_allowed_channels': [],
        'phishing_action': 'ban', 'scam_action': 'mute', 'spam_action': 'mute',
        'spam_max': 5, 'spam_interval': 5, 'caps_percent': 70, 'newaccount_days': 7,
        'log_anti_link': 0, 'log_anti_image': 0, 'log_anti_phishing': 0, 'log_anti_scam': 0,
        'log_anti_spam': 0, 'log_anti_caps': 0, 'log_anti_badwords': 0, 'log_anti_invite': 0, 'log_anti_newaccount': 0,
        'channel_configs': {},
        'ticket_staff': 0, 'ticket_log': 0, 'ticket_panels': {},
        'mod_warn_role': 0, 'mod_mute_role': 0, 'mod_infractions_role': 0, 'mod_log_channel': 0
    }
    for k, v in defaults.items():
        if k not in data: data[k] = v
    return data

async def is_immune(m, key):
    if key != 'anti_phishing' and (m.guild_permissions.administrator or m.id == m.guild.owner_id):
        return True
    if key in ['anti_phishing', 'anti_link', 'anti_invite']:
        return False
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,)) as c:
                rids = [r[0] for r in await c.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (m.guild.id,)) as c:
                uids = [r[0] for r in await c.fetchall()]
        if any(role.id in rids for role in m.roles) or m.id in uids:
            return True
    except: pass
    return False

async def sanction(m, action, dur, reason, g):
    try:
        if action == 'mute': await m.timeout(timedelta(minutes=dur), reason=reason)
        elif action == 'kick': await m.kick(reason=reason)
        elif action == 'ban': await m.ban(reason=reason)
    except: pass

async def send_log(g, key, m, msg, reason, extra=None):
    try:
        c = await cfg(g.id)
        ch = g.get_channel(c.get(f'log_{key}', 0))
        if not ch: return
        e = discord.Embed(title=f"🛡️ {key.replace('anti_', '').upper()}", color=C.RED, timestamp=now())
        e.add_field(name="👤 Utilisateur", value=f"{m.mention} (`{m.id}`)", inline=True)
        if msg and msg.channel:
            e.add_field(name="📍 Salon", value=msg.channel.mention, inline=True)
        e.add_field(name="⚠️ Raison", value=reason, inline=False)
        if extra:
            e.add_field(name="ℹ️ Détails", value=extra, inline=False)
        e.set_thumbnail(url=m.display_avatar.url)
        await ch.send(embed=e)
    except: pass

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔍 CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def get_gif_type(msg):
    ct = (msg.content or "").lower()
    if 'tenor.com' in ct: return 'tenor'
    if 'giphy.com' in ct: return 'giphy'
    for emb in msg.embeds:
        if emb.url and 'tenor' in emb.url.lower(): return 'tenor'
        if emb.url and 'giphy' in emb.url.lower(): return 'giphy'
    for att in msg.attachments:
        if att.filename.lower().endswith('.gif'): return 'gif'
    return None

def normalize(t):
    t = t.lower()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    for l, vs in LEET.items():
        for v in vs: t = t.replace(v, l)
    return t

def check_badwords(ct, words):
    if not words: return False, None
    norm = normalize(ct)
    for w in words:
        if normalize(w.strip()) in norm: return True, w
    return False, None

def check_link(ct, wl):
    urls = re.findall(r'https?://([^\s<>"]+)', ct.lower())
    for url in urls:
        dom = url.split('/')[0]
        if not any(w.lower() in dom for w in wl): return True, url
    return False, None

def check_invite(ct):
    m = re.search(r'discord\.gg/\w+|discord\.com/invite/\w+', ct, re.I)
    return (True, m.group()) if m else (False, None)

def check_phishing(ct):
    for d in PHISHING:
        if d in ct.lower(): return True, d
    return False, None

def check_scam(ct):
    for p in SCAM_PATTERNS:
        if re.search(p, ct, re.I): return True, p
    return False, None

def check_caps(ct, pct):
    ltrs = [c for c in ct if c.isalpha()]
    if len(ltrs) < 10: return False
    return sum(1 for c in ltrs if c.isupper()) / len(ltrs) * 100 >= pct

def check_image(msg, allowed):
    blocked = []
    gt = get_gif_type(msg)
    if gt and gt not in allowed: blocked.append(gt)
    for att in msg.attachments:
        ext = att.filename.lower().split('.')[-1]
        if ext in ['png', 'jpg', 'jpeg', 'webp', 'bmp'] and ext not in allowed:
            blocked.append(ext)
    return blocked

async def check_spam(msg, mx, intv):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker: spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n - t).total_seconds() < intv]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > mx

def check_channel_cfg(msg, conf):
    if not conf: return False, None
    ct = (msg.content or "").strip()
    # Commands only - bloque tout sauf les commandes slash (qui n'apparaissent pas comme messages normaux)
    if conf.get('commands_only', False):
        # Si le message n'est pas vide, c'est pas une commande slash
        if ct or msg.attachments:
            return True, "commands_only"
    if not conf.get('messages', True):
        has_txt = bool(re.sub(r'<a?:\w+:\d+>|https?://\S+', '', ct).strip())
        if has_txt and not msg.attachments and not msg.embeds:
            return True, "messages"
    if not conf.get('images', True):
        for att in msg.attachments:
            if att.filename.lower().split('.')[-1] in ['png', 'jpg', 'jpeg', 'webp', 'bmp']:
                return True, "images"
    if not conf.get('gifs', True) and get_gif_type(msg):
        return True, "gifs"
    if not conf.get('emojis', True) and re.search(r'<a?:\w+:\d+>', ct):
        return True, "emojis"
    if not conf.get('links', True) and re.search(r'https?://', ct):
        return True, "links"
    return False, None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_ticket(ch_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id, user_id, claimed_by, answers, panel_id FROM tickets WHERE channel_id=? AND status="open"', (ch_id,)) as c:
                r = await c.fetchone()
                if r:
                    ans = {}
                    try: ans = json.loads(r[3]) if r[3] else {}
                    except: pass
                    return {'id': r[0], 'user': r[1], 'claimed': r[2] or 0, 'answers': ans, 'panel_id': r[4] or ''}
                return None
    except: return None

async def count_user_tickets(g, uid, pid=None):
    cnt = 0
    to_close = []
    try:
        q = "SELECT id, channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'"
        p = [g.id, uid]
        if pid:
            q += " AND panel_id=?"
            p.append(pid)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(q, p) as c:
                tks = await c.fetchall()
        for tid, chid in tks:
            if g.get_channel(chid): cnt += 1
            else: to_close.append(tid)
        if to_close:
            async with aiosqlite.connect(DB_PATH) as db:
                for t in to_close:
                    await db.execute("UPDATE tickets SET status='closed' WHERE id=?", (t,))
                await db.commit()
        return cnt
    except: return 0

async def send_ticket_log(g, lt, user, ti, extra=None, closer=None, ch=None):
    try:
        c = await cfg(g.id)
        lch = g.get_channel(c.get('ticket_log', 0))
        if not lch: return
        colors = {'create': C.GREEN, 'claim': C.BLUE, 'close': C.RED, 'leave': C.ORANGE, 'add_staff': C.PURPLE}
        titles = {'create': '🎫 Ticket Créé', 'claim': '🙋 Ticket Pris', 'close': '🔒 Ticket Fermé', 'leave': '🚪 Utilisateur Parti', 'add_staff': '➕ Staff Ajouté'}
        e = discord.Embed(title=titles.get(lt, '🎫'), color=colors.get(lt, C.BLURPLE), timestamp=now())
        e.add_field(name="🎫 Ticket", value=f"#{ti.get('id', '?')}", inline=True)
        uid = user.id if hasattr(user, 'id') else user
        e.add_field(name="👤 Utilisateur", value=f"<@{uid}>", inline=True)
        if lt == 'claim' and extra:
            e.add_field(name="🙋 Pris par", value=f"<@{extra}>", inline=True)
        elif lt == 'close' and closer:
            e.add_field(name="🔒 Fermé par", value=closer.mention, inline=True)
        elif lt == 'add_staff' and extra:
            e.add_field(name="➕ Staff ajouté", value=f"<@{extra}>", inline=True)
        if ti.get('answers') and lt in ['create', 'close']:
            at = "\n".join([f"**{q}**: {a[:80]}" for q, a in list(ti['answers'].items())[:5]])
            if at: e.add_field(name="📝 Réponses", value=at[:1024], inline=False)
        if lt == 'close' and ch:
            lines = []
            try:
                async for m in ch.history(limit=200, oldest_first=True):
                    lines.append(f"[{m.created_at.strftime('%H:%M')}] {m.author.name}: {m.content or '[média]'}")
                f = discord.File(io.BytesIO(("\n".join(lines)).encode()), filename=f"ticket-{ti['id']}.txt")
                await lch.send(embed=e, file=f)
                return
            except: pass
        if hasattr(user, 'display_avatar'):
            e.set_thumbnail(url=user.display_avatar.url)
        await lch.send(embed=e)
    except: pass

async def create_ticket(i, pid, ans=None):
    ch = None
    try:
        c = await cfg(i.guild.id)
        pnl = c.get('ticket_panels', {}).get(pid, {})
        cat = i.guild.get_channel(pnl.get('category', 0))
        staff = i.guild.get_role(c.get('ticket_staff', 0))
        mx = pnl.get('max', 1)
        if not cat: return None, "❌ Catégorie non configurée"
        if await count_user_tickets(i.guild, i.user.id, pid) >= mx:
            return None, f"❌ Max {mx} ticket(s)"
        ow = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True)
        }
        if staff:
            ow[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if i.guild.owner:
            ow[i.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
        ch = await i.guild.create_text_channel(f"ticket-{i.user.name}"[:50], category=cat, overwrites=ow)
        aj = json.dumps(ans or {}, ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO tickets(guild_id, channel_id, user_id, panel_id, claimed_by, status, answers) VALUES(?,?,?,?,0,"open",?)',
                (i.guild.id, ch.id, i.user.id, pid, aj))
            await db.commit()
            async with db.execute('SELECT id FROM tickets WHERE channel_id=?', (ch.id,)) as cur:
                row = await cur.fetchone()
                tid = row[0] if row else 0
        emb = discord.Embed(title="🎫 Nouveau Ticket", color=C.BLURPLE, timestamp=now())
        emb.add_field(name="👤 Créé par", value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
        emb.add_field(name="🎫 ID", value=f"#{tid}", inline=True)
        emb.set_thumbnail(url=i.user.display_avatar.url)
        if ans:
            for t, a in ans.items():
                emb.add_field(name=f"📝 {t}", value=a[:1024], inline=False)
        emb.set_footer(text="Un staff va prendre en charge")
        mention = i.user.mention
        if staff: mention += f" {staff.mention}"
        await ch.send(content=mention, embed=emb, view=TicketControlView())
        await send_ticket_log(i.guild, 'create', i.user, {'id': tid, 'answers': ans or {}})
        return ch, None
    except Exception as ex:
        if ch:
            try: await ch.delete()
            except: pass
        return None, f"❌ {ex}"

class TicketQuestionnaireModal(Modal):
    def __init__(self, pid, qs):
        super().__init__(title="📝 Créer un ticket")
        self.pid = pid
        self.qs = qs
        for i, q in enumerate(qs[:5]):
            self.add_item(TextInput(
                label=q.get('title', f'Q{i+1}')[:45],
                placeholder=q.get('question', '')[:100],
                style=discord.TextStyle.paragraph if len(q.get('question', '')) > 50 else discord.TextStyle.short,
                required=True,
                max_length=500
            ))
    
    async def on_submit(self, i):
        try:
            ans = {self.qs[j].get('title', f'Q{j+1}'): ch.value for j, ch in enumerate(self.children) if j < len(self.qs)}
            await i.response.defer(ephemeral=True)
            ch, err = await create_ticket(i, self.pid, ans)
            await i.followup.send(err if err else f"✅ Ticket créé: {ch.mention}", ephemeral=True)
        except Exception as ex:
            try: await i.followup.send(f"❌ {ex}", ephemeral=True)
            except: pass

class TicketCreateButton(Button):
    def __init__(self, pid):
        super().__init__(label="📩 Créer un ticket", style=discord.ButtonStyle.success, custom_id=f"ticket_create_{pid}")
        self.pid = pid
    
    async def callback(self, i):
        try:
            c = await cfg(i.guild.id)
            pnl = c.get('ticket_panels', {}).get(self.pid, {})
            if not pnl:
                return await i.response.send_message("❌ Panel introuvable", ephemeral=True)
            qs = pnl.get('questions', [])
            mx = pnl.get('max', 1)
            if await count_user_tickets(i.guild, i.user.id, self.pid) >= mx:
                return await i.response.send_message(f"❌ Max {mx} ticket(s)", ephemeral=True)
            if qs:
                await i.response.send_modal(TicketQuestionnaireModal(self.pid, qs))
            else:
                await i.response.defer(ephemeral=True)
                ch, err = await create_ticket(i, self.pid)
                await i.followup.send(err if err else f"✅ Ticket créé: {ch.mention}", ephemeral=True)
        except: pass

class TicketCreateView(View):
    def __init__(self, pid):
        super().__init__(timeout=None)
        self.add_item(TicketCreateButton(pid))

class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🙋 Prendre en charge", style=discord.ButtonStyle.success, custom_id="ticket_ctrl_claim")
    async def claim(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            if i.user.id == tk['user']:
                return await i.response.send_message("❌ Vous ne pouvez pas prendre votre propre ticket", ephemeral=True)
            is_s = sr and sr in i.user.roles
            is_o = i.user.id == i.guild.owner_id
            is_a = i.user.guild_permissions.administrator
            if not (is_s or is_o or is_a):
                return await i.response.send_message("❌ Réservé au staff", ephemeral=True)
            tu = i.guild.get_member(tk['user'])
            ow = {
                i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True),
                i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            }
            if tu:
                ow[tu] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
            if i.guild.owner and i.guild.owner != i.user:
                ow[i.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
            if sr:
                ow[sr] = discord.PermissionOverwrite(view_channel=False)
            await i.channel.edit(overwrites=ow)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (i.user.id, i.channel.id))
                await db.commit()
            await i.response.send_message(f"✅ **{i.user.display_name}** prend ce ticket en charge\n\n*Les autres staffs ne peuvent plus voir ce ticket.*")
            btn.disabled = True
            btn.label = f"Pris par {i.user.display_name}"
            btn.style = discord.ButtonStyle.secondary
            await i.message.edit(view=self)
            await send_ticket_log(i.guild, 'claim', tk['user'], tk, extra=i.user.id)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="➕ Ajouter Staff", style=discord.ButtonStyle.primary, custom_id="ticket_ctrl_add")
    async def add_staff(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            if not tk['claimed']:
                return await i.response.send_message("❌ Le ticket doit d'abord être pris en charge", ephemeral=True)
            is_o = i.user.id == i.guild.owner_id
            is_c = i.user.id == tk['claimed']
            is_a = i.user.guild_permissions.administrator
            if not (is_c or is_o or is_a):
                return await i.response.send_message("❌ Seul le staff en charge peut ajouter quelqu'un", ephemeral=True)
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            if not sr:
                return await i.response.send_message("❌ Aucun rôle staff configuré", ephemeral=True)
            staffs = [m for m in sr.members if m.id != tk['claimed'] and m.id != tk['user']][:25]
            if not staffs:
                return await i.response.send_message("❌ Aucun autre staff disponible", ephemeral=True)
            opts = [discord.SelectOption(label=f"@{m.display_name}"[:25], value=str(m.id)) for m in staffs]
            await i.response.send_message("👥 Choisir un staff:", view=AddStaffView(opts, i.channel.id), ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="ticket_ctrl_close")
    async def close(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            is_o = i.user.id == i.guild.owner_id
            is_a = i.user.guild_permissions.administrator
            is_c = i.user.id == tk['claimed']
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            is_s = sr and sr in i.user.roles
            if tk['claimed']:
                if not (is_c or is_o or is_a):
                    return await i.response.send_message("❌ Seul le staff en charge ou un admin peut fermer", ephemeral=True)
            else:
                if not (is_s or is_o or is_a):
                    return await i.response.send_message("❌ Seul le staff peut fermer", ephemeral=True)
            tu = i.guild.get_member(tk['user'])
            await send_ticket_log(i.guild, 'close', tu or tk['user'], tk, closer=i.user, ch=i.channel)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (i.channel.id,))
                await db.commit()
            await i.response.send_message("🔒 Fermeture dans 3 secondes...")
            await asyncio.sleep(3)
            await i.channel.delete()
        except: pass

class AddStaffView(View):
    def __init__(self, opts, chid):
        super().__init__(timeout=60)
        self.add_item(AddStaffSelect(opts, chid))

class AddStaffSelect(Select):
    def __init__(self, opts, chid):
        super().__init__(placeholder="Choisir un staff...", options=opts)
        self.chid = chid
    
    async def callback(self, i):
        try:
            st = i.guild.get_member(int(self.values[0]))
            ch = i.guild.get_channel(self.chid)
            if st and ch:
                await ch.set_permissions(st, view_channel=True, send_messages=True, read_message_history=True)
                await i.response.send_message(f"✅ {st.mention} ajouté au ticket!", ephemeral=True)
                await ch.send(f"➕ **{st.display_name}** a été ajouté par {i.user.mention}")
                tk = await get_ticket(self.chid)
                if tk:
                    await send_ticket_log(i.guild, 'add_staff', tk['user'], tk, extra=st.id)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════

PROTS = [
    ("anti_link", "🔗", "Anti-Liens"),
    ("anti_invite", "🎟️", "Anti-Invite"),
    ("anti_image", "🖼️", "Anti-Images"),
    ("anti_phishing", "🎣", "Anti-Phishing"),
    ("anti_scam", "🚨", "Anti-Scam"),
    ("anti_spam", "📨", "Anti-Spam"),
    ("anti_caps", "🔠", "Anti-Caps"),
    ("anti_badwords", "🤬", "Anti-Insultes"),
    ("anti_newaccount", "👶", "Anti-NewAccount")
]

class MainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def interaction_check(self, i):
        return i.user.id == self.u.id
    
    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"**{self.g.name}**\n👥 {self.g.member_count} membres"
        if self.g.icon:
            e.set_thumbnail(url=self.g.icon.url)
        return e
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Modération", emoji="🔨", style=discord.ButtonStyle.primary, row=0)
    async def moderation(self, i, b):
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Commandes", emoji="⚡", style=discord.ButtonStyle.primary, row=0)
    async def commands(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def immune(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Config Salon", emoji="📺", style=discord.ButtonStyle.secondary, row=1)
    async def chan(self, i, b):
        v = ChanPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.success, row=1)
    async def tickets(self, i, b):
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Publicité", emoji="📢", style=discord.ButtonStyle.success, row=2)
    async def ads(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Statistiques", emoji="📊", style=discord.ButtonStyle.success, row=2)
    async def stats(self, i, b):
        v = StatPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL (REFAIT PROPREMENT)
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        lines = []
        for key, emoji, name in PROTS:
            status = "✅" if c.get(key) else "❌"
            log_ch = self.g.get_channel(c.get(f'log_{key}', 0))
            log_txt = f"→ {log_ch.mention}" if log_ch else ""
            lines.append(f"{emoji} **{name}**: {status} {log_txt}")
        e.description = "\n".join(lines)
        return e
    
    @discord.ui.select(
        placeholder="🛡️ Sélectionner une protection...",
        options=[discord.SelectOption(label=nm, value=k, emoji=em) for k, em, nm in PROTS]
    )
    async def sel(self, i, s):
        prot = next(p for p in PROTS if p[0] == s.values[0])
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ProtDetail(View):
    def __init__(self, u, g, prot):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.prot = prot
        self.key = prot[0]
    
    async def embed(self):
        c = await cfg(self.g.id)
        on = bool(c.get(self.key))
        e = discord.Embed(
            title=f"{self.prot[1]} {self.prot[2]}",
            color=C.GREEN if on else C.RED
        )
        e.add_field(name="🔘 État", value="✅ ACTIVÉ" if on else "❌ DÉSACTIVÉ", inline=False)
        
        # Configs spécifiques
        if self.key == "anti_link":
            wl = c.get('link_whitelist', [])
            e.add_field(name="🌐 Whitelist domaines", value=f"`{', '.join(wl[:15])}`" if wl else "*Aucun domaine*", inline=False)
            chs = c.get('link_allowed_channels', [])
            ch_txt = ", ".join([f"<#{x}>" for x in chs[:10]]) if chs else "*Aucun salon*"
            e.add_field(name="📍 Salons autorisés", value=ch_txt, inline=False)
        
        elif self.key == "anti_image":
            items = c.get('image_allowed', [])
            fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy']
            fmt_txt = " ".join([f"{'✅' if f in items else '❌'} `{f}`" for f in fmts])
            e.add_field(name="📁 Formats autorisés", value=fmt_txt, inline=False)
        
        elif self.key == "anti_badwords":
            words = c.get('badwords_list', [])
            if words:
                # Afficher tous les mots, ou limiter avec compteur
                if len(words) <= 30:
                    words_txt = ", ".join([f"`{w}`" for w in words])
                else:
                    words_txt = ", ".join([f"`{w}`" for w in words[:30]]) + f"\n*... et {len(words) - 30} autres*"
                e.add_field(name=f"🚫 Mots interdits ({len(words)})", value=words_txt[:1024], inline=False)
            else:
                e.add_field(name="🚫 Mots interdits", value="*Aucun mot configuré*", inline=False)
        
        elif self.key == "anti_spam":
            e.add_field(name="📊 Max messages", value=str(c.get('spam_max', 5)), inline=True)
            e.add_field(name="⏱️ Intervalle (sec)", value=str(c.get('spam_interval', 5)), inline=True)
            e.add_field(name="⚡ Action", value=c.get('spam_action', 'mute').upper(), inline=True)
        
        elif self.key == "anti_caps":
            e.add_field(name="📊 Pourcentage max", value=f"{c.get('caps_percent', 70)}%", inline=True)
        
        elif self.key == "anti_newaccount":
            e.add_field(name="📅 Jours minimum", value=str(c.get('newaccount_days', 7)), inline=True)
        
        elif self.key in ["anti_phishing", "anti_scam"]:
            ak = 'phishing_action' if self.key == "anti_phishing" else 'scam_action'
            e.add_field(name="⚡ Action", value=c.get(ak, 'ban' if 'phishing' in ak else 'mute').upper(), inline=True)
        
        # Salon de log
        log_ch = self.g.get_channel(c.get(f'log_{self.key}', 0))
        e.add_field(name="📜 Salon de log", value=log_ch.mention if log_ch else "❌ Non configuré", inline=False)
        
        return e
    
    @discord.ui.button(label="🔄 ON/OFF", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        c = await cfg(self.g.id)
        await db_set(self.g.id, self.key, 0 if c.get(self.key) else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="⚙️ Configurer", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        if self.key == "anti_image":
            v = ImageConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_badwords":
            v = BadwordsConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_link":
            v = LinkConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key in ["anti_spam", "anti_caps", "anti_newaccount"]:
            await i.response.send_modal(NumberConfigModal(self.g, self.u, self.key))
        elif self.key in ["anti_phishing", "anti_scam"]:
            v = ActionConfigPanel(self.u, self.g, self.key)
            await i.response.edit_message(embed=await v.embed(), view=v)
        else:
            await i.response.send_message("ℹ️ Pas de configuration supplémentaire", ephemeral=True)
    
    @discord.ui.button(label="📜 Définir Log", style=discord.ButtonStyle.secondary, row=0)
    async def set_log(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="❌ Aucun log", value="0", emoji="🚫"))
        v = LogSelectView(self.u, self.g, opts, self.key, self.prot)
        await i.response.edit_message(embed=discord.Embed(title="📜 Choisir le salon de log", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LogSelectView(View):
    def __init__(self, u, g, opts, key, prot):
        super().__init__(timeout=120)
        self.add_item(LogSelect(u, g, opts, key, prot))

class LogSelect(Select):
    def __init__(self, u, g, opts, key, prot):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
        self.prot = prot
    
    async def callback(self, i):
        await db_set(i.guild.id, f'log_{self.key}', int(self.values[0]))
        v = ProtDetail(self.u, self.g, self.prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🖼️ ANTI-IMAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ImageConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy']
        e = discord.Embed(title="🖼️ Formats autorisés", color=C.BLUE)
        lines = []
        for f in fmts:
            status = "✅ Autorisé" if f in items else "❌ Bloqué"
            lines.append(f"`{f.upper()}` : {status}")
        e.description = "\n".join(lines)
        e.set_footer(text="Cliquez sur un format pour le toggle")
        return e
    
    @discord.ui.select(
        placeholder="Sélectionner un format à toggle...",
        options=[
            discord.SelectOption(label="PNG", value="png", emoji="🖼️"),
            discord.SelectOption(label="JPG", value="jpg", emoji="🖼️"),
            discord.SelectOption(label="JPEG", value="jpeg", emoji="🖼️"),
            discord.SelectOption(label="GIF (fichier)", value="gif", emoji="🎞️"),
            discord.SelectOption(label="WEBP", value="webp", emoji="🖼️"),
            discord.SelectOption(label="Tenor", value="tenor", emoji="🎬"),
            discord.SelectOption(label="Giphy", value="giphy", emoji="🎬")
        ]
    )
    async def toggle_format(self, i, s):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmt = s.values[0]
        if fmt in items:
            items.remove(fmt)
        else:
            items.append(fmt)
        await db_set(self.g.id, 'image_allowed', items)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="✅ Tout autoriser", style=discord.ButtonStyle.success, row=1)
    async def allow_all(self, i, b):
        await db_set(self.g.id, 'image_allowed', ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy'])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="❌ Tout bloquer", style=discord.ButtonStyle.danger, row=1)
    async def block_all(self, i, b):
        await db_set(self.g.id, 'image_allowed', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_image")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🤬 ANTI-BADWORDS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class BadwordsConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        words = c.get('badwords_list', [])
        e = discord.Embed(title="🤬 Mots interdits", color=C.BLUE)
        if words:
            # Afficher tous les mots avec pagination si nécessaire
            all_words = ", ".join([f"`{w}`" for w in words])
            if len(all_words) > 4000:
                all_words = all_words[:4000] + "..."
            e.description = f"**{len(words)} mot(s) configuré(s):**\n\n{all_words}"
        else:
            e.description = "*Aucun mot interdit configuré*\n\nCliquez sur ➕ Ajouter pour ajouter des mots."
        return e
    
    @discord.ui.button(label="➕ Ajouter des mots", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddBadwordsModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer tout", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, i, b):
        await db_set(self.g.id, 'badwords_list', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_badwords")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddBadwordsModal(Modal, title="➕ Ajouter des mots interdits"):
    words = TextInput(
        label="Mots (séparés par des virgules)",
        placeholder="mot1, mot2, mot3, expression interdite, ...",
        style=discord.TextStyle.paragraph,
        max_length=4000
    )
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('badwords_list', [])
        new = [x.strip().lower() for x in self.words.value.split(',') if x.strip()]
        added = 0
        for w in new:
            if w and w not in items:
                items.append(w)
                added += 1
        await db_set(self.g.id, 'badwords_list', items)
        v = BadwordsConfigPanel(self.u, self.g)
        await i.response.edit_message(content=f"✅ {added} mot(s) ajouté(s)!", embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔗 ANTI-LINK CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔗 Configuration Anti-Liens", color=C.BLUE)
        
        wl = c.get('link_whitelist', [])
        e.add_field(
            name=f"🌐 Whitelist domaines ({len(wl)})",
            value=f"`{', '.join(wl)}`" if wl else "*Aucun domaine autorisé*",
            inline=False
        )
        
        chs = c.get('link_allowed_channels', [])
        ch_txt = ", ".join([f"<#{x}>" for x in chs]) if chs else "*Aucun salon*"
        e.add_field(
            name=f"📍 Salons autorisés ({len(chs)})",
            value=ch_txt,
            inline=False
        )
        
        return e
    
    @discord.ui.button(label="➕ Ajouter domaines", style=discord.ButtonStyle.success, row=0)
    async def add_domain(self, i, b):
        await i.response.send_modal(AddDomainModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Vider whitelist", style=discord.ButtonStyle.danger, row=0)
    async def clear_wl(self, i, b):
        await db_set(self.g.id, 'link_whitelist', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="➕ Ajouter salon", style=discord.ButtonStyle.primary, row=1)
    async def add_chan(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = LinkChanSelectView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📍 Choisir un salon à autoriser", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="🗑️ Vider salons", style=discord.ButtonStyle.danger, row=1)
    async def clear_chs(self, i, b):
        await db_set(self.g.id, 'link_allowed_channels', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_link")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddDomainModal(Modal, title="➕ Ajouter des domaines"):
    doms = TextInput(
        label="Domaines (séparés par des virgules)",
        placeholder="youtube.com, twitter.com, discord.com",
        style=discord.TextStyle.paragraph,
        max_length=2000
    )
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('link_whitelist', [])
        new = [x.strip().lower() for x in self.doms.value.split(',') if x.strip()]
        added = 0
        for d in new:
            if d and d not in items:
                items.append(d)
                added += 1
        await db_set(self.g.id, 'link_whitelist', items)
        v = LinkConfigPanel(self.u, self.g)
        await i.response.edit_message(content=f"✅ {added} domaine(s) ajouté(s)!", embed=await v.embed(), view=v)

class LinkChanSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(LinkChanSelect(u, g, opts))

class LinkChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        c = await cfg(i.guild.id)
        chs = c.get('link_allowed_channels', [])
        chid = int(self.values[0])
        if chid not in chs:
            chs.append(chid)
            await db_set(i.guild.id, 'link_allowed_channels', chs)
        v = LinkConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚙️ NUMBER CONFIG MODAL
# ═══════════════════════════════════════════════════════════════════════════════

class NumberConfigModal(Modal, title="⚙️ Configuration"):
    val = TextInput(label="Valeur", placeholder="5", max_length=3)
    
    def __init__(self, g, u, key):
        super().__init__()
        self.g = g
        self.u = u
        self.key = key
        if key == "anti_spam":
            self.val.label = "Nombre max de messages"
            self.val.placeholder = "5"
        elif key == "anti_caps":
            self.val.label = "Pourcentage max de majuscules"
            self.val.placeholder = "70"
        elif key == "anti_newaccount":
            self.val.label = "Âge minimum du compte (jours)"
            self.val.placeholder = "7"
    
    async def on_submit(self, i):
        v = int(self.val.value) if self.val.value.isdigit() else 5
        if self.key == "anti_spam":
            await db_set(self.g.id, 'spam_max', max(1, min(20, v)))
        elif self.key == "anti_caps":
            await db_set(self.g.id, 'caps_percent', max(10, min(100, v)))
        elif self.key == "anti_newaccount":
            await db_set(self.g.id, 'newaccount_days', max(1, min(365, v)))
        prot = next(p for p in PROTS if p[0] == self.key)
        vw = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await vw.embed(), view=vw)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚡ ACTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ActionConfigPanel(View):
    def __init__(self, u, g, key):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.key = key
    
    async def embed(self):
        c = await cfg(self.g.id)
        ak = 'phishing_action' if self.key == "anti_phishing" else 'scam_action'
        current = c.get(ak, 'ban' if 'phishing' in ak else 'mute')
        e = discord.Embed(title=f"⚡ Action pour {self.key.replace('anti_', '').title()}", color=C.BLUE)
        e.description = f"**Action actuelle:** `{current.upper()}`\n\nChoisissez l'action à effectuer:"
        return e
    
    @discord.ui.button(label="🔇 Mute", style=discord.ButtonStyle.primary, row=0)
    async def mute(self, i, b):
        await self._set(i, 'mute')
    
    @discord.ui.button(label="👢 Kick", style=discord.ButtonStyle.secondary, row=0)
    async def kick(self, i, b):
        await self._set(i, 'kick')
    
    @discord.ui.button(label="🔨 Ban", style=discord.ButtonStyle.danger, row=0)
    async def ban(self, i, b):
        await self._set(i, 'ban')
    
    async def _set(self, i, act):
        ak = 'phishing_action' if self.key == "anti_phishing" else 'scam_action'
        await db_set(self.g.id, ak, act)
        prot = next(p for p in PROTS if p[0] == self.key)
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == self.key)
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔨 MODÉRATION PANEL
# ═══════════════════════════════════════════════════════════════════════════════

async def send_mod_log(guild, action, mod, target, reason=None, duration=None, extra=None):
    """Envoie un log de modération"""
    try:
        c = await cfg(guild.id)
        log_ch = guild.get_channel(c.get('mod_log_channel', 0))
        if not log_ch:
            return
        
        colors = {'warn': C.YELLOW, 'unwarn': C.GREEN, 'mute': C.ORANGE, 'unmute': C.GREEN, 'infractions': C.BLUE}
        emojis = {'warn': '⚠️', 'unwarn': '✅', 'mute': '🔇', 'unmute': '🔊', 'infractions': '📋'}
        titles = {'warn': 'Avertissement', 'unwarn': 'Warn supprimé', 'mute': 'Mute', 'unmute': 'Unmute', 'infractions': 'Consultation infractions'}
        
        e = discord.Embed(
            title=f"{emojis.get(action, '🔨')} {titles.get(action, action.upper())}",
            color=colors.get(action, C.ORANGE),
            timestamp=now()
        )
        e.add_field(name="👮 Modérateur", value=f"{mod.mention}\n`{mod.id}`", inline=True)
        e.add_field(name="👤 Membre", value=f"{target.mention}\n`{target.id}`", inline=True)
        
        if duration:
            e.add_field(name="⏱️ Durée", value=duration, inline=True)
        if reason:
            e.add_field(name="📝 Raison", value=reason[:1024], inline=False)
        if extra:
            e.add_field(name="ℹ️ Info", value=extra, inline=False)
        
        e.set_thumbnail(url=target.display_avatar.url)
        await log_ch.send(embed=e)
    except Exception as ex:
        print(f"[MOD LOG ERROR] {ex}")

class ModerationPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔨 Modération", color=C.ORANGE)
        e.description = "Configurez les rôles et logs pour les commandes de modération."
        
        # Salon logs
        log_ch = self.g.get_channel(c.get('mod_log_channel', 0))
        e.add_field(
            name="📜 Salon Logs",
            value=log_ch.mention if log_ch else "❌ Non configuré",
            inline=False
        )
        
        # Warn
        warn_role = self.g.get_role(c.get('mod_warn_role', 0))
        e.add_field(
            name="⚠️ /warn & /unwarn",
            value=f"Rôle: {warn_role.mention if warn_role else '❌ Non configuré'}",
            inline=True
        )
        
        # Mute
        mute_role = self.g.get_role(c.get('mod_mute_role', 0))
        e.add_field(
            name="🔇 /mute & /unmute",
            value=f"Rôle: {mute_role.mention if mute_role else '❌ Non configuré'}",
            inline=True
        )
        
        # Infractions
        inf_role = self.g.get_role(c.get('mod_infractions_role', 0))
        e.add_field(
            name="📋 /infractions",
            value=f"Rôle: {inf_role.mention if inf_role else '❌ Non configuré'}",
            inline=True
        )
        
        e.set_footer(text="Les admins et le owner ont toujours accès à toutes les commandes")
        return e
    
    @discord.ui.button(label="📜 Salon Logs", style=discord.ButtonStyle.success, row=0)
    async def set_logs(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="❌ Aucun log", value="0"))
        v = ModLogSelectView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📜 Salon des logs modération", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="⚠️ Rôle /warn", style=discord.ButtonStyle.primary, row=1)
    async def set_warn(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Aucun rôle", value="0"))
        v = ModRoleSelectView(self.u, self.g, opts, 'mod_warn_role')
        await i.response.edit_message(embed=discord.Embed(title="⚠️ Rôle pour /warn & /unwarn", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="🔇 Rôle /mute", style=discord.ButtonStyle.primary, row=1)
    async def set_mute(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Aucun rôle", value="0"))
        v = ModRoleSelectView(self.u, self.g, opts, 'mod_mute_role')
        await i.response.edit_message(embed=discord.Embed(title="🔇 Rôle pour /mute & /unmute", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="📋 Rôle /infractions", style=discord.ButtonStyle.primary, row=1)
    async def set_inf(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Aucun rôle", value="0"))
        v = ModRoleSelectView(self.u, self.g, opts, 'mod_infractions_role')
        await i.response.edit_message(embed=discord.Embed(title="📋 Rôle pour /infractions", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ModLogSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ModLogSelect(u, g, opts))

class ModLogSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'mod_log_channel', int(self.values[0]))
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ModRoleSelectView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(ModRoleSelect(u, g, opts, key))

class ModRoleSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👑 IMMUNITÉS (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

class ImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,)) as c:
                rids = [r[0] for r in await c.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (self.g.id,)) as c:
                uids = [r[0] for r in await c.fetchall()]
        e = discord.Embed(title="👑 Immunités", color=C.YELLOW)
        e.add_field(name=f"🎭 Rôles immunisés ({len(rids)})", value=", ".join([f"<@&{r}>" for r in rids]) or "*Aucun*", inline=False)
        e.add_field(name=f"👤 Utilisateurs immunisés ({len(uids)})", value=", ".join([f"<@{u}>" for u in uids]) or "*Aucun*", inline=False)
        return e
    
    @discord.ui.button(label="➕ Ajouter rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        await i.response.edit_message(embed=discord.Embed(title="👑 Ajouter un rôle immunisé", color=C.YELLOW), view=ImmuneRoleView(self.u, self.g, opts))
    
    @discord.ui.button(label="➕ Ajouter user", style=discord.ButtonStyle.primary, row=0)
    async def add_user(self, i, b):
        await i.response.send_modal(AddImmuneUserModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Tout supprimer", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM immune_roles WHERE guild_id=?', (self.g.id,))
            await db.execute('DELETE FROM immune_users WHERE guild_id=?', (self.g.id,))
            await db.commit()
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ImmuneRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ImmuneRoleSelect(u, g, opts))

class ImmuneRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES(?,?)', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddImmuneUserModal(Modal, title="➕ Ajouter un utilisateur immunisé"):
    uid = TextInput(label="ID de l'utilisateur", placeholder="123456789012345678")
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            user_id = int(self.uid.value)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT OR IGNORE INTO immune_users VALUES(?,?)', (self.g.id, user_id))
                await db.commit()
        except: pass
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚡ COMMANDES PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class CommandsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="⚡ Commandes Personnalisées", color=C.PURPLE)
        e.description = "Configurez les commandes spéciales du serveur."
        
        # RellSeas
        rellseas_user = self.g.get_member(c.get('rellseas_user', 0))
        rellseas_role = self.g.get_role(c.get('rellseas_role', 0))
        e.add_field(
            name="🎭 RellSeas",
            value=f"👤 {rellseas_user.mention if rellseas_user else '❌'}\n🎭 {rellseas_role.mention if rellseas_role else '❌'}",
            inline=True
        )
        
        # Suggestions
        sugg_role = self.g.get_role(c.get('suggestion_role', 0))
        sugg_ch = self.g.get_channel(c.get('suggestion_channel', 0))
        e.add_field(
            name="💡 Suggestions",
            value=f"🎭 {sugg_role.mention if sugg_role else 'Tous'}\n📍 {sugg_ch.mention if sugg_ch else '❌'}",
            inline=True
        )
        
        # Trade
        trade_role = self.g.get_role(c.get('trade_role', 0))
        trade_ch = self.g.get_channel(c.get('trade_channel', 0))
        trade_cd = c.get('trade_cooldown', 1)
        trade_unit = c.get('trade_cooldown_unit', 'heures')
        e.add_field(
            name="🔄 Trade",
            value=f"🎭 {trade_role.mention if trade_role else 'Tous'}\n📍 {trade_ch.mention if trade_ch else '❌'}\n⏱️ {trade_cd} {trade_unit}",
            inline=True
        )
        
        return e
    
    @discord.ui.button(label="🎭 RellSeas", style=discord.ButtonStyle.primary, row=0)
    async def rellseas(self, i, b):
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="💡 Suggestions", style=discord.ButtonStyle.primary, row=0)
    async def suggestions(self, i, b):
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🔄 Trade", style=discord.ButtonStyle.primary, row=0)
    async def trade(self, i, b):
        v = TradePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎭 RELLSEAS
# ═══════════════════════════════════════════════════════════════════════════════

class RellSeasPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎭 Configuration RellSeas", color=C.PURPLE)
        
        rellseas_user = self.g.get_member(c.get('rellseas_user', 0))
        rellseas_role = self.g.get_role(c.get('rellseas_role', 0))
        warn_ch = self.g.get_channel(c.get('rellseas_warn_channel', 0))
        log_ch = self.g.get_channel(c.get('rellseas_log_channel', 0))
        
        e.description = "L'utilisateur autorisé reçoit **automatiquement** le rôle Realsy et peut le donner à d'autres."
        
        e.add_field(name="👤 Utilisateur autorisé", value=rellseas_user.mention if rellseas_user else "❌ Non configuré", inline=False)
        e.add_field(name="🎭 Rôle Realsy", value=rellseas_role.mention if rellseas_role else "❌ Non configuré", inline=False)
        e.add_field(name="⚠️ Salon warn", value=warn_ch.mention if warn_ch else "❌", inline=True)
        e.add_field(name="📜 Salon logs", value=log_ch.mention if log_ch else "❌", inline=True)
        
        e.set_footer(text="⏱️ 7 jours inactif = Warn | 14 jours = Rôle retiré")
        return e
    
    @discord.ui.button(label="👤 Utilisateur", style=discord.ButtonStyle.primary, row=0)
    async def set_user(self, i, b):
        await i.response.send_modal(RellSeasUserModal(self.g, self.u))
    
    @discord.ui.button(label="🎭 Rôle Realsy", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = RellSeasRoleView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Choisir le rôle Realsy", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="⚠️ Salon Warn", style=discord.ButtonStyle.secondary, row=1)
    async def set_warn_ch(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = RellSeasChanView(self.u, self.g, opts, 'rellseas_warn_channel')
        await i.response.edit_message(embed=discord.Embed(title="⚠️ Salon des warns", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📜 Salon Logs", style=discord.ButtonStyle.secondary, row=1)
    async def set_log_ch(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = RellSeasChanView(self.u, self.g, opts, 'rellseas_log_channel')
        await i.response.edit_message(embed=discord.Embed(title="📜 Salon des logs", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasUserModal(Modal, title="👤 Utilisateur RellSeas"):
    uid = TextInput(label="ID de l'utilisateur", placeholder="123456789012345678")
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            user_id = int(self.uid.value)
            await db_set(self.g.id, 'rellseas_user', user_id)
            
            # Donner automatiquement le rôle à l'utilisateur autorisé
            c = await cfg(self.g.id)
            role = self.g.get_role(c.get('rellseas_role', 0))
            member = self.g.get_member(user_id)
            
            if role and member and role not in member.roles:
                try:
                    await member.add_roles(role, reason="RellSeas - Utilisateur autorisé")
                    # Enregistrer dans le tracking
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('''INSERT OR REPLACE INTO realsy_tracking 
                            (guild_id, user_id, last_activity, warn_count) VALUES (?, ?, ?, 0)''',
                            (self.g.id, user_id, now().isoformat()))
                        await db.commit()
                except:
                    pass
        except:
            pass
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(RellSeasRoleSelect(u, g, opts))

class RellSeasRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'rellseas_role', int(self.values[0]))
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasChanView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(RellSeasChanSelect(u, g, opts, key))

class RellSeasChanSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           💡 SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class SuggestionPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="💡 Configuration Suggestions", color=C.PURPLE)
        
        sugg_role = self.g.get_role(c.get('suggestion_role', 0))
        sugg_ch = self.g.get_channel(c.get('suggestion_channel', 0))
        sugg_cd = c.get('suggestion_cooldown', 1)
        sugg_unit = c.get('suggestion_cooldown_unit', 'jours')
        
        e.add_field(name="🎭 Rôle autorisé", value=sugg_role.mention if sugg_role else "❌ Non configuré (tout le monde)", inline=False)
        e.add_field(name="📍 Salon des suggestions", value=sugg_ch.mention if sugg_ch else "❌ Non configuré", inline=False)
        e.add_field(name="⏱️ Cooldown", value=f"{sugg_cd} {sugg_unit}", inline=False)
        
        e.set_footer(text="Commande: /suggestion")
        return e
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Tout le monde", value="0"))
        v = SuggRoleView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Rôle autorisé", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = SuggChanView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon des suggestions", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="⏱️ Cooldown", style=discord.ButtonStyle.secondary, row=1)
    async def set_cooldown(self, i, b):
        await i.response.send_modal(SuggCooldownModal(self.g, self.u))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SuggRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(SuggRoleSelect(u, g, opts))

class SuggRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'suggestion_role', int(self.values[0]))
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SuggChanView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(SuggChanSelect(u, g, opts))

class SuggChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'suggestion_channel', int(self.values[0]))
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SuggCooldownModal(Modal, title="⏱️ Cooldown Suggestions"):
    duree = TextInput(label="Durée (nombre)", placeholder="1", default="1", max_length=3)
    unite = TextInput(label="Unité (jours ou semaines)", placeholder="jours", default="jours", max_length=10)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            cd = max(1, int(self.duree.value))
            unit = self.unite.value.lower()
            if unit not in ['jours', 'semaines']:
                unit = 'jours'
            await db_set(self.g.id, 'suggestion_cooldown', cd)
            await db_set(self.g.id, 'suggestion_cooldown_unit', unit)
        except: pass
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔄 TRADE PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class TradePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔄 Configuration Trade", color=C.PURPLE)
        
        trade_role = self.g.get_role(c.get('trade_role', 0))
        trade_ch = self.g.get_channel(c.get('trade_channel', 0))
        trade_cd = c.get('trade_cooldown', 1)
        trade_unit = c.get('trade_cooldown_unit', 'heures')
        
        e.description = "Configurez le système d'échange pour votre serveur.\n\n*Les utilisateurs pourront créer des annonces de trade avec `/trade`*"
        
        e.add_field(name="🎭 Rôle autorisé", value=trade_role.mention if trade_role else "Tout le monde", inline=True)
        e.add_field(name="📍 Salon", value=trade_ch.mention if trade_ch else "❌ Non configuré", inline=True)
        e.add_field(name="⏱️ Cooldown", value=f"{trade_cd} {trade_unit}", inline=True)
        
        e.set_footer(text="Commande: /trade")
        return e
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Tout le monde", value="0"))
        v = TradeRoleView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Rôle autorisé", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = TradeChanView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon des trades", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="⏱️ Cooldown", style=discord.ButtonStyle.primary, row=0)
    async def set_cooldown(self, i, b):
        await i.response.send_modal(TradeCooldownModal(self.g, self.u))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TradeRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TradeRoleSelect(u, g, opts))

class TradeRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'trade_role', int(self.values[0]))
        v = TradePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TradeChanView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TradeChanSelect(u, g, opts))

class TradeChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'trade_channel', int(self.values[0]))
        v = TradePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TradeCooldownModal(Modal, title="⏱️ Cooldown Trade"):
    duree = TextInput(label="Durée (nombre)", placeholder="1", default="1", max_length=3)
    unite = TextInput(label="Unité (secondes/minutes/heures/jours)", placeholder="heures", default="heures", max_length=10)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            cd = max(1, int(self.duree.value))
            unit = self.unite.value.lower()
            if unit not in ['secondes', 'minutes', 'heures', 'jours', 'semaines']:
                unit = 'heures'
            await db_set(self.g.id, 'trade_cooldown', cd)
            await db_set(self.g.id, 'trade_cooldown_unit', unit)
        except:
            pass
        
        v = TradePanel(self.u, self.g)
        e = await v.embed()
        await i.response.edit_message(embed=e, view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 PUBLICITÉ / NOTIFICATIONS SOCIALES
# ═══════════════════════════════════════════════════════════════════════════════

# Cache pour éviter de republier les mêmes posts
posted_content = {}

class AdsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📢 Publicité & Notifications", color=C.PURPLE)
        e.description = "Recevez les dernières publications de vos créateurs préférés!"
        
        # YouTube
        yt_ch = self.g.get_channel(c.get('ads_youtube_channel', 0))
        yt_feeds = c.get('ads_youtube_feeds', [])
        e.add_field(
            name="🔴 YouTube",
            value=f"📍 {yt_ch.mention if yt_ch else '❌'}\n📺 {len(yt_feeds)} chaîne(s)",
            inline=True
        )
        
        # Twitch
        tw_ch = self.g.get_channel(c.get('ads_twitch_channel', 0))
        tw_feeds = c.get('ads_twitch_feeds', [])
        e.add_field(
            name="🟣 Twitch",
            value=f"📍 {tw_ch.mention if tw_ch else '❌'}\n🎮 {len(tw_feeds)} streamer(s)",
            inline=True
        )
        
        # Twitter/X
        x_ch = self.g.get_channel(c.get('ads_twitter_channel', 0))
        x_feeds = c.get('ads_twitter_feeds', [])
        e.add_field(
            name="🐦 Twitter/X",
            value=f"📍 {x_ch.mention if x_ch else '❌'}\n👤 {len(x_feeds)} compte(s)",
            inline=True
        )
        
        # Reddit
        rd_ch = self.g.get_channel(c.get('ads_reddit_channel', 0))
        rd_feeds = c.get('ads_reddit_feeds', [])
        e.add_field(
            name="🟠 Reddit",
            value=f"📍 {rd_ch.mention if rd_ch else '❌'}\n📰 {len(rd_feeds)} subreddit(s)",
            inline=True
        )
        
        # Discord
        dc_ch = self.g.get_channel(c.get('ads_discord_channel', 0))
        dc_feeds = c.get('ads_discord_feeds', [])
        e.add_field(
            name="📡 Discord",
            value=f"📍 {dc_ch.mention if dc_ch else '❌'}\n💬 {len(dc_feeds)} salon(s)",
            inline=True
        )
        
        # RoSocial
        rs_ch = self.g.get_channel(c.get('ads_rosocial_channel', 0))
        rs_feeds = c.get('ads_rosocial_feeds', [])
        e.add_field(
            name="🎮 RoSocial",
            value=f"📍 {rs_ch.mention if rs_ch else '❌'}\n👤 {len(rs_feeds)} profil(s)",
            inline=True
        )
        
        e.set_footer(text="💡 Les notifications sont vérifiées toutes les 5 minutes")
        return e
    
    @discord.ui.button(label="🔴 YouTube", style=discord.ButtonStyle.danger, row=0)
    async def youtube(self, i, b):
        v = AdsYouTubePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🟣 Twitch", style=discord.ButtonStyle.primary, row=0)
    async def twitch(self, i, b):
        v = AdsTwitchPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🐦 Twitter/X", style=discord.ButtonStyle.secondary, row=0)
    async def twitter(self, i, b):
        v = AdsTwitterPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🟠 Reddit", style=discord.ButtonStyle.secondary, row=0)
    async def reddit(self, i, b):
        v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📡 Discord", style=discord.ButtonStyle.primary, row=1)
    async def discord_btn(self, i, b):
        v = AdsDiscordPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🎮 RoSocial", style=discord.ButtonStyle.success, row=1)
    async def rosocial(self, i, b):
        v = AdsRoSocialPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ─────────────────────────────── YOUTUBE ───────────────────────────────

class AdsYouTubePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔴 YouTube - Notifications", color=0xFF0000)
        
        yt_ch = self.g.get_channel(c.get('ads_youtube_channel', 0))
        yt_feeds = c.get('ads_youtube_feeds', [])
        
        e.add_field(name="📍 Salon", value=yt_ch.mention if yt_ch else "❌ Non configuré", inline=False)
        
        if yt_feeds:
            feeds_txt = "\n".join([f"• `{f['name']}` ({f['id'][:15]}...)" for f in yt_feeds[:10]])
            e.add_field(name=f"📺 Chaînes suivies ({len(yt_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="📺 Chaînes suivies", value="*Aucune chaîne configurée*", inline=False)
        
        e.set_footer(text="💡 Utilisez l'ID de chaîne YouTube (ex: UCxxxx)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_youtube_channel', 'youtube')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon YouTube", color=0xFF0000), view=v)
    
    @discord.ui.button(label="➕ Ajouter Chaîne", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsYouTubeAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Chaîne", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_youtube_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucune chaîne à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f['name'][:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_youtube_feeds', 'youtube')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer une chaîne", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsYouTubeAddModal(Modal, title="➕ Ajouter une chaîne YouTube"):
    name = TextInput(label="Nom de la chaîne", placeholder="Ex: MrBeast", max_length=50)
    channel_id = TextInput(label="ID de la chaîne YouTube", placeholder="UCX6OQ3DkcsbYNE6H8uQQuVA", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_youtube_feeds', [])
        
        # Vérifier si déjà ajouté
        if any(f['id'] == self.channel_id.value for f in feeds):
            return await i.response.send_message("❌ Cette chaîne est déjà ajoutée!", ephemeral=True)
        
        feeds.append({'name': self.name.value, 'id': self.channel_id.value})
        await db_set(self.g.id, 'ads_youtube_feeds', feeds)
        
        v = AdsYouTubePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── TWITCH ───────────────────────────────

class AdsTwitchPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🟣 Twitch - Notifications", color=0x9146FF)
        
        tw_ch = self.g.get_channel(c.get('ads_twitch_channel', 0))
        tw_feeds = c.get('ads_twitch_feeds', [])
        
        e.add_field(name="📍 Salon", value=tw_ch.mention if tw_ch else "❌ Non configuré", inline=False)
        
        if tw_feeds:
            feeds_txt = "\n".join([f"• `{f}`" for f in tw_feeds[:10]])
            e.add_field(name=f"🎮 Streamers suivis ({len(tw_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="🎮 Streamers suivis", value="*Aucun streamer configuré*", inline=False)
        
        e.set_footer(text="💡 Utilisez le nom d'utilisateur Twitch (ex: ninja)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_twitch_channel', 'twitch')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon Twitch", color=0x9146FF), view=v)
    
    @discord.ui.button(label="➕ Ajouter Streamer", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsTwitchAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Streamer", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitch_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun streamer à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_twitch_feeds', 'twitch')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un streamer", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsTwitchAddModal(Modal, title="➕ Ajouter un streamer Twitch"):
    username = TextInput(label="Nom d'utilisateur Twitch", placeholder="Ex: ninja", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitch_feeds', [])
        
        username = self.username.value.lower().strip()
        if username in feeds:
            return await i.response.send_message("❌ Ce streamer est déjà ajouté!", ephemeral=True)
        
        feeds.append(username)
        await db_set(self.g.id, 'ads_twitch_feeds', feeds)
        
        v = AdsTwitchPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── REDDIT ───────────────────────────────

class AdsRedditPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🟠 Reddit - Notifications", color=0xFF4500)
        
        rd_ch = self.g.get_channel(c.get('ads_reddit_channel', 0))
        rd_feeds = c.get('ads_reddit_feeds', [])
        
        e.add_field(name="📍 Salon", value=rd_ch.mention if rd_ch else "❌ Non configuré", inline=False)
        
        if rd_feeds:
            feeds_txt = "\n".join([f"• r/{f}" for f in rd_feeds[:10]])
            e.add_field(name=f"📰 Subreddits suivis ({len(rd_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="📰 Subreddits suivis", value="*Aucun subreddit configuré*", inline=False)
        
        e.set_footer(text="💡 Entrez le nom du subreddit sans 'r/' (ex: gaming)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_reddit_channel', 'reddit')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon Reddit", color=0xFF4500), view=v)
    
    @discord.ui.button(label="➕ Ajouter Subreddit", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsRedditAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Subreddit", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_reddit_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun subreddit à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f"r/{f}"[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_reddit_feeds', 'reddit')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un subreddit", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsRedditAddModal(Modal, title="➕ Ajouter un subreddit"):
    subreddit = TextInput(label="Nom du subreddit (sans r/)", placeholder="Ex: gaming", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_reddit_feeds', [])
        
        sub = self.subreddit.value.lower().strip().replace('r/', '')
        if sub in feeds:
            return await i.response.send_message("❌ Ce subreddit est déjà ajouté!", ephemeral=True)
        
        feeds.append(sub)
        await db_set(self.g.id, 'ads_reddit_feeds', feeds)
        
        v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── TWITTER/X ───────────────────────────────

# Liste d'instances Nitter fonctionnelles (fallback)
NITTER_INSTANCES = [
    "nitter.poast.org",
    "xcancel.com", 
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

class AdsTwitterPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🐦 Twitter/X - Notifications", color=0x1DA1F2)
        
        x_ch = self.g.get_channel(c.get('ads_twitter_channel', 0))
        x_feeds = c.get('ads_twitter_feeds', [])
        
        e.add_field(name="📍 Salon", value=x_ch.mention if x_ch else "❌ Non configuré", inline=False)
        
        if x_feeds:
            feeds_txt = "\n".join([f"• @{f}" for f in x_feeds[:10]])
            e.add_field(name=f"👤 Comptes suivis ({len(x_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="👤 Comptes suivis", value="*Aucun compte configuré*", inline=False)
        
        e.set_footer(text="💡 Entrez le nom d'utilisateur sans @ (ex: elonmusk)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_twitter_channel', 'twitter')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon Twitter", color=0x1DA1F2), view=v)
    
    @discord.ui.button(label="➕ Ajouter Compte", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsTwitterAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Compte", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitter_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun compte à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f"@{f}"[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_twitter_feeds', 'twitter')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un compte", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsTwitterAddModal(Modal, title="➕ Ajouter un compte Twitter"):
    username = TextInput(label="Nom d'utilisateur (sans @)", placeholder="Ex: elonmusk", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitter_feeds', [])
        
        username = self.username.value.lower().strip().replace('@', '')
        if username in feeds:
            return await i.response.send_message("❌ Ce compte est déjà ajouté!", ephemeral=True)
        
        feeds.append(username)
        await db_set(self.g.id, 'ads_twitter_feeds', feeds)
        
        v = AdsTwitterPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── DISCORD CHANNELS ───────────────────────────────

class AdsDiscordPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📡 Discord - Suivi de Salons", color=C.BLURPLE)
        
        dc_ch = self.g.get_channel(c.get('ads_discord_channel', 0))
        dc_feeds = c.get('ads_discord_feeds', [])
        
        e.add_field(name="📍 Salon de destination", value=dc_ch.mention if dc_ch else "❌ Non configuré", inline=False)
        
        if dc_feeds:
            feeds_txt = []
            for f in dc_feeds[:10]:
                ch = bot.get_channel(int(f['channel_id']))
                if ch:
                    feeds_txt.append(f"• #{ch.name} ({ch.guild.name[:15]})")
                else:
                    feeds_txt.append(f"• `{f['channel_id']}` (inaccessible)")
            e.add_field(name=f"💬 Salons suivis ({len(dc_feeds)})", value="\n".join(feeds_txt), inline=False)
        else:
            e.add_field(name="💬 Salons suivis", value="*Aucun salon configuré*", inline=False)
        
        e.set_footer(text="⚠️ Le bot doit être présent sur le serveur du salon à suivre")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_discord_channel', 'discord')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon de destination", color=C.BLURPLE), view=v)
    
    @discord.ui.button(label="➕ Ajouter Salon", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsDiscordAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Salon", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_discord_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun salon à supprimer", ephemeral=True)
        opts = []
        for idx, f in enumerate(feeds[:25]):
            ch = bot.get_channel(int(f['channel_id']))
            label = f"#{ch.name}"[:25] if ch else f"ID: {f['channel_id']}"[:25]
            opts.append(discord.SelectOption(label=label, value=str(idx)))
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_discord_feeds', 'discord')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un salon", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsDiscordAddModal(Modal, title="➕ Suivre un salon Discord"):
    channel_id = TextInput(label="ID du salon à suivre", placeholder="Ex: 1234567890123456789", max_length=25)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_discord_feeds', [])
        
        try:
            ch_id = int(self.channel_id.value.strip())
        except:
            return await i.response.send_message("❌ ID invalide!", ephemeral=True)
        
        # Vérifier si le bot a accès au salon
        ch = bot.get_channel(ch_id)
        if not ch:
            return await i.response.send_message("❌ Salon introuvable! Le bot doit être présent sur le serveur.", ephemeral=True)
        
        # Vérifier si déjà ajouté
        if any(f['channel_id'] == str(ch_id) for f in feeds):
            return await i.response.send_message("❌ Ce salon est déjà suivi!", ephemeral=True)
        
        feeds.append({'channel_id': str(ch_id), 'guild_name': ch.guild.name, 'channel_name': ch.name})
        await db_set(self.g.id, 'ads_discord_feeds', feeds)
        
        v = AdsDiscordPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── ROSOCIAL ───────────────────────────────

class AdsRoSocialPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎮 RoSocial - Notifications", color=0x00D4AA)
        
        rs_ch = self.g.get_channel(c.get('ads_rosocial_channel', 0))
        rs_feeds = c.get('ads_rosocial_feeds', [])
        
        e.add_field(name="📍 Salon", value=rs_ch.mention if rs_ch else "❌ Non configuré", inline=False)
        
        if rs_feeds:
            feeds_txt = "\n".join([f"• `{f}`" for f in rs_feeds[:10]])
            e.add_field(name=f"👤 Profils suivis ({len(rs_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="👤 Profils suivis", value="*Aucun profil configuré*", inline=False)
        
        e.set_footer(text="💡 Entrez le nom d'utilisateur RoSocial (ex: GoRipe)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_rosocial_channel', 'rosocial')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon RoSocial", color=0x00D4AA), view=v)
    
    @discord.ui.button(label="➕ Ajouter Profil", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsRoSocialAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Profil", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_rosocial_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun profil à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_rosocial_feeds', 'rosocial')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un profil", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsRoSocialAddModal(Modal, title="➕ Ajouter un profil RoSocial"):
    username = TextInput(label="Nom d'utilisateur RoSocial", placeholder="Ex: GoRipe", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_rosocial_feeds', [])
        
        username = self.username.value.strip()
        if username.lower() in [f.lower() for f in feeds]:
            return await i.response.send_message("❌ Ce profil est déjà ajouté!", ephemeral=True)
        
        feeds.append(username)
        await db_set(self.g.id, 'ads_rosocial_feeds', feeds)
        
        v = AdsRoSocialPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── COMMON VIEWS ───────────────────────────────

class AdsChannelSelectView(View):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(timeout=120)
        self.add_item(AdsChannelSelect(u, g, opts, key, platform))

class AdsChannelSelect(Select):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
        self.platform = platform
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        if self.platform == 'youtube':
            v = AdsYouTubePanel(self.u, self.g)
        elif self.platform == 'twitch':
            v = AdsTwitchPanel(self.u, self.g)
        elif self.platform == 'twitter':
            v = AdsTwitterPanel(self.u, self.g)
        elif self.platform == 'discord':
            v = AdsDiscordPanel(self.u, self.g)
        elif self.platform == 'rosocial':
            v = AdsRoSocialPanel(self.u, self.g)
        else:
            v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsFeedRemoveView(View):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(timeout=120)
        self.add_item(AdsFeedRemoveSelect(u, g, opts, key, platform))

class AdsFeedRemoveSelect(Select):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(placeholder="Sélectionner à supprimer...", options=opts)
        self.u = u
        self.g = g
        self.key = key
        self.platform = platform
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        feeds = c.get(self.key, [])
        idx = int(self.values[0])
        if 0 <= idx < len(feeds):
            feeds.pop(idx)
            await db_set(self.g.id, self.key, feeds)
        
        if self.platform == 'youtube':
            v = AdsYouTubePanel(self.u, self.g)
        elif self.platform == 'twitch':
            v = AdsTwitchPanel(self.u, self.g)
        elif self.platform == 'twitter':
            v = AdsTwitterPanel(self.u, self.g)
        elif self.platform == 'discord':
            v = AdsDiscordPanel(self.u, self.g)
        elif self.platform == 'rosocial':
            v = AdsRoSocialPanel(self.u, self.g)
        else:
            v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 STATISTIQUES PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class StatPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📊 Statistiques & Activité", color=C.PURPLE)
        e.description = "**🔄 Système automatique** - Les actions sont exécutées automatiquement chaque jour.\n*⚠️ Aucune mention automatique des membres*"
        
        # Config actuelle
        stat_cfg = c.get('stat_config', {})
        
        # Actions multiples
        action_labels = {'ping': '📋 Liste', 'remove_role': '🎭 Rôle', 'kick': '👢 Kick'}
        
        actions_7d = stat_cfg.get('actions_7d', [])
        actions_30d = stat_cfg.get('actions_30d', [])
        
        actions_7d_txt = " + ".join([action_labels.get(a, a) for a in actions_7d]) if actions_7d else "❌ Aucune"
        actions_30d_txt = " + ".join([action_labels.get(a, a) for a in actions_30d]) if actions_30d else "❌ Aucune"
        
        role_id = stat_cfg.get('activity_role', 0)
        notif_ch = self.g.get_channel(stat_cfg.get('notif_channel', 0))
        recovery_ch = self.g.get_channel(stat_cfg.get('recovery_channel', 0))
        
        role = self.g.get_role(role_id) if role_id else None
        
        e.add_field(
            name="⚙️ Configuration",
            value=f"**Actions 7j:** {actions_7d_txt}\n"
                  f"**Actions 30j:** {actions_30d_txt}\n"
                  f"**Rôle:** {role.mention if role else '❌'} | **Notifs:** {notif_ch.mention if notif_ch else '❌'} | **Récup:** {recovery_ch.mention if recovery_ch else '❌'}",
            inline=False
        )
        
        # Compter les membres AFK
        afk_7d, afk_30d = await self.count_afk_members()
        e.add_field(name="😴 AFK 7 jours", value=f"**{afk_7d}** membre(s)", inline=True)
        e.add_field(name="💤 AFK 30 jours", value=f"**{afk_30d}** membre(s)", inline=True)
        e.add_field(name="👥 Total membres", value=f"**{self.g.member_count}**", inline=True)
        
        e.set_footer(text="💡 Les membres récupèrent leur rôle en envoyant un message ou en rejoignant un vocal")
        
        return e
    
    async def count_afk_members(self):
        """Compte les membres AFK sur 7j et 30j"""
        afk_7d = 0
        afk_30d = 0
        now_dt = now()
        seven_days_ago = now_dt - timedelta(days=7)
        thirty_days_ago = now_dt - timedelta(days=30)
        
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Membres trackés
                async with db.execute(
                    'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                    (self.g.id,)
                ) as cursor:
                    tracked_users = set()
                    async for row in cursor:
                        user_id, last_msg, last_vocal = row
                        tracked_users.add(user_id)
                        
                        last_activity = None
                        if last_msg:
                            try:
                                last_activity = datetime.fromisoformat(last_msg)
                            except:
                                pass
                        if last_vocal:
                            try:
                                lv = datetime.fromisoformat(last_vocal)
                                if not last_activity or lv > last_activity:
                                    last_activity = lv
                            except:
                                pass
                        
                        if last_activity:
                            if last_activity.replace(tzinfo=timezone.utc) < seven_days_ago.replace(tzinfo=timezone.utc):
                                afk_7d += 1
                            if last_activity.replace(tzinfo=timezone.utc) < thirty_days_ago.replace(tzinfo=timezone.utc):
                                afk_30d += 1
                
                # Membres non trackés = considérés comme AFK
                for member in self.g.members:
                    if not member.bot and member.id not in tracked_users:
                        afk_7d += 1
                        afk_30d += 1
        except:
            pass
        
        return afk_7d, afk_30d
    
    @discord.ui.button(label="⚙️ Configurer Actions", style=discord.ButtonStyle.primary, row=0)
    async def config_actions(self, i, b):
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📈 Voir Graphique", style=discord.ButtonStyle.success, row=0)
    async def view_graph(self, i, b):
        await i.response.defer()
        
        # Générer le graphique
        img = await self.generate_afk_graph()
        
        if img:
            file = discord.File(img, filename="afk_stats.png")
            e = discord.Embed(title="📊 Statistiques d'Activité", color=C.PURPLE)
            e.set_image(url="attachment://afk_stats.png")
            e.set_footer(text=f"{self.g.name} • Statistiques d'activité")
            await i.followup.send(embed=e, file=file, ephemeral=True)
        else:
            await i.followup.send("❌ Erreur lors de la génération du graphique", ephemeral=True)
    
    async def generate_afk_graph(self):
        """Génère un graphique des membres AFK"""
        try:
            afk_7d, afk_30d = await self.count_afk_members()
            active_members = self.g.member_count - afk_7d
            
            # Créer le graphique
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
            fig.patch.set_facecolor('#2f3136')
            
            # Graphique 1: Camembert AFK
            colors1 = ['#57F287', '#FEE75C', '#ED4245']
            sizes1 = [active_members, afk_7d - afk_30d, afk_30d]
            labels1 = [f'Actifs\n({active_members})', f'AFK 7j\n({afk_7d - afk_30d})', f'AFK 30j\n({afk_30d})']
            
            # Filtrer les valeurs nulles
            filtered = [(s, l, c) for s, l, c in zip(sizes1, labels1, colors1) if s > 0]
            if filtered:
                sizes1, labels1, colors1 = zip(*filtered)
            
            ax1.pie(sizes1, labels=labels1, colors=colors1, autopct='%1.1f%%', startangle=90,
                   textprops={'color': 'white', 'fontsize': 11, 'fontweight': 'bold'})
            ax1.set_title('📊 Répartition des Membres', color='white', fontsize=14, fontweight='bold', pad=20)
            ax1.set_facecolor('#2f3136')
            
            # Graphique 2: Barres
            categories = ['Actifs', 'AFK 7 jours', 'AFK 30 jours']
            values = [active_members, afk_7d, afk_30d]
            colors2 = ['#57F287', '#FEE75C', '#ED4245']
            
            bars = ax2.bar(categories, values, color=colors2, edgecolor='white', linewidth=2)
            ax2.set_ylabel('Nombre de membres', color='white', fontsize=12)
            ax2.set_title('📈 Statistiques d\'Activité', color='white', fontsize=14, fontweight='bold', pad=20)
            ax2.set_facecolor('#36393f')
            ax2.tick_params(colors='white')
            ax2.spines['bottom'].set_color('white')
            ax2.spines['left'].set_color('white')
            ax2.spines['top'].set_visible(False)
            ax2.spines['right'].set_visible(False)
            
            # Ajouter les valeurs sur les barres
            for bar, val in zip(bars, values):
                ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                        str(val), ha='center', color='white', fontweight='bold', fontsize=12)
            
            plt.tight_layout()
            
            # Sauvegarder en buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
            buf.seek(0)
            plt.close(fig)
            
            return buf
        except Exception as ex:
            print(f"Erreur graphique: {ex}")
            return None
    
    @discord.ui.button(label="⚡ Exécuter maintenant", style=discord.ButtonStyle.danger, row=0)
    async def execute_actions(self, i, b):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        actions_7d = stat_cfg.get('actions_7d', [])
        actions_30d = stat_cfg.get('actions_30d', [])
        
        if not actions_7d and not actions_30d:
            return await i.response.send_message("❌ Aucune action configurée. Configurez d'abord les actions.", ephemeral=True)
        
        afk_7d, afk_30d = await self.count_afk_members()
        
        await i.response.send_message(
            f"⚠️ **Exécution manuelle des actions**\n\n"
            f"**Membres concernés:**\n"
            f"• 😴 AFK 7 jours: **{afk_7d}** membres\n"
            f"• 💤 AFK 30 jours: **{afk_30d}** membres\n\n"
            f"*Le système s'exécute automatiquement chaque jour, mais vous pouvez forcer l'exécution maintenant.*",
            view=StatExecuteConfirmView(self.u, self.g),
            ephemeral=True
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class StatActionPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        
        e = discord.Embed(title="⚙️ Configuration des Actions", color=C.ORANGE)
        e.description = "Configurez les actions automatiques sur les membres inactifs.\n**Vous pouvez sélectionner plusieurs actions !**\n\n*⚠️ Aucune mention automatique - Vous ferez le @here/@everyone vous-même*"
        
        action_labels = {'ping': '📋 Lister', 'remove_role': '🎭 Retirer rôle', 'kick': '👢 Kick'}
        
        # Actions 7 jours (maintenant une liste)
        actions_7d = stat_cfg.get('actions_7d', [])
        if actions_7d:
            actions_7d_txt = " + ".join([action_labels.get(a, a) for a in actions_7d])
        else:
            actions_7d_txt = "❌ Aucune"
        
        # Actions 30 jours (maintenant une liste)
        actions_30d = stat_cfg.get('actions_30d', [])
        if actions_30d:
            actions_30d_txt = " + ".join([action_labels.get(a, a) for a in actions_30d])
        else:
            actions_30d_txt = "❌ Aucune"
        
        role_id = stat_cfg.get('activity_role', 0)
        notif_ch = self.g.get_channel(stat_cfg.get('notif_channel', 0))
        recovery_ch = self.g.get_channel(stat_cfg.get('recovery_channel', 0))
        role = self.g.get_role(role_id) if role_id else None
        
        e.add_field(
            name="😴 Actions après 7 jours",
            value=actions_7d_txt,
            inline=True
        )
        e.add_field(
            name="💤 Actions après 30 jours",
            value=actions_30d_txt,
            inline=True
        )
        e.add_field(name="\u200b", value="\u200b", inline=True)
        
        e.add_field(
            name="🎭 Rôle d'activité",
            value=role.mention if role else "❌ Non défini",
            inline=True
        )
        e.add_field(
            name="📢 Salon notifications",
            value=notif_ch.mention if notif_ch else "❌ Non défini",
            inline=True
        )
        e.add_field(
            name="💬 Salon récupération",
            value=recovery_ch.mention if recovery_ch else "❌ Non défini",
            inline=True
        )
        
        e.set_footer(text="💡 Le rôle sera redonné automatiquement si le membre envoie un message ou rejoint un vocal")
        return e
    
    @discord.ui.select(
        placeholder="😴 Actions 7 jours (multi-sélection)...",
        options=[
            discord.SelectOption(label="Lister les membres", value="ping", emoji="📋", description="Afficher la liste dans le salon de notifications"),
            discord.SelectOption(label="Retirer le rôle", value="remove_role", emoji="🎭", description="Enlever le rôle d'activité"),
            discord.SelectOption(label="Kick les membres", value="kick", emoji="👢", description="Expulser du serveur"),
        ],
        min_values=0,
        max_values=3,
        row=0
    )
    async def action_7d(self, i, s):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['actions_7d'] = s.values  # Liste d'actions
        await db_set(self.g.id, 'stat_config', stat_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.select(
        placeholder="💤 Actions 30 jours (multi-sélection)...",
        options=[
            discord.SelectOption(label="Lister les membres", value="ping", emoji="📋", description="Afficher la liste dans le salon de notifications"),
            discord.SelectOption(label="Retirer le rôle", value="remove_role", emoji="🎭", description="Enlever le rôle d'activité"),
            discord.SelectOption(label="Kick les membres", value="kick", emoji="👢", description="Expulser du serveur"),
        ],
        min_values=0,
        max_values=3,
        row=1
    )
    async def action_30d(self, i, s):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['actions_30d'] = s.values  # Liste d'actions
        await db_set(self.g.id, 'stat_config', stat_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=2)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles if not r.is_default() and not r.managed and r < self.g.me.top_role][:25]
        if not roles:
            return await i.response.send_message("❌ Aucun rôle disponible", ephemeral=True)
        opts = [discord.SelectOption(label=r.name[:25], value=str(r.id)) for r in roles]
        v = StatRoleSelectView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Sélectionner le rôle d'activité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📢 Notifs", style=discord.ButtonStyle.primary, row=2)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = StatChannelSelectView(self.u, self.g, opts, 'notif_channel')
        await i.response.edit_message(embed=discord.Embed(title="📢 Salon de notifications", description="Salon où seront envoyées les alertes d'inactivité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="💬 Récup", style=discord.ButtonStyle.primary, row=2)
    async def set_recovery(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = StatChannelSelectView(self.u, self.g, opts, 'recovery_channel')
        await i.response.edit_message(embed=discord.Embed(title="💬 Salon de récupération", description="Salon où les membres doivent écrire pour récupérer leur activité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = StatPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="👢 Expulser AFK 7j", style=discord.ButtonStyle.danger, row=3)
    async def kick_7d(self, i, b):
        count = await count_afk_members_by_days(self.g, 7)
        await i.response.send_message(
            f"⚠️ **ATTENTION - Action irréversible !**\n\n"
            f"Vous êtes sur le point d'expulser **{count}** membre(s) inactif(s) depuis **7 jours**.\n\n"
            f"Cette action est **DÉFINITIVE** et ne peut pas être annulée.",
            view=KickConfirmView(self.u, self.g, 7, count),
            ephemeral=True
        )
    
    @discord.ui.button(label="👢 Expulser AFK 30j", style=discord.ButtonStyle.danger, row=3)
    async def kick_30d(self, i, b):
        count = await count_afk_members_by_days(self.g, 30)
        await i.response.send_message(
            f"⚠️ **ATTENTION - Action irréversible !**\n\n"
            f"Vous êtes sur le point d'expulser **{count}** membre(s) inactif(s) depuis **30 jours**.\n\n"
            f"Cette action est **DÉFINITIVE** et ne peut pas être annulée.",
            view=KickConfirmView(self.u, self.g, 30, count),
            ephemeral=True
        )

async def count_afk_members_by_days(guild, days):
    """Compte les membres AFK depuis X jours"""
    count = 0
    now_dt = now()
    cutoff = now_dt - timedelta(days=days)
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                tracked_users = set()
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    tracked_users.add(user_id)
                    
                    last_activity = None
                    if last_msg:
                        try:
                            last_activity = datetime.fromisoformat(last_msg)
                        except:
                            pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except:
                            pass
                    
                    if last_activity:
                        if last_activity.replace(tzinfo=timezone.utc) < cutoff.replace(tzinfo=timezone.utc):
                            member = guild.get_member(user_id)
                            if member and not member.bot and member.id != guild.owner_id:
                                count += 1
            
            for member in guild.members:
                if not member.bot and member.id not in tracked_users and member.id != guild.owner_id:
                    count += 1
    except:
        pass
    
    return count

class KickConfirmView(View):
    def __init__(self, u, g, days, count):
        super().__init__(timeout=60)
        self.u = u
        self.g = g
        self.days = days
        self.count = count
    
    @discord.ui.button(label="✅ Confirmer l'expulsion", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        await i.response.defer()
        for item in self.children:
            item.disabled = True
        await i.message.edit(view=self)
        result = await kick_afk_members(self.g, self.days)
        await i.followup.send(result, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Expulsion annulée.", view=None)

async def kick_afk_members(guild, days):
    """Expulse tous les membres AFK depuis X jours"""
    now_dt = now()
    cutoff = now_dt - timedelta(days=days)
    
    kicked = 0
    failed = 0
    skipped = 0
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                tracked_users = {}
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    last_activity = None
                    if last_msg:
                        try: last_activity = datetime.fromisoformat(last_msg)
                        except: pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except: pass
                    tracked_users[user_id] = last_activity
        
        for member in list(guild.members):
            if member.bot:
                continue
            if member.id == guild.owner_id:
                skipped += 1
                continue
            if member.top_role >= guild.me.top_role:
                skipped += 1
                continue
            
            last_activity = tracked_users.get(member.id)
            is_afk = False
            if not last_activity:
                is_afk = True
            else:
                la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
                is_afk = la_utc < cutoff.replace(tzinfo=timezone.utc)
            
            if is_afk:
                try:
                    await member.kick(reason=f"Inactivité de plus de {days} jours")
                    kicked += 1
                    await asyncio.sleep(0.5)
                except:
                    failed += 1
        
        result = f"✅ **Expulsion terminée !**\n\n"
        result += f"👢 **{kicked}** membre(s) expulsé(s)\n"
        if failed > 0:
            result += f"❌ **{failed}** échec(s)\n"
        if skipped > 0:
            result += f"⏭️ **{skipped}** ignoré(s)\n"
        result += f"\n*Critère: inactif depuis plus de {days} jours*"
        return result
        
    except Exception as ex:
        return f"❌ Erreur: {ex}"

class StatRoleSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(StatRoleSelect(u, g, opts))

class StatRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['activity_role'] = int(self.values[0])
        await db_set(self.g.id, 'stat_config', stat_cfg)
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class StatChannelSelectView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(StatChannelSelect(u, g, opts, key))

class StatChannelSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg[self.key] = int(self.values[0])
        await db_set(self.g.id, 'stat_config', stat_cfg)
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class StatExecuteConfirmView(View):
    def __init__(self, u, g):
        super().__init__(timeout=60)
        self.u = u
        self.g = g
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        await i.response.defer()
        result = await execute_afk_actions(self.g)
        await i.followup.send(result, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Action annulée", view=None)

async def execute_afk_actions(guild):
    """Exécute les actions sur les membres AFK - Version optimisée pour gros serveurs"""
    c = await cfg(guild.id)
    stat_cfg = c.get('stat_config', {})
    
    # Maintenant ce sont des listes d'actions
    actions_7d = stat_cfg.get('actions_7d', [])
    actions_30d = stat_cfg.get('actions_30d', [])
    role_id = stat_cfg.get('activity_role', 0)
    notif_ch_id = stat_cfg.get('notif_channel', 0)
    recovery_ch_id = stat_cfg.get('recovery_channel', 0)
    
    role = guild.get_role(role_id) if role_id else None
    notif_ch = guild.get_channel(notif_ch_id) if notif_ch_id else None
    recovery_ch = guild.get_channel(recovery_ch_id) if recovery_ch_id else None
    
    now_dt = now()
    seven_days_ago = now_dt - timedelta(days=7)
    thirty_days_ago = now_dt - timedelta(days=30)
    
    results = {
        'ping_7d': 0, 'remove_role_7d': 0, 'kick_7d': 0,
        'ping_30d': 0, 'remove_role_30d': 0, 'kick_30d': 0
    }
    
    try:
        # Récupérer les activités
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                user_activities = {}
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    last_activity = None
                    if last_msg:
                        try: last_activity = datetime.fromisoformat(last_msg)
                        except: pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except: pass
                    user_activities[user_id] = last_activity
        
        # Listes pour les membres AFK
        afk_members_7d = []  # Inactifs 7j mais pas 30j
        afk_members_30d = []  # Inactifs 30j+
        
        for member in guild.members:
            if member.bot or member.id == guild.owner_id:
                continue
            
            last_activity = user_activities.get(member.id)
            
            if not last_activity:
                is_afk_7d = True
                is_afk_30d = True
            else:
                la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
                is_afk_7d = la_utc < seven_days_ago.replace(tzinfo=timezone.utc)
                is_afk_30d = la_utc < thirty_days_ago.replace(tzinfo=timezone.utc)
            
            if is_afk_30d:
                afk_members_30d.append(member)
            elif is_afk_7d:
                afk_members_7d.append(member)
        
        # ═══════════════ ACTIONS 30 JOURS ═══════════════
        for member in afk_members_30d:
            # TOUJOURS retirer le rôle si une action est configurée (ping OU remove_role)
            # Car un membre AFK mentionné doit perdre son rôle
            if role and role in member.roles and actions_30d:
                try:
                    await member.remove_roles(role, reason="Inactivité 30 jours")
                    results['remove_role_30d'] += 1
                    await asyncio.sleep(0.1)
                except:
                    pass
            
            # Kick si configuré
            if 'kick' in actions_30d:
                try:
                    if member.top_role < guild.me.top_role:
                        await member.kick(reason="Inactivité 30 jours")
                        results['kick_30d'] += 1
                        await asyncio.sleep(0.3)
                except:
                    pass
        
        # ═══════════════ ACTIONS 7 JOURS ═══════════════
        for member in afk_members_7d:
            # TOUJOURS retirer le rôle si une action est configurée
            if role and role in member.roles and actions_7d:
                try:
                    await member.remove_roles(role, reason="Inactivité 7 jours")
                    results['remove_role_7d'] += 1
                    await asyncio.sleep(0.1)
                except:
                    pass
            
            # Kick si configuré
            if 'kick' in actions_7d:
                try:
                    if member.top_role < guild.me.top_role:
                        await member.kick(reason="Inactivité 7 jours")
                        results['kick_7d'] += 1
                        await asyncio.sleep(0.3)
                except:
                    pass
        
        # ═══════════════ NOTIFICATIONS COMPACTES ═══════════════
        if notif_ch:
            recovery_mention = recovery_ch.mention if recovery_ch else "un salon textuel ou vocal"
            
            # Notification 30 jours (si ping activé et membres non kickés)
            members_to_ping_30d = [m for m in afk_members_30d if 'kick' not in actions_30d]
            if 'ping' in actions_30d and members_to_ping_30d:
                results['ping_30d'] = len(members_to_ping_30d)
                await send_compact_afk_notification(
                    notif_ch, members_to_ping_30d, 30, recovery_mention, role
                )
            
            # Notification 7 jours (si ping activé et membres non kickés)
            members_to_ping_7d = [m for m in afk_members_7d if 'kick' not in actions_7d]
            if 'ping' in actions_7d and members_to_ping_7d:
                results['ping_7d'] = len(members_to_ping_7d)
                await send_compact_afk_notification(
                    notif_ch, members_to_ping_7d, 7, recovery_mention, role
                )
        
        # Résumé
        summary = "✅ **Actions exécutées:**\n\n"
        
        if results['ping_7d']: summary += f"📋 **{results['ping_7d']}** membre(s) listé(s) (7j)\n"
        if results['remove_role_7d']: summary += f"🎭 **{results['remove_role_7d']}** rôle(s) retiré(s) (7j)\n"
        if results['kick_7d']: summary += f"👢 **{results['kick_7d']}** membre(s) expulsé(s) (7j)\n"
        
        if results['ping_30d']: summary += f"📋 **{results['ping_30d']}** membre(s) listé(s) (30j)\n"
        if results['remove_role_30d']: summary += f"🎭 **{results['remove_role_30d']}** rôle(s) retiré(s) (30j)\n"
        if results['kick_30d']: summary += f"👢 **{results['kick_30d']}** membre(s) expulsé(s) (30j)\n"
        
        if sum(results.values()) == 0:
            summary = "ℹ️ Aucune action effectuée.\n\n**Vérifiez:**\n• Les actions sont-elles configurées ?\n• Y a-t-il des membres inactifs ?"
        else:
            summary += "\n💡 *Vous pouvez maintenant utiliser @here ou @everyone pour notifier les membres*"
        
        return summary
        
    except Exception as ex:
        return f"❌ Erreur: {ex}"

async def send_compact_afk_notification(channel, members, days, recovery_mention, role):
    """Envoie un beau tableau des membres AFK SANS aucune mention"""
    if not members:
        return
    
    # Configuration selon la durée
    if days == 7:
        title = "😴 Rapport d'Inactivité - 7 Jours"
        color = C.YELLOW
        emoji = "⚠️"
        severity = "modérée"
    else:
        title = "💤 Rapport d'Inactivité - 30 Jours"
        color = C.RED
        emoji = "🚨"
        severity = "critique"
    
    role_txt = f"**{role.name}**" if role else "d'activité"
    
    # ═══════════════ EMBED PRINCIPAL ═══════════════
    e = discord.Embed(title=title, color=color)
    
    e.description = (
        f"{emoji} **{len(members)}** membre(s) ont été détectés comme inactifs.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    # Statistiques
    e.add_field(
        name="📊 Statistiques",
        value=f"```\n"
              f"Membres concernés : {len(members)}\n"
              f"Durée d'inactivité: {days} jours\n"
              f"Sévérité          : {severity.upper()}\n"
              f"```",
        inline=False
    )
    
    # Actions effectuées
    actions_txt = ""
    if role:
        actions_txt += f"🎭 Le rôle {role_txt} a été **retiré**\n"
    actions_txt += f"📋 Les membres sont listés ci-dessous"
    
    e.add_field(
        name="⚡ Actions effectuées",
        value=actions_txt,
        inline=False
    )
    
    # Comment récupérer
    e.add_field(
        name="🔄 Comment récupérer son activité ?",
        value=f"```\n"
              f"1️⃣ Envoyer un message dans {recovery_mention}\n"
              f"   → Le message sera supprimé automatiquement\n"
              f"   → Le rôle sera redonné instantanément\n\n"
              f"2️⃣ OU rejoindre un salon vocal\n"
              f"   → Le rôle sera redonné automatiquement\n"
              f"```",
        inline=False
    )
    
    e.set_footer(text=f"📌 Aucune mention automatique • L'administrateur peut ping @here ou @everyone")
    e.timestamp = now()
    
    await channel.send(embed=e)
    
    # ═══════════════ TABLEAU DES MEMBRES ═══════════════
    # Créer des embeds avec la liste des membres (sans mentions !)
    
    # Trier par nom pour plus de lisibilité
    sorted_members = sorted(members, key=lambda m: m.display_name.lower())
    
    # Grouper par 20 membres par embed
    chunk_size = 20
    total_chunks = (len(sorted_members) + chunk_size - 1) // chunk_size
    
    for i in range(0, len(sorted_members), chunk_size):
        chunk = sorted_members[i:i + chunk_size]
        chunk_num = (i // chunk_size) + 1
        
        table_embed = discord.Embed(color=color)
        
        if total_chunks > 1:
            table_embed.title = f"📋 Liste des membres inactifs ({chunk_num}/{total_chunks})"
        else:
            table_embed.title = "📋 Liste des membres inactifs"
        
        # Créer un tableau formaté
        table_lines = []
        for idx, member in enumerate(chunk, start=i+1):
            # Format: numéro | nom | ID
            name = member.display_name[:20]
            table_lines.append(f"`{idx:3d}.` **{name}** • `{member.id}`")
        
        table_embed.description = "\n".join(table_lines)
        
        await channel.send(embed=table_embed)
        await asyncio.sleep(0.3)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔄 TÂCHE AUTOMATIQUE INACTIVITÉ
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(hours=24)
async def check_afk_automatic():
    """Vérifie automatiquement l'inactivité des membres chaque jour"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, data FROM guild_config') as cursor:
                async for row in cursor:
                    guild_id, data_str = row
                    try:
                        data = json.loads(data_str) if data_str else {}
                        guild = bot.get_guild(guild_id)
                        if not guild:
                            continue
                        
                        stat_cfg = data.get('stat_config', {})
                        actions_7d = stat_cfg.get('actions_7d', [])
                        actions_30d = stat_cfg.get('actions_30d', [])
                        
                        # Si aucune action configurée, passer
                        if not actions_7d and not actions_30d:
                            continue
                        
                        # Exécuter les actions automatiques
                        await execute_afk_actions_auto(guild, stat_cfg)
                        
                    except Exception as ex:
                        print(f"Erreur AFK auto {guild_id}: {ex}")
                        continue
    except Exception as ex:
        print(f"Erreur tâche AFK: {ex}")

@check_afk_automatic.before_loop
async def before_afk_check():
    await bot.wait_until_ready()

async def execute_afk_actions_auto(guild, stat_cfg):
    """Exécute les actions automatiques sur les membres AFK"""
    actions_7d = stat_cfg.get('actions_7d', [])
    actions_30d = stat_cfg.get('actions_30d', [])
    role_id = stat_cfg.get('activity_role', 0)
    notif_ch_id = stat_cfg.get('notif_channel', 0)
    recovery_ch_id = stat_cfg.get('recovery_channel', 0)
    
    role = guild.get_role(role_id) if role_id else None
    notif_ch = guild.get_channel(notif_ch_id) if notif_ch_id else None
    recovery_ch = guild.get_channel(recovery_ch_id) if recovery_ch_id else None
    
    now_dt = now()
    seven_days_ago = now_dt - timedelta(days=7)
    thirty_days_ago = now_dt - timedelta(days=30)
    
    # Récupérer les activités
    user_activities = {}
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    last_activity = None
                    if last_msg:
                        try: last_activity = datetime.fromisoformat(last_msg)
                        except: pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except: pass
                    user_activities[user_id] = last_activity
    except:
        return
    
    # Classifier les membres
    afk_members_7d = []
    afk_members_30d = []
    
    for member in guild.members:
        if member.bot or member.id == guild.owner_id:
            continue
        
        last_activity = user_activities.get(member.id)
        
        if not last_activity:
            is_afk_7d = True
            is_afk_30d = True
        else:
            la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
            is_afk_7d = la_utc < seven_days_ago.replace(tzinfo=timezone.utc)
            is_afk_30d = la_utc < thirty_days_ago.replace(tzinfo=timezone.utc)
        
        if is_afk_30d:
            afk_members_30d.append(member)
        elif is_afk_7d:
            afk_members_7d.append(member)
    
    # ═══════════════ ACTIONS 30 JOURS ═══════════════
    kicked_30d = []
    role_removed_30d = []
    
    for member in afk_members_30d:
        # Retirer le rôle
        if 'remove_role' in actions_30d and role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Inactivité 30 jours (auto)")
                role_removed_30d.append(member)
            except: pass
        
        # Kick
        if 'kick' in actions_30d:
            try:
                if member.top_role < guild.me.top_role:
                    await member.kick(reason="Inactivité 30 jours (auto)")
                    kicked_30d.append(member)
                    await asyncio.sleep(0.3)
            except: pass
    
    # Notification 30j (seulement si ping ET pas kick)
    members_to_notify_30d = [m for m in afk_members_30d if m not in kicked_30d]
    if 'ping' in actions_30d and members_to_notify_30d and notif_ch:
        recovery_mention = recovery_ch.mention if recovery_ch else "un salon textuel"
        await send_compact_afk_notification(notif_ch, members_to_notify_30d, 30, recovery_mention, role if 'remove_role' in actions_30d else None)
    
    # ═══════════════ ACTIONS 7 JOURS ═══════════════
    kicked_7d = []
    role_removed_7d = []
    
    for member in afk_members_7d:
        # Retirer le rôle
        if 'remove_role' in actions_7d and role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Inactivité 7 jours (auto)")
                role_removed_7d.append(member)
            except: pass
        
        # Kick
        if 'kick' in actions_7d:
            try:
                if member.top_role < guild.me.top_role:
                    await member.kick(reason="Inactivité 7 jours (auto)")
                    kicked_7d.append(member)
                    await asyncio.sleep(0.3)
            except: pass
    
    # Notification 7j (seulement si ping ET pas kick)
    members_to_notify_7d = [m for m in afk_members_7d if m not in kicked_7d]
    if 'ping' in actions_7d and members_to_notify_7d and notif_ch:
        recovery_mention = recovery_ch.mention if recovery_ch else "un salon textuel"
        await send_compact_afk_notification(notif_ch, members_to_notify_7d, 7, recovery_mention, role if 'remove_role' in actions_7d else None)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📺 CONFIG SALON
# ═══════════════════════════════════════════════════════════════════════════════

class ChanPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        e = discord.Embed(title="📺 Configuration des salons", color=C.ORANGE)
        if configs:
            lines = []
            for ch_id, conf in list(configs.items())[:15]:
                ch = self.g.get_channel(int(ch_id))
                if ch:
                    icons = ""
                    if not conf.get('messages', True): icons += "💬❌ "
                    if not conf.get('images', True): icons += "🖼️❌ "
                    if not conf.get('gifs', True): icons += "🎞️❌ "
                    if not conf.get('emojis', True): icons += "😀❌ "
                    if not conf.get('links', True): icons += "🔗❌ "
                    if conf.get('commands_only', False): icons += "🤖✅ "
                    lines.append(f"{ch.mention}: {icons or '✅ Tout autorisé'}")
            e.description = "\n".join(lines)
        else:
            e.description = "*Aucun salon configuré*"
        return e
    
    @discord.ui.button(label="➕ Configurer un salon", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        await i.response.edit_message(embed=discord.Embed(title="📺 Choisir un salon", color=C.ORANGE), view=ChanSelectView(self.u, self.g, opts))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ChanSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ChanSelect(u, g, opts))

class ChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        v = EditChanCfg(self.u, self.g, self.values[0])
        await i.response.edit_message(embed=await v.embed(), view=v)

class EditChanCfg(View):
    def __init__(self, u, g, ch_id):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.ch_id = ch_id
    
    async def get_conf(self):
        c = await cfg(self.g.id)
        return c.get('channel_configs', {}).get(str(self.ch_id), {'messages': True, 'images': True, 'gifs': True, 'emojis': True, 'links': True, 'commands_only': False})
    
    async def save(self, conf):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        configs[str(self.ch_id)] = conf
        await db_set(self.g.id, 'channel_configs', configs)
    
    async def embed(self):
        ch = self.g.get_channel(int(self.ch_id))
        conf = await self.get_conf()
        s = lambda k: "✅ Autorisé" if conf.get(k, True) else "❌ Bloqué"
        so = lambda k: "✅ Activé" if conf.get(k, False) else "❌ Désactivé"
        e = discord.Embed(title=f"📺 Configuration de #{ch.name if ch else '?'}", color=C.ORANGE)
        e.description = f"💬 Messages: {s('messages')}\n🖼️ Images: {s('images')}\n🎞️ GIFs: {s('gifs')}\n😀 Emojis: {s('emojis')}\n🔗 Liens: {s('links')}\n\n🤖 **Commandes bot uniquement**: {so('commands_only')}"
        return e
    
    async def toggle(self, i, key, default=True):
        conf = await self.get_conf()
        conf[key] = not conf.get(key, default)
        await self.save(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="💬 Messages", style=discord.ButtonStyle.primary, row=0)
    async def t1(self, i, b): await self.toggle(i, 'messages')
    
    @discord.ui.button(label="🖼️ Images", style=discord.ButtonStyle.primary, row=0)
    async def t2(self, i, b): await self.toggle(i, 'images')
    
    @discord.ui.button(label="🎞️ GIFs", style=discord.ButtonStyle.primary, row=0)
    async def t3(self, i, b): await self.toggle(i, 'gifs')
    
    @discord.ui.button(label="😀 Emojis", style=discord.ButtonStyle.primary, row=1)
    async def t4(self, i, b): await self.toggle(i, 'emojis')
    
    @discord.ui.button(label="🔗 Liens", style=discord.ButtonStyle.primary, row=1)
    async def t5(self, i, b): await self.toggle(i, 'links')
    
    @discord.ui.button(label="🤖 Commandes uniquement", style=discord.ButtonStyle.success, row=1)
    async def t6(self, i, b): await self.toggle(i, 'commands_only', False)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = ChanPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎫 TICKET CONFIG PANEL (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

class TicketMainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎫 Configuration Tickets", color=C.PURPLE)
        staff = self.g.get_role(c.get('ticket_staff', 0))
        lch = self.g.get_channel(c.get('ticket_log', 0))
        e.add_field(name="👮 Rôle Staff", value=staff.mention if staff else "❌ Non configuré", inline=True)
        e.add_field(name="📜 Salon Logs", value=lch.mention if lch else "❌ Non configuré", inline=True)
        panels = c.get('ticket_panels', {})
        if panels:
            pl = []
            for pid, pd in list(panels.items())[:10]:
                cat = self.g.get_channel(pd.get('category', 0))
                pl.append(f"• **{pd.get('name', pid)[:20]}** → `{cat.name if cat else '❌'}` ({len(pd.get('questions', []))} questions, max {pd.get('max', 1)})")
            e.add_field(name=f"📋 Panels ({len(panels)})", value="\n".join(pl), inline=False)
        else:
            e.add_field(name="📋 Panels", value="*Aucun panel créé*", inline=False)
        return e
    
    @discord.ui.button(label="👮 Définir Staff", style=discord.ButtonStyle.primary, row=0)
    async def staff(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        await i.response.edit_message(embed=discord.Embed(title="👮 Choisir le rôle Staff", color=C.PURPLE), view=TkStaffView(self.u, self.g, opts))
    
    @discord.ui.button(label="📜 Définir Logs", style=discord.ButtonStyle.primary, row=0)
    async def logs(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        await i.response.edit_message(embed=discord.Embed(title="📜 Choisir le salon Logs", color=C.PURPLE), view=TkLogView(self.u, self.g, opts))
    
    @discord.ui.button(label="➕ Nouveau Panel", style=discord.ButtonStyle.success, row=1)
    async def new(self, i, b):
        await i.response.send_modal(NewPanelModal(self.u, self.g))
    
    @discord.ui.button(label="📝 Modifier Panel", style=discord.ButtonStyle.secondary, row=1)
    async def edit(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if not panels:
            return await i.response.send_message("❌ Aucun panel créé", ephemeral=True)
        opts = [discord.SelectOption(label=pd.get('name', pid)[:25], value=pid) for pid, pd in list(panels.items())[:25]]
        await i.response.edit_message(embed=discord.Embed(title="📝 Choisir un panel", color=C.PURPLE), view=EditPanelSelectView(self.u, self.g, opts))
    
    @discord.ui.button(label="🔄 Rafraîchir", style=discord.ButtonStyle.secondary, row=2)
    async def ref(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class TkStaffView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TkStaffSel(u, g, opts))

class TkStaffSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_staff', int(self.values[0]))
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TkLogView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TkLogSel(u, g, opts))

class TkLogSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_log', int(self.values[0]))
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class NewPanelModal(Modal, title="➕ Nouveau Panel"):
    name = TextInput(label="Nom du panel", placeholder="Support, Partenariat...", max_length=30)
    mx = TextInput(label="Max tickets par utilisateur", placeholder="1", default="1", max_length=2)
    
    def __init__(self, u, g):
        super().__init__()
        self.u = u
        self.g = g
    
    async def on_submit(self, i):
        pid = str(int(time.time()))
        mxt = max(1, min(10, int(self.mx.value) if self.mx.value.isdigit() else 1))
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        panels[pid] = {'name': self.name.value, 'category': 0, 'questions': [], 'max': mxt}
        await db_set(self.g.id, 'ticket_panels', panels)
        v = PanelEditView(self.u, self.g, pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class EditPanelSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(EditPanelSel(u, g, opts))

class EditPanelSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un panel...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        v = PanelEditView(self.u, self.g, self.values[0])
        await i.response.edit_message(embed=await v.embed(), view=v)

class PanelEditView(View):
    def __init__(self, u, g, pid):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def get_panel(self):
        c = await cfg(self.g.id)
        return c.get('ticket_panels', {}).get(self.pid, {})
    
    async def embed(self):
        pnl = await self.get_panel()
        e = discord.Embed(title=f"🎫 Panel: {pnl.get('name', '?')}", color=C.PURPLE)
        cat = self.g.get_channel(pnl.get('category', 0))
        e.add_field(name="📁 Catégorie", value=cat.name if cat else "❌ Non configuré", inline=True)
        e.add_field(name="🔢 Max tickets", value=str(pnl.get('max', 1)), inline=True)
        qs = pnl.get('questions', [])
        if qs:
            e.add_field(name=f"📝 Questions ({len(qs)})", value="\n".join([f"• {q['title']}" for q in qs[:5]]), inline=False)
        else:
            e.add_field(name="📝 Questions", value="*Aucune question*", inline=False)
        return e
    
    @discord.ui.button(label="📁 Catégorie", style=discord.ButtonStyle.primary, row=0)
    async def cat(self, i, b):
        cats = list(self.g.categories)[:25]
        if not cats:
            return await i.response.send_message("❌ Aucune catégorie sur ce serveur", ephemeral=True)
        opts = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in cats]
        await i.response.edit_message(embed=discord.Embed(title="📁 Choisir la catégorie", color=C.PURPLE), view=PanelCatView(self.u, self.g, self.pid, opts))
    
    @discord.ui.button(label="📝 Questions", style=discord.ButtonStyle.primary, row=0)
    async def qs(self, i, b):
        v = PanelQsView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🔢 Max tickets", style=discord.ButtonStyle.secondary, row=0)
    async def mx(self, i, b):
        await i.response.send_modal(SetMaxModal(self.u, self.g, self.pid))
    
    @discord.ui.button(label="📤 Envoyer", style=discord.ButtonStyle.success, row=1)
    async def send(self, i, b):
        pnl = await self.get_panel()
        c = await cfg(self.g.id)
        if not pnl.get('category'):
            return await i.response.send_message("❌ Configure la catégorie d'abord!", ephemeral=True)
        if not c.get('ticket_staff'):
            return await i.response.send_message("❌ Configure le rôle Staff d'abord!", ephemeral=True)
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {ch.name}"[:25], value=str(ch.id)) for ch in chs]
        await i.response.edit_message(embed=discord.Embed(title="📤 Où envoyer le panel?", color=C.PURPLE), view=SendPanelView(self.u, self.g, self.pid, opts))
    
    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            del panels[self.pid]
        await db_set(self.g.id, 'ticket_panels', panels)
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class PanelCatView(View):
    def __init__(self, u, g, pid, opts):
        super().__init__(timeout=120)
        self.add_item(PanelCatSel(u, g, pid, opts))

class PanelCatSel(Select):
    def __init__(self, u, g, pid, opts):
        super().__init__(placeholder="Choisir une catégorie...", options=opts)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def callback(self, i):
        c = await cfg(i.guild.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['category'] = int(self.values[0])
            await db_set(i.guild.id, 'ticket_panels', panels)
        v = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SetMaxModal(Modal, title="🔢 Max tickets par utilisateur"):
    mx = TextInput(label="Nombre maximum", placeholder="1-10", default="1", max_length=2)
    
    def __init__(self, u, g, pid):
        super().__init__()
        self.u = u
        self.g = g
        self.pid = pid
    
    async def on_submit(self, i):
        v = max(1, min(10, int(self.mx.value) if self.mx.value.isdigit() else 1))
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['max'] = v
            await db_set(self.g.id, 'ticket_panels', panels)
        vw = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await vw.embed(), view=vw)

class PanelQsView(View):
    def __init__(self, u, g, pid):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def embed(self):
        c = await cfg(self.g.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        qs = pnl.get('questions', [])
        e = discord.Embed(title="📝 Questions du panel", color=C.PURPLE)
        if qs:
            for j, q in enumerate(qs, 1):
                e.add_field(name=f"{j}. {q['title']}", value=q['question'][:100], inline=False)
        else:
            e.description = "*Aucune question configurée*"
        e.set_footer(text="Maximum 5 questions")
        return e
    
    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        c = await cfg(self.g.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        if len(pnl.get('questions', [])) >= 5:
            return await i.response.send_message("❌ Maximum 5 questions", ephemeral=True)
        await i.response.send_modal(AddQModal(self.u, self.g, self.pid))
    
    @discord.ui.button(label="🗑️ Tout supprimer", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['questions'] = []
            await db_set(self.g.id, 'ticket_panels', panels)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddQModal(Modal, title="➕ Ajouter une question"):
    t = TextInput(label="Titre (affiché dans le formulaire)", placeholder="Ex: Pseudo en jeu", max_length=45)
    q = TextInput(label="Question complète", placeholder="Ex: Quel est votre pseudo sur le serveur?", style=discord.TextStyle.paragraph, max_length=100)
    
    def __init__(self, u, g, pid):
        super().__init__()
        self.u = u
        self.g = g
        self.pid = pid
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid].setdefault('questions', []).append({'title': self.t.value, 'question': self.q.value})
            await db_set(self.g.id, 'ticket_panels', panels)
        v = PanelQsView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SendPanelView(View):
    def __init__(self, u, g, pid, opts):
        super().__init__(timeout=120)
        self.add_item(SendPanelSel(u, g, pid, opts))

class SendPanelSel(Select):
    def __init__(self, u, g, pid, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def callback(self, i):
        ch = i.guild.get_channel(int(self.values[0]))
        if not ch:
            return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
        c = await cfg(i.guild.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        qs = pnl.get('questions', [])
        mx = pnl.get('max', 1)
        desc = "Cliquez sur le bouton ci-dessous pour créer un ticket."
        if qs:
            desc += f"\n\n📝 Vous devrez répondre à **{len(qs)}** question(s)."
        desc += f"\n🔢 Maximum **{mx}** ticket(s) simultané(s)."
        emb = discord.Embed(title=f"🎫 {pnl.get('name', 'Support')}", description=desc, color=C.BLURPLE)
        await ch.send(embed=emb, view=TicketCreateView(self.pid))
        await i.response.send_message(f"✅ Panel envoyé dans {ch.mention}!", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

async def update_realsy_activity(guild_id, user_id):
    """Met à jour la dernière activité d'un utilisateur avec le rôle Realsy"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT user_id FROM realsy_tracking WHERE guild_id=? AND user_id=?', 
                (guild_id, user_id)) as c:
                if await c.fetchone():
                    await db.execute('UPDATE realsy_tracking SET last_activity=?, warn_count=0 WHERE guild_id=? AND user_id=?',
                        (now().isoformat(), guild_id, user_id))
                    await db.commit()
    except:
        pass

@bot.event
async def on_ready():
    await db_init()
    bot.add_view(TicketControlView())
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM guild_config') as c:
                for row in await c.fetchall():
                    try:
                        data = json.loads(row[0]) if row[0] else {}
                        for pid in data.get('ticket_panels', {}):
                            bot.add_view(TicketCreateView(pid))
                    except: pass
    except: pass
    
    # Sync global des commandes
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées:")
        for cmd in synced:
            print(f"   - /{cmd.name}")
    except Exception as ex:
        print(f"❌ Erreur sync global: {ex}")
    
    # Lancer la tâche d'inactivité
    if not check_realsy_inactivity.is_running():
        check_realsy_inactivity.start()
    
    # Lancer la tâche des feeds sociaux
    if not check_social_feeds.is_running():
        check_social_feeds.start()
    
    # Lancer la tâche de vérification AFK automatique
    if not check_afk_automatic.is_running():
        check_afk_automatic.start()
    
    print(f"✅ {bot.user.name} v18 prêt!")
    print(f"🌐 Serveurs: {len(bot.guilds)}")
    print(f"📢 Vérification feeds sociaux toutes les 5 minutes")

@bot.tree.command(name="sync", description="🔄 Synchroniser les commandes (Admin)")
async def sync_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin requis", ephemeral=True)
    
    await i.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        cmd_list = "\n".join([f"• `/{c.name}`" for c in synced])
        await i.followup.send(f"✅ **{len(synced)} commandes synchronisées!**\n\n{cmd_list}", ephemeral=True)
    except Exception as ex:
        await i.followup.send(f"❌ Erreur: {ex}", ephemeral=True)

@bot.event
async def on_member_remove(m):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id, channel_id, claimed_by, answers FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (m.guild.id, m.id)) as c:
                tks = await c.fetchall()
        for tk in tks:
            ans = {}
            try: ans = json.loads(tk[3]) if tk[3] else {}
            except: pass
            ti = {'id': tk[0], 'user': m.id, 'claimed': tk[2] or 0, 'answers': ans}
            ch = m.guild.get_channel(tk[1])
            await send_ticket_log(m.guild, 'leave', m, ti)
            if ch:
                await ch.send(embed=discord.Embed(title="🚪 Utilisateur parti", description=f"**{m.display_name}** a quitté le serveur.", color=C.ORANGE))
    except: pass

@bot.event
async def on_member_join(m):
    try:
        c = await cfg(m.guild.id)
        if c.get('anti_newaccount'):
            days = c.get('newaccount_days', 7)
            age = (now() - m.created_at.replace(tzinfo=timezone.utc)).days
            if age < days:
                await send_log(m.guild, 'anti_newaccount', m, None, "Compte trop récent", f"Âge: {age} jour(s)")
                await m.kick(reason=f"Compte trop récent ({age} jours)")
    except: pass

async def relay_discord_message(msg):
    """Relay un message vers les serveurs qui suivent ce salon"""
    try:
        channel_id = str(msg.channel.id)
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, data FROM guild_config') as cursor:
                async for row in cursor:
                    guild_id, data_str = row
                    if guild_id == msg.guild.id:
                        continue
                    
                    try:
                        data = json.loads(data_str) if data_str else {}
                        feeds = data.get('ads_discord_feeds', [])
                        dest_channel_id = data.get('ads_discord_channel', 0)
                        
                        is_followed = any(f['channel_id'] == channel_id for f in feeds)
                        if not is_followed or not dest_channel_id:
                            continue
                        
                        dest_guild = bot.get_guild(guild_id)
                        if not dest_guild:
                            continue
                        dest_channel = dest_guild.get_channel(dest_channel_id)
                        if not dest_channel:
                            continue
                        
                        # ═══════════════ EMBED DISCORD RELAY PROFESSIONNEL ═══════════════
                        e = discord.Embed(color=0x5865F2)
                        
                        # Auteur avec le nom du serveur
                        e.set_author(
                            name=f"📡 DISCORD • {msg.guild.name}",
                            icon_url=msg.guild.icon.url if msg.guild.icon else "https://discord.com/assets/847541504914fd33810e70a0ea73177e.ico"
                        )
                        
                        # Thumbnail avec avatar de l'auteur
                        if msg.author.display_avatar:
                            e.set_thumbnail(url=msg.author.display_avatar.url)
                        
                        # Info du message
                        e.add_field(
                            name="👤 Auteur",
                            value=f"**{msg.author.display_name}**",
                            inline=True
                        )
                        e.add_field(
                            name="📍 Salon",
                            value=f"#{msg.channel.name}",
                            inline=True
                        )
                        
                        # Contenu du message
                        content = msg.content[:1500] if msg.content else ""
                        if content:
                            e.add_field(
                                name="💬 Message",
                                value=content,
                                inline=False
                            )
                        
                        # Images
                        if msg.attachments:
                            for att in msg.attachments[:1]:
                                if att.content_type and att.content_type.startswith('image'):
                                    e.set_image(url=att.url)
                                    break
                        
                        e.set_footer(
                            text=f"Discord • {msg.guild.name}",
                            icon_url="https://discord.com/assets/847541504914fd33810e70a0ea73177e.ico"
                        )
                        e.timestamp = msg.created_at
                        
                        await dest_channel.send(embed=e)
                        
                    except:
                        continue
    except:
        pass

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    
    # Relay Discord - Vérifier si ce salon est suivi par d'autres serveurs
    await relay_discord_message(msg)
    
    # Mise à jour activité Realsy
    await update_realsy_activity(msg.guild.id, msg.author.id)
    
    # ═══════════════ SALON DE RÉCUPÉRATION D'ACTIVITÉ ═══════════════
    try:
        c = await cfg(msg.guild.id)
        stat_cfg = c.get('stat_config', {})
        recovery_ch_id = stat_cfg.get('recovery_channel', 0)
        
        # Si le message est dans le salon de récupération
        if recovery_ch_id and msg.channel.id == recovery_ch_id:
            await handle_recovery_message(msg, stat_cfg)
            return  # Ne pas traiter le reste
    except:
        pass
    
    # ═══════════════ TRACKING ACTIVITÉ MEMBRE ═══════════════
    await track_member_message(msg)
    
    try:
        c = await cfg(msg.guild.id)
        ct = msg.content or ""
        chid = msg.channel.id
        gt = get_gif_type(msg)
        ag = c.get('image_allowed', [])
        iag = gt and gt in ag
        
        # Config salon spécifique
        chcf = c.get('channel_configs', {}).get(str(chid))
        if chcf and not (iag and chcf.get('gifs', True)):
            vio, _ = check_channel_cfg(msg, chcf)
            if vio:
                await msg.delete()
                return
        
        # Anti-phishing
        if c.get('anti_phishing'):
            f, d = check_phishing(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_phishing', msg.author, msg, "Lien de phishing détecté", f"`{d}`")
                await sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing", msg.guild)
                return
        
        # Anti-scam
        if c.get('anti_scam') and not await is_immune(msg.author, 'anti_scam'):
            f, p = check_scam(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_scam', msg.author, msg, "Message de scam détecté", f"`{p}`")
                await sanction(msg.author, c.get('scam_action', 'mute'), 60, "Scam", msg.guild)
                return
        
        # Anti-badwords
        if c.get('anti_badwords') and not await is_immune(msg.author, 'anti_badwords'):
            f, w = check_badwords(ct, c.get('badwords_list', []))
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_badwords', msg.author, msg, "Mot interdit détecté", f"`{w}`")
                return
        
        # Anti-invite
        if c.get('anti_invite'):
            f, inv = check_invite(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_invite', msg.author, msg, "Invitation Discord", f"`{inv}`")
                return
        
        # Anti-link
        if c.get('anti_link') and not iag:
            if chid not in c.get('link_allowed_channels', []):
                f, url = check_link(ct, c.get('link_whitelist', []))
                if f:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_link', msg.author, msg, "Lien non autorisé", f"`{url}`")
                    return
        
        # Anti-image
        if c.get('anti_image') and not await is_immune(msg.author, 'anti_image') and not iag:
            if chid not in c.get('image_allowed_channels', []):
                bl = check_image(msg, c.get('image_allowed', []))
                if bl:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_image', msg.author, msg, "Format non autorisé", f"`{', '.join(bl)}`")
                    return
        
        # Anti-spam
        if c.get('anti_spam') and not await is_immune(msg.author, 'anti_spam'):
            if await check_spam(msg, c.get('spam_max', 5), c.get('spam_interval', 5)):
                await msg.delete()
                await send_log(msg.guild, 'anti_spam', msg.author, msg, "Spam détecté", None)
                await sanction(msg.author, c.get('spam_action', 'mute'), 10, "Spam", msg.guild)
                return
        
        # Anti-caps
        if c.get('anti_caps') and not await is_immune(msg.author, 'anti_caps'):
            if check_caps(ct, c.get('caps_percent', 70)):
                await msg.delete()
                await send_log(msg.guild, 'anti_caps', msg.author, msg, "Trop de majuscules", None)
                return
    except: pass

# ═══════════════════════════════════════════════════════════════════════════════
#                              📋 COMMANDES SLASH
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Ouvrir le panneau de configuration")
async def configure_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Vous devez être administrateur", ephemeral=True)
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.embed(), view=v, ephemeral=True)

async def check_mod_perm(i, cmd_key):
    """Vérifie si l'utilisateur a la permission pour cette commande de modération"""
    c = await cfg(i.guild.id)
    role_id = c.get(cmd_key, 0)
    
    # Admins et owner ont toujours accès
    if i.user.guild_permissions.administrator or i.user.id == i.guild.owner_id:
        return True
    
    # Vérifier si l'utilisateur a le rôle configuré
    if role_id:
        role = i.guild.get_role(role_id)
        if role and role in i.user.roles:
            return True
    
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#                              ⚠️ WARN / UNWARN
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not await check_mod_perm(i, 'mod_warn_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if membre.id == i.user.id:
        return await i.response.send_message("❌ Vous ne pouvez pas vous warn vous-même", ephemeral=True)
    
    if membre.bot:
        return await i.response.send_message("❌ Vous ne pouvez pas warn un bot", ephemeral=True)
    
    if membre.top_role >= i.user.top_role and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Vous ne pouvez pas warn ce membre", ephemeral=True)
    
    # Enregistrer l'infraction
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, duration) VALUES(?,?,?,?,?,?)',
            (i.guild.id, membre.id, i.user.id, 'warn', raison, '')
        )
        await db.commit()
        # Compter les warns
        async with db.execute('SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type="warn"', (i.guild.id, membre.id)) as c:
            warn_count = (await c.fetchone())[0]
    
    # Créer l'embed
    e = discord.Embed(title="⚠️ Avertissement", color=C.YELLOW, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="📊 Total warns", value=str(warn_count), inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'warn', i.user, membre, raison, extra=f"Total warns: {warn_count}")

@bot.tree.command(name="unwarn", description="✅ Supprimer un avertissement d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez supprimer un warn")
async def unwarn_cmd(i: discord.Interaction, membre: discord.Member):
    if not await check_mod_perm(i, 'mod_warn_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    # Récupérer les warns (sans created_at pour éviter l'erreur)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, reason FROM infractions WHERE guild_id=? AND user_id=? AND type="warn" ORDER BY id DESC LIMIT 25',
            (i.guild.id, membre.id)
        ) as c:
            warns = await c.fetchall()
    
    if not warns:
        return await i.response.send_message(f"❌ {membre.mention} n'a aucun warn", ephemeral=True)
    
    # Créer les options
    opts = []
    for warn_id, reason in warns:
        label = f"#{warn_id} - {reason[:50]}{'...' if len(reason) > 50 else ''}"
        opts.append(discord.SelectOption(label=label[:100], value=str(warn_id)))
    
    e = discord.Embed(
        title=f"✅ Supprimer un warn de {membre.display_name}",
        description=f"Sélectionnez le warn à supprimer ({len(warns)} warn(s))",
        color=C.GREEN
    )
    e.set_thumbnail(url=membre.display_avatar.url)
    
    v = UnwarnSelectView(membre, opts)
    await i.response.send_message(embed=e, view=v, ephemeral=True)

class UnwarnSelectView(View):
    def __init__(self, membre, opts):
        super().__init__(timeout=120)
        self.add_item(UnwarnSelect(membre, opts))

class UnwarnSelect(Select):
    def __init__(self, membre, opts):
        super().__init__(placeholder="Sélectionner le warn à supprimer...", options=opts)
        self.membre = membre
    
    async def callback(self, i):
        warn_id = int(self.values[0])
        
        # Récupérer info du warn avant suppression
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT reason FROM infractions WHERE id=?', (warn_id,)) as c:
                row = await c.fetchone()
                reason = row[0] if row else "?"
            
            # Supprimer
            await db.execute('DELETE FROM infractions WHERE id=?', (warn_id,))
            await db.commit()
            
            # Compter les warns restants
            async with db.execute('SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type="warn"', (i.guild.id, self.membre.id)) as c:
                warn_count = (await c.fetchone())[0]
        
        e = discord.Embed(title="✅ Warn supprimé", color=C.GREEN, timestamp=now())
        e.add_field(name="👤 Membre", value=f"{self.membre.mention}", inline=True)
        e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
        e.add_field(name="📊 Warns restants", value=str(warn_count), inline=True)
        e.add_field(name="📝 Warn supprimé", value=reason[:1024], inline=False)
        
        await i.response.edit_message(embed=e, view=None)
        
        # Log
        await send_mod_log(i.guild, 'unwarn', i.user, self.membre, reason, extra=f"Warns restants: {warn_count}")

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔇 MUTE / UNMUTE
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="mute", description="🔇 Timeout un membre")
@app_commands.describe(membre="Le membre à mute", duree="La durée (nombre)", unite="L'unité de temps", raison="La raison du mute")
@app_commands.choices(unite=[
    app_commands.Choice(name="Minutes", value="minutes"),
    app_commands.Choice(name="Heures", value="heures"),
    app_commands.Choice(name="Jours", value="jours"),
    app_commands.Choice(name="Semaine (max)", value="semaine")
])
async def mute_cmd(i: discord.Interaction, membre: discord.Member, duree: int, unite: str, raison: str):
    if not await check_mod_perm(i, 'mod_mute_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if membre.id == i.user.id:
        return await i.response.send_message("❌ Vous ne pouvez pas vous mute vous-même", ephemeral=True)
    
    if membre.bot:
        return await i.response.send_message("❌ Vous ne pouvez pas mute un bot", ephemeral=True)
    
    if membre.top_role >= i.user.top_role and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Vous ne pouvez pas mute ce membre", ephemeral=True)
    
    # Calculer la durée
    duree = max(1, duree)
    if unite == "minutes":
        delta = timedelta(minutes=duree)
        dur_txt = f"{duree} minute(s)"
    elif unite == "heures":
        delta = timedelta(hours=duree)
        dur_txt = f"{duree} heure(s)"
    elif unite == "jours":
        duree = min(duree, 7)
        delta = timedelta(days=duree)
        dur_txt = f"{duree} jour(s)"
    else:
        delta = timedelta(weeks=1)
        dur_txt = "1 semaine"
    
    if delta > timedelta(days=7):
        delta = timedelta(days=7)
        dur_txt = "7 jours (maximum)"
    
    # Appliquer le timeout
    try:
        await membre.timeout(delta, reason=f"{raison} - Par {i.user.name}")
    except discord.Forbidden:
        return await i.response.send_message("❌ Je ne peux pas mute ce membre (permissions)", ephemeral=True)
    except Exception as ex:
        return await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    # Enregistrer l'infraction
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, duration) VALUES(?,?,?,?,?,?)',
            (i.guild.id, membre.id, i.user.id, 'mute', raison, dur_txt)
        )
        await db.commit()
    
    # Créer l'embed
    e = discord.Embed(title="🔇 Membre mute", color=C.ORANGE, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="⏱️ Durée", value=dur_txt, inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'mute', i.user, membre, raison, duration=dur_txt)

@bot.tree.command(name="unmute", description="🔊 Retirer le mute d'un membre")
@app_commands.describe(membre="Le membre à unmute", raison="La raison du unmute (optionnel)")
async def unmute_cmd(i: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    if not await check_mod_perm(i, 'mod_mute_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if not membre.is_timed_out():
        return await i.response.send_message(f"❌ {membre.mention} n'est pas mute", ephemeral=True)
    
    try:
        await membre.timeout(None, reason=f"Unmute par {i.user.name}: {raison}")
    except discord.Forbidden:
        return await i.response.send_message("❌ Je ne peux pas unmute ce membre", ephemeral=True)
    except Exception as ex:
        return await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    e = discord.Embed(title="🔊 Membre unmute", color=C.GREEN, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'unmute', i.user, membre, raison)

# ═══════════════════════════════════════════════════════════════════════════════
#                              📋 INFRACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="infractions", description="📋 Voir les infractions d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez voir les infractions")
async def infractions_cmd(i: discord.Interaction, membre: discord.Member):
    if not await check_mod_perm(i, 'mod_infractions_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    # Récupérer les infractions (sans ORDER BY created_at pour éviter erreur si colonne n'existe pas)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT type, reason, duration, mod_id FROM infractions WHERE guild_id=? AND user_id=? ORDER BY id DESC',
            (i.guild.id, membre.id)
        ) as c:
            rows = await c.fetchall()
    
    # Calculer le temps sur le serveur
    joined = membre.joined_at
    if joined:
        days_on_server = (now() - joined.replace(tzinfo=timezone.utc)).days
        time_on_server = f"{days_on_server} jour(s)"
    else:
        time_on_server = "Inconnu"
    
    # Compter les types
    warns = sum(1 for r in rows if r[0] == 'warn')
    mutes = sum(1 for r in rows if r[0] == 'mute')
    
    # Créer l'embed
    e = discord.Embed(title=f"📋 Infractions de {membre.display_name}", color=C.BLUE, timestamp=now())
    e.set_thumbnail(url=membre.display_avatar.url)
    
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="📅 Sur le serveur", value=time_on_server, inline=True)
    e.add_field(name="📊 Total", value=str(len(rows)), inline=True)
    
    e.add_field(name="⚠️ Warns", value=str(warns), inline=True)
    e.add_field(name="🔇 Mutes", value=str(mutes), inline=True)
    
    # Statut mute actuel
    if membre.is_timed_out():
        timeout_until = membre.timed_out_until
        if timeout_until:
            e.add_field(name="🔇 Mute actif", value=f"Jusqu'à <t:{int(timeout_until.timestamp())}:R>", inline=True)
        else:
            e.add_field(name="\u200b", value="\u200b", inline=True)
    else:
        e.add_field(name="\u200b", value="\u200b", inline=True)
    
    if rows:
        inf_lines = []
        for j, (typ, reason, duration, mod_id) in enumerate(rows[:10], 1):
            emoji = "⚠️" if typ == "warn" else "🔇"
            dur_txt = f" ({duration})" if duration else ""
            reason_short = reason[:40] + "..." if len(reason) > 40 else reason
            inf_lines.append(f"`{j}.` {emoji} **{typ.upper()}**{dur_txt}\n└ {reason_short}")
        
        e.add_field(name="📜 Historique (10 dernières)", value="\n".join(inf_lines)[:1024], inline=False)
    else:
        e.add_field(name="📜 Historique", value="✅ Aucune infraction", inline=False)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'infractions', i.user, membre, extra=f"Total: {len(rows)} infractions")

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎭 RELLSEAS COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="rellseas", description="🎭 Donner ou retirer le rôle Realsy à un membre")
@app_commands.describe(membre="Le membre", action="Donner ou retirer le rôle")
@app_commands.choices(action=[
    app_commands.Choice(name="Donner le rôle", value="add"),
    app_commands.Choice(name="Retirer le rôle", value="remove")
])
async def rellseas_cmd(i: discord.Interaction, membre: discord.Member, action: str):
    c = await cfg(i.guild.id)
    
    # Vérifier si l'utilisateur est autorisé
    if i.user.id != c.get('rellseas_user', 0) and not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Vous n'êtes pas autorisé à utiliser cette commande", ephemeral=True)
    
    # Vérifier si le rôle est configuré
    role = i.guild.get_role(c.get('rellseas_role', 0))
    if not role:
        return await i.response.send_message("❌ Le rôle Realsy n'est pas configuré", ephemeral=True)
    
    if action == "add":
        if role in membre.roles:
            return await i.response.send_message(f"❌ {membre.mention} a déjà le rôle {role.mention}", ephemeral=True)
        
        try:
            await membre.add_roles(role, reason=f"RellSeas par {i.user.name}")
            
            # Enregistrer l'activité initiale
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''INSERT OR REPLACE INTO realsy_tracking 
                    (guild_id, user_id, last_activity, warn_count) VALUES (?, ?, ?, 0)''',
                    (i.guild.id, membre.id, now().isoformat()))
                await db.commit()
            
            e = discord.Embed(title="🎭 Rôle Realsy donné", color=C.GREEN, timestamp=now())
            e.add_field(name="👤 Membre", value=f"{membre.mention}", inline=True)
            e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
            e.set_thumbnail(url=membre.display_avatar.url)
            await i.response.send_message(embed=e)
            
            # Log
            log_ch = i.guild.get_channel(c.get('rellseas_log_channel', 0))
            if log_ch:
                await log_ch.send(embed=e)
                
        except discord.Forbidden:
            return await i.response.send_message("❌ Je ne peux pas donner ce rôle", ephemeral=True)
    
    else:  # remove
        if role not in membre.roles:
            return await i.response.send_message(f"❌ {membre.mention} n'a pas le rôle {role.mention}", ephemeral=True)
        
        try:
            await membre.remove_roles(role, reason=f"RellSeas retiré par {i.user.name}")
            
            # Supprimer du tracking
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                    (i.guild.id, membre.id))
                await db.commit()
            
            e = discord.Embed(title="🎭 Rôle Realsy retiré", color=C.RED, timestamp=now())
            e.add_field(name="👤 Membre", value=f"{membre.mention}", inline=True)
            e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
            e.set_thumbnail(url=membre.display_avatar.url)
            await i.response.send_message(embed=e)
            
            # Log
            log_ch = i.guild.get_channel(c.get('rellseas_log_channel', 0))
            if log_ch:
                await log_ch.send(embed=e)
                
        except discord.Forbidden:
            return await i.response.send_message("❌ Je ne peux pas retirer ce rôle", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💡 SUGGESTION COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

suggestion_cooldowns = {}

@bot.tree.command(name="suggestion", description="💡 Proposer une suggestion")
@app_commands.describe(titre="Titre de votre suggestion", proposition="Décrivez votre suggestion en détail")
async def suggestion_cmd(i: discord.Interaction, titre: str, proposition: str):
    c = await cfg(i.guild.id)
    
    # Vérifier le rôle
    role_id = c.get('suggestion_role', 0)
    if role_id:
        role = i.guild.get_role(role_id)
        if role and role not in i.user.roles:
            return await i.response.send_message(f"❌ Vous devez avoir le rôle {role.mention}", ephemeral=True)
    
    # Vérifier le salon
    sugg_ch = i.guild.get_channel(c.get('suggestion_channel', 0))
    if not sugg_ch:
        return await i.response.send_message("❌ Le salon des suggestions n'est pas configuré", ephemeral=True)
    
    # Vérifier le cooldown
    cooldown_key = (i.guild.id, i.user.id)
    cd_duration = c.get('suggestion_cooldown', 1)
    cd_unit = c.get('suggestion_cooldown_unit', 'jours')
    
    if cd_unit == 'semaines':
        cd_seconds = cd_duration * 7 * 24 * 3600
    else:
        cd_seconds = cd_duration * 24 * 3600
    
    if cooldown_key in suggestion_cooldowns:
        last_time = suggestion_cooldowns[cooldown_key]
        elapsed = (now() - last_time).total_seconds()
        if elapsed < cd_seconds:
            remaining = cd_seconds - elapsed
            days = int(remaining // 86400)
            hours = int((remaining % 86400) // 3600)
            return await i.response.send_message(
                f"⏱️ Attendez encore **{days}j {hours}h**",
                ephemeral=True
            )
    
    # Créer un bel embed de suggestion
    e = discord.Embed(color=C.BLURPLE, timestamp=now())
    e.set_author(name="💡 Nouvelle Suggestion", icon_url=i.guild.icon.url if i.guild.icon else None)
    
    e.add_field(name="📋 Titre", value=f"```{titre[:100]}```", inline=False)
    e.add_field(name="📝 Proposition", value=proposition[:1000], inline=False)
    
    e.add_field(name="👤 Auteur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="🆔 ID", value=f"`{i.user.id}`", inline=True)
    e.add_field(name="📅 Date", value=f"<t:{int(now().timestamp())}:R>", inline=True)
    
    e.set_thumbnail(url=i.user.display_avatar.url)
    e.set_footer(text="Votez ci-dessous! ✅ Pour | 🟠 Neutre | ❌ Contre")
    
    # Envoyer
    msg = await sugg_ch.send(embed=e)
    
    # Ajouter les réactions
    await msg.add_reaction("✅")
    await msg.add_reaction("🟠")
    await msg.add_reaction("❌")
    
    # Enregistrer le cooldown
    suggestion_cooldowns[cooldown_key] = now()
    
    # Stocker pour le tracking
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO suggestions (guild_id, message_id, user_id, title) VALUES (?, ?, ?, ?)',
            (i.guild.id, msg.id, i.user.id, titre))
        await db.commit()
    
    # Confirmation
    confirm = discord.Embed(title="✅ Suggestion envoyée!", color=C.GREEN)
    confirm.description = f"Votre suggestion a été publiée dans {sugg_ch.mention}"
    confirm.add_field(name="📋 Titre", value=titre[:100], inline=False)
    await i.response.send_message(embed=confirm, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔄 TRADE COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

trade_cooldowns = {}

@bot.tree.command(name="trade", description="🔄 Créer une annonce d'échange")
async def trade_cmd(i: discord.Interaction):
    c = await cfg(i.guild.id)
    
    # Vérifier le rôle
    role_id = c.get('trade_role', 0)
    if role_id:
        role = i.guild.get_role(role_id)
        if role and role not in i.user.roles:
            return await i.response.send_message(f"❌ Vous devez avoir le rôle {role.mention}", ephemeral=True)
    
    # Vérifier le salon
    trade_ch = i.guild.get_channel(c.get('trade_channel', 0))
    if not trade_ch:
        return await i.response.send_message("❌ Le salon des trades n'est pas configuré", ephemeral=True)
    
    # Vérifier le cooldown
    cooldown_key = (i.guild.id, i.user.id)
    cd_duration = c.get('trade_cooldown', 1)
    cd_unit = c.get('trade_cooldown_unit', 'heures')
    
    if cd_unit == 'secondes':
        cd_seconds = cd_duration
    elif cd_unit == 'minutes':
        cd_seconds = cd_duration * 60
    elif cd_unit == 'heures':
        cd_seconds = cd_duration * 3600
    elif cd_unit == 'jours':
        cd_seconds = cd_duration * 86400
    elif cd_unit == 'semaines':
        cd_seconds = cd_duration * 604800
    else:
        cd_seconds = cd_duration * 3600
    
    if cooldown_key in trade_cooldowns:
        last_time = trade_cooldowns[cooldown_key]
        elapsed = (now() - last_time).total_seconds()
        if elapsed < cd_seconds:
            remaining = cd_seconds - elapsed
            if remaining >= 86400:
                time_txt = f"{int(remaining // 86400)}j {int((remaining % 86400) // 3600)}h"
            elif remaining >= 3600:
                time_txt = f"{int(remaining // 3600)}h {int((remaining % 3600) // 60)}min"
            elif remaining >= 60:
                time_txt = f"{int(remaining // 60)}min {int(remaining % 60)}s"
            else:
                time_txt = f"{int(remaining)}s"
            return await i.response.send_message(f"⏱️ Attendez encore **{time_txt}**", ephemeral=True)
    
    # Afficher le menu de création
    v = TradeBuilderView(i.user, i.guild, i.channel, trade_ch)
    e = v.get_embed()
    await i.response.send_message(embed=e, view=v, ephemeral=True)

class TradeBuilderView(View):
    def __init__(self, user, guild, channel, trade_ch):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.channel = channel
        self.trade_ch = trade_ch
        self.jeu = ""
        self.je_donne = []
        self.je_veux = []
        self.texte_donne = ""
        self.texte_veux = ""
        
        # Ajouter les selects d'emojis si le serveur en a
        emojis = list(guild.emojis)[:25]
        if emojis:
            self.add_item(TradeEmojiGiveSelect(self, emojis))
            self.add_item(TradeEmojiWantSelect(self, emojis))
    
    def get_embed(self):
        e = discord.Embed(title="🔄 Créer un Trade", color=C.PURPLE)
        
        # Construire l'affichage
        donne_display = " ".join(self.je_donne) + (" " + self.texte_donne if self.texte_donne else "")
        veux_display = " ".join(self.je_veux) + (" " + self.texte_veux if self.texte_veux else "")
        
        e.add_field(name="🎮 Jeu", value=self.jeu if self.jeu else "*Non défini*", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        
        e.add_field(name="📤 Je DONNE", value=donne_display.strip() if donne_display.strip() else "*Rien sélectionné*", inline=True)
        e.add_field(name="➡️", value="🔄", inline=True)
        e.add_field(name="📥 Je VEUX", value=veux_display.strip() if veux_display.strip() else "*Rien sélectionné*", inline=True)
        
        # Instructions
        if self.jeu and (donne_display.strip() or veux_display.strip()):
            e.set_footer(text="✅ Cliquez sur Confirmer pour continuer")
            e.color = C.GREEN
        else:
            e.set_footer(text="1️⃣ Définissez le jeu • 2️⃣ Sélectionnez/écrivez vos items • 3️⃣ Confirmez")
        
        return e
    
    @discord.ui.button(label="🎮 Définir le Jeu", style=discord.ButtonStyle.primary, row=2)
    async def set_game(self, i, b):
        await i.response.send_modal(TradeGameModal(self))
    
    @discord.ui.button(label="✏️ Texte Donne", style=discord.ButtonStyle.secondary, row=2)
    async def set_text_give(self, i, b):
        await i.response.send_modal(TradeTextGiveModal(self))
    
    @discord.ui.button(label="✏️ Texte Veux", style=discord.ButtonStyle.secondary, row=2)
    async def set_text_want(self, i, b):
        await i.response.send_modal(TradeTextWantModal(self))
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.success, row=3)
    async def confirm(self, i, b):
        donne_display = " ".join(self.je_donne) + (" " + self.texte_donne if self.texte_donne else "")
        veux_display = " ".join(self.je_veux) + (" " + self.texte_veux if self.texte_veux else "")
        
        if not self.jeu:
            return await i.response.send_message("❌ Définissez le jeu d'abord!", ephemeral=True)
        if not donne_display.strip() and not veux_display.strip():
            return await i.response.send_message("❌ Ajoutez au moins un item!", ephemeral=True)
        
        # Demander la preuve
        e = discord.Embed(title="📸 Preuve requise", color=C.ORANGE)
        e.description = "**Envoyez une image** de preuve dans les **3 minutes**."
        await i.response.edit_message(embed=e, view=None)
        
        # Attendre l'image
        def check(m):
            return m.author.id == self.user.id and m.channel.id == self.channel.id and m.attachments
        
        try:
            msg = await bot.wait_for('message', timeout=180.0, check=check)
            
            attachment = msg.attachments[0]
            image_data = await attachment.read()
            image_filename = attachment.filename
            
            try:
                await msg.delete()
            except:
                pass
            
        except asyncio.TimeoutError:
            return await i.followup.send("❌ Temps écoulé!", ephemeral=True)
        
        # Créer le post professionnel
        e = discord.Embed(color=C.GOLD)
        e.set_author(name=f"🔄 TRADE • {self.jeu.upper()}", icon_url=self.user.display_avatar.url)
        
        # Affichage horizontal bien propre
        e.add_field(
            name="📤 DONNE",
            value=donne_display.strip() if donne_display.strip() else "—",
            inline=True
        )
        e.add_field(
            name="⚡",
            value="🔄",
            inline=True
        )
        e.add_field(
            name="📥 VEUT",
            value=veux_display.strip() if veux_display.strip() else "—",
            inline=True
        )
        
        # Infos trader compactes
        e.add_field(
            name="",
            value=f"👤 {self.user.mention} • `{self.user.id}` • <t:{int(now().timestamp())}:R>",
            inline=False
        )
        
        # Image en petit (thumbnail en haut à droite)
        image_file = discord.File(io.BytesIO(image_data), filename=image_filename)
        e.set_thumbnail(url=f"attachment://{image_filename}")
        
        e.set_footer(text="✅ Intéressé? Réagissez! • 💬 MP pour négocier")
        
        # Envoyer
        trade_msg = await self.trade_ch.send(embed=e, file=image_file)
        await trade_msg.add_reaction("✅")
        await trade_msg.add_reaction("💬")
        
        trade_cooldowns[(self.guild.id, self.user.id)] = now()
        
        confirm = discord.Embed(title="✅ Trade publié!", color=C.GREEN)
        confirm.description = f"Votre offre a été publiée dans {self.trade_ch.mention}"
        await i.followup.send(embed=confirm, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger, row=3)
    async def cancel(self, i, b):
        await i.response.edit_message(embed=discord.Embed(title="❌ Trade annulé", color=C.RED), view=None)

class TradeEmojiGiveSelect(Select):
    def __init__(self, parent, emojis):
        self.parent = parent
        self.emoji_map = {}  # Stocker le mapping id -> format string
        options = []
        for e in emojis[:25]:
            # Stocker le format complet de l'emoji
            if e.animated:
                self.emoji_map[str(e.id)] = f"<a:{e.name}:{e.id}>"
            else:
                self.emoji_map[str(e.id)] = f"<:{e.name}:{e.id}>"
            options.append(discord.SelectOption(
                label=e.name[:25],
                value=str(e.id),
                emoji=e
            ))
        super().__init__(
            placeholder="📤 Emojis à DONNER...",
            options=options,
            min_values=0,
            max_values=min(len(options), 10),
            row=0
        )
    
    async def callback(self, i):
        self.parent.je_donne = []
        for emoji_id in self.values:
            # Utiliser le format stocké directement
            if emoji_id in self.emoji_map:
                self.parent.je_donne.append(self.emoji_map[emoji_id])
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeEmojiWantSelect(Select):
    def __init__(self, parent, emojis):
        self.parent = parent
        self.emoji_map = {}  # Stocker le mapping id -> format string
        options = []
        for e in emojis[:25]:
            # Stocker le format complet de l'emoji
            if e.animated:
                self.emoji_map[str(e.id)] = f"<a:{e.name}:{e.id}>"
            else:
                self.emoji_map[str(e.id)] = f"<:{e.name}:{e.id}>"
            options.append(discord.SelectOption(
                label=e.name[:25],
                value=str(e.id),
                emoji=e
            ))
        super().__init__(
            placeholder="📥 Emojis que je VEUX...",
            options=options,
            min_values=0,
            max_values=min(len(options), 10),
            row=1
        )
    
    async def callback(self, i):
        self.parent.je_veux = []
        for emoji_id in self.values:
            # Utiliser le format stocké directement
            if emoji_id in self.emoji_map:
                self.parent.je_veux.append(self.emoji_map[emoji_id])
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeGameModal(Modal, title="🎮 Définir le Jeu"):
    jeu = TextInput(label="Nom du jeu", placeholder="Ex: Rocket League, Fortnite, GTA RP...", max_length=50)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.jeu = self.jeu.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeTextGiveModal(Modal, title="📤 Ce que je DONNE (texte)"):
    texte = TextInput(label="Description", placeholder="Ex: 500 crédits, Voiture TW...", style=discord.TextStyle.paragraph, max_length=150, required=False)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.texte_donne = self.texte.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeTextWantModal(Modal, title="📥 Ce que je VEUX (texte)"):
    texte = TextInput(label="Description", placeholder="Ex: Octane TW, 1000 crédits...", style=discord.TextStyle.paragraph, max_length=150, required=False)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.texte_veux = self.texte.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

# ═══════════════════════════════════════════════════════════════════════════════
#                              📊 COMMANDE /STAT - STATISTIQUES MEMBRE
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="stat", description="📊 Voir les statistiques d'activité d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez voir les stats (vous par défaut)")
async def stat_cmd(i: discord.Interaction, membre: discord.Member = None):
    target = membre or i.user
    
    if target.bot:
        return await i.response.send_message("❌ Les bots n'ont pas de statistiques", ephemeral=True)
    
    await i.response.defer()
    
    # Générer les stats pour 7 jours par défaut
    stats = await get_member_stats(i.guild, target, 7)
    embed, file = await create_stat_embed(i.guild, target, stats, 7)
    
    v = StatMemberView(i.user, i.guild, target)
    
    if file:
        await i.followup.send(embed=embed, file=file, view=v)
    else:
        await i.followup.send(embed=embed, view=v)

class StatMemberView(View):
    def __init__(self, user, guild, target):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.target = target
        self.period = 7
    
    @discord.ui.button(label="📅 7 Jours", style=discord.ButtonStyle.primary, disabled=True)
    async def btn_7d(self, i, b):
        self.period = 7
        self.btn_7d.disabled = True
        self.btn_30d.disabled = False
        await self.refresh(i)
    
    @discord.ui.button(label="📅 30 Jours", style=discord.ButtonStyle.secondary)
    async def btn_30d(self, i, b):
        self.period = 30
        self.btn_7d.disabled = False
        self.btn_30d.disabled = True
        await self.refresh(i)
    
    @discord.ui.button(label="📈 Graphique Détaillé", style=discord.ButtonStyle.success, row=1)
    async def btn_graph(self, i, b):
        await i.response.defer()
        img = await generate_detailed_stat_graph(self.guild, self.target, self.period)
        if img:
            file = discord.File(img, filename="stats_detailed.png")
            e = discord.Embed(
                title=f"📊 Statistiques Détaillées - {self.target.display_name}",
                color=C.PURPLE
            )
            e.set_image(url="attachment://stats_detailed.png")
            e.set_footer(text=f"Période: {self.period} jours • {self.guild.name}")
            await i.followup.send(embed=e, file=file, ephemeral=True)
        else:
            await i.followup.send("❌ Pas assez de données pour générer un graphique", ephemeral=True)
    
    async def refresh(self, i):
        await i.response.defer()
        stats = await get_member_stats(self.guild, self.target, self.period)
        embed, file = await create_stat_embed(self.guild, self.target, stats, self.period)
        
        if file:
            await i.message.delete()
            await i.followup.send(embed=embed, file=file, view=self)
        else:
            await i.message.edit(embed=embed, view=self)

async def get_member_stats(guild, member, days):
    """Récupère les statistiques d'un membre sur une période donnée"""
    stats = {
        'total_messages': 0,
        'total_vocal_time': 0,
        'channels_messages': {},  # {channel_id: count}
        'channels_vocal': {},  # {channel_id: duration}
        'messages_per_day': {},  # {date: count}
        'vocal_per_day': {},  # {date: duration}
        'most_popular_message': None,
        'first_activity': None,
        'last_activity': None
    }
    
    try:
        cutoff = now() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Récupérer les messages
            async with db.execute('''
                SELECT channel_id, message_id, created_at FROM member_activity 
                WHERE guild_id=? AND user_id=? AND activity_type='message' AND created_at >= ?
                ORDER BY created_at ASC
            ''', (guild.id, member.id, cutoff_str)) as cursor:
                async for row in cursor:
                    ch_id, msg_id, created_at = row
                    stats['total_messages'] += 1
                    
                    # Par salon
                    stats['channels_messages'][ch_id] = stats['channels_messages'].get(ch_id, 0) + 1
                    
                    # Par jour
                    try:
                        dt = datetime.fromisoformat(created_at)
                        date_key = dt.strftime('%Y-%m-%d')
                        stats['messages_per_day'][date_key] = stats['messages_per_day'].get(date_key, 0) + 1
                        
                        if not stats['first_activity'] or dt < stats['first_activity']:
                            stats['first_activity'] = dt
                        if not stats['last_activity'] or dt > stats['last_activity']:
                            stats['last_activity'] = dt
                    except:
                        pass
            
            # Récupérer les sessions vocales
            async with db.execute('''
                SELECT channel_id, duration, created_at FROM member_activity 
                WHERE guild_id=? AND user_id=? AND activity_type='vocal' AND created_at >= ?
                ORDER BY created_at ASC
            ''', (guild.id, member.id, cutoff_str)) as cursor:
                async for row in cursor:
                    ch_id, duration, created_at = row
                    stats['total_vocal_time'] += duration or 0
                    
                    # Par salon
                    stats['channels_vocal'][ch_id] = stats['channels_vocal'].get(ch_id, 0) + (duration or 0)
                    
                    # Par jour
                    try:
                        dt = datetime.fromisoformat(created_at)
                        date_key = dt.strftime('%Y-%m-%d')
                        stats['vocal_per_day'][date_key] = stats['vocal_per_day'].get(date_key, 0) + (duration or 0)
                        
                        if not stats['first_activity'] or dt < stats['first_activity']:
                            stats['first_activity'] = dt
                        if not stats['last_activity'] or dt > stats['last_activity']:
                            stats['last_activity'] = dt
                    except:
                        pass
        
        # Trouver le message le plus populaire (avec le plus de réactions)
        # On cherche dans les derniers messages du membre
        if stats['channels_messages']:
            top_channel_id = max(stats['channels_messages'], key=stats['channels_messages'].get)
            channel = guild.get_channel(top_channel_id)
            if channel:
                try:
                    async for msg in channel.history(limit=100):
                        if msg.author.id == member.id:
                            reaction_count = sum(r.count for r in msg.reactions) if msg.reactions else 0
                            if reaction_count > 0:
                                if not stats['most_popular_message'] or reaction_count > stats['most_popular_message']['reactions']:
                                    stats['most_popular_message'] = {
                                        'content': msg.content[:100] + "..." if len(msg.content) > 100 else msg.content,
                                        'reactions': reaction_count,
                                        'url': msg.jump_url
                                    }
                except:
                    pass
                    
    except Exception as ex:
        print(f"Erreur get_member_stats: {ex}")
    
    return stats

async def create_stat_embed(guild, member, stats, days):
    """Crée l'embed des statistiques avec graphique"""
    e = discord.Embed(
        title=f"📊 Statistiques de {member.display_name}",
        color=C.PURPLE
    )
    e.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
    
    # Période
    e.description = f"**Période:** {days} derniers jours"
    
    # Messages
    e.add_field(
        name="💬 Messages",
        value=f"**{stats['total_messages']}** messages envoyés",
        inline=True
    )
    
    # Temps vocal
    vocal_time = stats['total_vocal_time']
    if vocal_time >= 3600:
        time_str = f"{vocal_time // 3600}h {(vocal_time % 3600) // 60}min"
    elif vocal_time >= 60:
        time_str = f"{vocal_time // 60}min {vocal_time % 60}s"
    else:
        time_str = f"{vocal_time}s"
    
    e.add_field(
        name="🔊 Temps en vocal",
        value=f"**{time_str}**",
        inline=True
    )
    
    # Moyenne par jour
    avg_messages = stats['total_messages'] / days if days > 0 else 0
    e.add_field(
        name="📈 Moyenne/jour",
        value=f"**{avg_messages:.1f}** msg/jour",
        inline=True
    )
    
    # Salon écrit le plus actif
    if stats['channels_messages']:
        top_ch_id = max(stats['channels_messages'], key=stats['channels_messages'].get)
        top_ch = guild.get_channel(top_ch_id)
        top_count = stats['channels_messages'][top_ch_id]
        e.add_field(
            name="📝 Salon écrit favoris",
            value=f"{top_ch.mention if top_ch else 'Inconnu'}\n({top_count} messages)",
            inline=True
        )
    else:
        e.add_field(name="📝 Salon écrit favoris", value="*Aucune donnée*", inline=True)
    
    # Salon vocal le plus utilisé
    if stats['channels_vocal']:
        top_vc_id = max(stats['channels_vocal'], key=stats['channels_vocal'].get)
        top_vc = guild.get_channel(top_vc_id)
        top_duration = stats['channels_vocal'][top_vc_id]
        if top_duration >= 3600:
            dur_str = f"{top_duration // 3600}h {(top_duration % 3600) // 60}min"
        elif top_duration >= 60:
            dur_str = f"{top_duration // 60}min"
        else:
            dur_str = f"{top_duration}s"
        e.add_field(
            name="🎤 Salon vocal favoris",
            value=f"{top_vc.name if top_vc else 'Inconnu'}\n({dur_str})",
            inline=True
        )
    else:
        e.add_field(name="🎤 Salon vocal favoris", value="*Aucune donnée*", inline=True)
    
    # Dernière activité
    if stats['last_activity']:
        e.add_field(
            name="🕐 Dernière activité",
            value=f"<t:{int(stats['last_activity'].timestamp())}:R>",
            inline=True
        )
    else:
        e.add_field(name="🕐 Dernière activité", value="*Inconnue*", inline=True)
    
    # Message le plus populaire
    if stats['most_popular_message']:
        mp = stats['most_popular_message']
        e.add_field(
            name=f"⭐ Message populaire ({mp['reactions']} réactions)",
            value=f"*\"{mp['content']}\"*\n[Voir le message]({mp['url']})",
            inline=False
        )
    
    # Générer le graphique
    img = await generate_stat_graph(stats, days, member.display_name)
    file = None
    if img:
        file = discord.File(img, filename="stats.png")
        e.set_image(url="attachment://stats.png")
    
    e.set_footer(text=f"{guild.name} • /stat", icon_url=guild.icon.url if guild.icon else None)
    e.timestamp = now()
    
    return e, file

async def generate_stat_graph(stats, days, username):
    """Génère un graphique des statistiques"""
    try:
        if not stats['messages_per_day'] and not stats['vocal_per_day']:
            return None
        
        # Préparer les données pour tous les jours de la période
        dates = []
        messages = []
        vocal = []
        
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            dates.append(dt.strftime('%d/%m'))
            messages.append(stats['messages_per_day'].get(date_key, 0))
            vocal.append(stats['vocal_per_day'].get(date_key, 0) / 60)  # Convertir en minutes
        
        # Créer le graphique
        fig, ax1 = plt.subplots(figsize=(12, 5))
        fig.patch.set_facecolor('#2f3136')
        ax1.set_facecolor('#36393f')
        
        # Barres pour les messages
        x = range(len(dates))
        bars = ax1.bar([i - 0.2 for i in x], messages, 0.4, label='Messages', color='#5865F2', alpha=0.8)
        ax1.set_xlabel('Date', color='white', fontsize=10)
        ax1.set_ylabel('Messages', color='#5865F2', fontsize=10)
        ax1.tick_params(axis='y', labelcolor='#5865F2')
        ax1.tick_params(axis='x', colors='white')
        
        # Deuxième axe pour le vocal
        ax2 = ax1.twinx()
        bars2 = ax2.bar([i + 0.2 for i in x], vocal, 0.4, label='Vocal (min)', color='#57F287', alpha=0.8)
        ax2.set_ylabel('Minutes en vocal', color='#57F287', fontsize=10)
        ax2.tick_params(axis='y', labelcolor='#57F287')
        
        # Style
        ax1.set_xticks(x)
        ax1.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        ax1.spines['bottom'].set_color('white')
        ax1.spines['left'].set_color('#5865F2')
        ax1.spines['top'].set_visible(False)
        ax2.spines['right'].set_color('#57F287')
        ax2.spines['top'].set_visible(False)
        
        # Titre
        plt.title(f'📊 Activité de {username}', color='white', fontsize=14, fontweight='bold', pad=15)
        
        # Légende
        fig.legend(loc='upper right', bbox_to_anchor=(0.98, 0.98), facecolor='#36393f', edgecolor='white', labelcolor='white')
        
        plt.tight_layout()
        
        # Sauvegarder
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
        buf.seek(0)
        plt.close(fig)
        
        return buf
        
    except Exception as ex:
        print(f"Erreur génération graphique: {ex}")
        return None

async def generate_detailed_stat_graph(guild, member, days):
    """Génère un graphique détaillé avec plusieurs visualisations"""
    try:
        stats = await get_member_stats(guild, member, days)
        
        if not stats['total_messages'] and not stats['total_vocal_time']:
            return None
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.patch.set_facecolor('#2f3136')
        
        # 1. Camembert des salons écrits (haut gauche)
        ax1 = axes[0, 0]
        ax1.set_facecolor('#2f3136')
        
        if stats['channels_messages']:
            # Top 5 salons
            sorted_channels = sorted(stats['channels_messages'].items(), key=lambda x: x[1], reverse=True)[:5]
            labels = []
            sizes = []
            for ch_id, count in sorted_channels:
                ch = guild.get_channel(ch_id)
                labels.append(f"#{ch.name[:15]}" if ch else f"#{ch_id}")
                sizes.append(count)
            
            colors = ['#5865F2', '#57F287', '#FEE75C', '#ED4245', '#9B59B6']
            ax1.pie(sizes, labels=labels, colors=colors[:len(sizes)], autopct='%1.1f%%',
                   textprops={'color': 'white', 'fontsize': 9})
            ax1.set_title('📝 Top Salons Écrits', color='white', fontsize=12, fontweight='bold')
        else:
            ax1.text(0.5, 0.5, 'Aucune donnée', ha='center', va='center', color='white', fontsize=12)
            ax1.set_title('📝 Top Salons Écrits', color='white', fontsize=12, fontweight='bold')
        
        # 2. Camembert des salons vocaux (haut droit)
        ax2 = axes[0, 1]
        ax2.set_facecolor('#2f3136')
        
        if stats['channels_vocal']:
            sorted_vocal = sorted(stats['channels_vocal'].items(), key=lambda x: x[1], reverse=True)[:5]
            labels = []
            sizes = []
            for ch_id, duration in sorted_vocal:
                ch = guild.get_channel(ch_id)
                labels.append(f"🔊 {ch.name[:15]}" if ch else f"🔊 {ch_id}")
                sizes.append(duration)
            
            colors = ['#57F287', '#5865F2', '#FEE75C', '#ED4245', '#9B59B6']
            ax2.pie(sizes, labels=labels, colors=colors[:len(sizes)], autopct='%1.1f%%',
                   textprops={'color': 'white', 'fontsize': 9})
            ax2.set_title('🎤 Top Salons Vocaux', color='white', fontsize=12, fontweight='bold')
        else:
            ax2.text(0.5, 0.5, 'Aucune donnée', ha='center', va='center', color='white', fontsize=12)
            ax2.set_title('🎤 Top Salons Vocaux', color='white', fontsize=12, fontweight='bold')
        
        # 3. Courbe d'activité messages (bas gauche)
        ax3 = axes[1, 0]
        ax3.set_facecolor('#36393f')
        
        dates = []
        messages = []
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            dates.append(dt.strftime('%d/%m'))
            messages.append(stats['messages_per_day'].get(date_key, 0))
        
        ax3.fill_between(range(len(dates)), messages, alpha=0.3, color='#5865F2')
        ax3.plot(range(len(dates)), messages, color='#5865F2', linewidth=2, marker='o', markersize=4)
        ax3.set_xlabel('Date', color='white', fontsize=10)
        ax3.set_ylabel('Messages', color='white', fontsize=10)
        ax3.set_title('💬 Messages par jour', color='white', fontsize=12, fontweight='bold')
        ax3.tick_params(colors='white')
        ax3.set_xticks(range(0, len(dates), max(1, len(dates)//7)))
        ax3.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45, fontsize=8)
        ax3.spines['bottom'].set_color('white')
        ax3.spines['left'].set_color('white')
        ax3.spines['top'].set_visible(False)
        ax3.spines['right'].set_visible(False)
        ax3.grid(True, alpha=0.2, color='white')
        
        # 4. Courbe d'activité vocale (bas droit)
        ax4 = axes[1, 1]
        ax4.set_facecolor('#36393f')
        
        vocal = []
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            vocal.append(stats['vocal_per_day'].get(date_key, 0) / 60)  # En minutes
        
        ax4.fill_between(range(len(dates)), vocal, alpha=0.3, color='#57F287')
        ax4.plot(range(len(dates)), vocal, color='#57F287', linewidth=2, marker='o', markersize=4)
        ax4.set_xlabel('Date', color='white', fontsize=10)
        ax4.set_ylabel('Minutes', color='white', fontsize=10)
        ax4.set_title('🎤 Temps vocal par jour', color='white', fontsize=12, fontweight='bold')
        ax4.tick_params(colors='white')
        ax4.set_xticks(range(0, len(dates), max(1, len(dates)//7)))
        ax4.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45, fontsize=8)
        ax4.spines['bottom'].set_color('white')
        ax4.spines['left'].set_color('white')
        ax4.spines['top'].set_visible(False)
        ax4.spines['right'].set_visible(False)
        ax4.grid(True, alpha=0.2, color='white')
        
        # Titre principal
        fig.suptitle(f'📊 Statistiques détaillées de {member.display_name}', 
                    color='white', fontsize=16, fontweight='bold', y=0.98)
        
        plt.tight_layout(rect=[0, 0, 1, 0.96])
        
        # Sauvegarder
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
        buf.seek(0)
        plt.close(fig)
        
        return buf
        
    except Exception as ex:
        print(f"Erreur génération graphique détaillé: {ex}")
        return None

# ═══════════════════════════════════════════════════════════════════════════════
#                              📊 SUGGESTION VOTE TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    
    # Vérifier si c'est une suggestion
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id FROM suggestions WHERE message_id=?', (payload.message_id,)) as c:
                if not await c.fetchone():
                    return
        
        # Mettre à jour la couleur de l'embed
        channel = bot.get_channel(payload.channel_id)
        if not channel:
            return
        
        msg = await channel.fetch_message(payload.message_id)
        
        # Compter les votes
        votes = {"✅": 0, "🟠": 0, "❌": 0}
        for reaction in msg.reactions:
            if reaction.emoji in votes:
                votes[reaction.emoji] = reaction.count - 1  # -1 pour le bot
        
        # Déterminer la couleur
        total = sum(votes.values())
        if total == 0:
            color = C.BLURPLE
        elif votes["✅"] > votes["❌"] and votes["✅"] > votes["🟠"]:
            color = C.GREEN
        elif votes["❌"] > votes["✅"] and votes["❌"] > votes["🟠"]:
            color = C.RED
        elif votes["🟠"] > votes["✅"] and votes["🟠"] > votes["❌"]:
            color = C.ORANGE
        else:
            color = C.BLURPLE
        
        # Mettre à jour l'embed
        if msg.embeds:
            old_embed = msg.embeds[0]
            new_embed = discord.Embed(
                title=old_embed.title,
                description=old_embed.description,
                color=color,
                timestamp=old_embed.timestamp
            )
            for field in old_embed.fields:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            if old_embed.thumbnail:
                new_embed.set_thumbnail(url=old_embed.thumbnail.url)
            new_embed.set_footer(text=f"✅ {votes['✅']} | 🟠 {votes['🟠']} | ❌ {votes['❌']}")
            
            await msg.edit(embed=new_embed)
    except:
        pass

@bot.event
async def on_raw_reaction_remove(payload):
    await on_raw_reaction_add(payload)  # Même logique

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎭 REALSY INACTIVITY TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(hours=24)
async def check_realsy_inactivity():
    """Vérifie l'inactivité des utilisateurs avec le rôle Realsy chaque jour"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, user_id, last_activity, warn_count FROM realsy_tracking') as c:
                rows = await c.fetchall()
        
        for guild_id, user_id, last_activity, warn_count in rows:
            try:
                guild = bot.get_guild(guild_id)
                if not guild:
                    continue
                
                c = await cfg(guild_id)
                role = guild.get_role(c.get('rellseas_role', 0))
                if not role:
                    continue
                
                member = guild.get_member(user_id)
                if not member or role not in member.roles:
                    # L'utilisateur n'a plus le rôle, supprimer du tracking
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                            (guild_id, user_id))
                        await db.commit()
                    continue
                
                # Calculer l'inactivité
                try:
                    last_dt = datetime.fromisoformat(last_activity)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                except:
                    last_dt = now() - timedelta(days=8)  # Considérer comme inactif si erreur
                
                days_inactive = (now() - last_dt).days
                
                if days_inactive >= 7:
                    warn_ch = guild.get_channel(c.get('rellseas_warn_channel', 0))
                    log_ch = guild.get_channel(c.get('rellseas_log_channel', 0))
                    
                    if warn_count == 0:
                        # Premier warn
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute('UPDATE realsy_tracking SET warn_count=1 WHERE guild_id=? AND user_id=?',
                                (guild_id, user_id))
                            await db.commit()
                        
                        if warn_ch:
                            e = discord.Embed(title="⚠️ Avertissement Inactivité", color=C.YELLOW, timestamp=now())
                            e.description = f"{member.mention}, vous êtes inactif depuis **{days_inactive} jours**.\n\n⚠️ Si vous restez inactif, votre rôle **{role.name}** sera retiré."
                            e.set_thumbnail(url=member.display_avatar.url)
                            await warn_ch.send(content=member.mention, embed=e)
                        
                        if log_ch:
                            log_e = discord.Embed(title="⚠️ Warn Inactivité #1", color=C.YELLOW, timestamp=now())
                            log_e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
                            log_e.add_field(name="📅 Inactif depuis", value=f"{days_inactive} jours", inline=True)
                            log_e.set_thumbnail(url=member.display_avatar.url)
                            await log_ch.send(embed=log_e)
                    
                    elif warn_count >= 1 and days_inactive >= 14:
                        # Deuxième warn - retirer le rôle
                        try:
                            await member.remove_roles(role, reason="Inactivité - 2ème avertissement")
                            
                            # Supprimer du tracking
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                                    (guild_id, user_id))
                                await db.commit()
                            
                            if warn_ch:
                                e = discord.Embed(title="🚫 Rôle Retiré - Inactivité", color=C.RED, timestamp=now())
                                e.description = f"{member.mention}, votre rôle **{role.name}** a été retiré pour cause d'inactivité prolongée ({days_inactive} jours)."
                                e.set_thumbnail(url=member.display_avatar.url)
                                await warn_ch.send(content=member.mention, embed=e)
                            
                            if log_ch:
                                log_e = discord.Embed(title="🚫 Rôle Retiré - AFK", color=C.RED, timestamp=now())
                                log_e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
                                log_e.add_field(name="🎭 Rôle retiré", value=role.mention, inline=True)
                                log_e.add_field(name="📅 Inactif depuis", value=f"{days_inactive} jours", inline=True)
                                log_e.set_thumbnail(url=member.display_avatar.url)
                                await log_ch.send(embed=log_e)
                        except:
                            pass
            except:
                continue
    except:
        pass

@check_realsy_inactivity.before_loop
async def before_check():
    await bot.wait_until_ready()

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 TÂCHE VÉRIFICATION FEEDS SOCIAUX
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=5)
async def check_social_feeds():
    """Vérifie les nouveaux posts YouTube, Twitch, Twitter, Reddit, Discord et RoSocial"""
    try:
        async with aiohttp.ClientSession() as session:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT guild_id, data FROM guild_config') as cursor:
                    async for row in cursor:
                        guild_id, data_str = row
                        try:
                            data = json.loads(data_str) if data_str else {}
                            guild = bot.get_guild(guild_id)
                            if not guild:
                                continue
                            
                            # YouTube
                            await check_youtube_feeds(session, guild, data)
                            
                            # Twitch
                            await check_twitch_feeds(session, guild, data)
                            
                            # Twitter/X
                            await check_twitter_feeds(session, guild, data)
                            
                            # Reddit
                            await check_reddit_feeds(session, guild, data)
                            
                            # RoSocial
                            await check_rosocial_feeds(session, guild, data)
                            
                        except Exception as ex:
                            print(f"Erreur feed {guild_id}: {ex}")
                            continue
    except Exception as ex:
        print(f"Erreur check_social_feeds: {ex}")

async def check_youtube_feeds(session, guild, data):
    """Vérifie les nouvelles vidéos YouTube"""
    channel = guild.get_channel(data.get('ads_youtube_channel', 0))
    feeds = data.get('ads_youtube_feeds', [])
    if not channel or not feeds:
        return
    
    for feed in feeds:
        try:
            channel_id = feed['id']
            channel_name = feed['name']
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            
            async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                xml_text = await resp.text()
            
            root = ET.fromstring(xml_text)
            ns = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015', 'media': 'http://search.yahoo.com/mrss/'}
            
            entries = root.findall('atom:entry', ns)
            if not entries:
                continue
            
            entry = entries[0]
            video_id_elem = entry.find('yt:videoId', ns)
            title_elem = entry.find('atom:title', ns)
            published_elem = entry.find('atom:published', ns)
            
            # Essayer de trouver la description
            media_group = entry.find('media:group', ns)
            description = ""
            if media_group is not None:
                desc_elem = media_group.find('media:description', ns)
                if desc_elem is not None and desc_elem.text:
                    description = desc_elem.text[:200] + "..." if len(desc_elem.text) > 200 else desc_elem.text
            
            if video_id_elem is None or title_elem is None:
                continue
            
            video_id = video_id_elem.text
            title = title_elem.text
            cache_key = f"yt_{guild.id}_{channel_id}"
            
            if cache_key in posted_content and posted_content[cache_key] == video_id:
                continue
            
            posted_content[cache_key] = video_id
            
            # ═══════════════ EMBED YOUTUBE PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0xFF0000)
            
            # Titre avec bannière
            e.title = f"▶️ {title}"
            e.url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Description du post
            if description:
                e.description = f"*{description}*"
            
            # Auteur avec logo YouTube
            e.set_author(
                name=f"🔴 YOUTUBE • {channel_name}",
                url=f"https://www.youtube.com/channel/{channel_id}",
                icon_url="https://www.gstatic.com/youtube/img/branding/youtubelogo/svg/youtubelogo.svg"
            )
            
            # Miniature grande
            e.set_image(url=f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")
            
            # Bouton "Regarder"
            e.add_field(
                name="",
                value=f"[▶️ **Regarder la vidéo**](https://www.youtube.com/watch?v={video_id})",
                inline=False
            )
            
            # Footer avec icône
            e.set_footer(
                text=f"YouTube • {channel_name}",
                icon_url="https://www.youtube.com/s/desktop/28b67e7f/img/favicon_144x144.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur YouTube feed {feed}: {ex}")
            continue

async def check_twitch_feeds(session, guild, data):
    """Vérifie si des streamers sont en live sur Twitch"""
    channel = guild.get_channel(data.get('ads_twitch_channel', 0))
    feeds = data.get('ads_twitch_feeds', [])
    if not channel or not feeds:
        return
    
    for username in feeds:
        try:
            url = f"https://www.twitch.tv/{username}"
            cache_key = f"twitch_{guild.id}_{username}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
            
            is_live = '"isLiveBroadcast":true' in html or 'isLiveBroadcast' in html
            
            was_live = posted_content.get(cache_key, False)
            
            if is_live and not was_live:
                posted_content[cache_key] = True
                
                # ═══════════════ EMBED TWITCH PROFESSIONNEL ═══════════════
                e = discord.Embed(color=0x9146FF)
                
                e.title = f"🔴 {username} est en LIVE !"
                e.url = f"https://www.twitch.tv/{username}"
                
                e.description = f"**{username}** vient de lancer un stream !\nRejoins le live maintenant !"
                
                e.set_author(
                    name=f"🟣 TWITCH • {username}",
                    url=f"https://www.twitch.tv/{username}",
                    icon_url="https://static.twitchcdn.net/assets/favicon-32-e29e246c157142c94346.png"
                )
                
                # Preview du stream (avec timestamp pour éviter le cache)
                e.set_image(url=f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{username.lower()}-1280x720.jpg?t={int(now().timestamp())}")
                
                e.add_field(
                    name="",
                    value=f"[🟣 **Rejoindre le stream**](https://www.twitch.tv/{username})",
                    inline=False
                )
                
                e.set_footer(
                    text=f"Twitch • {username}",
                    icon_url="https://static.twitchcdn.net/assets/favicon-32-e29e246c157142c94346.png"
                )
                e.timestamp = now()
                
                await channel.send(embed=e)
                
            elif not is_live and was_live:
                posted_content[cache_key] = False
            
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Twitch feed {username}: {ex}")
            continue

async def check_reddit_feeds(session, guild, data):
    """Vérifie les nouveaux posts Reddit"""
    channel = guild.get_channel(data.get('ads_reddit_channel', 0))
    feeds = data.get('ads_reddit_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Discord Bot 1.0'}
    
    for subreddit in feeds:
        try:
            rss_url = f"https://www.reddit.com/r/{subreddit}/new.rss?limit=1"
            
            async with session.get(rss_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                xml_text = await resp.text()
            
            root = ET.fromstring(xml_text)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            
            entries = root.findall('atom:entry', ns)
            if not entries:
                continue
            
            entry = entries[0]
            post_id = entry.find('atom:id', ns)
            title = entry.find('atom:title', ns)
            link = entry.find('atom:link', ns)
            author = entry.find('atom:author/atom:name', ns)
            content = entry.find('atom:content', ns)
            
            if post_id is None or title is None:
                continue
            
            post_id = post_id.text
            title = title.text
            link = link.get('href') if link is not None else f"https://reddit.com/r/{subreddit}"
            author = author.text if author is not None else "Unknown"
            
            # Extraire image si présente dans le contenu HTML
            image_url = None
            if content is not None and content.text:
                import re
                img_match = re.search(r'<img[^>]+src="([^"]+)"', content.text)
                if img_match:
                    image_url = img_match.group(1)
            
            cache_key = f"rd_{guild.id}_{subreddit}"
            
            if cache_key in posted_content and posted_content[cache_key] == post_id:
                continue
            
            posted_content[cache_key] = post_id
            
            # ═══════════════ EMBED REDDIT PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0xFF4500)
            
            e.title = f"📰 {title[:200]}"
            e.url = link
            
            e.set_author(
                name=f"🟠 REDDIT • r/{subreddit}",
                url=f"https://www.reddit.com/r/{subreddit}",
                icon_url="https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png"
            )
            
            e.add_field(name="👤 Auteur", value=f"u/{author}", inline=True)
            e.add_field(name="📁 Subreddit", value=f"r/{subreddit}", inline=True)
            
            if image_url and ('i.redd.it' in image_url or 'preview.redd.it' in image_url):
                e.set_image(url=image_url)
            
            e.add_field(
                name="",
                value=f"[🔗 **Voir le post complet**]({link})",
                inline=False
            )
            
            e.set_footer(
                text=f"Reddit • r/{subreddit}",
                icon_url="https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Reddit feed {subreddit}: {ex}")
            continue

async def check_twitter_feeds(session, guild, data):
    """Vérifie les nouveaux tweets via Nitter"""
    channel = guild.get_channel(data.get('ads_twitter_channel', 0))
    feeds = data.get('ads_twitter_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for username in feeds:
        try:
            xml_text = None
            working_instance = None
            for instance in NITTER_INSTANCES:
                try:
                    rss_url = f"https://{instance}/{username}/rss"
                    async with session.get(rss_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            xml_text = await resp.text()
                            working_instance = instance
                            break
                except:
                    continue
            
            if not xml_text:
                continue
            
            root = ET.fromstring(xml_text)
            items = root.findall('.//item')
            if not items:
                continue
            
            item = items[0]
            title = item.find('title')
            link = item.find('link')
            guid = item.find('guid')
            description = item.find('description')
            
            if title is None or guid is None:
                continue
            
            tweet_id = guid.text if guid is not None else ""
            tweet_text = title.text if title is not None else ""
            tweet_link = link.text if link is not None else f"https://twitter.com/{username}"
            
            # Convertir lien Nitter en lien Twitter
            tweet_link = tweet_link.replace(f"https://{working_instance}", "https://twitter.com") if working_instance else tweet_link
            
            # Extraire image si présente
            image_url = None
            if description is not None and description.text:
                import re
                img_match = re.search(r'<img[^>]+src="([^"]+)"', description.text)
                if img_match:
                    image_url = img_match.group(1)
            
            cache_key = f"twitter_{guild.id}_{username}"
            
            if cache_key in posted_content and posted_content[cache_key] == tweet_id:
                continue
            
            posted_content[cache_key] = tweet_id
            
            # ═══════════════ EMBED TWITTER PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0x1DA1F2)
            
            e.description = f"💬 {tweet_text[:1900]}"
            
            e.set_author(
                name=f"🐦 TWITTER/X • @{username}",
                url=f"https://twitter.com/{username}",
                icon_url="https://abs.twimg.com/responsive-web/client-web/icon-ios.77d25eba.png"
            )
            
            if image_url:
                # Convertir URL Nitter en URL Twitter si nécessaire
                if working_instance and working_instance in image_url:
                    image_url = image_url.replace(f"https://{working_instance}", "https://pbs.twimg.com")
                e.set_image(url=image_url)
            
            e.add_field(
                name="",
                value=f"[🐦 **Voir le tweet**]({tweet_link})",
                inline=False
            )
            
            e.set_footer(
                text=f"Twitter/X • @{username}",
                icon_url="https://abs.twimg.com/responsive-web/client-web/icon-ios.77d25eba.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Twitter feed {username}: {ex}")
            continue

async def check_rosocial_feeds(session, guild, data):
    """Vérifie les nouveaux posts RoSocial"""
    channel = guild.get_channel(data.get('ads_rosocial_channel', 0))
    feeds = data.get('ads_rosocial_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for username in feeds:
        try:
            url = f"https://rosocial.net/{username}"
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
            
            import re
            
            # Trouver le dernier post
            posts = re.findall(r'href="https://rosocial\.net/posts/(\d+)"', html)
            if not posts:
                posts = re.findall(r'/posts/(\d+)', html)
            
            if not posts:
                continue
            
            latest_post_id = posts[0]
            cache_key = f"rs_{guild.id}_{username}"
            
            if cache_key in posted_content and posted_content[cache_key] == latest_post_id:
                continue
            
            posted_content[cache_key] = latest_post_id
            
            post_url = f"https://rosocial.net/posts/{latest_post_id}"
            profile_url = f"https://rosocial.net/{username}"
            
            # Extraire la photo de profil si possible
            avatar_match = re.search(rf'{username}[^>]*<img[^>]+src="([^"]+)"', html)
            avatar_url = "https://rosocial.net/content/uploads/photos/2025/11/roso_597f00df39d1431f924ec9403430e921.png"
            if avatar_match:
                avatar_url = avatar_match.group(1)
            
            # Extraire le contenu du post si possible
            post_content = ""
            content_match = re.search(rf'/posts/{latest_post_id}"[^>]*>.*?<p[^>]*>([^<]+)</p>', html, re.DOTALL)
            if content_match:
                post_content = content_match.group(1).strip()[:200]
            
            # Extraire une image du post si présente
            image_url = None
            img_match = re.search(rf'/posts/{latest_post_id}.*?<img[^>]+src="(https://rosocial\.net/content/uploads/photos/[^"]+)"', html, re.DOTALL)
            if img_match:
                image_url = img_match.group(1)
            
            # ═══════════════ EMBED ROSOCIAL PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0x00D4AA)
            
            e.title = f"📝 Nouveau post de {username}"
            e.url = post_url
            
            if post_content:
                e.description = f"*{post_content}...*"
            
            e.set_author(
                name=f"🎮 ROSOCIAL • {username}",
                url=profile_url,
                icon_url="https://rosocial.net/content/uploads/photos/2025/11/roso_597f00df39d1431f924ec9403430e921.png"
            )
            
            # Thumbnail avec avatar ou logo
            e.set_thumbnail(url=avatar_url)
            
            # Image du post si disponible
            if image_url:
                e.set_image(url=image_url)
            
            e.add_field(
                name="",
                value=f"[🎮 **Voir le post**]({post_url}) • [👤 **Profil**]({profile_url})",
                inline=False
            )
            
            e.set_footer(
                text=f"RoSocial • {username}",
                icon_url="https://rosocial.net/content/uploads/photos/2025/11/roso_597f00df39d1431f924ec9403430e921.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur RoSocial feed {username}: {ex}")
            continue

@check_social_feeds.before_loop
async def before_social_check():
    await bot.wait_until_ready()

# Mise à jour activité sur vocal
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    guild_id = member.guild.id
    user_id = member.id
    key = (guild_id, user_id)
    
    # Si l'utilisateur rejoint un vocal
    if after.channel and (not before.channel or before.channel != after.channel):
        await update_realsy_activity(guild_id, user_id)
        
        # Enregistrer l'heure de connexion
        voice_join_tracker[key] = now()
        
        # Tracker l'activité + redonner le rôle si configuré
        await track_member_vocal_join(member, after.channel)
    
    # Si l'utilisateur quitte un vocal
    if before.channel and (not after.channel or before.channel != after.channel):
        # Calculer le temps passé
        join_time = voice_join_tracker.pop(key, None)
        if join_time:
            duration = int((now() - join_time).total_seconds())
            if duration > 0:
                await track_member_vocal_leave(member, before.channel, duration)

async def track_member_message(msg):
    """Enregistre un message dans le tracking d'activité"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour activity_tracking
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_message, total_messages)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_message = ?,
                    total_messages = total_messages + 1
            ''', (msg.guild.id, msg.author.id, now_str, now_str))
            
            # Enregistrer dans member_activity pour les stats détaillées
            await db.execute('''
                INSERT INTO member_activity (guild_id, user_id, activity_type, channel_id, message_id, created_at)
                VALUES (?, ?, 'message', ?, ?, ?)
            ''', (msg.guild.id, msg.author.id, msg.channel.id, msg.id, now_str))
            
            await db.commit()
        
    except Exception as ex:
        print(f"Erreur track message: {ex}")

async def handle_recovery_message(msg, stat_cfg):
    """Gère un message dans le salon de récupération - supprime le message et redonne le rôle"""
    try:
        role_id = stat_cfg.get('activity_role', 0)
        notif_ch_id = stat_cfg.get('notif_channel', 0)
        
        role = msg.guild.get_role(role_id) if role_id else None
        notif_ch = msg.guild.get_channel(notif_ch_id) if notif_ch_id else None
        
        # Supprimer le message immédiatement
        try:
            await msg.delete()
        except:
            pass
        
        # Mettre à jour l'activité du membre
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_message, total_messages)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_message = ?,
                    total_messages = total_messages + 1
            ''', (msg.guild.id, msg.author.id, now_str, now_str))
            await db.commit()
        
        # Redonner le rôle SEULEMENT si le membre ne l'a pas
        if role and role not in msg.author.roles:
            try:
                await msg.author.add_roles(role, reason="Récupération d'activité via salon dédié")
                
                # Notification discrète (sans mention) seulement si rôle redonné
                if notif_ch:
                    e = discord.Embed(
                        title="✅ Activité Récupérée",
                        color=C.GREEN
                    )
                    e.description = f"**{msg.author.display_name}** a récupéré le rôle **{role.name}**"
                    e.set_thumbnail(url=msg.author.display_avatar.url if msg.author.display_avatar else None)
                    e.set_footer(text=f"ID: {msg.author.id}")
                    e.timestamp = now()
                    await notif_ch.send(embed=e)
            except:
                pass
        
        # Si le membre a déjà le rôle, ne rien faire (évite le spam)
        
    except Exception as ex:
        print(f"Erreur handle_recovery_message: {ex}")

async def track_member_vocal_join(member, channel):
    """Enregistre une connexion vocale"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour last_vocal
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_vocal)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_vocal = ?
            ''', (member.guild.id, member.id, now_str, now_str))
            
            await db.commit()
        
        # Redonner le rôle d'activité si configuré
        await restore_activity_role(member)
        
    except Exception as ex:
        print(f"Erreur track vocal join: {ex}")

async def track_member_vocal_leave(member, channel, duration):
    """Enregistre le temps passé en vocal"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour le temps total en vocal
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, total_vocal_time)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    total_vocal_time = total_vocal_time + ?
            ''', (member.guild.id, member.id, duration, duration))
            
            # Enregistrer la session vocale
            await db.execute('''
                INSERT INTO member_activity (guild_id, user_id, activity_type, channel_id, duration, created_at)
                VALUES (?, ?, 'vocal', ?, ?, ?)
            ''', (member.guild.id, member.id, channel.id, duration, now_str))
            
            await db.commit()
            
    except Exception as ex:
        print(f"Erreur track vocal leave: {ex}")

async def restore_activity_role(member):
    """Redonne le rôle d'activité si le membre rejoint un vocal"""
    try:
        c = await cfg(member.guild.id)
        stat_cfg = c.get('stat_config', {})
        role_id = stat_cfg.get('activity_role', 0)
        notif_ch_id = stat_cfg.get('notif_channel', 0)
        
        if not role_id:
            return
        
        role = member.guild.get_role(role_id)
        if not role:
            return
        
        # Si le membre n'a pas le rôle, lui redonner
        if role not in member.roles:
            try:
                await member.add_roles(role, reason="Retour d'activité via vocal")
                
                # Notification discrète (sans mention)
                notif_ch = member.guild.get_channel(notif_ch_id) if notif_ch_id else None
                
                if notif_ch:
                    e = discord.Embed(
                        title="✅ Activité Récupérée",
                        color=C.GREEN
                    )
                    e.description = f"**{member.display_name}** a récupéré le rôle **{role.name}** en rejoignant un vocal"
                    e.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
                    e.set_footer(text=f"ID: {member.id}")
                    e.timestamp = now()
                    await notif_ch.send(embed=e)
            except:
                pass
                
    except Exception as ex:
        print(f"Erreur restore role: {ex}")

if __name__ == "__main__":
    print("🚀 Bot v18 - Démarrage...")
    bot.run(TOKEN)

from discord import app_commands
from discord.ui import View, Select, Modal, TextInput, Button
import aiosqlite, os, re, json, asyncio, unicodedata, io, time, aiohttp
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')  # Backend non-interactif
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from collections import defaultdict

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
DB_PATH = '/data/bot.db' if os.path.exists('/data') else 'bot.db'
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
spam_tracker = {}
voice_join_tracker = {}  # {(guild_id, user_id): datetime} - pour tracker le temps en vocal

class C:
    BLURPLE=0x5865F2; GREEN=0x57F287; RED=0xED4245; YELLOW=0xFEE75C
    PURPLE=0x9B59B6; BLUE=0x3498DB; ORANGE=0xE67E22; GOLD=0xFFD700

PHISHING = ['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com']
SCAM_PATTERNS = [r'free\s*nitro', r'steam\s*gift', r'@everyone.*http']
LEET = {'a':['@','4'],'e':['3','€'],'i':['1','!'],'o':['0'],'s':['$','5'],'t':['7']}

def now(): return datetime.now(timezone.utc)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💾 DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('CREATE TABLE IF NOT EXISTS guild_config(guild_id INTEGER PRIMARY KEY, data TEXT DEFAULT "{}")')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles(guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id, role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_users(guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id, user_id))')
        await db.execute('''CREATE TABLE IF NOT EXISTS infractions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            mod_id INTEGER,
            type TEXT,
            reason TEXT,
            duration TEXT DEFAULT "",
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour tracker l'activité Realsy
        await db.execute('''CREATE TABLE IF NOT EXISTS realsy_tracking(
            guild_id INTEGER,
            user_id INTEGER,
            last_activity TEXT,
            warn_count INTEGER DEFAULT 0,
            PRIMARY KEY(guild_id, user_id)
        )''')
        # Table pour les suggestions
        await db.execute('''CREATE TABLE IF NOT EXISTS suggestions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour tracker l'activité des membres
        await db.execute('''CREATE TABLE IF NOT EXISTS member_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            activity_type TEXT,
            channel_id INTEGER,
            duration INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0,
            reactions INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table pour les stats d'inactivité
        await db.execute('''CREATE TABLE IF NOT EXISTS activity_tracking (
            guild_id INTEGER,
            user_id INTEGER,
            last_message DATETIME,
            last_vocal DATETIME,
            total_messages INTEGER DEFAULT 0,
            total_vocal_time INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )''')
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'") as cur:
            if not await cur.fetchone():
                await db.execute('CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, user_id INTEGER, panel_id TEXT DEFAULT "", claimed_by INTEGER DEFAULT 0, status TEXT DEFAULT "open", answers TEXT DEFAULT "{}", created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
            else:
                async with db.execute("PRAGMA table_info(tickets)") as cur2:
                    cols = [r[1] for r in await cur2.fetchall()]
                for cn, ct in [('panel_id','TEXT DEFAULT ""'),('claimed_by','INTEGER DEFAULT 0'),('status','TEXT DEFAULT "open"'),('answers','TEXT DEFAULT "{}"')]:
                    if cn not in cols:
                        try: await db.execute(f'ALTER TABLE tickets ADD COLUMN {cn} {ct}')
                        except: pass
        # Migration infractions
        async with db.execute("PRAGMA table_info(infractions)") as cur:
            cols = [r[1] for r in await cur.fetchall()]
        if 'duration' not in cols:
            try: await db.execute('ALTER TABLE infractions ADD COLUMN duration TEXT DEFAULT ""')
            except: pass
        if 'created_at' not in cols:
            try: await db.execute('ALTER TABLE infractions ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP')
            except: pass
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
            await db.execute('INSERT INTO guild_config(guild_id, data) VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET data=?', (gid, jd, jd))
            await db.commit()
        return True
    except: return False

async def cfg(gid):
    data = await db_get(gid)
    defaults = {
        'anti_link': 0, 'anti_invite': 0, 'anti_image': 0, 'anti_phishing': 1, 'anti_scam': 1,
        'anti_spam': 0, 'anti_caps': 0, 'anti_newaccount': 0, 'anti_badwords': 0,
        'link_whitelist': [], 'image_allowed': [], 'badwords_list': [],
        'link_allowed_channels': [], 'image_allowed_channels': [],
        'phishing_action': 'ban', 'scam_action': 'mute', 'spam_action': 'mute',
        'spam_max': 5, 'spam_interval': 5, 'caps_percent': 70, 'newaccount_days': 7,
        'log_anti_link': 0, 'log_anti_image': 0, 'log_anti_phishing': 0, 'log_anti_scam': 0,
        'log_anti_spam': 0, 'log_anti_caps': 0, 'log_anti_badwords': 0, 'log_anti_invite': 0, 'log_anti_newaccount': 0,
        'channel_configs': {},
        'ticket_staff': 0, 'ticket_log': 0, 'ticket_panels': {},
        'mod_warn_role': 0, 'mod_mute_role': 0, 'mod_infractions_role': 0, 'mod_log_channel': 0
    }
    for k, v in defaults.items():
        if k not in data: data[k] = v
    return data

async def is_immune(m, key):
    if key != 'anti_phishing' and (m.guild_permissions.administrator or m.id == m.guild.owner_id):
        return True
    if key in ['anti_phishing', 'anti_link', 'anti_invite']:
        return False
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (m.guild.id,)) as c:
                rids = [r[0] for r in await c.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (m.guild.id,)) as c:
                uids = [r[0] for r in await c.fetchall()]
        if any(role.id in rids for role in m.roles) or m.id in uids:
            return True
    except: pass
    return False

async def sanction(m, action, dur, reason, g):
    try:
        if action == 'mute': await m.timeout(timedelta(minutes=dur), reason=reason)
        elif action == 'kick': await m.kick(reason=reason)
        elif action == 'ban': await m.ban(reason=reason)
    except: pass

async def send_log(g, key, m, msg, reason, extra=None):
    try:
        c = await cfg(g.id)
        ch = g.get_channel(c.get(f'log_{key}', 0))
        if not ch: return
        e = discord.Embed(title=f"🛡️ {key.replace('anti_', '').upper()}", color=C.RED, timestamp=now())
        e.add_field(name="👤 Utilisateur", value=f"{m.mention} (`{m.id}`)", inline=True)
        if msg and msg.channel:
            e.add_field(name="📍 Salon", value=msg.channel.mention, inline=True)
        e.add_field(name="⚠️ Raison", value=reason, inline=False)
        if extra:
            e.add_field(name="ℹ️ Détails", value=extra, inline=False)
        e.set_thumbnail(url=m.display_avatar.url)
        await ch.send(embed=e)
    except: pass

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔍 CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def get_gif_type(msg):
    ct = (msg.content or "").lower()
    if 'tenor.com' in ct: return 'tenor'
    if 'giphy.com' in ct: return 'giphy'
    for emb in msg.embeds:
        if emb.url and 'tenor' in emb.url.lower(): return 'tenor'
        if emb.url and 'giphy' in emb.url.lower(): return 'giphy'
    for att in msg.attachments:
        if att.filename.lower().endswith('.gif'): return 'gif'
    return None

def normalize(t):
    t = t.lower()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    for l, vs in LEET.items():
        for v in vs: t = t.replace(v, l)
    return t

def check_badwords(ct, words):
    if not words: return False, None
    norm = normalize(ct)
    for w in words:
        if normalize(w.strip()) in norm: return True, w
    return False, None

def check_link(ct, wl):
    urls = re.findall(r'https?://([^\s<>"]+)', ct.lower())
    for url in urls:
        dom = url.split('/')[0]
        if not any(w.lower() in dom for w in wl): return True, url
    return False, None

def check_invite(ct):
    m = re.search(r'discord\.gg/\w+|discord\.com/invite/\w+', ct, re.I)
    return (True, m.group()) if m else (False, None)

def check_phishing(ct):
    for d in PHISHING:
        if d in ct.lower(): return True, d
    return False, None

def check_scam(ct):
    for p in SCAM_PATTERNS:
        if re.search(p, ct, re.I): return True, p
    return False, None

def check_caps(ct, pct):
    ltrs = [c for c in ct if c.isalpha()]
    if len(ltrs) < 10: return False
    return sum(1 for c in ltrs if c.isupper()) / len(ltrs) * 100 >= pct

def check_image(msg, allowed):
    blocked = []
    gt = get_gif_type(msg)
    if gt and gt not in allowed: blocked.append(gt)
    for att in msg.attachments:
        ext = att.filename.lower().split('.')[-1]
        if ext in ['png', 'jpg', 'jpeg', 'webp', 'bmp'] and ext not in allowed:
            blocked.append(ext)
    return blocked

async def check_spam(msg, mx, intv):
    key = (msg.guild.id, msg.author.id)
    n = now()
    if key not in spam_tracker: spam_tracker[key] = []
    spam_tracker[key] = [t for t in spam_tracker[key] if (n - t).total_seconds() < intv]
    spam_tracker[key].append(n)
    return len(spam_tracker[key]) > mx

def check_channel_cfg(msg, conf):
    if not conf: return False, None
    ct = (msg.content or "").strip()
    # Commands only - bloque tout sauf les commandes slash (qui n'apparaissent pas comme messages normaux)
    if conf.get('commands_only', False):
        # Si le message n'est pas vide, c'est pas une commande slash
        if ct or msg.attachments:
            return True, "commands_only"
    if not conf.get('messages', True):
        has_txt = bool(re.sub(r'<a?:\w+:\d+>|https?://\S+', '', ct).strip())
        if has_txt and not msg.attachments and not msg.embeds:
            return True, "messages"
    if not conf.get('images', True):
        for att in msg.attachments:
            if att.filename.lower().split('.')[-1] in ['png', 'jpg', 'jpeg', 'webp', 'bmp']:
                return True, "images"
    if not conf.get('gifs', True) and get_gif_type(msg):
        return True, "gifs"
    if not conf.get('emojis', True) and re.search(r'<a?:\w+:\d+>', ct):
        return True, "emojis"
    if not conf.get('links', True) and re.search(r'https?://', ct):
        return True, "links"
    return False, None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_ticket(ch_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id, user_id, claimed_by, answers, panel_id FROM tickets WHERE channel_id=? AND status="open"', (ch_id,)) as c:
                r = await c.fetchone()
                if r:
                    ans = {}
                    try: ans = json.loads(r[3]) if r[3] else {}
                    except: pass
                    return {'id': r[0], 'user': r[1], 'claimed': r[2] or 0, 'answers': ans, 'panel_id': r[4] or ''}
                return None
    except: return None

async def count_user_tickets(g, uid, pid=None):
    cnt = 0
    to_close = []
    try:
        q = "SELECT id, channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'"
        p = [g.id, uid]
        if pid:
            q += " AND panel_id=?"
            p.append(pid)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(q, p) as c:
                tks = await c.fetchall()
        for tid, chid in tks:
            if g.get_channel(chid): cnt += 1
            else: to_close.append(tid)
        if to_close:
            async with aiosqlite.connect(DB_PATH) as db:
                for t in to_close:
                    await db.execute("UPDATE tickets SET status='closed' WHERE id=?", (t,))
                await db.commit()
        return cnt
    except: return 0

async def send_ticket_log(g, lt, user, ti, extra=None, closer=None, ch=None):
    try:
        c = await cfg(g.id)
        lch = g.get_channel(c.get('ticket_log', 0))
        if not lch: return
        colors = {'create': C.GREEN, 'claim': C.BLUE, 'close': C.RED, 'leave': C.ORANGE, 'add_staff': C.PURPLE}
        titles = {'create': '🎫 Ticket Créé', 'claim': '🙋 Ticket Pris', 'close': '🔒 Ticket Fermé', 'leave': '🚪 Utilisateur Parti', 'add_staff': '➕ Staff Ajouté'}
        e = discord.Embed(title=titles.get(lt, '🎫'), color=colors.get(lt, C.BLURPLE), timestamp=now())
        e.add_field(name="🎫 Ticket", value=f"#{ti.get('id', '?')}", inline=True)
        uid = user.id if hasattr(user, 'id') else user
        e.add_field(name="👤 Utilisateur", value=f"<@{uid}>", inline=True)
        if lt == 'claim' and extra:
            e.add_field(name="🙋 Pris par", value=f"<@{extra}>", inline=True)
        elif lt == 'close' and closer:
            e.add_field(name="🔒 Fermé par", value=closer.mention, inline=True)
        elif lt == 'add_staff' and extra:
            e.add_field(name="➕ Staff ajouté", value=f"<@{extra}>", inline=True)
        if ti.get('answers') and lt in ['create', 'close']:
            at = "\n".join([f"**{q}**: {a[:80]}" for q, a in list(ti['answers'].items())[:5]])
            if at: e.add_field(name="📝 Réponses", value=at[:1024], inline=False)
        if lt == 'close' and ch:
            lines = []
            try:
                async for m in ch.history(limit=200, oldest_first=True):
                    lines.append(f"[{m.created_at.strftime('%H:%M')}] {m.author.name}: {m.content or '[média]'}")
                f = discord.File(io.BytesIO(("\n".join(lines)).encode()), filename=f"ticket-{ti['id']}.txt")
                await lch.send(embed=e, file=f)
                return
            except: pass
        if hasattr(user, 'display_avatar'):
            e.set_thumbnail(url=user.display_avatar.url)
        await lch.send(embed=e)
    except: pass

async def create_ticket(i, pid, ans=None):
    ch = None
    try:
        c = await cfg(i.guild.id)
        pnl = c.get('ticket_panels', {}).get(pid, {})
        cat = i.guild.get_channel(pnl.get('category', 0))
        staff = i.guild.get_role(c.get('ticket_staff', 0))
        mx = pnl.get('max', 1)
        if not cat: return None, "❌ Catégorie non configurée"
        if await count_user_tickets(i.guild, i.user.id, pid) >= mx:
            return None, f"❌ Max {mx} ticket(s)"
        ow = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True)
        }
        if staff:
            ow[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if i.guild.owner:
            ow[i.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
        ch = await i.guild.create_text_channel(f"ticket-{i.user.name}"[:50], category=cat, overwrites=ow)
        aj = json.dumps(ans or {}, ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO tickets(guild_id, channel_id, user_id, panel_id, claimed_by, status, answers) VALUES(?,?,?,?,0,"open",?)',
                (i.guild.id, ch.id, i.user.id, pid, aj))
            await db.commit()
            async with db.execute('SELECT id FROM tickets WHERE channel_id=?', (ch.id,)) as cur:
                row = await cur.fetchone()
                tid = row[0] if row else 0
        emb = discord.Embed(title="🎫 Nouveau Ticket", color=C.BLURPLE, timestamp=now())
        emb.add_field(name="👤 Créé par", value=f"{i.user.mention}\n`{i.user.id}`", inline=True)
        emb.add_field(name="🎫 ID", value=f"#{tid}", inline=True)
        emb.set_thumbnail(url=i.user.display_avatar.url)
        if ans:
            for t, a in ans.items():
                emb.add_field(name=f"📝 {t}", value=a[:1024], inline=False)
        emb.set_footer(text="Un staff va prendre en charge")
        mention = i.user.mention
        if staff: mention += f" {staff.mention}"
        await ch.send(content=mention, embed=emb, view=TicketControlView())
        await send_ticket_log(i.guild, 'create', i.user, {'id': tid, 'answers': ans or {}})
        return ch, None
    except Exception as ex:
        if ch:
            try: await ch.delete()
            except: pass
        return None, f"❌ {ex}"

class TicketQuestionnaireModal(Modal):
    def __init__(self, pid, qs):
        super().__init__(title="📝 Créer un ticket")
        self.pid = pid
        self.qs = qs
        for i, q in enumerate(qs[:5]):
            self.add_item(TextInput(
                label=q.get('title', f'Q{i+1}')[:45],
                placeholder=q.get('question', '')[:100],
                style=discord.TextStyle.paragraph if len(q.get('question', '')) > 50 else discord.TextStyle.short,
                required=True,
                max_length=500
            ))
    
    async def on_submit(self, i):
        try:
            ans = {self.qs[j].get('title', f'Q{j+1}'): ch.value for j, ch in enumerate(self.children) if j < len(self.qs)}
            await i.response.defer(ephemeral=True)
            ch, err = await create_ticket(i, self.pid, ans)
            await i.followup.send(err if err else f"✅ Ticket créé: {ch.mention}", ephemeral=True)
        except Exception as ex:
            try: await i.followup.send(f"❌ {ex}", ephemeral=True)
            except: pass

class TicketCreateButton(Button):
    def __init__(self, pid):
        super().__init__(label="📩 Créer un ticket", style=discord.ButtonStyle.success, custom_id=f"ticket_create_{pid}")
        self.pid = pid
    
    async def callback(self, i):
        try:
            c = await cfg(i.guild.id)
            pnl = c.get('ticket_panels', {}).get(self.pid, {})
            if not pnl:
                return await i.response.send_message("❌ Panel introuvable", ephemeral=True)
            qs = pnl.get('questions', [])
            mx = pnl.get('max', 1)
            if await count_user_tickets(i.guild, i.user.id, self.pid) >= mx:
                return await i.response.send_message(f"❌ Max {mx} ticket(s)", ephemeral=True)
            if qs:
                await i.response.send_modal(TicketQuestionnaireModal(self.pid, qs))
            else:
                await i.response.defer(ephemeral=True)
                ch, err = await create_ticket(i, self.pid)
                await i.followup.send(err if err else f"✅ Ticket créé: {ch.mention}", ephemeral=True)
        except: pass

class TicketCreateView(View):
    def __init__(self, pid):
        super().__init__(timeout=None)
        self.add_item(TicketCreateButton(pid))

class TicketControlView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🙋 Prendre en charge", style=discord.ButtonStyle.success, custom_id="ticket_ctrl_claim")
    async def claim(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            if i.user.id == tk['user']:
                return await i.response.send_message("❌ Vous ne pouvez pas prendre votre propre ticket", ephemeral=True)
            is_s = sr and sr in i.user.roles
            is_o = i.user.id == i.guild.owner_id
            is_a = i.user.guild_permissions.administrator
            if not (is_s or is_o or is_a):
                return await i.response.send_message("❌ Réservé au staff", ephemeral=True)
            tu = i.guild.get_member(tk['user'])
            ow = {
                i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_permissions=True),
                i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            }
            if tu:
                ow[tu] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
            if i.guild.owner and i.guild.owner != i.user:
                ow[i.guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
            if sr:
                ow[sr] = discord.PermissionOverwrite(view_channel=False)
            await i.channel.edit(overwrites=ow)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?', (i.user.id, i.channel.id))
                await db.commit()
            await i.response.send_message(f"✅ **{i.user.display_name}** prend ce ticket en charge\n\n*Les autres staffs ne peuvent plus voir ce ticket.*")
            btn.disabled = True
            btn.label = f"Pris par {i.user.display_name}"
            btn.style = discord.ButtonStyle.secondary
            await i.message.edit(view=self)
            await send_ticket_log(i.guild, 'claim', tk['user'], tk, extra=i.user.id)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="➕ Ajouter Staff", style=discord.ButtonStyle.primary, custom_id="ticket_ctrl_add")
    async def add_staff(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            if not tk['claimed']:
                return await i.response.send_message("❌ Le ticket doit d'abord être pris en charge", ephemeral=True)
            is_o = i.user.id == i.guild.owner_id
            is_c = i.user.id == tk['claimed']
            is_a = i.user.guild_permissions.administrator
            if not (is_c or is_o or is_a):
                return await i.response.send_message("❌ Seul le staff en charge peut ajouter quelqu'un", ephemeral=True)
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            if not sr:
                return await i.response.send_message("❌ Aucun rôle staff configuré", ephemeral=True)
            staffs = [m for m in sr.members if m.id != tk['claimed'] and m.id != tk['user']][:25]
            if not staffs:
                return await i.response.send_message("❌ Aucun autre staff disponible", ephemeral=True)
            opts = [discord.SelectOption(label=f"@{m.display_name}"[:25], value=str(m.id)) for m in staffs]
            await i.response.send_message("👥 Choisir un staff:", view=AddStaffView(opts, i.channel.id), ephemeral=True)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)
    
    @discord.ui.button(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="ticket_ctrl_close")
    async def close(self, i, btn):
        try:
            tk = await get_ticket(i.channel.id)
            if not tk: return await i.response.send_message("❌ Ticket non trouvé", ephemeral=True)
            is_o = i.user.id == i.guild.owner_id
            is_a = i.user.guild_permissions.administrator
            is_c = i.user.id == tk['claimed']
            c = await cfg(i.guild.id)
            sr = i.guild.get_role(c.get('ticket_staff', 0))
            is_s = sr and sr in i.user.roles
            if tk['claimed']:
                if not (is_c or is_o or is_a):
                    return await i.response.send_message("❌ Seul le staff en charge ou un admin peut fermer", ephemeral=True)
            else:
                if not (is_s or is_o or is_a):
                    return await i.response.send_message("❌ Seul le staff peut fermer", ephemeral=True)
            tu = i.guild.get_member(tk['user'])
            await send_ticket_log(i.guild, 'close', tu or tk['user'], tk, closer=i.user, ch=i.channel)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (i.channel.id,))
                await db.commit()
            await i.response.send_message("🔒 Fermeture dans 3 secondes...")
            await asyncio.sleep(3)
            await i.channel.delete()
        except: pass

class AddStaffView(View):
    def __init__(self, opts, chid):
        super().__init__(timeout=60)
        self.add_item(AddStaffSelect(opts, chid))

class AddStaffSelect(Select):
    def __init__(self, opts, chid):
        super().__init__(placeholder="Choisir un staff...", options=opts)
        self.chid = chid
    
    async def callback(self, i):
        try:
            st = i.guild.get_member(int(self.values[0]))
            ch = i.guild.get_channel(self.chid)
            if st and ch:
                await ch.set_permissions(st, view_channel=True, send_messages=True, read_message_history=True)
                await i.response.send_message(f"✅ {st.mention} ajouté au ticket!", ephemeral=True)
                await ch.send(f"➕ **{st.display_name}** a été ajouté par {i.user.mention}")
                tk = await get_ticket(self.chid)
                if tk:
                    await send_ticket_log(i.guild, 'add_staff', tk['user'], tk, extra=st.id)
        except: await i.response.send_message("❌ Erreur", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🏠 MAIN PANEL
# ═══════════════════════════════════════════════════════════════════════════════

PROTS = [
    ("anti_link", "🔗", "Anti-Liens"),
    ("anti_invite", "🎟️", "Anti-Invite"),
    ("anti_image", "🖼️", "Anti-Images"),
    ("anti_phishing", "🎣", "Anti-Phishing"),
    ("anti_scam", "🚨", "Anti-Scam"),
    ("anti_spam", "📨", "Anti-Spam"),
    ("anti_caps", "🔠", "Anti-Caps"),
    ("anti_badwords", "🤬", "Anti-Insultes"),
    ("anti_newaccount", "👶", "Anti-NewAccount")
]

class MainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def interaction_check(self, i):
        return i.user.id == self.u.id
    
    def embed(self):
        e = discord.Embed(title="⚙️ Configuration", color=C.BLURPLE)
        e.description = f"**{self.g.name}**\n👥 {self.g.member_count} membres"
        if self.g.icon:
            e.set_thumbnail(url=self.g.icon.url)
        return e
    
    @discord.ui.button(label="Protection", emoji="🛡️", style=discord.ButtonStyle.primary, row=0)
    async def prot(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Modération", emoji="🔨", style=discord.ButtonStyle.primary, row=0)
    async def moderation(self, i, b):
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Commandes", emoji="⚡", style=discord.ButtonStyle.primary, row=0)
    async def commands(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Immunités", emoji="👑", style=discord.ButtonStyle.secondary, row=1)
    async def immune(self, i, b):
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Config Salon", emoji="📺", style=discord.ButtonStyle.secondary, row=1)
    async def chan(self, i, b):
        v = ChanPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Tickets", emoji="🎫", style=discord.ButtonStyle.success, row=1)
    async def tickets(self, i, b):
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Publicité", emoji="📢", style=discord.ButtonStyle.success, row=2)
    async def ads(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Statistiques", emoji="📊", style=discord.ButtonStyle.success, row=2)
    async def stats(self, i, b):
        v = StatPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="Fermer", emoji="✖️", style=discord.ButtonStyle.danger, row=2)
    async def close(self, i, b):
        await i.message.delete()

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANEL (REFAIT PROPREMENT)
# ═══════════════════════════════════════════════════════════════════════════════

class ProtPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🛡️ Protection", color=C.BLUE)
        lines = []
        for key, emoji, name in PROTS:
            status = "✅" if c.get(key) else "❌"
            log_ch = self.g.get_channel(c.get(f'log_{key}', 0))
            log_txt = f"→ {log_ch.mention}" if log_ch else ""
            lines.append(f"{emoji} **{name}**: {status} {log_txt}")
        e.description = "\n".join(lines)
        return e
    
    @discord.ui.select(
        placeholder="🛡️ Sélectionner une protection...",
        options=[discord.SelectOption(label=nm, value=k, emoji=em) for k, em, nm in PROTS]
    )
    async def sel(self, i, s):
        prot = next(p for p in PROTS if p[0] == s.values[0])
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ProtDetail(View):
    def __init__(self, u, g, prot):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.prot = prot
        self.key = prot[0]
    
    async def embed(self):
        c = await cfg(self.g.id)
        on = bool(c.get(self.key))
        e = discord.Embed(
            title=f"{self.prot[1]} {self.prot[2]}",
            color=C.GREEN if on else C.RED
        )
        e.add_field(name="🔘 État", value="✅ ACTIVÉ" if on else "❌ DÉSACTIVÉ", inline=False)
        
        # Configs spécifiques
        if self.key == "anti_link":
            wl = c.get('link_whitelist', [])
            e.add_field(name="🌐 Whitelist domaines", value=f"`{', '.join(wl[:15])}`" if wl else "*Aucun domaine*", inline=False)
            chs = c.get('link_allowed_channels', [])
            ch_txt = ", ".join([f"<#{x}>" for x in chs[:10]]) if chs else "*Aucun salon*"
            e.add_field(name="📍 Salons autorisés", value=ch_txt, inline=False)
        
        elif self.key == "anti_image":
            items = c.get('image_allowed', [])
            fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy']
            fmt_txt = " ".join([f"{'✅' if f in items else '❌'} `{f}`" for f in fmts])
            e.add_field(name="📁 Formats autorisés", value=fmt_txt, inline=False)
        
        elif self.key == "anti_badwords":
            words = c.get('badwords_list', [])
            if words:
                # Afficher tous les mots, ou limiter avec compteur
                if len(words) <= 30:
                    words_txt = ", ".join([f"`{w}`" for w in words])
                else:
                    words_txt = ", ".join([f"`{w}`" for w in words[:30]]) + f"\n*... et {len(words) - 30} autres*"
                e.add_field(name=f"🚫 Mots interdits ({len(words)})", value=words_txt[:1024], inline=False)
            else:
                e.add_field(name="🚫 Mots interdits", value="*Aucun mot configuré*", inline=False)
        
        elif self.key == "anti_spam":
            e.add_field(name="📊 Max messages", value=str(c.get('spam_max', 5)), inline=True)
            e.add_field(name="⏱️ Intervalle (sec)", value=str(c.get('spam_interval', 5)), inline=True)
            e.add_field(name="⚡ Action", value=c.get('spam_action', 'mute').upper(), inline=True)
        
        elif self.key == "anti_caps":
            e.add_field(name="📊 Pourcentage max", value=f"{c.get('caps_percent', 70)}%", inline=True)
        
        elif self.key == "anti_newaccount":
            e.add_field(name="📅 Jours minimum", value=str(c.get('newaccount_days', 7)), inline=True)
        
        elif self.key in ["anti_phishing", "anti_scam"]:
            ak = 'phishing_action' if self.key == "anti_phishing" else 'scam_action'
            e.add_field(name="⚡ Action", value=c.get(ak, 'ban' if 'phishing' in ak else 'mute').upper(), inline=True)
        
        # Salon de log
        log_ch = self.g.get_channel(c.get(f'log_{self.key}', 0))
        e.add_field(name="📜 Salon de log", value=log_ch.mention if log_ch else "❌ Non configuré", inline=False)
        
        return e
    
    @discord.ui.button(label="🔄 ON/OFF", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, i, b):
        c = await cfg(self.g.id)
        await db_set(self.g.id, self.key, 0 if c.get(self.key) else 1)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="⚙️ Configurer", style=discord.ButtonStyle.secondary, row=0)
    async def config(self, i, b):
        if self.key == "anti_image":
            v = ImageConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_badwords":
            v = BadwordsConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key == "anti_link":
            v = LinkConfigPanel(self.u, self.g)
            await i.response.edit_message(embed=await v.embed(), view=v)
        elif self.key in ["anti_spam", "anti_caps", "anti_newaccount"]:
            await i.response.send_modal(NumberConfigModal(self.g, self.u, self.key))
        elif self.key in ["anti_phishing", "anti_scam"]:
            v = ActionConfigPanel(self.u, self.g, self.key)
            await i.response.edit_message(embed=await v.embed(), view=v)
        else:
            await i.response.send_message("ℹ️ Pas de configuration supplémentaire", ephemeral=True)
    
    @discord.ui.button(label="📜 Définir Log", style=discord.ButtonStyle.secondary, row=0)
    async def set_log(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="❌ Aucun log", value="0", emoji="🚫"))
        v = LogSelectView(self.u, self.g, opts, self.key, self.prot)
        await i.response.edit_message(embed=discord.Embed(title="📜 Choisir le salon de log", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = ProtPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class LogSelectView(View):
    def __init__(self, u, g, opts, key, prot):
        super().__init__(timeout=120)
        self.add_item(LogSelect(u, g, opts, key, prot))

class LogSelect(Select):
    def __init__(self, u, g, opts, key, prot):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
        self.prot = prot
    
    async def callback(self, i):
        await db_set(i.guild.id, f'log_{self.key}', int(self.values[0]))
        v = ProtDetail(self.u, self.g, self.prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🖼️ ANTI-IMAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ImageConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmts = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy']
        e = discord.Embed(title="🖼️ Formats autorisés", color=C.BLUE)
        lines = []
        for f in fmts:
            status = "✅ Autorisé" if f in items else "❌ Bloqué"
            lines.append(f"`{f.upper()}` : {status}")
        e.description = "\n".join(lines)
        e.set_footer(text="Cliquez sur un format pour le toggle")
        return e
    
    @discord.ui.select(
        placeholder="Sélectionner un format à toggle...",
        options=[
            discord.SelectOption(label="PNG", value="png", emoji="🖼️"),
            discord.SelectOption(label="JPG", value="jpg", emoji="🖼️"),
            discord.SelectOption(label="JPEG", value="jpeg", emoji="🖼️"),
            discord.SelectOption(label="GIF (fichier)", value="gif", emoji="🎞️"),
            discord.SelectOption(label="WEBP", value="webp", emoji="🖼️"),
            discord.SelectOption(label="Tenor", value="tenor", emoji="🎬"),
            discord.SelectOption(label="Giphy", value="giphy", emoji="🎬")
        ]
    )
    async def toggle_format(self, i, s):
        c = await cfg(self.g.id)
        items = c.get('image_allowed', [])
        fmt = s.values[0]
        if fmt in items:
            items.remove(fmt)
        else:
            items.append(fmt)
        await db_set(self.g.id, 'image_allowed', items)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="✅ Tout autoriser", style=discord.ButtonStyle.success, row=1)
    async def allow_all(self, i, b):
        await db_set(self.g.id, 'image_allowed', ['png', 'jpg', 'jpeg', 'gif', 'webp', 'tenor', 'giphy'])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="❌ Tout bloquer", style=discord.ButtonStyle.danger, row=1)
    async def block_all(self, i, b):
        await db_set(self.g.id, 'image_allowed', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_image")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🤬 ANTI-BADWORDS CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class BadwordsConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        words = c.get('badwords_list', [])
        e = discord.Embed(title="🤬 Mots interdits", color=C.BLUE)
        if words:
            # Afficher tous les mots avec pagination si nécessaire
            all_words = ", ".join([f"`{w}`" for w in words])
            if len(all_words) > 4000:
                all_words = all_words[:4000] + "..."
            e.description = f"**{len(words)} mot(s) configuré(s):**\n\n{all_words}"
        else:
            e.description = "*Aucun mot interdit configuré*\n\nCliquez sur ➕ Ajouter pour ajouter des mots."
        return e
    
    @discord.ui.button(label="➕ Ajouter des mots", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        await i.response.send_modal(AddBadwordsModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer tout", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, i, b):
        await db_set(self.g.id, 'badwords_list', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_badwords")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddBadwordsModal(Modal, title="➕ Ajouter des mots interdits"):
    words = TextInput(
        label="Mots (séparés par des virgules)",
        placeholder="mot1, mot2, mot3, expression interdite, ...",
        style=discord.TextStyle.paragraph,
        max_length=4000
    )
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('badwords_list', [])
        new = [x.strip().lower() for x in self.words.value.split(',') if x.strip()]
        added = 0
        for w in new:
            if w and w not in items:
                items.append(w)
                added += 1
        await db_set(self.g.id, 'badwords_list', items)
        v = BadwordsConfigPanel(self.u, self.g)
        await i.response.edit_message(content=f"✅ {added} mot(s) ajouté(s)!", embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔗 ANTI-LINK CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class LinkConfigPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔗 Configuration Anti-Liens", color=C.BLUE)
        
        wl = c.get('link_whitelist', [])
        e.add_field(
            name=f"🌐 Whitelist domaines ({len(wl)})",
            value=f"`{', '.join(wl)}`" if wl else "*Aucun domaine autorisé*",
            inline=False
        )
        
        chs = c.get('link_allowed_channels', [])
        ch_txt = ", ".join([f"<#{x}>" for x in chs]) if chs else "*Aucun salon*"
        e.add_field(
            name=f"📍 Salons autorisés ({len(chs)})",
            value=ch_txt,
            inline=False
        )
        
        return e
    
    @discord.ui.button(label="➕ Ajouter domaines", style=discord.ButtonStyle.success, row=0)
    async def add_domain(self, i, b):
        await i.response.send_modal(AddDomainModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Vider whitelist", style=discord.ButtonStyle.danger, row=0)
    async def clear_wl(self, i, b):
        await db_set(self.g.id, 'link_whitelist', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="➕ Ajouter salon", style=discord.ButtonStyle.primary, row=1)
    async def add_chan(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = LinkChanSelectView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📍 Choisir un salon à autoriser", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="🗑️ Vider salons", style=discord.ButtonStyle.danger, row=1)
    async def clear_chs(self, i, b):
        await db_set(self.g.id, 'link_allowed_channels', [])
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == "anti_link")
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddDomainModal(Modal, title="➕ Ajouter des domaines"):
    doms = TextInput(
        label="Domaines (séparés par des virgules)",
        placeholder="youtube.com, twitter.com, discord.com",
        style=discord.TextStyle.paragraph,
        max_length=2000
    )
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        items = c.get('link_whitelist', [])
        new = [x.strip().lower() for x in self.doms.value.split(',') if x.strip()]
        added = 0
        for d in new:
            if d and d not in items:
                items.append(d)
                added += 1
        await db_set(self.g.id, 'link_whitelist', items)
        v = LinkConfigPanel(self.u, self.g)
        await i.response.edit_message(content=f"✅ {added} domaine(s) ajouté(s)!", embed=await v.embed(), view=v)

class LinkChanSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(LinkChanSelect(u, g, opts))

class LinkChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        c = await cfg(i.guild.id)
        chs = c.get('link_allowed_channels', [])
        chid = int(self.values[0])
        if chid not in chs:
            chs.append(chid)
            await db_set(i.guild.id, 'link_allowed_channels', chs)
        v = LinkConfigPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚙️ NUMBER CONFIG MODAL
# ═══════════════════════════════════════════════════════════════════════════════

class NumberConfigModal(Modal, title="⚙️ Configuration"):
    val = TextInput(label="Valeur", placeholder="5", max_length=3)
    
    def __init__(self, g, u, key):
        super().__init__()
        self.g = g
        self.u = u
        self.key = key
        if key == "anti_spam":
            self.val.label = "Nombre max de messages"
            self.val.placeholder = "5"
        elif key == "anti_caps":
            self.val.label = "Pourcentage max de majuscules"
            self.val.placeholder = "70"
        elif key == "anti_newaccount":
            self.val.label = "Âge minimum du compte (jours)"
            self.val.placeholder = "7"
    
    async def on_submit(self, i):
        v = int(self.val.value) if self.val.value.isdigit() else 5
        if self.key == "anti_spam":
            await db_set(self.g.id, 'spam_max', max(1, min(20, v)))
        elif self.key == "anti_caps":
            await db_set(self.g.id, 'caps_percent', max(10, min(100, v)))
        elif self.key == "anti_newaccount":
            await db_set(self.g.id, 'newaccount_days', max(1, min(365, v)))
        prot = next(p for p in PROTS if p[0] == self.key)
        vw = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await vw.embed(), view=vw)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚡ ACTION CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

class ActionConfigPanel(View):
    def __init__(self, u, g, key):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.key = key
    
    async def embed(self):
        c = await cfg(self.g.id)
        ak = 'phishing_action' if self.key == "anti_phishing" else 'scam_action'
        current = c.get(ak, 'ban' if 'phishing' in ak else 'mute')
        e = discord.Embed(title=f"⚡ Action pour {self.key.replace('anti_', '').title()}", color=C.BLUE)
        e.description = f"**Action actuelle:** `{current.upper()}`\n\nChoisissez l'action à effectuer:"
        return e
    
    @discord.ui.button(label="🔇 Mute", style=discord.ButtonStyle.primary, row=0)
    async def mute(self, i, b):
        await self._set(i, 'mute')
    
    @discord.ui.button(label="👢 Kick", style=discord.ButtonStyle.secondary, row=0)
    async def kick(self, i, b):
        await self._set(i, 'kick')
    
    @discord.ui.button(label="🔨 Ban", style=discord.ButtonStyle.danger, row=0)
    async def ban(self, i, b):
        await self._set(i, 'ban')
    
    async def _set(self, i, act):
        ak = 'phishing_action' if self.key == "anti_phishing" else 'scam_action'
        await db_set(self.g.id, ak, act)
        prot = next(p for p in PROTS if p[0] == self.key)
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        prot = next(p for p in PROTS if p[0] == self.key)
        v = ProtDetail(self.u, self.g, prot)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔨 MODÉRATION PANEL
# ═══════════════════════════════════════════════════════════════════════════════

async def send_mod_log(guild, action, mod, target, reason=None, duration=None, extra=None):
    """Envoie un log de modération"""
    try:
        c = await cfg(guild.id)
        log_ch = guild.get_channel(c.get('mod_log_channel', 0))
        if not log_ch:
            return
        
        colors = {'warn': C.YELLOW, 'unwarn': C.GREEN, 'mute': C.ORANGE, 'unmute': C.GREEN, 'infractions': C.BLUE}
        emojis = {'warn': '⚠️', 'unwarn': '✅', 'mute': '🔇', 'unmute': '🔊', 'infractions': '📋'}
        titles = {'warn': 'Avertissement', 'unwarn': 'Warn supprimé', 'mute': 'Mute', 'unmute': 'Unmute', 'infractions': 'Consultation infractions'}
        
        e = discord.Embed(
            title=f"{emojis.get(action, '🔨')} {titles.get(action, action.upper())}",
            color=colors.get(action, C.ORANGE),
            timestamp=now()
        )
        e.add_field(name="👮 Modérateur", value=f"{mod.mention}\n`{mod.id}`", inline=True)
        e.add_field(name="👤 Membre", value=f"{target.mention}\n`{target.id}`", inline=True)
        
        if duration:
            e.add_field(name="⏱️ Durée", value=duration, inline=True)
        if reason:
            e.add_field(name="📝 Raison", value=reason[:1024], inline=False)
        if extra:
            e.add_field(name="ℹ️ Info", value=extra, inline=False)
        
        e.set_thumbnail(url=target.display_avatar.url)
        await log_ch.send(embed=e)
    except Exception as ex:
        print(f"[MOD LOG ERROR] {ex}")

class ModerationPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔨 Modération", color=C.ORANGE)
        e.description = "Configurez les rôles et logs pour les commandes de modération."
        
        # Salon logs
        log_ch = self.g.get_channel(c.get('mod_log_channel', 0))
        e.add_field(
            name="📜 Salon Logs",
            value=log_ch.mention if log_ch else "❌ Non configuré",
            inline=False
        )
        
        # Warn
        warn_role = self.g.get_role(c.get('mod_warn_role', 0))
        e.add_field(
            name="⚠️ /warn & /unwarn",
            value=f"Rôle: {warn_role.mention if warn_role else '❌ Non configuré'}",
            inline=True
        )
        
        # Mute
        mute_role = self.g.get_role(c.get('mod_mute_role', 0))
        e.add_field(
            name="🔇 /mute & /unmute",
            value=f"Rôle: {mute_role.mention if mute_role else '❌ Non configuré'}",
            inline=True
        )
        
        # Infractions
        inf_role = self.g.get_role(c.get('mod_infractions_role', 0))
        e.add_field(
            name="📋 /infractions",
            value=f"Rôle: {inf_role.mention if inf_role else '❌ Non configuré'}",
            inline=True
        )
        
        e.set_footer(text="Les admins et le owner ont toujours accès à toutes les commandes")
        return e
    
    @discord.ui.button(label="📜 Salon Logs", style=discord.ButtonStyle.success, row=0)
    async def set_logs(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        opts.insert(0, discord.SelectOption(label="❌ Aucun log", value="0"))
        v = ModLogSelectView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📜 Salon des logs modération", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="⚠️ Rôle /warn", style=discord.ButtonStyle.primary, row=1)
    async def set_warn(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Aucun rôle", value="0"))
        v = ModRoleSelectView(self.u, self.g, opts, 'mod_warn_role')
        await i.response.edit_message(embed=discord.Embed(title="⚠️ Rôle pour /warn & /unwarn", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="🔇 Rôle /mute", style=discord.ButtonStyle.primary, row=1)
    async def set_mute(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Aucun rôle", value="0"))
        v = ModRoleSelectView(self.u, self.g, opts, 'mod_mute_role')
        await i.response.edit_message(embed=discord.Embed(title="🔇 Rôle pour /mute & /unmute", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="📋 Rôle /infractions", style=discord.ButtonStyle.primary, row=1)
    async def set_inf(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Aucun rôle", value="0"))
        v = ModRoleSelectView(self.u, self.g, opts, 'mod_infractions_role')
        await i.response.edit_message(embed=discord.Embed(title="📋 Rôle pour /infractions", color=C.ORANGE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ModLogSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ModLogSelect(u, g, opts))

class ModLogSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'mod_log_channel', int(self.values[0]))
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class ModRoleSelectView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(ModRoleSelect(u, g, opts, key))

class ModRoleSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        v = ModerationPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👑 IMMUNITÉS (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

class ImmunePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?', (self.g.id,)) as c:
                rids = [r[0] for r in await c.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?', (self.g.id,)) as c:
                uids = [r[0] for r in await c.fetchall()]
        e = discord.Embed(title="👑 Immunités", color=C.YELLOW)
        e.add_field(name=f"🎭 Rôles immunisés ({len(rids)})", value=", ".join([f"<@&{r}>" for r in rids]) or "*Aucun*", inline=False)
        e.add_field(name=f"👤 Utilisateurs immunisés ({len(uids)})", value=", ".join([f"<@{u}>" for u in uids]) or "*Aucun*", inline=False)
        return e
    
    @discord.ui.button(label="➕ Ajouter rôle", style=discord.ButtonStyle.success, row=0)
    async def add_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        await i.response.edit_message(embed=discord.Embed(title="👑 Ajouter un rôle immunisé", color=C.YELLOW), view=ImmuneRoleView(self.u, self.g, opts))
    
    @discord.ui.button(label="➕ Ajouter user", style=discord.ButtonStyle.primary, row=0)
    async def add_user(self, i, b):
        await i.response.send_modal(AddImmuneUserModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Tout supprimer", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, i, b):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM immune_roles WHERE guild_id=?', (self.g.id,))
            await db.execute('DELETE FROM immune_users WHERE guild_id=?', (self.g.id,))
            await db.commit()
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ImmuneRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ImmuneRoleSelect(u, g, opts))

class ImmuneRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES(?,?)', (i.guild.id, int(self.values[0])))
            await db.commit()
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddImmuneUserModal(Modal, title="➕ Ajouter un utilisateur immunisé"):
    uid = TextInput(label="ID de l'utilisateur", placeholder="123456789012345678")
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            user_id = int(self.uid.value)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT OR IGNORE INTO immune_users VALUES(?,?)', (self.g.id, user_id))
                await db.commit()
        except: pass
        v = ImmunePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           ⚡ COMMANDES PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class CommandsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="⚡ Commandes Personnalisées", color=C.PURPLE)
        e.description = "Configurez les commandes spéciales du serveur."
        
        # RellSeas
        rellseas_user = self.g.get_member(c.get('rellseas_user', 0))
        rellseas_role = self.g.get_role(c.get('rellseas_role', 0))
        e.add_field(
            name="🎭 RellSeas",
            value=f"👤 {rellseas_user.mention if rellseas_user else '❌'}\n🎭 {rellseas_role.mention if rellseas_role else '❌'}",
            inline=True
        )
        
        # Suggestions
        sugg_role = self.g.get_role(c.get('suggestion_role', 0))
        sugg_ch = self.g.get_channel(c.get('suggestion_channel', 0))
        e.add_field(
            name="💡 Suggestions",
            value=f"🎭 {sugg_role.mention if sugg_role else 'Tous'}\n📍 {sugg_ch.mention if sugg_ch else '❌'}",
            inline=True
        )
        
        # Trade
        trade_role = self.g.get_role(c.get('trade_role', 0))
        trade_ch = self.g.get_channel(c.get('trade_channel', 0))
        trade_cd = c.get('trade_cooldown', 1)
        trade_unit = c.get('trade_cooldown_unit', 'heures')
        e.add_field(
            name="🔄 Trade",
            value=f"🎭 {trade_role.mention if trade_role else 'Tous'}\n📍 {trade_ch.mention if trade_ch else '❌'}\n⏱️ {trade_cd} {trade_unit}",
            inline=True
        )
        
        return e
    
    @discord.ui.button(label="🎭 RellSeas", style=discord.ButtonStyle.primary, row=0)
    async def rellseas(self, i, b):
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="💡 Suggestions", style=discord.ButtonStyle.primary, row=0)
    async def suggestions(self, i, b):
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🔄 Trade", style=discord.ButtonStyle.primary, row=0)
    async def trade(self, i, b):
        v = TradePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎭 RELLSEAS
# ═══════════════════════════════════════════════════════════════════════════════

class RellSeasPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎭 Configuration RellSeas", color=C.PURPLE)
        
        rellseas_user = self.g.get_member(c.get('rellseas_user', 0))
        rellseas_role = self.g.get_role(c.get('rellseas_role', 0))
        warn_ch = self.g.get_channel(c.get('rellseas_warn_channel', 0))
        log_ch = self.g.get_channel(c.get('rellseas_log_channel', 0))
        
        e.description = "L'utilisateur autorisé reçoit **automatiquement** le rôle Realsy et peut le donner à d'autres."
        
        e.add_field(name="👤 Utilisateur autorisé", value=rellseas_user.mention if rellseas_user else "❌ Non configuré", inline=False)
        e.add_field(name="🎭 Rôle Realsy", value=rellseas_role.mention if rellseas_role else "❌ Non configuré", inline=False)
        e.add_field(name="⚠️ Salon warn", value=warn_ch.mention if warn_ch else "❌", inline=True)
        e.add_field(name="📜 Salon logs", value=log_ch.mention if log_ch else "❌", inline=True)
        
        e.set_footer(text="⏱️ 7 jours inactif = Warn | 14 jours = Rôle retiré")
        return e
    
    @discord.ui.button(label="👤 Utilisateur", style=discord.ButtonStyle.primary, row=0)
    async def set_user(self, i, b):
        await i.response.send_modal(RellSeasUserModal(self.g, self.u))
    
    @discord.ui.button(label="🎭 Rôle Realsy", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        v = RellSeasRoleView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Choisir le rôle Realsy", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="⚠️ Salon Warn", style=discord.ButtonStyle.secondary, row=1)
    async def set_warn_ch(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = RellSeasChanView(self.u, self.g, opts, 'rellseas_warn_channel')
        await i.response.edit_message(embed=discord.Embed(title="⚠️ Salon des warns", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📜 Salon Logs", style=discord.ButtonStyle.secondary, row=1)
    async def set_log_ch(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = RellSeasChanView(self.u, self.g, opts, 'rellseas_log_channel')
        await i.response.edit_message(embed=discord.Embed(title="📜 Salon des logs", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasUserModal(Modal, title="👤 Utilisateur RellSeas"):
    uid = TextInput(label="ID de l'utilisateur", placeholder="123456789012345678")
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            user_id = int(self.uid.value)
            await db_set(self.g.id, 'rellseas_user', user_id)
            
            # Donner automatiquement le rôle à l'utilisateur autorisé
            c = await cfg(self.g.id)
            role = self.g.get_role(c.get('rellseas_role', 0))
            member = self.g.get_member(user_id)
            
            if role and member and role not in member.roles:
                try:
                    await member.add_roles(role, reason="RellSeas - Utilisateur autorisé")
                    # Enregistrer dans le tracking
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('''INSERT OR REPLACE INTO realsy_tracking 
                            (guild_id, user_id, last_activity, warn_count) VALUES (?, ?, ?, 0)''',
                            (self.g.id, user_id, now().isoformat()))
                        await db.commit()
                except:
                    pass
        except:
            pass
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(RellSeasRoleSelect(u, g, opts))

class RellSeasRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'rellseas_role', int(self.values[0]))
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class RellSeasChanView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(RellSeasChanSelect(u, g, opts, key))

class RellSeasChanSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        v = RellSeasPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           💡 SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class SuggestionPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="💡 Configuration Suggestions", color=C.PURPLE)
        
        sugg_role = self.g.get_role(c.get('suggestion_role', 0))
        sugg_ch = self.g.get_channel(c.get('suggestion_channel', 0))
        sugg_cd = c.get('suggestion_cooldown', 1)
        sugg_unit = c.get('suggestion_cooldown_unit', 'jours')
        
        e.add_field(name="🎭 Rôle autorisé", value=sugg_role.mention if sugg_role else "❌ Non configuré (tout le monde)", inline=False)
        e.add_field(name="📍 Salon des suggestions", value=sugg_ch.mention if sugg_ch else "❌ Non configuré", inline=False)
        e.add_field(name="⏱️ Cooldown", value=f"{sugg_cd} {sugg_unit}", inline=False)
        
        e.set_footer(text="Commande: /suggestion")
        return e
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Tout le monde", value="0"))
        v = SuggRoleView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Rôle autorisé", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = SuggChanView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon des suggestions", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="⏱️ Cooldown", style=discord.ButtonStyle.secondary, row=1)
    async def set_cooldown(self, i, b):
        await i.response.send_modal(SuggCooldownModal(self.g, self.u))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SuggRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(SuggRoleSelect(u, g, opts))

class SuggRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'suggestion_role', int(self.values[0]))
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SuggChanView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(SuggChanSelect(u, g, opts))

class SuggChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'suggestion_channel', int(self.values[0]))
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SuggCooldownModal(Modal, title="⏱️ Cooldown Suggestions"):
    duree = TextInput(label="Durée (nombre)", placeholder="1", default="1", max_length=3)
    unite = TextInput(label="Unité (jours ou semaines)", placeholder="jours", default="jours", max_length=10)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            cd = max(1, int(self.duree.value))
            unit = self.unite.value.lower()
            if unit not in ['jours', 'semaines']:
                unit = 'jours'
            await db_set(self.g.id, 'suggestion_cooldown', cd)
            await db_set(self.g.id, 'suggestion_cooldown_unit', unit)
        except: pass
        v = SuggestionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🔄 TRADE PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class TradePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔄 Configuration Trade", color=C.PURPLE)
        
        trade_role = self.g.get_role(c.get('trade_role', 0))
        trade_ch = self.g.get_channel(c.get('trade_channel', 0))
        trade_cd = c.get('trade_cooldown', 1)
        trade_unit = c.get('trade_cooldown_unit', 'heures')
        
        e.description = "Configurez le système d'échange pour votre serveur.\n\n*Les utilisateurs pourront créer des annonces de trade avec `/trade`*"
        
        e.add_field(name="🎭 Rôle autorisé", value=trade_role.mention if trade_role else "Tout le monde", inline=True)
        e.add_field(name="📍 Salon", value=trade_ch.mention if trade_ch else "❌ Non configuré", inline=True)
        e.add_field(name="⏱️ Cooldown", value=f"{trade_cd} {trade_unit}", inline=True)
        
        e.set_footer(text="Commande: /trade")
        return e
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        opts.insert(0, discord.SelectOption(label="❌ Tout le monde", value="0"))
        v = TradeRoleView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Rôle autorisé", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = TradeChanView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon des trades", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="⏱️ Cooldown", style=discord.ButtonStyle.primary, row=0)
    async def set_cooldown(self, i, b):
        await i.response.send_modal(TradeCooldownModal(self.g, self.u))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = CommandsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TradeRoleView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TradeRoleSelect(u, g, opts))

class TradeRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'trade_role', int(self.values[0]))
        v = TradePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TradeChanView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TradeChanSelect(u, g, opts))

class TradeChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'trade_channel', int(self.values[0]))
        v = TradePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TradeCooldownModal(Modal, title="⏱️ Cooldown Trade"):
    duree = TextInput(label="Durée (nombre)", placeholder="1", default="1", max_length=3)
    unite = TextInput(label="Unité (secondes/minutes/heures/jours)", placeholder="heures", default="heures", max_length=10)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        try:
            cd = max(1, int(self.duree.value))
            unit = self.unite.value.lower()
            if unit not in ['secondes', 'minutes', 'heures', 'jours', 'semaines']:
                unit = 'heures'
            await db_set(self.g.id, 'trade_cooldown', cd)
            await db_set(self.g.id, 'trade_cooldown_unit', unit)
        except:
            pass
        
        v = TradePanel(self.u, self.g)
        e = await v.embed()
        await i.response.edit_message(embed=e, view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 PUBLICITÉ / NOTIFICATIONS SOCIALES
# ═══════════════════════════════════════════════════════════════════════════════

# Cache pour éviter de republier les mêmes posts
posted_content = {}

class AdsPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📢 Publicité & Notifications", color=C.PURPLE)
        e.description = "Recevez les dernières publications de vos créateurs préférés!"
        
        # YouTube
        yt_ch = self.g.get_channel(c.get('ads_youtube_channel', 0))
        yt_feeds = c.get('ads_youtube_feeds', [])
        e.add_field(
            name="🔴 YouTube",
            value=f"📍 {yt_ch.mention if yt_ch else '❌'}\n📺 {len(yt_feeds)} chaîne(s)",
            inline=True
        )
        
        # Twitch
        tw_ch = self.g.get_channel(c.get('ads_twitch_channel', 0))
        tw_feeds = c.get('ads_twitch_feeds', [])
        e.add_field(
            name="🟣 Twitch",
            value=f"📍 {tw_ch.mention if tw_ch else '❌'}\n🎮 {len(tw_feeds)} streamer(s)",
            inline=True
        )
        
        # Twitter/X
        x_ch = self.g.get_channel(c.get('ads_twitter_channel', 0))
        x_feeds = c.get('ads_twitter_feeds', [])
        e.add_field(
            name="🐦 Twitter/X",
            value=f"📍 {x_ch.mention if x_ch else '❌'}\n👤 {len(x_feeds)} compte(s)",
            inline=True
        )
        
        # Reddit
        rd_ch = self.g.get_channel(c.get('ads_reddit_channel', 0))
        rd_feeds = c.get('ads_reddit_feeds', [])
        e.add_field(
            name="🟠 Reddit",
            value=f"📍 {rd_ch.mention if rd_ch else '❌'}\n📰 {len(rd_feeds)} subreddit(s)",
            inline=True
        )
        
        # Discord
        dc_ch = self.g.get_channel(c.get('ads_discord_channel', 0))
        dc_feeds = c.get('ads_discord_feeds', [])
        e.add_field(
            name="📡 Discord",
            value=f"📍 {dc_ch.mention if dc_ch else '❌'}\n💬 {len(dc_feeds)} salon(s)",
            inline=True
        )
        
        # RoSocial
        rs_ch = self.g.get_channel(c.get('ads_rosocial_channel', 0))
        rs_feeds = c.get('ads_rosocial_feeds', [])
        e.add_field(
            name="🎮 RoSocial",
            value=f"📍 {rs_ch.mention if rs_ch else '❌'}\n👤 {len(rs_feeds)} profil(s)",
            inline=True
        )
        
        e.set_footer(text="💡 Les notifications sont vérifiées toutes les 5 minutes")
        return e
    
    @discord.ui.button(label="🔴 YouTube", style=discord.ButtonStyle.danger, row=0)
    async def youtube(self, i, b):
        v = AdsYouTubePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🟣 Twitch", style=discord.ButtonStyle.primary, row=0)
    async def twitch(self, i, b):
        v = AdsTwitchPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🐦 Twitter/X", style=discord.ButtonStyle.secondary, row=0)
    async def twitter(self, i, b):
        v = AdsTwitterPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🟠 Reddit", style=discord.ButtonStyle.secondary, row=0)
    async def reddit(self, i, b):
        v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📡 Discord", style=discord.ButtonStyle.primary, row=1)
    async def discord_btn(self, i, b):
        v = AdsDiscordPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🎮 RoSocial", style=discord.ButtonStyle.success, row=1)
    async def rosocial(self, i, b):
        v = AdsRoSocialPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

# ─────────────────────────────── YOUTUBE ───────────────────────────────

class AdsYouTubePanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🔴 YouTube - Notifications", color=0xFF0000)
        
        yt_ch = self.g.get_channel(c.get('ads_youtube_channel', 0))
        yt_feeds = c.get('ads_youtube_feeds', [])
        
        e.add_field(name="📍 Salon", value=yt_ch.mention if yt_ch else "❌ Non configuré", inline=False)
        
        if yt_feeds:
            feeds_txt = "\n".join([f"• `{f['name']}` ({f['id'][:15]}...)" for f in yt_feeds[:10]])
            e.add_field(name=f"📺 Chaînes suivies ({len(yt_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="📺 Chaînes suivies", value="*Aucune chaîne configurée*", inline=False)
        
        e.set_footer(text="💡 Utilisez l'ID de chaîne YouTube (ex: UCxxxx)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_youtube_channel', 'youtube')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon YouTube", color=0xFF0000), view=v)
    
    @discord.ui.button(label="➕ Ajouter Chaîne", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsYouTubeAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Chaîne", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_youtube_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucune chaîne à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f['name'][:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_youtube_feeds', 'youtube')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer une chaîne", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsYouTubeAddModal(Modal, title="➕ Ajouter une chaîne YouTube"):
    name = TextInput(label="Nom de la chaîne", placeholder="Ex: MrBeast", max_length=50)
    channel_id = TextInput(label="ID de la chaîne YouTube", placeholder="UCX6OQ3DkcsbYNE6H8uQQuVA", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_youtube_feeds', [])
        
        # Vérifier si déjà ajouté
        if any(f['id'] == self.channel_id.value for f in feeds):
            return await i.response.send_message("❌ Cette chaîne est déjà ajoutée!", ephemeral=True)
        
        feeds.append({'name': self.name.value, 'id': self.channel_id.value})
        await db_set(self.g.id, 'ads_youtube_feeds', feeds)
        
        v = AdsYouTubePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── TWITCH ───────────────────────────────

class AdsTwitchPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🟣 Twitch - Notifications", color=0x9146FF)
        
        tw_ch = self.g.get_channel(c.get('ads_twitch_channel', 0))
        tw_feeds = c.get('ads_twitch_feeds', [])
        
        e.add_field(name="📍 Salon", value=tw_ch.mention if tw_ch else "❌ Non configuré", inline=False)
        
        if tw_feeds:
            feeds_txt = "\n".join([f"• `{f}`" for f in tw_feeds[:10]])
            e.add_field(name=f"🎮 Streamers suivis ({len(tw_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="🎮 Streamers suivis", value="*Aucun streamer configuré*", inline=False)
        
        e.set_footer(text="💡 Utilisez le nom d'utilisateur Twitch (ex: ninja)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_twitch_channel', 'twitch')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon Twitch", color=0x9146FF), view=v)
    
    @discord.ui.button(label="➕ Ajouter Streamer", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsTwitchAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Streamer", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitch_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun streamer à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_twitch_feeds', 'twitch')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un streamer", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsTwitchAddModal(Modal, title="➕ Ajouter un streamer Twitch"):
    username = TextInput(label="Nom d'utilisateur Twitch", placeholder="Ex: ninja", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitch_feeds', [])
        
        username = self.username.value.lower().strip()
        if username in feeds:
            return await i.response.send_message("❌ Ce streamer est déjà ajouté!", ephemeral=True)
        
        feeds.append(username)
        await db_set(self.g.id, 'ads_twitch_feeds', feeds)
        
        v = AdsTwitchPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── REDDIT ───────────────────────────────

class AdsRedditPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🟠 Reddit - Notifications", color=0xFF4500)
        
        rd_ch = self.g.get_channel(c.get('ads_reddit_channel', 0))
        rd_feeds = c.get('ads_reddit_feeds', [])
        
        e.add_field(name="📍 Salon", value=rd_ch.mention if rd_ch else "❌ Non configuré", inline=False)
        
        if rd_feeds:
            feeds_txt = "\n".join([f"• r/{f}" for f in rd_feeds[:10]])
            e.add_field(name=f"📰 Subreddits suivis ({len(rd_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="📰 Subreddits suivis", value="*Aucun subreddit configuré*", inline=False)
        
        e.set_footer(text="💡 Entrez le nom du subreddit sans 'r/' (ex: gaming)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_reddit_channel', 'reddit')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon Reddit", color=0xFF4500), view=v)
    
    @discord.ui.button(label="➕ Ajouter Subreddit", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsRedditAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Subreddit", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_reddit_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun subreddit à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f"r/{f}"[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_reddit_feeds', 'reddit')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un subreddit", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsRedditAddModal(Modal, title="➕ Ajouter un subreddit"):
    subreddit = TextInput(label="Nom du subreddit (sans r/)", placeholder="Ex: gaming", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_reddit_feeds', [])
        
        sub = self.subreddit.value.lower().strip().replace('r/', '')
        if sub in feeds:
            return await i.response.send_message("❌ Ce subreddit est déjà ajouté!", ephemeral=True)
        
        feeds.append(sub)
        await db_set(self.g.id, 'ads_reddit_feeds', feeds)
        
        v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── TWITTER/X ───────────────────────────────

# Liste d'instances Nitter fonctionnelles (fallback)
NITTER_INSTANCES = [
    "nitter.poast.org",
    "xcancel.com", 
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

class AdsTwitterPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🐦 Twitter/X - Notifications", color=0x1DA1F2)
        
        x_ch = self.g.get_channel(c.get('ads_twitter_channel', 0))
        x_feeds = c.get('ads_twitter_feeds', [])
        
        e.add_field(name="📍 Salon", value=x_ch.mention if x_ch else "❌ Non configuré", inline=False)
        
        if x_feeds:
            feeds_txt = "\n".join([f"• @{f}" for f in x_feeds[:10]])
            e.add_field(name=f"👤 Comptes suivis ({len(x_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="👤 Comptes suivis", value="*Aucun compte configuré*", inline=False)
        
        e.set_footer(text="💡 Entrez le nom d'utilisateur sans @ (ex: elonmusk)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_twitter_channel', 'twitter')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon Twitter", color=0x1DA1F2), view=v)
    
    @discord.ui.button(label="➕ Ajouter Compte", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsTwitterAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Compte", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitter_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun compte à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f"@{f}"[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_twitter_feeds', 'twitter')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un compte", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsTwitterAddModal(Modal, title="➕ Ajouter un compte Twitter"):
    username = TextInput(label="Nom d'utilisateur (sans @)", placeholder="Ex: elonmusk", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_twitter_feeds', [])
        
        username = self.username.value.lower().strip().replace('@', '')
        if username in feeds:
            return await i.response.send_message("❌ Ce compte est déjà ajouté!", ephemeral=True)
        
        feeds.append(username)
        await db_set(self.g.id, 'ads_twitter_feeds', feeds)
        
        v = AdsTwitterPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── DISCORD CHANNELS ───────────────────────────────

class AdsDiscordPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📡 Discord - Suivi de Salons", color=C.BLURPLE)
        
        dc_ch = self.g.get_channel(c.get('ads_discord_channel', 0))
        dc_feeds = c.get('ads_discord_feeds', [])
        
        e.add_field(name="📍 Salon de destination", value=dc_ch.mention if dc_ch else "❌ Non configuré", inline=False)
        
        if dc_feeds:
            feeds_txt = []
            for f in dc_feeds[:10]:
                ch = bot.get_channel(int(f['channel_id']))
                if ch:
                    feeds_txt.append(f"• #{ch.name} ({ch.guild.name[:15]})")
                else:
                    feeds_txt.append(f"• `{f['channel_id']}` (inaccessible)")
            e.add_field(name=f"💬 Salons suivis ({len(dc_feeds)})", value="\n".join(feeds_txt), inline=False)
        else:
            e.add_field(name="💬 Salons suivis", value="*Aucun salon configuré*", inline=False)
        
        e.set_footer(text="⚠️ Le bot doit être présent sur le serveur du salon à suivre")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_discord_channel', 'discord')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon de destination", color=C.BLURPLE), view=v)
    
    @discord.ui.button(label="➕ Ajouter Salon", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsDiscordAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Salon", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_discord_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun salon à supprimer", ephemeral=True)
        opts = []
        for idx, f in enumerate(feeds[:25]):
            ch = bot.get_channel(int(f['channel_id']))
            label = f"#{ch.name}"[:25] if ch else f"ID: {f['channel_id']}"[:25]
            opts.append(discord.SelectOption(label=label, value=str(idx)))
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_discord_feeds', 'discord')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un salon", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsDiscordAddModal(Modal, title="➕ Suivre un salon Discord"):
    channel_id = TextInput(label="ID du salon à suivre", placeholder="Ex: 1234567890123456789", max_length=25)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_discord_feeds', [])
        
        try:
            ch_id = int(self.channel_id.value.strip())
        except:
            return await i.response.send_message("❌ ID invalide!", ephemeral=True)
        
        # Vérifier si le bot a accès au salon
        ch = bot.get_channel(ch_id)
        if not ch:
            return await i.response.send_message("❌ Salon introuvable! Le bot doit être présent sur le serveur.", ephemeral=True)
        
        # Vérifier si déjà ajouté
        if any(f['channel_id'] == str(ch_id) for f in feeds):
            return await i.response.send_message("❌ Ce salon est déjà suivi!", ephemeral=True)
        
        feeds.append({'channel_id': str(ch_id), 'guild_name': ch.guild.name, 'channel_name': ch.name})
        await db_set(self.g.id, 'ads_discord_feeds', feeds)
        
        v = AdsDiscordPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── ROSOCIAL ───────────────────────────────

class AdsRoSocialPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎮 RoSocial - Notifications", color=0x00D4AA)
        
        rs_ch = self.g.get_channel(c.get('ads_rosocial_channel', 0))
        rs_feeds = c.get('ads_rosocial_feeds', [])
        
        e.add_field(name="📍 Salon", value=rs_ch.mention if rs_ch else "❌ Non configuré", inline=False)
        
        if rs_feeds:
            feeds_txt = "\n".join([f"• `{f}`" for f in rs_feeds[:10]])
            e.add_field(name=f"👤 Profils suivis ({len(rs_feeds)})", value=feeds_txt, inline=False)
        else:
            e.add_field(name="👤 Profils suivis", value="*Aucun profil configuré*", inline=False)
        
        e.set_footer(text="💡 Entrez le nom d'utilisateur RoSocial (ex: GoRipe)")
        return e
    
    @discord.ui.button(label="📍 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = AdsChannelSelectView(self.u, self.g, opts, 'ads_rosocial_channel', 'rosocial')
        await i.response.edit_message(embed=discord.Embed(title="📍 Salon RoSocial", color=0x00D4AA), view=v)
    
    @discord.ui.button(label="➕ Ajouter Profil", style=discord.ButtonStyle.success, row=0)
    async def add_feed(self, i, b):
        await i.response.send_modal(AdsRoSocialAddModal(self.g, self.u))
    
    @discord.ui.button(label="🗑️ Supprimer Profil", style=discord.ButtonStyle.danger, row=0)
    async def remove_feed(self, i, b):
        c = await cfg(self.g.id)
        feeds = c.get('ads_rosocial_feeds', [])
        if not feeds:
            return await i.response.send_message("❌ Aucun profil à supprimer", ephemeral=True)
        opts = [discord.SelectOption(label=f[:25], value=str(idx)) for idx, f in enumerate(feeds[:25])]
        v = AdsFeedRemoveView(self.u, self.g, opts, 'ads_rosocial_feeds', 'rosocial')
        await i.response.edit_message(embed=discord.Embed(title="🗑️ Supprimer un profil", color=C.RED), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = AdsPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsRoSocialAddModal(Modal, title="➕ Ajouter un profil RoSocial"):
    username = TextInput(label="Nom d'utilisateur RoSocial", placeholder="Ex: GoRipe", max_length=30)
    
    def __init__(self, g, u):
        super().__init__()
        self.g = g
        self.u = u
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        feeds = c.get('ads_rosocial_feeds', [])
        
        username = self.username.value.strip()
        if username.lower() in [f.lower() for f in feeds]:
            return await i.response.send_message("❌ Ce profil est déjà ajouté!", ephemeral=True)
        
        feeds.append(username)
        await db_set(self.g.id, 'ads_rosocial_feeds', feeds)
        
        v = AdsRoSocialPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ─────────────────────────────── COMMON VIEWS ───────────────────────────────

class AdsChannelSelectView(View):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(timeout=120)
        self.add_item(AdsChannelSelect(u, g, opts, key, platform))

class AdsChannelSelect(Select):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
        self.platform = platform
    
    async def callback(self, i):
        await db_set(i.guild.id, self.key, int(self.values[0]))
        if self.platform == 'youtube':
            v = AdsYouTubePanel(self.u, self.g)
        elif self.platform == 'twitch':
            v = AdsTwitchPanel(self.u, self.g)
        elif self.platform == 'twitter':
            v = AdsTwitterPanel(self.u, self.g)
        elif self.platform == 'discord':
            v = AdsDiscordPanel(self.u, self.g)
        elif self.platform == 'rosocial':
            v = AdsRoSocialPanel(self.u, self.g)
        else:
            v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AdsFeedRemoveView(View):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(timeout=120)
        self.add_item(AdsFeedRemoveSelect(u, g, opts, key, platform))

class AdsFeedRemoveSelect(Select):
    def __init__(self, u, g, opts, key, platform):
        super().__init__(placeholder="Sélectionner à supprimer...", options=opts)
        self.u = u
        self.g = g
        self.key = key
        self.platform = platform
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        feeds = c.get(self.key, [])
        idx = int(self.values[0])
        if 0 <= idx < len(feeds):
            feeds.pop(idx)
            await db_set(self.g.id, self.key, feeds)
        
        if self.platform == 'youtube':
            v = AdsYouTubePanel(self.u, self.g)
        elif self.platform == 'twitch':
            v = AdsTwitchPanel(self.u, self.g)
        elif self.platform == 'twitter':
            v = AdsTwitterPanel(self.u, self.g)
        elif self.platform == 'discord':
            v = AdsDiscordPanel(self.u, self.g)
        elif self.platform == 'rosocial':
            v = AdsRoSocialPanel(self.u, self.g)
        else:
            v = AdsRedditPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📊 STATISTIQUES PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class StatPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="📊 Statistiques & Activité", color=C.PURPLE)
        e.description = "Gérez l'activité des membres et visualisez les statistiques du serveur."
        
        # Config actuelle
        stat_cfg = c.get('stat_config', {})
        
        # Actions multiples
        action_labels = {'ping': '🔔 Ping', 'remove_role': '🎭 Rôle', 'kick': '👢 Kick'}
        
        actions_7d = stat_cfg.get('actions_7d', [])
        actions_30d = stat_cfg.get('actions_30d', [])
        
        actions_7d_txt = " + ".join([action_labels.get(a, a) for a in actions_7d]) if actions_7d else "❌ Aucune"
        actions_30d_txt = " + ".join([action_labels.get(a, a) for a in actions_30d]) if actions_30d else "❌ Aucune"
        
        role_id = stat_cfg.get('activity_role', 0)
        notif_ch = self.g.get_channel(stat_cfg.get('notif_channel', 0))
        recovery_ch = self.g.get_channel(stat_cfg.get('recovery_channel', 0))
        
        role = self.g.get_role(role_id) if role_id else None
        
        e.add_field(
            name="⚙️ Configuration",
            value=f"**Actions 7j:** {actions_7d_txt}\n"
                  f"**Actions 30j:** {actions_30d_txt}\n"
                  f"**Rôle:** {role.mention if role else '❌'} | **Notifs:** {notif_ch.mention if notif_ch else '❌'} | **Récup:** {recovery_ch.mention if recovery_ch else '❌'}",
            inline=False
        )
        
        # Compter les membres AFK
        afk_7d, afk_30d = await self.count_afk_members()
        e.add_field(name="😴 AFK 7 jours", value=f"**{afk_7d}** membre(s)", inline=True)
        e.add_field(name="💤 AFK 30 jours", value=f"**{afk_30d}** membre(s)", inline=True)
        e.add_field(name="👥 Total membres", value=f"**{self.g.member_count}**", inline=True)
        
        return e
    
    async def count_afk_members(self):
        """Compte les membres AFK sur 7j et 30j"""
        afk_7d = 0
        afk_30d = 0
        now_dt = now()
        seven_days_ago = now_dt - timedelta(days=7)
        thirty_days_ago = now_dt - timedelta(days=30)
        
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Membres trackés
                async with db.execute(
                    'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                    (self.g.id,)
                ) as cursor:
                    tracked_users = set()
                    async for row in cursor:
                        user_id, last_msg, last_vocal = row
                        tracked_users.add(user_id)
                        
                        last_activity = None
                        if last_msg:
                            try:
                                last_activity = datetime.fromisoformat(last_msg)
                            except:
                                pass
                        if last_vocal:
                            try:
                                lv = datetime.fromisoformat(last_vocal)
                                if not last_activity or lv > last_activity:
                                    last_activity = lv
                            except:
                                pass
                        
                        if last_activity:
                            if last_activity.replace(tzinfo=timezone.utc) < seven_days_ago.replace(tzinfo=timezone.utc):
                                afk_7d += 1
                            if last_activity.replace(tzinfo=timezone.utc) < thirty_days_ago.replace(tzinfo=timezone.utc):
                                afk_30d += 1
                
                # Membres non trackés = considérés comme AFK
                for member in self.g.members:
                    if not member.bot and member.id not in tracked_users:
                        afk_7d += 1
                        afk_30d += 1
        except:
            pass
        
        return afk_7d, afk_30d
    
    @discord.ui.button(label="⚙️ Configurer Actions", style=discord.ButtonStyle.primary, row=0)
    async def config_actions(self, i, b):
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="📈 Voir Graphique", style=discord.ButtonStyle.success, row=0)
    async def view_graph(self, i, b):
        await i.response.defer()
        
        # Générer le graphique
        img = await self.generate_afk_graph()
        
        if img:
            file = discord.File(img, filename="afk_stats.png")
            e = discord.Embed(title="📊 Statistiques d'Activité", color=C.PURPLE)
            e.set_image(url="attachment://afk_stats.png")
            e.set_footer(text=f"{self.g.name} • Statistiques d'activité")
            await i.followup.send(embed=e, file=file, ephemeral=True)
        else:
            await i.followup.send("❌ Erreur lors de la génération du graphique", ephemeral=True)
    
    async def generate_afk_graph(self):
        """Génère un graphique des membres AFK"""
        try:
            afk_7d, afk_30d = await self.count_afk_members()
            active_members = self.g.member_count - afk_7d
            
            # Créer le graphique
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
            fig.patch.set_facecolor('#2f3136')
            
            # Graphique 1: Camembert AFK
            colors1 = ['#57F287', '#FEE75C', '#ED4245']
            sizes1 = [active_members, afk_7d - afk_30d, afk_30d]
            labels1 = [f'Actifs\n({active_members})', f'AFK 7j\n({afk_7d - afk_30d})', f'AFK 30j\n({afk_30d})']
            
            # Filtrer les valeurs nulles
            filtered = [(s, l, c) for s, l, c in zip(sizes1, labels1, colors1) if s > 0]
            if filtered:
                sizes1, labels1, colors1 = zip(*filtered)
            
            ax1.pie(sizes1, labels=labels1, colors=colors1, autopct='%1.1f%%', startangle=90,
                   textprops={'color': 'white', 'fontsize': 11, 'fontweight': 'bold'})
            ax1.set_title('📊 Répartition des Membres', color='white', fontsize=14, fontweight='bold', pad=20)
            ax1.set_facecolor('#2f3136')
            
            # Graphique 2: Barres
            categories = ['Actifs', 'AFK 7 jours', 'AFK 30 jours']
            values = [active_members, afk_7d, afk_30d]
            colors2 = ['#57F287', '#FEE75C', '#ED4245']
            
            bars = ax2.bar(categories, values, color=colors2, edgecolor='white', linewidth=2)
            ax2.set_ylabel('Nombre de membres', color='white', fontsize=12)
            ax2.set_title('📈 Statistiques d\'Activité', color='white', fontsize=14, fontweight='bold', pad=20)
            ax2.set_facecolor('#36393f')
            ax2.tick_params(colors='white')
            ax2.spines['bottom'].set_color('white')
            ax2.spines['left'].set_color('white')
            ax2.spines['top'].set_visible(False)
            ax2.spines['right'].set_visible(False)
            
            # Ajouter les valeurs sur les barres
            for bar, val in zip(bars, values):
                ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                        str(val), ha='center', color='white', fontweight='bold', fontsize=12)
            
            plt.tight_layout()
            
            # Sauvegarder en buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
            buf.seek(0)
            plt.close(fig)
            
            return buf
        except Exception as ex:
            print(f"Erreur graphique: {ex}")
            return None
    
    @discord.ui.button(label="🔄 Exécuter Actions", style=discord.ButtonStyle.danger, row=0)
    async def execute_actions(self, i, b):
        await i.response.send_message(
            "⚠️ **Êtes-vous sûr de vouloir exécuter les actions configurées ?**\n"
            "Cela affectera tous les membres AFK selon la configuration.",
            view=StatExecuteConfirmView(self.u, self.g),
            ephemeral=True
        )
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class StatActionPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        
        e = discord.Embed(title="⚙️ Configuration des Actions", color=C.ORANGE)
        e.description = "Configurez les actions automatiques sur les membres inactifs.\n**Vous pouvez sélectionner plusieurs actions !**"
        
        action_labels = {'ping': '🔔 Ping', 'remove_role': '🎭 Retirer rôle', 'kick': '👢 Kick'}
        
        # Actions 7 jours (maintenant une liste)
        actions_7d = stat_cfg.get('actions_7d', [])
        if actions_7d:
            actions_7d_txt = " + ".join([action_labels.get(a, a) for a in actions_7d])
        else:
            actions_7d_txt = "❌ Aucune"
        
        # Actions 30 jours (maintenant une liste)
        actions_30d = stat_cfg.get('actions_30d', [])
        if actions_30d:
            actions_30d_txt = " + ".join([action_labels.get(a, a) for a in actions_30d])
        else:
            actions_30d_txt = "❌ Aucune"
        
        role_id = stat_cfg.get('activity_role', 0)
        notif_ch = self.g.get_channel(stat_cfg.get('notif_channel', 0))
        recovery_ch = self.g.get_channel(stat_cfg.get('recovery_channel', 0))
        role = self.g.get_role(role_id) if role_id else None
        
        e.add_field(
            name="😴 Actions après 7 jours",
            value=actions_7d_txt,
            inline=True
        )
        e.add_field(
            name="💤 Actions après 30 jours",
            value=actions_30d_txt,
            inline=True
        )
        e.add_field(name="\u200b", value="\u200b", inline=True)
        
        e.add_field(
            name="🎭 Rôle d'activité",
            value=role.mention if role else "❌ Non défini",
            inline=True
        )
        e.add_field(
            name="📢 Salon notifications",
            value=notif_ch.mention if notif_ch else "❌ Non défini",
            inline=True
        )
        e.add_field(
            name="💬 Salon récupération",
            value=recovery_ch.mention if recovery_ch else "❌ Non défini",
            inline=True
        )
        
        e.set_footer(text="💡 Le rôle sera redonné automatiquement si le membre envoie un message ou rejoint un vocal")
        return e
    
    @discord.ui.select(
        placeholder="😴 Actions 7 jours (multi-sélection)...",
        options=[
            discord.SelectOption(label="Ping les membres", value="ping", emoji="🔔", description="Mentionner dans le salon de notifications"),
            discord.SelectOption(label="Retirer le rôle", value="remove_role", emoji="🎭", description="Enlever le rôle d'activité"),
            discord.SelectOption(label="Kick les membres", value="kick", emoji="👢", description="Expulser du serveur"),
        ],
        min_values=0,
        max_values=3,
        row=0
    )
    async def action_7d(self, i, s):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['actions_7d'] = s.values  # Liste d'actions
        await db_set(self.g.id, 'stat_config', stat_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.select(
        placeholder="💤 Actions 30 jours (multi-sélection)...",
        options=[
            discord.SelectOption(label="Ping les membres", value="ping", emoji="🔔", description="Mentionner dans le salon de notifications"),
            discord.SelectOption(label="Retirer le rôle", value="remove_role", emoji="🎭", description="Enlever le rôle d'activité"),
            discord.SelectOption(label="Kick les membres", value="kick", emoji="👢", description="Expulser du serveur"),
        ],
        min_values=0,
        max_values=3,
        row=1
    )
    async def action_30d(self, i, s):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['actions_30d'] = s.values  # Liste d'actions
        await db_set(self.g.id, 'stat_config', stat_cfg)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="🎭 Rôle", style=discord.ButtonStyle.primary, row=2)
    async def set_role(self, i, b):
        roles = [r for r in self.g.roles if not r.is_default() and not r.managed and r < self.g.me.top_role][:25]
        if not roles:
            return await i.response.send_message("❌ Aucun rôle disponible", ephemeral=True)
        opts = [discord.SelectOption(label=r.name[:25], value=str(r.id)) for r in roles]
        v = StatRoleSelectView(self.u, self.g, opts)
        await i.response.edit_message(embed=discord.Embed(title="🎭 Sélectionner le rôle d'activité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="📢 Notifs", style=discord.ButtonStyle.primary, row=2)
    async def set_channel(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = StatChannelSelectView(self.u, self.g, opts, 'notif_channel')
        await i.response.edit_message(embed=discord.Embed(title="📢 Salon de notifications", description="Salon où seront envoyées les alertes d'inactivité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="💬 Récup", style=discord.ButtonStyle.primary, row=2)
    async def set_recovery(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        v = StatChannelSelectView(self.u, self.g, opts, 'recovery_channel')
        await i.response.edit_message(embed=discord.Embed(title="💬 Salon de récupération", description="Salon où les membres doivent écrire pour récupérer leur activité", color=C.PURPLE), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = StatPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="👢 Expulser AFK 7j", style=discord.ButtonStyle.danger, row=3)
    async def kick_7d(self, i, b):
        count = await count_afk_members_by_days(self.g, 7)
        await i.response.send_message(
            f"⚠️ **ATTENTION - Action irréversible !**\n\n"
            f"Vous êtes sur le point d'expulser **{count}** membre(s) inactif(s) depuis **7 jours**.\n\n"
            f"Cette action est **DÉFINITIVE** et ne peut pas être annulée.",
            view=KickConfirmView(self.u, self.g, 7, count),
            ephemeral=True
        )
    
    @discord.ui.button(label="👢 Expulser AFK 30j", style=discord.ButtonStyle.danger, row=3)
    async def kick_30d(self, i, b):
        count = await count_afk_members_by_days(self.g, 30)
        await i.response.send_message(
            f"⚠️ **ATTENTION - Action irréversible !**\n\n"
            f"Vous êtes sur le point d'expulser **{count}** membre(s) inactif(s) depuis **30 jours**.\n\n"
            f"Cette action est **DÉFINITIVE** et ne peut pas être annulée.",
            view=KickConfirmView(self.u, self.g, 30, count),
            ephemeral=True
        )

async def count_afk_members_by_days(guild, days):
    """Compte les membres AFK depuis X jours"""
    count = 0
    now_dt = now()
    cutoff = now_dt - timedelta(days=days)
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                tracked_users = set()
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    tracked_users.add(user_id)
                    
                    last_activity = None
                    if last_msg:
                        try:
                            last_activity = datetime.fromisoformat(last_msg)
                        except:
                            pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except:
                            pass
                    
                    if last_activity:
                        if last_activity.replace(tzinfo=timezone.utc) < cutoff.replace(tzinfo=timezone.utc):
                            member = guild.get_member(user_id)
                            if member and not member.bot and member.id != guild.owner_id:
                                count += 1
            
            for member in guild.members:
                if not member.bot and member.id not in tracked_users and member.id != guild.owner_id:
                    count += 1
    except:
        pass
    
    return count

class KickConfirmView(View):
    def __init__(self, u, g, days, count):
        super().__init__(timeout=60)
        self.u = u
        self.g = g
        self.days = days
        self.count = count
    
    @discord.ui.button(label="✅ Confirmer l'expulsion", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        await i.response.defer()
        for item in self.children:
            item.disabled = True
        await i.message.edit(view=self)
        result = await kick_afk_members(self.g, self.days)
        await i.followup.send(result, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Expulsion annulée.", view=None)

async def kick_afk_members(guild, days):
    """Expulse tous les membres AFK depuis X jours"""
    now_dt = now()
    cutoff = now_dt - timedelta(days=days)
    
    kicked = 0
    failed = 0
    skipped = 0
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                tracked_users = {}
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    last_activity = None
                    if last_msg:
                        try: last_activity = datetime.fromisoformat(last_msg)
                        except: pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except: pass
                    tracked_users[user_id] = last_activity
        
        for member in list(guild.members):
            if member.bot:
                continue
            if member.id == guild.owner_id:
                skipped += 1
                continue
            if member.top_role >= guild.me.top_role:
                skipped += 1
                continue
            
            last_activity = tracked_users.get(member.id)
            is_afk = False
            if not last_activity:
                is_afk = True
            else:
                la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
                is_afk = la_utc < cutoff.replace(tzinfo=timezone.utc)
            
            if is_afk:
                try:
                    await member.kick(reason=f"Inactivité de plus de {days} jours")
                    kicked += 1
                    await asyncio.sleep(0.5)
                except:
                    failed += 1
        
        result = f"✅ **Expulsion terminée !**\n\n"
        result += f"👢 **{kicked}** membre(s) expulsé(s)\n"
        if failed > 0:
            result += f"❌ **{failed}** échec(s)\n"
        if skipped > 0:
            result += f"⏭️ **{skipped}** ignoré(s)\n"
        result += f"\n*Critère: inactif depuis plus de {days} jours*"
        return result
        
    except Exception as ex:
        return f"❌ Erreur: {ex}"

class StatRoleSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(StatRoleSelect(u, g, opts))

class StatRoleSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg['activity_role'] = int(self.values[0])
        await db_set(self.g.id, 'stat_config', stat_cfg)
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class StatChannelSelectView(View):
    def __init__(self, u, g, opts, key):
        super().__init__(timeout=120)
        self.add_item(StatChannelSelect(u, g, opts, key))

class StatChannelSelect(Select):
    def __init__(self, u, g, opts, key):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.key = key
    
    async def callback(self, i):
        c = await cfg(self.g.id)
        stat_cfg = c.get('stat_config', {})
        stat_cfg[self.key] = int(self.values[0])
        await db_set(self.g.id, 'stat_config', stat_cfg)
        v = StatActionPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class StatExecuteConfirmView(View):
    def __init__(self, u, g):
        super().__init__(timeout=60)
        self.u = u
        self.g = g
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.danger)
    async def confirm(self, i, b):
        await i.response.defer()
        result = await execute_afk_actions(self.g)
        await i.followup.send(result, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, i, b):
        await i.response.edit_message(content="❌ Action annulée", view=None)

async def execute_afk_actions(guild):
    """Exécute les actions sur les membres AFK - Version optimisée pour gros serveurs"""
    c = await cfg(guild.id)
    stat_cfg = c.get('stat_config', {})
    
    # Maintenant ce sont des listes d'actions
    actions_7d = stat_cfg.get('actions_7d', [])
    actions_30d = stat_cfg.get('actions_30d', [])
    role_id = stat_cfg.get('activity_role', 0)
    notif_ch_id = stat_cfg.get('notif_channel', 0)
    recovery_ch_id = stat_cfg.get('recovery_channel', 0)
    
    role = guild.get_role(role_id) if role_id else None
    notif_ch = guild.get_channel(notif_ch_id) if notif_ch_id else None
    recovery_ch = guild.get_channel(recovery_ch_id) if recovery_ch_id else None
    
    now_dt = now()
    seven_days_ago = now_dt - timedelta(days=7)
    thirty_days_ago = now_dt - timedelta(days=30)
    
    results = {
        'ping_7d': 0, 'remove_role_7d': 0, 'kick_7d': 0,
        'ping_30d': 0, 'remove_role_30d': 0, 'kick_30d': 0
    }
    
    try:
        # Récupérer les activités
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id, last_message, last_vocal FROM activity_tracking WHERE guild_id=?',
                (guild.id,)
            ) as cursor:
                user_activities = {}
                async for row in cursor:
                    user_id, last_msg, last_vocal = row
                    last_activity = None
                    if last_msg:
                        try: last_activity = datetime.fromisoformat(last_msg)
                        except: pass
                    if last_vocal:
                        try:
                            lv = datetime.fromisoformat(last_vocal)
                            if not last_activity or lv > last_activity:
                                last_activity = lv
                        except: pass
                    user_activities[user_id] = last_activity
        
        # Listes pour les membres AFK
        afk_members_7d = []  # Inactifs 7j mais pas 30j
        afk_members_30d = []  # Inactifs 30j+
        
        for member in guild.members:
            if member.bot or member.id == guild.owner_id:
                continue
            
            last_activity = user_activities.get(member.id)
            
            if not last_activity:
                is_afk_7d = True
                is_afk_30d = True
            else:
                la_utc = last_activity.replace(tzinfo=timezone.utc) if last_activity.tzinfo is None else last_activity
                is_afk_7d = la_utc < seven_days_ago.replace(tzinfo=timezone.utc)
                is_afk_30d = la_utc < thirty_days_ago.replace(tzinfo=timezone.utc)
            
            if is_afk_30d:
                afk_members_30d.append(member)
            elif is_afk_7d:
                afk_members_7d.append(member)
        
        # Exécuter les actions 30 jours
        for member in afk_members_30d:
            if 'remove_role' in actions_30d and role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Inactivité 30 jours")
                    results['remove_role_30d'] += 1
                except: pass
            
            if 'kick' in actions_30d:
                try:
                    if member.top_role < guild.me.top_role:
                        await member.kick(reason="Inactivité 30 jours")
                        results['kick_30d'] += 1
                        await asyncio.sleep(0.3)
                except: pass
        
        # Exécuter les actions 7 jours
        for member in afk_members_7d:
            if 'remove_role' in actions_7d and role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Inactivité 7 jours")
                    results['remove_role_7d'] += 1
                except: pass
            
            if 'kick' in actions_7d:
                try:
                    if member.top_role < guild.me.top_role:
                        await member.kick(reason="Inactivité 7 jours")
                        results['kick_7d'] += 1
                        await asyncio.sleep(0.3)
                except: pass
        
        # ═══════════════ NOTIFICATIONS COMPACTES ═══════════════
        if notif_ch:
            recovery_mention = recovery_ch.mention if recovery_ch else "un salon textuel"
            
            # Notification 30 jours (si ping activé et membres non kickés)
            if 'ping' in actions_30d and afk_members_30d and 'kick' not in actions_30d:
                results['ping_30d'] = len(afk_members_30d)
                await send_compact_afk_notification(
                    notif_ch, afk_members_30d, 30, recovery_mention, role
                )
            
            # Notification 7 jours (si ping activé et membres non kickés)
            if 'ping' in actions_7d and afk_members_7d and 'kick' not in actions_7d:
                results['ping_7d'] = len(afk_members_7d)
                await send_compact_afk_notification(
                    notif_ch, afk_members_7d, 7, recovery_mention, role
                )
        
        # Résumé
        summary = "✅ **Actions exécutées:**\n\n"
        
        if results['ping_7d']: summary += f"🔔 **{results['ping_7d']}** membre(s) mentionné(s) (7j)\n"
        if results['remove_role_7d']: summary += f"🎭 **{results['remove_role_7d']}** rôle(s) retiré(s) (7j)\n"
        if results['kick_7d']: summary += f"👢 **{results['kick_7d']}** membre(s) expulsé(s) (7j)\n"
        
        if results['ping_30d']: summary += f"🔔 **{results['ping_30d']}** membre(s) mentionné(s) (30j)\n"
        if results['remove_role_30d']: summary += f"🎭 **{results['remove_role_30d']}** rôle(s) retiré(s) (30j)\n"
        if results['kick_30d']: summary += f"👢 **{results['kick_30d']}** membre(s) expulsé(s) (30j)\n"
        
        if sum(results.values()) == 0:
            summary = "ℹ️ Aucune action effectuée.\n\n**Vérifiez:**\n• Les actions sont-elles configurées ?\n• Y a-t-il des membres inactifs ?"
        
        return summary
        
    except Exception as ex:
        return f"❌ Erreur: {ex}"

async def send_compact_afk_notification(channel, members, days, recovery_mention, role):
    """Envoie une notification compacte pour les membres AFK - Optimisée gros serveurs"""
    if not members:
        return
    
    # Créer l'embed principal
    if days == 7:
        title = "😴 Alerte Inactivité - 7 Jours"
        color = C.YELLOW
        emoji = "⚠️"
    else:
        title = "💤 Alerte Inactivité - 30 Jours"
        color = C.RED
        emoji = "🚨"
    
    role_txt = f"Votre rôle **{role.name}** a été retiré." if role else ""
    
    # Message d'introduction
    intro_embed = discord.Embed(title=title, color=color)
    intro_embed.description = (
        f"{emoji} **{len(members)} membre(s)** sont inactifs depuis plus de **{days} jours**.\n\n"
        f"Vous n'avez pas envoyé de message ni rejoint de salon vocal.\n"
        f"{role_txt}\n\n"
        f"**📢 Pour récupérer votre activité:**\n"
        f"Envoyez un message dans {recovery_mention} ou rejoignez un salon vocal.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    intro_embed.set_footer(text=f"Membres concernés: {len(members)}")
    intro_embed.timestamp = now()
    
    await channel.send(embed=intro_embed)
    
    # Grouper les mentions par paquets de 50 pour éviter les limites
    mentions = [m.mention for m in members]
    chunk_size = 50
    
    for i in range(0, len(mentions), chunk_size):
        chunk = mentions[i:i + chunk_size]
        chunk_num = (i // chunk_size) + 1
        total_chunks = (len(mentions) + chunk_size - 1) // chunk_size
        
        # Créer un embed pour chaque groupe
        chunk_embed = discord.Embed(color=color)
        
        if total_chunks > 1:
            chunk_embed.title = f"📋 Liste des membres ({chunk_num}/{total_chunks})"
        else:
            chunk_embed.title = "📋 Membres concernés"
        
        # Formater les mentions en colonnes (plus lisible)
        chunk_embed.description = " ".join(chunk)
        
        await channel.send(embed=chunk_embed)
        await asyncio.sleep(0.5)  # Rate limit

# ═══════════════════════════════════════════════════════════════════════════════
#                           📺 CONFIG SALON
# ═══════════════════════════════════════════════════════════════════════════════

class ChanPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        e = discord.Embed(title="📺 Configuration des salons", color=C.ORANGE)
        if configs:
            lines = []
            for ch_id, conf in list(configs.items())[:15]:
                ch = self.g.get_channel(int(ch_id))
                if ch:
                    icons = ""
                    if not conf.get('messages', True): icons += "💬❌ "
                    if not conf.get('images', True): icons += "🖼️❌ "
                    if not conf.get('gifs', True): icons += "🎞️❌ "
                    if not conf.get('emojis', True): icons += "😀❌ "
                    if not conf.get('links', True): icons += "🔗❌ "
                    if conf.get('commands_only', False): icons += "🤖✅ "
                    lines.append(f"{ch.mention}: {icons or '✅ Tout autorisé'}")
            e.description = "\n".join(lines)
        else:
            e.description = "*Aucun salon configuré*"
        return e
    
    @discord.ui.button(label="➕ Configurer un salon", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        await i.response.edit_message(embed=discord.Embed(title="📺 Choisir un salon", color=C.ORANGE), view=ChanSelectView(self.u, self.g, opts))
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class ChanSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(ChanSelect(u, g, opts))

class ChanSelect(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        v = EditChanCfg(self.u, self.g, self.values[0])
        await i.response.edit_message(embed=await v.embed(), view=v)

class EditChanCfg(View):
    def __init__(self, u, g, ch_id):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.ch_id = ch_id
    
    async def get_conf(self):
        c = await cfg(self.g.id)
        return c.get('channel_configs', {}).get(str(self.ch_id), {'messages': True, 'images': True, 'gifs': True, 'emojis': True, 'links': True, 'commands_only': False})
    
    async def save(self, conf):
        c = await cfg(self.g.id)
        configs = c.get('channel_configs', {})
        configs[str(self.ch_id)] = conf
        await db_set(self.g.id, 'channel_configs', configs)
    
    async def embed(self):
        ch = self.g.get_channel(int(self.ch_id))
        conf = await self.get_conf()
        s = lambda k: "✅ Autorisé" if conf.get(k, True) else "❌ Bloqué"
        so = lambda k: "✅ Activé" if conf.get(k, False) else "❌ Désactivé"
        e = discord.Embed(title=f"📺 Configuration de #{ch.name if ch else '?'}", color=C.ORANGE)
        e.description = f"💬 Messages: {s('messages')}\n🖼️ Images: {s('images')}\n🎞️ GIFs: {s('gifs')}\n😀 Emojis: {s('emojis')}\n🔗 Liens: {s('links')}\n\n🤖 **Commandes bot uniquement**: {so('commands_only')}"
        return e
    
    async def toggle(self, i, key, default=True):
        conf = await self.get_conf()
        conf[key] = not conf.get(key, default)
        await self.save(conf)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="💬 Messages", style=discord.ButtonStyle.primary, row=0)
    async def t1(self, i, b): await self.toggle(i, 'messages')
    
    @discord.ui.button(label="🖼️ Images", style=discord.ButtonStyle.primary, row=0)
    async def t2(self, i, b): await self.toggle(i, 'images')
    
    @discord.ui.button(label="🎞️ GIFs", style=discord.ButtonStyle.primary, row=0)
    async def t3(self, i, b): await self.toggle(i, 'gifs')
    
    @discord.ui.button(label="😀 Emojis", style=discord.ButtonStyle.primary, row=1)
    async def t4(self, i, b): await self.toggle(i, 'emojis')
    
    @discord.ui.button(label="🔗 Liens", style=discord.ButtonStyle.primary, row=1)
    async def t5(self, i, b): await self.toggle(i, 'links')
    
    @discord.ui.button(label="🤖 Commandes uniquement", style=discord.ButtonStyle.success, row=1)
    async def t6(self, i, b): await self.toggle(i, 'commands_only', False)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = ChanPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎫 TICKET CONFIG PANEL (INTACT)
# ═══════════════════════════════════════════════════════════════════════════════

class TicketMainPanel(View):
    def __init__(self, u, g):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
    
    async def embed(self):
        c = await cfg(self.g.id)
        e = discord.Embed(title="🎫 Configuration Tickets", color=C.PURPLE)
        staff = self.g.get_role(c.get('ticket_staff', 0))
        lch = self.g.get_channel(c.get('ticket_log', 0))
        e.add_field(name="👮 Rôle Staff", value=staff.mention if staff else "❌ Non configuré", inline=True)
        e.add_field(name="📜 Salon Logs", value=lch.mention if lch else "❌ Non configuré", inline=True)
        panels = c.get('ticket_panels', {})
        if panels:
            pl = []
            for pid, pd in list(panels.items())[:10]:
                cat = self.g.get_channel(pd.get('category', 0))
                pl.append(f"• **{pd.get('name', pid)[:20]}** → `{cat.name if cat else '❌'}` ({len(pd.get('questions', []))} questions, max {pd.get('max', 1)})")
            e.add_field(name=f"📋 Panels ({len(panels)})", value="\n".join(pl), inline=False)
        else:
            e.add_field(name="📋 Panels", value="*Aucun panel créé*", inline=False)
        return e
    
    @discord.ui.button(label="👮 Définir Staff", style=discord.ButtonStyle.primary, row=0)
    async def staff(self, i, b):
        roles = [r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts = [discord.SelectOption(label=f"@{r.name}"[:25], value=str(r.id)) for r in roles]
        await i.response.edit_message(embed=discord.Embed(title="👮 Choisir le rôle Staff", color=C.PURPLE), view=TkStaffView(self.u, self.g, opts))
    
    @discord.ui.button(label="📜 Définir Logs", style=discord.ButtonStyle.primary, row=0)
    async def logs(self, i, b):
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {c.name}"[:25], value=str(c.id)) for c in chs]
        await i.response.edit_message(embed=discord.Embed(title="📜 Choisir le salon Logs", color=C.PURPLE), view=TkLogView(self.u, self.g, opts))
    
    @discord.ui.button(label="➕ Nouveau Panel", style=discord.ButtonStyle.success, row=1)
    async def new(self, i, b):
        await i.response.send_modal(NewPanelModal(self.u, self.g))
    
    @discord.ui.button(label="📝 Modifier Panel", style=discord.ButtonStyle.secondary, row=1)
    async def edit(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if not panels:
            return await i.response.send_message("❌ Aucun panel créé", ephemeral=True)
        opts = [discord.SelectOption(label=pd.get('name', pid)[:25], value=pid) for pid, pd in list(panels.items())[:25]]
        await i.response.edit_message(embed=discord.Embed(title="📝 Choisir un panel", color=C.PURPLE), view=EditPanelSelectView(self.u, self.g, opts))
    
    @discord.ui.button(label="🔄 Rafraîchir", style=discord.ButtonStyle.secondary, row=2)
    async def ref(self, i, b):
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = MainPanel(self.u, self.g)
        await i.response.edit_message(embed=v.embed(), view=v)

class TkStaffView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TkStaffSel(u, g, opts))

class TkStaffSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un rôle...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_staff', int(self.values[0]))
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class TkLogView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(TkLogSel(u, g, opts))

class TkLogSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        await db_set(i.guild.id, 'ticket_log', int(self.values[0]))
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class NewPanelModal(Modal, title="➕ Nouveau Panel"):
    name = TextInput(label="Nom du panel", placeholder="Support, Partenariat...", max_length=30)
    mx = TextInput(label="Max tickets par utilisateur", placeholder="1", default="1", max_length=2)
    
    def __init__(self, u, g):
        super().__init__()
        self.u = u
        self.g = g
    
    async def on_submit(self, i):
        pid = str(int(time.time()))
        mxt = max(1, min(10, int(self.mx.value) if self.mx.value.isdigit() else 1))
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        panels[pid] = {'name': self.name.value, 'category': 0, 'questions': [], 'max': mxt}
        await db_set(self.g.id, 'ticket_panels', panels)
        v = PanelEditView(self.u, self.g, pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class EditPanelSelectView(View):
    def __init__(self, u, g, opts):
        super().__init__(timeout=120)
        self.add_item(EditPanelSel(u, g, opts))

class EditPanelSel(Select):
    def __init__(self, u, g, opts):
        super().__init__(placeholder="Choisir un panel...", options=opts)
        self.u = u
        self.g = g
    
    async def callback(self, i):
        v = PanelEditView(self.u, self.g, self.values[0])
        await i.response.edit_message(embed=await v.embed(), view=v)

class PanelEditView(View):
    def __init__(self, u, g, pid):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def get_panel(self):
        c = await cfg(self.g.id)
        return c.get('ticket_panels', {}).get(self.pid, {})
    
    async def embed(self):
        pnl = await self.get_panel()
        e = discord.Embed(title=f"🎫 Panel: {pnl.get('name', '?')}", color=C.PURPLE)
        cat = self.g.get_channel(pnl.get('category', 0))
        e.add_field(name="📁 Catégorie", value=cat.name if cat else "❌ Non configuré", inline=True)
        e.add_field(name="🔢 Max tickets", value=str(pnl.get('max', 1)), inline=True)
        qs = pnl.get('questions', [])
        if qs:
            e.add_field(name=f"📝 Questions ({len(qs)})", value="\n".join([f"• {q['title']}" for q in qs[:5]]), inline=False)
        else:
            e.add_field(name="📝 Questions", value="*Aucune question*", inline=False)
        return e
    
    @discord.ui.button(label="📁 Catégorie", style=discord.ButtonStyle.primary, row=0)
    async def cat(self, i, b):
        cats = list(self.g.categories)[:25]
        if not cats:
            return await i.response.send_message("❌ Aucune catégorie sur ce serveur", ephemeral=True)
        opts = [discord.SelectOption(label=f"📁 {c.name}"[:25], value=str(c.id)) for c in cats]
        await i.response.edit_message(embed=discord.Embed(title="📁 Choisir la catégorie", color=C.PURPLE), view=PanelCatView(self.u, self.g, self.pid, opts))
    
    @discord.ui.button(label="📝 Questions", style=discord.ButtonStyle.primary, row=0)
    async def qs(self, i, b):
        v = PanelQsView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="🔢 Max tickets", style=discord.ButtonStyle.secondary, row=0)
    async def mx(self, i, b):
        await i.response.send_modal(SetMaxModal(self.u, self.g, self.pid))
    
    @discord.ui.button(label="📤 Envoyer", style=discord.ButtonStyle.success, row=1)
    async def send(self, i, b):
        pnl = await self.get_panel()
        c = await cfg(self.g.id)
        if not pnl.get('category'):
            return await i.response.send_message("❌ Configure la catégorie d'abord!", ephemeral=True)
        if not c.get('ticket_staff'):
            return await i.response.send_message("❌ Configure le rôle Staff d'abord!", ephemeral=True)
        chs = list(self.g.text_channels)[:25]
        opts = [discord.SelectOption(label=f"# {ch.name}"[:25], value=str(ch.id)) for ch in chs]
        await i.response.edit_message(embed=discord.Embed(title="📤 Où envoyer le panel?", color=C.PURPLE), view=SendPanelView(self.u, self.g, self.pid, opts))
    
    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            del panels[self.pid]
        await db_set(self.g.id, 'ticket_panels', panels)
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, i, b):
        v = TicketMainPanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

class PanelCatView(View):
    def __init__(self, u, g, pid, opts):
        super().__init__(timeout=120)
        self.add_item(PanelCatSel(u, g, pid, opts))

class PanelCatSel(Select):
    def __init__(self, u, g, pid, opts):
        super().__init__(placeholder="Choisir une catégorie...", options=opts)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def callback(self, i):
        c = await cfg(i.guild.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['category'] = int(self.values[0])
            await db_set(i.guild.id, 'ticket_panels', panels)
        v = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SetMaxModal(Modal, title="🔢 Max tickets par utilisateur"):
    mx = TextInput(label="Nombre maximum", placeholder="1-10", default="1", max_length=2)
    
    def __init__(self, u, g, pid):
        super().__init__()
        self.u = u
        self.g = g
        self.pid = pid
    
    async def on_submit(self, i):
        v = max(1, min(10, int(self.mx.value) if self.mx.value.isdigit() else 1))
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['max'] = v
            await db_set(self.g.id, 'ticket_panels', panels)
        vw = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await vw.embed(), view=vw)

class PanelQsView(View):
    def __init__(self, u, g, pid):
        super().__init__(timeout=600)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def embed(self):
        c = await cfg(self.g.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        qs = pnl.get('questions', [])
        e = discord.Embed(title="📝 Questions du panel", color=C.PURPLE)
        if qs:
            for j, q in enumerate(qs, 1):
                e.add_field(name=f"{j}. {q['title']}", value=q['question'][:100], inline=False)
        else:
            e.description = "*Aucune question configurée*"
        e.set_footer(text="Maximum 5 questions")
        return e
    
    @discord.ui.button(label="➕ Ajouter", style=discord.ButtonStyle.success, row=0)
    async def add(self, i, b):
        c = await cfg(self.g.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        if len(pnl.get('questions', [])) >= 5:
            return await i.response.send_message("❌ Maximum 5 questions", ephemeral=True)
        await i.response.send_modal(AddQModal(self.u, self.g, self.pid))
    
    @discord.ui.button(label="🗑️ Tout supprimer", style=discord.ButtonStyle.danger, row=0)
    async def clear(self, i, b):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid]['questions'] = []
            await db_set(self.g.id, 'ticket_panels', panels)
        await i.response.edit_message(embed=await self.embed(), view=self)
    
    @discord.ui.button(label="◀️ Retour", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, i, b):
        v = PanelEditView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class AddQModal(Modal, title="➕ Ajouter une question"):
    t = TextInput(label="Titre (affiché dans le formulaire)", placeholder="Ex: Pseudo en jeu", max_length=45)
    q = TextInput(label="Question complète", placeholder="Ex: Quel est votre pseudo sur le serveur?", style=discord.TextStyle.paragraph, max_length=100)
    
    def __init__(self, u, g, pid):
        super().__init__()
        self.u = u
        self.g = g
        self.pid = pid
    
    async def on_submit(self, i):
        c = await cfg(self.g.id)
        panels = c.get('ticket_panels', {})
        if self.pid in panels:
            panels[self.pid].setdefault('questions', []).append({'title': self.t.value, 'question': self.q.value})
            await db_set(self.g.id, 'ticket_panels', panels)
        v = PanelQsView(self.u, self.g, self.pid)
        await i.response.edit_message(embed=await v.embed(), view=v)

class SendPanelView(View):
    def __init__(self, u, g, pid, opts):
        super().__init__(timeout=120)
        self.add_item(SendPanelSel(u, g, pid, opts))

class SendPanelSel(Select):
    def __init__(self, u, g, pid, opts):
        super().__init__(placeholder="Choisir un salon...", options=opts)
        self.u = u
        self.g = g
        self.pid = pid
    
    async def callback(self, i):
        ch = i.guild.get_channel(int(self.values[0]))
        if not ch:
            return await i.response.send_message("❌ Salon introuvable", ephemeral=True)
        c = await cfg(i.guild.id)
        pnl = c.get('ticket_panels', {}).get(self.pid, {})
        qs = pnl.get('questions', [])
        mx = pnl.get('max', 1)
        desc = "Cliquez sur le bouton ci-dessous pour créer un ticket."
        if qs:
            desc += f"\n\n📝 Vous devrez répondre à **{len(qs)}** question(s)."
        desc += f"\n🔢 Maximum **{mx}** ticket(s) simultané(s)."
        emb = discord.Embed(title=f"🎫 {pnl.get('name', 'Support')}", description=desc, color=C.BLURPLE)
        await ch.send(embed=emb, view=TicketCreateView(self.pid))
        await i.response.send_message(f"✅ Panel envoyé dans {ch.mention}!", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

async def update_realsy_activity(guild_id, user_id):
    """Met à jour la dernière activité d'un utilisateur avec le rôle Realsy"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT user_id FROM realsy_tracking WHERE guild_id=? AND user_id=?', 
                (guild_id, user_id)) as c:
                if await c.fetchone():
                    await db.execute('UPDATE realsy_tracking SET last_activity=?, warn_count=0 WHERE guild_id=? AND user_id=?',
                        (now().isoformat(), guild_id, user_id))
                    await db.commit()
    except:
        pass

@bot.event
async def on_ready():
    await db_init()
    bot.add_view(TicketControlView())
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM guild_config') as c:
                for row in await c.fetchall():
                    try:
                        data = json.loads(row[0]) if row[0] else {}
                        for pid in data.get('ticket_panels', {}):
                            bot.add_view(TicketCreateView(pid))
                    except: pass
    except: pass
    
    # Sync global des commandes
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées:")
        for cmd in synced:
            print(f"   - /{cmd.name}")
    except Exception as ex:
        print(f"❌ Erreur sync global: {ex}")
    
    # Lancer la tâche d'inactivité
    if not check_realsy_inactivity.is_running():
        check_realsy_inactivity.start()
    
    # Lancer la tâche des feeds sociaux
    if not check_social_feeds.is_running():
        check_social_feeds.start()
    
    print(f"✅ {bot.user.name} v15 prêt!")
    print(f"🌐 Serveurs: {len(bot.guilds)}")
    print(f"📢 Vérification feeds sociaux toutes les 5 minutes")

@bot.tree.command(name="sync", description="🔄 Synchroniser les commandes (Admin)")
async def sync_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Admin requis", ephemeral=True)
    
    await i.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        cmd_list = "\n".join([f"• `/{c.name}`" for c in synced])
        await i.followup.send(f"✅ **{len(synced)} commandes synchronisées!**\n\n{cmd_list}", ephemeral=True)
    except Exception as ex:
        await i.followup.send(f"❌ Erreur: {ex}", ephemeral=True)

@bot.event
async def on_member_remove(m):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id, channel_id, claimed_by, answers FROM tickets WHERE guild_id=? AND user_id=? AND status='open'", (m.guild.id, m.id)) as c:
                tks = await c.fetchall()
        for tk in tks:
            ans = {}
            try: ans = json.loads(tk[3]) if tk[3] else {}
            except: pass
            ti = {'id': tk[0], 'user': m.id, 'claimed': tk[2] or 0, 'answers': ans}
            ch = m.guild.get_channel(tk[1])
            await send_ticket_log(m.guild, 'leave', m, ti)
            if ch:
                await ch.send(embed=discord.Embed(title="🚪 Utilisateur parti", description=f"**{m.display_name}** a quitté le serveur.", color=C.ORANGE))
    except: pass

@bot.event
async def on_member_join(m):
    try:
        c = await cfg(m.guild.id)
        if c.get('anti_newaccount'):
            days = c.get('newaccount_days', 7)
            age = (now() - m.created_at.replace(tzinfo=timezone.utc)).days
            if age < days:
                await send_log(m.guild, 'anti_newaccount', m, None, "Compte trop récent", f"Âge: {age} jour(s)")
                await m.kick(reason=f"Compte trop récent ({age} jours)")
    except: pass

async def relay_discord_message(msg):
    """Relay un message vers les serveurs qui suivent ce salon"""
    try:
        channel_id = str(msg.channel.id)
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, data FROM guild_config') as cursor:
                async for row in cursor:
                    guild_id, data_str = row
                    if guild_id == msg.guild.id:
                        continue
                    
                    try:
                        data = json.loads(data_str) if data_str else {}
                        feeds = data.get('ads_discord_feeds', [])
                        dest_channel_id = data.get('ads_discord_channel', 0)
                        
                        is_followed = any(f['channel_id'] == channel_id for f in feeds)
                        if not is_followed or not dest_channel_id:
                            continue
                        
                        dest_guild = bot.get_guild(guild_id)
                        if not dest_guild:
                            continue
                        dest_channel = dest_guild.get_channel(dest_channel_id)
                        if not dest_channel:
                            continue
                        
                        # ═══════════════ EMBED DISCORD RELAY PROFESSIONNEL ═══════════════
                        e = discord.Embed(color=0x5865F2)
                        
                        # Auteur avec le nom du serveur
                        e.set_author(
                            name=f"📡 DISCORD • {msg.guild.name}",
                            icon_url=msg.guild.icon.url if msg.guild.icon else "https://discord.com/assets/847541504914fd33810e70a0ea73177e.ico"
                        )
                        
                        # Thumbnail avec avatar de l'auteur
                        if msg.author.display_avatar:
                            e.set_thumbnail(url=msg.author.display_avatar.url)
                        
                        # Info du message
                        e.add_field(
                            name="👤 Auteur",
                            value=f"**{msg.author.display_name}**",
                            inline=True
                        )
                        e.add_field(
                            name="📍 Salon",
                            value=f"#{msg.channel.name}",
                            inline=True
                        )
                        
                        # Contenu du message
                        content = msg.content[:1500] if msg.content else ""
                        if content:
                            e.add_field(
                                name="💬 Message",
                                value=content,
                                inline=False
                            )
                        
                        # Images
                        if msg.attachments:
                            for att in msg.attachments[:1]:
                                if att.content_type and att.content_type.startswith('image'):
                                    e.set_image(url=att.url)
                                    break
                        
                        e.set_footer(
                            text=f"Discord • {msg.guild.name}",
                            icon_url="https://discord.com/assets/847541504914fd33810e70a0ea73177e.ico"
                        )
                        e.timestamp = msg.created_at
                        
                        await dest_channel.send(embed=e)
                        
                    except:
                        continue
    except:
        pass

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    
    # Relay Discord - Vérifier si ce salon est suivi par d'autres serveurs
    await relay_discord_message(msg)
    
    # Mise à jour activité Realsy
    await update_realsy_activity(msg.guild.id, msg.author.id)
    
    # ═══════════════ TRACKING ACTIVITÉ MEMBRE ═══════════════
    await track_member_message(msg)
    
    try:
        c = await cfg(msg.guild.id)
        ct = msg.content or ""
        chid = msg.channel.id
        gt = get_gif_type(msg)
        ag = c.get('image_allowed', [])
        iag = gt and gt in ag
        
        # Config salon spécifique
        chcf = c.get('channel_configs', {}).get(str(chid))
        if chcf and not (iag and chcf.get('gifs', True)):
            vio, _ = check_channel_cfg(msg, chcf)
            if vio:
                await msg.delete()
                return
        
        # Anti-phishing
        if c.get('anti_phishing'):
            f, d = check_phishing(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_phishing', msg.author, msg, "Lien de phishing détecté", f"`{d}`")
                await sanction(msg.author, c.get('phishing_action', 'ban'), 60, "Phishing", msg.guild)
                return
        
        # Anti-scam
        if c.get('anti_scam') and not await is_immune(msg.author, 'anti_scam'):
            f, p = check_scam(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_scam', msg.author, msg, "Message de scam détecté", f"`{p}`")
                await sanction(msg.author, c.get('scam_action', 'mute'), 60, "Scam", msg.guild)
                return
        
        # Anti-badwords
        if c.get('anti_badwords') and not await is_immune(msg.author, 'anti_badwords'):
            f, w = check_badwords(ct, c.get('badwords_list', []))
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_badwords', msg.author, msg, "Mot interdit détecté", f"`{w}`")
                return
        
        # Anti-invite
        if c.get('anti_invite'):
            f, inv = check_invite(ct)
            if f:
                await msg.delete()
                await send_log(msg.guild, 'anti_invite', msg.author, msg, "Invitation Discord", f"`{inv}`")
                return
        
        # Anti-link
        if c.get('anti_link') and not iag:
            if chid not in c.get('link_allowed_channels', []):
                f, url = check_link(ct, c.get('link_whitelist', []))
                if f:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_link', msg.author, msg, "Lien non autorisé", f"`{url}`")
                    return
        
        # Anti-image
        if c.get('anti_image') and not await is_immune(msg.author, 'anti_image') and not iag:
            if chid not in c.get('image_allowed_channels', []):
                bl = check_image(msg, c.get('image_allowed', []))
                if bl:
                    await msg.delete()
                    await send_log(msg.guild, 'anti_image', msg.author, msg, "Format non autorisé", f"`{', '.join(bl)}`")
                    return
        
        # Anti-spam
        if c.get('anti_spam') and not await is_immune(msg.author, 'anti_spam'):
            if await check_spam(msg, c.get('spam_max', 5), c.get('spam_interval', 5)):
                await msg.delete()
                await send_log(msg.guild, 'anti_spam', msg.author, msg, "Spam détecté", None)
                await sanction(msg.author, c.get('spam_action', 'mute'), 10, "Spam", msg.guild)
                return
        
        # Anti-caps
        if c.get('anti_caps') and not await is_immune(msg.author, 'anti_caps'):
            if check_caps(ct, c.get('caps_percent', 70)):
                await msg.delete()
                await send_log(msg.guild, 'anti_caps', msg.author, msg, "Trop de majuscules", None)
                return
    except: pass

# ═══════════════════════════════════════════════════════════════════════════════
#                              📋 COMMANDES SLASH
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="configure", description="⚙️ Ouvrir le panneau de configuration")
async def configure_cmd(i: discord.Interaction):
    if not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Vous devez être administrateur", ephemeral=True)
    v = MainPanel(i.user, i.guild)
    await i.response.send_message(embed=v.embed(), view=v, ephemeral=True)

async def check_mod_perm(i, cmd_key):
    """Vérifie si l'utilisateur a la permission pour cette commande de modération"""
    c = await cfg(i.guild.id)
    role_id = c.get(cmd_key, 0)
    
    # Admins et owner ont toujours accès
    if i.user.guild_permissions.administrator or i.user.id == i.guild.owner_id:
        return True
    
    # Vérifier si l'utilisateur a le rôle configuré
    if role_id:
        role = i.guild.get_role(role_id)
        if role and role in i.user.roles:
            return True
    
    return False

# ═══════════════════════════════════════════════════════════════════════════════
#                              ⚠️ WARN / UNWARN
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="warn", description="⚠️ Avertir un membre")
@app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
async def warn_cmd(i: discord.Interaction, membre: discord.Member, raison: str):
    if not await check_mod_perm(i, 'mod_warn_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if membre.id == i.user.id:
        return await i.response.send_message("❌ Vous ne pouvez pas vous warn vous-même", ephemeral=True)
    
    if membre.bot:
        return await i.response.send_message("❌ Vous ne pouvez pas warn un bot", ephemeral=True)
    
    if membre.top_role >= i.user.top_role and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Vous ne pouvez pas warn ce membre", ephemeral=True)
    
    # Enregistrer l'infraction
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, duration) VALUES(?,?,?,?,?,?)',
            (i.guild.id, membre.id, i.user.id, 'warn', raison, '')
        )
        await db.commit()
        # Compter les warns
        async with db.execute('SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type="warn"', (i.guild.id, membre.id)) as c:
            warn_count = (await c.fetchone())[0]
    
    # Créer l'embed
    e = discord.Embed(title="⚠️ Avertissement", color=C.YELLOW, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="📊 Total warns", value=str(warn_count), inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'warn', i.user, membre, raison, extra=f"Total warns: {warn_count}")

@bot.tree.command(name="unwarn", description="✅ Supprimer un avertissement d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez supprimer un warn")
async def unwarn_cmd(i: discord.Interaction, membre: discord.Member):
    if not await check_mod_perm(i, 'mod_warn_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    # Récupérer les warns (sans created_at pour éviter l'erreur)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, reason FROM infractions WHERE guild_id=? AND user_id=? AND type="warn" ORDER BY id DESC LIMIT 25',
            (i.guild.id, membre.id)
        ) as c:
            warns = await c.fetchall()
    
    if not warns:
        return await i.response.send_message(f"❌ {membre.mention} n'a aucun warn", ephemeral=True)
    
    # Créer les options
    opts = []
    for warn_id, reason in warns:
        label = f"#{warn_id} - {reason[:50]}{'...' if len(reason) > 50 else ''}"
        opts.append(discord.SelectOption(label=label[:100], value=str(warn_id)))
    
    e = discord.Embed(
        title=f"✅ Supprimer un warn de {membre.display_name}",
        description=f"Sélectionnez le warn à supprimer ({len(warns)} warn(s))",
        color=C.GREEN
    )
    e.set_thumbnail(url=membre.display_avatar.url)
    
    v = UnwarnSelectView(membre, opts)
    await i.response.send_message(embed=e, view=v, ephemeral=True)

class UnwarnSelectView(View):
    def __init__(self, membre, opts):
        super().__init__(timeout=120)
        self.add_item(UnwarnSelect(membre, opts))

class UnwarnSelect(Select):
    def __init__(self, membre, opts):
        super().__init__(placeholder="Sélectionner le warn à supprimer...", options=opts)
        self.membre = membre
    
    async def callback(self, i):
        warn_id = int(self.values[0])
        
        # Récupérer info du warn avant suppression
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT reason FROM infractions WHERE id=?', (warn_id,)) as c:
                row = await c.fetchone()
                reason = row[0] if row else "?"
            
            # Supprimer
            await db.execute('DELETE FROM infractions WHERE id=?', (warn_id,))
            await db.commit()
            
            # Compter les warns restants
            async with db.execute('SELECT COUNT(*) FROM infractions WHERE guild_id=? AND user_id=? AND type="warn"', (i.guild.id, self.membre.id)) as c:
                warn_count = (await c.fetchone())[0]
        
        e = discord.Embed(title="✅ Warn supprimé", color=C.GREEN, timestamp=now())
        e.add_field(name="👤 Membre", value=f"{self.membre.mention}", inline=True)
        e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
        e.add_field(name="📊 Warns restants", value=str(warn_count), inline=True)
        e.add_field(name="📝 Warn supprimé", value=reason[:1024], inline=False)
        
        await i.response.edit_message(embed=e, view=None)
        
        # Log
        await send_mod_log(i.guild, 'unwarn', i.user, self.membre, reason, extra=f"Warns restants: {warn_count}")

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔇 MUTE / UNMUTE
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="mute", description="🔇 Timeout un membre")
@app_commands.describe(membre="Le membre à mute", duree="La durée (nombre)", unite="L'unité de temps", raison="La raison du mute")
@app_commands.choices(unite=[
    app_commands.Choice(name="Minutes", value="minutes"),
    app_commands.Choice(name="Heures", value="heures"),
    app_commands.Choice(name="Jours", value="jours"),
    app_commands.Choice(name="Semaine (max)", value="semaine")
])
async def mute_cmd(i: discord.Interaction, membre: discord.Member, duree: int, unite: str, raison: str):
    if not await check_mod_perm(i, 'mod_mute_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if membre.id == i.user.id:
        return await i.response.send_message("❌ Vous ne pouvez pas vous mute vous-même", ephemeral=True)
    
    if membre.bot:
        return await i.response.send_message("❌ Vous ne pouvez pas mute un bot", ephemeral=True)
    
    if membre.top_role >= i.user.top_role and i.user.id != i.guild.owner_id:
        return await i.response.send_message("❌ Vous ne pouvez pas mute ce membre", ephemeral=True)
    
    # Calculer la durée
    duree = max(1, duree)
    if unite == "minutes":
        delta = timedelta(minutes=duree)
        dur_txt = f"{duree} minute(s)"
    elif unite == "heures":
        delta = timedelta(hours=duree)
        dur_txt = f"{duree} heure(s)"
    elif unite == "jours":
        duree = min(duree, 7)
        delta = timedelta(days=duree)
        dur_txt = f"{duree} jour(s)"
    else:
        delta = timedelta(weeks=1)
        dur_txt = "1 semaine"
    
    if delta > timedelta(days=7):
        delta = timedelta(days=7)
        dur_txt = "7 jours (maximum)"
    
    # Appliquer le timeout
    try:
        await membre.timeout(delta, reason=f"{raison} - Par {i.user.name}")
    except discord.Forbidden:
        return await i.response.send_message("❌ Je ne peux pas mute ce membre (permissions)", ephemeral=True)
    except Exception as ex:
        return await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    # Enregistrer l'infraction
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO infractions(guild_id, user_id, mod_id, type, reason, duration) VALUES(?,?,?,?,?,?)',
            (i.guild.id, membre.id, i.user.id, 'mute', raison, dur_txt)
        )
        await db.commit()
    
    # Créer l'embed
    e = discord.Embed(title="🔇 Membre mute", color=C.ORANGE, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="⏱️ Durée", value=dur_txt, inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'mute', i.user, membre, raison, duration=dur_txt)

@bot.tree.command(name="unmute", description="🔊 Retirer le mute d'un membre")
@app_commands.describe(membre="Le membre à unmute", raison="La raison du unmute (optionnel)")
async def unmute_cmd(i: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison"):
    if not await check_mod_perm(i, 'mod_mute_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    if not membre.is_timed_out():
        return await i.response.send_message(f"❌ {membre.mention} n'est pas mute", ephemeral=True)
    
    try:
        await membre.timeout(None, reason=f"Unmute par {i.user.name}: {raison}")
    except discord.Forbidden:
        return await i.response.send_message("❌ Je ne peux pas unmute ce membre", ephemeral=True)
    except Exception as ex:
        return await i.response.send_message(f"❌ Erreur: {ex}", ephemeral=True)
    
    e = discord.Embed(title="🔊 Membre unmute", color=C.GREEN, timestamp=now())
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="👮 Modérateur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="📝 Raison", value=raison, inline=False)
    e.set_thumbnail(url=membre.display_avatar.url)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'unmute', i.user, membre, raison)

# ═══════════════════════════════════════════════════════════════════════════════
#                              📋 INFRACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="infractions", description="📋 Voir les infractions d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez voir les infractions")
async def infractions_cmd(i: discord.Interaction, membre: discord.Member):
    if not await check_mod_perm(i, 'mod_infractions_role'):
        return await i.response.send_message("❌ Vous n'avez pas la permission", ephemeral=True)
    
    # Récupérer les infractions (sans ORDER BY created_at pour éviter erreur si colonne n'existe pas)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT type, reason, duration, mod_id FROM infractions WHERE guild_id=? AND user_id=? ORDER BY id DESC',
            (i.guild.id, membre.id)
        ) as c:
            rows = await c.fetchall()
    
    # Calculer le temps sur le serveur
    joined = membre.joined_at
    if joined:
        days_on_server = (now() - joined.replace(tzinfo=timezone.utc)).days
        time_on_server = f"{days_on_server} jour(s)"
    else:
        time_on_server = "Inconnu"
    
    # Compter les types
    warns = sum(1 for r in rows if r[0] == 'warn')
    mutes = sum(1 for r in rows if r[0] == 'mute')
    
    # Créer l'embed
    e = discord.Embed(title=f"📋 Infractions de {membre.display_name}", color=C.BLUE, timestamp=now())
    e.set_thumbnail(url=membre.display_avatar.url)
    
    e.add_field(name="👤 Membre", value=f"{membre.mention}\n`{membre.id}`", inline=True)
    e.add_field(name="📅 Sur le serveur", value=time_on_server, inline=True)
    e.add_field(name="📊 Total", value=str(len(rows)), inline=True)
    
    e.add_field(name="⚠️ Warns", value=str(warns), inline=True)
    e.add_field(name="🔇 Mutes", value=str(mutes), inline=True)
    
    # Statut mute actuel
    if membre.is_timed_out():
        timeout_until = membre.timed_out_until
        if timeout_until:
            e.add_field(name="🔇 Mute actif", value=f"Jusqu'à <t:{int(timeout_until.timestamp())}:R>", inline=True)
        else:
            e.add_field(name="\u200b", value="\u200b", inline=True)
    else:
        e.add_field(name="\u200b", value="\u200b", inline=True)
    
    if rows:
        inf_lines = []
        for j, (typ, reason, duration, mod_id) in enumerate(rows[:10], 1):
            emoji = "⚠️" if typ == "warn" else "🔇"
            dur_txt = f" ({duration})" if duration else ""
            reason_short = reason[:40] + "..." if len(reason) > 40 else reason
            inf_lines.append(f"`{j}.` {emoji} **{typ.upper()}**{dur_txt}\n└ {reason_short}")
        
        e.add_field(name="📜 Historique (10 dernières)", value="\n".join(inf_lines)[:1024], inline=False)
    else:
        e.add_field(name="📜 Historique", value="✅ Aucune infraction", inline=False)
    
    await i.response.send_message(embed=e)
    
    # Log
    await send_mod_log(i.guild, 'infractions', i.user, membre, extra=f"Total: {len(rows)} infractions")

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎭 RELLSEAS COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="rellseas", description="🎭 Donner ou retirer le rôle Realsy à un membre")
@app_commands.describe(membre="Le membre", action="Donner ou retirer le rôle")
@app_commands.choices(action=[
    app_commands.Choice(name="Donner le rôle", value="add"),
    app_commands.Choice(name="Retirer le rôle", value="remove")
])
async def rellseas_cmd(i: discord.Interaction, membre: discord.Member, action: str):
    c = await cfg(i.guild.id)
    
    # Vérifier si l'utilisateur est autorisé
    if i.user.id != c.get('rellseas_user', 0) and not i.user.guild_permissions.administrator:
        return await i.response.send_message("❌ Vous n'êtes pas autorisé à utiliser cette commande", ephemeral=True)
    
    # Vérifier si le rôle est configuré
    role = i.guild.get_role(c.get('rellseas_role', 0))
    if not role:
        return await i.response.send_message("❌ Le rôle Realsy n'est pas configuré", ephemeral=True)
    
    if action == "add":
        if role in membre.roles:
            return await i.response.send_message(f"❌ {membre.mention} a déjà le rôle {role.mention}", ephemeral=True)
        
        try:
            await membre.add_roles(role, reason=f"RellSeas par {i.user.name}")
            
            # Enregistrer l'activité initiale
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''INSERT OR REPLACE INTO realsy_tracking 
                    (guild_id, user_id, last_activity, warn_count) VALUES (?, ?, ?, 0)''',
                    (i.guild.id, membre.id, now().isoformat()))
                await db.commit()
            
            e = discord.Embed(title="🎭 Rôle Realsy donné", color=C.GREEN, timestamp=now())
            e.add_field(name="👤 Membre", value=f"{membre.mention}", inline=True)
            e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
            e.set_thumbnail(url=membre.display_avatar.url)
            await i.response.send_message(embed=e)
            
            # Log
            log_ch = i.guild.get_channel(c.get('rellseas_log_channel', 0))
            if log_ch:
                await log_ch.send(embed=e)
                
        except discord.Forbidden:
            return await i.response.send_message("❌ Je ne peux pas donner ce rôle", ephemeral=True)
    
    else:  # remove
        if role not in membre.roles:
            return await i.response.send_message(f"❌ {membre.mention} n'a pas le rôle {role.mention}", ephemeral=True)
        
        try:
            await membre.remove_roles(role, reason=f"RellSeas retiré par {i.user.name}")
            
            # Supprimer du tracking
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                    (i.guild.id, membre.id))
                await db.commit()
            
            e = discord.Embed(title="🎭 Rôle Realsy retiré", color=C.RED, timestamp=now())
            e.add_field(name="👤 Membre", value=f"{membre.mention}", inline=True)
            e.add_field(name="👮 Par", value=f"{i.user.mention}", inline=True)
            e.set_thumbnail(url=membre.display_avatar.url)
            await i.response.send_message(embed=e)
            
            # Log
            log_ch = i.guild.get_channel(c.get('rellseas_log_channel', 0))
            if log_ch:
                await log_ch.send(embed=e)
                
        except discord.Forbidden:
            return await i.response.send_message("❌ Je ne peux pas retirer ce rôle", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              💡 SUGGESTION COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

suggestion_cooldowns = {}

@bot.tree.command(name="suggestion", description="💡 Proposer une suggestion")
@app_commands.describe(titre="Titre de votre suggestion", proposition="Décrivez votre suggestion en détail")
async def suggestion_cmd(i: discord.Interaction, titre: str, proposition: str):
    c = await cfg(i.guild.id)
    
    # Vérifier le rôle
    role_id = c.get('suggestion_role', 0)
    if role_id:
        role = i.guild.get_role(role_id)
        if role and role not in i.user.roles:
            return await i.response.send_message(f"❌ Vous devez avoir le rôle {role.mention}", ephemeral=True)
    
    # Vérifier le salon
    sugg_ch = i.guild.get_channel(c.get('suggestion_channel', 0))
    if not sugg_ch:
        return await i.response.send_message("❌ Le salon des suggestions n'est pas configuré", ephemeral=True)
    
    # Vérifier le cooldown
    cooldown_key = (i.guild.id, i.user.id)
    cd_duration = c.get('suggestion_cooldown', 1)
    cd_unit = c.get('suggestion_cooldown_unit', 'jours')
    
    if cd_unit == 'semaines':
        cd_seconds = cd_duration * 7 * 24 * 3600
    else:
        cd_seconds = cd_duration * 24 * 3600
    
    if cooldown_key in suggestion_cooldowns:
        last_time = suggestion_cooldowns[cooldown_key]
        elapsed = (now() - last_time).total_seconds()
        if elapsed < cd_seconds:
            remaining = cd_seconds - elapsed
            days = int(remaining // 86400)
            hours = int((remaining % 86400) // 3600)
            return await i.response.send_message(
                f"⏱️ Attendez encore **{days}j {hours}h**",
                ephemeral=True
            )
    
    # Créer un bel embed de suggestion
    e = discord.Embed(color=C.BLURPLE, timestamp=now())
    e.set_author(name="💡 Nouvelle Suggestion", icon_url=i.guild.icon.url if i.guild.icon else None)
    
    e.add_field(name="📋 Titre", value=f"```{titre[:100]}```", inline=False)
    e.add_field(name="📝 Proposition", value=proposition[:1000], inline=False)
    
    e.add_field(name="👤 Auteur", value=f"{i.user.mention}", inline=True)
    e.add_field(name="🆔 ID", value=f"`{i.user.id}`", inline=True)
    e.add_field(name="📅 Date", value=f"<t:{int(now().timestamp())}:R>", inline=True)
    
    e.set_thumbnail(url=i.user.display_avatar.url)
    e.set_footer(text="Votez ci-dessous! ✅ Pour | 🟠 Neutre | ❌ Contre")
    
    # Envoyer
    msg = await sugg_ch.send(embed=e)
    
    # Ajouter les réactions
    await msg.add_reaction("✅")
    await msg.add_reaction("🟠")
    await msg.add_reaction("❌")
    
    # Enregistrer le cooldown
    suggestion_cooldowns[cooldown_key] = now()
    
    # Stocker pour le tracking
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO suggestions (guild_id, message_id, user_id, title) VALUES (?, ?, ?, ?)',
            (i.guild.id, msg.id, i.user.id, titre))
        await db.commit()
    
    # Confirmation
    confirm = discord.Embed(title="✅ Suggestion envoyée!", color=C.GREEN)
    confirm.description = f"Votre suggestion a été publiée dans {sugg_ch.mention}"
    confirm.add_field(name="📋 Titre", value=titre[:100], inline=False)
    await i.response.send_message(embed=confirm, ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🔄 TRADE COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

trade_cooldowns = {}

@bot.tree.command(name="trade", description="🔄 Créer une annonce d'échange")
async def trade_cmd(i: discord.Interaction):
    c = await cfg(i.guild.id)
    
    # Vérifier le rôle
    role_id = c.get('trade_role', 0)
    if role_id:
        role = i.guild.get_role(role_id)
        if role and role not in i.user.roles:
            return await i.response.send_message(f"❌ Vous devez avoir le rôle {role.mention}", ephemeral=True)
    
    # Vérifier le salon
    trade_ch = i.guild.get_channel(c.get('trade_channel', 0))
    if not trade_ch:
        return await i.response.send_message("❌ Le salon des trades n'est pas configuré", ephemeral=True)
    
    # Vérifier le cooldown
    cooldown_key = (i.guild.id, i.user.id)
    cd_duration = c.get('trade_cooldown', 1)
    cd_unit = c.get('trade_cooldown_unit', 'heures')
    
    if cd_unit == 'secondes':
        cd_seconds = cd_duration
    elif cd_unit == 'minutes':
        cd_seconds = cd_duration * 60
    elif cd_unit == 'heures':
        cd_seconds = cd_duration * 3600
    elif cd_unit == 'jours':
        cd_seconds = cd_duration * 86400
    elif cd_unit == 'semaines':
        cd_seconds = cd_duration * 604800
    else:
        cd_seconds = cd_duration * 3600
    
    if cooldown_key in trade_cooldowns:
        last_time = trade_cooldowns[cooldown_key]
        elapsed = (now() - last_time).total_seconds()
        if elapsed < cd_seconds:
            remaining = cd_seconds - elapsed
            if remaining >= 86400:
                time_txt = f"{int(remaining // 86400)}j {int((remaining % 86400) // 3600)}h"
            elif remaining >= 3600:
                time_txt = f"{int(remaining // 3600)}h {int((remaining % 3600) // 60)}min"
            elif remaining >= 60:
                time_txt = f"{int(remaining // 60)}min {int(remaining % 60)}s"
            else:
                time_txt = f"{int(remaining)}s"
            return await i.response.send_message(f"⏱️ Attendez encore **{time_txt}**", ephemeral=True)
    
    # Afficher le menu de création
    v = TradeBuilderView(i.user, i.guild, i.channel, trade_ch)
    e = v.get_embed()
    await i.response.send_message(embed=e, view=v, ephemeral=True)

class TradeBuilderView(View):
    def __init__(self, user, guild, channel, trade_ch):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.channel = channel
        self.trade_ch = trade_ch
        self.jeu = ""
        self.je_donne = []
        self.je_veux = []
        self.texte_donne = ""
        self.texte_veux = ""
        
        # Ajouter les selects d'emojis si le serveur en a
        emojis = list(guild.emojis)[:25]
        if emojis:
            self.add_item(TradeEmojiGiveSelect(self, emojis))
            self.add_item(TradeEmojiWantSelect(self, emojis))
    
    def get_embed(self):
        e = discord.Embed(title="🔄 Créer un Trade", color=C.PURPLE)
        
        # Construire l'affichage
        donne_display = " ".join(self.je_donne) + (" " + self.texte_donne if self.texte_donne else "")
        veux_display = " ".join(self.je_veux) + (" " + self.texte_veux if self.texte_veux else "")
        
        e.add_field(name="🎮 Jeu", value=self.jeu if self.jeu else "*Non défini*", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        
        e.add_field(name="📤 Je DONNE", value=donne_display.strip() if donne_display.strip() else "*Rien sélectionné*", inline=True)
        e.add_field(name="➡️", value="🔄", inline=True)
        e.add_field(name="📥 Je VEUX", value=veux_display.strip() if veux_display.strip() else "*Rien sélectionné*", inline=True)
        
        # Instructions
        if self.jeu and (donne_display.strip() or veux_display.strip()):
            e.set_footer(text="✅ Cliquez sur Confirmer pour continuer")
            e.color = C.GREEN
        else:
            e.set_footer(text="1️⃣ Définissez le jeu • 2️⃣ Sélectionnez/écrivez vos items • 3️⃣ Confirmez")
        
        return e
    
    @discord.ui.button(label="🎮 Définir le Jeu", style=discord.ButtonStyle.primary, row=2)
    async def set_game(self, i, b):
        await i.response.send_modal(TradeGameModal(self))
    
    @discord.ui.button(label="✏️ Texte Donne", style=discord.ButtonStyle.secondary, row=2)
    async def set_text_give(self, i, b):
        await i.response.send_modal(TradeTextGiveModal(self))
    
    @discord.ui.button(label="✏️ Texte Veux", style=discord.ButtonStyle.secondary, row=2)
    async def set_text_want(self, i, b):
        await i.response.send_modal(TradeTextWantModal(self))
    
    @discord.ui.button(label="✅ Confirmer", style=discord.ButtonStyle.success, row=3)
    async def confirm(self, i, b):
        donne_display = " ".join(self.je_donne) + (" " + self.texte_donne if self.texte_donne else "")
        veux_display = " ".join(self.je_veux) + (" " + self.texte_veux if self.texte_veux else "")
        
        if not self.jeu:
            return await i.response.send_message("❌ Définissez le jeu d'abord!", ephemeral=True)
        if not donne_display.strip() and not veux_display.strip():
            return await i.response.send_message("❌ Ajoutez au moins un item!", ephemeral=True)
        
        # Demander la preuve
        e = discord.Embed(title="📸 Preuve requise", color=C.ORANGE)
        e.description = "**Envoyez une image** de preuve dans les **3 minutes**."
        await i.response.edit_message(embed=e, view=None)
        
        # Attendre l'image
        def check(m):
            return m.author.id == self.user.id and m.channel.id == self.channel.id and m.attachments
        
        try:
            msg = await bot.wait_for('message', timeout=180.0, check=check)
            
            attachment = msg.attachments[0]
            image_data = await attachment.read()
            image_filename = attachment.filename
            
            try:
                await msg.delete()
            except:
                pass
            
        except asyncio.TimeoutError:
            return await i.followup.send("❌ Temps écoulé!", ephemeral=True)
        
        # Créer le post professionnel
        e = discord.Embed(color=C.GOLD)
        e.set_author(name=f"🔄 TRADE • {self.jeu.upper()}", icon_url=self.user.display_avatar.url)
        
        # Affichage horizontal bien propre
        e.add_field(
            name="📤 DONNE",
            value=donne_display.strip() if donne_display.strip() else "—",
            inline=True
        )
        e.add_field(
            name="⚡",
            value="🔄",
            inline=True
        )
        e.add_field(
            name="📥 VEUT",
            value=veux_display.strip() if veux_display.strip() else "—",
            inline=True
        )
        
        # Infos trader compactes
        e.add_field(
            name="",
            value=f"👤 {self.user.mention} • `{self.user.id}` • <t:{int(now().timestamp())}:R>",
            inline=False
        )
        
        # Image en petit (thumbnail en haut à droite)
        image_file = discord.File(io.BytesIO(image_data), filename=image_filename)
        e.set_thumbnail(url=f"attachment://{image_filename}")
        
        e.set_footer(text="✅ Intéressé? Réagissez! • 💬 MP pour négocier")
        
        # Envoyer
        trade_msg = await self.trade_ch.send(embed=e, file=image_file)
        await trade_msg.add_reaction("✅")
        await trade_msg.add_reaction("💬")
        
        trade_cooldowns[(self.guild.id, self.user.id)] = now()
        
        confirm = discord.Embed(title="✅ Trade publié!", color=C.GREEN)
        confirm.description = f"Votre offre a été publiée dans {self.trade_ch.mention}"
        await i.followup.send(embed=confirm, ephemeral=True)
    
    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger, row=3)
    async def cancel(self, i, b):
        await i.response.edit_message(embed=discord.Embed(title="❌ Trade annulé", color=C.RED), view=None)

class TradeEmojiGiveSelect(Select):
    def __init__(self, parent, emojis):
        self.parent = parent
        self.emoji_map = {}  # Stocker le mapping id -> format string
        options = []
        for e in emojis[:25]:
            # Stocker le format complet de l'emoji
            if e.animated:
                self.emoji_map[str(e.id)] = f"<a:{e.name}:{e.id}>"
            else:
                self.emoji_map[str(e.id)] = f"<:{e.name}:{e.id}>"
            options.append(discord.SelectOption(
                label=e.name[:25],
                value=str(e.id),
                emoji=e
            ))
        super().__init__(
            placeholder="📤 Emojis à DONNER...",
            options=options,
            min_values=0,
            max_values=min(len(options), 10),
            row=0
        )
    
    async def callback(self, i):
        self.parent.je_donne = []
        for emoji_id in self.values:
            # Utiliser le format stocké directement
            if emoji_id in self.emoji_map:
                self.parent.je_donne.append(self.emoji_map[emoji_id])
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeEmojiWantSelect(Select):
    def __init__(self, parent, emojis):
        self.parent = parent
        self.emoji_map = {}  # Stocker le mapping id -> format string
        options = []
        for e in emojis[:25]:
            # Stocker le format complet de l'emoji
            if e.animated:
                self.emoji_map[str(e.id)] = f"<a:{e.name}:{e.id}>"
            else:
                self.emoji_map[str(e.id)] = f"<:{e.name}:{e.id}>"
            options.append(discord.SelectOption(
                label=e.name[:25],
                value=str(e.id),
                emoji=e
            ))
        super().__init__(
            placeholder="📥 Emojis que je VEUX...",
            options=options,
            min_values=0,
            max_values=min(len(options), 10),
            row=1
        )
    
    async def callback(self, i):
        self.parent.je_veux = []
        for emoji_id in self.values:
            # Utiliser le format stocké directement
            if emoji_id in self.emoji_map:
                self.parent.je_veux.append(self.emoji_map[emoji_id])
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeGameModal(Modal, title="🎮 Définir le Jeu"):
    jeu = TextInput(label="Nom du jeu", placeholder="Ex: Rocket League, Fortnite, GTA RP...", max_length=50)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.jeu = self.jeu.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeTextGiveModal(Modal, title="📤 Ce que je DONNE (texte)"):
    texte = TextInput(label="Description", placeholder="Ex: 500 crédits, Voiture TW...", style=discord.TextStyle.paragraph, max_length=150, required=False)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.texte_donne = self.texte.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

class TradeTextWantModal(Modal, title="📥 Ce que je VEUX (texte)"):
    texte = TextInput(label="Description", placeholder="Ex: Octane TW, 1000 crédits...", style=discord.TextStyle.paragraph, max_length=150, required=False)
    
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    
    async def on_submit(self, i):
        self.parent.texte_veux = self.texte.value
        await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

# ═══════════════════════════════════════════════════════════════════════════════
#                              📊 COMMANDE /STAT - STATISTIQUES MEMBRE
# ═══════════════════════════════════════════════════════════════════════════════

@bot.tree.command(name="stat", description="📊 Voir les statistiques d'activité d'un membre")
@app_commands.describe(membre="Le membre dont vous voulez voir les stats (vous par défaut)")
async def stat_cmd(i: discord.Interaction, membre: discord.Member = None):
    target = membre or i.user
    
    if target.bot:
        return await i.response.send_message("❌ Les bots n'ont pas de statistiques", ephemeral=True)
    
    await i.response.defer()
    
    # Générer les stats pour 7 jours par défaut
    stats = await get_member_stats(i.guild, target, 7)
    embed, file = await create_stat_embed(i.guild, target, stats, 7)
    
    v = StatMemberView(i.user, i.guild, target)
    
    if file:
        await i.followup.send(embed=embed, file=file, view=v)
    else:
        await i.followup.send(embed=embed, view=v)

class StatMemberView(View):
    def __init__(self, user, guild, target):
        super().__init__(timeout=300)
        self.user = user
        self.guild = guild
        self.target = target
        self.period = 7
    
    @discord.ui.button(label="📅 7 Jours", style=discord.ButtonStyle.primary, disabled=True)
    async def btn_7d(self, i, b):
        self.period = 7
        self.btn_7d.disabled = True
        self.btn_30d.disabled = False
        await self.refresh(i)
    
    @discord.ui.button(label="📅 30 Jours", style=discord.ButtonStyle.secondary)
    async def btn_30d(self, i, b):
        self.period = 30
        self.btn_7d.disabled = False
        self.btn_30d.disabled = True
        await self.refresh(i)
    
    @discord.ui.button(label="📈 Graphique Détaillé", style=discord.ButtonStyle.success, row=1)
    async def btn_graph(self, i, b):
        await i.response.defer()
        img = await generate_detailed_stat_graph(self.guild, self.target, self.period)
        if img:
            file = discord.File(img, filename="stats_detailed.png")
            e = discord.Embed(
                title=f"📊 Statistiques Détaillées - {self.target.display_name}",
                color=C.PURPLE
            )
            e.set_image(url="attachment://stats_detailed.png")
            e.set_footer(text=f"Période: {self.period} jours • {self.guild.name}")
            await i.followup.send(embed=e, file=file, ephemeral=True)
        else:
            await i.followup.send("❌ Pas assez de données pour générer un graphique", ephemeral=True)
    
    async def refresh(self, i):
        await i.response.defer()
        stats = await get_member_stats(self.guild, self.target, self.period)
        embed, file = await create_stat_embed(self.guild, self.target, stats, self.period)
        
        if file:
            await i.message.delete()
            await i.followup.send(embed=embed, file=file, view=self)
        else:
            await i.message.edit(embed=embed, view=self)

async def get_member_stats(guild, member, days):
    """Récupère les statistiques d'un membre sur une période donnée"""
    stats = {
        'total_messages': 0,
        'total_vocal_time': 0,
        'channels_messages': {},  # {channel_id: count}
        'channels_vocal': {},  # {channel_id: duration}
        'messages_per_day': {},  # {date: count}
        'vocal_per_day': {},  # {date: duration}
        'most_popular_message': None,
        'first_activity': None,
        'last_activity': None
    }
    
    try:
        cutoff = now() - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Récupérer les messages
            async with db.execute('''
                SELECT channel_id, message_id, created_at FROM member_activity 
                WHERE guild_id=? AND user_id=? AND activity_type='message' AND created_at >= ?
                ORDER BY created_at ASC
            ''', (guild.id, member.id, cutoff_str)) as cursor:
                async for row in cursor:
                    ch_id, msg_id, created_at = row
                    stats['total_messages'] += 1
                    
                    # Par salon
                    stats['channels_messages'][ch_id] = stats['channels_messages'].get(ch_id, 0) + 1
                    
                    # Par jour
                    try:
                        dt = datetime.fromisoformat(created_at)
                        date_key = dt.strftime('%Y-%m-%d')
                        stats['messages_per_day'][date_key] = stats['messages_per_day'].get(date_key, 0) + 1
                        
                        if not stats['first_activity'] or dt < stats['first_activity']:
                            stats['first_activity'] = dt
                        if not stats['last_activity'] or dt > stats['last_activity']:
                            stats['last_activity'] = dt
                    except:
                        pass
            
            # Récupérer les sessions vocales
            async with db.execute('''
                SELECT channel_id, duration, created_at FROM member_activity 
                WHERE guild_id=? AND user_id=? AND activity_type='vocal' AND created_at >= ?
                ORDER BY created_at ASC
            ''', (guild.id, member.id, cutoff_str)) as cursor:
                async for row in cursor:
                    ch_id, duration, created_at = row
                    stats['total_vocal_time'] += duration or 0
                    
                    # Par salon
                    stats['channels_vocal'][ch_id] = stats['channels_vocal'].get(ch_id, 0) + (duration or 0)
                    
                    # Par jour
                    try:
                        dt = datetime.fromisoformat(created_at)
                        date_key = dt.strftime('%Y-%m-%d')
                        stats['vocal_per_day'][date_key] = stats['vocal_per_day'].get(date_key, 0) + (duration or 0)
                        
                        if not stats['first_activity'] or dt < stats['first_activity']:
                            stats['first_activity'] = dt
                        if not stats['last_activity'] or dt > stats['last_activity']:
                            stats['last_activity'] = dt
                    except:
                        pass
        
        # Trouver le message le plus populaire (avec le plus de réactions)
        # On cherche dans les derniers messages du membre
        if stats['channels_messages']:
            top_channel_id = max(stats['channels_messages'], key=stats['channels_messages'].get)
            channel = guild.get_channel(top_channel_id)
            if channel:
                try:
                    async for msg in channel.history(limit=100):
                        if msg.author.id == member.id:
                            reaction_count = sum(r.count for r in msg.reactions) if msg.reactions else 0
                            if reaction_count > 0:
                                if not stats['most_popular_message'] or reaction_count > stats['most_popular_message']['reactions']:
                                    stats['most_popular_message'] = {
                                        'content': msg.content[:100] + "..." if len(msg.content) > 100 else msg.content,
                                        'reactions': reaction_count,
                                        'url': msg.jump_url
                                    }
                except:
                    pass
                    
    except Exception as ex:
        print(f"Erreur get_member_stats: {ex}")
    
    return stats

async def create_stat_embed(guild, member, stats, days):
    """Crée l'embed des statistiques avec graphique"""
    e = discord.Embed(
        title=f"📊 Statistiques de {member.display_name}",
        color=C.PURPLE
    )
    e.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
    
    # Période
    e.description = f"**Période:** {days} derniers jours"
    
    # Messages
    e.add_field(
        name="💬 Messages",
        value=f"**{stats['total_messages']}** messages envoyés",
        inline=True
    )
    
    # Temps vocal
    vocal_time = stats['total_vocal_time']
    if vocal_time >= 3600:
        time_str = f"{vocal_time // 3600}h {(vocal_time % 3600) // 60}min"
    elif vocal_time >= 60:
        time_str = f"{vocal_time // 60}min {vocal_time % 60}s"
    else:
        time_str = f"{vocal_time}s"
    
    e.add_field(
        name="🔊 Temps en vocal",
        value=f"**{time_str}**",
        inline=True
    )
    
    # Moyenne par jour
    avg_messages = stats['total_messages'] / days if days > 0 else 0
    e.add_field(
        name="📈 Moyenne/jour",
        value=f"**{avg_messages:.1f}** msg/jour",
        inline=True
    )
    
    # Salon écrit le plus actif
    if stats['channels_messages']:
        top_ch_id = max(stats['channels_messages'], key=stats['channels_messages'].get)
        top_ch = guild.get_channel(top_ch_id)
        top_count = stats['channels_messages'][top_ch_id]
        e.add_field(
            name="📝 Salon écrit favoris",
            value=f"{top_ch.mention if top_ch else 'Inconnu'}\n({top_count} messages)",
            inline=True
        )
    else:
        e.add_field(name="📝 Salon écrit favoris", value="*Aucune donnée*", inline=True)
    
    # Salon vocal le plus utilisé
    if stats['channels_vocal']:
        top_vc_id = max(stats['channels_vocal'], key=stats['channels_vocal'].get)
        top_vc = guild.get_channel(top_vc_id)
        top_duration = stats['channels_vocal'][top_vc_id]
        if top_duration >= 3600:
            dur_str = f"{top_duration // 3600}h {(top_duration % 3600) // 60}min"
        elif top_duration >= 60:
            dur_str = f"{top_duration // 60}min"
        else:
            dur_str = f"{top_duration}s"
        e.add_field(
            name="🎤 Salon vocal favoris",
            value=f"{top_vc.name if top_vc else 'Inconnu'}\n({dur_str})",
            inline=True
        )
    else:
        e.add_field(name="🎤 Salon vocal favoris", value="*Aucune donnée*", inline=True)
    
    # Dernière activité
    if stats['last_activity']:
        e.add_field(
            name="🕐 Dernière activité",
            value=f"<t:{int(stats['last_activity'].timestamp())}:R>",
            inline=True
        )
    else:
        e.add_field(name="🕐 Dernière activité", value="*Inconnue*", inline=True)
    
    # Message le plus populaire
    if stats['most_popular_message']:
        mp = stats['most_popular_message']
        e.add_field(
            name=f"⭐ Message populaire ({mp['reactions']} réactions)",
            value=f"*\"{mp['content']}\"*\n[Voir le message]({mp['url']})",
            inline=False
        )
    
    # Générer le graphique
    img = await generate_stat_graph(stats, days, member.display_name)
    file = None
    if img:
        file = discord.File(img, filename="stats.png")
        e.set_image(url="attachment://stats.png")
    
    e.set_footer(text=f"{guild.name} • /stat", icon_url=guild.icon.url if guild.icon else None)
    e.timestamp = now()
    
    return e, file

async def generate_stat_graph(stats, days, username):
    """Génère un graphique des statistiques"""
    try:
        if not stats['messages_per_day'] and not stats['vocal_per_day']:
            return None
        
        # Préparer les données pour tous les jours de la période
        dates = []
        messages = []
        vocal = []
        
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            dates.append(dt.strftime('%d/%m'))
            messages.append(stats['messages_per_day'].get(date_key, 0))
            vocal.append(stats['vocal_per_day'].get(date_key, 0) / 60)  # Convertir en minutes
        
        # Créer le graphique
        fig, ax1 = plt.subplots(figsize=(12, 5))
        fig.patch.set_facecolor('#2f3136')
        ax1.set_facecolor('#36393f')
        
        # Barres pour les messages
        x = range(len(dates))
        bars = ax1.bar([i - 0.2 for i in x], messages, 0.4, label='Messages', color='#5865F2', alpha=0.8)
        ax1.set_xlabel('Date', color='white', fontsize=10)
        ax1.set_ylabel('Messages', color='#5865F2', fontsize=10)
        ax1.tick_params(axis='y', labelcolor='#5865F2')
        ax1.tick_params(axis='x', colors='white')
        
        # Deuxième axe pour le vocal
        ax2 = ax1.twinx()
        bars2 = ax2.bar([i + 0.2 for i in x], vocal, 0.4, label='Vocal (min)', color='#57F287', alpha=0.8)
        ax2.set_ylabel('Minutes en vocal', color='#57F287', fontsize=10)
        ax2.tick_params(axis='y', labelcolor='#57F287')
        
        # Style
        ax1.set_xticks(x)
        ax1.set_xticklabels(dates, rotation=45, ha='right', fontsize=8)
        ax1.spines['bottom'].set_color('white')
        ax1.spines['left'].set_color('#5865F2')
        ax1.spines['top'].set_visible(False)
        ax2.spines['right'].set_color('#57F287')
        ax2.spines['top'].set_visible(False)
        
        # Titre
        plt.title(f'📊 Activité de {username}', color='white', fontsize=14, fontweight='bold', pad=15)
        
        # Légende
        fig.legend(loc='upper right', bbox_to_anchor=(0.98, 0.98), facecolor='#36393f', edgecolor='white', labelcolor='white')
        
        plt.tight_layout()
        
        # Sauvegarder
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
        buf.seek(0)
        plt.close(fig)
        
        return buf
        
    except Exception as ex:
        print(f"Erreur génération graphique: {ex}")
        return None

async def generate_detailed_stat_graph(guild, member, days):
    """Génère un graphique détaillé avec plusieurs visualisations"""
    try:
        stats = await get_member_stats(guild, member, days)
        
        if not stats['total_messages'] and not stats['total_vocal_time']:
            return None
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.patch.set_facecolor('#2f3136')
        
        # 1. Camembert des salons écrits (haut gauche)
        ax1 = axes[0, 0]
        ax1.set_facecolor('#2f3136')
        
        if stats['channels_messages']:
            # Top 5 salons
            sorted_channels = sorted(stats['channels_messages'].items(), key=lambda x: x[1], reverse=True)[:5]
            labels = []
            sizes = []
            for ch_id, count in sorted_channels:
                ch = guild.get_channel(ch_id)
                labels.append(f"#{ch.name[:15]}" if ch else f"#{ch_id}")
                sizes.append(count)
            
            colors = ['#5865F2', '#57F287', '#FEE75C', '#ED4245', '#9B59B6']
            ax1.pie(sizes, labels=labels, colors=colors[:len(sizes)], autopct='%1.1f%%',
                   textprops={'color': 'white', 'fontsize': 9})
            ax1.set_title('📝 Top Salons Écrits', color='white', fontsize=12, fontweight='bold')
        else:
            ax1.text(0.5, 0.5, 'Aucune donnée', ha='center', va='center', color='white', fontsize=12)
            ax1.set_title('📝 Top Salons Écrits', color='white', fontsize=12, fontweight='bold')
        
        # 2. Camembert des salons vocaux (haut droit)
        ax2 = axes[0, 1]
        ax2.set_facecolor('#2f3136')
        
        if stats['channels_vocal']:
            sorted_vocal = sorted(stats['channels_vocal'].items(), key=lambda x: x[1], reverse=True)[:5]
            labels = []
            sizes = []
            for ch_id, duration in sorted_vocal:
                ch = guild.get_channel(ch_id)
                labels.append(f"🔊 {ch.name[:15]}" if ch else f"🔊 {ch_id}")
                sizes.append(duration)
            
            colors = ['#57F287', '#5865F2', '#FEE75C', '#ED4245', '#9B59B6']
            ax2.pie(sizes, labels=labels, colors=colors[:len(sizes)], autopct='%1.1f%%',
                   textprops={'color': 'white', 'fontsize': 9})
            ax2.set_title('🎤 Top Salons Vocaux', color='white', fontsize=12, fontweight='bold')
        else:
            ax2.text(0.5, 0.5, 'Aucune donnée', ha='center', va='center', color='white', fontsize=12)
            ax2.set_title('🎤 Top Salons Vocaux', color='white', fontsize=12, fontweight='bold')
        
        # 3. Courbe d'activité messages (bas gauche)
        ax3 = axes[1, 0]
        ax3.set_facecolor('#36393f')
        
        dates = []
        messages = []
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            dates.append(dt.strftime('%d/%m'))
            messages.append(stats['messages_per_day'].get(date_key, 0))
        
        ax3.fill_between(range(len(dates)), messages, alpha=0.3, color='#5865F2')
        ax3.plot(range(len(dates)), messages, color='#5865F2', linewidth=2, marker='o', markersize=4)
        ax3.set_xlabel('Date', color='white', fontsize=10)
        ax3.set_ylabel('Messages', color='white', fontsize=10)
        ax3.set_title('💬 Messages par jour', color='white', fontsize=12, fontweight='bold')
        ax3.tick_params(colors='white')
        ax3.set_xticks(range(0, len(dates), max(1, len(dates)//7)))
        ax3.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45, fontsize=8)
        ax3.spines['bottom'].set_color('white')
        ax3.spines['left'].set_color('white')
        ax3.spines['top'].set_visible(False)
        ax3.spines['right'].set_visible(False)
        ax3.grid(True, alpha=0.2, color='white')
        
        # 4. Courbe d'activité vocale (bas droit)
        ax4 = axes[1, 1]
        ax4.set_facecolor('#36393f')
        
        vocal = []
        for i in range(days):
            dt = now() - timedelta(days=days-1-i)
            date_key = dt.strftime('%Y-%m-%d')
            vocal.append(stats['vocal_per_day'].get(date_key, 0) / 60)  # En minutes
        
        ax4.fill_between(range(len(dates)), vocal, alpha=0.3, color='#57F287')
        ax4.plot(range(len(dates)), vocal, color='#57F287', linewidth=2, marker='o', markersize=4)
        ax4.set_xlabel('Date', color='white', fontsize=10)
        ax4.set_ylabel('Minutes', color='white', fontsize=10)
        ax4.set_title('🎤 Temps vocal par jour', color='white', fontsize=12, fontweight='bold')
        ax4.tick_params(colors='white')
        ax4.set_xticks(range(0, len(dates), max(1, len(dates)//7)))
        ax4.set_xticklabels([dates[i] for i in range(0, len(dates), max(1, len(dates)//7))], rotation=45, fontsize=8)
        ax4.spines['bottom'].set_color('white')
        ax4.spines['left'].set_color('white')
        ax4.spines['top'].set_visible(False)
        ax4.spines['right'].set_visible(False)
        ax4.grid(True, alpha=0.2, color='white')
        
        # Titre principal
        fig.suptitle(f'📊 Statistiques détaillées de {member.display_name}', 
                    color='white', fontsize=16, fontweight='bold', y=0.98)
        
        plt.tight_layout(rect=[0, 0, 1, 0.96])
        
        # Sauvegarder
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor='#2f3136', edgecolor='none', dpi=100)
        buf.seek(0)
        plt.close(fig)
        
        return buf
        
    except Exception as ex:
        print(f"Erreur génération graphique détaillé: {ex}")
        return None

# ═══════════════════════════════════════════════════════════════════════════════
#                              📊 SUGGESTION VOTE TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    
    # Vérifier si c'est une suggestion
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id FROM suggestions WHERE message_id=?', (payload.message_id,)) as c:
                if not await c.fetchone():
                    return
        
        # Mettre à jour la couleur de l'embed
        channel = bot.get_channel(payload.channel_id)
        if not channel:
            return
        
        msg = await channel.fetch_message(payload.message_id)
        
        # Compter les votes
        votes = {"✅": 0, "🟠": 0, "❌": 0}
        for reaction in msg.reactions:
            if reaction.emoji in votes:
                votes[reaction.emoji] = reaction.count - 1  # -1 pour le bot
        
        # Déterminer la couleur
        total = sum(votes.values())
        if total == 0:
            color = C.BLURPLE
        elif votes["✅"] > votes["❌"] and votes["✅"] > votes["🟠"]:
            color = C.GREEN
        elif votes["❌"] > votes["✅"] and votes["❌"] > votes["🟠"]:
            color = C.RED
        elif votes["🟠"] > votes["✅"] and votes["🟠"] > votes["❌"]:
            color = C.ORANGE
        else:
            color = C.BLURPLE
        
        # Mettre à jour l'embed
        if msg.embeds:
            old_embed = msg.embeds[0]
            new_embed = discord.Embed(
                title=old_embed.title,
                description=old_embed.description,
                color=color,
                timestamp=old_embed.timestamp
            )
            for field in old_embed.fields:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            if old_embed.thumbnail:
                new_embed.set_thumbnail(url=old_embed.thumbnail.url)
            new_embed.set_footer(text=f"✅ {votes['✅']} | 🟠 {votes['🟠']} | ❌ {votes['❌']}")
            
            await msg.edit(embed=new_embed)
    except:
        pass

@bot.event
async def on_raw_reaction_remove(payload):
    await on_raw_reaction_add(payload)  # Même logique

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎭 REALSY INACTIVITY TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(hours=24)
async def check_realsy_inactivity():
    """Vérifie l'inactivité des utilisateurs avec le rôle Realsy chaque jour"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, user_id, last_activity, warn_count FROM realsy_tracking') as c:
                rows = await c.fetchall()
        
        for guild_id, user_id, last_activity, warn_count in rows:
            try:
                guild = bot.get_guild(guild_id)
                if not guild:
                    continue
                
                c = await cfg(guild_id)
                role = guild.get_role(c.get('rellseas_role', 0))
                if not role:
                    continue
                
                member = guild.get_member(user_id)
                if not member or role not in member.roles:
                    # L'utilisateur n'a plus le rôle, supprimer du tracking
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                            (guild_id, user_id))
                        await db.commit()
                    continue
                
                # Calculer l'inactivité
                try:
                    last_dt = datetime.fromisoformat(last_activity)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                except:
                    last_dt = now() - timedelta(days=8)  # Considérer comme inactif si erreur
                
                days_inactive = (now() - last_dt).days
                
                if days_inactive >= 7:
                    warn_ch = guild.get_channel(c.get('rellseas_warn_channel', 0))
                    log_ch = guild.get_channel(c.get('rellseas_log_channel', 0))
                    
                    if warn_count == 0:
                        # Premier warn
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute('UPDATE realsy_tracking SET warn_count=1 WHERE guild_id=? AND user_id=?',
                                (guild_id, user_id))
                            await db.commit()
                        
                        if warn_ch:
                            e = discord.Embed(title="⚠️ Avertissement Inactivité", color=C.YELLOW, timestamp=now())
                            e.description = f"{member.mention}, vous êtes inactif depuis **{days_inactive} jours**.\n\n⚠️ Si vous restez inactif, votre rôle **{role.name}** sera retiré."
                            e.set_thumbnail(url=member.display_avatar.url)
                            await warn_ch.send(content=member.mention, embed=e)
                        
                        if log_ch:
                            log_e = discord.Embed(title="⚠️ Warn Inactivité #1", color=C.YELLOW, timestamp=now())
                            log_e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
                            log_e.add_field(name="📅 Inactif depuis", value=f"{days_inactive} jours", inline=True)
                            log_e.set_thumbnail(url=member.display_avatar.url)
                            await log_ch.send(embed=log_e)
                    
                    elif warn_count >= 1 and days_inactive >= 14:
                        # Deuxième warn - retirer le rôle
                        try:
                            await member.remove_roles(role, reason="Inactivité - 2ème avertissement")
                            
                            # Supprimer du tracking
                            async with aiosqlite.connect(DB_PATH) as db:
                                await db.execute('DELETE FROM realsy_tracking WHERE guild_id=? AND user_id=?',
                                    (guild_id, user_id))
                                await db.commit()
                            
                            if warn_ch:
                                e = discord.Embed(title="🚫 Rôle Retiré - Inactivité", color=C.RED, timestamp=now())
                                e.description = f"{member.mention}, votre rôle **{role.name}** a été retiré pour cause d'inactivité prolongée ({days_inactive} jours)."
                                e.set_thumbnail(url=member.display_avatar.url)
                                await warn_ch.send(content=member.mention, embed=e)
                            
                            if log_ch:
                                log_e = discord.Embed(title="🚫 Rôle Retiré - AFK", color=C.RED, timestamp=now())
                                log_e.add_field(name="👤 Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
                                log_e.add_field(name="🎭 Rôle retiré", value=role.mention, inline=True)
                                log_e.add_field(name="📅 Inactif depuis", value=f"{days_inactive} jours", inline=True)
                                log_e.set_thumbnail(url=member.display_avatar.url)
                                await log_ch.send(embed=log_e)
                        except:
                            pass
            except:
                continue
    except:
        pass

@check_realsy_inactivity.before_loop
async def before_check():
    await bot.wait_until_ready()

# ═══════════════════════════════════════════════════════════════════════════════
#                           📢 TÂCHE VÉRIFICATION FEEDS SOCIAUX
# ═══════════════════════════════════════════════════════════════════════════════

@tasks.loop(minutes=5)
async def check_social_feeds():
    """Vérifie les nouveaux posts YouTube, Twitch, Twitter, Reddit, Discord et RoSocial"""
    try:
        async with aiohttp.ClientSession() as session:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT guild_id, data FROM guild_config') as cursor:
                    async for row in cursor:
                        guild_id, data_str = row
                        try:
                            data = json.loads(data_str) if data_str else {}
                            guild = bot.get_guild(guild_id)
                            if not guild:
                                continue
                            
                            # YouTube
                            await check_youtube_feeds(session, guild, data)
                            
                            # Twitch
                            await check_twitch_feeds(session, guild, data)
                            
                            # Twitter/X
                            await check_twitter_feeds(session, guild, data)
                            
                            # Reddit
                            await check_reddit_feeds(session, guild, data)
                            
                            # RoSocial
                            await check_rosocial_feeds(session, guild, data)
                            
                        except Exception as ex:
                            print(f"Erreur feed {guild_id}: {ex}")
                            continue
    except Exception as ex:
        print(f"Erreur check_social_feeds: {ex}")

async def check_youtube_feeds(session, guild, data):
    """Vérifie les nouvelles vidéos YouTube"""
    channel = guild.get_channel(data.get('ads_youtube_channel', 0))
    feeds = data.get('ads_youtube_feeds', [])
    if not channel or not feeds:
        return
    
    for feed in feeds:
        try:
            channel_id = feed['id']
            channel_name = feed['name']
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            
            async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                xml_text = await resp.text()
            
            root = ET.fromstring(xml_text)
            ns = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015', 'media': 'http://search.yahoo.com/mrss/'}
            
            entries = root.findall('atom:entry', ns)
            if not entries:
                continue
            
            entry = entries[0]
            video_id_elem = entry.find('yt:videoId', ns)
            title_elem = entry.find('atom:title', ns)
            published_elem = entry.find('atom:published', ns)
            
            # Essayer de trouver la description
            media_group = entry.find('media:group', ns)
            description = ""
            if media_group is not None:
                desc_elem = media_group.find('media:description', ns)
                if desc_elem is not None and desc_elem.text:
                    description = desc_elem.text[:200] + "..." if len(desc_elem.text) > 200 else desc_elem.text
            
            if video_id_elem is None or title_elem is None:
                continue
            
            video_id = video_id_elem.text
            title = title_elem.text
            cache_key = f"yt_{guild.id}_{channel_id}"
            
            if cache_key in posted_content and posted_content[cache_key] == video_id:
                continue
            
            posted_content[cache_key] = video_id
            
            # ═══════════════ EMBED YOUTUBE PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0xFF0000)
            
            # Titre avec bannière
            e.title = f"▶️ {title}"
            e.url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Description du post
            if description:
                e.description = f"*{description}*"
            
            # Auteur avec logo YouTube
            e.set_author(
                name=f"🔴 YOUTUBE • {channel_name}",
                url=f"https://www.youtube.com/channel/{channel_id}",
                icon_url="https://www.gstatic.com/youtube/img/branding/youtubelogo/svg/youtubelogo.svg"
            )
            
            # Miniature grande
            e.set_image(url=f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")
            
            # Bouton "Regarder"
            e.add_field(
                name="",
                value=f"[▶️ **Regarder la vidéo**](https://www.youtube.com/watch?v={video_id})",
                inline=False
            )
            
            # Footer avec icône
            e.set_footer(
                text=f"YouTube • {channel_name}",
                icon_url="https://www.youtube.com/s/desktop/28b67e7f/img/favicon_144x144.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur YouTube feed {feed}: {ex}")
            continue

async def check_twitch_feeds(session, guild, data):
    """Vérifie si des streamers sont en live sur Twitch"""
    channel = guild.get_channel(data.get('ads_twitch_channel', 0))
    feeds = data.get('ads_twitch_feeds', [])
    if not channel or not feeds:
        return
    
    for username in feeds:
        try:
            url = f"https://www.twitch.tv/{username}"
            cache_key = f"twitch_{guild.id}_{username}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
            
            is_live = '"isLiveBroadcast":true' in html or 'isLiveBroadcast' in html
            
            was_live = posted_content.get(cache_key, False)
            
            if is_live and not was_live:
                posted_content[cache_key] = True
                
                # ═══════════════ EMBED TWITCH PROFESSIONNEL ═══════════════
                e = discord.Embed(color=0x9146FF)
                
                e.title = f"🔴 {username} est en LIVE !"
                e.url = f"https://www.twitch.tv/{username}"
                
                e.description = f"**{username}** vient de lancer un stream !\nRejoins le live maintenant !"
                
                e.set_author(
                    name=f"🟣 TWITCH • {username}",
                    url=f"https://www.twitch.tv/{username}",
                    icon_url="https://static.twitchcdn.net/assets/favicon-32-e29e246c157142c94346.png"
                )
                
                # Preview du stream (avec timestamp pour éviter le cache)
                e.set_image(url=f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{username.lower()}-1280x720.jpg?t={int(now().timestamp())}")
                
                e.add_field(
                    name="",
                    value=f"[🟣 **Rejoindre le stream**](https://www.twitch.tv/{username})",
                    inline=False
                )
                
                e.set_footer(
                    text=f"Twitch • {username}",
                    icon_url="https://static.twitchcdn.net/assets/favicon-32-e29e246c157142c94346.png"
                )
                e.timestamp = now()
                
                await channel.send(embed=e)
                
            elif not is_live and was_live:
                posted_content[cache_key] = False
            
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Twitch feed {username}: {ex}")
            continue

async def check_reddit_feeds(session, guild, data):
    """Vérifie les nouveaux posts Reddit"""
    channel = guild.get_channel(data.get('ads_reddit_channel', 0))
    feeds = data.get('ads_reddit_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Discord Bot 1.0'}
    
    for subreddit in feeds:
        try:
            rss_url = f"https://www.reddit.com/r/{subreddit}/new.rss?limit=1"
            
            async with session.get(rss_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    continue
                xml_text = await resp.text()
            
            root = ET.fromstring(xml_text)
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            
            entries = root.findall('atom:entry', ns)
            if not entries:
                continue
            
            entry = entries[0]
            post_id = entry.find('atom:id', ns)
            title = entry.find('atom:title', ns)
            link = entry.find('atom:link', ns)
            author = entry.find('atom:author/atom:name', ns)
            content = entry.find('atom:content', ns)
            
            if post_id is None or title is None:
                continue
            
            post_id = post_id.text
            title = title.text
            link = link.get('href') if link is not None else f"https://reddit.com/r/{subreddit}"
            author = author.text if author is not None else "Unknown"
            
            # Extraire image si présente dans le contenu HTML
            image_url = None
            if content is not None and content.text:
                import re
                img_match = re.search(r'<img[^>]+src="([^"]+)"', content.text)
                if img_match:
                    image_url = img_match.group(1)
            
            cache_key = f"rd_{guild.id}_{subreddit}"
            
            if cache_key in posted_content and posted_content[cache_key] == post_id:
                continue
            
            posted_content[cache_key] = post_id
            
            # ═══════════════ EMBED REDDIT PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0xFF4500)
            
            e.title = f"📰 {title[:200]}"
            e.url = link
            
            e.set_author(
                name=f"🟠 REDDIT • r/{subreddit}",
                url=f"https://www.reddit.com/r/{subreddit}",
                icon_url="https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png"
            )
            
            e.add_field(name="👤 Auteur", value=f"u/{author}", inline=True)
            e.add_field(name="📁 Subreddit", value=f"r/{subreddit}", inline=True)
            
            if image_url and ('i.redd.it' in image_url or 'preview.redd.it' in image_url):
                e.set_image(url=image_url)
            
            e.add_field(
                name="",
                value=f"[🔗 **Voir le post complet**]({link})",
                inline=False
            )
            
            e.set_footer(
                text=f"Reddit • r/{subreddit}",
                icon_url="https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Reddit feed {subreddit}: {ex}")
            continue

async def check_twitter_feeds(session, guild, data):
    """Vérifie les nouveaux tweets via Nitter"""
    channel = guild.get_channel(data.get('ads_twitter_channel', 0))
    feeds = data.get('ads_twitter_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for username in feeds:
        try:
            xml_text = None
            working_instance = None
            for instance in NITTER_INSTANCES:
                try:
                    rss_url = f"https://{instance}/{username}/rss"
                    async with session.get(rss_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            xml_text = await resp.text()
                            working_instance = instance
                            break
                except:
                    continue
            
            if not xml_text:
                continue
            
            root = ET.fromstring(xml_text)
            items = root.findall('.//item')
            if not items:
                continue
            
            item = items[0]
            title = item.find('title')
            link = item.find('link')
            guid = item.find('guid')
            description = item.find('description')
            
            if title is None or guid is None:
                continue
            
            tweet_id = guid.text if guid is not None else ""
            tweet_text = title.text if title is not None else ""
            tweet_link = link.text if link is not None else f"https://twitter.com/{username}"
            
            # Convertir lien Nitter en lien Twitter
            tweet_link = tweet_link.replace(f"https://{working_instance}", "https://twitter.com") if working_instance else tweet_link
            
            # Extraire image si présente
            image_url = None
            if description is not None and description.text:
                import re
                img_match = re.search(r'<img[^>]+src="([^"]+)"', description.text)
                if img_match:
                    image_url = img_match.group(1)
            
            cache_key = f"twitter_{guild.id}_{username}"
            
            if cache_key in posted_content and posted_content[cache_key] == tweet_id:
                continue
            
            posted_content[cache_key] = tweet_id
            
            # ═══════════════ EMBED TWITTER PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0x1DA1F2)
            
            e.description = f"💬 {tweet_text[:1900]}"
            
            e.set_author(
                name=f"🐦 TWITTER/X • @{username}",
                url=f"https://twitter.com/{username}",
                icon_url="https://abs.twimg.com/responsive-web/client-web/icon-ios.77d25eba.png"
            )
            
            if image_url:
                # Convertir URL Nitter en URL Twitter si nécessaire
                if working_instance and working_instance in image_url:
                    image_url = image_url.replace(f"https://{working_instance}", "https://pbs.twimg.com")
                e.set_image(url=image_url)
            
            e.add_field(
                name="",
                value=f"[🐦 **Voir le tweet**]({tweet_link})",
                inline=False
            )
            
            e.set_footer(
                text=f"Twitter/X • @{username}",
                icon_url="https://abs.twimg.com/responsive-web/client-web/icon-ios.77d25eba.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur Twitter feed {username}: {ex}")
            continue

async def check_rosocial_feeds(session, guild, data):
    """Vérifie les nouveaux posts RoSocial"""
    channel = guild.get_channel(data.get('ads_rosocial_channel', 0))
    feeds = data.get('ads_rosocial_feeds', [])
    if not channel or not feeds:
        return
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for username in feeds:
        try:
            url = f"https://rosocial.net/{username}"
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    continue
                html = await resp.text()
            
            import re
            
            # Trouver le dernier post
            posts = re.findall(r'href="https://rosocial\.net/posts/(\d+)"', html)
            if not posts:
                posts = re.findall(r'/posts/(\d+)', html)
            
            if not posts:
                continue
            
            latest_post_id = posts[0]
            cache_key = f"rs_{guild.id}_{username}"
            
            if cache_key in posted_content and posted_content[cache_key] == latest_post_id:
                continue
            
            posted_content[cache_key] = latest_post_id
            
            post_url = f"https://rosocial.net/posts/{latest_post_id}"
            profile_url = f"https://rosocial.net/{username}"
            
            # Extraire la photo de profil si possible
            avatar_match = re.search(rf'{username}[^>]*<img[^>]+src="([^"]+)"', html)
            avatar_url = "https://rosocial.net/content/uploads/photos/2025/11/roso_597f00df39d1431f924ec9403430e921.png"
            if avatar_match:
                avatar_url = avatar_match.group(1)
            
            # Extraire le contenu du post si possible
            post_content = ""
            content_match = re.search(rf'/posts/{latest_post_id}"[^>]*>.*?<p[^>]*>([^<]+)</p>', html, re.DOTALL)
            if content_match:
                post_content = content_match.group(1).strip()[:200]
            
            # Extraire une image du post si présente
            image_url = None
            img_match = re.search(rf'/posts/{latest_post_id}.*?<img[^>]+src="(https://rosocial\.net/content/uploads/photos/[^"]+)"', html, re.DOTALL)
            if img_match:
                image_url = img_match.group(1)
            
            # ═══════════════ EMBED ROSOCIAL PROFESSIONNEL ═══════════════
            e = discord.Embed(color=0x00D4AA)
            
            e.title = f"📝 Nouveau post de {username}"
            e.url = post_url
            
            if post_content:
                e.description = f"*{post_content}...*"
            
            e.set_author(
                name=f"🎮 ROSOCIAL • {username}",
                url=profile_url,
                icon_url="https://rosocial.net/content/uploads/photos/2025/11/roso_597f00df39d1431f924ec9403430e921.png"
            )
            
            # Thumbnail avec avatar ou logo
            e.set_thumbnail(url=avatar_url)
            
            # Image du post si disponible
            if image_url:
                e.set_image(url=image_url)
            
            e.add_field(
                name="",
                value=f"[🎮 **Voir le post**]({post_url}) • [👤 **Profil**]({profile_url})",
                inline=False
            )
            
            e.set_footer(
                text=f"RoSocial • {username}",
                icon_url="https://rosocial.net/content/uploads/photos/2025/11/roso_597f00df39d1431f924ec9403430e921.png"
            )
            e.timestamp = now()
            
            await channel.send(embed=e)
            await asyncio.sleep(1)
            
        except Exception as ex:
            print(f"Erreur RoSocial feed {username}: {ex}")
            continue

@check_social_feeds.before_loop
async def before_social_check():
    await bot.wait_until_ready()

# Mise à jour activité sur vocal
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    
    guild_id = member.guild.id
    user_id = member.id
    key = (guild_id, user_id)
    
    # Si l'utilisateur rejoint un vocal
    if after.channel and (not before.channel or before.channel != after.channel):
        await update_realsy_activity(guild_id, user_id)
        
        # Enregistrer l'heure de connexion
        voice_join_tracker[key] = now()
        
        # Tracker l'activité + redonner le rôle si configuré
        await track_member_vocal_join(member, after.channel)
    
    # Si l'utilisateur quitte un vocal
    if before.channel and (not after.channel or before.channel != after.channel):
        # Calculer le temps passé
        join_time = voice_join_tracker.pop(key, None)
        if join_time:
            duration = int((now() - join_time).total_seconds())
            if duration > 0:
                await track_member_vocal_leave(member, before.channel, duration)

async def track_member_message(msg):
    """Enregistre un message dans le tracking d'activité"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour activity_tracking
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_message, total_messages)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_message = ?,
                    total_messages = total_messages + 1
            ''', (msg.guild.id, msg.author.id, now_str, now_str))
            
            # Enregistrer dans member_activity pour les stats détaillées
            await db.execute('''
                INSERT INTO member_activity (guild_id, user_id, activity_type, channel_id, message_id, created_at)
                VALUES (?, ?, 'message', ?, ?, ?)
            ''', (msg.guild.id, msg.author.id, msg.channel.id, msg.id, now_str))
            
            await db.commit()
        
        # Redonner le rôle d'activité si configuré
        await restore_activity_role(msg.author)
        
    except Exception as ex:
        print(f"Erreur track message: {ex}")

async def track_member_vocal_join(member, channel):
    """Enregistre une connexion vocale"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour last_vocal
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, last_vocal)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    last_vocal = ?
            ''', (member.guild.id, member.id, now_str, now_str))
            
            await db.commit()
        
        # Redonner le rôle d'activité si configuré
        await restore_activity_role(member)
        
    except Exception as ex:
        print(f"Erreur track vocal join: {ex}")

async def track_member_vocal_leave(member, channel, duration):
    """Enregistre le temps passé en vocal"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            now_str = now().isoformat()
            
            # Mettre à jour le temps total en vocal
            await db.execute('''
                INSERT INTO activity_tracking (guild_id, user_id, total_vocal_time)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    total_vocal_time = total_vocal_time + ?
            ''', (member.guild.id, member.id, duration, duration))
            
            # Enregistrer la session vocale
            await db.execute('''
                INSERT INTO member_activity (guild_id, user_id, activity_type, channel_id, duration, created_at)
                VALUES (?, ?, 'vocal', ?, ?, ?)
            ''', (member.guild.id, member.id, channel.id, duration, now_str))
            
            await db.commit()
            
    except Exception as ex:
        print(f"Erreur track vocal leave: {ex}")

async def restore_activity_role(member):
    """Redonne le rôle d'activité si le membre était marqué comme inactif"""
    try:
        c = await cfg(member.guild.id)
        stat_cfg = c.get('stat_config', {})
        role_id = stat_cfg.get('activity_role', 0)
        
        if not role_id:
            return
        
        role = member.guild.get_role(role_id)
        if not role:
            return
        
        # Si le membre n'a pas le rôle, lui redonner
        if role not in member.roles:
            try:
                await member.add_roles(role, reason="Retour d'activité")
                
                # Notifier dans le salon configuré
                notif_ch_id = stat_cfg.get('notif_channel', 0)
                notif_ch = member.guild.get_channel(notif_ch_id) if notif_ch_id else None
                
                if notif_ch:
                    e = discord.Embed(
                        title="✅ Retour d'activité",
                        description=f"{member.mention} est de retour actif et a récupéré le rôle {role.mention}!",
                        color=C.GREEN
                    )
                    e.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
                    e.timestamp = now()
                    await notif_ch.send(embed=e)
            except:
                pass
                
    except Exception as ex:
        print(f"Erreur restore role: {ex}")

if __name__ == "__main__":
    print("🚀 Bot v18 - Démarrage...")
    bot.run(TOKEN)
