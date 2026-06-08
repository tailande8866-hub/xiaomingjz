#!/bin/bash
# 上传数据库文件到服务器并重启容器

echo "正在复制数据库文件到容器..."
sudo docker cp /opt/saas-bot/accounting_bot.db saas-bot:/app/accounting_bot.db

echo "重启容器..."
sudo docker-compose restart

echo "查看日志..."
sudo docker-compose logs --tail=30 bot
