"""
超级管理员功能相关数据模型 - 多租户隔离

包含：
- GlobalForwardBlacklist: 全局消息转发黑名单（拉黑管理）
- SuperAdminSettings: 超管设置（免打扰等）
- ClosedUser: 已关闭用户列表
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, BigInteger, Boolean, Integer, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class GlobalForwardBlacklist(Base):
    """全局消息转发黑名单 - 超管拉黑的用户"""
    __tablename__ = "global_forward_blacklist"
    __table_args__ = (
        UniqueConstraint('bot_id', 'user_id', name='uix_blacklist_bot_user'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="被拉黑用户ID")
    blocked_by: Mapped[int] = mapped_column(BigInteger, comment="拉黑操作者ID（超管）")
    blocked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="拉黑时间")
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="解封时间(NULL=永久)")
    permanent: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否永久拉黑")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="拉黑原因")


class SuperAdminSettings(Base):
    """超级管理员设置 - 每个bot一条记录"""
    __tablename__ = "super_admin_settings"
    __table_args__ = (
        UniqueConstraint('bot_id', name='uix_super_admin_settings_bot'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    do_not_disturb: Mapped[bool] = mapped_column(Boolean, default=False, comment="免打扰模式")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")


class ClosedUser(Base):
    """已关闭用户列表 - 被超管强制关闭的用户"""
    __tablename__ = "closed_users"
    __table_args__ = (
        UniqueConstraint('bot_id', 'user_id', name='uix_closed_user_bot_user'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="被关闭用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    closed_by: Mapped[int] = mapped_column(BigInteger, comment="关闭操作者ID（超管）")
    closed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="关闭时间")
    original_expire_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="原到期时间")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="关闭原因")
    reopened: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已重新开通")
    reopened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="重新开通时间")


class PendingProvision(Base):
    """待开通用户 - 超管开通后等待用户提交Token"""
    __tablename__ = "pending_provisions"
    __table_args__ = (
        UniqueConstraint('bot_id', 'user_id', name='uix_pending_provision_bot_user'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="待开通用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    provisioned_by: Mapped[int] = mapped_column(BigInteger, comment="开通操作者ID（超管）")
    provisioned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="开通时间")
    duration_days: Mapped[int] = mapped_column(Integer, comment="开通时长（天）")
    expire_time: Mapped[datetime] = mapped_column(DateTime, comment="到期时间")
    mode: Mapped[str] = mapped_column(String(20), default="admin_send", comment="模式: admin_send=超管代发, user_send=用户自发")
    token_received: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已收到Token")
    token: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="收到的Token（加密存储）")
    completed: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已完成创建")
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="完成时间")


class SuperAdminMessageState(Base):
    """超管消息发送状态 - 记录向用户发消息的状态"""
    __tablename__ = "super_admin_message_states"
    __table_args__ = (
        UniqueConstraint('bot_id', 'admin_user_id', name='uix_msg_state_bot_admin'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    admin_user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="管理员用户ID")
    target_user_id: Mapped[int] = mapped_column(BigInteger, comment="目标用户ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="创建时间")
