"""
Compatibility wrapper for the old USDT listen service name.

The active implementation is WalletMonitorService, backed by
WatchedAddress and TransactionNotification models.
"""
from typing import Optional

from telegram import Bot

from .wallet_monitor_service import WalletMonitorService, wallet_monitor_service


def get_usdt_service() -> WalletMonitorService:
    """Return the active wallet monitor service."""
    return wallet_monitor_service


def init_usdt_service(bot: Bot, api_key: Optional[str] = None) -> WalletMonitorService:
    """Initialize the active wallet monitor service with a Bot instance."""
    wallet_monitor_service.bot = bot
    if api_key:
        wallet_monitor_service.api_key = api_key
    return wallet_monitor_service
