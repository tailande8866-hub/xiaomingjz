"""
统一 .env 文件生成器

🔥 这是全系统唯一的 .env 生成入口
🔥 所有 BOT 创建/恢复/修复路径都必须调用此模块
🔥 禁止在其他地方自行拼接 .env 内容

权限模型：
  SUPER_ADMIN_ID = 全局超管ID（平台最高权限，对所有BOT生效）
  BOT_OWNER_ID   = 当前BOT的创建者/拥有者ID
"""

import os
import logging
from pathlib import Path
from typing import Optional
from ..utils.database_url import get_shared_database_url

logger = logging.getLogger(__name__)

# 统一 .env 模板（唯一模板，禁止在其他地方定义第二份）
ENV_TEMPLATE = """# Bot配置
BOT_TOKEN={bot_token}
BOT_USERNAME={bot_username}

# 关键配置：标记为子机器人（非主机器人）
IS_MAIN_BOT=false

# 租户身份标识（多租户隔离核心）
INSTANCE_ID={instance_id}

# 数据库配置：统一共享数据库（支持无限裂变）
SHARED_DATABASE_URL={database_url}
DATABASE_URL={database_url}

# 管理员配置
# SUPER_ADMIN_ID: 全局超管ID（平台最高权限，对所有BOT生效）
SUPER_ADMIN_ID={super_admin_id}
# BOT_OWNER_ID: 当前BOT的创建者/拥有者ID
BOT_OWNER_ID={bot_owner_id}
OWNER_USER_ID={bot_owner_id}

# 默认设置
DEFAULT_CURRENCY=USDT
DEFAULT_EXCHANGE_RATE=7.3
DEFAULT_FEE_RATE=3

# 时区配置
TIMEZONE=Asia/Shanghai
"""


def get_global_super_admin_id() -> int:
    """
    获取全局超管ID（统一入口）
    
    优先级：config.SUPER_ADMIN_ID > 环境变量 SUPER_ADMIN_ID > 0
    """
    try:
        from config import config
        config_val = getattr(config, 'SUPER_ADMIN_ID', 0)
    except Exception:
        config_val = 0
    
    env_val = os.getenv('SUPER_ADMIN_ID', '0')
    
    try:
        result = int(config_val) or int(env_val)
    except (ValueError, TypeError):
        result = 0
    
    return result


def generate_env_content(
    bot_token: str,
    instance_id: str,
    bot_owner_id: int,
    bot_username: str = "",
    super_admin_id: Optional[int] = None,
    database_url: Optional[str] = None,
) -> str:
    """
    生成 .env 文件内容（统一入口）
    
    Args:
        bot_token: Bot Token（明文）
        instance_id: 实例ID（如 bot_a1b2c3d4）
        bot_owner_id: 当前BOT的创建者/拥有者ID
        bot_username: Bot 用户名
        super_admin_id: 全局超管ID（不传则自动获取）
        database_url: 数据库连接URL
    
    Returns:
        .env 文件内容字符串
    """
    if super_admin_id is None:
        super_admin_id = get_global_super_admin_id()
    database_url = get_shared_database_url(database_url)
    
    content = ENV_TEMPLATE.format(
        bot_token=bot_token,
        bot_username=bot_username or "",
        instance_id=instance_id,
        database_url=database_url,
        super_admin_id=super_admin_id,
        bot_owner_id=bot_owner_id,
    )
    
    logger.info(f"[EnvGenerator] Generated .env for instance={instance_id}, "
                f"super_admin={super_admin_id}, bot_owner={bot_owner_id}")
    
    return content


async def ensure_env_file(
    instance_dir: str,
    bot_token: str,
    instance_id: str,
    bot_owner_id: int,
    bot_username: str = "",
    super_admin_id: Optional[int] = None,
    database_url: Optional[str] = None,
) -> bool:
    """
    确保 .env 文件存在（不存在则自动生成）
    
    这是所有 BOT 恢复/启动路径的统一入口。
    如果 .env 已存在则跳过，不存在则自动生成。
    
    Args:
        instance_dir: 实例目录路径
        bot_token: Bot Token（明文或加密后的，需调用方解密）
        instance_id: 实例ID
        bot_owner_id: 当前BOT的创建者/拥有者ID
        bot_username: Bot 用户名
        super_admin_id: 全局超管ID
        database_url: 数据库连接URL
    
    Returns:
        True = 文件已存在或生成成功，False = 生成失败
    """
    dir_path = Path(instance_dir)
    env_path = dir_path / ".env"
    
    # 目录不存在则创建
    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[EnvGenerator] Created instance directory: {instance_dir}")
    
    # .env 已存在则跳过
    if env_path.exists():
        logger.info(f"[EnvGenerator] .env already exists: {env_path}, skipping")
        return True
    
    # 生成 .env
    try:
        content = generate_env_content(
            bot_token=bot_token,
            instance_id=instance_id,
            bot_owner_id=bot_owner_id,
            bot_username=bot_username,
            super_admin_id=super_admin_id,
            database_url=database_url,
        )
        env_path.write_text(content, encoding="utf-8")
        logger.info(f"[EnvGenerator] ✅ Generated .env: {env_path}")
        return True
    except Exception as e:
        logger.error(f"[EnvGenerator] ❌ Failed to generate .env: {e}", exc_info=True)
        return False
