#!/bin/bash
echo "=========================================="
echo "步骤1: 检查git拉取是否成功"
echo "=========================================="
cd /opt/saas-bot
git log --oneline -3
echo ""

echo "=========================================="
echo "步骤2: 检查数据库文件"
echo "=========================================="
ls -lh accounting_bot.db
echo ""

echo "=========================================="
echo "步骤3: 检查容器内数据库"
echo "=========================================="
sudo docker exec saas-bot ls -lh /app/accounting_bot.db
echo ""

echo "=========================================="
echo "步骤4: 复制最新数据库到容器"
echo "=========================================="
sudo docker cp /opt/saas-bot/accounting_bot.db saas-bot:/app/accounting_bot.db
echo "✅ 数据库已复制"
echo ""

echo "=========================================="
echo "步骤5: 重启容器"
echo "=========================================="
sudo docker-compose restart
echo "✅ 容器已重启"
echo ""

echo "=========================================="
echo "步骤6: 查看日志（等待10秒）"
echo "=========================================="
sleep 10
sudo docker-compose logs --tail=50 bot | grep -E "main_bot|Database initialized|Starting bot"
