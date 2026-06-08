"""
帮助中心内联按钮键盘
严格按照用户要求实现
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def help_keyboard(current_page: str = "index") -> InlineKeyboardMarkup:
    """
    生成帮助中心底部按钮
    
    排版：
    第 1 行：📘 基础功能    👤 操作人管理
    第 2 行：⚙️ 账单显示设置   💰 账单操作
    第 3 行：📁 分组管理    🛠️ 辅助功能
    第 4 行：⬅️ 返回主页    ⛔ 关闭
    """
    
    keyboard = [
        [
            InlineKeyboardButton("📘 基础功能", callback_data="help_basic"),
            InlineKeyboardButton("👤 操作人管理", callback_data="help_operator"),
        ],
        [
            InlineKeyboardButton("⚙️ 账单显示设置", callback_data="help_display"),
            InlineKeyboardButton("💰 账单操作", callback_data="help_billing"),
        ],
        [
            InlineKeyboardButton("📁 分组管理", callback_data="help_group"),
            InlineKeyboardButton("🛠️ 辅助功能", callback_data="help_tools"),
        ],
        [
            InlineKeyboardButton("⏪ 返回", callback_data="help_index"),
            InlineKeyboardButton("⛔ 关闭", callback_data="help_close"),
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)
