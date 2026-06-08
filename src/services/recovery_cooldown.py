"""
Recovery Cooldown（修复冷却机制）

🔥 核心职责：防止同一个 BOT 被连续重启
🔥 冷却规则：两次 recovery 间隔 ≥ 60 秒
🔥 作用：避免频繁修复导致的系统抖动
"""

import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CooldownRecord:
    """冷却记录"""
    instance_id: str
    last_recovery_time: float
    recovery_count: int = 0


class RecoveryCooldown:
    """
    修复冷却管理器
    
    防止同一个 BOT 在短时间内被多次修复：
    - 默认冷却时间：60 秒
    - 可配置不同级别的冷却时间
    """
    
    # 冷却时间配置（秒）
    DEFAULT_COOLDOWN = 60           # 默认冷却：60 秒
    LEVEL_1_COOLDOWN = 30           # 轻修复冷却：30 秒
    LEVEL_2_COOLDOWN = 60           # 中修复冷却：60 秒
    LEVEL_3_COOLDOWN = 120          # 重修复冷却：120 秒
    
    def __init__(self):
        self._records: Dict[str, CooldownRecord] = {}
        self._total_blocked = 0
        self._total_allowed = 0
    
    def allow(
        self,
        instance_id: str,
        repair_level: int = 2,
        custom_cooldown: Optional[int] = None
    ) -> bool:
        """
        检查是否允许修复（冷却检查）
        
        Args:
            instance_id: BOT 实例 ID
            repair_level: 修复级别（1=轻，2=中，3=重）
            custom_cooldown: 自定义冷却时间（秒），覆盖默认配置
        
        Returns:
            True = 冷却结束，允许修复
            False = 冷却中，禁止修复
        """
        now = time.time()
        
        # 确定冷却时间
        if custom_cooldown is not None:
            cooldown = custom_cooldown
        elif repair_level == 1:
            cooldown = self.LEVEL_1_COOLDOWN
        elif repair_level == 2:
            cooldown = self.LEVEL_2_COOLDOWN
        elif repair_level == 3:
            cooldown = self.LEVEL_3_COOLDOWN
        else:
            cooldown = self.DEFAULT_COOLDOWN
        
        # 获取或创建记录
        if instance_id not in self._records:
            self._records[instance_id] = CooldownRecord(
                instance_id=instance_id,
                last_recovery_time=0,
                recovery_count=0
            )
        
        record = self._records[instance_id]
        
        # 检查冷却
        time_since_last = now - record.last_recovery_time
        
        if record.last_recovery_time > 0 and time_since_last < cooldown:
            remaining = int(cooldown - time_since_last)
            self._total_blocked += 1
            logger.warning(
                f"[RecoveryCooldown] ⏳ {instance_id} 冷却中，"
                f"剩余 {remaining}s（级别 {repair_level}，冷却 {cooldown}s）"
            )
            return False
        
        # 允许修复，更新时间
        record.last_recovery_time = now
        record.recovery_count += 1
        self._total_allowed += 1
        
        if record.recovery_count > 1:
            logger.info(
                f"[RecoveryCooldown] ✅ {instance_id} 冷却结束，"
                f"允许第 {record.recovery_count} 次修复 "
                f"（距上次 {int(time_since_last)}s）"
            )
        else:
            logger.info(
                f"[RecoveryCooldown] ✅ {instance_id} 首次修复，无需冷却"
            )
        
        return True
    
    def get_remaining_cooldown(self, instance_id: str, repair_level: int = 2) -> int:
        """
        获取剩余冷却时间
        
        Returns:
            剩余冷却秒数，0 表示冷却结束
        """
        if instance_id not in self._records:
            return 0
        
        record = self._records[instance_id]
        
        if repair_level == 1:
            cooldown = self.LEVEL_1_COOLDOWN
        elif repair_level == 2:
            cooldown = self.LEVEL_2_COOLDOWN
        elif repair_level == 3:
            cooldown = self.LEVEL_3_COOLDOWN
        else:
            cooldown = self.DEFAULT_COOLDOWN
        
        now = time.time()
        remaining = cooldown - (now - record.last_recovery_time)
        
        return max(0, int(remaining))
    
    def reset(self, instance_id: str):
        """重置冷却记录（用于手动干预）"""
        if instance_id in self._records:
            self._records[instance_id].last_recovery_time = 0
            logger.info(f"[RecoveryCooldown] 🔄 {instance_id} 冷却记录已重置")
    
    def get_record(self, instance_id: str) -> Optional[CooldownRecord]:
        """获取冷却记录（只读）"""
        return self._records.get(instance_id)
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'total_monitored': len(self._records),
            'total_allowed': self._total_allowed,
            'total_blocked': self._total_blocked,
            'block_rate': (
                f"{self._total_blocked / max(self._total_allowed + self._total_blocked, 1) * 100:.1f}%"
            ),
        }


# 🔥 全局单例
recovery_cooldown = RecoveryCooldown()
