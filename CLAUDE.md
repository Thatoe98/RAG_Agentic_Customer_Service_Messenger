# Messenger Bot — Project Guide

## Overview

A Facebook Messenger bot for a business page that:
- Answers customer inquiries professionally using Gemini AI
- Reads company files from Google Drive when needed (products, pricing, policies)
- Escalates to a human supervisor via Telegram with full conversation context
- Supervisor replies from Telegram are forwarded back to the customer on Messenger
- Supervisor sends `/done` to hand the conversation back to the bot

---

## Current Status

### Completed
- [x] Facebook Messenger webhook (receive messages, send replies, typing indicator)
- [x] Gemini AI agent with tool use (agentic loop with safety cap)
- [x] `search_drive` tool — searches and reads Google Drive docs/sheets
- [x] `escalate_to_human` tool — triggers Telegram handover
- [x] Telegram handover: supervisor notified with full transcript
- [x] Bidirectional bridge: supervisor replies in Telegram → sent to customer on Messenger
- [x] `/done` command in Telegram returns conversation to bot
- [x] Thread-safe in-memory conversation store (per user PSID)
- [x] Drive result caching per conversation session
- [x] Telegram message ID tracking for nested thread replies
- [x] Facebook webhook signature verification (optional, via `FB_APP_SECRET`)
- [x] Railway deployment config

### Not Yet Done
- [x] Fill in `.env` with real credentials (Gemini key set; fill in FB + Telegram values)
- [ ] Replace `[Company Name]` in `prompts/system_prompt.txt`
- [ ] Deploy to Railway
- [ ] Register Facebook webhook URL in Meta Developer Portal
- [ ] Register Telegram webhook URL with BotFather
- [ ] Test end-to-end with a real Messenger conversation

---

## Project Structure

```
messenger_bot_with_claude/
├── main.py                  # FastAPI app: Facebook + Telegram webhook endpoints
├── agent.py                 # Gemini agentic loop with tool use
├── messenger.py             # Facebook Send API (send message, typing, get profile)
├── store.py                 # In-memory conversation state + Telegram↔PSID mapping
├── config.py                # Environment variable loading
├── tools/
│   ├── drive.py             # Google Drive search & read (Docs, Sheets, plain text)
│   └── handover.py          # Telegram notification and message forwarding
├── prompts/
│   └── system_prompt.txt    # AI persona, tone, escalation rules — edit freely
├── requirements.txt
├── railway.toml             # Railway deployment config
└── .env.example             # All required env vars with descriptions
```

---

## Architecture

```
Customer (Messenger)
        │  POST /webhook
        ▼
   main.py (FastAPI)
        │
        ▼
   agent.py (Gemini)
    ├── search_drive(query)     → tools/drive.py → Google Drive API
    └── escalate_to_human(reason)
              │
              ▼
        tools/handover.py
        Telegram notify supervisor (with full transcript)
        Thread marked escalated — bot goes silent

Supervisor (Telegram)
        │  Reply to escalation message
        ▼
   POST /telegram-webhook
        │  Forward reply to customer
        ▼
   messenger.py → Customer (Messenger)

Supervisor sends /done
        │
        ▼
   Thread unlocked — bot resumes
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values.

| Variable | Description |
|---|---|
| `FB_PAGE_ACCESS_TOKEN` | From Meta Developer Portal → your App → Messenger → Page token |
| `FB_VERIFY_TOKEN` | Any random string you choose — used once during webhook setup |
| `FB_APP_SECRET` | Optional but recommended — enables webhook signature verification |
| `GEMINI_API_KEY` | From [Google AI Studio](https://aistudio.google.com) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to service account `.json` file, or the raw JSON as a string |
| `GOOGLE_DRIVE_FOLDER_ID` | Optional — restrict Drive search to a specific shared folder |
| `TELEGRAM_BOT_TOKEN` | From Telegram `@BotFather` — `/newbot` |
| `TELEGRAM_SUPERVISOR_CHAT_ID` | Your personal chat ID or a group ID (use `@userinfobot` to find it) |

---

## Setup Steps

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Customize the bot persona
Edit `prompts/system_prompt.txt`:
- Replace `[Company Name]`
- Adjust tone, escalation triggers, and boundaries to match your business

### 4. Google Drive — service account setup
1. Go to [Google Cloud Console](https://console.cloud.google.com) → create a project
2. Enable **Google Drive API**
3. Create a **Service Account** → download the JSON key
4. Share your Drive folder with the service account email (e.g. `bot@project.iam.gserviceaccount.com`)
5. Set `GOOGLE_SERVICE_ACCOUNT_JSON` to the path of the JSON file

### 5. Telegram — supervisor bot setup
1. Message `@BotFather` → `/newbot` → get your `TELEGRAM_BOT_TOKEN`
2. Message `@userinfobot` to get your `TELEGRAM_SUPERVISOR_CHAT_ID`
3. Start a conversation with your new bot (required before it can message you)

### 6. Run locally
```bash
uvicorn main:app --reload --port 8000
```
Use [ngrok](https://ngrok.com) to expose localhost for webhook testing:
```bash
ngrok http 8000
```

### 7. Register webhooks

**Facebook** — in Meta Developer Portal:
- Callback URL: `https://your-domain.com/webhook`
- Verify Token: your `FB_VERIFY_TOKEN`
- Subscribe to: `messages`

**Telegram** — run once to register:
```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://your-domain.com/telegram-webhook"
```

### 8. Deploy to Railway
1. Push this folder to a GitHub repo
2. Connect repo to [Railway](https://railway.app)
3. Add all `.env` values in Railway dashboard → Variables
4. Railway auto-deploys on push

---

## Key Files to Edit

| File | What to change |
|---|---|
| `prompts/system_prompt.txt` | Company name, tone, escalation rules |
| `config.py` | Model name if you want to use a different Gemini model |
| `tools/drive.py` | `_MAX_TEXT_BYTES` if you need more/less context per document |
| `store.py` | Swap in Redis for multi-instance deployments |

---

## Future Plans

### Short term
- [ ] **Persistence** — replace in-memory `store.py` with Redis so conversations survive restarts and work across multiple instances
- [x] **Supervisor `/reset` command** — reply `/reset` to any escalation thread in Telegram to silently clear escalation (no message sent to customer)
- [x] **Typing indicator to supervisor** — `sendChatAction` typing is sent to Telegram before each forwarded customer message
- [x] **Greeting message** — auto-sent on first contact; override via `GREETING_MESSAGE` env var

### Medium term
- [ ] **Multi-supervisor support** — route different issue types to different Telegram chats (e.g. billing → finance group, tech → support group)
- [ ] **Session timeout** — automatically unlock escalated threads after X hours of supervisor inactivity
- [ ] **Quick reply buttons** — add Facebook Messenger quick reply chips for common questions
- [ ] **Conversation history on restart** — persist message history to a database (SQLite or Postgres)
- [ ] **Admin dashboard** — simple web UI to view active conversations and escalation queue

### Long term
- [ ] **Analytics** — track resolution rate, escalation rate, common topics, response time
- [ ] **Multi-language support** — detect language and respond accordingly
- [ ] **Attachment handling** — let customers send images/files and have Gemini describe or process them
- [ ] **Proactive messaging** — follow up with customers after X days (order updates, promotions)
- [ ] **CRM integration** — log conversations to HubSpot, Zoho, or similar

---

## Notes

- **State is in-memory by default.** Restarting the server clears all conversation history and escalation state. Implement Redis (`store.py`) before going to production.
- **Gemini model** is set to `gemini-2.0-flash` in `config.py`. Change to `gemini-1.5-pro` for more complex reasoning if needed.
- **Google Drive reads are cached per conversation session** to avoid redundant API calls.
- **Telegram thread mapping** tracks all message IDs (escalation notice + every supervisor reply) so nested replies always resolve to the correct customer.
