"""
链上地址监听系统 - 数据模型

包含：
1. WatchedAddress - 用户监听的地址
2. TransactionNotification - 已通知的交易记录（防重复）
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, BigInteger, Float, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class WatchedAddress(Base):
    """
    监听地址模型 - 多租户隔离
    
    存储用户添加的监听地址及其配置
    """
    __tablename__ = "watched_addresses"
    
    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 关联信息
    group_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="群组ID（0表示私聊用户）")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="用户ID")
    
    # 地址信息
    address: Mapped[str] = mapped_column(String(100), index=True, comment="TRON钱包地址（T开头）")
    alias: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="地址别名（如：财务钱包、冷钱包）")
    
    # 监听配置
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用监听")
    monitor_usdt: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否监听USDT")
    monitor_trx: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否监听TRX")
    
    # 追踪信息
    last_tx_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="最后处理的交易哈希")
    last_check_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后检查时间")
    
    # 统计信息
    total_notifications: Mapped[int] = mapped_column(default=0, comment="累计通知次数")


class TransactionNotification(Base):
    """
    交易通知记录模型 - 多租户隔离
    
    记录已推送的交易，防止重复通知
    """
    __tablename__ = "transaction_notifications"
    
    # 🔑 多租户隔离
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="所属机器人实例ID")
    
    # 交易信息
    tx_hash: Mapped[str] = mapped_column(String(100), unique=True, index=True, comment="交易哈希（唯一标识）")
    address: Mapped[str] = mapped_column(String(100), index=True, comment="监听的地址")
    
    # 转账详情
    amount: Mapped[float] = mapped_column(Float, comment="转账金额")
    token_symbol: Mapped[str] = mapped_column(String(20), comment="代币符号（USDT/TRX）")
    token_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="代币名称")
    
    # 交易方向
    from_address: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="发送方地址")
    to_address: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="接收方地址")
    
    # 通知信息
    notified_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="通知时间")
    notification_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="通知消息ID")
    
    # 关联信息
    watched_address_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="关联的监听地址ID")
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="通知发送的群组ID")
