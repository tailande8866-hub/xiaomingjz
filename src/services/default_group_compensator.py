"""
默认分组自动补偿器

职责：
1. Bot 首次启动时确保默认分组存在
2. 健康检查发现分组缺失时自动补偿
3. 管理员手动触发补偿
"""
import logging
from datetime import datetime
from sqlalchemy import select, and_

from ..models.broadcast_group import BroadcastGroup
from ..models.group import DEFAULT_BROADCAST_GROUP_TAG
from ..models.database import get_db_session

logger = logging.getLogger(__name__)


class DefaultGroupCompensator:
    """
    默认分组自动补偿器
    
    确保每个 Bot 都有正确的默认广播分组，防止数据缺失
    """
    
    async def ensure_default_group(self, bot_id: str) -> BroadcastGroup:
        """
        确保默认分组存在
        
        Args:
            bot_id: Bot 实例 ID
            
        Returns:
            默认广播分组对象
        """
        async with get_db_session() as db:
            # 查询是否存在默认分组
            query = select(BroadcastGroup).where(
                and_(
                    BroadcastGroup.name == DEFAULT_BROADCAST_GROUP_TAG,
                    BroadcastGroup.bot_id == bot_id
                )
            )
            result = await db.execute(query)
            default_group = result.scalar_one_or_none()
            
            if not default_group:
                logger.warning(f"⚠️ Default group missing for bot {bot_id}, creating...")
                
                # 创建默认分组
                default_group = BroadcastGroup(
                    name=DEFAULT_BROADCAST_GROUP_TAG,
                    description="系统自动创建的默认分组",
                    bot_id=bot_id,
                    created_by=0,  # 系统创建
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                db.add(default_group)
                await db.commit()
                await db.refresh(default_group)
                
                logger.info(f"✅ Default group created for bot {bot_id}: id={default_group.id}")
            else:
                logger.debug(f"✅ Default group exists for bot {bot_id}: id={default_group.id}")
            
            return default_group
    
    async def compensate_all_bots(self) -> dict:
        """
        补偿所有 Bot 的默认分组
        
        Returns:
            补偿结果统计
        """
        results = {
            'total_bots': 0,
            'compensated': 0,
            'already_exists': 0,
            'errors': 0,
            'details': []
        }
        
        async with get_db_session() as db:
            # 获取所有唯一的 bot_id
            from ..models import BotCreation
            query = select(BotCreation.instance_id).distinct()
            result = await db.execute(query)
            bot_ids = [row[0] for row in result.all()]
            
            results['total_bots'] = len(bot_ids)
            
            for bot_id in bot_ids:
                try:
                    default_group = await self.ensure_default_group(bot_id)
                    
                    if default_group.created_at == default_group.updated_at:
                        # 新创建的
                        results['compensated'] += 1
                        results['details'].append({
                            'bot_id': bot_id,
                            'action': 'created',
                            'group_id': default_group.id
                        })
                    else:
                        # 已存在
                        results['already_exists'] += 1
                        
                except Exception as e:
                    results['errors'] += 1
                    results['details'].append({
                        'bot_id': bot_id,
                        'action': 'error',
                        'error': str(e)
                    })
                    logger.error(f"Failed to compensate bot {bot_id}: {e}", exc_info=True)
        
        logger.info(
            f"📊 Default group compensation completed: "
            f"{results['compensated']} created, "
            f"{results['already_exists']} already exists, "
            f"{results['errors']} errors"
        )
        
        return results


# 全局实例
default_group_compensator = DefaultGroupCompensator()
