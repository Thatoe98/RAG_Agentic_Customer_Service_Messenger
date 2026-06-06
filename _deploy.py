"""Full server deployment: upload code, build Docker image, start container.

Reads all credentials from the local .env file — never commit secrets directly.
Run once for a fresh deployment; use _redeploy.py for incremental updates.
"""
import os
import secrets
import time

import paramiko
from dotenv import load_dotenv

load_dotenv()

HOST       = os.environ["SERVER_HOST"]
USER       = os.environ["SERVER_USER"]
PASS       = os.environ["SERVER_PASS"]
REMOTE_DIR = os.environ.get("SERVER_DIR", "/docker/messenger-bot")
BOT_DOMAIN = os.environ.get("BOT_DOMAIN", "bot.autom8agency.cloud")

# Admin credentials: use existing values from .env, or generate fresh ones
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(16)
SESSION_SEC = os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32)

# ── Files to upload ───────────────────────────────────────────────────────────
FILES = [
    "main.py", "agent.py", "config.py", "db.py", "rag.py",
    "guidelines.py", "store.py", "messenger.py", "conversations.py",
    "usage_log.py", "requirements.txt",
    "admin/__init__.py", "admin/routes.py", "admin/trainer_agent.py",
    "tools/__init__.py", "tools/handover.py",
    "prompts/system_prompt.txt", "prompts/trainer_prompt.txt",
    "templates/base.html", "templates/login.html", "templates/chat.html",
    "templates/files.html", "templates/_chat_turn.html",
    "templates/conversations.html", "templates/conversation_view.html",
    "templates/analytics.html", "templates/recommendations.html",
    "templates/_recommendations_result.html",
    "templates/_conv_rows.html", "templates/_messages.html",
]

# ── Server .env (written to the remote host) ──────────────────────────────────
ENV = f"""\
# Facebook
FB_PAGE_ACCESS_TOKEN={os.environ["FB_PAGE_ACCESS_TOKEN"]}
FB_VERIFY_TOKEN={os.environ["FB_VERIFY_TOKEN"]}
FB_APP_SECRET={os.environ.get("FB_APP_SECRET", "")}

# Gemini
GEMINI_API_KEY={os.environ["GEMINI_API_KEY"]}

# RAG / knowledge base
EMBEDDING_MODEL={os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")}
EMBEDDING_DIM={os.environ.get("EMBEDDING_DIM", "768")}
DB_PATH=data/knowledge.db

# Admin webapp
ADMIN_PASSWORD={ADMIN_PASS}
SESSION_SECRET={SESSION_SEC}

# Telegram
TELEGRAM_BOT_TOKEN={os.environ["TELEGRAM_BOT_TOKEN"]}
TELEGRAM_SUPERVISOR_CHAT_ID={os.environ["TELEGRAM_SUPERVISOR_CHAT_ID"]}

# Bot behaviour
GREETING_MESSAGE={os.environ.get("GREETING_MESSAGE", "Hi there! Thanks for reaching out. How can I help you today?")}
"""

DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p data
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
"""

COMPOSE = f"""\
services:
  messenger-bot:
    build: .
    restart: always
    labels:
      - traefik.enable=true
      - traefik.http.routers.messenger-bot.rule=Host(`{BOT_DOMAIN}`)
      - traefik.http.routers.messenger-bot.tls=true
      - traefik.http.routers.messenger-bot.entrypoints=web,websecure
      - traefik.http.routers.messenger-bot.tls.certresolver=mytlschallenge
      - traefik.http.services.messenger-bot.loadbalancer.server.port=8000
    env_file:
      - .env
    volumes:
      - bot_data:/app/data
    networks:
      - n8n_default

networks:
  n8n_default:
    external: true

volumes:
  bot_data:
"""

DOCKERIGNORE = """\
.env
__pycache__/
*.pyc
*.pyo
data/
.git/
"""


# ── Connect ───────────────────────────────────────────────────────────────────
print(f"Connecting to {HOST}...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASS, timeout=20)
sftp = client.open_sftp()


def run(cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    rc  = stdout.channel.recv_exit_status()
    combined = (out + err).strip()
    if combined:
        print(f"  {combined[:400]}")
    return rc


def sftp_mkdir(path):
    try:
        sftp.mkdir(path)
    except OSError:
        pass


def sftp_write(remote_path, content: str):
    with sftp.open(remote_path, "w") as f:
        f.write(content)


# ── 1. Directories ────────────────────────────────────────────────────────────
print("\n[1] Creating remote directories...")
for d in [REMOTE_DIR, f"{REMOTE_DIR}/admin", f"{REMOTE_DIR}/tools",
          f"{REMOTE_DIR}/prompts", f"{REMOTE_DIR}/templates", f"{REMOTE_DIR}/data"]:
    sftp_mkdir(d)

# ── 2. Source files ───────────────────────────────────────────────────────────
print("\n[2] Uploading source files...")
for rel in FILES:
    local = rel.replace("/", os.sep)
    if os.path.exists(local):
        sftp_mkdir(f"{REMOTE_DIR}/{os.path.dirname(rel)}")
        sftp.put(local, f"{REMOTE_DIR}/{rel}")
        print(f"  [OK] {rel}")
    else:
        print(f"  [MISSING] {rel}")

# ── 3. Generated files ────────────────────────────────────────────────────────
print("\n[3] Writing Dockerfile, docker-compose.yml, .env, .dockerignore...")
sftp_write(f"{REMOTE_DIR}/Dockerfile",         DOCKERFILE)
sftp_write(f"{REMOTE_DIR}/docker-compose.yml", COMPOSE)
sftp_write(f"{REMOTE_DIR}/.env",               ENV)
sftp_write(f"{REMOTE_DIR}/.dockerignore",      DOCKERIGNORE)
sftp.chmod(f"{REMOTE_DIR}/.env", 0o600)
print("  [OK] all written")

# ── 4. Build ──────────────────────────────────────────────────────────────────
print("\n[4] Building Docker image...")
_, stdout, stderr = client.exec_command(
    f"cd {REMOTE_DIR} && DOCKER_BUILDKIT=0 docker compose build 2>&1 | tail -10",
)
print((stdout.read() + stderr.read()).decode().strip())

# ── 5. Start ──────────────────────────────────────────────────────────────────
print("\n[5] Starting container...")
run(f"cd {REMOTE_DIR} && docker compose up -d")

time.sleep(4)
print("\n[6] Status:")
run("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")

sftp.close()
client.close()

print(f"""
Deploy complete.
  Admin: https://{BOT_DOMAIN}/admin
  ADMIN_PASSWORD: {ADMIN_PASS}
""")
