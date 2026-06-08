"""
群组额度管理模型 - 多租户隔离

支持：
- 额度上限配置
- 币种设置（USDT/CNY）
- 启用/禁用开关
- 预警阈值跟踪（90%、100%）
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, BigInteger, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class GroupQuota(Base):
    """群组额度管理模型 - 多租户隔离"""
    __tablename__ = "group_quotas"
    
    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 关联群组
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, unique=True, comment="群组ID")
    
    # 额度配置
    quota_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="额度上限")
    quota_currency: Mapped[str] = mapped_column(String(10), default="USDT", comment="额度币种: USDT/CNY")
    quota_enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用额度监控")
    
    # 预警阈值标志（防止重复发送）
    warning_threshold_90: Mapped[bool] = mapped_column(Boolean, default=False, comment="90%预警已发送")
    warning_threshold_100: Mapped[bool] = mapped_column(Boolean, default=False, comment="100%预警已发送")
    
    # 审计字段
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    
    def __repr__(self):
        return f"<GroupQuota(group_id={self.group_id}, limit={self.quota_limit}, currency={self.quota_currency}, enabled={self.quota_enabled})>"
