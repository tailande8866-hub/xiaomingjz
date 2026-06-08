#!/bin/bash
# 修复服务器 .env 文件中的加密密钥

cd /opt/saas-bot

# 检查当前密钥
CURRENT_KEY=$(grep BOT_TOKEN_ENCRYPTION_KEY .env | cut -d= -f2)
echo "当前密钥: $CURRENT_KEY"

# 替换为正确的密钥
NEW_KEY=$(python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)
sed -i "s/BOT_TOKEN_ENCRYPTION_KEY=.*/BOT_TOKEN_ENCRYPTION_KEY=${NEW_KEY}/" .env

# 验证
NEW_KEY=$(grep BOT_TOKEN_ENCRYPTION_KEY .env | cut -d= -f2)
echo "新密钥: $NEW_KEY"

# 重启服务
docker-compose restart bot

echo "✅ 密钥已更新，服务已重启"
