import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_SUPERVISOR_CHAT_ID

_TG = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


async def notify_supervisor(
    psid: str,
    user_name: str,
    summary: str,
    reason: str,
) -> int:
    """
    Send escalation notice to the supervisor on Telegram.
    Returns the Telegram message_id of the notice (used to map replies back to PSID).
    """
    text = (
        f"🔔 *Handover Request*\n\n"
        f"*Customer:* {user_name}\n"
        f"*Reason:* {reason}\n\n"
        f"*Conversation summary:*\n{summary}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"↩ *Reply to this message* to send a message to the customer.\n"
        f"Send /done as a reply when finished — the bot will resume."
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_TG}/sendMessage",
            json={
                "chat_id": TELEGRAM_SUPERVISOR_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]


async def forward_customer_message(
    user_name: str,
    text: str,
    escalation_msg_id: int,
) -> int:
    """
    Forward a new customer message to the supervisor during an active handover.
    Returns the Telegram message_id so we can extend the thread mapping.
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{_TG}/sendChatAction",
            json={"chat_id": TELEGRAM_SUPERVISOR_CHAT_ID, "action": "typing"},
        )
        resp = await client.post(
            f"{_TG}/sendMessage",
            json={
                "chat_id": TELEGRAM_SUPERVISOR_CHAT_ID,
                "text": f"💬 *{user_name}:* {text}",
                "parse_mode": "Markdown",
                "reply_to_message_id": escalation_msg_id,
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]


