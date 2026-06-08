"""
运行时状态存储（Runtime State Store）

职责：
1. 统一保存租户运行时状态
2. 管理 active capabilities
3. 管理 loaded schemas
4. 管理 cache version
5. 管理 runtime snapshot
6. 管理 dependency state

这是 Bot OS 的"状态中枢"，解决 Runtime State Explosion 问题。
"""
import logging
import hashlib
import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from copy import deepcopy

logger = logging.getLogger(__name__)


@dataclass
class TenantRuntimeState:
    """租户运行时状态"""
    
    tenant_id: str                           # 租户 ID（Bot ID）
    version: str = "1.0.0"                   # 版本号
    created_at: datetime = field(default_factory=datetime.utcnow)  # 创建时间
    updated_at: datetime = field(default_factory=datetime.utcnow)  # 更新时间
    
    # === 核心状态 ===
    active_capabilities: Dict[str, bool] = field(default_factory=dict)  # 激活的能力
    loaded_schemas: Dict[str, str] = field(default_factory=dict)        # 已加载的 Schema（schema_id → version）
    cache_version: str = "v1"                # 缓存版本
    runtime_snapshot: Optional[Dict[str, Any]] = None  # 运行时快照
    dependency_state: Dict[str, str] = field(default_factory=dict)  # 依赖状态（node_id → status）
    
    # === 元数据 ===
    last_config_update: Optional[datetime] = None   # 最后配置更新时间
    last_capability_update: Optional[datetime] = None  # 最后能力更新时间
    last_schema_refresh: Optional[datetime] = None     # 最后 Schema 刷新时间
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'tenant_id': self.tenant_id,
            'version': self.version,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'active_capabilities': self.active_capabilities,
            'loaded_schemas': self.loaded_schemas,
            'cache_version': self.cache_version,
            'runtime_snapshot': self.runtime_snapshot,
            'dependency_state': self.dependency_state,
            'last_config_update': self.last_config_update.isoformat() if self.last_config_update else None,
            'last_capability_update': self.last_capability_update.isoformat() if self.last_capability_update else None,
            'last_schema_refresh': self.last_schema_refresh.isoformat() if self.last_schema_refresh else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TenantRuntimeState':
        """从字典恢复"""
        return cls(
            tenant_id=data['tenant_id'],
            version=data.get('version', '1.0.0'),
            created_at=datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at'],
            updated_at=datetime.fromisoformat(data['updated_at']) if isinstance(data['updated_at'], str) else data['updated_at'],
            active_capabilities=data.get('active_capabilities', {}),
            loaded_schemas=data.get('loaded_schemas', {}),
            cache_version=data.get('cache_version', 'v1'),
            runtime_snapshot=data.get('runtime_snapshot'),
            dependency_state=data.get('dependency_state', {}),
            last_config_update=datetime.fromisoformat(data['last_config_update']) if data.get('last_config_update') else None,
            last_capability_update=datetime.fromisoformat(data['last_capability_update']) if data.get('last_capability_update') else None,
            last_schema_refresh=datetime.fromisoformat(data['last_schema_refresh']) if data.get('last_schema_refresh') else None,
        )
    
    def compute_checksum(self) -> str:
        """计算状态校验和（用于快速比对）"""
        state_str = json.dumps({
            'active_capabilities': self.active_capabilities,
            'loaded_schemas': self.loaded_schemas,
            'cache_version': self.cache_version,
            'dependency_state': self.dependency_state,
        }, sort_keys=True)
        
        return hashlib.md5(state_str.encode()).hexdigest()


class RuntimeStateStore:
    """
    运行时状态存储（单例）
    
    统一管理所有租户的运行时状态，防止状态爆炸。
    """
    
    def __init__(self):
        # 租户状态存储（tenant_id → TenantRuntimeState）
        self._states: Dict[str, TenantRuntimeState] = {}
        
        # 全局状态（用于跨租户共享的状态）
        self._global_state: Dict[str, Any] = {}
        
        # 状态监听器（用于通知状态变更）
        self._state_listeners: Dict[str, List] = {}
        
        logger.info("Runtime State Store initialized")
    
    async def get_or_create_state(self, tenant_id: str) -> TenantRuntimeState:
        """
        获取或创建租户状态
        
        Args:
            tenant_id: 租户 ID
            
        Returns:
            租户运行时状态
        """
        if tenant_id not in self._states:
            self._states[tenant_id] = TenantRuntimeState(tenant_id=tenant_id)
            logger.info(f"Created new runtime state for tenant: {tenant_id}")
        
        return self._states[tenant_id]
    
    async def get_state(self, tenant_id: str) -> Optional[TenantRuntimeState]:
        """
        获取租户状态
        
        Args:
            tenant_id: 租户 ID
            
        Returns:
            租户运行时状态，不存在则返回 None
        """
        return self._states.get(tenant_id)
    
    async def update_state(self, tenant_id: str, updates: Dict[str, Any]):
        """
        更新租户状态
        
        Args:
            tenant_id: 租户 ID
            updates: 更新字段字典
        """
        state = await self.get_or_create_state(tenant_id)
        
        # 更新字段
        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)
        
        # 更新时间戳
        state.updated_at = datetime.utcnow()
        
        logger.debug(f"Updated runtime state for tenant: {tenant_id}")
    
    async def set_active_capability(self, tenant_id: str, capability_name: str, enabled: bool):
        """
        设置激活的能力
        
        Args:
            tenant_id: 租户 ID
            capability_name: 能力名称
            enabled: 是否启用
        """
        state = await self.get_or_create_state(tenant_id)
        state.active_capabilities[capability_name] = enabled
        state.updated_at = datetime.utcnow()
        state.last_capability_update = datetime.utcnow()
        
        logger.info(f"Set capability {capability_name}={enabled} for tenant: {tenant_id}")
    
    async def set_loaded_schema(self, tenant_id: str, schema_id: str, version: str):
        """
        设置已加载的 Schema
        
        Args:
            tenant_id: 租户 ID
            schema_id: Schema ID
            version: 版本号
        """
        state = await self.get_or_create_state(tenant_id)
        state.loaded_schemas[schema_id] = version
        state.updated_at = datetime.utcnow()
        state.last_schema_refresh = datetime.utcnow()
        
        logger.info(f"Loaded schema {schema_id}@{version} for tenant: {tenant_id}")
    
    async def invalidate_cache(self, tenant_id: str):
        """
        使缓存失效（递增缓存版本）
        
        Args:
            tenant_id: 租户 ID
        """
        state = await self.get_or_create_state(tenant_id)
        
        # 解析当前版本号
        try:
            current_num = int(state.cache_version.lstrip('v'))
            new_num = current_num + 1
            state.cache_version = f"v{new_num}"
        except ValueError:
            state.cache_version = "v2"
        
        state.updated_at = datetime.utcnow()
        
        logger.info(f"Cache invalidated for tenant: {tenant_id}, new version: {state.cache_version}")
    
    async def save_runtime_snapshot(self, tenant_id: str, snapshot: Dict[str, Any]):
        """
        保存运行时快照
        
        Args:
            tenant_id: 租户 ID
            snapshot: 快照数据
        """
        state = await self.get_or_create_state(tenant_id)
        state.runtime_snapshot = deepcopy(snapshot)
        state.updated_at = datetime.utcnow()
        
        logger.info(f"Saved runtime snapshot for tenant: {tenant_id}")
    
    async def get_runtime_snapshot(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        获取运行时快照
        
        Args:
            tenant_id: 租户 ID
            
        Returns:
            快照数据，不存在则返回 None
        """
        state = await self.get_state(tenant_id)
        return state.runtime_snapshot if state else None
    
    async def set_dependency_state(self, tenant_id: str, node_id: str, status: str):
        """
        设置依赖节点状态
        
        Args:
            tenant_id: 租户 ID
            node_id: 节点 ID
            status: 状态（'active', 'inactive', 'pending', 'error'）
        """
        state = await self.get_or_create_state(tenant_id)
        state.dependency_state[node_id] = status
        state.updated_at = datetime.utcnow()
        
        logger.debug(f"Set dependency state {node_id}={status} for tenant: {tenant_id}")
    
    async def get_dependency_state(self, tenant_id: str, node_id: str) -> Optional[str]:
        """
        获取依赖节点状态
        
        Args:
            tenant_id: 租户 ID
            node_id: 节点 ID
            
        Returns:
            节点状态，不存在则返回 None
        """
        state = await self.get_state(tenant_id)
        return state.dependency_state.get(node_id) if state else None
    
    async def register_state_listener(self, tenant_id: str, callback):
        """
        注册状态监听器
        
        Args:
            tenant_id: 租户 ID（'*' 表示全局监听）
            callback: 回调函数 async callback(tenant_id, old_state, new_state)
        """
        if tenant_id not in self._state_listeners:
            self._state_listeners[tenant_id] = []
        
        self._state_listeners[tenant_id].append(callback)
        
        logger.info(f"Registered state listener for tenant: {tenant_id}")
    
    async def _notify_listeners(self, tenant_id: str, old_state: TenantRuntimeState, new_state: TenantRuntimeState):
        """
        通知状态监听器
        
        Args:
            tenant_id: 租户 ID
            old_state: 旧状态
            new_state: 新状态
        """
        # 通知特定租户监听器
        if tenant_id in self._state_listeners:
            for callback in self._state_listeners[tenant_id]:
                try:
                    await callback(tenant_id, old_state, new_state)
                except Exception as e:
                    logger.error(f"Error in state listener for {tenant_id}: {e}", exc_info=True)
        
        # 通知全局监听器
        if '*' in self._state_listeners:
            for callback in self._state_listeners['*']:
                try:
                    await callback(tenant_id, old_state, new_state)
                except Exception as e:
                    logger.error(f"Error in global state listener: {e}", exc_info=True)
    
    async def remove_tenant_state(self, tenant_id: str):
        """
        移除租户状态（Bot 删除时调用）
        
        Args:
            tenant_id: 租户 ID
        """
        if tenant_id in self._states:
            del self._states[tenant_id]
            logger.info(f"Removed runtime state for tenant: {tenant_id}")
    
    async def get_all_states(self) -> Dict[str, TenantRuntimeState]:
        """
        获取所有租户状态（用于监控）
        
        Returns:
            租户状态字典
        """
        return deepcopy(self._states)
    
    async def get_global_state(self, key: str) -> Optional[Any]:
        """
        获取全局状态
        
        Args:
            key: 状态键
            
        Returns:
            状态值，不存在则返回 None
        """
        return self._global_state.get(key)
    
    async def set_global_state(self, key: str, value: Any):
        """
        设置全局状态
        
        Args:
            key: 状态键
            value: 状态值
        """
        self._global_state[key] = value
        logger.debug(f"Set global state: {key}")
    
    async def clear_global_state(self):
        """清除全局状态"""
        self._global_state.clear()
        logger.info("Global state cleared")
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息（用于监控）
        
        Returns:
            统计信息字典
        """
        total_tenants = len(self._states)
        total_capabilities = sum(len(state.active_capabilities) for state in self._states.values())
        total_schemas = sum(len(state.loaded_schemas) for state in self._states.values())
        
        return {
            'total_tenants': total_tenants,
            'total_capabilities': total_capabilities,
            'total_schemas': total_schemas,
            'global_state_keys': len(self._global_state),
            'state_listeners': sum(len(listeners) for listeners in self._state_listeners.values()),
        }


# 全局单例
runtime_state_store = RuntimeStateStore()
