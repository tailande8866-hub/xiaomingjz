"""
旧配置管理模块（保留用于向后兼容）
注意：此模块已废弃，请使用 enhanced_config.py
"""
import os
from typing import Optional
from dotenv import load_dotenv

# 加载环境变量
# 尝试加载当前目录的 .env 文件（支持子机器人实例）
from pathlib import Path
current_dir = Path(__file__).parent.parent
env_file = current_dir / ".env"
if env_file.exists():
    load_dotenv(env_file)
else:
    load_dotenv()


class Config:
    """机器人配置类"""

    # Telegram Bot配置
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")
    
    # 🔒 租户身份标识（多租户隔离核心）
    INSTANCE_ID: str = os.getenv("INSTANCE_ID", "main_bot")

    # 数据库配置
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./accounting_bot.db")

    # 管理员配置
    SUPER_ADMIN_ID: int = int(os.getenv("SUPER_ADMIN_ID", "0"))

    # 默认设置
    DEFAULT_CURRENCY: str = os.getenv("DEFAULT_CURRENCY", "USDT")
    DEFAULT_EXCHANGE_RATE: float = float(os.getenv("DEFAULT_EXCHANGE_RATE", "7.3"))
    DEFAULT_FEE_RATE: float = float(os.getenv("DEFAULT_FEE_RATE", "3"))

    # Web后台配置
    DASHBOARD_ENABLED: bool = os.getenv("DASHBOARD_ENABLED", "false").lower() == "true"
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8080"))

    # 外部API密钥
    HUOBI_API_KEY: str = os.getenv("HUOBI_API_KEY", "")
    OKEX_API_KEY: str = os.getenv("OKEX_API_KEY", "")
    TRONSCAN_API_KEY: str = os.getenv("TRONSCAN_API_KEY", "")

    # 账单显示配置
    DEFAULT_DEPOSIT_DISPLAY_COUNT: int = 5
    DEFAULT_WITHDRAW_DISPLAY_COUNT: int = 5

    # 时区配置
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Shanghai")

    @classmethod
    def validate(cls) -> bool:
        """验证必要配置是否存在"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        return True


# 创建全局配置实例
config = Config()
