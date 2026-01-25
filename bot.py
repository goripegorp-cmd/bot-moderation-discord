try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
    import sys
    sys.modules['audioop'] = audioop

import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput, Button
import aiosqlite, os, re, json, asyncio, unicodedata, io, time
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
    unite = TextInput(label="Unité (secondes/minutes/heures/jours/semaines)", placeholder="heures", default="heures", max_length=10)
    
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
        except: pass
        v = TradePanel(self.u, self.g)
        await i.response.edit_message(embed=await v.embed(), view=v)

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
    
    print(f"✅ {bot.user.name} v13 prêt!")
    print(f"🌐 Serveurs: {len(bot.guilds)}")

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

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild: return
    
    # Mise à jour activité Realsy
    await update_realsy_activity(msg.guild.id, msg.author.id)
    
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
    
    # Ouvrir le modal
    await i.response.send_modal(TradeFormModal(i.guild, i.channel, trade_ch))

class TradeFormModal(Modal, title="🔄 Créer un Trade"):
    jeu = TextInput(
        label="🎮 Jeu",
        placeholder="Ex: Rocket League, Fortnite, GTA RP...",
        max_length=50
    )
    je_donne = TextInput(
        label="📤 Ce que je DONNE",
        placeholder="Décrivez ce que vous donnez...",
        style=discord.TextStyle.paragraph,
        max_length=200
    )
    je_veux = TextInput(
        label="📥 Ce que je VEUX",
        placeholder="Décrivez ce que vous voulez en échange...",
        style=discord.TextStyle.paragraph,
        max_length=200
    )
    
    def __init__(self, guild, channel, trade_ch):
        super().__init__()
        self.guild = guild
        self.channel = channel
        self.trade_ch = trade_ch
    
    async def on_submit(self, i):
        # Demander la preuve
        e = discord.Embed(title="📸 Preuve requise", color=C.ORANGE)
        e.description = "**Envoyez une image** de preuve dans les **3 minutes**.\n\n📷 *La preuve doit montrer que vous possédez les items.*"
        e.add_field(name="🎮 Jeu", value=self.jeu.value, inline=True)
        e.add_field(name="📤 Vous donnez", value=self.je_donne.value[:100], inline=True)
        e.add_field(name="📥 Vous voulez", value=self.je_veux.value[:100], inline=True)
        
        await i.response.send_message(embed=e, ephemeral=True)
        
        # Attendre l'image
        def check(m):
            return m.author.id == i.user.id and m.channel.id == self.channel.id and m.attachments
        
        try:
            msg = await bot.wait_for('message', timeout=180.0, check=check)
            
            if not msg.attachments:
                return await i.followup.send("❌ Aucune image détectée", ephemeral=True)
            
            # Télécharger l'image
            attachment = msg.attachments[0]
            image_data = await attachment.read()
            image_filename = attachment.filename
            
            # Supprimer le message
            try:
                await msg.delete()
            except:
                pass
            
        except asyncio.TimeoutError:
            return await i.followup.send("❌ Temps écoulé! Aucune preuve fournie.", ephemeral=True)
        
        # Créer le post de trade professionnel
        e = discord.Embed(color=C.GOLD)
        
        # Header compact
        e.set_author(
            name=f"🔄 TRADE • {self.jeu.value.upper()}",
            icon_url=i.user.display_avatar.url
        )
        
        # Section principale du trade - BIEN VISIBLE
        trade_display = f"```\n📤 {self.je_donne.value}\n\n       🔄\n\n📥 {self.je_veux.value}\n```"
        e.description = trade_display
        
        # Infos compactes sur une ligne
        e.add_field(
            name="ℹ️ Informations",
            value=f"👤 {i.user.mention} • 🆔 `{i.user.id}` • 📅 <t:{int(now().timestamp())}:R>",
            inline=False
        )
        
        # Image en petit (thumbnail)
        image_file = discord.File(io.BytesIO(image_data), filename=image_filename)
        e.set_thumbnail(url=f"attachment://{image_filename}")
        
        e.set_footer(text="✅ Réagissez si intéressé • 💬 Contactez en MP")
        
        # Envoyer
        trade_msg = await self.trade_ch.send(embed=e, file=image_file)
        
        await trade_msg.add_reaction("✅")
        await trade_msg.add_reaction("💬")
        
        # Cooldown
        trade_cooldowns[(self.guild.id, i.user.id)] = now()
        
        # Confirmation
        confirm = discord.Embed(title="✅ Trade publié!", color=C.GREEN)
        confirm.description = f"Votre offre a été publiée dans {self.trade_ch.mention}"
        await i.followup.send(embed=confirm, ephemeral=True)

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

# Mise à jour activité sur vocal
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    # Si l'utilisateur rejoint un vocal
    if after.channel and (not before.channel or before.channel != after.channel):
        await update_realsy_activity(member.guild.id, member.id)

if __name__ == "__main__":
    print("🚀 Bot v13 - Démarrage...")
    bot.run(TOKEN)
