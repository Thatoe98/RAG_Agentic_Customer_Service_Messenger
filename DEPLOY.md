# Deploying to a Hostinger KVM2 VPS

This guide deploys the bot + admin webapp on a single Ubuntu VPS using
**uvicorn (1 worker) + systemd + nginx + Let's Encrypt**. HTTPS is required
because Facebook and Telegram only call webhooks over TLS.

> **Run a single worker.** Conversation state is in-memory and the SQLite
> knowledge base uses one shared connection. Multiple workers would split state
> and can corrupt writes. One uvicorn worker is plenty for this workload.

---

## 0. Domain name — cost and why it's required

**Why:** Facebook and Telegram only send webhook calls over HTTPS. Let's Encrypt
(the free SSL provider) only issues certificates for real domain names — not bare
IP addresses. So you need a domain to get HTTPS, and you need HTTPS to receive
messages from Facebook and Telegram.

**Cost:** ~$12/year (~$1/month) for a `.com`. Check if you already have one:
- If Cross Culture Education has an existing website domain (e.g. `crosscultureedu.com`),
  you can add a free subdomain like `bot.crosscultureedu.com` — no extra cost.
- If you need to buy one: Hostinger sells domains at [hpanel.hostinger.com](https://hpanel.hostinger.com)
  — often discounted in the first year.

**Recommendation:** use a subdomain of your existing business domain if you have one.
It's free, looks professional, and takes 2 minutes to set up.

---

## 1. Point a domain at the VPS

Create an `A` record (e.g. `bot.yourdomain.com`) → your VPS IP.

## 2. Prepare the server

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip nginx
# Optional firewall
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

## 3. Get the code

```bash
sudo mkdir -p /opt/messenger-bot && sudo chown $USER /opt/messenger-bot
git clone <your-repo-url> /opt/messenger-bot
cd /opt/messenger-bot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 4. Configure environment

```bash
cp .env.example .env
nano .env   # fill in every value; set a strong ADMIN_PASSWORD and a random SESSION_SECRET
```

Generate a session secret:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

The SQLite knowledge base is created automatically at `data/knowledge.db` on
first run. Back this file up to keep your uploaded knowledge.

## 5. systemd service

Create `/etc/systemd/system/messenger-bot.service`:

```ini
[Unit]
Description=Messenger Bot (FastAPI)
After=network.target

[Service]
WorkingDirectory=/opt/messenger-bot
ExecStart=/opt/messenger-bot/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

Make sure the app dir is writable by the service user, then start it:

```bash
sudo chown -R www-data:www-data /opt/messenger-bot
sudo systemctl daemon-reload
sudo systemctl enable --now messenger-bot
sudo systemctl status messenger-bot     # check it's running
journalctl -u messenger-bot -f          # live logs
```

## 6. nginx reverse proxy

Create `/etc/nginx/sites-available/messenger-bot`:

```nginx
server {
    server_name bot.yourdomain.com;

    client_max_body_size 25M;   # allow document uploads

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it and add TLS:

```bash
sudo ln -s /etc/nginx/sites-available/messenger-bot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bot.yourdomain.com   # auto-configures HTTPS + renewal
```

## 7. Register webhooks

**Facebook** (Meta Developer Portal → Messenger → Webhooks):
- Callback URL: `https://bot.yourdomain.com/webhook`
- Verify Token: your `FB_VERIFY_TOKEN`
- Subscribe to: `messages`

**Telegram** (run once):
```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://bot.yourdomain.com/telegram-webhook"
```

## 8. Use it

- Admin webapp: `https://bot.yourdomain.com/admin` → log in with `ADMIN_PASSWORD`.
  - **Knowledge Files** tab: upload university/program/policy docs.
  - **Training Chat** tab: tune tone/strategy; test what the bot can find.
- Message your Facebook Page to test the customer flow end to end.

## Updating after a code change

```bash
cd /opt/messenger-bot
git pull
.venv/bin/pip install -r requirements.txt   # if deps changed
sudo systemctl restart messenger-bot
```

## Backups

```bash
# The knowledge base is one file (plus WAL sidecars):
cp data/knowledge.db ~/knowledge-backup-$(date +%F).db
```
