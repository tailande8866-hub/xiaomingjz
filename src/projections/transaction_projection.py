"""
Transaction Projection Service - 交易投影服务

负责将交易列表投影为用户可见的账单
这是 Financial Rendering Engine 的核心组件
"""
from typing import List, Optional
from decimal import Decimal

from ..models.transaction import Transaction
from ..models.projection import TransactionProjection
from ..services.projection_policy import ProjectionPolicy
from ..services.projection_service import ProjectionService


class TransactionProjectionService:
    """
    交易投影服务
    
    将数据库交易记录投影为用户可见的账单
    """
    
    @staticmethod
    async def project_user_bill(
        transactions: List[Transaction],
        limit: Optional[int] = None
    ) -> List[TransactionProjection]:
        """
        投影用户账单（只显示 SUCCESS + NORMAL）
        
        Args:
            transactions: 交易列表（已通过 Visibility Policy 过滤）
            limit: 限制数量
            
        Returns:
            投影后的账单列表
        """
        # 应用投影转换
        projections = ProjectionService.project_transactions(transactions)
        
        # 限制数量
        if limit:
            projections = projections[:limit]
        
        return projections
    
    @staticmethod
    async def project_audit_bill(
        transactions: List[Transaction],
        limit: Optional[int] = None
    ) -> List[TransactionProjection]:
        """
        投影审计账单（显示所有状态和类别）
        
        Args:
            transactions: 交易列表（已通过 Visibility Policy 过滤）
            limit: 限制数量
            
        Returns:
            投影后的审计账单列表
        """
        # 应用投影转换
        projections = ProjectionService.project_transactions(transactions)
        
        # 限制数量
        if limit:
            projections = projections[:limit]
        
        return projections
    
    @staticmethod
    def render_bill_markdown(
        projections: List[TransactionProjection],
        title: str = "📊 账单明细",
        show_header: bool = True
    ) -> str:
        """
        渲染账单为 Markdown 格式
        
        Args:
            projections: 投影后的账单列表
            title: 标题
            show_header: 是否显示表头
            
        Returns:
            Markdown 格式的账单
        """
        if not projections:
            return f"{title}\n\n暂无交易记录。"
        
        lines = [f"*{title}*"]
        
        if show_header:
            lines.append("")
            lines.append(f"共 {len(projections)} 笔交易")
        
        lines.append("")
        
        # 渲染每笔交易
        for i, projection in enumerate(projections, 1):
            lines.append(f"--- 第 {i} 笔 ---")
            lines.append(projection.to_markdown())
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def render_bill_html(
        projections: List[TransactionProjection],
        title: str = "📊 账单明细",
        show_header: bool = True
    ) -> str:
        """
        渲染账单为 HTML 格式（带蓝色金额和点击跳转）
        
        Args:
            projections: 投影后的账单列表
            title: 标题
            show_header: 是否显示表头
            
        Returns:
            HTML 格式的账单
        """
        if not projections:
            return f"{title}\n\n暂无交易记录。"
        
        lines = [f"<b>{title}</b>"]
        
        if show_header:
            lines.append("")
            lines.append(f"共 {len(projections)} 笔交易")
        
        lines.append("")
        
        # 渲染每笔交易
        for i, projection in enumerate(projections, 1):
            lines.append(f"--- 第 {i} 笔 ---")
            lines.append(projection.to_html())
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def calculate_balance(projections: List[TransactionProjection]) -> Decimal:
        """
        计算余额
        
        Args:
            projections: 投影后的账单列表
            
        Returns:
            余额（Decimal）
        """
        balance = Decimal('0')
        
        for projection in projections:
            # 只统计 SUCCESS + NORMAL 的交易
            if ProjectionPolicy.should_display_in_user_bill(
                projection.display_status.replace("✅ ", "").replace("🔄 ", "").replace("❌ ", "").replace("⏳ ", ""),
                projection.category
            ):
                balance += projection.display_amount
        
        return balance
