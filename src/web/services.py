"""
Web 业务逻辑层
"""
from datetime import datetime, timedelta
from typing import Dict, List
from src.models.transaction import Transaction
from src.services.billing_service import BillingService
from src.utils.formatter import Formatter
from src.repositories.group_repo import GroupRepo
import pandas as pd
import asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from config.enhanced_config import config_manager


class BillService:
    """账单服务"""
    
    def __init__(self, bot_id: str, chat_id: int):
        self.bot_id = bot_id
        self.chat_id = chat_id
    
    def _get_db_session(self):
        """获取数据库会话"""
        from src.core.database import get_async_engine
        engine = get_async_engine()
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return session_factory()
    
    async def get_today_bill(self) -> Dict:
        """获取今日账单"""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now()
        
        db = self._get_db_session()
        try:
            # 查询今日交易
            deposits = await BillingService.get_transactions(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id,
                transaction_type='deposit',
                start_date=today_start,
                end_date=today_end,
                limit=100
            )
            
            withdraws = await BillingService.get_transactions(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id,
                transaction_type='withdraw',
                start_date=today_start,
                end_date=today_end,
                limit=100
            )
            
            # 计算汇总
            summary = await BillingService.calculate_summary(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id
            )
            
            return {
                'deposits': [self._format_transaction(t) for t in deposits],
                'withdraws': [self._format_transaction(t) for t in withdraws],
                'summary': summary,
                'date': today_start.strftime('%Y-%m-%d')
            }
        finally:
            await db.close()
    
    async def get_history_bill(self, days: int = 7) -> Dict:
        """获取历史账单"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        db = self._get_db_session()
        try:
            deposits = await BillingService.get_transactions(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id,
                transaction_type='deposit',
                start_date=start_date,
                end_date=end_date,
                limit=500
            )
            
            withdraws = await BillingService.get_transactions(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id,
                transaction_type='withdraw',
                start_date=start_date,
                end_date=end_date,
                limit=500
            )
            
            summary = await BillingService.calculate_summary(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id
            )
            
            # 按日期分组
            daily_data = self._group_by_date(deposits, withdraws, days)
            
            return {
                'daily_data': daily_data,
                'summary': summary,
                'period': f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"
            }
        finally:
            await db.close()
    
    async def get_bill_detail(self, page: int = 1, page_size: int = 50) -> Dict:
        """获取明细流水（分页）"""
        offset = (page - 1) * page_size
        
        db = self._get_db_session()
        try:
            transactions = await BillingService.get_transactions(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id,
                limit=page_size
            )
            
            # 获取总数
            from src.repositories.transaction_repo import TransactionRepo
            tx_repo = TransactionRepo(db, self.bot_id)
            total = await tx_repo.count_by_group(self.chat_id)
            
            return {
                'transactions': [self._format_transaction(t) for t in transactions],
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total': total,
                    'total_pages': (total + page_size - 1) // page_size
                }
            }
        finally:
            await db.close()
    
    async def get_stats_summary(self, days: int = 30) -> Dict:
        """获取统计汇总"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        db = self._get_db_session()
        try:
            deposits = await BillingService.get_transactions(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id,
                transaction_type='deposit',
                start_date=start_date,
                end_date=end_date,
                limit=1000
            )
            
            withdraws = await BillingService.get_transactions(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id,
                transaction_type='withdraw',
                start_date=start_date,
                end_date=end_date,
                limit=1000
            )
            
            summary = await BillingService.calculate_summary(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id
            )
            
            # 趋势数据
            trend_data = self._calculate_trend(deposits, withdraws, days)
            
            # 用户排行
            user_ranking = self._calculate_user_ranking(deposits, withdraws)
            
            return {
                'summary': summary,
                'trend': trend_data,
                'user_ranking': user_ranking,
                'period': f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"
            }
        finally:
            await db.close()
    
    async def export_to_excel(self, days: int = 30) -> pd.DataFrame:
        """导出 Excel"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        db = self._get_db_session()
        try:
            transactions = await BillingService.get_transactions(
                db=db,
                bot_id=self.bot_id,
                group_id=self.chat_id,
                start_date=start_date,
                end_date=end_date,
                limit=5000
            )
            
            # 转换为 DataFrame
            data = []
            for t in transactions:
                data.append({
                    '时间': t.transaction_date.strftime('%Y-%m-%d %H:%M:%S'),
                    '类型': '入款' if t.amount > 0 else '下发',
                    '金额': abs(t.amount),
                    '币种': t.currency or 'USDT',
                    '操作人': t.user_name or t.user_id,
                    '备注': t.remark or '',
                    '消息链接': self._generate_message_link(t)
                })
            
            return pd.DataFrame(data)
        finally:
            await db.close()
    
    def _format_transaction(self, transaction) -> Dict:
        """格式化单笔交易"""
        return {
            'id': transaction.id,
            'time': transaction.transaction_date.strftime('%H:%M'),
            'amount': transaction.amount,
            'currency': transaction.currency or 'USDT',
            'user_name': transaction.user_name or transaction.user_id,
            'user_id': transaction.user_id,
            'remark': transaction.remark or '',
            'message_link': self._generate_message_link(transaction),
            'exchange_rate': transaction.exchange_rate,
            'fee_rate': transaction.fee_rate
        }
    
    def _generate_message_link(self, transaction) -> str:
        """生成消息链接"""
        if transaction.message_id and self.chat_id:
            # 处理超级群组 ID
            chat_id_str = str(self.chat_id)
            if chat_id_str.startswith('-100'):
                display_id = chat_id_str[4:]
            else:
                display_id = chat_id_str
            
            return f"https://t.me/c/{display_id}/{transaction.message_id}"
        return ''
    
    def _group_by_date(self, deposits, withdraws, days: int) -> List[Dict]:
        """按日期分组"""
        # TODO: 实现按日期分组逻辑
        return []
    
    def _calculate_trend(self, deposits, withdraws, days: int) -> List[Dict]:
        """计算趋势数据"""
        # TODO: 实现趋势计算逻辑
        return []
    
    def _calculate_user_ranking(self, deposits, withdraws) -> List[Dict]:
        """计算用户排行"""
        # TODO: 实现用户排行逻辑
        return []
