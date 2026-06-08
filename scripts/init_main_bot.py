"""
初始化主Bot记录到数据库

用于修复主Bot在数据库中不存在导致的租户上下文查找失败问题
"""
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_main_bot():
    """初始化主Bot记录"""
    
    # 从环境变量获取数据库连接信息
    db_user = os.getenv("DB_USER", "admin")
    db_password = os.getenv("DB_PASSWORD", "ChangeMe123")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "saas_accounting")
    
    # 主Bot信息
    bot_id = os.getenv("INSTANCE_ID", "bot_8700502141")
    bot_token_prefix = bot_id.replace("bot_", "")
    super_admin_id = int(os.getenv("SUPER_ADMIN_ID", "7862093562"))
    
    # 构建数据库连接URL
    database_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    
    logger.info(f"🔌 连接到数据库: {db_host}:{db_port}/{db_name}")
    logger.info(f" 主Bot ID: {bot_id}")
    logger.info(f"👤 超级管理员 ID: {super_admin_id}")
    
    # 创建异步引擎
    engine = create_async_engine(database_url)
    
    try:
        async with engine.begin() as conn:
            # 插入主Bot记录
            sql = text("""
                INSERT INTO bot_creations (
                    telegram_id,
                    bot_token,
                    bot_username,
                    bot_name,
                    instance_id,
                    instance_dir,
                    db_path,
                    env_path,
                    status,
                    super_admin_id,
                    parent_bot_id,
                    root_bot_id,
                    tree_depth,
                    core_version,
                    ui_version,
                    permission_version,
                    created_at,
                    started_at,
                    stopped_at,
                    updated_at,
                    config_json,
                    config_snapshot
                ) VALUES (
                    :telegram_id,
                    :bot_token,
                    :bot_username,
                    :bot_name,
                    :instance_id,
                    :instance_dir,
                    :db_path,
                    :env_path,
                    :status,
                    :super_admin_id,
                    NULL,
                    :root_bot_id,
                    0,
                    '1.0.0',
                    '1.0.0',
                    '1.0.0',
                    NOW(),
                    NOW(),
                    NULL,
                    NOW(),
                    '{}',
                    '{"enable_ai": false, "enable_auto_day_cut": true}'
                ) ON CONFLICT (instance_id) DO UPDATE SET
                    telegram_id = EXCLUDED.telegram_id,
                    bot_username = EXCLUDED.bot_username,
                    status = EXCLUDED.status,
                    super_admin_id = EXCLUDED.super_admin_id,
                    updated_at = NOW();
            """)
            
            await conn.execute(sql, {
                "telegram_id": int(bot_token_prefix),
                "bot_token": f"{bot_token_prefix}:PLACEHOLDER_TOKEN",
                "bot_username": "main_bot",
                "bot_name": "Main Bot",
                "instance_id": bot_id,
                "instance_dir": f"/app/bot_instances/{bot_id}",
                "db_path": f"/app/bot_instances/{bot_id}/data.db",
                "env_path": f"/app/bot_instances/{bot_id}/.env",
                "status": "running",
                "super_admin_id": super_admin_id,
                "root_bot_id": bot_id,
            })
            
            logger.info("✅ 主Bot记录已成功插入/更新到数据库")
            
            # 验证插入结果
            result = await conn.execute(text("""
                SELECT instance_id, bot_username, super_admin_id, status 
                FROM bot_creations 
                WHERE instance_id = :instance_id
            """), {"instance_id": bot_id})
            
            row = result.fetchone()
            if row:
                logger.info(f"📊 验证结果: instance_id={row[0]}, username={row[1]}, admin_id={row[2]}, status={row[3]}")
            else:
                logger.error("❌ 验证失败：未找到主Bot记录")
    
    except Exception as e:
        logger.error(f"❌ 初始化主Bot记录失败: {e}", exc_info=True)
        raise
    finally:
        await engine.dispose()
        logger.info("🔌 数据库连接已关闭")


if __name__ == "__main__":
    print("=" * 60)
    print("初始化主Bot记录到数据库")
    print("=" * 60)
    print()
    
    # 检查必要的环境变量
    required_envs = ["DB_HOST", "DB_PORT", "DB_NAME"]
    missing_envs = [env for env in required_envs if not os.getenv(env)]
    
    if missing_envs:
        print("❌ 缺少必要的环境变量:")
        for env in missing_envs:
            print(f"   - {env}")
        print()
        print("请设置这些环境变量后重新运行脚本")
        exit(1)
    
    # 运行初始化
    asyncio.run(init_main_bot())
    
    print()
    print("=" * 60)
    print("初始化完成！")
    print("请重启 Bot 容器使更改生效:")
    print("  docker-compose -f docker-compose.prod.yml restart saas-bot")
    print("=" * 60)
