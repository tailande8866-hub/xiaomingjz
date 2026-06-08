"""
Projection DTO - 财务投影数据传输对象（Universal Financial View Model）

统一财务显示层，所有账单展示都通过此 DTO
用于：Telegram/Web Admin/API/Export/Dashboard/Analytics/BI

核心原则：
- BaseProjectionDTO 作为所有投影的基类
- 显式声明 projection_policy
- 防止 Projection Drift
"""
from datetime import datetime
from typing import Optional
from decimal import Decimal
from dataclasses import dataclass


@dataclass
class BaseProjectionDTO:
    """
    基础投影 DTO（所有投影的基类）
    
    包含所有投影共有的字段
    """
    trace_id: str                          # 追踪 ID
    projection_policy: str                 # 投影策略（显式声明）
    created_at: datetime                   # 创建时间


@dataclass
class TransactionProjection(BaseProjectionDTO):
    """
    交易投影对象（用户看到的“财务现实”）
    
    所有显示逻辑都基于此 DTO
    """
    
    # 🔑 核心标识（从 BaseProjectionDTO 继承：trace_id, projection_policy, created_at）
    transaction_id: int                    # 交易 ID
    
    # 💰 金额显示
    display_amount: Decimal          # 显示金额（已格式化）
    currency: str                    # 币种
    cny_amount: Optional[Decimal]    # 人民币金额
    fee_amount: Optional[Decimal]    # 手续费
    final_amount: Optional[Decimal]  # 最终金额
    
    # 📊 状态显示
    display_status: str              # 显示状态（中文）
    display_type: str                # 显示类型（中文）
    category: str                    # 业务类别
    
    # 👤 操作者信息
    operator_name: str               # 操作者显示名称
    user_name: str                   # 用户显示名称
    
    # ⏰ 时间信息
    created_at: datetime             # 创建时间
    message_date: Optional[datetime] # 消息时间
    
    # 📝 备注
    note: Optional[str]              # 备注
    
    # 🔗 关联信息
    parent_trace_id: Optional[str]   # 父交易trace_id（reversal时）
    
    # 🔗 消息链接信息（用于点击跳转）
    group_id: Optional[int] = None   # 群组ID
    message_id: Optional[int] = None # 消息ID
    reply_to_message_id: Optional[int] = None  # 回复的消息ID
    
    def to_markdown(self) -> str:
        """
        转换为 Telegram Markdown 格式
        
        Returns:
            Markdown 格式的账单记录
        """
        lines = [
            f"💰 *{self.display_type}* | {self.display_status}",
            f"📅 `{self.created_at.strftime('%Y-%m-%d %H:%M:%S')}`",
            f"👤 操作者: `{self.operator_name}`",
            f"💵 金额: `{self.display_amount} {self.currency}`",
        ]
        
        if self.cny_amount:
            lines.append(f"💴 人民币: `{self.cny_amount} CNY`")
        
        if self.fee_amount and self.fee_amount > 0:
            lines.append(f"📉 手续费: `{self.fee_amount} {self.currency}`")
        
        if self.final_amount:
            lines.append(f"✅ 最终金额: `{self.final_amount} {self.currency}`")
        
        if self.note:
            lines.append(f"📝 备注: `{self.note}`")
        
        if self.parent_trace_id:
            lines.append(f"🔗 关联交易: `{self.parent_trace_id}`")
        
        lines.append(f"🆔 Trace ID: `{self.trace_id}`")
        
        return "\n".join(lines)
    
    def to_html(self) -> str:
        """
        转换为 Telegram HTML 格式（带蓝色金额和点击跳转）
        
        Returns:
            HTML 格式的账单记录
        """
        # 构建消息链接
        message_link = self._build_message_link()
        
        # 格式化金额（蓝色 + 可点击）
        amount_str = f"{self.display_amount} {self.currency}"
        if message_link:
            # 使用HTML格式，粗体 + 可点击链接（Telegram不支持自定义颜色）
            amount_display = f'<a href="{message_link}"><b>{amount_str}</b></a>'
        else:
            amount_display = f'<b>{amount_str}</b>'
        
        lines = [
            f"💰 <b>{self.display_type}</b> | {self.display_status}",
            f"📅 <code>{self.created_at.strftime('%Y-%m-%d %H:%M:%S')}</code>",
            f"👤 操作者: <code>{self.operator_name}</code>",
            f"💵 金额: {amount_display}",
        ]
        
        if self.cny_amount:
            cny_str = f"{self.cny_amount} CNY"
            if message_link:
                # 使用HTML格式，粗体 + 可点击链接（Telegram不支持自定义颜色）
                cny_display = f'<a href="{message_link}"><b>{cny_str}</b></a>'
            else:
                cny_display = f'<b>{cny_str}</b>'
            lines.append(f"💴 人民币: {cny_display}")
        
        if self.fee_amount and self.fee_amount > 0:
            lines.append(f"📉 手续费: <code>{self.fee_amount} {self.currency}</code>")
        
        if self.final_amount:
            lines.append(f"✅ 最终金额: <code>{self.final_amount} {self.currency}</code>")
        
        if self.note:
            lines.append(f"📝 备注: <code>{self.note}</code>")
        
        if self.parent_trace_id:
            lines.append(f"🔗 关联交易: <code>{self.parent_trace_id}</code>")
        
        lines.append(f"🆔 Trace ID: <code>{self.trace_id}</code>")
        
        return "\n".join(lines)
    
    def _build_message_link(self) -> Optional[str]:
        """
        构建消息链接
        
        Returns:
            消息链接或None
        """
        if not self.group_id or not self.message_id:
            return None
        
        chat_id_str = str(self.group_id)
        if chat_id_str.startswith("-100"):
            chat_id_for_link = chat_id_str[4:]  # 去掉 "-100" 前缀
        else:
            chat_id_for_link = chat_id_str.replace("-", "")
        
        # 优先使用回复的消息ID
        target_id = self.reply_to_message_id or self.message_id
        if target_id:
            return f"https://t.me/c/{chat_id_for_link}/{target_id}"
        
        return None
    
    def to_dict(self) -> dict:
        """
        转换为字典（用于 API/Export）
        
        Returns:
            字典格式的交易数据
        """
        return {
            "trace_id": self.trace_id,
            "transaction_id": self.transaction_id,
            "display_amount": float(self.display_amount),
            "currency": self.currency,
            "cny_amount": float(self.cny_amount) if self.cny_amount else None,
            "fee_amount": float(self.fee_amount) if self.fee_amount else None,
            "final_amount": float(self.final_amount) if self.final_amount else None,
            "display_status": self.display_status,
            "display_type": self.display_type,
            "category": self.category,
            "operator_name": self.operator_name,
            "user_name": self.user_name,
            "created_at": self.created_at.isoformat(),
            "message_date": self.message_date.isoformat() if self.message_date else None,
            "note": self.note,
            "parent_trace_id": self.parent_trace_id,
        }


@dataclass
class SummaryProjection(BaseProjectionDTO):
    """
    汇总投影对象
    
    用于：每日汇总、财务报表、Dashboard
    """
    
    # 📅 日期（从 BaseProjectionDTO 继承：trace_id, projection_policy, created_at）
    summary_date: datetime                 # 汇总日期
    
    # 💰 入款统计
    deposit_count: int
    deposit_amount: Decimal
    deposit_cny: Decimal
    
    # 💸 下发统计
    withdraw_count: int
    withdraw_amount: Decimal
    withdraw_cny: Decimal
    
    # 📦 寄存统计
    storage_amount: Decimal
    
    # 📉 手续费统计
    total_fee: Decimal
    
    # 💵 净额
    net_amount: Decimal
    
    def to_markdown(self) -> str:
        """转换为 Telegram Markdown 格式"""
        lines = [
            f"📊 *每日汇总* | {self.summary_date.strftime('%Y-%m-%d')}",
            f"",
            f"💰 *入款*",
            f"  笔数: `{self.deposit_count}`",
            f"  金额: `{self.deposit_amount} USDT`",
            f"  人民币: `{self.deposit_cny} CNY`",
            f"",
            f"💸 *下发*",
            f"  笔数: `{self.withdraw_count}`",
            f"  金额: `{self.withdraw_amount} USDT`",
            f"  人民币: `{self.withdraw_cny} CNY`",
            f"",
            f"📦 *寄存*: `{self.storage_amount} USDT`",
            f"📉 *手续费*: `{self.total_fee} USDT`",
            f"",
            f"💵 *净额*: `{self.net_amount} USDT`",
        ]
        
        return "\n".join(lines)
    
    def to_html(self) -> str:
        """转换为 Telegram HTML 格式（带蓝色金额）"""
        # 格式化金额为蓝色
        # 使用HTML格式，粗体突出显示（Telegram不支持自定义颜色）
        deposit_amount_str = f'<b>{self.deposit_amount} USDT</b>'
        withdraw_amount_str = f'<b>{self.withdraw_amount} USDT</b>'
        net_amount_str = f'<b>{self.net_amount} USDT</b>'
        
        lines = [
            f"📊 <b>每日汇总</b> | {self.summary_date.strftime('%Y-%m-%d')}",
            f"",
            f"💰 <b>入款</b>",
            f"  笔数: <code>{self.deposit_count}</code>",
            f"  金额: {deposit_amount_str}",
            f"  人民币: <code>{self.deposit_cny} CNY</code>",
            f"",
            f"💸 <b>下发</b>",
            f"  笔数: <code>{self.withdraw_count}</code>",
            f"  金额: {withdraw_amount_str}",
            f"  人民币: <code>{self.withdraw_cny} CNY</code>",
            f"",
            f"📦 <b>寄存</b>: <code>{self.storage_amount} USDT</code>",
            f"📉 <b>手续费</b>: <code>{self.total_fee} USDT</code>",
            f"",
            f"💵 <b>净额</b>: {net_amount_str}",
        ]
        
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "summary_date": self.summary_date.isoformat(),
            "deposit_count": self.deposit_count,
            "deposit_amount": float(self.deposit_amount),
            "deposit_cny": float(self.deposit_cny),
            "withdraw_count": self.withdraw_count,
            "withdraw_amount": float(self.withdraw_amount),
            "withdraw_cny": float(self.withdraw_cny),
            "storage_amount": float(self.storage_amount),
            "total_fee": float(self.total_fee),
            "net_amount": float(self.net_amount),
        }
