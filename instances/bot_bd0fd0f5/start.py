#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子机器人启动脚本 - bot_bd0fd0f5"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 获取当前脚本所在目录（即实例目录）
instance_dir = Path(__file__).parent

# 加载实例目录下的 .env 文件
env_file = instance_dir / ".env"
if env_file.exists():
    load_dotenv(env_file, override=True)

# 关键修复：如果没有 .env 文件，从目录名读取 INSTANCE_ID
if not os.environ.get("INSTANCE_ID"):
    # 从实例目录名获取 instance_id
    instance_id_from_dir = instance_dir.name
    if instance_id_from_dir.startswith("bot_"):
        os.environ["INSTANCE_ID"] = instance_id_from_dir
        print(f"Set INSTANCE_ID from directory name: {instance_id_from_dir}")

# 关键修复：子机器人必须使用父目录的主数据库
# 这样所有子机器人都能访问 BotCreation 表进行健康检查
# instance_dir = bot_instances/bot_xxx
# parent_dir = bot_instances
# project_root = 项目根目录 (AAAJIZHANG-main)
parent_dir = instance_dir.parent
project_root = parent_dir.parent  # 再往上一级才是项目根目录

def _sqlite_url_path_exists(database_url: str) -> bool:
    if not database_url.startswith("sqlite"):
        return True
    raw_path = database_url.split("///", 1)[-1]
    return Path(raw_path).exists()

configured_db_url = os.environ.get("SHARED_DATABASE_URL") or os.environ.get("DATABASE_URL")
if configured_db_url and _sqlite_url_path_exists(configured_db_url):
    shared_db_url = configured_db_url
else:
    test_db_path = project_root / "accounting_bot_test.db"
    main_db_path = project_root / "accounting_bot.db"
    shared_db_path = test_db_path if test_db_path.exists() else main_db_path
    shared_db_url = f"sqlite+aiosqlite:///{shared_db_path}"

os.environ["DATABASE_URL"] = shared_db_url
os.environ["SHARED_DATABASE_URL"] = shared_db_url

# 添加项目根目录到路径
sys.path.insert(0, str(project_root))

# 切换工作目录到实例目录
os.chdir(str(instance_dir))

# 导入并运行机器人
from src.bot import main

if __name__ == "__main__":
    main()
