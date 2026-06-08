"""
BOT 实例注册表（启动幂等控制）

🔥 防止 BOT 被重复启动
🔥 防止 runtime 重复注册
🔥 强制单例：一个 instance_id 只能有一个运行中的进程

使用方式：
    # 启动前检查
    if not BotInstanceRegistry.can_start(instance_id):
        logger.warning(f"BOT {instance_id} 已在运行中，跳过")
        return
    
    # 标记为启动中
    BotInstanceRegistry.mark_starting(instance_id, process_id)
    
    try:
        # 启动 BOT...
        BotInstanceRegistry.mark_running(instance_id, process)
    except Exception:
        BotInstanceRegistry.mark_failed(instance_id, error)
        raise
    finally:
        # 停止时
        BotInstanceRegistry.mark_stopped(instance_id)
"""

import threading
import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class BotInstanceState:
    """BOT 实例状态"""
    instance_id: str
    status: str  # 'starting', 'running', 'stopping', 'stopped', 'failed'
    process_id: Optional[int] = None
    process_obj: Optional[Any] = None  # subprocess.Popen 对象
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    error_message: Optional[str] = None
    restart_count: int = 0
    last_restart_at: Optional[datetime] = None


class BotInstanceRegistry:
    """
    BOT 实例注册表（线程安全单例）
    
    核心职责：
    1. 防止重复启动（幂等控制）
    2. 追踪运行状态
    3. 提供进程查找（通过 instance_id 找 process）
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._registry: Dict[str, BotInstanceState] = {}
        self._registry_lock = threading.RLock()
        self._initialized = True
        
        logger.info("[BotInstanceRegistry] ✅ 初始化完成")
    
    def can_start(self, instance_id: str) -> bool:
        """
        检查是否可以启动该 BOT
        
        返回 True 当且仅当：
        - 该 instance_id 从未被注册过，或
        - 该 instance_id 当前状态为 'stopped' 或 'failed'
        """
        with self._registry_lock:
            if instance_id not in self._registry:
                return True
            
            state = self._registry[instance_id]
            
            # 已停止或失败的可以重新启动
            if state.status in ('stopped', 'failed'):
                logger.info(f"[BotInstanceRegistry] BOT {instance_id} 状态为 {state.status}，允许重新启动")
                return True
            
            # 正在运行或启动中的，禁止重复启动
            if state.status in ('starting', 'running'):
                # 额外检查进程是否真的存在
                if state.process_obj and hasattr(state.process_obj, 'poll'):
                    if state.process_obj.poll() is None:
                        logger.warning(
                            f"[BotInstanceRegistry] ❌ BOT {instance_id} 已在运行中 "
                            f"(PID={state.process_id}, 状态={state.status})，禁止重复启动"
                        )
                        return False
                    else:
                        # 进程已退出但状态未更新
                        logger.warning(
                            f"[BotInstanceRegistry] ⚠️ BOT {instance_id} 进程已退出但状态为 {state.status}，"
                            f"自动标记为 stopped 并允许重新启动"
                        )
                        self._mark_stopped_internal(instance_id)
                        return True
                
                logger.warning(
                    f"[BotInstanceRegistry] ❌ BOT {instance_id} 状态为 {state.status}，"
                    f"禁止重复启动"
                )
                return False
            
            # 正在停止的，等待完全停止后再启动
            if state.status == 'stopping':
                logger.warning(
                    f"[BotInstanceRegistry] ❌ BOT {instance_id} 正在停止中，"
                    f"请等待完全停止后再启动"
                )
                return False
            
            return True
    
    def mark_starting(self, instance_id: str, process_id: int = None) -> bool:
        """
        标记 BOT 为启动中状态
        
        返回 True 表示成功标记，False 表示无法启动（已在运行中）
        """
        if not self.can_start(instance_id):
            return False
        
        with self._registry_lock:
            state = BotInstanceState(
                instance_id=instance_id,
                status='starting',
                process_id=process_id,
                started_at=datetime.now()
            )
            self._registry[instance_id] = state
            
            logger.info(
                f"[BotInstanceRegistry] 🚀 BOT {instance_id} 标记为 starting "
                f"(PID={process_id})"
            )
            return True
    
    def mark_running(self, instance_id: str, process_obj: Any) -> bool:
        """
        标记 BOT 为运行中状态
        
        Args:
            process_obj: subprocess.Popen 对象
        """
        with self._registry_lock:
            if instance_id not in self._registry:
                logger.error(
                    f"[BotInstanceRegistry] ❌ 无法标记 running："
                    f"BOT {instance_id} 未在注册表中"
                )
                return False
            
            state = self._registry[instance_id]
            
            if state.status != 'starting':
                logger.warning(
                    f"[BotInstanceRegistry] ⚠️ BOT {instance_id} 状态为 {state.status}，"
                    f"预期为 starting"
                )
            
            state.status = 'running'
            state.process_obj = process_obj
            
            if process_obj and hasattr(process_obj, 'pid'):
                state.process_id = process_obj.pid
            
            logger.info(
                f"[BotInstanceRegistry] ✅ BOT {instance_id} 标记为 running "
                f"(PID={state.process_id})"
            )
            return True
    
    def mark_stopping(self, instance_id: str) -> bool:
        """标记 BOT 为停止中状态"""
        with self._registry_lock:
            if instance_id not in self._registry:
                logger.warning(
                    f"[BotInstanceRegistry] ⚠️ 无法标记 stopping："
                    f"BOT {instance_id} 未在注册表中"
                )
                return False
            
            state = self._registry[instance_id]
            state.status = 'stopping'
            
            logger.info(f"[BotInstanceRegistry] 🛑 BOT {instance_id} 标记为 stopping")
            return True
    
    def mark_stopped(self, instance_id: str) -> bool:
        """标记 BOT 为已停止状态"""
        return self._mark_stopped_internal(instance_id)
    
    def _mark_stopped_internal(self, instance_id: str) -> bool:
        """内部方法：标记为已停止"""
        with self._registry_lock:
            if instance_id not in self._registry:
                return False
            
            state = self._registry[instance_id]
            state.status = 'stopped'
            state.stopped_at = datetime.now()
            state.process_obj = None
            
            logger.info(
                f"[BotInstanceRegistry] ⏹️ BOT {instance_id} 标记为 stopped "
                f"(运行时长: {state.stopped_at - state.started_at if state.started_at else 'N/A'})"
            )
            return True
    
    def mark_failed(self, instance_id: str, error_message: str) -> bool:
        """标记 BOT 为失败状态"""
        with self._registry_lock:
            if instance_id not in self._registry:
                # 为失败的 BOT 创建记录
                state = BotInstanceState(
                    instance_id=instance_id,
                    status='failed',
                    error_message=error_message,
                    stopped_at=datetime.now()
                )
                self._registry[instance_id] = state
            else:
                state = self._registry[instance_id]
                state.status = 'failed'
                state.error_message = error_message
                state.stopped_at = datetime.now()
                state.process_obj = None
            
            logger.error(
                f"[BotInstanceRegistry] 💥 BOT {instance_id} 标记为 failed: {error_message}"
            )
            return True
    
    def record_restart(self, instance_id: str) -> int:
        """记录重启次数"""
        with self._registry_lock:
            if instance_id not in self._registry:
                return 0
            
            state = self._registry[instance_id]
            state.restart_count += 1
            state.last_restart_at = datetime.now()
            
            return state.restart_count
    
    def get_state(self, instance_id: str) -> Optional[BotInstanceState]:
        """获取 BOT 状态"""
        with self._registry_lock:
            return self._registry.get(instance_id)
    
    def get_running_instances(self) -> Dict[str, BotInstanceState]:
        """获取所有运行中的实例"""
        with self._registry_lock:
            return {
                k: v for k, v in self._registry.items()
                if v.status in ('starting', 'running')
            }
    
    def get_process(self, instance_id: str) -> Optional[Any]:
        """获取 BOT 进程对象"""
        with self._registry_lock:
            state = self._registry.get(instance_id)
            if state and state.status == 'running':
                return state.process_obj
            return None
    
    def is_running(self, instance_id: str) -> bool:
        """检查 BOT 是否正在运行"""
        with self._registry_lock:
            if instance_id not in self._registry:
                return False
            
            state = self._registry[instance_id]
            
            if state.status != 'running':
                return False
            
            # 额外验证进程是否真的存在
            if state.process_obj and hasattr(state.process_obj, 'poll'):
                return state.process_obj.poll() is None
            
            return True
    
    def force_remove(self, instance_id: str) -> bool:
        """
        强制从注册表中移除（慎用）
        
        用于清理僵尸状态或手动干预场景
        """
        with self._registry_lock:
            if instance_id in self._registry:
                del self._registry[instance_id]
                logger.warning(
                    f"[BotInstanceRegistry] ⚠️ BOT {instance_id} 被强制从注册表移除"
                )
                return True
            return False
    
    def get_stats(self) -> dict:
        """获取注册表统计信息"""
        with self._registry_lock:
            stats = {
                'total': len(self._registry),
                'starting': sum(1 for s in self._registry.values() if s.status == 'starting'),
                'running': sum(1 for s in self._registry.values() if s.status == 'running'),
                'stopping': sum(1 for s in self._registry.values() if s.status == 'stopping'),
                'stopped': sum(1 for s in self._registry.values() if s.status == 'stopped'),
                'failed': sum(1 for s in self._registry.values() if s.status == 'failed'),
            }
            return stats


# 🔥 全局单例
bot_instance_registry = BotInstanceRegistry()
