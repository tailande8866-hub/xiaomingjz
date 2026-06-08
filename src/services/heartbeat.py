"""
心跳上报系统（Heartbeat System）

🔥 每个 BOT 实例定时上报心跳
🔥 Watchdog 通过心跳判断 BOT 是否存活/卡死
🔥 上报内容：状态、内存、CPU、消息处理量

心跳状态：
  - alive: 正常
  - busy: 高负载
  - degraded: 降级运行
  - shutting_down: 正在关闭
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class HeartbeatReporter:
    """
    心跳上报器
    
    每个 BOT 进程启动后创建一个实例，
    定时向数据库写入心跳记录。
    """
    
    def __init__(self, bot_id: str, interval: int = 30):
        """
        Args:
            bot_id: BOT 实例 ID
            interval: 上报间隔（秒）
        """
        self.bot_id = bot_id
        self.interval = interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._pid = os.getpid()
        self._start_time = time.time()
    
    async def start(self):
        """启动心跳上报"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"[Heartbeat] 🔥 心跳上报已启动: bot={self.bot_id}, interval={self.interval}s")
    
    async def stop(self):
        """停止心跳上报"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"[Heartbeat] ⏹️ 心跳上报已停止: bot={self.bot_id}")
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        # 首次延迟 5 秒再开始上报（等待 BOT 完全初始化）
        await asyncio.sleep(5)
        
        while self._running:
            try:
                await self._report()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Heartbeat] 上报失败: {e}")
            
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
    
    async def _report(self):
        """执行一次心跳上报"""
        from ..models.database import get_db_session
        from ..models.saas_auto import BotCreation
        from sqlalchemy import select
        
        now = datetime.utcnow()
        
        # 收集系统信息
        memory_mb = 0
        cpu_percent = 0.0
        
        try:
            import psutil
            proc = psutil.Process(self._pid)
            memory_mb = proc.memory_info().rss / 1024 / 1024
            cpu_percent = proc.cpu_percent(interval=0.1)
        except ImportError:
            pass
        except Exception:
            pass
        
        # 计算运行时长
        uptime_seconds = int(time.time() - self._start_time)
        
        # 判断状态
        status = "alive"
        if memory_mb > 500:  # 内存超过 500MB
            status = "busy"
        if cpu_percent > 80:  # CPU 超过 80%
            status = "busy"
        
        # 写入数据库
        try:
            async with get_db_session() as db:
                query = select(BotCreation).where(
                    BotCreation.instance_id == self.bot_id
                )
                result = await db.execute(query)
                bot = result.scalar_one_or_none()
                
                if bot:
                    bot.last_heartbeat = now
                    # 可以扩展更多字段
                    await db.commit()
        except Exception as e:
            logger.debug(f"[Heartbeat] DB 更新失败: {e}")
        
        logger.debug(
            f"[Heartbeat] 💓 bot={self.bot_id}, status={status}, "
            f"mem={memory_mb:.1f}MB, cpu={cpu_percent:.1f}%, "
            f"uptime={uptime_seconds}s"
        )


def create_heartbeat_task(bot_id: str, interval: int = 30) -> HeartbeatReporter:
    """
    创建心跳上报器（便捷函数）
    
    Args:
        bot_id: BOT 实例 ID
        interval: 上报间隔（秒）
    
    Returns:
        HeartbeatReporter 实例
    """
    return HeartbeatReporter(bot_id=bot_id, interval=interval)
