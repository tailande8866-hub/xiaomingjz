"""
Circuit Breaker（熔断器）

🔥 核心职责：防止无限重启、失败循环、watchdog 误触发灾难恢复
🔥 状态模型：CLOSED → OPEN → HALF → CLOSED
🔥 安全机制：连续失败达到阈值后熔断，冷却期后试探恢复

状态说明：
  - CLOSED: 正常状态，允许修复
  - OPEN:   熔断状态，禁止修复（连续失败达到阈值）
  - HALF:   半开状态，允许一次试探修复
"""

import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常，允许修复
    OPEN = "open"          # 熔断，禁止修复
    HALF_OPEN = "half"     # 半开，试探修复


@dataclass
class CircuitBreakerState:
    """单个 BOT 的熔断器状态"""
    instance_id: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    opened_at: Optional[float] = None
    half_open_attempts: int = 0


class CircuitBreaker:
    """
    熔断器
    
    防止同一个 BOT 被无限重启：
    1. 连续失败达到阈值 → 熔断（OPEN）
    2. 熔断期间禁止修复
    3. 冷却期后进入半开（HALF）
    4. 半开状态下允许一次试探修复
    5. 试探成功 → 关闭（CLOSED）
    6. 试探失败 → 重新熔断（OPEN）
    """
    
    # 配置参数
    FAILURE_THRESHOLD = 5           # 连续失败阈值
    SUCCESS_THRESHOLD = 2           # 连续成功阈值（半开状态）
    OPEN_DURATION = 300             # 熔断持续时间（秒）
    HALF_OPEN_MAX_ATTEMPTS = 3      # 半开状态最大尝试次数
    
    def __init__(self):
        self._states: Dict[str, CircuitBreakerState] = {}
        self._total_opens = 0
        self._total_half_opens = 0
        self._total_closes = 0
    
    def can_repair(self, instance_id: str) -> bool:
        """
        检查是否允许修复该 BOT
        
        Returns:
            True = 允许修复
            False = 熔断中，禁止修复
        """
        state = self._get_state(instance_id)
        now = time.time()
        
        if state.state == CircuitState.CLOSED:
            # 正常状态，允许修复
            return True
        
        elif state.state == CircuitState.OPEN:
            # 熔断状态，检查是否已过冷却期
            if state.opened_at and (now - state.opened_at) >= self.OPEN_DURATION:
                # 冷却期结束，进入半开状态
                logger.info(
                    f"[CircuitBreaker] 🔓 {instance_id} 熔断冷却结束，进入半开状态"
                )
                state.state = CircuitState.HALF_OPEN
                state.half_open_attempts = 0
                self._total_half_opens += 1
                return True
            else:
                # 仍在熔断中
                remaining = int(self.OPEN_DURATION - (now - state.opened_at))
                logger.warning(
                    f"[CircuitBreaker] ⛔ {instance_id} 熔断中，剩余 {remaining}s，禁止修复"
                )
                return False
        
        elif state.state == CircuitState.HALF_OPEN:
            # 半开状态，允许试探修复，但限制尝试次数
            if state.half_open_attempts >= self.HALF_OPEN_MAX_ATTEMPTS:
                logger.warning(
                    f"[CircuitBreaker] ⛔ {instance_id} 半开尝试次数耗尽，重新熔断"
                )
                self._open_circuit(state)
                return False
            
            state.half_open_attempts += 1
            logger.info(
                f"[CircuitBreaker] 🔍 {instance_id} 半开试探修复 "
                f"({state.half_open_attempts}/{self.HALF_OPEN_MAX_ATTEMPTS})"
            )
            return True
        
        return True
    
    def record_success(self, instance_id: str):
        """记录修复成功"""
        state = self._get_state(instance_id)
        now = time.time()
        
        state.success_count += 1
        state.last_success_time = now
        
        if state.state == CircuitState.HALF_OPEN:
            # 半开状态连续成功达到阈值 → 关闭熔断
            if state.success_count >= self.SUCCESS_THRESHOLD:
                logger.info(
                    f"[CircuitBreaker] ✅ {instance_id} 半开状态修复成功，关闭熔断"
                )
                self._close_circuit(state)
        
        elif state.state == CircuitState.CLOSED:
            # 正常状态，重置失败计数
            if state.failure_count > 0:
                logger.debug(
                    f"[CircuitBreaker] {instance_id} 修复成功，重置失败计数"
                )
                state.failure_count = 0
    
    def record_failure(self, instance_id: str, reason: str = ""):
        """记录修复失败"""
        state = self._get_state(instance_id)
        now = time.time()
        
        state.failure_count += 1
        state.last_failure_time = now
        
        if state.state == CircuitState.HALF_OPEN:
            # 半开状态失败 → 重新熔断
            logger.warning(
                f"[CircuitBreaker] 💥 {instance_id} 半开试探失败，重新熔断: {reason}"
            )
            self._open_circuit(state)
        
        elif state.state == CircuitState.CLOSED:
            # 正常状态连续失败达到阈值 → 熔断
            if state.failure_count >= self.FAILURE_THRESHOLD:
                logger.error(
                    f"[CircuitBreaker] 🔥 {instance_id} 连续失败 {state.failure_count} 次，"
                    f"触发熔断: {reason}"
                )
                self._open_circuit(state)
    
    def force_open(self, instance_id: str, reason: str = ""):
        """强制熔断（用于手动干预）"""
        state = self._get_state(instance_id)
        logger.warning(
            f"[CircuitBreaker] 🚫 {instance_id} 被强制熔断: {reason}"
        )
        self._open_circuit(state)
    
    def force_close(self, instance_id: str):
        """强制关闭熔断（用于手动恢复）"""
        state = self._get_state(instance_id)
        logger.info(
            f"[CircuitBreaker] 🔓 {instance_id} 被强制关闭熔断"
        )
        self._close_circuit(state)
    
    def _get_state(self, instance_id: str) -> CircuitBreakerState:
        """获取或创建状态对象"""
        if instance_id not in self._states:
            self._states[instance_id] = CircuitBreakerState(instance_id=instance_id)
        return self._states[instance_id]
    
    def _open_circuit(self, state: CircuitBreakerState):
        """打开熔断"""
        state.state = CircuitState.OPEN
        state.opened_at = time.time()
        state.half_open_attempts = 0
        self._total_opens += 1
    
    def _close_circuit(self, state: CircuitBreakerState):
        """关闭熔断"""
        state.state = CircuitState.CLOSED
        state.failure_count = 0
        state.success_count = 0
        state.opened_at = None
        state.half_open_attempts = 0
        self._total_closes += 1
    
    def get_state(self, instance_id: str) -> Optional[CircuitBreakerState]:
        """获取状态（外部只读）"""
        return self._states.get(instance_id)
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        states = list(self._states.values())
        
        return {
            'total_monitored': len(states),
            'closed': sum(1 for s in states if s.state == CircuitState.CLOSED),
            'open': sum(1 for s in states if s.state == CircuitState.OPEN),
            'half_open': sum(1 for s in states if s.state == CircuitState.HALF_OPEN),
            'total_opens': self._total_opens,
            'total_half_opens': self._total_half_opens,
            'total_closes': self._total_closes,
        }


# 🔥 全局单例
circuit_breaker = CircuitBreaker()
