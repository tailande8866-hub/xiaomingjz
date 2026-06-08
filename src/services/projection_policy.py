"""
Projection Policy - 投影策略层（金融语义宪法）

定义全局唯一的"有效交易"标准
所有显示逻辑都基于此策略

核心原则：
- 单一事实来源（Single Source of Truth）
- 不允许不同页面使用不同的过滤逻辑
- 防止 Projection Drift（投影漂移）
"""
from typing import List, Optional
from enum import Enum


class ProjectionPolicy(Enum):
    """
    投影策略枚举（金融语义宪法）
    
    所有 Projection 必须显式声明 policy
    禁止在 handler/dashboard/export 中偷偷自己 filter
    """
    USER_VISIBLE = "user_visible"              # 用户可见（账单查询）
    AUDIT_VISIBLE = "audit_visible"            # 审计可见（管理员）
    SUMMARY_VISIBLE = "summary_visible"        # 汇总可见（统计）
    EXPORT_VISIBLE = "export_visible"          # 导出可见（报表）
    DASHBOARD_VISIBLE = "dashboard_visible"    # Dashboard 可见（指标）
    ANALYTICS_VISIBLE = "analytics_visible"    # 分析可见（BI）


class ProjectionPolicy:
    """
    投影策略类
    
    定义不同场景下的交易可见性规则
    """
    
    @staticmethod
    def get_visible_status(policy: ProjectionPolicy) -> List[str]:
        """
        获取指定策略下的可见状态
        
        Args:
            policy: 投影策略
            
        Returns:
            可见状态列表
        """
        if policy == ProjectionPolicy.USER_VISIBLE:
            # 用户只看到 SUCCESS 状态
            return ["success"]
        
        elif policy == ProjectionPolicy.AUDIT_VISIBLE:
            # 审计可以看到所有状态
            return ["success", "failed", "revoked", "pending"]
        
        elif policy == ProjectionPolicy.SUMMARY_VISIBLE:
            # 汇总只统计 SUCCESS
            return ["success"]
        
        elif policy == ProjectionPolicy.EXPORT_VISIBLE:
            # 导出包含 SUCCESS + ADJUSTMENT
            return ["success"]
        
        elif policy == ProjectionPolicy.DASHBOARD_VISIBLE:
            # Dashboard 显示 SUCCESS
            return ["success"]
        
        elif policy == ProjectionPolicy.ANALYTICS_VISIBLE:
            # 分析可以看到所有状态
            return ["success", "failed", "revoked", "pending"]
        
        else:
            raise ValueError(f"Unknown projection policy: {policy}")
    
    @staticmethod
    def get_visible_categories(policy: ProjectionPolicy) -> List[str]:
        """
        获取指定策略下的可见类别
        
        Args:
            policy: 投影策略
            
        Returns:
            可见类别列表
        """
        if policy == ProjectionPolicy.USER_VISIBLE:
            # 用户只看到 NORMAL 类别
            return ["normal"]
        
        elif policy == ProjectionPolicy.AUDIT_VISIBLE:
            # 审计可以看到所有类别
            return ["normal", "reversal", "adjustment", "fee", "system"]
        
        elif policy == ProjectionPolicy.SUMMARY_VISIBLE:
            # 汇总排除 REVERSAL
            return ["normal", "adjustment", "fee", "system"]
        
        elif policy == ProjectionPolicy.EXPORT_VISIBLE:
            # 导出包含 SUCCESS + ADJUSTMENT
            return ["normal", "adjustment"]
        
        elif policy == ProjectionPolicy.DASHBOARD_VISIBLE:
            # Dashboard 排除 REVERSAL
            return ["normal", "adjustment", "fee", "system"]
        
        elif policy == ProjectionPolicy.ANALYTICS_VISIBLE:
            # 分析可以看到所有类别
            return ["normal", "reversal", "adjustment", "fee", "system"]
        
        else:
            raise ValueError(f"Unknown projection policy: {policy}")
    
    @staticmethod
    def should_display_in_user_bill(status: str, category: str) -> bool:
        """
        判断是否应该在用户账单中显示
        
        Args:
            status: 交易状态
            category: 交易类别
            
        Returns:
            是否显示
        """
        return (
            status == "success" and
            category == "normal"
        )
    
    @staticmethod
    def should_include_in_summary(status: str, category: str) -> bool:
        """
        判断是否应该包含在汇总统计中
        
        Args:
            status: 交易状态
            category: 交易类别
            
        Returns:
            是否包含
        """
        return (
            status == "success" and
            category != "reversal"  # 🔑 排除 reversal
        )
    
    @staticmethod
    def format_status_for_display(status: str) -> str:
        """
        格式化状态为显示文本
        
        Args:
            status: 原始状态
            
        Returns:
            显示文本（中文）
        """
        status_map = {
            "success": "✅ 成功",
            "failed": "❌ 失败",
            "revoked": "🔄 已撤销",
            "pending": "⏳ 处理中",
        }
        return status_map.get(status, status)
    
    @staticmethod
    def format_type_for_display(transaction_type: str, category: str) -> str:
        """
        格式化类型为显示文本
        
        Args:
            transaction_type: 原始类型
            category: 业务类别
            
        Returns:
            显示文本（中文）
        """
        # Reversal 交易特殊处理
        if category == "reversal":
            type_map = {
                "reversal_deposit": "↩️ 撤销入款",
                "reversal_withdraw": "↩️ 撤销下发",
                "reversal_storage": "↩️ 撤销寄存",
            }
            return type_map.get(transaction_type, "↩️ 撤销交易")
        
        # 正常交易
        type_map = {
            "deposit": "💰 入款",
            "withdraw": "💸 下发",
            "storage": "📦 寄存",
        }
        return type_map.get(transaction_type, transaction_type)
