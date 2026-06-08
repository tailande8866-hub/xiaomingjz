#!/bin/bash
# 自动备份脚本 - 保护核心数据
# 备份内容：用户账单、授权群组、Trial数据、BOT订阅、用户权限

BACKUP_DIR="/opt/saas-bot/backups"
DATA_DIR="/opt/saas-bot/data"
DB_DIR="/opt/saas-bot"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份数据
echo "开始备份..."
tar czf $BACKUP_DIR/backup_$DATE.tar.gz \
    -C $DB_DIR data/ *.db .env 2>/dev/null

# 检查备份是否成功
if [ -f "$BACKUP_DIR/backup_$DATE.tar.gz" ]; then
    echo "备份完成: backup_$DATE.tar.gz"
    echo "大小: $(du -h $BACKUP_DIR/backup_$DATE.tar.gz | cut -f1)"
else
    echo "备份失败"
    exit 1
fi

# 只保留最近 10 个备份
echo "清理旧备份..."
ls -t $BACKUP_DIR/*.tar.gz 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null

echo "备份系统运行正常"
