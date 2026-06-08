"""
数据库索引优化模块

分析高频查询并添加缺失的索引，提升查询性能
"""
import logging
from sqlalchemy import text
from .database import get_db

logger = logging.getLogger(__name__)


async def analyze_slow_queries():
    """
    分析慢查询
    
    Returns:
        慢查询列表
    """
    slow_queries = []
    
    # Transaction表的高频查询
    slow_queries.append({
        'table': 'transactions',
        'query_pattern': 'SELECT * FROM transactions WHERE group_id = ? AND transaction_date BETWEEN ? AND ?',
        'frequency': 'high',
        'current_indexes': ['group_id', 'transaction_date'],
        'suggested_index': 'idx_transactions_group_date (group_id, transaction_date)'
    })
    
    slow_queries.append({
        'table': 'transactions',
        'query_pattern': 'SELECT * FROM transactions WHERE user_id = ? ORDER BY transaction_date DESC',
        'frequency': 'medium',
        'current_indexes': ['user_id', 'transaction_date'],
        'suggested_index': 'idx_transactions_user_date (user_id, transaction_date)'
    })
    
    slow_queries.append({
        'table': 'transactions',
        'query_pattern': 'SELECT * FROM transactions WHERE operator_id = ? AND is_deleted = false',
        'frequency': 'low',
        'current_indexes': [],
        'suggested_index': 'idx_transactions_operator_deleted (operator_id, is_deleted)'
    })
    
    # GroupOperator表的高频查询
    slow_queries.append({
        'table': 'group_operators',
        'query_pattern': 'SELECT * FROM group_operators WHERE group_id = ? AND user_id = ?',
        'frequency': 'high',
        'current_indexes': ['group_id', 'user_id'],
        'suggested_index': 'idx_group_operators_group_user (group_id, user_id)'
    })
    
    # Subscription表的高频查询
    slow_queries.append({
        'table': 'subscriptions',
        'query_pattern': 'SELECT * FROM subscriptions WHERE telegram_id = ? AND status = ?',
        'frequency': 'high',
        'current_indexes': ['telegram_id'],
        'suggested_index': 'idx_subscriptions_telegram_status (telegram_id, status)'
    })
    
    slow_queries.append({
        'table': 'subscriptions',
        'query_pattern': 'SELECT * FROM subscriptions WHERE status = ? AND expire_date < ?',
        'frequency': 'medium',
        'current_indexes': [],
        'suggested_index': 'idx_subscriptions_status_expire (status, expire_date)'
    })
    
    # BotCreation表的高频查询
    slow_queries.append({
        'table': 'bot_creations',
        'query_pattern': 'SELECT * FROM bot_creations WHERE telegram_id = ? AND status = ?',
        'frequency': 'high',
        'current_indexes': ['telegram_id'],
        'suggested_index': 'idx_bot_creations_telegram_status (telegram_id, status)'
    })
    
    slow_queries.append({
        'table': 'bot_creations',
        'query_pattern': 'SELECT * FROM bot_creations WHERE status IN (?, ?)',
        'frequency': 'medium',
        'current_indexes': [],
        'suggested_index': 'idx_bot_creations_status (status)'
    })
    
    # PaymentOrder表的高频查询
    slow_queries.append({
        'table': 'payment_orders',
        'query_pattern': 'SELECT * FROM payment_orders WHERE order_id = ?',
        'frequency': 'high',
        'current_indexes': ['order_id'],
        'suggested_index': 'Already indexed'
    })
    
    slow_queries.append({
        'table': 'payment_orders',
        'query_pattern': 'SELECT * FROM payment_orders WHERE telegram_id = ? AND status = ?',
        'frequency': 'high',
        'current_indexes': ['telegram_id'],
        'suggested_index': 'idx_payment_orders_telegram_status (telegram_id, status)'
    })
    
    slow_queries.append({
        'table': 'payment_orders',
        'query_pattern': 'SELECT * FROM payment_orders WHERE status = ? AND expire_time < ?',
        'frequency': 'medium',
        'current_indexes': [],
        'suggested_index': 'idx_payment_orders_status_expire (status, expire_time)'
    })
    
    return slow_queries


async def create_missing_indexes():
    """
    创建缺失的索引
    
    Returns:
        创建的索引列表
    """
    created_indexes = []
    
    async for db in get_db():
        try:
            # 1. Transaction表复合索引
            indexes_to_create = [
                # Transaction表
                ("idx_transactions_group_date", "transactions", "(group_id, transaction_date)"),
                ("idx_transactions_user_date", "transactions", "(user_id, transaction_date)"),
                ("idx_transactions_operator_deleted", "transactions", "(operator_id, is_deleted)"),
                ("idx_transactions_type_date", "transactions", "(transaction_type, transaction_date)"),
                
                # GroupOperator表
                ("idx_group_operators_group_user", "group_operators", "(group_id, user_id)"),
                
                # Subscription表
                ("idx_subscriptions_telegram_status", "subscriptions", "(telegram_id, status)"),
                ("idx_subscriptions_status_expire", "subscriptions", "(status, expire_date)"),
                
                # BotCreation表
                ("idx_bot_creations_telegram_status", "bot_creations", "(telegram_id, status)"),
                ("idx_bot_creations_status", "bot_creations", "(status)"),
                
                # PaymentOrder表
                ("idx_payment_orders_telegram_status", "payment_orders", "(telegram_id, status)"),
                ("idx_payment_orders_status_expire", "payment_orders", "(status, expire_time)"),
            ]
            
            for index_name, table_name, columns in indexes_to_create:
                try:
                    # 检查索引是否已存在
                    check_sql = text("""
                        SELECT name FROM sqlite_master 
                        WHERE type='index' AND name=:index_name
                    """)
                    result = await db.execute(check_sql, {"index_name": index_name})
                    existing = result.scalar_one_or_none()
                    
                    if not existing:
                        # 创建索引
                        create_sql = text(f"CREATE INDEX {index_name} ON {table_name} {columns}")
                        await db.execute(create_sql)
                        await db.commit()
                        
                        created_indexes.append({
                            'name': index_name,
                            'table': table_name,
                            'columns': columns,
                            'status': 'created'
                        })
                        logger.info(f"Created index: {index_name} on {table_name}{columns}")
                    else:
                        created_indexes.append({
                            'name': index_name,
                            'table': table_name,
                            'columns': columns,
                            'status': 'already_exists'
                        })
                        logger.debug(f"Index already exists: {index_name}")
                        
                except Exception as e:
                    logger.error(f"Failed to create index {index_name}: {e}", exc_info=True)
                    created_indexes.append({
                        'name': index_name,
                        'table': table_name,
                        'columns': columns,
                        'status': f'error: {str(e)}'
                    })
            
            return created_indexes
            
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}", exc_info=True)
            await db.rollback()
            return created_indexes
        finally:
            break


async def drop_unused_indexes():
    """
    删除未使用的索引（谨慎使用）
    
    Returns:
        删除的索引列表
    """
    # 这个方法需要实际监控索引使用情况后再决定
    # 暂时不实现，避免误删重要索引
    logger.warning("drop_unused_indexes is not implemented yet")
    return []


async def optimize_database():
    """
    执行数据库优化
    
    Returns:
        优化结果
    """
    logger.info("Starting database optimization...")
    
    # 1. 分析慢查询
    logger.info("Analyzing slow queries...")
    slow_queries = await analyze_slow_queries()
    logger.info(f"Found {len(slow_queries)} potential slow query patterns")
    
    # 2. 创建缺失的索引
    logger.info("Creating missing indexes...")
    created_indexes = await create_missing_indexes() or []
    
    created_count = sum(1 for idx in created_indexes if idx['status'] == 'created')
    exists_count = sum(1 for idx in created_indexes if idx['status'] == 'already_exists')
    error_count = sum(1 for idx in created_indexes if idx['status'].startswith('error'))
    
    logger.info(f"Index creation completed:")
    logger.info(f"  - Created: {created_count}")
    logger.info(f"  - Already exists: {exists_count}")
    logger.info(f"  - Errors: {error_count}")
    
    # 3. 运行VACUUM优化数据库文件
    logger.info("Running VACUUM to optimize database file...")
    async for db in get_db():
        try:
            await db.execute(text("VACUUM"))
            logger.info("Database VACUUM completed")
        except Exception as e:
            logger.error(f"VACUUM failed: {e}", exc_info=True)
        finally:
            break
    
    return {
        'slow_queries_analyzed': len(slow_queries),
        'indexes_created': created_count,
        'indexes_already_exists': exists_count,
        'indexes_errors': error_count,
        'details': created_indexes
    }


# 如果需要手动运行优化
if __name__ == "__main__":
    import asyncio
    
    async def main():
        result = await optimize_database()
        print("\n优化结果:")
        print(f"  分析的慢查询模式: {result['slow_queries_analyzed']}")
        print(f"  创建的索引: {result['indexes_created']}")
        print(f"  已存在的索引: {result['indexes_already_exists']}")
        print(f"  错误数: {result['indexes_errors']}")
        
        if result['details']:
            print("\n索引详情:")
            for idx in result['details']:
                print(f"  - {idx['name']}: {idx['status']}")
    
    asyncio.run(main())
