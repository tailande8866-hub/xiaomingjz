"""
能力系统（Capability System）

职责：
1. Capability Registry（能力注册表）- 统一注册所有能力
2. Capability Resolver（能力解析器）- 运行时自动解析能力集
3. Capability Inheritance（能力继承）- Root Bot → Child Bot → Group → User
4. Capability Override（能力覆盖）- User > Group > Tenant > Global
5. Capability Rollout（灰度发布）- 支持 A/B Testing、Grey Release

这是 Bot OS 的"策略驱动运行时"（Policy Driven Runtime）。
"""
import logging
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class CapabilityScope(Enum):
    """能力作用域"""
    GLOBAL = "global"      # 全局能力
    TENANT = "tenant"      # 租户能力（Bot）
    GROUP = "group"        # 群组能力
    USER = "user"          # 用户能力


class CapabilityType(Enum):
    """能力类型"""
    FEATURE = "feature"           # 功能特性（例如：ai, broadcast）
    RUNTIME = "runtime"           # 运行时特性（例如：v2, dynamic_ui）
    BILLING = "billing"           # 计费特性（例如：pro, enterprise）
    PERMISSION = "permission"     # 权限特性（例如：admin, operator）


@dataclass
class CapabilityDefinition:
    """能力定义"""
    
    name: str                              # 能力名称（例如：'feature.ai'）
    scope: CapabilityScope                 # 作用域
    type: CapabilityType                   # 类型
    description: str = ""                  # 描述
    default_enabled: bool = False          # 默认是否启用
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'scope': self.scope.value,
            'type': self.type.value,
            'description': self.description,
            'default_enabled': self.default_enabled,
            'metadata': self.metadata
        }


@dataclass
class CapabilityGrant:
    """能力授权"""
    
    capability_name: str                   # 能力名称
    enabled: bool                          # 是否启用
    scope: CapabilityScope                 # 作用域
    scope_id: Optional[str] = None         # 作用域 ID（例如：bot_id, group_id, user_id）
    expires_at: Optional[datetime] = None  # 过期时间
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据（例如：rollout_percentage）
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'capability_name': self.capability_name,
            'enabled': self.enabled,
            'scope': self.scope.value,
            'scope_id': self.scope_id,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'metadata': self.metadata
        }


class CapabilityRegistry:
    """
    能力注册表
    
    负责：
    1. 注册所有能力定义
    2. 验证能力名称
    3. 提供能力元数据
    """
    
    def __init__(self):
        # 能力定义：{capability_name: CapabilityDefinition}
        self.definitions: Dict[str, CapabilityDefinition] = {}
        
        # 注册默认能力
        self._register_default_capabilities()
    
    def _register_default_capabilities(self):
        """注册默认能力"""
        
        # === Global Capabilities ===
        self.register(CapabilityDefinition(
            name="runtime.v2",
            scope=CapabilityScope.GLOBAL,
            type=CapabilityType.RUNTIME,
            description="Runtime v2 引擎",
            default_enabled=False
        ))
        
        self.register(CapabilityDefinition(
            name="ui.dynamic",
            scope=CapabilityScope.GLOBAL,
            type=CapabilityType.RUNTIME,
            description="动态 UI 渲染",
            default_enabled=True
        ))
        
        self.register(CapabilityDefinition(
            name="event.pipeline",
            scope=CapabilityScope.GLOBAL,
            type=CapabilityType.RUNTIME,
            description="事件管道保护层",
            default_enabled=True
        ))
        
        # === Tenant Capabilities ===
        self.register(CapabilityDefinition(
            name="feature.ai",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.FEATURE,
            description="AI 功能",
            default_enabled=False
        ))
        
        self.register(CapabilityDefinition(
            name="feature.broadcast",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.FEATURE,
            description="广播功能",
            default_enabled=True
        ))
        
        self.register(CapabilityDefinition(
            name="feature.day_cut",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.FEATURE,
            description="日切功能",
            default_enabled=True
        ))
        
        # 🆕 新增能力
        self.register(CapabilityDefinition(
            name="feature.energy",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.FEATURE,
            description="能量TRX功能",
            default_enabled=False
        ))
        
        self.register(CapabilityDefinition(
            name="feature.usdt_monitor",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.FEATURE,
            description="USDT监听功能",
            default_enabled=False
        ))
        
        self.register(CapabilityDefinition(
            name="billing.pro",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.BILLING,
            description="Pro 套餐",
            default_enabled=False
        ))
        
        self.register(CapabilityDefinition(
            name="billing.enterprise",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.BILLING,
            description="Enterprise 套餐",
            default_enabled=False
        ))
        
        # === Group Capabilities ===
        self.register(CapabilityDefinition(
            name="group.statistics",
            scope=CapabilityScope.GROUP,
            type=CapabilityType.FEATURE,
            description="群组统计",
            default_enabled=True
        ))
        
        self.register(CapabilityDefinition(
            name="group.auto_day_cut",
            scope=CapabilityScope.GROUP,
            type=CapabilityType.FEATURE,
            description="群组自动日切",
            default_enabled=False
        ))
        
        # 🆕 记账控制能力
        self.register(CapabilityDefinition(
            name="accounting:start_stop",
            scope=CapabilityScope.GROUP,
            type=CapabilityType.PERMISSION,
            description="开始/停止记账功能",
            default_enabled=True
        ))
        
        self.register(CapabilityDefinition(
            name="accounting:mute_control",
            scope=CapabilityScope.GROUP,
            type=CapabilityType.PERMISSION,
            description="上课/下课（禁言控制）",
            default_enabled=True
        ))
        
        # 🆕 交易操作能力
        self.register(CapabilityDefinition(
            name="transaction:create",
            scope=CapabilityScope.GROUP,
            type=CapabilityType.PERMISSION,
            description="创建交易记录（入账/下发/USDT）",
            default_enabled=True
        ))
        
        self.register(CapabilityDefinition(
            name="transaction:reverse",
            scope=CapabilityScope.GROUP,
            type=CapabilityType.PERMISSION,
            description="撤销交易记录",
            default_enabled=True
        ))
        
        # 🆕 操作员管理能力
        self.register(CapabilityDefinition(
            name="operator:manage",
            scope=CapabilityScope.GROUP,
            type=CapabilityType.PERMISSION,
            description="管理群组操作员（添加/删除/查看）",
            default_enabled=True
        ))
        
        self.register(CapabilityDefinition(
            name="operator:global_manage",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.PERMISSION,
            description="管理全局操作员",
            default_enabled=False
        ))
        
        # 🆕 管理员管理能力
        self.register(CapabilityDefinition(
            name="admin:manage",
            scope=CapabilityScope.TENANT,
            type=CapabilityType.PERMISSION,
            description="管理租户管理员（添加/删除/查看）",
            default_enabled=False
        ))
        
        # === User Capabilities ===
        self.register(CapabilityDefinition(
            name="user.beta",
            scope=CapabilityScope.USER,
            type=CapabilityType.PERMISSION,
            description="Beta 测试用户",
            default_enabled=False
        ))
        
        self.register(CapabilityDefinition(
            name="user.operator",
            scope=CapabilityScope.USER,
            type=CapabilityType.PERMISSION,
            description="操作人权限",
            default_enabled=False
        ))
    
    def register(self, definition: CapabilityDefinition):
        """
        注册能力定义
        
        Args:
            definition: 能力定义
        """
        self.definitions[definition.name] = definition
        logger.info(f"Registered capability: {definition.name}")
    
    def get_definition(self, name: str) -> Optional[CapabilityDefinition]:
        """
        获取能力定义
        
        Args:
            name: 能力名称
            
        Returns:
            能力定义，如果不存在则返回 None
        """
        return self.definitions.get(name)
    
    def exists(self, name: str) -> bool:
        """
        检查能力是否存在
        
        Args:
            name: 能力名称
            
        Returns:
            是否存在
        """
        return name in self.definitions
    
    def list_capabilities(self, scope: Optional[CapabilityScope] = None, 
                         type: Optional[CapabilityType] = None) -> List[CapabilityDefinition]:
        """
        列出能力
        
        Args:
            scope: 作用域过滤
            type: 类型过滤
            
        Returns:
            能力列表
        """
        capabilities = list(self.definitions.values())
        
        if scope:
            capabilities = [c for c in capabilities if c.scope == scope]
        
        if type:
            capabilities = [c for c in capabilities if c.type == type]
        
        return capabilities


class CapabilityResolver:
    """
    能力解析器
    
    负责：
    1. 解析用户/群组的最终能力集
    2. 处理能力继承（Root Bot → Child Bot → Group → User）
    3. 处理能力覆盖（User > Group > Tenant > Global）
    4. 支持灰度发布（Rollout）
    """
    
    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry
        
        # 能力授权存储：{scope_type: {scope_id: [CapabilityGrant]}}
        self.grants: Dict[str, Dict[str, List[CapabilityGrant]]] = {
            'global': {},
            'tenant': {},
            'group': {},
            'user': {}
        }
    
    def grant_capability(self, grant: CapabilityGrant):
        """
        授予能力
        
        Args:
            grant: 能力授权
        """
        scope_key = grant.scope.value
        scope_id = grant.scope_id or "default"
        
        if scope_key not in self.grants:
            self.grants[scope_key] = {}
        
        if scope_id not in self.grants[scope_key]:
            self.grants[scope_key][scope_id] = []
        
        # 移除旧的授权（如果存在）
        self.grants[scope_key][scope_id] = [
            g for g in self.grants[scope_key][scope_id]
            if g.capability_name != grant.capability_name
        ]
        
        # 添加新授权
        self.grants[scope_key][scope_id].append(grant)
        
        logger.info(
            f"Granted capability {grant.capability_name} to "
            f"{grant.scope.value}:{scope_id} (enabled={grant.enabled})"
        )
        
        # 🆕 触发 Reactive Engine
        try:
            from .reactive_dependency_graph import reactive_engine
            node_id = f"capability.{grant.capability_name}"
            import asyncio
            asyncio.create_task(reactive_engine.on_change(node_id))
        except Exception as e:
            logger.error(f"Error triggering reactive engine for capability {grant.capability_name}: {e}", exc_info=True)
    
    def resolve_capabilities(
        self,
        tenant_id: str,
        group_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Set[str]:
        """
        解析最终能力集
        
        优先级：User > Group > Tenant > Global
        
        Args:
            tenant_id: 租户 ID（Bot ID）
            group_id: 群组 ID（可选）
            user_id: 用户 ID（可选）
            
        Returns:
            启用的能力名称集合
        """
        enabled_capabilities: Set[str] = set()
        
        # 1. Global Capabilities（基础层）
        global_grants = self.grants.get('global', {}).get('default', [])
        for grant in global_grants:
            if not grant.is_expired() and grant.enabled:
                enabled_capabilities.add(grant.capability_name)
        
        # 2. Tenant Capabilities（覆盖 Global）
        tenant_grants = self.grants.get('tenant', {}).get(tenant_id, [])
        for grant in tenant_grants:
            if not grant.is_expired():
                if grant.enabled:
                    enabled_capabilities.add(grant.capability_name)
                else:
                    enabled_capabilities.discard(grant.capability_name)
        
        # 3. Group Capabilities（覆盖 Tenant）
        if group_id:
            group_grants = self.grants.get('group', {}).get(group_id, [])
            for grant in group_grants:
                if not grant.is_expired():
                    if grant.enabled:
                        enabled_capabilities.add(grant.capability_name)
                    else:
                        enabled_capabilities.discard(grant.capability_name)
        
        # 4. User Capabilities（最高优先级，覆盖 Group）
        if user_id:
            user_grants = self.grants.get('user', {}).get(user_id, [])
            for grant in user_grants:
                if not grant.is_expired():
                    if grant.enabled:
                        enabled_capabilities.add(grant.capability_name)
                    else:
                        enabled_capabilities.discard(grant.capability_name)
        
        return enabled_capabilities
    
    def has_capability(
        self,
        capability_name: str,
        tenant_id: str,
        group_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """
        检查是否有某个能力
        
        Args:
            capability_name: 能力名称
            tenant_id: 租户 ID
            group_id: 群组 ID（可选）
            user_id: 用户 ID（可选）
            
        Returns:
            是否有该能力
        """
        enabled_capabilities = self.resolve_capabilities(tenant_id, group_id, user_id)
        return capability_name in enabled_capabilities
    
    def apply_rollout(
        self,
        capability_name: str,
        tenant_id: str,
        rollout_percentage: float
    ):
        """
        应用灰度发布
        
        Args:
            capability_name: 能力名称
            tenant_id: 租户 ID
            rollout_percentage: 灰度百分比（0-100）
        """
        import hashlib
        
        # 使用 tenant_id 的哈希值决定是否启用
        hash_value = int(hashlib.md5(tenant_id.encode()).hexdigest(), 16)
        enabled = (hash_value % 100) < rollout_percentage
        
        grant = CapabilityGrant(
            capability_name=capability_name,
            enabled=enabled,
            scope=CapabilityScope.TENANT,
            scope_id=tenant_id,
            metadata={'rollout_percentage': rollout_percentage}
        )
        
        self.grant_capability(grant)
        
        logger.info(
            f"Applied rollout for {capability_name}: "
            f"tenant={tenant_id}, percentage={rollout_percentage}%, enabled={enabled}"
        )


# 全局实例
capability_registry = CapabilityRegistry()
capability_resolver = CapabilityResolver(capability_registry)
