# 🤖 AI Customer Support Bot — Facebook Messenger + RAG + Human Handoff

> An intelligent, production-ready customer support bot for a Myanmar→Thailand university consulting business, built on **Google Gemini**, a **custom RAG pipeline**, and a **bidirectional Telegram handoff** system — with a full **admin webapp** for no-code bot training.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat&logo=fastapi&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2.0%20Flash-4285F4?style=flat&logo=google&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-RAG%20Store-003B57?style=flat&logo=sqlite&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Supervisor%20Bridge-2CA5E0?style=flat&logo=telegram&logoColor=white)
![Facebook](https://img.shields.io/badge/Facebook-Messenger%20API-1877F2?style=flat&logo=facebook&logoColor=white)

---

## ✨ What This Project Does

Customers message the business on **Facebook Messenger**. The bot:

1. **Answers** inquiries using Gemini AI grounded in company documents
2. **Searches** an embedded knowledge base (RAG) for specific facts — tuition, intake dates, program requirements
3. **Escalates** gracefully to a human supervisor via **Telegram** when it can't help, with full conversation context
4. **Bridges** replies from Telegram back to the customer on Messenger in real time
5. **Returns** conversations to the bot when the supervisor types `/done`

The business owner trains and manages the bot through a **web admin panel** — no code changes, no redeployment.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Customer Journey                         │
└─────────────────────────────────────────────────────────────────┘

    Customer (Facebook Messenger)
           │  POST /webhook
           ▼
      FastAPI (main.py)
           │
           ▼
      Gemini Agent (agent.py)
      ┌────┴────────────────────────────────┐
      │  system prompt = base persona       │
      │             + live guidelines (DB)  │
      │                                     │
      ├── search_knowledge(query) ──────────┼──► RAG pipeline (rag.py)
      │        ▲                            │        embed query → cosine search
      │        └─ SQLite chunks ────────────┘        → top-k context text
      │
      └── escalate_to_human(reason)
               │
               ▼
         Telegram Supervisor
         (full transcript)
               │
               │ supervisor replies in Telegram
               ▼
         POST /telegram-webhook
               │  forward to customer
               ▼
         Facebook Messenger API

┌─────────────────────────────────────────────────────────────────┐
│                        Admin Webapp (/admin)                    │
└─────────────────────────────────────────────────────────────────┘

    Business Owner (browser)  →  /admin/login  →  session cookie
           │
           ├─ /admin/chat  ──►  Trainer Agent (Gemini)
           │                        ├─ search_knowledge()   test RAG
           │                        ├─ save_guideline()     train bot
           │                        ├─ update_guideline()
           │                        └─ delete_guideline()   → SQLite guidelines
           │                             └──► injected into customer bot's prompt
           │
           ├─ /admin/files ──►  Upload / delete knowledge docs
           │                        PDF, DOCX, TXT, CSV, MD
           │                        → chunk → embed → SQLite
           │
           ├─ /admin/conversations ──►  View all customer conversations
           │                             Reply as admin, toggle bot on/off
           │
           └─ /admin/analytics ──►  Usage stats + token tracking
              /admin/recommendations ──►  AI-generated improvement suggestions
```

---

## 🔑 Key Features

### 🧠 Retrieval-Augmented Generation (RAG) — Built from Scratch
- Documents embedded with **Gemini `gemini-embedding-001`** (768-dim, L2-normalized)
- Stored as raw `float32` BLOBs in **SQLite** — zero native extensions
- Retrieved by **brute-force cosine similarity** in NumPy — no vector database dependency
- In-memory chunk matrix cache, invalidated on ingest/delete
- Supports: **PDF, DOCX, TXT, CSV, Markdown**

### 🤖 Dual Agentic Architecture (Gemini Function Calling)
- **Customer Agent**: `search_knowledge` + `escalate_to_human` tools with a 10-iteration safety cap
- **Trainer Agent**: `search_knowledge` + `save/update/delete_guideline` tools for conversational bot training
- Both agents use the **full agentic loop pattern** (tool call → result → next generation)

### 🔁 Human-in-the-Loop Escalation Bridge
- AI detects when a human is needed (via tool call or phrase detection)
- Sends full conversation transcript to supervisor on **Telegram**
- Supervisor replies in Telegram thread → forwarded to customer on Messenger
- `/done` hands back to bot; `/reset` silently clears escalation
- Thread-safe message ID tracking across nested Telegram replies

### 🎓 Conversational Bot Training (No Code)
- Business owner chats with a trainer agent to adjust bot behavior
- "Always mention the free consultation", "Be more concise with parents"
- Guidelines saved to SQLite, **injected dynamically** into customer bot's system prompt
- Changes take effect on the next customer message — **no redeploy**

### 🛡️ Admin Inbox Takeover Detection
- Detects when a human admin replies directly from the Facebook Page inbox
- Silences the bot automatically for a configurable timeout period
- Bot resumes after timeout or when explicitly re-enabled

### 📊 Analytics & AI Recommendations
- Token usage tracked per request (source, model, input/output tokens)
- Conversation analytics: total users, active this week, escalation rate
- On-demand AI-generated improvement recommendations based on real usage data

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **API Framework** | FastAPI (async) | Native async, automatic OpenAPI docs, clean router mounting |
| **AI Model** | Google Gemini 2.0 Flash | Fast, multilingual (Burmese+English), native function calling |
| **Embeddings** | Gemini `gemini-embedding-001` | 768-dim, strong cross-lingual, no local model to host |
| **Vector Store** | SQLite + NumPy | Zero dependencies, cross-platform, trivially deployable |
| **Database** | SQLite (WAL mode) | Persistent state, thread-safe with shared write lock |
| **Admin UI** | Jinja2 + HTMX + Tailwind CDN | Server-rendered, no build step, reactive without React |
| **Session Auth** | Starlette `SessionMiddleware` | Signed cookies, single shared password |
| **HTTP Client** | httpx (async) | Async-native, used for Messenger API + Telegram API calls |
| **Messenger** | Facebook Graph API v21+ | Webhook-based, signature verification |
| **Supervisor** | Telegram Bot API | Threaded replies, command parsing, typing indicators |

---

## 📁 Project Structure

```
messenger_bot_with_claude/
├── main.py              # FastAPI: FB + Telegram webhooks, admin mounting
├── agent.py             # Customer Gemini agent (search + escalate tools)
├── rag.py               # RAG pipeline: chunk, embed, ingest, cosine search
├── guidelines.py        # Behavior guidelines CRUD + system prompt composition
├── db.py                # SQLite schema + thread-safe connection management
├── store.py             # In-memory conversation state + Telegram↔PSID mapping
├── conversations.py     # Persistent conversation + user history (SQLite)
├── messenger.py         # Facebook Send API wrapper
├── usage_log.py         # Token usage tracking
├── config.py            # Environment variable loading
├── admin/
│   ├── routes.py        # Admin webapp: auth, chat, files, conversations, analytics
│   └── trainer_agent.py # Trainer Gemini agent (guideline editing tools)
├── tools/
│   └── handover.py      # Telegram escalation + message forwarding
├── templates/           # Jinja2 + HTMX UI (12 templates)
│   ├── base.html
│   ├── login.html
│   ├── chat.html        # Trainer chat
│   ├── files.html       # Knowledge file manager
│   ├── conversations.html
│   ├── analytics.html
│   └── recommendations.html
├── prompts/
│   ├── system_prompt.txt  # Customer bot persona + escalation rules
│   └── trainer_prompt.txt # Trainer agent persona
├── data/                # SQLite knowledge.db (gitignored)
├── requirements.txt
├── railway.toml         # Railway deployment config
├── DEPLOY.md            # VPS deployment guide (systemd + nginx + certbot)
└── .env.example
```

---

## ⚙️ Setup

### Prerequisites
- Python 3.11+
- A [Google AI Studio](https://aistudio.google.com) API key
- A Facebook Developer App with Messenger enabled
- A Telegram bot (from `@BotFather`)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in your credentials
```

| Variable | Description |
|---|---|
| `FB_PAGE_ACCESS_TOKEN` | Meta Developer Portal → Messenger → Page token |
| `FB_VERIFY_TOKEN` | Any string — used once during webhook setup |
| `FB_APP_SECRET` | Optional — enables request signature verification |
| `GEMINI_API_KEY` | Google AI Studio |
| `TELEGRAM_BOT_TOKEN` | From `@BotFather` |
| `TELEGRAM_SUPERVISOR_CHAT_ID` | Your chat ID (from `@userinfobot`) |
| `ADMIN_PASSWORD` | Admin webapp login password |
| `SESSION_SECRET` | Random string for signing session cookies |

### 3. Run locally
```bash
uvicorn main:app --reload --port 8000
```

Expose with [ngrok](https://ngrok.com) for webhook testing:
```bash
ngrok http 8000
```

### 4. Register webhooks

**Facebook** — Meta Developer Portal:
- Callback URL: `https://your-domain.com/webhook`
- Verify Token: your `FB_VERIFY_TOKEN`
- Subscriptions: `messages`

**Telegram:**
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://your-domain.com/telegram-webhook"
```

### 5. Add knowledge documents
Open `https://your-domain.com/admin` → Files → Upload your PDFs, DOCX, or text files. The bot can answer questions from them immediately.

### 6. Train the bot
Open `https://your-domain.com/admin` → Chat → Tell the trainer agent how you want the bot to behave. Changes apply instantly.

---

## 🚀 Deployment

Refer to [`DEPLOY.md`](DEPLOY.md) for a full guide covering:
- Hostinger KVM2 VPS setup
- `systemd` service configuration
- `nginx` reverse proxy
- SSL with Certbot

---

## 🔮 Roadmap

- [ ] **Redis persistence** — swap in-memory `store.py` for Redis (multi-instance support)
- [ ] **Session timeout** — auto-unlock escalated threads after X hours of supervisor inactivity
- [ ] **Quick reply buttons** — Facebook Messenger chips for common questions
- [ ] **Multi-supervisor routing** — route issue types to different Telegram chats
- [ ] **Attachment handling** — process images/files customers send
- [ ] **CRM integration** — log conversations to HubSpot or Zoho

---

## 📄 License

MIT
