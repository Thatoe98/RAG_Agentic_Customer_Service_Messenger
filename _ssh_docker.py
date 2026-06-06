"""Check Docker container status and recent bot logs on the production server."""
import os

import paramiko
from dotenv import load_dotenv

load_dotenv()

HOST       = os.environ["SERVER_HOST"]
USER       = os.environ["SERVER_USER"]
PASS       = os.environ["SERVER_PASS"]
REMOTE_DIR = os.environ.get("SERVER_DIR", "/docker/messenger-bot")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=15)


def run(cmd):
    _, stdout, stderr = client.exec_command(cmd)
    return (stdout.read() + stderr.read()).decode().strip()


checks = {
    "containers":    "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'",
    "networks":      "docker network ls",
    "bot logs":      f"cd {REMOTE_DIR} && docker compose logs --tail 20 2>&1",
}

for label, cmd in checks.items():
    print(f"\n[{label}]")
    print(run(cmd))

client.close()
