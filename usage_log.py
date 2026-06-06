"""Token usage logging and stats for the admin analytics page."""
from db import get_conn, write_lock

# Gemini 2.0 Flash pricing (USD per 1M tokens)
_INPUT_COST_PER_M  = 0.075
_OUTPUT_COST_PER_M = 0.30


def log(source: str, model: str, input_tokens: int, output_tokens: int, psid: str | None = None):
    with write_lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO token_usage (source, psid, model, input_tokens, output_tokens, total_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source, psid, model, input_tokens, output_tokens, input_tokens + output_tokens),
        )
        conn.commit()


def log_response(response, source: str, model: str, psid: str | None = None):
    """Extract usage_metadata from a Gemini response and log it."""
    try:
        meta = response.usage_metadata
        log(
            source=source,
            model=model,
            input_tokens=meta.prompt_token_count or 0,
            output_tokens=meta.candidates_token_count or 0,
            psid=psid,
        )
    except Exception:
        pass  # never let logging break the main flow


def get_stats() -> dict:
    conn = get_conn()

    def q(sql, *args):
        row = conn.execute(sql, args).fetchone()
        return dict(row) if row else {}

    def ql(sql, *args):
        return [dict(r) for r in conn.execute(sql, args).fetchall()]

    today = q("""
        SELECT COALESCE(SUM(input_tokens),0)  AS input,
               COALESCE(SUM(output_tokens),0) AS output,
               COALESCE(SUM(total_tokens),0)  AS total,
               COUNT(*) AS calls
        FROM token_usage WHERE ts >= datetime('now', '-1 day')
    """)
    week = q("""
        SELECT COALESCE(SUM(input_tokens),0)  AS input,
               COALESCE(SUM(output_tokens),0) AS output,
               COALESCE(SUM(total_tokens),0)  AS total,
               COUNT(*) AS calls
        FROM token_usage WHERE ts >= datetime('now', '-7 days')
    """)
    by_source = ql("""
        SELECT source,
               SUM(input_tokens)  AS input,
               SUM(output_tokens) AS output,
               SUM(total_tokens)  AS total,
               COUNT(*)           AS calls
        FROM token_usage WHERE ts >= datetime('now', '-7 days')
        GROUP BY source ORDER BY total DESC
    """)
    daily = ql("""
        SELECT DATE(ts) AS day,
               SUM(input_tokens)  AS input,
               SUM(output_tokens) AS output,
               SUM(total_tokens)  AS total
        FROM token_usage
        WHERE ts >= datetime('now', '-7 days')
        GROUP BY DATE(ts) ORDER BY day
    """)

    def cost(inp, out):
        return round(inp / 1_000_000 * _INPUT_COST_PER_M + out / 1_000_000 * _OUTPUT_COST_PER_M, 4)

    return {
        "today":     {**today,     "cost": cost(today.get("input", 0),  today.get("output", 0))},
        "week":      {**week,      "cost": cost(week.get("input", 0),   week.get("output", 0))},
        "by_source": [{**r, "cost": cost(r["input"], r["output"])} for r in by_source],
        "daily":     daily,
    }
