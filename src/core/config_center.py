"""
配置控制中心（Config Center - Control Plane）

职责：
1. Config Registry（配置注册表）- 统一注册所有配置
2. Config Resolver（配置解析器）- 运行时自动解析最终配置
3. Config Scope（配置作用域）- Global/Tenant/Group/User 层级
4. Config Watcher（配置监听器）- 监听配置变更，触发 Soft Reload
5. Config Snapshot（配置快照）- 保存运行时状态，支持回滚
6. Rollback System（回滚系统）- 快速恢复到历史版本

这是 Bot OS 的"控制平面"（Control Plane），不是简单的配置文件管理器。
"""
import logging
import hashlib
import json
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from copy import deepcopy

logger = logging.getLogger(__name__)


class ConfigScope(Enum):
    """配置作用域"""
    GLOBAL = "global"      # 全局配置
    TENANT = "tenant"      # 租户配置（Bot）
    GROUP = "group"        # 群组配置
    USER = "user"          # 用户配置


@dataclass
class ConfigDefinition:
    """配置定义"""
    
    key: str                               # 配置键（例如：'ui.theme'）
    scope: ConfigScope                     # 作用域
    default_value: Any                     # 默认值
    description: str = ""                  # 描述
    value_type: str = "any"               # 值类型（'string', 'int', 'bool', 'json'）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'key': self.key,
            'scope': self.scope.value,
            'default_value': self.default_value,
            'description': self.description,
            'value_type': self.value_type,
            'metadata': self.metadata
        }


@dataclass
class ConfigValue:
    """配置值"""
    
    key: str                               # 配置键
    value: Any                             # 配置值
    scope: ConfigScope                     # 作用域
    scope_id: Optional[str] = None         # 作用域 ID（例如：bot_id, group_id, user_id）
    updated_at: datetime = field(default_factory=datetime.utcnow)  # 更新时间
    updated_by: Optional[str] = None       # 更新者
    version: int = 1                       # 版本号
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'key': self.key,
            'value': self.value,
            'scope': self.scope.value,
            'scope_id': self.scope_id,
            'updated_at': self.updated_at.isoformat(),
            'updated_by': self.updated_by,
            'version': self.version,
            'metadata': self.metadata
        }


@dataclass
class ConfigSnapshot:
    """配置快照（用于回滚）"""
    
    snapshot_id: str                       # 快照 ID
    tenant_id: str                         # 租户 ID
    version: str                           # 版本号
    checksum: str                          # 校验和
    config_data: Dict[str, Any]            # 配置数据
    created_at: datetime = field(default_factory=datetime.utcnow)  # 创建时间
    created_by: Optional[str] = None       # 创建者
    description: str = ""                  # 描述
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'snapshot_id': self.snapshot_id,
            'tenant_id': self.tenant_id,
            'version': self.version,
            'checksum': self.checksum,
            'config_data': self.config_data,
            'created_at': self.created_at.isoformat(),
            'created_by': self.created_by,
            'description': self.description
        }


class ConfigRegistry:
    """
    配置注册表
    
    负责：
    1. 注册所有配置定义
    2. 验证配置键
    3. 提供配置元数据
    """
    
    def __init__(self):
        # 配置定义：{config_key: ConfigDefinition}
        self.definitions: Dict[str, ConfigDefinition] = {}
        
        # 注册默认配置
        self._register_default_configs()
    
    def _register_default_configs(self):
        """注册默认配置"""
        
        # === Global Configs ===
        self.register(ConfigDefinition(
            key="runtime.version",
            scope=ConfigScope.GLOBAL,
            default_value="1.0.0",
            description="Runtime 版本",
            value_type="string"
        ))
        
        self.register(ConfigDefinition(
            key="ui.theme",
            scope=ConfigScope.GLOBAL,
            default_value="default",
            description="UI 主题",
            value_type="string"
        ))
        
        self.register(ConfigDefinition(
            key="broadcast.limit",
            scope=ConfigScope.GLOBAL,
            default_value=100,
            description="广播消息数量限制",
            value_type="int"
        ))
        
        # === Tenant Configs ===
        self.register(ConfigDefinition(
            key="statistics.enabled",
            scope=ConfigScope.TENANT,
            default_value=True,
            description="启用统计功能",
            value_type="bool"
        ))
        
        self.register(ConfigDefinition(
            key="billing.plan",
            scope=ConfigScope.TENANT,
            default_value="free",
            description="计费套餐",
            value_type="string"
        ))
        
        # === Group Configs ===
        self.register(ConfigDefinition(
            key="group.day_cut_time",
            scope=ConfigScope.GROUP,
            default_value="00:00",
            description="群组日切时间",
            value_type="string"
        ))
        
        # === User Configs ===
        self.register(ConfigDefinition(
            key="user.language",
            scope=ConfigScope.USER,
            default_value="zh-CN",
            description="用户语言",
            value_type="string"
        ))
        
        self.register(ConfigDefinition(
            key="user.currency",
            scope=ConfigScope.USER,
            default_value="CNY",
            description="用户货币",
            value_type="string"
        ))
    
    def register(self, definition: ConfigDefinition):
        """
        注册配置定义
        
        Args:
            definition: 配置定义
        """
        self.definitions[definition.key] = definition
        logger.info(f"Registered config: {definition.key}")
    
    def get_definition(self, key: str) -> Optional[ConfigDefinition]:
        """
        获取配置定义
        
        Args:
            key: 配置键
            
        Returns:
            配置定义，如果不存在则返回 None
        """
        return self.definitions.get(key)
    
    def exists(self, key: str) -> bool:
        """
        检查配置是否存在
        
        Args:
            key: 配置键
            
        Returns:
            是否存在
        """
        return key in self.definitions


class ConfigResolver:
    """
    配置解析器
    
    负责：
    1. 解析最终配置（User > Group > Tenant > Global）
    2. 监听配置变更
    3. 触发 Soft Reload
    """
    
    def __init__(self, registry: ConfigRegistry):
        self.registry = registry
        
        # 配置值存储：{scope_type: {scope_id: {config_key: ConfigValue}}}
        self.values: Dict[str, Dict[str, Dict[str, ConfigValue]]] = {
            'global': {},
            'tenant': {},
            'group': {},
            'user': {}
        }
        
        # 配置变更回调：{config_key: [callback]}
        self.change_callbacks: Dict[str, List[Callable[[str, Any], Awaitable[None]]]] = {}
        
        # 配置快照存储：{tenant_id: [ConfigSnapshot]}
        self.snapshots: Dict[str, List[ConfigSnapshot]] = {}
    
    def set_config(self, config_value: ConfigValue):
        """
        设置配置值
        
        Args:
            config_value: 配置值
        """
        scope_key = config_value.scope.value
        scope_id = config_value.scope_id or "default"
        
        if scope_key not in self.values:
            self.values[scope_key] = {}
        
        if scope_id not in self.values[scope_key]:
            self.values[scope_key][scope_id] = {}
        
        # 更新版本号
        if config_value.key in self.values[scope_key][scope_id]:
            existing = self.values[scope_key][scope_id][config_value.key]
            config_value.version = existing.version + 1
        
        # 保存配置值
        self.values[scope_key][scope_id][config_value.key] = config_value
        
        logger.info(
            f"Set config {config_value.key} for "
            f"{config_value.scope.value}:{scope_id} = {config_value.value}"
        )
        
        # 触发变更回调
        self._trigger_change_callbacks(config_value.key, config_value.value)
    
    def resolve_config(
        self,
        tenant_id: str,
        group_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        解析最终配置
        
        优先级：User > Group > Tenant > Global
        
        Args:
            tenant_id: 租户 ID（Bot ID）
            group_id: 群组 ID（可选）
            user_id: 用户 ID（可选）
            
        Returns:
            最终配置字典
        """
        resolved_config: Dict[str, Any] = {}
        
        # 1. Global Configs（基础层）
        global_configs = self.values.get('global', {}).get('default', {})
        for key, config_value in global_configs.items():
            resolved_config[key] = config_value.value
        
        # 2. Tenant Configs（覆盖 Global）
        tenant_configs = self.values.get('tenant', {}).get(tenant_id, {})
        for key, config_value in tenant_configs.items():
            resolved_config[key] = config_value.value
        
        # 3. Group Configs（覆盖 Tenant）
        if group_id:
            group_configs = self.values.get('group', {}).get(group_id, {})
            for key, config_value in group_configs.items():
                resolved_config[key] = config_value.value
        
        # 4. User Configs（最高优先级，覆盖 Group）
        if user_id:
            user_configs = self.values.get('user', {}).get(user_id, {})
            for key, config_value in user_configs.items():
                resolved_config[key] = config_value.value
        
        return resolved_config
    
    def get_config_value(
        self,
        key: str,
        tenant_id: str,
        group_id: Optional[str] = None,
        user_id: Optional[str] = None,
        default: Any = None
    ) -> Any:
        """
        获取单个配置值
        
        Args:
            key: 配置键
            tenant_id: 租户 ID
            group_id: 群组 ID（可选）
            user_id: 用户 ID（可选）
            default: 默认值
            
        Returns:
            配置值
        """
        resolved_config = self.resolve_config(tenant_id, group_id, user_id)
        return resolved_config.get(key, default)
    
    def register_change_callback(self, config_key: str, callback: Callable[[str, Any], Awaitable[None]]):
        """
        注册配置变更回调
        
        Args:
            config_key: 配置键
            callback: 回调函数，签名：async def callback(config_key, new_value)
        """
        if config_key not in self.change_callbacks:
            self.change_callbacks[config_key] = []
        
        self.change_callbacks[config_key].append(callback)
        logger.info(f"Registered change callback for config: {config_key}")
    
    async def _trigger_change_callbacks(self, config_key: str, new_value: Any):
        """
        触发配置变更回调
        
        Args:
            config_key: 配置键
            new_value: 新值
        """
        # 🆕 触发 Reactive Engine
        try:
            from .reactive_dependency_graph import reactive_engine
            node_id = f"config.{config_key}"
            await reactive_engine.on_change(node_id)
        except Exception as e:
            logger.error(f"Error triggering reactive engine for {config_key}: {e}", exc_info=True)
        
        # 触发旧版回调（向后兼容）
        if config_key in self.change_callbacks:
            for callback in self.change_callbacks[config_key]:
                try:
                    await callback(config_key, new_value)
                except Exception as e:
                    logger.error(f"Error in config change callback for {config_key}: {e}", exc_info=True)
    
    def create_snapshot(self, tenant_id: str, created_by: Optional[str] = None, description: str = "") -> ConfigSnapshot:
        """
        创建配置快照
        
        Args:
            tenant_id: 租户 ID
            created_by: 创建者
            description: 描述
            
        Returns:
            配置快照
        """
        import uuid
        
        # 获取当前配置
        config_data = self.resolve_config(tenant_id)
        
        # 生成快照 ID
        snapshot_id = str(uuid.uuid4())[:8]
        
        # 计算校验和
        checksum = hashlib.md5(json.dumps(config_data, sort_keys=True).encode()).hexdigest()
        
        # 生成版本号
        version = f"v{len(self.snapshots.get(tenant_id, [])) + 1}"
        
        # 创建快照
        snapshot = ConfigSnapshot(
            snapshot_id=snapshot_id,
            tenant_id=tenant_id,
            version=version,
            checksum=checksum,
            config_data=config_data,
            created_by=created_by,
            description=description
        )
        
        # 保存快照
        if tenant_id not in self.snapshots:
            self.snapshots[tenant_id] = []
        
        self.snapshots[tenant_id].append(snapshot)
        
        logger.info(f"Created config snapshot for tenant {tenant_id}: {snapshot_id}")
        
        return snapshot
    
    def rollback(self, tenant_id: str, snapshot_id: str) -> bool:
        """
        回滚到指定快照
        
        Args:
            tenant_id: 租户 ID
            snapshot_id: 快照 ID
            
        Returns:
            是否成功
        """
        if tenant_id not in self.snapshots:
            logger.warning(f"No snapshots found for tenant {tenant_id}")
            return False
        
        # 查找快照
        snapshot = None
        for s in self.snapshots[tenant_id]:
            if s.snapshot_id == snapshot_id:
                snapshot = s
                break
        
        if not snapshot:
            logger.warning(f"Snapshot {snapshot_id} not found for tenant {tenant_id}")
            return False
        
        # 恢复配置
        for key, value in snapshot.config_data.items():
            config_value = ConfigValue(
                key=key,
                value=value,
                scope=ConfigScope.TENANT,
                scope_id=tenant_id
            )
            self.set_config(config_value)
        
        logger.info(f"Rolled back tenant {tenant_id} to snapshot {snapshot_id}")
        
        return True
    
    def list_snapshots(self, tenant_id: str) -> List[ConfigSnapshot]:
        """
        列出租户的所有快照
        
        Args:
            tenant_id: 租户 ID
            
        Returns:
            快照列表
        """
        return self.snapshots.get(tenant_id, [])


# 全局实例
config_registry = ConfigRegistry()
config_resolver = ConfigResolver(config_registry)
