"""
交易事件模型 - 金融审计核心

所有交易相关操作都会生成事件记录
用于：审计、风控、对账、监控、数据分析
"""
from datetime import datetime
from typing import Optional
import enum
from sqlalchemy import String, BigInteger, Integer, Text, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TransactionEventType(enum.Enum):
    """
    交易事件类型枚举
    
    CREATED: 创建交易
    REVOKED: 撤销交易
    RETRY_BLOCKED: 幂等拦截（重复请求被阻止）
    FAILED: 交易失败
    QUERY: 查询账单
    EXPORT: 导出账单
    STATUS_CHANGED: 状态切换
    SUMMARY_UPDATED: 汇总更新
    """
    CREATED = "CREATED"
    REVOKED = "REVOKED"
    RETRY_BLOCKED = "RETRY_BLOCKED"
    FAILED = "FAILED"
    QUERY = "QUERY"
    EXPORT = "EXPORT"
    STATUS_CHANGED = "STATUS_CHANGED"
    SUMMARY_UPDATED = "SUMMARY_UPDATED"


class ActorType(enum.Enum):
    """
    事件参与者类型
    
    USER: 普通用户
    ADMIN: 管理员
    SYSTEM: 系统自动操作
    WEBHOOK: Webhook 回调
    RETRY_WORKER: 重试工作器
    """
    USER = "USER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"
    WEBHOOK = "WEBHOOK"
    RETRY_WORKER = "RETRY_WORKER"


class TransactionEvent(Base):
    """
    交易事件表 - 金融审计核心
    
    所有交易相关操作都会在此表中生成事件记录
    核心原则：Append-only（只增不改）
    
    ️ 注意：不使用 Base 的 id 和 created_at，自定义以支持 Integer AUTOINCREMENT
    """
    __tablename__ = "transaction_events"
    
    # 主键（✅ SQLite 使用 Integer 而非 BigInteger 以支持 AUTOINCREMENT）
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # ⏰ 时间戳（覆盖 Base 的 created_at）
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True, comment="事件创建时间")
    
    # 🔑 事件唯一标识（UUID）
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True, comment="事件唯一ID (UUID)")
    
    # 🔗 关联字段
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True, comment="关联的交易trace_id")
    parent_trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True, comment="父交易trace_id（用于reversal）")
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="机器人ID（多租户隔离）")
    transaction_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="关联的交易ID")
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="群组ID")
    
    # 📊 事件信息
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="事件类型")
    old_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="旧状态（状态变更时）")
    new_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="新状态（状态变更时）")
    
    # 👤 操作者信息
    operator_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="操作者ID")
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default=ActorType.USER.value, comment="参与者类型")
    
    # 🔑 元数据（JSON格式，存储额外信息）
    event_data: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True, comment="事件元数据")
    
    # 索引优化
    __table_args__ = (
        Index('idx_event_bot_trace', 'bot_id', 'trace_id'),
        Index('idx_event_bot_group', 'bot_id', 'group_id'),
        Index('idx_event_type_created', 'event_type', 'created_at'),
    )
    
    def __repr__(self):
        return f"<TransactionEvent(id={self.id}, type={self.event_type}, trace_id={self.trace_id})>"
