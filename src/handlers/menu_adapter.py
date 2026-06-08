"""
菜单系统适配层（Menu Adapter Layer）

职责：
1. 将旧 handler 适配到新架构（Runtime Router + Tenant Context）
2. 保留所有业务逻辑不变
3. 只修改入口和权限/上下文适配

采用方案 B：完整迁移适配策略
- 不改业务逻辑，只改入口和注册方式
- 逐步迁移 UI Schema，兼容 Capability/Config Center
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from ..services.tenant_context import TenantContext
from .menu_callbacks import (
    handle_usage_guide,
    handle_contact_support,
    handle_self_renew,
    handle_personal_center,
    handle_broadcast,
    handle_settings,
    # handle_broadcast_users,  # ✅ 已移除：改用 ui_schema_registry 中的新版本
    handle_runtime_stats,
    # ✅ 已移除：handle_broadcast_groups（改用 basic.handle_group_manage）
    # ⚠️ 已移除：handle_energy_trx 和 handle_usdt_monitor（功能废弃）
    # handle_energy_trx,
    # handle_usdt_monitor,
)
from .saas_purchase import handle_create_bot_click

logger = logging.getLogger(__name__)


# ============================================================================
# 适配函数定义
# ============================================================================

async def adapter_menu_usage_guide(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：使用说明
    
    旧 handler: handle_usage_guide(update, context)
    新签名: adapter_menu_usage_guide(update, context, tenant_context)
    """
    logger.info(f"[Adapter] Routing to usage guide for user {update.effective_user.id}")
    await handle_usage_guide(update, context)


async def adapter_saas_create_bot(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：创建续费（SaaS 自动售卖）
    
    统一入口：根据用户是否已创建 Bot 自动判断走创建流程还是续费流程
    """
    from .saas_purchase import handle_create_renew_entry
    logger.info(f"[Adapter] Routing to create/renew entry for user {update.effective_user.id}")
    await handle_create_renew_entry(update, context)


async def adapter_menu_contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：联系客服
    
    旧 handler: handle_contact_support(update, context)
    新签名: adapter_menu_contact_support(update, context, tenant_context)
    """
    logger.info(f"[Adapter] Routing to contact support for user {update.effective_user.id}")
    await handle_contact_support(update, context)


async def adapter_billing_self_renew(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：自助续费/创建机器人（统一入口）
    
    根据用户是否已创建 Bot 自动判断走创建流程还是续费流程
    """
    from .saas_purchase import handle_create_renew_entry
    
    user = update.effective_user
    logger.info(f"[Adapter] Routing to create/renew entry for user {user.id}")
    await handle_create_renew_entry(update, context)


async def adapter_menu_personal_center(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：个人中心

    旧 handler: handle_personal_center(update, context)
    新签名: adapter_menu_personal_center(update, context, tenant_context)

    注意：权限分层展示逻辑在旧 handler 内部实现
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    try:
        logger.info(f"[Adapter] Routing to personal center for user {update.effective_user.id}")
        await handle_personal_center(update, context)
    except Exception as e:
        logger.error(f"[adapter_menu_personal_center] Error: {e}", exc_info=True)
        # 异常兜底：返回友好提示
        error_text = "⚠️ 加载个人中心时出现错误，请稍后重试或联系客服。"
        try:
            if update.callback_query:
                await update.callback_query.answer(error_text, show_alert=True)
            elif update.message:
                await update.message.reply_text(error_text)
        except Exception as inner_e:
            logger.error(f"[adapter_menu_personal_center] Failed to send error message: {inner_e}")


async def adapter_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：群发广播
    
    旧 handler: handle_broadcast(update, context)
    新签名: adapter_broadcast_send(update, context, tenant_context)
    
    注意：权限检查已在旧 handler 中通过 PermissionChecker 完成
    """
    logger.info(f"[Adapter] Routing to broadcast send for user {update.effective_user.id}")
    await handle_broadcast(update, context)


async def adapter_group_manage(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：分组管理（使用 GroupTag 系统）
    
    旧 handler: handle_broadcast_groups(update, context)
    新 handler: handle_group_manage(update, context)
    
    注意：权限检查已在 handle_group_manage 中通过 PermissionChecker 完成
    """
    logger.info(f"[Adapter] Routing to group manage (GroupTag) for user {update.effective_user.id}")
    from .basic import handle_group_manage
    await handle_group_manage(update, context)


async def adapter_settings_main(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：功能设置
    
    旧 handler: handle_settings(update, context)
    新签名: adapter_settings_main(update, context, tenant_context)
    
    注意：权限检查已在旧 handler 中通过 PermissionChecker 完成
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    logger.info(f"[Adapter] Routing to settings main for user {update.effective_user.id}")
    try:
        await handle_settings(update, context)
    except Exception as e:
        logger.error(f"[adapter_settings_main] Error: {e}", exc_info=True)
        # 异常兜底：返回友好提示
        error_text = "⚠️ 加载功能设置菜单时出现错误，请稍后重试或联系客服。"
        try:
            if update.callback_query:
                await update.callback_query.answer(error_text, show_alert=True)
            elif update.message:
                await update.message.reply_text(error_text)
        except Exception as inner_e:
            logger.error(f"[adapter_settings_main] Failed to send error message: {inner_e}")


async def adapter_stats_runtime(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：运行统计
    
    旧 handler: handle_runtime_stats(update, context)
    新签名: adapter_stats_runtime(update, context, tenant_context)
    
    注意：仅超级管理员、Bot创建者、管理员可用
    """
    logger.info(f"[Adapter] Routing to runtime stats for user {update.effective_user.id}")
    await handle_runtime_stats(update, context)


async def adapter_energy_trx(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：能量 TRX
    
    显示能量兑换功能说明
    """
    logger.info(f"[Adapter] Routing to energy TRX for user {update.effective_user.id}")
    await update.message.reply_text(
        "⚡ <b>能量TRX兑换</b>\n\n"
        "💡 功能说明：\n"
        "• 提供TRX能量兑换服务\n"
        "• 支持多种兑换方式\n"
        "• 自动到账，无需等待\n\n"
        "🔧 此功能正在开发中，敬请期待！",
        parse_mode='HTML'
    )


async def adapter_usdt_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE, tenant_context: TenantContext):
    """
    适配：USDT 监听 - 调用新版功能
    """
    from ..handlers.usdt_monitor import handle_usdt_monitor

    logger.info(f"[Adapter] Routing to USDT monitor (new version) for user {update.effective_user.id}")

    await handle_usdt_monitor(update, context, tenant_context)


# ============================================================================
# 路由注册表（用于批量注册到 Runtime Router）
# ============================================================================

MENU_ADAPTER_ROUTES = {
    # 菜单模块
    'v1:menu:usage_guide': adapter_menu_usage_guide,
    'v1:menu:contact_support': adapter_menu_contact_support,
    'v1:menu:personal_center': adapter_menu_personal_center,
    
    # SaaS 模块
    'v1:saas:create_bot': adapter_saas_create_bot,
    
    # 账单模块
    'v1:billing:self_renew': adapter_billing_self_renew,
    
    # 群组模块
    'v1:group:manage': adapter_group_manage,
    
    # 广播模块
    'v1:broadcast:send': adapter_broadcast_send,
    # 广播模块
    # 'v1:broadcast:users': adapter_broadcast_users,  # ✅ 已移除：改用 ui_schema_registry 中的新版本
    
    # 设置模块
    'v1:settings:main': adapter_settings_main,
    
    # 统计模块
    'v1:stats:runtime': adapter_stats_runtime,  # 🆕 运行统计
    
    # 能量和USDT模块
    'v1:energy:trx': adapter_energy_trx,
    'v1:usdt:monitor': adapter_usdt_monitor,
}


def register_menu_adapters(runtime_router):
    """
    将菜单适配函数作为缺失路由的后备注册到 Runtime Router。

    UI Schema 注册器是新版菜单的主入口；适配层只补充尚未迁移的路由，
    避免后注册的旧 handler 静默覆盖新版内联页面。
    
    Args:
        runtime_router: RuntimeRouter 实例
    """
    for route_name, handler in MENU_ADAPTER_ROUTES.items():
        if route_name in runtime_router.routes:
            logger.info(f"Skipped menu adapter route already registered by UI schema: {route_name}")
            continue

        runtime_router.register_route(route_name, handler)
        logger.info(f"Registered menu adapter route: {route_name}")
