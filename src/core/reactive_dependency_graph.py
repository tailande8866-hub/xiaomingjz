"""
反应式依赖图（Reactive Dependency Graph）

职责：
1. Dependency Node（依赖节点）- 定义每个模块的依赖关系
2. Reactive Engine（反应引擎）- 监听变更，自动触发精准刷新
3. Targeted Refresh（精准刷新）- 避免全局 reload，防止 Cascade Storm
4. Dependency Resolver（依赖解析器）- 解析依赖链
5. Reload Strategy（重载策略）- soft/hard/invalidate

这是 Bot OS 的"反应系统"（Reactive System），不是简单的配置依赖。
"""
import logging
from typing import Dict, List, Optional, Set, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class NodeType(Enum):
    """节点类型"""
    CONFIG = "config"              # 配置节点
    CAPABILITY = "capability"      # 能力节点
    UI_SCHEMA = "ui_schema"        # UI Schema 节点
    ROUTE = "route"                # 路由节点
    RUNTIME_STATE = "runtime_state"  # 运行时状态节点
    CACHE = "cache"                # 缓存节点


class ReloadStrategy(Enum):
    """重载策略"""
    SOFT = "soft"                  # 软重载（无需重启，仅刷新内存）
    HARD = "hard"                  # 硬重载（需要重启或重新初始化）
    INVALIDATE = "invalidate"      # 仅失效缓存，下次访问时重新加载
    NONE = "none"                  # 无需重载


@dataclass
class DependencyNode:
    """依赖节点"""
    
    node_id: str                           # 节点 ID（例如：'config.ui.theme'）
    node_type: NodeType                    # 节点类型
    depends_on: List[str] = field(default_factory=list)  # 依赖的节点列表
    affects: List[str] = field(default_factory=list)     # 影响的节点列表
    reload_strategy: ReloadStrategy = ReloadStrategy.SOFT  # 重载策略
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'node_id': self.node_id,
            'node_type': self.node_type.value,
            'depends_on': self.depends_on,
            'affects': self.affects,
            'reload_strategy': self.reload_strategy.value,
            'metadata': self.metadata
        }


class DependencyGraph:
    """
    依赖图
    
    负责：
    1. 注册依赖节点
    2. 解析依赖链
    3. 检测循环依赖
    4. 提供影响分析
    """
    
    def __init__(self):
        # 节点注册表：{node_id: DependencyNode}
        self.nodes: Dict[str, DependencyNode] = {}
        
        # 反向索引：{affected_node: [dependent_nodes]}
        self.reverse_index: Dict[str, List[str]] = defaultdict(list)
        
        # 注册默认节点
        self._register_default_nodes()
    
    def _register_default_nodes(self):
        """注册默认依赖节点"""
        
        # === Config Nodes ===
        self.register(DependencyNode(
            node_id="config.ui.theme",
            node_type=NodeType.CONFIG,
            affects=["ui.schema.main_menu", "ui.schema.settings_menu"],
            reload_strategy=ReloadStrategy.SOFT,
            metadata={'description': 'UI 主题配置'}
        ))
        
        self.register(DependencyNode(
            node_id="config.runtime.version",
            node_type=NodeType.CONFIG,
            affects=["runtime.state", "route.cache", "tenant.reload"],
            reload_strategy=ReloadStrategy.HARD,
            metadata={'description': 'Runtime 版本配置'}
        ))
        
        self.register(DependencyNode(
            node_id="config.broadcast.limit",
            node_type=NodeType.CONFIG,
            affects=["runtime.state"],
            reload_strategy=ReloadStrategy.SOFT,
            metadata={'description': '广播限制配置'}
        ))
        
        # === Capability Nodes ===
        self.register(DependencyNode(
            node_id="capability.feature.ai",
            node_type=NodeType.CAPABILITY,
            affects=["ui.schema.main_menu", "route.ai_endpoint"],
            reload_strategy=ReloadStrategy.SOFT,
            metadata={'description': 'AI 功能能力'}
        ))
        
        self.register(DependencyNode(
            node_id="capability.runtime.v2",
            node_type=NodeType.CAPABILITY,
            affects=["runtime.state", "route.cache"],
            reload_strategy=ReloadStrategy.HARD,
            metadata={'description': 'Runtime v2 能力'}
        ))
        
        # === UI Schema Nodes ===
        self.register(DependencyNode(
            node_id="ui.schema.main_menu",
            node_type=NodeType.UI_SCHEMA,
            depends_on=["config.ui.theme", "capability.feature.ai"],
            affects=["route.menu_endpoint"],
            reload_strategy=ReloadStrategy.SOFT,
            metadata={'description': '主菜单 UI Schema'}
        ))
        
        self.register(DependencyNode(
            node_id="ui.schema.group_manage",
            node_type=NodeType.UI_SCHEMA,
            depends_on=["capability.feature.broadcast"],
            affects=["route.group_manage_endpoint"],
            reload_strategy=ReloadStrategy.SOFT,
            metadata={'description': '群组管理 UI Schema'}
        ))
        
        # === Route Nodes ===
        self.register(DependencyNode(
            node_id="route.menu_endpoint",
            node_type=NodeType.ROUTE,
            depends_on=["ui.schema.main_menu"],
            affects=["runtime.state"],
            reload_strategy=ReloadStrategy.INVALIDATE,
            metadata={'description': '菜单路由'}
        ))
        
        # === Runtime State Nodes ===
        self.register(DependencyNode(
            node_id="runtime.state",
            node_type=NodeType.RUNTIME_STATE,
            depends_on=["config.runtime.version", "capability.runtime.v2"],
            affects=["cache.tenant_context"],
            reload_strategy=ReloadStrategy.HARD,
            metadata={'description': '运行时状态'}
        ))
        
        # === Cache Nodes ===
        self.register(DependencyNode(
            node_id="cache.tenant_context",
            node_type=NodeType.CACHE,
            depends_on=["runtime.state"],
            affects=[],
            reload_strategy=ReloadStrategy.INVALIDATE,
            metadata={'description': '租户上下文缓存'}
        ))
    
    def register(self, node: DependencyNode):
        """
        注册依赖节点
        
        Args:
            node: 依赖节点
        """
        self.nodes[node.node_id] = node
        
        # 更新反向索引
        for affected_node in node.affects:
            self.reverse_index[affected_node].append(node.node_id)
        
        logger.info(f"Registered dependency node: {node.node_id}")
    
    def get_node(self, node_id: str) -> Optional[DependencyNode]:
        """
        获取依赖节点
        
        Args:
            node_id: 节点 ID
            
        Returns:
            依赖节点，如果不存在则返回 None
        """
        return self.nodes.get(node_id)
    
    def get_affected_nodes(self, node_id: str, visited: Optional[Set[str]] = None) -> List[str]:
        """
        获取受影响的节点列表（递归）
        
        Args:
            node_id: 节点 ID
            visited: 已访问节点集合（用于检测循环依赖）
            
        Returns:
            受影响的节点列表
        """
        if visited is None:
            visited = set()
        
        if node_id in visited:
            logger.warning(f"Cycle detected in dependency graph at {node_id}")
            return []
        
        visited.add(node_id)
        
        affected_nodes = []
        node = self.nodes.get(node_id)
        
        if not node:
            return []
        
        # 直接影响的节点
        for affected_node in node.affects:
            if affected_node not in visited:
                affected_nodes.append(affected_node)
                # 递归获取间接影响的节点
                affected_nodes.extend(self.get_affected_nodes(affected_node, visited))
        
        return affected_nodes
    
    def get_dependencies(self, node_id: str, visited: Optional[Set[str]] = None) -> List[str]:
        """
        获取依赖的节点列表（递归）
        
        Args:
            node_id: 节点 ID
            visited: 已访问节点集合
            
        Returns:
            依赖的节点列表
        """
        if visited is None:
            visited = set()
        
        if node_id in visited:
            return []
        
        visited.add(node_id)
        
        dependencies = []
        node = self.nodes.get(node_id)
        
        if not node:
            return []
        
        # 直接依赖的节点
        for dep_node in node.depends_on:
            if dep_node not in visited:
                dependencies.append(dep_node)
                # 递归获取间接依赖的节点
                dependencies.extend(self.get_dependencies(dep_node, visited))
        
        return dependencies
    
    def detect_cycles(self) -> List[List[str]]:
        """
        检测循环依赖
        
        Returns:
            循环依赖列表
        """
        cycles = []
        visited = set()
        rec_stack = set()
        
        def dfs(node_id: str, path: List[str]):
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)
            
            node = self.nodes.get(node_id)
            if node:
                for affected_node in node.affects:
                    if affected_node not in visited:
                        dfs(affected_node, path)
                    elif affected_node in rec_stack:
                        # 找到循环
                        cycle_start = path.index(affected_node)
                        cycles.append(path[cycle_start:] + [affected_node])
            
            path.pop()
            rec_stack.remove(node_id)
        
        for node_id in self.nodes:
            if node_id not in visited:
                dfs(node_id, [])
        
        return cycles


class ReactiveEngine:
    """
    反应引擎
    
    负责：
    1. 监听变更事件
    2. 解析依赖链
    3. 触发精准刷新
    4. 执行重载策略
    """
    
    def __init__(self, graph: DependencyGraph):
        self.graph = graph
        
        # 刷新处理器：{node_id: handler}
        self.refresh_handlers: Dict[str, Callable[[str], Awaitable[None]]] = {}
        
        # 变更历史：[(node_id, timestamp)]
        self.change_history: List[tuple] = []
    
    def register_refresh_handler(self, node_id: str, handler: Callable[[str], Awaitable[None]]):
        """
        注册刷新处理器
        
        Args:
            node_id: 节点 ID
            handler: 刷新处理器，签名：async def handler(node_id)
        """
        self.refresh_handlers[node_id] = handler
        logger.info(f"Registered refresh handler for node: {node_id}")
    
    async def on_change(self, node_id: str):
        """
        当节点变更时触发
        
        Args:
            node_id: 变更的节点 ID
        """
        import time
        
        logger.info(f"Change detected for node: {node_id}")
        
        # 记录变更历史
        self.change_history.append((node_id, time.time()))
        
        # 获取受影响的节点
        affected_nodes = self.graph.get_affected_nodes(node_id)
        
        if not affected_nodes:
            logger.debug(f"No affected nodes for {node_id}")
            return
        
        logger.info(f"Affected nodes: {affected_nodes}")
        
        # 按依赖顺序排序（拓扑排序）
        sorted_nodes = self._topological_sort(affected_nodes)
        
        # 依次触发刷新
        for affected_node in sorted_nodes:
            await self._refresh_node(affected_node)
    
    async def _refresh_node(self, node_id: str):
        """
        刷新节点
        
        Args:
            node_id: 节点 ID
        """
        node = self.graph.get_node(node_id)
        if not node:
            logger.warning(f"Node not found: {node_id}")
            return
        
        logger.info(f"Refreshing node: {node_id} (strategy={node.reload_strategy.value})")
        
        # 🆕 更新 Runtime State Store
        try:
            from .runtime_state_store import runtime_state_store
            
            # 提取 tenant_id（从 node_id 中）
            # 例如：config.ui.theme@bot_abc123 → bot_abc123
            parts = node_id.split('@')
            if len(parts) > 1:
                tenant_id = parts[1]
                
                # 根据节点类型更新状态
                if node.node_type.name == 'CONFIG':
                    await runtime_state_store.invalidate_cache(tenant_id)
                    await runtime_state_store.set_dependency_state(
                        tenant_id, node_id, 'refreshed'
                    )
                elif node.node_type.name == 'CAPABILITY':
                    # 能力变更时更新 active_capabilities
                    cap_name = node_id.replace('capability.', '').split('@')[0]
                    await runtime_state_store.set_active_capability(tenant_id, cap_name, True)
                    await runtime_state_store.set_dependency_state(
                        tenant_id, node_id, 'active'
                    )
                elif node.node_type.name == 'UI_SCHEMA':
                    # Schema 加载时记录
                    schema_id = node_id.replace('ui.schema.', '').split('@')[0]
                    await runtime_state_store.set_loaded_schema(tenant_id, schema_id, 'latest')
        except Exception as e:
            logger.error(f"Error updating runtime state store: {e}", exc_info=True)
        
        # 根据重载策略执行刷新
        if node.reload_strategy == ReloadStrategy.SOFT:
            await self._soft_reload(node_id)
        elif node.reload_strategy == ReloadStrategy.HARD:
            await self._hard_reload(node_id)
        elif node.reload_strategy == ReloadStrategy.INVALIDATE:
            await self._invalidate_cache(node_id)
        elif node.reload_strategy == ReloadStrategy.NONE:
            logger.debug(f"No reload needed for {node_id}")
        
        # 触发刷新处理器
        if node_id in self.refresh_handlers:
            try:
                await self.refresh_handlers[node_id](node_id)
            except Exception as e:
                logger.error(f"Error in refresh handler for {node_id}: {e}", exc_info=True)
    
    async def _soft_reload(self, node_id: str):
        """软重载（无需重启，仅刷新内存）"""
        logger.info(f"Soft reload: {node_id}")
        # TODO: 实现软重载逻辑
    
    async def _hard_reload(self, node_id: str):
        """硬重载（需要重启或重新初始化）"""
        logger.info(f"Hard reload: {node_id}")
        # TODO: 实现硬重载逻辑
    
    async def _invalidate_cache(self, node_id: str):
        """失效缓存"""
        logger.info(f"Invalidate cache: {node_id}")
        # TODO: 实现缓存失效逻辑
    
    def _topological_sort(self, nodes: List[str]) -> List[str]:
        """
        拓扑排序（确保依赖顺序）
        
        Args:
            nodes: 节点列表
            
        Returns:
            排序后的节点列表
        """
        visited = set()
        temp_mark = set()
        sorted_nodes = []
        
        def visit(node_id: str):
            if node_id in temp_mark:
                logger.warning(f"Cycle detected during topological sort at {node_id}")
                return
            if node_id in visited:
                return
            
            temp_mark.add(node_id)
            
            node = self.graph.get_node(node_id)
            if node:
                for dep_node in node.depends_on:
                    if dep_node in nodes:
                        visit(dep_node)
            
            temp_mark.remove(node_id)
            visited.add(node_id)
            sorted_nodes.append(node_id)
        
        for node_id in nodes:
            if node_id not in visited:
                visit(node_id)
        
        return sorted_nodes
    
    def get_change_history(self, limit: int = 100) -> List[tuple]:
        """
        获取变更历史
        
        Args:
            limit: 返回数量限制
            
        Returns:
            变更历史列表
        """
        return self.change_history[-limit:]


# 全局实例
dependency_graph = DependencyGraph()
reactive_engine = ReactiveEngine(dependency_graph)
