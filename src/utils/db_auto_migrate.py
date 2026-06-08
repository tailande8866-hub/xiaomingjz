"""
数据库自动迁移脚本

在 Bot 启动时自动检测并添加缺失的数据库字段
"""
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def migrate_database(db_path: str) -> bool:
    """
    自动迁移数据库,添加缺失的字段
    
    Args:
        db_path: 数据库文件路径
    
    Returns:
        True 如果迁移成功
    """
    try:
        logger.info(f"🔧 开始检查数据库迁移: {db_path}")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 检查 transactions 表的字段
        cursor.execute("PRAGMA table_info(transactions)")
        columns = [row[1] for row in cursor.fetchall()]
        
        migrations_needed = []
        
        # 检查 batch_id 字段
        if 'batch_id' not in columns:
            migrations_needed.append('batch_id')
            logger.info("  需要添加字段: batch_id")
        
        # 检查 operator_chat_id 字段
        if 'operator_chat_id' not in columns:
            migrations_needed.append('operator_chat_id')
            logger.info("  需要添加字段: operator_chat_id")
        
        # 执行迁移
        if migrations_needed:
            logger.info(f"  开始迁移 {len(migrations_needed)} 个字段...")
            
            if 'batch_id' in migrations_needed:
                cursor.execute(
                    "ALTER TABLE transactions ADD COLUMN batch_id TEXT"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_transactions_batch_id ON transactions(batch_id)"
                )
                logger.info("  ✅ 添加 batch_id 字段成功")
            
            if 'operator_chat_id' in migrations_needed:
                cursor.execute(
                    "ALTER TABLE transactions ADD COLUMN operator_chat_id INTEGER"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_transactions_operator_chat_id ON transactions(operator_chat_id)"
                )
                logger.info("  ✅ 添加 operator_chat_id 字段成功")
            
            conn.commit()
            logger.info("✅ 数据库迁移完成")
        else:
            logger.info("✅ 数据库已是最新版本,无需迁移")
        
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ 数据库迁移失败: {e}", exc_info=True)
        return False


def auto_migrate_on_startup():
    """
    启动时自动迁移
    
    支持两种数据库路径:
    1. /app/accounting_bot.db (容器根目录)
    2. /app/data/accounting_bot.db (数据目录)
    """
    # 可能的数据库路径
    possible_paths = [
        '/app/accounting_bot.db',
        '/app/data/accounting_bot.db',
        './accounting_bot.db',
        './data/accounting_bot.db'
    ]
    
    for db_path in possible_paths:
        path = Path(db_path)
        if path.exists():
            logger.info(f"找到数据库: {path.absolute()}")
            migrate_database(str(path.absolute()))
            return
    
    logger.warning("未找到数据库文件,跳过迁移")


if __name__ == "__main__":
    # 直接运行此脚本进行测试
    logging.basicConfig(level=logging.INFO)
    auto_migrate_on_startup()
