# 🚀 Anik X Cheats - Premium Ticket, Security & License Bot

A production-ready, ultra-fast Discord Bot and SaaS Web Dashboard featuring Advanced Ticket Panels, AI AutoMod (Gemini & Groq), Anti-Alt, Anti-Nuke, License / Trial Key Management, and Super Admin 2FA.

---

## 🌟 Key Features
- **🎫 Advanced Ticket System:** Dropdown category selection (Support, Buy Panel, UID Bypass), claim/close controls, and HTML transcript generator.
- **🤖 AI AutoMod & Multimodal Scan:** Real-time AI text and image scanning to block toxicity, crypto scams, invite links, and bad words with automatic warnings.
- **🛡️ Anti-Alt & Anti-Nuke Protection:** Automatically kicks suspicious new accounts and blocks compromised staff accounts with rapid-action timeouts.
- **🔑 Trial Key & UID Management:** Interactive key claim buttons, UID management (`/create_user`, `/remove_uid`), and bulk key seeding.
- **🌐 Web Dashboard (Flask + 2FA):** Full web management with Super Admin two-factor authentication, Discord OAuth2, and web embed sender.
- **⚡ Moderation Prefix Commands:** `?ban`, `?timeout`, `?clear`, `?warnings`, `?clearwarnings`, `?help`

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
DISCORD_REDIRECT_URI=http://127.0.0.1:8080/callback
MONGO_URI=mongodb+srv://...
FLASK_SECRET_KEY=your_secret_key
PORT=8080
GEMINI_API_KEY=your_gemini_api_key
GROQ_API_KEY=your_groq_api_key
OWNER_ID=your_discord_id
```

### 3. Run the Bot & Dashboard
```bash
python bot.py
```
Visit `http://localhost:8080` in your web browser.
