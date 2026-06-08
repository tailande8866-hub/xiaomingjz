"""
数据模型包
"""
from .database import Base, engine, AsyncSessionLocal, get_db, get_db_session, init_db, close_db
from .group import Group, GroupOperator, UserConfig, PrivateChatUser, CustomKeyword, CustomButton, GroupTag, AdminGlobalConfig, ImpersonationWhitelist, TopicForwardMap, AdminNicknameCache, AdSettings, AdButton
from .group_quota import GroupQuota  # 🆕 额度管理模型
from .group_member_index import GroupMemberIndex  # 🆕 群组成员索引（支持 @username 添加操作人）
from .transaction import Transaction, DailySummary, TransactionStatus, TransactionCategory
from .rule_snapshot import RuleSnapshot  # ✅ 规则快照表（批次锁）
from .admin import Admin
from .saas_auto import PricingPlan, Subscription, BotCreation, PaymentOrder, TrialRecord, TokenCheckLog
from .projection import TransactionProjection, SummaryProjection
from .broadcast_group import BroadcastGroup
from .first_auth_welcome import FirstAuthWelcomeConfig
from .transaction_event import TransactionEvent, TransactionEventType, ActorType  # 🆕 交易事件模型
# from .usdt_listen import UsdtListen, UsdtTxRecord  # 🆕 USDT监听模型（文件暂缺，已注释）
from .wallet_monitor import WatchedAddress, TransactionNotification  # 🆕 钱包监听模型
from .timed_message import TimedMessageSetting, TimedMessageSendLog
from .topic_mode import TopicModeSettings, UserTopic, UserActiveTarget, UserBlock  # 🆕 话题模式模型
from .super_admin import (
    GlobalForwardBlacklist,  # 🆕 全局消息转发黑名单
    SuperAdminSettings,  # 🆕 超管设置
    ClosedUser,  # 🆕 已关闭用户
    PendingProvision,  # 🆕 待开通用户
    SuperAdminMessageState,  # 🆕 超管消息发送状态
)
from .bot_management import BotOperationLog, BotAdmin  # 🆕 机器人状态管理模型

__all__ = [
    "Base",
    "engine",
    "AsyncSessionLocal",
    "get_db",
    "get_db_session",  # 新增：上下文管理器模式
    "init_db",
    "close_db",
    "Group",
    "GroupOperator",
    "UserConfig",
    "PrivateChatUser",
    "CustomKeyword",
    "CustomButton",
    "GroupTag",
    "AdminGlobalConfig",
    "ImpersonationWhitelist",  # 🆕 冒充管理员白名单
    "TopicForwardMap",
    "AdminNicknameCache",  # 🆕 管理员昵称缓存表
    "AdSettings",
    "AdButton",
    "GroupQuota",  # 🆕 额度管理模型
    "GroupMemberIndex",  # 🆕 群组成员索引
    "Admin",
    "PricingPlan",
    "Subscription",
    "BotCreation",
    "PaymentOrder",
    "TrialRecord",  # 🆕 试用记录模型
    "Transaction",
    "DailySummary",
    "TransactionStatus",
    "TransactionCategory",
    "RuleSnapshot",  # ✅ 规则快照表（批次锁）
    "TransactionProjection",
    "SummaryProjection",
    "BroadcastGroup",
    "FirstAuthWelcomeConfig",  #  首次授权欢迎语配置
    "TransactionEvent",  # 🆕 交易事件模型
    "TransactionEventType",  # 事件类型枚举
    "ActorType",  # 参与者类型枚举
    # "UsdtListen",  # 🆕 USDT监听地址（文件暂缺，已注释）
    # "UsdtTxRecord",  # 🆕 USDT交易记录（去重用）（文件暂缺，已注释）
    "WatchedAddress",  # 🆕 监听地址
    "TransactionNotification",  # 🆕 交易通知记录
    "TimedMessageSetting",
    "TimedMessageSendLog",
    "TopicModeSettings",  # 🆕 话题模式配置
    "UserTopic",  # 🆕 用户话题绑定
    "UserActiveTarget",  # 🆕 管理员聊天目标
    "UserBlock",  # 🆕 用户禁言/拉黑
    "GlobalForwardBlacklist",  # 🆕 全局消息转发黑名单
    "SuperAdminSettings",  # 🆕 超管设置
    "ClosedUser",  # 🆕 已关闭用户
    "PendingProvision",  # 🆕 待开通用户
    "SuperAdminMessageState",  # 🆕 超管消息发送状态
    "BotOperationLog",  # 🆕 机器人操作日志
    "BotAdmin",  # 🆕 Bot管理员
]
