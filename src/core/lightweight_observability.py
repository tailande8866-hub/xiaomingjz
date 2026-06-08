"""
轻量生产观测层（Lightweight Production Observability）

职责：
1. Bot Health Monitor - 监控 Bot 存活状态
2. Event Pipeline Monitor - 监控事件管道健康
3. Callback Failure Tracker - 追踪 callback 失效原因
4. Runtime Snowball Detector - 检测 Runtime 雪崩
5. Tenant Error Aggregator - 聚合租户错误
6. Quick Diagnostic API - 快速诊断接口

这是 Bot OS 的"轻量观测层"，不是复杂的监控系统。
"""
import logging
import time
import asyncio
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum

logger = logging.getLogger(__name__)


class BotHealthStatus(Enum):
    """Bot 健康状态"""
    ALIVE = "alive"              # 存活
    DEAD = "dead"                # 死亡
    UNHEALTHY = "unhealthy"      # 不健康（响应慢/错误多）
    UNKNOWN = "unknown"          # 未知


@dataclass
class BotHealthRecord:
    """Bot 健康记录"""
    
    bot_id: str
    status: BotHealthStatus = BotHealthStatus.UNKNOWN
    last_heartbeat: Optional[datetime] = None
    last_error: Optional[str] = None
    error_count_last_hour: int = 0
    response_time_avg: float = 0.0  # 平均响应时间（秒）
    message_count_last_hour: int = 0
    
    def is_alive(self) -> bool:
        """检查是否存活"""
        if not self.last_heartbeat:
            return False
        
        # 超过 5 分钟没有心跳视为死亡
        return (datetime.utcnow() - self.last_heartbeat).total_seconds() < 300
    
    def is_unhealthy(self) -> bool:
        """检查是否不健康"""
        # 错误率过高（每小时 > 50 个错误）
        if self.error_count_last_hour > 50:
            return True
        
        # 响应时间过长（平均 > 5 秒）
        if self.response_time_avg > 5.0:
            return True
        
        return False


@dataclass
class EventPipelineMetrics:
    """事件管道指标"""
    
    queue_size: int = 0                    # 队列大小
    processing_rate: float = 0.0           # 处理速率（events/sec）
    avg_processing_time: float = 0.0       # 平均处理时间（秒）
    retry_count_last_hour: int = 0         # 重试次数
    dlq_size: int = 0                      # 死信队列大小
    rate_limited_count: int = 0            # 限流次数
    duplicate_count: int = 0               # 去重次数
    
    def is_overloaded(self) -> bool:
        """检查是否过载"""
        # 队列积压过多
        if self.queue_size > 5000:
            return True
        
        # 死信队列过大
        if self.dlq_size > 500:
            return True
        
        return False


@dataclass
class CallbackFailureRecord:
    """Callback 失效记录"""
    
    callback_data: str
    tenant_id: Optional[str] = None
    user_id: Optional[int] = None
    failure_reason: str = ""               # 失效原因
    timestamp: datetime = field(default_factory=datetime.utcnow)
    route_version: Optional[str] = None    # 路由版本
    
    # 常见失效原因
    REASONS = {
        "route_not_found": "路由不存在",
        "version_mismatch": "版本不匹配",
        "permission_denied": "权限不足",
        "capability_disabled": "能力未启用",
        "schema_not_loaded": "Schema 未加载",
        "tenant_not_found": "租户不存在",
    }


@dataclass
class RuntimeSnowballAlert:
    """Runtime 雪崩告警"""
    
    alert_type: str                        # 告警类型
    severity: str = "WARNING"              # 严重程度（WARNING/CRITICAL）
    description: str = ""                  # 描述
    affected_tenants: List[str] = field(default_factory=list)  # 受影响的租户
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # 雪崩类型
    TYPES = {
        "event_storm": "事件风暴（Event Storm）",
        "cascade_failure": "级联故障（Cascade Failure）",
        "memory_pressure": "内存压力（Memory Pressure）",
        "callback_flood": "Callback 洪水（Callback Flood）",
        "config_cascade": "配置级联风暴（Config Cascade）",
    }


class LightweightObservability:
    """
    轻量生产观测层（单例）
    
    提供快速诊断能力，解决生产环境问题。
    """
    
    def __init__(self):
        # === Bot 健康监控 ===
        self._bot_health: Dict[str, BotHealthRecord] = {}
        
        # === 事件管道监控 ===
        self._event_metrics = EventPipelineMetrics()
        
        # === Callback 失效追踪 ===
        self._callback_failures: deque = deque(maxlen=1000)  # 最近 1000 条失效记录
        self._callback_failure_stats: Dict[str, int] = defaultdict(int)  # 按原因统计
        
        # === Runtime 雪崩检测 ===
        self._snowball_alerts: deque = deque(maxlen=100)  # 最近 100 条告警
        
        # === 租户错误聚合 ===
        self._tenant_errors: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        
        # === 性能指标 ===
        self._response_times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        
        logger.info("Lightweight Observability initialized")
    
    # ====================================================================
    # Bot 健康监控
    # ====================================================================
    
    async def record_bot_heartbeat(self, bot_id: str):
        """
        记录 Bot 心跳
        
        Args:
            bot_id: Bot ID
        """
        if bot_id not in self._bot_health:
            self._bot_health[bot_id] = BotHealthRecord(bot_id=bot_id)
        
        record = self._bot_health[bot_id]
        record.last_heartbeat = datetime.utcnow()
        record.status = BotHealthStatus.ALIVE
        
        # 重置小时计数器（每小时重置一次）
        if record.last_heartbeat and (datetime.utcnow() - record.last_heartbeat).total_seconds() > 3600:
            record.error_count_last_hour = 0
            record.message_count_last_hour = 0
    
    async def record_bot_error(self, bot_id: str, error_message: str):
        """
        记录 Bot 错误
        
        Args:
            bot_id: Bot ID
            error_message: 错误消息
        """
        if bot_id not in self._bot_health:
            self._bot_health[bot_id] = BotHealthRecord(bot_id=bot_id)
        
        record = self._bot_health[bot_id]
        record.last_error = error_message
        record.error_count_last_hour += 1
        
        # 检查是否不健康
        if record.is_unhealthy():
            record.status = BotHealthStatus.UNHEALTHY
            logger.warning(f"Bot {bot_id} is unhealthy: {error_message}")
    
    async def record_bot_message(self, bot_id: str, response_time: float):
        """
        记录 Bot 消息处理
        
        Args:
            bot_id: Bot ID
            response_time: 响应时间（秒）
        """
        if bot_id not in self._bot_health:
            self._bot_health[bot_id] = BotHealthRecord(bot_id=bot_id)
        
        record = self._bot_health[bot_id]
        record.message_count_last_hour += 1
        
        # 更新平均响应时间
        times = self._response_times[bot_id]
        times.append(response_time)
        record.response_time_avg = sum(times) / len(times)
    
    async def get_bot_health(self, bot_id: str) -> Optional[BotHealthRecord]:
        """
        获取 Bot 健康状态
        
        Args:
            bot_id: Bot ID
            
        Returns:
            健康记录，不存在则返回 None
        """
        record = self._bot_health.get(bot_id)
        
        # 检查是否死亡
        if record and not record.is_alive():
            record.status = BotHealthStatus.DEAD
        
        return record
    
    async def get_all_bot_health(self) -> Dict[str, BotHealthRecord]:
        """
        获取所有 Bot 健康状态
        
        Returns:
            Bot 健康记录字典
        """
        # 更新所有 Bot 的状态
        for record in self._bot_health.values():
            if not record.is_alive():
                record.status = BotHealthStatus.DEAD
        
        return dict(self._bot_health)
    
    async def get_dead_bots(self) -> List[str]:
        """
        获取死亡的 Bot 列表
        
        Returns:
            死亡的 Bot ID 列表
        """
        dead_bots = []
        for bot_id, record in self._bot_health.items():
            if record.status == BotHealthStatus.DEAD or not record.is_alive():
                dead_bots.append(bot_id)
        
        return dead_bots
    
    # ====================================================================
    # 事件管道监控
    # ====================================================================
    
    async def update_event_metrics(self, metrics: Dict[str, Any]):
        """
        更新事件管道指标
        
        Args:
            metrics: 指标字典
        """
        self._event_metrics.queue_size = metrics.get('queue_size', 0)
        self._event_metrics.processing_rate = metrics.get('processing_rate', 0.0)
        self._event_metrics.avg_processing_time = metrics.get('avg_processing_time', 0.0)
        self._event_metrics.retry_count_last_hour = metrics.get('retry_count', 0)
        self._event_metrics.dlq_size = metrics.get('dlq_size', 0)
        self._event_metrics.rate_limited_count = metrics.get('rate_limited', 0)
        self._event_metrics.duplicate_count = metrics.get('duplicates', 0)
    
    async def get_event_metrics(self) -> EventPipelineMetrics:
        """
        获取事件管道指标
        
        Returns:
            事件管道指标
        """
        return self._event_metrics
    
    async def is_event_pipeline_overloaded(self) -> bool:
        """
        检查事件管道是否过载
        
        Returns:
            是否过载
        """
        return self._event_metrics.is_overloaded()
    
    # ====================================================================
    # Callback 失效追踪
    # ====================================================================
    
    async def record_callback_failure(
        self,
        callback_data: str,
        failure_reason: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[int] = None,
        route_version: Optional[str] = None
    ):
        """
        记录 Callback 失效
        
        Args:
            callback_data: Callback 数据
            failure_reason: 失效原因
            tenant_id: 租户 ID
            user_id: 用户 ID
            route_version: 路由版本
        """
        record = CallbackFailureRecord(
            callback_data=callback_data,
            tenant_id=tenant_id,
            user_id=user_id,
            failure_reason=failure_reason,
            route_version=route_version
        )
        
        self._callback_failures.append(record)
        self._callback_failure_stats[failure_reason] += 1
        
        logger.warning(
            f"Callback failure: {callback_data}, reason={failure_reason}, "
            f"tenant={tenant_id}, user={user_id}"
        )
    
    async def get_callback_failures(
        self,
        limit: int = 50,
        tenant_id: Optional[str] = None
    ) -> List[CallbackFailureRecord]:
        """
        获取 Callback 失效记录
        
        Args:
            limit: 限制数量
            tenant_id: 过滤租户 ID
            
        Returns:
            失效记录列表
        """
        failures = list(self._callback_failures)
        
        # 按租户过滤
        if tenant_id:
            failures = [f for f in failures if f.tenant_id == tenant_id]
        
        # 按时间倒序
        failures.sort(key=lambda x: x.timestamp, reverse=True)
        
        return failures[:limit]
    
    async def get_callback_failure_stats(self) -> Dict[str, int]:
        """
        获取 Callback 失效统计
        
        Returns:
            按原因统计的字典
        """
        return dict(self._callback_failure_stats)
    
    # ====================================================================
    # Runtime 雪崩检测
    # ====================================================================
    
    async def detect_snowball(self) -> List[RuntimeSnowballAlert]:
        """
        检测 Runtime 雪崩
        
        Returns:
            雪崩告警列表
        """
        alerts = []
        
        # 1. 检测事件风暴
        if await self.is_event_pipeline_overloaded():
            alert = RuntimeSnowballAlert(
                alert_type="event_storm",
                severity="CRITICAL",
                description=f"Event pipeline overloaded: queue_size={self._event_metrics.queue_size}, dlq_size={self._event_metrics.dlq_size}"
            )
            alerts.append(alert)
            self._snowball_alerts.append(alert)
        
        # 2. 检测级联故障（多个 Bot 同时死亡）
        dead_bots = await self.get_dead_bots()
        if len(dead_bots) > 5:
            alert = RuntimeSnowballAlert(
                alert_type="cascade_failure",
                severity="CRITICAL",
                description=f"{len(dead_bots)} bots died simultaneously",
                affected_tenants=dead_bots
            )
            alerts.append(alert)
            self._snowball_alerts.append(alert)
        
        # 3. 检测 Callback 洪水
        recent_failures = len([
            f for f in self._callback_failures
            if (datetime.utcnow() - f.timestamp).total_seconds() < 300
        ])
        if recent_failures > 100:
            alert = RuntimeSnowballAlert(
                alert_type="callback_flood",
                severity="WARNING",
                description=f"{recent_failures} callback failures in last 5 minutes"
            )
            alerts.append(alert)
            self._snowball_alerts.append(alert)
        
        # 4. 检测配置级联风暴
        config_updates = len([
            a for a in self._snowball_alerts
            if a.alert_type == "config_cascade" and 
            (datetime.utcnow() - a.timestamp).total_seconds() < 60
        ])
        if config_updates > 10:
            alert = RuntimeSnowballAlert(
                alert_type="config_cascade",
                severity="WARNING",
                description=f"{config_updates} config cascades in last minute"
            )
            alerts.append(alert)
            self._snowball_alerts.append(alert)
        
        if alerts:
            logger.error(f"Runtime snowball detected: {len(alerts)} alerts")
        
        return alerts
    
    async def get_snowball_alerts(self, limit: int = 20) -> List[RuntimeSnowballAlert]:
        """
        获取雪崩告警
        
        Args:
            limit: 限制数量
            
        Returns:
            告警列表
        """
        return list(self._snowball_alerts)[-limit:]
    
    # ====================================================================
    # 租户错误聚合
    # ====================================================================
    
    async def record_tenant_error(self, tenant_id: str, error_message: str):
        """
        记录租户错误
        
        Args:
            tenant_id: 租户 ID
            error_message: 错误消息
        """
        self._tenant_errors[tenant_id].append({
            'message': error_message,
            'timestamp': datetime.utcnow()
        })
    
    async def get_tenant_errors(
        self,
        tenant_id: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        获取租户错误
        
        Args:
            tenant_id: 租户 ID
            limit: 限制数量
            
        Returns:
            错误列表
        """
        errors = list(self._tenant_errors.get(tenant_id, []))
        errors.sort(key=lambda x: x['timestamp'], reverse=True)
        return errors[:limit]
    
    async def get_top_error_tenants(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取错误最多的租户
        
        Args:
            limit: 限制数量
            
        Returns:
            租户错误统计列表
        """
        tenant_error_counts = [
            {
                'tenant_id': tenant_id,
                'error_count': len(errors)
            }
            for tenant_id, errors in self._tenant_errors.items()
        ]
        
        # 按错误数排序
        tenant_error_counts.sort(key=lambda x: x['error_count'], reverse=True)
        
        return tenant_error_counts[:limit]
    
    # ====================================================================
    # 快速诊断 API
    # ====================================================================
    
    async def quick_diagnostic(self) -> Dict[str, Any]:
        """
        快速诊断（一键检查系统健康）
        
        Returns:
            诊断结果
        """
        diagnostic = {
            'timestamp': datetime.utcnow().isoformat(),
            'bot_health': {},
            'event_pipeline': {},
            'callback_failures': {},
            'snowball_alerts': [],
            'top_error_tenants': [],
        }
        
        # 1. Bot 健康
        all_health = await self.get_all_bot_health()
        alive_count = sum(1 for r in all_health.values() if r.status == BotHealthStatus.ALIVE)
        dead_count = sum(1 for r in all_health.values() if r.status == BotHealthStatus.DEAD)
        unhealthy_count = sum(1 for r in all_health.values() if r.status == BotHealthStatus.UNHEALTHY)
        
        diagnostic['bot_health'] = {
            'total': len(all_health),
            'alive': alive_count,
            'dead': dead_count,
            'unhealthy': unhealthy_count,
            'dead_bot_ids': await self.get_dead_bots(),
        }
        
        # 2. 事件管道
        event_metrics = await self.get_event_metrics()
        diagnostic['event_pipeline'] = {
            'queue_size': event_metrics.queue_size,
            'processing_rate': event_metrics.processing_rate,
            'dlq_size': event_metrics.dlq_size,
            'is_overloaded': await self.is_event_pipeline_overloaded(),
        }
        
        # 3. Callback 失效
        failure_stats = await self.get_callback_failure_stats()
        diagnostic['callback_failures'] = {
            'total_recent': len(self._callback_failures),
            'by_reason': failure_stats,
        }
        
        # 4. 雪崩告警
        snowball_alerts = await self.detect_snowball()
        diagnostic['snowball_alerts'] = [
            {
                'type': alert.alert_type,
                'severity': alert.severity,
                'description': alert.description,
                'affected_tenants': alert.affected_tenants,
            }
            for alert in snowball_alerts
        ]
        
        # 5. 错误最多的租户
        diagnostic['top_error_tenants'] = await self.get_top_error_tenants(limit=10)
        
        return diagnostic
    
    async def get_tenant_diagnostic(self, tenant_id: str) -> Dict[str, Any]:
        """
        租户级别诊断
        
        Args:
            tenant_id: 租户 ID
            
        Returns:
            诊断结果
        """
        diagnostic = {
            'tenant_id': tenant_id,
            'timestamp': datetime.utcnow().isoformat(),
            'bot_health': None,
            'recent_errors': [],
            'callback_failures': [],
        }
        
        # 1. Bot 健康
        health = await self.get_bot_health(tenant_id)
        if health:
            diagnostic['bot_health'] = {
                'status': health.status.value,
                'last_heartbeat': health.last_heartbeat.isoformat() if health.last_heartbeat else None,
                'last_error': health.last_error,
                'error_count_last_hour': health.error_count_last_hour,
                'response_time_avg': health.response_time_avg,
            }
        
        # 2. 最近错误
        diagnostic['recent_errors'] = await self.get_tenant_errors(tenant_id, limit=20)
        
        # 3. Callback 失效
        diagnostic['callback_failures'] = await self.get_callback_failures(
            limit=20,
            tenant_id=tenant_id
        )
        
        return diagnostic


# 全局单例
lightweight_observability = LightweightObservability()
