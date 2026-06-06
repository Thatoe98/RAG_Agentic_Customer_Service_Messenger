"""Print the docker-compose.yml files on the production server."""
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


print("[bot docker-compose.yml]")
print(run(f"cat {REMOTE_DIR}/docker-compose.yml"))

print("\n[/docker directory]")
print(run("ls -la /docker/"))

client.close()
