"""
工具函数包
"""
from .parser import CommandParser
from .calculator import Calculator
from .formatter import Formatter
from .rate_limiter import rate_limiter, RateLimiter
from .logging_config import get_logger, setup_production_logging, log_startup_info, log_shutdown_info
from . import db_helper  # 数据库辅助函数
from .interaction_helper import (  # 前端交互优化
    show_loading,
    edit_to_success,
    edit_to_error,
    install_callback_alert_patch,
    ErrorMessages,
    send_error_message,
    show_confirmation_dialog,
    show_dangerous_action_confirmation,
    SuccessMessages,
    send_success_message,
    send_info_message,
    send_warning_message
)
from .monitoring import BotMonitor, bot_monitor, start_bot_monitoring, stop_bot_monitoring  # 监控系统
from .tenant_scope import scoped_query, scoped_query_with_filters, scoped_insert, scoped_count  # 租户隔离工具

__all__ = [
    "CommandParser",
    "Calculator",
    "Formatter",
    "rate_limiter",  # 全局限流器实例
    "RateLimiter",  # 限流器类
    "get_logger",  # 获取logger实例
    "setup_production_logging",  # 设置生产日志
    "log_startup_info",  # 记录启动信息
    "log_shutdown_info",  # 记录关闭信息
    "db_helper",  # 数据库辅助函数模块
    # 前端交互优化工具
    "show_loading",
    "edit_to_success",
    "edit_to_error",
    "install_callback_alert_patch",
    "ErrorMessages",
    "send_error_message",
    "show_confirmation_dialog",
    "show_dangerous_action_confirmation",
    "SuccessMessages",
    "send_success_message",
    "send_info_message",
    "send_warning_message",
    # 监控和告警系统
    "BotMonitor",
    "bot_monitor",
    "start_bot_monitoring",
    "stop_bot_monitoring",
    # 租户隔离工具
    "scoped_query",
    "scoped_query_with_filters",
    "scoped_insert",
    "scoped_count",
]

