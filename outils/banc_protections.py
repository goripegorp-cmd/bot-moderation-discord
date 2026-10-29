"""outils/banc_protections.py — audit de bout en bout des protections (29/10/2026).

De vrais messages passent dans le VRAI on_message (membre ordinaire, compte de 400 jours, aucune base) ; on
relève ce que fait le bot : suppression, sanction, alerte. Usage : python outils/banc_protections.py outils/banc_protections_cas.txt
(lignes « a || b » = plusieurs messages du même membre). Lent : quelques secondes par message (attentes du bot)."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import os, sys, asyncio, datetime as dt
os.environ["FAUX_JETON"] = "1"
import discord
import bot as B
import tempfile
B.DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "banc.db")   # jamais la base du PC

JOURNAL = []
def note(*a):
    JOURNAL.append(" ".join(str(x) for x in a)[:160])

async def rien(*a, **k):
    return None
async def faux(*a, **k):
    return False

CONF = {"anti_invite": 1}
async def lire_config(gid):
    return dict(CONF), True
B._lire_config = lire_config
B._config_cache.clear() if hasattr(B._config_cache, "clear") else None
for nom in ("is_fully_immune", "is_channel_immune", "is_ticket_channel", "update_realsy_activity", "_questions_hook",
            "_check_auto_slow_mode"):
    setattr(B, nom, faux)
async def sanction(m, action, dur, reason, g, actor_id=None):
    note("SANCTION", action, dur, reason)
B.sanction = sanction
async def immunites(gid):
    return {"channels": set(), "users": set(), "roles": set()}
B._get_immunity = immunites
async def marquer(*a, **k): return None
B.activite_module.marquer_actif = marquer
try:
    B.recidivism_module.tier_of = lambda *a: 0
except Exception: pass
async def log_event(bot, g, ev, **k):
    note("ALERTE", getattr(ev, "name", ev), (k.get("description") or "")[:60].replace("\n", " "))
B.ulogger2026.log_event = log_event

MAINTENANT = dt.datetime.now(dt.timezone.utc)
class Perms(discord.Permissions):
    pass
class Salon:
    def __init__(s):
        s.id, s.name, s.type, s.category, s.category_id, s.guild = 555, "chat", discord.ChannelType.text, None, None, None
        s.mention, s.nsfw, s.slowmode_delay = "#chat", False, 0
    async def send(s, *a, **k): note("ENVOI salon", (a[0] if a else k.get("content") or k.get("embed") and k["embed"].title or "")[:60] if (a or k) else "")
    def permissions_for(s, x): return discord.Permissions.all() if x is GUILDE.me else discord.Permissions.text()
    async def edit(s, **k): note("SALON edit", k)
    def history(s, **k):
        async def g():
            if False: yield None
        return g()
    async def purge(s, **k): note("PURGE"); return []
    async def webhooks(s): return []
class Membre:
    def __init__(s, i, bot=False):
        s.id, s.bot, s.name, s.display_name, s.global_name = i, bot, f"membre{i}", f"membre{i}", None
        s.mention, s.roles, s.guild_permissions = f"<@{i}>", [], discord.Permissions.none()
        s.joined_at, s.created_at = MAINTENANT - dt.timedelta(days=200), MAINTENANT - dt.timedelta(days=400)
        s.avatar, s.display_avatar, s.premium_since, s.pending, s.top_role, s.status = None, None, None, False, None, None
        s.public_flags, s.flags, s.communication_disabled_until, s.voice = None, None, None, None
        s.timed_out_until = None
        s.guild = globals().get("GUILDE")
    def is_timed_out(s): return False
    async def timeout(s, *a, **k): note("TIMEOUT", a[0] if a else "", k.get("reason", ""))
    async def kick(s, **k): note("KICK", k.get("reason", ""))
    async def ban(s, **k): note("BAN", k.get("reason", ""))
    async def send(s, *a, **k): note("DM")
    async def add_roles(s, *r, **k): note("ROLE+", [getattr(x, "name", x) for x in r])
    async def remove_roles(s, *r, **k): note("ROLE-")
    async def edit(s, **k): note("MEMBRE edit", list(k))
class Guilde:
    def __init__(s):
        s.id, s.owner_id, s.name, s.member_count = 999, 1, "test", 500
        s.me = Membre(2, bot=True); s.me.guild_permissions = discord.Permissions.all()
        s.roles, s.channels, s.text_channels, s.voice_channels, s.members = [], [], [], [], []
        s.default_role = type("R", (), {"id": 999, "name": "@everyone", "is_default": lambda self: True, "mention": "@everyone"})()
        s.icon, s.premium_subscriber_role, s.system_channel, s.rules_channel = None, None, None, None
    def get_member(s, i): return None
    def get_channel(s, i): return None
    def get_role(s, i): return None
    def get_thread(s, i): return None
GUILDE = Guilde()
SALON = Salon(); SALON.guild = GUILDE; GUILDE.me.guild = GUILDE
N = [1000]
class Message:
    def __init__(s, texte, auteur):
        N[0] += 1
        s.id, s.content, s.author, s.guild, s.channel = N[0], texte, auteur, GUILDE, SALON
        s.attachments, s.embeds, s.stickers, s.mentions, s.role_mentions, s.channel_mentions = [], [], [], [], [], []
        s.mention_everyone = "@everyone" in texte
        s.reference, s.type, s.webhook_id, s.message_snapshots, s.poll = None, discord.MessageType.default, None, [], None
        s.created_at, s.edited_at, s.jump_url, s.flags, s.interaction, s.application_id = MAINTENANT, None, "https://discord.com/x", None, None, None
        s.clean_content, s.system_content, s.pinned, s.tts, s.components = texte, texte, False, False, []
    async def delete(s, **k): note("SUPPRIMÉ")
    async def reply(s, *a, **k): note("RÉPONSE", (a[0] if a else k.get("content") or "")[:50])
    async def add_reaction(s, e): note("RÉACTION", e)

CAS = [l.rstrip("\n") for l in open(sys.argv[1], encoding="utf-8") if l.strip() and not l.startswith("#")]

async def main():
    uid = 100
    for ligne in CAS:
        uid += 1
        JOURNAL.clear()
        auteur = Membre(uid)
        for texte in ligne.split(" || "):
            try:
                await B.on_message(Message(texte, auteur))
            except Exception as ex:
                note("EXCEPTION", type(ex).__name__, ex)
            await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        print("■", ligne[:90]); print("   →", " | ".join(dict.fromkeys(JOURNAL)) or "rien")
asyncio.run(main())
