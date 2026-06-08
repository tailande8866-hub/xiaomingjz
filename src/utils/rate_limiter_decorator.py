"""
限流装饰器

使用方法：
在 handler 函数上添加装饰器：
    from ..utils.rate_limiter_decorator import rate_limit
    
    @rate_limit(action="command", max_requests=20, window_seconds=60)
    async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        ...
"""
import logging
from functools import wraps
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def rate_limit(
    action: str = "command",
    max_requests: Optional[int] = None,
    window_seconds: Optional[int] = None,
):
    """
    限流装饰器
    
    Args:
        action: 操作类型（command, broadcast, callback, bot.create）
        max_requests: 最大请求次数（可选，使用默认配置）
        window_seconds: 时间窗口（秒）（可选，使用默认配置）
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            # 获取用户 ID
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                logger.warning(f"No user_id in {func.__name__}")
                return await func(update, context, *args, **kwargs)
            
            # 检查限流
            from .rate_limiter import rate_limiter
            if await rate_limiter.check_limit(user_id, action=action, max_requests=max_requests, window_seconds=window_seconds):
                remaining = await rate_limiter.get_remaining(user_id, action=action, max_requests=max_requests, window_seconds=window_seconds)
                
                # 发送限流提示
                if update.callback_query:
                    try:
                        await update.callback_query.answer(
                            f"⚠️ 操作过于频繁\n剩余次数：{remaining} 次",
                            show_alert=True
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send callback answer: {e}")
                elif update.message:
                    try:
                        await update.message.reply_text(
                            f"⚠️ 操作过于频繁\n剩余次数：{remaining} 次"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send message: {e}")
                
                return None
            
            # 通过限流，执行原函数
            return await func(update, context, *args, **kwargs)
        
        return wrapper
    return decorator
