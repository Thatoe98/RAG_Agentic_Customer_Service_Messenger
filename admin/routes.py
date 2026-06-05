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

import guidelines
import rag
from admin import trainer_agent
from config import ADMIN_PASSWORD

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")

# Single-operator trainer chat history (this is an internal admin tool).
_history: list[dict] = []
_history_lock = threading.Lock()

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


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
