"""
Projection Service - 财务投影服务

负责将 ORM Transaction 转换为 Projection DTO
这是 Financial Projection Engine 的核心
"""
from decimal import Decimal
from typing import List, Optional
from datetime import datetime

from ..models.transaction import Transaction
from ..models.projection import TransactionProjection, SummaryProjection
from .projection_policy import ProjectionPolicy


class ProjectionService:
    """
    投影服务类
    
    将数据库交易记录投影为用户可见的财务数据
    """
    
    @staticmethod
    def project_transaction(tx: Transaction) -> TransactionProjection:
        """
        将单个 Transaction ORM 对象投影为 TransactionProjection
        
        Args:
            tx: Transaction ORM 对象
            
        Returns:
            TransactionProjection DTO
        """
        # 格式化金额（使用 Decimal 避免浮点误差）
        display_amount = Decimal(str(tx.amount))
        cny_amount = Decimal(str(tx.cny_amount)) if tx.cny_amount else None
        fee_amount = Decimal(str(tx.fee_amount)) if tx.fee_amount else None
        final_amount = Decimal(str(tx.final_amount)) if tx.final_amount else None
        
        # 格式化显示文本
        display_status = ProjectionPolicy.format_status_for_display(tx.status.value if hasattr(tx.status, 'value') else tx.status)
        display_type = ProjectionPolicy.format_type_for_display(
            tx.transaction_type,
            tx.category.value if hasattr(tx.category, 'value') else tx.category
        )
        
        # 构建操作者名称
        operator_name = tx.operator_username or tx.operator_first_name or f"ID:{tx.operator_id}"
        user_name = tx.username or tx.first_name or f"ID:{tx.user_id}"
        
        return TransactionProjection(
            trace_id=tx.trace_id or "",
            projection_policy="default",  # ✅ 默认投影策略
            transaction_id=tx.id,
            display_amount=display_amount,
            currency=tx.currency,
            cny_amount=cny_amount,
            fee_amount=fee_amount,
            final_amount=final_amount,
            display_status=display_status,
            display_type=display_type,
            category=tx.category,
            operator_name=operator_name,
            user_name=user_name,
            created_at=tx.transaction_date,
            message_date=tx.message_date,
            note=tx.note,
            parent_trace_id=tx.parent_trace_id,
            # 🔗 消息链接信息（用于点击跳转）
            group_id=tx.group_id,
            message_id=tx.message_id,
            reply_to_message_id=tx.reply_to_message_id,
        )
    
    @staticmethod
    def project_transactions(transactions: List[Transaction]) -> List[TransactionProjection]:
        """
        批量投影交易列表
        
        Args:
            transactions: Transaction ORM 对象列表
            
        Returns:
            TransactionProjection DTO 列表
        """
        return [ProjectionService.project_transaction(tx) for tx in transactions]
    
    @staticmethod
    def project_summary(
        summary_date: datetime,
        deposit_count: int,
        deposit_amount: float,
        deposit_cny: float,
        withdraw_count: int,
        withdraw_amount: float,
        withdraw_cny: float,
        storage_amount: float,
        total_fee: float,
        net_amount: float
    ) -> SummaryProjection:
        """
        投影汇总数据
        
        Args:
            summary_date: 汇总日期
            deposit_count: 入款笔数
            deposit_amount: 入款金额
            deposit_cny: 入款人民币金额
            withdraw_count: 下发笔数
            withdraw_amount: 下发金额
            withdraw_cny: 下发人民币金额
            storage_amount: 寄存金额
            total_fee: 手续费总额
            net_amount: 净额
            
        Returns:
            SummaryProjection DTO
        """
        return SummaryProjection(
            trace_id=f"summary_{summary_date.strftime('%Y%m%d')}",
            projection_policy="default",
            created_at=datetime.utcnow(),
            summary_date=summary_date,
            deposit_count=deposit_count,
            deposit_amount=Decimal(str(deposit_amount)),
            deposit_cny=Decimal(str(deposit_cny)),
            withdraw_count=withdraw_count,
            withdraw_amount=Decimal(str(withdraw_amount)),
            withdraw_cny=Decimal(str(withdraw_cny)),
            storage_amount=Decimal(str(storage_amount)),
            total_fee=Decimal(str(total_fee)),
            net_amount=Decimal(str(net_amount)),
        )
