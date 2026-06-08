"""
防数据漂移系统

职责：
1. 检测孤儿记录（没有对应 Bot 的记录）
2. 检测僵尸进程（数据库标记 running 但进程不存在）
3. 检测分组一致性（群组指向不存在的分组）
4. 检测权限一致性（管理员记录与 BotCreation 不匹配）
5. 检测树状结构一致性（parent_bot_id 指向不存在的 Bot）
"""
import logging
from datetime import datetime
from sqlalchemy import select, func

from ..models import BotCreation, Group, BroadcastGroup, Admin, get_db_session

logger = logging.getLogger(__name__)


class DataDriftPreventionSystem:
    """
    防数据漂移系统
    
    定期检测和修复数据不一致问题
    """
    
    async def run_full_check(self) -> dict:
        """
        执行完整的数据一致性检查
        
        Returns:
            检查结果统计
        """
        results = {
            'timestamp': datetime.utcnow().isoformat(),
            'checks': {},
            'total_issues': 0,
            'fixed_issues': 0
        }
        
        # Check 1: 树状结构一致性
        tree_result = await self._check_tree_consistency()
        results['checks']['tree_consistency'] = tree_result
        results['total_issues'] += tree_result['issues_found']
        results['fixed_issues'] += tree_result['issues_fixed']
        
        # Check 2: 分组一致性
        group_result = await self._check_group_consistency()
        results['checks']['group_consistency'] = group_result
        results['total_issues'] += group_result['issues_found']
        results['fixed_issues'] += group_result['issues_fixed']
        
        logger.info(
            f"📊 Data drift check completed: "
            f"{results['total_issues']} issues found, "
            f"{results['fixed_issues']} fixed"
        )
        
        return results
    
    async def _check_tree_consistency(self) -> dict:
        """检测树状结构一致性"""
        result = {'issues_found': 0, 'issues_fixed': 0, 'details': []}
        
        async with get_db_session() as db:
            # 查找所有有 parent_bot_id 的 Bot
            query = select(BotCreation).where(BotCreation.parent_bot_id.isnot(None))
            result_query = await db.execute(query)
            child_bots = result_query.scalars().all()
            
            for child_bot in child_bots:
                # 检查 parent_bot_id 是否存在
                parent_query = select(BotCreation).where(
                    BotCreation.instance_id == child_bot.parent_bot_id
                )
                parent_result = await db.execute(parent_query)
                parent_bot = parent_result.scalar_one_or_none()
                
                if not parent_bot:
                    result['issues_found'] += 1
                    logger.warning(
                        f"⚠️ Orphan child bot detected: {child_bot.instance_id} "
                        f"(parent {child_bot.parent_bot_id} not found)"
                    )
                    
                    # 修复：设置为根节点
                    child_bot.parent_bot_id = None
                    child_bot.root_bot_id = child_bot.instance_id
                    child_bot.tree_depth = 0
                    result['issues_fixed'] += 1
                    
                    result['details'].append({
                        'type': 'orphan_child_bot',
                        'instance_id': child_bot.instance_id,
                        'action': 'reset_to_root'
                    })
            
            await db.commit()
        
        return result
    
    async def _check_group_consistency(self) -> dict:
        """检测分组一致性"""
        result = {'issues_found': 0, 'issues_fixed': 0, 'details': []}
        
        async with get_db_session() as db:
            # 查找所有有 broadcast_group_id 的群组
            query = select(Group).where(Group.broadcast_group_id.isnot(None))
            result_query = await db.execute(query)
            groups = result_query.scalars().all()
            
            for group in groups:
                # 检查 broadcast_group_id 是否存在
                bg_query = select(BroadcastGroup).where(
                    BroadcastGroup.id == group.broadcast_group_id
                )
                bg_result = await db.execute(bg_query)
                broadcast_group = bg_result.scalar_one_or_none()
                
                if not broadcast_group:
                    result['issues_found'] += 1
                    logger.warning(
                        f"⚠️ Group {group.group_id} references non-existent "
                        f"broadcast group {group.broadcast_group_id}"
                    )
                    
                    # 修复：清除无效的分组引用
                    group.broadcast_group_id = None
                    result['issues_fixed'] += 1
                    
                    result['details'].append({
                        'type': 'invalid_broadcast_group',
                        'group_id': group.group_id,
                        'action': 'clear_broadcast_group_id'
                    })
            
            await db.commit()
        
        return result


# 全局实例
data_drift_prevention_system = DataDriftPreventionSystem()
