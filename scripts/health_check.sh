#!/bin/bash
# 系统健康检查脚本
# 每 15 分钟执行一次

LOG_FILE="/opt/saas-bot/logs/health_check.log"

docker exec saas-bot python3 -c "
import sqlite3
conn = sqlite3.connect('/app/accounting_bot.db')
tables = ['groups', 'transactions', 'admins', 'transaction_events']
for table in tables:
    try:
        count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(f'{table}: OK ({count} records)')
    except Exception as e:
        print(f'{table}: ERROR - {e}')
conn.close()
" >> "$LOG_FILE" 2>&1

echo "$(date): Health check completed" >> "$LOG_FILE"
