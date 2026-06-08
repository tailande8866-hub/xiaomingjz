#!/bin/bash

# ========================================
# SaaS记账机器人 - 交互式配置向导
# ========================================

set -e

echo ""
echo "=========================================="
echo "  🚀 SaaS记账机器人 - 配置向导"
echo "=========================================="
echo ""

# 检查是否在正确目录
if [ ! -f ".env.prod.example" ]; then
    echo "❌ 错误: 请在项目根目录运行此脚本"
    exit 1
fi

# 检查是否已存在 .env
if [ -f ".env" ]; then
    echo "⚠️  .env 文件已存在"
    read -p "是否覆盖？(y/n): " overwrite
    if [ "$overwrite" != "y" ] && [ "$overwrite" != "Y" ]; then
        echo "取消配置"
        exit 0
    fi
fi

echo ""
echo "📝 请依次输入以下配置信息"
echo "   (直接回车使用默认值或示例值)"
echo ""

# ==================== Telegram Bot 配置 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  Telegram Bot 配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "Bot Token (从 @BotFather 获取): " bot_token
if [ -z "$bot_token" ]; then
    echo "   Bot Token 必须设置"
    read -p "请重新输入 Bot Token: " bot_token
fi
if [ -z "$bot_token" ]; then
    echo "Bot Token cannot be empty"
    exit 1
fi

read -p "Super Admin ID (向 @userinfobot 获取): " admin_id
if [ -z "$admin_id" ]; then
    echo "   ⚠️  必须设置 Super Admin ID"
    read -p "请重新输入 Super Admin ID: " admin_id
fi

echo ""

# ==================== 域名配置 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  域名配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "域名 (例如: bot.yourdomain.com): " domain
if [ -z "$domain" ]; then
    domain="bot.yourdomain.com"
    echo "   ⚠️  使用示例域名，请记得修改"
fi

echo ""

# ==================== 数据库配置 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  数据库配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "数据库密码 (建议强密码): " db_password
if [ -z "$db_password" ]; then
    db_password="ChangeMe123_StrongPassword"
    echo "   ⚠️  使用默认密码，生产环境请修改"
fi

db_user="admin"

echo ""

# ==================== Redis 配置 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  Redis 配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "Redis 密码 (建议强密码): " redis_password
if [ -z "$redis_password" ]; then
    redis_password="ChangeMeRedis123_StrongPassword"
    echo "   ⚠️  使用默认密码，生产环境请修改"
fi

echo ""

# ==================== USDT 支付配置 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5️⃣  USDT 支付配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "USDT TRC20 收款地址: " usdt_address
if [ -z "$usdt_address" ]; then
    echo "   ⚠️  USDT 地址为空，后续需要手动配置"
fi

read -p "TronScan API Key (可选，回车跳过): " tronscan_key
if [ -z "$tronscan_key" ]; then
    tronscan_key=""
fi

echo ""

# ==================== 生成安全密钥 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6️⃣  生成安全密钥"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "正在生成加密密钥..."

# 检查 Python3
if command -v python3 &> /dev/null; then
    encryption_key=$(python3 -c "from src.utils.token_encryptor import token_encryptor; print(token_encryptor.generate_key())" 2>/dev/null || echo "")
    web_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || echo "")
    
    if [ -n "$encryption_key" ] && [ -n "$web_key" ]; then
        echo "✅ 密钥生成成功"
    else
        echo "⚠️  密钥生成失败，使用随机字符串"
        encryption_key="encryption_key_$(date +%s)_$(openssl rand -hex 16)"
        web_key="web_key_$(date +%s)_$(openssl rand -hex 32)"
    fi
else
    echo "⚠️  Python3 未安装，使用随机字符串"
    encryption_key="encryption_key_$(date +%s)_$(openssl rand -hex 16)"
    web_key="web_key_$(date +%s)_$(openssl rand -hex 32)"
fi

echo ""

# ==================== 创建 .env 文件 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "7️⃣  创建配置文件"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cat > .env <<EOF
# ==================== Telegram Bot配置 ====================
BOT_TOKEN=$bot_token
SUPER_ADMIN_ID=$admin_id

# ==================== 域名配置 ====================
DOMAIN=$domain

# ==================== 数据库配置 ====================
DB_PASSWORD=$db_password
DB_USER=$db_user

# ==================== Redis配置 ====================
REDIS_PASSWORD=$redis_password

# ==================== USDT支付配置 ====================
USDT_PAYMENT_ADDRESS=$usdt_address
TRONSCAN_API_KEY=$tronscan_key

# ==================== Webhook配置 ====================
WEBHOOK_URL=https://\${DOMAIN}/webhook
WEB_DOMAIN=https://\${DOMAIN}

# ==================== 安全配置 ====================
BOT_TOKEN_ENCRYPTION_KEY=$encryption_key
WEB_SECRET_KEY=$web_key

# ==================== SaaS配置 ====================
PAYMENT_TEST_MODE=false
AUTHORIZATION_ENABLED=true

# ==================== 日志配置 ====================
LOG_LEVEL=INFO

# ==================== 性能优化配置 ====================
EVENT_WORKERS=3
MAX_RETRIES=3

# ==================== 其他配置 ====================
TZ=Asia/Shanghai
PYTHONUNBUFFERED=1
EOF

# 设置权限
chmod 600 .env

echo "✅ .env 文件已创建"
echo ""

# ==================== 显示配置摘要 ====================
echo "=========================================="
echo "  ✅ 配置完成！"
echo "=========================================="
echo ""
echo "📋 配置摘要:"
echo "   Bot Token: ${bot_token:0:20}..."
echo "   Admin ID: $admin_id"
echo "   Domain: $domain"
echo "   DB Password: ${db_password:0:5}..."
echo "   Redis Password: ${redis_password:0:5}..."
echo "   USDT Address: ${usdt_address:0:10}..."
echo ""
echo "⚠️  下一步:"
echo "   1. 配置 SSL 证书: ./setup_ssl.sh"
echo "   2. 启动服务: ./deploy.sh"
echo ""
echo "💡 提示:"
echo "   - 查看配置: cat .env"
echo "   - 修改配置: nano .env"
echo "   - 保护配置: chmod 600 .env"
echo ""
