"""
机器人状态管理模型
用于机器人状态面板、操作日志等
"""
from datetime import datetime
from sqlalchemy import String, BigInteger, Text, DateTime, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from .database import Base


class BotOperationLog(Base):
    """机器人操作日志表"""
    __tablename__ = "bot_operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="Bot实例ID")
    operator_user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="操作者用户ID")
    action: Mapped[str] = mapped_column(String(50), comment="操作类型: delete/restart/disconnect/reset_token/transfer_owner")
    status: Mapped[str] = mapped_column(String(20), comment="操作状态: success/failed")
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="操作详情/错误信息")
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="旧值(JSON)")
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="新值(JSON)")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="操作时间")

    def __repr__(self):
        return f"<BotOperationLog(bot_id='{self.bot_id}', action='{self.action}', status='{self.status}')>"


class BotAdmin(Base):
    """Bot管理员表 - 记录Bot的所有者和管理员"""
    __tablename__ = "bot_admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="Bot实例ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户ID")
    role: Mapped[str] = mapped_column(String(20), default="admin", comment="角色: owner/admin/operator")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="名字")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否激活")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="添加时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def __repr__(self):
        return f"<BotAdmin(bot_id='{self.bot_id}', user_id={self.user_id}, role='{self.role}')>"
