"""
Summary Projection Service - 汇总投影服务

负责将交易列表投影为汇总统计
这是 Financial Rendering Engine 的汇总组件
"""
from typing import List
from decimal import Decimal
from datetime import datetime

from ..models.transaction import Transaction
from ..models.projection import SummaryProjection
from ..services.projection_policy import ProjectionPolicy
from ..services.projection_service import ProjectionService


class SummaryProjectionService:
    """
    汇总投影服务
    
    将数据库交易记录投影为汇总统计
    """
    
    @staticmethod
    async def project_daily_summary(
        transactions: List[Transaction],
        summary_date: datetime
    ) -> SummaryProjection:
        """
        投影每日汇总
        
        Args:
            transactions: 交易列表（已通过 Visibility Policy 过滤）
            summary_date: 汇总日期
            
        Returns:
            投影后的汇总数据
        """
        # 初始化统计数据
        deposit_count = 0
        deposit_amount = Decimal('0')
        deposit_cny = Decimal('0')
        
        withdraw_count = 0
        withdraw_amount = Decimal('0')
        withdraw_cny = Decimal('0')
        
        storage_amount = Decimal('0')
        total_fee = Decimal('0')
        
        # 遍历交易，累加统计
        for tx in transactions:
            # 只统计 SUCCESS 且不是 REVERSAL 的交易
            if not ProjectionPolicy.should_include_in_summary(tx.status.value if hasattr(tx.status, 'value') else tx.status, 
                                                              tx.category.value if hasattr(tx.category, 'value') else tx.category):
                continue
            
            amount = Decimal(str(tx.amount))
            cny_amount = Decimal(str(tx.cny_amount)) if tx.cny_amount else Decimal('0')
            fee_amount = Decimal(str(tx.fee_amount)) if tx.fee_amount else Decimal('0')
            
            if tx.transaction_type == 'deposit':
                deposit_count += 1
                deposit_amount += amount
                deposit_cny += cny_amount
            elif tx.transaction_type == 'withdraw':
                withdraw_count += 1
                withdraw_amount += amount
                withdraw_cny += cny_amount
            elif tx.transaction_type == 'storage':
                storage_amount += amount
            
            total_fee += fee_amount
        
        # 计算净额
        net_amount = deposit_amount - withdraw_amount
        
        # 创建投影对象
        return ProjectionService.project_summary(
            summary_date=summary_date,
            deposit_count=deposit_count,
            deposit_amount=float(deposit_amount),
            deposit_cny=float(deposit_cny),
            withdraw_count=withdraw_count,
            withdraw_amount=float(withdraw_amount),
            withdraw_cny=float(withdraw_cny),
            storage_amount=float(storage_amount),
            total_fee=float(total_fee),
            net_amount=float(net_amount)
        )
    
    @staticmethod
    def render_summary_markdown(projection: SummaryProjection) -> str:
        """
        渲染汇总为 Markdown 格式
        
        Args:
            projection: 投影后的汇总数据
            
        Returns:
            Markdown 格式的汇总
        """
        return projection.to_markdown()
    
    @staticmethod
    def render_summary_html(projection: SummaryProjection) -> str:
        """
        渲染汇总为 HTML 格式（带蓝色金额）
        
        Args:
            projection: 投影后的汇总数据
            
        Returns:
            HTML 格式的汇总
        """
        return projection.to_html()
