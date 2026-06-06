"""Force a clean rebuild and restart of the bot container on the production server.

Use this when you need a full no-cache rebuild (e.g. dependency changes).
For code-only changes, _redeploy.py is faster.
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

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=20)


def run(cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = (stdout.read() + stderr.read()).decode().strip()
    if out:
        print(out)


print("[1] Building image (no cache)...")
_, stdout, stderr = client.exec_command(
    f"cd {REMOTE_DIR} && DOCKER_BUILDKIT=0 docker compose build --no-cache 2>&1 | tail -15"
)
print((stdout.read() + stderr.read()).decode().strip())

print("\n[2] Starting container...")
run(f"cd {REMOTE_DIR} && docker compose up -d 2>&1")

time.sleep(5)

print("\n[3] Status:")
run("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")

print("\n[4] Logs:")
run(f"cd {REMOTE_DIR} && docker compose logs --tail 20 2>&1")

client.close()
