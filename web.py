from flask import Flask, render_template, redirect, url_for, request, session, jsonify
from flask_discord import DiscordOAuth2Session, requires_authorization, Unauthorized
import os
from threading import Thread
from dotenv import load_dotenv
from db import get_guild_config, save_guild_config, get_verified_count, save_oauth_member, get_all_oauth_members
import discord
import asyncio
import requests
import urllib.parse

load_dotenv()
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "welcome-dm-bot-super-secret-key")

# Discord OAuth2 Config
app.config["DISCORD_CLIENT_ID"] = os.getenv("DISCORD_CLIENT_ID", "")
app.config["DISCORD_CLIENT_SECRET"] = os.getenv("DISCORD_CLIENT_SECRET", "")
app.config["DISCORD_REDIRECT_URI"] = os.getenv("DISCORD_REDIRECT_URI", "http://127.0.0.1:5000/callback")
app.config["DISCORD_BOT_TOKEN"] = os.getenv("DISCORD_TOKEN", "")

discord_oauth = DiscordOAuth2Session(app)
global_bot = None
verify_callback = None

def set_verify_callback(callback_func):
    global verify_callback
    verify_callback = callback_func

@app.route("/")
def index():
    if discord_oauth.authorized:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/login")
def login():
    return discord_oauth.create_session(scope=["identify", "guilds"])

@app.route("/callback")
def callback():
    try:
        discord_oauth.callback()
    except Exception as e:
        print(f"OAuth Callback Error: {e}")
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    discord_oauth.revoke()
    return redirect(url_for("index"))

@app.route("/dashboard")
@requires_authorization
def dashboard():
    try:
        user = discord_oauth.fetch_user()
        guilds = discord_oauth.fetch_guilds()
        
        admin_guilds = []
        for g in guilds:
            if getattr(g.permissions, "administrator", False) or getattr(g.permissions, "manage_guild", False):
                config = get_guild_config(g.id)
                channels = []
                bot_in_server = False
                if global_bot:
                    discord_guild = global_bot.get_guild(g.id)
                    if discord_guild:
                        bot_in_server = True
                        channels = [{"id": str(c.id), "name": c.name} for c in discord_guild.text_channels]
                
                admin_guilds.append({
                    "id": str(g.id),
                    "name": g.name,
                    "icon_url": g.icon_url or "https://cdn.discordapp.com/embed/avatars/0.png",
                    "config": config,
                    "channels": channels,
                    "bot_in_server": bot_in_server
                })
        
        return render_template("dashboard.html", user=user, guilds=admin_guilds)
    except Exception as e:
        import traceback
        return f"<pre>{traceback.format_exc()}</pre>"

@app.route("/manage/<int:guild_id>")
@requires_authorization
def manage(guild_id):
    user = discord_oauth.fetch_user()
    guilds = discord_oauth.fetch_guilds()
    
    target_guild = next((g for g in guilds if g.id == guild_id), None)
    if not target_guild or not (getattr(target_guild.permissions, "administrator", False) or getattr(target_guild.permissions, "manage_guild", False)):
        return redirect(url_for("dashboard"))
        
    config = get_guild_config(guild_id)
    channels = []
    roles = []
    bot_in_server = False
    
    if global_bot:
        discord_guild = global_bot.get_guild(guild_id)
        if discord_guild:
            bot_in_server = True
            channels = [{"id": str(c.id), "name": c.name} for c in discord_guild.text_channels]
            roles = [{"id": str(r.id), "name": r.name} for r in discord_guild.roles if r.name != "@everyone"]
            
    guild_data = {
        "id": str(target_guild.id),
        "name": target_guild.name,
        "icon_url": target_guild.icon_url or "https://cdn.discordapp.com/embed/avatars/0.png",
        "config": config,
        "channels": channels,
        "roles": roles,
        "bot_in_server": bot_in_server,
        "verified_count": get_verified_count(guild_id)
    }

    return render_template("manage.html", user=user, guild=guild_data)

@app.route("/set_welcome", methods=["POST"])
@requires_authorization
def set_welcome():
    guild_id = request.form.get("guild_id")
    welcome_enabled = request.form.get("welcome_enabled") == "on"
    welcome_as_embed = request.form.get("welcome_as_embed") == "on"
    channel_id = request.form.get("channel_id")
    welcome_title = request.form.get("welcome_title")
    welcome_description = request.form.get("welcome_description")
    welcome_image = request.form.get("welcome_image")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["welcome_enabled"] = welcome_enabled
            config["welcome_as_embed"] = welcome_as_embed
            if channel_id:
                config["welcome_channel_id"] = channel_id
            if welcome_title is not None:
                config["welcome_title"] = welcome_title
            if welcome_description is not None:
                config["welcome_description"] = welcome_description
            if welcome_image is not None:
                config["welcome_image"] = welcome_image
                
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/set_public_chat_welcome", methods=["POST"])
@requires_authorization
def set_public_chat_welcome():
    guild_id = request.form.get("guild_id")
    public_chat_welcome_enabled = request.form.get("public_chat_welcome_enabled") == "on"
    channel_id = request.form.get("channel_id")
    public_chat_welcome_message = request.form.get("public_chat_welcome_message")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["public_chat_welcome_enabled"] = public_chat_welcome_enabled
            if channel_id:
                config["public_chat_welcome_channel_id"] = channel_id
            if public_chat_welcome_message is not None:
                config["public_chat_welcome_message"] = public_chat_welcome_message
                
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/set_dm_welcome", methods=["POST"])
@requires_authorization
def set_dm_welcome():
    guild_id = request.form.get("guild_id")
    dm_welcome_enabled = request.form.get("dm_welcome_enabled") == "on"
    dm_welcome_message = request.form.get("dm_welcome_message")
    dm_welcome_ticket_link = request.form.get("dm_welcome_ticket_link")
    dm_welcome_image = request.form.get("dm_welcome_image")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["dm_welcome_enabled"] = dm_welcome_enabled
            if dm_welcome_message is not None:
                config["dm_welcome_message"] = dm_welcome_message
            if dm_welcome_ticket_link is not None:
                config["dm_welcome_ticket_link"] = dm_welcome_ticket_link
            if dm_welcome_image is not None:
                config["dm_welcome_image"] = dm_welcome_image
                
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/set_autorole", methods=["POST"])
@requires_authorization
def set_autorole():
    guild_id = request.form.get("guild_id")
    autorole_enabled = request.form.get("autorole_enabled") == "on"
    autorole_role_id = request.form.get("autorole_role_id")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["autorole_enabled"] = autorole_enabled
            config["autorole_role_id"] = autorole_role_id if autorole_role_id else None
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/set_leave_config", methods=["POST"])
@requires_authorization
def set_leave_config():
    guild_id = request.form.get("guild_id")
    leave_enabled = request.form.get("leave_enabled") == "on"
    channel_id = request.form.get("channel_id")
    leave_message = request.form.get("leave_message")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["leave_enabled"] = leave_enabled
            if channel_id:
                config["leave_channel_id"] = channel_id
            if leave_message is not None:
                config["leave_message"] = leave_message
                
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/test_welcome_web", methods=["POST"])
@requires_authorization
def test_welcome_web():
    guild_id = request.form.get("guild_id")
    channel_id = request.form.get("channel_id")
    
    if global_bot and guild_id and channel_id:
        try:
            guild_id_int = int(guild_id)
            channel_id_int = int(channel_id)
            
            async def send():
                try:
                    guild = global_bot.get_guild(guild_id_int)
                    channel = global_bot.get_channel(channel_id_int)
                    if channel and guild:
                        config = get_guild_config(guild_id_int)
                        title = config.get("welcome_title") or f"Welcome to {guild.name} 🚀"
                        desc = config.get("welcome_description") or f"Hey @User, welcome to **{guild.name}**!"
                        img = config.get("welcome_image", "")
                        
                        embed = discord.Embed(
                            title=title.replace("{server_name}", guild.name).replace("{member_count}", str(guild.member_count)),
                            description=desc.replace("{server_name}", guild.name).replace("{user_mention}", "@User").replace("{member_count}", str(guild.member_count)),
                            color=0x2b2d31
                        )
                        if img and img.startswith("http"):
                            embed.set_image(url=img)
                        embed.set_footer(text=f"Test Welcome • {guild.name}")
                        embed.timestamp = discord.utils.utcnow()
                        await channel.send(content="🧪 **[Web Test]**", embed=embed)
                except Exception as e:
                    print(f"Error in async test send: {e}")
            
            asyncio.run_coroutine_threadsafe(send(), global_bot.loop)
        except Exception as e:
            print(f"Error launching test send: {e}")
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/set_verify_config", methods=["POST"])
@requires_authorization
def set_verify_config():
    guild_id = request.form.get("guild_id")
    verify_enabled = request.form.get("verify_enabled") == "on"
    channel_id = request.form.get("channel_id")
    role_id = request.form.get("role_id")
    verify_title = request.form.get("verify_title")
    verify_description = request.form.get("verify_description")
    verify_image = request.form.get("verify_image")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["verify_enabled"] = verify_enabled
            if channel_id:
                config["verify_channel_id"] = channel_id
            if role_id:
                config["verify_role_id"] = role_id
            if verify_title is not None:
                config["verify_title"] = verify_title
            if verify_description is not None:
                config["verify_description"] = verify_description
            if verify_image is not None:
                config["verify_image"] = verify_image
                
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/send_verify_panel_web", methods=["POST"])
@requires_authorization
def send_verify_panel_web():
    guild_id = request.form.get("guild_id")
    channel_id = request.form.get("channel_id")
    if global_bot and guild_id and channel_id:
        try:
            guild_id_int = int(guild_id)
            channel_id_int = int(channel_id)
            if verify_callback:
                verify_callback(guild_id_int, channel_id_int)
        except Exception as e:
            print(f"Error launching verify panel send: {e}")
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/verify/<guild_id>")
def start_oauth_verify(guild_id):
    client_id = os.getenv("DISCORD_CLIENT_ID", "")
    base_redirect = os.getenv("DISCORD_REDIRECT_URI", "").replace("/callback", "").rstrip("/")
    if not base_redirect:
        base_redirect = request.host_url.rstrip("/")
    redirect_uri = f"{base_redirect}/verify/callback"
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify guilds.join",
        "state": str(guild_id)
    }
    discord_auth_url = "https://discord.com/api/oauth2/authorize?" + urllib.parse.urlencode(params)
    return redirect(discord_auth_url)

@app.route("/verify/callback")
def oauth_verify_callback():
    code = request.args.get("code")
    guild_id = request.args.get("state")
    error = request.args.get("error")
    
    if error or not code:
        return "<h3>❌ Verification was cancelled or failed. You can close this window.</h3>", 400

    client_id = os.getenv("DISCORD_CLIENT_ID", "")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "")
    base_redirect = os.getenv("DISCORD_REDIRECT_URI", "").replace("/callback", "").rstrip("/")
    if not base_redirect:
        base_redirect = request.host_url.rstrip("/")
    redirect_uri = f"{base_redirect}/verify/callback"

    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        token_resp = requests.post("https://discord.com/api/v10/oauth2/token", data=token_data, headers=headers)
        if token_resp.status_code != 200:
            print(f"OAuth Token Exchange Error: {token_resp.text}")
            return f"<h3>❌ Token Exchange Failed. Please try verifying again.</h3>", 400

        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 604800)

        # Fetch User Profile
        user_resp = requests.get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        if user_resp.status_code != 200:
            return "<h3>❌ Failed to fetch Discord user information.</h3>", 400

        user_info = user_resp.json()
        user_id = user_info.get("id")
        username = user_info.get("username")
        avatar_hash = user_info.get("avatar")
        user_avatar = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png" if avatar_hash else "https://cdn.discordapp.com/embed/avatars/0.png"
        ip_addr = request.headers.get("X-Forwarded-For", request.remote_addr)

        # 1. Store OAuth2 Token into MongoDB
        save_oauth_member(
            user_id=user_id,
            username=username,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            guild_id=guild_id,
            ip_address=ip_addr
        )

        # 2. Add Verified Role in Discord Server
        server_name = "the Server"
        role_name = "Verified"
        if global_bot and guild_id:
            try:
                guild_id_int = int(guild_id)
                user_id_int = int(user_id)
                
                async def grant_role():
                    guild = global_bot.get_guild(guild_id_int)
                    if guild:
                        nonlocal server_name, role_name
                        server_name = guild.name
                        member = guild.get_member(user_id_int)
                        if not member:
                            try:
                                member = await guild.fetch_member(user_id_int)
                            except:
                                pass
                        config = get_guild_config(guild_id_int)
                        role_id = config.get("verify_role_id")
                        if role_id and member:
                            role = guild.get_role(int(role_id))
                            if role:
                                role_name = role.name
                                if role not in member.roles:
                                    try:
                                        await member.add_roles(role, reason="Passed Discord OAuth2 Account Verification")
                                    except Exception as role_err:
                                        print(f"Error giving verified role: {role_err}")

                asyncio.run_coroutine_threadsafe(grant_role(), global_bot.loop)
            except Exception as e:
                print(f"Role assign error: {e}")

        return render_template("verify_success.html", username=username, user_id=user_id, user_avatar=user_avatar, server_name=server_name, role_name=role_name)

    except Exception as ex:
        print(f"Verification Callback Exception: {ex}")
        return f"<h3>❌ Error during verification: {ex}</h3>", 500

@app.route("/status/<int:guild_id>/<int:user_id>")
def verification_status(guild_id, user_id):
    server_name = "Server"
    role_name = "Verified"
    username = f"User {user_id}"
    user_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"
    
    if global_bot:
        guild = global_bot.get_guild(guild_id)
        if guild:
            server_name = guild.name
            member = guild.get_member(user_id)
            if member:
                username = member.name
                if member.display_avatar:
                    user_avatar = member.display_avatar.url
            config = get_guild_config(guild_id)
            role_id = config.get("verify_role_id")
            if role_id:
                role = guild.get_role(int(role_id))
                if role:
                    role_name = role.name
                    
    return render_template("verify_success.html", username=username, user_id=user_id, user_avatar=user_avatar, server_name=server_name, role_name=role_name)

@app.route("/pull_members", methods=["POST"])
@requires_authorization
def pull_members():
    guild_id = request.form.get("guild_id")
    if not guild_id:
        return redirect(url_for("dashboard"))

    bot_token = os.getenv("DISCORD_TOKEN", "")
    members = get_all_oauth_members()

    success_count = 0
    already_in_count = 0
    failed_count = 0

    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json"
    }

    for m in members:
        user_id = m.get("user_id")
        access_token = m.get("access_token")
        if not user_id or not access_token:
            continue
        
        url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}"
        body = {"access_token": access_token}

        try:
            resp = requests.put(url, json=body, headers=headers)
            if resp.status_code == 201:
                success_count += 1
            elif resp.status_code == 204:
                already_in_count += 1
            else:
                failed_count += 1
        except:
            failed_count += 1

    return redirect(url_for("manage", guild_id=guild_id))

@app.errorhandler(Unauthorized)
def redirect_unauthorized(e):
    return redirect(url_for("login"))

def run_server():
    port = int(os.getenv("PORT", 5000))
    print(f"🌐 [Welcome & DM Dashboard] Starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, use_reloader=False)

def run_web(bot_instance=None):
    global global_bot
    global_bot = bot_instance
    t = Thread(target=run_server, daemon=True)
    t.start()
