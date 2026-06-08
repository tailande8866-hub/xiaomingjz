"""
事件管道保护层（Event Pipeline Protection Layer）

职责：
1. Event Queue（事件队列）- 削峰、异步处理
2. Event Deduplication（事件去重）- 防止重复执行
3. Retry Strategy（重试策略）- 指数退避
4. Dead Letter Queue（DLQ，死信队列）- 失败事件隔离
5. Event Rate Limit（限流）- 防止事件风暴

这是 Bot OS 的"交通系统"，没有它，Runtime 会堵死。
"""
import asyncio
import hashlib
import logging
import time
from typing import Dict, List, Optional, Callable, Awaitable, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class EventPriority(Enum):
    """事件优先级"""
    LOW = 0        # 低优先级（例如：日志记录）
    NORMAL = 1     # 普通优先级（默认）
    HIGH = 2       # 高优先级（例如：权限变更）
    CRITICAL = 3   # 关键优先级（例如：Bot 创建/删除）


@dataclass
class QueuedEvent:
    """队列中的事件"""
    
    event_id: str                      # 事件唯一 ID
    event_type: str                    # 事件类型
    data: Dict[str, Any]               # 事件数据
    bot_id: Optional[str] = None       # Bot ID
    root_bot_id: Optional[str] = None  # 根 Bot ID
    priority: EventPriority = EventPriority.NORMAL  # 优先级
    created_at: float = field(default_factory=time.time)  # 创建时间
    retry_count: int = 0               # 重试次数
    max_retries: int = 5               # 最大重试次数
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type,
            'data': self.data,
            'bot_id': self.bot_id,
            'root_bot_id': self.root_bot_id,
            'priority': self.priority.value,
            'created_at': self.created_at,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries
        }


class EventDeduplicator:
    """
    事件去重器
    
    使用事件指纹（event_hash）在短时间内去重相同事件
    """
    
    def __init__(self, window_seconds: int = 5):
        """
        Args:
            window_seconds: 去重时间窗口（秒）
        """
        self.window_seconds = window_seconds
        # {event_hash: timestamp}
        self.seen_events: Dict[str, float] = {}
    
    def generate_event_hash(self, event_type: str, data: Dict[str, Any]) -> str:
        """
        生成事件指纹
        
        Args:
            event_type: 事件类型
            data: 事件数据
            
        Returns:
            事件哈希值
        """
        # 将事件类型和数据序列化为字符串
        content = f"{event_type}:{str(sorted(data.items()))}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def is_duplicate(self, event_type: str, data: Dict[str, Any]) -> bool:
        """
        检查是否是重复事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
            
        Returns:
            是否重复
        """
        event_hash = self.generate_event_hash(event_type, data)
        current_time = time.time()
        
        # 清理过期记录
        self._cleanup_expired(current_time)
        
        # 检查是否在时间窗口内
        if event_hash in self.seen_events:
            last_seen = self.seen_events[event_hash]
            if current_time - last_seen < self.window_seconds:
                logger.debug(f"Duplicate event detected: {event_type}")
                return True
        
        # 记录事件
        self.seen_events[event_hash] = current_time
        return False
    
    def _cleanup_expired(self, current_time: float):
        """清理过期的事件记录"""
        expired_hashes = [
            hash for hash, timestamp in self.seen_events.items()
            if current_time - timestamp >= self.window_seconds
        ]
        for hash in expired_hashes:
            del self.seen_events[hash]


class EventRateLimiter:
    """
    事件限流器
    
    限制每种事件类型的每秒处理数量
    """
    
    def __init__(self):
        # {event_type: [timestamps]}
        self.event_timestamps: Dict[str, List[float]] = defaultdict(list)
        
        # 默认限流配置：{event_type: max_events_per_second}
        self.rate_limits: Dict[str, int] = {
            'BOT_CREATED': 10,
            'BOT_STARTED': 10,
            'GROUP_STATUS_CHANGED': 50,
            'PERMISSION_CHANGED': 20,
            'ADMIN_ADDED': 10,
            'DEFAULT': 100  # 默认限流
        }
    
    def set_rate_limit(self, event_type: str, max_events_per_second: int):
        """
        设置事件限流
        
        Args:
            event_type: 事件类型
            max_events_per_second: 每秒最大事件数
        """
        self.rate_limits[event_type] = max_events_per_second
        logger.info(f"Set rate limit for {event_type}: {max_events_per_second}/sec")
    
    def is_rate_limited(self, event_type: str) -> bool:
        """
        检查是否触发限流
        
        Args:
            event_type: 事件类型
            
        Returns:
            是否被限流
        """
        current_time = time.time()
        max_events = self.rate_limits.get(event_type, self.rate_limits['DEFAULT'])
        
        # 清理 1 秒前的时间戳
        self.event_timestamps[event_type] = [
            ts for ts in self.event_timestamps[event_type]
            if current_time - ts < 1.0
        ]
        
        # 检查是否超过限流
        if len(self.event_timestamps[event_type]) >= max_events:
            logger.warning(f"Rate limit exceeded for {event_type}: {len(self.event_timestamps[event_type])}/{max_events}")
            return True
        
        # 记录当前时间戳
        self.event_timestamps[event_type].append(current_time)
        return False


class DeadLetterQueue:
    """
    死信队列（DLQ）
    
    存储处理失败的事件，用于后续分析和人工干预
    """
    
    def __init__(self, max_size: int = 1000):
        """
        Args:
            max_size: DLQ 最大容量
        """
        self.max_size = max_size
        self.dead_letters: List[Dict[str, Any]] = []
    
    def add(self, queued_event: QueuedEvent, error: Exception):
        """
        添加死信
        
        Args:
            queued_event: 失败的事件
            error: 错误信息
        """
        dead_letter = {
            'event': queued_event.to_dict(),
            'error': str(error),
            'error_type': type(error).__name__,
            'failed_at': time.time(),
            'retry_count': queued_event.retry_count
        }
        
        self.dead_letters.append(dead_letter)
        
        # 如果超过最大容量，移除最旧的
        if len(self.dead_letters) > self.max_size:
            removed = self.dead_letters.pop(0)
            logger.warning(f"DLQ full, removed oldest dead letter: {removed['event']['event_id']}")
        
        logger.error(
            f"Event added to DLQ: {queued_event.event_id} "
            f"(type={queued_event.event_type}, retries={queued_event.retry_count}, "
            f"error={error})"
        )
    
    def get_all(self) -> List[Dict[str, Any]]:
        """获取所有死信"""
        return self.dead_letters.copy()
    
    def clear(self):
        """清空死信队列"""
        self.dead_letters.clear()
        logger.info("DLQ cleared")
    
    def size(self) -> int:
        """获取死信数量"""
        return len(self.dead_letters)


class EventPipeline:
    """
    事件管道（核心组件）
    
    整合：
    1. Event Queue
    2. Event Deduplication
    3. Retry Strategy
    4. Dead Letter Queue
    5. Event Rate Limit
    """
    
    def __init__(self, max_queue_size: int = 10000, num_workers: int = 3):
        """
        Args:
            max_queue_size: 队列最大容量
            num_workers: Worker 数量
        """
        self.max_queue_size = max_queue_size
        self.num_workers = num_workers
        
        # 事件队列（优先级队列）
        self.event_queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        
        # 去重器
        self.deduplicator = EventDeduplicator(window_seconds=5)
        
        # 限流器
        self.rate_limiter = EventRateLimiter()
        
        # 死信队列
        self.dlq = DeadLetterQueue(max_size=1000)
        
        # 事件处理器注册表：{event_type: handler}
        self.handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[None]]] = {}
        
        # Worker 任务
        self.workers: List[asyncio.Task] = []
        
        # 运行状态
        self.is_running = False
        
        # 统计信息
        self.stats = {
            'total_published': 0,
            'total_processed': 0,
            'total_dropped': 0,
            'total_duplicates': 0,
            'total_rate_limited': 0,
            'total_dlq': 0,
            'queue_size': 0
        }
    
    def register_handler(self, event_type: str, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        """
        注册事件处理器
        
        Args:
            event_type: 事件类型
            handler: 处理函数，签名：async def handler(data)
        """
        self.handlers[event_type] = handler
        logger.info(f"Registered handler for event: {event_type}")
    
    async def publish(self, event_type: str, data: Dict[str, Any], 
                     bot_id: Optional[str] = None, 
                     root_bot_id: Optional[str] = None,
                     priority: EventPriority = EventPriority.NORMAL):
        """
        发布事件到队列
        
        Args:
            event_type: 事件类型
            data: 事件数据
            bot_id: Bot ID
            root_bot_id: 根 Bot ID
            priority: 优先级
        """
        try:
            self.stats['total_published'] += 1
            
            # 1. 检查去重
            if self.deduplicator.is_duplicate(event_type, data):
                self.stats['total_duplicates'] += 1
                logger.debug(f"Event dropped (duplicate): {event_type}")
                return
            
            # 2. 检查限流
            if self.rate_limiter.is_rate_limited(event_type):
                self.stats['total_rate_limited'] += 1
                logger.warning(f"Event dropped (rate limited): {event_type}")
                return
            
            # 3. 生成事件 ID
            import uuid
            event_id = str(uuid.uuid4())
            
            # 4. 创建队列事件
            queued_event = QueuedEvent(
                event_id=event_id,
                event_type=event_type,
                data=data,
                bot_id=bot_id,
                root_bot_id=root_bot_id,
                priority=priority
            )
            
            # 5. 加入队列（带优先级）
            try:
                # PriorityQueue 使用元组 (priority, event) 排序
                await self.event_queue.put((-priority.value, time.time(), queued_event))
                self.stats['queue_size'] = self.event_queue.qsize()
                logger.debug(f"Event published: {event_type} (id={event_id}, priority={priority.name})")
            except asyncio.QueueFull:
                self.stats['total_dropped'] += 1
                logger.error(f"Event queue full, dropping event: {event_type}")
        
        except Exception as e:
            logger.error(f"Error publishing event: {e}", exc_info=True)
    
    async def start(self):
        """启动事件管道"""
        if self.is_running:
            logger.warning("Event pipeline already running")
            return
        
        self.is_running = True
        logger.info(f"Starting event pipeline with {self.num_workers} workers")
        
        # 启动 Workers
        for i in range(self.num_workers):
            worker_task = asyncio.create_task(self._worker(i))
            self.workers.append(worker_task)
        
        logger.info("Event pipeline started")
    
    async def stop(self):
        """停止事件管道"""
        if not self.is_running:
            return
        
        self.is_running = False
        logger.info("Stopping event pipeline...")
        
        # 等待所有 Worker 完成
        for worker in self.workers:
            worker.cancel()
        
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        
        logger.info("Event pipeline stopped")
    
    async def _worker(self, worker_id: int):
        """
        Worker 协程
        
        Args:
            worker_id: Worker ID
        """
        logger.info(f"Worker {worker_id} started")
        
        while self.is_running:
            try:
                # 从队列中获取事件（超时 1 秒）
                try:
                    _, _, queued_event = await asyncio.wait_for(
                        self.event_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # 处理事件
                await self._process_event(queued_event, worker_id)
                
                # 标记任务完成
                self.event_queue.task_done()
            
            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
        
        logger.info(f"Worker {worker_id} stopped")
    
    async def _process_event(self, queued_event: QueuedEvent, worker_id: int):
        """
        处理事件
        
        Args:
            queued_event: 队列事件
            worker_id: Worker ID
        """
        event_type = queued_event.event_type
        event_id = queued_event.event_id
        
        try:
            logger.debug(f"Worker {worker_id} processing event: {event_type} (id={event_id})")
            
            # 获取处理器
            handler = self.handlers.get(event_type)
            if not handler:
                logger.warning(f"No handler registered for event: {event_type}")
                return
            
            # 执行处理器
            await handler(queued_event.data)
            
            # 更新统计
            self.stats['total_processed'] += 1
            logger.debug(f"Event processed successfully: {event_type} (id={event_id})")
        
        except Exception as e:
            logger.error(f"Error processing event {event_type} (id={event_id}): {e}", exc_info=True)
            
            # 重试逻辑
            if queued_event.retry_count < queued_event.max_retries:
                await self._retry_event(queued_event, e)
            else:
                # 超过最大重试次数，加入 DLQ
                self.dlq.add(queued_event, e)
                self.stats['total_dlq'] += 1
    
    async def _retry_event(self, queued_event: QueuedEvent, error: Exception):
        """
        重试事件（指数退避）
        
        Args:
            queued_event: 队列事件
            error: 错误信息
        """
        queued_event.retry_count += 1
        
        # 指数退避：1s, 3s, 10s, 30s, ...
        delay = min(1 * (3 ** (queued_event.retry_count - 1)), 60)
        
        logger.warning(
            f"Retrying event {queued_event.event_type} (id={queued_event.event_id}), "
            f"attempt {queued_event.retry_count}/{queued_event.max_retries}, "
            f"delay={delay}s"
        )
        
        # 等待后重新加入队列
        await asyncio.sleep(delay)
        
        try:
            await self.event_queue.put((
                -queued_event.priority.value,
                time.time(),
                queued_event
            ))
        except asyncio.QueueFull:
            logger.error(f"Event queue full during retry, adding to DLQ: {queued_event.event_id}")
            self.dlq.add(queued_event, error)
            self.stats['total_dlq'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            'dlq_size': self.dlq.size(),
            'is_running': self.is_running,
            'num_workers': len(self.workers)
        }


# 全局实例
event_pipeline = EventPipeline(max_queue_size=10000, num_workers=3)
