"""Meta Marketing API client — mirrors messenger.py style.

Uses Graph API v22.0 (Marketing API) to read ad account insights, list
campaigns, and manage campaign status / daily budgets.

All config vars are optional so the app boots without ads configured.
Check META_ADS_ACCESS_TOKEN and META_AD_ACCOUNT_ID before calling these
functions, or rely on the early-return guards inside each one.

Budgets in the Marketing API are always in *minor* currency units
(e.g. satang for THB, cents for USD). list_campaigns() and get_campaign()
convert them to major units (÷100) for display. set_campaign_budget()
accepts major units and converts back before sending.
"""
import logging

import httpx

from config import META_AD_ACCOUNT_ID, META_ADS_ACCESS_TOKEN

_BASE = "https://graph.facebook.com/v22.0"
_ACT = f"act_{META_AD_ACCOUNT_ID}" if META_AD_ACCOUNT_ID else ""

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _norm_insights(row: dict) -> dict:
    """Normalise an insights row: coerce numeric strings, flatten actions list."""
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _i(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    result = {
        "spend":       _f(row.get("spend", 0)),
        "impressions": _i(row.get("impressions", 0)),
        "clicks":      _i(row.get("clicks", 0)),
        "ctr":         _f(row.get("ctr", 0)),
        "cpc":         _f(row.get("cpc", 0)),
        "reach":       _i(row.get("reach", 0)),
    }
    # Flatten actions list → dict keyed by action_type
    actions: dict[str, int] = {}
    for a in row.get("actions", []):
        try:
            actions[a["action_type"]] = int(a["value"])
        except (KeyError, ValueError, TypeError):
            pass
    result["actions"] = actions
    return result


_INSIGHT_FIELDS = "spend,impressions,clicks,ctr,cpc,reach,actions"
_CAMPAIGN_FIELDS = "id,name,status,effective_status,objective,daily_budget,lifetime_budget"


def _fmt_campaign(c: dict, insights: dict) -> dict:
    """Merge raw campaign dict + normalised insights into a display-ready dict."""
    daily = c.get("daily_budget")
    lifetime = c.get("lifetime_budget")
    return {
        "id":               c["id"],
        "name":             c.get("name", ""),
        "status":           c.get("status", ""),
        "effective_status": c.get("effective_status", ""),
        "objective":        c.get("objective", ""),
        # Convert minor → major currency units
        "daily_budget":    round(int(daily) / 100, 2) if daily else None,
        "lifetime_budget": round(int(lifetime) / 100, 2) if lifetime else None,
        "spend":       insights.get("spend", 0.0),
        "impressions": insights.get("impressions", 0),
        "clicks":      insights.get("clicks", 0),
        "ctr":         insights.get("ctr", 0.0),
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def get_account_insights(date_preset: str = "last_7d") -> dict:
    """Return account-level spend/performance for the given date preset.

    date_preset: "today" | "last_7d" | "last_30d" (and other Marketing API presets)
    Returns an empty dict if not configured or on API error.
    """
    if not (_ACT and META_ADS_ACCESS_TOKEN):
        return {}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_BASE}/{_ACT}/insights",
            params={
                "fields": _INSIGHT_FIELDS,
                "date_preset": date_preset,
                "access_token": META_ADS_ACCESS_TOKEN,
            },
            timeout=20.0,
        )
        if resp.status_code != 200:
            log.warning("Ads account insights fetch failed: %s %s", resp.status_code, resp.text)
            return {}
        data = resp.json().get("data", [])
        return _norm_insights(data[0]) if data else {}


async def list_campaigns(date_preset: str = "last_7d") -> list[dict]:
    """Return all campaigns with merged per-campaign insights.

    Makes one request for the campaign list, then one per campaign for
    insights (sequential to avoid rate limits). Budgets are converted from
    minor to major currency units.
    """
    if not (_ACT and META_ADS_ACCESS_TOKEN):
        return []
    async with httpx.AsyncClient() as client:
        # 1. Fetch campaign list
        resp = await client.get(
            f"{_BASE}/{_ACT}/campaigns",
            params={
                "fields": _CAMPAIGN_FIELDS,
                "access_token": META_ADS_ACCESS_TOKEN,
                "limit": 50,
            },
            timeout=20.0,
        )
        if resp.status_code != 200:
            log.warning("Ads campaigns list failed: %s %s", resp.status_code, resp.text)
            return []

        campaigns = resp.json().get("data", [])
        result = []

        # 2. Fetch per-campaign insights and merge
        for c in campaigns:
            insights: dict = {}
            try:
                ir = await client.get(
                    f"{_BASE}/{c['id']}/insights",
                    params={
                        "fields": "spend,impressions,clicks,ctr",
                        "date_preset": date_preset,
                        "access_token": META_ADS_ACCESS_TOKEN,
                    },
                    timeout=15.0,
                )
                if ir.status_code == 200:
                    idata = ir.json().get("data", [])
                    if idata:
                        insights = _norm_insights(idata[0])
            except Exception:
                log.warning("Could not fetch insights for campaign %s", c.get("id"))

            result.append(_fmt_campaign(c, insights))
        return result


async def get_campaign(campaign_id: str, date_preset: str = "last_7d") -> dict | None:
    """Fetch a single campaign with insights (used to re-render a row after mutations)."""
    if not META_ADS_ACCESS_TOKEN:
        return None
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_BASE}/{campaign_id}",
            params={
                "fields": _CAMPAIGN_FIELDS,
                "access_token": META_ADS_ACCESS_TOKEN,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            log.warning("Campaign fetch failed for %s: %s %s", campaign_id, resp.status_code, resp.text)
            return None
        c = resp.json()

        insights: dict = {}
        try:
            ir = await client.get(
                f"{_BASE}/{campaign_id}/insights",
                params={
                    "fields": "spend,impressions,clicks,ctr",
                    "date_preset": date_preset,
                    "access_token": META_ADS_ACCESS_TOKEN,
                },
                timeout=15.0,
            )
            if ir.status_code == 200:
                idata = ir.json().get("data", [])
                if idata:
                    insights = _norm_insights(idata[0])
        except Exception:
            pass

        return _fmt_campaign(c, insights)


async def set_campaign_status(campaign_id: str, status: str) -> bool:
    """Pause or resume a campaign. status must be "ACTIVE" or "PAUSED".

    Returns True if Meta confirmed success, False otherwise.
    Raises httpx.HTTPStatusError on 4xx/5xx.
    """
    if status not in {"ACTIVE", "PAUSED"}:
        raise ValueError(f"Invalid status: {status!r} — must be 'ACTIVE' or 'PAUSED'")
    if not META_ADS_ACCESS_TOKEN:
        return False
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_BASE}/{campaign_id}",
            params={"access_token": META_ADS_ACCESS_TOKEN},
            json={"status": status},
            timeout=15.0,
        )
        resp.raise_for_status()
        return bool(resp.json().get("success", False))


async def set_campaign_budget(campaign_id: str, daily_budget_major: float) -> bool:
    """Update a campaign's daily budget.

    daily_budget_major is in major currency units (e.g. 500 for 500 THB).
    The API requires minor units (satang/cents), so we multiply by 100.

    Raises ValueError for non-positive amounts.
    Raises httpx.HTTPStatusError on 4xx/5xx.
    """
    if daily_budget_major <= 0:
        raise ValueError("Budget must be a positive number")
    minor = int(round(daily_budget_major * 100))
    if not META_ADS_ACCESS_TOKEN:
        return False
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_BASE}/{campaign_id}",
            params={"access_token": META_ADS_ACCESS_TOKEN},
            json={"daily_budget": minor},
            timeout=15.0,
        )
        resp.raise_for_status()
        return bool(resp.json().get("success", False))
