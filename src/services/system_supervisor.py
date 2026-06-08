"""
System Supervisor（系统总控）

🔥 统一调度：Watchdog + Recovery Engine + Heartbeat + Registry
🔥 主循环：定时巡检所有 BOT，发现异常自动修复
🔥 启动入口：主 BOT 的 _post_init 中启动

架构：
    SystemSupervisor
        ├── BotWatchdog（巡检）
        ├── BotRecoveryEngine（修复）
        ├── HeartbeatReporter（心跳上报 - 主BOT自身）
        └── BotInstanceRegistry（状态管理）
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class SystemSupervisor:
    """
    系统总控
    
    职责：
    1. 启动时初始化所有子系统
    2. 定时巡检所有 BOT
    3. 发现异常触发自动修复
    4. 上报主 BOT 自身心跳
    5. 提供系统健康状态查询
    """
    
    def __init__(
        self,
        watchdog_interval: int = 30,      # 巡检间隔（秒）
        heartbeat_interval: int = 30,      # 心跳间隔（秒）
        stats_interval: int = 300,         # 统计上报间隔（秒）
    ):
        self.watchdog_interval = watchdog_interval
        self.heartbeat_interval = heartbeat_interval
        self.stats_interval = stats_interval
        
        self._running = False
        self._watchdog_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None
        self._started_at: Optional[datetime] = None
    
    async def start(self):
        """启动系统总控"""
        if self._running:
            logger.warning("[Supervisor] 已经在运行中")
            return
        
        self._running = True
        self._started_at = datetime.utcnow()
        
        logger.info("=" * 60)
        logger.info("🚀 [SystemSupervisor] 系统总控启动")
        logger.info(f"   巡检间隔: {self.watchdog_interval}s")
        logger.info(f"   心跳间隔: {self.heartbeat_interval}s")
        logger.info(f"   统计间隔: {self.stats_interval}s")
        logger.info("=" * 60)
        
        # 启动子系统
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        self._heartbeat_task = asyncio.create_task(self._main_bot_heartbeat_loop())
        self._stats_task = asyncio.create_task(self._stats_loop())
        
        # 首次立即巡检一次
        try:
            await self._run_watchdog_check()
        except Exception as e:
            logger.error(f"[Supervisor] 首次巡检失败: {e}")
    
    async def stop(self):
        """停止系统总控"""
        self._running = False
        
        for task in [self._watchdog_task, self._heartbeat_task, self._stats_task]:
            if task:
                task.cancel()
        
        await asyncio.gather(
            *filter(None, [self._watchdog_task, self._heartbeat_task, self._stats_task]),
            return_exceptions=True
        )
        
        logger.info("[Supervisor] ⏹️ 系统总控已停止")
    
    async def _watchdog_loop(self):
        """Watchdog 巡检循环"""
        # 首次延迟 10 秒（等待子 BOT 启动完成）
        await asyncio.sleep(10)
        
        while self._running:
            try:
                await self._run_watchdog_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Supervisor] 巡检异常: {e}", exc_info=True)
            
            try:
                await asyncio.sleep(self.watchdog_interval)
            except asyncio.CancelledError:
                break
    
    async def _run_watchdog_check(self):
        """执行一次巡检"""
        from .bot_watchdog import bot_watchdog
        
        results = await bot_watchdog.check_all_bots()
        
        # 记录异常
        unhealthy = {k: v for k, v in results.items() if not v.is_healthy}
        if unhealthy:
            for instance_id, health in unhealthy.items():
                logger.warning(
                    f"[Supervisor] ⚠️ 异常 BOT: {instance_id}, "
                    f"status={health.status}, message={health.message}"
                )
    
    async def _main_bot_heartbeat_loop(self):
        """主 BOT 自身心跳上报循环"""
        await asyncio.sleep(5)
        
        while self._running:
            try:
                await self._report_main_bot_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[Supervisor] 主 BOT 心跳上报失败: {e}")
            
            try:
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
    
    async def _report_main_bot_heartbeat(self):
        """上报主 BOT 心跳"""
        from ..models.database import get_db_session
        from ..models.saas_auto import BotCreation
        from sqlalchemy import select
        
        now = datetime.utcnow()
        
        try:
            async with get_db_session() as db:
                query = select(BotCreation).where(
                    BotCreation.instance_id == 'main_bot'
                )
                result = await db.execute(query)
                main_bot = result.scalar_one_or_none()
                
                if main_bot:
                    main_bot.last_heartbeat = now
                    await db.commit()
        except Exception as e:
            logger.debug(f"[Supervisor] 主 BOT 心跳 DB 更新失败: {e}")
    
    async def _stats_loop(self):
        """统计信息上报循环"""
        await asyncio.sleep(60)  # 首次延迟 60 秒
        
        while self._running:
            try:
                self._log_system_stats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Supervisor] 统计上报异常: {e}")
            
            try:
                await asyncio.sleep(self.stats_interval)
            except asyncio.CancelledError:
                break
    
    def _log_system_stats(self):
        """记录系统统计信息"""
        from .bot_watchdog import bot_watchdog
        from .bot_recovery_engine import bot_recovery_engine
        from .bot_instance_registry import bot_instance_registry
        
        watchdog_stats = bot_watchdog.get_stats()
        recovery_stats = bot_recovery_engine.get_stats()
        registry_stats = bot_instance_registry.get_stats()
        
        uptime = "N/A"
        if self._started_at:
            uptime_seconds = (datetime.utcnow() - self._started_at).total_seconds()
            hours = int(uptime_seconds // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            uptime = f"{hours}h {minutes}m"
        
        logger.info(
            f"[Supervisor] 📊 系统状态 | "
            f"运行时长: {uptime} | "
            f"巡检: {watchdog_stats['total_checks']}次, "
            f"异常: {watchdog_stats['total_anomalies']}次 | "
            f"修复: {recovery_stats['total_recoveries']}次 "
            f"(成功率: {recovery_stats['success_rate']}) | "
            f"Registry: {registry_stats}"
        )
    
    def get_system_health(self) -> dict:
        """获取系统整体健康状态"""
        from .bot_watchdog import bot_watchdog
        from .bot_recovery_engine import bot_recovery_engine
        from .bot_instance_registry import bot_instance_registry
        
        return {
            'supervisor_running': self._running,
            'uptime_seconds': (
                (datetime.utcnow() - self._started_at).total_seconds()
                if self._started_at else 0
            ),
            'watchdog': bot_watchdog.get_stats(),
            'recovery': bot_recovery_engine.get_stats(),
            'registry': bot_instance_registry.get_stats(),
        }


# 🔥 全局单例
system_supervisor = SystemSupervisor()
