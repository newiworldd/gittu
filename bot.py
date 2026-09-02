import discord
from discord.ext import commands, tasks
from discord import app_commands
import os
import asyncio
import urllib.parse
import aiohttp
from dotenv import load_dotenv
from db import get_guild_config, save_guild_config, record_verified_member, get_all_oauth_members, delete_oauth_member
from web import run_web, set_verify_callback

# ---------- Configuration ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ---------- Verification View ----------
def create_verify_view(guild_id: int):
    client_id = os.getenv("DISCORD_CLIENT_ID", "")
    base_redirect = os.getenv("DISCORD_REDIRECT_URI", "").replace("/callback", "").rstrip("/")
    if not base_redirect:
        base_redirect = "https://verify.anikxcheatx.com"
    redirect_uri = f"{base_redirect}/verify/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify guilds.join",
        "state": str(guild_id)
    }
    discord_oauth_url = "https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(params)

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label="Verify Now",
        url=discord_oauth_url,
        style=discord.ButtonStyle.link,
        emoji="🛡️"
    ))
    return view

class WelcomeDMBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.loop.create_task(self.tree.sync())  # background sync
        self.status_task.start()
        self.check_deauthorized_task.start()

    @tasks.loop(minutes=2)
    async def status_task(self):
        server_count = len(self.guilds)
        await self.change_presence(
            activity=discord.Streaming(
                name=f"Welcoming {server_count} Servers | Anik X Suite",
                url="https://twitch.tv/anikxcheats"
            )
        )

    @tasks.loop(minutes=15)
    async def check_deauthorized_task(self):
        """Periodically check if verified members deauthorized the bot, and remove role if so."""
        members = get_all_oauth_members()
        if not members:
            return

        async with aiohttp.ClientSession() as session:
            for m in members:
                user_id_str = m.get("user_id")
                access_token = m.get("access_token")
                guild_id_str = m.get("guild_id")
                if not user_id_str or not access_token:
                    continue

                try:
                    async with session.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bearer {access_token}"}) as resp:
                        if resp.status == 401:  # Deauthorized / Revoked!
                            user_id = int(user_id_str)
                            username = m.get("username", user_id_str)
                            print(f"⚠️ [Deauthorized] User {username} ({user_id}) deauthorized the bot. Removing Verified Role...", flush=True)
                            delete_oauth_member(user_id_str)

                            # Strip role from target guilds
                            target_guilds = [self.get_guild(int(guild_id_str))] if guild_id_str else self.guilds
                            for guild in target_guilds:
                                if not guild:
                                    continue
                                config = get_guild_config(guild.id)
                                role_id = config.get("verify_role_id")
                                if role_id:
                                    role = guild.get_role(int(role_id))
                                    member = guild.get_member(user_id)
                                    if not member:
                                        try:
                                            member = await guild.fetch_member(user_id)
                                        except:
                                            pass
                                    if member and role and role in member.roles:
                                        try:
                                            await member.remove_roles(role, reason="User deauthorized Discord Verification")
                                            print(f"✅ [Deauthorized] Successfully removed @{role.name} from {member.name} in {guild.name}", flush=True)
                                        except Exception as re:
                                            print(f"❌ Error removing role: {re}", flush=True)
                except Exception as e:
                    pass

    @check_deauthorized_task.before_loop
    @status_task.before_loop
    async def before_tasks(self):
        await self.wait_until_ready()

    async def on_ready(self):
        print(f"==================================================", flush=True)
        print(f"🚀 [Welcome & DM Bot] Logged in as: {self.user} (ID: {self.user.id})", flush=True)
        print(f"🌐 Serving {len(self.guilds)} Guilds", flush=True)
        print(f"==================================================", flush=True)

    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        guild_config = get_guild_config(guild.id)

        # 1. Auto-Role Assignment
        if guild_config.get("autorole_enabled"):
            role_id = guild_config.get("autorole_role_id")
            if role_id:
                try:
                    role = guild.get_role(int(role_id))
                    if role:
                        await member.add_roles(role, reason="Auto-Role on Join")
                        print(f"[AutoRole] Assigned {role.name} to {member.display_name} in {guild.name}")
                except discord.Forbidden:
                    print(f"[AutoRole Error] Lacking permission to assign role in {guild.name}")
                except Exception as e:
                    print(f"[AutoRole Error] {e}")

        # 2. Server Welcome Message / Embed
        if guild_config.get("welcome_enabled"):
            welcome_channel_id = guild_config.get("welcome_channel_id")
            if welcome_channel_id:
                channel = guild.get_channel(int(welcome_channel_id))
                if not channel:
                    try:
                        channel = await guild.fetch_channel(int(welcome_channel_id))
                    except:
                        pass
                if channel:
                    title = guild_config.get("welcome_title") or f"Welcome to {guild.name} 🚀"
                    desc = guild_config.get("welcome_description") or (
                        f"Hey {member.mention}, welcome to the core of **{guild.name}**!\n\n"
                        f"**Welcome**\n"
                        f"You've just entered a space built for **cyber minds, devs, and masterminds**.\n\n"
                        f"📌 **Before you start:**\n"
                        f"• Read the rules to stay safe\n"
                        f"• Respect all members\n"
                        f"• No spam / no toxic behavior"
                    )
                    img = guild_config.get("welcome_image") or "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif"

                    # Replace placeholders
                    title = title.replace("{server_name}", guild.name).replace("{member_count}", str(guild.member_count))
                    desc = desc.replace("{server_name}", guild.name).replace("{user_mention}", member.mention).replace("{member_count}", str(guild.member_count))

                    try:
                        embed = discord.Embed(
                            title=title,
                            description=desc,
                            color=0x2ecc71
                        )
                        if member.display_avatar:
                            embed.set_thumbnail(url=member.display_avatar.url)
                        elif guild.icon:
                            embed.set_thumbnail(url=guild.icon.url)
                            
                        if img and img.startswith("http"):
                            embed.set_image(url=img)
                            
                        embed.set_footer(text=f"Member #{guild.member_count} • {guild.name}", icon_url=guild.icon.url if guild.icon else None)
                        embed.timestamp = discord.utils.utcnow()
                        
                        await channel.send(content=member.mention, embed=embed)
                        print(f"🎉 [Welcome] Sent welcome embed for {member.display_name} in #{channel.name}")
                    except discord.Forbidden:
                        print(f"[Welcome Error] Cannot send message in channel {welcome_channel_id} (Forbidden)")
                    except Exception as e:
                        print(f"[Welcome Error] {e}")

        # 3. Public Chat Welcome Tagger (5s auto-delete)
        if guild_config.get("public_chat_welcome_enabled"):
            pc_channel_id = guild_config.get("public_chat_welcome_channel_id")
            if pc_channel_id:
                pc_channel = guild.get_channel(int(pc_channel_id))
                if pc_channel:
                    pc_msg = guild_config.get("public_chat_welcome_message") or "Hey {user_mention}, welcome to the chat! Make sure to read the rules and stay safe. 🚀"
                    pc_msg = pc_msg.replace("{server_name}", guild.name).replace("{user_mention}", member.mention).replace("{member_count}", str(guild.member_count))
                    try:
                        pc_sent = await pc_channel.send(pc_msg)
                        await asyncio.sleep(5)
                        await pc_sent.delete()
                    except (discord.Forbidden, discord.NotFound):
                        pass
                    except Exception as e:
                        print(f"[Public Chat Welcome Error] {e}")

        # 4. DM Welcome Message
        if guild_config.get("dm_welcome_enabled"):
            dm_msg = guild_config.get("dm_welcome_message") or f"Welcome to {guild.name}! We are thrilled to have you here."
            dm_msg = dm_msg.replace("{server_name}", guild.name).replace("{user_mention}", member.mention).replace("{member_count}", str(guild.member_count))
            ticket_link = guild_config.get("dm_welcome_ticket_link")
            dm_image = guild_config.get("dm_welcome_image")

            embed = discord.Embed(
                title=f"Welcome to {guild.name}! 🎉",
                description=dm_msg,
                color=0xe74c3c
            )
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
            if dm_image and dm_image.startswith("http"):
                embed.set_image(url=dm_image)
            embed.set_footer(text=f"Sent from {guild.name}")
            embed.timestamp = discord.utils.utcnow()

            view = None
            if ticket_link and ticket_link.startswith("http"):
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Open Ticket / Visit Server", url=ticket_link, style=discord.ButtonStyle.link, emoji="🎫"))

            try:
                if view:
                    await member.send(embed=embed, view=view)
                else:
                    await member.send(embed=embed)
                print(f"[DM Welcome] Sent welcome DM to {member.display_name}")
            except discord.Forbidden:
                print(f"[DM Welcome] Could not send DM to {member.display_name} (DMs closed)")
            except Exception as e:
                print(f"[DM Welcome Error] {e}")

    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild
        guild_config = get_guild_config(guild.id)

        if guild_config.get("leave_enabled"):
            leave_channel_id = guild_config.get("leave_channel_id")
            if leave_channel_id:
                channel = guild.get_channel(int(leave_channel_id))
                if channel:
                    msg = guild_config.get("leave_message") or "**{username}** has left the server. 😢"
                    msg = msg.replace("{username}", member.name).replace("{user_mention}", member.mention).replace("{server_name}", guild.name).replace("{member_count}", str(guild.member_count))
                    try:
                        embed = discord.Embed(
                            description=msg,
                            color=0x95a5a6
                        )
                        if member.display_avatar:
                            embed.set_thumbnail(url=member.display_avatar.url)
                        embed.set_footer(text=f"Remaining Members: {guild.member_count}")
                        embed.timestamp = discord.utils.utcnow()
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass
                    except Exception as e:
                        print(f"[Leave Module Error] {e}")


bot = WelcomeDMBot()

# ==================== SLASH COMMANDS ====================

@bot.tree.command(name="setup_welcome", description="Configure the server welcome message channel")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(channel="The channel where welcome messages will be sent", enable="Enable or disable welcome messages")
async def setup_welcome_cmd(interaction: discord.Interaction, channel: discord.TextChannel, enable: bool = True):
    config = get_guild_config(interaction.guild.id)
    config["welcome_enabled"] = enable
    config["welcome_channel_id"] = str(channel.id)
    save_guild_config(interaction.guild.id, config)

    embed = discord.Embed(
        title="✅ Welcome System Configured",
        description=f"Welcome messages are now **{'Enabled' if enable else 'Disabled'}** in {channel.mention}.\nUse the Web Dashboard to customize embeds and banners.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setup_dm", description="Toggle Direct Message (DM) welcome on/off")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(enable="Enable or disable DM welcome messages")
async def setup_dm_cmd(interaction: discord.Interaction, enable: bool):
    config = get_guild_config(interaction.guild.id)
    config["dm_welcome_enabled"] = enable
    save_guild_config(interaction.guild.id, config)

    embed = discord.Embed(
        title="✅ DM Welcome System Updated",
        description=f"DM Welcome messages are now **{'Enabled' if enable else 'Disabled'}**.\nManage DM content and price lists directly from the Web Dashboard.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setup_autorole", description="Set a role to automatically give to new members")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(role="Role to assign to new members", enable="Enable or disable auto-role")
async def setup_autorole_cmd(interaction: discord.Interaction, role: discord.Role, enable: bool = True):
    config = get_guild_config(interaction.guild.id)
    config["autorole_enabled"] = enable
    config["autorole_role_id"] = str(role.id)
    save_guild_config(interaction.guild.id, config)

    embed = discord.Embed(
        title="✅ Auto-Role Configured",
        description=f"Auto-Role is now **{'Enabled' if enable else 'Disabled'}** with role {role.mention}.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="test_welcome", description="Send a test welcome message to a channel")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(channel="Target channel to test")
async def test_welcome_cmd(interaction: discord.Interaction, channel: discord.TextChannel = None):
    target_channel = channel or interaction.channel
    config = get_guild_config(interaction.guild.id)
    guild = interaction.guild
    member = interaction.user

    title = config.get("welcome_title") or f"Welcome to {guild.name} 🚀"
    desc = config.get("welcome_description") or f"Hey {member.mention}, welcome to **{guild.name}**!"
    img = config.get("welcome_image", "")

    title = title.replace("{server_name}", guild.name).replace("{member_count}", str(guild.member_count))
    desc = desc.replace("{server_name}", guild.name).replace("{user_mention}", member.mention).replace("{member_count}", str(guild.member_count))

    embed = discord.Embed(
        title=title,
        description=desc,
        color=0x2b2d31
    )
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)
    if img and img.startswith("http"):
        embed.set_image(url=img)
    embed.set_footer(text=f"Member #{guild.member_count} • {guild.name} (TEST PREVIEW)")
    embed.timestamp = discord.utils.utcnow()

    await target_channel.send(content=f"🧪 **[Test Preview]** {member.mention}", embed=embed)
    await interaction.response.send_message(f"✅ Test welcome sent to {target_channel.mention}", ephemeral=True)

@bot.tree.command(name="test_dm", description="Send a test DM welcome to your inbox")
@app_commands.checks.has_permissions(administrator=True)
async def test_dm_cmd(interaction: discord.Interaction):
    config = get_guild_config(interaction.guild.id)
    guild = interaction.guild
    member = interaction.user

    dm_msg = config.get("dm_welcome_message") or f"Welcome to {guild.name}! We are thrilled to have you here."
    dm_msg = dm_msg.replace("{server_name}", guild.name).replace("{user_mention}", member.mention).replace("{member_count}", str(guild.member_count))
    ticket_link = config.get("dm_welcome_ticket_link")
    dm_image = config.get("dm_welcome_image")

    embed = discord.Embed(
        title=f"Welcome to {guild.name}! 🎉 (TEST)",
        description=dm_msg,
        color=0xe74c3c
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    if dm_image and dm_image.startswith("http"):
        embed.set_image(url=dm_image)
    embed.set_footer(text=f"Sent from {guild.name} (Test Preview)")
    embed.timestamp = discord.utils.utcnow()

    view = None
    if ticket_link and ticket_link.startswith("http"):
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open Ticket / Visit Server", url=ticket_link, style=discord.ButtonStyle.link, emoji="🎫"))

    try:
        if view:
            await member.send(embed=embed, view=view)
        else:
            await member.send(embed=embed)
        await interaction.response.send_message("✅ Check your Direct Messages (DMs) for the test preview!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to send DM: {e}. Please ensure your DMs are open.", ephemeral=True)

@bot.tree.command(name="setup_verify", description="Configure the verification role and channel")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(role="Role to grant upon verification", channel="Channel where verification will take place", enable="Enable or disable verification")
async def setup_verify_cmd(interaction: discord.Interaction, role: discord.Role, channel: discord.TextChannel = None, enable: bool = True):
    config = get_guild_config(interaction.guild.id)
    config["verify_enabled"] = enable
    config["verify_role_id"] = str(role.id)
    if channel:
        config["verify_channel_id"] = str(channel.id)
    save_guild_config(interaction.guild.id, config)

    embed = discord.Embed(
        title="✅ Verification System Configured",
        description=f"Verification is now **{'Enabled' if enable else 'Disabled'}**.\n• Verified Role: {role.mention}\n• Channel: {channel.mention if channel else 'Current'}\n\nUse `/send_verify_panel` or the Web Dashboard to post the verification panel.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="send_verify_panel", description="Post the verification embed with the 'Verify Now' button")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(channel="Target channel to post verification panel (defaults to current)")
async def send_verify_panel_cmd(interaction: discord.Interaction, channel: discord.TextChannel = None):
    await interaction.response.defer(ephemeral=True)
    target_channel = channel or interaction.channel
    guild = interaction.guild
    guild_config = get_guild_config(guild.id)

    title = guild_config.get("verify_title") or f"🛡️ {guild.name} Member Verification"
    desc = guild_config.get("verify_description") or f"Welcome to **{guild.name}**!\n\nClick the **Verify Now** button below to get access to all channels and features."
    img = guild_config.get("verify_image", "")

    title = title.replace("{server_name}", guild.name)
    desc = desc.replace("{server_name}", guild.name)

    embed = discord.Embed(
        title=title,
        description=desc,
        color=0x2ecc71
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    if img and img.startswith("http"):
        embed.set_image(url=img)
    embed.set_footer(text=f"Anik X Suite • {guild.name} Security")
    embed.timestamp = discord.utils.utcnow()

    await target_channel.send(embed=embed, view=create_verify_view(guild.id))
    await interaction.followup.send(f"✅ Verification panel sent to {target_channel.mention}!", ephemeral=True)

@bot.tree.command(name="sync_deauthorized", description="Check and remove Verified Role from members who deauthorized the bot")
@app_commands.checks.has_permissions(administrator=True)
async def sync_deauthorized_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    config = get_guild_config(guild.id)
    role_id = config.get("verify_role_id")
    if not role_id:
        return await interaction.followup.send("❌ Verification role is not configured.", ephemeral=True)

    role = guild.get_role(int(role_id))
    members = get_all_oauth_members(str(guild.id)) or get_all_oauth_members()
    removed_count = 0

    async with aiohttp.ClientSession() as session:
        for m in members:
            access_token = m.get("access_token")
            user_id_str = m.get("user_id")
            if not access_token or not user_id_str:
                continue

            try:
                async with session.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bearer {access_token}"}) as resp:
                    if resp.status == 401:  # Deauthorized!
                        user_id = int(user_id_str)
                        delete_oauth_member(user_id_str)
                        member = guild.get_member(user_id)
                        if not member:
                            try:
                                member = await guild.fetch_member(user_id)
                            except:
                                pass
                        if member and role and role in member.roles:
                            await member.remove_roles(role, reason="Manual sync: User deauthorized Verification")
                            removed_count += 1
            except:
                pass

    await interaction.followup.send(f"🔍 **Deauthorization Sync Complete!**\nScanned members. Removed role from **{removed_count}** users who deauthorized.", ephemeral=True)

async def trigger_verify_panel_send(guild_id: int, channel_id: int):
    try:
        print(f"🚀 [Verify Panel] Sending verification panel to Guild: {guild_id}, Channel: {channel_id}...", flush=True)
        guild = bot.get_guild(guild_id)
        if not guild:
            try:
                guild = await bot.fetch_guild(guild_id)
            except Exception as ge:
                print(f"❌ [Verify Panel] Guild fetch error: {ge}", flush=True)
                
        if not guild:
            print(f"❌ [Verify Panel] Bot is not in guild {guild_id}!", flush=True)
            return

        channel = guild.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception as ce:
                print(f"❌ [Verify Panel] Channel fetch error: {ce}", flush=True)

        if not channel:
            print(f"❌ [Verify Panel] Channel {channel_id} not found!", flush=True)
            return

        guild_config = get_guild_config(guild_id)
        title = guild_config.get("verify_title") or f"🛡️ {guild.name} Member Verification"
        desc = guild_config.get("verify_description") or f"Welcome to **{guild.name}**!\n\nClick the **Verify Now** button below to get access to all channels."
        img = guild_config.get("verify_image", "")

        title = title.replace("{server_name}", guild.name)
        desc = desc.replace("{server_name}", guild.name)

        embed = discord.Embed(
            title=title,
            description=desc,
            color=0x2ecc71
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if img and img.startswith("http"):
            embed.set_image(url=img)
        embed.set_footer(text=f"Anik X Suite • {guild.name} Security")
        embed.timestamp = discord.utils.utcnow()

        await channel.send(embed=embed, view=create_verify_view(guild.id))
        print(f"✅ [Verify Panel] Successfully sent verification panel to #{channel.name} ({channel.id})!", flush=True)
    except discord.Forbidden:
        print(f"❌ [Verify Panel] Missing Permission: Bot needs 'Send Messages' and 'Embed Links' in channel {channel_id}!", flush=True)
    except Exception as e:
        print(f"❌ [Verify Panel] Error sending panel: {e}", flush=True)

def handle_verify_panel_request(guild_id: int, channel_id: int):
    if bot.loop and bot.loop.is_running():
        asyncio.run_coroutine_threadsafe(trigger_verify_panel_send(guild_id, channel_id), bot.loop)
    else:
        print("❌ [Verify Panel] Bot event loop is not running yet!", flush=True)

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
        print("❌ Error: DISCORD_TOKEN is missing from .env file!", flush=True)
    else:
        set_verify_callback(handle_verify_panel_request)
        # Start Flask Web Dashboard concurrently
        run_web(bot)
        print("🤖 [Discord Bot] Starting bot runner...", flush=True)
        try:
            asyncio.run(start_bot_with_retry())
        except (KeyboardInterrupt, SystemExit):
            print("Bot shutdown gracefully.")
