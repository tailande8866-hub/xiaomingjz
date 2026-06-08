"""
GroupTag 服务层 - 分组标签管理

提供 GroupTag 相关的业务逻辑封装，替代旧的 BroadcastGroupService
"""
import logging
from typing import List, Optional, Dict
from sqlalchemy import select, and_, update, func
from telegram import Bot as TelegramBot

from ..models.database import get_db_session
from ..models.group import Group, GroupTag, DEFAULT_BROADCAST_GROUP_TAG

logger = logging.getLogger(__name__)


class GroupTagService:
    """GroupTag 服务类 - 提供分组标签的核心业务逻辑"""
    
    @staticmethod
    async def ensure_default_tag(bot_id: str, created_by: int = 0) -> GroupTag:
        """
        确保默认分组标签存在（系统启动时调用）
        
        功能：
        1. 检查当前 bot_id 是否有默认分组标签
        2. 如果不存在则创建
        3. 将所有没有 group_tag 的群组分配到默认标签
        
        Args:
            bot_id: 当前 Bot ID（多租户隔离，必填）
            created_by: 创建者 Telegram ID（默认 0 表示系统创建）
            
        Returns:
            默认分组标签对象
            
        Raises:
            ValueError: 如果 bot_id 为空
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            # 1. 查找或创建默认分组标签
            query = select(GroupTag).where(
                and_(
                    GroupTag.tag_name == DEFAULT_BROADCAST_GROUP_TAG,
                    GroupTag.bot_id == bot_id,
                    GroupTag.is_active.is_(True)
                )
            )
            result = await db.execute(query)
            default_tag = result.scalar_one_or_none()
            
            if not default_tag:
                # 创建默认分组标签
                default_tag = GroupTag(
                    tag_name=DEFAULT_BROADCAST_GROUP_TAG,
                    description="系统默认分组，所有群组初始归属于此",
                    created_by=created_by,
                    bot_id=bot_id,
                    is_active=True
                )
                
                db.add(default_tag)
                await db.commit()
                await db.refresh(default_tag)
                
                logger.info(f"Created default group tag (id={default_tag.id}, bot_id={bot_id})")
            
            # 2. 将所有没有 group_tag 的群组分配到默认标签
            update_query = (
                update(Group)
                .where(
                    and_(
                        Group.group_tag.is_(None),
                        Group.bot_id == bot_id
                    )
                )
                .values(group_tag=DEFAULT_BROADCAST_GROUP_TAG)
            )
            result = await db.execute(update_query)
            
            if result.rowcount > 0:
                await db.commit()
                logger.info(
                    f"Assigned {result.rowcount} groups to default tag "
                    f"'{DEFAULT_BROADCAST_GROUP_TAG}' (bot_id={bot_id})"
                )
            
            return default_tag
    
    @staticmethod
    async def sync_group_status(bot: TelegramBot, bot_id: str) -> Dict[str, int]:
        """
        同步群组状态并清理无效群组
        
        功能：
        1. 遍历当前 bot_id 的所有群组
        2. 调用 Telegram API 验证群组是否还存在
        3. 自动同步群组名称（防止用户改名）
        4. 删除已退出的无效群组
        
        Args:
            bot: Telegram Bot 实例，用于验证群组是否存在
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            统计信息字典：
            - 'cleaned': 清理的无效群组数量
            - 'synced': 同步名称的群组数量
            - 'valid': 有效群组数量
            
        Raises:
            ValueError: 如果 bot_id 为空
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
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
                        logger.info(
                            f"Syncing group name: {group.group_id} "
                            f"'{group.group_name}' -> '{chat.title}'"
                        )
                        group.group_name = chat.title
                        synced_count += 1
                    
                    valid_count += 1
                except Exception as e:
                    logger.warning(
                        f"Cleaning invalid group: {group.group_id} "
                        f"({group.group_name}), reason: {e}"
                    )
                    await db.delete(group)
                    cleaned_count += 1
            
            await db.commit()
            
            result = {
                'cleaned': cleaned_count,
                'synced': synced_count,
                'valid': valid_count
            }
            
            logger.info(
                f"Group sync completed: valid={valid_count}, "
                f"cleaned={cleaned_count}, synced={synced_count} "
                f"(bot_id={bot_id})"
            )
            
            return result
    
    @staticmethod
    async def get_all_tags(bot_id: str, include_inactive: bool = False) -> List[GroupTag]:
        """
        获取当前 Bot 的所有分组标签
        
        Args:
            bot_id: 当前 Bot ID（多租户隔离，必填）
            include_inactive: 是否包含禁用的标签
            
        Returns:
            分组标签列表
            
        Raises:
            ValueError: 如果 bot_id 为空
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            conditions = [GroupTag.bot_id == bot_id]
            
            if not include_inactive:
                conditions.append(GroupTag.is_active.is_(True))
            
            query = select(GroupTag).where(and_(*conditions)).order_by(GroupTag.tag_name)
            result = await db.execute(query)
            
            return list(result.scalars().all())
    
    @staticmethod
    async def get_tag_by_name(tag_name: str, bot_id: str) -> Optional[GroupTag]:
        """
        根据标签名称获取分组标签
        
        Args:
            tag_name: 标签名称
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            分组标签对象，如果不存在则返回 None
            
        Raises:
            ValueError: 如果 bot_id 为空
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            query = select(GroupTag).where(
                and_(
                    GroupTag.tag_name == tag_name,
                    GroupTag.bot_id == bot_id
                )
            )
            result = await db.execute(query)
            
            return result.scalar_one_or_none()
    
    @staticmethod
    async def create_tag(
        tag_name: str,
        bot_id: str,
        created_by: int,
        description: Optional[str] = None
    ) -> GroupTag:
        """
        创建新的分组标签
        
        Args:
            tag_name: 标签名称
            bot_id: 当前 Bot ID（多租户隔离，必填）
            created_by: 创建者 Telegram ID
            description: 标签描述（可选）
            
        Returns:
            创建的分组标签对象
            
        Raises:
            ValueError: 如果 bot_id 为空或标签已存在
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            # 检查标签是否已存在
            existing = await GroupTagService.get_tag_by_name(tag_name, bot_id)
            if existing:
                raise ValueError(f"Tag '{tag_name}' already exists")
            
            # 创建新标签
            new_tag = GroupTag(
                tag_name=tag_name,
                description=description,
                created_by=created_by,
                bot_id=bot_id,
                is_active=True
            )
            
            db.add(new_tag)
            await db.commit()
            await db.refresh(new_tag)
            
            logger.info(f"Created group tag '{tag_name}' (id={new_tag.id}, bot_id={bot_id})")
            
            return new_tag
    
    @staticmethod
    async def delete_tag(tag_name: str, bot_id: str) -> bool:
        """
        删除分组标签
        
        注意：不允许删除默认标签
        
        Args:
            tag_name: 标签名称
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            是否删除成功
            
        Raises:
            ValueError: 如果尝试删除默认标签或标签不存在
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        if tag_name == DEFAULT_BROADCAST_GROUP_TAG:
            raise ValueError(f"Cannot delete default tag '{DEFAULT_BROADCAST_GROUP_TAG}'")
        
        async with get_db_session() as db:
            tag = await GroupTagService.get_tag_by_name(tag_name, bot_id)
            if not tag:
                raise ValueError(f"Tag '{tag_name}' does not exist")
            
            # 将关联的群组设置为默认标签
            default_tag = await GroupTagService.ensure_default_tag(bot_id)
            
            update_query = (
                update(Group)
                .where(
                    and_(
                        Group.group_tag == tag_name,
                        Group.bot_id == bot_id
                    )
                )
                .values(group_tag=default_tag.tag_name)
            )
            await db.execute(update_query)
            
            # 删除标签
            await db.delete(tag)
            await db.commit()
            
            logger.info(
                f"Deleted group tag '{tag_name}', groups moved to default tag"
            )
            
            return True
    
    @staticmethod
    async def assign_group_to_tag(
        group_id: int,
        tag_name: str,
        bot_id: str
    ) -> bool:
        """
        将群组分配到指定标签
        
        Args:
            group_id: Telegram 群组 ID
            tag_name: 标签名称
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            是否分配成功
            
        Raises:
            ValueError: 如果标签不存在
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            # 检查标签是否存在
            tag = await GroupTagService.get_tag_by_name(tag_name, bot_id)
            if not tag:
                raise ValueError(f"Tag '{tag_name}' does not exist")
            
            # 更新群组的 group_tag
            update_query = (
                update(Group)
                .where(
                    and_(
                        Group.group_id == group_id,
                        Group.bot_id == bot_id
                    )
                )
                .values(group_tag=tag_name)
            )
            result = await db.execute(update_query)
            await db.commit()
            
            if result.rowcount > 0:
                logger.info(
                    f"Assigned group {group_id} to tag '{tag_name}' (bot_id={bot_id})"
                )
                return True
            else:
                logger.warning(f"Group {group_id} not found")
                return False
    
    @staticmethod
    async def get_groups_by_tag(tag_name: str, bot_id: str) -> List[Group]:
        """
        获取指定标签下的所有群组
        
        Args:
            tag_name: 标签名称
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            群组列表
            
        Raises:
            ValueError: 如果标签不存在
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            # 查找标签是否存在
            tag = await GroupTagService.get_tag_by_name(tag_name, bot_id)
            if not tag:
                raise ValueError(f"Tag '{tag_name}' does not exist")
            
            # 查询该标签下的所有活跃群组
            groups_query = (
                select(Group)
                .where(
                    and_(
                        Group.group_tag == tag_name,
                        Group.is_active.is_(True),
                        Group.bot_id == bot_id
                    )
                )
                .order_by(Group.group_name)
            )
            groups_result = await db.execute(groups_query)
            return list(groups_result.scalars().all())
    
    @staticmethod
    async def get_groups_not_in_any_tag(bot_id: str) -> List[Group]:
        """
        获取不在任何标签中的群组（未分配标签的群组）
        
        Args:
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            群组列表
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            groups_query = (
                select(Group)
                .where(
                    and_(
                        Group.group_tag.is_(None),
                        Group.is_active.is_(True),
                        Group.bot_id == bot_id
                    )
                )
                .order_by(Group.group_name)
            )
            groups_result = await db.execute(groups_query)
            return list(groups_result.scalars().all())
    
    @staticmethod
    async def get_tag_stats(bot_id: str) -> Dict:
        """
        获取分组标签统计信息
        
        Args:
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            统计信息字典：
            - 'total_groups': 总群组数
            - 'default_groups': 默认标签群组数
            - 'groups_by_tag': 各标签的群组数 {tag_name: count}
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            # 获取所有活跃群组
            active_groups_query = select(Group).where(
                and_(
                    Group.is_active.is_(True),
                    Group.bot_id == bot_id
                )
            )
            active_groups_result = await db.execute(active_groups_query)
            active_groups = list(active_groups_result.scalars().all())
            
            # 按标签统计
            groups_by_tag = {}
            default_count = 0
            
            for group in active_groups:
                if group.group_tag is None:
                    # 未分配标签，计入默认标签
                    default_count += 1
                else:
                    groups_by_tag[group.group_tag] = groups_by_tag.get(group.group_tag, 0) + 1
            
            # 确保所有标签都有计数（包括 0）
            all_tags = await GroupTagService.get_all_tags(bot_id)
            for tag in all_tags:
                if tag.tag_name not in groups_by_tag:
                    groups_by_tag[tag.tag_name] = 0
            
            return {
                'total_groups': len(active_groups),
                'default_groups': default_count,
                'groups_by_tag': groups_by_tag
            }
    
    @staticmethod
    async def remove_group_from_tag(group_id: int, bot_id: str) -> bool:
        """
        从群组移除标签（设置为默认标签）
        
        Args:
            group_id: Telegram 群组 ID
            bot_id: 当前 Bot ID（多租户隔离，必填）
            
        Returns:
            是否移除成功
        """
        if not bot_id:
            raise ValueError("bot_id is required for multi-tenant isolation")
        
        async with get_db_session() as db:
            # 获取默认标签
            default_tag = await GroupTagService.ensure_default_tag(bot_id)
            
            # 更新群组的 group_tag 为默认标签
            update_query = (
                update(Group)
                .where(
                    and_(
                        Group.group_id == group_id,
                        Group.bot_id == bot_id
                    )
                )
                .values(group_tag=default_tag.tag_name)
            )
            result = await db.execute(update_query)
            await db.commit()
            
            if result.rowcount > 0:
                logger.info(
                    f"Removed tag from group {group_id}, set to default "
                    f"'{default_tag.tag_name}' (bot_id={bot_id})"
                )
                return True
            else:
                logger.warning(f"Group {group_id} not found")
                return False
