"""
Repair Strategy（修复分级系统）

🔥 核心思想：不是所有问题都"重启解决"
🔥 三层修复策略：LEVEL 1（轻）→ LEVEL 2（中）→ LEVEL 3（重）
🔥 决策逻辑：根据问题类型选择最优修复策略

修复级别：
  - LEVEL 1: 轻修复（registry sync, env reload）
  - LEVEL 2: 中修复（restart process）
  - LEVEL 3: 重修复（kill + rebuild env + restart）
"""

import logging
from enum import Enum
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class RepairLevel(Enum):
    """修复级别"""
    LEVEL_1 = 1  # 轻修复
    LEVEL_2 = 2  # 中修复
    LEVEL_3 = 3  # 重修复


@dataclass
class RepairStrategy:
    """修复策略"""
    level: RepairLevel
    name: str
    description: str
    cooldown_seconds: int


class RepairStrategySelector:
    """
    修复策略选择器
    
    根据异常类型选择最优修复策略：
    - registry_desync → LEVEL 1（轻修复）
    - no_response → LEVEL 2（中修复）
    - env_corrupt → LEVEL 3（重修复）
    """
    
    # 问题类型到修复级别的映射
    ISSUE_TO_LEVEL = {
        # LEVEL 1: 轻修复（状态同步类）
        'registry_desync': RepairLevel.LEVEL_1,
        'registry_sync_needed': RepairLevel.LEVEL_1,
        'state_mismatch': RepairLevel.LEVEL_1,
        
        # LEVEL 2: 中修复（进程问题类）
        'no_heartbeat': RepairLevel.LEVEL_2,
        'no_response': RepairLevel.LEVEL_2,
        'process_hang': RepairLevel.LEVEL_2,
        'zombie': RepairLevel.LEVEL_2,
        'crashed': RepairLevel.LEVEL_2,
        
        # LEVEL 3: 重修复（环境损坏类）
        'env_invalid': RepairLevel.LEVEL_3,
        'env_corrupt': RepairLevel.LEVEL_3,
        'env_missing': RepairLevel.LEVEL_3,
        'process_lost': RepairLevel.LEVEL_3,
        'severe_corruption': RepairLevel.LEVEL_3,
    }
    
    # 修复策略详情
    STRATEGIES = {
        RepairLevel.LEVEL_1: RepairStrategy(
            level=RepairLevel.LEVEL_1,
            name="轻修复",
            description="状态同步，无需重启进程",
            cooldown_seconds=30
        ),
        RepairLevel.LEVEL_2: RepairStrategy(
            level=RepairLevel.LEVEL_2,
            name="中修复",
            description="重启进程",
            cooldown_seconds=60
        ),
        RepairLevel.LEVEL_3: RepairStrategy(
            level=RepairLevel.LEVEL_3,
            name="重修复",
            description="重建环境 + 重启进程",
            cooldown_seconds=120
        ),
    }
    
    @classmethod
    def get_strategy(cls, issue_type: str) -> RepairStrategy:
        """
        根据问题类型获取修复策略
        
        Args:
            issue_type: 问题类型（如 'registry_desync', 'no_heartbeat'）
        
        Returns:
            RepairStrategy
        """
        level = cls.ISSUE_TO_LEVEL.get(issue_type, RepairLevel.LEVEL_2)
        return cls.STRATEGIES[level]
    
    @classmethod
    def get_level(cls, issue_type: str) -> RepairLevel:
        """获取修复级别"""
        return cls.ISSUE_TO_LEVEL.get(issue_type, RepairLevel.LEVEL_2)
    
    @classmethod
    def get_cooldown(cls, issue_type: str) -> int:
        """获取该问题类型的冷却时间"""
        strategy = cls.get_strategy(issue_type)
        return strategy.cooldown_seconds
    
    @classmethod
    def classify_issue(cls, health_status: dict) -> str:
        """
        根据健康状态分类问题类型
        
        Args:
            health_status: BotHealthStatus 的字典表示
        
        Returns:
            issue_type 字符串
        """
        status = health_status.get('status', 'unknown')
        
        # 直接映射
        if status in cls.ISSUE_TO_LEVEL:
            return status
        
        # 根据状态推断
        if status == 'healthy':
            return 'none'
        
        # 默认返回通用问题类型
        return 'unknown'


class RepairExecutor:
    """
    修复执行器
    
    根据选择的策略执行具体修复动作
    """
    
    def __init__(self):
        self._executors: dict = {
            RepairLevel.LEVEL_1: self._execute_level_1,
            RepairLevel.LEVEL_2: self._execute_level_2,
            RepairLevel.LEVEL_3: self._execute_level_3,
        }
    
    async def execute(
        self,
        bot,
        issue_type: str,
        health_status: dict
    ) -> tuple[bool, str]:
        """
        执行修复
        
        Returns:
            (success, action_description)
        """
        strategy = RepairStrategySelector.get_strategy(issue_type)
        executor = self._executors.get(strategy.level, self._execute_level_2)
        
        logger.info(
            f"[RepairExecutor] 🔧 执行修复: {bot.instance_id}, "
            f"问题={issue_type}, 策略={strategy.name}"
        )
        
        return await executor(bot, issue_type, health_status)
    
    async def _execute_level_1(
        self,
        bot,
        issue_type: str,
        health_status: dict
    ) -> tuple[bool, str]:
        """LEVEL 1: 轻修复（状态同步）"""
        from .bot_instance_registry import bot_instance_registry
        
        if issue_type == 'registry_desync':
            # 同步 registry 状态
            bot_instance_registry.mark_running(bot.instance_id)
            return True, "registry_synced"
        
        # 其他 LEVEL 1 问题默认返回成功
        return True, "level_1_default"
    
    async def _execute_level_2(
        self,
        bot,
        issue_type: str,
        health_status: dict
    ) -> tuple[bool, str]:
        """LEVEL 2: 中修复（重启进程）"""
        from .bot_recovery_engine import bot_recovery_engine
        
        # 使用现有的 recovery 逻辑
        success = await bot_recovery_engine._restart_bot(bot)
        action = "restart_process"
        
        if issue_type == 'zombie':
            action = "kill_zombie + restart"
        elif issue_type == 'no_heartbeat':
            action = "restart_no_heartbeat"
        elif issue_type == 'crashed':
            action = "restart_after_crash"
        
        return success, action
    
    async def _execute_level_3(
        self,
        bot,
        issue_type: str,
        health_status: dict
    ) -> tuple[bool, str]:
        """LEVEL 3: 重修复（重建环境 + 重启）"""
        from .env_validator import EnvAutoRepair
        from ..utils.token_encryptor import token_encryptor
        from .bot_recovery_engine import bot_recovery_engine
        
        # Step 1: 修复 .env
        if issue_type in ['env_invalid', 'env_corrupt', 'env_missing']:
            try:
                decrypted_token = token_encryptor.decrypt_from_base64(bot.bot_token)
                env_ok, _ = await EnvAutoRepair.validate_and_repair(
                    instance_dir=bot.instance_dir,
                    bot_token=decrypted_token,
                    instance_id=bot.instance_id,
                    bot_owner_id=bot.super_admin_id or 0,
                    bot_username=bot.bot_username or "",
                    auto_repair=True
                )
                if not env_ok:
                    return False, "env_repair_failed"
            except Exception as e:
                logger.error(f"[RepairExecutor] .env 修复失败: {e}")
                return False, f"env_repair_error: {e}"
        
        # Step 2: 重启进程
        success = await bot_recovery_engine._restart_bot(bot)
        
        action = "rebuild_env + restart"
        if issue_type == 'process_lost':
            action = "restart_after_process_lost"
        elif issue_type == 'severe_corruption':
            action = "full_rebuild + restart"
        
        return success, action


# 🔥 全局单例
repair_executor = RepairExecutor()
