"""
账单操作处理器包

将原billing.py拆分为多个模块，提高可维护性：
- deposit: 入款相关（handle_deposit, revoke_deposit）
- withdraw: 下发相关（handle_withdraw, revoke_withdraw）
- storage: 寄存相关（handle_storage）
- query: 查询相关（show_bills, show_my_bills）
- revoke: 撤销相关（revoke_by_reply）
- management: 管理相关（delete_bills, save_bills）
"""
from .deposit import handle_deposit as _handle_deposit, revoke_deposit, get_day_cut_period
from .withdraw import handle_withdraw as _handle_withdraw, revoke_withdraw
from .storage import handle_storage
from .query import show_bills, show_my_bills
from .revoke import revoke_by_reply
from .management import delete_bills, save_bills, confirm_delete_bills_callback, cancel_delete_bills_callback
from .debug import current_traceback, get_effective_accounting_bot_id, log_accounting_debug, log_accounting_trace


async def handle_deposit(update, context):
    try:
        return await _handle_deposit(update, context)
    except Exception:
        raw_bot_id = None
        effective_bot_id = None
        try:
            from ...utils.bot_id_middleware import get_current_bot_id
            raw_bot_id = get_current_bot_id(context)
            effective_bot_id = get_effective_accounting_bot_id(context, raw_bot_id)
        except Exception:
            pass
        log_accounting_debug(
            update=update,
            context=context,
            handler="billing.handle_deposit.exception",
            bot_id=effective_bot_id,
            error_traceback=current_traceback(),
        )
        log_accounting_trace(
            update=update,
            context=context,
            handler="billing.handle_deposit.exception",
            bot_id=raw_bot_id,
            effective_bot_id=effective_bot_id,
            tenant_query_bot_id=effective_bot_id,
            error_traceback=current_traceback(),
        )
        raise


async def handle_withdraw(update, context):
    try:
        return await _handle_withdraw(update, context)
    except Exception:
        raw_bot_id = None
        effective_bot_id = None
        try:
            from ...utils.bot_id_middleware import get_current_bot_id
            raw_bot_id = get_current_bot_id(context)
            effective_bot_id = get_effective_accounting_bot_id(context, raw_bot_id)
        except Exception:
            pass
        log_accounting_debug(
            update=update,
            context=context,
            handler="billing.handle_withdraw.exception",
            bot_id=effective_bot_id,
            error_traceback=current_traceback(),
        )
        log_accounting_trace(
            update=update,
            context=context,
            handler="billing.handle_withdraw.exception",
            bot_id=raw_bot_id,
            effective_bot_id=effective_bot_id,
            tenant_query_bot_id=effective_bot_id,
            error_traceback=current_traceback(),
        )
        raise

__all__ = [
    # 入款
    'handle_deposit',
    'revoke_deposit',
    # 下发
    'handle_withdraw',
    'revoke_withdraw',
    # 寄存
    'handle_storage',
    # 查询
    'show_bills',
    'show_my_bills',
    # 撤销
    'revoke_by_reply',
    # 管理
    'delete_bills',
    'save_bills',
    'confirm_delete_bills_callback',
    'cancel_delete_bills_callback',
    # 辅助函数
    'get_day_cut_period',
]
