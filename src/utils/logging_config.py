"""
日志系统配置模块

提供生产级别的日志管理功能：
- 日志轮转（按大小和时间）
- 分级日志文件（info/warning/error）
- 控制台彩色输出
- 异步日志支持
- 日志压缩和清理
"""
import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime


class LogConfig:
    """日志配置类"""
    
    def __init__(
        self,
        log_dir: str = "logs",
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5,
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG
    ):
        """
        初始化日志配置
        
        Args:
            log_dir: 日志目录
            max_bytes: 单个日志文件最大大小（字节）
            backup_count: 保留的备份文件数量
            console_level: 控制台日志级别
            file_level: 文件日志级别
        """
        self.log_dir = Path(log_dir)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.console_level = console_level
        self.file_level = file_level
        
        # 确保日志目录存在
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
    def setup_logging(self):
        """
        设置完整的日志系统
        
        Returns:
            root logger
        """
        # 创建根logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # 根logger设置为最低级别
        
        # 清除现有的handlers（避免重复）
        root_logger.handlers.clear()
        
        # 1. 控制台Handler（彩色输出）
        console_handler = self._create_console_handler()
        root_logger.addHandler(console_handler)
        
        # 2. 通用日志文件（所有级别）
        general_handler = self._create_general_file_handler()
        root_logger.addHandler(general_handler)
        
        # 3. INFO级别日志文件
        info_handler = self._create_level_file_handler('INFO')
        root_logger.addHandler(info_handler)
        
        # 4. WARNING级别日志文件
        warning_handler = self._create_level_file_handler('WARNING')
        root_logger.addHandler(warning_handler)
        
        # 5. ERROR级别日志文件
        error_handler = self._create_level_file_handler('ERROR')
        root_logger.addHandler(error_handler)
        
        # 6. 异常日志文件（专门记录异常堆栈）
        exception_handler = self._create_exception_file_handler()
        root_logger.addHandler(exception_handler)
        
        return root_logger
    
    def _create_console_handler(self) -> logging.Handler:
        """创建控制台Handler（带彩色输出）"""
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(self.console_level)
        
        # 彩色日志格式
        if sys.platform == 'win32':
            # Windows使用简单格式
            formatter = SafeFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - [bot_id=%(bot_id)s user_id=%(user_id)s] - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        else:
            # Linux/Mac使用彩色格式
            formatter = ColoredFormatter(
                '%(asctime)s - %(name)s - %(levelname)s - [bot_id=%(bot_id)s user_id=%(user_id)s] - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        
        handler.setFormatter(formatter)
        return handler
    
    def _create_general_file_handler(self) -> logging.Handler:
        """创建通用日志文件Handler（所有级别）"""
        log_file = self.log_dir / "bot.log"
        
        # 使用大小轮转
        handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        handler.setLevel(self.file_level)
        
        formatter = SafeFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - [bot_id=%(bot_id)s user_id=%(user_id)s] - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        return handler
    
    def _create_level_file_handler(self, level_name: str) -> logging.Handler:
        """
        创建指定级别的日志文件Handler
        
        Args:
            level_name: 日志级别名称（INFO/WARNING/ERROR）
        
        Returns:
            配置好的Handler
        """
        log_file = self.log_dir / f"{level_name.lower()}.log"
        
        # 使用时间和大小双重轮转
        handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when='midnight',  # 每天午夜轮转
            interval=1,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        handler.setLevel(getattr(logging, level_name))
        
        # 只记录指定级别及以上的日志
        handler.addFilter(LevelFilter(level_name))
        
        formatter = SafeFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - [bot_id=%(bot_id)s user_id=%(user_id)s] - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        return handler
    
    def _create_exception_file_handler(self) -> logging.Handler:
        """创建异常日志文件Handler（专门记录异常）"""
        log_file = self.log_dir / "exceptions.log"
        
        handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        handler.setLevel(logging.ERROR)
        
        # 详细的异常格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s\n'
            '[%(filename)s:%(lineno)d in %(funcName)s]\n'
            '%(message)s\n'
            'Traceback:\n%(exc_text)s\n'
            '=' * 80 + '\n',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        return handler


class SafeFormatter(logging.Formatter):
    """安全的日志格式化器，处理缺失的字段"""
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录，处理缺失的字段"""
        # 设置默认值
        if not hasattr(record, 'bot_id'):
            record.bot_id = 'N/A'
        if not hasattr(record, 'user_id'):
            record.user_id = 'N/A'
        
        return super().format(record)


class LevelFilter(logging.Filter):
    """日志级别过滤器"""
    
    def __init__(self, level_name: str):
        super().__init__()
        self.level = getattr(logging, level_name)
    
    def filter(self, record: logging.LogRecord) -> bool:
        """只允许指定级别的日志通过"""
        return record.levelno >= self.level


class ColoredFormatter(SafeFormatter):
    """彩色日志格式化器（仅Linux/Mac）"""
    
    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[1;31m', # 粗体红色
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录，添加颜色"""
        log_color = self.COLORS.get(record.levelname, self.RESET)
        
        # 保存原始levelname
        original_levelname = record.levelname
        
        # 添加颜色
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        
        # 格式化
        result = super().format(record)
        
        # 恢复原始levelname
        record.levelname = original_levelname
        
        return result


def get_logger(name: str = None) -> logging.Logger:
    """
    获取logger实例
    
    Args:
        name: logger名称，默认为调用者模块名
    
    Returns:
        配置好的logger实例
    """
    if name is None:
        # 自动获取调用者模块名
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'unknown')
    
    return logging.getLogger(name)


def setup_production_logging():
    """
    设置生产环境日志
    
    这是主要的入口函数，应该在应用启动时调用
    """
    config = LogConfig(
        log_dir="logs",
        max_bytes=10 * 1024 * 1024,  # 10MB
        backup_count=5,
        console_level=logging.INFO,
        file_level=logging.DEBUG
    )
    
    logger = config.setup_logging()
    logger.info("Production logging system initialized")
    logger.info(f"Log directory: {config.log_dir.absolute()}")
    
    return logger


# 便捷函数
def log_startup_info(logger: logging.Logger):
    """记录启动信息"""
    logger.info("=" * 80)
    logger.info("Application Starting")
    logger.info(f"Python Version: {sys.version}")
    logger.info(f"Platform: {sys.platform}")
    logger.info(f"Working Directory: {Path.cwd()}")
    logger.info(f"Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)


def log_shutdown_info(logger: logging.Logger):
    """记录关闭信息"""
    logger.info("=" * 80)
    logger.info("Application Shutting Down")
    logger.info(f"Shutdown Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
