"""
群组成员索引仓库
提供数据库操作接口，支持 @username 添加操作人功能
严格按照 bot_id + group_id + username 联合查询（多租户隔离）
"""
import logging
from typing import Optional
from datetime import datetime
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import GroupMemberIndex

logger = logging.getLogger(__name__)


class GroupMemberIndexRepo:
    """群组成员索引仓库 - 多租户隔离"""
    
    @staticmethod
    async def upsert_member(
        db: AsyncSession,
        bot_id: str,
        group_id: int,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None
    ) -> GroupMemberIndex:
        """
        插入或更新群组成员索引
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            group_id: 群组ID
            user_id: 用户ID
            username: 用户名（可选，会自动转为小写）
            first_name: 用户名字（可选）
            
        Returns:
            GroupMemberIndex: 成员索引记录
        """
        # 统一处理 username：转小写、去掉 @
        if username:
            username_lower = username.lower().lstrip('@')
        else:
            username_lower = None
        
        # 先查询是否存在（bot_id + group_id + user_id）
        query = select(GroupMemberIndex).where(
            and_(
                GroupMemberIndex.bot_id == bot_id,
                GroupMemberIndex.group_id == group_id,
                GroupMemberIndex.user_id == user_id
            )
        )
        result = await db.execute(query)
        member = result.scalar_one_or_none()
        
        if member:
            # 更新现有记录
            member.username = username_lower
            member.first_name = first_name
            member.last_seen_at = datetime.utcnow()
            logger.debug(f"更新群成员索引: bot_id={bot_id}, group_id={group_id}, user_id={user_id}")
        else:
            # 创建新记录
            member = GroupMemberIndex(
                bot_id=bot_id,
                group_id=group_id,
                user_id=user_id,
                username=username_lower,
                first_name=first_name,
                last_seen_at=datetime.utcnow(),
                created_at=datetime.utcnow()
            )
            db.add(member)
            logger.debug(f"创建群成员索引: bot_id={bot_id}, group_id={group_id}, user_id={user_id}, username={username_lower}")
        
        return member
    
    @staticmethod
    async def get_user_id_by_username(
        db: AsyncSession,
        bot_id: str,
        group_id: int,
        username: str
    ) -> Optional[int]:
        """
        通过 username 查询 user_id（严格按 bot_id + group_id + username 查询）
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            group_id: 群组ID
            username: 用户名
            
        Returns:
            Optional[int]: 用户ID，如果不存在返回 None
        """
        if not username:
            return None
        
        # 统一转为小写，去掉 @
        username_lower = username.lower().lstrip('@')
        
        # 查询（bot_id + group_id + username 联合查询）
        query = select(GroupMemberIndex).where(
            and_(
                GroupMemberIndex.bot_id == bot_id,
                GroupMemberIndex.group_id == group_id,
                GroupMemberIndex.username == username_lower
            )
        )
        result = await db.execute(query)
        member = result.scalar_one_or_none()
        
        if member:
            logger.debug(f"✅ 找到用户: @{username_lower} -> user_id={member.user_id}")
            return member.user_id
        else:
            logger.debug(f"❌ 未找到用户: bot_id={bot_id}, group_id={group_id}, username=@{username_lower}")
            return None
    
    @staticmethod
    async def get_member_info(
        db: AsyncSession,
        bot_id: str,
        group_id: int,
        username: str
    ) -> Optional[dict]:
        """
        获取完整的成员信息（包括 user_id 和 first_name）
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            group_id: 群组ID
            username: 用户名
            
        Returns:
            Optional[dict]: {user_id, first_name} 或 None
        """
        if not username:
            return None
        
        username_lower = username.lower().lstrip('@')
        
        query = select(GroupMemberIndex).where(
            and_(
                GroupMemberIndex.bot_id == bot_id,
                GroupMemberIndex.group_id == group_id,
                GroupMemberIndex.username == username_lower
            )
        )
        result = await db.execute(query)
        member = result.scalar_one_or_none()
        
        if member:
            return {
                'user_id': member.user_id,
                'first_name': member.first_name
            }
        return None
    
    @staticmethod
    async def get_username_by_user_id(
        db: AsyncSession,
        bot_id: str,
        group_id: int,
        user_id: int
    ) -> Optional[str]:
        """
        通过 user_id 查询 username（用于 @all 通知时补充缺失的 username）
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            group_id: 群组ID
            user_id: 用户ID
            
        Returns:
            Optional[str]: username（不含 @），如果不存在返回 None
        """
        query = select(GroupMemberIndex).where(
            and_(
                GroupMemberIndex.bot_id == bot_id,
                GroupMemberIndex.group_id == group_id,
                GroupMemberIndex.user_id == user_id,
                GroupMemberIndex.username != None  # 确保 username 存在
            )
        )
        result = await db.execute(query)
        member = result.scalar_one_or_none()
        
        if member and member.username:
            logger.debug(f"✅ 通过数据库补充 username: user_id={user_id} -> @{member.username}")
            return member.username
        return None
    
    @staticmethod
    async def get_all_group_members(
        db: AsyncSession,
        bot_id: str,
        group_id: int,
        limit: int = 100
    ) -> list:
        """
        获取群组所有成员列表（用于 @all 通知）
        
        Args:
            db: 数据库会话
            bot_id: 机器人实例ID
            group_id: 群组ID
            limit: 返回数量限制（Telegram 限制一条消息最多 @100 人）
            
        Returns:
            List[dict]: 成员列表，每个成员包含 {user_id, username, first_name}
        """
        query = select(GroupMemberIndex).where(
            and_(
                GroupMemberIndex.bot_id == bot_id,
                GroupMemberIndex.group_id == group_id
            )
        ).order_by(
            GroupMemberIndex.last_seen_at.desc()
        ).limit(limit)
        
        result = await db.execute(query)
        members = result.scalars().all()
        
        # 转换为字典列表
        member_list = []
        for member in members:
            member_list.append({
                'user_id': member.user_id,
                'username': member.username,
                'first_name': member.first_name
            })
        
        logger.debug(f"从数据库获取群成员: bot_id={bot_id}, group_id={group_id}, 共 {len(member_list)} 人")
        return member_list
