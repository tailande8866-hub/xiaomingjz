from types import SimpleNamespace

import pytest

from src.handlers import usdt_monitor


class DummyMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class DummyContext:
    def __init__(self):
        self.user_data = {"waiting_for": usdt_monitor.USDT_WAITING_ADDRESS, "usdt_bot_id": "bot-1"}


@pytest.mark.asyncio
async def test_address_input_rejects_invalid_tron_address():
    message = DummyMessage("bad-address")
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=123))
    context = DummyContext()

    await usdt_monitor.handle_address_input(update, context)

    assert "地址格式不正确" in message.replies[0][0]
    assert context.user_data["waiting_for"] == usdt_monitor.USDT_WAITING_ADDRESS


@pytest.mark.asyncio
async def test_address_input_saves_valid_address(monkeypatch):
    calls = {}

    async def fake_add_watched_address(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(id=10)

    monkeypatch.setattr(
        usdt_monitor.wallet_monitor_service,
        "add_watched_address",
        fake_add_watched_address,
    )

    address = "T" + "A" * 33
    message = DummyMessage(f"{address} 财务钱包")
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=123))
    context = DummyContext()

    await usdt_monitor.handle_address_input(update, context)

    assert calls["bot_id"] == "bot-1"
    assert calls["user_id"] == 123
    assert calls["group_id"] == 0
    assert calls["address"] == address
    assert calls["alias"] == "财务钱包"
    assert "waiting_for" not in context.user_data
    assert "已添加监听地址" in message.replies[0][0]
