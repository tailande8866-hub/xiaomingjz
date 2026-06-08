#!/bin/bash
# MVP快速部署脚本
# 使用方法: chmod +x quick_deploy.sh && ./quick_deploy.sh

set -e  # 遇到错误立即退出

echo "=========================================="
echo "  SaaS记账机器人 MVP快速部署脚本"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否以root运行
if [ "$EUID" -ne 0 ]; then 
    echo -e "${YELLOW}提示: 建议使用sudo运行此脚本${NC}"
    read -p "是否继续? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 步骤1: 检查Docker
echo -e "${GREEN}[1/7] 检查Docker安装...${NC}"
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}Docker未安装，开始安装...${NC}"
    
    # 检测操作系统
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
    else
        echo -e "${RED}无法检测操作系统${NC}"
        exit 1
    fi
    
    if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        # Ubuntu/Debian
        apt-get update
        apt-get install -y \
            apt-transport-https \
            ca-certificates \
            curl \
            gnupg \
            lsb-release
        
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
        
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
          $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
        
        apt-get update
        apt-get install -y docker-ce docker-ce-cli containerd.io
        
    elif [ "$OS" = "centos" ] || [ "$OS" = "rhel" ]; then
        # CentOS/RHEL
        yum install -y yum-utils
        yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        yum install -y docker-ce docker-ce-cli containerd.io
        systemctl start docker
        systemctl enable docker
    else
        echo -e "${RED}不支持的操作系统: $OS${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}Docker安装完成${NC}"
else
    echo -e "${GREEN}Docker已安装: $(docker --version)${NC}"
fi

# 检查Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo -e "${YELLOW}安装Docker Compose...${NC}"
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo -e "${GREEN}Docker Compose安装完成${NC}"
else
    echo -e "${GREEN}Docker Compose已安装: $(docker-compose --version)${NC}"
fi

echo ""

# 步骤2: 配置环境变量
echo -e "${GREEN}[2/7] 配置环境变量...${NC}"
if [ ! -f .env ]; then
    cp .env.example .env
    echo -e "${GREEN}已创建 .env 配置文件${NC}"
    echo -e "${YELLOW}请编辑 .env 文件并填写必要配置${NC}"
    echo ""
    read -p "按回车键继续..."
else
    echo -e "${GREEN}.env 已存在${NC}"
fi

echo ""

# 步骤3: 创建必要目录
echo -e "${GREEN}[3/7] 创建必要目录...${NC}"
mkdir -p logs bot_instances backups static
echo -e "${GREEN}目录创建完成${NC}"

echo ""

# 步骤4: 设置文件权限
echo -e "${GREEN}[4/7] 设置文件权限...${NC}"
chmod 600 .env 2>/dev/null || true
chmod +x scripts/backup.sh 2>/dev/null || true
echo -e "${GREEN}权限设置完成${NC}"

echo ""

# 步骤5: 构建Docker镜像
echo -e "${GREEN}[5/7] 构建Docker镜像...${NC}"
docker-compose build
echo -e "${GREEN}镜像构建完成${NC}"

echo ""

# 步骤6: 启动服务
echo -e "${GREEN}[6/7] 启动服务...${NC}"
docker-compose up -d
echo -e "${GREEN}服务启动完成${NC}"

echo ""

# 步骤7: 检查服务状态
echo -e "${GREEN}[7/7] 检查服务状态...${NC}"
sleep 5
docker-compose ps

echo ""
echo "=========================================="
echo -e "${GREEN}部署完成！${NC}"
echo "=========================================="
echo ""
echo "📊 服务状态:"
docker-compose ps
echo ""
echo "📝 查看日志:"
echo "   docker-compose logs -f"
echo ""
echo "🔄 重启服务:"
echo "   docker-compose restart"
echo ""
echo "🛑 停止服务:"
echo "   docker-compose down"
echo ""
echo "💾 备份数据库:"
echo "   ./scripts/backup.sh"
echo ""
echo "⚠️  重要提醒:"
echo "   1. 请确保已正确配置 .env 文件"
echo "   2. 建议配置SSL证书（HTTPS）"
echo "   3. 定期备份数据库"
echo "   4. 查看 docs/SAAS_AUTO_SELLING_GUIDE.md 获取详细文档"
echo ""
echo "祝您好运！🚀"
