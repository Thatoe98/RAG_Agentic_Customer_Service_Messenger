"""Admin-trained behavior guidelines + customer system-prompt composition.

Guidelines are short natural-language rules the business owner adds via the
trainer chat (e.g. "always mention the free consultation"). They are appended
to the base persona prompt so the customer bot's behavior can be tuned without
a redeploy.
"""
import time
from pathlib import Path

from db import get_conn, write_lock

_BASE_PROMPT = Path("prompts/system_prompt.txt").read_text(encoding="utf-8")


def list_guidelines() -> list[dict]:
    rows = get_conn().execute(
        "SELECT id, text, created_at, updated_at FROM guidelines ORDER BY created_at"
    ).fetchall()
    return [dict(r) for r in rows]


def add_guideline(text: str) -> int:
    now = time.time()
    conn = get_conn()
    with write_lock:
        cur = conn.execute(
            "INSERT INTO guidelines (text, created_at, updated_at) VALUES (?, ?, ?)",
            (text.strip(), now, now),
        )
        conn.commit()
    return cur.lastrowid


def update_guideline(guideline_id: int, text: str) -> bool:
    conn = get_conn()
    with write_lock:
        cur = conn.execute(
            "UPDATE guidelines SET text = ?, updated_at = ? WHERE id = ?",
            (text.strip(), time.time(), guideline_id),
        )
        conn.commit()
    return cur.rowcount > 0


def delete_guideline(guideline_id: int) -> bool:
    conn = get_conn()
    with write_lock:
        cur = conn.execute("DELETE FROM guidelines WHERE id = ?", (guideline_id,))
        conn.commit()
    return cur.rowcount > 0


def compose_system_prompt() -> str:
    """Base persona + the current learned guidelines block."""
    guidelines = list_guidelines()
    if not guidelines:
        return _BASE_PROMPT
    lines = "\n".join(f"- {g['text']}" for g in guidelines)
    return (
        f"{_BASE_PROMPT}\n\n"
        "## Learned Guidelines\n"
        "Additional instructions from the business owner. Follow these closely; "
        "if any conflict with the rules above, the rules above win.\n"
        f"{lines}\n"
    )
