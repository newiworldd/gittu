from flask import Flask, render_template, redirect, url_for, request, session, flash
from flask_discord import DiscordOAuth2Session, requires_authorization, Unauthorized
import os
from threading import Thread
from dotenv import load_dotenv
from db import get_guild_config, save_guild_config, check_admin, get_all_keys, add_free_keys, get_claimed_users
import discord
import asyncio

load_dotenv()
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "anik-x-cheats-super-secret-key")

# Discord OAuth2 Config
app.config["DISCORD_CLIENT_ID"] = os.getenv("DISCORD_CLIENT_ID", "")
app.config["DISCORD_CLIENT_SECRET"] = os.getenv("DISCORD_CLIENT_SECRET", "")
app.config["DISCORD_REDIRECT_URI"] = os.getenv("DISCORD_REDIRECT_URI", "http://127.0.0.1:5000/callback")
app.config["DISCORD_BOT_TOKEN"] = os.getenv("DISCORD_TOKEN", "")

discord_oauth = DiscordOAuth2Session(app)

# Callback for sending panel from dashboard to bot
panel_callback = None

def set_panel_callback(cb):
    global panel_callback
    panel_callback = cb



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
        pass
    return redirect(url_for("dashboard"))

# Global bot instance
global_bot = None

@app.route("/dashboard")
@requires_authorization
def dashboard():
    import traceback
    try:
        user = discord_oauth.fetch_user()
        guilds = discord_oauth.fetch_guilds()
        
        admin_guilds = []
        for g in guilds:
            # Check if user has Administrator (0x8) or Manage Server (0x20)
            if getattr(g.permissions, "administrator", False) or getattr(g.permissions, "manage_guild", False):
                config = get_guild_config(g.id)
                channels = []
                bot_in_server = False
                if global_bot:
                    discord_guild = global_bot.get_guild(g.id)
                    if discord_guild:
                        bot_in_server = True
                        channels = [{"id": str(c.id), "name": c.name} for c in discord_guild.text_channels]
                
                # Pass config directly as dictionary to avoid __slots__ error
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
        return f"<pre>{traceback.format_exc()}</pre>"

from db import get_guild_config, save_guild_config

def check_auth():
    if session.get("admin_logged_in"): return True
    if discord_oauth.authorized: return True
    return False

@app.route("/send_panel", methods=["POST"])
def send_panel():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    channel_id = request.form.get("channel_id")
    
    if panel_callback and guild_id and channel_id:
        try:
            panel_callback(int(guild_id), int(channel_id))
        except ValueError:
            pass
            
    return redirect(url_for("dashboard"))

@app.route("/set_ticket_config", methods=["POST"])
def set_ticket_config():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    ticket_banner = request.form.get("ticket_banner")
    ticket_logo = request.form.get("ticket_logo")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            if ticket_banner is not None:
                config["ticket_banner"] = ticket_banner
            if ticket_logo is not None:
                config["ticket_logo"] = ticket_logo
                
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/set_key_claim_config", methods=["POST"])
def set_key_claim_config():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    key_channel_id = request.form.get("key_channel_id")
    claimkey_enabled = request.form.get("claimkey_enabled") == "1"
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["key_channel_id"] = key_channel_id or None
            config["claimkey_enabled"] = claimkey_enabled
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/set_welcome", methods=["POST"])
def set_welcome():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    welcome_enabled = request.form.get("welcome_enabled") == "on"
    channel_id = request.form.get("channel_id")
    welcome_title = request.form.get("welcome_title")
    welcome_description = request.form.get("welcome_description")
    welcome_image = request.form.get("welcome_image")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["welcome_enabled"] = welcome_enabled
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
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/set_public_chat_welcome", methods=["POST"])
def set_public_chat_welcome():
    if not check_auth(): return redirect(url_for("login"))
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
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/set_leave_config", methods=["POST"])
def set_leave_config():
    if not check_auth(): return redirect(url_for("login"))
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
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/set_autorole", methods=["POST"])
def set_autorole():
    if not session.get("admin_logged_in"):
        return "Unauthorized", 403
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
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/set_dm_welcome", methods=["POST"])
def set_dm_welcome():
    if not check_auth(): return redirect(url_for("login"))
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
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/set_premium_config", methods=["POST"])
def set_premium_config():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    crypto_address = request.form.get("crypto_address")
    binance_id = request.form.get("binance_id")
    bkash_number = request.form.get("bkash_number")
    auto_responder_enabled = request.form.get("auto_responder_enabled") == "on"
    ai_support_enabled = request.form.get("ai_support_enabled") == "on"
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["crypto_address"] = crypto_address if crypto_address is not None else ""
            config["binance_id"] = binance_id if binance_id is not None else ""
            config["bkash_number"] = bkash_number if bkash_number is not None else ""
            config["auto_responder_enabled"] = auto_responder_enabled
            config["ai_support_enabled"] = ai_support_enabled
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/set_automod_config", methods=["POST"])
def set_automod_config():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    automod_enabled = request.form.get("automod_enabled") == "on"
    automod_block_links = request.form.get("automod_block_links") == "on"
    automod_block_badwords = request.form.get("automod_block_badwords") == "on"
    automod_badwords = request.form.get("automod_badwords")
    automod_ai_enabled = request.form.get("automod_ai_enabled") == "on"
    automod_action = request.form.get("automod_action")
    anti_alt_enabled = request.form.get("anti_alt_enabled") == "on"
    anti_alt_days = request.form.get("anti_alt_days")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["automod_enabled"] = automod_enabled
            config["automod_block_links"] = automod_block_links
            config["automod_block_badwords"] = automod_block_badwords
            config["automod_badwords"] = automod_badwords if automod_badwords is not None else ""
            config["automod_ai_enabled"] = automod_ai_enabled
            config["automod_action"] = automod_action if automod_action else "delete_and_warn"
            config["anti_alt_enabled"] = anti_alt_enabled
            try:
                config["anti_alt_days"] = int(anti_alt_days) if anti_alt_days else 7
            except ValueError:
                config["anti_alt_days"] = 7
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/set_logs_config", methods=["POST"])
def set_logs_config():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    log_channel_id = request.form.get("log_channel_id")
    transcripts_channel_id = request.form.get("transcripts_channel_id")
    
    if guild_id:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            config["log_channel_id"] = log_channel_id if log_channel_id else None
            config["transcripts_channel_id"] = transcripts_channel_id if transcripts_channel_id else None
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/add_custom_response", methods=["POST"])
def add_custom_response():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    keywords = request.form.get("keywords")
    reply = request.form.get("reply")
    
    if guild_id and keywords and reply:
        try:
            guild_id_int = int(guild_id)
            config = get_guild_config(guild_id_int)
            if "custom_responses" not in config:
                config["custom_responses"] = []
            
            # keywords like "ltc, btc, pay" will be split into a list by bot.py
            config["custom_responses"].append({"keywords": keywords, "reply": reply})
            save_guild_config(guild_id_int, config)
        except ValueError:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id_int))

@app.route("/delete_custom_response/<int:guild_id>/<int:index>", methods=["POST"])
def delete_custom_response(guild_id, index):
    if not check_auth(): return redirect(url_for("login"))
    config = get_guild_config(guild_id)
    if "custom_responses" in config and 0 <= index < len(config["custom_responses"]):
        config["custom_responses"].pop(index)
        save_guild_config(guild_id, config)
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/manage/<int:guild_id>")
@requires_authorization
def manage(guild_id):
    user = discord_oauth.fetch_user()
    guilds = discord_oauth.fetch_guilds()
    
    # Check if user has permission in this guild
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
        "bot_in_server": bot_in_server
    }
    
    claimed_users = get_claimed_users()
    # Filter claimed users for this specific guild
    guild_claims = [c for c in claimed_users if str(c.get("guild_id")) == str(guild_id)]

    return render_template("manage.html", user=user, guild=guild_data, claimed_keys=guild_claims, total_claims=len(guild_claims))

@app.route("/create_role", methods=["POST"])
def create_role():
    if not session.get("admin_logged_in"):
        return "Unauthorized", 403
    guild_id = request.form.get("guild_id")
    role_name = request.form.get("role_name")
    role_color = request.form.get("role_color")
    
    if global_bot and guild_id and role_name:
        try:
            guild_id_int = int(guild_id)
            guild = global_bot.get_guild(guild_id_int)
            if guild:
                color = discord.Color.default()
                if role_color and role_color.startswith('#'):
                    color = discord.Color(int(role_color.lstrip('#'), 16))
                
                async def create():
                    try:
                        await guild.create_role(name=role_name, color=color)
                    except Exception:
                        pass
                
                asyncio.run_coroutine_threadsafe(create(), global_bot.loop)
        except Exception:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/assign_role", methods=["POST"])
def assign_role():
    if not session.get("admin_logged_in"):
        return "Unauthorized", 403
    guild_id = request.form.get("guild_id")
    user_id = request.form.get("user_id")
    role_id = request.form.get("role_id")
    
    if global_bot and guild_id and user_id and role_id:
        try:
            guild_id_int = int(guild_id)
            user_id_int = int(user_id)
            role_id_int = int(role_id)
            
            guild = global_bot.get_guild(guild_id_int)
            if guild:
                role = guild.get_role(role_id_int)
                if role:
                    async def assign():
                        try:
                            member = guild.get_member(user_id_int)
                            if not member:
                                member = await guild.fetch_member(user_id_int)
                            if member:
                                await member.add_roles(role)
                        except Exception:
                            pass
                    
                    asyncio.run_coroutine_threadsafe(assign(), global_bot.loop)
        except Exception:
            pass
            
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/logout")
def logout():
    discord_oauth.revoke()
    return redirect(url_for("index"))

@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        from db import check_admin, get_admin
        if check_admin(username, password):
            admin_doc = get_admin(username)
            if admin_doc and admin_doc.get("twofa_secret"):
                # Check if 2FA bypass cookie is present and matches the username
                if request.cookies.get("twofa_verified") == username:
                    session["admin_logged_in"] = True
                    session["admin_username"] = username
                    return redirect(url_for("admin_dashboard"))
                session["temp_admin_user"] = username
                return redirect(url_for("admin_twofa"))
                
            session["admin_logged_in"] = True
            session["admin_username"] = username
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid credentials."
    return render_template("admin_login.html", error=error)

@app.route("/admin_twofa", methods=["GET", "POST"])
def admin_twofa():
    username = session.get("temp_admin_user")
    if not username:
        return redirect(url_for("admin_login"))
        
    error = None
    if request.method == "POST":
        code = request.form.get("code")
        from db import get_admin
        admin_doc = get_admin(username)
        if admin_doc and admin_doc.get("twofa_secret"):
            import pyotp
            totp = pyotp.TOTP(admin_doc["twofa_secret"])
            if totp.verify(code):
                session.pop("temp_admin_user", None)
                session["admin_logged_in"] = True
                session["admin_username"] = username
                # Set 2FA bypass cookie valid for 3 days (3 * 24 * 60 * 60 seconds)
                resp = redirect(url_for("admin_dashboard"))
                resp.set_cookie("twofa_verified", username, max_age=3*24*60*60, httponly=True)
                return resp
            else:
                error = "Invalid 2FA code."
        else:
            error = "2FA not configured for this user."
    return render_template("admin_twofa_login.html", error=error)

@app.route("/admin/2fa/setup")
def admin_2fa_setup():
    if not session.get("admin_logged_in"):
        return {"error": "Unauthorized"}, 401
    import pyotp
    import urllib.parse
    secret = pyotp.random_base32()
    username = session.get("admin_username", "xdanik700")
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=username, issuer_name="AnikXCheats")
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={urllib.parse.quote(provisioning_uri)}"
    return {"secret": secret, "qr_url": qr_url}

@app.route("/admin/2fa/verify", methods=["POST"])
def admin_2fa_verify():
    if not session.get("admin_logged_in"):
        return {"success": False, "message": "Unauthorized"}, 401
    code = request.form.get("code")
    secret = request.form.get("secret")
    if not code or not secret:
        return {"success": False, "message": "Code and secret are required"}, 400
        
    import pyotp
    totp = pyotp.TOTP(secret)
    if totp.verify(code):
        from db import get_admin, save_admin
        username = session.get("admin_username", "xdanik700")
        admin_doc = get_admin(username)
        if admin_doc:
            admin_doc["twofa_secret"] = secret
            save_admin(username, admin_doc)
            from flask import jsonify
            resp = jsonify({"success": True})
            resp.set_cookie("twofa_verified", username, max_age=3*24*60*60, httponly=True)
            return resp
        return {"success": False, "message": "Admin user not found in database"}, 404
    return {"success": False, "message": "Invalid code. Check your authenticator app and try again."}, 400

@app.route("/admin/2fa/disable", methods=["POST"])
def admin_2fa_disable():
    if not session.get("admin_logged_in"):
        return {"success": False, "message": "Unauthorized"}, 401
    code = request.form.get("code")
    if not code:
        return {"success": False, "message": "Code is required"}, 400
        
    from db import get_admin, save_admin
    username = session.get("admin_username", "xdanik700")
    admin_doc = get_admin(username)
    if admin_doc and admin_doc.get("twofa_secret"):
        import pyotp
        totp = pyotp.TOTP(admin_doc["twofa_secret"])
        if totp.verify(code):
            admin_doc["twofa_secret"] = None
            save_admin(username, admin_doc)
            return {"success": True}
        return {"success": False, "message": "Invalid code."}, 400
    return {"success": False, "message": "2FA is not enabled."}, 400

@app.route("/admin_dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
        
    from db import get_admin
    username = session.get("admin_username", "xdanik700")
    admin_doc = get_admin(username)
    twofa_enabled = admin_doc.get("twofa_secret") is not None if admin_doc else False
        
    guilds_data = []
    total_members = 0
    if global_bot:
        for g in global_bot.guilds:
            guilds_data.append({
                "id": str(g.id),
                "name": g.name,
                "icon_url": g.icon.url if g.icon else None,
                "member_count": g.member_count
            })
            total_members += g.member_count
            
    return render_template(
        "admin_dashboard.html", 
        guilds=guilds_data, 
        total_members=total_members, 
        twofa_enabled=twofa_enabled
    )

@app.route("/admin/manage/<int:guild_id>")
def admin_manage(guild_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
        
    config = get_guild_config(guild_id)
    channels = []
    roles = []
    bot_in_server = False
    target_guild = None
    
    if global_bot:
        discord_guild = global_bot.get_guild(guild_id)
        if discord_guild:
            target_guild = discord_guild
            bot_in_server = True
            channels = [{"id": str(c.id), "name": c.name} for c in discord_guild.text_channels]
            roles = [{"id": str(r.id), "name": r.name} for r in discord_guild.roles if r.name != "@everyone"]
            
    if not target_guild:
        return "Bot is not in this guild.", 404
        
    guild_data = {
        "id": str(target_guild.id),
        "name": target_guild.name,
        "icon_url": target_guild.icon.url if target_guild.icon else "https://cdn.discordapp.com/embed/avatars/0.png",
        "config": config,
        "channels": channels,
        "roles": roles,
        "bot_in_server": bot_in_server
    }
    claimed_users = get_claimed_users()
    guild_claims = [c for c in claimed_users if str(c.get("guild_id")) == str(guild_id)]

    return render_template("manage.html", user={"username": "Super Admin", "avatar_url": ""}, guild=guild_data, is_super_admin=True, claimed_keys=guild_claims, total_claims=len(guild_claims))

@app.route("/web_send_embed", methods=["POST"])
def web_send_embed():
    if not check_auth(): return redirect(url_for("login"))
    guild_id = request.form.get("guild_id")
    channel_id = request.form.get("channel_id")
    template = request.form.get("template")
    title = request.form.get("title")
    description = request.form.get("description")
    color = request.form.get("color")
    image_url = request.form.get("image_url")
    thumbnail_url = request.form.get("thumbnail_url")

    # Write to a public debug log file so user can read it in browser
    import datetime
    def write_debug(msg):
        try:
            log_dir = os.path.dirname(os.path.abspath(__file__))
            log_file_path = os.path.join(log_dir, "static", "debug.log")
            os.makedirs(os.path.join(log_dir, "static"), exist_ok=True)
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception as log_ex:
            print(f"Failed to write to debug.log: {log_ex}")

    write_debug(f"Received request to send embed: guild={guild_id}, channel={channel_id}, template={template}")

    if not global_bot:
        write_debug("Error: global_bot is None!")

    if global_bot and guild_id and channel_id:
        try:
            guild_id_int = int(guild_id)
            channel_id_int = int(channel_id)
            
            async def send():
                try:
                    write_debug(f"Starting async send task for channel {channel_id_int}...")
                    channel = global_bot.get_channel(channel_id_int)
                    if not channel:
                        write_debug("Channel not cached, fetching channel from Discord API...")
                        try:
                            channel = await global_bot.fetch_channel(channel_id_int)
                            write_debug(f"Channel fetched successfully: {channel.name if channel else 'None'}")
                        except Exception as fetch_ex:
                            write_debug(f"Error fetching channel: {fetch_ex}")
                    else:
                        write_debug(f"Channel found in cache: {channel.name}")
                        
                    if channel:
                        guild_config = get_guild_config(guild_id_int)
                        fallback_banner = "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif"
                        fallback_logo = "https://media.discordapp.net/attachments/1448757915035897886/1532872634058936500/axc.gif?ex=6a6e6e63&is=6a6d1ce3&hm=6cce736ff46f16b4ece45fc226890625eb79e4debced09a22f200bda093ffa49&=&width=350&height=350"
                        
                        embed = None
                        
                        if template == "basic-panel":
                            embed = discord.Embed(
                                title="BASIC PANEL ALL SERVER SAFE!!! <a:emoji_46:1528280811038834799>",
                                description=(
                                    "⚡ **BASIC PANEL ALL SERVER SAFE** <a:emoji_46:1528280811038834799>\n\n"
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
                        elif template == "premium-panel":
                            embed = discord.Embed(
                                title="AXC PREMIUM PANEL V3 <a:fire2:1528328548295643178>",
                                description=(
                                    "🔥 **AXC PREMIUM PANEL V3** <a:fire2:1528328548295643178>\n\n"
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
                            embed_color = discord.Color.red()
                            if color:
                                try:
                                    embed_color = discord.Color(int(color.lstrip('#'), 16))
                                except ValueError:
                                    pass
                            embed = discord.Embed(
                                title=title or "Custom Embed",
                                description=(description or "").replace("\\n", "\n").replace("\r\n", "\n"),
                                color=embed_color
                            )
                        
                        final_thumbnail = thumbnail_url.strip() if thumbnail_url else (guild_config.get("ticket_logo") or fallback_logo)
                        final_banner = image_url.strip() if image_url else (guild_config.get("ticket_banner") or fallback_banner)
                        
                        if final_thumbnail and "e62e3cc75f1747e0824ed1ee0dda51a9.webp" in final_thumbnail:
                            final_thumbnail = fallback_logo
                            
                        if final_thumbnail and final_thumbnail.strip().startswith("http"):
                            try:
                                embed.set_thumbnail(url=final_thumbnail.strip())
                            except:
                                pass
                        
                        if final_banner and final_banner.strip().startswith("http"):
                            try:
                                embed.set_image(url=final_banner.strip())
                            except:
                                pass

                        if final_thumbnail and final_thumbnail.strip().startswith("http"):
                            embed.set_footer(text="Anik X Cheats • Ticket System", icon_url=final_thumbnail.strip())
                        else:
                            embed.set_footer(text="Anik X Cheats • Ticket System")
                            
                        embed.timestamp = discord.utils.utcnow()
                        
                        write_debug("Attempting to send embed to channel...")
                        await channel.send(embed=embed)
                        write_debug("[Web Send Success] Sent embed successfully!")
                        print(f"[Web Send Success] Sent embed to channel {channel_id_int}")
                    else:
                        write_debug(f"[Web Send Error] Channel {channel_id_int} not found / inaccessible.")
                        print(f"[Web Send Error] Channel {channel_id_int} not found.")
                except Exception as send_err:
                    import traceback
                    write_debug(f"[Web Send Error] Exception in async send: {send_err}\nTraceback: {traceback.format_exc()}")
                    print(f"[Web Send Error] Exception in async send: {send_err}")
            
            asyncio.run_coroutine_threadsafe(send(), global_bot.loop)
        except Exception as e:
            import traceback
            write_debug(f"Error launching async send thread: {e}\nTraceback: {traceback.format_exc()}")
            print(f"Error sending embed from web: {e}")

    # Use is_super_admin param to redirect properly if requested
    is_super_admin = request.form.get("is_super_admin")
    if is_super_admin:
        return redirect(url_for("admin_manage", guild_id=guild_id))
    return redirect(url_for("manage", guild_id=guild_id))

@app.route("/admin_logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))

@app.route("/transcript/<transcript_id>")
def view_transcript(transcript_id):
    from db import get_transcript
    data = get_transcript(transcript_id)
    if not data:
        return "Transcript not found", 404
    return render_template("transcript.html", data=data)

@app.errorhandler(Unauthorized)
def redirect_unauthorized(e):
    return redirect(url_for("login"))

def run_server():
    # Only bind to 0.0.0.0 to make it publicly accessible on Render
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), use_reloader=False)

def run_web(bot_instance=None):
    global global_bot
    global_bot = bot_instance
    t = Thread(target=run_server)
    t.start()
