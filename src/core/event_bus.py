"""
事件总线系统（Event Bus）

职责：
1. 发布事件（GROUP_CREATED, BOT_CREATED, PERMISSION_CHANGED等）
2. 订阅事件
3. 异步处理事件
4. 支持事件持久化（可选）
5. 🆕 集成 Event Pipeline Protection Layer
"""
import asyncio
import logging
from typing import Callable, Awaitable, Dict, List, Any
from datetime import datetime
from enum import Enum

from .event_pipeline import event_pipeline, EventPriority

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """事件类型枚举"""
    # Bot 相关事件
    BOT_CREATED = "bot_created"
    BOT_STARTED = "bot_started"
    BOT_STOPPED = "bot_stopped"
    BOT_REMOVED = "bot_removed"
    BOT_SYNCED = "bot_synced"
    
    # 群组相关事件
    GROUP_CREATED = "group_created"
    GROUP_UPDATED = "group_updated"
    GROUP_REMOVED = "group_removed"
    GROUP_STATUS_CHANGED = "group_status_changed"
    
    # 🆕 分组相关事件
    GROUP_TAG_CREATED = "group_tag_created"        # 分组创建
    GROUP_TAG_DELETED = "group_tag_deleted"        # 分组删除
    GROUP_BOUND_TO_TAG = "group_bound_to_tag"      # 群组绑定到分组
    GROUP_UNBOUND_FROM_TAG = "group_unbound_from_tag"  # 群组从分组解绑
    
    # 权限相关事件
    PERMISSION_CHANGED = "permission_changed"
    ADMIN_ADDED = "admin_added"
    ADMIN_REMOVED = "admin_removed"
    
    # 版本相关事件
    VERSION_UPDATED = "version_updated"
    
    # 其他事件
    PAYMENT_RECEIVED = "payment_received"
    SUBSCRIPTION_EXPIRED = "subscription_expired"


class Event:
    """事件对象"""
    
    def __init__(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        bot_id: str = None,
        root_bot_id: str = None,
        timestamp: datetime = None
    ):
        self.event_type = event_type
        self.data = data
        self.bot_id = bot_id
        self.root_bot_id = root_bot_id
        self.timestamp = timestamp or datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'event_type': self.event_type,
            'data': self.data,
            'bot_id': self.bot_id,
            'root_bot_id': self.root_bot_id,
            'timestamp': self.timestamp.isoformat()
        }


class EventBus:
    """
    事件总线
    
    支持：
    1. 发布/订阅模式
    2. 全局事件和 Bot 特定事件
    3. 异步事件处理
    """
    
    def __init__(self):
        # 事件处理器：{event_type: [handler1, handler2, ...]}
        self.handlers: Dict[EventType, List[Callable[[Event], Awaitable[None]]]] = {}
        
        # Bot 特定事件处理器：{bot_id: {event_type: [handler1, ...]}}
        self.bot_specific_handlers: Dict[str, Dict[EventType, List[Callable[[Event], Awaitable[None]]]]] = {}
        
        # 事件历史（用于调试）
        self.event_history: List[Event] = []
        self.max_history_size = 1000
    
    def subscribe(self, event_type: EventType, handler: Callable[[Event], Awaitable[None]], bot_id: str = None):
        """
        订阅事件
        
        Args:
            event_type: 事件类型
            handler: 事件处理函数，签名：async def handler(event)
            bot_id: Bot ID（可选，如果提供则只处理该 Bot 的事件）
        """
        if bot_id:
            # Bot 特定事件
            if bot_id not in self.bot_specific_handlers:
                self.bot_specific_handlers[bot_id] = {}
            
            if event_type not in self.bot_specific_handlers[bot_id]:
                self.bot_specific_handlers[bot_id][event_type] = []
            
            self.bot_specific_handlers[bot_id][event_type].append(handler)
            logger.info(f"Subscribed to {event_type} for bot {bot_id}")
        else:
            # 全局事件
            if event_type not in self.handlers:
                self.handlers[event_type] = []
            
            self.handlers[event_type].append(handler)
            logger.info(f"Subscribed to global {event_type}")
    
    async def publish(self, event: Event):
        """
        发布事件（使用 Event Pipeline）
        
        Args:
            event: 事件对象
        """
        logger.info(f"Publishing event: {event.event_type} (bot_id={event.bot_id})")
        
        # 添加到事件历史
        self.event_history.append(event)
        if len(self.event_history) > self.max_history_size:
            self.event_history.pop(0)
        
        # 🆕 使用 Event Pipeline 发布事件（异步、削峰、防阻塞）
        try:
            # 确定优先级
            priority = self._determine_priority(event.event_type)
            
            await event_pipeline.publish(
                event_type=event.event_type.value,
                data=event.to_dict(),
                bot_id=event.bot_id,
                root_bot_id=event.root_bot_id,
                priority=priority
            )
        except Exception as e:
            logger.error(f"Error publishing event to pipeline: {e}", exc_info=True)
            # 降级：直接执行处理器（保留旧逻辑作为后备）
            await self._execute_handlers_directly(event)
    
    async def _execute_handlers_directly(self, event: Event):
        """
        直接执行事件处理器（降级方案）
        
        Args:
            event: 事件对象
        """
        # 1. 触发全局事件处理器
        if event.event_type in self.handlers:
            for handler in self.handlers[event.event_type]:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"Error in global event handler for {event.event_type}: {e}", exc_info=True)
        
        # 2. 触发 Bot 特定事件处理器
        if event.bot_id and event.bot_id in self.bot_specific_handlers:
            if event.event_type in self.bot_specific_handlers[event.bot_id]:
                for handler in self.bot_specific_handlers[event.bot_id][event.event_type]:
                    try:
                        await handler(event)
                    except Exception as e:
                        logger.error(f"Error in bot-specific event handler for {event.event_type}: {e}", exc_info=True)
        
        # 3. 触发根 Bot 事件处理器（用于树状结构同步）
        if event.root_bot_id and event.root_bot_id != event.bot_id:
            if event.root_bot_id in self.bot_specific_handlers:
                if event.event_type in self.bot_specific_handlers[event.root_bot_id]:
                    for handler in self.bot_specific_handlers[event.root_bot_id][event.event_type]:
                        try:
                            await handler(event)
                        except Exception as e:
                            logger.error(f"Error in root bot event handler for {event.event_type}: {e}", exc_info=True)
    
    def _determine_priority(self, event_type: EventType) -> EventPriority:
        """
        确定事件优先级
        
        Args:
            event_type: 事件类型
            
        Returns:
            优先级
        """
        # 关键事件
        if event_type in [EventType.BOT_CREATED, EventType.BOT_REMOVED]:
            return EventPriority.CRITICAL
        
        # 高优先级事件
        if event_type in [EventType.PERMISSION_CHANGED, EventType.ADMIN_ADDED, EventType.ADMIN_REMOVED]:
            return EventPriority.HIGH
        
        # 普通事件
        return EventPriority.NORMAL
    
    async def publish_simple(self, event_type: EventType, data: Dict[str, Any], bot_id: str = None, root_bot_id: str = None):
        """
        简化版发布事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
            bot_id: Bot ID
            root_bot_id: 根 Bot ID
        """
        event = Event(
            event_type=event_type,
            data=data,
            bot_id=bot_id,
            root_bot_id=root_bot_id
        )
        await self.publish(event)
    
    def get_event_history(self, event_type: EventType = None, bot_id: str = None, limit: int = 100) -> List[Event]:
        """
        获取事件历史
        
        Args:
            event_type: 事件类型（可选）
            bot_id: Bot ID（可选）
            limit: 返回数量限制
            
        Returns:
            事件列表
        """
        filtered_events = self.event_history
        
        if event_type:
            filtered_events = [e for e in filtered_events if e.event_type == event_type]
        
        if bot_id:
            filtered_events = [e for e in filtered_events if e.bot_id == bot_id or e.root_bot_id == bot_id]
        
        return filtered_events[-limit:]


# 全局实例
event_bus = EventBus()
