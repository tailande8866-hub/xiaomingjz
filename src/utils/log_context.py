"""
日志上下文中间件

职责：
自动为所有日志添加上下文信息（tenant_id, bot_id, route, event_id）

使用方法：
在 handler 或 service 中使用：
    from ..utils.log_context import log_context
    
    with log_context(bot_id="bot_abc123", user_id=123):
        logger.info("处理消息")  # 自动带上 bot_id, user_id
"""
import logging
import contextvars
from typing import Optional
from functools import wraps

# 创建上下文变量
bot_id_ctx = contextvars.ContextVar('bot_id', default=None)
user_id_ctx = contextvars.ContextVar('user_id', default=None)
route_ctx = contextvars.ContextVar('route', default=None)
event_id_ctx = contextvars.ContextVar('event_id', default=None)


class LogContextFilter(logging.Filter):
    """日志过滤器，自动添加上下文信息"""
    
    def filter(self, record):
        # 从上下文中获取值
        record.bot_id = bot_id_ctx.get() or 'N/A'
        record.user_id = user_id_ctx.get() or 'N/A'
        record.route = route_ctx.get() or 'N/A'
        record.event_id = event_id_ctx.get() or 'N/A'
        
        return True


def setup_log_context():
    """设置日志上下文过滤器"""
    
    # 为根 logger 添加过滤器
    root_logger = logging.getLogger()
    
    # 检查是否已经添加过
    for handler in root_logger.handlers:
        if not any(isinstance(f, LogContextFilter) for f in handler.filters):
            handler.addFilter(LogContextFilter())
    
    # 也为 src logger 添加
    src_logger = logging.getLogger('src')
    for handler in src_logger.handlers:
        if not any(isinstance(f, LogContextFilter) for f in handler.filters):
            handler.addFilter(LogContextFilter())


class log_context:
    """日志上下文管理器"""
    
    def __init__(
        self,
        bot_id: Optional[str] = None,
        user_id: Optional[int] = None,
        route: Optional[str] = None,
        event_id: Optional[str] = None
    ):
        self.bot_id = bot_id
        self.user_id = user_id
        self.route = route
        self.event_id = event_id
        
        # 保存旧的上下文值
        self._old_bot_id = None
        self._old_user_id = None
        self._old_route = None
        self._old_event_id = None
    
    def __enter__(self):
        # 保存旧值
        self._old_bot_id = bot_id_ctx.get()
        self._old_user_id = user_id_ctx.get()
        self._old_route = route_ctx.get()
        self._old_event_id = event_id_ctx.get()
        
        # 设置新值
        if self.bot_id is not None:
            bot_id_ctx.set(self.bot_id)
        if self.user_id is not None:
            user_id_ctx.set(self.user_id)
        if self.route is not None:
            route_ctx.set(self.route)
        if self.event_id is not None:
            event_id_ctx.set(self.event_id)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # 恢复旧值
        if self._old_bot_id is not None:
            bot_id_ctx.set(self._old_bot_id)
        if self._old_user_id is not None:
            user_id_ctx.set(self._old_user_id)
        if self._old_route is not None:
            route_ctx.set(self._old_route)
        if self._old_event_id is not None:
            event_id_ctx.set(self._old_event_id)


def with_log_context(func):
    """装饰器：自动为函数添加日志上下文"""
    
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 尝试从参数中提取 bot_id, user_id
        bot_id = kwargs.get('bot_id') or getattr(args[0], 'bot_id', None) if args else None
        user_id = kwargs.get('user_id') or getattr(args[0], 'user_id', None) if args else None
        
        with log_context(bot_id=bot_id, user_id=user_id):
            return await func(*args, **kwargs)
    
    return wrapper


# 初始化
setup_log_context()
