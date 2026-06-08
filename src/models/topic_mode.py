"""
话题模式相关数据模型 - 多租户隔离

包含：
- TopicModeSettings: 话题模式配置
- UserTopic: 用户话题绑定
- UserActiveTarget: 管理员当前聊天目标
- UserBlock: 用户禁言/拉黑
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, BigInteger, Boolean, Integer, DateTime, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TopicModeSettings(Base):
    """话题模式配置 - 每个bot一条记录"""
    __tablename__ = "topic_mode_settings"
    __table_args__ = (
        UniqueConstraint('bot_id', name='uix_topic_mode_bot_id'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用话题模式")
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="转发目标群组ID")
    group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="群组标题")
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="创建者用户ID")


class UserTopic(Base):
    """用户话题绑定 - 每个用户在群组中有一个话题"""
    __tablename__ = "user_topics"
    __table_args__ = (
        UniqueConstraint('bot_id', 'user_id', name='uix_user_topic_bot_user'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户ID")
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="群组ID")
    topic_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="话题ID(message_thread_id)")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户昵称")
    active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否活跃")
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后消息时间")


class UserActiveTarget(Base):
    """管理员当前聊天目标 - 管理员私聊bot时自动转发给目标用户"""
    __tablename__ = "user_active_targets"
    __table_args__ = (
        UniqueConstraint('bot_id', 'admin_user_id', name='uix_active_target_bot_admin'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    admin_user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="管理员用户ID")
    target_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="目标用户ID")
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="关联群组ID")
    topic_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="关联话题ID")


class UserBlock(Base):
    """用户禁言/拉黑"""
    __tablename__ = "user_blocks"
    __table_args__ = (
        UniqueConstraint('bot_id', 'user_id', name='uix_user_block_bot_user'),
    )

    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户ID")
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="禁言截止时间(NULL=永久)")
    permanent: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否永久封禁")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="封禁原因")
