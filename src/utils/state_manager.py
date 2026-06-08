"""
用户状态管理工具

提供装饰器和工具函数来管理用户的对话状态
"""
import logging
import time
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# 会话超时时间（秒）：10分钟无操作则自动过期
SESSION_TIMEOUT = 600


def require_state(state_name: str, error_message: str = None):
    """
    要求用户处于特定状态的装饰器
    
    Args:
        state_name: 状态名称（在context.user_data中的key）
        error_message: 不在该状态时的错误提示（可选，暂不使用）
    
    Returns:
        装饰器函数
    
    Example:
        @require_state('waiting_for_broadcast')
        async def handle_broadcast_message(update, context):
            # 只有当 waiting_for_broadcast=True 时才会执行
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            # 检查是否在指定状态
            if not context.user_data.get(state_name):
                logger.debug(
                    f"User {update.effective_user.id if update.effective_user else 'unknown'} "
                    f"not in state '{state_name}', skipping handler"
                )
                return  # 不在该状态，不处理
            
            # 在指定状态，执行handler
            return await func(update, context, *args, **kwargs)
        
        return wrapper
    return decorator


def clear_state(context: ContextTypes.DEFAULT_TYPE, *state_names: str):
    """
    清除用户状态
    
    Args:
        context: Telegram上下文
        state_names: 要清除的状态名称列表
    
    Example:
        clear_state(context, 'waiting_for_broadcast', 'broadcast_chat_id')
    """
    for state_name in state_names:
        context.user_data.pop(state_name, None)


def set_state(context: ContextTypes.DEFAULT_TYPE, state_name: str, value=True):
    """
    设置用户状态
    
    Args:
        context: Telegram上下文
        state_name: 状态名称
        value: 状态值（默认True）
    
    Example:
        set_state(context, 'waiting_for_broadcast')
        set_state(context, 'bot_step', 'token_input')
    """
    context.user_data[state_name] = value


def get_state(context: ContextTypes.DEFAULT_TYPE, state_name: str, default=None):
    """
    获取用户状态
    
    Args:
        context: Telegram上下文
        state_name: 状态名称
        default: 默认值
    
    Returns:
        状态值或默认值
    
    Example:
        if get_state(context, 'waiting_for_broadcast'):
            # 处理广播消息
    """
    return context.user_data.get(state_name, default)



# ============================================================================
# 编辑状态管理（用于欢迎语、关键词等内联菜单编辑）
# ============================================================================

# 用户编辑状态常量
EDIT_STATE_WELCOME_TEXT = "edit_welcome_text"       # 正在编辑欢迎语
EDIT_STATE_WELCOME_MEDIA = "edit_welcome_media"     # 正在编辑欢迎语媒体
EDIT_STATE_WELCOME_BUTTONS = "edit_welcome_buttons" # 正在编辑欢迎语按钮
EDIT_STATE_WELCOME_LIST_ADD = "edit_welcome_list_add" # 正在添加欢迎语列表项
EDIT_STATE_ADD_KEYWORD = "add_keyword"              # 正在添加关键词
EDIT_STATE_ADD_KEYWORD_REPLY = "add_keyword_reply"  # 正在添加关键词回复
EDIT_STATE_KEYWORD_EDIT = "edit_keyword_edit"       # 正在编辑关键词回复

# 编辑状态描述
EDIT_STATE_DESCRIPTIONS = {
    EDIT_STATE_WELCOME_TEXT: "正在编辑欢迎语",
    EDIT_STATE_WELCOME_MEDIA: "正在设置欢迎语媒体",
    EDIT_STATE_WELCOME_BUTTONS: "正在设置欢迎语按钮",
    EDIT_STATE_WELCOME_LIST_ADD: "正在添加欢迎语列表项",
    EDIT_STATE_ADD_KEYWORD: "正在添加关键词",
    EDIT_STATE_ADD_KEYWORD_REPLY: "正在添加关键词回复",
    EDIT_STATE_KEYWORD_EDIT: "正在编辑关键词回复",
}


async def set_edit_state(context: ContextTypes.DEFAULT_TYPE, state: str, data: dict = None):
    """
    设置用户编辑状态（同时记录时间戳用于超时控制）

    Args:
        context: Telegram上下文
        state: 状态名称（使用 EDIT_STATE_* 常量）
        data: 附加数据（可选）

    Example:
        await set_edit_state(context, EDIT_STATE_WELCOME_TEXT)
        await set_edit_state(context, EDIT_STATE_ADD_KEYWORD_REPLY, {"keyword": "你好"})
    """
    context.user_data["edit_state"] = state
    context.user_data["edit_state_timestamp"] = time.time()
    if data:
        context.user_data["edit_state_data"] = data
    else:
        context.user_data.pop("edit_state_data", None)

    logger.debug(f"Set edit state: {state}, data: {data}")


async def get_edit_state(context: ContextTypes.DEFAULT_TYPE) -> tuple:
    """
    获取用户编辑状态（不校验超时）

    Args:
        context: Telegram上下文

    Returns:
        tuple: (状态名称, 附加数据) 或 (None, None)

    Example:
        state, data = await get_edit_state(context)
        if state == EDIT_STATE_WELCOME_TEXT:
            # 处理欢迎语编辑
            pass
    """
    state = context.user_data.get("edit_state")
    data = context.user_data.get("edit_state_data")
    return state, data


async def check_edit_state_timeout(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    检查编辑状态是否超时，如果超时则自动清除状态

    Args:
        context: Telegram上下文

    Returns:
        bool: True = 已超时（状态已被清除），False = 有效（时间戳已刷新）
    """
    state = context.user_data.get("edit_state")
    if not state:
        return True  # 无状态视为已超时/无效

    ts = context.user_data.get("edit_state_timestamp")
    if not ts:
        # 没有时间戳（旧版本遗留），设置时间戳并放行
        context.user_data["edit_state_timestamp"] = time.time()
        return False

    if time.time() - ts > SESSION_TIMEOUT:
        logger.info(f"编辑状态超时: {state}，已自动清除")
        await clear_edit_state(context)
        return True

    # 未超时，刷新时间戳
    context.user_data["edit_state_timestamp"] = time.time()
    return False


async def clear_edit_state(context: ContextTypes.DEFAULT_TYPE):
    """
    清除用户编辑状态

    Args:
        context: Telegram上下文

    Example:
        await clear_edit_state(context)
    """
    context.user_data.pop("edit_state", None)
    context.user_data.pop("edit_state_data", None)
    context.user_data.pop("edit_state_timestamp", None)
    logger.debug("Cleared edit state")


def is_in_edit_state(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    检查用户是否处于编辑状态
    
    Args:
        context: Telegram上下文
    
    Returns:
        bool: 是否处于编辑状态
    """
    return context.user_data.get("edit_state") is not None


def get_edit_state_description(state: str) -> str:
    """
    获取编辑状态的描述
    
    Args:
        state: 状态名称
    
    Returns:
        str: 状态描述
    """
    return EDIT_STATE_DESCRIPTIONS.get(state, "未知状态")
