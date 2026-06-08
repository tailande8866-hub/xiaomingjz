"""
Bot Recovery Engine（BOT 自愈引擎）

🔥 核心职责：自动修复所有异常状态的 BOT
🔥 修复策略：根据异常类型选择最优修复方案
🔥 安全机制：重启限流、修复冷却、失败熔断

修复类型：
  - zombie: 杀死僵尸进程 → 重启
  - registry_desync: 同步 registry 状态
  - no_heartbeat: 重启进程
  - env_invalid: 修复 .env → 重启
  - process_lost: 重新启动
"""

import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RecoveryRecord:
    """修复记录"""
    instance_id: str
    reason: str
    action: str
    success: bool
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class BotRecoveryEngine:
    """
    BOT 自愈引擎（Phase 4 强化版）
    
    🔥 修复流程：
    1. Health Score < threshold？
    2. Circuit Breaker allow？
    3. Cooldown allow？
    4. Repair Strategy select
    5. Execute repair
    6. Record result
    
    🔥 安全机制：
    - 熔断器：防止无限重启
    - 冷却机制：避免连续修复
    - 修复分级：轻/中/重三级策略
    - 健康评分：低分才修，高分观察
    """
    
    def __init__(self):
        # Phase 4: 引入稳定性控制层
        from .circuit_breaker import circuit_breaker
        from .recovery_cooldown import recovery_cooldown
        from .repair_strategy import RepairStrategySelector, repair_executor
        from .health_score import health_score_calculator
        
        self._circuit_breaker = circuit_breaker
        self._cooldown = recovery_cooldown
        self._strategy_selector = RepairStrategySelector
        self._repair_executor = repair_executor
        self._health_score = health_score_calculator
        
        # 修复历史
        self._recovery_history: list = []
        self._max_history_size = 100
        
        # 统计
        self._total_recoveries = 0
        self._successful_recoveries = 0
        self._failed_recoveries = 0
        
        # 健康评分阈值（低于此分数才修复）
        self._repair_threshold = 50
    
    async def recover(
        self,
        bot,
        reason: str,
        message: str = "",
        health_status: dict = None
    ) -> bool:
        """
        自动修复异常 BOT（Phase 4 完整流程）
        
        Args:
            bot: BotCreation 记录
            reason: 异常原因
            message: 异常描述
            health_status: 健康状态（用于计算 Health Score）
        
        Returns:
            是否修复成功
        """
        instance_id = bot.instance_id
        
        # 🔥 Phase 4-4: Health Score 检查（低分才修）
        if health_status:
            score_result = self._health_score.calculate(
                instance_id=instance_id,
                health_status=health_status
            )
            
            if not self._health_score.should_repair(instance_id, self._repair_threshold):
                logger.info(
                    f"[RecoveryEngine] ⏸️ BOT {instance_id} 健康分数 {score_result['score']}/100，"
                    f"高于阈值 {self._repair_threshold}，暂不修复，持续观察"
                )
                return True  # 返回 True 表示"无需修复"，不是错误
        
        # 🔥 Phase 4-1: Circuit Breaker 检查（熔断器）
        if not self._circuit_breaker.can_repair(instance_id):
            logger.warning(
                f"[RecoveryEngine] ⛔ BOT {instance_id} 被熔断器阻止，跳过修复"
            )
            return False
        
        # 🔥 Phase 4-2: Cooldown 检查（冷却机制）
        repair_level = self._strategy_selector.get_level(reason).value
        if not self._cooldown.allow(instance_id, repair_level=repair_level):
            logger.info(
                f"[RecoveryEngine] ⏳ BOT {instance_id} 冷却中，跳过修复"
            )
            return False
        
        # 🔥 Phase 4-3: 选择修复策略
        strategy = self._strategy_selector.get_strategy(reason)
        logger.warning(
            f"[RecoveryEngine] 🔧 开始修复 BOT {instance_id}: "
            f"reason={reason}, strategy={strategy.name}({strategy.level.name}), "
            f"cooldown={strategy.cooldown_seconds}s"
        )
        
        # 5. 执行修复
        success = False
        action = "unknown"
        
        try:
            if reason == "zombie":
                success, action = await self._recover_zombie(bot)
            elif reason == "no_heartbeat":
                success, action = await self._recover_no_heartbeat(bot)
            elif reason == "env_invalid":
                success, action = await self._recover_env_invalid(bot)
            elif reason == "registry_desync":
                success, action = await self._recover_registry_desync(bot)
            elif reason == "process_lost":
                success, action = await self._recover_process_lost(bot)
            elif reason == "crashed":
                success, action = await self._recover_crashed(bot)
            else:
                success, action = await self._recover_generic(bot)
        except Exception as e:
            logger.error(
                f"[RecoveryEngine] ❌ 修复 BOT {instance_id} 异常: {e}",
                exc_info=True
            )
            action = f"error: {e}"
        
        # 6. 记录修复结果到 Circuit Breaker
        self._circuit_breaker.record_result(instance_id, success)
        
        # 7. 记录修复历史
        self._record_recovery(instance_id, reason, action, success)
        
        if success:
            self._successful_recoveries += 1
            logger.info(f"[RecoveryEngine] ✅ BOT {instance_id} 修复成功: action={action}")
        else:
            self._failed_recoveries += 1
            logger.error(f"[RecoveryEngine] ❌ BOT {instance_id} 修复失败: action={action}")
        
        return success
    
    async def _recover_zombie(self, bot) -> tuple:
        """修复僵尸进程：杀死 → 重启"""
        instance_id = bot.instance_id
        
        # Step 1: 杀死僵尸进程
        await self._kill_process(bot.process_id)
        
        # Step 2: 清理 registry
        from .bot_instance_registry import bot_instance_registry
        bot_instance_registry.mark_stopped(instance_id)
        
        # Step 3: 等待进程完全退出
        await asyncio.sleep(2)
        
        # Step 4: 重新启动
        success = await self._restart_bot(bot)
        
        return success, "kill_zombie + restart"
    
    async def _recover_no_heartbeat(self, bot) -> tuple:
        """修复心跳超时：重启进程"""
        instance_id = bot.instance_id
        
        # Step 1: 标记为停止
        from .bot_instance_registry import bot_instance_registry
        bot_instance_registry.mark_stopping(instance_id)
        
        # Step 2: 尝试优雅终止
        await self._kill_process(bot.process_id)
        
        # Step 3: 清理
        bot_instance_registry.mark_stopped(instance_id)
        await asyncio.sleep(2)
        
        # Step 4: 重新启动
        success = await self._restart_bot(bot)
        
        return success, "kill_no_heartbeat + restart"
    
    async def _recover_env_invalid(self, bot) -> tuple:
        """修复 .env 无效：修复 .env → 重启"""
        from .env_validator import EnvAutoRepair
        from .utils.token_encryptor import token_encryptor
        
        # Step 1: 修复 .env
        try:
            decrypted_token = token_encryptor.decrypt_from_base64(bot.bot_token)
            env_ok, env_result = await EnvAutoRepair.validate_and_repair(
                instance_dir=bot.instance_dir,
                bot_token=decrypted_token,
                instance_id=bot.instance_id,
                bot_owner_id=bot.super_admin_id or 0,
                bot_username=bot.bot_username or "",
                auto_repair=True
            )
        except Exception as e:
            logger.error(f"[RecoveryEngine] .env 修复失败: {e}")
            env_ok = False
        
        if not env_ok:
            return False, "env_repair_failed"
        
        # Step 2: 如果进程在运行，需要重启以加载新 .env
        from .bot_instance_registry import bot_instance_registry
        if bot_instance_registry.is_running(bot.instance_id):
            bot_instance_registry.mark_stopping(bot.instance_id)
            await self._kill_process(bot.process_id)
            bot_instance_registry.mark_stopped(bot.instance_id)
            await asyncio.sleep(2)
            success = await self._restart_bot(bot)
            return success, "env_repaired + restart"
        
        return True, "env_repaired (no restart needed)"
    
    async def _recover_registry_desync(self, bot) -> tuple:
        """修复 Registry 不同步：同步状态"""
        from .bot_instance_registry import bot_instance_registry
        
        instance_id = bot.instance_id
        
        # 进程在运行但 registry 未标记 → 同步 registry
        if bot.process_id:
            try:
                import psutil
                if psutil.pid_exists(bot.process_id):
                    process = psutil.Process(bot.process_id)
                    # 找到运行列表中的进程对象
                    from .bot_instance_manager import bot_instance_manager
                    if instance_id in bot_instance_manager.running_processes:
                        proc_info = bot_instance_manager.running_processes[instance_id]
                        bot_instance_registry.mark_running(instance_id, proc_info['process'])
                        return True, "registry_synced"
            except Exception:
                pass
        
        # 无法同步 → 标记为需要重启
        bot_instance_registry.force_remove(instance_id)
        return False, "registry_force_removed (will restart on next check)"
    
    async def _recover_process_lost(self, bot) -> tuple:
        """修复进程丢失：重新启动"""
        from .bot_instance_registry import bot_instance_registry
        
        instance_id = bot.instance_id
        bot_instance_registry.force_remove(instance_id)
        
        await asyncio.sleep(1)
        success = await self._restart_bot(bot)
        
        return success, "restart_after_process_lost"
    
    async def _recover_crashed(self, bot) -> tuple:
        """修复崩溃：重启"""
        from .bot_instance_registry import bot_instance_registry
        
        instance_id = bot.instance_id
        bot_instance_registry.force_remove(instance_id)
        
        await asyncio.sleep(1)
        success = await self._restart_bot(bot)
        
        return success, "restart_after_crash"
    
    async def _recover_generic(self, bot) -> tuple:
        """通用修复：重启"""
        from .bot_instance_registry import bot_instance_registry
        
        instance_id = bot.instance_id
        bot_instance_registry.force_remove(instance_id)
        
        await asyncio.sleep(1)
        success = await self._restart_bot(bot)
        
        return success, "generic_restart"
    
    # ========== 辅助方法 ==========
    
    async def _kill_process(self, pid: Optional[int]):
        """杀死进程"""
        if not pid:
            return
        
        try:
            import psutil
            if not psutil.pid_exists(pid):
                return
            
            process = psutil.Process(pid)
            process.terminate()
            
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                process.kill()
                logger.warning(f"[RecoveryEngine] 进程 {pid} 未优雅退出，已强制杀死")
            
        except psutil.NoSuchProcess:
            pass  # 进程已不存在
        except Exception as e:
            logger.warning(f"[RecoveryEngine] 杀死进程 {pid} 失败: {e}")
    
    async def _restart_bot(self, bot) -> bool:
        """重启 BOT"""
        try:
            from .bot_instance_manager import bot_instance_manager
            success = await bot_instance_manager.start_bot_instance(bot)
            return success
        except Exception as e:
            logger.error(f"[RecoveryEngine] 重启 BOT {bot.instance_id} 失败: {e}")
            return False
    
    def _record_recovery(self, instance_id: str, reason: str, action: str, success: bool):
        """记录修复历史"""
        record = RecoveryRecord(
            instance_id=instance_id,
            reason=reason,
            action=action,
            success=success,
            message=f"action={action}, success={success}"
        )
        
        self._recovery_history.append(record)
        self._total_recoveries += 1
        
        # 限制历史大小
        if len(self._recovery_history) > self._max_history_size:
            self._recovery_history = self._recovery_history[-self._max_history_size:]
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'total_recoveries': self._total_recoveries,
            'successful': self._successful_recoveries,
            'failed': self._failed_recoveries,
            'success_rate': (
                f"{self._successful_recoveries / max(self._total_recoveries, 1) * 100:.1f}%"
            ),
            'history_size': len(self._recovery_history),
        }
    
    def get_recent_history(self, limit: int = 10) -> list:
        """获取最近的修复历史"""
        return self._recovery_history[-limit:]


# 🔥 全局单例
bot_recovery_engine = BotRecoveryEngine()
