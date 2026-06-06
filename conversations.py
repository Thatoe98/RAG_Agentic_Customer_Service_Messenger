"""Persistent user profiles and message history for the admin dashboard."""
from datetime import datetime, timezone

from db import get_conn, write_lock


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ── User profile ──────────────────────────────────────────────────────────────

def upsert_user(psid: str, first_name: str = "", last_name: str = "", profile_pic: str = ""):
    """Create or update a user's profile. Called once on first contact."""
    name = f"{first_name} {last_name}".strip() or psid
    now = _now()
    with write_lock:
        conn = get_conn()
        conn.execute("""
            INSERT INTO users (psid, name, first_name, last_name, profile_pic, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(psid) DO UPDATE SET
                name        = excluded.name,
                first_name  = excluded.first_name,
                last_name   = excluded.last_name,
                profile_pic = excluded.profile_pic,
                last_seen   = excluded.last_seen
        """, (psid, name, first_name, last_name, profile_pic, now, now))
        conn.commit()


def touch_user(psid: str):
    """Update last_seen for a returning user without fetching their profile again."""
    now = _now()
    with write_lock:
        conn = get_conn()
        conn.execute("""
            INSERT INTO users (psid, name, first_seen, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(psid) DO UPDATE SET last_seen = excluded.last_seen
        """, (psid, psid, now, now))
        conn.commit()


def get_user(psid: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM users WHERE psid = ?", (psid,)).fetchone()
    return dict(row) if row else None


def list_users(limit: int = 200) -> list[dict]:
    """All users ordered by last_seen desc, with last message preview."""
    rows = get_conn().execute("""
        SELECT u.psid, u.name, u.first_name, u.profile_pic,
               u.first_seen, u.last_seen, u.bot_enabled,
               (SELECT content FROM messages WHERE psid = u.psid ORDER BY ts DESC LIMIT 1) AS last_message,
               (SELECT role    FROM messages WHERE psid = u.psid ORDER BY ts DESC LIMIT 1) AS last_role,
               (SELECT COUNT(*) FROM messages WHERE psid = u.psid) AS message_count
        FROM users u
        ORDER BY u.last_seen DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ── Bot on/off toggle ─────────────────────────────────────────────────────────

def get_bot_enabled(psid: str) -> bool:
    row = get_conn().execute(
        "SELECT bot_enabled FROM users WHERE psid = ?", (psid,)
    ).fetchone()
    return bool(row["bot_enabled"]) if row else True


def set_bot_enabled(psid: str, enabled: bool):
    now = _now()
    with write_lock:
        conn = get_conn()
        conn.execute("""
            INSERT INTO users (psid, name, first_seen, last_seen, bot_enabled)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(psid) DO UPDATE SET bot_enabled = excluded.bot_enabled
        """, (psid, psid, now, now, int(enabled)))
        conn.commit()


# ── Message history ───────────────────────────────────────────────────────────

def persist_message(psid: str, role: str, content: str):
    with write_lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO messages (psid, role, content, ts) VALUES (?, ?, ?, ?)",
            (psid, role, content, _now()),
        )
        conn.commit()


def get_messages(psid: str) -> list[dict]:
    rows = get_conn().execute(
        "SELECT id, role, content, ts FROM messages WHERE psid = ? ORDER BY ts ASC",
        (psid,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_analytics() -> dict:
    conn = get_conn()

    total_users    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    user_messages  = conn.execute("SELECT COUNT(*) FROM messages WHERE role = 'user'").fetchone()[0]
    bot_messages   = conn.execute("SELECT COUNT(*) FROM messages WHERE role = 'assistant'").fetchone()[0]

    active_today = conn.execute(
        "SELECT COUNT(DISTINCT psid) FROM messages WHERE ts >= datetime('now', '-1 day')"
    ).fetchone()[0]
    active_week = conn.execute(
        "SELECT COUNT(DISTINCT psid) FROM messages WHERE ts >= datetime('now', '-7 days')"
    ).fetchone()[0]

    bot_off_count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE bot_enabled = 0"
    ).fetchone()[0]

    escalated_count = conn.execute(
        "SELECT COUNT(DISTINCT psid) FROM messages "
        "WHERE role = 'assistant' AND content LIKE '[Supervisor]%'"
    ).fetchone()[0]

    daily_rows = conn.execute("""
        SELECT DATE(ts) AS day, COUNT(*) AS cnt
        FROM messages
        WHERE ts >= datetime('now', '-7 days')
        GROUP BY DATE(ts)
        ORDER BY day
    """).fetchall()
    daily_messages = [{"day": r["day"], "count": r["cnt"]} for r in daily_rows]

    recent_rows = conn.execute(
        "SELECT content FROM messages WHERE role = 'user' ORDER BY ts DESC LIMIT 50"
    ).fetchall()
    recent_user_messages = [r["content"] for r in recent_rows]

    return {
        "total_users": total_users,
        "total_messages": total_messages,
        "user_messages": user_messages,
        "bot_messages": bot_messages,
        "active_today": active_today,
        "active_week": active_week,
        "bot_off_count": bot_off_count,
        "escalated_count": escalated_count,
        "daily_messages": daily_messages,
        "recent_user_messages": recent_user_messages,
    }
