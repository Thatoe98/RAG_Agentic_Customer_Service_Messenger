# Meta Ads — Setup Instructions

Follow these steps to connect your Facebook/Instagram ad account to the `/admin/ads` dashboard.
No coding required — this is all done in browser tabs.

---

## Step 1 — Find your Ad Account ID

1. Open [Meta Ads Manager](https://adsmanager.facebook.com).
2. In the top-left corner, click the account dropdown.
3. Your **Ad Account ID** is the number shown there (e.g. `1234567890`).
   - It may also appear in the URL: `adsmanager.facebook.com/...?act=1234567890`
4. Copy it — you will paste it into `.env` as `META_AD_ACCOUNT_ID`.

> **Important:** enter only the number. Do NOT include the `act_` prefix — the code adds that automatically.

---

## Step 2 — Add Marketing API to your existing Meta App

You already have a Meta Developer App (the one that gives you `FB_PAGE_ACCESS_TOKEN`).
You need to add the **Marketing API** product to it.

1. Go to [Meta for Developers](https://developers.facebook.com/apps/).
2. Click your app → **Add Product** → find **Marketing API** → click **Set Up**.
3. That's it. The product is now available.

---

## Step 3 — Get a token with ads permissions

You have two options. **Option B is recommended** — it gives you a token that never expires and survives server restarts.

### Option A — Quick test (expires in ~1–2 hours)

1. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select your app in the top-right dropdown.
3. Click **Add a Permission** → add `ads_read` and `ads_management`.
4. Click **Generate Access Token** → copy the token.
5. Paste it into `.env` as `META_ADS_ACCESS_TOKEN`.

This is fine for testing locally. It will stop working after a couple of hours.

### Option B — Never-expiring System User token (recommended for production)

1. Go to [Meta Business Suite](https://business.facebook.com) → **Settings** (gear icon, bottom-left).
2. Under **Users**, click **System Users** → **Add**.
3. Give it a name (e.g. `BotAdsUser`), role **Admin** or **Employee** is fine.
4. Once created, click **Add Assets** → **Ad Accounts** → select your ad account → give it **Full Control**.
5. Click **Generate New Token**:
   - Select your app.
   - Check **`ads_read`** and **`ads_management`**.
   - Set expiry to **Never**.
6. Copy the token → paste into `.env` as `META_ADS_ACCESS_TOKEN`.

---

## Step 4 — Do I need to submit my app for review?

**No — not for your own ad accounts.**

Marketing API **Standard Access** (the default when you add the product) is enough to manage
ad accounts that belong to your Business. App Review is only required to manage *other people's*
ad accounts at scale. Since this is your own business, you are good to go.

---

## Step 5 — Update your `.env` file

Add these two lines to your `.env` (local and on the server):

```
# Meta Ads
META_AD_ACCOUNT_ID=1234567890
META_ADS_ACCESS_TOKEN=your_system_user_token_goes_here
```

---

## Step 6 — Test locally

```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000/admin/ads](http://localhost:8000/admin/ads) and log in.

You should see:
- Account-level spend / impressions / clicks / CTR / reach cards (last 7 days).
- A table of your campaigns with per-campaign performance.
- Pause/Resume buttons and inline budget editors for each campaign.
- A "Get AI Recommendations" button powered by Gemini.

If you see the amber "not configured" banner, double-check that both env vars are set and the
server was restarted after editing `.env`.

---

## Step 7 — Deploy to the server

The new files are already in `_redeploy.py`'s `FILES` list. Before deploying:

1. SSH into the server (via Hostinger hPanel) and add the two env vars to `/docker/messenger-bot/.env`:
   ```
   META_AD_ACCOUNT_ID=1234567890
   META_ADS_ACCESS_TOKEN=your_system_user_token_goes_here
   ```
2. From your local machine, run:
   ```bash
   python _redeploy.py
   ```
3. Open `https://bot.autom8agency.cloud/admin/ads` and verify.

---

## Optional bonus — Conversational ads management in Claude Desktop

Meta released an **official Ads MCP** (April 2026) at `mcp.facebook.com/ads`. It exposes 29
Marketing API tools directly to AI clients (Claude Desktop, Claude.ai, Cursor, etc.).

To set it up in Claude Desktop (takes ~5 minutes, no code):
1. Open Claude Desktop → Settings → MCP Servers → Add Server.
2. Enter URL: `mcp.facebook.com/ads`
3. Click **Connect** → a Meta OAuth login screen appears → log in with your Business account.
4. Done. You can now ask Claude things like:
   - *"Show me my ad spend this week"*
   - *"Pause all campaigns under 1% CTR"*
   - *"Which campaign has the highest CPC?"*

This is completely independent of the `/admin/ads` dashboard built here — they talk to the same
ad account but through different surfaces.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "not configured" banner in /admin/ads | Env vars missing or server not restarted | Add both vars to `.env`, restart uvicorn |
| API error on the dashboard | Token expired or missing permissions | Re-generate token with `ads_read` + `ads_management` |
| Campaigns show 0 spend/clicks | No spend in the selected period | Switch to a longer period (30 days) in the period selector |
| Pause/Resume button shows an error | Token lacks `ads_management` | Regenerate token and ensure that permission is checked |
| Budget update fails | Campaign uses lifetime budget (not daily) | Lifetime-budget campaigns show "Lifetime" — budget editing is disabled for them |
