#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${1:-stable-audit-backup}"
COMPOSE_FILE="docker-compose.prod.yml"

cd "$PROJECT_DIR"

git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"

if [ ! -f .env ] && [ -f .env.production ]; then
  cp .env.production .env
fi

mkdir -p logs instances bot_instances backups backups/pg_backup

docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans
docker compose -f "$COMPOSE_FILE" ps

echo
echo "Update complete."
echo "View logs: cd $PROJECT_DIR && docker compose -f $COMPOSE_FILE logs -f bot"
