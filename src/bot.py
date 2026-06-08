"""
Telegram记账机器人主程序

⭐ 已重构为使用 Bot Factory 模式
- 所有 Bot 共享同一套功能内核
- 通过配置区分不同 Bot 的行为
"""
import os
import asyncio
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import Application, ContextTypes

from config import config
from .core.bot_factory import BotFactory
from .utils.logging_config import setup_production_logging, log_startup_info
from .utils.database_url import get_shared_database_url

# 配置生产级日志系统
logger = setup_production_logging()
log_startup_info(logger)



def main():
    """
    主函数 - 使用 Bot Factory 创建和运行机器人
    
    这是主机器人的入口点，子机器人也会调用此函数但传入不同的 token
    """
    # 验证配置
    config.validate()
    
    # 判断是否为主机器人（通过环境变量或配置）
    # 子机器人会在 .env 中设置 IS_MAIN_BOT=false
    is_main_bot = os.environ.get('IS_MAIN_BOT', 'true').lower() == 'true'
    runtime_instance_id = os.environ.get('INSTANCE_ID')
    enable_child_autostart = (
        is_main_bot
        or runtime_instance_id == 'test_bot'
        or os.environ.get('ENABLE_CHILD_BOT_AUTOSTART', 'false').lower() == 'true'
    )
    
    logger.info(
        "Starting bot (is_main_bot=%s, instance_id=%s, child_autostart=%s)",
        is_main_bot,
        runtime_instance_id,
        enable_child_autostart,
    )
    
    # Deleted: # ⭐ 启动 Web 服务（在后台线程）
    # Deleted: if os.environ.get('WEB_ENABLED', 'false').lower() == 'true':
    # Deleted:     logger.info("🚀 Starting Web Bill System in background...")
    # Deleted:     web_thread = threading.Thread(target=start_web_server, daemon=True)
    # Deleted:     web_thread.start()
    
    # 使用 Bot Factory 创建 Application
    application = BotFactory.create_application(
        bot_token=config.BOT_TOKEN,
        is_main_bot=is_main_bot
    )
    
    # 🔥 终极永久解决方案：主Bot启动后，自动启动所有子Bot
    if enable_child_autostart:
        try:
            from .services.bot_instance_manager import bot_instance_manager
            from .models.saas_auto import BotLifecycleStatus
            from .models.database import get_db_session
            from sqlalchemy import select, and_
            from .models import BotCreation
            
            async def _ensure_bot_env_file(bot):
                """
                检查并修复子 Bot 的 .env 文件 → 统一调用 EnvGenerator
                """
                from .services.env_generator import ensure_env_file
                from .utils.token_encryptor import token_encryptor
                
                try:
                    decrypted_token = token_encryptor.decrypt_from_base64(bot.bot_token)
                    await ensure_env_file(
                        instance_dir=bot.instance_dir,
                        bot_token=decrypted_token,
                        instance_id=bot.instance_id,
                        bot_owner_id=bot.telegram_id,
                        bot_username=bot.bot_username or "",
                        database_url=get_shared_database_url(),
                    )
                except Exception as e:
                    logger.error(f"  ❌ 确保 .env 文件失败: {e}")
            
            async def start_all_sub_bots(application):
                """
                在主Bot启动后，异步启动所有ACTIVE状态的子Bot
                保证：以后每次更新 → 主 Bot + 子 Bot 全部正常
                """
                logger.info("🚀 [终极方案] 正在自动启动所有子 Bot...")
                
                try:
                    async with get_db_session() as db:
                        # 查询所有 ACTIVE 状态的子 Bot（排除主 Bot）
                        query = select(BotCreation).where(
                            and_(
                                BotCreation.lifecycle_status == BotLifecycleStatus.ACTIVE,
                                (BotCreation.token_status.is_(None) | (BotCreation.token_status != "invalid")),
                                (BotCreation.expire_time.is_(None) | (BotCreation.expire_time > datetime.utcnow())),
                                BotCreation.instance_id != 'main_bot',
                            )
                        )
                        result = await db.execute(query)
                        active_bots = result.scalars().all()
                        
                        if not active_bots:
                            logger.info("✅ 没有需要启动的子 Bot")
                            return
                        
                        logger.info(f"📊 发现 {len(active_bots)} 个 ACTIVE 状态的子 Bot")
                        
                        started_count = 0
                        failed_count = 0
                        
                        for bot in active_bots:
                            try:
                                logger.info(f"  🔄 正在启动: {bot.instance_id} (@{bot.bot_username or 'unknown'})...")
                                
                                # 🔥 关键修复：检查并修复缺失的 .env 文件
                                await _ensure_bot_env_file(bot)
                                
                                # 使用 bot_instance_manager 启动 Bot
                                success = await bot_instance_manager.start_bot_instance(bot)
                                
                                if success:
                                    started_count += 1
                                    logger.info(f"  ✅ 启动成功: {bot.instance_id}")
                                else:
                                    failed_count += 1
                                    logger.warning(f"  ❌ 启动失败: {bot.instance_id}")
                                
                                # 稍微延迟，避免同时启动过多进程
                                await asyncio.sleep(0.5)
                                
                            except Exception as e:
                                failed_count += 1
                                logger.error(f"  ❌ 启动异常 {bot.instance_id}: {e}")
                        
                        logger.info(f"🎉 子 Bot 启动完成: {started_count} 成功, {failed_count} 失败")
                        logger.info("🔥 终极保证: 主 Bot + 所有子 Bot 已全部正常运行！")
                        
                except Exception as e:
                    logger.error(f"⚠️ 自动启动子 Bot 时出错: {e}")
                    # 不阻断主程序运行
            
            # 在应用启动后执行（使用 post_init 钩子）
            # 🔥 关键：保存原始的 post_init，然后在 start_all_sub_bots 中调用
            original_post_init = application.post_init
            
            async def combined_post_init(application):
                """组合 post_init：先执行原始的，再启动子 Bot"""
                # 1. 先执行原始的 post_init（初始化数据库等）
                if original_post_init:
                    await original_post_init(application)
                
                # 2. 再启动子 Bot
                await start_all_sub_bots(application)
            
            application.post_init = combined_post_init
            logger.info("🔥 已注册子 Bot 自动启动（终极永久方案）")
            
        except Exception as e:
            logger.error(f"Error setting up child bots auto-start: {e}", exc_info=True)
    
    # 运行机器人（Polling 模式）
    logger.info("Starting bot in polling mode...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=-1,
        poll_interval=0.5,
        timeout=5,
        read_timeout=12,
        write_timeout=12,
        connect_timeout=20,
        pool_timeout=20,
    )


if __name__ == "__main__":
    main()
