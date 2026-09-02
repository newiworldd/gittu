import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import asyncio
from dotenv import load_dotenv

# ---------- Configuration ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
import io
import random
import string
from openai import AsyncOpenAI
from db import get_guild_config, save_guild_config, get_ticket, save_ticket, delete_ticket, generate_license, has_user_claimed, mark_user_claimed, reset_user_claim, reset_all_claims, get_user_claim, reveal_user_key
import aiohttp

scaleway_key = os.getenv("SCALEWAY_API_KEY") or os.getenv("SCW_SECRET_KEY")
scaleway_base_url = os.getenv("SCALEWAY_BASE_URL", "https://api.scaleway.ai/ff39d33c-a9a2-44b6-9070-4d3b70400fa1/v1")

scaleway_client = None
if scaleway_key:
    scaleway_client = AsyncOpenAI(base_url=scaleway_base_url, api_key=scaleway_key)

async def get_available_ticket_category(guild: discord.Guild):
    return None

async def check_guild_authorized(interaction: discord.Interaction) -> bool:
    """Checks if the guild is authorized to use the bot commands, or if the user is the bot owner."""
    if not interaction.guild:
        return False
        
    is_owner = False
    try:
        is_owner = await interaction.client.is_owner(interaction.user)
    except Exception:
        pass
        
    owner_id_env = os.getenv("OWNER_ID")
    if owner_id_env and str(interaction.user.id) == str(owner_id_env):
        is_owner = True
        
    if is_owner:
        return True
        
    guild_config = get_guild_config(interaction.guild.id)
    return guild_config.get("authorized", False)


# ---------- Bot Setup ----------
class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.automod_warnings = {}
        self.admin_message_timestamps = {}
        self.scam_hash_cache = {}  # MD5 Hash -> boolean (True if scam, False if clean)

    async def setup_hook(self):
        self.add_view(TicketTypeSelectView())  # persistent view
        self.add_view(TrialKeyClaimButtonView())  # persistent key claim view
        await self.tree.sync()
        self.status_task.start()
        


    @tasks.loop(minutes=2)
    async def status_task(self):
        server_count = len(self.guilds) + 524  # Fake count as requested
        await self.change_presence(
            activity=discord.Streaming(
                name=f"Watching {server_count} Servers | Anik X Cheats",
                url="https://twitch.tv/anikxcheats"
            )
        )

    @status_task.before_loop
    async def before_status_task(self):
        await self.wait_until_ready()

    async def on_ready(self):
        print(f"Logged in as {self.user}")

    async def on_member_join(self, member):
        guild_config = get_guild_config(member.guild.id)
        
        # Anti-Alt Account Protection
        if guild_config.get("anti_alt_enabled"):
            import datetime
            now = discord.utils.utcnow()
            creation_date = member.created_at
            age = (now - creation_date).days
            limit = guild_config.get("anti_alt_days", 7)
            
            if age < limit:
                try:
                    reason = f"Anti-Alt Protection: Account age ({age} days) is less than required ({limit} days)"
                    try:
                        dm_embed = discord.Embed(
                            title="❌ Kicked from Server",
                            description=(
                                f"You were kicked from **{member.guild.name}** because your account is too new.\n"
                                f"Minimum required account age: **{limit} days**.\n"
                                f"Your account age: **{age} days**."
                            ),
                            color=discord.Color.red()
                        )
                        await member.send(embed=dm_embed)
                    except:
                        pass
                    
                    await member.kick(reason=reason)
                    
                    log_channel_id = guild_config.get("log_channel_id")
                    if log_channel_id:
                        log_channel = member.guild.get_channel(int(log_channel_id))
                        if log_channel:
                            log_embed = discord.Embed(
                                title="🛡️ Anti-Alt Account Kicked",
                                color=discord.Color.red()
                            )
                            log_embed.add_field(name="User", value=f"{member} ({member.id})", inline=True)
                            log_embed.add_field(name="Account Age", value=f"{age} days (Created: {creation_date.strftime('%Y-%m-%d')})", inline=True)
                            log_embed.add_field(name="Required Age", value=f"{limit} days", inline=True)
                            log_embed.timestamp = discord.utils.utcnow()
                            await log_channel.send(embed=log_embed)
                except Exception as e:
                    print(f"Anti-Alt Kick Failed: {e}")
                return

        # Auto-Role Assignment
        if guild_config.get("autorole_enabled"):
            role_id = guild_config.get("autorole_role_id")
            if role_id:
                role = member.guild.get_role(int(role_id))
                if role:
                    try:
                        await member.add_roles(role)
                    except discord.Forbidden:
                        print(f"Failed to assign auto-role in {member.guild.name}: Bot lacks permissions (Forbidden).")
                    except Exception as e:
                        print(f"Error assigning auto-role: {e}")

        welcome_channel_id = guild_config.get("welcome_channel_id")
        
        if guild_config.get("welcome_enabled") and welcome_channel_id:
            channel = self.get_channel(int(welcome_channel_id))
            if channel:
                title = guild_config.get("welcome_title")
                if not title or title.strip() == "":
                    title = f"Welcome to {member.guild.name} 🚀"
                    
                desc = guild_config.get("welcome_description")
                if not desc or desc.strip() == "":
                    desc = f"Hey {member.mention}, welcome to the core of **{member.guild.name}**"
                    
                img = guild_config.get("welcome_image", "")
                
                # Format variables
                title = title.replace("{server_name}", member.guild.name)
                desc = desc.replace("{server_name}", member.guild.name).replace("{user_mention}", member.mention)

                # Build stunning embed
                embed = discord.Embed(
                    title=title,
                    description=desc,
                    color=0x2b2d31
                )
                embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
                if img:
                    embed.set_image(url=img)
                
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass

        # Public Chat Welcome Logic (Separate short message in general chat)
        if guild_config.get("public_chat_welcome_enabled"):
            pc_welcome_channel_id = guild_config.get("public_chat_welcome_channel_id")
            if pc_welcome_channel_id:
                pc_channel = self.get_channel(int(pc_welcome_channel_id))
                if pc_channel:
                    pc_msg = guild_config.get(
                        "public_chat_welcome_message", 
                        "Hey {user_mention}, welcome to the chat! Make sure to read the rules and stay safe. 🚀"
                    )
                    pc_msg = pc_msg.replace("{server_name}", member.guild.name).replace("{user_mention}", member.mention)
                    try:
                        pc_sent = await pc_channel.send(pc_msg)
                        await asyncio.sleep(5)
                        await pc_sent.delete()
                    except discord.Forbidden:
                        pass

        # DM Welcome Logic
        if guild_config.get("dm_welcome_enabled"):
            default_dm = (
                f"Welcome to {member.guild.name}! We are thrilled to have you here.\n\n"
                "## BASIC PANEL  <a:opp:1463879098525946052>\n\n"
                "<:1383730976848609280:1463908853581086872>  **PRICE LIST :**\n"
                "```\n"
                "1 MONTH = 700 INR BDT / 8$\n"
                "PERMANENT = 2000 INR BDT / 24$```\n\n"
                "## AXC PREMIUM PANEL V3.2 <a:opp:1463879098525946052>\n\n"
                "<:1383730976848609280:1463908853581086872>   **PRICE LIST :**\n"
                "```\n"
                "7 DAYS = 400 INR BDT / 5$\n"
                "15 DAYS = 800 INR BDT / 10$\n"
                "1 MONTH = 1000 INR BDT / 12$\n"
                "PERMANENT = 3000 INR BDT / 35$```\n\n"
                "## PREMIUM UID BYPASS <a:opp:1463879098525946052>\n\n"
                "<:1383730976848609280:1463908853581086872>   **PRICE LIST :**\n"
                "```\n"
                "7 DAYS = 400 INR BDT / 5$\n"
                "1 MONTH = 800 INR BDT / 8$\n"
                "PERMANENT = 2000 INR BDT / 25$```\n\n"
                "**⚠️ OPEN TICKET FOR BUY OR GET SUPPORT**"
            )
            dm_msg = guild_config.get("dm_welcome_message")
            if not dm_msg or dm_msg.strip() == "":
                dm_msg = default_dm
            dm_msg = dm_msg.replace("{server_name}", member.guild.name).replace("{user_mention}", member.mention)
            ticket_link = guild_config.get("dm_welcome_ticket_link")
            dm_image = guild_config.get("dm_welcome_image")
            if not dm_image or dm_image.strip() == "":
                dm_image = "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif"
            
            embed = discord.Embed(
                title=f"Welcome to {member.guild.name}!",
                description=dm_msg,
                color=0x2b2d31
            )
            
            # Use ticket_logo if available, otherwise fallback to guild icon
            custom_logo = guild_config.get("ticket_logo")
            if custom_logo and custom_logo.strip() != "":
                embed.set_thumbnail(url=custom_logo.strip())
            elif member.guild.icon:
                embed.set_thumbnail(url=member.guild.icon.url)
                
            if dm_image and dm_image.strip() != "":
                embed.set_image(url=dm_image.strip())
                
            if ticket_link:
                # Add a button with the ticket link
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Open a Ticket", url=ticket_link, style=discord.ButtonStyle.link))
                try:
                    await member.send(embed=embed, view=view)
                except discord.Forbidden:
                    pass
            else:
                try:
                    await member.send(embed=embed)
                except discord.Forbidden:
                    pass

    async def on_member_remove(self, member):
        guild_config = get_guild_config(member.guild.id)
        if guild_config.get("leave_enabled"):
            leave_channel_id = guild_config.get("leave_channel_id")
            if leave_channel_id:
                channel = self.get_channel(int(leave_channel_id))
                if channel:
                    msg = guild_config.get("leave_message", "**{username}** has left the server. 😢")
                    msg = msg.replace("{username}", member.name).replace("{server_name}", member.guild.name)
                    try:
                        await channel.send(msg)
                    except discord.Forbidden:
                        pass

    async def on_message_delete(self, message):
        if message.author.bot or not message.guild:
            return
        guild_config = get_guild_config(message.guild.id)
        log_channel_id = guild_config.get("log_channel_id")
        if log_channel_id:
            channel = self.get_channel(int(log_channel_id))
            if channel:
                embed = discord.Embed(title="🗑️ Message Deleted", color=discord.Color.red())
                embed.add_field(name="Author", value=message.author.mention, inline=True)
                embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                embed.add_field(name="Content", value=message.content[:1024] or "No content", inline=False)
                embed.set_footer(text=f"User ID: {message.author.id}")
                embed.timestamp = discord.utils.utcnow()
                try: await channel.send(embed=embed)
                except: pass

    async def on_message_edit(self, before, after):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        guild_config = get_guild_config(before.guild.id)
        log_channel_id = guild_config.get("log_channel_id")
        if log_channel_id:
            channel = self.get_channel(int(log_channel_id))
            if channel:
                embed = discord.Embed(title="✏️ Message Edited", color=discord.Color.orange(), url=after.jump_url)
                embed.add_field(name="Author", value=before.author.mention, inline=True)
                embed.add_field(name="Channel", value=before.channel.mention, inline=True)
                embed.add_field(name="Before", value=before.content[:1024] or "None", inline=False)
                embed.add_field(name="After", value=after.content[:1024] or "None", inline=False)
                embed.timestamp = discord.utils.utcnow()
                try: await channel.send(embed=embed)
                except: pass

    async def on_message(self, message):
        if message.author.bot:
            return

        # Handle DM password verification for locked keys
        if message.guild is None:
            claim = get_user_claim(message.author.id)
            if claim and not claim.get("revealed", True):
                guild_id = claim.get("guild_id")
                if guild_id:
                    guild_config = get_guild_config(int(guild_id))
                    correct_password = guild_config.get("claim_password", "").strip()
                    user_input = message.content.strip()
                    
                    if correct_password and user_input == correct_password:
                        reveal_user_key(message.author.id)
                        success_embed = discord.Embed(
                            title="<:arrow:1528280452232642570>   **Key Claimed Successfully!** <:tick:1528280519161417749>",
                            description=(
                                f"\n"
                                f"<:trick_supreme:1528280687126253648> **Here is your unique key** <:moderator:1528328618894295161>\n"
                                f"`{claim['key']}`\n\n"
                                f"<a:RedDiamond:1528280763932344422> **Keep it safe. You will not be able to get another key.** <a:Warning:1528328561361158245>"
                            ),
                            color=discord.Color.red()
                        )
                        await message.author.send(embed=success_embed)
                    else:
                        await message.author.send("❌ **Incorrect Password!** Please enter the correct password to reveal your key.")
                return

        # Auto-delete chat/messages in Key Claim channel that are not !claimkey
        if message.guild:
            guild_config = get_guild_config(message.guild.id)
            key_channel_id = guild_config.get("key_channel_id")
            if key_channel_id and str(message.channel.id) == str(key_channel_id):
                cleaned_content = message.content.strip()
                # Check if it starts with claimkey command or setkeychannel
                if not (cleaned_content.startswith("!claimkey") or cleaned_content.startswith("?setkeychannel") or cleaned_content.startswith("!setkeychannel")):
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    return

        is_staff = False
        guild_config = {}
        if message.guild:
            guild_config = get_guild_config(message.guild.id)
            staff_role_id = guild_config.get("staff_role_id")
            
            if staff_role_id:
                staff_role = message.guild.get_role(int(staff_role_id))
                if staff_role and staff_role in message.author.roles:
                    is_staff = True
            
            if message.author.guild_permissions.administrator:
                is_staff = True
                
            for role in message.author.roles:
                role_name = role.name.lower()
                if any(kw in role_name for kw in ["staff", "admin", "owner", "mod", "ㅤㅤㅤㅤㅤowner ᭡ ♡"]):
                    is_staff = True
                    break

        # Moderation Commands (?timeout and ?remove)
        if message.guild and message.author.guild_permissions.administrator and message.content.startswith("?"):
            msg_parts = message.content.strip().split()
            cmd = msg_parts[0].lower()
            
            if cmd == "?timeout":
                if len(message.mentions) == 0:
                    await message.channel.send("❌ Please mention the user you want to timeout. Example: `?timeout @member 5 days`")
                    return
                
                target_member = message.mentions[0]
                days = 1
                hours = 0
                minutes = 0
                seconds = 0
                
                if len(msg_parts) >= 4:
                    try:
                        amount = int(msg_parts[2])
                        unit = msg_parts[3].lower()
                        if "day" in unit:
                            days = amount
                        elif "hour" in unit:
                            days = 0
                            hours = amount
                        elif "minute" in unit or "min" in unit:
                            days = 0
                            minutes = amount
                        elif "second" in unit or "sec" in unit:
                            days = 0
                            seconds = amount
                    except ValueError:
                        pass
                
                import datetime
                delta = datetime.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
                
                if delta.days > 28:
                    delta = datetime.timedelta(days=28)
                    await message.channel.send("⚠️ Discord maximum timeout is 28 days. Automatically capped to 28 days.")
                
                try:
                    await target_member.timeout(delta, reason=f"Timed out by admin: {message.author}")
                    embed = discord.Embed(
                        title="🔇 Member Timed Out",
                        description=f"**{target_member.mention}** has been timed out for **{delta}**.",
                        color=discord.Color.orange()
                    )
                    embed.set_footer(text=f"Moderator: {message.author}")
                    await message.channel.send(embed=embed)
                except Exception as e:
                    await message.channel.send(f"❌ Failed to timeout user: {e}")
                return
                
            elif cmd == "?remove":
                if len(message.mentions) == 0:
                    await message.channel.send("❌ Please mention the user to remove timeout. Example: `?remove @member`")
                    return
                
                target_member = message.mentions[0]
                try:
                    await target_member.timeout(None, reason=f"Timeout removed by admin: {message.author}")
                    embed = discord.Embed(
                        title="🔊 Timeout Removed",
                        description=f"Timeout/mute has been removed for **{target_member.mention}**.",
                        color=discord.Color.green()
                    )
                    embed.set_footer(text=f"Moderator: {message.author}")
                    await message.channel.send(embed=embed)
                except Exception as e:
                    await message.channel.send(f"❌ Failed to remove timeout: {e}")
                return

            elif cmd == "?ban":
                if len(message.mentions) == 0:
                    await message.channel.send("❌ Please mention the user you want to ban. Example: `?ban @member`")
                    return
                
                target_member = message.mentions[0]
                try:
                    await target_member.ban(reason=f"Banned by admin: {message.author}")
                    embed = discord.Embed(
                        title="🔨 Member Banned",
                        description=f"**{target_member.mention}** has been banned from the server.",
                        color=discord.Color.red()
                    )
                    embed.set_footer(text=f"Moderator: {message.author}")
                    await message.channel.send(embed=embed)
                except Exception as e:
                    await message.channel.send(f"❌ Failed to ban user: {e}")
                return

            elif cmd == "?warnings":
                if len(message.mentions) == 0:
                    await message.channel.send("❌ Please mention the user to check warnings. Example: `?warnings @member`")
                    return
                
                target_member = message.mentions[0]
                warn_key = f"{message.guild.id}:{target_member.id}"
                warnings = self.automod_warnings.get(warn_key, 0)
                
                embed = discord.Embed(
                    title="⚠️ Member Warnings Details",
                    description=f"**{target_member.mention}** currently has **{warnings}** warnings.",
                    color=discord.Color.yellow()
                )
                await message.channel.send(embed=embed)
                return
                
            elif cmd == "?clearwarnings":
                if len(message.mentions) == 0:
                    await message.channel.send("❌ Please mention the user to clear warnings. Example: `?clearwarnings @member`")
                    return
                
                target_member = message.mentions[0]
                warn_key = f"{message.guild.id}:{target_member.id}"
                self.automod_warnings[warn_key] = 0
                
                embed = discord.Embed(
                    title="✅ Warnings Cleared",
                    description=f"Warnings for **{target_member.mention}** have been reset to 0.",
                    color=discord.Color.green()
                )
                embed.set_footer(text=f"Moderator: {message.author}")
                await message.channel.send(embed=embed)
                return

            elif cmd == "?clear":
                amount = 10
                if len(msg_parts) >= 2:
                    try:
                        amount = int(msg_parts[1])
                    except ValueError:
                        pass
                
                if amount > 100:
                    amount = 100
                elif amount < 1:
                    amount = 1
                
                try:
                    deleted = await message.channel.purge(limit=amount + 1)
                    success_msg = await message.channel.send(f"🧹 Cleared **{len(deleted) - 1}** messages.")
                    await asyncio.sleep(3)
                    await success_msg.delete()
                except Exception as e:
                    await message.channel.send(f"❌ Failed to clear messages: {e}")
                return

            elif cmd == "?help":
                embed = discord.Embed(
                    title="🛡️ Admin Moderation Commands Help",
                    description="List of all available custom prefix commands for Administrators:",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="🔇 `?timeout @member [duration]`",
                    value="Timeout/mute a member. Default is 1 day. Examples:\n• `?timeout @member 5 days`\n• `?timeout @member 30 minutes`\n*(Max limit is 28 days)*",
                    inline=False
                )
                embed.add_field(
                    name="🔊 `?remove @member`",
                    value="Remove active timeout/mute from a member.",
                    inline=False
                )
                embed.add_field(
                    name="🔨 `?ban @member`",
                    value="Permanently ban a member from the server.",
                    inline=False
                )
                embed.add_field(
                    name="⚠️ `?warnings @member`",
                    value="Check the warning count of a member.",
                    inline=False
                )
                embed.add_field(
                    name="✅ `?clearwarnings @member`",
                    value="Reset warning count of a member to 0.",
                    inline=False
                )
                embed.add_field(
                    name="🧹 `?clear [amount]`",
                    value="Delete a specified number of messages (default is 10, max is 100).",
                    inline=False
                )
                embed.add_field(
                    name="⚙️ `!setkeychannel <#channel>` / `!removekeychannel`",
                    value="Set or remove/disable the key distribution channel (Admin only).",
                    inline=False
                )
                embed.add_field(
                    name="📬 `!sendkey`",
                    value="Post the trial key claiming panel with the button (Admin only).",
                    inline=False
                )
                embed.add_field(
                    name="🔑 `!claimkey` or `/claimkey`",
                    value="Claim a free 1-Day key from the API. DMed to user (Limit: 1 per user).",
                    inline=False
                )
                embed.add_field(
                    name="🎛️ `!claimkey toggle` / `on` / `off`",
                    value="Enable/disable the free key claiming feature (Admin only).",
                    inline=False
                )
                embed.add_field(
                    name="👥 `!authorize user <@user>` / `list`",
                    value="Authorize a user to generate keys or list authorized users (Admin only).",
                    inline=False
                )
                embed.add_field(
                    name="🚫 `!unauthorize user <@user>`",
                    value="Remove key generation authorization from a user (Admin only).",
                    inline=False
                )
                embed.add_field(
                    name="⚡ `!genkey [duration]`",
                    value="Generate a key. Valid durations: `1`, `3`, `7`, `15`, `30` days (Authorized/Admin only).",
                    inline=False
                )
                embed.add_field(
                    name="🔄 `!resetclaim <@user>` / `all`",
                    value="Reset claim limit for a user or for everyone (Admin only).",
                    inline=False
                )
                embed.add_field(
                    name="ℹ️ `?help`",
                    value="Show this moderation and utility command list.",
                    inline=False
                )
                embed.set_footer(text=f"Requested by: {message.author}")
                
                try:
                    await message.channel.send(embed=embed)
                except:
                    pass
                return

        # Admin Anti-Spam / Anti-Nuke (Hacker/Compromise detection)
        if message.guild and is_staff:
            import time
            now = time.time()
            admin_key = f"{message.guild.id}:{message.author.id}"
            
            if admin_key not in self.admin_message_timestamps:
                self.admin_message_timestamps[admin_key] = []
                
            self.admin_message_timestamps[admin_key] = [t for t in self.admin_message_timestamps[admin_key] if now - t < 5]
            self.admin_message_timestamps[admin_key].append(now)
            
            if len(self.admin_message_timestamps[admin_key]) >= 5:
                self.admin_message_timestamps[admin_key] = []
                try:
                    await message.delete()
                except:
                    pass
                    
                try:
                    import datetime
                    await message.author.timeout(datetime.timedelta(days=28), reason="Anti-Nuke: Admin message spam detected (possible compromise)")
                    
                    nuke_embed = discord.Embed(
                        title="🚨 SECURITY THREAT BLOCK: ANTI-NUKE DETECTED",
                        description=(
                            f"Administrator/Staff {message.author.mention} was timed out for **28 days** (maximum limit).\n\n"
                            "**Reason:** Excessive message spam in 5 seconds (potential account compromise/nuke protection).\n"
                            "All administrator actions have been restricted."
                        ),
                        color=discord.Color.dark_red()
                    )
                    await message.channel.send(embed=nuke_embed)
                    
                    log_channel_id = guild_config.get("log_channel_id")
                    if log_channel_id:
                        log_channel = message.guild.get_channel(int(log_channel_id))
                        if log_channel:
                            log_embed = discord.Embed(
                                title="🚨 ANTI-NUKE ACTION LOGGED",
                                color=discord.Color.red()
                            )
                            log_embed.add_field(name="Admin Involved", value=f"{message.author} ({message.author.id})", inline=True)
                            log_embed.add_field(name="Action Taken", value="Muted / Timed Out for 28 Days", inline=True)
                            log_embed.add_field(name="Spam Count", value="5+ messages in 5 seconds", inline=True)
                            log_embed.timestamp = discord.utils.utcnow()
                            await log_channel.send(embed=log_embed)
                except Exception as e:
                    print(f"Anti-Nuke Timeout Failed: {e}")
                return

        # AutoMod Check
        if message.guild:
            print(f"[AutoMod Debug] Message author: {message.author} (ID: {message.author.id})", flush=True)
            print(f"[AutoMod Debug] is_staff: {is_staff}", flush=True)
            print(f"[AutoMod Debug] automod_enabled: {guild_config.get('automod_enabled')}", flush=True)
            print(f"[AutoMod Debug] automod_ai_enabled: {guild_config.get('automod_ai_enabled')}", flush=True)
            print(f"[AutoMod Debug] scaleway_client active: {scaleway_client is not None}", flush=True)
            print(f"[AutoMod Debug] Attachments count: {len(message.attachments)}", flush=True)

        if message.guild and not is_staff and guild_config.get("automod_enabled"):
            flagged = False
            reason = ""
            content_lower = message.content.lower()

            # 1. Block Links
            if guild_config.get("automod_block_links"):
                if any(x in content_lower for x in ["http://", "https://", "discord.gg/", "discord.com/invite"]):
                    flagged = True
                    reason = "Sending links"

            # 2. Block Bad Words (Exact Word Match using Regex to prevent false substring triggers like 'football', 'balance', etc.)
            if not flagged and guild_config.get("automod_block_badwords"):
                custom_badwords_str = guild_config.get("automod_badwords", "")
                if custom_badwords_str:
                    import re
                    badwords = [w.strip().lower() for w in custom_badwords_str.split(",") if w.strip()]
                    for word in badwords:
                        pattern = r'(?:\b|_)' + re.escape(word) + r'(?:\b|_)'
                        if re.search(pattern, content_lower):
                            flagged = True
                            reason = f"Using restricted word ({word})"
                            break

            # 3. AI Context-Aware Toxicity & Promotion Check (Scaleway DeepSeek Flash)
            if not flagged and guild_config.get("automod_ai_enabled") and scaleway_client:
                try:
                    print(f"[AutoMod Debug] Analyzing message intent with DeepSeek: {message.content}", flush=True)
                    sys_prompt = (
                        "You are an intelligent Discord automod context analyzer specializing in English, Bengali, and Banglish.\n"
                        "Your objective is to accurately determine whether a message should be DELETED/BLOCKED or ALLOWED based on real context and user intent.\n\n"
                        "❌ BLOCK (Output 'YES') ONLY if the message is:\n"
                        "1. Genuine severe abusive slangs, heavy vulgarity, extreme sexual insults, or direct targeted harassment/abuse.\n"
                        "2. Unauthorized self-promotion, advertising competing discord servers/shops/services, selling cheats, invite links, or scams.\n\n"
                        "✅ ALLOW (Output 'NO') if the message is:\n"
                        "1. Normal conversation, friendly chat, casual Banglish/Bengali or English chatting.\n"
                        "2. Customer support queries, asking for help, reporting bugs, complaining about services (e.g. 'website not working', 'free panel down', 'help me', 'how to buy', 'baje lagse', 'valo na').\n"
                        "3. Normal gaming discussions, emulator talk, gameplay comments.\n"
                        "4. Words that sound like slangs or contain common letters but are used in an innocent context (e.g. 'balance', 'football', '5 ta baje', 'global').\n\n"
                        "Decision rule: When in doubt or if it is casual friendly speech, DO NOT block. Respond with ONLY 'YES' or 'NO'."
                    )
                    completion = await scaleway_client.chat.completions.create(
                        model="deepseek-v4-flash-0731",
                        messages=[
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": message.content}
                        ],
                        max_tokens=32768,
                        temperature=0.0
                    )
                    choice_msg = completion.choices[0].message
                    raw_content = choice_msg.content or ""
                    if not raw_content and hasattr(choice_msg, "reasoning_content") and choice_msg.reasoning_content:
                        raw_content = choice_msg.reasoning_content
                    
                    ai_response = str(raw_content).strip().upper()
                    print(f"[AutoMod Debug] AI Toxicity Response: {ai_response}", flush=True)
                    
                    # Clean up response to get exact decision, removing thinking process if present
                    temp_tox = ai_response.upper()
                    if "</THINK>" in temp_tox:
                        temp_tox = temp_tox.split("</THINK>")[-1]
                    clean_tox = "".join(c for c in temp_tox if c.isalnum())
                    if clean_tox == "YES" or clean_tox.startswith("YES"):
                        flagged = True
                        reason = "AI Moderation (detected severe abuse, harassment, or unauthorized promotion)"
                except Exception as e:
                    print(f"AutoMod AI Error: {e}", flush=True)

            # 4. AI Multimodal Image Scam Checker
            if not flagged and guild_config.get("automod_ai_enabled") and message.attachments and scaleway_client:
                print(f"[AutoMod Debug] Found {len(message.attachments)} attachments. Scanning images...", flush=True)
                for attachment in message.attachments:
                    if attachment.content_type and attachment.content_type.startswith("image/"):
                        try:
                            print(f"[AutoMod Debug] Reading image: {attachment.filename}", flush=True)
                            img_data = await attachment.read()
                            
                            # MD5 Hash Checking for spam protection
                            import hashlib
                            img_hash = hashlib.md5(img_data).hexdigest()
                            
                            if img_hash in self.scam_hash_cache:
                                cached_result = self.scam_hash_cache[img_hash]
                                print(f"[AutoMod Debug] Hash cache hit for {attachment.filename}! Scam={cached_result}", flush=True)
                                if cached_result:
                                    flagged = True
                                    reason = "AI Scam Image Filter (cached scam match)"
                                    break
                                else:
                                    continue

                            prompt = (
                                "You are a strict Discord scam filter.\n"
                                "Analyze this image. You must ONLY output 'YES' if the image matches one of these 4 specific scam templates:\n"
                                "1. A fake Twitter/X post by 'MrBeast' promoting a cryptocurrency casino linked to 'mapewin.com' or giving away $5,600.\n"
                                "2. A dark-themed website dashboard under 'mapewin.com' showing an 'Activate Code for Bonus' section, specifically containing promo code 'BET' with a green 'Activate' button.\n"
                                "3. A website popup modal saying 'Withdrawal Success! Your Withdrawal of $5600.00 Was Successfully!' or similar on a dark gambling site.\n"
                                "4. A screenshot showing a mobile phone screen displaying a Trust Wallet or Binance transaction receiving '+5 600 USDT' (or '+5600 USDT') held in front of the 'Withdrawal Success!' web dashboard.\n\n"
                                "CRITICAL: If the image does not show one of these 4 exact templates, you MUST output 'NO'. Do NOT block general gaming screenshots, clean chat logs, codes, general photos, or desktop screens. They are 100% safe."
                            )
                            
                            ai_response = ""
                            try:
                                import base64
                                base64_image = base64.b64encode(img_data).decode("utf-8")
                                chat_completion = await scaleway_client.chat.completions.create(
                                    messages=[
                                        {
                                            "role": "user",
                                            "content": [
                                                {"type": "text", "text": prompt},
                                                {
                                                    "type": "image_url",
                                                    "image_url": {
                                                        "url": f"data:{attachment.content_type};base64,{base64_image}"
                                                    }
                                                }
                                            ]
                                        }
                                    ],
                                    model="deepseek-v4-flash-0731",
                                    max_tokens=32768
                                )
                                ai_response = chat_completion.choices[0].message.content.strip().upper()
                            except Exception as vision_err:
                                print(f"[AutoMod Image Debug] Scaleway vision note: {vision_err}")
                                ai_response = "NO"
                                
                            print(f"[AutoMod Debug] Image scanner AI Response: {ai_response}", flush=True)
                            
                            # Clean up response to avoid false substring matches, removing thinking process if present
                            temp_img = ai_response.upper()
                            if "</THINK>" in temp_img:
                                temp_img = temp_img.split("</THINK>")[-1]
                            clean_img = "".join(c for c in temp_img if c.isalnum())
                            
                            is_scam = clean_img == "YES" or clean_img.startswith("YES")
                            self.scam_hash_cache[img_hash] = is_scam
                            
                            if is_scam:
                                flagged = True
                                reason = "AI Scam Image Filter (detected scam/phishing promo)"
                                break
                        except Exception as e:
                            print(f"AutoMod Image AI Error: {e}", flush=True)

            if flagged:
                action = guild_config.get("automod_action", "delete_and_warn")
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass

                if action == "delete_and_warn":
                    warn_embed = discord.Embed(
                        title="⚠️ Auto-Moderator Warning",
                        description=f"Hey {message.author.mention}, your message was removed because: **{reason}**.\nPlease follow the server rules.",
                        color=discord.Color.red()
                    )
                    await message.channel.send(embed=warn_embed, delete_after=10)
                elif action == "timeout_3_warnings":
                    warn_key = f"{message.guild.id}:{message.author.id}"
                    warnings = self.automod_warnings.get(warn_key, 0) + 1
                    self.automod_warnings[warn_key] = warnings
                    
                    if warnings >= 3:
                        self.automod_warnings[warn_key] = 0
                        try:
                            import datetime
                            await message.author.timeout(datetime.timedelta(days=7), reason="AutoMod: 3 Warnings reached (Toxicity/Spam/Promotion)")
                            timeout_embed = discord.Embed(
                                title="🔇 Member Muted (Timeout)",
                                description=f"{message.author.mention} has been timed out for 7 days after receiving 3 warnings.",
                                color=discord.Color.dark_red()
                            )
                            await message.channel.send(embed=timeout_embed)
                        except Exception as e:
                            print(f"Failed to timeout user: {e}")
                    else:
                        warn_embed = discord.Embed(
                            title="⚠️ Auto-Moderator Warning",
                            description=f"Hey {message.author.mention}, your message was removed. Reason: **{reason}**.\n\n*Warnings: {warnings}/3* (At 3 warnings you will be muted for 7 days).",
                            color=discord.Color.red()
                        )
                        await message.channel.send(embed=warn_embed, delete_after=10)

                log_channel_id = guild_config.get("log_channel_id")
                if log_channel_id:
                    log_channel = message.guild.get_channel(int(log_channel_id))
                    if log_channel:
                        log_embed = discord.Embed(
                            title="🛡️ AutoMod Action Logged",
                            color=discord.Color.dark_orange()
                        )
                        log_embed.add_field(name="User", value=f"{message.author} ({message.author.id})", inline=True)
                        log_embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                        log_embed.add_field(name="Reason", value=reason, inline=True)
                        log_embed.add_field(name="Message Content", value=message.content[:1024] or "[Empty / Embedded]", inline=False)
                        log_embed.timestamp = discord.utils.utcnow()
                        try:
                            await log_channel.send(embed=log_embed)
                        except:
                            pass
                return

        # Check if message is in a ticket channel
        ticket_data = get_ticket(str(message.channel.id))
        if ticket_data:
            if is_staff and self.user in message.mentions:
                msg_content = message.content.lower()
                if any(word in msg_content for word in ["stop", "pause", "disable", "off"]):
                    ticket_data["ai_disabled"] = True
                    save_ticket(str(message.channel.id), ticket_data)
                    embed = discord.Embed(
                        title="🤖 AI Support Paused", 
                        description="AI Support has been disabled for this ticket. Staff will handle it manually.", 
                        color=discord.Color.red()
                    )
                    await message.channel.send(embed=embed)
                    return
                elif any(word in msg_content for word in ["start", "resume", "enable", "on"]):
                    ticket_data["ai_disabled"] = False
                    save_ticket(str(message.channel.id), ticket_data)
                    embed = discord.Embed(
                        title="🤖 AI Support Active", 
                        description="AI Support is now active for this ticket.", 
                        color=discord.Color.green()
                    )
                    await message.channel.send(embed=embed)
                    return

            if is_staff and message.author.id != ticket_data["user_id"]:
                # Forward to user's DM
                user_id = ticket_data["user_id"]
                user = self.get_user(user_id) or await self.fetch_user(user_id)
                if user:
                    try:
                        embed = discord.Embed(
                            title=f"New Staff Reply in #{message.channel.name}",
                            description=message.content,
                            color=discord.Color.blue()
                        )
                        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url if message.author.display_avatar else None)
                        embed.set_footer(text="Note: Reply back in the ticket channel, not here.")
                        
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(label="Go to Ticket", url=message.channel.jump_url, style=discord.ButtonStyle.link))
                        try:
                            await user.send(embed=embed, view=view)
                        except discord.Forbidden:
                            pass
                    except Exception as e:
                        print(f"Failed to forward to user: {e}")
                        
            if message.author.bot:
                return

            content_lower = message.content.lower()
            
            # 1. Custom Auto-Responders
            custom_responses = guild_config.get("custom_responses", [])
            matched_custom = False
            
            if not is_staff:
                for cr in custom_responses:
                    kws = [k.strip().lower() for k in cr["keywords"].split(",")]
                    if any(kw in content_lower for kw in kws):
                        embed = discord.Embed(title="🔔 Auto-Reply", description=cr["reply"], color=discord.Color.gold())
                        await message.channel.send(embed=embed)
                        matched_custom = True
                        break
                    
            if is_staff:
                pass # Skip AI and responders for staff
            elif matched_custom:
                pass # Skip AI and hardcoded
            
            elif any(word in content_lower for word in ["binance", "pay id"]):
                binance_id = guild_config.get("binance_id") or "1247871004"
                embed = discord.Embed(title="🟡 Binance Payment", description=f"Please send your payment to the following Binance Pay ID:\n\n**`{binance_id}`**\n\n*Kindly send a screenshot after the transaction is complete.*", color=discord.Color.gold())
                await message.channel.send(embed=embed)
                
            elif any(word in content_lower for word in ["bkash", "bikash"]):
                bkash_number = guild_config.get("bkash_number") or "01858182283"
                embed = discord.Embed(title="🦅 bKash Payment", description=f"Please **Send Money** to this Personal bKash number:\n\n**`{bkash_number}`**\n\n*(Note: This is a personal bKash number, you MUST use the Send Money option)*\n\n*Please send a screenshot after successful payment.*", color=0xE2136E) # bKash Pink
                await message.channel.send(embed=embed)

            elif any(word in content_lower for word in ["crypto", "btc", "bitcoin", "usdt", "ltc", "pay"]):
                crypto_addr = guild_config.get("crypto_address") or "bc1qfmm97pfel5c02rcmges5vapwsu7k0ut52js8fd"
                embed = discord.Embed(title="🪙 Crypto Payment (BTC)", description=f"Please send the exact amount to the following BTC address:\n\n**`{crypto_addr}`**\n\n*Send a screenshot of the transaction hash after payment.*", color=discord.Color.blurple())
                embed.set_image(url=f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={crypto_addr}")
                await message.channel.send(embed=embed)
                
            elif any(word in content_lower for word in ["paypal", "cashapp", "skrill", "international", "international client", "other country"]):
                embed = discord.Embed(title="🌍 International Payment", description="Please wait a moment! A staff member will be here shortly to guide you through our international payment options.", color=discord.Color.teal())
                await message.channel.send(embed=embed)
                
            # 2. Premium AI Agent (Scaleway DeepSeek)
            elif not ticket_data.get("ai_disabled") and not message.author.bot and scaleway_client:
                async with message.channel.typing():
                    try:
                        history_msgs = [msg async for msg in message.channel.history(limit=10, oldest_first=False)]
                        history_msgs.reverse()
                        product_knowledge = """
# BASIC PANEL ALL SERVER SAFE!!!
Functions: AIMBOT EXTERNAL, AIMBOT ON/OFF.
Locations: CHAMS MENU, STREAM MODE.
Note: 100% SAFE FOR MAIN ID, FULLY EXTERNAL PANEL.
Price: 1 MONTH = 700 INR / 8$, PERMANENT = 2000 INR / 24$.

# AXC PREMIUM PANEL V3.2
Functions: AIMBOT HEAD, ON/OFF (IN GAME), SNIPER SCOPE/MACRO/AIM/LOCATIONS, AWM/M82B SWITCH, SPEED HACK, WALL HACK, GLITCH FIRE, CAMERA RIGHT, FAST LANDING, VISION 7X.
Locations: CHAMS MENU, RED/BLUE CHAMS, ESP LINE/BOX/FILL BOX/SKELETON/INFO.
Settings: STREAM MODE, BLOCK INTERNET, RESET GUEST.
Mobile Control: START SERVER, ONE TIME SETUP, FULL CONTROL FROM PHONE.
Note: 100% SAFE FOR MAIN ID, FULLY BRUTAL AND EXTERNAL.
Price: 7 DAYS = 400 INR / 5$, 15 DAYS = 800 INR / 10$, 1 MONTH = 1000 INR / 12$, PERMANENT = 3000 INR / 35$.

# Premium UID Emulator Bypass
Features: Same applying process, India + All other servers supported, 101% Safe & Stable.
Price: 30 Days = $8 / ₹800 / 800 BDT, Permanent = $25 / ₹2500 / 2500 BDT.
Reseller Features: Full API Dashboard Access, full OBB + Custom EXE Service, Web Access or Discord Bot Setup, Seller/Reseller Support.
Servers Supported: India, Bangladesh, Pakistan, Brazil, US, EU, Russia, Indonesia, Malaysia, Singapore, Vietnam, Mexico, Taiwan, Thailand, Philippines, Korea, Japan, Australia, MENA, Africa, NZ, Canada, Spain, KSA, UAE, Italy, France, Germany, Netherlands, Sweden, Norway, Finland, Poland, Turkey, UK, Argentina, Chile, Colombia, Peru, Venezuela, Ukraine, Belgium, Czech, Hungary.
"""
                        system_prompt = (
                            "You are the official Support AI Agent for 'Anik X Cheats'. Your job is to assist the user in their ticket.\n"
                            "IMPORTANT Guidelines:\n"
                            "1. Always reply in the exact language the user is speaking (Bengali, Banglish, Hindi, or English).\n"
                            "2. Be concise, friendly, and helpful.\n"
                            "3. If they ask how to pay, tell them to type 'bkash', 'binance', or 'crypto' to get payment details immediately.\n"
                            f"Product Info:\n{product_knowledge}"
                        )
                        
                        ai_msgs = [{"role": "system", "content": system_prompt}]
                        for m in history_msgs:
                            role = "assistant" if m.author == self.user else "user"
                            ai_msgs.append({"role": role, "content": m.content})
                            
                        chat_completion = await scaleway_client.chat.completions.create(
                            messages=ai_msgs,
                            model="deepseek-v4-flash-0731",
                            max_tokens=32768,
                            temperature=0.3
                        )
                        choice_msg = chat_completion.choices[0].message
                        response_text = choice_msg.content or ""
                        if not response_text and hasattr(choice_msg, "reasoning_content") and choice_msg.reasoning_content:
                            response_text = choice_msg.reasoning_content
                            
                        if response_text:
                            if "</think>" in response_text:
                                response_text = response_text.split("</think>")[-1].strip()
                            await message.channel.send(response_text)
                    except Exception as e:
                        print(f"Ticket AI Error: {e}")

        await self.process_commands(message)

bot = TicketBot()

# ---------- Ticket Creation ----------
async def create_ticket(interaction: discord.Interaction, ticket_type: str):
    guild = interaction.guild
    user = interaction.user
    guild_config = get_guild_config(guild.id)

    staff_role_id = guild_config.get("staff_role_id")
    if not staff_role_id:
        return await interaction.response.send_message(
            "Staff role is not set for this server. Use /set_staff_role first.",
            ephemeral=True
        )

    staff_role = guild.get_role(int(staff_role_id))
    if staff_role is None:
        return await interaction.response.send_message(
            "Staff role not found.",
            ephemeral=True
        )

    guild_config["ticket_count"] += 1
    save_guild_config(guild.id, guild_config)

    channel_name = f"{ticket_type}-ticket-{guild_config['ticket_count']}"

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, use_application_commands=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, use_application_commands=False),
        staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, use_application_commands=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, use_application_commands=True),
    }

    try:
        channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites
        )
    except discord.HTTPException as e:
        return await interaction.response.send_message(
            f"Could not create ticket channel: {e}",
            ephemeral=True
        )

    # Save ticket info in DB
    save_ticket(str(channel.id), {
        "type": ticket_type,
        "user_id": user.id,
        "guild_id": guild.id,
        "claimed": False,
        "claimed_by": None
    })

    # Define custom detailed embeds for each ticket type
    ticket_details = {
        "basic-panel": {
            "title": "💻 Basic-Panel Support & Purchase",
            "color": 0x3498db,  # Blue
            "prices": "```\n1 MONTH = 700 INR / BDT / 8$\nPERMANENT = 2000 INR / BDT / 24$\n```",
            "features": "• 100% Safe for Main ID\n• Fully External Panel\n• Aimbot External (ON/OFF)\n• Chams Menu, Stream Mode"
        },
        "premium-panel": {
            "title": "👑 Premium-Panel Support & Purchase",
            "color": 0xf1c40f,  # Gold
            "prices": "```\n7 DAYS = 400 INR / BDT / 5$\n15 DAYS = 800 INR / BDT / 10$\n1 MONTH = 1000 INR / BDT / 12$\nPERMANENT = 3000 INR / BDT / 35$\n```",
            "features": (
                "• 100% Safe for Main ID (Fully Brutal & External)\n"
                "• Aimbot Head (ON/OFF in-game)\n"
                "• Sniper Scope/Macro/Aim/Locations\n"
                "• AWM/M82B Switch\n"
                "• Speed Hack & Wall Hack\n"
                "• Glitch Fire & Camera Right\n"
                "• Fast Landing & Vision 7X\n"
                "• Red/Blue Chams & ESP (Line/Box/Skeleton)\n"
                "• Stream Mode, Block Internet, Reset Guest\n"
                "• Mobile Control (phone setup/control)"
            )
        },
        "uid-bypass": {
            "title": "⚡ Uid-Bypass Support & Purchase",
            "color": 0xe74c3c,  # Red
            "prices": "```\n7 DAYS = 400 INR / BDT / 5$\n30 DAYS = 800 INR / BDT / 8$\nPERMANENT = 2000 INR / BDT / 25$\n```",
            "features": "• 101% Safe & Stable (Main ID)\n• India + All other servers supported\n• Full API Dashboard Access (Resellers)\n• Custom OBB + Custom EXE Service"
        },
        "source-code": {
            "title": "🧾 Source Code Purchase",
            "color": 0x9b59b6,  # Purple
            "prices": "• Please wait for the Owner to give a custom quote.",
            "features": "• Complete Loader & Cheat Source Code\n• Developer assistance for setup"
        },
        "help": {
            "title": "🎧 General Help & Support",
            "color": 0x2ecc71,  # Green
            "prices": "• Support is completely free!",
            "features": "• Ask your questions / describe the bug\n• Staff will assist you shortly"
        }
    }

    banner_url = guild_config.get("ticket_banner")
    logo_url = guild_config.get("ticket_logo")

    if ticket_type == "basic-panel":
        embed = discord.Embed(
            title="BASIC PANEL ALL SERVER SAFE!!! <a:emoji_46:1528280811038834799>",
            description=(
                f"Welcome {user.mention}! Thank you for creating a ticket. Our staff will assist you shortly.\n\n"
                "╔═══════════════════════════════════╗\n"
                "   **BASIC PANEL ALL SERVER SAFE** <a:emoji_46:1528280811038834799>\n"
                "╚═══════════════════════════════════╝\n\n"
                "<:an:1528280435572998145>   **AIM FUNCTIONS :**\n"
                "```[+] AIMBOT EXTERNAL \n"
                "[+] AIMBOT ON / OFF\n"
                "```\n"
                "<:downvote:1528328454460669952>  **LOCATION MENU :**\n"
                "```[+] CHAMS MENU\n"
                "[+] STREAM MODE\n"
                "```\n"
                "<a:fire2:1528328548295643178>  **NOTE :**\n"
                "```ALL SERVER SAFE\n"
                "100% SAFE FOR MAIN ID\n"
                "FULLY EXTERNAL PANEL```\n"
                "<:price:1528280545744654506>  **PRICE LIST :**\n"
                "```1 MONTH   = 700 INR / 8$\n"
                "PERMANENT = 2000 INR / 24$```\n\n"
                "💳 **PAYMENT CHANNELS**\n"
                "We accept bKash, Binance, and Crypto. Type **`bkash`**, **`binance`**, or **`crypto`** to get payment details instantly!"
            ),
            color=0x3498db
        )
    elif ticket_type == "premium-panel":
        embed = discord.Embed(
            title="AXC PREMIUM PANEL V3 <a:fire2:1528328548295643178>",
            description=(
                f"Welcome {user.mention}! Thank you for creating a ticket. Our staff will assist you shortly.\n\n"
                "╔═══════════════════════════════════╗\n"
                "   **AXC PREMIUM PANEL V3** <a:fire2:1528328548295643178>\n"
                "╚═══════════════════════════════════╝\n\n"
                "<:an:1528280435572998145>  **FUNCTIONS :**\n"
                "```[+] AIMBOT HEAD\n"
                "[+] AIMBOT ON / OFF ( IN GAME )\n"
                "[+] SNIPER SCOPE \n"
                "[+] SNIPER MACRO\n"
                "[+] AWM SWITCH\n"
                "[+] M82B SWITCH\n"
                "[+] SNIPER AIM\n"
                "[+] SNIPER LOCATIONS\n"
                "[+] GLITCH FIRE\n"
                "[+] CAMERA RIGHT\n"
                "[+] FAST LANDING```\n"
                "<a:Ak47:1528280754633572372>  **LOCATION MENU :**\n"
                "```[+] CHAMS MENU\n"
                "[+] RED CHAMS\n"
                "[+] BLUE CHAMS\n"
                "[+] ESP LINE\n"
                "[+] ESP BOX\n"
                "[+] ESP FILL BOX\n"
                "[+] ESP SKELETEON\n"
                "[+] ESP INFO```\n"
                "<:price:1528280545744654506>   **PRICE LIST :**\n"
                "```7 DAYS    = 400 INR / 5$\n"
                "15 DAYS   = 800 INR / 10$\n"
                "1 MONTH   = 1000 INR / 12$\n"
                "PERMANENT = 3000 INR / 35$```\n\n"
                "💳 **PAYMENT CHANNELS**\n"
                "We accept bKash, Binance, and Crypto. Type **`bkash`**, **`binance`**, or **`crypto`** to get payment details instantly!"
            ),
            color=0xf1c40f
        )
    elif ticket_type == "uid-bypass":
        embed = discord.Embed(
            title="<:an:1528280435572998145> UID BYPASS | SAFE ALL SERVER",
            description=(
                f"Welcome {user.mention}! Thank you for creating a ticket. Our staff will assist you shortly.\n\n"
                "╔═══════════════════════════════════╗\n"
                "   **UID BYPASS | SAFE ALL SERVER** <:an:1528280435572998145>\n"
                "╚═══════════════════════════════════╝\n\n"
                "<a:Ak47:1528280754633572372>  Easy Setup & Full Support\n"
                "<a:Ak47:1528280754633572372>  Work On All Emulator \n"
                "<a:Ak47:1528280754633572372>  Anti-Lags\n\n"
                "<:price:1528280545744654506>  **PRICE LIST** \n"
                "```1 Month  — $12 | ₹1,020\n"
                "Lifetime — $30 | ₹3,100```\n"
                "**UID BYPASS API** \n"
                "<:price:1528280545744654506> **PRICE LIST** \n"
                "```$60 — Unlimited UID | ₹6,500```\n\n"
                "💳 **PAYMENT CHANNELS**\n"
                "We accept bKash, Binance, and Crypto. Type **`bkash`**, **`binance`**, or **`crypto`** to get payment details instantly!"
            ),
            color=0xe74c3c
        )
    else:
        details = ticket_details.get(ticket_type, {
            "title": f"{ticket_type.capitalize()} Ticket",
            "color": 0x2b2d31,
            "prices": "Custom ticket type.",
            "features": "Please wait for support."
        })

        embed = discord.Embed(
            title=details["title"],
            description=f"Welcome {user.mention}! Thank you for creating a ticket. Our staff will assist you shortly.",
            color=details["color"]
        )
        embed.add_field(name="💰 PRICE LIST", value=details["prices"], inline=False)
        embed.add_field(name="✨ FEATURES", value=details["features"], inline=False)
        embed.add_field(
            name="💳 PAYMENT CHANNELS", 
            value="We accept bKash, Binance, and Crypto. Type **`bkash`**, **`binance`**, or **`crypto`** to get payment details instantly!", 
            inline=False
        )

    banner_url = guild_config.get("ticket_banner")
    if not banner_url or banner_url.strip() == "":
        banner_url = "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif"
        
    logo_url = guild_config.get("ticket_logo")
    if not logo_url or logo_url.strip() == "" or "e62e3cc75f1747e0824ed1ee0dda51a9.webp" in logo_url:
        logo_url = "https://media.discordapp.net/attachments/1448757915035897886/1532872634058936500/axc.gif?ex=6a6e6e63&is=6a6d1ce3&hm=6cce736ff46f16b4ece45fc226890625eb79e4debced09a22f200bda093ffa49&=&width=350&height=350"

    embed.set_thumbnail(url=logo_url.strip())
    embed.set_image(url=banner_url.strip())

    embed.set_footer(text="Anik X Cheats • Ticket System", icon_url=logo_url.strip())
    embed.timestamp = discord.utils.utcnow()

    await channel.send(
        content=f"👋 {user.mention} **Welcome to your support ticket!**",
        embed=embed,
        view=TicketActionView(staff_role_id=int(staff_role_id))
    )

    await interaction.response.send_message(
        f"Ticket created: {channel.mention}",
        ephemeral=True
    )

    if scaleway_client:
        async def send_ai_greeting():
            await asyncio.sleep(1)
            async with channel.typing():
                try:
                    sys_prompt = (
                        f"You are the friendly AI Support Agent for 'Anik X Cheats'.\n"
                        f"The user '{user.display_name}' just opened a '{ticket_type}' ticket.\n"
                        f"Send a warm, welcoming, and helpful greeting in the channel. Mention that staff and AI are here to help.\n"
                        f"Ask how you can assist them today (purchase, panel questions, emulator setup, or key help).\n"
                        f"Keep it short (2-3 sentences), enthusiastic, and use emojis."
                    )
                    completion = await scaleway_client.chat.completions.create(
                        messages=[{"role": "system", "content": sys_prompt}],
                        model="deepseek-v4-flash-0731",
                        max_tokens=32768,
                        temperature=0.4
                    )
                    choice_msg = completion.choices[0].message
                    response_text = choice_msg.content or ""
                    if not response_text and hasattr(choice_msg, "reasoning_content") and choice_msg.reasoning_content:
                        response_text = choice_msg.reasoning_content
                        
                    if response_text:
                        if "</think>" in response_text:
                            response_text = response_text.split("</think>")[-1].strip()
                        await channel.send(f"🤖 **AI Support:** {response_text}")
                except Exception as e:
                    print(f"AI Greeting Error: {e}")
                    
        bot.loop.create_task(send_ai_greeting())

# ---------- Views ----------
class TrialKeyClaimButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="GET 1 DAYS TRIAL ACCESS",
        style=discord.ButtonStyle.green,
        emoji="<:emoji_74:1528302510207664269>",
        custom_id="get_trial_key_button"
    )
    async def get_trial_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_config = get_guild_config(interaction.guild.id)
        
        # Check if free claiming is disabled
        if not guild_config.get("claimkey_enabled", True):
            return await interaction.response.send_message("❌ Free key claiming is currently disabled by administrators.", ephemeral=True)

        # Check if already claimed
        if has_user_claimed(interaction.user.id):
            return await interaction.response.send_message("❌ You have already claimed a free key! Limit: 1 per user.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # Test DM first before calling API
        try:
            test_embed = discord.Embed(description="Generating your license key...", color=discord.Color.blue())
            test_msg = await interaction.user.send(embed=test_embed)
        except discord.Forbidden:
            return await interaction.followup.send(f"❌ {interaction.user.mention}, I couldn't send you a Direct Message. Please open your DMs and try again.", ephemeral=True)

        # Generate key from API (1 Day)
        generated_key = await call_key_generator_api(1)
        if not generated_key:
            try:
                await test_msg.delete()
            except Exception:
                pass
            return await interaction.followup.send("❌ Failed to generate key. Please contact staff or try again later.", ephemeral=True)

        # Success! Save claim to DB and edit DM message
        mark_user_claimed(interaction.user.id, generated_key, interaction.guild.id, revealed=True)
        success_embed = discord.Embed(
            title="<:tik:1528280512169246894>  **YOUR SECURE ACCESS**",
            description=(
                f"**Your personal credentials are below. Never share it.**\n"
                f"<:trick_supreme:1528280687126253648>  **LICENSE KEY — Tap to copy**\n"
                f"```\n"
                f"{generated_key}```\n\n"
                f"<:arrow:1528280452232642570>  **DOWNLOAD BYPASS EXE**\n"
                f"[Click here to download Bypass Emulator](https://www.dropbox.com/scl/fi/u9czoect0rv5w2o9v0h11/AXC-LIB-BYPASS.exe?rlkey=wjwke1emn688j44lv7tj6wxvv&st=sh84trcd&dl=0)\n"
                f"<:arrow:1528280452232642570>  **DOWNLOAD FREEFIRE APK**\n"
                f"[Click here to download Free Fire APK](https://www.dropbox.com/scl/fi/vqhivuvpvfxhjw0ub3p2v/FREE-FIRE-OB54-V7A.xapk?rlkey=cmjfz7cyr8pd84x0mpedt1i3u&st=35uogn0d&dl=0)\n"
                f"<a:Warning:1528328561361158245>  **IMPORTANT**\n"
                f"**This LICENSE KEY will only work on the EXE given above.**"
            ),
            color=discord.Color.red()
        )
        await test_msg.edit(embed=success_embed)
        await interaction.followup.send("📬 I have DMed you your license key!", ephemeral=True)

class TicketTypeSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())

class TicketTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Basic-Panel", value="basic-panel", description="Create a Basic-Panel ticket", emoji="💻"),
            discord.SelectOption(label="Premium-Panel", value="premium-panel", description="Create a Premium-Panel ticket", emoji="👑"),
            discord.SelectOption(label="Uid-Bypass", value="uid-bypass", description="Create a Uid-Bypass ticket", emoji="⚡"),
            discord.SelectOption(label="Help", value="help", description="Create a help ticket", emoji="🎧"),
            discord.SelectOption(label="Buy Source Code", value="source-code", description="Create a Source Code ticket", emoji="🧾"),
        ]
        super().__init__(
            placeholder="Select a category",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_type_select"
        )

    async def callback(self, interaction: discord.Interaction):
        ticket_type = self.values[0]
        await create_ticket(interaction, ticket_type)

class TicketActionView(discord.ui.View):
    def __init__(self, staff_role_id: int):
        super().__init__(timeout=None)
        self.staff_role_id = staff_role_id

    def is_staff(self, interaction: discord.Interaction) -> bool:
        staff_role = interaction.guild.get_role(self.staff_role_id)
        return (
            interaction.user.guild_permissions.administrator
            or (staff_role in interaction.user.roles if staff_role else False)
        )

    @discord.ui.button(
        label="Claim Ticket",
        style=discord.ButtonStyle.primary,
        emoji="📌",
        custom_id="claim_ticket"
    )
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction):
            return await interaction.response.send_message(
                "Only staff or admins can claim tickets.",
                ephemeral=True
            )

        ticket_data = get_ticket(str(interaction.channel.id))
        if ticket_data is None:
            return await interaction.response.send_message(
                "Ticket data not found.",
                ephemeral=True
            )

        if ticket_data["claimed"]:
            return await interaction.response.send_message(
                "This ticket is already claimed.",
                ephemeral=True
            )

        ticket_data["claimed"] = True
        ticket_data["claimed_by"] = interaction.user.id
        save_ticket(str(interaction.channel.id), ticket_data)

        button.disabled = True
        button.label = f"Claimed by {interaction.user.name}"

        await interaction.response.edit_message(view=self)
        await interaction.channel.send(
            f"📌 Ticket claimed by {interaction.user.mention}"
        )

        user_id = ticket_data["user_id"]
        user = interaction.client.get_user(user_id)
        if not user:
            try:
                user = await interaction.client.fetch_user(user_id)
            except:
                pass
                
        if user:
            try:
                embed = discord.Embed(
                    title="📌 Ticket Claimed",
                    description=f"Your ticket **#{interaction.channel.name}** has been claimed by {interaction.user.mention}.",
                    color=discord.Color.green()
                )
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Go to Ticket", url=interaction.channel.jump_url, style=discord.ButtonStyle.link))
                await user.send(embed=embed, view=view)
            except:
                pass

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="close_ticket"
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction):
            return await interaction.response.send_message(
                "Only staff or admins can close tickets.",
                ephemeral=True
            )

        ticket_data = get_ticket(str(interaction.channel.id))
        user_id = ticket_data["user_id"] if ticket_data else None
        user = None
        if user_id:
            user = bot.get_user(user_id) or await bot.fetch_user(user_id)

        await interaction.response.send_message(
            "Generating transcript and closing ticket..."
        )
        
        # Transcript Generation & Saving
        import uuid
        import datetime
        from db import save_transcript
        
        transcript_id = str(uuid.uuid4())
        messages = [message async for message in interaction.channel.history(limit=None, oldest_first=True)]
        
        messages_data = []
        
        # Premium styled offline HTML header
        html_header = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Transcript: #{interaction.channel.name}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #1e1f22;
            --bg-chat: #313338;
            --bg-sidebar: #2b2d31;
            --text-main: #dbdee1;
            --text-muted: #949ba4;
            --text-link: #00a8fc;
            --header-primary: #f2f3f5;
            --border: #3f4147;
            --accent: #5865f2;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-base);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            background-color: var(--bg-sidebar);
            border-bottom: 1px solid var(--border);
            padding: 20px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header-left h1 {{
            color: var(--header-primary);
            font-size: 1.5rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .header-left h1 span {{ color: var(--text-muted); font-weight: 400; }}
        .header-left p {{ color: var(--text-muted); font-size: 0.85rem; margin-top: 4px; }}
        .meta-badge {{
            background: rgba(88, 101, 242, 0.1);
            color: var(--accent);
            border: 1px solid rgba(88, 101, 242, 0.2);
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: 600;
        }}
        .chat-container {{
            flex: 1;
            background-color: var(--bg-chat);
            max-width: 1000px;
            width: 100%;
            margin: 30px auto;
            border-radius: 8px;
            border: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(0,0,0,0.2);
        }}
        .chat-messages {{ padding: 24px; overflow-y: auto; flex: 1; }}
        .message-group {{ display: flex; gap: 16px; margin-bottom: 20px; padding: 4px 0; }}
        .avatar {{ width: 40px; height: 40px; border-radius: 50%; object-fit: cover; flex-shrink: 0; background-color: #2b2d31; }}
        .message-content {{ flex: 1; }}
        .message-header {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }}
        .author-name {{ color: var(--header-primary); font-weight: 600; font-size: 0.95rem; }}
        .message-time {{ color: var(--text-muted); font-size: 0.75rem; }}
        .message-text {{ font-size: 0.925rem; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }}
        .attachment {{ margin-top: 8px; max-width: 400px; border-radius: 4px; overflow: hidden; border: 1px solid var(--border); }}
        .attachment img {{ width: 100%; display: block; }}
        .footer {{ text-align: center; padding: 20px; color: var(--text-muted); font-size: 0.8rem; border-top: 1px solid var(--border); background-color: var(--bg-sidebar); }}
    </style>
</head>
<body>
    <header class="header">
        <div class="header-left">
            <h1>#{interaction.channel.name} <span>in {interaction.guild.name}</span></h1>
            <p>Opener: {user.name if user else "Unknown"} | Closed by: {interaction.user.display_name} on {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC</p>
        </div>
        <div class="meta-badge">Offline Ticket Transcript</div>
    </header>
    <div class="chat-container">
        <div class="chat-messages">
"""
        
        html_messages = ""
        for m in messages:
            avatar_url = str(m.author.display_avatar.url) if m.author.avatar else "https://cdn.discordapp.com/embed/avatars/0.png"
            time_str = m.created_at.strftime("%I:%M %p - %b %d, %Y")
            
            attach_html = ""
            for a in m.attachments:
                ext = a.filename.split('.')[-1].lower() if '.' in a.filename else ''
                if ext in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
                    attach_html += f'<div class="attachment"><img src="{a.url}" alt="Attachment"></div>'
                else:
                    attach_html += f'<div class="attachment"><a href="{a.url}" target="_blank" style="color: var(--text-link); text-decoration: none;">📎 {a.filename}</a></div>'
            
            html_messages += f"""
            <div class="message-group">
                <img class="avatar" src="{avatar_url}" alt="Avatar">
                <div class="message-content">
                    <div class="message-header">
                        <span class="author-name">{m.author.display_name}</span>
                        <span class="message-time">{time_str}</span>
                    </div>
                    <div class="message-text">{m.content}</div>
                    {attach_html}
                </div>
            </div>
            """
            
            messages_data.append({
                "author": m.author.name,
                "display_name": m.author.display_name,
                "avatar": avatar_url,
                "time": time_str,
                "content": m.content,
                "attachments": [a.url for a in m.attachments]
            })
            
        html_footer = """
        </div>
        <footer class="footer">
            &copy; 2026 Anik X Cheats. Ticket transcript powered by VΞLTRIX.
        </footer>
    </div>
</body>
</html>
"""
        html_content = html_header + html_messages + html_footer
        
        transcript_doc = {
            "_id": transcript_id,
            "guild_id": interaction.guild.id,
            "guild_name": interaction.guild.name,
            "channel_name": interaction.channel.name,
            "closed_by": interaction.user.display_name,
            "closed_at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "opener_id": user_id,
            "opener_name": user.name if user else "Unknown",
            "messages": messages_data
        }
        save_transcript(transcript_id, transcript_doc)
        
        # Base Web URL extraction
        redirect_uri = os.getenv("DISCORD_REDIRECT_URI", "http://127.0.0.1:5000/callback")
        base_url = "/".join(redirect_uri.split("/")[:3])
        transcript_url = f"{base_url}/transcript/{transcript_id}"
        
        # Send Web URL to User's DM
        if user:
            try:
                dm_embed = discord.Embed(
                    title="🔒 Ticket Closed",
                    description=(
                        f"Your ticket **#{interaction.channel.name}** in **{interaction.guild.name}** has been closed.\n\n"
                        f"🌐 **Online Transcript:** [Click here to view chat]({transcript_url})"
                    ),
                    color=discord.Color.red()
                )
                await user.send(embed=dm_embed)
            except Exception as dm_err:
                print(f"Failed to DM user: {dm_err}")
                
        # Send to Transcripts Channel
        guild_config = get_guild_config(interaction.guild.id)
        transcript_channel_id = guild_config.get("transcripts_channel_id")
        if transcript_channel_id:
            t_channel = bot.get_channel(int(transcript_channel_id))
            if t_channel:
                try:
                    chan_embed = discord.Embed(
                        title="🔒 Ticket Closed & Archived",
                        description=(
                            f"Ticket **#{interaction.channel.name}** has been closed by {interaction.user.mention}.\n\n"
                            f"👤 **Opened By:** {user.mention if user else 'Unknown'}\n"
                            f"🌐 **Online Web View:** [Click here to view transcript]({transcript_url})"
                        ),
                        color=discord.Color.dark_red()
                    )
                    file_backup = discord.File(fp=io.BytesIO(html_content.encode('utf-8')), filename=f"transcript-{interaction.channel.name}.html")
                    await t_channel.send(embed=chan_embed, file=file_backup)
                except Exception as chan_err:
                    print(f"Failed to send to transcripts channel: {chan_err}")

        if ticket_data:
            delete_ticket(str(interaction.channel.id))

        await asyncio.sleep(3)
        await interaction.channel.delete()

# ---------- Slash Commands ----------
@bot.tree.command(name="authorize_guild", description="Authorize a Discord server to use the bot's commands (Owner only).")
@app_commands.describe(guild_id="The ID of the guild/server to authorize")
async def authorize_guild(interaction: discord.Interaction, guild_id: str):
    is_owner = False
    try:
        is_owner = await interaction.client.is_owner(interaction.user)
    except Exception:
        pass
    owner_id_env = os.getenv("OWNER_ID")
    if owner_id_env and str(interaction.user.id) == str(owner_id_env):
        is_owner = True
        
    if not is_owner:
        return await interaction.response.send_message(
            "❌ Only the bot owner can authorize servers.",
            ephemeral=True
        )
        
    try:
        g_id = int(guild_id)
    except ValueError:
        return await interaction.response.send_message(
            "❌ Invalid Guild ID. Please provide a numeric ID.",
            ephemeral=True
        )
        
    config = get_guild_config(g_id)
    config["authorized"] = True
    save_guild_config(g_id, config)
    
    guild_name = "Unknown Server"
    guild_obj = interaction.client.get_guild(g_id)
    if guild_obj:
        guild_name = guild_obj.name
        
    await interaction.response.send_message(
        f"✅ Successfully authorized server: **{guild_name}** (`{guild_id}`)."
    )

@bot.tree.command(name="unauthorize_guild", description="Unauthorize a Discord server from using the bot's commands (Owner only).")
@app_commands.describe(guild_id="The ID of the guild/server to unauthorize")
async def unauthorize_guild(interaction: discord.Interaction, guild_id: str):
    is_owner = False
    try:
        is_owner = await interaction.client.is_owner(interaction.user)
    except Exception:
        pass
    owner_id_env = os.getenv("OWNER_ID")
    if owner_id_env and str(interaction.user.id) == str(owner_id_env):
        is_owner = True
        
    if not is_owner:
        return await interaction.response.send_message(
            "❌ Only the bot owner can unauthorize servers.",
            ephemeral=True
        )
        
    try:
        g_id = int(guild_id)
    except ValueError:
        return await interaction.response.send_message(
            "❌ Invalid Guild ID. Please provide a numeric ID.",
            ephemeral=True
        )
        
    config = get_guild_config(g_id)
    config["authorized"] = False
    save_guild_config(g_id, config)
    
    guild_name = "Unknown Server"
    guild_obj = interaction.client.get_guild(g_id)
    if guild_obj:
        guild_name = guild_obj.name
        
    await interaction.response.send_message(
        f"✅ Successfully unauthorized server: **{guild_name}** (`{guild_id}`)."
    )

@bot.tree.command(name="list_authorized_guilds", description="List all authorized servers (Owner only).")
async def list_authorized_guilds(interaction: discord.Interaction):
    is_owner = False
    try:
        is_owner = await interaction.client.is_owner(interaction.user)
    except Exception:
        pass
    owner_id_env = os.getenv("OWNER_ID")
    if owner_id_env and str(interaction.user.id) == str(owner_id_env):
        is_owner = True
        
    if not is_owner:
        return await interaction.response.send_message(
            "❌ Only the bot owner can view authorized servers.",
            ephemeral=True
        )
        
    await interaction.response.defer(ephemeral=True)
    
    authorized_list = []
    
    try:
        mongo_uri = os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        import pymongo
        client_db = pymongo.MongoClient(mongo_uri)
        db = client_db["ticket_bot_db"]
        guilds_coll = db["guilds"]
        
        auth_docs = list(guilds_coll.find({"authorized": True}))
        for doc in auth_docs:
            g_id = int(doc["_id"])
            guild_obj = interaction.client.get_guild(g_id)
            g_name = guild_obj.name if guild_obj else "Unknown Server"
            authorized_list.append(f"• **{g_name}** (`{g_id}`)")
    except Exception as e:
        from db import dummy_db
        try:
            for g_id_str, config in dummy_db.guilds.items():
                if config.get("authorized", False):
                    guild_obj = interaction.client.get_guild(int(g_id_str))
                    g_name = guild_obj.name if guild_obj else "Unknown Server"
                    authorized_list.append(f"• **{g_name}** (`{g_id_str}`)")
        except:
            pass
            
    if not authorized_list:
        return await interaction.followup.send("No servers are currently authorized.", ephemeral=True)
        
    embed = discord.Embed(
        title="🛡️ Authorized Servers List",
        description="\n".join(authorized_list),
        color=discord.Color.blue()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="list_servers", description="List all servers the bot is currently in with invite links (Owner only).")
async def list_servers(interaction: discord.Interaction):
    is_owner = False
    try:
        is_owner = await interaction.client.is_owner(interaction.user)
    except Exception:
        pass
    owner_id_env = os.getenv("OWNER_ID")
    if owner_id_env and str(interaction.user.id) == str(owner_id_env):
        is_owner = True
        
    if not is_owner:
        return await interaction.response.send_message(
            "❌ Only the bot owner can use this command.",
            ephemeral=True
        )
        
    await interaction.response.defer(ephemeral=True)
    
    server_list = []
    for guild in interaction.client.guilds:
        invite_url = "No Invite Permission"
        # Try to find a text channel where we can create an invite link
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).create_instant_invite:
                try:
                    invite = await channel.create_invite(max_age=3600, max_uses=5)
                    invite_url = invite.url
                    break
                except:
                    pass
        server_list.append(f"• **{guild.name}** (`{guild.id}`) | Members: {guild.member_count} | [Invite Link]({invite_url})")
        
    if not server_list:
        return await interaction.followup.send("The bot is not in any servers.", ephemeral=True)
        
    # Split into chunks of 15 servers to avoid embed limit
    chunks = [server_list[i:i + 15] for i in range(0, len(server_list), 15)]
    
    for idx, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=f"🌍 Bot Server List (Part {idx + 1})",
            description="\n".join(chunk),
            color=discord.Color.purple()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="send_embed", description="Send a custom premium embed to a channel")
@app_commands.describe(
    channel="The channel to send the embed to",
    template="Choose a pre-made template (basic-panel, premium-panel, uid-bypass)",
    title="Custom Title (ignored if template chosen)",
    description="Custom Description (ignored if template chosen, use \\n for newlines)",
    color="Hex color code (e.g. #3498db)",
    image_url="URL of the large banner image (overrides template)",
    thumbnail_url="URL of the small thumbnail image (overrides template)"
)
@app_commands.choices(template=[
    app_commands.Choice(name="Basic-Panel", value="basic-panel"),
    app_commands.Choice(name="Premium-Panel", value="premium-panel"),
    app_commands.Choice(name="Uid-Bypass", value="uid-bypass")
])
async def send_embed(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    template: str = None,
    title: str = None,
    description: str = None,
    color: str = None,
    image_url: str = None,
    thumbnail_url: str = None
):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "Administrator permission required.",
            ephemeral=True
        )

    guild_config = get_guild_config(interaction.guild.id)
    fallback_banner = "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif"
    fallback_logo = "https://media.discordapp.net/attachments/1448757915035897886/1532872634058936500/axc.gif?ex=6a6e6e63&is=6a6d1ce3&hm=6cce736ff46f16b4ece45fc226890625eb79e4debced09a22f200bda093ffa49&=&width=350&height=350"

    embed = None

    if template == "basic-panel":
        embed = discord.Embed(
            title="BASIC PANEL ALL SERVER SAFE!!! <a:emoji_46:1528280811038834799>",
            description=(
                "<:an:1528280435572998145>   **AIM FUNCTIONS : **\n"
                "```[+] AIMBOT EXTERNAL \n"
                "[+] AIMBOT ON / OFF\n"
                "```\n"
                "<:downvote:1528328454460669952>  **LOCATION MENU:**\n"
                "```\n"
                "[+] CHAMS MENU\n"
                "[+] STREAM MODE\n"
                "```\n"
                "<a:fire2:1528328548295643178>  **NOTE : **\n"
                "```ALL SERVER SAFE\n"
                "100% SAFE FOR MAIN ID\n"
                "FULLY EXTERNAL PANEL```\n"
                "<:price:1528280545744654506>  **PRICE LIST :**\n"
                "```\n"
                "1 MONTH = 700 INR / 8$\n"
                "PERMANENT = 2000 INR / 24$```\n\n"
                "💳 **PAYMENT CHANNELS**\n"
                "We accept bKash, Binance, and Crypto. Type **`bkash`**, **`binance`**, or **`crypto`** to get payment details instantly!"
            ),
            color=0x3498db
        )
    elif template == "premium-panel":
        embed = discord.Embed(
            title="AXC PREMIUM PANEL V3 <a:redfire:1418839188912078928>",
            description=(
                "<:an:1528280435572998145>  **FUNCTIONS : **\n"
                "```[+] AIMBOT HEAD\n"
                "[+] AIMBOT ON / OFF ( IN GAME )\n"
                "[+] SNIPER SCOPE \n"
                "[+] SNIPER MACRO\n"
                "[+] AWM SWITCH\n"
                "[+] M82B SWITCH\n"
                "[+] SNIPER AIM\n"
                "[+] SNIPER LOCATIONS \n"
                "[+] SPEED HACK\n"
                "[+] WALL HACK\n"
                "[+] GLITCH FIRE\n"
                "[+] CAMERA RIGHT\n"
                "[+] FAST LANDING\n"
                "[+] VISION 7X```\n"
                "<a:Ak47:1528280754633572372>  **LOCATION MENU :**\n"
                "```[+] CHAMS MENU\n"
                "[+] RED CHAMS\n"
                "[+] BLUE CHAMS\n"
                "[+] ESP LINE\n"
                "[+] ESP BOX\n"
                "[+] ESP FILL BOX\n"
                "[+] ESP SKELETEON\n"
                "[+] ESP INFO```\n"
                "<a:Developer_:1528328581728436244>  **SETTINGS:**\n"
                "```\n"
                "[+] STREAM MODE\n"
                "[+] BLOCK INTERNET \n"
                "[+] RESET GUEST\n"
                "```\n"
                "<a:fire2:1528328548295643178>  **MOBILE CONTROL :**\n"
                "```\n"
                "[+] START SERVER\n"
                "[+] ONTE TIME SETUP\n"
                "[+] FULL CONTROL FROM PHONE\n"
                "```\n"
                "<:announce:1528280445278621836>  **NOTE : **\n"
                "```ALL SERVER SAFE\n"
                "100% SAFE FOR MAIN ID\n"
                "FULLY BRUTAL AND EXTERNAL```\n"
                "<:price:1528280545744654506>   **PRICE LIST :**\n"
                "```\n"
                "7 DAYS = 400 INR / 5$\n"
                "15 DAYS = 800 INR / 10$\n"
                "1 MONTH = 1000 INR / 12$\n"
                "PERMANENT = 3000 INR / 35$```\n\n"
                "💳 **PAYMENT CHANNELS**\n"
                "We accept bKash, Binance, and Crypto. Type **`bkash`**, **`binance`**, or **`crypto`** to get payment details instantly!"
            ),
            color=0xf1c40f
        )
    elif template == "uid-bypass":
        embed = discord.Embed(
            title="<:an:1528280435572998145> UID BYPASS | SAFE ALL SERVER",
            description=(
                "<a:Ak47:1528280754633572372>  Easy Setup & Full Support\n"
                "<a:Ak47:1528280754633572372>  Work On All Emulator \n"
                "<a:Ak47:1528280754633572372>  Anti-Lags\n\n"
                "<:price:1528280545744654506>  **PRICE LIST** \n"
                "```1 Month — $12 | ₹1,020\n"
                "Lifetime — $30 | ₹3,100```\n\n"
                "**UID BYPASS API** \n\n"
                "<:price:1528280545744654506> **PRICE LIST** \n"
                "```$60 — Unlimited UID | ₹6,500```\n\n"
                "💳 **PAYMENT CHANNELS**\n"
                "We accept bKash, Binance, and Crypto. Type **`bkash`**, **`binance`**, or **`crypto`** to get payment details instantly!"
            ),
            color=0xe74c3c
        )
    else:
        if not title or not description:
            return await interaction.response.send_message(
                "You must provide a title and description if not using a template.",
                ephemeral=True
            )
        embed_color = discord.Color.red()
        if color:
            try:
                embed_color = discord.Color(int(color.lstrip('#'), 16))
            except ValueError:
                pass
        embed = discord.Embed(
            title=title,
            description=description.replace("\\n", "\n"),
            color=embed_color
        )

    # Set media
    final_thumbnail = thumbnail_url.strip() if thumbnail_url else (guild_config.get("ticket_logo") or fallback_logo)
    final_banner = image_url.strip() if image_url else (guild_config.get("ticket_banner") or fallback_banner)

    if "e62e3cc75f1747e0824ed1ee0dda51a9.webp" in final_thumbnail:
        final_thumbnail = fallback_logo

    embed.set_thumbnail(url=final_thumbnail)
    embed.set_image(url=final_banner)
    embed.set_footer(text="Anik X Cheats • Ticket System", icon_url=final_thumbnail)
    embed.timestamp = discord.utils.utcnow()

    try:
        await channel.send(embed=embed)
        await interaction.response.send_message(
            f"Embed successfully sent to {channel.mention}!",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Failed to send embed: {e}",
            ephemeral=True
        )

@bot.tree.command(name="add_uid", description="Directly register a client's UID on the cheat bypass API and database.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    uid="The target Free Fire UID (numbers only)",
    days="Number of days (e.g. 30, or 0 for lifetime)"
)
async def add_uid(
    interaction: discord.Interaction,
    uid: str,
    days: int
):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    config = get_guild_config(interaction.guild.id)
    authorized_users = config.get("authorized_users", [])
    is_admin = interaction.user.guild_permissions.administrator
    is_authorized = str(interaction.user.id) in [str(u) for u in authorized_users]
    
    if not (is_admin or is_authorized):
        return await interaction.response.send_message(
            "❌ Only server administrators or authorized users can register UIDs.",
            ephemeral=True
        )
        
    if not uid.isdigit():
        return await interaction.response.send_message(
            "❌ Invalid UID format. Please use numbers only.",
            ephemeral=True
        )

    await interaction.response.defer()

    import pymongo
    import datetime
    import base64
    import requests
    
    db_success = False
    db_msg = ""
    try:
        mongo_uri = os.getenv("BYPASS_MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        client_db = pymongo.MongoClient(mongo_uri)
        db = client_db["uidbypassdb"]
        uids_coll = db["uids"]
        
        if int(days) == 0:
            expiry_date = 'lifetime'
        else:
            expiry_date = (datetime.datetime.now() + datetime.timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
            
        existing = uids_coll.find_one({"uid": str(uid)})
        if existing:
            db_msg = "UID already registered in database."
        else:
            entry = {
                'uid': str(uid),
                'note': f'Discord Ticket: #{interaction.channel.name}',
                'expiry_date': expiry_date,
                'added_by': f'Discord Bot ({interaction.user.name})',
                'added_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            uids_coll.insert_one(entry)
            db_success = True
            db_msg = "UID saved to database."
    except Exception as db_err:
        db_msg = f"Database sync error: {db_err}"

    api_success = False
    api_msg = ""
    try:
        url = os.getenv("GTC_API_URL")
        api_key = os.getenv("GTC_API_KEY")
        if not url or not api_key:
            raise Exception("GTC API configuration is missing from environment variables.")
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        axc_days = "9999" if str(days) == '0' else str(days)
        payload = {"account_id": str(uid), "for_days": axc_days}
        
        try:
            check_r = requests.get(url, params={"action": "info", "account_id": str(uid)}, headers=headers, timeout=8)
            if check_r.status_code == 200:
                res_json = check_r.json()
                if res_json.get("success"):
                    api_success = True
                    api_msg = "UID already active on external server."
        except:
            pass
            
        if not api_success:
            r = requests.post(url, params={"action": "add"}, json=payload, headers=headers, timeout=12)
            if r.status_code in (200, 201):
                try:
                    res_json = r.json()
                    if res_json.get("success") or "added successfully" in res_json.get("message", "").lower():
                        api_success = True
                        api_msg = res_json.get("message", "Synced successfully.")
                    else:
                        api_msg = res_json.get("message", "API accepted with notice.")
                except:
                    if "added successfully" in r.text.lower():
                        api_success = True
                        api_msg = "Registered on bypass system."
                    else:
                        api_msg = f"API Response: {r.text[:100]}"
            else:
                api_msg = f"Server returned error code {r.status_code}"
    except Exception as api_err:
        api_msg = f"API network error: {api_err}"

    embed = discord.Embed(
        title="<a:RedCrown:1528328624409677855>  UID Bypass Registration",
        color=discord.Color.green() if (db_success or api_success) else discord.Color.red()
    )
    embed.add_field(name="Target UID", value=f"`{uid}`", inline=True)
    embed.add_field(name="Validity", value=f"`{days} Days`" if days > 0 else "`Lifetime`", inline=True)
    embed.add_field(name="Cheat DB Status", value=f"<:tick:1528280519161417749>  {db_msg}" if db_success else f"❌ {db_msg}", inline=False)
    embed.add_field(name="Bypass API Sync", value=f"<:an:1528280435572998145>  {api_msg}" if api_success else f"⚠️ {api_msg}", inline=False)
    
    await interaction.followup.send(embed=embed)

    # Send premium styled DM to the ticket opener if registration was successful
    if db_success or api_success or "already active" in api_msg.lower():
        ticket_data = get_ticket(str(interaction.channel.id))
        user_id = ticket_data["user_id"] if ticket_data else None
        if user_id:
            try:
                opener = interaction.client.get_user(user_id) or await interaction.client.fetch_user(user_id)
                if opener:
                    fallback_banner = "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif"
                    fallback_logo = "https://media.discordapp.net/attachments/1448757915035897886/1532872634058936500/axc.gif?ex=6a6e6e63&is=6a6d1ce3&hm=6cce736ff46f16b4ece45fc226890625eb79e4debced09a22f200bda093ffa49&=&width=350&height=350"
                    logo_url = guild_config.get("ticket_logo") or fallback_logo
                    banner_url = guild_config.get("ticket_banner") or fallback_banner
                    
                    val_str = f"{days} Days" if days > 0 else "Lifetime"
                    dm_embed = discord.Embed(
                        title="AXC UID BYPASS ACTIVATION <:an:1528280435572998145>",
                        description=(
                            "⚡ **AXC UID BYPASS ACTIVATION** <:an:1528280435572998145>\n\n"
                            "⚡ **Your UID has been successfully activated!**\n\n"
                            f"👤 **Target UID:** `{uid}`\n"
                            f"📅 **Validity:** `{val_str}`\n\n"
                            "enjoy safe bypass!"
                        ),
                        color=0xf1c40f
                    )
                    dm_embed.set_thumbnail(url=logo_url)
                    await opener.send(embed=dm_embed)
            except Exception as dm_err:
                print(f"Failed to DM activation info: {dm_err}")

@bot.tree.command(name="remove_uid", description="Directly remove a client's UID from the cheat bypass API and database.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    uid="The target Free Fire UID to remove (numbers only)"
)
async def remove_uid(
    interaction: discord.Interaction,
    uid: str
):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    config = get_guild_config(interaction.guild.id)
    authorized_users = config.get("authorized_users", [])
    is_admin = interaction.user.guild_permissions.administrator
    is_authorized = str(interaction.user.id) in [str(u) for u in authorized_users]
    
    if not (is_admin or is_authorized):
        return await interaction.response.send_message(
            "❌ Only server administrators or authorized users can remove UIDs.",
            ephemeral=True
        )
        
    if not uid.isdigit():
        return await interaction.response.send_message(
            "❌ Invalid UID format. Please use numbers only.",
            ephemeral=True
        )

    await interaction.response.defer()

    import pymongo
    import base64
    import requests
    
    db_success = False
    db_msg = ""
    
    try:
        mongo_uri = os.getenv("BYPASS_MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        client_db = pymongo.MongoClient(mongo_uri)
        db = client_db["uidbypassdb"]
        uids_coll = db["uids"]
        
        existing = uids_coll.find_one({"uid": str(uid)})
        if not existing:
            db_msg = "UID not found in database."
        else:
            uids_coll.delete_one({"uid": str(uid)})
            db_success = True
            db_msg = "UID deleted from database."
    except Exception as db_err:
        db_msg = f"Database sync error: {db_err}"

    api_success = False
    api_msg = ""
    try:
        url = os.getenv("GTC_API_URL")
        api_key = os.getenv("GTC_API_KEY")
        if not url or not api_key:
            raise Exception("GTC API configuration is missing from environment variables.")
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {"account_id": str(uid)}
        r = requests.post(url, params={"action": "remove"}, json=payload, headers=headers, timeout=12)

        if r.status_code in (200, 201):
            try:
                res_json = r.json()
                if res_json.get("success") or "deleted" in res_json.get("message", "").lower() or "success" in res_json.get("message", "").lower() or "removed" in res_json.get("message", "").lower():
                    api_success = True
                    api_msg = res_json.get("message", "Removed from bypass system.")
                else:
                    api_msg = res_json.get("message", "API response warning.")
            except:
                if "success" in r.text.lower() or "deleted" in r.text.lower() or "removed" in r.text.lower():
                    api_success = True
                    api_msg = "Removed from bypass system."
                else:
                    api_msg = f"API Response: {r.text[:100]}"
        else:
            api_msg = f"Server returned error code {r.status_code}"
    except Exception as api_err:
        api_msg = f"API network error: {api_err}"

    embed = discord.Embed(
        title="🗑️ UID Bypass Removal",
        color=discord.Color.green() if (db_success or api_success) else discord.Color.red()
    )
    embed.add_field(name="Target UID", value=f"`{uid}`", inline=True)
    embed.add_field(name="Cheat DB Status", value=f"<:tick:1528280519161417749>  {db_msg}" if db_success else f"❌ {db_msg}", inline=False)
    embed.add_field(name="Bypass API Sync", value=f"<:an:1528280435572998145>  {api_msg}" if api_success else f"⚠️ {api_msg}", inline=False)
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="authorize_user", description="Authorize a Discord user to run the info_uid command.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    user="The Discord user to authorize"
)
async def authorize_user(
    interaction: discord.Interaction,
    user: discord.User
):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Only server administrators can authorize users.",
            ephemeral=True
        )
        
    config = get_guild_config(interaction.guild.id)
    if "authorized_users" not in config:
        config["authorized_users"] = []
        
    user_id_str = str(user.id)
    if user_id_str in config["authorized_users"]:
        return await interaction.response.send_message(
            f"⚠️ {user.mention} is already authorized.",
            ephemeral=True
        )
        
    config["authorized_users"].append(user_id_str)
    save_guild_config(interaction.guild.id, config)
    
    await interaction.response.send_message(
        f"✅ Successfully authorized {user.mention} (`{user.id}`) to use `/info_uid` command."
    )

@bot.tree.command(name="unauthorize_user", description="Remove authorization for a Discord user from running info_uid command.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    user="The Discord user to unauthorize"
)
async def unauthorize_user(
    interaction: discord.Interaction,
    user: discord.User
):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Only server administrators can unauthorize users.",
            ephemeral=True
        )
        
    config = get_guild_config(interaction.guild.id)
    if "authorized_users" not in config:
        config["authorized_users"] = []
        
    user_id_str = str(user.id)
    if user_id_str not in config["authorized_users"]:
        return await interaction.response.send_message(
            f"⚠️ {user.mention} is not authorized.",
            ephemeral=True
        )
        
    config["authorized_users"].remove(user_id_str)
    save_guild_config(interaction.guild.id, config)
    
    await interaction.response.send_message(
        f"✅ Successfully unauthorized {user.mention} (`{user.id}`)."
    )

@bot.tree.command(name="info_uid", description="Check a client's UID info from the cheat bypass API and database.")
@app_commands.describe(
    uid="The target Free Fire UID to check (numbers only)"
)
async def info_uid(
    interaction: discord.Interaction,
    uid: str
):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    config = get_guild_config(interaction.guild.id)
    authorized_users = config.get("authorized_users", [])
    
    is_admin = interaction.user.guild_permissions.administrator
    is_authorized = str(interaction.user.id) in [str(u) for u in authorized_users]
    
    if not (is_admin or is_authorized):
        return await interaction.response.send_message(
            "❌ Only server administrators or authorized users can check UID info.",
            ephemeral=True
        )
        
    if not uid.isdigit():
        return await interaction.response.send_message(
            "❌ Invalid UID format. Please use numbers only.",
            ephemeral=True
        )

    await interaction.response.defer()

    import pymongo
    import requests
    
    db_found = False
    db_msg = ""
    db_expiry = "N/A"
    db_added_by = "N/A"
    
    try:
        mongo_uri = os.getenv("BYPASS_MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        client_db = pymongo.MongoClient(mongo_uri)
        db = client_db["uidbypassdb"]
        uids_coll = db["uids"]
        
        existing = uids_coll.find_one({"uid": str(uid)})
        if existing:
            db_found = True
            db_expiry = existing.get("expiry_date", "N/A")
            db_added_by = existing.get("added_by", "N/A")
            db_msg = "UID found in database."
        else:
            db_msg = "UID not found in database."
    except Exception as db_err:
        db_msg = f"Database query error: {db_err}"

    api_success = False
    api_msg = ""
    api_data = {}
    
    try:
        url = os.getenv("GTC_API_URL")
        api_key = os.getenv("GTC_API_KEY")
        if not url or not api_key:
            raise Exception("GTC API configuration is missing from environment variables.")
        headers = {
            "X-API-KEY": api_key,
            "Accept": "application/json"
        }
        
        r = requests.get(url, params={"action": "info", "account_id": str(uid)}, headers=headers, timeout=12)
        if r.status_code == 200:
            try:
                res_json = r.json()
                if res_json.get("success") or "active" in res_json.get("message", "").lower() or res_json.get("data"):
                    api_success = True
                    api_data = res_json.get("data", {})
                    api_msg = res_json.get("message", "UID active on bypass server.")
                else:
                    api_msg = res_json.get("message", "UID not active on bypass server.")
            except:
                if "active" in r.text.lower() or "success" in r.text.lower():
                    api_success = True
                    api_msg = "UID active on bypass server."
                else:
                    api_msg = f"API Response: {r.text[:100]}"
        else:
            api_msg = f"Server returned error code {r.status_code}"
    except Exception as api_err:
        api_msg = f"API network error: {api_err}"

    embed = discord.Embed(
        title="🔍 UID Bypass Info",
        color=discord.Color.green() if (db_found or api_success) else discord.Color.red()
    )
    embed.add_field(name="Target UID", value=f"`{uid}`", inline=True)
    embed.add_field(name="Cheat DB Status", value=f"<:tick:1528280519161417749>  {db_msg}" if db_found else f"❌ {db_msg}", inline=False)
    
    if db_found:
        embed.add_field(name="DB Expiry Date", value=f"`{db_expiry}`", inline=True)
        embed.add_field(name="DB Added By", value=f"`{db_added_by}`", inline=True)
        
    embed.add_field(name="Bypass API Status", value=f"<:an:1528280435572998145>  {api_msg}" if api_success else f"⚠️ {api_msg}", inline=False)
    
    if api_data:
        expiry_date = api_data.get("expiry_date") or api_data.get("expiry")
        if expiry_date:
            embed.add_field(name="API Expiry Date", value=f"`{expiry_date}`", inline=True)
            
        added_by = api_data.get("added_by") or api_data.get("adder_name")
        if added_by:
            embed.add_field(name="API Added By", value=f"`{added_by}`", inline=True)

    await interaction.followup.send(embed=embed)

async def app_id_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    import pymongo
    import os
    try:
        mongo_uri = os.getenv("AUTH_MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        client_db = pymongo.MongoClient(mongo_uri)
        db = client_db["licensing_db"]
        apps = list(db["apps"].find({}))
        choices = []
        for app in apps:
            app_name = app.get("name", "Unknown App")
            app_id = app["id"]
            if current.lower() in app_name.lower() or current.lower() in app_id.lower():
                choices.append(app_commands.Choice(name=app_name, value=app_id))
        return choices[:25]
    except Exception as e:
        print(f"Autocomplete error: {e}")
        return []

@bot.tree.command(name="create_user", description="Create a new client account directly in the auth licensing system.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    password="The client's new password",
    days="Number of days (e.g. 30, or 0 for lifetime)",
    username="The client's new username (optional - defaults to ticket opener)",
    app_id="Target App ID (optional - defaults to first app)"
)
@app_commands.autocomplete(app_id=app_id_autocomplete)
async def create_user(
    interaction: discord.Interaction,
    password: str,
    days: int,
    username: str = None,
    app_id: str = None
):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Only server administrators can create users.",
            ephemeral=True
        )

    if not username:
        ticket_data = get_ticket(str(interaction.channel.id))
        if not ticket_data:
            return await interaction.response.send_message(
                "❌ You must specify a username when running this command outside a ticket channel.",
                ephemeral=True
            )
        user_id = ticket_data.get("user_id")
        try:
            member = interaction.guild.get_member(int(user_id)) or await interaction.guild.fetch_member(int(user_id))
            raw_name = member.name
        except:
            return await interaction.response.send_message(
                "❌ Could not retrieve the ticket opener's details. Please enter the username manually.",
                ephemeral=True
            )
            
        import re
        username = re.sub(r'[^a-zA-Z0-9_]', '', raw_name)
        if len(username) < 3:
            username = f"usr_{str(user_id)[-6:]}"
        elif len(username) > 20:
            username = username[:20]
        
    if len(username) < 3 or len(username) > 20:
        return await interaction.response.send_message(
            "❌ Username must be between 3 and 20 characters.",
            ephemeral=True
        )

    await interaction.response.defer()

    import pymongo
    import datetime
    import bcrypt
    import uuid
    
    success = False
    msg = ""
    license_key = ""
    target_app_name = ""
    
    try:
        mongo_uri = os.getenv("AUTH_MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        client_db = pymongo.MongoClient(mongo_uri)
        db = client_db["licensing_db"]
        
        apps = list(db["apps"].find({}))
        if not apps:
            msg = "No applications found in the licensing database."
        else:
            if not app_id:
                app_obj = apps[0]
                app_id = app_obj["id"]
                target_app_name = app_obj.get("name", app_id)
            else:
                app_obj = db["apps"].find_one({"id": app_id})
                if not app_obj:
                    msg = f"Application ID '{app_id}' not found."
                else:
                    target_app_name = app_obj.get("name", app_id)
            
            if app_id and app_obj:
                existing = db["users"].find_one({"username": username, "app_id": app_id})
                if existing:
                    msg = "Username already exists in this application."
                else:
                    salt = bcrypt.gensalt()
                    hashed = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
                    
                    license_key = f"LCN-USR-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"
                    
                    if int(days) > 0:
                        expiry = (datetime.datetime.utcnow() + datetime.timedelta(days=int(days))).isoformat()
                    else:
                        expiry = "Lifetime"
                        
                    lic_doc = {
                        "key": license_key,
                        "app_id": app_id,
                        "duration_days": int(days),
                        "subscription_id": None,
                        "is_used": True,
                        "used_by": username,
                        "expires_at": expiry,
                        "is_banned": False,
                        "note": f"Auto-generated via Discord Bot in ticket #{interaction.channel.name}",
                        "hwid": None,
                        "created_at": datetime.datetime.utcnow().isoformat()
                    }
                    db["licenses"].insert_one(lic_doc)
                    
                    user_doc = {
                        "username": username,
                        "password": hashed,
                        "role": "user",
                        "app_id": app_id,
                        "license_key": license_key,
                        "subscription_id": None,
                        "hwid": None,
                        "created_at": datetime.datetime.utcnow().isoformat()
                    }
                    db["users"].insert_one(user_doc)
                    
                    db["logs"].insert_one({
                        "app_id": app_id,
                        "event": "User Create",
                        "details": f"Created direct user '{username}' with key '{license_key}' via Discord bot",
                        "timestamp": datetime.datetime.utcnow().isoformat()
                    })
                    
                    success = True
                    msg = "User account successfully created."
    except Exception as err:
        msg = f"Database connection error: {err}"

    embed = discord.Embed(
        title="<:trick_supreme:1528280687126253648>  Auth User Registration",
        color=discord.Color.green() if success else discord.Color.red()
    )
    embed.add_field(name="Username", value=f"`{username}`", inline=True)
    embed.add_field(name="Password", value=f"`{password}`", inline=True)
    embed.add_field(name="Validity", value=f"`{days} Days`" if days > 0 else "`Lifetime`", inline=True)
    if success:
        embed.add_field(name="Status", value=f"<:emoji_67:1528302438401048667>  {msg}", inline=False)
    else:
        embed.add_field(name="Status", value=f"❌ {msg}", inline=False)

    await interaction.followup.send(embed=embed)

    if success:
        ticket_data = get_ticket(str(interaction.channel.id))
        user_id = ticket_data["user_id"] if ticket_data else None
        if user_id:
            try:
                opener = interaction.client.get_user(user_id) or await interaction.client.fetch_user(user_id)
                if opener:
                    fallback_logo = "https://media.discordapp.net/attachments/1448757915035897886/1532872634058936500/axc.gif?ex=6a6e6e63&is=6a6d1ce3&hm=6cce736ff46f16b4ece45fc226890625eb79e4debced09a22f200bda093ffa49&=&width=350&height=350"
                    logo_url = guild_config.get("ticket_logo") or fallback_logo
                    val_str = f"{days} Days" if days > 0 else "Lifetime"
                    
                    dm_embed = discord.Embed(
                        title="AXC CLIENT ACCOUNT CREATED <:an:1528280435572998145>",
                        description=(
                            "🔑 **AXC CLIENT ACCOUNT DETAILS** <:an:1528280435572998145>\n\n"
                            "🔑 **Your cheat access account has been created!**\n\n"
                            f"👤 **Username:** `{username}`\n"
                            f"🔒 **Password:** `{password}`\n"
                            f"📅 **Validity:** `{val_str}`\n\n"
                            "Download the loader, log in with your credentials, and enjoy premium access!"
                        ),
                        color=0xf1c40f
                    )
                    dm_embed.set_thumbnail(url=logo_url)
                    await opener.send(embed=dm_embed)
            except Exception as dm_err:
                print(f"Failed to DM user account info: {dm_err}")

@bot.tree.command(name="genkey", description="Generate a new license key in the auth licensing system.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    days="Number of days for key validity (e.g. 30, or 0 for lifetime)",
    app_id="Target App ID (optional - defaults to first app)"
)
@app_commands.autocomplete(app_id=app_id_autocomplete)
async def genkey(
    interaction: discord.Interaction,
    days: int,
    app_id: str = None
):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Only server administrators can generate keys.",
            ephemeral=True
        )

    await interaction.response.defer()

    import pymongo
    import datetime
    import uuid
    
    success = False
    msg = ""
    generated_key = ""
    target_app_name = ""
    
    try:
        mongo_uri = os.getenv("AUTH_MONGO_URI") or os.getenv("MONGO_URI") or "mongodb://localhost:27017/"
        client_db = pymongo.MongoClient(mongo_uri)
        db = client_db["licensing_db"]
        
        apps = list(db["apps"].find({}))
        if not apps:
            msg = "No applications found in the licensing database."
        else:
            if not app_id:
                app_obj = apps[0]
                app_id = app_obj["id"]
                target_app_name = app_obj.get("name", app_id)
            else:
                app_obj = db["apps"].find_one({"id": app_id})
                if not app_obj:
                    msg = f"Application ID '{app_id}' not found."
                else:
                    target_app_name = app_obj.get("name", app_id)
            
            if app_id and app_obj:
                generated_key = f"LCN-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"
                now = datetime.datetime.utcnow()
                
                lic_doc = {
                    "key": generated_key,
                    "app_id": app_id,
                    "duration_days": int(days),
                    "subscription_id": None,
                    "is_used": False,
                    "used_by": None,
                    "expires_at": None,
                    "is_banned": False,
                    "note": f"Generated via Discord slash command by {interaction.user}",
                    "hwid": None,
                    "created_at": now.isoformat()
                }
                db["licenses"].insert_one(lic_doc)
                
                db["logs"].insert_one({
                    "app_id": app_id,
                    "event": "License Generate",
                    "details": f"Generated key '{generated_key}' (duration: {days} days) via Discord bot",
                    "timestamp": now.isoformat()
                })
                
                success = True
                msg = "License key generated successfully."
    except Exception as err:
        msg = f"Database connection error: {err}"

    embed = discord.Embed(
        title="🔑 License Key Generator",
        color=discord.Color.green() if success else discord.Color.red()
    )
    embed.add_field(name="Validity", value=f"`{days} Days`" if days > 0 else "`Lifetime`", inline=True)
    if success:
        embed.add_field(name="App Name", value=f"`{target_app_name}`", inline=True)
        embed.add_field(name="Generated Key", value=f"`{generated_key}`", inline=False)
        embed.add_field(name="Status", value=f"✅ {msg}", inline=False)
    else:
        embed.add_field(name="Status", value=f"❌ {msg}", inline=False)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="setup_ticket", description="Setup the ticket panel")
@app_commands.default_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "Administrator permission required.",
            ephemeral=True
        )

    guild_config = get_guild_config(interaction.guild.id)
    banner_url = guild_config.get("ticket_banner", "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExNXprYXQ0Z3QzeGMweDFoZmYzZnBqMTBsamJ4cDVrNjg5eDdiM2g2MCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/7RwanQsnkwtQoM1lMo/giphy.gif")
    logo_url = guild_config.get("ticket_logo", "https://media.discordapp.net/attachments/1448757915035897886/1506560802185019472/axcmainlogi-removebg.png?ex=6a3b8895&is=6a3a3715&hm=64d12abe8a8e1d146cf1d83246745bbbfebbb508cf1f0a96f5475a618d20fd7a&=&format=webp&quality=lossless&width=978&height=978")

    embed = discord.Embed(
        title="<:support:1463880645016027298> Support Ticket System",
        description="Need help? Create a ticket and our staff will assist you shortly.",
        color=discord.Color.red()
    )

    embed.set_image(url=banner_url)
    embed.set_thumbnail(url=logo_url)

    embed.add_field(
        name="<:rules:1463880669296984227> Rules",
        value=(
            "• Do not create tickets for fun\n"
            "• No abusive language\n"
            "• Discuss TOS & warranty before purchase"
        ),
        inline=False
    )

    embed.add_field(
        name="<a:times:1463880691107233802> Response Time",
        value="Staff will respond within **1 to 5 minutes** (usually faster).",
        inline=False
    )

    embed.set_footer(text="Anik X Cheats • Ticket System", icon_url=logo_url)
    embed.timestamp = discord.utils.utcnow()

    await interaction.channel.send(embed=embed, view=TicketTypeSelectView())
    await interaction.response.send_message(
        "Ticket panel has been set up.",
        ephemeral=True
    )

@bot.tree.command(name="set_staff_role", description="Set staff role for tickets")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="Staff role")
async def set_staff_role(interaction: discord.Interaction, role: discord.Role):
    if not await check_guild_authorized(interaction):
        return await interaction.response.send_message(
            "❌ This server is not authorized to use this bot's premium commands.",
            ephemeral=True
        )

    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "Administrator permission required.",
            ephemeral=True
        )

    guild_config = get_guild_config(interaction.guild.id)
    guild_config["staff_role_id"] = str(role.id)
    save_guild_config(interaction.guild.id, guild_config)

    await interaction.response.send_message(
        f"Staff role set to {role.mention}",
        ephemeral=True
    )



@bot.tree.command(name="add_user", description="Add a user to the ticket (Premium)")
@app_commands.describe(user="The user to add")
async def add_user(interaction: discord.Interaction, user: discord.Member):
    if "ticket" not in interaction.channel.name:
        return await interaction.response.send_message("This command can only be used in tickets.", ephemeral=True)
    
    await interaction.channel.set_permissions(user, view_channel=True, send_messages=True)
    embed = discord.Embed(title="👤 User Added", description=f"{user.mention} has been added to the ticket by {interaction.user.mention}.", color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="remove_user", description="Remove a user from the ticket (Premium)")
@app_commands.describe(user="The user to remove")
async def remove_user(interaction: discord.Interaction, user: discord.Member):
    if "ticket" not in interaction.channel.name:
        return await interaction.response.send_message("This command can only be used in tickets.", ephemeral=True)
        
    await interaction.channel.set_permissions(user, overwrite=None)
    embed = discord.Embed(title="👤 User Removed", description=f"{user.mention} has been removed from the ticket.", color=discord.Color.red())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rename_ticket", description="Rename the current ticket (Premium)")
@app_commands.describe(new_name="The new name for the ticket")
async def rename_ticket(interaction: discord.Interaction, new_name: str):
    if "ticket" not in interaction.channel.name:
        return await interaction.response.send_message("This command can only be used in tickets.", ephemeral=True)
        
    old_name = interaction.channel.name
    await interaction.channel.edit(name=new_name)
    embed = discord.Embed(title="📝 Ticket Renamed", description=f"Ticket renamed from `{old_name}` to `{new_name}`", color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="transcript", description="Generate a transcript of the ticket manually (Premium)")
async def transcript_cmd(interaction: discord.Interaction):
    if "ticket" not in interaction.channel.name:
        return await interaction.response.send_message("This command can only be used in tickets.", ephemeral=True)
        
    await interaction.response.send_message("Generating transcript... Please wait.", ephemeral=True)
    messages = [message async for message in interaction.channel.history(limit=None, oldest_first=True)]
    html_content = f"<html><head><title>Transcript: {interaction.channel.name}</title><style>body{{font-family: sans-serif; background-color: #36393f; color: #dcddde;}} .msg{{margin-bottom: 10px;}} .author{{font-weight: bold; color: #fff;}} .time{{color: #72767d; font-size: 0.8em; margin-left: 10px;}}</style></head><body><h1>Transcript for {interaction.channel.name}</h1><hr>"
    for m in messages:
        html_content += f"<div class='msg'><span class='author'>{m.author.display_name}</span><span class='time'>{m.created_at.strftime('%Y-%m-%d %H:%M:%S')}</span><br>{m.content}</div>"
    html_content += "</body></html>"
    
    file = discord.File(fp=io.BytesIO(html_content.encode('utf-8')), filename=f"transcript-{interaction.channel.name}.html")
    await interaction.channel.send(f"📄 **Transcript manually generated by {interaction.user.mention}**", file=file)

# ---------- Key Distribution Commands ----------

@bot.tree.command(name="setup_key_channel", description="Set the channel where users can claim free keys.")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="The channel for key claiming")
async def setup_key_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Only administrators can set the key distribution channel.",
            ephemeral=True
        )

    guild_config = get_guild_config(interaction.guild.id)
    guild_config["key_channel_id"] = str(channel.id)
    save_guild_config(interaction.guild.id, guild_config)

    embed = discord.Embed(
        title="🔑 Key Channel Configured",
        description=f"Free keys can now be claimed in {channel.mention} using `/claimkey` or `!claimkey`.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="claimkey", description="Claim a free license key (Limit: 1 per user).")
async def claimkey(interaction: discord.Interaction):
    guild_config = get_guild_config(interaction.guild.id)
    key_channel_id = guild_config.get("key_channel_id")

    if not key_channel_id:
        return await interaction.response.send_message(
            "❌ Key distribution has not been configured/authorized by the administrator yet.",
            ephemeral=True
        )

    if str(interaction.channel.id) != str(key_channel_id):
        authorized_channel = interaction.guild.get_channel(int(key_channel_id))
        mention_str = authorized_channel.mention if authorized_channel else f"<#{key_channel_id}>"
        return await interaction.response.send_message(
            f"❌ This command can only be used in {mention_str}.",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    if has_user_claimed(interaction.user.id):
        embed = discord.Embed(
            title="🔑 Key Claim Status",
            description="❌ You have already claimed a key! You can only claim a key once.",
            color=discord.Color.red()
        )
        return await interaction.followup.send(embed=embed, ephemeral=True)

    generated_key = await call_key_generator_api(1)
    if not generated_key:
        embed = discord.Embed(
            title="🔑 Key Claim Status",
            description="❌ Failed to generate key from AuthAXC system. Please contact staff or try again later.",
            color=discord.Color.red()
        )
        return await interaction.followup.send(embed=embed, ephemeral=True)

    claimed_key = generated_key
    mark_user_claimed(interaction.user.id, claimed_key, interaction.guild.id, revealed=True)

    # Key claimed successfully! Send it to the user.
    embed = discord.Embed(
        title="<:tik:1528280512169246894>  **YOUR SECURE ACCESS**",
        description=(
            f"**Your personal credentials are below. Never share it.**\n"
            f"<:trick_supreme:1528280687126253648>  **LICENSE KEY — Tap to copy**\n"
            f"```\n"
            f"{claimed_key}```\n\n"
            f"<:arrow:1528280452232642570>  **DOWNLOAD BYPASS EXE**\n"
            f"[Click here to download Bypass Emulator](https://www.dropbox.com/scl/fi/u9czoect0rv5w2o9v0h11/AXC-LIB-BYPASS.exe?rlkey=wjwke1emn688j44lv7tj6wxvv&st=sh84trcd&dl=0)\n"
            f"<:arrow:1528280452232642570>  **DOWNLOAD FREEFIRE APK**\n"
            f"[Click here to download Free Fire APK](https://www.dropbox.com/scl/fi/vqhivuvpvfxhjw0ub3p2v/FREE-FIRE-OB54-V7A.xapk?rlkey=cmjfz7cyr8pd84x0mpedt1i3u&st=35uogn0d&dl=0)\n"
            f"<a:Warning:1528328561361158245>  **IMPORTANT**\n"
            f"**This LICENSE KEY will only work on the EXE given above.**"
        ),
        color=discord.Color.red()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

# Prefix equivalents
@bot.command(name="setkeychannel")
@commands.has_permissions(administrator=True)
async def prefix_set_key_channel(ctx, channel: discord.TextChannel):
    guild_config = get_guild_config(ctx.guild.id)
    guild_config["key_channel_id"] = str(channel.id)
    save_guild_config(ctx.guild.id, guild_config)
    await ctx.send(f"✅ Key channel set to {channel.mention}")

@bot.command(name="removekeychannel")
@commands.has_permissions(administrator=True)
async def prefix_remove_key_channel(ctx):
    guild_config = get_guild_config(ctx.guild.id)
    guild_config["key_channel_id"] = None
    save_guild_config(ctx.guild.id, guild_config)
    await ctx.send("✅ Key distribution channel has been disabled/removed.")

@bot.command(name="sendkey")
@commands.has_permissions(administrator=True)
async def send_trial_claim_panel(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass
        
    guild_config = get_guild_config(ctx.guild.id)
    logo_url = guild_config.get("ticket_logo", "https://media.discordapp.net/attachments/1448757915035897886/1506560802185019472/axcmainlogi-removebg.png?ex=6a3b8895&is=6a3a3715&hm=64d12abe8a8e1d146cf1d83246745bbbfebbb508cf1f0a96f5475a618d20fd7a&=&format=webp&quality=lossless&width=978&height=978")
    
    embed = discord.Embed(
        title="LIP BYPASS 1 DAY TRIAL",
        description="",
        color=0x2b2d31
    )
    # Set the GIF banner
    embed.set_image(url="https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif")
    
    await ctx.send(embed=embed, view=TrialKeyClaimButtonView())

# --- Helper to retrieve API Key ---
def get_api_key_from_vps():
    # Try reading from config.json on the VPS first, fallback to env variable
    try:
        config_path = "/root/self-bot/config.json"
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
                return data.get("api_key", "")
    except Exception:
        pass
    return os.getenv("KEY_GEN_API_KEY", "")

async def call_key_generator_api(duration: int) -> str:
    url = os.getenv("KEY_GEN_API_URL", "https://auth.anikxcheatx.com/api/seller/generate")
    seller_key = os.getenv("KEY_GEN_API_KEY") or os.getenv("SELLER_KEY", "")
    app_id = os.getenv("AUTH_APP_ID", "")
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "app_id": app_id,
        "seller_key": seller_key,
        "duration_days": duration,
        "count": 1,
        "note": "Discord Free Trial Claim"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=15.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "success" and data.get("keys"):
                        return data["keys"][0]
                else:
                    print(f"AuthAXC Seller API returned status {resp.status}: {await resp.text()}")
    except Exception as e:
        print(f"Failed calling AuthAXC key generator API: {e}")
    return None

@bot.command(name="claimkey")
async def prefix_claimkey(ctx, action: str = None):
    guild_config = get_guild_config(ctx.guild.id)
    
    # Handle toggle command (Admin only)
    if action in ["on", "off", "toggle"]:
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("❌ Only administrators can toggle key claiming.")
            
        current_state = guild_config.get("claimkey_enabled", True)
        if action == "on":
            guild_config["claimkey_enabled"] = True
        elif action == "off":
            guild_config["claimkey_enabled"] = False
        else:
            guild_config["claimkey_enabled"] = not current_state
            
        save_guild_config(ctx.guild.id, guild_config)
        status = "ENABLED" if guild_config["claimkey_enabled"] else "DISABLED"
        return await ctx.send(f"✅ Free key claiming has been **{status}** for this server.")

    # Normal claim logic
    # Try deleting the user's !claimkey command message instantly
    try:
        await ctx.message.delete()
    except Exception:
        pass

    key_channel_id = guild_config.get("key_channel_id")
    if not key_channel_id:
        try:
            err_msg = await ctx.send("❌ Key distribution channel has not been configured yet. Use `!setkeychannel <channel>`.")
            await asyncio.sleep(5)
            await err_msg.delete()
        except Exception:
            pass
        return

    if str(ctx.channel.id) != str(key_channel_id):
        try:
            authorized_channel = ctx.guild.get_channel(int(key_channel_id))
            mention_str = authorized_channel.mention if authorized_channel else f"channel ID {key_channel_id}"
            err_msg = await ctx.send(f"❌ This command can only be used in {mention_str}.")
            await asyncio.sleep(5)
            await err_msg.delete()
        except Exception:
            pass
        return

    # Check if free claiming is disabled
    if not guild_config.get("claimkey_enabled", True):
        try:
            err_msg = await ctx.send("❌ Free key claiming is currently disabled by administrators.")
            await asyncio.sleep(5)
            await err_msg.delete()
        except Exception:
            pass
        return

    # Check if already claimed
    if has_user_claimed(ctx.author.id):
        try:
            err_msg = await ctx.send("❌ You have already claimed a free key! Limit: 1 per user.")
            await asyncio.sleep(5)
            await err_msg.delete()
        except Exception:
            pass
        return

    # Test DM first before calling API
    try:
        test_embed = discord.Embed(description="Generating your license key...", color=discord.Color.blue())
        test_msg = await ctx.author.send(embed=test_embed)
    except discord.Forbidden:
        try:
            err_msg = await ctx.send(f"❌ {ctx.author.mention}, I couldn't send you a Direct Message. Please open your DMs and try again.")
            await asyncio.sleep(5)
            await err_msg.delete()
        except Exception:
            pass
        return

    # Generate key from API (1 Day)
    generated_key = await call_key_generator_api(1)
    if not generated_key:
        try:
            await test_msg.delete()
            err_msg = await ctx.send("❌ Failed to generate key. Please contact staff or try again later.")
            await asyncio.sleep(5)
            await err_msg.delete()
        except Exception:
            pass
        return

    # Success! Save claim to DB and edit DM message
    mark_user_claimed(ctx.author.id, generated_key, ctx.guild.id, revealed=True)
    success_embed = discord.Embed(
        title="<:tik:1528280512169246894>  **YOUR SECURE ACCESS**",
        description=(
            f"**Your personal credentials are below. Never share it.**\n"
            f"<:trick_supreme:1528280687126253648>  **LICENSE KEY — Tap to copy**\n"
            f"```\n"
            f"{generated_key}```\n\n"
            f"<:arrow:1528280452232642570>  **DOWNLOAD BYPASS EXE**\n"
            f"[Click here to download Bypass Emulator](https://www.dropbox.com/scl/fi/u9czoect0rv5w2o9v0h11/AXC-LIB-BYPASS.exe?rlkey=wjwke1emn688j44lv7tj6wxvv&st=sh84trcd&dl=0)\n"
            f"<:arrow:1528280452232642570>  **DOWNLOAD FREEFIRE APK**\n"
            f"[Click here to download Free Fire APK](https://www.dropbox.com/scl/fi/vqhivuvpvfxhjw0ub3p2v/FREE-FIRE-OB54-V7A.xapk?rlkey=cmjfz7cyr8pd84x0mpedt1i3u&st=35uogn0d&dl=0)\n"
            f"<a:Warning:1528328561361158245>  **IMPORTANT**\n"
            f"**This LICENSE KEY will only work on the EXE given above.**"
        ),
        color=discord.Color.red()
    )
    await test_msg.edit(embed=success_embed)
    notification_text = f"📬 {ctx.author.mention}, I have DMed you your license key!"

    try:
        success_msg = await ctx.send(notification_text)
        await asyncio.sleep(5)
        await success_msg.delete()
    except Exception:
        pass

@bot.command(name="genkey")
async def prefix_genkey(ctx, duration: int = None):
    guild_config = get_guild_config(ctx.guild.id)
    authorized_users = guild_config.get("authorized_users", [])
    
    # Check authorization (Must be authorized user or Administrator)
    is_authorized = str(ctx.author.id) in authorized_users or ctx.author.guild_permissions.administrator
    if not is_authorized:
        return await ctx.send("❌ You are not authorized to use this command.")

    if not duration:
        return await ctx.send("❌ Please specify a duration. Example: `!genkey 3` (Valid options: 1, 3, 7, 15, 30)")

    if duration not in [1, 3, 7, 15, 30]:
        return await ctx.send("❌ Invalid duration. Authorized users can only generate: `1`, `3`, `7`, `15`, `30` days.")

    # Call API
    msg_status = await ctx.send("⏳ Generating key...")
    generated_key = await call_key_generator_api(duration)
    if not generated_key:
        return await msg_status.edit(content="❌ Failed to generate key from API. Verify API settings.")

    embed = discord.Embed(
        title="🔑 License Key Generated",
        description=(
            f"**Duration:** {duration} Day(s)\n"
            f"**Key:** `{generated_key}`\n\n"
            f"Generated by: {ctx.author.mention}"
        ),
        color=discord.Color.green()
    )
    await msg_status.delete()
    await ctx.send(embed=embed)

@bot.command(name="authorize")
@commands.has_permissions(administrator=True)
async def prefix_authorize(ctx, sub_cmd: str = None, user: discord.Member = None):
    guild_config = get_guild_config(ctx.guild.id)
    if "authorized_users" not in guild_config:
        guild_config["authorized_users"] = []

    if not sub_cmd:
        return await ctx.send("❌ Usage: `!authorize user <@user>` or `!authorize list`")

    if sub_cmd.lower() == "list":
        users_list = guild_config["authorized_users"]
        if not users_list:
            return await ctx.send("ℹ️ No users are currently authorized.")
        
        mentions = [f"<@{uid}> (`{uid}`)" for uid in users_list]
        embed = discord.Embed(
            title="👥 Authorized Users List",
            description="\n".join(mentions),
            color=discord.Color.blue()
        )
        return await ctx.send(embed=embed)

    if sub_cmd.lower() == "user":
        if not user:
            return await ctx.send("❌ Please mention a user to authorize. Example: `!authorize user @username`")
            
        uid_str = str(user.id)
        if uid_str in guild_config["authorized_users"]:
            return await ctx.send(f"⚠️ {user.mention} is already authorized.")

        guild_config["authorized_users"].append(uid_str)
        save_guild_config(ctx.guild.id, guild_config)
        return await ctx.send(f"✅ Successfully authorized {user.mention} to generate keys (1, 3, 7, 15, 30 days).")

    return await ctx.send("❌ Invalid sub-command. Use `user` or `list`.")

@bot.command(name="unauthorize")
@commands.has_permissions(administrator=True)
async def prefix_unauthorize(ctx, sub_cmd: str = None, user: discord.Member = None):
    guild_config = get_guild_config(ctx.guild.id)
    if "authorized_users" not in guild_config:
        guild_config["authorized_users"] = []

    if not sub_cmd or sub_cmd.lower() != "user" or not user:
        return await ctx.send("❌ Usage: `!unauthorize user <@user>`")

    uid_str = str(user.id)
    if uid_str not in guild_config["authorized_users"]:
        return await ctx.send(f"❌ {user.mention} is not authorized.")

    guild_config["authorized_users"].remove(uid_str)
    save_guild_config(ctx.guild.id, guild_config)
    return await ctx.send(f"✅ Removed authorization for {user.mention}.")

@bot.command(name="resetclaim")
@commands.has_permissions(administrator=True)
async def prefix_resetclaim(ctx, target: str = None):
    if not target:
        return await ctx.send("❌ Usage: `!resetclaim <@user_mention>` or `!resetclaim all`")

    if target.lower() == "all":
        reset_all_claims()
        return await ctx.send("✅ Successfully reset all user claims! Everyone can now claim a free key again.")

    # Try resolving user from mention or ID
    user = None
    if ctx.message.mentions:
        user = ctx.message.mentions[0]
    else:
        try:
            user_id = int(target)
            user = await bot.fetch_user(user_id)
        except Exception:
            pass

    if not user:
        return await ctx.send("❌ User not found. Please mention the user or provide a valid user ID.")

    success = reset_user_claim(user.id)
    if success:
        return await ctx.send(f"✅ Successfully reset claim limit for {user.mention}. They can now claim a free key again!")
    else:
        return await ctx.send(f"❌ {user.mention} has not claimed any key yet.")

# ---------- Run Bot ----------
from web import run_web, set_panel_callback
import asyncio

async def trigger_panel_send(guild_id: int, channel_id: int):
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except:
            return
            
    guild_config = get_guild_config(guild_id)
    banner_url = guild_config.get("ticket_banner", "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExNXprYXQ0Z3QzeGMweDFoZmYzZnBqMTBsamJ4cDVrNjg5eDdiM2g2MCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/7RwanQsnkwtQoM1lMo/giphy.gif")
    logo_url = guild_config.get("ticket_logo", "https://media.discordapp.net/attachments/1448757915035897886/1506560802185019472/axcmainlogi-removebg.png?ex=6a3b8895&is=6a3a3715&hm=64d12abe8a8e1d146cf1d83246745bbbfebbb508cf1f0a96f5475a618d20fd7a&=&format=webp&quality=lossless&width=978&height=978")

    embed = discord.Embed(
        title="<:support:1463880645016027298> Support Ticket System",
        description="Need help? Create a ticket and our staff will assist you shortly.",
        color=discord.Color.red()
    )
    embed.set_image(url=banner_url)
    embed.set_thumbnail(url=logo_url)
    embed.add_field(
        name="<:rules:1463880669296984227> Rules",
        value="• Do not create tickets for fun\n• No abusive language\n• Discuss TOS & warranty before purchase",
        inline=False
    )
    embed.add_field(
        name="<a:times:1463880691107233802> Response Time",
        value="Staff will respond within **1 to 5 minutes** (usually faster).",
        inline=False
    )
    embed.set_footer(text="Anik X Cheats • Ticket System", icon_url=logo_url)
    embed.timestamp = discord.utils.utcnow()

    await channel.send(embed=embed, view=TicketTypeSelectView())

def handle_panel_request(guild_id: int, channel_id: int):
    asyncio.run_coroutine_threadsafe(trigger_panel_send(guild_id, channel_id), bot.loop)

async def start_bot_with_retry():
    while True:
        try:
            await bot.start(TOKEN)
        except discord.HTTPException as e:
            if e.status == 429:
                print(f"⚠️ [Discord Rate Limit] Discord IP temporarily blocked (429). Retrying in 45 seconds... ({e})")
                await asyncio.sleep(45)
            else:
                print(f"❌ [Discord HTTP Error] {e}. Retrying in 20 seconds...")
                await asyncio.sleep(20)
        except Exception as e:
            print(f"❌ [Bot Error] Unexpected error: {e}. Retrying in 15 seconds...")
            await asyncio.sleep(15)

if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN not found in .env")
    else:
        set_panel_callback(handle_panel_request)
        run_web(bot)
        try:
            asyncio.run(start_bot_with_retry())
        except (KeyboardInterrupt, SystemExit):
            print("Bot shutdown gracefully.")
