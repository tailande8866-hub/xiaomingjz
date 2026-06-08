#!/bin/bash

echo "=========================================="
echo "初始化服务器数据库"
echo "=========================================="
echo ""

# 进入容器并执行Python脚本
sudo docker exec -it saas-bot python3 << 'EOF'
import asyncio
import os
from sqlalchemy import select, text
from src.core.database import async_session
from src.models.bot_instance import BotInstance
from src.models.group import Group
from src.models.admin import Admin
from src.models.group_authorization import GroupAuthorization

async def init_db():
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        raise RuntimeError('BOT_TOKEN must be set in the container environment')
    async with async_session() as session:
        # 1. 创建 main_bot 记录
        print("1. 检查 main_bot 记录...")
        result = await session.execute(select(BotInstance).where(BotInstance.bot_id == 'main_bot'))
        bot = result.scalar_one_or_none()
        
        if not bot:
            print("  → 创建 main_bot...")
            bot = BotInstance(
                bot_id='main_bot',
                bot_token=bot_token,
                is_active=True
            )
            session.add(bot)
            await session.commit()
            print("  ✅ main_bot 已创建")
        else:
            print("  ✅ main_bot 已存在")
        
        # 2. 检查数据库表是否完整
        print("\n2. 检查数据库表...")
        tables = ['bot_instances', 'groups', 'admins', 'group_authorizations', 'transactions']
        for table in tables:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            print(f"  - {table}: {count} 条记录")
        
        print("\n==========================================")
        print("✅ 数据库初始化完成！")
        print("==========================================")
        print("\n请重启容器：sudo docker-compose restart")
        print("然后查看日志：sudo docker-compose logs -f bot")

asyncio.run(init_db())
EOF

echo ""
echo "✅ 脚本执行完成！"
echo ""
