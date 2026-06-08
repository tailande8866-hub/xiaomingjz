"""
核心模块 - Bot Factory 和统一功能注册中心

这个模块实现了 Telegram SaaS 平台的核心架构：
- 所有 Bot 共享同一套功能内核
- 通过配置区分不同 Bot 的行为
- 支持 Polling 和 Webhook 两种模式
"""

from .bot_factory import BotFactory

__all__ = ["BotFactory"]
