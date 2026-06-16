import logging

import httpx
import store
from config import FB_PAGE_ACCESS_TOKEN

_BASE = "https://graph.facebook.com/v19.0"

log = logging.getLogger(__name__)


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
    """Fetch a user's name via the Conversations API participants list.

    The old /{psid}?fields=first_name,... endpoint returns error 100/33 for
    page tokens since it was deprecated. The Conversations API still returns
    the user's display name in the participants list.
    Profile pictures are no longer available via the standard Graph API.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_BASE}/me/conversations",
            params={
                "user_id": psid,
                "fields": "participants",
                "access_token": FB_PAGE_ACCESS_TOKEN,
            },
        )
        data = resp.json()
        if resp.status_code != 200:
            log.warning("FB conversations fetch failed for %s: %s %s", psid, resp.status_code, data)
            return {}

        for convo in data.get("data", []):
            for participant in convo.get("participants", {}).get("data", []):
                if participant.get("id") == psid:
                    name = participant.get("name", "")
                    parts = name.split(" ", 1)
                    return {
                        "first_name": parts[0],
                        "last_name": parts[1] if len(parts) > 1 else "",
                        "profile_pic": "",
                    }

        log.warning("PSID %s not found in conversations participants", psid)
        return {}
