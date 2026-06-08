# Server Deploy

Fresh server recommended: Ubuntu 22.04 LTS or Ubuntu 24.04 LTS.

## Fresh Install

Run this on a newly installed server:

```bash
apt-get update && apt-get install -y git && cd /opt && rm -rf saas-bot && git clone -b stable-audit-backup https://github.com/tailande8866-hub/xiaomingjizhang.git saas-bot && cd /opt/saas-bot && bash install_server.sh --reset
```

The script installs Docker Compose v2, creates `.env` from `.env.production` when missing, generates missing local secrets, creates runtime directories, builds the image, and starts the services.

## Update Existing Server

```bash
cd /opt/saas-bot && bash update_server.sh
```

## Logs

```bash
cd /opt/saas-bot && docker compose -f docker-compose.prod.yml logs -f bot
```

## Service Status

```bash
cd /opt/saas-bot && docker compose -f docker-compose.prod.yml ps
```

## Reset All Runtime Data

This deletes database volumes and bot runtime directories.

```bash
cd /opt/saas-bot && bash install_server.sh --reset
```

## Notes

- Use `docker compose`, not old `docker-compose`.
- `.env` is generated locally and is not committed.
- `install_server.sh` keeps `BOT_TOKEN` and `SUPER_ADMIN_ID` from `.env.production` if `.env` does not exist.
- Missing `DB_PASSWORD`, `REDIS_PASSWORD`, `BOT_TOKEN_ENCRYPTION_KEY`, and `WEB_SECRET_KEY` are generated automatically.
