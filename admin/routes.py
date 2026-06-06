"""Admin webapp: login, training chat, and knowledge-file management.

Server-rendered (Jinja2 + HTMX). Mounted under /admin by main.py, which also
installs the session middleware used for login.
"""
import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import asyncio

import conversations as convdb
from db import get_conn, write_lock
import guidelines
import messenger
import rag
import store
import usage_log
from admin import trainer_agent
from config import ADMIN_PASSWORD, GEMINI_API_KEY, GEMINI_MODEL
from google import genai
from google.genai import types as gtypes

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

# Single-operator trainer chat history (this is an internal admin tool).
_history: list[dict] = []
_history_lock = threading.Lock()

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
_gemini = genai.Client(api_key=GEMINI_API_KEY)


def _authed(request: Request) -> bool:
    return bool(request.session.get("authed"))


# ── Auth ─────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _authed(request):
        return RedirectResponse("/admin/chat", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, password: str = Form(...)):
    if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
        request.session["authed"] = True
        return RedirectResponse("/admin/chat", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": "Incorrect password."}, status_code=401
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# ── Training chat ────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def index(request: Request):
    return RedirectResponse("/admin/chat", status_code=303)


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    with _history_lock:
        history = list(_history)
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"active": "chat", "history": history, "guidelines": guidelines.list_guidelines()},
    )


@router.post("/chat/send", response_class=HTMLResponse)
async def chat_send(request: Request, message: str = Form(...)):
    if not _authed(request):
        return HTMLResponse("Unauthorized", status_code=401)
    message = message.strip()
    if not message:
        return HTMLResponse("")

    with _history_lock:
        history = list(_history)
    try:
        reply = await trainer_agent.chat(history, message)
    except Exception:
        log.exception("Trainer agent error")
        reply = "Something went wrong handling that. Check the server logs."

    with _history_lock:
        _history.append({"role": "user", "content": message})
        _history.append({"role": "assistant", "content": reply})

    return templates.TemplateResponse(
        request,
        "_chat_turn.html",
        {"user_message": message, "assistant_message": reply},
    )


@router.post("/chat/clear")
async def chat_clear(request: Request):
    if not _authed(request):
        return HTMLResponse("Unauthorized", status_code=401)
    with _history_lock:
        _history.clear()
    return RedirectResponse("/admin/chat", status_code=303)


# ── File management ──────────────────────────────────────────────────────────

@router.get("/files", response_class=HTMLResponse)
async def files_page(request: Request, error: str | None = None, ok: str | None = None):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    docs = rag.list_documents()
    for d in docs:
        d["uploaded_str"] = datetime.fromtimestamp(
            d["uploaded_at"], tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
        d["size_kb"] = round((d["size_bytes"] or 0) / 1024, 1)
    return templates.TemplateResponse(
        request, "files.html", {"active": "files", "docs": docs, "error": error, "ok": ok}
    )


@router.post("/files/upload")
async def files_upload(request: Request, file: UploadFile):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)

    data = await file.read()
    if not data:
        return RedirectResponse("/admin/files?error=Empty+file.", status_code=303)
    if len(data) > _MAX_UPLOAD_BYTES:
        return RedirectResponse("/admin/files?error=File+too+large+(max+20MB).", status_code=303)

    try:
        import asyncio

        result = await asyncio.to_thread(
            rag.ingest, file.filename, file.content_type or "", data
        )
    except Exception as exc:
        log.exception("Ingest failed for %s", file.filename)
        return RedirectResponse(
            f"/admin/files?error=Could+not+process+file:+{exc}", status_code=303
        )

    return RedirectResponse(
        f"/admin/files?ok=Added+{result['filename']}+({result['num_chunks']}+chunks).",
        status_code=303,
    )


@router.post("/files/{doc_id}/delete")
async def files_delete(request: Request, doc_id: int):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    rag.delete_document(doc_id)
    return RedirectResponse("/admin/files?ok=Deleted.", status_code=303)


# ── Conversations ─────────────────────────────────────────────────────────────

def _fmt_ts(ts_str: str | None) -> str:
    if not ts_str:
        return "—"
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.strftime("%b %d, %H:%M")
    except Exception:
        return ts_str or "—"


@router.get("/conversations", response_class=HTMLResponse)
async def conversations_page(request: Request):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    users = convdb.list_users()
    for u in users:
        u["last_seen_str"] = _fmt_ts(u["last_seen"])
        preview = (u.get("last_message") or "")
        u["last_message_preview"] = preview[:70] + ("…" if len(preview) > 70 else "")
    return templates.TemplateResponse(
        request, "conversations.html",
        {"active": "conversations", "users": users},
    )


@router.get("/conversations/partial", response_class=HTMLResponse)
async def conversations_partial(request: Request):
    if not _authed(request):
        return HTMLResponse("", status_code=401)
    users = convdb.list_users()
    for u in users:
        u["last_seen_str"] = _fmt_ts(u["last_seen"])
        preview = (u.get("last_message") or "")
        u["last_message_preview"] = preview[:70] + ("…" if len(preview) > 70 else "")
    return templates.TemplateResponse(request, "_conv_rows.html", {"users": users})


@router.get("/conversations/{psid}/messages", response_class=HTMLResponse)
async def messages_partial(request: Request, psid: str):
    if not _authed(request):
        return HTMLResponse("", status_code=401)
    msgs = convdb.get_messages(psid)
    for m in msgs:
        m["ts_str"] = _fmt_ts(m["ts"])
    return templates.TemplateResponse(request, "_messages.html", {"messages": msgs})


@router.get("/conversations/{psid}", response_class=HTMLResponse)
async def conversation_view(request: Request, psid: str):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    user = convdb.get_user(psid)
    if not user:
        return RedirectResponse("/admin/conversations", status_code=303)
    msgs = convdb.get_messages(psid)
    for m in msgs:
        m["ts_str"] = _fmt_ts(m["ts"])
    return templates.TemplateResponse(
        request, "conversation_view.html",
        {"active": "conversations", "user": user, "messages": msgs},
    )


@router.post("/conversations/{psid}/toggle-bot")
async def toggle_bot(request: Request, psid: str):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    new_state = not convdb.get_bot_enabled(psid)
    convdb.set_bot_enabled(psid, new_state)
    if new_state:
        store.clear_admin_silence(psid)
    return RedirectResponse(f"/admin/conversations/{psid}", status_code=303)


@router.post("/conversations/{psid}/reply")
async def conversation_reply(request: Request, psid: str, message: str = Form(...)):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    message = message.strip()
    if message:
        try:
            await messenger.send_message(psid, message)
            tagged = f"[Admin] {message}"
            convdb.persist_message(psid, "assistant", tagged)
            store.add_message(psid, "assistant", tagged)
            # Auto-disable bot when admin manually replies
            convdb.set_bot_enabled(psid, False)
        except Exception:
            log.exception("Failed to send admin reply to %s", psid)
    return RedirectResponse(f"/admin/conversations/{psid}", status_code=303)


# ── Analytics ─────────────────────────────────────────────────────────────────

@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    stats = convdb.get_analytics()
    token_stats = usage_log.get_stats()
    return templates.TemplateResponse(
        request, "analytics.html",
        {"active": "analytics", "stats": stats, "tokens": token_stats},
    )


# ── Recommendations ───────────────────────────────────────────────────────────

def _load_recommendations() -> list[dict]:
    from db import get_conn
    rows = get_conn().execute(
        "SELECT id, ts, content FROM recommendations ORDER BY ts DESC LIMIT 20"
    ).fetchall()
    out = []
    for r in rows:
        try:
            dt = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            ts_str = dt.strftime("%b %d %Y, %H:%M UTC")
        except Exception:
            ts_str = r["ts"]
        out.append({"id": r["id"], "ts_str": ts_str, "content": r["content"]})
    return out


@router.get("/recommendations", response_class=HTMLResponse)
async def recommendations_page(request: Request):
    if not _authed(request):
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(
        request, "recommendations.html",
        {"active": "recommendations", "history": _load_recommendations()},
    )


@router.post("/recommendations/generate", response_class=HTMLResponse)
async def recommendations_generate(request: Request):
    if not _authed(request):
        return HTMLResponse("Unauthorized", status_code=401)

    stats = convdb.get_analytics()
    guidelines_list = guidelines.list_guidelines()

    msgs_text = "\n".join(f"- {m}" for m in stats["recent_user_messages"][:30]) or "None yet."
    gl_text = "\n".join(f"- {g['text']}" for g in guidelines_list) or "None yet."

    prompt = f"""You are analyzing a Facebook Messenger bot for Cross Culture Education (Myanmar → Thailand university consulting).

Current stats:
- Total customers: {stats['total_users']}
- Active this week: {stats['active_week']}
- Escalated conversations: {stats['escalated_count']}
- Bot disabled (manual mode): {stats['bot_off_count']}
- Total messages: {stats['total_messages']}

Recent customer messages (last 30):
{msgs_text}

Current bot guidelines:
{gl_text}

Provide 5–7 specific, actionable recommendations to improve the bot. For each:
1. What to do (concise title)
2. Why — one sentence based on the data above
3. How — e.g. "add a guideline saying…", "upload a document about…", "train the bot to…"

Be specific to the university consulting business. Format as a numbered list."""

    try:
        response = await asyncio.wait_for(
            _gemini.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=[gtypes.Content(role="user", parts=[gtypes.Part(text=prompt)])],
            ),
            timeout=45.0,
        )
        usage_log.log_response(response, source="recommendations", model=GEMINI_MODEL)
        result = response.candidates[0].content.parts[0].text
        # Persist
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with write_lock:
            get_conn().execute(
                "INSERT INTO recommendations (ts, content) VALUES (?, ?)", (now, result)
            )
            get_conn().commit()
        ts_str = datetime.now(timezone.utc).strftime("%b %d %Y, %H:%M UTC")
    except asyncio.TimeoutError:
        result = "Request timed out (45s). Try again — Gemini may be slow."
        ts_str = None
    except Exception:
        log.exception("Recommendations generation failed")
        result = "Failed to generate recommendations. Check server logs."
        ts_str = None

    return templates.TemplateResponse(
        request, "_recommendations_result.html",
        {"result": result, "ts_str": ts_str},
    )
