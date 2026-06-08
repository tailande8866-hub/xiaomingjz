"""
InlineKeyboard 构建器
用于生成汇率查询的筛选按钮
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List


class KeyboardBuilder:
    """汇率查询键盘构建器"""
    
    # 支付方式配置
    PAYMENT_METHODS = [
        ("all", "🟢 所有"),
        ("bank", "🏦 银行卡"),
        ("alipay", "💙 支付宝"),
        ("wechat", "💚 微信")
    ]
    
    @staticmethod
    def build_rate_keyboard(exchange: str, current_method: str = "all") -> InlineKeyboardMarkup:
        """
        构建汇率查询的筛选键盘
        
        Args:
            exchange: 交易所名称 (htx/binance)
            current_method: 当前选中的支付方式
        
        Returns:
            InlineKeyboardMarkup 对象
        """
        keyboard = []
        row = []
        
        for method_code, method_name in KeyboardBuilder.PAYMENT_METHODS:
            # 如果是当前选中的方式，添加对勾标记
            if method_code == current_method:
                display_name = f"✅ {method_name}"
            else:
                display_name = method_name
            
            # callback_data 格式: rate:{exchange}:{method}
            callback_data = f"rate:{exchange}:{method_code}"
            
            button = InlineKeyboardButton(display_name, callback_data=callback_data)
            row.append(button)
            
            # 每4个按钮换一行（或者全部在一行）
            if len(row) >= 4:
                keyboard.append(row)
                row = []
        
        # 添加剩余的按钮
        if row:
            keyboard.append(row)
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def parse_callback_data(callback_data: str) -> dict:
        """
        解析回调数据
        
        Args:
            callback_data: 回调数据字符串 (格式: rate:{exchange}:{method})
        
        Returns:
            包含 exchange 和 method 的字典
        """
        parts = callback_data.split(":")
        
        if len(parts) == 3 and parts[0] == "rate":
            return {
                "exchange": parts[1],
                "method": parts[2]
            }
        
        return {}
