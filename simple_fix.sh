#!/bin/bash
docker-compose exec bot python -c "
import sqlite3
conn = sqlite3.connect('/app/data/accounting_bot.db')
c = conn.cursor()
c.execute('UPDATE groups SET status=\"ACTIVE\", is_active=1')
print('已修复所有群组')
c.execute('SELECT group_name, status, is_active FROM groups')
for g in c.fetchall():
    print(f'{g[0]}: status={g[1]}, is_active={g[2]}')
conn.commit()
conn.close()
"
docker-compose restart bot
