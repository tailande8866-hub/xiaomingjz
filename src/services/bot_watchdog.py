"""
Bot Watchdog（BOT 看门狗系统）

🔥 核心职责：监控所有 BOT 实例的健康状态
🔥 检测能力：僵尸进程、假运行、状态漂移、心跳丢失
🔥 与 BotRecoveryEngine 配合实现自动修复

检测类型：
  - zombie: registry 标记运行但进程已死
  - registry_desync: 进程在运行但 registry 未标记
  - no_heartbeat: 进程存活但心跳超时（可能卡死）
  - env_invalid: .env 文件验证失败
  - process_lost: 数据库标记运行但进程不存在
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BotHealthStatus:
    """BOT 健康状态"""
    instance_id: str
    is_healthy: bool
    status: str  # 'healthy', 'zombie', 'no_heartbeat', 'crashed', 'env_invalid', 'unknown'
    process_alive: bool
    registry_running: bool
    heartbeat_ok: bool
    env_valid: bool
    health_score: int  # 0-100
    message: str
    checked_at: datetime = field(default_factory=datetime.utcnow)
    pid: Optional[int] = None


class BotWatchdog:
    """
    BOT 看门狗
    
    统一监控所有 BOT 实例的健康状态，
    发现异常后调用 BotRecoveryEngine 进行自动修复。
    """
    
    def __init__(self):
        self._check_interval = 30  # 检查间隔（秒）
        self._heartbeat_timeout = 90  # 心跳超时（秒）
        self._last_check_results: Dict[str, BotHealthStatus] = {}
        self._check_count = 0
        self._anomaly_count = 0
    
    async def check_all_bots(self) -> Dict[str, BotHealthStatus]:
        """
        检查所有 BOT 实例的健康状态
        
        Returns:
            {instance_id: BotHealthStatus}
        """
        from .bot_instance_registry import bot_instance_registry
        from ..models.database import get_db_session
        from ..models.saas_auto import BotCreation, BotLifecycleStatus
        from sqlalchemy import select, and_
        
        self._check_count += 1
        results = {}
        
        try:
            async with get_db_session() as db:
                # 查询所有活跃的子 BOT
                query = select(BotCreation).where(
                    and_(
                        BotCreation.lifecycle_status == BotLifecycleStatus.ACTIVE,
                        BotCreation.instance_id != 'main_bot',
                        BotCreation.instance_dir.isnot(None)
                    )
                )
                result = await db.execute(query)
                bots = result.scalars().all()
                
                for bot in bots:
                    try:
                        health = await self.check_bot(bot)
                        results[bot.instance_id] = health
                        
                        # 🔥 发现异常 → 自动修复
                        if not health.is_healthy:
                            self._anomaly_count += 1
                            await self._trigger_recovery(bot, health)
                    except Exception as e:
                        logger.error(f"[Watchdog] 检查 BOT {bot.instance_id} 异常: {e}")
                        results[bot.instance_id] = BotHealthStatus(
                            instance_id=bot.instance_id,
                            is_healthy=False,
                            status='unknown',
                            process_alive=False,
                            registry_running=False,
                            heartbeat_ok=False,
                            env_valid=False,
                            health_score=0,
                            message=f"Check error: {e}"
                        )
            
            self._last_check_results = results
            
            # 统计日志
            healthy = sum(1 for r in results.values() if r.is_healthy)
            total = len(results)
            if total > 0:
                logger.info(
                    f"[Watchdog] 第 {self._check_count} 次巡检完成: "
                    f"总计 {total}, 健康 {healthy}, 异常 {total - healthy}"
                )
            
            return results
            
        except Exception as e:
            logger.error(f"[Watchdog] check_all_bots 异常: {e}", exc_info=True)
            return results
    
    async def check_bot(self, bot) -> BotHealthStatus:
        """
        检查单个 BOT 的健康状态
        
        检测维度：
        1. Registry 状态 vs 进程状态（是否一致）
        2. 进程是否真实存在
        3. 心跳是否超时
        4. .env 文件是否有效
        """
        from .bot_instance_registry import bot_instance_registry
        from .env_validator import EnvValidator
        
        instance_id = bot.instance_id
        pid = bot.process_id
        
        # 1. 检查 Registry 状态
        registry_running = bot_instance_registry.is_running(instance_id)
        
        # 2. 检查进程是否真实存在
        process_alive = self._check_process_alive(pid)
        
        # 3. 检查心跳
        heartbeat_ok = await self._check_heartbeat(bot)
        
        # 4. 检查 .env 文件
        env_valid = self._check_env_valid(bot)
        
        # 综合判断
        health_score = 100
        status = 'healthy'
        message = 'Running normally'
        is_healthy = True
        
        # ❌ 检测：僵尸进程（registry 标记运行但进程已死）
        if registry_running and not process_alive:
            status = 'zombie'
            health_score = 20
            message = f'僵尸进程: registry=running, process=dead (PID={pid})'
            is_healthy = False
        
        # ❌ 检测：Registry 不同步（进程在运行但 registry 未标记）
        elif process_alive and not registry_running:
            status = 'registry_desync'
            health_score = 50
            message = f'Registry 不同步: process=alive, registry=not_running'
            is_healthy = False
        
        # ❌ 检测：心跳超时（进程存活但无响应）
        elif process_alive and registry_running and not heartbeat_ok:
            status = 'no_heartbeat'
            health_score = 30
            message = f'心跳超时: 进程存活但无响应 (> {self._heartbeat_timeout}s)'
            is_healthy = False
        
        # ❌ 检测：.env 文件无效
        if not env_valid:
            if is_healthy:
                # .env 无效但进程正常 → 降低健康度
                health_score = 60
                status = 'env_invalid'
                message = '.env 文件验证失败（进程暂时正常）'
                is_healthy = True  # 进程还在跑，暂不标记为不健康
            else:
                # .env 无效且进程异常 → 双重问题
                health_score = min(health_score, 10)
                message += ' + .env 无效'
        
        # ❌ 检测：进程丢失（数据库标记运行但进程不存在且不在 registry）
        if not process_alive and not registry_running and bot.status == 'running':
            status = 'process_lost'
            health_score = 0
            message = f'进程丢失: 数据库状态={bot.status}, 但进程不存在'
            is_healthy = False
        
        return BotHealthStatus(
            instance_id=instance_id,
            is_healthy=is_healthy,
            status=status,
            process_alive=process_alive,
            registry_running=registry_running,
            heartbeat_ok=heartbeat_ok,
            env_valid=env_valid,
            health_score=health_score,
            message=message,
            pid=pid
        )
    
    def _check_process_alive(self, pid: Optional[int]) -> bool:
        """检查进程是否真实存在"""
        if not pid:
            return False
        
        try:
            import psutil
            return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
        except (ImportError, psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    async def _check_heartbeat(self, bot) -> bool:
        """检查心跳是否正常"""
        if not bot.last_heartbeat:
            return True  # 首次检查，没有心跳记录
        
        now = datetime.utcnow()
        heartbeat_age = (now - bot.last_heartbeat).total_seconds()
        
        return heartbeat_age <= self._heartbeat_timeout
    
    def _check_env_valid(self, bot) -> bool:
        """检查 .env 文件是否有效"""
        if not bot.instance_dir:
            return True  # 没有目录，跳过检查
        
        try:
            from .env_validator import EnvValidator
            from pathlib import Path
            
            env_path = Path(bot.instance_dir) / ".env"
            if not env_path.exists():
                return False
            
            result = EnvValidator.validate_env(
                env_path=str(env_path),
                expected_bot_owner_id=bot.super_admin_id or 0,
                expected_instance_id=bot.instance_id
            )
            return result.is_valid
        except Exception:
            return True  # 检查失败不标记为无效
    
    async def _trigger_recovery(self, bot, health: BotHealthStatus):
        """触发自动修复"""
        try:
            from .bot_recovery_engine import bot_recovery_engine
            await bot_recovery_engine.recover(bot, health.status, health.message)
        except Exception as e:
            logger.error(f"[Watchdog] 触发修复失败: {e}", exc_info=True)
    
    def get_stats(self) -> dict:
        """获取 Watchdog 统计信息"""
        last_results = self._last_check_results
        
        return {
            'total_checks': self._check_count,
            'total_anomalies': self._anomaly_count,
            'last_check_bots': len(last_results),
            'last_check_healthy': sum(1 for r in last_results.values() if r.is_healthy),
            'last_check_unhealthy': sum(1 for r in last_results.values() if not r.is_healthy),
        }


# 🔥 全局单例
bot_watchdog = BotWatchdog()
