#!/bin/bash

# ========================================
# SaaS记账机器人 - 一键完整部署
# ========================================

set -e

echo ""
echo "=========================================="
echo "  🚀 SaaS记账机器人 - 一键部署"
echo "=========================================="
echo ""

# 检查是否在正确目录
if [ ! -f "docker-compose.prod.yml" ]; then
    echo "❌ 错误: 请在项目根目录运行此脚本"
    exit 1
fi

echo "此脚本将自动完成："
echo "   1. 配置环境变量"
echo "   2. 获取 SSL 证书"
echo "   3. 启动 Docker 服务"
echo "   4. 验证部署状态"
echo ""

read -p "是否继续？(y/n): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "取消部署"
    exit 0
fi

echo ""

# ==================== 步骤1: 配置环境变量 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "步骤 1/4: 配置环境变量"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -f ".env" ]; then
    echo "运行配置向导..."
    chmod +x setup_config.sh
    ./setup_config.sh
else
    echo "✅ .env 文件已存在"
    read -p "是否重新配置？(y/n): " reconfig
    if [ "$reconfig" = "y" ] || [ "$reconfig" = "Y" ]; then
        chmod +x setup_config.sh
        ./setup_config.sh
    fi
fi

echo ""

# ==================== 步骤2: 配置 SSL 证书 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "步骤 2/4: 配置 SSL 证书"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -f "nginx/ssl/fullchain.pem" ] || [ ! -f "nginx/ssl/privkey.pem" ]; then
    echo "运行 SSL 配置向导..."
    chmod +x setup_ssl.sh
    ./setup_ssl.sh
else
    echo "✅ SSL 证书已存在"
    read -p "是否重新获取？(y/n): " renew_ssl
    if [ "$renew_ssl" = "y" ] || [ "$renew_ssl" = "Y" ]; then
        chmod +x setup_ssl.sh
        ./setup_ssl.sh
    fi
fi

echo ""

# ==================== 步骤3: 启动服务 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "步骤 3/4: 启动 Docker 服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "正在构建和启动服务..."
echo ""

chmod +x deploy.sh
./deploy.sh

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 部署失败，请检查日志"
    docker-compose -f docker-compose.prod.yml logs --tail=50
    exit 1
fi

echo ""

# ==================== 步骤4: 验证部署 ====================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "步骤 4/4: 验证部署状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

sleep 5

# 检查容器状态
echo "检查容器状态..."
if docker-compose -f docker-compose.prod.yml ps | grep -q "Up"; then
    echo "✅ 所有服务运行正常"
else
    echo "❌ 部分服务未正常运行"
    docker-compose -f docker-compose.prod.yml ps
    exit 1
fi

echo ""

# 显示服务状态
echo "=========================================="
echo "  服务状态"
echo "=========================================="
docker-compose -f docker-compose.prod.yml ps

echo ""

# 获取域名
DOMAIN=$(grep "^DOMAIN=" .env | cut -d'=' -f2)

echo "=========================================="
echo "  访问地址"
echo "=========================================="
echo "   HTTPS: https://$DOMAIN"
echo "   Health: https://$DOMAIN/health"
echo ""

echo "=========================================="
echo "  常用命令"
echo "=========================================="
echo "   查看日志: docker-compose -f docker-compose.prod.yml logs -f bot"
echo "   重启服务: docker-compose -f docker-compose.prod.yml restart"
echo "   停止服务: docker-compose -f docker-compose.prod.yml down"
echo "   进入容器: docker exec -it saas-bot bash"
echo ""

echo "=========================================="
echo "  ✅ 部署完成！"
echo "=========================================="
echo ""
echo "🎉 恭喜！SaaS记账机器人已成功部署"
echo ""
echo "📋 下一步:"
echo "   1. 在 Telegram 中搜索您的 Bot"
echo "   2. 发送 /start 命令测试"
echo "   3. 查看详细文档了解功能"
echo ""
echo "💡 提示:"
echo "   - 查看日志: docker-compose -f docker-compose.prod.yml logs -f"
echo "   - 备份数据: ./scripts/backup.sh"
echo "   - 更新代码: git pull && ./deploy.sh"
echo ""
