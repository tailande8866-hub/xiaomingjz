#!/bin/bash

# ==================== SaaS记账机器人 - 一键部署脚本 ====================
# 
# 使用方法：
#   chmod +x auto_deploy.sh
#   ./auto_deploy.sh
#
# 功能：
#   1. 检查系统环境
#   2. 安装 Docker 和 Docker Compose
#   3. 克隆代码
#   4. 引导配置 .env
#   5. 配置 SSL 证书
#   6. 启动服务
#   7. 验证部署

set -e  # 遇到错误立即退出

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo "=========================================="
echo "  SaaS记账机器人 - 一键部署工具"
echo "=========================================="
echo ""

# ==================== 步骤1: 检查系统环境 ====================
echo -e "${CYAN}[步骤 1/7] 检查系统环境...${NC}"

# 检查操作系统
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
    echo -e "${GREEN}✅ 操作系统: $OS $VER${NC}"
else
    echo -e "${RED}❌ 无法检测操作系统${NC}"
    exit 1
fi

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}❌ 请使用 root 权限运行此脚本${NC}"
    echo "   sudo ./auto_deploy.sh"
    exit 1
fi

# 检查域名
echo ""
echo -e "${YELLOW}请输入您的域名（例如: bot.yourdomain.com）:${NC}"
read -p "域名: " DOMAIN

if [ -z "$DOMAIN" ]; then
    echo -e "${RED}❌ 域名不能为空${NC}"
    exit 1
fi

echo -e "${GREEN}✅ 域名: $DOMAIN${NC}"
echo ""

# ==================== 步骤2: 安装 Docker ====================
echo -e "${CYAN}[步骤 2/7] 检查并安装 Docker...${NC}"

if command -v docker &> /dev/null; then
    echo -e "${GREEN}✅ Docker 已安装: $(docker --version)${NC}"
else
    echo -e "${YELLOW}⚠️  Docker 未安装，开始安装...${NC}"
    
    if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
        curl -fsSL https://get.docker.com -o get-docker.sh
        sh get-docker.sh
        rm get-docker.sh
    elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
        yum install -y yum-utils
        yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        yum install -y docker-ce docker-ce-cli containerd.io
        systemctl start docker
        systemctl enable docker
    else
        echo -e "${RED}❌ 不支持的操作系统: $OS${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Docker 安装完成${NC}"
fi

# 添加用户到 docker 组
usermod -aG docker $USER 2>/dev/null || true

# 检查 Docker Compose
if command -v docker-compose &> /dev/null; then
    echo -e "${GREEN}✅ Docker Compose 已安装: $(docker-compose --version)${NC}"
else
    echo -e "${YELLOW}⚠️  Docker Compose 未安装，开始安装...${NC}"
    
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    
    echo -e "${GREEN}✅ Docker Compose 安装完成${NC}"
fi

echo ""

# ==================== 步骤3: 克隆代码 ====================
echo -e "${CYAN}[步骤 3/7] 克隆代码...${NC}"

DEPLOY_DIR="/opt/saas-bot"

if [ -d "$DEPLOY_DIR/.git" ]; then
    echo -e "${YELLOW}⚠️  目录已存在，更新代码...${NC}"
    cd $DEPLOY_DIR
    git pull origin main || git pull origin master
    echo -e "${GREEN}✅ 代码已更新${NC}"
else
    echo -e "${YELLOW}⚠️  创建目录并克隆代码...${NC}"
    mkdir -p $DEPLOY_DIR
    cd $DEPLOY_DIR
    git clone https://github.com/tailande8866-hub/tg-.git . || {
        echo -e "${RED}❌ Git 克隆失败${NC}"
        echo "请手动上传代码到 $DEPLOY_DIR"
        exit 1
    }
    echo -e "${GREEN}✅ 代码已克隆${NC}"
fi

echo ""

# ==================== 步骤4: 配置环境变量 ====================
echo -e "${CYAN}[步骤 4/7] 配置环境变量...${NC}"

cd $DEPLOY_DIR

if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  .env 文件不存在，从模板创建...${NC}"
    cp .env.prod.example .env
    
    echo ""
    echo -e "${YELLOW}请配置以下信息（直接回车使用默认值）:${NC}"
    echo ""
    
    # Bot Token
    read -p "Bot Token (required, from @BotFather): " BOT_TOKEN_INPUT
    if [ -z "$BOT_TOKEN_INPUT" ]; then
        echo -e "${RED}Bot Token cannot be empty${NC}"
        exit 1
    fi
    if [ -n "$BOT_TOKEN_INPUT" ]; then
        sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$BOT_TOKEN_INPUT|" .env
    fi
    
    # Super Admin ID
    read -p "Super Admin ID (向 @userinfobot 获取): " ADMIN_ID
    if [ -n "$ADMIN_ID" ]; then
        sed -i "s|^SUPER_ADMIN_ID=.*|SUPER_ADMIN_ID=$ADMIN_ID|" .env
    fi
    
    # Domain
    sed -i "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" .env
    
    # DB Password
    read -p "数据库密码 (默认: ChangeMe123_StrongPassword): " DB_PASS
    if [ -n "$DB_PASS" ]; then
        sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$DB_PASS|" .env
    fi
    
    # Redis Password
    read -p "Redis密码 (默认: ChangeMeRedis123_StrongPassword): " REDIS_PASS
    if [ -n "$REDIS_PASS" ]; then
        sed -i "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$REDIS_PASS|" .env
    fi
    
    # USDT Address
    read -p "USDT收款地址: " USDT_ADDR
    if [ -n "$USDT_ADDR" ]; then
        sed -i "s|^USDT_PAYMENT_ADDRESS=.*|USDT_PAYMENT_ADDRESS=$USDT_ADDR|" .env
    fi
    
    # TronScan API Key
    read -p "TronScan API Key (可选): " TRON_KEY
    if [ -n "$TRON_KEY" ]; then
        sed -i "s|^TRONSCAN_API_KEY=.*|TRONSCAN_API_KEY=$TRON_KEY|" .env
    fi
    
    # Generate encryption keys
    echo ""
    echo -e "${YELLOW}生成加密密钥...${NC}"
    
    if command -v python3 &> /dev/null; then
        ENCRYPTION_KEY=$(python3 -c "from src.utils.token_encryptor import token_encryptor; print(token_encryptor.generate_key())" 2>/dev/null || echo "default_encryption_key_$(date +%s)")
        WEB_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || echo "default_web_key_$(date +%s)")
        
        sed -i "s|^BOT_TOKEN_ENCRYPTION_KEY=.*|BOT_TOKEN_ENCRYPTION_KEY=$ENCRYPTION_KEY|" .env
        sed -i "s|^WEB_SECRET_KEY=.*|WEB_SECRET_KEY=$WEB_KEY|" .env
        
        echo -e "${GREEN}✅ 加密密钥已生成${NC}"
    else
        echo -e "${YELLOW}⚠️  Python3 未安装，使用默认密钥（生产环境请手动修改）${NC}"
    fi
    
    echo -e "${GREEN}✅ .env 配置完成${NC}"
else
    echo -e "${GREEN}✅ .env 文件已存在${NC}"
    echo -e "${YELLOW}⚠️  请手动检查配置是否正确: nano .env${NC}"
fi

echo ""

# ==================== 步骤5: 配置 SSL 证书 ====================
echo -e "${CYAN}[步骤 5/7] 配置 SSL 证书...${NC}"

SSL_DIR="$DEPLOY_DIR/nginx/ssl"
mkdir -p $SSL_DIR

if [ -f "$SSL_DIR/fullchain.pem" ] && [ -f "$SSL_DIR/privkey.pem" ]; then
    echo -e "${GREEN}✅ SSL 证书已存在${NC}"
else
    echo -e "${YELLOW}⚠️  SSL 证书不存在，开始配置...${NC}"
    
    # 检查 certbot
    if ! command -v certbot &> /dev/null; then
        echo -e "${YELLOW}⚠️  安装 Certbot...${NC}"
        
        if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
            apt install -y certbot
        elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]]; then
            yum install -y certbot
        fi
    fi
    
    # 停止可能占用80端口的服务
    docker-compose -f docker-compose.prod.yml down 2>/dev/null || true
    
    # 获取证书
    echo -e "${YELLOW}⚠️  正在获取 SSL 证书...${NC}"
    certbot certonly --standalone -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN || {
        echo -e "${RED}❌ SSL 证书获取失败${NC}"
        echo "请手动配置 SSL 证书到: $SSL_DIR"
        echo "需要文件: fullchain.pem 和 privkey.pem"
        exit 1
    }
    
    # 复制证书
    cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem $SSL_DIR/
    cp /etc/letsencrypt/live/$DOMAIN/privkey.pem $SSL_DIR/
    chmod 644 $SSL_DIR/fullchain.pem
    chmod 600 $SSL_DIR/privkey.pem
    
    echo -e "${GREEN}✅ SSL 证书配置完成${NC}"
fi

echo ""

# ==================== 步骤6: 启动服务 ====================
echo -e "${CYAN}[步骤 6/7] 启动服务...${NC}"

cd $DEPLOY_DIR

# 设置执行权限
chmod +x deploy.sh

# 执行部署
echo -e "${YELLOW}⚠️  正在构建和启动服务...${NC}"
./deploy.sh

echo ""

# ==================== 步骤7: 验证部署 ====================
echo -e "${CYAN}[步骤 7/7] 验证部署...${NC}"

sleep 5

# 检查容器状态
if docker-compose -f docker-compose.prod.yml ps | grep -q "Up"; then
    echo -e "${GREEN}✅ 所有服务运行正常${NC}"
    
    echo ""
    echo "=========================================="
    echo "  服务状态"
    echo "=========================================="
    docker-compose -f docker-compose.prod.yml ps
    
    echo ""
    echo "=========================================="
    echo "  访问地址"
    echo "=========================================="
    echo -e "${GREEN}HTTPS: https://$DOMAIN${NC}"
    echo -e "${GREEN}Health: https://$DOMAIN/health${NC}"
    
    echo ""
    echo "=========================================="
    echo "  常用命令"
    echo "=========================================="
    echo "查看日志: docker-compose -f docker-compose.prod.yml logs -f bot"
    echo "重启服务: docker-compose -f docker-compose.prod.yml restart"
    echo "停止服务: docker-compose -f docker-compose.prod.yml down"
    echo "进入容器: docker exec -it saas-bot bash"
    
    echo ""
    echo -e "${GREEN}🎉 部署完成！${NC}"
    echo ""
    echo -e "${YELLOW}下一步:${NC}"
    echo "1. 在 Telegram 中搜索您的 Bot"
    echo "2. 发送 /start 命令测试"
    echo "3. 查看详细文档: cat DOCKER_PRODUCTION_DEPLOY.md"
else
    echo -e "${RED}❌ 服务启动失败，请检查日志${NC}"
    echo ""
    echo "查看错误日志:"
    docker-compose -f docker-compose.prod.yml logs --tail=50
    exit 1
fi
