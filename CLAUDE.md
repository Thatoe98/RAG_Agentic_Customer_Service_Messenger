# Messenger Bot — Project Guide

## Overview

A Facebook Messenger bot for **Cross Culture Education** (Myanmar → Thailand university consulting) that:
- Answers customer inquiries professionally using Gemini AI
- Retrieves company knowledge via **local RAG** (semantic search over an embedded knowledge base) — no more live Google Drive reads
- Escalates to a human supervisor via Telegram with full conversation context
- Supervisor replies from Telegram are forwarded back to the customer on Messenger
- Supervisor sends `/done` to hand the conversation back to the bot

It also ships an **admin webapp** (same FastAPI process) for the business owner to:
- **Train the bot via chat** — adjust tone/strategy/behavior in natural language; the trainer agent saves these as persistent *guidelines* injected into the customer bot's system prompt, and can test retrieval against the live knowledge base
- **Manage knowledge files** — upload (PDF / DOCX / TXT / CSV / MD) and delete documents; uploads are chunked, embedded, and indexed for RAG

---

## Restructure Plan (in progress, 2026-06)

Goal: stop burning tokens by dumping whole Drive docs into the model. Replace with RAG + an admin webapp for knowledge and behavior management.

**Decisions locked in:**
- **Embeddings:** Gemini `gemini-embedding-001` (768-dim, normalized). Cheap, strong Burmese/English cross-lingual, no local model to host.
- **Vector store:** plain SQLite (`data/knowledge.db`) — embeddings stored as float32 BLOBs, retrieval by brute-force cosine in NumPy. Zero native extensions, cross-platform (Windows dev + Linux VPS). Swap to sqlite-vec/pgvector only if the corpus grows large.
- **Admin frontend:** server-rendered Jinja2 + HTMX + Tailwind (CDN). No Node/build step.
- **Auth:** single shared `ADMIN_PASSWORD`, signed session cookie (Starlette `SessionMiddleware`).
- **Google Drive:** removed entirely. Knowledge now lives only in the RAG store.

**Build order / checklist:**
- [x] Plan + CLAUDE.md
- [x] `config.py` — drop Drive vars; add `ADMIN_PASSWORD`, `SESSION_SECRET`, `EMBEDDING_MODEL`, `DB_PATH`
- [x] `db.py` — SQLite connection + schema (`documents`, `chunks`, `guidelines`)
- [x] `rag.py` — embed / chunk / ingest / search / document CRUD
- [x] `guidelines.py` — guideline CRUD + compose customer system prompt
- [x] `agent.py` — replace `search_drive` with `search_knowledge`; inject guidelines
- [x] `admin/trainer_agent.py` — trainer chat agent (search + guideline tools)
- [x] `admin/routes.py` — login, chat, files routers
- [x] `templates/` — base, login, chat, files
- [x] `main.py` — mount admin router + session middleware
- [x] `requirements.txt`, `.env.example`, `.gitignore`
- [x] Delete `tools/drive.py`
- [x] `DEPLOY.md` — Hostinger KVM2 (systemd + nginx + certbot)
- [x] Smoke-tested locally (RAG ingest/search incl. Burmese, admin auth, upload). **Still TODO:** deploy + register webhooks + real Messenger test, then upload the real knowledge docs via the admin UI.

---

## Current Status

### Completed
- [x] Facebook Messenger webhook (receive messages, send replies, typing indicator)
- [x] Gemini AI agent with tool use (agentic loop with safety cap)
- [x] `escalate_to_human` tool — triggers Telegram handover
- [x] Telegram handover: supervisor notified with full transcript
- [x] Bidirectional bridge: supervisor replies in Telegram → sent to customer on Messenger
- [x] `/done` command in Telegram returns conversation to bot
- [x] Thread-safe in-memory conversation store (per user PSID)
- [x] Local RAG knowledge base (SQLite + Gemini embeddings) with `search_knowledge` tool
- [x] Admin webapp: training chat + knowledge-file manager
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
├── main.py                  # FastAPI app: FB + Telegram webhooks, mounts admin router + session middleware
├── agent.py                 # Customer-facing Gemini agent: search_knowledge + escalate_to_human
├── messenger.py             # Facebook Send API (send message, typing, get profile)
├── store.py                 # In-memory conversation state + Telegram↔PSID mapping
├── config.py                # Environment variable loading
├── db.py                    # SQLite connection + schema bootstrap (documents, chunks, guidelines)
├── rag.py                   # Embedding, chunking, ingest, semantic search, document CRUD
├── guidelines.py            # Admin-trained behavior guidelines + customer system-prompt composition
├── admin/
│   ├── routes.py            # Admin webapp: login, training chat, file manager
│   └── trainer_agent.py     # Trainer chat agent (RAG search + guideline edit tools)
├── tools/
│   └── handover.py          # Telegram notification and message forwarding
├── templates/               # Jinja2 + HTMX admin UI (base, login, chat, files)
├── prompts/
│   ├── system_prompt.txt    # Customer bot persona, tone, escalation rules
│   └── trainer_prompt.txt   # Trainer agent persona (admin-facing)
├── data/                    # SQLite knowledge.db lives here (gitignored)
├── requirements.txt
├── railway.toml             # Railway deployment config (legacy)
├── DEPLOY.md                # Hostinger KVM2 VPS deployment guide
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
   agent.py (Gemini)   ← system prompt = base persona + admin guidelines (guidelines.py)
    ├── search_knowledge(query) → rag.py → embed query → cosine over SQLite chunks → top-k text
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

### Admin webapp (same FastAPI process, `/admin`)

```
Business owner (browser)
        │  login (ADMIN_PASSWORD → signed session cookie)
        ▼
   admin/routes.py
   ├── /admin/chat   ── trainer_agent.py (Gemini)
   │                      ├── search_knowledge(query)        test what the bot can find
   │                      ├── save_guideline / update / delete  edit persistent behavior
   │                      └── list_guidelines
   │                            │
   │                            ▼  guidelines.py → SQLite `guidelines`
   │                      (these guidelines are injected into the CUSTOMER bot's prompt)
   │
   └── /admin/files  ── upload → rag.ingest() → parse + chunk + embed → SQLite
                        delete → rag.delete_document()
```

---

## RAG Pipeline (`rag.py`)

- **Embedding model:** `gemini-embedding-001`, `output_dimensionality=768`, L2-normalized. Query embeddings use `task_type=RETRIEVAL_QUERY`; document chunks use `RETRIEVAL_DOCUMENT`.
- **Chunking:** ~1000 chars per chunk with ~150 char overlap, split on paragraph/sentence boundaries.
- **Storage:** SQLite. `chunks.embedding` is a raw float32 BLOB (`numpy.tobytes()`). No vector extension.
- **Search:** load all chunk vectors into a NumPy matrix, cosine similarity vs. the query vector, return top-k chunk texts with their source filename. Fast for thousands of chunks; revisit if the corpus reaches tens of thousands.
- **Parsers:** PDF (`pypdf`), DOCX (`python-docx`), TXT/MD/CSV (decoded text).
- **Cache:** the in-memory vector matrix is cached and invalidated on any ingest/delete so search stays cheap.

## Behavior Training (`guidelines.py`)

- The customer bot's `system_instruction` = `prompts/system_prompt.txt` (base persona) **+** a dynamically rendered `## Learned Guidelines` block listing every active guideline from the DB.
- The trainer chat agent edits these guidelines through tool calls, so the owner "trains" the bot conversationally (e.g. "always mention the free consultation", "be more concise with parents"). Changes take effect on the customer bot's next message — no redeploy.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values.

| Variable | Description |
|---|---|
| `FB_PAGE_ACCESS_TOKEN` | From Meta Developer Portal → your App → Messenger → Page token |
| `FB_VERIFY_TOKEN` | Any random string you choose — used once during webhook setup |
| `FB_APP_SECRET` | Optional but recommended — enables webhook signature verification |
| `GEMINI_API_KEY` | From [Google AI Studio](https://aistudio.google.com) |
| `TELEGRAM_BOT_TOKEN` | From Telegram `@BotFather` — `/newbot` |
| `TELEGRAM_SUPERVISOR_CHAT_ID` | Your personal chat ID or a group ID (use `@userinfobot` to find it) |
| `ADMIN_PASSWORD` | Password for the `/admin` webapp login |
| `SESSION_SECRET` | Random string used to sign admin session cookies |
| `EMBEDDING_MODEL` | Optional — defaults to `gemini-embedding-001` |
| `DB_PATH` | Optional — defaults to `data/knowledge.db` |

> Google Drive variables (`GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_DRIVE_FOLDER_ID`) are **no longer used** — knowledge is managed through the admin webapp.

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
