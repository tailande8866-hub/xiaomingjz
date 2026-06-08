"""
初始化默认套餐数据
运行此脚本会在数据库中创建默认的SaaS套餐
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models import PricingPlan, get_db, init_db
from sqlalchemy import select


async def init_default_plans():
    """初始化默认套餐"""
    
    # 先初始化数据库表
    await init_db()
    
    print("[INIT] 正在初始化默认套餐...")
    
    # 定义默认套餐
    default_plans = [
        {
            "name": "一个月",
            "description": "适合个人使用，可创建1个机器人",
            "price": 20.0,
            "duration_days": 30,
            "max_bots": 1,
            "max_groups_per_bot": 5,
            "display_order": 1,
            "is_active": True,
            "is_popular": False
        },
        {
            "name": "三个月",
            "description": "适合小团队，可创建1个机器人",
            "price": 50.0,
            "duration_days": 90,
            "max_bots": 1,
            "max_groups_per_bot": 10,
            "display_order": 2,
            "is_active": True,
            "is_popular": True  # 热门推荐
        },
        {
            "name": "一年",
            "description": "适合企业使用，可创建1个机器人",
            "price": 188.0,
            "duration_days": 365,
            "max_bots": 1,
            "max_groups_per_bot": 50,
            "display_order": 3,
            "is_active": True,
            "is_popular": False
        },
        {
            "name": "永久使用",
            "description": "超值永久套餐，可创建1个机器人",
            "price": 368.0,
            "duration_days": 99999,
            "max_bots": 1,
            "max_groups_per_bot": 100,
            "display_order": 4,
            "is_active": True,
            "is_popular": False
        }
    ]
    
    async for db in get_db():
        try:
            # 检查是否已有套餐
            query = select(PricingPlan)
            result = await db.execute(query)
            existing_plans = result.scalars().all()
            
            if existing_plans:
                print(f"[SKIP] 数据库中已有 {len(existing_plans)} 个套餐，跳过初始化")
                for plan in existing_plans:
                    print(f"   - {plan.name}: {plan.price} USDT / {plan.duration_days}天")
                return
            
            # 创建默认套餐
            for plan_data in default_plans:
                plan = PricingPlan(**plan_data)
                db.add(plan)
                print(f"[OK] 创建套餐: {plan_data['name']} - {plan_data['price']} USDT")
            
            await db.commit()
            print("\n[DONE] 默认套餐初始化完成！")
            print("\n可用套餐列表：")
            for plan_data in default_plans:
                popular_tag = " [热门]" if plan_data['is_popular'] else ""
                print(f"  • {plan_data['name']}{popular_tag}")
                print(f"    价格: {plan_data['price']} USDT")
                print(f"    时长: {plan_data['duration_days']} 天")
                print(f"    机器人数量: {plan_data['max_bots']} 个")
                print(f"    每Bot群组数: {plan_data['max_groups_per_bot']} 个")
                print()
                
        except Exception as e:
            print(f"[ERROR] 初始化失败: {e}")
            import traceback
            traceback.print_exc()
            await db.rollback()
        finally:
            break


if __name__ == "__main__":
    print("=" * 60)
    print("SaaS套餐初始化工具")
    print("=" * 60)
    print()
    
    asyncio.run(init_default_plans())
