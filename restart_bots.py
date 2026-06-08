"""重启所有子bot"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.bot_instance_manager import BotInstanceManager
from config import config


async def restart_all_bots():
    """重启所有运行中的bot"""
    mgr = BotInstanceManager()
    
    # 获取所有bot
    bots = await mgr.list_bots()
    print(f"找到 {len(bots)} 个bot")
    
    # 停止所有运行中的bot
    for bot in bots:
        bot_id = bot['bot_id']
        status = bot.get('status')
        print(f"停止 bot: {bot_id} (状态: {status})")
        try:
            await mgr.stop_bot(bot_id)
            print(f"✅ 已停止 {bot_id}")
        except Exception as e:
            print(f"⚠️ 停止 {bot_id} 失败: {e}")
    
    # 等待一下确保进程完全退出
    await asyncio.sleep(2)
    
    # 重新启动所有bot
    for bot in bots:
        bot_id = bot['bot_id']
        print(f"启动 bot: {bot_id}")
        try:
            await mgr.start_bot(bot_id)
            print(f"✅ 已启动 {bot_id}")
        except Exception as e:
            print(f"❌ 启动 {bot_id} 失败: {e}")
    
    print("\n所有bot重启完成！")


if __name__ == "__main__":
    asyncio.run(restart_all_bots())
