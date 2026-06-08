#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="docker-compose.prod.yml"

cd "$PROJECT_DIR"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root: sudo bash install_server.sh"
  exit 1
fi

echo "[1/6] Installing system packages and Docker Compose v2..."
apt-get update
apt-get install -y ca-certificates curl git gnupg lsb-release openssl

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

systemctl enable docker
systemctl start docker

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is not available after Docker install."
  exit 1
fi

echo "[2/6] Preparing environment file..."
if [ ! -f .env ]; then
  if [ -f .env.production ]; then
    cp .env.production .env
  elif [ -f .env.template ]; then
    cp .env.template .env
  else
    echo "Missing .env.production or .env.template"
    exit 1
  fi
fi

set_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf "\n%s=%s\n" "$key" "$value" >> .env
  fi
}

get_env() {
  grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- || true
}

random_hex() {
  openssl rand -hex "$1"
}

random_fernet_key() {
  python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
}

valid_fernet_key() {
  KEY_TO_CHECK="$1" python3 - <<'PY'
import os
from cryptography.fernet import Fernet
try:
    Fernet(os.environ.get("KEY_TO_CHECK", "").encode())
    raise SystemExit(0)
except Exception:
    raise SystemExit(1)
PY
}

BOT_TOKEN_VALUE="$(get_env BOT_TOKEN)"
SUPER_ADMIN_VALUE="$(get_env SUPER_ADMIN_ID)"
if [ -z "$BOT_TOKEN_VALUE" ] || [ "$BOT_TOKEN_VALUE" = "your_bot_token_here" ]; then
  echo "Please edit .env and set BOT_TOKEN before starting."
  exit 1
fi
if [ -z "$SUPER_ADMIN_VALUE" ] || [ "$SUPER_ADMIN_VALUE" = "your_telegram_user_id" ]; then
  echo "Please edit .env and set SUPER_ADMIN_ID before starting."
  exit 1
fi

[ -n "$(get_env DB_USER)" ] || set_env DB_USER "admin"
[ -n "$(get_env DB_PASSWORD)" ] || set_env DB_PASSWORD "$(random_hex 16)"
[ -n "$(get_env REDIS_PASSWORD)" ] || set_env REDIS_PASSWORD "$(random_hex 16)"
[ -n "$(get_env BOT_TOKEN_ENCRYPTION_KEY)" ] || set_env BOT_TOKEN_ENCRYPTION_KEY "$(random_fernet_key)"
if ! valid_fernet_key "$(get_env BOT_TOKEN_ENCRYPTION_KEY)"; then
  set_env BOT_TOKEN_ENCRYPTION_KEY "$(random_fernet_key)"
fi
[ -n "$(get_env WEB_SECRET_KEY)" ] || set_env WEB_SECRET_KEY "$(random_hex 32)"
set_env IS_MAIN_BOT "true"
set_env INSTANCE_ID "main_bot"

echo "[3/6] Preparing runtime directories..."
mkdir -p logs instances bot_instances backups backups/pg_backup nginx/conf.d nginx/ssl nginx/html

echo "[4/6] Resetting containers if requested..."
if [ "${1:-}" = "--reset" ]; then
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
  rm -rf logs/* instances/* bot_instances/* backups/pg_backup/*
fi

echo "[5/6] Building and starting services..."
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

echo "[6/6] Service status..."
docker compose -f "$COMPOSE_FILE" ps

echo
echo "Install complete."
echo "View logs: cd $PROJECT_DIR && docker compose -f $COMPOSE_FILE logs -f bot"
