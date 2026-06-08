"""
USDT TRC20支付监听服务
自动检测链上转账并确认支付
"""
import logging
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, and_, update

from ..models import Subscription, PricingPlan, PaymentOrder, get_db

logger = logging.getLogger(__name__)


class USDTService:
    """USDT支付服务"""
    
    # TronScan公共API配置（无需API Key）
    TRONSCAN_API_URL = "https://apilist.tronscanapi.com/api"
    
    def __init__(self):
        # 收款地址（需要在.env中配置）
        from config import config
        self.payment_address = getattr(config, 'USDT_PAYMENT_ADDRESS', None)
        
        # 测试模式配置
        import os
        self.test_mode = os.getenv('PAYMENT_TEST_MODE', 'false').lower() == 'true'
        self.test_delay = int(os.getenv('PAYMENT_TEST_DELAY', '2'))
        self.test_generate_tx_hash = os.getenv('PAYMENT_TEST_GENERATE_TX_HASH', 'true').lower() == 'true'
        
        if not self.payment_address:
            logger.warning("USDT_PAYMENT_ADDRESS not configured in .env")
        
        if self.test_mode:
            logger.info("🧪 TEST MODE ENABLED - Payment verification will be simulated")

    
    async def generate_payment_order(
        self,
        telegram_id: int,
        username: str,
        plan_id: int,
        amount: float
    ) -> dict:
        """
        生成支付订单并保存到数据库
        
        🆕 动态金额机制：在基础金额上添加6位小数，确保每笔订单金额唯一
        例如：60 USDT -> 60.123456 USDT
        
        Returns:
            {
                'order_id': str,
                'payment_address': str,
                'amount': float,  # 动态金额（带小数）
                'base_amount': float,  # 基础金额
                'memo': str,  # 备注信息，用于识别支付
                'expire_time': datetime
            }
        """
        import uuid
        import random
        
        order_id = f"ORDER_{uuid.uuid4().hex[:12].upper()}"
        expire_time = datetime.utcnow() + timedelta(minutes=30)  # 30分钟有效期
        
        # 生成唯一备注（取telegram_id后几位 + 短随机码）
        import random
        # 取telegram_id最后4位，再加4位随机数字，总共8位
        short_id = str(telegram_id)[-4:] if len(str(telegram_id)) >=4 else str(telegram_id).zfill(4)
        random_code = ''.join([str(random.randint(0,9)) for _ in range(4)])
        memo = f"{short_id}{random_code}"
        
        # 🆕 生成动态金额：基础金额 + 6位随机小数（0.000001 - 0.999999）
        # 这样可以确保每笔订单金额唯一，便于匹配
        random_decimal = random.randint(1, 999999) / 1000000  # 0.000001 - 0.999999
        dynamic_amount = round(amount + random_decimal, 6)
        
        logger.info(f"🎯 Dynamic amount generated: {amount} + {random_decimal:.6f} = {dynamic_amount:.6f} USDT")
        
        # 保存订单到数据库
        from ..models.database import get_db_session
        
        async with get_db_session() as db:
            try:
                # 检查是否已有未支付的相同金额订单（防止重复创建）
                existing_query = select(PaymentOrder).where(
                    and_(
                        PaymentOrder.telegram_id == telegram_id,
                        PaymentOrder.plan_id == plan_id,
                        PaymentOrder.status == "pending",
                        PaymentOrder.expire_time > datetime.utcnow()
                    )
                )
                existing_result = await db.execute(existing_query)
                existing_order = existing_result.scalar_one_or_none()
                
                if existing_order:
                    # 返回现有订单
                    return {
                        'order_id': existing_order.order_id,
                        'payment_address': existing_order.payment_address,
                        'amount': existing_order.amount,
                        'base_amount': amount,
                        'memo': existing_order.memo,
                        'expire_time': existing_order.expire_time,
                        'plan_id': existing_order.plan_id
                    }
                
                # 获取套餐名称
                plan_query = select(PricingPlan).where(PricingPlan.id == plan_id)
                plan_result = await db.execute(plan_query)
                plan = plan_result.scalar_one_or_none()
                plan_name = plan.name if plan else "Unknown"
                
                # 创建新订单（使用动态金额）
                order = PaymentOrder(
                    order_id=order_id,
                    telegram_id=telegram_id,
                    username=username,
                    plan_id=plan_id,
                    plan_name=plan_name,
                    amount=dynamic_amount,  # 🆕 使用动态金额
                    payment_address=self.payment_address or "TYourUSDTAddressXXXXXXXXXXXXX",
                    memo=memo,
                    status="pending",
                    expire_time=expire_time
                )
                db.add(order)
                await db.commit()
                
                logger.info(f"Payment order created: {order_id} for user {telegram_id}, amount: {dynamic_amount:.6f} USDT")
                
                return {
                    'order_id': order_id,
                    'payment_address': order.payment_address,
                    'amount': dynamic_amount,  # 🆕 返回动态金额
                    'base_amount': amount,  # 🆕 返回基础金额
                    'memo': memo,
                    'expire_time': expire_time,
                    'plan_id': plan_id
                }
                
            except Exception as e:
                logger.error(f"Error creating payment order: {e}", exc_info=True)
                await db.rollback()
                raise
    
    async def check_payment_received(
        self,
        order_id: str,
        expected_amount: float
    ) -> tuple[bool, Optional[dict]]:
        """
        检查是否收到支付（通过TronScan API或测试模式）
        
        Args:
            order_id: 订单号
            expected_amount: 期望金额
        
        Returns:
            (是否收到支付, 交易信息字典或None)
        """
        try:
            if not self.payment_address:
                logger.error("Payment address not configured")
                return False, None
            
            # 测试模式：模拟支付成功
            if self.test_mode:
                logger.info(f"🧪 TEST MODE: Simulating payment for order {order_id}")
                
                # 延迟模拟处理时间
                if self.test_delay > 0:
                    await asyncio.sleep(self.test_delay)
                
                # 生成虚拟交易信息
                tx_info = self._generate_test_transaction_info(order_id, expected_amount)
                
                # 更新订单状态为已支付
                from ..models.database import get_db_session
                
                async with get_db_session() as db:
                    try:
                        query = select(PaymentOrder).where(PaymentOrder.order_id == order_id)
                        result = await db.execute(query)
                        order = result.scalar_one_or_none()
                        
                        if order:
                            order.status = "paid"
                            order.tx_hash = tx_info['tx_hash']
                            order.block_number = tx_info['block_number']
                            order.paid_amount = tx_info['amount']
                            order.paid_at = tx_info['paid_at']
                            order.check_count += 1
                            order.last_check_at = datetime.utcnow()
                            await db.commit()
                            
                            logger.info(f"✅ TEST MODE: Payment simulated successfully for order {order_id}")
                            return True, tx_info
                        else:
                            logger.error(f"Order not found in test mode: {order_id}")
                            return False, None
                            
                    except Exception as e:
                        logger.error(f"Error updating order in test mode: {e}", exc_info=True)
                        await db.rollback()
                        return False, None
            
            # 正式模式：从数据库获取订单信息
            from ..models.database import get_db_session
            
            async with get_db_session() as db:
                try:
                    query = select(PaymentOrder).where(PaymentOrder.order_id == order_id)
                    result = await db.execute(query)
                    order = result.scalar_one_or_none()
                    
                    if not order:
                        logger.error(f"Order not found: {order_id}")
                        return False, None
                    
                    # 更新检查次数
                    order.check_count += 1
                    order.last_check_at = datetime.utcnow()
                    await db.flush()
                    
                    # 调用TronScan API查询交易
                    async with httpx.AsyncClient(timeout=10) as client:
                        response = await client.get(
                            f"{self.TRONSCAN_API_URL}/transaction",
                            params={
                                'address': self.payment_address,
                                'limit': 50,
                                'start': 0,
                                'sort': '-timestamp'
                            }
                        )
                        
                        if response.status_code != 200:
                            logger.error(f"TronScan API error: {response.status_code}")
                            return False, None
                        
                        data = response.json()
                        transactions = data.get('data', [])
                        
                        # 遍历最近的交易
                        for tx in transactions:
                            # 检查是否是TRC20转账
                            if tx.get('contractType') != 'TriggerSmartContract':
                                continue
                            
                            # 检查接收地址
                            to_address = tx.get('toAddress', '')
                            if to_address != self.payment_address:
                                continue
                            
                            # 检查金额（USDT有6位小数）
                            raw_amount = tx.get('amount', 0)
                            actual_amount = raw_amount / 1_000_000  # 转换为USDT
                            
                            # 验证金额（允许1%误差）
                            if abs(actual_amount - expected_amount) > expected_amount * 0.01:
                                continue
                            
                            # 检查交易时间（必须在订单有效期内）
                            tx_timestamp = tx.get('timestamp', 0)
                            tx_time = datetime.fromtimestamp(tx_timestamp / 1000)
                            if tx_time < order.created_at or tx_time > order.expire_time:
                                continue
                            
                            # 找到匹配的交易！
                            tx_hash = tx.get('hash', '')
                            block_number = tx.get('blockNumber', 0)
                            
                            logger.info(f"Payment detected! Order: {order_id}, TX: {tx_hash}, Amount: {actual_amount} USDT")
                            
                            # 更新订单状态
                            order.status = "paid"
                            order.tx_hash = tx_hash
                            order.block_number = block_number
                            order.paid_amount = actual_amount
                            order.paid_at = tx_time
                            await db.commit()
                            
                            return True, {
                                'tx_hash': tx_hash,
                                'block_number': block_number,
                                'amount': actual_amount,
                                'paid_at': tx_time
                            }
                    
                    # 未找到匹配的交易
                    return False, None
                    
                except Exception as e:
                    logger.error(f"Error checking payment in DB: {e}", exc_info=True)
                    await db.rollback()
                    return False, None
            
        except Exception as e:
            logger.error(f"Error checking payment: {e}", exc_info=True)
            return False, None
    
    def _generate_test_transaction_info(self, order_id: str, amount: float) -> dict:
        """
        生成测试模式的虚拟交易信息
        
        Args:
            order_id: 订单号
            amount: 支付金额
            
        Returns:
            虚拟交易信息字典
        """
        import uuid
        
        now = datetime.utcnow()
        
        if self.test_generate_tx_hash:
            # 生成虚拟交易哈希
            tx_hash = f"TEST_TX_{uuid.uuid4().hex[:16].upper()}"
            block_number = 1000000 + hash(order_id) % 100000
        else:
            tx_hash = None
            block_number = None
        
        return {
            'tx_hash': tx_hash,
            'block_number': block_number,
            'amount': amount,
            'paid_at': now
        }
    
    async def activate_subscription(
        self,
        telegram_id: int,
        username: str,
        plan_id: int
    ) -> tuple[bool, str]:
        """
        激活订阅
        
        Returns:
            (success, message)
        """
        try:
            from ..models.database import get_db_session
            
            async with get_db_session() as db:
                try:
                    # 获取套餐信息
                    query = select(PricingPlan).where(PricingPlan.id == plan_id)
                    result = await db.execute(query)
                    plan = result.scalar_one_or_none()
                    
                    if not plan:
                        return False, "套餐不存在"
                    
                    # 检查是否已有活跃订阅
                    existing_query = select(Subscription).where(
                        and_(
                            Subscription.telegram_id == telegram_id,
                            Subscription.status == "active"
                        )
                    )
                    existing_result = await db.execute(existing_query)
                    existing_sub = existing_result.scalar_one_or_none()
                    
                    now = datetime.utcnow()
                    
                    if existing_sub:
                        # 续费：延长到期时间
                        if existing_sub.expire_date > now:
                            # 从当前到期时间开始延长
                            new_expire_date = existing_sub.expire_date + timedelta(days=plan.duration_days)
                        else:
                            # 已过期，从现在开始
                            new_expire_date = now + timedelta(days=plan.duration_days)
                        
                        existing_sub.plan_id = plan_id
                        existing_sub.plan_name = plan.name
                        existing_sub.expire_date = new_expire_date
                        existing_sub.updated_at = now
                        
                        subscription = existing_sub
                        action = "续费"
                    else:
                        # 新订阅
                        subscription = Subscription(
                            telegram_id=telegram_id,
                            username=username,
                            plan_id=plan_id,
                            plan_name=plan.name,
                            status="active",
                            start_date=now,
                            expire_date=now + timedelta(days=plan.duration_days),
                            auto_renew=False,
                            bots_created=0,
                            total_groups=0
                        )
                        db.add(subscription)
                        action = "开通"
                    
                    await db.commit()
                    
                    return True, f"订阅{action}成功！有效期至 {subscription.expire_date.strftime('%Y-%m-%d %H:%M:%S')}"
                    
                except Exception as e:
                    logger.error(f"Error activating subscription: {e}", exc_info=True)
                    await db.rollback()
                    return False, f"激活失败: {str(e)}"
        except Exception as e:
            logger.error(f"Error in activate_subscription: {e}", exc_info=True)
            return False, f"激活失败: {str(e)}"
    
    async def cleanup_expired_orders(self):
        """
        清理过期订单（定时任务调用）
        将超过30分钟未支付的订单标记为expired
        """
        try:
            async for db in get_db():
                try:
                    now = datetime.utcnow()
                    
                    # 查询所有pending且已过期的订单
                    query = select(PaymentOrder).where(
                        and_(
                            PaymentOrder.status == "pending",
                            PaymentOrder.expire_time < now
                        )
                    )
                    result = await db.execute(query)
                    expired_orders = result.scalars().all()
                    
                    count = 0
                    for order in expired_orders:
                        order.status = "expired"
                        count += 1
                    
                    if count > 0:
                        await db.commit()
                        logger.info(f"Cleaned up {count} expired orders")
                    
                except Exception as e:
                    logger.error(f"Error cleaning up expired orders: {e}", exc_info=True)
                    await db.rollback()
                finally:
                    break
        except Exception as e:
            logger.error(f"Error in cleanup_expired_orders: {e}", exc_info=True)


# 全局服务实例
usdt_service = USDTService()
