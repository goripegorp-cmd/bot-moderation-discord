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
import aiosqlite,os,re,json,asyncio,unicodedata,traceback,io,time
from datetime import datetime,timedelta,timezone
from dotenv import load_dotenv

load_dotenv()
TOKEN=os.getenv('BOT_TOKEN')
DB_PATH='/data/bot.db' if os.path.exists('/data') else 'bot.db'
intents=discord.Intents.all()
bot=commands.Bot(command_prefix='!',intents=intents)
spam_tracker={}

class C:
    BLURPLE=0x5865F2;GREEN=0x57F287;RED=0xED4245;YELLOW=0xFEE75C;PURPLE=0x9B59B6;BLUE=0x3498DB;ORANGE=0xE67E22

PHISHING=['discord-nitro.gift','discordgift.site','free-nitro.com','steampowered.ru','dlscord.com']
SCAM_PATTERNS=[r'free\s*nitro',r'steam\s*gift',r'@everyone.*http']
LEET={'a':['@','4'],'e':['3','€'],'i':['1','!'],'o':['0'],'s':['$','5'],'t':['7']}
def now():return datetime.now(timezone.utc)

async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('CREATE TABLE IF NOT EXISTS guild_config(guild_id INTEGER PRIMARY KEY,data TEXT DEFAULT "{}")')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_roles(guild_id INTEGER,role_id INTEGER,PRIMARY KEY(guild_id,role_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS immune_users(guild_id INTEGER,user_id INTEGER,PRIMARY KEY(guild_id,user_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS infractions(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,user_id INTEGER,mod_id INTEGER,type TEXT,reason TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'") as cur:
            if not await cur.fetchone():
                await db.execute('CREATE TABLE tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,channel_id INTEGER,user_id INTEGER,panel_id TEXT DEFAULT "",claimed_by INTEGER DEFAULT 0,status TEXT DEFAULT "open",answers TEXT DEFAULT "{}",created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
            else:
                async with db.execute("PRAGMA table_info(tickets)") as cur2:
                    cols=[r[1] for r in await cur2.fetchall()]
                for cn,ct in[('panel_id','TEXT DEFAULT ""'),('claimed_by','INTEGER DEFAULT 0'),('status','TEXT DEFAULT "open"'),('answers','TEXT DEFAULT "{}"')]:
                    if cn not in cols:
                        try:await db.execute(f'ALTER TABLE tickets ADD COLUMN {cn} {ct}')
                        except:pass
        await db.commit()
    print("✅ DB OK")

async def db_get(gid):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM guild_config WHERE guild_id=?',(gid,)) as c:
                r=await c.fetchone()
                return json.loads(r[0]) if r and r[0] else {}
    except:return {}

async def db_set(gid,key,val):
    try:
        data=await db_get(gid);data[key]=val;jd=json.dumps(data,ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO guild_config(guild_id,data)VALUES(?,?)ON CONFLICT(guild_id)DO UPDATE SET data=?',(gid,jd,jd))
            await db.commit()
        return True
    except:return False

async def cfg(gid):
    data=await db_get(gid)
    defaults={'anti_link':0,'anti_invite':0,'anti_image':0,'anti_phishing':1,'anti_scam':1,'anti_spam':0,'anti_caps':0,'anti_newaccount':0,'anti_badwords':0,
        'link_whitelist':[],'image_allowed':[],'badwords_list':[],'link_allowed_channels':[],'image_allowed_channels':[],
        'phishing_action':'ban','scam_action':'mute','spam_action':'mute','spam_max':5,'spam_interval':5,'caps_percent':70,'newaccount_days':7,
        'log_anti_link':0,'log_anti_image':0,'log_anti_phishing':0,'log_anti_scam':0,'log_anti_spam':0,'log_anti_caps':0,'log_anti_badwords':0,'log_anti_invite':0,'log_anti_newaccount':0,
        'channel_configs':{},'ticket_staff':0,'ticket_log':0,'ticket_panels':{}}
    for k,v in defaults.items():
        if k not in data:data[k]=v
    return data

async def is_immune(m,key):
    if key!='anti_phishing' and(m.guild_permissions.administrator or m.id==m.guild.owner_id):return True
    if key in['anti_phishing','anti_link','anti_invite']:return False
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?',(m.guild.id,)) as c:
                rids=[r[0] for r in await c.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?',(m.guild.id,)) as c:
                uids=[r[0] for r in await c.fetchall()]
        if any(role.id in rids for role in m.roles) or m.id in uids:return True
    except:pass
    return False

async def sanction(m,action,dur,reason,g):
    try:
        if action=='mute':await m.timeout(timedelta(minutes=dur),reason=reason)
        elif action=='kick':await m.kick(reason=reason)
        elif action=='ban':await m.ban(reason=reason)
    except:pass

async def send_log(g,key,m,msg,reason,extra=None):
    try:
        c=await cfg(g.id);ch=g.get_channel(c.get(f'log_{key}',0))
        if not ch:return
        e=discord.Embed(title=f"🛡️ {key}",color=C.RED,timestamp=now())
        e.add_field(name="👤",value=f"{m.mention}`{m.id}`",inline=True)
        if msg and msg.channel:e.add_field(name="📍",value=msg.channel.mention,inline=True)
        e.add_field(name="⚠️",value=reason,inline=False)
        if extra:e.add_field(name="ℹ️",value=extra,inline=False)
        e.set_thumbnail(url=m.display_avatar.url)
        await ch.send(embed=e)
    except:pass

def get_gif_type(msg):
    ct=(msg.content or"").lower()
    if'tenor.com'in ct:return'tenor'
    if'giphy.com'in ct:return'giphy'
    for emb in msg.embeds:
        if emb.url and'tenor'in emb.url.lower():return'tenor'
        if emb.url and'giphy'in emb.url.lower():return'giphy'
    for att in msg.attachments:
        if att.filename.lower().endswith('.gif'):return'gif'
    return None

def normalize(t):
    t=t.lower();t=unicodedata.normalize('NFD',t);t=''.join(c for c in t if unicodedata.category(c)!='Mn')
    for l,vs in LEET.items():
        for v in vs:t=t.replace(v,l)
    return t

def check_badwords(ct,words):
    if not words:return False,None
    norm=normalize(ct)
    for w in words:
        if normalize(w.strip()) in norm:return True,w
    return False,None

def check_link(ct,wl):
    urls=re.findall(r'https?://([^\s<>"]+)',ct.lower())
    for url in urls:
        dom=url.split('/')[0]
        if not any(w.lower() in dom for w in wl):return True,url
    return False,None

def check_invite(ct):
    m=re.search(r'discord\.gg/\w+|discord\.com/invite/\w+',ct,re.I)
    return(True,m.group()) if m else(False,None)

def check_phishing(ct):
    for d in PHISHING:
        if d in ct.lower():return True,d
    return False,None

def check_scam(ct):
    for p in SCAM_PATTERNS:
        if re.search(p,ct,re.I):return True,p
    return False,None

def check_caps(ct,pct):
    ltrs=[c for c in ct if c.isalpha()]
    if len(ltrs)<10:return False
    return sum(1 for c in ltrs if c.isupper())/len(ltrs)*100>=pct

def check_image(msg,allowed):
    blocked=[]
    gt=get_gif_type(msg)
    if gt and gt not in allowed:blocked.append(gt)
    for att in msg.attachments:
        ext=att.filename.lower().split('.')[-1]
        if ext in['png','jpg','jpeg','webp','bmp'] and ext not in allowed:blocked.append(ext)
    return blocked

async def check_spam(msg,mx,intv):
    key=(msg.guild.id,msg.author.id);n=now()
    if key not in spam_tracker:spam_tracker[key]=[]
    spam_tracker[key]=[t for t in spam_tracker[key] if(n-t).total_seconds()<intv]
    spam_tracker[key].append(n)
    return len(spam_tracker[key])>mx

def check_channel_cfg(msg,conf):
    if not conf:return False,None
    ct=(msg.content or"").strip()
    if not conf.get('messages',True):
        has_txt=bool(re.sub(r'<a?:\w+:\d+>|https?://\S+','',ct).strip())
        if has_txt and not msg.attachments and not msg.embeds:return True,"messages"
    if not conf.get('images',True):
        for att in msg.attachments:
            if att.filename.lower().split('.')[-1] in['png','jpg','jpeg','webp','bmp']:return True,"images"
    if not conf.get('gifs',True) and get_gif_type(msg):return True,"gifs"
    if not conf.get('emojis',True) and re.search(r'<a?:\w+:\d+>',ct):return True,"emojis"
    if not conf.get('links',True) and re.search(r'https?://',ct):return True,"links"
    return False,None

# ═══════════════════════════════════════════════════════════════════════════════
#                           🎫 TICKETS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_ticket(ch_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id,user_id,claimed_by,answers,panel_id FROM tickets WHERE channel_id=? AND status="open"',(ch_id,)) as c:
                r=await c.fetchone()
                if r:
                    ans={}
                    try:ans=json.loads(r[3]) if r[3] else {}
                    except:pass
                    return{'id':r[0],'user':r[1],'claimed':r[2] or 0,'answers':ans,'panel_id':r[4] or''}
                return None
    except:return None

async def count_user_tickets(g,uid,pid=None):
    cnt=0;to_close=[]
    try:
        q="SELECT id,channel_id FROM tickets WHERE guild_id=? AND user_id=? AND status='open'";p=[g.id,uid]
        if pid:q+=" AND panel_id=?";p.append(pid)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(q,p) as c:
                tks=await c.fetchall()
        for tid,chid in tks:
            if g.get_channel(chid):cnt+=1
            else:to_close.append(tid)
        if to_close:
            async with aiosqlite.connect(DB_PATH) as db:
                for t in to_close:await db.execute("UPDATE tickets SET status='closed' WHERE id=?",(t,))
                await db.commit()
        return cnt
    except:return 0

async def send_ticket_log(g,lt,user,ti,extra=None,closer=None,ch=None):
    try:
        c=await cfg(g.id);lch=g.get_channel(c.get('ticket_log',0))
        if not lch:return
        colors={'create':C.GREEN,'claim':C.BLUE,'close':C.RED,'leave':C.ORANGE,'add_staff':C.PURPLE}
        titles={'create':'🎫 Créé','claim':'🙋 Pris','close':'🔒 Fermé','leave':'🚪 Parti','add_staff':'➕ Staff'}
        e=discord.Embed(title=titles.get(lt,'🎫'),color=colors.get(lt,C.BLURPLE),timestamp=now())
        e.add_field(name="🎫",value=f"#{ti.get('id','?')}",inline=True)
        uid=user.id if hasattr(user,'id') else user
        e.add_field(name="👤",value=f"<@{uid}>",inline=True)
        if lt=='claim' and extra:e.add_field(name="🙋",value=f"<@{extra}>",inline=True)
        elif lt=='close' and closer:e.add_field(name="🔒",value=closer.mention,inline=True)
        elif lt=='add_staff' and extra:e.add_field(name="➕",value=f"<@{extra}>",inline=True)
        if ti.get('answers') and lt in['create','close']:
            at="\n".join([f"**{q}**:{a[:80]}" for q,a in list(ti['answers'].items())[:5]])
            if at:e.add_field(name="📝",value=at[:1024],inline=False)
        if lt=='close' and ch:
            lines=[]
            try:
                async for m in ch.history(limit=200,oldest_first=True):
                    lines.append(f"[{m.created_at.strftime('%H:%M')}]{m.author.name}:{m.content or'[média]'}")
                f=discord.File(io.BytesIO(("\n".join(lines)).encode()),filename=f"ticket-{ti['id']}.txt")
                await lch.send(embed=e,file=f);return
            except:pass
        if hasattr(user,'display_avatar'):e.set_thumbnail(url=user.display_avatar.url)
        await lch.send(embed=e)
    except:pass

async def create_ticket(i,pid,ans=None):
    ch=None
    try:
        c=await cfg(i.guild.id);pnl=c.get('ticket_panels',{}).get(pid,{})
        cat=i.guild.get_channel(pnl.get('category',0));staff=i.guild.get_role(c.get('ticket_staff',0));mx=pnl.get('max',1)
        if not cat:return None,"❌ Catégorie non configurée"
        if await count_user_tickets(i.guild,i.user.id,pid)>=mx:return None,f"❌ Max {mx} ticket(s)"
        ow={i.guild.default_role:discord.PermissionOverwrite(view_channel=False),
            i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,attach_files=True,read_message_history=True),
            i.guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,manage_permissions=True)}
        if staff:ow[staff]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
        if i.guild.owner:ow[i.guild.owner]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True)
        ch=await i.guild.create_text_channel(f"ticket-{i.user.name}"[:50],category=cat,overwrites=ow)
        aj=json.dumps(ans or{},ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT INTO tickets(guild_id,channel_id,user_id,panel_id,claimed_by,status,answers)VALUES(?,?,?,?,0,"open",?)',(i.guild.id,ch.id,i.user.id,pid,aj))
            await db.commit()
            async with db.execute('SELECT id FROM tickets WHERE channel_id=?',(ch.id,)) as cur:
                row=await cur.fetchone();tid=row[0] if row else 0
        emb=discord.Embed(title="🎫 Nouveau Ticket",color=C.BLURPLE,timestamp=now())
        emb.add_field(name="👤",value=f"{i.user.mention}\n`{i.user.id}`",inline=True)
        emb.add_field(name="🎫",value=f"#{tid}",inline=True)
        emb.set_thumbnail(url=i.user.display_avatar.url)
        if ans:
            for t,a in ans.items():emb.add_field(name=f"📝 {t}",value=a[:1024],inline=False)
        emb.set_footer(text="Staff va prendre en charge")
        mention=i.user.mention
        if staff:mention+=f" {staff.mention}"
        await ch.send(content=mention,embed=emb,view=TicketControlView())
        await send_ticket_log(i.guild,'create',i.user,{'id':tid,'answers':ans or{}})
        return ch,None
    except Exception as ex:
        if ch:
            try:await ch.delete()
            except:pass
        return None,f"❌ {ex}"

class TicketQuestionnaireModal(Modal):
    def __init__(self,pid,qs):
        super().__init__(title="📝 Créer un ticket")
        self.pid=pid;self.qs=qs
        for i,q in enumerate(qs[:5]):
            self.add_item(TextInput(label=q.get('title',f'Q{i+1}')[:45],placeholder=q.get('question','')[:100],style=discord.TextStyle.paragraph if len(q.get('question',''))>50 else discord.TextStyle.short,required=True,max_length=500))
    async def on_submit(self,i):
        try:
            ans={self.qs[j].get('title',f'Q{j+1}'):ch.value for j,ch in enumerate(self.children) if j<len(self.qs)}
            await i.response.defer(ephemeral=True)
            ch,err=await create_ticket(i,self.pid,ans)
            await i.followup.send(err if err else f"✅ Ticket créé: {ch.mention}",ephemeral=True)
        except Exception as ex:
            try:await i.followup.send(f"❌ {ex}",ephemeral=True)
            except:pass

class TicketCreateButton(Button):
    def __init__(self,pid):
        super().__init__(label="📩 Créer un ticket",style=discord.ButtonStyle.success,custom_id=f"ticket_create_{pid}")
        self.pid=pid
    async def callback(self,i):
        try:
            c=await cfg(i.guild.id);pnl=c.get('ticket_panels',{}).get(self.pid,{})
            if not pnl:return await i.response.send_message("❌ Panel introuvable",ephemeral=True)
            qs=pnl.get('questions',[]);mx=pnl.get('max',1)
            if await count_user_tickets(i.guild,i.user.id,self.pid)>=mx:return await i.response.send_message(f"❌ Max {mx} ticket(s)",ephemeral=True)
            if qs:await i.response.send_modal(TicketQuestionnaireModal(self.pid,qs))
            else:
                await i.response.defer(ephemeral=True)
                ch,err=await create_ticket(i,self.pid)
                await i.followup.send(err if err else f"✅ Ticket créé: {ch.mention}",ephemeral=True)
        except:pass

class TicketCreateView(View):
    def __init__(self,pid):
        super().__init__(timeout=None)
        self.add_item(TicketCreateButton(pid))

class TicketControlView(View):
    def __init__(self):super().__init__(timeout=None)
    @discord.ui.button(label="🙋 Prendre en charge",style=discord.ButtonStyle.success,custom_id="ticket_ctrl_claim")
    async def claim(self,i,btn):
        try:
            tk=await get_ticket(i.channel.id)
            if not tk:return await i.response.send_message("❌",ephemeral=True)
            c=await cfg(i.guild.id);sr=i.guild.get_role(c.get('ticket_staff',0))
            if i.user.id==tk['user']:return await i.response.send_message("❌ Pas votre ticket",ephemeral=True)
            is_s=sr and sr in i.user.roles;is_o=i.user.id==i.guild.owner_id;is_a=i.user.guild_permissions.administrator
            if not(is_s or is_o or is_a):return await i.response.send_message("❌ Staff only",ephemeral=True)
            tu=i.guild.get_member(tk['user'])
            ow={i.guild.default_role:discord.PermissionOverwrite(view_channel=False),i.guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,manage_permissions=True),i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)}
            if tu:ow[tu]=discord.PermissionOverwrite(view_channel=True,send_messages=True,attach_files=True,read_message_history=True)
            if i.guild.owner and i.guild.owner!=i.user:ow[i.guild.owner]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True)
            if sr:ow[sr]=discord.PermissionOverwrite(view_channel=False)
            await i.channel.edit(overwrites=ow)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE tickets SET claimed_by=? WHERE channel_id=?',(i.user.id,i.channel.id))
                await db.commit()
            await i.response.send_message(f"✅ **{i.user.display_name}** prend en charge")
            btn.disabled=True;btn.label=f"Pris par {i.user.display_name}";btn.style=discord.ButtonStyle.secondary
            await i.message.edit(view=self)
            await send_ticket_log(i.guild,'claim',tk['user'],tk,extra=i.user.id)
        except:await i.response.send_message("❌",ephemeral=True)
    @discord.ui.button(label="➕ Ajouter Staff",style=discord.ButtonStyle.primary,custom_id="ticket_ctrl_add")
    async def add_staff(self,i,btn):
        try:
            tk=await get_ticket(i.channel.id)
            if not tk:return await i.response.send_message("❌",ephemeral=True)
            if not tk['claimed']:return await i.response.send_message("❌ Claim d'abord",ephemeral=True)
            is_o=i.user.id==i.guild.owner_id;is_c=i.user.id==tk['claimed'];is_a=i.user.guild_permissions.administrator
            if not(is_c or is_o or is_a):return await i.response.send_message("❌",ephemeral=True)
            c=await cfg(i.guild.id);sr=i.guild.get_role(c.get('ticket_staff',0))
            if not sr:return await i.response.send_message("❌",ephemeral=True)
            staffs=[m for m in sr.members if m.id!=tk['claimed'] and m.id!=tk['user']][:25]
            if not staffs:return await i.response.send_message("❌ Aucun staff",ephemeral=True)
            opts=[discord.SelectOption(label=f"@{m.display_name}"[:25],value=str(m.id)) for m in staffs]
            await i.response.send_message("👥 Staff:",view=AddStaffView(opts,i.channel.id),ephemeral=True)
        except:await i.response.send_message("❌",ephemeral=True)
    @discord.ui.button(label="🔒 Fermer",style=discord.ButtonStyle.danger,custom_id="ticket_ctrl_close")
    async def close(self,i,btn):
        try:
            tk=await get_ticket(i.channel.id)
            if not tk:return await i.response.send_message("❌",ephemeral=True)
            is_o=i.user.id==i.guild.owner_id;is_a=i.user.guild_permissions.administrator;is_c=i.user.id==tk['claimed']
            c=await cfg(i.guild.id);sr=i.guild.get_role(c.get('ticket_staff',0));is_s=sr and sr in i.user.roles
            if tk['claimed']:
                if not(is_c or is_o or is_a):return await i.response.send_message("❌",ephemeral=True)
            else:
                if not(is_s or is_o or is_a):return await i.response.send_message("❌",ephemeral=True)
            tu=i.guild.get_member(tk['user'])
            await send_ticket_log(i.guild,'close',tu or tk['user'],tk,closer=i.user,ch=i.channel)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?",(i.channel.id,))
                await db.commit()
            await i.response.send_message("🔒 Fermeture...")
            await asyncio.sleep(3);await i.channel.delete()
        except:pass

class AddStaffView(View):
    def __init__(self,opts,chid):
        super().__init__(timeout=60)
        self.add_item(AddStaffSelect(opts,chid))

class AddStaffSelect(Select):
    def __init__(self,opts,chid):
        super().__init__(placeholder="Staff...",options=opts)
        self.chid=chid
    async def callback(self,i):
        try:
            st=i.guild.get_member(int(self.values[0]));ch=i.guild.get_channel(self.chid)
            if st and ch:
                await ch.set_permissions(st,view_channel=True,send_messages=True,read_message_history=True)
                await i.response.send_message(f"✅ {st.mention} ajouté",ephemeral=True)
                await ch.send(f"➕ **{st.display_name}** ajouté par {i.user.mention}")
                tk=await get_ticket(self.chid)
                if tk:await send_ticket_log(i.guild,'add_staff',tk['user'],tk,extra=st.id)
        except:await i.response.send_message("❌",ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                           🛡️ PROTECTION PANELS
# ═══════════════════════════════════════════════════════════════════════════════

PROTS=[("anti_link","🔗","Anti-Liens"),("anti_invite","🎟️","Anti-Invite"),("anti_image","🖼️","Anti-Images"),("anti_phishing","🎣","Anti-Phishing"),("anti_scam","🚨","Anti-Scam"),("anti_spam","📨","Anti-Spam"),("anti_caps","🔠","Anti-Caps"),("anti_badwords","🤬","Anti-Insultes"),("anti_newaccount","👶","Anti-NewAccount")]

class MainPanel(View):
    def __init__(self,u,g):
        super().__init__(timeout=600)
        self.u=u;self.g=g
    async def interaction_check(self,i):return i.user.id==self.u.id
    def embed(self):
        e=discord.Embed(title="⚙️ Configuration",color=C.BLURPLE)
        e.description=f"**{self.g.name}**\n{self.g.member_count} membres"
        if self.g.icon:e.set_thumbnail(url=self.g.icon.url)
        return e
    @discord.ui.button(label="Protection",emoji="🛡️",style=discord.ButtonStyle.primary,row=0)
    async def prot(self,i,b):v=ProtPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)
    @discord.ui.button(label="Logs",emoji="📜",style=discord.ButtonStyle.secondary,row=0)
    async def logs(self,i,b):
        c=await cfg(self.g.id)
        e=discord.Embed(title="📜 Logs",color=C.PURPLE)
        lines=[f"{em} {nm}: {self.g.get_channel(c.get(f'log_{k}',0)).mention if c.get(f'log_{k}') and self.g.get_channel(c.get(f'log_{k}')) else '❌'}" for k,em,nm in PROTS]
        e.description="\n".join(lines)
        await i.response.edit_message(embed=e,view=BackView(self.u,self.g))
    @discord.ui.button(label="Immunités",emoji="👑",style=discord.ButtonStyle.secondary,row=0)
    async def immune(self,i,b):v=ImmunePanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)
    @discord.ui.button(label="Config Salon",emoji="📺",style=discord.ButtonStyle.primary,row=1)
    async def chan(self,i,b):v=ChanPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)
    @discord.ui.button(label="Tickets",emoji="🎫",style=discord.ButtonStyle.success,row=1)
    async def tickets(self,i,b):v=TicketMainPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)
    @discord.ui.button(label="Fermer",emoji="✖️",style=discord.ButtonStyle.danger,row=2)
    async def close(self,i,b):await i.message.delete()

class BackView(View):
    def __init__(self,u,g):super().__init__(timeout=300);self.u=u;self.g=g
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary)
    async def back(self,i,b):v=MainPanel(self.u,self.g);await i.response.edit_message(embed=v.embed(),view=v)

class ProtPanel(View):
    def __init__(self,u,g):super().__init__(timeout=600);self.u=u;self.g=g
    async def embed(self):
        c=await cfg(self.g.id)
        lines=[f"{em} {nm}: {'✅' if c.get(k) else '❌'}" for k,em,nm in PROTS]
        e=discord.Embed(title="🛡️ Protection",color=C.BLUE)
        e.description="```\n"+"\n".join(lines)+"\n```"
        return e
    @discord.ui.select(placeholder="Sélectionner...",options=[discord.SelectOption(label=nm,value=k,emoji=em) for k,em,nm in PROTS])
    async def sel(self,i,s):
        prot=next(p for p in PROTS if p[0]==s.values[0])
        v=ProtDetail(self.u,self.g,prot)
        await i.response.edit_message(embed=await v.embed(),view=v)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):v=MainPanel(self.u,self.g);await i.response.edit_message(embed=v.embed(),view=v)

class ProtDetail(View):
    def __init__(self,u,g,prot):
        super().__init__(timeout=600)
        self.u=u;self.g=g;self.prot=prot;self.key=prot[0]
    async def embed(self):
        c=await cfg(self.g.id);on=bool(c.get(self.key))
        e=discord.Embed(title=f"{self.prot[1]} {self.prot[2]}",color=C.GREEN if on else C.RED)
        e.add_field(name="État",value="✅ ACTIVÉ" if on else "❌ DÉSACTIVÉ",inline=False)
        if self.key=="anti_link":
            e.add_field(name="Whitelist",value=", ".join([f"`{d}`" for d in c.get('link_whitelist',[])[:8]]) or"*Aucun*",inline=False)
            chs=c.get('link_allowed_channels',[])
            e.add_field(name="Salons autorisés",value=", ".join([f"<#{x}>" for x in chs[:5]]) or"*Aucun*",inline=False)
        elif self.key=="anti_image":
            items=c.get('image_allowed',[])
            fmts=['png','jpg','jpeg','gif','webp','tenor','giphy']
            e.add_field(name="Formats autorisés",value=" ".join([f"{'✅' if f in items else '❌'}`{f}`" for f in fmts]),inline=False)
        elif self.key=="anti_badwords":
            e.add_field(name="Mots interdits",value=", ".join([f"`{w}`" for w in c.get('badwords_list',[])[:10]]) or"*Aucun*",inline=False)
        elif self.key=="anti_spam":
            e.add_field(name="Max messages",value=str(c.get('spam_max',5)),inline=True)
            e.add_field(name="Intervalle (sec)",value=str(c.get('spam_interval',5)),inline=True)
            e.add_field(name="Action",value=c.get('spam_action','mute'),inline=True)
        elif self.key=="anti_caps":
            e.add_field(name="% max",value=f"{c.get('caps_percent',70)}%",inline=True)
        elif self.key=="anti_newaccount":
            e.add_field(name="Jours min",value=str(c.get('newaccount_days',7)),inline=True)
        elif self.key in["anti_phishing","anti_scam"]:
            ak='phishing_action' if self.key=="anti_phishing" else 'scam_action'
            e.add_field(name="Action",value=c.get(ak,'ban' if'phishing'in ak else'mute'),inline=True)
        lch=self.g.get_channel(c.get(f'log_{self.key}',0))
        e.add_field(name="📜 Salon Log",value=lch.mention if lch else"❌",inline=False)
        return e
    @discord.ui.button(label="ON/OFF",emoji="🔄",style=discord.ButtonStyle.primary,row=0)
    async def toggle(self,i,b):
        c=await cfg(self.g.id);await db_set(self.g.id,self.key,0 if c.get(self.key) else 1)
        await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="⚙️ Config",style=discord.ButtonStyle.secondary,row=0)
    async def config(self,i,b):
        if self.key=="anti_image":v=ImageCfgPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)
        elif self.key=="anti_badwords":await i.response.send_modal(AddWordsModal(self.g,self.u))
        elif self.key=="anti_link":v=LinkCfgPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)
        elif self.key in["anti_spam","anti_caps","anti_newaccount"]:await i.response.send_modal(NumberConfigModal(self.g,self.u,self.key))
        elif self.key in["anti_phishing","anti_scam"]:v=ActionCfgPanel(self.u,self.g,self.key);await i.response.edit_message(embed=await v.embed(),view=v)
        else:await i.response.send_message("⚙️ Pas de config spéciale",ephemeral=True)
    @discord.ui.button(label="📜 Log",style=discord.ButtonStyle.secondary,row=0)
    async def set_log(self,i,b):
        chs=list(self.g.text_channels)[:25]
        opts=[discord.SelectOption(label=f"#{c.name}"[:25],value=str(c.id)) for c in chs]
        v=LogSelectView(self.u,self.g,opts,self.key,self.prot)
        await i.response.edit_message(view=v)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):v=ProtPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)

class LogSelectView(View):
    def __init__(self,u,g,opts,key,prot):
        super().__init__(timeout=120)
        self.add_item(LogSelect(u,g,opts,key,prot))

class LogSelect(Select):
    def __init__(self,u,g,opts,key,prot):
        super().__init__(placeholder="Salon log...",options=opts)
        self.u=u;self.g=g;self.key=key;self.prot=prot
    async def callback(self,i):
        await db_set(i.guild.id,f'log_{self.key}',int(self.values[0]))
        v=ProtDetail(self.u,self.g,self.prot)
        await i.response.edit_message(embed=await v.embed(),view=v)

class AddWordsModal(Modal,title="➕ Mots interdits"):
    words=TextInput(label="Mots (séparés par virgules)",placeholder="mot1, mot2",style=discord.TextStyle.paragraph)
    def __init__(self,g,u):super().__init__();self.g=g;self.u=u
    async def on_submit(self,i):
        c=await cfg(self.g.id);items=c.get('badwords_list',[])
        new=[x.strip().lower() for x in self.words.value.split(',') if x.strip()]
        items.extend([x for x in new if x not in items])
        await db_set(self.g.id,'badwords_list',items)
        prot=next(p for p in PROTS if p[0]=="anti_badwords")
        v=ProtDetail(self.u,self.g,prot)
        await i.response.edit_message(embed=await v.embed(),view=v)

class NumberConfigModal(Modal,title="⚙️ Configuration"):
    val=TextInput(label="Valeur",placeholder="5")
    def __init__(self,g,u,key):
        super().__init__()
        self.g=g;self.u=u;self.key=key
        if key=="anti_spam":self.val.label="Max messages"
        elif key=="anti_caps":self.val.label="% majuscules max"
        elif key=="anti_newaccount":self.val.label="Jours minimum"
    async def on_submit(self,i):
        v=int(self.val.value) if self.val.value.isdigit() else 5
        if self.key=="anti_spam":await db_set(self.g.id,'spam_max',v)
        elif self.key=="anti_caps":await db_set(self.g.id,'caps_percent',v)
        elif self.key=="anti_newaccount":await db_set(self.g.id,'newaccount_days',v)
        prot=next(p for p in PROTS if p[0]==self.key)
        vw=ProtDetail(self.u,self.g,prot)
        await i.response.edit_message(embed=await vw.embed(),view=vw)

class ImageCfgPanel(View):
    def __init__(self,u,g):super().__init__(timeout=600);self.u=u;self.g=g
    async def embed(self):
        c=await cfg(self.g.id);items=c.get('image_allowed',[])
        fmts=['png','jpg','jpeg','gif','webp','tenor','giphy']
        e=discord.Embed(title="🖼️ Formats autorisés",color=C.BLUE)
        e.description=" ".join([f"{'✅' if f in items else '❌'} `{f}`" for f in fmts])
        return e
    @discord.ui.button(label="➕ Format",style=discord.ButtonStyle.success,row=0)
    async def add(self,i,b):
        c=await cfg(self.g.id);items=c.get('image_allowed',[])
        fmts=['png','jpg','jpeg','gif','webp','tenor','giphy']
        avail=[f for f in fmts if f not in items]
        if not avail:return await i.response.send_message("✅ Tous autorisés",ephemeral=True)
        opts=[discord.SelectOption(label=f.upper(),value=f) for f in avail]
        v=FormatSelectView(self.u,self.g,opts,'add')
        await i.response.edit_message(view=v)
    @discord.ui.button(label="➖ Format",style=discord.ButtonStyle.danger,row=0)
    async def rem(self,i,b):
        c=await cfg(self.g.id);items=c.get('image_allowed',[])
        if not items:return await i.response.send_message("❌ Vide",ephemeral=True)
        opts=[discord.SelectOption(label=f.upper(),value=f) for f in items]
        v=FormatSelectView(self.u,self.g,opts,'rem')
        await i.response.edit_message(view=v)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):
        prot=next(p for p in PROTS if p[0]=="anti_image")
        v=ProtDetail(self.u,self.g,prot)
        await i.response.edit_message(embed=await v.embed(),view=v)

class FormatSelectView(View):
    def __init__(self,u,g,opts,action):
        super().__init__(timeout=120)
        self.add_item(FormatSelect(u,g,opts,action))

class FormatSelect(Select):
    def __init__(self,u,g,opts,action):
        super().__init__(placeholder="Format...",options=opts)
        self.u=u;self.g=g;self.action=action
    async def callback(self,i):
        c=await cfg(i.guild.id);items=c.get('image_allowed',[]);f=self.values[0]
        if self.action=='add' and f not in items:items.append(f)
        elif self.action=='rem' and f in items:items.remove(f)
        await db_set(i.guild.id,'image_allowed',items)
        v=ImageCfgPanel(self.u,self.g)
        await i.response.edit_message(embed=await v.embed(),view=v)

class LinkCfgPanel(View):
    def __init__(self,u,g):super().__init__(timeout=600);self.u=u;self.g=g
    async def embed(self):
        c=await cfg(self.g.id)
        e=discord.Embed(title="🔗 Config Anti-Liens",color=C.BLUE)
        e.add_field(name="Whitelist",value=", ".join([f"`{d}`" for d in c.get('link_whitelist',[])[:10]]) or"*Aucun*",inline=False)
        chs=c.get('link_allowed_channels',[])
        e.add_field(name="Salons autorisés",value=", ".join([f"<#{x}>" for x in chs[:8]]) or"*Aucun*",inline=False)
        return e
    @discord.ui.button(label="➕ Domaine",style=discord.ButtonStyle.success,row=0)
    async def add_domain(self,i,b):await i.response.send_modal(AddDomainModal(self.g,self.u))
    @discord.ui.button(label="🗑️ Clear Whitelist",style=discord.ButtonStyle.danger,row=0)
    async def clear(self,i,b):
        await db_set(self.g.id,'link_whitelist',[])
        await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="➕ Salon",style=discord.ButtonStyle.primary,row=1)
    async def add_chan(self,i,b):
        chs=list(self.g.text_channels)[:25]
        opts=[discord.SelectOption(label=f"#{c.name}"[:25],value=str(c.id)) for c in chs]
        v=LinkChanSelectView(self.u,self.g,opts)
        await i.response.edit_message(view=v)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b):
        prot=next(p for p in PROTS if p[0]=="anti_link")
        v=ProtDetail(self.u,self.g,prot)
        await i.response.edit_message(embed=await v.embed(),view=v)

class AddDomainModal(Modal,title="➕ Domaines whitelist"):
    doms=TextInput(label="Domaines (séparés par virgules)",placeholder="youtube.com, twitter.com",style=discord.TextStyle.paragraph)
    def __init__(self,g,u):super().__init__();self.g=g;self.u=u
    async def on_submit(self,i):
        c=await cfg(self.g.id);items=c.get('link_whitelist',[])
        new=[x.strip().lower() for x in self.doms.value.split(',') if x.strip()]
        items.extend([x for x in new if x not in items])
        await db_set(self.g.id,'link_whitelist',items)
        v=LinkCfgPanel(self.u,self.g)
        await i.response.edit_message(embed=await v.embed(),view=v)

class LinkChanSelectView(View):
    def __init__(self,u,g,opts):
        super().__init__(timeout=120)
        self.add_item(LinkChanSelect(u,g,opts))

class LinkChanSelect(Select):
    def __init__(self,u,g,opts):
        super().__init__(placeholder="Salon...",options=opts)
        self.u=u;self.g=g
    async def callback(self,i):
        c=await cfg(i.guild.id);chs=c.get('link_allowed_channels',[])
        chid=int(self.values[0])
        if chid not in chs:chs.append(chid)
        await db_set(i.guild.id,'link_allowed_channels',chs)
        v=LinkCfgPanel(self.u,self.g)
        await i.response.edit_message(embed=await v.embed(),view=v)

class ActionCfgPanel(View):
    def __init__(self,u,g,key):super().__init__(timeout=600);self.u=u;self.g=g;self.key=key
    async def embed(self):
        c=await cfg(self.g.id)
        ak='phishing_action' if self.key=="anti_phishing" else 'scam_action'
        e=discord.Embed(title=f"⚙️ Action {self.key}",color=C.BLUE)
        e.add_field(name="Action actuelle",value=c.get(ak,'ban' if'phishing'in ak else'mute'),inline=False)
        return e
    @discord.ui.button(label="Mute",style=discord.ButtonStyle.primary,row=0)
    async def mute(self,i,b):await self.set_action(i,'mute')
    @discord.ui.button(label="Kick",style=discord.ButtonStyle.secondary,row=0)
    async def kick(self,i,b):await self.set_action(i,'kick')
    @discord.ui.button(label="Ban",style=discord.ButtonStyle.danger,row=0)
    async def ban(self,i,b):await self.set_action(i,'ban')
    async def set_action(self,i,act):
        ak='phishing_action' if self.key=="anti_phishing" else 'scam_action'
        await db_set(self.g.id,ak,act)
        await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):
        prot=next(p for p in PROTS if p[0]==self.key)
        v=ProtDetail(self.u,self.g,prot)
        await i.response.edit_message(embed=await v.embed(),view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           👑 IMMUNITÉS
# ═══════════════════════════════════════════════════════════════════════════════

class ImmunePanel(View):
    def __init__(self,u,g):super().__init__(timeout=600);self.u=u;self.g=g
    async def embed(self):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM immune_roles WHERE guild_id=?',(self.g.id,)) as c:
                rids=[r[0] for r in await c.fetchall()]
            async with db.execute('SELECT user_id FROM immune_users WHERE guild_id=?',(self.g.id,)) as c:
                uids=[r[0] for r in await c.fetchall()]
        e=discord.Embed(title="👑 Immunités",color=C.YELLOW)
        e.add_field(name="Rôles",value=", ".join([f"<@&{r}>" for r in rids]) or"*Aucun*",inline=False)
        e.add_field(name="Utilisateurs",value=", ".join([f"<@{u}>" for u in uids]) or"*Aucun*",inline=False)
        return e
    @discord.ui.button(label="➕ Rôle",style=discord.ButtonStyle.success,row=0)
    async def add_role(self,i,b):
        roles=[r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts=[discord.SelectOption(label=f"@{r.name}"[:25],value=str(r.id)) for r in roles]
        await i.response.edit_message(view=ImmuneRoleView(self.u,self.g,opts))
    @discord.ui.button(label="➕ User",style=discord.ButtonStyle.primary,row=0)
    async def add_user(self,i,b):await i.response.send_modal(AddImmuneUserModal(self.g,self.u))
    @discord.ui.button(label="🗑️ Clear",style=discord.ButtonStyle.danger,row=0)
    async def clear(self,i,b):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM immune_roles WHERE guild_id=?',(self.g.id,))
            await db.execute('DELETE FROM immune_users WHERE guild_id=?',(self.g.id,))
            await db.commit()
        await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):v=MainPanel(self.u,self.g);await i.response.edit_message(embed=v.embed(),view=v)

class ImmuneRoleView(View):
    def __init__(self,u,g,opts):
        super().__init__(timeout=120)
        self.add_item(ImmuneRoleSelect(u,g,opts))

class ImmuneRoleSelect(Select):
    def __init__(self,u,g,opts):
        super().__init__(placeholder="Rôle...",options=opts)
        self.u=u;self.g=g
    async def callback(self,i):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR IGNORE INTO immune_roles VALUES(?,?)',(i.guild.id,int(self.values[0])))
            await db.commit()
        v=ImmunePanel(self.u,self.g)
        await i.response.edit_message(embed=await v.embed(),view=v)

class AddImmuneUserModal(Modal,title="➕ User immunisé"):
    uid=TextInput(label="ID utilisateur",placeholder="123456789")
    def __init__(self,g,u):super().__init__();self.g=g;self.u=u
    async def on_submit(self,i):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('INSERT OR IGNORE INTO immune_users VALUES(?,?)',(self.g.id,int(self.uid.value)))
                await db.commit()
        except:pass
        v=ImmunePanel(self.u,self.g)
        await i.response.edit_message(embed=await v.embed(),view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                           📺 CONFIG SALON
# ═══════════════════════════════════════════════════════════════════════════════

class ChanPanel(View):
    def __init__(self,u,g):super().__init__(timeout=600);self.u=u;self.g=g
    async def embed(self):
        c=await cfg(self.g.id);configs=c.get('channel_configs',{})
        e=discord.Embed(title="📺 Config Salon",color=C.ORANGE)
        if configs:
            lines=[]
            for ch_id,conf in list(configs.items())[:10]:
                ch=self.g.get_channel(int(ch_id))
                if ch:
                    icons=""
                    if not conf.get('messages',True):icons+="💬❌"
                    if not conf.get('images',True):icons+="🖼️❌"
                    if not conf.get('gifs',True):icons+="🎞️❌"
                    if not conf.get('links',True):icons+="🔗❌"
                    lines.append(f"{ch.mention}: {icons or'✅ tout'}")
            e.description="\n".join(lines) or"*Aucun*"
        else:e.description="*Aucun*"
        return e
    @discord.ui.button(label="➕ Config",style=discord.ButtonStyle.success,row=0)
    async def add(self,i,b):
        chs=list(self.g.text_channels)[:25]
        opts=[discord.SelectOption(label=f"#{c.name}"[:25],value=str(c.id)) for c in chs]
        await i.response.edit_message(view=ChanSelectView(self.u,self.g,opts))
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):v=MainPanel(self.u,self.g);await i.response.edit_message(embed=v.embed(),view=v)

class ChanSelectView(View):
    def __init__(self,u,g,opts):
        super().__init__(timeout=120)
        self.add_item(ChanSelect(u,g,opts))

class ChanSelect(Select):
    def __init__(self,u,g,opts):
        super().__init__(placeholder="Salon...",options=opts)
        self.u=u;self.g=g
    async def callback(self,i):
        v=EditChanCfg(self.u,self.g,self.values[0])
        await i.response.edit_message(embed=await v.embed(),view=v)

class EditChanCfg(View):
    def __init__(self,u,g,ch_id):super().__init__(timeout=600);self.u=u;self.g=g;self.ch_id=ch_id
    async def get_conf(self):
        c=await cfg(self.g.id)
        return c.get('channel_configs',{}).get(str(self.ch_id),{'messages':True,'images':True,'gifs':True,'emojis':True,'links':True})
    async def save(self,conf):
        c=await cfg(self.g.id);configs=c.get('channel_configs',{});configs[str(self.ch_id)]=conf
        await db_set(self.g.id,'channel_configs',configs)
    async def embed(self):
        ch=self.g.get_channel(int(self.ch_id));conf=await self.get_conf()
        s=lambda k:"✅" if conf.get(k,True) else "❌"
        e=discord.Embed(title=f"📺 #{ch.name if ch else '?'}",color=C.ORANGE)
        e.description=f"💬 Messages: {s('messages')}\n🖼️ Images: {s('images')}\n🎞️ GIFs: {s('gifs')}\n😀 Emojis: {s('emojis')}\n🔗 Liens: {s('links')}"
        return e
    async def toggle(self,i,key):
        conf=await self.get_conf();conf[key]=not conf.get(key,True);await self.save(conf)
        await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="💬",style=discord.ButtonStyle.primary,row=0)
    async def t1(self,i,b):await self.toggle(i,'messages')
    @discord.ui.button(label="🖼️",style=discord.ButtonStyle.primary,row=0)
    async def t2(self,i,b):await self.toggle(i,'images')
    @discord.ui.button(label="🎞️",style=discord.ButtonStyle.primary,row=0)
    async def t3(self,i,b):await self.toggle(i,'gifs')
    @discord.ui.button(label="😀",style=discord.ButtonStyle.primary,row=1)
    async def t4(self,i,b):await self.toggle(i,'emojis')
    @discord.ui.button(label="🔗",style=discord.ButtonStyle.primary,row=1)
    async def t5(self,i,b):await self.toggle(i,'links')
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b):v=ChanPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)

# ═══════════════════════════════════════════════════════════════════════════════
#                    🎫 TICKET CONFIG PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class TicketMainPanel(View):
    def __init__(self,u,g):super().__init__(timeout=600);self.u=u;self.g=g
    async def embed(self):
        c=await cfg(self.g.id)
        e=discord.Embed(title="🎫 Tickets",color=C.PURPLE)
        staff=self.g.get_role(c.get('ticket_staff',0));lch=self.g.get_channel(c.get('ticket_log',0))
        e.add_field(name="👮 Staff",value=staff.mention if staff else"❌",inline=True)
        e.add_field(name="📜 Logs",value=lch.mention if lch else"❌",inline=True)
        panels=c.get('ticket_panels',{})
        if panels:
            pl=[]
            for pid,pd in list(panels.items())[:10]:
                cat=self.g.get_channel(pd.get('category',0))
                pl.append(f"• **{pd.get('name',pid)[:15]}** → `{cat.name if cat else'❌'}` ({len(pd.get('questions',[]))}Q, max{pd.get('max',1)})")
            e.add_field(name=f"📋 Panels ({len(panels)})",value="\n".join(pl),inline=False)
        else:e.add_field(name="📋 Panels",value="*Aucun*",inline=False)
        return e
    @discord.ui.button(label="👮 Staff",style=discord.ButtonStyle.primary,row=0)
    async def staff(self,i,b):
        roles=[r for r in self.g.roles[1:] if not r.is_bot_managed()][:25]
        opts=[discord.SelectOption(label=f"@{r.name}"[:25],value=str(r.id)) for r in roles]
        await i.response.edit_message(embed=discord.Embed(title="👮 Staff",color=C.PURPLE),view=TkStaffView(self.u,self.g,opts))
    @discord.ui.button(label="📜 Logs",style=discord.ButtonStyle.primary,row=0)
    async def logs(self,i,b):
        chs=list(self.g.text_channels)[:25]
        opts=[discord.SelectOption(label=f"#{c.name}"[:25],value=str(c.id)) for c in chs]
        await i.response.edit_message(embed=discord.Embed(title="📜 Logs",color=C.PURPLE),view=TkLogView(self.u,self.g,opts))
    @discord.ui.button(label="➕ Panel",style=discord.ButtonStyle.success,row=1)
    async def new(self,i,b):await i.response.send_modal(NewPanelModal(self.u,self.g))
    @discord.ui.button(label="📝 Modifier",style=discord.ButtonStyle.secondary,row=1)
    async def edit(self,i,b):
        c=await cfg(self.g.id);panels=c.get('ticket_panels',{})
        if not panels:return await i.response.send_message("❌",ephemeral=True)
        opts=[discord.SelectOption(label=pd.get('name',pid)[:25],value=pid) for pid,pd in list(panels.items())[:25]]
        await i.response.edit_message(embed=discord.Embed(title="📝 Panel",color=C.PURPLE),view=EditPanelView(self.u,self.g,opts))
    @discord.ui.button(label="🔄",style=discord.ButtonStyle.secondary,row=2)
    async def ref(self,i,b):await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="◀️ Retour",style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b):v=MainPanel(self.u,self.g);await i.response.edit_message(embed=v.embed(),view=v)

class TkStaffView(View):
    def __init__(self,u,g,opts):super().__init__(timeout=120);self.add_item(TkStaffSel(u,g,opts))
class TkStaffSel(Select):
    def __init__(self,u,g,opts):super().__init__(placeholder="Rôle...",options=opts);self.u=u;self.g=g
    async def callback(self,i):
        await db_set(i.guild.id,'ticket_staff',int(self.values[0]))
        v=TicketMainPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)

class TkLogView(View):
    def __init__(self,u,g,opts):super().__init__(timeout=120);self.add_item(TkLogSel(u,g,opts))
class TkLogSel(Select):
    def __init__(self,u,g,opts):super().__init__(placeholder="Salon...",options=opts);self.u=u;self.g=g
    async def callback(self,i):
        await db_set(i.guild.id,'ticket_log',int(self.values[0]))
        v=TicketMainPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)

class NewPanelModal(Modal,title="➕ Nouveau Panel"):
    name=TextInput(label="Nom",placeholder="Support",max_length=30)
    mx=TextInput(label="Max tickets",placeholder="1",default="1",max_length=2)
    def __init__(self,u,g):super().__init__();self.u=u;self.g=g
    async def on_submit(self,i):
        pid=str(int(time.time()));mxt=max(1,min(10,int(self.mx.value) if self.mx.value.isdigit() else 1))
        c=await cfg(self.g.id);panels=c.get('ticket_panels',{})
        panels[pid]={'name':self.name.value,'category':0,'questions':[],'max':mxt}
        await db_set(self.g.id,'ticket_panels',panels)
        v=PanelEditView(self.u,self.g,pid);await i.response.edit_message(embed=await v.embed(),view=v)

class EditPanelView(View):
    def __init__(self,u,g,opts):super().__init__(timeout=120);self.add_item(EditPanelSel(u,g,opts))
class EditPanelSel(Select):
    def __init__(self,u,g,opts):super().__init__(placeholder="Panel...",options=opts);self.u=u;self.g=g
    async def callback(self,i):v=PanelEditView(self.u,self.g,self.values[0]);await i.response.edit_message(embed=await v.embed(),view=v)

class PanelEditView(View):
    def __init__(self,u,g,pid):super().__init__(timeout=600);self.u=u;self.g=g;self.pid=pid
    async def get_panel(self):c=await cfg(self.g.id);return c.get('ticket_panels',{}).get(self.pid,{})
    async def embed(self):
        pnl=await self.get_panel()
        e=discord.Embed(title=f"🎫 {pnl.get('name','?')}",color=C.PURPLE)
        cat=self.g.get_channel(pnl.get('category',0))
        e.add_field(name="📁 Catégorie",value=cat.name if cat else"❌",inline=True)
        e.add_field(name="🔢 Max",value=str(pnl.get('max',1)),inline=True)
        qs=pnl.get('questions',[])
        if qs:e.add_field(name=f"📝 Questions ({len(qs)})",value="\n".join([f"• {q['title']}" for q in qs[:5]]),inline=False)
        else:e.add_field(name="📝 Questions",value="*Aucune*",inline=False)
        return e
    @discord.ui.button(label="📁 Catégorie",style=discord.ButtonStyle.primary,row=0)
    async def cat(self,i,b):
        cats=list(self.g.categories)[:25]
        if not cats:return await i.response.send_message("❌",ephemeral=True)
        opts=[discord.SelectOption(label=f"📁 {c.name}"[:25],value=str(c.id)) for c in cats]
        await i.response.edit_message(view=PanelCatView(self.u,self.g,self.pid,opts))
    @discord.ui.button(label="📝 Questions",style=discord.ButtonStyle.primary,row=0)
    async def qs(self,i,b):v=PanelQsView(self.u,self.g,self.pid);await i.response.edit_message(embed=await v.embed(),view=v)
    @discord.ui.button(label="🔢 Max",style=discord.ButtonStyle.secondary,row=0)
    async def mx(self,i,b):await i.response.send_modal(SetMaxModal(self.u,self.g,self.pid))
    @discord.ui.button(label="📤 Envoyer",style=discord.ButtonStyle.success,row=1)
    async def send(self,i,b):
        pnl=await self.get_panel();c=await cfg(self.g.id)
        if not pnl.get('category'):return await i.response.send_message("❌ Catégorie!",ephemeral=True)
        if not c.get('ticket_staff'):return await i.response.send_message("❌ Staff!",ephemeral=True)
        chs=list(self.g.text_channels)[:25]
        opts=[discord.SelectOption(label=f"#{ch.name}"[:25],value=str(ch.id)) for ch in chs]
        await i.response.edit_message(embed=discord.Embed(title="📤 Où?",color=C.PURPLE),view=SendPanelView(self.u,self.g,self.pid,opts))
    @discord.ui.button(label="🗑️ Suppr",style=discord.ButtonStyle.danger,row=1)
    async def delete(self,i,b):
        c=await cfg(self.g.id);panels=c.get('ticket_panels',{})
        if self.pid in panels:del panels[self.pid]
        await db_set(self.g.id,'ticket_panels',panels)
        v=TicketMainPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)
    @discord.ui.button(label="◀️",style=discord.ButtonStyle.secondary,row=2)
    async def back(self,i,b):v=TicketMainPanel(self.u,self.g);await i.response.edit_message(embed=await v.embed(),view=v)

class PanelCatView(View):
    def __init__(self,u,g,pid,opts):super().__init__(timeout=120);self.add_item(PanelCatSel(u,g,pid,opts))
class PanelCatSel(Select):
    def __init__(self,u,g,pid,opts):super().__init__(placeholder="Catégorie...",options=opts);self.u=u;self.g=g;self.pid=pid
    async def callback(self,i):
        c=await cfg(i.guild.id);panels=c.get('ticket_panels',{})
        if self.pid in panels:panels[self.pid]['category']=int(self.values[0]);await db_set(i.guild.id,'ticket_panels',panels)
        v=PanelEditView(self.u,self.g,self.pid);await i.response.edit_message(embed=await v.embed(),view=v)

class SetMaxModal(Modal,title="🔢 Max"):
    mx=TextInput(label="Max",placeholder="1-10",default="1",max_length=2)
    def __init__(self,u,g,pid):super().__init__();self.u=u;self.g=g;self.pid=pid
    async def on_submit(self,i):
        v=max(1,min(10,int(self.mx.value) if self.mx.value.isdigit() else 1))
        c=await cfg(self.g.id);panels=c.get('ticket_panels',{})
        if self.pid in panels:panels[self.pid]['max']=v;await db_set(self.g.id,'ticket_panels',panels)
        vw=PanelEditView(self.u,self.g,self.pid);await i.response.edit_message(embed=await vw.embed(),view=vw)

class PanelQsView(View):
    def __init__(self,u,g,pid):super().__init__(timeout=600);self.u=u;self.g=g;self.pid=pid
    async def embed(self):
        c=await cfg(self.g.id);pnl=c.get('ticket_panels',{}).get(self.pid,{});qs=pnl.get('questions',[])
        e=discord.Embed(title="📝 Questions",color=C.PURPLE)
        if qs:
            for j,q in enumerate(qs,1):e.add_field(name=f"{j}. {q['title']}",value=q['question'][:100],inline=False)
        else:e.description="*Aucune*"
        e.set_footer(text="Max 5")
        return e
    @discord.ui.button(label="➕",style=discord.ButtonStyle.success,row=0)
    async def add(self,i,b):
        c=await cfg(self.g.id);pnl=c.get('ticket_panels',{}).get(self.pid,{})
        if len(pnl.get('questions',[]))>=5:return await i.response.send_message("❌ Max 5",ephemeral=True)
        await i.response.send_modal(AddQModal(self.u,self.g,self.pid))
    @discord.ui.button(label="🗑️",style=discord.ButtonStyle.danger,row=0)
    async def clear(self,i,b):
        c=await cfg(self.g.id);panels=c.get('ticket_panels',{})
        if self.pid in panels:panels[self.pid]['questions']=[];await db_set(self.g.id,'ticket_panels',panels)
        await i.response.edit_message(embed=await self.embed(),view=self)
    @discord.ui.button(label="◀️",style=discord.ButtonStyle.secondary,row=1)
    async def back(self,i,b):v=PanelEditView(self.u,self.g,self.pid);await i.response.edit_message(embed=await v.embed(),view=v)

class AddQModal(Modal,title="➕ Question"):
    t=TextInput(label="Titre",placeholder="Pseudo",max_length=45)
    q=TextInput(label="Question",placeholder="Quel est votre pseudo?",style=discord.TextStyle.paragraph,max_length=100)
    def __init__(self,u,g,pid):super().__init__();self.u=u;self.g=g;self.pid=pid
    async def on_submit(self,i):
        c=await cfg(self.g.id);panels=c.get('ticket_panels',{})
        if self.pid in panels:panels[self.pid].setdefault('questions',[]).append({'title':self.t.value,'question':self.q.value});await db_set(self.g.id,'ticket_panels',panels)
        v=PanelQsView(self.u,self.g,self.pid);await i.response.edit_message(embed=await v.embed(),view=v)

class SendPanelView(View):
    def __init__(self,u,g,pid,opts):super().__init__(timeout=120);self.add_item(SendPanelSel(u,g,pid,opts))
class SendPanelSel(Select):
    def __init__(self,u,g,pid,opts):super().__init__(placeholder="Salon...",options=opts);self.u=u;self.g=g;self.pid=pid
    async def callback(self,i):
        ch=i.guild.get_channel(int(self.values[0]))
        if not ch:return await i.response.send_message("❌",ephemeral=True)
        c=await cfg(i.guild.id);pnl=c.get('ticket_panels',{}).get(self.pid,{})
        qs=pnl.get('questions',[]);mx=pnl.get('max',1)
        desc="Cliquez pour créer un ticket."
        if qs:desc+=f"\n\n📝 {len(qs)} question(s)"
        desc+=f"\n🔢 Max {mx} ticket(s)"
        emb=discord.Embed(title=f"🎫 {pnl.get('name','Support')}",description=desc,color=C.BLURPLE)
        await ch.send(embed=emb,view=TicketCreateView(self.pid))
        await i.response.send_message(f"✅ → {ch.mention}",ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
#                              🎯 EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    await db_init()
    bot.add_view(TicketControlView())
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM guild_config') as c:
                for row in await c.fetchall():
                    try:
                        data=json.loads(row[0]) if row[0] else {}
                        for pid in data.get('ticket_panels',{}):bot.add_view(TicketCreateView(pid))
                    except:pass
    except:pass
    await bot.tree.sync()
    print(f"✅ {bot.user.name} v11.5 prêt!")

@bot.event
async def on_member_remove(m):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id,channel_id,claimed_by,answers FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",(m.guild.id,m.id)) as c:
                tks=await c.fetchall()
        for tk in tks:
            ans={};
            try:ans=json.loads(tk[3]) if tk[3] else {}
            except:pass
            ti={'id':tk[0],'user':m.id,'claimed':tk[2] or 0,'answers':ans}
            ch=m.guild.get_channel(tk[1])
            await send_ticket_log(m.guild,'leave',m,ti)
            if ch:await ch.send(embed=discord.Embed(title="🚪 Parti",description=f"**{m.display_name}** a quitté",color=C.ORANGE))
    except:pass

@bot.event
async def on_member_join(m):
    try:
        c=await cfg(m.guild.id)
        if c.get('anti_newaccount'):
            days=c.get('newaccount_days',7);age=(now()-m.created_at.replace(tzinfo=timezone.utc)).days
            if age<days:
                await send_log(m.guild,'anti_newaccount',m,None,"Compte récent",f"{age}j")
                await m.kick(reason=f"Compte récent ({age}j)")
    except:pass

@bot.event
async def on_message(msg):
    if msg.author.bot or not msg.guild:return
    try:
        c=await cfg(msg.guild.id);ct=msg.content or"";chid=msg.channel.id
        gt=get_gif_type(msg);ag=c.get('image_allowed',[]);iag=gt and gt in ag
        chcf=c.get('channel_configs',{}).get(str(chid))
        if chcf and not(iag and chcf.get('gifs',True)):
            vio,_=check_channel_cfg(msg,chcf)
            if vio:await msg.delete();return
        if c.get('anti_phishing'):
            f,d=check_phishing(ct)
            if f:await msg.delete();await send_log(msg.guild,'anti_phishing',msg.author,msg,"Phishing",f"`{d}`");await sanction(msg.author,c.get('phishing_action','ban'),60,"Phishing",msg.guild);return
        if c.get('anti_scam') and not await is_immune(msg.author,'anti_scam'):
            f,p=check_scam(ct)
            if f:await msg.delete();await send_log(msg.guild,'anti_scam',msg.author,msg,"Scam",f"`{p}`");await sanction(msg.author,c.get('scam_action','mute'),60,"Scam",msg.guild);return
        if c.get('anti_badwords') and not await is_immune(msg.author,'anti_badwords'):
            f,w=check_badwords(ct,c.get('badwords_list',[]))
            if f:await msg.delete();await send_log(msg.guild,'anti_badwords',msg.author,msg,"Mot interdit",f"`{w}`");return
        if c.get('anti_invite'):
            f,inv=check_invite(ct)
            if f:await msg.delete();await send_log(msg.guild,'anti_invite',msg.author,msg,"Invitation",f"`{inv}`");return
        if c.get('anti_link') and not iag:
            if chid not in c.get('link_allowed_channels',[]):
                f,url=check_link(ct,c.get('link_whitelist',[]))
                if f:await msg.delete();await send_log(msg.guild,'anti_link',msg.author,msg,"Lien",f"`{url}`");return
        if c.get('anti_image') and not await is_immune(msg.author,'anti_image') and not iag:
            if chid not in c.get('image_allowed_channels',[]):
                bl=check_image(msg,c.get('image_allowed',[]))
                if bl:await msg.delete();await send_log(msg.guild,'anti_image',msg.author,msg,"Format",f"`{', '.join(bl)}`");return
        if c.get('anti_spam') and not await is_immune(msg.author,'anti_spam'):
            if await check_spam(msg,c.get('spam_max',5),c.get('spam_interval',5)):
                await msg.delete();await send_log(msg.guild,'anti_spam',msg.author,msg,"Spam",None);await sanction(msg.author,c.get('spam_action','mute'),10,"Spam",msg.guild);return
        if c.get('anti_caps') and not await is_immune(msg.author,'anti_caps'):
            if check_caps(ct,c.get('caps_percent',70)):
                await msg.delete();await send_log(msg.guild,'anti_caps',msg.author,msg,"Caps",None);return
    except:pass

@bot.tree.command(name="configure",description="⚙️ Configuration")
async def configure_cmd(i:discord.Interaction):
    if not i.user.guild_permissions.administrator:return await i.response.send_message("❌",ephemeral=True)
    v=MainPanel(i.user,i.guild);await i.response.send_message(embed=v.embed(),view=v,ephemeral=True)

@bot.tree.command(name="warn",description="⚠️ Avertir")
@app_commands.describe(membre="Membre",raison="Raison")
async def warn_cmd(i:discord.Interaction,membre:discord.Member,raison:str):
    if not i.user.guild_permissions.moderate_members:return await i.response.send_message("❌",ephemeral=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO infractions(guild_id,user_id,mod_id,type,reason)VALUES(?,?,?,?,?)',(i.guild.id,membre.id,i.user.id,'warn',raison))
        await db.commit()
    await i.response.send_message(f"⚠️ {membre.mention}: {raison}")

if __name__=="__main__":
    print("🚀 v11.5")
    bot.run(TOKEN)
