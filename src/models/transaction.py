"""
交易记录数据模型 - 金融级增强版

支持：
- 状态机（PENDING/SUCCESS/FAILED/REVOKED）
- 幂等性检查（idempotency_key）
- 撤销追溯（reversal 相关字段）
- 审计追踪（trace_id）
"""
from datetime import datetime
from typing import Optional
import enum
from sqlalchemy import String, BigInteger, Float, Integer, Text, Boolean, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class TransactionStatus(enum.Enum):
    """
    交易状态枚举（金融级）
    
    PENDING: 处理中（等待确认）
    SUCCESS: 成功（有效交易）
    FAILED: 失败（处理失败）
    REVOKED: 已撤销（被用户或系统撤销）
    """
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REVOKED = "revoked"


class TransactionCategory(enum.Enum):
    """
    交易类别枚举（财务语义层）
    
    NORMAL: 正常交易（入款/下发/寄存）
    REVERSAL: 撤销交易（反向交易，用于审计）
    ADJUSTMENT: 调整交易（手动修正）
    FEE: 手续费交易
    SYSTEM: 系统交易（自动操作）
    
    注意：状态 ≠ 类型
    - REVOKED 是状态
    - REVERSAL 是业务类别
    """
    NORMAL = "normal"
    REVERSAL = "reversal"
    ADJUSTMENT = "adjustment"
    FEE = "fee"
    SYSTEM = "system"


class Transaction(Base):
    """交易记录模型 - 多租户隔离"""
    __tablename__ = "transactions"

    #  多租户隔离 - 所属机器人ID
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 基本信息
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="名字")

    # 操作人信息
    operator_id: Mapped[int] = mapped_column(BigInteger, comment="操作人ID")
    operator_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="操作人用户名")
    operator_first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="操作人名字")
    operator_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="操作人所在聊天ID(用于构建消息链接)")

    # 交易信息
    transaction_type: Mapped[str] = mapped_column(String(20), index=True, comment="交易类型: deposit(入款), withdraw(下发), storage(寄存)")
    amount: Mapped[float] = mapped_column(Float, comment="金额")
    currency: Mapped[str] = mapped_column(String(10), default="USDT", comment="币种")

    # 汇率和费率 (✅ 批次锁：入账时冻结，永不变更)
    exchange_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="汇率(冻结)")
    fee_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="费率%(冻结)")
    
    # ✅ 批次锁：同一批次入款使用相同规则 (格式:YYYYMMDD-序号)
    batch_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True, comment="规则批次ID")

    # 计算结果
    cny_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="人民币金额")
    fee_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="手续费金额")
    final_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="最终金额")
    
    # ✅ 冻结的 USDT 金额（追求完美：账是记录出来的，不是算出来的）
    amount_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="USDT金额(未扣费,入账时冻结)")
    final_amount_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="扣费后USDT金额(应下发,入账时冻结)")
    fee_amount_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="手续费USDT(入账时冻结)")

    # 备注和消息
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="备注")
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="消息ID")
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="回复的消息ID")
    
    # 🔑 追踪ID（UUID，用于审计、撤销、对账）
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True, comment="交易追踪ID (UUID)")
    
    # 🔐 幂等性键（防止重复记账）
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True, index=True, comment="幂等性键 (bot_id:chat_id:message_id)")

    # 🔄 状态机（金融级）
    status: Mapped[str] = mapped_column(
        SQLEnum(TransactionStatus, name='transaction_status'),
        default=TransactionStatus.SUCCESS,
        index=True,
        comment="交易状态: pending/success/failed/revoked"
    )
    
    # 📊 交易类别（财务语义层）
    category: Mapped[str] = mapped_column(
        SQLEnum(TransactionCategory, name='transaction_category'),
        default=TransactionCategory.NORMAL,
        index=True,
        comment="交易类别: normal/reversal/adjustment/fee/system"
    )
    
    # 🔙 撤销相关字段
    reversed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="撤销操作人ID")
    reversed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="撤销时间")
    parent_trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True, comment="父交易trace_id（用于reversal transaction）")
    reversal_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="撤销原因")

    # 状态标记（保留向后兼容）
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已删除（兼容旧逻辑）")
    is_correction: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否为修正记录")

    # 日期
    transaction_date: Mapped[datetime] = mapped_column(index=True, comment="交易日期")
    message_date: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="消息发送时间")
    day_cut_date: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="所属日切日期")


class DailySummary(Base):
    """每日汇总模型 - 多租户隔离"""
    __tablename__ = "daily_summaries"

    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID")
    summary_date: Mapped[datetime] = mapped_column(index=True, comment="汇总日期")

    # 入款统计
    total_deposit_count: Mapped[int] = mapped_column(Integer, default=0, comment="入款笔数")
    total_deposit_amount: Mapped[float] = mapped_column(Float, default=0, comment="入款总额")
    total_deposit_cny: Mapped[float] = mapped_column(Float, default=0, comment="入款人民币总额")

    # 下发统计
    total_withdraw_count: Mapped[int] = mapped_column(Integer, default=0, comment="下发笔数")
    total_withdraw_amount: Mapped[float] = mapped_column(Float, default=0, comment="下发总额")
    total_withdraw_cny: Mapped[float] = mapped_column(Float, default=0, comment="下发人民币总额")

    # 寄存统计
    total_storage_amount: Mapped[float] = mapped_column(Float, default=0, comment="寄存总额")

    # 手续费统计
    total_fee_amount: Mapped[float] = mapped_column(Float, default=0, comment="手续费总额")

    # 净额
    net_amount: Mapped[float] = mapped_column(Float, default=0, comment="净额（入款-下发）")

    # 是否已保存
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已保存")
