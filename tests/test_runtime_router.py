from types import SimpleNamespace
from pathlib import Path
import re

from src.core.runtime_router import RuntimeRouter
from src.handlers.menu_adapter import register_menu_adapters


class DummyTenantContext:
    def __init__(self, enabled_features=None, permissions=None):
        self.enabled_features = set(enabled_features or [])
        self.permissions = set(permissions or [])

    def is_feature_enabled(self, feature_flag):
        return feature_flag in self.enabled_features

    def has_permission(self, permission):
        return permission in self.permissions


class DummyCallbackQuery:
    def __init__(self, data):
        self.data = data


class DummyContext:
    def __init__(self):
        self.user_data = {}


def test_feature_flag_uses_module_from_versioned_route():
    router = RuntimeRouter()
    tenant = DummyTenantContext(enabled_features={"enable_settings"})

    assert router._check_feature_flag("v1:settings:main", tenant) is True
    assert router._check_feature_flag("v1:broadcast:send", tenant) is False


def test_permission_uses_module_action_from_versioned_route():
    router = RuntimeRouter()
    tenant = DummyTenantContext(permissions={"can_settings"})

    assert router._check_permission("v1:settings:main", tenant) is True
    assert router._check_permission("v1:broadcast:send", tenant) is False


def test_legacy_callback_route_upgrades_with_params():
    router = RuntimeRouter()
    update = SimpleNamespace(callback_query=DummyCallbackQuery("settings:main:extra"), message=None)
    context = DummyContext()

    assert router._determine_route(update, context) == "v1:settings:main"
    assert context.user_data["callback_params"] == ["extra"]


def test_callback_params_are_cleared_when_next_route_has_no_params():
    router = RuntimeRouter()
    context = DummyContext()
    context.user_data["callback_params"] = ["old"]
    update = SimpleNamespace(callback_query=DummyCallbackQuery("v1:usdt:list"), message=None)

    assert router._determine_route(update, context) == "v1:usdt:list"
    assert "callback_params" not in context.user_data


def test_ui_schema_registry_has_no_duplicate_literal_routes():
    registry_path = Path(__file__).resolve().parents[1] / "src" / "core" / "ui_schema_registry.py"
    source = registry_path.read_text(encoding="utf-8")
    routes = re.findall(r'runtime_router\.register_route\("([^"]+)"', source)

    duplicates = {route for route in routes if routes.count(route) > 1}

    assert duplicates == set()


def test_menu_adapter_does_not_override_existing_routes():
    router = RuntimeRouter()

    async def existing_handler(update, context, tenant_context):
        return None

    router.register_route("v1:settings:main", existing_handler)

    register_menu_adapters(router)

    assert router.routes["v1:settings:main"] is existing_handler
