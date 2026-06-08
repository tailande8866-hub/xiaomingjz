"""
配置管理包

提供统一的配置管理接口
"""
from .enhanced_config import config, ConfigCompat, config_manager, ConfigManager

__all__ = [
    "config",  # 向后兼容的配置实例
    "ConfigCompat",  # 向后兼容类
    "config_manager",  # 新的配置管理器
    "ConfigManager",  # 配置管理器类
]
