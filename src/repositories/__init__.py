"""
Repository Layer - 统一数据访问层

所有 Repository 自动注入 bot_id，确保多租户数据隔离
"""
from .base_repo import BaseRepo
from .transaction_repo import TransactionRepo
from .group_repo import GroupRepo, GroupOperatorRepo
from .summary_repo import DailySummaryRepo
from .user_config_repo import UserConfigRepo
from .custom_button_repo import CustomButtonRepo
from .topic_mode_repo import TopicModeSettingsRepo, UserTopicRepo, UserActiveTargetRepo, UserBlockRepo
from .super_admin_repo import (
    GlobalForwardBlacklistRepo,
    SuperAdminSettingsRepo,
    ClosedUserRepo,
    PendingProvisionRepo,
    SuperAdminMessageStateRepo,
)
from .bot_management_repo import (
    BotOperationLogRepository,
    BotAdminRepository,
    BotManagementRepository,
)

__all__ = [
    'BaseRepo',
    'TransactionRepo',
    'GroupRepo',
    'GroupOperatorRepo',
    'DailySummaryRepo',
    'UserConfigRepo',
    'CustomButtonRepo',
    'TopicModeSettingsRepo',
    'UserTopicRepo',
    'UserActiveTargetRepo',
    'UserBlockRepo',
    'GlobalForwardBlacklistRepo',
    'SuperAdminSettingsRepo',
    'ClosedUserRepo',
    'PendingProvisionRepo',
    'SuperAdminMessageStateRepo',
    'BotOperationLogRepository',
    'BotAdminRepository',
    'BotManagementRepository',
]
