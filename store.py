import time
from dataclasses import dataclass, field
from typing import Optional
import threading

@dataclass
class Conversation:
    messages: list = field(default_factory=list)
    escalated: bool = False
    escalation_msg_id: Optional[int] = None
    greeted: bool = False
    admin_silenced_at: Optional[float] = None

_store: dict[str, Conversation] = {}
_lock = threading.Lock()
_telegram_to_psid: dict[int, str] = {}
_bot_sent_mids: dict[str, float] = {}
_mids_lock = threading.Lock()


def get_or_create(psid: str) -> Conversation:
    with _lock:
        if psid not in _store:
            _store[psid] = Conversation()
        return _store[psid]


def add_message(psid: str, role: str, content: str):
    conv = get_or_create(psid)
    with _lock:
        conv.messages.append({"role": role, "content": content})


def get_messages(psid: str) -> list:
    return list(get_or_create(psid).messages)


def is_escalated(psid: str) -> bool:
    return get_or_create(psid).escalated


def set_escalated(psid: str, telegram_msg_id: int):
    conv = get_or_create(psid)
    with _lock:
        conv.escalated = True
        conv.escalation_msg_id = telegram_msg_id
        _telegram_to_psid[telegram_msg_id] = psid


def reset_escalation(psid: str):
    conv = get_or_create(psid)
    with _lock:
        if conv.escalation_msg_id and conv.escalation_msg_id in _telegram_to_psid:
            del _telegram_to_psid[conv.escalation_msg_id]
        conv.escalated = False
        conv.escalation_msg_id = None


def register_telegram_msg(psid: str, msg_id: int):
    """Register any Telegram message ID to psid so thread-replies always resolve."""
    with _lock:
        _telegram_to_psid[msg_id] = psid


def psid_from_telegram_msg(telegram_msg_id: int) -> Optional[str]:
    return _telegram_to_psid.get(telegram_msg_id)


def clear_messages(psid: str):
    conv = get_or_create(psid)
    with _lock:
        conv.messages = []


def mark_greeted(psid: str):
    get_or_create(psid).greeted = True


def is_greeted(psid: str) -> bool:
    return get_or_create(psid).greeted


# ── Admin inbox takeover ─────────────────────────────────────────────────────

def register_bot_mid(mid: str):
    """Track a message ID sent by the bot so inbox echoes can be distinguished."""
    with _mids_lock:
        _bot_sent_mids[mid] = time.time()
        cutoff = time.time() - 300
        stale = [k for k, v in _bot_sent_mids.items() if v < cutoff]
        for k in stale:
            del _bot_sent_mids[k]


def is_bot_mid(mid: str) -> bool:
    return mid in _bot_sent_mids


def set_admin_silenced(psid: str):
    conv = get_or_create(psid)
    with _lock:
        conv.admin_silenced_at = time.time()


def is_admin_silenced(psid: str, timeout: float) -> bool:
    conv = get_or_create(psid)
    if conv.admin_silenced_at is None:
        return False
    if time.time() - conv.admin_silenced_at > timeout:
        with _lock:
            conv.admin_silenced_at = None
        return False
    return True


def refresh_admin_silence(psid: str):
    """Update the silence timestamp so the timeout resets on each admin message."""
    conv = get_or_create(psid)
    with _lock:
        if conv.admin_silenced_at is not None:
            conv.admin_silenced_at = time.time()


def clear_admin_silence(psid: str):
    """Clear inbox-takeover silence so the bot resumes immediately."""
    conv = get_or_create(psid)
    with _lock:
        conv.admin_silenced_at = None
