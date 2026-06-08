"""
自动备份脚本

功能:
1. 自动备份SQLite数据库
2. 保留最近N天的备份
3. 可配置备份频率(每日/每周)
4. 备份到指定目录

使用方法:
- 手动执行: python scripts/auto_backup.py
- 定时任务: 添加到crontab或Windows任务计划程序
"""
import os
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/backup.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置参数
BACKUP_DIR = Path("./backups")  # 备份目录
DB_FILE = Path("./accounting_bot.db")  # 数据库文件
RETENTION_DAYS = 30  # 保留天数
MAX_BACKUPS = 50  # 最大备份数量


def create_backup():
    """创建数据库备份"""
    try:
        # 确保备份目录存在
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        
        # 检查数据库文件是否存在
        if not DB_FILE.exists():
            logger.error(f"❌ 数据库文件不存在: {DB_FILE}")
            return False
        
        # 生成备份文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"db_backup_{timestamp}.db"
        backup_path = BACKUP_DIR / backup_filename
        
        # 复制数据库文件
        shutil.copy2(DB_FILE, backup_path)
        
        # 验证备份文件
        if backup_path.exists() and backup_path.stat().st_size > 0:
            file_size_mb = backup_path.stat().st_size / (1024 * 1024)
            logger.info(f"✅ 备份成功: {backup_filename} ({file_size_mb:.2f} MB)")
            return True
        else:
            logger.error(f"❌ 备份文件验证失败: {backup_filename}")
            return False
            
    except Exception as e:
        logger.error(f"❌ 备份失败: {e}", exc_info=True)
        return False


def cleanup_old_backups():
    """清理过期备份"""
    try:
        if not BACKUP_DIR.exists():
            return
        
        # 获取所有备份文件
        backup_files = list(BACKUP_DIR.glob("db_backup_*.db"))
        
        if not backup_files:
            logger.info("ℹ️ 没有备份文件需要清理")
            return
        
        # 按修改时间排序
        backup_files.sort(key=lambda x: x.stat().st_mtime)
        
        # 删除超过保留天数的备份
        cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)
        deleted_count = 0
        
        for backup_file in backup_files:
            file_mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
            
            # 删除条件: 超过保留天数 或 超过最大数量
            should_delete = (
                file_mtime < cutoff_date or 
                len(backup_files) - deleted_count > MAX_BACKUPS
            )
            
            if should_delete:
                try:
                    backup_file.unlink()
                    deleted_count += 1
                    logger.info(f"🗑️ 删除过期备份: {backup_file.name}")
                except Exception as e:
                    logger.warning(f"⚠️ 删除备份失败 {backup_file.name}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✨ 清理完成: 删除了 {deleted_count} 个过期备份")
        else:
            logger.info("ℹ️ 无需清理备份")
            
    except Exception as e:
        logger.error(f"❌ 清理备份失败: {e}", exc_info=True)


def get_backup_stats():
    """获取备份统计信息"""
    try:
        if not BACKUP_DIR.exists():
            return {"count": 0, "total_size_mb": 0, "oldest": None, "newest": None}
        
        backup_files = list(BACKUP_DIR.glob("db_backup_*.db"))
        
        if not backup_files:
            return {"count": 0, "total_size_mb": 0, "oldest": None, "newest": None}
        
        total_size = sum(f.stat().st_size for f in backup_files)
        total_size_mb = total_size / (1024 * 1024)
        
        dates = [datetime.fromtimestamp(f.stat().st_mtime) for f in backup_files]
        
        return {
            "count": len(backup_files),
            "total_size_mb": round(total_size_mb, 2),
            "oldest": min(dates).strftime("%Y-%m-%d %H:%M:%S"),
            "newest": max(dates).strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except Exception as e:
        logger.error(f"❌ 获取备份统计失败: {e}")
        return {"count": 0, "total_size_mb": 0, "oldest": None, "newest": None}


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("🔄 开始自动备份流程")
    logger.info("=" * 60)
    
    # 1. 创建备份
    logger.info("📦 步骤1: 创建数据库备份...")
    success = create_backup()
    
    if not success:
        logger.error("❌ 备份失败,退出")
        return False
    
    # 2. 清理过期备份
    logger.info("\n🧹 步骤2: 清理过期备份...")
    cleanup_old_backups()
    
    # 3. 显示统计信息
    logger.info("\n📊 步骤3: 备份统计信息")
    stats = get_backup_stats()
    logger.info(f"   备份数量: {stats['count']}")
    logger.info(f"   总大小: {stats['total_size_mb']} MB")
    if stats['oldest']:
        logger.info(f"   最早备份: {stats['oldest']}")
    if stats['newest']:
        logger.info(f"   最新备份: {stats['newest']}")
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ 自动备份流程完成")
    logger.info("=" * 60)
    
    return True


if __name__ == "__main__":
    main()
