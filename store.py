from dataclasses import dataclass, field
from typing import Optional
import threading

@dataclass
class Conversation:
    messages: list = field(default_factory=list)
    escalated: bool = False
    escalation_msg_id: Optional[int] = None
    drive_cache: dict = field(default_factory=dict)

_store: dict[str, Conversation] = {}
_lock = threading.Lock()
_telegram_to_psid: dict[int, str] = {}


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


def get_drive_cache(psid: str, query: str) -> Optional[str]:
    return get_or_create(psid).drive_cache.get(query)


def set_drive_cache(psid: str, query: str, result: str):
    conv = get_or_create(psid)
    with _lock:
        conv.drive_cache[query] = result
