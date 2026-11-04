# ============================================================
# VEXOR - Discord Manager Bot (single-file edition)
# Python 3.10+ | discord.py 2.4+
#
# Install:
#   py -m pip install -U discord.py
#
# Set DISCORD_TOKEN as an environment variable. Never paste your
# bot token into chat or commit it to a public repository.
#
# Discord Developer Portal:
#   - Enable SERVER MEMBERS INTENT
#   - Enable MESSAGE CONTENT INTENT
# Invite permissions (grant only what you use):
#   Manage Roles, Kick Members, Ban Members, Moderate Members,
#   Manage Messages, Manage Channels, View Audit Log,
#   Send Messages, Embed Links, Read Message History,
#   Add Reactions.
#
# IMPORTANT LIMITATION:
# VEXOR cannot remotely disable another bot's application/slash
# commands using VEXOR's bot token. Discord integration command
# permissions must be configured by a server administrator in
# Server Settings > Integrations > select that bot > Commands.
# The /botlock command below records which integrations you intend
# to restrict and explains the required Discord-side action; it does
# NOT falsely claim to enforce another bot's commands.
# ============================================================

import os
import re
import json
import time
import asyncio
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is missing. Set it as an environment variable; "
        "do not put your token in the source code."
    )

CONFIG_FILE = "vexor_config.json"
DATA_FILE = "vexor_data.json"
SELF_ROLE_CHANNEL = "🎭-𝘚𝘌𝘓𝘍-𝘙𝘖𝘓𝘌𝘚"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -------------------------- persistence --------------------------

def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
            return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, OSError):
        print(f"WARNING: Could not read {path}; starting with empty data.")
        return {}

config = load_json(CONFIG_FILE)
data = load_json(DATA_FILE)

def save_json(path, value):
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
    os.replace(temp, path)

def save_config():
    save_json(CONFIG_FILE, config)

def save_data():
    save_json(DATA_FILE, data)

def cfg(guild_id):
    return config.setdefault(str(guild_id), {})

def gdata(guild_id):
    return data.setdefault(str(guild_id), {})

def is_owner(interaction: discord.Interaction):
    return interaction.guild is not None and interaction.user.id == interaction.guild.owner_id

async def owner_only(interaction: discord.Interaction):
    if not is_owner(interaction):
        await interaction.response.send_message(
            "Only the server owner can use this command.", ephemeral=True
        )
        return False
    return True

async def send_log(guild: discord.Guild, message: str):
    channel_id = cfg(guild.id).get("modlog")
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel:
        try:
            await channel.send(message[:1900])
        except discord.HTTPException:
            pass

async def safe_reply(interaction, content, *, ephemeral=True):
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral)

def bot_member(guild):
    return guild.me or guild.get_member(bot.user.id)

# -------------------------- ready / status --------------------------

@bot.event
async def on_ready():
    if not getattr(bot, "_vexor_views_registered", False):
        bot.add_view(TicketView())
        bot.add_view(CloseTicketView())
        bot._vexor_views_registered = True
    try:
        synced = await bot.tree.sync()
        print(f"VEXOR online as {bot.user}; synced {len(synced)} commands.")
    except discord.HTTPException as exc:
        print("Command sync failed:", exc)

@bot.tree.command(name="ping", description="Check VEXOR latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Pong! VEXOR latency: {round(bot.latency * 1000)} ms"
    )

@bot.tree.command(name="hello", description="Say hello")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message("Hello! VEXOR is here ⚡")

@bot.tree.command(name="serverstatus", description="Show server status")
async def serverstatus(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        return await safe_reply(interaction, "Use this command inside a server.")
    online = sum(
        1 for m in guild.members
        if m.status != discord.Status.offline and not m.bot
    )
    embed = discord.Embed(title=f"{guild.name} — Server Status", color=discord.Color.blurple())
    embed.add_field(name="Members", value=str(guild.member_count or 0))
    embed.add_field(name="Non-offline members (cached)", value=str(online))
    embed.add_field(name="Text channels", value=str(len(guild.text_channels)))
    embed.add_field(name="Voice channels", value=str(len(guild.voice_channels)))
    embed.add_field(name="Roles", value=str(len(guild.roles)))
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    await interaction.response.send_message(embed=embed)

# -------------------------- moderation --------------------------

@bot.tree.command(name="say", description="Make VEXOR send a message")
@app_commands.checks.has_permissions(manage_messages=True)
async def say(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(
        message, allowed_mentions=discord.AllowedMentions.none()
    )

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.id == interaction.user.id or member.top_role >= interaction.user.top_role:
        return await safe_reply(interaction, "You cannot kick yourself or a member with an equal/higher role.")
    me = bot_member(interaction.guild)
    if me is None or member.top_role >= me.top_role:
        return await safe_reply(interaction, "Move VEXOR's role above the target member.")
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 {member} was kicked. Reason: {reason}")
    await send_log(interaction.guild, f"👢 {member} kicked by {interaction.user}. Reason: {reason}")

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if member.id == interaction.user.id or member.top_role >= interaction.user.top_role:
        return await safe_reply(interaction, "You cannot ban yourself or a member with an equal/higher role.")
    me = bot_member(interaction.guild)
    if me is None or member.top_role >= me.top_role:
        return await safe_reply(interaction, "Move VEXOR's role above the target member.")
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 {member} was banned. Reason: {reason}")
    await send_log(interaction.guild, f"🔨 {member} banned by {interaction.user}. Reason: {reason}")

@bot.tree.command(name="unban", description="Unban a user by Discord ID")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
        await interaction.response.send_message(f"✅ {user} has been unbanned.")
        await send_log(interaction.guild, f"Unban: {user} by {interaction.user}. Reason: {reason}")
    except ValueError:
        await safe_reply(interaction, "Invalid numeric User ID.")
    except discord.NotFound:
        await safe_reply(interaction, "That user is not banned.")
    except discord.Forbidden:
        await safe_reply(interaction, "VEXOR is missing the Ban Members permission.")

@bot.tree.command(name="timeout", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def timeout_member(
    interaction: discord.Interaction, member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"
):
    if member.id == interaction.user.id or member.top_role >= interaction.user.top_role:
        return await safe_reply(interaction, "You cannot timeout yourself or an equal/higher role.")
    me = bot_member(interaction.guild)
    if me is None or member.top_role >= me.top_role:
        return await safe_reply(interaction, "Move VEXOR's role above the target member.")
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(f"⏳ {member.mention} timed out for {minutes} minutes.")
    await send_log(interaction.guild, f"⏳ {member} timed out by {interaction.user}: {reason}")

@bot.tree.command(name="untimeout", description="Remove a member timeout")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def untimeout(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None, reason=f"Timeout removed by {interaction.user}")
    await interaction.response.send_message(f"✅ Timeout removed from {member.mention}.")
    await send_log(interaction.guild, f"Timeout removed from {member} by {interaction.user}.")

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    records = gdata(interaction.guild.id).setdefault("warnings", {})
    records.setdefault(str(member.id), []).append({
        "moderator": interaction.user.id, "reason": reason,
        "time": datetime.now(timezone.utc).isoformat()
    })
    save_data()
    try:
        await member.send(f"⚠️ Warning from {interaction.guild.name}\nReason: {reason}")
    except discord.HTTPException:
        pass
    await interaction.response.send_message(f"⚠️ {member.mention} warned. Reason: {reason}")
    await send_log(interaction.guild, f"⚠️ {member} warned by {interaction.user}: {reason}")

@bot.tree.command(name="warnings", description="View a member's warning count")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(interaction: discord.Interaction, member: discord.Member):
    records = gdata(interaction.guild.id).get("warnings", {}).get(str(member.id), [])
    if not records:
        return await interaction.response.send_message(f"{member} has no saved warnings.", ephemeral=True)
    lines = [f"{i}. {w['reason']} — <t:{int(datetime.fromisoformat(w['time']).timestamp())}:R>"
             for i, w in enumerate(records[-10:], 1)]
    await interaction.response.send_message(
        f"Warnings for {member} (showing up to 10):\n" + "\n".join(lines), ephemeral=True
    )

@bot.tree.command(name="clear", description="Delete 1–100 recent messages")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)
    await send_log(interaction.guild, f"🧹 {interaction.user} deleted {len(deleted)} messages.")

@bot.tree.command(name="lock", description="Lock the current text channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    channel = interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Locked by {interaction.user}")
    await interaction.response.send_message("🔒 Channel locked.")
    await send_log(interaction.guild, f"🔒 {channel.mention} locked by {interaction.user}.")

@bot.tree.command(name="unlock", description="Unlock the current text channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    channel = interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {interaction.user}")
    await interaction.response.send_message("🔓 Channel unlocked.")
    await send_log(interaction.guild, f"🔓 {channel.mention} unlocked by {interaction.user}.")

@bot.tree.command(name="slowmode", description="Set channel slowmode in seconds")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
    await interaction.channel.edit(slowmode_delay=seconds)
    await interaction.response.send_message(f"⏱️ Slowmode set to {seconds} seconds.")

# -------------------------- setup / auto roles / welcome --------------------------

@bot.tree.command(name="setwelcome", description="Set the welcome channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setwelcome(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg(interaction.guild.id)["welcome"] = channel.id
    save_config()
    await interaction.response.send_message(f"✅ Welcome channel set to {channel.mention}.")

@bot.tree.command(name="setgoodbye", description="Set the goodbye channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setgoodbye(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg(interaction.guild.id)["goodbye"] = channel.id
    save_config()
    await interaction.response.send_message(f"✅ Goodbye channel set to {channel.mention}.")

@bot.tree.command(name="setautorole", description="Set the role automatically given to new members")
@app_commands.checks.has_permissions(manage_roles=True)
async def setautorole(interaction: discord.Interaction, role: discord.Role):
    me = bot_member(interaction.guild)
    if role.is_default() or me is None or role >= me.top_role:
        return await safe_reply(interaction, "Choose a normal role below VEXOR's highest role.")
    cfg(interaction.guild.id)["autorole"] = role.id
    save_config()
    await interaction.response.send_message(f"✅ Auto role set to {role.mention}.")

@bot.tree.command(name="setmodlog", description="Set moderation and event log channel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setmodlog(interaction: discord.Interaction, channel: discord.TextChannel):
    cfg(interaction.guild.id)["modlog"] = channel.id
    save_config()
    await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.")

@bot.tree.command(name="automod", description="Enable or disable invite-link filtering")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod(interaction: discord.Interaction, enabled: bool):
    cfg(interaction.guild.id)["automod"] = enabled
    save_config()
    await interaction.response.send_message(f"🛡️ Invite-link filter {'enabled' if enabled else 'disabled'}.")

@bot.tree.command(name="antispam", description="Enable or disable basic message flood protection")
@app_commands.checks.has_permissions(manage_guild=True)
async def antispam(interaction: discord.Interaction, enabled: bool):
    cfg(interaction.guild.id)["antispam"] = enabled
    save_config()
    await interaction.response.send_message(f"🛡️ Anti-spam {'enabled' if enabled else 'disabled'}.")

@bot.tree.command(name="antiraid", description="Enable or disable join-raid alert protection")
@app_commands.checks.has_permissions(manage_guild=True)
async def antiraid(interaction: discord.Interaction, enabled: bool):
    cfg(interaction.guild.id)["antiraid"] = enabled
    save_config()
    await interaction.response.send_message(f"🛡️ Anti-raid alerts {'enabled' if enabled else 'disabled'}.")

@bot.event
async def on_member_join(member: discord.Member):
    settings = cfg(member.guild.id)
    now = time.time()
    recent = [t for t in gdata(member.guild.id).get("recent_joins", []) if now - t < 30]
    recent.append(now)
    gdata(member.guild.id)["recent_joins"] = recent
    save_data()
    if settings.get("antiraid") and len(recent) >= 8:
        await send_log(member.guild, f"🚨 Possible raid: {len(recent)} joins in 30 seconds.")
    welcome_id = settings.get("welcome")
    welcome = member.guild.get_channel(welcome_id) if welcome_id else None
    if welcome:
        await welcome.send(f"👋 Welcome {member.mention} to **{member.guild.name}**! You are member #{member.guild.member_count}.")
    role_id = settings.get("autorole")
    role = member.guild.get_role(role_id) if role_id else None
    me = bot_member(member.guild)
    if role and me and role < me.top_role:
        try:
            await member.add_roles(role, reason="VEXOR Auto Role")
        except discord.HTTPException as exc:
            await send_log(member.guild, f"Auto-role failed for {member}: {exc}")

@bot.event
async def on_member_remove(member: discord.Member):
    settings = cfg(member.guild.id)
    channel_id = settings.get("goodbye") or settings.get("welcome")
    channel = member.guild.get_channel(channel_id) if channel_id else None
    if channel:
        await channel.send(f"👋 **{member}** has left the server.")
    await send_log(member.guild, f"📤 {member} left the server.")

# -------------------------- automod / anti-spam --------------------------

invite_pattern = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/\S+", re.I)
message_windows = {}

@bot.event
async def on_message(message: discord.Message):
    if message.guild is None or message.author.bot:
        return
    settings = cfg(message.guild.id)
    if settings.get("automod") and invite_pattern.search(message.content):
        if not message.author.guild_permissions.manage_messages:
            try:
                await message.delete()
                await message.channel.send(
                    f"⚠️ {message.author.mention}, invite links are not allowed.",
                    delete_after=5
                )
                await send_log(message.guild, f"🛡️ Removed invite link from {message.author}.")
            except discord.HTTPException:
                pass
            return
    if settings.get("antispam") and not message.author.guild_permissions.manage_messages:
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        timestamps = [t for t in message_windows.get(key, []) if now - t < 7]
        timestamps.append(now)
        message_windows[key] = timestamps
        if len(timestamps) >= 6:
            try:
                await message.delete()
                await message.author.timeout(timedelta(seconds=30), reason="VEXOR anti-spam")
                await message.channel.send(f"⚠️ {message.author.mention}, slow down. 30-second timeout applied.", delete_after=6)
                await send_log(message.guild, f"Anti-spam timeout: {message.author}.")
            except discord.HTTPException:
                pass
            message_windows[key] = []
            return
    await bot.process_commands(message)

# -------------------------- reaction roles --------------------------

@bot.tree.command(name="reactionrole", description="Create a reaction role in the configured self-role channel")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True, add_reactions=True, read_message_history=True)
async def reactionrole(interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
    me = bot_member(interaction.guild)
    if me is None or role.is_default() or role >= me.top_role:
        return await safe_reply(interaction, "VEXOR's role must be above the selected role.")
    channel = discord.utils.get(interaction.guild.text_channels, name=SELF_ROLE_CHANNEL)
    if channel is None:
        return await safe_reply(interaction, f"Could not find #{SELF_ROLE_CHANNEL}.")
    try:
        msg = await channel.fetch_message(int(message_id))
        await msg.add_reaction(emoji)
        key = f"{channel.id}:{msg.id}:{emoji}"
        cfg(interaction.guild.id).setdefault("reaction_roles", {})[key] = role.id
        save_config()
        await interaction.response.send_message(f"✅ Reaction role created: {emoji} → {role.mention}")
    except (ValueError, discord.NotFound):
        await safe_reply(interaction, "Invalid message ID or message not found.")

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None or (payload.member and payload.member.bot):
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    role_id = cfg(guild.id).get("reaction_roles", {}).get(f"{payload.channel_id}:{payload.message_id}:{payload.emoji}")
    member = guild.get_member(payload.user_id)
    role = guild.get_role(role_id) if role_id else None
    me = bot_member(guild)
    if member and role and me and role < me.top_role:
        try:
            await member.add_roles(role, reason="VEXOR Reaction Role")
        except discord.HTTPException:
            pass

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    role_id = cfg(guild.id).get("reaction_roles", {}).get(f"{payload.channel_id}:{payload.message_id}:{payload.emoji}")
    member = guild.get_member(payload.user_id)
    role = guild.get_role(role_id) if role_id else None
    if member and role:
        try:
            await member.remove_roles(role, reason="VEXOR Reaction Role Removed")
        except discord.HTTPException:
            pass

# -------------------------- ticket system --------------------------

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.green, custom_id="vexor:ticket:create", emoji="🎫")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None:
            return await safe_reply(interaction, "Use this inside a server.")
        category_id = cfg(guild.id).get("ticket_category")
        category = guild.get_channel(category_id) if category_id else None
        safe_name = re.sub(r"[^a-z0-9-]", "", interaction.user.name.lower().replace(" ", "-"))[:18] or "member"
        channel_name = f"ticket-{safe_name}"
        existing = discord.utils.get(guild.text_channels, name=channel_name)
        if existing:
            return await safe_reply(interaction, f"You already have a ticket: {existing.mention}")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        me = bot_member(guild)
        if me:
            overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True)
        staff_role_id = cfg(guild.id).get("ticket_staff_role")
        staff_role = guild.get_role(staff_role_id) if staff_role_id else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        try:
            channel = await guild.create_text_channel(channel_name, category=category if isinstance(category, discord.CategoryChannel) else None, overwrites=overwrites, reason="VEXOR ticket created")
            await channel.send(f"{interaction.user.mention} Thanks for opening a ticket. Staff will be with you soon.", view=CloseTicketView())
            await interaction.response.send_message(f"🎫 Ticket created: {channel.mention}", ephemeral=True)
            await send_log(guild, f"🎫 Ticket opened by {interaction.user}: {channel.mention}")
        except discord.Forbidden:
            await safe_reply(interaction, "VEXOR needs Manage Channels permission.")

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.red, custom_id="vexor:ticket:close", emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.channel.name.startswith("ticket-"):
            return await safe_reply(interaction, "This is not a VEXOR ticket.")
        await interaction.response.send_message("Closing ticket in 5 seconds…", ephemeral=True)
        await send_log(interaction.guild, f"🔒 Ticket {interaction.channel.mention} closed by {interaction.user}.")
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")

@bot.tree.command(name="ticketsetup", description="Post the ticket creation panel")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
async def ticketsetup(interaction: discord.Interaction, staff_role: discord.Role = None):
    settings = cfg(interaction.guild.id)
    settings["ticket_staff_role"] = staff_role.id if staff_role else None
    save_config()
    embed = discord.Embed(title="VEXOR Support Tickets", description="Press the button below to open a private support ticket.", color=discord.Color.blurple())
    await interaction.channel.send(embed=embed, view=TicketView())
    await interaction.response.send_message("✅ Ticket panel posted.", ephemeral=True)

# -------------------------- giveaway system --------------------------

@bot.tree.command(name="giveaway", description="Start a simple giveaway")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 10080], prize: str):
    await interaction.response.defer()
    end_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    embed = discord.Embed(title="🎉 Giveaway!", description=f"Prize: **{prize}**\nReact with 🎉 to enter.\nEnds <t:{int(end_at.timestamp())}:R>", color=discord.Color.gold())
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎉")
    await send_log(interaction.guild, f"🎉 Giveaway started by {interaction.user}: {prize}")
    await interaction.followup.send(f"Giveaway started: {msg.jump_url}")

# -------------------------- server management --------------------------

@bot.tree.command(name="userinfo", description="Show information about a member")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"User Info — {member}", color=discord.Color.blurple())
    embed.add_field(name="User ID", value=str(member.id), inline=False)
    embed.add_field(name="Created", value=f"<t:{int(member.created_at.timestamp())}:R>")
    if member.joined_at:
        embed.add_field(name="Joined", value=f"<t:{int(member.joined_at.timestamp())}:R>")
    embed.add_field(name="Top role", value=member.top_role.mention)
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="serverinfo", description="Show server information")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=g.name, color=discord.Color.blurple())
    embed.add_field(name="Server ID", value=str(g.id))
    embed.add_field(name="Members", value=str(g.member_count))
    embed.add_field(name="Owner", value=f"<@{g.owner_id}>")
    embed.add_field(name="Created", value=f"<t:{int(g.created_at.timestamp())}:D>")
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    await interaction.response.send_message(embed=embed)

# -------------------------- special bot lock --------------------------

@bot.tree.command(name="botlock", description="Record a bot integration you want to restrict/unrestrict")
@app_commands.describe(action="Choose block, unblock, or list", target_bot="Select the bot user")
@app_commands.choices(action=[
    app_commands.Choice(name="block", value="block"),
    app_commands.Choice(name="unblock", value="unblock"),
    app_commands.Choice(name="list", value="list"),
])
async def botlock(interaction: discord.Interaction, action: app_commands.Choice[str], target_bot: discord.User = None):
    if not await owner_only(interaction):
        return
    settings = cfg(interaction.guild.id)
    locks = settings.setdefault("botlock_notes", {})
    if action.value == "list":
        if not locks:
            return await interaction.response.send_message("No bot-lock entries are saved.", ephemeral=True)
        lines = [f"• <@{uid}> — {state}" for uid, state in locks.items()]
        return await interaction.response.send_message(
            "Saved bot-lock list (configuration notes only):\n" + "\n".join(lines) +
            "\n\nTo actually restrict commands, open Server Settings → Integrations → select the bot → Commands and set the allowed roles/channels there.",
            ephemeral=True
        )
    if target_bot is None or not target_bot.bot:
        return await safe_reply(interaction, "Select a bot account.")
    locks[str(target_bot.id)] = action.value
    save_config()
    state_text = "marked for restriction" if action.value == "block" else "marked as allowed"
    await interaction.response.send_message(
        f"Saved: {target_bot.mention} is {state_text} in VEXOR's list.\n\n"
        "Important: this does not itself disable that bot's slash commands. "
        "Discord does not let VEXOR use its own bot token to edit another application's command permissions. "
        "To enforce it, go to Server Settings → Integrations → select that bot → Commands, "
        "then configure allowed roles/channels. Keep your owner account allowed.",
        ephemeral=True
    )

# -------------------------- errors --------------------------

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    if isinstance(original, app_commands.MissingPermissions):
        message = "❌ You do not have the Discord permission required for this command."
    elif isinstance(original, app_commands.BotMissingPermissions):
        message = "❌ VEXOR is missing a required permission. Check its role and channel permissions."
    elif isinstance(original, app_commands.CommandOnCooldown):
        message = "⏳ Please wait before using that command again."
    elif isinstance(original, discord.Forbidden):
        message = "❌ Discord denied the action. Check VEXOR's permissions and role hierarchy."
    else:
        print("VEXOR command error:", repr(original))
        message = "❌ An error occurred. Check the bot console for details."
    await safe_reply(interaction, message)

bot.run(TOKEN)
