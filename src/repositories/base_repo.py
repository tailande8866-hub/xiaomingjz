"""
Repository Base - 统一数据访问层基类

所有 Repository 都继承自 BaseRepo，自动注入 bot_id
确保所有查询都包含 WHERE bot_id = ? 条件
"""
from typing import TypeVar, Generic, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, and_
from sqlalchemy.orm import DeclarativeBase
import logging

logger = logging.getLogger(__name__)

ModelType = TypeVar('ModelType', bound=DeclarativeBase)


class BaseRepo(Generic[ModelType]):
    """
    Repository 基类
    
    核心功能：
    1. 自动注入 bot_id 到所有查询
    2. 提供统一的 CRUD 操作
    3. 防止开发者忘记添加 bot_id 条件
    
    使用示例：
        repo = TransactionRepo(session, bot_id)
        transactions = await repo.get_all()
    """
    
    def __init__(self, session: AsyncSession, bot_id: str):
        """
        初始化 Repository
        
        Args:
            session: SQLAlchemy 异步会话
            bot_id: 当前机器人的唯一标识
        """
        self.session = session
        self.bot_id = bot_id
        
        if not bot_id:
            raise ValueError("bot_id cannot be empty!")
        
        logger.debug(f"BaseRepo initialized for bot_id={bot_id}")
    
    @property
    def model_class(self) -> type:
        """子类必须实现，返回模型类"""
        raise NotImplementedError("Subclasses must implement model_class property")
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[ModelType]:
        """
        获取所有记录（自动添加 bot_id 条件）
        
        Args:
            limit: 限制数量
            offset: 偏移量
            
        Returns:
            记录列表
        """
        stmt = (
            select(self.model_class)
            .where(self.model_class.bot_id == self.bot_id)
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def get_by_id(self, record_id: int) -> Optional[ModelType]:
        """
        根据 ID 获取记录（自动添加 bot_id 条件）
        
        Args:
            record_id: 记录 ID
            
        Returns:
            记录对象或 None
        """
        stmt = select(self.model_class).where(
            and_(
                self.model_class.id == record_id,
                self.model_class.bot_id == self.bot_id
            )
        )
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create(self, **kwargs) -> ModelType:
        """
        创建新记录（自动设置 bot_id）
        
        Args:
            **kwargs: 字段值
            
        Returns:
            创建的记录对象
        """
        # 自动注入 bot_id
        kwargs['bot_id'] = self.bot_id
        
        record = self.model_class(**kwargs)
        self.session.add(record)
        await self.session.flush()
        
        logger.info(f"Created {self.model_class.__name__} with bot_id={self.bot_id}")
        return record
    
    async def update(self, record_id: int, **kwargs) -> Optional[ModelType]:
        """
        更新记录（自动验证 bot_id）
        
        Args:
            record_id: 记录 ID
            **kwargs: 要更新的字段
            
        Returns:
            更新后的记录或 None
        """
        # 先查询确认归属
        record = await self.get_by_id(record_id)
        
        if not record:
            logger.warning(f"Record {record_id} not found or not owned by bot_id={self.bot_id}")
            return None
        
        # 更新字段（不允许修改 bot_id）
        for key, value in kwargs.items():
            if key != 'bot_id' and hasattr(record, key):
                setattr(record, key, value)
        
        await self.session.flush()
        logger.info(f"Updated {self.model_class.__name__} {record_id}")
        return record
    
    async def delete(self, record_id: int) -> bool:
        """
        删除记录（自动验证 bot_id）
        
        Args:
            record_id: 记录 ID
            
        Returns:
            是否删除成功
        """
        stmt = delete(self.model_class).where(
            and_(
                self.model_class.id == record_id,
                self.model_class.bot_id == self.bot_id
            )
        )
        
        result = await self.session.execute(stmt)
        deleted_count = result.rowcount
        
        if deleted_count > 0:
            logger.info(f"Deleted {self.model_class.__name__} {record_id}")
            return True
        else:
            logger.warning(f"Failed to delete {self.model_class.__name__} {record_id} (not found or not owned)")
            return False
    
    async def count(self) -> int:
        """
        统计记录数量（自动添加 bot_id 条件）
        
        Returns:
            记录数量
        """
        from sqlalchemy import func
        
        stmt = (
            select(func.count())
            .select_from(self.model_class)
            .where(self.model_class.bot_id == self.bot_id)
        )
        
        result = await self.session.execute(stmt)
        return result.scalar() or 0
