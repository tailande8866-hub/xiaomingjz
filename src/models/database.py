"""
数据库配置和基础模型
"""
import os
from datetime import datetime
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, DateTime

from config import config


def _ensure_db_directory():
    """确保数据库文件所在目录存在"""
    db_url = config.DATABASE_URL
    if 'sqlite' in db_url.lower():
        # 从 URL 中提取文件路径
        # sqlite+aiosqlite:///app/data/accounting_bot.db -> /app/data/accounting_bot.db
        db_path = db_url.replace('sqlite+aiosqlite:///', '').replace('sqlite:///', '')
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            print(f"Created database directory: {db_dir}")


# 🔥 在导入时确保目录存在
_ensure_db_directory()


class Base(DeclarativeBase):
    """SQLAlchemy基础模型"""
    metadata = MetaData()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# 创建异步引擎（优化连接池配置）
# SQLite 不支持连接池参数，需要根据数据库类型动态配置
if 'sqlite' in config.DATABASE_URL.lower():
    engine = create_async_engine(
        config.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,  # 连接前检查有效性
    )
else:
    # MySQL/PostgreSQL 等数据库支持连接池
    engine = create_async_engine(
        config.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,  # 连接前检查有效性
        pool_size=10,  # 连接池大小
        max_overflow=20,  # 最大溢出连接数
        pool_timeout=30,  # 获取连接超时时间（秒）
        pool_recycle=3600,  # 连接回收时间（秒）
    )

# 创建会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话（生成器模式，用于依赖注入）
    
    使用示例：
        async for db in get_db():
            result = await db.execute(query)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话（上下文管理器模式，推荐用于复杂事务）
    
    优势：
    - 所有操作在同一事务中
    - 自动提交/回滚
    - 避免嵌套会话问题
    
    使用示例：
        async with get_db_session() as db:
            # 第一次查询
            result1 = await db.execute(query1)
            # 第二次查询（同一会话）
            result2 = await db.execute(query2)
            # 自动提交
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化数据库"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """关闭数据库连接"""
    await engine.dispose()
