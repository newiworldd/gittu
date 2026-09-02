# 🚀 Anik X Suite - Welcome & DM Automation Bot

A production-ready, ultra-clean Discord Bot and Web Dashboard dedicated to member onboarding, rich welcome embeds, direct message (DM) greetings, auto-roles, and leave logs.

---

## 🌟 Key Features
- **🎉 Server Welcome Embeds:** Customizable title, description, banner image, thumbnail, and dynamic placeholders (`{server_name}`, `{user_mention}`, `{member_count}`).
- **💬 Public Chat Welcome:** Mentions newcomers in general chat and automatically purges the ping after 5 seconds.
- **📩 DM Welcome System:** Sends personalized direct messages to new members with server info, price lists, and interactive buttons.
- **🎭 Auto-Role:** Instantly assigns selected roles to new members on arrival.
- **🚪 Member Leave Logs:** Tracks departures in dedicated log channels.
- **🌐 Web Dashboard (Flask + OAuth2):** Full visual configuration panel with live embed preview.

---

## 🛠️ Setup & Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env` and fill in your credentials:
```env
DISCORD_TOKEN=your_bot_token
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_REDIRECT_URI=http://127.0.0.1:5000/callback
MONGO_URI=mongodb+srv://...
FLASK_SECRET_KEY=your_secret_key
PORT=5000
```

### 3. Run the Bot & Dashboard
```bash
python bot.py
```
Visit `http://localhost:5000` in your web browser.
