import logging
import os
import traceback
from typing import Any

logger = logging.getLogger(__name__)


def safe_session_label(db: Any = None) -> str:
    if db is None:
        return "none"
    return f"{type(db).__name__}@{id(db)}"


def bool_label(value: Any) -> str:
    if value is None:
        return "unknown"
    return str(bool(value))


def format_rate_config(group: Any = None, exchange_rate: Any = None, fee_rate: Any = None) -> str:
    group_exchange_rate = getattr(group, "exchange_rate", None) if group is not None else None
    group_fee_rate = getattr(group, "fee_rate", None) if group is not None else None
    return (
        f"group_exchange_rate={group_exchange_rate}, "
        f"group_fee_rate={group_fee_rate}, "
        f"effective_exchange_rate={exchange_rate}, "
        f"effective_fee_rate={fee_rate}"
    )


def log_accounting_debug(
    *,
    update,
    context,
    handler: str,
    bot_id: str | None = None,
    tenant_id: str | None = None,
    group: Any = None,
    operator_found: Any = None,
    permission_pass: Any = None,
    db: Any = None,
    rate_config: str | None = None,
    error_traceback: str | None = None,
) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "message", None)
    text = getattr(message, "text", None)
    app = getattr(context, "application", None)
    app_bot_data = getattr(app, "bot_data", {}) or {}
    resolved_bot_id = bot_id or app_bot_data.get("bot_id")
    resolved_tenant_id = tenant_id or resolved_bot_id
    is_main_bot = os.environ.get("IS_MAIN_BOT", "true").lower() == "true"

    logger.info(
        "[ACCOUNTING_DEBUG]\n"
        "is_main_bot=%s\n"
        "bot_id=%s\n"
        "tenant_id=%s\n"
        "chat_id=%s\n"
        "user_id=%s\n"
        "text=%s\n"
        "handler=%s\n"
        "group_config_found=%s\n"
        "group_id=%s\n"
        "operator_found=%s\n"
        "rate_config=%s\n"
        "permission_pass=%s\n"
        "db_session=%s\n"
        "error_traceback=%s",
        is_main_bot,
        resolved_bot_id,
        resolved_tenant_id,
        getattr(chat, "id", None),
        getattr(user, "id", None),
        text,
        handler,
        bool_label(group),
        getattr(group, "group_id", None),
        bool_label(operator_found),
        rate_config or "unknown",
        bool_label(permission_pass),
        safe_session_label(db),
        error_traceback or "",
    )


def get_effective_accounting_bot_id(context, current_bot_id: str | None = None) -> str:
    raw_bot_id = current_bot_id
    if not raw_bot_id:
        try:
            from ...utils.bot_id_middleware import get_current_bot_id
            raw_bot_id = get_current_bot_id(context)
        except Exception:
            raw_bot_id = None

    if raw_bot_id:
        return raw_bot_id

    is_main_bot = os.environ.get("IS_MAIN_BOT", "true").lower() == "true"
    return "main_bot" if is_main_bot else "unknown_bot"


def log_accounting_trace(
    *,
    update,
    context,
    handler: str,
    bot_id: str | None = None,
    effective_bot_id: str | None = None,
    group: Any = None,
    operator_found: Any = None,
    tenant_query_bot_id: str | None = None,
    error_traceback: str | None = None,
) -> None:
    chat = getattr(update, "effective_chat", None)
    user = getattr(update, "effective_user", None)
    message = getattr(update, "message", None)
    text = getattr(message, "text", None)
    is_main_bot = os.environ.get("IS_MAIN_BOT", "true").lower() == "true"

    logger.info(
        "[ACCOUNTING_TRACE]\n"
        "is_main_bot=%s\n"
        "bot_id=%s\n"
        "effective_bot_id=%s\n"
        "chat_id=%s\n"
        "user_id=%s\n"
        "text=%s\n"
        "handler=%s\n"
        "group_config_found=%s\n"
        "operator_found=%s\n"
        "tenant_query_bot_id=%s\n"
        "error_traceback=%s",
        is_main_bot,
        bot_id,
        effective_bot_id,
        getattr(chat, "id", None),
        getattr(user, "id", None),
        text,
        handler,
        bool_label(group),
        bool_label(operator_found),
        tenant_query_bot_id or effective_bot_id or bot_id,
        error_traceback or "",
    )


def current_traceback() -> str:
    return "".join(traceback.format_exc())
