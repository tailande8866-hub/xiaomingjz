"""
分组管理事件监听器

职责：
1. 监听分组相关事件（创建、删除、绑定）
2. 通知私聊端刷新 UI Schema 页面
3. 保证多 Bot 数据隔离
"""
import logging
from typing import Dict, Any

from ..core.event_bus import EventBus, Event, EventType
from ..core.ui_renderer import ui_renderer

logger = logging.getLogger(__name__)


class GroupTagEventListener:
    """分组管理事件监听器"""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._register_handlers()
    
    def _register_handlers(self):
        """注册事件处理器"""
        
        # 监听分组创建事件
        self.event_bus.subscribe(
            EventType.GROUP_TAG_CREATED,
            self._on_group_tag_created
        )
        
        # 监听分组删除事件
        self.event_bus.subscribe(
            EventType.GROUP_TAG_DELETED,
            self._on_group_tag_deleted
        )
        
        # 监听群组绑定到分组事件
        self.event_bus.subscribe(
            EventType.GROUP_BOUND_TO_TAG,
            self._on_group_bound_to_tag
        )
        
        # 监听群组从分组解绑事件
        self.event_bus.subscribe(
            EventType.GROUP_UNBOUND_FROM_TAG,
            self._on_group_unbound_from_tag
        )
        
        logger.info("✅ GroupTagEventListener registered")
    
    async def _on_group_tag_created(self, event: Event):
        """处理分组创建事件"""
        bot_id = event.data.get("bot_id")
        tag_name = event.data.get("tag_name")
        
        logger.info(f"[Bot: {bot_id}] Group tag created: {tag_name}")
        
        # 刷新该 Bot 下所有打开"分组管理"页面的用户
        await self._refresh_group_manage_pages(bot_id)
    
    async def _on_group_tag_deleted(self, event: Event):
        """处理分组删除事件"""
        bot_id = event.data.get("bot_id")
        tag_name = event.data.get("tag_name")
        
        logger.info(f"[Bot: {bot_id}] Group tag deleted: {tag_name}")
        
        # 刷新该 Bot 下所有打开"分组管理"页面的用户
        await self._refresh_group_manage_pages(bot_id)
    
    async def _on_group_bound_to_tag(self, event: Event):
        """处理群组绑定到分组事件"""
        bot_id = event.data.get("bot_id")
        group_id = event.data.get("group_id")
        tag_name = event.data.get("tag_name")
        
        logger.info(f"[Bot: {bot_id}] Group {group_id} bound to tag: {tag_name}")
        
        # 刷新该 Bot 下所有打开"分组管理"页面的用户
        await self._refresh_group_manage_pages(bot_id)
    
    async def _on_group_unbound_from_tag(self, event: Event):
        """处理群组从分组解绑事件"""
        bot_id = event.data.get("bot_id")
        group_id = event.data.get("group_id")
        
        logger.info(f"[Bot: {bot_id}] Group {group_id} unbound from tag")
        
        # 刷新该 Bot 下所有打开"分组管理"页面的用户
        await self._refresh_group_manage_pages(bot_id)
    
    async def _refresh_group_manage_pages(self, bot_id: str):
        """
        刷新指定 Bot 下所有打开"分组管理"页面的用户
        
        Args:
            bot_id: Bot ID
        """
        try:
            # 获取该 Bot 下所有活跃用户（这里简化处理，实际可能需要维护一个活跃用户列表）
            # 由于当前架构没有维护活跃用户列表，我们采用被动刷新策略：
            # 当用户下次访问"分组管理"页面时，会自动获取最新数据
            
            # TODO: 如果需要主动推送，可以维护一个 active_users 字典
            # active_users = ui_renderer.get_active_users(bot_id, page="group_manage")
            # for user_id in active_users:
            #     await ui_renderer.refresh_page(bot_id, user_id, "group_manage")
            
            logger.debug(f"[Bot: {bot_id}] Group manage pages will be refreshed on next access")
            
        except Exception as e:
            logger.error(f"[Bot: {bot_id}] Failed to refresh group manage pages: {e}", exc_info=True)


# 全局事件监听器实例
group_tag_event_listener = None


def init_group_tag_event_listener(event_bus: EventBus):
    """
    初始化分组管理事件监听器
    
    Args:
        event_bus: 事件总线实例
    """
    global group_tag_event_listener
    if group_tag_event_listener is None:
        group_tag_event_listener = GroupTagEventListener(event_bus)
        logger.info("GroupTagEventListener initialized")
    
    return group_tag_event_listener
