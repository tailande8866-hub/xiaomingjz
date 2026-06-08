"""
规则快照模型 - 批次锁核心

用于锁定每一批入款的汇率和费率规则，确保：
1. 同一批次内的所有交易使用相同规则
2. 历史规则不可变更（审计追溯）
3. 报表可按批次隔离统计
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RuleSnapshot(Base):
    """规则快照表 - 批次锁"""
    __tablename__ = "rule_snapshots"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # ✅ 批次 ID (唯一键)
    batch_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, comment="规则批次ID (格式:YYYYMMDD-序号)")
    
    # 🧊 冻结的规则参数
    exchange_rate: Mapped[float] = mapped_column(Float, comment="汇率(冻结)")
    fee_rate: Mapped[float] = mapped_column(Float, comment="费率%(冻结)")
    
    # 📅 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="创建时间")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否激活(可停用旧批次)")
    
    # 📝 备注
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="批次描述")
    
    def __repr__(self):
        return f"<RuleSnapshot(batch_id='{self.batch_id}', rate={self.exchange_rate}, fee={self.fee_rate}%)>"
