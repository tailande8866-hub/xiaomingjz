"""
重置测试数据库 - 删除旧数据库并重新创建
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 读取测试配置
test_env_path = project_root / ".env.test"
if test_env_path.exists():
    with open(test_env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

os.environ['IS_MAIN_BOT'] = 'false'
os.environ['INSTANCE_ID'] = 'test_bot'

# 导入数据库模型
from src.models.database import Base, engine
from sqlalchemy import inspect

print("=" * 60)
print("🔄 重置测试数据库")
print("=" * 60)

# 获取数据库 URL
db_url = os.environ.get('DATABASE_URL', 'sqlite+aiosqlite:///./accounting_bot_test.db')
print(f" 数据库 URL: {db_url}")

# 提取数据库文件路径
if 'sqlite' in db_url:
    db_path = db_url.replace('sqlite+aiosqlite:///', '').replace('sqlite:///', '')
    db_path = str(project_root / db_path)
    print(f"📁 数据库文件: {db_path}")

# 删除旧数据库
if os.path.exists(db_path):
    print(f"\n🗑️  删除旧数据库文件...")
    os.remove(db_path)
    print(f"✅ 已删除: {db_path}")
else:
    print(f"\nℹ️  数据库文件不存在，将创建新数据库")

# 创建新数据库
print(f"\n 创建新数据库...")
import asyncio

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ 数据库表创建完成")

asyncio.run(create_tables())

# 验证表结构
print(f"\n🔍 验证表结构...")
import sqlite3

conn = sqlite3.connect(db_path)
cursor = conn.execute("PRAGMA table_info(transactions)")
columns = [row[1] for row in cursor.fetchall()]

print(f"📊 transactions 表共有 {len(columns)} 个字段")
print(f"✅ operator_chat_id: {'存在' if 'operator_chat_id' in columns else '不存在'}")
print(f"✅ batch_id: {'存在' if 'batch_id' in columns else '不存在'}")

conn.close()

print("\n" + "=" * 60)
print("✅ 测试数据库重置完成！")
print("=" * 60)

