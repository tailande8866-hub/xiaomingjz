#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/opt/saas-bot"
COMPOSE_FILE="docker-compose.prod.yml"
BACKUP_DIR="backups"
ENV_FILE=".env"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

cd "$PROJECT_DIR"

echo "==> project: $PROJECT_DIR"

if docker-compose -f "$COMPOSE_FILE" ps >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
elif docker compose -f "$COMPOSE_FILE" ps >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
else
  echo "==> error: neither docker-compose nor docker compose can manage $COMPOSE_FILE"
  exit 1
fi
echo "==> compose command: ${COMPOSE_CMD[*]}"

if [ -f "$ENV_FILE" ]; then
  cp "$ENV_FILE" "${ENV_FILE}.backup_${TIMESTAMP}"
  echo "==> env backup: ${ENV_FILE}.backup_${TIMESTAMP}"
fi

mkdir -p "$BACKUP_DIR"

if "${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" ps postgres >/dev/null 2>&1; then
  "${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U admin saas_accounting > "${BACKUP_DIR}/backup_${TIMESTAMP}.sql"
  echo "==> db backup: ${BACKUP_DIR}/backup_${TIMESTAMP}.sql"
else
  echo "==> skip db backup: postgres service not found"
fi

git fetch origin
git pull --ff-only origin main

if [ -f ".env.production" ]; then
  cp .env.production .env
  echo "==> env synced from .env.production"
fi

"${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" up -d --build
"${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" logs --tail=100 bot
