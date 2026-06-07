# Messenger Bot — Project Guide

## Overview

A Facebook Messenger bot for **Cross Culture Education** (Myanmar → Thailand university consulting) that:
- Answers customer inquiries professionally using Gemini AI (`gemini-3-flash-preview`)
- Retrieves company knowledge via **local RAG** (semantic search over an embedded knowledge base)
- Escalates to a human supervisor via Telegram with full conversation context
- Supervisor replies from Telegram are forwarded back to the customer on Messenger
- Supervisor sends `/done` to hand the conversation back to the bot; `/reset` to clear escalation silently

It ships an **admin webapp** (`/admin`) for the business owner to:
- **Train the bot via chat** — adjust tone/strategy/behavior; the trainer agent saves persistent *guidelines* injected into the customer bot's system prompt
- **Manage knowledge files** — upload (PDF / DOCX / TXT / CSV / MD), delete; uploads are chunked, embedded, indexed for RAG
- **View conversations** — browse all users, read full message histories, toggle bot on/off per user, reply directly from the panel
- **Analytics** — total users, active users, message counts, daily breakdown, escalation/bot-off counts
- **Token usage** — input/output token counts and USD cost by source (agent, trainer, recommendations)
- **AI recommendations** — on-demand Gemini analysis of recent messages + guidelines → actionable suggestions

---

## Deployment

**Hostinger KVM2 VPS** — Ubuntu 24.04, IP `72.60.235.218`  
**Domain:** `bot.autom8agency.cloud`  
**Stack:** Docker + Traefik (reverse proxy with auto-TLS from Let's Encrypt)

### How it runs on the server

Traefik is part of the **n8n stack** at `/docker/n8n/docker-compose.yml`. It owns ports 80 and 443 and serves as the HTTPS entry point for all services, including the bot.

The bot lives at `/docker/messenger-bot/` and joins the shared `n8n_default` Docker network so Traefik can route `bot.autom8agency.cloud` to it.

```
Internet → Traefik (:443) → n8n_default network → messenger-bot:8000
```

### Deploy scripts (run locally from this directory)

```bash
python _deploy.py      # full fresh deploy: upload all files, build image, start
python _redeploy.py    # incremental: upload changed files, rebuild, restart
```

Both read credentials from `.env` (`SERVER_HOST`, `SERVER_USER`, `SERVER_PASS`, `SERVER_DIR`, `BOT_DOMAIN`).

### Server maintenance

```bash
# SSH access (via Hostinger hPanel terminal — port 22 is not externally reachable)
# Docker management
docker ps
docker logs messenger-bot-messenger-bot-1 --tail 50
cd /docker/messenger-bot && docker compose up -d

# If the site becomes unreachable (conntrack overflow):
systemctl restart docker   # resets Docker networking, containers auto-restart
# Or as a last resort: reboot the VPS from hPanel

# Conntrack limits (already applied — prevents the networking issue):
# net.netfilter.nf_conntrack_max = 131072
# net.netfilter.nf_conntrack_tcp_timeout_established = 3600
# net.netfilter.nf_conntrack_tcp_timeout_time_wait = 15

# Auto-recovery cron (already set):
# */5 * * * * curl -sf --max-time 10 http://localhost:80/health > /dev/null || systemctl restart docker
```

### Webhook registration

**Facebook** (Meta Developer Portal → Messenger → Webhooks):
- Callback URL: `https://bot.autom8agency.cloud/webhook`
- Verify Token: `FB_VERIFY_TOKEN` from `.env`
- Subscribe to: `messages`

**Telegram** (run once):
```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://bot.autom8agency.cloud/telegram-webhook"
```

---

## Project Structure

```
messenger_bot_with_claude/
├── main.py                  # FastAPI app: FB + Telegram webhooks, health, session middleware
├── agent.py                 # Customer-facing Gemini agent: search_knowledge + escalate_to_human
├── messenger.py             # Facebook Send API (send message, typing, get profile)
├── store.py                 # In-memory conversation state + Telegram↔PSID mapping
├── conversations.py         # SQLite: user profiles, message history, analytics queries
├── usage_log.py             # Token usage logging + cost stats (Gemini 2.0 Flash pricing)
├── config.py                # Environment variable loading
├── db.py                    # SQLite schema bootstrap (documents, chunks, guidelines, users, messages, token_usage, recommendations)
├── rag.py                   # Embedding, chunking, ingest, semantic search, document CRUD
├── guidelines.py            # Admin-trained behavior guidelines + customer system-prompt composition
├── admin/
│   ├── routes.py            # Admin webapp: login, training chat, files, conversations, analytics, recommendations
│   └── trainer_agent.py     # Trainer chat agent (RAG search + guideline edit tools)
├── tools/
│   └── handover.py          # Telegram notification and message forwarding
├── templates/               # Jinja2 + HTMX admin UI
│   ├── base.html, login.html, chat.html, files.html
│   ├── conversations.html, conversation_view.html
│   ├── analytics.html, recommendations.html
│   └── _chat_turn.html, _conv_rows.html, _messages.html, _recommendations_result.html
├── prompts/
│   ├── system_prompt.txt    # Customer bot persona, tone, escalation rules
│   └── trainer_prompt.txt   # Trainer agent persona (admin-facing)
├── data/                    # SQLite knowledge.db lives here (gitignored)
├── _deploy.py               # Full fresh deploy via SSH (upload + build + start)
├── _redeploy.py             # Incremental redeploy via SSH (upload changed files + restart)
├── _ssh_compose.py          # SSH util: run docker compose commands
├── _ssh_docker.py           # SSH util: show docker ps
├── _ssh_explore.py          # SSH util: explore server filesystem
├── _ssh_start.py            # SSH util: start containers
├── requirements.txt
├── DEPLOY.md                # Hostinger VPS deployment guide (nginx/systemd path, superseded by Docker)
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
   agent.py (Gemini)   ← system prompt = base persona + admin guidelines
    ├── search_knowledge(query) → rag.py → cosine over SQLite chunks → top-k text
    └── escalate_to_human(reason)
              │
              ▼
        tools/handover.py → Telegram notify supervisor (with transcript)
        Thread marked escalated — bot goes silent

Supervisor (Telegram)
        │  Reply to escalation message
        ▼
   POST /telegram-webhook
   ├── /done  → unlock thread, bot resumes
   ├── /reset → unlock silently (no customer message)
   └── text   → forward to customer on Messenger
```

### Admin webapp (`/admin`)

```
Business owner (browser)
        │  login → signed session cookie
        ▼
   admin/routes.py
   ├── /admin/chat          trainer_agent.py (Gemini): search + guideline CRUD
   ├── /admin/files         upload → rag.ingest() → chunk + embed → SQLite
   │                        delete → rag.delete_document()
   ├── /admin/conversations list users → view history → toggle bot → admin reply
   ├── /admin/analytics     user/message stats + daily breakdown + token cost
   └── /admin/recommendations Gemini analysis of recent data → suggestions
```

### Admin inbox takeover (Facebook Page inbox)

When the business owner replies directly from the Facebook Page inbox (not the admin panel), the bot detects the echo event and silences itself for `ADMIN_SILENCE_TIMEOUT` minutes. This lets the owner handle a conversation manually without going through the admin panel.

---

## RAG Pipeline (`rag.py`)

- **Embedding model:** `gemini-embedding-001`, 768-dim, L2-normalized. Query: `RETRIEVAL_QUERY`; docs: `RETRIEVAL_DOCUMENT`.
- **Chunking:** ~1000 chars per chunk, ~150 char overlap, split on paragraph/sentence boundaries.
- **Storage:** SQLite. `chunks.embedding` is a raw float32 BLOB. No vector extension.
- **Search:** NumPy cosine similarity over all chunk vectors. Fast for thousands of chunks.
- **Parsers:** PDF (`pypdf`), DOCX (`python-docx`), TXT/MD/CSV (decoded text).
- **Cache:** in-memory vector matrix invalidated on any ingest/delete.

## Behavior Training (`guidelines.py`)

The customer bot's `system_instruction` = `prompts/system_prompt.txt` + a `## Learned Guidelines` block from the DB. The trainer chat agent edits guidelines through tool calls. Changes take effect on the next customer message — no redeploy.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values.

| Variable | Description |
|---|---|
| `FB_PAGE_ACCESS_TOKEN` | Meta Developer Portal → your App → Messenger → Page token |
| `FB_VERIFY_TOKEN` | Any random string — used once during webhook setup |
| `FB_APP_SECRET` | Optional — enables webhook signature verification |
| `GEMINI_API_KEY` | From Google AI Studio |
| `TELEGRAM_BOT_TOKEN` | From `@BotFather` |
| `TELEGRAM_SUPERVISOR_CHAT_ID` | Your personal chat ID or group ID |
| `ADMIN_PASSWORD` | Password for `/admin` login |
| `SESSION_SECRET` | Random string for signing session cookies |
| `EMBEDDING_MODEL` | Optional — defaults to `gemini-embedding-001` |
| `DB_PATH` | Optional — defaults to `data/knowledge.db` |
| `GREETING_MESSAGE` | Optional — override the default first-contact greeting |
| `ADMIN_SILENCE_TIMEOUT_MINUTES` | Optional — minutes bot stays silent after admin inbox takeover (default 30) |
| `SERVER_HOST` | VPS IP — used by deploy scripts |
| `SERVER_USER` | VPS SSH user (root) |
| `SERVER_PASS` | VPS SSH password |
| `SERVER_DIR` | Remote app directory (default `/docker/messenger-bot`) |
| `BOT_DOMAIN` | Public domain (default `bot.autom8agency.cloud`) |

---

## Current Status

### Completed
- [x] Facebook Messenger webhook (receive, send, typing indicator)
- [x] Gemini AI agent with tool use (agentic loop, 10-iteration safety cap)
- [x] Force-escalation when customer explicitly asks for human (bypasses model judgment)
- [x] `escalate_to_human` tool → Telegram handover with transcript
- [x] Bidirectional bridge: supervisor Telegram replies → customer Messenger
- [x] `/done` command returns conversation to bot (clears history)
- [x] `/reset` command clears escalation silently
- [x] Thread-safe in-memory conversation store
- [x] Local RAG knowledge base (SQLite + Gemini embeddings)
- [x] Admin webapp: training chat + knowledge-file manager
- [x] Admin conversations view (history, toggle bot, direct reply)
- [x] Admin analytics (users, messages, daily breakdown, token cost)
- [x] AI recommendations page
- [x] Token usage logging with USD cost tracking
- [x] Admin inbox takeover detection (Facebook Page inbox → bot silences)
- [x] Facebook webhook signature verification
- [x] `/health` endpoint
- [x] Deployed to Hostinger VPS via Docker + Traefik
- [x] Auto-recovery cron (restarts Docker if health check fails)
- [x] conntrack limits tuned to prevent networking overflow

### Remaining
- [ ] Replace `[Company Name]` placeholder in `prompts/system_prompt.txt`
- [ ] Upload real knowledge documents via `/admin/files`
- [ ] **Persistence** — `store.py` is in-memory; restart clears escalation state and greeted flags. Swap for Redis before scaling or if restarts become frequent.

---

## Notes

- **One uvicorn worker only.** `store.py` is in-memory and SQLite has one shared connection. Multiple workers would split state. One worker is plenty for this workload.
- **Conversation history survives restarts** (persisted in SQLite via `conversations.py`) but in-memory escalation state (`store.py`) does not.
- **Gemini model** is `gemini-3-flash-preview` in `config.py`.
- **SSH to VPS** is only accessible via Hostinger hPanel terminal (port 22 is not reachable from external IPs).
