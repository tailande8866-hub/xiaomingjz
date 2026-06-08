"""
限流中间件（轻量级）

职责：
防止 Runtime 被刷爆，保护关键操作

保护对象：
1. 广播消息（防止频繁广播）
2. 创建 Bot（防止恶意创建）
3. Callback 查询（防止快速点击）
4. 高频命令（防止刷屏）

使用方法：
在 handler 中使用：
    from ..utils.rate_limiter import rate_limiter
    
    # 检查限流
    if await rate_limiter.check_limit(user_id, action="broadcast", max_requests=5, window_seconds=3600):
        await context.bot.send_message(chat_id=user_id, text="操作过于频繁，请稍后再试")
        return

装饰器使用：
    from ..utils.rate_limiter import rate_limit_deposit
    
    @rate_limit_deposit
    async def handle_deposit(update, context):
        ...
"""
import logging
import time
from typing import Dict, Optional, Callable
from collections import defaultdict
from functools import wraps

logger = logging.getLogger(__name__)


class RateLimiter:
    """限流器（单例）"""
    
    def __init__(self):
        # 存储每个用户的请求记录
        # 格式：{user_id: {action: [(timestamp, ...)]}}
        self.requests: Dict[int, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
        
        # 默认限流配置
        self.default_limits = {
            "broadcast": {"max_requests": 30, "window_seconds": 3600},  # 每小时 30 次
            "bot.create": {"max_requests": 3, "window_seconds": 86400},  # 每天 3 次
            "callback": {"max_requests": 90, "window_seconds": 60},  # 每分钟 90 次
            "command": {"max_requests": 90, "window_seconds": 60},  # 每分钟 90 次
        }
    
    async def check_limit(
        self,
        user_id: int,
        action: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> bool:
        """
        检查是否超过限流
        
        Args:
            user_id: 用户 ID
            action: 操作类型（broadcast, bot.create, callback, command）
            max_requests: 最大请求次数（可选，使用默认配置）
            window_seconds: 时间窗口（秒）（可选，使用默认配置）
            
        Returns:
            True = 超过限流（应该拒绝）
            False = 未超过限流（允许通过）
        """
        # 获取限流配置
        if action in self.default_limits:
            config = self.default_limits[action]
            max_requests = max_requests or config["max_requests"]
            window_seconds = window_seconds or config["window_seconds"]
        else:
            # 未知操作，使用默认配置
            max_requests = max_requests or 20
            window_seconds = window_seconds or 60
        
        now = time.time()
        window_start = now - window_seconds
        
        # 清理过期记录
        self.requests[user_id][action] = [
            ts for ts in self.requests[user_id][action] if ts > window_start
        ]
        
        # 检查是否超过限制
        current_count = len(self.requests[user_id][action])
        
        if current_count >= max_requests:
            logger.warning(
                f"Rate limit exceeded: user={user_id}, action={action}, "
                f"count={current_count}/{max_requests}, window={window_seconds}s"
            )
            return True  # 超过限流
        
        # 记录本次请求
        self.requests[user_id][action].append(now)
        
        logger.debug(
            f"Rate limit check passed: user={user_id}, action={action}, "
            f"count={current_count + 1}/{max_requests}"
        )
        
        return False  # 未超过限流
    
    async def get_remaining(
        self,
        user_id: int,
        action: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> int:
        """
        获取剩余可用次数
        
        Returns:
            剩余次数
        """
        if action in self.default_limits:
            config = self.default_limits[action]
            max_requests = max_requests or config["max_requests"]
            window_seconds = window_seconds or config["window_seconds"]
        else:
            max_requests = max_requests or 20
            window_seconds = window_seconds or 60
        
        now = time.time()
        window_start = now - window_seconds
        
        # 清理过期记录
        self.requests[user_id][action] = [
            ts for ts in self.requests[user_id][action] if ts > window_start
        ]
        
        current_count = len(self.requests[user_id][action])
        remaining = max(0, max_requests - current_count)
        
        return remaining
    
    def reset(self, user_id: Optional[int] = None, action: Optional[str] = None):
        """
        重置限流记录
        
        Args:
            user_id: 用户 ID（None = 所有用户）
            action: 操作类型（None = 所有操作）
        """
        if user_id is None:
            self.requests.clear()
        elif action is None:
            if user_id in self.requests:
                del self.requests[user_id]
        else:
            if user_id in self.requests and action in self.requests[user_id]:
                del self.requests[user_id][action]


# 全局单例
rate_limiter = RateLimiter()


# === 装饰器函数 ===

def rate_limit_deposit(func: Callable) -> Callable:
    """
    入款操作限流装饰器（3秒限流）
    
    用法：
        @rate_limit_deposit
        async def handle_deposit(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return await func(update, context, *args, **kwargs)
        
        # 检查限流
        if await rate_limiter.check_limit(user_id, action="deposit", max_requests=1, window_seconds=3):
            try:
                await update.message.reply_text(
                    "⚠️ 操作过于频繁，请至少等待 3 秒后再试"
                )
            except Exception:
                pass
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper


def rate_limit_withdraw(func: Callable) -> Callable:
    """
    出款操作限流装饰器（3秒限流）
    
    用法：
        @rate_limit_withdraw
        async def handle_withdraw(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return await func(update, context, *args, **kwargs)
        
        # 检查限流
        if await rate_limiter.check_limit(user_id, action="withdraw", max_requests=1, window_seconds=3):
            try:
                await update.message.reply_text(
                    "⚠️ 操作过于频繁，请至少等待 3 秒后再试"
                )
            except Exception:
                pass
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper


def rate_limit_confirm_payment(func: Callable) -> Callable:
    """
    确认支付限流装饰器（5秒限流）
    
    用法：
        @rate_limit_confirm_payment
        async def confirm_payment(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return await func(update, context, *args, **kwargs)
        
        # 检查限流
        if await rate_limiter.check_limit(user_id, action="confirm_payment", max_requests=1, window_seconds=5):
            try:
                if update.callback_query:
                    await update.callback_query.answer("⚠️ 操作过于频繁，请至少等待 5 秒后再试", show_alert=True)
                elif update.message:
                    await update.message.reply_text("⚠️ 操作过于频繁，请至少等待 5 秒后再试")
            except Exception:
                pass
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper


def rate_limit_payment(func: Callable) -> Callable:
    """
    支付操作限流装饰器（5秒限流）
    
    用法：
        @rate_limit_payment
        async def start_create_bot_flow(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return await func(update, context, *args, **kwargs)
        
        # 检查限流
        if await rate_limiter.check_limit(user_id, action="payment", max_requests=1, window_seconds=5):
            try:
                if update.callback_query:
                    await update.callback_query.answer("⚠️ 操作过于频繁，请至少等待 5 秒后再试", show_alert=True)
                elif update.message:
                    await update.message.reply_text("⚠️ 操作过于频繁，请至少等待 5 秒后再试")
            except Exception:
                pass
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper


def rate_limit_create_bot(func: Callable) -> Callable:
    """
    创建机器人限流装饰器（10秒限流）
    
    用法：
        @rate_limit_create_bot
        async def confirm_create_bot(update, context):
            ...
    """
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return await func(update, context, *args, **kwargs)
        
        # 检查限流
        if await rate_limiter.check_limit(user_id, action="create_bot", max_requests=1, window_seconds=10):
            try:
                if update.callback_query:
                    await update.callback_query.answer("⚠️ 操作过于频繁，请至少等待 10 秒后再试", show_alert=True)
                elif update.message:
                    await update.message.reply_text("⚠️ 操作过于频繁，请至少等待 10 秒后再试")
            except Exception:
                pass
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapper
