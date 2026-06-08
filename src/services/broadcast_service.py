"""
Broadcast Service - 群发广播服务
"""
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Union
from telegram import Message
from telegram.ext import ContextTypes

from ..models.database import get_db_session
from ..models.group import Group
from ..services.group_tag_service import GroupTagService

logger = logging.getLogger(__name__)


class BroadcastService:
    """广播服务 - 负责向群组批量发送消息"""
    
    @staticmethod
    async def get_target_groups(
        broadcast_type: str,
        selected_groups: Optional[List[int]] = None,
        selected_broadcast_groups: Optional[List[str]] = None,
        bot_id: Optional[str] = None
    ) -> List[Group]:
        """
        获取目标群组列表
        
        Args:
            broadcast_type: 广播类型 'all' 或 'group'
            selected_groups: 手动选择的群组ID列表（用于'all'模式）
            selected_broadcast_groups: 选择的广播分组名称列表（用于'group'模式）
            bot_id: 机器人ID（用于多租户隔离）
            
        Returns:
            目标群组列表
        """
        async with get_db_session() as db:
            if broadcast_type == 'all':
                # 获取所有活跃群组
                from sqlalchemy import select
                query = select(Group).where(Group.is_active.is_(True))
                if bot_id:
                    query = query.where(Group.bot_id == bot_id)
                result = await db.execute(query)
                groups = result.scalars().all()
                
                # 如果指定了特定群组，过滤
                if selected_groups:
                    groups = [g for g in groups if g.id in selected_groups]
                    
            elif broadcast_type == 'group':
                # 获取指定广播分组下的所有活跃群组（使用新架构 GroupTag）
                groups = []
                if selected_broadcast_groups:
                    for tag_name in selected_broadcast_groups:
                        try:
                            tag_groups = await GroupTagService.get_groups_by_tag(
                                tag_name=tag_name,
                                bot_id=bot_id
                            )
                            groups.extend(tag_groups)
                        except ValueError as e:
                            logger.warning(f"Skipping invalid tag '{tag_name}': {e}")
                else:
                    # 获取所有标签下的群组
                    all_tags = await GroupTagService.get_all_tags(bot_id=bot_id)
                    for tag in all_tags:
                        try:
                            tag_groups = await GroupTagService.get_groups_by_tag(
                                tag_name=tag.tag_name,
                                bot_id=bot_id
                            )
                            groups.extend(tag_groups)
                        except ValueError as e:
                            logger.warning(f"Skipping tag '{tag.tag_name}': {e}")
            else:
                groups = []
            
            return groups
    
    @staticmethod
    async def send_broadcast(
        context: ContextTypes.DEFAULT_TYPE,
        groups: List[Group],
        message_data: Dict,
        send_mode: str = 'forward',  # 'forward' 或 'send'
        progress_callback=None
    ) -> Dict[str, int]:
        """
        发送广播消息
        
        Args:
            context: Bot上下文
            groups: 目标群组列表
            message_data: 消息数据（包含消息ID、chat_id等）
            send_mode: 发送模式 'forward'（转发）或 'send'（发送）
            progress_callback: 进度回调函数
            
        Returns:
            发送结果统计
        """
        success_count = 0
        fail_count = 0
        total = len(groups)
        
        for idx, group in enumerate(groups):
            try:
                if send_mode == 'forward' and message_data.get('forward_from_chat_id'):
                    # 转发模式
                    await context.bot.forward_message(
                        chat_id=group.group_id,
                        from_chat_id=message_data['forward_from_chat_id'],
                        message_id=message_data['forward_message_id']
                    )
                else:
                    # 发送模式
                    text = message_data.get('text', '')
                    parse_mode = message_data.get('parse_mode', 'HTML')
                    
                    await context.bot.send_message(
                        chat_id=group.group_id,
                        text=text,
                        parse_mode=parse_mode
                    )
                
                success_count += 1
                
                # 每发送100条调用一次进度回调
                if progress_callback and success_count % 100 == 0:
                    await progress_callback(success_count, total)
                    
                # 稍微延迟，避免触发Telegram限流
                if idx < total - 1:
                    await asyncio.sleep(0.05)  # 每秒约20条，Telegram API限制约30条/秒
                    
            except Exception as e:
                logger.error(f"广播到群组 {group.group_id} 失败: {str(e)}")
                fail_count += 1
                
                # 如果进度回调存在，也调用它
                if progress_callback:
                    await progress_callback(success_count + fail_count, total)
        
        return {
            'success': success_count,
            'fail': fail_count,
            'total': total
        }
    
    @staticmethod
    async def build_broadcast_summary(
        broadcast_type: str,
        selected_groups: Optional[List[int]] = None,
        selected_broadcast_groups: Optional[List[str]] = None,
        success_count: int = 0,
        fail_count: int = 0,
        total_count: int = 0
    ) -> str:
        """
        构建广播摘要消息
        
        Args:
            broadcast_type: 广播类型
            selected_groups: 选择的群组
            selected_broadcast_groups: 选择的广播分组
            success_count: 成功数量
            fail_count: 失败数量
            total_count: 总数
            
        Returns:
            摘要消息文本
        """
        message = "📡 <b>广播结果</b>\n\n"
        
        # 广播类型
        if broadcast_type == 'all':
            if selected_groups:
                message += f"广播类型：指定群组\n"
            else:
                message += f"广播类型：所有群组\n"
        elif broadcast_type == 'group':
            if selected_broadcast_groups:
                groups_str = ", ".join(selected_broadcast_groups)
                message += f"广播分组：{groups_str}\n"
            else:
                message += f"广播分组：所有分组\n"
        
        # 统计信息
        message += f"\n发送群组数量：<b>{total_count}</b>\n"
        message += f"成功：<b>{success_count}</b>\n"
        if fail_count > 0:
            message += f"失败：<b>{fail_count}</b>\n"
        
        message += f"\n发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return message
