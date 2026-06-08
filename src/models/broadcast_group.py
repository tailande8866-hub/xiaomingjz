"""
Broadcast Group Model - 广播分组模型

用于管理群组的广播分类
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Integer, DateTime, Boolean, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class BroadcastGroup(Base):
    """
    广播分组模型
    
    用于将群组按类别分组，方便批量发送消息
    """
    __tablename__ = "broadcast_groups"
    
    # 🔑 主键
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # 🔐 多租户隔离（核心）
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="所属 Bot ID")
    
    # 📊 分组信息
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="分组名称")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="分组描述")
    
    # 👤 创建者信息
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="创建者 Telegram ID")
    
    # ⏰ 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    
    # 📊 索引
    __table_args__ = (
        Index('idx_bot_id', 'bot_id'),
        Index('idx_name', 'name'),
        Index('idx_created_by', 'created_by'),
        # 唯一约束：同一 Bot 内分组名唯一
        Index('idx_bot_name_unique', 'bot_id', 'name', unique=True),
    )
    
    def __repr__(self):
        return f"<BroadcastGroup(name='{self.name}', created_by={self.created_by})>"
