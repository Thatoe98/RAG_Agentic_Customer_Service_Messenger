"""Incremental redeploy: upload changed files, rebuild image, restart container.

Edit FILES to the list of files you changed since the last deploy, then run:
    python _redeploy.py
"""
import os
import time

import paramiko
from dotenv import load_dotenv

load_dotenv()

HOST       = os.environ["SERVER_HOST"]
USER       = os.environ["SERVER_USER"]
PASS       = os.environ["SERVER_PASS"]
REMOTE_DIR = os.environ.get("SERVER_DIR", "/docker/messenger-bot")

# ── Edit this list before running ─────────────────────────────────────────────
FILES = [
    "main.py",
    "agent.py",
    "admin/routes.py",
    "admin/trainer_agent.py",
    "tools/handover.py",
    "prompts/system_prompt.txt",
    "db.py",
    "usage_log.py",
    "conversations.py",
    "config.py",
    "ads.py",
    "templates/base.html",
    "templates/analytics.html",
    "templates/conversations.html",
    "templates/conversation_view.html",
    "templates/recommendations.html",
    "templates/_recommendations_result.html",
    "templates/_conv_rows.html",
    "templates/_messages.html",
    "templates/chat.html",
    "templates/_guidelines.html",
    "templates/_guideline_edit.html",
    "templates/ads.html",
    "templates/_ads_campaign_row.html",
    "templates/_ads_reco_result.html",
]
# ──────────────────────────────────────────────────────────────────────────────

print(f"Connecting to {HOST}...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=20)
sftp = client.open_sftp()


def run(cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = (stdout.read() + stderr.read()).decode().strip()
    if out:
        print(out)


print("\n[1] Uploading files...")
for rel in FILES:
    local = rel.replace("/", os.sep)
    if os.path.exists(local):
        sftp.put(local, f"{REMOTE_DIR}/{rel}")
        print(f"  [OK] {rel}")
    else:
        print(f"  [SKIP] {rel} not found locally")

sftp.close()

print("\n[2] Rebuilding image...")
_, stdout, stderr = client.exec_command(
    f"cd {REMOTE_DIR} && docker compose build 2>&1 | tail -5"
)
print((stdout.read() + stderr.read()).decode().strip())

print("\n[3] Restarting container...")
run(f"cd {REMOTE_DIR} && docker compose up -d 2>&1")

time.sleep(5)
print("\n[4] Startup logs:")
run(f"cd {REMOTE_DIR} && docker compose logs --tail 8 2>&1")

client.close()
