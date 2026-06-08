#!/bin/bash

# ============================================
# Telegram SaaS Bot - 一键部署脚本
# ============================================

set -e

echo "=========================================="
echo "🚀 Telegram SaaS Bot 一键部署脚本"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查必要工具
echo "📦 检查必要工具..."

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker 未安装${NC}"
    echo "请先安装 Docker: curl -fsSL https://get.docker.com | bash"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose 未安装${NC}"
    echo "请先安装 Docker Compose"
    exit 1
fi

echo -e "${GREEN}✅ Docker 和 Docker Compose 已安装${NC}"
echo ""

# 检查是否在Git仓库中
if [ ! -d ".git" ]; then
    echo -e "${RED}❌ 未检测到 Git 仓库${NC}"
    echo "请先克隆代码: git clone <仓库地址> ."
    exit 1
fi

echo "✅ 检测到 Git 仓库"
echo ""

# 检查配置文件
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  未找到 .env 配置文件${NC}"
    if [ -f ".env.prod" ]; then
        echo "正在从 .env.prod 创建 .env..."
        cp .env.prod .env
        echo -e "${YELLOW}⚠️  请编辑 .env 文件，修改必要的配置项${NC}"
        echo "必须修改的配置："
        echo "  - BOT_TOKEN"
        echo "  - SUPER_ADMIN_ID"
        echo "  - WEB_BASE_URL"
        read -p "按回车键继续部署（或 Ctrl+C 取消）..."
    else
        echo -e "${RED}❌ 未找到 .env.prod 模板文件${NC}"
        exit 1
    fi
else
    echo "✅ 找到 .env 配置文件"
fi
echo ""

# 创建必要目录
echo "📁 创建必要目录..."
mkdir -p data logs bot_instances
echo -e "${GREEN}✅ 目录创建完成${NC}"
echo ""

# 停止旧容器（如果存在）
echo "🛑 停止旧容器..."
docker-compose down 2>/dev/null || true
echo -e "${GREEN}✅ 旧容器已停止${NC}"
echo ""

# 构建并启动容器
echo "🔨 构建Docker镜像..."
docker-compose build --no-cache

echo ""
echo "🚀 启动服务..."
docker-compose up -d

echo ""
echo -e "${GREEN}=========================================="
echo "✅ 部署完成！"
echo "==========================================${NC}"
echo ""
echo "📊 服务状态："
docker-compose ps
echo ""
echo "📝 查看日志："
echo "   docker-compose logs -f bot"
echo ""
echo "🌐 Web账单系统："
echo "   http://your-domain.com:8081"
echo ""
echo "⚠️  重要提示："
echo "   1. 请确保防火墙开放端口 8081"
echo "   2. 请定期备份数据库"
echo "   3. 查看实时日志: docker-compose logs -f bot"
echo ""
