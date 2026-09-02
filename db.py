from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client["welcome_dm_bot_db"]
    guilds_collection = db["guilds"]
    verified_collection = db["verified_members"]
else:
    print("WARNING: MONGO_URI not found in .env. Falling back to in-memory storage (NOT persistent!).")
    client = None

    class DummyDB:
        def __init__(self):
            self.guilds = {}
            self.verified = {}

    dummy_db = DummyDB()

def get_default_config(guild_id: int):
    return {
        "_id": str(guild_id),
        "welcome_enabled": False,
        "welcome_as_embed": True,
        "welcome_channel_id": None,
        "welcome_title": "Welcome to {server_name} 🚀",
        "welcome_description": "Hey {user_mention}, welcome to the core of **{server_name}**!\n\n📌 **Getting Started:**\n• Read the rules in the info channel\n• Grab your self-roles\n• Say hi in general chat!",
        "welcome_image": "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif",
        
        "public_chat_welcome_enabled": False,
        "public_chat_welcome_channel_id": None,
        "public_chat_welcome_message": "Hey {user_mention}, welcome to the chat! Make sure to read the rules and have fun! 🚀",
        
        "dm_welcome_enabled": False,
        "dm_welcome_message": "Welcome to {server_name}! We are thrilled to have you here.\n\nCheck out our channels and enjoy your stay! 🎉",
        "dm_welcome_ticket_link": "",
        "dm_welcome_image": "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif",
        
        "autorole_enabled": False,
        "autorole_role_id": None,
        
        "leave_enabled": False,
        "leave_channel_id": None,
        "leave_message": "**{username}** has left the server. 😢",

        # Verification System
        "verify_enabled": False,
        "verify_channel_id": None,
        "verify_role_id": None,
        "verify_title": "🛡️ Member Verification System",
        "verify_description": "Welcome to **{server_name}**!\n\nTo access all channels and community discussions, click the **Verify Now** button below.\n\n📌 **Quick Server Rules:**\n• Respect all members and staff\n• No unsolicited spam, DM adverts, or toxicity\n• Follow Discord Community Guidelines",
        "verify_image": "https://media.giphy.com/media/7RwanQsnkwtQoM1lMo/giphy.gif"
    }

def get_guild_config(guild_id: int):
    guild_key = str(guild_id)
    if client:
        data = guilds_collection.find_one({"_id": guild_key})
        if not data:
            data = get_default_config(guild_id)
            guilds_collection.insert_one(data)
        return data
    else:
        if guild_key not in dummy_db.guilds:
            dummy_db.guilds[guild_key] = get_default_config(guild_id)
        return dummy_db.guilds[guild_key]

def save_guild_config(guild_id: int, data: dict):
    guild_key = str(guild_id)
    if client:
        data["_id"] = guild_key
        guilds_collection.replace_one({"_id": guild_key}, data, upsert=True)
    else:
        dummy_db.guilds[guild_key] = data

import datetime

def record_verified_member(guild_id: int, user_id: int, username: str):
    doc = {
        "_id": f"{guild_id}_{user_id}",
        "guild_id": str(guild_id),
        "user_id": str(user_id),
        "username": username,
        "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    if client:
        verified_collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    else:
        dummy_db.verified[doc["_id"]] = doc

def save_oauth_member(user_id: str, username: str, access_token: str, refresh_token: str, expires_in: int, guild_id: str = None, ip_address: str = None):
    doc = {
        "_id": str(user_id),
        "user_id": str(user_id),
        "username": username,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expires_in)).isoformat(),
        "guild_id": str(guild_id) if guild_id else None,
        "ip_address": ip_address,
        "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    if client:
        verified_collection.replace_one({"_id": str(user_id)}, doc, upsert=True)
    else:
        dummy_db.verified[str(user_id)] = doc

def get_all_oauth_members(guild_id: str = None):
    if client:
        query = {"guild_id": str(guild_id)} if guild_id else {}
        return list(verified_collection.find(query))
    else:
        if guild_id:
            return [v for v in dummy_db.verified.values() if v.get("guild_id") == str(guild_id)]
        return list(dummy_db.verified.values())

def is_user_verified(guild_id: int, user_id: int) -> bool:
    doc_id = str(user_id)
    if client:
        return verified_collection.find_one({"_id": doc_id}) is not None
    else:
        return doc_id in dummy_db.verified

def get_verified_count(guild_id: int = None) -> int:
    if client:
        query = {"guild_id": str(guild_id)} if guild_id else {}
        return verified_collection.count_documents(query)
    else:
        if guild_id:
            return sum(1 for v in dummy_db.verified.values() if v.get("guild_id") == str(guild_id))
        return len(dummy_db.verified)

def delete_oauth_member(user_id: str):
    if client:
        verified_collection.delete_one({"_id": str(user_id)})
    else:
        dummy_db.verified.pop(str(user_id), None)
