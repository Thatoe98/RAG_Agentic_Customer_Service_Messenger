import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_SUPERVISOR_CHAT_ID

_TG = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _md(text: str) -> str:
    """Escape Telegram Markdown v1 special characters in dynamic content."""
    for ch in ["_", "*", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


_TG_LIMIT = 4096

def _display_name(user_name: str, psid: str) -> str:
    """Return a friendly name — fall back to 'Customer' if only a PSID is available."""
    if user_name and user_name != psid and not user_name.isdigit():
        return user_name
    return "Customer"


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
    name = _display_name(user_name, psid)
    header = (
        f"🔔 *{_md(name)}* human နဲ့ ပြောချင်တယ်\n"
        f"📌 {_md(reason)}\n\n"
        f"💬 *Conversation:*\n"
    )
    footer = (
        "\n─────────────────────\n"
        "↩ Reply လုပ်ပြီး customer ဆီ message ပို့နိုင်တယ်\n"
        "/done ရိုက်ရင် bot ပြန်ယူမယ်"
    )
    # Fit summary within Telegram's 4096-char limit
    max_summary = _TG_LIMIT - len(header) - len(footer) - 50
    trimmed = summary if len(summary) <= max_summary else summary[-max_summary:].lstrip()
    text = header + _md(trimmed) + footer

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
        name = _display_name(user_name, user_name)
        resp = await client.post(
            f"{_TG}/sendMessage",
            json={
                "chat_id": TELEGRAM_SUPERVISOR_CHAT_ID,
                "text": f"👤 *{_md(name)}:* {_md(text)}",
                "parse_mode": "Markdown",
                "reply_to_message_id": escalation_msg_id,
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]


