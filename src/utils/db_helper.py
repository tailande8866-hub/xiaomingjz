"""
数据库辅助函数模块

提供常用的数据库查询和操作函数，减少代码重复
"""
import logging
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy import select, and_, func, false
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Group, GroupOperator, UserConfig, Transaction, DailySummary

logger = logging.getLogger(__name__)


# ============================================================================
# 群组相关查询
# ============================================================================

async def get_group(db: AsyncSession, group_id: int, bot_id: str = None) -> Optional[Group]:
    """
    获取群组信息
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        bot_id: Bot实例ID（可选，用于多租户隔离）
    
    Returns:
        Group对象或None
    """
    query = select(Group).where(Group.group_id == group_id)
    
    # 如果提供 bot_id，添加多租户隔离条件
    if bot_id:
        query = query.where(Group.bot_id == bot_id)
    
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def check_group_active(db: AsyncSession, group_id: int, bot_id: str = None) -> bool:
    """
    检查群组是否开启记账
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        bot_id: Bot实例ID（可选，用于多租户隔离）
    
    Returns:
        True如果群组存在且开启记账
    """
    group = await get_group(db, group_id, bot_id)
    return group is not None and group.is_active


# ============================================================================
# 权限检查
# ============================================================================

async def is_operator(db: AsyncSession, user_id: int, group_id: int, bot_id: str = None) -> bool:
    """
    检查用户是否有操作权限
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        group_id: 群组ID
        bot_id: Bot实例ID（可选，用于多租户隔离）
    
    Returns:
        True如果有权限
    """
    # 检查是否为全局操作人
    query = select(GroupOperator).where(
        and_(
            GroupOperator.user_id == user_id,
            GroupOperator.is_global.is_(True)
        )
    )
    # 如果提供 bot_id，添加多租户隔离条件
    if bot_id:
        query = query.where(GroupOperator.bot_id == bot_id)
    
    result = await db.execute(query)
    if result.scalar_one_or_none():
        return True
    
    # 检查是否为群组操作人
    query = select(GroupOperator).where(
        and_(
            GroupOperator.group_id == group_id,
            GroupOperator.user_id == user_id
        )
    )
    # 如果提供 bot_id，添加多租户隔离条件
    if bot_id:
        query = query.where(GroupOperator.bot_id == bot_id)
    
    result = await db.execute(query)
    if result.scalar_one_or_none():
        return True
    
    # 检查是否全员可操作
    group = await get_group(db, group_id, bot_id)
    if group and group.all_members_operator:
        return True
    
    return False


async def get_operators(db: AsyncSession, group_id: int) -> List[GroupOperator]:
    """
    获取群组的所有操作人
    
    Args:
        db: 数据库会话
        group_id: 群组ID
    
    Returns:
        操作人列表
    """
    query = select(GroupOperator).where(
        and_(
            GroupOperator.group_id == group_id,
            GroupOperator.is_global.is_(False)
        )
    )
    result = await db.execute(query)
    return result.scalars().all()


# ============================================================================
# 交易记录查询
# ============================================================================

async def get_transactions(
    db: AsyncSession,
    group_id: int,
    transaction_type: str = None,
    user_id: int = None,
    start_date: datetime = None,
    end_date: datetime = None,
    limit: int = 50,
    offset: int = 0,
    is_deleted: bool = False
) -> List[Transaction]:
    """
    查询交易记录
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        transaction_type: 交易类型 (deposit/withdraw/storage)
        user_id: 用户ID
        start_date: 开始日期
        end_date: 结束日期
        limit: 限制数量
        offset: 偏移量
        is_deleted: 是否包含已删除的记录
    
    Returns:
        交易记录列表
    """
    conditions = [
        Transaction.group_id == group_id,
    ]
    
    # ✅ 使用 is_() / is_not() 处理布尔字段
    if is_deleted:
        conditions.append(Transaction.is_deleted.is_(True))
    else:
        conditions.append(Transaction.is_deleted.is_(False))
    
    if transaction_type:
        conditions.append(Transaction.transaction_type == transaction_type)
    
    if user_id:
        conditions.append(Transaction.user_id == user_id)
    
    if start_date:
        conditions.append(Transaction.transaction_date >= start_date)
    
    if end_date:
        conditions.append(Transaction.transaction_date < end_date)
    
    query = (
        select(Transaction)
        .where(and_(*conditions))
        .order_by(Transaction.transaction_date.desc())
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(query)
    return result.scalars().all()


async def get_transaction_by_id(db: AsyncSession, transaction_id: int) -> Optional[Transaction]:
    """
    根据ID获取交易记录
    
    Args:
        db: 数据库会话
        transaction_id: 交易记录ID
    
    Returns:
        Transaction对象或None
    """
    query = select(Transaction).where(Transaction.id == transaction_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_transaction_by_message_id(
    db: AsyncSession,
    group_id: int,
    message_id: int
) -> Optional[Transaction]:
    """
    根据消息ID获取交易记录
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        message_id: 消息ID
    
    Returns:
        Transaction对象或None
    """
    query = select(Transaction).where(
        and_(
            Transaction.group_id == group_id,
            Transaction.message_id == message_id,
            Transaction.is_deleted.is_(False)  # 🔑 过滤已删除的记录
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def count_transactions(
    db: AsyncSession,
    group_id: int,
    transaction_type: str = None,
    user_id: int = None,
    start_date: datetime = None,
    end_date: datetime = None,
    is_deleted: bool = False
) -> int:
    """
    统计交易记录数量
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        transaction_type: 交易类型
        user_id: 用户ID
        start_date: 开始日期
        end_date: 结束日期
        is_deleted: 是否包含已删除的记录
    
    Returns:
        记录数量
    """
    conditions = [
        Transaction.group_id == group_id,
    ]
    
    # ✅ 使用 is_() / is_not() 处理布尔字段
    if is_deleted:
        conditions.append(Transaction.is_deleted.is_(True))
    else:
        conditions.append(Transaction.is_deleted.is_(False))
    
    if transaction_type:
        conditions.append(Transaction.transaction_type == transaction_type)
    
    if user_id:
        conditions.append(Transaction.user_id == user_id)
    
    if start_date:
        conditions.append(Transaction.transaction_date >= start_date)
    
    if end_date:
        conditions.append(Transaction.transaction_date < end_date)
    
    query = select(func.count()).select_from(Transaction).where(and_(*conditions))
    result = await db.execute(query)
    return result.scalar_one()


# ============================================================================
# 统计汇总
# ============================================================================

async def get_daily_summary(
    db: AsyncSession,
    group_id: int,
    summary_date: datetime
) -> Optional[DailySummary]:
    """
    获取每日汇总
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        summary_date: 汇总日期
    
    Returns:
        DailySummary对象或None
    """
    query = select(DailySummary).where(
        and_(
            DailySummary.group_id == group_id,
            DailySummary.summary_date == summary_date
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def calculate_totals(
    db: AsyncSession,
    group_id: int,
    start_date: datetime = None,
    end_date: datetime = None,
    transaction_type: str = None
) -> dict:
    """
    计算总计
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        start_date: 开始日期
        end_date: 结束日期
        transaction_type: 交易类型
    
    Returns:
        包含count, total_amount, total_cny的字典
    """
    conditions = [
        Transaction.group_id == group_id,
        Transaction.is_deleted.is_(False)
    ]
    
    if start_date:
        conditions.append(Transaction.transaction_date >= start_date)
    
    if end_date:
        conditions.append(Transaction.transaction_date < end_date)
    
    if transaction_type:
        conditions.append(Transaction.transaction_type == transaction_type)
    
    query = select(
        func.count(Transaction.id).label('count'),
        func.coalesce(func.sum(Transaction.amount), 0).label('total_amount'),
        func.coalesce(func.sum(Transaction.cny_amount), 0).label('total_cny')
    ).where(and_(*conditions))
    
    result = await db.execute(query)
    row = result.one()
    
    return {
        'count': row.count,
        'total_amount': row.total_amount,
        'total_cny': row.total_cny
    }


# ============================================================================
# 用户配置
# ============================================================================

async def get_user_config(
    db: AsyncSession,
    group_id: int,
    user_id: int
) -> Optional[UserConfig]:
    """
    获取用户配置
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        user_id: 用户ID
    
    Returns:
        UserConfig对象或None
    """
    query = select(UserConfig).where(
        and_(
            UserConfig.group_id == group_id,
            UserConfig.user_id == user_id
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_or_update_user_config(
    db: AsyncSession,
    group_id: int,
    user_id: int,
    username: str = None,
    first_name: str = None,
    exchange_rate: float = None,
    fee_rate: float = None
) -> UserConfig:
    """
    创建或更新用户配置
    
    Args:
        db: 数据库会话
        group_id: 群组ID
        user_id: 用户ID
        username: 用户名
        first_name: 名字
        exchange_rate: 汇率
        fee_rate: 费率
    
    Returns:
        UserConfig对象
    """
    config = await get_user_config(db, group_id, user_id)
    
    if not config:
        config = UserConfig(
            group_id=group_id,
            user_id=user_id,
            username=username,
            first_name=first_name
        )
        db.add(config)
    else:
        if username:
            config.username = username
        if first_name:
            config.first_name = first_name
    
    if exchange_rate is not None:
        config.exchange_rate = exchange_rate
    
    if fee_rate is not None:
        config.fee_rate = fee_rate
    
    await db.flush()
    return config


# ============================================================================
# 日切周期
# ============================================================================

def get_day_cut_period(group: Group) -> tuple:
    """
    获取当前日切周期的开始和结束时间
    
    Args:
        group: 群组对象
    
    Returns:
        tuple: (start_date, end_date) 或者 (None, None) 如果没有设置日切
    """
    if not group.day_cut_time:
        return None, None
    
    now = datetime.utcnow()
    day_cut_hour = group.day_cut_time.hour
    day_cut_minute = group.day_cut_time.minute
    
    # 今天的日切时间
    today_cut = now.replace(hour=day_cut_hour, minute=day_cut_minute, second=0, microsecond=0)
    
    # 判断当前是否在今天日切之后
    if now >= today_cut:
        # 当前周期从今天日切开始，到明天日切结束
        start_date = today_cut
        end_date = today_cut + timedelta(days=1)
    else:
        # 当前周期从昨天日切开始，到今天日切结束
        start_date = today_cut - timedelta(days=1)
        end_date = today_cut
    
    return start_date, end_date
