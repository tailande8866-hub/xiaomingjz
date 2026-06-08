"""
增强配置管理模块

提供：
- 配置验证
- 类型安全
- 敏感信息保护
- 配置热重载支持
- 默认值管理
"""
import os
import re
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _normalize_database_url(database_url: str) -> str:
    raw = (database_url or "").strip() or "sqlite+aiosqlite:///./accounting_bot.db"
    if not raw.startswith("sqlite"):
        return raw

    if raw.startswith("sqlite+aiosqlite:///"):
        path_str = raw[len("sqlite+aiosqlite:///"):]
        path = Path(path_str)
        if not path.is_absolute():
            path = (_project_root() / path).resolve()
        return f"sqlite+aiosqlite:///{path.as_posix()}"

    if raw.startswith("sqlite:///"):
        path_str = raw[len("sqlite:///"):]
        path = Path(path_str)
        if not path.is_absolute():
            path = (_project_root() / path).resolve()
        return f"sqlite:///{path.as_posix()}"

    return raw


@dataclass
class DatabaseConfig:
    """数据库配置"""
    url: str = "sqlite+aiosqlite:///./accounting_bot.db"
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 3600
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        if not self.url:
            errors.append("DATABASE_URL is required")
        if self.pool_size < 1:
            errors.append("POOL_SIZE must be >= 1")
        return errors


@dataclass
class TelegramConfig:
    """Telegram Bot配置"""
    bot_token: str = ""
    bot_username: str = ""
    super_admin_id: int = 0
    instance_id: str = "main_bot"  # 🔒 租户身份标识（多租户隔离核心）
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        if not self.bot_token:
            errors.append("BOT_TOKEN is required")
        if not re.match(r'^\d+:[A-Za-z0-9_-]+$', self.bot_token):
            errors.append("BOT_TOKEN format is invalid")
        if self.super_admin_id <= 0:
            errors.append("SUPER_ADMIN_ID must be > 0")
        return errors


@dataclass
class PaymentConfig:
    """支付配置"""
    usdt_payment_address: str = ""
    tronscan_api_key: str = ""
    payment_timeout: int = 1800  # 30分钟
    min_confirmations: int = 19  # TRON确认数
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        # USDT地址是可选的（如果不使用USDT支付）
        if self.usdt_payment_address and not re.match(r'^T[A-Za-z0-9]{33}$', self.usdt_payment_address):
            errors.append("USDT_PAYMENT_ADDRESS format is invalid (should start with T)")
        return errors


@dataclass
class WebConfig:
    """Web后台配置"""
    enabled: bool = False
    port: int = 8080
    host: str = "0.0.0.0"
    secret_key: str = "change-me-in-production"
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        if self.port < 1 or self.port > 65535:
            errors.append("DASHBOARD_PORT must be between 1 and 65535")
        if self.enabled and self.secret_key == "change-me-in-production":
            errors.append("WEB_SECRET_KEY should be changed in production")
        return errors


@dataclass
class ExchangeConfig:
    """汇率配置"""
    default_currency: str = "USDT"
    default_exchange_rate: float = 7.3
    default_fee_rate: float = 3.0
    huobi_api_key: str = ""
    okex_api_key: str = ""
    
    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        if self.default_exchange_rate <= 0:
            errors.append("DEFAULT_EXCHANGE_RATE must be > 0")
        if self.default_fee_rate < 0 or self.default_fee_rate > 100:
            errors.append("DEFAULT_FEE_RATE must be between 0 and 100")
        return errors


@dataclass
class DisplayConfig:
    """显示配置"""
    default_deposit_display_count: int = 5
    default_withdraw_display_count: int = 5
    timezone: str = "Asia/Shanghai"

    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        if self.default_deposit_display_count < 1:
            errors.append("DEPOSIT_DISPLAY_COUNT must be >= 1")
        if self.default_withdraw_display_count < 1:
            errors.append("WITHDRAW_DISPLAY_COUNT must be >= 1")
        return errors


@dataclass
class TrialConfig:
    """试用配置 - 一次性试用资格"""
    trial_days: int = 15           # 试用天数（默认15天）
    trial_max_bots: int = 1        # 试用期间可创建机器人数量
    trial_max_groups: int = 5      # 试用期间可管理群组数量

    def validate(self) -> List[str]:
        """验证配置"""
        errors = []
        if self.trial_days < 1:
            errors.append("TRIAL_DAYS must be >= 1")
        if self.trial_max_bots < 1:
            errors.append("TRIAL_MAX_BOTS must be >= 1")
        if self.trial_max_groups < 1:
            errors.append("TRIAL_MAX_GROUPS must be >= 1")
        return errors


class ConfigManager:
    """
    配置管理器
    
    提供统一的配置访问接口，支持：
    - 配置验证
    - 类型安全
    - 敏感信息保护
    - 热重载
    """
    
    def __init__(self, env_file: Optional[Path] = None):
        """
        初始化配置管理器
        
        Args:
            env_file: .env文件路径，None则自动检测
        """
        self._env_file = env_file
        self._config_cache: Dict[str, Any] = {}
        self._last_load_time: float = 0
        
        # 加载配置
        self.load_config()
        
        # Do not validate on import. Unit tests and maintenance scripts often
        # import config without a production .env; main.py still validates
        # before the bot actually starts.
        if os.getenv("VALIDATE_CONFIG_ON_IMPORT", "false").lower() == "true":
            self.validate()
    
    def load_config(self):
        """加载配置文件"""
        try:
            # 确定.env文件路径
            if self._env_file is None:
                # ✅ 优先使用当前工作目录下的 .env 文件（支持子机器人实例）
                cwd_env = Path.cwd() / ".env"
                if cwd_env.exists():
                    self._env_file = cwd_env
                else:
                    # 备用：使用项目根目录的 .env 文件
                    current_dir = Path(__file__).parent.parent
                    env_file = current_dir / ".env"
                    if env_file.exists():
                        self._env_file = env_file
                    else:
                        self._env_file = Path(".env")
            
            # 加载环境变量
            if self._env_file.exists():
                load_dotenv(self._env_file, override=True)
                logger.info(f"✅ Loaded config from {self._env_file}")
                logger.info(f"   BOT_TOKEN set: {bool(os.getenv('BOT_TOKEN'))}")
            else:
                logger.warning(f"Config file not found: {self._env_file}")
            
            # 解析配置
            self._parse_config()
            
        except Exception as e:
            logger.error(f"Failed to load config: {e}", exc_info=True)
            raise
    
    def _parse_config(self):
        """解析环境变量为配置对象"""
        # Telegram配置
        self.telegram = TelegramConfig(
            bot_token=os.getenv("BOT_TOKEN", ""),
            bot_username=os.getenv("BOT_USERNAME", ""),
            super_admin_id=int(os.getenv("SUPER_ADMIN_ID", "0")),
            instance_id=os.getenv("INSTANCE_ID", "main_bot")  # 🔒 租户身份标识
        )
        
        # 数据库配置
        self.database = DatabaseConfig(
            url=_normalize_database_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./accounting_bot.db")),
            pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
            pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "3600"))
        )
        
        # 支付配置
        self.payment = PaymentConfig(
            usdt_payment_address=os.getenv("USDT_PAYMENT_ADDRESS", ""),
            tronscan_api_key=os.getenv("TRONSCAN_API_KEY", ""),
            payment_timeout=int(os.getenv("PAYMENT_TIMEOUT", "1800")),
            min_confirmations=int(os.getenv("MIN_CONFIRMATIONS", "19"))
        )
        
        # Web配置
        self.web = WebConfig(
            enabled=os.getenv("DASHBOARD_ENABLED", "false").lower() == "true",
            port=int(os.getenv("DASHBOARD_PORT", "8080")),
            host=os.getenv("DASHBOARD_HOST", "0.0.0.0"),
            secret_key=os.getenv("WEB_SECRET_KEY", "change-me-in-production")
        )
        
        # 汇率配置
        self.exchange = ExchangeConfig(
            default_currency=os.getenv("DEFAULT_CURRENCY", "USDT"),
            default_exchange_rate=float(os.getenv("DEFAULT_EXCHANGE_RATE", "7.3")),
            default_fee_rate=float(os.getenv("DEFAULT_FEE_RATE", "3")),
            huobi_api_key=os.getenv("HUOBI_API_KEY", ""),
            okex_api_key=os.getenv("OKEX_API_KEY", "")
        )
        
        # 显示配置
        self.display = DisplayConfig(
            default_deposit_display_count=int(os.getenv("DEPOSIT_DISPLAY_COUNT", "5")),
            default_withdraw_display_count=int(os.getenv("WITHDRAW_DISPLAY_COUNT", "5")),
            timezone=os.getenv("TIMEZONE", "Asia/Shanghai")
        )

        # 试用配置
        self.trial = TrialConfig(
            trial_days=int(os.getenv("TRIAL_DAYS", "15")),
            trial_max_bots=int(os.getenv("TRIAL_MAX_BOTS", "1")),
            trial_max_groups=int(os.getenv("TRIAL_MAX_GROUPS", "5"))
        )

        logger.info("Config parsed successfully")
    
    def validate(self) -> bool:
        """
        验证所有配置
        
        Returns:
            True如果所有配置有效
        
        Raises:
            ValueError: 如果配置无效
        """
        all_errors = []
        
        # 验证各个配置段
        all_errors.extend(self.telegram.validate())
        all_errors.extend(self.database.validate())
        all_errors.extend(self.payment.validate())
        all_errors.extend(self.web.validate())
        all_errors.extend(self.exchange.validate())
        all_errors.extend(self.display.validate())
        all_errors.extend(self.trial.validate())
        
        if all_errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in all_errors)
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info("Configuration validation passed")
        return True
    
    def reload(self):
        """重新加载配置（热重载）"""
        logger.info("Reloading configuration...")
        self.load_config()
        self.validate()
        logger.info("Configuration reloaded successfully")
    
    def get_sensitive_info_masked(self) -> Dict[str, str]:
        """
        获取脱敏后的配置信息（用于日志记录）
        
        Returns:
            脱敏后的配置字典
        """
        return {
            "BOT_TOKEN": self._mask_secret(self.telegram.bot_token),
            "BOT_USERNAME": self.telegram.bot_username,
            "DATABASE_URL": self._mask_url(self.database.url),
            "SUPER_ADMIN_ID": str(self.telegram.super_admin_id),
            "USDT_PAYMENT_ADDRESS": self._mask_secret(self.payment.usdt_payment_address),
            "DASHBOARD_ENABLED": str(self.web.enabled),
            "DASHBOARD_PORT": str(self.web.port),
        }
    
    @staticmethod
    def _mask_secret(secret: str, show_chars: int = 4) -> str:
        """脱敏敏感信息"""
        if not secret:
            return "(not set)"
        if len(secret) <= show_chars:
            return "****"
        return secret[:show_chars] + "*" * (len(secret) - show_chars)
    
    @staticmethod
    def _mask_url(url: str) -> str:
        """脱敏URL中的密码"""
        if not url:
            return "(not set)"
        # 移除密码部分
        masked = re.sub(r':([^@]+)@', ':***@', url)
        return masked
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于调试）"""
        return {
            "telegram": {
                "bot_token": self.telegram.bot_token,
                "bot_username": self.telegram.bot_username,
                "super_admin_id": self.telegram.super_admin_id,
            },
            "database": {
                "url": self.database.url,
                "pool_size": self.database.pool_size,
                "max_overflow": self.database.max_overflow,
            },
            "payment": {
                "usdt_payment_address": self.payment.usdt_payment_address,
                "payment_timeout": self.payment.payment_timeout,
            },
            "web": {
                "enabled": self.web.enabled,
                "port": self.web.port,
            },
            "exchange": {
                "default_currency": self.exchange.default_currency,
                "default_exchange_rate": self.exchange.default_exchange_rate,
            },
            "display": {
                "timezone": self.display.timezone,
            },
            "trial": {
                "trial_days": self.trial.trial_days,
                "trial_max_bots": self.trial.trial_max_bots,
                "trial_max_groups": self.trial.trial_max_groups,
            }
        }
    
    def save_to_env(self, filepath: Optional[Path] = None):
        """
        保存当前配置到.env文件
        
        Args:
            filepath: 保存路径，None则使用当前路径
        """
        if filepath is None:
            filepath = self._env_file
        
        env_content = []
        
        # Telegram配置
        env_content.append("# Telegram Bot配置")
        env_content.append(f"BOT_TOKEN={self.telegram.bot_token}")
        env_content.append(f"BOT_USERNAME={self.telegram.bot_username}")
        env_content.append(f"SUPER_ADMIN_ID={self.telegram.super_admin_id}")
        env_content.append("")
        
        # 数据库配置
        env_content.append("# 数据库配置")
        env_content.append(f"DATABASE_URL={self.database.url}")
        env_content.append(f"DB_POOL_SIZE={self.database.pool_size}")
        env_content.append(f"DB_MAX_OVERFLOW={self.database.max_overflow}")
        env_content.append("")
        
        # 支付配置
        env_content.append("# 支付配置")
        env_content.append(f"USDT_PAYMENT_ADDRESS={self.payment.usdt_payment_address}")
        env_content.append(f"TRONSCAN_API_KEY={self.payment.tronscan_api_key}")
        env_content.append("")
        
        # Web配置
        env_content.append("# Web后台配置")
        env_content.append(f"DASHBOARD_ENABLED={str(self.web.enabled).lower()}")
        env_content.append(f"DASHBOARD_PORT={self.web.port}")
        env_content.append(f"WEB_SECRET_KEY={self.web.secret_key}")
        env_content.append("")
        
        # 其他配置
        env_content.append("# 其他配置")
        env_content.append(f"DEFAULT_CURRENCY={self.exchange.default_currency}")
        env_content.append(f"DEFAULT_EXCHANGE_RATE={self.exchange.default_exchange_rate}")
        env_content.append(f"DEFAULT_FEE_RATE={self.exchange.default_fee_rate}")
        env_content.append(f"TIMEZONE={self.display.timezone}")
        
        filepath.write_text("\n".join(env_content), encoding="utf-8")
        logger.info(f"Config saved to {filepath}")


# 全局配置管理器实例
config_manager = ConfigManager()

# 向后兼容：提供旧的config接口
class ConfigCompat:
    """向后兼容的配置类"""
    
    @property
    def BOT_TOKEN(self) -> str:
        return config_manager.telegram.bot_token
    
    @property
    def BOT_USERNAME(self) -> str:
        return config_manager.telegram.bot_username
    
    @property
    def DATABASE_URL(self) -> str:
        return config_manager.database.url
    
    @property
    def SUPER_ADMIN_ID(self) -> int:
        return config_manager.telegram.super_admin_id
    
    @property
    def INSTANCE_ID(self) -> str:
        """🔒 租户身份标识（多租户隔离核心）"""
        return config_manager.telegram.instance_id
    
    @property
    def DEFAULT_CURRENCY(self) -> str:
        return config_manager.exchange.default_currency
    
    @property
    def DEFAULT_EXCHANGE_RATE(self) -> float:
        return config_manager.exchange.default_exchange_rate
    
    @property
    def DEFAULT_FEE_RATE(self) -> float:
        return config_manager.exchange.default_fee_rate
    
    @property
    def DASHBOARD_ENABLED(self) -> bool:
        return config_manager.web.enabled
    
    @property
    def DASHBOARD_PORT(self) -> int:
        return config_manager.web.port
    
    @property
    def HUOBI_API_KEY(self) -> str:
        return config_manager.exchange.huobi_api_key
    
    @property
    def OKEX_API_KEY(self) -> str:
        return config_manager.exchange.okex_api_key
    
    @property
    def TRONSCAN_API_KEY(self) -> str:
        return config_manager.payment.tronscan_api_key
    
    @property
    def USDT_PAYMENT_ADDRESS(self) -> str:
        return config_manager.payment.usdt_payment_address
    
    @property
    def TIMEZONE(self) -> str:
        return config_manager.display.timezone
    
    @classmethod
    def validate(cls) -> bool:
        return config_manager.validate()


# 创建全局配置实例（向后兼容）
config = ConfigCompat()
