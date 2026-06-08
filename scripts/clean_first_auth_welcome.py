"""自动清理数据库中的首次授权欢迎语配置"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import select, delete
from src.models import AdminGlobalConfig

async def clean():
    engine = create_async_engine('sqlite+aiosqlite:///./accounting_bot.db')
    async with engine.begin() as conn:
        # 查询配置
        result = await conn.execute(
            select(AdminGlobalConfig).where(
                AdminGlobalConfig.config_key == "first_auth_welcome_message"
            )
        )
        configs = result.fetchall()
        
        if configs:
            print(f" 发现 {len(configs)} 条首次授权欢迎语配置，正在删除...")
            
            # 删除配置
            await conn.execute(
                delete(AdminGlobalConfig).where(
                    AdminGlobalConfig.config_key == "first_auth_welcome_message"
                )
            )
            print("✅ 已删除所有首次授权欢迎语配置")
            print(" 现在 Bot 将使用代码中固定的默认欢迎语")
        else:
            print("✅ 没有找到需要清理的配置")
        
        print("\n 完成！请重启 Bot 使更改生效")

if __name__ == "__main__":
    asyncio.run(clean())
