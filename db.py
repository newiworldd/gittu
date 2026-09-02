from pymongo import MongoClient
import os
import datetime
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client["ticket_security_bot_db"]
    guilds_collection = db["guilds"]
    tickets_collection = db["tickets"]
    admins_collection = db["admins"]
    licenses_collection = db["licenses"]
    transcripts_collection = db["transcripts"]
    key_dist_collection = db["key_distribution"]
    claimed_users_collection = db["claimed_users"]
    
    # Auto-seed default admin credentials if not present
    if not admins_collection.find_one({"username": "xdanik700"}):
        admins_collection.insert_one({"username": "xdanik700", "password": "xdanik700"})
else:
    print("WARNING: MONGO_URI not found in .env. Falling back to in-memory storage (NOT persistent!).")
    client = None

    class DummyDB:
        def __init__(self):
            self.guilds = {}
            self.tickets = {}
            self.transcripts = {}
            self.admins = {"xdanik700": {"username": "xdanik700", "password": "xdanik700"}}
            self.licenses = {}
            self.claimed_users = {}
            self.free_keys = {f"lib{i}": {"claimed": False, "claimed_by": None} for i in range(1, 59)}

    dummy_db = DummyDB()

# --- Guild Config ---
def get_default_guild_config(guild_id: int):
    return {
        "_id": str(guild_id),
        "staff_role_id": None,
        "ticket_category_id": None,
        "ticket_banner": "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif",
        "ticket_logo": "https://media.discordapp.net/attachments/1449011993083379806/1463872206252806175/e62e3cc75f1747e0824ed1ee0dda51a9.webp",
        "ticket_count": 0,
        "crypto_address": "",
        "binance_id": "",
        "bkash_number": "",
        "log_channel_id": None,
        "transcripts_channel_id": None,
        "auto_responder_enabled": True,
        "ai_support_enabled": False,
        "custom_responses": [],
        
        # Security & AutoMod
        "automod_enabled": False,
        "automod_block_links": False,
        "automod_block_badwords": False,
        "automod_badwords": "fuck,scam,choda,khanki",
        "automod_ai_enabled": False,
        "automod_action": "delete_and_warn",
        "anti_alt_enabled": False,
        "anti_alt_days": 7,
        "anti_nuke_enabled": True,
        
        # Trial Key & Auth
        "authorized": False,
        "key_channel_id": None,
        "claimkey_enabled": False
    }

def get_guild_config(guild_id: int):
    guild_key = str(guild_id)
    if client:
        data = guilds_collection.find_one({"_id": guild_key})
        if not data:
            data = get_default_guild_config(guild_id)
            guilds_collection.insert_one(data)
        return data
    else:
        if guild_key not in dummy_db.guilds:
            dummy_db.guilds[guild_key] = get_default_guild_config(guild_id)
        return dummy_db.guilds[guild_key]

def save_guild_config(guild_id: int, data: dict):
    guild_key = str(guild_id)
    if client:
        data["_id"] = guild_key
        guilds_collection.replace_one({"_id": guild_key}, data, upsert=True)
    else:
        dummy_db.guilds[guild_key] = data

# --- Tickets ---
def get_ticket(channel_id: str):
    if client:
        return tickets_collection.find_one({"_id": str(channel_id)})
    else:
        return dummy_db.tickets.get(str(channel_id))

def save_ticket(channel_id: str, data: dict):
    channel_key = str(channel_id)
    if client:
        data["_id"] = channel_key
        tickets_collection.replace_one({"_id": channel_key}, data, upsert=True)
    else:
        dummy_db.tickets[channel_key] = data

def delete_ticket(channel_id: str):
    channel_key = str(channel_id)
    if client:
        tickets_collection.delete_one({"_id": channel_key})
    else:
        if channel_key in dummy_db.tickets:
            del dummy_db.tickets[channel_key]

def get_all_tickets_for_guild(guild_id: int):
    if client:
        return list(tickets_collection.find({"guild_id": str(guild_id)}))
    else:
        return [t for t in dummy_db.tickets.values() if str(t.get("guild_id")) == str(guild_id)]

# --- Transcripts ---
def save_transcript(transcript_id: str, data: dict):
    if client:
        data["_id"] = str(transcript_id)
        transcripts_collection.replace_one({"_id": str(transcript_id)}, data, upsert=True)
    else:
        dummy_db.transcripts[str(transcript_id)] = data

def get_transcript(transcript_id: str):
    if client:
        return transcripts_collection.find_one({"_id": str(transcript_id)})
    return dummy_db.transcripts.get(str(transcript_id))

# --- Super Admin & 2FA ---
def get_admin(username: str):
    if client:
        return admins_collection.find_one({"username": username})
    else:
        return dummy_db.admins.get(username)

def save_admin(username: str, data: dict):
    if client:
        admins_collection.replace_one({"username": username}, data, upsert=True)
    else:
        dummy_db.admins[username] = data

def check_admin(username: str, password: str):
    admin = get_admin(username)
    return admin is not None and admin.get("password") == password

# --- Licenses ---
def generate_license(key: str, days: int, generated_by: int):
    if client:
        licenses_collection.insert_one({"_id": key, "days": days, "generated_by": generated_by, "redeemed": False})
    else:
        dummy_db.licenses[key] = {"_id": key, "days": days, "generated_by": generated_by, "redeemed": False}

def get_license(key: str):
    if client:
        return licenses_collection.find_one({"_id": key})
    return dummy_db.licenses.get(key)

# --- Free Trial Key System ---
def seed_free_keys():
    if not client:
        if not hasattr(dummy_db, "free_keys"):
            dummy_db.free_keys = {f"lib{i}": {"claimed": False, "claimed_by": None} for i in range(1, 59)}
        return
        
    if key_dist_collection.count_documents({}) == 0:
        keys_to_insert = []
        for i in range(1, 59):
            keys_to_insert.append({
                "_id": f"lib{i}",
                "claimed": False,
                "claimed_by": None,
                "claimed_at": None
            })
        key_dist_collection.insert_many(keys_to_insert)

def has_user_claimed(user_id: int) -> bool:
    if client:
        return claimed_users_collection.find_one({"user_id": str(user_id)}) is not None
    else:
        return str(user_id) in dummy_db.claimed_users

def mark_user_claimed(user_id: int, key: str, guild_id: int, revealed: bool = True):
    now_iso = datetime.datetime.utcnow().isoformat()
    if client:
        claimed_users_collection.insert_one({
            "user_id": str(user_id),
            "key": key,
            "guild_id": str(guild_id),
            "revealed": revealed,
            "claimed_at": now_iso
        })
    else:
        dummy_db.claimed_users[str(user_id)] = {
            "key": key,
            "guild_id": str(guild_id),
            "revealed": revealed,
            "claimed_at": now_iso
        }

def get_user_claim(user_id: int):
    if client:
        return claimed_users_collection.find_one({"user_id": str(user_id)})
    else:
        return dummy_db.claimed_users.get(str(user_id))

def reveal_user_key(user_id: int):
    if client:
        claimed_users_collection.update_one({"user_id": str(user_id)}, {"$set": {"revealed": True}})
    else:
        if str(user_id) in dummy_db.claimed_users:
            dummy_db.claimed_users[str(user_id)]["revealed"] = True

def reset_user_claim(user_id: int) -> bool:
    if client:
        result = claimed_users_collection.delete_one({"user_id": str(user_id)})
        return result.deleted_count > 0
    else:
        if str(user_id) in dummy_db.claimed_users:
            del dummy_db.claimed_users[str(user_id)]
            return True
        return False

def reset_all_claims() -> bool:
    if client:
        claimed_users_collection.delete_many({})
        return True
    else:
        dummy_db.claimed_users.clear()
        return True

def get_claimed_users():
    if client:
        return list(claimed_users_collection.find({}))
    else:
        return [{"user_id": k, "key": v["key"], "guild_id": v["guild_id"], "revealed": v["revealed"]} for k, v in dummy_db.claimed_users.items()]

def get_all_keys():
    if client:
        seed_free_keys()
        return list(key_dist_collection.find({}))
    else:
        seed_free_keys()
        return [{"_id": k, "claimed": v["claimed"], "claimed_by": v["claimed_by"]} for k, v in dummy_db.free_keys.items()]

def add_free_keys(keys_list: list):
    if client:
        seed_free_keys()
        for key in keys_list:
            key = key.strip()
            if not key:
                continue
            key_dist_collection.update_one(
                {"_id": key},
                {"$setOnInsert": {"claimed": False, "claimed_by": None, "claimed_at": None}},
                upsert=True
            )
    else:
        seed_free_keys()
        for key in keys_list:
            key = key.strip()
            if not key:
                continue
            if key not in dummy_db.free_keys:
                dummy_db.free_keys[key] = {"claimed": False, "claimed_by": None}
