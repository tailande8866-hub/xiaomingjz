"""
群组状态枚举定义

用于 SaaS Bot Operating System 的群组生命周期管理
"""
from enum import Enum


class GroupStatus(str, Enum):
    """
    群组状态机
    
    状态流转：
    PENDING → ACTIVE (Bot 被管理员/超管拉入群)
    PENDING → UNAUTHORIZED (Bot 被普通用户拉入群)
    ACTIVE → EXPIRED (套餐到期)
    ACTIVE → DISABLED (手动禁用)
    UNAUTHORIZED → ACTIVE (超管授权)
    EXPIRED → ACTIVE (续费)
    DISABLED → ACTIVE (重新启用)
    """
    
    # 待处理 - Bot 刚被拉入群，等待确认授权状态
    PENDING = "PENDING"
    
    # 活跃 - 已授权，正常使用
    ACTIVE = "ACTIVE"
    
    # 未授权 - 普通用户拉群，需要超管授权
    UNAUTHORIZED = "UNAUTHORIZED"
    
    # 已过期 - 套餐到期（SaaS 预留）
    EXPIRED = "EXPIRED"
    
    # 已禁用 - 手动禁用（违规等）
    DISABLED = "DISABLED"
    
    def is_active(self) -> bool:
        """检查群组是否处于可用状态"""
        return self == GroupStatus.ACTIVE
    
    def can_use_features(self) -> bool:
        """检查群组是否可以使用功能"""
        return self == GroupStatus.ACTIVE
    
    def needs_authorization(self) -> bool:
        """检查群组是否需要授权"""
        return self in [GroupStatus.PENDING, GroupStatus.UNAUTHORIZED]
