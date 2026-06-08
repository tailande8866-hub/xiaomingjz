"""
Tenant Scope - 自动租户隔离查询工具
确保所有数据库查询都强制带上 WHERE bot_id = ?
"""
from typing import Type
from sqlalchemy import select, and_
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)


def scoped_query(model_class, context: ContextTypes.DEFAULT_TYPE = None, bot_id: str = None):
    """
    创建带租户隔离的查询对象
    
    Args:
        model_class: SQLAlchemy 模型类
        context: Telegram handler 的 context 对象（可选）
        bot_id: 手动指定的 bot_id（可选，优先级最高）
    
    Returns:
        SQLAlchemy select 查询对象（已自动追加 WHERE bot_id = ?）
    
    Raises:
        RuntimeError: 如果 bot_id 缺失
        AttributeError: 如果模型不支持租户隔离
    
    用法：
        # 方式1：从 context 自动获取 bot_id
        query = scoped_query(Group, context)
        result = await db.execute(query)
        
        # 方式2：手动指定 bot_id
        query = scoped_query(Group, bot_id="bot_abc123")
    """
    # 获取 bot_id
    if not bot_id and context:
        bot_id = context.application.bot_data.get('bot_id')
    
    if not bot_id:
        raise RuntimeError(
            "Cannot create scoped query: bot_id is missing! "
            "Ensure BotIdMiddleware is initialized."
        )
    
    # 检查模型是否支持租户隔离
    if not hasattr(model_class, 'bot_id'):
        raise AttributeError(
            f"Model {model_class.__name__} does not support tenant isolation "
            f"(missing bot_id field)"
        )
    
    # 创建带租户过滤的查询
    query = select(model_class).where(model_class.bot_id == bot_id)
    return query


def scoped_query_with_filters(model_class, context: ContextTypes.DEFAULT_TYPE = None, 
                               bot_id: str = None, **filters):
    """
    创建带租户隔离和额外过滤条件的查询对象
    
    Args:
        model_class: SQLAlchemy 模型类
        context: Telegram handler 的 context 对象（可选）
        bot_id: 手动指定的 bot_id（可选）
        **filters: 额外的过滤条件（字典形式）
    
    Returns:
        SQLAlchemy select 查询对象
    
    用法：
        query = scoped_query_with_filters(
            Group, 
            context,
            is_active=True,
            group_type="supergroup"
        )
        # 等价于：
        # SELECT * FROM groups 
        # WHERE bot_id = ? AND is_active = ? AND group_type = ?
    """
    # 获取 bot_id
    if not bot_id and context:
        bot_id = context.application.bot_data.get('bot_id')
    
    if not bot_id:
        raise RuntimeError(
            "Cannot create scoped query: bot_id is missing!"
        )
    
    # 检查模型是否支持租户隔离
    if not hasattr(model_class, 'bot_id'):
        raise AttributeError(
            f"Model {model_class.__name__} does not support tenant isolation"
        )
    
    # 构建查询条件
    conditions = [model_class.bot_id == bot_id]
    
    # 添加额外过滤条件
    for field, value in filters.items():
        if hasattr(model_class, field):
            conditions.append(getattr(model_class, field) == value)
        else:
            logger.warning(f"Model {model_class.__name__} has no field '{field}'")
    
    # 创建查询
    query = select(model_class).where(and_(*conditions))
    return query


def scoped_insert(model_instance, context: ContextTypes.DEFAULT_TYPE = None, bot_id: str = None):
    """
    为模型实例自动注入 bot_id
    
    Args:
        model_instance: SQLAlchemy 模型实例
        context: Telegram handler 的 context 对象（可选）
        bot_id: 手动指定的 bot_id（可选）
    
    Returns:
        修改后的模型实例（bot_id 已注入）
    
    Raises:
        RuntimeError: 如果 bot_id 缺失
        AttributeError: 如果模型不支持 bot_id
    
    用法：
        # 方式1：从 context 自动获取 bot_id
        group = Group(group_id=123, group_name="测试群")
        group = scoped_insert(group, context)
        db.add(group)
        
        # 方式2：手动指定 bot_id
        group = scoped_insert(group, bot_id="bot_abc123")
    """
    # 获取 bot_id
    if not bot_id and context:
        bot_id = context.application.bot_data.get('bot_id')
    
    if not bot_id:
        raise RuntimeError(
            "Cannot inject bot_id: bot_id is missing! "
            "Ensure BotIdMiddleware is initialized."
        )
    
    # 检查模型是否支持 bot_id
    if not hasattr(model_instance, 'bot_id'):
        raise AttributeError(
            f"Model {type(model_instance).__name__} does not support tenant isolation "
            f"(missing bot_id field)"
        )
    
    # 注入 bot_id
    model_instance.bot_id = bot_id
    
    return model_instance


def scoped_count(model_class, context: ContextTypes.DEFAULT_TYPE = None, bot_id: str = None):
    """
    创建带租户隔离的统计查询
    
    Args:
        model_class: SQLAlchemy 模型类
        context: Telegram handler 的 context 对象
        bot_id: 手动指定的 bot_id
    
    Returns:
        SQLAlchemy func.count 查询对象
    
    用法：
        from sqlalchemy import func
        query = scoped_count(Group, context)
        result = await db.execute(query)
        count = result.scalar()
    """
    from sqlalchemy import func
    
    if not bot_id and context:
        bot_id = context.application.bot_data.get('bot_id')
    
    if not bot_id:
        raise RuntimeError("Cannot create scoped count: bot_id is missing!")
    
    if not hasattr(model_class, 'bot_id'):
        raise AttributeError(f"Model {model_class.__name__} does not support tenant isolation")
    
    query = select(func.count()).select_from(model_class).where(model_class.bot_id == bot_id)
    return query
