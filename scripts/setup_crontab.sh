#!/bin/bash
# 定时任务配置脚本
# 自动配置所有定时任务

# 设置 crontab
cat << 'EOF' | crontab -
# 数据库备份 - 每天凌晨 2 点
0 2 * * * /opt/saas-bot/backup.sh

# 日志清理 - 每周日凌晨 3 点
0 3 * * 0 /opt/saas-bot/log_cleanup.sh

# 数据库优化 - 每月 1 号凌晨 4 点
0 4 1 * * /opt/saas-bot/db_optimize.sh

# 健康检查 - 每 15 分钟
*/15 * * * * /opt/saas-bot/health_check.sh
EOF

echo "Crontab configured successfully!"
echo ""
echo "Current crontab:"
crontab -l
