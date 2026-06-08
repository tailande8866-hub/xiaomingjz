"""
Bot监控系统

提供：
- 系统资源监控（CPU/内存/磁盘）
- Bot健康检查
- 异常告警通知
- 性能指标收集
"""
import os
import logging
import asyncio
from datetime import datetime
from typing import Dict, Optional
from telegram import Bot

logger = logging.getLogger(__name__)


class BotMonitor:
    """
    Bot监控系统
    
    功能：
    - 系统资源监控（CPU/内存/磁盘）
    - Bot健康检查
    - 异常告警通知
    - 性能指标收集
    """
    
    def __init__(
        self,
        alert_thresholds: Optional[Dict[str, float]] = None,
        admin_chat_ids: Optional[list] = None
    ):
        """
        初始化监控系统
        
        Args:
            alert_thresholds: 告警阈值配置
            admin_chat_ids: 管理员聊天ID列表（用于接收告警）
        """
        # 告警阈值
        self.alert_thresholds = alert_thresholds or {
            'cpu_percent': 80.0,      # CPU使用率 > 80%
            'memory_percent': 85.0,   # 内存使用率 > 85%
            'disk_usage': 90.0,       # 磁盘使用率 > 90%
            'active_connections': 100 # 活跃连接数 > 100
        }
        
        # 管理员列表
        self.admin_chat_ids = admin_chat_ids or []
        
        # 监控状态
        self.is_monitoring = False
        self.last_check_time: Optional[datetime] = None
        self.alert_history: list = []  # 告警历史
        
        # 性能指标
        self.metrics: Dict[str, any] = {
            'total_uptime': 0,
            'total_requests': 0,
            'error_count': 0,
            'last_error': None
        }
    
    async def start_monitoring(self, bot: Bot, interval: int = 60):
        """
        启动监控
        
        Args:
            bot: Telegram Bot实例
            interval: 检查间隔（秒），默认60秒
        """
        if self.is_monitoring:
            logger.warning("Monitoring is already running")
            return
        
        self.is_monitoring = True
        logger.info(f"Bot monitoring started (interval: {interval}s)")
        
        while self.is_monitoring:
            try:
                await self.check_system_health(bot)
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(interval)
    
    def stop_monitoring(self):
        """停止监控"""
        self.is_monitoring = False
        logger.info("Bot monitoring stopped")
    
    async def check_system_health(self, bot: Bot):
        """
        检查系统健康状态
        
        Args:
            bot: Telegram Bot实例
        """
        self.last_check_time = datetime.utcnow()
        
        try:
            # 1. 检查CPU使用率
            cpu_percent = self._get_cpu_percent()
            if cpu_percent > self.alert_thresholds['cpu_percent']:
                await self._send_alert(
                    bot,
                    f"⚠️ CPU使用率过高: {cpu_percent:.1f}%\n"
                    f"阈值: {self.alert_thresholds['cpu_percent']}%"
                )
            
            # 2. 检查内存使用率
            memory_percent = self._get_memory_percent()
            if memory_percent > self.alert_thresholds['memory_percent']:
                await self._send_alert(
                    bot,
                    f"⚠️ 内存使用率过高: {memory_percent:.1f}%\n"
                    f"阈值: {self.alert_thresholds['memory_percent']}%"
                )
            
            # 3. 检查磁盘使用率
            disk_percent = self._get_disk_percent()
            if disk_percent > self.alert_thresholds['disk_usage']:
                await self._send_alert(
                    bot,
                    f"⚠️ 磁盘使用率过高: {disk_percent:.1f}%\n"
                    f"阈值: {self.alert_thresholds['disk_usage']}%"
                )
            
            # 4. 记录健康状态
            logger.debug(
                f"System health check - "
                f"CPU: {cpu_percent:.1f}%, "
                f"Memory: {memory_percent:.1f}%, "
                f"Disk: {disk_percent:.1f}%"
            )
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            await self._send_alert(bot, f"❌ 健康检查失败: {str(e)}")
    
    def _get_cpu_percent(self) -> float:
        """
        获取CPU使用率
        
        Returns:
            CPU使用率百分比
        """
        try:
            import psutil
            return psutil.cpu_percent(interval=1)
        except ImportError:
            # 如果没有psutil，返回0（跳过CPU监控）
            logger.warning("psutil not installed, skipping CPU monitoring")
            return 0.0
        except Exception as e:
            logger.error(f"Failed to get CPU usage: {e}")
            return 0.0
    
    def _get_memory_percent(self) -> float:
        """
        获取内存使用率
        
        Returns:
            内存使用率百分比
        """
        try:
            import psutil
            memory = psutil.virtual_memory()
            return memory.percent
        except ImportError:
            # 如果没有psutil，尝试使用其他方法
            return self._get_memory_percent_fallback()
        except Exception as e:
            logger.error(f"Failed to get memory usage: {e}")
            return 0.0
    
    def _get_memory_percent_fallback(self) -> float:
        """
        获取内存使用率（备用方法）
        
        Returns:
            内存使用率百分比
        """
        try:
            if os.name == 'nt':  # Windows
                import ctypes
                kernel32 = ctypes.windll.kernel32
                c_ulonglong = ctypes.c_ulonglong
                
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ('dwLength', ctypes.c_ulong),
                        ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', c_ulonglong),
                        ('ullAvailPhys', c_ulonglong),
                        ('ullTotalPageFile', c_ulonglong),
                        ('ullAvailPageFile', c_ulonglong),
                        ('ullTotalVirtual', c_ulonglong),
                        ('ullAvailVirtual', c_ulonglong),
                        ('sullAvailExtendedVirtual', c_ulonglong),
                    ]
                
                memoryStatus = MEMORYSTATUSEX()
                memoryStatus.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                kernel32.GlobalMemoryStatusEx(ctypes.byref(memoryStatus))
                
                return float(memoryStatus.dwMemoryLoad)
            else:  # Linux/Mac
                with open('/proc/meminfo', 'r') as f:
                    lines = f.readlines()
                    total = None
                    available = None
                    
                    for line in lines:
                        if line.startswith('MemTotal:'):
                            total = int(line.split()[1])
                        elif line.startswith('MemAvailable:'):
                            available = int(line.split()[1])
                    
                    if total and available:
                        return ((total - available) / total) * 100.0
            
            return 0.0
        except Exception as e:
            logger.error(f"Fallback memory check failed: {e}")
            return 0.0
    
    def _get_disk_percent(self) -> float:
        """
        获取磁盘使用率
        
        Returns:
            磁盘使用率百分比
        """
        try:
            import psutil
            disk = psutil.disk_usage('/')
            return disk.percent
        except ImportError:
            # 如果没有psutil，使用os.statvfs（Linux/Mac）
            return self._get_disk_percent_fallback()
        except Exception as e:
            logger.error(f"Failed to get disk usage: {e}")
            return 0.0
    
    def _get_disk_percent_fallback(self) -> float:
        """
        获取磁盘使用率（备用方法）
        
        Returns:
            磁盘使用率百分比
        """
        try:
            if os.name != 'nt':  # Linux/Mac
                stat = os.statvfs('/')
                total = stat.f_blocks * stat.f_frsize
                free = stat.f_bfree * stat.f_frsize
                used = total - free
                return (used / total) * 100.0
            
            return 0.0
        except Exception as e:
            logger.error(f"Fallback disk check failed: {e}")
            return 0.0
    
    async def _send_alert(self, bot: Bot, message: str):
        """
        发送告警消息
        
        Args:
            bot: Telegram Bot实例
            message: 告警消息
        """
        # 添加时间戳
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        full_message = f"🚨 系统告警 [{timestamp}]\n\n{message}"
        
        # 记录告警历史
        self.alert_history.append({
            'timestamp': timestamp,
            'message': message
        })
        
        # 限制历史记录大小（保留最近100条）
        if len(self.alert_history) > 100:
            self.alert_history = self.alert_history[-100:]
        
        # 发送到管理员
        if self.admin_chat_ids and bot:
            for chat_id in self.admin_chat_ids:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=full_message
                    )
                    logger.info(f"Alert sent to admin {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to send alert to {chat_id}: {e}")
        else:
            # 如果没有配置管理员，只记录日志
            logger.warning(full_message)
    
    def record_request(self):
        """记录请求"""
        self.metrics['total_requests'] += 1
    
    def record_error(self, error: Exception):
        """
        记录错误
        
        Args:
            error: 异常对象
        """
        self.metrics['error_count'] += 1
        self.metrics['last_error'] = {
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'error_type': type(error).__name__,
            'error_message': str(error)
        }
        
        logger.error(f"Error recorded: {type(error).__name__}: {str(error)}")
    
    def get_metrics(self) -> Dict[str, any]:
        """
        获取性能指标
        
        Returns:
            性能指标字典
        """
        return {
            **self.metrics,
            'uptime': self.last_check_time,
            'alert_count': len(self.alert_history),
            'last_alert': self.alert_history[-1] if self.alert_history else None
        }
    
    def get_health_report(self) -> str:
        """
        生成健康报告
        
        Returns:
            健康报告文本
        """
        cpu = self._get_cpu_percent()
        memory = self._get_memory_percent()
        disk = self._get_disk_percent()
        
        report = "📊 系统健康报告\n\n"
        report += f"🖥️ CPU使用率: {cpu:.1f}%\n"
        report += f"💾 内存使用率: {memory:.1f}%\n"
        report += f"💿 磁盘使用率: {disk:.1f}%\n\n"
        report += f"📈 总请求数: {self.metrics['total_requests']}\n"
        report += f"❌ 错误次数: {self.metrics['error_count']}\n"
        report += f"🚨 告警次数: {len(self.alert_history)}\n"
        
        if self.metrics['last_error']:
            last_error = self.metrics['last_error']
            report += f"\n⚠️ 最后错误: {last_error['timestamp']}\n"
            report += f"   {last_error['error_type']}: {last_error['error_message']}"
        
        return report


# 全局监控实例
bot_monitor = BotMonitor()


async def start_bot_monitoring(bot: Bot, admin_chat_ids: list = None, interval: int = 60):
    """
    启动Bot监控（便捷函数）
    
    Args:
        bot: Telegram Bot实例
        admin_chat_ids: 管理员聊天ID列表
        interval: 检查间隔（秒）
    """
    global bot_monitor
    
    if admin_chat_ids:
        bot_monitor.admin_chat_ids = admin_chat_ids
    
    await bot_monitor.start_monitoring(bot, interval)


def stop_bot_monitoring():
    """停止Bot监控（便捷函数）"""
    global bot_monitor
    bot_monitor.stop_monitoring()
