"""Explore the production server environment (OS, ports, nginx, disk, RAM)."""
import os

import paramiko
from dotenv import load_dotenv

load_dotenv()

HOST = os.environ["SERVER_HOST"]
USER = os.environ["SERVER_USER"]
PASS = os.environ["SERVER_PASS"]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=15)


def run(cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    return out or err


checks = {
    "OS":              "lsb_release -ds 2>/dev/null || cat /etc/os-release | grep PRETTY | cut -d= -f2",
    "docker version":  "docker --version",
    "disk":            "df -h / | tail -1",
    "RAM":             "free -h | grep Mem",
    "ports":           "ss -tlnp | grep LISTEN | head -15",
    "docker files":    "find /docker -name 'docker-compose.y*' 2>/dev/null",
    "domain DNS":      f"dig +short {os.environ.get('BOT_DOMAIN', '')} @8.8.8.8",
}

for label, cmd in checks.items():
    print(f"\n[{label}]")
    print(run(cmd))

client.close()
