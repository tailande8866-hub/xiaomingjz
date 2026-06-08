"""
自定义关键词回复服务 - 支持私聊和群组两种配置方式
"""
import logging
from typing import Optional, List, Dict
from sqlalchemy import select, and_, delete, update
from telegram import Update

from ..models import CustomKeyword, get_db_session
from ..utils.bot_id_middleware import get_current_bot_id

logger = logging.getLogger(__name__)


class CustomKeywordService:
    """自定义关键词回复服务"""
    
    @staticmethod
    async def add_keyword(
        bot_id: str,
        keyword: str,
        reply_text: str,
        group_id: int = 0,
        created_by: int = 0
    ) -> bool:
        """
        添加关键词
        
        Args:
            bot_id: 机器人ID
            keyword: 关键词
            reply_text: 回复内容
            group_id: 群组ID（0表示全局）
            created_by: 创建者用户ID
            
        Returns:
            bool: 是否成功
        """
        async with get_db_session() as db:
            try:
                # 检查是否已存在相同关键词
                query = select(CustomKeyword).where(
                    and_(
                        CustomKeyword.bot_id == bot_id,
                        CustomKeyword.group_id == group_id,
                        CustomKeyword.keyword == keyword,
                        CustomKeyword.is_active.is_(True)
                    )
                )
                result = await db.execute(query)
                existing = result.scalar_one_or_none()
                
                if existing:
                    # 更新现有关键词
                    existing.reply_text = reply_text
                    logger.info(f"Updated keyword: {keyword} in group {group_id}")
                else:
                    # 创建新关键词
                    new_keyword = CustomKeyword(
                        bot_id=bot_id,
                        group_id=group_id,
                        keyword=keyword,
                        reply_text=reply_text,
                        is_active=True,
                        created_by=created_by
                    )
                    db.add(new_keyword)
                    logger.info(f"Added keyword: {keyword} in group {group_id}")
                
                await db.commit()
                return True
                
            except Exception as e:
                logger.error(f"Failed to add keyword: {e}", exc_info=True)
                await db.rollback()
                return False
    
    @staticmethod
    async def delete_keyword(bot_id: str, keyword: str, group_id: int = 0) -> bool:
        """
        删除关键词
        
        Args:
            bot_id: 机器人ID
            keyword: 关键词
            group_id: 群组ID（0表示全局）
            
        Returns:
            bool: 是否成功
        """
        async with get_db_session() as db:
            try:
                query = select(CustomKeyword).where(
                    and_(
                        CustomKeyword.bot_id == bot_id,
                        CustomKeyword.group_id == group_id,
                        CustomKeyword.keyword == keyword,
                        CustomKeyword.is_active.is_(True)
                    )
                )
                result = await db.execute(query)
                keyword_obj = result.scalar_one_or_none()
                
                if keyword_obj:
                    keyword_obj.is_active = False
                    await db.commit()
                    logger.info(f"Deleted keyword: {keyword} in group {group_id}")
                    return True
                else:
                    logger.warning(f"Keyword not found: {keyword} in group {group_id}")
                    return False
                    
            except Exception as e:
                logger.error(f"Failed to delete keyword: {e}", exc_info=True)
                await db.rollback()
                return False
    
    @staticmethod
    async def get_keywords(bot_id: str, group_id: int = 0) -> List[CustomKeyword]:
        """
        获取关键词列表
        
        Args:
            bot_id: 机器人ID
            group_id: 群组ID（0表示全局）
            
        Returns:
            List[CustomKeyword]: 关键词列表
        """
        async with get_db_session() as db:
            try:
                query = select(CustomKeyword).where(
                    and_(
                        CustomKeyword.bot_id == bot_id,
                        CustomKeyword.group_id == group_id,
                        CustomKeyword.is_active.is_(True)
                    )
                ).order_by(CustomKeyword.keyword)
                
                result = await db.execute(query)
                return list(result.scalars().all())
                
            except Exception as e:
                logger.error(f"Failed to get keywords: {e}", exc_info=True)
                return []
    
    @staticmethod
    async def find_matching_keyword(bot_id: str, chat_id: int, text: str) -> Optional[CustomKeyword]:
        """
        查找匹配的关键词（优先匹配群组关键词，再匹配全局关键词）
        
        Args:
            bot_id: 机器人ID
            chat_id: 聊天ID
            text: 消息文本
            
        Returns:
            Optional[CustomKeyword]: 匹配的关键词对象，未找到返回None
        """
        async with get_db_session() as db:
            try:
                # 1. 先查找群组专属关键词
                query = select(CustomKeyword).where(
                    and_(
                        CustomKeyword.bot_id == bot_id,
                        CustomKeyword.group_id == chat_id,
                        CustomKeyword.keyword == text,
                        CustomKeyword.is_active.is_(True)
                    )
                )
                result = await db.execute(query)
                group_keyword = result.scalar_one_or_none()
                
                if group_keyword:
                    logger.debug(f"Found group-specific keyword: {text} in group {chat_id}")
                    return group_keyword
                
                # 2. 再查找全局关键词
                query = select(CustomKeyword).where(
                    and_(
                        CustomKeyword.bot_id == bot_id,
                        CustomKeyword.group_id == 0,  # 全局关键词
                        CustomKeyword.keyword == text,
                        CustomKeyword.is_active.is_(True)
                    )
                )
                result = await db.execute(query)
                global_keyword = result.scalar_one_or_none()
                
                if global_keyword:
                    logger.debug(f"Found global keyword: {text}")
                    return global_keyword
                
                return None
                
            except Exception as e:
                logger.error(f"Failed to find matching keyword: {e}", exc_info=True)
                return None
    
    @staticmethod
    async def clear_user_keywords(bot_id: str, user_id: int, group_id: int = 0) -> int:
        """
        清除用户创建的关键词
        
        Args:
            bot_id: 机器人ID
            user_id: 用户ID
            group_id: 群组ID（0表示全局）
            
        Returns:
            int: 删除的数量
        """
        async with get_db_session() as db:
            try:
                update_stmt = update(CustomKeyword).where(
                    and_(
                        CustomKeyword.bot_id == bot_id,
                        CustomKeyword.created_by == user_id,
                        CustomKeyword.group_id == group_id
                    )
                ).values(is_active=False)
                result = await db.execute(update_stmt)
                await db.commit()

                updated_count = result.rowcount
                logger.info(f"Soft-deleted {updated_count} keywords for user {user_id} in group {group_id}")
                return updated_count
                
            except Exception as e:
                logger.error(f"Failed to clear keywords: {e}", exc_info=True)
                await db.rollback()
                return 0
