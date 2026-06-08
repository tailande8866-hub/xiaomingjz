"""
机器人状态管理面板 Handler
处理机器人状态显示、删除、重启、断开、重置Token、转移所属权等功能
"""
import logging
import html
import traceback
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_

from ..models import Admin, get_db_session
from ..models.saas_auto import BotCreation
from ..repositories.bot_management_repo import (
    BotManagementRepository, BotAdminRepository, BotOperationLogRepository
)
from ..utils.bot_id_middleware import get_current_bot_id
from ..utils.state_manager import clear_state
from ..utils.token_encryptor import token_encryptor

logger = logging.getLogger(__name__)

# 固定超级管理员ID
FIXED_SUPER_ADMIN_ID = 7862093562

# Callback 前缀
BOT_MGMT_PREFIX = "bot_mgmt"
BOT_SETTINGS = f"{BOT_MGMT_PREFIX}:settings"
BOT_DELETE = f"{BOT_MGMT_PREFIX}:delete"
BOT_DELETE_CONFIRM = f"{BOT_MGMT_PREFIX}:delete:confirm"
BOT_RESTART = f"{BOT_MGMT_PREFIX}:restart"
BOT_DISCONNECT = f"{BOT_MGMT_PREFIX}:disconnect"
BOT_DISCONNECT_CONFIRM = f"{BOT_MGMT_PREFIX}:disconnect:confirm"
BOT_RESET_TOKEN = f"{BOT_MGMT_PREFIX}:reset_token"
BOT_TRANSFER = f"{BOT_MGMT_PREFIX}:transfer"
BOT_TRANSFER_SELECT = f"{BOT_MGMT_PREFIX}:transfer:select"
BOT_TRANSFER_CONFIRM = f"{BOT_MGMT_PREFIX}:transfer:confirm"
BOT_BACK = f"{BOT_MGMT_PREFIX}:back"
BOT_MANAGE_SCENES = {"created_success", "renewed_success"}


def _is_bot_owner_or_super_admin(user_id: int, bot_creation: BotCreation) -> bool:
    """检查用户是否是Bot所有者或超级管理员"""
    if user_id == FIXED_SUPER_ADMIN_ID:
        return True
    if bot_creation and int(getattr(bot_creation, "telegram_id", 0) or 0) == int(user_id):
        return True
    return False


def _normalize_scene(scene: str | None) -> str:
    if scene in BOT_MANAGE_SCENES:
        return scene
    return "created_success"


def _mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 10:
        return "***"
    return f"{token[:4]}***{token[-4:]}"


def _build_bot_manage_callback(action: str, bot_id: str, scene: str, extra: list[str] | None = None) -> str:
    parts = [BOT_MGMT_PREFIX] + action.split(":") + [bot_id, _normalize_scene(scene)]
    if extra:
        parts.extend([str(item) for item in extra])
    return ":".join(parts)


def _parse_bot_manage_callback(callback_data: str, fallback_bot_id: str) -> dict:
    scene = "created_success"
    action = ""
    bot_id = fallback_bot_id
    admin_user_id = None
    page = 1

    if callback_data.startswith(f"{BOT_TRANSFER_CONFIRM}:"):
        parts = callback_data.split(":")
        if len(parts) >= 6:
            action = "transfer:confirm"
            bot_id = parts[3]
            scene = parts[4]
            admin_user_id = int(parts[5]) if parts[5].isdigit() else None
    elif callback_data.startswith(f"{BOT_TRANSFER_SELECT}:"):
        parts = callback_data.split(":")
        if len(parts) >= 6:
            action = "transfer:select"
            bot_id = parts[3]
            scene = parts[4]
            admin_user_id = int(parts[5]) if parts[5].isdigit() else None
            if len(parts) >= 7 and parts[6].isdigit():
                page = int(parts[6])
    elif callback_data.startswith(f"{BOT_DELETE_CONFIRM}:"):
        parts = callback_data.split(":")
        action = "delete:confirm"
        if len(parts) >= 5:
            bot_id = parts[3]
            scene = parts[4]
    elif callback_data.startswith(f"{BOT_DISCONNECT_CONFIRM}:"):
        parts = callback_data.split(":")
        action = "disconnect:confirm"
        if len(parts) >= 5:
            bot_id = parts[3]
            scene = parts[4]
    else:
        parts = callback_data.split(":")
        if len(parts) >= 2 and parts[0] == BOT_MGMT_PREFIX:
            action = parts[1]
            if len(parts) >= 4:
                bot_id = parts[2]
                scene = parts[3]
                if action == "transfer" and len(parts) >= 5 and parts[4].isdigit():
                    page = int(parts[4])

    return {
        "action": action,
        "bot_id": bot_id,
        "scene": _normalize_scene(scene),
        "admin_user_id": admin_user_id,
        "page": page,
    }


def render_bot_manage_buttons(bot_id: str, user_id: int, scene: str) -> InlineKeyboardMarkup:
    scene = _normalize_scene(scene)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ 更多设置", callback_data=_build_bot_manage_callback("settings", bot_id, scene)),
            InlineKeyboardButton("🗑️ 删除机器人", callback_data=_build_bot_manage_callback("delete", bot_id, scene)),
        ],
        [
            InlineKeyboardButton("🔄 重启机器人", callback_data=_build_bot_manage_callback("restart", bot_id, scene)),
            InlineKeyboardButton("➖ 断开机器人", callback_data=_build_bot_manage_callback("disconnect", bot_id, scene)),
        ],
        [
            InlineKeyboardButton("🔐 重置令牌(token)", callback_data=_build_bot_manage_callback("reset_token", bot_id, scene)),
            InlineKeyboardButton("➡️📱 转移所属权", callback_data=_build_bot_manage_callback("transfer", bot_id, scene)),
        ],
        [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_id, scene))],
    ])


def _build_bot_manage_scene_text(bot_creation: BotCreation, scene: str) -> str:
    expire_time = getattr(bot_creation, "expire_time", None)
    expire_text = expire_time.strftime("%Y-%m-%d %H:%M") if expire_time else "永久"
    if _normalize_scene(scene) == "renewed_success":
        return (
            "✅ <b>续费成功啦！🎉</b>\n\n"
            "你的专属记账Bot服务时长已更新\n"
            f"订阅续费成功！有效期至 {expire_text}\n\n"
            "可以继续安心使用所有功能咯~"
        )
    run_status = _format_run_status(getattr(bot_creation, "status", None))
    token_status = _format_token_status(getattr(bot_creation, "token_status", None))
    return (
        "🥳 你的专属记账小机器人诞生啦！\n\n"
        f"🤖 机器人名称：{html.escape(bot_creation.bot_name or bot_creation.bot_username or bot_creation.instance_id)}\n"
        f"👤 用户名：@{html.escape(bot_creation.bot_username or 'unknown')}\n"
        f"📅 到期时间：{expire_text}\n"
        "📦 当前版本：全功能版\n\n"
        "头像、名称都可以自由设置\n"
        "群组记账、数据管理全都归你掌控\n"
        "快去体验吧~\n\n"
        "🤖 机器人状态\n\n"
        f"运行状态：{run_status}\n"
        f"Token状态：{token_status}"
    )


async def _show_bot_manage_scene_message(query, bot_creation: BotCreation, user_id: int, scene: str):
    await query.edit_message_text(
        _build_bot_manage_scene_text(bot_creation, scene),
        reply_markup=render_bot_manage_buttons(bot_creation.instance_id, user_id, scene),
        parse_mode="HTML",
    )


def _format_run_status(status: str) -> str:
    """格式化运行状态显示"""
    status_map = {
        "running": "✅ 正常运行",
        "stopped": "❌ 未运行",
        "failed": "⚠️ 启动失败",
        "restarting": "🔄 重启中",
        "disconnected": "➖ 已断开",
        "creating": "🔄 创建中",
        "error": "⚠️ 异常",
    }
    return status_map.get(status, f"❓ {status}")


def _format_token_status(status: str) -> str:
    """格式化Token状态显示"""
    status_map = {
        "normal": "✅ 有效",
        "invalid": "❌ 无效",
        "checking": "🔄 检测中",
        "error": "⚠️ 检测失败",
        "disabled": "➖ 已停用",
    }
    return status_map.get(status, f"❓ {status}")


async def show_bot_status_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    显示机器人状态管理面板
    从个人中心按钮调用
    """
    query = update.callback_query
    message = update.message
    user = update.effective_user

    if not user:
        if query:
            await query.answer("无法获取用户信息", show_alert=True)
        return

    user_id = user.id
    bot_id = get_current_bot_id(context)

    try:
        async with get_db_session() as db:
            # 获取Bot信息
            repo = BotManagementRepository(db)
            bot_creation = await repo.get_bot_creation(bot_id)

            if not bot_creation:
                if query:
                    await query.answer("未找到机器人信息", show_alert=True)
                elif message:
                    await message.reply_text("未找到机器人信息")
                return

            # 权限检查
            if not _is_bot_owner_or_super_admin(user_id, bot_creation):
                if query:
                    await query.answer("无权限访问", show_alert=True)
                elif message:
                    await message.reply_text("⚠️ 无权限访问")
                return

            # 构建状态显示
            run_status = _format_run_status(bot_creation.status)
            token_status = _format_token_status(bot_creation.token_status)

            text = (
                f"🤖 机器人状态\n"
                f"运行状态：{run_status}\n"
                f"Token状态：{token_status}"
            )

            reply_markup = render_bot_manage_buttons(bot_creation.instance_id, user_id, "created_success")

            if query:
                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            elif message:
                await message.reply_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )

    except Exception as e:
        logger.error(f"[BOT_MGMT] Show panel error: {e}", exc_info=True)
        logger.error(f"[BOT_MGMT] Traceback: {traceback.format_exc()}")
        if query:
            await query.answer("加载机器人状态失败", show_alert=True)
        elif message:
            await message.reply_text("⚠️ 加载机器人状态失败")


async def handle_bot_management_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理机器人管理面板的所有回调"""
    query = update.callback_query
    if not query:
        return

    user = update.effective_user
    if not user:
        await query.answer("无法获取用户信息", show_alert=True)
        return

    user_id = user.id
    callback_data = query.data
    callback_meta = _parse_bot_manage_callback(callback_data, get_current_bot_id(context))
    target_bot_id = callback_meta["bot_id"]
    scene = callback_meta["scene"]
    action = callback_meta["action"]

    try:
        async with get_db_session() as db:
            repo = BotManagementRepository(db)
            bot_creation = await repo.get_bot_creation(target_bot_id)

            if not bot_creation:
                print(
                    f"[BOT_MANAGE_CALLBACK] callback_data={callback_data} user_id={user_id} "
                    f"bot_id={target_bot_id} scene={scene} action={action} "
                    f"handler=handle_bot_management_callback permission_pass=False"
                )
                await query.edit_message_text("未找到机器人信息")
                return

            permission_pass = _is_bot_owner_or_super_admin(user_id, bot_creation)
            print(
                f"[BOT_MANAGE_CALLBACK] callback_data={callback_data} user_id={user_id} "
                f"bot_id={target_bot_id} scene={scene} action={action} "
                f"handler=handle_bot_management_callback permission_pass={permission_pass}"
            )

            if not permission_pass:
                await query.answer("无权限访问", show_alert=True)
                return

            if action == "settings":
                await _handle_settings(update, context, db, bot_creation, target_bot_id, scene)
            elif action == "delete":
                await _handle_delete_confirm(update, context, target_bot_id, scene)
            elif action == "delete:confirm":
                await _handle_delete(update, context, db, bot_creation, user_id, scene)
            elif action == "restart":
                await _handle_restart(update, context, db, bot_creation, user_id, scene)
            elif action == "disconnect":
                await _handle_disconnect_confirm(update, context, target_bot_id, scene)
            elif action == "disconnect:confirm":
                await _handle_disconnect(update, context, db, bot_creation, user_id, scene)
            elif action == "reset_token":
                await _handle_reset_token_start(update, context, target_bot_id, scene)
            elif action == "transfer":
                await _handle_transfer_start(update, context, db, target_bot_id, scene, callback_meta["page"])
            elif action == "transfer:select":
                await _handle_transfer_select(update, context, db, target_bot_id, scene, callback_meta["admin_user_id"], callback_meta["page"])
            elif action == "transfer:confirm":
                await _handle_transfer_confirm(update, context, db, target_bot_id, scene, callback_meta["admin_user_id"], user_id)
            elif action == "back":
                clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")
                context.user_data.pop("transfer_new_owner_id", None)
                context.user_data.pop("transfer_old_owner_id", None)
                await _show_bot_manage_scene_message(query, bot_creation, user_id, scene)
            else:
                await query.edit_message_text("未知操作")

    except Exception as e:
        logger.error(f"[BOT_MGMT] Callback error: {e}", exc_info=True)
        logger.error(f"[BOT_MGMT] Traceback: {traceback.format_exc()}")
        await query.edit_message_text("⚠️ 处理请求时出现错误，请稍后重试")


async def _handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE, db, bot_creation, target_bot_id: str, scene: str):
    """处理更多设置 - 跳转到功能设置"""
    clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")
    context.user_data["_bot_id_override"] = target_bot_id

    from .menu_callbacks import handle_settings
    await handle_settings(update, context)


async def _handle_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str, scene: str):
    """显示删除确认页"""
    query = update.callback_query

    text = (
        "⚠️ <b>确认删除BOT？</b>\n\n"
        "删除后：\n"
        "• BOT 将停止运行\n"
        "• Token 将解除绑定\n"
        "• 到期时间保留\n"
        "• 历史账单数据保留\n"
        "• 群组数据保留"
    )

    keyboard = [
        [InlineKeyboardButton("✅ 确认删除", callback_data=_build_bot_manage_callback("delete:confirm", bot_id, scene))],
        [InlineKeyboardButton("❌ 取消", callback_data=_build_bot_manage_callback("back", bot_id, scene))]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def _handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, db, bot_creation, user_id, scene: str):
    """执行删除（停用）机器人"""
    query = update.callback_query
    repo = BotManagementRepository(db)
    log_repo = BotOperationLogRepository(db)

    try:
        # 1. 停止Bot实例
        await _stop_bot_instance(bot_creation.instance_id)

        # 2. 更新数据库状态
        success = await repo.disable_bot(bot_creation.instance_id)

        if success:
            # 3. 写入操作日志
            await log_repo.create_log(
                bot_id=bot_creation.instance_id,
                operator_user_id=user_id,
                action="delete",
                status="success",
                message="机器人已停用",
                old_value={"status": bot_creation.status, "token_status": bot_creation.token_status}
            )

            await query.edit_message_text(
                "🗑️ <b>BOT已删除/停用，历史数据已保留。</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_creation.instance_id, scene))]
                ])
            )
        else:
            await log_repo.create_log(
                bot_id=bot_creation.instance_id,
                operator_user_id=user_id,
                action="delete",
                status="failed",
                message="停用机器人失败"
            )
            await query.edit_message_text("❌ 删除机器人失败")

    except Exception as e:
        logger.error(f"[BOT_MGMT] Delete bot error: {e}", exc_info=True)
        print(traceback.format_exc())
        await query.edit_message_text("❌ 删除机器人时出现错误")


async def _handle_restart(update: Update, context: ContextTypes.DEFAULT_TYPE, db, bot_creation, user_id, scene: str):
    """处理重启机器人"""
    query = update.callback_query
    repo = BotManagementRepository(db)
    log_repo = BotOperationLogRepository(db)

    await query.answer("正在重启BOT，请稍候...", show_alert=True)
    await query.edit_message_text("🔄 <b>正在重启机器人，请稍候...</b>", parse_mode="HTML")

    try:
        # 1. 设置重启中状态
        await repo.update_bot_status(bot_creation.instance_id, run_status="restarting")

        # 2. 停止当前实例
        await _stop_bot_instance(bot_creation.instance_id)

        # 3. 检测Token有效性
        token_valid, bot_info, error, verify_result = await _validate_bot_token(bot_creation.bot_token)

        if not token_valid:
            if verify_result == "invalid":
                await repo.update_bot_status(
                    bot_creation.instance_id,
                    run_status="stopped",
                    token_status="invalid",
                    last_error=error
                )
                await log_repo.create_log(
                    bot_id=bot_creation.instance_id,
                    operator_user_id=user_id,
                    action="restart",
                    status="failed",
                    message=f"Token无效: {error}"
                )
                await query.edit_message_text(
                    "❌ <b>Token无效，无法重启，请先重置令牌。</b>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_creation.instance_id, scene))]
                    ])
                )
                return

            await log_repo.create_log(
                bot_id=bot_creation.instance_id,
                operator_user_id=user_id,
                action="restart",
                status="failed",
                message=f"Token检测失败: {error}"
            )
            await query.edit_message_text(
                "⚠️ <b>Token检测失败，请稍后再试。</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_creation.instance_id, scene))]
                ])
            )
            return

        # 4. 重新启动Bot
        start_success = await _start_bot_instance(bot_creation.instance_id)

        if start_success:
            await repo.update_bot_status(
                bot_creation.instance_id,
                run_status="running",
                token_status="normal"
            )
            await log_repo.create_log(
                bot_id=bot_creation.instance_id,
                operator_user_id=user_id,
                action="restart",
                status="success",
                message="机器人重启成功"
            )
            await query.edit_message_text(
                "✅ <b>BOT重启成功</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_creation.instance_id, scene))]
                ])
            )
        else:
            await repo.update_bot_status(
                bot_creation.instance_id,
                run_status="failed"
            )
            await log_repo.create_log(
                bot_id=bot_creation.instance_id,
                operator_user_id=user_id,
                action="restart",
                status="failed",
                message="启动Bot实例失败"
            )
            await query.edit_message_text(
                "⚠️ <b>Token检测失败，请稍后再试。</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_creation.instance_id, scene))]
                ])
            )

    except Exception as e:
        logger.error(f"[BOT_MGMT] Restart bot error: {e}", exc_info=True)
        print(traceback.format_exc())
        await query.edit_message_text("❌ 重启机器人时出现错误")


async def _handle_disconnect_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str, scene: str):
    """显示断开确认页"""
    query = update.callback_query

    text = (
        "⚠️ <b>确认断开机器人？</b>\n\n"
        "断开后：\n"
        "• 机器人将暂停运行\n"
        "• 数据和到期时间保留\n"
        "• 可随时点击重启机器人恢复"
    )

    keyboard = [
        [InlineKeyboardButton("✅ 确认断开", callback_data=_build_bot_manage_callback("disconnect:confirm", bot_id, scene))],
        [InlineKeyboardButton("❌ 取消", callback_data=_build_bot_manage_callback("back", bot_id, scene))]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def _handle_disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE, db, bot_creation, user_id, scene: str):
    """执行断开机器人"""
    query = update.callback_query
    repo = BotManagementRepository(db)
    log_repo = BotOperationLogRepository(db)

    try:
        # 1. 停止Bot实例
        await _stop_bot_instance(bot_creation.instance_id)

        # 2. 更新状态为disconnected
        success = await repo.disconnect_bot(bot_creation.instance_id)

        if success:
            await log_repo.create_log(
                bot_id=bot_creation.instance_id,
                operator_user_id=user_id,
                action="disconnect",
                status="success",
                message="机器人已断开"
            )
            await query.edit_message_text(
                "⏸️ <b>BOT已断开，数据和到期时间已保留。</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_creation.instance_id, scene))]
                ])
            )
        else:
            await log_repo.create_log(
                bot_id=bot_creation.instance_id,
                operator_user_id=user_id,
                action="disconnect",
                status="failed",
                message="断开机器人失败"
            )
            await query.edit_message_text("❌ 断开机器人失败")

    except Exception as e:
        logger.error(f"[BOT_MGMT] Disconnect bot error: {e}", exc_info=True)
        print(traceback.format_exc())
        await query.edit_message_text("❌ 断开机器人时出现错误")


async def _handle_reset_token_start(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str, scene: str):
    """开始重置Token流程"""
    query = update.callback_query

    text = (
        "🔐 <b>重置令牌</b>\n\n"
        "请发送新的 Bot Token。\n\n"
        '发送"取消"可退出。'
    )

    keyboard = [[InlineKeyboardButton("❌ 取消", callback_data=_build_bot_manage_callback("back", bot_id, scene))]]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

    context.user_data["bot_mgmt_state"] = "waiting_token"
    context.user_data["bot_mgmt_bot_id"] = bot_id
    context.user_data["bot_mgmt_scene"] = scene
    context.user_data["bot_mgmt_panel_chat_id"] = query.message.chat_id if query and query.message else None
    context.user_data["bot_mgmt_panel_message_id"] = query.message.message_id if query and query.message else None


async def handle_reset_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户输入的新Token"""
    message = update.message
    if not message or not message.text:
        return

    user = update.effective_user
    if not user:
        return

    user_id = user.id
    bot_id = context.user_data.get("bot_mgmt_bot_id") or get_current_bot_id(context)
    scene = _normalize_scene(context.user_data.get("bot_mgmt_scene"))
    text = message.text.strip()

    # 检查状态
    if context.user_data.get("bot_mgmt_state") != "waiting_token":
        return

    # 取消操作
    if text == "取消":
        clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")
        await message.reply_text(
            "已取消重置Token操作",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_id, scene))]
            ])
        )
        return

    try:
        async with get_db_session() as db:
            repo = BotManagementRepository(db)
            log_repo = BotOperationLogRepository(db)
            bot_creation = await repo.get_bot_creation(bot_id)

            if not bot_creation:
                await message.reply_text("未找到机器人信息")
                clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")
                return

            # 权限检查
            if not _is_bot_owner_or_super_admin(user_id, bot_creation):
                await message.reply_text("⚠️ 无权限访问")
                clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")
                return

            # 1. 校验Token格式
            if ":" not in text or len(text) <= 20 or not text.split(":", 1)[0].isdigit():
                await message.reply_text(
                    "❌ Token格式不正确。\n\n"
                    '请重新发送正确的 Bot Token，或发送"取消"退出。'
                )
                return

            # 2. 调用getMe验证
            token_valid, bot_info, error, verify_result = await _validate_bot_token(text)
            print(
                f"[BOT_TOKEN_RESET_INPUT] user_id={user_id} bot_id={bot_id} "
                f"token_masked={_mask_token(text)} verify_result={verify_result}"
            )

            if not token_valid:
                await message.reply_text(
                    f"❌ Token无效，请重新发送正确的Bot Token。\n\n"
                    f"错误信息：{error}\n\n"
                    '发送"取消"可退出。'
                )
                return

            # 3. 验证成功，执行重置
            old_token = bot_creation.bot_token
            old_username = bot_creation.bot_username
            old_name = bot_creation.bot_name

            # 停止旧Bot实例
            await _stop_bot_instance(bot_creation.instance_id)

            # 更新Token信息
            new_username = bot_info.get("username", "")
            new_name = bot_info.get("first_name", "")

            success = await repo.update_bot_token(
                bot_creation.instance_id,
                text,
                new_username,
                new_name
            )

            if success:
                # 重新启动Bot
                await _start_bot_instance(bot_creation.instance_id)

                # 写入操作日志
                await log_repo.create_log(
                    bot_id=bot_creation.instance_id,
                    operator_user_id=user_id,
                    action="reset_token",
                    status="success",
                    message="Token重置成功",
                    old_value={"username": old_username, "name": old_name},
                    new_value={"username": new_username, "name": new_name}
                )

                # 清除状态
                clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")

                await message.reply_text(
                    "✅ <b>Token重置成功！</b>\n\n"
                    "BOT已重新启动，所有数据和到期时间保持不变。",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_creation.instance_id, scene))]
                    ])
                )
            else:
                await log_repo.create_log(
                    bot_id=bot_creation.instance_id,
                    operator_user_id=user_id,
                    action="reset_token",
                    status="failed",
                    message="更新Token失败"
                )
                await message.reply_text("❌ Token重置失败")
                clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")

    except Exception as e:
        logger.error(f"[BOT_MGMT] Reset token error: {e}", exc_info=True)
        print(traceback.format_exc())
        await message.reply_text("❌ 重置Token时出现错误")
        clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")


async def _get_transfer_admins(db, bot_id: str, owner_id: int | None = None):
    """转移所属候选人只来自当前 bot_id 的 admins 表，并同步到 bot_admins 供角色切换使用。"""
    query = select(Admin).where(
        and_(
            Admin.bot_id == bot_id,
            Admin.is_active.is_(True),
        )
    ).order_by(Admin.created_at.desc())
    result = await db.execute(query)
    admins = result.scalars().all()
    if owner_id:
        admins = [admin for admin in admins if int(admin.user_id) != int(owner_id)]

    bot_admin_repo = BotAdminRepository(db)
    for admin in admins:
        await bot_admin_repo.create_or_update_admin(
            bot_id=bot_id,
            user_id=admin.user_id,
            role="admin",
            username=admin.username,
            first_name=admin.first_name,
        )
    return admins


async def _get_transfer_admin(db, bot_id: str, user_id: int):
    query = select(Admin).where(
        and_(
            Admin.bot_id == bot_id,
            Admin.user_id == user_id,
            Admin.is_active.is_(True),
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _handle_transfer_start(update: Update, context: ContextTypes.DEFAULT_TYPE, db, bot_id: str, scene: str, page: int = 1):
    """开始转移所属权 - 显示管理员列表"""
    query = update.callback_query
    bot_creation = await BotManagementRepository(db).get_bot_creation(bot_id)
    owner_id = int(getattr(bot_creation, "telegram_id", 0) or 0)
    admins = await _get_transfer_admins(db, bot_id, owner_id)

    if not admins:
        await query.edit_message_text(
            '⚠️ 当前BOT暂无可转移管理员。\n'
            '请先在“加管理员”中添加管理员后再进行转移。',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_id, scene))]
            ])
        )
        return

    page_size = 8
    total_pages = max(1, (len(admins) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start_index = (page - 1) * page_size
    current_admins = admins[start_index:start_index + page_size]

    keyboard = []
    for admin in current_admins:
        display_name = admin.first_name or admin.username or str(admin.user_id)
        keyboard.append([
            InlineKeyboardButton(
                f"👤 {display_name} ({admin.user_id})",
                callback_data=_build_bot_manage_callback("transfer:select", bot_id, scene, [admin.user_id, page])
            )
        ])

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=_build_bot_manage_callback("transfer", bot_id, scene, [page - 1])))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("➡️ 下一页", callback_data=_build_bot_manage_callback("transfer", bot_id, scene, [page + 1])))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_id, scene))])

    text = (
        "➡️ <b>转移所属</b>\n\n"
        "请选择需要转移的管理员：\n\n"
        f"第 {page}/{total_pages} 页"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def _handle_transfer_select(update: Update, context: ContextTypes.DEFAULT_TYPE, db, bot_id: str, scene: str, new_owner_id: int | None, page: int = 1):
    """选择管理员后显示确认页"""
    query = update.callback_query

    if not new_owner_id:
        await query.edit_message_text("参数错误")
        return

    new_owner = await _get_transfer_admin(db, bot_id, new_owner_id)

    if not new_owner:
        await query.edit_message_text("管理员不存在")
        return

    # 获取当前owner
    admin_repo = BotAdminRepository(db)
    current_owner = await admin_repo.get_owner(bot_id)
    bot_creation = await BotManagementRepository(db).get_bot_creation(bot_id)
    old_owner_id = current_owner.user_id if current_owner else int(getattr(bot_creation, "telegram_id", 0) or 0)

    await admin_repo.create_or_update_admin(
        bot_id=bot_id,
        user_id=new_owner.user_id,
        role="admin",
        username=new_owner.username,
        first_name=new_owner.first_name,
    )

    # 存储到context供确认使用
    context.user_data["transfer_new_owner_id"] = new_owner_id
    context.user_data["transfer_old_owner_id"] = old_owner_id

    new_owner_name = new_owner.first_name or new_owner.username or str(new_owner.user_id)

    text = (
        "⚠️ <b>确认转移BOT所属权？</b>\n\n"
        f"当前所属用户：<code>{old_owner_id}</code>\n"
        f"新所属用户：<code>{new_owner_id}</code> ({html.escape(new_owner_name)})\n\n"
        "转移后：\n"
        "• 新用户将成为 Bot 创建者\n"
        "• 原用户将失去 owner 权限\n"
        "• 原 owner 自动降级为管理员\n"
        "• 到期时间保持不变\n"
        "• Token 保持不变\n"
        "• 数据保持不变"
    )

    keyboard = [
        [InlineKeyboardButton("✅ 确认转移", callback_data=_build_bot_manage_callback("transfer:confirm", bot_id, scene, [new_owner_id]))],
        [InlineKeyboardButton("❌ 取消", callback_data=_build_bot_manage_callback("transfer", bot_id, scene, [page]))]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def _handle_transfer_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, db, bot_id: str, scene: str, new_owner_id: int | None, user_id: int):
    """确认转移所属权"""
    query = update.callback_query
    if not new_owner_id:
        await query.edit_message_text("参数错误")
        return

    # 从context获取旧owner ID
    old_owner_id = context.user_data.get("transfer_old_owner_id", int(getattr((await BotManagementRepository(db).get_bot_creation(bot_id)), "telegram_id", 0) or 0))

    try:
        admin_repo = BotAdminRepository(db)
        bot_repo = BotManagementRepository(db)
        log_repo = BotOperationLogRepository(db)
        target_admin = await _get_transfer_admin(db, bot_id, new_owner_id)
        if not target_admin:
            await query.edit_message_text("管理员不存在")
            return

        # 1. 转移所有权（更新bot_admins表）
        transfer_success = await admin_repo.transfer_ownership(bot_id, old_owner_id, new_owner_id)

        if not transfer_success:
            await query.edit_message_text("❌ 转移所有权失败")
            return

        # 2. 更新BotCreation的super_admin_id
        await bot_repo.update_owner(bot_id, new_owner_id)

        # 3. 写入操作日志
        await log_repo.create_log(
            bot_id=bot_id,
            operator_user_id=user_id,
            action="transfer_owner",
            status="success",
            message=f"所有权从 {old_owner_id} 转移到 {new_owner_id}",
            old_value={"owner_id": old_owner_id},
            new_value={"owner_id": new_owner_id}
        )

        # 4. 清除状态
        clear_state(context, "bot_mgmt_state", "bot_mgmt_bot_id", "bot_mgmt_scene", "bot_mgmt_panel_chat_id", "bot_mgmt_panel_message_id")
        context.user_data.pop("transfer_new_owner_id", None)
        context.user_data.pop("transfer_old_owner_id", None)
        context.user_data.pop("_bot_id_override", None)

        # 5. 通知原owner（当前用户）
        await query.edit_message_text(
            f"✅ <b>所属权转移成功！</b>\n\n"
            f"新的所属用户ID：<code>{new_owner_id}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ 返回", callback_data=_build_bot_manage_callback("back", bot_id, scene))]
            ])
        )

        # 6. 通知新owner
        try:
            await context.bot.send_message(
                chat_id=new_owner_id,
                text=(
                    "🎉 <b>你已成为该机器人的新创建者。</b>\n\n"
                    "你现在拥有：\n"
                    "• Bot 管理权限\n"
                    "• Token 管理权限\n"
                    "• 功能设置权限\n"
                    "• 续费管理权限"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"[BOT_MGMT] Failed to notify new owner: {e}")

    except Exception as e:
        logger.error(f"[BOT_MGMT] Transfer ownership error: {e}", exc_info=True)
        print(traceback.format_exc())
        await query.edit_message_text("❌ 转移所属权时出现错误")


# ==================== 辅助函数 ====================

async def _validate_bot_token(token: str) -> tuple[bool, dict | None, str | None, str]:
    """
    验证Bot Token有效性
    返回: (是否有效, bot信息, 错误信息)
    """
    try:
        from telegram import Bot
        # 解密token（如果是加密的）
        plain_token = token
        if token and not token.startswith("bot"):
            try:
                plain_token = token_encryptor.decrypt_from_base64(token)
            except Exception:
                plain_token = token

        bot = Bot(token=plain_token)
        bot_info = await bot.get_me()
        return True, {
            "id": bot_info.id,
            "username": bot_info.username,
            "first_name": bot_info.first_name
        }, None, "valid"

    except Exception as e:
        error_str = str(e).lower()
        # 只有Unauthorized/invalid token才标记为invalid
        if "unauthorized" in error_str or "invalid token" in error_str:
            return False, None, "Token未授权或无效", "invalid"
        elif "timeout" in error_str or "timed out" in error_str:
            return False, None, "网络超时，请稍后重试", "temporary"
        elif "too many requests" in error_str or "429" in error_str:
            return False, None, "请求过于频繁，请稍后重试", "temporary"
        else:
            return False, None, f"检测失败: {str(e)}", "temporary"


async def _stop_bot_instance(instance_id: str) -> bool:
    """停止Bot实例"""
    try:
        from ..services.bot_instance_manager import bot_instance_manager
        logger.info(f"[BOT_MGMT] Stopping bot instance: {instance_id}")
        return await bot_instance_manager.stop_bot_instance(instance_id)
    except Exception as e:
        logger.error(f"[BOT_MGMT] Stop bot error: {e}")
        print(traceback.format_exc())
        return False


async def _start_bot_instance(instance_id: str) -> bool:
    """启动Bot实例"""
    try:
        from ..services.bot_instance_manager import bot_instance_manager
        async with get_db_session() as db:
            repo = BotManagementRepository(db)
            bot_creation = await repo.get_bot_creation(instance_id)
            if not bot_creation:
                return False
            logger.info(f"[BOT_MGMT] Starting bot instance: {instance_id}")
            return await bot_instance_manager.start_bot_instance(bot_creation)
    except Exception as e:
        logger.error(f"[BOT_MGMT] Start bot error: {e}")
        print(traceback.format_exc())
        return False
