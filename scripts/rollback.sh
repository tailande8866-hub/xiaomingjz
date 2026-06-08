#!/bin/bash
set -e

# 🔥 服务器项目目录（固定路径，永不改变）
PROJECT_DIR="/opt/saas-bot"

cd "$PROJECT_DIR"

echo "============================================="
echo " 🛟 数据回滚工具"
echo "============================================="
echo ""
echo " 📂 项目目录: $PROJECT_DIR"
echo ""

# 查找最新的备份文件
LATEST_BACKUP=$(ls -t backups/auto_backup_*.db 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "❌ 错误: 没有找到备份文件"
    echo ""
    echo "📂 backups/ 目录内容:"
    ls -la backups/ 2>/dev/null || echo "   (目录为空或不存在)"
    echo ""
    exit 1
fi

echo "🗄️  找到最新备份: $LATEST_BACKUP"
echo ""

# 确认回滚
echo "⚠️  警告: 回滚将恢复数据库到备份时的状态"
echo "   备份时间: $(stat -c %y "$LATEST_BACKUP" 2>/dev/null || stat -f %Sm "$LATEST_BACKUP" 2>/dev/null)"
echo ""
read -p "确定要回滚吗? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo ""
    echo "❌ 回滚已取消"
    exit 0
fi

echo ""
echo "📂 步骤 1/3: 停止服务..."
docker-compose down
echo "   ✅ 服务已停止"
echo ""

echo "📂 步骤 2/3: 恢复数据库..."
mkdir -p data

# 备份当前数据库（防止二次丢失）
if [ -f "data/accounting_bot.db" ]; then
    cp data/accounting_bot.db backups/pre_rollback_$(date +%Y%m%d_%H%M%S).db
    echo "   ✅ 当前数据库已备份"
fi

# 恢复备份
cp "$LATEST_BACKUP" data/accounting_bot.db
echo "   ✅ 数据库已恢复: $LATEST_BACKUP"
echo ""

echo "📂 步骤 3/3: 重启服务..."
docker-compose up -d
echo "   ✅ 服务已重启"
echo ""

echo "============================================="
echo " ✅ 回滚完成！"
echo "============================================="
echo ""
echo " 📌 数据库已恢复到备份时的状态"
echo " 🛡️ 所有数据、授权、子机器人配置已恢复"
echo ""
echo " 📂 恢复的数据库: $LATEST_BACKUP"
echo ""
