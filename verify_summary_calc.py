"""验证汇总计算逻辑"""
import asyncio
import os

os.environ.setdefault('BOT_TOKEN', '123456:TEST_TOKEN_FOR_LOCAL_VERIFICATION')
os.environ['SUPER_ADMIN_ID'] = '123456'

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.models.transaction import Transaction
from src.utils.calculator import Calculator

async def verify_summary():
    DATABASE_URL = "sqlite+aiosqlite:///./accounting_bot_test.db"
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # 获取所有交易
        result = await session.execute(select(Transaction).order_by(Transaction.id))
        transactions = result.scalars().all()
        
        print(f"\n{'='*80}")
        print(f"交易数据汇总（共 {len(transactions)} 笔）")
        print(f"{'='*80}\n")
        
        # 分别统计入款和下发
        deposits = [t for t in transactions if t.transaction_type == 'deposit' and not t.is_deleted]
        withdraws = [t for t in transactions if t.transaction_type == 'withdraw' and not t.is_deleted]
        
        print(f"入款笔数: {len(deposits)}")
        print(f"下发笔数: {len(withdraws)}\n")
        
        # 计算汇总
        total_deposit_cny = sum(t.cny_amount or 0 for t in deposits)
        total_deposit_usd = sum(t.amount_usd or 0 for t in deposits)
        total_deposit_fee = sum(t.fee_amount or 0 for t in deposits)
        total_deposit_fee_usd = sum(t.fee_amount_usd or 0 for t in deposits)
        
        total_withdraw_cny = sum(t.cny_amount or 0 for t in withdraws)
        total_withdraw_usd = sum(t.amount_usd or 0 for t in withdraws)
        
        print(f"【入款汇总】")
        print(f"  总入款 CNY: {total_deposit_cny:.2f}")
        print(f"  总入款 USDT (未扣费): {total_deposit_usd + total_deposit_fee_usd:.2f}U")
        print(f"  总入款 USDT (已扣费): {total_deposit_usd:.2f}U")
        print(f"  手续费 CNY: {total_deposit_fee:.2f}")
        print(f"  手续费 USDT: {total_deposit_fee_usd:.2f}U")
        print()
        
        print(f"【下发汇总】")
        print(f"  总下发 CNY: {total_withdraw_cny:.2f}")
        print(f"  总下发 USDT: {total_withdraw_usd:.2f}U")
        print()
        
        # 计算应下发
        deposit_after_fee_cny = total_deposit_cny - total_deposit_fee
        pending_withdraw_cny = deposit_after_fee_cny - total_withdraw_cny
        
        deposit_after_fee_usd = total_deposit_usd  # 已经是扣费后的
        pending_withdraw_usd = deposit_after_fee_usd - total_withdraw_usd
        
        print(f"【应下发计算】")
        print(f"  应下发 CNY = {total_deposit_cny:.2f} - {total_deposit_fee:.2f} - {total_withdraw_cny:.2f} = {pending_withdraw_cny:.2f}")
        print(f"  应下发 USDT = {total_deposit_usd:.2f}U - {total_withdraw_usd:.2f}U = {pending_withdraw_usd:.2f}U")
        print()
        
        # 验证你截图中的数据
        print(f"{'='*80}")
        print(f"与你截图对比：")
        print(f"{'='*80}\n")
        print(f"总入款：{total_deposit_cny:.0f} ({(total_deposit_usd + total_deposit_fee_usd):.2f}U)")
        print(f"应下发：{pending_withdraw_cny:.1f} ({pending_withdraw_usd:.2f}U)")
        print(f"总下发：{total_withdraw_cny:.0f} ({total_withdraw_usd:.2f}U)")
        print(f"总结余：{pending_withdraw_cny:.1f} ({pending_withdraw_usd:.2f}U)")
        print()
        
        # 检查是否有负数
        if pending_withdraw_usd < 0:
            print(f"⚠️  应下发 USDT 是负数！{pending_withdraw_usd:.2f}U")
            print(f"   原因：入款扣费后 USDT ({total_deposit_usd:.2f}U) < 下发 USDT ({total_withdraw_usd:.2f}U)")
        else:
            print(f"✅ 应下发 USDT 是正数：{pending_withdraw_usd:.2f}U")

if __name__ == "__main__":
    asyncio.run(verify_summary())
