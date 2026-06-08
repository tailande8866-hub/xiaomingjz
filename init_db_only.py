#!/usr/bin/env python3
"""
只初始化数据库，不启动Bot
"""
import asyncio
import os
from src.models.database import init_db, get_db_session
from sqlalchemy import select
from src.models.saas_auto import BotCreation

async def main():
    bot_token = os.getenv("BOT_TOKEN")
    super_admin_id = int(os.getenv("SUPER_ADMIN_ID", "0") or "0")
    bot_username = os.getenv("BOT_USERNAME", "main_bot")

    if not bot_token or not super_admin_id:
        raise RuntimeError("BOT_TOKEN and SUPER_ADMIN_ID must be set before initializing main_bot")

    print("1. 创建数据库表结构...")
    await init_db()
    print("[OK] 数据库表已创建")

    print("\n2. 创建 main_bot 记录...")
    async with get_db_session() as session:
        result = await session.execute(select(BotCreation).where(BotCreation.instance_id == 'main_bot'))
        bot = result.scalar_one_or_none()
        
        if not bot:
            bot = BotCreation(
                telegram_id=int(bot_token.split(':', 1)[0]),
                bot_token=bot_token,
                bot_username=bot_username,
                super_admin_id=super_admin_id,
                instance_id='main_bot',
                status='running',
                instance_dir=None,
                db_path=None,
                env_path=None,
                tree_depth=0
            )
            session.add(bot)
            print("[OK] main_bot 已创建")
        else:
            print("[OK] main_bot 已存在")
    
    print("\n3. 验证数据库...")
    async with get_db_session() as session:
        result = await session.execute(select(BotCreation))
        bots = result.fetchall()
        print(f"数据库中有 {len(bots)} 个 bot 实例")
        for b in bots:
            print(f"  - {b[0].bot_username}: status={b[0].status}")
    
    print("\n 数据库初始化完成！可以直接推送到Git了")

if __name__ == "__main__":
    asyncio.run(main())
