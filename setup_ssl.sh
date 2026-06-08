#!/bin/bash

# ========================================
# SSL 证书自动配置脚本
# ========================================

set -e

echo ""
echo "=========================================="
echo "  🔐 SSL 证书配置向导"
echo "=========================================="
echo ""

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "❌ 错误: .env 文件不存在"
    echo "   请先运行: ./setup_config.sh"
    exit 1
fi

# 获取域名
DOMAIN=$(grep "^DOMAIN=" .env | cut -d'=' -f2)

if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "your-domain.com" ]; then
    echo "❌ 错误: 域名未配置或为示例域名"
    echo "   请编辑 .env 文件，设置正确的 DOMAIN"
    exit 1
fi

echo "检测到域名: $DOMAIN"
echo ""

# 检查是否已有证书
if [ -f "nginx/ssl/fullchain.pem" ] && [ -f "nginx/ssl/privkey.pem" ]; then
    echo "⚠️  SSL 证书已存在"
    read -p "是否重新获取？(y/n): " renew
    if [ "$renew" != "y" ] && [ "$renew" != "Y" ]; then
        echo "使用现有证书"
        exit 0
    fi
fi

# 安装 Certbot
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  安装 Certbot"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if ! command -v certbot &> /dev/null; then
    echo "正在安装 Certbot..."
    
    # 检测系统
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$NAME
        
        if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
            apt update -y
            apt install -y certbot
        elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
            yum install -y epel-release
            yum install -y certbot
        else
            echo "⚠️  未知系统，请手动安装 Certbot"
            exit 1
        fi
    else
        echo "⚠️  无法检测系统，请手动安装 Certbot"
        exit 1
    fi
    
    echo "✅ Certbot 安装完成"
else
    echo "✅ Certbot 已安装"
fi

echo ""

# 停止占用80端口的服务
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  准备获取证书"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "停止可能占用80端口的服务..."
docker-compose -f docker-compose.prod.yml down 2>/dev/null || true
systemctl stop nginx 2>/dev/null || true

echo "✅ 80端口已释放"
echo ""

# 获取证书
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  获取 SSL 证书"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "正在向 Let's Encrypt 申请证书..."
echo "域名: $DOMAIN"
echo ""

certbot certonly --standalone \
    -d $DOMAIN \
    --non-interactive \
    --agree-tos \
    --email admin@$DOMAIN \
    --keep-until-expiring

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ SSL 证书获取失败"
    echo ""
    echo "可能的原因:"
    echo "   1. 域名未正确解析到服务器IP"
    echo "   2. 80端口被防火墙阻止"
    echo "   3. 域名尚未生效（DNS传播需要时间）"
    echo ""
    echo "解决方法:"
    echo "   1. 检查 DNS: ping $DOMAIN"
    echo "   2. 检查防火墙: ufw allow 80/tcp"
    echo "   3. 等待几分钟后重试"
    echo ""
    exit 1
fi

echo ""
echo "✅ SSL 证书获取成功"
echo ""

# 复制证书
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  配置证书"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "创建 SSL 目录..."
mkdir -p nginx/ssl

echo "复制证书文件..."
cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem nginx/ssl/
cp /etc/letsencrypt/live/$DOMAIN/privkey.pem nginx/ssl/

echo "设置权限..."
chmod 644 nginx/ssl/fullchain.pem
chmod 600 nginx/ssl/privkey.pem

echo "✅ 证书配置完成"
echo ""

# 验证证书
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5️⃣  验证证书"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "证书信息:"
openssl x509 -in nginx/ssl/fullchain.pem -noout -subject -dates

echo ""
echo "文件列表:"
ls -la nginx/ssl/

echo ""

# 完成
echo "=========================================="
echo "  ✅ SSL 证书配置完成！"
echo "=========================================="
echo ""
echo "📋 证书信息:"
echo "   域名: $DOMAIN"
echo "   证书路径: nginx/ssl/fullchain.pem"
echo "   私钥路径: nginx/ssl/privkey.pem"
echo ""
echo "⚠️  下一步:"
echo "   启动服务: ./deploy.sh"
echo ""
echo "💡 提示:"
echo "   - 证书有效期: 90天"
echo "   - 自动续期: certbot renew"
echo "   - 查看证书: openssl x509 -in nginx/ssl/fullchain.pem -noout -dates"
echo ""
