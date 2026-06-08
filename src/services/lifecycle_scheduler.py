"""
Bot 生命周期管理定时任务调度器

职责：
1. 每小时检查一次 Bot 到期状态
2. 自动转换生命周期状态
3. 记录日志和统计信息
"""
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..services.bot_lifecycle_manager import bot_lifecycle_manager

logger = logging.getLogger(__name__)


class LifecycleScheduler:
    """生命周期管理调度器"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
    
    async def run_lifecycle_check(self):
        """执行生命周期检查（被调度器调用）"""
        logger.info("⏰ Scheduled lifecycle check started...")
        
        try:
            start_time = datetime.utcnow()
            
            # 执行生命周期检查
            await bot_lifecycle_manager.check_and_update_lifecycle()
            
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            logger.info(f"✅ Scheduled lifecycle check completed in {duration:.2f}s")
            
        except Exception as e:
            logger.error(f"❌ Error in scheduled lifecycle check: {e}", exc_info=True)
    
    def start(self):
        """启动调度器"""
        logger.info("🚀 Starting lifecycle management scheduler...")
        
        # 每小时执行一次生命周期检查
        self.scheduler.add_job(
            self.run_lifecycle_check,
            trigger='interval',
            hours=1,
            id='lifecycle_check',
            name='Bot Lifecycle Status Check',
            replace_existing=True
        )
        
        # 启动调度器
        self.scheduler.start()
        
        logger.info("✅ Lifecycle scheduler started (runs every hour)")
    
    def stop(self):
        """停止调度器"""
        logger.info("🛑 Stopping lifecycle scheduler...")
        self.scheduler.shutdown()
        logger.info("✅ Lifecycle scheduler stopped")


# 全局实例
lifecycle_scheduler = LifecycleScheduler()
