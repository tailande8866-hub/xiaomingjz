"""
SaaS自动化售卖系统数据模型
"""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import String, BigInteger, Boolean, Float, Integer, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


# === 🆕 生命周期状态枚举 ===
class BotLifecycleStatus:
    """Bot 生命周期状态"""
    ACTIVE = "ACTIVE"           # 正常运行期（未到期）
    SUSPENDED = "SUSPENDED"     # 暂停状态（已到期，进入宽限期）
    ARCHIVED = "ARCHIVED"       # 归档状态（宽限期结束，停止实例但保留数据）
    DELETED = "DELETED"         # 已删除（长期不续费，真正删除）


# === 🆕 生命周期配置常量 ===
class LifecycleConfig:
    """生命周期管理配置"""
    GRACE_PERIOD_DAYS = 7       # 宽限期：7天（SUSPENDED → ARCHIVED）
    ARCHIVE_AFTER_DAYS = 30     # 归档后保留：30天（ARCHIVED → DELETE 提示）
    DELETE_AFTER_DAYS = 180     # 最终删除：180天（ARCHIVED → DELETED）


class PricingPlan(Base):
    """套餐模型"""
    __tablename__ = "pricing_plans"
    
    # 套餐基本信息
    name: Mapped[str] = mapped_column(String(100), unique=True, comment="套餐名称")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="套餐描述")
    
    # 价格和时长
    price: Mapped[float] = mapped_column(Float, comment="价格（USDT）")
    duration_days: Mapped[int] = mapped_column(Integer, comment="时长（天）")
    
    # 功能限制
    max_bots: Mapped[int] = mapped_column(Integer, default=1, comment="可创建机器人数量")
    max_groups_per_bot: Mapped[int] = mapped_column(Integer, default=5, comment="每个Bot最大群组数")
    
    # 显示设置
    display_order: Mapped[int] = mapped_column(Integer, default=0, comment="显示顺序")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    is_popular: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否热门推荐")
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<PricingPlan(name='{self.name}', price={self.price} USDT, {self.duration_days}天)>"


class Subscription(Base):
    """用户订阅模型"""
    __tablename__ = "subscriptions"
    
    # 用户信息
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, comment="Telegram用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    
    # 订阅信息
    plan_id: Mapped[int] = mapped_column(Integer, comment="套餐ID")
    plan_name: Mapped[str] = mapped_column(String(100), comment="套餐名称")
    
    # 订阅状态
    status: Mapped[str] = mapped_column(String(20), default="active", comment="状态: active, expired, cancelled")
    start_date: Mapped[datetime] = mapped_column(DateTime, comment="订阅开始时间")
    expire_date: Mapped[datetime] = mapped_column(DateTime, comment="订阅到期时间")
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否自动续费")
    
    # 使用统计
    bots_created: Mapped[int] = mapped_column(Integer, default=0, comment="已创建机器人数量")
    total_groups: Mapped[int] = mapped_column(Integer, default=0, comment="总群组数")
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Subscription(telegram_id={self.telegram_id}, status='{self.status}', expires='{self.expire_date}')>"


class BotCreation(Base):
    """机器人创建记录模型（增强版 - 支持无限裂变）"""
    __tablename__ = "bot_creations"
    
    # === 现有字段（保持不变）===
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="Telegram用户ID")
    bot_token: Mapped[str] = mapped_column(String(255), unique=True, comment="机器人Token")
    bot_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="机器人用户名")
    bot_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="机器人名称")
    
    # 实例信息
    instance_id: Mapped[str] = mapped_column(String(50), unique=True, comment="实例ID")
    instance_dir: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="实例目录路径（主 Bot 为 NULL）")
    db_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="数据库路径（主 Bot 为 NULL）")
    env_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="环境变量文件路径（主 Bot 为 NULL）")
    
    # 运行状态
    status: Mapped[str] = mapped_column(String(20), default="creating", comment="状态: creating, running, stopped, error")
    process_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="进程ID")
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后心跳时间")
    
    # 配置信息
    super_admin_id: Mapped[int] = mapped_column(BigInteger, comment="超级管理员Telegram ID")
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="配置信息(JSON)")
    
    # === 🆕 新增字段：树状结构支持 ===
    parent_bot_id: Mapped[Optional[str]] = mapped_column(
        String(50), 
        nullable=True, 
        index=True,
        comment="父 Bot 的 instance_id（NULL 表示根节点/Master Bot）"
    )
    root_bot_id: Mapped[Optional[str]] = mapped_column(
        String(50), 
        nullable=True, 
        index=True,
        comment="根 Bot 的 instance_id（用于快速定位整棵树）"
    )
    tree_depth: Mapped[int] = mapped_column(
        Integer, 
        default=0,
        comment="树深度（Master=0, 子Bot=1, 孙Bot=2...）"
    )
    
    # === 🆕 新增字段：版本管理 ===
    core_version: Mapped[str] = mapped_column(
        String(20), 
        default="1.0.0",
        comment="核心逻辑版本号"
    )
    ui_version: Mapped[str] = mapped_column(
        String(20), 
        default="1.0.0",
        comment="UI 模板版本号"
    )
    permission_version: Mapped[str] = mapped_column(
        String(20), 
        default="1.0.0",
        comment="权限模型版本号"
    )
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="最后同步时间"
    )
    
    # === 🆕 新增字段：配置快照 ===
    config_snapshot: Mapped[Optional[str]] = mapped_column(
        Text, 
        nullable=True,
        comment="创建时的配置快照（JSON格式）"
    )
    
    # === 🆕 新增字段：支付防重放 ===
    order_id: Mapped[Optional[str]] = mapped_column(
        String(50), 
        nullable=True, 
        unique=True,
        index=True,
        comment="关联的订单号（用于防止重复创建）"
    )
    
    # === 🆕 新增字段：生命周期管理 ===
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), 
        default="ACTIVE",
        index=True,
        comment="生命周期状态: ACTIVE/SUSPENDED/ARCHIVED/DELETED"
    )
    expire_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="套餐到期时间（用于生命周期管理）"
    )
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="最后活动时间（用于活跃度检测）"
    )
    grace_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="宽限期结束时间（SUSPENDED → ARCHIVED）"
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="归档时间（ARCHIVED → DELETED 的起点）"
    )
    
    # === 🆕 新增字段：Token状态管理 ===
    token_status: Mapped[str] = mapped_column(
        String(20), 
        default="normal",
        index=True,
        comment="Token状态: normal / invalid / checking"
    )
    token_invalid_reason: Mapped[Optional[str]] = mapped_column(
        String(500), 
        nullable=True,
        comment="Token失效原因"
    )
    token_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="最后检测时间"
    )
    token_invalid_notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="最后通知用户时间"
    )
    rebind_status: Mapped[str] = mapped_column(
        String(20), 
        default="none",
        comment="重绑状态: none / waiting"
    )
    rebind_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, 
        nullable=True,
        comment="正在重绑的用户ID"
    )
    rebind_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="开始等待重绑时间"
    )
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="启动时间")
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="停止时间")
    
    def __repr__(self):
        return f"<BotCreation(bot_username='{self.bot_username}', depth={self.tree_depth}, token_status='{self.token_status}')>"


class TokenCheckLog(Base):
    """Token检测日志表 - 记录每次检测"""
    __tablename__ = "token_check_logs"
    
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="Bot实例ID")
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="触发检测的用户ID")
    check_type: Mapped[str] = mapped_column(
        String(20), 
        index=True,
        comment="检测类型: renew / profile / command / heartbeat / rebind"
    )
    status: Mapped[str] = mapped_column(
        String(20), 
        index=True,
        comment="检测状态: success / failed"
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        String(1000), 
        nullable=True,
        comment="错误信息"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<TokenCheckLog(bot_id='{self.bot_id}', check_type='{self.check_type}', status='{self.status}')>"


class TrialRecord(Base):
    """试用记录模型 - 一次性试用资格管理"""
    __tablename__ = "trial_records"

    # 复合唯一键：bot_id + user_id 确保每个用户在一个Bot下只能申请一次
    bot_id: Mapped[str] = mapped_column(String(50), index=True, comment="Bot实例ID")
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="Telegram用户ID")

    # 试用信息
    apply_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, comment="申请时间")
    start_time: Mapped[datetime] = mapped_column(DateTime, comment="试用开始时间")
    expire_time: Mapped[datetime] = mapped_column(DateTime, comment="试用到期时间")

    # 标记已使用（防止重复申请）
    used_once: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否已使用试用资格")

    # 额外信息（可选）
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    user_fullname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户全名")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TrialRecord(bot_id='{self.bot_id}', user_id={self.user_id}, expire='{self.expire_time}')>"


class PaymentOrder(Base):
    """支付订单模型"""
    __tablename__ = "payment_orders"
    
    # 订单基本信息
    order_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, comment="订单号")
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="Telegram用户ID")
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="用户名")
    
    # 套餐信息
    plan_id: Mapped[int] = mapped_column(Integer, comment="套餐ID")
    plan_name: Mapped[str] = mapped_column(String(100), comment="套餐名称")
    
    # 支付信息
    amount: Mapped[float] = mapped_column(Float, comment="支付金额（USDT）")
    payment_address: Mapped[str] = mapped_column(String(255), comment="收款地址")
    memo: Mapped[str] = mapped_column(String(50), unique=True, index=True, comment="支付备注（用于识别）")
    
    # 订单状态
    status: Mapped[str] = mapped_column(String(20), default="pending", comment="状态: pending, paid, expired, cancelled")
    expire_time: Mapped[datetime] = mapped_column(DateTime, comment="订单过期时间")
    
    # 链上交易信息（支付成功后填充）
    tx_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="交易哈希")
    block_number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="区块高度")
    paid_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="实际支付金额")
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="支付时间")
    
    # 重试和检查记录
    check_count: Mapped[int] = mapped_column(Integer, default=0, comment="检查次数")
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后检查时间")
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<PaymentOrder(order_id='{self.order_id}', status='{self.status}', amount={self.amount} USDT)>"
