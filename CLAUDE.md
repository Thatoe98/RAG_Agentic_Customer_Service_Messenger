# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Messenger Bot — Project Guide

## Overview

Facebook Messenger bot for **Cross Culture Education** (Myanmar → Thailand university consulting). Answers inquiries via Gemini AI with local RAG, escalates to a supervisor via Telegram, and ships an admin webapp at `/admin`.

**Admin webapp features:** training chat (guidelines), knowledge-file manager, conversations (history / toggle bot / direct reply / clear memory), analytics, token usage, AI recommendations, Meta Ads dashboard.

---

## Development

```bash
# Setup (venv already at .venv/)
pip install -r requirements.txt

# Run locally
uvicorn main:app --reload --port 8000
# Admin panel: http://localhost:8000/admin

# Webhooks need public HTTPS — use ngrok for local testing
ngrok http 8000
```

Copy `.env.example` → `.env`. No test suite — verify by running the app.

---

## Deployment

**Hostinger KVM2 VPS** — Ubuntu 24.04 · `72.60.235.218` · domain `bot.autom8agency.cloud`  
**Stack:** Docker + Traefik (in n8n stack at `/docker/n8n/docker-compose.yml`). Bot joins `n8n_default` network.

```bash
python _deploy.py      # full fresh deploy
python _redeploy.py    # incremental: upload changed files in FILES list, rebuild, restart
```

Both read `SERVER_HOST / SERVER_USER / SERVER_PASS / SERVER_DIR / BOT_DOMAIN` from `.env`.  
SSH only reachable via Hostinger hPanel terminal (port 22 blocked externally).

**When adding new files**, add them to the `FILES` list in `_redeploy.py` — it only uploads what's listed.

```bash
# Server-side
docker logs messenger-bot-messenger-bot-1 --tail 50
cd /docker/messenger-bot && docker compose up -d
# Networking issue (conntrack overflow): systemctl restart docker
```

**Webhook registration** (one-time):
- Facebook: Meta Developer Portal → Messenger → Webhooks → `https://bot.autom8agency.cloud/webhook`
- Telegram: `curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://bot.autom8agency.cloud/telegram-webhook"`

---

## Architecture

```
Customer (Messenger)
        │  POST /webhook
        ▼
   main.py (FastAPI)
        ▼
   agent.py (Gemini)   ← system_prompt.txt + active guidelines from DB
    ├── search_knowledge(query) → rag.py → NumPy cosine over SQLite chunks
    └── escalate_to_human(reason) → tools/handover.py → Telegram
          Thread marked escalated — bot silent until supervisor sends /done or /reset

Supervisor (Telegram) replies → POST /telegram-webhook → forwarded to customer on Messenger
```

```
Admin (browser) → admin/routes.py
  ├── /admin/chat          trainer_agent.py: search KB + guideline CRUD (add/edit/delete)
  ├── /admin/files         rag.ingest() → chunk + embed → SQLite
  ├── /admin/conversations users list, message history, bot toggle, direct reply,
  │                        clear-memory (wipes in-memory LLM context),
  │                        clear-all (wipes context + SQLite messages),
  │                        refresh-profile (re-fetches name from Facebook)
  ├── /admin/analytics     stats + token cost
  ├── /admin/recommendations Gemini analysis → suggestions
  └── /admin/ads           Meta Ads dashboard: account insights, campaign list,
                           pause/resume/budget controls, AI recommendations
                           (powered by ads.py → graph.facebook.com/v22.0 Marketing API)
```

**Admin inbox takeover:** when the owner replies from the Facebook Page inbox directly, the bot detects the echo event and silences itself for `ADMIN_SILENCE_TIMEOUT` minutes.

---

## Meta Ads (`ads.py`)

Graph API v22.0, Marketing API. All functions are async `httpx.AsyncClient` — same pattern as `messenger.py`. Config vars `META_AD_ACCOUNT_ID` and `META_ADS_ACCESS_TOKEN` are **optional** (`os.environ.get`); the page shows a "not configured" banner when they are absent and the app boots normally.

**Budgets:** the Marketing API always returns and accepts budgets in *minor* currency units (satang for THB, cents for USD). `ads.py` converts to major units (÷100) for display and back (×100) before writes. The user enters major units in the budget edit form.

**Token permission needed:** `ads_read` (for insights) + `ads_management` (for pause/resume/budget). The existing `FB_PAGE_ACCESS_TOKEN` does NOT have these — a separate System User token is required. See `META_ADS_SETUP.md`.

---

## RAG Pipeline (`rag.py`)

Embedding model `gemini-embedding-001`, 768-dim, L2-normalized. Chunks ~1000 chars / 150 overlap stored as float32 BLOBs in SQLite. Search is NumPy cosine similarity — no vector extension needed. Cache (in-memory matrix) invalidated on any ingest/delete.

## Behavior Training (`guidelines.py`)

`system_instruction` = `prompts/system_prompt.txt` + `## Learned Guidelines` block from DB. Trainer agent edits guidelines via tool calls; changes take effect on next customer message. Guidelines sidebar in `/admin/chat` shows sequential display numbers (1, 2, 3… via `loop.index`) — **not** DB ids, which have gaps after deletes. Each row has inline Edit/Delete buttons (HTMX partials: `_guidelines.html`, `_guideline_edit.html`). Trainer agent `list_guidelines` output also uses display numbers + shows `(id=N)` so the model uses the correct DB id for mutations.

---

## Facebook User Profile API

The old `GET /{psid}?fields=first_name,last_name,profile_pic` endpoint is **deprecated** — returns error 100/33 for all non-admin PSIDs. The current working approach is the Conversations API:

```
GET /me/conversations?user_id={psid}&fields=participants  →  participant.name
```

Profile pictures are **not available** via any current Graph API endpoint for PSIDs. The admin account (app developer) is the only exception because it bypasses the restriction. Use "Refresh All Names" on the conversations list to back-fill names for existing users.

---

## Environment Variables

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
| `ADMIN_SILENCE_TIMEOUT_MINUTES` | Optional — bot silence after admin inbox takeover (default 30) |
| `META_AD_ACCOUNT_ID` | Optional — numeric ad account ID (without `act_` prefix) for `/admin/ads` |
| `META_ADS_ACCESS_TOKEN` | Optional — System User token with `ads_read` + `ads_management` permissions |
| `SERVER_HOST/USER/PASS/DIR` | VPS credentials for deploy scripts |
| `BOT_DOMAIN` | Public domain (default `bot.autom8agency.cloud`) |

`GEMINI_MODEL` is **hardcoded** to `gemini-3-flash-preview` in `config.py` — not an env var.

---

## Notes

- **One uvicorn worker only.** `store.py` is in-memory; SQLite has one shared connection. Multiple workers split state.
- **Escalation state is not persisted.** `store.py` (in-memory) loses escalation flags and greeted state on restart. SQLite message history survives. Swap for Redis before scaling.
- **`store.clear_messages(psid)`** clears in-memory LLM context only. `convdb.delete_messages(psid)` wipes SQLite history. Admin panel "Clear Memory" / "Clear Chat + Memory" buttons call these respectively.
- **Trainer chat history** (`_history` in `admin/routes.py`) is in-memory and shared across all admin sessions. Clearing it affects everyone.
- **Telegram notifications are in Burmese** (`tools/handover.py`) — don't replace unless changing audience.
- **`usage_log` exports a function named `log`** — always call as `usage_log.log(...)`, never import it directly (shadows `logging.getLogger` locals).
- **`db.write_lock`** must be held for all SQLite writes; reads don't need it.
- **Remaining work:** upload real knowledge docs via `/admin/files`; swap `store.py` for Redis if restarts become frequent.
