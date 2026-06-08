#!/usr/bin/env python3
"""
Telegram记账机器人启动脚本
"""
import sys
import os

# 禁用Python字节码缓存（开发/本地测试时使用，运营时再移除）
sys.dont_write_bytecode = True

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ✅ 自动数据库迁移（在启动时检查并添加缺失字段）
try:
    from src.utils.db_auto_migrate import auto_migrate_on_startup
    auto_migrate_on_startup()
except Exception as e:
    print(f"⚠️  数据库迁移失败: {e}（将继续启动）")

from src.bot import main

if __name__ == "__main__":
    main()
