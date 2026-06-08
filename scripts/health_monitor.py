"""
Bot健康监控脚本

功能:
1. 检查Bot进程是否运行
2. 检查数据库连接
3. 检查磁盘空间
4. 检查内存使用
5. 发送告警通知(可选)

使用方法:
- 手动执行: python scripts/health_monitor.py
- 定时任务: 每5分钟执行一次
"""
import os
import sys
import json
import logging
import psutil
from datetime import datetime
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置参数
ALERT_THRESHOLD = {
    'disk_usage_percent': 90,  # 磁盘使用率告警阈值
    'memory_mb': 400,  # 内存使用告警阈值(MB)
    'db_size_mb': 1000,  # 数据库大小告警阈值(MB)
}


def check_process_running():
    """检查Bot进程是否在运行"""
    try:
        # 查找python main.py进程
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and 'main.py' in ' '.join(cmdline):
                    return True, proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        return False, None
    except Exception as e:
        logger.error(f"❌ 检查进程失败: {e}")
        return False, None


def check_database():
    """检查数据库连接和状态"""
    try:
        from src.models.database import get_db_session
        from sqlalchemy import text
        import asyncio
        
        async def _check():
            async with get_db_session() as db:
                # 测试查询
                result = await db.execute(text("SELECT 1"))
                result.scalar()
                
                # 获取数据库大小
                db_path = Path("./accounting_bot.db")
                if db_path.exists():
                    size_mb = db_path.stat().st_size / (1024 * 1024)
                    return True, f"{size_mb:.2f} MB"
                else:
                    return True, "N/A (PostgreSQL)"
        
        success, size = asyncio.run(_check())
        return success, size
        
    except Exception as e:
        logger.error(f"❌ 数据库检查失败: {e}")
        return False, str(e)


def check_disk_space():
    """检查磁盘空间"""
    try:
        usage = psutil.disk_usage('/')
        percent = usage.percent
        free_gb = usage.free / (1024 ** 3)
        
        status = "OK" if percent < ALERT_THRESHOLD['disk_usage_percent'] else "WARNING"
        
        return status == "OK", {
            'percent': percent,
            'free_gb': round(free_gb, 2),
            'status': status
        }
    except Exception as e:
        logger.error(f"❌ 磁盘空间检查失败: {e}")
        return False, {'percent': 0, 'free_gb': 0, 'status': 'ERROR'}


def check_memory_usage():
    """检查内存使用"""
    try:
        # 获取Bot进程的内存使用
        bot_memory_mb = 0
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
            try:
                cmdline = proc.info.get('cmdline', [])
                if cmdline and 'main.py' in ' '.join(cmdline):
                    memory_mb = proc.info['memory_info'].rss / (1024 * 1024)
                    bot_memory_mb = memory_mb
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        status = "OK" if bot_memory_mb < ALERT_THRESHOLD['memory_mb'] else "WARNING"
        
        return status == "OK", {
            'memory_mb': round(bot_memory_mb, 2),
            'threshold_mb': ALERT_THRESHOLD['memory_mb'],
            'status': status
        }
    except Exception as e:
        logger.error(f"❌ 内存使用检查失败: {e}")
        return False, {'memory_mb': 0, 'threshold_mb': 0, 'status': 'ERROR'}


def check_log_files():
    """检查日志文件状态"""
    try:
        log_dir = Path("./logs")
        if not log_dir.exists():
            return False, "日志目录不存在"
        
        # 检查错误日志
        error_log = log_dir / "error.log"
        if error_log.exists():
            # 检查最近是否有新错误
            mtime = datetime.fromtimestamp(error_log.stat().st_mtime)
            age_hours = (datetime.now() - mtime).total_seconds() / 3600
            
            if age_hours < 1:  # 1小时内有错误日志更新
                return False, f"最近{age_hours:.1f}小时有错误"
        
        return True, "正常"
    except Exception as e:
        logger.error(f"❌ 日志文件检查失败: {e}")
        return False, str(e)


def generate_health_report():
    """生成健康报告"""
    report = {
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'checks': {}
    }
    
    # 1. 进程检查
    process_ok, pid = check_process_running()
    report['checks']['process'] = {
        'status': 'OK' if process_ok else 'FAIL',
        'pid': pid,
        'message': f"进程运行中 (PID: {pid})" if process_ok else "进程未运行"
    }
    
    # 2. 数据库检查
    db_ok, db_size = check_database()
    report['checks']['database'] = {
        'status': 'OK' if db_ok else 'FAIL',
        'size': db_size,
        'message': f"数据库正常 ({db_size})" if db_ok else f"数据库异常: {db_size}"
    }
    
    # 3. 磁盘空间检查
    disk_ok, disk_info = check_disk_space()
    report['checks']['disk'] = {
        'status': disk_info['status'],
        'usage_percent': disk_info['percent'],
        'free_gb': disk_info['free_gb'],
        'message': f"磁盘使用 {disk_info['percent']:.1f}%, 剩余 {disk_info['free_gb']} GB"
    }
    
    # 4. 内存使用检查
    memory_ok, memory_info = check_memory_usage()
    report['checks']['memory'] = {
        'status': memory_info['status'],
        'memory_mb': memory_info['memory_mb'],
        'threshold_mb': memory_info['threshold_mb'],
        'message': f"内存使用 {memory_info['memory_mb']} MB (阈值: {memory_info['threshold_mb']} MB)"
    }
    
    # 5. 日志文件检查
    log_ok, log_msg = check_log_files()
    report['checks']['logs'] = {
        'status': 'OK' if log_ok else 'WARNING',
        'message': log_msg
    }
    
    # 总体状态
    all_ok = all(check['status'] == 'OK' for check in report['checks'].values())
    report['overall_status'] = 'HEALTHY' if all_ok else 'UNHEALTHY'
    
    return report


def send_alert(report):
    """发送告警通知(可扩展)"""
    # TODO: 实现告警通知
    # 可以集成:
    # - Telegram Bot消息
    # - 邮件通知
    # - Webhook
    # - Slack/Discord
    
    if report['overall_status'] == 'UNHEALTHY':
        logger.warning("⚠️ 系统健康检查失败,需要关注!")
        
        for check_name, check_info in report['checks'].items():
            if check_info['status'] != 'OK':
                logger.warning(f"   {check_name}: {check_info['message']}")


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("🔍 开始健康检查")
    logger.info("=" * 60)
    
    # 生成健康报告
    report = generate_health_report()
    
    # 输出报告
    logger.info("\n📊 健康检查报告:")
    logger.info(f"   时间: {report['timestamp']}")
    logger.info(f"   状态: {report['overall_status']}")
    logger.info("")
    
    for check_name, check_info in report['checks'].items():
        icon = "✅" if check_info['status'] == 'OK' else "❌" if check_info['status'] == 'FAIL' else "⚠️"
        logger.info(f"   {icon} {check_name.upper()}: {check_info['message']}")
    
    # 保存报告到文件
    report_file = Path("./logs/health_report.json")
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\n💾 报告已保存: {report_file}")
    
    # 发送告警(如果有问题)
    send_alert(report)
    
    logger.info("\n" + "=" * 60)
    
    # 返回退出码(用于cron判断)
    return 0 if report['overall_status'] == 'HEALTHY' else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
