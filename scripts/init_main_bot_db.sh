#!/bin/bash
# 初始化主Bot记录到数据库
# 用法：./scripts/init_main_bot_db.sh

set -e

echo "=========================================="
echo "初始化主Bot记录到数据库"
echo "=========================================="
echo ""

# 从 .env 文件读取配置
cd /opt/tg-bot

if [ ! -f .env ]; then
    echo "❌ 错误：找不到 .env 文件"
    exit 1
fi

BOT_TOKEN=$(grep "^BOT_TOKEN=" .env | cut -d'=' -f2)
SUPER_ADMIN_ID=$(grep "^SUPER_ADMIN_ID=" .env | cut -d'=' -f2)
DB_USER=$(grep "^DB_USER=" .env | cut -d'=' -f2)
DB_PASSWORD=$(grep "^DB_PASSWORD=" .env | cut -d'=' -f2)

if [ -z "$BOT_TOKEN" ]; then
    echo "❌ 错误：BOT_TOKEN 未配置"
    exit 1
fi

# 从 BOT_TOKEN 提取 bot_id
BOT_TOKEN_PREFIX=$(echo "$BOT_TOKEN" | cut -d':' -f1)
INSTANCE_ID="bot_${BOT_TOKEN_PREFIX}"

echo "📋 配置信息："
echo "  Bot Token Prefix: $BOT_TOKEN_PREFIX"
echo "  Instance ID: $INSTANCE_ID"
echo "  Super Admin ID: $SUPER_ADMIN_ID"
echo "  Database User: $DB_USER"
echo ""

echo "🔧 正在插入/更新主Bot记录..."
echo ""

# 执行 SQL
docker-compose -f docker-compose.prod.yml exec -T postgres psql -U "$DB_USER" -d saas_accounting << EOF
INSERT INTO bot_creations (
    telegram_id,
    bot_token,
    bot_username,
    bot_name,
    instance_id,
    instance_dir,
    db_path,
    env_path,
    status,
    super_admin_id,
    parent_bot_id,
    root_bot_id,
    tree_depth,
    core_version,
    ui_version,
    permission_version,
    created_at,
    started_at,
    stopped_at,
    updated_at,
    config_json,
    config_snapshot
) VALUES (
    ${BOT_TOKEN_PREFIX},
    '${BOT_TOKEN}',
    'main_bot',
    'Main Bot',
    '${INSTANCE_ID}',
    '/app/bot_instances/${INSTANCE_ID}',
    '/app/bot_instances/${INSTANCE_ID}/data.db',
    '/app/bot_instances/${INSTANCE_ID}/.env',
    'running',
    ${SUPER_ADMIN_ID},
    NULL,
    '${INSTANCE_ID}',
    0,
    '1.0.0',
    '1.0.0',
    '1.0.0',
    NOW(),
    NOW(),
    NULL,
    NOW(),
    '{}',
    '{"enable_ai": false, "enable_auto_day_cut": true}'
) ON CONFLICT (instance_id) DO UPDATE SET
    telegram_id = EXCLUDED.telegram_id,
    bot_username = EXCLUDED.bot_username,
    status = EXCLUDED.status,
    super_admin_id = EXCLUDED.super_admin_id,
    updated_at = NOW();
EOF

echo ""
echo "✅ 主Bot记录已成功插入/更新"
echo ""

echo "🔍 验证结果："
docker-compose -f docker-compose.prod.yml exec -T postgres psql -U "$DB_USER" -d saas_accounting -c "
SELECT instance_id, bot_username, super_admin_id, status FROM bot_creations;
"

echo ""
echo "=========================================="
echo "✅ 初始化完成！"
echo "请重启 Bot 容器使更改生效："
echo "  docker-compose -f docker-compose.prod.yml restart bot"
echo "=========================================="
