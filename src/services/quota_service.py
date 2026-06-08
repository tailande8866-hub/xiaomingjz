"""
额度管理服务 - 监控群组净入账金额并发送预警

职责：
1. 设置和管理群组额度配置
2. 计算当前净入账金额
3. 检查是否达到预警阈值（90%、100%）
4. 发送预警消息
"""
import logging
from telegram.ext import ContextTypes

from ..repositories.group_quota_repo import GroupQuotaRepo
from ..models import get_db_session

logger = logging.getLogger(__name__)


class QuotaService:
    """额度管理服务"""
    
    async def set_quota(
        self,
        group_id: int,
        bot_id: str,
        amount: float,
        currency: str = "USDT"
    ) -> tuple[bool, str]:
        """
        设置群组额度
        
        Args:
            group_id: 群组ID
            bot_id: Bot实例ID
            amount: 额度上限
            currency: 币种（USDT/CNY）
            
        Returns:
            (是否成功, 消息文本)
        """
        async with get_db_session() as db:
            quota_repo = GroupQuotaRepo(db, bot_id)
            
            try:
                await quota_repo.create_or_update(
                    group_id=group_id,
                    quota_limit=amount,
                    quota_currency=currency
                )
                await db.commit()
                
                message = (
                    f"✅ 额度设置成功\n\n"
                    f"群组ID: {group_id}\n"
                    f"额度上限: {amount} {currency}\n"
                    f"状态: 已启用\n\n"
                    f"💡 当净入账（入款-下发）接近或超过额度时，系统会发送预警提示。"
                )
                
                logger.info(f"[BOT:{bot_id}] Quota set for group {group_id}: {amount} {currency}")
                return True, message
                
            except Exception as e:
                logger.error(f"[BOT:{bot_id}] Failed to set quota: {e}", exc_info=True)
                await db.rollback()
                return False, f"❌ 设置失败: {str(e)}"
    
    async def disable_quota(
        self,
        group_id: int,
        bot_id: str
    ) -> tuple[bool, str]:
        """
        禁用群组额度监控
        
        Args:
            group_id: 群组ID
            bot_id: Bot实例ID
            
        Returns:
            (是否成功, 消息文本)
        """
        async with get_db_session() as db:
            quota_repo = GroupQuotaRepo(db, bot_id)
            
            success = await quota_repo.disable_quota(group_id)
            
            if success:
                await db.commit()
                message = f"✅ 已关闭群组 {group_id} 的额度监控"
                logger.info(f"[BOT:{bot_id}] Quota disabled for group {group_id}")
                return True, message
            else:
                message = f"❌ 未找到群组 {group_id} 的额度配置"
                return False, message
    
    async def check_and_warn_quota(
        self,
        db,
        group_id: int,
        bot_id: str,
        new_amount: float,
        currency: str,
        transaction_type: str,
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        检查额度并发送预警（状态机模式）
        
        🆕 架构优化：使用外部传入的 db 会话，避免 SQLite 读取隔离问题
        - 必须在 Transaction commit 之后调用
        - 基于同一个会话查询最新数据
        
        Args:
            db: 数据库会话（从外部传入，必须在 commit 之后）
            group_id: 群组ID
            bot_id: Bot实例ID
            new_amount: 本次交易金额
            currency: 交易币种
            transaction_type: 交易类型（deposit/withdraw）
            context: Telegram Context
                
        Returns:
            是否超额（True=超额，False=正常）
        """
        # ✅ 使用外部传入的 db 会话（已在 commit 之后）
        quota_repo = GroupQuotaRepo(db, bot_id)
            
        # 1. 获取额度配置
        quota = await quota_repo.get_by_group_id(group_id)
            
        if not quota or not quota.quota_enabled:
            # 未配置或未启用，直接返回
            return False
            
        # 2. 如果币种不匹配，需要换算（简化处理：假设都是同一币种）
        # TODO: 如果需要支持多币种，这里添加汇率换算逻辑
            
        # 3. 获取当前净入账（查询最新数据）
        usage = await quota_repo.get_quota_usage(group_id)
        current_net = usage['net_amount']
            
        logger.info(
            f"[BOT:{bot_id}] Quota check: group={group_id}, "
            f"type={transaction_type}, amount={new_amount}, "
            f"current_net={current_net}, "
            f"deposit_total={usage['deposit_total']}, "
            f"withdraw_total={usage['withdraw_total']}"
        )
            
        # 4. 基于当前数据计算新的净额
        if transaction_type == 'deposit':
            new_net = current_net + new_amount
        elif transaction_type == 'withdraw':
            new_net = current_net - new_amount
        else:
            new_net = current_net
            
        # 5. 计算使用百分比
        quota_limit = quota.quota_limit
        usage_percent = (new_net / quota_limit * 100) if quota_limit > 0 else 0
            
        #  6. 状态机逻辑：每次重新计算状态，允许回退
        warned_any = False
            
        # ✅ 情况1：使用率 >= 100% → 超额状态（每次都提醒）
        if usage_percent >= 100:
            await self._send_warning_message(
                context=context,
                chat_id=group_id,
                quota_limit=quota_limit,
                current_net=new_net,
                usage_percent=usage_percent,
                threshold=100,
                currency=quota.quota_currency
            )
                
            # 更新标志（保持为 True，因为仍在超额状态）
            quota.warning_threshold_100 = True
            quota.warning_threshold_90 = True  # 同时也标记 90%
            warned_any = True
            logger.info(f"[BOT:{bot_id}] Group {group_id} is OVER LIMIT ({usage_percent:.1f}%)")
            
        # ✅ 情况2：90% <= 使用率 < 100% → 预警状态
        elif usage_percent >= 90:
            # 只有从 NORMAL 进入 WARNING 时才发送提醒
            if not quota.warning_threshold_90:
                await self._send_warning_message(
                    context=context,
                    chat_id=group_id,
                    quota_limit=quota_limit,
                    current_net=new_net,
                    usage_percent=usage_percent,
                    threshold=90,
                    currency=quota.quota_currency
                )
                warned_any = True
                
            # 更新标志
            quota.warning_threshold_90 = True
            quota.warning_threshold_100 = False  # 重置 100% 标志
            logger.info(f"[BOT:{bot_id}] Group {group_id} is in WARNING state ({usage_percent:.1f}%)")
            
        # ✅ 情况3：使用率 < 90% → 正常状态（重置所有标志）
        else:
            # 如果之前处于预警或超额状态，现在恢复正常
            if quota.warning_threshold_90 or quota.warning_threshold_100:
                logger.info(
                    f"[BOT:{bot_id}] Group {group_id} returned to NORMAL state "
                    f"(was {quota.warning_threshold_90}/{quota.warning_threshold_100}, now {usage_percent:.1f}%)"
                )
                
            # 重置所有预警标志，允许下次再次触发
            quota.warning_threshold_90 = False
            quota.warning_threshold_100 = False
            
        # 7. 提交数据库更改（更新预警标志）
        if warned_any or quota.warning_threshold_90 == False:
            await db.commit()
            
        # 8. 返回是否超额
        return usage_percent >= 100
    
    async def _send_warning_message(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        quota_limit: float,
        current_net: float,
        usage_percent: float,
        threshold: int,
        currency: str
    ):
        """
        发送预警消息
        
        Args:
            context: Telegram Context
            chat_id: 群组ID
            quota_limit: 额度上限
            current_net: 当前净入账
            usage_percent: 使用百分比
            threshold: 预警阈值（90或100）
            currency: 币种
        """
        if threshold == 90:
            emoji = "⚠️"
            title = "额度预警"
            description = f"当前净入账已达到额度的 {usage_percent:.1f}%，请注意控制！"
        else:  # 100%
            emoji = "🚨"
            title = "额度已超额"
            description = f"当前净入账已超过额度上限！\n但仍可继续记账，请尽快处理。"
        
        message = (
            f"{emoji} <b>{title}</b>\n\n"
            f"额度上限: {quota_limit:.2f} {currency}\n"
            f"当前净入账: {current_net:.2f} {currency}\n"
            f"使用率: {usage_percent:.1f}%\n\n"
            f"{description}\n\n"
            f"💡 净入账 = 入款总额 - 下发总额\n"
            f"💡 如需调整额度，请联系管理员使用「设置额度」命令"
        )
        
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info(f"Sent {threshold}% warning to group {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send warning message: {e}")


# 全局实例
quota_service = QuotaService()
