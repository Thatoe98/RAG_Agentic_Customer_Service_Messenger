import hashlib
import hmac
import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

import messenger
import store
from agent import handle_message
from config import ADMIN_SILENCE_TIMEOUT, FB_APP_SECRET, FB_VERIFY_TOKEN, GREETING_MESSAGE
from tools.handover import notify_supervisor

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI()


# ── Facebook webhook ────────────────────────────────────────────────────────

@app.get("/webhook")
async def fb_verify(request: Request):
    params = dict(request.query_params)
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == FB_VERIFY_TOKEN
    ):
        return PlainTextResponse(params["hub.challenge"])
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def fb_webhook(request: Request):
    body = await request.body()

    if FB_APP_SECRET:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            FB_APP_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=403, detail="Bad signature")

    payload = json.loads(body)
    if payload.get("object") != "page":
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            msg = event.get("message", {})
            if not msg:
                continue
            if msg.get("is_echo"):
                mid = msg.get("mid", "")
                text = msg.get("text", "")
                if text and not store.is_bot_mid(mid):
                    # A human admin sent this directly from the Page inbox
                    psid = event["recipient"]["id"]
                    if store.is_admin_silenced(psid, ADMIN_SILENCE_TIMEOUT):
                        store.refresh_admin_silence(psid)
                    else:
                        log.info("Admin inbox takeover detected for %s", psid)
                        store.set_admin_silenced(psid)
            else:
                psid = event["sender"]["id"]
                text = msg.get("text", "").strip()
                if text:
                    await _process(psid, text)

    return {"status": "ok"}


async def _process(psid: str, text: str):
    try:
        if store.is_admin_silenced(psid, ADMIN_SILENCE_TIMEOUT) and not store.is_escalated(psid):
            log.info("Bot silenced by admin for %s; ignoring message", psid)
            return
        await messenger.send_typing(psid)
        if not store.is_greeted(psid):
            store.mark_greeted(psid)
            await messenger.send_message(psid, GREETING_MESSAGE)
        reply = await handle_message(psid, text)
        if reply:
            await messenger.send_message(psid, reply)
    except Exception:
        log.exception("Error processing message from %s", psid)
        await messenger.send_message(
            psid, "I'm sorry, something went wrong. Please try again in a moment."
        )


# ── Telegram webhook (supervisor replies) ───────────────────────────────────

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"ok": True}

    text = message.get("text", "").strip()
    msg_id = message["message_id"]
    reply_to = message.get("reply_to_message")

    if not reply_to:
        return {"ok": True}

    # Resolve PSID: check the replied-to message, then one level up for nested replies
    psid = store.psid_from_telegram_msg(reply_to["message_id"])
    if not psid:
        grandparent = reply_to.get("reply_to_message")
        if grandparent:
            psid = store.psid_from_telegram_msg(grandparent["message_id"])

    if not psid:
        return {"ok": True}

    # /reset — clear escalation silently (no message sent to customer)
    if text.lower().startswith("/reset"):
        store.reset_escalation(psid)
        return {"ok": True}

    # /done — hand conversation back to bot
    if text.lower().startswith("/done"):
        store.reset_escalation(psid)
        store.clear_messages(psid)
        await messenger.send_message(
            psid,
            "Our team has finished assisting you. Is there anything else I can help you with?",
        )
        return {"ok": True}

    # Forward supervisor reply to the customer on Messenger
    if text:
        store.add_message(psid, "assistant", f"[Supervisor] {text}")
        # Register this message ID so further thread replies also resolve
        store.register_telegram_msg(psid, msg_id)
        await messenger.send_message(psid, text)

    return {"ok": True}


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}
