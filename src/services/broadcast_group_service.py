"""
Broadcast Group Service - 广播分组管理服务

⚠️ DEPRECATED - 此服务已废弃，请使用 GroupTagService 替代

迁移状态：
- ✅ initialize_default_group() → GroupTagService.ensure_default_tag()
- ✅ clean_invalid_groups() → GroupTagService.sync_group_status()
- ✅ get_all_groups() → GroupTagService.get_all_tags()
- ✅ get_groups_by_broadcast() → GroupTagService.get_groups_by_tag()
- ✅ get_group_stats() → GroupTagService.get_tag_stats()

保留原因：
- 仅用于向后兼容，不应在新代码中使用
- 未来版本将完全移除此文件

提供广播分组的 CRUD 操作和统计功能
"""
import logging
from typing import List, Optional, Dict
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from ..models.database import get_db_session
from ..models.broadcast_group import BroadcastGroup
from ..models.group import Group

logger = logging.getLogger(__name__)


class BroadcastGroupService:
    """广播分组管理服务"""
    
    @staticmethod
    async def create_broadcast_group(
        name: str,
        created_by: int,
        bot_id: str,
        description: Optional[str] = None
    ) -> BroadcastGroup:
        """
        创建广播分组
        
        Args:
            name: 分组名称
            created_by: 创建者 Telegram ID
            bot_id: 当前 Bot ID（多租户隔离）
            description: 分组描述
            
        Returns:
            创建的 BroadcastGroup 对象
        """
        from ..models.group import DEFAULT_BROADCAST_GROUP_TAG
        
        async with get_db_session() as db:
            # 检查是否为默认分组名称
            if name == DEFAULT_BROADCAST_GROUP_TAG:
                raise ValueError(f"'{DEFAULT_BROADCAST_GROUP_TAG}' 是系统默认分组，不允许创建")
            
            # ✅ 检查同一 Bot 内名称是否已存在（多租户隔离）
            query = select(BroadcastGroup).where(
                (BroadcastGroup.name == name) &
                (BroadcastGroup.bot_id == bot_id)
            )
            result = await db.execute(query)
            existing = result.scalar_one_or_none()
            
            if existing:
                raise ValueError(f"分组 '{name}' 已存在")
            
            # 创建新分组
            broadcast_group = BroadcastGroup(
                name=name,
                description=description,
                created_by=created_by,
                bot_id=bot_id  # ✅ 绑定 bot_id
            )
            
            db.add(broadcast_group)
            await db.commit()
            await db.refresh(broadcast_group)
            
            logger.info(f"Created broadcast group '{name}' by user {created_by}")
            return broadcast_group
    
    @staticmethod
    async def delete_broadcast_group(name: str, bot_id: str) -> bool:
        """
        删除广播分组
        
        Args:
            name: 分组名称
            bot_id: 当前 Bot ID（多租户隔离）
            
        Returns:
            是否删除成功
        """
        from ..models.group import DEFAULT_BROADCAST_GROUP_TAG
        
        async with get_db_session() as db:
            # 检查是否为默认分组
            if name == DEFAULT_BROADCAST_GROUP_TAG:
                raise ValueError(f"'{DEFAULT_BROADCAST_GROUP_TAG}' 是系统默认分组，不允许删除")
            
            # ✅ 查找当前 Bot 的分组（多租户隔离）
            query = select(BroadcastGroup).where(
                (BroadcastGroup.name == name) &
                (BroadcastGroup.bot_id == bot_id)
            )
            result = await db.execute(query)
            broadcast_group = result.scalar_one_or_none()
            
            if not broadcast_group:
                raise ValueError(f"分组 '{name}' 不存在")
            
            # 获取默认分组
            default_group = await BroadcastGroupService.get_or_create_default_group(bot_id=bot_id)
            
            # 将关联的群组设置为默认分组
            update_query = (
                Group.__table__
                .update()
                .where(Group.broadcast_group_id == broadcast_group.id)
                .values(broadcast_group_id=default_group.id)
            )
            await db.execute(update_query)
            
            # 删除分组
            await db.delete(broadcast_group)
            await db.commit()
            
            logger.info(f"Deleted broadcast group '{name}', groups moved to default")
            return True
    
    @staticmethod
    async def get_all_groups(bot_id: str) -> List[BroadcastGroup]:
        """
        获取当前 Bot 的所有广播分组
        
        Args:
            bot_id: 当前 Bot ID（多租户隔离）
        
        Returns:
            广播分组列表
        """
        async with get_db_session() as db:
            # ✅ 只返回当前 Bot 的分组（多租户隔离）
            query = select(BroadcastGroup).where(
                BroadcastGroup.bot_id == bot_id
            ).order_by(BroadcastGroup.created_at.desc())
            result = await db.execute(query)
            return result.scalars().all()
    
    @staticmethod
    async def get_group_stats(bot_id: str = None) -> Dict:
        """
        获取广播分组统计信息
        
        Args:
            bot_id: 当前机器人的 bot_id，用于过滤群组（防止多 Bot 数据混杂）
        
        Returns:
            统计信息字典
        """
        async with get_db_session() as db:
            # ✅ 构建 bot_id 过滤条件（支持多租户隔离）
            if bot_id:
                bot_filter = (Group.bot_id == bot_id) | (Group.bot_id == None)
            else:
                bot_filter = True  # 如果没有提供 bot_id，则不过滤
            
            # ✅ 获取所有活跃且属于当前 Bot 的群组
            active_groups_query = select(Group).where(
                (Group.is_active.is_(True)) & bot_filter
            )
            active_groups_result = await db.execute(active_groups_query)
            active_groups = active_groups_result.scalars().all()
            
            # ✅ 按分组统计
            groups_by_broadcast = {}
            default_count = 0
            
            for group in active_groups:
                if group.broadcast_group_id is None:
                    # 未分配分组，计入默认分组
                    default_count += 1
                else:
                    # 已分配分组，需要查询对应的广播分组名称
                    bg_query = select(BroadcastGroup).where(BroadcastGroup.id == group.broadcast_group_id)
                    bg_result = await db.execute(bg_query)
                    bg = bg_result.scalar_one_or_none()
                    if bg:
                        groups_by_broadcast[bg.name] = groups_by_broadcast.get(bg.name, 0) + 1
            
            # ✅ 确保所有当前 Bot 的广播分组都有计数（包括 0）
            all_groups_query = select(BroadcastGroup).where(
                BroadcastGroup.bot_id == bot_id
            )
            all_groups_result = await db.execute(all_groups_query)
            all_broadcast_groups = all_groups_result.scalars().all()
            
            for bg in all_broadcast_groups:
                if bg.name not in groups_by_broadcast:
                    groups_by_broadcast[bg.name] = 0
            
            return {
                'total_groups': len(active_groups),
                'default_groups': default_count,
                'groups_by_broadcast': groups_by_broadcast
            }
    
    @staticmethod
    async def get_groups_by_broadcast(broadcast_group_name: str, bot_id: str) -> List[Group]:
        """
        获取指定广播分组下的所有群组
        
        Args:
            broadcast_group_name: 广播分组名称
            bot_id: 当前 Bot ID（多租户隔离）
            
        Returns:
            群组列表
        """
        async with get_db_session() as db:
            # ✅ 查找当前 Bot 的广播分组（多租户隔离）
            bg_query = select(BroadcastGroup).where(
                (BroadcastGroup.name == broadcast_group_name) &
                (BroadcastGroup.bot_id == bot_id)
            )
            bg_result = await db.execute(bg_query)
            broadcast_group = bg_result.scalar_one_or_none()
            
            if not broadcast_group:
                raise ValueError(f"广播分组 '{broadcast_group_name}' 不存在")
            
            # 查询该分组下的所有群组（只返回有效群组且属于当前 Bot）
            groups_query = (
                select(Group)
                .where(
                    (Group.broadcast_group_id == broadcast_group.id) &
                    (Group.is_active.is_(True)) &
                    ((Group.bot_id == bot_id) | (Group.bot_id == None))  # ✅ 租户隔离
                )
                .order_by(Group.group_name)
            )
            groups_result = await db.execute(groups_query)
            return groups_result.scalars().all()
    
    @staticmethod
    async def get_groups_not_in_broadcast(bot_id: str) -> List[Group]:
        """
        获取不在任何广播分组中的群组
        
        Args:
            bot_id: 当前 Bot ID（多租户隔离）
        
        Returns:
            群组列表
        """
        async with get_db_session() as db:
            groups_query = (
                select(Group)
                .where(
                    (Group.broadcast_group_id.is_(None)) &
                    (Group.is_active.is_(True)) &
                    ((Group.bot_id == bot_id) | (Group.bot_id == None))  # ✅ 租户隔离
                )
                .order_by(Group.group_name)
            )
            groups_result = await db.execute(groups_query)
            return groups_result.scalars().all()
    
    @staticmethod
    async def get_group_by_name(name: str, bot_id: str) -> Optional[BroadcastGroup]:
        """
        根据名称获取广播分组
        
        Args:
            name: 分组名称
            bot_id: 当前 Bot ID（多租户隔离）
            
        Returns:
            BroadcastGroup 对象或 None
        """
        async with get_db_session() as db:
            # ✅ 只查询当前 Bot 的分组（多租户隔离）
            query = select(BroadcastGroup).where(
                (BroadcastGroup.name == name) &
                (BroadcastGroup.bot_id == bot_id)
            )
            result = await db.execute(query)
            return result.scalar_one_or_none()
    
    @staticmethod
    async def get_group_by_id(group_id: int) -> Optional[BroadcastGroup]:
        """
        根据 ID 获取广播分组
        
        Args:
            group_id: 分组 ID
            
        Returns:
            BroadcastGroup 对象或 None
        """
        async with get_db_session() as db:
            query = select(BroadcastGroup).where(BroadcastGroup.id == group_id)
            result = await db.execute(query)
            return result.scalar_one_or_none()
    
    @staticmethod
    async def assign_group_to_broadcast(
        group_id: int,
        broadcast_group_name: str,
        bot_id: str
    ) -> bool:
        """
        将群组分配到广播分组
        
        Args:
            group_id: 群组 ID
            broadcast_group_name: 广播分组名称
            bot_id: 当前 Bot ID（多租户隔离）
            
        Returns:
            是否分配成功
        """
        async with get_db_session() as db:
            # ✅ 查找当前 Bot 的广播分组（多租户隔离）
            bg_query = select(BroadcastGroup).where(
                (BroadcastGroup.name == broadcast_group_name) &
                (BroadcastGroup.bot_id == bot_id)
            )
            bg_result = await db.execute(bg_query)
            broadcast_group = bg_result.scalar_one_or_none()
            
            if not broadcast_group:
                raise ValueError(f"广播分组 '{broadcast_group_name}' 不存在")
            
            # 更新群组的广播分组 ID
            update_query = (
                Group.__table__
                .update()
                .where(Group.id == group_id)
                .values(broadcast_group_id=broadcast_group.id)
            )
            await db.execute(update_query)
            await db.commit()
            
            logger.info(f"Assigned group {group_id} to broadcast group '{broadcast_group_name}'")
            return True
    
    @staticmethod
    async def remove_group_from_broadcast(group_id: int, bot_id: str) -> bool:
        """
        从广播分组中移除群组（放回默认分组）
        
        Args:
            group_id: 群组 ID
            bot_id: 当前 Bot ID（多租户隔离）
            
        Returns:
            是否移除成功
        """
        async with get_db_session() as db:
            # 获取或创建默认分组
            default_group = await BroadcastGroupService.get_or_create_default_group(bot_id=bot_id)
            
            # 将群组的广播分组 ID 设置为默认分组 ID
            update_query = (
                Group.__table__
                .update()
                .where(Group.id == group_id)
                .values(broadcast_group_id=default_group.id)
            )
            await db.execute(update_query)
            await db.commit()
            
            logger.info(f"Removed group {group_id} from broadcast group, assigned to default group")
            return True
    
    @staticmethod
    async def get_or_create_default_group(created_by: int = 0, bot_id: str = None) -> BroadcastGroup:
        """
        获取或创建默认广播分组
        
        Args:
            created_by: 创建者 Telegram ID（默认 0 表示系统创建）
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            默认广播分组对象
        """
        from ..models.group import DEFAULT_BROADCAST_GROUP_TAG
        
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            # ✅ 查找当前 Bot 的默认分组（多租户隔离）
            query = select(BroadcastGroup).where(
                (BroadcastGroup.name == DEFAULT_BROADCAST_GROUP_TAG) &
                (BroadcastGroup.bot_id == bot_id)
            )
            result = await db.execute(query)
            default_group = result.scalar_one_or_none()
            
            if not default_group:
                # 创建当前 Bot 的默认分组
                default_group = BroadcastGroup(
                    name=DEFAULT_BROADCAST_GROUP_TAG,
                    description="系统默认分组，所有群组初始归属于此",
                    created_by=created_by,
                    bot_id=bot_id  # ✅ 绑定 bot_id
                )
                
                db.add(default_group)
                await db.commit()
                await db.refresh(default_group)
                
                logger.info(f"Created default broadcast group (id={default_group.id})")
            
            return default_group
    
    @staticmethod
    async def initialize_default_group(created_by: int = 0, bot_id: str = None) -> BroadcastGroup:
        """
        初始化默认分组（系统启动时调用）
        将所有没有分组的群组分配到默认分组
        
        Args:
            created_by: 创建者 Telegram ID
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            默认广播分组对象
        """
        from ..models.group import DEFAULT_BROADCAST_GROUP_TAG
        
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            # 获取或创建当前 Bot 的默认分组
            default_group = await BroadcastGroupService.get_or_create_default_group(created_by, bot_id=bot_id)
            
            # ✅ 将当前 Bot 中没有分组的群组分配到默认分组
            update_query = (
                Group.__table__
                .update()
                .where(
                    (Group.broadcast_group_id.is_(None)) &
                    ((Group.bot_id == bot_id) | (Group.bot_id == None))
                )
                .values(broadcast_group_id=default_group.id)
            )
            result = await db.execute(update_query)
            
            if result.rowcount > 0:
                await db.commit()
                logger.info(f"Assigned {result.rowcount} groups to default broadcast group")
            
            return default_group
    
    @staticmethod
    async def clean_invalid_groups(bot) -> Dict[str, int]:
        """
        清理无效的群组记录（Telegram 中不存在的群组）
        
        Args:
            bot: Telegram Bot 实例，用于验证群组是否存在
            
        Returns:
            统计信息字典：{'cleaned': 清理数量, 'synced': 同步名称数量, 'valid': 有效数量}
        """
        from ..utils.bot_id_middleware import get_current_bot_id_from_bot
        
        # 获取当前机器人的 bot_id
        bot_id = get_current_bot_id_from_bot(bot)
        
        async with get_db_session() as db:
            # 查询当前机器人的所有群组
            groups_query = select(Group).where(Group.bot_id == bot_id)
            groups_result = await db.execute(groups_query)
            all_groups = list(groups_result.scalars().all())
            
            cleaned_count = 0
            synced_count = 0
            valid_count = 0
            
            for group in all_groups:
                try:
                    # 调用 Telegram API 验证群组是否还存在
                    chat = await bot.get_chat(group.group_id)
                    
                    # 自动同步群组名称（防止用户改名）
                    if chat.title != group.group_name:
                        logger.info(f"同步群组名称: {group.group_id} '{group.group_name}' -> '{chat.title}'")
                        group.group_name = chat.title
                        synced_count += 1
                    
                    valid_count += 1
                except Exception as e:
                    logger.warning(f"自动清理无效群组: {group.group_id} ({group.group_name}), 原因: {e}")
                    await db.delete(group)
                    cleaned_count += 1
            
            await db.commit()
            
            result = {
                'cleaned': cleaned_count,
                'synced': synced_count,
                'valid': valid_count
            }
            
            logger.info(
                f"群组清理完成: 有效={valid_count}, "
                f"清理={cleaned_count}, 同步名称={synced_count}"
            )
            
            return result
