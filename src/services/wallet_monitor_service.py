"""
链上地址监听服务（Wallet Monitor Service）

职责：
1. 统一轮询所有监听地址（避免API限流）
2. 调用TronScan API查询TRC20交易
3. 检测新交易并生成通知
4. 防重复推送（通过tx_hash）

架构：
- 单后台任务统一扫描
- 5~10秒轮询间隔
- TronScan API（官方）
"""
import logging
import asyncio
import time
from datetime import datetime
from typing import List, Dict, Optional
from decimal import Decimal

import httpx
from telegram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WatchedAddress, TransactionNotification
from ..models.database import get_db_session
from config import config

logger = logging.getLogger(__name__)

# TronScan API 配置
TRONSCAN_API_BASE = "https://apilist.tronscanapi.com"
TRC20_TRANSFERS_ENDPOINT = "/api/token_trc20/transfers"
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"  # USDT TRC20 合约地址

# USDT 精度（6位小数）
USDT_DECIMALS = 6


class WalletMonitorService:
    """
    链上地址监听服务
    
    设计原则：
    - 统一轮询：一个后台任务扫描所有地址
    - 防重复：通过 tx_hash 去重
    - 多租户：通过 bot_id 隔离数据
    """
    
    def __init__(self):
        self.is_running = False
        self.monitor_task: Optional[asyncio.Task] = None
        self.poll_interval = 8  # 轮询间隔（秒）
        
        # API 配置
        self.api_key = getattr(config, 'TRONSCAN_API_KEY', '')
        self.http_client: Optional[httpx.AsyncClient] = None
        
        # Telegram Bot 实例（用于发送通知）
        self.bot: Optional[Bot] = None
    
    async def start(self, bot: Optional[Bot] = None):
        """
        启动监听服务
        
        Args:
            bot: Telegram Bot 实例（可选，用于发送通知）
        """
        if self.is_running:
            logger.warning("WalletMonitorService is already running")
            return
        
        self.is_running = True
        self.http_client = httpx.AsyncClient(timeout=10.0)
        
        # 保存 Bot 实例
        if bot:
            self.bot = bot
            logger.info(f"✅ WalletMonitorService started with Bot instance")
        else:
            logger.info("✅ WalletMonitorService started (no Bot instance for notifications)")
        
        self.monitor_task = asyncio.create_task(self._monitor_loop())
    
    async def stop(self):
        """停止监听服务"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        if self.http_client:
            await self.http_client.aclose()
        
        logger.info("🛑 WalletMonitorService stopped")
    
    async def _monitor_loop(self):
        """主监控循环 - 统一扫描所有地址"""
        while self.is_running:
            try:
                await self._scan_all_addresses()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}", exc_info=True)
                await asyncio.sleep(10)  # 出错后等待10秒
    
    async def _scan_all_addresses(self):
        """扫描所有启用的监听地址"""
        async with get_db_session() as db:
            # 获取所有启用的地址
            result = await db.execute(
                select(WatchedAddress).where(
                    WatchedAddress.enabled == True
                )
            )
            addresses = result.scalars().all()
        
        if not addresses:
            return
        
        logger.debug(f"Scanning {len(addresses)} watched addresses")
        
        # 批量处理：按 bot_id 分组
        bot_addresses: Dict[str, List[WatchedAddress]] = {}
        for addr in addresses:
            if addr.bot_id not in bot_addresses:
                bot_addresses[addr.bot_id] = []
            bot_addresses[addr.bot_id].append(addr)
        
        # 为每个 bot 处理其地址
        for bot_id, addr_list in bot_addresses.items():
            await self._process_addresses(bot_id, addr_list)
    
    async def _process_addresses(self, bot_id: str, addresses: List[WatchedAddress]):
        """处理一批地址的监听"""
        for address_info in addresses:
            try:
                # 查询 TRC20 USDT 交易
                if address_info.monitor_usdt:
                    await self._check_usdt_transfers(bot_id, address_info)
                
                # TODO: 查询 TRX 交易（如果需要）
                if address_info.monitor_trx:
                    # await self._check_trx_transfers(bot_id, address_info)
                    pass
                
                # 更新最后检查时间
                async with get_db_session() as db:
                    address_info.last_check_time = datetime.utcnow()
                    await db.merge(address_info)
                    await db.commit()
                
            except Exception as e:
                logger.error(f"Error processing address {address_info.address}: {e}")
    
    async def _check_usdt_transfers(self, bot_id: str, address_info: WatchedAddress):
        """检查 USDT TRC20 交易"""
        try:
            # 调用 TronScan API
            transfers = await self._fetch_trc20_transfers(address_info.address, USDT_CONTRACT)
            
            if not transfers:
                return
            
            # 倒序处理（最新的交易在前）
            for transfer in reversed(transfers):
                tx_hash = transfer.get('transaction_id')
                
                # 检查是否已通知
                if await self._is_notified(bot_id, tx_hash):
                    continue
                
                # 检查是否是最后一次处理的交易（首次运行时忽略历史交易）
                if address_info.last_tx_hash and tx_hash == address_info.last_tx_hash:
                    break
                
                # 提取交易信息
                amount = self._parse_usdt_amount(transfer)
                from_addr = transfer.get('from_address', '')
                to_addr = transfer.get('to_address', '')
                
                # 确定交易方向
                direction = 'IN' if to_addr.lower() == address_info.address.lower() else 'OUT'
                
                # 只通知入账（可选配置）
                if direction == 'IN':
                    # 保存通知记录
                    notification = await self._save_notification(
                        bot_id=bot_id,
                        tx_hash=tx_hash,
                        address=address_info.address,
                        amount=amount,
                        token_symbol='USDT',
                        from_address=from_addr,
                        to_address=to_addr,
                        watched_address_id=address_info.id,
                        group_id=address_info.group_id
                    )
                    
                    # 更新地址的最后处理交易
                    async with get_db_session() as db:
                        address_info.last_tx_hash = tx_hash
                        address_info.total_notifications += 1
                        await db.merge(address_info)
                        await db.commit()
                    
                    # 推送通知
                    await self._send_notification(
                        bot_id=bot_id,
                        address_info=address_info,
                        amount=amount,
                        from_address=from_addr,
                        tx_hash=tx_hash,
                        direction=direction
                    )
        
        except Exception as e:
            logger.error(f"Error checking USDT transfers for {address_info.address}: {e}")
    
    async def _fetch_trc20_transfers(self, address: str, contract: str, limit: int = 20) -> List[Dict]:
        """获取 TRC20 转账记录"""
        try:
            url = f"{TRONSCAN_API_BASE}{TRC20_TRANSFERS_ENDPOINT}"
            params = {
                'relatedAddress': address,
                'contract_address': contract,
                'limit': limit,
                'sort': '-timestamp'  # 按时间倒序
            }
            
            # 使用TronScan公共API，无需API Key
            response = await self.http_client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('data', [])
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # API Key 无效，静默跳过（避免日志污染）
                logger.debug(f"TronScan API 401 - API Key 未配置或无效")
            else:
                logger.error(f"Error fetching TRC20 transfers: HTTP {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error fetching TRC20 transfers: {e}")
            return []
    
    def _parse_usdt_amount(self, transfer: Dict) -> float:
        """解析 USDT 金额（考虑精度）"""
        raw_amount = transfer.get('quant', 0)
        # USDT 是 6 位精度
        amount = float(Decimal(str(raw_amount)) / Decimal(str(10 ** USDT_DECIMALS)))
        return amount
    
    async def _is_notified(self, bot_id: str, tx_hash: str) -> bool:
        """检查交易是否已通知"""
        async with get_db_session() as db:
            result = await db.execute(
                select(TransactionNotification).where(
                    TransactionNotification.bot_id == bot_id,
                    TransactionNotification.tx_hash == tx_hash
                )
            )
            return result.scalar_one_or_none() is not None
    
    async def _save_notification(self, **kwargs) -> TransactionNotification:
        """保存通知记录"""
        notification = TransactionNotification(**kwargs)
        
        async with get_db_session() as db:
            db.add(notification)
            await db.commit()
            await db.refresh(notification)
        
        return notification
    
    async def _send_notification(
        self,
        bot_id: str,
        address_info: WatchedAddress,
        amount: float,
        from_address: str,
        tx_hash: str,
        direction: str
    ):
        """发送 Telegram 通知"""
        try:
            # 检查是否有 Bot 实例
            if not self.bot:
                logger.warning("No Bot instance available for sending notification")
                return
            
            # 格式化金额
            amount_str = f"{amount:.2f}"
            
            # 构建消息
            message = (
                f"💸 <b>收到新的 USDT 转账</b>\n\n"
                f"🏦 <b>地址：</b>{address_info.alias or address_info.address}\n"
                f"💰 <b>金额：</b>{amount_str} USDT\n"
                f"👤 <b>来自：</b><code>{from_address[:8]}...{from_address[-6:]}</code>\n"
                f"🕒 <b>时间：</b>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"🔗 <b>TxHash：</b>\n<code>{tx_hash}</code>"
            )
            
            # 确定通知目标
            chat_id = address_info.user_id if address_info.group_id == 0 else address_info.group_id
            
            # 发送消息
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='HTML'
            )
            
            logger.info(f"✅ Notification sent to {chat_id}: {amount} USDT from {from_address}")
            
            # 更新统计
            async with get_db_session() as db:
                address_info.total_notifications += 1
                await db.merge(address_info)
                await db.commit()
        
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    async def add_watched_address(
        self,
        bot_id: str,
        user_id: int,
        group_id: int,
        address: str,
        alias: Optional[str] = None,
        monitor_usdt: bool = True,
        monitor_trx: bool = False
    ) -> WatchedAddress:
        """添加监听地址"""
        # 验证地址格式
        if not address.startswith('T') or len(address) < 30:
            raise ValueError("无效的TRON地址格式")
        
        # 检查是否已存在
        async with get_db_session() as db:
            result = await db.execute(
                select(WatchedAddress).where(
                    WatchedAddress.bot_id == bot_id,
                    WatchedAddress.user_id == user_id,
                    WatchedAddress.address == address
                )
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                raise ValueError("该地址已在监听列表中")
            
            # 创建新记录
            new_address = WatchedAddress(
                bot_id=bot_id,
                user_id=user_id,
                group_id=group_id,
                address=address,
                alias=alias,
                monitor_usdt=monitor_usdt,
                monitor_trx=monitor_trx
            )
            
            db.add(new_address)
            await db.commit()
            await db.refresh(new_address)
        
        return new_address
    
    async def remove_watched_address(self, bot_id: str, address_id: int, user_id: int = None) -> bool:
        """删除监听地址"""
        async with get_db_session() as db:
            query = select(WatchedAddress).where(
                WatchedAddress.bot_id == bot_id,
                WatchedAddress.id == address_id
            )

            if user_id is not None:
                query = query.where(WatchedAddress.user_id == user_id)

            result = await db.execute(query)
            address = result.scalar_one_or_none()
            
            if not address:
                return False
            
            await db.delete(address)
            await db.commit()
        
        return True
    
    async def get_watched_addresses(self, bot_id: str, user_id: int = None, group_id: int = None) -> List[WatchedAddress]:
        """获取监听地址列表"""
        async with get_db_session() as db:
            query = select(WatchedAddress).where(WatchedAddress.bot_id == bot_id)
            
            if user_id:
                query = query.where(WatchedAddress.user_id == user_id)
            if group_id:
                query = query.where(WatchedAddress.group_id == group_id)
            
            result = await db.execute(query.order_by(WatchedAddress.created_at.desc()))
            return result.scalars().all()


# 全局单例
wallet_monitor_service = WalletMonitorService()
