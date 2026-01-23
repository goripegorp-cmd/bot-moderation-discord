# ============================================
# BOT DISCORD - MODÉRATION & PROTECTION
# ============================================
# Version 2.0 - Interface Premium
# Description: Bot complet de modération avec interface
#              magnifique et système de permissions avancé
# ============================================

import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import os
import re
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import Optional
import aiohttp

# Charger les variables d'environnement
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

# Configuration du bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# Chemin de la base de données
DB_PATH = 'moderation.db'

# ============================================
# COULEURS & EMOJIS POUR L'INTERFACE
# ============================================

class Colors:
    SUCCESS = 0x57F287
    ERROR = 0xED4245
    WARNING = 0xFEE75C
    INFO = 0x5865F2
    MODERATION = 0xEB459E
    PREMIUM = 0xF47FFF
    DARK = 0x2F3136
    GOLD = 0xFFD700
    CYAN = 0x00D9FF

class Emojis:
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    WARN = "🚨"
    MUTE = "🔇"
    UNMUTE = "🔊"
    KICK = "👢"
    BAN = "🔨"
    UNBAN = "🔓"
    TIMEOUT = "⏰"
    CLEAR = "🗑️"
    SHIELD = "🛡️"
    CROWN = "👑"
    SETTINGS = "⚙️"
    LOGS = "📜"
    MEMBER = "👤"
    MODERATOR = "👮"
    LINK = "🔗"
    IMAGE = "🖼️"
    PHISHING = "🎣"
    STATS = "📊"
    CALENDAR = "📅"
    ID = "🆔"
    REASON = "📝"
    DURATION = "⏱️"
    TOTAL = "📈"
    CHECK = "☑️"
    CROSS = "☒"

PHISHING_DOMAINS = [
    'discord-nitro.gift', 'discordgift.site', 'discord-app.com',
    'discorcl.com', 'dlscord.com', 'discordc.com', 'discord-airdrop.com',
    'steamcommunity.ru', 'steampowered.ru', 'free-nitro.com',
    'discord-drop.com', 'discordnitro.gift', 'claim-nitro.com'
]

# ============================================
# FONCTIONS D'INTERFACE
# ============================================

def create_embed(title=None, description=None, color=Colors.INFO, thumbnail=None, 
                 image=None, author_name=None, author_icon=None, 
                 footer_text=None, footer_icon=None, timestamp=True):
    embed = discord.Embed(
        title=title, description=description, color=color,
        timestamp=datetime.utcnow() if timestamp else None
    )
    if thumbnail: embed.set_thumbnail(url=thumbnail)
    if image: embed.set_image(url=image)
    if author_name: embed.set_author(name=author_name, icon_url=author_icon)
    if footer_text: embed.set_footer(text=footer_text, icon_url=footer_icon)
    return embed

def success_embed(title, description=None, **kwargs):
    return create_embed(title=f"{Emojis.SUCCESS} {title}", description=description, color=Colors.SUCCESS, **kwargs)

def error_embed(title, description=None, **kwargs):
    return create_embed(title=f"{Emojis.ERROR} {title}", description=description, color=Colors.ERROR, **kwargs)

def warning_embed(title, description=None, **kwargs):
    return create_embed(title=f"{Emojis.WARNING} {title}", description=description, color=Colors.WARNING, **kwargs)

def mod_embed(title, description=None, **kwargs):
    return create_embed(title=title, description=description, color=Colors.MODERATION, **kwargs)

# ============================================
# BASE DE DONNÉES
# ============================================

async def init_database():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL, reason TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY, log_channel_id INTEGER,
            mute_role_id INTEGER, warns_for_mute INTEGER DEFAULT 0,
            warns_for_kick INTEGER DEFAULT 0, warns_for_ban INTEGER DEFAULT 0,
            anti_link BOOLEAN DEFAULT 0, anti_image BOOLEAN DEFAULT 0,
            anti_phishing BOOLEAN DEFAULT 1, anti_spam BOOLEAN DEFAULT 0,
            anti_raid BOOLEAN DEFAULT 0, anti_fake_bot BOOLEAN DEFAULT 1)''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS immune_roles (
            guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, role_id))''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS staff_roles (
            guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, role_id))''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS exempt_channels (
            guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, channel_id))''')
        
        await db.execute('''CREATE TABLE IF NOT EXISTS mod_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL, action TEXT NOT NULL,
            reason TEXT, duration TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        
        await db.commit()
        print("✅ Base de données initialisée")

# ============================================
# FONCTIONS UTILITAIRES
# ============================================

async def get_guild_config(guild_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM guild_config WHERE guild_id = ?', (guild_id,))
        row = await cursor.fetchone()
        if row: return dict(row)
        await db.execute('INSERT INTO guild_config (guild_id) VALUES (?)', (guild_id,))
        await db.commit()
        return {'guild_id': guild_id, 'log_channel_id': None, 'mute_role_id': None,
                'warns_for_mute': 0, 'warns_for_kick': 0, 'warns_for_ban': 0,
                'anti_link': False, 'anti_image': False, 'anti_phishing': True,
                'anti_spam': False, 'anti_raid': False, 'anti_fake_bot': True}

async def is_immune(member):
    if member.id == member.guild.owner_id: return True
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (member.guild.id,))
        immune_roles = [row[0] for row in await cursor.fetchall()]
    return any(role.id in immune_roles for role in member.roles)

async def is_staff(member):
    if member.id == member.guild.owner_id: return True
    if member.guild_permissions.administrator: return True
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id = ?', (member.guild.id,))
        staff_roles = [row[0] for row in await cursor.fetchall()]
    return any(role.id in staff_roles for role in member.roles)

async def get_user_warns(guild_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            'SELECT * FROM warns WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC',
            (guild_id, user_id))
        return [dict(row) for row in await cursor.fetchall()]

async def add_warn(guild_id, user_id, moderator_id, reason):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO warns (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)',
                        (guild_id, user_id, moderator_id, reason))
        await db.commit()
        cursor = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id = ? AND user_id = ?', (guild_id, user_id))
        return (await cursor.fetchone())[0]

async def log_action(guild_id, user_id, moderator_id, action, reason=None, duration=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO mod_logs (guild_id, user_id, moderator_id, action, reason, duration) VALUES (?, ?, ?, ?, ?, ?)',
                        (guild_id, user_id, moderator_id, action, reason, duration))
        await db.commit()

async def send_log(guild, embed):
    config = await get_guild_config(guild.id)
    if config['log_channel_id']:
        channel = guild.get_channel(config['log_channel_id'])
        if channel:
            try: await channel.send(embed=embed)
            except: pass

def is_owner():
    async def predicate(interaction): return interaction.user.id == interaction.guild.owner_id
    return app_commands.check(predicate)

# ============================================
# ÉVÉNEMENTS
# ============================================

@bot.event
async def on_ready():
    await init_database()
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes synchronisées")
    except Exception as e: print(f"❌ Erreur: {e}")
    print(f"✅ Bot connecté: {bot.user}")
    print(f"✅ Serveurs: {len(bot.guilds)}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="🛡️ Protection"), status=discord.Status.online)

@bot.event
async def on_guild_join(guild):
    await get_guild_config(guild.id)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild: return
    if await is_immune(message.author): return
    
    config = await get_guild_config(message.guild.id)
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT 1 FROM exempt_channels WHERE guild_id = ? AND channel_id = ?',
                                  (message.guild.id, message.channel.id))
        if await cursor.fetchone(): return
    
    if config['anti_phishing']:
        for domain in PHISHING_DOMAINS:
            if domain in message.content.lower():
                await message.delete()
                embed = create_embed(title=f"{Emojis.PHISHING} Phishing Détecté",
                    description=f"{message.author.mention}, lien malveillant supprimé!", color=Colors.ERROR)
                await message.channel.send(embed=embed, delete_after=10)
                log_embed = mod_embed(title=f"{Emojis.PHISHING} Tentative de Phishing", thumbnail=message.author.display_avatar.url)
                log_embed.add_field(name="Membre", value=message.author.mention)
                log_embed.add_field(name="Domaine", value=f"`{domain}`")
                await send_log(message.guild, log_embed)
                return
    
    if config['anti_link'] and re.search(r'https?://[^\s]+', message.content):
        await message.delete()
        embed = create_embed(title=f"{Emojis.LINK} Lien Non Autorisé",
            description=f"{message.author.mention}, les liens ne sont pas autorisés.", color=Colors.WARNING)
        await message.channel.send(embed=embed, delete_after=10)
        return
    
    if config['anti_image'] and message.attachments:
        for att in message.attachments:
            if att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                await message.delete()
                embed = create_embed(title=f"{Emojis.IMAGE} Image Non Autorisée",
                    description=f"{message.author.mention}, les images ne sont pas autorisées.", color=Colors.WARNING)
                await message.channel.send(embed=embed, delete_after=10)
                return

@bot.event
async def on_member_join(member):
    account_age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
    embed = create_embed(title="👋 Nouveau Membre", color=Colors.SUCCESS, thumbnail=member.display_avatar.url)
    embed.add_field(name=f"{Emojis.MEMBER} Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
    embed.add_field(name=f"{Emojis.CALENDAR} Compte créé", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
    if account_age < 7: embed.add_field(name=f"{Emojis.WARNING} Attention", value="Compte récent!", inline=False)
    embed.set_footer(text=f"Membres: {member.guild.member_count}")
    await send_log(member.guild, embed)

@bot.event
async def on_member_remove(member):
    embed = create_embed(title="👋 Membre Parti", color=Colors.ERROR, thumbnail=member.display_avatar.url)
    embed.add_field(name=f"{Emojis.MEMBER} Membre", value=f"`{member}`\n`{member.id}`", inline=True)
    embed.set_footer(text=f"Membres: {member.guild.member_count}")
    await send_log(member.guild, embed)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    embed = create_embed(title=f"{Emojis.CLEAR} Message Supprimé", color=Colors.WARNING, thumbnail=message.author.display_avatar.url)
    embed.add_field(name="Auteur", value=message.author.mention, inline=True)
    embed.add_field(name="Salon", value=message.channel.mention, inline=True)
    if message.content:
        embed.add_field(name="Contenu", value=f"```{message.content[:500]}```", inline=False)
    await send_log(message.guild, embed)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content: return
    embed = create_embed(title="✏️ Message Modifié", color=Colors.INFO, thumbnail=before.author.display_avatar.url)
    embed.add_field(name="Auteur", value=before.author.mention, inline=True)
    embed.add_field(name="Salon", value=before.channel.mention, inline=True)
    embed.add_field(name="Avant", value=f"```{before.content[:300] or '(vide)'}```", inline=False)
    embed.add_field(name="Après", value=f"```{after.content[:300] or '(vide)'}```", inline=False)
    await send_log(before.guild, embed)

# ============================================
# COMMANDES DE CONFIGURATION (OWNER)
# ============================================

config_group = app_commands.Group(name="config", description="⚙️ Configuration (Owner)", default_permissions=discord.Permissions(administrator=True))

@config_group.command(name="logs", description="📜 Définir le salon de logs")
@is_owner()
async def config_logs(interaction: discord.Interaction, channel: discord.TextChannel):
    await get_guild_config(interaction.guild.id)  # S'assurer que la config existe
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE guild_config SET log_channel_id = ? WHERE guild_id = ?', (channel.id, interaction.guild.id))
        await db.commit()
    embed = success_embed("Salon de Logs", f"Logs envoyés dans {channel.mention}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_group.command(name="muterole", description="🔇 Définir le rôle mute")
@is_owner()
async def config_muterole(interaction: discord.Interaction, role: discord.Role):
    await get_guild_config(interaction.guild.id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE guild_config SET mute_role_id = ? WHERE guild_id = ?', (role.id, interaction.guild.id))
        await db.commit()
    embed = success_embed("Rôle Mute", f"Rôle mute: {role.mention}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_group.command(name="staffrole", description="👮 Gérer les rôles staff")
@is_owner()
@app_commands.choices(action=[app_commands.Choice(name="➕ Ajouter", value="add"), app_commands.Choice(name="➖ Retirer", value="remove")])
async def config_staffrole(interaction: discord.Interaction, action: str, role: discord.Role):
    async with aiosqlite.connect(DB_PATH) as db:
        if action == "add":
            await db.execute('INSERT OR IGNORE INTO staff_roles (guild_id, role_id) VALUES (?, ?)', (interaction.guild.id, role.id))
            embed = success_embed("Rôle Staff Ajouté", f"{role.mention} peut utiliser les commandes de modération")
        else:
            await db.execute('DELETE FROM staff_roles WHERE guild_id = ? AND role_id = ?', (interaction.guild.id, role.id))
            embed = success_embed("Rôle Staff Retiré", f"{role.mention} ne peut plus utiliser les commandes")
        await db.commit()
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_group.command(name="sanctions", description="⚖️ Sanctions automatiques")
@is_owner()
async def config_sanctions(interaction: discord.Interaction, warns_mute: int = 0, warns_kick: int = 0, warns_ban: int = 0):
    await get_guild_config(interaction.guild.id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE guild_config SET warns_for_mute = ?, warns_for_kick = ?, warns_for_ban = ? WHERE guild_id = ?',
                        (warns_mute, warns_kick, warns_ban, interaction.guild.id))
        await db.commit()
    embed = create_embed(title=f"{Emojis.SETTINGS} Sanctions Configurées", color=Colors.SUCCESS)
    embed.add_field(name=f"{Emojis.MUTE} Mute", value=f"```{warns_mute} warns```" if warns_mute else "```Désactivé```", inline=True)
    embed.add_field(name=f"{Emojis.KICK} Kick", value=f"```{warns_kick} warns```" if warns_kick else "```Désactivé```", inline=True)
    embed.add_field(name=f"{Emojis.BAN} Ban", value=f"```{warns_ban} warns```" if warns_ban else "```Désactivé```", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_group.command(name="protection", description="🛡️ Activer/désactiver une protection")
@is_owner()
@app_commands.choices(protection=[
    app_commands.Choice(name="🔗 Anti-Liens", value="anti_link"),
    app_commands.Choice(name="🖼️ Anti-Images", value="anti_image"),
    app_commands.Choice(name="🎣 Anti-Phishing", value="anti_phishing")])
async def config_protection(interaction: discord.Interaction, protection: str, activer: bool):
    await get_guild_config(interaction.guild.id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f'UPDATE guild_config SET {protection} = ? WHERE guild_id = ?', (activer, interaction.guild.id))
        await db.commit()
    names = {"anti_link": "Anti-Liens", "anti_image": "Anti-Images", "anti_phishing": "Anti-Phishing"}
    status = "activée ✅" if activer else "désactivée ❌"
    embed = create_embed(title=f"{Emojis.SHIELD} Protection {names[protection]}", description=f"Protection **{status}**", 
                        color=Colors.SUCCESS if activer else Colors.ERROR)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_group.command(name="immunerole", description="👑 Gérer les rôles immunisés")
@is_owner()
@app_commands.choices(action=[app_commands.Choice(name="➕ Ajouter", value="add"), app_commands.Choice(name="➖ Retirer", value="remove")])
async def config_immunerole(interaction: discord.Interaction, action: str, role: discord.Role):
    async with aiosqlite.connect(DB_PATH) as db:
        if action == "add":
            await db.execute('INSERT OR IGNORE INTO immune_roles (guild_id, role_id) VALUES (?, ?)', (interaction.guild.id, role.id))
            embed = success_embed("Rôle Immunisé", f"{role.mention} est maintenant **immunisé**")
        else:
            await db.execute('DELETE FROM immune_roles WHERE guild_id = ? AND role_id = ?', (interaction.guild.id, role.id))
            embed = success_embed("Immunité Retirée", f"{role.mention} n'est plus immunisé")
        await db.commit()
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_group.command(name="view", description="👁️ Voir la configuration")
@is_owner()
async def config_view(interaction: discord.Interaction):
    config = await get_guild_config(interaction.guild.id)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT role_id FROM immune_roles WHERE guild_id = ?', (interaction.guild.id,))
        immune = [interaction.guild.get_role(r[0]) for r in await cursor.fetchall()]
        cursor = await db.execute('SELECT role_id FROM staff_roles WHERE guild_id = ?', (interaction.guild.id,))
        staff = [interaction.guild.get_role(r[0]) for r in await cursor.fetchall()]
    
    embed = create_embed(title=f"{Emojis.SETTINGS} Configuration", color=Colors.PREMIUM,
                        thumbnail=interaction.guild.icon.url if interaction.guild.icon else None)
    
    log_ch = interaction.guild.get_channel(config['log_channel_id'])
    mute_r = interaction.guild.get_role(config['mute_role_id'])
    embed.add_field(name=f"{Emojis.LOGS} Logs", value=log_ch.mention if log_ch else "`Non configuré`", inline=True)
    embed.add_field(name=f"{Emojis.MUTE} Rôle Mute", value=mute_r.mention if mute_r else "`Non configuré`", inline=True)
    
    sanctions = ""
    if config['warns_for_mute']: sanctions += f"🔇 Mute: **{config['warns_for_mute']}** warns\n"
    if config['warns_for_kick']: sanctions += f"👢 Kick: **{config['warns_for_kick']}** warns\n"
    if config['warns_for_ban']: sanctions += f"🔨 Ban: **{config['warns_for_ban']}** warns\n"
    embed.add_field(name="⚖️ Sanctions Auto", value=sanctions or "`Aucune`", inline=False)
    
    protections = ""
    if config['anti_link']: protections += "✅ Anti-Liens\n"
    if config['anti_image']: protections += "✅ Anti-Images\n"
    if config['anti_phishing']: protections += "✅ Anti-Phishing\n"
    embed.add_field(name=f"{Emojis.SHIELD} Protections", value=protections or "`Aucune`", inline=True)
    
    embed.add_field(name=f"{Emojis.CROWN} Immunisés", value=", ".join([r.mention for r in immune if r]) or "`Aucun`", inline=False)
    embed.add_field(name=f"{Emojis.MODERATOR} Staff", value=", ".join([r.mention for r in staff if r]) or "`Aucun`", inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.tree.add_command(config_group)

# ============================================
# COMMANDES DE MODÉRATION
# ============================================

@bot.tree.command(name="warn", description="🚨 Avertir un membre")
@app_commands.default_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison"):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée", "Vous n'avez pas accès à cette commande."), ephemeral=True)
    if await is_immune(member):
        return await interaction.response.send_message(embed=error_embed("Action Impossible", "Ce membre est **immunisé**."), ephemeral=True)
    
    count = await add_warn(interaction.guild.id, member.id, interaction.user.id, reason)
    await log_action(interaction.guild.id, member.id, interaction.user.id, "WARN", reason)
    
    embed = mod_embed(title=f"{Emojis.WARN} Avertissement", description=f"{member.mention} a reçu un warn", thumbnail=member.display_avatar.url)
    embed.add_field(name=f"{Emojis.MEMBER} Membre", value=f"{member.mention}\n`{member.id}`", inline=True)
    embed.add_field(name=f"{Emojis.MODERATOR} Modérateur", value=interaction.user.mention, inline=True)
    embed.add_field(name=f"{Emojis.TOTAL} Total", value=f"```{count}```", inline=True)
    embed.add_field(name=f"{Emojis.REASON} Raison", value=f"```{reason}```", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_log(interaction.guild, embed)
    
    config = await get_guild_config(interaction.guild.id)
    if config['warns_for_ban'] and count >= config['warns_for_ban']:
        await member.ban(reason=f"[AUTO] {count} warns")
        await interaction.followup.send(embed=warning_embed("Ban Automatique", f"{member} banni ({count} warns)"), ephemeral=True)
    elif config['warns_for_kick'] and count >= config['warns_for_kick']:
        await member.kick(reason=f"[AUTO] {count} warns")
        await interaction.followup.send(embed=warning_embed("Kick Automatique", f"{member} expulsé ({count} warns)"), ephemeral=True)
    elif config['warns_for_mute'] and count >= config['warns_for_mute']:
        mute_role = interaction.guild.get_role(config['mute_role_id'])
        if mute_role:
            await member.add_roles(mute_role)
            await interaction.followup.send(embed=warning_embed("Mute Automatique", f"{member} mute ({count} warns)"), ephemeral=True)

@bot.tree.command(name="warnings", description="📋 Voir les warns d'un membre")
@app_commands.default_permissions(moderate_members=True)
async def warnings(interaction: discord.Interaction, member: discord.Member):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    
    warns = await get_user_warns(interaction.guild.id, member.id)
    embed = create_embed(title=f"{Emojis.LOGS} Warns de {member}", color=Colors.INFO if not warns else Colors.WARNING, thumbnail=member.display_avatar.url)
    embed.add_field(name=f"{Emojis.TOTAL} Total", value=f"```{len(warns)}```", inline=True)
    
    for w in warns[:5]:
        mod = interaction.guild.get_member(w['moderator_id'])
        embed.add_field(name=f"#{w['id']} • {w['timestamp'][:10]}", value=f"**Raison:** {w['reason']}\n**Par:** {mod.name if mod else 'Inconnu'}", inline=False)
    
    if not warns: embed.add_field(name=f"{Emojis.SUCCESS} Aucun Warn", value="Ce membre est clean!", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarns", description="🗑️ Supprimer tous les warns")
@app_commands.default_permissions(administrator=True)
async def clearwarns(interaction: discord.Interaction, member: discord.Member):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT COUNT(*) FROM warns WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, member.id))
        count = (await cursor.fetchone())[0]
        await db.execute('DELETE FROM warns WHERE guild_id = ? AND user_id = ?', (interaction.guild.id, member.id))
        await db.commit()
    
    embed = success_embed("Warns Supprimés", f"**{count}** warn(s) supprimé(s) pour {member.mention}", thumbnail=member.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_log(interaction.guild, embed)

@bot.tree.command(name="mute", description="🔇 Mute un membre")
@app_commands.default_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison"):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    if await is_immune(member):
        return await interaction.response.send_message(embed=error_embed("Membre Immunisé"), ephemeral=True)
    
    config = await get_guild_config(interaction.guild.id)
    mute_role = interaction.guild.get_role(config['mute_role_id'])
    if not mute_role:
        return await interaction.response.send_message(embed=error_embed("Configuration", "Rôle mute non configuré. Utilisez `/config muterole`"), ephemeral=True)
    
    await member.add_roles(mute_role, reason=reason)
    await log_action(interaction.guild.id, member.id, interaction.user.id, "MUTE", reason)
    
    embed = mod_embed(title=f"{Emojis.MUTE} Membre Mute", thumbnail=member.display_avatar.url)
    embed.add_field(name=f"{Emojis.MEMBER} Membre", value=member.mention, inline=True)
    embed.add_field(name=f"{Emojis.MODERATOR} Par", value=interaction.user.mention, inline=True)
    embed.add_field(name=f"{Emojis.REASON} Raison", value=f"```{reason}```", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_log(interaction.guild, embed)

@bot.tree.command(name="unmute", description="🔊 Unmute un membre")
@app_commands.default_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    
    config = await get_guild_config(interaction.guild.id)
    mute_role = interaction.guild.get_role(config['mute_role_id'])
    if mute_role and mute_role in member.roles:
        await member.remove_roles(mute_role)
        embed = success_embed("Membre Unmute", f"{member.mention} a été unmute", thumbnail=member.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_log(interaction.guild, embed)
    else:
        await interaction.response.send_message(embed=error_embed("Erreur", "Ce membre n'est pas mute"), ephemeral=True)

@bot.tree.command(name="timeout", description="⏰ Timeout un membre")
@app_commands.default_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Aucune raison"):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    if await is_immune(member):
        return await interaction.response.send_message(embed=error_embed("Membre Immunisé"), ephemeral=True)
    if minutes > 40320:
        return await interaction.response.send_message(embed=error_embed("Durée Invalide", "Maximum: 28 jours"), ephemeral=True)
    
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await log_action(interaction.guild.id, member.id, interaction.user.id, "TIMEOUT", reason, f"{minutes}min")
    
    duration = f"{minutes//1440}j" if minutes >= 1440 else f"{minutes//60}h" if minutes >= 60 else f"{minutes}min"
    embed = mod_embed(title=f"{Emojis.TIMEOUT} Timeout", thumbnail=member.display_avatar.url)
    embed.add_field(name=f"{Emojis.MEMBER} Membre", value=member.mention, inline=True)
    embed.add_field(name=f"{Emojis.DURATION} Durée", value=f"```{duration}```", inline=True)
    embed.add_field(name=f"{Emojis.REASON} Raison", value=f"```{reason}```", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_log(interaction.guild, embed)

@bot.tree.command(name="kick", description="👢 Expulser un membre")
@app_commands.default_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison"):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    if await is_immune(member):
        return await interaction.response.send_message(embed=error_embed("Membre Immunisé"), ephemeral=True)
    
    name, avatar = str(member), member.display_avatar.url
    await member.kick(reason=reason)
    await log_action(interaction.guild.id, member.id, interaction.user.id, "KICK", reason)
    
    embed = mod_embed(title=f"{Emojis.KICK} Membre Expulsé", thumbnail=avatar)
    embed.add_field(name=f"{Emojis.MEMBER} Membre", value=f"`{name}`", inline=True)
    embed.add_field(name=f"{Emojis.MODERATOR} Par", value=interaction.user.mention, inline=True)
    embed.add_field(name=f"{Emojis.REASON} Raison", value=f"```{reason}```", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_log(interaction.guild, embed)

@bot.tree.command(name="ban", description="🔨 Bannir un membre")
@app_commands.default_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Aucune raison", delete_days: int = 0):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    if await is_immune(member):
        return await interaction.response.send_message(embed=error_embed("Membre Immunisé"), ephemeral=True)
    
    name, avatar = str(member), member.display_avatar.url
    await member.ban(reason=reason, delete_message_days=min(7, max(0, delete_days)))
    await log_action(interaction.guild.id, member.id, interaction.user.id, "BAN", reason)
    
    embed = create_embed(title=f"{Emojis.BAN} Membre Banni", color=Colors.ERROR, thumbnail=avatar)
    embed.add_field(name=f"{Emojis.MEMBER} Membre", value=f"`{name}`", inline=True)
    embed.add_field(name=f"{Emojis.MODERATOR} Par", value=interaction.user.mention, inline=True)
    embed.add_field(name=f"{Emojis.REASON} Raison", value=f"```{reason}```", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await send_log(interaction.guild, embed)

@bot.tree.command(name="unban", description="🔓 Débannir un utilisateur")
@app_commands.default_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        embed = success_embed("Utilisateur Débanni", f"`{user}` a été débanni", thumbnail=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_log(interaction.guild, embed)
    except:
        await interaction.response.send_message(embed=error_embed("Erreur", "ID invalide ou utilisateur non banni"), ephemeral=True)

@bot.tree.command(name="clear", description="🗑️ Supprimer des messages")
@app_commands.default_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=min(100, max(1, amount)))
    
    embed = success_embed("Messages Supprimés", f"**{len(deleted)}** messages supprimés")
    embed.add_field(name="Salon", value=interaction.channel.mention, inline=True)
    embed.add_field(name="Par", value=interaction.user.mention, inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="modlogs", description="📜 Historique des sanctions")
@app_commands.default_permissions(moderate_members=True)
async def modlogs(interaction: discord.Interaction, member: discord.Member):
    if not await is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_embed("Permission Refusée"), ephemeral=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM mod_logs WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC LIMIT 10',
                                  (interaction.guild.id, member.id))
        logs = [dict(r) for r in await cursor.fetchall()]
    
    embed = create_embed(title=f"{Emojis.LOGS} Historique de {member}", color=Colors.INFO, thumbnail=member.display_avatar.url)
    embed.add_field(name=f"{Emojis.TOTAL} Actions", value=f"```{len(logs)}```", inline=True)
    
    emojis = {"WARN": "🚨", "MUTE": "🔇", "UNMUTE": "🔊", "TIMEOUT": "⏰", "KICK": "👢", "BAN": "🔨", "UNBAN": "🔓"}
    for log in logs:
        mod = interaction.guild.get_member(log['moderator_id'])
        embed.add_field(name=f"{emojis.get(log['action'], '📝')} {log['action']} • {log['timestamp'][:10]}",
                       value=f"**Par:** {mod.name if mod else 'Inconnu'}\n**Raison:** {log['reason'] or 'N/A'}", inline=False)
    
    if not logs: embed.add_field(name=f"{Emojis.SUCCESS} Aucune Sanction", value="Historique vide", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="📚 Aide du bot")
async def help_cmd(interaction: discord.Interaction):
    embed = create_embed(title=f"{Emojis.INFO} Aide - Bot Modération", color=Colors.PREMIUM, thumbnail=bot.user.display_avatar.url)
    embed.add_field(name=f"{Emojis.MODERATOR} Modération", value="```/warn /warnings /clearwarns\n/mute /unmute /timeout\n/kick /ban /unban /clear\n/modlogs```", inline=False)
    if interaction.user.id == interaction.guild.owner_id:
        embed.add_field(name=f"{Emojis.CROWN} Configuration (Owner)", value="```/config logs /config muterole\n/config staffrole /config sanctions\n/config protection /config immunerole\n/config view```", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============================================
# GESTION DES ERREURS
# ============================================

@bot.tree.error
async def on_error(interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        embed = error_embed("Accès Refusé", "Cette commande est réservée au **propriétaire** du serveur.")
    else:
        embed = error_embed("Erreur", f"```{str(error)[:200]}```")
    try: await interaction.response.send_message(embed=embed, ephemeral=True)
    except: await interaction.followup.send(embed=embed, ephemeral=True)

# ============================================
# LANCEMENT
# ============================================

if __name__ == "__main__":
    print("🚀 Démarrage du bot...")
    bot.run(TOKEN)
