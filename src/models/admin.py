"""
管理员数据模型
存储超级管理员添加的管理员信息
"""
from datetime import datetime
from sqlalchemy import String, BigInteger, Boolean, Text, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from .database import Base


class Admin(Base):
    """管理员模型（由超级管理员添加）- 多租户隔离"""
    __tablename__ = "admins"
    
    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # Telegram信息
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="Telegram用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Telegram用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="名字")
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="姓氏")
    
    # 权限信息
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否激活")
    permissions: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="权限列表(JSON格式)")
    
    # 详细权限配置（优化版）
    can_create_bot: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否可以创建机器人（支持无限裂变分销）")
    can_manage_admins: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否可以管理其他管理员（仅超级管理员可授权）")
    can_manage_group_members: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否可以管理群组成员")
    can_broadcast: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否有群发广播/分组广播权限")
    can_set_day_cut: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否可设置日切时间")
    can_set_keywords: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否可设置关键词回复")
    can_billing: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否有记账功能")
    can_query: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否有查询功能")
    can_settings: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否可以功能设置")
    can_renew: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否有续费功能")
    
    # 添加者信息
    added_by: Mapped[int] = mapped_column(BigInteger, comment="添加者的Telegram用户ID（超级管理员）")
    added_by_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="添加者用户名")
    
    # 备注
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="备注")

    # 🆕 试用管理员相关字段
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否为试用管理员")
    group_limit: Mapped[int] = mapped_column(Integer, default=0, comment="可管理群组数量限制（0表示无限制）")
    expire_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="试用到期时间")

    def __repr__(self):
        return f"<Admin(user_id={self.user_id}, username='{self.username}', is_trial={self.is_trial})>"
