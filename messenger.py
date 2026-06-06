import httpx
import store
from config import FB_PAGE_ACCESS_TOKEN

_BASE = "https://graph.facebook.com/v19.0"


async def send_message(recipient_psid: str, text: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_BASE}/me/messages",
            params={"access_token": FB_PAGE_ACCESS_TOKEN},
            json={
                "recipient": {"id": recipient_psid},
                "message": {"text": text},
                "messaging_type": "RESPONSE",
            },
        )
        resp.raise_for_status()
        mid = resp.json().get("message_id", "")
        if mid:
            store.register_bot_mid(mid)


async def send_typing(recipient_psid: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{_BASE}/me/messages",
            params={"access_token": FB_PAGE_ACCESS_TOKEN},
            json={
                "recipient": {"id": recipient_psid},
                "sender_action": "typing_on",
            },
        )


async def get_user_profile(psid: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_BASE}/{psid}",
            params={
                "fields": "first_name,last_name,profile_pic",
                "access_token": FB_PAGE_ACCESS_TOKEN,
            },
        )
        if resp.status_code == 200:
            return resp.json()
    return {}
