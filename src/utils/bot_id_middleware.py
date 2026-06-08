"""
Bot ID Middleware - 自动注入当前机器人的 bot_id

在所有 Handler 执行前，从 application.bot_data 中获取当前 bot_id
并注入到 handler_data 中，确保所有查询都能正确隔离数据
"""
import os
import logging
from typing import Callable, Dict, Any
from telegram.ext import Application, ContextTypes
from telegram import Update

logger = logging.getLogger(__name__)

# ✅ 全局缓存：确保 bot_id 始终可用（防止 bot_data 被框架重置）
_bot_id_cache = {}
_bot_token_cache = {}


def get_bot_id_from_token(bot_token: str) -> str:
    """
    从 Bot Token 生成唯一的 bot_id
    
    使用 token 的前10个字符作为 bot_id
    例如: 8700502141:AAGdJ9lfsow... -> bot_8700502141
    """
    # 提取 token 的第一部分（数字ID）
    token_prefix = bot_token.split(':')[0]
    return f"bot_{token_prefix}"


def _is_main_bot_runtime() -> bool:
    return os.environ.get("IS_MAIN_BOT", "true").strip().lower() != "false"


def _resolve_runtime_bot_id(application: Application = None) -> str:
    if _is_main_bot_runtime():
        return "main_bot"

    env_bot_id = os.environ.get("INSTANCE_ID", "").strip()
    if env_bot_id:
        return env_bot_id

    if application is not None:
        try:
            bot_token = application.bot.token
            if bot_token:
                return get_bot_id_from_token(bot_token)
        except Exception as e:
            logger.error(f"Failed to get bot_id from token: {e}")

        try:
            bot_id = getattr(application.bot, "id", None)
            if bot_id:
                return f"bot_{bot_id}"
        except Exception:
            pass

    cached_bot_id = _bot_id_cache.get("current")
    if cached_bot_id:
        return cached_bot_id

    return "main_bot"


class BotIdMiddleware:
    """
    Bot ID 中间件
    
    功能：
    1. 在每次请求时自动注入 bot_id 到 context.user_data / context.chat_data
    2. 提供统一的 bot_id 获取方法
    3. 确保所有数据库查询都带上 WHERE bot_id = ? 条件
    """
    
    @staticmethod
    def inject_bot_id(application: Application):
        """
        为 Application 注册 bot_id 注入逻辑
        
        使用方法：
            BotIdMiddleware.inject_bot_id(application)
        """
        
        # ✅ 立即设置 bot_id（不等待 post_init）
        bot_id = _resolve_runtime_bot_id(application)
        
        # 兼容模式：如果没有 INSTANCE_ID，使用 Token 前缀
        if not bot_id:
            try:
                bot_token = application.bot.token
                bot_id = f"bot_{bot_token.split(':')[0]}"
                logger.info(f" Tenant Identity Locked (from token): {bot_id}")
            except Exception as e:
                logger.error(f"⚠️ Failed to get bot_id from token: {e}")
                # 最后保底：使用 bot 的 id
                bot_id = f"bot_{application.bot.id}"
                logger.warning(f"️ Fallback to bot.id: {bot_id}")
        else:
            logger.info(f"🔒 Tenant Identity Locked (from INSTANCE_ID): {bot_id}")
        
        # ✅ 确保 bot_data 字典存在（build() 可能未初始化）
        if not hasattr(application, 'bot_data') or application.bot_data is None:
            application.bot_data = {}
        
        # 立即存储到 bot_data
        application.bot_data['bot_id'] = bot_id
        application.bot_data['bot_token'] = application.bot.token
        
        # ✅ 存储到全局缓存（双重保护）
        _bot_id_cache['current'] = bot_id
        _bot_token_cache['current'] = application.bot.token
        
        logger.info(f"🔒 Tenant Identity Locked: {bot_id}")
        logger.info(f"✅ Bot ID injected into bot_data successfully")
        
        # 在 post_init 中再次确认（防止被覆盖）
        original_post_init = application.post_init
        
        async def wrapped_post_init(app: Application):
            # 确保 bot_data 存在
            if not hasattr(app, 'bot_data') or app.bot_data is None:
                app.bot_data = {}
                    
            # ✅ 修复：强制使用环境变量中的 bot_id，防止从持久化文件恢复旧值
            env_bot_id = _resolve_runtime_bot_id(app)
            if env_bot_id:
                app.bot_data['bot_id'] = env_bot_id
                _bot_id_cache['current'] = env_bot_id
                logger.info(f"✅ post_init: bot_id = {env_bot_id} (from INSTANCE_ID)")
            elif not app.bot_data.get('bot_id'):
                # 如果没有 INSTANCE_ID，使用缓存
                cached_bot_id = _bot_id_cache.get('current', bot_id)
                app.bot_data['bot_id'] = cached_bot_id
                logger.warning(f"⚠️ bot_id was missing in post_init, re-injected: {cached_bot_id}")
                logger.info(f"✅ post_init: bot_id = {app.bot_data.get('bot_id')}")
            else:
                logger.info(f"✅ post_init: bot_id = {app.bot_data.get('bot_id')}")
                    
            # 调用原始的 post_init
            if original_post_init:
                await original_post_init(app)
        
        application.post_init = wrapped_post_init
        
        logger.info("BotIdMiddleware registered successfully")
    
    @staticmethod
    def get_bot_id(context: ContextTypes.DEFAULT_TYPE) -> str:
        """
        从 context 中获取当前 bot_id
        
        Args:
            context: Telegram handler 的 context 对象
            
        Returns:
            str: 当前机器人的 bot_id
            
        Raises:
            ValueError: 如果 bot_id 未初始化
        """
        global _bot_id_cache
        
        # ✅ 优先从 bot_data 获取
        bot_id = context.application.bot_data.get('bot_id')
        
        # ✅ 如果 bot_data 中没有，尝试从全局缓存获取
        if not bot_id:
            bot_id = _bot_id_cache.get('current')
            if bot_id:
                logger.warning(f"⚠️ bot_id not in bot_data, using cache: {bot_id}")
                # 重新注入到 bot_data
                context.application.bot_data['bot_id'] = bot_id
        
        if not bot_id:
            raise ValueError(
                "Bot ID not initialized! "
                "Make sure BotIdMiddleware.inject_bot_id() was called during app initialization."
            )
        
        return bot_id
    
    @staticmethod
    def add_to_handler_data(context: ContextTypes.DEFAULT_TYPE, data: Dict[str, Any]):
        """
        将 bot_id 添加到 handler_data 字典中
        
        Args:
            context: Telegram handler 的 context 对象
            data: handler_data 字典（会被修改）
        """
        try:
            bot_id = BotIdMiddleware.get_bot_id(context)
            data['bot_id'] = bot_id
        except ValueError as e:
            logger.error(f"Failed to inject bot_id: {e}")
            raise


# 便捷函数
def get_current_bot_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    获取当前 bot_id 的便捷函数
    
    Usage:
        bot_id = get_current_bot_id(context)
    """
    try:
        override_bot_id = context.user_data.get('_bot_id_override')
        if override_bot_id:
            return override_bot_id
    except Exception:
        pass

    try:
        return BotIdMiddleware.get_bot_id(context)
    except Exception:
        app = getattr(context, 'application', None)
        if app is not None:
            fallback_bot_id = _resolve_runtime_bot_id(app)
            if not hasattr(app, 'bot_data') or app.bot_data is None:
                app.bot_data = {}
            app.bot_data['bot_id'] = fallback_bot_id
            _bot_id_cache['current'] = fallback_bot_id
            return fallback_bot_id

        try:
            bot = getattr(getattr(context, 'application', None), 'bot', None)
            if bot and getattr(bot, 'token', None):
                fallback_bot_id = get_bot_id_from_token(bot.token)
                app = getattr(context, 'application', None)
                if app is not None:
                    if not hasattr(app, 'bot_data') or app.bot_data is None:
                        app.bot_data = {}
                    app.bot_data['bot_id'] = fallback_bot_id
                _bot_id_cache['current'] = fallback_bot_id
                return fallback_bot_id
        except Exception:
            pass

        try:
            bot = getattr(getattr(context, 'application', None), 'bot', None)
            if bot and getattr(bot, 'id', None):
                fallback_bot_id = f"bot_{bot.id}"
                app = getattr(context, 'application', None)
                if app is not None:
                    if not hasattr(app, 'bot_data') or app.bot_data is None:
                        app.bot_data = {}
                    app.bot_data['bot_id'] = fallback_bot_id
                _bot_id_cache['current'] = fallback_bot_id
                return fallback_bot_id
        except Exception:
            pass

        raise


def get_current_bot_id_from_bot(bot) -> str:
    """
    从 Bot 对象直接获取 bot_id
    
    Args:
        bot: Telegram Bot 实例
        
    Returns:
        str: bot_id (格式: bot_8700502141)
    """
    if _is_main_bot_runtime():
        return "main_bot"
    bot_token = bot.token
    return get_bot_id_from_token(bot_token)
