"""
汇率报价格式化器
负责将原始数据渲染为Telegram富文本消息
"""
from typing import List, Dict
from datetime import datetime


class RateFormatter:
    """汇率报价格式化器"""
    
    # 交易所图标和名称映射
    EXCHANGE_INFO = {
        "htx": {
            "emoji": "🔥",
            "name": "火币 (HTX)",
            "subtitle": "C2C 实时报价"
        },
        "binance": {
            "emoji": "💛",
            "name": "币安 (Binance)",
            "subtitle": "C2C 实时报价"
        }
    }
    
    # 支付方式图标
    PAYMENT_ICONS = {
        "all": "✅",
        "bank": "🏦",
        "alipay": "💙",
        "wechat": "💚"
    }
    
    @staticmethod
    def format_rate_message(
        exchange: str,
        merchants: List[Dict],
        payment_method: str = "all",
        query_time: str = None
    ) -> str:
        """
        格式化汇率报价消息
        
        Args:
            exchange: 交易所名称 (htx/binance)
            merchants: 商家列表
            payment_method: 当前筛选的支付方式
            query_time: 查询时间
        
        Returns:
            格式化后的消息文本
        """
        if not query_time:
            query_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        info = RateFormatter.EXCHANGE_INFO.get(exchange.lower(), {})
        emoji = info.get("emoji", "📊")
        name = info.get("name", exchange.upper())
        subtitle = info.get("subtitle", "报价")
        
        # 构建消息头部（紧凑格式）
        message = f"{emoji} <b>{name}</b> - {subtitle}\n"
        message += f" <b>查询时间</b>: <code>{query_time}</code>\n\n"
        
        if not merchants:
            message += "️ <b>暂无数据</b>"
            return message
        
        # 显示商家列表（紧凑排版）
        message += f"💰 <b>实时报价 (TOP {len(merchants)})</b>\n\n"
        
        for merchant in merchants:
            rank = merchant.get("rank", 0)
            price = merchant.get("price", 0)
            merchant_name = merchant.get("merchant_name", "未知商家")
            completion_rate = merchant.get("completion_rate", 0)
            trade_count = merchant.get("trade_count", 0)
            
            # 格式化价格（保留2位小数，使用等宽字体）
            price_str = f"<code>{price:.2f}</code>"
            
            # 序号徽章
            if rank == 1:
                rank_icon = "🥇"
            elif rank == 2:
                rank_icon = "🥈"
            elif rank == 3:
                rank_icon = "🥉"
            else:
                rank_icon = f"  "
            
            # 商家信息（紧凑格式）
            merchant_info = f"{merchant_name}"
            
            # 组装行（减少空格）
            message += f"{rank_icon}{price_str} {merchant_info}\n"
        
        return message
    
    @staticmethod
    def get_payment_method_name(method: str) -> str:
        """获取支付方式的中文名称"""
        names = {
            "all": "所有",
            "bank": "银行卡",
            "alipay": "支付宝",
            "wechat": "微信"
        }
        return names.get(method, method)
